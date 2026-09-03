"""Adversarial court for graph-held relation cardinality contracts."""
import inspect

import pytest

import nodelang.cell_relation_contract as relation_contract_module
from nodelang.cell_protocols import build_relation
from nodelang.cell_relation_contract import (
    bootstrap_relation_contract_protocol,
    build_relation_contract,
    build_role_constraint,
    compose_validated_relation,
    open_relation_contract_protocol,
    read_relation_contract,
    release_relation_contract,
    resolve_relation_contract_authority,
    validate_relation,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
    Snapshot,
)


BUDGET = 20_000


def _terminal(cell_id, atom=b""):
    return Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _base_graph():
    store = CellStore()
    protocol = bootstrap_relation_contract_protocol(store)
    store.commit(store.revision, create=(
        _terminal("role:alpha", b"alpha"),
        _terminal("role:beta", b"beta"),
        _terminal("role:optional", b"optional"),
        _terminal("role:unknown", b"unknown"),
        _terminal("participant:a", b"a"),
        _terminal("participant:b", b"b"),
        _terminal("participant:fixed", b"fixed"),
        _terminal("participant:short", b"four"),
        _terminal("participant:long", b"five!"),
    ))
    return store, protocol


def _constraint(
    store,
    protocol,
    constraint_id,
    role,
    minimum,
    maximum,
    *,
    fixed=None,
    atom_maximum=None,
    require_exists=True,
):
    return build_role_constraint(
        store,
        protocol,
        constraint_id=constraint_id,
        participant_role=role,
        minimum=minimum,
        maximum=maximum,
        fixed_participant_root=fixed,
        terminal_atom_maximum=atom_maximum,
        require_participant_exists=require_exists,
        budget=BUDGET,
    )


def _complete_constraints(store, protocol):
    alpha = _constraint(
        store, protocol, "constraint:alpha", "role:alpha", 1, 2
    )
    beta = _constraint(
        store,
        protocol,
        "constraint:beta",
        "role:beta",
        1,
        1,
        fixed="participant:fixed",
    )
    optional = _constraint(
        store,
        protocol,
        "constraint:optional",
        "role:optional",
        0,
        1,
        atom_maximum=4,
        require_exists=False,
    )
    return alpha, beta, optional


def _released_contract(store, protocol, *, contract_id="contract:released"):
    constraints = _complete_constraints(store, protocol)
    contract = build_relation_contract(
        store,
        protocol,
        contract_id=contract_id,
        constraint_roots=(item.root_id for item in constraints),
        released=True,
        budget=BUDGET,
    )
    return contract, constraints


def _valid_target(store, *, relation_id="target:valid", include_optional=False):
    members = [
        ("role:alpha", "participant:a"),
        ("role:alpha", "participant:b"),
        ("role:beta", "participant:fixed"),
    ]
    if include_optional:
        members.append(("role:optional", "participant:short"))
    return build_relation(store, members, relation_id=relation_id)


def test_valid_n_ary_relation_and_absent_or_present_optional_role():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    without_optional = _valid_target(store, relation_id="target:no-optional")
    with_optional = _valid_target(
        store, relation_id="target:with-optional", include_optional=True
    )

    first = validate_relation(
        store.snapshot(),
        protocol,
        contract.root_id,
        without_optional.root_id,
        budget=BUDGET,
    )
    second = validate_relation(
        store.snapshot(),
        protocol,
        contract.root_id,
        with_optional.root_id,
        budget=BUDGET,
    )

    assert first.member_count == 3
    assert first.role_counts["role:optional"] == 0
    assert second.member_count == 4
    assert second.role_counts == {
        "role:alpha": 2,
        "role:beta": 1,
        "role:optional": 1,
    }


def test_candidate_composition_is_validated_without_committing():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    before = store.snapshot()
    candidate = compose_validated_relation(
        before,
        protocol,
        contract.root_id,
        (
            ("role:alpha", "participant:a"),
            ("role:beta", "participant:fixed"),
        ),
        relation_id="target:candidate",
        budget=BUDGET,
    )
    assert store.snapshot() == before
    assert candidate.root_id == "target:candidate"
    assert candidate.validation.member_count == 2
    store.commit(before.revision, create=candidate.cells)
    assert validate_relation(
        store.snapshot(), protocol, contract.root_id, candidate.root_id,
        budget=BUDGET,
    ).role_counts["role:alpha"] == 1


