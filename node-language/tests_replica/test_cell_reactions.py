"""Operational court for the standard graph-held Watcher assembly."""
from pathlib import Path
import time

import pytest

from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    compose_catalog_instance,
    instantiate_catalog_definition,
)
from nodelang.cell_protocols import read_relation, rewire_incidence
from nodelang.cell_reactions import (
    ReactionEngine,
    prepare_reaction_instance_registration,
    reaction_events,
    register_reaction_instance,
    set_reaction_enabled,
    wire_instance_source,
)
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _one_participant(snapshot, root, role):
    members = read_relation(snapshot, root, budget=100_000)
    values = [
        member.participant_id for member in members if member.role_id == role
    ]
    assert len(values) == 1
    return values[0]


def _watcher(store, protocol, library, source_root):
    instance = instantiate_catalog_definition(
        store,
        protocol,
        library.catalog_root,
        library.definition_roots[1],
    )
    wire_instance_source(store, protocol, instance.root_id, source_root)
    reaction_root = register_reaction_instance(
        store,
        protocol,
        library.reaction_protocol,
        instance.root_id,
    )[0]
    return instance, reaction_root


def _source(store):
    store.commit(store.revision, create=(
        Cell("source:leaf", NULL_CELL_ID, NULL_CELL_ID, b"one"),
        Cell("source:root", "source:leaf", NULL_CELL_ID, b""),
    ))
    return "source:root"


def _replace_atom(store, root, atom):
    cell = store.read(root)
    store.commit(store.revision, replace=(
        Cell(cell.id, cell.link0, cell.link1, atom),
    ))


def test_reaction_registration_can_share_the_instance_atomic_commit():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    snapshot = store.snapshot()
    composed = compose_catalog_instance(
        snapshot,
        protocol,
        library.catalog_root,
        library.definition_roots[1],
    )

    prepared = prepare_reaction_instance_registration(
        snapshot,
        protocol,
        library.reaction_protocol,
        composed.instance.root_id,
        pending_cells=composed.cells,
    )
    assert store.revision == snapshot.revision
    assert composed.instance.root_id not in store.snapshot().cells
    assert read_relation(
        store.snapshot(), library.reaction_protocol.registry_root, budget=100_000
    ) == ()

    committed = store.commit(
        snapshot.revision,
        create=(*composed.cells, *prepared.create),
        replace=prepared.replace,
    )
    assert committed == snapshot.revision + 1
    registered = read_relation(
        store.snapshot(), library.reaction_protocol.registry_root, budget=100_000
    )
    assert tuple(
        member.participant_id for member in registered
        if member.role_id == library.reaction_protocol.role("reaction-member")
    ) == prepared.roots


def test_watcher_is_operational():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    source = _source(store)
    _, reaction_root = _watcher(store, protocol, library, source)
    engine = ReactionEngine(
        store, protocol, library.reaction_protocol
    )

    assert engine.drain() == 1
    assert reaction_events(
        store.snapshot(), library.reaction_protocol, reaction_root
    ) == ()

    _replace_atom(store, "source:leaf", b"two")
    _replace_atom(store, "source:leaf", b"three")
    _replace_atom(store, "source:leaf", b"four")
    last_source_revision = store.revision
    assert engine.drain() == 1
    events = reaction_events(
        store.snapshot(), library.reaction_protocol, reaction_root
    )
    assert len(events) == 1
    assert events[0].source_root == source
    assert events[0].fingerprint == store.fingerprint(source)
    assert events[0].revision == last_source_revision

    runtime = read_relation(store.snapshot(), reaction_root, budget=100_000)
    status_root = next(
        member.participant_id for member in runtime
        if member.role_id == library.reaction_protocol.role("status-state")
    )
    error_root = next(
        member.participant_id for member in runtime
        if member.role_id == library.reaction_protocol.role("error-state")
    )
    assert store.read(status_root).atom == b"changed"
    assert store.read(error_root).atom == b""


