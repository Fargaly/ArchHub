from __future__ import annotations

from pathlib import Path
import uuid

import pytest

from nodelang.cell_logic import (
    LogicProtocol,
    PrimitiveFact,
    evaluate_logic,
    read_logic_term,
)
from nodelang.cell_protocols import CellBatch, compose_relation_cells
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
)


def _leaf(batch: CellBatch, label: str) -> str:
    root = "logic-test:%s:%s" % (label, uuid.uuid4())
    batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, label.encode("ascii")))
    return root


def _logic_fixture():
    store = CellStore()
    batch = CellBatch(store)
    roles = {
        name: _leaf(batch, "role-" + name)
        for name in (
            "conforms-to", "rule", "head", "body", "predicate", "argument",
            "variable", "constant",
        )
    }
    shapes = {
        name: _leaf(batch, "shape-" + name)
        for name in ("term", "clause", "rule")
    }
    predicates = {
        name: _leaf(batch, "predicate-" + name)
        for name in ("edge", "reachable", "decision", "bound")
    }
    variables = {name: _leaf(batch, "variable-" + name) for name in "xyz"}
    values = {name: _leaf(batch, "value-" + name) for name in "abc"}
    evidence = {
        "ab": _leaf(batch, "evidence-ab"),
        "bc": _leaf(batch, "evidence-bc"),
        "ba": _leaf(batch, "evidence-ba"),
    }

    def term(variable: str) -> str:
        return batch.relation((
            (roles["conforms-to"], shapes["term"]),
            (roles["variable"], variables[variable]),
        )).root_id

    def clause(predicate: str, terms: tuple[str, ...]) -> str:
        return batch.relation((
            (roles["conforms-to"], shapes["clause"]),
            (roles["predicate"], predicates[predicate]),
            *((roles["argument"], term(variable)) for variable in terms),
        )).root_id

    def rule(head: str, body: tuple[str, ...]) -> str:
        return batch.relation((
            (roles["conforms-to"], shapes["rule"]),
            (roles["head"], head),
            *((roles["body"], item) for item in body),
        )).root_id

    direct = rule(
        clause("reachable", ("x", "y")),
        (clause("edge", ("x", "y")),),
    )
    recursive = rule(
        clause("reachable", ("x", "y")),
        (
            clause("edge", ("x", "z")),
            clause("reachable", ("z", "y")),
        ),
    )
    decision = rule(
        clause("decision", ("x", "y")),
        (clause("reachable", ("x", "y")),),
    )
    program = batch.relation((
        (roles["rule"], decision),
        (roles["rule"], direct),
        (roles["rule"], recursive),
    )).root_id
    batch.commit()
    protocol = LogicProtocol(
        roles["conforms-to"],
        roles["rule"],
        roles["head"],
        roles["body"],
        roles["predicate"],
        roles["argument"],
        roles["variable"],
        roles["constant"],
        shapes["term"],
        shapes["clause"],
        shapes["rule"],
        predicates["edge"],
        predicates["bound"],
    )
    return store, protocol, program, roles, shapes, predicates, variables, values, evidence, (decision, direct, recursive)


def _facts(predicate, arguments, _budget, *, expected_predicate, rows):
    if predicate != expected_predicate:
        return ()
    return tuple(
        PrimitiveFact(evidence, values, (evidence,))
        for evidence, values in rows
        if len(arguments) == len(values)
        and all(expected is None or expected == actual for expected, actual in zip(arguments, values))
    )


def test_graph_rules_prove_recursive_composition_with_exact_bindings_and_reads():
    store, protocol, program, _roles, _shapes, predicates, variables, values, evidence, rules = _logic_fixture()
    rows = (
        (evidence["ab"], (values["a"], values["b"])),
        (evidence["bc"], (values["b"], values["c"])),
    )
    proofs = evaluate_logic(
        store.snapshot(),
        protocol,
        program,
        predicate_root=predicates["decision"],
        arguments=(values["a"], values["c"]),
        primitive_facts=lambda predicate, arguments, budget: _facts(
            predicate,
            arguments,
            budget,
            expected_predicate=predicates["edge"],
            rows=rows,
        ),
        budget=10_000,
    )

    assert len(proofs) == 1
    proof = proofs[0]
    assert proof.top_rule_root == rules[0]
    assert proof.bindings[variables["x"]] == values["a"]
    assert proof.bindings[variables["y"]] == values["c"]
    assert {step.rule_root for step in proof.steps} == set(rules)
    assert set(rules).issubset(proof.read_roots)
    assert {evidence["ab"], evidence["bc"]}.issubset(proof.read_roots)


def test_recursive_cycle_terminates_and_small_budget_fails_closed():
    store, protocol, program, _roles, _shapes, predicates, _variables, values, evidence, _rules = _logic_fixture()
    cycle_rows = (
        (evidence["ab"], (values["a"], values["b"])),
        (evidence["ba"], (values["b"], values["a"])),
    )
    provider = lambda predicate, arguments, budget: _facts(
        predicate,
        arguments,
        budget,
        expected_predicate=predicates["edge"],
        rows=cycle_rows,
    )

    assert evaluate_logic(
        store.snapshot(),
        protocol,
        program,
        predicate_root=predicates["decision"],
        arguments=(values["a"], values["c"]),
        primitive_facts=provider,
        budget=10_000,
    ) == ()
    with pytest.raises((InvalidCell, MatchBudgetExceeded), match="budget|exceeded"):
        evaluate_logic(
            store.snapshot(),
            protocol,
            program,
            predicate_root=predicates["decision"],
            arguments=(values["a"], values["c"]),
            primitive_facts=provider,
            budget=1,
        )


