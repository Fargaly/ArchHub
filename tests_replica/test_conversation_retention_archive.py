"""Courts for conversation retention: archive before delete, restore, bounds.

Lane "retention" (2026-09-24). Conversations are indexed content in the side
store, never graph Cells. A conversation idle for 20 days is written to a JSONL
file in the user's data folder and only then removed from the store; Work keeps
its conversation; restore re-imports the file; no pass writes a graph revision;
the launcher and geometry logs are capped.
"""
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from nodelang.conversation_archive import (archive_directory, archive_file, export_messages,
    read_archive)
from nodelang.conversation_history import ConversationHistoryStore, _RETENTION_SECONDS
from nodelang.log_rotation import RotatingLog, rotate

DAY = 86400.0
ROOM = "app:test:room"
OWNER = ("session", "subject", "view", "tenant", "assurance")


def _history(tmp_path, clock):
    history = ConversationHistoryStore(tmp_path / "content.sqlite3", instance_id="instance-1",
                                       retention_clock=lambda: clock[0])
    history.ensure_conversation(ROOM)
    history.initialize_retention()
    history.initialize_page_protection()
    return history


def _fill(history, room=ROOM, count=5):
    first = history.append(room, author="founder", content="first", idempotency_key="k0")
    for index in range(1, count):
        history.append(room, author="founder", content="message %d" % index,
                       idempotency_key="k%d" % index, reply_to=first["id"] if index == 1 else None,
                       recipients=("colleague",) if index == 2 else ())


def _ready(history, room=ROOM):
    status = history.retention_status(room)
    history.resolve_page_tracking(room, resolver_identity=OWNER,
        expected_activity_revision=status["activity_revision"], before_commit=lambda: None)


def _cas(status):
    return dict(expected_activity_revision=status["activity_revision"],
                expected_archive_revision=status["archive_revision"],
                expected_head=status["last_sequence"],
                expected_content_generation=status["content_generation"])


def _archive_now(history, room=ROOM):
    status = history.retention_status(room)
    return history.archive(room, **_cas(status), protected=False, before_commit=lambda: None)


def _page(history, room=ROOM):
    return history.page(room, principal="founder", read_all=True, limit=100)["messages"]


def _rows(history, room=ROOM):
    return history._db.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (room,)).fetchone()[0]


# Court 1: only eligible content is deleted.
def test_retention_deletes_only_content_idle_for_twenty_days(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    _ready(history)
    clock[0] += _RETENTION_SECONDS - 60          # 19 days 23:59 idle: not eligible
    status = _archive_now(history)
    exported = []
    with pytest.raises(ValueError, match="inactive for 20 days"):
        history.purge_archived(ROOM, **_cas(status), protected=False, before_commit=lambda: None,
                               export=exported.append)
    assert _rows(history) == 5 and exported == []
    clock[0] += 120                               # now past 20 days
    result = history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                                    before_commit=lambda: None, export=exported.append)
    assert result["purged"] == 5 and _rows(history) == 0
    assert [m["sequence"] for m in exported[0]] == [5, 4, 3, 2, 1]


