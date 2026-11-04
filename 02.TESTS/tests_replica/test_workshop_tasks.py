"""Workshop tasks: two agents claim the same task 100 times; exactly one wins each time.

Real Workshop SQLite file, two real connections racing on two threads, no mocks.
Then release, complete, lease expiry, and the Work column the Studio reads.
"""
import threading

from nodelang import workshop_tasks
from nodelang.workshop_mailbox import application_history


def test_two_agents_one_winner_every_time(tmp_path, monkeypatch):
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
        assert sorted(wins.values()) == [False, True], (task, wins)
        winner = next(name for name, won in wins.items() if won)
        with application_history() as history:
            assert workshop_tasks.get(history, task)["owner"] == winner

    with application_history() as history:
        task, row = ids[0], workshop_tasks.get(history, ids[0])
        holder, other = row["owner"], ({"agent-a", "agent-b"} - {row["owner"]}).pop()
        assert workshop_tasks.claim(history, task, holder, holder)            # renewing your own lease
        assert not workshop_tasks.release(history, task, other)               # only the holder releases
        assert workshop_tasks.release(history, task, holder)
        assert workshop_tasks.claim(history, task, other, other)
        assert not workshop_tasks.complete(history, task, holder)             # a former holder cannot finish it
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

    # An agent's declare() is its task: working claims it, a new request frees the old one, done completes it.
    from nodelang.workshop_mailbox import call
    me = {"claude/sessionID": "wstask-declare"}
    declare = lambda request, status: call("declare", {"task": "Fix " + request, "paths": [str(tmp_path)],
                                                       "status": status, "request_id": request}, me)
    def declared_rows():
        return [row for row in nograph_server._list_tasks() if row["id"].startswith("declared-")]
    declare("REQ-1", "working")
    first = declared_rows()
    assert len(first) == 1 and first[0]["description"] == "Fix REQ-1" and first[0]["title"] == "Fix" and first[0]["status"] == "WIP" and first[0]["owner"]
    declare("REQ-1", "working")                                              # re-declaring renews, no new row
    declare("REQ-2", "working")
    states = {row["description"]: row["status"] for row in declared_rows()}
    assert states == {"Fix REQ-1": "DONE", "Fix REQ-2": "WIP"}, states
    bound = next(row for row in declared_rows() if row["description"] == "Fix REQ-2")
    assert bound["owner"]
    assert bound["agents"] == [bound["owner"]]
    assert bound["folders"] and bound["scope"] == bound["folders"][0]
    assert bound["plan"][0]["status"] == "working"
    assert bound["activity"][0]["status"] == "WIP"
    assert bound["session"]
    declare("REQ-2", "done")
    assert {row["description"]: row["status"] for row in declared_rows()}["Fix REQ-2"] == "DONE"
    call("declare", {"task": "Starting", "paths": [str(tmp_path)], "status": "working", "request_id": "unassigned"}, me)
    assert len(declared_rows()) == 2                                         # no fake rows for unassigned work


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
