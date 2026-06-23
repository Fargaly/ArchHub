"""SIGNED-IN CLOUD GOES FIRST + DEAD-CLI NEVER BLOCKS (founder 2026-06-23:
'the first AI call is slow').

Root cause: the founder has the `claude` + `codex` CLIs installed but SIGNED
OUT. The auto router preferred claude_cli then codex_cli BEFORE everything;
claude_cli 401s fast but codex_cli HANGS to its subprocess timeout — so the
user's FIRST turn stalled before the router reached the working archhub_cloud
free model.

These tests lock the fix:

1) BOUNDED CLI TIMEOUTS — the claude_cli + codex_cli subprocess ceilings are
   bounded to ~12 s so a hung/dead CLI fails fast and the router routes onward
   in the same call.
2) CLOUD-FIRST-WHEN-SIGNED-IN — auto + signed-in cloud + an UNPROVEN CLI ⇒
   _route prefers archhub_cloud ahead of claude_cli / codex_cli.
3) NO REGRESSION — an explicit `claude_cli:...` pick still routes to claude_cli;
   a CLI proven-working this session stays ahead of cloud; signed-out-everything
   still raises the honest 'No LLM configured'; a BYO key still wins.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import llm_router as llm_router_mod  # noqa: E402
from llm_router import LLMRouter, ROUTE_AUTO  # noqa: E402


# --- shared fakes ----------------------------------------------------------


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


# --- 1) bounded CLI subprocess timeouts ------------------------------------


class TestBoundedCliTimeouts:
    def test_codex_cli_timeout_is_bounded(self):
        import llm_providers.codex_cli_client as cx
        # ~12 s ceiling — a dead/hung codex must never burn 60 s before the
        # router routes onward.
        assert cx._TIMEOUT_S <= 12

    def test_claude_cli_timeout_is_bounded(self):
        import llm_providers.claude_cli_client as cc
        # ~12 s ceiling — a hung claude subprocess must never hold the user
        # for minutes (was 300 s) before the fallback chain moves on.
        assert cc._TIMEOUT_S <= 12


# --- 2) cloud-first when signed-in + unproven CLI --------------------------


class TestCloudFirstWhenSignedIn:
    @pytest.mark.parametrize("prompt", [
        "Could you draft a longer paragraph of prose for me please.",  # default
        "create a wall in revit on level 1",                            # modeling
        "explain why this schedule is wrong",                          # analysis
        "hi",                                                          # short
    ])
    def test_signed_in_cloud_beats_unproven_cli(self, prompt):
        r = _router()
        # Signed-in cloud AND both CLIs installed but UNPROVEN this session.
        r.configured_providers = lambda **k: [
            "archhub_cloud", "claude_cli", "codex_cli"]
        prov, model, note = r._route(
            [{"role": "user", "content": prompt}], ROUTE_AUTO)
        assert prov == "archhub_cloud", (prompt, prov, note)
        assert model == "auto"

    def test_cli_without_cloud_still_routes_to_cli(self):
        # Cloud NOT signed in ⇒ the cloud-first guard is skipped and the CLI
        # is the primary (unchanged behaviour for a CLI-only user).
        r = _router()
        r.configured_providers = lambda **k: ["claude_cli"]
        prov, model, _note = r._route(
            [{"role": "user", "content": "hi"}], ROUTE_AUTO)
        assert prov == "claude_cli"


# --- 3) no regressions -----------------------------------------------------


class TestNoRegression:
    def test_explicit_claude_cli_pick_is_honoured(self):
        # An explicit provider:model selection still routes to claude_cli even
        # when cloud is signed in — the explicit-pick branch returns before
        # the cloud-first guard is ever reached.
        r = _router()
        r.configured_providers = lambda **k: ["archhub_cloud", "claude_cli"]
        prov, model, _note = r._route(
            [{"role": "user", "content": "hi"}], "claude_cli:sonnet")
        assert prov == "claude_cli"
        assert model == "sonnet"

    def test_explicit_codex_cli_pick_is_honoured(self):
        r = _router()
        r.configured_providers = lambda **k: ["archhub_cloud", "codex_cli"]
        prov, model, _note = r._route(
            [{"role": "user", "content": "hi"}], "codex_cli:auto")
        assert prov == "codex_cli"
        assert model == "auto"

    def test_proven_cli_stays_ahead_of_cloud(self):
        # A user whose CLI ACTUALLY works this session is not regressed: the
        # proven CLI keeps priority over the cloud-first default.
        r = _router()
        r.configured_providers = lambda **k: ["archhub_cloud", "claude_cli"]
        r._clear_signed_out("claude_cli")   # records proven-ok
        prov, _model, _note = r._route(
            [{"role": "user", "content": "hi"}], ROUTE_AUTO)
        assert prov == "claude_cli"

    def test_byo_key_still_wins_over_cloud_and_cli(self):
        # BYO anthropic key + signed-in cloud + unproven CLI: the cloud-first
        # guard fires (cloud ahead of the CLI), but a modeling/analysis/default
        # prompt with a BYO key present still resolves to the BYO provider —
        # the cloud-first guard only reorders cloud vs the CLIs, never demotes
        # a BYO key. (Here the CLI is absent so we land in the heuristic
        # blocks where the BYO key leads.)
        r = _router()
        r.configured_providers = lambda **k: ["anthropic", "archhub_cloud"]
        prov, _model, _note = r._route(
            [{"role": "user", "content": "create a wall in revit"}], ROUTE_AUTO)
        assert prov == "anthropic"

    def test_signed_out_everything_raises_honest_no_llm(self):
        r = _router()
        r.configured_providers = lambda **k: []
        with pytest.raises(RuntimeError, match="No LLM configured"):
            r._route([{"role": "user", "content": "hello there friend"}],
                     ROUTE_AUTO)
