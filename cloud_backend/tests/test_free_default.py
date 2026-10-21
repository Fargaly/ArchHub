"""FREE DEFAULT tier — zero-config free model served by our cloud.

Founder 2026-06-22: a no-BYO-key request must get a strong free model
served BY our cloud (proxied to a free provider with a server-side key),
NOT a 402 byo_key_required. Key optional, upgrade later. BYO + hosted
paths stay intact.

These tests prove:
  - When the free tier IS configured, a no-key (byo_key default) request
    is SERVED (StreamingResponse) — no 402.
  - The upstream call goes to the configured free provider/base/model
    with the server-side key, and the request is forced onto the free
    model (a no-key user can't aim the free key at a paid model).
  - No hosted credit is consumed; only the fair-use counter bumps.
  - /v1/models advertises the free model as the default for a no-key user.
  - When the free tier is NOT configured, the honest 402 still fires
    (BYO still works) — never a crash.
  - Quota exhaustion still wins over the free path (more actionable).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "t.db"))
    import importlib
    import config as _config
    import db as _db
    import proxy as _proxy
    importlib.reload(_config)
    importlib.reload(_db)
    importlib.reload(_proxy)
    _db.init_schema()
    yield


def _user(email: str, plan: str = "trial"):
    import db
    u = db.get_or_create_user(email)
    if plan != "trial":
        db.update_user_plan(u["id"], plan=plan, stripe_id=None, period_end=None)
        u = db.get_user_by_email(email)
    return u


def _configure_free(monkeypatch, *, provider="groq",
                    base="https://api.groq.com/openai/v1",
                    model="llama-3.3-70b-versatile", key="free-server-key"):
    monkeypatch.setattr("config.FREE_DEFAULT_ENABLED", True)
    monkeypatch.setattr("config.FREE_PROVIDER", provider)
    monkeypatch.setattr("config.FREE_PROVIDER_BASE_URL", base)
    monkeypatch.setattr("config.ARCHHUB_FREE_MODEL", model)
    monkeypatch.setattr("config.FREE_PROVIDER_API_KEY", key)
    # ONE-SYSTEM (#64): config.select_free_model() prefers NVIDIA, then Gemini
    # via NVIDIA_API_KEY / GOOGLE_API_KEY when no explicit free key is set. The
    # runner's real env may carry those, so pin them OFF here to isolate the
    # CONFIGURED-provider path under test. Tests that exercise the NVIDIA/Gemini
    # fallback set these explicitly themselves.
    monkeypatch.setattr("config.NVIDIA_API_KEY", "")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "")


def _call(user, body=None):
    import proxy
    return asyncio.run(
        proxy.chat_completions(user=user, body=body or {"model": "auto"}))


# ── No key → served free, not 402 ───────────────────────────────────

def test_no_key_trial_user_gets_free_model_not_402(monkeypatch):
    """The headline guarantee: a trial user with NO BYO key + NO paid plan
    gets the free model SERVED — never byo_key_required."""
    _configure_free(monkeypatch)

    async def _fake_free(model, body):
        # Prove the request is forced onto the free model id.
        assert model == "llama-3.3-70b-versatile"
        assert body["model"] == "llama-3.3-70b-versatile"
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'

    monkeypatch.setattr("proxy._stream_free", _fake_free)
    resp = _call(_user("free1@example.com", "trial"),
                 body={"model": "auto"})
    assert isinstance(resp, StreamingResponse)
    assert resp.headers.get("X-ArchHub-Tier") == "free-default"
    assert resp.headers.get("X-ArchHub-Model") == "llama-3.3-70b-versatile"


def test_no_key_solo_user_also_served_free(monkeypatch):
    _configure_free(monkeypatch)
    monkeypatch.setattr(
        "proxy._stream_free",
        lambda m, b: _agen(b'data: {}\n\n'))
    resp = _call(_user("free-solo@example.com", "solo"))
    assert isinstance(resp, StreamingResponse)


async def _agen(*chunks):
    for c in chunks:
        yield c


def test_free_path_forces_server_model_over_requested(monkeypatch):
    """A no-key user requesting an expensive model id is overridden onto
    the free model — they can't point the server key at a paid upstream."""
    _configure_free(monkeypatch)
    seen = {}

    async def _fake_free(model, body):
        seen["model"] = model
        seen["body_model"] = body["model"]
        yield b'data: {}\n\n'

    monkeypatch.setattr("proxy._stream_free", _fake_free)
    resp = _call(_user("free2@example.com", "trial"),
                 body={"model": "claude-opus-4-6"})
    # Drain the stream so the generator runs.
    asyncio.run(_drain(resp))
    assert seen["model"] == "llama-3.3-70b-versatile"
    assert seen["body_model"] == "llama-3.3-70b-versatile"


