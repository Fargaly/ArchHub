"""Workshop tasks: two agents claim the same task 100 times; both join it as members every time.

Real Workshop SQLite file, two real connections racing on two threads, no mocks.
Then release, complete, lease expiry, and the Work column the Studio reads.
"""
import threading

import pytest

from nodelang import workshop_tasks
from nodelang.workshop_mailbox import application_history


@pytest.fixture(autouse=True)
def work_column_lifetime(monkeypatch):
    from nodelang import nograph_server
    # Direct column tests need the same worker-thread cleanup as closing a Studio server.
    monkeypatch.setattr(nograph_server, "_STORE_VERSION_CLOSED", [False])
    yield
    nograph_server._close_store_version()


def test_two_agents_both_join_as_members_every_time(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        ids = [workshop_tasks.create(history, "task %d" % n, "founder")["id"] for n in range(100)]

    for task in ids:
        gate, wins = threading.Barrier(2), {}

        def agent(name):
            with application_history(busy_timeout_seconds=2.0) as history:
                gate.wait()
                wins[name] = workshop_tasks.claim(history, task, name, name.title())

        racers = [threading.Thread(target=agent, args=(name,)) for name in ("agent-a", "agent-b")]
        [racer.start() for racer in racers]
        [racer.join() for racer in racers]
        assert sorted(wins.values()) == [True, True], (task, wins)           # a session has members, not one holder
        with application_history() as history:
            joined = workshop_tasks.get(history, task)
            assert sorted(member["owner"] for member in joined["members"]) == ["agent-a", "agent-b"]
            assert joined["owner"] in wins and joined["status"] == "claimed"

    with application_history() as history:
        task, row = ids[0], workshop_tasks.get(history, ids[0])
        holder, other = row["owner"], ({"agent-a", "agent-b"} - {row["owner"]}).pop()
        assert workshop_tasks.claim(history, task, holder, holder)            # renewing your own lease
        assert not workshop_tasks.release(history, task, "agent-c")           # only a member releases
        assert workshop_tasks.release(history, task, holder)
        assert workshop_tasks.get(history, task)["owner"] == other            # the other member keeps the session
        assert workshop_tasks.claim(history, task, other, other)
        assert not workshop_tasks.complete(history, task, holder)             # a member who left cannot finish it
        assert workshop_tasks.complete(history, task, other, "shipped")
        assert not workshop_tasks.claim(history, task, holder, holder)        # done stays done
        # A lapsed lease closes the attempt, then the task is planned for the next agent.
        before = history._db.execute("SELECT owner FROM workshop_tasks WHERE id=?", (ids[1],)).fetchone()[0]
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (ids[1],))
        stale = workshop_tasks.get(history, ids[1])
        assert stale["status"] == "open" and stale["outcome"] == "interrupted" and stale["owner"] is None
        newcomer = ({"agent-a", "agent-b"} - {before}).pop()
        assert workshop_tasks.claim(history, ids[1], newcomer, newcomer)

    from nodelang import nograph_server
    column = {row["id"]: row for row in nograph_server._list_tasks()}
    assert column[ids[0]]["status"] == "DONE" and column[ids[0]]["result"] == "shipped"
    assert column[ids[1]]["status"] == "WIP" and column[ids[1]]["owner"] == newcomer
    assert column[ids[2]]["status"] == "WIP"
    assert nograph_server._set_task_status(ids[2], "PLANNED")["status"] == "PLANNED"
    assert nograph_server._set_task_status(ids[2], "WIP")["ok"] is False

    # Declarations join work the user created. Moving or reporting status must never create another card.
    from nodelang.workshop_mailbox import call
    with application_history() as history:
        first_id = workshop_tasks.create_session(history, "First repair", select=False)["taskId"]
        second_id = workshop_tasks.create_session(history, "Second repair", select=False)["taskId"]
    expected = set(ids) | {first_id, second_id}
    me = {"claude/sessionID": "wstask-declare"}
    def declare(request, status):
        call("declare", {"task": "Review drawings", "paths": [str(tmp_path)],
                         "status": status, "request_id": request}, me)

    def work_rows():
        rows = {row["id"]: row for row in nograph_server._list_tasks()}
        assert set(rows) == expected
        return rows

    declare("unknown-request", "working")
    assert work_rows()[first_id]["status"] == "PLANNED"
    declare(first_id, "working")
    first = work_rows()[first_id]
    assert first["description"] == "First repair" and first["status"] == "WIP" and first["owner"]
    declare(first_id, "working")
    declare(second_id, "working")
    rows = work_rows()
    assert rows[first_id]["status"] == "PLANNED"
    bound = rows[second_id]
    assert bound["status"] == "WIP"
    assert bound["owner"]
    assert bound["agents"] == [bound["owner"]]
    assert bound["folders"] and bound["scope"] == bound["folders"][0]
    assert bound["plan"][0]["status"] == "working"
    assert bound["activity"][0]["status"] == "WIP"
    assert bound["session"]
    declare(second_id, "done")
    declare("unassigned", "working")
    rows = work_rows()
    assert rows[first_id]["status"] == "PLANNED" and rows[second_id]["status"] == "DONE"


