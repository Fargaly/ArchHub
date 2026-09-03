"""Zero-config CLOUD FREE DEFAULT routing (founder #64: 'desktop AI should
just work signed-in — no key, no 402').

This locks the DESKTOP half of the zero-config free model (ONE-SYSTEM — the
existing `archhub_cloud` provider + the existing `is_signed_in()` reachable
gate; no parallel provider). The backend half (`_serve_free_default` /
`config.select_free_model`) lives in `cloud_backend/` and is gated on the
founder funding one upstream key + flipping the free switch — a TRUE boundary.

Guarantees (each runs against the REAL code path, not a stubbed router):

A) REACHABLE-ONLY-WITH-A-TOKEN — `configured_providers()` includes
   `archhub_cloud` iff `cloud_client.is_signed_in()` is True. Signed-out =>
   the provider is cleanly absent (no error spam, neutral soft-route box).

B) AUTO PREFERS CLOUD WHEN SIGNED-IN + NO BYO + NO LOCAL — a zero-config
   signed-in user (no provider key, no env, no Ollama/CLI/LM Studio) routes
   `auto` to `archhub_cloud` across every routing bucket (default / modeling
   / analysis / short). It is the answer, not a 402 dead-end.

C) BYO / LOCAL STILL WIN — when a BYO key OR a local provider is present, it
   is preferred over the managed cloud (cloud is the LAST-RESORT fallback,
   never overriding a working local/BYO provider).

D) THE REQUEST CARRIES THE BEARER — `_get_client('archhub_cloud')` builds an
   `ArchHubCloudClient` whose OpenAI SDK is configured with the user's
   `current_token()` as the api_key (so the POST to the cloud
   /v1/chat/completions carries the bearer), and refuses to build when there
   is no token.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import cloud_client  # noqa: E402
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


@pytest.fixture
def zero_config(monkeypatch):
    """A pristine machine: no BYO keys, no env keys, no relay, no local
    providers (no Ollama / CLI / LM Studio). Sign-in state is controlled per
    test via `set_signed_in`. Returns a helper to toggle sign-in."""
    # No secrets-store keys, no relay setting.
    monkeypatch.setattr(llm_router_mod, "list_keys", lambda: [])
    monkeypatch.setattr(llm_router_mod, "load_api_key", lambda p: "")
    # No env keys.
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                "OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    # No local providers reachable. configured_providers imports these lazily
    # from the provider modules, so patch at the source module.
    import llm_providers.ollama_client as _oll
    import llm_providers.claude_cli_client as _ccli
    import llm_providers.codex_cli_client as _xcli
    import llm_detector as _det
    monkeypatch.setattr(_oll, "list_local_models", lambda: [])
    monkeypatch.setattr(_ccli, "claude_cli_path", lambda: None)
    monkeypatch.setattr(_xcli, "codex_cli_path", lambda: None)
    monkeypatch.setattr(_det, "probe_lmstudio", lambda: {})
    # relay setting absent — load_setting('relay_base_url') must be falsy.
    import secrets_store as _ss
    monkeypatch.setattr(_ss, "load_setting", lambda *a, **k: "")

    state = {"token": None}

    def _current_token():
        return state["token"]

    # is_signed_in() == bool(current_token()); patch the source of truth.
    monkeypatch.setattr(cloud_client, "current_token", _current_token)

    def set_signed_in(yes: bool, token: str = "tok_plausible_bearer_123456"):
        state["token"] = token if yes else None

    return set_signed_in


# --- A) reachable iff signed in --------------------------------------------


class TestReachableOnlyWithToken:
    def test_signed_out_cloud_not_configured(self, zero_config):
        zero_config(False)
        r = _router()
        assert "archhub_cloud" not in r.configured_providers()

    def test_signed_in_cloud_is_configured(self, zero_config):
        zero_config(True)
        r = _router()
        assert "archhub_cloud" in r.configured_providers()

    def test_signed_out_yields_empty_set_no_error(self, zero_config):
        # Pristine + signed out: the whole set is empty (the neutral
        # soft-route state), and computing it never raises / spams.
        zero_config(False)
        r = _router()
        assert r.configured_providers() == []


# --- B) auto prefers cloud when signed-in + no BYO + no local ---------------


class TestAutoPrefersCloudZeroConfig:
    @pytest.mark.parametrize("prompt", [
        "Could you draft a longer paragraph of prose for me please.",  # default
        "create a wall in revit on level 1",                            # modeling
        "explain why this schedule is wrong",                          # analysis
        "hi",                                                          # short
    ])
    def test_zero_config_auto_routes_to_cloud(self, zero_config, prompt):
        zero_config(True)
        r = _router()
        prov, model, note = r._route(
            [{"role": "user", "content": prompt}], ROUTE_AUTO)
        assert prov == "archhub_cloud", (prompt, prov, note)
        # 'auto' lets the backend pick the free model server-side.
        assert model == "auto"

    def test_signed_out_zero_config_raises_honest_no_llm(self, zero_config):
        # Signed out + nothing else configured: _route can't invent a
        # provider — it raises the honest 'No LLM configured' error (which
        # the UI renders as the neutral soft-route box), NOT a fake route.
        zero_config(False)
        r = _router()
        with pytest.raises(RuntimeError, match="No LLM configured"):
            r._route([{"role": "user", "content": "hello there friend"}],
                     ROUTE_AUTO)


# --- C) BYO / local still win over managed cloud ---------------------------


class TestByoAndLocalWinOverCloud:
    def test_byo_anthropic_beats_cloud(self, zero_config, monkeypatch):
        zero_config(True)  # cloud reachable too
        # Add a real BYO anthropic key.
        monkeypatch.setattr(llm_router_mod, "list_keys", lambda: ["anthropic"])
        monkeypatch.setattr(
            llm_router_mod, "load_api_key",
            lambda p: "sk-ant-xxx" if p == "anthropic" else "")
        r = _router()
        cfg = set(r.configured_providers())
        assert {"anthropic", "archhub_cloud"} <= cfg
        prov, _model, _note = r._route(
            [{"role": "user", "content": "draft a long paragraph of prose"}],
            ROUTE_AUTO)
        assert prov == "anthropic"   # BYO wins

    def test_local_ollama_beats_cloud(self, zero_config, monkeypatch):
        zero_config(True)  # cloud reachable too
        import llm_providers.ollama_client as _oll
        monkeypatch.setattr(_oll, "list_local_models", lambda: ["llama3.1:8b"])
        r = _router()
        r._pick_ollama_model = lambda task: "llama3.1:8b"
        cfg = set(r.configured_providers())
        assert {"ollama", "archhub_cloud"} <= cfg
        prov, model, _note = r._route(
            [{"role": "user", "content": "draft a long paragraph of prose"}],
            ROUTE_AUTO)
        assert prov == "ollama"      # local wins
        assert model == "llama3.1:8b"


# --- D) the client build carries the bearer --------------------------------


class TestClientCarriesBearer:
    def test_get_client_builds_with_bearer(self, zero_config, monkeypatch):
        zero_config(True, token="tok_real_bearer_abcdef123456")
        # current_token is read inside _get_client via cloud_client; the
        # archhub_cloud_client imports OpenAI lazily — capture its kwargs.
        captured = {}

        class _FakeOpenAI:
            def __init__(self, *, api_key, base_url, default_headers=None):
                captured["api_key"] = api_key
                captured["base_url"] = base_url
                captured["headers"] = default_headers or {}

        import openai as _openai_pkg
        monkeypatch.setattr(_openai_pkg, "OpenAI", _FakeOpenAI)

        r = _router()
        client = r._get_client("archhub_cloud")
        assert client is not None
        # The bearer the SDK will send == the user's current_token().
        assert captured["api_key"] == "tok_real_bearer_abcdef123456"
        # Pointed at the cloud /v1 base (POSTs .../v1/chat/completions).
        assert captured["base_url"].rstrip("/").endswith("/v1")

    def test_get_client_refuses_without_token(self, zero_config):
        zero_config(False)   # no token on disk
        r = _router()
        with pytest.raises(RuntimeError, match="isn't signed in"):
            r._get_client("archhub_cloud")
