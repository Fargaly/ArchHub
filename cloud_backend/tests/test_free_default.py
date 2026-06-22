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
    """No free provider key configured → honest byo_key_required 402
    (BYO still works), never a crash."""
    monkeypatch.setattr("config.FREE_DEFAULT_ENABLED", True)
    monkeypatch.setattr("config.FREE_PROVIDER", "groq")
    monkeypatch.setattr("config.FREE_PROVIDER_BASE_URL",
                        "https://api.groq.com/openai/v1")
    monkeypatch.setattr("config.FREE_PROVIDER_API_KEY", "")  # no key
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
    monkeypatch.setattr(_config, "FREE_PROVIDER_API_KEY",
                        "op://archhub/groq/api_key")
    assert _config.free_provider_key() == "resolved-free-key"
