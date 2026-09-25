"""Court: a warm canvas read never holds the graph lock for its whole build.

GET /api/universal/canvas built the full canvas projection and bound its
controls inside ``mutation_lock`` (measured on a 204,870-cell old-shape graph:
1.2-1.4 s per warm read, 2.2 s cold), so every other request waited behind it.
The full canvas now builds from one pinned head where any graph commit is
refused, and takes the lock only for its short tail, which issues the
interaction lease at the unchanged revision. A read that must publish
interaction authority (the first one) is built under the lock as before.
"""
import json
import threading

from tests_replica.test_baboom_native_frame_lock_hold import LOCK_HOLD_BOUND_SECONDS, TimedLock
from nodelang import commit_intent
from nodelang.application_server import ApplicationServer


def _server():
    return ApplicationServer(enable_machine_transport=False).start()


def _canvas(server, binding):
    # As the HTTP GET does: the read runs under the person's user action, which
    # is what admits a first read's interaction-authority publication.
    with commit_intent.declare(commit_intent.USER_ACTION, actor=binding.subject_root,
                               reason="open the canvas"):
        return server.project_interaction_canvas(binding)


def _holds(server, binding, reads=3):
    timed = TimedLock()
    original = server.mutation_lock
    server.mutation_lock = timed
    me = threading.current_thread().name
    try:
        holds = []
        for _ in range(reads):
            timed.holds.clear()
            projection = _canvas(server, binding)
            holds.append(max((hold for hold, name in timed.holds if name == me), default=0.0))
    finally:
        server.mutation_lock = original
    return holds, projection


def _stable(projection):
    return json.dumps({key: value for key, value in projection.items()
                       if key != "interaction_projection"}, sort_keys=True, default=str)


def _cold_longest_hold(outside_lock):
    server = _server()
    try:
        server._interaction_canvas_outside_lock = outside_lock
        binding = server._resolve_browser_session(server.browser_session_token)
        revision = server.universal_store.revision
        holds, projection = _holds(server, binding, reads=1)
        return holds[0], server.universal_store.revision > revision, projection
    finally:
        server.close()


def test_the_first_canvas_read_publishes_its_interactions_in_short_holds():
    """Read #0 publishes interaction authority; each publication takes the
    lock only for itself, so no single hold carries the whole build."""
    locked, locked_published, _ = _cold_longest_hold(False)
    unlocked, unlocked_published, projection = _cold_longest_hold(True)
    print("\ncold canvas read longest lock hold ms: locked build %.1f; outside-lock build %.1f" % (
        locked * 1000, unlocked * 1000))
    assert locked_published == unlocked_published
    assert projection["interaction_projection"]["bindings"]
    assert unlocked < locked / 2, (unlocked, locked)


def test_a_warm_canvas_read_holds_the_graph_lock_only_briefly():
    server = _server()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)
        _canvas(server, binding)  # the first read may publish interaction authority
        server._interaction_canvas_outside_lock = False
        locked, _ = _holds(server, binding)
        server._interaction_canvas_outside_lock = True
        unlocked, projection = _holds(server, binding)
        print("\ncanvas read longest lock hold ms: locked build %s; outside-lock build %s" % (
            [round(h * 1000, 1) for h in locked], [round(h * 1000, 1) for h in unlocked]))
        assert projection["revision"] == server.universal_store.revision
        assert projection["interaction_projection"]["bindings"]
        assert max(unlocked) < LOCK_HOLD_BOUND_SECONDS, (
            "canvas read held mutation_lock %.1f ms (bound %.0f ms)"
            % (max(unlocked) * 1000, LOCK_HOLD_BOUND_SECONDS * 1000))
    finally:
        server.close()


def test_a_warm_canvas_read_equals_the_locked_build_of_the_same_revision():
    server = _server()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)
        _canvas(server, binding)
        revision = server.universal_store.revision
        server._interaction_canvas_outside_lock = False
        locked = _canvas(server, binding)
        server._interaction_canvas_outside_lock = True
        unlocked = _canvas(server, binding)
        assert server.universal_store.revision == revision
        assert locked["revision"] == unlocked["revision"] == revision
        assert _stable(locked) == _stable(unlocked)
        assert ([b["control"] for b in locked["interaction_projection"]["bindings"]]
                == [b["control"] for b in unlocked["interaction_projection"]["bindings"]])
    finally:
        server.close()


def test_a_canvas_build_that_sees_a_commit_is_rebuilt_at_one_revision():
    server = _server()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)
        _canvas(server, binding)
        original = server._project_interaction_canvas_scoped
        committed = []

        def racing(*args, **kwargs):
            if kwargs.get("unlocked_from") is not None and not committed:
                from nodelang.universal_cell import Cell, NULL_CELL_ID
                from nodelang import commit_intent
                with commit_intent.declare(commit_intent.USER_ACTION, actor="court",
                                           reason="commit during a canvas build"):
                    server.universal_store.commit(server.universal_store.revision, create=(
                        Cell("test:canvas-race", NULL_CELL_ID, NULL_CELL_ID, b""),))
                committed.append(server.universal_store.revision)
            return original(*args, **kwargs)

        server._project_interaction_canvas_scoped = racing
        projection = _canvas(server, binding)
        assert committed
        assert projection["revision"] == server.universal_store.revision == committed[0]
    finally:
        server.close()


def test_a_commit_in_the_middle_of_the_build_never_returns_a_mixed_revision(monkeypatch):
    """Verifier 2026-09-25 (test_vr_midbuild.py): the graph moves AFTER the
    unlocked build read it. Without the tail drift check this goes red."""
    import nodelang.application_server as application_server_module
    from nodelang.universal_cell import Cell, NULL_CELL_ID

    server = _server()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)
        _canvas(server, binding)
        builds = []
        original_scoped = server._project_interaction_canvas_scoped

        def scoped(*args, **kwargs):
            builds.append(kwargs.get("unlocked_from", "locked"))
            return original_scoped(*args, **kwargs)

        original_canvas = application_server_module.project_universal_canvas

        def commit_from_another_thread():
            def run():
                with server.mutation_lock, commit_intent.declare(
                        commit_intent.USER_ACTION, actor="court", reason="mid-build commit"):
                    server.universal_store.commit(server.universal_store.revision, create=(
                        Cell("test:canvas-midbuild", NULL_CELL_ID, NULL_CELL_ID, b""),))
            worker = threading.Thread(target=run)
            worker.start()
            worker.join(30)
            assert not worker.is_alive()

        def canvas(*args, **kwargs):
            projection = original_canvas(*args, **kwargs)
            if len(builds) == 1:
                commit_from_another_thread()
            return projection

        server._project_interaction_canvas_scoped = scoped
        monkeypatch.setattr(application_server_module, "project_universal_canvas", canvas)
        projection = _canvas(server, binding)
        final = server.universal_store.revision
        assert projection["revision"] == final
        assert builds[-1] in ("locked", final), "the returned build started at another revision"
        monkeypatch.setattr(application_server_module, "project_universal_canvas", original_canvas)
        server._interaction_canvas_outside_lock = False
        locked = _canvas(server, binding)
        assert locked["revision"] == final
        assert _stable(locked) == _stable(projection)
    finally:
        server.close()


def test_six_warm_canvas_reads_after_the_first_add_no_revision():
    """Only the first read publishes interaction authority; the verifier saw
    1003 -> 1048 across six reads on an earlier build."""
    server = _server()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)
        _canvas(server, binding)
        revision = server.universal_store.revision
        for _ in range(6):
            assert _canvas(server, binding)["revision"] == revision
        assert server.universal_store.revision == revision
    finally:
        server.close()