def test_purge_refuses_without_an_archive_export(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    _ready(history)
    clock[0] += 21 * DAY
    status = _archive_now(history)
    with pytest.raises(ValueError, match="archive export before delete"):
        history.purge_archived(ROOM, **_cas(status), protected=False, before_commit=lambda: None)
    assert _rows(history) == 5


def test_unresolved_draft_pages_keep_the_conversation(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)                                 # tracking never resolved: protected
    clock[0] += 30 * DAY
    assert history.page_protection_status(ROOM)["protected"] is True
    status = history.retention_status(ROOM)
    with pytest.raises(ValueError, match="page protection"):
        history.archive(ROOM, **_cas(status), protected=False, before_commit=lambda: None)
    assert _rows(history) == 5


# Court 3: export happens before delete; a crash between leaves both copies.
def test_failed_export_deletes_nothing(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    _ready(history)
    clock[0] += 21 * DAY
    status = _archive_now(history)

    def disk_full(messages):
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        history.purge_archived(ROOM, **_cas(status), protected=False, before_commit=lambda: None,
                               export=disk_full)
    assert _rows(history) == 5
    assert history._db.execute("SELECT count(*) FROM message_tombstones").fetchone()[0] == 0


def test_crash_between_export_and_commit_leaves_both_copies_and_retry_writes_once(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    _ready(history)
    before = _page(history)
    clock[0] += 21 * DAY
    status = _archive_now(history)
    path = archive_file(archive_directory(tmp_path / "content.sqlite3"), ROOM)
    export = lambda messages: export_messages(path, ROOM, history.instance_id, messages)
    calls = []

    def crash_before_commit():
        calls.append(1)
        if len(calls) == 2:                        # first call opens, second is the pre-commit check
            raise RuntimeError("power lost before commit")

    with pytest.raises(RuntimeError, match="power lost"):
        history.purge_archived(ROOM, **_cas(status), protected=False,
                               before_commit=crash_before_commit, export=export)
    # Both copies: the rows are still in the store and in the archive file.
    assert _rows(history) == 5
    assert [m["sequence"] for m in read_archive(path, ROOM, history.instance_id)] == [1, 2, 3, 4, 5]
    # A torn final line from the crash is dropped, never read as content.
    with path.open("ab") as handle:
        handle.write(b'{"kind":"message","sequ')
    history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                           before_commit=lambda: None, export=export)
    assert _rows(history) == 0
    lines = path.read_bytes().splitlines()
    assert len(lines) == 6 and lines[-1].endswith(b"}")   # header + 5, each sequence once
    archived = read_archive(path, ROOM, history.instance_id)
    assert [{k: m[k] for k in ("id", "sequence", "content", "reply_to", "recipients")} for m in archived] == \
        [{k: m[k] for k in ("id", "sequence", "content", "reply_to", "recipients")} for m in before]


# Court 4: restore works.
def test_restore_reimports_the_archive_at_original_sequences(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history, count=7)
    _ready(history)
    before = _page(history)
    counts = history.counts(ROOM, principal="colleague")
    clock[0] += 21 * DAY
    _archive_now(history)
    path = archive_file(archive_directory(tmp_path / "content.sqlite3"), ROOM)
    history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                           before_commit=lambda: None, max_messages=4,
                           export=lambda m: export_messages(path, ROOM, history.instance_id, m))
    assert _rows(history) == 3                     # a partial purge: newest four removed
    history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                           before_commit=lambda: None,
                           export=lambda m: export_messages(path, ROOM, history.instance_id, m))
    assert _rows(history) == 0
    # A record that is not what retention removed is refused.
    forged = dict(read_archive(path, ROOM, history.instance_id)[0], id="someone-else")
    with pytest.raises(ValueError, match="does not match"):
        history.restore_archived(ROOM, [forged], before_commit=lambda: None)
    restored = history.restore_archived(ROOM, read_archive(path, ROOM, history.instance_id),
                                        before_commit=lambda: None)
    assert restored["restored"] == 7 and restored["tombstones"] == 0
    assert restored["archived_at"] is None and restored["purged_messages"] == 0
    assert _page(history) == before
    assert history.counts(ROOM, principal="colleague") == counts
    assert [m["content"] for m in history.search(ROOM, "message 3", principal="founder", read_all=True)] == ["message 3"]
    again = history.restore_archived(ROOM, read_archive(path, ROOM, history.instance_id),
                                     before_commit=lambda: None)
    assert again["restored"] == 0                  # idempotent: present messages are skipped
    history.append(ROOM, author="founder", content="after restore", idempotency_key="k-new")
    assert _page(history)[-1]["sequence"] == 8


# Court 4b: restore verifies each line against the content digest in its tombstone.
def test_restore_refuses_an_edited_archive_line(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    _ready(history)
    before = _page(history)
    clock[0] += 21 * DAY
    _archive_now(history)
    path = archive_file(archive_directory(tmp_path / "content.sqlite3"), ROOM)
    history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                           before_commit=lambda: None,
                           export=lambda m: export_messages(path, ROOM, history.instance_id, m))
    digests = history._db.execute("SELECT sequence,content_digest FROM message_tombstones ORDER BY sequence").fetchall()
    assert [row[0] for row in digests] == [1, 2, 3, 4, 5] and all(len(row[1]) == 64 for row in digests)
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[3])
    assert edited["sequence"] == 3
    edited["content"] = "words retention never removed"
    lines[3] = json.dumps(edited, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="content differs"):
        history.restore_archived(ROOM, read_archive(path, ROOM, history.instance_id), before_commit=lambda: None)
    assert _rows(history) == 0                     # the whole batch was refused
    # A changed audience is refused too, and the valid line before it rolls back.
    first, second = read_archive(path, ROOM, history.instance_id)[:2]
    with pytest.raises(ValueError, match="content differs"):
        history.restore_archived(ROOM, [first, dict(second, recipients=["someone-else"])],
                                 before_commit=lambda: None)
    assert _rows(history) == 0
    lines[3] = json.dumps({"kind": "message", **{k: before[2][k] for k in before[2]}},
                          ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    restored = history.restore_archived(ROOM, read_archive(path, ROOM, history.instance_id),
                                        before_commit=lambda: None)
    assert restored["restored"] == 5 and _page(history) == before


def test_the_first_purge_adds_the_digest_column_and_the_store_reopens(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    assert history._has_content_digests() is False  # a store that never purged keeps its shape
    _fill(history)
    _ready(history)
    clock[0] += 21 * DAY
    _archive_now(history)
    def refused(messages):
        raise OSError("disk full")
    with pytest.raises(OSError):
        history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                               before_commit=lambda: None, export=refused)
    assert history._has_content_digests() is False  # rolled back with the purge
    history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
                           before_commit=lambda: None, export=lambda m: None)
    assert history._has_content_digests() is True
    history.close()
    reopened = ConversationHistoryStore(tmp_path / "content.sqlite3", instance_id="instance-1", create=False)
    assert reopened.retention_status(ROOM)["purged_messages"] == 5
    reopened.close()


# Court 3 (store level): a room born in a protected store needs no draft resolution.
def test_a_room_born_in_a_protected_store_is_eligible_without_resolution(tmp_path):
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    history.ensure_conversation("app:new-room")
    history.track_new_conversation("app:new-room")
    assert history.born_tracked("app:new-room")
    assert history.track_new_conversation("app:new-room")["protected"] is False  # idempotent
    _fill(history, "app:new-room")
    _fill(history)                                 # a room that already has history
    with pytest.raises(ValueError, match="only a new, unused conversation"):
        history.track_new_conversation(ROOM)
    clock[0] += 21 * DAY
    status = _archive_now(history, "app:new-room")
    history.purge_archived("app:new-room", **_cas(status), protected=False,
                           before_commit=lambda: None, export=lambda m: None)
    assert _rows(history, "app:new-room") == 0
    assert history.page_protection_status(ROOM)["protected"] is True  # a legacy room still waits


