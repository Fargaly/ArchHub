"""The real Grand Map authority on the universal-cell kernel."""
from collections.abc import Mapping
import json

from nodelang.cell_protocols import (
    inspect_properties,
    open_scoped_composition,
    prepare_append_relation_members,
    read_relation,
    set_property_atom,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, Snapshot
from nodelang.universal_map_import import (
    import_grand_map_cells,
    project_grand_map_cells,
)


def _source_counts():
    with open(resolve_map_path(), encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        "domains": len(data),
        "nodes": sum(len(domain.get("nodes", ())) for domain in data),
        "params": sum(
            len(node.get("params", ()))
            for domain in data for node in domain.get("nodes", ())
        ),
        "wires": sum(len(domain.get("wires", ())) for domain in data),
        "cross": sum(len(domain.get("cross", ())) for domain in data),
    }


def _built():
    store = CellStore()
    registry = import_grand_map_cells(store, resolve_map_path())
    return store, registry


class _IterationCountedCells(Mapping):
    def __init__(self, cells):
        self._cells = cells
        self.full_iterations = 0

    def __getitem__(self, key):
        return self._cells[key]

    def __iter__(self):
        self.full_iterations += 1
        return iter(self._cells)

    def __len__(self):
        return len(self._cells)


def test_full_authority_imports_in_one_atomic_revision_with_exact_counts():
    store, registry = _built()
    expected = _source_counts()
    assert store.revision == 1
    assert len(registry.domains) == expected["domains"]
    assert len(registry.nodes) == expected["nodes"]
    assert sum(len(params) for params in registry.params.values()) == expected["params"]
    assert len(registry.wires) == expected["wires"]
    assert len(registry.cross_relations) == expected["cross"]
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())


def test_import_has_no_legacy_class_or_nested_semantic_fields():
    store, _registry = _built()
    assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}
    forbidden = {"kind", "params", "body", "relations", "children", "ports"}
    assert not (forbidden & set(Cell.__dataclass_fields__))
    assert all(isinstance(cell.atom, bytes) for cell in store.snapshot().cells.values())


def test_all_parameter_rows_are_selectable_property_relations():
    store, registry = _built()
    expected = _source_counts()["params"]
    refs = [ref for params in registry.params.values() for ref in params.values()]
    assert len(refs) == expected
    for ref in refs:
        members = read_relation(store.snapshot(), ref.relation_root, budget=16)
        assert {member.role_id for member in members} == {
            registry.roles["owner"],
            registry.roles["value"],
            registry.roles["label"],
        }


def test_internal_and_cross_domain_wires_are_first_class_relation_cells():
    store, registry = _built()
    first_wire = registry.wires[0]
    wire_members = read_relation(store.snapshot(), first_wire, budget=16)
    assert {member.role_id for member in wire_members} == {
        registry.roles["source"], registry.roles["target"]
    }

    first_cross = registry.cross_relations[0]
    cross_members = read_relation(store.snapshot(), first_cross, budget=16)
    assert {member.role_id for member in cross_members} == {
        registry.roles["source"],
        registry.roles["target"],
        registry.roles["why"],
    }


def test_domain_and_whole_map_are_openable_compositions_without_group_kind():
    store, registry = _built()
    ui_region = open_scoped_composition(
        store.snapshot(), registry.domains["ui"],
        member_role=registry.roles["member"],
        scope_role=registry.roles["scope"],
        budget=10_000,
    )
    assert registry.nodes["ui_design_tokens"] in ui_region
    whole = open_scoped_composition(
        store.snapshot(), registry.grand_map_root,
        member_role=registry.roles["member"],
        scope_role=registry.roles["scope"],
        budget=10_000,
    )
    assert set(registry.domains.values()) <= whole


def test_real_design_token_is_visible_and_editable_through_property_lens():
    store, registry = _built()
    selected = registry.nodes["ui_design_tokens"]
    rows = inspect_properties(
        store.snapshot(),
        selected_root=selected,
        relation_roots=registry.properties["ui_design_tokens"],
        owner_role=registry.roles["owner"],
        value_role=registry.roles["value"],
        label_role=registry.roles["label"],
        budget=32,
    )
    by_label = {
        store.read(row.label_root).atom.decode("utf-8"): row for row in rows
    }
    accent = by_label["accent"]
    assert store.read(accent.value_root).atom == b"#d97757 (terracotta)"
    set_property_atom(
        store,
        accent.relation_root,
        value_role=registry.roles["value"],
        atom=b"#123456",
        budget=16,
    )
    assert store.read(accent.value_root).atom == b"#123456"


def test_same_authority_import_has_deterministic_cell_identities():
    first, _first_registry = _built()
    second, _second_registry = _built()
    assert first.snapshot().cells == second.snapshot().cells


def test_restart_projection_uses_the_graph_not_a_changed_import_file(tmp_path):
    source_path = tmp_path / "grand-map.json"
    with open(resolve_map_path(), encoding="utf-8") as handle:
        source = json.load(handle)
    source_path.write_text(json.dumps(source), encoding="utf-8")

    store = CellStore()
    imported = import_grand_map_cells(store, source_path)
    first_node = source[0]["nodes"][0]
    first_node.setdefault("params", []).append({
        "k": "must-not-enter-without-import",
        "v": "external mutation",
    })
    source_path.write_text(json.dumps(source), encoding="utf-8")

    restored = project_grand_map_cells(store.snapshot(), source_path)
    assert restored.nodes == imported.nodes
    assert restored.domains == imported.domains
    assert restored.wires == imported.wires
    assert restored.cross_relations == imported.cross_relations
    assert "must-not-enter-without-import" not in restored.params[
        source[0]["nodes"][0]["id"]
    ]


def test_restart_projection_indexes_cell_roots_once_not_once_per_property():
    store, imported = _built()
    original = store.snapshot()
    counted = _IterationCountedCells(original.cells)
    restored = project_grand_map_cells(Snapshot(original.revision, counted))

    assert restored.nodes == imported.nodes
    assert sum(len(refs) for refs in restored.root_properties.values()) > 3000
    assert counted.full_iterations <= 4


def test_map_projection_coexists_with_other_protocols_on_the_same_domain():
    store, imported = _built()
    domain_root = imported.domains["brain"]
    role_root = "test:role:property"
    value_root = "test:brain:property"
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot,
        domain_root,
        ((role_root, value_root),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            Cell(role_root, NULL_CELL_ID, NULL_CELL_ID, b"property"),
            Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, b"live app property"),
            *patch.create,
        ),
        replace=patch.replace,
    )

    projected = project_grand_map_cells(store.snapshot())
    assert projected.nodes == imported.nodes
    assert projected.domains == imported.domains
    assert projected.wires == imported.wires
