"""Courts for the graph link between a note effect and its consent session."""
from __future__ import annotations

import pytest

from nodelang.cell_baboom_meeting_note_publication import (
    bootstrap_baboom_meeting_note_publication_protocol,
    create_baboom_meeting_note_publication,
    find_baboom_meeting_note_publication,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _store() -> CellStore:
    store = CellStore()
    store.commit(
        store.revision,
        create=(
            Cell(
                "app:baboom-connector-delegation:court",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"delegation",
            ),
            Cell(
                "baboom-meeting-notes:session:court",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"consent",
            ),
        ),
    )
    return store


def test_publication_binding_is_exact_and_carries_no_note_content():
    store = _store()
    protocol = bootstrap_baboom_meeting_note_publication_protocol(store)
    binding = create_baboom_meeting_note_publication(
        store,
        protocol,
        delegation_root="app:baboom-connector-delegation:court",
        meeting_notes_root="baboom-meeting-notes:session:court",
    )
    assert binding.root_id.startswith("app:baboom-meeting-note-publication:binding:")
    assert binding.delegation_root == "app:baboom-connector-delegation:court"
    assert binding.meeting_notes_root == "baboom-meeting-notes:session:court"
    assert find_baboom_meeting_note_publication(
        store.snapshot(), protocol, binding.delegation_root
    ) == binding
    assert b"note text" not in repr(store.snapshot().cells).encode("utf-8")

    with pytest.raises(InvalidCell, match="already bound"):
        create_baboom_meeting_note_publication(
            store,
            protocol,
            delegation_root=binding.delegation_root,
            meeting_notes_root=binding.meeting_notes_root,
        )


def test_publication_binding_rejects_noncanonical_targets():
    store = _store()
    protocol = bootstrap_baboom_meeting_note_publication_protocol(store)
    with pytest.raises(InvalidCell, match="delegation is invalid"):
        create_baboom_meeting_note_publication(
            store,
            protocol,
            delegation_root="court:delegation",
            meeting_notes_root="baboom-meeting-notes:session:court",
        )