# Court 6: log rotation caps size.
def test_log_rotation_caps_every_log(tmp_path):
    path = tmp_path / "launcher.log"
    rotated = []
    log = RotatingLog(path, max_bytes=1000, keep=3, on_rotate=lambda stream: rotated.append(stream.fileno()))
    line = "x" * 99 + "\n"
    for index in range(200):                       # 20,000 bytes through a 1,000-byte cap
        log.write(line)
    log.write("newest line\n")
    log.flush()
    log.close()
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["launcher.log", "launcher.log.1", "launcher.log.2", "launcher.log.3"]
    assert all((tmp_path / name).stat().st_size < 1000 + len(line) for name in files)
    assert sum((tmp_path / name).stat().st_size for name in files) <= 4 * 1000 + len(line)
    assert path.read_text(encoding="utf-8").endswith("newest line\n")
    assert rotated                                  # faulthandler follows each reopen
    geometry = tmp_path / "baboom-geometry.log"
    geometry.write_bytes(b"g" * 6_874_693)          # the founder machine size, 2026-09-24
    assert rotate(geometry, 512 * 1024, 3) is True
    assert not geometry.exists() and (tmp_path / "baboom-geometry.log.1").stat().st_size == 6_874_693
    assert rotate(geometry, 512 * 1024, 3) is False # nothing to rotate until it grows again


def test_geometry_receipts_rotate_at_their_cap(tmp_path, monkeypatch):
    from nodelang import log_rotation
    from nodelang.baboom_native_companion import BaboomNativeCompanionController as BaboomNativeCompanion
    monkeypatch.setattr(log_rotation, "GEOMETRY_LOG_BYTES", 2000)
    companion = BaboomNativeCompanion.__new__(BaboomNativeCompanion)
    companion._geometry_log = tmp_path / "baboom-geometry.log"
    for index in range(400):
        companion.geometry_receipt("moved to %d,%d" % (index, index))
    sizes = {p.name: p.stat().st_size for p in tmp_path.iterdir()}
    assert set(sizes) <= {"baboom-geometry.log", "baboom-geometry.log.1", "baboom-geometry.log.2",
                          "baboom-geometry.log.3"}
    assert max(sizes.values()) < 2000 + 64


