"""Authority courts for a shared durable Universal Cell journal.

These courts stay below every product protocol.  They prove that changing the
physical journal does not change the only semantic record, revision ordering,
optimistic conflict behavior, or migration evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from types import SimpleNamespace
from types import MappingProxyType

import pytest

import nodelang.application_server as application_server_module
import nodelang.universal_cell as universal_cell_module
from nodelang.cell_attestations import CourtInvocation
from nodelang.application_server import ApplicationServer
from nodelang.universal_application import _runtime_ownership_court_runner
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    DatabaseOwnerConflict,
    InvalidCell,
    migrate_cell_history,
)


@dataclass
class _SharedJournalState:
    current: dict[str, Cell] = field(default_factory=lambda: {
        NULL_CELL_ID: Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
    })
    revision: int = 0
    versions: dict[int, tuple[Cell, ...]] = field(default_factory=lambda: {
        0: (Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b""),)
    })
    changes: dict[int, tuple[str, ...]] = field(default_factory=lambda: {
        0: (NULL_CELL_ID,)
    })
    runtime_fences: set[str] = field(default_factory=set)


class _SharedJournal:
    backend = "court-shared"
    local_path = None
    exclusive_owner = False
    shared_writers = True

    def __init__(self, state: _SharedJournalState, identity: str) -> None:
        self._state = state
        self.identity = identity
        self.closed = False

    def load(self):
        return (
            MappingProxyType(dict(self._state.current)),
            self._state.revision,
            dict(self._state.versions),
            dict(self._state.changes),
        )

    def append(self, expected_revision, next_revision, changed):
        if self._state.revision != expected_revision:
            raise Conflict(
                "expected durable revision %s, current revision is %s"
                % (expected_revision, self._state.revision)
            )
        changed = tuple(changed)
        assert next_revision == expected_revision + 1
        self._state.revision = next_revision
        self._state.versions[next_revision] = changed
        self._state.changes[next_revision] = tuple(
            sorted(cell.id for cell in changed)
        )
        self._state.current.update({cell.id: cell for cell in changed})

    def close(self):
        self.closed = True

    def backup_to(self, _destination):
        raise InvalidCell(
            "shared authority recovery requires a provider restore drill"
        )

    def acquire_runtime_fence(self, resource_id):
        if resource_id in self._state.runtime_fences:
            raise DatabaseOwnerConflict(
                "shared authority already has an active runtime owner"
            )
        self._state.runtime_fences.add(resource_id)
        released = False

        def release():
            nonlocal released
            if released:
                return
            released = True
            self._state.runtime_fences.discard(resource_id)

        return release


def _leaf(root_id: str, atom: bytes) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def test_cellstore_accepts_one_storage_neutral_shared_authority():
    state = _SharedJournalState()
    store = CellStore(journal=_SharedJournal(state, "court:one-root"))

    assert store.durability_backend == "court-shared"
    assert store.authority_identity == "court:one-root"
    assert store.database_path is None
    assert store.has_exclusive_database_owner is False
    assert store.supports_shared_writers is True

    store.commit(0, create=(_leaf("cloud:root", bytes(range(256))),))
    reopened = CellStore(journal=_SharedJournal(state, "court:one-root"))
    assert reopened.read("cloud:root").atom == bytes(range(256))
    assert reopened.revision_chain_digest() == store.revision_chain_digest()


def test_stale_shared_writer_fails_then_refreshes_to_accepted_revision():
    state = _SharedJournalState()
    first = CellStore(journal=_SharedJournal(state, "court:shared"))
    stale = CellStore(journal=_SharedJournal(state, "court:shared"))

    first.commit(0, create=(_leaf("cloud:first", b"accepted"),))
    with pytest.raises(Conflict, match="current revision is 1"):
        stale.commit(0, create=(_leaf("cloud:stale", b"rejected"),))

    assert stale.revision == 1
    assert stale.read("cloud:first").atom == b"accepted"
    assert "cloud:stale" not in stale.snapshot().cells
    stale.commit(1, create=(_leaf("cloud:second", b"retried"),))
    assert first.refresh() == 2
    assert first.read("cloud:second").atom == b"retried"


def test_exact_history_migration_preserves_revisions_cells_and_chain_digest():
    source = CellStore()
    source.commit(0, create=(_leaf("cloud:migrate", b"before"),))
    source.commit(1, replace=(_leaf("cloud:migrate", b"after"),))
    target = CellStore(
        journal=_SharedJournal(_SharedJournalState(), "court:destination")
    )

    evidence = migrate_cell_history(source, target)

    assert evidence.source_revision == evidence.destination_revision == 2
    assert evidence.revision_chain_digest == source.revision_chain_digest()
    assert target.revision_chain_digest() == source.revision_chain_digest()
    assert target.at(1).cells["cloud:migrate"].atom == b"before"
    assert target.read("cloud:migrate").atom == b"after"


def test_migration_rejects_a_nonempty_destination_and_same_authority():
    source = CellStore()
    source.commit(0, create=(_leaf("source", b"source"),))
    target = CellStore(
        journal=_SharedJournal(_SharedJournalState(), "court:destination")
    )
    target.commit(0, create=(_leaf("target", b"target"),))

    with pytest.raises(InvalidCell, match="destination must be at genesis"):
        migrate_cell_history(source, target)

    same_state = _SharedJournalState()
    first = CellStore(journal=_SharedJournal(same_state, "court:same"))
    second = CellStore(journal=_SharedJournal(same_state, "court:same"))
    with pytest.raises(InvalidCell, match="distinct authorities"):
        migrate_cell_history(first, second)


def test_migration_rejects_source_changes_without_promoting_partial_copy(
    monkeypatch,
):
    source = CellStore()
    source.commit(0, create=(_leaf("source:first", b"first"),))
    target = CellStore(
        journal=_SharedJournal(_SharedJournalState(), "court:changing-target")
    )
    original = source.revision_changes

    def mutate_after_read(revision):
        changed = original(revision)
        if source.revision == 1:
            source.commit(
                1,
                create=(_leaf("source:concurrent", b"concurrent"),),
            )
        return changed

    monkeypatch.setattr(source, "revision_changes", mutate_after_read)
    with pytest.raises(Conflict, match="source changed"):
        migrate_cell_history(source, target)

    assert source.revision == 2
    assert target.revision == 1
    assert target.read("source:first").atom == b"first"
    assert "source:concurrent" not in target.snapshot().cells


def test_shared_authority_cannot_masquerade_as_a_local_file_backup(tmp_path):
    store = CellStore(
        journal=_SharedJournal(_SharedJournalState(), "court:remote")
    )
    with pytest.raises(InvalidCell, match="provider restore drill"):
        store.backup_to(tmp_path / "not-a-cloud-backup.sqlite3")


def test_runtime_ownership_court_accepts_shared_durable_authority():
    store = CellStore(
        journal=_SharedJournal(_SharedJournalState(), "court:runtime")
    )
    content = b"shared durable runtime owner"
    invocation = CourtInvocation(
        subject_name="court:runtime-owner",
        subject_digest=hashlib.sha256(content).hexdigest(),
        subject_content=content,
        external_parameters={
            "mode": "persistent",
            "databaseIdentity": hashlib.sha256(
                store.authority_identity.encode("utf-8")
            ).hexdigest(),
            "processId": str(os.getpid()),
            "phase": "acquire",
        },
    )

    result = _runtime_ownership_court_runner(store)(invocation)

    assert result.passed is True
    assert all(result.checks.values())
    assert result.details["backend"] == "court-shared"


def test_shared_authority_runtime_fence_denies_live_takeover_then_releases():
    state = _SharedJournalState()
    first = CellStore(journal=_SharedJournal(state, "court:fence"))
    second = CellStore(journal=_SharedJournal(state, "court:fence"))

    release = first.acquire_runtime_fence("app:archhub")
    with pytest.raises(DatabaseOwnerConflict, match="active runtime owner"):
        second.acquire_runtime_fence("app:archhub")

    release()
    second_release = second.acquire_runtime_fence("app:archhub")
    second_release()


def test_application_runtime_attestation_uses_remote_authority_not_local_path():
    store = CellStore(
        journal=_SharedJournal(_SharedJournalState(), "court:attestation")
    )
    server = object.__new__(ApplicationServer)
    server.universal_store = store
    server.universal_registry = SimpleNamespace(application_root="app:archhub")
    server._runtime_holder_root = "app:runtime-holder:court"

    parameters, content = server._runtime_owner_attestation_inputs("acquire")

    assert parameters == {
        "mode": "persistent",
        "databaseIdentity": hashlib.sha256(
            store.authority_identity.encode("utf-8")
        ).hexdigest(),
        "processId": str(os.getpid()),
        "phase": "acquire",
    }
    assert b"court:attestation" not in content


def test_shared_runtime_bootstrap_holds_exact_fence_before_build(monkeypatch):
    prepare = getattr(
        application_server_module,
        "prepare_shared_universal_runtime",
        None,
    )
    assert callable(prepare), "shared runtime bootstrap is not implemented"
    state = _SharedJournalState()
    store = CellStore(journal=_SharedJournal(state, "court:bootstrap"))
    observed = {}
    registry = SimpleNamespace(application_root="app:archhub")

    def build(_map_path, selected_store, **_kwargs):
        observed["store"] = selected_store
        observed["fenced"] = "app:archhub" in state.runtime_fences
        return selected_store, registry

    monkeypatch.setattr(
        application_server_module,
        "build_universal_application",
        build,
    )
    prepared = prepare(
        store,
        map_path="court-map",
        key_provider=object(),
    )

    assert observed == {"store": store, "fenced": True}
    assert prepared.store is store
    assert prepared.registry is registry
    assert "app:archhub" in state.runtime_fences
    prepared.close()
    assert not state.runtime_fences


def test_runtime_fence_lease_is_exactly_bound_and_single_use():
    lease_type = getattr(
        universal_cell_module,
        "RuntimeFenceLease",
        None,
    )
    assert lease_type is not None, "runtime fence lease is not implemented"
    state = _SharedJournalState()
    store = CellStore(journal=_SharedJournal(state, "court:lease"))
    other = CellStore(journal=_SharedJournal(state, "court:lease"))
    lease = store.prepare_runtime_fence("app:archhub")

    with pytest.raises(InvalidCell, match="CellStore"):
        lease.consume(other, "app:archhub")
    with pytest.raises(InvalidCell, match="resource"):
        lease.consume(store, "app:other")

    release = lease.consume(store, "app:archhub")
    with pytest.raises(InvalidCell, match="consumed"):
        lease.consume(store, "app:archhub")
    release()
    assert not state.runtime_fences


def test_shared_runtime_bootstrap_failure_releases_fence(monkeypatch):
    prepare = getattr(
        application_server_module,
        "prepare_shared_universal_runtime",
        None,
    )
    assert callable(prepare), "shared runtime bootstrap is not implemented"
    state = _SharedJournalState()
    journal = _SharedJournal(state, "court:failed-bootstrap")
    store = CellStore(journal=journal)

    def fail(*_args, **_kwargs):
        assert "app:archhub" in state.runtime_fences
        raise RuntimeError("injected build failure")

    monkeypatch.setattr(
        application_server_module,
        "build_universal_application",
        fail,
    )
    with pytest.raises(RuntimeError, match="injected build failure"):
        prepare(
            store,
            map_path="court-map",
            key_provider=object(),
        )

    assert not state.runtime_fences
    assert journal.closed is True


def test_server_handoff_consumes_prepared_lease_without_reacquiring():
    state = _SharedJournalState()
    store = CellStore(journal=_SharedJournal(state, "court:server-handoff"))
    lease = store.prepare_runtime_fence("app:archhub")

    release = application_server_module._take_universal_runtime_fence(
        store,
        "app:archhub",
        lease,
    )

    assert state.runtime_fences == {"app:archhub"}
    with pytest.raises(InvalidCell, match="consumed"):
        application_server_module._take_universal_runtime_fence(
            store,
            "app:archhub",
            lease,
        )
    release()
    assert not state.runtime_fences


def test_shared_runtime_restore_holds_the_same_fence(monkeypatch):
    state = _SharedJournalState()
    store = CellStore(journal=_SharedJournal(state, "court:restore"))
    store.commit(0, create=(_leaf("app:archhub", b"application"),))
    observed = {}
    registry = SimpleNamespace(application_root="app:archhub")

    def restore(_map_path, selected_store, **kwargs):
        observed["store"] = selected_store
        observed["fenced"] = "app:archhub" in state.runtime_fences
        observed["key_provider"] = kwargs["key_provider"]
        return selected_store, registry

    monkeypatch.setattr(
        application_server_module,
        "restore_universal_application",
        restore,
    )
    key_provider = object()
    prepared = application_server_module.prepare_shared_universal_runtime(
        store,
        map_path="court-map",
        key_provider=key_provider,
    )

    assert observed == {
        "store": store,
        "fenced": True,
        "key_provider": key_provider,
    }
    prepared.close()
    assert not state.runtime_fences


def test_application_server_rejects_unprepared_shared_authority():
    state = _SharedJournalState()
    store = CellStore(journal=_SharedJournal(state, "court:unprepared"))
    try:
        with pytest.raises(
            ValueError,
            match="requires a prepared runtime fence",
        ):
            ApplicationServer(
                universal_store=store,
                universal_registry=SimpleNamespace(
                    application_root="app:archhub"
                ),
            )
    finally:
        store.close()

    assert not state.runtime_fences
