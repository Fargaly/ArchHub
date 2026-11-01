"""Workshop detail: declared model, recorded task result, agent member detach.

Real Workshop SQLite and a real .archhub document. No stand-in model, result, or node.
"""
from nodelang.session_files import SessionFiles, new_document
from nodelang.workshop_mailbox import CATEGORY, ROOM, application_history, call


def test_people_list_carries_the_model_when_declared_and_blank_otherwise(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    from nodelang import workshop_live
    monkeypatch.setattr(workshop_live, "live_ids", lambda: {})
    call("declare", {"task": "Detail the panel", "paths": [str(tmp_path)], "status": "working",
                     "request_id": "WSDETAIL", "display_name": "Grove", "model": "grok-4"},
         {"claude/sessionID": "wsdetail-grove"})
    call("declare", {"task": "Watch the room", "paths": [str(tmp_path)], "status": "working",
                     "request_id": "WSDETAIL", "display_name": "Plain"},
         {"threadId": "wsdetail-plain"})
    rows = {agent["name"]: agent for agent in workshop_live.live_agents()}
    assert rows["Grove"]["model"] == "grok-4"
    assert rows["Plain"]["model"] == ""


def test_completed_task_returns_its_recorded_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    from nodelang import workshop_tasks
    with application_history() as history:
        stored = workshop_tasks.create(history, "Ship the panel", "founder")
        assert workshop_tasks.claim(history, stored["id"], "grove", "Grove")
        assert workshop_tasks.complete(history, stored["id"], "grove", "artifact: report.md")
        replied = workshop_tasks.create(history, "Close the loop", "founder")
        assert workshop_tasks.claim(history, replied["id"], "grove", "Grove")
        assert workshop_tasks.complete(history, replied["id"], "grove", "")
        history.append(ROOM, author="Grove", content="https://files/report.md", category=CATEGORY,
                       refs=(replied["id"],), idempotency_key="wsdetail-reply")
        silent = workshop_tasks.create(history, "Nothing recorded", "founder")
        assert workshop_tasks.claim(history, silent["id"], "grove", "Grove")
        assert workshop_tasks.complete(history, silent["id"], "grove", "")
        column = {row["id"]: row for row in workshop_tasks.column(history)}
    assert column[stored["id"]]["status"] == "DONE"
    assert column[stored["id"]]["result"] == "artifact: report.md"
    assert column[replied["id"]]["result"] == "https://files/report.md"
    assert column[silent["id"]]["result"] == ""


def test_detach_member_creates_one_agent_node_and_attach_removes_it(tmp_path):
    document = new_document("Workshop")
    document["nodes"].append({
        "id": "workshop",
        "type": "thing.workshop",
        "title": "Workshop",
        "params": {"thread": "app:workshop"},
        "position": {"x": 40, "y": 48},
        "members": [{"id": "agent-grove", "title": "Grove", "agent": "grove"}],
    })
    files = SessionFiles(tmp_path)
    detached = files.dispatch({"action": "member-op", "op": "detach", "document": document,
                               "args": ["workshop", "agent-grove", 120, 80]})
    document = detached["document"]
    agents = [node for node in document["nodes"] if node["type"] == "thing.agent"]
    assert len(agents) == 1
    agent = agents[0]
    assert agent["id"] == "agent-grove" and agent["params"]["agent"] == "grove"
    assert [port["id"] for port in agent["ports"]["target"]] == ["task"]
    assert [port["id"] for port in agent["ports"]["source"]] == ["result"]
    assert any(wire["to"] == {"node": "agent-grove", "socket": "task"} for wire in document["wires"])
    workshop = next(node for node in document["nodes"] if node["id"] == "workshop")
    assert workshop.get("members") == []
    attached = files.dispatch({"action": "member-op", "op": "attach", "document": document,
                               "args": ["workshop", "agent-grove"]})
    document = attached["document"]
    assert [node for node in document["nodes"] if node["type"] == "thing.agent"] == []
    assert [wire for wire in document["wires"] if "agent-grove" in (wire["from"]["node"], wire["to"]["node"])] == []
    workshop = next(node for node in document["nodes"] if node["id"] == "workshop")
    assert workshop["members"] == [{"id": "agent-grove", "title": "Grove", "agent": "grove"}]
