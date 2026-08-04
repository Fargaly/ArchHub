"""Generic visual scope projection over the one Unified Cell authority."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_attention import active_focus, open_attention_protocol
from .unified_authority import (
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


@dataclass(frozen=True, slots=True)
class LensPort:
    relation_root: str
    participant_role: str
    connection: str | None
    other_roots: tuple[str, ...]


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
) -> tuple[LensProperty, ...]:
    projected: list[LensProperty] = []
    for name, raw in sorted(definition.contracts["parameters"].items()):
        if not isinstance(raw, Mapping):
            raise InvalidCell("definition parameter presentation is invalid")
        metadata = dict(raw)
        editor = metadata.pop("editor", None)
        projected.append(LensProperty(
            name,
            values.get(name),
            editor,
            MappingProxyType(dict(sorted(metadata.items()))),
        ))
    return tuple(projected)


def project_unified_scope(
    authority: UnifiedAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    view_root: str | None = None,
) -> UnifiedScopeLens:
    """Project one bounded scope without adding product-name dispatch."""
    snapshot = authority.store.snapshot()
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
    ports: dict[str, list[LensPort]] = {
        root: [] for root in level.composition_roots
    }
    for relation in relations:
        connection = relation.properties.get("connection")
        if connection is not None and type(connection) is not str:
            raise InvalidCell("relation connection presentation is invalid")
        participant_roots = tuple(root for _, root in relation.participants)
        for role, root in relation.participants:
            if root not in ports:
                continue
            ports[root].append(LensPort(
                relation.root_id,
                role,
                connection,
                tuple(item for item in participant_roots if item != root),
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
            _properties(definition, values),
            tuple(sorted(ports[root], key=lambda item: item.relation_root)),
            True,
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
