"""The Cockpit is an admin panel, not a dashboard (founder 2026-11-17, F48.1 and F48.2).

What the panel adds to the founder routes, exercised through the routes
themselves: the Inbox is one read over the waiting queues and its rows act;
the Users list filters and counts on the server; a suspend and a test-account
purge change nothing until the founder's typed word arrives; companies are
listed; the page is served at /founder and the system graph moved to
/founder/map; the founder sets a company's models and owner, invites
into it and emails one person; the page's two fonts are byte copies served
behind the founder gate. Each action is checked on the rows it changes and on
the audit row it writes. Refund reasons live in test_founder_refunds.py, the payments
list in test_founder_sees_payments.py.
"""
from __future__ import annotations

import json

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
STRANGER = "someone.else@studio.example"
USER = "architect.two@studio.example"
TEST_ACCOUNT = "reality+smoketest9@archhub.io"


@pytest.fixture
def client():
    import main
    return KeyedClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _logged(action: str) -> list:
    import db
    return [row for row in db.recent_founder_actions(50) if row["action"] == action]


def _inbox(client) -> list:
    answer = client.get("/founder/api/inbox", headers=_auth(FOUNDER))
    assert answer.status_code == 200, answer.text
    assert answer.json()["count"] == len(answer.json()["items"])
    return answer.json()["items"]


def test_the_page_is_the_admin_panel_and_the_system_graph_moved(client):
    founder = _auth(FOUNDER)
    page = client.get("/founder", headers=founder)
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    graph = client.get("/founder/map", headers=founder)
    assert graph.status_code == 200 and "/founder/map-assets/" in graph.text
    assert graph.text != page.text
    assert 'href="/founder"' in graph.text and "/founder/admin" not in graph.text   # the map links to the panel itself
    assert client.get("/founder/admin", headers=founder, follow_redirects=False).status_code == 404   # the old address is gone


def test_a_stranger_reaches_none_of_the_new_routes(client):
    stranger = _auth(STRANGER)
    for path in ("/founder/map", "/founder/api/inbox", "/founder/api/companies",
                 "/founder/api/users/find?only=paying"):
        assert client.get(path, headers=stranger).status_code == 403, path


def test_the_inbox_is_one_read_and_its_rows_act(client):
    import db
    import founder_cockpit
    member = db.get_or_create_user(USER)
    db.submit_community_version("revit-tips", "frag-1", "hlc-1", contributor=member["id"],
                                text="Lock the phase filter in every view template.")
    db.record_payment_event(kind="payment_failed", user_id=member["id"], stripe_object="in_court_1",
                            amount=1900, currency="usd", detail="attempt 2")
    task = db.enqueue_agent_task(directive="push the update", created_by=FOUNDER, kind="app")
    db.claim_agent_task(task["id"], "archhub-app")
    db.finish_agent_task(task["id"], ok=False, result="device offline")
    founder_cockpit.record_error(where="POST /v1/court", kind="TimeoutError",
                                 message="the court timed out", status=504)

    items = {item["kind"]: item for item in _inbox(client)}
    assert set(items) == {"community", "payment_failed", "relay_failed", "error"}
    post = items["community"]
    assert (post["who"], post["community_id"], post["id"], post["hlc"]) == (
        USER, "revit-tips", "frag-1", "hlc-1")
    assert items["payment_failed"]["who"] == USER and items["payment_failed"]["amount"] == 1900
    assert items["relay_failed"]["id"] == task["id"]
    assert items["relay_failed"]["text"] == "device offline"

    judged = client.post("/founder/api/community/judge", headers=_auth(FOUNDER), json={
        "community_id": post["community_id"], "id": post["id"], "hlc": post["hlc"],
        "admit": False, "reason": "Not about practice"})
    assert judged.status_code == 200 and judged.json()["status"] == "rejected"
    retried = client.post("/founder/api/relay/tasks/%s/retry" % task["id"], headers=_auth(FOUNDER))
    assert retried.status_code == 200
    assert {item["kind"] for item in _inbox(client)} == {"payment_failed", "error"}
    assert db.pending_community_versions() == []
    assert db.get_agent_task(task["id"])["status"] == "queued"
    (verdict,) = _logged("community.judge")
    assert json.loads(verdict["result"]) == {"admit": False, "judged": True,
                                             "reason": "Not about practice"}
    assert [row["target"] for row in _logged("relay.retry")] == [task["id"]]


def test_the_users_list_filters_and_counts_on_the_server(client):
    import db
    founder = _auth(FOUNDER)                                        # the founder is a trial account
    trial = db.get_or_create_user(USER)
    db.update_user_profile(trial["id"], full_name="Court Planner")
    paying = db.get_or_create_user("paying.one@studio.example")
    db.update_user_plan(paying["id"], plan="solo")
    db.get_or_create_user(TEST_ACCOUNT)
    suspended = db.get_or_create_user("stopped.one@studio.example")
    db.set_user_suspended(suspended["id"], "court")
    session = db.issue_token(trial["id"])
    db.device_heartbeat(trial["id"], "court-device", "Office PC", session)

    def find(**params):
        answer = client.get("/founder/api/users/find", params=params, headers=founder)
        assert answer.status_code == 200, answer.text
        return answer.json()

    everyone = find()
    assert everyone["counts"] == {"all": 5, "paying": 1, "trial": 3, "test": 1, "suspended": 1}
    rows = {row["email"]: row for row in everyone["users"]}
    assert len(rows) == 5
    assert rows[TEST_ACCOUNT]["test"] is True and rows[USER]["test"] is False
    assert rows[FOUNDER]["founder"] is True and rows[USER]["founder"] is False
    assert rows["stopped.one@studio.example"]["suspended_reason"] == "court"
    assert rows[USER]["devices"] == 1 and rows[USER]["last_seen"] is None
    assert [row["email"] for row in find(only="paying")["users"]] == ["paying.one@studio.example"]
    assert [row["email"] for row in find(only="test")["users"]] == [TEST_ACCOUNT]
    assert [row["email"] for row in find(only="suspended")["users"]] == ["stopped.one@studio.example"]
    assert {row["email"] for row in find(only="trial")["users"]} == {
        FOUNDER, USER, "stopped.one@studio.example"}
    assert [row["email"] for row in find(q="planner")["users"]] == [USER]      # by name
    assert session not in json.dumps(everyone)


def test_a_suspend_without_the_typed_word_changes_nothing(client):
    import db
    session = _auth(USER)
    for body in ({"reason": "court"}, {"reason": "court", "typed": "yes"}):
        refused = client.post("/founder/api/users/%s/suspend" % USER, headers=_auth(FOUNDER), json=body)
        assert refused.status_code == 400, refused.text
    assert client.get("/v1/me", headers=session).status_code == 200
    assert db.get_user_by_email(USER)["suspended_at"] is None and _logged("user.suspend") == []
    done = client.post("/founder/api/users/%s/suspend" % USER, headers=_auth(FOUNDER),
                       json={"reason": "court", "typed": "SUSPEND"})
    assert done.status_code == 200, done.text
    assert client.get("/v1/me", headers=session).status_code == 401
    (row,) = _logged("user.suspend")
    assert row["target"] == USER and json.loads(row["result"]) == {"reason": "court"}


