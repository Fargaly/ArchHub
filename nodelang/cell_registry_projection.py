"""Read-only projections of deterministic graph vocabularies.

Bootstrap functions create authority.  These functions only recover Python
indexes from already persisted Cells, so reopening a database never creates a
parallel graph or regenerates incidence identities.
"""
from __future__ import annotations

from types import MappingProxyType

from .cell_adapters import AdapterProtocol, ROLE_NAMES as ADAPTER_ROLES
from .cell_attestations import AttestationProtocol, ROLE_NAMES as ATTESTATION_ROLES
from .cell_authorization import (
    ACTION_NAMES,
    AuthorizationProtocol,
    ROLE_NAMES as AUTHORIZATION_ROLES,
)
from .cell_catalog import (
    AssemblyProtocol,
    ROLE_NAMES as ASSEMBLY_ROLES,
    read_definition,
    verify_released_catalog,
)
from .cell_composer import (
    COMMAND_NAMES,
    ComposerProtocol,
    ROLE_NAMES as COMPOSER_ROLES,
)
from .cell_domain_catalog import DOMAIN_SPECS, GovernedDomainLibrary
from .cell_identity import (
    IdentityProtocol,
    KIND_NAMES as IDENTITY_KINDS,
    ROLE_NAMES as IDENTITY_ROLES,
    STATE_NAMES as IDENTITY_STATES,
)
from .cell_lifecycle import (
    LifecycleDefinition,
    LifecycleProtocol,
    ROLE_NAMES as LIFECYCLE_ROLES,
)
from .cell_reactions import (
    REACTION_ROLE_NAMES,
    ReactionProtocol,
)
from .cell_standard_library import StandardLibraryBuild
from .cell_state_machine import (
    ROLE_NAMES as STATE_MACHINE_ROLES,
    StateMachineProtocol,
)
from .cell_ui import ROLE_NAMES as UI_ROLES, UIProtocol
from .universal_cell import InvalidCell, Snapshot


def _roots(prefix: str, segment: str, names) -> MappingProxyType:
    return MappingProxyType({
        name: "%s:%s:%s" % (prefix, segment, name) for name in names
    })


def _require(snapshot: Snapshot, roots, label: str) -> None:
    # Point reads, never set(snapshot.cells): the head map is lazy over a
    # journal of millions of rows, and materialising every id here ran on
    # each of the dozens of protocol projections a boot performs. That one
    # line was half of a 259s boot (boot-profile.log, 2026-09-05).
    missing = {root for root in roots if root not in snapshot.cells}
    if missing:
        raise InvalidCell(
            "%s projection is incomplete: %s" % (label, sorted(missing)[0])
        )


def project_assembly_protocol(
    snapshot: Snapshot, prefix: str
) -> AssemblyProtocol:
    roles = _roots(prefix, "role", ASSEMBLY_ROLES)
    states = _roots(prefix, "state", ("draft", "released", "deprecated"))
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values(), *states.values()), "assembly protocol")
    return AssemblyProtocol(root, roles, states)


def project_reaction_protocol(
    snapshot: Snapshot, prefix: str
) -> ReactionProtocol:
    roles = _roots(prefix, "role", REACTION_ROLE_NAMES)
    states = _roots(prefix, "state", ("enabled", "disabled"))
    root = prefix + ":root"
    registry = prefix + ":registry"
    _require(
        snapshot,
        (root, registry, *roles.values(), *states.values()),
        "reaction protocol",
    )
    return ReactionProtocol(root, registry, roles, states)


def project_lifecycle_protocol(
    snapshot: Snapshot, prefix: str
) -> LifecycleProtocol:
    roles = _roots(prefix, "role", LIFECYCLE_ROLES)
    states = _roots(prefix, "state", ("wip", "shared", "published", "archived"))
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values(), *states.values()), "lifecycle protocol")
    return LifecycleProtocol(root, roles, states)


def project_state_machine_protocol(
    snapshot: Snapshot, prefix: str
) -> StateMachineProtocol:
    roles = _roots(prefix, "role", STATE_MACHINE_ROLES)
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values()), "state-machine protocol")
    return StateMachineProtocol(root, roles)


def project_adapter_protocol(
    snapshot: Snapshot, prefix: str
) -> AdapterProtocol:
    roles = _roots(prefix, "role", ADAPTER_ROLES)
    states = _roots(
        prefix,
        "state",
        ("draft", "released", "requested", "granted", "denied", "revoked"),
    )
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values(), *states.values()), "adapter protocol")
    return AdapterProtocol(root, roles, states)


def project_attestation_protocol(
    snapshot: Snapshot, prefix: str
) -> AttestationProtocol:
    roles = _roots(prefix, "role", ATTESTATION_ROLES)
    states = _roots(prefix, "state", ("draft", "released", "passed", "failed"))
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values(), *states.values()), "attestation protocol")
    return AttestationProtocol(root, roles, states)


