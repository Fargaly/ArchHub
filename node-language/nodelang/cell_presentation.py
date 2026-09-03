"""Graph-defined progressive presentation over the universal Cell floor.

The protocol does not introduce a persisted panel, tab, widget, or node type.
It describes presentation compositions with ordinary relation Cells.  A host
renderer may project the admitted composition to HTML, but labels, ordering,
lens membership, authority, reusable content bindings, and current focus stay
in the graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_protocols import CellBatch, RelationBuild, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "panel",
    "label",
    "lens",
    "component",
    "source",
    "presenter",
    "authority",
    "focus",
)


@dataclass(frozen=True, slots=True)
class PresentationProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown presentation role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class PresentationComponent:
    root_id: str
    label_root: str
    source_root: str
    presenter_root: str


@dataclass(frozen=True, slots=True)
class PresentationPanel:
    root_id: str
    label_root: str
    lens_roots: tuple[str, ...]
    component_roots: tuple[str, ...]
    authority_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PresentationProjection:
    root_id: str
    active_panel_root: str | None
    panels: tuple[PresentationPanel, ...]
    components: Mapping[str, PresentationComponent]


def compose_presentation_protocol(
    batch: CellBatch,
    *,
    prefix: str = "presentation-protocol",
) -> PresentationProtocol:
    """Add the small, domain-neutral presentation vocabulary to ``batch``."""
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in ROLE_NAMES
    }
    for name, root_id in roles.items():
        batch.add(Cell(
            root_id,
            NULL_CELL_ID,
            NULL_CELL_ID,
            name.encode("ascii"),
        ))
    root_id = "%s:root" % prefix
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    return PresentationProtocol(root_id, MappingProxyType(roles))


def compose_component(
    batch: CellBatch,
    protocol: PresentationProtocol,
    *,
    root_id: str,
    label_root: str,
    source_root: str,
    presenter_root: str,
) -> str:
    batch.relation((
        (protocol.role("label"), label_root),
        (protocol.role("source"), source_root),
        (protocol.role("presenter"), presenter_root),
    ), relation_id=root_id)
    return root_id


def compose_panel(
    batch: CellBatch,
    protocol: PresentationProtocol,
    *,
    root_id: str,
    label_root: str,
    lens_roots: Iterable[str],
    component_roots: Iterable[str],
    authority_roots: Iterable[str] = (),
) -> str:
    batch.relation((
        (protocol.role("label"), label_root),
        *((protocol.role("lens"), root) for root in lens_roots),
        *((protocol.role("component"), root) for root in component_roots),
        *((protocol.role("authority"), root) for root in authority_roots),
    ), relation_id=root_id)
    return root_id


def compose_presentation(
    batch: CellBatch,
    protocol: PresentationProtocol,
    *,
    root_id: str,
    panel_roots: Iterable[str],
) -> str:
    batch.relation(
        ((protocol.role("panel"), root) for root in panel_roots),
        relation_id=root_id,
    )
    return root_id


def compose_panel_focus(
    batch: CellBatch,
    protocol: PresentationProtocol,
    *,
    root_id: str,
    panel_root: str,
) -> RelationBuild:
    return batch.relation(
        ((protocol.role("focus"), panel_root),),
        relation_id=root_id,
    )


def _single(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("presentation %s must have exactly one value" % label)
    return values[0]


def read_component(
    snapshot: Snapshot,
    protocol: PresentationProtocol,
    root_id: str,
) -> PresentationComponent:
    members = read_relation(snapshot, root_id, budget=32)
    return PresentationComponent(
        root_id,
        _single(members, protocol.role("label"), "component label"),
        _single(members, protocol.role("source"), "component source"),
        _single(members, protocol.role("presenter"), "component presenter"),
    )


def read_panel(
    snapshot: Snapshot,
    protocol: PresentationProtocol,
    root_id: str,
) -> PresentationPanel:
    members = read_relation(snapshot, root_id, budget=128)
    label_root = _single(members, protocol.role("label"), "panel label")
    lens_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("lens")
    )
    component_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("component")
    )
    authority_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("authority")
    )
    if not lens_roots:
        raise InvalidCell("presentation panel has no admitted lens")
    if not component_roots:
        raise InvalidCell("presentation panel has no content binding")
    return PresentationPanel(
        root_id,
        label_root,
        lens_roots,
        component_roots,
        authority_roots,
    )


def project_presentation(
    snapshot: Snapshot,
    protocol: PresentationProtocol,
    presentation_root: str,
    *,
    active_lens_root: str,
    focus_binding_root: str,
    available_component_roots: Iterable[str],
    principal_roots: Iterable[str],
) -> PresentationProjection:
    """Resolve applicable, non-empty panels without inventing hidden tabs."""
    members = read_relation(snapshot, presentation_root, budget=256)
    panel_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("panel")
    )
    if not panel_roots:
        raise InvalidCell("presentation has no panels")

    available = set(available_component_roots)
    principals = set(principal_roots)
    panels: list[PresentationPanel] = []
    components: dict[str, PresentationComponent] = {}
    for panel_root in panel_roots:
        panel = read_panel(snapshot, protocol, panel_root)
        if active_lens_root not in panel.lens_roots:
            continue
        if panel.authority_roots and principals.isdisjoint(
            panel.authority_roots
        ):
            continue
        admitted_components = tuple(
            root for root in panel.component_roots if root in available
        )
        if not admitted_components:
            continue
        projected = PresentationPanel(
            panel.root_id,
            panel.label_root,
            panel.lens_roots,
            admitted_components,
            panel.authority_roots,
        )
        panels.append(projected)
        for component_root in admitted_components:
            components.setdefault(
                component_root,
                read_component(snapshot, protocol, component_root),
            )

    focus_members = read_relation(snapshot, focus_binding_root, budget=16)
    preferred = _single(
        focus_members, protocol.role("focus"), "panel focus"
    )
    admitted_roots = {panel.root_id for panel in panels}
    active = preferred if preferred in admitted_roots else (
        panels[0].root_id if panels else None
    )
    return PresentationProjection(
        presentation_root,
        active,
        tuple(panels),
        MappingProxyType(components),
    )


__all__ = [
    "ROLE_NAMES",
    "PresentationProtocol",
    "PresentationComponent",
    "PresentationPanel",
    "PresentationProjection",
    "compose_presentation_protocol",
    "compose_component",
    "compose_panel",
    "compose_presentation",
    "compose_panel_focus",
    "read_component",
    "read_panel",
    "project_presentation",
]
