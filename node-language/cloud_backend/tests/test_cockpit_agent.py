"""Founder Cockpit AGENT LOOP — tests (PHASE 5, MOCKED MODEL — no network).

The model transport is MOCKED (a scripted chat_fn) so CI never makes a network
call. These prove:

  (1) AGENT LOOP — the loop calls a READ tool, gets real data, and answers.
  (2) GATED WRITE — a write tool returns needs_confirm (nothing changes), then
      on confirm it changes REAL state on the temp db AND writes an audit row.
  (3) WITHHELD — impersonation / erasure / refund are NOT registered tools and
      are refused (no code path performs them).
  (4) KEYWORD FALLBACK — when no model key is reachable, POST /command falls
      back to the deterministic keyword router and still works.
  (5) BLAST-RADIUS — grant_credits is dollar-capped.
  (6) NO-SECRET — tool results never carry tokens.

Run: python -m pytest cloud_backend/tests/test_cockpit_agent.py -q
"""
from __future__ import annotations

import base64
import hashlib
import json

import pytest


FOUNDER_EMAIL = "founder@archhub-cockpit-test.com"


@pytest.fixture(autouse=True)
def _set_founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    # Ensure NO real model key leaks into the loop tests (we inject chat_fn).
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    import founder_cockpit
    founder_cockpit.clear_errors()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _pkce_pair():
    import secrets
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _sign_in(client, monkeypatch, email) -> str:
    async def fake_send(**kw):
        return True
    import email_sender, db
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
    verifier, challenge = _pkce_pair()
    r = client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
    assert r.status_code == 202, r.text
    u = db.get_user_by_email(email)
    with db.connect() as con:
        row = con.execute(
            "SELECT code FROM codes WHERE user_id = ?", (u["id"],)).fetchone()
    r2 = client.post("/v1/auth/exchange",
                     json={"code": row["code"], "code_verifier": verifier})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# A fake model_cfg so the loop never tries to resolve a real provider.
FAKE_CFG = {"provider": "mock", "base_url": "http://mock", "model": "mock-1",
            "key": "x"}


def _scripted_chat(*turns):
    """Build a chat_fn that returns the given assistant messages in order.
    Each turn is a dict shaped like an OpenAI assistant message."""
    seq = list(turns)
    calls = {"n": 0}

    def chat_fn(model_cfg, messages, tools):
        i = calls["n"]
        calls["n"] += 1
        if i < len(seq):
            return seq[i]
        # Default: a plain answer (loop should already have ended).
        return {"role": "assistant", "content": "done", "tool_calls": None}

    chat_fn.calls = calls
    return chat_fn


def _tool_call(name, args, cid="c1"):
    return {
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }],
    }


# ---------------------------------------------------------------------------
# (1) AGENT LOOP — read tool then answer
# ---------------------------------------------------------------------------
class TestAgentLoopRead:
    def test_loop_calls_read_tool_then_answers(self, client, monkeypatch):
        import cockpit_agent, db
        _sign_in(client, monkeypatch, "alice@studio.com")
        # Turn 1: model calls users_find. Turn 2: model answers.
        chat = _scripted_chat(
            _tool_call("users_find", {"query": "alice"}),
            {"role": "assistant", "content": "Found 1 user: alice@studio.com.",
             "tool_calls": None},
        )
        out = cockpit_agent.agent_command(
            "find alice", actor=FOUNDER_EMAIL,
            model_cfg=FAKE_CFG, chat_fn=chat)
        assert out["ok"] is True
        assert out["action"] == "agent_answer"
        assert "alice@studio.com" in out["message"]
        # The read tool actually ran (it's in the trace).
        assert any(t["tool"] == "users_find" for t in out["tools_used"])
        # The loop consumed two model turns.
        assert chat.calls["n"] == 2

    def test_read_tool_returns_no_secrets(self, client, monkeypatch):
        """users_get must never include token/code/secret fields."""
        import cockpit_agent
        _sign_in(client, monkeypatch, "bob@studio.com")
        res = cockpit_agent._t_users_get({"email": "bob@studio.com"})
        u = res["user"]
        for forbidden in ("token", "code", "secret", "password"):
            assert not any(forbidden in k.lower() for k in u.keys())