async def _drain(resp):
    async for _ in resp.body_iterator:
        pass


def test_free_path_consumes_no_hosted_credit(monkeypatch):
    """Free is free: the stream bumps the fair-use counter but never
    decrements a hosted credit."""
    import db
    _configure_free(monkeypatch)
    calls = {"credit": 0, "usage": 0}
    monkeypatch.setattr(
        "db.consume_credit_for_actor",
        lambda u, n: calls.__setitem__("credit", calls["credit"] + n))
    monkeypatch.setattr(
        "db.increment_usage_for_actor",
        lambda u, n: calls.__setitem__("usage", calls["usage"] + n))
    monkeypatch.setattr("proxy._stream_free",
                        lambda m, b: _agen(b'data: {}\n\n'))
    resp = _call(_user("free3@example.com", "trial"))
    asyncio.run(_drain(resp))
    assert calls["credit"] == 0      # NO hosted credit touched
    assert calls["usage"] == 1       # fair-use counter bumped once


# ── /v1/models advertises the free default ───────────────────────────

def test_models_lists_free_default_for_no_key_user(monkeypatch):
    _configure_free(monkeypatch)
    import proxy
    out = proxy.list_models(user=_user("free-m@example.com", "trial"))
    assert out["archhub_free_default"] is True
    assert out["archhub_default_model"] == "llama-3.3-70b-versatile"
    ids = [m["id"] for m in out["data"]]
    assert "llama-3.3-70b-versatile" in ids
    assert out["data"][0]["archhub_default"] is True


# ── Honest fallback when the free tier is NOT configured ─────────────

def test_no_free_key_falls_back_to_byo_402(monkeypatch):
    """NO reachable provider at all (no free key, no NVIDIA, no GOOGLE) →
    honest byo_key_required 402 (BYO still works), never a crash + never a
    fake. This is the genuine "nothing configured" degrade."""
    monkeypatch.setattr("config.FREE_DEFAULT_ENABLED", True)
    monkeypatch.setattr("config.FREE_PROVIDER", "groq")
    monkeypatch.setattr("config.FREE_PROVIDER_BASE_URL",
                        "https://api.groq.com/openai/v1")
    monkeypatch.setattr("config.FREE_PROVIDER_API_KEY", "")  # no free key
    monkeypatch.setattr("config.NVIDIA_API_KEY", "")         # no NVIDIA
    monkeypatch.setattr("config.GOOGLE_API_KEY", "")         # no Gemini
    with pytest.raises(HTTPException) as exc:
        _call(_user("nofree@example.com", "trial"))
    assert exc.value.status_code == 402
    assert exc.value.detail["error"] == "byo_key_required"
    assert exc.value.detail["free_default"] == "unavailable"


def test_free_disabled_switch_falls_back_to_byo(monkeypatch):
    _configure_free(monkeypatch)
    monkeypatch.setattr("config.FREE_DEFAULT_ENABLED", False)  # master off
    with pytest.raises(HTTPException) as exc:
        _call(_user("offsw@example.com", "trial"))
    assert exc.value.detail["error"] == "byo_key_required"


# ── Quota still wins (more actionable) ──────────────────────────────

