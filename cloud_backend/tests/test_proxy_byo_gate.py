"""Cloud LLM proxy BYO_KEY gate — 2026-05-24.

Free / Solo plans always run BYO key. Studio / Firm get cloud-proxied
LLM access only when PROXY_LIVE is on (founder flips after funding
upstream provider balances). Quota-exhausted still wins over the
BYO gate so the user sees the more actionable "upgrade" message.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException


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


def _call(user):
    import proxy
    return asyncio.run(proxy.chat_completions(user=user, body={"model": "auto"}))


# ── PROXY_LIVE OFF ──────────────────────────────────────────────────


def test_trial_user_gets_byo_required(monkeypatch):
    monkeypatch.setattr("config.PROXY_LIVE", False)
    u = _user("t1@example.com", "trial")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.status_code == 402
    assert exc.value.detail["error"] == "byo_key_required"
    assert exc.value.detail["plan"] == "trial"


def test_solo_user_gets_byo_required(monkeypatch):
    monkeypatch.setattr("config.PROXY_LIVE", False)
    u = _user("s1@example.com", "solo")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.status_code == 402
    assert exc.value.detail["error"] == "byo_key_required"
    assert exc.value.detail["plan"] == "solo"


def test_studio_user_gets_byo_required_when_proxy_off(monkeypatch):
    """Even paid Studio plans see byo_required when PROXY_LIVE=0 —
    accidental traffic cannot burn down the dev balance."""
    monkeypatch.setattr("config.PROXY_LIVE", False)
    u = _user("st1@example.com", "studio")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.status_code == 402
    assert exc.value.detail["error"] == "byo_key_required"
    assert exc.value.detail["proxy_live"] is False


# ── PROXY_LIVE ON ───────────────────────────────────────────────────


def test_trial_user_still_byo_when_proxy_on(monkeypatch):
    """Even with PROXY_LIVE=1, trial plan is not on the allow-list —
    Free tier never burns founder budget."""
    monkeypatch.setattr("config.PROXY_LIVE", True)
    u = _user("t2@example.com", "trial")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.detail["error"] == "byo_key_required"


def test_solo_user_still_byo_when_proxy_on(monkeypatch):
    monkeypatch.setattr("config.PROXY_LIVE", True)
    u = _user("s2@example.com", "solo")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.detail["error"] == "byo_key_required"


# ── Quota wins over BYO gate (more actionable) ──────────────────────


def test_quota_exhausted_wins_over_byo_required(monkeypatch):
    """Trial user with msgs burnt should see quota_exhausted (which
    tells them to upgrade) — NOT byo_required."""
    import db
    monkeypatch.setattr("config.PROXY_LIVE", False)
    u = _user("burn@example.com", "trial")
    with db.connect() as con:
        con.execute("UPDATE users SET msg_used = msg_limit WHERE id = ?", (u["id"],))
    u = db.get_user_by_email("burn@example.com")
    with pytest.raises(HTTPException) as exc:
        _call(u)
    assert exc.value.detail["error"] == "quota_exhausted"
    assert exc.value.detail["actor"] == "user"
