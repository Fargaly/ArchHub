"""Courts for graph-held, revocation-aware runtime-presence leases."""
from __future__ import annotations

import pytest

from nodelang.cell_runtime_presence import (
    bootstrap_runtime_presence_protocol,
    list_active_runtime_presences,
    renew_runtime_presence,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _store_with_runtime_roots(session: str, custody: str) -> CellStore:
    store = CellStore()
    store.commit(
        store.revision,
        create=(
            Cell(session, NULL_CELL_ID, NULL_CELL_ID, b"runtime-session"),
            Cell(custody, NULL_CELL_ID, NULL_CELL_ID, b"device-custody"),
            Cell(
                "device-custody:sha256:other",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"other-device-custody",
            ),
        ),
    )
    return store


def test_runtime_presence_lease_renews_without_rebinding_its_identity():
    store = _store_with_runtime_roots(
        "app:agent-session:runtime:one", "device-custody:sha256:one"
    )
    protocol = bootstrap_runtime_presence_protocol(store)

    created, revision = renew_runtime_presence(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:one",
        device_custody_root="device-custody:sha256:one",
        runtime="baboom",
        now=100.0,
        lease_seconds=60.0,
    )
    assert revision == store.revision
    assert [item.root_id for item in list_active_runtime_presences(
        store.snapshot(), protocol, now=159.999
    )] == [created.root_id]

    renewed, revision = renew_runtime_presence(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:one",
        device_custody_root="device-custody:sha256:one",
        runtime="baboom",
        now=150.0,
        lease_seconds=60.0,
    )
    assert renewed.root_id == created.root_id
    assert renewed.issued_at == created.issued_at
    assert renewed.refreshed_at == 150.0
    assert renewed.expires_at == 210.0
    assert revision == store.revision

    with pytest.raises(InvalidCell, match="binding drifted"):
        renew_runtime_presence(
            store,
            protocol,
            agent_session_root="app:agent-session:runtime:one",
            device_custody_root="device-custody:sha256:other",
            runtime="baboom",
            now=151.0,
            lease_seconds=60.0,
        )


def test_runtime_presence_lease_expires_without_a_cleanup_mutation():
    store = _store_with_runtime_roots(
        "app:agent-session:runtime:expired", "device-custody:sha256:expired"
    )
    protocol = bootstrap_runtime_presence_protocol(store)
    created, revision = renew_runtime_presence(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:expired",
        device_custody_root="device-custody:sha256:expired",
        runtime="baboom",
        now=40.0,
        lease_seconds=20.0,
    )

    assert len(list_active_runtime_presences(
        store.snapshot(), protocol, now=59.999
    )) == 1
    assert list_active_runtime_presences(
        store.snapshot(), protocol, now=60.0
    ) == ()
    assert store.revision == revision
    assert created.expires_at == 60.0
