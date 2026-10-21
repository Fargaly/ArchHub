"""Court: the machine Workshop read never holds the graph lock for its build.

GET /api/universal/workshop built its whole projection -- the ordinary-content
page read, its admission, its byte budget -- inside ``mutation_lock``, so every
other machine request queued behind it (the founder's "the graph stalls
everything"). It now follows the BABOOM native frame (00911b3): one pinned
head built without the lock, a stale-read refusal, and a short second lock
only to re-validate the page at the unchanged revision.

Uses the frame court's fixture: the in-memory graph and a persistent graph
whose first boot created a Workshop content store (the installed path).
"""
import json
import threading

from tests_replica.test_baboom_native_frame_lock_hold import (  # noqa: F401  (fixture)
    LOCK_HOLD_BOUND_SECONDS, TimedLock, enrolled,
)

READER_THREAD = "archhub-universal-runtime-request"


def _seed_workshop(server, count=12):
    for index in range(count):
        server.dispatch_universal_machine_route({"method": "POST", "path": "/api/universal/workshop", "body": {
            "category": "plan", "refs": [server.universal_registry.application_root],
            "evidence": [], "recipients": [], "reply_to": None,
            "created_at": "2026-09-24T10:00:00+00:00",
            "text": "Workshop lock court message %d" % index,
            "idempotency_key": "workshop-lock-court-%d" % index}})


def _read(client):
    return client.request("GET", "/api/universal/workshop", response_timeout_seconds=60)


def _longest_holds(server, client, reads=3):
    timed = TimedLock()
    original = server.mutation_lock
    server.mutation_lock = timed
    try:
        holds = []
        for _ in range(reads):
            timed.holds.clear()
            result = _read(client)
            holds.append(max((hold for hold, name in timed.holds if name == READER_THREAD),
                             default=0.0))
    finally:
        server.mutation_lock = original
    return holds, result


def test_workshop_read_holds_the_graph_lock_only_briefly(enrolled):
    server, baboom = enrolled
    _seed_workshop(server)
    _read(baboom)  # warm route caches
    server._workshop_read_outside_lock = False
    locked, _ = _longest_holds(server, baboom)
    server._workshop_read_outside_lock = True
    unlocked, result = _longest_holds(server, baboom)
    print("\n[%s] workshop read longest lock hold ms: locked build %s; outside-lock build %s" % (
        server._fixture_kind, [round(h * 1000, 1) for h in locked],
        [round(h * 1000, 1) for h in unlocked]))
    assert result["workshop"] == server.universal_registry.workshop_root
    assert max(unlocked) < LOCK_HOLD_BOUND_SECONDS, (
        "Workshop read held mutation_lock %.1f ms (bound %.0f ms)"
        % (max(unlocked) * 1000, LOCK_HOLD_BOUND_SECONDS * 1000))


def test_workshop_read_equals_the_locked_build_of_the_same_revision(enrolled):
    server, baboom = enrolled
    _seed_workshop(server)
    revision = server.universal_store.revision
    server._workshop_read_outside_lock = False
    locked = _read(baboom)
    server._workshop_read_outside_lock = True
    unlocked = _read(baboom)
    assert server.universal_store.revision == revision
    assert locked["revision"] == unlocked["revision"] == revision
    assert json.dumps(locked, sort_keys=True) == json.dumps(unlocked, sort_keys=True)