def test_a_purge_without_the_typed_word_deletes_nothing(client):
    import db
    db.get_or_create_user(TEST_ACCOUNT)
    db.get_or_create_user(USER)
    for body in ({"confirm": True}, {"confirm": True, "typed": "remove"}):
        refused = client.post("/founder/api/purge-test-users", headers=_auth(FOUNDER), json=body)
        assert refused.status_code == 400, refused.text
    assert db.get_user_by_email(TEST_ACCOUNT) is not None and _logged("purge_test_users") == []
    done = client.post("/founder/api/purge-test-users", headers=_auth(FOUNDER),
                       json={"confirm": True, "typed": "DELETE"})
    assert done.status_code == 200 and done.json()["purged"] == 1
    assert db.get_user_by_email(TEST_ACCOUNT) is None and db.get_user_by_email(USER) is not None
    (row,) = _logged("purge_test_users")
    assert json.loads(row["result"])["emails"] == [TEST_ACCOUNT]


def test_the_companies_list_shows_owner_and_seats(client):
    import db
    owner = db.get_or_create_user("owner.one@studio.example")
    company = db.create_company(name="Court Studio", owner_user_id=owner["id"], plan="studio",
                                seat_limit=5)
    db.add_company_member(company_id=company["id"], user_id=db.get_or_create_user(USER)["id"],
                          invited_by_user_id=owner["id"])
    answer = client.get("/founder/api/companies", headers=_auth(FOUNDER))
    assert answer.status_code == 200, answer.text
    (row,) = answer.json()["companies"]
    assert (row["name"], row["plan"], row["owner_email"], row["seats_used"], row["seat_limit"]) == (
        "Court Studio", "studio", "owner.one@studio.example", 2, 5)


ASSETS = __import__("pathlib").Path(__file__).resolve().parents[1] / "cockpit_assets"
FONT_SOURCE = __import__("pathlib").Path(__file__).resolve().parents[3] / "01.APP" / "nodelang" / "data" / "website" / "fonts"


@pytest.mark.parametrize("name", ["inter-variable.woff2", "jetbrains-mono-regular.woff2"])
def test_the_fonts_are_byte_copies_served_by_the_founder_gate(client, name):
    copy = ASSETS / "fonts" / name
    assert copy.read_bytes() == (FONT_SOURCE / name).read_bytes(), "%s drifted from its source" % name
    page = client.get("/founder", headers=_auth(FOUNDER)).text
    assert "fonts.googleapis.com" not in page and "fonts.gstatic.com" not in page
    assert "/founder/map-assets/fonts/%s" % name in page
    served = client.get("/founder/map-assets/fonts/%s" % name, headers=_auth(FOUNDER))
    assert served.status_code == 200 and served.content == copy.read_bytes()
    assert client.get("/founder/map-assets/fonts/%s" % name,
                      headers=_auth(STRANGER)).status_code == 403


def test_the_founder_manages_a_company_and_each_change_is_logged(client):
    import db
    owner = db.get_or_create_user("owner.two@studio.example")
    member = db.get_or_create_user(USER)
    company = db.create_company(name="Seat Studio", owner_user_id=owner["id"], plan="studio",
                                seat_limit=5)
    db.add_company_member(company_id=company["id"], user_id=member["id"],
                          invited_by_user_id=owner["id"])
    base = "/founder/api/companies/%s" % company["id"]
    for path, body in (("/ai-mode", {"ai_mode": "hosted"}), ("/owner", {"user_id": member["id"]})):
        assert client.post(base + path, headers=_auth(STRANGER), json=body).status_code == 403
    assert client.get(base, headers=_auth(STRANGER)).status_code == 403

    detail = client.get(base, headers=_auth(FOUNDER)).json()
    assert {m["email"]: m["role"] for m in detail["members"]} == {
        "owner.two@studio.example": "owner", USER: "member"}


    assert client.post(base + "/ai-mode", headers=_auth(FOUNDER),
                       json={"ai_mode": "anything"}).status_code == 400
    assert client.post(base + "/ai-mode", headers=_auth(FOUNDER),
                       json={"ai_mode": "hosted"}).status_code == 200
    assert db.get_company(company["id"])["ai_mode"] == "hosted"

    stranger = db.get_or_create_user(STRANGER)
    assert client.post(base + "/owner", headers=_auth(FOUNDER),
                       json={"user_id": stranger["id"]}).status_code == 404
    moved = client.post(base + "/owner", headers=_auth(FOUNDER), json={"user_id": member["id"]})
    assert moved.status_code == 200, moved.text
    assert db.get_company(company["id"])["owner_user_id"] == member["id"]
    assert db.get_membership(company["id"], owner["id"])["role"] == "admin"
    (row,) = _logged("company.owner")
    assert row["target"] == "Seat Studio" and json.loads(row["result"]) == {"owner": USER}
    assert len(_logged("company.ai_mode")) == 1


def test_the_founder_emails_one_person_through_the_one_sender(client, monkeypatch):
    import db
    import email_sender
    db.get_or_create_user(USER)
    sent = []

    async def fake_send(*, to, subject, text, html):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(email_sender, "send_outcome", _outcome(fake_send))
    route = "/founder/api/users/%s/email" % USER
    assert client.post(route, headers=_auth(STRANGER),
                       json={"subject": "Hi", "text": "Body"}).status_code == 403
    assert client.post(route, headers=_auth(FOUNDER), json={"subject": "Hi"}).status_code == 400
    assert sent == [] and _logged("user.email") == []
    done = client.post(route, headers=_auth(FOUNDER),
                       json={"subject": "Your seat", "text": "A private note about the seat."})
    assert done.status_code == 200, done.text
    assert sent == [(USER, "Your seat", "A private note about the seat.")]
    (row,) = _logged("user.email")
    assert row["target"] == USER
    assert json.loads(row["result"]) == {"subject": "Your seat", "chars": 30, "outcome": "accepted"}

    async def refuse(**_kwargs):
        return False

    monkeypatch.setattr(email_sender, "send_outcome", _outcome(refuse))
    failed = client.post(route, headers=_auth(FOUNDER), json={"subject": "Again", "text": "x"})
    assert failed.status_code == 502 and not _logged("user.email")[0]["ok"]


def test_the_founder_invites_into_a_company_within_its_seats(client, monkeypatch):
    import db
    import email_sender
    links = []

    async def fake_invite(*, to, link):
        links.append((to, link))
        return True

    monkeypatch.setattr(email_sender, "send_company_invite_outcome", _outcome(fake_invite))
    owner = db.get_or_create_user("owner.three@studio.example")
    company = db.create_company(name="Invite Studio", owner_user_id=owner["id"], plan="studio",
                                seat_limit=2)
    route = "/founder/api/companies/%s/invite" % company["id"]
    assert client.post(route, headers=_auth(STRANGER), json={"email": USER}).status_code == 403
    assert client.post(route, headers=_auth(FOUNDER), json={"email": "not-an-email"}).status_code == 400
    done = client.post(route, headers=_auth(FOUNDER), json={"email": USER})
    assert done.status_code == 200, done.text
    assert "token" not in done.json() and [to for to, _ in links] == [USER]
    full = client.post(route, headers=_auth(FOUNDER), json={"email": "third@studio.example"})
    assert full.status_code == 400 and len(links) == 1
    rows = _logged("company.invite")
    assert [json.loads(r["result"]) for r in rows] == [
        {"email": "third@studio.example", "refused": "every seat is taken; add a seat first"},
        {"email": USER, "role": "member", "outcome": "accepted"}]
    assert all("token" not in r["result"] for r in rows)


