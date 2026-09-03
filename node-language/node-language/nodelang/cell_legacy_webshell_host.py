"""Graph-held contract for the superseded public WebShell host boundary.

The legacy WebShell can remain useful only as a host/adapter while the
Universal Cell application graph replaces its surfaces. This module records the
allowed preview routes and bridge slots as Cells. It does not import the
WebShell, start a server, or serve any route.
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
    "route",
    "method",
    "slot",
    "authority",
    "legacy-migration-only",
    "cell-passthrough",
    "body-limit-bytes",
    "digest",
)

DEFAULT_CONTRACT_ROOT = "legacy-webshell-host:route-contract:v1"
ACTIVE_CELL_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
ROUTE_SPECS = (
    {
        "route": "/__archhub_preview_bridge.js",
        "method": "GET",
        "slot": "preview_bridge_source",
        "authority": "legacy-webshell-host-bootstrap",
        "legacy_migration_only": "true",
        "cell_passthrough": "false",
        "body_limit_bytes": "0",
    },
    {
        "route": "/__archhub/node-grammar",
        "method": "GET",
        "slot": "get_node_grammar",
        "authority": "legacy-typed-grammar-projection",
        "legacy_migration_only": "true",
        "cell_passthrough": "false",
        "body_limit_bytes": "0",
    },
    {
        "route": "/__archhub/grand-map-ui-surface",
        "method": "GET",
        "slot": "get_grand_map_ui_surface",
        "authority": "legacy-projection-router-with-universal-canvas-escape",
        "legacy_migration_only": "true",
        "cell_passthrough": "true",
        "body_limit_bytes": "0",
    },
    {
        "route": "/__archhub/universal-interaction",
        "method": "POST",
        "slot": "submit_universal_interaction",
        "authority": ACTIVE_CELL_AUTHORITY,
        "legacy_migration_only": "false",
        "cell_passthrough": "true",
        "body_limit_bytes": "1048576",
    },
)


@dataclass(frozen=True, slots=True)
class LegacyWebShellHostProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown WebShell host role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class LegacyWebShellHostContract:
    root_id: str
    route_roots: tuple[str, ...]


def route_contract_digest(route_specs: tuple[Mapping[str, str], ...]) -> str:
    normalized = _validate_route_specs(route_specs)
    lines = [
        "|".join(
            spec[key]
            for key in (
                "method",
                "route",
                "slot",
                "authority",
                "legacy_migration_only",
                "cell_passthrough",
                "body_limit_bytes",
            )
        )
        for spec in normalized
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def bootstrap_legacy_webshell_host_protocol(
    store: CellStore,
    *,
    prefix: str = "legacy-webshell-host-protocol",
) -> LegacyWebShellHostProtocol:
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
    return LegacyWebShellHostProtocol(root_id, roles)


def build_legacy_webshell_host_contract(
    store: CellStore,
    protocol: LegacyWebShellHostProtocol,
    *,
    route_specs: tuple[Mapping[str, str], ...] = ROUTE_SPECS,
    contract_id: str = DEFAULT_CONTRACT_ROOT,
) -> LegacyWebShellHostContract:
    specs = _validate_route_specs(route_specs)
    digest_root = contract_id + ":digest"
    batch = CellBatch(store)
    batch.add(Cell(
        digest_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        route_contract_digest(specs).encode("ascii"),
    ))
    route_roots = []
    for index, spec in enumerate(specs):
        route_root = "%s:route:%s" % (contract_id, index)
        field_roots = {}
        for field, value in spec.items():
            root_id = "%s:%s" % (route_root, field.replace("_", "-"))
            batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")))
            field_roots[field] = root_id
        batch.relation(
            (
                (protocol.role("route"), field_roots["route"]),
                (protocol.role("method"), field_roots["method"]),
                (protocol.role("slot"), field_roots["slot"]),
                (protocol.role("authority"), field_roots["authority"]),
                (
                    protocol.role("legacy-migration-only"),
                    field_roots["legacy_migration_only"],
                ),
                (protocol.role("cell-passthrough"), field_roots["cell_passthrough"]),
                (protocol.role("body-limit-bytes"), field_roots["body_limit_bytes"]),
            ),
            relation_id=route_root,
        )
        route_roots.append(route_root)
    batch.relation(
        (
            (protocol.role("digest"), digest_root),
            *((protocol.role("route"), root) for root in route_roots),
        ),
        relation_id=contract_id,
    )
    batch.commit()
    return LegacyWebShellHostContract(contract_id, tuple(route_roots))


def project_legacy_webshell_host_contract(
    snapshot: Snapshot,
    protocol: LegacyWebShellHostProtocol,
    contract_root: str = DEFAULT_CONTRACT_ROOT,
) -> dict[str, object]:
    members = read_relation(snapshot, contract_root, budget=100_000)
    digest = _text(snapshot, _one(members, protocol.role("digest"), "digest"))
    routes = []
    for route_root in _many(members, protocol.role("route")):
        route_members = read_relation(snapshot, route_root, budget=100)
        route = {
            "route": _text(snapshot, _one(route_members, protocol.role("route"), "route")),
            "method": _text(snapshot, _one(route_members, protocol.role("method"), "method")),
            "slot": _text(snapshot, _one(route_members, protocol.role("slot"), "slot")),
            "authority": _text(
                snapshot,
                _one(route_members, protocol.role("authority"), "authority"),
            ),
            "legacy_migration_only": _text(
                snapshot,
                _one(
                    route_members,
                    protocol.role("legacy-migration-only"),
                    "legacy flag",
                ),
            ),
            "cell_passthrough": _text(
                snapshot,
                _one(
                    route_members,
                    protocol.role("cell-passthrough"),
                    "Cell passthrough flag",
                ),
            ),
            "body_limit_bytes": _text(
                snapshot,
                _one(
                    route_members,
                    protocol.role("body-limit-bytes"),
                    "body limit",
                ),
            ),
        }
        routes.append(route)
    route_specs = tuple(routes)
    if route_contract_digest(route_specs) != digest:
        raise InvalidCell("legacy WebShell host route contract digest drifted")
    post_routes = [item for item in route_specs if item["method"] == "POST"]
    for item in post_routes:
        if item["cell_passthrough"] != "true":
            raise InvalidCell("POST WebShell routes must be Cell passthroughs")
    return {
        "root": contract_root,
        "digest": digest,
        "active_authority": ACTIVE_CELL_AUTHORITY,
        "routes": route_specs,
        "route_count": len(route_specs),
        "promotion_allowed": False,
    }


def _validate_route_specs(
    route_specs: tuple[Mapping[str, str], ...],
) -> tuple[Mapping[str, str], ...]:
    if type(route_specs) is not tuple or not route_specs:
        raise InvalidCell("legacy WebShell host route specs must be a non-empty tuple")
    required = {
        "route",
        "method",
        "slot",
        "authority",
        "legacy_migration_only",
        "cell_passthrough",
        "body_limit_bytes",
    }
    seen_routes = set()
    normalized = []
    for spec in route_specs:
        if set(spec) != required:
            raise InvalidCell("legacy WebShell host route spec fields are invalid")
        route = str(spec["route"])
        method = str(spec["method"])
        if not route.startswith("/__archhub"):
            raise InvalidCell("legacy WebShell host route must stay namespaced")
        if method not in {"GET", "POST"}:
            raise InvalidCell("legacy WebShell host method is not admitted")
        if route in seen_routes:
            raise InvalidCell("legacy WebShell host route is duplicated")
        seen_routes.add(route)
        flags = (str(spec["legacy_migration_only"]), str(spec["cell_passthrough"]))
        if any(flag not in {"true", "false"} for flag in flags):
            raise InvalidCell("legacy WebShell host flags must be true/false")
        try:
            if int(str(spec["body_limit_bytes"])) < 0:
                raise ValueError
        except ValueError as exc:
            raise InvalidCell("legacy WebShell host body limit is invalid") from exc
        normalized.append(MappingProxyType({key: str(spec[key]) for key in required}))
    return tuple(normalized)


def _many(members: tuple[RelationMember, ...], role_root: str) -> tuple[str, ...]:
    return tuple(member.participant_id for member in members if member.role_id == role_root)


def _one(members: tuple[RelationMember, ...], role_root: str, label: str) -> str:
    values = _many(members, role_root)
    if len(values) != 1:
        raise InvalidCell("legacy WebShell host contract requires exactly one %s" % label)
    return values[0]


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("legacy WebShell host contract references a missing Cell")
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("legacy WebShell host contract expected a terminal atom")
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("legacy WebShell host contract atom is not UTF-8") from exc


__all__ = [
    "ACTIVE_CELL_AUTHORITY",
    "DEFAULT_CONTRACT_ROOT",
    "ROUTE_SPECS",
    "LegacyWebShellHostContract",
    "LegacyWebShellHostProtocol",
    "bootstrap_legacy_webshell_host_protocol",
    "build_legacy_webshell_host_contract",
    "project_legacy_webshell_host_contract",
    "route_contract_digest",
]
