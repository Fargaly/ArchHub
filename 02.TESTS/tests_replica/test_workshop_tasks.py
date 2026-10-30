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
        # A lapsed lease frees the task for the next agent.
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (ids[1],))
        stale = workshop_tasks.get(history, ids[1])
        assert stale["lease_expired"]
        newcomer = ({"agent-a", "agent-b"} - {stale["owner"]}).pop()
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
    assert states == {"Fix REQ-1": "PLANNED", "Fix REQ-2": "WIP"}, states
    declare("REQ-2", "done")
    assert {row["description"]: row["status"] for row in declared_rows()}["Fix REQ-2"] == "DONE"
    call("declare", {"task": "Starting", "paths": [str(tmp_path)], "status": "working", "request_id": "unassigned"}, me)
    assert len(declared_rows()) == 2                                         # no fake rows for unassigned work
