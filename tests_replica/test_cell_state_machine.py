"""Forcing court for generic graph-held operational state and evidence."""
import inspect

import pytest

from nodelang.cell_state_machine import (
    bootstrap_state_machine_protocol,
    build_evidence,
    build_evidence_admission,
    build_state_machine,
    build_transition,
    machine_history,
    read_evidence_admission,
    read_evidence,
    read_state_machine,
    transition_machine,
    transition_machine_with_new_evidence,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


@pytest.fixture()
def machine():
    store = CellStore()
    protocol = bootstrap_state_machine_protocol(store)
    roots = {
        "state:open": b"Open",
        "state:pending": b"Pending",
        "state:committed": b"Committed",
        "state:aborted": b"Aborted",
        "event:prepare": b"Prepare",
        "event:commit": b"Commit",
        "event:abort": b"Abort",
        "evidence-type:confirmation": b"External confirmation",
        "actor:member": b"Member",
        "issuer:adapter": b"Allowlisted adapter",
    }
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in roots.items()
    ))
    prepare = build_transition(
        store, protocol, transition_id="transition:prepare",
        from_state_root="state:open", to_state_root="state:pending",
        event_root="event:prepare",
    )
    commit = build_transition(
        store, protocol, transition_id="transition:commit",
        from_state_root="state:pending", to_state_root="state:committed",
        event_root="event:commit",
        required_evidence_type_roots=("evidence-type:confirmation",),
    )
    abort = build_transition(
        store, protocol, transition_id="transition:abort",
        from_state_root="state:pending", to_state_root="state:aborted",
        event_root="event:abort",
    )
    root = build_state_machine(
        store,
        protocol,
        machine_id="machine:test",
        state_roots=(
            "state:open", "state:pending", "state:committed", "state:aborted",
        ),
        transition_roots=(prepare, commit, abort),
        initial_state_root="state:open",
    )
    return store, protocol, root


def test_state_change_and_history_event_are_one_atomic_revision(machine):
    store, protocol, root = machine
    before = store.revision
    event_root, revision = transition_machine(
        store, protocol, root,
        event_root="event:prepare", expected_state_root="state:open",
        actor_root="actor:member",
    )
    assert revision == before + 1
    state = read_state_machine(store.snapshot(), protocol, root)
    assert state.current_state_root == "state:pending"
    history = machine_history(store.snapshot(), protocol, root)
    assert [event.root_id for event in history] == [event_root]
    assert history[0].from_state_root == "state:open"
    assert history[0].to_state_root == "state:pending"
    assert history[0].actor_root == "actor:member"
    assert history[0].timestamp_root
    assert history[0].evidence_roots == ()
    assert history[0].context_roots == ()


def test_transition_records_explicit_session_context_and_rejects_missing_context(
    machine,
):
    store, protocol, root = machine
    before = store.revision
    with pytest.raises(InvalidCell, match="context"):
        transition_machine(
            store,
            protocol,
            root,
            event_root="event:prepare",
            expected_state_root="state:open",
            actor_root="actor:member",
            context_roots=("session:missing",),
        )
    assert store.revision == before

    store.commit(store.revision, create=(
        Cell("session:one", NULL_CELL_ID, NULL_CELL_ID, b"Session one"),
    ))
    transition_machine(
        store,
        protocol,
        root,
        event_root="event:prepare",
        expected_state_root="state:open",
        actor_root="actor:member",
        context_roots=("session:one",),
    )
    assert machine_history(
        store.snapshot(), protocol, root
    )[-1].context_roots == ("session:one",)


def test_evidence_required_transition_rejects_missing_and_accepts_verified(machine):
    store, protocol, root = machine
    transition_machine(
        store, protocol, root,
        event_root="event:prepare", expected_state_root="state:open",
        actor_root="actor:member",
    )
    with pytest.raises(InvalidCell, match="evidence"):
        transition_machine(
            store, protocol, root,
            event_root="event:commit", expected_state_root="state:pending",
            actor_root="actor:member",
        )
    evidence = build_evidence(
        store,
        protocol,
        evidence_id="evidence:confirmation:1",
        evidence_type_root="evidence-type:confirmation",
        payload=b'{"provider":"confirmed"}',
        issuer_root="issuer:adapter",
    )
    projected = read_evidence(store.snapshot(), protocol, evidence)
    assert projected.payload == b'{"provider":"confirmed"}'
    transition_machine(
        store, protocol, root,
        event_root="event:commit", expected_state_root="state:pending",
        actor_root="actor:member", evidence_roots=(evidence,),
        trusted_issuer_roots=("issuer:adapter",),
    )
    assert read_state_machine(
        store.snapshot(), protocol, root
    ).current_state_root == "state:committed"
    assert machine_history(
        store.snapshot(), protocol, root
    )[-1].evidence_roots == (evidence,)


