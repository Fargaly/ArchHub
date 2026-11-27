"""Every cockpit route that acts writes one founder_action_log row (Cockpit P9, 2026-09-29).

The command path always audited; four routes that act outside it did not:
the purge-test-users route, the browser sign-in code, and the application's
task claim and result. A minted sign-in code is never written to the log.
(POST /founder/map-state is the founder's desktop publishing its map, a sync
stamped by its own pushed-at record, not an action.)
"""
from __future__ import annotations

import pytest

# Cockpit routes with an outside effect need one action_key per confirmed action
# (founder_cockpit._guarded). Calls that are not about the key get a fresh one,
# as a new deliberate submission from the page would; the guard's own tests
# pass their keys explicitly.
import re as _re
import uuid as _uuid
from fastapi.testclient import TestClient as _TestClient

_GUARDED = _re.compile(r"^/founder/api/(users/[^/]+/email|feedback/[^/]+/reply|companies/[^/]+/(invite|invite/resend|seats)"
                       r"|stripe/refund(/[^/]+/cancel)?)$")



def _outcome(fake):
    """A test mailer that answers True/False (or an outcome string) as the
    three-valued outcome the Cockpit reads: accepted, refused or unknown."""
    async def wrapped(**kwargs):
        answer = await fake(**kwargs)
        return answer if isinstance(answer, str) else ("accepted" if answer else "refused")
    return wrapped

class KeyedClient(_TestClient):
    def post(self, url, *args, **kwargs):
        body = kwargs.get("json")
        if _GUARDED.match(str(url)) and (body is None or isinstance(body, dict)) and "action_key" not in (body or {}):
            kwargs["json"] = dict(body or {}, action_key=_uuid.uuid4().hex)
        return super().post(url, *args, **kwargs)


FOUNDER = "founder.desktop@example.test"


@pytest.fixture
def client():
    import main
    return KeyedClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _actions(action: str) -> list[dict]:
    import db
    return [row for row in db.recent_founder_actions(200) if row["action"] == action]


def test_the_purge_route_audits_its_preview_and_its_effect(client):
    import db
    db.get_or_create_user("seed-user-1@example.com")
    preview = client.post("/founder/api/purge-test-users", headers=_auth(FOUNDER), json={})
    assert preview.status_code == 200 and preview.json()["dry_run"] is True
    assert [row["actor"] for row in _actions("purge_test_users.preview")] == [FOUNDER]
    done = client.post("/founder/api/purge-test-users", headers=_auth(FOUNDER),
                       json={"confirm": True, "typed": "DELETE"})
    assert done.status_code == 200 and done.json()["dry_run"] is False
    (row,) = _actions("purge_test_users")
    assert row["actor"] == FOUNDER and '"deleted": %d' % done.json()["deleted"] in row["result"]


def test_the_browser_code_is_audited_and_the_code_is_never_logged(client):
    r = client.post("/founder/api/browser-code", headers=_auth(FOUNDER))
    assert r.status_code == 200
    code = r.json()["claim_url"].split("code=", 1)[1]
    (row,) = _actions("browser_code")
    assert row["actor"] == FOUNDER
    import db
    assert not any(code in (entry["result"] + entry["command"] + (entry["target"] or ""))
                   for entry in db.recent_founder_actions(200))


def test_a_claimed_task_and_its_result_are_audited_an_idle_poll_is_not(client):
    import db
    idle = client.post("/founder/api/agent-tasks/claim", headers=_auth(FOUNDER), json={})
    assert idle.status_code == 200 and idle.json()["task"] is None
    assert _actions("agent_task.claim") == []
    task = db.enqueue_agent_task(directive="court: say hello", created_by=FOUNDER, kind="app")
    claimed = client.post("/founder/api/agent-tasks/claim", headers=_auth(FOUNDER), json={})
    assert claimed.json()["task"]["id"] == task["id"]
    (claim,) = _actions("agent_task.claim")
    assert claim["target"] == task["id"] and claim["actor"] == FOUNDER
    done = client.post("/founder/api/agent-tasks/%s/result" % task["id"],
                       headers=_auth(FOUNDER), json={"ok": True, "result": "hello"})
    assert done.status_code == 200
    (result,) = _actions("agent_task.result")
    assert result["target"] == task["id"] and result["ok"] == 1

