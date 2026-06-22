"""Founder Cockpit COMMAND SURFACE — REAL AUTHORITY tests (PHASE 5).

Proves the cockpit ACTS, not just displays:
  (a) a command causes a REAL db change (set plan -> row.plan changes;
      purge test users -> rows actually deleted) on the temp test db.
  (b) a non-founder caller -> 403 on every action route.
  (c) destructive actions need {confirm: true} (preview, nothing deleted).
  (d) the agent-direction command produces a REAL queued/started effect
      (an agent_tasks row the app-side loop can claim).

These run against the same TestClient + temp db the rest of the cockpit
tests use, so every assertion is on real stored state, never a mock.
"""
from __future__ import annotations

import base64
import hashlib

import pytest


FOUNDER_EMAIL = "founder@archhub-cockpit-test.com"


@pytest.fixture(autouse=True)
def _set_founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
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


ACTION_ROUTES = [
    ("POST", "/founder/api/command"),
    ("POST", "/founder/api/purge-test-users"),
    ("GET", "/founder/api/actions"),
    ("GET", "/founder/api/agent-tasks"),
]


# --- (b) gating: non-founder + unauthenticated -> 403 on EVERY action route -
class TestActionRoutesGated:
    @pytest.mark.parametrize("method,path", ACTION_ROUTES)
    def test_unauthenticated_403(self, client, method, path):
        r = client.request(method, path, json={})
        assert r.status_code == 403, (path, r.status_code)

    @pytest.mark.parametrize("method,path", ACTION_ROUTES)
    def test_non_founder_403(self, client, monkeypatch, method, path):
        token = _sign_in(client, monkeypatch, "not.the.founder@studio.com")
        # Sanity: token is valid on a normal route.
        assert client.get("/v1/me", headers=_auth(token)).status_code == 200
        r = client.request(method, path, headers=_auth(token), json={})
        assert r.status_code == 403, (path, r.status_code)

    def test_non_founder_cannot_set_plan(self, client, monkeypatch):
        """A non-founder cannot mutate another user's plan via the command."""
        import db
        token = _sign_in(client, monkeypatch, "attacker@studio.com")
        _sign_in(client, monkeypatch, "victim@studio.com")
        before = db.get_user_by_email("victim@studio.com")["plan"]
        r = client.post("/founder/api/command", headers=_auth(token),
                        json={"command": "set victim@studio.com to studio"})
        assert r.status_code == 403
        after = db.get_user_by_email("victim@studio.com")["plan"]
        assert after == before  # unchanged — no authority leaked


# --- (a) REAL db change: set plan -----------------------------------------
class TestSetPlanRealEffect:
    def test_command_sets_plan_row_changes(self, client, monkeypatch):
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "target@studio.com")
        assert db.get_user_by_email("target@studio.com")["plan"] == "trial"
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "set target@studio.com to studio"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["action"] == "set_plan"
        assert d["plan"] == "studio"
        # REAL state changed in the db:
        row = db.get_user_by_email("target@studio.com")
        assert row["plan"] == "studio"
        assert row["msg_limit"] == __import__("config").PLAN_QUOTAS["studio"]

    def test_set_plan_unknown_user_clean_fail(self, client, monkeypatch):
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "set nobody@nowhere-real.com to solo"})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is False
        assert "no_such_user" in d.get("error", "")

    def test_set_plan_unknown_plan_rejected(self, client, monkeypatch):
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "u2@studio.com")
        # args path with an invalid plan must not mutate.
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "set plan",
                              "args": {"action": "set_plan",
                                       "email": "u2@studio.com",
                                       "plan": "platinum"}})
        d = r.json()
        assert d["ok"] is False
        assert db.get_user_by_email("u2@studio.com")["plan"] == "trial"