def test_launcher_writes_through_the_rotating_log():
    source = (Path(__file__).resolve().parents[1] / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "_log = RotatingLog(_log_path)" in source
    # The plain append file survives only as the fallback for a broken import.
    assert source.count('open(_log_path, "a"') == 1
    assert source.index("except Exception:") < source.index('open(_log_path, "a"')
    assert '_rotate_log(_log_dir / "brain.log", LAUNCHER_LOG_BYTES, LOG_KEEP)' in source
    assert "_log.on_rotate = lambda stream: faulthandler.enable(file=stream)" in source


# Courts 1, 2, 4, 5 on the real application: maintenance, Work, HTTP, graph.
@pytest.fixture(scope="module")
def application(tmp_path_factory):
    from nodelang import universal_application as app
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    root = tmp_path_factory.mktemp("retention-app")
    patch = pytest.MonkeyPatch()
    patch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    server = ApplicationServer(universal_state_path=root / "graph.sqlite3", universal_key_provider=keys,
        universal_workspace_root=root, enable_machine_transport=False,
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
        live_watch=False).start()
    try:
        yield server
    finally:
        server.close()
        patch.undo()


def _sweep(service, context, limit=40):
    """Passes from the first conversation until the cursor wraps once."""
    cursor, results = None, []
    for _ in range(limit):
        result = service.maintain_retention(authentication_context=context, after_conversation_id=cursor)
        results.append(result)
        cursor = result["next_conversation_id"]
        if cursor is None and result["status"] != "changed":
            break
    return results


def _graph_counts(server):
    connection = sqlite3.connect("file:%s?mode=ro" % Path(server.universal_store.database_path).as_posix(),
                                 uri=True, timeout=30)
    try:
        return connection.execute("SELECT (SELECT MAX(revision) FROM revisions), "
            "(SELECT COUNT(*) FROM cell_versions), (SELECT COUNT(*) FROM current_cells)").fetchone()
    finally:
        connection.close()


def _request(server, path, body=None):
    call = Request(server.url + path, headers={"Content-Type": "application/json", "Origin": server.url,
        "Cookie": "ArchHub-Session=" + server.browser_session_token,
        "X-ArchHub-CSRF": server.browser_csrf_token},
        data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(call, timeout=60) as response:
            return response.status, json.loads(response.read())
    except HTTPError as refused:
        return refused.code, json.loads(refused.read())


def test_idle_retention_archives_only_eligible_rooms_keeps_work_and_writes_no_graph(application, tmp_path, monkeypatch):
    from nodelang import commit_intent
    from nodelang import universal_application as app
    from nodelang.workshop_conversation_catalog import create_workshop_conversation
    from nodelang.workshop_work_creation import create_browser_workshop_work
    server = application
    registry, store = server.universal_registry, server.universal_store
    browser = server._resolve_browser_session(server.browser_session_token)
    # Setup is a person acting. The retention passes below run with NO declared
    # intent, so any graph commit they attempted would itself be refused.
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="retention court setup"):
        app.set_universal_scope(store, registry, registry.map.domains["brain"], authentication_context=browser.context)
        app.set_universal_scope(store, registry, registry.workshop_workbench_root, authentication_context=browser.context)
        old = create_workshop_conversation(server, authentication_context=browser.context,
            expected_revision=store.revision, title="Old idea", participant_roots=[browser.subject_root],
            idempotency_key="retention-old")["root"]
        recent = create_workshop_conversation(server, authentication_context=browser.context,
            expected_revision=store.revision, title="Recent idea", participant_roots=[browser.subject_root],
            idempotency_key="retention-recent")["root"]
        workflow = registry.workshop_root
        create_browser_workshop_work(server, browser, {"workshop_root": workflow,
            "workshop_scope": registry.workshop_workbench_root, "revision": store.revision,
            "title": "Keep this workflow", "projection": False}, browser_guard=lambda: None)
    service = server.conversation_content
    history = service._history
    # Court 3 (fresh install): the profile is used exactly as it was born. No
    # activation, no draft resolution: the store is page-protected from its
    # first boot and every room it created is born with complete tracking.
    assert history._db.execute("PRAGMA user_version").fetchone()[0] == 5
    assert all(history.born_tracked(room) for room in (old, recent, workflow))
    assert history._db.execute("SELECT count(*) FROM conversation_page_tracking").fetchone()[0] == 3
    clock = [2_000_000_000.0]
    monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
    for room in (old, recent, workflow):
        _fill(history, room)
    # Time is observed, not read off the wall: the court's monotonic clock moves
    # with its wall clock, and a first sweep sees each room's current activity.
    from nodelang import conversation_retention_maintenance as maintenance
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0], raising=False)
    _sweep(service, registry.authorization.session.context(minimum_validity_seconds=5))
    clock[0] += 19 * DAY
    history.append(recent, author="founder", content="still going", idempotency_key="recent-late")
    clock[0] += 2 * DAY                            # old + workflow idle 21 days, recent 2 days
    # The workflow is FINISHED: the guard reads its real state machine with the
    # current state moved to the graph's own "complete" state. Finished Work
    # still keeps its conversation (before this lane only open Work did).
    import dataclasses
    from nodelang import workshop_retention_guard as guard_module
    real_machine = guard_module.read_instance_state_machine
    finished = []

    def completed_machine(snapshot, assembly, protocol, root):
        machine = real_machine(snapshot, assembly, protocol, root)
        complete = [state for state in machine.state_roots
                    if snapshot.cells[state].atom.decode("utf-8").casefold() == "complete"]
        assert len(complete) == 1
        finished.append(root)
        return dataclasses.replace(machine, current_state_root=complete[0])

    monkeypatch.setattr(guard_module, "read_instance_state_machine", completed_machine)
    baseline = _graph_counts(server)
    revision = store.revision
    context = registry.authorization.session.context(minimum_validity_seconds=5)
    cursor, results = None, []
    for _ in range(40):
        result = service.maintain_retention(authentication_context=context, after_conversation_id=cursor)
        results.append(result)
        cursor = result["next_conversation_id"]
        if result["status"] == "idle" and cursor is None and _rows(history, old) == 0:
            break
    assert _rows(history, old) == 0, results
    assert _rows(history, recent) == 6              # not eligible: untouched
    assert _rows(history, workflow) == 5            # finished Work references it: always kept
    assert finished                                 # the guard really read the Work as complete
    assert any(r["protected"] for r in results)
    path = archive_file(archive_directory(service._path), old)
    assert [m["content"] for m in read_archive(path, old, history.instance_id)] == \
        ["first"] + ["message %d" % i for i in range(1, 5)]
    assert not archive_file(archive_directory(service._path), workflow).exists()
    # Court 5: not one graph revision, version or current cell moved.
    assert store.revision == revision and _graph_counts(server) == baseline
    assert service._retention_last_run["status"] in ("idle", "changed")

    # Settings reads the policy, the last pass and the archived room over HTTP.
    status, overview = _request(server, "/api/universal/conversation-retention")
    assert status == 200 and overview["policy"]["inactive_days"] == 20, overview
    row = [item for item in overview["archived"] if item["conversation"] == old]
    assert row and row[0]["archived_at"] and row[0]["removed_messages"] == 5 and row[0]["archive_exists"]
    assert row[0]["title"] == "Old idea"
    assert overview["last_change"]["purged"] == 5

    opened = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: opened.append(args))
    status, located = _request(server, "/api/universal/conversation-archive-open", {"conversation": old})
    assert status == 200 and located["path"] == str(path) and opened == [["explorer", "/select," + str(path)]]

    # Court 4 over HTTP: restore re-imports the room; still no graph write.
    status, restored = _request(server, "/api/universal/conversation-restore", {"conversation": old})
    assert status == 200 and restored["restored"] == 5, restored
    assert _rows(history, old) == 5 and restored["archived_at"] is None
    assert [m["content"] for m in _page(history, old)] == ["first"] + ["message %d" % i for i in range(1, 5)]
    assert store.revision == revision and _graph_counts(server) == baseline
    status, missing = _request(server, "/api/universal/conversation-restore", {"conversation": recent})
    assert status == 404 and missing["ok"] is False

    # A browser POST is a person acting: the next pass waits for an idle moment.
    waiting = service.maintain_retention(authentication_context=context)
    assert waiting["status"] == "waiting-for-idle" and waiting["inspected"] == 0

