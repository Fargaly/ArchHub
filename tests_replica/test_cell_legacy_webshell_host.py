"""The legacy WebShell host boundary must be graph-held and fenced."""
from __future__ import annotations

import inspect
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = PRODUCT_ROOT / "12.PRODUCTION"
for path in (PUBLIC_ROOT, PUBLIC_ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from nodelang.cell_legacy_webshell_host import (  # noqa: E402
    ACTIVE_CELL_AUTHORITY,
    ROUTE_SPECS,
    bootstrap_legacy_webshell_host_protocol,
    build_legacy_webshell_host_contract,
    project_legacy_webshell_host_contract,
    route_contract_digest,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell  # noqa: E402
import nodelang.cell_legacy_webshell_host as contract_module  # noqa: E402
from production_webshell_preview import preview_bridge_source  # noqa: E402


def _contract_world():
    store = CellStore()
    protocol = bootstrap_legacy_webshell_host_protocol(store)
    built = build_legacy_webshell_host_contract(store, protocol)
    return store, protocol, built


def test_webshell_host_route_contract_is_cells_and_non_promotable():
    store, protocol, built = _contract_world()
    projection = project_legacy_webshell_host_contract(
        store.snapshot(), protocol, built.root_id
    )

    assert projection["route_count"] == 4
    assert projection["routes"] == ROUTE_SPECS
    assert projection["digest"] == route_contract_digest(ROUTE_SPECS)
    assert projection["promotion_allowed"] is False
    assert projection["active_authority"] == ACTIVE_CELL_AUTHORITY
    routes = {item["route"]: item for item in projection["routes"]}
    assert routes["/__archhub/universal-interaction"] == {
        "route": "/__archhub/universal-interaction",
        "method": "POST",
        "slot": "submit_universal_interaction",
        "authority": ACTIVE_CELL_AUTHORITY,
        "legacy_migration_only": "false",
        "cell_passthrough": "true",
        "body_limit_bytes": "1048576",
    }
    assert all(
        route.startswith("/__archhub")
        for route in routes
    )


def test_webshell_host_contract_matches_preview_routes_and_bridge_slots():
    preview_source = (
        PUBLIC_ROOT / "tools" / "production_webshell_preview.py"
    ).read_text(encoding="utf-8")
    pyqt_bridge = (PUBLIC_ROOT / "app" / "bridge.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    browser_bridge = preview_bridge_source()

    for spec in ROUTE_SPECS:
        route = spec["route"]
        slot = spec["slot"]
        assert route in preview_source or route in browser_bridge
        assert slot in preview_source or slot in pyqt_bridge or slot in browser_bridge
    assert "if size > 1_048_576" in preview_source
    assert "universal_canvas_interaction(payload)" in preview_source
    assert "universal_canvas_interaction(payload)" in pyqt_bridge
    assert "grand_map_ui_surface(surface or \"home-top\"" in preview_source
    assert "grand_map_ui_surface(requested_surface)" in pyqt_bridge
    assert "universal_grand_map_surface(requested_surface)" in pyqt_bridge


def test_webshell_host_contract_rejects_graph_drift():
    store, protocol, built = _contract_world()
    route_root = built.route_roots[-1]
    method_root = route_root + ":method"
    original = store.read(method_root)
    store.commit(store.revision, replace=(
        Cell(original.id, original.link0, original.link1, b"GET"),
    ))

    with pytest.raises(InvalidCell, match="digest drifted"):
        project_legacy_webshell_host_contract(
            store.snapshot(), protocol, built.root_id
        )


def test_webshell_host_contract_rejects_unnamespaced_or_unbounded_routes():
    store = CellStore()
    protocol = bootstrap_legacy_webshell_host_protocol(store)
    bad_route = dict(ROUTE_SPECS[0])
    bad_route["route"] = "/api/not-archhub"
    with pytest.raises(InvalidCell, match="namespaced"):
        build_legacy_webshell_host_contract(
            store, protocol, route_specs=(bad_route,)
        )

    store = CellStore()
    protocol = bootstrap_legacy_webshell_host_protocol(store)
    bad_limit = dict(ROUTE_SPECS[-1])
    bad_limit["body_limit_bytes"] = "-1"
    with pytest.raises(InvalidCell, match="body limit"):
        build_legacy_webshell_host_contract(
            store, protocol, route_specs=(bad_limit,)
        )


def test_webshell_host_contract_module_does_not_start_or_import_host():
    source = inspect.getsource(contract_module)
    for forbidden in (
        "make_server",
        "ThreadingHTTPServer",
        "serve_forever",
        "webbrowser",
        "PyQt",
        "ArchHubBridge",
        "subprocess",
        "open(",
        "exec(",
        "eval(",
    ):
        assert forbidden not in source