def test_stale_state_impossible_transition_and_ambiguous_rule_are_rejected(machine):
    store, protocol, root = machine
    transition_machine(
        store, protocol, root,
        event_root="event:prepare", expected_state_root="state:open",
        actor_root="actor:member",
    )
    with pytest.raises(InvalidCell, match="stale"):
        transition_machine(
            store, protocol, root,
            event_root="event:abort", expected_state_root="state:open",
            actor_root="actor:member",
        )
    with pytest.raises(InvalidCell, match="not admitted"):
        transition_machine(
            store, protocol, root,
            event_root="event:prepare", expected_state_root="state:pending",
            actor_root="actor:member",
        )
    duplicate = build_transition(
        store, protocol, transition_id="transition:abort:duplicate",
        from_state_root="state:pending", to_state_root="state:open",
        event_root="event:abort",
    )
    state = read_state_machine(store.snapshot(), protocol, root)
    incidence = store.read(state.root_id)
    # A machine is immutable in shape through the public API; build a second
    # malformed machine to prove ambiguous graph declarations fail closed.
    assert incidence.id == root
    malformed = build_state_machine(
        store,
        protocol,
        machine_id="machine:ambiguous",
        state_roots=state.state_roots,
        transition_roots=(*state.transition_roots, duplicate),
        initial_state_root="state:pending",
    )
    with pytest.raises(InvalidCell, match="ambiguous"):
        transition_machine(
            store, protocol, malformed,
            event_root="event:abort", expected_state_root="state:pending",
            actor_root="actor:member",
        )


def test_evidence_content_digest_detects_tampering(machine):
    store, protocol, _ = machine
    evidence = build_evidence(
        store,
        protocol,
        evidence_id="evidence:tamper",
        evidence_type_root="evidence-type:confirmation",
        payload=b"confirmed",
        issuer_root="issuer:adapter",
    )
    projected = read_evidence(store.snapshot(), protocol, evidence)
    payload = store.read(projected.payload_root)
    store.commit(store.revision, replace=(Cell(
        payload.id, payload.link0, payload.link1, b"forged",
    ),))
    with pytest.raises(InvalidCell, match="digest"):
        read_evidence(store.snapshot(), protocol, evidence)


def test_integrity_checked_but_untrusted_evidence_cannot_cross_gate(machine):
    store, protocol, root = machine
    transition_machine(
        store, protocol, root,
        event_root="event:prepare", expected_state_root="state:open",
        actor_root="actor:member",
    )
    evidence = build_evidence(
        store,
        protocol,
        evidence_id="evidence:untrusted",
        evidence_type_root="evidence-type:confirmation",
        payload=b"confirmed",
        issuer_root="actor:member",
    )
    with pytest.raises(InvalidCell, match="issuer is not trusted"):
        transition_machine(
            store, protocol, root,
            event_root="event:commit", expected_state_root="state:pending",
            actor_root="actor:member", evidence_roots=(evidence,),
            trusted_issuer_roots=("issuer:adapter",),
        )


