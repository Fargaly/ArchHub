"""Desktop provider-error fixes (founder archhub.log recurring errors,
branch fix/desktop-provider-errors).

The live archhub.log showed three recurring, EXPECTED provider failures being
logged as ERROR + an un-callable NVIDIA model 404-ing in a loop:

  - [nvidia] NotFoundError 404 Function-not-found-for-account on model
    nvidia/llama-3.1-nemotron-ultra-253b-v1  → the nvidia provider picked an
    un-callable catalog model.
  - [anthropic] 401 invalid x-api-key (stale key in secrets.dat).
  - [claude_cli] 401 / [codex_cli] 60s timeout (signed out).

These pins lock the ROOT fixes (not suppression):

1. NVIDIA default/auto resolves to the known-callable meta/llama-3.3-70b-instruct
   (the model the cloud serves), never the un-callable nemotron-253b. A 404
   function-not-found marks THAT model bad + routes onward, never repeating the
   identical 404.
2. EXPECTED provider failures (auth 401/403, 404 not-found, CLI timeout,
   signed-out/blocked) log at WARNING; genuine unexpected exceptions stay ERROR.
3. Signed-in cloud + auto + broken (failed-this-session) non-cloud providers →
   archhub_cloud is chosen rather than re-churning the broken keyed/CLI provider.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import llm_router as llm_router_mod  # noqa: E402
from llm_router import (  # noqa: E402
    LLMRouter,
    ROUTE_AUTO,
    NVIDIA_DEFAULT_MODEL,
    KNOWN_MODELS,
    _looks_like_uncallable_model,
    _looks_like_auth_or_quota,
)


def _router():
    """Bare router — the routing/marking methods under test never touch
    self.tools, so bypass __init__ and seed only the state they read."""
    r = object.__new__(LLMRouter)
    r._clients = {}
    r._blocklist = {}
    r._block_reasons = {}
    r._signed_out = set()
    r._proven_ok = set()
    r._attempted_failed = set()
    r._bad_models = set()
    return r


# ── 1. NVIDIA MODEL ────────────────────────────────────────────────────────


class TestNvidiaCallableModel:
    def test_default_constant_is_the_cloud_served_model(self):
        assert NVIDIA_DEFAULT_MODEL == "meta/llama-3.3-70b-instruct"

    def test_catalog_head_nvidia_row_is_the_callable_model(self):
        nv = [i for i, _ in KNOWN_MODELS if i.startswith("nvidia:")]
        assert nv, "no nvidia rows"
        # FIRST nvidia row is the default the picker lands on — must be callable.
        assert nv[0] == f"nvidia:{NVIDIA_DEFAULT_MODEL}", nv

    def test_bare_nvidia_pick_resolves_to_default(self):
        r = _router()
        prov, model, _note = r._route([{"role": "user", "content": "hi"}],
                                      "nvidia")
        assert prov == "nvidia"
        assert model == NVIDIA_DEFAULT_MODEL

    def test_nvidia_auto_resolves_to_default(self):
        r = _router()
        prov, model, _note = r._route([{"role": "user", "content": "hi"}],
                                      "nvidia:auto")
        assert prov == "nvidia"
        assert model == NVIDIA_DEFAULT_MODEL

    def test_explicit_good_nvidia_model_is_honoured(self):
        r = _router()
        pick = "nvidia:deepseek-ai/deepseek-r1"
        prov, model, _note = r._route([{"role": "user", "content": "hi"}], pick)
        assert (prov, model) == ("nvidia", "deepseek-ai/deepseek-r1")

    def test_bad_nvidia_model_is_substituted_with_default(self):
        r = _router()
        bad = "nvidia/llama-3.1-nemotron-ultra-253b-v1"
        r._mark_model_bad("nvidia", bad, reason="404 Function-not-found")
        assert r.is_model_bad("nvidia", bad)
        prov, model, note = r._route([{"role": "user", "content": "hi"}],
                                     f"nvidia:{bad}")
        assert prov == "nvidia"
        assert model == NVIDIA_DEFAULT_MODEL
        assert "uncallable" in note

    def test_uncallable_classifier_matches_nvidia_404(self):
        ex = RuntimeError(
            "NotFoundError 404 Function-not-found-for-account on model "
            "nvidia/llama-3.1-nemotron-ultra-253b-v1")
        assert _looks_like_uncallable_model(ex)
        # And it is NOT mistaken for an auth/quota failure (different recovery).
        assert not _looks_like_auth_or_quota(ex)

    def test_uncallable_classifier_ignores_plain_auth(self):
        assert not _looks_like_uncallable_model(
            RuntimeError("401 invalid x-api-key"))


# ── 2. LOG LEVEL ────────────────────────────────────────────────────────────


class _FakeStreamClient:
    """Client whose stream_completion raises a chosen exception, to drive the
    auto-fallback except-block logging path in `complete`."""

    def __init__(self, exc):
        self._exc = exc

    def stream_completion(self, *a, **k):
        raise self._exc


def _router_for_complete(monkeypatch, *, provider, exc, signed_out_ok=True):
    """A router wired so `complete` routes to exactly `provider`, whose client
    raises `exc`, with every fallback drained so the loop ends after one
    logged attempt. Returns (router)."""
    r = _router()
    # Route deterministically to the target provider on every call.
    monkeypatch.setattr(r, "_route",
                        lambda hist, model: (provider, "some-model", "note"))
    monkeypatch.setattr(r, "_get_client", lambda p: _FakeStreamClient(exc))
    # _complete_once is the real method — but we don't need it to run; the
    # client raising inside it is enough. Stub it to raise like the client so
    # the except block (the unit under test) runs with the real classifiers.
    monkeypatch.setattr(r, "_complete_once",
                        lambda **kw: (_ for _ in ()).throw(exc))
    # configured_providers must be non-empty so the soft-route guard passes.
    monkeypatch.setattr(r, "configured_providers", lambda **k: [provider])
    # Quiet the block/telemetry side effects.
    monkeypatch.setattr(r, "block_provider", lambda *a, **k: None)
    return r


@pytest.mark.parametrize("exc,expect_level", [
    (RuntimeError("401 invalid x-api-key"), logging.WARNING),
    (RuntimeError("403 Forbidden"), logging.WARNING),
    (RuntimeError("404 Function-not-found-for-account on model x/y"),
     logging.WARNING),
    (RuntimeError("402 payment required byo_key_required"), logging.WARNING),
    (ValueError("totally unexpected internal explosion"), logging.ERROR),
])
def test_expected_failures_log_warning_unexpected_stay_error(
        monkeypatch, caplog, exc, expect_level):
    r = _router_for_complete(monkeypatch, provider="anthropic", exc=exc)
    caplog.set_level(logging.WARNING, logger="archhub.llm")
    with pytest.raises(Exception):
        r.complete([{"role": "user", "content": "hello there"}], ROUTE_AUTO)
    recs = [rec for rec in caplog.records
            if rec.name == "archhub.llm" and "EXCEPTION" in rec.getMessage()]
    assert recs, "no archhub.llm EXCEPTION record emitted"
    assert recs[0].levelno == expect_level, (
        f"{exc!r} logged at {recs[0].levelname}, expected "
        f"{logging.getLevelName(expect_level)}")


def test_cli_timeout_logs_warning(monkeypatch, caplog):
    exc = RuntimeError("codex CLI error: process timed out after 60s")
    r = _router_for_complete(monkeypatch, provider="codex_cli", exc=exc)
    caplog.set_level(logging.WARNING, logger="archhub.llm")
    with pytest.raises(Exception):
        r.complete([{"role": "user", "content": "hello there"}], ROUTE_AUTO)
    recs = [rec for rec in caplog.records
            if rec.name == "archhub.llm" and "EXCEPTION" in rec.getMessage()]
    assert recs and recs[0].levelno == logging.WARNING


# ── 3. CLOUD-FIRST OVER BROKEN KEYED/LOCAL ──────────────────────────────────


class TestCloudFirstOverBroken:
    def test_attempted_failed_tracked(self):
        r = _router()
        assert not r.has_provider_failed("anthropic")
        r._mark_attempted_failed("anthropic")
        assert r.has_provider_failed("anthropic")

    def test_signed_in_cloud_chosen_when_only_keyed_is_broken(self, monkeypatch):
        r = _router()
        # Cloud signed in + a stale-key anthropic still in `configured` this
        # turn, but it has FAILED this session and is not proven.
        monkeypatch.setattr(r, "configured_providers",
                            lambda **k: ["anthropic", "archhub_cloud"])
        r._mark_attempted_failed("anthropic")
        prov, model, note = r._route(
            [{"role": "user", "content": "draft a long paragraph of prose"}],
            ROUTE_AUTO)
        assert prov == "archhub_cloud", (prov, note)
        assert model == "auto"

    def test_fresh_byo_key_still_beats_cloud(self, monkeypatch):
        # No-regression: a never-failed BYO anthropic key leads over cloud.
        r = _router()
        monkeypatch.setattr(r, "configured_providers",
                            lambda **k: ["anthropic", "archhub_cloud"])
        prov, _model, _note = r._route(
            [{"role": "user", "content": "draft a long paragraph of prose"}],
            ROUTE_AUTO)
        assert prov == "anthropic"

    def test_proven_keyed_provider_still_beats_cloud(self, monkeypatch):
        # A keyed provider that failed once but later PROVED working stays
        # preferred over cloud (guard checks proven_ok too).
        r = _router()
        monkeypatch.setattr(r, "configured_providers",
                            lambda **k: ["anthropic", "archhub_cloud"])
        r._mark_attempted_failed("anthropic")
        r._proven_ok.add("anthropic")
        prov, _model, _note = r._route(
            [{"role": "user", "content": "draft a long paragraph of prose"}],
            ROUTE_AUTO)
        assert prov == "anthropic"

    def test_explicit_pick_still_honoured(self, monkeypatch):
        # No-regression: an explicit good model pick is honoured verbatim.
        r = _router()
        monkeypatch.setattr(r, "configured_providers",
                            lambda **k: ["anthropic", "archhub_cloud"])
        prov, model, _note = r._route(
            [{"role": "user", "content": "hi"}], "anthropic:claude-opus-4-7")
        assert (prov, model) == ("anthropic", "claude-opus-4-7")
