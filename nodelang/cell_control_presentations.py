"""Graph-authored identities and presentation for visible application controls.

The protocol contains no command dispatcher. It binds a control identity to
its human label, accessible title, visual zone, order, and an explicit icon
assignment relation. Interaction authority remains a separate graph protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_icons import (
    IconCatalogBuild,
    IconProtocol,
    project_icon,
    project_icon_assignment,
)
from .cell_protocols import compose_relation_cells, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


PROTOCOL_PREFIX = "app:control-presentation-protocol"
CATALOG_ROOT = "app:control-presentation-catalog:v1"
ROLE_NAMES = (
    "vocabulary-member",
    "catalog-member",
    "owner",
    "label",
    "title",
    "zone",
    "order",
    "icon-assignment",
)


@dataclass(frozen=True, slots=True)
class ControlSpec:
    owner_root: str
    label: str
    title: str
    zone: str
    order: int
    icon_name: str


CONTROL_SPECS = (
    ControlSpec("app:control:rail:home", "Home", "Home", "application-rail", 10, "house"),
    ControlSpec("app:control:rail:search", "Search", "Search", "application-rail", 20, "search"),
    ControlSpec("app:control:rail:share", "Share", "Share", "application-rail", 30, "share-2"),
    ControlSpec("app:control:rail:settings", "Settings", "Settings", "application-rail", 40, "settings"),
    ControlSpec("app:control:library:place", "Place", "Place on canvas", "library", 10, "plus"),
    ControlSpec("app:control:canvas:scope-up", "Up", "Up one graph level", "canvas-toolbar", 10, "arrow-left"),
    ControlSpec("app:control:canvas:zoom-out", "Zoom out", "Zoom out", "canvas-toolbar", 20, "zoom-out"),
    ControlSpec("app:control:canvas:zoom-in", "Zoom in", "Zoom in", "canvas-toolbar", 30, "zoom-in"),
    ControlSpec("app:control:canvas:fit", "Fit", "Fit canvas", "canvas-toolbar", 40, "maximize"),
    ControlSpec("app:control:canvas:undo", "Undo", "Undo graph transaction", "canvas-toolbar", 45, "undo-2"),
    ControlSpec("app:control:canvas:redo", "Redo", "Redo graph transaction", "canvas-toolbar", 46, "redo-2"),
    ControlSpec("app:control:canvas:group", "Group", "Compose selected nodes", "canvas-toolbar", 50, "group"),
    ControlSpec("app:control:canvas:ungroup", "Ungroup", "Expose this composition's direct members", "canvas-toolbar", 60, "ungroup"),
    ControlSpec(
        "app:control:inspector:add-property",
        "Add parameter",
        "Add parameter",
        "inspector-properties",
        10,
        "plus",
    ),
    ControlSpec(
        "app:control:inspector:add-interface",
        "Add interface",
        "Add interface",
        "inspector-interfaces",
        10,
        "plus",
    ),
)


@dataclass(frozen=True, slots=True)
class ControlPresentationProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown control-presentation role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ControlPresentation:
    root_id: str
    owner_root: str
    label: str
    title: str
    zone: str
    order: int
    icon_assignment_root: str
    icon_root: str


@dataclass(frozen=True, slots=True)
class ControlCatalogProjection:
    root_id: str
    controls: Mapping[str, ControlPresentation]


@dataclass(frozen=True, slots=True)
class ControlCatalogBuild:
    protocol: ControlPresentationProtocol
    catalog_root: str
    control_roots: Mapping[str, str]


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("control presentation text is missing or invalid") from exc


def _single(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("control %s must have exactly one value" % label)
    return values[0]


def _leaf(expected: dict[str, Cell], root_id: str, value: str) -> str:
    cell = Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
    previous = expected.get(root_id)
    if previous is not None and previous != cell:
        raise InvalidCell("control presentation identity collision")
    expected[root_id] = cell
    return root_id


def _relation(expected: dict[str, Cell], root_id: str, members) -> str:
    for cell in compose_relation_cells(members, relation_id=root_id).cells:
        previous = expected.get(cell.id)
        if previous is not None and previous != cell:
            raise InvalidCell("control presentation relation collision")
        expected[cell.id] = cell
    return root_id


def _is_additive_catalog_tail_upgrade(
    snapshot: Snapshot,
    roles: Mapping[str, str],
    control_roots: Mapping[str, str],
    drifted: tuple[tuple[str, Cell, Cell], ...],
) -> bool:
    if len(drifted) != 1 or CATALOG_ROOT not in snapshot.cells:
        return False
    root_id, existing, expected = drifted[0]
    try:
        existing_members = read_relation(snapshot, CATALOG_ROOT, budget=128)
    except InvalidCell:
        return False
    expected_members = tuple(
        (roles["catalog-member"], root) for root in control_roots.values()
    )
    existing_pairs = tuple(
        (member.role_id, member.participant_id)
        for member in existing_members
    )
    if (
        not existing_pairs
        or len(existing_pairs) >= len(expected_members)
        or existing_pairs != expected_members[:len(existing_pairs)]
    ):
        return False
    tail_index = len(existing_pairs) - 1
    expected_tail_id = (
        CATALOG_ROOT if tail_index == 0
        else "%s:chain:%s" % (CATALOG_ROOT, tail_index)
    )
    return (
        root_id == expected_tail_id
        and existing.id == expected.id
        and existing.link0 == expected.link0
        and existing.link1 == NULL_CELL_ID
        and expected.link1 != NULL_CELL_ID
        and existing.atom == expected.atom
    )


def ensure_archhub_control_catalog(
    store: CellStore,
    icon_catalog: IconCatalogBuild,
) -> ControlCatalogBuild:
    """Materialize current visible controls without product action dispatch."""
    expected: dict[str, Cell] = {}
    roles = {
        name: "%s:role:%s" % (PROTOCOL_PREFIX, name)
        for name in ROLE_NAMES
    }
    for name, root_id in roles.items():
        _leaf(expected, root_id, name)
    protocol_root = _relation(
        expected,
        PROTOCOL_PREFIX + ":root",
        ((roles["vocabulary-member"], root) for root in roles.values()),
    )

    snapshot = store.snapshot()
    control_roots: dict[str, str] = {}
    for specification in CONTROL_SPECS:
        icon_root = icon_catalog.icon_roots.get(specification.icon_name)
        if icon_root is None:
            raise InvalidCell("control references an icon outside the admitted catalogue")
        project_icon(snapshot, icon_catalog.protocol, icon_root)
        token = specification.owner_root.removeprefix("app:control:")
        control_root = "app:control-presentation:%s" % token
        owner_root = _leaf(
            expected, specification.owner_root, specification.label
        )
        label_root = _leaf(
            expected, control_root + ":label", specification.label
        )
        title_root = _leaf(
            expected, control_root + ":title", specification.title
        )
        zone_root = _leaf(
            expected, control_root + ":zone", specification.zone
        )
        order_root = _leaf(
            expected, control_root + ":order", str(specification.order)
        )
        assignment_root = control_root + ":icon-assignment"
        _relation(expected, assignment_root, (
            (icon_catalog.protocol.role("owner"), owner_root),
            (icon_catalog.protocol.role("icon"), icon_root),
        ))
        _relation(expected, control_root, (
            (roles["owner"], owner_root),
            (roles["label"], label_root),
            (roles["title"], title_root),
            (roles["zone"], zone_root),
            (roles["order"], order_root),
            (roles["icon-assignment"], assignment_root),
        ))
        control_roots[specification.owner_root] = control_root
    _relation(expected, CATALOG_ROOT, (
        (roles["catalog-member"], root) for root in control_roots.values()
    ))

    drifted: list[tuple[str, Cell, Cell]] = []
    for root_id, expected_cell in expected.items():
        existing = snapshot.cells.get(root_id)
        if existing is not None and existing != expected_cell:
            drifted.append((root_id, existing, expected_cell))
    if drifted and not _is_additive_catalog_tail_upgrade(
        snapshot, roles, control_roots, tuple(drifted)
    ):
        raise InvalidCell(
            "persisted control presentation drifted at %s" % drifted[0][0]
        )
    missing = tuple(
        cell for root_id, cell in expected.items()
        if root_id not in snapshot.cells
    )
    replacement = tuple(expected_cell for _root, _old, expected_cell in drifted)
    if missing or replacement:
        store.commit(snapshot.revision, create=missing, replace=replacement)
    return ControlCatalogBuild(
        ControlPresentationProtocol(protocol_root, MappingProxyType(roles)),
        CATALOG_ROOT,
        MappingProxyType(control_roots),
    )


def project_control(
    snapshot: Snapshot,
    protocol: ControlPresentationProtocol,
    icon_protocol: IconProtocol,
    control_root: str,
) -> ControlPresentation:
    members = read_relation(snapshot, control_root, budget=128)
    owner_root = _single(members, protocol.role("owner"), "owner")
    label = _text(snapshot, _single(members, protocol.role("label"), "label"))
    title = _text(snapshot, _single(members, protocol.role("title"), "title"))
    zone = _text(snapshot, _single(members, protocol.role("zone"), "zone"))
    order_text = _text(
        snapshot, _single(members, protocol.role("order"), "order")
    )
    if not order_text.isdigit():
        raise InvalidCell("control order is invalid")
    assignment_root = _single(
        members, protocol.role("icon-assignment"), "icon assignment"
    )
    assignment = project_icon_assignment(
        snapshot, icon_protocol, assignment_root
    )
    if assignment.owner_root != owner_root:
        raise InvalidCell("control icon assignment left its owner")
    if not label or not title:
        raise InvalidCell("control accessible text is empty")
    return ControlPresentation(
        control_root,
        owner_root,
        label,
        title,
        zone,
        int(order_text),
        assignment_root,
        assignment.icon_root,
    )


def project_control_catalog(
    snapshot: Snapshot,
    protocol: ControlPresentationProtocol,
    icon_protocol: IconProtocol,
    catalog_root: str,
) -> ControlCatalogProjection:
    members = read_relation(snapshot, catalog_root, budget=512)
    controls: dict[str, ControlPresentation] = {}
    zone_orders: set[tuple[str, int]] = set()
    for member in members:
        if member.role_id != protocol.role("catalog-member"):
            raise InvalidCell("control catalogue has an undeclared role")
        control = project_control(
            snapshot, protocol, icon_protocol, member.participant_id
        )
        if control.owner_root in controls:
            raise InvalidCell("control catalogue repeats an owner")
        zone_order = (control.zone, control.order)
        if zone_order in zone_orders:
            raise InvalidCell("control catalogue repeats a zone order")
        zone_orders.add(zone_order)
        controls[control.owner_root] = control
    if not controls:
        raise InvalidCell("control catalogue is empty")
    ordered = dict(sorted(
        controls.items(), key=lambda item: (item[1].zone, item[1].order)
    ))
    return ControlCatalogProjection(
        catalog_root, MappingProxyType(ordered)
    )


__all__ = [
    "CATALOG_ROOT",
    "CONTROL_SPECS",
    "ControlCatalogBuild",
    "ControlCatalogProjection",
    "ControlPresentation",
    "ControlPresentationProtocol",
    "ControlSpec",
    "ensure_archhub_control_catalog",
    "project_control",
    "project_control_catalog",
]