def test_transitive_rule_uses_bounded_goal_directed_tabling():
    (
        store,
        protocol,
        program,
        _roles,
        _shapes,
        predicates,
        _variables,
        values,
        evidence,
        _rules,
    ) = _logic_fixture()
    deep = tuple("logic-test:deep:%04d" % index for index in range(2_000))
    rows = (
        (evidence["ab"], (values["a"], deep[0])),
        (evidence["ab"], (values["a"], values["b"])),
        *((evidence["ab"], pair) for pair in zip(deep, deep[1:])),
        (evidence["bc"], (values["b"], values["c"])),
    )
    proofs = evaluate_logic(
        store.snapshot(),
        protocol,
        program,
        predicate_root=predicates["decision"],
        arguments=(values["a"], values["c"]),
        primitive_facts=lambda predicate, arguments, budget: _facts(
            predicate,
            arguments,
            budget,
            expected_predicate=predicates["edge"],
            rows=rows,
        ),
        budget=300,
    )

    assert len(proofs) == 1
    assert {evidence["ab"], evidence["bc"]}.issubset(proofs[0].read_roots)


def test_duplicate_program_rule_and_malformed_term_fail_closed():
    store, protocol, program, roles, shapes, predicates, variables, values, _evidence, rules = _logic_fixture()
    duplicate = compose_relation_cells((
        (roles["rule"], rules[0]),
        (roles["rule"], rules[0]),
        (roles["rule"], rules[1]),
        (roles["rule"], rules[2]),
    ))
    store.commit(store.revision, create=duplicate.cells)
    with pytest.raises(InvalidCell, match="unique graph-held rules"):
        evaluate_logic(
            store.snapshot(),
            protocol,
            duplicate.build.root_id,
            predicate_root=predicates["decision"],
            arguments=(values["a"], values["c"]),
            primitive_facts=lambda *_args: (),
        )

    malformed = compose_relation_cells((
        (roles["conforms-to"], shapes["term"]),
        (roles["variable"], variables["x"]),
        (roles["constant"], values["a"]),
    ))
    store.commit(store.revision, create=malformed.cells)
    with pytest.raises(InvalidCell, match="one variable or constant"):
        read_logic_term(store.snapshot(), protocol, malformed.build.root_id)


def test_logic_interpreter_contains_no_archhub_product_catalogue():
    source = (Path(__file__).parents[1] / "nodelang" / "cell_logic.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "ArchHub", "Grand Map", "Workshop", "catalogue", "definition",
        "grant", "allow", "deny", "session",
    ):
        assert forbidden not in source


def test_closure_edge_memo_yields_byte_identical_proofs_and_forgets_per_snapshot():
    """SPEC 4.1: a fast path exists only under an equivalence proof.

    The transitive-closure solver memoizes edge EXPANSION per snapshot and
    re-derives traces along the found path. The proof it yields must be
    identical to the cold solver's -- same top rule, same bindings, same
    steps, same read roots -- on first and repeated queries, and a
    different snapshot must not inherit the memo.
    """
    import nodelang.cell_logic as logic

    store, protocol, program, _roles, _shapes, predicates, variables, values, evidence, rules = _logic_fixture()
    rows = (
        (evidence["ab"], (values["a"], values["b"])),
        (evidence["bc"], (values["b"], values["c"])),
    )
    snapshot = store.snapshot()

    def ask():
        return evaluate_logic(
            snapshot,
            protocol,
            program,
            predicate_root=predicates["decision"],
            arguments=(values["a"], values["c"]),
            primitive_facts=lambda predicate, arguments, budget: _facts(
                predicate, arguments, budget,
                expected_predicate=predicates["edge"], rows=rows,
            ),
            budget=10_000,
        )

    logic._CLOSURE_REACH_MEMO.clear()
    cold = ask()                     # populates the memo
    assert logic._CLOSURE_REACH_MEMO, "memo did not populate"
    warm = ask()                     # served from the memo
    assert len(cold) == len(warm) == 1
    for left, right in zip(cold, warm):
        assert left.top_rule_root == right.top_rule_root
        assert dict(left.bindings) == dict(right.bindings)
        assert tuple(left.steps) == tuple(right.steps)
        assert tuple(left.read_roots) == tuple(right.read_roots)

    # A different snapshot object must not be answered by this memo.
    held_key = id(snapshot.cells)
    other = store.snapshot()
    assert other.cells is snapshot.cells or id(other.cells) != held_key
    memo_ids = set(logic._CLOSURE_REACH_MEMO)
    assert held_key in memo_ids
def test_transitive_sweep_is_billed_per_frontier_node_not_per_inner_goal():
    """Proving absence walks the whole frontier; the budget must bound the
    FRONTIER, not the frontier times the edge rule's body size.

    A 1,482-node containment sweep on the live graph spent 48,305 goals and
    one publish batch pushed a scope past the ceiling: the canvas served no
    interactions. With expansion billed as one step per reached node, a
    2,000-node sweep fits inside a budget barely above the frontier size
    and answers "no proof" instead of dying.
    """
    (
        store,
        protocol,
        program,
        _roles,
        _shapes,
        predicates,
        _variables,
        values,
        evidence,
        _rules,
    ) = _logic_fixture()
    deep = tuple("logic-test:deep:%04d" % index for index in range(2_000))
    rows = (
        (evidence["ab"], (values["a"], deep[0])),
        *((evidence["ab"], pair) for pair in zip(deep, deep[1:])),
    )
    proofs = evaluate_logic(
        store.snapshot(),
        protocol,
        program,
        predicate_root=predicates["decision"],
        arguments=(values["a"], values["c"]),
        primitive_facts=lambda predicate, arguments, budget: _facts(
            predicate,
            arguments,
            budget,
            expected_predicate=predicates["edge"],
            rows=rows,
        ),
        budget=2_300,
    )
    assert proofs == ()