# --- Round two: feedback, community bans and packs, leftovers -------------------

def _fake_mail(monkeypatch, ok=True):
    import email_sender
    sent = []

    async def fake_send(*, to, subject, text, html):
        sent.append((to, subject, text))
        return ok

    monkeypatch.setattr(email_sender, "send_outcome", _outcome(fake_send))
    return sent


def test_feedback_is_sent_signed_in_and_the_founder_works_it(client, monkeypatch):
    import db
    sent = _fake_mail(monkeypatch)
    person = _auth(USER)
    assert client.post("/v1/feedback", json={"text": "x"}).status_code == 401
    assert client.post("/v1/feedback", headers=person, json={"text": "  "}).status_code == 400
    first = client.post("/v1/feedback", headers=person,
                        json={"text": "Export froze Revit.", "type": "bug"}).json()["id"]
    second = client.post("/v1/feedback", headers=person,
                         json={"text": "Export froze again.", "type": "bug"}).json()["id"]
    founder = _auth(FOUNDER)
    for path in ("/founder/api/feedback", "/founder/api/feedback/%s" % first):
        assert client.get(path, headers=_auth(STRANGER)).status_code == 403
    listed = client.get("/founder/api/feedback?status=new", headers=founder).json()
    assert {row["id"] for row in listed["feedback"]} == {first, second}
    assert listed["counts"]["new"] == 2 and listed["feedback"][0]["email"] == USER
    assert {item["id"] for item in _inbox(client) if item["kind"] == "feedback"} == {first, second}

    assert client.post("/founder/api/feedback/%s/status" % first, headers=founder,
                       json={"status": "done"}).status_code == 400
    assert client.post("/founder/api/feedback/%s/status" % first, headers=founder,
                       json={"status": "shipped"}).status_code == 200
    assert client.post("/founder/api/feedback/%s/plan" % first, headers=founder,
                       json={"plan_row": "drop table"}).status_code == 400
    assert client.post("/founder/api/feedback/%s/plan" % first, headers=founder,
                       json={"plan_row": "R238"}).status_code == 200
    assert client.post("/founder/api/feedback/%s/reply" % first, headers=founder,
                       json={"text": ""}).status_code == 400
    answered = client.post("/founder/api/feedback/%s/reply" % first, headers=founder,
                           json={"text": "Fixed in the next build."})
    assert answered.status_code == 200, answered.text
    assert sent == [(USER, "About your ArchHub feedback", "Fixed in the next build.")]
    assert client.post("/founder/api/feedback/%s/merge" % second, headers=founder,
                       json={"into": first}).status_code == 200
    row = client.get("/founder/api/feedback/%s" % first, headers=founder).json()["feedback"]
    assert (row["status"], row["plan_row"], [r["text"] for r in row["replies"]]) == (
        "shipped", "R238", ["Fixed in the next build."])
    assert db.get_user_by_email(USER)["id"] == row["user_id"]
    assert client.get("/founder/api/feedback", headers=founder).json()["counts"]["new"] == 0
    assert [json.loads(r["result"])["to"] for r in _logged("feedback.status")] == ["shipped"]
    assert _logged("feedback.plan") and _logged("feedback.reply") and _logged("feedback.merge")


def test_a_ban_needs_the_word_stops_community_shares_and_is_reversible(client):
    import community_review
    import db
    member = db.get_or_create_user(USER)
    route = "/founder/api/community/ban"
    assert client.post(route, headers=_auth(STRANGER), json={"user": USER}).status_code == 403
    for body in ({"user": USER, "reason": "client data"}, {"user": USER, "typed": "BAN"},
                 {"user": USER, "reason": "client data", "typed": "ban it"}):
        assert client.post(route, headers=_auth(FOUNDER), json=body).status_code == 400
    assert client.post(route, headers=_auth(FOUNDER),
                       json={"user": FOUNDER, "reason": "x", "typed": "BAN"}).status_code == 409
    assert not db.is_community_banned(member["id"]) and _logged("community.ban") == []
    assert client.post(route, headers=_auth(FOUNDER),
                       json={"user": USER, "reason": "client data", "typed": "BAN"}).status_code == 200
    delta = {"fragments": [{"scope": "community", "id": "frag-b", "hlc": "h1", "text": "A tip.",
                            "extra": {"community_id": "revit-tips"}}]}
    community_review.submit_versions(member["id"], delta, {}, ["revit-tips"])
    assert db.pending_community_versions() == []
    assert [b["email"] for b in client.get("/founder/api/community/bans",
                                           headers=_auth(FOUNDER)).json()["bans"]] == [USER]
    assert client.post("/founder/api/community/unban", headers=_auth(FOUNDER),
                       json={"user": USER}).status_code == 200
    community_review.submit_versions(member["id"], delta, {}, ["revit-tips"])
    assert len(db.pending_community_versions()) == 1
    assert json.loads(_logged("community.ban")[0]["result"])["reason"] == "client data"
    assert _logged("community.unban")[0]["target"] == USER


def test_a_pack_take_down_needs_the_word_hides_it_and_is_reversible(client):
    import time
    import db
    author = db.get_or_create_user(USER)
    with db.connect() as con:
        con.execute("INSERT INTO marketplace_packs (id, slug, title, author_user_id, manifest_json, "
                    "signature, pubkey, status, created_at, updated_at) VALUES ('pk_court', "
                    "'court-pack', 'Court pack', ?, '{}', 's', 'k', 'approved', ?, ?)",
                    (author["id"], int(time.time()), int(time.time())))
        con.execute("INSERT INTO marketplace_reports (pack_id, reporter_user_id, reason, created_at) "
                    "VALUES ('pk_court', ?, 'Contains a client logo', ?)", (author["id"], int(time.time())))
    assert [i["id"] for i in _inbox(client) if i["kind"] == "pack_reported"] == ["pk_court"]
    (pack,) = client.get("/founder/api/packs", headers=_auth(FOUNDER)).json()["packs"]
    assert pack["reports"][0]["reason"] == "Contains a client logo"
    route = "/founder/api/packs/pk_court/takedown"
    assert client.post(route, headers=_auth(STRANGER), json={}).status_code == 403
    assert client.post(route, headers=_auth(FOUNDER), json={"reason": "logo"}).status_code == 400
    assert client.get("/marketplace/packs/pk_court").status_code == 200
    assert client.post(route, headers=_auth(FOUNDER),
                       json={"reason": "logo", "typed": "TAKEDOWN"}).status_code == 200
    assert client.get("/marketplace/packs/pk_court").status_code == 404
    assert client.get("/marketplace/packs/pk_court/download").status_code == 404
    assert [i for i in _inbox(client) if i["kind"] == "pack_reported"] == []
    assert client.post("/founder/api/packs/pk_court/restore", headers=_auth(FOUNDER)).status_code == 200
    assert client.get("/marketplace/packs/pk_court").status_code == 200
    assert _logged("pack.takedown")[0]["target"] == "pk_court" and _logged("pack.restore")


