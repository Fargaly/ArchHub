"""Courts for the privacy-bounded BABOOM activity capsule."""
from __future__ import annotations

import pytest

from nodelang.cell_activity import (
    bootstrap_baboom_activity_protocol,
    list_active_baboom_activities,
    renew_baboom_activity,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _store() -> CellStore:
    store = CellStore()
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
