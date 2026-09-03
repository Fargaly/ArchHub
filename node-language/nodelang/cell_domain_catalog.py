"""Released higher-level assemblies composed from lifecycle and state protocols."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_catalog import (
    AssemblyProtocol,
    build_interface,
    verify_released_definition,
)
from .cell_lifecycle import (
    LifecycleDefinition,
    LifecycleProtocol,
    build_versioned_asset_definition,
)
from .cell_protocols import read_relation
from .cell_state_machine import (
    StateMachineProtocol,
    build_evidence_admission,
    build_state_machine,
    build_transition,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, Snapshot


@dataclass(frozen=True, slots=True)
class GovernedDomainLibrary:
    definitions: Mapping[str, LifecycleDefinition]

    @property
    def definition_roots(self) -> tuple[str, ...]:
        return tuple(
            definition.definition_root for definition in self.definitions.values()
        )


DOMAIN_SPECS = (
    {
        "key": "database-transaction",
        "name": "Database Transaction",
        "presentation": "standard-library/database-transaction",
        "contract": (
            "intent is local; commit is an admitted operational transition only "
            "after integrity-checked storage evidence"
        ),
        "fields": (
            ("resource", "unconfigured"),
            ("operation", "write"),
            ("payload-reference", "unwired"),
            ("idempotency-key", "unset"),
        ),
        "states": ("open", "pending", "committed", "aborted"),
        "initial": "open",
        "evidence": ("storage-confirmation",),
        "transitions": (
            ("stage", "open", "pending", ()),
            ("commit", "pending", "committed", ("storage-confirmation",)),
            ("abort", "pending", "aborted", ()),
        ),
    },
    {
        "key": "monetary-intent",
        "name": "Monetary Intent",
        "presentation": "standard-library/monetary-intent",
        "contract": (
            "amount intent never proves settlement; success or failure requires "
            "integrity-checked provider evidence from an admitted adapter"
        ),
        "fields": (
            ("provider", "unconfigured"),
            ("amount-minor", "0"),
            ("currency", "unset"),
            ("idempotency-key", "unset"),
            ("external-reference", "none"),
        ),
        "states": (
            "requires-action", "pending", "succeeded", "failed", "canceled",
        ),
        "initial": "requires-action",
        "evidence": ("provider-confirmation",),
        "transitions": (
            ("submit", "requires-action", "pending", ()),
            ("confirm", "pending", "succeeded", ("provider-confirmation",)),
            ("reject", "pending", "failed", ("provider-confirmation",)),
            ("cancel", "requires-action", "canceled", ()),
            ("cancel", "pending", "canceled", ("provider-confirmation",)),
        ),
    },
    {
        "key": "geometry-asset",
        "name": "Geometry Asset",
        "presentation": "standard-library/geometry-asset",
        "contract": (
            "binary payload stays content-addressed; schema, units, CRS, transform, "
            "labels, validation, presentation, and provenance remain separate wires"
        ),
        "fields": (
            ("blob-reference", "unwired"),
            ("media-type", "application/octet-stream"),
            ("content-digest", "unset"),
            ("schema", "unset"),
            ("units", "unset"),
            ("crs", "unset"),
            ("transform", "identity"),
            ("labels", "empty"),
            ("presentation", "default"),
            ("provenance", "unwired"),
        ),
        "states": ("draft", "pending-validation", "valid", "invalid"),
        "initial": "draft",
        "evidence": ("validator-report",),
        "transitions": (
            ("validate", "draft", "pending-validation", ()),
            ("accept", "pending-validation", "valid", ("validator-report",)),
            ("reject", "pending-validation", "invalid", ("validator-report",)),
        ),
    },
    {
        "key": "cde-governed-asset",
        "name": "CDE Governed Asset",
        "presentation": "standard-library/cde-governed-asset",
        "contract": (
            "review authority is independent from WIP, Shared, Published, and "
            "Archived revision heads; promotion never mutates source history"
        ),
        "fields": (
            ("container-id", "unset"),
            ("privacy-tier", "T1 INTERNAL"),
            ("owner", "unassigned"),
            ("required-gates", "unwired"),
        ),
        "states": ("authoring", "review", "authorized", "superseded"),
        "initial": "authoring",
        "evidence": ("approval-record",),
        "transitions": (
            ("submit", "authoring", "review", ()),
            ("authorize", "review", "authorized", ("approval-record",)),
            ("return", "review", "authoring", ("approval-record",)),
            ("supersede", "authorized", "superseded", ("approval-record",)),
        ),
    },
    {
        "key": "knowledge-branch",
        "name": "Knowledge Branch",
        "presentation": "standard-library/knowledge-branch",
        "contract": (
            "concurrent variations remain separate heads until a traced review "
            "accepts, rejects, or explicitly merges them"
        ),
        "fields": (
            ("source", "unwired"),
            ("scope", "private"),
            ("claims", "empty"),
            ("provenance", "unwired"),
        ),
        "states": ("draft", "reviewing", "accepted", "rejected"),
        "initial": "draft",
        "evidence": ("review-record",),
        "evidence_issuers": {
            "review-record": "review-authority",
        },
        "transitions": (
            ("submit", "draft", "reviewing", ()),
            ("accept", "reviewing", "accepted", ("review-record",)),
            ("reject", "reviewing", "rejected", ("review-record",)),
        ),
    },
    {
        "key": "governed-work",
        "name": "Governed Work",
        "presentation": "standard-library/governed-work",
        "contract": (
            "work is a provenanced activity wired to its plan, scope, CDE, "
            "requirements, dependencies, policy, inputs, and outputs; claim "
            "records actor and session, review requires artifact evidence, "
            "and completion requires an independent court receipt"
        ),
        "fields": (
            ("title", "Untitled work"),
            ("description", ""),
            ("priority", "0"),
            ("external-key", "unset"),
            ("plan", "unwired"),
            ("scope", "unwired"),
            ("cde-container", "unwired"),
            ("requirements", "unwired"),
            ("dependencies", "unwired"),
            ("required-capabilities", "unwired"),
            ("applicable-policy", "unwired"),
            ("inputs", "unwired"),
            ("outputs", "unwired"),
        ),
        "states": (
            "open", "claimed", "blocked", "review", "complete",
            "cancelled",
        ),
        "initial": "open",
        "evidence": (
            "block-reason", "resume-decision", "artifact-proof",
            "independent-court-receipt", "cancellation-decision",
        ),
        "transitions": (
            ("claim", "open", "claimed", ()),
            ("release", "claimed", "open", ()),
            ("block", "claimed", "blocked", ("block-reason",)),
            ("resume", "blocked", "claimed", ("resume-decision",)),
            ("submit", "claimed", "review", ("artifact-proof",)),
            (
                "accept", "review", "complete",
                ("independent-court-receipt",),
            ),
            (
                "return", "review", "claimed",
                ("independent-court-receipt",),
            ),
            (
                "cancel", "open", "cancelled",
                ("cancellation-decision",),
            ),
            (
                "cancel", "claimed", "cancelled",
                ("cancellation-decision",),
            ),
            (
                "cancel", "blocked", "cancelled",
                ("cancellation-decision",),
            ),
            (
                "cancel", "review", "cancelled",
                ("cancellation-decision",),
            ),
        ),
    },
    {
        "key": "permission-request",
        "name": "Permission Request",
        "presentation": "standard-library/permission-request",
        "contract": (
            "a requested effect remains inert until an authorized human decision; "
            "execution starts only with admission evidence from an allowlisted "
            "adapter, and success or failure requires its integrity-checked receipt"
        ),
        "fields": (
            ("requester", "unassigned"),
            ("action", "unconfigured"),
            ("object", "unwired"),
            ("parameters", "empty"),
            ("reason", "unset"),
            ("expires-at", "unset"),
        ),
        "states": (
            "pending", "approved", "rejected", "executing", "succeeded",
            "failed", "canceled",
        ),
        "initial": "pending",
        "evidence": (
            "user-decision", "execution-admission", "execution-receipt",
        ),
        "transitions": (
            ("approve", "pending", "approved", ("user-decision",)),
            ("approve", "failed", "approved", ("user-decision",)),
            ("reject", "pending", "rejected", ("user-decision",)),
            ("cancel", "pending", "canceled", ("user-decision",)),
            ("cancel", "approved", "canceled", ("user-decision",)),
            (
                "execute", "approved", "executing",
                ("execution-admission",),
            ),
            (
                "succeed", "executing", "succeeded",
                ("execution-receipt",),
            ),
            (
                "fail", "executing", "failed",
                ("execution-receipt",),
            ),
        ),
    },
)


def _relation_physical_region(
    snapshot: Snapshot, relation_root: str
) -> tuple[str, ...]:
    read_relation(snapshot, relation_root, budget=100_000)
    region = []
    cursor = relation_root
    while cursor != NULL_CELL_ID:
        chain = snapshot.cells[cursor]
        region.append(chain.id)
        if chain.link0 != NULL_CELL_ID:
            region.append(chain.link0)
        cursor = chain.link1
    return tuple(region)


def _build_domain_definition(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    operational: StateMachineProtocol,
    spec,
    *,
    prefix: str,
) -> LifecycleDefinition:
    key = spec["key"]
    base = "%s:%s" % (prefix, key)
    terminal_atoms = {
        base + ":documentation": spec["contract"],
        base + ":interface-contract": "editable declared field boundary",
        base + ":interface-presentation": spec["presentation"],
        **{
            "%s:field:%s" % (base, name): value
            for name, value in spec["fields"]
        },
        **{
            "%s:field-name:%s" % (base, name): name
            for name, _ in spec["fields"]
        },
        **{
            "%s:state:%s" % (base, name): name.replace("-", " ").upper()
            for name in spec["states"]
        },
        **{
            "%s:event:%s" % (base, name): name.replace("-", " ")
            for name, *_ in spec["transitions"]
        },
        **{
            "%s:evidence-type:%s" % (base, name): name.replace("-", " ")
            for name in spec["evidence"]
        },
        **{
            "%s:evidence-issuer:%s" % (base, issuer): issuer.replace("-", " ")
            for issuer in dict.fromkeys(
                spec.get("evidence_issuers", {}).values()
            )
        },
    }
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
        for root, value in terminal_atoms.items()
    ))
    states = {
        name: "%s:state:%s" % (base, name) for name in spec["states"]
    }
    events = {
        name: "%s:event:%s" % (base, name)
        for name, *_ in spec["transitions"]
    }
    evidence_types = {
        name: "%s:evidence-type:%s" % (base, name)
        for name in spec["evidence"]
    }
    evidence_issuers = {
        name: "%s:evidence-issuer:%s" % (base, issuer)
        for name, issuer in spec.get("evidence_issuers", {}).items()
    }
    evidence_admissions = {
        name: build_evidence_admission(
            store,
            operational,
            admission_id="%s:evidence-admission:%s" % (base, name),
            evidence_type_root=evidence_types[name],
            issuer_root=issuer_root,
        )
        for name, issuer_root in evidence_issuers.items()
    }
    transition_roots = []
    for index, (event, source, target, required) in enumerate(spec["transitions"]):
        legacy_required = tuple(
            evidence_types[name] for name in required
            if name not in evidence_admissions
        )
        admitted_required = tuple(
            evidence_admissions[name] for name in required
            if name in evidence_admissions
        )
        if legacy_required and admitted_required:
            raise ValueError(
                "%s mixes legacy and issuer-bound evidence on one transition"
                % base
            )
        transition_roots.append(build_transition(
            store,
            operational,
            transition_id="%s:transition:%s:%s" % (base, event, index),
            from_state_root=states[source],
            to_state_root=states[target],
            event_root=events[event],
            required_evidence_type_roots=legacy_required,
            required_evidence_admission_roots=admitted_required,
        ))
    machine_root = build_state_machine(
        store,
        operational,
        machine_id=base + ":operational-machine",
        state_roots=states.values(),
        transition_roots=transition_roots,
        initial_state_root=states[spec["initial"]],
    )
    interfaces = []
    for name, _ in spec["fields"]:
        interfaces.append(build_interface(
            store,
            assembly,
            interface_id="%s:interface:%s" % (base, name),
            target_root="%s:field:%s" % (base, name),
            name_root="%s:field-name:%s" % (base, name),
            contract_root=base + ":interface-contract",
            presentation_root=base + ":interface-presentation",
            documentation_root=base + ":documentation",
        ))

    snapshot = store.snapshot()
    relation_roots = (
        *transition_roots,
        *evidence_admissions.values(),
        machine_root,
        machine_root + ":history",
    )
    physical = tuple(
        cell_id
        for root in relation_roots
        for cell_id in _relation_physical_region(snapshot, root)
    )
    interface_parts = tuple(
        cell_id for interface in interfaces for cell_id in interface.part_roots
    )
    terminal_roots = tuple(terminal_atoms)
    return build_versioned_asset_definition(
        store,
        assembly,
        lifecycle,
        prefix=base + ":lifecycle",
        name=spec["name"],
        version="1.0.0",
        contract=spec["contract"],
        documentation=spec["contract"],
        presentation=spec["presentation"],
        operational_evidence="tests_replica/test_cell_domain_catalog.py::%s" % key,
        extra_part_roots=(
            *terminal_roots,
            *physical,
            *interface_parts,
        ),
        extra_interface_roots=tuple(
            interface.root_id for interface in interfaces
        ),
        extra_state_roots=(machine_root, *states.values()),
        extra_rule_roots=(machine_root,),
        extra_capability_roots=(operational.root_id,),
        extra_shared_roots=(operational.root_id, *operational.roles.values()),
    )


def build_governed_domain_definition(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    operational: StateMachineProtocol,
    key: str,
    *,
    prefix: str = "governed-domain-library",
) -> LifecycleDefinition:
    """Build or verify one named standard assembly from the admitted specs."""
    matches = tuple(spec for spec in DOMAIN_SPECS if spec["key"] == key)
    if len(matches) != 1:
        raise ValueError("unknown governed domain assembly %r" % key)
    base = "%s:%s" % (prefix, key)
    definition_root = base + ":lifecycle:definition"
    snapshot = store.snapshot()
    if definition_root in snapshot.cells:
        definition = verify_released_definition(
            snapshot, assembly, definition_root
        )
        return LifecycleDefinition(
            definition.root_id,
            base + ":lifecycle:manifest",
            definition.part_roots,
        )
    return _build_domain_definition(
        store,
        assembly,
        lifecycle,
        operational,
        matches[0],
        prefix=prefix,
    )


def build_governed_domain_library(
    store: CellStore,
    assembly: AssemblyProtocol,
    lifecycle: LifecycleProtocol,
    operational: StateMachineProtocol,
    *,
    prefix: str = "governed-domain-library",
    domain_keys: tuple[str, ...] | None = None,
) -> GovernedDomainLibrary:
    keys = (
        tuple(spec["key"] for spec in DOMAIN_SPECS)
        if domain_keys is None
        else tuple(domain_keys)
    )
    if len(keys) != len(set(keys)):
        raise ValueError("governed domain library repeats an assembly key")
    definitions = {
        key: build_governed_domain_definition(
            store,
            assembly,
            lifecycle,
            operational,
            key,
            prefix=prefix,
        )
        for key in keys
    }
    return GovernedDomainLibrary(MappingProxyType(definitions))


__all__ = [
    "GovernedDomainLibrary", "DOMAIN_SPECS",
    "build_governed_domain_definition", "build_governed_domain_library",
]