def test_watcher_cancellation_and_replay_are_graph_state():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    source = _source(store)
    _, reaction_root = _watcher(store, protocol, library, source)
    engine = ReactionEngine(store, protocol, library.reaction_protocol)
    engine.drain()

    set_reaction_enabled(
        store, library.reaction_protocol, reaction_root, False
    )
    _replace_atom(store, "source:leaf", b"while-disabled")
    assert engine.drain() == 0
    assert reaction_events(
        store.snapshot(), library.reaction_protocol, reaction_root
    ) == ()

    set_reaction_enabled(
        store, library.reaction_protocol, reaction_root, True
    )
    assert engine.drain() == 1
    assert len(reaction_events(
        store.snapshot(), library.reaction_protocol, reaction_root
    )) == 1


def test_watcher_restarts_from_graph_cursor_not_process_memory(tmp_path: Path):
    database = tmp_path / "reactions.sqlite3"
    store = CellStore(database)
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    source = _source(store)
    _, reaction_root = _watcher(store, protocol, library, source)
    ReactionEngine(store, protocol, library.reaction_protocol).drain()
    store.close()

    reopened = CellStore(database)
    _replace_atom(reopened, "source:leaf", b"after-restart")
    engine = ReactionEngine(reopened, protocol, library.reaction_protocol)
    assert engine.drain() == 1
    events = reaction_events(
        reopened.snapshot(), library.reaction_protocol, reaction_root
    )
    assert len(events) == 1
    assert events[0].fingerprint == reopened.fingerprint(source)
    reopened.close()


def test_self_observing_watcher_is_rejected_disabled_and_auditable():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    placeholder = _source(store)
    _, reaction_root = _watcher(store, protocol, library, placeholder)
    reaction = library.reaction_protocol
    event_log = _one_participant(
        store.snapshot(), reaction_root, reaction.role("event-log")
    )
    # Rewire the public source to the Watcher's own event log.
    runtime = read_relation(store.snapshot(), reaction_root, budget=100_000)
    source_interface = next(
        member.participant_id for member in runtime
        if member.role_id == reaction.role("source-interface")
    )
    interface = read_relation(store.snapshot(), source_interface, budget=100_000)
    target = next(
        member for member in interface
        if member.role_id == protocol.role("interface-target")
    )
    rewire_incidence(store, target.incidence_id, event_log)

    engine = ReactionEngine(store, protocol, reaction)
    assert engine.drain() == 1
    _replace_atom(store, event_log, b"seed-cycle")
    assert engine.drain(max_rounds=3) == 0
    runtime = read_relation(store.snapshot(), reaction_root, budget=100_000)
    enabled = _one_participant(
        store.snapshot(), reaction_root, reaction.role("enabled-state")
    )
    status = _one_participant(
        store.snapshot(), reaction_root, reaction.role("status-state")
    )
    error = _one_participant(
        store.snapshot(), reaction_root, reaction.role("error-state")
    )
    assert enabled == reaction.states["disabled"]
    assert store.read(status).atom == b"error"
    assert b"fingerprint root cannot exclude itself" in store.read(error).atom
    assert reaction_events(store.snapshot(), reaction, reaction_root) == ()


def test_background_worker_runs_without_spawning_a_process_or_window():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, protocol)
    source = _source(store)
    _, reaction_root = _watcher(store, protocol, library, source)
    engine = ReactionEngine(store, protocol, library.reaction_protocol)
    engine.start()
    deadline = time.time() + 3
    while time.time() < deadline:
        runtime = read_relation(store.snapshot(), reaction_root, budget=100_000)
        status = next(
            member.participant_id for member in runtime
            if member.role_id == library.reaction_protocol.role("status-state")
        )
        if store.read(status).atom == b"ready":
            break
        time.sleep(0.01)
    else:
        engine.stop()
        pytest.fail("background reaction baseline did not complete")

    _replace_atom(store, "source:leaf", b"background")
    deadline = time.time() + 3
    while time.time() < deadline:
        if reaction_events(
            store.snapshot(), library.reaction_protocol, reaction_root
        ):
            break
        time.sleep(0.01)
    engine.stop()
    assert len(reaction_events(
        store.snapshot(), library.reaction_protocol, reaction_root
    )) == 1
    assert engine.failures() == ()