# ---------------------------------------------------------------------------
# (2) GATED WRITE — needs_confirm then real change + audit
# ---------------------------------------------------------------------------
class TestGatedWriteSetPlan:
    def test_write_returns_needs_confirm_and_changes_nothing(
            self, client, monkeypatch):
        import cockpit_agent, db
        _sign_in(client, monkeypatch, "carol@studio.com")
        assert db.get_user_by_email("carol@studio.com")["plan"] == "trial"
        chat = _scripted_chat(
            _tool_call("users_set_plan",
                       {"email": "carol@studio.com", "plan": "studio"}))
        out = cockpit_agent.agent_command(
            "make carol studio", actor=FOUNDER_EMAIL,
            model_cfg=FAKE_CFG, chat_fn=chat)
        assert out["needs_confirm"] is True
        assert out["action"] == "users_set_plan"
        assert out["pending"]["tool"] == "users_set_plan"
        # Preview names the EXACT target + change.
        assert out["preview"]["target"]["email"] == "carol@studio.com"
        assert out["preview"]["change"]["plan"]["to"] == "studio"
        # NOTHING changed yet.
        assert db.get_user_by_email("carol@studio.com")["plan"] == "trial"

    def test_confirm_applies_real_change_and_audits(self, client, monkeypatch):
        import cockpit_agent, db
        _sign_in(client, monkeypatch, "dave@studio.com")
        before_audit = len(db.recent_founder_actions(100))
        # Execute the confirmed write directly (the 2nd half of the protocol).
        res = cockpit_agent.confirm_pending(
            actor=FOUNDER_EMAIL, tool="users_set_plan",
            args={"email": "dave@studio.com", "plan": "firm"},
            command="make dave firm")
        assert res["ok"] is True
        assert res["executed"] is True
        # REAL state changed.
        row = db.get_user_by_email("dave@studio.com")
        assert row["plan"] == "firm"
        # An audit row was written.
        after = db.recent_founder_actions(100)
        assert len(after) == before_audit + 1
        assert after[0]["action"] == "users_set_plan"
        assert after[0]["actor"] == FOUNDER_EMAIL
        assert after[0]["ok"] == 1

    def test_full_route_confirm_flow_changes_state(self, client, monkeypatch):
        """End-to-end over the HTTP route: confirm a pending write."""
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "erin@studio.com")
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"confirm": True,
                              "pending": {"tool": "users_set_plan",
                                          "args": {"email": "erin@studio.com",
                                                   "plan": "solo"}}})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True and d["executed"] is True
        assert db.get_user_by_email("erin@studio.com")["plan"] == "solo"


class TestGatedWriteGrantCreditsCap:
    def test_grant_under_cap_previews(self, client, monkeypatch):
        import cockpit_agent
        _sign_in(client, monkeypatch, "frank@studio.com")
        pv = cockpit_agent._w_grant_credits_preview(
            {"email": "frank@studio.com", "messages": 100})
        assert "error" not in pv
        assert pv["change"]["grant_messages"] == 100

    def test_grant_over_cap_refused(self, client, monkeypatch):
        import cockpit_agent
        _sign_in(client, monkeypatch, "grace@studio.com")
        # 10 million messages would blow far past the $200 cap.
        pv = cockpit_agent._w_grant_credits_preview(
            {"email": "grace@studio.com", "messages": 10_000_000})
        assert pv["error"] == "exceeds_usd_cap"

    def test_confirm_over_cap_does_not_grant(self, client, monkeypatch):
        import cockpit_agent, db
        _sign_in(client, monkeypatch, "heidi@studio.com")
        u = db.get_user_by_email("heidi@studio.com")
        before = db.credit_balance(user_id=u["id"])
        res = cockpit_agent.confirm_pending(
            actor=FOUNDER_EMAIL, tool="users_grant_credits",
            args={"email": "heidi@studio.com", "messages": 10_000_000})
        assert res["ok"] is False
        assert db.credit_balance(user_id=u["id"]) == before  # no money moved


# ---------------------------------------------------------------------------
# (3) WITHHELD — no tool, refused, never performed
# ---------------------------------------------------------------------------
class TestWithheld:
    def test_withheld_actions_have_no_tool(self):
        import cockpit_agent
        names = set(cockpit_agent.TOOLS.keys())
        for n in names:
            assert "impersonat" not in n
            assert "erase" not in n and "gdpr" not in n
            assert "refund" not in n
        # And the openai schema the model sees has none either.
        schema_names = {t["function"]["name"]
                        for t in cockpit_agent.openai_tools()}
        assert not any("refund" in n or "impersonat" in n or "erase" in n
                       for n in schema_names)

    def test_model_asking_for_withheld_is_refused_not_performed(
            self, client, monkeypatch):
        """Even if the model emits a withheld 'tool', the loop refuses it and
        there is no code path to perform it — the loop just informs + answers."""
        import cockpit_agent
        chat = _scripted_chat(
            _tool_call("refund_user", {"email": "x@y.com"}),
            {"role": "assistant",
             "content": "Refunds are founder-hands-only; I can't do that.",
             "tool_calls": None},
        )
        out = cockpit_agent.agent_command(
            "refund x@y.com", actor=FOUNDER_EMAIL,
            model_cfg=FAKE_CFG, chat_fn=chat)
        assert out["ok"] is True
        assert out["action"] == "agent_answer"
        assert "founder-hands-only" in out["message"].lower()
        # The refused call is recorded as refused, not executed.
        assert any(t.get("refused") for t in out["tools_used"])

    def test_is_withheld_helper(self):
        import cockpit_agent
        assert cockpit_agent.is_withheld("impersonate")
        assert cockpit_agent.is_withheld("erase_account")
        assert cockpit_agent.is_withheld("refund_charge")
        assert not cockpit_agent.is_withheld("users_set_plan")