def test_quota_exhausted_wins_over_free(monkeypatch):
    import db
    _configure_free(monkeypatch)
    u = _user("burnfree@example.com", "trial")
    with db.connect() as con:
        con.execute("UPDATE users SET msg_used = msg_limit WHERE id = ?",
                    (u["id"],))
    u = db.get_user_by_email("burnfree@example.com")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.detail["error"] == "quota_exhausted"


# ── op:// secret reference resolution ───────────────────────────────

def test_free_key_resolves_op_reference(monkeypatch):
    """An op:// reference for the free key resolves at call time via the
    env fallback (no plaintext key in code/git)."""
    monkeypatch.setenv("OP_ARCHHUB_GROQ_API_KEY", "resolved-free-key")
    import importlib
    import config as _config
    importlib.reload(_config)
    monkeypatch.setattr(_config, "FREE_PROVIDER", "groq")
    monkeypatch.setattr(_config, "FREE_PROVIDER_API_KEY",
                        "op://archhub/groq/api_key")
    assert _config.free_provider_key() == "resolved-free-key"


# ── ONE-SYSTEM #64: Gemini-now, NVIDIA-when-keyed selection ──────────
# config.select_free_model() is THE shared selector reused by the cloud free
# path AND cockpit_agent.reachable_model(). These prove the headline founder
# guarantee: the free default lights up TODAY on the already-deployed
# GOOGLE_API_KEY (no new secret), and prefers NVIDIA the moment it is keyed.


def _reset_free_env(monkeypatch):
    """Reset the free-default knobs to their committed defaults + clear every
    provider key, so each selection test starts from a known clean slate
    regardless of the runner's real env."""
    monkeypatch.setattr("config.FREE_DEFAULT_ENABLED", True)
    monkeypatch.setattr("config.FREE_PROVIDER", "nvidia")  # committed default
    monkeypatch.setattr("config.FREE_PROVIDER_API_KEY", "")
    monkeypatch.setattr("config.FREE_PROVIDER_BASE_URL", "")
    monkeypatch.setattr("config.ARCHHUB_FREE_MODEL", "meta/llama-3.3-70b-instruct")
    monkeypatch.setattr("config.NVIDIA_API_KEY", "")
    monkeypatch.setattr("config.NVIDIA_BASE_URL",
                        "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr("config.NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "")


def test_free_available_with_only_google_key(monkeypatch):
    """THE #64 headline: with ONLY GOOGLE_API_KEY set (today's deployed
    reality) + NVIDIA unset, free_default_available() is True via Gemini —
    so the composer works for real users with no new secret."""
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.GOOGLE_API_KEY", "deployed-google-key")
    assert config.free_default_available() is True
    sel = config.select_free_model()
    assert sel is not None
    assert sel["provider"] == "google"
    assert sel["base_url"] == (
        "https://generativelanguage.googleapis.com/v1beta/openai")
    assert sel["model"] == "gemini-2.5-flash"
    assert sel["key"] == "deployed-google-key"
    # The served model id the proxy advertises reflects Gemini.
    assert config.free_selected_model() == "gemini-2.5-flash"
    assert config.free_provider_key() == "deployed-google-key"


def test_serve_free_default_targets_gemini_with_only_google_key(monkeypatch):
    """When Gemini is the selected free provider, _serve_free_default streams
    to the Gemini OpenAI-compat base with the deployed GOOGLE key + forces the
    Gemini model id — proving the user-facing path serves the selected provider
    (not a stale config default)."""
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.GOOGLE_API_KEY", "deployed-google-key")

    captured = {}

    class _FakeStream:
        def __init__(self, method, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = (json or {}).get("model")
            captured["auth"] = (headers or {}).get("Authorization")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_bytes(self):
            yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, headers=None, json=None):
            return _FakeStream(method, url, headers=headers, json=json)

    monkeypatch.setattr(proxy.httpx, "AsyncClient", _FakeClient)
    resp = _call(_user("gemini-user@example.com", "trial"),
                 body={"model": "auto"})
    assert isinstance(resp, StreamingResponse)
    assert resp.headers.get("X-ArchHub-Model") == "gemini-2.5-flash"
    asyncio.run(_drain(resp))
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/openai"
        "/chat/completions")
    assert captured["model"] == "gemini-2.5-flash"
    # The deployed GOOGLE key (server-side) carries the call — never the user.
    assert captured["auth"] == "Bearer deployed-google-key"


