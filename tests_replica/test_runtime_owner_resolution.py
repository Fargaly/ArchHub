"""Court: the machine's active runtime is resolved, never guessed.

The announcement at %LOCALAPPDATA%/ArchHub/active-universal-runtime.json is a
signed POINTER to one runtime's own record. resolve_active_runtime() accepts it
only when the signature, runtime id, status, process id AND creation time, and
the graph's runtime-ownership generation all hold -- with no fallback to any
other record. A clean exit leaves the pointer naming a "stopped" record; no
older owner is ever restored.
"""
import dataclasses
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from nodelang import application_machine_transport as transport_module
from nodelang.application_machine_transport import (
    RuntimeResolutionError,
    UniversalRuntimeTransport,
    read_runtime_owner_generation,
    resolve_active_runtime,
    verify_active_runtime,
    write_runtime_pointer,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider

APP = "app:archhub"


def _provider():
    return MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"p" * 32)


def _graph(path, *rows):
    """A graph database holding runtime-ownership records: (generation, state)."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS operational_records (kind TEXT NOT NULL, "
        "record_root TEXT NOT NULL, owner_root TEXT NOT NULL, state TEXT NOT NULL, "
        "generation INTEGER NOT NULL, authority_revision INTEGER NOT NULL, "
        "updated_at REAL NOT NULL, payload TEXT NOT NULL)"
    )
    for generation, state in rows:
        connection.execute(
            "INSERT INTO operational_records VALUES ('runtime-ownership', ?, ?, ?, 1, 1, ?, ?)",
            ("rec:%d" % generation, APP, state, time.time(),
             json.dumps({"generation": generation, "resource_root": APP})),
        )
    connection.commit()
    connection.close()


def _set_state(path, generation, state):
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE operational_records SET state = ? WHERE record_root = ?",
        (state, "rec:%d" % generation),
    )
    connection.commit()
    connection.close()


def _transport(tmp_path, name, database, generation, pointer):
    return UniversalRuntimeTransport(
        lambda _request: {},
        application_root=APP,
        agent_session_root="app:agent-session:founder",
        workshop_root="app:workshop",
        work_registry_root="app:governed-work-registry",
        database=str(database),
        descriptor_path=tmp_path / (name + ".runtime-descriptor.json"),
        pointer_path=pointer,
        owner_generation=generation,
        key_provider=_provider(),
    )


def _kind(pointer, provider):
    with pytest.raises(RuntimeResolutionError) as refusal:
        resolve_active_runtime(pointer, provider)
    return refusal.value.kind


def test_stop_restart_pair_resolves_only_the_current_owner(tmp_path):
    database = tmp_path / "graph.sqlite3"
    pointer = tmp_path / "active-universal-runtime.json"
    provider = _provider()
    _graph(database, (1, "active"))
    first = _transport(tmp_path, "first", database, 1, pointer).start()
    try:
        owner = resolve_active_runtime(pointer, provider)
        assert owner.runtime_id == first.runtime_id
        assert owner.owner_generation == 1
        assert owner.process_created_at > 0
        assert json.loads(pointer.read_text())["format"] == "archhub.universal-runtime-pointer"
    finally:
        first.close()
    _set_state(database, 1, "released")
    # Clean exit: the pointer names a stopped record; nothing older comes back.
    assert _kind(pointer, provider) == "stopped"

    _graph(database, (2, "active"))
    second = _transport(tmp_path, "second", database, 2, pointer).start()
    try:
        assert resolve_active_runtime(pointer, provider).runtime_id == second.runtime_id
    finally:
        second.close()
    _set_state(database, 2, "released")
    assert _kind(pointer, provider) == "stopped"
    # The first runtime's own record is stopped too: no record anywhere says active.
    for record in tmp_path.glob("*.runtime-descriptor.json"):
        assert json.loads(record.read_text())["status"] == "stopped"


def test_a_superseded_generation_is_refused_even_while_its_process_lives(tmp_path):
    database = tmp_path / "graph.sqlite3"
    pointer = tmp_path / "active-universal-runtime.json"
    provider = _provider()
    _graph(database, (1, "active"))
    older = _transport(tmp_path, "older", database, 1, pointer).start()
    try:
        assert resolve_active_runtime(pointer, provider).owner_generation == 1
        # Another runtime took the graph over (generation 2); this process is
        # still alive and its record still says "active" -- it is NOT the owner.
        _set_state(database, 1, "failed")
        _graph(database, (2, "active"))
        assert _kind(pointer, provider) == "superseded"
    finally:
        older.close()


def test_a_reused_process_id_is_not_the_owner(tmp_path, monkeypatch):
    database = tmp_path / "graph.sqlite3"
    pointer = tmp_path / "active-universal-runtime.json"
    provider = _provider()
    _graph(database, (1, "active"))
    runtime = _transport(tmp_path, "reused", database, 1, pointer).start()
    try:
        recorded = resolve_active_runtime(pointer, provider).process_created_at
        # The same process id now belongs to a process created at another time.
        monkeypatch.setattr(transport_module, "_process_created_at",
                            lambda _pid: recorded + 10_000_000)
        assert _kind(pointer, provider) == "pid-reused"
    finally:
        monkeypatch.undo()
        runtime.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity")
def test_process_identity_is_the_creation_time_of_a_real_process():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        created = transport_module._process_created_at(child.pid)
        assert type(created) is int and created > 0
        assert transport_module._process_created_at(child.pid) == created
        assert transport_module._process_created_at(os.getpid()) != created
    finally:
        child.kill()
        child.wait()
    # An exited process is no owner, whatever identity its handle still reports.
    assert transport_module._windows_process_is_active(child.pid) is False


def test_a_dead_owner_is_refused_and_no_other_record_is_used(tmp_path, monkeypatch):
    database = tmp_path / "graph.sqlite3"
    pointer = tmp_path / "active-universal-runtime.json"
    provider = _provider()
    _graph(database, (1, "active"))
    runtime = _transport(tmp_path, "dead", database, 1, pointer).start()
    try:
        monkeypatch.setattr(transport_module, "_windows_process_is_active", lambda _pid: False)
        assert _kind(pointer, provider) == "dead"
    finally:
        monkeypatch.undo()
        runtime.close()
    # A second, perfectly live-looking owner record beside the pointer is NOT
    # a fallback: the pointer names one record and only that one is judged.
    _graph(database, (2, "active"))
    other = _transport(tmp_path, "other", database, 2, None).start()
    try:
        assert _kind(pointer, provider) == "stopped"
        (tmp_path / "dead.runtime-descriptor.json").unlink()
        assert _kind(pointer, provider) == "unreadable"
    finally:
        other.close()


def test_a_forged_or_mismatched_pointer_is_refused(tmp_path):
    database = tmp_path / "graph.sqlite3"
    pointer = tmp_path / "active-universal-runtime.json"
    provider = _provider()
    _graph(database, (1, "active"))
    runtime = _transport(tmp_path, "signed", database, 1, pointer).start()
    try:
        document = json.loads(pointer.read_text())
        document["owner_generation"] = 7
        pointer.write_text(json.dumps(document))
        assert _kind(pointer, provider) == "unreadable"
        # Correctly signed, but naming a generation its record does not hold.
        descriptor = transport_module._read_descriptor_document(runtime.descriptor_path, provider)
        write_runtime_pointer(pointer, runtime.descriptor_path,
                              dataclasses.replace(descriptor, owner_generation=9), provider)
        assert _kind(pointer, provider) == "unreadable"
    finally:
        runtime.close()
    assert _kind(tmp_path / "absent.json", provider) == "missing"


def test_a_legacy_v1_record_never_resolves_as_a_live_owner(tmp_path):
    provider = _provider()
    runtime = _transport(tmp_path, "legacy", "", 0, None).start()
    try:
        descriptor = transport_module._read_descriptor_document(runtime.descriptor_path, provider)
        legacy = dataclasses.replace(
            descriptor, format_version=1, owner_generation=0, process_created_at=0)
        with pytest.raises(RuntimeResolutionError) as refusal:
            verify_active_runtime(legacy)
        assert refusal.value.kind == "legacy"
    finally:
        runtime.close()


def test_the_generation_read_is_bounded_and_fails_closed_under_a_writer(tmp_path):
    database = tmp_path / "graph.sqlite3"
    _graph(database, (3, "active"))
    assert read_runtime_owner_generation(str(database), APP) == (3, "active")
    assert read_runtime_owner_generation(str(database), "app:other") is None
    assert read_runtime_owner_generation(str(tmp_path / "absent.sqlite3"), APP) is None
    # A writer holds the database exclusively: the read waits at most its
    # budget (200 ms) and answers "unreadable", never a guess.
    writer = sqlite3.connect(database, isolation_level=None)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        assert read_runtime_owner_generation(str(database), APP) is None
        assert time.monotonic() - started < 1.0
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert transport_module._GENERATION_READ_BUDGET <= 0.2


def test_the_generation_read_never_takes_the_write_lock(tmp_path, monkeypatch):
    database = tmp_path / "graph.sqlite3"
    _graph(database, (1, "active"))
    opened = []
    real_connect = sqlite3.connect

    def spy(target, *args, **kwargs):
        opened.append((target, kwargs.get("uri")))
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(transport_module.sqlite3, "connect", spy)
    assert read_runtime_owner_generation(str(database), APP) == (1, "active")
    assert opened and all(uri is True and "mode=ro" in str(target) for target, uri in opened)


def test_the_launcher_announces_by_pointer_and_restores_nothing():
    source = open(os.path.join(os.path.dirname(__file__), os.pardir,
                               "launch_archhub_test.py"), encoding="utf-8").read()
    assert "_previous_active" not in source
    assert "machine_pointer_path=" in source
    assert "active-universal-runtime.json" in source
    assert ".write_bytes(" not in source.split("def _finish_application_shutdown", 1)[-1].split("def ", 1)[0]
