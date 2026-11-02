"""Workshop routing: delivery only to the named agent, one task per agent, project rooms."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import psutil
import pytest

from nodelang.application_machine_transport import MachinePipePeer
from nodelang.workshop_mailbox import CATEGORY, ROOM, application_history, call
from nodelang import workshop_mailbox, workshop_tasks


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(workshop_mailbox, "_sender_may_push", lambda *args, **kwargs: False)
    process = psutil.Process()
    peer = MachinePipePeer(pid=process.pid, created_at=process.create_time(), cwd=str(tmp_path))
    (tmp_path / "10.PRODUCT" / "x").mkdir(parents=True)
    (tmp_path / "10.PRODUCT" / "y").mkdir(parents=True)
    (tmp_path / "10.PRODUCT" / "c").mkdir(parents=True)
    (tmp_path / "BBC4").mkdir()
    return tmp_path, peer


def _declare(peer, root, ctx, name, request, folder):
    return call("declare", {"task": name + " work", "paths": [str(root / folder)], "status": "working",
                            "request_id": request, "display_name": name}, ctx, peer=peer)


def _ids(page):
    return [row["id"] for row in page.get("pending", [])]


def test_addressed_message_reaches_only_its_addressee_and_unknown_returns(room):
    root, peer = room
    x = {"threadId": "agent-x"}
    y = {"claude/sessionID": "agent-y"}
    coordinator = {"claude/sessionID": "coordinator-717"}
    _declare(peer, root, x, "Agent X", "RX", "10.PRODUCT/x")
    sent_y = _declare(peer, root, y, "Agent Y", "RY", "10.PRODUCT/y")
    _declare(peer, root, coordinator, "Coordinator", "RC", "10.PRODUCT/c")
    note = call("send", {"to": sent_y["sender_label"], "text": "Only for Y"}, x, peer=peer)
    assert note["message_id"] in _ids(call("pending", {}, y, peer=peer))
    assert note["message_id"] not in _ids(call("pending", {}, coordinator, peer=peer))
    assert note["message_id"] not in _ids(call("pending", {}, x, peer=peer))
    call("send", {"to": "main agent 2780/root", "text": "progress for my own root"}, x, peer=peer)
    returned = call("pending", {}, x, peer=peer)["pending"]
    assert any("No live agent matches" in row["content"] and "Live agents:" in row["content"] for row in returned)
    assert all(row["id"] != note["message_id"] for row in call("pending", {}, coordinator, peer=peer)["pending"])
    assert all("main agent 2780/root" not in row["content"] for row in call("pending", {}, y, peer=peer)["pending"])
    assert workshop_mailbox._asks_for_reply({"content": "To *:\nstatus: lane pushed"}) is False
    assert workshop_mailbox._asks_for_reply({"content": "To " + sent_y["sender_label"] + ":\nstatus: pushed"}) is False
    assert workshop_mailbox._asks_for_reply({"content": "To " + sent_y["sender_label"] + ":\nCan you confirm?"}) is True


def test_one_declared_task_updates_and_old_offline_task_is_stale(room):
    _root, _peer = room
    with application_history() as history:
        workshop_tasks.declared(history, "root-x", "same", "First title", "working", "agent-x", "Agent X", "ArchHub")
        workshop_tasks.declared(history, "root-x", "same", "Updated title", "working", "agent-x", "Agent X", "ArchHub")
        rows = [row for row in workshop_tasks.rows(history) if row["owner"] == "agent-x"]
        assert len(rows) == 1 and rows[0]["title"] == "Updated title" and rows[0]["updated_at"]
        workshop_tasks.declared(history, "root-old", "old", "Nobody started", "working", "agent-old", "Old Agent", "ArchHub")
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        history._db.execute("UPDATE workshop_tasks SET updated_at=?, status='open', owner='agent-old' WHERE owner='agent-old'", (old,))
        listed = {row["description"]: row for row in workshop_tasks.column(history)}
        assert listed["Nobody started"]["status"] == "stale" and listed["Nobody started"]["inProgress"] is False
        assert "Stale, not in progress" in listed["Nobody started"]["summary"]


def test_task_conversation_is_only_its_own_messages(room):
    _root, _peer = room
    with application_history() as history:
        workshop_tasks.declared(history, "root-x", "job", "Draw the sheet", "working", "agent-x", "Agent X", "ArchHub")
        task = workshop_tasks._declared_id("agent-x")
        history.append(ROOM, author="Agent Y", content="To Agent X:\nbound to the task", category=CATEGORY,
                       refs=(task,), idempotency_key="bound-note")
        history.append(ROOM, author="Agent Z", content="To Agent X:\nunrelated traffic", category=CATEGORY,
                       refs=("someone-else",), idempotency_key="loose-note")
        shown = next(row for row in workshop_tasks.column(history) if row["id"] == task)
        assert shown["messages"] == []
        assert [row["text"] for row in shown["agentLog"]] == ["To Agent X:\nbound to the task"]
        assert "Draw the sheet" in shown["summary"] or "sheet" in shown["summary"].casefold()


def test_bbc4_traffic_stays_out_of_the_archhub_room_unless_it_names_the_agent(room):
    root, peer = room
    arch = {"claude/sessionID": "arch-agent"}
    bbc = {"threadId": "bbc4-agent"}
    arch_row = _declare(peer, root, arch, "Arch Agent", "RA", "10.PRODUCT/x")
    _declare(peer, root, bbc, "BBC Agent", "RB", "BBC4")
    broadcast = call("send", {"to": "*", "text": "BBC4 progress for the room"}, bbc, peer=peer)
    assert broadcast["message_id"] not in _ids(call("pending", {}, arch, peer=peer))
    named = call("send", {"to": arch_row["sender_label"], "text": "Please look at this sheet"}, bbc, peer=peer)
    assert named["message_id"] in _ids(call("pending", {}, arch, peer=peer))
    visible = call("read", {"since": 0}, arch, peer=peer)["messages"]
    assert broadcast["message_id"] not in [row["id"] for row in visible]
    assert named["message_id"] in [row["id"] for row in visible]
    with application_history() as history:
        arch_tasks = workshop_tasks.column(history, project="ArchHub")
        assert arch_tasks and all(row["project"] != "BBC4" for row in arch_tasks)
        assert any(row["project"] == "BBC4" for row in workshop_tasks.column(history, project="BBC4"))


def test_declare_returns_rules_and_arabic_reply_to_the_founder_is_corrected(room, monkeypatch):
    root, peer = room
    rules = root / "gov" / ".rulesync" / "rules"
    rules.mkdir(parents=True)
    sheet = "# ArchHub founder rules\n\n- **LANG** Reply in English.\n"
    (rules / "archhub-ledger.md").write_text(sheet, encoding="utf-8")
    monkeypatch.setenv("ARCHHUB_GOVERNANCE_HOOKS_DIR", str(root / "gov"))
    ctx = {"threadId": "agent-x"}
    joined = _declare(peer, root, ctx, "Agent X", "RX", "10.PRODUCT/x")
    assert sheet.strip() in joined["rules"]["text"]
    assert "reply in English" in joined["rules"]["text"]
    assert joined["rules"]["version"] == sha256(sheet.encode("utf-8")).hexdigest()[:12]
    call("send", {"to": "founder", "text": "تم التنفيذ بالكامل"}, ctx, peer=peer)
    page = call("pending", {}, ctx, peer=peer)
    assert any("Workshop correction" in row["content"] and "reply in English" in row["content"] for row in page["pending"])
    assert joined["rules"]["version"] in page["rules_reminder"]
    call("send", {"to": "Agent Y", "text": "ملاحظة داخلية"}, ctx, peer=peer)
    call("send", {"to": "founder", "text": "Done. The sheet is filed."}, ctx, peer=peer)
    again = call("pending", {}, ctx, peer=peer)["pending"]
    assert sum("Workshop correction" in row["content"] for row in again) == 1
