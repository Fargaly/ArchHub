"""Architecture court for the Universal Cell physical floor.

The floor may know only Cells, relations, generic rewrites, contracts,
catalogues, and authorization.  Product-specific or legacy interpreters are
temporary outer-ring exceptions; this court is shrink-only so they cannot grow
while their behaviour is migrated into released graph assemblies.
"""
from __future__ import annotations

import ast
from pathlib import Path


NODE_LANGUAGE = Path(__file__).resolve().parents[1]
NODELANG = NODE_LANGUAGE / "nodelang"


# These are physical and generic protocol modules, not application assemblies.
FLOOR_IMPORTS = {
    # The set-digest is a leaf below the kernel: pure hashing over cell
    # rows, no kernel import (Cell = Any), so the physical floor gained a
    # module without gaining a doorway.
    "cell_set_digest": frozenset(),
    "universal_cell": frozenset({"cell_set_digest"}),
    "cell_protocols": frozenset({"universal_cell"}),
    "cell_rules": frozenset({"universal_cell", "cell_protocols"}),
    "cell_relation_contract": frozenset({"universal_cell", "cell_protocols"}),
    "cell_catalog": frozenset({
        "universal_cell", "cell_protocols", "cell_relation_contract",
    }),
    "cell_authorization": frozenset({"universal_cell", "cell_protocols"}),
}

# Existing exceptions are migration debt.  The set may only shrink.
OUTER_RING_EXCEPTION_BASELINE = frozenset({
    "cell_baboom_connector_execution",
    "cell_baboom_meeting_note_publication",
    "cell_baboom_model_execution",
    "cell_baboom_steward",
    "cell_legacy_brain_governance",
    "cell_legacy_core_nodes",
    "cell_legacy_custom_nodes",
    "cell_legacy_self_extension",
    "cell_legacy_surface_catalog",
    "cell_legacy_webshell_host",
})

OUTER_RING_RUNTIME_IMPORT_BASELINE = frozenset({
    "cell_baboom_meeting_note_publication",
    "cell_baboom_model_execution",
})


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _local_imports(path: Path) -> frozenset[str]:
    imports = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module:
            imports.add(node.module.split(".", 1)[0])
    return frozenset(imports)


def _calls_json_loads(path: Path) -> bool:
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and node.func.attr == "loads"
        ):
            return True
    return False


def test_physical_floor_has_no_product_imports_or_json_atom_interpreters():
    forbidden_terms = (
        "baboom", "brain", "workshop", "cockpit", "website",
        "monetization", "revit", "claude", "gemini", "codex",
    )
    for module, allowed_imports in FLOOR_IMPORTS.items():
        path = NODELANG / (module + ".py")
        source = path.read_text(encoding="utf-8").lower()
        assert _local_imports(path) <= allowed_imports, module
        assert not _calls_json_loads(path), module
        assert all(term not in source for term in forbidden_terms), module


def test_product_and_legacy_interpreter_modules_are_shrink_only():
    actual = frozenset(
        path.stem
        for path in NODELANG.glob("cell_*.py")
        if path.stem.startswith(("cell_baboom_", "cell_legacy_"))
    )
    assert actual <= OUTER_RING_EXCEPTION_BASELINE


def test_normal_runtime_has_no_legacy_interpreter_imports():
    for path in NODELANG.glob("*.py"):
        if path.stem.startswith("cell_legacy_"):
            continue
        assert not {
            module for module in _local_imports(path)
            if module.startswith("cell_legacy_")
        }, path.name


def test_normal_runtime_product_specific_imports_are_shrink_only():
    imports = frozenset().union(*(
        _local_imports(NODELANG / name)
        for name in (
            "universal_application.py",
            "application_server.py",
            "application_machine_transport.py",
        )
    ))
    actual = frozenset(
        module for module in imports if module.startswith("cell_baboom_")
    )
    assert actual <= OUTER_RING_RUNTIME_IMPORT_BASELINE
