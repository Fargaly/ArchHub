"""LOCAL-FIRST routing (founder 2026-06-22: 'I have Claude Code + Codex
installed but the composer gives nothing back').

Root cause: a turn with NO usable BYO key routed to the managed ArchHub
Cloud proxy, which answered HTTP 402 `byo_key_required`, and the turn did
NOT fall through to an available local provider (claude_cli / codex_cli /
ollama / lmstudio) — it dead-ended (hung / empty).

These tests lock the unblocker:

A) 402 / byo_key_required is classified as auth-or-quota → 'skip to next
   provider', never a fatal turn error.
B) When the explicit pick names a cloud provider that ISN'T usable, _route
   falls through to an available LOCAL provider.
C) The auto Default block prefers a running LOCAL provider OVER the managed
   cloud fallback (avoid the 402 round-trip entirely).
D) End-to-end: NO BYO key + a stub local provider available ⇒ complete()
   routes to the local provider and returns its real reply (not a 402).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from llm_router import (  # noqa: E402
    LLMRouter,
    _looks_like_auth_or_quota,
)


# --- shared fakes (mirror test_llm_router_primary_and_empty) ---------------


class _FakeManager:
    entries = []


class _FakeToolEngine:
    def __init__(self, schemas):
        self.manager = _FakeManager()
        self._schemas = schemas

    def tool_schemas_for(self, provider):
        return list(self._schemas)

    def invoke(self, *a, **k):
        return {"status": "ok"}


def _router(schemas=None):
    r = LLMRouter(_FakeToolEngine(schemas or []))
    r._build_system_prompt = lambda: "SYS"
    return r


class _FakeClient:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def stream_completion(self, *, model, system, messages, tools,
                          on_chunk, **kwargs):
        self.calls += 1
        step = self._script.pop(0) if self._script else {
            "type": "final", "text": "", "tool_calls": []}
        if isinstance(step, Exception):
            raise step
        txt = step.get("text", "")
        if txt and on_chunk:
            on_chunk(txt)
        return {"type": step.get("type", "final"), "text": txt,
                "tool_calls": step.get("tool_calls", []), "usage": None}


# --- A) 402 / byo_key_required is a skip-to-next signal --------------------


class TestByoKey402Classification:
    def test_numeric_402_is_auth_or_quota(self):
        ex = Exception("Error code: 402 - {'error': {'message': "
                       "'byo_key_required'}}")
        assert _looks_like_auth_or_quota(ex) is True

    def test_worded_byo_key_required_without_code_is_auth_or_quota(self):
        # Some bodies strip the numeric code; the worded form must STILL
        # classify so the chain skips to the next provider, not raises.
        assert _looks_like_auth_or_quota(Exception("byo_key_required")) is True
        assert _looks_like_auth_or_quota(
            Exception("bring your own key to use this model")) is True
        assert _looks_like_auth_or_quota(
            Exception("no managed quota remaining")) is True

    def test_router_is_auth_error_matches_byo_key(self):
        r = _router()
        assert r._is_auth_error(
            "archhub_cloud", Exception("402 byo_key_required")) is True


# --- B) explicit cloud pick falls through to local when unusable -----------


class TestExplicitPickFallsThroughToLocal:
    def test_signed_out_cloud_pick_routes_to_local_claude_cli(self):
        r = _router()
        # archhub_cloud was explicitly picked but PROVEN dead this session
        # (it 402'd → marked signed-out). claude_cli IS available.
        r._mark_signed_out("archhub_cloud", reason="402 byo_key_required")
        r.configured_providers = lambda **k: ["claude_cli"]
        prov, model, note = r._route(
            [{"role": "user", "content": "yo"}], "archhub_cloud:auto")
        assert prov == "claude_cli"
        assert model == "sonnet"
        assert "archhub_cloud unavailable" in note

    def test_blocked_cloud_pick_routes_to_local(self):
        r = _router()
        # archhub_cloud blocked after a recent 4xx; codex_cli available.
        r.block_provider("archhub_cloud", "402 byo_key_required")
        r.configured_providers = lambda **k: ["codex_cli"]
        prov, model, note = r._route(
            [{"role": "user", "content": "yo"}], "archhub_cloud:auto")
        assert prov == "codex_cli"
        assert "archhub_cloud unavailable" in note

    def test_usable_explicit_pick_is_honoured(self):
        r = _router()
        # A normal model-picker selection: not blocked, not signed-out →
        # honoured verbatim (back-compat — never silently redirected).
        prov, model, note = r._route(
            [{"role": "user", "content": "yo"}],
            "anthropic:claude-sonnet-4-6")
        assert prov == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_dead_cloud_pick_no_local_falls_through_to_auto(self):
        # archhub_cloud picked but PROVEN dead; only a usable BYO key exists,
        # no local. Fall through to auto heuristics (which pick the configured
        # cloud key), never dead-end on the proven-dead pick.
        r = _router()
        r._mark_signed_out("archhub_cloud", reason="402")
        r.configured_providers = lambda **k: ["anthropic"]
        prov, model, note = r._route(
            [{"role": "user", "content": "draft a longer paragraph please"}],
            "archhub_cloud:auto")
        assert prov == "anthropic"


# --- C) auto Default prefers local over managed cloud ----------------------


class TestAutoPrefersLocalOverManagedCloud:
    def test_ollama_beats_archhub_cloud_in_default(self):
        r = _router()
        # Long, non-keyword text → falls to the Default block. Both a
        # managed cloud AND a local ollama are "configured".
        r.configured_providers = lambda **k: ["archhub_cloud", "ollama"]
        r._pick_ollama_model = lambda task: "llama3.1:8b"
        prov, model, note = r._route(
            [{"role": "user",
              "content": "Could you draft a longer paragraph of prose for me."}],
            "auto")
        assert prov == "ollama"
        assert model == "llama3.1:8b"


# --- D) end-to-end: no BYO key + local available ⇒ real local reply --------


class TestEndToEndLocalFirst:
    def test_signed_in_cloud_then_dead_cli_returns_cloud_reply(self):
        """The headline scenario, post-2026-06-23 (signed-in cloud goes
        FIRST): cloud is signed in AND a (signed-out / hung) claude_cli is
        installed. The first AI call must hit the working cloud free model
        and return its reply — NOT stall behind the dead CLI.

        This is the inverse of the old local-first ordering: the founder has
        claude/codex installed but signed out, so the CLI must be the
        FALLBACK, not the primary. cloud first = fast + clean."""
        r = _router(schemas=[])
        local = _FakeClient([{"type": "final",
                              "text": "real reply from local Claude Code"}])
        cloud = _FakeClient([{"type": "final",
                              "text": "reply from ArchHub Cloud free model"}])

        def fake_get_client(provider):
            if provider == "claude_cli":
                return local
            if provider == "archhub_cloud":
                return cloud
            raise RuntimeError(f"no client for {provider}")

        r._get_client = fake_get_client
        # Both are 'configured'; the REAL _route runs (cloud-first when
        # signed in + no CLI proven this session), so cloud answers and the
        # dead CLI is never reached.
        r.configured_providers = lambda **k: ["archhub_cloud", "claude_cli"]

        resp = r.complete(history=[{"role": "user", "content": "hi"}],
                          model="auto")
        assert resp.text == "reply from ArchHub Cloud free model"
        assert local.calls == 0   # the (dead) CLI was never reached

    def test_proven_cli_stays_ahead_of_cloud(self):
        """No regression for a user whose CLI ACTUALLY works: once claude_cli
        has returned a successful completion this session it is proven-ok, so
        a later auto turn keeps routing to the CLI even though cloud is signed
        in. cloud-first is only the default for an UNPROVEN CLI."""
        r = _router(schemas=[])
        local = _FakeClient([
            {"type": "final", "text": "first CLI reply"},
            {"type": "final", "text": "second CLI reply"},
        ])
        cloud = _FakeClient([{"type": "final", "text": "cloud reply"}])

        def fake_get_client(provider):
            if provider == "claude_cli":
                return local
            if provider == "archhub_cloud":
                return cloud
            raise RuntimeError(f"no client for {provider}")

        r._get_client = fake_get_client
        r.configured_providers = lambda **k: ["archhub_cloud", "claude_cli"]
        # Simulate the CLI having already proven it works this session.
        r._clear_signed_out("claude_cli")
        assert r.is_provider_proven_ok("claude_cli") is True

        prov, model, _note = r._route(
            [{"role": "user", "content": "hi"}], "auto")
        assert prov == "claude_cli"   # proven CLI keeps priority over cloud

    def test_cloud_402_then_local_fallback_when_cloud_picked_first(self):
        """Belt-and-braces: if cloud IS reached first (e.g. an explicit
        cloud pick that was usable at route time but 402s at call time),
        the 402 is treated as skip-to-next and the local provider answers —
        no fatal raise, no empty turn."""
        r = _router(schemas=[])
        local = _FakeClient([{"type": "final", "text": "local saved the turn"}])
        cloud = _FakeClient([
            Exception("Error code: 402 - byo_key_required")])

        def fake_get_client(provider):
            if provider == "claude_cli":
                return local
            if provider == "archhub_cloud":
                return cloud
            raise RuntimeError(f"no client for {provider}")

        r._get_client = fake_get_client
        r.configured_providers = lambda **k: ["archhub_cloud", "claude_cli"]

        # Force cloud first, then let the auto re-route reach local.
        calls = {"n": 0}

        def fake_route(history, model):
            calls["n"] += 1
            if calls["n"] == 1:
                return "archhub_cloud", "auto", "forced cloud first"
            return ("claude_cli", "sonnet", "local fallback")

        r._route = fake_route

        statuses = []
        resp = r.complete(history=[{"role": "user", "content": "hi"}],
                          model="auto", on_status=statuses.append)
        assert resp.text == "local saved the turn"
        assert cloud.calls == 1   # cloud tried once (402)
        assert local.calls == 1   # local answered