def project_composer_protocol(
    snapshot: Snapshot, prefix: str
) -> ComposerProtocol:
    roles = _roots(prefix, "role", COMPOSER_ROLES)
    commands = _roots(prefix, "command", COMMAND_NAMES)
    states = _roots(prefix, "state", ("draft", "released", "deprecated"))
    root = prefix + ":root"
    _require(
        snapshot,
        (root, *roles.values(), *commands.values(), *states.values()),
        "composer protocol",
    )
    return ComposerProtocol(root, roles, commands, states)


def project_authorization_protocol(
    snapshot: Snapshot, prefix: str
) -> AuthorizationProtocol:
    roles = _roots(prefix, "role", AUTHORIZATION_ROLES)
    actions = _roots(prefix, "action", ACTION_NAMES)
    effects = _roots(prefix, "effect", ("permit", "forbid"))
    states = _roots(prefix, "state", ("draft", "released", "revoked"))
    root = prefix + ":root"
    _require(
        snapshot,
        (root, *roles.values(), *actions.values(), *effects.values(), *states.values()),
        "authorization protocol",
    )
    return AuthorizationProtocol(root, roles, actions, effects, states)


def project_identity_protocol(
    snapshot: Snapshot, prefix: str
) -> IdentityProtocol:
    roles = _roots(prefix, "role", IDENTITY_ROLES)
    kinds = _roots(prefix, "kind", IDENTITY_KINDS)
    states = _roots(prefix, "state", IDENTITY_STATES)
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values(), *kinds.values(), *states.values()), "identity protocol")
    return IdentityProtocol(root, roles, kinds, states)


def project_ui_protocol(snapshot: Snapshot, prefix: str) -> UIProtocol:
    roles = _roots(prefix, "role", UI_ROLES)
    root = prefix + ":root"
    _require(snapshot, (root, *roles.values()), "UI protocol")
    return UIProtocol(root, roles)


def project_standard_library(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    *,
    prefix: str,
    catalog_root: str | None = None,
    required_domain_keys: tuple[str, ...] | None = None,
    additional_definition_roots: tuple[str, ...] = (),
) -> StandardLibraryBuild:
    reaction = project_reaction_protocol(snapshot, prefix + ":reaction-protocol")
    lifecycle = project_lifecycle_protocol(snapshot, prefix + ":lifecycle-protocol")
    state_machine = project_state_machine_protocol(
        snapshot, prefix + ":state-machine-protocol"
    )
    ordered = prefix + ":definition:ordered-list"
    watcher = prefix + ":definition:watcher"
    versioned = prefix + ":versioned-asset:definition"
    available_specs = {spec["key"]: spec for spec in DOMAIN_SPECS}
    domain_keys = (
        tuple(available_specs)
        if required_domain_keys is None
        else tuple(required_domain_keys)
    )
    if len(domain_keys) != len(set(domain_keys)):
        raise InvalidCell("standard-library domain projection repeats a key")
    unknown = set(domain_keys) - set(available_specs)
    if unknown:
        raise InvalidCell("standard-library domain projection has unknown keys")
    governed: dict[str, LifecycleDefinition] = {}
    for key in domain_keys:
        spec = available_specs[key]
        base = "%s:governed-domains:%s:lifecycle" % (prefix, spec["key"])
        definition_root = base + ":definition"
        definition = read_definition(snapshot, assembly, definition_root)
        governed[spec["key"]] = LifecycleDefinition(
            definition_root,
            base + ":manifest",
            definition.part_roots,
        )
    if len(additional_definition_roots) != len(set(additional_definition_roots)):
        raise InvalidCell("standard-library projection repeats an extension")
    definitions = (
        ordered,
        watcher,
        versioned,
        *(item.definition_root for item in governed.values()),
        *additional_definition_roots,
    )
    if len(definitions) != len(set(definitions)):
        raise InvalidCell("standard-library projection repeats a definition")
    for root in definitions:
        read_definition(snapshot, assembly, root)
    selected_catalog_root = catalog_root or (
        prefix + ":catalog:v2"
        if prefix + ":catalog:v2" in snapshot.cells
        else prefix + ":catalog"
    )
    catalog = verify_released_catalog(
        snapshot, assembly, selected_catalog_root
    )
    if set(catalog.definition_roots) != set(definitions):
        raise InvalidCell(
            "standard-library projection does not match released catalogue"
        )
    shared = {
        key: prefix + ":ordered-list:" + suffix
        for key, suffix in {
            "item-role": "role:item",
            "interface-name": "interface-name",
            "contract": "contract",
            "documentation": "documentation",
            "presentation": "presentation",
            "evidence": "evidence",
        }.items()
    }
    for key in (
        "source-slot", "interface-name", "event-log", "fingerprint",
        "cursor", "status", "error", "contract", "documentation",
        "presentation", "evidence",
    ):
        shared["watcher-" + key] = prefix + ":watcher:" + key
    _require(snapshot, shared.values(), "standard-library shared roots")
    return StandardLibraryBuild(
        catalog_root=selected_catalog_root,
        definition_roots=definitions,
        shared_roots=MappingProxyType(shared),
        reaction_protocol=reaction,
        lifecycle_protocol=lifecycle,
        state_machine_protocol=state_machine,
        governed_domains=GovernedDomainLibrary(MappingProxyType(governed)),
    )


__all__ = [name for name in globals() if name.startswith("project_")]
