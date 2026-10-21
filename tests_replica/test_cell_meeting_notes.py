"""Courts for BABOOM's graph-held meeting-note consent sessions."""
from __future__ import annotations

import pytest

from nodelang.cell_meeting_notes import (
    bootstrap_baboom_meeting_notes_protocol,
    close_baboom_meeting_notes,
    list_active_baboom_meeting_notes,
    start_baboom_meeting_notes,
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


def test_consent_session_renews_without_meeting_content_or_rebinding():
    store = _store()
    protocol = bootstrap_baboom_meeting_notes_protocol(store)
    created, revision = start_baboom_meeting_notes(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
        now=100.0,
        lease_seconds=3600.0,
    )
    assert created.capture_mode == "founder-supplied"
    assert created.state == "active"
    assert created.opened_at == 100.0
    assert created.expires_at == 3700.0
    assert created.root_id.startswith("baboom-meeting-notes:session:")
    assert revision == store.revision
    assert [item.root_id for item in list_active_baboom_meeting_notes(
        store.snapshot(), protocol, now=3699.999
    )] == [created.root_id]

    renewed, revision = start_baboom_meeting_notes(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
        now=200.0,
        lease_seconds=3600.0,
    )
    assert renewed.root_id == created.root_id
    assert renewed.opened_at == 100.0
    assert renewed.expires_at == 3800.0
    assert revision == store.revision

    with pytest.raises(InvalidCell, match="binding drifted"):
        start_baboom_meeting_notes(
            store,
            protocol,
            agent_session_root="app:agent-session:runtime:baboom-court",
            device_custody_root="device-custody:sha256:other",
            now=201.0,
            lease_seconds=3600.0,
        )


def test_consent_session_closes_without_cleanup_or_raw_note_storage():
    store = _store()
    protocol = bootstrap_baboom_meeting_notes_protocol(store)
    created, _ = start_baboom_meeting_notes(
        store,
        protocol,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
        now=100.0,
        lease_seconds=60.0,
    )
    closed, revision = close_baboom_meeting_notes(
        store,
        protocol,
        session_root=created.root_id,
        agent_session_root="app:agent-session:runtime:baboom-court",
        device_custody_root="device-custody:sha256:baboom-court",
    )
    assert closed.root_id == created.root_id
    assert closed.state == "closed"
    assert list_active_baboom_meeting_notes(
        store.snapshot(), protocol, now=101.0
    ) == ()
    assert store.revision == revision
    assert all(
        b"note" not in cell.atom.lower()
        and b"meeting" not in cell.atom.lower()
        for cell in store.snapshot().cells.values()
        if cell.id.startswith(created.root_id + ":")
    )

    with pytest.raises(InvalidCell, match="not active"):
        close_baboom_meeting_notes(
            store,
            protocol,
            session_root=created.root_id,
            agent_session_root="app:agent-session:runtime:baboom-court",
            device_custody_root="device-custody:sha256:baboom-court",
        )
