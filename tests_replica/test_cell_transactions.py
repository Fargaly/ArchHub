"""Courts for graph-declared, multi-root, all-or-nothing rewrite sets."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodelang.cell_protocols import read_relation, rewire_incidence
from nodelang.cell_rules import bootstrap_rule_protocol, build_rule
from nodelang.cell_transactions import (
    bootstrap_transaction_protocol,
    build_transaction,
    execute_transaction,
    project_transaction_protocol,
    read_transaction,
    transaction_content_digest,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    NoMatch,
)


ROOT = Path(__file__).resolve().parents[1]


def _terminal(root_id: str, atom: bytes = b"") -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _fixture(*, invalid_second: bool = False):
    store = CellStore()
    store.commit(store.revision, create=(
        _terminal("pattern:current"),
        _terminal("pattern:desired"),
        Cell("pattern:state", "pattern:current", "pattern:desired", b"state"),
        _terminal("activate:left"),
        _terminal("activate:right"),
        Cell("activate:state", "activate:left", "activate:right", b"state"),
        _terminal("retain:left"),
        _terminal("retain:right"),
        Cell("retain:state", "retain:left", "retain:right", b"state"),
    ))
    rule_protocol = bootstrap_rule_protocol(
        store, prefix="transaction-test:rule-protocol"
    )
    activate = build_rule(
        store,
        rule_protocol,
        rule_id="transaction-test:rule:activate",
        pattern_root="pattern:state",
        replacement_root="activate:state",
        pattern_variables=("pattern:current", "pattern:desired"),
        replacement_bindings={
            "activate:left": "pattern:desired",
            "activate:right": "pattern:desired",
        },
    ).root_id
    retain = build_rule(
        store,
        rule_protocol,
        rule_id="transaction-test:rule:retain",
        pattern_root="pattern:state",
        replacement_root="retain:state",
        pattern_variables=("pattern:current", "pattern:desired"),
        replacement_bindings={
            "retain:left": "pattern:current",
            "retain:right": "pattern:desired",
        },
    ).root_id
    store.commit(store.revision, create=(
        _terminal("state:a:current", b"A current"),
        _terminal("state:a:desired", b"A desired"),
        Cell("state:a", "state:a:current", "state:a:desired", b"state"),
        _terminal("state:b:current", b"B current"),
        _terminal("state:b:desired", b"B desired"),
        Cell(
            "state:b",
            "state:b:current",
            "state:b:desired",
            b"not-state" if invalid_second else b"state",
        ),
        _terminal("transaction-test:evidence", b"court evidence"),
        _terminal("transaction-test:outcome", b"both active"),
    ))
    transaction_protocol = bootstrap_transaction_protocol(
        store, prefix="transaction-test:protocol"
    )
    transaction = build_transaction(
        store,
        transaction_protocol,
        transaction_id="transaction-test:set",
        steps=((activate, "state:a"), (activate, "state:b")),
        evidence_roots=("transaction-test:evidence",),
        outcome_roots=("transaction-test:outcome",),
    ).root_id
    return store, rule_protocol, transaction_protocol, transaction, activate, retain


def test_two_rewrites_publish_as_one_revision_and_one_commit_event():
    store, rules, protocol, transaction, _activate, _retain = _fixture()
    before = store.revision
    events = []
    unsubscribe = store.subscribe(events.append)
    result = execute_transaction(
        store, protocol, rules, transaction, expected_revision=before
    )
    unsubscribe()

    assert result.revision == before + 1
    assert len(events) == 1
    assert events[0].revision == result.revision
    assert store.read("state:a").link0 == store.read("state:a").link1 == (
        "state:a:desired"
    )
    assert store.read("state:b").link0 == store.read("state:b").link1 == (
        "state:b:desired"
    )
    assert {"state:a", "state:b"}.issubset(result.touched_roots)
    assert result.evidence_roots == ("transaction-test:evidence",)
    assert result.outcome_roots == ("transaction-test:outcome",)


def test_failed_second_match_publishes_neither_rewrite():
    store, rules, protocol, transaction, _activate, _retain = _fixture(
        invalid_second=True
    )
    before_revision = store.revision
    before_a = store.read("state:a")
    before_b = store.read("state:b")
    with pytest.raises(NoMatch):
        execute_transaction(
            store, protocol, rules, transaction, expected_revision=before_revision
        )
    assert store.revision == before_revision
    assert store.read("state:a") == before_a
    assert store.read("state:b") == before_b


def test_stale_revision_and_failing_guard_publish_nothing():
    store, rules, protocol, transaction, _activate, _retain = _fixture()
    current = store.revision
    before = (store.read("state:a"), store.read("state:b"))
    with pytest.raises(Conflict):
        execute_transaction(
            store, protocol, rules, transaction, expected_revision=current - 1
        )

    def deny_commit() -> None:
        raise RuntimeError("authority changed")

    with pytest.raises(RuntimeError, match="authority changed"):
        execute_transaction(
            store,
            protocol,
            rules,
            transaction,
            expected_revision=current,
            precommit_guard=deny_commit,
        )
    assert store.revision == current
    assert (store.read("state:a"), store.read("state:b")) == before


def test_transaction_protocol_reconstructs_after_process_restart():
    store, rules, protocol, transaction, _activate, _retain = _fixture()
    restarted = project_transaction_protocol(store.snapshot(), protocol.root_id)
    projected = read_transaction(store.snapshot(), restarted, transaction)
    assert restarted == protocol
    assert tuple(step.target_root for step in projected.steps) == (
        "state:a", "state:b"
    )
    assert transaction_content_digest(
        store.snapshot(), restarted, rules, transaction
    ) == transaction_content_digest(store.snapshot(), protocol, rules, transaction)


def test_rewiring_a_step_changes_behavior_without_executor_code_changes():
    store, rules, protocol, transaction, _activate, retain = _fixture()
    snapshot = store.snapshot()
    projected = read_transaction(snapshot, protocol, transaction)
    first_step = projected.steps[0]
    rule_member = next(
        member
        for member in read_relation(snapshot, first_step.root_id)
        if member.role_id == protocol.role("rule")
    )
    rewire_incidence(store, rule_member.incidence_id, participant_id=retain)

    execute_transaction(store, protocol, rules, transaction)
    assert store.read("state:a").link0 == "state:a:current"
    assert store.read("state:a").link1 == "state:a:desired"
    assert store.read("state:b").link0 == store.read("state:b").link1 == (
        "state:b:desired"
    )


def test_transaction_rejects_duplicate_continuing_roots_before_build():
    store, _rules, protocol, _transaction, activate, _retain = _fixture()
    before = store.revision
    with pytest.raises(InvalidCell, match="repeats a continuing target"):
        build_transaction(
            store,
            protocol,
            transaction_id="transaction-test:duplicate",
            steps=((activate, "state:a"), (activate, "state:a")),
        )
    assert store.revision == before


def test_transaction_interpreter_contains_no_product_dispatch():
    module = ast.parse(
        (ROOT / "nodelang" / "cell_transactions.py").read_text(encoding="utf-8")
    )
    strings = {
        node.value.lower()
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    forbidden = {
        "properties", "panel", "group", "brain", "domain", "publish",
        "catalogue", "selection", "session", "database", "bim",
    }
    assert not any(
        term == value or term in value.split()
        for term in forbidden for value in strings
    )
