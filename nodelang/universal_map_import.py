"""Import the Grand Map authority onto the universal-cell kernel.

The source JSON is read only as an external authority format. Every imported
semantic item becomes a Cell composition: map roots, scalar values, properties,
parameters, internal dependencies, cross-domain relations, domains, and the
whole-map root. The import is published in one atomic Store revision.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote

from .cell_protocols import CellBatch, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


@dataclass(frozen=True, slots=True)
class PropertyRef:
    relation_root: str
    value_root: str
    label_root: str


@dataclass(frozen=True, slots=True)
class UniversalMapRegistry:
    roles: Mapping[str, str]
    nodes: Mapping[str, str]
    properties: Mapping[str, tuple[str, ...]]
    root_properties: Mapping[str, tuple[str, ...]]
    params: Mapping[str, Mapping[str, PropertyRef]]
    domains: Mapping[str, str]
    wires: tuple[str, ...]
    cross_relations: tuple[str, ...]
    grand_map_root: str


def _part(value: object) -> str:
    return quote(str(value), safe="")


def _atom_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, (str, int, float)):
        return str(value).encode("utf-8")
    raise InvalidCell("Grand Map terminal values must be scalar")


def import_grand_map_cells(
    store: CellStore,
    path: str | Path,
) -> UniversalMapRegistry:
    with open(Path(path).expanduser().resolve(), encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise InvalidCell("Grand Map authority must be a domain list")

    batch = CellBatch(store)
    roles = {
        name: "gm:role:%s" % name
        for name in (
            "owner", "value", "label", "member", "scope",
            "source", "target", "why",
        )
    }
    for name, role_id in roles.items():
        batch.add(Cell(role_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))

    label_roots: dict[str, str] = {}

    def label_root(label: str) -> str:
        existing = label_roots.get(label)
        if existing is not None:
            return existing
        cell_id = "gm:label:%s" % _part(label)
        batch.add(Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, label.encode("utf-8")))
        label_roots[label] = cell_id
        return cell_id

    def add_property(
        owner_root: str,
        owner_key: str,
        namespace: str,
        key: str,
        value: object,
    ) -> PropertyRef:
        token = "%s:%s" % (_part(namespace), _part(key))
        value_root = "gm:value:%s:%s" % (_part(owner_key), token)
        relation_root = "gm:property:%s:%s" % (_part(owner_key), token)
        key_label = label_root(key)
        batch.add(Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, _atom_bytes(value)))
        batch.relation([
            (roles["owner"], owner_root),
            (roles["value"], value_root),
            (roles["label"], key_label),
        ], relation_id=relation_root)
        return PropertyRef(relation_root, value_root, key_label)

    nodes: dict[str, str] = {}
    properties: dict[str, list[str]] = {}
    root_properties: dict[str, list[str]] = {}
    params: dict[str, dict[str, PropertyRef]] = {}
    node_domains: dict[str, str] = {}

    for domain in data:
        domain_key = domain["key"]
        for source_node in domain.get("nodes", ()):
            map_id = source_node["id"]
            if map_id in nodes:
                raise InvalidCell("duplicate Grand Map node %r" % map_id)
            root_id = "gm:node:%s" % _part(map_id)
            batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, b""))
            nodes[map_id] = root_id
            properties[map_id] = []
            root_properties[root_id] = properties[map_id]
            params[map_id] = {}
            node_domains[map_id] = domain_key

    for domain in data:
        for source_node in domain.get("nodes", ()):
            map_id = source_node["id"]
            owner_root = nodes[map_id]
            for key, value in source_node.items():
                if key == "params":
                    continue
                ref = add_property(owner_root, map_id, "field", key, value)
                properties[map_id].append(ref.relation_root)
            for parameter in source_node.get("params", ()):
                key = parameter["k"]
                if key in params[map_id]:
                    raise InvalidCell(
                        "duplicate parameter %r on Grand Map node %r" % (key, map_id)
                    )
                ref = add_property(
                    owner_root, map_id, "parameter", key, parameter.get("v")
                )
                params[map_id][key] = ref
                properties[map_id].append(ref.relation_root)

    domain_ids = {
        domain["key"]: "gm:domain:%s" % _part(domain["key"])
        for domain in data
    }
    wires: list[str] = []
    wires_by_domain: dict[str, list[str]] = {key: [] for key in domain_ids}
    for domain in data:
        key = domain["key"]
        for index, pair in enumerate(domain.get("wires", ())):
            source, target = pair
            relation_root = "gm:wire:%s:%s" % (_part(key), index)
            batch.relation([
                (roles["source"], nodes[source]),
                (roles["target"], nodes[target]),
            ], relation_id=relation_root)
            wires.append(relation_root)
            wires_by_domain[key].append(relation_root)

    cross_relations: list[str] = []
    cross_by_domain: dict[str, list[str]] = {key: [] for key in domain_ids}
    for domain in data:
        key = domain["key"]
        for index, cross in enumerate(domain.get("cross", ())):
            source = cross["from"]
            target_domain = cross["to_domain"]
            why_root = "gm:cross-why:%s:%s" % (_part(key), index)
            relation_root = "gm:cross:%s:%s" % (_part(key), index)
            batch.add(Cell(
                why_root, NULL_CELL_ID, NULL_CELL_ID, _atom_bytes(cross.get("why"))
            ))
            batch.relation([
                (roles["source"], nodes[source]),
                (roles["target"], domain_ids[target_domain]),
                (roles["why"], why_root),
            ], relation_id=relation_root)
            cross_relations.append(relation_root)
            cross_by_domain[key].append(relation_root)

    domains: dict[str, str] = {}
    for domain in data:
        key = domain["key"]
        members: list[tuple[str, str]] = []
        for source_node in domain.get("nodes", ()):
            map_id = source_node["id"]
            members.append((roles["member"], nodes[map_id]))
            members.extend(
                (roles["scope"], relation_root)
                for relation_root in properties[map_id]
            )
        members.extend(
            (roles["scope"], relation_root)
            for relation_root in wires_by_domain[key] + cross_by_domain[key]
        )
        root_id = domain_ids[key]
        batch.relation(members, relation_id=root_id)
        domain_properties = [
            add_property(root_id, "domain:%s" % key, "field", "key", key).relation_root,
            add_property(
                root_id, "domain:%s" % key, "field", "title",
                domain.get("title", key),
            ).relation_root,
        ]
        root_properties[root_id] = domain_properties
        domains[key] = root_id

    grand_map_root = "gm:grand-map"
    batch.relation(
        [(roles["member"], domains[domain["key"]]) for domain in data],
        relation_id=grand_map_root,
    )
    batch.commit()

    return UniversalMapRegistry(
        roles=MappingProxyType(dict(roles)),
        nodes=MappingProxyType(dict(nodes)),
        properties=MappingProxyType({
            key: tuple(value) for key, value in properties.items()
        }),
        root_properties=MappingProxyType({
            key: tuple(value) for key, value in root_properties.items()
        }),
        params=MappingProxyType({
            key: MappingProxyType(dict(value)) for key, value in params.items()
        }),
        domains=MappingProxyType(dict(domains)),
        wires=tuple(wires),
        cross_relations=tuple(cross_relations),
        grand_map_root=grand_map_root,
    )


def project_grand_map_cells(
    snapshot,
    path: str | Path | None = None,
) -> UniversalMapRegistry:
    """Rebuild the Grand Map index from its persisted Cell authority.

    ``path`` is retained for source compatibility with restore callers.  It is
    deliberately not read: the JSON file is an import boundary, not a second
    authority that may redefine an already-persisted graph during restart.
    """
    del path
    roles = {
        name: "gm:role:%s" % name
        for name in (
            "owner", "value", "label", "member", "scope",
            "source", "target", "why",
        )
    }
    cell_roots = frozenset(snapshot.cells)
    missing_roles = set(roles.values()) - cell_roots
    if missing_roles:
        raise InvalidCell("persisted Grand Map role vocabulary is incomplete")

    def scalar(root_id: str, label: str) -> str:
        try:
            cell = snapshot.cells[root_id]
        except KeyError as exc:
            raise InvalidCell("Grand Map %s root is missing" % label) from exc
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("Grand Map %s must be a terminal Cell" % label)
        try:
            return cell.atom.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidCell("Grand Map %s is not UTF-8" % label) from exc

    def property_ref(relation_root: str) -> tuple[str, PropertyRef]:
        members = read_relation(snapshot, relation_root, budget=32)
        by_role = {
            role: tuple(
                member.participant_id
                for member in members if member.role_id == role
            )
            for role in (
                roles["owner"], roles["value"], roles["label"]
            )
        }
        if set(member.role_id for member in members) != set(by_role):
            raise InvalidCell("Grand Map property has undeclared roles")
        if any(len(values) != 1 for values in by_role.values()):
            raise InvalidCell("Grand Map property is incomplete")
        owner_root = by_role[roles["owner"]][0]
        value_root = by_role[roles["value"]][0]
        label_root = by_role[roles["label"]][0]
        if {owner_root, value_root, label_root} - cell_roots:
            raise InvalidCell("Grand Map property references missing Cells")
        return owner_root, PropertyRef(
            relation_root, value_root, label_root
        )

    grand_map_root = "gm:grand-map"
    if grand_map_root not in snapshot.cells:
        raise InvalidCell("persisted Grand Map root is missing")
    map_members = read_relation(snapshot, grand_map_root, budget=100_000)
    if any(member.role_id != roles["member"] for member in map_members):
        raise InvalidCell("persisted Grand Map root has undeclared roles")
    domain_roots = tuple(member.participant_id for member in map_members)
    if not domain_roots or len(domain_roots) != len(set(domain_roots)):
        raise InvalidCell("persisted Grand Map domains are missing or duplicated")

    nodes: dict[str, str] = {}
    properties: dict[str, tuple[str, ...]] = {}
    root_properties: dict[str, tuple[str, ...]] = {}
    params: dict[str, Mapping[str, PropertyRef]] = {}
    domains: dict[str, str] = {}
    wires: list[str] = []
    cross_relations: list[str] = []
    all_refs_by_owner: dict[str, list[PropertyRef]] = {}
    for relation_root in sorted(
        root for root in snapshot.cells
        if root.startswith("gm:property:")
        and ":incidence:" not in root
        and ":chain:" not in root
    ):
        owner_root, reference = property_ref(relation_root)
        all_refs_by_owner.setdefault(owner_root, []).append(reference)
    for domain_root in domain_roots:
        if domain_root not in snapshot.cells:
            raise InvalidCell("persisted Grand Map domain is missing")
        members = read_relation(snapshot, domain_root, budget=100_000)
        node_roots = tuple(
            member.participant_id for member in members
            if member.role_id == roles["member"]
        )
        scope_roots = tuple(
            member.participant_id for member in members
            if member.role_id == roles["scope"]
        )
        if any(
            member.role_id.startswith("gm:role:")
            and member.role_id not in (roles["member"], roles["scope"])
            for member in members
        ):
            raise InvalidCell("Grand Map domain has undeclared roles")
        if len(node_roots) != len(set(node_roots)):
            raise InvalidCell("Grand Map domain repeats a node")

        scoped_refs_by_owner: dict[str, list[PropertyRef]] = {}
        for scope_root in scope_roots:
            if scope_root.startswith("gm:property:"):
                owner_root, reference = property_ref(scope_root)
                scoped_refs_by_owner.setdefault(owner_root, []).append(reference)
            elif scope_root.startswith("gm:wire:"):
                relation = read_relation(snapshot, scope_root, budget=16)
                if {member.role_id for member in relation} != {
                    roles["source"], roles["target"]
                }:
                    raise InvalidCell("Grand Map wire authority drifted")
                wires.append(scope_root)
            elif scope_root.startswith("gm:cross:"):
                relation = read_relation(snapshot, scope_root, budget=16)
                if {member.role_id for member in relation} != {
                    roles["source"], roles["target"], roles["why"]
                }:
                    raise InvalidCell("Grand Map cross relation drifted")
                cross_relations.append(scope_root)
            else:
                raise InvalidCell("Grand Map domain contains an unknown scope")

        domain_refs = tuple(all_refs_by_owner.get(domain_root, ()))
        domain_fields = {
            scalar(ref.label_root, "property label"):
            scalar(ref.value_root, "property value")
            for ref in domain_refs
        }
        if set(domain_fields) != {"key", "title"}:
            raise InvalidCell("Grand Map domain identity properties drifted")
        domain_key = domain_fields["key"]
        if not domain_key or domain_key in domains:
            raise InvalidCell("Grand Map domain key is missing or duplicated")
        domains[domain_key] = domain_root
        root_properties[domain_root] = tuple(
            ref.relation_root for ref in domain_refs
        )

        for node_root in node_roots:
            if node_root not in snapshot.cells:
                raise InvalidCell("Grand Map node root is missing")
            node_refs = tuple(scoped_refs_by_owner.get(node_root, ()))
            authoritative_refs = tuple(all_refs_by_owner.get(node_root, ()))
            if not node_refs and not authoritative_refs:
                # A live application may extend a Grand Map domain with members
                # of its own.  Imported map nodes are distinguished by their
                # explicit property relations, not by assuming that every
                # domain member came from the external import.
                continue
            if set(node_refs) != set(authoritative_refs):
                raise InvalidCell(
                    "Grand Map node properties leave their domain scope"
                )
            labels = {
                ref.relation_root: scalar(ref.label_root, "property label")
                for ref in node_refs
            }
            identity = tuple(
                scalar(ref.value_root, "node identity")
                for ref in node_refs
                if labels[ref.relation_root] == "id"
                and ":field:" in ref.relation_root
            )
            if len(identity) != 1 or not identity[0]:
                raise InvalidCell("Grand Map node has no unique identity")
            map_id = identity[0]
            if map_id in nodes:
                raise InvalidCell("duplicate Grand Map node %r" % map_id)
            nodes[map_id] = node_root
            properties[map_id] = tuple(
                ref.relation_root for ref in node_refs
            )
            root_properties[node_root] = properties[map_id]
            parameter_refs: dict[str, PropertyRef] = {}
            for ref in node_refs:
                if ":parameter:" not in ref.relation_root:
                    continue
                key = labels[ref.relation_root]
                if key in parameter_refs:
                    raise InvalidCell(
                        "duplicate parameter %r on Grand Map node %r"
                        % (key, map_id)
                    )
                parameter_refs[key] = ref
            params[map_id] = MappingProxyType(parameter_refs)

    return UniversalMapRegistry(
        roles=MappingProxyType(roles),
        nodes=MappingProxyType(nodes),
        properties=MappingProxyType(properties),
        root_properties=MappingProxyType(root_properties),
        params=MappingProxyType(params),
        domains=MappingProxyType(domains),
        wires=tuple(wires),
        cross_relations=tuple(cross_relations),
        grand_map_root=grand_map_root,
    )


__all__ = [
    "PropertyRef",
    "UniversalMapRegistry",
    "import_grand_map_cells",
    "project_grand_map_cells",
]