def test_workshop_read_builds_while_a_writer_holds_the_graph_lock(enrolled):
    """The build no longer waits on a writer: it completes while the lock is
    held. A graph-tail read then returns at once; a content page waits only
    for its short re-check."""
    server, baboom = enrolled
    _seed_workshop(server)
    _read(baboom)
    built, finished, answer = threading.Event(), threading.Event(), {}
    original = server._project_universal_machine_workshop

    def observed(**kwargs):
        result = original(**kwargs)
        built.set()
        return result

    def reader():
        # The founder-local read: a bound session's signed admission still
        # takes the lock briefly before any route runs, which is not this court.
        try:
            answer["value"] = server.dispatch_universal_machine_route(
                {"method": "GET", "path": "/api/universal/workshop", "body": {}})
        except Exception as exc:  # reported below
            answer["error"] = exc
        finished.set()

    server._project_universal_machine_workshop = observed
    worker = threading.Thread(target=reader, daemon=True)
    try:
        with server.mutation_lock:
            worker.start()
            assert built.wait(20), "the Workshop build waited on the held graph lock"
            if server._fixture_kind == "in-memory":
                assert finished.wait(20), "a graph-tail read waited on the held graph lock"
        assert finished.wait(30)
    finally:
        worker.join(30)
        server._project_universal_machine_workshop = original
    assert "error" not in answer, answer.get("error")
    assert answer["value"]["workshop"] == server.universal_registry.workshop_root


def test_workshop_read_stays_on_one_revision_while_the_graph_commits(enrolled):
    server, baboom = enrolled
    _seed_workshop(server)
    stop, commits, errors = threading.Event(), [0], []

    def writer():
        index = 0
        while not stop.is_set():
            index += 1
            try:
                server.dispatch_universal_machine_route({"method": "POST", "path": "/api/universal/work", "body": {
                    "title": "Concurrent Work %d" % index, "description": "fixture",
                    "priority": 30, "external_key": "workshop-lock-concurrent-%d" % index,
                    "references": {"scope": server.universal_registry.map.domains["brain"]},
                    "x": 300 + index, "y": 300}})
                commits[0] += 1
            except Exception as exc:  # the writer is fixture load, not the court
                errors.append(repr(exc))

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        reads = [_read(baboom) for _ in range(4)]
    finally:
        stop.set()
        thread.join(30)
    assert commits[0] > 0, errors[:3]
    for result in reads:
        assert type(result["revision"]) is int
        assert result["workshop"] == server.universal_registry.workshop_root


def _briefing(server):
    return server.dispatch_universal_machine_route({"method": "GET",
        "path": "/api/universal/baboom-steward-briefing", "body": {"projection": "founder-briefing"}})


def _briefing_holds(server, reads=3):
    timed = TimedLock()
    original = server.mutation_lock
    server.mutation_lock = timed
    me = threading.current_thread().name
    try:
        holds = []
        for _ in range(reads):
            timed.holds.clear()
            result = _briefing(server)
            holds.append(max((hold for hold, name in timed.holds if name == me), default=0.0))
    finally:
        server.mutation_lock = original
    return holds, result


def test_steward_briefing_holds_the_graph_lock_only_briefly(enrolled):
    server, _baboom = enrolled
    _seed_workshop(server)
    _briefing(server)
    server._steward_briefing_outside_lock = False
    locked, _ = _briefing_holds(server)
    server._steward_briefing_outside_lock = True
    unlocked, result = _briefing_holds(server)
    print("\n[%s] steward briefing longest lock hold ms: locked build %s; outside-lock build %s" % (
        server._fixture_kind, [round(h * 1000, 1) for h in locked],
        [round(h * 1000, 1) for h in unlocked]))
    assert result["revision"] == server.universal_store.revision
    assert max(unlocked) < LOCK_HOLD_BOUND_SECONDS, (
        "Steward briefing held mutation_lock %.1f ms (bound %.0f ms)"
        % (max(unlocked) * 1000, LOCK_HOLD_BOUND_SECONDS * 1000))


def test_steward_briefing_equals_the_locked_build_of_the_same_revision(enrolled):
    server, _baboom = enrolled
    _seed_workshop(server)
    revision = server.universal_store.revision
    server._steward_briefing_outside_lock = False
    locked = _briefing(server)
    server._steward_briefing_outside_lock = True
    unlocked = _briefing(server)
    assert server.universal_store.revision == revision
    assert locked["revision"] == unlocked["revision"] == revision
    assert json.dumps(locked, sort_keys=True) == json.dumps(unlocked, sort_keys=True)