def test_invalid_candidate_leaves_no_partial_relation():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    before = store.snapshot()
    with pytest.raises(InvalidCell, match="wrong fixed participant"):
        compose_validated_relation(
            before,
            protocol,
            contract.root_id,
            (
                ("role:alpha", "participant:a"),
                ("role:beta", "participant:b"),
            ),
            relation_id="target:rejected-candidate",
            budget=BUDGET,
        )
    assert store.snapshot() == before
    assert "target:rejected-candidate" not in store.snapshot().cells


def test_definition_authority_resolution_is_structural_and_fail_closed():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    authority = resolve_relation_contract_authority(
        store.snapshot(),
        capability_roots=(protocol.root_id,),
        rule_roots=(contract.root_id,),
        budget=BUDGET,
    )
    assert authority.protocol.root_id == protocol.root_id
    assert authority.contract.root_id == contract.root_id
    with pytest.raises(InvalidCell, match="exactly one released"):
        resolve_relation_contract_authority(
            store.snapshot(),
            capability_roots=(protocol.root_id,),
            rule_roots=(contract.root_id, contract.root_id),
            budget=BUDGET,
        )


def test_unknown_participant_role_is_rejected():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = build_relation(store, (
        ("role:alpha", "participant:a"),
        ("role:beta", "participant:fixed"),
        ("role:unknown", "participant:b"),
    ), relation_id="target:unknown")

    with pytest.raises(InvalidCell, match="unknown participant role"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_under_cardinality_is_rejected():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = build_relation(store, (
        ("role:beta", "participant:fixed"),
    ), relation_id="target:under")

    with pytest.raises(InvalidCell, match="below minimum cardinality"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_over_cardinality_is_rejected():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = build_relation(store, (
        ("role:alpha", "participant:a"),
        ("role:alpha", "participant:b"),
        ("role:alpha", "participant:a"),
        ("role:beta", "participant:fixed"),
    ), relation_id="target:over")

    with pytest.raises(InvalidCell, match="exceeds maximum cardinality"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_wrong_fixed_participant_root_is_rejected():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = build_relation(store, (
        ("role:alpha", "participant:a"),
        ("role:beta", "participant:b"),
    ), relation_id="target:wrong-fixed")

    with pytest.raises(InvalidCell, match="wrong fixed participant root"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_missing_required_participant_is_rejected():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = build_relation(store, (
        ("role:alpha", NULL_CELL_ID),
        ("role:beta", "participant:fixed"),
    ), relation_id="target:missing")

    with pytest.raises(InvalidCell, match="missing required participant"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )

    valid = build_relation(store, (
        ("role:alpha", "participant:a"),
        ("role:beta", "participant:fixed"),
    ), relation_id="target:dangling")
    corrupted_cells = dict(store.snapshot().cells)
    alpha_incidence = corrupted_cells[valid.incidence_ids[0]]
    corrupted_cells[alpha_incidence.id] = Cell(
        alpha_incidence.id,
        alpha_incidence.link0,
        "participant:absent",
        alpha_incidence.atom,
    )
    corrupted = Snapshot(store.revision, corrupted_cells)
    with pytest.raises(InvalidCell, match="target relation participant is missing"):
        validate_relation(
            corrupted, protocol, contract.root_id, valid.root_id, budget=BUDGET
        )


def test_oversized_terminal_atom_is_rejected():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = build_relation(store, (
        ("role:alpha", "participant:a"),
        ("role:beta", "participant:fixed"),
        ("role:optional", "participant:long"),
    ), relation_id="target:oversized")

    with pytest.raises(InvalidCell, match="terminal atom is oversized"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_duplicate_constraints_for_one_role_are_rejected_before_contract_commit():
    store, protocol = _base_graph()
    first = _constraint(store, protocol, "constraint:first", "role:alpha", 0, 1)
    second = _constraint(store, protocol, "constraint:second", "role:alpha", 1, 2)
    before = store.revision

    with pytest.raises(InvalidCell, match="duplicate role constraints"):
        build_relation_contract(
            store,
            protocol,
            contract_id="contract:duplicate",
            constraint_roots=(first.root_id, second.root_id),
            budget=BUDGET,
        )
    assert store.revision == before


def test_draft_release_and_contract_tamper_protection():
    store, protocol = _base_graph()
    alpha = _constraint(
        store, protocol, "constraint:release-alpha", "role:alpha", 1, 1
    )
    contract = build_relation_contract(
        store,
        protocol,
        contract_id="contract:draft",
        constraint_roots=(alpha.root_id,),
        budget=BUDGET,
    )
    target = build_relation(store, (
        ("role:alpha", "participant:a"),
    ), relation_id="target:release")
    draft = read_relation_contract(
        store.snapshot(), protocol, contract.root_id, budget=BUDGET
    )
    assert draft.lifecycle_root == protocol.state("draft")
    with pytest.raises(InvalidCell, match="draft relation contract"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )

    digest = release_relation_contract(
        store, protocol, contract.root_id, budget=BUDGET
    )
    assert digest == store.read(contract.digest_root).atom
    validate_relation(
        store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
    )

    minimum = store.read(alpha.minimum_root)
    store.commit(store.revision, replace=(Cell(
        minimum.id, minimum.link0, minimum.link1, b"0"
    ),))
    with pytest.raises(InvalidCell, match="contract has been tampered with"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_definition_digest_binding_is_protected():
    store, protocol = _base_graph()
    alpha = _constraint(
        store, protocol, "constraint:bound-alpha", "role:alpha", 1, 1
    )
    definition_digest = _terminal("definition:digest", b"revision-digest")
    store.commit(store.revision, create=(definition_digest,))
    contract = build_relation_contract(
        store,
        protocol,
        contract_id="contract:bound",
        constraint_roots=(alpha.root_id,),
        definition_digest_root=definition_digest.id,
        budget=BUDGET,
    )
    target = build_relation(store, (
        ("role:alpha", "participant:a"),
    ), relation_id="target:bound")

    opened = read_relation_contract(
        store.snapshot(), protocol, contract.root_id, budget=BUDGET
    )
    assert opened.lifecycle_root == protocol.state("definition-bound")
    validate_relation(
        store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
    )

    stored = store.read(definition_digest.id)
    store.commit(store.revision, replace=(Cell(
        stored.id, stored.link0, stored.link1, b"other-revision"
    ),))
    with pytest.raises(InvalidCell, match="contract has been tampered with"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_protocol_tampering_is_rejected_before_target_validation():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = _valid_target(store)
    role = store.read(protocol.role("minimum"))
    store.commit(store.revision, replace=(Cell(
        role.id, role.link0, role.link1, b"changed"
    ),))

    with pytest.raises(InvalidCell, match="protocol"):
        open_relation_contract_protocol(
            store.snapshot(), protocol.root_id, budget=BUDGET
        )
    with pytest.raises(InvalidCell, match="protocol"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=BUDGET
        )


def test_explicit_traversal_budget_exhaustion_is_deterministic():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = _valid_target(store)

    with pytest.raises(MatchBudgetExceeded, match="budget|exceeded"):
        open_relation_contract_protocol(store.snapshot(), protocol.root_id, budget=1)
    with pytest.raises(MatchBudgetExceeded, match="budget|exceeded"):
        validate_relation(
            store.snapshot(), protocol, contract.root_id, target.root_id, budget=1
        )


def test_replica_reopens_from_cells_without_side_table_or_persisted_subclass():
    store, protocol = _base_graph()
    contract, _ = _released_contract(store, protocol)
    target = _valid_target(store, include_optional=True)
    assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())

    replica = CellStore()
    replica.commit(replica.revision, create=tuple(
        cell
        for cell_id, cell in store.snapshot().cells.items()
        if cell_id != NULL_CELL_ID
    ))
    reopened = open_relation_contract_protocol(
        replica.snapshot(), protocol.root_id, budget=BUDGET
    )
    result = validate_relation(
        replica.snapshot(),
        reopened,
        contract.root_id,
        target.root_id,
        budget=BUDGET,
    )
    assert result.member_count == 4
    assert all(type(cell) is Cell for cell in replica.snapshot().cells.values())

    source = inspect.getsource(relation_contract_module).lower()
    for forbidden in ("cognition", "model", "proposal", "product"):
        assert forbidden not in source