def test_an_install_created_before_draft_protection_is_upgraded_at_an_idle_pass(tmp_path, monkeypatch):
    """A v4 store (fresh install from an earlier release) becomes v5 at one idle
    pass; its old room stays protected, a room created afterwards is removed
    once idle for 20 days, and the graph never moves."""
    from nodelang import commit_intent
    from nodelang import universal_application as app
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.workshop_conversation_catalog import create_workshop_conversation
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    with monkeypatch.context() as earlier_release:
        earlier_release.setattr(ConversationHistoryStore, "initialize_page_protection", lambda self, **k: None)
        earlier_release.setattr(ConversationHistoryStore, "track_new_conversation", lambda self, *a, **k: None)
        server = ApplicationServer(universal_state_path=tmp_path / "graph.sqlite3", universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False, live_watch=False)
    try:
        registry, store, service = server.universal_registry, server.universal_store, server.conversation_content
        history = service._history
        assert history._db.execute("PRAGMA user_version").fetchone()[0] == 4
        clock = [2_000_000_000.0]
        monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
        _fill(history, registry.workshop_root)
        context = registry.authorization.session.context(minimum_validity_seconds=5)
        # A backup taken BEFORE the upgrade (v4, tombstones without a content digest).
        backup = service.backup_recovery(tmp_path / "backups", authentication_context=context,
                                         timeout_seconds=60.0)
        upgraded = service.maintain_retention(authentication_context=context)
        assert upgraded["status"] == "upgraded"
        assert history._db.execute("PRAGMA user_version").fetchone()[0] == 5
        browser = server._resolve_browser_session(server.browser_session_token)
        with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="upgrade court setup"):
            app.set_universal_scope(store, registry, registry.map.domains["brain"], authentication_context=browser.context)
            app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                                    authentication_context=browser.context)
            room = create_workshop_conversation(server, authentication_context=browser.context,
                expected_revision=store.revision, title="After the upgrade",
                participant_roots=[browser.subject_root], idempotency_key="after-upgrade")["root"]
        assert history.born_tracked(room) and not history.born_tracked(registry.workshop_root)
        _fill(history, room)
        from nodelang import conversation_retention_maintenance as maintenance
        monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0], raising=False)
        _sweep(service, context)
        clock[0] += 21 * DAY
        baseline = _graph_counts(server)
        cursor = None
        for _ in range(20):
            result = service.maintain_retention(authentication_context=context, after_conversation_id=cursor)
            cursor = result["next_conversation_id"]
            if _rows(history, room) == 0 and cursor is None:
                break
        assert _rows(history, room) == 0
        assert _rows(history, registry.workshop_root) == 5   # legacy room: drafts unresolved, kept
        assert _graph_counts(server) == baseline
        assert history._has_content_digests()                # the purge changed the tombstone shape
        # Recovery: the pre-upgrade backup restores into the upgraded, purged owner as-is.
        restored_dir = tmp_path / "restored"
        service.prepare_recovery_restore(backup, restored_dir, authentication_context=context,
                                         timeout_seconds=60.0)
        content = restored_dir / service._path.name
        with sqlite3.connect(content) as check:
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("PRAGMA user_version").fetchone()[0] == 4
        restored = ConversationHistoryStore(content, instance_id=history.instance_id, create=False)
        try:
            assert _rows(restored, registry.workshop_root) == 5
            assert restored._has_content_digests() is False
            restored.initialize_page_protection()             # what the next idle pass does
            assert restored._db.execute("PRAGMA user_version").fetchone()[0] == 5
            assert restored._db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            restored.close()
        # And the reverse shape: a backup of the upgraded, purged owner restores too.
        again = service.backup_recovery(tmp_path / "backups-after", authentication_context=context,
                                        timeout_seconds=60.0)
        service.prepare_recovery_restore(again, tmp_path / "restored-after", authentication_context=context,
                                         timeout_seconds=60.0)
        with sqlite3.connect(tmp_path / "restored-after" / service._path.name) as check:
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert check.execute("SELECT count(*) FROM message_tombstones WHERE content_digest IS NOT NULL"
                                 ).fetchone()[0] == 5
    finally:
        server.close()


# ---- Verifier findings, 2026-09-24. Each court names only APIs the previous
# patch also had, so on that code it fails on its own assertion.

def _export_with_rebuild(path, room, instance, messages):
    """What the owner paths do: a missing index is rebuilt, then export runs."""
    import time as _time
    from nodelang import conversation_archive as archive
    try:
        return export_messages(path, room, instance, messages)
    except Exception as refused:
        if type(refused).__name__ != "ArchiveIndexStale":
            raise
        archive.rebuild_index(path, room, instance, deadline=_time.monotonic() + 20)
        return export_messages(path, room, instance, messages)


