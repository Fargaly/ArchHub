"""Prepare graph rules for an explicitly supported source-policy contract.

No mutation, publication, clean-intent mapping or authority activation occurs.
Unsupported conditions refuse compilation rather than becoming weaker rules.
"""
from dataclasses import dataclass
from types import MappingProxyType
import uuid

from .application_policy_binding import CONTEXT_FIELDS
from .cell_authorization import read_authorization_policy, read_authorization_rule, verify_authorization_policy
from .cell_logic import evaluate_logic, PrimitiveFact
from .cell_protocols import compose_relation_cells, read_relation
from .universal_cell import Cell, InvalidCell, NULL_CELL_ID


@dataclass(frozen=True, slots=True)
class CompiledPolicyPlan:
    source_revision: int
    source_policy: str
    source_policy_digest: bytes
    source_protocol: object
    logic_protocol: object
    program_root: str
    decision_predicate: str
    permit_root: str
    forbid_root: str
    cells: tuple[Cell, ...]
    source_rules: object


def prepare_application_policy(snapshot, source_protocol, policy_root, logic, predicates, *, max_cells=50_000):
    """Compile exact principal/action/object-or-selected-scope and input constraints.

    Only the factory's single selected scope is supported as resource lineage.
    The caller must not use this plan for requests with additional ancestors.
    """
    if type(max_cells) is not int or not 1 <= max_cells <= 100_000:
        raise InvalidCell("policy compiler cell budget is invalid")
    if (set(predicates) != set(CONTEXT_FIELDS) or
            len(set(predicates.values())) != len(predicates) or
            any(type(root) is not str or root == NULL_CELL_ID or root not in snapshot.cells
                for root in predicates.values()) or
            logic.relation_member_predicate in predicates.values()):
        raise InvalidCell("policy compiler context predicates are invalid")
    source = read_authorization_policy(snapshot, source_protocol, policy_root)
    if not source.rule_roots or len(source.rule_roots) > 512:
        raise InvalidCell("policy compiler requires one to 512 source rules")
    source = verify_authorization_policy(snapshot, source_protocol, policy_root)
    rules = tuple(read_authorization_rule(snapshot, source_protocol, root) for root in source.rule_roots)
    for rule in rules:
        unsupported = tuple(name for name in ("interface_root", "lifecycle_state_root",
            "operational_state_root", "expires_at_root", "max_invocations_root")
            if getattr(rule, name) is not None)
        if unsupported:
            raise InvalidCell("policy translation requires unsupported conditions: " + ",".join(unsupported))
        if rule.effect_root not in (source_protocol.effects["permit"], source_protocol.effects["forbid"]):
            raise InvalidCell("policy compiler source effect is invalid")
    cells = []

    def add(values):
        cells.extend(values)
        if len(cells) > max_cells:
            raise InvalidCell("policy compilation exceeded its cell budget")

    def leaf(label):
        root = str(uuid.uuid4())
        add((Cell(root, NULL_CELL_ID, NULL_CELL_ID, label.encode("ascii")),))
        return root

    def relation(members):
        built = compose_relation_cells(members, relation_id=str(uuid.uuid4()))
        add(built.cells)
        return built.build.root_id

    def term(root, variable=False):
        return relation(((logic.conforms_to_role, logic.term_shape),
            (logic.variable_role if variable else logic.constant_role, root)))

    def clause(predicate, terms):
        return relation(((logic.conforms_to_role, logic.clause_shape),
            (logic.predicate_role, predicate), *((logic.argument_role, root) for root in terms)))

    decision = leaf("source-policy-decision")
    subject, object_ = leaf("subject-variable"), leaf("object-variable")
    compiled, origins = [], {}
    for source_rule in rules:
        for resource_field in ("object", "scope"):
            head = clause(decision, (term(source_rule.effect_root), term(subject, True),
                term(source_rule.action_root), term(object_, True)))
            body = [clause(predicates["subject"], (term(subject, True),)),
                clause(predicates["object"], (term(object_, True),)),
                clause(predicates["action"], (term(source_rule.action_root),)),
                clause(predicates["principal"], (term(source_rule.principal_root),)),
                clause(predicates[resource_field], (term(source_rule.object_root),))]
            for field in ("tenant", "assurance", "purpose", "classification", "audience"):
                required = getattr(source_rule, field + "_root")
                if required is not None:
                    body.append(clause(predicates[field], (term(required),)))
            if source_rule.subject_relation_root is not None:
                body.append(clause(logic.relation_member_predicate,
                    (term(object_, True), term(source_rule.subject_relation_root), term(subject, True))))
            root = relation(((logic.conforms_to_role, logic.rule_shape),
                (logic.head_role, head), *((logic.body_role, value) for value in body)))
            compiled.append(root)
            origins[root] = source_rule.root_id
    program = relation(tuple((logic.rule_role, root) for root in compiled))
    return CompiledPolicyPlan(snapshot.revision, policy_root, snapshot.cells[source.digest_root].atom, source_protocol, logic,
        program, decision, source_protocol.effects["permit"], source_protocol.effects["forbid"],
        tuple(cells), MappingProxyType(origins))


def evaluate_compiled_policy(snapshot, plan, logic, primitive_facts, *, subject, action, object_root, budget=100_000):
    """Return (allowed, proofs), checking forbids before permits on one context.

    This is a preparation/equivalence evaluator, not clean runtime admission.
    An evaluation exception propagates; it must never become an empty deny set.
    """
    if type(budget) is not int or budget < 2:
        raise InvalidCell("policy evaluation budget is invalid")
    if logic != plan.logic_protocol:
        raise InvalidCell("compiled policy logic selection changed")
    validate = getattr(primitive_facts, "validate", None)
    if not callable(validate):
        raise InvalidCell("compiled policy requires a live context validator")
    validate()
    if any(snapshot.cells.get(cell.id) != cell for cell in plan.cells):
        raise InvalidCell("compiled policy program changed or is missing")
    source = verify_authorization_policy(snapshot, plan.source_protocol, plan.source_policy)
    if snapshot.cells[source.digest_root].atom != plan.source_policy_digest:
        raise InvalidCell("compiled policy source changed")

    def facts(predicate, arguments, remaining):
        if predicate != logic.relation_member_predicate:
            return primitive_facts(predicate, arguments, remaining)
        if len(arguments) != 3 or arguments[0] is None:
            return ()
        relation, role, participant = arguments
        return tuple(PrimitiveFact(member.incidence_id,
            (relation, member.role_id, member.participant_id),
            (relation, member.incidence_id, member.role_id, member.participant_id))
            for member in read_relation(snapshot, relation, budget=remaining, retain_projection=False)
            if (role is None or role == member.role_id) and
               (participant is None or participant == member.participant_id))
    for effect, allowed in ((plan.forbid_root, False), (plan.permit_root, True)):
        validate()
        proofs = evaluate_logic(snapshot, logic, plan.program_root,
            predicate_root=plan.decision_predicate,
            arguments=(effect, subject, action, object_root),
            primitive_facts=facts, budget=budget // 2, max_proofs=1)
        validate()
        if proofs:
            return allowed, proofs
    return False, ()
