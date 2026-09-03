"""Cell-native icon catalogue and safe SVG geometry projection.

The generated Lucide extract is import evidence only. Icon geometry,
provenance, catalogue membership, and control assignments are materialized as
ordinary relation Cells before the application can project them.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import compose_relation_cells, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


LUCIDE_VERSION = "1.25.0"
PROTOCOL_PREFIX = "app:icon-protocol"
CATALOG_ROOT = "app:icon-catalog:lucide:1.25.0"
SOURCE_ROOT = "app:icon-source:lucide-static:1.25.0"
SOURCE_PATH = Path(__file__).with_name("assets") / "lucide-icons-1.25.0.json"

ROLE_NAMES = (
    "vocabulary-member",
    "catalog-member",
    "name",
    "source",
    "package",
    "version",
    "license",
    "homepage",
    "repository",
    "source-digest",
    "geometry-digest",
    "view-box",
    "primitive",
    "order",
    "tag",
    "attribute",
    "attribute-name",
    "attribute-value",
    "owner",
    "icon",
)

ALLOWED_SVG_TAGS = frozenset({
    "path", "circle", "line", "rect", "polyline", "polygon",
})
ALLOWED_SVG_ATTRIBUTES = frozenset({
    "d", "cx", "cy", "r", "x", "y", "width", "height", "rx", "ry",
    "x1", "x2", "y1", "y2", "points",
})
_NUMBER = re.compile(r"^-?(?:\d+(?:\.\d+)?|\.\d+)$")
_POINTS = re.compile(
    r"^-?(?:\d+(?:\.\d+)?|\.\d+)(?:[ ,]+-?(?:\d+(?:\.\d+)?|\.\d+))+$"
)
_PATH_DATA = re.compile(r"^[MmZzLlHhVvCcSsQqTtAa0-9.,+\- ]+$")


@dataclass(frozen=True, slots=True)
class IconProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown icon role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class IconSourceProjection:
    root_id: str
    package: str
    version: str
    license: str
    homepage: str
    repository: str
    source_sha256: str
    selected_geometry_sha256: str


@dataclass(frozen=True, slots=True)
class IconPrimitiveProjection:
    root_id: str
    order: int
    tag: str
    attributes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class IconProjection:
    root_id: str
    name: str
    source_root: str
    view_box: str
    primitives: tuple[IconPrimitiveProjection, ...]


@dataclass(frozen=True, slots=True)
class IconCatalogProjection:
    root_id: str
    source: IconSourceProjection
    icons: Mapping[str, IconProjection]


@dataclass(frozen=True, slots=True)
class IconCatalogBuild:
    protocol: IconProtocol
    catalog_root: str
    source_root: str
    icon_roots: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class IconAssignmentProjection:
    root_id: str
    owner_root: str
    icon_root: str


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("icon text leaf is missing or invalid") from exc


def _single(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("icon %s must have exactly one value" % label)
    return values[0]


def _source_document() -> dict:
    try:
        document = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCell("Lucide import evidence is missing or invalid") from exc
    if set(document) != {"schema", "package", "icons"}:
        raise InvalidCell("Lucide import evidence shape drifted")
    if document["schema"] != "archhub-lucide-source-v1":
        raise InvalidCell("Lucide import evidence schema drifted")
    package = document["package"]
    expected_package_fields = {
        "name", "version", "license", "homepage", "repository", "source",
        "source_sha256", "selected_geometry_sha256",
    }
    if set(package) != expected_package_fields:
        raise InvalidCell("Lucide package evidence shape drifted")
    if (
        package["name"] != "lucide-static"
        or package["version"] != LUCIDE_VERSION
        or package["license"] != "ISC"
        or package["source"] != "icon-nodes.json"
    ):
        raise InvalidCell("Lucide package evidence is not the admitted release")
    canonical = json.dumps(
        document["icons"], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != package[
        "selected_geometry_sha256"
    ]:
        raise InvalidCell("Lucide selected geometry digest drifted")
    return document


def _leaf(expected: dict[str, Cell], root_id: str, value: str) -> str:
    cell = Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
    previous = expected.get(root_id)
    if previous is not None and previous != cell:
        raise InvalidCell("icon build contains an identity collision")
    expected[root_id] = cell
    return root_id


def _relation(
    expected: dict[str, Cell],
    root_id: str,
    members,
) -> str:
    for cell in compose_relation_cells(members, relation_id=root_id).cells:
        previous = expected.get(cell.id)
        if previous is not None and previous != cell:
            raise InvalidCell("icon build contains a relation collision")
        expected[cell.id] = cell
    return root_id


def ensure_archhub_icon_catalog(store: CellStore) -> IconCatalogBuild:
    """Materialize the admitted source as stable, recursively inspectable Cells."""
    document = _source_document()
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
    package = document["package"]
    source_members = []
    for role, key in (
        ("package", "name"),
        ("version", "version"),
        ("license", "license"),
        ("homepage", "homepage"),
        ("repository", "repository"),
        ("source-digest", "source_sha256"),
        ("geometry-digest", "selected_geometry_sha256"),
    ):
        leaf = _leaf(
            expected,
            "%s:%s" % (SOURCE_ROOT, role),
            str(package[key]),
        )
        source_members.append((roles[role], leaf))
    _relation(expected, SOURCE_ROOT, source_members)

    icon_roots: dict[str, str] = {}
    for name, primitives in document["icons"].items():
        if not isinstance(name, str) or not isinstance(primitives, list):
            raise InvalidCell("Lucide icon evidence is malformed")
        token = name.lower()
        icon_root = "app:icon:lucide:%s" % token
        name_root = _leaf(expected, icon_root + ":name", name)
        view_box_root = _leaf(expected, icon_root + ":view-box", "0 0 24 24")
        primitive_roots = []
        for index, primitive in enumerate(primitives):
            if (
                not isinstance(primitive, list)
                or len(primitive) != 2
                or not isinstance(primitive[0], str)
                or not isinstance(primitive[1], dict)
            ):
                raise InvalidCell("Lucide primitive evidence is malformed")
            primitive_root = "%s:primitive:%d" % (icon_root, index)
            order_root = _leaf(
                expected, primitive_root + ":order", str(index)
            )
            tag_root = _leaf(
                expected, primitive_root + ":tag", primitive[0]
            )
            attribute_roots = []
            for attribute_index, (attribute_name, value) in enumerate(
                primitive[1].items()
            ):
                attribute_root = "%s:attribute:%d" % (
                    primitive_root, attribute_index
                )
                attribute_name_root = _leaf(
                    expected, attribute_root + ":name", attribute_name
                )
                attribute_value_root = _leaf(
                    expected, attribute_root + ":value", str(value)
                )
                _relation(expected, attribute_root, (
                    (roles["attribute-name"], attribute_name_root),
                    (roles["attribute-value"], attribute_value_root),
                ))
                attribute_roots.append(attribute_root)
            _relation(expected, primitive_root, (
                (roles["order"], order_root),
                (roles["tag"], tag_root),
                *((roles["attribute"], root) for root in attribute_roots),
            ))
            primitive_roots.append(primitive_root)
        _relation(expected, icon_root, (
            (roles["name"], name_root),
            (roles["source"], SOURCE_ROOT),
            (roles["view-box"], view_box_root),
            *((roles["primitive"], root) for root in primitive_roots),
        ))
        icon_roots[name] = icon_root
    _relation(expected, CATALOG_ROOT, (
        (roles["source"], SOURCE_ROOT),
        *((roles["catalog-member"], root) for root in icon_roots.values()),
    ))

    snapshot = store.snapshot()
    for root_id, cell in expected.items():
        existing = snapshot.cells.get(root_id)
        if existing is not None and existing != cell:
            raise InvalidCell("persisted icon catalogue drifted at %s" % root_id)
    missing = tuple(
        cell for root_id, cell in expected.items()
        if root_id not in snapshot.cells
    )
    if missing:
        store.commit(snapshot.revision, create=missing)
    return IconCatalogBuild(
        IconProtocol(protocol_root, MappingProxyType(roles)),
        CATALOG_ROOT,
        SOURCE_ROOT,
        MappingProxyType(icon_roots),
    )


def _validate_attribute(name: str, value: str) -> None:
    if name not in ALLOWED_SVG_ATTRIBUTES:
        raise InvalidCell("icon attribute is outside the safe SVG allowlist")
    if any(character in value for character in '<>"\'&;'):
        raise InvalidCell("icon attribute contains unsafe markup characters")
    if name == "d":
        valid = bool(_PATH_DATA.fullmatch(value))
    elif name == "points":
        valid = bool(_POINTS.fullmatch(value))
    else:
        valid = bool(_NUMBER.fullmatch(value))
    if not valid:
        raise InvalidCell("icon attribute value is outside the safe geometry grammar")


def _project_source(
    snapshot: Snapshot,
    protocol: IconProtocol,
    source_root: str,
) -> IconSourceProjection:
    members = read_relation(snapshot, source_root, budget=128)
    values = {
        role: _text(snapshot, _single(members, protocol.role(role), role))
        for role in (
            "package", "version", "license", "homepage", "repository",
            "source-digest", "geometry-digest",
        )
    }
    if values["version"] != LUCIDE_VERSION or values["license"] != "ISC":
        raise InvalidCell("icon source release drifted")
    for digest_role in ("source-digest", "geometry-digest"):
        if not re.fullmatch(r"[0-9a-f]{64}", values[digest_role]):
            raise InvalidCell("icon source digest is invalid")
    return IconSourceProjection(
        source_root,
        values["package"],
        values["version"],
        values["license"],
        values["homepage"],
        values["repository"],
        values["source-digest"],
        values["geometry-digest"],
    )


def project_icon(
    snapshot: Snapshot,
    protocol: IconProtocol,
    icon_root: str,
) -> IconProjection:
    members = read_relation(snapshot, icon_root, budget=512)
    name = _text(snapshot, _single(members, protocol.role("name"), "name"))
    source_root = _single(members, protocol.role("source"), "source")
    _project_source(snapshot, protocol, source_root)
    view_box = _text(
        snapshot, _single(members, protocol.role("view-box"), "view box")
    )
    if view_box != "0 0 24 24":
        raise InvalidCell("icon view box is outside the admitted geometry")
    projected = []
    seen_orders: set[int] = set()
    for member in members:
        if member.role_id != protocol.role("primitive"):
            continue
        primitive_members = read_relation(
            snapshot, member.participant_id, budget=128
        )
        order_text = _text(
            snapshot,
            _single(primitive_members, protocol.role("order"), "primitive order"),
        )
        if not order_text.isdigit():
            raise InvalidCell("icon primitive order is invalid")
        order = int(order_text)
        if order in seen_orders:
            raise InvalidCell("icon primitive order is duplicated")
        seen_orders.add(order)
        tag = _text(
            snapshot,
            _single(primitive_members, protocol.role("tag"), "primitive tag"),
        )
        if tag not in ALLOWED_SVG_TAGS:
            raise InvalidCell("icon tag is outside the safe SVG allowlist")
        attributes: dict[str, str] = {}
        for attribute_member in primitive_members:
            if attribute_member.role_id != protocol.role("attribute"):
                continue
            attribute = read_relation(
                snapshot, attribute_member.participant_id, budget=32
            )
            attribute_name = _text(
                snapshot,
                _single(
                    attribute,
                    protocol.role("attribute-name"),
                    "attribute name",
                ),
            )
            attribute_value = _text(
                snapshot,
                _single(
                    attribute,
                    protocol.role("attribute-value"),
                    "attribute value",
                ),
            )
            if attribute_name in attributes:
                raise InvalidCell("icon attribute is duplicated")
            _validate_attribute(attribute_name, attribute_value)
            attributes[attribute_name] = attribute_value
        if not attributes:
            raise InvalidCell("icon primitive has no geometry")
        projected.append(IconPrimitiveProjection(
            member.participant_id,
            order,
            tag,
            MappingProxyType(attributes),
        ))
    projected.sort(key=lambda item: item.order)
    if not projected or [item.order for item in projected] != list(
        range(len(projected))
    ):
        raise InvalidCell("icon primitive sequence is incomplete")
    return IconProjection(icon_root, name, source_root, view_box, tuple(projected))


def project_icon_catalog(
    snapshot: Snapshot,
    protocol: IconProtocol,
    catalog_root: str,
) -> IconCatalogProjection:
    members = read_relation(snapshot, catalog_root, budget=4096)
    source_root = _single(members, protocol.role("source"), "catalog source")
    source = _project_source(snapshot, protocol, source_root)
    icons: dict[str, IconProjection] = {}
    for member in members:
        if member.role_id != protocol.role("catalog-member"):
            continue
        icon = project_icon(snapshot, protocol, member.participant_id)
        if icon.source_root != source_root or icon.name in icons:
            raise InvalidCell("icon catalogue membership drifted")
        icons[icon.name] = icon
    if not icons:
        raise InvalidCell("icon catalogue is empty")
    return IconCatalogProjection(
        catalog_root, source, MappingProxyType(icons)
    )


def assign_icon(
    store: CellStore,
    protocol: IconProtocol,
    *,
    owner_root: str,
    icon_root: str,
    assignment_root: str,
) -> str:
    snapshot = store.snapshot()
    if owner_root not in snapshot.cells:
        raise InvalidCell("icon assignment owner is missing")
    project_icon(snapshot, protocol, icon_root)
    composed = compose_relation_cells((
        (protocol.role("owner"), owner_root),
        (protocol.role("icon"), icon_root),
    ), relation_id=assignment_root)
    existing = tuple(
        snapshot.cells.get(cell.id) for cell in composed.cells
    )
    if any(cell is not None for cell in existing):
        if any(current != expected for current, expected in zip(existing, composed.cells)):
            raise InvalidCell("persisted icon assignment drifted")
        return assignment_root
    store.commit(snapshot.revision, create=composed.cells)
    return assignment_root


def project_icon_assignment(
    snapshot: Snapshot,
    protocol: IconProtocol,
    assignment_root: str,
) -> IconAssignmentProjection:
    members = read_relation(snapshot, assignment_root, budget=32)
    owner_root = _single(members, protocol.role("owner"), "assignment owner")
    icon_root = _single(members, protocol.role("icon"), "assignment icon")
    if owner_root not in snapshot.cells:
        raise InvalidCell("icon assignment owner is missing")
    project_icon(snapshot, protocol, icon_root)
    return IconAssignmentProjection(assignment_root, owner_root, icon_root)


__all__ = [
    "ALLOWED_SVG_ATTRIBUTES",
    "ALLOWED_SVG_TAGS",
    "CATALOG_ROOT",
    "IconAssignmentProjection",
    "IconCatalogBuild",
    "IconCatalogProjection",
    "IconPrimitiveProjection",
    "IconProjection",
    "IconProtocol",
    "IconSourceProjection",
    "LUCIDE_VERSION",
    "ROLE_NAMES",
    "SOURCE_PATH",
    "SOURCE_ROOT",
    "assign_icon",
    "ensure_archhub_icon_catalog",
    "project_icon",
    "project_icon_assignment",
    "project_icon_catalog",
]