# --- Every founder POST route, found by enumeration, writes an audit row --------
# A route added later that is in neither table fails the first test. Routes that
# predate the admin panel are covered by the named tests; the panel's routes are
# called here, one by one, and must each leave one more founder_action_log row.
COVERED_ELSEWHERE = {
    "/founder/api/users/{key}/suspend": "test_cockpit_admin_panel.test_a_suspend_without_the_typed_word_changes_nothing",
    "/founder/api/users/{key}/plan": "test_founder_changes_a_tier",
    "/founder/api/users/{key}/restore": "test_founder_suspends_and_restores",
    "/founder/api/community/judge": "test_cockpit_admin_panel.test_the_inbox_is_one_read_and_its_rows_act",
    "/founder/api/command": "test_founder_cockpit_command",
    "/founder/api/browser-code": "test_the_browser_code_is_audited_and_the_code_is_never_logged",
    "/founder/api/devices/{user_key}/{device_id}/disconnect": "test_founder_sees_and_disconnects_devices",
    "/founder/api/stripe/refund": "test_founder_refunds",
    "/founder/api/db/query": "test_founder_reads_the_database",
    "/founder/api/relay/tasks/{task_id}/retry": "test_cockpit_admin_panel.test_the_inbox_is_one_read_and_its_rows_act",
    "/founder/api/relay/drain": "test_founder_steers_the_relay",
    "/founder/api/agent-tasks/claim": "test_a_claimed_task_and_its_result_are_audited_an_idle_poll_is_not",
    "/founder/api/agent-tasks/{task_id}/result": "test_a_claimed_task_and_its_result_are_audited_an_idle_poll_is_not",
    "/founder/api/purge-test-users": "test_the_purge_route_audits_its_preview_and_its_effect",
    "/founder/api/agent-approvals/{approval_id}/decide": "test_cockpit_mcp.test_approve_runs_it_once_and_the_agent_can_see_the_outcome",
}
CALLED_HERE = {
    "/founder/api/companies/{company_id}/ai-mode": lambda c: ("/founder/api/companies/%s/ai-mode" % c["co"], {"ai_mode": "hosted"}),
    "/founder/api/companies/{company_id}/owner": lambda c: ("/founder/api/companies/%s/owner" % c["co"], {"user_id": c["member"]}),
    "/founder/api/companies/{company_id}/invite": lambda c: ("/founder/api/companies/%s/invite" % c["co"], {"email": "new.one@studio.example"}),
    "/founder/api/users/{key}/email": lambda c: ("/founder/api/users/%s/email" % c["user"], {"subject": "Hi", "text": "A note."}),
    "/founder/api/users/{key}/delete": lambda c: ("/founder/api/users/%s/delete" % c["user"], {"typed": "DELETE"}),
    "/founder/api/feedback/{feedback_id}/status": lambda c: ("/founder/api/feedback/%s/status" % c["fb"], {"status": "planned"}),
    "/founder/api/feedback/{feedback_id}/plan": lambda c: ("/founder/api/feedback/%s/plan" % c["fb"], {"plan_row": "R1"}),
    "/founder/api/feedback/{feedback_id}/merge": lambda c: ("/founder/api/feedback/%s/merge" % c["fb2"], {"into": c["fb"]}),
    "/founder/api/feedback/{feedback_id}/reply": lambda c: ("/founder/api/feedback/%s/reply" % c["fb"], {"text": "Thanks."}),
    "/founder/api/community/ban": lambda c: ("/founder/api/community/ban", {"user": c["user"], "reason": "x", "typed": "BAN"}),
    "/founder/api/community/unban": lambda c: ("/founder/api/community/unban", {"user": c["user"]}),
    # Unsigned on purpose: a refused recovery is still one audit row (test_community_owner_recovery covers success).
    "/founder/api/community/{community_id}/owner": lambda c: ("/founder/api/community/legacy-audit/owner",
                                                              {"owner": c["user"], "typed": "RECOVER"}),
    "/founder/api/packs/{pack_id}/takedown": lambda c: ("/founder/api/packs/pk_audit/takedown", {"reason": "x", "typed": "TAKEDOWN"}),
    "/founder/api/packs/{pack_id}/restore": lambda c: ("/founder/api/packs/pk_down/restore", {}),
    "/founder/api/companies/{company_id}/invite/resend": lambda c: ("/founder/api/companies/%s/invite/resend" % c["co"], {"email": "pending.audit@studio.example"}),
    "/founder/api/actions/key/{key}/check": lambda c: ("/founder/api/actions/key/key-audit-unresolved/check", {}),
    "/founder/api/actions/key/{key}/resolve": lambda c: ("/founder/api/actions/key/key-audit-unresolved/resolve", {"arrived": False}),
    "/founder/api/errors/resolve": lambda c: ("/founder/api/errors/resolve", {"where": "POST /v1/audit", "kind": "TimeoutError"}),
}