# --- (a)+(c) REAL db change + confirm gate: purge test users ---------------
class TestPurgeRealEffectAndConfirm:
    def test_purge_needs_confirm_preview_deletes_nothing(self, client, monkeypatch):
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "throwaway1@example.com")
        before = db.count_users()
        # No confirm -> preview only, NOTHING deleted.
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "purge test users"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["needs_confirm"] is True
        assert d["would_delete"] >= 1
        assert "throwaway1@example.com" in d["emails"]
        assert db.count_users() == before  # nothing gone yet

    def test_purge_with_confirm_really_deletes(self, client, monkeypatch):
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "throwaway2@example.com")
        _sign_in(client, monkeypatch, "real.customer@studio.com")
        assert db.get_user_by_email("throwaway2@example.com") is not None
        before = db.count_users()
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "purge test users", "confirm": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["deleted"] >= 1
        # REAL rows gone: the test user is deleted...
        assert db.get_user_by_email("throwaway2@example.com") is None
        assert db.count_users() < before
        # ...but the real (non-test) customer survives.
        assert db.get_user_by_email("real.customer@studio.com") is not None

    def test_dedicated_purge_route_also_gated_on_confirm(self, client, monkeypatch):
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "throwaway3@example.com")
        before = db.count_users()
        # preview
        r = client.post("/founder/api/purge-test-users", headers=_auth(ftoken),
                        json={})
        assert r.json()["needs_confirm"] is True
        assert db.count_users() == before
        # confirmed
        r2 = client.post("/founder/api/purge-test-users", headers=_auth(ftoken),
                         json={"confirm": True})
        assert r2.json()["deleted"] >= 1
        assert db.get_user_by_email("throwaway3@example.com") is None


# --- (toggle) REAL config flag effect on serving --------------------------
class TestFreeDefaultToggle:
    def test_toggle_persists_and_changes_serving(self, client, monkeypatch):
        import db, config
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        # Turn OFF -> persisted flag + serving disabled regardless of env.
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "free default off"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["free_default"] is False
        assert db.get_founder_flag("free_default") == "0"
        # REAL downstream effect: free serving is now off.
        assert config.free_default_available() is False
        # Turn ON again -> flag flips.
        r2 = client.post("/founder/api/command", headers=_auth(ftoken),
                         json={"command": "free default on"})
        assert r2.json()["free_default"] is True
        assert db.get_founder_flag("free_default") == "1"


# --- (d) agent direction: REAL queued/started effect ----------------------
class TestDirectAgentRealQueue:
    def test_build_command_enqueues_real_task(self, client, monkeypatch):
        import db
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        before = db.count_agent_tasks()
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "build a Notion connector for me"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["action"] == "direct_agent"
        assert d["queued"] is True
        tid = d["task_id"]
        assert tid.startswith("task_")
        # REAL durable state: a queued row the agent loop can pick up.
        assert db.count_agent_tasks() == before + 1
        task = db.get_agent_task(tid)
        assert task is not None
        assert task["status"] == "queued"
        assert "Notion" in task["directive"]
        # And it is genuinely claimable work (the agent side of the contract).
        claimed = db.claim_agent_task(tid, "agent-worker-1")
        assert claimed is not None
        assert claimed["status"] == "claimed"
        # A second claim fails (already taken) — proves real atomic state.
        assert db.claim_agent_task(tid, "agent-worker-2") is None

    def test_agent_tasks_route_lists_the_task(self, client, monkeypatch):
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        client.post("/founder/api/command", headers=_auth(ftoken),
                    json={"command": "build a Revit QA pass"})
        r = client.get("/founder/api/agent-tasks", headers=_auth(ftoken))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert any("Revit" in t["directive"] for t in body["tasks"])


# --- audit: every command is logged ----------------------------------------
class TestCommandAudit:
    def test_actions_logged_and_listed(self, client, monkeypatch):
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        _sign_in(client, monkeypatch, "auditme@studio.com")
        client.post("/founder/api/command", headers=_auth(ftoken),
                    json={"command": "set auditme@studio.com to solo"})
        r = client.get("/founder/api/actions", headers=_auth(ftoken))
        assert r.status_code == 200
        actions = r.json()["actions"]
        assert any(a["action"] == "set_plan" and a["actor"] == FOUNDER_EMAIL
                   for a in actions)

    def test_help_command(self, client, monkeypatch):
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        r = client.post("/founder/api/command", headers=_auth(ftoken),
                        json={"command": "help"})
        d = r.json()
        assert d["action"] == "help"
        assert "purge test users" in d["message"]


# --- page surface: the command box is on the cockpit page -------------------
class TestCommandSurfaceOnPage:
    def test_page_has_command_box(self, client, monkeypatch):
        ftoken = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
        html = client.get("/founder", headers=_auth(ftoken)).text
        assert 'id="cmd"' in html
        assert "/founder/api/command" in html
        assert "Confirm" in html