# ---------------------------------------------------------------------------
# (4) KEYWORD FALLBACK — no model key reachable
# ---------------------------------------------------------------------------
class TestKeywordFallback:
    def test_no_model_raises_modelerror(self, monkeypatch):
        import cockpit_agent
        # reachable_model() returns None when no key configured.
        monkeypatch.setattr(cockpit_agent, "reachable_model", lambda: None)
        with pytest.raises(cockpit_agent.ModelError):
            cockpit_agent.agent_command("hi", actor=FOUNDER_EMAIL)

    def test_route_falls_back_to_keyword_when_no_model(
            self, client, monkeypatch):
        """With no model key, POST /command uses the keyword router and the
        legacy 'set <email> to <plan>' still changes real state."""
        import db, cockpit_agent
        monkeypatch.setattr(cockpit_agent, "reachable_model", lambda: None)
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "ivan@studio.com")
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "set ivan@studio.com to studio"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["action"] == "set_plan"
        assert d.get("mode") == "keyword_fallback"
        assert db.get_user_by_email("ivan@studio.com")["plan"] == "studio"

    def test_model_error_midloop_does_not_crash_route(
            self, client, monkeypatch):
        """If the model errors, the route falls back to keyword routing."""
        import cockpit_agent
        def boom():
            return FAKE_CFG
        def chat_boom(*a, **k):
            raise cockpit_agent.ModelError("upstream 500")
        monkeypatch.setattr(cockpit_agent, "reachable_model", boom)
        monkeypatch.setattr(cockpit_agent, "_chat", chat_boom)
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "help"})
        assert r.status_code == 200, r.text
        d = r.json()
        # Keyword router handled 'help'.
        assert d["action"] == "help"
        assert d.get("mode") == "keyword_fallback"


# ---------------------------------------------------------------------------
# (5) Gating still holds on the agent path
# ---------------------------------------------------------------------------
class TestAgentPathGated:
    def test_non_founder_cannot_confirm_a_write(self, client, monkeypatch):
        import db
        token = _sign_in(client, monkeypatch, "attacker2@studio.com")
        _sign_in(client, monkeypatch, "victim2@studio.com")
        before = db.get_user_by_email("victim2@studio.com")["plan"]
        r = client.post("/founder/api/command", headers=_auth(token),
                        json={"confirm": True,
                              "pending": {"tool": "users_set_plan",
                                          "args": {"email": "victim2@studio.com",
                                                   "plan": "firm"}}})
        assert r.status_code == 403
        assert db.get_user_by_email("victim2@studio.com")["plan"] == before


# ---------------------------------------------------------------------------
# (6) FREE DEFAULT config (#64) — NVIDIA is the configured free provider
# ---------------------------------------------------------------------------
class TestFreeDefaultNvidia:
    def test_nvidia_is_default_free_provider(self):
        import config
        assert config.FREE_PROVIDER == "nvidia"
        from urllib.parse import urlparse
        assert urlparse(config.FREE_PROVIDER_BASE_URL).hostname == "integrate.api.nvidia.com"
        assert "llama-3.3-70b" in config.ARCHHUB_FREE_MODEL

    def test_free_key_falls_back_to_nvidia_key(self, monkeypatch):
        import importlib, config
        monkeypatch.setenv("FREE_PROVIDER", "nvidia")
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-123")
        monkeypatch.delenv("FREE_PROVIDER_API_KEY", raising=False)
        importlib.reload(config)
        try:
            assert config.free_provider_key() == "nvapi-test-123"
            # Gated on the key: available now that the key is set.
            assert config.free_default_available() is True
        finally:
            monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
            importlib.reload(config)

    def test_free_unavailable_without_key(self, monkeypatch):
        import importlib, config
        monkeypatch.setenv("FREE_PROVIDER", "nvidia")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("FREE_PROVIDER_API_KEY", raising=False)
        # ONE-SYSTEM (#64): the selector also falls back to Gemini via
        # GOOGLE_API_KEY. To assert the genuine "nothing reachable" state we
        # must clear GOOGLE too (the runner's real env may carry it).
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        importlib.reload(config)
        try:
            assert config.free_provider_key() == ""
            assert config.free_default_available() is False
            assert config.select_free_model() is None
        finally:
            importlib.reload(config)

    def test_free_falls_back_to_gemini_when_only_google_keyed(self, monkeypatch):
        """#64 headline at the cockpit layer: with ONLY GOOGLE_API_KEY set,
        the shared selector lights up via Gemini (no NVIDIA key needed)."""
        import importlib, config
        monkeypatch.setenv("FREE_PROVIDER", "nvidia")  # committed default
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("FREE_PROVIDER_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "deployed-google-key")
        importlib.reload(config)
        try:
            assert config.free_default_available() is True
            sel = config.select_free_model()
            assert sel["provider"] == "google"
            assert sel["model"] == "gemini-2.5-flash"
            assert config.free_provider_key() == "deployed-google-key"
        finally:
            monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
            importlib.reload(config)
