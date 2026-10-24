"""SESSIONLINK2: original Workshop custody and real bounded worker, no live profiles."""
import time

from nodelang import workshop_mailbox as mail
from tests_replica.test_wsinject import declare, send
from tests_replica.test_newapp_mailbox import peer

pytest_plugins = ("tests_replica.test_wsinject",)


def test_held_question_preserves_original_reason_and_is_reminded_then_escalated(room):
    owner, history = room
    recipient = declare(owner, {"threadId": "codex-fixture"})

    class HeldTransport:
        calls = 0

        def inject(self, *_args, **_kwargs):
            self.calls += 1
            return {"status": "held", "delivery_status": "held", "delivery_reason": "draft_input_unknown"}

    transport = HeldTransport()
    delivery = mail.WorkshopInjection(owner, transport, reminder_minutes=1, escalation_minutes=2)
    note = send(owner, text="Preserve this question while its recipient types")
    started = time.time()
    delivery.tick(now=started)
    event = mail.delivery_events(history, {"id": note["message_id"]})[recipient["sender_key"]]["initial-outcome"]
    assert event["status"] == "held"
    assert event["delivery_reason"] == "draft_input_unknown"
    assert event["dispatch_attempted"] is False
    delivery.tick(now=started + 61)
    delivery = mail.WorkshopInjection(owner, transport, reminder_minutes=1, escalation_minutes=2)
    delivery.tick(now=started + 180)
    assert transport.calls == 2, "a held real ask still receives its one reminder"
    events = mail.delivery_events(history, {"id": note["message_id"]})[recipient["sender_key"]]
    assert events["reminder-outcome"]["status"] == "held"
    assert "escalated" in events
    delivery.tick(now=started + 240)
    assert transport.calls == 2, "escalation must not create repeated native input"
    assert history._db.execute("SELECT COUNT(*) FROM messages WHERE author='Workshop coordination' AND reply_to=?",
        (note["message_id"],)).fetchone()[0] == 1
    pending = owner.shared_agent_mail("pending", {"context": {"threadId": "codex-fixture"}}, peer=peer())
    assert any(row["id"] == note["message_id"] and "Preserve this question" in row["content"] for row in pending["pending"])
    assert history._db.execute("SELECT COUNT(*) FROM messages WHERE category=?", (mail.CATEGORY,)).fetchone()[0] == 2