def test_nvidia_preferred_when_keyed(monkeypatch):
    """The moment NVIDIA_API_KEY is set, NVIDIA wins over Gemini even with
    GOOGLE_API_KEY also present — preferred provider for scale (#64)."""
    import config
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.NVIDIA_API_KEY", "nvidia-server-key")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "deployed-google-key")
    sel = config.select_free_model()
    assert sel is not None
    assert sel["provider"] == "nvidia"
    assert sel["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert sel["model"] == "meta/llama-3.3-70b-instruct"
    assert sel["key"] == "nvidia-server-key"
    assert config.free_default_available() is True
    assert config.free_provider_key() == "nvidia-server-key"


def test_serve_free_default_targets_nvidia_when_keyed(monkeypatch):
    """User-facing path streams to NVIDIA's base + model id when NVIDIA is
    keyed (preferred), even if GOOGLE is also set."""
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.NVIDIA_API_KEY", "nvidia-server-key")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "deployed-google-key")

    seen = {}

    async def _fake_free(model, body):
        seen["model"] = model
        seen["base"] = config.free_selected_base_url()
        seen["key"] = config.free_provider_key()
        yield b'data: {}\n\n'

    monkeypatch.setattr("proxy._stream_free", _fake_free)
    resp = _call(_user("nv-user@example.com", "trial"), body={"model": "auto"})
    assert resp.headers.get("X-ArchHub-Model") == "meta/llama-3.3-70b-instruct"
    asyncio.run(_drain(resp))
    assert seen["model"] == "meta/llama-3.3-70b-instruct"
    assert seen["base"] == "https://integrate.api.nvidia.com/v1"
    assert seen["key"] == "nvidia-server-key"


def test_models_advertises_gemini_when_only_google_key(monkeypatch):
    """/v1/models reflects the ACTUALLY-served free model id (Gemini today)."""
    import config
    import proxy
    _reset_free_env(monkeypatch)
    monkeypatch.setattr("config.GOOGLE_API_KEY", "deployed-google-key")
    out = proxy.list_models(user=_user("m-gemini@example.com", "trial"))
    assert out["archhub_free_default"] is True
    assert out["archhub_default_model"] == "gemini-2.5-flash"
    ids = [m["id"] for m in out["data"]]
    assert "gemini-2.5-flash" in ids


def test_cockpit_reachable_model_reuses_shared_selector(monkeypatch):
    """ONE-SYSTEM proof: cockpit_agent.reachable_model() returns the SAME
    selection as config.select_free_model() — no parallel provider logic."""
    import config
    import cockpit_agent
    _reset_free_env(monkeypatch)
    # Gemini-only today.
    monkeypatch.setattr("config.GOOGLE_API_KEY", "deployed-google-key")
    rm = cockpit_agent.reachable_model()
    sel = config.select_free_model()
    assert rm == sel
    assert rm["provider"] == "google"
    # NVIDIA keyed → both flip to NVIDIA together.
    monkeypatch.setattr("config.NVIDIA_API_KEY", "nvidia-server-key")
    rm2 = cockpit_agent.reachable_model()
    sel2 = config.select_free_model()
    assert rm2 == sel2
    assert rm2["provider"] == "nvidia"
    # Nothing reachable → both None.
    monkeypatch.setattr("config.NVIDIA_API_KEY", "")
    monkeypatch.setattr("config.GOOGLE_API_KEY", "")
    assert cockpit_agent.reachable_model() is None
    assert config.select_free_model() is None