def test_native_canvas_tools_attribute_solved_count_to_selected_task(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from nodelang.canvas_tools import register_canvas_tools
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    tools = {}
    class Server:
        def tool(self, *, name, **unused):
            def bind(fn):
                tools[name] = fn
                return fn
            return bind
    register_canvas_tools(Server())
    def actor(name):
        return SimpleNamespace(session=SimpleNamespace(client_params=SimpleNamespace(clientInfo=SimpleNamespace(name=name))))
    with application_history() as history:
        a = workshop_tasks.create(history, "Lists", "founder")
        b = workshop_tasks.create(history, "Quantities", "founder", canvas_task=a["id"])
        path = b["session_path"]
        first, second = actor("Claude QA"), actor("Codex QA")
        for row,owner in [(a,"Claude QA"),(b,"Codex QA")]:
            assert workshop_tasks.claim(history,row["id"],owner,owner)
        listing = tools["canvas.add_node"](path,"n_list",first,params={"value":"[1,2,3]"},task=a["id"])["node"]
        count = tools["canvas.add_node"](path,"s_count",second,task=b["id"])["node"]
        with pytest.raises(ValueError, match="Choose the task"):
            tools["canvas.add_node"](path,"s_count",second)
        tools["canvas.wire"](path,listing+".value",count+".items",second)
        def read_count():
            view=workshop_tasks.open_session(history,b["id"],select=False)
            return next(n["output"]["count"] for n in view["activity"] if n["id"]==count)
        assert read_count()==3
        tools["canvas.set_param"](path,listing,"value","[1,2,3,4]",first)
        assert read_count()==4
        first_view=workshop_tasks.open_session(history,a["id"],select=False)
        assert listing in {n["id"] for n in first_view["workflow"]}
        assert count not in {n["id"] for n in first_view["workflow"]}
        assert any(h["by"]=="agent:Codex QA" for h in tools["canvas.read"](path)["last_edits"])


def test_shared_canvas_keeps_two_tasks_subtasks_and_agent_results_separate(tmp_path, monkeypatch):
    from nodelang import canvas_documents as docs, session_files as files
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        a = workshop_tasks.create(history, "Doors", "founder")
        b = workshop_tasks.create(history, "Schedules", "founder", canvas_task=a["id"])
        path = a["session_path"]
        assert b["session_path"] == path
        child_a, child_b = [workshop_tasks.create(history, r["title"]+" subtask", "founder", parent=r["id"]) for r in (a,b)]
        assert {r["session_path"] for r in (child_a,child_b)} == {path}
        for row, peer in [(a,"peer-a"),(b,"peer-b")]:
            assert workshop_tasks.claim(history, row["id"], peer, peer)
            workshop_tasks.update_session(history, row["id"], {"plan":[row["title"]+" check"],
                "messages":[{"text":peer}], "nodes":[{"id":"result-"+peer,"type":"note","title":"Found",
                "result":{"status":"Done","output":peer}}]})
            workshop_tasks.record_step(history,row["id"],peer,peer,"Review","working",result="Checked")
        before = files.read_document(path)
        a_step = next(n for n in before["nodes"] if n["title"] == "Doors check")
        b_step = next(n for n in before["nodes"] if n["title"] == "Schedules check")
        workshop_tasks.update_session(history, b["id"], {"plan":["Revised schedule"]})
        with pytest.raises(ValueError,match="another task"):
            workshop_tasks.update_session(history, b["id"], {"parameters":[{"id":a_step["id"],"params":{"value":"wrong"}}]})
        assert next(n for n in files.read_document(path)["nodes"] if n["id"]==a_step["id"]) == a_step
        for row, peer, plan in [(a,"peer-a","Doors check"),(b,"peer-b","Revised schedule")]:
            view = workshop_tasks.open_session(history,row["id"],select=False)
            assert view["plan"] == [plan] and [m["text"] for m in view["messages"]] == [peer]
            assert {r["output"] for r in view["activity"] if r.get("output")} == {peer}
        docs.edit(path,"Reviewer","remove selected step",lambda d:d.update(nodes=[n for n in d["nodes"] if n["id"]!=b_step["id"]]),solve_changed=False)
        assert workshop_tasks.handover(history,b["id"])["plan"] == []
        docs.undo_last(path,"Reviewer")
        assert workshop_tasks.handover(history,b["id"])["plan"] == ["Revised schedule"]
        assert workshop_tasks.handover(history,a["id"])["plan"] == ["Doors check"]
        assert files.read_document(path)["properties"]["taskContext"]["task"] == a["id"]
        workshop_tasks.set_status(history, b["id"], "DONE")
        assert files.session_fields(files.read_document(path),roots={})["state"] == "open"
        for removed_row in (a,b):
            rid = removed_row["id"]
            def remove_task(document):
                document["nodes"] = [n for n in document["nodes"] if n["id"] != rid]
                document["wires"] = [w for w in document["wires"] if rid not in (w["from"]["node"],w["to"]["node"])]
            docs.edit(path,"Reviewer","remove selected task",remove_task,solve_changed=False)
            with pytest.raises(ValueError,match="no longer"):
                workshop_tasks.open_session(history,rid,select=False)
            docs.undo_last(path,"Reviewer")
            assert workshop_tasks.open_session(history,rid,select=False)["taskId"] == rid
        assert workshop_tasks.bound_session_path(a["id"]) == path


def test_plan_steps_survive_edit_remove_undo_and_reopen(tmp_path, monkeypatch):
    from nodelang import canvas_documents as docs, session_files as files
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        task = workshop_tasks.create(history, "Shared canvas", "founder")
        identity, path = task["id"], task["session_path"]
        def legacy(document):
            document["properties"]["taskContext"]["plan"] = ["Check doors", "Check walls"]
        docs.edit(path, "fixture", "older plan", legacy, solve_changed=False)
        workshop_tasks.update_session(history, identity, {"materializePlan": ["Check doors", "Check walls"]})
        docs.undo_last(path, "Reviewer")
        assert files.read_document(path)["properties"]["taskContext"]["plan"] == ["Check doors", "Check walls"]
        workshop_tasks.update_session(history, identity, {"plan": ["Check doors", "Check walls"]})
        def steps():
            return {n["title"]: n["id"] for n in files.read_document(path)["nodes"] if "plan_order" in n["params"]}
        original = steps()
        workshop_tasks.update_session(history, identity, {"plan": ["Check fire doors", "Check walls"]})
        assert steps()["Check fire doors"] == original["Check doors"]
        selected = original["Check doors"]
        def remove(document):
            document["nodes"] = [n for n in document["nodes"] if n["id"] != selected]
        docs.edit(path, "Reviewer", "remove selected step", remove, solve_changed=False)
        assert workshop_tasks.open_session(history, identity, select=False)["plan"] == ["Check walls"]
        docs.undo_last(path, "Reviewer")
        assert workshop_tasks.open_session(history, identity, select=False)["plan"] == ["Check fire doors", "Check walls"]
        assert steps()["Check walls"] == original["Check walls"]


def test_rename_records_the_title_the_founder_typed(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        task = workshop_tasks.create(history, "Old hall", "founder")["id"]
        renamed = workshop_tasks.rename(history, task, "North hall")
        assert renamed["ok"] is True and renamed["title"] == "North hall" and renamed["description"] == "North hall"
        assert workshop_tasks.get(history, task)["title"] == "North hall"


def test_stale_write_conflicts_and_typed_errors_name_the_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        created = workshop_tasks.create(history, "Hall", "founder")
        task, seen = created["id"], created["revision"]
        assert seen == 0
        workshop_tasks.rename(history, task, "North hall", revision=seen)
        try:
            workshop_tasks.rename(history, task, "South hall", revision=seen)
        except workshop_tasks.TaskConflict as error:
            assert error.code == "CONFLICT"
        else:
            raise AssertionError("stale write overwrote the task")
        assert workshop_tasks.get(history, task)["title"] == "North hall"
        try:
            workshop_tasks.rename(history, "missing-task", "Nowhere", revision=0)
        except workshop_tasks.TaskNotFound as error:
            assert error.code == "NOT_FOUND"
        else:
            raise AssertionError("missing task was written")
        current = workshop_tasks.get(history, task)
        workshop_tasks.claim(history, task, "agent-a", "Agent A", revision=current["revision"])
        held = workshop_tasks.get(history, task)
        try:
            workshop_tasks.release(history, task, "agent-b", revision=held["revision"])
        except workshop_tasks.TaskLeaseLost as error:
            assert error.code == "LEASE_LOST"
        else:
            raise AssertionError("a non-holder released the lease")
        assert workshop_tasks.get(history, task)["owner"] == "agent-a"


def test_lapsed_lease_is_interrupted_and_requeued(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        quiet = workshop_tasks.create(history, "Quiet hall", "founder")["id"]
        noisy = workshop_tasks.create(history, "Noisy hall", "founder")["id"]
        assert workshop_tasks.claim(history, quiet, "agent-a", "Agent A", lease_seconds=30)
        assert workshop_tasks.claim(history, noisy, "agent-a", "Agent A", lease_seconds=30)
        assert workshop_tasks.mark_writing(history, noisy, "agent-a")
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id IN (?,?)", (quiet, noisy))
        closed = {row["id"]: row for row in (workshop_tasks.get(history, quiet), workshop_tasks.get(history, noisy))}
        assert closed[quiet]["status"] == "open" and closed[quiet]["outcome"] == "interrupted"
        assert closed[quiet]["owner"] is None
        assert closed[noisy]["status"] == "open" and closed[noisy]["outcome"] == "unknown"
        assert workshop_tasks.claim(history, quiet, "agent-b", "Agent B", lease_seconds=30)
        again = workshop_tasks.get(history, quiet)
        assert again["status"] == "claimed" and again["owner"] == "agent-b" and again["outcome"] is None
    from nodelang import nograph_server
    shown = {row["id"]: row for row in nograph_server._list_tasks()}
    assert shown[noisy]["status"] == "PLANNED" and shown[noisy]["rowState"] == "unknown"


def test_third_run_waits_when_capacity_is_reached(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        ids = [workshop_tasks.create(history, "Run %d" % n, "founder")["id"] for n in range(3)]
        assert workshop_tasks.TASKS_NODE["params"]["max_runs"] == 2
        assert workshop_tasks.begin_run(history, ids[0], "agent-a", "Agent A", lease_seconds=30)
        assert workshop_tasks.begin_run(history, ids[1], "agent-b", "Agent B", lease_seconds=30)
        try:
            workshop_tasks.begin_run(history, ids[2], "agent-c", "Agent C", lease_seconds=30)
        except workshop_tasks.TaskLimitReached as error:
            assert error.code == "LIMIT_REACHED"
        else:
            raise AssertionError("a third run started")
        waiting = workshop_tasks.get(history, ids[2])
        assert waiting["status"] == "open" and waiting["capacity"] == "LIMIT_REACHED"
        assert workshop_tasks.complete(history, ids[0], "agent-a", "done")
        assert workshop_tasks.begin_run(history, ids[2], "agent-c", "Agent C", lease_seconds=30)
        admitted = workshop_tasks.get(history, ids[2])
        assert admitted["status"] == "claimed" and admitted["owner"] == "agent-c" and admitted["capacity"] is None
    from nodelang import nograph_server
    shown = {row["id"]: row for row in nograph_server._list_tasks()}
    assert shown[ids[2]]["status"] == "WIP"


def test_continue_uses_current_claimant_when_a_former_member_is_still_online(tmp_path, monkeypatch):
    from nodelang import workshop_live, workshop_mailbox
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        row = workshop_tasks.create(history, "Review", "founder")
        task = row["id"]
        for owner in ["former", "current"]:
            assert workshop_tasks.claim(history, task, owner, owner)
        history._db.execute("UPDATE workshop_tasks SET members=json_set(members,'$[0].lease_until',0) WHERE id=?", (task,))
    peers = [dict(session=k, agent=k, handle=k, name=k, app="test", native_session_id=k) for k in ["former", "current"]]
    monkeypatch.setattr(workshop_live, "live_agents", lambda: peers)
    sent = []
    def record(history, message, identity, **options):
        sent.append((message["to"], options["queued"]))
        return {"message_id": "recorded"}
    monkeypatch.setattr(workshop_mailbox, "_send", record)
    monkeypatch.setattr(workshop_live, "deliver", lambda history, message, recipients, *a, **kw:
                        [{"state":"pending", "agent":r["session"]} for r in recipients])
    receipt = workshop_live.send_as_founder("Continue", [], task=task, task_peer=True)
    assert sent == [("current", (task,))]
    assert receipt["deliveries"] == [{"state":"pending", "agent":"current"}]
