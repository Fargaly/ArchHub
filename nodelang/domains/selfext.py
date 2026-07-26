"""Node-native self-extension, court, installation, and rollback.

The extension is data in the one table, never a hidden plugin registry.  A
proposal opens into editable parameters, requirement leaves, generated generic
node records, court evidence, approval, and reversible effect plans.  External
mutation is available only through the guarded helpers at the bottom: both
re-read the live approval and court nodes, temporarily unfreeze the appropriate
effect, apply it through the audited effect law, and freeze it again.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from ..core import Store
from ..laws_effect import apply_effect


DEFAULT_PROPOSAL = {
    "intent": "Build a reusable node subgraph",
    "target_scope": "10.PRODUCT/13.NODE-LANGUAGE",
    "requested_by": "founder",
    "mode": "plan",
}

DEFAULT_REQUIREMENTS = (
    {
        "id": "one-table",
        "predicate": "every generated component is in the one node table",
        "gate_kind": "assertion",
        "expected": True,
        "status": "open",
    },
    {
        "id": "reversible",
        "predicate": "installation has an explicit rollback plan",
        "gate_kind": "assertion",
        "expected": True,
        "status": "open",
    },
)

DEFAULT_GENERATED = (
    {
        "role": "value",
        "title": "Generated input",
        "primitive": "value",
        "configuration": {"value": None},
    },
    {
        "role": "behavior",
        "title": "Generated behavior",
        "primitive": "merge",
        "configuration": {"fn": "first"},
    },
)

DEFAULT_COURT_EVIDENCE = {
    "impossible_state_passed": False,
    "confidence": 0.0,
    "confidence_threshold": 0.95,
    "spec_tests_passed": False,
    "tail_coverage": 0.0,
    "required_coverage": 1.0,
    "independent_judge": False,
    "juror_diversity": 0.0,
    "required_diversity": 0.5,
    "evidence_present": False,
    "evidence_refs": [],
}

_PROPOSAL_FIELDS = frozenset(DEFAULT_PROPOSAL)
_REQUIREMENT_FIELDS = frozenset(DEFAULT_REQUIREMENTS[0])
_GENERATED_FIELDS = frozenset(DEFAULT_GENERATED[0])
_COURT_FIELDS = frozenset(DEFAULT_COURT_EVIDENCE)


def _exact_fields(record: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    missing = sorted(allowed - set(record))
    unknown = sorted(set(record) - allowed)
    if missing or unknown:
        raise ValueError(
            "%s fields mismatch; missing=%r unknown=%r" % (label, missing, unknown)
        )


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    clean = str(value).strip()
    if not clean and not allow_empty:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _ratio(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise ValueError("%s must be between 0 and 1" % label)
    return number


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "value", "value": value}, actor=actor
    )


def _wire(
    store: Store,
    source: str,
    target: str,
    title: str,
    actor: str,
) -> str:
    return store.relation(
        [
            {
                "role": "source", "direction": "out", "node_id": source,
                "port_id": "value", "cardinality": "one",
            },
            {
                "role": "target", "direction": "in", "node_id": target,
                "port_id": "value", "cardinality": "one",
            },
        ],
        title=title,
        actor=actor,
    )


def _op(
    store: Store,
    title: str,
    floor: Mapping[str, Any],
    sources: Iterable[str],
    inner: list[str],
    relations: list[str],
    actor: str,
) -> str:
    node = store.add("op", title, floor=dict(floor), actor=actor)
    inner.append(node)
    for source in sources:
        relations.append(_wire(store, source, node, "Input to %s" % title, actor))
    return node


def _record_group(
    store: Store,
    title: str,
    record: Mapping[str, Any],
    actor: str,
    *,
    kind: str = "group",
    frozen: bool = False,
) -> tuple[str, str, dict[str, str], list[str]]:
    params = {
        name: _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in record.items()
    }
    inner = list(params.values())
    relations: list[str] = []
    assembled = _op(
        store,
        "Assemble %s" % title,
        {"op": "merge", "fn": "record", "keys": list(record)},
        params.values(),
        inner,
        relations,
        actor,
    )
    group = store.add(
        kind, title, inner=inner, params=params, frozen=frozen, actor=actor
    )
    return group, assembled, params, relations


def _validated_proposal(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _PROPOSAL_FIELDS, "proposal")
    return {
        "intent": _text(record["intent"], "proposal intent"),
        "target_scope": _text(record["target_scope"], "proposal target scope"),
        "requested_by": _text(record["requested_by"], "proposal requester"),
        "mode": _text(record["mode"], "proposal mode"),
    }


def _validated_requirements(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for raw in records:
        record = dict(raw)
        _exact_fields(record, _REQUIREMENT_FIELDS, "requirement")
        out.append({
            "id": _text(record["id"], "requirement id"),
            "predicate": _text(record["predicate"], "requirement predicate"),
            "gate_kind": _text(record["gate_kind"], "requirement gate kind"),
            "expected": record["expected"],
            "status": _text(record["status"], "requirement status"),
        })
    if not out:
        raise ValueError("self-extension needs at least one requirement")
    ids = [item["id"] for item in out]
    if len(ids) != len(set(ids)):
        raise ValueError("requirement ids must be unique")
    return out


def _validated_generated(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for raw in records:
        record = dict(raw)
        _exact_fields(record, _GENERATED_FIELDS, "generated component")
        configuration = record["configuration"]
        if not isinstance(configuration, Mapping):
            raise ValueError("generated component configuration must be a mapping")
        out.append({
            "role": _text(record["role"], "generated role"),
            "title": _text(record["title"], "generated title"),
            "primitive": _text(record["primitive"], "generated primitive"),
            "configuration": dict(configuration),
        })
    if not out:
        raise ValueError("self-extension needs at least one generated component")
    return out


def _validated_evidence(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _COURT_FIELDS, "court evidence")
    refs = record["evidence_refs"]
    if isinstance(refs, (str, bytes)) or not isinstance(refs, Iterable):
        raise ValueError("court evidence refs must be an iterable")
    return {
        "impossible_state_passed": bool(record["impossible_state_passed"]),
        "confidence": _ratio(record["confidence"], "court confidence"),
        "confidence_threshold": _ratio(
            record["confidence_threshold"], "court confidence threshold"
        ),
        "spec_tests_passed": bool(record["spec_tests_passed"]),
        "tail_coverage": _ratio(record["tail_coverage"], "court tail coverage"),
        "required_coverage": _ratio(
            record["required_coverage"], "court required coverage"
        ),
        "independent_judge": bool(record["independent_judge"]),
        "juror_diversity": _ratio(
            record["juror_diversity"], "court juror diversity"
        ),
        "required_diversity": _ratio(
            record["required_diversity"], "court required diversity"
        ),
        "evidence_present": bool(record["evidence_present"]),
        "evidence_refs": [_text(item, "court evidence reference") for item in refs],
    }


def build_self_extension_domain(
    store: Store,
    *,
    proposal: Mapping[str, Any] = DEFAULT_PROPOSAL,
    requirements: Iterable[Mapping[str, Any]] = DEFAULT_REQUIREMENTS,
    generated: Iterable[Mapping[str, Any]] = DEFAULT_GENERATED,
    court_evidence: Mapping[str, Any] = DEFAULT_COURT_EVIDENCE,
    baseline: Any = None,
    actor: str = "self-extension-domain",
) -> dict[str, Any]:
    """Build one inspectable and inert-by-default self-extension graph."""
    proposal_record = _validated_proposal(proposal)
    requirement_records = _validated_requirements(requirements)
    generated_records = _validated_generated(generated)
    evidence_record = _validated_evidence(court_evidence)

    all_relations: list[str] = []
    proposal_group, proposal_record_node, proposal_params, relations = _record_group(
        store, "Extension proposal", proposal_record, actor,
        kind="proposal", frozen=True,
    )
    all_relations.extend(relations)

    requirement_groups: dict[str, str] = {}
    requirement_params: dict[str, dict[str, str]] = {}
    requirement_records_nodes: list[str] = []
    for record in requirement_records:
        group, assembled, params, relations = _record_group(
            store, "Requirement: %s" % record["id"], record, actor
        )
        requirement_groups[record["id"]] = group
        requirement_params[record["id"]] = params
        requirement_records_nodes.append(assembled)
        all_relations.extend(relations)
    requirements_inner = list(requirement_groups.values())
    requirements_list = _op(
        store, "Requirement leaves", {"op": "merge", "fn": "list"},
        requirement_records_nodes, requirements_inner, all_relations, actor,
    )
    requirements_group = store.add(
        "group", "Requirement tree", inner=requirements_inner, actor=actor
    )

    library_query = _param(
        store, "Library search query", proposal_record["intent"], actor
    )
    library_matches = _param(store, "Library matches", [], actor)
    library_no_duplicate = _param(store, "No duplicate capability", True, actor)
    library_record_inner = [library_query, library_matches, library_no_duplicate]
    library_record = _op(
        store, "Library-first search result",
        {"op": "merge", "fn": "record",
         "keys": ["query", "matches", "no_duplicate"]},
        [library_query, library_matches, library_no_duplicate],
        library_record_inner, all_relations, actor,
    )
    library_group = store.add(
        "group", "Library-first search", inner=library_record_inner,
        params={
            "query": library_query,
            "matches": library_matches,
            "no_duplicate": library_no_duplicate,
        },
        actor=actor,
    )

    generated_groups: list[str] = []
    generated_params: list[dict[str, str]] = []
    generated_records_nodes: list[str] = []
    for index, record in enumerate(generated_records):
        group, assembled, params, relations = _record_group(
            store, "Generated component %d: %s" % (index + 1, record["title"]),
            record,
            actor,
        )
        generated_groups.append(group)
        generated_params.append(params)
        generated_records_nodes.append(assembled)
        all_relations.extend(relations)
    generated_inner = list(generated_groups)
    generated_manifest = _op(
        store, "Generated subgraph manifest", {"op": "merge", "fn": "list"},
        generated_records_nodes, generated_inner, all_relations, actor,
    )
    generated_group = store.add(
        "group", "Generated node subgraph", inner=generated_inner, actor=actor
    )

    evidence_group, evidence_record_node, evidence_params, relations = _record_group(
        store, "Court evidence", evidence_record, actor
    )
    all_relations.extend(relations)
    true_node = store.add(
        "value", "True", floor={"op": "value", "value": True}, actor=actor
    )
    empty_node = store.add(
        "value", "Empty", floor={"op": "value", "value": ""}, actor=actor
    )

    court_inner: list[str] = [evidence_group]
    impossible_gate = _op(
        store, "Impossible-state gate",
        {"op": "compare", "cmp": "=="},
        [evidence_params["impossible_state_passed"], true_node],
        court_inner, all_relations, actor,
    )
    confidence_gate = _op(
        store, "Calibrated confidence gate",
        {"op": "compare", "cmp": ">="},
        [evidence_params["confidence"], evidence_params["confidence_threshold"]],
        court_inner, all_relations, actor,
    )
    spec_gate = _op(
        store, "Spec-derived tests gate",
        {"op": "compare", "cmp": "=="},
        [evidence_params["spec_tests_passed"], true_node],
        court_inner, all_relations, actor,
    )
    coverage_gate = _op(
        store, "Tail and coverage gate",
        {"op": "compare", "cmp": ">="},
        [evidence_params["tail_coverage"], evidence_params["required_coverage"]],
        court_inner, all_relations, actor,
    )
    independence_gate = _op(
        store, "Independent judge gate",
        {"op": "compare", "cmp": "=="},
        [evidence_params["independent_judge"], true_node],
        court_inner, all_relations, actor,
    )
    diversity_gate = _op(
        store, "Juror diversity gate",
        {"op": "compare", "cmp": ">="},
        [evidence_params["juror_diversity"], evidence_params["required_diversity"]],
        court_inner, all_relations, actor,
    )
    evidence_gate = _op(
        store, "Evidence is present",
        {"op": "compare", "cmp": "=="},
        [evidence_params["evidence_present"], true_node],
        court_inner, all_relations, actor,
    )
    court_verdict = _op(
        store, "Court verdict",
        {"op": "math", "fn": "*"},
        [impossible_gate, confidence_gate, spec_gate, coverage_gate,
         independence_gate, diversity_gate, evidence_gate,
         library_no_duplicate],
        court_inner, all_relations, actor,
    )
    court_group = store.add(
        "group", "Independent court", inner=court_inner, actor=actor
    )

    approved = _param(store, "Installation approved", False, actor)
    approver = _param(store, "Installation approver", "", actor)
    approved_at = _param(store, "Installation approved at", "", actor)
    approval_inner = [approved, approver, approved_at]
    approved_true = _op(
        store, "Approval is explicit", {"op": "compare", "cmp": "=="},
        [approved, true_node], approval_inner, all_relations, actor,
    )
    approver_present = _op(
        store, "Approver is identified", {"op": "compare", "cmp": "!="},
        [approver, empty_node], approval_inner, all_relations, actor,
    )
    timestamp_present = _op(
        store, "Approval is timestamped", {"op": "compare", "cmp": "!="},
        [approved_at, empty_node], approval_inner, all_relations, actor,
    )
    approval_gate = _op(
        store, "Approval gate", {"op": "math", "fn": "*"},
        [approved_true, approver_present, timestamp_present],
        approval_inner, all_relations, actor,
    )
    approval_group = store.add(
        "group", "Founder approval", inner=approval_inner,
        params={"approved": approved, "approver": approver,
                "approved_at": approved_at}, actor=actor,
    )

    installed = _param(store, "Extension installed", False, actor)
    install_target = _param(
        store, "Installation target", proposal_record["target_scope"], actor
    )
    install_change = _param(
        store, "Installation change",
        {"action": "attach_subgraph", "subgraph": generated_group,
         "manifest": generated_manifest},
        actor,
    )
    install_effect = store.add(
        "op", "Frozen installation effect",
        floor={"op": "effect", "target": proposal_record["target_scope"],
               "change": {"$param": "change"}},
        params={"target": install_target, "change": install_change},
        frozen=True,
        actor=actor,
    )
    installation_group = store.add(
        "group", "Installation plan",
        inner=[install_target, install_change, install_effect],
        params={"target": install_target, "change": install_change},
        actor=actor,
    )
    install_result = store.add(
        "op", "Installation result", floor={"op": "merge", "fn": "list"},
        actor=actor,
    )
    install_relation = store.relation(
        [
            {"role": "source", "direction": "out", "node_id": generated_group,
             "port_id": "candidate", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": install_result,
             "port_id": "result", "cardinality": "one"},
        ],
        title="Approved court-green installation",
        stages=[
            {"role": "approval", "mode": "guard", "node_id": approval_gate},
            {"role": "court", "mode": "guard", "node_id": court_verdict},
            {"role": "installation", "mode": "map", "node_id": installation_group},
        ],
        actor=actor,
    )
    all_relations.append(install_relation)

    rollback_approved = _param(store, "Rollback approved", False, actor)
    rollback_approver = _param(store, "Rollback approver", "", actor)
    rollback_approved_at = _param(store, "Rollback approved at", "", actor)
    rollback_inner = [rollback_approved, rollback_approver, rollback_approved_at]
    rollback_true = _op(
        store, "Rollback approval is explicit",
        {"op": "compare", "cmp": "=="},
        [rollback_approved, true_node], rollback_inner, all_relations, actor,
    )
    rollback_actor_present = _op(
        store, "Rollback approver is identified",
        {"op": "compare", "cmp": "!="},
        [rollback_approver, empty_node], rollback_inner, all_relations, actor,
    )
    rollback_time_present = _op(
        store, "Rollback approval is timestamped",
        {"op": "compare", "cmp": "!="},
        [rollback_approved_at, empty_node], rollback_inner, all_relations, actor,
    )
    installed_gate = _op(
        store, "Extension is installed", {"op": "compare", "cmp": "=="},
        [installed, true_node], rollback_inner, all_relations, actor,
    )
    rollback_gate = _op(
        store, "Rollback approval gate", {"op": "math", "fn": "*"},
        [rollback_true, rollback_actor_present, rollback_time_present,
         installed_gate], rollback_inner, all_relations, actor,
    )
    rollback_approval_group = store.add(
        "group", "Rollback approval", inner=rollback_inner,
        params={"approved": rollback_approved, "approver": rollback_approver,
                "approved_at": rollback_approved_at}, actor=actor,
    )

    rollback_target = _param(
        store, "Rollback target", proposal_record["target_scope"], actor
    )
    rollback_change = _param(
        store, "Rollback change",
        {"action": "restore_baseline", "subgraph": generated_group,
         "baseline": baseline},
        actor,
    )
    rollback_effect = store.add(
        "op", "Frozen rollback effect",
        floor={"op": "effect", "target": proposal_record["target_scope"],
               "change": {"$param": "change"}},
        params={"target": rollback_target, "change": rollback_change},
        frozen=True,
        actor=actor,
    )
    rollback_group = store.add(
        "group", "Rollback plan",
        inner=[rollback_target, rollback_change, rollback_effect],
        params={"target": rollback_target, "change": rollback_change},
        actor=actor,
    )
    rollback_result = store.add(
        "op", "Rollback result", floor={"op": "merge", "fn": "list"},
        actor=actor,
    )
    rollback_relation = store.relation(
        [
            {"role": "source", "direction": "out", "node_id": installation_group,
             "port_id": "installed-change", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": rollback_result,
             "port_id": "rollback-result", "cardinality": "one"},
        ],
        title="Approved court-green rollback",
        stages=[
            {"role": "approval", "mode": "guard", "node_id": rollback_gate},
            {"role": "court", "mode": "guard", "node_id": court_verdict},
            {"role": "rollback", "mode": "map", "node_id": rollback_group},
        ],
        actor=actor,
    )
    all_relations.append(rollback_relation)

    lifecycle_relations = [
        _wire(store, proposal_group, requirements_group,
              "Proposal becomes requirements", actor),
        _wire(store, requirements_group, library_group,
              "Requirements search the library", actor),
        _wire(store, library_group, generated_group,
              "Library result drives composition", actor),
        _wire(store, generated_group, evidence_group,
              "Generated graph requires evidence", actor),
        _wire(store, evidence_group, court_group,
              "Evidence is judged by court", actor),
        _wire(store, installation_group, rollback_group,
              "Installation has an explicit inverse", actor),
    ]
    all_relations.extend(lifecycle_relations)

    session = store.add(
        "session", "Self-Extension Domain",
        inner=[proposal_group, requirements_group, library_group, generated_group,
               evidence_group, court_group, approval_group, installation_group,
               install_result, rollback_approval_group, rollback_group,
               rollback_result] + lifecycle_relations +
              [install_relation, rollback_relation],
        actor=actor,
    )
    return {
        "session": session,
        "proposal": proposal_group,
        "proposal_record": proposal_record_node,
        "proposal_params": proposal_params,
        "requirements": requirements_group,
        "requirements_list": requirements_list,
        "requirement_groups": requirement_groups,
        "requirement_params": requirement_params,
        "library": library_group,
        "library_record": library_record,
        "library_params": {
            "query": library_query, "matches": library_matches,
            "no_duplicate": library_no_duplicate,
        },
        "generated": generated_group,
        "generated_manifest": generated_manifest,
        "generated_groups": generated_groups,
        "generated_params": generated_params,
        "evidence": evidence_group,
        "evidence_record": evidence_record_node,
        "evidence_params": evidence_params,
        "court": court_group,
        "court_gates": {
            "impossible_state": impossible_gate,
            "confidence": confidence_gate,
            "spec_tests": spec_gate,
            "tail_coverage": coverage_gate,
            "independence": independence_gate,
            "juror_diversity": diversity_gate,
            "evidence": evidence_gate,
        },
        "court_verdict": court_verdict,
        "approval": approval_group,
        "approval_params": {
            "approved": approved, "approver": approver, "approved_at": approved_at,
        },
        "approval_gate": approval_gate,
        "installed": installed,
        "installation": installation_group,
        "install_effect": install_effect,
        "install_result": install_result,
        "install_relation": install_relation,
        "rollback_approval": rollback_approval_group,
        "rollback_approval_params": {
            "approved": rollback_approved, "approver": rollback_approver,
            "approved_at": rollback_approved_at,
        },
        "rollback_gate": rollback_gate,
        "rollback": rollback_group,
        "rollback_effect": rollback_effect,
        "rollback_result": rollback_result,
        "rollback_relation": rollback_relation,
        "lifecycle_relations": lifecycle_relations,
        "relations": all_relations,
    }


def _set_parameter(
    store: Store,
    params: Mapping[str, str],
    name: str,
    value: Any,
    actor: str,
) -> str:
    if name not in params:
        raise KeyError("unknown self-extension parameter %r" % name)
    node_id = str(params[name])
    store.edit(node_id, ["body", "floor", "value"], value, actor=actor)
    return node_id


def set_proposal_parameter(
    store: Store,
    domain: Mapping[str, Any],
    name: str,
    value: Any,
    *,
    actor: str = "proposal-editor",
) -> str:
    """Edit a proposal's parameter node without mutating the frozen proposal."""
    return _set_parameter(store, domain["proposal_params"], name, value, actor)