def _founder_post_routes() -> set:
    from tests.test_one_signin_one_cloud_address import registered_routes

    return {route.path for route in registered_routes()
            if (route.path or "").startswith("/founder/api/") and "POST" in (getattr(route, "methods", None) or ())}


def test_every_founder_post_route_is_accounted_for():
    found = _founder_post_routes()
    assert found == set(COVERED_ELSEWHERE) | set(CALLED_HERE), (
        "new or removed founder routes: %s" % sorted(found ^ (set(COVERED_ELSEWHERE) | set(CALLED_HERE))))


@pytest.fixture
def seeded(monkeypatch):
    import json
    import time
    import db
    import email_sender
    import feedback
    import founder_cockpit

    async def ok_send(**_kwargs):
        return True

    monkeypatch.setattr(email_sender, "send_outcome", _outcome(ok_send))
    monkeypatch.setattr(email_sender, "send_company_invite_outcome", _outcome(ok_send))
    owner = db.get_or_create_user("owner.audit@studio.example")
    member = db.get_or_create_user("member.audit@studio.example")
    co = db.create_company(name="Audit Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    db.add_company_member(company_id=co["id"], user_id=member["id"], invited_by_user_id=owner["id"])
    fb = feedback.submit(member["id"], "First.", "bug")
    fb2 = feedback.submit(member["id"], "Second.", "bug")
    now = int(time.time())
    db.get_or_create_user(FOUNDER)
    with db.connect() as con:
        for pid, status in (("pk_audit", "approved"), ("pk_down", "taken_down")):
            con.execute("INSERT INTO marketplace_packs (id, slug, title, author_user_id, manifest_json, signature, "
                        "pubkey, status, created_at, updated_at) VALUES (?, ?, 'Pack', ?, '{}', 's', 'k', ?, ?, ?)",
                        (pid, pid, member["id"], status, now, now))
        con.execute("INSERT INTO founder_action_log (ts, actor, command, action, target, result, ok) VALUES "
                    "(?, ?, 'POST /founder/api/stripe/refund', 'stripe.refund', 'pi_audit', ?, 1)",
                    (now, FOUNDER, json.dumps({"id": "re_audit", "amount": 100, "currency": "usd"})))
    founder_cockpit.record_error(where="POST /v1/audit", kind="TimeoutError", message="slow", status=504)
    db.create_company_invite(company_id=co["id"], email="pending.audit@studio.example", role="member",
                             invited_by_user_id=owner["id"])
    db.claim_action_key(key="key-audit-unresolved", founder=FOUNDER, route="POST /founder/api/users/{key}/email",
                        target="someone@studio.example", body_hash="x")
    db.finish_action_key("key-audit-unresolved", status=202, result="{}", state="uncertain")
    return {"co": co["id"], "member": member["id"], "user": member["email"], "fb": fb["id"],
            "fb2": fb2["id"]}


@pytest.mark.parametrize("template", sorted(CALLED_HERE))
def test_each_admin_panel_route_writes_one_audit_row(client, seeded, template):
    import db
    path, body = CALLED_HERE[template](seeded)
    before = db.recent_founder_actions(1000)
    answer = client.post(path, headers=_auth(FOUNDER), json=body)
    assert answer.status_code < 500, (template, answer.status_code, answer.text)
    after = db.recent_founder_actions(1000)
    assert len(after) == len(before) + 1, template
    assert after[0]["actor"] == FOUNDER and after[0]["command"].startswith("POST /founder/api/")