def test_a_differing_archived_line_keeps_the_message_and_writes_a_conflict_file(tmp_path):
    """Verifier probe: seq 3 already archived with other content must not be deleted."""
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    _ready(history)
    messages = _page(history)
    clock[0] += 21 * DAY
    _archive_now(history)
    path = archive_file(archive_directory(tmp_path / "content.sqlite3"), ROOM)
    path.parent.mkdir(parents=True)
    header = {"kind": "conversation-archive", "version": 1, "conversation_id": ROOM,
              "instance_id": history.instance_id}
    other = {"kind": "message", **dict(messages[2], content="not what the store holds")}
    path.write_text(json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n"
                    + json.dumps(other, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
            before_commit=lambda: None,
            export=lambda m: _export_with_rebuild(path, ROOM, history.instance_id, m))
    assert _rows(history) == 5                      # every message is still in the store
    assert history._db.execute("SELECT count(*) FROM message_tombstones").fetchone()[0] == 0
    conflict = json.loads(Path(str(path) + ".conflict.json").read_text(encoding="utf-8"))
    assert [row["sequence"] for row in conflict] == [3]
    assert "not what the store holds" in conflict[0]["in_archive"]
    assert "message 2" in conflict[0]["in_store"]
    # While the conflict file stands, no later pass deletes this room.
    with pytest.raises(ValueError):
        history.purge_archived(ROOM, **_cas(history.retention_status(ROOM)), protected=False,
            before_commit=lambda: None,
            export=lambda m: _export_with_rebuild(path, ROOM, history.instance_id, m))
    assert _rows(history) == 5


def test_export_under_the_lock_reads_only_its_batch_not_the_whole_archive(tmp_path, monkeypatch):
    import builtins
    import io
    room, instance = "app:big-room", "instance-1"
    path = archive_file(tmp_path / "archive", room)

    def message(sequence):
        return {"id": "m%d" % sequence, "conversation_id": room, "sequence": sequence, "author": "founder",
                "content": ("x" * 10_000) + str(sequence), "category": "note", "recipients": [], "refs": [],
                "evidence": [], "reply_to": None, "created_at": "2026-01-01T00:00:00+00:00",
                "idempotency_key": "k%d" % sequence}

    for start in range(1, 401, 100):                 # 4 MB already archived and indexed
        _export_with_rebuild(path, room, instance, [message(s) for s in range(start, start + 100)])
    assert path.stat().st_size > 4_000_000
    read = [0]
    real_open = io.open

    class Counted:
        def __init__(self, handle):
            self._handle = handle
        def read(self, *args):
            data = self._handle.read(*args)
            read[0] += len(data)
            return data
        def __getattr__(self, name):
            return getattr(self._handle, name)
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return self._handle.__exit__(*exc)

    def counting_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return Counted(handle) if str(file).endswith(".jsonl") and "b" in mode else handle

    monkeypatch.setattr(io, "open", counting_open)
    monkeypatch.setattr(builtins, "open", counting_open)
    written = export_messages(path, room, instance, [message(s) for s in range(401, 406)])
    monkeypatch.undo()
    assert tuple(written) == (401, 402, 403, 404, 405)
    assert read[0] < 5 * 11_000 + 8192, read[0]     # its own lines read back + the header


def test_a_rotation_refused_by_a_held_log_destroys_no_older_copy(tmp_path, monkeypatch):
    import os
    from nodelang import log_rotation
    log = tmp_path / "launcher.log"
    log.write_bytes(b"current" * 400)
    for index in (1, 2, 3):
        (tmp_path / ("launcher.log.%d" % index)).write_bytes(b"copy %d" % index)
    real_replace = os.replace

    def held(source, target, *args, **kwargs):
        if os.path.abspath(source) == os.path.abspath(log):
            raise PermissionError("the log is held open by another process")
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", held)
    for _ in range(5):
        log_rotation.rotate(log, 1000, 3)
    monkeypatch.undo()
    held_bytes = lambda path: path.read_bytes() if path.exists() else None
    assert held_bytes(log) == b"current" * 400
    assert [held_bytes(tmp_path / ("launcher.log.%d" % i)) for i in (1, 2, 3)] == [b"copy 1", b"copy 2", b"copy 3"]


def test_a_rotation_interrupted_after_moving_the_log_is_finished_next_time(tmp_path, monkeypatch):
    import os
    from nodelang import log_rotation
    log = tmp_path / "launcher.log"
    log.write_bytes(b"current" * 400)
    (tmp_path / "launcher.log.1").write_bytes(b"copy 1")
    real_replace = os.replace
    failures = [1]

    def shift_fails_once(source, target, *args, **kwargs):
        if str(source).endswith(".log.1") and failures[0]:
            failures[0] = 0
            raise PermissionError("copy held for a moment")
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", shift_fails_once)
    log_rotation.rotate(log, 1000, 3)
    monkeypatch.undo()
    log_rotation.rotate(log, 1000, 3)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["launcher.log.1", "launcher.log.2"], names
    assert (tmp_path / "launcher.log.1").read_bytes() == b"current" * 400
    assert (tmp_path / "launcher.log.2").read_bytes() == b"copy 1"


def test_geometry_receipts_back_off_when_the_log_cannot_rotate(tmp_path, monkeypatch):
    import os
    from nodelang import log_rotation
    from nodelang.baboom_native_companion import BaboomNativeCompanionController
    monkeypatch.setattr(log_rotation, "GEOMETRY_LOG_BYTES", 2000)
    log = tmp_path / "baboom-geometry.log"
    log.write_bytes(b"g" * 5000)
    attempts = [0]
    real_replace = os.replace

    def held(source, target, *args, **kwargs):
        if os.path.abspath(source) == os.path.abspath(log):
            attempts[0] += 1
            raise PermissionError("held open")
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", held)
    companion = BaboomNativeCompanionController.__new__(BaboomNativeCompanionController)
    companion._geometry_log = log
    for index in range(200):
        companion.geometry_receipt("moved to %d" % index)
    assert attempts[0] <= 1, attempts[0]


def _room(server, title, key):
    from nodelang import commit_intent
    from nodelang import universal_application as app
    from nodelang.workshop_conversation_catalog import create_workshop_conversation
    registry, store = server.universal_registry, server.universal_store
    browser = server._resolve_browser_session(server.browser_session_token)
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="retention court room"):
        app.set_universal_scope(store, registry, registry.map.domains["brain"], authentication_context=browser.context)
        app.set_universal_scope(store, registry, registry.workshop_workbench_root, authentication_context=browser.context)
        return browser, create_workshop_conversation(server, authentication_context=browser.context,
            expected_revision=store.revision, title=title, participant_roots=[browser.subject_root],
            idempotency_key=key)["root"]


