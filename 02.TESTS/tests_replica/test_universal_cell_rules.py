"""Rule protocol court: behavior selection and bindings are graph cells."""
from nodelang.cell_protocols import read_relation, rewire_incidence
from nodelang.cell_rules import (
    bootstrap_rule_protocol,
    build_rule,
    execute_rule,
    project_rule_protocol,
    rule_content_digest,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _rule_graph():
    return [
        Cell("p-left", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("p-right", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("p-pair", "p-left", "p-right", b"pair"),
        Cell("r-left", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("r-right", NULL_CELL_ID, NULL_CELL_ID, b""),
        Cell("r-pair", "r-right", "r-left", b"pair"),
    ]


def _target(prefix):
    return [
        Cell(prefix + "-a", NULL_CELL_ID, NULL_CELL_ID, b"A"),
        Cell(prefix + "-b", NULL_CELL_ID, NULL_CELL_ID, b"B"),
        Cell(prefix, prefix + "-a", prefix + "-b", b"pair"),
    ]


def test_rule_node_contains_pattern_replacement_variables_and_bindings():
    store = CellStore()
    store.commit(store.revision, create=_rule_graph())
    protocol = bootstrap_rule_protocol(store)
    rule = build_rule(
        store,
        protocol,
        rule_id="swap-rule",
        pattern_root="p-pair",
        replacement_root="r-pair",
        pattern_variables=("p-left", "p-right"),
        replacement_bindings={"r-left": "p-left", "r-right": "p-right"},
    )
    members = read_relation(store.snapshot(), rule.root_id, budget=32)
    assert {member.role_id for member in members} == {
        protocol.pattern_role,
        protocol.replacement_role,
        protocol.pattern_variable_role,
        protocol.binding_role,
    }
    assert len(rule.binding_roots) == 2


def test_rule_protocol_reconstructs_from_persisted_graph_root(tmp_path):
    path = tmp_path / "rule-protocol.sqlite3"
    store = CellStore(path)
    protocol = bootstrap_rule_protocol(store)
    root_id = protocol.root_id
    store.close()

    reopened = CellStore(path)
    restored = project_rule_protocol(reopened.snapshot(), root_id)
    assert restored == protocol
    reopened.close()


def test_execute_needs_only_rule_root_target_root_and_protocol_graph():
    store = CellStore()
    store.commit(store.revision, create=_rule_graph() + _target("target"))
    protocol = bootstrap_rule_protocol(store)
    rule = build_rule(
        store,
        protocol,
        rule_id="swap-rule",
        pattern_root="p-pair",
        replacement_root="r-pair",
        pattern_variables=("p-left", "p-right"),
        replacement_bindings={"r-left": "p-left", "r-right": "p-right"},
    )
    execute_rule(store, protocol, rule.root_id, "target", budget=128)
    assert store.read("target").link0 == "target-b"
    assert store.read("target").link1 == "target-a"


def test_rewiring_binding_nodes_changes_rule_behavior_without_engine_edit():
    store = CellStore()
    store.commit(
        store.revision,
        create=_rule_graph() + _target("target1") + _target("target2"),
    )
    protocol = bootstrap_rule_protocol(store)
    rule = build_rule(
        store,
        protocol,
        rule_id="swap-rule",
        pattern_root="p-pair",
        replacement_root="r-pair",
        pattern_variables=("p-left", "p-right"),
        replacement_bindings={"r-left": "p-left", "r-right": "p-right"},
    )
    execute_rule(store, protocol, rule.root_id, "target1", budget=128)
    assert store.read("target1").link0 == "target1-b"

    for binding_root in rule.binding_roots:
        members = read_relation(store.snapshot(), binding_root, budget=16)
        replacement = next(
            member for member in members
            if member.role_id == protocol.replacement_variable_role
        )
        pattern = next(
            member for member in members
            if member.role_id == protocol.pattern_variable_role
        )
        desired = "p-right" if replacement.participant_id == "r-left" else "p-left"
        rewire_incidence(store, pattern.incidence_id, desired)

    execute_rule(store, protocol, rule.root_id, "target2", budget=128)
    assert store.read("target2").link0 == "target2-a"
    assert store.read("target2").link1 == "target2-b"


def test_rule_constant_binding_preserves_an_existing_graph_identity():
    store = CellStore()
    store.commit(store.revision, create=_rule_graph() + _target("target1") + _target("target2") + [
        Cell("constant-c", NULL_CELL_ID, NULL_CELL_ID, b"C"),
        Cell("constant-d", NULL_CELL_ID, NULL_CELL_ID, b"D"),
    ])
    protocol = bootstrap_rule_protocol(store)
    rule = build_rule(
        store,
        protocol,
        rule_id="constant-rule",
        pattern_root="p-pair",
        replacement_root="r-pair",
        pattern_variables=("p-left", "p-right"),
        replacement_bindings={"r-right": "p-right"},
        replacement_constants={"r-left": "constant-c"},
    )
    execute_rule(store, protocol, rule.root_id, "target1", budget=128)
    assert store.read("target1").link0 == "target1-b"
    assert store.read("target1").link1 == "constant-c"

    binding = next(
        root for root in rule.binding_roots
        if any(
            member.role_id == protocol.constant_role
            for member in read_relation(store.snapshot(), root, budget=16)
        )
    )
    constant_member = next(
        member for member in read_relation(store.snapshot(), binding, budget=16)
        if member.role_id == protocol.constant_role
    )
    rewire_incidence(store, constant_member.incidence_id, "constant-d")
    execute_rule(store, protocol, rule.root_id, "target2", budget=128)
    assert store.read("target2").link1 == "constant-d"


def test_rule_digest_tracks_behavior_but_not_constant_target_content():
    store = CellStore()
    store.commit(store.revision, create=_rule_graph() + [
        Cell("constant", NULL_CELL_ID, NULL_CELL_ID, b"C"),
    ])
    protocol = bootstrap_rule_protocol(store)
    rule = build_rule(
        store,
        protocol,
        rule_id="digest-rule",
        pattern_root="p-pair",
        replacement_root="r-pair",
        pattern_variables=("p-left", "p-right"),
        replacement_bindings={"r-right": "p-right"},
        replacement_constants={"r-left": "constant"},
    )
    first = rule_content_digest(store.snapshot(), protocol, rule.root_id)

    constant = store.read("constant")
    store.commit(store.revision, replace=(Cell(
        constant.id, constant.link0, constant.link1, b"changed ordinary content"
    ),))
    assert rule_content_digest(store.snapshot(), protocol, rule.root_id) == first

    replacement = store.read("r-pair")
    store.commit(store.revision, replace=(Cell(
        replacement.id,
        replacement.link0,
        replacement.link1,
        b"changed behavior",
    ),))
    assert rule_content_digest(store.snapshot(), protocol, rule.root_id) != first
