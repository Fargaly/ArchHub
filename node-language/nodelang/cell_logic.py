"""Bounded graph-held relational logic over the Universal Cell floor.

The interpreter knows only variables, constants, predicates, clauses, rules,
and externally supplied primitive facts.  Product and authorization meaning is
carried by graph identities and graph-held rules, never by Python dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections import deque
from typing import Callable, Iterable, Iterator, Mapping

from .cell_protocols import RelationMember, read_relation
from .universal_cell import InvalidCell, Snapshot


@dataclass(frozen=True, slots=True)
class LogicProtocol:
    conforms_to_role: str
    rule_role: str
    head_role: str
    body_role: str
    predicate_role: str
    argument_role: str
    variable_role: str
    constant_role: str
    term_shape: str
    clause_shape: str
    rule_shape: str
    relation_member_predicate: str
    bound_predicate: str


@dataclass(frozen=True, slots=True)
class LogicTerm:
    root_id: str
    variable_root: str | None
    constant_root: str | None


@dataclass(frozen=True, slots=True)
class LogicClause:
    root_id: str
    predicate_root: str
    terms: tuple[LogicTerm, ...]


@dataclass(frozen=True, slots=True)
class LogicRule:
    root_id: str
    head: LogicClause
    body: tuple[LogicClause, ...]


@dataclass(frozen=True, slots=True)
class PrimitiveFact:
    """One primitive fact and the exact graph roots read to establish it."""

    root_id: str
    arguments: tuple[str, ...]
    evidence_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicProofStep:
    rule_root: str
    bindings: Mapping[str, str]
    evidence_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicProof:
    top_rule_root: str
    bindings: Mapping[str, str]
    steps: tuple[LogicProofStep, ...]
    read_roots: tuple[str, ...]


PrimitiveFactProvider = Callable[
    [str, tuple[str | None, ...], int], Iterable[PrimitiveFact]
]


def _for_role(
    members: tuple[RelationMember, ...], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _single(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("logic %s requires exactly one participant" % label)
    return values[0]


def _validate_shape(
    members: tuple[RelationMember, ...], protocol: LogicProtocol, expected: str
) -> None:
    if _single(members, protocol.conforms_to_role, "shape") != expected:
        raise InvalidCell("logic composition has the wrong structural protocol")


def read_logic_term(
    snapshot: Snapshot,
    protocol: LogicProtocol,
    root_id: str,
    *,
    budget: int = 10_000,
) -> LogicTerm:
    members = read_relation(snapshot, root_id, budget=budget)
    _validate_shape(members, protocol, protocol.term_shape)
    admitted = {
        protocol.conforms_to_role,
        protocol.variable_role,
        protocol.constant_role,
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("logic term contains an undeclared role")
    variables = _for_role(members, protocol.variable_role)
    constants = _for_role(members, protocol.constant_role)
    if len(variables) + len(constants) != 1:
        raise InvalidCell("logic term requires one variable or constant")
    return LogicTerm(
        root_id,
        variables[0] if variables else None,
        constants[0] if constants else None,
    )


def read_logic_clause(
    snapshot: Snapshot,
    protocol: LogicProtocol,
    root_id: str,
    *,
    budget: int = 10_000,
) -> LogicClause:
    members = read_relation(snapshot, root_id, budget=budget)
    _validate_shape(members, protocol, protocol.clause_shape)
    admitted = {
        protocol.conforms_to_role,
        protocol.predicate_role,
        protocol.argument_role,
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("logic clause contains an undeclared role")
    predicate = _single(members, protocol.predicate_role, "predicate")
    terms = tuple(
        read_logic_term(snapshot, protocol, root, budget=budget)
        for root in _for_role(members, protocol.argument_role)
    )
    return LogicClause(root_id, predicate, terms)


def read_logic_rule(
    snapshot: Snapshot,
    protocol: LogicProtocol,
    root_id: str,
    *,
    budget: int = 10_000,
) -> LogicRule:
    members = read_relation(snapshot, root_id, budget=budget)
    _validate_shape(members, protocol, protocol.rule_shape)
    admitted = {
        protocol.conforms_to_role,
        protocol.head_role,
        protocol.body_role,
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("logic rule contains an undeclared role")
    head = read_logic_clause(
        snapshot,
        protocol,
        _single(members, protocol.head_role, "head"),
        budget=budget,
    )
    body = tuple(
        read_logic_clause(snapshot, protocol, root, budget=budget)
        for root in _for_role(members, protocol.body_role)
    )
    return LogicRule(root_id, head, body)


_Variable = tuple[int, str]
_Value = str | _Variable


def _is_variable(value: _Value) -> bool:
    return isinstance(value, tuple)


def _deref(value: _Value, bindings: Mapping[_Variable, _Value]) -> _Value:
    seen: set[_Variable] = set()
    while _is_variable(value) and value in bindings:
        if value in seen:
            raise InvalidCell("logic variable binding contains a cycle")
        seen.add(value)
        value = bindings[value]
    return value


def _unify(
    left: _Value,
    right: _Value,
    bindings: Mapping[_Variable, _Value],
) -> dict[_Variable, _Value] | None:
    result = dict(bindings)
    left = _deref(left, result)
    right = _deref(right, result)
    if left == right:
        return result
    if _is_variable(left):
        result[left] = right
        return result
    if _is_variable(right):
        result[right] = left
        return result
    return None


def _term_value(term: LogicTerm, frame: int) -> _Value:
    if term.variable_root is not None:
        return (frame, term.variable_root)
    if term.constant_root is None:
        raise InvalidCell("logic term has no value")
    return term.constant_root


# The most goals ONE transitive edge expansion may burn before it is
# refused as pathological. Ordinary edge rules cost ~30 goals; this is
# a backstop, not a tuning knob.
_EDGE_EXPANSION_CEILING = 10_000


@dataclass(slots=True)
class _Meter:
    remaining: int
    next_frame: int = 1

    def spend(self) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            raise InvalidCell("logic evaluation exceeded its budget")

    def frame(self) -> int:
        value = self.next_frame
        self.next_frame += 1
        return value


@dataclass(frozen=True, slots=True)
class _Trace:
    bindings: Mapping[_Variable, _Value]
    steps: tuple[tuple[int, str, tuple[str, ...]], ...]
    read_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TransitiveClosurePlan:
    edge_predicate: str
    direct_rule: LogicRule
    recursive_rule: LogicRule
    identity_rule: LogicRule | None


def _transitive_closure_plan(
    predicate_root: str,
    rules: tuple[LogicRule, ...],
) -> _TransitiveClosurePlan | None:
    """Recognize a graph-declared reflexive/transitive binary relation."""

    def variables(terms: tuple[LogicTerm, ...]) -> tuple[str, ...] | None:
        roots = tuple(term.variable_root for term in terms)
        if any(root is None for root in roots):
            return None
        return tuple(root for root in roots if root is not None)

    identity: LogicRule | None = None
    direct: LogicRule | None = None
    recursive: LogicRule | None = None
    edge_predicate: str | None = None
    for rule in rules:
        head = variables(rule.head.terms)
        if head is None or len(head) != 2:
            return None
        if not rule.body:
            if head[0] != head[1] or identity is not None:
                return None
            identity = rule
            continue
        if len(rule.body) == 1:
            edge = rule.body[0]
            edge_terms = variables(edge.terms)
            if (
                edge.predicate_root == predicate_root
                or edge_terms != head
                or direct is not None
            ):
                return None
            direct = rule
            edge_predicate = edge.predicate_root
            continue
        if len(rule.body) == 2:
            edge, tail = rule.body
            edge_terms = variables(edge.terms)
            tail_terms = variables(tail.terms)
            if (
                edge.predicate_root == predicate_root
                or tail.predicate_root != predicate_root
                or edge_terms is None
                or tail_terms is None
                or len(edge_terms) != 2
                or len(tail_terms) != 2
                or edge_terms[0] != head[0]
                or tail_terms[0] != edge_terms[1]
                or tail_terms[1] != head[1]
                or recursive is not None
            ):
                return None
            recursive = rule
            if edge_predicate is not None and edge_predicate != edge.predicate_root:
                return None
            edge_predicate = edge.predicate_root
            continue
        return None
    if direct is None or recursive is None or edge_predicate is None:
        return None
    return _TransitiveClosurePlan(
        edge_predicate,
        direct,
        recursive,
        identity,
    )


# Reachability over a transitive-closure predicate is a pure function of
# (snapshot, edge predicate, source): a snapshot is immutable and the edge
# rule is graph-held. The solver re-derived that set through unification on
# every closure query -- hundreds of queries per boot, each walking the same
# edges. The memo HOLDS the mapping it keys on (an id is stable only while
# its object lives) and is bounded to a few snapshots. It records ONLY the
# reachable set discovered by the solver's own walk; a target outside the
# set is answered without a walk (the walk would yield nothing), a target
# inside walks exactly as before and yields the same trace.
_CLOSURE_REACH_MEMO: dict[int, tuple[object, dict]] = {}


def _reach_memo_for(snapshot: Snapshot) -> dict:
    key = id(snapshot.cells)
    held = _CLOSURE_REACH_MEMO.get(key)
    if held is None or held[0] is not snapshot.cells:
        if len(_CLOSURE_REACH_MEMO) >= 4:
            _CLOSURE_REACH_MEMO.pop(next(iter(_CLOSURE_REACH_MEMO)))
        held = (snapshot.cells, {})
        _CLOSURE_REACH_MEMO[key] = held
    return held[1]


def evaluate_logic(
    snapshot: Snapshot,
    protocol: LogicProtocol,
    program_root: str,
    *,
    predicate_root: str,
    arguments: tuple[str, ...],
    primitive_facts: PrimitiveFactProvider,
    budget: int = 100_000,
    max_proofs: int = 2,
) -> tuple[LogicProof, ...]:
    """Evaluate one fully grounded query and return canonical top-rule proofs."""
    if not arguments or any(type(value) is not str for value in arguments):
        raise InvalidCell("logic query arguments must be grounded identities")
    if budget < 1 or max_proofs < 1:
        raise InvalidCell("logic evaluation bounds are invalid")
    program_members = read_relation(snapshot, program_root, budget=budget)
    rule_roots = _for_role(program_members, protocol.rule_role)
    if not rule_roots or len(rule_roots) != len(set(rule_roots)):
        raise InvalidCell("logic program requires unique graph-held rules")
    rules = tuple(
        read_logic_rule(snapshot, protocol, root, budget=budget)
        for root in rule_roots
    )
    by_predicate: dict[str, tuple[LogicRule, ...]] = {}
    for predicate in {rule.head.predicate_root for rule in rules}:
        by_predicate[predicate] = tuple(
            rule for rule in rules if rule.head.predicate_root == predicate
        )
    closure_plans = {
        predicate: plan
        for predicate, predicate_rules in by_predicate.items()
        if (plan := _transitive_closure_plan(predicate, predicate_rules))
        is not None
    }
    meter = _Meter(budget)
    failed_ground_goals: set[tuple[str, tuple[str | None, ...]]] = set()

    def resolved(
        values: tuple[_Value, ...], bindings: Mapping[_Variable, _Value]
    ) -> tuple[str | None, ...]:
        output: list[str | None] = []
        for value in values:
            value = _deref(value, bindings)
            output.append(None if _is_variable(value) else value)
        return tuple(output)

    def solve_body(
        clauses: tuple[LogicClause, ...],
        frame: int,
        trace: _Trace,
        stack: frozenset[tuple[str, tuple[str | None, ...]]],
    ) -> Iterator[_Trace]:
        if not clauses:
            yield trace
            return
        clause = clauses[0]
        goal = tuple(_term_value(term, frame) for term in clause.terms)
        for solved in solve_goal(
            clause.predicate_root, goal, trace, stack
        ):
            yield from solve_body(clauses[1:], frame, solved, stack)

    def bind_rule_step(
        trace: _Trace,
        rule: LogicRule,
        head_values: tuple[str, ...],
        body_values: tuple[tuple[str, ...], ...],
    ) -> _Trace:
        meter.spend()
        frame = meter.frame()
        bindings: Mapping[_Variable, _Value] | None = trace.bindings
        for term, value in zip(rule.head.terms, head_values):
            bindings = _unify(_term_value(term, frame), value, bindings)
            if bindings is None:
                raise InvalidCell("transitive rule head does not match its plan")
        if len(body_values) != len(rule.body):
            raise InvalidCell("transitive rule body does not match its plan")
        for clause, values in zip(rule.body, body_values):
            if len(values) != len(clause.terms):
                raise InvalidCell("transitive rule clause does not match its plan")
            for term, value in zip(clause.terms, values):
                bindings = _unify(_term_value(term, frame), value, bindings)
                if bindings is None:
                    raise InvalidCell(
                        "transitive rule binding does not match its plan"
                    )
        return _Trace(
            MappingProxyType(dict(bindings)),
            (*trace.steps, (frame, rule.root_id, ())),
            tuple(dict.fromkeys((*trace.read_roots, rule.root_id))),
        )

    def closure_trace(
        trace: _Trace,
        plan: _TransitiveClosurePlan,
        path: tuple[str, ...],
    ) -> _Trace:
        if len(path) == 1:
            if plan.identity_rule is None:
                raise InvalidCell("transitive identity rule is missing")
            return bind_rule_step(
                trace,
                plan.identity_rule,
                (path[0], path[0]),
                (),
            )
        result = bind_rule_step(
            trace,
            plan.direct_rule,
            (path[-2], path[-1]),
            ((path[-2], path[-1]),),
        )
        for index in range(len(path) - 3, -1, -1):
            result = bind_rule_step(
                result,
                plan.recursive_rule,
                (path[index], path[-1]),
                (
                    (path[index], path[index + 1]),
                    (path[index + 1], path[-1]),
                ),
            )
        return result

    edge_memo = _reach_memo_for(snapshot)

    def edge_children(plan: _TransitiveClosurePlan, node: str) -> tuple[str, ...]:
        """The nodes one edge away from `node`, in solver order.

        A memo over the snapshot: the edge rule is graph-held and the
        snapshot immutable, so this tuple is a fact of the pair. The
        expansion runs the solver itself once per (edge, node) -- the
        exact goal the walk would run -- and only the CHILDREN are kept.
        Traces are never memoized: they are re-derived along the found
        path by the same goal, so the yielded proof is byte-identical to
        an unmemoized walk.
        """
        key = (plan.edge_predicate, node)
        held = edge_memo.get(key)
        if held is not None:
            return held
        variable = (meter.frame(), "transitive-edge-child")
        children: list[str] = []
        # One frontier node costs the caller ONE step. The inner solve
        # that finds its children is real work, but billing every inner
        # goal made the budget a function of the RULE BODY SIZE times
        # the region: a 1,482-node containment sweep spent 48,305 goals
        # and one 2026-08-19 publish batch pushed one scope past
        # the ceiling -- the live canvas served no interactions. The
        # walk is bounded by the graph by construction; the budget now
        # bounds the FRONTIER, and a separate per-expansion ceiling
        # still refuses a pathological edge rule.
        before = meter.remaining
        for solved in solve_goal(
            plan.edge_predicate, (node, variable),
            _Trace(MappingProxyType({}), (), ()), frozenset()
        ):
            child = _deref(variable, solved.bindings)
            if _is_variable(child):
                raise InvalidCell("transitive edge left its result unbound")
            children.append(child)
        inner_spend = before - meter.remaining
        if inner_spend > _EDGE_EXPANSION_CEILING:
            raise InvalidCell("transitive edge rule exceeded its budget")
        meter.remaining = before - 1
        if meter.remaining < 0:
            raise InvalidCell("logic evaluation exceeded its budget")
        held = tuple(children)
        edge_memo[key] = held
        return held

    def solve_transitive(
        plan: _TransitiveClosurePlan,
        source: str,
        target: str,
        trace: _Trace,
        stack: frozenset[tuple[str, tuple[str | None, ...]]],
    ) -> Iterator[_Trace]:
        if source == target and plan.identity_rule is not None:
            yield closure_trace(trace, plan, (source,))
            return
        # Find the path over memoized edges (cheap), then re-derive the
        # traces along exactly that path with the real goals (bounded by
        # path length, not by the frontier).
        parents: dict[str, str] = {source: source}
        pending = deque((source,))
        found_path: tuple[str, ...] | None = None
        while pending and found_path is None:
            current = pending.popleft()
            for child in edge_children(plan, current):
                if child in parents:
                    continue
                parents[child] = current
                if child == target:
                    chain = [child]
                    while chain[-1] != source:
                        chain.append(parents[chain[-1]])
                    found_path = tuple(reversed(chain))
                    break
                pending.append(child)
        if found_path is None:
            return
        current_trace = trace
        for index in range(len(found_path) - 1):
            step_from, step_to = found_path[index], found_path[index + 1]
            variable = (meter.frame(), "transitive-edge-result")
            advanced = None
            for solved in solve_goal(
                plan.edge_predicate, (step_from, variable), current_trace, stack
            ):
                child = _deref(variable, solved.bindings)
                if child == step_to:
                    advanced = solved
                    break
            if advanced is None:
                raise InvalidCell("transitive edge vanished between walk and proof")
            current_trace = advanced
        yield closure_trace(current_trace, plan, found_path)

    def solve_goal(
        predicate: str,
        goal: tuple[_Value, ...],
        trace: _Trace,
        stack: frozenset[tuple[str, tuple[str | None, ...]]],
    ) -> Iterator[_Trace]:
        meter.spend()
        signature = (predicate, resolved(goal, trace.bindings))
        if signature in stack:
            return
        grounded = all(value is not None for value in signature[1])
        if grounded and signature in failed_ground_goals:
            return
        next_stack = stack | {signature}
        yielded = False
        closure = closure_plans.get(predicate)
        if (
            closure is not None
            and predicate != predicate_root
            and grounded
            and len(signature[1]) == 2
        ):
            source, target = signature[1]
            if source is None or target is None:
                raise InvalidCell("grounded transitive query lost an argument")
            for solved in solve_transitive(
                closure,
                source,
                target,
                trace,
                next_stack,
            ):
                yielded = True
                yield solved
            if not yielded:
                failed_ground_goals.add(signature)
            return
        fact_pattern = signature[1]
        facts = tuple(primitive_facts(predicate, fact_pattern, meter.remaining))
        for fact in facts:
            meter.spend()
            if len(fact.arguments) != len(goal):
                raise InvalidCell("primitive fact arity does not match its query")
            bindings: Mapping[_Variable, _Value] | None = trace.bindings
            for term, value in zip(goal, fact.arguments):
                bindings = _unify(term, value, bindings)
                if bindings is None:
                    break
            if bindings is None:
                continue
            yielded = True
            yield _Trace(
                MappingProxyType(dict(bindings)),
                trace.steps,
                tuple(dict.fromkeys((*trace.read_roots, *fact.evidence_roots))),
            )
        for rule in by_predicate.get(predicate, ()):
            meter.spend()
            if len(rule.head.terms) != len(goal):
                continue
            frame = meter.frame()
            bindings = trace.bindings
            for term, value in zip(rule.head.terms, goal):
                bindings = _unify(_term_value(term, frame), value, bindings)
                if bindings is None:
                    break
            if bindings is None:
                continue
            entered = _Trace(
                MappingProxyType(dict(bindings)),
                trace.steps,
                tuple(dict.fromkeys((*trace.read_roots, rule.root_id))),
            )
            for solved in solve_body(rule.body, frame, entered, next_stack):
                yielded = True
                yield _Trace(
                    solved.bindings,
                    (*solved.steps, (frame, rule.root_id, ())),
                    solved.read_roots,
                )
        if grounded and not yielded:
            failed_ground_goals.add(signature)

    proofs: list[LogicProof] = []
    top_rules = by_predicate.get(predicate_root, ())
    for top_rule in top_rules:
        initial = _Trace(MappingProxyType({}), (), ())
        selected: _Trace | None = None
        # Restrict this branch to the selected top rule without changing the
        # graph-held program seen by all recursive goals.
        original = by_predicate[predicate_root]
        by_predicate[predicate_root] = (top_rule,)
        try:
            selected = next(
                solve_goal(predicate_root, tuple(arguments), initial, frozenset()),
                None,
            )
        finally:
            by_predicate[predicate_root] = original
        if selected is None:
            continue
        top_frame = next(
            (
                frame
                for frame, rule_root, _evidence in selected.steps
                if rule_root == top_rule.root_id
            ),
            None,
        )
        if top_frame is None:
            raise InvalidCell("logic proof omitted its top rule step")
        top_bindings: dict[str, str] = {}
        for term in (*top_rule.head.terms, *(term for clause in top_rule.body for term in clause.terms)):
            if term.variable_root is None:
                continue
            value = _deref((top_frame, term.variable_root), selected.bindings)
            if not _is_variable(value):
                top_bindings[term.variable_root] = value
        steps: list[LogicProofStep] = []
        for frame, rule_root, evidence in selected.steps:
            rule = next(rule for rule in rules if rule.root_id == rule_root)
            step_bindings: dict[str, str] = {}
            for term in (*rule.head.terms, *(term for clause in rule.body for term in clause.terms)):
                if term.variable_root is None:
                    continue
                value = _deref((frame, term.variable_root), selected.bindings)
                if not _is_variable(value):
                    step_bindings[term.variable_root] = value
            steps.append(LogicProofStep(
                rule_root,
                MappingProxyType(dict(sorted(step_bindings.items()))),
                (),
            ))
        proofs.append(LogicProof(
            top_rule.root_id,
            MappingProxyType(dict(sorted(top_bindings.items()))),
            tuple(steps),
            tuple(sorted(set(selected.read_roots))),
        ))
        if len(proofs) >= max_proofs:
            break
    return tuple(proofs)


__all__ = [
    "LogicProtocol",
    "LogicTerm",
    "LogicClause",
    "LogicRule",
    "PrimitiveFact",
    "LogicProofStep",
    "LogicProof",
    "PrimitiveFactProvider",
    "read_logic_term",
    "read_logic_clause",
    "read_logic_rule",
    "evaluate_logic",
]