def test_polls_never_keep_a_room_but_an_explicit_open_does(application, monkeypatch):
    """SPEC 3.6: an unattended window polling every 2.5 s must not extend
    retention; a person opening the conversation daily must."""
    from nodelang import conversation_retention_maintenance as maintenance
    from nodelang.existing_workshop_conversation import read_browser_workshop
    server = application
    service, history = server.conversation_content, server.conversation_content._history
    scope = server.universal_registry.workshop_workbench_root
    browser, polled = _room(server, "Left open, polled", "polled-room")
    _browser, opened = _room(server, "Opened every day", "opened-room")
    clock = [2_200_000_000.0]
    monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
    monkeypatch.setattr(maintenance, "_monotonic", lambda: clock[0], raising=False)
    for room in (polled, opened):
        _fill(history, room)
    token = server.browser_session_token

    def read(room, previous=None):
        return read_browser_workshop(server, browser, root=room, scope=scope, session_token=token,
            after=None if previous is None else str(previous["revision"]),
            content_after=None if previous is None else previous["content_cursor"])

    def open_room(room):
        import time as _time
        before = history.retention_status(room)["activity_revision"]
        status, _body = _request(server, "/api/universal/workshop?root=%s&scope=%s&open=1"
                                 % (quote(room, safe=""), quote(scope, safe="")))
        assert status == 200
        deadline = _time.monotonic() + 3             # recorded after the page is sent
        while history.retention_status(room)["activity_revision"] == before and _time.monotonic() < deadline:
            _time.sleep(0.02)

    open_room(polled)                               # the window opens once, at the start
    last = read(polled)
    context = server.universal_registry.authorization.session.context(minimum_validity_seconds=5)
    _sweep(service, context)
    for _day in range(21):
        for _tick in range(24):                     # the Studio refresh: every 2.5 s
            clock[0] += 2.5
            last = read(polled, last)
        clock[0] += DAY - 60
        open_room(opened)                           # a person opens this room each day
        _sweep(service, context)
    assert _rows(history, opened) == 5              # opened daily: kept
    assert _rows(history, polled) == 0              # only polled for 21 days: removed


def test_a_wall_clock_jumped_forward_a_month_removes_nothing(application, monkeypatch):
    from nodelang import conversation_retention_maintenance as maintenance
    server = application
    service, history = server.conversation_content, server.conversation_content._history
    _browser, room = _room(server, "Clock jump", "clock-jump")
    clock, mono = [2_400_000_000.0], [5_000_000.0]
    monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
    monkeypatch.setattr(maintenance, "_monotonic", lambda: mono[0], raising=False)
    _fill(history, room)
    context = server.universal_registry.authorization.session.context(minimum_validity_seconds=5)
    _sweep(service, context)
    clock[0] += 30 * DAY                            # the system clock is set a month ahead
    mono[0] += 60                                   # while one minute really passed
    _sweep(service, context)
    _sweep(service, context)
    assert _rows(history, room) == 5                # nothing removed by a clock change
    for _day in range(21):                          # then 21 genuinely observed days
        clock[0] += DAY
        mono[0] += DAY
        _sweep(service, context)
    assert _rows(history, room) == 0                # retention still works on observed time


def test_setting_the_clock_back_and_forward_across_restarts_earns_no_idle_time(application, monkeypatch):
    """Verifier probe: back, save, forward + restart must not earn restart credit each cycle."""
    from nodelang import conversation_retention_maintenance as maintenance
    server = application
    service, history = server.conversation_content, server.conversation_content._history
    _browser, room = _room(server, "Clock toggled", "clock-toggle")
    clock, mono = [2_600_000_000.0], [9_000_000.0]
    monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
    monkeypatch.setattr(maintenance, "_monotonic", lambda: mono[0], raising=False)
    _fill(history, room)
    context = server.universal_registry.authorization.session.context(minimum_validity_seconds=5)
    _sweep(service, context)                        # the room's activity is observed
    clock[0] += 21 * DAY                            # wall clock set 21 days ahead
    mono[0] += 700
    _sweep(service, context)
    high = clock[0]
    for _cycle in range(7):
        clock[0] = high - 3 * DAY                   # set back three days
        mono[0] += 700
        _sweep(service, context)                    # observed and saved
        service._retention_observed = None          # the app restarts
        clock[0] = high                             # set forward again
        mono[0] += 700
        _sweep(service, context)
    assert _rows(history, room) == 5                # no idle time was earned


