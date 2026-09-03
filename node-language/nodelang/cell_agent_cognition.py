"""Graph-native, proposal-only cognition assembled from universal Cells.

Provider SDKs, network calls, model invocation, target mutation, permission
issuance, and adapter execution are deliberately outside this module.  The
graph remains the durable body; a model descriptor and binding are replaceable
relations, a request seals one authorised source snapshot, and model output may
only enter as an untrusted Proposal relation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_adapters import (
    AdapterProtocol,
    verify_adapter_catalog,
    verify_released_adapter,
)
from .cell_agent_body import (
    AgentBodyProtocol,
    _compose_authorization_receipt,
    _evaluate_agent_requests,
    _read_authorization_receipt,
    _verify_authorization_receipt_integrity,
    _require_request_binding,
    _validate_decision,
    read_context_entry,
    read_agent_body,
    read_agent_session,
)
from .cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationProtocol,
    AuthorizationRequest,
    read_authorization_rule,
    verify_authorization_policy,
)
from .cell_catalog import (
    AssemblyProtocol,
    build_definition,
    build_interface,
    build_role_obligation,
    release_definition,
    verify_released_catalog,
    verify_released_definition,
)
from .cell_lifecycle import graph_content_digest
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
)
from .cell_relation_contract import (
    RelationContractProtocol,
    bootstrap_relation_contract_protocol,
    build_relation_contract,
    build_role_constraint,
    open_relation_contract_protocol,
    resolve_relation_contract_authority,
    validate_relation,
)
from .cell_status_ledger import (
    StatusEventProjection,
    StatusLedgerProtocol,
    assert_subject_usable,
    bootstrap_status_ledger_protocol,
    open_status_ledger_protocol,
    prepare_status_event,
    read_status_event,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "descriptor-member",
    "binding-member",
    "session-cognition-member",
    "request-member",
    "proposal-member",
    "budget-max-context-entries",
    "budget-max-input-bytes",
    "budget-max-output-bytes",
    "budget-max-latency-ms",
    "budget-max-cost-microunits",
    "descriptor-definition",
    "descriptor-provider",
    "descriptor-model",
    "descriptor-model-revision",
    "descriptor-input-contract",
    "descriptor-output-definition",
    "descriptor-modality",
    "descriptor-context-limit",
    "descriptor-data-policy",
    "descriptor-evidence",
    "descriptor-version",
    "descriptor-budget",
    "descriptor-adapter-action",
    "descriptor-adapter-location",
    "descriptor-adapter-datatype",
    "descriptor-reviewer",
    "descriptor-release-request",
    "descriptor-release-receipt",
    "descriptor-release-revision",
    "descriptor-lifecycle",
    "descriptor-digest",
    "release-request-descriptor",
    "release-request-reviewer",
    "release-request-source-revision",
    "release-request-policy",
    "release-request-action",
    "release-request-rule",
    "release-request-reason",
    "binding-definition",
    "binding-body",
    "binding-descriptor",
    "binding-descriptor-digest",
    "binding-adapter",
    "binding-adapter-catalog",
    "binding-policy",
    "binding-budget",
    "binding-creation-revision",
    "binding-action",
    "binding-rule",
    "binding-authorization-reason",
    "binding-authorization-receipt",
    "binding-lifecycle",
    "binding-digest",
    "session-cognition-session",
    "session-cognition-request-registry",
    "session-cognition-creation-revision",
    "session-cognition-action",
    "session-cognition-policy",
    "session-cognition-rule",
    "session-cognition-reason",
    "session-cognition-receipt",
    "request-definition",
    "request-session",
    "request-binding",
    "request-source-revision",
    "request-revision-chain-digest",
    "request-context-manifest",
    "request-input-digest",
    "request-input-bytes",
    "request-intent",
    "request-purpose",
    "request-output-definition",
    "request-budget",
    "request-idempotency",
    "request-read-receipt",
    "request-registry-receipt",
    "request-state",
    "request-digest",
    "manifest-member",
    "manifest-entry",
    "manifest-context-root",
    "manifest-sequence",
    "proposal-definition",
    "proposal-request",
    "proposal-session",
    "proposal-binding",
    "proposal-source-revision",
    "proposal-context-manifest",
    "proposal-operation",
    "proposal-payload",
    "proposal-target",
    "proposal-rationale",
    "proposal-uncertainty",
    "proposal-evidence",
    "proposal-idempotency",
    "proposal-creation-receipt",
    "proposal-state",
    "proposal-digest",
)

STATE_NAMES = (
    "draft",
    "released",
    "active",
    "prepared",
    "proposed",
    "revoked",
)
REGISTRY_NAMES = ("descriptor", "binding", "session", "request", "proposal")
RELATION_BUDGET = 100_000
MAX_POLICIES = 32
MAX_MODALITIES = 16
MAX_DATA_POLICIES = 64
MAX_EVIDENCE = 128
MAX_CONTEXT_ENTRIES = 128
MAX_PROPOSAL_TARGETS = 128
MAX_TEXT_BYTES = 16_384


@dataclass(frozen=True, slots=True)
class AgentCognitionProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    registries: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown cognition role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown cognition state %r" % name) from exc

    def registry(self, name: str) -> str:
        try:
            return self.registries[name]
        except KeyError as exc:
            raise InvalidCell("unknown cognition registry %r" % name) from exc


@dataclass(frozen=True, slots=True)
class AgentCognitionDefinitions:
    model_descriptor_root: str
    model_binding_root: str
    cognition_request_root: str
    proposal_root: str
    status_ledger_root: str

    @property
    def roots(self) -> tuple[str, ...]:
        return (
            self.model_descriptor_root,
            self.model_binding_root,
            self.cognition_request_root,
            self.proposal_root,
        )


@dataclass(frozen=True, slots=True)
class CognitionBudgetProjection:
    root_id: str
    max_context_entries: int
    max_input_bytes: int
    max_output_bytes: int
    max_latency_ms: int
    max_cost_microunits: int


@dataclass(frozen=True, slots=True)
class ModelDescriptorProjection:
    root_id: str
    definition_root: str
    provider_root: str
    model_root: str
    model_revision_root: str
    input_contract_root: str
    output_definition_root: str
    modality_roots: tuple[str, ...]
    context_limit: int
    data_policy_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    version: str
    budget_root: str
    adapter_action_root: str
    adapter_location_root: str
    adapter_datatype_root: str
    reviewer_root: str
    release_request_root: str | None
    release_receipt_root: str | None
    release_policy_root: str | None
    release_action_root: str | None
    release_rule_roots: tuple[str, ...]
    release_reason: str | None
    release_revision: int | None
    lifecycle_root: str
    digest_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class ModelBindingProjection:
    root_id: str
    definition_root: str
    body_root: str
    descriptor_root: str
    descriptor_digest: str
    adapter_root: str
    adapter_catalog_root: str
    policy_roots: tuple[str, ...]
    budget_root: str
    creation_revision: int
    action_root: str
    rule_roots: tuple[str, ...]
    authorization_reason: str
    authorization_receipt_root: str
    lifecycle_root: str
    digest_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class SessionCognitionProjection:
    root_id: str
    session_root: str
    request_registry_root: str
    creation_revision: int
    action_root: str
    policy_root: str
    rule_roots: tuple[str, ...]
    authorization_reason: str
    authorization_receipt_root: str


@dataclass(frozen=True, slots=True)
class CognitionRequestProjection:
    root_id: str
    definition_root: str
    session_root: str
    binding_root: str
    source_revision: int
    revision_chain_digest: str
    context_manifest_root: str
    context_entry_roots: tuple[str, ...]
    context_roots: tuple[str, ...]
    input_digest: str
    input_bytes: int
    intent_root: str
    purpose_root: str
    output_definition_root: str
    budget_root: str
    idempotency_key: str
    read_receipt_roots: tuple[str, ...]
    registry_receipt_root: str
    state_root: str
    digest_root: str
    digest: str


@dataclass(frozen=True, slots=True)
class ProposalProjection:
    root_id: str
    definition_root: str
    request_root: str
    session_root: str
    binding_root: str
    source_revision: int
    context_manifest_root: str
    operation_root: str
    payload_root: str
    target_roots: tuple[str, ...]
    rationale: str
    uncertainty: float
    evidence_roots: tuple[str, ...]
    idempotency_key: str
    creation_receipt_root: str
    state_root: str
    digest_root: str
    digest: str


def _terminal(root_id: str, value: str | int) -> Cell:
    if isinstance(value, int):
        raw = str(value).encode("ascii")
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raise InvalidCell("cognition terminal value is invalid")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, raw)


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("%s is not terminal" % label)
        return cell.atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("%s is missing or invalid" % label) from exc


def _integer(snapshot: Snapshot, root_id: str, label: str) -> int:
    try:
        return int(_text(snapshot, root_id, label))
    except ValueError as exc:
        raise InvalidCell("%s is not an integer" % label) from exc


def _for_role(members: Iterable[RelationMember], role_id: str) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _one(members: Iterable[RelationMember], role_id: str, label: str) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("%s requires exactly one participant" % label)
    return values[0]


def _optional(
    members: Iterable[RelationMember], role_id: str, label: str
) -> str | None:
    values = _for_role(members, role_id)
    if len(values) > 1:
        raise InvalidCell("%s permits at most one participant" % label)
    return values[0] if values else None


def _closed_roles(
    members: Iterable[RelationMember], allowed: Iterable[str], label: str
) -> None:
    permitted = frozenset(allowed)
    if any(member.role_id not in permitted for member in members):
        raise InvalidCell("%s contains an undeclared role" % label)


def _unique(
    roots: Iterable[str], label: str, *, limit: int
) -> tuple[str, ...]:
    values = tuple(roots)
    if len(values) > limit:
        raise InvalidCell("%s exceeds its bound" % label)
    if len(values) != len(set(values)):
        raise InvalidCell("%s repeats a root" % label)
    return values


def _ensure(snapshot: Snapshot, roots: Iterable[str], label: str) -> None:
    if any(root not in snapshot.cells for root in roots):
        raise InvalidCell("%s references a missing Cell" % label)


def _validate_model_identity_capability(
    snapshot: Snapshot,
    protocol: AgentCognitionProtocol,
    capability_root: str,
    *,
    provider_root: str,
    model_root: str,
    model_revision_root: str,
) -> None:
    """Require the adapter location bound to one exact model identity relation."""
    members = read_relation(snapshot, capability_root, budget=RELATION_BUDGET)
    roles = tuple(
        protocol.role(name) for name in (
            "descriptor-provider",
            "descriptor-model",
            "descriptor-model-revision",
        )
    )
    _closed_roles(members, roles, "model identity capability")
    actual = (
        _one(members, roles[0], "model identity provider"),
        _one(members, roles[1], "model identity model"),
        _one(members, roles[2], "model identity revision"),
    )
    if actual != (provider_root, model_root, model_revision_root):
        raise InvalidCell("model identity capability does not match descriptor")


def _assert_creates(
    snapshot: Snapshot, cells: Iterable[Cell], label: str
) -> tuple[Cell, ...]:
    values = tuple(cells)
    identities = tuple(cell.id for cell in values)
    if len(identities) != len(set(identities)):
        raise InvalidCell("%s creates duplicate Cell identities" % label)
    if any(root in snapshot.cells for root in identities):
        raise InvalidCell("%s would replace an existing Cell" % label)
    return values


def _determining_rule_object(
    snapshot: Snapshot,
    authorization: AuthorizationProtocol,
    rule_roots: Iterable[str],
    admitted_roots: Iterable[str],
    label: str,
) -> str:
    objects = {
        read_authorization_rule(snapshot, authorization, root).object_root
        for root in rule_roots
    }
    admitted = frozenset(admitted_roots)
    if len(objects) != 1 or not objects.issubset(admitted):
        raise AuthorizationDenied(
            "%s authority is not exact to the object or lineage" % label
        )
    return next(iter(objects))


def _protocol_for_prefix(prefix: str) -> AgentCognitionProtocol:
    return AgentCognitionProtocol(
        prefix + ":root",
        MappingProxyType({
            name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
        }),
        MappingProxyType({
            name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES
        }),
        MappingProxyType({
            name: "%s:registry:%s" % (prefix, name) for name in REGISTRY_NAMES
        }),
    )


_REGISTRY_ROLES = MappingProxyType({
    "descriptor": "descriptor-member",
    "binding": "binding-member",
    "session": "session-cognition-member",
    "request": "request-member",
    "proposal": "proposal-member",
})


def _validate_protocol(
    snapshot: Snapshot, protocol: AgentCognitionProtocol
) -> None:
    if not protocol.root_id.endswith(":root"):
        raise InvalidCell("cognition protocol identity is invalid")
    expected = _protocol_for_prefix(protocol.root_id[:-5])
    if protocol != expected:
        raise InvalidCell("cognition protocol vocabulary mapping drifted")
    _ensure(
        snapshot,
        (
            protocol.root_id,
            *protocol.roles.values(),
            *protocol.states.values(),
            *protocol.registries.values(),
        ),
        "cognition protocol",
    )
    for name, root in (*protocol.roles.items(), *protocol.states.items()):
        if _text(snapshot, root, "cognition vocabulary") != name:
            raise InvalidCell("cognition protocol vocabulary drifted")
    members = read_relation(snapshot, protocol.root_id, budget=RELATION_BUDGET)
    expected_members = tuple(
        (protocol.role("vocabulary-member"), root)
        for root in (
            *protocol.roles.values(),
            *protocol.states.values(),
            *protocol.registries.values(),
        )
    )
    if snapshot.cells[protocol.root_id].atom != b"" or tuple(
        (member.role_id, member.participant_id) for member in members
    ) != expected_members:
        raise InvalidCell("cognition protocol vocabulary relation drifted")
    for name, role_name in _REGISTRY_ROLES.items():
        registry = protocol.registry(name)
        if snapshot.cells[registry].atom != b"":
            raise InvalidCell("cognition registry drifted")
        registry_members = read_relation(
            snapshot, registry, budget=RELATION_BUDGET
        )
        if any(
            member.role_id != protocol.role(role_name)
            for member in registry_members
        ):
            raise InvalidCell("cognition registry contains an undeclared role")
        roots = tuple(member.participant_id for member in registry_members)
        if len(roots) != len(set(roots)):
            raise InvalidCell("cognition registry repeats a root")


def bootstrap_agent_cognition_protocol(
    store: CellStore, *, prefix: str = "agent-cognition-protocol"
) -> AgentCognitionProtocol:
    protocol = _protocol_for_prefix(prefix)
    batch = CellBatch(store)
    for name, root in (*protocol.roles.items(), *protocol.states.items()):
        batch.add(_terminal(root, name))
    for root in protocol.registries.values():
        batch.relation((), relation_id=root)
    batch.relation(
        (
            (protocol.role("vocabulary-member"), root)
            for root in (
                *protocol.roles.values(),
                *protocol.states.values(),
                *protocol.registries.values(),
            )
        ),
        relation_id=protocol.root_id,
    )
    batch.commit()
    _validate_protocol(store.snapshot(), protocol)
    return protocol


def open_agent_cognition_protocol(
    snapshot: Snapshot, *, prefix: str = "agent-cognition-protocol"
) -> AgentCognitionProtocol:
    protocol = _protocol_for_prefix(prefix)
    _validate_protocol(snapshot, protocol)
    return protocol


def _definition_region(
    store: CellStore,
    assembly: AssemblyProtocol,
    cognition: AgentCognitionProtocol,
    *,
    prefix: str,
    key: str,
    name: str,
    contract: str,
    documentation: str,
    evidence: str,
    shared_roots: Iterable[str] = (),
) -> str:
    roots = {
        "slot": "%s:%s:root-slot" % (prefix, key),
        "name": "%s:%s:interface-name" % (prefix, key),
        "contract": "%s:%s:contract" % (prefix, key),
        "documentation": "%s:%s:documentation" % (prefix, key),
        "presentation": "%s:%s:presentation" % (prefix, key),
        "evidence": "%s:%s:evidence" % (prefix, key),
    }
    store.commit(
        store.revision,
        create=(
            _terminal(roots["slot"], "unbound instance root"),
            _terminal(roots["name"], "root"),
            _terminal(roots["contract"], contract),
            _terminal(roots["documentation"], documentation),
            _terminal(roots["presentation"], "agent-cognition/%s" % key),
            _terminal(roots["evidence"], evidence),
        ),
    )
    interface = build_interface(
        store,
        assembly,
        interface_id="%s:%s:interface:root" % (prefix, key),
        target_root=roots["slot"],
        name_root=roots["name"],
        contract_root=roots["contract"],
        presentation_root=roots["presentation"],
        documentation_root=roots["documentation"],
    )
    definition = build_definition(
        store,
        assembly,
        definition_id="%s:definition:%s" % (prefix, key),
        name=name,
        version="1.0.0",
        part_roots=(
            roots["slot"],
            roots["name"],
            roots["contract"],
            roots["documentation"],
            roots["presentation"],
            *interface.part_roots,
        ),
        interface_roots=(interface.root_id,),
        evidence_roots=(roots["evidence"],),
        shared_roots=(
            cognition.root_id,
            *cognition.roles.values(),
            *cognition.states.values(),
            *cognition.registries.values(),
            *shared_roots,
        ),
    )
    return definition.root_id


def _cognition_contract_specs(
    cognition: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
) -> Mapping[str, tuple[tuple[str, int, int, str | None, int | None], ...]]:
    """Return the build recipe that is persisted as released graph authority."""
    one = (1, 1)
    descriptor = (
        ("descriptor-definition", *one, definitions.model_descriptor_root, None),
        ("descriptor-provider", *one, None, None),
        ("descriptor-model", *one, None, None),
        ("descriptor-model-revision", *one, None, None),
        ("descriptor-input-contract", *one, None, None),
        ("descriptor-output-definition", *one, definitions.proposal_root, None),
        ("descriptor-modality", 1, MAX_MODALITIES, None, None),
        ("descriptor-context-limit", *one, None, 32),
        ("descriptor-data-policy", 1, MAX_DATA_POLICIES, None, None),
        ("descriptor-evidence", 1, MAX_EVIDENCE, None, None),
        ("descriptor-version", *one, None, 128),
        ("descriptor-budget", *one, None, None),
        ("descriptor-adapter-action", *one, None, None),
        ("descriptor-adapter-location", *one, None, None),
        ("descriptor-adapter-datatype", *one, None, None),
        ("descriptor-reviewer", *one, None, None),
        ("descriptor-release-request", 0, 1, None, None),
        ("descriptor-release-receipt", 0, 1, None, None),
        ("descriptor-release-revision", 0, 1, None, 32),
        ("descriptor-lifecycle", *one, None, None),
        ("descriptor-digest", *one, None, 128),
    )
    binding = (
        ("binding-definition", *one, definitions.model_binding_root, None),
        ("binding-body", *one, None, None),
        ("binding-descriptor", *one, None, None),
        ("binding-descriptor-digest", *one, None, 128),
        ("binding-adapter", *one, None, None),
        ("binding-adapter-catalog", *one, None, None),
        ("binding-policy", 1, MAX_POLICIES, None, None),
        ("binding-budget", *one, None, None),
        ("binding-creation-revision", *one, None, 32),
        ("binding-action", *one, None, None),
        ("binding-rule", 1, 256, None, None),
        ("binding-authorization-reason", *one, None, MAX_TEXT_BYTES),
        ("binding-authorization-receipt", *one, None, None),
        ("binding-lifecycle", *one, cognition.state("active"), None),
        ("binding-digest", *one, None, 128),
    )
    request = (
        ("request-definition", *one, definitions.cognition_request_root, None),
        ("request-session", *one, None, None),
        ("request-binding", *one, None, None),
        ("request-source-revision", *one, None, 32),
        ("request-revision-chain-digest", *one, None, 128),
        ("request-context-manifest", *one, None, None),
        ("request-input-digest", *one, None, 128),
        ("request-input-bytes", *one, None, 32),
        ("request-intent", *one, None, None),
        ("request-purpose", *one, None, None),
        ("request-output-definition", *one, definitions.proposal_root, None),
        ("request-budget", *one, None, None),
        ("request-idempotency", *one, None, 512),
        ("request-read-receipt", 1, MAX_CONTEXT_ENTRIES, None, None),
        ("request-registry-receipt", *one, None, None),
        ("request-state", *one, cognition.state("prepared"), None),
        ("request-digest", *one, None, 128),
    )
    proposal = (
        ("proposal-definition", *one, definitions.proposal_root, None),
        ("proposal-request", *one, None, None),
        ("proposal-session", *one, None, None),
        ("proposal-binding", *one, None, None),
        ("proposal-source-revision", *one, None, 32),
        ("proposal-context-manifest", *one, None, None),
        ("proposal-operation", *one, None, None),
        ("proposal-payload", *one, None, None),
        ("proposal-target", 1, MAX_PROPOSAL_TARGETS, None, None),
        ("proposal-rationale", *one, None, MAX_TEXT_BYTES),
        ("proposal-uncertainty", *one, None, 64),
        ("proposal-evidence", 0, MAX_EVIDENCE, None, None),
        ("proposal-idempotency", *one, None, 512),
        ("proposal-creation-receipt", *one, None, None),
        ("proposal-state", *one, cognition.state("proposed"), None),
        ("proposal-digest", *one, None, 128),
    )
    return MappingProxyType({
        "model-descriptor": descriptor,
        "model-binding": binding,
        "cognition-request": request,
        "proposal": proposal,
    })


def _attach_cognition_contract(
    store: CellStore,
    assembly: AssemblyProtocol,
    relation_protocol: RelationContractProtocol,
    cognition: AgentCognitionProtocol,
    *,
    prefix: str,
    key: str,
    definition_root: str,
    shared_definition_roots: Iterable[str],
    specs: Iterable[tuple[str, int, int, str | None, int | None]],
) -> None:
    constraints = tuple(
        build_role_constraint(
            store,
            relation_protocol,
            constraint_id="%s:contract:%s:constraint:%s" % (
                prefix, key, role_name
            ),
            participant_role=cognition.role(role_name),
            minimum=minimum,
            maximum=maximum,
            fixed_participant_root=fixed_root,
            terminal_atom_maximum=atom_maximum,
            budget=RELATION_BUDGET,
        )
        for role_name, minimum, maximum, fixed_root, atom_maximum in specs
    )
    contract = build_relation_contract(
        store,
        relation_protocol,
        contract_id="%s:contract:%s" % (prefix, key),
        constraint_roots=(item.root_id for item in constraints),
        released=True,
        budget=RELATION_BUDGET,
    )
    obligations = tuple(
        build_role_obligation(
            store,
            assembly,
            obligation_id="%s:%s:obligation:%s" % (prefix, key, role_name),
            required_role=assembly.role(role_name),
            minimum=1,
        ).root_id
        for role_name in ("interface", "rule", "capability")
    )
    shared_roots = tuple(dict.fromkeys((
        relation_protocol.root_id,
        *relation_protocol.roles.values(),
        *relation_protocol.states.values(),
        *relation_protocol.values.values(),
        *shared_definition_roots,
    )))
    external = {
        NULL_CELL_ID,
        *shared_roots,
        cognition.root_id,
        *cognition.roles.values(),
        *cognition.states.values(),
        *cognition.registries.values(),
    }
    snapshot = store.snapshot()
    contract_region: set[str] = set()
    pending = [contract.root_id]
    while pending:
        root = pending.pop()
        if root in external or root in contract_region:
            continue
        try:
            cell = snapshot.cells[root]
        except KeyError as exc:
            raise InvalidCell(
                "cognition relation contract references a missing Cell"
            ) from exc
        contract_region.add(root)
        pending.extend((cell.link0, cell.link1))
    shared_authority_roots = tuple(dict.fromkeys((
        *shared_roots,
        *sorted(contract_region),
    )))
    patch = prepare_append_relation_members(
        snapshot,
        definition_root,
        (
            (assembly.role("rule"), contract.root_id),
            (assembly.role("capability"), relation_protocol.root_id),
            *((assembly.role("obligation"), root) for root in obligations),
            *((assembly.role("shared"), root) for root in shared_authority_roots),
        ),
        budget=RELATION_BUDGET,
    )
    store.commit(
        store.revision,
        create=patch.create,
        replace=patch.replace,
    )
    release_definition(store, assembly, definition_root)


def build_agent_cognition_definitions(
    store: CellStore,
    assembly: AssemblyProtocol,
    cognition: AgentCognitionProtocol,
    *,
    prefix: str = "agent-cognition-library",
) -> AgentCognitionDefinitions:
    _validate_protocol(store.snapshot(), cognition)
    specs = (
        (
            "model-descriptor",
            "Model Descriptor",
            "released provider-neutral model identity and Proposal output contract",
            "Pins a provider, model revision, data policy, budgets, and adapter bounds without executing it.",
        ),
        (
            "model-binding",
            "Model Binding",
            "immutable body-to-descriptor and allowlisted-adapter binding",
            "Binds a durable Agent Body to one released descriptor and adapter generation; sessions pin the exact binding.",
        ),
        (
            "cognition-request",
            "Cognition Request",
            "one authorised source revision, bounded context manifest, and Proposal-only output",
            "Seals the exact session binding and authorised context snapshot supplied to replaceable cognition.",
        ),
        (
            "proposal",
            "Proposal",
            "untrusted bounded proposal with no direct mutation or execution authority",
            "Records proposed graph work and evidence; acceptance, mutation, permission, and execution remain separate governed decisions.",
        ),
    )
    status_prefix = prefix + ":status-ledger"
    status_root = status_prefix + ":root"
    status = (
        open_status_ledger_protocol(store.snapshot(), prefix=status_prefix)
        if status_root in store.snapshot().cells
        else bootstrap_status_ledger_protocol(store, prefix=status_prefix)
    )
    roots = tuple(
        _definition_region(
            store,
            assembly,
            cognition,
            prefix=prefix,
            key=key,
            name=name,
            contract=contract,
            documentation=documentation,
            evidence="tests_replica/test_cell_agent_cognition.py",
            shared_roots=(
                status.root_id,
                status.registry_root,
                *status.roles.values(),
                *status.states.values(),
            ),
        )
        for key, name, contract, documentation in specs
    )
    definitions = AgentCognitionDefinitions(*roots, status.root_id)
    relation_prefix = prefix + ":relation-contract-protocol"
    relation_root = relation_prefix + ":root"
    relation_protocol = (
        open_relation_contract_protocol(
            store.snapshot(), relation_root, budget=RELATION_BUDGET
        )
        if relation_root in store.snapshot().cells
        else bootstrap_relation_contract_protocol(
            store, prefix=relation_prefix
        )
    )
    contract_specs = _cognition_contract_specs(cognition, definitions)
    for (key, _name, _contract, _documentation), definition_root in zip(
        specs, roots
    ):
        _attach_cognition_contract(
            store,
            assembly,
            relation_protocol,
            cognition,
            prefix=prefix,
            key=key,
            definition_root=definition_root,
            shared_definition_roots=definitions.roots,
            specs=contract_specs[key],
        )
    return definitions


def _verify_definitions(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    catalog_root: str,
    definitions: AgentCognitionDefinitions,
) -> None:
    catalog = verify_released_catalog(snapshot, assembly, catalog_root)
    if not set(definitions.roots).issubset(catalog.definition_roots):
        raise InvalidCell("cognition definitions are outside the released catalogue")
    for root in definitions.roots:
        verify_released_definition(snapshot, assembly, root)
    _status_protocol(snapshot, definitions)


def _status_protocol(
    snapshot: Snapshot,
    definitions: AgentCognitionDefinitions,
) -> StatusLedgerProtocol:
    if not definitions.status_ledger_root.endswith(":root"):
        raise InvalidCell("cognition status-ledger identity is invalid")
    return open_status_ledger_protocol(
        snapshot,
        prefix=definitions.status_ledger_root.removesuffix(":root"),
    )


def _validate_definition_relation(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    definition_root: str,
    relation_root: str,
) -> None:
    """Validate one instance through its released graph-held definition."""
    definition = verify_released_definition(
        snapshot, assembly, definition_root
    )
    authority = resolve_relation_contract_authority(
        snapshot,
        capability_roots=definition.capability_roots,
        rule_roots=definition.rule_roots,
        budget=RELATION_BUDGET,
    )
    validate_relation(
        snapshot,
        authority.protocol,
        authority.contract.root_id,
        relation_root,
        budget=RELATION_BUDGET,
    )


def build_cognition_budget(
    store: CellStore,
    protocol: AgentCognitionProtocol,
    *,
    budget_id: str,
    max_context_entries: int,
    max_input_bytes: int,
    max_output_bytes: int,
    max_latency_ms: int,
    max_cost_microunits: int,
) -> str:
    values = (
        max_context_entries,
        max_input_bytes,
        max_output_bytes,
        max_latency_ms,
        max_cost_microunits,
    )
    if (
        max_context_entries < 1
        or max_context_entries > MAX_CONTEXT_ENTRIES
        or max_input_bytes < 1
        or max_output_bytes < 1
        or max_latency_ms < 1
        or max_cost_microunits < 0
    ):
        raise InvalidCell("cognition budget is outside released bounds")
    if budget_id in store.snapshot().cells:
        raise InvalidCell("cognition budget root already exists")
    role_names = (
        "budget-max-context-entries",
        "budget-max-input-bytes",
        "budget-max-output-bytes",
        "budget-max-latency-ms",
        "budget-max-cost-microunits",
    )
    terminals = tuple(
        _terminal("%s:%s" % (budget_id, role), value)
        for role, value in zip(role_names, values)
    )
    relation = compose_relation_cells(
        tuple(
            (protocol.role(role), terminal.id)
            for role, terminal in zip(role_names, terminals)
        ),
        relation_id=budget_id,
    )
    store.commit(store.revision, create=(*terminals, *relation.cells))
    read_cognition_budget(store.snapshot(), protocol, budget_id)
    return budget_id


def read_cognition_budget(
    snapshot: Snapshot,
    protocol: AgentCognitionProtocol,
    budget_root: str,
) -> CognitionBudgetProjection:
    members = read_relation(snapshot, budget_root, budget=RELATION_BUDGET)
    role_names = (
        "budget-max-context-entries",
        "budget-max-input-bytes",
        "budget-max-output-bytes",
        "budget-max-latency-ms",
        "budget-max-cost-microunits",
    )
    _closed_roles(
        members, (protocol.role(name) for name in role_names), "cognition budget"
    )
    values = tuple(
        _integer(
            snapshot,
            _one(members, protocol.role(name), "cognition budget " + name),
            "cognition budget " + name,
        )
        for name in role_names
    )
    budget = CognitionBudgetProjection(budget_root, *values)
    if (
        budget.max_context_entries < 1
        or budget.max_context_entries > MAX_CONTEXT_ENTRIES
        or budget.max_input_bytes < 1
        or budget.max_output_bytes < 1
        or budget.max_latency_ms < 1
        or budget.max_cost_microunits < 0
    ):
        raise InvalidCell("cognition budget is outside released bounds")
    return budget


def _descriptor_digest(
    snapshot: Snapshot,
    protocol: AgentCognitionProtocol,
    descriptor: ModelDescriptorProjection,
) -> str:
    digest = hashlib.blake2b(digest_size=32)
    values: list[bytes] = []
    for value in (
        descriptor.root_id,
        descriptor.definition_root,
        descriptor.provider_root,
        descriptor.model_root,
        descriptor.model_revision_root,
        descriptor.input_contract_root,
        descriptor.output_definition_root,
        *descriptor.modality_roots,
        str(descriptor.context_limit),
        *descriptor.data_policy_roots,
        *descriptor.evidence_roots,
        descriptor.version,
        descriptor.budget_root,
        descriptor.adapter_action_root,
        descriptor.adapter_location_root,
        descriptor.adapter_datatype_root,
        descriptor.reviewer_root,
        descriptor.release_request_root or "",
        descriptor.release_receipt_root or "",
        descriptor.release_policy_root or "",
        descriptor.release_action_root or "",
        *descriptor.release_rule_roots,
        descriptor.release_reason or "",
    ):
        values.append(value.encode("utf-8"))
    budget = read_cognition_budget(
        snapshot,
        protocol,
        descriptor.budget_root,
    )
    values.extend(
        str(value).encode("ascii")
        for value in (
            budget.max_context_entries,
            budget.max_input_bytes,
            budget.max_output_bytes,
            budget.max_latency_ms,
            budget.max_cost_microunits,
        )
    )
    for root in (
        descriptor.provider_root,
        descriptor.model_root,
        descriptor.model_revision_root,
        descriptor.input_contract_root,
        *descriptor.modality_roots,
        *descriptor.data_policy_roots,
        *descriptor.evidence_roots,
        descriptor.budget_root,
        descriptor.adapter_action_root,
        descriptor.adapter_location_root,
        descriptor.adapter_datatype_root,
        descriptor.reviewer_root,
    ):
        values.append(graph_content_digest(
            snapshot, root, budget=RELATION_BUDGET
        ))
    for raw in values:
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()

def build_model_descriptor(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    *,
    descriptor_id: str,
    provider_root: str,
    model_root: str,
    model_revision_root: str,
    input_contract_root: str,
    output_definition_root: str,
    modality_roots: Iterable[str],
    context_limit: int,
    data_policy_roots: Iterable[str],
    evidence_roots: Iterable[str],
    version: str,
    budget_root: str,
    adapter_action_root: str,
    adapter_location_root: str,
    adapter_datatype_root: str,
    reviewer_root: str,
) -> ModelDescriptorProjection:
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    if output_definition_root != definitions.proposal_root:
        raise InvalidCell("model descriptor output must be the released Proposal")
    if descriptor_id in snapshot.cells:
        raise InvalidCell("model descriptor root already exists")
    modalities = _unique(
        modality_roots, "model descriptor modalities", limit=MAX_MODALITIES
    )
    policies = _unique(
        data_policy_roots,
        "model descriptor data policies",
        limit=MAX_DATA_POLICIES,
    )
    evidence = _unique(
        evidence_roots, "model descriptor evidence", limit=MAX_EVIDENCE
    )
    if not modalities or not policies or not evidence:
        raise InvalidCell("model descriptor requires modality, policy, and evidence")
    if not isinstance(version, str) or not version or len(version) > 128:
        raise InvalidCell("model descriptor version is invalid")
    budget = read_cognition_budget(snapshot, protocol, budget_root)
    if context_limit < 1 or context_limit > budget.max_context_entries:
        raise InvalidCell("model descriptor context limit exceeds its budget")
    required = (
        provider_root,
        model_root,
        model_revision_root,
        input_contract_root,
        output_definition_root,
        *modalities,
        *policies,
        *evidence,
        budget_root,
        adapter_action_root,
        adapter_location_root,
        adapter_datatype_root,
        reviewer_root,
    )
    _ensure(snapshot, required, "model descriptor")
    _validate_model_identity_capability(
        snapshot,
        protocol,
        adapter_location_root,
        provider_root=provider_root,
        model_root=model_root,
        model_revision_root=model_revision_root,
    )
    roots = {
        "context": descriptor_id + ":context-limit",
        "version": descriptor_id + ":version",
        "digest": descriptor_id + ":digest",
    }
    terminals = (
        _terminal(roots["context"], context_limit),
        _terminal(roots["version"], version),
        _terminal(roots["digest"], ""),
    )
    relation = compose_relation_cells(
        (
            (protocol.role("descriptor-definition"), definitions.model_descriptor_root),
            (protocol.role("descriptor-provider"), provider_root),
            (protocol.role("descriptor-model"), model_root),
            (protocol.role("descriptor-model-revision"), model_revision_root),
            (protocol.role("descriptor-input-contract"), input_contract_root),
            (protocol.role("descriptor-output-definition"), output_definition_root),
            *((protocol.role("descriptor-modality"), root) for root in modalities),
            (protocol.role("descriptor-context-limit"), roots["context"]),
            *((protocol.role("descriptor-data-policy"), root) for root in policies),
            *((protocol.role("descriptor-evidence"), root) for root in evidence),
            (protocol.role("descriptor-version"), roots["version"]),
            (protocol.role("descriptor-budget"), budget_root),
            (protocol.role("descriptor-adapter-action"), adapter_action_root),
            (protocol.role("descriptor-adapter-location"), adapter_location_root),
            (protocol.role("descriptor-adapter-datatype"), adapter_datatype_root),
            (protocol.role("descriptor-reviewer"), reviewer_root),
            (protocol.role("descriptor-lifecycle"), protocol.state("draft")),
            (protocol.role("descriptor-digest"), roots["digest"]),
        ),
        relation_id=descriptor_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("descriptor"),
        protocol.role("descriptor-member"),
        descriptor_id,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (*terminals, *relation.cells, *append.create),
        "model descriptor",
    )
    store.commit(
        snapshot.revision,
        create=created,
        replace=append.replace,
    )
    return read_model_descriptor(
        store.snapshot(),
        assembly,
        catalog_root,
        protocol,
        definitions,
        descriptor_id,
        require_released=False,
    )


def read_model_descriptor(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    descriptor_root: str,
    *,
    require_released: bool = True,
) -> ModelDescriptorProjection:
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    registry = read_relation(
        snapshot, protocol.registry("descriptor"), budget=RELATION_BUDGET
    )
    if sum(
        member.participant_id == descriptor_root
        and member.role_id == protocol.role("descriptor-member")
        for member in registry
    ) != 1:
        raise InvalidCell("model descriptor is not registered exactly once")
    _validate_definition_relation(
        snapshot,
        assembly,
        definitions.model_descriptor_root,
        descriptor_root,
    )
    members = read_relation(snapshot, descriptor_root, budget=RELATION_BUDGET)
    allowed = tuple(
        protocol.role(name)
        for name in (
            "descriptor-definition",
            "descriptor-provider",
            "descriptor-model",
            "descriptor-model-revision",
            "descriptor-input-contract",
            "descriptor-output-definition",
            "descriptor-modality",
            "descriptor-context-limit",
            "descriptor-data-policy",
            "descriptor-evidence",
            "descriptor-version",
            "descriptor-budget",
            "descriptor-adapter-action",
            "descriptor-adapter-location",
            "descriptor-adapter-datatype",
            "descriptor-reviewer",
            "descriptor-release-request",
            "descriptor-release-receipt",
            "descriptor-release-revision",
            "descriptor-lifecycle",
            "descriptor-digest",
        )
    )
    _closed_roles(members, allowed, "model descriptor")
    definition_root = _one(
        members, protocol.role("descriptor-definition"), "descriptor definition"
    )
    if definition_root != definitions.model_descriptor_root:
        raise InvalidCell("model descriptor uses another definition")
    output_definition = _one(
        members,
        protocol.role("descriptor-output-definition"),
        "descriptor output definition",
    )
    if output_definition != definitions.proposal_root:
        raise InvalidCell("model descriptor output is not Proposal")
    modalities = _unique(
        _for_role(members, protocol.role("descriptor-modality")),
        "model descriptor modalities",
        limit=MAX_MODALITIES,
    )
    policies = _unique(
        _for_role(members, protocol.role("descriptor-data-policy")),
        "model descriptor data policies",
        limit=MAX_DATA_POLICIES,
    )
    evidence = _unique(
        _for_role(members, protocol.role("descriptor-evidence")),
        "model descriptor evidence",
        limit=MAX_EVIDENCE,
    )
    if not modalities or not policies or not evidence:
        raise InvalidCell("model descriptor lacks required bounds")
    lifecycle = _one(
        members, protocol.role("descriptor-lifecycle"), "descriptor lifecycle"
    )
    release_root = _optional(
        members,
        protocol.role("descriptor-release-revision"),
        "descriptor release revision",
    )
    release_revision = (
        _integer(snapshot, release_root, "descriptor release revision")
        if release_root is not None
        else None
    )
    release_request_root = _optional(
        members,
        protocol.role("descriptor-release-request"),
        "descriptor release request",
    )
    release_receipt_root = _optional(
        members,
        protocol.role("descriptor-release-receipt"),
        "descriptor release receipt",
    )
    release_policy_root = None
    release_action_root = None
    release_rule_roots: tuple[str, ...] = ()
    release_reason = None
    release_source_revision = None
    if release_request_root is not None:
        request_members = read_relation(
            snapshot, release_request_root, budget=RELATION_BUDGET
        )
        request_roles = tuple(
            protocol.role(name)
            for name in (
                "release-request-descriptor",
                "release-request-reviewer",
                "release-request-source-revision",
                "release-request-policy",
                "release-request-action",
                "release-request-rule",
                "release-request-reason",
            )
        )
        _closed_roles(request_members, request_roles, "descriptor release request")
        if _one(
            request_members,
            protocol.role("release-request-descriptor"),
            "release request descriptor",
        ) != descriptor_root:
            raise InvalidCell("descriptor release request points elsewhere")
        if _one(
            request_members,
            protocol.role("release-request-reviewer"),
            "release request reviewer",
        ) != _one(
            members, protocol.role("descriptor-reviewer"), "descriptor reviewer"
        ):
            raise InvalidCell("descriptor release reviewer drifted")
        release_source_revision = _integer(
            snapshot,
            _one(
                request_members,
                protocol.role("release-request-source-revision"),
                "release request source revision",
            ),
            "release request source revision",
        )
        release_policy_root = _one(
            request_members,
            protocol.role("release-request-policy"),
            "release request policy",
        )
        release_action_root = _one(
            request_members,
            protocol.role("release-request-action"),
            "release request action",
        )
        release_rule_roots = _unique(
            _for_role(request_members, protocol.role("release-request-rule")),
            "release request rules",
            limit=256,
        )
        release_reason = _text(
            snapshot,
            _one(
                request_members,
                protocol.role("release-request-reason"),
                "release request reason",
            ),
            "release request reason",
        )
    if lifecycle == protocol.state("draft"):
        if require_released:
            raise InvalidCell("model descriptor is not released")
        if any(value is not None for value in (
            release_revision, release_request_root, release_receipt_root
        )):
            raise InvalidCell("draft model descriptor contains release evidence")
    elif lifecycle == protocol.state("released"):
        if (
            release_revision is None
            or release_request_root is None
            or release_receipt_root is None
            or release_source_revision is None
            or release_source_revision + 1 != release_revision
            or release_revision > snapshot.revision
        ):
            raise InvalidCell("released model descriptor lacks valid release evidence")
    else:
        raise InvalidCell("model descriptor lifecycle is invalid")
    context_root = _one(
        members,
        protocol.role("descriptor-context-limit"),
        "descriptor context limit",
    )
    version_root = _one(
        members, protocol.role("descriptor-version"), "descriptor version"
    )
    digest_root = _one(
        members, protocol.role("descriptor-digest"), "descriptor digest"
    )
    budget_root = _one(
        members, protocol.role("descriptor-budget"), "descriptor budget"
    )
    budget = read_cognition_budget(snapshot, protocol, budget_root)
    context_limit = _integer(snapshot, context_root, "descriptor context limit")
    if context_limit < 1 or context_limit > budget.max_context_entries:
        raise InvalidCell("model descriptor context limit exceeds its budget")
    descriptor = ModelDescriptorProjection(
        descriptor_root,
        definition_root,
        _one(members, protocol.role("descriptor-provider"), "descriptor provider"),
        _one(members, protocol.role("descriptor-model"), "descriptor model"),
        _one(
            members,
            protocol.role("descriptor-model-revision"),
            "descriptor model revision",
        ),
        _one(
            members,
            protocol.role("descriptor-input-contract"),
            "descriptor input contract",
        ),
        output_definition,
        modalities,
        context_limit,
        policies,
        evidence,
        _text(snapshot, version_root, "descriptor version"),
        budget_root,
        _one(
            members,
            protocol.role("descriptor-adapter-action"),
            "descriptor adapter action",
        ),
        _one(
            members,
            protocol.role("descriptor-adapter-location"),
            "descriptor adapter location",
        ),
        _one(
            members,
            protocol.role("descriptor-adapter-datatype"),
            "descriptor adapter datatype",
        ),
        _one(
            members, protocol.role("descriptor-reviewer"), "descriptor reviewer"
        ),
        release_request_root,
        release_receipt_root,
        release_policy_root,
        release_action_root,
        release_rule_roots,
        release_reason,
        release_revision,
        lifecycle,
        digest_root,
        _text(snapshot, digest_root, "descriptor digest"),
    )
    _ensure(
        snapshot,
        (
            descriptor.provider_root,
            descriptor.model_root,
            descriptor.model_revision_root,
            descriptor.input_contract_root,
            *descriptor.modality_roots,
            *descriptor.data_policy_roots,
            *descriptor.evidence_roots,
            descriptor.adapter_action_root,
            descriptor.adapter_location_root,
            descriptor.adapter_datatype_root,
            descriptor.reviewer_root,
        ),
        "model descriptor",
    )
    _validate_model_identity_capability(
        snapshot,
        protocol,
        descriptor.adapter_location_root,
        provider_root=descriptor.provider_root,
        model_root=descriptor.model_root,
        model_revision_root=descriptor.model_revision_root,
    )
    if lifecycle == protocol.state("released"):
        actual = _descriptor_digest(snapshot, protocol, descriptor)
        if not descriptor.digest or not hmac.compare_digest(descriptor.digest, actual):
            raise InvalidCell("released model descriptor has drifted")
        assert_subject_usable(
            snapshot,
            _status_protocol(snapshot, definitions),
            descriptor.root_id,
            descriptor.digest,
        )
    elif descriptor.digest:
        raise InvalidCell("draft model descriptor contains a digest")
    return descriptor


def release_model_descriptor(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    release_request: AuthorizationRequest,
    descriptor_root: str,
    *,
    reviewer_root: str,
    policy_root: str,
    resolver_state: object | None = None,
) -> str:
    snapshot = store.snapshot()
    descriptor = read_model_descriptor(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        descriptor_root,
        require_released=False,
    )
    if descriptor.lifecycle_root != protocol.state("draft"):
        raise InvalidCell("only a draft model descriptor can be released")
    if descriptor.reviewer_root != reviewer_root:
        raise AuthorizationDenied("model descriptor reviewer does not match")
    if (
        release_request.object_root != descriptor_root
        or release_request.action_root not in authorization.actions.values()
    ):
        raise AuthorizationDenied("descriptor release request is not exact")
    policy = verify_authorization_policy(snapshot, authorization, policy_root)
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        policy.root_id,
        authentication_broker,
        authentication_context,
        (release_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    if (
        not decision.allowed
        or decision.subject_root != reviewer_root
        or decision.policy_root != policy.root_id
        or decision.object_root != descriptor_root
        or decision.action_root != release_request.action_root
        or decision.reason != "explicit-permit"
        or not decision.determining_rule_roots
        or not set(decision.determining_rule_roots).issubset(policy.rule_roots)
    ):
        raise AuthorizationDenied("descriptor release was not explicitly authorised")
    determining_object = _determining_rule_object(
        snapshot,
        authorization,
        decision.determining_rule_roots,
        (descriptor_root, *release_request.resource_lineage_roots),
        "descriptor release",
    )
    for rule_root in decision.determining_rule_roots:
        rule = read_authorization_rule(snapshot, authorization, rule_root)
        if (
            rule.effect_root != authorization.effects["permit"]
            or rule.action_root != release_request.action_root
            or rule.object_root != determining_object
            or rule.interface_root != release_request.interface_root
            or rule.purpose_root != release_request.purpose_root
            or rule.classification_root != release_request.classification_root
            or rule.audience_root != release_request.audience_root
            or rule.lifecycle_state_root != release_request.lifecycle_state_root
            or rule.operational_state_root != release_request.operational_state_root
        ):
            raise AuthorizationDenied("descriptor release rule is not exact")
    release_revision = snapshot.revision + 1
    release_root = descriptor_root + ":release-revision"
    release_request_root = descriptor_root + ":release-request"
    release_receipt_root = descriptor_root + ":release-receipt"
    source_revision_root = release_request_root + ":source-revision"
    reason_root = release_request_root + ":reason"
    request_relation = compose_relation_cells(
        (
            (protocol.role("release-request-descriptor"), descriptor_root),
            (protocol.role("release-request-reviewer"), reviewer_root),
            (
                protocol.role("release-request-source-revision"),
                source_revision_root,
            ),
            (protocol.role("release-request-policy"), decision.policy_root),
            (protocol.role("release-request-action"), decision.action_root),
            *(
                (protocol.role("release-request-rule"), root)
                for root in decision.determining_rule_roots
            ),
            (protocol.role("release-request-reason"), reason_root),
        ),
        relation_id=release_request_root,
    )
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        agent_protocol,
        authorization,
        evaluation,
        0,
        receipt_id=release_receipt_root,
    )
    append = prepare_append_relation_members(
        snapshot,
        descriptor_root,
        (
            (protocol.role("descriptor-release-request"), release_request_root),
            (protocol.role("descriptor-release-receipt"), release_receipt_root),
            (protocol.role("descriptor-release-revision"), release_root),
        ),
        budget=RELATION_BUDGET,
    )
    released = ModelDescriptorProjection(
        descriptor.root_id,
        descriptor.definition_root,
        descriptor.provider_root,
        descriptor.model_root,
        descriptor.model_revision_root,
        descriptor.input_contract_root,
        descriptor.output_definition_root,
        descriptor.modality_roots,
        descriptor.context_limit,
        descriptor.data_policy_roots,
        descriptor.evidence_roots,
        descriptor.version,
        descriptor.budget_root,
        descriptor.adapter_action_root,
        descriptor.adapter_location_root,
        descriptor.adapter_datatype_root,
        descriptor.reviewer_root,
        release_request_root,
        release_receipt_root,
        decision.policy_root,
        decision.action_root,
        tuple(decision.determining_rule_roots),
        decision.reason,
        release_revision,
        protocol.state("released"),
        descriptor.digest_root,
        "",
    )
    digest = _descriptor_digest(snapshot, protocol, released)
    members = read_relation(snapshot, descriptor_root, budget=RELATION_BUDGET)
    lifecycle_member = next(
        member
        for member in members
        if member.role_id == protocol.role("descriptor-lifecycle")
    )
    lifecycle_cell = snapshot.cells[lifecycle_member.incidence_id]
    digest_cell = snapshot.cells[descriptor.digest_root]
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=(
            _terminal(release_root, release_revision),
            _terminal(source_revision_root, snapshot.revision),
            _terminal(reason_root, decision.reason),
            *receipt_cells,
            *request_relation.cells,
            *append.create,
        ),
        replace=(
            *append.replace,
            Cell(
                lifecycle_cell.id,
                lifecycle_cell.link0,
                protocol.state("released"),
                lifecycle_cell.atom,
            ),
            Cell(
                digest_cell.id,
                digest_cell.link0,
                digest_cell.link1,
                digest.encode("ascii"),
            ),
        ),
    )
    released_descriptor = read_model_descriptor(
        store.snapshot(),
        assembly,
        catalog_root,
        protocol,
        definitions,
        descriptor_root,
    )
    receipt = _verify_authorization_receipt_integrity(
        store.snapshot(),
        agent_protocol,
        authorization,
        release_receipt_root,
    )
    if (
        receipt.revision + 1 != released_descriptor.release_revision
        or receipt.subject_root != reviewer_root
        or receipt.policy_root != released_descriptor.release_policy_root
        or receipt.action_root != released_descriptor.release_action_root
        or receipt.object_root != descriptor_root
        or receipt.rule_roots != released_descriptor.release_rule_roots
        or receipt.reason != released_descriptor.release_reason
    ):
        raise InvalidCell("descriptor release evidence drifted")
    return digest


def revoke_model_descriptor(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    revocation_request: AuthorizationRequest,
    descriptor_root: str,
    *,
    reviewer_root: str,
    policy_root: str,
    resolver_state: object | None = None,
) -> StatusEventProjection:
    """Append one irreversible, authenticated status event for a descriptor."""
    snapshot = store.snapshot()
    descriptor = read_model_descriptor(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        descriptor_root,
    )
    if descriptor.reviewer_root != reviewer_root:
        raise AuthorizationDenied("model descriptor reviewer does not match")
    if (
        revocation_request.object_root != descriptor_root
        or revocation_request.action_root not in authorization.actions.values()
    ):
        raise AuthorizationDenied("descriptor revocation request is not exact")
    policy = verify_authorization_policy(snapshot, authorization, policy_root)
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        policy.root_id,
        authentication_broker,
        authentication_context,
        (revocation_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    if (
        not decision.allowed
        or decision.subject_root != reviewer_root
        or decision.policy_root != policy.root_id
        or decision.object_root != descriptor_root
        or decision.action_root != revocation_request.action_root
        or decision.reason != "explicit-permit"
        or not decision.determining_rule_roots
        or not set(decision.determining_rule_roots).issubset(policy.rule_roots)
    ):
        raise AuthorizationDenied(
            "descriptor revocation was not explicitly authorised"
        )
    determining_object = _determining_rule_object(
        snapshot,
        authorization,
        decision.determining_rule_roots,
        (descriptor_root, *revocation_request.resource_lineage_roots),
        "descriptor revocation",
    )
    for rule_root in decision.determining_rule_roots:
        rule = read_authorization_rule(snapshot, authorization, rule_root)
        if (
            rule.effect_root != authorization.effects["permit"]
            or rule.action_root != revocation_request.action_root
            or rule.object_root != determining_object
            or rule.interface_root != revocation_request.interface_root
            or rule.purpose_root != revocation_request.purpose_root
            or rule.classification_root != revocation_request.classification_root
            or rule.audience_root != revocation_request.audience_root
            or rule.lifecycle_state_root != revocation_request.lifecycle_state_root
            or rule.operational_state_root
            != revocation_request.operational_state_root
        ):
            raise AuthorizationDenied("descriptor revocation rule is not exact")
    event_root = descriptor_root + ":status:revoked"
    receipt_root = event_root + ":authorization-receipt"
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        agent_protocol,
        authorization,
        evaluation,
        0,
        receipt_id=receipt_root,
    )
    status = _status_protocol(snapshot, definitions)
    patch = prepare_status_event(
        snapshot,
        status,
        event_id=event_root,
        subject_root=descriptor.root_id,
        subject_digest=descriptor.digest,
        state_root=status.state("revoked"),
        actor_root=reviewer_root,
        policy_root=decision.policy_root,
        action_root=decision.action_root,
        rule_roots=decision.determining_rule_roots,
        reason=decision.reason,
        authorization_receipt_root=receipt_root,
        pending_evidence_cells=receipt_cells,
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=(*receipt_cells, *patch.create),
        replace=patch.replace,
    )
    committed = store.snapshot()
    event = read_status_event(committed, status, event_root)
    receipt = _verify_authorization_receipt_integrity(
        committed,
        agent_protocol,
        authorization,
        receipt_root,
    )
    if (
        receipt.revision + 1 != event.created_revision
        or receipt.subject_root != event.actor_root
        or receipt.policy_root != event.policy_root
        or receipt.action_root != event.action_root
        or receipt.object_root != event.subject_root
        or receipt.rule_roots != event.rule_roots
        or receipt.reason != event.reason
        or event.subject_digest != descriptor.digest
    ):
        raise InvalidCell("descriptor revocation evidence drifted")
    return event


def _binding_digest(
    snapshot: Snapshot,
    protocol: AgentCognitionProtocol,
    binding: ModelBindingProjection,
) -> str:
    digest = hashlib.blake2b(digest_size=32)
    budget = read_cognition_budget(snapshot, protocol, binding.budget_root)
    values = (
        binding.root_id,
        binding.definition_root,
        binding.body_root,
        binding.descriptor_root,
        binding.descriptor_digest,
        binding.adapter_root,
        binding.adapter_catalog_root,
        *binding.policy_roots,
        binding.budget_root,
        str(budget.max_context_entries),
        str(budget.max_input_bytes),
        str(budget.max_output_bytes),
        str(budget.max_latency_ms),
        str(budget.max_cost_microunits),
        str(binding.creation_revision),
        binding.action_root,
        *binding.rule_roots,
        binding.authorization_reason,
        binding.authorization_receipt_root,
        binding.lifecycle_root,
    )
    for value in values:
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def read_model_binding(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    binding_root: str,
) -> ModelBindingProjection:
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    registry = read_relation(
        snapshot, protocol.registry("binding"), budget=RELATION_BUDGET
    )
    if sum(
        member.role_id == protocol.role("binding-member")
        and member.participant_id == binding_root
        for member in registry
    ) != 1:
        raise InvalidCell("model binding is not registered exactly once")
    _validate_definition_relation(
        snapshot,
        assembly,
        definitions.model_binding_root,
        binding_root,
    )
    members = read_relation(snapshot, binding_root, budget=RELATION_BUDGET)
    role_names = (
        "binding-definition",
        "binding-body",
        "binding-descriptor",
        "binding-descriptor-digest",
        "binding-adapter",
        "binding-adapter-catalog",
        "binding-policy",
        "binding-budget",
        "binding-creation-revision",
        "binding-action",
        "binding-rule",
        "binding-authorization-reason",
        "binding-authorization-receipt",
        "binding-lifecycle",
        "binding-digest",
    )
    _closed_roles(
        members, (protocol.role(name) for name in role_names), "model binding"
    )
    definition = _one(
        members, protocol.role("binding-definition"), "binding definition"
    )
    if definition != definitions.model_binding_root:
        raise InvalidCell("model binding uses another definition")
    descriptor_root = _one(
        members, protocol.role("binding-descriptor"), "binding descriptor"
    )
    descriptor = read_model_descriptor(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        descriptor_root,
    )
    if (
        descriptor.release_receipt_root is None
        or descriptor.release_revision is None
    ):
        raise InvalidCell("model binding descriptor lacks release evidence")
    descriptor_release = _verify_authorization_receipt_integrity(
        snapshot,
        agent_protocol,
        authorization,
        descriptor.release_receipt_root,
    )
    if (
        descriptor_release.revision + 1 != descriptor.release_revision
        or descriptor_release.subject_root != descriptor.reviewer_root
        or descriptor_release.policy_root != descriptor.release_policy_root
        or descriptor_release.action_root != descriptor.release_action_root
        or descriptor_release.object_root != descriptor.root_id
        or descriptor_release.rule_roots != descriptor.release_rule_roots
        or descriptor_release.reason != descriptor.release_reason
    ):
        raise InvalidCell("model descriptor release evidence drifted")
    descriptor_digest_root = _one(
        members,
        protocol.role("binding-descriptor-digest"),
        "binding descriptor digest",
    )
    descriptor_digest = _text(
        snapshot, descriptor_digest_root, "binding descriptor digest"
    )
    if not hmac.compare_digest(descriptor_digest, descriptor.digest):
        raise InvalidCell("model binding descriptor digest drifted")
    catalog = verify_adapter_catalog(snapshot, adapter_protocol, adapter_catalog_root)
    bound_catalog = _one(
        members,
        protocol.role("binding-adapter-catalog"),
        "binding adapter catalogue",
    )
    if bound_catalog != adapter_catalog_root:
        raise InvalidCell("model binding points to another adapter catalogue")
    adapter_root = _one(
        members, protocol.role("binding-adapter"), "binding adapter"
    )
    if adapter_root not in catalog.adapter_roots:
        raise InvalidCell("model binding adapter is outside the allowlist")
    adapter = verify_released_adapter(snapshot, adapter_protocol, adapter_root)
    if (
        descriptor.adapter_action_root not in adapter.action_roots
        or descriptor.adapter_location_root not in adapter.location_roots
        or descriptor.adapter_datatype_root not in adapter.datatype_roots
    ):
        raise InvalidCell("model binding exceeds adapter bounds")
    budget_root = _one(
        members, protocol.role("binding-budget"), "binding budget"
    )
    if budget_root != descriptor.budget_root:
        raise InvalidCell("model binding budget differs from its descriptor")
    read_cognition_budget(snapshot, protocol, budget_root)
    policies = _unique(
        _for_role(members, protocol.role("binding-policy")),
        "model binding policies",
        limit=MAX_POLICIES,
    )
    if not policies:
        raise InvalidCell("model binding has no policy")
    _ensure(snapshot, policies, "model binding policies")
    creation_root = _one(
        members,
        protocol.role("binding-creation-revision"),
        "binding creation revision",
    )
    reason_root = _one(
        members,
        protocol.role("binding-authorization-reason"),
        "binding authorization reason",
    )
    digest_root = _one(
        members, protocol.role("binding-digest"), "binding digest"
    )
    binding = ModelBindingProjection(
        binding_root,
        definition,
        _one(members, protocol.role("binding-body"), "binding body"),
        descriptor_root,
        descriptor_digest,
        adapter_root,
        bound_catalog,
        policies,
        budget_root,
        _integer(snapshot, creation_root, "binding creation revision"),
        _one(members, protocol.role("binding-action"), "binding action"),
        _unique(
            _for_role(members, protocol.role("binding-rule")),
            "model binding rules",
            limit=256,
        ),
        _text(snapshot, reason_root, "binding authorization reason"),
        _one(
            members,
            protocol.role("binding-authorization-receipt"),
            "binding authorization receipt",
        ),
        _one(members, protocol.role("binding-lifecycle"), "binding lifecycle"),
        digest_root,
        _text(snapshot, digest_root, "binding digest"),
    )
    if binding.creation_revision < 1 or binding.creation_revision > snapshot.revision:
        raise InvalidCell("model binding creation revision is invalid")
    if binding.lifecycle_root != protocol.state("active"):
        raise InvalidCell("model binding is not active")
    body_members = read_relation(snapshot, binding.body_root, budget=RELATION_BUDGET)
    body_identity = _one(
        body_members,
        agent_protocol.role("body-identity"),
        "model binding body identity",
    )
    receipt = _verify_authorization_receipt_integrity(
        snapshot,
        agent_protocol,
        authorization,
        binding.authorization_receipt_root,
    )
    if (
        receipt.revision + 1 != binding.creation_revision
        or receipt.subject_root != body_identity
        or receipt.policy_root not in binding.policy_roots
        or receipt.action_root != binding.action_root
        or receipt.object_root != binding.body_root
        or receipt.rule_roots != binding.rule_roots
        or receipt.reason != binding.authorization_reason
    ):
        raise InvalidCell("model binding authorization evidence drifted")
    actual = _binding_digest(snapshot, protocol, binding)
    if not binding.digest or not hmac.compare_digest(binding.digest, actual):
        raise InvalidCell("model binding has drifted")
    return binding


def make_model_binding_verifier(
    protocol: AgentCognitionProtocol,
    assembly: AssemblyProtocol,
    catalog_root: str,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
):
    def verify(snapshot: Snapshot, binding_root: str, body_root: str):
        binding = read_model_binding(
            snapshot,
            assembly,
            catalog_root,
            protocol,
            definitions,
            adapter_protocol,
            adapter_catalog_root,
            agent_protocol,
            authorization,
            binding_root,
        )
        if binding.body_root != body_root:
            raise InvalidCell("model binding belongs to another Agent Body")
        return binding

    return verify


def bind_agent_body_model(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    binding_request: AuthorizationRequest,
    *,
    binding_id: str,
    body_root: str,
    descriptor_root: str,
    adapter_root: str,
    policy_roots: Iterable[str],
    budget_root: str,
    resolver_state: object | None = None,
) -> ModelBindingProjection:
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    verifier = make_model_binding_verifier(
        protocol,
        assembly,
        catalog_root,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
    )
    body = read_agent_body(
        snapshot,
        agent_protocol,
        authorization,
        body_root,
        model_binding_verifier=verifier,
    )
    descriptor = read_model_descriptor(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        descriptor_root,
    )
    catalog = verify_adapter_catalog(
        snapshot, adapter_protocol, adapter_catalog_root
    )
    if adapter_root not in catalog.adapter_roots:
        raise InvalidCell("model adapter is outside the released allowlist")
    adapter = verify_released_adapter(snapshot, adapter_protocol, adapter_root)
    if (
        descriptor.adapter_action_root not in adapter.action_roots
        or descriptor.adapter_location_root not in adapter.location_roots
        or descriptor.adapter_datatype_root not in adapter.datatype_roots
    ):
        raise InvalidCell("model adapter does not satisfy descriptor bounds")
    if budget_root != descriptor.budget_root:
        raise InvalidCell("model binding budget differs from descriptor")
    read_cognition_budget(snapshot, protocol, budget_root)
    policies = _unique(
        policy_roots, "model binding policies", limit=MAX_POLICIES
    )
    if not policies:
        raise InvalidCell("model binding requires at least one policy")
    _ensure(snapshot, policies, "model binding policies")
    if binding_id in snapshot.cells:
        raise InvalidCell("model binding root already exists")
    _require_request_binding(
        binding_request,
        object_root=body_root,
        action_roots=body.authority_action_roots,
        lineage_roots=tuple(binding_request.resource_lineage_roots),
        interface_root=binding_request.interface_root,
        audience_root=body.visibility_root,
        classification_root=binding_request.classification_root,
        lifecycle_root=body.lifecycle_root,
        purpose_root=binding_request.purpose_root,
        operational_root=agent_protocol.state("active"),
        label="agent model binding request",
    )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        (binding_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    determining_object = _determining_rule_object(
        snapshot,
        authorization,
        decision.determining_rule_roots,
        (body_root, *binding_request.resource_lineage_roots),
        "agent model binding",
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        decision,
        expected_object_root=body_root,
        expected_rule_object_root=determining_object,
        expected_interface_root=binding_request.interface_root,
        expected_purpose_root=binding_request.purpose_root,
        expected_classification_root=binding_request.classification_root,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=agent_protocol.state("active"),
        label="agent model binding",
    )
    creation_revision = snapshot.revision + 1
    roots = {
        "descriptor-digest": binding_id + ":descriptor-digest",
        "creation-revision": binding_id + ":creation-revision",
        "reason": binding_id + ":authorization-reason",
        "receipt": binding_id + ":authorization-receipt",
        "digest": binding_id + ":digest",
    }
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        agent_protocol,
        authorization,
        evaluation,
        0,
        receipt_id=roots["receipt"],
    )
    provisional = ModelBindingProjection(
        binding_id,
        definitions.model_binding_root,
        body_root,
        descriptor_root,
        descriptor.digest,
        adapter_root,
        adapter_catalog_root,
        policies,
        budget_root,
        creation_revision,
        decision.action_root,
        decision.determining_rule_roots,
        decision.reason,
        roots["receipt"],
        protocol.state("active"),
        roots["digest"],
        "",
    )
    digest = _binding_digest(snapshot, protocol, provisional)
    terminals = (
        _terminal(roots["descriptor-digest"], descriptor.digest),
        _terminal(roots["creation-revision"], creation_revision),
        _terminal(roots["reason"], decision.reason),
        _terminal(roots["digest"], digest),
    )
    relation = compose_relation_cells(
        (
            (protocol.role("binding-definition"), definitions.model_binding_root),
            (protocol.role("binding-body"), body_root),
            (protocol.role("binding-descriptor"), descriptor_root),
            (protocol.role("binding-descriptor-digest"), roots["descriptor-digest"]),
            (protocol.role("binding-adapter"), adapter_root),
            (protocol.role("binding-adapter-catalog"), adapter_catalog_root),
            *((protocol.role("binding-policy"), root) for root in policies),
            (protocol.role("binding-budget"), budget_root),
            (protocol.role("binding-creation-revision"), roots["creation-revision"]),
            (protocol.role("binding-action"), decision.action_root),
            *((protocol.role("binding-rule"), root) for root in decision.determining_rule_roots),
            (protocol.role("binding-authorization-reason"), roots["reason"]),
            (protocol.role("binding-authorization-receipt"), roots["receipt"]),
            (protocol.role("binding-lifecycle"), protocol.state("active")),
            (protocol.role("binding-digest"), roots["digest"]),
        ),
        relation_id=binding_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("binding"),
        protocol.role("binding-member"),
        binding_id,
        budget=RELATION_BUDGET,
    )
    body_members = read_relation(snapshot, body_root, budget=RELATION_BUDGET)
    binding_members = tuple(
        member for member in body_members
        if member.role_id == agent_protocol.role("body-model-binding")
    )
    if len(binding_members) != 1:
        raise InvalidCell("Agent Body has no unique model-binding incidence")
    binding_incidence = snapshot.cells[binding_members[0].incidence_id]
    created = _assert_creates(
        snapshot,
        (*terminals, *receipt_cells, *relation.cells, *append.create),
        "model binding",
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=(
            *append.replace,
            Cell(
                binding_incidence.id,
                binding_incidence.link0,
                binding_id,
                binding_incidence.atom,
            ),
        ),
    )
    return read_model_binding(
        store.snapshot(),
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        binding_id,
    )


def _session_cognition_root(session_root: str) -> str:
    return session_root + ":cognition"


def _session_request_registry_root(session_root: str) -> str:
    return session_root + ":cognition-request-registry"


def _read_session_cognition(
    store: CellStore,
    protocol: AgentCognitionProtocol,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    session_root: str,
) -> SessionCognitionProjection:
    snapshot = store.snapshot()
    root = _session_cognition_root(session_root)
    registry = read_relation(
        snapshot, protocol.registry("session"), budget=RELATION_BUDGET
    )
    if sum(
        member.role_id == protocol.role("session-cognition-member")
        and member.participant_id == root
        for member in registry
    ) != 1:
        raise InvalidCell("session cognition is not registered exactly once")
    members = read_relation(snapshot, root, budget=RELATION_BUDGET)
    role_names = (
        "session-cognition-session",
        "session-cognition-request-registry",
        "session-cognition-creation-revision",
        "session-cognition-action",
        "session-cognition-policy",
        "session-cognition-rule",
        "session-cognition-reason",
        "session-cognition-receipt",
    )
    _closed_roles(
        members, (protocol.role(name) for name in role_names), "session cognition"
    )
    projected_session = _one(
        members,
        protocol.role("session-cognition-session"),
        "session cognition session",
    )
    if projected_session != session_root:
        raise InvalidCell("session cognition points to another session")
    request_registry = _one(
        members,
        protocol.role("session-cognition-request-registry"),
        "session cognition request registry",
    )
    if request_registry != _session_request_registry_root(session_root):
        raise InvalidCell("session cognition request registry is not canonical")
    request_members = read_relation(
        snapshot, request_registry, budget=RELATION_BUDGET
    )
    if any(
        member.role_id != protocol.role("request-member")
        for member in request_members
    ):
        raise InvalidCell("session request registry contains an undeclared role")
    request_roots = tuple(member.participant_id for member in request_members)
    if (
        len(request_roots) != len(set(request_roots))
        or len(request_roots) > MAX_CONTEXT_ENTRIES
    ):
        raise InvalidCell("session request registry is invalid")
    reason_root = _one(
        members, protocol.role("session-cognition-reason"), "session cognition reason"
    )
    projection = SessionCognitionProjection(
        root,
        session_root,
        request_registry,
        _integer(
            snapshot,
            _one(
                members,
                protocol.role("session-cognition-creation-revision"),
                "session cognition creation revision",
            ),
            "session cognition creation revision",
        ),
        _one(
            members,
            protocol.role("session-cognition-action"),
            "session cognition action",
        ),
        _one(
            members,
            protocol.role("session-cognition-policy"),
            "session cognition policy",
        ),
        _unique(
            _for_role(members, protocol.role("session-cognition-rule")),
            "session cognition rules",
            limit=256,
        ),
        _text(snapshot, reason_root, "session cognition reason"),
        _one(
            members,
            protocol.role("session-cognition-receipt"),
            "session cognition receipt",
        ),
    )
    receipt = _verify_authorization_receipt_integrity(
        snapshot,
        agent_protocol,
        authorization,
        projection.authorization_receipt_root,
    )
    session_members = read_relation(
        snapshot, session_root, budget=RELATION_BUDGET
    )
    session_subject = _one(
        session_members,
        agent_protocol.role("session-subject"),
        "session cognition subject",
    )
    if (
        projection.creation_revision != store.cell_created_revision(root)
        or receipt.revision + 1 != projection.creation_revision
        or store.cell_created_revision(projection.authorization_receipt_root)
        != projection.creation_revision
        or receipt.subject_root != session_subject
        or receipt.policy_root != projection.policy_root
        or receipt.action_root != projection.action_root
        or receipt.object_root != session_root
        or receipt.rule_roots != projection.rule_roots
        or receipt.reason != projection.authorization_reason
    ):
        raise InvalidCell("session cognition authorization evidence drifted")
    return projection


def provision_session_cognition(
    store: CellStore,
    protocol: AgentCognitionProtocol,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    provision_request: AuthorizationRequest,
    *,
    session_root: str,
    model_binding_verifier,
    proposal_verifier=None,
    resolver_state: object | None = None,
) -> SessionCognitionProjection:
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    session = read_agent_session(
        snapshot,
        agent_protocol,
        authorization,
        session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if session.model_binding_root is None:
        raise InvalidCell("session cognition requires a verified model binding")
    root = _session_cognition_root(session_root)
    if root in snapshot.cells:
        return _read_session_cognition(
            store, protocol, agent_protocol, authorization, session_root
        )
    body = read_agent_body(
        snapshot,
        agent_protocol,
        authorization,
        session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    _require_request_binding(
        provision_request,
        object_root=session_root,
        action_roots=body.authority_action_roots,
        lineage_roots=(session.scope_root,),
        interface_root=provision_request.interface_root,
        audience_root=body.visibility_root,
        classification_root=provision_request.classification_root,
        lifecycle_root=body.lifecycle_root,
        purpose_root=provision_request.purpose_root,
        operational_root=agent_protocol.state("active"),
        label="session cognition provision request",
    )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        (provision_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    determining_object = _determining_rule_object(
        snapshot,
        authorization,
        decision.determining_rule_roots,
        (session_root, session.scope_root),
        "session cognition provision",
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        decision,
        expected_object_root=session_root,
        expected_rule_object_root=determining_object,
        expected_interface_root=provision_request.interface_root,
        expected_purpose_root=provision_request.purpose_root,
        expected_classification_root=provision_request.classification_root,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=agent_protocol.state("active"),
        label="session cognition provision",
    )
    request_registry = _session_request_registry_root(session_root)
    creation_root = root + ":creation-revision"
    reason_root = root + ":authorization-reason"
    receipt_root = root + ":authorization-receipt"
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        agent_protocol,
        authorization,
        evaluation,
        0,
        receipt_id=receipt_root,
    )
    registry_relation = compose_relation_cells((), relation_id=request_registry)
    cognition_relation = compose_relation_cells(
        (
            (protocol.role("session-cognition-session"), session_root),
            (
                protocol.role("session-cognition-request-registry"),
                request_registry,
            ),
            (
                protocol.role("session-cognition-creation-revision"),
                creation_root,
            ),
            (protocol.role("session-cognition-action"), decision.action_root),
            (protocol.role("session-cognition-policy"), decision.policy_root),
            *((
                protocol.role("session-cognition-rule"), root_id
            ) for root_id in decision.determining_rule_roots),
            (protocol.role("session-cognition-reason"), reason_root),
            (protocol.role("session-cognition-receipt"), receipt_root),
        ),
        relation_id=root,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.registry("session"),
        protocol.role("session-cognition-member"),
        root,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (
            _terminal(reason_root, decision.reason),
            _terminal(creation_root, snapshot.revision + 1),
            *receipt_cells,
            *registry_relation.cells,
            *cognition_relation.cells,
            *append.create,
        ),
        "session cognition",
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=append.replace,
    )
    return _read_session_cognition(
        store, protocol, agent_protocol, authorization, session_root
    )


def _derived_identity(namespace: str, *parts: str) -> str:
    digest = hashlib.blake2b(digest_size=24)
    for value in (namespace, *parts):
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return "%s:%s" % (namespace, digest.hexdigest())


def _request_digest(request: CognitionRequestProjection) -> str:
    digest = hashlib.blake2b(digest_size=32)
    values = (
        request.root_id,
        request.definition_root,
        request.session_root,
        request.binding_root,
        str(request.source_revision),
        request.revision_chain_digest,
        request.context_manifest_root,
        *request.context_entry_roots,
        *request.context_roots,
        request.input_digest,
        str(request.input_bytes),
        request.intent_root,
        request.purpose_root,
        request.output_definition_root,
        request.budget_root,
        request.idempotency_key,
        *request.read_receipt_roots,
        request.registry_receipt_root,
        request.state_root,
    )
    for value in values:
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def create_cognition_request(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    context_requests: Iterable[AuthorizationRequest],
    registry_request: AuthorizationRequest,
    *,
    session_root: str,
    context_entry_roots: Iterable[str],
    intent_root: str,
    purpose_root: str,
    idempotency_key: str,
    model_binding_verifier,
    proposal_verifier=None,
    resolver_state: object | None = None,
) -> CognitionRequestProjection:
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key.encode("utf-8")) > 512
    ):
        raise InvalidCell("cognition request idempotency key is invalid")
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    if proposal_verifier is None:
        proposal_verifier = make_proposal_verifier(
            store,
            assembly,
            catalog_root,
            protocol,
            definitions,
            adapter_protocol,
            adapter_catalog_root,
            agent_protocol,
            authorization,
            model_binding_verifier=model_binding_verifier,
        )
    session = read_agent_session(
        snapshot,
        agent_protocol,
        authorization,
        session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if session.model_binding_root is None:
        raise InvalidCell("cognition request requires a verified model binding")
    body = read_agent_body(
        snapshot,
        agent_protocol,
        authorization,
        session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    binding = read_model_binding(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        session.model_binding_root,
    )
    session_cognition = _read_session_cognition(
        store, protocol, agent_protocol, authorization, session_root
    )
    entries = _unique(
        context_entry_roots,
        "cognition request context entries",
        limit=MAX_CONTEXT_ENTRIES,
    )
    descriptor = read_model_descriptor(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        binding.descriptor_root,
    )
    budget = read_cognition_budget(snapshot, protocol, binding.budget_root)
    if not entries or len(entries) > min(
        descriptor.context_limit, budget.max_context_entries
    ):
        raise InvalidCell("cognition request context exceeds the binding budget")
    requests = tuple(context_requests)
    if len(requests) != len(entries):
        raise InvalidCell("cognition request context authorization is incomplete")
    projected_entries = tuple(
        read_context_entry(
            snapshot,
            agent_protocol,
            authorization,
            root,
            model_binding_verifier=model_binding_verifier,
            proposal_verifier=proposal_verifier,
        )
        for root in entries
    )
    if any(
        entry.session_root != session_root
        or entry.root_id not in session.context_entry_roots
        for entry in projected_entries
    ):
        raise InvalidCell("cognition request includes context from another session")
    if tuple(entry.sequence for entry in projected_entries) != tuple(
        sorted(entry.sequence for entry in projected_entries)
    ):
        raise InvalidCell("cognition request context order is not stable")
    if any(
        entry.sensitivity_root not in descriptor.data_policy_roots
        for entry in projected_entries
    ):
        raise AuthorizationDenied(
            "cognition context is outside the model data policy"
        )
    input_bytes, input_digest = _bounded_regions_summary(
        snapshot,
        tuple(entry.context_root for entry in projected_entries),
        max_bytes=budget.max_input_bytes,
        max_cells=budget.max_context_entries * 64,
        label="cognition input",
    )
    _ensure(snapshot, (intent_root, purpose_root), "cognition request")
    for request, entry in zip(requests, projected_entries):
        _require_request_binding(
            request,
            object_root=entry.context_root,
            action_roots=body.authority_action_roots,
            lineage_roots=(session.scope_root,),
            interface_root=entry.context_interface_root,
            audience_root=entry.audience_root,
            classification_root=entry.sensitivity_root,
            lifecycle_root=entry.lifecycle_root,
            purpose_root=purpose_root,
            operational_root=agent_protocol.state("active"),
            label="cognition context request",
        )
    _require_request_binding(
        registry_request,
        object_root=session_cognition.request_registry_root,
        action_roots=body.authority_action_roots,
        lineage_roots=(session.scope_root,),
        interface_root=registry_request.interface_root,
        audience_root=body.visibility_root,
        classification_root=registry_request.classification_root,
        lifecycle_root=body.lifecycle_root,
        purpose_root=purpose_root,
        operational_root=agent_protocol.state("active"),
        label="cognition request registry mutation",
    )
    evaluated_requests = (*requests, registry_request)
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        evaluated_requests,
        resolver_state,
    )
    if len(evaluation.decisions) != len(evaluated_requests):
        raise AuthorizationDenied("cognition request authorization was incomplete")
    for decision, request, entry in zip(
        evaluation.decisions[:-1], requests, projected_entries
    ):
        rule_object = _determining_rule_object(
            snapshot,
            authorization,
            decision.determining_rule_roots,
            (entry.context_root, session.scope_root),
            "cognition context",
        )
        _validate_decision(
            snapshot,
            authorization,
            body,
            decision,
            expected_object_root=entry.context_root,
            expected_rule_object_root=rule_object,
            expected_interface_root=entry.context_interface_root,
            expected_purpose_root=purpose_root,
            expected_classification_root=entry.sensitivity_root,
            expected_audience_root=entry.audience_root,
            expected_lifecycle_root=entry.lifecycle_root,
            expected_operational_root=agent_protocol.state("active"),
            label="cognition context",
        )
    registry_decision = evaluation.decisions[-1]
    registry_rule_object = _determining_rule_object(
        snapshot,
        authorization,
        registry_decision.determining_rule_roots,
        (session_cognition.request_registry_root, session.scope_root),
        "cognition request registry",
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        registry_decision,
        expected_object_root=session_cognition.request_registry_root,
        expected_rule_object_root=registry_rule_object,
        expected_interface_root=registry_request.interface_root,
        expected_purpose_root=purpose_root,
        expected_classification_root=registry_request.classification_root,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=agent_protocol.state("active"),
        label="cognition request registry",
    )
    request_id = _derived_identity(
        "cognition-request", session_root, idempotency_key
    )
    if request_id in snapshot.cells:
        existing = read_cognition_request(
            store,
            assembly,
            catalog_root,
            protocol,
            definitions,
            adapter_protocol,
            adapter_catalog_root,
            agent_protocol,
            authorization,
            request_id,
            model_binding_verifier=model_binding_verifier,
            proposal_verifier=proposal_verifier,
        )
        expected = (
            session_root,
            session.model_binding_root,
            entries,
            tuple(entry.context_root for entry in projected_entries),
            intent_root,
            purpose_root,
            binding.budget_root,
            idempotency_key,
        )
        actual = (
            existing.session_root,
            existing.binding_root,
            existing.context_entry_roots,
            existing.context_roots,
            existing.intent_root,
            existing.purpose_root,
            existing.budget_root,
            existing.idempotency_key,
        )
        if actual == expected:
            return existing
        raise InvalidCell(
            "cognition request idempotency key was reused for other content"
        )
    source_revision = snapshot.revision
    source_chain_digest = store.revision_chain_digest(source_revision)
    manifest_root = request_id + ":context-manifest"
    manifest_cells: list[Cell] = []
    manifest_members: list[tuple[str, str]] = []
    for offset, entry in enumerate(projected_entries, 1):
        item_root = "%s:item:%04d" % (manifest_root, offset)
        sequence_root = item_root + ":sequence"
        item = compose_relation_cells(
            (
                (protocol.role("manifest-entry"), entry.root_id),
                (protocol.role("manifest-context-root"), entry.context_root),
                (protocol.role("manifest-sequence"), sequence_root),
            ),
            relation_id=item_root,
        )
        manifest_cells.extend((_terminal(sequence_root, offset), *item.cells))
        manifest_members.append((protocol.role("manifest-member"), item_root))
    manifest = compose_relation_cells(
        manifest_members, relation_id=manifest_root
    )
    manifest_cells.extend(manifest.cells)
    roots = {
        "source-revision": request_id + ":source-revision",
        "source-chain": request_id + ":revision-chain-digest",
        "input-digest": request_id + ":input-digest",
        "input-bytes": request_id + ":input-bytes",
        "idempotency": request_id + ":idempotency",
        "digest": request_id + ":digest",
    }
    read_receipt_roots = tuple(
        "%s:read-receipt:%04d" % (request_id, offset)
        for offset in range(1, len(entries) + 1)
    )
    registry_receipt_root = request_id + ":registry-receipt"
    receipt_cells: list[Cell] = []
    for index, receipt_root in enumerate(
        (*read_receipt_roots, registry_receipt_root)
    ):
        receipt_cells.extend(
            _compose_authorization_receipt(
                snapshot,
                agent_protocol,
                authorization,
                evaluation,
                index,
                receipt_id=receipt_root,
            )
        )
    provisional = CognitionRequestProjection(
        request_id,
        definitions.cognition_request_root,
        session_root,
        session.model_binding_root,
        source_revision,
        source_chain_digest,
        manifest_root,
        entries,
        tuple(entry.context_root for entry in projected_entries),
        input_digest,
        input_bytes,
        intent_root,
        purpose_root,
        definitions.proposal_root,
        binding.budget_root,
        idempotency_key,
        read_receipt_roots,
        registry_receipt_root,
        protocol.state("prepared"),
        roots["digest"],
        "",
    )
    digest = _request_digest(provisional)
    request_relation = compose_relation_cells(
        (
            (protocol.role("request-definition"), definitions.cognition_request_root),
            (protocol.role("request-session"), session_root),
            (protocol.role("request-binding"), session.model_binding_root),
            (protocol.role("request-source-revision"), roots["source-revision"]),
            (protocol.role("request-revision-chain-digest"), roots["source-chain"]),
            (protocol.role("request-context-manifest"), manifest_root),
            (protocol.role("request-input-digest"), roots["input-digest"]),
            (protocol.role("request-input-bytes"), roots["input-bytes"]),
            (protocol.role("request-intent"), intent_root),
            (protocol.role("request-purpose"), purpose_root),
            (protocol.role("request-output-definition"), definitions.proposal_root),
            (protocol.role("request-budget"), binding.budget_root),
            (protocol.role("request-idempotency"), roots["idempotency"]),
            *((protocol.role("request-read-receipt"), root) for root in read_receipt_roots),
            (protocol.role("request-registry-receipt"), registry_receipt_root),
            (protocol.role("request-state"), protocol.state("prepared")),
            (protocol.role("request-digest"), roots["digest"]),
        ),
        relation_id=request_id,
    )
    session_append = prepare_append_relation_member(
        snapshot,
        session_cognition.request_registry_root,
        protocol.role("request-member"),
        request_id,
        budget=RELATION_BUDGET,
    )
    global_append = prepare_append_relation_member(
        snapshot,
        protocol.registry("request"),
        protocol.role("request-member"),
        request_id,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (
            _terminal(roots["source-revision"], source_revision),
            _terminal(roots["source-chain"], source_chain_digest),
            _terminal(roots["input-digest"], input_digest),
            _terminal(roots["input-bytes"], input_bytes),
            _terminal(roots["idempotency"], idempotency_key),
            _terminal(roots["digest"], digest),
            *receipt_cells,
            *manifest_cells,
            *request_relation.cells,
            *session_append.create,
            *global_append.create,
        ),
        "cognition request",
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=(*session_append.replace, *global_append.replace),
    )
    return read_cognition_request(
        store,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        request_id,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )


def read_cognition_request(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    request_root: str,
    *,
    model_binding_verifier,
    proposal_verifier=None,
) -> CognitionRequestProjection:
    snapshot = store.snapshot()
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    global_registry = read_relation(
        snapshot, protocol.registry("request"), budget=RELATION_BUDGET
    )
    if sum(
        member.role_id == protocol.role("request-member")
        and member.participant_id == request_root
        for member in global_registry
    ) != 1:
        raise InvalidCell("cognition request is not globally registered once")
    _validate_definition_relation(
        snapshot,
        assembly,
        definitions.cognition_request_root,
        request_root,
    )
    members = read_relation(snapshot, request_root, budget=RELATION_BUDGET)
    role_names = (
        "request-definition",
        "request-session",
        "request-binding",
        "request-source-revision",
        "request-revision-chain-digest",
        "request-context-manifest",
        "request-input-digest",
        "request-input-bytes",
        "request-intent",
        "request-purpose",
        "request-output-definition",
        "request-budget",
        "request-idempotency",
        "request-read-receipt",
        "request-registry-receipt",
        "request-state",
        "request-digest",
    )
    _closed_roles(
        members, (protocol.role(name) for name in role_names), "cognition request"
    )
    definition = _one(
        members, protocol.role("request-definition"), "request definition"
    )
    if definition != definitions.cognition_request_root:
        raise InvalidCell("cognition request uses another definition")
    output_definition = _one(
        members,
        protocol.role("request-output-definition"),
        "request output definition",
    )
    if output_definition != definitions.proposal_root:
        raise InvalidCell("cognition request output is not Proposal")
    session_root = _one(
        members, protocol.role("request-session"), "request session"
    )
    session_cognition = _read_session_cognition(
        store, protocol, agent_protocol, authorization, session_root
    )
    local_registry = read_relation(
        snapshot,
        session_cognition.request_registry_root,
        budget=RELATION_BUDGET,
    )
    if sum(
        member.role_id == protocol.role("request-member")
        and member.participant_id == request_root
        for member in local_registry
    ) != 1:
        raise InvalidCell("cognition request is not session-registered once")
    source_root = _one(
        members,
        protocol.role("request-source-revision"),
        "request source revision",
    )
    source_revision = _integer(snapshot, source_root, "request source revision")
    if (
        source_revision < 0
        or source_revision >= store.cell_created_revision(request_root)
        or store.cell_created_revision(request_root) != source_revision + 1
    ):
        raise InvalidCell("cognition request creation is not adjacent to its source")
    source = store.at(source_revision)
    chain_root = _one(
        members,
        protocol.role("request-revision-chain-digest"),
        "request revision-chain digest",
    )
    chain_digest = _text(snapshot, chain_root, "request revision-chain digest")
    if not hmac.compare_digest(
        chain_digest, store.revision_chain_digest(source_revision)
    ):
        raise InvalidCell("cognition request source history has drifted")
    binding_root = _one(
        members, protocol.role("request-binding"), "request binding"
    )
    source_session = read_agent_session(
        source,
        agent_protocol,
        authorization,
        session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=None,
    )
    source_body = read_agent_body(
        source,
        agent_protocol,
        authorization,
        source_session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    if source_session.model_binding_root != binding_root:
        raise InvalidCell("cognition request binding differs from source session")
    binding = read_model_binding(
        source,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        binding_root,
    )
    budget_root = _one(
        members, protocol.role("request-budget"), "request budget"
    )
    if budget_root != binding.budget_root:
        raise InvalidCell("cognition request budget differs from binding")
    manifest_root = _one(
        members,
        protocol.role("request-context-manifest"),
        "request context manifest",
    )
    manifest_members = read_relation(
        snapshot, manifest_root, budget=RELATION_BUDGET
    )
    if any(
        member.role_id != protocol.role("manifest-member")
        for member in manifest_members
    ):
        raise InvalidCell("cognition context manifest contains an undeclared role")
    item_roots = tuple(member.participant_id for member in manifest_members)
    if (
        not item_roots
        or len(item_roots) != len(set(item_roots))
        or len(item_roots) > MAX_CONTEXT_ENTRIES
    ):
        raise InvalidCell("cognition context manifest is invalid")
    entry_roots: list[str] = []
    context_roots: list[str] = []
    for expected_sequence, item_root in enumerate(item_roots, 1):
        item_members = read_relation(snapshot, item_root, budget=RELATION_BUDGET)
        _closed_roles(
            item_members,
            (
                protocol.role("manifest-entry"),
                protocol.role("manifest-context-root"),
                protocol.role("manifest-sequence"),
            ),
            "cognition context manifest item",
        )
        entry_root = _one(
            item_members, protocol.role("manifest-entry"), "manifest entry"
        )
        context_root = _one(
            item_members,
            protocol.role("manifest-context-root"),
            "manifest context root",
        )
        sequence = _integer(
            snapshot,
            _one(
                item_members,
                protocol.role("manifest-sequence"),
                "manifest sequence",
            ),
            "manifest sequence",
        )
        if sequence != expected_sequence:
            raise InvalidCell("cognition context manifest order drifted")
        entry = read_context_entry(
            source,
            agent_protocol,
            authorization,
            entry_root,
            model_binding_verifier=model_binding_verifier,
        )
        if (
            entry.session_root != session_root
            or entry.context_root != context_root
            or entry_root not in source_session.context_entry_roots
        ):
            raise InvalidCell("cognition context manifest drifted from source")
        entry_roots.append(entry_root)
        context_roots.append(context_root)
    read_receipts = _unique(
        _for_role(members, protocol.role("request-read-receipt")),
        "cognition request read receipts",
        limit=MAX_CONTEXT_ENTRIES,
    )
    if len(read_receipts) != len(entry_roots):
        raise InvalidCell("cognition request read evidence is incomplete")
    for receipt_root, context_root in zip(read_receipts, context_roots):
        receipt = _verify_authorization_receipt_integrity(
            snapshot,
            agent_protocol,
            authorization,
            receipt_root,
        )
        if (
            receipt.revision != source_revision
            or store.cell_created_revision(receipt_root) != source_revision + 1
            or receipt.subject_root != source_session.subject_root
            or receipt.policy_root != source_body.authority_policy_root
            or receipt.action_root not in source_body.authority_action_roots
            or not set(receipt.rule_roots).issubset(
                source_body.authority_rule_roots
            )
            or receipt.object_root != context_root
        ):
            raise InvalidCell("cognition request read evidence drifted")
    input_digest_root = _one(
        members, protocol.role("request-input-digest"), "request input digest"
    )
    input_bytes_root = _one(
        members, protocol.role("request-input-bytes"), "request input bytes"
    )
    input_digest = _text(snapshot, input_digest_root, "request input digest")
    input_bytes = _integer(snapshot, input_bytes_root, "request input bytes")
    source_budget = read_cognition_budget(source, protocol, budget_root)
    actual_input_bytes, actual_input_digest = _bounded_regions_summary(
        source,
        tuple(context_roots),
        max_bytes=source_budget.max_input_bytes,
        max_cells=source_budget.max_context_entries * 64,
        label="cognition input",
    )
    if (
        input_bytes != actual_input_bytes
        or not hmac.compare_digest(input_digest, actual_input_digest)
    ):
        raise InvalidCell("cognition request input evidence drifted")
    registry_receipt_root = _one(
        members,
        protocol.role("request-registry-receipt"),
        "request registry receipt",
    )
    registry_receipt = _verify_authorization_receipt_integrity(
        snapshot,
        agent_protocol,
        authorization,
        registry_receipt_root,
    )
    if (
        registry_receipt.revision != source_revision
        or store.cell_created_revision(registry_receipt_root)
        != source_revision + 1
        or registry_receipt.subject_root != source_session.subject_root
        or registry_receipt.policy_root != source_body.authority_policy_root
        or registry_receipt.action_root not in source_body.authority_action_roots
        or not set(registry_receipt.rule_roots).issubset(
            source_body.authority_rule_roots
        )
        or registry_receipt.object_root != session_cognition.request_registry_root
    ):
        raise InvalidCell("cognition request registry evidence drifted")
    idempotency_root = _one(
        members, protocol.role("request-idempotency"), "request idempotency"
    )
    digest_root = _one(
        members, protocol.role("request-digest"), "request digest"
    )
    request = CognitionRequestProjection(
        request_root,
        definition,
        session_root,
        binding_root,
        source_revision,
        chain_digest,
        manifest_root,
        tuple(entry_roots),
        tuple(context_roots),
        input_digest,
        input_bytes,
        _one(members, protocol.role("request-intent"), "request intent"),
        _one(members, protocol.role("request-purpose"), "request purpose"),
        output_definition,
        budget_root,
        _text(snapshot, idempotency_root, "request idempotency"),
        read_receipts,
        registry_receipt_root,
        _one(members, protocol.role("request-state"), "request state"),
        digest_root,
        _text(snapshot, digest_root, "request digest"),
    )
    if request.state_root != protocol.state("prepared"):
        raise InvalidCell("cognition request is not prepared")
    if request.root_id != _derived_identity(
        "cognition-request", request.session_root, request.idempotency_key
    ):
        raise InvalidCell("cognition request semantic identity drifted")
    actual = _request_digest(request)
    if not request.digest or not hmac.compare_digest(request.digest, actual):
        raise InvalidCell("cognition request has drifted")
    return request


def _bounded_regions_summary(
    snapshot: Snapshot,
    root_ids: tuple[str, ...],
    *,
    max_bytes: int,
    max_cells: int,
    label: str,
) -> tuple[int, str]:
    if not root_ids or len(root_ids) != len(set(root_ids)):
        raise InvalidCell("%s roots are empty or repeated" % label)
    pending = list(root_ids)
    seen: dict[str, Cell] = {}
    total = 0
    while pending:
        current = pending.pop()
        if current == NULL_CELL_ID or current in seen:
            continue
        try:
            cell = snapshot.cells[current]
        except KeyError as exc:
            raise InvalidCell("%s references a missing Cell" % label) from exc
        if len(seen) >= max_cells:
            raise InvalidCell("%s exceeds its Cell budget" % label)
        seen[current] = cell
        total += sum(len(value.encode("utf-8")) for value in (
            cell.id, cell.link0, cell.link1
        )) + len(cell.atom)
        if total > max_bytes:
            raise InvalidCell("%s exceeds its input byte budget" % label)
        pending.extend((cell.link0, cell.link1))
    digest = hashlib.blake2b(digest_size=32)
    for root in root_ids:
        raw = root.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    for root in sorted(seen):
        cell = seen[root]
        for raw in (
            cell.id.encode("utf-8"),
            cell.link0.encode("utf-8"),
            cell.link1.encode("utf-8"),
            cell.atom,
        ):
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    return total, digest.hexdigest()


def _bounded_region_bytes(
    snapshot: Snapshot, root_id: str, *, max_bytes: int, max_cells: int
) -> int:
    pending = [root_id]
    seen: set[str] = set()
    total = 0
    while pending:
        current = pending.pop()
        if current == NULL_CELL_ID or current in seen:
            continue
        if current not in snapshot.cells:
            raise InvalidCell("proposal payload references a missing Cell")
        seen.add(current)
        if len(seen) > max_cells:
            raise InvalidCell("proposal payload exceeds its Cell budget")
        cell = snapshot.cells[current]
        total += len(cell.id.encode("utf-8")) + len(cell.atom)
        if total > max_bytes:
            raise InvalidCell("proposal payload exceeds its byte budget")
        pending.extend((cell.link0, cell.link1))
    return total


def _proposal_digest(snapshot: Snapshot, proposal: ProposalProjection) -> str:
    digest = hashlib.blake2b(digest_size=32)
    values = (
        proposal.root_id,
        proposal.definition_root,
        proposal.request_root,
        proposal.session_root,
        proposal.binding_root,
        str(proposal.source_revision),
        proposal.context_manifest_root,
        proposal.operation_root,
        proposal.payload_root,
        *proposal.target_roots,
        proposal.rationale,
        repr(proposal.uncertainty),
        *proposal.evidence_roots,
        proposal.idempotency_key,
        proposal.creation_receipt_root,
        proposal.state_root,
    )
    for value in values:
        raw = value.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    payload_digest = graph_content_digest(
        snapshot, proposal.payload_root, budget=RELATION_BUDGET
    )
    digest.update(len(payload_digest).to_bytes(8, "big"))
    digest.update(payload_digest)
    return digest.hexdigest()


def _read_proposal_snapshot(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    proposal_root: str,
    *,
    expected_session_root: str | None = None,
) -> ProposalProjection:
    _validate_protocol(snapshot, protocol)
    _verify_definitions(snapshot, assembly, catalog_root, definitions)
    global_registry = read_relation(
        snapshot, protocol.registry("proposal"), budget=RELATION_BUDGET
    )
    if sum(
        member.role_id == protocol.role("proposal-member")
        and member.participant_id == proposal_root
        for member in global_registry
    ) != 1:
        raise InvalidCell("Proposal is not globally registered once")
    _validate_definition_relation(
        snapshot,
        assembly,
        definitions.proposal_root,
        proposal_root,
    )
    members = read_relation(snapshot, proposal_root, budget=RELATION_BUDGET)
    role_names = (
        "proposal-definition",
        "proposal-request",
        "proposal-session",
        "proposal-binding",
        "proposal-source-revision",
        "proposal-context-manifest",
        "proposal-operation",
        "proposal-payload",
        "proposal-target",
        "proposal-rationale",
        "proposal-uncertainty",
        "proposal-evidence",
        "proposal-idempotency",
        "proposal-creation-receipt",
        "proposal-state",
        "proposal-digest",
    )
    _closed_roles(
        members, (protocol.role(name) for name in role_names), "Proposal"
    )
    definition = _one(
        members, protocol.role("proposal-definition"), "Proposal definition"
    )
    if definition != definitions.proposal_root:
        raise InvalidCell("Proposal uses another definition")
    session_root = _one(
        members, protocol.role("proposal-session"), "Proposal session"
    )
    if expected_session_root is not None and session_root != expected_session_root:
        raise InvalidCell("Proposal belongs to another session")
    targets = _unique(
        _for_role(members, protocol.role("proposal-target")),
        "Proposal targets",
        limit=MAX_PROPOSAL_TARGETS,
    )
    if not targets:
        raise InvalidCell("Proposal requires at least one target")
    evidence = _unique(
        _for_role(members, protocol.role("proposal-evidence")),
        "Proposal evidence",
        limit=MAX_EVIDENCE,
    )
    rationale_root = _one(
        members, protocol.role("proposal-rationale"), "Proposal rationale"
    )
    uncertainty_root = _one(
        members, protocol.role("proposal-uncertainty"), "Proposal uncertainty"
    )
    try:
        uncertainty = float(
            _text(snapshot, uncertainty_root, "Proposal uncertainty")
        )
    except ValueError as exc:
        raise InvalidCell("Proposal uncertainty is invalid") from exc
    if not math.isfinite(uncertainty) or uncertainty < 0 or uncertainty > 1:
        raise InvalidCell("Proposal uncertainty is outside zero to one")
    source_revision_root = _one(
        members,
        protocol.role("proposal-source-revision"),
        "Proposal source revision",
    )
    idempotency_root = _one(
        members, protocol.role("proposal-idempotency"), "Proposal idempotency"
    )
    digest_root = _one(
        members, protocol.role("proposal-digest"), "Proposal digest"
    )
    proposal = ProposalProjection(
        proposal_root,
        definition,
        _one(members, protocol.role("proposal-request"), "Proposal request"),
        session_root,
        _one(members, protocol.role("proposal-binding"), "Proposal binding"),
        _integer(snapshot, source_revision_root, "Proposal source revision"),
        _one(
            members,
            protocol.role("proposal-context-manifest"),
            "Proposal context manifest",
        ),
        _one(members, protocol.role("proposal-operation"), "Proposal operation"),
        _one(members, protocol.role("proposal-payload"), "Proposal payload"),
        targets,
        _text(snapshot, rationale_root, "Proposal rationale"),
        uncertainty,
        evidence,
        _text(snapshot, idempotency_root, "Proposal idempotency"),
        _one(
            members,
            protocol.role("proposal-creation-receipt"),
            "Proposal creation receipt",
        ),
        _one(members, protocol.role("proposal-state"), "Proposal state"),
        digest_root,
        _text(snapshot, digest_root, "Proposal digest"),
    )
    if proposal.state_root != protocol.state("proposed"):
        raise InvalidCell("Proposal is not in proposed state")
    if proposal.root_id != _derived_identity(
        "proposal", proposal.request_root, proposal.idempotency_key
    ):
        raise InvalidCell("Proposal semantic identity drifted")
    actual = _proposal_digest(snapshot, proposal)
    if not proposal.digest or not hmac.compare_digest(proposal.digest, actual):
        raise InvalidCell("Proposal has drifted")
    return proposal


def make_proposal_verifier(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    *,
    model_binding_verifier,
):
    def verify(snapshot: Snapshot, proposal_root: str, session_root: str):
        if snapshot.revision != store.revision:
            raise InvalidCell("Proposal verifier snapshot is not current")
        proposal = _read_proposal_snapshot(
            snapshot,
            assembly,
            catalog_root,
            protocol,
            definitions,
            proposal_root,
            expected_session_root=session_root,
        )
        request = read_cognition_request(
            store,
            assembly,
            catalog_root,
            protocol,
            definitions,
            adapter_protocol,
            adapter_catalog_root,
            agent_protocol,
            authorization,
            proposal.request_root,
            model_binding_verifier=model_binding_verifier,
            proposal_verifier=None,
        )
        if (
            proposal.session_root != request.session_root
            or proposal.binding_root != request.binding_root
            or proposal.source_revision != request.source_revision
            or proposal.context_manifest_root != request.context_manifest_root
        ):
            raise InvalidCell("Proposal lineage differs from its Cognition Request")
        session_members = read_relation(
            snapshot, session_root, budget=RELATION_BUDGET
        )
        proposal_registry = _one(
            session_members,
            agent_protocol.role("session-proposal-registry"),
            "session Proposal registry",
        )
        scope_root = _one(
            session_members,
            agent_protocol.role("session-scope"),
            "session scope",
        )
        if sum(
            member.role_id == agent_protocol.role("proposal-member")
            and member.participant_id == proposal_root
            for member in read_relation(
                snapshot, proposal_registry, budget=RELATION_BUDGET
            )
        ) != 1:
            raise InvalidCell("Proposal is not session-registered exactly once")
        if not set(proposal.target_roots).issubset(
            {*request.context_roots, scope_root}
        ):
            raise InvalidCell("Proposal targets drifted outside authorised context")
        catalog = verify_released_catalog(snapshot, assembly, catalog_root)
        if proposal.operation_root not in catalog.definition_roots:
            raise InvalidCell("Proposal operation left the released catalogue")
        verify_released_definition(snapshot, assembly, proposal.operation_root)
        budget = read_cognition_budget(snapshot, protocol, request.budget_root)
        _bounded_region_bytes(
            snapshot,
            proposal.payload_root,
            max_bytes=budget.max_output_bytes,
            max_cells=budget.max_context_entries * 64,
        )
        receipt = _verify_authorization_receipt_integrity(
            snapshot,
            agent_protocol,
            authorization,
            proposal.creation_receipt_root,
        )
        if (
            receipt.subject_root != _one(
                session_members,
                agent_protocol.role("session-subject"),
                "session subject",
            )
            or receipt.object_root != proposal_registry
        ):
            raise InvalidCell("Proposal creation evidence drifted")
        return proposal

    return verify


def create_proposal(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    authentication_broker: AuthenticationBroker,
    authentication_context: object,
    registry_request: AuthorizationRequest,
    *,
    request_root: str,
    operation_root: str,
    payload_root: str,
    target_roots: Iterable[str],
    rationale: str,
    uncertainty: float,
    evidence_roots: Iterable[str],
    idempotency_key: str,
    model_binding_verifier,
    resolver_state: object | None = None,
) -> ProposalProjection:
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key.encode("utf-8")) > 512
    ):
        raise InvalidCell("Proposal idempotency key is invalid")
    if (
        not isinstance(rationale, str)
        or not rationale
        or len(rationale.encode("utf-8")) > MAX_TEXT_BYTES
    ):
        raise InvalidCell("Proposal rationale is invalid")
    if (
        not isinstance(uncertainty, (int, float))
        or not math.isfinite(float(uncertainty))
        or float(uncertainty) < 0
        or float(uncertainty) > 1
    ):
        raise InvalidCell("Proposal uncertainty is outside zero to one")
    snapshot = store.snapshot()
    proposal_verifier = make_proposal_verifier(
        store,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        model_binding_verifier=model_binding_verifier,
    )
    request = read_cognition_request(
        store,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        request_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    session = read_agent_session(
        snapshot,
        agent_protocol,
        authorization,
        request.session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if session.model_binding_root != request.binding_root:
        raise InvalidCell("Proposal session binding differs from its request")
    body = read_agent_body(
        snapshot,
        agent_protocol,
        authorization,
        session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    catalog = verify_released_catalog(snapshot, assembly, catalog_root)
    if operation_root not in catalog.definition_roots:
        raise InvalidCell("Proposal operation is outside the released catalogue")
    verify_released_definition(snapshot, assembly, operation_root)
    targets = _unique(
        target_roots, "Proposal targets", limit=MAX_PROPOSAL_TARGETS
    )
    if not targets:
        raise InvalidCell("Proposal requires at least one target")
    allowed_targets = frozenset((*request.context_roots, session.scope_root))
    if not set(targets).issubset(allowed_targets):
        raise AuthorizationDenied("Proposal target was not in authorised context")
    evidence = _unique(
        evidence_roots, "Proposal evidence", limit=MAX_EVIDENCE
    )
    if not set(evidence).issubset(
        {*request.context_roots, payload_root}
    ):
        raise AuthorizationDenied("Proposal evidence was not in authorised context")
    _ensure(snapshot, (payload_root, *targets, *evidence), "Proposal")
    budget = read_cognition_budget(snapshot, protocol, request.budget_root)
    _bounded_region_bytes(
        snapshot,
        payload_root,
        max_bytes=budget.max_output_bytes,
        max_cells=budget.max_context_entries * 64,
    )
    _require_request_binding(
        registry_request,
        object_root=session.proposal_registry_root,
        action_roots=body.authority_action_roots,
        lineage_roots=(session.scope_root,),
        interface_root=registry_request.interface_root,
        audience_root=body.visibility_root,
        classification_root=registry_request.classification_root,
        lifecycle_root=body.lifecycle_root,
        purpose_root=request.purpose_root,
        operational_root=agent_protocol.state("active"),
        label="Proposal registry request",
    )
    evaluation = _evaluate_agent_requests(
        snapshot,
        authorization,
        body.authority_policy_root,
        authentication_broker,
        authentication_context,
        (registry_request,),
        resolver_state,
    )
    decision = evaluation.decisions[0]
    determining_object = _determining_rule_object(
        snapshot,
        authorization,
        decision.determining_rule_roots,
        (session.proposal_registry_root, session.scope_root),
        "Proposal registry",
    )
    _validate_decision(
        snapshot,
        authorization,
        body,
        decision,
        expected_object_root=session.proposal_registry_root,
        expected_rule_object_root=determining_object,
        expected_interface_root=registry_request.interface_root,
        expected_purpose_root=request.purpose_root,
        expected_classification_root=registry_request.classification_root,
        expected_audience_root=body.visibility_root,
        expected_lifecycle_root=body.lifecycle_root,
        expected_operational_root=agent_protocol.state("active"),
        label="Proposal registry",
    )
    proposal_id = _derived_identity("proposal", request_root, idempotency_key)
    if proposal_id in snapshot.cells:
        existing = read_proposal(
            store,
            assembly,
            catalog_root,
            protocol,
            definitions,
            adapter_protocol,
            adapter_catalog_root,
            agent_protocol,
            authorization,
            proposal_id,
            model_binding_verifier=model_binding_verifier,
        )
        expected = (
            request_root,
            operation_root,
            payload_root,
            targets,
            rationale,
            float(uncertainty),
            evidence,
            idempotency_key,
        )
        actual = (
            existing.request_root,
            existing.operation_root,
            existing.payload_root,
            existing.target_roots,
            existing.rationale,
            existing.uncertainty,
            existing.evidence_roots,
            existing.idempotency_key,
        )
        if actual == expected:
            return existing
        raise InvalidCell("Proposal idempotency key was reused for other content")
    roots = {
        "source-revision": proposal_id + ":source-revision",
        "rationale": proposal_id + ":rationale",
        "uncertainty": proposal_id + ":uncertainty",
        "idempotency": proposal_id + ":idempotency",
        "receipt": proposal_id + ":creation-receipt",
        "digest": proposal_id + ":digest",
    }
    receipt_cells = _compose_authorization_receipt(
        snapshot,
        agent_protocol,
        authorization,
        evaluation,
        0,
        receipt_id=roots["receipt"],
    )
    provisional = ProposalProjection(
        proposal_id,
        definitions.proposal_root,
        request_root,
        request.session_root,
        request.binding_root,
        request.source_revision,
        request.context_manifest_root,
        operation_root,
        payload_root,
        targets,
        rationale,
        float(uncertainty),
        evidence,
        idempotency_key,
        roots["receipt"],
        protocol.state("proposed"),
        roots["digest"],
        "",
    )
    digest = _proposal_digest(snapshot, provisional)
    relation = compose_relation_cells(
        (
            (protocol.role("proposal-definition"), definitions.proposal_root),
            (protocol.role("proposal-request"), request_root),
            (protocol.role("proposal-session"), request.session_root),
            (protocol.role("proposal-binding"), request.binding_root),
            (protocol.role("proposal-source-revision"), roots["source-revision"]),
            (protocol.role("proposal-context-manifest"), request.context_manifest_root),
            (protocol.role("proposal-operation"), operation_root),
            (protocol.role("proposal-payload"), payload_root),
            *((protocol.role("proposal-target"), root) for root in targets),
            (protocol.role("proposal-rationale"), roots["rationale"]),
            (protocol.role("proposal-uncertainty"), roots["uncertainty"]),
            *((protocol.role("proposal-evidence"), root) for root in evidence),
            (protocol.role("proposal-idempotency"), roots["idempotency"]),
            (protocol.role("proposal-creation-receipt"), roots["receipt"]),
            (protocol.role("proposal-state"), protocol.state("proposed")),
            (protocol.role("proposal-digest"), roots["digest"]),
        ),
        relation_id=proposal_id,
    )
    session_append = prepare_append_relation_member(
        snapshot,
        session.proposal_registry_root,
        agent_protocol.role("proposal-member"),
        proposal_id,
        budget=RELATION_BUDGET,
    )
    global_append = prepare_append_relation_member(
        snapshot,
        protocol.registry("proposal"),
        protocol.role("proposal-member"),
        proposal_id,
        budget=RELATION_BUDGET,
    )
    created = _assert_creates(
        snapshot,
        (
            _terminal(roots["source-revision"], request.source_revision),
            _terminal(roots["rationale"], rationale),
            _terminal(roots["uncertainty"], repr(float(uncertainty))),
            _terminal(roots["idempotency"], idempotency_key),
            _terminal(roots["digest"], digest),
            *receipt_cells,
            *relation.cells,
            *session_append.create,
            *global_append.create,
        ),
        "Proposal",
    )
    authentication_broker.commit_authenticated(
        authentication_context,
        store,
        snapshot.revision,
        create=created,
        replace=(*session_append.replace, *global_append.replace),
    )
    return read_proposal(
        store,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        proposal_id,
        model_binding_verifier=model_binding_verifier,
    )


def read_proposal(
    store: CellStore,
    assembly: AssemblyProtocol,
    catalog_root: str,
    protocol: AgentCognitionProtocol,
    definitions: AgentCognitionDefinitions,
    adapter_protocol: AdapterProtocol,
    adapter_catalog_root: str,
    agent_protocol: AgentBodyProtocol,
    authorization: AuthorizationProtocol,
    proposal_root: str,
    *,
    model_binding_verifier,
) -> ProposalProjection:
    snapshot = store.snapshot()
    proposal = _read_proposal_snapshot(
        snapshot,
        assembly,
        catalog_root,
        protocol,
        definitions,
        proposal_root,
    )
    proposal_verifier = make_proposal_verifier(
        store,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        model_binding_verifier=model_binding_verifier,
    )
    session = read_agent_session(
        snapshot,
        agent_protocol,
        authorization,
        proposal.session_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if session.proposal_roots.count(proposal_root) != 1:
        raise InvalidCell("Proposal is not session-registered exactly once")
    request = read_cognition_request(
        store,
        assembly,
        catalog_root,
        protocol,
        definitions,
        adapter_protocol,
        adapter_catalog_root,
        agent_protocol,
        authorization,
        proposal.request_root,
        model_binding_verifier=model_binding_verifier,
        proposal_verifier=proposal_verifier,
    )
    if (
        proposal.session_root != request.session_root
        or proposal.binding_root != request.binding_root
        or proposal.source_revision != request.source_revision
        or proposal.context_manifest_root != request.context_manifest_root
    ):
        raise InvalidCell("Proposal lineage differs from its Cognition Request")
    if not set(proposal.target_roots).issubset(
        {*request.context_roots, session.scope_root}
    ):
        raise InvalidCell("Proposal targets drifted outside authorised context")
    catalog = verify_released_catalog(snapshot, assembly, catalog_root)
    if proposal.operation_root not in catalog.definition_roots:
        raise InvalidCell("Proposal operation left the released catalogue")
    budget = read_cognition_budget(snapshot, protocol, request.budget_root)
    _bounded_region_bytes(
        snapshot,
        proposal.payload_root,
        max_bytes=budget.max_output_bytes,
        max_cells=budget.max_context_entries * 64,
    )
    receipt = _verify_authorization_receipt_integrity(
        snapshot,
        agent_protocol,
        authorization,
        proposal.creation_receipt_root,
    )
    body = read_agent_body(
        snapshot,
        agent_protocol,
        authorization,
        session.body_root,
        model_binding_verifier=model_binding_verifier,
    )
    if (
        receipt.revision + 1 != store.cell_created_revision(proposal.root_id)
        or store.cell_created_revision(proposal.creation_receipt_root)
        != store.cell_created_revision(proposal.root_id)
        or receipt.subject_root != session.subject_root
        or receipt.policy_root != body.authority_policy_root
        or receipt.action_root not in body.authority_action_roots
        or not set(receipt.rule_roots).issubset(body.authority_rule_roots)
        or receipt.object_root != session.proposal_registry_root
    ):
        raise InvalidCell("Proposal creation evidence drifted")
    return proposal


__all__ = [
    "AgentCognitionDefinitions",
    "AgentCognitionProtocol",
    "CognitionBudgetProjection",
    "CognitionRequestProjection",
    "ModelBindingProjection",
    "ModelDescriptorProjection",
    "ProposalProjection",
    "SessionCognitionProjection",
    "bind_agent_body_model",
    "bootstrap_agent_cognition_protocol",
    "build_agent_cognition_definitions",
    "build_cognition_budget",
    "build_model_descriptor",
    "create_cognition_request",
    "create_proposal",
    "make_model_binding_verifier",
    "make_proposal_verifier",
    "open_agent_cognition_protocol",
    "provision_session_cognition",
    "read_cognition_budget",
    "read_cognition_request",
    "read_model_binding",
    "read_model_descriptor",
    "read_proposal",
    "release_model_descriptor",
]