def set_court_evidence(
    store: Store,
    domain: Mapping[str, Any],
    name: str,
    value: Any,
    *,
    actor: str = "court",
) -> str:
    if name in {
        "confidence", "confidence_threshold", "tail_coverage",
        "required_coverage", "juror_diversity", "required_diversity",
    }:
        value = _ratio(value, "court %s" % name)
    return _set_parameter(store, domain["evidence_params"], name, value, actor)


def set_install_approval(
    store: Store,
    domain: Mapping[str, Any],
    approved: bool,
    *,
    approver: str = "",
    approved_at: str = "",
    actor: str = "founder",
) -> list[str]:
    params = domain["approval_params"]
    values = {
        "approved": bool(approved),
        "approver": _text(approver, "approver", allow_empty=not approved),
        "approved_at": _text(
            approved_at, "approval timestamp", allow_empty=not approved
        ),
    }
    return [_set_parameter(store, params, name, value, actor)
            for name, value in values.items()]


def set_rollback_approval(
    store: Store,
    domain: Mapping[str, Any],
    approved: bool,
    *,
    approver: str = "",
    approved_at: str = "",
    actor: str = "founder",
) -> list[str]:
    params = domain["rollback_approval_params"]
    values = {
        "approved": bool(approved),
        "approver": _text(approver, "rollback approver", allow_empty=not approved),
        "approved_at": _text(
            approved_at, "rollback approval timestamp", allow_empty=not approved
        ),
    }
    return [_set_parameter(store, params, name, value, actor)
            for name, value in values.items()]