def test_delete_closes_the_account_keeps_its_rows_and_restore_reopens_it(client):
    import db
    session = _auth(USER)
    route = "/founder/api/users/%s/delete" % USER
    assert client.post(route, headers=_auth(STRANGER), json={"typed": "DELETE"}).status_code == 403
    assert client.post(route, headers=_auth(FOUNDER), json={"typed": "delete it"}).status_code == 400
    assert client.post("/founder/api/users/%s/delete" % FOUNDER, headers=_auth(FOUNDER),
                       json={"typed": "DELETE"}).status_code == 409
    assert client.get("/v1/me", headers=session).status_code == 200
    assert client.post(route, headers=_auth(FOUNDER), json={"typed": "DELETE"}).status_code == 200
    assert client.get("/v1/me", headers=session).status_code == 401
    row = db.get_user_by_email(USER)
    assert row is not None and row["deleted_at"] is not None              # nothing removed
    assert json.loads(_logged("user.delete")[0]["result"])["data_removed"] is False
    assert client.post("/founder/api/users/%s/restore" % USER, headers=_auth(FOUNDER)).status_code == 200
    assert db.get_user_by_email(USER)["deleted_at"] is None
    assert db.get_user_by_email(USER)["suspended_at"] is None


def _typed_routes():
    """Every typed confirmation in the panel: route, body without the word, the word."""
    return [
        ("/founder/api/users/%s/suspend" % USER, {"reason": "court"}, "SUSPEND"),
        ("/founder/api/users/%s/delete" % USER, {"reason": "court"}, "DELETE"),
        ("/founder/api/community/ban", {"user": USER, "reason": "court"}, "BAN"),
        ("/founder/api/packs/pk_typed/takedown", {"reason": "court"}, "TAKEDOWN"),
        ("/founder/api/purge-test-users", {"confirm": True}, "DELETE"),
        ("/founder/api/relay/drain", {"reason": "court"}, "DRAIN"),
    ]


@pytest.mark.parametrize("route,body,word", _typed_routes())
def test_every_typed_confirmation_is_checked_on_the_server(client, route, body, word):
    import time
    import db
    author = db.get_or_create_user(USER)
    db.get_or_create_user(TEST_ACCOUNT)
    with db.connect() as con:
        con.execute("INSERT INTO marketplace_packs (id, slug, title, author_user_id, manifest_json, "
                    "signature, pubkey, status, created_at, updated_at) VALUES ('pk_typed', 'typed-pack', "
                    "'Typed pack', ?, '{}', 's', 'k', 'approved', ?, ?)",
                    (author["id"], int(time.time()), int(time.time())))
    before = len(db.recent_founder_actions(500))
    for typed in (None, "", word.lower() + "x", "YES"):
        payload = dict(body) if typed is None else dict(body, typed=typed)
        assert client.post(route, headers=_auth(FOUNDER), json=payload).status_code == 400, (route, typed)
    assert db.get_user_by_email(USER)["suspended_at"] is None
    assert not db.is_community_banned(author["id"])
    assert db.get_user_by_email(TEST_ACCOUNT) is not None
    with db.connect() as con:
        assert con.execute("SELECT status FROM marketplace_packs WHERE id = 'pk_typed'").fetchone()[0] == "approved"
    assert len(db.recent_founder_actions(500)) == before                  # nothing acted, nothing logged


def test_a_refund_without_the_typed_word_never_reaches_stripe(client, monkeypatch):
    import billing
    import db
    called = []
    monkeypatch.setattr(billing, "refund_payment", lambda **kw: called.append(kw) or {"id": "re_x"})
    founder = db.get_or_create_user(FOUNDER)
    token = db.issue_refund_confirmation(founder_id=founder["id"], payment_intent="pi_court",
                                         amount=500, currency="usd")
    for typed in (None, "refund please", ""):
        body = {"confirm_token": token, "reason": "court"}
        if typed is not None:
            body["typed"] = typed
        assert client.post("/founder/api/stripe/refund", headers=_auth(FOUNDER), json=body).status_code == 400
    assert called == []
    done = client.post("/founder/api/stripe/refund", headers=_auth(FOUNDER),
                       json={"confirm_token": token, "reason": "court", "typed": "REFUND"})
    assert done.status_code == 200, done.text
    assert len(called) == 1


@pytest.mark.parametrize("raw,status", [
    (b"x" * 5000, 413),                                                   # over 4096 bytes, unread
    (b'{"text": "ok", "extra": 1}', 400),                                 # unknown field
    (b'{"text": 7}', 400),
    (b'{"text": "' + b"a" * 2001 + b'"}', 400),                           # 2001 characters: refused, not cut
    (b'{"text": "ok", "type": "rant"}', 400),
    (b'{"text": "ok", "source": "email"}', 400),
    (b'["text"]', 400),
    (b"not json", 400),
])
def test_feedback_bodies_are_bounded_and_validated(client, raw, status):
    import db
    answer = client.post("/v1/feedback", headers=dict(_auth(USER), **{"Content-Type": "application/json"}),
                         content=raw)
    assert answer.status_code == status, answer.text
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


def test_feedback_is_limited_per_person(client):
    person = _auth(USER)
    for n in range(5):
        assert client.post("/v1/feedback", headers=person, json={"text": "note %d" % n}).status_code == 200
    assert client.post("/v1/feedback", headers=person, json={"text": "sixth"}).status_code == 429
    assert client.post("/v1/feedback", headers=_auth("other.person@studio.example"),
                       json={"text": "mine"}).status_code == 200          # per person, not global


def test_marking_an_error_fixed_and_the_daily_usage(client):
    import db
    import founder_cockpit
    founder_cockpit.clear_errors()
    founder_cockpit.record_error(where="POST /v1/court", kind="TimeoutError", message="slow", status=504)
    founder_cockpit.record_error(where="POST /v1/court", kind="TimeoutError", message="slow", status=504)
    assert client.post("/founder/api/errors/resolve", headers=_auth(STRANGER),
                       json={"where": "POST /v1/court", "kind": "TimeoutError"}).status_code == 403
    done = client.post("/founder/api/errors/resolve", headers=_auth(FOUNDER),
                       json={"where": "POST /v1/court", "kind": "TimeoutError"})
    assert done.status_code == 200 and done.json()["removed"] == 2
    assert client.get("/founder/api/errors", headers=_auth(FOUNDER)).json()["errors"] == []
    assert _logged("errors.resolve")
    real = db.get_or_create_user(USER)
    test = db.get_or_create_user(TEST_ACCOUNT)
    db.log_usage(real["id"], model="claude-sonnet", input_toks=10, output_toks=10, cost_micros=3000)
    db.log_usage(real["id"], model="gpt-5", input_toks=10, output_toks=10, cost_micros=1000)
    db.log_usage(test["id"], model="claude-sonnet", input_toks=10, output_toks=10, cost_micros=9000)
    daily = client.get("/founder/api/usage/daily", headers=_auth(FOUNDER)).json()
    assert [(d["claude"], d["gpt"], d["other"]) for d in daily["days"]] == [(1, 1, 0)]
    assert [(t["email"], t["cost_micros"]) for t in daily["top"]] == [(USER, 4000)]
    me = client.get("/founder/api/overview", headers=_auth(FOUNDER)).json()["me"]
    assert me["email"] == FOUNDER


# --- Round four: truthful restore ---------------------------------------------

