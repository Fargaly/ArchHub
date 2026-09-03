"""Courts for Cell-native ROMA requirement trees."""
from nodelang.cell_protocols import read_relation
from nodelang.cell_roma_requirements import (
    bootstrap_roma_requirement_protocol,
    open_roma_requirement_protocol,
    project_roma_requirement_tree_index,
    project_roma_requirement_tree,
    roma_edge_root,
    roma_node_root,
    roma_tree_root,
    sync_roma_requirement_tree,
)
from nodelang.cell_value_graph import (
    bootstrap_value_graph_protocol,
    project_value_graph_protocol,
)
from nodelang.universal_cell import CellStore


def _tree(state="open", verdict=None, claimed_by=None, past_claimants=None):
    return {
        "tree_id": "rt-demo",
        "root_id": "root",
        "owner_user": "founder",
        "title": "Ship the system",
        "created_at": "2026-07-20T00:00:00+00:00",
        "updated_at": "2026-07-20T00:00:00+00:00",
        "nodes": {
            "root": {
                "node_id": "root",
                "parent": None,
                "title": "Ship the system",
                "children": ["leaf-a", "leaf-b"],
                "state": "open",
                "gate_kind": "manual",
                "gate_spec": {},
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:00:00+00:00",
            },
            "leaf-a": {
                "node_id": "leaf-a",
                "parent": "root",
                "title": "Build the Cell graph",
                "predicate": "tree nodes are addressable Cells",
                "children": [],
                "state": state,
                "verdict": verdict,
                "claimed_by": claimed_by,
                "past_claimants": past_claimants or [],
                "gate_kind": "pytest",
                "gate_spec": {
                    "path": "tests_replica/test_cell_roma_requirements.py",
                    "selector": "test_sync_creates_addressable_tree",
                },
                "judged_by": "roma-court" if verdict else None,
                "attempts": 1 if verdict == "red" else 0,
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:01:00+00:00",
            },
            "leaf-b": {
                "node_id": "leaf-b",
                "parent": "root",
                "title": "Keep the old tree as projection only",
                "children": [],
                "state": "green",
                "verdict": "green",
                "evidence_ref": "court:green",
                "gate_kind": "manual",
                "gate_spec": {},
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:02:00+00:00",
            },
        },
    }


def test_sync_creates_addressable_tree_without_json_atoms(tmp_path):
    store = CellStore(tmp_path / "roma.sqlite3")
    value_protocol = bootstrap_value_graph_protocol(
        store, prefix="test:value-graph"
    )
    protocol = bootstrap_roma_requirement_protocol(
        store, prefix="test:roma"
    )

    result = sync_roma_requirement_tree(
        store,
        protocol,
        value_protocol,
        _tree(),
        source="brain.roma_atomize",
    )

    assert result["schema"] == "archhub-roma-requirement-tree-cell-sync/v1"
    assert result["tree_root"] == roma_tree_root("rt-demo")
    assert result["node_count"] == 3
    assert result["edge_count"] == 2
    projected = project_roma_requirement_tree(
        store.snapshot(), protocol, value_protocol, roma_tree_root("rt-demo")
    )
    assert projected["root_node"] == roma_node_root("rt-demo", "root")
    assert set(projected["edges"]) == {
        roma_edge_root("rt-demo", "root", "leaf-a"),
        roma_edge_root("rt-demo", "root", "leaf-b"),
    }
    leaf = projected["nodes"][roma_node_root("rt-demo", "leaf-a")]
    assert leaf["gate_kind"] == "pytest"
    assert leaf["gate_spec"]["selector"] == "test_sync_creates_addressable_tree"
    assert [item["node_id"] for item in projected["frontier"]] == ["leaf-a"]

    snapshot = store.snapshot()
    assert not any(
        cell.atom.startswith(b"{") or cell.atom.startswith(b"[")
        for cell in snapshot.cells.values()
    )
    tree_members = read_relation(snapshot, roma_tree_root("rt-demo"), budget=100_000)
    assert any(member.participant_id == roma_node_root("rt-demo", "leaf-a")
               for member in tree_members)


def test_sync_rewires_state_without_duplicate_state_members(tmp_path):
    store = CellStore(tmp_path / "roma.sqlite3")
    value_protocol = bootstrap_value_graph_protocol(store)
    protocol = bootstrap_roma_requirement_protocol(store)
    sync_roma_requirement_tree(store, protocol, value_protocol, _tree())
    before_revision = store.revision

    sync_roma_requirement_tree(
        store,
        protocol,
        value_protocol,
        _tree(state="claimed", claimed_by="agent-a", past_claimants=["agent-a"]),
    )

    assert store.revision == before_revision + 1
    node_root = roma_node_root("rt-demo", "leaf-a")
    members = read_relation(store.snapshot(), node_root, budget=100_000)
    state_members = [
        member for member in members
        if member.role_id == protocol.role("state-root")
    ]
    assert len(state_members) == 1
    projected = project_roma_requirement_tree(
        store.snapshot(), protocol, value_protocol, roma_tree_root("rt-demo")
    )
    leaf = projected["nodes"][node_root]
    assert leaf["state"] == "claimed"
    assert leaf["claimed_by"] == "agent-a"
    assert leaf["past_claimants"] == ("agent-a",)


def test_protocol_reopens_from_committed_cells(tmp_path):
    path = tmp_path / "roma.sqlite3"
    store = CellStore(path)
    value_protocol = bootstrap_value_graph_protocol(
        store, prefix="persist:value-graph"
    )
    protocol = bootstrap_roma_requirement_protocol(
        store, prefix="persist:roma"
    )
    sync_roma_requirement_tree(store, protocol, value_protocol, _tree())
    store.close()

    reopened = CellStore(path)
    restored_value = project_value_graph_protocol(
        reopened.snapshot(), prefix="persist:value-graph"
    )
    restored_roma = open_roma_requirement_protocol(
        reopened.snapshot(), prefix="persist:roma"
    )
    projected = project_roma_requirement_tree(
        reopened.snapshot(),
        restored_roma,
        restored_value,
        roma_tree_root("rt-demo"),
    )

    assert projected["node_count"] == 3
    assert projected["edges"]


def test_tree_index_projects_from_registry_relation(tmp_path):
    store = CellStore(tmp_path / "roma.sqlite3")
    value_protocol = bootstrap_value_graph_protocol(store)
    protocol = bootstrap_roma_requirement_protocol(store)
    sync_roma_requirement_tree(store, protocol, value_protocol, _tree())

    index = project_roma_requirement_tree_index(
        store.snapshot(), protocol, value_protocol
    )

    assert index["schema"] == "archhub-roma-requirement-tree-cell-index/v1"
    assert index["registry"] == protocol.registry_root
    assert index["tree_ids"] == ("rt-demo",)
    assert index["tree_count"] == 1
    assert index["trees"][0]["tree_root"] == roma_tree_root("rt-demo")
    assert index["trees"][0]["node_count"] == 3
    assert index["trees"][0]["frontier_count"] == 1
