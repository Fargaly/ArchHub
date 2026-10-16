from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from nodelang.universal_cell import DatabaseOwnerConflict


ROOT = Path(__file__).resolve().parents[1]


def _launcher_names(*names, **bindings):
    tree = ast.parse((ROOT / "launch_archhub_test.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in selected} == set(names)
    namespace = dict(bindings)
    exec(compile(ast.Module(body=selected, type_ignores=[]), "launch_archhub_test.py", "exec"), namespace)
    return namespace


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _saved_graph_probe():
    return _launcher_names("_saved_graph_exists", os=__import__("os"))["_saved_graph_exists"]


def _saved_application(path):
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    with CellStore(path) as store:
        store.commit(store.revision, create=(Cell("app:archhub", NULL_CELL_ID, NULL_CELL_ID, b""),))


def test_upgrade_preflight_admits_the_existing_2230_graph_for_migration(tmp_path):
    legacy = tmp_path / "archhub-test.universal.sqlite3"
    _saved_application(legacy)
    (tmp_path / "runtime-descriptor.json").write_text("{}", encoding="utf-8")
    before = legacy.read_bytes()
    assert _saved_graph_probe()(tmp_path, tmp_path / "authority.sqlite3") is True
    assert legacy.read_bytes() == before
    assert not (tmp_path / "authority.sqlite3").exists()


def test_upgrade_preflight_still_refuses_a_missing_target_with_its_own_wal(tmp_path):
    _saved_application(tmp_path / "archhub-test.universal.sqlite3")
    (tmp_path / "authority.sqlite3-wal").write_bytes(b"unreconciled target")
    with pytest.raises(RuntimeError, match="recovery files remain"):
        _saved_graph_probe()(tmp_path, tmp_path / "authority.sqlite3")


def test_upgrade_preflight_never_treats_a_corrupt_legacy_graph_as_first_run(tmp_path):
    (tmp_path / "archhub-test.universal.sqlite3").write_bytes(b"not sqlite")
    with pytest.raises(RuntimeError, match="unreadable database header"):
        _saved_graph_probe()(tmp_path, tmp_path / "authority.sqlite3")


def test_selected_generation_presence_checks_the_actual_database_directory(tmp_path):
    database = tmp_path / "unified-authority" / "generations" / "test-generation" / "authority.sqlite3"
    database.parent.mkdir(parents=True)
    _saved_application(database)
    (tmp_path / "runtime-descriptor.json").write_text("{}", encoding="utf-8")
    assert _saved_graph_probe()(tmp_path, database) is True


def test_transient_owner_conflict_retries_until_the_saved_graph_opens():
    clock = FakeClock()
    calls = []

    def boot():
        calls.append("boot")
        if len(calls) < 4:
            raise DatabaseOwnerConflict("held by previous owner")
        return "server"

    messages = []
    ns = _launcher_names(
        "_open_saved_graph",
        "_release_own_fence",
        "_is_transient_owner_conflict",
        _boot=boot,
        print=lambda *parts, **_kw: messages.append(" ".join(str(p) for p in parts)),
        time=clock,
        state_path=Path("archhub-test.universal.sqlite3"),
        state_dir=Path("."),
        os=__import__("os"),
    )

    server, refusal = ns["_open_saved_graph"](
        max_wait_seconds=45.0,
        sleep_seconds=1.0,
    )

    assert server == "server"
    assert refusal is None
    assert len(calls) == 4
    assert clock.sleeps == [1.0, 1.0, 1.0]
    assert sum("owner lock still held" in item for item in messages) == 3
    assert any("the saved graph opened on attempt 4" in item for item in messages)


def test_owner_conflict_past_window_refuses_and_marks_descriptor_not_active():
    clock = FakeClock()
    messages = []
    descriptor_statuses = []
    boxes = []
    exits = []

    ns = _launcher_names(
        "_open_saved_graph",
        "_release_own_fence",
        "_is_transient_owner_conflict",
        "_refuse_boot_without_living",
        "_boot_refusal_message",
        _boot=lambda: (_ for _ in ()).throw(DatabaseOwnerConflict("still held")),
        print=lambda *parts, **_kw: messages.append(" ".join(str(p) for p in parts)),
        time=clock,
        state_path=Path("archhub-test.universal.sqlite3"),
        state_dir=Path("."),
        os=__import__("os"),
        descriptor_path=Path("runtime-descriptor.json"),
        machine_key_provider=object(),
        _log_path=Path("launcher.log"),
        _mark_runtime_refused=lambda refusal: descriptor_statuses.append(type(refusal).__name__),
        _message_box=lambda message, **kwargs: boxes.append((message, kwargs)) or True,
        _exit_process=lambda code: exits.append(code),
    )

    server, refusal = ns["_open_saved_graph"](
        max_wait_seconds=3.0,
        sleep_seconds=1.0,
    )
    assert server is None
    assert isinstance(refusal, DatabaseOwnerConflict)

    ns["_refuse_boot_without_living"](refusal)

    assert descriptor_statuses == ["DatabaseOwnerConflict"]
    assert len(boxes) == 1
    assert boxes[0][1].get("blocking") is False
    assert boxes[0][1].get("quit_event") is not None
    assert exits == [1]
    assert len(clock.sleeps) == 3
    assert any("owner lock still held" in item for item in messages)


def test_quit_request_during_refusal_message_exits():
    exits = []
    quit_event = threading.Event()

    ns = _launcher_names(
        "_boot_refusal_message",
        "_refuse_boot_without_living",
        _mark_runtime_refused=lambda _refusal: None,
        _message_box=lambda _message, **kwargs: kwargs["quit_event"].set() or True,
        _exit_process=lambda code: exits.append(code),
        _log_path=Path("launcher.log"),
    )

    ns["_refuse_boot_without_living"](
        RuntimeError("boom"),
        quit_event=quit_event,
    )

    assert quit_event.is_set()
    assert exits == [1]


def test_excepthook_uses_nonblocking_notice_when_qt_loop_is_running():
    boxes = []
    ns = _launcher_names(
        "_tell_the_person",
        "_qt_event_loop_running",
        "_boot_refusal_message",
        traceback=__import__("traceback"),
        _log_path=Path("launcher.log"),
        _message_box=lambda message, **kwargs: boxes.append((message, kwargs)) or True,
        _qt_app_event_loop_active=lambda: True,
    )

    ns["_tell_the_person"](RuntimeError, RuntimeError("bad boot"), None)

    assert boxes
    assert boxes[0][1].get("blocking") is False
