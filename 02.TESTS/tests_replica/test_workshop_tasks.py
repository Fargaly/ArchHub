"""Workshop tasks: two agents claim the same task 100 times; both join it as members every time.

Real Workshop SQLite file, two real connections racing on two threads, no mocks.
Then release, complete, lease expiry, and the Work column the Studio reads.
"""
import sqlite3
import threading
from pathlib import Path

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


def test_explicit_legacy_child_migration(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from nodelang.canvas_tools import register_canvas_tools
    from nodelang import nograph_server as server
    from pathlib import Path
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    tools = {}
    class Server:
        def tool(self, *, name, **unused):
            def bind(fn):
                tools[name] = fn
                return fn
            return bind
    register_canvas_tools(Server())
    actor = SimpleNamespace(session=SimpleNamespace(client_params=SimpleNamespace(clientInfo=SimpleNamespace(name='Codex QA'))))
    with application_history() as h:
        p,c,i = [workshop_tasks.create(h,title,'founder') for title in ('Project','Child','Independent')]
        h._db.execute('UPDATE workshop_tasks SET parent_id=? WHERE id=?',(p['id'],c['id']))
        h._db.commit()
        assert workshop_tasks.claim(h,c['id'],'Codex QA','Codex QA')
        source = c['session_path']
        listing = tools['canvas.add_node'](source,'n_list',actor,params={'value':'[8,9]'},task=c['id'])['node']
        count = tools['canvas.add_node'](source,'s_count',actor,task=c['id'])['node']
        tools['canvas.wire'](source,listing+'.value',count+'.items',actor)
    from nodelang import canvas_documents
    def legacy_note(doc):
        doc['notes'].append({'text':'Preserve this child message','role':'task'})
    canvas_documents.edit(source,'You','legacy chat',legacy_note,solve_changed=False)
    canvas_documents.edit(p['session_path'],'You','parent annotation',
                          lambda doc: doc['notes'].append({'text':'Parent annotation'}),solve_changed=False)
    original, unrelated = [Path(path).read_bytes() for path in (source,i['session_path'])]
    for move in ('first', 'retried'):  # a retried move is a no-op
        assert server._move_legacy_child(c['id'])['path'] == p['session_path'], move
        view = server._open_task_graph(c['id'])
        assert any(m['text']=='Preserve this child message' and m['id']=='note-0' for m in view['messages'])
        assert all(m['text']!='Preserve this child message' for m in server._open_task_graph(p['id'])['messages'])
        assert next(item['output']['count'] for item in view['activity'] if item['id']==count) == 2
    assert server._move_legacy_child(c['id'],restore=True)['path'] == source
    reopened = server._open_task_graph(c['id'])
    assert reopened.get('path') == source, reopened
    assert Path(source).read_bytes() == original
    assert Path(i['session_path']).read_bytes() == unrelated
    assert count not in {n['id'] for n in server._open_task_graph(p['id'])['workflow']}
    with application_history() as h:
        h._db.execute('UPDATE workshop_tasks SET parent_id=NULL WHERE id=?',(c['id'],))
        h._db.commit()
    with pytest.raises(ValueError, match='destination'):
        server._move_legacy_child(c['id'])
    from nodelang import session_files
    monkeypatch.setattr(session_files,'_registered_roots',lambda:{'p1':{'label':'Same'},'p2':{'label':'Same'}})
    canvas_documents.edit(source,'You','project one',lambda doc: doc['properties'].update(project='p1'),solve_changed=False)
    canvas_documents.edit(p['session_path'],'You','project two',lambda doc: doc['properties'].update(project='p2'),solve_changed=False)
    with pytest.raises(ValueError,match='in this project'):
        server._move_legacy_child(c['id'],p['id'])
    assert server._open_task_graph(c['id'])['path'] == source
    canvas_documents.edit(p['session_path'],'You','same project',lambda doc: doc['properties'].update(project='p1'),solve_changed=False)
    for as_subtask in (False, True):
        view = server._move_legacy_child(c['id'],p['id'],as_subtask)
        assert view['path'] == p['session_path']
        assert next(item['output']['count'] for item in view['activity'] if item['id']==count) == 2
        assert server._open_task_graph(c['id'])['path'] == p['session_path']
        with application_history() as h:
            assert workshop_tasks.get(h,c['id'])['parent_id'] == (p['id'] if as_subtask else None)
        target = p['session_path']
        saved = session_files.read_document(target)
        saved['viewport']['x'] += 12
        saved['properties']['viewportSaved'] = True
        saved = canvas_documents.commit_ui(target,saved,canvas_documents.revision(saved))
        assert saved['properties']['history'][-1]['view_only'] is True
        assert server._move_legacy_child(c['id'],restore=True)['path'] == source
        with application_history() as h:
            assert workshop_tasks.get(h,c['id'])['parent_id'] is None
        assert Path(i['session_path']).read_bytes() == unrelated
    server._move_legacy_child(c['id'],p['id'])
    canvas_documents.undo_last(p['session_path'], 'You')
    reopened = server._open_task_graph(c['id'])
    assert reopened.get('path') == source, reopened
    server._move_legacy_child(c['id'],p['id'])
    edited = session_files.read_document(target)
    edited['title'] += ' changed by the user'
    canvas_documents.commit_ui(target,edited,canvas_documents.revision(edited))
    with pytest.raises(ValueError,match='canvas changed'):
        server._move_legacy_child(c['id'],restore=True)
    assert session_files.read_document(target)['title'] == edited['title']
    assert server._open_task_graph(c['id'])['path'] == target


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


def test_column_reads_committed_state_with_writer_active(tmp_path, monkeypatch):
    import sqlite3
    from nodelang import nograph_server, workshop_mailbox

    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    assert nograph_server._list_tasks(True) == []
    assert not workshop_mailbox.profile_database().exists()
    with application_history() as history:
        task = workshop_tasks.create(history, "Committed title", "qa")["id"]
    with sqlite3.connect(workshop_mailbox.profile_database()) as writer:
        writer.execute("UPDATE workshop_tasks SET title=? WHERE id=?", ("Pending title", task))
        rows = {row["id"]: row for row in nograph_server._list_tasks(True)}
        assert rows[task]["title"] == "Committed title"
        writer.rollback()
    writer.close()


@pytest.mark.parametrize("archived", [False, True])
def test_permanent_delete_removes_the_task_and_its_own_file_after_reopen(tmp_path, archived):
    from nodelang.session_files import SessionFiles

    with application_history() as history:
        task = workshop_tasks.create(history, "Remove this draft", "tester")
        other = workshop_tasks.create(history, "Keep this draft", "tester")
        target, keep = Path(task["session_path"]), Path(other["session_path"])
        assert target.is_relative_to(tmp_path) and keep.is_relative_to(tmp_path)
        assert target.is_file()
        untouched = keep.read_bytes()
        workshop_tasks.open_session(history, other["id"], select=False)
        workshop_tasks.open_session(history, task["id"], select=True)
        files = SessionFiles()
        assert files.current_path() == str(target)
        if archived:
            assert workshop_tasks.archive(history, task["id"], revision=task["revision"])
            workshop_tasks.open_session(history, other["id"], select=True)
        revision = workshop_tasks.get(history, task["id"])["revision"]
        receipt = workshop_tasks.delete_home_task(history, task["id"], revision=revision, files=files)
        assert receipt == {"ok": True, "deleted": True, "id": task["id"]}

    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) is None
        assert task["id"] not in {row["id"] for row in workshop_tasks.rows(reopened, include_archived=True)}
        assert not target.exists()
        assert workshop_tasks.get(reopened, other["id"])["session_path"] == str(keep)
        assert keep.read_bytes() == untouched
        restored_files = SessionFiles()
        if archived:
            assert restored_files.current_path() == str(keep)
        pointers = {row["path"] for row in restored_files.open_files()}
        assert str(target) not in pointers
        assert str(keep) in pointers