def test_reopening_a_deleted_account_reports_a_suspension_that_survives(client):
    import db
    member = db.get_or_create_user(USER)
    db.set_user_suspended(member["id"], "payment disputed")
    assert client.post("/founder/api/users/%s/delete" % USER, headers=_auth(FOUNDER),
                       json={"typed": "DELETE"}).status_code == 200
    reopened = client.post("/founder/api/users/%s/restore" % USER, headers=_auth(FOUNDER)).json()["user"]
    assert reopened["deleted_at"] is None and reopened["suspended_at"] is not None
    assert reopened["suspended_reason"] == "payment disputed"
    plain = client.post("/founder/api/users/%s/restore" % USER, headers=_auth(FOUNDER)).json()["user"]
    assert plain["suspended_at"] is None                                  # a second restore lifts it


# --- Round six: one confirmed action, once ----------------------------------------

def _mailer(monkeypatch, accept=True):
    import email_sender
    sent = []

    async def send(*, to, subject, text, html):
        sent.append((to, subject))
        return accept

    async def invite(*, to, link):
        sent.append((to, "invite"))
        return accept

    monkeypatch.setattr(email_sender, "send_outcome", _outcome(send))
    monkeypatch.setattr(email_sender, "send_company_invite_outcome", _outcome(invite))
    return sent


def test_a_repeated_email_with_the_same_key_sends_once_and_returns_the_record(client, monkeypatch):
    sent = _mailer(monkeypatch)
    import db
    db.get_or_create_user(USER)
    route = "/founder/api/users/%s/email" % USER
    body = {"subject": "Seat", "text": "One note.", "action_key": "key-email-0001"}
    first = client.post(route, headers=_auth(FOUNDER), json=body)
    again = client.post(route, headers=_auth(FOUNDER), json=body)
    assert first.status_code == again.status_code == 200
    assert again.json()["repeat"] is True and again.json()["emailed"] is True
    assert sent == [(USER, "Seat")] and len(_logged("user.email")) == 1
    changed = client.post(route, headers=_auth(FOUNDER), json=dict(body, text="Another note."))
    assert changed.status_code == 409 and changed.json()["state"] == "refused" and len(sent) == 1
    fresh = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-email-0002"))
    assert fresh.status_code == 200 and len(sent) == 2                    # a new deliberate send
    for bad in (dict(body, action_key=None), dict(body, action_key="short")):
        assert client.post(route, headers=_auth(FOUNDER), json=bad).status_code == 400


def test_a_repeated_reply_with_the_same_key_answers_once(client, monkeypatch):
    sent = _mailer(monkeypatch)
    import db
    import feedback
    row = feedback.submit(db.get_or_create_user(USER)["id"], "Export froze.", "bug")
    route = "/founder/api/feedback/%s/reply" % row["id"]
    body = {"text": "Fixed.", "action_key": "key-reply-0001"}
    for _ in range(3):
        assert client.post(route, headers=_auth(FOUNDER), json=body).status_code == 200
    assert len(sent) == 1 and len(feedback.get(row["id"])["replies"]) == 1
    assert len(_logged("feedback.reply")) == 1


