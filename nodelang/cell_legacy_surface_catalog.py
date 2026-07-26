"""Graph-held catalogue for superseded legacy UI surface names.

The old public WebShell has a large Python registry of named surfaces. This
module does not render those surfaces and does not import that registry. It
mirrors an already-extracted list into ordinary Universal Cells so the registry
is visible, digest-checked, and fenced as non-authoritative while it is being
consumed by the Universal Cell application graph.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import CellBatch, RelationMember, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "item",
    "name",
    "index",
    "source-digest",
    "lifecycle",
    "superseded-by",
    "promotion-allowed",
)

DEFAULT_CATALOG_ROOT = "legacy-grand-map-ui:surface-catalog:v1"
DEFAULT_LIFECYCLE = "superseded_migration_evidence"
DEFAULT_SUPERSEDED_BY = "10.PRODUCT/13.NODE-LANGUAGE Universal Cell authority"


@dataclass(frozen=True, slots=True)
class LegacySurfaceCatalogProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown legacy surface catalogue role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class LegacySurfaceCatalogBuild:
    root_id: str
    surface_roots: tuple[str, ...]


def surface_names_digest(surface_names: tuple[str, ...]) -> str:
    """Return the frozen registry digest used by the public WIP courts."""
    names = _validate_names(surface_names)
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()


def bootstrap_legacy_surface_catalog_protocol(
    store: CellStore,
    *,
    prefix: str = "legacy-surface-catalog-protocol",
) -> LegacySurfaceCatalogProtocol:
    roles = MappingProxyType({
        name: "%s:role:%s" % (prefix, name)
        for name in ROLE_NAMES
    })
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    root_id = prefix + ":root"
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return LegacySurfaceCatalogProtocol(root_id, roles)


def build_legacy_surface_catalog(
    store: CellStore,
    protocol: LegacySurfaceCatalogProtocol,
    surface_names: tuple[str, ...],
    *,
    source_digest: str | None = None,
    catalog_id: str = DEFAULT_CATALOG_ROOT,
    lifecycle: str = DEFAULT_LIFECYCLE,
    superseded_by: str = DEFAULT_SUPERSEDED_BY,
) -> LegacySurfaceCatalogBuild:
    names = _validate_names(surface_names)
    digest = source_digest or surface_names_digest(names)
    if digest != surface_names_digest(names):
        raise InvalidCell("legacy surface registry digest does not match names")

    source_digest_root = catalog_id + ":source-digest"
    lifecycle_root = catalog_id + ":lifecycle"
    superseded_by_root = catalog_id + ":superseded-by"
    promotion_allowed_root = catalog_id + ":promotion-allowed"
    batch = CellBatch(store)
    for root_id, value in (
        (source_digest_root, digest),
        (lifecycle_root, lifecycle),
        (superseded_by_root, superseded_by),
        (promotion_allowed_root, "false"),
    ):
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")))

    surface_roots = []
    for index, name in enumerate(names):
        surface_root = "%s:surface:%s" % (catalog_id, name)
        name_root = surface_root + ":name"
        index_root = surface_root + ":index"
        batch.add(Cell(name_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")))
        batch.add(Cell(index_root, NULL_CELL_ID, NULL_CELL_ID, str(index).encode("ascii")))
        batch.relation(
            (
                (protocol.role("name"), name_root),
                (protocol.role("index"), index_root),
                (protocol.role("source-digest"), source_digest_root),
                (protocol.role("lifecycle"), lifecycle_root),
                (protocol.role("superseded-by"), superseded_by_root),
                (protocol.role("promotion-allowed"), promotion_allowed_root),
            ),
            relation_id=surface_root,
        )
        surface_roots.append(surface_root)

    batch.relation(
        (
            (protocol.role("source-digest"), source_digest_root),
            (protocol.role("lifecycle"), lifecycle_root),
            (protocol.role("superseded-by"), superseded_by_root),
            (protocol.role("promotion-allowed"), promotion_allowed_root),
            *((protocol.role("item"), root) for root in surface_roots),
        ),
        relation_id=catalog_id,
    )
    batch.commit()
    return LegacySurfaceCatalogBuild(catalog_id, tuple(surface_roots))


def project_legacy_surface_catalog(
    snapshot: Snapshot,
    protocol: LegacySurfaceCatalogProtocol,
    catalog_root: str = DEFAULT_CATALOG_ROOT,
) -> dict[str, object]:
    members = read_relation(snapshot, catalog_root, budget=100_000)
    source_digest = _text(snapshot, _one(members, protocol.role("source-digest"), "source digest"))
    lifecycle = _text(snapshot, _one(members, protocol.role("lifecycle"), "lifecycle"))
    superseded_by = _text(snapshot, _one(members, protocol.role("superseded-by"), "superseded authority"))
    promotion_allowed = _text(
        snapshot,
        _one(members, protocol.role("promotion-allowed"), "promotion flag"),
    )
    item_roots = _many(members, protocol.role("item"))
    surfaces = []
    for surface_root in item_roots:
        surface_members = read_relation(snapshot, surface_root, budget=100)
        name = _text(snapshot, _one(surface_members, protocol.role("name"), "surface name"))
        index_text = _text(snapshot, _one(surface_members, protocol.role("index"), "surface index"))
        try:
            index = int(index_text)
        except ValueError as exc:
            raise InvalidCell("legacy surface index is not an integer") from exc
        _expect_shared(
            surface_members, protocol.role("source-digest"), source_digest,
            snapshot=snapshot, label="source digest",
        )
        _expect_shared(
            surface_members, protocol.role("lifecycle"), lifecycle,
            snapshot=snapshot, label="lifecycle",
        )
        _expect_shared(
            surface_members, protocol.role("superseded-by"), superseded_by,
            snapshot=snapshot, label="superseded authority",
        )
        _expect_shared(
            surface_members, protocol.role("promotion-allowed"), promotion_allowed,
            snapshot=snapshot, label="promotion flag",
        )
        surfaces.append({"root": surface_root, "name": name, "index": index})
    surfaces.sort(key=lambda item: item["index"])
    names = tuple(str(item["name"]) for item in surfaces)
    if len(names) != len(set(names)):
        raise InvalidCell("legacy surface registry repeats a surface name")
    if tuple(range(len(surfaces))) != tuple(int(item["index"]) for item in surfaces):
        raise InvalidCell("legacy surface registry indexes are not contiguous")
    if surface_names_digest(names) != source_digest:
        raise InvalidCell("legacy surface registry digest drifted")
    if promotion_allowed != "false":
        raise InvalidCell("legacy surface registry cannot be promotable")
    return {
        "root": catalog_root,
        "source_digest": source_digest,
        "lifecycle": lifecycle,
        "superseded_by": superseded_by,
        "promotion_allowed": False,
        "surface_count": len(surfaces),
        "surfaces": tuple(surfaces),
    }


def _validate_names(surface_names: tuple[str, ...]) -> tuple[str, ...]:
    if type(surface_names) is not tuple:
        raise InvalidCell("legacy surface names must be an immutable tuple")
    if not surface_names:
        raise InvalidCell("legacy surface catalogue cannot be empty")
    if len(surface_names) != len(set(surface_names)):
        raise InvalidCell("legacy surface catalogue repeats a surface name")
    for name in surface_names:
        if not isinstance(name, str) or not name.strip():
            raise InvalidCell("legacy surface name must be non-empty text")
        if name != name.strip():
            raise InvalidCell("legacy surface names cannot carry hidden whitespace")
        if name.startswith("universal-"):
            raise InvalidCell("legacy surface catalogue cannot claim universal surfaces")
    return surface_names


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("legacy surface catalogue references a missing Cell")
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("legacy surface catalogue expected a terminal atom")
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("legacy surface catalogue atom is not UTF-8") from exc


def _many(members: tuple[RelationMember, ...], role_root: str) -> tuple[str, ...]:
    return tuple(member.participant_id for member in members if member.role_id == role_root)


def _one(
    members: tuple[RelationMember, ...],
    role_root: str,
    label: str,
) -> str:
    values = _many(members, role_root)
    if len(values) != 1:
        raise InvalidCell("legacy surface catalogue requires exactly one %s" % label)
    return values[0]


def _expect_shared(
    members: tuple[RelationMember, ...],
    role_root: str,
    expected_text: str,
    *,
    snapshot: Snapshot,
    label: str,
) -> None:
    root = _one(members, role_root, label)
    if _text(snapshot, root) != expected_text:
        raise InvalidCell("legacy surface catalogue has inconsistent %s" % label)


__all__ = [
    "DEFAULT_CATALOG_ROOT",
    "DEFAULT_LIFECYCLE",
    "DEFAULT_SUPERSEDED_BY",
    "LegacySurfaceCatalogBuild",
    "LegacySurfaceCatalogProtocol",
    "bootstrap_legacy_surface_catalog_protocol",
    "build_legacy_surface_catalog",
    "project_legacy_surface_catalog",
    "surface_names_digest",
]
