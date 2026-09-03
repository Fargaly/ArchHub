"""Cell-native ROMA requirement tree protocol.

This module does not create a new stored record shape. A ROMA tree is a
composition of four-field Cells: protocol role cells, a tree relation, stable
requirement-node relations, explicit parent/child edge relations, and
structured value-graph roots for gate specs.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote

from .cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .cell_value_graph import ValueGraphProtocol, build_value_graphs, read_value_graph
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "protocol-role",
    "state",
    "registry",
    "tree",
    "node",
    "edge",
    "tree-id",
    "root-node",
    "owner",
    "title",
    "created-at",
    "updated-at",
    "node-id",
    "parent",
    "child",
    "state-root",
    "predicate",
    "gate-kind",
    "gate-spec",
    "verdict",
    "evidence-ref",
    "claimed-by",
    "past-claimant",
    "judged-by",
    "attempts",
    "source",
)
STATE_NAMES = ("open", "claimed", "green", "red", "needs_root")
MAX_TREE_NODES = 2_000


@dataclass(frozen=True, slots=True)
class RomaRequirementProtocol:
    root_id: str
    registry_root: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown ROMA role %r" % name) from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("unknown ROMA state %r" % name) from exc


def _terminal(root_id: str, value: object) -> Cell:
    return Cell(
        root_id,
        NULL_CELL_ID,
        NULL_CELL_ID,
        str(value).encode("utf-8"),
    )


def _part(value: object) -> str:
    return quote(str(value), safe="")


def roma_tree_root(tree_id: str) -> str:
    if type(tree_id) is not str or not tree_id.strip():
        raise InvalidCell("ROMA tree id is invalid")
    return "app:roma-tree:%s" % _part(tree_id.strip())


def roma_node_root(tree_id: str, node_id: str) -> str:
    if type(node_id) is not str or not node_id.strip():
        raise InvalidCell("ROMA node id is invalid")
    return "%s:node:%s" % (roma_tree_root(tree_id), _part(node_id.strip()))


def roma_edge_root(tree_id: str, parent_id: str, child_id: str) -> str:
    if type(parent_id) is not str or type(child_id) is not str:
        raise InvalidCell("ROMA edge ids are invalid")
    if not parent_id.strip() or not child_id.strip():
        raise InvalidCell("ROMA edge ids are invalid")
    return "%s:edge:%s:%s" % (
        roma_tree_root(tree_id),
        _part(parent_id.strip()),
        _part(child_id.strip()),
    )


def bootstrap_roma_requirement_protocol(
    store: CellStore,
    *,
    prefix: str = "app:roma-requirement-protocol",
) -> RomaRequirementProtocol:
    root_id = prefix + ":root"
    registry_root = prefix + ":registry"
    if root_id in store.snapshot().cells:
        raise InvalidCell("ROMA requirement protocol already exists")
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    registry = compose_relation_cells((), relation_id=registry_root)
    protocol = compose_relation_cells(
        (
            *((roles["protocol-role"], root) for root in roles.values()),
            *((roles["state"], root) for root in states.values()),
            (roles["registry"], registry_root),
        ),
        relation_id=root_id,
    )
    store.commit(
        store.revision,
        create=(
            *(_terminal(root, name) for name, root in roles.items()),
            *(_terminal(root, name) for name, root in states.items()),
            *registry.cells,
            *protocol.cells,
        ),
    )
    return RomaRequirementProtocol(
        root_id,
        registry_root,
        MappingProxyType(roles),
        MappingProxyType(states),
    )


def open_roma_requirement_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "app:roma-requirement-protocol",
) -> RomaRequirementProtocol:
    root_id = prefix + ":root"
    registry_root = prefix + ":registry"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    required = (root_id, registry_root, *roles.values(), *states.values())
    if any(root not in snapshot.cells for root in required):
        raise InvalidCell("ROMA requirement protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    expected = {
        *((roles["protocol-role"], root) for root in roles.values()),
        *((roles["state"], root) for root in states.values()),
        (roles["registry"], registry_root),
    }
    actual = {(member.role_id, member.participant_id) for member in members}
    if expected - actual:
        raise InvalidCell("ROMA requirement protocol vocabulary drifted")
    read_relation(snapshot, registry_root, budget=100_000)
    return RomaRequirementProtocol(
        root_id,
        registry_root,
        MappingProxyType(roles),
        MappingProxyType(states),
    )


def _normal_tree(tree: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(tree, Mapping):
        raise InvalidCell("ROMA tree payload must be a mapping")
    tree_id = tree.get("tree_id")
    root_id = tree.get("root_id")
    nodes = tree.get("nodes")
    if type(tree_id) is not str or not tree_id.strip():
        raise InvalidCell("ROMA tree id is invalid")
    if type(root_id) is not str or not root_id.strip():
        raise InvalidCell("ROMA root node id is invalid")
    if not isinstance(nodes, Mapping) or not nodes:
        raise InvalidCell("ROMA tree nodes must be a non-empty mapping")
    if len(nodes) > MAX_TREE_NODES:
        raise InvalidCell("ROMA tree exceeds its node budget")
    if root_id not in nodes:
        raise InvalidCell("ROMA root node is missing")
    normal_nodes: dict[str, dict[str, object]] = {}
    for node_id, node in nodes.items():
        if type(node_id) is not str or not node_id.strip():
            raise InvalidCell("ROMA node id is invalid")
        if not isinstance(node, Mapping):
            raise InvalidCell("ROMA node payload must be a mapping")
        if node.get("node_id") not in {None, node_id}:
            raise InvalidCell("ROMA node id drifted")
        state = str(node.get("state") or "open")
        if state not in STATE_NAMES:
            raise InvalidCell("ROMA node state is invalid")
        children = node.get("children") or []
        if not isinstance(children, list) or any(
            type(child) is not str or not child.strip() for child in children
        ):
            raise InvalidCell("ROMA node children are invalid")
        past_claimants = node.get("past_claimants") or []
        if not isinstance(past_claimants, list) or any(
            type(item) is not str for item in past_claimants
        ):
            raise InvalidCell("ROMA node past claimants are invalid")
        try:
            attempts = int(node.get("attempts") or 0)
        except (TypeError, ValueError) as exc:
            raise InvalidCell("ROMA node attempts are invalid") from exc
        if attempts < 0:
            raise InvalidCell("ROMA node attempts are invalid")
        gate_spec = node.get("gate_spec") or {}
        if not isinstance(gate_spec, Mapping):
            raise InvalidCell("ROMA gate spec must be a mapping")
        normal_nodes[node_id] = {
            "node_id": node_id,
            "parent": node.get("parent") or "",
            "title": str(node.get("title") or ""),
            "predicate": str(node.get("predicate") or ""),
            "state": state,
            "verdict": str(node.get("verdict") or ""),
            "evidence_ref": str(node.get("evidence_ref") or ""),
            "children": tuple(children),
            "claimed_by": str(node.get("claimed_by") or ""),
            "past_claimants": tuple(past_claimants),
            "gate_kind": str(node.get("gate_kind") or "manual"),
            "gate_spec": dict(gate_spec),
            "judged_by": str(node.get("judged_by") or ""),
            "attempts": attempts,
            "created_at": str(node.get("created_at") or ""),
            "updated_at": str(node.get("updated_at") or ""),
        }
    for node_id, node in normal_nodes.items():
        parent = str(node["parent"])
        if node_id != root_id and parent not in normal_nodes:
            raise InvalidCell("ROMA node parent is missing")
        for child in node["children"]:
            if child not in normal_nodes:
                raise InvalidCell("ROMA node child is missing")
            if normal_nodes[child]["parent"] != node_id:
                raise InvalidCell("ROMA parent/child relation is inconsistent")
    return {
        "tree_id": tree_id.strip(),
        "root_id": root_id.strip(),
        "owner_user": str(tree.get("owner_user") or "founder"),
        "title": str(tree.get("title") or ""),
        "created_at": str(tree.get("created_at") or ""),
        "updated_at": str(tree.get("updated_at") or ""),
        "nodes": normal_nodes,
    }


def _field(root_id: str, name: str) -> str:
    return "%s:field:%s" % (root_id, name)


def _member_pairs(snapshot: Snapshot, relation_root: str) -> set[tuple[str, str]]:
    if relation_root not in snapshot.cells:
        return set()
    return {
        (member.role_id, member.participant_id)
        for member in read_relation(snapshot, relation_root, budget=100_000)
    }


def _add_terminal(
    snapshot: Snapshot,
    creates: dict[str, Cell],
    replaces: dict[str, Cell],
    root_id: str,
    value: object,
) -> None:
    candidate = _terminal(root_id, value)
    current = snapshot.cells.get(root_id)
    if current is None:
        creates[root_id] = candidate
    elif current != candidate:
        replaces[root_id] = candidate


def _relation_cells(
    snapshot: Snapshot,
    creates: dict[str, Cell],
    replaces: dict[str, Cell],
    relation_root: str,
    pairs: tuple[tuple[str, str], ...],
    *,
    unique_roles: frozenset[str] = frozenset(),
) -> None:
    if relation_root not in snapshot.cells and relation_root not in creates:
        relation = compose_relation_cells(pairs, relation_id=relation_root)
        for cell in relation.cells:
            if cell.id in creates and creates[cell.id] != cell:
                raise InvalidCell("ROMA relation create conflict")
            creates[cell.id] = cell
        return
    if relation_root in creates:
        return
    members = read_relation(snapshot, relation_root, budget=100_000)
    existing = {(member.role_id, member.participant_id) for member in members}
    by_role: dict[str, list[object]] = {}
    for member in members:
        by_role.setdefault(member.role_id, []).append(member)
    missing_items: list[tuple[str, str]] = []
    for role_id, participant_id in pairs:
        if (role_id, participant_id) in existing:
            continue
        existing_for_role = by_role.get(role_id, [])
        if role_id in unique_roles and existing_for_role:
            if len(existing_for_role) != 1:
                raise InvalidCell("ROMA unique relation role is duplicated")
            incidence = snapshot.cells[existing_for_role[0].incidence_id]
            replaces[incidence.id] = Cell(
                incidence.id,
                incidence.link0,
                participant_id,
                incidence.atom,
            )
            continue
        missing_items.append((role_id, participant_id))
    missing = tuple(missing_items)
    if not missing:
        return
    patch = prepare_append_relation_members(
        snapshot, relation_root, missing, budget=100_000
    )
    for cell in patch.create:
        creates[cell.id] = cell
    for cell in patch.replace:
        replaces[cell.id] = cell


def _ensure_gate_specs(
    store: CellStore,
    value_protocol: ValueGraphProtocol,
    normal: Mapping[str, object],
) -> tuple[str, ...]:
    snapshot = store.snapshot()
    missing: dict[str, object] = {}
    tree_id = str(normal["tree_id"])
    nodes = normal["nodes"]
    assert isinstance(nodes, Mapping)
    for node_id, node in nodes.items():
        assert isinstance(node, Mapping)
        root = "%s:gate-spec" % roma_node_root(tree_id, str(node_id))
        if root in snapshot.cells:
            existing = read_value_graph(snapshot, value_protocol, root)
            if existing != dict(node["gate_spec"]):
                raise InvalidCell("ROMA gate spec changed; supersede the node")
        else:
            missing[root] = dict(node["gate_spec"])
    if missing:
        return build_value_graphs(store, value_protocol, missing)[0]
    return tuple()


def sync_roma_requirement_tree(
    store: CellStore,
    protocol: RomaRequirementProtocol,
    value_protocol: ValueGraphProtocol,
    tree: Mapping[str, object],
    *,
    source: str = "brain.roma",
) -> dict[str, object]:
    """Synchronize a ROMA requirement tree into stable Cell relations."""
    normal = _normal_tree(tree)
    _ensure_gate_specs(store, value_protocol, normal)
    snapshot = store.snapshot()
    tree_id = str(normal["tree_id"])
    tree_root = roma_tree_root(tree_id)
    root_node = roma_node_root(tree_id, str(normal["root_id"]))
    creates: dict[str, Cell] = {}
    replaces: dict[str, Cell] = {}

    tree_fields = {
        "tree-id": normal["tree_id"],
        "owner": normal["owner_user"],
        "title": normal["title"],
        "created-at": normal["created_at"],
        "updated-at": normal["updated_at"],
        "source": source,
    }
    tree_pairs: list[tuple[str, str]] = [
        (protocol.role("root-node"), root_node),
    ]
    for name, value in tree_fields.items():
        root = _field(tree_root, name)
        _add_terminal(snapshot, creates, replaces, root, value)
        tree_pairs.append((protocol.role(name), root))

    nodes = normal["nodes"]
    assert isinstance(nodes, Mapping)
    edge_count = 0
    for node_id, node in sorted(nodes.items()):
        assert isinstance(node, Mapping)
        node_root = roma_node_root(tree_id, str(node_id))
        tree_pairs.append((protocol.role("node"), node_root))
        fields = {
            "node-id": node_id,
            "parent": node["parent"],
            "title": node["title"],
            "predicate": node["predicate"],
            "state-root": protocol.state(str(node["state"])),
            "gate-kind": node["gate_kind"],
            "gate-spec": "%s:gate-spec" % node_root,
            "verdict": node["verdict"],
            "evidence-ref": node["evidence_ref"],
            "claimed-by": node["claimed_by"],
            "judged-by": node["judged_by"],
            "attempts": node["attempts"],
            "created-at": node["created_at"],
            "updated-at": node["updated_at"],
        }
        node_pairs: list[tuple[str, str]] = [(protocol.role("tree"), tree_root)]
        for name, value in fields.items():
            if name in {"state-root", "gate-spec"}:
                root = str(value)
            else:
                root = _field(node_root, name)
                _add_terminal(snapshot, creates, replaces, root, value)
            node_pairs.append((protocol.role(name), root))
        for index, claimant in enumerate(node["past_claimants"]):
            root = "%s:past-claimant:%s" % (node_root, index)
            _add_terminal(snapshot, creates, replaces, root, claimant)
            node_pairs.append((protocol.role("past-claimant"), root))
        for child in node["children"]:
            edge_root = roma_edge_root(tree_id, str(node_id), str(child))
            child_root = roma_node_root(tree_id, str(child))
            edge_pairs = (
                (protocol.role("parent"), node_root),
                (protocol.role("child"), child_root),
                (protocol.role("tree"), tree_root),
            )
            _relation_cells(snapshot, creates, replaces, edge_root, edge_pairs)
            node_pairs.append((protocol.role("edge"), edge_root))
            tree_pairs.append((protocol.role("edge"), edge_root))
            edge_count += 1
        _relation_cells(
            snapshot,
            creates,
            replaces,
            node_root,
            tuple(node_pairs),
            unique_roles=frozenset({
                protocol.role("tree"),
                protocol.role("node-id"),
                protocol.role("parent"),
                protocol.role("title"),
                protocol.role("predicate"),
                protocol.role("state-root"),
                protocol.role("gate-kind"),
                protocol.role("gate-spec"),
                protocol.role("verdict"),
                protocol.role("evidence-ref"),
                protocol.role("claimed-by"),
                protocol.role("judged-by"),
                protocol.role("attempts"),
                protocol.role("created-at"),
                protocol.role("updated-at"),
            }),
        )

    _relation_cells(
        snapshot,
        creates,
        replaces,
        tree_root,
        tuple(tree_pairs),
        unique_roles=frozenset({
            protocol.role("root-node"),
            protocol.role("tree-id"),
            protocol.role("owner"),
            protocol.role("title"),
            protocol.role("created-at"),
            protocol.role("updated-at"),
            protocol.role("source"),
        }),
    )
    registry_pairs = ((protocol.role("tree"), tree_root),)
    _relation_cells(
        snapshot, creates, replaces, protocol.registry_root, registry_pairs
    )
    if creates or replaces:
        store.commit(
            snapshot.revision,
            create=tuple(creates.values()),
            replace=tuple(replaces.values()),
        )
    projected = project_roma_requirement_tree(
        store.snapshot(), protocol, value_protocol, tree_root
    )
    return {
        "schema": "archhub-roma-requirement-tree-cell-sync/v1",
        "tree_root": tree_root,
        "node_count": projected["node_count"],
        "edge_count": edge_count,
        "frontier_count": len(projected["frontier"]),
        "revision": store.revision,
    }


def _one_text(
    snapshot: Snapshot,
    members,
    protocol: RomaRequirementProtocol,
    role: str,
) -> str:
    matches = [member.participant_id for member in members if member.role_id == protocol.role(role)]
    if len(matches) != 1:
        raise InvalidCell("ROMA graph field %s is not unique" % role)
    return snapshot.cells[matches[0]].atom.decode("utf-8")


def _optional_text(
    snapshot: Snapshot,
    members,
    protocol: RomaRequirementProtocol,
    role: str,
) -> str:
    matches = [member.participant_id for member in members if member.role_id == protocol.role(role)]
    if len(matches) > 1:
        raise InvalidCell("ROMA graph field %s is duplicated" % role)
    if not matches:
        return ""
    return snapshot.cells[matches[0]].atom.decode("utf-8")


def project_roma_requirement_tree(
    snapshot: Snapshot,
    protocol: RomaRequirementProtocol,
    value_protocol: ValueGraphProtocol,
    tree_root: str,
) -> dict[str, object]:
    members = read_relation(snapshot, tree_root, budget=100_000)
    node_roots = tuple(
        member.participant_id
        for member in members
        if member.role_id == protocol.role("node")
    )
    edge_roots = tuple(
        member.participant_id
        for member in members
        if member.role_id == protocol.role("edge")
    )
    root_nodes = tuple(
        member.participant_id
        for member in members
        if member.role_id == protocol.role("root-node")
    )
    if len(root_nodes) != 1:
        raise InvalidCell("ROMA graph root node is not unique")
    nodes: dict[str, dict[str, object]] = {}
    for node_root in node_roots:
        node_members = read_relation(snapshot, node_root, budget=100_000)
        state_roots = tuple(
            member.participant_id
            for member in node_members
            if member.role_id == protocol.role("state-root")
        )
        gate_specs = tuple(
            member.participant_id
            for member in node_members
            if member.role_id == protocol.role("gate-spec")
        )
        if len(state_roots) != 1 or len(gate_specs) != 1:
            raise InvalidCell("ROMA graph node state/gate is not unique")
        state = next(
            name for name, root in protocol.states.items() if root == state_roots[0]
        )
        children = []
        for edge_member in node_members:
            if edge_member.role_id != protocol.role("edge"):
                continue
            edge_members = read_relation(
                snapshot, edge_member.participant_id, budget=100_000
            )
            child_roots = tuple(
                member.participant_id
                for member in edge_members
                if member.role_id == protocol.role("child")
            )
            if len(child_roots) != 1:
                raise InvalidCell("ROMA graph edge child is not unique")
            children.append(child_roots[0])
        past_claimants = tuple(
            snapshot.cells[member.participant_id].atom.decode("utf-8")
            for member in node_members
            if member.role_id == protocol.role("past-claimant")
        )
        nodes[node_root] = {
            "root": node_root,
            "node_id": _one_text(snapshot, node_members, protocol, "node-id"),
            "parent": _optional_text(snapshot, node_members, protocol, "parent"),
            "title": _one_text(snapshot, node_members, protocol, "title"),
            "predicate": _optional_text(snapshot, node_members, protocol, "predicate"),
            "state": state,
            "gate_kind": _one_text(snapshot, node_members, protocol, "gate-kind"),
            "gate_spec": read_value_graph(snapshot, value_protocol, gate_specs[0]),
            "verdict": _optional_text(snapshot, node_members, protocol, "verdict"),
            "evidence_ref": _optional_text(
                snapshot, node_members, protocol, "evidence-ref"
            ),
            "claimed_by": _optional_text(
                snapshot, node_members, protocol, "claimed-by"
            ),
            "past_claimants": past_claimants,
            "judged_by": _optional_text(snapshot, node_members, protocol, "judged-by"),
            "attempts": int(_one_text(snapshot, node_members, protocol, "attempts")),
            "created_at": _one_text(snapshot, node_members, protocol, "created-at"),
            "updated_at": _one_text(snapshot, node_members, protocol, "updated-at"),
            "children": tuple(children),
        }
    frontier = tuple(
        node for node in nodes.values()
        if not node["children"] and node["state"] != "green"
    )
    return {
        "schema": "archhub-roma-requirement-tree-cell/v1",
        "tree_root": tree_root,
        "tree_id": _one_text(snapshot, members, protocol, "tree-id"),
        "owner": _one_text(snapshot, members, protocol, "owner"),
        "title": _one_text(snapshot, members, protocol, "title"),
        "created_at": _one_text(snapshot, members, protocol, "created-at"),
        "updated_at": _one_text(snapshot, members, protocol, "updated-at"),
        "root_node": root_nodes[0],
        "node_count": len(nodes),
        "edge_count": len(edge_roots),
        "nodes": nodes,
        "edges": edge_roots,
        "frontier": frontier,
    }


def project_roma_requirement_tree_index(
    snapshot: Snapshot,
    protocol: RomaRequirementProtocol,
    value_protocol: ValueGraphProtocol,
) -> dict[str, object]:
    """Project the ROMA tree registry without using a second catalogue."""
    registry_members = read_relation(
        snapshot, protocol.registry_root, budget=100_000
    )
    tree_roots = tuple(
        member.participant_id
        for member in registry_members
        if member.role_id == protocol.role("tree")
    )
    trees = []
    for tree_root in tree_roots:
        projected = project_roma_requirement_tree(
            snapshot, protocol, value_protocol, tree_root
        )
        trees.append({
            "tree_root": tree_root,
            "tree_id": projected["tree_id"],
            "title": projected["title"],
            "owner": projected["owner"],
            "node_count": projected["node_count"],
            "edge_count": projected["edge_count"],
            "frontier_count": len(projected["frontier"]),
        })
    trees.sort(key=lambda item: str(item["tree_id"]))
    return {
        "schema": "archhub-roma-requirement-tree-cell-index/v1",
        "registry": protocol.registry_root,
        "tree_count": len(trees),
        "tree_ids": tuple(str(item["tree_id"]) for item in trees),
        "trees": tuple(trees),
    }


__all__ = [
    "RomaRequirementProtocol",
    "bootstrap_roma_requirement_protocol",
    "open_roma_requirement_protocol",
    "project_roma_requirement_tree",
    "project_roma_requirement_tree_index",
    "roma_edge_root",
    "roma_node_root",
    "roma_tree_root",
    "sync_roma_requirement_tree",
]