def test_a_repeated_invite_with_the_same_key_makes_one_token_and_holds_one_seat(client, monkeypatch):
    sent = _mailer(monkeypatch)
    import db
    owner = db.get_or_create_user("owner.six@studio.example")
    company = db.create_company(name="Six Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    route = "/founder/api/companies/%s/invite" % company["id"]
    body = {"email": USER, "action_key": "key-invite-0001"}
    for _ in range(3):
        assert client.post(route, headers=_auth(FOUNDER), json=body).status_code == 200
    assert len(sent) == 1 and db.count_outstanding_invites(company["id"]) == 1


def test_an_action_claimed_but_unfinished_is_in_flight_then_uncertain_never_replayed(client, monkeypatch):
    import time
    import db
    sent = _mailer(monkeypatch)
    db.get_or_create_user(USER)
    route = "/founder/api/users/%s/email" % USER
    body = {"subject": "Seat", "text": "One note.", "action_key": "key-stuck-0001"}
    import founder_cockpit
    digest = founder_cockpit._body_hash("POST /founder/api/users/{key}/email", USER, body)
    db.claim_action_key(key="key-stuck-0001", founder=FOUNDER, route="POST /founder/api/users/{key}/email",
                        target=USER, body_hash=digest)                    # a send that never finished
    flight = client.post(route, headers=_auth(FOUNDER), json=body)
    assert flight.status_code == 409 and flight.json()["state"] == "in_flight"
    with db.connect() as con:
        con.execute("UPDATE founder_action_keys SET claimed_at = ? WHERE key = 'key-stuck-0001'",
                    (int(time.time()) - 3600,))
    unsure = client.post(route, headers=_auth(FOUNDER), json=body)
    assert unsure.status_code == 409 and unsure.json()["state"] == "uncertain"
    assert "may have been sent" in unsure.json()["error"] and sent == []


@pytest.mark.parametrize("route_of", ["email", "reply", "invite"])
def test_a_refused_email_is_reported_as_not_emailed(client, monkeypatch, route_of):
    import db
    import feedback
    sent = _mailer(monkeypatch, accept=False)
    user = db.get_or_create_user(USER)
    owner = db.get_or_create_user("owner.seven@studio.example")
    company = db.create_company(name="Seven Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    row = feedback.submit(user["id"], "Export froze.", "bug")
    route, body = {
        "email": ("/founder/api/users/%s/email" % USER, {"subject": "Hi", "text": "A note."}),
        "reply": ("/founder/api/feedback/%s/reply" % row["id"], {"text": "Fixed."}),
        "invite": ("/founder/api/companies/%s/invite" % company["id"], {"email": "new.seven@studio.example"}),
    }[route_of]
    answer = client.post(route, headers=_auth(FOUNDER), json=body)
    assert answer.status_code == 502 and answer.json()["ok"] is False
    assert answer.json()["emailed"] is False and answer.json()["retryable"] is True
    assert len(sent) == 1
    if route_of == "invite":
        assert answer.json()["created"] is True                           # the invite exists, unmailed
    if route_of == "reply":
        assert feedback.get(row["id"])["replies"] == []                   # nothing claims an answer went out


def test_an_invite_goes_to_the_company_opened_when_two_share_a_name(client, monkeypatch):
    _mailer(monkeypatch)
    import db
    owner = db.get_or_create_user("owner.same@studio.example")
    first = db.create_company(name="Same Name", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    second = db.create_company(name="Same Name", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    listed = client.get("/founder/api/companies", headers=_auth(FOUNDER)).json()["companies"]
    assert len({c["slug"] for c in listed if c["name"] == "Same Name"}) == 2  # the page can tell them apart
    assert client.post("/founder/api/companies/%s/invite" % second["id"], headers=_auth(FOUNDER),
                       json={"email": USER}).status_code == 200
    assert db.count_outstanding_invites(second["id"]) == 1
    assert db.count_outstanding_invites(first["id"]) == 0


def test_the_owner_invite_answer_is_unchanged(client, monkeypatch):
    _mailer(monkeypatch, accept=False)                                    # even when the mail is refused
    import db
    owner = db.get_or_create_user("owner.eight@studio.example")
    company = db.create_company(name="Eight Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    answer = client.post("/v1/companies/%s/invites" % company["id"], headers=_auth("owner.eight@studio.example"),
                         json={"email": USER, "role": "member"})
    assert answer.status_code == 200, answer.text
    assert set(answer.json()) == {"token", "email", "role", "expires_at", "invite_url"}


# --- Round seven: three mail outcomes; uncertain is held, journaled, resolved ----

class _Provider:
    """A fake mail provider behind httpx: each call takes the next scripted answer."""
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def client(self, *args, **kwargs):
        provider = self

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, *a, **k):
                provider.calls += 1
                answer = provider.answers.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return _Client()


def _http(status, body):
    import httpx
    return httpx.Response(status, content=body, request=httpx.Request("POST", "https://mail.example.test"))


@pytest.mark.parametrize("answer,outcome,old_bool", [
    ("200", "accepted", True),
    ("422-json", "refused", False),
    ("400-garbage", "unknown", False),
    ("503", "unknown", False),
    ("timeout-after-accept", "unknown", False),
])
def test_the_mailer_has_three_outcomes_and_the_old_answer_is_unchanged(monkeypatch, answer, outcome, old_bool):
    import asyncio
    import httpx
    import config
    import email_sender
    make = {"200": lambda: _http(200, b'{"id":"m1"}'), "422-json": lambda: _http(422, b'{"message":"bad address"}'),
            "400-garbage": lambda: _http(400, b"<html>oops"), "503": lambda: _http(503, b'{"message":"busy"}'),
            "timeout-after-accept": lambda: httpx.ReadTimeout("the provider took it, the answer never came")}[answer]
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_not_a_key")
    provider = _Provider([make(), make()])
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", provider.client)
    mail = {"to": USER, "subject": "s", "text": "t", "html": "h"}
    assert asyncio.run(email_sender.send_outcome(**mail)) == outcome
    assert asyncio.run(email_sender._send(**mail)) is old_bool              # existing callers: as before


def _unknown_mail(monkeypatch):
    import email_sender
    sent = []

    async def unknown(**kwargs):
        sent.append(kwargs["to"])
        return "unknown"

    monkeypatch.setattr(email_sender, "send_outcome", unknown)
    monkeypatch.setattr(email_sender, "send_company_invite_outcome", unknown)
    return sent


def test_an_unknown_send_is_held_until_resolved_then_sends_exactly_once(client, monkeypatch):
    import db
    import email_sender
    sent = _unknown_mail(monkeypatch)
    db.get_or_create_user(USER)
    route = "/founder/api/users/%s/email" % USER
    body = {"subject": "Seat", "text": "One note."}
    first = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-unknown-001"))
    assert first.status_code == 202 and first.json()["state"] == "uncertain" and first.json()["emailed"] is None
    again = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-unknown-001"))
    assert again.json()["state"] == "uncertain" and len(sent) == 1        # same key: the record, no send
    held = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-unknown-002"))
    assert held.status_code == 409 and held.json()["state"] == "held" and len(sent) == 1
    listed = client.get("/founder/api/actions/unresolved", headers=_auth(FOUNDER)).json()["actions"]
    assert [(a["key"], a["what"], a["target"], a["state"]) for a in listed] == [
        ("key-unknown-001", "Email", USER, "uncertain")]
    assert [i["id"] for i in _inbox(client) if i["kind"] == "unresolved"] == ["key-unknown-001"]
    check = client.post("/founder/api/actions/key/key-unknown-001/check", headers=_auth(FOUNDER)).json()
    assert check["action"]["state"] == "uncertain" and len(sent) == 1      # Check does nothing
    resolve = "/founder/api/actions/key/key-unknown-001/resolve"
    assert client.post(resolve, headers=_auth(STRANGER), json={"arrived": False}).status_code == 403
    assert client.post(resolve, headers=_auth(FOUNDER), json={"arrived": "no"}).status_code == 400
    assert client.post(resolve, headers=_auth(FOUNDER), json={"arrived": False}).status_code == 200
    assert client.post(resolve, headers=_auth(FOUNDER), json={"arrived": True}).status_code == 409   # once
    assert client.get("/founder/api/actions/unresolved", headers=_auth(FOUNDER)).json()["actions"] == []
    assert json.loads(_logged("action.resolve")[0]["result"])["arrived"] is False

    async def accepted(**kwargs):
        sent.append(kwargs["to"])
        return email_sender.ACCEPTED

    monkeypatch.setattr(email_sender, "send_outcome", accepted)
    fresh = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-unknown-003"))
    assert fresh.status_code == 200 and fresh.json()["emailed"] is True and len(sent) == 2


def test_resolving_as_arrived_closes_it_without_a_send(client, monkeypatch):
    import db
    sent = _unknown_mail(monkeypatch)
    import feedback
    row = feedback.submit(db.get_or_create_user(USER)["id"], "Export froze.", "bug")
    answer = client.post("/founder/api/feedback/%s/reply" % row["id"], headers=_auth(FOUNDER),
                         json={"text": "Fixed.", "action_key": "key-reply-unk-1"})
    assert answer.json()["state"] == "uncertain" and feedback.get(row["id"])["replies"] == []
    assert client.post("/founder/api/actions/key/key-reply-unk-1/resolve", headers=_auth(FOUNDER),
                       json={"arrived": True}).status_code == 200
    repeat = client.post("/founder/api/feedback/%s/reply" % row["id"], headers=_auth(FOUNDER),
                         json={"text": "Fixed.", "action_key": "key-reply-unk-1"})
    assert repeat.json()["state"] == "resolved_sent" and len(sent) == 1


def test_a_definite_refusal_can_be_sent_again_under_a_fresh_key(client, monkeypatch):
    import db
    sent = _mailer(monkeypatch, accept=False)
    db.get_or_create_user(USER)
    route = "/founder/api/users/%s/email" % USER
    body = {"subject": "Seat", "text": "One note."}
    refused = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-refused-01"))
    assert refused.status_code == 502 and refused.json()["refused"] is True and sent == [(USER, "Seat")]
    _mailer(monkeypatch, accept=True)
    again = client.post(route, headers=_auth(FOUNDER), json=dict(body, action_key="key-refused-02"))
    assert again.status_code == 200 and again.json()["emailed"] is True
    assert client.get("/founder/api/actions/unresolved", headers=_auth(FOUNDER)).json()["actions"] == []


def test_a_refused_invite_email_is_sent_again_for_the_same_invite(client, monkeypatch):
    import db
    sent = _mailer(monkeypatch, accept=False)
    owner = db.get_or_create_user("owner.nine@studio.example")
    company = db.create_company(name="Nine Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    made = client.post("/founder/api/companies/%s/invite" % company["id"], headers=_auth(FOUNDER),
                       json={"email": USER})
    assert made.status_code == 502 and made.json()["created"] is True and made.json()["refused"] is True
    assert sent == [(USER, "invite")]
    with db.connect() as con:
        tokens = [r[0] for r in con.execute("SELECT token FROM company_invites WHERE company_id = ?",
                                            (company["id"],)).fetchall()]
    _mailer(monkeypatch, accept=True)
    resend = "/founder/api/companies/%s/invite/resend" % company["id"]
    assert client.post(resend, headers=_auth(STRANGER), json={"email": USER}).status_code == 403
    done = client.post(resend, headers=_auth(FOUNDER), json={"email": USER})
    assert done.status_code == 200 and done.json()["emailed"] is True and done.json()["resent"] is True
    with db.connect() as con:
        after = [r[0] for r in con.execute("SELECT token FROM company_invites WHERE company_id = ?",
                                           (company["id"],)).fetchall()]
    assert after == tokens and len(tokens) == 1 and db.count_outstanding_invites(company["id"]) == 1
    assert client.post(resend, headers=_auth(FOUNDER), json={"email": "nobody@studio.example"}).status_code == 404


def test_an_unknown_invite_email_keeps_the_invite_and_is_held(client, monkeypatch):
    import db
    _unknown_mail(monkeypatch)
    owner = db.get_or_create_user("owner.ten@studio.example")
    company = db.create_company(name="Ten Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    made = client.post("/founder/api/companies/%s/invite" % company["id"], headers=_auth(FOUNDER),
                       json={"email": USER, "action_key": "key-invite-unk-1"})
    assert made.status_code == 202 and made.json()["state"] == "uncertain" and made.json()["created"] is True
    assert db.count_outstanding_invites(company["id"]) == 1
    held = client.post("/founder/api/companies/%s/invite" % company["id"], headers=_auth(FOUNDER),
                       json={"email": USER, "action_key": "key-invite-unk-2"})
    assert held.status_code == 409 and db.count_outstanding_invites(company["id"]) == 1


# --- Rounds nine and ten: one refund per payment; an unknown refund is never retried ---

class APIConnectionError(Exception):
    """Named like the Stripe SDK's connection error: Stripe's answer never came."""


class _ProcessDied(BaseException):
    """Not an Exception: nothing in the route catches it, as when the process is killed."""


class _StripeError(Exception):
    def __init__(self, status, kind):
        super().__init__(kind)
        self.http_status, self.json_body = status, {"error": {"type": kind, "message": kind}}


class _RefundStripe:
    """Stripe for refunds. `mode` decides the next create: ok, drop (refunded, answer
    lost), conflict (409), mismatch (idempotency error), card (definite refusal).
    `mutations` counts every create; `lists` counts the read-only reads."""
    def __init__(self):
        self.mode, self.mutations, self.lists, self.made, self.keys, self.calls = "ok", [], 0, [], [], []
        self.attempts = 0                                 # every Refund.create reached, counted before any raise
        stub = self

        class PaymentIntent:
            @staticmethod
            def retrieve(intent, **kw):
                return {"id": intent, "amount_received": 3900, "currency": "usd", "status": "succeeded",
                        "customer": {"email": "payer@studio.example"}}

        class Refund:
            @staticmethod
            def create(**kw):
                stub.attempts += 1
                if stub.mode == "die":
                    raise _ProcessDied("the process stopped inside the Stripe call")
                stub.mutations.append(kw["payment_intent"])
                stub.keys.append(kw.get("idempotency_key"))
                stub.calls.append(kw)
                mode, stub.mode = stub.mode, "ok"
                if mode == "conflict":
                    raise _StripeError(409, "idempotency_error")
                if mode == "mismatch":
                    raise _StripeError(400, "idempotency_error")
                if mode == "card":
                    raise _StripeError(402, "card_error")
                import time as _t
                refund = {"id": "re_%d" % (len(stub.made) + 1), "status": "succeeded", "amount": kw["amount"],
                          "currency": "usd", "created": int(_t.time()), "metadata": kw.get("metadata") or {},
                          "payment_intent": kw["payment_intent"]}
                stub.made.append(refund)
                if mode == "drop":
                    raise APIConnectionError("the refund was made; the answer never came")
                return refund

            @staticmethod
            def list(payment_intent=None, limit=100):
                stub.lists += 1
                return {"data": [r for r in stub.made if r["payment_intent"] == payment_intent]}

        self.PaymentIntent, self.Refund, self.api_key = PaymentIntent, Refund, None


@pytest.fixture
def stripe_stub(monkeypatch):
    import billing
    import config
    stub = _RefundStripe()
    monkeypatch.setattr(billing, "stripe", stub)
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_court")
    return stub


def _preview(client, intent="pi_court"):
    answer = client.post("/founder/api/stripe/refund", headers=_auth(FOUNDER),
                         json={"payment_intent": intent, "amount": 500, "reason": "court"})
    assert answer.status_code == 200, answer.text
    return answer.json()["confirm_token"]


def _confirm(client, token, key, **extra):
    return client.post("/founder/api/stripe/refund", headers=_auth(FOUNDER), json={
        "confirm_token": token, "reason": "court", "typed": "REFUND", "action_key": key, **extra})


def _unresolved(client):
    return client.get("/founder/api/actions/unresolved", headers=_auth(FOUNDER)).json()["actions"]


def test_one_unresolved_refund_per_payment_whatever_the_key(client, stripe_stub):
    import db
    first_token, second_token = _preview(client), _preview(client)
    # another worker's refund of this payment is in flight: its claim holds the payment
    assert db.claim_action_key(key="key-other-worker", founder=FOUNDER, route="POST /founder/api/stripe/refund",
                               target="pi_court", body_hash="x", hold="refund:pi_court") is None
    refused = _confirm(client, first_token, "key-refund-a")
    assert refused.status_code == 409 and refused.json()["state"] == "held" and stripe_stub.mutations == []
    db.finish_action_key("key-other-worker", status=200, result="{}")    # it finished: the hold is gone
    stripe_stub.mode = "drop"
    assert _confirm(client, first_token, "key-refund-b").json()["state"] == "uncertain"
    again = _confirm(client, second_token, "key-refund-c")
    assert again.status_code == 409 and again.json()["state"] == "held"
    assert stripe_stub.mutations == ["pi_court"]                          # exactly one reached Stripe


def test_the_payment_comes_from_the_confirmation_not_the_page(client, stripe_stub):
    token = _preview(client)
    done = _confirm(client, token, "key-refund-page", payment_intent="pi_someone_else")
    assert done.status_code == 200, done.text
    assert stripe_stub.mutations == ["pi_court"]
    assert stripe_stub.keys[0].startswith("archhub-refund-") and token not in stripe_stub.keys[0]


@pytest.mark.parametrize("mode", ["conflict", "mismatch"])
def test_a_conflict_or_idempotency_error_is_unknown_held_and_keeps_the_confirmation(client, stripe_stub, mode):
    token = _preview(client)
    stripe_stub.mode = mode
    answer = _confirm(client, token, "key-refund-" + mode)
    assert answer.status_code == 202 and answer.json()["state"] == "uncertain"
    assert [a["key"] for a in _unresolved(client)] == ["key-refund-" + mode]
    retry = _confirm(client, token, "key-refund-" + mode + "-2")
    assert retry.status_code == 409 and len(stripe_stub.mutations) == 1      # held, confirmation still used


def test_a_definite_card_refusal_releases_the_confirmation(client, stripe_stub):
    token = _preview(client)
    stripe_stub.mode = "card"
    refused = _confirm(client, token, "key-refund-card-1")
    assert refused.status_code == 502 and refused.json()["refused"] is True and _unresolved(client) == []
    assert _confirm(client, token, "key-refund-card-2").status_code == 200
    assert len(stripe_stub.made) == 1


def _age(key, seconds):
    import db
    with db.connect() as con:
        con.execute("UPDATE founder_action_keys SET claimed_at = claimed_at - ? WHERE key = ?", (seconds, key))


def _no_recovery_for(client, key):
    """Every recovery route refuses a refund action; nothing about it changes."""
    import db
    before = db.get_action_key(key)
    assert client.post("/founder/api/actions/key/%s/check" % key, headers=_auth(FOUNDER)).status_code == 409
    for arrived in (True, False):
        assert client.post("/founder/api/actions/key/%s/resolve" % key, headers=_auth(FOUNDER),
                           json={"arrived": arrived}).status_code == 409
    after = db.get_action_key(key)
    assert (after["state"], after["hold"]) == (before["state"], before["hold"]) and after["hold"]


def test_an_unknown_refund_keeps_its_payment_held_whatever_happens(client, stripe_stub):
    import db
    stripe_stub.mode = "drop"
    answer = _confirm(client, _preview(client), "key-refund-held", customer="lina@studio.example")
    assert answer.status_code == 202 and answer.json()["replay"]["message"].startswith("The refund's result is unknown")
    _age("key-refund-held", 90 * 86400)                                   # any amount of time
    _no_recovery_for(client, "key-refund-held")
    (row,) = _unresolved(client)
    assert (row["payment_intent"], row["amount"], row["currency"], row["customer"], row["money"]) == (
        "pi_court", 500, "usd", "payer@studio.example", True)                # the server's records, not the page's
    assert row["stripe_url"] == "https://dashboard.stripe.com/test/payments/pi_court"
    assert row["message"] == ("The refund's result is unknown. Look at this payment in Stripe. "
                              "The panel will not refund this payment again.")
    (item,) = [i for i in _inbox(client) if i["kind"] == "unresolved"]
    assert item["stripe_url"] == row["stripe_url"]
    again = _confirm(client, _preview(client), "key-refund-again")         # a fresh confirmation
    assert again.status_code == 409 and "will not refund this payment again" in again.json()["error"]
    assert stripe_stub.mutations == ["pi_court"]
    assert db.get_action_key("key-refund-held")["hold"] == "refund:pi_court"


def test_a_refund_claim_that_died_mid_call_holds_the_payment_the_same_way(client, stripe_stub):
    import db
    assert db.claim_action_key(key="key-refund-died", founder=FOUNDER, route="POST /founder/api/stripe/refund",
                               target="pi_court", body_hash="x", hold="refund:pi_court") is None
    _age("key-refund-died", 30 * 86400)                                   # never recorded an outcome
    _no_recovery_for(client, "key-refund-died")
    (row,) = _unresolved(client)
    assert row["state"] == "uncertain" and row["stripe_url"].endswith("/pi_court")
    # a row with no stored context: nothing invented, the page says "not recorded"
    assert (row["payment_intent"], row["amount"], row["currency"], row["customer"]) == ("pi_court", None, None, None)
    assert _confirm(client, _preview(client), "key-refund-after-died").status_code == 409
    assert stripe_stub.mutations == []


def test_a_refund_killed_inside_the_stripe_call_shows_what_the_server_stored(client, stripe_stub):
    import db
    token = _preview(client)
    stripe_stub.mode = "die"
    try:      # the kill: the test client may re-raise it or answer 500; either way no outcome is recorded
        _confirm(client, token, "key-refund-killed", customer="someone.else@example.test", amount=99999)
    except BaseException:
        pass
    assert stripe_stub.attempts == 1 and stripe_stub.mutations == []      # it reached Stripe once and died there
    row = db.get_action_key("key-refund-killed")
    assert row["state"] == "claimed" and row["result"] is None and row["hold"] == "refund:pi_court"
    stored = json.loads(row["context"])
    assert stored == {"payment": "pi_court", "amount": 500, "currency": "usd", "customer": "payer@studio.example",
                      "customer_error": None}
    _age("key-refund-killed", 3600)
    (view,) = _unresolved(client)
    assert (view["payment_intent"], view["amount"], view["currency"], view["customer"], view["state"]) == (
        "pi_court", 500, "usd", "payer@studio.example", "uncertain")
    (item,) = [i for i in _inbox(client) if i["kind"] == "unresolved"]
    assert (item["amount"], item["currency"], item["customer"]) == (500, "usd", "payer@studio.example")
    assert item["stripe_url"].endswith("/pi_court")
    db.set_action_context("key-refund-killed", correlation="act_other", context={"amount": 1, "customer": "x"})
    assert json.loads(db.get_action_key("key-refund-killed")["context"]) == stored          # written once
    _no_recovery_for(client, "key-refund-killed")


def test_the_refund_correlation_is_stored_before_the_call_and_sent_as_metadata(client, stripe_stub):
    import db
    assert _confirm(client, _preview(client), "key-refund-corr").status_code == 200
    (call,) = stripe_stub.calls
    correlation = db.get_action_key("key-refund-corr")["correlation"]
    assert correlation and call["metadata"]["archhub_action"] == correlation
    assert db.get_action_key("key-refund-corr")["route"] == "POST /founder/api/stripe/refund"   # the guard's stored route
    assert call["metadata"]["issued_by"] == FOUNDER and call["idempotency_key"].startswith("archhub-refund-")


def test_a_retry_of_the_same_confirmation_sends_the_identical_request(client, stripe_stub):
    token = _preview(client)
    stripe_stub.mode = "card"
    assert _confirm(client, token, "key-refund-try-1").status_code == 502
    assert _confirm(client, token, "key-refund-try-2").status_code == 200
    first, second = stripe_stub.calls
    assert first == second                                               # same key, same body


@pytest.mark.parametrize("secret,url", [
    ("sk_test_x", "https://dashboard.stripe.com/test/payments/pi_court"),
    ("rk_live_x", "https://dashboard.stripe.com/payments/pi_court"),
    ("", "https://dashboard.stripe.com/search?query=pi_court"),
])
def test_the_stripe_link_follows_the_configured_mode(monkeypatch, secret, url):
    import config
    import founder_cockpit
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", secret)
    assert founder_cockpit.stripe_payment_url("pi_court") == url


def test_the_owner_seat_route_answers_as_at_the_base(client):
    import db
    owner = db.get_or_create_user("owner.base@studio.example")
    company = db.create_company(name="Base Studio", owner_user_id=owner["id"], plan="studio", seat_limit=5)
    answer = client.post("/v1/companies/%s/seats" % company["id"], headers=_auth("owner.base@studio.example"),
                         json={"seats": 6})
    assert answer.status_code == 200 and answer.json() == {"ok": True, "company_id": company["id"],
                                                            "seat_limit": 6, "stripe": None}
    assert client.post("/founder/api/companies/%s/seats" % company["id"], headers=_auth(FOUNDER),
                       json={"seats": 7}).status_code in (404, 405)            # not a Cockpit action


def test_an_uncertain_feedback_answer_is_added_when_it_arrived(client, monkeypatch):
    import db
    import feedback
    _unknown_mail(monkeypatch)
    row = feedback.submit(db.get_or_create_user(USER)["id"], "Export froze.", "bug")
    client.post("/founder/api/feedback/%s/reply" % row["id"], headers=_auth(FOUNDER),
                json={"text": "Fixed in the next build.", "action_key": "key-reply-arr-01"})
    assert feedback.get(row["id"])["replies"] == []
    client.post("/founder/api/actions/key/key-reply-arr-01/resolve", headers=_auth(FOUNDER), json={"arrived": True})
    assert [r["text"] for r in feedback.get(row["id"])["replies"]] == ["Fixed in the next build."]
    other = feedback.submit(db.get_or_create_user(USER)["id"], "Second.", "bug")
    client.post("/founder/api/feedback/%s/reply" % other["id"], headers=_auth(FOUNDER),
                json={"text": "Not this one.", "action_key": "key-reply-arr-02"})
    client.post("/founder/api/actions/key/key-reply-arr-02/resolve", headers=_auth(FOUNDER), json={"arrived": False})
    assert feedback.get(other["id"])["replies"] == []
