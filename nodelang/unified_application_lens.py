"""Generic visual scope projection over the one Unified Cell authority."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_attention import active_focus, open_attention_protocol
from .cell_protocols import read_relation
from .unified_authority import (
    property_identities,
    CallerCommandCapability,
    DefinitionProjection,
    UnifiedAuthority,
    composition_root,
    read_definition,
    read_scope_level,
    relation_members,
)
from .universal_cell import InvalidCell


@dataclass(frozen=True, slots=True)
class LensProperty:
    name: str
    value: object
    editor: object
    constraints: Mapping[str, object]
    # Identity of the cells this row was read from. Without them a rendered
    # value cannot be traced back to the graph that produced it, so the
    # visual layer can show a value but not prove it.
    property_root: str | None = None
    owner_root: str | None = None
    name_root: str | None = None
    value_root: str | None = None


@dataclass(frozen=True, slots=True)
class LensPort:
    relation_root: str
    participant_role: str
    connection: str | None
    other_roots: tuple[str, ...]
    # A socket is declared by an interface in the definition and realised by
    # incidences in the relation. Both are named here so a drawn socket can
    # be traced to the cells that authorise it rather than described by
    # whatever the renderer guessed.
    interface_root: str | None = None
    direction: object = None
    multiple: object = None
    permission: object = None
    editable: bool = False
    source_incidence: str | None = None
    target_incidence: str | None = None
    authority_roots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LensNode:
    root_id: str
    structural_role: str
    label: str
    definition_root: str | None
    definition_name: str | None
    lifecycle: str | None
    state_parameter: str | None
    state: object
    panels: tuple[str, ...]
    properties: tuple[LensProperty, ...]
    ports: tuple[LensPort, ...]
    openable: bool
    # Appearance is declared in the definition's presentation contract. It is
    # carried with the root of each declaring cell so a rendered node can name
    # where every visible attribute came from instead of inventing it.
    presentation_root: str | None = None
    icon: object = None
    color_token: object = None
    resolved_color: object = None
    position: object = None
    icon_root: str | None = None
    color_token_root: str | None = None
    position_root: str | None = None


@dataclass(frozen=True, slots=True)
class LensRelation:
    root_id: str
    participants: tuple[tuple[str, str], ...]
    properties: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class LensCatalogueItem:
    root_id: str
    name: str
    version: str
    lifecycle: str
    parameters: Mapping[str, object]
    interfaces: Mapping[str, object]
    presentation: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class UnifiedScopeLens:
    graph_id: str
    revision: int
    scope_root: str
    scope_label: str | None
    selected_root: str | None
    selected_roots: tuple[str, ...]
    nodes: tuple[LensNode, ...]
    relations: tuple[LensRelation, ...]
    catalogue: tuple[LensCatalogueItem, ...]


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is not list or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise InvalidCell("%s presentation is invalid" % label)
    return tuple(item.strip() for item in value)


def _definition_item(definition: DefinitionProjection) -> LensCatalogueItem:
    return LensCatalogueItem(
        definition.root_id,
        definition.name,
        definition.version,
        definition.lifecycle,
        MappingProxyType(dict(definition.contracts["parameters"])),
        MappingProxyType(dict(definition.contracts["interfaces"])),
        MappingProxyType(dict(definition.contracts["presentation"])),
    )


def _interface_binding(
    authority,
    snapshot,
    level,
    owner_root: str,
    connection: object,
    caller,
    relation_root: str,
    participant_role: str,
) -> dict[str, object]:
    """Name the interface a socket is declared by, and what it declares.

    A socket is drawn because a definition declares an interface for it. If
    that declaration cannot be found the socket carries no interface facts
    rather than invented ones, so a renderer cannot present a guess as a
    contract.
    """
    # A socket exists because a relation puts this node in it. That relation
    # is the authority for the socket even when no interface is declared, so
    # it is named rather than leaving the socket unattributable. Direction,
    # cardinality and permission stay absent until a definition declares
    # them; a default here would assert a contract the graph never made.
    # With no declared interface the graph still states which side of the
    # relation this node occupies. That role is the direction it can honestly
    # report; cardinality and permission remain unknown rather than assumed.
    fallback = {
        "interface_root": relation_root,
        "direction": participant_role,
        "multiple": None,
        "permission": None,
        "authority_roots": (relation_root,),
    }
    instance = level.instances.get(owner_root)
    if instance is None or type(connection) is not str:
        return fallback
    definition_root = instance.get("definition")
    if type(definition_root) is not str:
        return fallback
    definition = read_definition(authority, definition_root, caller=caller)
    interfaces = definition.contracts.get("interfaces") or {}
    declared = interfaces.get(connection)
    if not isinstance(declared, Mapping):
        return fallback
    contract_root = definition.contract_roots.get("interfaces")
    identities = (
        property_identities(authority, snapshot, contract_root)
        if contract_root else {}
    )
    interface_root = (identities.get(connection) or {}).get(
        "property_root"
    ) or contract_root
    authority_roots = tuple(
        root for root in (interface_root, contract_root, definition.revision_root)
        if root and root in snapshot.cells
    )
    return {
        "interface_root": interface_root,
        "direction": declared.get("direction") or participant_role,
        "multiple": declared.get("multiple"),
        "permission": declared.get("permission"),
        "authority_roots": authority_roots,
    }


def _catalogue(
    authority: UnifiedAuthority,
    caller: CallerCommandCapability,
) -> tuple[LensCatalogueItem, ...]:
    roots = sorted(
        member.participant_id
        for member in relation_members(
            authority.store.snapshot(), authority.manifest.catalogue_root
        )
        if member.role_id == authority.role("definition")
    )
    items = tuple(
        _definition_item(read_definition(authority, root, caller=caller))
        for root in roots
    )
    return tuple(sorted(items, key=lambda item: (item.name.casefold(), item.root_id)))


def _properties(
    definition: DefinitionProjection,
    values: Mapping[str, object],
    identities: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[LensProperty, ...]:
    projected: list[LensProperty] = []
    for name, raw in sorted(definition.contracts["parameters"].items()):
        if not isinstance(raw, Mapping):
            raise InvalidCell("definition parameter presentation is invalid")
        metadata = dict(raw)
        editor = metadata.pop("editor", None)
        identity = (identities or {}).get(name) or {}
        projected.append(LensProperty(
            name,
            values.get(name),
            editor,
            MappingProxyType(dict(sorted(metadata.items()))),
            identity.get("property_root"),
            identity.get("owner"),
            identity.get("name_root"),
            identity.get("value_root"),
        ))
    return tuple(projected)


def project_unified_scope(
    authority: UnifiedAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    view_root: str | None = None,
    at_revision: int | None = None,
) -> UnifiedScopeLens:
    """Project one bounded scope without adding product-name dispatch."""
    if at_revision is None:
        snapshot = authority.store.snapshot()
    else:
        if type(at_revision) is not int or at_revision < 0:
            raise InvalidCell("scope revision is invalid")
        snapshot = authority.store.at(at_revision)
    level = read_scope_level(
        authority,
        scope_root,
        scope_root=scope_root,
        caller=caller,
        at_revision=snapshot.revision,
    )
    selected_root: str | None = None
    selected_roots: tuple[str, ...] = ()
    if view_root is not None:
        if type(view_root) is not str or not view_root:
            raise InvalidCell("view session root is invalid")
        if view_root != caller.session_root:
            raise InvalidCell("view session root does not belong to the caller")
        protocol = open_attention_protocol(snapshot)
        focus = active_focus(snapshot, protocol, session_root=view_root)
        if focus is not None:
            if focus.scope_root != scope_root:
                raise InvalidCell("active focus scope drifted")
            visible = frozenset(level.composition_roots)
            if not set(focus.selected_roots).issubset(visible):
                raise InvalidCell("active focus selection is outside the projected scope")
            selected_root = focus.primary_root
            selected_roots = focus.selected_roots
    relations = tuple(
        LensRelation(
            relation.root_id,
            relation.participants,
            MappingProxyType(dict(relation.properties)),
        )
        for relation in level.relations.values()
    )
    role_names = {authority.role(name): name for name in authority.roles}
    ports: dict[str, list[LensPort]] = {
        root: [] for root in level.composition_roots
    }
    for relation in relations:
        connection = relation.properties.get("connection")
        if connection is not None and type(connection) is not str:
            raise InvalidCell("relation connection presentation is invalid")
        participant_roots = tuple(root for _, root in relation.participants)
        members = read_relation(snapshot, relation.root_id, budget=1024)
        incidence_by_role: dict[str, str] = {}
        for member in members:
            role_name = role_names.get(member.role_id)
            if role_name and role_name not in incidence_by_role:
                incidence_by_role[role_name] = member.incidence_id
        source_incidence = incidence_by_role.get("source")
        target_incidence = incidence_by_role.get("target")
        if source_incidence is None or target_incidence is None:
            ordered = [member.incidence_id for member in members]
            if len(ordered) >= 2:
                source_incidence = source_incidence or ordered[0]
                target_incidence = target_incidence or next(
                    item for item in ordered if item != source_incidence
                )
        for role, root in relation.participants:
            if root not in ports:
                continue
            interface = _interface_binding(
                authority, snapshot, level, root, connection, caller,
                relation.root_id, role,
            )
            ports[root].append(LensPort(
                relation.root_id,
                role,
                connection,
                tuple(item for item in participant_roots if item != root),
                interface.get("interface_root"),
                interface.get("direction"),
                interface.get("multiple"),
                interface.get("permission"),
                bool(interface.get("interface_root")),
                source_incidence,
                target_incidence,
                interface.get("authority_roots", ()),
            ))

    nodes: list[LensNode] = []
    for root in level.composition_roots:
        instance = level.instances.get(root)
        if instance is None:
            nodes.append(LensNode(
                root,
                "composition",
                level.composition_labels[root] or "Untitled composition",
                None,
                None,
                None,
                None,
                None,
                (),
                (),
                tuple(sorted(ports[root], key=lambda item: item.relation_root)),
                True,
            ))
            continue
        definition_root = instance.get("definition")
        values = instance.get("values")
        if type(definition_root) is not str or not isinstance(values, Mapping):
            raise InvalidCell("instance lens projection is invalid")
        definition = read_definition(authority, definition_root, caller=caller)
        presentation = definition.contracts["presentation"]
        presentation_root = definition.contract_roots.get("presentation")
        presentation_identities = (
            property_identities(
                authority, authority.store.snapshot(), presentation_root
            )
            if presentation_root else {}
        )
        rules = definition.contracts["rules"]
        label = presentation.get("label", definition.name)
        if type(label) is not str or not label.strip():
            raise InvalidCell("definition label presentation is invalid")
        state_parameter = rules.get("state_parameter")
        if state_parameter is not None and (
            type(state_parameter) is not str or not state_parameter.strip()
        ):
            raise InvalidCell("definition state presentation is invalid")
        nodes.append(LensNode(
            root,
            "instance",
            label.strip(),
            definition.root_id,
            definition.name,
            definition.lifecycle,
            state_parameter,
            None if state_parameter is None else values.get(state_parameter),
            _text_tuple(presentation.get("panels"), "definition panel"),
            _properties(
                definition,
                values,
                property_identities(
                    authority, authority.store.snapshot(), root
                ),
            ),
            tuple(sorted(ports[root], key=lambda item: item.relation_root)),
            True,
            presentation_root,
            presentation.get("icon"),
            presentation.get("token"),
            presentation.get("color"),
            presentation.get("position"),
            presentation_identities.get("icon", {}).get("property_root"),
            presentation_identities.get("token", {}).get("property_root"),
            presentation_identities.get("position", {}).get("property_root"),
        ))
    return UnifiedScopeLens(
        authority.manifest.graph_id,
        level.revision,
        scope_root,
        level.label,
        selected_root,
        selected_roots,
        tuple(nodes),
        relations,
        _catalogue(authority, caller),
    )


def project_workshop_lens(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> UnifiedScopeLens:
    return project_unified_scope(
        authority,
        composition_root(authority, "Workshop", caller=caller),
        caller=caller,
    )


def scope_lens_payload(lens: UnifiedScopeLens) -> dict[str, object]:
    """Convert the immutable projection to transport-safe plain data."""
    def plain(value: object) -> object:
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: plain(getattr(value, field.name))
                for field in fields(value)
            }
        if isinstance(value, Mapping):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(item) for item in value]
        if value is None or type(value) in {bool, int, float, str}:
            return value
        raise InvalidCell("scope lens contains non-transport data")

    payload = plain(lens)
    if not isinstance(payload, dict):
        raise InvalidCell("scope lens payload is invalid")
    return payload


__all__ = [
    "LensCatalogueItem",
    "LensNode",
    "LensPort",
    "LensProperty",
    "LensRelation",
    "UnifiedScopeLens",
    "project_unified_scope",
    "project_workshop_lens",
    "scope_lens_payload",
]