def test_permanent_delete_refuses_a_stale_revision(tmp_path):
    with application_history() as history:
        task = workshop_tasks.create(history, "First title", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        workshop_tasks.rename(history, task["id"], "Updated title", revision=task["revision"])
        expected = workshop_tasks.get(history, task["id"])
        saved = path.read_bytes()
        with pytest.raises(workshop_tasks.TaskConflict):
            workshop_tasks.delete_home_task(history, task["id"], revision=task["revision"])

    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) == expected
        assert path.read_bytes() == saved


@pytest.mark.parametrize("writing", [False, True])
def test_permanent_delete_preserves_a_live_members_work(tmp_path, writing):
    with application_history() as history:
        task = workshop_tasks.create(history, "Live drawing check", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        assert workshop_tasks.claim(history, task["id"], "member", "Member")
        if writing:
            assert workshop_tasks.mark_writing(history, task["id"], "member")
        expected = workshop_tasks.get(history, task["id"])
        saved = path.read_bytes()
        with pytest.raises(ValueError):
            workshop_tasks.delete_home_task(history, task["id"], revision=expected["revision"])

    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) == expected
        assert path.read_bytes() == saved


def test_permanent_delete_restores_the_file_if_the_database_rejects_delete(tmp_path):
    from nodelang.session_files import SessionFiles

    with application_history() as history:
        task = workshop_tasks.create(history, "Recover this draft", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        saved = path.read_bytes()
        workshop_tasks.open_session(history, task["id"], select=True)
        history._db.execute("CREATE TEMP TRIGGER reject_task_delete BEFORE DELETE ON workshop_tasks "
                            "BEGIN SELECT RAISE(ABORT, 'test delete failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="test delete failure"):
            workshop_tasks.delete_home_task(history, task["id"], revision=task["revision"], files=SessionFiles())

    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) == task
        assert path.read_bytes() == saved
        assert SessionFiles().current_path() == str(path)


def test_permanent_delete_refuses_a_canvas_shared_by_two_tasks(tmp_path):
    with application_history() as history:
        root = workshop_tasks.create(history, "Coordination canvas", "tester")
        child = workshop_tasks.create(history, "Check the drawing", "tester", parent=root["id"])
        path = Path(root["session_path"])
        assert path.is_relative_to(tmp_path) and str(path) == child["session_path"]
        saved = path.read_bytes()
        for task in (root, child):
            with pytest.raises(ValueError):
                workshop_tasks.delete_home_task(history, task["id"])

    with application_history() as reopened:
        for task in (root, child):
            assert workshop_tasks.get(reopened, task["id"])["session_path"] == str(path)
        assert path.read_bytes() == saved


def test_permanent_delete_refuses_a_file_that_belongs_to_another_task(tmp_path):
    with application_history() as history:
        target = workshop_tasks.create(history, "Remove this draft", "tester")
        other = workshop_tasks.create(history, "Different canvas", "tester")
        other_path = Path(other["session_path"])
        assert other_path.is_relative_to(tmp_path)
        foreign = other_path.with_name("Unbound copy.archhub")
        saved = other_path.read_bytes()
        foreign.write_bytes(saved)
        history._db.execute("UPDATE workshop_tasks SET session_path=? WHERE id=?", (str(foreign), target["id"]))
        with pytest.raises(ValueError):
            workshop_tasks.delete_home_task(history, target["id"])

    with application_history() as reopened:
        assert workshop_tasks.get(reopened, target["id"])["session_path"] == str(foreign)
        assert foreign.read_bytes() == other_path.read_bytes() == saved


def test_permanent_delete_retry_finishes_interrupted_profile_cleanup(tmp_path, monkeypatch):
    from nodelang.session_files import SessionFiles

    with application_history() as history:
        task = workshop_tasks.create(history, "Finish delete on retry", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        workshop_tasks.open_session(history, task["id"], select=True)
        files = SessionFiles()

        def blocked_metadata_write(target, value):
            raise PermissionError("Profile metadata is locked")

        monkeypatch.setattr(files, "_write_pointer_metadata", blocked_metadata_write)
        with pytest.raises(PermissionError, match="Profile metadata is locked"):
            workshop_tasks.delete_home_task(history, task["id"], revision=task["revision"], files=files)

    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) is None
        assert not path.exists()
        assert SessionFiles().current_path() == str(path)
        receipt = workshop_tasks.delete_home_task(reopened, task["id"], revision=task["revision"], files=SessionFiles())
        assert receipt == {"ok": True, "deleted": True, "id": task["id"]}

    assert not path.exists()
    assert all(row["path"] != str(path) for row in SessionFiles().open_files())


def test_permanent_delete_dispatch_respects_unsaved_views(tmp_path):
    from types import SimpleNamespace
    from nodelang import nograph_server

    server = SimpleNamespace()
    with application_history() as history:
        task = workshop_tasks.create(history, "Dirty view", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        saved = path.read_bytes()
    request = SimpleNamespace(method="POST", body={"action": "data-api", "function": "deleteTask",
                                                  "args": [task["id"], task["revision"]]})
    for name in ("left", "right"):
        nograph_server.record_edit_state(server, {"view": name, "file": str(path), "seq": 1, "unsaved": True})
    nograph_server.record_edit_state(server, {"view": "left", "file": str(path), "seq": 2, "unsaved": False})
    refused = nograph_server.r_workshop(server, request)["result"]
    assert refused["ok"] is False and "unsaved" in refused["error"].lower()
    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) == task and path.read_bytes() == saved
    nograph_server.record_edit_state(server, {"view": "right", "file": str(path), "seq": 2, "unsaved": False})
    assert nograph_server.r_workshop(server, request)["result"] == {"ok": True, "deleted": True, "id": task["id"]}
    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) is None and not path.exists()