def _gate_is_open(store: Store, node_id: str) -> bool:
    return bool(store.pull(node_id))


def apply_installation(
    store: Store,
    domain: Mapping[str, Any],
    sink: MutableMapping[Any, Any],
    *,
    actor: str = "founder",
) -> dict[str, Any]:
    """Apply the external change only while approval and court are live-green."""
    if not _gate_is_open(store, str(domain["approval_gate"])):
        raise PermissionError("installation approval gate is closed")
    if not _gate_is_open(store, str(domain["court_verdict"])):
        raise PermissionError("installation court gate is closed")
    effect = str(domain["install_effect"])
    store.apply_op({"op": "unfreeze", "id": effect, "actor": actor})
    try:
        target = store.pull(store.nodes[effect]["params"]["target"])
        store.edit(effect, ["body", "floor", "target"], target, actor=actor)
        result = apply_effect(store, effect, sink, actor=actor)
    finally:
        store.apply_op({"op": "freeze", "id": effect, "actor": actor})
    store.edit(
        str(domain["installed"]), ["body", "floor", "value"], True, actor=actor
    )
    return result


def apply_rollback(
    store: Store,
    domain: Mapping[str, Any],
    sink: MutableMapping[Any, Any],
    *,
    actor: str = "founder",
) -> dict[str, Any]:
    """Apply the explicit inverse only while rollback approval and court are green."""
    if not _gate_is_open(store, str(domain["rollback_gate"])):
        raise PermissionError("rollback approval gate is closed")
    if not _gate_is_open(store, str(domain["court_verdict"])):
        raise PermissionError("rollback court gate is closed")
    effect = str(domain["rollback_effect"])
    store.apply_op({"op": "unfreeze", "id": effect, "actor": actor})
    try:
        target = store.pull(store.nodes[effect]["params"]["target"])
        store.edit(effect, ["body", "floor", "target"], target, actor=actor)
        result = apply_effect(store, effect, sink, actor=actor)
    finally:
        store.apply_op({"op": "freeze", "id": effect, "actor": actor})
    store.edit(
        str(domain["installed"]), ["body", "floor", "value"], False, actor=actor
    )
    return result