def test_graph_evidence_admission_binds_type_to_one_issuer():
    store = CellStore()
    protocol = bootstrap_state_machine_protocol(store)
    roots = {
        "state:pending": b"Pending",
        "state:committed": b"Committed",
        "event:commit": b"Commit",
        "evidence-type:review": b"Review record",
        "issuer:reviewer": b"Named reviewer",
        "issuer:other": b"Other allowlisted issuer",
        "actor:member": b"Member",
    }
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in roots.items()
    ))
    admission = build_evidence_admission(
        store,
        protocol,
        admission_id="admission:reviewer-review",
        evidence_type_root="evidence-type:review",
        issuer_root="issuer:reviewer",
    )
    assert read_evidence_admission(
        store.snapshot(), protocol, admission
    ).issuer_root == "issuer:reviewer"
    transition = build_transition(
        store,
        protocol,
        transition_id="transition:commit",
        from_state_root="state:pending",
        to_state_root="state:committed",
        event_root="event:commit",
        required_evidence_admission_roots=(admission,),
    )
    machine = build_state_machine(
        store,
        protocol,
        machine_id="machine:admitted-evidence",
        state_roots=("state:pending", "state:committed"),
        transition_roots=(transition,),
        initial_state_root="state:pending",
    )
    wrong_issuer = build_evidence(
        store,
        protocol,
        evidence_id="evidence:other-review",
        evidence_type_root="evidence-type:review",
        payload=b"reviewed",
        issuer_root="issuer:other",
    )
    with pytest.raises(InvalidCell, match="declared admissions"):
        transition_machine(
            store,
            protocol,
            machine,
            event_root="event:commit",
            expected_state_root="state:pending",
            actor_root="actor:member",
            evidence_roots=(wrong_issuer,),
            trusted_issuer_roots=("issuer:reviewer", "issuer:other"),
        )
    approved_issuer = build_evidence(
        store,
        protocol,
        evidence_id="evidence:reviewer-review",
        evidence_type_root="evidence-type:review",
        payload=b"reviewed",
        issuer_root="issuer:reviewer",
    )
    transition_machine(
        store,
        protocol,
        machine,
        event_root="event:commit",
        expected_state_root="state:pending",
        actor_root="actor:member",
        evidence_roots=(approved_issuer,),
        trusted_issuer_roots=("issuer:reviewer", "issuer:other"),
    )
    assert read_state_machine(
        store.snapshot(), protocol, machine
    ).current_state_root == "state:committed"


def test_transition_rejects_mixed_legacy_and_graph_evidence_requirements(machine):
    store, protocol, _ = machine
    admission = build_evidence_admission(
        store,
        protocol,
        admission_id="admission:confirmation",
        evidence_type_root="evidence-type:confirmation",
        issuer_root="issuer:adapter",
    )
    with pytest.raises(InvalidCell, match="cannot mix"):
        build_transition(
            store,
            protocol,
            transition_id="transition:mixed-evidence",
            from_state_root="state:open",
            to_state_root="state:pending",
            event_root="event:prepare",
            required_evidence_type_roots=("evidence-type:confirmation",),
            required_evidence_admission_roots=(admission,),
        )


def test_new_evidence_and_transition_share_one_atomic_revision(machine):
    store, protocol, root = machine
    transition_machine(
        store, protocol, root,
        event_root="event:prepare", expected_state_root="state:open",
        actor_root="actor:member",
    )
    before = store.revision
    with pytest.raises(InvalidCell, match="issuer is not trusted"):
        transition_machine_with_new_evidence(
            store,
            protocol,
            root,
            event_root="event:commit",
            expected_state_root="state:pending",
            actor_root="actor:member",
            evidence_id="evidence:atomic:denied",
            evidence_type_root="evidence-type:confirmation",
            evidence_payload=b"denied",
            evidence_issuer_root="actor:member",
            trusted_issuer_roots=("issuer:adapter",),
        )
    assert store.revision == before
    assert "evidence:atomic:denied" not in store.snapshot().cells

    evidence, event, revision = transition_machine_with_new_evidence(
        store,
        protocol,
        root,
        event_root="event:commit",
        expected_state_root="state:pending",
        actor_root="actor:member",
        evidence_id="evidence:atomic:accepted",
        evidence_type_root="evidence-type:confirmation",
        evidence_payload=b'{"provider":"confirmed"}',
        evidence_issuer_root="issuer:adapter",
        trusted_issuer_roots=("issuer:adapter",),
    )
    assert revision == before + 1
    assert read_evidence(store.snapshot(), protocol, evidence).payload == (
        b'{"provider":"confirmed"}'
    )
    history = machine_history(store.snapshot(), protocol, root)
    assert history[-1].root_id == event
    assert history[-1].evidence_roots == (evidence,)
    assert read_state_machine(
        store.snapshot(), protocol, root
    ).current_state_root == "state:committed"


def test_operational_floor_has_no_product_or_domain_dispatch():
    source = inspect.getsource(transition_machine).lower()
    for forbidden in (
        '"payment"', '"database"', '"geometry"', '"bim"', '"knowledge"',
    ):
        assert forbidden not in source