def test_permanent_delete_refuses_unreleased_members_after_lease_expires(tmp_path):
    with application_history() as history:
        task = workshop_tasks.create(history, "Open membership", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        saved = path.read_bytes()
        assert workshop_tasks.claim(history, task["id"], "member", "Member")
        history._db.execute("UPDATE workshop_tasks SET lease_until=0, members=json_set(members, "
                            "'$[0].lease_until', 0) WHERE id=?", (task["id"],))
        expected = workshop_tasks.rows(history, task["id"], settle=False)
        assert expected[0]["members"] and not expected[0]["members"][0].get("left")
        with pytest.raises(ValueError, match="member"):
            workshop_tasks.delete_home_task(history, task["id"])
    with application_history() as reopened:
        assert workshop_tasks.rows(reopened, task["id"], settle=False) == expected and path.read_bytes() == saved


def test_permanent_delete_refuses_active_workshop_declaration(tmp_path):
    from nodelang.workshop_mailbox import call, read_declarations

    with application_history() as history:
        task = workshop_tasks.create(history, "Declared work", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
    call("declare", {"task": "Review drawings", "paths": [str(tmp_path)], "status": "working",
                     "request_id": task["id"]}, {"claude/sessionID": "delete-declaration"})
    with application_history() as history:
        active = workshop_tasks.get(history, task["id"])
        assert workshop_tasks.release(history, task["id"], active["owner"], reason="manual")
        saved = path.read_bytes()
        assert workshop_tasks._declaration_for(task, read_declarations(history._db))
        with pytest.raises(ValueError, match="active Workshop agent"):
            workshop_tasks.delete_home_task(history, task["id"])
    with application_history() as reopened:
        assert workshop_tasks.get(reopened, task["id"]) is not None and path.read_bytes() == saved


@pytest.mark.parametrize("copy_document", [False, True])
def test_permanent_delete_cleans_private_run_history_and_preserves_shared_history(tmp_path, copy_document):
    from nodelang.session_files import append_run, runs_path

    with application_history() as history:
        task = workshop_tasks.create(history, "Task with run history", "tester")
        path = Path(task["session_path"])
        assert path.is_relative_to(tmp_path)
        saved = path.read_bytes()
        append_run(path, {"id": "test-run", "state": "succeeded"})
        log = runs_path(path)
        assert log.is_relative_to(tmp_path)
        original_history = log.read_bytes()
        if copy_document:
            sibling = path.with_name("Second canvas.archhub")
            sibling.write_bytes(saved)
            with pytest.raises(ValueError, match="shares this run history"):
                workshop_tasks.delete_home_task(history, task["id"])
        else:
            assert workshop_tasks.delete_home_task(history, task["id"])["deleted"]
    with application_history() as reopened:
        if copy_document:
            assert workshop_tasks.get(reopened, task["id"]) == task
            assert path.read_bytes() == sibling.read_bytes() == saved and log.read_bytes() == original_history
        else:
            assert workshop_tasks.get(reopened, task["id"]) is None and not path.exists() and not log.exists()
def test_child_task_has_one_accountable_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        parent = workshop_tasks.create(history, "Shared project", "founder")
        child = workshop_tasks.create(history, "One piece", "founder", parent=parent["id"])["id"]

    gate = threading.Barrier(2)
    def compete(agent):
        with application_history(busy_timeout_seconds=5) as history:
            gate.wait(timeout=5)
            return workshop_tasks.claim(history, child, agent, agent)

    from concurrent.futures import ThreadPoolExecutor
    agents = ["agent-a", "agent-b"]
    with ThreadPoolExecutor(2) as pool:
        wins = list(pool.map(compete, agents))
    assert sorted(wins) == [False, True]
    owner, other = agents[wins.index(True)], agents[wins.index(False)]
    with application_history() as history:
        assert workshop_tasks.mark_writing(history, child, owner)
        assert workshop_tasks.claim(history, child, owner, owner)
        assert workshop_tasks.get(history, child)["write_open"]
        assert not workshop_tasks.mark_writing(history, child, other)
        assert not workshop_tasks.complete(history, child, other)
        assert workshop_tasks.release(history, child, owner)
        assert workshop_tasks.claim(history, child, other, other)
        assert not workshop_tasks.mark_writing(history, child, owner)

def test_verified_progress_is_scoped_to_installed_build(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(workshop_tasks, "_running_build", lambda: "first-build")
    with application_history() as history:
        task = workshop_tasks.create(history, "Acceptance", "founder")["id"]
        assert workshop_tasks.claim(history, task, "builder", "Builder")
        update = lambda actor, values: workshop_tasks.acceptance_update(history, task, actor, values)
        update("builder", {"criteria": ["One", "Two", "Three", "Four"], "reviewer": "reviewer"})
        verdict = {"criterion": "One", "build": "first-build", "passed": True, "evidence": "Saved and reopened."}
        with pytest.raises(ValueError):
            update("builder", verdict)
        update("reviewer", verdict)
        summary = update("reviewer", {**verdict, "criterion": "Two"})
        assert (summary["verified"], summary["total"]) == (2, 4)
    with application_history() as history:
        row = workshop_tasks.get(history, task)
        assert workshop_tasks.verification_summary(row["acceptance"], "first-build") == summary
        monkeypatch.setattr(workshop_tasks, "_running_build", lambda: "next-build")
        with pytest.raises(ValueError):
            update("reviewer", verdict)
        failed = update("reviewer", {**verdict, "passed": False, "build": "next-build"})
        assert failed["verified"] == 0 and failed["total"] == 4

@pytest.mark.parametrize("interruption", ["paused", "lease_expired"])
def test_handover_offers_one_named_successor_and_blocks_replay(tmp_path, monkeypatch, interruption):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        parent = workshop_tasks.create(history, "Parent", "founder")
        task = workshop_tasks.create(history, "Child", "founder", parent=parent["id"])["id"]
        history._db.execute("UPDATE workshop_tasks SET project='Example' WHERE id=?", (task,))
        assert workshop_tasks.claim(history, task, "first", "First")
        workshop_tasks.update_session(history, task, {"agents": ["Second"]})
        assert workshop_tasks.mark_writing(history, task, "first")
        if interruption == "paused":
            assert workshop_tasks.release(history, task, "first", reason="paused")
        else:
            history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (task,))
            workshop_tasks.reap_stalled(history)
        with pytest.raises(workshop_tasks.TaskLeaseLost):
            workshop_tasks.begin_run(history, task, "first", "First")
        assert not workshop_tasks.claim(history, task, "first", "First")
        candidate = {"session":"second", "agent":"Second", "current":True, "project":"Example",
                     "runtime":"codex", "native_session_id":"second-test"}
        workshop_tasks.offer_handovers(history, [{**candidate, "project":"Other"}])
        assert "offered" not in workshop_tasks.get(history, task)["handover_route"]
        workshop_tasks.offer_handovers(history, [candidate])
        workshop_tasks.offer_handovers(history, [candidate])
        assert workshop_tasks.get(history, task)["handover_route"]["offered"] == "second"
        assert history._db.execute("SELECT count(*) FROM messages WHERE content LIKE 'To Second:%Workshop handover%'").fetchone()[0] == 1
        assert not workshop_tasks.claim(history, task, "third", "Third")
    with application_history() as history:
        assert workshop_tasks.claim(history, task, "second", "Second")
        assert not workshop_tasks.mark_writing(history, task, "second")
        assert not workshop_tasks.complete(history, task, "second")
        workshop_tasks.reconcile_handover(history, task, "second", {"applied":True, "observation":"One matching target receipt."})
        assert not workshop_tasks.mark_writing(history, task, "second")
        assert workshop_tasks.complete(history, task, "second", "Confirmed existing receipt.")

def test_mailbox_retries_reuse_work_and_acknowledged_effect(tmp_path, monkeypatch):
    from nodelang.workshop_mailbox import _task
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        parent = workshop_tasks.create(history, "One workspace", "founder")["id"]
        me = {"sender_key":"one", "sender_label":"First"}
        peer = {"sender_key":"two", "sender_label":"Second"}
        create = {"title":"Feature check", "parent":parent, "piece":"item-3"}
        task = _task(history, "task_create", create, me)["task"]["id"]
        assert _task(history, "task_create", create, peer)["task"]["id"] == task
        assert len(workshop_tasks.rows(history)) == 2
        assert _task(history, "task_claim", {"id":task}, me)["ok"]
        assert not _task(history, "task_claim", {"id":task}, peer)["ok"]
        start = {"id":task, "begin_write":True}
        assert _task(history, "task_set_session", start, me)["ok"]
        assert not _task(history, "task_set_session", start, me)["ok"]
        _task(history, "task_set_session", {"id":task, "reconcile":{"applied":True, "observation":"Target receipt 1"}}, me)
        assert _task(history, "task_release", {"id":task, "reason":"paused"}, me)["ok"]
        assert _task(history, "task_claim", {"id":task}, peer)["ok"]
        assert not _task(history, "task_set_session", start, peer)["ok"]
        assert _task(history, "task_complete", {"id":task}, peer)["ok"]


def test_agents_resume_the_same_task_or_create_a_child_in_its_session(tmp_path, monkeypatch):
    from nodelang.workshop_mailbox import _task
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    with application_history() as history:
        def start(who, title, **fields):
            return _task(history, "task_create", {"title": title, **fields},
                         {"sender_key": who, "sender_label": who})
        first = start("builder", "Review plans", intent="plan-review")
        task = first["task"]["id"]
        for resumed in [start("reviewer", "review plans"),
                        start("builder", "Check sheets", intent="plan-review"),
                        start("reviewer", "Finish review", continue_task=task)]:
            assert resumed["joined"] and resumed["task"]["id"] == task
            assert resumed["session"]["path"] == first["session"]["path"]
        child = start("builder", "Check dimensions", parent=task)
        assert start("builder", "Check dimensions")["task"]["id"] == child["task"]["id"]
        assert child["task"]["parent_id"] == task
        assert child["session"]["path"] == first["session"]["path"]
        assert workshop_tasks.declared(history, "peer", "other-request", "Review plans", "working",
                                       "checker", "Checker") == task
        assert workshop_tasks.declared(history, "peer", "other-request", "Resume it", "working",
                                       "checker", "Checker", continue_task=task) == task
        with history._transaction(write=True):
            history._db.execute("UPDATE workshop_tasks SET project='Project B' WHERE id=?", (task,))
        assert workshop_tasks._matching_open_task(history, "Project B", "Review plans", "") == task
        assert workshop_tasks._matching_open_task(history, "Project A", "Review plans", "") is None
        assert len(workshop_tasks.rows(history)) == 2
