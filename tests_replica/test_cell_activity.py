"""Courts for the privacy-bounded BABOOM activity capsule."""
from __future__ import annotations

import pytest

from nodelang.cell_activity import (
    bootstrap_baboom_activity_protocol,
    ensure_store_baboom_activity_storage,
    list_baboom_activities,
    list_active_baboom_activities,
    renew_baboom_activity,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell
from nodelang.runtime_presence_lease_storage import RuntimePresenceLeaseStorage


@pytest.mark.parametrize("persistent", [False, True])
def test_active_activity_survives_more_than_one_thousand_expired_rows(tmp_path, persistent):
    store = _store(tmp_path / "active.sqlite3" if persistent else None)
    protocol = bootstrap_baboom_activity_protocol(store)
    storage = protocol.activity_storage
    try:
        for i in range(1002):
            storage.record_baboom_activity({
                "activity_root": f"activity:{i:04d}",
                "agent_session_root": f"app:agent-session:runtime:s{i}",
                "device_custody_root": "device-custody:sha256:baboom-court",
                "app": "Revit", "observed_at": 100.0,
                "expires_at": 300.0 if i == 1001 else 150.0,
                "authority_revision": store.revision,
            })
        active = list_active_baboom_activities(store.snapshot(), protocol, now=200.0)
        assert [item.root_id for item in active] == ["activity:1001"]
        with pytest.raises(InvalidCell, match="bound"):
            list_baboom_activities(store.snapshot(), protocol)
        for invalid_limit in (-1, 0, True, 1.5, 10002):
            with pytest.raises(InvalidCell, match="limit"):
                storage.list_baboom_activity_rows(limit=invalid_limit)
            with pytest.raises(InvalidCell, match="limit"):
                storage.list_active_baboom_activity_rows(200.0, limit=invalid_limit)
    finally:
        storage.close()
        store.close()


def test_activity_storage_cannot_replace_instance_owner(tmp_path):
    store = _store(tmp_path / "owner.sqlite3")
    protocol = bootstrap_baboom_activity_protocol(store)
    duplicate = RuntimePresenceLeaseStorage(store.database_path)
    foreign_store = _store(tmp_path / "foreign.sqlite3")
    foreign = RuntimePresenceLeaseStorage(foreign_store.database_path)
    try:
        with pytest.raises(InvalidCell, match="owner"):
            ensure_store_baboom_activity_storage(store, duplicate)
        with pytest.raises(InvalidCell, match="another database"):
            ensure_store_baboom_activity_storage(store, foreign)
        assert store._runtime_presence_lease_storage is protocol.activity_storage
    finally:
        duplicate.close()
        foreign.close()
        protocol.activity_storage.close()
        foreign_store.close()
        store.close()


def _store(database_path=None) -> CellStore:
    store = CellStore(database_path)
    store.commit(
        store.revision,
        create=(
            Cell(
                "app:agent-session:runtime:baboom-court",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"runtime-session",
            ),
            Cell(
                "device-custody:sha256:baboom-court",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"device-custody",
            ),
            Cell(
                "device-custody:sha256:other",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"other-device-custody",
            ),
        ),
    )
    return store


def test_activity_capsule_renews_one_released_app_without_rebinding():
    store = _store()
    protocol = bootstrap_baboom_activity_protocol(store)
    created, revision = renew_baboom_activity(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
        app="Revit",
        now=100.0,
        lease_seconds=90.0,
    )
    assert created.app == "Revit"
    assert revision == store.revision
    assert [item.root_id for item in list_active_baboom_activities(
        store.snapshot(), protocol, now=189.999
    )] == [created.root_id]

    renewed, revision = renew_baboom_activity(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
        app="Codex",
        now=150.0,
        lease_seconds=90.0,
    )
    assert renewed.root_id == created.root_id
    assert renewed.app == "Codex"
    assert renewed.observed_at == 150.0
    assert renewed.expires_at == 240.0
    assert revision == store.revision

    with pytest.raises(InvalidCell, match="binding drifted"):
        renew_baboom_activity(
            store,
            protocol,
            agent_session_root="app:agent-session:runtime:baboom-court",
            device_custody_root="device-custody:sha256:other",
            app="Codex",
            now=151.0,
            lease_seconds=90.0,
        )


def test_activity_capsule_expires_without_cleanup_and_rejects_unknown_app():
    store = _store()
    protocol = bootstrap_baboom_activity_protocol(store)
    _, revision = renew_baboom_activity(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
        app="Rhino",
        now=40.0,
        lease_seconds=15.0,
    )
    assert len(list_active_baboom_activities(
        store.snapshot(), protocol, now=54.999
    )) == 1
    assert list_active_baboom_activities(
        store.snapshot(), protocol, now=55.0
    ) == ()
    assert store.revision == revision

    with pytest.raises(InvalidCell, match="not released"):
        renew_baboom_activity(
            store,
            protocol,
            agent_session_root="app:agent-session:runtime:baboom-court",
            device_custody_root="device-custody:sha256:baboom-court",
            app="Sensitive Client Portal",
            now=60.0,
            lease_seconds=90.0,
        )


@pytest.mark.parametrize("persistent", [False, True])
def test_activity_observations_never_add_graph_revisions(tmp_path, persistent):
    path = tmp_path / "instance.sqlite3" if persistent else None
    store = _store(path)
    protocol = bootstrap_baboom_activity_protocol(store)
    revision = store.revision
    count = len(store.snapshot().cells)
    try:
        for step in range(10):
            activity, returned_revision = renew_baboom_activity(
                store, protocol,
                agent_session_root="app:agent-session:runtime:baboom-court",
                device_custody_root="device-custody:sha256:baboom-court",
                app="Revit" if step % 2 == 0 else "Codex",
                now=100.0 + step, lease_seconds=15.0,
            )
            assert returned_revision == revision == store.revision
            assert len(store.snapshot().cells) == count
        assert activity.app == "Codex"
        assert len(list_active_baboom_activities(store.snapshot(), protocol, now=123.0)) == 1
        assert list_active_baboom_activities(store.snapshot(), protocol, now=124.0) == ()
    finally:
        storage = getattr(protocol, "activity_storage", None)
        if storage is not None:
            storage.close()
        store.close()