def test_only_an_explicit_open_counts_never_a_read_without_cursors(application, monkeypatch):
    """A2: a refresh after a failed read carries no cursor; only open=1 is a person opening."""
    import time as _time
    server = application
    history = server.conversation_content._history
    _browser, room = _room(server, "Explicit open only", "explicit-open")
    clock = [2_800_000_000.0]
    monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
    _fill(history, room)
    scope = server.universal_registry.workshop_workbench_root
    query = "/api/universal/workshop?root=%s&scope=%s" % (quote(room, safe=""), quote(scope, safe=""))
    before = history.retention_status(room)["activity_revision"]
    clock[0] += 2 * 3600
    status, _page_body = _request(server, query)            # cursorless read, as after an error
    assert status == 200
    _time.sleep(0.5)
    assert history.retention_status(room)["activity_revision"] == before
    status, _page_body = _request(server, query + "&open=1")  # a person navigates here
    assert status == 200
    deadline = _time.monotonic() + 3
    while history.retention_status(room)["activity_revision"] == before and _time.monotonic() < deadline:
        _time.sleep(0.05)
    assert history.retention_status(room)["activity_revision"] == before + 1


def test_an_open_under_a_foreign_write_lock_never_stalls_or_fails_the_page(application, monkeypatch):
    """A1: the activity note never blocks a read and never holds the owner lock."""
    import time as _time
    server = application
    service, history = server.conversation_content, server.conversation_content._history
    _browser, room = _room(server, "Busy store", "busy-store")
    clock = [3_000_000_000.0]
    monkeypatch.setattr(history, "_retention_clock", lambda: clock[0])
    _fill(history, room)
    clock[0] += 2 * 3600
    scope = server.universal_registry.workshop_workbench_root
    query = "/api/universal/workshop?root=%s&scope=%s" % (quote(room, safe=""), quote(scope, safe=""))
    notes = []
    real_note = getattr(history, "note_open", None)

    def observed_note(*args, **kwargs):
        started = _time.monotonic()
        owned = server.mutation_lock._is_owned()
        try:
            return real_note(*args, **kwargs)
        finally:
            notes.append((owned, _time.monotonic() - started))

    if real_note is not None:
        monkeypatch.setattr(history, "note_open", observed_note)
    before = history.retention_status(room)["activity_revision"]
    foreign = sqlite3.connect(str(service._path), timeout=0, isolation_level=None)
    foreign.execute("BEGIN IMMEDIATE")                      # another writer holds the store
    try:
        timings = []
        for suffix in ("", "&open=1"):
            started = _time.monotonic()
            status, body = _request(server, query + suffix)
            timings.append(_time.monotonic() - started)
            assert status == 200 and body.get("ok") is not False, body
        assert max(timings) < 1.0, timings                 # the page is never held behind the lock
        deadline = _time.monotonic() + 3
        while not notes and _time.monotonic() < deadline:
            _time.sleep(0.05)
        assert notes and all(owned is False for owned, _ in notes), notes
        assert all(elapsed < 0.2 for _, elapsed in notes), notes
        assert history.retention_status(room)["activity_revision"] == before  # skipped, not waited
    finally:
        foreign.execute("ROLLBACK")
        foreign.close()
    status, _body = _request(server, query + "&open=1")
    assert status == 200
    deadline = _time.monotonic() + 3
    while history.retention_status(room)["activity_revision"] == before and _time.monotonic() < deadline:
        _time.sleep(0.05)
    assert history.retention_status(room)["activity_revision"] == before + 1


def test_the_open_note_skips_a_locked_store_within_its_budget_and_never_blocks_readers(tmp_path):
    """v5: the note's first plain read also waits at most 50 ms; readers behind it are not held."""
    import threading
    import time as _time
    clock = [1_000_000.0]
    history = _history(tmp_path, clock)
    _fill(history)
    clock[0] += 2 * 3600
    foreign = sqlite3.connect(str(tmp_path / "content.sqlite3"), timeout=0, isolation_level=None)
    foreign.execute("BEGIN EXCLUSIVE")                    # a writer commits: nobody may read
    try:
        probe = sqlite3.connect(str(tmp_path / "content.sqlite3"), timeout=0)
        with pytest.raises(sqlite3.OperationalError):
            probe.execute("SELECT count(*) FROM conversation_retention").fetchone()
        probe.close()
        outcome = {}

        def note():
            started = _time.monotonic()
            try:
                outcome["result"] = history.note_open(ROOM)
            except Exception as refused:                # the old read raised after 2 s
                outcome["result"] = refused
            outcome["seconds"] = _time.monotonic() - started

        worker = threading.Thread(target=note)
        worker.start()
        _time.sleep(0.01)
        waited = _time.monotonic()
        acquired = history._lock.acquire(timeout=5)      # a concurrent reader's first step
        reader_wait = _time.monotonic() - waited
        if acquired:
            history._lock.release()
        worker.join(10)
        assert outcome["seconds"] < 0.15, outcome          # skipped within its budget
        assert outcome["result"] is None, outcome
        assert reader_wait < 0.1, reader_wait               # the reader was not held behind it
    finally:
        foreign.execute("ROLLBACK")
        foreign.close()
    assert history.note_open(ROOM) is not None            # free store: the open is recorded
