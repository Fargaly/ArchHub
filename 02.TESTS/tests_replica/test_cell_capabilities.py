"""The court that decides whether the RUNNING application can reach any of it."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_secrets import admit_secret, read_secret_reference
from nodelang.cell_capabilities import (
    CAPABILITIES,
    assert_capabilities_present,
    install_capabilities,
    missing_capabilities,
)
from nodelang.cell_session_state import open_session, read_session
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def test_a_bare_graph_can_reach_nothing():
    store = CellStore()
    assert len(missing_capabilities(store.snapshot())) == len(CAPABILITIES)
    with pytest.raises(InvalidCell):
        assert_capabilities_present(store.snapshot())


def test_installing_puts_every_capability_in_the_graph():
    store = CellStore()
    install_capabilities(store)
    assert missing_capabilities(store.snapshot(), include_skills=False) == ()


def test_installing_twice_changes_nothing():
    store = CellStore()
    install_capabilities(store)
    settled = store.snapshot().revision
    install_capabilities(store)
    assert store.snapshot().revision == settled


def test_the_real_application_reaches_every_capability():
    """The one that matters: build the app the founder runs, then look."""
    store, _registry = build_universal_application(resolve_map_path(), CellStore())
    assert_capabilities_present(store.snapshot())


def test_a_capability_is_usable_against_the_application_graph():
    """Present is not enough -- it has to work on the live store."""
    store, _registry = build_universal_application(resolve_map_path(), CellStore())
    admit_secret(
        store, name="anthropic",
        reference="op://archhub/models/anthropic", custody="operator-vault",
    )
    entry = read_secret_reference(store.snapshot(), "anthropic")
    assert entry.reference == "op://archhub/models/anthropic"


def test_a_session_opens_on_the_application_graph():
    store, _registry = build_universal_application(resolve_map_path(), CellStore())
    snapshot = store.snapshot()
    owner = next(iter(snapshot.cells))
    open_session(store, session_root="session:live", owner_root=owner)
    assert read_session(store.snapshot(), "session:live").owner_root == owner
