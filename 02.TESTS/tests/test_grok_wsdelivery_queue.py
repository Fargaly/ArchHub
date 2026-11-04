"""Queued Workshop handover with an isolated mailbox and real declare/pending/seen calls."""
from unittest.mock import patch

import pytest

from nodelang import workshop_live, workshop_mailbox as mailbox


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(mailbox, "mailbox_label", lambda peer, context:
        (context["threadId"], "grok" if context["threadId"] == "Grok" else "codex"))
    monkeypatch.setattr(mailbox, "_sender_may_push", lambda *args: True)
    monkeypatch.setattr(workshop_live, "live_agents", lambda: [])
    monkeypatch.setattr(workshop_live, "discover_target", lambda target: [])
    return tmp_path / "workshop" / "messages.sqlite3"


def send(database, to="Grok"):
    return mailbox.call("send", {"to": to, "text": "Coordinate this.", "idempotency_key": "queued"},
        {"threadId": "sender"}, database=database, one_shot=True)


def join(database, name):
    return mailbox.call("declare", {"task": "Queue handover", "paths": [str(database.parent)], "status": "working",
        "request_id": "unassigned"}, {"threadId": name}, database=database)


def receipts(database, message_id):
    with mailbox.application_history(database=database) as history:
        return [dict(row) for row in history._db.execute(
            "SELECT recipient, state, reason FROM workshop_live_deliveries WHERE message_id=?", (message_id,))]


def test_queued_pending(database):
    result = send(database)
    rows = receipts(database, result["message_id"])
    assert len(rows) == 1
    assert rows[0]["state"] == "pending"
    assert rows[0]["reason"] == "queued until Grok next starts"


def test_declare_joins(database):
    result = send(database)
    message_id = result["message_id"]
    assert receipts(database, message_id)[0]["state"] == "pending"
    other = join(database, "other")
    assert mailbox.call("pending", {}, {"threadId": "other"}, database=database)["pending"] == []
    peer = join(database, "Grok")
    pending = mailbox.call("pending", {}, {"threadId": "Grok"}, database=database)["pending"]
    assert [message["id"] for message in pending] == [message_id]
    mailbox.call("seen", {"message_ids": [message_id], "channel": "session-start hook"},
        {"threadId": "Grok"}, database=database)
    rows = receipts(database, message_id)
    assert rows == [{"recipient": peer["sender_key"], "state": "delivered",
        "reason": "handed over in session-start hook"}]
    assert all(row["recipient"] != other["sender_key"] for row in rows)
    assert mailbox.call("pending", {}, {"threadId": "Grok"}, database=database)["pending"] == []


@pytest.mark.parametrize("resolved_pending", [False, True])
def test_seen_reconciles_exact_seed_and_suppresses_resend(database, resolved_pending):
    result = send(database)
    message_id = result["message_id"]
    peer = join(database, "Grok")
    identity = {**peer, "sender_key": "agent:session:isolated"}
    with mailbox.application_history(database=database) as history:
        history._db.execute("DELETE FROM workshop_live_deliveries WHERE message_id=?", (message_id,))
        seed = (message_id, "Grok", "Grok", "", "", "workshop", "pending",
            "queued until Grok next starts", "2026-11-04T00:00:00+00:00", 0)
        history._db.execute("INSERT INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)", seed)
        if resolved_pending:
            history._db.execute("INSERT INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)",
                (message_id, identity["sender_key"], *seed[2:]))
        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.session',?)",
            (identity["sender_key"],))
        body = {"message_ids": [message_id], "channel": "session-start hook"}
        mailbox._seen(history, body, identity, "grok")
        mailbox._seen(history, body, identity, "grok")
        assert mailbox._pending(history, identity, "grok")["pending"] == []
        pushes = []
        with patch.object(workshop_live, "push", side_effect=lambda *a, **k: pushes.append(a)):
            repeated = workshop_live.deliver(history, message_id,
                [{"session": identity["sender_key"], "agent": "Grok", "runtime": "grok"}],
                "sender", "Coordinate this.")
        assert pushes == []
        assert repeated[0]["repeat"] is True
        assert repeated[0]["state"] == "delivered"
    assert receipts(database, message_id) == [{"recipient": identity["sender_key"], "state": "delivered",
        "reason": "handed over in session-start hook"}]


def test_seen_preserves_other_recipients_and_rejects_wrong_peer(database):
    result = send(database, "Grok, other")
    message_id = result["message_id"]
    grok = join(database, "Grok")
    join(database, "other")
    join(database, "unrelated")
    with mailbox.application_history(database=database) as history:
        history._db.execute("DELETE FROM workshop_live_deliveries WHERE message_id=?", (message_id,))
        for recipient, state in [("Grok", "pending"), ("other", "pending"), ("already-delivered", "delivered")]:
            history._db.execute("INSERT INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)",
                (message_id, recipient, recipient, "", "", "workshop", state, "original", "now", 0))
    body = {"message_ids": [message_id], "channel": "session-start hook"}
    before = receipts(database, message_id)
    mailbox.call("seen", body, {"threadId": "unrelated"}, database=database)
    mailbox.call("seen", body, {"threadId": "sender"}, database=database)
    assert receipts(database, message_id) == before
    mailbox.call("seen", body, {"threadId": "Grok"}, database=database)
    rows = {row["recipient"]: row for row in receipts(database, message_id)}
    assert set(rows) == {grok["sender_key"], "other", "already-delivered"}
    assert rows[grok["sender_key"]]["state"] == "delivered"
    assert rows["other"]["state"] == "pending"
    assert rows["already-delivered"]["reason"] == "original"


def test_sender_check_still_blocks_injection(database, monkeypatch):
    monkeypatch.setattr(mailbox, "_sender_may_push", lambda *args: False)
    monkeypatch.setattr(mailbox, "_deliver_now", lambda *args: pytest.fail("unverified sender pushed"))
    result = send(database)
    assert result["delivery"][0]["state"] == "failed"
    assert "Sender is not a running agent session" in result["delivery"][0]["reason"]
