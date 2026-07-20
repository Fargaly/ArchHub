from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from workflows.grand_map_ui import (  # noqa: E402
    default_grand_map_path,
    grand_map_ui_surface,
)


def _map(path: Path, nodes: list[dict]) -> None:
    path.write_text(
        json.dumps([
            {"key": "ui", "title": "UI", "nodes": nodes, "wires": []},
        ]),
        encoding="utf-8",
    )


def _domains(path: Path, domains: list[dict]) -> None:
    path.write_text(json.dumps(domains), encoding="utf-8")


def _node(node_id: str, title: str, status: str = "partial") -> dict:
    return {"id": node_id, "title": title, "status": status}


def _legacy_surface_names_from_source() -> tuple[str, ...]:
    source = (_APP / "workflows" / "grand_map_ui.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "grand_map_ui_surface":
            for child in ast.walk(node):
                if not isinstance(child, ast.Assign) or not isinstance(child.value, ast.Dict):
                    continue
                if not any(
                    isinstance(target, ast.Name) and target.id == "builders"
                    for target in child.targets
                ):
                    continue
                keys = [
                    key.value
                    for key in child.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                ]
                return tuple(keys)
    raise AssertionError("grand_map_ui_surface builders registry not found")


def test_legacy_grand_map_ui_surfaces_are_marked_non_authoritative():
    payload = grand_map_ui_surface("rail-drawer-shell")

    assert payload["ok"] is True
    assert payload["authority"] == "legacy-handbuilt-grand-map-ui-projection"
    assert payload["authority_status"] == "superseded_migration_evidence"
    assert payload["promotion_allowed"] is False
    assert payload["superseded_by"] == (
        "10.PRODUCT/13.NODE-LANGUAGE Universal Cell authority"
    )
    assert payload["authority"] != "10.PRODUCT/13.NODE-LANGUAGE"


def test_legacy_grand_map_surface_registry_is_frozen_until_cell_consumption():
    surfaces = _legacy_surface_names_from_source()
    digest = hashlib.sha256(
        "\n".join(sorted(surfaces)).encode("utf-8")
    ).hexdigest()

    assert len(surfaces) == 198
    assert digest == "b8be80ca1a2d34eb2873ab98d3847f4cbfa6e8aff61469f9accb5494b59cbda0"
    assert all(not surface.startswith("universal-") for surface in surfaces)


def test_legacy_grand_map_projection_module_does_not_claim_authority():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "workflows"
        / "grand_map_ui.py"
    ).read_text(encoding="utf-8")

    header = source.split('"""', 2)[1]
    normalized_header = " ".join(header.split())
    assert "migration evidence" in header
    assert "not the active Node Language authority" in normalized_header
    assert "universal_grand_map_surface" in header
    assert "planning authority" not in header
    assert (
        "New authority surfaces should be implemented through Universal Cell"
        in " ".join(source.split())
    )


def test_unknown_legacy_grand_map_surface_is_marked_non_authoritative():
    payload = grand_map_ui_surface("universal-future-surface")

    assert payload["ok"] is False
    assert payload["surface"] == "universal-future-surface"
    assert payload["error"] == "unknown legacy Grand Map UI surface"
    assert payload["authority"] == "legacy-handbuilt-grand-map-ui-projection"
    assert payload["authority_status"] == "superseded_migration_evidence"
    assert payload["promotion_allowed"] is False
    assert payload["superseded_by"] == (
        "10.PRODUCT/13.NODE-LANGUAGE Universal Cell authority"
    )
    assert payload["authority"] != "10.PRODUCT/13.NODE-LANGUAGE"


def test_rail_drawer_shell_is_a_legacy_node_surface():
    payload = grand_map_ui_surface("rail-drawer-shell")
    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:rail-drawer-shell"

    ui_nodes = {
        node["id"]: node
        for node in payload["nodes"]
        if node.get("type") == "ui.element"
    }
    expected = {
        "ui:grandmap:rail-drawer-shell",
        "ui:grandmap:rail-drawer-frame",
        "ui:grandmap:rail-drawer-header",
        "ui:grandmap:rail-drawer-title",
        "ui:grandmap:rail-drawer-spacer",
        "ui:grandmap:rail-drawer-close",
        "ui:grandmap:rail-drawer-body",
    }
    assert expected <= set(ui_nodes)
    assert ui_nodes["ui:grandmap:rail-drawer-shell"]["data"]["action"] == "rail.drawer.close"
    assert ui_nodes["ui:grandmap:rail-drawer-shell"]["data"]["test_id"] == "rail-drawer-overlay"
    assert ui_nodes["ui:grandmap:rail-drawer-frame"]["data"]["stop_click"] is True
    assert ui_nodes["ui:grandmap:rail-drawer-title"]["data"]["bind"] == "slot:rail-drawer-title"
    assert ui_nodes["ui:grandmap:rail-drawer-close"]["data"]["action"] == "rail.drawer.close"
    assert ui_nodes["ui:grandmap:rail-drawer-close"]["data"]["test_id"] == "rail-drawer-close"
    assert ui_nodes["ui:grandmap:rail-drawer-body"]["data"]["render_slot"] == "slot:rail-drawer-body"

    child_pairs = {
        (wire.get("from", {}).get("node"), wire.get("to", {}).get("node"))
        for wire in payload["wires"]
    }
    assert ("ui:grandmap:rail-drawer-shell", "ui:grandmap:rail-drawer-frame") in child_pairs
    assert ("ui:grandmap:rail-drawer-frame", "ui:grandmap:rail-drawer-header") in child_pairs
    assert ("ui:grandmap:rail-drawer-frame", "ui:grandmap:rail-drawer-body") in child_pairs


def test_rail_drawer_host_renders_the_authority_surface_and_routes_close_actions():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const seedGrandMapRailDrawerShellFallbackNodes ="):
        jsx.index("const ensureGrandMapSidebarShellNodes =")
    ]
    host = jsx[
        jsx.index("const RAIL_DRAWER_META ="):
        jsx.index("const RailDrawerHost = React.memo", jsx.index("const RAIL_DRAWER_META ="))
    ]

    assert "bridgeAsync('get_grand_map_ui_surface', 'rail-drawer-shell')" in helper
    assert "syncGrandMapSurfaceStateSlots('rail-drawer-shell', rootId, slotMap" in helper
    assert "test_id:resolvedMeta.testid || 'rail-drawer'" in helper
    assert "'data-rail-drawer': panel || ''" in helper
    assert "const RailDrawerShellSurface = ({ panel, meta, body }) =>" in host
    assert 'surface="rail-drawer-shell"' in host
    assert "renderSlots={{ ['slot:rail-drawer-body']:body }}" in host
    assert "return <RailDrawerShellSurface panel={panel} meta={meta} body={body}/>;" in host
    assert "dispatchRailDrawerCloseAction('escape', e)" in host
    assert "registerUiHostCapability('rail.drawer.close'" in host
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction);" not in host
    assert 'onClick={close} data-testid="rail-drawer-overlay"' not in host


def _child_wire_pairs(payload: dict) -> set[tuple[str, str]]:
    return {
        (wire["from"]["node"], wire["to"]["node"])
        for wire in payload["wires"]
        if not str(wire["to"]["node"]).startswith("param:")
        and wire.get("data", {}).get("role") not in {
            "ui_action_relation",
            "ui_action_parameter_relation",
            "ui_binding_relation",
        }
    }


def _non_parameter_nodes(payload: dict) -> list[dict]:
    return [
        node
        for node in payload["nodes"]
        if node.get("data", {}).get("role") not in {"parameter", "ui_action"}
    ]


def test_ui_graph_identity_lookup_uses_a_repairable_array_index():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const __uiArrayIdentityIndexes ="):
        jsx.index("const _uiSafeId =", jsx.index("const __uiArrayIdentityIndexes ="))
    ]
    setter = jsx[
        jsx.index("window.ahSetUiNodeParam = function"):
        jsx.index("window.ahEditUiNode = function", jsx.index("window.ahSetUiNodeParam = function"))
    ]

    assert "new WeakMap()" in helper
    assert "list.length < state.indexedLength" in helper
    assert "for (let index = state.indexedLength; index < list.length; index += 1)" in helper
    assert "list[cached.index] === cached.item" in helper
    assert "if (!cached) return null;" in helper
    assert "Node/wire identity is immutable" in helper
    assert "state.byId.set(id, { item, index });" in helper
    assert "const _uiIndexOf = (items, id) =>" in helper
    assert "if (cached && list[cached.index] === item) return cached.index;" in helper
    assert "var n = _uiFind(g.nodes, id);" in setter
    assert "var candidate = _uiFind(g.nodes, n.data.param_nodes[i]);" in setter
    assert "var existingParamNode = _uiFind(g.nodes, paramNodeId);" in setter
    assert "if (!_uiFind(g.wires, wireId))" in setter


def test_ui_relation_materializers_use_identity_index_for_exact_wire_ids():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const syncUiBindingRelation ="):
        jsx.index("const rightRailConnectionWireId =", jsx.index("const syncUiBindingRelation ="))
    ]

    assert "const index = _uiIndexOf(g.wires, payload.id);" in helper
    assert "const wire = _uiFind(g.wires, wireId);" in helper
    assert "if (!_uiFind(g.wires, wireId))" in helper
    assert "const existingLinkIndex = _uiIndexOf(g.wires, linkId);" in helper
    assert "const ownerWireIndex = _uiIndexOf(g.wires, ownerWireId);" in helper
    assert "g.wires.findIndex(w => w && w.id === payload.id)" not in helper


def test_graph_health_validation_waits_for_node_graph_materialization_to_settle():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    server_strip = jsx[
        jsx.index("const ServerStrip ="):
        jsx.index("const HealthStripItem =", jsx.index("const ServerStrip ="))
    ]
    health_strip = jsx[
        jsx.index("const HealthStripItem ="):
        jsx.index("window.StudioLM = StudioLM;", jsx.index("const HealthStripItem ="))
    ]

    assert "let validationTimer = null;" in server_strip
    assert "const onBump = () => schedulePull(650);" in server_strip
    assert "const onValidated = () => schedulePull(0);" in server_strip
    assert "if (validationTimer) clearTimeout(validationTimer);" in server_strip
    assert "const onBump = () => pull();" not in server_strip
    assert "let bumpTimer = null;" in health_strip
    assert "bumpTimer = setTimeout(() => {" in health_strip
    assert "}, 350);" in health_strip


def test_node_connection_scan_rejects_non_incident_wires_before_authority_expansion():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const nodeConnectionRowsFromGraphWires ="):
        jsx.index("const nodeConnectionLayerRows =", jsx.index("const nodeConnectionRowsFromGraphWires ="))
    ]

    assert "const graphNodeById = new Map();" in helper
    assert "const wireNodeByLogicalWireId = new Map();" in helper
    assert "resolvePortEndpoint(graphNodes, fromNode, graphNodeById)" in helper
    assert "resolvePortEndpoint(graphNodes, toNode, graphNodeById)" in helper
    assert helper.index("if (!isOutgoing && !isIncoming) return;") < helper.index(
        "const authorityWireData = wireNode"
    )
    assert "graphNodeById.get(relationNodeId) || wireNodeByLogicalWireId.get(logicalWireId)" in helper


def test_grand_map_home_surface_emits_production_ui_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_design_tokens", "Design Tokens"),
        _node("ui_account_chip", "Account Chip"),
        _node("ui_composer_bar", "Composer Bar"),
        _node("ui_command_palette", "Command Palette"),
    ])

    payload = grand_map_ui_surface("home-top", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:home-top"
    assert payload["source"] == str(grand_map)
    assert payload["source_node_ids"] == [
        "ui_design_tokens",
        "ui_account_chip",
        "ui_composer_bar",
        "ui_command_palette",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui_design_tokens"]["type"] == "ui.element"
    assert nodes["ui_design_tokens"]["data"]["source_map_node"] == "ui_design_tokens"
    assert nodes["ui_design_tokens"]["data"].get("text", "") == ""
    assert nodes["ui_account_chip"]["data"]["source_title"] == "Account Chip"
    assert nodes["ui_account_chip"]["data"]["bind"] == "slot:signed"
    assert nodes["ui_account_chip"]["data"]["action"] == "account.open"
    assert nodes["ui_composer_bar"]["data"]["bind"] == "slot:session-count"
    assert nodes["ui_command_palette"]["data"]["bind"] == "slot:model"
    assert nodes["ui_command_palette"]["data"]["action"] == "model.picker.open"
    assert nodes["ui:grandmap:brain"]["data"]["bind"] == "slot:brain"
    assert nodes["ui:grandmap:brain"]["data"]["action"] == "brain.folders.open"
    assert nodes["ui:grandmap:graph"]["data"]["bind"] == "slot:graph"
    assert nodes["ui:grandmap:graph"]["data"]["action"] == "graph.health.open"
    assert nodes["slot:model"]["type"] == "data.constant"
    assert nodes["slot:signed"]["data"]["value"] == "sign in"
    assert nodes["slot:session-count"]["data"]["value"] == ""
    assert nodes["slot:brain"]["data"]["value"] == "brain: idle"
    assert nodes["slot:graph"]["data"]["value"] == "graph: no canvas open"
    assert nodes["ui:grandmap:home-top"]["data"].get("text", "") == ""
    assert nodes["ui:grandmap:home-top"]["data"]["children"] == [
        "ui_design_tokens",
        "ui_command_palette",
        "ui_account_chip",
        "ui_composer_bar",
        "ui:grandmap:brain",
        "ui:grandmap:graph",
    ]

    wire_pairs = {
        (wire["from"]["node"], wire["to"]["node"])
        for wire in payload["wires"]
    }
    assert ("ui:grandmap:home-top", "ui_design_tokens") in wire_pairs
    assert ("ui_design_tokens", "ui:grandmap:arch") in wire_pairs
    assert ("ui:grandmap:home-top", "ui:grandmap:graph") in wire_pairs

    wires = {wire["id"]: wire for wire in payload["wires"]}
    assert wires["w:ui-binding:slot-signed->ui_account_chip:bind"] == {
        "id": "w:ui-binding:slot-signed->ui_account_chip:bind",
        "from": {"node": "slot:signed", "port": "value"},
        "to": {"node": "ui_account_chip", "port": "binding:bind"},
        "data": {
            "role": "ui_binding_relation",
            "relation": "drives_bind",
            "source_node": "slot:signed",
            "target_node": "ui_account_chip",
            "binding_key": "bind",
            "value_key": "bind",
        },
    }
    assert "w:ui-binding:slot-brain->ui-grandmap-brain:bind" in wires
    assert "w:ui-binding:slot-graph->ui-grandmap-graph:bind" in wires
    assert "w:ui-binding:slot-signed->ui_account_chip:bind" in nodes["ui_account_chip"]["data"]["binding_wires"]


def test_grand_map_home_surface_rejects_missing_authority(tmp_path):
    missing = tmp_path / "missing.json"
    payload = grand_map_ui_surface("home-top", grand_map_path=missing)

    assert payload["ok"] is False
    assert payload["source"] == str(missing)
    assert "FileNotFoundError" in payload["error"]


def test_grand_map_sessions_header_emits_node_surface(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_open_session", "Open Session"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-sessions-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:sessions-header"
    assert payload["source_node_ids"] == [
        "sessions_threads_rail",
        "sessions_open_session",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:sessions-title"]["data"]["source_map_node"] == "sessions_threads_rail"
    assert nodes["ui:grandmap:sessions-count"]["data"]["bind"] == "slot:session-count"
    assert nodes["ui:grandmap:sessions-action"]["data"]["source_map_node"] == "sessions_open_session"
    assert nodes["ui:grandmap:sessions-action"]["data"].get("text", "") == ""
    assert nodes["slot:session-count"]["type"] == "data.constant"

    assert _child_wire_pairs(payload) == {
        ("ui:grandmap:sessions-header", "ui:grandmap:sessions-title"),
        ("ui:grandmap:sessions-header", "ui:grandmap:sessions-count"),
        ("ui:grandmap:sessions-header", "ui:grandmap:sessions-action"),
    }


def test_grand_map_chat_session_row_emits_open_menu_and_state_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_open_session", "Open Session"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("chat-session-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:chat-session-row"
    assert payload["source_node_ids"] == [
        "sessions_threads_rail",
        "sessions_open_session",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:chat-session-title"]["data"]["value"] == "Session"
    assert nodes["slot:chat-session-state"]["data"]["value"] == "idle"
    assert nodes["slot:chat-session-active"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:chat-session-row"]["data"]["children"] == [
        "ui:grandmap:chat-session-open",
        "ui:grandmap:chat-session-more",
        "ui:grandmap:chat-session-menu",
    ]
    assert nodes["ui:grandmap:chat-session-open"]["data"]["action"] == (
        "sessions.chat.row.open"
    )
    assert nodes["ui:grandmap:chat-session-open"]["data"]["active_bind"] == (
        "slot:chat-session-active"
    )
    assert nodes["ui:grandmap:chat-session-dot"]["data"]["state_bind"] == (
        "slot:chat-session-state"
    )
    assert nodes["ui:grandmap:chat-session-title"]["data"]["bind"] == (
        "slot:chat-session-title"
    )
    assert nodes["ui:grandmap:chat-session-more"]["data"]["action"] == (
        "sessions.chat.row.menu.toggle"
    )
    assert nodes["ui:grandmap:chat-session-menu"]["data"]["render_slot"] == (
        "slot:chat-session-menu"
    )

    assert _child_wire_pairs(payload) == {
        ("ui:grandmap:chat-session-row", "ui:grandmap:chat-session-open"),
        ("ui:grandmap:chat-session-row", "ui:grandmap:chat-session-more"),
        ("ui:grandmap:chat-session-row", "ui:grandmap:chat-session-menu"),
        ("ui:grandmap:chat-session-open", "ui:grandmap:chat-session-dot"),
        ("ui:grandmap:chat-session-open", "ui:grandmap:chat-session-title"),
    }


def test_grand_map_chat_panel_header_emits_menu_and_new_chat_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_open_session", "Open Session"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("chat-panel-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:chat-panel-header"
    assert payload["source_node_ids"] == [
        "sessions_threads_rail",
        "sessions_open_session",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:chat-panel-title"]["data"]["value"] == "Chats"
    assert nodes["slot:chat-panel-active-session"]["data"]["value"] == ""
    assert nodes["ui:grandmap:chat-panel-header"]["data"]["children"] == [
        "ui:grandmap:chat-panel-title",
        "ui:grandmap:chat-panel-spacer",
        "ui:grandmap:chat-panel-menu",
        "ui:grandmap:chat-panel-new",
    ]
    assert nodes["ui:grandmap:chat-panel-title"]["data"]["bind"] == "slot:chat-panel-title"
    assert nodes["ui:grandmap:chat-panel-menu"]["data"]["action"] == (
        "sessions.chat.panel.menu.toggle"
    )
    assert nodes["ui:grandmap:chat-panel-new"]["data"]["action"] == "session.create"

    assert _child_wire_pairs(payload) == {
        ("ui:grandmap:chat-panel-header", "ui:grandmap:chat-panel-title"),
        ("ui:grandmap:chat-panel-header", "ui:grandmap:chat-panel-spacer"),
        ("ui:grandmap:chat-panel-header", "ui:grandmap:chat-panel-menu"),
        ("ui:grandmap:chat-panel-header", "ui:grandmap:chat-panel-new"),
    }


def test_grand_map_chat_panel_search_emits_bound_input_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("chat-panel-search", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:chat-panel-search"
    assert payload["source_node_ids"] == ["sessions_threads_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:chat-search-query"]["data"]["value"] == ""
    assert nodes["ui:grandmap:chat-panel-search"]["data"]["children"] == [
        "ui:grandmap:chat-search-row",
    ]
    assert nodes["ui:grandmap:chat-search-row"]["data"]["children"] == [
        "ui:grandmap:chat-search-icon",
        "ui:grandmap:chat-search-input",
    ]
    assert nodes["ui:grandmap:chat-search-input"]["data"]["tag"] == "input"
    assert nodes["ui:grandmap:chat-search-input"]["data"]["bind"] == (
        "slot:chat-search-query"
    )
    assert nodes["ui:grandmap:chat-search-input"]["data"]["action"] == (
        "sessions.chat.search.update"
    )
    assert nodes["ui:grandmap:chat-search-input"]["data"]["placeholder"] == (
        "Search chats..."
    )


def test_grand_map_chat_panel_shell_emits_panel_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_threads_rail", "Threads Rail")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("chat-panel-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:chat-panel-shell"
    assert payload["source_node_ids"] == ["sessions_threads_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:chat-panel-shell"]["data"]["cls"] == "ah-chat-panel-shell-node"
    assert nodes["ui:grandmap:chat-panel-shell"]["data"]["children"] == [
        "ui:grandmap:chat-panel-shell-header",
        "ui:grandmap:chat-panel-shell-search",
        "ui:grandmap:chat-panel-shell-list",
        "ui:grandmap:chat-panel-shell-menu",
        "ui:grandmap:chat-panel-shell-account",
    ]
    assert nodes["ui:grandmap:chat-panel-shell-header"]["data"]["render_slot"] == (
        "slot:chat-panel-shell-header"
    )
    assert nodes["ui:grandmap:chat-panel-shell-search"]["data"]["render_slot"] == (
        "slot:chat-panel-shell-search"
    )
    assert nodes["ui:grandmap:chat-panel-shell-list"]["data"]["render_slot"] == (
        "slot:chat-panel-shell-list"
    )
    assert nodes["ui:grandmap:chat-panel-shell-menu"]["data"]["render_slot"] == (
        "slot:chat-panel-shell-menu"
    )
    assert nodes["ui:grandmap:chat-panel-shell-account"]["data"]["render_slot"] == (
        "slot:chat-panel-shell-account"
    )


def test_grand_map_chat_panel_list_emits_content_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_threads_rail", "Threads Rail")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("chat-panel-list", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:chat-panel-list"
    assert payload["source_node_ids"] == ["sessions_threads_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:chat-panel-list"]["data"]["cls"] == (
        "ah-chat-panel-list-node ah-scroll"
    )
    assert nodes["ui:grandmap:chat-panel-list"]["data"]["render_slot"] == (
        "slot:chat-panel-list-content"
    )


def test_grand_map_chat_panel_message_emits_bound_message_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_threads_rail", "Threads Rail")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("chat-panel-message", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:chat-panel-message"
    assert payload["source_node_ids"] == ["sessions_threads_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:chat-panel-message"]["data"]["value"] == ""
    assert nodes["ui:grandmap:chat-panel-message"]["data"]["cls"] == (
        "ah-chat-panel-message-node"
    )
    assert nodes["ui:grandmap:chat-panel-message"]["data"]["bind"] == (
        "slot:chat-panel-message"
    )


def test_chat_panel_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    header = jsx[
        jsx.index("const ensureGrandMapChatPanelHeaderNodes ="):
        jsx.index("const ensureGrandMapChatPanelSearchNodes =", jsx.index("const ensureGrandMapChatPanelHeaderNodes ="))
    ]
    search = jsx[
        jsx.index("const ensureGrandMapChatPanelSearchNodes ="):
        jsx.index("const ensureGrandMapChatPanelListNodes =", jsx.index("const ensureGrandMapChatPanelSearchNodes ="))
    ]
    message = jsx[
        jsx.index("const ensureGrandMapChatPanelMessageNodes ="):
        jsx.index("const ensureGrandMapSkillsPanelShellNodes =", jsx.index("const ensureGrandMapChatPanelMessageNodes ="))
    ]

    assert "syncGrandMapSurfaceStateSlots('chat-panel-header', rootId, slotMap" in header
    assert "state_key: 'chat_panel_header_state_node_id'" in header
    assert "'slot:chat-panel-title': slots && slots.title ? slots.title : 'Chats'" in header
    assert "'slot:chat-panel-active-session': slots && slots.activeSessionId ? slots.activeSessionId : ''" in header
    assert "syncGrandMapSurfaceStateSlots('chat-panel-search', rootId, slotMap" in search
    assert "state_key: 'chat_panel_search_state_node_id'" in search
    assert "'slot:chat-search-query': slots && slots.query ? slots.query : ''" in search
    assert "syncGrandMapSurfaceStateSlots('chat-panel-message', rootId, slotMap" in message
    assert "state_key: 'chat_panel_message_state_node_id'" in message
    assert "'slot:chat-panel-message': slots && slots.message ? slots.message : ''" in message


def test_grand_map_skills_panel_header_emits_save_action_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Brain Skills")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skills-panel-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:skills-panel-header"
    assert payload["source_node_ids"] == ["brain_skills"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:skills-panel-count"]["data"]["value"] == "0"
    assert nodes["ui:grandmap:skills-panel-header"]["data"]["children"] == [
        "ui:grandmap:skills-panel-title",
        "ui:grandmap:skills-panel-count",
        "ui:grandmap:skills-panel-spacer",
        "ui:grandmap:skills-panel-save",
    ]
    assert nodes["ui:grandmap:skills-panel-title"]["data"]["bind"] == (
        "slot:skills-panel-title"
    )
    assert nodes["ui:grandmap:skills-panel-count"]["data"]["bind"] == (
        "slot:skills-panel-count"
    )
    assert nodes["ui:grandmap:skills-panel-save"]["data"]["action"] == (
        "skills.save.current"
    )


def test_grand_map_skills_panel_search_emits_bound_input_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Brain Skills")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skills-panel-search", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:skills-panel-search"
    assert payload["source_node_ids"] == ["brain_skills"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:skills-search-query"]["data"]["value"] == ""
    assert nodes["ui:grandmap:skills-search-input"]["data"]["tag"] == "input"
    assert nodes["ui:grandmap:skills-search-input"]["data"]["bind"] == (
        "slot:skills-search-query"
    )
    assert nodes["ui:grandmap:skills-search-input"]["data"]["action"] == (
        "skills.search.update"
    )
    assert nodes["ui:grandmap:skills-search-input"]["data"]["placeholder"] == (
        "Search saved skills..."
    )


def test_grand_map_skills_panel_list_emits_scroll_slot_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Brain Skills")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skills-panel-list", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:skills-panel-list"
    assert payload["source_node_ids"] == ["brain_skills"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:skills-panel-list"]["data"]["cls"] == (
        "ah-skills-panel-list-node ah-scroll"
    )
    assert nodes["ui:grandmap:skills-panel-list"]["data"]["render_slot"] == (
        "slot:skills-panel-list-content"
    )
    assert nodes["ui:grandmap:skills-panel-list"]["data"]["test_id"] == (
        "skills-panel-list"
    )


def test_grand_map_skills_panel_message_emits_bound_message_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Brain Skills")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skills-panel-message", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:skills-panel-message"
    assert payload["source_node_ids"] == ["brain_skills"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:skills-panel-message"]["data"]["value"] == ""
    assert nodes["ui:grandmap:skills-panel-message"]["data"]["cls"] == (
        "ah-skills-panel-message-node"
    )
    assert nodes["ui:grandmap:skills-panel-message"]["data"]["bind"] == (
        "slot:skills-panel-message"
    )
    assert nodes["ui:grandmap:skills-panel-message"]["data"]["test_id"] == (
        "skills-panel-message"
    )


def test_grand_map_skills_panel_shell_emits_panel_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Brain Skills")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skills-panel-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:skills-panel-shell"
    assert payload["source_node_ids"] == ["brain_skills"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:skills-panel-shell"]["data"]["cls"] == (
        "ah-skills-panel-shell-node"
    )
    assert nodes["ui:grandmap:skills-panel-shell"]["data"]["children"] == [
        "ui:grandmap:skills-panel-shell-header",
        "ui:grandmap:skills-panel-shell-search",
        "ui:grandmap:skills-panel-shell-list",
    ]
    assert nodes["ui:grandmap:skills-panel-shell-header"]["data"]["render_slot"] == (
        "slot:skills-panel-shell-header"
    )
    assert nodes["ui:grandmap:skills-panel-shell-search"]["data"]["render_slot"] == (
        "slot:skills-panel-shell-search"
    )
    assert nodes["ui:grandmap:skills-panel-shell-list"]["data"]["render_slot"] == (
        "slot:skills-panel-shell-list"
    )


def test_grand_map_skills_panel_row_emits_spawn_json_badge_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Brain Skills")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skills-panel-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:skills-row"
    assert payload["source_node_ids"] == ["brain_skills"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:skills-row-name"]["data"]["value"] == "Skill"
    assert nodes["slot:skills-row-badge"]["data"]["value"] == "P"
    assert nodes["ui:grandmap:skills-row"]["data"]["action"] == "skills.row.spawn"
    assert nodes["ui:grandmap:skills-row"]["data"]["draggable"] is True
    assert nodes["ui:grandmap:skills-row"]["data"]["drag_mime"] == (
        "application/x-archhub-skill"
    )
    assert nodes["ui:grandmap:skills-row"]["data"]["children"] == [
        "ui:grandmap:skills-row-main",
        "ui:grandmap:skills-row-sub",
    ]
    assert nodes["ui:grandmap:skills-row-main"]["data"]["children"] == [
        "ui:grandmap:skills-row-mark",
        "ui:grandmap:skills-row-name",
        "ui:grandmap:skills-row-json",
        "ui:grandmap:skills-row-badge",
    ]
    assert nodes["ui:grandmap:skills-row-name"]["data"]["bind"] == "slot:skills-row-name"
    assert nodes["ui:grandmap:skills-row-json"]["data"]["action"] == (
        "skills.row.view-json"
    )
    assert nodes["ui:grandmap:skills-row-badge"]["data"]["bind"] == (
        "slot:skills-row-badge"
    )
    assert nodes["ui:grandmap:skills-row-badge"]["data"]["state_bind"] == (
        "slot:skills-row-mode"
    )
    assert nodes["ui:grandmap:skills-row-sub"]["data"]["bind"] == "slot:skills-row-sub"

    for node_id, node in nodes.items():
        assert node.get("params"), f"{node_id} has no editable parameter list"
        assert node.get("config_schema"), f"{node_id} has no visual config schema"
        assert node.get("config"), f"{node_id} has no editable config mirror"

    root_params = {param["k"]: param["v"] for param in nodes["ui:grandmap:skills-row"]["params"]}
    assert root_params["tag"] == "div"
    assert root_params["action"] == "skills.row.spawn"
    assert root_params["draggable"] is True
    assert root_params["drag_mime"] == "application/x-archhub-skill"
    assert root_params["children"] == [
        "ui:grandmap:skills-row-main",
        "ui:grandmap:skills-row-sub",
    ]

    name_params = {
        param["k"]: param["v"]
        for param in nodes["ui:grandmap:skills-row-name"]["params"]
    }
    assert name_params["bind"] == "slot:skills-row-name"
    assert nodes["slot:skills-row-name"]["params"] == [
        {"k": "value", "label": "value", "type": "text", "v": "Skill"}
    ]

    root_param_id = "param:ui:grandmap:skills-row:action"
    assert root_param_id in nodes
    assert nodes[root_param_id]["type"] == "stem.node"
    assert nodes[root_param_id]["data"]["role"] == "parameter"
    assert nodes[root_param_id]["data"]["adapts_to"] == "ui.element"
    assert nodes[root_param_id]["data"]["owner"] == "ui:grandmap:skills-row"
    assert nodes[root_param_id]["data"]["key"] == "action"
    assert nodes[root_param_id]["data"]["value"] == "skills.row.spawn"
    assert nodes[root_param_id]["data"]["value_type"] == "text"
    assert root_param_id in nodes["ui:grandmap:skills-row"]["data"]["param_nodes"]
    assert root_param_id in nodes["ui:grandmap:skills-row"]["data"]["group_nodes"]
    assert "ui:grandmap:skills-row-main" in nodes["ui:grandmap:skills-row"]["data"]["group_nodes"]

    slot_param_id = "param:slot:skills-row-name:value"
    assert slot_param_id in nodes
    assert nodes[slot_param_id]["type"] == "stem.node"
    assert nodes[slot_param_id]["data"]["role"] == "parameter"
    assert nodes[slot_param_id]["data"]["adapts_to"] == "data.constant"
    assert slot_param_id in nodes["slot:skills-row-name"]["data"]["param_nodes"]

    assert not [
        node["type"]
        for node in nodes.values()
        if node["type"] in {"ui.parameter", "data.parameter"}
    ]

    wire_pairs = {
        (wire["from"]["node"], wire["from"]["port"], wire["to"]["node"], wire["to"]["port"])
        for wire in payload["wires"]
    }
    assert (
        "ui:grandmap:skills-row",
        "param:action",
        root_param_id,
        "owner",
    ) in wire_pairs


def test_grand_map_search_panel_shell_emits_panel_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_command_palette", "Command Palette")],
            "wires": [],
        },
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_threads_rail", "Threads Rail")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_lm_graph_state", "LM_GRAPH State Store")],
            "wires": [],
        },
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [
                _node("brain_skills", "Skill Library"),
                _node("brain_fact_store", "Fact Store"),
            ],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
        {
            "key": "connectors",
            "title": "Connectors",
            "nodes": [_node("connectors_panel", "Connector Panel")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("search-panel-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:search-panel-shell"
    assert payload["source_node_ids"] == [
        "ui_command_palette",
        "sessions_threads_rail",
        "canvas_lm_graph_state",
        "brain_skills",
        "brain_fact_store",
        "nodes_library_search",
        "connectors_panel",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:search-panel-shell"]["data"]["cls"] == (
        "ah-search-panel-shell-node"
    )
    assert nodes["ui:grandmap:search-panel-shell"]["data"]["children"] == [
        "ui:grandmap:search-panel-shell-header",
        "ui:grandmap:search-panel-shell-search",
        "ui:grandmap:search-panel-shell-scopes",
        "ui:grandmap:search-panel-shell-results",
    ]
    assert nodes["ui:grandmap:search-panel-shell-header"]["data"]["render_slot"] == (
        "slot:search-panel-shell-header"
    )
    assert nodes["ui:grandmap:search-panel-shell-search"]["data"]["render_slot"] == (
        "slot:search-panel-shell-search"
    )
    assert nodes["ui:grandmap:search-panel-shell-scopes"]["data"]["render_slot"] == (
        "slot:search-panel-shell-scopes"
    )
    assert nodes["ui:grandmap:search-panel-shell-results"]["data"]["render_slot"] == (
        "slot:search-panel-shell-results"
    )


def test_grand_map_search_panel_inner_surfaces_emit_node_authority(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_command_palette", "Command Palette")],
            "wires": [],
        },
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_threads_rail", "Threads Rail")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_lm_graph_state", "LM_GRAPH State Store")],
            "wires": [],
        },
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [
                _node("brain_skills", "Skill Library"),
                _node("brain_fact_store", "Fact Store"),
            ],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
        {
            "key": "connectors",
            "title": "Connectors",
            "nodes": [_node("connectors_panel", "Connector Panel")],
            "wires": [],
        },
    ])

    header = grand_map_ui_surface("search-panel-header", grand_map_path=grand_map)
    input_surface = grand_map_ui_surface("search-panel-input", grand_map_path=grand_map)
    scopes_list = grand_map_ui_surface("search-panel-scopes-list", grand_map_path=grand_map)
    scope_row = grand_map_ui_surface("search-panel-scope-row", grand_map_path=grand_map)
    results_list = grand_map_ui_surface("search-panel-results-list", grand_map_path=grand_map)
    empty = grand_map_ui_surface("search-panel-empty-state", grand_map_path=grand_map)
    hit = grand_map_ui_surface("search-panel-hit-row", grand_map_path=grand_map)

    assert header["ok"] is True
    header_nodes = {node["id"]: node for node in header["nodes"]}
    assert header_nodes["ui:grandmap:search-panel-title"]["data"]["bind"] == (
        "slot:search-panel-title"
    )

    assert input_surface["ok"] is True
    input_nodes = {node["id"]: node for node in input_surface["nodes"]}
    assert input_nodes["ui:grandmap:search-input-field"]["data"]["tag"] == "input"
    assert input_nodes["ui:grandmap:search-input-field"]["data"]["action"] == (
        "search.query.update"
    )
    assert input_nodes["ui:grandmap:search-input-field"]["data"]["bind"] == (
        "slot:search-query"
    )

    assert scopes_list["ok"] is True
    scopes_list_nodes = {node["id"]: node for node in scopes_list["nodes"]}
    assert scopes_list_nodes["ui:grandmap:search-panel-scopes-list"]["data"]["cls"] == (
        "ah-search-scopes-list-node"
    )
    assert scopes_list_nodes["ui:grandmap:search-panel-scopes-list"]["data"]["render_slot"] == (
        "slot:search-panel-scopes-list-content"
    )

    assert scope_row["ok"] is True
    scope_nodes = {node["id"]: node for node in scope_row["nodes"]}
    assert scope_nodes["ui:grandmap:search-scope-row"]["data"]["action"] == (
        "search.scope.pick"
    )
    assert scope_nodes["ui:grandmap:search-scope-row"]["data"]["active_bind"] == (
        "slot:search-scope-active"
    )
    assert scope_nodes["ui:grandmap:search-scope-count"]["data"]["bind"] == (
        "slot:search-scope-count"
    )

    assert results_list["ok"] is True
    results_list_nodes = {node["id"]: node for node in results_list["nodes"]}
    assert results_list_nodes["ui:grandmap:search-panel-results-list"]["data"]["cls"] == (
        "ah-search-results-list-node ah-scroll"
    )
    assert results_list_nodes["ui:grandmap:search-panel-results-list"]["data"]["render_slot"] == (
        "slot:search-panel-results-list-content"
    )
    assert results_list_nodes["ui:grandmap:search-panel-results-list"]["data"]["test_id"] == (
        "search-panel-results-list"
    )

    empty_nodes = {node["id"]: node for node in empty["nodes"]}
    assert empty_nodes["ui:grandmap:search-empty-state"]["data"]["visible_when"] == {
        "bind": "slot:search-empty-visible",
        "values": ["true"],
    }

    assert hit["ok"] is True
    hit_nodes = {node["id"]: node for node in hit["nodes"]}
    assert hit_nodes["ui:grandmap:search-hit-row"]["data"]["action"] == (
        "search.hit.activate"
    )
    assert hit_nodes["ui:grandmap:search-hit-row"]["data"]["disabled_bind"] == (
        "slot:search-hit-disabled"
    )
    assert hit_nodes["ui:grandmap:search-hit-sub"]["data"]["visible_when"] == {
        "bind": "slot:search-hit-sub-visible",
        "values": ["true"],
    }


def test_search_panel_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    header = jsx[
        jsx.index("const ensureGrandMapSearchPanelHeaderNodes ="):
        jsx.index(
            "const ensureGrandMapSearchPanelInputNodes =",
            jsx.index("const ensureGrandMapSearchPanelHeaderNodes ="),
        )
    ]
    input_nodes = jsx[
        jsx.index("const ensureGrandMapSearchPanelInputNodes ="):
        jsx.index(
            "const ensureGrandMapSearchPanelScopesLabelNodes =",
            jsx.index("const ensureGrandMapSearchPanelInputNodes ="),
        )
    ]
    scopes = jsx[
        jsx.index("const ensureGrandMapSearchPanelScopesLabelNodes ="):
        jsx.index(
            "const ensureGrandMapSearchPanelScopesListNodes =",
            jsx.index("const ensureGrandMapSearchPanelScopesLabelNodes ="),
        )
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapSearchPanelTemplate ="):
        jsx.index("const ensureGrandMapSearchPanelScopeRowNodes =", jsx.index("const cloneGrandMapSearchPanelTemplate ="))
    ]

    assert "syncGrandMapSurfaceStateSlots('search-panel-header', rootId, slotMap" in header
    assert "state_key: 'search_panel_header_state_node_id'" in header
    assert "'slot:search-panel-title': 'Search'" in header
    assert "'slot:search-panel-shortcut': 'CMD+K'" in header
    assert "syncGrandMapSurfaceStateSlots('search-panel-input', rootId, slotMap" in input_nodes
    assert "state_key: 'search_panel_input_state_node_id'" in input_nodes
    assert "'slot:search-query': (slots && slots.query) || ''" in input_nodes
    assert "'slot:search-placeholder': 'everything in studio...'" in input_nodes
    assert "syncGrandMapSurfaceStateSlots('search-panel-scopes-label', rootId, slotMap" in scopes
    assert "state_key: 'search_panel_scopes_label_state_node_id'" in scopes
    assert "'slot:search-scopes-label': 'SCOPES'" in scopes
    assert "const mappedSlotMap = putGrandMapMappedSlotMap(" in clone
    assert "syncGrandMapMappedSurfaceState(surfaceName, sid, rootId, mappedSlotMap)" in clone
    assert "syncGrandMapNodeRailFocusRelation(null, rootId)" in clone


def test_grand_map_share_panel_shell_emits_panel_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_share_export", "Share Export")],
            "wires": [],
        },
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Skill Library")],
            "wires": [],
        },
        {
            "key": "community",
            "title": "Community",
            "nodes": [_node("community_share_card", "Share to Community")],
            "wires": [],
        },
        {
            "key": "cloud",
            "title": "Cloud",
            "nodes": [_node("cloud_sync_client", "Desktop Sync Client")],
            "wires": [],
        },
        {
            "key": "users",
            "title": "Users",
            "nodes": [_node("users_account_chip", "Account chip")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("share-panel-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:share-panel-shell"
    assert payload["source_node_ids"] == [
        "sessions_share_export",
        "brain_skills",
        "community_share_card",
        "cloud_sync_client",
        "users_account_chip",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:share-panel-shell"]["data"]["cls"] == (
        "ah-share-panel-shell-node"
    )
    assert nodes["ui:grandmap:share-panel-shell"]["data"]["test_id"] == "rail-share"
    assert nodes["ui:grandmap:share-panel-shell"]["data"]["children"] == [
        "ui:grandmap:share-panel-shell-header",
        "ui:grandmap:share-panel-shell-description",
        "ui:grandmap:share-panel-shell-list",
    ]
    assert nodes["ui:grandmap:share-panel-shell-header"]["data"]["render_slot"] == (
        "slot:share-panel-shell-header"
    )
    assert nodes["ui:grandmap:share-panel-shell-description"]["data"]["render_slot"] == (
        "slot:share-panel-shell-description"
    )
    assert nodes["ui:grandmap:share-panel-shell-list"]["data"]["render_slot"] == (
        "slot:share-panel-shell-list"
    )


def test_grand_map_share_panel_inner_surfaces_emit_node_authority(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_share_export", "Share Export")],
            "wires": [],
        },
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Skill Library")],
            "wires": [],
        },
        {
            "key": "community",
            "title": "Community",
            "nodes": [_node("community_share_card", "Share to Community")],
            "wires": [],
        },
    ])

    header = grand_map_ui_surface("share-panel-header", grand_map_path=grand_map)
    row = grand_map_ui_surface("share-panel-row", grand_map_path=grand_map)
    list_surface = grand_map_ui_surface("share-panel-list", grand_map_path=grand_map)
    section = grand_map_ui_surface("share-panel-section-heading", grand_map_path=grand_map)
    empty = grand_map_ui_surface("share-panel-empty-state", grand_map_path=grand_map)
    loading = grand_map_ui_surface("share-panel-loading", grand_map_path=grand_map)

    assert header["ok"] is True
    assert header["root_id"] == "ui:grandmap:share-panel-header"
    header_nodes = {node["id"]: node for node in header["nodes"]}
    assert header_nodes["ui:grandmap:share-panel-add"]["data"]["tag"] == "button"
    assert header_nodes["ui:grandmap:share-panel-add"]["data"]["action"] == "share.canvas"
    assert header_nodes["ui:grandmap:share-panel-count"]["data"]["bind"] == (
        "slot:share-panel-count"
    )

    assert section["ok"] is True
    section_nodes = {node["id"]: node for node in section["nodes"]}
    assert section_nodes["ui:grandmap:share-panel-section-heading"]["data"]["bind"] == (
        "slot:share-section-title"
    )

    assert row["ok"] is True
    assert row["root_id"] == "ui:grandmap:share-panel-row"
    row_nodes = {node["id"]: node for node in row["nodes"]}
    assert row_nodes["ui:grandmap:share-panel-row"]["data"]["children"] == [
        "ui:grandmap:share-row-main",
        "ui:grandmap:share-row-actions",
        "ui:grandmap:share-row-note",
    ]
    assert row_nodes["ui:grandmap:share-row-copy-link"]["data"]["action"] == (
        "share.row.export"
    )
    assert row_nodes["ui:grandmap:share-row-copy-link"]["data"]["args"] == {
        "want": "link"
    }
    assert row_nodes["ui:grandmap:share-row-export-json"]["data"]["args"] == {
        "want": "json"
    }
    assert row_nodes["ui:grandmap:share-row-publish"]["data"]["action"] == (
        "share.row.publish"
    )
    assert row_nodes["ui:grandmap:share-row-publish"]["data"]["visible_when"] == {
        "bind": "slot:share-row-publish-visible",
        "values": ["true"],
    }
    assert row_nodes["ui:grandmap:share-row-copy-link"]["data"]["disabled_bind"] == (
        "slot:share-row-busy"
    )
    assert row_nodes["ui:grandmap:share-row-note"]["data"]["state_bind"] == (
        "slot:share-row-note-kind"
    )

    assert list_surface["ok"] is True
    assert list_surface["root_id"] == "ui:grandmap:share-panel-list"
    list_nodes = {node["id"]: node for node in list_surface["nodes"]}
    assert list_nodes["ui:grandmap:share-panel-list"]["data"]["cls"] == (
        "ah-share-panel-list-node ah-scroll"
    )
    assert list_nodes["ui:grandmap:share-panel-list"]["data"]["render_slot"] == (
        "slot:share-panel-list-content"
    )
    assert list_nodes["ui:grandmap:share-panel-list"]["data"]["test_id"] == (
        "rail-share-list"
    )

    empty_nodes = {node["id"]: node for node in empty["nodes"]}
    assert empty_nodes["ui:grandmap:share-panel-empty-state"]["data"]["visible_when"] == {
        "bind": "slot:share-empty-visible",
        "values": ["true"],
    }
    loading_nodes = {node["id"]: node for node in loading["nodes"]}
    assert loading_nodes["ui:grandmap:share-panel-loading"]["data"]["bind"] == (
        "slot:share-loading-message"
    )


def test_grand_map_workspace_shell_emits_layout_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [
                _node("canvas_lm_graph_state", "LM_GRAPH State Store"),
                _node("canvas_node_view", "NodeView Renderer"),
            ],
            "wires": [],
        },
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("workspace-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:workspace-shell"
    assert payload["source_node_ids"] == [
        "canvas_lm_graph_state",
        "canvas_node_view",
        "ui_node_card",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:workspace-shell"]["data"]["tag"] == "main"
    assert nodes["ui:grandmap:workspace-shell"]["data"]["cls"] == (
        "ah-workspace-shell-node"
    )
    assert nodes["ui:grandmap:workspace-shell"]["data"]["children"] == [
        "ui:grandmap:workspace-shell-header",
        "ui:grandmap:workspace-shell-canvas",
        "ui:grandmap:workspace-shell-rail",
    ]
    assert nodes["ui:grandmap:workspace-shell-header"]["data"]["render_slot"] == (
        "slot:workspace-shell-header"
    )
    assert nodes["ui:grandmap:workspace-shell-canvas"]["data"]["render_slot"] == (
        "slot:workspace-shell-canvas"
    )
    assert nodes["ui:grandmap:workspace-shell-rail"]["data"]["render_slot"] == (
        "slot:workspace-shell-rail"
    )


def test_grand_map_canvas_shell_emits_viewport_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [
                _node("canvas_lm_graph_state", "LM_GRAPH State Store"),
                _node("canvas_node_view", "NodeView Renderer"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-shell"
    assert payload["source_node_ids"] == ["canvas_lm_graph_state", "canvas_node_view"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:canvas-shell"]["data"]["tag"] == "div"
    assert nodes["ui:grandmap:canvas-shell"]["data"]["cls"] == "ah-canvas-shell-node"
    assert nodes["ui:grandmap:canvas-shell"]["data"]["children"] == [
        "ui:grandmap:canvas-shell-content",
    ]
    assert nodes["ui:grandmap:canvas-shell-content"]["data"]["render_slot"] == (
        "slot:canvas-shell-content"
    )


def test_grand_map_canvas_pan_layer_emits_transform_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [
                _node("canvas_lm_graph_state", "LM_GRAPH State Store"),
                _node("canvas_node_view", "NodeView Renderer"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-pan-layer", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-pan-layer"
    assert payload["source_node_ids"] == ["canvas_lm_graph_state", "canvas_node_view"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:canvas-pan-layer"]["data"]["tag"] == "div"
    assert nodes["ui:grandmap:canvas-pan-layer"]["data"]["cls"] == (
        "ah-canvas-pan-layer-node"
    )
    assert nodes["ui:grandmap:canvas-pan-layer"]["data"]["children"] == [
        "ui:grandmap:canvas-pan-layer-content",
    ]
    assert nodes["ui:grandmap:canvas-pan-layer-content"]["data"]["render_slot"] == (
        "slot:canvas-pan-layer-content"
    )


def test_grand_map_app_shell_emits_super_node_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("nl_ui_app_is_graph", "App UI Is The Graph"),
                _node("ui_design_tokens", "Design Tokens"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("app-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:app-shell"
    assert payload["source_node_ids"] == ["nl_ui_app_is_graph", "ui_design_tokens"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:app-shell"]["data"]
    assert root["tag"] == "div"
    assert root["cls"] == "ah-app-shell-node"
    assert root["state_bind"] == "slot:app-shell-mode"
    assert root["test_id"] == "app-shell"
    assert root["children"] == [
        "ui:grandmap:app-shell-rail",
        "ui:grandmap:app-shell-main",
        "ui:grandmap:app-shell-inspector",
        "ui:grandmap:app-shell-status",
        "ui:grandmap:app-shell-overlays",
    ]
    assert nodes["slot:app-shell-mode"]["data"]["value"] == "home"
    assert nodes["slot:app-shell-inspector-focus"]["data"]["value"] == ""
    assert nodes["param:ui:grandmap:app-shell:children"]["data"]["value"] == root["children"]
    assert nodes["ui:grandmap:app-shell-rail"]["data"]["render_slot"] == (
        "slot:app-shell-rail"
    )
    assert nodes["ui:grandmap:app-shell-main"]["data"]["render_slot"] == (
        "slot:app-shell-main"
    )
    assert nodes["ui:grandmap:app-shell-inspector"]["data"]["render_slot"] == (
        "slot:app-shell-inspector"
    )
    assert nodes["ui:grandmap:app-shell-inspector"]["data"]["state_bind"] == (
        "slot:app-shell-inspector-focus"
    )
    assert nodes["ui:grandmap:app-shell-status"]["data"]["render_slot"] == (
        "slot:app-shell-status"
    )
    assert nodes["ui:grandmap:app-shell-overlays"]["data"]["render_slot"] == (
        "slot:app-shell-overlays"
    )


def test_grand_map_home_shell_emits_home_layout_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_open_session", "Open Session"),
                _node("sessions_cloud_sync", "Cloud Session Sync"),
            ],
            "wires": [],
        },
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_design_tokens", "Design Tokens"),
                _node("ui_composer_bar", "Composer Bar"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:home-shell"
    assert payload["source_node_ids"] == [
        "sessions_threads_rail",
        "sessions_open_session",
        "sessions_cloud_sync",
        "ui_design_tokens",
        "ui_composer_bar",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:home-shell"]["data"]["tag"] == "main"
    assert nodes["ui:grandmap:home-shell"]["data"]["cls"] == "ah-home-shell-node ah-scroll"
    assert nodes["ui:grandmap:home-shell"]["data"]["children"] == [
        "ui:grandmap:home-shell-styles",
        "ui:grandmap:home-shell-top",
        "ui:grandmap:home-shell-plan",
        "ui:grandmap:home-shell-sessions",
        "ui:grandmap:home-shell-selection",
        "ui:grandmap:home-shell-content",
        "ui:grandmap:home-shell-composer",
    ]
    assert nodes["ui:grandmap:home-shell-styles"]["data"]["render_slot"] == (
        "slot:home-shell-styles"
    )
    assert nodes["ui:grandmap:home-shell-top"]["data"]["render_slot"] == (
        "slot:home-shell-top"
    )
    assert nodes["ui:grandmap:home-shell-sessions"]["data"]["render_slot"] == (
        "slot:home-shell-sessions"
    )
    assert nodes["ui:grandmap:home-shell-content"]["data"]["render_slot"] == (
        "slot:home-shell-content"
    )
    assert nodes["ui:grandmap:home-shell-composer"]["data"]["render_slot"] == (
        "slot:home-shell-composer"
    )


def test_grand_map_app_rail_emits_navigation_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_sidebar_rail", "Sidebar Rail"),
        _node("ui_modal_system", "Modal System"),
        _node("ui_command_palette", "Command Palette"),
    ])

    payload = grand_map_ui_surface("app-rail", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:app-rail"
    assert payload["source_node_ids"] == [
        "ui_sidebar_rail",
        "ui_command_palette",
        "ui_modal_system",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:rail-active"]["data"]["value"] == "home"
    assert nodes["ui:grandmap:rail-home"]["data"]["action"] == "rail.home.open"
    assert nodes["ui:grandmap:rail-home"]["data"]["active_bind"] == "slot:rail-active"
    assert nodes["ui:grandmap:rail-search"]["data"]["action"] == "rail.search.open"
    assert nodes["ui:grandmap:rail-share"]["data"]["action"] == "rail.share.open"
    assert nodes["ui:grandmap:rail-settings"]["data"]["action"] == "settings.open"
    assert nodes["ui:grandmap:rail-spacer"]["data"]["cls"] == "ah-rail-spacer-node"
    assert nodes["ui:grandmap:rail-home"]["data"]["children"] == [
        "ui:grandmap:rail-home-icon",
        "ui:grandmap:rail-home-label",
    ]
    assert nodes["ui:grandmap:rail-home-icon"]["data"]["children"] == [
        "ui:grandmap:rail-home-svg"
    ]
    assert nodes["ui:grandmap:rail-home-svg"]["data"]["tag"] == "svg"
    assert nodes["ui:grandmap:rail-home-svg"]["data"]["data_attrs"]["viewBox"] == "0 0 24 24"
    assert nodes["ui:grandmap:rail-home-path"]["data"]["tag"] == "path"
    assert nodes["ui:grandmap:rail-home-path"]["data"]["data_attrs"]["strokeLinecap"] == "round"
    assert nodes["ui:grandmap:rail-home-label"]["data"]["text"] == "home"
    assert nodes["ui:grandmap:rail-search-circle"]["data"]["tag"] == "circle"
    assert nodes["ui:grandmap:rail-share-path-b"]["data"]["tag"] == "path"
    assert nodes["ui:grandmap:rail-settings-path"]["data"]["tag"] == "path"


def test_sidebar_shell_surface_emits_icon_and_panel_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_sidebar_rail", "Sidebar Rail"),
    ])

    payload = grand_map_ui_surface("sidebar-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:sidebar-shell"
    assert payload["source_node_ids"] == ["ui_sidebar_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:sidebar-shell"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:sidebar-shell"]["data"]["cls"] == "ah-sidebar-shell-node"
    assert nodes["ui:grandmap:sidebar-shell"]["data"]["children"] == [
        "ui:grandmap:sidebar-icon-rail",
        "ui:grandmap:sidebar-active-panel",
    ]
    assert nodes["ui:grandmap:sidebar-icon-rail"]["data"]["render_slot"] == "slot:sidebar-icon-rail"
    assert nodes["ui:grandmap:sidebar-active-panel"]["data"]["render_slot"] == "slot:sidebar-active-panel"


def test_home_rail_shell_surface_emits_icon_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_sidebar_rail", "Sidebar Rail"),
    ])

    payload = grand_map_ui_surface("home-rail-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:home-rail-shell"
    assert payload["source_node_ids"] == ["ui_sidebar_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:home-rail-shell"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:home-rail-shell"]["data"]["cls"] == "ah-home-rail-shell-node"
    assert nodes["ui:grandmap:home-rail-shell"]["data"]["children"] == [
        "ui:grandmap:home-rail-icon-rail",
    ]
    assert nodes["ui:grandmap:home-rail-icon-rail"]["data"]["render_slot"] == "slot:home-rail-icon-rail"


def test_grand_map_status_strip_emits_runtime_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_sidebar_rail", "Sidebar Rail"),
        _node("ui_command_palette", "Command Palette"),
        _node("ui_account_chip", "Account Chip"),
        _node("ui_composer_bar", "Composer Bar"),
    ])

    payload = grand_map_ui_surface("status-strip", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:status-strip"

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:status-runtime"]["data"]["value"] == "server"
    assert nodes["slot:status-session"]["data"]["value"] == ""
    assert nodes["slot:status-health"]["data"]["value"] == "healthy"
    assert nodes["slot:status-version"]["data"]["value"] == "ArchHub"
    assert nodes["ui:grandmap:status-runtime"]["data"]["action"] == "settings.open"
    assert nodes["ui:grandmap:status-memory"]["data"]["action"] == "memory.open"
    assert nodes["ui:grandmap:status-health"]["data"]["action"] == "graph.health.open"
    assert nodes["ui:grandmap:status-settings"]["data"]["action"] == "settings.open"
    assert nodes["ui:grandmap:status-version"]["data"]["tag"] == "button"
    assert nodes["ui:grandmap:status-version"]["data"]["action"] == "application.focus"
    assert nodes["ui:grandmap:status-version"]["data"]["args"] == {"node_id": "app:archhub"}
    assert nodes["ui:grandmap:status-strip"]["data"]["children"] == [
        "ui:grandmap:status-runtime",
        "ui:grandmap:status-sep-a",
        "ui:grandmap:status-session",
        "ui:grandmap:status-model",
        "ui:grandmap:status-sep-b",
        "ui:grandmap:status-memory",
        "ui:grandmap:status-health",
        "ui:grandmap:status-spacer",
        "ui:grandmap:status-settings",
        "ui:grandmap:status-sep-c",
        "ui:grandmap:status-version",
    ]


def test_update_notifier_surface_emits_version_slots_and_relaunch_action(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
        _node("ui_design_tokens", "Design Tokens"),
    ])

    payload = grand_map_ui_surface("update-notifier", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:update-notifier"
    assert payload["source_node_ids"] == ["ui_modal_system", "ui_design_tokens"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:update-notifier"]
    assert root["data"]["test_id"] == "update-banner"
    assert root["data"]["children"] == [
        "ui:grandmap:update-icon",
        "ui:grandmap:update-copy",
        "ui:grandmap:update-relaunch",
    ]
    assert nodes["slot:update-current"]["data"]["value"] == "?"
    assert nodes["slot:update-latest"]["data"]["value"] == "latest"
    assert nodes["slot:update-busy"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:update-current"]["data"]["bind"] == "slot:update-current"
    assert nodes["ui:grandmap:update-latest"]["data"]["bind"] == "slot:update-latest"
    assert nodes["ui:grandmap:update-relaunch"]["data"]["action"] == "update.relaunch"
    assert nodes["ui:grandmap:update-relaunch"]["data"]["disabled_bind"] == "slot:update-busy"
    assert nodes["ui:grandmap:update-relaunch"]["data"]["test_id"] == "update-relaunch"


def test_global_toast_surface_emits_message_and_state_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("global-toast", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:global-toast"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:global-toast"]["data"]
    assert root["test_id"] == "global-toast"
    assert root["bind"] == "slot:global-toast-message"
    assert root["state_bind"] == "slot:global-toast-kind"
    assert nodes["slot:global-toast-message"]["data"]["value"] == ""
    assert nodes["slot:global-toast-kind"]["data"]["value"] == "info"


def test_canvas_toast_surface_emits_no_pan_message_and_state_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("canvas-toast", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-toast"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-toast"]["data"]
    assert root["test_id"] == "canvas-toast"
    assert root["bind"] == "slot:canvas-toast-message"
    assert root["state_bind"] == "slot:canvas-toast-kind"
    assert root["data_attrs"] == {"data-no-pan": "true"}
    assert nodes["slot:canvas-toast-message"]["data"]["value"] == ""
    assert nodes["slot:canvas-toast-kind"]["data"]["value"] == "info"


def test_canvas_group_dialog_surface_emits_parametric_form_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("canvas-group-dialog", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-group-dialog"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-group-dialog"]["data"]
    assert root["action"] == "canvas.group.cancel"
    assert root["children"] == ["ui:grandmap:group-dialog-panel"]
    panel = nodes["ui:grandmap:group-dialog-panel"]["data"]
    assert panel["action"] == "canvas.group.noop"
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["data-no-pan"] == "true"
    assert nodes["slot:group-title"]["data"]["value"] == "Group"
    assert nodes["slot:group-style"]["data"]["value"] == "transform"
    assert nodes["ui:grandmap:group-title-input"]["data"]["tag"] == "input"
    assert nodes["ui:grandmap:group-title-input"]["data"]["bind"] == "slot:group-title"
    assert nodes["ui:grandmap:group-title-input"]["data"]["action"] == "canvas.group.title.update"
    assert nodes["ui:grandmap:group-title-input"]["data"]["submit_action"] == "canvas.group.create"
    style_nodes = [
        node_id
        for node_id in nodes
        if node_id.startswith("ui:grandmap:group-style-")
        and node_id not in {"ui:grandmap:group-style-field", "ui:grandmap:group-style-label", "ui:grandmap:group-style-list"}
    ]
    assert len(style_nodes) == 6
    assert nodes["ui:grandmap:group-style-transform"]["data"]["active_bind"] == "slot:group-style"
    assert nodes["ui:grandmap:group-style-transform"]["data"]["action"] == "canvas.group.style.set"
    assert nodes["ui:grandmap:group-cancel"]["data"]["action"] == "canvas.group.cancel"
    assert nodes["ui:grandmap:group-create"]["data"]["action"] == "canvas.group.create"


def test_canvas_save_skill_dialog_surface_emits_parametric_form_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("canvas-save-skill-dialog", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-save-skill-dialog"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-save-skill-dialog"]["data"]
    assert root["action"] == "canvas.save-skill.cancel"
    assert root["children"] == ["ui:grandmap:save-skill-panel"]
    panel = nodes["ui:grandmap:save-skill-panel"]["data"]
    assert panel["action"] == "canvas.save-skill.noop"
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["data-no-pan"] == "true"
    assert nodes["slot:save-skill-name"]["data"]["value"] == "untitled skill"
    assert nodes["slot:save-skill-mode"]["data"]["value"] == "shared"
    assert nodes["ui:grandmap:save-skill-name-input"]["data"]["bind"] == "slot:save-skill-name"
    assert nodes["ui:grandmap:save-skill-name-input"]["data"]["action"] == "canvas.save-skill.name.update"
    assert nodes["ui:grandmap:save-skill-name-input"]["data"]["submit_action"] == "canvas.save-skill.save"
    assert nodes["ui:grandmap:save-skill-description-input"]["data"]["tag"] == "textarea"
    assert nodes["ui:grandmap:save-skill-description-input"]["data"]["action"] == "canvas.save-skill.description.update"
    assert nodes["ui:grandmap:save-skill-category-input"]["data"]["placeholder"] == "e.g. revit, takeoff, qa"
    assert nodes["ui:grandmap:save-skill-mode-shared"]["data"]["active_bind"] == "slot:save-skill-mode"
    assert nodes["ui:grandmap:save-skill-mode-shared"]["data"]["action"] == "canvas.save-skill.mode.set"
    assert nodes["ui:grandmap:save-skill-mode-private"]["data"]["args"] == {"mode": "private"}
    assert nodes["ui:grandmap:save-skill-cancel"]["data"]["action"] == "canvas.save-skill.cancel"
    assert nodes["ui:grandmap:save-skill-save"]["data"]["action"] == "canvas.save-skill.save"


def test_create_node_modal_surface_emits_parametric_form_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("create-node-modal", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:create-node-modal"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:create-node-modal"]["data"]
    assert root["action"] == "create-node.cancel"
    assert root["children"] == ["ui:grandmap:create-node-panel"]
    panel = nodes["ui:grandmap:create-node-panel"]["data"]
    assert panel["action"] == "create-node.noop"
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["data-no-pan"] == "true"
    assert nodes["slot:create-node-category"]["data"]["value"] == "filter"
    assert nodes["ui:grandmap:create-node-type-input"]["data"]["bind"] == "slot:create-node-type"
    assert nodes["ui:grandmap:create-node-type-input"]["data"]["action"] == "create-node.type.update"
    assert nodes["ui:grandmap:create-node-type-input"]["data"]["submit_action"] == "create-node.create"
    assert nodes["ui:grandmap:create-node-category-input"]["data"]["placeholder"] == "filter"
    assert nodes["ui:grandmap:create-node-inputs-input"]["data"]["action"] == "create-node.inputs.update"
    assert nodes["ui:grandmap:create-node-outputs-input"]["data"]["action"] == "create-node.outputs.update"
    assert nodes["ui:grandmap:create-node-cancel"]["data"]["action"] == "create-node.cancel"
    assert nodes["ui:grandmap:create-node-create"]["data"]["action"] == "create-node.create"


def test_ai_node_modal_surface_emits_phase_controlled_node_form(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("ai-node-modal", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:ai-node-modal"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:ai-node-modal"]["data"]
    assert root["action"] == "ai-node.close"
    assert root["children"] == ["ui:grandmap:ai-node-panel"]
    panel = nodes["ui:grandmap:ai-node-panel"]["data"]
    assert panel["action"] == "ai-node.noop"
    assert panel["data_attrs"]["data-no-pan"] == "true"
    assert panel["data_attrs"]["aria-labelledby"] == "lm-ai-node-modal-title"
    assert nodes["slot:ai-node-phase"]["data"]["value"] == "idle"
    assert nodes["slot:ai-node-can-draft"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:ai-node-desc-input"]["data"]["tag"] == "textarea"
    assert nodes["ui:grandmap:ai-node-desc-input"]["data"]["bind"] == "slot:ai-node-desc"
    assert nodes["ui:grandmap:ai-node-desc-input"]["data"]["action"] == "ai-node.desc.update"
    assert nodes["ui:grandmap:ai-node-draft"]["data"]["action"] == "ai-node.generate"
    assert nodes["ui:grandmap:ai-node-draft"]["data"]["disabled_bind"] == "slot:ai-node-can-draft"
    assert nodes["ui:grandmap:ai-node-example-0"]["data"]["action"] == "ai-node.example.pick"
    assert nodes["ui:grandmap:ai-node-working"]["data"]["visible_when"] == {
        "bind": "slot:ai-node-phase",
        "value": "working",
    }
    assert nodes["ui:grandmap:ai-node-done"]["data"]["visible_when"]["value"] == "done"
    assert nodes["ui:grandmap:ai-node-error"]["data"]["visible_when"]["value"] == "error"
    assert nodes["ui:grandmap:ai-node-add"]["data"]["action"] == "ai-node.add"
    assert nodes["ui:grandmap:ai-node-create-another"]["data"]["action"] == "ai-node.reset"


def test_first_run_profile_surface_emits_profile_form_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_modal_system", "Modal / Panel System"),
    ])

    payload = grand_map_ui_surface("first-run-profile", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:first-run-profile"
    assert payload["source_node_ids"] == ["ui_modal_system"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    panel = nodes["ui:grandmap:first-run-panel"]["data"]
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["data-no-pan"] == "true"
    assert nodes["ui:grandmap:first-run-wordmark"]["data"]["render_slot"] == "slot:first-run-wordmark"
    assert nodes["ui:grandmap:first-run-firm-input"]["data"]["bind"] == "slot:first-run-firm"
    assert nodes["ui:grandmap:first-run-firm-input"]["data"]["action"] == "first-run.firm.update"
    assert nodes["ui:grandmap:first-run-role-select"]["data"]["tag"] == "select"
    assert nodes["ui:grandmap:first-run-role-select"]["data"]["action"] == "first-run.role.update"
    assert nodes["ui:grandmap:first-run-discipline-select"]["data"]["action"] == "first-run.discipline.update"
    assert nodes["ui:grandmap:first-run-role-option-0"]["data"]["option_value"] == ""
    assert nodes["ui:grandmap:first-run-role-option-1"]["data"]["option_value"] == "Architect"
    assert nodes["ui:grandmap:first-run-discipline-option-1"]["data"]["option_value"] == "Architecture"
    assert nodes["ui:grandmap:first-run-skip"]["data"]["action"] == "first-run.skip"
    assert nodes["ui:grandmap:first-run-save"]["data"]["action"] == "first-run.save"
    assert nodes["ui:grandmap:first-run-save"]["data"]["disabled_bind"] == "slot:first-run-save-disabled"


def test_modal_actions_route_through_handler_and_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    group_dialog = jsx[
        jsx.index("const GroupDialog ="):
        jsx.index("const SaveSkillDialog =", jsx.index("const GroupDialog ="))
    ]
    save_skill = jsx[
        jsx.index("const SaveSkillDialog ="):
        jsx.index("const LM_GRAPH =", jsx.index("const SaveSkillDialog ="))
    ]
    create_node = jsx[
        jsx.index("const CreateNodeModal ="):
        jsx.index("const modalInput =", jsx.index("const CreateNodeModal ="))
    ]
    ai_node = jsx[
        jsx.index("const AINodeModal ="):
        jsx.index("const FirstRunProfile =", jsx.index("const AINodeModal ="))
    ]
    first_run = jsx[
        jsx.index("const FirstRunProfile ="):
        jsx.index("const WirePromotePalette =", jsx.index("const FirstRunProfile ="))
    ]
    wire_promote = jsx[
        jsx.index("const WirePromotePalette ="):
        jsx.index("const BrokenWireRow =", jsx.index("const WirePromotePalette ="))
    ]
    broken_wire = jsx[
        jsx.index("const BrokenWireDialog ="):
        jsx.index("const SELF_HEAL_KINDS =", jsx.index("const BrokenWireDialog ="))
    ]

    assert "registerUiHostCapability('canvas.group.title.update'" in group_dialog
    assert "registerUiHostCapability('canvas.group.style.set'" in group_dialog
    assert "registerUiHostCapability('canvas.group.cancel'" in group_dialog
    assert "registerUiHostCapability('canvas.group.create'" in group_dialog

    assert "registerUiHostCapability('canvas.save-skill.name.update'" in save_skill
    assert "registerUiHostCapability('canvas.save-skill.mode.set'" in save_skill
    assert "registerUiHostCapability('canvas.save-skill.cancel'" in save_skill
    assert "registerUiHostCapability('canvas.save-skill.save'" in save_skill

    assert "registerUiHostCapability('create-node.type.update'" in create_node
    assert "registerUiHostCapability('create-node.cancel'" in create_node
    assert "registerUiHostCapability('create-node.create'" in create_node

    assert "registerUiHostCapability('ai-node.desc.update'" in ai_node
    assert "registerUiHostCapability('ai-node.generate'" in ai_node
    assert "registerUiHostCapability('ai-node.add'" in ai_node

    assert "registerUiHostCapability('first-run.firm.update'" in first_run
    assert "registerUiHostCapability('first-run.skip'" in first_run
    assert "registerUiHostCapability('first-run.save'" in first_run

    assert "registerUiHostCapability('wire-promote.close'" in wire_promote
    assert "registerUiHostCapability('wire-promote.query.update'" in wire_promote
    assert "registerUiHostCapability('wire-promote.result.pick'" in wire_promote

    assert "registerUiHostCapability('broken-wire.close'" in broken_wire
    assert "registerUiHostCapability('broken-wire.insert-adapter'" in broken_wire
    assert "registerUiHostCapability('broken-wire.delete-anyway'" in broken_wire


def test_sidebar_shell_hydrates_sidebar_container_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    sidebar = jsx[
        jsx.index("const SidebarInner ="):
        jsx.index("const Sidebar =", jsx.index("const SidebarInner ="))
    ]

    assert "const SidebarShellSurface = ({ iconRail, activePanel }) =>" in jsx
    assert "const ensureGrandMapSidebarShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'sidebar-shell'" in jsx
    assert "<SidebarShellSurface" in sidebar
    assert "slot:sidebar-icon-rail" in jsx
    assert "slot:sidebar-active-panel" in jsx
    assert "<aside style={{" not in sidebar


def test_home_rail_shell_hydrates_home_branch_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    studio_root = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SidebarShellSurface =", jsx.index("const StudioLM ="))
    ]

    assert "const HomeRailShellSurface = ({ iconRail }) =>" in jsx
    assert "const ensureGrandMapHomeRailShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'home-rail-shell'" in jsx
    assert "<HomeRailShellSurface" in studio_root
    assert "slot:home-rail-icon-rail" in jsx
    assert "<aside style={{" not in studio_root


def test_app_shell_hydrates_root_frame_as_super_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    studio_root = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SField = ({ label }) =>", jsx.index("const StudioLM ="))
    ]
    app_shell = jsx[
        jsx.index("const AppShellSurface ="):
        jsx.index("const HomeRailShellSurface =", jsx.index("const AppShellSurface ="))
    ]

    assert "const AppShellSurface = ({ mode, session, focusId, rail, main, status, overlays, inspector }) =>" in jsx
    assert "const seedGrandMapAppShellFallbackNodes = (mode, focusId) =>" in jsx
    assert "const seededRootId = seedGrandMapAppShellFallbackNodes(mode, focusId);" in jsx
    assert "const ensureGrandMapAppShellNodes = (mode, focusId) =>" in jsx
    assert "const ARCHHUB_APPLICATION_SUPER_NODE_ID = 'app:archhub';" in jsx
    assert "const ensureGrandMapApplicationSuperNode = ({ mode, session, focusId } = {}) =>" in jsx
    assert "const focusGrandMapApplicationSuperNode = () =>" in jsx
    assert "detail: { node_id: ARCHHUB_APPLICATION_SUPER_NODE_ID }" in jsx
    assert "const appRelationWireId = (targetId, role) =>" in jsx
    assert "const appRelationWireNodeId = (wireId) =>" in jsx
    assert "const appRelationEndpointWireId = (wireId, endpoint) =>" in jsx
    assert "const _uiPortParamKey = (direction, portId) =>" in jsx
    assert "const ensureUiNodePortParamNode = (graph, ownerId, port, direction) =>" in jsx
    assert "const livePortValue = (existingValueParam" in jsx
    assert "materializeGrandMapParamNode(ownerId, key, livePortValue);" in jsx
    assert "window.ahSetUiNodeParam(ownerId, key, livePortValue);" not in jsx
    assert "const upsertAppRelationWireNode = (graph, wire) =>" in jsx
    assert "ensureGrandMapApplicationSuperNode({ mode, session, focusId });" in app_shell
    assert "const hasInspector = !session && !!inspector;" in app_shell
    assert "gridTemplateColumns: session ? '292px 1fr' : (hasInspector ? '56px minmax(0, 1fr) minmax(280px, 320px)' : '56px 1fr')" in app_shell
    assert "id: ARCHHUB_APPLICATION_SUPER_NODE_ID" in jsx
    assert "kind: 'group'" in jsx
    assert "role: 'application'" in jsx
    assert "surface_nodes: uniqueSurfaceNodes" in jsx
    assert "const isApplicationSurfaceTarget = (targetId) =>" in jsx
    assert "if (!id || id.indexOf('param:') === 0) return false;" in jsx
    assert "if (['parameter', 'wire', 'wire_layer', 'wire_runtime', 'selected_wire_path_wire'].indexOf(targetData.role) >= 0) return false;" in jsx
    assert "capabilities.some(capability => ['parameter', 'port', 'relation', 'relation-stage'].indexOf(capability) >= 0)" in jsx
    assert ".filter(isApplicationSurfaceTarget)" in jsx
    assert "group_nodes: uniqueGroupNodes" in jsx
    assert "relation_wire_ids: Array.from(liveRelationWireIds)" in jsx
    assert "relation_wire_node_ids: Array.from(liveRelationWireNodeIds)" in jsx
    assert "relation_wire_layer_node_ids: Array.from(liveRelationWireLayerNodeIds)" in jsx
    assert "relation_endpoint_wire_ids: Array.from(liveRelationEndpointWireIds)" in jsx
    assert "relation_port_node_ids: Array.from(liveRelationPortNodeIds)" in jsx
    assert "const upsertAppRelationWire = (targetId, role, options = {}) =>" in jsx
    assert "if (String(targetId).indexOf('param:') === 0) return;" in jsx
    assert "const sourcePortNodeId = ensureUiNodePortParamNode(g, ARCHHUB_APPLICATION_SUPER_NODE_ID" in jsx
    assert "const targetPortNodeId = ensureUiNodePortParamNode(g, targetId" in jsx
    assert "from: { node: sourcePortNodeId || ARCHHUB_APPLICATION_SUPER_NODE_ID, port: 'value' }" in jsx
    assert "to: { node: targetPortNodeId || targetId, port: targetPortId }" in jsx
    assert "const relationSurfaceNodes = uniqueSurfaceNodes.filter(isApplicationSurfaceTarget);" in jsx
    assert "relationSurfaceNodes.forEach(targetId => upsertAppRelationWire(targetId, 'surface', {" in jsx
    assert "source_boundary_port: 'surface_output'" in jsx
    assert "const wireNodeId = upsertAppRelationWireNode(g, relationPayload);" in jsx
    assert "const existingRelationIndex = _uiIndexOf(g.wires, id);" in jsx
    assert "else g.wires.push(relationPayload);" in jsx
    assert "liveRelationWireIds.has(w.id)" in jsx
    assert "liveRelationWireNodeIds.add(wireNodeId);" in jsx
    assert "to: { node: wireNodeId, port: 'from' }" in jsx
    assert "from: { node: wireNodeId, port: 'to' }" in jsx
    assert "liveRelationEndpointWireIds.add(payload.id);" in jsx
    assert "const duplicateApplicationStateParamKeys = Object.keys(boundaryPortValues);" in jsx
    assert "duplicateApplicationStateParamNodeIds" in jsx
    assert "liveNode.data.param_nodes = liveNode.data.param_nodes.filter(id => !duplicateApplicationStateParamNodeIds.has(id));" in jsx
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'mode', currentMode);" not in jsx
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'session_id', sessionId);" not in jsx
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'focus_id', focusNodeId);" not in jsx
    assert "const syncAppParamNode = (key, value) =>" in jsx
    assert "Object.keys(boundaryPortValues).forEach(key => syncAppParamNode(key, boundaryPortValues[key]));" in jsx
    assert "syncAppParamNode('surface_count', relationSurfaceNodes.length);" not in jsx
    assert "get_grand_map_ui_surface', 'app-shell'" in jsx
    assert "if (!window.archhub || typeof window.archhub.get_grand_map_ui_surface !== 'function') {" in jsx
    assert "test_id: 'app-shell'" in jsx
    assert "<AppShellSurface" in studio_root
    assert "mode={session ? 'workspace' : 'home'}" in studio_root
    assert "rail={appRailSlot}" in studio_root
    assert "focusId={focusId}" in studio_root
    assert "main={appMainSlot}" in studio_root
    assert "status={appStatusSlot}" in studio_root
    assert "overlays={appOverlaySlot}" in studio_root
    assert "inspector={homeInspectorSlot}" in studio_root
    assert "const focusNodeForShell = React.useMemo(" in studio_root
    assert "const homeInspectorSlot = !session && focusNodeForShell" in studio_root
    assert "<NodeRail node={focusNodeForShell} bumpGraph={bumpGraph} setFocusId={setFocusId}/>" in studio_root
    assert "slot:app-shell-rail" in app_shell
    assert "slot:app-shell-main" in app_shell
    assert "slot:app-shell-inspector" in app_shell
    assert "slot:app-shell-status" in app_shell
    assert "slot:app-shell-overlays" in app_shell
    assert "slot:app-shell-mode" in jsx
    assert "slot:app-shell-inspector-focus" in jsx
    assert "syncGrandMapSurfaceStateSlots('app-shell', rootId, slotMap" in jsx
    assert "state_key: 'app_shell_state_node_id'" in jsx
    assert "return (\n    <div style={{" not in studio_root
    assert "gridTemplateColumns: session ? '292px 1fr' : '56px 1fr'" not in studio_root


def test_status_version_focuses_application_super_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    server_strip = jsx[
        jsx.index("const ServerStrip ="):
        jsx.index("const ServerStripMemo =")
    ]

    assert "registerUiHostCapability('application.focus'" in server_strip
    assert "registerUiHostCapability('graph.health.open'" in server_strip
    assert server_strip.count("focusGrandMapApplicationSuperNode();") >= 2
    graph_health_branch = server_strip[
        server_strip.index("registerUiHostCapability('graph.health.open'"):
        server_strip.index("registerUiHostCapability('application.focus'")
    ]
    assert "focusGrandMapApplicationSuperNode();" in graph_health_branch
    assert "<StripItem onClick={focusGrandMapApplicationSuperNode}>{ver ? `v${ver}` : 'ArchHub'}</StripItem>" in server_strip


def test_ui_behavior_listener_migration_is_shrink_only_and_wire_values_stay_open():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")

    # One listener is the generic graph interpreter. Every other occurrence is
    # migration debt and this exact count may only be reduced.
    assert jsx.count("window.addEventListener('lm-ui-node-action'") == 1
    assert "function executeUiActionBehaviorGraph(detail)" in jsx
    assert "resolveUiHostOperationAuthority(g, detail || {})" in jsx
    assert "spec.closedOptions === true" in jsx
    generic_specs = jsx[
        jsx.index("const GENERIC_WIRE_LAYER_SPECS = ["):
        jsx.index("const wireLayerSpecsForContext =", jsx.index("const GENERIC_WIRE_LAYER_SPECS = ["))
    ]
    assert "closedOptions:true" not in generic_specs


def test_application_super_node_stays_out_of_workflow_canvas():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    visible_filter = jsx[
        jsx.index("const isVisibleWorkflowCanvasNode ="):
        jsx.index("const wireEndpointNodeId =", jsx.index("const isVisibleWorkflowCanvasNode ="))
    ]

    assert "if (data.role === 'application') return false;" in visible_filter
    assert "data.role === 'wire'" in visible_filter


def test_application_super_node_relationships_are_wires_not_only_arrays():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]

    assert "const liveRelationWireIds = new Set();" in super_node
    assert "const liveRelationPortNodeIds = new Set();" in super_node
    assert "data: {" in super_node
    assert "role: 'relation'" in super_node
    assert "relation: role" in super_node
    assert "owner: ARCHHUB_APPLICATION_SUPER_NODE_ID" in super_node
    assert "target: targetId" in super_node
    assert "source_owner: ARCHHUB_APPLICATION_SUPER_NODE_ID" in super_node
    assert "from_port_node: sourcePortNodeId || ''" in super_node
    assert "to_port_node: targetPortNodeId || ''" in super_node
    assert "const valueType = existingWireData.value_type || options.value_type || 'ui';" in super_node
    assert "const schemaRef = existingWireData.schema_ref || options.schema_ref || 'archhub.ui.element';" in super_node
    assert "const srcField = existingWireData.src_field || options.src_field || '';" in super_node
    assert "const dstField = existingWireData.dst_field || options.dst_field || '';" in super_node
    assert "const gatePolicy = existingWireData.gate_policy || options.gate_policy || 'allow-if-target-exists';" in super_node
    assert "value_type: valueType" in super_node
    assert "schema_ref: schemaRef" in super_node
    assert "src_field: srcField" in super_node
    assert "dst_field: dstField" in super_node
    assert "gate_policy: gatePolicy" in super_node
    assert "const encryption = existingWireData.encryption || options.encryption || 'none';" in super_node
    assert "encryption" in super_node
    assert "const existingRelationIndex = _uiIndexOf(g.wires, id);" in super_node
    assert "if (existingRelationIndex >= 0) g.wires[existingRelationIndex] = Object.assign({}, g.wires[existingRelationIndex], relationPayload);" in super_node
    assert "else g.wires.push(relationPayload);" in super_node
    assert "relationPayload.data = Object.assign({}, relationPayload.data || {}, { relation_node: wireNodeId });" in super_node
    assert "id: appRelationEndpointWireId(id, 'from')" in super_node
    assert "id: appRelationEndpointWireId(id, 'to')" in super_node
    assert "g.wires = (g.wires || []).filter" in super_node
    assert "liveRelationWireIds.has(w.id)" in super_node


def test_application_boundary_ports_are_first_class_parameter_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    port_helper = jsx[
        jsx.index("const uiNodePortOwnerWireId ="):
        jsx.index("const upsertAppRelationWireNode =", jsx.index("const uiNodePortOwnerWireId ="))
    ]
    super_node = jsx[
        jsx.index("const ARCHHUB_APPLICATION_BOUNDARY_PORT_SPECS ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]

    assert "const ARCHHUB_APPLICATION_BOUNDARY_PORT_SPECS = [" in super_node
    assert "id: 'runtime_http_port'" in super_node
    assert "endpoint_kind: 'pc-port'" in super_node
    assert "id: 'status_runtime_label'" in super_node
    assert "id: 'model_status'" in super_node
    assert "id: 'memory_state'" in super_node
    assert "id: 'application_version'" in super_node
    assert "id: 'active_sidebar_panel'" in super_node
    assert "id: 'rail_drawer_panel'" in super_node
    assert "id: 'active_app_modals'" in super_node
    assert "id: 'active_app_modal_primary'" in super_node
    assert "id: 'settings_open'" in super_node
    assert "presentation: 'status-strip'" in super_node
    assert "presentation: 'rail-state'" in super_node
    assert "presentation: 'modal-overlay'" in super_node
    assert "id: 'surface_output'" in super_node
    assert "exposure_scope: 'website'" in super_node
    assert "const applicationBoundaryInputPorts = ARCHHUB_APPLICATION_BOUNDARY_PORT_SPECS" in super_node
    assert "const applicationBoundaryOutputPorts = ARCHHUB_APPLICATION_BOUNDARY_PORT_SPECS" in super_node
    assert "node.ins = applicationBoundaryInputPorts;" in super_node
    assert "...applicationBoundaryOutputPorts" in super_node
    assert "const liveApplicationBoundaryPortNodeIds = new Set();" in super_node
    assert "const applicationBoundaryPortNodeIds = {};" in super_node
    assert "ensureUiNodePortParamNode(g, ARCHHUB_APPLICATION_SUPER_NODE_ID, Object.assign({}, spec" in super_node
    assert "relation_wire_family: 'application_boundary'" in super_node
    assert "application_boundary_port_node_ids: Array.from(liveApplicationBoundaryPortNodeIds)" in super_node
    assert "applicationBoundaryPortNodeIds[spec.id] = portNodeId;" in super_node

    assert "const uiNodePortOwnerWireId = (ownerId, portDirection, portId) =>" in port_helper
    assert "const schemaRef = String(portData.schema_ref || ('archhub.port.' + portType));" in port_helper
    assert "const gatePolicy = String(portData.gate_policy || 'allow-if-owner-exists');" in port_helper
    assert "const codec = String(portData.codec || 'none');" in port_helper
    assert "const encryption = String(portData.encryption || 'none');" in port_helper
    assert "const behavior = String(portData.behavior || 'wire-endpoint');" in port_helper
    assert "const exposureScope = String(portData.exposure_scope || portData.scope || 'internal');" in port_helper
    assert "schema_ref: schemaRef" in port_helper
    assert "gate_policy: gatePolicy" in port_helper
    assert "encryption" in port_helper
    assert "setLocalParam('schema_ref', 'schema ref', 'text', schemaRef);" in port_helper
    assert "setLocalParam('encryption', 'encryption', 'text', encryption);" in port_helper
    assert "['value', livePortValue]" in port_helper
    assert "['gate_policy', gatePolicy]" in port_helper
    assert "['codec', codec]" in port_helper
    assert "['encryption', encryption]" in port_helper
    assert "['behavior', behavior]" in port_helper
    assert "['presentation', presentation]" in port_helper
    assert "const nestedPortParams = [" in port_helper
    assert "if (materializeNestedParams)" in port_helper
    assert "nestedPortParams.forEach(([paramKey, paramValue]) => materializeGrandMapParamNode(paramNodeId, paramKey, paramValue));" in port_helper
    assert "window.ahSetUiNodeParam(paramNodeId, 'encryption', encryption);" not in port_helper
    assert "role: 'port_owner_link'" in port_helper
    assert "relation: 'owns_port'" in port_helper
    assert "{ id: portId, label: portLabel, t: portType }" in port_helper


def test_application_surface_and_focus_relations_use_boundary_ports():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]

    assert "const sourceBoundaryPortId = options.source_boundary_port || '';" in super_node
    assert "const sourceBoundaryPortNodeId = sourceBoundaryPortId ? (applicationBoundaryPortNodeIds[sourceBoundaryPortId] || '') : '';" in super_node
    assert "const sourcePortNodeId = sourceBoundaryPortNodeId || ensureUiNodePortParamNode" in super_node
    assert "source_boundary_port: sourceBoundaryPortId" in super_node
    assert "relationSurfaceNodes.forEach(targetId => upsertAppRelationWire(targetId, 'surface', {" in super_node
    assert "source_boundary_port: 'surface_output'" in super_node
    assert "schema_ref: 'archhub.ui.surface'" in super_node
    assert "behavior: 'render'" in super_node
    assert "presentation: 'surface-relation'" in super_node
    assert "upsertAppRelationWire(focusNodeId, 'active_focus', {" in super_node
    assert "source_boundary_port: 'active_focus'" in super_node
    assert "const staleRelationPortNodeIds = new Set();" in super_node
    assert "data.relation_wire_family === 'app_relation'" in super_node
    assert "data.owner === ARCHHUB_APPLICATION_SUPER_NODE_ID" in super_node
    assert "staleRelationPortNodeIds.add(n.id);" in super_node
    assert "data.role === 'port_owner_link' && stale.has(data.port_node)" in super_node


def test_status_strip_fields_are_application_boundary_wired():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]
    status_strip = jsx[
        jsx.index("const ensureGrandMapStatusStripNodes ="):
        jsx.index("function ensureHomeTopUiNodes", jsx.index("const ensureGrandMapStatusStripNodes ="))
    ]

    assert "const statusSlotValue = (slotId, fallback) =>" in super_node
    assert "status_runtime_label: statusSlotValue('slot:status-runtime', '')" in super_node
    assert "model_status: statusSlotValue('slot:status-model', '')" in super_node
    assert "memory_state: statusSlotValue('slot:status-memory', 'memory')" in super_node
    assert "graph_health_state: statusSlotValue('slot:status-health', 'healthy')" in super_node
    assert "application_version: statusSlotValue('slot:status-version', 'ArchHub')" in super_node
    assert "'ui:grandmap:status-strip'" in super_node
    assert "'ui:grandmap:status-runtime'" in super_node
    assert "'ui:grandmap:status-session'" in super_node
    assert "'ui:grandmap:status-model'" in super_node
    assert "'ui:grandmap:status-memory'" in super_node
    assert "'ui:grandmap:status-health'" in super_node
    assert "'ui:grandmap:status-settings'" in super_node
    assert "'ui:grandmap:status-version'" in super_node
    assert "Object.keys(boundaryPortValues).forEach(key => syncAppParamNode(key, boundaryPortValues[key]));" in super_node
    assert "syncAppParamNode('status_runtime_label', boundaryPortValues.status_runtime_label);" not in super_node
    assert "const statusBoundaryTargets = [" in super_node
    assert "target: 'ui:grandmap:status-runtime'" in super_node
    assert "source_boundary_port: 'status_runtime_label'" in super_node
    assert "target: 'ui:grandmap:status-session'" in super_node
    assert "source_boundary_port: 'active_session'" in super_node
    assert "target: 'ui:grandmap:status-model'" in super_node
    assert "source_boundary_port: 'model_status'" in super_node
    assert "target: 'ui:grandmap:status-memory'" in super_node
    assert "source_boundary_port: 'memory_state'" in super_node
    assert "target: 'ui:grandmap:status-health'" in super_node
    assert "source_boundary_port: 'graph_health'" in super_node
    assert "target: 'ui:grandmap:status-settings'" in super_node
    assert "source_boundary_port: 'command_palette'" in super_node
    assert "target: 'ui:grandmap:status-version'" in super_node
    assert "source_boundary_port: 'application_version'" in super_node
    assert "upsertAppRelationWire(spec.target, spec.role, {" in super_node
    assert "target_port: 'status_value'" in super_node
    assert "presentation: 'status-strip'" in super_node

    assert "const syncStatusToApplication = () =>" in status_strip
    assert "status_runtime_label: slots && slots.runtime ? slots.runtime : 'server'" in status_strip
    assert "syncGrandMapSurfaceStateSlots('status-strip', rootId, slotMap" in status_strip
    assert "state_key: 'status_strip_state_node_id'" in status_strip
    assert "'slot:status-runtime': slots && slots.runtime ? slots.runtime : 'server'" in status_strip
    assert "'slot:status-version': slots && slots.version ? slots.version : 'ArchHub'" in status_strip
    assert "applicationBoundaryPortNodeId(g, portForKey[key])" in status_strip
    assert "setGrandMapInlineNodeField(appNode, key, values[key]);" in status_strip
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, key, value)" not in status_strip
    assert "materializeGrandMapParamNode(portNodeId, 'value', value);" in status_strip
    assert "window.ahSetUiNodeParam(portNodeId, 'value', value)" not in status_strip
    assert "const syncStatusApplicationRelations = () =>" in status_strip
    assert "ensureGrandMapApplicationSuperNode({" in status_strip
    assert "mode: appConfig.mode || appData.active_mode || 'home'" in status_strip
    assert "session: { id: appConfig.session_id || appData.active_session || '' }" in status_strip
    assert "focusId: appConfig.focus_id || appData.active_focus || ''" in status_strip
    assert "mode: 'status-strip'" not in status_strip


def test_shell_and_modal_state_are_application_boundary_wired():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]
    sync = jsx[
        jsx.index("const syncGrandMapSidebarPanelState ="):
        jsx.index("const upsertGrandMapCommandPaletteNode =", jsx.index("const syncGrandMapSidebarPanelState ="))
    ]

    assert "const existingAppState = Object.assign({}" in super_node
    assert "active_sidebar_panel: existingAppState.active_sidebar_panel || 'nodes'" in super_node
    assert "rail_drawer_panel: existingAppState.rail_drawer_panel || ''" in super_node
    assert "active_app_modals: existingAppState.active_app_modals || []" in super_node
    assert "active_app_modal_primary: existingAppState.active_app_modal_primary || 'none'" in super_node
    assert "settings_open: !!existingAppState.settings_open" in super_node
    assert "Object.keys(boundaryPortValues).forEach(key => syncAppParamNode(key, boundaryPortValues[key]));" in super_node
    assert "syncAppParamNode('active_sidebar_panel', boundaryPortValues.active_sidebar_panel);" not in super_node
    assert "const shellStateBoundaryTargets = [" in super_node
    assert "target: 'ui:grandmap:sidebar-shell'" in super_node
    assert "role: 'sidebar_active_panel'" in super_node
    assert "source_boundary_port: 'active_sidebar_panel'" in super_node
    assert "target: 'ui:grandmap:app-rail'" in super_node
    assert "source_boundary_port: 'rail_drawer_panel'" in super_node
    assert "target: 'ui:grandmap:app-shell-overlays'" in super_node
    assert "source_boundary_port: 'active_app_modals'" in super_node
    assert "source_boundary_port: 'active_app_modal_primary'" in super_node
    assert "target: 'ui:grandmap:settings-stub'" in super_node
    assert "source_boundary_port: 'settings_open'" in super_node
    assert "target_port: 'state'" in super_node
    assert "behavior: 'control-flow'" in super_node
    assert "presentation: spec.presentation || 'inspector-row'" in super_node

    assert "syncApplicationBoundaryPortValue(g, 'active_sidebar_panel', active);" in sync
    assert "syncApplicationBoundaryPortValue(g, 'rail_drawer_panel', drawer);" in sync
    assert "applicationBoundaryStateNodeId('sidebar-state')" in sync
    assert "exposes_active_sidebar_panel" in sync
    assert "exposes_rail_drawer_panel" in sync
    assert "sidebar_state_wire_node_ids" in sync
    assert "syncApplicationBoundaryPortValue(g, 'active_app_modals', active);" in sync
    assert "syncApplicationBoundaryPortValue(g, 'active_app_modal_primary', payload.active_app_modal_primary);" in sync
    assert "syncApplicationBoundaryPortValue(g, 'settings_open', payload.settings_open);" in sync
    assert "applicationBoundaryStateNodeId('modal-state')" in sync
    assert "exposes_active_app_modals" in sync
    assert "exposes_active_app_modal_primary" in sync
    assert "exposes_settings_open" in sync
    assert "modal_state_wire_node_ids" in sync


def test_application_runtime_and_host_state_use_boundary_relation_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const applicationBoundaryStateNodeId ="):
        jsx.index("const ensureGrandMapApplicationSuperNode =", jsx.index("const applicationBoundaryStateNodeId ="))
    ]
    runtime_sync = jsx[
        jsx.index("const syncApplicationBoundaryRuntimeHostState ="):
        jsx.index("const ensureGrandMapApplicationSuperNode =", jsx.index("const syncApplicationBoundaryRuntimeHostState ="))
    ]
    super_node = jsx[
        jsx.index("const ARCHHUB_APPLICATION_BOUNDARY_PORT_SPECS ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]
    server_strip = jsx[
        jsx.index("const ServerStrip ="):
        jsx.index("const ServerStripMemo =", jsx.index("const ServerStrip ="))
    ]

    assert "id: 'runtime_state'" in super_node
    assert "id: 'host_registry'" in super_node
    assert "id: 'host_live_count'" in super_node
    assert "const applicationBoundaryStateNodeId = (kind) =>" in helpers
    assert "const applicationBoundaryStateWireId = (boundaryPortId, targetNodeId, relation) =>" in helpers
    assert "const applicationBoundaryPortNodeId = (graph, portId) =>" in helpers
    assert "data.relation_wire_family === 'application_boundary'" in helpers
    assert "const upsertApplicationBoundaryStateNode = (graph, nodeId, title, payload) =>" in helpers
    assert "role: 'application_runtime_state'" in helpers
    assert "role: 'application_host_registry_state'" in helpers
    assert "const upsertApplicationBoundaryStateRelation = (graph, boundaryPortId, targetNodeId, relation, options = {}) =>" in helpers
    assert "wire_family: 'application_boundary'" in helpers
    assert "source_boundary_port: boundaryPortId" in helpers
    assert "upsertApplicationBoundaryStateRelation(g, 'runtime_http_port'" in helpers
    assert "upsertApplicationBoundaryStateRelation(g, 'runtime_state'" in helpers
    assert "upsertApplicationBoundaryStateRelation(g, 'host_registry'" in helpers
    assert "upsertApplicationBoundaryStateRelation(g, 'host_live_count'" in helpers
    assert "boundary_state_node_ids: liveBoundaryStateNodeIds" in helpers
    assert "boundary_state_wire_node_ids: liveBoundaryStateWireNodeIds" in helpers
    assert "['runtime_state_node_id', runtimeNode && runtimeNode.id || '']" in runtime_sync
    assert "['boundary_state_wire_node_ids', liveBoundaryStateWireNodeIds]" in runtime_sync
    assert "setGrandMapInlineNodeField(appNode, key, value)" in runtime_sync
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'runtime_state_node_id'" not in runtime_sync
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'boundary_state_wire_node_ids'" not in runtime_sync
    assert "syncApplicationBoundaryRuntimeHostState({" in super_node
    assert "runtime_state: runtimeStateValue" in super_node
    assert "host_registry_state: hostRegistryState" in super_node
    assert "host_live_count: hostLiveCount" in super_node
    assert "window.__archhub_runtime_info = r;" in server_strip
    assert "syncApplicationBoundaryRuntimeHostState({ runtime: r, hosts: LM_HOSTS || [] });" in server_strip


def test_application_boundary_state_focus_opens_runtime_host_chain_on_canvas():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workflow_filters = jsx[
        jsx.index("const workflowApplicationBoundaryAnatomyNodesForFocus ="):
        jsx.index("const isStructuralAnatomyViewNode =", jsx.index("const workflowApplicationBoundaryAnatomyNodesForFocus ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    debug_state = jsx[
        jsx.index("window.__archhub_wire_anatomy_state = {"):
        jsx.index("const toggleExpanded =", jsx.index("window.__archhub_wire_anatomy_state = {"))
    ]

    assert "const workflowApplicationBoundaryAnatomyNodesForFocus = (graphNodes, focusId) =>" in workflow_filters
    assert "const rawGraphNodes = [];" in workflow_filters
    assert "const anatomyNodeById = (id) => byId.get(id || '') || rawById.get(id || '');" in workflow_filters
    assert "const node = anatomyNodeById(id);" in workflow_filters
    assert "focusData.relation_wire_family === 'application_boundary'" in workflow_filters
    assert "focusData.role === 'wire' && focusData.wire_family === 'application_boundary'" in workflow_filters
    assert "const isAppBoundaryRelationWireData = (data) => !!(" in workflow_filters
    assert "data.owner === ARCHHUB_APPLICATION_SUPER_NODE_ID" in workflow_filters
    assert "data.source_boundary_port &&" in workflow_filters
    assert "data.source_boundary_port !== 'surface_output'" in workflow_filters
    assert "const isAppBoundaryWire = isAppBoundaryRelationWireData(focusData);" in workflow_filters
    assert "const isAppBoundaryLayer = focusData.role === 'wire_layer' && isAppBoundaryRelationWireData(focusOwnerData);" in workflow_filters
    assert "const isAppBoundaryRuntime = focusData.role === 'wire_runtime' && isAppBoundaryRelationWireData(focusOwnerData);" in workflow_filters
    assert "const hasIncomingAppBoundaryRelation = (liveGraphNodes || []).some(node => {" in workflow_filters
    assert "!isApplicationFocus && !isAppBoundaryWire && !isAppBoundaryLayer && !isAppBoundaryRuntime &&" in workflow_filters
    assert "isBoundaryWire || isAppBoundaryWire" in workflow_filters
    assert "isBoundaryLayer || isBoundaryRuntime || isAppBoundaryLayer || isAppBoundaryRuntime" in workflow_filters
    assert "(Array.isArray(appData.relation_wire_node_ids) ? appData.relation_wire_node_ids : []).forEach(wireNodeById);" in workflow_filters
    assert "focusData.role === 'application_runtime_state'" in workflow_filters
    assert "focusData.role === 'application_host_registry_state'" in workflow_filters
    assert "focusId === ARCHHUB_APPLICATION_SUPER_NODE_ID" in workflow_filters
    assert "if (!isBoundaryRelationWireNode(node)) return;" in workflow_filters
    assert "data.source_boundary_port === boundaryPortId" in workflow_filters
    assert "toPortData.owner === focusId" in workflow_filters
    assert "nodeConnectionWireLayerChips(liveGraphNodes, wireNode).forEach(chip =>" in workflow_filters
    assert "(rawGraphNodes || []).forEach(n => {" in workflow_filters
    assert "return Array.from(ids).filter(id => !!anatomyNodeById(id));" in workflow_filters
    assert "anatomy_owner_boundary_focus: focusId" in workflow_filters
    assert "anatomy_boundary_role: roleOf(id)" in workflow_filters
    assert "return data.owner === ARCHHUB_APPLICATION_SUPER_NODE_ID ? 'boundary_port' : 'target_port';" in workflow_filters
    assert "const boundaryStateAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowApplicationBoundaryAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "const anatomyNodes = selectedWireAnatomyNodes.concat(" in node_canvas
    assert "boundaryStateAnatomyNodes," in node_canvas
    assert "nodeConnectionSectionAnatomyNodes," in node_canvas
    assert "const anatomyNodeIds = new Set(anatomyNodes.map(n => n && n.id).filter(Boolean));" in node_canvas
    assert "const baseOutsideAnatomy = base.filter(n => n && !anatomyNodeIds.has(n.id));" in node_canvas
    assert "return baseOutsideAnatomy.concat(anatomyNodes.filter(n => n && !seen.has(n.id)));" in node_canvas
    assert "boundaryStateAnatomyNodeIds" in debug_state
    assert "boundaryStateAnatomyNodes: (boundaryStateAnatomyNodes || []).map(n => {" in debug_state
    assert "anatomy_boundary_role: data.anatomy_boundary_role || ''" in debug_state
    assert "wire_family: data.wire_family || data.relation_wire_family || ''" in debug_state
    assert "source_boundary_port: data.source_boundary_port || data.port_id || ''" in debug_state


def test_hidden_application_super_node_focus_opens_canvas_anatomy():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workflow_filters = jsx[
        jsx.index("const isVisibleWorkflowCanvasNode ="):
        jsx.index("const wireEndpointNodeId =")
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    focus_effect = node_canvas[
        node_canvas.index("const onFocusNode = (ev) =>"):
        node_canvas.index("window.addEventListener('lm-focus-node', onFocusNode);", node_canvas.index("const onFocusNode = (ev) =>"))
    ]

    assert "if (data.role === 'application') return false;" in workflow_filters
    assert "const isApplicationFocus = focusId === ARCHHUB_APPLICATION_SUPER_NODE_ID;" in workflow_filters
    assert "const liveFocusNode = (workflowLiveGraphNodes(graphNodes) || []).find(n => n && n.id === nid);" in focus_effect
    assert "const node = (allNodes || []).find(n => n.id === nid) || liveFocusNode;" in focus_effect
    assert "if (!node) return;" in focus_effect
    assert "setFocusId(nid);" in focus_effect
    assert "}, [zoom, allNodes, graphNodes, positions, getWrapRect, setFocusId]);" in node_canvas


def test_application_relation_wires_materialize_as_focusable_wire_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    wire_node = jsx[
        jsx.index("const appRelationWireNodeId ="):
        jsx.index("const ensureGrandMapApplicationSuperNode =", jsx.index("const appRelationWireNodeId ="))
    ]

    assert "'wire:relation:' + grandMapSafeId(wireId || 'relation-wire')" in wire_node
    assert "kind: 'wire'" in wire_node
    assert "cat: 'wire'" in wire_node
    assert "role: 'wire'" in wire_node
    assert "const wireFamily = data.wire_family || 'app_relation';" in wire_node
    assert "wire_family: wireFamily" in wire_node
    assert "wire_id: wire.id" in wire_node
    assert "const portBinding = [fromPortNode || fromNode, toPortNode || toNode].join(' -> ');" in wire_node
    assert "const appRelationWireLayerKeys = () => APP_RELATION_WIRE_LAYER_SPECS.map(spec => spec.id);" in wire_node
    assert "const requestedAnatomy = data.materialize_wire_anatomy;" in wire_node
    assert "requestedAnatomy === 'layers'" in wire_node
    assert "const materializeWireAnatomy = anatomyMode !== 'none';" in wire_node
    assert "const materializeWireParams = anatomyMode === 'full';" in wire_node
    assert "const appRelationWireShouldMaterializeAnatomy = (wireFamily) =>" in wire_node
    assert "if (family === 'ui_action') return true;" in wire_node
    assert "if (family === 'ui_binding') return true;" in wire_node
    assert "if (family === 'ui_render_slot_mount') return true;" in wire_node
    assert "if (family === 'ui_slot_parameter') return true;" in wire_node
    assert "if (family.indexOf('right_rail_') === 0) return true;" in wire_node
    assert "if (family.indexOf('ui_') === 0) return true;" in wire_node
    assert "if (family === 'node_connections_section_ui') return true;" in wire_node
    assert "if (family === 'canvas_selected_wire') return true;" in wire_node
    assert "'materialize_wire_anatomy'" in wire_node
    assert "const wireLayers = materializeWireAnatomy ? ['gate', 'behavior', 'presentation'] : [];" in wire_node
    assert "const activeStageIds = new Set" in wire_node
    assert "const activeSpecs = APP_RELATION_WIRE_LAYER_SPECS.filter" in wire_node
    assert "if (materializeWireParams) {" in wire_node
    assert "const GENERIC_WIRE_LAYER_SPECS = [" in wire_node
    assert "const wireLayerSpecsForContext = (overrides) =>" in wire_node
    assert "const APP_RELATION_WIRE_LAYER_SPECS = wireLayerSpecsForContext({" in wire_node
    assert "source_port: { valueKey:'from_port_node', capabilities:['select_output_port_node', 'port_parameter', 'external_port_binding'] }" in wire_node
    assert "target_port: { valueKey:'to_port_node', capabilities:['select_input_port_node', 'port_parameter', 'external_port_binding'] }" in wire_node
    assert "{ id:'source_field', valueKey:'src_field', title:'Source field layer', capabilities:['select_subvalue', 'field_projection', 'geometry_attribute_path', 'image_metadata_path'] }" in wire_node
    assert "{ id:'target_field', valueKey:'dst_field', title:'Target field layer', capabilities:['wrap_subvalue', 'field_injection', 'input_shape'] }" in wire_node
    assert "{ id:'schema', valueKey:'schema_ref', title:'Schema layer', capabilities:['schema_ref', 'contract_check'] }" in wire_node
    assert "const ensureAppRelationWireLayerNodes = (graph, wireNodeId, payload, wireFamily, requestedStageIds) =>" in wire_node
    assert "{ id:'encryption', valueKey:'encryption', title:'Encryption layer', capabilities:['encrypt', 'decrypt'], options:WIRE_LAYER_OPTION_SETS.encryption }" in wire_node
    assert "role: 'wire_layer'" in wire_node
    assert "wire_family: family" in wire_node
    assert "role: 'wire_layer_link'" in wire_node
    assert "materializeWireLayerValueParamNode(g, layerNode, spec, value);" in wire_node
    assert "layer_nodes: layerMap" in wire_node
    assert "node.outs = [{ id:'to', label:'to', t:'node' }, { id:'layer', label:'layers', t:'node' }];" in wire_node
    assert "source_owner: sourceOwner" in wire_node
    assert "target_owner: targetOwner" in wire_node
    assert "from_port_node: fromPortNode" in wire_node
    assert "to_port_node: toPortNode" in wire_node
    assert "port_binding: portBinding" in wire_node
    assert "wire_layers: wireLayers" in wire_node
    assert "gate_policy: gatePolicy" in wire_node
    assert "encryption" in wire_node
    assert "['relation', relation]" in wire_node
    assert "['source_owner', sourceOwner]" in wire_node
    assert "['target_owner', targetOwner]" in wire_node
    assert "['wire_layers', wireLayers]" in wire_node
    assert "['src_field', srcField]" in wire_node
    assert "['dst_field', dstField]" in wire_node
    assert "['port_binding', portBinding]" in wire_node
    assert "['gate_policy', gatePolicy]" in wire_node
    assert "['encryption', encryption]" in wire_node
    assert "['presentation', presentation]" in wire_node
    assert "['from_node', fromNode]" in wire_node
    assert "['to_node', toNode]" in wire_node
    assert "materializeGrandMapParamNode(nodeId, paramKey, paramValue);" in wire_node
    assert "window.ahSetUiNodeParam(nodeId, 'relation', relation);" not in wire_node
    assert "window.ahSetUiNodeParam(nodeId, 'wire_layers', wireLayers);" not in wire_node
    assert "if (materializeWireAnatomy) {" in wire_node
    assert "ensureAppRelationWireLayerNodes(g, nodeId, {" in wire_node
    assert "node.data = Object.assign({}, node.data || {}, { layer_nodes: {}, wire_layers: [] });" in wire_node
    assert "from_port_node: fromPortNode" in wire_node
    assert "to_port_node: toPortNode" in wire_node
    assert "src_field: srcField" in wire_node
    assert "dst_field: dstField" in wire_node
    assert "param.wire_layer_node_id = layerNodeId;" in wire_node


def test_ui_action_relations_materialize_layer_anatomy_before_selection():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    action_relation = jsx[
        jsx.index("const uiActionEndpointWireId ="):
        jsx.index("const syncUiImportedActionRelationWireNode =")
    ]

    assert "Object.prototype.hasOwnProperty.call(options, 'materialize_wire_anatomy')" in action_relation
    assert "existingRelationData.anatomy_mode === 'full' ? true : 'layers'" in action_relation
    assert action_relation.count("materialize_nested_params: false") >= 2
    assert "materialize_wire_anatomy: requestedAnatomy" in action_relation


def test_ui_binding_relations_materialize_stages_except_for_compact_inspector_bindings():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    binding_relation = jsx[
        jsx.index("const syncUiBindingRelation ="):
        jsx.index("const syncUiSurfaceDeclaredBindingRelations =")
    ]

    assert "wire_family: 'ui_binding'" in binding_relation
    assert "from_port_node: sourcePortNodeId || ''" in binding_relation
    assert "to_port_node: targetPortNodeId || ''" in binding_relation
    assert binding_relation.count("materialize_nested_params: false") >= 2
    assert "materialize_wire_anatomy: compactInspectorBinding ? false : 'layers'" in binding_relation
    assert "role: 'ui_binding_projection'" in binding_relation
    assert "ui_binding_migrated_keys:Array.from(new Set" in binding_relation

    selected_wire = jsx[
        jsx.index("const ensureSelectedRelationWireFullAnatomy ="):
        jsx.index("const rightRailConnectionWireId =")
    ]
    node_rail = jsx[
        jsx.index("const NodeRail ="):
        jsx.index("// Audit 2026-05-28", jsx.index("const NodeRail ="))
    ]
    assert "data.role !== 'wire'" in selected_wire
    assert "data.anatomy_mode !== 'full'" in selected_wire
    assert "materializeGrandMapParamNode(encryptionLayer.id, 'key_ref', keyRef)" in selected_wire
    assert "const rawWire = _uiFind(g.wires, data.wire_id);" in selected_wire
    assert "materialize_wire_anatomy: true" in selected_wire
    assert "selected_for_inspection: true" in selected_wire
    assert "const selectedNodeId = upsertAppRelationWireNode(g, selectedPayload);" in selected_wire
    assert "node = ensureSelectedRelationWireFullAnatomy(node);" in node_rail


def test_lazy_port_parameter_children_materialize_when_the_port_is_selected():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    port_helper = jsx[
        jsx.index("const ensureUiNodePortParamNode ="):
        jsx.index("const upsertAppRelationWireNode =")
    ]
    selected_parameter = jsx[
        jsx.index("const ensureSelectedParameterNodeFullAnatomy ="):
        jsx.index("const rightRailConnectionWireId =")
    ]
    node_rail = jsx[
        jsx.index("const NodeRail ="):
        jsx.index("// Audit 2026-05-28", jsx.index("const NodeRail ="))
    ]

    assert "const materializeNestedParams = portData.materialize_nested_params !== false;" in port_helper
    assert "nested_params_materialized: materializeNestedParams" in port_helper
    assert "if (materializeNestedParams)" in port_helper
    assert "nestedPortParams.forEach(([paramKey, paramValue]) => materializeGrandMapParamNode" in port_helper
    assert "data.nested_params_materialized !== false" in selected_parameter
    assert "materializeGrandMapParamNode(node.id, param.k, param.v);" in selected_parameter
    assert "nested_params_materialized: true" in selected_parameter
    assert "node = ensureSelectedParameterNodeFullAnatomy(node);" in node_rail


def test_application_relation_wire_layers_are_owned_and_cleaned_by_super_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]

    assert "const liveRelationWireLayerNodeIds = new Set();" in super_node
    assert "Object.values(wireNode.data.layer_nodes)" in super_node
    assert "layerNodes.forEach(layerNodeId => layerNodeId && liveRelationWireLayerNodeIds.add(layerNodeId));" in super_node
    assert "const staleRelationWireLayerNodeIds = new Set();" in super_node
    assert "n.data.role === 'wire_layer' && n.data.wire_family === 'app_relation'" in super_node
    assert "const staleRelationPortNodeIds = new Set();" in super_node
    assert "...staleRelationPortNodeIds" in super_node
    assert "data.role === 'wire_layer_link' && stale.has(data.layer_node)" in super_node
    assert "data.role === 'wire_runtime_link' && stale.has(data.runtime_node)" in super_node
    assert "Array.from(liveRelationWireLayerNodeIds)" in super_node


def test_application_relation_wire_edits_survive_super_node_refresh():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]
    upsert = super_node[
        super_node.index("const upsertAppRelationWire ="):
        super_node.index("const relationPayload = {", super_node.index("const upsertAppRelationWire ="))
    ]

    assert "const existingWireNode = _uiFind(g.nodes, appRelationWireNodeId(id));" in upsert
    assert "const existingWireData = existingWireNode && existingWireNode.data && typeof existingWireNode.data === 'object'" in upsert
    assert "const valueType = existingWireData.value_type || options.value_type || 'ui';" in upsert
    assert "const schemaRef = existingWireData.schema_ref || options.schema_ref || 'archhub.ui.element';" in upsert
    assert "const srcField = existingWireData.src_field || options.src_field || '';" in upsert
    assert "const dstField = existingWireData.dst_field || options.dst_field || '';" in upsert
    assert "const gatePolicy = existingWireData.gate_policy || options.gate_policy || 'allow-if-target-exists';" in upsert
    assert "const codec = existingWireData.codec || options.codec || 'none';" in upsert
    assert "const encryption = existingWireData.encryption || options.encryption || 'none';" in upsert
    assert "const behavior = existingWireData.behavior || options.behavior || 'mediate-relation';" in upsert
    assert "const presentation = existingWireData.presentation || options.presentation || 'surface-relation';" in upsert


def test_application_super_node_wires_active_focus_as_relation_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]

    assert "const upsertAppRelationWire = (targetId, role, options = {}) =>" in super_node
    assert "const sourcePortId = options.source_port || role;" in super_node
    assert "const targetPortId = options.target_port || 'owner';" in super_node
    assert "const valueType = existingWireData.value_type || options.value_type || 'ui';" in super_node
    assert "const schemaRef = existingWireData.schema_ref || options.schema_ref || 'archhub.ui.element';" in super_node
    assert "to: { node: targetPortNodeId || targetId, port: targetPortId }" in super_node
    assert "if (focusNodeId && isApplicationSurfaceTarget(focusNodeId)) {" in super_node
    assert "upsertAppRelationWire(focusNodeId, 'active_focus', {" in super_node
    assert "source_port: 'active_focus'" in super_node
    assert "target_port: 'focused_by'" in super_node
    assert "value_type: 'node'" in super_node
    assert "schema_ref: 'archhub.graph.node'" in super_node
    assert "behavior: 'drive-active-right-rail'" in super_node
    assert "presentation: 'focus-relation'" in super_node


def test_command_palette_state_is_graph_node_and_application_wire():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    super_node = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]
    helper = jsx[
        jsx.index("const upsertGrandMapCommandPaletteNode ="):
        jsx.index("const ensureGrandMapStatusStripNodes =", jsx.index("const upsertGrandMapCommandPaletteNode ="))
    ]
    row_surface = jsx[
        jsx.index("const CommandPaletteRowSurface ="):
        jsx.index("const CommandPaletteSurface =", jsx.index("const CommandPaletteRowSurface ="))
    ]
    input_surface = jsx[
        jsx.index("const CommandPaletteInputSurface ="):
        jsx.index("const CommandPaletteRowSurface =", jsx.index("const CommandPaletteInputSurface ="))
    ]
    surface = jsx[
        jsx.index("const CommandPaletteSurface ="):
        jsx.index("const CommandPaletteInner =", jsx.index("const CommandPaletteSurface ="))
    ]
    palette = jsx[
        jsx.index("const CommandPaletteInner ="):
        jsx.index("const CommandPalette = React.memo")
    ]
    palette_list = palette[
        palette.index("const paletteList = ("):
        palette.index("const paletteFooter = (")
    ]

    assert "const GRANDMAP_COMMAND_PALETTE_NODE_ID = 'ui:grandmap:command-palette';" in jsx
    assert "GRANDMAP_COMMAND_PALETTE_NODE_ID," in super_node
    assert "type: 'ui.element'" in helper
    assert "kind: 'ui'" in helper
    assert "cat: 'ui'" in helper
    assert "tag: 'div'" in helper
    assert "source_node_ids: ['ui_command_palette']" in helper
    assert "action: 'command_palette.close'" in helper
    assert "args: { node_id: rootId }" in helper
    assert "'data-command-palette-close-action': 'command_palette.close'" in helper
    assert "hydrateUiNodeActionBehavior(rootId, 'command-palette'" in helper
    assert "children: ['ui:grandmap:command-palette-panel']" in helper
    assert "stop_click: true" in helper
    assert "render_slot: 'slot:command-palette-input'" in helper
    assert "render_slot: 'slot:command-palette-list'" in helper
    assert "render_slot: 'slot:command-palette-footer'" in helper
    assert "capabilities: ['store_value', 'drive_owner_config', 'modal_overlay', 'command_search']" in helper
    assert "const sourcePortNodeId = ensureUiNodePortParamNode(g, ARCHHUB_APPLICATION_SUPER_NODE_ID" in helper
    assert "const targetPortNodeId = ensureUiNodePortParamNode(g, rootId" in helper
    assert "const wireId = appRelationWireId(rootId, 'command_palette');" in helper
    assert "schema_ref: 'archhub.ui.command_palette'" in helper
    assert "behavior: 'control-command-palette'" in helper
    assert "presentation: 'modal-overlay'" in helper
    assert "upsertAppRelationWireNode(g, relationPayload);" in helper
    assert "command_palette_state_node: true" in helper
    assert "command_palette_open: !!state.open" in helper
    assert "command_palette_query: state.q ? String(state.q) : ''" in helper
    assert "command_palette_selected_index: selectedItem ? Number(state.selIdx || 0) : -1" in helper
    assert "command_palette_total_count: all.length" in helper
    assert "command_palette_filtered_count: filtered.length" in helper
    assert "command_palette_memory_count: countKind('memory')" in helper
    assert "syncNode(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'command_palette_state');" in helper
    assert "syncNode(rootId, 'command_palette_state');" in helper
    assert "syncNode('ui:grandmap:app-shell-overlays', 'command_palette_state');" in helper
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(node, key, payload[key]));" in helper
    assert "syncApplicationBoundaryPortValue(g, 'command_palette', payload);" in helper
    assert "window.ahSetUiNodeParam(nodeId, key, payload[key]);" not in helper
    assert "const upsertGrandMapCommandPaletteInputNode = (slots = {}) =>" in helper
    assert "surface: 'command-palette-input'" in helper
    assert "role: 'command_palette_input'" in helper
    assert "action: 'command_palette.query_change'" in helper
    assert "key_actions: {" in helper
    assert "action: 'command_palette.select_next'" in helper
    assert "action: 'command_palette.select_previous'" in helper
    assert "action: 'command_palette.run_selected'" in helper
    assert "action: 'command_palette.close'" in helper
    assert "hydrateUiNodeActionBehavior(rootId, 'command-palette-input'" in helper
    assert "state_key: 'command_palette_input_state_node_id'" in helper
    assert "const upsertGrandMapCommandPaletteRowNodes = (item, slots = {}) =>" in helper
    assert "surface: 'command-palette-row'" in helper
    assert "role: 'command_palette_row'" in helper
    assert "action: 'command_palette.run_item'" in helper
    assert "args: actionArgs" in helper
    assert "hover_action: 'command_palette.select_item'" in helper
    assert "hover_args: hoverArgs" in helper
    assert "'data-command-palette-item-id': item.id || ''" in helper
    assert "hydrateUiNodeActionBehavior(rootId, 'command-palette-row'" in helper
    assert "bind: labelSlot" in helper
    assert "bind: subSlot" in helper
    assert "bind: kindSlot" in helper
    assert "syncGrandMapSurfaceStateSlots('command-palette-row-' + sid, rootId, slotMap" in helper
    assert "state_key: 'command_palette_row_state_node_id'" in helper
    assert "['ui:grandmap:command-palette-list-slot', rootId]" in helper
    assert "listNode.data.row_nodes" in helper
    assert "['item_id', item.id || '']" in helper
    assert "['selected', selected]" in helper
    assert "['action', 'command_palette.run_item']" in helper
    assert "['hover_action', 'command_palette.select_item']" in helper
    assert "setGrandMapInlineNodeField(root, field, fieldValue)" in helper
    assert "window.ahSetUiNodeParam(rootId, 'item_id', item.id || '');" not in helper
    assert "window.ahSetUiNodeParam(rootId, 'selected', selected);" not in helper
    assert "const CommandPaletteInputSurface = ({ query, selectedIndex, filteredCount, selectedItem, setQuery, setSelectedIndex, runSelected, closePalette }) =>" in input_surface
    assert "() => upsertGrandMapCommandPaletteInputNode({" in input_surface
    assert "registerUiHostCapability('command_palette.query_change'" in input_surface
    assert "registerUiHostCapability('command_palette.select_next'" in input_surface
    assert "registerUiHostCapability('command_palette.select_previous'" in input_surface
    assert "registerUiHostCapability('command_palette.run_selected'" in input_surface
    assert "registerUiHostCapability('command_palette.close'" in input_surface
    assert 'surface="command-palette-input"' in input_surface
    assert "const CommandPaletteRowSurface = ({ item, index, selected, tagCol, runItem, setSelectedIndex }) =>" in row_surface
    assert "() => upsertGrandMapCommandPaletteRowNodes(item, { index, selected, tagCol })" in row_surface
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction);" not in row_surface
    assert "registerUiHostCapability('command_palette.run_item'" in row_surface
    assert "registerUiHostCapability('command_palette.select_item'" in row_surface
    assert 'surface="command-palette-row"' in row_surface
    row_live_surface = row_surface[
        row_surface.index("if (!rootId) return fallback;"):
        row_surface.index(");", row_surface.index("if (!rootId) return fallback;"))
    ]
    assert "rootProps" not in row_live_surface
    assert "onClick: () => runItem(item)" not in row_live_surface
    assert "onMouseEnter: () => setSelectedIndex(index)" not in row_live_surface
    assert "const CommandPaletteSurface = ({ closePalette, input, list, footer, fallback }) =>" in surface
    assert "() => upsertGrandMapCommandPaletteNode()" in surface
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction);" not in surface
    assert "registerUiHostCapability('command_palette.close'" in surface
    assert 'surface="command-palette"' in surface
    assert "rootProps={{ onClick: closePalette }}" not in surface
    assert "'slot:command-palette-input': input" in surface
    assert "'slot:command-palette-list': list" in surface
    assert "'slot:command-palette-footer': footer" in surface
    assert "const selectedItem = filtered[selIdx] || null;" in palette
    assert "syncGrandMapCommandPaletteState({" in palette
    assert "selectedItem," in palette
    assert "<CommandPaletteInputSurface" in palette
    assert "setQuery={setQ}" in palette
    assert "setSelectedIndex={setSelIdx}" in palette
    assert "runSelected={run}" in palette
    assert "const paletteInput = (" in palette
    assert "const paletteList = (" in palette
    assert "const paletteFooter = (" in palette
    assert "const paletteFallback = (" in palette
    assert "<CommandPaletteSurface" in palette
    assert "<CommandPaletteRowSurface" in palette_list
    assert "<div key={it.id}" not in palette_list


def test_app_shell_rail_and_command_palette_rows_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    app_shell = jsx[
        jsx.index("const seedGrandMapAppShellFallbackNodes ="):
        jsx.index("const ARCHHUB_APPLICATION_SUPER_NODE_ID =", jsx.index("const seedGrandMapAppShellFallbackNodes ="))
    ]
    rail = jsx[
        jsx.index("const ensureGrandMapAppRailNodes ="):
        jsx.index("const syncGrandMapSidebarPanelState =", jsx.index("const ensureGrandMapAppRailNodes ="))
    ]
    command_rows = jsx[
        jsx.index("const upsertGrandMapCommandPaletteRowNodes ="):
        jsx.index("const ensureGrandMapSettingsStubNodes =", jsx.index("const upsertGrandMapCommandPaletteRowNodes ="))
    ]

    assert "syncGrandMapSurfaceStateSlots('app-shell', rootId, slotMap" in app_shell
    assert "state_key: 'app_shell_state_node_id'" in app_shell
    assert "'slot:app-shell-mode': mode || 'home'" in app_shell
    assert "'slot:app-shell-inspector-focus': focusId || ''" in app_shell
    fallback_seed = app_shell[
        app_shell.index("const children = ["):
        app_shell.index("syncGrandMapSurfaceStateSlots('app-shell', rootId, slotMap")
    ]
    assert "let childrenParam = root.params.find(p => p && p.k === 'children');" in fallback_seed
    assert "materializeGrandMapParamNode(rootId, 'children', children);" in fallback_seed
    assert "window.ahSetUiNodeParam(rootId, 'children', children)" not in fallback_seed
    assert "const authoritativeChildren = Array.isArray(root.data && root.data.children)" in app_shell
    assert "materializeGrandMapParamNode(rootId, 'children', authoritativeChildren);" in app_shell
    assert "window.ahSetUiNodeParam(rootId, 'children', authoritativeChildren)" not in app_shell
    assert "syncGrandMapSurfaceStateSlots('app-rail', rootId, slotMap" in rail
    assert "state_key: 'app_rail_state_node_id'" in rail
    assert "'slot:rail-active': slots && slots.active ? slots.active : 'home'" in rail
    assert "const slotMap = {" in command_rows
    assert "[labelSlot]: item.label || ''" in command_rows
    assert "syncGrandMapSurfaceStateSlots('command-palette-row-' + sid, rootId, slotMap" in command_rows
    assert "state_key: 'command_palette_row_state_node_id'" in command_rows


def test_visible_ui_node_click_focuses_backing_node_into_home_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    projector = jsx[
        jsx.index("function projectUiNode("):
        jsx.index("const UiNodeSurface =", jsx.index("function projectUiNode("))
    ]
    studio_root = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SField = ({ label }) =>", jsx.index("const StudioLM ="))
    ]

    assert "const uiFocusRouteAuthority = (nodes, wires, ownerNodeId) =>" in jsx
    assert "const syncUiFocusRouteRelation = (ownerNodeId, surfaceName) =>" in jsx
    assert "props.onClickCapture = (e) =>" in projector
    assert "window.dispatchEvent(new CustomEvent('lm-ui-node-focus'" in projector
    assert "source:'ui-projector'" in projector
    assert "focus_relation_node_id:route.relationNode && route.relationNode.id || ''" in projector
    assert "focus_relation_wire_id:route.relationWire && route.relationWire.id || ''" in projector
    assert "window.addEventListener('lm-ui-node-focus', focusGraphNodeAtRoot);" in studio_root
    assert "const focusNodeForShell = React.useMemo(" in studio_root
    assert "const homeInspectorSlot = !session && focusNodeForShell" in studio_root
    assert "<NodeRail node={focusNodeForShell} bumpGraph={bumpGraph} setFocusId={setFocusId}/>" in studio_root
    assert "inspector={homeInspectorSlot}" in studio_root


def test_chat_panel_shell_hydrates_chats_panel_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chats_panel = jsx[
        jsx.index("const ChatsPanel ="):
        jsx.index("const ChatItemMenu =", jsx.index("const ChatsPanel ="))
    ]

    assert "const ChatPanelShellSurface = ({ header, search, list, menu, account }) =>" in jsx
    assert "const ensureGrandMapChatPanelShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-shell'" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-list'" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-message'" in jsx
    assert "const ChatPanelListSurface = ({ children }) =>" in jsx
    assert "const ChatPanelMessageSurface = ({ message }) =>" in jsx
    assert "<ChatPanelShellSurface" in chats_panel
    assert "<ChatPanelListSurface>" in chats_panel
    assert "<ChatPanelMessageSurface message=" in chats_panel
    assert "<SkillsPanelListSurface>" not in chats_panel
    assert "slot:chat-panel-shell-header" in jsx
    assert "slot:chat-panel-shell-search" in jsx
    assert "slot:chat-panel-shell-list" in jsx
    assert "slot:chat-panel-list-content" in jsx
    assert "slot:chat-panel-message" in jsx
    assert "<div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0, position:'relative' }}>" not in chats_panel
    assert "padding:'18px 12px', fontFamily:LM.serif" not in chats_panel


def test_skills_panel_shell_hydrates_skills_panel_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    skills_panel = jsx[
        jsx.index("const SkillsPanel ="):
        jsx.index("const SearchPanel =", jsx.index("const SkillsPanel ="))
    ]

    assert "const SkillsPanelShellSurface = ({ header, search, list }) =>" in jsx
    assert "const ensureGrandMapSkillsPanelShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'skills-panel-shell'" in jsx
    assert "<SkillsPanelShellSurface" in skills_panel
    assert "slot:skills-panel-shell-header" in jsx
    assert "slot:skills-panel-shell-search" in jsx
    assert "slot:skills-panel-shell-list" in jsx
    assert "<div data-panel=\"skills\" style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>" not in skills_panel


def test_skills_panel_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    header = jsx[
        jsx.index("const ensureGrandMapSkillsPanelHeaderNodes ="):
        jsx.index(
            "const ensureGrandMapSkillsPanelSearchNodes =",
            jsx.index("const ensureGrandMapSkillsPanelHeaderNodes ="),
        )
    ]
    search = jsx[
        jsx.index("const ensureGrandMapSkillsPanelSearchNodes ="):
        jsx.index(
            "const ensureGrandMapSkillsPanelListNodes =",
            jsx.index("const ensureGrandMapSkillsPanelSearchNodes ="),
        )
    ]
    list_nodes = jsx[
        jsx.index("const ensureGrandMapSkillsPanelListNodes ="):
        jsx.index(
            "const ensureGrandMapSkillsPanelMessageNodes =",
            jsx.index("const ensureGrandMapSkillsPanelListNodes ="),
        )
    ]
    message = jsx[
        jsx.index("const ensureGrandMapSkillsPanelMessageNodes ="):
        jsx.index(
            "const cleanGrandMapSkill =",
            jsx.index("const ensureGrandMapSkillsPanelMessageNodes ="),
        )
    ]
    row_clone = jsx[
        jsx.index("const cloneGrandMapSkillsPanelRowTemplate ="):
        jsx.index(
            "const ensureGrandMapSkillsPanelRowNodes =",
            jsx.index("const cloneGrandMapSkillsPanelRowTemplate ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('skills-panel-header', rootId, slotMap" in header
    assert "state_key: 'skills_panel_header_state_node_id'" in header
    assert "'slot:skills-panel-title': slots && slots.title ? slots.title : 'Skills'" in header
    assert "'slot:skills-panel-count': slots && slots.count != null ? slots.count : 0" in header
    assert "syncGrandMapSurfaceStateSlots('skills-panel-search', rootId, slotMap" in search
    assert "state_key: 'skills_panel_search_state_node_id'" in search
    assert "'slot:skills-search-query': slots && slots.query ? slots.query : ''" in search
    assert "syncGrandMapSurfaceStateSlots('skills-panel-list', rootId, slotMap" in list_nodes
    assert "state_key: 'skills_panel_list_state_node_id'" in list_nodes
    assert "'slot:skills-panel-list-content': ''" in list_nodes
    assert "syncGrandMapSurfaceStateSlots('skills-panel-message', rootId, slotMap" in message
    assert "state_key: 'skills_panel_message_state_node_id'" in message
    assert "'slot:skills-panel-message': (slots && slots.message) || ''" in message
    assert "const clonedSlotMap = {};" in row_clone
    assert "clonedSlotMap[mapId(id)] = slotMap[id];" in row_clone
    assert "syncGrandMapSurfaceStateSlots('skills-panel-row-' + sid, rootId, clonedSlotMap" in row_clone
    assert "state_key: 'skills_panel_row_state_node_id'" in row_clone


def test_search_panel_shell_hydrates_search_panel_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    search_panel = jsx[
        jsx.index("const SearchPanel ="):
        jsx.index("const NodePaletteShellSurface =", jsx.index("const SearchPanel ="))
    ]

    assert (
        "const SearchPanelShellSurface = ({ header, search, scopes, results }) =>"
        in jsx
    )
    assert "const ensureGrandMapSearchPanelShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'search-panel-shell'" in jsx
    assert "<SearchPanelShellSurface" in search_panel
    assert "slot:search-panel-shell-header" in jsx
    assert "slot:search-panel-shell-search" in jsx
    assert "slot:search-panel-shell-scopes" in jsx
    assert "slot:search-panel-shell-results" in jsx
    assert "<div data-panel=\"search\" style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>" not in search_panel


def test_search_panel_hydrates_inner_content_from_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    search_panel = jsx[
        jsx.index("const SearchPanel ="):
        jsx.index("const NodePaletteShellSurface =", jsx.index("const SearchPanel ="))
    ]

    for surface in [
        "search-panel-header",
        "search-panel-input",
        "search-panel-scopes-label",
        "search-panel-scopes-list",
        "search-panel-scope-row",
        "search-panel-results-list",
        "search-panel-empty-state",
        "search-panel-hit-row",
    ]:
        assert f"get_grand_map_ui_surface', '{surface}'" in jsx

    assert "const SearchPanelHeaderSurface = () =>" in jsx
    assert "const SearchPanelInputSurface = ({ q, setQ }) =>" in jsx
    assert "const SearchPanelScopesListSurface = ({ children }) =>" in jsx
    assert "const SearchPanelScopeRowSurface = ({ scopeDef, activeScope, setScope }) =>" in jsx
    assert "const SearchPanelResultsListSurface = ({ children }) =>" in jsx
    assert "const SearchPanelHitSurface = ({ hit, onActivate }) =>" in jsx
    assert "search.query.update" in jsx
    assert "search.scope.pick" in jsx
    assert "search.hit.activate" in jsx
    assert "header={<SearchPanelHeaderSurface/>}" in search_panel
    assert "search={<SearchPanelInputSurface q={q} setQ={setQ}/>" in search_panel
    assert "<SearchPanelScopesLabelSurface/>" in search_panel
    assert "<SearchPanelScopesListSurface>" in search_panel
    assert "<SearchPanelScopeRowSurface" in search_panel
    assert "<SearchPanelResultsListSurface>" in search_panel
    assert "<SearchPanelEmptyStateSurface" in search_panel
    assert "<SearchPanelHitSurface" in search_panel
    assert "<div style={{ padding:'0 6px', display:'flex', flexDirection:'column', gap:1 }}" not in search_panel
    assert "<div className=\"ah-scroll\" style={{ flex:1, overflow:'auto', padding:'8px 6px 8px'" not in search_panel
    assert "const SearchHit =" not in jsx
    assert "onMouseEnter={e => onClick" not in search_panel


def test_workspace_shell_hydrates_workspace_layout_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workspace = jsx[
        jsx.index("const WorkspaceInner ="):
        jsx.index("const Workspace = React.memo", jsx.index("const WorkspaceInner ="))
    ]

    assert "const WorkspaceShellSurface = ({ header, canvas, rail, rootProps }) =>" in jsx
    assert "const seedGrandMapWorkspaceShellFallbackNodes = () =>" in jsx
    assert "const ensureGrandMapWorkspaceShellNodes = () =>" in jsx
    assert "const seededRootId = seedGrandMapWorkspaceShellFallbackNodes();" in jsx
    assert "get_grand_map_ui_surface', 'workspace-shell'" in jsx
    assert "<WorkspaceShellSurface" in workspace
    assert "rootProps={{ style: workspaceShellStyle }}" in workspace
    assert "slot:workspace-shell-header" in jsx
    assert "slot:workspace-shell-canvas" in jsx
    assert "slot:workspace-shell-rail" in jsx
    assert "<main style={{" not in workspace


def test_canvas_shell_hydrates_canvas_viewport_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const CanvasShellSurface = ({ content, rootProps }) =>" in jsx
    assert "const seedGrandMapCanvasShellFallbackNodes = () =>" in jsx
    assert "const ensureGrandMapCanvasShellNodes = () =>" in jsx
    assert "const seededRootId = seedGrandMapCanvasShellFallbackNodes();" in jsx
    assert "get_grand_map_ui_surface', 'canvas-shell'" in jsx
    assert "<CanvasShellSurface" in node_canvas
    assert "slot:canvas-shell-content" in jsx
    assert "ref: wrapRef" in node_canvas
    assert "onMouseDown: onCanvasMouseDown" in node_canvas
    assert "content={(<>" in node_canvas
    assert "return (\n    <div\n      ref={wrapRef}" not in node_canvas


def test_canvas_pan_layer_hydrates_transform_layer_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const CanvasPanLayerSurface = ({ content, rootProps }) =>" in jsx
    assert "const seedGrandMapCanvasPanLayerFallbackNodes = () =>" in jsx
    assert "const ensureGrandMapCanvasPanLayerNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-pan-layer'" in jsx
    assert "<CanvasPanLayerSurface" in node_canvas
    assert "slot:canvas-pan-layer-content" in jsx
    assert "ref: panLayerRef" in node_canvas
    assert "transform:`scale(${zoom})`" in node_canvas
    assert "<div ref={panLayerRef}" not in node_canvas


def test_canvas_viewport_state_syncs_to_canvas_node_params():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    viewport_sync = jsx[
        jsx.index("const syncGrandMapCanvasViewportState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasViewportState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasViewportState = (state) =>" in viewport_sync
    assert "canvas_state_node: true" in viewport_sync
    assert "viewport_state: payload" in viewport_sync
    assert "pan_x: payload.pan_x" in viewport_sync
    assert "pan_y: payload.pan_y" in viewport_sync
    assert "zoom_percent: payload.zoom_percent" in viewport_sync
    assert "materializeGrandMapParamNode(nodeId, key, values[key]);" in viewport_sync
    assert "window.ahSetUiNodeParam(nodeId, key, values[key]);" not in viewport_sync
    assert "syncNode('ui:grandmap:canvas-pan-layer', payload);" in viewport_sync
    assert "syncNode('ui:grandmap:canvas-shell', {" in viewport_sync
    assert "submitUniversalCanvasInteraction({" in viewport_sync
    assert "interaction: 'canvas_viewport_update'" in viewport_sync
    assert "viewport: payload" in viewport_sync
    assert "const canvasState = {" in node_canvas
    assert "window.__archhub_canvas_state = canvasState;" in node_canvas
    assert "syncGrandMapCanvasViewportState(canvasState);" in node_canvas


def test_canvas_selection_state_syncs_to_inline_state_and_relation_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    selection_sync = jsx[
        jsx.index("const canvasSelectionWireId ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const canvasSelectionWireId ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const canvasSelectionWireId = (targetId) =>" in selection_sync
    assert "const canvasSelectionEndpointWireId = (wireId, endpoint) =>" in selection_sync
    assert "const syncGrandMapCanvasSelectionState = (selectedIds) =>" in selection_sync
    assert "const ownerId = 'ui:grandmap:canvas-shell';" in selection_sync
    assert "['selected_node_ids', selected]" in selection_sync
    assert "['selection_count', selected.length]" in selection_sync
    assert "setGrandMapInlineNodeField(owner, key, value)" in selection_sync
    assert "window.ahSetUiNodeParam(ownerId, 'selected_node_ids', selected);" not in selection_sync
    assert "window.ahSetUiNodeParam(ownerId, 'selection_count', selected.length);" not in selection_sync
    assert "relation_wire_family: 'canvas_selection'" in selection_sync
    assert "wire_family: 'canvas_selection'" in selection_sync
    assert "relation: 'selected_node'" in selection_sync
    assert "behavior: 'select-node'" in selection_sync
    assert "presentation: 'selection-relation'" in selection_sync
    assert "provenance: 'runtime:syncGrandMapCanvasSelectionState'" in selection_sync
    assert "selection_relation_wire_node_ids: Array.from(liveWireNodeIds)" in selection_sync
    assert "selection_relation_endpoint_wire_ids: Array.from(liveEndpointWireIds)" in selection_sync
    assert "selection_relation_port_node_ids: Array.from(livePortNodeIds)" in selection_sync
    assert "if (n.data && n.data.role === 'parameter' && n.data.relation_wire_family === 'canvas_selection'" in selection_sync
    assert "try { syncGrandMapCanvasSelectionState(selectedIds); } catch (_e) {}" in node_canvas


def test_canvas_selected_wire_state_syncs_to_inline_state_and_relation_wire():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    selected_wire_sync = jsx[
        jsx.index("const syncGrandMapCanvasSelectedWireState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasSelectedWireState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasSelectedWireState = (selection) =>" in selected_wire_sync
    assert "const ref = selection == null ? null : resolveWorkflowWireRelation(g, selection);" in selected_wire_sync
    assert "selected_wire_index: selectedWireIndex" in selected_wire_sync
    assert "selected_wire_node_id: targetWireNodeId" in selected_wire_sync
    assert "selected_wire_id: selectedWireId" in selected_wire_sync
    assert "const selectedWireJunctionNodeIds = [];" in selected_wire_sync
    assert "nodeConnectionWireJunctionMemberNodeIds(g, junctionNodeId)" in selected_wire_sync
    assert "const selectedWireRuntimeNodeId = targetWireNodeId" in selected_wire_sync
    assert "refreshWorkflowWireRuntimeNode(g, targetWireNodeId)" in selected_wire_sync
    assert "const selectedWireMemberRuntimeNodeIds = selectedWireMemberNodeIds" in selected_wire_sync
    assert "const selectedWireLayerNodeIds = [];" in selected_wire_sync
    assert "nodeConnectionWireLayerChips(g.nodes, wireNode)" in selected_wire_sync
    assert "const selectedWirePathNodeIds = [];" in selected_wire_sync
    assert "...selectedWireLayerNodeIds" in selected_wire_sync
    assert "const selectedWirePathGroupNodeId = targetWireNodeId ? 'ui:grandmap:canvas-selected-wire-path-group' : '';" in selected_wire_sync
    assert "selected_wire_junction_node_ids: selectedWireJunctionNodeIds" in selected_wire_sync
    assert "selected_wire_member_node_ids: selectedWireMemberNodeIds" in selected_wire_sync
    assert "selected_wire_layer_node_ids: selectedWireLayerNodeIds" in selected_wire_sync
    assert "selected_wire_runtime_node_id: selectedWireRuntimeNodeId" in selected_wire_sync
    assert "selected_wire_member_runtime_node_ids: selectedWireMemberRuntimeNodeIds" in selected_wire_sync
    assert "selected_wire_source_port_node_id: selectedWireSourcePortNodeId" in selected_wire_sync
    assert "selected_wire_target_port_node_id: selectedWireTargetPortNodeId" in selected_wire_sync
    assert "selected_wire_endpoint_port_node_ids: selectedWireEndpointPortNodeIds" in selected_wire_sync
    assert "selected_wire_path_node_ids: selectedWirePathNodeIds" in selected_wire_sync
    assert "selected_wire_path_group_node_id: selectedWirePathGroupNodeId" in selected_wire_sync
    assert "selected_wire_path_wire_node_ids: selectedWirePathWireNodeIds" in selected_wire_sync
    assert "const selectedWirePathWireLayerNodeIds = [];" in selected_wire_sync
    assert "selected_wire_path_wire_layer_node_ids: selectedWirePathWireLayerNodeIds" in selected_wire_sync
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(owner, key, payload[key]));" in selected_wire_sync
    assert "setGrandMapInlineNodeField(owner, 'selected_wire_path_wire_node_ids', Array.from(livePathWireNodeIds));" in selected_wire_sync
    assert "setGrandMapInlineNodeField(owner, 'selected_wire_path_wire_layer_node_ids', Array.from(livePathWireLayerNodeIds));" in selected_wire_sync
    assert "Object.keys(pathGroupData).forEach(key => setGrandMapInlineNodeField(pathGroupNode, key, pathGroupData[key]));" in selected_wire_sync
    assert "window.ahSetUiNodeParam(ownerId, 'selected_wire_index', selectedWireIndex);" not in selected_wire_sync
    assert "window.ahSetUiNodeParam(ownerId, 'selected_wire_node_id', targetWireNodeId);" not in selected_wire_sync
    assert "window.ahSetUiNodeParam(ownerId, 'selected_wire_path_wire_node_ids', selectedWirePathWireNodeIds);" not in selected_wire_sync
    assert "window.ahSetUiNodeParam(selectedWirePathGroupNodeId, key, pathGroupData[key])" not in selected_wire_sync
    assert "wire_family: 'canvas_selected_wire'" in selected_wire_sync
    assert "relation: 'selected_wire'" in selected_wire_sync
    assert "value_type: 'wire'" in selected_wire_sync
    assert "schema_ref: 'archhub.graph.wire'" in selected_wire_sync
    assert "behavior: 'select-wire'" in selected_wire_sync
    assert "presentation: 'selected-wire-relation'" in selected_wire_sync
    assert "selected_wire_relation_node_id: Array.from(liveWireNodeIds)[0] || ''" in selected_wire_sync
    assert "selected_wire_endpoint_wire_ids: Array.from(liveEndpointWireIds)" in selected_wire_sync
    assert "selected_wire_path_wire_ids: Array.from(livePathWireIds)" in selected_wire_sync
    assert "selected_wire_path_wire_node_ids: Array.from(livePathWireNodeIds)" in selected_wire_sync
    assert "selected_wire_path_wire_layer_node_ids: Array.from(livePathWireLayerNodeIds)" in selected_wire_sync
    assert "selected_wire_path_group_node_id: Array.from(livePathGroupNodeIds)[0] || ''" in selected_wire_sync
    assert "selected_wire_selection_port_node_ids: selectedWireSelectionPortNodeIds" in selected_wire_sync
    assert "selected_wire_port_node_ids: selectedWireAllPortNodeIds" in selected_wire_sync
    assert "const selectedWirePathWireNodesExist = selectedWirePathWireNodeIds.every(id => !!_uiFind(g.nodes, id));" in selected_wire_sync
    assert "const selectedWirePathWireLayerNodesExist = selectedWirePathWireLayerNodeIds.every(id => !!_uiFind(g.nodes, id));" in selected_wire_sync
    assert "role: 'selected_wire_path_wire'" in selected_wire_sync
    assert "pathWireNode.type = 'stem.node';" in selected_wire_sync
    assert "pathWireNode.kind = 'wire';" in selected_wire_sync
    assert "const pathWireParamKeys = [" in selected_wire_sync
    assert "pathWireNode.params = pathWireParamKeys.map(key => ({" in selected_wire_sync
    assert "capabilities: ['relation', 'behavior', 'presentation', 'provenance']" in selected_wire_sync
    assert "anatomy_mode: 'none'" in selected_wire_sync
    assert "wire_layers: []" in selected_wire_sync
    assert "pathWireParamKeys.forEach(key => materializeGrandMapParamNode" not in selected_wire_sync
    assert "ensureAppRelationWireLayerNodes(g, pathWireNodeId" not in selected_wire_sync
    assert "port_binding: relationNodeId + ' -> ' + pathNodeId" in selected_wire_sync
    assert "role: 'selected_wire_path_wire_endpoint'" in selected_wire_sync
    assert "path_wire_node: pathWireNodeId" in selected_wire_sync
    assert "path_wire_id: pathWireId" in selected_wire_sync
    assert "from: { node: relationNodeId, port: 'path' }" in selected_wire_sync
    assert "to: { node: pathWireNodeId, port: 'from' }" in selected_wire_sync
    assert "from: { node: pathWireNodeId, port: 'to' }" in selected_wire_sync
    assert "to: { node: pathNodeId, port: 'selected_path' }" in selected_wire_sync
    assert "const ensureNodeInputPort = (nodeId, portId, label, type) =>" in selected_wire_sync
    assert "const ensureNodeOutputPort = (nodeId, portId, label, type) =>" in selected_wire_sync
    assert "ensureNodeOutputPort(relationNodeId, 'path', 'path', 'node');" in selected_wire_sync
    assert "ensureNodeOutputPort(relationNodeId, 'path_group', 'path group', 'group');" in selected_wire_sync
    assert "selectedWirePathNodeIds.forEach(pathNodeId => ensureNodeInputPort(pathNodeId, 'selected_path', 'selected path', 'node'));" in selected_wire_sync
    assert "role: 'selected_wire_path'" in selected_wire_sync
    assert "relation: 'selected_wire_path'" in selected_wire_sync
    assert "role: 'selected_wire_path_group_relation'" in selected_wire_sync
    assert "relation: 'selected_wire_path_group'" in selected_wire_sync
    assert "role: 'selected_wire_path_group'" in selected_wire_sync
    assert "kind: 'group'" in selected_wire_sync
    assert "{ id:'selected_path', label:'selected path', t:'node' }" in selected_wire_sync
    assert "group_nodes: pathGroupNodeIds" in selected_wire_sync
    assert "selectedWireEndpointPortNodeIds.concat(selectedWireSelectionPortNodeIds)" in selected_wire_sync
    assert "behavior: 'inspect-selected-relation-path'" in selected_wire_sync
    assert "presentation: 'right-rail-group'" in selected_wire_sync
    assert "path_node: pathNodeId" in selected_wire_sync
    assert "if (id.indexOf('w:canvas-selected-wire-path:') === 0)" in selected_wire_sync
    assert "stalePathWireLayerNodeIds.has(data.layer_node)" in selected_wire_sync
    assert "const activeWireSelection = selectedWire || (" in node_canvas
    assert "window.__archhub_active_canvas_wire_selection" in node_canvas
    assert "try { syncGrandMapCanvasSelectedWireState(activeWireSelection); } catch (_e) {}" in node_canvas
    assert "window.setTimeout(() => {" in node_canvas
    assert "try { syncGrandMapCanvasSelectedWireState(activeWireSelection); } catch (_e) {}" in node_canvas
    assert "}, [selectedWire, graphBump, focusId]);" in node_canvas
    assert "window.__archhubSyncGrandMapCanvasSelectedWireState = syncGrandMapCanvasSelectedWireState;" in selected_wire_sync


def test_canvas_debug_state_exposes_selected_wire_path():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("window.__archhub_wire_anatomy_state = {"):
        jsx.index("const toggleExpanded =", jsx.index("window.__archhub_wire_anatomy_state = {"))
    ]

    assert "selectedWireSelection: selectedWire" in node_canvas
    assert "selectedWirePath: (() => {" in node_canvas
    assert "selected_rendered_wire_index: data.selected_rendered_wire_index" in node_canvas
    assert "selected_projected_wire_id: data.selected_projected_wire_id || ''" in node_canvas
    assert "selected_projected_from_wire_id: data.selected_projected_from_wire_id || ''" in node_canvas
    assert "selected_wire_incidence_role: data.selected_wire_incidence_role || ''" in node_canvas
    assert "selectedWireSelection.wireFamily === 'node_connections_section_ui'" in jsx
    assert "upsertNodeConnectionUiChildWireNode(g, projectedFromWireId || rawWireData.wire_id || ref.wireNodeId" in jsx
    assert "const selectedWireStateStillApplied = !targetWireNodeId || (" in jsx
    assert "ownerData.selected_projected_from_wire_id === payload.selected_projected_from_wire_id" in jsx
    assert "selected_wire_path_group_node_id: data.selected_wire_path_group_node_id || ''" in node_canvas
    assert "selected_wire_junction_node_ids: data.selected_wire_junction_node_ids || []" in node_canvas
    assert "selected_wire_member_node_ids: data.selected_wire_member_node_ids || []" in node_canvas
    assert "selected_wire_layer_node_ids: data.selected_wire_layer_node_ids || []" in node_canvas
    assert "selected_wire_runtime_node_id: data.selected_wire_runtime_node_id || ''" in node_canvas
    assert "selected_wire_member_runtime_node_ids: data.selected_wire_member_runtime_node_ids || []" in node_canvas
    assert "selected_wire_source_port_node_id: data.selected_wire_source_port_node_id || ''" in node_canvas
    assert "selected_wire_target_port_node_id: data.selected_wire_target_port_node_id || ''" in node_canvas
    assert "selected_wire_endpoint_port_node_ids: data.selected_wire_endpoint_port_node_ids || []" in node_canvas
    assert "selected_wire_selection_port_node_ids: data.selected_wire_selection_port_node_ids || []" in node_canvas
    assert "selected_wire_port_node_ids: data.selected_wire_port_node_ids || []" in node_canvas
    assert "selected_wire_path_node_ids: data.selected_wire_path_node_ids || []" in node_canvas
    assert "selected_wire_path_wire_ids: data.selected_wire_path_wire_ids || []" in node_canvas
    assert "selected_wire_path_wire_node_ids: data.selected_wire_path_wire_node_ids || []" in node_canvas
    assert "selected_wire_path_wire_layer_node_ids: data.selected_wire_path_wire_layer_node_ids || []" in node_canvas
    assert "selectedPath: !!(w && (w.selectedPath || w.selectedPathJunction))" in node_canvas
    assert "selectedPathRole: w && w.selectedPathRole || ''" in node_canvas


def test_canvas_behavior_state_syncs_snap_to_grid_to_params():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    behavior_sync = jsx[
        jsx.index("const syncGrandMapCanvasBehaviorState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasBehaviorState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasBehaviorState = (state) =>" in behavior_sync
    assert "const ownerId = 'ui:grandmap:canvas-shell';" in behavior_sync
    assert "snap_to_grid: snapToGrid" in behavior_sync
    assert "snap_grid_size: 20" in behavior_sync
    assert "node_drag_behavior: snapToGrid ? 'snap-to-grid' : 'freeform'" in behavior_sync
    assert "behavior_state_node: true" in behavior_sync
    assert "behavior_state: payload" in behavior_sync
    assert "materializeGrandMapParamNode(ownerId, 'snap_to_grid', payload.snap_to_grid);" in behavior_sync
    assert "materializeGrandMapParamNode(ownerId, 'snap_grid_size', payload.snap_grid_size);" in behavior_sync
    assert "materializeGrandMapParamNode(ownerId, 'node_drag_behavior', payload.node_drag_behavior);" in behavior_sync
    assert "window.ahSetUiNodeParam(ownerId, 'snap_to_grid', payload.snap_to_grid);" not in behavior_sync
    assert "window.ahSetUiNodeParam(ownerId, 'snap_grid_size', payload.snap_grid_size);" not in behavior_sync
    assert "window.ahSetUiNodeParam(ownerId, 'node_drag_behavior', payload.node_drag_behavior);" not in behavior_sync
    assert "try { syncGrandMapCanvasBehaviorState({ snapToGrid }); } catch (_e) {}" in node_canvas


def test_canvas_overlay_state_syncs_to_inline_state_and_target_relation_wire():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    overlay_sync = jsx[
        jsx.index("const syncGrandMapCanvasOverlayState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasOverlayState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasOverlayState = (state) =>" in overlay_sync
    assert "const ownerId = 'ui:grandmap:canvas-shell';" in overlay_sync
    assert "if (state.ctxMenu) overlays.push('canvas_menu');" in overlay_sync
    assert "if (state.nodeMenu) overlays.push('node_menu');" in overlay_sync
    assert "if (state.wireMenu) overlays.push('wire_menu');" in overlay_sync
    assert "if (state.wireFieldPicker) overlays.push('wire_field_picker');" in overlay_sync
    assert "if (state.groupDialog) overlays.push('group_dialog');" in overlay_sync
    assert "if (state.saveSkillDialog) overlays.push('save_skill_dialog');" in overlay_sync
    assert "active_overlays: overlays" in overlay_sync
    assert "overlay_target_node_id: targetNodeId" in overlay_sync
    assert "overlay_target_wire_node_id: targetWireNodeId" in overlay_sync
    assert "toast_message: (state.toast && (state.toast.msg || state.toast.text)) || ''" in overlay_sync
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(owner, key, payload[key]));" in overlay_sync
    assert "window.ahSetUiNodeParam(ownerId, key, payload[key]);" not in overlay_sync
    assert "relation_wire_family: 'canvas_overlay'" in overlay_sync
    assert "wire_family: 'canvas_overlay'" in overlay_sync
    assert "relation: 'overlay_target'" in overlay_sync
    assert "behavior: 'drive-overlay-target'" in overlay_sync
    assert "presentation: 'overlay-relation'" in overlay_sync
    assert "provenance: 'runtime:syncGrandMapCanvasOverlayState'" in overlay_sync
    assert "overlay_relation_node_id: Array.from(liveWireNodeIds)[0] || ''" in overlay_sync
    assert "overlay_endpoint_wire_ids: Array.from(liveEndpointWireIds)" in overlay_sync
    assert "overlay_port_node_ids: Array.from(livePortNodeIds)" in overlay_sync
    assert "syncGrandMapCanvasOverlayState({" in node_canvas
    assert "wireFieldPicker," in node_canvas
    assert "saveSkillDialog," in node_canvas


def test_canvas_gesture_state_syncs_to_inline_state_and_relation_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    gesture_sync = jsx[
        jsx.index("const syncGrandMapCanvasGestureState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasGestureState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasGestureState = (state) =>" in gesture_sync
    assert "const ownerId = 'ui:grandmap:canvas-shell';" in gesture_sync
    assert "if (wireDrag) gestures.push('wire_drag');" in gesture_sync
    assert "if (state.bandRect) gestures.push('band_select');" in gesture_sync
    assert "if (state.dropTarget) gestures.push('drop_target');" in gesture_sync
    assert "active_gestures: gestures" in gesture_sync
    assert "wire_drag_source_node_id: from.nodeId || ''" in gesture_sync
    assert "wire_drag_hover_node_id: hover && hover.nodeId || ''" in gesture_sync
    assert "wire_drag_hover_ok: !!(hover && hover.ok)" in gesture_sync
    assert "band_x0: Number(band.x0 || 0)" in gesture_sync
    assert "drop_target_x: Number(drop.x || 0)" in gesture_sync
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(owner, key, payload[key]));" in gesture_sync
    assert "window.ahSetUiNodeParam(ownerId, key, payload[key]);" not in gesture_sync
    assert "const upsertGestureRelation = (targetId, relation, targetPortId) =>" in gesture_sync
    assert "relation_wire_family: 'canvas_gesture'" in gesture_sync
    assert "wire_family: 'canvas_gesture'" in gesture_sync
    assert "behavior: 'drive-canvas-gesture'" in gesture_sync
    assert "presentation: 'gesture-relation'" in gesture_sync
    assert "provenance: 'runtime:syncGrandMapCanvasGestureState'" in gesture_sync
    assert "upsertGestureRelation(payload.wire_drag_source_node_id, 'wire_drag_source'" in gesture_sync
    assert "upsertGestureRelation(payload.wire_drag_hover_node_id, 'wire_drag_hover'" in gesture_sync
    assert "gesture_relation_node_ids: Array.from(liveWireNodeIds)" in gesture_sync
    assert "try { syncGrandMapCanvasGestureState({ wireDrag, bandRect, dropTarget }); } catch (_e) {}" in node_canvas


def test_canvas_node_positions_sync_to_node_params():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    position_sync = jsx[
        jsx.index("const syncGrandMapCanvasNodePositionState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasNodePositionState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasNodePositionState = (positions, nodes) =>" in position_sync
    assert "node.x = entry.x;" in position_sync
    assert "node.y = entry.y;" in position_sync
    assert "position_node: true" in position_sync
    assert "canvas_x: entry.x" in position_sync
    assert "canvas_y: entry.y" in position_sync
    assert "position: { x: entry.x, y: entry.y }" in position_sync
    assert "materializeGrandMapParamNode(entry.id, 'x', entry.x);" in position_sync
    assert "materializeGrandMapParamNode(entry.id, 'y', entry.y);" in position_sync
    assert "materializeGrandMapParamNode(entry.id, 'position', { x: entry.x, y: entry.y });" in position_sync
    assert "window.ahSetUiNodeParam(entry.id, 'x', entry.x);" not in position_sync
    assert "window.ahSetUiNodeParam(entry.id, 'y', entry.y);" not in position_sync
    assert "window.ahSetUiNodeParam(entry.id, 'position', { x: entry.x, y: entry.y });" not in position_sync
    assert "const paramId = _uiParamNodeId(entry.id, key);" in position_sync
    assert "position_param_node_ids: positionParamNodeIds" in position_sync
    assert "['positioned_node_ids', entries.map(e => e.id)]" in position_sync
    assert "['positioned_node_count', entries.length]" in position_sync
    assert "setGrandMapInlineNodeField(owner, key, value)" in position_sync
    assert "window.ahSetUiNodeParam('ui:grandmap:canvas-shell', 'positioned_node_ids', entries.map(e => e.id));" not in position_sync
    assert "try { syncGrandMapCanvasNodePositionState(positions, persistentCanvasNodes); } catch (_e) {}" in node_canvas


def test_canvas_expansion_state_keeps_node_params_and_inline_shell_state():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    expansion_sync = jsx[
        jsx.index("const syncGrandMapCanvasExpansionState ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const syncGrandMapCanvasExpansionState ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const syncGrandMapCanvasExpansionState = (expanded, nodes, groups) =>" in expansion_sync
    assert "const expandedNodeIds = canvasNodes" in expansion_sync
    assert "const collapsedGroupIds = (groups || [])" in expansion_sync
    assert "card_expanded: isExpanded" in expansion_sync
    assert "materializeGrandMapParamNode(sourceNode.id, 'card_expanded', isExpanded);" in expansion_sync
    assert "window.ahSetUiNodeParam(sourceNode.id, 'card_expanded', isExpanded);" not in expansion_sync
    assert "const paramId = _uiParamNodeId(sourceNode.id, 'card_expanded');" in expansion_sync
    assert "expansion_state_node: true" in expansion_sync
    assert "expanded_node_ids: expandedNodeIds" in expansion_sync
    assert "collapsed_group_ids: collapsedGroupIds" in expansion_sync
    assert "expansion_param_node_ids: expansionParamNodeIds" in expansion_sync
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(owner, key, payload[key]));" in expansion_sync
    assert "window.ahSetUiNodeParam('ui:grandmap:canvas-shell', 'expanded_node_ids', expandedNodeIds);" not in expansion_sync
    assert "window.ahSetUiNodeParam('ui:grandmap:canvas-shell', 'collapsed_group_ids', collapsedGroupIds);" not in expansion_sync
    assert "try { syncGrandMapCanvasExpansionState(expanded, persistentCanvasNodes, LM_GRAPH.groups || []); } catch (_e) {}" in node_canvas


def test_home_shell_hydrates_home_layout_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    home = jsx[
        jsx.index("const Home ="):
        jsx.index("const SessionThumb =", jsx.index("const Home ="))
    ]

    assert (
        "const HomeShellSurface = ({ styles, top, plan, sessions, selection, content, composer, rootProps }) =>"
        in jsx
    )
    assert "const seedGrandMapHomeShellFallbackNodes = () =>" in jsx
    assert "const ensureGrandMapHomeShellNodes = () =>" in jsx
    assert "const seededRootId = seedGrandMapHomeShellFallbackNodes();" in jsx
    assert "get_grand_map_ui_surface', 'home-shell'" in jsx
    assert "fallback_home_shell: true" in jsx
    assert "<HomeShellSurface" in home
    assert "rootProps={{ style: homeShellStyle }}" in home
    assert "slot:home-shell-styles" in jsx
    assert "slot:home-shell-top" in jsx
    assert "slot:home-shell-sessions" in jsx
    assert "slot:home-shell-selection" in jsx
    assert "slot:home-shell-content" in jsx
    assert "slot:home-shell-composer" in jsx
    assert "<main className=\"ah-scroll\" style={{" not in home


def test_home_render_keeps_graph_slot_updates_out_of_inline_jsx():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    home = jsx[
        jsx.index("const Home ="):
        jsx.index("const SessionThumb =", jsx.index("const Home ="))
    ]

    assert "rootId={ensure" not in home
    assert "<HomeTopSurface" in home
    assert "<HomeSessionsHeaderSurface" in home
    assert "<HomeSessionToolbarSurface" in home
    assert "<HomeSelectionToolbarSurface" in home
    assert "<HomeEmptyStateSurface" in home
    assert "<HomeComposerBodySurface" in home


def test_home_surfaces_use_shared_surface_hook_not_local_refresh_timers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    home_surfaces = jsx[
        jsx.index("const HomeShellSurface ="):
        jsx.index("const Home =", jsx.index("const HomeShellSurface ="))
    ]

    assert home_surfaces.count("useGrandMapSurfaceRoot(") >= 7
    assert "() => ensureGrandMapHomeShellNodes()" in home_surfaces
    assert "() => ensureHomeTopUiNodes({ model: modelName, sessionCount, graph })" in home_surfaces
    assert "() => ensureGrandMapSessionsHeaderNodes({ sessionCount })" in home_surfaces
    assert "() => ensureGrandMapSessionToolbarNodes({ filter, selectMode, syncLabel })" in home_surfaces
    assert "() => ensureGrandMapSelectionToolbarNodes({ selectedCount, allVisibleSelected })" in home_surfaces
    assert "() => ensureGrandMapHomeEmptyStateNodes({ message })" in home_surfaces
    assert "() => ensureGrandMapComposerBodyNodes({ title, dragOver, attachmentCount, recording })" in home_surfaces
    assert "bumpHomeShellSurface" not in home_surfaces
    assert "bumpHomeTopSurface" not in home_surfaces
    assert "bumpHomeSessionsHeaderSurface" not in home_surfaces
    assert "bumpHomeSessionToolbarSurface" not in home_surfaces
    assert "bumpHomeSelectionToolbarSurface" not in home_surfaces
    assert "bumpHomeEmptyStateSurface" not in home_surfaces
    assert "bumpHomeComposerBodySurface" not in home_surfaces
    assert "setTimeout(() => bumpHome" not in home_surfaces


def test_home_session_cards_and_workspace_shell_keep_node_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    session_card = jsx[
        jsx.index("const SessionCard ="):
        jsx.index("const WorkspaceShellSurface =")
    ]
    workspace_shell = jsx[
        jsx.index("const WorkspaceShellSurface ="):
        jsx.index("const WorkspaceInner =")
    ]

    assert "const rootId = ensureGrandMapSessionCardNodes(" not in session_card
    assert "const rootId = ensureGrandMapWorkspaceShellNodes()" not in workspace_shell
    assert "() => ensureGrandMapSessionCardNodes(s, { selectMode, isSelected })" in session_card
    assert "ah-session-card-wrap" not in session_card
    assert "slot:session-card-menu:' + sid" in session_card
    assert "() => ensureGrandMapWorkspaceShellNodes()" in workspace_shell


def test_workspace_header_keeps_node_surface_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ws_header = jsx[jsx.index("const WsHeader ="):jsx.index("const smallBtn =")]

    assert "const CanvasHomeActionsSurface = () =>" in jsx
    assert "const CanvasModelPickerSurface = ({ modelLabel }) =>" in jsx
    assert "const CanvasNewSessionActionSurface = () =>" in jsx
    assert "const CanvasSessionActionsSurface = () =>" in jsx
    assert "const CanvasSessionTabSurface = ({ session, isActive }) =>" in jsx
    assert "ensureGrandMapCanvasHomeActionsNodes()" not in ws_header
    assert "ensureGrandMapCanvasModelPickerNodes({" not in ws_header
    assert "ensureGrandMapCanvasNewSessionActionNodes()" not in ws_header
    assert "ensureGrandMapCanvasSessionActionsNodes()" not in ws_header
    assert "ensureGrandMapCanvasSessionTabNodes(s, { isActive: a })" not in ws_header
    assert "fallback=" not in ws_header
    assert "<WsTab" not in ws_header
    assert "const WsTab =" not in jsx
    assert "const HoverBtn =" not in jsx
    assert "<ModelStrip" not in ws_header
    assert "HoverBtn onClick={onFork}" not in ws_header
    assert "<CanvasHomeActionsSurface" in ws_header
    assert "<CanvasModelPickerSurface" in ws_header
    assert "<CanvasNewSessionActionSurface" in ws_header
    assert "<CanvasSessionActionsSurface" in ws_header
    assert "<CanvasSessionTabSurface" in ws_header


def test_canvas_toolbar_and_composer_keep_node_surface_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    canvas_toolbar = jsx[
        jsx.index("const CanvasToolbar ="):
        jsx.index("const toolBtn =")
    ]
    floating_composer = jsx[
        jsx.index("const FloatingComposer ="):
        jsx.index("const MiniMap =", jsx.index("const FloatingComposer ="))
    ]

    assert "const CanvasToolbarSurface = ({ zoomPercent }) =>" in jsx
    assert "const CanvasToolbarSurface = ({ zoomPercent, fallback }) =>" not in jsx
    assert "const CanvasComposerBodySurface = ({ text, dragOver, attachmentCount, recording, mode }) =>" in jsx
    assert "const CanvasComposerBodySurface = ({ text, dragOver, attachmentCount, recording, mode, fallback }) =>" not in jsx
    assert "const CanvasComposerHelpSurface = () =>" in jsx
    assert "const CanvasComposerHelpSurface = ({ fallback }) =>" not in jsx
    assert "rootId={ensureGrandMapCanvasToolbarNodes({" not in canvas_toolbar
    assert "rootId={ensureGrandMapCanvasComposerBodyNodes({" not in floating_composer
    assert "rootId={ensureGrandMapCanvasComposerHelpNodes()}" not in floating_composer
    assert "<CanvasToolbarSurface" in canvas_toolbar
    assert "<CanvasComposerBodySurface" in floating_composer
    assert "<CanvasComposerHelpSurface" in floating_composer


def test_canvas_toolbar_and_composer_actions_route_through_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    canvas_toolbar = jsx[
        jsx.index("const CanvasToolbar ="):
        jsx.index("const toolBtn =")
    ]
    floating_composer = jsx[
        jsx.index("const FloatingComposer ="):
        jsx.index("const MiniMap =", jsx.index("const FloatingComposer ="))
    ]

    assert "registerUiHostCapability('canvas.toolbar.zoom.in'" in canvas_toolbar
    assert "registerUiHostCapability('canvas.toolbar.zoom.out'" in canvas_toolbar
    assert "registerUiHostCapability('canvas.toolbar.fit'" in canvas_toolbar
    assert "registerUiHostCapability('canvas.toolbar.run'" in canvas_toolbar
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in canvas_toolbar

    assert "registerUiHostCapability('canvas.composer.attach'" in floating_composer
    assert "registerUiHostCapability('canvas.composer.voice.toggle'" in floating_composer
    assert "registerUiHostCapability('canvas.composer.mode.set'" in floating_composer
    assert "registerUiHostCapability('canvas.composer.attachments.clear'" in floating_composer
    assert "registerUiHostCapability('canvas.composer.submit'" in floating_composer
    assert "registerUiHostCapability('canvas.composer.text.update'" in floating_composer
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in floating_composer
    assert "setText(value);" in floating_composer


def test_node_output_and_context_menu_actions_route_through_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    output_body = jsx[
        jsx.index("const OutputBody = ({ n }) =>"):
        jsx.index("const StagePreview =", jsx.index("const OutputBody = ({ n }) =>"))
    ]
    node_menu = jsx[
        jsx.index("const NodeMenu ="):
        jsx.index("const WireMenu =", jsx.index("const NodeMenu ="))
    ]
    wire_menu = jsx[
        jsx.index("const WireMenu ="):
        jsx.index("const WireFieldPicker =", jsx.index("const WireMenu ="))
    ]
    canvas_menu = jsx[
        jsx.index("const CanvasMenu ="):
        jsx.index("const CanvasNodeCardHeaderSurface =", jsx.index("const CanvasMenu ="))
    ]

    assert "registerUiHostCapability('node-output.preview.toggle'" in output_body
    assert "registerUiHostCapability('node-output.save'" in output_body
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in output_body

    assert "registerUiHostCapability('node.menu.run'" in node_menu
    assert "registerUiHostCapability('node.menu.delete'" in node_menu
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in node_menu

    assert "registerUiHostCapability('wire.menu.toggle-gate'" in wire_menu
    assert "registerUiHostCapability('wire.menu.toggle-codec'" in wire_menu
    assert "registerUiHostCapability('wire.menu.toggle-presentation'" in wire_menu
    assert "registerUiHostCapability('wire.menu.disconnect'" in wire_menu
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in wire_menu

    assert "registerUiHostCapability('canvas.menu.add-node'" in canvas_menu
    assert "registerUiHostCapability('canvas.menu.snap.toggle'" in canvas_menu
    assert "registerUiHostCapability('canvas.menu.clear'" in canvas_menu
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in canvas_menu


def test_navigation_session_and_palette_actions_route_through_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    icon_rail = jsx[
        jsx.index("const IconRailInner ="):
        jsx.index("const IconRail = React.memo", jsx.index("const IconRailInner ="))
    ]
    chat_row = jsx[
        jsx.index("const ChatSessionRow ="):
        jsx.index("const ChatPanelShellSurface =", jsx.index("const ChatSessionRow ="))
    ]
    chats_panel = jsx[
        jsx.index("const ChatsPanel ="):
        jsx.index("const HomeSessionActionMenuSurface =", jsx.index("const ChatsPanel ="))
    ]
    chat_menu = jsx[
        jsx.index("const ChatItemMenu ="):
        jsx.index("const panelIconBtn =", jsx.index("const ChatItemMenu ="))
    ]
    workspace_header = jsx[
        jsx.index("const WsHeader ="):
        jsx.index("const smallBtn =", jsx.index("const WsHeader ="))
    ]
    nodes_panel = jsx[
        jsx.index("const NodesPanel ="):
        jsx.index("const NodesPanelMemo =", jsx.index("const NodesPanel ="))
    ]
    palette_item = jsx[
        jsx.index("const PaletteMenuItem ="):
        jsx.index("const LM_SAVED_SKILLS =", jsx.index("const PaletteMenuItem ="))
    ]

    assert "registerUiHostCapability('rail.home.open'" in icon_rail
    assert "registerUiHostCapability('rail.search.open'" in icon_rail
    assert "registerUiHostCapability('rail.share.open'" in icon_rail
    assert "registerUiHostCapability('settings.open'" in icon_rail

    assert "registerUiHostCapability('sessions.chat.row.open'" in chat_row
    assert "registerUiHostCapability('sessions.chat.row.menu.toggle'" in chat_row

    assert "registerUiHostCapability('sessions.chat.panel.menu.toggle'" in chats_panel
    assert "registerUiHostCapability('session.create'" in chats_panel
    assert "registerUiHostCapability('sessions.chat.search.update'" in chats_panel

    assert "registerUiHostCapability('sessions.menu.action'" in chat_menu
    assert "onAction && onAction(a)" in chat_menu

    assert "bindHeaderAction('canvas.session.fork'" in workspace_header
    assert "bindHeaderAction('sessions.tab.close'" in workspace_header
    assert "registerUiHostCapability(capability" in workspace_header
    assert "d.node_id === 'ui:grandmap:canvas-new-session-action'" in workspace_header
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in workspace_header

    assert "registerUiHostCapability('nodes.palette.search.update'" in nodes_panel
    assert "registerUiHostCapability('nodes.palette.sort.toggle'" in nodes_panel
    assert "registerUiHostCapability('nodes.palette.section.toggle'" in nodes_panel

    assert "registerUiHostCapability('nodes.palette.menu.item.run'" in palette_item
    assert "registerUiHostCapability('nodes.palette.skill.promote'" in palette_item
    assert "registerUiHostCapability('nodes.palette.item.add'" in palette_item
    assert "registerUiHostCapability('nodes.palette.item.pin.toggle'" in palette_item


def test_account_settings_and_status_actions_route_through_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    account_identity = jsx[
        jsx.index("const AccountIdentity ="):
        jsx.index("const AccountChip =", jsx.index("const AccountIdentity ="))
    ]
    account_chip = jsx[
        jsx.index("const AccountChip ="):
        jsx.index("const BrainChip =", jsx.index("const AccountChip ="))
    ]
    settings = jsx[
        jsx.index("const Settings ="):
        jsx.index("const ModelPickerRow =", jsx.index("const Settings ="))
    ]
    server_strip = jsx[
        jsx.index("const ServerStrip ="):
        jsx.index("const HealthStripItem =", jsx.index("const ServerStrip ="))
    ]

    assert "registerUiHostCapability('account.identity.signin'" in account_identity
    assert "ui:grandmap:account-identity" in account_identity
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in account_identity

    assert "registerUiHostCapability('account.chip.activate'" in account_chip
    assert "registerUiHostCapability('account.menu.account'" in account_chip
    assert "registerUiHostCapability('account.menu.dashboard'" in account_chip
    assert "registerUiHostCapability('account.menu.signout'" in account_chip
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in account_chip

    assert "registerUiHostCapability('settings.close'" in settings
    assert "ui:grandmap:settings-stub" in settings
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in settings

    assert "registerUiHostCapability('settings.open'" in server_strip
    assert "registerUiHostCapability('memory.open'" in server_strip
    assert "registerUiHostCapability('graph.health.open'" in server_strip
    assert "registerUiHostCapability('application.focus'" in server_strip
    assert "const fromStatusStrip = d =>" in server_strip
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in server_strip
    assert "function executeUiActionBehaviorGraph(detail)" in jsx
    assert "ensureUiHostOperationSubgraph(" in jsx


def test_context_menus_and_canvas_hint_keep_node_surface_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chat_item_menu = jsx[
        jsx.index("const ChatItemMenu ="):
        jsx.index("const panelIconBtn =")
    ]
    node_menu = jsx[
        jsx.index("const NodeMenu ="):
        jsx.index("const WireMenu =")
    ]
    wire_menu = jsx[
        jsx.index("const WireMenu ="):
        jsx.index("const WireFieldPicker =")
    ]
    canvas_hint = jsx[
        jsx.index("const CanvasHint ="):
        jsx.index("const CanvasMenu =")
    ]
    canvas_menu = jsx[
        jsx.index("const CanvasMenu ="):
        jsx.index("const _NodeRenderer_inner =")
    ]

    assert "const HomeSessionActionMenuSurface = ({ rootProps }) =>" in jsx
    assert "const HomeSessionActionMenuSurface = ({ fallback" not in jsx
    assert "const NodeContextMenuSurface = ({ isSubgraph, isSharedSkill, flattenable }) =>" in jsx
    assert "const NodeContextMenuSurface = ({ isSubgraph, isSharedSkill, flattenable, fallback }) =>" not in jsx
    assert "const WireContextMenuSurface = ({ dstFrozen, dstBypassed, gateBlocked, codecBase64, presentationHidden }) =>" in jsx
    assert "const WireContextMenuSurface = ({ dstFrozen, dstBypassed, fallback }) =>" not in jsx
    assert "wire.menu.toggle-gate" in wire_menu
    assert "wire.menu.toggle-codec" in wire_menu
    assert "wire.menu.toggle-presentation" in wire_menu
    assert "const seedGrandMapWireRuntimeMenuFallbackNodes = () => {" in jsx
    assert "seedGrandMapWireRuntimeMenuFallbackNodes();" in jsx
    assert "materializeGrandMapParamNode(rootId, 'children', nextChildren);" in jsx
    assert "window.ahSetUiNodeParam(rootId, 'children', nextChildren)" not in jsx
    assert "const CanvasGestureHintSurface = () =>" in jsx
    assert "const CanvasGestureHintSurface = ({ fallback }) =>" not in jsx
    assert "const CanvasContextMenuSurface = ({ snapToGrid }) =>" in jsx
    assert "const CanvasContextMenuSurface = ({ snapToGrid, fallback }) =>" not in jsx
    assert "rootId={ensureGrandMapSessionActionMenuNodes()}" not in chat_item_menu
    assert "rootId={ensureGrandMapNodeContextMenuNodes({" not in node_menu
    assert "rootId={ensureGrandMapWireContextMenuNodes({" not in wire_menu
    assert "rootId={ensureGrandMapCanvasGestureHintNodes()}" not in canvas_hint
    assert "rootId={ensureGrandMapCanvasContextMenuNodes({" not in canvas_menu
    assert "<HomeSessionActionMenuSurface" in chat_item_menu
    assert "data-chat-menu" in chat_item_menu
    assert "position:'absolute', right:0, top:'100%'" not in chat_item_menu
    assert "<NodeContextMenuSurface" in node_menu
    assert "<WireContextMenuSurface" in wire_menu
    assert "<CanvasGestureHintSurface" in canvas_hint
    assert "<CanvasContextMenuSurface" in canvas_menu


def test_canvas_node_card_surface_emits_existing_card_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_node_view", "Canvas Node View")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-node-card", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-node-card"
    assert payload["source_node_ids"] == ["ui_node_card", "canvas_node_view"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-node-card"]
    assert root["type"] == "ui.element"
    assert root["data"]["cls"] == "lm-node ah-canvas-node-card-node"
    assert root["data"]["children"] == [
        "ui:grandmap:canvas-node-card-header",
        "ui:grandmap:canvas-node-card-body",
        "ui:grandmap:canvas-node-card-sockets",
    ]
    assert nodes["ui:grandmap:canvas-node-card-header"]["data"]["render_slot"] == "slot:canvas-node-card-header"
    assert nodes["ui:grandmap:canvas-node-card-body"]["data"]["render_slot"] == "slot:canvas-node-card-body"
    assert nodes["ui:grandmap:canvas-node-card-sockets"]["data"]["render_slot"] == "slot:canvas-node-card-sockets"
    assert "param:ui:grandmap:canvas-node-card:cls" in nodes


def test_canvas_node_card_header_surface_emits_bound_category_and_action_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_node_view", "Canvas Node View")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-node-card-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-node-card-header"
    assert payload["source_node_ids"] == ["ui_node_card", "canvas_node_view"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-node-card-header"]
    assert root["type"] == "ui.element"
    assert root["data"]["cls"] == "ah-canvas-node-card-header-node"
    assert root["data"]["children"] == [
        "ui:grandmap:canvas-node-card-header-icon",
        "ui:grandmap:canvas-node-card-header-label",
        "ui:grandmap:canvas-node-card-header-spacer",
        "ui:grandmap:canvas-node-card-header-status",
        "ui:grandmap:canvas-node-card-header-actions",
    ]
    assert nodes["ui:grandmap:canvas-node-card-header-icon"]["data"]["bind"] == "slot:canvas-node-card-icon"
    assert nodes["ui:grandmap:canvas-node-card-header-label"]["data"]["bind"] == "slot:canvas-node-card-label"
    assert nodes["ui:grandmap:canvas-node-card-header-status"]["data"]["render_slot"] == "slot:canvas-node-card-status"
    assert nodes["ui:grandmap:canvas-node-card-header-actions"]["data"]["render_slot"] == "slot:canvas-node-card-actions"
    assert "slot:canvas-node-card-icon" in nodes
    assert "slot:canvas-node-card-label" in nodes
    assert "param:ui:grandmap:canvas-node-card-header:cls" in nodes


def test_canvas_node_card_body_surface_emits_bound_title_subtitle_and_detail_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_node_view", "Canvas Node View")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-node-card-body", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-node-card-body"
    assert payload["source_node_ids"] == ["ui_node_card", "canvas_node_view"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-node-card-body"]
    assert root["type"] == "ui.element"
    assert root["data"]["cls"] == "ah-canvas-node-card-body-node"
    assert root["data"]["children"] == [
        "ui:grandmap:canvas-node-card-body-title",
        "ui:grandmap:canvas-node-card-body-subtitle",
        "ui:grandmap:canvas-node-card-body-detail",
    ]
    assert nodes["ui:grandmap:canvas-node-card-body-title"]["data"]["bind"] == "slot:canvas-node-card-title"
    subtitle = nodes["ui:grandmap:canvas-node-card-body-subtitle"]["data"]
    assert subtitle["bind"] == "slot:canvas-node-card-subtitle"
    assert subtitle["hidden_bind"] == "slot:canvas-node-card-subtitle-hidden"
    assert subtitle["hidden_value"] == "true"
    assert nodes["ui:grandmap:canvas-node-card-body-detail"]["data"]["render_slot"] == "slot:canvas-node-card-detail"
    assert "slot:canvas-node-card-title" in nodes
    assert "slot:canvas-node-card-subtitle" in nodes
    assert "slot:canvas-node-card-subtitle-hidden" in nodes
    assert "param:ui:grandmap:canvas-node-card-body:cls" in nodes


def test_canvas_node_socket_surface_emits_port_dot_and_label_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_node_view", "Canvas Node View")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-node-socket", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-node-socket"
    assert payload["source_node_ids"] == ["ui_node_card", "canvas_node_view"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:canvas-node-socket"]
    assert root["type"] == "ui.element"
    assert root["data"]["cls"] == "ah-canvas-node-socket-node"
    assert root["data"]["children"] == [
        "ui:grandmap:canvas-node-socket-dot",
        "ui:grandmap:canvas-node-socket-label",
    ]
    assert root["data"]["data_attrs"]["data-lm-socket-surface"] == "1"
    dot = nodes["ui:grandmap:canvas-node-socket-dot"]["data"]
    label = nodes["ui:grandmap:canvas-node-socket-label"]["data"]
    assert dot["cls"] == "ah-canvas-node-socket-dot-node"
    assert dot["data_attrs"]["data-lm-socket-dot"] == "1"
    assert label["cls"] == "ah-canvas-node-socket-label-node"
    assert label["bind"] == "slot:canvas-node-socket-label"
    assert "slot:canvas-node-socket-label" in nodes
    assert "slot:canvas-node-socket-side" in nodes
    assert "slot:canvas-node-socket-type" in nodes
    assert "param:ui:grandmap:canvas-node-socket:cls" in nodes
    assert "param:ui:grandmap:canvas-node-socket:data_attrs" in nodes
    assert ("ui:grandmap:canvas-node-socket", "ui:grandmap:canvas-node-socket-dot") in _child_wire_pairs(payload)
    assert ("ui:grandmap:canvas-node-socket", "ui:grandmap:canvas-node-socket-label") in _child_wire_pairs(payload)


def test_canvas_node_socket_slots_wire_to_port_parameter_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    socket = jsx[
        jsx.index("const ensureGrandMapCanvasNodeSocketNodes ="):
        jsx.index("const nodeOutputBodyInstanceId =", jsx.index("const ensureGrandMapCanvasNodeSocketNodes ="))
    ]

    assert "const safeSocketKey = grandMapSafeId([side || 'socket', sockId || 'value'].join(':'));" in socket
    assert "__field_relations: [" in socket
    assert "slot: 'slot:canvas-node-socket-label'" in socket
    assert "key: 'canvas_socket_' + safeSocketKey + '_label'" in socket
    assert "behavior: 'render-port-label'" in socket
    assert "slot: 'slot:canvas-node-socket-side'" in socket
    assert "key: 'canvas_socket_' + safeSocketKey + '_side'" in socket
    assert "behavior: 'render-port-side'" in socket
    assert "slot: 'slot:canvas-node-socket-type'" in socket
    assert "key: 'canvas_socket_' + safeSocketKey + '_type'" in socket
    assert "value_type: 'schema'" in socket


def test_node_output_body_surface_emits_param_preview_and_action_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    body = grand_map_ui_surface("node-output-body", grand_map_path=grand_map)
    row = grand_map_ui_surface("node-output-param-row", grand_map_path=grand_map)

    assert body["ok"] is True
    assert body["root_id"] == "ui:grandmap:node-output-body"
    body_nodes = {node["id"]: node for node in body["nodes"]}
    root = body_nodes["ui:grandmap:node-output-body"]["data"]
    assert root["style"] == {"marginTop": 8, "display": "flex", "flexDirection": "column", "gap": 7}
    assert root["children"] == [
        "ui:grandmap:node-output-params",
        "ui:grandmap:node-output-preview",
        "ui:grandmap:node-output-preview-render",
        "ui:grandmap:node-output-actions",
    ]
    assert body_nodes["ui:grandmap:node-output-params"]["data"]["render_slot"] == "slot:node-output-params"
    preview = body_nodes["ui:grandmap:node-output-preview"]["data"]
    assert preview["bind"] == "slot:node-output-preview-text"
    assert preview["hidden_bind"] == "slot:node-output-preview-text-hidden"
    assert preview["state_bind"] == "slot:node-output-preview-state"
    render = body_nodes["ui:grandmap:node-output-preview-render"]["data"]
    assert render["render_slot"] == "slot:node-output-preview-render"
    assert render["hidden_bind"] == "slot:node-output-preview-render-hidden"
    assert render["state_bind"] == "slot:node-output-preview-state"
    assert body_nodes["ui:grandmap:node-output-preview-action"]["data"]["action"] == "node-output.preview.toggle"
    save = body_nodes["ui:grandmap:node-output-save-action"]["data"]
    assert save["action"] == "node-output.save"
    assert save["disabled_bind"] == "slot:node-output-save-disabled"

    assert row["ok"] is True
    assert row["root_id"] == "ui:grandmap:node-output-param-row"
    row_nodes = {node["id"]: node for node in row["nodes"]}
    assert row_nodes["ui:grandmap:node-output-param-row"]["data"]["children"] == [
        "ui:grandmap:node-output-param-key",
        "ui:grandmap:node-output-param-value",
    ]
    assert row_nodes["ui:grandmap:node-output-param-key"]["data"]["bind"] == "slot:node-output-param-key"
    assert row_nodes["ui:grandmap:node-output-param-value"]["data"]["bind"] == "slot:node-output-param-value"


def test_node_result_row_surface_emits_generic_result_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-result-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-result-row"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-result-row"]["data"]
    assert root["children"] == [
        "ui:grandmap:node-result-icon",
        "ui:grandmap:node-result-value",
        "ui:grandmap:node-result-ms",
    ]
    assert root["state_bind"] == "slot:node-result-state"
    assert nodes["ui:grandmap:node-result-icon"]["data"]["bind"] == "slot:node-result-icon"
    assert nodes["ui:grandmap:node-result-value"]["data"]["bind"] == "slot:node-result-value"
    assert nodes["ui:grandmap:node-result-ms"]["data"]["bind"] == "slot:node-result-ms"


def test_node_param_display_and_alert_rows_emit_generic_body_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    param = grand_map_ui_surface("node-param-display-row", grand_map_path=grand_map)
    alert = grand_map_ui_surface("node-alert-row", grand_map_path=grand_map)

    assert param["ok"] is True
    param_nodes = {node["id"]: node for node in param["nodes"]}
    assert param_nodes["ui:grandmap:node-param-display-row"]["data"]["children"] == [
        "ui:grandmap:node-param-display-key",
        "ui:grandmap:node-param-display-leader",
        "ui:grandmap:node-param-display-value",
    ]
    assert param_nodes["ui:grandmap:node-param-display-key"]["data"]["bind"] == "slot:node-param-display-key"
    assert param_nodes["ui:grandmap:node-param-display-value"]["data"]["bind"] == "slot:node-param-display-value"

    assert alert["ok"] is True
    alert_nodes = {node["id"]: node for node in alert["nodes"]}
    alert_root = alert_nodes["ui:grandmap:node-alert-row"]["data"]
    assert alert_root["state_bind"] == "slot:node-alert-state"
    assert alert_root["children"] == ["ui:grandmap:node-alert-icon", "ui:grandmap:node-alert-text"]
    assert alert_nodes["ui:grandmap:node-alert-icon"]["data"]["bind"] == "slot:node-alert-icon"
    assert alert_nodes["ui:grandmap:node-alert-text"]["data"]["bind"] == "slot:node-alert-text"


def test_node_typed_param_row_surface_emits_generic_typed_param_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-typed-param-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-typed-param-row"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-typed-param-row"]["data"]
    value_wrap = nodes["ui:grandmap:node-typed-param-value-wrap"]["data"]
    indicator = nodes["ui:grandmap:node-typed-param-indicator"]["data"]
    value = nodes["ui:grandmap:node-typed-param-value"]["data"]
    assert root["cls"] == "ah-node-typed-param-row-node"
    assert root["children"] == [
        "ui:grandmap:node-typed-param-key",
        "ui:grandmap:node-typed-param-value-wrap",
    ]
    assert nodes["ui:grandmap:node-typed-param-key"]["data"]["bind"] == "slot:node-typed-param-key"
    assert value_wrap["state_bind"] == "slot:node-typed-param-state"
    assert indicator["bind"] == "slot:node-typed-param-indicator"
    assert indicator["state_bind"] == "slot:node-typed-param-state"
    assert value["bind"] == "slot:node-typed-param-value"


def test_node_empty_message_surface_emits_generic_empty_state_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-empty-message", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-empty-message"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-empty-message"]["data"]
    assert root["cls"] == "ah-node-empty-message-node"
    assert root["bind"] == "slot:node-empty-message-text"
    assert "slot:node-empty-message-text" in nodes


def test_node_progress_row_surface_emits_generic_progress_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-progress-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-progress-row"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-progress-row"]["data"]
    assert root["state_bind"] == "slot:node-progress-state"
    assert root["children"] == [
        "ui:grandmap:node-progress-header",
        "ui:grandmap:node-progress-track",
    ]
    assert nodes["ui:grandmap:node-progress-label"]["data"]["bind"] == "slot:node-progress-label"
    assert nodes["ui:grandmap:node-progress-percent"]["data"]["bind"] == "slot:node-progress-percent"
    assert nodes["ui:grandmap:node-progress-track"]["data"]["children"] == ["ui:grandmap:node-progress-fill"]


def test_node_section_label_surface_emits_generic_label_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-section-label", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-section-label"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-section-label"]["data"]
    assert root["cls"] == "ah-node-section-label-node"
    assert root["bind"] == "slot:node-section-label-text"
    assert "slot:node-section-label-text" in nodes


def test_node_expression_preview_surface_emits_generic_expression_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-expression-preview", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-expression-preview"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-expression-preview"]["data"]
    assert root["cls"] == "ah-node-expression-preview-node"
    assert root["bind"] == "slot:node-expression-preview-text"
    assert root["state_bind"] == "slot:node-expression-preview-state"


def test_node_port_row_surface_emits_generic_port_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-port-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-port-row"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-port-row"]["data"]
    assert root["cls"] == "ah-node-port-row-node"
    assert root["state_bind"] == "slot:node-port-row-state"
    assert root["children"] == [
        "ui:grandmap:node-port-row-icon",
        "ui:grandmap:node-port-row-label",
        "ui:grandmap:node-port-row-type",
    ]
    assert nodes["ui:grandmap:node-port-row-icon"]["data"]["bind"] == "slot:node-port-row-icon"
    assert nodes["ui:grandmap:node-port-row-label"]["data"]["bind"] == "slot:node-port-row-label"
    assert nodes["ui:grandmap:node-port-row-type"]["data"]["bind"] == "slot:node-port-row-type"


def test_node_action_button_surface_emits_generic_action_button_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-action-button", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-action-button"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-action-button"]["data"]
    assert root["tag"] == "button"
    assert root["cls"] == "ah-node-action-button-node"
    assert root["bind"] == "slot:node-action-button-label"
    assert root["disabled_bind"] == "slot:node-action-button-disabled"
    assert root["state_bind"] == "slot:node-action-button-state"
    assert root["action"] == "node-action-button.press"
    assert root["args"] == {"button_id": ""}


def test_node_note_surfaces_emit_display_and_editor_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    display = grand_map_ui_surface("node-note-display", grand_map_path=grand_map)
    editor = grand_map_ui_surface("node-note-editor", grand_map_path=grand_map)

    assert display["ok"] is True
    assert display["root_id"] == "ui:grandmap:node-note-display"
    display_nodes = {node["id"]: node for node in display["nodes"]}
    display_root = display_nodes["ui:grandmap:node-note-display"]["data"]
    assert display_root["tag"] == "div"
    assert display_root["cls"] == "ah-node-note-display-node"
    assert display_root["double_action"] == "node-note-display.edit"
    assert display_root["render_slot"] == "slot:node-note-display-content"

    assert editor["ok"] is True
    assert editor["root_id"] == "ui:grandmap:node-note-editor"
    editor_nodes = {node["id"]: node for node in editor["nodes"]}
    editor_root = editor_nodes["ui:grandmap:node-note-editor"]["data"]
    assert editor_root["tag"] == "textarea"
    assert editor_root["cls"] == "ah-node-note-editor-node"
    assert editor_root["bind"] == "slot:node-note-editor-text"
    assert editor_root["action"] == "node-note-editor.change"
    assert editor_root["rows"] == 5
    assert "slot:node-note-editor-text" in editor_nodes


def test_generic_node_tile_row_output_and_icon_surfaces(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    choice = grand_map_ui_surface("node-choice-tile", grand_map_path=grand_map)
    kv = grand_map_ui_surface("node-kv-row", grand_map_path=grand_map)
    output = grand_map_ui_surface("node-output-port-row", grand_map_path=grand_map)
    icon = grand_map_ui_surface("node-icon-button", grand_map_path=grand_map)

    assert choice["ok"] is True
    choice_nodes = {node["id"]: node for node in choice["nodes"]}
    choice_root = choice_nodes["ui:grandmap:node-choice-tile"]["data"]
    assert choice_root["action"] == "node-choice-tile.press"
    assert choice_root["args"] == {"choice_id": ""}
    assert choice_root["state_bind"] == "slot:node-choice-tile-state"
    assert choice_nodes["ui:grandmap:node-choice-tile-title"]["data"]["bind"] == (
        "slot:node-choice-tile-title"
    )

    assert kv["ok"] is True
    kv_nodes = {node["id"]: node for node in kv["nodes"]}
    kv_root = kv_nodes["ui:grandmap:node-kv-row"]["data"]
    assert kv_root["children"] == ["ui:grandmap:node-kv-row-key", "ui:grandmap:node-kv-row-value"]
    assert kv_nodes["ui:grandmap:node-kv-row-value"]["data"]["bind"] == "slot:node-kv-row-value"

    assert output["ok"] is True
    output_nodes = {node["id"]: node for node in output["nodes"]}
    output_root = output_nodes["ui:grandmap:node-output-port-row"]["data"]
    assert output_root["action"] == "node-output-port-row.press"
    assert output_root["args"] == {"output_id": ""}
    assert output_nodes["ui:grandmap:node-output-port-row-type"]["data"]["bind"] == (
        "slot:node-output-port-row-type"
    )

    assert icon["ok"] is True
    icon_nodes = {node["id"]: node for node in icon["nodes"]}
    icon_root = icon_nodes["ui:grandmap:node-icon-button"]["data"]
    assert icon_root["tag"] == "button"
    assert icon_root["active_bind"] == "slot:node-icon-button-active"
    assert icon_root["action"] == "node-icon-button.press"
    assert icon_root["args"] == {"button_id": ""}


def test_markdown_block_list_surfaces_emit_render_slot_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    block = grand_map_ui_surface("node-markdown-block", grand_map_path=grand_map)
    listing = grand_map_ui_surface("node-markdown-list", grand_map_path=grand_map)
    item = grand_map_ui_surface("node-markdown-list-item", grand_map_path=grand_map)
    inline = grand_map_ui_surface("node-markdown-inline", grand_map_path=grand_map)
    link = grand_map_ui_surface("node-markdown-link", grand_map_path=grand_map)
    image = grand_map_ui_surface("node-markdown-image", grand_map_path=grand_map)

    assert block["ok"] is True
    block_nodes = {node["id"]: node for node in block["nodes"]}
    block_root = block_nodes["ui:grandmap:node-markdown-block"]["data"]
    assert block_root["cls"] == "ah-node-markdown-block-node"
    assert block_root["state_bind"] == "slot:node-markdown-block-kind"
    assert block_root["render_slot"] == "slot:node-markdown-block-content"

    assert listing["ok"] is True
    list_nodes = {node["id"]: node for node in listing["nodes"]}
    list_root = list_nodes["ui:grandmap:node-markdown-list"]["data"]
    assert list_root["tag"] == "ul"
    assert list_root["render_slot"] == "slot:node-markdown-list-items"

    assert item["ok"] is True
    item_nodes = {node["id"]: node for node in item["nodes"]}
    item_root = item_nodes["ui:grandmap:node-markdown-list-item"]["data"]
    assert item_root["tag"] == "li"
    assert item_root["render_slot"] == "slot:node-markdown-list-item-content"

    assert inline["ok"] is True
    inline_nodes = {node["id"]: node for node in inline["nodes"]}
    inline_root = inline_nodes["ui:grandmap:node-markdown-inline"]["data"]
    assert inline_root["tag"] == "span"
    assert inline_root["cls"] == "ah-node-markdown-inline-node"
    assert inline_root["bind"] == "slot:node-markdown-inline-text"
    assert inline_root["state_bind"] == "slot:node-markdown-inline-kind"

    assert link["ok"] is True
    link_nodes = {node["id"]: node for node in link["nodes"]}
    link_root = link_nodes["ui:grandmap:node-markdown-link"]["data"]
    assert link_root["tag"] == "a"
    assert link_root["cls"] == "ah-node-markdown-link-node"
    assert link_root["bind"] == "slot:node-markdown-link-text"
    assert link_root["href_bind"] == "slot:node-markdown-link-href"
    assert "slot:node-markdown-link-href" in link_nodes

    assert image["ok"] is True
    image_nodes = {node["id"]: node for node in image["nodes"]}
    image_root = image_nodes["ui:grandmap:node-markdown-image"]["data"]
    assert image_root["tag"] == "img"
    assert image_root["cls"] == "ah-node-markdown-image-node"
    assert image_root["src_bind"] == "slot:node-markdown-image-src"
    assert image_root["alt_bind"] == "slot:node-markdown-image-alt"
    assert "slot:node-markdown-image-alt" in image_nodes


def test_node_stage_preview_surface_emits_generic_preview_frame(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-stage-preview", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-stage-preview"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-stage-preview"]["data"]
    assert root["cls"] == "ah-node-stage-preview-node"
    assert root["render_slot"] == "slot:node-stage-preview-content"


def test_node_stage_preview_content_surfaces_emit_generic_content_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    image = grand_map_ui_surface("node-stage-image-preview", grand_map_path=grand_map)
    text = grand_map_ui_surface("node-stage-text-preview", grand_map_path=grand_map)
    empty = grand_map_ui_surface("node-stage-empty-preview", grand_map_path=grand_map)

    assert image["ok"] is True
    image_nodes = {node["id"]: node for node in image["nodes"]}
    image_root = image_nodes["ui:grandmap:node-stage-image-preview"]["data"]
    assert image_root["tag"] == "img"
    assert image_root["src_bind"] == "slot:node-stage-image-preview-src"
    assert image_root["alt_bind"] == "slot:node-stage-image-preview-alt"
    assert "slot:node-stage-image-preview-alt" in image_nodes

    assert text["ok"] is True
    text_nodes = {node["id"]: node for node in text["nodes"]}
    text_root = text_nodes["ui:grandmap:node-stage-text-preview"]["data"]
    assert text_root["tag"] == "div"
    assert text_root["bind"] == "slot:node-stage-text-preview-text"

    assert empty["ok"] is True
    empty_nodes = {node["id"]: node for node in empty["nodes"]}
    empty_root = empty_nodes["ui:grandmap:node-stage-empty-preview"]["data"]
    assert empty_root["tag"] == "div"
    assert empty_root["bind"] == "slot:node-stage-empty-preview-text"


def test_node_preformatted_preview_surface_emits_generic_pre_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-preformatted-preview", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-preformatted-preview"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-preformatted-preview"]["data"]
    assert root["tag"] == "pre"
    assert root["cls"] == "ah-node-preformatted-preview-node"
    assert root["bind"] == "slot:node-preformatted-preview-text"
    assert "slot:node-preformatted-preview-text" in nodes


def test_node_image_preview_surface_emits_bound_img_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-image-preview", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-image-preview"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-image-preview"]["data"]
    img = nodes["ui:grandmap:node-image-preview-img"]["data"]
    assert root["cls"] == "ah-node-image-preview-node"
    assert root["children"] == ["ui:grandmap:node-image-preview-img"]
    assert img["tag"] == "img"
    assert img["cls"] == "ah-node-image-preview-img-node"
    assert img["src_bind"] == "slot:node-image-preview-src"
    assert img["alt_bind"] == "slot:node-image-preview-alt"
    assert "slot:node-image-preview-src" in nodes
    assert "slot:node-image-preview-alt" in nodes


def test_node_list_preview_surfaces_emit_generic_list_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    preview = grand_map_ui_surface("node-list-preview", grand_map_path=grand_map)
    item = grand_map_ui_surface("node-list-preview-item", grand_map_path=grand_map)

    assert preview["ok"] is True
    assert preview["root_id"] == "ui:grandmap:node-list-preview"
    preview_nodes = {node["id"]: node for node in preview["nodes"]}
    root = preview_nodes["ui:grandmap:node-list-preview"]["data"]
    assert root["tag"] == "ul"
    assert root["cls"] == "ah-node-list-preview-node"
    assert root["render_slot"] == "slot:node-list-preview-items"

    assert item["ok"] is True
    assert item["root_id"] == "ui:grandmap:node-list-preview-item"
    item_nodes = {node["id"]: node for node in item["nodes"]}
    item_root = item_nodes["ui:grandmap:node-list-preview-item"]["data"]
    assert item_root["tag"] == "li"
    assert item_root["cls"] == "ah-node-list-preview-item-node"
    assert item_root["bind"] == "slot:node-list-preview-item-text"
    assert item_root["state_bind"] == "slot:node-list-preview-item-state"


def test_node_table_preview_surfaces_emit_generic_table_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    preview = grand_map_ui_surface("node-table-preview", grand_map_path=grand_map)
    header = grand_map_ui_surface("node-table-header-cell", grand_map_path=grand_map)
    row = grand_map_ui_surface("node-table-row", grand_map_path=grand_map)
    cell = grand_map_ui_surface("node-table-cell", grand_map_path=grand_map)

    assert preview["ok"] is True
    assert preview["root_id"] == "ui:grandmap:node-table-preview"
    preview_nodes = {node["id"]: node for node in preview["nodes"]}
    root = preview_nodes["ui:grandmap:node-table-preview"]["data"]
    table = preview_nodes["ui:grandmap:node-table-preview-table"]["data"]
    head_row = preview_nodes["ui:grandmap:node-table-preview-head-row"]["data"]
    body = preview_nodes["ui:grandmap:node-table-preview-body"]["data"]
    assert root["children"] == ["ui:grandmap:node-table-preview-table"]
    assert table["tag"] == "table"
    assert head_row["render_slot"] == "slot:node-table-preview-header"
    assert body["render_slot"] == "slot:node-table-preview-rows"

    header_nodes = {node["id"]: node for node in header["nodes"]}
    header_root = header_nodes["ui:grandmap:node-table-header-cell"]["data"]
    assert header_root["tag"] == "th"
    assert header_root["bind"] == "slot:node-table-header-cell-text"
    assert header_root["state_bind"] == "slot:node-table-header-cell-align"

    row_nodes = {node["id"]: node for node in row["nodes"]}
    row_root = row_nodes["ui:grandmap:node-table-row"]["data"]
    assert row_root["tag"] == "tr"
    assert row_root["render_slot"] == "slot:node-table-row-cells"
    assert row_root["state_bind"] == "slot:node-table-row-state"

    cell_nodes = {node["id"]: node for node in cell["nodes"]}
    cell_root = cell_nodes["ui:grandmap:node-table-cell"]["data"]
    assert cell_root["tag"] == "td"
    assert cell_root["bind"] == "slot:node-table-cell-text"
    assert cell_root["state_bind"] == "slot:node-table-cell-align"


def test_canvas_node_renderer_uses_node_card_surface_slots_not_raw_shell():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_renderer = jsx[
        jsx.index("const _NodeRenderer_inner ="):
        jsx.index("const NodeRenderer = React.memo")
    ]
    regular_path = node_renderer[
        node_renderer.index("const isAiPlan ="):
        node_renderer.index("// Custom comparator", 0)
    ]

    assert "const CanvasNodeCardSurface = ({ node, rootProps, header, body, sockets }) =>" in jsx
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeCardNodes(node) : null" in jsx
    assert "<CanvasNodeCardSurface" in regular_path
    assert "slot:canvas-node-card-header" in regular_path
    assert "slot:canvas-node-card-body" in regular_path
    assert "slot:canvas-node-card-sockets" in regular_path
    assert "const focusCanvasCard = (e) => {" in regular_path
    assert "window.__archhub_suppress_ui_focus_until = Date.now() + 250;" in regular_path
    assert "new CustomEvent('lm-focus-node'" in regular_path
    assert "detail: { node_id: n.id }" in regular_path
    assert "onClick: focusCanvasCard" in regular_path
    assert "onMouseDownCapture: (e) => {" in regular_path
    assert "onFocus && onFocus(e);" in regular_path
    assert "_nodeHandlerLatest.current = { toggleExpanded, onNodeDragStart, setFocusId, bumpGraph };" in jsx
    assert "_nodeHandlerLatest.current.bumpGraph && _nodeHandlerLatest.current.bumpGraph();" in jsx
    assert '<div className="lm-node" data-node-id={n.id} onClick={onFocus}' not in regular_path
    focus_suppressor = jsx[
        jsx.index("const uiSurfaceSuppressesFocusRoute ="):
        jsx.index("const uiFocusRouteAuthority =")
    ]
    assert "'canvas-node-card'" in focus_suppressor


def test_socket_renderer_uses_node_surface_without_losing_wire_contract():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    surface = jsx[
        jsx.index("const CanvasSocketSurface = ({"):
        jsx.index("const Socket = ({ side, i, t, label, nodeId, sockId, onMouseDown, onContextMenu, surfaceEnabled = true }) =>")
    ]
    socket = jsx[
        jsx.index("const Socket = ({ side, i, t, label, nodeId, sockId, onMouseDown, onContextMenu, surfaceEnabled = true }) =>"):
        jsx.index("// \u2500\u2500\u2500 per-category body content", jsx.index("const Socket = ({ side, i, t, label, nodeId, sockId, onMouseDown, onContextMenu, surfaceEnabled = true }) =>"))
    ]

    assert "surfaceEnabled ? ensureGrandMapCanvasNodeSocketNodes(nodeId, side, sockId, label, t) : null" in surface
    assert 'surface="canvas-node-socket"' in surface
    assert "rootProps={rootProps}" in surface
    assert "'data-lm-socket': `${side}:${nodeId}:${sockId}`" in surface
    assert "'data-side': side" in surface
    assert "'data-node': nodeId" in surface
    assert "'data-pin': sockId" in surface
    assert "'data-type': t" in surface
    assert "onMouseDown" in surface
    assert "onContextMenu" in surface
    assert "data-lm-socket-dot=\"1\"" in surface
    assert ".ah-canvas-node-socket-node" in surface
    assert "pointerEvents:'auto'" in surface
    assert "cursor:'crosshair'" in surface
    assert "<CanvasSocketSurface" in socket
    assert "surfaceEnabled={surfaceEnabled}" in socket
    focus_suppressor = jsx[
        jsx.index("const uiSurfaceSuppressesFocusRoute ="):
        jsx.index("const uiFocusRouteAuthority =")
    ]
    assert "'canvas-node-socket'" in focus_suppressor
    assert "bridgeAsync('get_grand_map_ui_surface', 'canvas-node-socket')" in jsx


def test_output_body_uses_node_surfaces_for_preview_and_save_controls():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    output_body = jsx[
        jsx.index("const OutputBody = ({ n }) =>"):
        jsx.index("// Audit 2026-06-02", jsx.index("const OutputBody = ({ n }) =>"))
    ]

    assert "const NodeOutputBodySurface = ({ node, showPreview, saving, hasOutput, previewText, paramsSlot, previewSlot }) =>" in jsx
    assert "const NodeOutputParamRowSurface = ({ nodeId, p }) =>" in jsx
    assert "const NodeOutputTypedPreviewSurface = ({ node, value, kind }) =>" in jsx
    assert "const nodeOutputPreviewKind = (n, val) =>" in jsx
    assert "const normalizeGrandMapNodeOutputBodyTypedPreviewNodes = (sid, slotMap) =>" in jsx
    assert "root.data.children.splice(previewIndex + 1, 0, renderId);" in jsx
    assert "hidden_bind: textHiddenSlot" in jsx
    assert "render_slot: renderSlot" in jsx
    assert "normalizeGrandMapNodeOutputBodyTypedPreviewNodes(sid, slotMap);" in jsx
    assert "get_grand_map_ui_surface', 'node-output-body'" in jsx
    assert "get_grand_map_ui_surface', 'node-output-param-row'" in jsx
    assert "node-output.preview.toggle" in jsx
    assert "node-output.save" in jsx
    assert "save_node_output" in output_body
    assert "const previewKind = hasOutput ? nodeOutputPreviewKind(n, value) : 'text';" in output_body
    assert "<NodeOutputTypedPreviewSurface node={n} value={value} kind={previewKind}/>" in output_body
    assert "previewSlot={typedPreview}" in output_body
    assert "<NodeOutputBodySurface" in output_body
    assert "'data-typed-preview': hasTypedPreview ? 'true' : 'false'" in jsx
    assert "data-fallback-render-slot=\"slot:node-output-preview-render\"" in jsx
    assert "!typedRenderNodeReady" in jsx
    assert "<NodeOutputParamRowSurface key={p.k} nodeId={nodeId} p={p}/>" in output_body
    assert "style={smallBtn" not in output_body
    assert "onClick={() => setShowPreview" not in output_body
    assert "<div onClick={e => e.stopPropagation()} style={{ marginTop:8" not in output_body


def test_node_output_body_slots_wire_to_output_parameter_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    output_nodes = jsx[
        jsx.index("const ensureGrandMapNodeOutputBodyNodes ="):
        jsx.index("const ensureGrandMapNodeOutputParamRowNodes =", jsx.index("const ensureGrandMapNodeOutputBodyNodes ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="):
        jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes =", jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="))
    ]
    normalizer = jsx[
        jsx.index("const normalizeGrandMapNodeOutputBodyTypedPreviewNodes ="):
        jsx.index("const ensureGrandMapNodeOutputBodyNodes =", jsx.index("const normalizeGrandMapNodeOutputBodyTypedPreviewNodes ="))
    ]

    assert "__field_relations: [" in output_nodes
    assert "slot: 'slot:node-output-preview-hidden'" in output_nodes
    assert "key: 'node_output_preview_hidden'" in output_nodes
    assert "slot: 'slot:node-output-preview-text-hidden'" in output_nodes
    assert "key: 'node_output_preview_text_hidden'" in output_nodes
    assert "slot: 'slot:node-output-preview-render-hidden'" in output_nodes
    assert "key: 'node_output_preview_render_hidden'" in output_nodes
    assert "slot: 'slot:node-output-preview-state'" in output_nodes
    assert "key: 'node_output_preview_state'" in output_nodes
    assert "slot: 'slot:node-output-preview-text'" in output_nodes
    assert "key: 'node_output_preview_text'" in output_nodes
    assert "slot: 'slot:node-output-preview-action-label'" in output_nodes
    assert "key: 'node_output_preview_action_label'" in output_nodes
    assert "slot: 'slot:node-output-save-label'" in output_nodes
    assert "key: 'node_output_save_label'" in output_nodes
    assert "slot: 'slot:node-output-save-disabled'" in output_nodes
    assert "key: 'node_output_save_disabled'" in output_nodes
    assert "presentation: 'node-output-preview'" in output_nodes
    assert "presentation: 'node-output-actions'" in output_nodes
    assert "slotMap.__field_relations" in clone
    assert "syncUiSlotParameterRelation(mapId(entry.slot), entry.owner_node_id, entry.key, entry.value" in clone
    assert "const mappedSlotMap = {};" in normalizer
    assert "mappedSlotMap[mappedId] = slotMap[id];" in normalizer
    assert "syncGrandMapMappedSurfaceState('node-output-body', sid, rootId, mappedSlotMap" in normalizer
    assert "state_key: 'node_output_body_state_node_id'" in normalizer


def test_node_output_param_and_port_rows_wire_visible_slots_to_parameters():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    param_row = jsx[
        jsx.index("const ensureGrandMapNodeOutputParamRowNodes ="):
        jsx.index("const nodeNoteEditorInstanceId =", jsx.index("const ensureGrandMapNodeOutputParamRowNodes ="))
    ]
    port_row = jsx[
        jsx.index("const ensureGrandMapNodeOutputPortRowNodes ="):
        jsx.index("const nodeIconButtonInstanceId =", jsx.index("const ensureGrandMapNodeOutputPortRowNodes ="))
    ]

    assert "const safeOutputParamKey = grandMapSafeId(outputParamKey);" in param_row
    assert "__field_relations: [" in param_row
    assert "slot: 'slot:node-output-param-key'" in param_row
    assert "key: 'node_output_param_key_' + safeOutputParamKey" in param_row
    assert "slot: 'slot:node-output-param-value'" in param_row
    assert "key: outputParamKey" in param_row
    assert "surface: 'node-output-param-row'" in param_row
    assert "value_type: p.type || typeof p.v" in param_row

    assert "const safePortKey = grandMapSafeId(portKey);" in port_row
    assert "__field_relations: [" in port_row
    assert "slot: 'slot:node-output-port-row-key'" in port_row
    assert "key: 'node_output_port_' + safePortKey + '_key'" in port_row
    assert "slot: 'slot:node-output-port-row-description'" in port_row
    assert "key: 'node_output_port_' + safePortKey + '_description'" in port_row
    assert "slot: 'slot:node-output-port-row-type'" in port_row
    assert "key: 'node_output_port_' + safePortKey + '_type'" in port_row
    assert "slot: 'slot:node-output-port-row-state'" in port_row
    assert "key: 'node_output_port_' + safePortKey + '_state'" in port_row
    assert "surface: 'node-output-port-row'" in port_row


def test_choice_kv_and_icon_surfaces_wire_visible_slots_to_parameters():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    choice = jsx[
        jsx.index("const ensureGrandMapNodeChoiceTileNodes ="):
        jsx.index("const nodeKvRowInstanceId =", jsx.index("const ensureGrandMapNodeChoiceTileNodes ="))
    ]
    kv = jsx[
        jsx.index("const ensureGrandMapNodeKvRowNodes ="):
        jsx.index("const nodeOutputPortRowInstanceId =", jsx.index("const ensureGrandMapNodeKvRowNodes ="))
    ]
    icon = jsx[
        jsx.index("const ensureGrandMapNodeIconButtonNodes ="):
        jsx.index("const nodeMarkdownBlockInstanceId =", jsx.index("const ensureGrandMapNodeIconButtonNodes ="))
    ]

    assert "const safeChoiceKey = grandMapSafeId(choiceKey);" in choice
    assert "__field_relations: [" in choice
    assert "slot: 'slot:node-choice-tile-title'" in choice
    assert "key: 'node_choice_' + safeChoiceKey + '_title'" in choice
    assert "slot: 'slot:node-choice-tile-subtitle'" in choice
    assert "key: 'node_choice_' + safeChoiceKey + '_subtitle'" in choice
    assert "slot: 'slot:node-choice-tile-status'" in choice
    assert "key: 'node_choice_' + safeChoiceKey + '_status'" in choice
    assert "slot: 'slot:node-choice-tile-state'" in choice
    assert "key: 'node_choice_' + safeChoiceKey + '_state'" in choice

    assert "const safeKvKey = grandMapSafeId(kvKey);" in kv
    assert "__field_relations: [" in kv
    assert "slot: 'slot:node-kv-row-key'" in kv
    assert "key: 'node_kv_' + safeKvKey + '_key'" in kv
    assert "slot: 'slot:node-kv-row-value'" in kv
    assert "key: 'node_kv_' + safeKvKey + '_value'" in kv
    assert "slot: 'slot:node-kv-row-state'" in kv
    assert "key: 'node_kv_' + safeKvKey + '_state'" in kv

    assert "const safeButtonKey = grandMapSafeId(buttonKey);" in icon
    assert "__field_relations: [" in icon
    assert "slot: 'slot:node-icon-button-icon'" in icon
    assert "key: 'node_icon_button_' + safeButtonKey + '_icon'" in icon
    assert "slot: 'slot:node-icon-button-label'" in icon
    assert "key: 'node_icon_button_' + safeButtonKey + '_label'" in icon
    assert "slot: 'slot:node-icon-button-active'" in icon
    assert "key: 'node_icon_button_' + safeButtonKey + '_active'" in icon


def test_markdown_surfaces_wire_visible_content_to_parameter_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    block = jsx[
        jsx.index("const ensureGrandMapNodeMarkdownBlockNodes ="):
        jsx.index("const nodeMarkdownListInstanceId =", jsx.index("const ensureGrandMapNodeMarkdownBlockNodes ="))
    ]
    inline = jsx[
        jsx.index("const ensureGrandMapNodeMarkdownInlineNodes ="):
        jsx.index("const nodeMarkdownLinkInstanceId =", jsx.index("const ensureGrandMapNodeMarkdownInlineNodes ="))
    ]
    link = jsx[
        jsx.index("const ensureGrandMapNodeMarkdownLinkNodes ="):
        jsx.index("const nodeMarkdownImageInstanceId =", jsx.index("const ensureGrandMapNodeMarkdownLinkNodes ="))
    ]
    image = jsx[
        jsx.index("const ensureGrandMapNodeMarkdownImageNodes ="):
        jsx.index("const ensureGrandMapCanvasHomeActionsNodes =", jsx.index("const ensureGrandMapNodeMarkdownImageNodes ="))
    ]
    components = jsx[
        jsx.index("const NodeMarkdownLinkSurface ="):
        jsx.index("const ReadBody =", jsx.index("const NodeMarkdownLinkSurface ="))
    ]

    assert "const safeRowKey = grandMapSafeId(rowKey);" in block
    assert "__field_relations: [" in block
    assert "slot: 'slot:node-markdown-block-kind'" in block
    assert "key: 'node_markdown_block_' + safeRowKey + '_kind'" in block

    assert "__field_relations: [" in inline
    assert "slot: 'slot:node-markdown-inline-text'" in inline
    assert "key: 'node_markdown_inline_' + safeRowKey + '_text'" in inline
    assert "slot: 'slot:node-markdown-inline-kind'" in inline
    assert "key: 'node_markdown_inline_' + safeRowKey + '_kind'" in inline

    assert "__field_relations: [" in link
    assert "'slot:node-markdown-link-href': slots && slots.url != null ? String(slots.url) : ''" in link
    assert "slot: 'slot:node-markdown-link-text'" in link
    assert "key: 'node_markdown_link_' + safeRowKey + '_text'" in link
    assert "slot: 'slot:node-markdown-link-href'" in link
    assert "key: 'node_markdown_link_' + safeRowKey + '_href'" in link

    assert "__field_relations: [" in image
    assert "'slot:node-markdown-image-alt': slots && slots.alt != null ? String(slots.alt) : 'markdown image'" in image
    assert "slot: 'slot:node-markdown-image-src'" in image
    assert "key: 'node_markdown_image_' + safeRowKey + '_src'" in image
    assert "slot: 'slot:node-markdown-image-alt'" in image
    assert "key: 'node_markdown_image_' + safeRowKey + '_alt'" in image

    assert "ensureGrandMapNodeMarkdownLinkNodes(nodeId, { rowId, text, url })" in components
    assert 'rootProps={{ target: "_blank", rel: "noopener noreferrer" }}' in components
    assert "ensureGrandMapNodeMarkdownImageNodes(nodeId, { rowId, src, alt })" in components
    assert 'rootProps={{ alt: alt || "markdown image" }}' not in components


def test_preview_surfaces_wire_visible_content_to_parameter_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    stage_image = jsx[
        jsx.index("const ensureGrandMapNodeStageImagePreviewNodes ="):
        jsx.index("const nodeStageTextPreviewInstanceId =", jsx.index("const ensureGrandMapNodeStageImagePreviewNodes ="))
    ]
    stage_text = jsx[
        jsx.index("const ensureGrandMapNodeStageTextPreviewNodes ="):
        jsx.index("const nodeStageEmptyPreviewInstanceId =", jsx.index("const ensureGrandMapNodeStageTextPreviewNodes ="))
    ]
    stage_empty = jsx[
        jsx.index("const ensureGrandMapNodeStageEmptyPreviewNodes ="):
        jsx.index("const nodePreformattedPreviewInstanceId =", jsx.index("const ensureGrandMapNodeStageEmptyPreviewNodes ="))
    ]
    pre = jsx[
        jsx.index("const ensureGrandMapNodePreformattedPreviewNodes ="):
        jsx.index("const nodeImagePreviewInstanceId =", jsx.index("const ensureGrandMapNodePreformattedPreviewNodes ="))
    ]
    image = jsx[
        jsx.index("const ensureGrandMapNodeImagePreviewNodes ="):
        jsx.index("const nodeListPreviewInstanceId =", jsx.index("const ensureGrandMapNodeImagePreviewNodes ="))
    ]
    list_item = jsx[
        jsx.index("const ensureGrandMapNodeListPreviewItemNodes ="):
        jsx.index("const nodeTablePreviewInstanceId =", jsx.index("const ensureGrandMapNodeListPreviewItemNodes ="))
    ]
    header = jsx[
        jsx.index("const ensureGrandMapNodeTableHeaderCellNodes ="):
        jsx.index("const nodeTableRowInstanceId =", jsx.index("const ensureGrandMapNodeTableHeaderCellNodes ="))
    ]
    row = jsx[
        jsx.index("const ensureGrandMapNodeTableRowNodes ="):
        jsx.index("const nodeTableCellInstanceId =", jsx.index("const ensureGrandMapNodeTableRowNodes ="))
    ]
    cell = jsx[
        jsx.index("const ensureGrandMapNodeTableCellNodes ="):
        jsx.index("const nodeNoteDisplayInstanceId =", jsx.index("const ensureGrandMapNodeTableCellNodes ="))
    ]

    assert "__field_relations: [" in stage_image
    assert "slot: 'slot:node-stage-image-preview-src'" in stage_image
    assert "key: 'node_stage_image_preview_src'" in stage_image
    assert "slot: 'slot:node-stage-image-preview-alt'" in stage_image
    assert "key: 'node_stage_image_preview_alt'" in stage_image

    assert "__field_relations: [" in stage_text
    assert "slot: 'slot:node-stage-text-preview-text'" in stage_text
    assert "key: 'node_stage_text_preview_text'" in stage_text

    assert "__field_relations: [" in stage_empty
    assert "slot: 'slot:node-stage-empty-preview-text'" in stage_empty
    assert "key: 'node_stage_empty_preview_text'" in stage_empty

    assert "__field_relations: [" in pre
    assert "key: 'node_preformatted_preview_' + safeRowKey + '_text'" in pre

    assert "__field_relations: [" in image
    assert "slot: 'slot:node-image-preview-src'" in image
    assert "key: 'node_image_preview_' + safeRowKey + '_src'" in image
    assert "slot: 'slot:node-image-preview-alt'" in image
    assert "key: 'node_image_preview_' + safeRowKey + '_alt'" in image

    assert "__field_relations: [" in list_item
    assert "key: 'node_list_preview_item_' + safeRowKey + '_text'" in list_item
    assert "key: 'node_list_preview_item_' + safeRowKey + '_state'" in list_item

    assert "__field_relations: [" in header
    assert "key: 'node_table_header_cell_' + safeRowKey + '_text'" in header
    assert "key: 'node_table_header_cell_' + safeRowKey + '_align'" in header

    assert "__field_relations: [" in row
    assert "key: 'node_table_row_' + safeRowKey + '_state'" in row

    assert "__field_relations: [" in cell
    assert "key: 'node_table_cell_' + safeRowKey + '_text'" in cell
    assert "key: 'node_table_cell_' + safeRowKey + '_align'" in cell


def test_generic_row_and_control_surfaces_wire_visible_fields_to_parameters():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    result = jsx[
        jsx.index("const ensureGrandMapNodeResultRowNodes ="):
        jsx.index("const nodeParamDisplayRowInstanceId =", jsx.index("const ensureGrandMapNodeResultRowNodes ="))
    ]
    param = jsx[
        jsx.index("const ensureGrandMapNodeParamDisplayRowNodes ="):
        jsx.index("const nodeTypedParamRowInstanceId =", jsx.index("const ensureGrandMapNodeParamDisplayRowNodes ="))
    ]
    typed = jsx[
        jsx.index("const ensureGrandMapNodeTypedParamRowNodes ="):
        jsx.index("const nodeAlertRowInstanceId =", jsx.index("const ensureGrandMapNodeTypedParamRowNodes ="))
    ]
    alert = jsx[
        jsx.index("const ensureGrandMapNodeAlertRowNodes ="):
        jsx.index("const nodeEmptyMessageInstanceId =", jsx.index("const ensureGrandMapNodeAlertRowNodes ="))
    ]
    empty = jsx[
        jsx.index("const ensureGrandMapNodeEmptyMessageNodes ="):
        jsx.index("const nodeProgressRowInstanceId =", jsx.index("const ensureGrandMapNodeEmptyMessageNodes ="))
    ]
    progress = jsx[
        jsx.index("const ensureGrandMapNodeProgressRowNodes ="):
        jsx.index("const nodeSectionLabelInstanceId =", jsx.index("const ensureGrandMapNodeProgressRowNodes ="))
    ]
    section = jsx[
        jsx.index("const ensureGrandMapNodeSectionLabelNodes ="):
        jsx.index("const nodeExpressionPreviewInstanceId =", jsx.index("const ensureGrandMapNodeSectionLabelNodes ="))
    ]
    expression = jsx[
        jsx.index("const ensureGrandMapNodeExpressionPreviewNodes ="):
        jsx.index("const nodePortRowInstanceId =", jsx.index("const ensureGrandMapNodeExpressionPreviewNodes ="))
    ]
    port = jsx[
        jsx.index("const ensureGrandMapNodePortRowNodes ="):
        jsx.index("const nodeActionButtonInstanceId =", jsx.index("const ensureGrandMapNodePortRowNodes ="))
    ]
    action = jsx[
        jsx.index("const ensureGrandMapNodeActionButtonNodes ="):
        jsx.index("const nodeStagePreviewInstanceId =", jsx.index("const ensureGrandMapNodeActionButtonNodes ="))
    ]

    assert "__field_relations: [" in result
    assert "key: 'node_result_' + safeRowKey + '_value'" in result
    assert "value_type: 'data'" in result
    assert "key: 'node_result_' + safeRowKey + '_state'" in result

    assert "__field_relations: [" in param
    assert "const safeParamKey = grandMapSafeId(paramKey);" in param
    assert "key: 'node_param_display_' + safeParamKey + '_key'" in param
    assert "key: paramKey" in param
    assert "behavior: 'render-parameter-value'" in param

    assert "__field_relations: [" in typed
    assert "key: 'node_typed_param_' + safeParamKey + '_key'" in typed
    assert "key: paramKey" in typed
    assert "key: 'node_typed_param_' + safeParamKey + '_indicator'" in typed
    assert "key: 'node_typed_param_' + safeParamKey + '_state'" in typed

    assert "__field_relations: [" in alert
    assert "key: 'node_alert_' + safeRowKey + '_text'" in alert
    assert "key: 'node_alert_' + safeRowKey + '_state'" in alert

    assert "__field_relations: [" in empty
    assert "key: 'node_empty_message_' + safeRowKey + '_text'" in empty

    assert "__field_relations: [" in progress
    assert "key: 'node_progress_' + safeRowKey + '_percent'" in progress
    assert "value_type: 'percentage'" in progress

    assert "__field_relations: [" in section
    assert "key: 'node_section_label_' + safeRowKey + '_text'" in section

    assert "__field_relations: [" in expression
    assert "key: 'node_expression_preview_' + safeRowKey + '_text'" in expression
    assert "value_type: 'logic'" in expression

    assert "__field_relations: [" in port
    assert "key: 'node_port_row_' + safeRowKey + '_label'" in port
    assert "value_type: 'schema'" in port

    assert "__field_relations: [" in action
    assert "key: 'node_action_button_' + safeRowKey + '_disabled'" in action
    assert "value_type: 'boolean'" in action
    assert "__action_args: { button_id: buttonId }" in action


def test_cloned_surfaces_auto_wire_owned_slots_to_parameters():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="):
        jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes =", jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="))
    ]
    note_editor = jsx[
        jsx.index("const ensureGrandMapNodeNoteEditorNodes ="):
        jsx.index("const nodeChoiceTileInstanceId =", jsx.index("const ensureGrandMapNodeNoteEditorNodes ="))
    ]

    assert "const slotFieldRelationEntries = (Array.isArray(slotMap && slotMap.__field_relations) ? slotMap.__field_relations : []).slice();" in clone
    assert "const autoOwnerNodeId = slotMap && slotMap.__owner_node_id ? String(slotMap.__owner_node_id) : '';" in clone
    assert "if (autoOwnerNodeId) {" in clone
    assert "explicitSlotRelationSlots.has(slotId)" in clone
    assert "key: prefix + '_' + grandMapSafeId(slotName)" in clone
    assert "behavior: 'render-slot'" in clone

    assert "__owner_node_id: nodeId" in note_editor
    assert "__slot_param_prefix: 'node_note_editor'" in note_editor
    assert "'slot:node-note-editor-text': slots && slots.text != null ? String(slots.text) : ''" in note_editor


def test_read_body_uses_generic_node_result_row_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    read_body = jsx[
        jsx.index("const ReadBody = ({ n }) =>"):
        jsx.index("const FilterBody =", jsx.index("const ReadBody = ({ n }) =>"))
    ]

    assert "const NodeResultRowSurface = ({ nodeId, rowId, icon, result, ms, state }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-result-row'" in jsx
    assert "<NodeResultRowSurface" in read_body
    assert "result={n.result}" in read_body
    assert "ms={n.ms}" in read_body
    assert "<div style={{ marginTop:7, fontFamily:LM.mono" not in read_body


def test_filter_and_logic_bodies_reuse_generic_node_result_row_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    filter_body = jsx[
        jsx.index("const FilterBody = ({ n }) =>"):
        jsx.index("// Transform body", jsx.index("const FilterBody = ({ n }) =>"))
    ]
    logic_body = jsx[
        jsx.index("const LogicBody = ({ n }) =>"):
        jsx.index("// Compose body", jsx.index("const LogicBody = ({ n }) =>"))
    ]

    assert "<NodeResultRowSurface" in filter_body
    assert "<NodeSectionLabelSurface" in filter_body
    assert "<NodeExpressionPreviewSurface" in filter_body
    assert 'rowId="filter"' in filter_body
    assert 'rowId="predicate"' in filter_body
    assert 'state="filter"' in filter_body
    assert "<NodeResultRowSurface" in logic_body
    assert "<NodeSectionLabelSurface" in logic_body
    assert "<NodeExpressionPreviewSurface" in logic_body
    assert 'rowId="logic"' in logic_body
    assert 'rowId="predicate"' in logic_body
    assert 'state="logic"' in logic_body
    assert "const NodeExpressionPreviewSurface = ({ nodeId, rowId, text, state }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-expression-preview'" in jsx
    assert ">predicate</div>" not in filter_body
    assert ">predicate</div>" not in logic_body
    assert "background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`" not in filter_body
    assert "background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`" not in logic_body
    assert "display:'flex', alignItems:'center', gap:6, marginTop:6" not in filter_body
    assert "display:'flex', alignItems:'center', gap:6, marginTop:6" not in logic_body


def test_compose_body_reuses_generic_node_result_row_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    compose_body = jsx[
        jsx.index("const ComposeBody = ({ n }) =>"):
        jsx.index("const AnnotateBody =", jsx.index("const ComposeBody = ({ n }) =>"))
    ]

    assert "<NodeResultRowSurface" in compose_body
    assert "<NodeEmptyMessageSurface" in compose_body
    assert "<NodeTablePreviewSurface" in compose_body
    assert "<NodeTableHeaderCellSurface" in compose_body
    assert "<NodeTableRowSurface" in compose_body
    assert "<NodeTableCellSurface" in compose_body
    assert 'rowId="compose"' in compose_body
    assert 'rowId="schedule-empty"' in compose_body
    assert 'rowId="compose-table"' in compose_body
    assert "result={n.result}" in compose_body
    assert "get_grand_map_ui_surface', 'node-empty-message'" in jsx
    assert "get_grand_map_ui_surface', 'node-table-preview'" in jsx
    assert "display:'flex', alignItems:'center', gap:6, marginTop:6" not in compose_body
    assert "gridTemplateColumns:`repeat(${cols.length}, 1fr)`" not in compose_body
    assert "gridTemplateColumns:`repeat(${(cols && cols.length) || 1}, 1fr)`" not in compose_body
    assert "No schedule configured yet.<br/>" not in compose_body


def test_transform_body_reuses_generic_param_and_alert_rows():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    transform_body = jsx[
        jsx.index("const TransformBody = ({ n }) =>"):
        jsx.index("// Logic body", jsx.index("const TransformBody = ({ n }) =>"))
    ]

    assert "const NodeParamDisplayRowSurface = ({ nodeId, p }) =>" in jsx
    assert "const NodeAlertRowSurface = ({ nodeId, rowId, icon, text, state }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-param-display-row'" in jsx
    assert "get_grand_map_ui_surface', 'node-alert-row'" in jsx
    assert "<NodeParamDisplayRowSurface key={p.k} nodeId={n.id || 'transform-node'} p={p}/>" in transform_body
    assert "<NodeAlertRowSurface" in transform_body
    assert 'rowId="approval"' in transform_body
    assert 'state="warn"' in transform_body
    assert "borderBottom:`1px dashed ${LM.lineSoft}`" not in transform_body
    assert "mutates model" in transform_body


def test_annotate_body_reuses_generic_node_progress_row_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    annotate_body = jsx[
        jsx.index("const AnnotateBody = ({ n }) =>"):
        jsx.index("// Audit 2026-05-28", jsx.index("const AnnotateBody = ({ n }) =>"))
    ]

    assert "const NodeProgressRowSurface = ({ nodeId, rowId, label, progress, state }) =>" in jsx
    assert "const NodeSectionLabelSurface = ({ nodeId, rowId, text }) =>" in jsx
    assert "const NodeParamDisplayRowSurface = ({ nodeId, p }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-progress-row'" in jsx
    assert "get_grand_map_ui_surface', 'node-section-label'" in jsx
    assert "get_grand_map_ui_surface', 'node-param-display-row'" in jsx
    assert "<NodeProgressRowSurface" in annotate_body
    assert "<NodeParamDisplayRowSurface key={p.k} nodeId={n.id || 'annotate-node'} p={p}/>" in annotate_body
    assert '<NodeSectionLabelSurface nodeId={n.id || \'annotate-node\'} rowId="preview" text="PREVIEW"/>' in annotate_body
    assert 'rowId="runtime"' in annotate_body
    assert "label={n.runtime}" in annotate_body
    assert "progress={n.progress}" in annotate_body
    assert "<CompactParam" not in annotate_body
    assert "const CompactParam =" not in jsx
    assert "Math.round(n.progress*100)" not in annotate_body
    assert "height:3, background:LM.bgDeep" not in annotate_body
    assert ">PREVIEW</div>" not in annotate_body


def test_stage_preview_uses_generic_node_stage_preview_frame():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    stage_preview = jsx[
        jsx.index("const StagePreview = ({ n }) =>"):
        jsx.index("// \u2500\u2500\u2500 canvas toolbar", jsx.index("const StagePreview = ({ n }) =>"))
    ]

    assert "const NodeStagePreviewSurface = ({ nodeId, children }) =>" in jsx
    assert "const NodeStageImagePreviewSurface = ({ nodeId, src }) =>" in jsx
    assert "const NodeStageTextPreviewSurface = ({ nodeId, text }) =>" in jsx
    assert "const NodeStageEmptyPreviewSurface = ({ nodeId, text }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-stage-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-stage-image-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-stage-text-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-stage-empty-preview'" in jsx
    assert "<NodeStagePreviewSurface nodeId={n.id || 'stage-preview'}>" in stage_preview
    assert "<NodeStageImagePreviewSurface nodeId={n.id || 'stage-preview'} src={img}/>" in stage_preview
    assert "<NodeStageTextPreviewSurface nodeId={n.id || 'stage-preview'} text={text.slice(0, 600)}/>" in stage_preview
    assert "<NodeStageEmptyPreviewSurface" in stage_preview
    assert "</NodeStagePreviewSurface>" in stage_preview
    assert '<img src={img} alt="node output preview"' not in stage_preview
    assert "Preview appears after this node runs.</div>" not in stage_preview
    assert "aspectRatio:'2/1'" not in stage_preview
    assert "backgroundImage:`linear-gradient" not in stage_preview


def test_custom_body_reuses_generic_port_row_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    custom_body = jsx[
        jsx.index("const CustomBody = ({ n }) =>"):
        jsx.index("const ConnectorOpBody =", jsx.index("const CustomBody = ({ n }) =>"))
    ]

    assert "const NodePortRowSurface = ({ nodeId, rowId, icon, label, type, state }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-port-row'" in jsx
    assert "<NodePortRowSurface" in custom_body
    assert "<NodeEmptyMessageSurface" in custom_body
    assert "<NodeSectionLabelSurface" in custom_body
    assert 'rowId="ports-empty"' in custom_body
    assert 'rowId="custom-type"' in custom_body
    assert 'state="in"' in custom_body
    assert 'state="out"' in custom_body
    assert "const CustomBodyRow" not in jsx
    assert "display:'flex', alignItems:'center', gap:6, fontFamily:LM.mono, fontSize:9.5" not in custom_body
    assert "no declared ports</span>" not in custom_body


def test_grammar_body_reuses_generic_typed_param_and_preview_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    grammar_body = jsx[
        jsx.index("const GrammarBody = ({ n }) =>"):
        jsx.index("const CustomBody =", jsx.index("const GrammarBody = ({ n }) =>"))
    ]

    assert "const NodeTypedParamRowSurface = ({ nodeId, paramKey, value, indicator, state, swatch }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-typed-param-row'" in jsx
    assert "<NodeTypedParamRowSurface" in grammar_body
    assert "<NodeEmptyMessageSurface" in grammar_body
    assert "<NodeSectionLabelSurface" in grammar_body
    assert "<NodePreformattedPreviewSurface" in grammar_body
    assert 'rowId="params-empty"' in grammar_body
    assert 'rowId="params-more"' in grammar_body
    assert 'rowId="cooked"' in grammar_body
    assert "String.fromCharCode(10003)" in grammar_body
    assert "String.fromCharCode(10005)" in grammar_body
    assert "background:hex" not in grammar_body
    assert "height:10, borderRadius:2" not in grammar_body
    assert "fontFamily:LM.mono, fontSize:9, color:LM.inkDim" not in grammar_body
    assert "maxHeight:72, overflow:'auto', whiteSpace:'pre-wrap'" not in grammar_body


def test_connector_op_body_reuses_generic_display_surfaces_for_passive_state():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    connector_body = jsx[
        jsx.index("const ConnectorOpBody = ({ n }) =>"):
        jsx.index("const HostBody =", jsx.index("const ConnectorOpBody = ({ n }) =>"))
    ]

    assert "<NodeEmptyMessageSurface" in connector_body
    assert "<NodeTypedParamRowSurface" in connector_body
    assert "<NodeSectionLabelSurface" in connector_body
    assert "<NodeAlertRowSurface" in connector_body
    assert "<NodeResultRowSurface" in connector_body
    assert "<NodeActionButtonSurface" in connector_body
    assert 'rowId="op-empty"' in connector_body
    assert 'rowId="params-more"' in connector_body
    assert 'rowId="mutates-host"' in connector_body
    assert 'rowId="connector-result"' in connector_body
    assert 'rowId="run"' in connector_body
    assert "node-action-button.press" in jsx
    assert "lm-run-connector-op" in connector_body
    assert "String.fromCharCode(9654)" in connector_body
    assert "String.fromCharCode(10003)" in connector_body
    assert "String.fromCharCode(10005)" in connector_body
    assert "<button onClick={onRun}" not in connector_body
    assert "background:LM.bgDeep, border:`1px solid ${res.ok ? LM.lineSoft : LM.err}`" not in connector_body
    assert "p.label || p.k}{p.required ? ' *' : ''" not in connector_body
    assert "no op chosen</" not in connector_body


def test_host_body_reuses_generic_param_display_rows():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    host_body = jsx[
        jsx.index("const HostBody = ({ n }) =>"):
        jsx.index("const ConversationCompactExpandSurface =", jsx.index("const HostBody = ({ n }) =>"))
    ]

    assert "<NodeParamDisplayRowSurface" in host_body
    assert "p={{ k: o.label || o.id, v: o.val }}" in host_body
    assert "display:'flex', gap:6, fontFamily:LM.mono, fontSize:10" not in host_body
    assert "borderBottom:`1px dashed ${LM.lineSoft}`" not in host_body


def test_note_body_reuses_node_display_and_editor_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    note_body = jsx[
        jsx.index("const NoteBody = ({ n }) =>"):
        jsx.index("const GrammarBody = ({ n }) =>", jsx.index("const NoteBody = ({ n }) =>"))
    ]

    assert "const NodeNoteDisplaySurface = ({ nodeId, children, onEdit }) =>" in jsx
    assert "const NodeNoteEditorSurface = ({ nodeId, text, onChange, onCommit, onCancel }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-note-display'" in jsx
    assert "get_grand_map_ui_surface', 'node-note-editor'" in jsx
    assert "node-note-display.edit" in jsx
    assert "node-note-editor.change" in jsx
    assert "<NodeNoteDisplaySurface" in note_body
    assert "<NodeNoteEditorSurface" in note_body
    assert "draftRef.current" in note_body
    assert "<textarea autoFocus value={draft}" not in note_body
    assert "<div onDoubleClick={() => setEditing(true)}" not in note_body
    assert "onChange={e => setDraft(e.target.value)}" not in note_body


def test_note_markdown_blocks_are_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    inline = jsx[
        jsx.index("const _renderInlineMd = (text, nodeId = 'markdown-node', rowPrefix = 'inline') =>"):
        jsx.index("const _renderMarkdown = (text, nodeId = 'markdown-node') =>")
    ]
    markdown = jsx[
        jsx.index("const _renderMarkdown = (text, nodeId = 'markdown-node') =>"):
        jsx.index("const NoteBody = ({ n }) =>", jsx.index("const _renderMarkdown = (text, nodeId = 'markdown-node') =>"))
    ]
    note_body = jsx[
        jsx.index("const NoteBody = ({ n }) =>"):
        jsx.index("const GrammarBody = ({ n }) =>", jsx.index("const NoteBody = ({ n }) =>"))
    ]

    assert "const NodeMarkdownBlockSurface = ({ nodeId, rowId, kind, children }) =>" in jsx
    assert "const NodeMarkdownListSurface = ({ nodeId, rowId, children }) =>" in jsx
    assert "const NodeMarkdownListItemSurface = ({ nodeId, rowId, children }) =>" in jsx
    assert "const NodeMarkdownInlineSurface = ({ nodeId, rowId, kind, text }) =>" in jsx
    assert "const NodeMarkdownLinkSurface = ({ nodeId, rowId, text, url }) =>" in jsx
    assert "const NodeMarkdownImageSurface = ({ nodeId, rowId, src, alt }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-markdown-block'" in jsx
    assert "get_grand_map_ui_surface', 'node-markdown-list'" in jsx
    assert "get_grand_map_ui_surface', 'node-markdown-list-item'" in jsx
    assert "get_grand_map_ui_surface', 'node-markdown-inline'" in jsx
    assert "get_grand_map_ui_surface', 'node-markdown-link'" in jsx
    assert "get_grand_map_ui_surface', 'node-markdown-image'" in jsx
    assert "<NodeMarkdownInlineSurface" in inline
    assert "<NodeMarkdownLinkSurface" in inline
    assert "<NodeMarkdownImageSurface" in inline
    assert "<NodeMarkdownBlockSurface" in markdown
    assert "<NodeMarkdownListSurface" in markdown
    assert "<NodeMarkdownListItemSurface" in markdown
    assert "_renderInlineMd(b, nodeId," in markdown
    assert "_renderInlineMd(ln.replace(/^### /, ''), nodeId," in markdown
    assert "_renderInlineMd(ln.replace(/^## /, ''), nodeId," in markdown
    assert "_renderInlineMd(ln.replace(/^# /, ''), nodeId," in markdown
    assert "_renderInlineMd(ln, nodeId," in markdown
    assert "_renderMarkdown(initialText, n.id || 'note-node')" in note_body
    assert "out.push(<img" not in inline
    assert "out.push(<a" not in inline
    assert "out.push(<code" not in inline
    assert "out.push(<strong" not in inline
    assert "out.push(<em" not in inline
    assert "out.push(<h1" not in markdown
    assert "out.push(<h2" not in markdown
    assert "out.push(<h3" not in markdown
    assert "out.push(<p" not in markdown
    assert "out.push(<ul" not in markdown
    assert "<li key={i}" not in markdown


def test_host_node_v2_body_reuses_generic_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    host_v2 = jsx[
        jsx.index("const HostNodeV2Body = ({ n }) =>"):
        jsx.index("const WatchBody = ({ n }) =>", jsx.index("const HostNodeV2Body = ({ n }) =>"))
    ]

    assert "action = 'node-choice-tile.press', actionArgs, onPress, active" in jsx
    assert "const NodeKvRowSurface = ({ nodeId, rowId, rowKey, value, state }) =>" in jsx
    assert "action = 'node-output-port-row.press', actionArgs, onPress, onHover" in jsx
    assert "action = 'node-icon-button.press', actionArgs, onPress, width = 22" in jsx
    assert "get_grand_map_ui_surface', 'node-choice-tile'" in jsx
    assert "get_grand_map_ui_surface', 'node-kv-row'" in jsx
    assert "get_grand_map_ui_surface', 'node-output-port-row'" in jsx
    assert "get_grand_map_ui_surface', 'node-icon-button'" in jsx
    assert "node-choice-tile.press" in jsx
    assert "node-output-port-row.press" in jsx
    assert "node-icon-button.press" in jsx
    assert "<NodeChoiceTileSurface" in host_v2
    assert "<NodeKvRowSurface" in host_v2
    assert "<NodeOutputPortRowSurface" in host_v2
    assert "<NodeIconButtonSurface" in host_v2
    assert 'action="connector.operation.select"' in host_v2
    assert 'action="connector.output.promote"' in host_v2
    assert "action={'node.verb.' + v.key + '.toggle'}" in host_v2
    assert "lm-host-set-op" not in host_v2
    assert "lm-host-promote-output" not in host_v2
    assert "data-host-op-tile={op.op_id}" not in host_v2
    assert "data-host-output={tk}" not in host_v2
    assert "<button key={v.key}" not in host_v2
    assert "<button onClick={() => setAdvancedOpen" not in host_v2


def test_watch_body_reuses_generic_empty_and_preformatted_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    watch_body = jsx[
        jsx.index("const WatchBody = ({ n }) =>"):
        jsx.index("// \u2500\u2500\u2500 SLICE E (AgDR-0008): NoteBody", jsx.index("const WatchBody = ({ n }) =>"))
    ]

    assert "<NodeEmptyMessageSurface" in watch_body
    assert 'rowId="watch-empty"' in watch_body
    assert "text=\"no data yet - wire a node to me\"" in watch_body
    assert "const NodePreformattedPreviewSurface = ({ nodeId, rowId, text, maxHeight = 200, marginTop = 6 }) =>" in jsx
    assert "const NodeImagePreviewSurface = ({ nodeId, rowId, src }) =>" in jsx
    assert "const NodeListPreviewSurface = ({ nodeId, rowId, children }) =>" in jsx
    assert "const NodeTablePreviewSurface = ({ nodeId, rowId, header, rows }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-preformatted-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-image-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-list-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-list-preview-item'" in jsx
    assert "get_grand_map_ui_surface', 'node-table-preview'" in jsx
    assert "get_grand_map_ui_surface', 'node-table-header-cell'" in jsx
    assert "get_grand_map_ui_surface', 'node-table-row'" in jsx
    assert "get_grand_map_ui_surface', 'node-table-cell'" in jsx
    assert "<NodePreformattedPreviewSurface" in watch_body
    assert "<NodeImagePreviewSurface" in watch_body
    assert "<NodeListPreviewSurface" in watch_body
    assert "<NodeListPreviewItemSurface" in watch_body
    assert "<NodeTablePreviewSurface" in watch_body
    assert "<NodeTableHeaderCellSurface" in watch_body
    assert "<NodeTableRowSurface" in watch_body
    assert "<NodeTableCellSurface" in watch_body
    assert 'rowId="geometry"' in watch_body
    assert 'rowId="json"' in watch_body
    assert 'rowId="watch-image"' in watch_body
    assert 'rowId="watch-list"' in watch_body
    assert 'rowId="watch-table"' in watch_body
    assert "src={s}" in watch_body
    assert "maxHeight={140}" in watch_body
    assert "maxHeight={200}" in watch_body
    assert "fontStyle:'italic'" not in watch_body
    assert '<img src={s} alt="watch"' not in watch_body
    assert "<ul style={{ marginTop:6" not in watch_body
    assert "<table style={{ borderCollapse:'collapse'" not in watch_body
    assert "<pre style={{ marginTop:6" not in watch_body
    assert "<pre style={{ margin:0" not in watch_body


def test_reroute_and_collapsed_group_ports_use_shared_socket_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    group_block = jsx[
        jsx.index("{promoted.ins.map((p, i) => ("):
        jsx.index("Expanded branch", jsx.index("{promoted.ins.map((p, i) => ("))
    ]
    reroute_block = jsx[
        jsx.index("if (n.kind === 'reroute') {"):
        jsx.index("// AI nodes can expand horizontally", jsx.index("if (n.kind === 'reroute') {"))
    ]

    assert group_block.count("<CanvasSocketSurface") == 2
    assert "side=\"in\"" in group_block
    assert "side=\"out\"" in group_block
    assert "nodeId={p.groupSocket}" in group_block
    assert "sockId={p.groupSocket}" in group_block
    assert "data-lm-socket={`in:${p.groupSocket}:${p.groupSocket}`}" not in group_block
    assert "data-lm-socket={`out:${p.groupSocket}:${p.groupSocket}`}" not in group_block
    assert "data-lm-socket-dot=\"1\"" not in group_block

    assert reroute_block.count("<CanvasSocketSurface") == 2
    assert "nodeId={n.id}" in reroute_block
    assert "sockId=\"value\"" in reroute_block
    assert "data-lm-socket={`in:${n.id}:value`}" not in reroute_block
    assert "data-lm-socket={`out:${n.id}:value`}" not in reroute_block
    assert "data-lm-socket-dot=\"1\"" not in reroute_block


def test_canvas_node_card_root_import_bumps_after_async_surface_merge():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    root_importer = jsx[
        jsx.index("const ensureGrandMapCanvasNodeCardNodes ="):
        jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate =", jsx.index("const ensureGrandMapCanvasNodeCardNodes ="))
    ]

    assert "bridgeAsync('get_grand_map_ui_surface', 'canvas-node-card')" in root_importer
    assert "if (mergeUiSurfaceIntoGraph(payload))" in root_importer
    assert "window.dispatchEvent(new Event('archhub-ui-surface-imported'))" in root_importer
    assert "window.dispatchEvent(new Event('lm-graph-bump'))" in root_importer


def test_canvas_node_renderer_uses_node_backed_header_and_body_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_renderer = jsx[
        jsx.index("const _NodeRenderer_inner ="):
        jsx.index("const NodeRenderer = React.memo")
    ]
    regular_path = node_renderer[
        node_renderer.index("const isAiPlan ="):
        node_renderer.index("// Custom comparator", 0)
    ]

    assert "const CanvasNodeCardHeaderSurface = ({ node, cat, focused, onDragStart, status, actions }) =>" in jsx
    assert "const CanvasNodeCardBodySurface = ({ node, expanded, onToggleExpand, detail }) =>" in jsx
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeCardHeaderNodes(node, cat) : null" in jsx
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeCardBodyNodes(node) : null" in jsx
    assert "<CanvasNodeCardHeaderSurface" in regular_path
    assert "<CanvasNodeCardBodySurface" in regular_path
    assert "status={nodeHeaderStatusSlot}" in regular_path
    assert "actions={nodeHeaderActionsSlot}" in regular_path
    assert "detail={nodeBodyDetailSlot}" in regular_path
    assert "slot:canvas-node-card-status" in jsx
    assert "slot:canvas-node-card-actions" in jsx
    assert "slot:canvas-node-card-detail" in jsx
    assert ">{n.title}</div>" not in regular_path
    assert "{n.sub && <div" not in regular_path


def test_cloned_ui_node_params_materialize_only_when_explicit():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const clonedUiNodeShouldMaterializeParams ="):
        jsx.index("const finishClonedUiNodeParamAuthority =", jsx.index("const clonedUiNodeShouldMaterializeParams ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="):
        jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes =", jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="))
    ]

    assert "copy.data.materialize_param_nodes === true" in helper
    assert "copy.data.eager_param_nodes === true" in helper
    assert "if (!clonedUiNodeShouldMaterializeParams(copy)) return;" in helper
    assert "materializeGrandMapParamNode(copy, p.k, copy.data[p.k])" in helper
    assert "window.ahSetUiNodeParam(copy.id, p.k, copy.data[p.k])" not in helper
    assert "if (tn.data && tn.data.role === 'parameter') return;" in clone
    assert "if (String(id).indexOf('__') === 0) return;" in clone
    assert "resetClonedUiNodeParamLinks(copy);" in clone
    assert "['bind', 'src_bind', 'href_bind', 'alt_bind', 'active_bind', 'disabled_bind', 'hidden_bind', 'state_bind'].forEach(k => {" in clone
    assert "copy.data.args = Object.assign({}, copy.data.args || {}, slotMap.__action_args);" in clone
    assert "syncClonedUiNodeParams(copy);" in clone
    assert "if (String(fromId).indexOf('param:') === 0 ||" in clone
    assert "String(toId).indexOf('param:') === 0) return;" in clone
    assert "copy.data.param_nodes = copy.data.param_nodes.map(mapId)" not in clone
    assert "copy.data.role === 'parameter' && copy.data.key" not in clone


def test_canvas_node_card_slots_wire_to_node_parameters():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="):
        jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes =", jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="))
    ]
    header = jsx[
        jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes ="):
        jsx.index("const ensureGrandMapCanvasNodeCardBodyNodes =", jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes ="))
    ]
    body = jsx[
        jsx.index("const ensureGrandMapCanvasNodeCardBodyNodes ="):
        jsx.index("const canvasNodeSocketInstanceId =", jsx.index("const ensureGrandMapCanvasNodeCardBodyNodes ="))
    ]
    helper = jsx[
        jsx.index("const uiSlotParameterWireId ="):
        jsx.index("const rightRailFocusWireId =", jsx.index("const uiSlotParameterWireId ="))
    ]
    prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailClones ="):
        jsx.index("let __grandMapUiHomeSlots", jsx.index("const pruneGrandMapFocusedRailClones ="))
    ]
    panel_prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailPanelClones ="):
        jsx.index("const __grandMapSurfaceBuildSignatures =", jsx.index("const pruneGrandMapFocusedRailPanelClones ="))
    ]

    assert "const syncUiSlotParameterRelation =" in helper
    assert "const relationWireFamily = options.wire_family || 'ui_slot_parameter';" in helper
    assert "const relationName = options.relation || relationWireFamily;" in helper
    assert "wire_family: relationWireFamily" in helper
    assert "relation: relationName" in helper
    assert "ui_owner_node_id: ownerNodeId" in helper
    assert "ui_param_node_id: sourceParamNodeId" in helper
    assert "ui_slot_node_id: slotNodeId" in helper
    assert "behavior: options.behavior || 'display-slot-value'" in helper
    assert "presentation: options.presentation || 'ui-slot'" in helper
    assert "const materializeSlotParamNodes = options.materialize_slot_param_nodes === true;" in helper
    assert "['ui_slot_parameter_relation_node_id', relationNodeId || '']" in helper
    assert "setGrandMapInlineNodeField(slotNode, field, fieldValue)" in helper
    assert "if (window.ahSetUiNodeParam && materializeSlotParamNodes) {" not in helper
    assert "const clonedSlotMap = {};" in clone
    assert "clonedSlotMap[mappedId] = slotMap[id];" in clone
    assert "const slotRelationGroupNodeIds = [];" in clone
    assert "slotMap.__field_relations" in clone
    assert "syncUiSlotParameterRelation(mapId(entry.slot), entry.owner_node_id, entry.key, entry.value" in clone
    assert "materialize_slot_param_nodes: false" in clone
    assert "syncGrandMapSurfaceStateSlots(surfaceName + '-' + sid, rootId, clonedSlotMap" in clone
    assert "state_key: grandMapSafeId(surfaceName || 'surface').replace(/[-.]/g, '_') + '_state_node_id'" in clone
    assert "setGrandMapInlineNodeField(rootNode, 'group_nodes', groupNodes)" in clone
    assert "__field_relations: [" in header
    assert "key: 'canvas_card_icon'" in header
    assert "key: 'canvas_card_label'" in header
    assert "__field_relations: [" in body
    assert "key: 'title'" in body
    assert "key: 'sub'" in body
    assert "key: 'canvas_card_subtitle_hidden'" in body
    assert "data.wire_family === 'ui_slot_parameter'" in prune
    assert "data.role === 'wire_layer' && data.wire_family === 'ui_slot_parameter'" in prune


def test_generic_cloned_node_surfaces_prematerialize_action_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="):
        jsx.index("const ensureGrandMapCanvasNodeCardHeaderNodes =", jsx.index("const cloneGrandMapCanvasNodeCardSurfaceTemplate ="))
    ]
    output_body = jsx[
        jsx.index("const ensureGrandMapNodeOutputBodyNodes ="):
        jsx.index("const ensureGrandMapNodeOutputParamRowNodes =", jsx.index("const ensureGrandMapNodeOutputBodyNodes ="))
    ]
    port_row = jsx[
        jsx.index("const ensureGrandMapNodeOutputPortRowNodes ="):
        jsx.index("const nodeIconButtonInstanceId =", jsx.index("const ensureGrandMapNodeOutputPortRowNodes ="))
    ]

    assert "const surfaceName = String(template.root_id || 'ui-surface').replace(/^ui:grandmap:/, '');" in clone
    assert "const actionRelationGroupNodeIds = [];" in clone
    assert "if (copy.data && copy.data.action) {" in clone
    assert "ensureUiActionBehaviorNode(copy.id, 'action', copy.data.action, actionArgs" in clone
    assert "event: 'hydrate'" in clone
    assert "component: surfaceName" in clone
    assert "ensureUiActionHandlerRoute({" in clone
    assert "owner_node_id: copy.id" in clone
    assert "target_node_id: targetNodeId" in clone
    assert "action_handler_node_id: route.handler_node_id || ''" in clone
    assert "'data-action-node-id': runtime.action_node_id || ''" in clone
    assert "'data-action-handler-node-id': route.handler_node_id || ''" in clone
    assert "const relationGroupNodeIds = [].concat(slotRelationGroupNodeIds, actionRelationGroupNodeIds);" in clone
    assert "if (copy.data.action && slotMap && slotMap.__action)" in clone
    assert "copy.data.action = String(slotMap.__action);" in clone
    assert "__action_args: { node_id: nodeId }" in output_body
    assert "__action: slots && slots.action ? String(slots.action) : 'node-output-port-row.press'" in port_row
    assert "__action_args: Object.assign({ output_id: sid }, slots && slots.args || {})" in port_row


def test_node_canvas_filters_ui_surface_implementation_nodes_from_workflow_view():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const isWorkflowGraphNode ="):
        jsx.index("const NodeCanvas = React.memo")
    ]

    assert "const isWorkflowGraphNode = (node) =>" in jsx
    assert "const isVisibleWorkflowCanvasNode = (node) =>" in jsx
    assert "type.indexOf('ui.') === 0" in node_canvas
    assert "cat === 'ui'" in node_canvas
    assert "id.indexOf('ui:') === 0" in node_canvas
    assert "id.indexOf('slot:') === 0" in node_canvas
    assert "id.indexOf('param:ui:') === 0" in node_canvas
    assert "id.indexOf('param:slot:') === 0" in node_canvas
    assert "const canvasNodes = React.useMemo(" in node_canvas
    assert ".filter(isVisibleWorkflowCanvasNode)" in node_canvas
    assert "const selectedWireAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowWireAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "const focusedParameterAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowParameterAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "const selectedPathGroupAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowSelectedWirePathGroupAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "const anatomyNodes = selectedWireAnatomyNodes.concat(" in node_canvas
    assert "boundaryStateAnatomyNodes," in node_canvas
    assert "nodeConnectionSectionAnatomyNodes," in node_canvas
    assert "return baseOutsideAnatomy.concat(anatomyNodes.filter(n => n && !seen.has(n.id)));" in node_canvas
    assert "visibleNodesSrc = React.useMemo" in node_canvas
    assert "cullToViewport(canvasNodes || []" in node_canvas
    assert "const base = wires.filter(w => {" in node_canvas
    assert "!canvasNodeIds.has(wireEndpointNodeId(w.from))" in node_canvas
    assert "projectedSectionWireIds.has(w && w.id)" in node_canvas
    assert "const visibleRelationEndpointWireIds = new Set();" in node_canvas
    assert "data.role !== 'wire_endpoint' || !data.relation_node || !data.relation_wire_id" in node_canvas
    assert "visibleRelationEndpointWireIds.add(data.relation_wire_id);" in node_canvas
    assert "data.role === 'relation' && data.relation_node && visibleRelationEndpointWireIds.has(w && w.id)" in node_canvas
    assert "return base.concat(nodeConnectionSectionAnatomyWires || []);" in node_canvas
    assert "nodes: canvasNodes" in node_canvas


def test_workflow_parameter_nodes_are_saved_but_not_top_level_canvas_cards():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workflow_filters = jsx[
        jsx.index("const isWorkflowGraphNode ="):
        jsx.index("const wireEndpointNodeId =")
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo")
    ]
    snapshot = jsx[
        jsx.index("const workflowGraphSnapshot ="):
        jsx.index("const workflowGraphJSON =")
    ]

    assert "const isWorkflowGraphNode = (node) =>" in workflow_filters
    assert "const isVisibleWorkflowCanvasNode = (node) =>" in workflow_filters
    assert "if (!isWorkflowGraphNode(node)) return false;" in workflow_filters
    assert "if (data.role === 'parameter') return false;" in workflow_filters
    assert "if (data.role === 'wire') return false;" in workflow_filters
    assert "if (data.role === 'wire_layer') return false;" in workflow_filters
    assert "if (data.role === 'selected_wire_path_wire') return false;" in workflow_filters
    assert "if (data.role === 'selected_wire_path_group') return false;" in workflow_filters
    assert "].filter(isWorkflowGraphNode)" in snapshot
    assert ".filter(isVisibleWorkflowCanvasNode)" in node_canvas
    assert ".filter(isWorkflowCanvasNode)" not in node_canvas


def test_workflow_wires_materialize_as_hidden_structural_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const wireEndpointNodeId ="):
        jsx.index("const workflowGraphSnapshot =", jsx.index("const wireEndpointNodeId ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const wireEndpointPortId = (endpoint) =>" in helpers
    assert "const workflowWireNodeId = (wire, index) =>" in helpers
    assert "const workflowWireEndpointWireId = (wireNodeId, endpoint) =>" in helpers
    assert "const workflowWirePortSpec = (node, portId, side) =>" in helpers
    assert "const WORKFLOW_WIRE_LAYER_SPECS = wireLayerSpecsForContext({" in helpers
    assert "{ id:'ports', valueKey:'port_binding', title:'Ports layer', capabilities:['source_port', 'target_port', 'expose_parameter', 'presentation_port'] }" in jsx
    assert "source_port: { capabilities:['select_output_socket', 'port_parameter', 'external_port_binding'] }" in helpers
    assert "target_port: { capabilities:['select_input_socket', 'port_parameter', 'external_port_binding'] }" in helpers
    assert "{ id:'source_field', valueKey:'src_field', title:'Source field layer', capabilities:['select_subvalue', 'field_projection', 'geometry_attribute_path', 'image_metadata_path'] }" in jsx
    assert "{ id:'target_field', valueKey:'dst_field', title:'Target field layer', capabilities:['wrap_subvalue', 'field_injection', 'input_shape'] }" in jsx
    assert "{ id:'schema', valueKey:'schema_ref', title:'Schema layer', capabilities:['schema_ref', 'contract_check'] }" in jsx
    assert "{ id:'encryption', valueKey:'encryption', title:'Encryption layer', capabilities:['encrypt', 'decrypt'], options:WIRE_LAYER_OPTION_SETS.encryption }" in jsx
    assert "const workflowWireLayerNodeId = (wireNodeId, layerId) =>" in helpers
    assert "const workflowWireLayerLinkWireId = (wireNodeId, layerId) =>" in helpers
    assert "const workflowWireLayerSpecForKey = (key) =>" in helpers
    assert "const workflowWireLayerKeys = () => WORKFLOW_WIRE_LAYER_SPECS.map(spec => spec.id);" in helpers
    assert "const workflowWireParamLabel = (key) =>" in helpers
    assert "const materializeWireLayerValueParamNode = (graph, layerNode, spec, value, valueOptions) =>" in jsx
    assert "param_family: 'wire_layer_value'" in jsx
    assert "relation: 'parameterizes_layer_value'" in jsx
    assert "const ensureWorkflowWireLayerNodes = (graph, wireNodeId, payload) =>" in helpers
    assert "const materializeWorkflowWireNodes = (graph) =>" in helpers
    assert "if (!workflowWireShouldMaterializeRawEdge(wire)) return;" in helpers
    assert "if (!isVisibleWorkflowCanvasNode(fromOwner) || !isVisibleWorkflowCanvasNode(toOwner)) return;" in helpers
    assert "if (fromData.role === 'wire' || toData.role === 'wire') return;" in helpers
    assert "const sourcePortNodeId = ensureUiNodePortParamNode(g, fromNode, workflowWirePortSpec(fromOwner, fromPort, 'out'), 'out');" in helpers
    assert "const targetPortNodeId = ensureUiNodePortParamNode(g, toNode, workflowWirePortSpec(toOwner, toPort, 'in'), 'in');" in helpers
    assert "const portBinding = existingWireData.port_binding ||" in helpers
    assert "[(sourcePortNodeId || fromNode), (targetPortNodeId || toNode)].join(' -> ');" in helpers
    assert "const wireLayers = workflowWireLayerKeys();" in helpers
    assert "role: 'wire'" in helpers
    assert "wire_family: 'workflow_wire'" in helpers
    assert "kind: 'wire'" in helpers
    assert "cat: 'wire'" in helpers
    assert "wire_layers: wireLayers" in helpers
    assert "port_binding: portBinding" in helpers
    assert "src_field: srcField" in helpers
    assert "dst_field: dstField" in helpers
    assert "role: 'wire_layer'" in helpers
    assert "role: 'wire_layer_link'" in helpers
    assert "materializeWireLayerValueParamNode(g, layerNode, spec, value, valueOptions);" in helpers
    assert "wireNode.data = Object.assign({}, wireNode.data || {}, {" in helpers
    assert "layer_nodes: layerMap" in helpers
    assert "param.wire_layer = spec.id;" in helpers
    assert "param.wire_layer_node_id = layerNodeId;" in helpers
    assert "ensureWorkflowWireLayerNodes(g, id, payload).forEach(layerNodeId => liveWireLayerNodeIds.add(layerNodeId));" in helpers
    assert "data.role === 'wire_layer' && data.wire_family === 'workflow_wire'" in helpers
    assert "gate_policy: gatePolicy" in helpers
    assert "encryption" in helpers
    assert "presentation_edge: true" in helpers
    assert "role: 'wire_endpoint'" in helpers
    assert "wire_family: 'workflow_wire'" in helpers
    assert "relation_node: id" in helpers
    assert "from_node" in helpers
    assert "to_port" in helpers
    assert "data.role === 'wire' && data.wire_family === 'workflow_wire'" in helpers
    assert "data.role === 'wire' || liveWireNodeIds.has(node.id)" not in helpers
    assert "window.materializeWorkflowWireNodes = materializeWorkflowWireNodes;" in helpers
    assert "materializeWorkflowWireNodes(LM_GRAPH)" in node_canvas
    assert "if (bumpGraph) bumpGraph();" in node_canvas


def test_workflow_wire_fanout_and_fanin_materialize_as_junction_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const workflowWireJunctionNodeId ="):
        jsx.index("const ensureWorkflowWireLayerNodes =", jsx.index("const workflowWireJunctionNodeId ="))
    ]
    materializer = jsx[
        jsx.index("const materializeWorkflowWireNodes ="):
        jsx.index("const workflowWireRelationNodeIdForWire =", jsx.index("const materializeWorkflowWireNodes ="))
    ]
    authority = jsx[
        jsx.index("const NODE_CONNECTION_JUNCTION_RUNTIME_KEYS ="):
        jsx.index("const nodeConnectionCodecEncode =", jsx.index("const nodeConnectionWireAuthorityData ="))
    ]
    anatomy = jsx[
        jsx.index("const workflowWireAnatomyNodesForFocus ="):
        jsx.index("const workflowParameterAnatomyNodesForFocus =", jsx.index("const workflowWireAnatomyNodesForFocus ="))
    ]

    assert "const workflowWireJunctionNodeId = (topology, anchorNode, anchorPort) =>" in helpers
    assert "const materializeWorkflowWireJunctionNodes = (graph, liveWireNodeIds, liveWireLayerNodeIds) =>" in helpers
    assert "groups.push({ topology:'fanout', members });" in helpers
    assert "groups.push({ topology:'fanin', members });" in helpers
    assert "wire_topology: group.topology" in helpers
    assert "relation: 'junction'" in helpers
    assert "member_wire_node_ids: memberWireNodeIds" in helpers
    assert "role: 'wire_junction_member'" in helpers
    assert "member.data = Object.assign({}, data, {" in helpers
    assert "junction_nodes: nextIds" in helpers
    assert "junction_node: nextIds[0] || ''" in helpers
    assert "if (materializeWorkflowWireJunctionNodes(g, liveWireNodeIds, liveWireLayerNodeIds))" in materializer
    assert "data.role === 'wire_junction_member' && (stale.has(data.junction_node) || stale.has(data.member_wire_node))" in materializer
    assert "const nodeConnectionWireJunctionNodes = (graphNodes, wireNode) =>" in authority
    assert "const nodeConnectionWireJunctionChips = (graphNodes, wireNode) =>" in authority
    assert "const nodeConnectionWireJunctionMemberNodeIds = (graph, junctionNodeId) =>" in authority
    assert "data.role === 'wire_junction_member' && data.junction_node === junctionNodeId" in authority
    assert "Object.assign(source, nodeConnectionWireLayerAuthorityValues(graphNodes, junctionNode));" in authority
    assert "source.junction_node = junctionNode.id;" in authority
    assert "junction_node_id: authorityWireData.junction_node || ''" in jsx
    assert "'data-wire-junction-node-id': port.junction_node_id || ''" in jsx
    assert "'data-wire-junction-node-id':item.junction_node_id || ''" in jsx
    assert "nodeConnectionWireJunctionNodes(graphNodes, wireNode).forEach(junctionNode =>" in jsx
    assert "label: 'junction ' + chip.label" in jsx
    assert "const junctionIds = workflowWireJunctionIdsForMember(wireNode).filter(id => byId.has(id));" in anatomy
    assert "const memberIds = [];" in anatomy
    assert "nodeConnectionWireJunctionMemberNodeIds(junctionGraph, junctionId)" in anatomy
    assert "...memberIds" in anatomy
    assert "const allLayerIds = Array.from(new Set([].concat(layerIds, junctionLayerIds, memberLayerIds).filter(Boolean)));" in anatomy
    assert "...junctionIds" in anatomy
    assert "junctionLayerIds, memberLayerIds" in anatomy


def test_selected_workflow_wire_exposes_anatomy_nodes_on_same_canvas():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workflow_filters = jsx[
        jsx.index("const isWorkflowGraphNode ="):
        jsx.index("const wireEndpointNodeId =")
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const workflowWireOwnerForFocus = (graphNodes, focusId) =>" in workflow_filters
    assert "const workflowLiveGraphNodes = (graphNodes) =>" in workflow_filters
    assert "((window.__archhub_LM_GRAPH || {}).nodes" in workflow_filters
    assert "data.role === 'wire' && data.wire_family === 'workflow_wire'" in workflow_filters
    assert "data.role === 'wire_layer' && data.wire_family === 'workflow_wire'" in workflow_filters
    assert "data.param_family === 'port' && data.relation_wire_family === 'workflow_wire'" in workflow_filters
    assert "const workflowWireAnatomyNodesForFocus = (graphNodes, focusId) =>" in workflow_filters
    assert "wireData.from_port_node" in workflow_filters
    assert "wireData.to_port_node" in workflow_filters
    assert "Object.values(wireData.layer_nodes" in workflow_filters
    assert "paramIdsForOwner(id).forEach(pid => anatomyIds.add(pid))" not in workflow_filters
    assert "paramIds.forEach((id, index) =>" not in workflow_filters
    assert "anatomy_view: true" in workflow_filters
    assert "anatomy_owner_wire: wireNodeId" in workflow_filters
    assert "const selectedWireAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowWireAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "const anatomyNodes = selectedWireAnatomyNodes.concat(" in node_canvas
    assert "boundaryStateAnatomyNodes," in node_canvas
    assert "nodeConnectionSectionAnatomyNodes," in node_canvas
    assert "baseOutsideAnatomy.concat(anatomyNodes.filter" in node_canvas


def test_selected_wire_path_group_opens_as_canvas_anatomy_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workflow_filters = jsx[
        jsx.index("const workflowSelectedWirePathGroupAnatomyNodesForFocus ="):
        jsx.index("const isStructuralAnatomyViewNode =", jsx.index("const workflowSelectedWirePathGroupAnatomyNodesForFocus ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    debug_state = jsx[
        jsx.index("window.__archhub_wire_anatomy_state = {"):
        jsx.index("const toggleExpanded =", jsx.index("window.__archhub_wire_anatomy_state = {"))
    ]

    assert "const workflowSelectedWirePathGroupAnatomyNodesForFocus = (graphNodes, focusId) =>" in workflow_filters
    assert "const rawGraphNodes = [];" in workflow_filters
    assert "const anatomyNodeById = (id) => byId.get(id || '') || rawById.get(id || '');" in workflow_filters
    assert "groupData.role !== 'selected_wire_path_group'" in workflow_filters
    assert "const selectedWireId = groupData.selected_wire_node_id || '';" in workflow_filters
    assert "const junctionIds = Array.isArray(groupData.selected_wire_junction_node_ids)" in workflow_filters
    assert "const memberIds = Array.isArray(groupData.selected_wire_member_node_ids)" in workflow_filters
    assert "const selectedLayerIds = Array.isArray(groupData.selected_wire_layer_node_ids)" in workflow_filters
    assert "const pathWireNodeIds = Array.isArray(groupData.selected_wire_path_wire_node_ids)" in workflow_filters
    assert "const allPathWireLayerIds = Array.isArray(groupData.selected_wire_path_wire_layer_node_ids)" in workflow_filters
    assert "const pathWireLayerIds = [];" in workflow_filters
    assert "const layerIds = Array.from(new Set(selectedLayerIds.concat(pathWireLayerIds)));" in workflow_filters
    assert "const sourceEndpointPortId = groupData.selected_wire_source_port_node_id || '';" in workflow_filters
    assert "const targetEndpointPortId = groupData.selected_wire_target_port_node_id || '';" in workflow_filters
    assert "const endpointPortIds = [];" in workflow_filters
    assert "if (id === sourceEndpointPortId) return 'source_endpoint_port';" in workflow_filters
    assert "if (id === targetEndpointPortId) return 'target_endpoint_port';" in workflow_filters
    assert "if (pathWireLayerIds.indexOf(id) >= 0) return 'path_wire_layer';" in workflow_filters
    assert "groupData.selected_wire_runtime_node_id || ''" in workflow_filters
    assert "const allPathParamIds = [];" in workflow_filters
    assert "pathIds.slice().forEach(id => paramIdsForOwner(id).forEach(pid => addUnique(allPathParamIds, pid)));" in workflow_filters
    assert "(rawGraphNodes || []).forEach(n => {" in workflow_filters
    assert "anatomy_owner_path_group: focusId" in workflow_filters
    assert "anatomy_path_role: roleOf(id)" in workflow_filters
    assert "anatomy_path_wire_layer_count: allPathWireLayerIds.length" in workflow_filters
    assert "anatomy_parameter_node_count: allPathParamIds.length" in workflow_filters
    assert "cloneAt(focusId, midX - 120, midY - 230, 240, 92);" in workflow_filters
    assert "placeIds([sourceEndpointPortId].filter(Boolean)" in workflow_filters
    assert "placeIds([targetEndpointPortId].filter(Boolean)" in workflow_filters
    assert "placeIds(pathWireNodeIds" in workflow_filters
    assert "placeIds(layerIds" in workflow_filters
    assert "placeIds(runtimeIds.filter(Boolean)" in workflow_filters
    assert "placeIds(paramIds" not in workflow_filters
    assert "const selectedPathGroupAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowSelectedWirePathGroupAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "selectedPathGroupAnatomyNodes" in node_canvas
    assert "pathGroupAnatomyNodeIds" in debug_state


def test_focused_parameter_node_exposes_itself_on_same_canvas():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    workflow_filters = jsx[
        jsx.index("const workflowParameterAnatomyNodesForFocus ="):
        jsx.index("const wireEndpointNodeId =", jsx.index("const workflowParameterAnatomyNodesForFocus ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const workflowParameterAnatomyNodesForFocus = (graphNodes, focusId) =>" in workflow_filters
    assert "paramData.role !== 'parameter'" in workflow_filters
    assert "const ownerId = paramData.owner || paramData.owner_id || '';" in workflow_filters
    assert "if (!owner || !isWorkflowGraphNode(owner)) return [];" in workflow_filters
    assert "if (ownerData.role === 'wire' || ownerData.role === 'wire_layer') return [];" in workflow_filters
    assert "anatomy_parameter_focus: true" in workflow_filters
    assert "const focusedParameterAnatomyNodes = React.useMemo(" in node_canvas
    assert "workflowParameterAnatomyNodesForFocus(graphNodes, focusId)" in node_canvas
    assert "const anatomyNodes = selectedWireAnatomyNodes.concat(" in node_canvas
    assert "boundaryStateAnatomyNodes," in node_canvas
    assert "nodeConnectionSectionAnatomyNodes," in node_canvas
    assert "parameterAnatomyNodeIds" in node_canvas


def test_frontend_workflow_wire_creation_births_layered_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const workflowWireBirthPayload ="):
        jsx.index("const WORKFLOW_WIRE_LAYER_SPECS =", jsx.index("const workflowWireBirthPayload ="))
    ]

    assert "value_type: valueType" in helper
    assert "src_field: (options && options.src_field) || ''" in helper
    assert "dst_field: (options && options.dst_field) || ''" in helper
    assert "schema_ref:" in helper
    assert "gate_policy:" in helper
    assert "codec:" in helper
    assert "encryption:" in helper
    assert "behavior:" in helper
    assert "presentation:" in helper
    assert "provenance:" in helper
    assert "data: {" in helper
    assert "source_owner: fromNode" in helper
    assert "target_owner: toNode" in helper
    assert "const commitWorkflowWireBirth = (graph, payload) =>" in helper
    assert "g.wires = [...g.wires, payload];" in helper
    assert "try { materializeWorkflowWireNodes(g); } catch (_e) {}" in helper
    assert "const workflowWireBirthPayloadFromWire = (graph, wire, options) =>" in helper
    assert "const commitWorkflowWireBirthFromWire = (graph, wire, options) =>" in helper
    assert "const replaceWorkflowGraphFromResult = (resultGraph) =>" in helper
    assert "replaceWorkflowGraphFromResult(result.graph);" in jsx
    assert "replaceWorkflowGraphFromResult(out.graph);" in jsx

    for provenance in (
        "frontend:agent-wire-action",
        "frontend:host-conversation-spawn",
        "frontend:socket-click-wire",
        "frontend:socket-drag-wire",
        "frontend:socket-drop-auto-wire",
        "frontend:node-branch-action",
        "frontend:conversation-branch-inbound",
        "frontend:wire-promote-palette",
        "frontend:auto-bridge-delete",
        "frontend:spawn-skill-inline",
        "frontend:skill-disentangle",
        "frontend:adapter-insert",
    ):
        assert provenance in jsx

    assert "const w = { from: [action.src_node, fromPort], to: [action.dst_node, prefIn] };" not in jsx
    assert "LM_GRAPH.wires = [...(LM_GRAPH.wires || []), { from:[hostNode.id, outId], to:[convNode.id, inId] }];" not in jsx
    assert "LM_GRAPH.wires = [...(LM_GRAPH.wires || []), {\n          from:[fromN.nodeId, fromN.sockId]" not in jsx
    assert "LM_GRAPH.wires = [...(LM_GRAPH.wires || []), workflowWireBirthPayload(" not in jsx
    assert "LM_GRAPH.wires = (LM_GRAPH.wires || []).concat(bridgeWires);" not in jsx
    assert "LM_GRAPH.wires = [...(LM_GRAPH.wires || []), ...blob.wires];" not in jsx
    assert "LM_GRAPH.wires = [...LM_GRAPH.wires, ...blob.wires];" not in jsx
    assert "LM_GRAPH.wires = result.graph.wires || [];" not in jsx
    assert "LM_GRAPH.wires = out.graph.wires || [];" not in jsx
    assert "LM_GRAPH.wires = (LM_GRAPH.wires || []).concat([" not in jsx
    assert "LM_GRAPH.wires = [...(LM_GRAPH.wires || []), ...inbound.map(w => workflowWireBirthPayload(" not in jsx
    assert "commitWorkflowWireBirth(LM_GRAPH, w);" in jsx
    assert "newWires.forEach(wire => commitWorkflowWireBirth(LM_GRAPH, wire));" in jsx
    assert "bridgeWires.forEach(wire => commitWorkflowWireBirth(LM_GRAPH, wire));" in jsx
    assert "commitWorkflowWireBirthFromWire(LM_GRAPH, wire" in jsx
    assert "inbound.forEach(w => commitWorkflowWireBirth(LM_GRAPH, workflowWireBirthPayload(" in jsx
    assert ".map(w => ({ ...w, to:[newId, w.to[1]] }))" not in jsx


def test_canvas_wire_click_focuses_backing_wire_node_for_properties():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas_full = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    node_canvas = jsx[
        jsx.index("{visibleWires.map(w => {"):
        jsx.index("{/* Wire-in-flight preview", jsx.index("{visibleWires.map(w => {"))
    ]

    assert "const focusWorkflowWireNode = React.useCallback((wire, index) => {" in node_canvas_full
    assert "const selection = workflowWireSelectionForRenderedWire(LM_GRAPH, wire, index);" in node_canvas_full
    assert "setSelectedWire(selection);" in node_canvas_full
    assert "window.__archhub_active_canvas_wire_selection = selection;" in node_canvas_full
    assert "const selectedWireStateNodeId = syncGrandMapCanvasSelectedWireState(selection);" in node_canvas_full
    assert "window.__archhub_last_canvas_wire_selection_sync = {" in node_canvas_full
    assert "const wireNodeId = selection.wireNodeId || ((wire && wire.data && wire.data.relation_node)" in node_canvas_full
    assert "|| workflowWireRelationNodeIdForWire(wire, index));" in node_canvas_full
    assert "try { materializeWorkflowWireNodes(LM_GRAPH); } catch (_e) {}" in node_canvas_full
    assert "setFocusId(wireNodeId);" in node_canvas_full
    assert "source: 'canvas-wire'" in node_canvas_full
    assert "const isSel = workflowWireSelectionMatchesRenderedWire(selectedWire, w);" in node_canvas
    assert "const backingWireNodeId = (w.raw && w.raw.data && w.raw.data.relation_node)" in node_canvas
    assert "|| workflowWireRelationNodeIdForWire(w.raw, w.i);" in node_canvas
    assert "focusWorkflowWireNode(w.raw, w.i);" in node_canvas
    assert "const focusedWireNodeId = focusWorkflowWireNode(w.raw, w.i) || backingWireNodeId;" in node_canvas
    assert "const selection = workflowWireSelectionForRenderedWire(LM_GRAPH, w.raw, w.i);" in node_canvas
    assert "wireNodeId: focusedWireNodeId || selection.wireNodeId" in node_canvas
    assert "window.__archhub_active_canvas_wire_selection = null;" in node_canvas_full


def test_canvas_wire_renderer_accepts_object_endpoint_anatomy_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    wires_memo = node_canvas[
        node_canvas.index("const wires = React.useMemo(() => (allWiresRaw || []).map((w, i) => {"):
        node_canvas.index("}).filter(Boolean), [nodeById, focusId, allWiresRaw, graphBump, selectedWirePathNodeSet, selectedWirePathTargetWireNodeId]);")
    ]
    visible_wires = node_canvas[
        node_canvas.index("{visibleWires.map(w => {"):
        node_canvas.index("{/* Wire-in-flight preview", node_canvas.index("{visibleWires.map(w => {"))
    ]

    assert "const fromNodeId = wireEndpointNodeId(w && w.from);" in wires_memo
    assert "const fromPortId = wireEndpointPortId(w && w.from);" in wires_memo
    assert "const toNodeId = wireEndpointNodeId(w && w.to);" in wires_memo
    assert "const toPortId = wireEndpointPortId(w && w.to);" in wires_memo
    assert "const from = resolveEndpoint(fromNodeId, fromPortId, 'out');" in wires_memo
    assert "const to   = resolveEndpoint(toNodeId,   toPortId,   'in');" in wires_memo
    assert "fromNodeId, fromPortId, toNodeId, toPortId" in wires_memo
    assert "data-wire-from={w.fromNodeId}" in visible_wires
    assert "data-wire-to={w.toNodeId}" in visible_wires


def test_canvas_wire_endpoint_coordinates_default_missing_node_dimensions():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const resolveEndpoint = (nodeId, portId, side /* 'in'|'out' */) =>"):
        jsx.index("// Memoized \u2014 endpoint resolution", jsx.index("const resolveEndpoint = (nodeId, portId, side /* 'in'|'out' */) =>"))
    ]

    assert "const nx = Number.isFinite(Number(node.x)) ? Number(node.x) : 0;" in node_canvas
    assert "const ny = Number.isFinite(Number(node.y)) ? Number(node.y) : 0;" in node_canvas
    assert "const nw = Number.isFinite(Number(node.w)) ? Number(node.w) : 220;" in node_canvas
    assert "const x = side === 'out' ? (nx + nw) : nx;" in node_canvas
    assert "return { x, y: ny + socketY(idx), t: portsList[idx]?.t };" in node_canvas
    assert "node.x + node.w" not in node_canvas
    assert "node.y + socketY(idx)" not in node_canvas


def test_canvas_operations_use_endpoint_helpers_for_object_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    legacy_patterns = (
        "w.from[0]",
        "w.from[1]",
        "w.to[0]",
        "w.to[1]",
        "w.raw.from[0]",
        "w.raw.to[0]",
    )
    for pattern in legacy_patterns:
        assert pattern not in node_canvas
    assert "wireEndpointNodeId(w && w.from)" in node_canvas
    assert "wireEndpointPortId(w && w.from)" in node_canvas
    assert "wireEndpointNodeId(w && w.to)" in node_canvas
    assert "wireEndpointPortId(w && w.to)" in node_canvas
    assert "const fromDragged = idSet.has(w.fromNodeId);" in node_canvas
    assert "const toDragged   = idSet.has(w.toNodeId);" in node_canvas
    assert "const _src = w => wireEndpointNodeId(w && w.from) || w.src_node;" in node_canvas
    assert "const _dst = w => wireEndpointNodeId(w && w.to) || w.dst_node;" in node_canvas


def test_structural_graph_actions_record_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const recordGraphOperationNode ="):
        jsx.index("const putGrandMapSlot =", jsx.index("const recordGraphOperationNode ="))
    ]
    workflow_filters = jsx[
        jsx.index("const isWorkflowGraphNode ="):
        jsx.index("const isVisibleWorkflowCanvasNode =", jsx.index("const isWorkflowGraphNode ="))
    ]
    remove_wire = jsx[
        jsx.index("const removeWorkflowWireRelation ="):
        jsx.index("const workflowGraphSnapshot =", jsx.index("const removeWorkflowWireRelation ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    node_actions = jsx[
        jsx.index("const NodeActionsSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeActionsSurface ="))
    ]

    assert "role: 'graph_operation'" in helper
    assert "kind: 'history'" in helper
    assert "capabilities: ['audit', 'replay_intent', 'explain_mutation']" in helper
    assert "materializeGrandMapParamNode(opId, 'operation', operation);" in helper
    assert "materializeGrandMapParamNode(opId, 'target_ids', targetIds);" in helper
    assert "materializeGrandMapParamNode(opId, 'payload_json', payloadJson);" in helper
    assert "window.ahSetUiNodeParam(opId, 'operation', operation);" not in helper
    assert "window.ahSetUiNodeParam(opId, 'target_ids', targetIds);" not in helper
    assert "window.ahSetUiNodeParam(opId, 'payload_json', payloadJson);" not in helper
    assert "role: 'graph_operation_target'" in helper
    assert "relation: 'operates_on'" in helper
    assert "const recordUiActionOperationNode = (graph, detail, route, operation, payload, options) =>" in helper
    assert "role: 'ui_action_operation_route'" in helper
    assert "relation: 'invokes_operation'" in helper
    assert "handler_node: r.handler_node_id" in helper
    assert "if (data.role === 'graph_operation' || data.role === 'graph_operation_target') return false;" in workflow_filters
    assert "id.indexOf('param:op:graph:') === 0" in workflow_filters
    assert "owner.indexOf('op:graph:') === 0" in workflow_filters
    assert "recordGraphOperationNode(g, 'wire.delete'" in remove_wire
    assert "affected_wire_ids: affectedWireIds" in remove_wire
    assert "recordGraphOperationNode(LM_GRAPH, 'node.duplicate'" in node_canvas
    assert "recordGraphOperationNode(LM_GRAPH, 'node.disconnect'" in node_canvas
    assert "recordGraphOperationNode(LM_GRAPH, 'node.delete'" in node_canvas
    assert "source: 'keyboard'" in node_canvas
    assert "wireTargets:false" in node_canvas
    assert "recordGraphOperationNode(LM_GRAPH, 'node.branch'" in node_actions
    assert "source: 'right_rail'" in node_actions
    assert "if (removeWorkflowWireRelation(LM_GRAPH, wireNodeId)) removed += 1;" in node_canvas
    assert "try { materializeWorkflowWireNodes(LM_GRAPH); } catch (_e) {}" in node_canvas
    assert "replaceWorkflowGraphFromResult(result.graph);" in node_canvas
    assert "replaceWorkflowGraphFromResult(result.graph);" in node_actions


def test_home_actions_route_through_component_handler_and_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    home = jsx[
        jsx.index("const Home ="):
        jsx.index("const SessionThumb =", jsx.index("const Home ="))
    ]

    assert "const bindHomeAction = (capability, callback) => registerUiHostCapability" in home
    assert "bindHomeAction('session.create'" in home
    assert "bindHomeAction('sessions.filter.set'" in home
    assert "bindHomeAction('sessions.select.toggle'" in home
    assert "bindHomeAction('sessions.selected.delete'" in home
    assert "bindHomeAction('sessions.sync'" in home
    assert "bindHomeAction('model.picker.open'" in home
    assert "bindHomeAction('account.open'" in home
    assert "bindHomeAction('brain.folders.open'" in home
    assert "bindHomeAction('graph.health.open'" in home
    graph_health_branch = home[
        home.index("bindHomeAction('graph.health.open'"):
        home.index("bindHomeAction('composer.attach'")
    ]
    assert "focusGrandMapApplicationSuperNode();" in graph_health_branch
    assert "bindHomeAction('composer.submit'" in home
    assert "bindHomeAction('composer.form.submit'" in home
    assert "bindHomeAction('composer.text.update'" in home
    assert "setTitle(args.value || '');" in home


def test_canvas_wire_presentation_layer_controls_drawn_path():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    wires_memo = jsx[
        jsx.index("const wires = React.useMemo(() => (allWiresRaw || []).map((w, i) => {"):
        jsx.index("}).filter(Boolean), [nodeById, focusId, allWiresRaw, graphBump, selectedWirePathNodeSet, selectedWirePathTargetWireNodeId]);")
    ]
    node_canvas = jsx[
        jsx.index("{visibleWires.map(w => {"):
        jsx.index("{/* Wire-in-flight preview", jsx.index("{visibleWires.map(w => {"))
    ]

    assert "const wirePresentation = String((w.presentation || (w.data && w.data.presentation) || 'canvas-bezier')).toLowerCase();" in wires_memo
    assert "wirePresentation.indexOf('straight') >= 0" in wires_memo
    assert "wirePresentation.indexOf('orthogonal') >= 0 || wirePresentation.indexOf('elbow') >= 0" in wires_memo
    assert "presentation: wirePresentation" in wires_memo
    assert "data-wire-presentation={w.presentation}" in node_canvas


def test_canvas_wire_runtime_node_controls_drawn_edge():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    wires_memo = jsx[
        jsx.index("const wires = React.useMemo(() => (allWiresRaw || []).map((w, i) => {"):
        jsx.index("}).filter(Boolean), [nodeById, focusId, allWiresRaw, graphBump, selectedWirePathNodeSet, selectedWirePathTargetWireNodeId]);")
    ]
    node_canvas = jsx[
        jsx.index("{visibleWires.map(w => {"):
        jsx.index("{/* Wire-in-flight preview", jsx.index("{visibleWires.map(w => {"))
    ]

    assert "const edgeData = w && w.data && typeof w.data === 'object' ? w.data : {};" in wires_memo
    assert "const backingWireNodeId = edgeData.relation_node || workflowWireRelationNodeIdForWire(w, i);" in wires_memo
    assert "const authorityWireData = backingWireNode" in wires_memo
    assert "? nodeConnectionWireAuthorityData(LM_GRAPH, backingWireNode, w)" in wires_memo
    assert "const runtimeFromNodeId = authorityWireData.from_node || authorityWireData.source_owner || fromNodeId;" in wires_memo
    assert "const runtimeFromPortId = authorityWireData.from_port || fromPortId;" in wires_memo
    assert "const live = (LM_GRAPH.nodes ? LM_WIRE_STATE[lmWireEdgeId(w)] : null);" in wires_memo
    assert "const runtime = backingWireNode" in wires_memo
    assert "? nodeConnectionWireRuntimeState(authorityWireData, live || {})" in wires_memo
    assert "const runtimeNodeId = runtime && backingWireNode" in wires_memo
    assert "? syncWireRuntimeNode(LM_GRAPH, backingWireNode.id, runtime, rawRuntimeValue, runtimeDisplayValue" in wires_memo
    assert "const runtimeData = Object.assign({}, runtime || {}, (runtimeNode && runtimeNode.data) || {});" in wires_memo
    assert "const runtimeGateState = String(runtimeData.gate_state || 'open');" in wires_memo
    assert "const runtimePresentationState = String(runtimeData.presentation_state || 'visible');" in wires_memo
    assert "const runtimeActive = Object.prototype.hasOwnProperty.call(runtimeData, 'active')" in wires_memo
    assert "|| runtimeGateState === 'blocked'" in wires_memo
    assert "|| runtimePresentationState === 'hidden'" in wires_memo
    assert "|| runtimeActive === false" in wires_memo
    assert "runtimeNodeId," in wires_memo
    assert "runtimeGateState," in wires_memo
    assert "runtimeActive," in wires_memo
    assert "const runtimeJunctionNodeId = authorityWireData.junction_node || '';" in wires_memo
    assert "const runtimeSummary = runtime ? nodeConnectionRuntimeSummary(runtimeData) : '';" in wires_memo
    assert "runtimeJunctionNodeId," in wires_memo
    assert "runtimeSummary," in wires_memo
    assert "runtimeDisplayValue," in wires_memo
    assert "runtimePresentationState," in wires_memo
    assert "const runtimeBlocked = w.runtimeGateState === 'blocked';" in node_canvas
    assert "const runtimeHidden = w.runtimePresentationState === 'hidden';" in node_canvas
    assert "const runtimeProtected = !!(w.runtimeEncryptionState && w.runtimeEncryptionState !== 'clear');" in node_canvas
    assert "const runtimeEncoded = !!(w.runtimeCodec && w.runtimeCodec !== 'none');" in node_canvas
    assert "const baseStroke = runtimeBlocked ? LM.err" in node_canvas
    assert "const baseDash = runtimeBlocked ? '2 6'" in node_canvas
    assert "runtimeEncoded ? '10 3 2 3'" in node_canvas
    assert "data-wire-node-id={backingWireNodeId || ''}" in node_canvas
    assert "data-wire-junction-node-id={w.runtimeJunctionNodeId || ''}" in node_canvas
    assert "data-wire-runtime-node-id={w.runtimeNodeId || ''}" in node_canvas
    assert "data-wire-runtime-display={w.runtimeDisplayValue || ''}" in node_canvas
    assert "data-wire-runtime-summary={w.runtimeSummary || ''}" in node_canvas
    assert "data-wire-gate-state={w.runtimeGateState || ''}" in node_canvas
    assert "data-wire-active={w.runtimeActive ? 'true' : 'false'}" in node_canvas
    assert "{w.animated && w.runtimeActive && !runtimeHidden && !runtimeBlocked && (" in node_canvas


def test_canvas_selected_wire_path_controls_drawn_edges():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas_inner = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    wires_memo = jsx[
        jsx.index("const selectedWirePathNodeIds = React.useMemo(() => {"):
        jsx.index("}).filter(Boolean), [nodeById, focusId, allWiresRaw, graphBump", jsx.index("const selectedWirePathNodeIds = React.useMemo(() => {"))
    ]
    render = jsx[
        jsx.index("{visibleWires.map(w => {"):
        jsx.index("{/* Wire-in-flight preview", jsx.index("{visibleWires.map(w => {"))
    ]

    assert "const selectedWirePathNodeIds = React.useMemo(() => {" in node_canvas_inner
    assert "nodeConnectionWireJunctionMemberNodeIds(LM_GRAPH, junctionNodeId).forEach(add);" in wires_memo
    assert "const selectedWirePathNodeSet = React.useMemo(" in node_canvas_inner
    assert "const selectedWirePathTargetWireNodeId = React.useMemo(() => {" in node_canvas_inner
    assert "const selectedPath = !!(backingWireNodeId && selectedWirePathNodeSet.has(backingWireNodeId));" in wires_memo
    assert "const selectedPathJunction = !!(runtimeJunctionNodeId && selectedWirePathNodeSet.has(runtimeJunctionNodeId));" in wires_memo
    assert "const selectedPathRole = selectedPath" in wires_memo
    assert "selectedPath," in wires_memo
    assert "selectedPathJunction," in wires_memo
    assert "selectedPathRole," in wires_memo
    assert "const isSelectedPathWire = !!(w.selectedPath || w.selectedPathJunction);" in render
    assert "data-wire-selected-path={isSelectedPathWire ? 'true' : 'false'}" in render
    assert "data-wire-selected-path-role={w.selectedPathRole || ''}" in render
    assert "{isSelectedPathWire && (" in render
    assert "stroke={LM.accent}" in render
    assert "strokeWidth={strokeW + 6}" in render
    assert "filter={(w.focused || isSel || isSelectedPathWire) ? \"url(#lm-wire-glow)\" : undefined}" in render


def test_canvas_debug_state_exposes_wire_relation_runtime_metadata():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("window.__archhub_wire_anatomy_state = {"):
        jsx.index("const toggleExpanded =", jsx.index("window.__archhub_wire_anatomy_state = {"))
    ]

    assert "junction: w && w.runtimeJunctionNodeId" in node_canvas
    assert "gate: w && w.runtimeGateState" in node_canvas
    assert "codec: w && w.runtimeCodec" in node_canvas
    assert "encryption: w && w.runtimeEncryptionState" in node_canvas
    assert "display: w && w.runtimeDisplayValue" in node_canvas


def test_workflow_done_edges_state_preserves_wire_runtime_layers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    prelude = jsx[
        jsx.index("// Apply a runner `edges_state` array"):
        jsx.index("const _applyEdgesState = (edges) => {")
    ]
    handler = jsx[
        jsx.index("const _applyEdgesState = (edges) => {"):
        jsx.index("// Workflow / node cook result.", jsx.index("const _applyEdgesState = (edges) => {"))
    ]

    assert "edges_state` array ([{id,state,...wire layers}])" in prelude
    assert "const next = Object.assign({}, e);" in handler
    assert "next.state = e.state || 'idle';" in handler
    assert "next.preview = e.preview || e.value_preview || '';" in handler
    assert "LM_WIRE_STATE[String(e.id)] = next;" in handler


def test_canvas_wire_actions_mutate_relation_node_not_only_drawn_line():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const workflowWireRelationNodeIdForWire ="):
        jsx.index("const workflowGraphSnapshot =", jsx.index("const workflowWireRelationNodeIdForWire ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const resolveWorkflowWireRelation = (graph, selection) =>" in helpers
    assert "const workflowWireEndpointWithPort = (endpoint, fallbackNode, nextPort) =>" in helpers
    assert "const workflowWireShouldMaterializeRawEdge = (wire) =>" in jsx
    assert "workflowWireInternalRelationRoles.has(role)" in jsx
    assert "const family = String(data.wire_family || data.relation_wire_family || '');" in jsx
    assert "if (family && family !== 'workflow_wire') return false;" in jsx
    assert "wireId.indexOf('w:workflow-wire-layer:') === 0" in jsx
    assert "!workflowWireShouldMaterializeRawEdge(wire)" in jsx
    assert "!isVisibleWorkflowCanvasNode(fromOwner) || !isVisibleWorkflowCanvasNode(toOwner)" in jsx
    assert "const refreshWorkflowWireRuntimeNode = (graph, wireNodeId) =>" in helpers
    assert "const setWorkflowWireLayerValue = (graph, selection, key, value) =>" in helpers
    assert "const authorityData = nodeConnectionWireAuthorityData(g, wireNode, presentationWire);" in helpers
    assert "const live = nodeConnectionLiveWireState(" in helpers
    assert "const runtime = nodeConnectionWireRuntimeState(authorityData, live || {});" in helpers
    assert "const displayValue = nodeConnectionRuntimeDisplayValue(rawValue, runtime);" in helpers
    assert "return syncWireRuntimeNode(g, wireNodeId, runtime, rawValue, displayValue" in helpers
    assert "const removeWorkflowWireRelation = (graph, selection) =>" in helpers
    assert "const layerSpec = WORKFLOW_WIRE_LAYER_SPECS.find(spec => spec && spec.valueKey === key);" in helpers
    assert "ref.node.data.layer_nodes[layerSpec.id]" in helpers
    assert "materializeGrandMapParamNode(layerNodeId, 'value', value)" in helpers
    assert "window.ahSetUiNodeParam(layerNodeId, 'value', value)" not in helpers
    assert "ref.wire.from = workflowWireEndpointWithPort(ref.wire.from, ref.fromNode, value);" in helpers
    assert "ref.wire.to = workflowWireEndpointWithPort(ref.wire.to, ref.toNode, value);" in helpers
    assert "data.relation_node === ref.wireNodeId" in helpers
    assert "wireEndpointNodeId(wire && wire.from) === ref.wireNodeId" in helpers
    assert "try { materializeWorkflowWireNodes(g); } catch (_e) {}" in helpers
    assert "try { refreshWorkflowWireRuntimeNode(graph || LM_GRAPH, ref.wireNodeId); } catch (_e) {}" in helpers
    assert "const handleRelationNodeParamUpdateAction = (detail) =>" in helpers
    assert "d.__relation_param_handled || d.action !== 'node.param.update'" in helpers
    assert "data.role === 'wire' && data.wire_family === 'workflow_wire'" in helpers
    assert "changed = setWorkflowWireLayerValue(g, node.id, key, args.value);" in helpers
    assert "data.role === 'wire_layer' && key === 'value'" in helpers
    assert "changed = setWorkflowWireLayerValue(g, ownerWireId, layerValueKey, args.value);" in helpers
    assert "d.__relation_param_handled = true;" in helpers
    assert "materializeGrandMapParamNode(args.value_slot, 'value', args.value);" in helpers
    assert "window.ahSetUiNodeParam(args.value_slot, 'value', args.value);" not in helpers
    assert "window.__archhubBumpGraph && window.__archhubBumpGraph();" in helpers
    assert "try { if (typeof saveCurrentGraph === 'function') saveCurrentGraph(); } catch (_e) {}" in helpers
    assert "registerUiHostCapability('node.param.update'" in jsx
    assert "handleRelationNodeParamUpdateAction(d)" in jsx

    assert "removeWorkflowWireRelation(LM_GRAPH, selectedWire)" in node_canvas
    assert "removeWorkflowWireRelation(LM_GRAPH, wireMenu)" in node_canvas
    assert "resolveWorkflowWireRelation(LM_GRAPH, wireMenu)" in node_canvas
    assert "const wireMenuLayerState = React.useMemo(() => {" in node_canvas
    assert "gateBlocked: String(read('gate_policy') || '') === 'deny'" in node_canvas
    assert "codecBase64: String(read('codec') || '') === 'base64'" in node_canvas
    assert "presentationHidden: String(read('presentation') || '') === 'hidden'" in node_canvas
    assert "const applyWireMenuLayerValue = React.useCallback((key, value, label) => {" in node_canvas
    assert "setWorkflowWireLayerValue(LM_GRAPH, selection, key, value)" in node_canvas
    assert "setWireFieldPicker({ wireIdx: wireMenu.idx, wireNodeId: ref.wireNodeId, side: 'src', paths });" in node_canvas
    assert "setWireFieldPicker({ wireIdx: wireMenu.idx, wireNodeId: ref.wireNodeId, side: 'dst', paths });" in node_canvas
    assert "gateBlocked={wireMenuLayerState.gateBlocked}" in node_canvas
    assert "codecBase64={wireMenuLayerState.codecBase64}" in node_canvas
    assert "presentationHidden={wireMenuLayerState.presentationHidden}" in node_canvas
    assert "onToggleGate={() => {" in node_canvas
    assert "onToggleCodec={() => {" in node_canvas
    assert "onTogglePresentation={() => {" in node_canvas
    assert "wireMenuLayerState.gateBlocked ? 'type-compatible-and-enabled' : 'deny'" in node_canvas
    assert "wireMenuLayerState.codecBase64 ? 'none' : 'base64'" in node_canvas
    assert "wireMenuLayerState.presentationHidden ? 'canvas-bezier' : 'hidden'" in node_canvas
    assert "const selection = { idx: wireFieldPicker.wireIdx, wireNodeId: wireFieldPicker.wireNodeId };" in node_canvas
    assert "setWorkflowWireLayerValue(LM_GRAPH, selection, wireFieldPicker.side === 'src' ? 'src_field' : 'dst_field', path)" in node_canvas
    assert "LM_GRAPH.wires = (LM_GRAPH.wires || []).filter((_, i) => i !== wireMenu.idx);" not in node_canvas


def test_app_relation_wire_layer_helper_uses_app_relation_contract():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const resolveAppRelationWireRelation ="):
        jsx.index("const ensureGrandMapApplicationSuperNode =", jsx.index("const resolveAppRelationWireRelation ="))
    ]
    layer_specs = jsx[
        jsx.index("const WIRE_LAYER_OPTION_SETS ="):
        jsx.index("const appRelationWireLayerSpecForKey =", jsx.index("const WIRE_LAYER_OPTION_SETS ="))
    ]

    assert "const WIRE_LAYER_OPTION_SETS = {" in layer_specs
    assert "value_type: ['any'" not in layer_specs
    assert "gate_policy: ['allow-if-target-exists', 'allow-if-source-and-target-exist', 'allow-if-owner-and-action-exist', 'allow-if-handler-exists', 'allow-if-slot-present', 'allow-if-host-present', 'allow-if-slot-and-host-exist', 'type-compatible-and-enabled', 'allow-reviewed', 'deny', 'require-scope', 'require-schema', 'require-secret-clearance']" in layer_specs
    assert "codec: ['none', 'text', 'json', 'react', 'base64', 'binary', 'image-uri', 'geometry-json', 'ifc-fragment', 'speckle-object']" in layer_specs
    assert "encryption: ['none', 'aes-gcm', 'fernet', 'local-key', 'workspace-key', 'user-key', 'external-kms', 'secret-ref', 'redacted']" in layer_specs
    assert "behavior: ['mediate-relation', 'drive-active-right-rail', 'provide-render-slot', 'mount-render-slot', 'provide-ui-binding-value', 'consume-ui-binding-value', 'bind-ui-value', 'emit-ui-action', 'configure-ui-action', 'route-ui-action', 'operate-on-node', 'parameter-set', 'data-flow', 'pull-on-demand', 'force-recook', 'control-flow', 'transform', 'validate', 'render', 'encrypt', 'decrypt']" in layer_specs
    assert "presentation: ['surface-relation', 'focus-relation', 'ui-slot', 'ui-slot-host', 'ui-binding', 'ui-binding-source', 'ui-binding-target', 'ui-action', 'ui-action-param', 'ui-action-handler', 'ui-action-target', 'canvas-bezier', 'inspector-row', 'port-chip', 'layer-chip', 'geometry-preview', 'image-preview', 'hidden']" in layer_specs
    assert "const wireLayerParamType = (spec) => wireLayerParamOptions(spec).length > 0 ? 'select' : 'text';" in layer_specs
    assert "const valueType = options.length > 0 ? 'select' : wireLayerParamType(spec);" in layer_specs
    assert "syncWireLayerParam(layerNode, 'value', 'value', valueType, value, options);" in layer_specs
    assert "{ id:'type', valueKey:'value_type', title:'Type layer', capabilities:['type_check', 'schema_ref'] }" in layer_specs
    assert "options:WIRE_LAYER_OPTION_SETS.gate_policy" in layer_specs
    assert "options:WIRE_LAYER_OPTION_SETS.codec" in layer_specs
    assert "options:WIRE_LAYER_OPTION_SETS.encryption" in layer_specs
    assert "options:WIRE_LAYER_OPTION_SETS.behavior" in layer_specs
    assert "options:WIRE_LAYER_OPTION_SETS.presentation" in layer_specs
    assert "const resolveAppRelationWireRelation = (graph, selection) =>" in helpers
    assert "const setAppRelationWireLayerValue = (graph, selection, key, value) =>" in helpers
    assert "appRelationWireLayerSpecForKey(paramKey)" in helpers
    assert "appRelationWireParamLabel(paramKey)" in helpers
    assert "param.type = wireLayerParamType(layerSpec);" in helpers
    assert "const options = wireLayerParamOptions(layerSpec);" in helpers
    assert "layerParam.type = wireLayerParamType(layerSpec);" in helpers
    assert "const relationWire = wires.find(w => {" in helpers
    assert "wd.role !== 'wire_endpoint'" in helpers
    assert "wd.role !== 'wire_layer_link'" in helpers
    assert "relationWire," in helpers
    assert "materializeGrandMapParamNode(ref.wireNodeId, paramKey, paramValue)" in helpers
    assert "window.ahSetUiNodeParam(ref.wireNodeId, paramKey, paramValue)" not in helpers
    assert "ref.relationWire[paramKey] = paramValue;" in helpers
    assert "ref.relationWire.data = Object.assign({}, ref.relationWire.data || {}, { [paramKey]: paramValue });" in helpers
    assert "materializeGrandMapParamNode(layerNode, 'value', paramValue)" in helpers
    assert "window.ahSetUiNodeParam(layerNode.id, 'value', paramValue)" not in helpers
    assert "setWireNodeValue('port_binding', [fromPortNode || ref.sourceOwner, toPortNode || ref.targetOwner].join(' -> '));" in helpers
    assert "ref.fromEndpoint.from = appRelationWireEndpointWithNode(" in helpers
    assert "ref.toEndpoint.to = appRelationWireEndpointWithNode(" in helpers
    assert "ref.relationWire.from = appRelationWireEndpointWithNode(" in helpers
    assert "ref.relationWire.to = appRelationWireEndpointWithNode(" in helpers
    assert "data.relation_node !== ref.wireNodeId" in helpers
    assert "data.from_port_node = value;" in helpers
    assert "data.to_port_node = value;" in helpers


def test_right_rail_edits_workflow_wire_node_through_relation_helper():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeActionsSurface =")
    ]
    update_branch = properties_surface[
        properties_surface.index("if (d.action === 'node.param.update') {"):
        properties_surface.index("} else if (d.action === 'node.param.promote') {")
    ]

    assert "node.data.role === 'selected_wire_path_wire'" in properties_surface
    assert "const isWorkflowWireNode = isRelationWireNode && node.data.role === 'wire' && node.data.wire_family === 'workflow_wire';" in properties_surface
    assert "const isSelectedPathWireNode = isRelationWireNode && node.data.role === 'selected_wire_path_wire' && node.data.wire_family === 'canvas_selected_wire';" in properties_surface
    assert "node.data.wire_family === 'application_boundary'" in properties_surface
    assert "isSelectedPathWireNode" in properties_surface
    assert "if (isWorkflowWireNode) {" in update_branch
    assert "setWorkflowWireLayerValue(LM_GRAPH, node.id, d.args.key, d.args.value);" in update_branch
    assert "} else if (isAppRelationWireNode) {" in update_branch
    assert "setAppRelationWireLayerValue(LM_GRAPH, node.id, d.args.key, d.args.value);" in update_branch
    assert "applyGrandMapNodeParamEdit(node, { [d.args.key]: d.args.value }" in update_branch
    assert "operation: 'right-rail.param.edit'" in update_branch
    assert "} else if (window.ahSetUiNodeParam) {" not in update_branch
    assert "registerUiHostCapability('node.param.update'" in properties_surface
    assert "registerUiHostCapability('node.param.promote'" in properties_surface
    assert "registerUiHostCapability('node.param.focus'" in properties_surface
    assert "handler_node_id:authority && authority.handlerNode && authority.handlerNode.id || ''" in properties_surface
    assert "handler_node_id: route.handler_node_id || ''" in properties_surface
    assert "isRelationWireNode" in properties_surface[properties_surface.index("}, [node && node.id"):]


def test_workflow_wire_endpoint_node_params_rewire_relation_endpoint():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const setWorkflowWireLayerValue ="):
        jsx.index("const removeWorkflowWireRelation =", jsx.index("const setWorkflowWireLayerValue ="))
    ]

    assert "if (key === 'from_node') {" in helper
    assert "ref.wire.from = workflowWireEndpointWithPort(ref.wire.from, value, ref.fromPort);" in helper
    assert "source_owner: value" in helper
    assert "from_node: value" in helper
    assert "} else if (key === 'to_node') {" in helper
    assert "ref.wire.to = workflowWireEndpointWithPort(ref.wire.to, value, ref.toPort);" in helper
    assert "target_owner: value" in helper
    assert "to_node: value" in helper
    assert "} else if (key === 'from_port') {" in helper
    assert "try { materializeWorkflowWireNodes(graph || LM_GRAPH); } catch (_e) {}" in helper


def test_node_properties_rows_display_param_labels_but_keep_wiring_keys():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="))
    ]

    assert "const label = String((p && (p.label || p.k)) || key);" in clone
    assert "[keySlot]: label" in clone
    assert "syncGrandMapSurfaceStateSlots('node-property-param-row-'" not in clone
    assert "state_key: 'node_property_param_row_state_node_id'" not in clone
    assert "'data-param-key': key" in clone
    assert "'data-param-owner': node.id" in clone
    assert "copy.data.args = Object.assign({}, copy.data.args || {}, {" in clone
    assert "node_id: node.id" in clone
    assert "param_node_id: paramNodeId" in clone
    assert "wire_layer: p && p.wire_layer ? p.wire_layer : ''" in clone
    assert "wire_layer_node_id: p && p.wire_layer_node_id ? p.wire_layer_node_id : ''" in clone
    assert "value_slot: valueSlot" in clone
    assert "key," in clone
    assert "if (p && p.wire_layer) copy.data.data_attrs['data-wire-layer'] = p.wire_layer;" in clone
    assert "if (p && p.wire_layer_node_id) copy.data.data_attrs['data-wire-layer-node'] = p.wire_layer_node_id;" in clone
    assert "const label = String((p && (p.label || p.k)) || key);" in fallback
    assert "text:label" in fallback
    assert "'data-param-owner':node.id" in fallback
    assert "const wireLayerNodeId = p && p.wire_layer_node_id ? p.wire_layer_node_id : '';" in fallback
    assert "const wireLayer = p && p.wire_layer ? p.wire_layer : '';" in fallback
    assert "'data-wire-layer':wireLayer" in fallback
    assert "'data-wire-layer-node':wireLayerNodeId" in fallback
    assert "args:{ node_id:node.id, key, param_node_id:paramNodeId, focus_node_id:focusNodeId, read_only:readOnly, wire_layer:wireLayer, wire_layer_node_id:wireLayerNodeId, runtime_node_id:runtimeNodeId, runtime_key:runtimeKey }" in fallback
    assert "syncGrandMapSurfaceStateSlots('node-property-param-row-'" not in fallback
    assert "state_key: 'node_property_param_row_state_node_id'" not in fallback


def test_workflow_wire_layer_params_surface_as_layer_rows():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const WORKFLOW_WIRE_LAYER_SPECS ="):
        jsx.index("const workflowWireRelationNodeIdForWire =", jsx.index("const WORKFLOW_WIRE_LAYER_SPECS ="))
    ]

    assert "{ k:'gate_policy', label:workflowWireParamLabel('gate_policy'), type:'text', v:gatePolicy }" in helpers
    assert "{ k:'codec', label:workflowWireParamLabel('codec'), type:'text', v:codec }" in helpers
    assert "{ k:'encryption', label:workflowWireParamLabel('encryption'), type:'text', v:encryption }" in helpers
    assert "{ k:'behavior', label:workflowWireParamLabel('behavior'), type:'text', v:behavior }" in helpers
    assert "{ k:'presentation', label:workflowWireParamLabel('presentation'), type:'text', v:presentation }" in helpers
    assert "const WORKFLOW_WIRE_LAYER_SPECS = wireLayerSpecsForContext({" in helpers
    assert "options:WIRE_LAYER_OPTION_SETS.value_type" not in jsx
    assert "options:WIRE_LAYER_OPTION_SETS.codec" in jsx
    assert "const workflowWireEndpointPortOptions = (graph, nodeId, side) =>" in helpers
    assert "if (spec && spec.valueKey === 'from_port')" in helpers
    assert "return workflowWireEndpointPortOptions(graph, source.from_node || source.source_owner, 'out');" in helpers
    assert "if (spec && spec.valueKey === 'to_port')" in helpers
    assert "return workflowWireEndpointPortOptions(graph, source.to_node || source.target_owner, 'in');" in helpers
    assert "value_control: valueControl" in helpers
    assert "value_options: valueOptions" in helpers
    assert "type:valueControl" in helpers
    assert "options:valueOptions" in helpers
    assert "const paramLabel = workflowWireParamLabel(key);" in helpers
    assert "if (p.label !== paramLabel) { p.label = paramLabel; changed = true; }" in helpers
    assert "const layerSpec = workflowWireLayerSpecForKey(key);" in helpers
    assert "const paramType = workflowWireLayerParamType(g, layerSpec, payload);" in helpers
    assert "const options = workflowWireLayerParamOptions(g, layerSpec, payload);" in helpers
    assert "p.type = paramType;" in helpers
    assert "p.options = options;" in helpers
    assert "nextParam.wire_layer = layerSpec.id;" in helpers
    assert "nextParam.wire_layer_node_id = layerNodeId;" in helpers


def test_right_rail_edits_workflow_wire_layer_node_through_parent_wire_relation():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeActionsSurface =")
    ]
    update_branch = properties_surface[
        properties_surface.index("if (d.action === 'node.param.update') {"):
        properties_surface.index("} else if (d.action === 'node.param.promote') {")
    ]
    helper = jsx[
        jsx.index("const setWorkflowWireLayerValue ="):
        jsx.index("const removeWorkflowWireRelation =", jsx.index("const setWorkflowWireLayerValue ="))
    ]

    assert "const isRelationWireLayerNode = node && node.data && node.data.role === 'wire_layer';" in properties_surface
    assert "const isWorkflowWireLayerNode = isRelationWireLayerNode && node.data.wire_family === 'workflow_wire';" in properties_surface
    assert "const isAppRelationWireLayerNode = isRelationWireLayerNode && (" in properties_surface
    assert "node.data.wire_family === 'application_boundary'" in properties_surface
    assert "node.data.wire_family === 'canvas_selected_wire'" in properties_surface
    assert "} else if (isRelationWireLayerNode && d.args.key === 'value') {" in update_branch
    assert "const ownerWireId = (node.data && (node.data.owner || node.data.parent))" in update_branch
    assert "const layerValueKey = (node.data && node.data.value_key)" in update_branch
    assert "recookNodeId = ownerWireId;" in update_branch
    assert "if (isWorkflowWireLayerNode) {" in update_branch
    assert "setWorkflowWireLayerValue(LM_GRAPH, ownerWireId, layerValueKey, d.args.value);" in update_branch
    assert "} else if (isAppRelationWireLayerNode) {" in update_branch
    assert "setAppRelationWireLayerValue(LM_GRAPH, ownerWireId, layerValueKey, d.args.value);" in update_branch
    assert "if (isRelationWireLayerNode && !recookNodeId) {" in update_branch
    assert "if (ownerWireId && ownerWireId !== node.id) {" in update_branch
    assert "isRelationWireLayerNode" in properties_surface[properties_surface.index("}, [node && node.id"):]
    assert "try { materializeWorkflowWireNodes(graph || LM_GRAPH); } catch (_e) {}" in helper


def test_workflow_wire_layer_edit_updates_save_snapshot_fields():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const setWorkflowWireLayerValue ="):
        jsx.index("const removeWorkflowWireRelation =", jsx.index("const setWorkflowWireLayerValue ="))
    ]
    listener = jsx[
        jsx.index("const handleRelationNodeParamUpdateAction ="):
        jsx.index("const removeWorkflowWireRelation =", jsx.index("const handleRelationNodeParamUpdateAction ="))
    ]

    assert "ref.node.data = Object.assign({}, ref.node.data || {}, { [key]: value });" in helper
    assert "ref.node.config = Object.assign({}, ref.node.config || {}, { [key]: value });" in helper
    assert "layerNode.data = Object.assign({}, layerNode.data || {}, { value });" in helper
    assert "layerNode.config = Object.assign({}, layerNode.config || {}, { value });" in helper
    assert "ref.wire[key] = value;" in helper
    assert "ref.wire.data = Object.assign({}, ref.wire.data || {}, { [key]: value });" in helper
    assert "materializeGrandMapParamNode(ref.wireNodeId, key, value)" in helper
    assert "window.ahSetUiNodeParam(ref.wireNodeId, key, value)" not in helper
    assert "materializeGrandMapParamNode(layerNodeId, 'value', value)" in helper
    assert "window.ahSetUiNodeParam(layerNodeId, 'value', value)" not in helper
    assert "try { materializeWorkflowWireNodes(graph || LM_GRAPH); } catch (_e) {}" in helper
    assert "try { refreshWorkflowWireRuntimeNode(graph || LM_GRAPH, ref.wireNodeId); } catch (_e) {}" in helper
    assert "try { if (typeof saveCurrentGraph === 'function') saveCurrentGraph(); } catch (_e) {}" in listener
    assert "data.role === 'selected_wire_path_wire' && data.wire_family === 'canvas_selected_wire'" in listener
    assert "data.wire_family === 'canvas_selected_wire'" in listener


def test_node_body_renders_wire_parameter_and_layer_nodes_as_structural_bodies():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_body = jsx[
        jsx.index("const NodeBody ="):
        jsx.index("const structuralValueOf =", jsx.index("const NodeBody ="))
    ]
    wire_body = jsx[
        jsx.index("const WireRelationBody ="):
        jsx.index("const WireLayerBody =", jsx.index("const WireRelationBody ="))
    ]
    layer_body = jsx[
        jsx.index("const WireLayerBody ="):
        jsx.index("const WireRuntimeBody =", jsx.index("const WireLayerBody ="))
    ]
    runtime_body = jsx[
        jsx.index("const WireRuntimeBody ="):
        jsx.index("const ParameterNodeBody =", jsx.index("const WireRuntimeBody ="))
    ]
    parameter_body = jsx[
        jsx.index("const ParameterNodeBody ="):
        jsx.index("// ─── AgDR-0024", jsx.index("const ParameterNodeBody ="))
    ]

    boundary_body = jsx[
        jsx.index("const BoundaryAnatomyBody ="):
        jsx.index("const wireRuntimeNodeForOwner =", jsx.index("const BoundaryAnatomyBody ="))
    ]

    assert "const boundaryRole = n && n.data && n.data.anatomy_boundary_role;" in node_body
    assert "return <BoundaryAnatomyBody n={n}/>;" in node_body
    assert "boundaryRole === 'boundary_port'" in node_body
    assert "boundaryRole === 'target_port'" in node_body
    assert "if (role === 'wire') return <WireRelationBody n={n}/>;" in node_body
    assert "if (role === 'selected_wire_path_wire') return <WireRelationBody n={n}/>;" in node_body
    assert "if (role === 'wire_layer') return <WireLayerBody n={n}/>;" in node_body
    assert "if (role === 'wire_runtime') return <WireRuntimeBody n={n}/>;" in node_body
    assert "if (role === 'parameter') return <ParameterNodeBody n={n}/>;" in node_body
    assert "data-node-structural-body=\"wire\"" in wire_body
    assert "'gate_policy'" in wire_body
    assert "'codec'" in wire_body
    assert "'encryption'" in wire_body
    assert "'behavior'" in wire_body
    assert "'presentation'" in wire_body
    assert "wireRuntimeNodeForOwner(nodeId)" in wire_body
    assert "rowId=\"wire-runtime-node\"" in wire_body
    assert "rowId=\"wire-runtime-gate\"" in wire_body
    assert "rowId=\"wire-runtime-display\"" in wire_body
    assert "data-node-structural-body=\"wire-layer\"" in layer_body
    assert "structuralValueOf(n, 'capabilities')" in layer_body
    assert "data-node-structural-body=\"wire-runtime\"" in runtime_body
    assert "'gate_state'" in runtime_body
    assert "'value_type'" in runtime_body
    assert "'raw_value'" in runtime_body
    assert "'display_value'" in runtime_body
    assert "const payloadKind = wireRuntimePayloadKind(n);" in runtime_body
    assert "data-wire-runtime-payload-kind={payloadKind}" in runtime_body
    assert "NodeImagePreviewSurface nodeId={nodeId} rowId=\"wire-runtime-image\"" in runtime_body
    assert "rowId={payloadKind === 'geometry' ? 'wire-runtime-geometry-json' : 'wire-runtime-payload-json'}" in runtime_body
    assert "wireRuntimeGeometrySummary(n)" in runtime_body
    assert "data-node-structural-body=\"parameter\"" in parameter_body
    assert "structuralValueOf(n, 'owner')" in parameter_body
    assert "data-node-structural-body=\"boundary-anatomy\"" in boundary_body
    assert "['anatomy_boundary_role', 'boundary role']" in boundary_body
    assert "['source_boundary_port', 'source boundary port']" in boundary_body
    assert "['schema_ref', 'schema']" in boundary_body
    assert "['gate_policy', 'gate']" in boundary_body
    assert "['behavior', 'behavior']" in boundary_body
    assert "['presentation', 'presentation']" in boundary_body


def test_structural_anatomy_views_do_not_clone_canvas_surface_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const isStructuralAnatomyViewNode ="):
        jsx.index("const wireEndpointNodeId =", jsx.index("const isStructuralAnatomyViewNode ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    card_surfaces = jsx[
        jsx.index("const CanvasNodeCardHeaderSurface ="):
        jsx.index("const _NodeRenderer_inner =", jsx.index("const CanvasNodeCardHeaderSurface ="))
    ]
    renderer = jsx[
        jsx.index("const _NodeRenderer_inner ="):
        jsx.index("const NodeStateDot =", jsx.index("const _NodeRenderer_inner ="))
    ]
    socket = jsx[
        jsx.index("const CanvasSocketSurface = ({"):
        jsx.index("const Socket =", jsx.index("const CanvasSocketSurface = ({"))
    ]

    assert "if (!data.anatomy_view) return false;" in helper
    assert "if (data.anatomy_boundary_role) return true;" in helper
    assert "data.role === 'wire' || data.role === 'wire_layer' || data.role === 'wire_runtime' ||" in helper
    assert "data.role === 'parameter' || data.role === 'selected_wire_path_group' ||" in helper
    assert "data.role === 'selected_wire_path_wire'" in helper
    assert "data.param_family === 'port' && data.relation_wire_family === 'workflow_wire'" in helper
    assert "const persistentCanvasNodes = React.useMemo(" in node_canvas
    assert ".filter(n => !isStructuralAnatomyViewNode(n))" in node_canvas
    assert "syncGrandMapCanvasNodePositionState(positions, persistentCanvasNodes)" in node_canvas
    assert "syncGrandMapCanvasExpansionState(expanded, persistentCanvasNodes" in node_canvas
    assert "const surfaceEnabled = !isStructuralAnatomyViewNode(node);" in card_surfaces
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeCardHeaderNodes(node, cat) : null" in card_surfaces
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeCardBodyNodes(node) : null" in card_surfaces
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeCardNodes(node) : null" in card_surfaces
    assert "surfaceEnabled = true" in socket
    assert "surfaceEnabled ? ensureGrandMapCanvasNodeSocketNodes(nodeId, side, sockId, label, t) : null" in socket
    assert "const structuralAnatomyView = isStructuralAnatomyViewNode(n);" in renderer
    assert "surfaceEnabled={!structuralAnatomyView}" in renderer


def test_palette_spawn_materializes_params_as_parameter_nodes_at_birth():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const materializeWorkflowNodeParamNodes ="):
        jsx.index("const addNodeFromLibrary =", jsx.index("const materializeWorkflowNodeParamNodes ="))
    ]
    add_node = jsx[
        jsx.index("const addNodeFromLibrary ="):
        jsx.index("const removeUserNode =", jsx.index("const addNodeFromLibrary ="))
    ]

    assert "const materializeWorkflowNodeParamNodes = (node) =>" in helper
    assert "Array.isArray(node.params)" in helper
    assert "node.config && typeof node.config === 'object'" in helper
    assert "node.config_schema && typeof node.config_schema === 'object'" in helper
    assert "materializeGrandMapParamNode(node, key, value);" in helper
    assert "window.ahSetUiNodeParam(node.id, key, value);" not in helper
    assert "LM_GRAPH.nodes.push(node);\n      materializeWorkflowNodeParamNodes(node);" in add_node
    assert "LM_GRAPH.nodes.push(gnode);\n      materializeWorkflowNodeParamNodes(gnode);" in add_node
    assert "LM_GRAPH.nodes.push(newNode);\n    materializeWorkflowNodeParamNodes(newNode);" in add_node


def test_node_rail_param_items_unions_schema_fields_and_existing_params():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    param_items = jsx[
        jsx.index("const nodeRailParamItems ="):
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate =", jsx.index("const nodeRailParamItems ="))
    ]

    assert "const liveNode = node && node.id" in param_items
    assert "const params = ((liveNode && liveNode.params) || []).map(p => Object.assign({}, p));" in param_items
    assert "const seenParamKeys = new Set(items.map(p => p && p.k));" in param_items
    assert "params.forEach(p => { if (p && p.k != null && !seenParamKeys.has(p.k)) items.push(p); });" in param_items
    assert "const appendRuntimeItems = (items) => (items || []).concat(nodeRailWireRuntimeParamItems(liveNode));" in param_items
    assert "const dedupeNodeRailParamItems = (items) =>" in jsx
    assert "const finalizeItems = (items) => nodeRailRelationContractParamItems(" in param_items
    assert "return finalizeItems(items);" in param_items


def test_palette_wrappers_are_node_only_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    section = jsx[
        jsx.index("const PaletteSectionHeader ="):
        jsx.index("const PaletteMenuItem =", jsx.index("const PaletteSectionHeader ="))
    ]
    item = jsx[
        jsx.index("const NodeLibItem ="):
        jsx.index("const HomeShellSurface =", jsx.index("const NodeLibItem ="))
    ]

    assert "const graphNodes = ((window.__archhub_LM_GRAPH || {}).nodes || []);" not in section
    assert "const sectionSid = grandMapSafeId(id || title || 'section');" not in section
    assert "const ready = rootId && _uiFind(graphNodes, rootId)" not in section
    assert "_uiFind(graphNodes, 'slot:nodes-palette-section-title:' + sectionSid)" not in section
    assert "_uiFind(graphNodes, 'slot:nodes-palette-section-count:' + sectionSid)" not in section
    assert "if (ready) {" not in section
    assert "return rootId" in section
    assert "const graphNodes = ((window.__archhub_LM_GRAPH || {}).nodes || []);" not in item
    assert "const ready = rootId && _uiFind(graphNodes, rootId)" not in item
    assert "_uiFind(graphNodes, 'slot:nodes-palette-item-title:' + instanceId)" not in item
    assert "_uiFind(graphNodes, 'slot:nodes-palette-item-sub:' + instanceId)" not in item
    assert "if (ready) {" not in item
    assert "return rootId" in item


def test_workflow_payloads_filter_ui_surface_nodes_from_session_run_and_save():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    save_block = jsx[
        jsx.index("const _saveCurrentGraphSync ="):
        jsx.index("const saveCurrentGraph =", jsx.index("const _saveCurrentGraphSync ="))
    ]
    ws_header = jsx[
        jsx.index("const WsHeader ="):
        jsx.index("const smallBtn =", jsx.index("const WsHeader ="))
    ]
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo")
    ]

    assert "const workflowGraphSnapshot = (extraNodes) =>" in jsx
    assert "try { materializeWorkflowWireNodes(LM_GRAPH); } catch (_e) {}" in jsx
    assert "].filter(isWorkflowGraphNode)" in jsx
    assert "const merged = workflowGraphSnapshot(extra)" in save_block
    assert "JSON.stringify(merged)" in save_block
    assert "JSON.stringify({ nodes: LM_GRAPH.nodes || []" not in ws_header
    assert "JSON.stringify(workflowGraphSnapshot())" in ws_header
    assert "bridgeCall('run_workflow', currentSid(), workflowGraphJSON())" in node_canvas
    assert "JSON.stringify(LM_GRAPH));" not in node_canvas


def test_ui_projector_mounts_nested_surface_refs_through_relation_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    projector = jsx[
        jsx.index("function projectUiNode"):
        jsx.index("const UiNodeSurface =", jsx.index("function projectUiNode"))
    ]
    home_composer = jsx[
        jsx.index("const HomeComposerBodySurface ="):
        jsx.index("const Home =", jsx.index("const HomeComposerBodySurface ="))
    ]

    assert "const UiSurfaceRefNode = ({ surfaceRef, recording }) =>" in jsx
    assert "React.createElement(UiSurfaceRefNode" not in projector
    assert "d.surface_ref ? 'slot:surface-ref:' + d.surface_ref" in projector
    assert "uiRenderSlotMountAuthority(nodes, wires, id, declaredRenderSlot)" in projector
    assert "syncUiRenderSlotMountRelation(id, effectiveRenderSlot" in projector
    assert "'slot:surface-ref:home-composer-actions'" in home_composer
    assert '<UiSurfaceRefNode surfaceRef="home-composer-actions" recording={recording}/>' in home_composer
    assert 'renderSlots={renderSlots}' in home_composer
    assert "ensureGrandMapComposerActionsNodes({" not in projector
    assert "rootId: ensureGrandMap" not in projector


def test_first_screen_shells_keep_node_surface_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    home_rail = jsx[
        jsx.index("const HomeRailShellSurface ="):
        jsx.index("const SidebarShellSurface =")
    ]
    sidebar_shell = jsx[
        jsx.index("const SidebarShellSurface ="):
        jsx.index("const SidebarInner =")
    ]
    icon_rail = jsx[
        jsx.index("const IconRailInner ="):
        jsx.index("const IconRail = React.memo")
    ]
    chat_panel_shell = jsx[
        jsx.index("const ChatPanelShellSurface ="):
        jsx.index("const ChatsPanel =")
    ]

    assert "const rootId = ensureGrandMapHomeRailShellNodes()" not in home_rail
    assert "const rootId = ensureGrandMapSidebarShellNodes()" not in sidebar_shell
    assert "const railRootId = ensureGrandMapAppRailNodes({" not in icon_rail
    assert "const rootId = ensureGrandMapChatPanelShellNodes()" not in chat_panel_shell
    assert "() => ensureGrandMapHomeRailShellNodes()" in home_rail
    assert "() => ensureGrandMapSidebarShellNodes()" in sidebar_shell
    assert "() => ensureGrandMapAppRailNodes({ active: activeRail })" in icon_rail
    assert "() => ensureGrandMapChatPanelShellNodes()" in chat_panel_shell
    assert "<RailIcon" not in icon_rail
    assert "const RailIcon =" not in jsx
    assert "return null;" in icon_rail
    assert ".ah-rail-icon-node" in icon_rail
    assert "svgAttrs.has(k)" in jsx


def test_sidebar_panel_state_syncs_to_inline_application_shell_state_and_boundary_ports():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    sync = jsx[
        jsx.index("const syncGrandMapSidebarPanelState ="):
        jsx.index("const ensureGrandMapStatusStripNodes =", jsx.index("const syncGrandMapSidebarPanelState ="))
    ]
    studio = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SField = ({ label }) =>", jsx.index("const StudioLM ="))
    ]
    drawer = jsx[
        jsx.index("const RailDrawerHostInner ="):
        jsx.index("const RailDrawerHost = React.memo", jsx.index("const RailDrawerHostInner ="))
    ]

    assert "const syncGrandMapSidebarPanelState = ({ activePanel, drawerPanel } = {}) =>" in sync
    assert "active_sidebar_panel: active" in sync
    assert "rail_drawer_panel: drawer" in sync
    assert "sidebar_panel_state: drawer || active" in sync
    assert "sidebar_state_node: true" in sync
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(node, key, payload[key]));" in sync
    assert "window.ahSetUiNodeParam(nodeId, 'active_sidebar_panel', active);" not in sync
    assert "window.ahSetUiNodeParam(nodeId, 'rail_drawer_panel', drawer);" not in sync
    assert "window.ahSetUiNodeParam(nodeId, 'sidebar_panel_state', payload.sidebar_panel_state);" not in sync
    assert "syncNode(ARCHHUB_APPLICATION_SUPER_NODE_ID);" in sync
    assert "syncNode('ui:grandmap:sidebar-shell');" in sync
    assert "syncNode('ui:grandmap:app-rail');" in sync
    assert "syncApplicationBoundaryPortValue(g, 'active_sidebar_panel', active);" in sync
    assert "syncApplicationBoundaryPortValue(g, 'rail_drawer_panel', drawer);" in sync
    assert "applicationBoundaryStateNodeId('sidebar-state')" in sync
    assert "role: 'application_sidebar_state'" in sync
    assert "upsertApplicationBoundaryStateRelation(g, 'active_sidebar_panel', stateNode.id, 'exposes_active_sidebar_panel'" in sync
    assert "upsertApplicationBoundaryStateRelation(g, 'rail_drawer_panel', stateNode.id, 'exposes_rail_drawer_panel'" in sync
    assert "target_port: 'active_sidebar_panel'" in sync
    assert "target_port: 'rail_drawer_panel'" in sync
    assert "sidebar_state_node_id: stateNode.id" in sync
    assert "sidebar_state_wire_node_ids: stateWireNodeIds" in sync
    assert "syncGrandMapSidebarPanelState({ activePanel: panel });" in studio
    assert "syncGrandMapSidebarPanelState({ drawerPanel: panel });" in drawer


def test_application_modal_state_syncs_to_inline_overlay_state_and_boundary_ports():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    sync = jsx[
        jsx.index("const syncGrandMapApplicationModalState ="):
        jsx.index("const upsertGrandMapCommandPaletteNode =", jsx.index("const syncGrandMapApplicationModalState ="))
    ]
    studio = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SField = ({ label }) =>", jsx.index("const StudioLM ="))
    ]

    assert "const syncGrandMapApplicationModalState = (state = {}) =>" in sync
    assert "if (state.pickerOpen) active.push('model_picker');" in sync
    assert "if (state.settingsOpen) active.push('settings');" in sync
    assert "if (state.libraryOpen) active.push('node_library');" in sync
    assert "if (state.createNodeOpen) active.push('create_node');" in sync
    assert "if (state.aiNodeOpen) active.push('ai_node');" in sync
    assert "if (state.wirePromote) active.push('wire_promote');" in sync
    assert "active_app_modals: active" in sync
    assert "active_app_modal_primary: active[0] || 'none'" in sync
    assert "model_picker_open: !!state.pickerOpen" in sync
    assert "settings_open: !!state.settingsOpen" in sync
    assert "node_library_open: !!state.libraryOpen" in sync
    assert "wire_promote_source_node_id: wirePromote && wirePromote.from && wirePromote.from.nodeId || ''" in sync
    assert "app_modal_state_node: true" in sync
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(node, key, payload[key]));" in sync
    assert "window.ahSetUiNodeParam(nodeId, key, payload[key]);" not in sync
    assert "syncNode(ARCHHUB_APPLICATION_SUPER_NODE_ID);" in sync
    assert "syncNode('ui:grandmap:app-shell-overlays');" in sync
    assert "syncNode('ui:grandmap:app-shell');" in sync
    assert "syncApplicationBoundaryPortValue(g, 'active_app_modals', active);" in sync
    assert "syncApplicationBoundaryPortValue(g, 'active_app_modal_primary', payload.active_app_modal_primary);" in sync
    assert "syncApplicationBoundaryPortValue(g, 'settings_open', payload.settings_open);" in sync
    assert "applicationBoundaryStateNodeId('modal-state')" in sync
    assert "role: 'application_modal_state'" in sync
    assert "active_app_modals_json: JSON.stringify(active)" in sync
    assert "upsertApplicationBoundaryStateRelation(g, 'active_app_modals', stateNode.id, 'exposes_active_app_modals'" in sync
    assert "upsertApplicationBoundaryStateRelation(g, 'active_app_modal_primary', stateNode.id, 'exposes_active_app_modal_primary'" in sync
    assert "upsertApplicationBoundaryStateRelation(g, 'settings_open', stateNode.id, 'exposes_settings_open'" in sync
    assert "target_port: 'active_app_modals'" in sync
    assert "target_port: 'active_app_modal_primary'" in sync
    assert "target_port: 'settings_open'" in sync
    assert "modal_state_node_id: stateNode.id" in sync
    assert "modal_state_wire_node_ids: stateWireNodeIds" in sync
    assert "syncGrandMapApplicationModalState({" in studio
    assert "pickerOpen," in studio
    assert "settingsOpen," in studio
    assert "libraryOpen," in studio
    assert "createNodeOpen," in studio
    assert "aiNodeOpen," in studio
    assert "wirePromote," in studio


def test_settings_stub_fallback_is_node_surface_not_primary_inline_modal():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const ensureGrandMapSettingsStubNodes ="):
        jsx.index("const ensureGrandMapStatusStripNodes =", jsx.index("const ensureGrandMapSettingsStubNodes ="))
    ]
    settings = jsx[
        jsx.index("const Settings ="):
        jsx.index("const ModelPickerRow =", jsx.index("const Settings ="))
    ]

    assert "const ensureGrandMapSettingsStubNodes = () =>" in helper
    assert "const rootId = 'ui:grandmap:settings-stub';" in helper
    assert "type: 'ui.element'" in helper
    assert "surface: 'settings-stub'" in helper
    assert "test_id: 'settings-stub'" in helper
    assert "stop_click: true" in helper
    assert "role: 'dialog'" in helper
    assert "'aria-modal': 'true'" in helper
    assert "'aria-label': 'Settings'" in helper
    assert "action: 'settings.close'" in helper
    assert "args: { node_id: rootId }" in helper
    assert "'data-settings-close-action': 'settings.close'" in helper
    assert "args: { node_id: rootId + ':close', target_node_id: rootId }" in helper
    assert "hydrateUiNodeActionBehavior(rootId, 'settings-stub'" in helper
    assert "hydrateUiNodeActionBehavior(rootId + ':close', 'settings-stub-close'" in helper
    assert "auto_focus: true" in helper
    assert "behavior: 'render-settings-stub'" in helper
    assert "const rootId = useGrandMapSurfaceRoot(" in settings
    assert "() => ensureGrandMapSettingsStubNodes()" in settings
    assert "registerUiHostCapability('settings.close'" in settings
    assert "const fallback = (" in settings
    assert 'surface="settings-stub"' in settings
    assert "rootProps={{ onClick: onClose }}" not in settings
    assert "return rootId" in settings


def test_side_panel_rows_headers_and_shells_keep_node_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chat_row = jsx[
        jsx.index("const ChatSessionRow ="):
        jsx.index("const ChatPanelShellSurface =")
    ]
    chats_panel = jsx[
        jsx.index("const ChatsPanel ="):
        jsx.index("const ChatItemMenu =", jsx.index("const ChatsPanel ="))
    ]
    skills_row = jsx[
        jsx.index("const SkillsPanelRow ="):
        jsx.index("const SkillsPanelShellSurface =")
    ]
    skills_shell = jsx[
        jsx.index("const SkillsPanelShellSurface ="):
        jsx.index("const SkillsPanel =")
    ]
    skills_panel = jsx[
        jsx.index("const SkillsPanel ="):
        jsx.index("const SearchPanelShellSurface =")
    ]
    search_shell = jsx[
        jsx.index("const SearchPanelShellSurface ="):
        jsx.index("const SearchPanel =", jsx.index("const SearchPanelShellSurface ="))
    ]

    assert "const rootId = ensureGrandMapChatSessionRowNodes(" not in chat_row
    assert "const chatPanelHeaderRoot = ensureGrandMapChatPanelHeaderNodes(" not in chats_panel
    assert "const chatPanelSearchRoot = ensureGrandMapChatPanelSearchNodes(" not in chats_panel
    assert "const rootId = ensureGrandMapChatPanelListNodes()" not in chats_panel
    assert "const rootId = ensureGrandMapChatPanelMessageNodes(" not in chats_panel
    assert "const rootId = ensureGrandMapSkillsPanelRowNodes(" not in skills_row
    assert "if (!rootId)" not in skills_row
    assert '<div draggable="true"' not in skills_row
    assert "const rootId = ensureGrandMapSkillsPanelShellNodes()" not in skills_shell
    assert "const skillsPanelHeaderRoot = ensureGrandMapSkillsPanelHeaderNodes(" not in skills_panel
    assert "const skillsPanelSearchRoot = ensureGrandMapSkillsPanelSearchNodes(" not in skills_panel
    assert "const rootId = ensureGrandMapSkillsPanelListNodes()" not in skills_panel
    assert "const rootId = ensureGrandMapSkillsPanelMessageNodes(" not in skills_panel
    assert "const rootId = ensureGrandMapSearchPanelShellNodes()" not in search_shell
    assert "const rootId = ensureGrandMapSearchPanelScopesListNodes()" not in search_shell
    assert "const rootId = ensureGrandMapSearchPanelResultsListNodes()" not in search_shell
    assert "<span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, letterSpacing:'-0.005em', color:LM.ink }}>Chats</span>" not in chats_panel
    assert "<input value={q} onChange={e => setQ(e.target.value)} placeholder=\"Search chats...\"" not in chats_panel
    assert "<span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Skills</span>" not in skills_panel
    assert "<input value={q} onChange={e => setQ(e.target.value)} placeholder=\"Search saved skills...\"" not in skills_panel
    assert "if (!rootId)" not in chat_row
    assert "useGrandMapSurfaceRoot(" in chat_row
    assert "() => ensureGrandMapChatPanelHeaderNodes({" in chats_panel
    assert "() => ensureGrandMapChatPanelSearchNodes({ query: q })" in chats_panel
    assert "() => ensureGrandMapChatPanelListNodes()" in jsx
    assert "() => ensureGrandMapChatPanelMessageNodes({ message })" in jsx
    assert "useGrandMapSurfaceRoot(" in skills_row
    assert "() => ensureGrandMapSkillsPanelShellNodes()" in skills_shell
    assert "() => ensureGrandMapSkillsPanelHeaderNodes({" in skills_panel
    assert "() => ensureGrandMapSkillsPanelSearchNodes({ query: q })" in skills_panel
    assert "() => ensureGrandMapSkillsPanelListNodes()" in jsx
    assert "() => ensureGrandMapSkillsPanelMessageNodes({ message })" in jsx
    assert "() => ensureGrandMapSearchPanelShellNodes()" in search_shell
    assert "() => ensureGrandMapSearchPanelScopesListNodes()" in jsx
    assert "() => ensureGrandMapSearchPanelResultsListNodes()" in jsx


def test_node_palette_shell_hydrates_nodes_panel_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    nodes_panel = jsx[
        jsx.index("const NodesPanel ="):
        jsx.index("const NodesPanelMemo =", jsx.index("const NodesPanel ="))
    ]

    assert (
        "const NodePaletteShellSurface = ({ styles, header, menu, search, list, footer, rootProps }) =>"
        in jsx
    )
    assert "const ensureGrandMapNodePaletteShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-shell'" in jsx
    assert "<NodePaletteShellSurface" in nodes_panel
    assert "rootProps={{ onContextMenu: onPanelContextMenu }}" in nodes_panel
    assert "const NodePaletteListSurface = ({ children }) =>" in jsx
    assert "<NodePaletteListSurface>" in nodes_panel
    assert "const NodePaletteGroupSurface = ({ id, title, count, kind = 'group', open = true, header, children }) =>" in jsx
    assert "<NodePaletteGroupSurface" in nodes_panel
    assert "surface=\"node-palette-group\"" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-group'" in jsx
    assert '<div className="ah-scroll" style={{ flex:1, overflow:\'auto\', padding:\'0 6px 8px\'' not in nodes_panel
    assert "const NodePaletteContextMenuSurface = ({ children, x, y }) =>" in jsx
    assert "<NodePaletteContextMenuSurface x={ctxMenu.x} y={ctxMenu.y}>" in nodes_panel
    assert "<div data-no-pan onClick={e => e.stopPropagation()} style={{" not in nodes_panel
    assert "slot:node-palette-shell-styles" in jsx
    assert "slot:node-palette-shell-header" in jsx
    assert "slot:node-palette-shell-menu" in jsx
    assert "slot:node-palette-shell-search" in jsx
    assert "slot:node-palette-shell-list" in jsx
    assert "slot:node-palette-shell-footer" in jsx
    assert "<div onContextMenu={onPanelContextMenu}" not in nodes_panel
    assert "<div style={{ marginBottom:4 }}>" not in nodes_panel
    assert "<div style={{ marginBottom:6 }}>" not in nodes_panel


def test_node_palette_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    search = jsx[
        jsx.index("const ensureGrandMapNodePaletteSearchNodes ="):
        jsx.index(
            "const ensureGrandMapNodePaletteListNodes =",
            jsx.index("const ensureGrandMapNodePaletteSearchNodes ="),
        )
    ]
    list_nodes = jsx[
        jsx.index("const ensureGrandMapNodePaletteListNodes ="):
        jsx.index(
            "const nodePaletteGroupInstanceId =",
            jsx.index("const ensureGrandMapNodePaletteListNodes ="),
        )
    ]
    group_clone = jsx[
        jsx.index("const cloneGrandMapNodePaletteGroupTemplate ="):
        jsx.index(
            "const ensureGrandMapNodePaletteGroupNodes =",
            jsx.index("const cloneGrandMapNodePaletteGroupTemplate ="),
        )
    ]
    context_menu = jsx[
        jsx.index("const ensureGrandMapNodePaletteContextMenuNodes ="):
        jsx.index(
            "const nodePaletteEffectKey =",
            jsx.index("const ensureGrandMapNodePaletteContextMenuNodes ="),
        )
    ]
    item_clone = jsx[
        jsx.index("const cloneGrandMapNodePaletteItemTemplate ="):
        jsx.index(
            "const ensureGrandMapNodePaletteItemNodes =",
            jsx.index("const cloneGrandMapNodePaletteItemTemplate ="),
        )
    ]
    section_clone = jsx[
        jsx.index("const cloneGrandMapNodePaletteSectionHeaderTemplate ="):
        jsx.index(
            "const ensureGrandMapNodePaletteSectionHeaderNodes =",
            jsx.index("const cloneGrandMapNodePaletteSectionHeaderTemplate ="),
        )
    ]
    menu_clone = jsx[
        jsx.index("const cloneGrandMapNodePaletteMenuItemTemplate ="):
        jsx.index(
            "const ensureGrandMapNodePaletteMenuItemNodes =",
            jsx.index("const cloneGrandMapNodePaletteMenuItemTemplate ="),
        )
    ]
    sidecar_clone = jsx[
        jsx.index("const cloneGrandMapNodePaletteSkillSidecarTemplate ="):
        jsx.index(
            "const ensureGrandMapNodePaletteSkillSidecarNodes =",
            jsx.index("const cloneGrandMapNodePaletteSkillSidecarTemplate ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('node-palette-search', rootId, slotMap" in search
    assert "state_key: 'node_palette_search_state_node_id'" in search
    assert "materialize_param_nodes: true" in search
    assert "materialize_wire_anatomy: true" in search
    assert "wire_family: 'surface_state_field'" in search
    assert "'slot:nodes-palette-search': (slots && slots.query) || ''" in search
    assert "'slot:nodes-palette-sort': (slots && slots.sortMode) || 'default'" in search
    assert "syncGrandMapSurfaceStateSlots('node-palette-list', rootId, slotMap" in list_nodes
    assert "state_key: 'node_palette_list_state_node_id'" in list_nodes
    assert "'slot:node-palette-list-content': ''" in list_nodes
    assert "syncGrandMapSurfaceStateSlots('node-palette-group-' + sid, rootId, clonedSlotMap" in group_clone
    assert "state_key: 'node_palette_group_state_node_id'" in group_clone
    assert "'slot:nodes-palette-group-title': slots && slots.title ? slots.title : 'GROUP'" in group_clone
    assert "'slot:nodes-palette-group-open': slots && slots.open === false ? 'false' : 'true'" in group_clone
    assert "'slot:nodes-palette-group-header': ''" in group_clone
    assert "'slot:nodes-palette-group-content': ''" in group_clone
    assert "syncGrandMapSurfaceStateSlots('node-palette-context-menu', rootId, slotMap" in context_menu
    assert "state_key: 'node_palette_context_menu_state_node_id'" in context_menu
    assert "'slot:node-palette-context-menu-content': ''" in context_menu
    assert "syncGrandMapSurfaceStateSlots('node-palette-item-' + instanceId, rootId, clonedSlotMap" in item_clone
    assert "state_key: 'node_palette_item_state_node_id'" in item_clone
    assert "syncGrandMapSurfaceStateSlots('node-palette-section-header-' + sid, rootId, clonedSlotMap" in section_clone
    assert "state_key: 'node_palette_section_state_node_id'" in section_clone
    assert "syncGrandMapSurfaceStateSlots('node-palette-menu-item-' + sid, rootId, clonedSlotMap" in menu_clone
    assert "state_key: 'node_palette_menu_item_state_node_id'" in menu_clone
    assert "syncGrandMapSurfaceStateSlots('node-palette-skill-sidecar-' + sid, rootId, clonedSlotMap" in sidecar_clone
    assert "state_key: 'node_palette_skill_sidecar_state_node_id'" in sidecar_clone


def test_node_palette_runtime_state_is_application_boundary_node_and_wire():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const ensureNodePaletteApplicationBoundaryPort ="):
        jsx.index(
            "const ensureGrandMapApplicationSuperNode =",
            jsx.index("const ensureNodePaletteApplicationBoundaryPort ="),
        )
    ]
    nodes_panel = jsx[
        jsx.index("const NodesPanel = ({ addNodeFromLibrary }) =>"):
        jsx.index("const NodesPanelMemo = React.memo(NodesPanel);")
    ]

    assert "id: 'node_palette_state'" in jsx
    assert "schema_ref: 'archhub.ui.node_palette.state'" in jsx
    assert "endpoint_kind: 'ui-control'" in jsx
    assert "ensureUiNodePortParamNode(g, ARCHHUB_APPLICATION_SUPER_NODE_ID" in helper
    assert "relation_wire_family: 'application_boundary'" in helper
    assert "applicationBoundaryStateNodeId('node-palette-state')" in helper
    assert "upsertApplicationBoundaryStateNode(" in helper
    assert (
        "upsertApplicationBoundaryStateRelation(g, 'node_palette_state', "
        "stateNodeId, 'exposes_node_palette_state'"
    ) in helper
    assert "syncApplicationBoundaryPortValue(g, 'node_palette_state', payload.node_palette_state)" in helper
    assert "const readGrandMapNodePaletteStateSnapshot = () =>" in helper
    assert "node_palette_open_categories_json" in helper
    assert "node_palette_hidden_categories_json" in helper
    assert "node_palette_pins_json" in helper
    assert "node_palette_usage_json" in helper
    assert "node_palette_state_node_id" in helper
    assert "node_palette_state_wire_node_id" in helper
    assert "syncGrandMapNodePaletteState({" in nodes_panel
    assert "const paletteGraphStateSnapshot = readGrandMapNodePaletteStateSnapshot();" in nodes_panel
    assert "const paletteCategoryIsHidden = (cat) => paletteHiddenCategorySet.has(String(cat));" in nodes_panel
    assert "const paletteRenderOpenCategories = Array.isArray(paletteGraphStateSnapshot.open_categories)" in nodes_panel
    assert "const paletteCategoryIsOpen = (cat) => (" in nodes_panel
    assert "paletteOpenCategorySet ? paletteOpenCategorySet.has(String(cat)) : !!openCats[cat]" in nodes_panel
    assert ".filter(c => grouped.has(c) && !paletteCategoryIsHidden(c))" in nodes_panel
    assert ".concat([...grouped.keys()].filter(c => !order.includes(c) && !paletteCategoryIsHidden(c)))" in nodes_panel
    assert "const visibleEntryCount = sections.reduce((total, c) => total + ((grouped.get(c) || []).length), 0);" in nodes_panel
    assert "count={visibleEntryCount}" in nodes_panel
    assert "open_categories: openCats" in nodes_panel
    assert "const open = paletteCategoryIsOpen(c);" in nodes_panel
    assert "...prev, [c]: !open" in nodes_panel
    assert "hidden_categories: paletteHiddenCategories" in nodes_panel
    assert "pins: palettePinnedIds" in nodes_panel
    assert "usage: paletteUsageSnapshot" in nodes_panel
    assert "const palettePinnedLocalLookup = new Map();" in nodes_panel
    assert "const paletteVisiblePins = paletteRenderPinnedIds" in nodes_panel
    assert "const catalogEntry = paletteQuickCatalog.get(String(id));" in nodes_panel
    assert 'id="pinned"' in nodes_panel
    assert 'title="PINNED"' in nodes_panel
    assert "count={paletteVisiblePins.length}" in nodes_panel
    assert 'kind="pinned"' in nodes_panel
    assert "const paletteMostUsedEntries = Object.keys(paletteRenderUsage || {})" in nodes_panel
    assert 'id="most-used"' in nodes_panel
    assert 'title="MOST USED"' in nodes_panel
    assert "count={paletteMostUsedEntries.length}" in nodes_panel
    assert 'kind="usage"' in nodes_panel
    assert "paletteRecordItemUsage(it);" in nodes_panel
    assert "pinned={paletteItemIsPinned(it.id)}" in nodes_panel
    assert "onPin={() => togglePin(it, cat, cat && cat.label || 'node')}" in nodes_panel
    assert "entry.spawnCat || (entry.cat && entry.cat.label)" in nodes_panel
    assert "onContextMenu={(e) => {" in nodes_panel
    assert "e.preventDefault(); e.stopPropagation(); toggleHidden(c);" in nodes_panel


def test_wire_related_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    wire_menu = jsx[
        jsx.index("const ensureGrandMapWireContextMenuNodes ="):
        jsx.index(
            "const ensureGrandMapNodeContextMenuNodes =",
            jsx.index("const ensureGrandMapWireContextMenuNodes ="),
        )
    ]
    promote = jsx[
        jsx.index("const updateGrandMapWirePromotePaletteSlots ="):
        jsx.index(
            "const ensureGrandMapWirePromotePaletteNodes =",
            jsx.index("const updateGrandMapWirePromotePaletteSlots ="),
        )
    ]
    result_row = jsx[
        jsx.index("const cloneGrandMapWirePromoteResultRowTemplate ="):
        jsx.index(
            "const ensureGrandMapWirePromoteResultRowNodes =",
            jsx.index("const cloneGrandMapWirePromoteResultRowTemplate ="),
        )
    ]
    broken_dialog = jsx[
        jsx.index("const updateGrandMapBrokenWireDialogSlots ="):
        jsx.index(
            "const ensureGrandMapBrokenWireDialogNodes =",
            jsx.index("const updateGrandMapBrokenWireDialogSlots ="),
        )
    ]
    broken_row = jsx[
        jsx.index("const cloneGrandMapBrokenWireRowTemplate ="):
        jsx.index(
            "const ensureGrandMapBrokenWireRowNodes =",
            jsx.index("const cloneGrandMapBrokenWireRowTemplate ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('wire-context-menu', rootId, slotMap" in wire_menu
    assert "state_key: 'wire_context_menu_state_node_id'" in wire_menu
    assert "materialize_param_nodes: true" in wire_menu
    assert "materialize_wire_anatomy: true" in wire_menu
    assert "wire_family: 'surface_state_field'" in wire_menu
    assert "'slot:wire-gate-blocked': slots && slots.gateBlocked ? 'true' : 'false'" in wire_menu
    assert "'slot:wire-codec-base64': slots && slots.codecBase64 ? 'true' : 'false'" in wire_menu
    assert "'slot:wire-presentation-hidden': slots && slots.presentationHidden ? 'true' : 'false'" in wire_menu
    assert "syncGrandMapSurfaceStateSlots('wire-promote-palette', rootId, slotMap" in promote
    assert "state_key: 'wire_promote_palette_state_node_id'" in promote
    assert "materialize_param_nodes: true" in promote
    assert "materialize_wire_anatomy: true" in promote
    assert "wire_family: 'surface_state_field'" in promote
    assert "'slot:wire-promote-query': (slots && slots.query) || ''" in promote
    assert "'slot:wire-promote-has-results': hasResults ? 'true' : 'false'" in promote
    assert "syncGrandMapSurfaceStateSlots('wire-promote-result-row-' + instanceId, rootId, clonedSlotMap" in result_row
    assert "state_key: 'wire_promote_result_state_node_id'" in result_row
    assert "syncGrandMapSurfaceStateSlots('broken-wire-dialog', rootId, slotMap" in broken_dialog
    assert "state_key: 'broken_wire_dialog_state_node_id'" in broken_dialog
    assert "materialize_param_nodes: true" in broken_dialog
    assert "materialize_wire_anatomy: true" in broken_dialog
    assert "wire_family: 'surface_state_field'" in broken_dialog
    assert "'slot:broken-wire-node-title': (info && info.nodeTitle) || ''" in broken_dialog
    assert "syncGrandMapSurfaceStateSlots('broken-wire-row-' + instanceId, rootId, clonedSlotMap" in broken_row
    assert "state_key: 'broken_wire_row_state_node_id'" in broken_row


def test_canvas_and_node_context_menus_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    canvas_menu = jsx[
        jsx.index("const ensureGrandMapCanvasContextMenuNodes ="):
        jsx.index(
            "const seedGrandMapWireRuntimeMenuFallbackNodes =",
            jsx.index("const ensureGrandMapCanvasContextMenuNodes ="),
        )
    ]
    node_menu = jsx[
        jsx.index("const ensureGrandMapNodeContextMenuNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasGestureHintNodes =",
            jsx.index("const ensureGrandMapNodeContextMenuNodes ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('canvas-context-menu', rootId, slotMap" in canvas_menu
    assert "state_key: 'canvas_context_menu_state_node_id'" in canvas_menu
    assert "materialize_param_nodes: true" in canvas_menu
    assert "materialize_wire_anatomy: true" in canvas_menu
    assert "wire_family: 'surface_state_field'" in canvas_menu
    assert "'slot:canvas-snap-to-grid': slots && slots.snapToGrid ? 'true' : 'false'" in canvas_menu
    assert "syncGrandMapSurfaceStateSlots('node-context-menu', rootId, slotMap" in node_menu
    assert "state_key: 'node_context_menu_state_node_id'" in node_menu
    assert "materialize_param_nodes: true" in node_menu
    assert "materialize_wire_anatomy: true" in node_menu
    assert "wire_family: 'surface_state_field'" in node_menu
    assert "'slot:node-menu-is-subgraph': slots && slots.isSubgraph ? 'true' : 'false'" in node_menu
    assert "'slot:node-menu-shared-skill': slots && slots.isSharedSkill ? 'true' : 'false'" in node_menu
    assert "'slot:node-menu-flattenable': slots && slots.flattenable ? 'true' : 'false'" in node_menu


def test_wire_promote_palette_hydrates_add_node_overlay_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    wire_promote = jsx[
        jsx.index("const WirePromoteResultRow ="):
        jsx.index("const LM_NODE_TEMPLATES =", jsx.index("const WirePromoteResultRow ="))
    ]

    assert "const ensureGrandMapWirePromotePaletteNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'wire-promote-palette'" in jsx
    assert "const ensureGrandMapWirePromoteResultRowNodes = (result, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'wire-promote-result-row'" in jsx
    assert "const WirePromoteResultRow = ({ result, index, active, onHover }) =>" in jsx
    assert "ensureGrandMapWirePromoteResultRowNodes(result, { index, active })" in wire_promote
    assert "ensureGrandMapWirePromotePaletteNodes({" in wire_promote
    assert 'surface="wire-promote-palette"' in wire_promote
    assert 'surface="wire-promote-result-row"' in wire_promote
    assert "slot:wire-promote-results" in wire_promote
    assert "wire-promote.query.update" in wire_promote
    assert "wire-promote.result.pick" in wire_promote
    assert "wire-promote.submit" in wire_promote
    assert "wire-promote.close" in wire_promote
    assert "<input autoFocus value={q}" not in wire_promote
    assert "<button key={r.id} onClick={() => { _bumpRecent(r.id); onPick(r); }}" not in wire_promote
    assert 'className="ah-scroll"' not in wire_promote


def test_broken_wire_dialog_hydrates_recovery_modal_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    broken_dialog = jsx[
        jsx.index("const BrokenWireRow ="):
        jsx.index("//", jsx.index("const BrokenWireDialog =") + 1)
    ]

    assert "const ensureGrandMapBrokenWireDialogNodes = (info) =>" in jsx
    assert "get_grand_map_ui_surface', 'broken-wire-dialog'" in jsx
    assert "const ensureGrandMapBrokenWireRowNodes = (row, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'broken-wire-row'" in jsx
    assert "syncGrandMapSurfaceStateSlots('broken-wire-dialog', rootId, slotMap" in jsx
    assert "'slot:broken-wire-node-title': (info && info.nodeTitle) || ''" in jsx
    assert "'slot:broken-wire-count-label': broken.length === 1" in jsx
    assert "'slot:broken-wire-adapter-label': srcType && dstType" in jsx
    assert "const BrokenWireRow = ({ row, index }) =>" in broken_dialog
    assert "ensureGrandMapBrokenWireDialogNodes(info)" in broken_dialog
    assert "ensureGrandMapBrokenWireRowNodes(row, index)" in broken_dialog
    assert 'surface="broken-wire-dialog"' in broken_dialog
    assert 'surface="broken-wire-row"' in broken_dialog
    assert "slot:broken-wire-rows" in broken_dialog
    assert "broken-wire.insert-adapter" in broken_dialog
    assert "broken-wire.delete-anyway" in broken_dialog
    assert 'data-testid="broken-wire-dialog-backdrop"' not in broken_dialog
    assert '<div data-testid="broken-wire-dialog"' not in broken_dialog
    assert '<button aria-label="Insert adapter' not in broken_dialog
    assert "style={{" not in broken_dialog


def test_graph_health_badge_hydrates_validator_panel_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    graph_health = jsx[
        jsx.index("const GraphHealthIssueRow ="):
        jsx.index("const NodeContextMenuSurface =", jsx.index("const GraphHealthBadge ="))
    ]

    assert "const ensureGrandMapGraphHealthBadgeNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'graph-health-badge'" in jsx
    assert "const ensureGrandMapGraphHealthIssueRowNodes = (issue, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'graph-health-issue-row'" in jsx
    assert "syncGrandMapSurfaceStateSlots('graph-health-badge', rootId, slotMap" in jsx
    assert "'slot:graph-health-open': open ? 'true' : 'false'" in jsx
    assert "'slot:graph-health-state': state" in jsx
    assert "'slot:graph-health-summary': summary" in jsx
    assert "const GraphHealthIssueRow = ({ issue, index }) =>" in graph_health
    assert "ensureGrandMapGraphHealthBadgeNodes({" in graph_health
    assert "ensureGrandMapGraphHealthIssueRowNodes(issue, index)" in graph_health
    assert 'surface="graph-health-badge"' in graph_health
    assert 'surface="graph-health-issue-row"' in graph_health
    assert "slot:graph-health-issues" in graph_health
    assert "graph-health.open" in graph_health
    assert "graph-health.close" in graph_health
    assert "graph-health.self-heal" in graph_health
    assert "registerUiHostCapability('graph-health.open'" in graph_health
    assert "registerUiHostCapability('graph-health.close'" in graph_health
    assert "registerUiHostCapability('graph-health.self-heal'" in graph_health
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in graph_health
    assert 'data-testid="graph-health-badge"' not in graph_health
    assert 'data-testid="graph-health-panel"' not in graph_health
    assert "issues.map((iss, i) =>" not in graph_health


def test_health_strip_item_hydrates_footer_popover_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    health_strip = jsx[
        jsx.index("const HealthStripItem ="):
        jsx.index("window.StudioLM = StudioLM;", jsx.index("const HealthStripItem ="))
    ]

    assert "const ensureGrandMapHealthStripItemNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'health-strip-item'" in jsx
    assert "syncGrandMapSurfaceStateSlots('health-strip-item', rootId, slotMap" in jsx
    assert "'slot:health-strip-open': slots && slots.open ? 'true' : 'false'" in jsx
    assert "'slot:health-strip-hidden': slots && slots.hidden ? 'true' : 'false'" in jsx
    assert "'slot:health-strip-label': label" in jsx
    assert "ensureGrandMapHealthStripItemNodes({" in health_strip
    assert 'surface="health-strip-item"' in health_strip
    assert "slot:health-strip-issues" in health_strip
    assert "<GraphHealthIssueRow key={index} issue={issue} index={index}/>" in health_strip
    assert "health-strip.toggle" in health_strip
    assert "health-strip.close" in health_strip
    assert "health-strip.self-heal" in health_strip
    assert "graph-health.issue.focus" in health_strip
    assert "window.addEventListener('lm-graph-health-open'" in health_strip
    assert "bridgeAsync('graph_validate'" in health_strip
    assert 'data-testid="health-strip-item"' not in health_strip
    assert 'data-testid="health-strip-self-heal"' not in health_strip
    assert "<button onClick={() => setOpen(o => !o)}" not in health_strip
    assert "issues.map((iss, i) =>" not in health_strip
    assert "style={{" not in health_strip


def test_graph_health_state_syncs_to_inline_application_badge_footer_and_boundary_port():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const syncGrandMapGraphHealthState ="):
        jsx.index("const ensureGrandMapGraphHealthBadgeNodes =", jsx.index("const syncGrandMapGraphHealthState ="))
    ]

    assert "const syncGrandMapGraphHealthState = (slots) =>" in helper
    assert "graph_health_state_node: true" in helper
    assert "graph_health_open: open" in helper
    assert "graph_health_hidden: hidden" in helper
    assert "graph_health_state: state" in helper
    assert "graph_health_summary: summary" in helper
    assert "graph_health_error_count: err" in helper
    assert "graph_health_warning_count: warn" in helper
    assert "graph_health_issue_count: total" in helper
    assert "graph_health_has_issues: hasIssues" in helper
    assert "syncNode(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'graph_health_state');" in helper
    assert "syncNode('ui:grandmap:graph-health-badge', 'graph_health_state');" in helper
    assert "syncNode('ui:grandmap:health-strip-item', 'graph_health_state');" in helper
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(node, key, payload[key]));" in helper
    assert "syncApplicationBoundaryPortValue(g, 'graph_health', state);" in helper
    assert "window.ahSetUiNodeParam(nodeId, key, payload[key]);" not in helper
    assert "syncGrandMapGraphHealthState(slots || {});" in helper


def test_graph_health_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    badge = jsx[
        jsx.index("const updateGrandMapGraphHealthSlots ="):
        jsx.index(
            "const ensureGrandMapGraphHealthBadgeNodes =",
            jsx.index("const updateGrandMapGraphHealthSlots ="),
        )
    ]
    issue_row = jsx[
        jsx.index("const cloneGrandMapGraphHealthIssueRowTemplate ="):
        jsx.index(
            "const ensureGrandMapGraphHealthIssueRowNodes =",
            jsx.index("const cloneGrandMapGraphHealthIssueRowTemplate ="),
        )
    ]
    strip = jsx[
        jsx.index("const updateGrandMapHealthStripSlots ="):
        jsx.index(
            "const ensureGrandMapHealthStripItemNodes =",
            jsx.index("const updateGrandMapHealthStripSlots ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('graph-health-badge', rootId, slotMap" in badge
    assert "state_key: 'graph_health_badge_state_node_id'" in badge
    assert "'slot:graph-health-has-issues': hasIssues ? 'true' : 'false'" in badge
    assert "syncGrandMapSurfaceStateSlots('graph-health-issue-row-' + instanceId, rootId, clonedSlotMap" in issue_row
    assert "state_key: 'graph_health_issue_state_node_id'" in issue_row
    assert "'slot:graph-health-issue-message': safeIssue.msg ? String(safeIssue.msg) : ''" in issue_row
    assert "syncGrandMapSurfaceStateSlots('health-strip-item', rootId, slotMap" in strip
    assert "state_key: 'health_strip_item_state_node_id'" in strip
    assert "'slot:health-strip-empty': 'graph valid - ' + String(total) + ' issues'" in strip


def test_model_picker_hydrates_modal_groups_and_rows_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    model_picker = jsx[
        jsx.index("const ModelPickerRow ="):
        jsx.index("// Hat 3 audit", jsx.index("const ModelPicker ="))
    ]

    assert "const ensureGrandMapModelPickerModalNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'model-picker-modal'" in jsx
    assert "const ensureGrandMapModelPickerGroupNodes = (group, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'model-picker-group'" in jsx
    assert "const ensureGrandMapModelPickerRowNodes = (modelItem, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'model-picker-row'" in jsx
    assert "syncGrandMapSurfaceStateSlots('model-picker-modal', rootId, slotMap" in jsx
    assert "'slot:model-picker-query': query" in jsx
    assert "'slot:model-picker-has-results': hasResults ? 'true' : 'false'" in jsx
    assert "const ModelPickerRow = ({ item, index, selected }) =>" in model_picker
    assert "const ModelPickerGroup = ({ group, index, model }) =>" in model_picker
    assert "ensureGrandMapModelPickerModalNodes({" in model_picker
    assert "ensureGrandMapModelPickerGroupNodes(group, index)" in model_picker
    assert "ensureGrandMapModelPickerRowNodes(item, { index, selected })" in model_picker
    assert 'surface="model-picker-modal"' in model_picker
    assert 'surface="model-picker-group"' in model_picker
    assert 'surface="model-picker-row"' in model_picker
    assert "slot:model-picker-groups" in model_picker
    assert "model-picker.query.update" in model_picker
    assert "model-picker.pick" in model_picker
    assert "registerUiHostCapability('model-picker.close'" in model_picker
    assert "registerUiHostCapability('model-picker.query.update'" in model_picker
    assert "registerUiHostCapability('model-picker.pick'" in model_picker
    assert "window.addEventListener('lm-ui-node-action', onUiNodeAction)" not in model_picker
    assert "window.addEventListener('keydown', onKey)" not in model_picker
    assert "<input autoFocus value={q}" not in model_picker
    assert "filteredGroups.map(g =>" not in model_picker
    assert "g.items.map(m =>" not in model_picker
    assert 'className="ah-scroll"' not in model_picker


def test_model_picker_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chip = jsx[
        jsx.index("const ensureGrandMapCanvasModelPickerNodes ="):
        jsx.index(
            "const updateGrandMapModelPickerModalSlots =",
            jsx.index("const ensureGrandMapCanvasModelPickerNodes ="),
        )
    ]
    modal = jsx[
        jsx.index("const updateGrandMapModelPickerModalSlots ="):
        jsx.index(
            "const ensureGrandMapModelPickerModalNodes =",
            jsx.index("const updateGrandMapModelPickerModalSlots ="),
        )
    ]
    group = jsx[
        jsx.index("const cloneGrandMapModelPickerGroupTemplate ="):
        jsx.index(
            "const ensureGrandMapModelPickerGroupNodes =",
            jsx.index("const cloneGrandMapModelPickerGroupTemplate ="),
        )
    ]
    row = jsx[
        jsx.index("const cloneGrandMapModelPickerRowTemplate ="):
        jsx.index(
            "const ensureGrandMapModelPickerRowNodes =",
            jsx.index("const cloneGrandMapModelPickerRowTemplate ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('canvas-model-picker', rootId, slotMap" in chip
    assert "state_key: 'canvas_model_picker_state_node_id'" in chip
    assert "materialize_param_nodes: true" in chip
    assert "materialize_wire_anatomy: true" in chip
    assert "wire_family: 'surface_state_field'" in chip
    assert "'slot:canvas-model-label': slots && slots.modelLabel ? slots.modelLabel : 'Auto (router picks)'" in chip
    assert "syncGrandMapSurfaceStateSlots('model-picker-modal', rootId, slotMap" in modal
    assert "state_key: 'model_picker_modal_state_node_id'" in modal
    assert "materialize_param_nodes: true" in modal
    assert "materialize_wire_anatomy: true" in modal
    assert "wire_family: 'surface_state_field'" in modal
    assert "'slot:model-picker-query': query" in modal
    assert "'slot:model-picker-empty-message': hasResults ? ''" in modal
    assert "syncGrandMapSurfaceStateSlots('model-picker-group-' + instanceId, rootId, clonedSlotMap" in group
    assert "state_key: 'model_picker_group_state_node_id'" in group
    assert "'slot:model-picker-group-name': (group && group.name) || 'MODELS'" in group
    assert "syncGrandMapSurfaceStateSlots('model-picker-row-' + instanceId, rootId, clonedSlotMap" in row
    assert "state_key: 'model_picker_row_state_node_id'" in row
    assert "'slot:model-picker-row-selected': slots && slots.selected ? 'true' : 'false'" in row
    assert "const actionNodeIds = [];" in row
    assert "if (copy.data && copy.data.action) actionNodeIds.push(copy.id);" in row
    assert "hydrateUiNodeActionBehavior(actionNodeId, 'model-picker-row'" in row


def test_node_palette_components_keep_node_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    shell = jsx[
        jsx.index("const NodePaletteShellSurface ="):
        jsx.index("const NodesPanel =")
    ]
    nodes_panel = jsx[
        jsx.index("const NodesPanel ="):
        jsx.index("const NodesPanelMemo =", jsx.index("const NodesPanel ="))
    ]
    section_header = jsx[
        jsx.index("const PaletteSectionHeader ="):
        jsx.index("const PaletteMenuItem =")
    ]
    menu_item = jsx[
        jsx.index("const PaletteMenuItem ="):
        jsx.index("const PaletteSkillSidecar =")
    ]
    skill_sidecar = jsx[
        jsx.index("const PaletteSkillSidecar ="):
        jsx.index("const NodeLibItem =")
    ]
    node_lib_item = jsx[
        jsx.index("const NodeLibItem ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const NodeLibItem ="))
    ]

    assert "const rootId = ensureGrandMapNodePaletteShellNodes()" not in shell
    assert "const rootId = ensureGrandMapNodePaletteGroupNodes(" not in shell
    assert "const paletteHeaderRoot = ensureGrandMapNodePaletteHeaderNodes()" not in nodes_panel
    assert "const paletteSearchRoot = ensureGrandMapNodePaletteSearchNodes(" not in nodes_panel
    assert "<span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Nodes</span>" not in nodes_panel
    assert "drag - right-click" not in nodes_panel
    assert '<input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search nodes..."' not in nodes_panel
    assert "const rootId = ensureGrandMapNodePaletteSectionHeaderNodes(" not in section_header
    assert "const rootId = ensureGrandMapNodePaletteMenuItemNodes(" not in menu_item
    assert "const rootId = ensureGrandMapNodePaletteSkillSidecarNodes(" not in skill_sidecar
    assert "const rootId = ensureGrandMapNodePaletteItemNodes(" not in node_lib_item
    assert "() => ensureGrandMapNodePaletteShellNodes()" in shell
    assert "() => ensureGrandMapNodePaletteGroupNodes({ id, title, count, kind, open })" in shell
    assert "() => ensureGrandMapNodePaletteHeaderNodes()" in nodes_panel
    assert "() => ensureGrandMapNodePaletteSearchNodes({ query: q, sortMode })" in nodes_panel
    assert "() => ensureGrandMapNodePaletteSectionHeaderNodes({" in section_header
    assert "() => ensureGrandMapNodePaletteMenuItemNodes(item, {" in menu_item
    assert "() => ensureGrandMapNodePaletteSkillSidecarNodes(skill, {" in skill_sidecar
    assert "() => ensureGrandMapNodePaletteItemNodes(it, cat, {" in node_lib_item
    assert "if (kind === 'separator')" not in menu_item
    assert "runFallbackMenuItem" not in menu_item
    assert "return rootId" in section_header
    assert "return rootId" in menu_item
    assert "return rootId" in skill_sidecar
    assert "return rootId" in node_lib_item
    assert 'surface="node-palette-item"' in node_lib_item
    assert "rootProps={{" in node_lib_item
    assert "<div onMouseEnter={() => setH(true)}" not in node_lib_item


def test_node_palette_template_clones_rewrite_param_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone_names = [
        "cloneGrandMapNodePaletteItemTemplate",
        "cloneGrandMapNodePaletteGroupTemplate",
        "cloneGrandMapNodePaletteSectionHeaderTemplate",
        "cloneGrandMapNodePaletteMenuItemTemplate",
        "cloneGrandMapNodePaletteSkillSidecarTemplate",
    ]
    for name in clone_names:
        block = jsx[
            jsx.index(f"const {name} ="):
            jsx.index("const ensureGrandMap", jsx.index(f"const {name} ="))
        ]
        assert "if (node.data && node.data.role === 'parameter') return;" in block
        assert "resetClonedUiNodeParamLinks(copy);" in block
        assert "if (Array.isArray(copy.data.group_nodes)) copy.data.group_nodes = copy.data.group_nodes.map(mapId);" in block
        assert "if (copy.data.render_slot) copy.data.render_slot = mapId(copy.data.render_slot);" in block
        assert "finishClonedUiNodeParamAuthority(copy);" in block
        assert "upsert(g.nodes, copy);\n    syncClonedUiNodeParams(copy);" in block


def test_wire_promote_result_row_clone_rewrites_param_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    block = jsx[
        jsx.index("const cloneGrandMapWirePromoteResultRowTemplate ="):
        jsx.index("const ensureGrandMapWirePromoteResultRowNodes =", jsx.index("const cloneGrandMapWirePromoteResultRowTemplate ="))
    ]

    assert "if (node.data && node.data.role === 'parameter') return;" in block
    assert "resetClonedUiNodeParamLinks(copy);" in block
    assert "if (Array.isArray(copy.data.group_nodes)) copy.data.group_nodes = copy.data.group_nodes.map(mapId);" in block
    assert "if (copy.data.render_slot) copy.data.render_slot = mapId(copy.data.render_slot);" in block
    assert "copy.data.args = Object.assign({}, copy.data.args || {}, {" in block
    assert "finishClonedUiNodeParamAuthority(copy);" in block
    assert "upsert(g.nodes, copy);\n    syncClonedUiNodeParams(copy);" in block


def test_broken_wire_row_clone_rewrites_param_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    block = jsx[
        jsx.index("const cloneGrandMapBrokenWireRowTemplate ="):
        jsx.index("const ensureGrandMapBrokenWireRowNodes =", jsx.index("const cloneGrandMapBrokenWireRowTemplate ="))
    ]

    assert "const slotMap = {" in block
    assert "'slot:broken-wire-row-src': brokenWireEndpointLabel(row && row.src)" in block
    assert "'slot:broken-wire-row-dst': brokenWireEndpointLabel(row && row.dst)" in block
    assert "if (node.data && node.data.role === 'parameter') return;" in block
    assert "resetClonedUiNodeParamLinks(copy);" in block
    assert "if (Array.isArray(copy.data.group_nodes)) copy.data.group_nodes = copy.data.group_nodes.map(mapId);" in block
    assert "if (copy.data.render_slot) copy.data.render_slot = mapId(copy.data.render_slot);" in block
    assert "finishClonedUiNodeParamAuthority(copy);" in block
    assert "upsert(g.nodes, copy);\n    syncClonedUiNodeParams(copy);" in block


def test_graph_health_issue_row_clone_rewrites_param_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    block = jsx[
        jsx.index("const cloneGrandMapGraphHealthIssueRowTemplate ="):
        jsx.index("const ensureGrandMapGraphHealthIssueRowNodes =", jsx.index("const cloneGrandMapGraphHealthIssueRowTemplate ="))
    ]

    assert "const slotMap = {" in block
    assert "'slot:graph-health-issue-level': safeIssue.level ? String(safeIssue.level) : 'warn'" in block
    assert "'slot:graph-health-issue-message': safeIssue.msg ? String(safeIssue.msg) : ''" in block
    assert "if (node.data && node.data.role === 'parameter') return;" in block
    assert "resetClonedUiNodeParamLinks(copy);" in block
    assert "if (Array.isArray(copy.data.group_nodes)) copy.data.group_nodes = copy.data.group_nodes.map(mapId);" in block
    assert "if (copy.data.render_slot) copy.data.render_slot = mapId(copy.data.render_slot);" in block
    assert "copy.data.args = Object.assign({}, copy.data.args || {}, {" in block
    assert "node_id: safeIssue.node_id || ''" in block
    assert "finishClonedUiNodeParamAuthority(copy);" in block
    assert "upsert(g.nodes, copy);\n    syncClonedUiNodeParams(copy);" in block


def test_model_picker_group_and_row_clones_rewrite_param_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    group_block = jsx[
        jsx.index("const cloneGrandMapModelPickerGroupTemplate ="):
        jsx.index("const ensureGrandMapModelPickerGroupNodes =", jsx.index("const cloneGrandMapModelPickerGroupTemplate ="))
    ]
    row_block = jsx[
        jsx.index("const cloneGrandMapModelPickerRowTemplate ="):
        jsx.index("const ensureGrandMapModelPickerRowNodes =", jsx.index("const cloneGrandMapModelPickerRowTemplate ="))
    ]

    assert "'slot:model-picker-group-name': (group && group.name) || 'MODELS'" in group_block
    assert "clonedSlotMap[mapId(id)] = slotMap[id];" in group_block
    assert "syncGrandMapSurfaceStateSlots('model-picker-group-' + instanceId, rootId, clonedSlotMap" in group_block
    assert "state_key: 'model_picker_group_state_node_id'" in group_block
    assert "if (node.data && node.data.role === 'parameter') return;" in group_block
    assert "resetClonedUiNodeParamLinks(copy);" in group_block
    assert "if (copy.data.render_slot) copy.data.render_slot = mapId(copy.data.render_slot);" in group_block
    assert "finishClonedUiNodeParamAuthority(copy);" in group_block
    assert "upsert(g.nodes, copy);\n    syncClonedUiNodeParams(copy);" in group_block

    assert "const slotMap = {" in row_block
    assert "'slot:model-picker-row-name': clean.name || 'Model'" in row_block
    assert "'slot:model-picker-row-selected': slots && slots.selected ? 'true' : 'false'" in row_block
    assert "if (node.data && node.data.role === 'parameter') return;" in row_block
    assert "resetClonedUiNodeParamLinks(copy);" in row_block
    assert "if (copy.data.render_slot) copy.data.render_slot = mapId(copy.data.render_slot);" in row_block
    assert "copy.data.args = Object.assign({}, copy.data.args || {}, {" in row_block
    assert "model_id: clean.id || clean.name || ''" in row_block
    assert "finishClonedUiNodeParamAuthority(copy);" in row_block
    assert "upsert(g.nodes, copy);\n    syncClonedUiNodeParams(copy);" in row_block


def test_node_palette_async_template_imports_wake_surface_wrappers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ensure_names = [
        "ensureGrandMapNodePaletteItemNodes",
        "ensureGrandMapNodePaletteGroupNodes",
        "ensureGrandMapNodePaletteSectionHeaderNodes",
        "ensureGrandMapNodePaletteMenuItemNodes",
        "ensureGrandMapNodePaletteSkillSidecarNodes",
    ]
    for name in ensure_names:
        block = jsx[
            jsx.index(f"const {name} ="):
            jsx.index("const cloneGrandMap" if "SkillSidecar" not in name else "const ensureGrandMapNodeRail", jsx.index(f"const {name} ="))
        ]
        assert "window.dispatchEvent(new Event('archhub-ui-surface-imported'))" in block
        assert "window.dispatchEvent(new Event('lm-graph-bump'))" in block


def test_account_brain_share_node_rail_and_status_keep_node_updates_out_of_inline_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    router_status = jsx[
        jsx.index("const RouterStatus ="):
        jsx.index("const PROVIDER_TAG =", jsx.index("const RouterStatus ="))
    ]
    account_identity = jsx[
        jsx.index("const AccountIdentity ="):
        jsx.index("const AccountChip =", jsx.index("const AccountIdentity ="))
    ]
    account_chip = jsx[
        jsx.index("const AccountChip ="):
        jsx.index("const _syncWhen =", jsx.index("const AccountChip ="))
    ]
    brain_chip = jsx[
        jsx.index("const BrainChip ="):
        jsx.index("const HomeGraphHealthChip =")
    ]
    share_shell = jsx[
        jsx.index("const SharePanelShellSurface ="):
        jsx.index("const SharePanel =", jsx.index("const SharePanelShellSurface ="))
    ]
    empty_node_rail = jsx[
        jsx.index("const EmptyNodeRailShellSurface ="):
        jsx.index("const NodeRailShellSurface =")
    ]
    node_rail_shell = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =")
    ]
    server_strip = jsx[
        jsx.index("const ServerStrip ="):
        jsx.index("const ServerStripMemo =")
    ]

    assert "const routerStatusRoot = ensureGrandMapCanvasRouterStatusNodes(" not in router_status
    assert "const rootId = ensureGrandMapAccountIdentityNodes(" not in account_identity
    assert "const accountChipRoot = ensureGrandMapCanvasAccountChipNodes(" not in account_chip
    assert "const accountMenuRoot = ensureGrandMapCanvasAccountMenuNodes(" not in account_chip
    assert "const brainChipRoot = ensureGrandMapCanvasBrainChipNodes(" not in brain_chip
    assert 'data-testid="router-status"' not in router_status
    assert 'data-account-state="signed-out"' not in account_chip
    assert 'data-account-state="signed-in"' not in account_chip
    assert 'data-testid="account-menu"' not in account_chip
    assert "const AccountMenuItem =" not in account_chip
    assert 'data-testid="brain-chip"' not in brain_chip
    assert "const rootId = ensureGrandMapSharePanelShellNodes()" not in share_shell
    assert "const rootId = ensureGrandMapNodeRailEmptyShellNodes()" not in empty_node_rail
    assert "const statusRootId = ensureGrandMapStatusStripNodes(" not in server_strip
    assert "() => ensureGrandMapCanvasRouterStatusNodes({ label: shown })" in router_status
    assert "() => ensureGrandMapAccountIdentityNodes({" in account_identity
    assert "() => ensureGrandMapCanvasAccountChipNodes({" in account_chip
    assert "() => signedIn ? ensureGrandMapCanvasAccountMenuNodes({ email }) : null" in account_chip
    assert "() => ensureGrandMapCanvasBrainChipNodes({ label, state: brainState })" in brain_chip
    assert "() => ensureGrandMapSharePanelShellNodes()" in share_shell
    assert "() => ensureGrandMapNodeRailEmptyShellNodes()" in empty_node_rail
    assert "useGrandMapSurfaceRoot(" in node_rail_shell
    assert "() => ensureGrandMapStatusStripNodes({" in server_strip


def test_account_chip_state_syncs_to_inline_graph_node_state():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    sync_helper = jsx[
        jsx.index("const syncGrandMapAccountChipState ="):
        jsx.index("const ensureGrandMapAccountIdentityNodes =", jsx.index("const syncGrandMapAccountChipState ="))
    ]
    account_chip = jsx[
        jsx.index("const AccountChip ="):
        jsx.index("const _syncWhen =", jsx.index("const AccountChip ="))
    ]

    assert "const syncGrandMapAccountChipState = (state) =>" in sync_helper
    assert "account_chip_state_node: true" in sync_helper
    assert "account_signed_in: signedIn" in sync_helper
    assert "account_state: signedIn ? 'signed-in' : 'signed-out'" in sync_helper
    assert "account_menu_open: menuOpen" in sync_helper
    assert "account_email: (state && state.email) || ''" in sync_helper
    assert "account_plan: (state && state.plan) || ''" in sync_helper
    assert "account_remaining_messages: typeof (state && state.remaining) === 'number' ? state.remaining : ''" in sync_helper
    assert "account_cloud_url: (state && state.cloudUrl) || ''" in sync_helper
    assert "syncNode(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'account_chip_state');" in sync_helper
    assert "syncNode('ui:grandmap:canvas-account-chip', 'account_chip_state');" in sync_helper
    assert "syncNode('ui:grandmap:canvas-account-menu', 'account_menu_state');" in sync_helper
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(node, key, payload[key]));" in sync_helper
    assert "window.ahSetUiNodeParam(nodeId, key, payload[key]);" not in sync_helper
    assert "syncGrandMapAccountChipState({" in account_chip
    assert "menuOpen," in account_chip
    assert "}, [signedIn, email, cloudUrl, plan, remaining, menuOpen, label]);" in account_chip


def test_account_and_router_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    router = jsx[
        jsx.index("const ensureGrandMapCanvasRouterStatusNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasBrainChipNodes =",
            jsx.index("const ensureGrandMapCanvasRouterStatusNodes ="),
        )
    ]
    brain = jsx[
        jsx.index("const ensureGrandMapCanvasBrainChipNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasAccountChipNodes =",
            jsx.index("const ensureGrandMapCanvasBrainChipNodes ="),
        )
    ]
    account_chip = jsx[
        jsx.index("const ensureGrandMapCanvasAccountChipNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasAccountMenuNodes =",
            jsx.index("const ensureGrandMapCanvasAccountChipNodes ="),
        )
    ]
    account_menu = jsx[
        jsx.index("const ensureGrandMapCanvasAccountMenuNodes ="):
        jsx.index(
            "const syncGrandMapAccountChipState =",
            jsx.index("const ensureGrandMapCanvasAccountMenuNodes ="),
        )
    ]
    account_identity = jsx[
        jsx.index("const ensureGrandMapAccountIdentityNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasNewSessionActionNodes =",
            jsx.index("const ensureGrandMapAccountIdentityNodes ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('canvas-router-status', rootId, slotMap" in router
    assert "state_key: 'canvas_router_status_state_node_id'" in router
    assert "'slot:canvas-router-label': slots && slots.label ? slots.label : ''" in router
    assert "syncGrandMapSurfaceStateSlots('canvas-brain-chip', rootId, slotMap" in brain
    assert "state_key: 'canvas_brain_chip_state_node_id'" in brain
    assert "'slot:canvas-brain-state': slots && slots.state ? slots.state : 'idle'" in brain
    assert "syncGrandMapSurfaceStateSlots('canvas-account-chip', rootId, slotMap" in account_chip
    assert "state_key: 'canvas_account_chip_state_node_id'" in account_chip
    assert "'slot:canvas-account-state': slots && slots.state ? slots.state : 'signed-out'" in account_chip
    assert "syncGrandMapSurfaceStateSlots('canvas-account-menu', rootId, slotMap" in account_menu
    assert "state_key: 'canvas_account_menu_state_node_id'" in account_menu
    assert "'slot:canvas-account-email': slots && slots.email ? slots.email : ''" in account_menu
    assert "syncGrandMapSurfaceStateSlots('account-identity', rootId, slotMap" in account_identity
    assert "state_key: 'account_identity_state_node_id'" in account_identity
    assert "'slot:account-identity-state': slots && slots.state ? slots.state : 'signed-out'" in account_identity


def test_share_panel_shell_hydrates_share_panel_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    share_panel = jsx[
        jsx.index("const SharePanel ="):
        jsx.index("const RAIL_DRAWER_META =", jsx.index("const SharePanel ="))
    ]

    assert "const SharePanelShellSurface = ({ header, description, list }) =>" in jsx
    assert "const ensureGrandMapSharePanelShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'share-panel-shell'" in jsx
    assert "<SharePanelShellSurface" in share_panel
    assert "slot:share-panel-shell-header" in jsx
    assert "slot:share-panel-shell-description" in jsx
    assert "slot:share-panel-shell-list" in jsx
    assert "<div data-panel=\"share\" data-testid=\"rail-share\"" not in share_panel


def test_share_panel_hydrates_inner_content_from_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    share_panel = jsx[
        jsx.index("const SharePanel ="):
        jsx.index("const RAIL_DRAWER_META =", jsx.index("const SharePanel ="))
    ]

    for surface in [
        "share-panel-header",
        "share-panel-description",
        "share-panel-list",
        "share-panel-section-heading",
        "share-panel-row",
        "share-panel-empty-state",
        "share-panel-loading",
    ]:
        assert f"get_grand_map_ui_surface', '{surface}'" in jsx

    assert "const SharePanelHeaderSurface = ({ nShare }) =>" in jsx
    assert "const SharePanelListSurface = ({ children }) =>" in jsx
    assert "const SharePanelRowSurface = ({ kind, item, busy, note, doExport, doPublish }) =>" in jsx
    assert "<SharePanelHeaderSurface nShare={nShare}/>" in share_panel
    assert "<SharePanelDescriptionSurface/>" in share_panel
    assert "<SharePanelListSurface>" in share_panel
    assert '<SharePanelSectionHeadingSurface id="skills" title="SKILLS"/>' in share_panel
    assert '<SharePanelSectionHeadingSurface id="sessions" title="SESSIONS"/>' in share_panel
    assert "<SharePanelRowSurface" in share_panel
    assert "<SharePanelEmptyStateSurface" in share_panel
    assert "<SharePanelLoadingSurface visible={!loaded}/>" in share_panel
    assert "share.row.export" in jsx
    assert "share.row.publish" in jsx
    assert "lm-ui-node-action" in jsx
    assert "actBtn =" not in share_panel
    assert "rowNote =" not in share_panel
    assert '<div className="ah-scroll" style={{ flex:1, overflow:\'auto\'' not in share_panel
    assert 'data-testid="rail-share-skill-row"' not in share_panel
    assert 'data-testid="rail-share-session-row"' not in share_panel


def test_share_panel_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    header = jsx[
        jsx.index("const ensureGrandMapSharePanelHeaderNodes ="):
        jsx.index(
            "const ensureGrandMapSharePanelDescriptionNodes =",
            jsx.index("const ensureGrandMapSharePanelHeaderNodes ="),
        )
    ]
    description = jsx[
        jsx.index("const ensureGrandMapSharePanelDescriptionNodes ="):
        jsx.index(
            "const ensureGrandMapSharePanelListNodes =",
            jsx.index("const ensureGrandMapSharePanelDescriptionNodes ="),
        )
    ]
    list_nodes = jsx[
        jsx.index("const ensureGrandMapSharePanelListNodes ="):
        jsx.index(
            "const cloneGrandMapSharePanelTemplate =",
            jsx.index("const ensureGrandMapSharePanelListNodes ="),
        )
    ]
    clone_helper = jsx[
        jsx.index("const cloneGrandMapSharePanelTemplate ="):
        jsx.index(
            "const ensureGrandMapSharePanelSectionHeadingNodes =",
            jsx.index("const cloneGrandMapSharePanelTemplate ="),
        )
    ]
    loading = jsx[
        jsx.index("const ensureGrandMapSharePanelLoadingNodes ="):
        jsx.index(
            "const ensureGrandMapSkillsPanelHeaderNodes =",
            jsx.index("const ensureGrandMapSharePanelLoadingNodes ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('share-panel-header', rootId, slotMap" in header
    assert "state_key: 'share_panel_header_state_node_id'" in header
    assert "'slot:share-panel-title': 'Share & publish'" in header
    assert "'slot:share-panel-count': ((slots && slots.count != null)" in header
    assert "syncGrandMapSurfaceStateSlots('share-panel-description', rootId, slotMap" in description
    assert "state_key: 'share_panel_description_state_node_id'" in description
    assert "'slot:share-panel-description':" in description
    assert "syncGrandMapSurfaceStateSlots('share-panel-list', rootId, slotMap" in list_nodes
    assert "state_key: 'share_panel_list_state_node_id'" in list_nodes
    assert "'slot:share-panel-list-content': ''" in list_nodes
    assert "const clonedSlotMap = {};" in clone_helper
    assert "clonedSlotMap[mapId(id)] = slotMap[id];" in clone_helper
    assert "syncGrandMapSurfaceStateSlots('share-panel-instance-'" in clone_helper
    assert "state_key: 'share_panel_instance_state_node_id'" in clone_helper
    assert "syncGrandMapSurfaceStateSlots('share-panel-loading', rootId, slotMap" in loading
    assert "state_key: 'share_panel_loading_state_node_id'" in loading
    assert "'slot:share-loading-visible': slots && slots.visible ? 'true' : 'false'" in loading
    assert "'slot:share-loading-message': (slots && slots.message)" in loading


def test_grand_map_new_session_action_emits_clickable_action_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_open_session", "Open Session")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-new-session-action", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:new-session-action"
    assert payload["source_node_ids"] == ["sessions_open_session"]

    [node] = _non_parameter_nodes(payload)
    assert node["id"] == "ui:grandmap:new-session-action"
    assert node["type"] == "ui.element"
    assert node["data"]["tag"] == "button"
    assert node["data"]["text"] == "+ new canvas"
    assert node["data"]["cls"] == "ah-node-action-button"
    assert node["data"]["action"] == "session.create"
    assert node["data"]["args"] == {"title": "untitled"}
    assert node["data"]["source_map_node"] == "sessions_open_session"


def test_grand_map_ui_action_is_behavior_node_with_real_wires(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_open_session", "Open Session")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-new-session-action", grand_map_path=grand_map)

    nodes = {node["id"]: node for node in payload["nodes"]}
    wires = {wire["id"]: wire for wire in payload["wires"]}
    root = nodes["ui:grandmap:new-session-action"]
    action_node_id = "action:ui-grandmap-new-session-action:action:session.create"
    action_param_node_id = "param:ui:grandmap:new-session-action:action"

    assert action_node_id in root["data"]["action_nodes"]
    assert action_node_id in root["data"]["group_nodes"]
    assert action_param_node_id in root["data"]["group_nodes"]

    action_node = nodes[action_node_id]
    assert action_node["kind"] == "behavior"
    assert action_node["data"]["role"] == "ui_action"
    assert action_node["data"]["owner"] == root["id"]
    assert action_node["data"]["action_key"] == "action"
    assert action_node["data"]["action"] == "session.create"
    assert action_node["data"]["action_param_node_id"] == action_param_node_id
    assert action_node["data"]["args"] == {"title": "untitled"}
    assert action_node["data"]["event_count"] == 0
    assert "drive_behavior" in action_node["data"]["capabilities"]

    assert "param:action:ui-grandmap-new-session-action:action:session.create:action" in nodes
    assert "param:action:ui-grandmap-new-session-action:action:session.create:event_count" in nodes
    assert wires["w:ui-action:ui-grandmap-new-session-action:action:owner"] == {
        "id": "w:ui-action:ui-grandmap-new-session-action:action:owner",
        "from": {"node": root["id"], "port": "action:action"},
        "to": {"node": action_node_id, "port": "owner"},
        "data": {
            "role": "ui_action_relation",
            "relation": "emits_behavior",
            "owner": root["id"],
            "action_node": action_node_id,
            "action_key": "action",
            "action": "session.create",
        },
    }
    assert wires["w:ui-action:ui-grandmap-new-session-action:action:param"]["from"] == {
        "node": action_param_node_id,
        "port": "value",
    }
    assert wires["w:ui-action:ui-grandmap-new-session-action:action:param"]["to"] == {
        "node": action_node_id,
        "port": "action_param",
    }


def test_grand_map_session_toolbar_emits_grouped_control_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_cloud_sync", "Cloud Sync"),
                _node("sessions_open_session", "Open Session"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-session-toolbar", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:session-toolbar"
    assert payload["source_node_ids"] == [
        "sessions_cloud_sync",
        "sessions_threads_rail",
        "sessions_open_session",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:session-filter"]["data"]["value"] == "all"
    assert nodes["slot:select-mode"]["data"]["value"] == "false"
    assert nodes["slot:session-sync-label"]["data"]["value"] == "sync sessions"
    assert nodes["ui:grandmap:session-toolbar"]["data"]["children"] == [
        "ui:grandmap:session-sync",
        "ui:grandmap:session-filter-all",
        "ui:grandmap:session-filter-mine",
        "ui:grandmap:session-filter-workflows",
        "ui:grandmap:session-select-toggle",
        "ui:grandmap:new-session-action",
    ]
    assert nodes["ui:grandmap:session-sync"]["data"]["action"] == "sessions.sync"
    assert nodes["ui:grandmap:session-sync"]["data"]["bind"] == "slot:session-sync-label"
    assert nodes["ui:grandmap:session-filter-all"]["data"]["action"] == "sessions.filter.set"
    assert nodes["ui:grandmap:session-filter-all"]["data"]["args"] == {"filter": "all"}
    assert nodes["ui:grandmap:session-filter-all"]["data"]["active_bind"] == "slot:session-filter"
    assert nodes["ui:grandmap:session-filter-all"]["data"]["active_value"] == "all"
    assert nodes["ui:grandmap:session-select-toggle"]["data"]["action"] == "sessions.select.toggle"
    assert nodes["ui:grandmap:session-select-toggle"]["data"]["text_cases"] == {
        "bind": "slot:select-mode",
        "values": {"true": "done", "false": "select"},
        "default": "select",
    }
    assert nodes["ui:grandmap:new-session-action"]["data"]["action"] == "session.create"


def test_grand_map_selection_toolbar_emits_bulk_action_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_clear_graph", "Clear Graph"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-selection-toolbar", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:selection-toolbar"
    assert payload["source_node_ids"] == [
        "sessions_threads_rail",
        "sessions_clear_graph",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:selected-count"]["data"]["value"] == "0"
    assert nodes["slot:all-visible-selected"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:selection-toolbar"]["data"]["children"] == [
        "ui:grandmap:session-select-all",
        "ui:grandmap:session-selected-count",
        "ui:grandmap:session-delete-selected",
        "ui:grandmap:session-select-cancel",
    ]
    assert nodes["ui:grandmap:session-select-all"]["data"]["action"] == "sessions.select.visible.toggle"
    assert nodes["ui:grandmap:session-select-all"]["data"]["text_cases"] == {
        "bind": "slot:all-visible-selected",
        "values": {"true": "clear all", "false": "select all"},
        "default": "select all",
    }
    assert nodes["ui:grandmap:session-selected-count"]["data"]["bind"] == "slot:selected-count"
    assert nodes["ui:grandmap:session-delete-selected"]["data"]["action"] == "sessions.selected.delete"
    assert nodes["ui:grandmap:session-delete-selected"]["data"]["disabled_bind"] == "slot:selected-count"
    assert nodes["ui:grandmap:session-delete-selected"]["data"]["disabled_value"] == "0"
    assert nodes["ui:grandmap:session-select-cancel"]["data"]["action"] == "sessions.select.cancel"
    wires = {wire["id"]: wire for wire in payload["wires"]}
    assert wires["w:ui-binding:slot-all-visible-selected->ui-grandmap-session-select-all:text_cases.bind"]["data"] == {
        "role": "ui_binding_relation",
        "relation": "drives_text_cases.bind",
        "source_node": "slot:all-visible-selected",
        "target_node": "ui:grandmap:session-select-all",
        "binding_key": "text_cases.bind",
        "value_key": "text_cases.bind",
    }
    assert wires["w:ui-binding:slot-selected-count->ui-grandmap-session-delete-selected:disabled_bind"]["to"] == {
        "node": "ui:grandmap:session-delete-selected",
        "port": "binding:disabled_bind",
    }
    assert (
        "w:ui-binding:slot-selected-count->ui-grandmap-session-delete-selected:disabled_bind"
        in nodes["ui:grandmap:session-delete-selected"]["data"]["binding_wires"]
    )


def test_grand_map_home_empty_state_emits_bound_message_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-empty-state", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:home-empty-state"
    assert payload["source_node_ids"] == ["sessions_threads_rail"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:empty-state-message"]["data"]["value"] == (
        "No sessions yet. Type a title above and hit Enter."
    )
    assert nodes["ui:grandmap:home-empty-state"]["data"]["children"] == [
        "ui:grandmap:empty-state-message"
    ]
    assert nodes["ui:grandmap:empty-state-message"]["data"]["bind"] == "slot:empty-state-message"


def test_home_toolbar_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    sessions_header = jsx[
        jsx.index("const ensureGrandMapSessionsHeaderNodes ="):
        jsx.index("const ensureGrandMapSessionToolbarNodes =", jsx.index("const ensureGrandMapSessionsHeaderNodes ="))
    ]
    session_toolbar = jsx[
        jsx.index("const ensureGrandMapSessionToolbarNodes ="):
        jsx.index("const ensureGrandMapSelectionToolbarNodes =", jsx.index("const ensureGrandMapSessionToolbarNodes ="))
    ]
    selection_toolbar = jsx[
        jsx.index("const ensureGrandMapSelectionToolbarNodes ="):
        jsx.index("const ensureGrandMapHomeEmptyStateNodes =", jsx.index("const ensureGrandMapSelectionToolbarNodes ="))
    ]
    empty_state = jsx[
        jsx.index("const ensureGrandMapHomeEmptyStateNodes ="):
        jsx.index("const grandMapSlotValueType =", jsx.index("const ensureGrandMapHomeEmptyStateNodes ="))
    ]

    assert "syncGrandMapSurfaceStateSlots('home-sessions-header', rootId, slotMap" in sessions_header
    assert "state_key: 'sessions_header_state_node_id'" in sessions_header
    assert "'slot:session-count': __grandMapUiHomeSlots.sessionCount || 0" in sessions_header
    assert "syncGrandMapSurfaceStateSlots('home-session-toolbar', rootId, slotMap" in session_toolbar
    assert "state_key: 'session_toolbar_state_node_id'" in session_toolbar
    assert "'slot:session-filter': __grandMapUiHomeSlots.filter || 'all'" in session_toolbar
    assert "'slot:select-mode': selectMode" in session_toolbar
    assert "'slot:session-sync-label': __grandMapUiHomeSlots.syncLabel || 'sync sessions'" in session_toolbar
    assert "syncGrandMapSurfaceStateSlots('home-selection-toolbar', rootId, slotMap" in selection_toolbar
    assert "state_key: 'selection_toolbar_state_node_id'" in selection_toolbar
    assert "'slot:selected-count': __grandMapUiHomeSlots.selectedCount || 0" in selection_toolbar
    assert "'slot:all-visible-selected': allVisibleSelected" in selection_toolbar
    assert "syncGrandMapSurfaceStateSlots('home-empty-state', rootId, slotMap" in empty_state
    assert "state_key: 'empty_state_node_id'" in empty_state
    assert "const slotMap = { 'slot:empty-state-message': message };" in empty_state


def test_grand_map_session_card_template_emits_action_node_shell(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_session_object", "Session Object"),
                _node("sessions_open_session", "Open Session"),
                _node("sessions_threads_rail", "Threads Rail"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-session-card", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:session-card"
    assert payload["source_node_ids"] == [
        "sessions_session_object",
        "sessions_open_session",
        "sessions_threads_rail",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:session-title"]["data"]["value"] == ""
    assert nodes["slot:session-state"]["data"]["value"] == ""
    assert nodes["slot:session-selected"]["data"]["value"] == "false"
    root = nodes["ui:grandmap:session-card"]
    assert root["data"]["action"] == "sessions.card.activate"
    assert root["data"]["role"] == "button"
    assert root["data"]["active_bind"] == "slot:session-selected"
    assert root["data"]["children"] == [
        "ui:grandmap:session-card-top",
        "ui:grandmap:session-card-title",
        "ui:grandmap:session-card-last",
        "ui:grandmap:session-card-footer",
        "ui:grandmap:session-card-menu",
        "ui:grandmap:session-card-menu-slot",
    ]
    assert nodes["ui:grandmap:session-card-title"]["data"]["bind"] == "slot:session-title"
    assert nodes["ui:grandmap:session-card-state"]["data"]["bind"] == "slot:session-state"
    assert nodes["ui:grandmap:session-card-menu"]["data"]["action"] == "sessions.card.menu.toggle"
    assert nodes["ui:grandmap:session-card-menu-slot"]["data"]["render_slot"] == (
        "slot:session-card-menu"
    )


def test_home_session_surfaces_wire_slots_to_session_object_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers_start = jsx.index("const grandMapSlotValueType =")
    helpers_end = jsx.index(
        "const ensureGrandMapSessionCardNodes =",
        helpers_start,
    )
    helpers = jsx[helpers_start:helpers_end]
    chat_start = jsx.index("const cloneGrandMapChatSessionRowTemplate =")
    chat_end = jsx.index(
        "const ensureGrandMapChatSessionRowNodes =",
        chat_start,
    )
    chat = jsx[chat_start:chat_end]

    assert "type: 'stem.node'" in helpers
    assert "kind: 'session'" in helpers
    assert "role: 'session_object'" in helpers
    assert "['title', session.title || session.id || 'session']" in helpers
    assert "['state', session.state || 'idle']" in helpers
    assert "materializeGrandMapParamNode(nodeId, paramKey, paramValue);" in helpers
    assert "window.ahSetUiNodeParam(nodeId, 'title'" not in helpers
    assert "window.ahSetUiNodeParam(nodeId, 'state'" not in helpers
    assert "syncGrandMapOwnedSlotRelations('session-card', mapId, slotMap, sessionNodeId, 'session_card')" in helpers
    assert "syncGrandMapOwnedSlotRelations('chat-session-row', mapId, slotMap, sessionNodeId, 'chat_session_row')" in chat
    assert "resetClonedUiNodeParamLinks(copy);" in helpers
    assert "copy.data.children = copy.data.children.map(mapId)" in helpers
    assert "if (Array.isArray(copy.data.group_nodes)) copy.data.group_nodes = copy.data.group_nodes.map(mapId);" in helpers
    assert "finishClonedUiNodeParamAuthority(copy);" in helpers
    assert "syncClonedUiNodeParams(copy);" in helpers
    assert "syncGrandMapMappedSurfaceState('session-card', sid, rootId, mappedSlotMap" in helpers
    assert "state_key: 'session_card_state_node_id'" in helpers
    assert "syncGrandMapMappedSurfaceState('chat-session-row', sid, rootId, mappedSlotMap" in chat
    assert "state_key: 'chat_session_row_state_node_id'" in chat
    assert "syncUiSlotParameterRelation(mapId(slotId), ownerNodeId" in helpers
    assert "value_type: grandMapSlotValueType(slotName)" in helpers
    assert "behavior: 'render-slot'" in helpers
    assert "provenance: 'runtime:syncGrandMapOwnedSlotRelations'" in helpers
    assert "materialize_slot_param_nodes: false" in helpers
    assert "session_object_node_id: sessionNodeId" in helpers
    assert "sessionNodeId ? [sessionNodeId] : []" in helpers
    assert "session_object_node_id: sessionNodeId" in chat
    assert "setGrandMapInlineNodeField(root, 'session_object_node_id', sessionNodeId)" in helpers
    assert "setGrandMapInlineNodeField(root, 'session_object_node_id', sessionNodeId)" in chat
    assert "window.ahSetUiNodeParam(rootId, 'session_object_node_id', sessionNodeId)" not in helpers
    assert "window.ahSetUiNodeParam(rootId, 'session_object_node_id', sessionNodeId)" not in chat


def test_grand_map_session_action_menu_emits_action_buttons(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_open_session", "Open Session"),
                _node("sessions_version_history", "Version History"),
                _node("sessions_clear_graph", "Clear Graph"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("home-session-action-menu", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:session-action-menu"
    assert payload["source_node_ids"] == [
        "sessions_threads_rail",
        "sessions_open_session",
        "sessions_version_history",
        "sessions_clear_graph",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:session-action-menu"]["data"]["cls"] == (
        "ah-session-action-menu-node"
    )
    assert nodes["ui:grandmap:session-action-menu"]["data"]["children"] == [
        "ui:grandmap:session-action-rename",
        "ui:grandmap:session-action-fork",
        "ui:grandmap:session-action-duplicate",
        "ui:grandmap:session-action-separator",
        "ui:grandmap:session-action-delete",
    ]
    assert nodes["ui:grandmap:session-action-rename"]["data"]["action"] == "sessions.menu.action"
    assert nodes["ui:grandmap:session-action-rename"]["data"]["args"] == {"action": "rename"}
    assert nodes["ui:grandmap:session-action-fork"]["data"]["args"] == {"action": "fork"}
    assert nodes["ui:grandmap:session-action-duplicate"]["data"]["args"] == {"action": "duplicate"}
    assert nodes["ui:grandmap:session-action-delete"]["data"]["args"] == {"action": "delete"}
    assert "ah-session-menu-danger-node" in nodes["ui:grandmap:session-action-delete"]["data"]["cls"]


def test_grand_map_composer_actions_emit_action_buttons(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_composer_bar", "Composer Bar")])

    payload = grand_map_ui_surface("home-composer-actions", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:composer-actions"
    assert payload["source_node_ids"] == ["ui_composer_bar"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:composer-recording"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:composer-actions"]["data"]["children"] == [
        "ui:grandmap:composer-attach",
        "ui:grandmap:composer-voice",
        "ui:grandmap:composer-send",
    ]
    assert nodes["ui:grandmap:composer-attach"]["data"]["action"] == "composer.attach"
    assert nodes["ui:grandmap:composer-voice"]["data"]["action"] == "composer.voice.toggle"
    assert nodes["ui:grandmap:composer-voice"]["data"]["text_cases"] == {
        "bind": "slot:composer-recording",
        "values": {"true": "stop rec", "false": "voice"},
        "default": "voice",
    }
    assert nodes["ui:grandmap:composer-send"]["data"]["action"] == "composer.submit"


def test_grand_map_composer_body_emits_form_and_textarea_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_composer_bar", "Composer Bar")])

    payload = grand_map_ui_surface("home-composer-body", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:composer-body"
    assert payload["source_node_ids"] == ["ui_composer_bar"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:composer-drag-over"]["data"]["value"] == "false"
    assert nodes["slot:composer-attachment-count"]["data"]["value"] == "0"
    assert nodes["ui:grandmap:composer-body"]["data"]["tag"] == "form"
    assert nodes["ui:grandmap:composer-body"]["data"]["action"] == "composer.form.submit"
    assert nodes["ui:grandmap:composer-body"]["data"]["children"] == [
        "ui:grandmap:composer-attachments",
        "ui:grandmap:composer-file-input",
        "ui:grandmap:composer-row",
    ]
    assert nodes["ui:grandmap:composer-file-input"]["data"]["tag"] == "input"
    assert nodes["ui:grandmap:composer-file-input"]["data"]["input_type"] == "file"
    assert nodes["ui:grandmap:composer-textarea"]["data"]["tag"] == "textarea"
    assert nodes["ui:grandmap:composer-textarea"]["data"]["action"] == "composer.text.update"
    assert nodes["ui:grandmap:composer-textarea"]["data"]["submit_action"] == "composer.submit"
    assert nodes["ui:grandmap:composer-actions-mount"]["data"]["surface_ref"] == "home-composer-actions"


def test_grand_map_canvas_composer_body_emits_mode_and_submit_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_composer_bar", "Composer Bar")])

    payload = grand_map_ui_surface("canvas-composer-body", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-composer-body"
    assert payload["source_node_ids"] == ["ui_composer_bar"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-composer-mode"]["data"]["value"] == "plan"
    assert nodes["slot:canvas-composer-text"]["data"]["value"] == ""
    assert nodes["ui:grandmap:canvas-composer-body"]["data"]["action"] == "canvas.composer.submit"
    assert nodes["ui:grandmap:canvas-composer-textarea"]["data"]["action"] == "canvas.composer.text.update"
    assert nodes["ui:grandmap:canvas-composer-textarea"]["data"]["submit_action"] == "canvas.composer.submit"
    assert nodes["ui:grandmap:canvas-composer-attach"]["data"]["action"] == "canvas.composer.attach"
    assert nodes["ui:grandmap:canvas-composer-voice"]["data"]["action"] == "canvas.composer.voice.toggle"
    assert nodes["ui:grandmap:canvas-composer-send"]["data"]["action"] == "canvas.composer.submit"
    assert nodes["ui:grandmap:canvas-composer-mode-picker"]["data"]["test_id"] == "composer-mode-picker"
    assert nodes["ui:grandmap:canvas-composer-mode-plan"]["data"]["args"] == {"mode": "plan"}
    assert nodes["ui:grandmap:canvas-composer-mode-auto"]["data"]["args"] == {"mode": "auto"}
    assert nodes["ui:grandmap:canvas-composer-mode-yolo"]["data"]["args"] == {"mode": "yolo"}
    assert nodes["ui:grandmap:canvas-composer-mode-extend"]["data"]["args"] == {"mode": "extend"}


def test_grand_map_canvas_composer_help_emits_command_rows(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-composer-help", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-composer-help"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:canvas-composer-help-title"]["data"]["text"] == "SLASH COMMANDS"
    assert nodes["ui:grandmap:canvas-composer-help-wire"]["data"]["children"] == [
        "ui:grandmap:canvas-composer-help-wire-command",
        "ui:grandmap:canvas-composer-help-wire-description",
    ]
    assert nodes["ui:grandmap:canvas-composer-help-wire-command"]["data"]["text"] == "/wire"
    assert nodes["ui:grandmap:canvas-composer-help-createnode-command"]["data"]["text"] == "/createnode"


def test_grand_map_canvas_toolbar_emits_zoom_and_run_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-toolbar", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-toolbar"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-zoom-percent"]["data"]["value"] == "100"
    assert nodes["ui:grandmap:canvas-toolbar"]["data"]["children"] == [
        "ui:grandmap:canvas-zoom-in",
        "ui:grandmap:canvas-zoom-out",
        "ui:grandmap:canvas-zoom-label",
        "ui:grandmap:canvas-fit",
        "ui:grandmap:canvas-toolbar-separator",
        "ui:grandmap:canvas-run-workflow",
    ]
    assert nodes["ui:grandmap:canvas-zoom-in"]["data"]["action"] == "canvas.toolbar.zoom.in"
    assert nodes["ui:grandmap:canvas-zoom-out"]["data"]["action"] == "canvas.toolbar.zoom.out"
    assert nodes["ui:grandmap:canvas-zoom-label"]["data"]["bind"] == "slot:canvas-zoom-percent"
    assert nodes["ui:grandmap:canvas-fit"]["data"]["action"] == "canvas.toolbar.fit"
    assert nodes["ui:grandmap:canvas-run-workflow"]["data"]["action"] == "canvas.toolbar.run"


def test_canvas_composer_and_toolbar_slots_wire_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const grandMapSurfaceStateNodeId ="):
        jsx.index("const cloneGrandMapSessionCardTemplate =", jsx.index("const grandMapSurfaceStateNodeId ="))
    ]
    composer = jsx[
        jsx.index("const ensureGrandMapCanvasComposerBodyNodes ="):
        jsx.index("const ensureGrandMapCanvasComposerHelpNodes =", jsx.index("const ensureGrandMapCanvasComposerBodyNodes ="))
    ]
    home_actions = jsx[
        jsx.index("const ensureGrandMapComposerActionsNodes ="):
        jsx.index("const ensureGrandMapComposerBodyNodes =", jsx.index("const ensureGrandMapComposerActionsNodes ="))
    ]
    home_body = jsx[
        jsx.index("const ensureGrandMapComposerBodyNodes ="):
        jsx.index("const seedGrandMapCanvasToolbarFallbackNodes =", jsx.index("const ensureGrandMapComposerBodyNodes ="))
    ]
    fallback_actions = jsx[
        jsx.index("const seedGrandMapComposerActionsFallbackNodes ="):
        jsx.index("const seedGrandMapComposerBodyFallbackNodes =", jsx.index("const seedGrandMapComposerActionsFallbackNodes ="))
    ]
    fallback_body = jsx[
        jsx.index("const seedGrandMapComposerBodyFallbackNodes ="):
        jsx.index("const ensureGrandMapSessionsHeaderNodes =", jsx.index("const seedGrandMapComposerBodyFallbackNodes ="))
    ]
    fallback_canvas_toolbar = jsx[
        jsx.index("const seedGrandMapCanvasToolbarFallbackNodes ="):
        jsx.index("const seedGrandMapCanvasComposerBodyFallbackNodes =", jsx.index("const seedGrandMapCanvasToolbarFallbackNodes ="))
    ]
    fallback_canvas_composer = jsx[
        jsx.index("const seedGrandMapCanvasComposerBodyFallbackNodes ="):
        jsx.index("const ensureGrandMapCanvasComposerBodyNodes =", jsx.index("const seedGrandMapCanvasComposerBodyFallbackNodes ="))
    ]
    toolbar = jsx[
        jsx.index("const ensureGrandMapCanvasToolbarNodes ="):
        jsx.index("const ensureGrandMapCanvasNodeCardNodes =", jsx.index("const ensureGrandMapCanvasToolbarNodes ="))
    ]

    assert "role: 'surface_state'" in helpers
    assert "kind: 'state'" in helpers
    assert "state_values: Object.assign({}, values || {})" in helpers
    assert "const surfaceStateShouldMaterializeParams = (options) =>" in helpers
    assert "options.materialize_param_nodes !== false" in helpers
    assert "if (surfaceStateShouldMaterializeParams(options)) {" in helpers
    assert "const resolvedOptions = Object.assign({" in helpers
    assert "materialize_param_nodes: true" in helpers
    assert "materialize_wire_anatomy: true" in helpers
    assert "wire_family: 'surface_state_field'" in helpers
    assert "materializeGrandMapParamNode(nodeId, 'surface_name', surfaceName);" in helpers
    assert "materializeGrandMapParamNode(nodeId, 'surface_' + grandMapSafeId(slotName), values[slotId]);" in helpers
    assert "setGrandMapInlineNodeField(root, stateKey, stateNodeId);" in helpers
    assert "root.config = Object.assign({}, root.config || {}, { [stateKey]: stateNodeId });" in helpers
    assert "materialize_root_state_param" not in helpers
    assert "window.ahSetUiNodeParam(rootId, stateKey, stateNodeId)" not in helpers
    assert "syncGrandMapOwnedSlotRelations(" in helpers
    assert "root.data = Object.assign({}, root.data || {}, {" in helpers
    assert "[stateKey]: stateNodeId" in helpers
    assert "relationGroupNodeIds" in helpers

    assert "syncGrandMapSurfaceStateSlots('canvas-composer-body', rootId, slotMap" in composer
    assert "state_key: 'canvas_composer_state_node_id'" in composer
    assert "prefix: 'canvas_composer'" in composer
    assert "'slot:canvas-composer-text'" in composer
    assert "'slot:canvas-composer-mode'" in composer
    assert "syncGrandMapSurfaceStateSlots('canvas-toolbar', rootId, slotMap" in toolbar
    assert "state_key: 'canvas_toolbar_state_node_id'" in toolbar
    assert "prefix: 'canvas_toolbar'" in toolbar
    assert "'slot:canvas-zoom-percent'" in toolbar
    assert "syncGrandMapSurfaceStateSlots('home-composer-actions', rootId, slotMap" in home_actions
    assert "state_key: 'home_composer_actions_state_node_id'" in home_actions
    assert "syncGrandMapSurfaceStateSlots('home-composer-body', rootId, slotMap" in home_body
    assert "state_key: 'home_composer_body_state_node_id'" in home_body
    assert "syncGrandMapSurfaceStateSlots('home-composer-actions', rootId, slotMap" in fallback_actions
    assert "syncGrandMapSurfaceStateSlots('home-composer-body', rootId, slotMap" in fallback_body
    assert "syncGrandMapSurfaceStateSlots('canvas-toolbar', rootId, slotMap" in fallback_canvas_toolbar
    assert "state_key: 'canvas_toolbar_state_node_id'" in fallback_canvas_toolbar
    assert "syncGrandMapSurfaceStateSlots('canvas-composer-body', rootId, slotMap" in fallback_canvas_composer
    assert "state_key: 'canvas_composer_state_node_id'" in fallback_canvas_composer


def test_grand_map_canvas_session_actions_emits_save_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-session-actions", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-session-actions"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:canvas-session-actions"]["data"]["children"] == [
        "ui:grandmap:canvas-action-fork",
        "ui:grandmap:canvas-action-save-skill",
        "ui:grandmap:canvas-action-save",
    ]
    assert nodes["ui:grandmap:canvas-action-fork"]["data"]["action"] == "canvas.session.fork"
    assert nodes["ui:grandmap:canvas-action-save-skill"]["data"]["action"] == "canvas.session.save-skill"
    assert nodes["ui:grandmap:canvas-action-save"]["data"]["action"] == "canvas.session.save"
    assert "ah-canvas-header-primary-node" in nodes["ui:grandmap:canvas-action-save"]["data"]["cls"]


def test_grand_map_canvas_model_picker_emits_bound_model_action(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-model-picker", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-model-picker"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-model-label"]["data"]["value"] == "Auto (router picks)"
    assert nodes["ui:grandmap:canvas-model-picker"]["data"]["action"] == "model.picker.open"
    assert nodes["ui:grandmap:canvas-model-picker"]["data"]["children"] == [
        "ui:grandmap:canvas-model-mark",
        "ui:grandmap:canvas-model-label",
    ]
    assert nodes["ui:grandmap:canvas-model-mark"]["data"]["text"] == "A"
    assert nodes["ui:grandmap:canvas-model-label"]["data"]["bind"] == "slot:canvas-model-label"


def test_grand_map_model_picker_modal_emits_searchable_picker_shell(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_command_palette", "Command Palette")],
            "wires": [],
        },
        {
            "key": "models",
            "title": "Models",
            "nodes": [
                _node("models_router", "Models Router"),
                _node("models_registry", "Models Registry"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("model-picker-modal", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:model-picker-modal"
    assert payload["source_node_ids"] == [
        "ui_command_palette",
        "models_router",
        "models_registry",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:model-picker-modal"]["data"]
    assert root["action"] == "model-picker.close"
    assert root["data_attrs"]["data-no-pan"] == "true"
    assert root["children"] == ["ui:grandmap:model-picker-panel"]
    panel = nodes["ui:grandmap:model-picker-panel"]["data"]
    assert panel["role"] == "dialog"
    assert panel["action"] == "model-picker.noop"
    assert nodes["slot:model-picker-query"]["data"]["value"] == ""
    assert nodes["slot:model-picker-has-results"]["data"]["value"] == "true"
    query = nodes["ui:grandmap:model-picker-search-input"]["data"]
    assert query["tag"] == "input"
    assert query["bind"] == "slot:model-picker-query"
    assert query["action"] == "model-picker.query.update"
    assert query["key_actions"]["Escape"]["action"] == "model-picker.close"
    assert query["key_actions"]["Escape"]["key"] == "escape"
    assert query["test_id"] == "model-picker-query"
    assert nodes["ui:grandmap:model-picker-empty"]["data"]["visible_when"] == {
        "bind": "slot:model-picker-has-results",
        "value": "false",
    }
    assert nodes["ui:grandmap:model-picker-groups"]["data"]["render_slot"] == (
        "slot:model-picker-groups"
    )


def test_grand_map_model_picker_group_emits_grouped_items_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_command_palette", "Command Palette")],
            "wires": [],
        },
        {
            "key": "models",
            "title": "Models",
            "nodes": [
                _node("models_router", "Models Router"),
                _node("models_registry", "Models Registry"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("model-picker-group", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:model-picker-group"
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:model-picker-group-name"]["data"]["value"] == "MODELS"
    assert nodes["ui:grandmap:model-picker-group"]["data"]["children"] == [
        "ui:grandmap:model-picker-group-name",
        "ui:grandmap:model-picker-group-items",
    ]
    assert nodes["ui:grandmap:model-picker-group-name"]["data"]["bind"] == (
        "slot:model-picker-group-name"
    )
    assert nodes["ui:grandmap:model-picker-group-items"]["data"]["render_slot"] == (
        "slot:model-picker-group-items"
    )


def test_grand_map_model_picker_row_emits_pickable_model_row(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_command_palette", "Command Palette")],
            "wires": [],
        },
        {
            "key": "models",
            "title": "Models",
            "nodes": [
                _node("models_router", "Models Router"),
                _node("models_registry", "Models Registry"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("model-picker-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:model-picker-row"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:model-picker-row"]["data"]
    assert root["tag"] == "button"
    assert root["action"] == "model-picker.pick"
    assert root["active_bind"] == "slot:model-picker-row-selected"
    assert root["children"] == [
        "ui:grandmap:model-picker-row-mark",
        "ui:grandmap:model-picker-row-copy",
        "ui:grandmap:model-picker-row-latency",
        "ui:grandmap:model-picker-row-tag",
    ]
    assert nodes["slot:model-picker-row-name"]["data"]["value"] == "Model"
    assert nodes["slot:model-picker-row-selected"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:model-picker-row-mark"]["data"]["bind"] == (
        "slot:model-picker-row-initial"
    )
    assert nodes["ui:grandmap:model-picker-row-name"]["data"]["bind"] == (
        "slot:model-picker-row-name"
    )
    assert nodes["ui:grandmap:model-picker-row-sub"]["data"]["bind"] == (
        "slot:model-picker-row-sub"
    )
    assert nodes["ui:grandmap:model-picker-row-latency"]["data"]["bind"] == (
        "slot:model-picker-row-latency"
    )
    assert nodes["ui:grandmap:model-picker-row-tag"]["data"]["bind"] == (
        "slot:model-picker-row-tag"
    )


def test_grand_map_canvas_router_status_emits_bound_router_chip(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-router-status", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-router-status"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-router-label"]["data"]["value"] == ""
    assert nodes["ui:grandmap:canvas-router-status"]["data"]["children"] == [
        "ui:grandmap:canvas-router-mark",
        "ui:grandmap:canvas-router-label",
    ]
    assert nodes["ui:grandmap:canvas-router-mark"]["data"]["text"] == "auto"
    assert nodes["ui:grandmap:canvas-router-label"]["data"]["bind"] == (
        "slot:canvas-router-label"
    )


def test_grand_map_canvas_brain_chip_emits_bound_action_chip(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-brain-chip", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-brain-chip"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-brain-label"]["data"]["value"] == "brain idle"
    assert nodes["slot:canvas-brain-state"]["data"]["value"] == "idle"
    assert nodes["ui:grandmap:canvas-brain-chip"]["data"]["bind"] == (
        "slot:canvas-brain-label"
    )
    assert nodes["ui:grandmap:canvas-brain-chip"]["data"]["state_bind"] == (
        "slot:canvas-brain-state"
    )
    assert nodes["ui:grandmap:canvas-brain-chip"]["data"]["action"] == (
        "brain.folders.open"
    )


def test_grand_map_canvas_account_chip_emits_bound_activate_chip(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_account_chip", "Account Chip")])

    payload = grand_map_ui_surface("canvas-account-chip", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-account-chip"
    assert payload["source_node_ids"] == ["ui_account_chip"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-account-label"]["data"]["value"] == "Sign in"
    assert nodes["slot:canvas-account-state"]["data"]["value"] == "signed-out"
    assert nodes["ui:grandmap:canvas-account-chip"]["data"]["action"] == (
        "account.chip.activate"
    )
    assert nodes["ui:grandmap:canvas-account-chip"]["data"]["state_bind"] == (
        "slot:canvas-account-state"
    )
    assert nodes["ui:grandmap:canvas-account-label"]["data"]["bind"] == (
        "slot:canvas-account-label"
    )
    assert nodes["ui:grandmap:canvas-account-caret"]["data"]["state_bind"] == (
        "slot:canvas-account-state"
    )


def test_grand_map_graph_health_badge_emits_validator_panel_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_wire_layer", "Wire Layer")],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_validator", "Nodes Validator")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("graph-health-badge", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:graph-health-badge"
    assert payload["source_node_ids"] == ["canvas_wire_layer", "nodes_validator"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:graph-health-badge"]["data"]
    assert root["data_attrs"]["data-no-pan"] == "true"
    assert root["data_attrs"]["data-testid"] == "graph-health-badge"
    assert root["children"] == [
        "ui:grandmap:graph-health-collapsed",
        "ui:grandmap:graph-health-panel",
    ]
    assert nodes["slot:graph-health-open"]["data"]["value"] == "false"
    assert nodes["slot:graph-health-state"]["data"]["value"] == "ok"
    assert nodes["slot:graph-health-summary"]["data"]["value"] == "ok"
    assert nodes["slot:graph-health-has-issues"]["data"]["value"] == "false"

    collapsed = nodes["ui:grandmap:graph-health-collapsed"]["data"]
    assert collapsed["tag"] == "button"
    assert collapsed["action"] == "graph-health.open"
    assert collapsed["state_bind"] == "slot:graph-health-state"
    assert collapsed["visible_when"] == {
        "bind": "slot:graph-health-open",
        "value": "false",
    }
    panel = nodes["ui:grandmap:graph-health-panel"]["data"]
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["data-testid"] == "graph-health-panel"
    assert panel["visible_when"] == {
        "bind": "slot:graph-health-open",
        "value": "true",
    }
    assert nodes["ui:grandmap:graph-health-self-heal"]["data"]["action"] == (
        "graph-health.self-heal"
    )
    assert nodes["ui:grandmap:graph-health-close"]["data"]["action"] == (
        "graph-health.close"
    )
    assert nodes["ui:grandmap:graph-health-empty"]["data"]["visible_when"] == {
        "bind": "slot:graph-health-has-issues",
        "value": "false",
    }
    assert nodes["ui:grandmap:graph-health-issue-list"]["data"]["render_slot"] == (
        "slot:graph-health-issues"
    )


def test_grand_map_graph_health_issue_row_emits_focusable_issue_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_validator", "Nodes Validator")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("graph-health-issue-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:graph-health-issue-row"
    assert payload["source_node_ids"] == ["nodes_validator"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:graph-health-issue-row"]["data"]
    assert root["action"] == "graph-health.issue.focus"
    assert root["state_bind"] == "slot:graph-health-issue-level"
    assert root["test_id"] == "graph-health-issue"
    assert root["children"] == [
        "ui:grandmap:graph-health-issue-head",
        "ui:grandmap:graph-health-issue-message",
    ]
    assert nodes["slot:graph-health-issue-level"]["data"]["value"] == "warn"
    assert nodes["slot:graph-health-issue-has-target"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:graph-health-issue-level"]["data"]["bind"] == (
        "slot:graph-health-issue-level"
    )
    assert nodes["ui:grandmap:graph-health-issue-code"]["data"]["bind"] == (
        "slot:graph-health-issue-code"
    )
    assert nodes["ui:grandmap:graph-health-issue-target"]["data"]["bind"] == (
        "slot:graph-health-issue-target"
    )
    assert nodes["ui:grandmap:graph-health-issue-target"]["data"]["visible_when"] == {
        "bind": "slot:graph-health-issue-has-target",
        "value": "true",
    }
    assert nodes["ui:grandmap:graph-health-issue-message"]["data"]["bind"] == (
        "slot:graph-health-issue-message"
    )


def test_grand_map_health_strip_item_emits_footer_popover_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_wire_layer", "Wire Layer")],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_validator", "Nodes Validator")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("health-strip-item", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:health-strip-item"
    assert payload["source_node_ids"] == ["canvas_wire_layer", "nodes_validator"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:health-strip-item"]["data"]
    assert root["data_attrs"]["data-no-pan"] == "true"
    assert root["children"] == [
        "ui:grandmap:health-strip-button",
        "ui:grandmap:health-strip-overlay",
    ]
    assert nodes["slot:health-strip-open"]["data"]["value"] == "false"
    assert nodes["slot:health-strip-hidden"]["data"]["value"] == "false"
    assert nodes["slot:health-strip-state"]["data"]["value"] == "ok"
    assert nodes["slot:health-strip-label"]["data"]["value"] == "healthy"
    assert nodes["slot:health-strip-has-issues"]["data"]["value"] == "false"

    button = nodes["ui:grandmap:health-strip-button"]["data"]
    assert button["tag"] == "button"
    assert button["bind"] == "slot:health-strip-label"
    assert button["action"] == "health-strip.toggle"
    assert button["state_bind"] == "slot:health-strip-state"
    assert button["test_id"] == "health-strip-item"
    assert button["visible_when"] == {
        "bind": "slot:health-strip-hidden",
        "value": "false",
    }

    overlay = nodes["ui:grandmap:health-strip-overlay"]["data"]
    assert overlay["action"] == "health-strip.close"
    assert overlay["visible_when"] == {
        "bind": "slot:health-strip-open",
        "value": "true",
    }
    panel = nodes["ui:grandmap:health-strip-panel"]["data"]
    assert panel["role"] == "dialog"
    assert panel["action"] == "health-strip.noop"
    assert nodes["ui:grandmap:health-strip-self-heal"]["data"]["action"] == (
        "health-strip.self-heal"
    )
    assert nodes["ui:grandmap:health-strip-self-heal"]["data"]["test_id"] == (
        "health-strip-self-heal"
    )
    assert nodes["ui:grandmap:health-strip-close"]["data"]["action"] == (
        "health-strip.close"
    )
    assert nodes["ui:grandmap:health-strip-empty"]["data"]["bind"] == (
        "slot:health-strip-empty"
    )
    assert nodes["ui:grandmap:health-strip-empty"]["data"]["visible_when"] == {
        "bind": "slot:health-strip-has-issues",
        "value": "false",
    }
    assert nodes["ui:grandmap:health-strip-issue-list"]["data"]["render_slot"] == (
        "slot:health-strip-issues"
    )


def test_grand_map_canvas_account_menu_emits_menu_actions(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_account_chip", "Account Chip")])

    payload = grand_map_ui_surface("canvas-account-menu", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-account-menu"
    assert payload["source_node_ids"] == ["ui_account_chip"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-account-email"]["data"]["value"] == ""
    assert nodes["ui:grandmap:canvas-account-menu"]["data"]["children"] == [
        "ui:grandmap:canvas-account-menu-email",
        "ui:grandmap:canvas-account-menu-account",
        "ui:grandmap:canvas-account-menu-dashboard",
        "ui:grandmap:canvas-account-menu-signout",
    ]
    assert nodes["ui:grandmap:canvas-account-menu-email"]["data"]["bind"] == (
        "slot:canvas-account-email"
    )
    assert nodes["ui:grandmap:canvas-account-menu-account"]["data"]["action"] == (
        "account.menu.account"
    )
    assert nodes["ui:grandmap:canvas-account-menu-dashboard"]["data"]["action"] == (
        "account.menu.dashboard"
    )
    assert nodes["ui:grandmap:canvas-account-menu-signout"]["data"]["action"] == (
        "account.menu.signout"
    )


def test_grand_map_account_identity_footer_emits_live_identity_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_account_chip", "Account Chip")])

    payload = grand_map_ui_surface("account-identity-footer", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:account-identity"
    assert payload["source_node_ids"] == ["ui_account_chip"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:account-identity-label"]["data"]["value"] == "Sign in"
    assert nodes["slot:account-identity-sub"]["data"]["value"] == "ArchHub Cloud"
    assert nodes["slot:account-identity-initial"]["data"]["value"] == ">"
    assert nodes["slot:account-identity-state"]["data"]["value"] == "signed-out"
    root = nodes["ui:grandmap:account-identity"]["data"]
    assert root["action"] == "account.identity.signin"
    assert root["state_bind"] == "slot:account-identity-state"
    assert root["test_id"] == "account-identity"
    assert root["children"] == [
        "ui:grandmap:account-identity-avatar",
        "ui:grandmap:account-identity-copy",
    ]
    assert nodes["ui:grandmap:account-identity-avatar"]["data"]["bind"] == (
        "slot:account-identity-initial"
    )
    assert nodes["ui:grandmap:account-identity-name"]["data"]["bind"] == (
        "slot:account-identity-label"
    )
    assert nodes["ui:grandmap:account-identity-tag"]["data"]["bind"] == (
        "slot:account-identity-sub"
    )


def test_grand_map_canvas_home_actions_emit_wordmark_and_home_action(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_sidebar_rail", "Sidebar Rail"),
        _node("ui_design_tokens", "Design Tokens"),
    ])

    payload = grand_map_ui_surface("canvas-home-actions", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-home-actions"
    assert payload["source_node_ids"] == ["ui_sidebar_rail", "ui_design_tokens"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:canvas-home-actions"]["data"]["children"] == [
        "ui:grandmap:canvas-home-grid",
        "ui:grandmap:canvas-home-wordmark",
        "ui:grandmap:canvas-home-divider",
    ]
    assert nodes["ui:grandmap:canvas-home-grid"]["data"]["action"] == "rail.home.open"
    assert nodes["ui:grandmap:canvas-home-wordmark"]["data"]["action"] == "rail.home.open"
    assert nodes["ui:grandmap:canvas-home-wordmark-arch"]["data"]["text"] == "Arch"
    assert nodes["ui:grandmap:canvas-home-wordmark-hub"]["data"]["text"] == "Hub"
    assert nodes["ui:grandmap:canvas-home-wordmark"]["data"]["source_map_node"] == (
        "ui_design_tokens"
    )


def test_grand_map_canvas_new_session_action_uses_session_domain_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [_node("sessions_open_session", "Open Session")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-new-session-action", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-new-session-action"
    assert payload["source_node_ids"] == ["sessions_open_session"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    node = nodes["ui:grandmap:canvas-new-session-action"]
    assert node["data"]["text"] == "+"
    assert node["data"]["action"] == "session.create"
    assert node["data"]["args"] == {"title": "untitled"}
    assert node["data"]["source_map_node"] == "sessions_open_session"


def test_grand_map_canvas_session_tab_emits_activate_close_and_state(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "sessions",
            "title": "Sessions",
            "nodes": [
                _node("sessions_threads_rail", "Threads Rail"),
                _node("sessions_open_session", "Open Session"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("canvas-session-tab", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-session-tab"
    assert payload["source_node_ids"] == ["sessions_threads_rail", "sessions_open_session"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-tab-title"]["data"]["value"] == "untitled"
    assert nodes["slot:canvas-tab-state"]["data"]["value"] == "idle"
    assert nodes["slot:canvas-tab-active"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:canvas-session-tab"]["data"]["action"] == (
        "sessions.tab.activate"
    )
    assert nodes["ui:grandmap:canvas-session-tab"]["data"]["active_bind"] == (
        "slot:canvas-tab-active"
    )
    assert nodes["ui:grandmap:canvas-session-tab-state"]["data"]["state_bind"] == (
        "slot:canvas-tab-state"
    )
    assert nodes["ui:grandmap:canvas-session-tab-title"]["data"]["bind"] == (
        "slot:canvas-tab-title"
    )
    assert nodes["ui:grandmap:canvas-session-tab-close"]["data"]["action"] == (
        "sessions.tab.close"
    )

    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapCanvasSessionTabTemplate ="):
        jsx.index("const ensureGrandMapCanvasSessionTabNodes =", jsx.index("const cloneGrandMapCanvasSessionTabTemplate ="))
    ]
    assert "const mappedSlotMap = putGrandMapMappedSlotMap(" in clone
    assert "syncGrandMapMappedSurfaceState('canvas-session-tab', sid, rootId, mappedSlotMap" in clone
    assert "state_key: 'canvas_session_tab_state_node_id'" in clone


def test_grand_map_canvas_context_menu_emits_menu_actions(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-context-menu", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-context-menu"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:canvas-snap-to-grid"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:canvas-menu-add-node"]["data"]["action"] == "canvas.menu.add-node"
    assert nodes["ui:grandmap:canvas-menu-paste"]["data"]["action"] == "canvas.menu.paste"
    assert nodes["ui:grandmap:canvas-menu-fit"]["data"]["action"] == "canvas.menu.fit"
    assert nodes["ui:grandmap:canvas-menu-zoom-100"]["data"]["action"] == "canvas.menu.zoom-100"
    assert nodes["ui:grandmap:canvas-menu-snap"]["data"]["action"] == "canvas.menu.snap.toggle"
    assert nodes["ui:grandmap:canvas-menu-snap"]["data"]["active_bind"] == "slot:canvas-snap-to-grid"
    assert nodes["ui:grandmap:canvas-menu-clear"]["data"]["action"] == "canvas.menu.clear"
    assert "ah-canvas-context-menu-danger-node" in nodes["ui:grandmap:canvas-menu-clear"]["data"]["cls"]


def test_grand_map_wire_context_menu_emits_stateful_wire_actions(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("wire-context-menu", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:wire-context-menu"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:wire-target-frozen"]["data"]["value"] == "false"
    assert nodes["slot:wire-target-bypassed"]["data"]["value"] == "false"
    assert nodes["slot:wire-gate-blocked"]["data"]["value"] == "false"
    assert nodes["slot:wire-codec-base64"]["data"]["value"] == "false"
    assert nodes["slot:wire-presentation-hidden"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:wire-menu-pick-source"]["data"]["action"] == "wire.menu.pick-source"
    assert nodes["ui:grandmap:wire-menu-pick-dest"]["data"]["action"] == "wire.menu.pick-dest"
    assert nodes["ui:grandmap:wire-menu-swap-target"]["data"]["action"] == "wire.menu.swap-target"
    assert nodes["ui:grandmap:wire-menu-toggle-gate"]["data"]["action"] == "wire.menu.toggle-gate"
    assert nodes["ui:grandmap:wire-menu-toggle-gate"]["data"]["active_bind"] == "slot:wire-gate-blocked"
    assert nodes["ui:grandmap:wire-menu-toggle-gate"]["data"]["text_cases"] == {
        "bind": "slot:wire-gate-blocked",
        "values": {"true": "Open wire gate", "false": "Block wire gate"},
        "default": "Block wire gate",
    }
    assert nodes["ui:grandmap:wire-menu-toggle-codec"]["data"]["action"] == "wire.menu.toggle-codec"
    assert nodes["ui:grandmap:wire-menu-toggle-codec"]["data"]["active_bind"] == "slot:wire-codec-base64"
    assert nodes["ui:grandmap:wire-menu-toggle-codec"]["data"]["text_cases"] == {
        "bind": "slot:wire-codec-base64",
        "values": {"true": "Decode to plain text", "false": "Encode as base64"},
        "default": "Encode as base64",
    }
    assert nodes["ui:grandmap:wire-menu-toggle-presentation"]["data"]["action"] == "wire.menu.toggle-presentation"
    assert nodes["ui:grandmap:wire-menu-toggle-presentation"]["data"]["active_bind"] == "slot:wire-presentation-hidden"
    assert nodes["ui:grandmap:wire-menu-toggle-presentation"]["data"]["text_cases"] == {
        "bind": "slot:wire-presentation-hidden",
        "values": {"true": "Show wire", "false": "Hide wire"},
        "default": "Hide wire",
    }
    assert nodes["ui:grandmap:wire-menu-freeze-target"]["data"]["text_cases"] == {
        "bind": "slot:wire-target-frozen",
        "values": {"true": "Unfreeze target", "false": "Freeze target"},
        "default": "Freeze target",
    }
    assert nodes["ui:grandmap:wire-menu-bypass-target"]["data"]["text_cases"] == {
        "bind": "slot:wire-target-bypassed",
        "values": {"true": "Un-bypass target", "false": "Bypass target"},
        "default": "Bypass target",
    }
    assert nodes["ui:grandmap:wire-menu-disconnect"]["data"]["action"] == "wire.menu.disconnect"


def test_grand_map_node_context_menu_emits_base_actions(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-context-menu", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-context-menu"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:node-menu-is-subgraph"]["data"]["value"] == "false"
    assert nodes["slot:node-menu-shared-skill"]["data"]["value"] == "false"
    assert nodes["slot:node-menu-flattenable"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:node-menu-run"]["data"]["action"] == "node.menu.run"
    assert nodes["ui:grandmap:node-menu-freeze"]["data"]["action"] == "node.menu.freeze"
    assert nodes["ui:grandmap:node-menu-bypass"]["data"]["action"] == "node.menu.bypass"
    assert nodes["ui:grandmap:node-menu-flatten"]["data"]["hidden_bind"] == "slot:node-menu-flattenable"
    assert nodes["ui:grandmap:node-menu-expand"]["data"]["hidden_bind"] == "slot:node-menu-is-subgraph"
    assert nodes["ui:grandmap:node-menu-disentangle"]["data"]["hidden_bind"] == "slot:node-menu-shared-skill"
    assert nodes["ui:grandmap:node-menu-delete"]["data"]["action"] == "node.menu.delete"
    assert "ah-node-context-menu-danger-node" in nodes["ui:grandmap:node-menu-delete"]["data"]["cls"]


def test_canvas_behavior_menu_toggles_materialize_behavior_parameter_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_canvas = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas = React.memo", jsx.index("const NodeCanvasInner ="))
    ]
    node_menu = node_canvas[
        node_canvas.index("onFreeze={() => {"):
        node_canvas.index("onRename={() => {", node_canvas.index("onFreeze={() => {"))
    ]
    node_rename = node_canvas[
        node_canvas.index("onRename={() => {"):
        node_canvas.index("onDuplicate={() => {", node_canvas.index("onRename={() => {"))
    ]
    wire_menu = node_canvas[
        node_canvas.index("onFreezeTarget={async () => {"):
        node_canvas.index("{wireFieldPicker && (", node_canvas.index("onFreezeTarget={async () => {"))
    ]
    disable_verbs = jsx[
        jsx.index("const onVerbKey = (e) => {"):
        jsx.index("document.addEventListener('keydown', onVerbKey", jsx.index("const onVerbKey = (e) => {"))
    ]

    assert "node.config = { ...(node.config || {}), frozen: node.frozen };" not in node_menu
    assert "const next = !(node.frozen || (node.config && node.config.frozen));" in node_menu
    assert "applyGrandMapNodeParamEdit(node, next" in node_menu
    assert "operation: 'node.menu.freeze'" in node_menu
    assert "const next = !(node.bypass || node.bypassed" in node_menu
    assert "operation: 'node.menu.bypass'" in node_menu
    assert "window.ahSetUiNodeParam(node.id, 'frozen', node.frozen);" not in node_menu
    assert "window.ahSetUiNodeParam(node.id, 'bypass', node.bypass);" not in node_menu
    assert "applyGrandMapNodeParamEdit(dst, next" in wire_menu
    assert "operation: 'wire.menu.freeze-target'" in wire_menu
    assert "operation: 'wire.menu.bypass-target'" in wire_menu
    assert "window.ahSetUiNodeParam(dstId, 'frozen', next);" not in wire_menu
    assert "window.ahSetUiNodeParam(dstId, 'bypass', next);" not in wire_menu
    assert "applyGrandMapNodeParamEdit(node, { bypass: next }" in disable_verbs
    assert "operation: 'node.bypass'" in disable_verbs
    assert "applyGrandMapNodeParamEdit(node, { frozen: next }" in disable_verbs
    assert "operation: 'node.freeze'" in disable_verbs
    assert "applyGrandMapNodeParamEdit(node, { preview_off: next }" in disable_verbs
    assert "operation: 'node.preview.toggle'" in disable_verbs
    assert "operation: 'node.pin.clear'" in disable_verbs
    assert "operation: 'node.pin.set'" in disable_verbs
    assert "window.ahSetUiNodeParam(node.id, 'pinned', false);" not in disable_verbs
    assert "window.ahSetUiNodeParam(node.id, 'pinned', true);" not in disable_verbs
    assert "applyGrandMapNodeParamEdit(node, { title: next }" in node_rename
    assert "operation: 'node.menu.rename'" in node_rename
    assert "if (window.ahSetUiNodeParam) window.ahSetUiNodeParam(node.id, 'title', next);" not in node_rename
    assert "if (next != null) { node.title = next;" not in node_rename


def test_grand_map_canvas_gesture_hint_emits_hint_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("canvas-gesture-hint", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:canvas-gesture-hint"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:canvas-hint-scroll"]["data"]["text"] == "scroll -> zoom"
    assert nodes["ui:grandmap:canvas-hint-drag"]["data"]["text"] == "drag -> pan"
    assert nodes["ui:grandmap:canvas-hint-menu"]["data"]["text"] == "right-click -> menu"


def test_grand_map_node_palette_header_emits_title_and_hint_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [
        _node("ui_sidebar_rail", "Sidebar Rail"),
        _node("ui_command_palette", "Command Palette"),
    ])

    payload = grand_map_ui_surface("node-palette-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-header"
    assert payload["source_node_ids"] == ["ui_sidebar_rail", "ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-palette-title"]["data"]["text"] == "Nodes"
    assert nodes["ui:grandmap:node-palette-hint"]["data"]["text"] == "drag - right-click"
    assert nodes["ui:grandmap:node-palette-header"]["data"]["children"] == [
        "ui:grandmap:node-palette-title",
        "ui:grandmap:node-palette-hint",
        "ui:grandmap:node-palette-header-spacer",
    ]


def test_grand_map_node_palette_search_emits_search_and_sort_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-palette-search", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-search"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:nodes-palette-search"]["data"]["value"] == ""
    assert nodes["slot:nodes-palette-sort"]["data"]["value"] == "default"
    assert nodes["ui:grandmap:node-palette-search-input"]["data"]["tag"] == "input"
    assert nodes["ui:grandmap:node-palette-search-input"]["data"]["action"] == (
        "nodes.palette.search.update"
    )
    assert nodes["ui:grandmap:node-palette-search-input"]["data"]["placeholder"] == (
        "Search nodes..."
    )
    assert nodes["ui:grandmap:node-palette-sort"]["data"]["action"] == (
        "nodes.palette.sort.toggle"
    )
    assert nodes["ui:grandmap:node-palette-sort"]["data"]["active_bind"] == (
        "slot:nodes-palette-sort"
    )


def test_grand_map_node_palette_shell_emits_panel_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_sidebar_rail", "Sidebar Rail"),
                _node("ui_command_palette", "Command Palette"),
            ],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Skill Library")],
            "wires": [],
        },
        {
            "key": "connectors",
            "title": "Connectors",
            "nodes": [_node("connectors_panel", "Connector Panel")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-palette-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-shell"
    assert payload["source_node_ids"] == [
        "ui_sidebar_rail",
        "ui_command_palette",
        "nodes_library_search",
        "brain_skills",
        "connectors_panel",
    ]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-palette-shell"]["data"]["cls"] == (
        "ah-node-palette-shell-node"
    )
    assert nodes["ui:grandmap:node-palette-shell"]["data"]["children"] == [
        "ui:grandmap:node-palette-shell-styles",
        "ui:grandmap:node-palette-shell-header",
        "ui:grandmap:node-palette-shell-menu",
        "ui:grandmap:node-palette-shell-search",
        "ui:grandmap:node-palette-shell-list",
        "ui:grandmap:node-palette-shell-footer",
    ]
    assert nodes["ui:grandmap:node-palette-shell-styles"]["data"]["render_slot"] == (
        "slot:node-palette-shell-styles"
    )
    assert nodes["ui:grandmap:node-palette-shell-header"]["data"]["render_slot"] == (
        "slot:node-palette-shell-header"
    )
    assert nodes["ui:grandmap:node-palette-shell-menu"]["data"]["render_slot"] == (
        "slot:node-palette-shell-menu"
    )
    assert nodes["ui:grandmap:node-palette-shell-search"]["data"]["render_slot"] == (
        "slot:node-palette-shell-search"
    )
    assert nodes["ui:grandmap:node-palette-shell-list"]["data"]["render_slot"] == (
        "slot:node-palette-shell-list"
    )
    assert nodes["ui:grandmap:node-palette-shell-footer"]["data"]["render_slot"] == (
        "slot:node-palette-shell-footer"
    )


def test_grand_map_node_palette_list_emits_content_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-palette-list", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-list"
    assert payload["source_node_ids"] == ["nodes_library_search"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-palette-list"]["data"]["cls"] == (
        "ah-node-palette-list-node ah-scroll"
    )
    assert nodes["ui:grandmap:node-palette-list"]["data"]["render_slot"] == (
        "slot:node-palette-list-content"
    )


def test_grand_map_node_palette_group_emits_openable_group_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-palette-group", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-group"
    assert payload["source_node_ids"] == ["nodes_library_search"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:nodes-palette-group-title"]["data"]["value"] == "GROUP"
    assert nodes["slot:nodes-palette-group-count"]["data"]["value"] == "0"
    assert nodes["slot:nodes-palette-group-kind"]["data"]["value"] == "group"
    assert nodes["slot:nodes-palette-group-open"]["data"]["value"] == "true"
    root = nodes["ui:grandmap:node-palette-group"]["data"]
    assert root["state_bind"] == "slot:nodes-palette-group-kind"
    assert root["children"] == [
        "ui:grandmap:node-palette-group-header",
        "ui:grandmap:node-palette-group-body",
    ]
    assert nodes["ui:grandmap:node-palette-group-header"]["data"]["render_slot"] == (
        "slot:nodes-palette-group-header"
    )
    body = nodes["ui:grandmap:node-palette-group-body"]["data"]
    assert body["render_slot"] == "slot:nodes-palette-group-content"
    assert body["hidden_bind"] == "slot:nodes-palette-group-open"
    assert body["hidden_value"] == "false"
    assert any(
        wire["from"]["node"] == "ui:grandmap:node-palette-group"
        and wire["to"]["node"] == "ui:grandmap:node-palette-group-body"
        for wire in payload["wires"]
    )


def test_grand_map_node_palette_context_menu_emits_content_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-palette-context-menu", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-context-menu"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-palette-context-menu"]["data"]["cls"] == (
        "ah-node-palette-context-menu-node"
    )
    assert nodes["ui:grandmap:node-palette-context-menu"]["data"]["render_slot"] == (
        "slot:node-palette-context-menu-content"
    )


def test_grand_map_wire_promote_palette_emits_add_node_overlay_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_command_palette", "Command Palette")],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("wire-promote-palette", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:wire-promote-palette"
    assert payload["source_node_ids"] == ["ui_command_palette", "nodes_library_search"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:wire-promote-palette"]["data"]
    assert root["action"] == "wire-promote.close"
    assert root["children"] == ["ui:grandmap:wire-promote-panel"]
    panel = nodes["ui:grandmap:wire-promote-panel"]["data"]
    assert panel["action"] == "wire-promote.noop"
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["data-no-pan"] == "true"
    assert nodes["slot:wire-promote-title"]["data"]["value"] == "ADD NODE"
    assert nodes["slot:wire-promote-query"]["data"]["value"] == ""
    assert nodes["slot:wire-promote-has-results"]["data"]["value"] == "false"
    query = nodes["ui:grandmap:wire-promote-query-input"]["data"]
    assert query["tag"] == "input"
    assert query["bind"] == "slot:wire-promote-query"
    assert query["action"] == "wire-promote.query.update"
    assert query["submit_action"] == "wire-promote.submit"
    assert query["test_id"] == "wire-promote-query"
    assert nodes["ui:grandmap:wire-promote-empty"]["data"]["hidden_bind"] == (
        "slot:wire-promote-has-results"
    )
    assert nodes["ui:grandmap:wire-promote-result-slot"]["data"]["render_slot"] == (
        "slot:wire-promote-results"
    )


def test_grand_map_wire_promote_result_row_emits_pickable_param_row(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [_node("nodes_library_search", "Library Search")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("wire-promote-result-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:wire-promote-result-row"
    assert payload["source_node_ids"] == ["nodes_library_search"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:wire-promote-result-row"]["data"]
    assert root["tag"] == "button"
    assert root["action"] == "wire-promote.result.pick"
    assert root["active_bind"] == "slot:wire-promote-result-active"
    assert root["children"] == [
        "ui:grandmap:wire-promote-result-dot",
        "ui:grandmap:wire-promote-result-copy",
        "ui:grandmap:wire-promote-result-cat",
    ]
    assert nodes["slot:wire-promote-result-title"]["data"]["value"] == "Node"
    assert nodes["slot:wire-promote-result-active"]["data"]["value"] == "false"
    assert nodes["ui:grandmap:wire-promote-result-dot"]["data"]["state_bind"] == (
        "slot:wire-promote-result-cat"
    )
    assert nodes["ui:grandmap:wire-promote-result-title"]["data"]["bind"] == (
        "slot:wire-promote-result-title"
    )
    assert nodes["ui:grandmap:wire-promote-result-sub"]["data"]["bind"] == (
        "slot:wire-promote-result-sub"
    )
    assert nodes["ui:grandmap:wire-promote-result-cat"]["data"]["bind"] == (
        "slot:wire-promote-result-cat"
    )


def test_grand_map_broken_wire_dialog_emits_recovery_modal_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_modal_system", "Modal System")],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_wire_layer", "Wire Layer")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("broken-wire-dialog", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:broken-wire-dialog"
    assert payload["source_node_ids"] == ["ui_modal_system", "canvas_wire_layer"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:broken-wire-dialog"]["data"]
    assert root["action"] == "broken-wire.close"
    assert root["data_attrs"]["data-no-pan"] == "true"
    assert root["data_attrs"]["data-testid"] == "broken-wire-dialog-backdrop"
    assert root["children"] == ["ui:grandmap:broken-wire-panel"]

    panel = nodes["ui:grandmap:broken-wire-panel"]["data"]
    assert panel["action"] == "broken-wire.noop"
    assert panel["role"] == "dialog"
    assert panel["data_attrs"]["aria-modal"] == "true"
    assert panel["data_attrs"]["data-testid"] == "broken-wire-dialog"
    assert nodes["slot:broken-wire-node-title"]["data"]["value"] == ""
    assert nodes["slot:broken-wire-count-label"]["data"]["value"] == "breaks 0 wires"
    assert nodes["slot:broken-wire-adapter-label"]["data"]["value"] == (
        "library.suggest_swaps - auto-bridge first broken pair"
    )
    assert nodes["ui:grandmap:broken-wire-list"]["data"]["render_slot"] == (
        "slot:broken-wire-rows"
    )
    assert nodes["ui:grandmap:broken-wire-insert-adapter"]["data"]["action"] == (
        "broken-wire.insert-adapter"
    )
    assert nodes["ui:grandmap:broken-wire-cancel"]["data"]["action"] == (
        "broken-wire.cancel"
    )
    assert nodes["ui:grandmap:broken-wire-delete"]["data"]["action"] == (
        "broken-wire.delete-anyway"
    )


def test_grand_map_broken_wire_row_emits_parametric_endpoint_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [_node("canvas_wire_layer", "Wire Layer")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("broken-wire-row", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:broken-wire-row"
    assert payload["source_node_ids"] == ["canvas_wire_layer"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:broken-wire-row"]["data"]
    assert root["children"] == [
        "ui:grandmap:broken-wire-row-src",
        "ui:grandmap:broken-wire-row-src-type",
        "ui:grandmap:broken-wire-row-arrow",
        "ui:grandmap:broken-wire-row-dst",
        "ui:grandmap:broken-wire-row-dst-type",
    ]
    assert nodes["slot:broken-wire-row-src"]["data"]["value"] == ""
    assert nodes["slot:broken-wire-row-src-type"]["data"]["value"] == ""
    assert nodes["slot:broken-wire-row-dst"]["data"]["value"] == ""
    assert nodes["slot:broken-wire-row-dst-type"]["data"]["value"] == ""
    assert nodes["ui:grandmap:broken-wire-row-src"]["data"]["bind"] == (
        "slot:broken-wire-row-src"
    )
    assert nodes["ui:grandmap:broken-wire-row-src-type"]["data"]["bind"] == (
        "slot:broken-wire-row-src-type"
    )
    assert nodes["ui:grandmap:broken-wire-row-arrow"]["data"]["text"] == "->"
    assert nodes["ui:grandmap:broken-wire-row-dst"]["data"]["bind"] == (
        "slot:broken-wire-row-dst"
    )
    assert nodes["ui:grandmap:broken-wire-row-dst-type"]["data"]["bind"] == (
        "slot:broken-wire-row-dst-type"
    )


def test_grand_map_node_palette_item_emits_draggable_double_action_row(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-palette-item", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-item"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:nodes-palette-item-title"]["data"]["value"] == "Node"
    assert nodes["slot:nodes-palette-item-sub"]["data"]["value"] == ""
    assert nodes["slot:nodes-palette-item-effect"]["data"]["value"] == ""
    assert nodes["slot:nodes-palette-item-pinned"]["data"]["value"] == "false"
    root = nodes["ui:grandmap:node-palette-item"]["data"]
    assert root["double_action"] == "nodes.palette.item.add"
    assert root["draggable"] is True
    assert root["drag_payload"] == {}
    assert root["children"] == [
        "ui:grandmap:node-palette-item-dot",
        "ui:grandmap:node-palette-item-copy",
        "ui:grandmap:node-palette-item-effect",
        "ui:grandmap:node-palette-item-pin",
        "ui:grandmap:node-palette-item-add",
    ]
    assert nodes["ui:grandmap:node-palette-item-title"]["data"]["bind"] == (
        "slot:nodes-palette-item-title"
    )
    assert nodes["ui:grandmap:node-palette-item-sub"]["data"]["bind"] == (
        "slot:nodes-palette-item-sub"
    )
    assert nodes["ui:grandmap:node-palette-item-effect"]["data"]["state_bind"] == (
        "slot:nodes-palette-item-effect"
    )
    assert nodes["ui:grandmap:node-palette-item-pin"]["data"]["action"] == (
        "nodes.palette.item.pin.toggle"
    )
    assert nodes["ui:grandmap:node-palette-item-pin"]["data"]["active_bind"] == (
        "slot:nodes-palette-item-pinned"
    )


def test_grand_map_node_palette_section_header_emits_toggleable_header(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-palette-section-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-section-header"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:nodes-palette-section-title"]["data"]["value"] == "SECTION"
    assert nodes["slot:nodes-palette-section-count"]["data"]["value"] == "0"
    assert nodes["slot:nodes-palette-section-open"]["data"]["value"] == "false"
    assert nodes["slot:nodes-palette-section-toggleable"]["data"]["value"] == "false"
    root = nodes["ui:grandmap:node-palette-section-header"]["data"]
    assert root["action"] == "nodes.palette.section.toggle"
    assert root["state_bind"] == "slot:nodes-palette-section-kind"
    assert root["children"] == [
        "ui:grandmap:node-palette-section-chevron",
        "ui:grandmap:node-palette-section-title",
        "ui:grandmap:node-palette-section-count",
    ]
    assert nodes["ui:grandmap:node-palette-section-chevron"]["data"]["text_cases"] == {
        "bind": "slot:nodes-palette-section-open",
        "values": {"true": "v", "false": ">"},
        "default": ">",
    }
    assert nodes["ui:grandmap:node-palette-section-chevron"]["data"]["hidden_bind"] == (
        "slot:nodes-palette-section-toggleable"
    )
    assert nodes["ui:grandmap:node-palette-section-title"]["data"]["bind"] == (
        "slot:nodes-palette-section-title"
    )


def test_grand_map_node_palette_menu_item_emits_action_header_separator_rows(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-palette-menu-item", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-menu-item"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:nodes-palette-menu-label"]["data"]["value"] == ""
    assert nodes["slot:nodes-palette-menu-kind"]["data"]["value"] == "action"
    assert nodes["slot:nodes-palette-menu-danger"]["data"]["value"] == "false"
    root = nodes["ui:grandmap:node-palette-menu-item"]["data"]
    assert root["children"] == [
        "ui:grandmap:node-palette-menu-separator",
        "ui:grandmap:node-palette-menu-header",
        "ui:grandmap:node-palette-menu-button",
    ]
    assert root["state_bind"] == "slot:nodes-palette-menu-kind"
    assert nodes["ui:grandmap:node-palette-menu-header"]["data"]["bind"] == (
        "slot:nodes-palette-menu-label"
    )
    assert nodes["ui:grandmap:node-palette-menu-button"]["data"]["action"] == (
        "nodes.palette.menu.item.run"
    )
    assert nodes["ui:grandmap:node-palette-menu-button"]["data"]["active_bind"] == (
        "slot:nodes-palette-menu-danger"
    )


def test_grand_map_node_palette_skill_sidecar_emits_badge_and_promote_action(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_command_palette", "Command Palette")])

    payload = grand_map_ui_surface("node-palette-skill-sidecar", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-palette-skill-sidecar"
    assert payload["source_node_ids"] == ["ui_command_palette"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:nodes-palette-skill-badge"]["data"]["value"] == "P"
    assert nodes["slot:nodes-palette-skill-shared"]["data"]["value"] == "false"
    assert nodes["slot:nodes-palette-skill-promotable"]["data"]["value"] == "true"
    root = nodes["ui:grandmap:node-palette-skill-sidecar"]["data"]
    assert root["children"] == [
        "ui:grandmap:node-palette-skill-badge",
        "ui:grandmap:node-palette-skill-promote",
    ]
    assert nodes["ui:grandmap:node-palette-skill-badge"]["data"]["bind"] == (
        "slot:nodes-palette-skill-badge"
    )
    assert nodes["ui:grandmap:node-palette-skill-badge"]["data"]["active_bind"] == (
        "slot:nodes-palette-skill-shared"
    )
    assert nodes["ui:grandmap:node-palette-skill-promote"]["data"]["action"] == (
        "nodes.palette.skill.promote"
    )
    assert nodes["ui:grandmap:node-palette-skill-promote"]["data"]["hidden_bind"] == (
        "slot:nodes-palette-skill-promotable"
    )


def test_default_workspace_grand_map_can_drive_home_surface_when_present():
    path = default_grand_map_path()
    if not path.exists():
        pytest.skip(f"workspace Grand Map not present at {path}")

    payload = grand_map_ui_surface("home-top")

    assert payload["ok"] is True
    assert payload["source"] == str(path)
    assert any(
        node["id"] == "ui_design_tokens"
        and node["data"]["source_map_node"] == "ui_design_tokens"
        for node in payload["nodes"]
    )


def test_node_properties_panel_surface_is_a_node_with_param_row_template(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
                _node("ui_modal_system", "Modal / Panel System"),
            ],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [
                _node("canvas_inline_param_edit", "Inline Param Edit"),
            ],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [
                _node("nodes_param_promote", "Param to Socket Promote"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-properties-panel", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-properties-panel"
    assert payload["source_node_ids"] == [
        "ui_node_card",
        "ui_modal_system",
        "canvas_inline_param_edit",
        "nodes_param_promote",
    ]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-properties-panel"]
    assert root["type"] == "ui.element"
    assert root["data"]["cls"] == "ah-node-properties-panel-node"
    assert root["data"]["children"] == [
        "ui:grandmap:node-properties-heading",
        "ui:grandmap:node-properties-help",
        "ui:grandmap:node-properties-list",
    ]
    assert nodes["ui:grandmap:node-properties-title"]["data"]["bind"] == "slot:node-title"
    assert nodes["ui:grandmap:node-properties-subtitle"]["data"]["bind"] == "slot:node-subtitle"
    assert nodes["ui:grandmap:node-properties-count"]["data"]["bind"] == "slot:node-param-count"
    assert nodes["ui:grandmap:node-property-param-row"]["data"]["children"] == [
        "ui:grandmap:node-property-param-promote",
        "ui:grandmap:node-property-param-body",
    ]
    assert nodes["ui:grandmap:node-property-param-label"]["data"]["bind"] == "slot:node-param-key"
    assert nodes["ui:grandmap:node-property-param-label"]["data"]["action"] == "node.param.focus"
    assert nodes["ui:grandmap:node-property-param-controls"]["data"]["children"] == [
        "ui:grandmap:node-property-param-text-input",
        "ui:grandmap:node-property-param-number-input",
        "ui:grandmap:node-property-param-slider-input",
        "ui:grandmap:node-property-param-select",
        "ui:grandmap:node-property-param-boolean-input",
        "ui:grandmap:node-property-param-color-input",
    ]
    assert nodes["ui:grandmap:node-property-param-text-input"]["data"]["tag"] == "input"
    assert nodes["ui:grandmap:node-property-param-text-input"]["data"]["input_type"] == "text"
    assert nodes["ui:grandmap:node-property-param-text-input"]["data"]["bind"] == "slot:node-param-value"
    assert nodes["ui:grandmap:node-property-param-text-input"]["data"]["action"] == "node.param.update"
    assert nodes["ui:grandmap:node-property-param-text-input"]["data"]["visible_when"] == {
        "bind": "slot:node-param-control",
        "values": ["text"],
    }
    assert nodes["ui:grandmap:node-property-param-number-input"]["data"]["input_type"] == "number"
    assert nodes["ui:grandmap:node-property-param-number-input"]["data"]["value_cast"] == "number"
    assert nodes["ui:grandmap:node-property-param-slider-input"]["data"]["input_type"] == "range"
    assert nodes["ui:grandmap:node-property-param-slider-input"]["data"]["value_cast"] == "number"
    assert nodes["ui:grandmap:node-property-param-select"]["data"]["tag"] == "select"
    assert nodes["ui:grandmap:node-property-param-select"]["data"]["action"] == "node.param.update"
    assert nodes["ui:grandmap:node-property-param-option"]["data"]["tag"] == "option"
    assert nodes["ui:grandmap:node-property-param-boolean-input"]["data"]["input_type"] == "checkbox"
    assert nodes["ui:grandmap:node-property-param-boolean-input"]["data"]["value_cast"] == "boolean"
    assert nodes["ui:grandmap:node-property-param-color-input"]["data"]["input_type"] == "color"
    assert nodes["ui:grandmap:node-property-param-promote"]["data"]["action"] == "node.param.promote"
    assert nodes["ui:grandmap:node-property-param-promote"]["data"]["visible_when"] == {
        "bind": "slot:node-param-promotable",
        "values": ["true"],
    }
    assert "param:ui:grandmap:node-properties-panel:cls" in nodes
    assert "param:ui:grandmap:node-property-param-select:visible_when" in nodes
    assert "ui:grandmap:node-property-param-row" in root["data"]["group_nodes"]


def test_node_rail_shell_surface_emits_right_sidebar_render_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-rail-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-rail-shell"
    assert payload["source_node_ids"] == ["ui_node_card"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-rail-shell"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:node-rail-shell"]["data"]["children"] == [
        "ui:grandmap:node-rail-summary",
        "ui:grandmap:node-rail-properties",
        "ui:grandmap:node-rail-connections",
        "ui:grandmap:node-rail-special",
        "ui:grandmap:node-rail-plan",
        "ui:grandmap:node-rail-actions",
    ]
    assert nodes["ui:grandmap:node-rail-summary"]["data"]["render_slot"] == (
        "slot:node-rail-summary"
    )
    assert nodes["ui:grandmap:node-rail-connections"]["data"]["render_slot"] == (
        "slot:node-rail-connections"
    )
    assert nodes["ui:grandmap:node-rail-properties"]["data"]["render_slot"] == (
        "slot:node-rail-properties"
    )
    assert nodes["ui:grandmap:node-rail-special"]["data"]["render_slot"] == (
        "slot:node-rail-special"
    )
    assert nodes["ui:grandmap:node-rail-plan"]["data"]["render_slot"] == (
        "slot:node-rail-plan"
    )
    assert nodes["ui:grandmap:node-rail-actions"]["data"]["render_slot"] == (
        "slot:node-rail-actions"
    )


def test_node_rail_empty_shell_surface_emits_blank_inspector_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [_node("ui_node_card", "Node Card Component")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("node-rail-empty-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:node-rail-empty-shell"
    assert payload["source_node_ids"] == ["ui_node_card"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-rail-empty-shell"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:node-rail-empty-shell"]["data"]["cls"] == "ah-node-rail-empty-shell-node"


def test_node_properties_panel_is_hydrated_in_production_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeRail =")
    ]
    node_rail = jsx[jsx.index("const NodeRail ="):jsx.index("const ConversationRail")]
    shell_surface = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeRailShellSurface ="))
    ]

    assert "const ensureGrandMapNodePropertiesPanelNodes = (node, slots) =>" in jsx
    assert "const seedGrandMapNodePropertiesPanelFallbackNodes = (node, slots) =>" in jsx
    assert "const seededRootId = seedGrandMapNodePropertiesPanelFallbackNodes(node, slots || {});" in jsx
    assert "if (seededRootId) rememberGrandMapSurfaceBuild(rootId, signature);" in jsx
    assert "if (grandMapSurfaceShouldReuse(rootId, signature)) return rootId;" in jsx
    assert "get_grand_map_ui_surface', 'node-properties-panel'" in jsx
    assert "node.param.update" in properties_surface
    assert "node.param.promote" in properties_surface
    assert "node.param.focus" in properties_surface
    assert "lm-param-promote" in properties_surface
    assert "lm-ui-node-focus" in properties_surface
    assert "lm-promote-param-to-socket" not in properties_surface
    assert "const nodePropertiesRoot = node" not in properties_surface
    assert "const nodePropertiesRoot = useGrandMapSurfaceRoot(" in properties_surface
    assert "() => node ? ensureGrandMapNodePropertiesPanelNodes(node, {" in properties_surface
    assert "__surface_signature: propertySurfaceSignature" in properties_surface
    assert "[propertySurfaceSignature]" in properties_surface
    assert "const [, bumpPropertiesSurface] = React.useReducer" not in properties_surface
    assert "const bridgeLate = setTimeout(() => bumpPropertiesSurface(), 1600)" not in properties_surface
    assert "const immediateNodePropertiesRoot = lightweightProperties && node" in properties_surface
    assert "const effectiveNodePropertiesRoot = immediateNodePropertiesRoot || nodePropertiesRoot;" in properties_surface
    assert '<UiNodeSurface rootId={effectiveNodePropertiesRoot} surface="node-properties-panel"/>' in properties_surface
    assert "const railNode = rootId" in shell_surface
    assert "resolveRightRailFocusedNodeThroughRelation(railGraph, rootId, node)" in shell_surface
    assert "const onRailParamChange = React.useCallback((k, v, commit, recookNodeId) => {" in shell_surface
    assert "onParamChange && onParamChange(k, v, commit, recookNodeId, railNode && railNode.id);" in shell_surface
    assert "<NodePropertiesSurface node={railNode} onParamChange={onRailParamChange}/>" in shell_surface
    assert "<NodePropertiesSurface node={railNode} onParamChange={onParamChange}/>" not in shell_surface
    assert "<NodePropertiesSurface node={node} onParamChange={onParamChange}/>" not in shell_surface
    assert "node = { ins:[], outs:[], messages:[], params:[], ...node }" not in node_rail
    assert "node.ins = Array.isArray(node.ins) ? node.ins : [];" in node_rail
    assert "<NodePropertiesSurface node={node} onParamChange={onParamChange}/>" not in node_rail
    assert "FullParam" not in shell_surface


def test_node_rail_shell_is_hydrated_in_production_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_rail = jsx[jsx.index("const NodeRail ="):jsx.index("const ConversationRail")]
    shell_surface = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeRailShellSurface ="))
    ]

    assert "const NodeRailShellSurface = ({ node, cat, bumpGraph, setFocusId, onParamChange, children }) =>" in jsx
    assert "const seedGrandMapNodeRailShellFallbackNodes = (node) =>" in jsx
    assert "const seededRootId = seedGrandMapNodeRailShellFallbackNodes(node);" in jsx
    assert "return seededRootId;" in jsx
    assert "return seededRootId || rootId;" in jsx
    assert "return _uiFind(g.nodes, rootId) ? rootId : seedGrandMapNodeRailShellFallbackNodes(node);" in jsx
    assert "get_grand_map_ui_surface', 'node-rail-shell'" in jsx
    assert "slot:node-rail-summary" in shell_surface
    assert "slot:node-rail-connections" in shell_surface
    assert "slot:node-rail-properties" in shell_surface
    assert "slot:node-rail-special" in shell_surface
    assert 'data-node-rail-properties-host="1"' not in shell_surface
    assert "<NodePropertiesSurface node={railNode} onParamChange={onRailParamChange}/>" in shell_surface
    assert "slot:node-rail-plan" in shell_surface
    assert "slot:node-rail-actions" in shell_surface
    assert "window.dispatchEvent(new CustomEvent('archhub-ui-surface-imported', { detail: { root_id: rootId } }))" in jsx
    assert "const EmptyNodeRailShellSurface = () =>" in jsx
    assert "const ensureGrandMapNodeRailEmptyShellNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'node-rail-empty-shell'" in jsx
    assert "if (!node) return <EmptyNodeRailShellSurface/>;" in node_rail
    assert "const specialRail = railNode && railNode.cat === 'ai'" in shell_surface
    assert "? <ConversationRail node={railNode} bumpGraph={bumpGraph}/>" in shell_surface
    assert "? <ConnectorRail node={railNode} bumpGraph={bumpGraph}/>" in shell_surface
    assert "const specialRail = node.cat === 'ai'" not in node_rail
    assert "? <ConversationRail node={node} bumpGraph={bumpGraph}/>" not in node_rail
    assert "? <ConnectorRail node={node} bumpGraph={bumpGraph}/>" not in node_rail
    assert "if (node.cat === 'ai') return <ConversationRail" not in node_rail
    assert "return <ConnectorRail node={node} bumpGraph={bumpGraph}/>" not in node_rail
    assert "<NodeRailShellSurface node={node} cat={cat} bumpGraph={bumpGraph} setFocusId={setFocusId} onParamChange={onParamChange}/>" in node_rail
    assert "{specialRail}</NodeRailShellSurface>" not in node_rail
    assert "if (!node) return <aside" not in node_rail
    assert '<aside className="ah-scroll"' not in node_rail


def test_node_rail_shell_wires_focus_relation_to_inspected_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodeRailShellTemplate ="):
        jsx.index("const nodeRailParamItems =", jsx.index("const cloneGrandMapNodeRailShellTemplate ="))
    ]
    helper = jsx[
        jsx.index("const rightRailFocusWireId ="):
        jsx.index("const resolveAppRelationWireRelation =", jsx.index("const rightRailFocusWireId ="))
    ]

    assert "syncGrandMapNodeRailFocusRelation(node, rootId);" in clone
    assert "const rightRailFocusWireId = (rootId) =>" in helper
    assert "const syncGrandMapNodeRailFocusRelation = (node, rootId) =>" in helper
    assert "const resolveRightRailFocusedNodeThroughRelation = (graph, rootId, fallbackNode) =>" in helper
    assert "const relationWireId = rightRailFocusWireId(rootId);" in helper
    assert "const relationWire = wires.find(w => w && w.id === relationWireId);" in helper
    assert "const targetPortNodeId = relationData.to_port_node || relationNodeData.to_port_node" in helper
    assert "targetPortData.owner" in helper
    assert "const resolved = targetId ? _uiFind(nodes, targetId) : null;" in helper
    assert "return resolved || fallbackNode || null;" in helper
    assert "relation_wire_family: 'right_rail_focus'" in helper
    assert "wire_family: 'right_rail_focus'" in helper
    assert "relation: 'right_rail_focus'" in helper
    assert "owner: rootId" in helper
    assert "target: targetId" in helper
    assert "value_type: 'node'" in helper
    assert "schema_ref: 'archhub.graph.node'" in helper
    assert "behavior: 'drive-active-right-rail'" in helper
    assert "presentation: 'inspector-row'" in helper
    assert "right_rail_focus_relation_node_id: relationNodeId || ''" in helper
    assert "['right_rail_focus_node_id', targetId]" in helper
    assert "setGrandMapInlineNodeField(owner, field, fieldValue)" in helper
    assert "window.ahSetUiNodeParam(rootId, 'right_rail_focus_node_id', targetId);" not in helper
    assert "data.role === 'wire' && data.wire_family === 'right_rail_focus'" in helper
    assert "data.role === 'wire_layer' && data.wire_family === 'right_rail_focus'" in helper
    assert "data.role === 'parameter' && data.relation_wire_family === 'right_rail_focus'" in helper
    assert "const syncApplicationRightRailFocusContext = (detail) =>" in jsx
    assert "if (detail.node_id) window.__archhub_focus_id = detail.node_id;" in jsx
    assert "right_rail_focus_wire_node_id: detail.wire_node_id || ''" in jsx
    assert "right_rail_focus_endpoint_role: detail.endpoint_role || ''" in jsx
    assert "right_rail_focus_wire_layer_node_id: detail.wire_layer_node_id || ''" in jsx
    assert "Object.keys(payload).forEach(key => setGrandMapInlineNodeField(appNode, key, payload[key]));" in jsx
    assert "const portNodeId = syncApplicationBoundaryPortValue(g, 'right_rail_focus', payload.right_rail_focus_node_id);" in jsx
    assert "Object.keys(payload).forEach(key => materializeGrandMapParamNode(portNodeId, key, payload[key]));" in jsx
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, key, payload[key])" not in jsx
    assert "const syncApplicationRightRailFocusToCanvasWire = (detail) =>" in jsx
    assert "if (!wireNodeId && focusData.role === 'wire') wireNodeId = focusNode.id;" in jsx
    assert "if (!wireNodeId && (focusData.role === 'wire_layer' || focusData.role === 'wire_runtime'))" in jsx
    assert "nodeConnectionIsInspectorInternalWireFamily(wireFamily)" in jsx
    assert "window.__archhub_active_canvas_wire_selection = selection;" in jsx
    assert "const syncSelectedWire = window.__archhubSyncGrandMapCanvasSelectedWireState;" in jsx
    assert "syncApplicationRightRailFocusToCanvasWire(detail);" in jsx


def test_node_properties_rows_wire_to_parameter_nodes_in_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const rightRailPropertyWireId ="):
        jsx.index("const rightRailFocusWireId =", jsx.index("const rightRailPropertyWireId ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="))
    ]
    prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailClones = (activeSid) =>"):
        jsx.index("let __grandMapUiHomeSlots = {};")
    ]

    assert "const syncGrandMapNodePropertyRowRelation = (rowNodeId, ownerNodeId, key, paramNodeId, options = {}) =>" in helper
    assert "const handleRightRailPropertyParamUpdateAction = (detail) =>" in helper
    assert "const resolveRightRailPropertyRelationTarget = (graph, args) =>" in helper
    assert "const syncRightRailPropertyActionRelationArgs = (graph, rowNodeId, ownerNodeId, key, relationResult) =>" in helper
    assert "relation_wire_family: 'right_rail_property'" in helper
    assert "wire_family: 'right_rail_property'" in helper
    assert "relation: 'right_rail_property'" in helper
    assert "property_owner_node_id: ownerNodeId" in helper
    assert "property_row_node_id: rowNodeId" in helper
    assert "property_key: key" in helper
    assert "behavior: options.behavior || 'display-and-edit-parameter'" in helper
    assert "presentation: options.presentation || 'property-row'" in helper
    assert "materialize_wire_anatomy: 'layers'" in helper
    assert "const relationNodeId = upsertAppRelationWireNode(g, relationPayload);" in helper
    assert "right_rail_property_relation_node_id: relationNodeId || ''" in helper
    assert "const materializeRowParamNodes = options.materialize_row_param_nodes === true;" in helper
    assert "['right_rail_property_relation_node_id', relationNodeId || '']" in helper
    assert "setGrandMapInlineNodeField(rowNode, field, fieldValue)" in helper
    assert "if (window.ahSetUiNodeParam && materializeRowParamNodes) {" not in helper
    assert "window.ahSetUiNodeParam(rowNodeId, 'property_param_node_id', targetParamNodeId);" not in helper
    assert "applyGrandMapNodeParamEdit(target.ownerNodeId, { [target.key]: value }" in helper
    assert "operation: 'right-rail.property.edit'" in helper
    assert "materializeGrandMapParamNode(target.targetParamNodeId, 'value', value);" in helper
    assert "window.ahSetUiNodeParam(target.targetParamNodeId, 'value', value);" not in helper
    assert "window.ahSetUiNodeParam(target.ownerNodeId, target.key, value);" not in helper
    assert "target.relationWire.transport_value = value;" in helper
    assert "updated_by: 'right_rail_property_relation'" in helper
    assert "const propertyRelationGroupNodeIds = [];" in clone
    assert "const panelSlotMap = {};" in clone
    assert "syncGrandMapSurfaceStateSlots('node-properties-panel-' + sid, rootId, panelSlotMap" in clone
    assert "state_key: 'node_properties_panel_state_node_id'" in clone
    assert "syncGrandMapNodePropertyRowRelation(rowRoot, node.id, key, paramNodeId" in clone
    assert "materialize_row_param_nodes: false" in clone
    assert "syncRightRailPropertyActionRelationArgs(g, rowRoot, node.id, key, relationResult);" in clone
    assert "'data-property-relation-node': relationResult.relationNodeId || ''" in clone
    assert "existing.concat(rowRootIds, propertyRelationGroupNodeIds)" in clone
    assert "const propertyRelationGroupNodeIds = [];" in fallback
    assert "const panelSlotMap = {" in fallback
    assert "syncGrandMapSurfaceStateSlots('node-properties-panel-' + sid, rootId, panelSlotMap" in fallback
    assert "state_key: 'node_properties_panel_state_node_id'" in fallback
    assert "syncGrandMapNodePropertyRowRelation(rowId, node.id, key, paramNodeId" in fallback
    assert "materialize_row_param_nodes: false" in fallback
    assert "syncRightRailPropertyActionRelationArgs(g, rowId, node.id, key, relationResult);" in fallback
    assert "'data-property-relation-wire': relationResult.relationWireId || ''" in fallback
    assert "rowIds,\n        propertyRelationGroupNodeIds" in fallback
    assert "data.wire_family === 'right_rail_property'" in prune
    assert "data.role === 'wire_layer' && data.wire_family === 'right_rail_property'" in prune
    assert "registerUiHostCapability('node.param.update'" in jsx
    assert "handleRightRailPropertyParamUpdateAction(d)" in jsx


def test_ai_plan_section_is_hydrated_from_node_surface_in_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ai_plan_section = jsx[
        jsx.index("const AiPlanSection ="):
        jsx.index("// Flush-on-deselect helper", jsx.index("const AiPlanSection ="))
    ]
    ai_plan_clone = jsx[
        jsx.index("const cloneGrandMapAiPlanSectionTemplate ="):
        jsx.index("const ensureGrandMapAiPlanSectionNodes =", jsx.index("const cloneGrandMapAiPlanSectionTemplate ="))
    ]
    shell_surface = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeRailShellSurface ="))
    ]

    assert "get_grand_map_ui_surface', 'ai-plan-section'" in jsx
    assert "const rootId = useGrandMapSurfaceRoot(" in ai_plan_section
    assert "() => node ? ensureGrandMapAiPlanSectionNodes(node, plan, loading) : null" in ai_plan_section
    assert 'surface="ai-plan-section"' in ai_plan_section
    assert "ai.plan.replay" in ai_plan_section
    assert "ai.plan.open_file" in ai_plan_section
    assert "AiPlanRow" not in ai_plan_section
    assert "Replay from cache</button>" not in ai_plan_section
    assert "Open full table</button>" not in ai_plan_section
    assert "<AiPlanSection node={railNode}/>" in shell_surface
    assert "const mappedSlotMap = putGrandMapMappedSlotMap(" in ai_plan_clone
    assert "syncGrandMapMappedSurfaceState('ai-plan-section', sid, rootId, mappedSlotMap" in ai_plan_clone
    assert "state_key: 'ai_plan_section_state_node_id'" in ai_plan_clone


def test_node_properties_panel_actions_write_slot_and_canonical_graph_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    project_ui_node = jsx[
        jsx.index("function projectUiNode(nodes, id, key, renderSlots, wires, surfaceName)"):
        jsx.index("// A live surface:", jsx.index("function projectUiNode(nodes, id, key, renderSlots, wires, surfaceName)"))
    ]
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeRail =")
    ]
    node_rail = jsx[jsx.index("const NodeRail ="):jsx.index("const ConversationRail")]

    assert "if (handleRightRailPropertyParamUpdateAction(d)) {" in properties_surface
    assert "const liveNode = liveGraph && Array.isArray(liveGraph.nodes) ? _uiFind(liveGraph.nodes, id) : null;" in project_ui_node
    assert "const mergedArgs = Object.assign({}, primaryActionAuthority.args || {}, eventArgs, args || {});" in project_ui_node
    assert "const liveArgs = liveData.args" not in project_ui_node
    assert "materializeGrandMapParamNode(d.args.value_slot, 'value', d.args.value)" in properties_surface
    assert "materializeGrandMapParamNode(d.args.param_node_id, 'value', d.args.value)" in properties_surface
    assert properties_surface.index("materializeGrandMapParamNode(d.args.value_slot, 'value', d.args.value)") < properties_surface.index(
        "materializeGrandMapParamNode(d.args.param_node_id, 'value', d.args.value)"
    )
    assert "const focusNodeId = d.args.focus_node_id || d.args.wire_layer_node_id ||" in properties_surface
    assert "ensureGrandMapFocusableParamNode(node, key, currentValue, d.args.param_node_id);" in properties_surface
    assert "node_id: focusNodeId" in properties_surface
    assert "handler_node_id: route.handler_node_id || ''" in properties_surface
    assert "const liveGraphNodes = ((window.__archhub_LM_GRAPH || {}).nodes || []);" in node_rail
    assert "const editNodeId = targetNodeId || node.id;" in node_rail
    assert "const liveNode = liveGraphNodes.find(x => x && x.id === editNodeId) || (editNodeId === node.id ? node : null) || node;" in node_rail
    assert "const targetNode = liveNode;" in node_rail
    assert "if (targetNode !== node && targetNode.id === node.id) {" in node_rail


def test_ui_param_writer_mirrors_behavior_params_to_runtime_flags():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    setter = jsx[
        jsx.index("window.ahSetUiNodeParam = function"):
        jsx.index("window.ahEditUiNode = function", jsx.index("window.ahSetUiNodeParam = function"))
    ]

    assert "if (key === 'frozen' || key === 'bypass') {" in setter
    assert "if (key === 'title') {" in setter
    assert "n.title = nextTitle;" in setter
    assert "if (key === 'sub') {" in setter
    assert "n.sub = nextSub;" in setter
    assert "key === 'preview_off' || key === 'pinned'" in setter
    assert "n[key] = nextBehaviorFlag;" in setter
    assert "key === 'pinned_value' || key === 'pinned_at'" in setter
    assert "n[key] = value;" in setter
    assert "var boolValue = value === true || value === 'true' || value === 1 || value === '1';" in setter
    assert "n.frozen = boolValue;" in setter
    assert "n.bypass = false;" in setter
    assert "n.config.bypass = false;" in setter
    assert "n.bypass = boolValue;" in setter
    assert "n.frozen = false;" in setter
    assert "n.config.frozen = false;" in setter


def test_node_properties_panel_routes_ui_node_edits_to_ui_param_graph():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeRail =")
    ]

    assert "const isUiNode = node && (String(node.type || '').indexOf('ui.') === 0" in properties_surface
    assert "applyGrandMapNodeParamEdit(node, { [d.args.key]: d.args.value }" in properties_surface
    assert "operation: 'right-rail.param.edit'" in properties_surface
    assert "window.ahSetUiNodeParam(node.id, d.args.key, d.args.value)" not in properties_surface
    assert "if (isUiNode) {" in properties_surface
    ui_branch = properties_surface[
        properties_surface.index("if (isUiNode) {"):
        properties_surface.index("onParamChange && onParamChange", properties_surface.index("if (isUiNode) {"))
    ]
    assert "return;" in ui_branch


def test_node_properties_panel_materializes_param_nodes_for_workflow_node_edits():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeRail =")
    ]
    update_branch = properties_surface[
        properties_surface.index("if (d.action === 'node.param.update') {"):
        properties_surface.index("} else if (d.action === 'node.param.promote') {")
    ]

    selected_param_write = "applyGrandMapNodeParamEdit(node, { [d.args.key]: d.args.value }, {"
    direct_update_branch = update_branch[update_branch.index("let recookNodeId = '';"):]
    assert selected_param_write in direct_update_branch
    assert direct_update_branch.index(selected_param_write) < direct_update_branch.index("if (isUiNode) {")
    assert direct_update_branch.index(selected_param_write) < direct_update_branch.index("onParamChange && onParamChange")
    ui_branch = direct_update_branch[
        direct_update_branch.index("if (isUiNode) {"):
        direct_update_branch.index("onParamChange && onParamChange")
    ]
    assert "return;" in ui_branch


def test_node_properties_panel_materializes_visible_params_on_focus_not_only_edit():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="))
    ]

    assert "const paramNodeId = (p && p.param_node_id) ? p.param_node_id : _uiParamNodeId(node.id, key);" in clone
    assert "const paramValue = p && Object.prototype.hasOwnProperty.call(p, 'v') ? p.v : '';" in clone
    assert "materializeGrandMapParamNode(node, key, paramValue);" in clone
    assert clone.index("materializeGrandMapParamNode(node, key, paramValue);") < clone.index("const rowMapId =")
    assert "[valueSlot]: paramValue" in clone
    assert "syncGrandMapSurfaceStateSlots('node-property-param-row-'" not in clone
    assert "const paramNodeId = (p && p.param_node_id) ? p.param_node_id : _uiParamNodeId(node.id, key);" in fallback
    assert "args:{ node_id:node.id, key, param_node_id:paramNodeId, focus_node_id:focusNodeId, read_only:readOnly, wire_layer:wireLayer, wire_layer_node_id:wireLayerNodeId, runtime_node_id:runtimeNodeId, runtime_key:runtimeKey, value_slot:valueSlot }" in fallback
    assert "materializeGrandMapParamNode(node, key, rawValue);" in fallback


def test_node_rail_params_read_values_from_wired_param_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const nodeRailVisibleParamItems ="):
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate =", jsx.index("const nodeRailParamItems ="))
    ]

    assert "const nodeRailVisibleParamItems = (items) =>" in helper
    assert "'children'," in helper
    assert "'param_nodes'," in helper
    assert "'group_nodes'," in helper
    assert "'action_nodes'," in helper
    assert "'summary_icon'," in helper
    assert "'summary_label'," in helper
    assert "const family = String((p && (p.relation_wire_family || p.wire_family)) || '');" in helper
    assert "const exposureScope = String((p && p.exposure_scope) || '');" in helper
    assert "if (family === 'ui_slot_parameter' || family.indexOf('right_rail_') === 0) return false;" in helper
    assert "if (exposureScope === 'right-rail') return false;" in helper
    assert "const liveNode = node && node.id" in helper
    assert "const wiredParamNodeIds = new Set" in helper
    assert "String(fromPort || '').indexOf('param:') === 0" in helper
    assert "wiredParamNodeIds.add(toNode);" in helper
    assert "const applyWiredParamNodeValues = (items) =>" in helper
    assert "const paramNode = graphNodes.find(n => n && n.id === pid);" in helper
    assert "relation_wire_family: data.relation_wire_family || ''" in helper
    assert "exposure_scope: data.exposure_scope || ''" in helper
    assert "Object.assign(existing, metadata);" in helper
    assert "existing.v = value;" in helper
    assert "existing.param_node_id = pid;" in helper
    assert "param_node_id: pid" in helper
    assert "const appendRuntimeItems = (items) => (items || []).concat(nodeRailWireRuntimeParamItems(liveNode));" in helper
    assert "const finalizeItems = (items) => nodeRailRelationContractParamItems(" in helper
    assert "return finalizeItems(items);" in helper
    assert "return finalizeItems(params);" in helper


def test_wire_runtime_payload_rows_are_properties_not_authored_layers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const WIRE_RUNTIME_PROPERTY_FIELDS ="):
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate =", jsx.index("const nodeRailParamItems ="))
    ]
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeActionsSurface =")
    ]
    update_branch = properties_surface[
        properties_surface.index("if (d.action === 'node.param.update') {"):
        properties_surface.index("} else if (d.action === 'node.param.promote') {")
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="))
    ]

    assert "['transport_value', 'runtime transport value', 'text']" in helper
    assert "['decoded_preview', 'runtime decoded preview', 'text']" in helper
    assert "['display_value', 'runtime display value', 'text']" in helper
    assert "function nodeRailWireRuntimeParamItems(node)" in helper
    assert "data.role !== 'wire' && data.role !== 'selected_wire_path_wire'" in helper
    assert "if (nodeConnectionIsInspectorInternalWireFamily(data.wire_family || data.relation_wire_family || '')) return [];" in helper
    assert "const runtimeRow = nodeConnectionRuntimeRowForWire(graph, node);" in helper
    assert "k: 'runtime_' + runtimeKey" in helper
    assert "param_node_id: _uiParamNodeId(runtimeNode.id, runtimeKey)" in helper
    assert "param_family: 'wire_runtime'" in helper
    assert "runtime_node_id: runtimeNode.id" in helper
    assert "runtime_key: runtimeKey" in helper
    assert "wire_node_id: node.id" in helper
    assert "const appendRuntimeItems = (items) => (items || []).concat(nodeRailWireRuntimeParamItems(liveNode));" in helper
    assert "if (runtimeNodeId) copy.data.data_attrs['data-runtime-node'] = runtimeNodeId;" in clone
    assert "if (runtimeKey) copy.data.data_attrs['data-runtime-key'] = runtimeKey;" in clone
    assert "runtime_node_id: runtimeNodeId" in clone
    assert "runtime_key: runtimeKey" in clone
    assert "'data-runtime-node':runtimeNodeId" in fallback
    assert "'data-runtime-key':runtimeKey" in fallback
    assert "runtime_node_id:runtimeNodeId" in fallback
    assert "runtime_key:runtimeKey" in fallback
    assert "if (isRelationWireNode && d.args.runtime_node_id && d.args.runtime_key) {" in update_branch
    assert "applyGrandMapNodeParamEdit(d.args.runtime_node_id, { [d.args.runtime_key]: d.args.value }" in update_branch
    assert "operation: 'right-rail.runtime-param.edit'" in update_branch
    assert "window.ahSetUiNodeParam(d.args.runtime_node_id, d.args.runtime_key, d.args.value);" not in update_branch
    assert "} else if (isWorkflowWireNode) {" in update_branch


def test_node_properties_panel_parameter_node_value_edits_drive_owner_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeRail =")
    ]
    update_branch = properties_surface[
        properties_surface.index("if (d.action === 'node.param.update') {"):
        properties_surface.index("} else if (d.action === 'node.param.promote') {")
    ]

    assert "const isParameterNode = node && node.data && node.data.role === 'parameter';" in properties_surface
    assert "if (isParameterNode) {" in update_branch
    assert "const ownerId = (node.data && (node.data.owner || node.data.owner_id))" in update_branch
    assert "const ownerKey = (node.data && node.data.key)" in update_branch
    assert "if (ownerId && d.args.key === 'value' && ownerKey && ownerId !== node.id) {" in update_branch
    assert "applyGrandMapNodeParamEdit(ownerId, { [ownerKey]: d.args.value }" in update_branch
    assert "operation: 'right-rail.owner-param.edit'" in update_branch
    assert "window.ahSetUiNodeParam(ownerId, ownerKey, d.args.value);" not in update_branch
    assert "if (ownerId && ownerId !== node.id) {" in update_branch
    assert "recookNodeId = ownerId;" in update_branch
    assert "materializeGrandMapParamNode(d.args.param_node_id, 'value', d.args.value);" in update_branch
    assert update_branch.index("materializeGrandMapParamNode(d.args.param_node_id, 'value', d.args.value);") < update_branch.index(
        "applyGrandMapNodeParamEdit(node, { [d.args.key]: d.args.value }, {"
    )
    assert update_branch.index("applyGrandMapNodeParamEdit(node, { [d.args.key]: d.args.value }, {") < update_branch.index(
        "applyGrandMapNodeParamEdit(ownerId, { [ownerKey]: d.args.value }"
    )
    assert "onParamChange && onParamChange(d.args.key, d.args.value, false, recookNodeId);" in update_branch


def test_node_rail_recooks_parameter_or_wire_owner_when_editing_backing_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_rail = jsx[
        jsx.index("const NodeRail ="):
        jsx.index("// Audit 2026-05-28", jsx.index("const NodeRail ="))
    ]

    assert "const onParamChange = (k, v, commit, recookNodeId, targetNodeId) => {" in node_rail
    assert "const editNodeId = targetNodeId || node.id;" in node_rail
    assert "const cookNodeId = recookNodeId || targetNode.id;" in node_rail
    assert "flushReCook(cookNodeId);" in node_rail
    assert "reCookParamTick(cookNodeId);" in node_rail
    assert "flushReCook(targetNode.id);" not in node_rail
    assert "reCookParamTick(targetNode.id);" not in node_rail


def test_node_properties_panel_focuses_parameter_node_as_graph_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    focus_helper = jsx[
        jsx.index("const ensureGrandMapFocusableParamNode ="):
        jsx.index("let __grandMapUiHomeTopPending", jsx.index("const ensureGrandMapFocusableParamNode ="))
    ]
    properties_surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeRail =")
    ]
    workspace = jsx[
        jsx.index("const WorkspaceInner ="):
        jsx.index("const Workspace = React.memo", jsx.index("const WorkspaceInner ="))
    ]
    focus_branch = properties_surface[
        properties_surface.index("} else if (d.action === 'node.param.focus') {"):
        properties_surface.index("};", properties_surface.index("} else if (d.action === 'node.param.focus') {"))
    ]

    assert "const ensureGrandMapFocusableParamNode =" in focus_helper
    assert "const fallbackParamNodeId = _uiParamNodeId(nodeId, key);" in focus_helper
    assert "materializeGrandMapParamNode(nodeId, key, value);" in focus_helper
    assert "window.ahSetUiNodeParam(node.id, key, currentValue);" not in focus_branch
    assert "const focusNodeId = d.args.focus_node_id || d.args.wire_layer_node_id ||" in focus_branch
    assert "ensureGrandMapFocusableParamNode(node, key, currentValue, d.args.param_node_id);" in focus_branch
    assert "node_id: focusNodeId" in focus_branch
    assert "handler_node_id: route.handler_node_id || ''" in focus_branch
    assert "window.addEventListener('lm-ui-node-focus', focusGraphNode);" in workspace
    assert "if (!graphNodes.find(n => n && n.id === nodeId)) return;" in workspace
    assert "setFocusId(nodeId);" in workspace


def test_node_properties_wire_layer_rows_focus_layer_node_before_storage_param():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="))
    ]
    focus_branch = jsx[
        jsx.index("} else if (d.action === 'node.param.focus') {"):
        jsx.index("};", jsx.index("} else if (d.action === 'node.param.focus') {"))
    ]

    assert "'data-wire-layer':" not in clone
    assert "if (p && p.wire_layer) copy.data.data_attrs['data-wire-layer'] = p.wire_layer;" in clone
    assert "if (p && p.wire_layer_node_id) copy.data.data_attrs['data-wire-layer-node'] = p.wire_layer_node_id;" in clone
    assert "wire_layer_node_id: p && p.wire_layer_node_id ? p.wire_layer_node_id : ''" in clone
    assert "const wireLayerNodeId = p && p.wire_layer_node_id ? p.wire_layer_node_id : '';" in fallback
    assert "args:{ node_id:node.id, key, param_node_id:paramNodeId, focus_node_id:focusNodeId, read_only:readOnly, wire_layer:wireLayer, wire_layer_node_id:wireLayerNodeId, runtime_node_id:runtimeNodeId, runtime_key:runtimeKey }" in fallback
    assert "d.args.focus_node_id || d.args.wire_layer_node_id ||" in focus_branch
    assert "ensureGrandMapFocusableParamNode(node, key, currentValue, d.args.param_node_id)" in focus_branch


def test_port_parameter_properties_surface_exposes_attached_wire_references():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const nodeRailAttachedWireReferenceParamItems = (node) =>"):
        jsx.index("const nodeRailParamItems = (node) =>", jsx.index("const nodeRailAttachedWireReferenceParamItems = (node) =>"))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const seedGrandMapNodePropertiesPanelFallbackNodes ="))
    ]
    update_branch = jsx[
        jsx.index("if (d.action === 'node.param.update') {"):
        jsx.index("} else if (d.action === 'node.param.promote') {", jsx.index("if (d.action === 'node.param.update') {"))
    ]

    assert "data.role !== 'parameter' || data.param_family !== 'port'" in helper
    assert "wireData.role === 'port_owner_link'" in helper
    assert "nodeConnectionIsInspectorInternalWireData(wireData)" in helper
    assert "attached_wire_' + String(index + 1)" in helper
    assert "attached wire node" in helper
    assert "opposite port node" in helper
    assert "gate layer node" in helper
    assert "read_only: true" in helper
    assert "focus_node_id: focusNodeId || value" in helper
    assert "const appendAttachedWireReferenceItems = (items) => (items || []).concat(nodeRailAttachedWireReferenceParamItems(liveNode));" in jsx
    assert "appendAttachedWireReferenceItems(appendWireAnatomyReferenceItems(appendRuntimeItems(items)))" in jsx
    assert "return finalizeItems(params);" in jsx
    assert "const readOnlySlot = rowMapId('slot:node-param-readonly');" in clone
    assert "[readOnlySlot]: p && p.read_only ? 'true' : 'false'" in clone
    assert "const syncNodeRailPropertyParamNodeMetadata = (graph, ownerNodeId, key, paramNodeId, p) =>" in jsx
    assert "graph_reference: isGraphReference" in jsx
    assert "syncNodeRailPropertyParamNodeMetadata(g, node.id, key, paramNodeId, p);" in clone
    assert "focus_node_id: p && p.focus_node_id ? p.focus_node_id : ''" in clone
    assert "read_only: !!(p && p.read_only)" in clone
    assert "copy.data.disabled_bind = readOnlySlot;" in clone
    assert "'data-read-only': 'true'" in clone
    assert "const focusNodeId = p && p.focus_node_id ? p.focus_node_id : '';" in fallback
    assert "const readOnly = !!(p && p.read_only);" in fallback
    assert "syncNodeRailPropertyParamNodeMetadata(g, node.id, key, paramNodeId, p);" in fallback
    assert "disabled_bind:readOnly ? valueSlot + ':readonly' : undefined" in fallback
    assert "if (d.args.read_only) {" in update_branch


def test_wire_node_properties_surface_exposes_endpoint_layer_runtime_references():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const nodeRailWireAnatomyReferenceParamItems = (node) =>"):
        jsx.index("const nodeRailParamItems = (node) =>", jsx.index("const nodeRailWireAnatomyReferenceParamItems = (node) =>"))
    ]
    param_items = jsx[
        jsx.index("const nodeRailParamItems ="):
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate =", jsx.index("const nodeRailParamItems ="))
    ]

    assert "(data.role !== 'wire' && data.role !== 'selected_wire_path_wire')" in helper
    assert "nodeConnectionIsInspectorInternalWireFamily(wireFamily)" in helper
    assert "nodeConnectionWireAuthorityData(graph, node, null)" in helper
    assert "source_endpoint_port_node" in helper
    assert "target_endpoint_port_node" in helper
    assert "source port layer node" in helper
    assert "target port layer node" in helper
    assert "gate layer node" in helper
    assert "codec layer node" in helper
    assert "encryption layer node" in helper
    assert "behavior layer node" in helper
    assert "presentation layer node" in helper
    assert "runtime_node" in helper
    assert "read_only: true" in helper
    assert "const appendWireAnatomyReferenceItems = (items) => (items || []).concat(nodeRailWireAnatomyReferenceParamItems(liveNode));" in param_items
    assert "appendWireAnatomyReferenceItems(appendRuntimeItems(items))" in param_items
    assert "return finalizeItems(params);" in param_items


def test_node_actions_panel_surface_emits_authority_rail_buttons(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_command_palette", "Command Palette"),
            ],
            "wires": [],
        },
    ])
    payload = grand_map_ui_surface("node-actions-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:node-actions-panel"
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:node-actions-panel"]
    assert root["data"]["children"] == [
        "ui:grandmap:node-action-rerun",
        "ui:grandmap:node-action-pin-skill",
        "ui:grandmap:node-action-branch",
        "ui:grandmap:node-action-disconnect",
    ]
    assert nodes["ui:grandmap:node-action-rerun"]["data"]["text"] == "\u21bb Rerun this node"
    assert nodes["ui:grandmap:node-action-rerun"]["data"]["action"] == "node.rail.rerun"
    assert nodes["ui:grandmap:node-action-pin-skill"]["data"]["text"] == "Pin to skill"
    assert nodes["ui:grandmap:node-action-pin-skill"]["data"]["action"] == "node.rail.pin-skill"
    assert nodes["ui:grandmap:node-action-branch"]["data"]["text"] == "Branch from here"
    assert nodes["ui:grandmap:node-action-branch"]["data"]["action"] == "node.rail.branch"
    assert nodes["ui:grandmap:node-action-disconnect"]["data"]["text"] == "Disconnect all"
    assert nodes["ui:grandmap:node-action-disconnect"]["data"]["action"] == "node.rail.disconnect"
    assert "ah-node-action-danger-node" in nodes["ui:grandmap:node-action-disconnect"]["data"]["cls"]


def test_node_actions_panel_is_hydrated_in_production_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_rail = jsx[jsx.index("const NodeRail ="):jsx.index("const ConversationRail")]
    actions_surface = jsx[
        jsx.index("const NodeActionsSurface ="):
        jsx.index("const NodeSummarySurface =", jsx.index("const NodeActionsSurface ="))
    ]
    shell_surface = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeRailShellSurface ="))
    ]

    assert "const NodeActionsSurface = ({ node, bumpGraph }) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-actions-panel'" in jsx
    assert "node.rail.rerun" in jsx
    assert "node.rail.pin-skill" in jsx
    assert "node.rail.branch" in jsx
    assert "node.rail.disconnect" in jsx
    assert "const nodeActionsRoot = useGrandMapSurfaceRoot(" in actions_surface
    assert "() => node ? ensureGrandMapNodeActionsPanelNodes(node) : null" in actions_surface
    assert "const [, bumpNodeActionsSurface] = React.useReducer" not in actions_surface
    assert "<NodeActionsSurface node={railNode} bumpGraph={bumpGraph}/>" in shell_surface
    assert "<NodeActionsSurface node={node} bumpGraph={bumpGraph}/>" not in node_rail
    assert "bridgeCall('run_node', currentSid(), node.id, JSON.stringify(LM_GRAPH))" not in node_rail
    assert "registerUiHostCapability('node.rail.rerun'" in actions_surface
    assert "registerUiHostCapability('node.rail.pin-skill'" in actions_surface
    assert "registerUiHostCapability('node.rail.branch'" in actions_surface
    assert "registerUiHostCapability('node.rail.disconnect'" in actions_surface
    assert "handler_node_id:authority && authority.handlerNode && authority.handlerNode.id || ''" in actions_surface
    assert "recordGraphOperationNode(LM_GRAPH, 'node.rerun'" in actions_surface
    assert "recordGraphOperationNode(LM_GRAPH, 'node.pin-skill'" in actions_surface
    assert "handler_node_id: route.handler_node_id || ''" in actions_surface


def test_node_actions_panel_prematerializes_action_behavior_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    actions_clone = jsx[
        jsx.index("const cloneGrandMapNodeActionsPanelTemplate ="):
        jsx.index("const ensureGrandMapNodeActionsPanelNodes =", jsx.index("const cloneGrandMapNodeActionsPanelTemplate ="))
    ]
    action_helpers = jsx[
        jsx.index("function ensureUiActionBehaviorNode"):
        jsx.index("const uiActionSurfaceNameFromEvent", jsx.index("function ensureUiActionBehaviorNode"))
    ]
    prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailClones ="):
        jsx.index("let __grandMapUiHomeSlots", jsx.index("const pruneGrandMapFocusedRailClones ="))
    ]

    assert "const actionRelationGroupNodeIds = [];" in actions_clone
    assert "ensureUiActionBehaviorNode(copy.id, 'action', copy.data.action" in actions_clone
    assert "event: 'hydrate'" in actions_clone
    assert "component: 'node-actions-panel'" in actions_clone
    assert "ensureUiActionHandlerRoute({" in actions_clone
    assert "owner_node_id: copy.id" in actions_clone
    assert "target_node_id: node.id" in actions_clone
    assert "action_node_id: runtime.action_node_id || ''" in actions_clone
    assert "action_handler_node_id: route.handler_node_id || ''" in actions_clone
    assert "'data-action-node-id': runtime.action_node_id || ''" in actions_clone
    assert "actionRelationGroupNodeIds.push(...groupNodes);" in actions_clone
    assert "setGrandMapInlineNodeField(rootNode, 'group_nodes', groupNodes)" in actions_clone
    assert "const isHydration = meta.hydrate === true || meta.event === 'hydrate';" in action_helpers
    assert "const now = isHydration ? 0 : Date.now();" in action_helpers
    assert "const isHydration = options.hydrate === true || d.hydrate === true || d.event === 'hydrate';" in action_helpers
    assert "data.role === 'ui_action' && removeIds.has(data.owner)" in prune
    assert "data.role === 'ui_action_handler' && removeIds.has(data.owner_node_id)" in prune


def test_ui_node_surface_renderer_applies_node_style_data():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    projector = jsx[jsx.index("function projectUiNode"):jsx.index("const UiNodeSurface =")]

    assert "if (d.style && typeof d.style === 'object') props.style = d.style;" in projector
    assert "if (d.src_bind) props.src = String(_uiBindingValue(nodes, wires, id, 'src_bind', d.src_bind));" in projector
    assert "if (d.href_bind) props.href = String(_uiBindingValue(nodes, wires, id, 'href_bind', d.href_bind));" in projector
    assert "if (d.alt_bind) props.alt = String(_uiBindingValue(nodes, wires, id, 'alt_bind', d.alt_bind));" in projector
    assert "else if (d.alt) props.alt = String(d.alt);" in projector


def test_ui_node_surface_renderer_reads_bindings_from_wires_first():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const __uiBindingWireIndexes ="):
        jsx.index("function ensureUiActionBehaviorNode", jsx.index("const __uiBindingWireIndexes ="))
    ]
    projector = jsx[jsx.index("function projectUiNode"):jsx.index("const UiNodeSurface =")]
    surface = jsx[jsx.index("const UiNodeSurface ="):jsx.index("// THE WATCHER", jsx.index("const UiNodeSurface ="))]

    assert "data.role === 'ui_binding_relation' ||" in helper
    assert "(data.role === 'relation' && data.wire_family === 'ui_binding')" in helper
    assert "const __uiBindingWireIndexes = typeof WeakMap !== 'undefined' ? new WeakMap() : null;" in helper
    assert "const _uiBindingWireKey = (nodeId, bindingKey) =>" in helper
    assert "const _uiBindingWiresFor = (wires, nodeId, bindingKey) =>" in helper
    assert "data.role === 'relation' && data.wire_family === 'ui_binding'" in helper
    assert "String(_uiEndpointPort(wire.to) || '').replace(/^binding:/, '')" in helper
    assert "const _uiBindingValue = (nodes, wires, nodeId, bindingKey, fallback) =>" in helper
    assert "try { syncUiBindingRelation(nodeId, bindingKey, sourceId); } catch (_e) {}" not in helper
    assert "const syncUiBindingRelation = (targetNodeId, bindingKey, sourceNodeId, surfaceName) =>" in helper
    assert "const compactInspectorBinding = !endpointsAlreadyMaterialized" in helper
    assert "const materializeUiBindingEndpointPorts = (graph, wireNode, rawWire) =>" in helper
    assert "const effectiveSourceNodeId = String(" in helper
    assert "existingRelationData.source_node || existingRelationData.source_owner || sourceNodeId" in helper
    assert "if (!sourceNode && effectiveSourceNodeId.indexOf('slot:') === 0) {" in helper
    assert "sourceNode = ensureUiRenderSlotNode(g, effectiveSourceNodeId);" in helper
    assert "relationData.source_node || relationData.source_owner" in helper
    assert "gatePolicy === 'deny'" in helper
    assert "if (migrated && !relationNode) return '';" in helper
    assert "return migrated ? '' : (fallback || '');" in helper
    assert ".filter(wire => !!_uiBindingWireMeta(wire));" in helper
    assert "relation_wire_family: 'ui_binding'" in helper
    assert "wire_family: 'ui_binding'" in helper
    assert "relation: 'ui_binding'" in helper
    assert "binding_key: bindingKey" in helper
    assert "behavior: existingRelationData.behavior || 'bind-ui-value'" in helper
    assert "presentation: existingRelationData.presentation || 'ui-binding'" in helper
    assert "const uiDeclaredBindingRefs = (data) =>" in helper
    assert "const syncUiSurfaceDeclaredBindingRelations = (nodes, rootId, wires, surfaceName) =>" in helper
    assert "function hydrateUiNodeActionSubtree(rootId, component)" in jsx
    assert "uiDeclaredBindingRefs(data).forEach(([bindingKey, sourceNodeId]) => {" in helper
    assert "syncUiBindingRelation(nodeId, bindingKey, sourceNodeId, surfaceName || '')" in helper
    assert "const bindingIndex = _uiBindingWireIndex(wires);" in helper
    assert "seen.forEach(targetNodeId => {" in helper
    assert "bindingIndex.byTarget.get(String(targetNodeId))" in helper
    assert "if (data.role !== 'ui_binding_relation') return;" in helper
    assert "syncUiBindingRelation(String(targetNodeId), bindingKey, sourceNodeId, surfaceName || '')" in helper
    assert "'binding_key'" in jsx
    assert "'source_node'" in jsx
    assert "'target_node'" in jsx
    assert "String(_uiBindingValue(nodes, wires, id, 'bind', d.bind))" in projector
    assert "String(_uiBindingValue(nodes, wires, id, 'href_bind', d.href_bind))" in projector
    assert "String(_uiBindingValue(nodes, wires, id, 'alt_bind', d.alt_bind))" in projector
    assert "String(_uiBindingValue(nodes, wires, id, 'text_cases.bind', d.text_cases.bind))" in projector
    assert "String(_uiBindingValue(nodes, wires, id, 'visible_when.bind', d.visible_when.bind))" in projector
    assert "String(_uiBindingValue(nodes, wires, id, 'state_bind', d.state_bind))" in projector
    assert "String(_uiBindingValue(nodes, wires, id, 'disabled_bind', d.disabled_bind))" in projector
    assert "const graph = window.__archhub_LM_GRAPH || {};" in surface
    assert "const wires = graph.wires || [];" in surface
    assert "syncUiSurfaceDeclaredBindingRelations(nodes, rootId, wires, surface);" in surface
    assert "hydrateUiNodeActionSubtree(rootId, 'ui-surface:' + String(surface || 'ui'));" in surface
    assert "projectUiNode(nodes, rootId, 'r', renderSlots || {}, wires, surface)" in surface
    merge = jsx[
        jsx.index("const mergeUiSurfaceIntoGraph ="):
        jsx.index("const grandMapSafeId =", jsx.index("const mergeUiSurfaceIntoGraph ="))
    ]
    assert "if (data.role !== 'ui_binding_relation') return;" in merge
    assert "syncUiBindingRelation(targetNodeId, bindingKey, sourceNodeId)" in merge


def test_ui_render_slots_materialize_mount_relation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const uiRenderSlotMountWireId ="):
        jsx.index("function projectUiNode", jsx.index("const uiRenderSlotMountWireId ="))
    ]
    projector = jsx[jsx.index("function projectUiNode"):jsx.index("const UiNodeSurface =")]

    assert "const uiRenderSlotMountWireId = (hostNodeId, slotId) =>" in helper
    assert "const ensureUiRenderSlotNode = (graph, slotId) =>" in helper
    assert "const uiRenderSlotMountAuthority = (nodes, wires, hostNodeId, declaredSlotId) =>" in helper
    assert "const syncUiRenderSlotMountRelation = (hostNodeId, slotId, surfaceName, hasSlotChild) =>" in helper
    assert "relation_wire_family: 'ui_render_slot_mount'" in helper
    assert "wire_family: 'ui_render_slot_mount'" in helper
    assert "relation: 'ui_render_slot_mount'" in helper
    assert "render_slot_node_id: slotNode.id" in helper
    assert "slot_mount_state: slotMountState" in helper
    assert "slot_has_child: !!hasSlotChild" in helper
    assert "ui_render_slot_mount_state: slotMountState" in helper
    assert "ui_render_slot_mount_relation_node_id: relationNodeId || ''" in helper
    assert "ui_render_slot_mount_wire_id: wireId" in helper
    assert "behavior: 'mount-render-slot'" in helper
    assert "codec: 'react'" in helper
    assert "'render_slot'" in jsx
    assert "optionalWireMetadata" in jsx
    assert "].concat(Object.keys(optionalWireMetadata).map(key => [key, optionalWireMetadata[key]])).forEach(([paramKey, paramValue]) => {" in jsx
    assert "const declaredRenderSlot = d.render_slot || (d.surface_ref ? 'slot:surface-ref:' + d.surface_ref : '');" in projector
    assert "const mountAuthority = uiRenderSlotMountAuthority(nodes, wires, id, declaredRenderSlot);" in projector
    assert "const effectiveRenderSlot = mountAuthority.slotId || declaredRenderSlot;" in projector
    assert "const slotChild = mountAuthority.allowed ? candidateSlotChild : null;" in projector
    assert "const hasRenderSlot = slotChild !== null && slotChild !== undefined && slotChild !== false;" in projector
    assert "if (declaredRenderSlot && (!mountAuthority.migrated || mountAuthority.relationNode))" in projector
    assert "syncUiRenderSlotMountRelation(id, effectiveRenderSlot, surfaceName || '', hasRenderSlot)" in projector
    assert "presentation !== 'hidden'" in helper
    assert "behavior !== 'disabled'" in helper
    assert "authority.migrated && !authority.relationNode" in helper
    assert "ui_render_slot_mount_migrated: true" in helper
    assert "Object.prototype.hasOwnProperty.call(renderSlots, d.render_slot)" not in projector
    assert "projectUiNode(nodes, cid, i, renderSlots, wires, surfaceName)" in projector


def test_ui_node_action_emitter_materializes_behavior_nodes_and_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    action_relation_helper = jsx[
        jsx.index("const uiActionEndpointWireId ="):
        jsx.index("function ensureUiActionBehaviorNode", jsx.index("const uiActionEndpointWireId ="))
    ]
    helper = jsx[
        jsx.index("function ensureUiActionBehaviorNode"):
        jsx.index("function projectUiNode", jsx.index("function ensureUiActionBehaviorNode"))
    ]
    projector = jsx[jsx.index("function projectUiNode"):jsx.index("const UiNodeSurface =")]

    assert "role: 'ui_action'" in helper
    assert "kind: 'behavior'" in helper
    assert "materializeGrandMapParamNode(ownerId, key, actionValue)" in helper
    assert "window.ahSetUiNodeParam(ownerId, key, actionValue)" not in helper
    assert "owner.data.action_nodes" in helper
    assert "owner.data.group_nodes" in helper
    assert "w:ui-action:" in helper
    assert "role: 'ui_action_relation'" in helper
    assert "role: 'ui_action_parameter_relation'" in helper
    assert "role: 'ui_action_args_relation'" in helper
    assert "const syncUiActionRelationWireNode = (wireId, options = {}) =>" in action_relation_helper
    assert "const syncUiImportedActionRelationWireNode = (wire) =>" in action_relation_helper
    assert "relation_wire_family: 'ui_action'" in action_relation_helper
    assert "wire_family: 'ui_action'" in action_relation_helper
    assert "ui_action_relation_node_ids" in action_relation_helper
    assert "ui_action_port_node_ids" in action_relation_helper
    assert "ui_action_layer_node_ids" in action_relation_helper
    assert "role === 'ui_action_relation'" in action_relation_helper
    assert "role === 'ui_action_parameter_relation'" in action_relation_helper
    assert "role === 'ui_action_args_relation'" in action_relation_helper
    assert "role === 'ui_action_handler_route'" in action_relation_helper
    assert "role === 'ui_action_handler_target'" in action_relation_helper
    assert "role === 'ui_action_operation_route'" in action_relation_helper
    assert "syncUiActionRelationWireNode(ownerWireId, {" in helper
    assert "behavior: 'emit-ui-action'" in helper
    assert "presentation: 'ui-action'" in helper
    assert "syncUiActionRelationWireNode(paramWireId, {" in helper
    assert "behavior: 'configure-ui-action'" in helper
    assert "presentation: 'ui-action-param'" in helper
    assert "syncUiActionRelationWireNode(argsWireId, {" in helper
    assert "behavior: 'configure-ui-action-arguments'" in helper
    assert "presentation: 'ui-action-args'" in helper
    assert "putParam('event_count', 'event count', 'number', eventCount);" in helper
    assert "window.ahSetUiNodeParam(actionNodeId, 'event_count', eventCount)" not in helper
    assert "capabilities: ['emit_event', 'drive_behavior', 'audit', 'presentation_trigger']" in helper
    assert "function materializeUiActionDispatchRoute" in helper
    assert "ensureUiActionBehaviorNode(ownerId, actionKey, actionValue" in helper
    assert "ensureUiActionHandlerRoute({" in helper
    assert "component: 'ui-surface-dispatch:' + (surfaceName || 'unknown')" in helper
    assert "const primaryActionAuthority = actionAuthorityFor('action', d.action" in projector
    assert "materializeUiActionDispatchRoute(id, 'action', effectiveAction" in projector
    assert "materializeUiActionDispatchRoute(id, 'submit_action', effectiveSubmitAction" in projector
    assert "materializeUiActionDispatchRoute(id, 'double_action', effectiveDoubleAction" in projector
    assert "materializeUiActionDispatchRoute(id, 'hover_action', effectiveHoverAction" in projector
    assert "materializeUiActionDispatchRoute(id, actionKey, authority.action" in projector
    assert "props['data-key-actions'] = keyActionEntries.map(entry => entry.keyName).join(' ')" in projector
    assert projector.count("if (dispatch.blocked) return;") >= 5
    assert "surface: dispatch.surfaceName || ''" in projector
    assert "action_node_id: runtime.action_node_id" in projector
    assert "action_param_node_id: runtime.action_param_node_id" in projector
    assert "action_owner_wire_id: runtime.action_owner_wire_id" in projector
    assert "action_param_wire_id: runtime.action_param_wire_id" in projector
    assert "dispatch_handler_node_id: route.handler_node_id" in projector
    assert "dispatch_action_handler_wire_id: route.action_handler_wire_id" in projector
    assert "dispatch_handler_target_wire_id: route.handler_target_wire_id" in projector
    merge = jsx[
        jsx.index("const mergeUiSurfaceIntoGraph ="):
        jsx.index("const grandMapSafeId =", jsx.index("const mergeUiSurfaceIntoGraph ="))
    ]
    assert "syncUiImportedActionRelationWireNode(w)" in merge


def test_imported_ui_surface_nodes_prematerialize_action_behavior_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const uiActionHydrationSpecsForNodeData ="):
        jsx.index("function materializeUiActionDispatchRoute", jsx.index("const uiActionHydrationSpecsForNodeData ="))
    ]
    merge = jsx[
        jsx.index("const mergeUiSurfaceIntoGraph ="):
        jsx.index("const grandMapSafeId =", jsx.index("const mergeUiSurfaceIntoGraph ="))
    ]

    assert "const uiActionHydrationSpecsForNodeData = (data) =>" in helper
    assert "if (d.action)" in helper
    assert "if (d.submit_action)" in helper
    assert "if (d.double_action)" in helper
    assert "if (d.hover_action)" in helper
    assert "specs.push({ key: 'hover_action', action: d.hover_action" in helper
    assert "if (d.key_actions && typeof d.key_actions === 'object')" in helper
    assert "key: 'key_action_' + _uiSafeId(keySpec.key || keyName, 'key')" in helper
    assert "function hydrateUiNodeActionBehavior(ownerId, component, options = {})" in helper
    assert "ensureUiActionBehaviorNode(ownerId, spec.key, spec.action, actionArgs" in helper
    assert "ensureUiActionHandlerRoute({" in helper
    assert "action_routes_by_key" in helper
    assert "['data-' + attrPrefix + '-node-id']" in helper
    assert "uiActionDispatchTargetNodeId(ownerId, actionArgs)" in helper
    assert "const actionHydrationGroupNodeIds = [];" in merge
    assert "hydrateUiNodeActionBehavior(n.id, 'ui-surface-import:' + importSurfaceName" in merge
    assert "setGrandMapInlineNodeField(rootNode, 'group_nodes', groupNodes);" in merge


def test_fallback_ui_nodes_materialize_action_behavior_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    fallback = jsx[
        jsx.index("const seedGrandMapFallbackUiNodes ="):
        jsx.index("const seedGrandMapSessionsHeaderFallbackNodes =", jsx.index("const seedGrandMapFallbackUiNodes ="))
    ]

    assert "const actionRelationGroupNodeIds = [];" in fallback
    assert "if (!item || !item.id || !(item.data && item.data.action)) return;" in fallback
    assert "ensureUiActionBehaviorNode(item.id, 'action', data.action, actionArgs" in fallback
    assert "event: 'hydrate'" in fallback
    assert "component: 'fallback-ui'" in fallback
    assert "ensureUiActionHandlerRoute({" in fallback
    assert "target_node_id: uiActionDispatchTargetNodeId(item.id, actionArgs)" in fallback
    assert "owner_node_id: item.id" in fallback
    assert "action_node_id: runtime.action_node_id || ''" in fallback
    assert "action_handler_node_id: route.handler_node_id || ''" in fallback
    assert "'data-action-node-id': runtime.action_node_id || ''" in fallback
    assert "setGrandMapInlineNodeField(root, 'group_nodes', root.data.group_nodes);" in fallback


def test_ui_node_action_handler_routes_are_nodes_and_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("function ensureUiActionHandlerRoute"):
        jsx.index("function projectUiNode", jsx.index("function ensureUiActionHandlerRoute"))
    ]

    assert "role: 'ui_action_handler'" in helper
    assert "kind: 'behavior'" in helper
    assert "capabilities: ['route_action', 'invoke_operation', 'audit', 'gate_execution']" in helper
    assert "w:ui-action-handler:" in helper
    assert "role: 'ui_action_handler_route'" in helper
    assert "relation: 'handled_by'" in helper
    assert "syncUiActionRelationWireNode(actionWireId, {" in helper
    assert "behavior: 'route-ui-action'" in helper
    assert "presentation: 'ui-action-handler'" in helper
    assert "role: 'ui_action_handler_target'" in helper
    assert "relation: 'operates_on'" in helper
    assert "syncUiActionRelationWireNode(targetWireId, {" in helper
    assert "behavior: 'operate-on-node'" in helper
    assert "presentation: 'ui-action-target'" in helper
    assert "putParam('event_count', 'event count', 'number', eventCount);" in helper
    assert "window.ahSetUiNodeParam(handlerId, 'event_count', eventCount)" not in helper


def test_ui_node_surface_click_emits_focus_without_overwriting_actions():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    projector = jsx[jsx.index("function projectUiNode"):jsx.index("const UiNodeSurface =")]

    assert "props.onClickCapture = (e) => {" in projector
    assert "window.__archhub_suppress_ui_focus_until" in projector
    assert "if (target && target.closest && target.closest('.lm-node')) return;" in projector
    suppressor = jsx[
        jsx.index("const uiSurfaceSuppressesFocusRoute ="):
        jsx.index("const uiFocusRouteAuthority =")
    ]
    assert "'node-connections-panel'" in suppressor
    assert "let focusRouteAuthority = uiFocusRouteAuthority(nodes, wires, id);" in projector
    assert "syncUiFocusRouteRelation(id, surfaceName || '')" in projector
    assert "if (!route.allowed) return;" in projector
    assert "new CustomEvent('lm-ui-node-focus'" in projector
    assert "node_id:id" in projector
    assert "focus_relation_wire_id:route.relationWire && route.relationWire.id || ''" in projector
    assert "props.onClick = emitAction;" in projector


def test_workspace_routes_ui_node_focus_to_existing_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    studio = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SField = ({ label }) =>", jsx.index("const StudioLM ="))
    ]
    workspace = jsx[
        jsx.index("const WorkspaceInner ="):
        jsx.index("// React.memo comparator for Workspace", jsx.index("const WorkspaceInner ="))
    ]

    assert "window.__archhub_focus_id = focusId || null;" in studio
    assert "const focusGraphNodeAtRoot = (ev) => {" in studio
    assert "window.addEventListener('lm-focus-node', focusGraphNodeAtRoot);" in studio
    assert "window.addEventListener('lm-ui-node-focus', focusGraphNodeAtRoot);" in studio
    assert "window.removeEventListener('lm-focus-node', focusGraphNodeAtRoot);" in studio
    assert "window.removeEventListener('lm-ui-node-focus', focusGraphNodeAtRoot);" in studio
    assert "setFocusId(nodeId);" in studio
    assert "const focusGraphNode = (ev) => {" in workspace
    assert "const canvasFocusEvent = 'lm-focus-node';" in workspace
    assert "window.addEventListener('lm-ui-node-focus', focusGraphNode)" in workspace
    assert "window.addEventListener(canvasFocusEvent, focusGraphNode)" in workspace
    assert "window.removeEventListener('lm-ui-node-focus', focusGraphNode)" in workspace
    assert "window.removeEventListener(canvasFocusEvent, focusGraphNode)" in workspace
    assert "const nodeId = ev && ev.detail && ev.detail.node_id;" in workspace
    assert "setFocusId(nodeId);" in workspace
    assert "const memoNode = allNodes.find(n => n.id === focusId);" in workspace
    assert "return ((window.__archhub_LM_GRAPH || {}).nodes || []).find(n => n && n.id === focusId) || null;" in workspace
    assert "<NodeRail node={focusNode} bumpGraph={bumpGraph} setFocusId={setFocusId}/>" in workspace


def test_new_canvas_command_mounts_workspace_or_records_failure():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    studio = jsx[
        jsx.index("const StudioLM ="):
        jsx.index("const SField = ({ label }) =>", jsx.index("const StudioLM ="))
    ]
    session_open = studio[
        studio.index("const session = openId"):
        studio.index("const openSession = React.useCallback", studio.index("const session = openId"))
    ]
    listeners = studio[
        studio.index("const recordSessionLaunchError ="):
        studio.index("window.addEventListener('lm-new-session'", studio.index("const recordSessionLaunchError ="))
    ]

    assert "|| {" in session_open
    assert "id: openId, title: openId" in session_open
    assert "window.__archhub_open_id = openId || null;" in session_open
    assert "window.__archhub_has_session = !!session;" in session_open
    assert "window.__archhub_session_ids = (LM_SESSIONS || []).map" in session_open
    assert "if (!LM_SESSIONS.find(s => s && s.id === id))" in studio
    assert "LM_SESSIONS.push({ id, title:id" in studio
    assert "window.__archhub_session_launch_error = {" in listeners
    assert "const onNewSession = () => {" in listeners
    assert "createSession('untitled').catch(e => recordSessionLaunchError('lm-new-session', e));" in listeners
    assert "const onCmdNewCanvas = () => {" in listeners
    assert "createSession().catch(e => recordSessionLaunchError('lm-action-new-canvas', e));" in listeners
    assert "openSession(sid).catch(e => recordSessionLaunchError('lm-action-open-session', e));" in listeners
    assert "openSession(sid).catch(e => recordSessionLaunchError('lm-open-session', e));" in listeners


def test_node_renderer_memo_repaints_when_node_params_change():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    canvas = jsx[
        jsx.index("const nodeRendererVisualSig ="):
        jsx.index("// React.memo comparator for NodeCanvas", jsx.index("const nodeRendererVisualSig ="))
    ]
    renderer = jsx[
        jsx.index("const NodeRenderer = React.memo"):
        jsx.index("const NodeStateDot =", jsx.index("const NodeRenderer = React.memo"))
    ]

    assert "const nodeRendererVisualSig = (n) =>" in canvas
    assert "params: (n.params || []).map(p => [p && p.k, p && p.v, p && p.type])" in canvas
    assert "config: n.config || {}" in canvas
    assert "dataValue: n.data && Object.prototype.hasOwnProperty.call(n.data, 'value')" in canvas
    assert "nodeVisualSig={nodeRendererVisualSig(n)}" in canvas
    assert "if (prev.nodeVisualSig !== next.nodeVisualSig) return false;" in renderer


def test_node_summary_panel_surface_emits_authority_header_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])
    payload = grand_map_ui_surface("node-summary-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:node-summary-panel"
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-summary-panel"]["data"]["children"] == [
        "ui:grandmap:node-summary-meta",
        "ui:grandmap:node-summary-title",
        "ui:grandmap:node-summary-subtitle",
    ]
    assert nodes["ui:grandmap:node-summary-icon"]["data"]["bind"] == "slot:node-summary-icon"
    assert nodes["ui:grandmap:node-summary-label"]["data"]["bind"] == "slot:node-summary-label"
    assert nodes["ui:grandmap:node-summary-title"]["data"]["bind"] == "slot:node-summary-title"
    assert nodes["ui:grandmap:node-summary-subtitle"]["data"]["bind"] == "slot:node-summary-subtitle"
    assert nodes["ui:grandmap:node-summary-subtitle"]["data"]["hidden_bind"] == "slot:node-summary-subtitle"
    assert nodes["ui:grandmap:node-summary-subtitle"]["data"]["hidden_value"] == ""


def test_node_summary_panel_is_hydrated_in_production_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_rail = jsx[jsx.index("const NodeRail ="):jsx.index("const ConversationRail")]
    summary_surface = jsx[
        jsx.index("const NodeSummarySurface ="):
        jsx.index("const NodeConnectionsSurface =", jsx.index("const NodeSummarySurface ="))
    ]
    shell_surface = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeRailShellSurface ="))
    ]

    assert "const NodeSummarySurface = ({ node, cat }) =>" in jsx
    assert "const seedGrandMapNodeSummaryPanelFallbackNodes = (node, cat) =>" in jsx
    assert "const seededRootId = seedGrandMapNodeSummaryPanelFallbackNodes(node, cat || {});" in jsx
    assert "if (seededRootId) rememberGrandMapSurfaceBuild(rootId, signature);" in jsx
    assert "if (grandMapSurfaceShouldReuse(rootId, signature)) return rootId;" in jsx
    assert "get_grand_map_ui_surface', 'node-summary-panel'" in jsx
    assert "const nodeSummaryRoot = useGrandMapSurfaceRoot(" in summary_surface
    assert "() => node ? ensureGrandMapNodeSummaryPanelNodes(node, cat || {}) : null" in summary_surface
    assert "const [, bumpNodeSummarySurface] = React.useReducer" not in summary_surface
    assert "<NodeSummarySurface node={railNode} cat={railCat}/>" in shell_surface
    assert "<NodeSummarySurface node={node} cat={cat}/>" not in shell_surface
    assert "<NodeSummarySurface node={node} cat={cat}/>" not in node_rail
    assert "{node.title}" not in node_rail


def test_node_summary_slots_wire_to_focused_node_parameters():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const rightRailSummaryWireId ="):
        jsx.index("const rightRailFocusWireId =", jsx.index("const rightRailSummaryWireId ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapNodeSummaryPanelTemplate ="):
        jsx.index("const seedGrandMapNodeSummaryPanelFallbackNodes =", jsx.index("const cloneGrandMapNodeSummaryPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodeSummaryPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodeSummaryPanelNodes =", jsx.index("const seedGrandMapNodeSummaryPanelFallbackNodes ="))
    ]
    prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailClones ="):
        jsx.index("let __grandMapUiHomeSlots", jsx.index("const pruneGrandMapFocusedRailClones ="))
    ]

    assert "const syncGrandMapNodeSummarySlotRelation =" in helper
    assert "materializeGrandMapParamNode(ownerNodeId, key, value)" in helper
    assert "window.ahSetUiNodeParam(ownerNodeId, key, value)" not in helper
    assert "relation_wire_family: 'right_rail_summary'" in helper
    assert "wire_family: 'right_rail_summary'" in helper
    assert "relation: 'right_rail_summary'" in helper
    assert "summary_owner_node_id: ownerNodeId" in helper
    assert "summary_param_node_id: sourceParamNodeId" in helper
    assert "summary_slot_node_id: slotNodeId" in helper
    assert "behavior: options.behavior || 'display-summary-field'" in helper
    assert "presentation: options.presentation || 'summary-header'" in helper
    assert "right_rail_summary_relation_node_id: relationNodeId || ''" in helper
    assert "const materializeSlotParamNodes = options.materialize_slot_param_nodes === true;" in helper
    assert "['right_rail_summary_relation_node_id', relationNodeId || '']" in helper
    assert "setGrandMapInlineNodeField(slotNode, field, fieldValue)" in helper
    assert "if (window.ahSetUiNodeParam && materializeSlotParamNodes) {" not in helper
    assert "{ slot:'slot:node-summary-title', key:'title'" in clone
    assert "{ slot:'slot:node-summary-subtitle', key:'sub'" in clone
    assert "{ slot:'slot:node-summary-icon', key:'summary_icon'" in clone
    assert "{ slot:'slot:node-summary-label', key:'summary_label'" in clone
    assert "syncGrandMapNodeSummarySlotRelation(mapId(entry.slot), node.id, entry.key, entry.value" in clone
    assert "runtime:cloneGrandMapNodeSummaryPanelTemplate" in clone
    assert "materialize_slot_param_nodes: false" in clone
    assert "syncGrandMapSurfaceStateSlots('node-summary-panel-' + sid, rootId, panelSlotMap" in clone
    assert "state_key: 'node_summary_panel_state_node_id'" in clone
    assert "syncGrandMapNodeSummarySlotRelation(mapId(entry.slot), node.id, entry.key, entry.value" in fallback
    assert "runtime:seedGrandMapNodeSummaryPanelFallbackNodes" in fallback
    assert "materialize_slot_param_nodes: false" in fallback
    assert "syncGrandMapSurfaceStateSlots('node-summary-panel-' + sid, rootId, panelSlotMap" in fallback
    assert "state_key: 'node_summary_panel_state_node_id'" in fallback
    assert "data.wire_family === 'right_rail_summary'" in prune
    assert "data.role === 'wire_layer' && data.wire_family === 'right_rail_summary'" in prune


def test_node_connections_panel_surface_emits_authority_pin_row_template(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])
    payload = grand_map_ui_surface("node-connections-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:node-connections-panel"
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:node-connections-panel"]["data"]["children"] == [
        "ui:grandmap:node-connections-heading",
        "ui:grandmap:node-connections-box",
    ]
    assert nodes["ui:grandmap:node-connections-heading"]["data"]["text"] == "CONNECTIONS"
    assert nodes["ui:grandmap:node-connection-pin-row"]["data"]["children"] == [
        "ui:grandmap:node-connection-pin-dot",
        "ui:grandmap:node-connection-pin-label",
        "ui:grandmap:node-connection-pin-line",
        "ui:grandmap:node-connection-pin-value",
        "ui:grandmap:node-connection-pin-anatomy",
        "ui:grandmap:node-connection-port-strip",
        "ui:grandmap:node-connection-junction-strip",
        "ui:grandmap:node-connection-layer-strip",
    ]
    assert nodes["ui:grandmap:node-connection-pin-label"]["data"]["bind"] == "slot:node-connection-pin-label"
    assert nodes["ui:grandmap:node-connection-pin-value"]["data"]["bind"] == "slot:node-connection-pin-value"
    assert nodes["ui:grandmap:node-connection-pin-anatomy"]["data"]["bind"] == "slot:node-connection-pin-anatomy"
    assert nodes["ui:grandmap:node-connection-port-strip"]["data"]["children"] == [
        "ui:grandmap:node-connection-port-chip",
        "ui:grandmap:node-connection-other-port-chip",
    ]
    assert nodes["ui:grandmap:node-connection-port-chip"]["data"]["tag"] == "button"
    assert nodes["ui:grandmap:node-connection-port-chip"]["data"]["bind"] == "slot:node-connection-port-label"
    assert nodes["ui:grandmap:node-connection-other-port-chip"]["data"]["tag"] == "button"
    assert nodes["ui:grandmap:node-connection-other-port-chip"]["data"]["bind"] == "slot:node-connection-other-port-label"
    assert nodes["ui:grandmap:node-connection-junction-strip"]["data"]["children"] == [
        "ui:grandmap:node-connection-junction-chip",
    ]
    assert nodes["ui:grandmap:node-connection-junction-chip"]["data"]["tag"] == "button"
    assert nodes["ui:grandmap:node-connection-junction-chip"]["data"]["bind"] == "slot:node-connection-junction-label"
    assert nodes["ui:grandmap:node-connection-layer-strip"]["data"]["children"] == [
        "ui:grandmap:node-connection-layer-chip",
    ]
    assert nodes["ui:grandmap:node-connection-layer-chip"]["data"]["tag"] == "button"
    assert nodes["ui:grandmap:node-connection-layer-chip"]["data"]["bind"] == "slot:node-connection-layer-label"


def test_node_connections_panel_is_hydrated_in_production_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    node_rail = jsx[jsx.index("const NodeRail ="):jsx.index("const ConversationRail")]
    connections_surface = jsx[
        jsx.index("const NodeConnectionsSurface ="):
        jsx.index("const EmptyNodeRailShellSurface =", jsx.index("const NodeConnectionsSurface ="))
    ]
    shell_surface = jsx[
        jsx.index("const NodeRailShellSurface ="):
        jsx.index("const NodeRail =", jsx.index("const NodeRailShellSurface ="))
    ]

    assert "const NodeConnectionsSurface = ({ node, setFocusId }) =>" in jsx
    assert "const nodeConnectionRowsFromGraphWires = (node) =>" in jsx
    assert "const nodeConnectionIsInspectorInternalWireFamily = (family) =>" in jsx
    assert "value === 'ui_slot_parameter' || value.indexOf('right_rail_') === 0" in jsx
    assert "const nodeConnectionIsInspectorInternalWireData = (...items) =>" in jsx
    assert "const nodeConnectionIsInspectorInternalParameterKey = (key) =>" in jsx
    assert "value === 'summary_icon'" in jsx
    assert "value === 'summary_label'" in jsx
    assert "role === 'ui_child_relation'" in jsx
    assert "role === 'ui_slot_parameter_relation'" in jsx
    assert "if (nodeConnectionIsInspectorInternalWireData(data, wireData, authorityWireData)) return;" in jsx
    assert "if (nodeConnectionIsInspectorInternalWireFamily(wireFamily)) return [];" in jsx
    assert "!nodeConnectionIsInspectorInternalParameterKey(key)" in jsx
    assert "!nodeConnectionIsInspectorInternalWireFamily(pd.relation_wire_family || '')" in jsx
    assert "const nodeConnectionPanelItems = (node) =>" in jsx
    assert "const NODE_CONNECTION_SECTION_LIMITS = {" in jsx
    assert "'declared-ports': 16" in jsx
    assert "'runtime-boundary': 20" in jsx
    assert "'app-relations': 12" in jsx
    assert "parameters: 8" in jsx
    assert "const limitedNodeConnectionPanelItems = (node, items) =>" in jsx
    assert "const nodeConnectionExpandRow = (nodeId, side, sectionKey, section, hiddenRows, currentLimit, totalRows) =>" in jsx
    assert "connection_expand_row: true" in jsx
    assert "action: 'node.connection.expand'" in jsx
    assert "section_label: section && section.label || sectionKey" in jsx
    assert "section_order: section && section.order || 999" in jsx
    assert "const NODE_CONNECTION_ALWAYS_VISIBLE_BOUNDARY_PORTS = new Set([" in jsx
    assert "'runtime_http_port'" in jsx
    assert "'host_registry'" in jsx
    assert "'host_live_count'" in jsx
    assert "const nodeConnectionItemAlwaysVisible = item =>" in jsx
    assert "NODE_CONNECTION_ALWAYS_VISIBLE_BOUNDARY_PORTS.has(String(item.source_boundary_port || ''))" in jsx
    assert "item.runtime_node_id && item.relation === 'evaluates_runtime'" in jsx
    assert "const alwaysVisible = allRows.filter(nodeConnectionItemAlwaysVisible);" in jsx
    assert "const normalLimit = Math.max(limit - alwaysVisible.length, 0);" in jsx
    assert "allRows.filter(row => !visibleSet.has(row))" in jsx
    assert "const expandNodeConnectionSectionLimit = (nodeId, side, sectionKey, nextLimit) =>" in jsx
    assert "const nodeConnectionLimitSignature = (nodeId) =>" in jsx
    assert "if (item && item.connection_expand_row) {" in jsx
    assert "key: item.section_key || (side === 'in' ? 'incoming-other' : 'outgoing-other')" in jsx
    assert "label: item.section_label || 'More connections'" in jsx
    assert "const nodeConnectionShouldUseCompactWirePanel = (node) =>" in jsx


    assert "(data.role === 'wire' && !nodeConnectionIsInspectorInternalWireFamily(data.wire_family || data.relation_wire_family || ''))" in jsx
    assert "const seedGrandMapNodeConnectionsPanelFallbackNodes = (node, options = {}) =>" in jsx
    assert "compact_wire_connections: !!options.compact_wire_connections" in jsx
    assert "__compact_wire_surface: compactWireConnections" in connections_surface
    assert "if (slots && slots.__compact_wire_surface) {" in jsx
    assert "const seededRootId = seedGrandMapNodeConnectionsPanelFallbackNodes(node);" in jsx
    assert "if (seededRootId) rememberGrandMapSurfaceBuild(rootId, signature);" in jsx
    assert "if (grandMapSurfaceShouldReuse(rootId, signature)) return rootId;" in jsx
    assert "get_grand_map_ui_surface', 'node-connections-panel'" in jsx
    assert "const DeferredRailSlot = ({ slotKey, delay = 1800, children }) =>" in jsx
    assert "const nodeRailShouldMountConnectionsImmediately = (node) =>" in jsx
    assert "data.role === 'wire' ||" in jsx
    assert "const connectionsSlot = nodeRailShouldMountConnectionsImmediately(railNode)" in shell_surface
    assert "[slotId('slot:node-rail-connections')]: connectionsSlot" in shell_surface
    assert "const nodeConnectionsRoot = useGrandMapSurfaceRoot(" in connections_surface
    assert "__surface_signature: pinSignature" in connections_surface
    assert "const [, bumpNodeConnectionsSurface] = React.useReducer" in connections_surface
    assert "const connectionItemsFull = node ? nodeConnectionPanelItems(node) : { receives: [], sends: [] };" in connections_surface
    assert "const connectionLimitSig = node ? nodeConnectionLimitSignature(node.id) : '';" in connections_surface
    assert "wire_node_id:item && item.wire_node_id || ''" in jsx
    assert "port_node_id:item && item.port_node_id || ''" in jsx
    assert "other_port_node_id:item && item.other_port_node_id || ''" in jsx
    assert "endpoint_role:item && item.endpoint_role || ''" in jsx
    assert "const connectionItems = node ? limitedNodeConnectionPanelItems(node, connectionItemsFull) : { receives: [], sends: [] };" in connections_surface
    assert "connectionLimitSig," in connections_surface
    assert "(connectionItems.receives || []).map" in connections_surface
    assert "(connectionItems.sends || []).map" in connections_surface
    assert "p && p.anatomy, p && p.port_node_id, p && p.other_port_node_id, p && p.junction_node_id" in connections_surface
    assert "p && p.path_junction_node_id, p && p.path_group_node_id, p && p.path_role, p && p.junction_nodes, p && p.layer_nodes" in connections_surface
    assert "p && p.runtime_node_id, p && p.param_node_id, p && p.parameter_key" in connections_surface
    assert "p && p.wire_family, p && p.source_boundary_port, p && p.boundary_port_node_id, p && p.boundary_state_node_id" in connections_surface
    assert "p && p.row_key, p && p.wire_id" in connections_surface
    assert "p && p.junction_node_id, p && p.path_junction_node_id, p && p.path_group_node_id, p && p.path_role, p && p.junction_nodes" in connections_surface
    assert "p && p.layer_nodes, p && p.runtime_node_id, p && p.param_node_id, p && p.parameter_key, p && p.runtime" in connections_surface
    assert "p && p.connection_expand_row, p && p.section_key, p && p.connection_next_limit, p && p.connection_total_count" in connections_surface
    assert "d.args.owner_node_id !== node.id" in connections_surface
    assert "__right_rail_connection_route_reused" in jsx
    assert "registerUiHostCapability('node.connection.focus'" in connections_surface
    assert "registerUiHostCapability('node.connection.expand'" in connections_surface
    assert "handler_node_id:authority && authority.handlerNode && authority.handlerNode.id || ''" in connections_surface
    assert "if (d.action === 'node.connection.expand') {" in connections_surface
    assert "expandNodeConnectionSectionLimit(" in connections_surface
    assert "d.args.connection_side || 'out'" in connections_surface
    assert "d.args.connection_next_limit || 9999" in connections_surface
    assert "bumpNodeConnectionsSurface();" in connections_surface
    assert "new CustomEvent('lm-graph-bump')" in connections_surface
    assert "setFocusId && setFocusId(targetNodeId)" in connections_surface
    assert "const focusDetail = {" in connections_surface
    assert "syncApplicationRightRailFocusContext(focusDetail);" in connections_surface
    assert "new CustomEvent('lm-focus-node'" in connections_surface
    assert "node_id: targetNodeId" in connections_surface
    assert "wire_id: d.args.wire_id || ''" in connections_surface
    assert "wire_edge_id: d.args.wire_edge_id || ''" in connections_surface
    assert "wire_family: d.args.wire_family || ''" in connections_surface
    assert "wire_node_id: d.args.wire_node_id || ''" in connections_surface
    assert "relation: d.args.relation || ''" in connections_surface
    assert "source_boundary_port: d.args.source_boundary_port || ''" in connections_surface
    assert "boundary_port_node_id: d.args.boundary_port_node_id || ''" in connections_surface
    assert "boundary_state_node_id: d.args.boundary_state_node_id || ''" in connections_surface
    assert "port_node_id: d.args.port_node_id || ''" in connections_surface
    assert "other_port_node_id: d.args.other_port_node_id || ''" in connections_surface
    assert "endpoint_node_id: d.args.endpoint_node_id || ''" in connections_surface
    assert "endpoint_role: d.args.endpoint_role || ''" in connections_surface
    assert "endpoint_port_id: d.args.endpoint_port_id || ''" in connections_surface
    assert "runtime_node_id: d.args.runtime_node_id || ''" in connections_surface
    assert "wire_layer_node_id: d.args.wire_layer_node_id || ''" in connections_surface
    assert "wire_layer: d.args.wire_layer || ''" in connections_surface
    assert "wire_layer_key: d.args.wire_layer_key || ''" in connections_surface
    assert "param_node_id: d.args.param_node_id || ''" in connections_surface
    assert "parameter_key: d.args.parameter_key || ''" in connections_surface
    assert "parameter_family: d.args.parameter_family || ''" in connections_surface
    assert "handler_node_id: route.handler_node_id || ''" in connections_surface
    assert "<NodeConnectionsSurface node={railNode} setFocusId={setFocusId}/>" in shell_surface
    assert "<NodeConnectionsSurface node={node}/>" not in node_rail
    assert "<PinRow" not in node_rail
    assert "CONNECTIONS" not in node_rail


def test_ui_projection_uses_ordered_child_relation_nodes_as_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    child_authority = jsx[
        jsx.index("const uiChildRelationWireId ="):
        jsx.index("const syncUiSurfaceDeclaredBindingRelations =")
    ]
    projection = jsx[
        jsx.index("function projectUiNode("):
        jsx.index("// THE WATCHER", jsx.index("function projectUiNode("))
    ]

    assert "const syncUiChildRelation =" in child_authority
    assert "const uiChildIdsFromRelations =" in child_authority
    assert "const syncUiSurfaceChildRelations =" in child_authority
    assert "role:'ui_child_relation'" in child_authority
    assert "const relationNodeId = upsertAppRelationWireNode(g, payload);" in child_authority
    assert "role:'wire_endpoint', endpoint:'from'" in child_authority
    assert "role:'wire_endpoint', endpoint:'to'" in child_authority
    assert "relationData.target_owner" in child_authority
    assert "relationData.child_order" in child_authority
    assert "gatePolicy !== 'deny'" in child_authority
    assert "return parentData.ui_child_relations_migrated === true ? []" in child_authority
    assert "node.data.ui_child_relations_migrated !== true" in child_authority
    assert "const childIds = uiChildIdsFromRelations(nodes, wires, id, d.children || []);" in projection
    assert "syncUiSurfaceChildRelations(nodes, rootId, wires, surface);" in projection
    assert "const kids = (d.children || []).map" not in projection


def test_ui_child_relation_authority_has_a_bounded_visual_verifier():
    verifier = (_APP.parent / "tools" / "verify_ui_child_relation_authority.cjs").read_text(encoding="utf-8")
    assert "ensureSelectedRelationWireFullAnatomy" in verifier
    assert "window.ahSetUiNodeParam(relationNodeId, 'target_owner', childBId);" in verifier
    assert "window.ahSetUiNodeParam(relationNodeId, 'gate_policy', 'deny');" in verifier
    assert "child survives projection deletion" in verifier
    assert "deleted child relation node fell back to children[]" in verifier
    assert "window.ahSetUiNodeParam(mountNodeId, 'render_slot', 'slot:authority:b');" in verifier
    assert "render slot survives projection deletion" in verifier
    assert "deleted render-slot relation node fell back to render_slot declaration" in verifier
    assert "window.ahSetUiNodeParam(bindingNodeId, 'source_node', bindingSourceBId);" in verifier
    assert "legacyProjection.data.role !== 'ui_binding_projection'" in verifier
    assert "binding survives projection deletion" in verifier
    assert "deleted binding relation node fell back to bind declaration or legacy projection" in verifier


def test_node_connections_panel_reads_real_graph_wires_as_rows():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const nodeConnectionRowsFromGraphWires ="):
        jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate =", jsx.index("const nodeConnectionRowsFromGraphWires ="))
    ]

    assert "const graphWires = g && Array.isArray(g.wires) ? g.wires : [];" in helper
    assert "const nodeConnectionEndpointNode = (endpoint) =>" in jsx
    assert "const nodeConnectionEndpointPort = (endpoint) =>" in jsx
    assert "Array.isArray(endpoint) ? endpoint[0] : (endpoint && endpoint.node)" in jsx
    assert "Array.isArray(endpoint) ? endpoint[1] : (endpoint && endpoint.port)" in jsx
    assert "w.from[0]" not in helper
    assert "w.to[0]" not in helper
    assert "w.from[1]" not in helper
    assert "w.to[1]" not in helper
    assert "const nodeConnectionLayerRows = (node) =>" in helper
    assert "const nodeConnectionParameterRows = (node) =>" in helper
    assert "if (data.role === 'wire' || data.role === 'selected_wire_path_wire') return [];" in helper
    assert "const paramFamily = nodeGraphOwnValue(paramNode, 'param_family', pd.param_family || '');" in helper
    assert "const graphReference = paramFamily === 'graph_reference'" in helper
    assert "&& !graphReference" in helper
    assert "const nodeConnectionStructuralOwnerRows = (node) =>" in helper
    assert "const nodeConnectionJunctionRows = (node) =>" in helper
    assert "const memberIds = nodeConnectionWireJunctionMemberNodeIds(g, nodeId);" in helper
    assert "const nodeConnectionSelectedPathRows = (node) =>" in helper
    assert "cd.role !== 'selected_wire_path_group'" in helper
    assert "label: 'relation path group'" in helper
    assert "path_group_node_id: pathGroupNode.id" in helper
    assert "relation: 'selected_relation_path_group'" in helper
    assert "const nodeConnectionSelectedPathGroupRows = (node) =>" in helper
    assert "data.role !== 'selected_wire_path_group'" in helper
    assert "const pathWireLayerNodeIds = new Set(" in helper
    assert "filter(childId => !pathWireLayerNodeIds.has(childId))" in helper
    assert "relation: 'contains_path_node'" in helper
    assert "path wire node" in helper
    assert "wireData.relation === 'selected_wire_path_wire_endpoint' ? 'path wire endpoint' : 'path wire'" in helper
    assert "const pathWireNodeId = wireData.path_wire_node || ('wire:selected-path:' + grandMapSafeId(wireId));" in helper
    assert "wire_node_id: pathWireNodeId" in helper
    assert "focus_node_id: graphNodes.some(n => n && n.id === pathWireNodeId) ? pathWireNodeId : targetNodeId" in helper
    assert "wireData.relation === 'selected_wire_path_wire_endpoint' ? 'path_wire_endpoint' : 'path_wire'" in helper
    assert "relation: wireData.relation || 'selected_wire_path'" in helper
    assert "const junctionNodes = isJunction ? [node] : nodeConnectionWireJunctionNodes(graphNodes, node);" in helper
    assert "const memberIds = nodeConnectionWireJunctionMemberNodeIds(g, junctionNode.id);" in helper
    assert "label: 'relation path junction'" in helper
    assert "label: selectedBranch ? 'selected branch' : 'path member'" in helper
    assert "relation: 'selected_relation_path'" in helper
    assert "path_role: selectedBranch ? 'selected_branch' : 'member_branch'" in helper
    assert "row_key: 'selected-path-member:' + junctionNode.id + ':' + memberId" in helper
    assert "path_junction_node_id: junctionNode.id" in helper
    assert "const authorityData = memberNode" in helper
    assert "const live = nodeConnectionLiveWireState(" in helper
    assert "const runtime = nodeConnectionWireRuntimeState(authorityData, live || {});" in helper
    assert "const runtimeNodeId = memberNode" in helper
    assert "syncWireRuntimeNode(g, memberId, runtime, rawValue, displayValue" in helper
    assert "const memberLayerChips = nodeConnectionWireLayerChips(graphNodes, memberNode);" in helper
    assert "nodeConnectionWireLayerChips(graphNodes, node).forEach(chip => {" in helper
    assert "nodeConnectionWireLayerChips(graphNodes, junctionNode).forEach(chip => {" in helper
    assert "label: 'junction ' + chip.label" in helper
    assert "junction_nodes: [{" in helper
    assert "layer_nodes: memberLayerChips" in helper
    assert "layer_nodes: nodeConnectionWireLayerChips(graphNodes, junctionNode)" in helper
    assert "data.param_nodes" in helper
    assert "const isPortNode = family === 'port' || !!pd.port_node;" in helper
    assert "label: isPortNode" in helper
    assert "relation: isPortNode ? 'owns_port' : 'owns_parameter'" in helper
    assert "isPortNode ? 'port node' : 'param node'" in helper
    assert "portDirection ? 'direction: ' + portDirection : ''" in helper
    assert "exposureScope ? 'scope: ' + exposureScope : ''" in helper
    assert "encryption ? 'encryption: ' + encryption : ''" in helper
    assert "const relationWireFamily = isPortNode ? (pd.relation_wire_family || '') : '';" in helper
    assert "const sourceBoundaryPort = relationWireFamily === 'application_boundary' ? (pd.port_id || '') : '';" in helper
    assert "wire_family: relationWireFamily" in helper
    assert "source_boundary_port: sourceBoundaryPort" in helper
    assert "boundary_port_node_id: relationWireFamily === 'application_boundary' ? paramNode.id : ''" in helper
    assert "owned_by_parameter_owner" in helper
    assert "contained_by_wire" in helper
    assert "evaluated_by_wire" in helper
    assert "label: 'owner node'" in helper
    assert "focus_node_id: ownerId" in helper
    assert "param_node_id: paramNode.id" in helper
    assert "parameter_key: key || ''" in helper
    assert "parameter_family: family" in helper
    assert "const endpointRows = nodeConnectionEndpointRows(node);" in helper
    assert "const parameterRows = nodeConnectionParameterRows(node);" in helper
    assert "declaredReceives.concat(ownerRows, endpointRows.receives, junctionRows.receives, selectedPathRows.receives, selectedPathGroupRows.receives, wireRows.receives)" in helper
    assert "declaredSends.concat(endpointRows.sends, wireRows.sends, junctionRows.sends, selectedPathRows.sends, selectedPathGroupRows.sends, layerRows, parameterRows)" in helper
    assert "if (!nodeId || (data.role !== 'wire' && data.role !== 'selected_wire_path_wire')) return [];" in helper
    assert "data.layer_nodes && typeof data.layer_nodes === 'object'" in helper
    assert "nd.role === 'wire_layer' && nd.owner === nodeId" in helper
    assert "focus_node_id: layerNode.id" in helper
    assert "String(wireId).indexOf('w:param:') === 0" in helper
    assert "if (data.role === 'wire_endpoint' || data.role === 'wire_layer_link' || data.role === 'wire_runtime_link') return;" in helper
    assert "const resolvePortEndpoint = (graphNodes, endpointNodeId, graphNodeById) =>" in jsx
    assert "endpointData.role === 'parameter' && endpointData.param_family === 'port'" in jsx
    assert "const nodeConnectionAnatomySummary = (wireData, edgeData) =>" in jsx
    assert "const nodeConnectionWireRuntimeState = (wireData, edgeData) =>" in jsx
    assert "const nodeGraphParameterValue = (graphNodes, ownerId, key) =>" in jsx
    assert "const nodeConnectionPortParameterEndpoint = (graphNodes, portNodeId) =>" in jsx
    assert "const nodeConnectionWireLayerAuthorityValues = (graphNodes, wireNode) =>" in jsx
    assert "const nodeConnectionWireAuthorityData = (graph, wireNode, presentationWire) =>" in jsx
    assert "Object.assign(source, nodeConnectionWireLayerAuthorityValues(graphNodes, wireNode))" in jsx
    assert "const nodeConnectionRuntimeDisplayValue = (value, runtime) =>" in jsx
    assert "const nodeConnectionTryBase64Decode = (value) =>" in jsx
    assert "const nodeConnectionCodecDecode = (value, codec) =>" in jsx
    assert "const nodeConnectionTransportPreviewValue = (transport) =>" in jsx
    assert "const nodeConnectionRuntimeDecodedPreview = (runtime) =>" in jsx
    assert "Object.prototype.hasOwnProperty.call(transport, 'decrypted_preview')" in jsx
    assert "const isDecodableCodec = codec === 'base64' || codec === 'base64:v1' || codec === 'json' || codec === 'json:v1';" in jsx
    assert "if (!hasSafeDecrypt && !isDecodableCodec) return '';" in jsx
    assert "return decodedPreview ? '[decrypted preview] ' + decodedPreview" in jsx
    assert "const nodeConnectionRuntimeSummary = (runtime) =>" in jsx
    assert "const syncWireRuntimeNode = (graph, wireNodeId, runtime, rawValue, displayValue, context) =>" in jsx
    assert "role: 'wire_runtime'" in jsx
    assert "role: 'wire_runtime_link'" in jsx
    assert "gatePolicy === 'deny' ? 'blocked'" in jsx
    assert "return 'base64:' + btoa(unescape(encodeURIComponent(raw)));" in jsx
    assert "return '[redacted]';" in jsx
    assert "decoded_preview: decodedPreview" in jsx
    assert "return '[hidden by presentation]';" in jsx
    assert "const nodeConnectionWireLayerChips = (graphNodes, wireNode) =>" in jsx
    assert "const nodeConnectionWireJunctionChips = (graphNodes, wireNode) =>" in jsx
    assert "layerData.role === 'wire_layer' && layerData.owner === wireNode.id" in jsx
    assert "const nodeConnectionRuntimeRowForWire = (graph, wireNode) =>" in jsx
    assert "label: 'runtime node'" in jsx
    assert "focus_node_id: runtimeNodeId" in jsx
    assert "runtime_node_id: runtimeNodeId" in jsx
    assert "wire_family: authorityData.wire_family || data.wire_family || ''" in jsx
    assert "source_boundary_port: authorityData.source_boundary_port || data.source_boundary_port || ''" in jsx
    assert "boundary_port_node_id: (authorityData.wire_family || data.wire_family || '') === 'application_boundary'" in jsx
    assert "boundary_state_node_id: (authorityData.wire_family || data.wire_family || '') === 'application_boundary'" in jsx
    assert "relation: 'evaluates_runtime'" in jsx
    assert "runtimeData.display_value || displayValue" in jsx
    assert "const nodeConnectionPortNodeLabel = (graphNodes, portNodeId, fallbackLabel) =>" in jsx
    assert "const valueParam = portNode && Array.isArray(portNode.params)" in jsx
    assert "|| data.value" in jsx
    assert "['gate', 'gate_policy']" in jsx
    assert "['codec', 'codec']" in jsx
    assert "['enc', 'encryption']" in jsx
    assert "['logic', 'behavior']" in jsx
    assert "['view', 'presentation']" in jsx
    assert "const relationNodeId = data.relation_node || '';" in helper
    assert "const logicalWireId = data.relation_wire_id || wireId;" in helper
    assert "const wireNode = graphNodeById.get(relationNodeId) || wireNodeByLogicalWireId.get(logicalWireId);" in helper
    assert "wireNodeByLogicalWireId.set(candidateData.wire_id, candidate);" in helper
    assert "const authorityWireData = wireNode" in helper
    assert "nodeConnectionWireAuthorityData(g, wireNode, wire)" in helper
    assert "const relation = data.relation || authorityWireData.relation || wireData.relation || data.role || '';" in helper
    assert "const fromEndpoint = resolvePortEndpoint(graphNodes, fromNode, graphNodeById);" in helper
    assert "const toEndpoint = resolvePortEndpoint(graphNodes, toNode, graphNodeById);" in helper
    assert "const sourcePortNodeId = authorityWireData.from_port_node || wireData.from_port_node || data.from_port_node || fromEndpoint.port_node_id || '';" in helper
    assert "const targetPortNodeId = authorityWireData.to_port_node || wireData.to_port_node || data.to_port_node || toEndpoint.port_node_id || '';" in helper
    assert "fromEndpoint.owner === nodeId" in helper
    assert "toEndpoint.owner === nodeId" in helper
    assert "const showMediatedTarget = !!(" in helper
    assert "const showMediatedSource = !!(" in helper
    assert "wire_node_id: wireNode && wireNode.id || ''" in helper
    assert "port_node_id: isOutgoing ? sourcePortNodeId : targetPortNodeId" in helper
    assert "other_port_node_id: isOutgoing ? targetPortNodeId : sourcePortNodeId" in helper
    assert "wire_edge_id: wireId" in helper
    assert "const runtime = nodeConnectionWireRuntimeState(authorityWireData, live || {});" in helper
    assert "const displayValue = nodeConnectionRuntimeDisplayValue(rawValue, runtime);" in helper
    assert "const wireFamily = authorityWireData.wire_family || data.wire_family || '';" in helper
    assert "const sourceBoundaryPort = authorityWireData.source_boundary_port || data.source_boundary_port || '';" in helper
    assert "const runtimeNodeId = syncWireRuntimeNode(g, wireNode && wireNode.id, runtime, rawValue, displayValue" in helper
    assert "wire_family: wireFamily" in helper
    assert "source_boundary_port: sourceBoundaryPort" in helper
    assert "focus_node_id: wireNode && wireNode.id || mediatedTargetId" in helper
    assert "boundary_port_node_id: wireFamily === 'application_boundary' ? sourcePortNodeId : ''" in helper
    assert "boundary_state_node_id: wireFamily === 'application_boundary' ? mediatedTargetId : ''" in helper
    assert "layerChips.push({" in helper
    assert "label: runtimeChipLabel" in helper
    assert "val: displayValue" in helper
    assert "raw_val: rawValue" in helper
    assert "runtime_node_id: runtimeNodeId" in helper
    assert "const anatomySummary = nodeConnectionAnatomySummary(authorityWireData, {});" in helper
    assert "anatomy: [anatomySummary, runtimeSummary].filter(Boolean).join(' | ')" in helper
    assert "runtime," in helper
    assert "junction_nodes: junctionChips" in helper
    assert "layer_nodes: layerChips" in helper
    assert "const capabilities = Array.isArray(layerData.capabilities) ? layerData.capabilities.join(',') : '';" in helper
    assert "const wireFamily = data.wire_family || '';" in helper
    assert "const sourceBoundaryPort = data.source_boundary_port || '';" in helper
    assert "wire_family: wireFamily" in helper


def test_selected_wire_connections_panel_has_explicit_cable_endpoint_sections():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const nodeConnectionRowsFromGraphWires ="):
        jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate =", jsx.index("const nodeConnectionRowsFromGraphWires ="))
    ]
    panel = jsx[
        jsx.index("const nodeConnectionPanelItems ="):
        jsx.index("const nodeConnectionLimitStore =", jsx.index("const nodeConnectionPanelItems ="))
    ]
    section = jsx[
        jsx.index("const nodeConnectionSectionForItem ="):
        jsx.index("const createNodeConnectionSectionState =", jsx.index("const nodeConnectionSectionForItem ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate ="):
        jsx.index("const seedGrandMapNodeConnectionsPanelFallbackNodes =", jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodeConnectionsPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodeConnectionsPanelNodes =", jsx.index("const seedGrandMapNodeConnectionsPanelFallbackNodes ="))
    ]

    assert "const nodeConnectionEndpointRows = (node) =>" in helper
    assert "data.role !== 'wire' && data.role !== 'selected_wire_path_wire'" in helper
    assert "nodeConnectionIsInspectorInternalWireFamily(wireFamily)" in helper
    assert "const authorityData = nodeConnectionWireAuthorityData(g, node, null);" in helper
    assert "const sourcePortNodeId = authorityData.from_port_node" in helper
    assert "const targetPortNodeId = authorityData.to_port_node" in helper
    assert "id: 'wire-endpoint:' + role + ':' + nodeId" in helper
    assert "label: role + ' endpoint'" in helper
    assert "focus_node_id: portNodeId || ownerId" in helper
    assert "endpoint_role: role" in helper
    assert "cable_endpoint: true" in helper
    assert "relation: role === 'source' ? 'wire_source_endpoint' : 'wire_target_endpoint'" in helper
    assert "if (sourceRow) rows.receives.push(sourceRow);" in helper
    assert "if (targetRow) rows.sends.push(targetRow);" in helper
    assert "const endpointRows = nodeConnectionEndpointRows(node);" in panel
    assert "endpointRows.receives" in panel
    assert "endpointRows.sends" in panel
    assert "'wire-endpoints': 8" in panel
    assert "'wire-runtime': 6" in panel
    assert "return { key:'wire-endpoints', label:'Wire endpoints', order:45 };" in section
    assert "return { key:'wire-runtime', label:'Runtime payload', order:58 };" in section
    assert "'data-cable-endpoint-role': port.endpoint_role || ''" in clone
    assert "'data-cable-endpoint-node-id': port.endpoint_node_id || ''" in clone
    assert "'data-cable-endpoint-port-id': port.endpoint_port_id || ''" in clone
    assert "'data-cable-endpoint-role':item.endpoint_role || ''" in fallback
    assert "'data-cable-endpoint-node-id':item.endpoint_node_id || ''" in fallback
    assert "'data-cable-endpoint-port-id':item.endpoint_port_id || ''" in fallback
    assert "source_boundary_port: sourceBoundaryPort" in helper
    assert "boundary_port_node_id: wireFamily === 'application_boundary' ? (data.from_port_node || '') : ''" in helper
    assert "boundary_state_node_id: wireFamily === 'application_boundary' ? (data.target_owner || data.target || data.to_node || '') : ''" in helper
    assert "wire_layer_node_id: layerNode.id" in helper
    assert "wire_layer_key: valueKey" in helper
    assert "'can: ' + capabilities" in helper
    assert "const runtimeRow = nodeConnectionRuntimeRowForWire(g, node);" in helper
    assert "return runtimeRow ? layerRows.concat([runtimeRow]) : layerRows;" in helper
    assert "rows.sends.push(row);" in helper
    assert "rows.receives.push(row);" in helper
    assert "const layerRows = nodeConnectionLayerRows(node);" in helper
    assert "const ownerRows = nodeConnectionStructuralOwnerRows(node);" in helper
    assert "const junctionRows = nodeConnectionJunctionRows(node);" in helper
    assert "const selectedPathRows = nodeConnectionSelectedPathRows(node);" in helper
    assert "const selectedPathGroupRows = nodeConnectionSelectedPathGroupRows(node);" in helper
    assert "declaredReceives.concat(ownerRows, endpointRows.receives, junctionRows.receives, selectedPathRows.receives, selectedPathGroupRows.receives, wireRows.receives)" in helper
    assert "declaredSends.concat(endpointRows.sends, wireRows.sends, junctionRows.sends, selectedPathRows.sends, selectedPathGroupRows.sends, layerRows, parameterRows)" in helper
    assert "nodeConnectionWireJunctionMemberNodeIds(g, nodeId)" in helper
    assert "relation: 'member_of_junction'" in helper
    assert "relation: 'contains_branch'" in helper
    assert "runtime_node_id: runtimeNodeId" in helper
    assert "runtime," in helper


def test_node_connections_wire_rows_are_focusable_ui_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate ="):
        jsx.index("const ensureGrandMapNodeConnectionsPanelNodes =", jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate ="))
    ]

    assert "const isWireRow = !!(port && port.wire_id);" in clone
    assert "const isExpandRow = !!(port && port.connection_expand_row);" in clone
    assert "const isFocusableRow = !!(port && (isExpandRow || port.wire_id || port.focus_node_id));" in clone
    assert "const rowAction = isExpandRow ? 'node.connection.expand' : 'node.connection.focus';" in clone
    assert "connection_side: port.connection_side || side" in clone
    assert "connection_next_limit: port.connection_next_limit || 9999" in clone
    assert "port.row_key || port.wire_id || port.id || port.label" in clone
    assert "copy.data.action = rowAction;" in clone
    assert "nodeConnectionPortNodeLabel(g.nodes, port.port_node_id" in clone
    assert "nodeConnectionPortNodeLabel(g.nodes, port.other_port_node_id" in clone
    assert "const rowLabelText = (port && (port.label || port.id)) || '';" in clone
    assert "const rowValueText = (port && (port.val || port.t)) || '';" in clone
    assert "const rowAnatomyText = (port && port.anatomy) || '';" in clone
    assert "delete copy.data.bind; copy.data.text = rowLabelText;" in clone
    assert "delete copy.data.bind; copy.data.text = rowValueText;" in clone
    assert "delete copy.data.bind; copy.data.text = rowAnatomyText;" in clone
    assert "delete copy.data.bind; copy.data.text = ownPortLabel;" in clone
    assert "delete copy.data.bind; copy.data.text = otherPortLabel;" in clone
    assert "node_id: port && (port.focus_node_id || port.wire_node_id || port.other_node_id)" in clone
    assert "endpoint_node_id: port.other_node_id" in clone
    assert "owner_node_id: node.id" in clone
    assert "wire_edge_id: port && port.wire_edge_id || ''" in clone
    assert "wire_family: port.wire_family || ''" in clone
    assert "wire_node_id: port && port.wire_node_id || ''" in clone
    assert "relation: port && port.relation || ''" in clone
    assert "source_boundary_port: port.source_boundary_port || ''" in clone
    assert "boundary_port_node_id: port.boundary_port_node_id || ''" in clone
    assert "boundary_state_node_id: port.boundary_state_node_id || ''" in clone
    assert "port_node_id: port && port.port_node_id || ''" in clone
    assert "other_port_node_id: port && port.other_port_node_id || ''" in clone
    assert "endpoint_role: port && port.endpoint_role || ''" in clone
    assert "endpoint_port_id: port && port.endpoint_port_id || ''" in clone
    assert "runtime_node_id: port && port.runtime_node_id || ''" in clone
    assert "param_node_id: port && port.param_node_id || ''" in clone
    assert "parameter_key: port && port.parameter_key || ''" in clone
    assert "'data-wire-id': port.wire_id" in clone
    assert "'data-wire-edge-id': port.wire_edge_id || ''" in clone
    assert "'data-wire-family': port.wire_family || ''" in clone
    assert "'data-source-boundary-port': port.source_boundary_port || ''" in clone
    assert "'data-boundary-port-node-id': port.boundary_port_node_id || ''" in clone
    assert "'data-boundary-state-node-id': port.boundary_state_node_id || ''" in clone
    assert "'data-wire-node-id': port.wire_node_id || ''" in clone
    assert "'data-wire-path-junction-node-id': port.path_junction_node_id || port.junction_node_id || ''" in clone
    assert "'data-wire-path-group-node-id': port.path_group_node_id || ''" in clone
    assert "'data-wire-path-role': port.path_role || ''" in clone
    assert "'data-wire-runtime-node-id': port.runtime_node_id || ''" in clone
    assert "'data-wire-layer-node-id': port.wire_layer_node_id || ''" in clone
    assert "'data-wire-layer-key': port.wire_layer_key || ''" in clone
    assert "'data-focus-node-id': port.focus_node_id || ''" in clone
    assert "'data-param-node-id': port.param_node_id || ''" in clone
    assert "'data-parameter-key': port.parameter_key || ''" in clone
    assert "'data-parameter-family': port.parameter_family || ''" in clone
    assert "'data-port-node-id': port.port_node_id || ''" in clone
    assert "'data-other-port-node-id': port.other_port_node_id || ''" in clone
    assert "'data-wire-gate-state': port.runtime && port.runtime.gate_state || ''" in clone
    assert "'data-wire-codec': port.runtime && port.runtime.codec || ''" in clone
    assert "'data-wire-encryption-state': port.runtime && port.runtime.encryption_state || ''" in clone
    assert "'data-connection-expand-row': isExpandRow ? 'true' : 'false'" in clone
    assert "'data-connection-section-key': port.section_key || ''" in clone
    assert "'data-connection-next-limit': port.connection_next_limit || ''" in clone
    assert "'data-connection-total-count': port.connection_total_count || ''" in clone
    assert "'data-wire-active': port.runtime && port.runtime.active ? 'true' : 'false'" in clone
    assert "tn.id === 'ui:grandmap:node-connection-port-chip'" in clone
    assert "node_id: port.port_node_id" in clone
    assert "other_port_node_id: port.other_port_node_id || ''" in clone
    assert "'data-port-focus-node-id': port.port_node_id || ''" in clone
    assert "tn.id === 'ui:grandmap:node-connection-other-port-chip'" in clone
    assert "node_id: port.other_port_node_id" in clone
    assert "other_port_node_id: port.port_node_id || ''" in clone
    assert "'data-port-focus-node-id': port.other_port_node_id || ''" in clone
    assert "const ensurePortChip = (baseId, labelText, focusNodeId, portSide, extraClass) =>" in clone
    assert "text: labelText" in clone
    assert "const portStripId = rowMapId('ui:grandmap:node-connection-port-strip');" in clone
    assert "const wireLayerNodes = Array.isArray(port && port.layer_nodes) ? port.layer_nodes : [];" in clone
    assert "const wireJunctionNodes = Array.isArray(port && port.junction_nodes) ? port.junction_nodes : [];" in clone
    assert "const ensureJunctionChip = (junction, index) =>" in clone
    assert "const junctionStripId = rowMapId('ui:grandmap:node-connection-junction-strip');" in clone
    assert "children:junctionChipIds" in clone
    assert "node_id:junction.id" in clone
    assert "'data-wire-junction-node-id': junction.id || ''" in clone
    assert "const ensureLayerChip = (layer, index) =>" in clone
    assert "'data-wire-layer-node-id': layer.id || ''" in clone
    assert "'data-wire-layer-key': layer.value_key || ''" in clone
    assert "text: layer.label || layer.layer || 'layer'" in clone
    assert "const layerStripId = rowMapId('ui:grandmap:node-connection-layer-strip');" in clone
    assert "children:layerChipIds" in clone
    assert "if (children.indexOf(layerStripId) < 0) children.push(layerStripId);" in clone
    assert "if (children.indexOf(junctionStripId) < 0) children.push(junctionStripId);" in clone
    assert "const ownChipId = ensurePortChip(" in clone
    assert "const otherChipId = ensurePortChip(" in clone
    assert "if (children.indexOf(portStripId) < 0)" in clone
    assert "const isExpandRow = !!(item && item.connection_expand_row);" in clone
    assert "const rowAction = isExpandRow ? 'node.connection.expand' : 'node.connection.focus';" in clone
    assert "connection_side: item.connection_side || side" in clone
    assert "connection_next_limit: item.connection_next_limit || 9999" in clone
    assert "action:isFocusableRow ? rowAction : ''" in clone
    assert "node_id:item && (item.focus_node_id || item.wire_node_id || item.other_node_id)" in clone
    assert "wire_family:item.wire_family || ''" in clone
    assert "source_boundary_port:item.source_boundary_port || ''" in clone
    assert "boundary_port_node_id:item.boundary_port_node_id || ''" in clone
    assert "boundary_state_node_id:item.boundary_state_node_id || ''" in clone
    assert "item.row_key || item.wire_id || item.id || item.label" in clone
    assert "const rowLabelText = (item && (item.label || item.id)) || '';" in clone
    assert "const rowValueText = (item && (item.val || item.t)) || '';" in clone
    assert "const rowAnatomyText = (item && item.anatomy) || '';" in clone
    assert "rowId + ':anatomy'" in clone
    assert "rowId + ':ports'" in clone
    assert "rowId + ':junctions'" in clone
    assert "rowId + ':layers'" in clone
    assert "text:junction.label || junction.topology || 'junction'" in clone
    assert "'data-wire-junction-node-id':junction.id || ''" in clone
    assert "text:layer.label || layer.layer || 'layer'" in clone
    assert "'data-wire-layer-node-id':layer.id || ''" in clone
    assert "'data-wire-gate-state':item.runtime && item.runtime.gate_state || ''" in clone
    assert "'data-wire-family':item.wire_family || ''" in clone
    assert "'data-source-boundary-port':item.source_boundary_port || ''" in clone
    assert "'data-boundary-port-node-id':item.boundary_port_node_id || ''" in clone
    assert "'data-boundary-state-node-id':item.boundary_state_node_id || ''" in clone
    assert "'data-wire-codec':item.runtime && item.runtime.codec || ''" in clone
    assert "'data-wire-encryption-state':item.runtime && item.runtime.encryption_state || ''" in clone
    assert "'data-connection-expand-row':isExpandRow ? 'true' : 'false'" in clone
    assert "'data-connection-section-key':item.section_key || ''" in clone
    assert "'data-connection-next-limit':item.connection_next_limit || ''" in clone
    assert "'data-connection-total-count':item.connection_total_count || ''" in clone
    assert "'data-wire-path-junction-node-id':item.path_junction_node_id || item.junction_node_id || ''" in clone
    assert "'data-wire-path-group-node-id':item.path_group_node_id || ''" in clone
    assert "'data-wire-path-role':item.path_role || ''" in clone
    assert "'data-wire-runtime-node-id':item.runtime_node_id || ''" in clone
    assert "'data-wire-layer-node-id':item.wire_layer_node_id || ''" in clone
    assert "'data-wire-layer-key':item.wire_layer_key || ''" in clone
    assert "'data-param-node-id':item.param_node_id || ''" in clone
    assert "'data-parameter-key':item.parameter_key || ''" in clone
    assert "'data-parameter-family':item.parameter_family || ''" in clone
    assert "'data-wire-active':item.runtime && item.runtime.active ? 'true' : 'false'" in clone
    assert "rowId + ':port'" in clone
    assert "rowId + ':other-port'" in clone


def test_node_connections_rows_wire_to_target_nodes_in_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const rightRailConnectionWireId ="):
        jsx.index("const rightRailFocusWireId =", jsx.index("const rightRailConnectionWireId ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate ="):
        jsx.index("const ensureGrandMapNodeConnectionsPanelNodes =", jsx.index("const cloneGrandMapNodeConnectionsPanelTemplate ="))
    ]
    fallback = jsx[
        jsx.index("const seedGrandMapNodeConnectionsPanelFallbackNodes ="):
        jsx.index("const ensureGrandMapNodeConnectionsPanelNodes =", jsx.index("const seedGrandMapNodeConnectionsPanelFallbackNodes ="))
    ]
    prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailClones ="):
        jsx.index("let __grandMapUiHomeSlots", jsx.index("const pruneGrandMapFocusedRailClones ="))
    ]
    panel_prune = jsx[
        jsx.index("const pruneGrandMapFocusedRailPanelClones ="):
        jsx.index("const __grandMapSurfaceBuildSignatures =", jsx.index("const pruneGrandMapFocusedRailPanelClones ="))
    ]

    assert "const rightRailConnectionTargetNodeId =" in helper
    assert "item.focus_node_id" in helper
    assert "item.wire_node_id" in helper
    assert "item.runtime_node_id" in helper
    assert "relation_wire_family: 'right_rail_connection'" in helper
    assert "wire_family: 'right_rail_connection'" in helper
    assert "relation: 'right_rail_connection'" in helper
    assert "connection_row_node_id: rowNodeId" in helper
    assert "represented_wire_node_id: item.wire_node_id || ''" in helper
    assert "represented_runtime_node_id: item.runtime_node_id || ''" in helper
    assert "represented_param_node_id: item.param_node_id || ''" in helper
    assert "gate_policy: options.gate_policy || runtime.gate_policy || 'allow-if-target-exists'" in helper
    assert "codec: options.codec || runtime.codec || 'none'" in helper
    assert "encryption: options.encryption || runtime.encryption || 'none'" in helper
    assert "behavior: options.behavior || 'focus-related-node'" in helper
    assert "presentation: options.presentation || 'connection-row'" in helper
    assert "const upsertRightRailConnectionWireNode = (graph, wire) =>" in helper
    assert "const relationNodeId = upsertRightRailConnectionWireNode(g, relationPayload);" in helper
    assert "materialize_wire_anatomy: false" in helper
    assert "anatomy_mode: materializeAnatomy ? 'layers' : 'none'" in helper
    assert "if (materializeAnatomy) ensureAppRelationWireLayerNodes(g, nodeId, {" in helper
    assert "materializeGrandMapParamNode(nodeId, key, payload[key] == null ? '' : payload[key])" not in helper
    assert "right_rail_connection_relation_node_id: relationNodeId || ''" in helper
    assert "['right_rail_connection_relation_node_id', relationNodeId || '']" in helper
    assert "setGrandMapInlineNodeField(rowNode, field, fieldValue)" in helper
    assert "window.ahSetUiNodeParam(rowNodeId, 'connection_target_node_id', targetNodeId)" not in helper
    assert "const nodeConnectionSectionForItem = (item, side) =>" in jsx
    assert "const materializeNodeConnectionSectionNodes = (graph, sectionState, side, mapId, writeNode, options = {}) =>" in jsx
    assert "const upsertNodeConnectionUiChildWireNode = (graph, wireId, wireData) =>" in jsx
    assert "const setNodeConnectionSectionWireValue = (graph, wireNodeId, key, value) =>" in jsx
    assert "node_connection_section_wire:true" in jsx
    assert "wireData.relation_node = relationNodeId || ''" in jsx
    assert "wire_family: 'node_connections_section_ui'" in jsx
    assert "setNodeConnectionSectionWireValue(LM_GRAPH, node.id, d.args.key, d.args.value)" in jsx
    assert "changed = setNodeConnectionSectionWireValue(g, node.id, key, args.value);" in jsx
    assert "(role === 'ui_child_relation' && family !== 'node_connections_section_ui')" in jsx
    assert "'data-connection-section':key" in jsx
    assert "schema_ref: 'archhub.ui.node_connection_section'" in jsx
    assert "action:'node.connection.focus'" in jsx
    assert "node_id:sectionId" in jsx
    assert "'data-focus-node-id':sectionId" in jsx
    assert ".ah-node-connection-section-node" in jsx
    assert "const sectionState = createNodeConnectionSectionState();" in clone
    assert "registerNodeConnectionSectionRow(sectionState, side, port, rowRoot);" in clone
    assert "materializeNodeConnectionSectionNodes(g, sectionState, 'in', mapId, writeSectionNode" in clone
    assert "if (receivesList) setGrandMapInlineNodeField(receivesList, 'children', receivesSections.sectionIds)" in clone
    assert "receivesSections.groupNodeIds" in clone
    assert "const sectionState = createNodeConnectionSectionState();" in fallback
    assert "registerNodeConnectionSectionRow(sectionState, side, item, rowId);" in fallback
    assert "materializeNodeConnectionSectionNodes(g, sectionState, 'in', mapId, addEl" in fallback
    assert "children:receivesSections.sectionIds" in fallback
    assert "receivesSections.groupNodeIds" in fallback
    assert "syncGrandMapNodeConnectionRowRelation(rowRoot, node.id, port, side" in clone
    assert "materialize_port_param_nodes: false" in clone
    assert "materialize_endpoint_wires: false" in clone
    assert "materialize_row_param_nodes: false" in clone
    assert "syncGrandMapSurfaceStateSlots('node-connections-panel-' + sid, rootId, panelSlotMap" in clone
    assert "state_key: 'node_connections_panel_state_node_id'" in clone
    assert "syncGrandMapSurfaceStateSlots('node-connection-pin-row-'" not in clone
    assert "state_key: 'node_connection_pin_row_state_node_id'" not in clone
    assert "'data-connection-relation-node': relationResult.relationNodeId || ''" in clone
    assert "connectionRelationGroupNodeIds.push(...(relationResult.groupNodeIds || []));" in clone
    assert "setGrandMapInlineNodeField(rootNode, 'group_nodes', groupNodes)" in clone
    assert "syncGrandMapNodeConnectionRowRelation(rowId, node.id, item, side" in fallback
    assert "materialize_port_param_nodes: false" in fallback
    assert "materialize_endpoint_wires: false" in fallback
    assert "materialize_row_param_nodes: false" in fallback
    assert "syncGrandMapSurfaceStateSlots('node-connections-panel-' + sid, rootId, panelSlotMap" in fallback
    assert "state_key: 'node_connections_panel_state_node_id'" in fallback
    assert "syncGrandMapSurfaceStateSlots('node-connection-pin-row-'" not in fallback
    assert "state_key: 'node_connection_pin_row_state_node_id'" not in fallback
    assert "runtime:seedGrandMapNodeConnectionsPanelFallbackNodes" in fallback
    assert "data.wire_family === 'right_rail_connection'" in prune
    assert "data.wire_family === 'node_connections_section_ui'" in prune
    assert "removeIds.has(data.target_owner)" in prune
    assert "addKeepId(window.__archhub_focus_id || '')" in prune
    assert "keepIds.forEach(id => removeIds.delete(id));" in prune
    assert "const keepIds = new Set();" in panel_prune
    assert "try { addKeepId(window.__archhub_focus_id || ''); } catch (_e) {}" in panel_prune
    assert "keepIds.has(data.connection_row_node_id)" in panel_prune
    assert "keepIds.forEach(id => removeIds.delete(id));" in panel_prune
    assert "data.role === 'wire_layer' && data.wire_family === 'right_rail_connection'" in prune
    assert "const workflowNodeConnectionSectionAnatomyForFocus = (graphNodes, focusId) =>" in jsx
    assert "const seenGraphNodeIds = new Set();" in jsx
    assert "(graphNodes || []).forEach(addLiveGraphNode);" in jsx
    assert "const workflowNodeConnectionSectionAnatomyNodesForFocus = (graphNodes, focusId) =>" in jsx
    assert "const workflowNodeConnectionSectionAnatomyWiresForFocus = (graphNodes, focusId, canvasNodeIds) =>" in jsx
    assert "anatomy_node_connection_section_role" in jsx
    assert "role: 'node_connection_section_incidence'" in jsx
    assert "projected_from_wire_id: wire.id || data.wire_id || ''" in jsx
    assert "incidence_role: 'source-to-relation'" in jsx
    assert "incidence_role: 'relation-to-target'" in jsx
    assert "const appendCanvasPort = (ports, id, label, t) =>" in jsx
    assert "clone.ins = appendCanvasPort(node.ins, 'from', 'from', 'node');" in jsx
    assert "clone.outs = appendCanvasPort(node.outs, 'to', 'to', 'node');" in jsx
    assert "clone.ins = appendCanvasPort(node.ins, 'parent', 'parent', 'node');" in jsx
    assert "clone.outs = appendCanvasPort(node.outs, 'child', 'child', 'node');" in jsx
    assert "const workflowWireSelectionForRenderedWire = (graph, wire, renderedIndex) =>" in jsx
    assert "projectedFromWireId" in jsx
    assert "realIndex = wires.findIndex(candidate => candidate && candidate.id === projectedFromWireId)" in jsx
    assert "const workflowWireSelectionMatchesRenderedWire = (selection, renderedWire) =>" in jsx
    assert "setSelectedWire(selection);" in jsx
    assert "selected_projected_wire_id" in jsx
    assert "selected_projected_from_wire_id" in jsx
    assert "selected_wire_incidence_role" in jsx
    assert "const isSel = workflowWireSelectionMatchesRenderedWire(selectedWire, w);" in jsx
    assert "const nodeConnectionSectionAnatomyNodes = React.useMemo(" in jsx
    assert "nodeConnectionSectionAnatomyNodes," in jsx
    assert "const nodeConnectionSectionAnatomyWires = React.useMemo(" in jsx
    assert "projectedSectionWireIds.has(w && w.id)" in jsx
    assert "return base.concat(nodeConnectionSectionAnatomyWires || []);" in jsx
    assert "nodeConnectionSectionAnatomyNodeIds:" in jsx
    assert "nodeConnectionSectionAnatomyWirePairs:" in jsx


def test_workflow_wire_materializer_does_not_promote_ui_support_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    inspector_filter = jsx[
        jsx.index("const nodeConnectionIsInspectorInternalWireData ="):
        jsx.index("const nodeConnectionIsInspectorInternalParameterKey =", jsx.index("const nodeConnectionIsInspectorInternalWireData ="))
    ]
    workflow_filter = jsx[
        jsx.index("const isVisibleWorkflowCanvasNode ="):
        jsx.index("const workflowWirePortSpec =", jsx.index("const isVisibleWorkflowCanvasNode ="))
    ]

    assert "role === 'ui_action_handler_target'" in inspector_filter
    assert "role === 'ui_action_operation_route'" in inspector_filter
    assert "if (data.role === 'ui_action') return false;" in workflow_filter
    assert "if (data.role === 'ui_action_handler') return false;" in workflow_filter
    assert "if (data.role === 'surface_state') return false;" in workflow_filter
    assert "if (nodeConnectionIsInspectorInternalWireData(data)) return false;" in workflow_filter
    assert "if (wireId.indexOf('w:ui-') === 0) return false;" in workflow_filter


def test_junction_layer_edits_refresh_member_branch_runtime_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    relation_edit = jsx[
        jsx.index("const refreshWorkflowWireRuntimeNode ="):
        jsx.index("const handleRelationNodeParamUpdateAction =", jsx.index("const refreshWorkflowWireRuntimeNode ="))
    ]

    assert "const refreshWorkflowWireJunctionMemberRuntimeNodes = (graph, junctionNodeId) =>" in relation_edit
    assert "nodeConnectionWireJunctionMemberNodeIds(g, junctionNodeId)" in relation_edit
    assert ".map(memberId => refreshWorkflowWireRuntimeNode(g, memberId))" in relation_edit
    assert "member_runtime_node_ids: runtimeNodeIds" in relation_edit
    assert "junctionNode.params.filter(p => !(p && p.k === 'member_runtime_node_ids'))" in relation_edit
    assert "window.ahSetUiNodeParam(junctionNodeId, 'member_runtime_node_ids', runtimeNodeIds);" not in relation_edit
    assert "['fanout', 'fanin', 'junction', 'hyperedge'].indexOf(String(refData.wire_topology || '')) >= 0" in relation_edit
    assert "refreshWorkflowWireJunctionMemberRuntimeNodes(graph || LM_GRAPH, ref.wireNodeId)" in relation_edit


def test_wire_runtime_nodes_are_owned_and_cleaned_with_wires():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    app_supernode = jsx[
        jsx.index("const ensureGrandMapApplicationSuperNode ="):
        jsx.index("const ensureGrandMapNewSessionActionNodes =", jsx.index("const ensureGrandMapApplicationSuperNode ="))
    ]
    workflow_materializer = jsx[
        jsx.index("const materializeWorkflowWireNodes ="):
        jsx.index("if (typeof window !== 'undefined')", jsx.index("const materializeWorkflowWireNodes ="))
    ]

    assert "setGrandMapInlineNodeField(owner, 'runtime_node', nodeId);" in jsx
    assert "window.ahSetUiNodeParam(wireNodeId, 'runtime_node', nodeId);" not in jsx
    assert "Object.keys(runtimeData).forEach(key => window.ahSetUiNodeParam(nodeId, key, runtimeData[key]));" not in jsx
    assert "['decoded_preview', 'decoded preview', 'text', runtimeData.decoded_preview]" in jsx
    assert "const decodedPreview = structuralRawValueOf(n, 'decoded_preview', '');" in jsx
    assert "if (decodedPreview !== '') return decodedPreview;" in jsx
    assert "'decoded_preview'," in jsx
    assert "const liveRelationWireRuntimeNodeIds = new Set();" in app_supernode
    assert "if (runtimeNodeId) liveRelationWireRuntimeNodeIds.add(runtimeNodeId);" in app_supernode
    assert "const staleRelationWireRuntimeNodeIds = new Set();" in app_supernode
    assert "data.role === 'wire_runtime' && n.data.wire_family === 'app_relation'" in app_supernode
    assert "relation_wire_runtime_node_ids: Array.from(liveRelationWireRuntimeNodeIds)" in app_supernode
    assert "if (data.role === 'wire_runtime_link' && stale.has(data.runtime_node)) return false;" in app_supernode
    assert "const liveWireRuntimeNodeIds = new Set();" in workflow_materializer
    assert "if (node && node.data && node.data.runtime_node) liveWireRuntimeNodeIds.add(node.data.runtime_node);" in workflow_materializer
    assert "const staleWorkflowRuntimeNodeIds = new Set();" in workflow_materializer
    assert "data.role === 'wire_runtime' && data.wire_family === 'workflow_wire'" in workflow_materializer
    assert "staleWorkflowRuntimeNodeIds.has(data.owner)" in workflow_materializer
    assert "if (data.role === 'wire_runtime_link' && stale.has(data.runtime_node)) return false;" in workflow_materializer


def test_connector_identity_panel_surface_emits_authority_header_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])
    payload = grand_map_ui_surface("connector-identity-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:connector-identity-panel"
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:connector-identity-panel"]["data"]["children"] == [
        "ui:grandmap:connector-identity-meta",
        "ui:grandmap:connector-identity-title",
        "ui:grandmap:connector-identity-subtitle",
    ]
    assert nodes["ui:grandmap:connector-identity-dot"]["data"]["tag"] == "span"
    assert nodes["ui:grandmap:connector-identity-label"]["data"]["bind"] == "slot:connector-identity-label"
    assert nodes["ui:grandmap:connector-identity-title"]["data"]["bind"] == "slot:connector-identity-title"
    assert nodes["ui:grandmap:connector-identity-subtitle"]["data"]["bind"] == "slot:connector-identity-subtitle"


def test_connector_connections_panel_surface_emits_flat_pin_rows(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])
    payload = grand_map_ui_surface("connector-connections-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:connector-connections-panel"
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:connector-connections-panel"]["data"]["children"] == [
        "ui:grandmap:connector-connections-heading",
        "ui:grandmap:connector-connections-box",
    ]
    assert nodes["ui:grandmap:connector-connections-heading"]["data"]["text"] == "CONNECTIONS"
    assert nodes["ui:grandmap:connector-connection-pin-row"]["data"]["children"] == [
        "ui:grandmap:connector-connection-pin-dot",
        "ui:grandmap:connector-connection-pin-label",
        "ui:grandmap:connector-connection-pin-line",
        "ui:grandmap:connector-connection-pin-value",
    ]
    assert "ui:grandmap:connector-connections-receives" not in nodes
    assert "ui:grandmap:connector-connections-sends" not in nodes


def test_connector_rail_shell_surface_emits_authority_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])
    payload = grand_map_ui_surface("connector-rail-shell", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:connector-rail-shell"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:connector-rail-shell"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:connector-rail-shell"]["data"]["cls"] == "ah-connector-rail-shell-node ah-scroll"
    assert nodes["ui:grandmap:connector-rail-shell"]["data"]["children"] == [
        "ui:grandmap:connector-rail-flush",
        "ui:grandmap:connector-rail-identity",
        "ui:grandmap:connector-rail-controls",
        "ui:grandmap:connector-rail-description",
        "ui:grandmap:connector-rail-destructive",
        "ui:grandmap:connector-rail-empty",
        "ui:grandmap:connector-rail-params",
        "ui:grandmap:connector-rail-run",
        "ui:grandmap:connector-rail-connections",
    ]
    assert nodes["ui:grandmap:connector-rail-flush"]["data"]["render_slot"] == "slot:connector-rail-flush"
    assert nodes["ui:grandmap:connector-rail-identity"]["data"]["render_slot"] == "slot:connector-rail-identity"
    assert nodes["ui:grandmap:connector-rail-controls"]["data"]["render_slot"] == "slot:connector-rail-controls"
    assert nodes["ui:grandmap:connector-rail-description"]["data"]["render_slot"] == "slot:connector-rail-description"
    assert nodes["ui:grandmap:connector-rail-destructive"]["data"]["render_slot"] == "slot:connector-rail-destructive"
    assert nodes["ui:grandmap:connector-rail-empty"]["data"]["render_slot"] == "slot:connector-rail-empty"
    assert nodes["ui:grandmap:connector-rail-params"]["data"]["render_slot"] == "slot:connector-rail-params"
    assert nodes["ui:grandmap:connector-rail-run"]["data"]["render_slot"] == "slot:connector-rail-run"
    assert nodes["ui:grandmap:connector-rail-connections"]["data"]["render_slot"] == "slot:connector-rail-connections"


def test_connector_controls_panel_surface_emits_host_and_operation_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("connector-controls-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:connector-controls-panel"
    assert payload["source_node_ids"] == ["ui_node_card"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:connector-controls-panel"]["data"]["children"] == [
        "ui:grandmap:connector-host-picker",
        "ui:grandmap:connector-host-badge-panel",
        "ui:grandmap:connector-op-picker",
    ]
    assert nodes["ui:grandmap:connector-host-picker"]["data"]["visible_when"] == {
        "bind": "slot:connector-host-state",
        "values": ["unconfigured"],
    }
    assert nodes["ui:grandmap:connector-host-badge-panel"]["data"]["visible_when"] == {
        "bind": "slot:connector-host-state",
        "values": ["configured"],
    }
    assert nodes["ui:grandmap:connector-op-picker"]["data"]["visible_when"] == {
        "bind": "slot:connector-host-state",
        "values": ["configured"],
    }
    assert nodes["ui:grandmap:connector-host-select"]["data"]["tag"] == "select"
    assert nodes["ui:grandmap:connector-host-select"]["data"]["bind"] == "slot:connector-host-value"
    assert nodes["ui:grandmap:connector-host-select"]["data"]["action"] == "connector.host.pick"
    assert nodes["ui:grandmap:connector-op-select"]["data"]["tag"] == "select"
    assert nodes["ui:grandmap:connector-op-select"]["data"]["bind"] == "slot:connector-op-value"
    assert nodes["ui:grandmap:connector-op-select"]["data"]["action"] == "connector.op.pick"
    assert nodes["ui:grandmap:connector-host-option"]["data"]["tag"] == "option"
    assert nodes["ui:grandmap:connector-op-option"]["data"]["tag"] == "option"
    assert "param:ui:grandmap:connector-controls-panel:cls" in nodes
    assert "param:ui:grandmap:connector-host-picker:visible_when" in nodes


def test_connector_run_panel_surface_emits_run_and_result_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("connector-run-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:connector-run-panel"
    assert payload["source_node_ids"] == ["ui_node_card"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:connector-run-panel"]["data"]["children"] == [
        "ui:grandmap:connector-run-button",
        "ui:grandmap:connector-result",
    ]
    assert nodes["ui:grandmap:connector-run-panel"]["data"]["visible_when"] == {
        "bind": "slot:connector-run-visible",
        "values": ["true"],
    }
    assert nodes["ui:grandmap:connector-run-button"]["data"]["tag"] == "button"
    assert nodes["ui:grandmap:connector-run-button"]["data"]["bind"] == "slot:connector-run-label"
    assert nodes["ui:grandmap:connector-run-button"]["data"]["action"] == "connector.run"
    assert nodes["ui:grandmap:connector-run-button"]["data"]["disabled_bind"] == "slot:connector-run-disabled"
    assert nodes["ui:grandmap:connector-result"]["data"]["visible_when"] == {
        "bind": "slot:connector-result-visible",
        "values": ["true"],
    }
    assert nodes["ui:grandmap:connector-result"]["data"]["state_bind"] == "slot:connector-result-state"
    assert nodes["ui:grandmap:connector-result-title"]["data"]["bind"] == "slot:connector-result-title"
    assert nodes["ui:grandmap:connector-result-message"]["data"]["bind"] == "slot:connector-result-message"
    assert "param:ui:grandmap:connector-run-panel:visible_when" in nodes


def test_connector_rail_actions_route_through_handler_and_operation_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    controls = jsx[
        jsx.index("const ConnectorControlsSurface ="):
        jsx.index("const ConnectorParamsSurface =", jsx.index("const ConnectorControlsSurface ="))
    ]
    params = jsx[
        jsx.index("const ConnectorParamsSurface ="):
        jsx.index("const ConnectorDescriptionSurface =", jsx.index("const ConnectorParamsSurface ="))
    ]
    run_panel = jsx[
        jsx.index("const ConnectorRunSurface ="):
        jsx.index("const ConnectorRailShellSurface =", jsx.index("const ConnectorRunSurface ="))
    ]

    assert "registerUiHostCapability('connector.host.pick'" in controls
    assert "registerUiHostCapability('connector.op.pick'" in controls
    assert "d.args.node_id !== node.id" in controls

    assert "registerUiHostCapability('connector.param.update'" in params
    assert "registerUiHostCapability('connector.param.promote'" in params
    assert "registerUiHostCapability('connector.param.focus'" in params
    assert "const paramNodeId = ensureGrandMapFocusableParamNode(node, key, currentValue, d.args.param_node_id);" in params
    assert "window.ahSetUiNodeParam(node.id, key, currentValue);" not in params
    assert "registerUiHostCapability('connector.params.tab'" in params
    assert "registerUiHostCapability('connector.param.multi.toggle'" in params
    assert "handler_node_id: authority.handlerNode && authority.handlerNode.id || ''" in params

    assert "registerUiHostCapability('connector.run'" in run_panel
    assert "d.args.node_id !== node.id" in run_panel
    assert "handler_node_id: authority.handlerNode && authority.handlerNode.id || ''" in run_panel


def test_connector_params_panel_surface_emits_typed_parameter_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
        {
            "key": "nodes",
            "title": "Nodes",
            "nodes": [
                _node("nodes_param_promote", "Param Promote"),
            ],
            "wires": [],
        },
        {
            "key": "canvas",
            "title": "Canvas",
            "nodes": [
                _node("canvas_inline_param_edit", "Inline Param Edit"),
            ],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("connector-params-panel", grand_map_path=grand_map)

    assert payload["ok"] is True, payload
    assert payload["root_id"] == "ui:grandmap:connector-params-panel"
    assert payload["source_node_ids"] == [
        "ui_node_card",
        "nodes_param_promote",
        "canvas_inline_param_edit",
    ]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:connector-params-panel"]["data"]["children"] == [
        "ui:grandmap:connector-param-tabs",
        "ui:grandmap:connector-param-heading",
        "ui:grandmap:connector-param-empty",
        "ui:grandmap:connector-param-list",
    ]
    assert nodes["ui:grandmap:connector-params-panel"]["data"]["visible_when"] == {
        "bind": "slot:connector-params-visible",
        "values": ["true"],
    }
    assert nodes["ui:grandmap:connector-param-tab"]["data"]["action"] == "connector.params.tab"
    assert nodes["ui:grandmap:connector-param-promote"]["data"]["action"] == "connector.param.promote"
    assert nodes["ui:grandmap:connector-param-label"]["data"]["action"] == "connector.param.focus"
    assert nodes["ui:grandmap:connector-param-text-input"]["data"]["action"] == "connector.param.update"
    assert nodes["ui:grandmap:connector-param-number-input"]["data"]["value_cast"] == "number"
    assert nodes["ui:grandmap:connector-param-slider-input"]["data"]["input_type"] == "range"
    assert nodes["ui:grandmap:connector-param-select"]["data"]["tag"] == "select"
    assert nodes["ui:grandmap:connector-param-option"]["data"]["tag"] == "option"
    assert nodes["ui:grandmap:connector-param-boolean-input"]["data"]["value_cast"] == "boolean"
    assert nodes["ui:grandmap:connector-param-textarea"]["data"]["tag"] == "textarea"
    assert nodes["ui:grandmap:connector-param-multi-option"]["data"]["action"] == (
        "connector.param.multi.toggle"
    )
    assert "param:ui:grandmap:connector-params-panel:visible_when" in nodes
    assert "param:ui:grandmap:connector-param-text-input:visible_when" in nodes
    assert "ui:grandmap:connector-param-row" in nodes["ui:grandmap:connector-params-panel"]["data"]["group_nodes"]


def test_connector_controls_and_params_clones_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    controls = jsx[
        jsx.index("const cloneGrandMapConnectorControlsPanelTemplate ="):
        jsx.index("const ensureGrandMapConnectorControlsPanelNodes =", jsx.index("const cloneGrandMapConnectorControlsPanelTemplate ="))
    ]
    params = jsx[
        jsx.index("const cloneGrandMapConnectorParamsPanelTemplate ="):
        jsx.index("const ensureGrandMapConnectorParamsPanelNodes =", jsx.index("const cloneGrandMapConnectorParamsPanelTemplate ="))
    ]

    assert "const panelSlotMap = {};" in controls
    assert "syncGrandMapSurfaceStateSlots('connector-controls-panel-' + sid, rootId, panelSlotMap" in controls
    assert "state_key: 'connector_controls_panel_state_node_id'" in controls
    assert "const panelSlotMap = {};" in params
    assert "syncGrandMapSurfaceStateSlots('connector-params-panel-' + sid, rootId, panelSlotMap" in params
    assert "state_key: 'connector_params_panel_state_node_id'" in params
    assert "const tabSlotMap = {" in params
    assert "syncGrandMapSurfaceStateSlots('connector-param-tab-' + sid + '-' + grandMapSafeId(group), tabId, tabSlotMap" in params
    assert "state_key: 'connector_param_tab_state_node_id'" in params
    assert "const rowSlotMap = {" in params
    assert "[slots.value]: valueForSlot" in params
    assert "syncGrandMapSurfaceStateSlots('connector-param-row-' + sid + '-' + psid, rowRoot, rowSlotMap" in params
    assert "state_key: 'connector_param_row_state_node_id'" in params


def test_connector_text_panel_surfaces_emit_bound_visibility_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "ui",
            "title": "UI",
            "nodes": [
                _node("ui_node_card", "Node Card Component"),
            ],
            "wires": [],
        },
    ])

    cases = [
        (
            "connector-description-panel",
            "ui:grandmap:connector-description-panel",
            "slot:connector-description-visible",
            "slot:connector-description",
        ),
        (
            "connector-destructive-warning",
            "ui:grandmap:connector-destructive-warning",
            "slot:connector-destructive-visible",
            "slot:connector-destructive-message",
        ),
        (
            "connector-empty-panel",
            "ui:grandmap:connector-empty-panel",
            "slot:connector-empty-visible",
            "slot:connector-empty-message",
        ),
    ]
    for surface, root_id, visible_slot, value_slot in cases:
        payload = grand_map_ui_surface(surface, grand_map_path=grand_map)
        assert payload["ok"] is True, payload
        assert payload["root_id"] == root_id
        assert payload["source_node_ids"] == ["ui_node_card"]
        nodes = {node["id"]: node for node in payload["nodes"]}
        assert nodes[root_id]["data"]["bind"] == value_slot
        assert nodes[root_id]["data"]["visible_when"] == {
            "bind": visible_slot,
            "values": ["true"],
        }
        assert f"param:{root_id}:visible_when" in nodes


def test_connector_rail_hydrates_identity_and_connections_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    identity_surface = jsx[
        jsx.index("const ConnectorIdentitySurface ="):
        jsx.index("const ConnectorConnectionsSurface =", jsx.index("const ConnectorIdentitySurface ="))
    ]
    connections_surface = jsx[
        jsx.index("const ConnectorConnectionsSurface ="):
        jsx.index("// \u2500\u2500\u2500 Connector property rail", jsx.index("const ConnectorConnectionsSurface ="))
    ]
    connector_rail = jsx[
        jsx.index("const ConnectorRail ="):
        jsx.index("// AgDR-0021 ai.plan", jsx.index("const ConnectorRail ="))
    ]

    assert "const ConnectorIdentitySurface = ({ node, host, conn, op, col }) =>" in jsx
    assert "const ConnectorConnectionsSurface = ({ node }) =>" in jsx
    assert "get_grand_map_ui_surface', 'connector-identity-panel'" in jsx
    assert "get_grand_map_ui_surface', 'connector-connections-panel'" in jsx
    assert "const rootId = useGrandMapSurfaceRoot(" in identity_surface
    assert "() => node ? ensureGrandMapConnectorIdentityPanelNodes(node, host, conn, op, col) : null" in identity_surface
    assert "const [, bumpConnectorIdentitySurface] = React.useReducer" not in identity_surface
    assert "const rootId = useGrandMapSurfaceRoot(" in connections_surface
    assert "() => node ? ensureGrandMapConnectorConnectionsPanelNodes(node) : null" in connections_surface
    assert "const [, bumpConnectorConnectionsSurface] = React.useReducer" not in connections_surface
    assert "<ConnectorIdentitySurface node={node} host={host} conn={conn} op={op} col={col}/>" in connector_rail
    assert "<ConnectorConnectionsSurface node={node}/>" in connector_rail
    assert "<PinRow" not in connector_rail


def test_connector_rail_shell_is_hydrated_in_production_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    shell_surface = jsx[
        jsx.index("const ConnectorRailShellSurface ="):
        jsx.index("const ConnectorRail =", jsx.index("const ConnectorRailShellSurface ="))
    ]
    connector_rail = jsx[
        jsx.index("const ConnectorRail ="):
        jsx.index("// AgDR-0021 ai.plan", jsx.index("const ConnectorRail ="))
    ]

    assert "const ConnectorRailShellSurface = ({ node, host, conn, op, col, running, slots }) =>" in jsx
    assert "get_grand_map_ui_surface', 'connector-rail-shell'" in jsx
    assert "slot:connector-rail-identity" in shell_surface
    assert "slot:connector-rail-controls" in shell_surface
    assert "slot:connector-rail-params" in shell_surface
    assert "slot:connector-rail-run" in shell_surface
    assert "slot:connector-rail-connections" in shell_surface
    assert "const rootId = useGrandMapSurfaceRoot(" in shell_surface
    assert "() => node ? ensureGrandMapConnectorRailShellNodes(node) : null" in shell_surface
    assert "const [, bumpConnectorRailShellSurface] = React.useReducer" not in shell_surface
    assert "shallow COPY" not in connector_rail
    assert "node = (LM_GRAPH.nodes || []).find(n => n.id === node.id) || node;" in connector_rail
    assert "<ConnectorRailShellSurface node={node} host={host} conn={conn} op={op} col={col} running={running}" in connector_rail
    assert "<aside className=\"ah-scroll\"" not in connector_rail


def test_connector_rail_hydrates_controls_and_run_from_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    controls_surface = jsx[
        jsx.index("const ConnectorControlsSurface ="):
        jsx.index("const ConnectorRunSurface =", jsx.index("const ConnectorControlsSurface ="))
    ]
    run_surface = jsx[
        jsx.index("const ConnectorRunSurface ="):
        jsx.index("// \u2500\u2500\u2500 Connector property rail", jsx.index("const ConnectorRunSurface ="))
    ]
    connector_rail = jsx[
        jsx.index("const ConnectorRail ="):
        jsx.index("// AgDR-0021 ai.plan", jsx.index("const ConnectorRail ="))
    ]

    assert "get_grand_map_ui_surface', 'connector-controls-panel'" in jsx
    assert "get_grand_map_ui_surface', 'connector-run-panel'" in jsx
    assert "const ConnectorControlsSurface = ({ node, conns, host, conn, ops, op, col, pickHost, pickOp }) =>" in jsx
    assert "ensureGrandMapConnectorControlsPanelNodes(node, conns || [], host, conn, ops || [], op, col)" in controls_surface
    assert "connector.host.pick" in controls_surface
    assert "connector.op.pick" in controls_surface
    assert "pickHost && pickHost(value)" in controls_surface
    assert "pickOp && pickOp(value)" in controls_surface
    assert "const ConnectorRunSurface = ({ node, op, running, res, col }) =>" in jsx
    assert "ensureGrandMapConnectorRunPanelNodes(node, op, running, res, col)" in run_surface
    assert "connector.run" in run_surface
    assert "lm-run-connector-op" in run_surface
    assert "controls: <ConnectorControlsSurface" in connector_rail
    assert "run: <ConnectorRunSurface node={node} op={op} running={running} res={res} col={col}/>" in connector_rail
    assert "onChange={(e) => pickHost(e.target.value)}" not in connector_rail
    assert "onChange={(e) => pickOp(e.target.value)}" not in connector_rail
    assert "lm-run-connector-op" not in connector_rail


def test_connector_rail_hydrates_params_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    params_surface = jsx[
        jsx.index("const ConnectorParamsSurface ="):
        jsx.index("const ConnectorRunSurface =", jsx.index("const ConnectorParamsSurface ="))
    ]
    connector_rail = jsx[
        jsx.index("const ConnectorRail ="):
        jsx.index("// AgDR-0021 ai.plan", jsx.index("const ConnectorRail ="))
    ]

    assert "get_grand_map_ui_surface', 'connector-params-panel'" in jsx
    assert "const ConnectorParamsSurface = ({ node, op, params, groupNames, activeTab, setTab, setParam, col }) =>" in jsx
    assert "useConnectorDynamicOptions(params || [])" in params_surface
    assert "ensureGrandMapConnectorParamsPanelNodes(" in params_surface
    assert "connector.param.update" in params_surface
    assert "materializeGrandMapParamNode(d.args.value_slot, 'value', d.args.value);" in params_surface
    assert "window.ahSetUiNodeParam(d.args.value_slot, 'value', d.args.value);" not in params_surface
    assert "connector.param.promote" in params_surface
    assert "connector.param.focus" in params_surface
    assert "connector.param.multi.toggle" in params_surface
    assert "connector.params.tab" in params_surface
    assert "lm-param-promote" in params_surface
    assert "params: <ConnectorParamsSurface" in connector_rail
    assert "<ParamField p={p} siblings={params}" not in connector_rail
    assert "groupNames.map(g =>" not in connector_rail


def test_connector_rail_hydrates_description_warning_and_empty_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    connector_rail = jsx[
        jsx.index("const ConnectorRail ="):
        jsx.index("// AgDR-0021 ai.plan", jsx.index("const ConnectorRail ="))
    ]

    assert "get_grand_map_ui_surface', 'connector-description-panel'" in jsx
    assert "get_grand_map_ui_surface', 'connector-destructive-warning'" in jsx
    assert "get_grand_map_ui_surface', 'connector-empty-panel'" in jsx
    assert "const ConnectorDescriptionSurface = ({ node, op }) =>" in jsx
    assert "const ConnectorDestructiveWarningSurface = ({ node }) =>" in jsx
    assert "const ConnectorEmptySurface = ({ node, host }) =>" in jsx
    assert "description: <ConnectorDescriptionSurface node={node} op={op}/>" in connector_rail
    assert "destructive: <ConnectorDestructiveWarningSurface node={node}/>" in connector_rail
    assert "empty: <ConnectorEmptySurface node={node} host={host}/>" in connector_rail
    assert "op && op.description &&" not in connector_rail
    assert "node.destructive &&" not in connector_rail
    assert "!host &&" not in connector_rail


def test_connector_remaining_clones_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    simple = jsx[
        jsx.index("const cloneGrandMapConnectorSimplePanelTemplate ="):
        jsx.index("const ensureGrandMapConnectorDescriptionPanelNodes =", jsx.index("const cloneGrandMapConnectorSimplePanelTemplate ="))
    ]
    run = jsx[
        jsx.index("const cloneGrandMapConnectorRunPanelTemplate ="):
        jsx.index("const ensureGrandMapConnectorRunPanelNodes =", jsx.index("const cloneGrandMapConnectorRunPanelTemplate ="))
    ]
    identity = jsx[
        jsx.index("const cloneGrandMapConnectorIdentityPanelTemplate ="):
        jsx.index("const ensureGrandMapConnectorIdentityPanelNodes =", jsx.index("const cloneGrandMapConnectorIdentityPanelTemplate ="))
    ]
    connections = jsx[
        jsx.index("const cloneGrandMapConnectorConnectionsPanelTemplate ="):
        jsx.index("const ensureGrandMapConnectorConnectionsPanelNodes =", jsx.index("const cloneGrandMapConnectorConnectionsPanelTemplate ="))
    ]

    assert "const clonedSlotMap = {};" in simple
    assert "syncGrandMapSurfaceStateSlots(surfaceName, rootId, clonedSlotMap" in simple
    assert "state_key: statePrefix + '_state_node_id'" in simple
    assert "syncGrandMapSurfaceStateSlots('connector-run-panel-' + sid, rootId, panelSlotMap" in run
    assert "state_key: 'connector_run_panel_state_node_id'" in run
    assert "syncGrandMapSurfaceStateSlots('connector-identity-panel-' + sid, rootId, panelSlotMap" in identity
    assert "state_key: 'connector_identity_panel_state_node_id'" in identity
    assert "const rowSlotMap = {" in connections
    assert "syncGrandMapSurfaceStateSlots('connector-connection-pin-row-' + sid + '-' + grandMapSafeId(key), rowRoot, rowSlotMap" in connections
    assert "state_key: 'connector_connection_pin_row_state_node_id'" in connections


def test_conversation_collapsed_rail_surface_emits_expand_action_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-collapsed-rail", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-collapsed-rail"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-collapsed-rail"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:conversation-collapsed-rail"]["data"]["cls"] == (
        "ah-conversation-collapsed-rail-node"
    )
    assert nodes["ui:grandmap:conversation-collapsed-rail"]["data"]["children"] == [
        "ui:grandmap:conversation-collapsed-chevron",
        "ui:grandmap:conversation-collapsed-label",
    ]
    assert nodes["ui:grandmap:conversation-collapsed-rail"]["data"]["action"] == (
        "conversation.rail.expand"
    )
    assert nodes["ui:grandmap:conversation-collapsed-label"]["data"]["bind"] == (
        "slot:conversation-collapsed-label"
    )


def test_conversation_runtime_clones_wire_visible_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helpers = jsx[
        jsx.index("const putGrandMapMappedSlotMap ="):
        jsx.index("const cloneGrandMapSessionCardTemplate =", jsx.index("const putGrandMapMappedSlotMap ="))
    ]
    assert "const mappedSlotMap = {};" in helpers
    assert "putGrandMapSlot(mappedId, label, slotMap[id]);" in helpers
    assert "const syncGrandMapMappedSurfaceState =" in helpers
    assert "syncGrandMapSurfaceStateSlots(surfaceName + '-' + sid, rootId, mappedSlotMap" in helpers

    expected = {
        "conversation-collapsed-rail": "cloneGrandMapConversationCollapsedRailTemplate",
        "conversation-header": "cloneGrandMapConversationHeaderTemplate",
        "conversation-day-divider": "cloneGrandMapConversationDayDividerTemplate",
        "conversation-tool-trace": "cloneGrandMapConversationToolTraceTemplate",
        "conversation-turn-actions": "cloneGrandMapConversationTurnActionsTemplate",
        "conversation-turn": "cloneGrandMapConversationTurnTemplate",
        "conversation-reasoning": "cloneGrandMapConversationReasoningTemplate",
        "conversation-reasoning-step": "cloneGrandMapConversationReasoningStepTemplate",
        "conversation-compact-expand": "cloneGrandMapConversationCompactExpandTemplate",
        "conversation-compact-turn": "cloneGrandMapConversationCompactTurnTemplate",
        "conversation-route-meta-row": "cloneGrandMapConversationRouteMetaRowTemplate",
        "conversation-search-empty": "cloneGrandMapConversationSearchEmptyTemplate",
        "conversation-search-bar": "cloneGrandMapConversationSearchBarTemplate",
        "conversation-reply-composer": "cloneGrandMapConversationReplyComposerTemplate",
        "conversation-expanded-turn": "cloneGrandMapConversationExpandedTurnTemplate",
        "conversation-fabricated-tool-warning": "cloneGrandMapFabricatedToolWarningTemplate",
        "conversation-code-block": "cloneGrandMapConversationCodeBlockTemplate",
        "conversation-clipped-text": "cloneGrandMapConversationClippedTextTemplate",
        "conversation-text-span": "cloneGrandMapConversationTextTemplate",
        "conversation-thinking": "cloneGrandMapConversationThinkingTemplate",
    }
    for surface, fn in expected.items():
        start = jsx.index("const " + fn + " =")
        end = jsx.index("const ensure", start)
        clone = jsx[start:end]
        assert "mappedSlotMap" in clone
        assert f"syncGrandMapMappedSurfaceState('{surface}', sid, rootId, mappedSlotMap)" in clone


def test_conversation_header_surface_emits_collapse_and_bound_title_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-header"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-header"]["data"]["children"] == [
        "ui:grandmap:conversation-header-meta",
        "ui:grandmap:conversation-header-title",
        "ui:grandmap:conversation-header-subtitle",
    ]
    assert nodes["ui:grandmap:conversation-header-meta"]["data"]["children"] == [
        "ui:grandmap:conversation-header-collapse",
        "ui:grandmap:conversation-header-icon",
        "ui:grandmap:conversation-header-label",
        "ui:grandmap:conversation-header-spacer",
        "ui:grandmap:conversation-header-count",
    ]
    assert nodes["ui:grandmap:conversation-header-collapse"]["data"]["action"] == (
        "conversation.rail.collapse"
    )
    assert nodes["ui:grandmap:conversation-header-label"]["data"]["bind"] == (
        "slot:conversation-label"
    )
    assert nodes["ui:grandmap:conversation-header-count"]["data"]["bind"] == (
        "slot:conversation-count"
    )
    assert nodes["ui:grandmap:conversation-header-title"]["data"]["bind"] == (
        "slot:conversation-title"
    )
    assert nodes["ui:grandmap:conversation-header-subtitle"]["data"]["bind"] == (
        "slot:conversation-subtitle"
    )


def test_conversation_day_divider_surface_emits_bound_label_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-day-divider", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-day-divider"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-day-divider"]["data"]["children"] == [
        "ui:grandmap:conversation-day-line-start",
        "ui:grandmap:conversation-day-label",
        "ui:grandmap:conversation-day-line-end",
    ]
    assert nodes["ui:grandmap:conversation-day-label"]["data"]["bind"] == (
        "slot:conversation-day-label"
    )


def test_conversation_tool_trace_surface_emits_row_template_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-tool-trace", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-tool-trace"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-tool-trace"]["data"]["children"] == [
        "ui:grandmap:conversation-tool-trace-title",
        "ui:grandmap:conversation-tool-trace-list",
    ]
    assert nodes["ui:grandmap:conversation-tool-trace-title"]["data"]["text"] == (
        "TOOL TRACE"
    )
    assert nodes["ui:grandmap:conversation-tool-trace-row"]["data"]["bind"] == (
        "slot:conversation-tool-trace-row"
    )


def test_conversation_turn_actions_surface_emits_action_buttons(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-turn-actions", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-turn-actions"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-turn-actions"]["data"]["children"] == [
        "ui:grandmap:conversation-turn-regen",
        "ui:grandmap:conversation-turn-branch",
        "ui:grandmap:conversation-turn-edit",
        "ui:grandmap:conversation-turn-copy",
        "ui:grandmap:conversation-turn-spacer",
        "ui:grandmap:conversation-turn-tokens",
    ]
    assert nodes["ui:grandmap:conversation-turn-regen"]["data"]["action"] == (
        "conversation.turn.regen"
    )
    assert nodes["ui:grandmap:conversation-turn-branch"]["data"]["action"] == (
        "conversation.turn.branch"
    )
    assert nodes["ui:grandmap:conversation-turn-edit"]["data"]["action"] == (
        "conversation.turn.edit"
    )
    assert nodes["ui:grandmap:conversation-turn-copy"]["data"]["action"] == (
        "conversation.turn.copy"
    )
    assert nodes["ui:grandmap:conversation-turn-tokens"]["data"]["bind"] == (
        "slot:conversation-turn-tokens"
    )


def test_conversation_turn_surface_emits_shell_and_render_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-turn", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-turn"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-turn"]["data"]["children"] == [
        "ui:grandmap:conversation-turn-avatar",
        "ui:grandmap:conversation-turn-content",
    ]
    assert nodes["ui:grandmap:conversation-turn-content"]["data"]["children"] == [
        "ui:grandmap:conversation-turn-meta",
        "ui:grandmap:conversation-turn-body",
        "ui:grandmap:conversation-turn-reasoning",
        "ui:grandmap:conversation-turn-actions-mount",
    ]
    assert nodes["ui:grandmap:conversation-turn-meta"]["data"]["children"] == [
        "ui:grandmap:conversation-turn-name",
        "ui:grandmap:conversation-turn-time",
    ]
    assert nodes["ui:grandmap:conversation-turn-avatar"]["data"]["bind"] == (
        "slot:conversation-turn-avatar"
    )
    assert nodes["ui:grandmap:conversation-turn-avatar"]["data"]["state_bind"] == (
        "slot:conversation-turn-role"
    )
    assert nodes["ui:grandmap:conversation-turn-name"]["data"]["bind"] == (
        "slot:conversation-turn-name"
    )
    assert nodes["ui:grandmap:conversation-turn-time"]["data"]["bind"] == (
        "slot:conversation-turn-time"
    )
    assert nodes["ui:grandmap:conversation-turn-body"]["data"]["render_slot"] == (
        "slot:conversation-turn-body"
    )
    assert nodes["ui:grandmap:conversation-turn-reasoning"]["data"]["render_slot"] == (
        "slot:conversation-turn-reasoning"
    )
    assert nodes["ui:grandmap:conversation-turn-actions-mount"]["data"]["render_slot"] == (
        "slot:conversation-turn-actions"
    )


def test_conversation_reasoning_surface_emits_openable_step_slot(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-reasoning", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-reasoning"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["slot:conversation-reasoning-open"]["data"]["value"] == "false"
    assert nodes["slot:conversation-reasoning-chevron"]["data"]["value"] == ">"
    root = nodes["ui:grandmap:conversation-reasoning"]["data"]
    assert root["children"] == [
        "ui:grandmap:conversation-reasoning-toggle",
        "ui:grandmap:conversation-reasoning-panel",
    ]
    toggle = nodes["ui:grandmap:conversation-reasoning-toggle"]["data"]
    assert toggle["action"] == "conversation.reasoning.toggle"
    assert toggle["state_bind"] == "slot:conversation-reasoning-open"
    panel = nodes["ui:grandmap:conversation-reasoning-panel"]["data"]
    assert panel["render_slot"] == "slot:conversation-reasoning-steps"
    assert panel["visible_when"] == {
        "bind": "slot:conversation-reasoning-open",
        "value": "true",
    }


def test_conversation_reasoning_step_surface_emits_bound_step_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-reasoning-step", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-reasoning-step"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-reasoning-step"]["data"]
    assert root["children"] == [
        "ui:grandmap:conversation-reasoning-step-index",
        "ui:grandmap:conversation-reasoning-step-text",
    ]
    assert nodes["ui:grandmap:conversation-reasoning-step-index"]["data"]["bind"] == (
        "slot:conversation-reasoning-step-index"
    )
    assert nodes["ui:grandmap:conversation-reasoning-step-text"]["data"]["bind"] == (
        "slot:conversation-reasoning-step-text"
    )


def test_conversation_compact_expand_surface_emits_node_action_button(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-compact-expand", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-compact-expand"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-compact-expand"]["data"]
    assert root["tag"] == "button"
    assert root["action"] == "conversation.compact.expand"
    assert root["children"] == [
        "ui:grandmap:conversation-compact-expand-icon",
        "ui:grandmap:conversation-compact-expand-count",
        "ui:grandmap:conversation-compact-expand-spacer",
        "ui:grandmap:conversation-compact-expand-action",
    ]
    assert nodes["ui:grandmap:conversation-compact-expand-count"]["data"]["bind"] == (
        "slot:conversation-compact-expand-count"
    )
    assert nodes["ui:grandmap:conversation-compact-expand-action"]["data"]["bind"] == (
        "slot:conversation-compact-expand-action"
    )


def test_conversation_compact_turn_surface_emits_preview_row_shell(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-compact-turn", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-compact-turn"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-compact-turn"]["data"]
    assert root["children"] == [
        "ui:grandmap:conversation-compact-turn-avatar",
        "ui:grandmap:conversation-compact-turn-content",
    ]
    assert nodes["ui:grandmap:conversation-compact-turn-avatar"]["data"]["bind"] == (
        "slot:conversation-compact-turn-avatar"
    )
    assert nodes["ui:grandmap:conversation-compact-turn-avatar"]["data"]["state_bind"] == (
        "slot:conversation-compact-turn-role"
    )
    assert nodes["ui:grandmap:conversation-compact-turn-name"]["data"]["visible_when"] == {
        "bind": "slot:conversation-compact-turn-role",
        "value": "assistant",
    }
    assert nodes["ui:grandmap:conversation-compact-turn-body"]["data"]["render_slot"] == (
        "slot:conversation-compact-turn-body"
    )
    assert nodes["ui:grandmap:conversation-compact-turn-reasoning"]["data"]["render_slot"] == (
        "slot:conversation-compact-turn-reasoning"
    )
    assert nodes["ui:grandmap:conversation-compact-turn-route"]["data"]["render_slot"] == (
        "slot:conversation-compact-turn-route"
    )


def test_conversation_route_meta_surfaces_emit_container_and_rows(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    meta = grand_map_ui_surface("conversation-route-meta", grand_map_path=grand_map)
    row = grand_map_ui_surface("conversation-route-meta-row", grand_map_path=grand_map)

    assert meta["ok"] is True
    assert meta["root_id"] == "ui:grandmap:conversation-route-meta"
    meta_nodes = {node["id"]: node for node in meta["nodes"]}
    meta_root = meta_nodes["ui:grandmap:conversation-route-meta"]["data"]
    assert meta_root["render_slot"] == "slot:conversation-route-meta-rows"
    assert meta_root["test_id"] == "route-meta"

    assert row["ok"] is True
    assert row["root_id"] == "ui:grandmap:conversation-route-meta-row"
    row_nodes = {node["id"]: node for node in row["nodes"]}
    assert row_nodes["ui:grandmap:conversation-route-meta-row"]["data"]["children"] == [
        "ui:grandmap:conversation-route-meta-row-arrow",
        "ui:grandmap:conversation-route-meta-row-text",
    ]
    assert row_nodes["ui:grandmap:conversation-route-meta-row-arrow"]["data"]["text"] == "⇉"
    assert row_nodes["ui:grandmap:conversation-route-meta-row-text"]["data"]["bind"] == (
        "slot:conversation-route-meta-row-text"
    )


def test_conversation_node_scrollback_and_search_empty_surfaces(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    scrollback = grand_map_ui_surface("conversation-node-scrollback", grand_map_path=grand_map)
    empty = grand_map_ui_surface("conversation-search-empty", grand_map_path=grand_map)

    assert scrollback["ok"] is True
    assert scrollback["root_id"] == "ui:grandmap:conversation-node-scrollback"
    scroll_nodes = {node["id"]: node for node in scrollback["nodes"]}
    scroll_root = scroll_nodes["ui:grandmap:conversation-node-scrollback"]["data"]
    assert scroll_root["cls"] == "ah-conversation-node-scrollback-node ah-scroll"
    assert scroll_root["render_slot"] == "slot:conversation-node-scrollback-content"

    assert empty["ok"] is True
    assert empty["root_id"] == "ui:grandmap:conversation-search-empty"
    empty_nodes = {node["id"]: node for node in empty["nodes"]}
    assert empty_nodes["slot:conversation-search-empty-query"]["type"] == "data.constant"
    assert empty_nodes["ui:grandmap:conversation-search-empty"]["data"]["children"] == [
        "ui:grandmap:conversation-search-empty-prefix",
        "ui:grandmap:conversation-search-empty-query",
        "ui:grandmap:conversation-search-empty-suffix",
    ]
    assert empty_nodes["ui:grandmap:conversation-search-empty-query"]["data"]["bind"] == (
        "slot:conversation-search-empty-query"
    )


def test_conversation_ai_body_wrapper_surfaces_are_slotted_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    expanded = grand_map_ui_surface("conversation-ai-body-expanded", grand_map_path=grand_map)
    compact = grand_map_ui_surface("conversation-ai-body-compact", grand_map_path=grand_map)

    assert expanded["ok"] is True
    assert expanded["root_id"] == "ui:grandmap:conversation-ai-body-expanded"
    expanded_nodes = {node["id"]: node for node in expanded["nodes"]}
    expanded_root = expanded_nodes["ui:grandmap:conversation-ai-body-expanded"]["data"]
    assert expanded_root["cls"] == "ah-conversation-ai-body-expanded-node"
    assert expanded_root["style"] == {"marginTop": 9, "display": "flex", "flexDirection": "column", "gap": 7}
    assert expanded_root["children"] == [
        "ui:grandmap:conversation-ai-body-expanded-search",
        "ui:grandmap:conversation-ai-body-expanded-scrollback",
        "ui:grandmap:conversation-ai-body-expanded-reply",
    ]
    assert expanded_nodes["ui:grandmap:conversation-ai-body-expanded-search"]["data"]["render_slot"] == (
        "slot:conversation-ai-body-search"
    )
    assert expanded_nodes["ui:grandmap:conversation-ai-body-expanded-scrollback"]["data"]["render_slot"] == (
        "slot:conversation-ai-body-scrollback"
    )
    assert expanded_nodes["ui:grandmap:conversation-ai-body-expanded-reply"]["data"]["render_slot"] == (
        "slot:conversation-ai-body-reply"
    )

    assert compact["ok"] is True
    assert compact["root_id"] == "ui:grandmap:conversation-ai-body-compact"
    compact_nodes = {node["id"]: node for node in compact["nodes"]}
    compact_root = compact_nodes["ui:grandmap:conversation-ai-body-compact"]["data"]
    assert compact_root["style"] == {"marginTop": 9, "display": "flex", "flexDirection": "column", "gap": 9}
    assert compact_root["children"] == [
        "ui:grandmap:conversation-ai-body-compact-expand",
        "ui:grandmap:conversation-ai-body-compact-turns",
    ]
    assert compact_nodes["ui:grandmap:conversation-ai-body-compact-expand"]["data"]["render_slot"] == (
        "slot:conversation-ai-body-compact-expand"
    )
    assert compact_nodes["ui:grandmap:conversation-ai-body-compact-turns"]["data"]["render_slot"] == (
        "slot:conversation-ai-body-compact-turns"
    )


def test_conversation_search_bar_surface_emits_input_and_clear_actions(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-search-bar", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-search-bar"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-search-bar"]["data"]
    assert root["children"] == [
        "ui:grandmap:conversation-search-icon",
        "ui:grandmap:conversation-search-input",
        "ui:grandmap:conversation-search-count",
        "ui:grandmap:conversation-search-clear",
    ]
    assert nodes["ui:grandmap:conversation-search-icon"]["data"]["tag"] == "svg"
    search_input = nodes["ui:grandmap:conversation-search-input"]["data"]
    assert search_input["tag"] == "input"
    assert search_input["bind"] == "slot:conversation-search-query"
    assert search_input["action"] == "conversation.search.update"
    assert search_input["placeholder"] == "Search this conversation..."
    assert nodes["ui:grandmap:conversation-search-count"]["data"]["bind"] == (
        "slot:conversation-search-count"
    )
    clear = nodes["ui:grandmap:conversation-search-clear"]["data"]
    assert clear["action"] == "conversation.search.clear"
    assert clear["hidden_bind"] == "slot:conversation-search-clear-hidden"
    assert clear["hidden_value"] == "true"


def test_conversation_reply_composer_surface_emits_textarea_and_submit_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-reply-composer", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-reply-composer"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-reply-composer"]["data"]
    assert root["children"] == [
        "ui:grandmap:conversation-reply-slash",
        "ui:grandmap:conversation-reply-input",
        "ui:grandmap:conversation-reply-send",
    ]
    text_area = nodes["ui:grandmap:conversation-reply-input"]["data"]
    assert text_area["tag"] == "textarea"
    assert text_area["bind"] == "slot:conversation-reply-value"
    assert text_area["action"] == "conversation.reply.update"
    assert text_area["submit_action"] == "conversation.reply.submit"
    assert text_area["rows"] == 1
    assert text_area["auto_grow"] is True
    assert text_area["auto_grow_max"] == 140
    send = nodes["ui:grandmap:conversation-reply-send"]["data"]
    assert send["tag"] == "button"
    assert send["bind"] == "slot:conversation-reply-send-label"
    assert send["action"] == "conversation.reply.submit"
    assert send["disabled_bind"] == "slot:conversation-reply-send-disabled"


def test_conversation_expanded_turn_surface_emits_message_row_shell(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-expanded-turn", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-expanded-turn"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-expanded-turn"]["data"]
    assert root["children"] == [
        "ui:grandmap:conversation-expanded-turn-avatar",
        "ui:grandmap:conversation-expanded-turn-content",
    ]
    assert nodes["ui:grandmap:conversation-expanded-turn-avatar"]["data"]["bind"] == (
        "slot:conversation-expanded-turn-avatar"
    )
    assert nodes["ui:grandmap:conversation-expanded-turn-avatar"]["data"]["state_bind"] == (
        "slot:conversation-expanded-turn-role"
    )
    assert nodes["ui:grandmap:conversation-expanded-turn-content"]["data"]["children"] == [
        "ui:grandmap:conversation-expanded-turn-meta",
        "ui:grandmap:conversation-expanded-turn-body",
    ]
    assert nodes["ui:grandmap:conversation-expanded-turn-name"]["data"]["bind"] == (
        "slot:conversation-expanded-turn-name"
    )
    assert nodes["ui:grandmap:conversation-expanded-turn-time"]["data"]["bind"] == (
        "slot:conversation-expanded-turn-time"
    )
    assert nodes["ui:grandmap:conversation-expanded-turn-body"]["data"]["render_slot"] == (
        "slot:conversation-expanded-turn-body"
    )


def test_conversation_rail_shell_surface_emits_render_slots(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-rail-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-rail-shell"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-rail-shell"]["data"]["tag"] == "aside"
    assert nodes["ui:grandmap:conversation-rail-shell"]["data"]["children"] == [
        "ui:grandmap:conversation-rail-minimap",
        "ui:grandmap:conversation-rail-header",
        "ui:grandmap:conversation-rail-scrollback",
    ]
    assert nodes["ui:grandmap:conversation-rail-minimap"]["data"]["render_slot"] == (
        "slot:conversation-rail-minimap"
    )
    assert nodes["ui:grandmap:conversation-rail-header"]["data"]["render_slot"] == (
        "slot:conversation-rail-header"
    )
    assert nodes["ui:grandmap:conversation-rail-scrollback"]["data"]["render_slot"] == (
        "slot:conversation-rail-scrollback"
    )


def test_rail_minimap_surface_emits_frame_and_jump_board_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("rail-minimap", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:rail-minimap"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:rail-minimap"]["data"]
    assert root["children"] == [
        "ui:grandmap:rail-minimap-empty",
        "ui:grandmap:rail-minimap-live",
    ]
    assert root["visible_when"] == {
        "bind": "slot:rail-minimap-visible",
        "value": "true",
    }
    assert nodes["slot:rail-minimap-visible"]["data"]["value"] == "true"
    assert nodes["slot:rail-minimap-ready"]["data"]["value"] == "false"
    assert nodes["slot:rail-minimap-title"]["data"]["value"] == "MAP - CLICK TO JUMP"
    assert nodes["ui:grandmap:rail-minimap-empty"]["data"]["bind"] == (
        "slot:rail-minimap-empty"
    )
    assert nodes["ui:grandmap:rail-minimap-empty"]["data"]["visible_when"] == {
        "bind": "slot:rail-minimap-ready",
        "value": "false",
    }
    assert nodes["ui:grandmap:rail-minimap-live"]["data"]["visible_when"] == {
        "bind": "slot:rail-minimap-ready",
        "value": "true",
    }
    board = nodes["ui:grandmap:rail-minimap-board"]["data"]
    assert board["action"] == "rail-minimap.jump"
    assert board["test_id"] == "rail-minimap-board"
    assert board["render_slot"] == "slot:rail-minimap-nodes"
    assert board["children"] == ["ui:grandmap:rail-minimap-viewport"]


def test_rail_minimap_node_rect_surface_emits_reusable_rect_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("rail-minimap-node-rect", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:rail-minimap-node-rect"
    assert payload["source_node_ids"] == ["ui_node_card"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    rect = nodes["ui:grandmap:rail-minimap-node-rect"]["data"]
    assert rect["tag"] == "div"
    assert rect["cls"] == "ah-rail-minimap-node-rect-node"
    assert rect["data_attrs"]["aria-hidden"] == "true"


def test_conversation_scrollback_surface_emits_scroll_container_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-scrollback", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-scrollback"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:conversation-scrollback"]["data"]
    assert root["tag"] == "div"
    assert root["cls"] == "ah-conversation-scrollback-node ah-scroll"
    assert root["test_id"] == "conversation-scrollback"
    assert root["render_slot"] == "slot:conversation-scrollback-content"


def test_conversation_fabricated_tool_warning_surface_emits_bound_copy_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-fabricated-tool-warning", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-fabricated-tool-warning"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-fabricated-tool-warning"]["data"]["children"] == [
        "ui:grandmap:conversation-fabricated-tool-title",
        "ui:grandmap:conversation-fabricated-tool-body",
        "ui:grandmap:conversation-fabricated-tool-clean",
    ]
    assert nodes["ui:grandmap:conversation-fabricated-tool-title"]["data"]["bind"] == (
        "slot:conversation-fabricated-tool-title"
    )
    assert nodes["ui:grandmap:conversation-fabricated-tool-body"]["data"]["bind"] == (
        "slot:conversation-fabricated-tool-body"
    )
    assert nodes["ui:grandmap:conversation-fabricated-tool-clean"]["data"]["bind"] == (
        "slot:conversation-fabricated-tool-clean"
    )
    assert nodes["ui:grandmap:conversation-fabricated-tool-clean"]["data"]["hidden_bind"] == (
        "slot:conversation-fabricated-tool-clean-hidden"
    )


def test_conversation_code_block_surface_emits_header_buttons_and_bound_code_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-code-block", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-code-block"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-code-block"]["data"]["children"] == [
        "ui:grandmap:conversation-code-header",
        "ui:grandmap:conversation-code-body",
    ]
    assert nodes["ui:grandmap:conversation-code-header"]["data"]["children"] == [
        "ui:grandmap:conversation-code-language",
        "ui:grandmap:conversation-code-lines",
        "ui:grandmap:conversation-code-spacer",
        "ui:grandmap:conversation-code-copy",
        "ui:grandmap:conversation-code-toggle",
    ]
    assert nodes["ui:grandmap:conversation-code-language"]["data"]["bind"] == (
        "slot:conversation-code-language"
    )
    assert nodes["ui:grandmap:conversation-code-lines"]["data"]["bind"] == (
        "slot:conversation-code-lines"
    )
    assert nodes["ui:grandmap:conversation-code-copy"]["data"]["action"] == (
        "conversation.code.copy"
    )
    assert nodes["ui:grandmap:conversation-code-toggle"]["data"]["action"] == (
        "conversation.code.toggle"
    )
    assert nodes["ui:grandmap:conversation-code-toggle"]["data"]["bind"] == (
        "slot:conversation-code-toggle"
    )
    assert nodes["ui:grandmap:conversation-code-toggle"]["data"]["hidden_bind"] == (
        "slot:conversation-code-toggle-hidden"
    )
    assert nodes["ui:grandmap:conversation-code-toggle"]["data"]["hidden_value"] == "true"
    assert nodes["ui:grandmap:conversation-code-body"]["data"]["tag"] == "pre"
    assert nodes["ui:grandmap:conversation-code-body"]["data"]["bind"] == (
        "slot:conversation-code-body"
    )
    assert nodes["ui:grandmap:conversation-code-body"]["data"]["state_bind"] == (
        "slot:conversation-code-state"
    )


def test_conversation_clipped_text_surface_emits_toggleable_text_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-clipped-text", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-clipped-text"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-clipped-text"]["data"]["children"] == [
        "ui:grandmap:conversation-clipped-text-value",
        "ui:grandmap:conversation-clipped-text-caret",
        "ui:grandmap:conversation-clipped-text-toggle",
    ]
    assert nodes["ui:grandmap:conversation-clipped-text-value"]["data"]["bind"] == (
        "slot:conversation-clipped-text-value"
    )
    caret = nodes["ui:grandmap:conversation-clipped-text-caret"]["data"]
    assert caret["visible_when"] == {
        "bind": "slot:conversation-clipped-text-streaming",
        "value": "true",
    }
    toggle = nodes["ui:grandmap:conversation-clipped-text-toggle"]["data"]
    assert toggle["tag"] == "button"
    assert toggle["bind"] == "slot:conversation-clipped-text-toggle-label"
    assert toggle["action"] == "conversation.clipped-text.toggle"
    assert toggle["visible_when"] == {
        "bind": "slot:conversation-clipped-text-long",
        "value": "true",
    }


def test_conversation_text_span_surface_emits_bound_prose_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-text-span", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-text-span"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-text-span"]["data"]["tag"] == "span"
    assert nodes["ui:grandmap:conversation-text-span"]["data"]["cls"] == (
        "ah-conversation-text-span-node"
    )
    assert nodes["ui:grandmap:conversation-text-span"]["data"]["bind"] == (
        "slot:conversation-text-body"
    )


def test_conversation_thinking_surface_emits_dots_and_label_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("conversation-thinking", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:conversation-thinking"
    assert payload["source_node_ids"] == ["ui_node_card"]

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ui:grandmap:conversation-thinking"]["data"]["children"] == [
        "ui:grandmap:conversation-thinking-dot-0",
        "ui:grandmap:conversation-thinking-dot-1",
        "ui:grandmap:conversation-thinking-dot-2",
        "ui:grandmap:conversation-thinking-label",
    ]
    assert nodes["ui:grandmap:conversation-thinking-label"]["data"]["bind"] == (
        "slot:conversation-thinking-label"
    )
    assert nodes["ui:grandmap:conversation-thinking-dot-0"]["data"]["cls"] == (
        "ah-conversation-thinking-dot-node ah-conversation-thinking-dot-0-node"
    )


def test_ai_plan_section_surface_emits_stateful_metric_and_action_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(grand_map, [_node("ui_node_card", "Node Card")])

    payload = grand_map_ui_surface("ai-plan-section", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:ai-plan-section"
    assert payload["source_node_ids"] == ["ui_node_card"]
    nodes = {node["id"]: node for node in payload["nodes"]}
    root = nodes["ui:grandmap:ai-plan-section"]
    assert root["data"]["children"] == [
        "ui:grandmap:ai-plan-heading",
        "ui:grandmap:ai-plan-loading",
        "ui:grandmap:ai-plan-empty",
        "ui:grandmap:ai-plan-metrics",
        "ui:grandmap:ai-plan-decisions-heading",
        "ui:grandmap:ai-plan-decisions",
        "ui:grandmap:ai-plan-actions",
    ]
    assert nodes["ui:grandmap:ai-plan-heading"]["data"]["bind"] == "slot:ai-plan-status"
    assert nodes["ui:grandmap:ai-plan-loading"]["data"]["visible_when"] == {
        "bind": "slot:ai-plan-state",
        "values": ["loading"],
    }
    assert nodes["ui:grandmap:ai-plan-empty"]["data"]["visible_when"] == {
        "bind": "slot:ai-plan-state",
        "values": ["empty"],
    }
    assert nodes["ui:grandmap:ai-plan-metrics"]["data"]["visible_when"] == {
        "bind": "slot:ai-plan-state",
        "values": ["ready"],
    }
    assert nodes["ui:grandmap:ai-plan-metric-plan-id"]["data"]["bind"] == "slot:ai-plan-id"
    assert nodes["ui:grandmap:ai-plan-metric-calls"]["data"]["bind"] == "slot:ai-plan-calls"
    assert nodes["ui:grandmap:ai-plan-decision-1"]["data"]["visible_when"] == {
        "bind": "slot:ai-plan-decision-1-visible",
        "values": ["true"],
    }
    assert nodes["ui:grandmap:ai-plan-replay"]["data"]["action"] == "ai.plan.replay"
    assert nodes["ui:grandmap:ai-plan-open"]["data"]["action"] == "ai.plan.open_file"
    child_ids = {
        child
        for node in payload["nodes"]
        for child in node.get("data", {}).get("children", []) or []
    }
    assert child_ids <= set(nodes)


def test_conversation_rail_hydrates_collapsed_and_header_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    collapsed_surface = jsx[
        jsx.index("const ConversationCollapsedSurface ="):
        jsx.index("const ConversationHeaderSurface =", jsx.index("const ConversationCollapsedSurface ="))
    ]
    conversation_rail = jsx[
        jsx.index("const ConversationRail ="):
        jsx.index("const ConversationTextSurface =", jsx.index("const ConversationRail ="))
    ]

    assert "const ConversationCollapsedSurface = ({ node, toggleCollapsed }) =>" in jsx
    assert "const ConversationHeaderSurface = ({ node, cat, toggleCollapsed }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-collapsed-rail'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-header'" in jsx
    assert "<aside key={node && node.id}" not in collapsed_surface
    assert ".ah-conversation-header-node{padding:12px 16px 10px" in jsx
    assert "<div style={{ padding:'12px 16px 10px'" not in jsx
    assert "<ConversationCollapsedSurface node={node} toggleCollapsed={toggleCollapsed}/>" in conversation_rail
    assert "<ConversationHeaderSurface node={node} cat={cat} toggleCollapsed={toggleCollapsed}/>" in jsx
    assert "CONVERSATION · {node.messages.length}" not in conversation_rail


def test_conversation_collapse_state_syncs_to_inline_node_and_app_state():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    collapse_sync = jsx[
        jsx.index("const syncGrandMapConversationCollapseState ="):
        jsx.index("const WorkspaceInner =", jsx.index("const syncGrandMapConversationCollapseState ="))
    ]
    workspace = jsx[
        jsx.index("const WorkspaceInner ="):
        jsx.index("const Workspace = React.memo", jsx.index("const WorkspaceInner ="))
    ]
    conversation_rail = jsx[
        jsx.index("const ConversationRail ="):
        jsx.index("const ConversationTextSurface =", jsx.index("const ConversationRail ="))
    ]

    assert "const syncGrandMapConversationCollapseState = (nodeId, collapsed, storageKey) =>" in collapse_sync
    assert "conversation_collapsed: isCollapsed" in collapse_sync
    assert "conversation_collapse_key: storageKey || ''" in collapse_sync
    assert "['conversation_collapsed', isCollapsed]" in collapse_sync
    assert "['conversation_collapse_key', storageKey || '']" in collapse_sync
    assert "setGrandMapInlineNodeField(node, key, value)" in collapse_sync
    assert "window.ahSetUiNodeParam(nodeId, 'conversation_collapsed', isCollapsed);" not in collapse_sync
    assert "window.ahSetUiNodeParam(nodeId, 'conversation_collapse_key', storageKey || '');" not in collapse_sync
    assert "right_rail_conversation_collapsed: isCollapsed" in collapse_sync
    assert "right_rail_focus_node_id: nodeId" in collapse_sync
    assert "['right_rail_conversation_collapsed', isCollapsed]" in collapse_sync
    assert "['right_rail_focus_node_id', nodeId]" in collapse_sync
    assert "setGrandMapInlineNodeField(appNode, key, value)" in collapse_sync
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'right_rail_conversation_collapsed', isCollapsed);" not in collapse_sync
    assert "window.ahSetUiNodeParam(ARCHHUB_APPLICATION_SUPER_NODE_ID, 'right_rail_focus_node_id', nodeId);" not in collapse_sync
    assert "syncGrandMapConversationCollapseState(focusId, next, _convoKey);" in workspace
    assert "syncGrandMapConversationCollapseState(node.id, collapsed, _convoKey);" in conversation_rail
    assert "syncGrandMapConversationCollapseState(node.id, next, _convoKey);" in conversation_rail


def test_conversation_rail_hydrates_expanded_shell_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    conversation_rail = jsx[
        jsx.index("const ConversationRail ="):
        jsx.index("const ConversationTextSurface =", jsx.index("const ConversationRail ="))
    ]
    shell_surface = jsx[
        jsx.index("const ConversationRailShellSurface ="):
        jsx.index("const ConversationRail =", jsx.index("const ConversationRailShellSurface ="))
    ]

    assert "const ConversationRailShellSurface = ({ node, cat, toggleCollapsed, scrollRef, children }) =>" in jsx
    assert "const ConversationScrollbackSurface = ({ scrollRef, children }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-rail-shell'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-scrollback'" in jsx
    assert "slot:conversation-rail-minimap" in shell_surface
    assert "slot:conversation-rail-header" in shell_surface
    assert "slot:conversation-rail-scrollback" in shell_surface
    assert "slot:conversation-scrollback-content" in jsx
    assert "<ConversationScrollbackSurface scrollRef={scrollRef}>{children}</ConversationScrollbackSurface>" in shell_surface
    assert "node = { ins:[], outs:[], messages:[], params:[], ...node }" not in conversation_rail
    assert "node.messages = Array.isArray(node.messages) ? node.messages : [];" in conversation_rail
    assert "not a detached inspector copy" in conversation_rail
    assert "<ConversationRailShellSurface node={node} cat={cat} toggleCollapsed={toggleCollapsed} scrollRef={scrollRef}>" in conversation_rail
    assert "<aside key={node.id} style" not in conversation_rail
    assert "<div ref={scrollRef} className=\"ah-scroll\" style={{" not in shell_surface


def test_rail_minimap_hydrates_frame_and_rectangles_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    minimap = jsx[
        jsx.index("const RailMiniMapNodeRect ="):
        jsx.index("const PaletteSectionHeader =", jsx.index("const RailMiniMap ="))
    ]

    assert "const ensureGrandMapRailMinimapNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'rail-minimap'" in jsx
    assert "const ensureGrandMapRailMinimapNodeRectNodes = (node, style) =>" in jsx
    assert "get_grand_map_ui_surface', 'rail-minimap-node-rect'" in jsx
    assert "syncGrandMapSurfaceStateSlots('rail-minimap', rootId, slotMap" in jsx
    assert "'slot:rail-minimap-visible': visible ? 'true' : 'false'" in jsx
    assert "'slot:rail-minimap-ready': ready ? 'true' : 'false'" in jsx
    assert "eventArgs.localX" in jsx
    assert "eventArgs.targetWidth" in jsx
    assert "const RailMiniMapNodeRect = ({ node, style }) =>" in minimap
    assert "ensureGrandMapRailMinimapNodeRectNodes(node, style)" in minimap
    assert "ensureGrandMapRailMinimapNodes({" in minimap
    assert 'surface="rail-minimap"' in minimap
    assert 'surface="rail-minimap-node-rect"' in minimap
    assert "slot:rail-minimap-nodes" in minimap
    assert "rail-minimap.jump" in minimap
    assert "archhub-minimap-jump" in minimap
    assert "<div style={{ margin:'4px 8px 0'" not in minimap
    assert "nodes.map(n => {" in minimap


def test_rail_minimap_wires_slots_to_surface_state_node():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    block = jsx[
        jsx.index("const updateGrandMapRailMinimapSlots ="):
        jsx.index(
            "const ensureGrandMapRailMinimapNodes =",
            jsx.index("const updateGrandMapRailMinimapSlots ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('rail-minimap', rootId, slotMap" in block
    assert "state_key: 'rail_minimap_state_node_id'" in block
    assert "'slot:rail-minimap-title': (slots && slots.title) || 'MAP - CLICK TO JUMP'" in block
    assert "'slot:rail-minimap-empty': (slots && slots.empty) || 'OPEN SESSION FOR MAP'" in block


def test_conversation_rail_hydrates_day_dividers_and_tool_trace_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    conversation_rail = jsx[
        jsx.index("const ConversationRail ="):
        jsx.index("const ConversationTextSurface =", jsx.index("const ConversationRail ="))
    ]

    assert "const ConversationDayDividerSurface = ({ dayKey, label }) =>" in jsx
    assert "const ConversationToolTraceSurface = ({ node }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-day-divider'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-tool-trace'" in jsx
    assert "<ConversationDayDividerSurface key={'div-' + key + '-' + i} dayKey={key} label={_dayLabelOf(key)}/>" in conversation_rail
    assert "<ConversationToolTraceSurface node={node}/>" in conversation_rail
    assert "TOOL TRACE" not in conversation_rail


def test_chat_turn_hydrates_message_shell_and_action_bar_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chat_turn = jsx[
        jsx.index("const ChatTurn ="):
        jsx.index("const PinRow =", jsx.index("const ChatTurn ="))
    ]
    turn_surface = jsx[
        jsx.index("const ConversationTurnSurface ="):
        jsx.index("// AgDR-0032", jsx.index("const ConversationTurnSurface ="))
    ]

    assert "const ConversationTurnSurface = ({ nodeId, m, ix, isLast, onAction }) =>" in jsx
    assert "const ConversationTurnActionsSurface = ({ m, ix, onAction }) =>" in jsx
    assert "const ConversationReasoningSurface = ({ nodeId, ix, steps }) =>" in jsx
    assert "const ConversationReasoningStepSurface = ({ reasoningId, step, index }) =>" in jsx
    assert "render_slot" in jsx
    assert "get_grand_map_ui_surface', 'conversation-turn'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-turn-actions'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-reasoning'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-reasoning-step'" in jsx
    assert "<ConversationTurnSurface nodeId={nodeId} m={m} ix={ix} isLast={isLast} onAction={onAction}/>" in chat_turn
    assert "<ChatText text={m.text}/>" not in chat_turn
    assert "<ThinkingDots color={aiColor}/>" not in chat_turn
    assert "<ConversationTurnActionsSurface m={m} ix={ix} onAction={onAction}/>" in turn_surface
    assert "<ConversationReasoningSurface nodeId={nodeId} ix={ix} steps={m.reasoning}/>" in turn_surface
    assert "<ConversationReasoningStepSurface" in jsx
    assert "conversation.reasoning.toggle" in jsx
    assert "slot:conversation-reasoning-steps" in jsx
    assert "m.reasoning.map((step, ri) =>" not in turn_surface
    assert "setShowReasoning" not in turn_surface
    assert "<ChatAction" not in jsx


def test_ai_body_compact_reasoning_reuses_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ai_body = jsx[
        jsx.index("const AIBody ="):
        jsx.index("// Compact text renderer", jsx.index("const AIBody ="))
    ]
    compact_turn = jsx[
        jsx.index("const ConversationCompactTurnSurface ="):
        jsx.index("const AIBody =", jsx.index("const ConversationCompactTurnSurface ="))
    ]
    expanded_ai_body = ai_body[:ai_body.index("// Compact view")]

    assert "const messageIx = Math.max(0, total - recent.length + i);" in ai_body
    assert "const ConversationCompactExpandSurface = ({ nodeId, total, onToggleExpand }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-compact-expand'" in jsx
    assert "conversation.compact.expand" in jsx
    assert "const ConversationCompactTurnSurface = ({ nodeId, m, ix, isLast }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-compact-turn'" in jsx
    assert "const ConversationRouteMetaSurface = ({ nodeId, ix, routes }) =>" in jsx
    assert "const ConversationRouteMetaRowSurface = ({ metaId, route, index }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-route-meta'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-route-meta-row'" in jsx
    assert "const ConversationNodeScrollbackSurface = ({ children }) =>" in jsx
    assert "const ConversationSearchEmptySurface = ({ query }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-node-scrollback'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-search-empty'" in jsx
    assert "const ConversationAIBodyExpandedSurface = ({ searchSlot, scrollbackSlot, replySlot }) =>" in jsx
    assert "const ConversationAIBodyCompactSurface = ({ expandSlot, turnsSlot }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-ai-body-expanded'" in jsx
    assert "get_grand_map_ui_surface', 'conversation-ai-body-compact'" in jsx
    assert "const ConversationSearchBarSurface = ({ nodeId, query, resultCount, total, onQueryChange }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-search-bar'" in jsx
    assert "conversation.search.update" in jsx
    assert "conversation.search.clear" in jsx
    assert "const ConversationReplyComposerSurface = ({ nodeId, reply, onReplyChange, onSubmit }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-reply-composer'" in jsx
    assert "conversation.reply.update" in jsx
    assert "conversation.reply.submit" in jsx
    assert "const ConversationExpandedTurnSurface = ({ nodeId, m, ix, query }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-expanded-turn'" in jsx
    assert "<ConversationSearchBarSurface" in ai_body
    assert "<ConversationReplyComposerSurface" in ai_body
    assert "<ConversationNodeScrollbackSurface>" in ai_body
    assert "<ConversationSearchEmptySurface query={q}/>" in ai_body
    assert "<ConversationAIBodyExpandedSurface" in ai_body
    assert "<ConversationAIBodyCompactSurface" in ai_body
    assert "<ConversationExpandedTurnSurface" in ai_body
    assert "<ConversationCompactExpandSurface" in ai_body
    assert "<ConversationCompactTurnSurface" in ai_body
    assert "<ConversationReasoningSurface" in compact_turn
    assert "<ConversationRouteMetaSurface nodeId={nodeId} ix={ix} routes={m.route}/>" in compact_turn
    assert "nodeId={n.id || 'ai-body'}" in ai_body
    assert "ix={'compact-' + ix}" in compact_turn
    assert "placeholder=\"Search this conversation" not in ai_body
    assert "setQ(e.target.value)" not in ai_body
    assert "placeholder=\"Reply" not in ai_body
    assert "setReply(e.target.value)" not in ai_body
    assert "onKeyDown={e => { if (e.key === 'Enter'" not in ai_body
    assert "className=\"ah-scroll\" style={{" not in ai_body
    assert "onClick={e => e.stopPropagation()} style={{ marginTop:9" not in ai_body
    assert "<div style={{ marginTop:9, display:'flex', flexDirection:'column', gap:9 }}" not in ai_body
    assert "No matches for" not in ai_body
    assert "display:'grid', placeItems:'center'" not in expanded_ai_body
    assert "highlight(m.text, q)" not in expanded_ai_body
    assert "expand + search" not in ai_body
    assert "onMouseEnter" not in ai_body
    assert "setShowReasoning" not in ai_body
    assert "m.reasoning.map((step, ri) =>" not in ai_body
    assert "const aiLetter = m.who || (m.model && m.model.who)" not in ai_body
    assert "data-testid=\"route-meta\" style={{" not in ai_body
    assert "m.route.map((r, ri) =>" not in ai_body


def test_clipped_text_plain_preview_hydrates_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clipped_text = jsx[
        jsx.index("const ClippedText ="):
        jsx.index("const highlight =", jsx.index("const ClippedText ="))
    ]

    assert "const ConversationClippedTextSurface = ({ text, color, isStreaming, caretColor }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-clipped-text'" in jsx
    assert "conversation.clipped-text.toggle" in jsx
    assert "return <ConversationClippedTextSurface text={s} color={color} isStreaming={isStreaming} caretColor={caretColor}/>;" in clipped_text
    assert "setOpen" not in clipped_text
    assert "show more chars" not in clipped_text


def test_chat_text_hydrates_fabricated_tool_warning_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chat_text = jsx[
        jsx.index("const ChatText ="):
        jsx.index("const ChatCodeBlock =", jsx.index("const ChatText ="))
    ]

    assert "const FabricatedToolWarningSurface = ({ cleanText }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-fabricated-tool-warning'" in jsx
    assert "<FabricatedToolWarningSurface cleanText={scrub.clean}/>" in chat_text
    assert "FABRICATED TOOL CALL" not in chat_text


def test_chat_code_block_hydrates_code_fence_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    code_block = jsx[
        jsx.index("const ChatCodeBlock ="):
        jsx.index("const ConversationTurnActionsSurface =", jsx.index("const ChatCodeBlock ="))
    ]

    assert "const ConversationCodeBlockSurface = ({ lang, code }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-code-block'" in jsx
    assert "<ConversationCodeBlockSurface lang={lang} code={code}/>" in code_block
    assert "navigator.clipboard.writeText(code)" not in code_block
    assert "lines.slice(0, 8)" not in code_block


def test_chat_text_hydrates_plain_prose_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    chat_text = jsx[
        jsx.index("const ChatText ="):
        jsx.index("const ConversationCodeBlockSurface =", jsx.index("const ChatText ="))
    ]

    assert "const ConversationTextSurface = ({ text, instanceKey }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-text-span'" in jsx
    assert "const chatTextInstanceId = React.useMemo(() => _lm_uid(), [])" in chat_text
    assert "return <ConversationTextSurface text={s} instanceKey={chatTextInstanceId + ':plain'}/>;" in chat_text
    assert "<ConversationTextSurface key={i} text={seg} instanceKey={chatTextInstanceId + ':seg:' + i}/>" in chat_text
    assert "whiteSpace:'pre-wrap'" not in chat_text


def test_thinking_indicator_hydrates_from_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    thinking = jsx[
        jsx.index("const ThinkingDots ="):
        jsx.index("const _TOOL_NAME =", jsx.index("const ThinkingDots ="))
    ]

    assert "const ConversationThinkingSurface = ({ color }) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-thinking'" in jsx
    assert "<ConversationThinkingSurface color={color}/>" in thinking
    assert "thinking</span>" not in thinking


def test_conversation_surfaces_use_shared_surface_hook_not_local_refresh_timers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    conversation_surfaces = jsx[
        jsx.index("const ConversationCollapsedSurface ="):
        jsx.index("const PinRow =", jsx.index("const ConversationCollapsedSurface ="))
    ]

    assert conversation_surfaces.count("useGrandMapSurfaceRoot(") >= 13
    assert "() => node ? ensureGrandMapConversationCollapsedRailNodes(node) : null" in conversation_surfaces
    assert "() => node ? ensureGrandMapConversationHeaderNodes(node, cat || {}) : null" in conversation_surfaces
    assert "() => dayKey ? ensureGrandMapConversationDayDividerNodes(dayKey, label) : null" in conversation_surfaces
    assert "() => node ? ensureGrandMapConversationToolTraceNodes(node) : null" in conversation_surfaces
    assert "() => node ? ensureGrandMapConversationRailShellNodes(node) : null" in conversation_surfaces
    assert "() => ensureGrandMapConversationTextNodes(text, instanceKey)" in conversation_surfaces
    assert "() => ensureGrandMapConversationThinkingNodes(color, instanceKey)" in conversation_surfaces
    assert "() => ensureGrandMapFabricatedToolWarningNodes(cleanText)" in conversation_surfaces
    assert "() => ensureGrandMapConversationCodeBlockNodes(lang, code, open)" in conversation_surfaces
    assert "() => ensureGrandMapConversationTurnActionsNodes(m, ix)" in conversation_surfaces
    assert "() => ensureGrandMapConversationTurnNodes(nodeId, m, ix)" in conversation_surfaces
    assert "() => ensureGrandMapConversationReasoningNodes(nodeId, ix, open, count)" in conversation_surfaces
    assert "() => ensureGrandMapConversationReasoningStepNodes(reasoningId, step, index)" in conversation_surfaces
    assert "bumpConversation" not in conversation_surfaces
    assert "bumpFabricatedToolWarningSurface" not in conversation_surfaces
    assert "setTimeout(() => bumpConversation" not in conversation_surfaces
    assert "window.dispatchEvent(new Event('lm-graph-bump'))" not in conversation_surfaces


def test_ui_node_surface_graph_bump_is_deferred_out_of_render():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    surface = jsx[jsx.index("const UiNodeSurface ="):jsx.index("// THE WATCHER", jsx.index("const UiNodeSurface ="))]

    assert "const onGraphBump = () => {" in surface
    assert "timer = setTimeout(() => {" in surface
    assert "window.addEventListener('lm-graph-bump', onGraphBump)" in surface
    assert "window.addEventListener('lm-graph-bump', bump)" not in surface


def test_surface_root_hook_refreshes_when_async_surface_import_completes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    hook = jsx[
        jsx.index("const useGrandMapSurfaceRoot ="):
        jsx.index("const UiSurfaceRefNode =", jsx.index("const useGrandMapSurfaceRoot ="))
    ]

    assert "const currentRootRef = React.useRef(null);" in hook
    assert "currentRootRef.current = id;" in hook
    assert "const onSurfaceImported = (ev) => {" in hook
    assert "const importedRoot = ev && ev.detail && ev.detail.root_id;" in hook
    assert "if (importedRoot && currentRootRef.current && importedRoot !== currentRootRef.current) return;" in hook
    assert "refresh();" in hook
    assert "window.addEventListener('archhub-ui-surface-imported', onSurfaceImported)" in hook
    assert "window.removeEventListener('archhub-ui-surface-imported', onSurfaceImported)" in hook
    assert "window.addEventListener('lm-graph-bump', onGraphBump)" not in hook


def test_ui_param_setter_reuses_global_param_node_when_owner_links_are_rebuilt():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    watcher = jsx[
        jsx.index("window.ahSetUiNodeParam = function"):
        jsx.index("window.ahEditUiNode = function", jsx.index("window.ahSetUiNodeParam = function"))
    ]

    assert "var existingParamNode = _uiFind(g.nodes, paramNodeId);" in watcher
    assert "if (existingParamNode) {" in watcher
    assert "paramNode = existingParamNode;" in watcher
    assert "if (n.data.param_nodes.indexOf(paramNodeId) < 0) {" in watcher
    assert "n.data.param_nodes.push(paramNodeId);" in watcher
    assert "g.nodes.push(paramNode);" in watcher
    assert "var editorType = (param && param.type) ? param.type : inferEditorType(value);" in watcher
    assert "var schemaType = editorType === 'text' ? 'string' : editorType;" in watcher
    assert "param_type: editorType" in watcher
    assert "config_schema: { value: { type: schemaType, default: value } }" in watcher
    assert "{ k: 'value', label: 'value', type: editorType, v: value }" in watcher
    assert "valueParam.type = editorType;" in watcher


def test_node_properties_row_clone_maps_template_children_once():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]

    assert "copy.data.children = tn.data.children.map(rowMapId)" in clone
    assert "copy.data.children = copy.data.children.map(rowMapId)" not in clone
    assert "const paramNodeId = (p && p.param_node_id) ? p.param_node_id : _uiParamNodeId(node.id, key);" in clone
    assert "param_node_id: paramNodeId" in clone
    assert "if (Object.prototype.hasOwnProperty.call(copy.data, k)) copy.config[k] = copy.data[k];" in clone
    assert "Object.assign({}, p, { v: copy.data[p.k] })" in clone


def test_node_properties_row_clone_uses_param_type_to_build_node_controls():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]
    projector = jsx[
        jsx.index("function projectUiNode"):
        jsx.index("const UiNodeSurface =", jsx.index("function projectUiNode"))
    ]

    assert "const normalizeParamControl = (p) =>" in clone
    assert "return 'select';" in clone
    assert "return 'slider';" in clone
    assert "return 'number';" in clone
    assert "return 'boolean';" in clone
    assert "return 'color';" in clone
    assert "const controlSlot = rowMapId('slot:node-param-control');" in clone
    assert "const promotableSlot = rowMapId('slot:node-param-promotable');" in clone
    assert "[controlSlot]: control" in clone
    assert "[promotableSlot]: node && node.op_id ? 'true' : 'false'" in clone
    assert "syncGrandMapSurfaceStateSlots('node-property-param-row-'" not in clone
    assert "'data-lm-param-row': '1'" in clone
    assert "'data-param-node': paramNodeId" in clone
    assert "'data-param-owner': node.id" in clone
    assert "copy.data.children = optionRootIds;" in clone
    assert "copy.data.option_value = parts.value;" in clone
    assert "const activeControlTemplateIds = new Set(controlTemplateIds[control] || controlTemplateIds.text);" in clone
    assert "if (allControlTemplateIds.has(tn.id) && !activeControlTemplateIds.has(tn.id)) return;" in clone
    assert "copy.data.children = Array.from(activeControlTemplateIds).map(rowMapId);" in clone
    assert "delete copy.data.visible_when;" in clone
    assert "delete copy.data.action;" in clone
    assert "copy.data.visible_when = Object.assign({}, copy.data.visible_when, { bind: promotableSlot });" in clone
    assert "if (d.visible_when && d.visible_when.bind) {" in projector
    assert "const isNodeHidden = props.hidden === true || props['data-hidden'] === 'true';" in projector
    assert "if (!isNodeHidden) props.checked =" in projector
    assert "if (!isNodeHidden) {" in projector
    assert "props.value = /^#[0-9a-fA-F]{6}$/.test(colorValue) ? colorValue : '#000000';" in projector
    assert "props.value = '';" in projector
    assert "if (!isNodeHidden) props.value = d.bind ? String(_uiBindingValue(nodes, wires, id, 'bind', d.bind)) : txt;" in projector
    assert "props.checked = checkedRaw === true || String(checkedRaw).toLowerCase() === 'true';" in projector
    assert "d.value_cast === 'number' || d.input_type === 'number' || d.input_type === 'range'" in projector
    assert "} else if (d.tag === 'select') {" in projector


def test_node_properties_schema_keeps_live_param_type_for_controls():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    items = jsx[
        jsx.index("const nodeRailParamItems ="):
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate =", jsx.index("const nodeRailParamItems ="))
    ]

    assert "if (pr && pr.type) row.type = pr.type;" in items
    assert "if (pr && Array.isArray(pr.options) && pr.options.length > 0) row.options = pr.options;" in items
    assert "['min', 'max', 'step'].forEach" in items


def test_node_properties_row_clone_lazy_materializes_internal_scaffold_params():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="):
        jsx.index("const ensureGrandMapNodePropertiesPanelNodes =", jsx.index("const cloneGrandMapNodePropertiesPanelTemplate ="))
    ]

    assert "if (tn.data && tn.data.role === 'parameter') return;" in clone
    assert "copy.data.param_nodes = [];" in clone
    assert "const syncClonedParams = (copy) =>" in clone
    assert "if (!(copy.data && copy.data.materialize_param_nodes === true)) return;" in clone
    assert "materializeGrandMapParamNode(copy, p.k, copy.data[p.k]);" in clone
    assert "window.ahSetUiNodeParam(copy.id, p.k, copy.data[p.k]);" not in clone
    assert "syncClonedParams(copy);" in clone
    assert "String(fromId).indexOf('param:') === 0" in clone


def test_right_rail_secondary_clones_materialize_fresh_param_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "const resetClonedUiNodeParamLinks = (copy) =>" in jsx
    assert "const syncClonedUiNodeParams = (copy) =>" in jsx
    clone_names = [
        "NodeRailShell",
        "NodeActionsPanel",
        "NodeSummaryPanel",
        "NodeConnectionsPanel",
    ]

    for name in clone_names:
        clone = jsx[
            jsx.index(f"const cloneGrandMap{name}Template ="):
            jsx.index(f"const ensureGrandMap{name}Nodes =", jsx.index(f"const cloneGrandMap{name}Template ="))
        ]
        assert "if (tn.data && tn.data.role === 'parameter') return;" in clone, name
        assert "resetClonedUiNodeParamLinks(copy);" in clone, name
        assert "finishClonedUiNodeParamAuthority(copy);" in clone, name
        assert "syncClonedUiNodeParams(copy);" in clone, name
        assert "String(fromId).indexOf('param:') === 0" in clone, name


def test_focused_right_rail_clones_prune_previous_focus_instances():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "const pruneGrandMapFocusedRailClones = (activeSid) =>" in jsx
    assert "const pruneGrandMapFocusedRailPanelClones = (activeSid, prefixes, wireFamilies = []) =>" in jsx
    helper = jsx[
        jsx.index("const pruneGrandMapFocusedRailClones = (activeSid) =>"):
        jsx.index("let __grandMapUiHomeSlots = {};")
    ]
    for prefix in [
        "ui:grandmap:node-rail-",
        "ui:grandmap:node-summary-",
        "ui:grandmap:node-connections-",
        "ui:grandmap:node-connection-pin-",
        "ui:grandmap:node-properties-",
        "ui:grandmap:node-property-param-",
        "ui:grandmap:node-actions-",
        "ui:grandmap:node-action-",
        "slot:node-summary-",
        "slot:node-connections-",
        "slot:node-connection-pin-",
        "slot:node-title",
        "slot:node-subtitle",
        "slot:node-category",
        "slot:node-param-count",
        "slot:node-property-help",
        "slot:node-param-",
    ]:
        assert prefix in helper
    assert "removeIds.has(n.data.owner)" in helper
    assert "g.wires = (g.wires || []).filter(wire =>" in helper
    assert "const hasInstanceSuffix = id.indexOf('slot:') === 0 ? parts.length > 2 : parts.length > 3;" in helper

    shell_clone = jsx[
        jsx.index("const cloneGrandMapNodeRailShellTemplate ="):
        jsx.index("const seedGrandMapNodeRailShellFallbackNodes =", jsx.index("const cloneGrandMapNodeRailShellTemplate ="))
    ]
    assert "pruneGrandMapFocusedRailClones(sid);" in shell_clone

    for name in [
        "NodeActionsPanel",
        "NodeSummaryPanel",
        "NodeConnectionsPanel",
        "NodePropertiesPanel",
    ]:
        clone = jsx[
            jsx.index(f"const cloneGrandMap{name}Template ="):
            jsx.index(f"const ensureGrandMap{name}Nodes =", jsx.index(f"const cloneGrandMap{name}Template ="))
        ]
        assert "pruneGrandMapFocusedRailPanelClones(sid," in clone, name
        assert "pruneGrandMapFocusedRailClones(sid);" not in clone, name


def test_home_surface_jsx_hydrates_from_bridge_before_fallback():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    home_slots = jsx[
        jsx.index("const updateGrandMapHomeSlots = (slots) =>"):
        jsx.index("const refreshGrandMapAccountSlot =", jsx.index("const updateGrandMapHomeSlots = (slots) =>"))
    ]
    home_jsx = jsx[jsx.index("const Home ="):jsx.index("const WorkspaceInner")]
    first_run_jsx = jsx[
        jsx.index("const FirstRunProfile ="):
        jsx.index("unified Add-Node Search overlay")
    ]
    ws_header_jsx = jsx[jsx.index("const WsHeader ="):jsx.index("const smallBtn =")]
    skills_panel = jsx[
        jsx.index("const SkillsPanel ="):
        jsx.index("const SearchPanelShellSurface", jsx.index("const SkillsPanel ="))
    ]

    assert "get_grand_map_ui_surface" in jsx
    assert "mergeUiSurfaceIntoGraph(payload)" in jsx
    assert "updateGrandMapHomeSlots(__grandMapUiHomeSlots)" in jsx
    assert "'graph: ' + fmt(nodes.length) + 'N ' + fmt(wires.length) + 'W'" in home_jsx
    assert "canvasNodeCount > 0 ? 'graph: active' : 'graph: ui surface'" not in home_jsx
    assert "const slotMap = {" in home_slots
    assert "syncGrandMapSurfaceStateSlots('home-runtime-state', 'ui:grandmap:home-top', slotMap" in home_slots
    assert "state_key: 'home_runtime_state_node_id'" in home_slots
    assert "bridgeAsync('cloud_status')" in jsx
    assert "updateGrandMapHomeSlots({ signed: label })" in jsx
    assert "const grandMapRoot = ensureGrandMapHomeTopUiNodes(slots);" in jsx
    assert "const ensureGrandMapSessionsHeaderNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-sessions-header'" in jsx
    assert "ensureGrandMapSessionsHeaderNodes({" in jsx
    assert "const ensureGrandMapSessionToolbarNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-session-toolbar'" in jsx
    assert "ensureGrandMapSessionToolbarNodes({" in jsx
    assert "const ensureGrandMapSelectionToolbarNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-selection-toolbar'" in jsx
    assert "ensureGrandMapSelectionToolbarNodes({" in jsx
    assert "const ensureGrandMapHomeEmptyStateNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-empty-state'" in jsx
    assert "ensureGrandMapHomeEmptyStateNodes({" in jsx
    assert "const ensureGrandMapSessionCardNodes = (session, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-session-card'" in jsx
    assert "ensureGrandMapSessionCardNodes(s, {" in jsx
    assert "slot:session-card-menu:' + sid" in jsx
    assert "const ensureGrandMapChatSessionRowNodes = (session, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'chat-session-row'" in jsx
    assert "<ChatSessionRow key={s.id} session={s}" in jsx
    assert "slot:chat-session-menu:' + sid" in jsx
    assert "sessions.chat.row.open" in jsx
    assert "sessions.chat.row.menu.toggle" in jsx
    assert "const ensureGrandMapChatPanelHeaderNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-header'" in jsx
    assert '<UiNodeSurface rootId={chatPanelHeaderRoot} surface="chat-panel-header"/>' in jsx
    assert "sessions.chat.panel.menu.toggle" in jsx
    assert "const ensureGrandMapChatPanelSearchNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-search'" in jsx
    assert '<UiNodeSurface rootId={chatPanelSearchRoot} surface="chat-panel-search"/>' in jsx
    assert "sessions.chat.search.update" in jsx
    assert "const ensureGrandMapChatPanelListNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-list'" in jsx
    assert "const ChatPanelListSurface = ({ children }) =>" in jsx
    assert "<ChatPanelListSurface>" in jsx
    assert "const ensureGrandMapChatPanelMessageNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'chat-panel-message'" in jsx
    assert "const ChatPanelMessageSurface = ({ message }) =>" in jsx
    assert "<ChatPanelMessageSurface message=" in jsx
    assert "const ensureGrandMapSkillsPanelHeaderNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'skills-panel-header'" in jsx
    assert '<UiNodeSurface rootId={skillsPanelHeaderRoot} surface="skills-panel-header"/>' in jsx
    assert "skills.save.current" in jsx
    assert "const ensureGrandMapSkillsPanelSearchNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'skills-panel-search'" in jsx
    assert '<UiNodeSurface rootId={skillsPanelSearchRoot} surface="skills-panel-search"/>' in jsx
    assert "skills.search.update" in jsx
    assert "const ensureGrandMapSkillsPanelListNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'skills-panel-list'" in jsx
    assert "const SkillsPanelListSurface = ({ children }) =>" in jsx
    assert "<SkillsPanelListSurface>" in jsx
    assert "const ensureGrandMapSkillsPanelMessageNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'skills-panel-message'" in jsx
    assert "const SkillsPanelMessageSurface = ({ message }) =>" in jsx
    assert "<SkillsPanelMessageSurface message=" in jsx
    assert '<div className="ah-scroll" style={{ flex:1, overflow:\'auto\', padding:\'0 6px 8px\'' not in skills_panel
    assert "const ensureGrandMapSkillsPanelRowNodes = (skill, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'skills-panel-row'" in jsx
    assert "<SkillsPanelRow key={s.id || s.name} skill={s}" in jsx
    assert "skills.row.spawn" in jsx
    assert "skills.row.view-json" in jsx
    assert "const _uiNodeData = (nodes, node) =>" in jsx
    assert "const paramNodeIds = Array.isArray(data.param_nodes)" in jsx
    assert "window.ahSetUiNodeParam = function (id, key, value)" in jsx
    assert "var param = params.find(function (p) { return p && p.k === key; });" in jsx
    assert "g.nodes.push(paramNode);" in jsx
    assert "n.config[key] = value;" in jsx
    assert "const ensureGrandMapSessionActionMenuNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'home-session-action-menu'" in jsx
    assert "ensureGrandMapSessionActionMenuNodes()" in jsx
    assert "const ensureGrandMapComposerActionsNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-composer-actions'" in jsx
    assert "const seedGrandMapComposerActionsFallbackNodes = (recording) =>" in jsx
    assert "ensureGrandMapComposerActionsNodes({" in jsx
    assert "const ensureGrandMapComposerBodyNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'home-composer-body'" in jsx
    assert "const seedGrandMapComposerBodyFallbackNodes = (slots) =>" in jsx
    assert "ensureGrandMapComposerBodyNodes({" in jsx
    assert "const ensureGrandMapCanvasComposerBodyNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-composer-body'" in jsx
    assert "const seedGrandMapCanvasComposerBodyFallbackNodes = (slots) =>" in jsx
    assert "ensureGrandMapCanvasComposerBodyNodes({" in jsx
    assert "const ensureGrandMapCanvasComposerHelpNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-composer-help'" in jsx
    assert "ensureGrandMapCanvasComposerHelpNodes()" in jsx
    assert "const ensureGrandMapCanvasToolbarNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-toolbar'" in jsx
    assert "const seedGrandMapCanvasToolbarFallbackNodes = (slots) =>" in jsx
    assert "ensureGrandMapCanvasToolbarNodes({" in jsx
    assert "const ensureGrandMapCanvasHomeActionsNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-home-actions'" in jsx
    assert "ensureGrandMapCanvasHomeActionsNodes()" in jsx
    assert "const ensureGrandMapCanvasModelPickerNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-model-picker'" in jsx
    assert "ensureGrandMapCanvasModelPickerNodes({" in jsx
    assert "const ensureGrandMapModelPickerModalNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'model-picker-modal'" in jsx
    assert "ensureGrandMapModelPickerModalNodes({" in jsx
    assert "const ensureGrandMapModelPickerGroupNodes = (group, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'model-picker-group'" in jsx
    assert "const ensureGrandMapModelPickerRowNodes = (modelItem, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'model-picker-row'" in jsx
    assert "const ensureGrandMapCanvasRouterStatusNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-router-status'" in jsx
    assert "ensureGrandMapCanvasRouterStatusNodes({ label: shown })" in jsx
    assert "const ensureGrandMapCanvasBrainChipNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-brain-chip'" in jsx
    assert "ensureGrandMapCanvasBrainChipNodes({ label, state: brainState })" in jsx
    assert "const ensureGrandMapCanvasAccountChipNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-account-chip'" in jsx
    assert "ensureGrandMapCanvasAccountChipNodes({" in jsx
    assert "const ensureGrandMapCanvasAccountMenuNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-account-menu'" in jsx
    assert "ensureGrandMapCanvasAccountMenuNodes({ email })" in jsx
    assert "const ensureGrandMapAccountIdentityNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'account-identity-footer'" in jsx
    assert '<UiNodeSurface rootId={rootId} surface="account-identity-footer"/>' in jsx
    assert "account.identity.signin" in jsx
    assert "const ensureGrandMapCanvasNewSessionActionNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-new-session-action'" in jsx
    assert "ensureGrandMapCanvasNewSessionActionNodes()" in jsx
    assert "const ensureGrandMapCanvasSessionTabNodes = (session, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-session-tab'" in jsx
    assert "ensureGrandMapCanvasSessionTabNodes(session, { isActive })" in jsx
    assert "const ensureGrandMapCanvasSessionActionsNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-session-actions'" in jsx
    assert "ensureGrandMapCanvasSessionActionsNodes()" in jsx
    assert "<CanvasModelPickerSurface" in ws_header_jsx
    assert "<CanvasHomeActionsSurface" in ws_header_jsx
    assert "rail.home.open" in ws_header_jsx
    assert "<CanvasNewSessionActionSurface" in ws_header_jsx
    assert "<CanvasSessionTabSurface" in ws_header_jsx
    assert "sessions.tab.activate" in ws_header_jsx
    assert "sessions.tab.close" in ws_header_jsx
    assert "<CanvasSessionActionsSurface" in ws_header_jsx
    assert "canvas.session.fork" in ws_header_jsx
    assert "canvas.session.save-skill" in ws_header_jsx
    assert "canvas.session.save" in ws_header_jsx
    assert "ensureGrandMapCanvasSessionActionsNodes()" not in first_run_jsx
    assert "const ensureGrandMapCanvasContextMenuNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-context-menu'" in jsx
    assert "ensureGrandMapCanvasContextMenuNodes({" in jsx
    assert "const ensureGrandMapWireContextMenuNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'wire-context-menu'" in jsx
    assert "ensureGrandMapWireContextMenuNodes({" in jsx
    assert "const ensureGrandMapNodeContextMenuNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-context-menu'" in jsx
    assert "ensureGrandMapNodeContextMenuNodes({" in jsx
    assert "const ensureGrandMapCanvasGestureHintNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-gesture-hint'" in jsx
    assert "ensureGrandMapCanvasGestureHintNodes()" in jsx
    assert "const ensureGrandMapGraphHealthBadgeNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'graph-health-badge'" in jsx
    assert "ensureGrandMapGraphHealthBadgeNodes({" in jsx
    assert "const ensureGrandMapGraphHealthIssueRowNodes = (issue, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'graph-health-issue-row'" in jsx
    assert "ensureGrandMapGraphHealthIssueRowNodes(issue, index)" in jsx
    assert "const ensureGrandMapHealthStripItemNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'health-strip-item'" in jsx
    assert "ensureGrandMapHealthStripItemNodes({" in jsx
    assert "const ensureGrandMapWirePromotePaletteNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'wire-promote-palette'" in jsx
    assert "ensureGrandMapWirePromotePaletteNodes({" in jsx
    assert "const ensureGrandMapWirePromoteResultRowNodes = (result, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'wire-promote-result-row'" in jsx
    assert "ensureGrandMapWirePromoteResultRowNodes(result, { index, active })" in jsx
    assert "wire-promote.query.update" in jsx
    assert "wire-promote.result.pick" in jsx
    assert "wire-promote.submit" in jsx
    assert "const ensureGrandMapNodePaletteHeaderNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-header'" in jsx
    assert "ensureGrandMapNodePaletteHeaderNodes()" in jsx
    assert "const ensureGrandMapNodePaletteSearchNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-search'" in jsx
    assert "ensureGrandMapNodePaletteSearchNodes({" in jsx
    assert "const ensureGrandMapNodePaletteListNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-list'" in jsx
    assert "const NodePaletteListSurface = ({ children }) =>" in jsx
    assert "<NodePaletteListSurface>" in jsx
    assert "const ensureGrandMapNodePaletteContextMenuNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-context-menu'" in jsx
    assert "const NodePaletteContextMenuSurface = ({ children, x, y }) =>" in jsx
    assert "const ensureGrandMapNodePaletteItemNodes = (item, cat, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-item'" in jsx
    assert "ensureGrandMapNodePaletteItemNodes(it, cat, {" in jsx
    assert "nodes.palette.item.add" in jsx
    assert "nodes.palette.item.pin.toggle" in jsx
    assert "const ensureGrandMapNodePaletteSectionHeaderNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-section-header'" in jsx
    assert "ensureGrandMapNodePaletteSectionHeaderNodes({" in jsx
    assert "nodes.palette.section.toggle" in jsx
    assert "const ensureGrandMapNodePaletteMenuItemNodes = (item, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-menu-item'" in jsx
    assert "<PaletteMenuItem key={i} item={it} index={i}/>" in jsx
    assert "nodes.palette.menu.item.run" in jsx
    assert "const ensureGrandMapNodePaletteSkillSidecarNodes = (skill, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'node-palette-skill-sidecar'" in jsx
    assert "<PaletteSkillSidecar skill={s} isShared={isShared}" in jsx
    assert "nodes.palette.skill.promote" in jsx
    assert "props.onDoubleClick = emitDoubleAction;" in jsx
    assert "key:'drag_action'" in jsx
    assert "action:d.drag_action || 'ui.drag.start'" in jsx
    assert "const dragActionAuthority = actionAuthorityFor('drag_action'" in jsx
    assert "props.draggable = !!effectiveDragAction;" in jsx
    assert "props.onDragStart = effectiveDragAction ? (e) =>" in jsx
    assert "materializeUiActionDispatchRoute(" in jsx
    assert "action_key:'drag_action'" in jsx
    assert "if (d.rows !== undefined) props.rows = d.rows;" in jsx
    assert "if (d.auto_grow) {" in jsx
    assert "const ensureGrandMapNewSessionActionNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'home-new-session-action'" in jsx
    assert "ensureGrandMapNewSessionActionNodes()" not in jsx
    assert "const ensureGrandMapAppRailNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'app-rail'" in jsx
    assert "ensureGrandMapAppRailNodes({" in jsx
    assert "const ensureGrandMapStatusStripNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'status-strip'" in jsx
    assert "ensureGrandMapStatusStripNodes({" in jsx
    assert "const wireVersionToApplicationNode = () =>" in jsx
    assert "action: 'application.focus'" in jsx
    assert "args: { node_id: ARCHHUB_APPLICATION_SUPER_NODE_ID }" in jsx
    assert "const ensureGrandMapRailMinimapNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'rail-minimap'" in jsx
    assert "ensureGrandMapRailMinimapNodes({" in jsx
    assert "const ensureGrandMapRailMinimapNodeRectNodes = (node, style) =>" in jsx
    assert "get_grand_map_ui_surface', 'rail-minimap-node-rect'" in jsx
    assert "const ensureGrandMapConversationScrollbackNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-scrollback'" in jsx
    assert "const ensureGrandMapConversationReasoningNodes = (nodeId, ix, open, count) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-reasoning'" in jsx
    assert "const ensureGrandMapConversationReasoningStepNodes = (reasoningId, step, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-reasoning-step'" in jsx
    assert "const ensureGrandMapConversationCompactExpandNodes = (nodeId, total) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-compact-expand'" in jsx
    assert "const ensureGrandMapConversationCompactTurnNodes = (nodeId, m, ix) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-compact-turn'" in jsx
    assert "const ensureGrandMapConversationRouteMetaNodes = (nodeId, ix) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-route-meta'" in jsx
    assert "const ensureGrandMapConversationRouteMetaRowNodes = (metaId, route, index) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-route-meta-row'" in jsx
    assert "const ensureGrandMapConversationNodeScrollbackNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-node-scrollback'" in jsx
    assert "const ensureGrandMapConversationSearchEmptyNodes = (query) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-search-empty'" in jsx
    assert "const ensureGrandMapConversationAIBodyExpandedNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-ai-body-expanded'" in jsx
    assert "const ensureGrandMapConversationAIBodyCompactNodes = () =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-ai-body-compact'" in jsx
    assert "const ensureGrandMapConversationSearchBarNodes = (nodeId, slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-search-bar'" in jsx
    assert "const ensureGrandMapConversationReplyComposerNodes = (nodeId, reply) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-reply-composer'" in jsx
    assert "const ensureGrandMapConversationExpandedTurnNodes = (nodeId, m, ix) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-expanded-turn'" in jsx
    assert "const ensureGrandMapConversationClippedTextNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'conversation-clipped-text'" in jsx
    assert "lm-ui-node-action" in jsx
    assert "session.create" in jsx
    assert "sessions.filter.set" in jsx
    assert "sessions.select.toggle" in jsx
    assert "sessions.select.visible.toggle" in jsx
    assert "sessions.selected.delete" in jsx
    assert "sessions.select.cancel" in jsx
    assert "sessions.card.activate" in jsx
    assert "sessions.card.menu.toggle" in jsx
    assert "sessions.menu.action" in jsx
    assert "composer.attach" in jsx
    assert "composer.voice.toggle" in jsx
    assert "composer.submit" in jsx
    assert "composer.text.update" in jsx
    assert "composer.form.submit" in jsx
    assert "canvas.composer.submit" in jsx
    assert "canvas.composer.text.update" in jsx
    assert "canvas.composer.mode.set" in jsx
    assert "canvas.toolbar.zoom.in" in jsx
    assert "canvas.toolbar.run" in jsx
    assert "canvas.menu.add-node" in jsx
    assert "canvas.menu.snap.toggle" in jsx
    assert "wire.menu.pick-source" in jsx
    assert "wire.menu.disconnect" in jsx
    assert "node.menu.run" in jsx
    assert "node.menu.delete" in jsx
    assert "canvas-gesture-hint" in jsx
    assert "graph-health-badge" in jsx
    assert "graph-health-issue-row" in jsx
    assert "graph-health.issue.focus" in jsx
    assert "health-strip-item" in jsx
    assert "health-strip.toggle" in jsx
    assert "health-strip.self-heal" in jsx
    assert "rail-minimap" in jsx
    assert "rail-minimap-node-rect" in jsx
    assert "rail-minimap.jump" in jsx
    assert "conversation-scrollback" in jsx
    assert "conversation-reasoning" in jsx
    assert "conversation-reasoning-step" in jsx
    assert "conversation.reasoning.toggle" in jsx
    assert "conversation-compact-expand" in jsx
    assert "conversation.compact.expand" in jsx
    assert "conversation-compact-turn" in jsx
    assert "conversation-route-meta" in jsx
    assert "conversation-route-meta-row" in jsx
    assert "conversation-node-scrollback" in jsx
    assert "conversation-search-empty" in jsx
    assert "conversation-ai-body-expanded" in jsx
    assert "conversation-ai-body-compact" in jsx
    assert "conversation-search-bar" in jsx
    assert "conversation.search.update" in jsx
    assert "conversation.search.clear" in jsx
    assert "conversation-reply-composer" in jsx
    assert "conversation.reply.update" in jsx
    assert "conversation.reply.submit" in jsx
    assert "conversation-expanded-turn" in jsx
    assert "conversation-clipped-text" in jsx
    assert "conversation.clipped-text.toggle" in jsx
    assert "nodes.palette.search.update" in jsx
    assert "nodes.palette.sort.toggle" in jsx
    assert "sessions.sync" in jsx
    assert "rail.home.open" in jsx
    assert "rail.search.open" in jsx
    assert "rail.share.open" in jsx
    assert "settings.open" in jsx
    assert "memory.open" in jsx
    assert "graph.health.open" in jsx

    assert "model.picker.open" in jsx
    assert "model-picker-modal" in jsx
    assert "model-picker-row" in jsx
    assert "model-picker.pick" in jsx
    assert "account.open" in jsx
    assert "brain.folders.open" in jsx
    assert "graph.health.open" in jsx
    assert "data-action" in jsx
    assert "<ModelStrip model={model} setPickerOpen={setPickerOpen}/>" not in home_jsx
    assert "<BrainChip/>" not in home_jsx
    assert "<AccountChip compact/>" not in home_jsx
    assert "<HomeGraphHealthChip/>" not in home_jsx
    assert "graph={homeTopGraphLabel}" in jsx
    assert "flexWrap:'wrap', minWidth:0" in jsx
    assert "<h2 style={{ fontFamily:LM.serif, fontSize:26, fontWeight:400, letterSpacing:'-0.015em', margin:0 }}>Sessions</h2>" not in jsx
    assert "<button onClick={()=>onCreateSession&&onCreateSession('untitled')} style={chipBtn(true)}>+ new canvas</button>" not in jsx
    assert "<SyncSessionsButton/>" not in jsx
    assert "const SyncSessionsButton = () =>" not in jsx
    assert "['all','mine','workflows'].map" not in jsx
    assert 'data-testid="session-select-toggle"' not in jsx
    assert 'data-testid="session-select-toolbar"' not in jsx
    assert 'data-testid="session-delete-selected"' not in jsx
    assert "data-testid={'session-select-' + s.id}" not in jsx
    assert "{ k:'rename',    t:'Rename' }" not in jsx
    assert "{ k:'delete',    t:'Delete', danger:true }" not in jsx
    assert "title={recording ? 'Stop recording' : 'Voice input'}" not in jsx
    assert "<textarea value={title} onChange={e => setTitle(e.target.value)}" not in jsx
    assert "<textarea ref={inputRef} value={text} rows={1}" not in jsx
    assert "title={recording ? 'Stop recording' : 'Voice input (browser SpeechRecognition)'}" not in jsx
    assert "<div style={{ color:LM.accent, marginBottom:4 }}>SLASH COMMANDS</div>" not in jsx
    assert "<div>/wire   <span style={{ color:LM.inkMuted }}>connect two nodes by name</span></div>" not in jsx
    assert "<button onClick={(e) => { e.stopPropagation(); setZoom(z => Math.min(2, +(z + 0.1).toFixed(2)))" not in jsx
    assert "<button onClick={(e) => { e.stopPropagation(); onRun && onRun();" not in jsx
    assert "t:'Snap to grid'" not in jsx
    assert "it.toggle" not in jsx
    assert "t:dstFrozen ? 'Unfreeze target' : 'Freeze target'" not in jsx
    assert "t:'Disconnect',              on:onDisconnect" not in jsx
    assert "t:'Run',             on:onRun" not in jsx
    assert "t:'Delete',          on:onDelete" not in jsx
    assert "<span>scroll" not in jsx
    assert "<span>right-click" not in jsx
    assert "attachments.map((a, i) =>" not in jsx
    assert "ensureHomeTopUiNodes({" in jsx
    assert "if (window.archhub) return null;" in jsx
    assert "modelName={model && model.name}" in jsx
    assert "sessionCount={sessions.length}" in jsx
    assert "if (__grandMapUiHomeTopPending) return 'ui:grandmap:home-top';" in jsx
    assert "if (__grandMapSessionsHeaderPending) return 'ui:grandmap:sessions-header';" in jsx
    assert "if (__grandMapSessionToolbarPending) return 'ui:grandmap:session-toolbar';" in jsx
    assert "if (__grandMapSelectionToolbarPending) return 'ui:grandmap:selection-toolbar';" in jsx
    assert "if (__grandMapHomeEmptyStatePending) return rootId;" in jsx
    assert "const seedGrandMapSessionsHeaderFallbackNodes = () =>" in jsx
    assert "const seedGrandMapSessionToolbarFallbackNodes = () =>" in jsx
    assert "const seedGrandMapHomeEmptyStateFallbackNodes = (message) =>" in jsx
    assert "fallback_home_surface: true" in jsx
    assert "if (__grandMapNodePaletteHeaderPending) return rootId;" in jsx
    assert "if (__grandMapNodePaletteSearchPending) return rootId;" in jsx
    assert "if (__grandMapNewSessionActionPending) return 'ui:grandmap:new-session-action';" in jsx
    assert "if (__grandMapCanvasHomeActionsPending) return rootId;" in jsx
    assert "if (__grandMapCanvasNewSessionActionPending) return rootId;" in jsx
    assert "if (__grandMapCanvasSessionTabTemplatePending) return rootId;" in jsx
    assert "if (__grandMapCanvasRouterStatusPending) return rootId;" in jsx
    assert "if (__grandMapCanvasBrainChipPending) return rootId;" in jsx
    assert "if (__grandMapCanvasAccountChipPending) return rootId;" in jsx
    assert "if (__grandMapCanvasAccountMenuPending) return rootId;" in jsx
    assert "props['data-state'] = String(_uiBindingValue(nodes, wires, id, 'state_bind', d.state_bind));" in jsx
    assert "} else if (d.tag === 'input') {" in jsx
    assert "props.onChange = (e) => emitAction(e, { value: e && e.target ? e.target.value : '' });" in jsx

    bridge_call = jsx.index("get_grand_map_ui_surface")
    fallback_seed = jsx.index("add('ui:ht-arch'")
    assert bridge_call < fallback_seed

def test_ui_param_writer_bumps_only_on_real_graph_change():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "const _uiParamValueEquals = (a, b) =>" in jsx
    writer = jsx[
        jsx.index("window.ahSetUiNodeParam = function"):
        jsx.index("window.ahEditUiNode = function", jsx.index("window.ahSetUiNodeParam = function"))
    ]
    assert "var changed = false;" in writer
    assert "if (!_uiParamValueEquals(param.v, value)) changed = true;" in writer
    assert "if (!_uiParamValueEquals(n.config[key], value)) changed = true;" in writer
    assert "if (!_uiParamValueEquals(n.data[key], value)) changed = true;" in writer
    assert "if (changed && !window.__archhub_suppress_ui_param_bump)" in writer


def test_inline_node_field_writer_does_not_create_property_params():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    writer = jsx[
        jsx.index("const setGrandMapInlineNodeField ="):
        jsx.index("const resetClonedUiNodeParamLinks =", jsx.index("const setGrandMapInlineNodeField ="))
    ]

    assert "node.data = Object.assign({}, node.data || {}, { [key]: value });" in writer
    assert "node.config = Object.assign({}, node.config || {}, { [key]: value });" in writer
    assert "node.params.push" not in writer
    assert "const param = node.params.find" not in writer
    assert "if (key === 'title') node.title" in writer


def test_surface_slot_writer_updates_inline_without_child_param_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    slot_writer = jsx[
        jsx.index("const putGrandMapSlot ="):
        jsx.index("const resetClonedUiNodeParamLinks =", jsx.index("const putGrandMapSlot ="))
    ]
    assert "n.data = Object.assign({}, n.data || {});" in slot_writer
    assert "n.config = Object.assign({}, n.config || {});" in slot_writer
    assert "n.data.value = slotValue;" in slot_writer
    assert "n.config.value = slotValue;" in slot_writer
    assert "n.params.push({ k:'value', label:'value', type:'text', v:slotValue });" in slot_writer
    assert "window.ahSetUiNodeParam(id, 'value'" not in slot_writer


def test_cloned_ui_param_sync_suppresses_graph_wide_bumps():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    sync = jsx[
        jsx.index("const syncClonedUiNodeParams ="):
        jsx.index("const finishClonedUiNodeParamAuthority =", jsx.index("const syncClonedUiNodeParams ="))
    ]
    helper = jsx[
        jsx.index("const materializeGrandMapParamNode ="):
        jsx.index("const ensureGrandMapFocusableParamNode =", jsx.index("const materializeGrandMapParamNode ="))
    ]
    assert "materializeGrandMapParamNode(copy, p.k, copy.data[p.k])" in sync
    assert "withSuppressedUiParamBumps(write);" in helper
    assert "window.ahSetUiNodeParam(copy.id, p.k, copy.data[p.k]);" not in sync


def test_focused_right_rail_surfaces_use_targeted_wakeup_not_graph_bump():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ranges = [
        ("ensureGrandMapNodeRailShellNodes", "const nodeRailParamItems ="),
        ("ensureGrandMapNodePropertiesPanelNodes", "const cloneGrandMapNodeActionsPanelTemplate ="),
        ("ensureGrandMapNodeActionsPanelNodes", "const cloneGrandMapNodeSummaryPanelTemplate ="),
        ("ensureGrandMapNodeSummaryPanelNodes", "const nodeConnectionEndpointNode ="),
        ("ensureGrandMapNodeConnectionsPanelNodes", "const cloneGrandMapConnectorRailShellTemplate ="),
    ]
    for name, end_marker in ranges:
        ensure = jsx[
            jsx.index(f"const {name} ="):
            jsx.index(end_marker, jsx.index(f"const {name} ="))
        ]
        assert "archhub-ui-surface-imported" in ensure, name
        assert "window.dispatchEvent(new Event('lm-graph-bump'))" not in ensure, name


def test_update_notifier_hydrates_banner_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    update_notifier = jsx[
        jsx.index("function UpdateNotifier()"):
        jsx.index("// AgDR-0036 follow-up", jsx.index("function UpdateNotifier()"))
    ]

    assert "const ensureGrandMapUpdateNotifierNodes = (avail, busy) =>" in jsx
    assert "get_grand_map_ui_surface', 'update-notifier'" in jsx
    assert "syncGrandMapSurfaceStateSlots('update-notifier', rootId, slotMap" in jsx
    assert "'slot:update-current': avail.current || '?'" in jsx
    assert "'slot:update-latest': avail.latest || 'latest'" in jsx
    assert "'slot:update-busy': busy ? 'true' : 'false'" in jsx
    assert "update.relaunch" in update_notifier
    assert 'surface="update-notifier"' in update_notifier
    assert "data-testid=\"update-banner\"" not in update_notifier
    assert "style={{" not in update_notifier


def test_global_toast_hydrates_notification_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    global_toast = jsx[
        jsx.index("const GlobalToastInner ="):
        jsx.index("const GlobalToast = React.memo", jsx.index("const GlobalToastInner ="))
    ]

    assert "const ensureGrandMapGlobalToastNodes = (toast) =>" in jsx
    assert "get_grand_map_ui_surface', 'global-toast'" in jsx
    assert "syncGrandMapSurfaceStateSlots('global-toast', rootId, slotMap" in jsx
    assert "'slot:global-toast-message': toast.msg || ''" in jsx
    assert "'slot:global-toast-kind': toast.kind || 'info'" in jsx
    assert 'surface="global-toast"' in global_toast
    assert "ah-global-toast-node" in global_toast
    assert "const col = toast.kind" not in global_toast
    assert "position:'fixed', bottom:24" not in global_toast
    assert ">{toast.msg}</div>" not in global_toast


def test_canvas_toast_hydrates_canvas_notification_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    canvas_toast = jsx[
        jsx.index("const CanvasToastSurface ="):
        jsx.index("const NodeCanvasInner =", jsx.index("const CanvasToastSurface ="))
    ]
    node_canvas_render = jsx[
        jsx.index("const NodeCanvasInner ="):
        jsx.index("const NodeCanvas =", jsx.index("const NodeCanvasInner ="))
    ]

    assert "const ensureGrandMapCanvasToastNodes = (toast) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-toast'" in jsx
    assert "syncGrandMapSurfaceStateSlots('canvas-toast', rootId, slotMap" in jsx
    assert "'slot:canvas-toast-message': toast.msg || ''" in jsx
    assert "'slot:canvas-toast-kind': toast.kind || 'info'" in jsx
    assert 'surface="canvas-toast"' in canvas_toast
    assert "ah-canvas-toast-node" in canvas_toast
    assert "const toast = useArchHubToastChannel('canvas');" in canvas_toast
    assert "<CanvasToastSurface/>" in node_canvas_render
    assert "const ARCHHUB_TOAST_CHANNEL_NODE_ID = 'state:archhub:toast-channel';" in jsx
    assert "wire_family:'toast_presentation'" in jsx
    assert "!relation.relationNode || !relation.allowed" in jsx
    assert "window.addEventListener('lm-canvas-toast', ev => publishArchHubToast" in jsx
    assert "<CanvasToastSurface toast={toast}/>" not in node_canvas_render
    assert "<div data-no-pan style={{" not in node_canvas_render
    assert ">{toast.msg}</div>" not in node_canvas_render


def test_update_and_toast_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    update = jsx[
        jsx.index("const ensureGrandMapUpdateNotifierNodes ="):
        jsx.index(
            "const ensureGrandMapGlobalToastNodes =",
            jsx.index("const ensureGrandMapUpdateNotifierNodes ="),
        )
    ]
    global_toast = jsx[
        jsx.index("const ensureGrandMapGlobalToastNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasToastNodes =",
            jsx.index("const ensureGrandMapGlobalToastNodes ="),
        )
    ]
    canvas_toast = jsx[
        jsx.index("const ensureGrandMapCanvasToastNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasGroupDialogNodes =",
            jsx.index("const ensureGrandMapCanvasToastNodes ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('update-notifier', rootId, slotMap" in update
    assert "state_key: 'update_notifier_state_node_id'" in update
    assert "'slot:update-relaunch-label': busy ? 'Relaunching...' : 'Relaunch to update'" in update
    assert "syncGrandMapSurfaceStateSlots('global-toast', rootId, slotMap" in global_toast
    assert "state_key: 'global_toast_state_node_id'" in global_toast
    assert "'slot:global-toast-kind': toast.kind || 'info'" in global_toast
    assert "syncGrandMapSurfaceStateSlots('canvas-toast', rootId, slotMap" in canvas_toast
    assert "state_key: 'canvas_toast_state_node_id'" in canvas_toast
    assert "'slot:canvas-toast-kind': toast.kind || 'info'" in canvas_toast


def test_canvas_group_dialog_hydrates_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    group_dialog = jsx[
        jsx.index("const GroupDialog ="):
        jsx.index("// SLICE G", jsx.index("const GroupDialog ="))
    ]
    renderer_input = jsx[
        jsx.index("} else if (d.tag === 'input') {"):
        jsx.index("} else if (d.tag === 'select') {", jsx.index("} else if (d.tag === 'input') {"))
    ]

    assert "const ensureGrandMapCanvasGroupDialogNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-group-dialog'" in jsx
    assert "syncGrandMapSurfaceStateSlots('canvas-group-dialog', rootId, slotMap" in jsx
    assert "state_key: 'canvas_group_dialog_state_node_id'" in jsx
    assert "materialize_param_nodes: true" in jsx[
        jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="):
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes =", jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="))
    ]
    assert "materialize_wire_anatomy: true" in jsx[
        jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="):
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes =", jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="))
    ]
    assert "wire_family: 'surface_state_field'" in jsx[
        jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="):
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes =", jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="))
    ]
    assert "'slot:group-title': title" in jsx
    assert "'slot:group-style': style" in jsx
    assert "canvas.group.title.update" in group_dialog
    assert "canvas.group.style.set" in group_dialog
    assert "canvas.group.create" in group_dialog
    assert 'surface="canvas-group-dialog"' in group_dialog
    assert "<UiNodeSurface rootId={rootId} surface=\"canvas-group-dialog\"/>" in group_dialog
    assert "submit_action" in renderer_input
    assert "action: dispatch.action || effectiveSubmitAction" in renderer_input
    assert "<input autoFocus value={title}" not in group_dialog
    assert "GROUP_STYLES.map(s =>" not in group_dialog
    assert "<button onClick={submit}" not in group_dialog


def test_canvas_save_skill_dialog_hydrates_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    save_dialog = jsx[
        jsx.index("const SaveSkillDialog ="):
        jsx.index("const LM_GRAPH", jsx.index("const SaveSkillDialog ="))
    ]

    assert "const ensureGrandMapCanvasSaveSkillDialogNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'canvas-save-skill-dialog'" in jsx
    assert "syncGrandMapSurfaceStateSlots('canvas-save-skill-dialog', rootId, slotMap" in jsx
    assert "state_key: 'canvas_save_skill_dialog_state_node_id'" in jsx
    assert "materialize_param_nodes: true" in jsx[
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="):
        jsx.index("const ensureGrandMapCreateNodeModalNodes =", jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="))
    ]
    assert "materialize_wire_anatomy: true" in jsx[
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="):
        jsx.index("const ensureGrandMapCreateNodeModalNodes =", jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="))
    ]
    assert "wire_family: 'surface_state_field'" in jsx[
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="):
        jsx.index("const ensureGrandMapCreateNodeModalNodes =", jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="))
    ]
    assert "'slot:save-skill-name': name" in jsx
    assert "'slot:save-skill-description': description" in jsx
    assert "'slot:save-skill-category': category" in jsx
    assert "'slot:save-skill-mode': mode" in jsx
    assert "canvas.save-skill.name.update" in save_dialog
    assert "canvas.save-skill.description.update" in save_dialog
    assert "canvas.save-skill.category.update" in save_dialog
    assert "canvas.save-skill.mode.set" in save_dialog
    assert "canvas.save-skill.save" in save_dialog
    assert 'surface="canvas-save-skill-dialog"' in save_dialog
    assert "<UiNodeSurface rootId={rootId} surface=\"canvas-save-skill-dialog\"/>" in save_dialog
    assert "<input autoFocus value={name}" not in save_dialog
    assert "<textarea value={description}" not in save_dialog
    assert "MODE_OPTS.map(opt =>" not in save_dialog
    assert "rootStyle={{" not in save_dialog


def test_create_node_modal_hydrates_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    create_modal = jsx[
        jsx.index("const CreateNodeModal ="):
        jsx.index("const modalInput = () =>", jsx.index("const CreateNodeModal ="))
    ]

    assert "const ensureGrandMapCreateNodeModalNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'create-node-modal'" in jsx
    assert "syncGrandMapSurfaceStateSlots('create-node-modal', rootId, slotMap" in jsx
    assert "state_key: 'create_node_modal_state_node_id'" in jsx
    assert "materialize_param_nodes: true" in jsx[
        jsx.index("const ensureGrandMapCreateNodeModalNodes ="):
        jsx.index("const aiNodePortLabel =", jsx.index("const ensureGrandMapCreateNodeModalNodes ="))
    ]
    assert "materialize_wire_anatomy: true" in jsx[
        jsx.index("const ensureGrandMapCreateNodeModalNodes ="):
        jsx.index("const aiNodePortLabel =", jsx.index("const ensureGrandMapCreateNodeModalNodes ="))
    ]
    assert "wire_family: 'surface_state_field'" in jsx[
        jsx.index("const ensureGrandMapCreateNodeModalNodes ="):
        jsx.index("const aiNodePortLabel =", jsx.index("const ensureGrandMapCreateNodeModalNodes ="))
    ]
    assert "'slot:create-node-type': type" in jsx
    assert "'slot:create-node-category': cat" in jsx
    assert "'slot:create-node-inputs': inputs" in jsx
    assert "'slot:create-node-outputs': outputs" in jsx
    assert "create-node.type.update" in create_modal
    assert "create-node.category.update" in create_modal
    assert "create-node.inputs.update" in create_modal
    assert "create-node.outputs.update" in create_modal
    assert "create-node.create" in create_modal
    assert 'surface="create-node-modal"' in create_modal
    assert "<UiNodeSurface rootId={rootId} surface=\"create-node-modal\"/>" in create_modal
    assert "<SField label=\"Type ID\"" not in create_modal
    assert "onChange={e=>setType" not in create_modal
    assert "<button onClick={submit}" not in create_modal


def test_canvas_dialog_form_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    group = jsx[
        jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="):
        jsx.index(
            "const ensureGrandMapCanvasSaveSkillDialogNodes =",
            jsx.index("const ensureGrandMapCanvasGroupDialogNodes ="),
        )
    ]
    save = jsx[
        jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="):
        jsx.index(
            "const ensureGrandMapCreateNodeModalNodes =",
            jsx.index("const ensureGrandMapCanvasSaveSkillDialogNodes ="),
        )
    ]
    create = jsx[
        jsx.index("const ensureGrandMapCreateNodeModalNodes ="):
        jsx.index(
            "const aiNodePortLabel =",
            jsx.index("const ensureGrandMapCreateNodeModalNodes ="),
        )
    ]

    assert "syncGrandMapSurfaceStateSlots('canvas-group-dialog', rootId, slotMap" in group
    assert "state_key: 'canvas_group_dialog_state_node_id'" in group
    assert "'slot:group-selection-count': count + ' nodes in selection'" in group
    assert "syncGrandMapSurfaceStateSlots('canvas-save-skill-dialog', rootId, slotMap" in save
    assert "state_key: 'canvas_save_skill_dialog_state_node_id'" in save
    assert "'slot:save-skill-mode': mode" in save
    assert "syncGrandMapSurfaceStateSlots('create-node-modal', rootId, slotMap" in create
    assert "state_key: 'create_node_modal_state_node_id'" in create
    assert "'slot:create-node-outputs': outputs" in create


def test_ai_node_modal_hydrates_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ai_modal = jsx[
        jsx.index("const AINodeModal ="):
        jsx.index("const FirstRunProfile =", jsx.index("const AINodeModal ="))
    ]

    assert "const ensureGrandMapAINodeModalNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'ai-node-modal'" in jsx
    assert "syncGrandMapSurfaceStateSlots('ai-node-modal', rootId, slotMap" in jsx
    assert "state_key: 'ai_node_modal_state_node_id'" in jsx
    assert "materialize_param_nodes: true" in jsx[
        jsx.index("const updateGrandMapAINodeModalSlots ="):
        jsx.index("const ensureGrandMapAINodeModalNodes =", jsx.index("const updateGrandMapAINodeModalSlots ="))
    ]
    assert "materialize_wire_anatomy: true" in jsx[
        jsx.index("const updateGrandMapAINodeModalSlots ="):
        jsx.index("const ensureGrandMapAINodeModalNodes =", jsx.index("const updateGrandMapAINodeModalSlots ="))
    ]
    assert "wire_family: 'surface_state_field'" in jsx[
        jsx.index("const updateGrandMapAINodeModalSlots ="):
        jsx.index("const ensureGrandMapAINodeModalNodes =", jsx.index("const updateGrandMapAINodeModalSlots ="))
    ]
    assert "'slot:ai-node-desc': desc" in jsx
    assert "'slot:ai-node-can-draft': desc.trim() && phase === 'idle' ? 'true' : 'false'" in jsx
    assert "'slot:ai-node-result-title': resultTitle" in jsx
    assert "ai-node.desc.update" in ai_modal
    assert "ai-node.example.pick" in ai_modal
    assert "ai-node.generate" in ai_modal
    assert "ai-node.reset" in ai_modal
    assert "ai-node.add" in ai_modal
    assert 'surface="ai-node-modal"' in ai_modal
    assert "<UiNodeSurface rootId={rootId} surface=\"ai-node-modal\"/>" in ai_modal
    assert "<textarea autoFocus value={desc}" not in ai_modal
    assert "AINODE_EXAMPLES.map" not in ai_modal
    assert "<button onClick={generate}" not in ai_modal
    assert "<button onClick={addToCanvas}" not in ai_modal


def test_first_run_profile_hydrates_from_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    first_run = jsx[
        jsx.index("const FirstRunProfile ="):
        jsx.index("//", jsx.index("const FirstRunProfile =") + 1)
    ]

    assert "const ensureGrandMapFirstRunProfileNodes = (slots) =>" in jsx
    assert "get_grand_map_ui_surface', 'first-run-profile'" in jsx
    assert "syncGrandMapSurfaceStateSlots('first-run-profile', rootId, slotMap" in jsx
    assert "state_key: 'first_run_profile_state_node_id'" in jsx
    assert "materialize_param_nodes: true" in jsx[
        jsx.index("const ensureGrandMapFirstRunProfileNodes ="):
        jsx.index("const ensureGrandMapCommandDeckShellNodes =", jsx.index("const ensureGrandMapFirstRunProfileNodes ="))
    ]
    assert "materialize_wire_anatomy: true" in jsx[
        jsx.index("const ensureGrandMapFirstRunProfileNodes ="):
        jsx.index("const ensureGrandMapCommandDeckShellNodes =", jsx.index("const ensureGrandMapFirstRunProfileNodes ="))
    ]
    assert "wire_family: 'surface_state_field'" in jsx[
        jsx.index("const ensureGrandMapFirstRunProfileNodes ="):
        jsx.index("const ensureGrandMapCommandDeckShellNodes =", jsx.index("const ensureGrandMapFirstRunProfileNodes ="))
    ]
    assert "'slot:first-run-firm': firm" in jsx
    assert "'slot:first-run-role': role" in jsx
    assert "'slot:first-run-discipline': discipline" in jsx
    assert "'slot:first-run-save-disabled': (saving || !filled) ? 'true' : 'false'" in jsx
    assert "first-run.firm.update" in first_run
    assert "first-run.role.update" in first_run
    assert "first-run.discipline.update" in first_run
    assert "first-run.skip" in first_run
    assert "first-run.save" in first_run
    assert 'surface="first-run-profile"' in first_run
    assert "slot:first-run-wordmark" in first_run
    assert "<SField label=\"Firm / company\"/>" not in first_run
    assert "ROLES.map" not in first_run
    assert "DISCIPLINES.map" not in first_run


def test_ai_profile_and_command_header_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    ai = jsx[
        jsx.index("const updateGrandMapAINodeModalSlots ="):
        jsx.index("const ensureGrandMapFirstRunProfileNodes =", jsx.index("const updateGrandMapAINodeModalSlots ="))
    ]
    first_run = jsx[
        jsx.index("const ensureGrandMapFirstRunProfileNodes ="):
        jsx.index("const ensureGrandMapCommandDeckShellNodes =", jsx.index("const ensureGrandMapFirstRunProfileNodes ="))
    ]
    command_header = jsx[
        jsx.index("const ensureGrandMapCommandDeckHeaderNodes ="):
        jsx.index("const cloneGrandMapCommandDeckTemplate =", jsx.index("const ensureGrandMapCommandDeckHeaderNodes ="))
    ]

    assert "syncGrandMapSurfaceStateSlots('ai-node-modal', rootId, slotMap" in ai
    assert "state_key: 'ai_node_modal_state_node_id'" in ai
    assert "'slot:ai-node-result-outputs': result ? aiNodePortLabel(result.outputs) : 'none'" in ai
    assert "syncGrandMapSurfaceStateSlots('first-run-profile', rootId, slotMap" in first_run
    assert "state_key: 'first_run_profile_state_node_id'" in first_run
    assert "materialize_param_nodes: true" in first_run
    assert "materialize_wire_anatomy: true" in first_run
    assert "wire_family: 'surface_state_field'" in first_run
    assert "'slot:first-run-save-label': saving ? 'Saving...' : 'Save'" in first_run
    assert "syncGrandMapSurfaceStateSlots('command-deck-header', rootId, slotMap" in command_header
    assert "state_key: 'command_deck_header_state_node_id'" in command_header
    assert "'slot:command-deck-refresh-label': slots && slots.loading ? 'Refreshing...' : 'Refresh'" in command_header


def test_command_deck_cloned_surfaces_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapCommandDeckTemplate ="):
        jsx.index("const ensureGrandMapSkillJsonShellNodes =", jsx.index("const cloneGrandMapCommandDeckTemplate ="))
    ]

    assert "const clonedSlotMap = {};" in clone
    assert "clonedSlotMap[mappedId] = slotMap[id];" in clone
    assert "syncGrandMapSurfaceStateSlots(surfaceName, rootId, clonedSlotMap" in clone
    assert "state_key: statePrefix + '_state_node_id'" in clone
    assert "'slot:command-deck-tile-title': tile.title || 'Tile'" in clone
    assert "'slot:command-deck-stat-value': stat.value == null ? '' : String(stat.value)" in clone
    assert "'slot:command-deck-empty-message': (slots && slots.message) || 'Source not reachable right now.'" in clone


def test_compiled_home_surface_uses_node_action_runtime():
    compiled = (_APP / "web_ui" / "studio-lm.compiled.js").read_text(encoding="utf-8")
    home_compiled = compiled[compiled.index("const Home="):compiled.index("const SessionThumb=")]

    assert "home-new-session-action" in compiled
    assert "home-session-toolbar" in compiled
    assert "home-selection-toolbar" in compiled
    assert "home-empty-state" in compiled
    assert "home-session-card" in compiled
    assert "chat-session-row" in compiled
    assert "chat-panel-header" in compiled
    assert "chat-panel-search" in compiled
    assert "chat-panel-list" in compiled
    assert "chat-panel-message" in compiled
    assert "search-panel-scopes-list" in compiled
    assert "search-panel-results-list" in compiled
    assert "skills-panel-header" in compiled
    assert "skills-panel-search" in compiled
    assert "skills-panel-list" in compiled
    assert "skills-panel-message" in compiled
    assert "skills-panel-row" in compiled
    assert "home-session-action-menu" in compiled
    assert "home-composer-actions" in compiled
    assert "home-composer-body" in compiled
    assert "canvas-composer-body" in compiled
    assert "canvas-composer-help" in compiled
    assert "canvas-toolbar" in compiled
    assert "node-output-body" in compiled
    assert "node-output-param-row" in compiled
    assert "node-result-row" in compiled
    assert "node-param-display-row" in compiled
    assert "node-typed-param-row" in compiled
    assert "node-alert-row" in compiled
    assert "node-empty-message" in compiled
    assert "node-progress-row" in compiled
    assert "node-section-label" in compiled
    assert "node-expression-preview" in compiled
    assert "node-port-row" in compiled
    assert "node-action-button" in compiled
    assert "node-stage-preview" in compiled
    assert "node-stage-image-preview" in compiled
    assert "node-stage-text-preview" in compiled
    assert "node-stage-empty-preview" in compiled
    assert "node-preformatted-preview" in compiled
    assert "node-image-preview" in compiled
    assert "node-list-preview" in compiled
    assert "node-list-preview-item" in compiled
    assert "node-table-preview" in compiled
    assert "node-table-header-cell" in compiled
    assert "node-table-row" in compiled
    assert "node-table-cell" in compiled
    assert "node-note-display" in compiled
    assert "node-note-editor" in compiled
    assert "node-choice-tile" in compiled
    assert "node-kv-row" in compiled
    assert "node-output-port-row" in compiled
    assert "node-icon-button" in compiled
    assert "node-markdown-block" in compiled
    assert "node-markdown-list" in compiled
    assert "node-markdown-list-item" in compiled
    assert "node-markdown-inline" in compiled
    assert "node-markdown-link" in compiled
    assert "node-markdown-image" in compiled
    assert "node-output.preview.toggle" in compiled
    assert "node-output.save" in compiled
    assert "canvas-home-actions" in compiled
    assert "canvas-model-picker" in compiled
    assert "model-picker-modal" in compiled
    assert "model-picker-group" in compiled
    assert "model-picker-row" in compiled
    assert "model-picker.query.update" in compiled
    assert "model-picker.pick" in compiled
    assert "canvas-router-status" in compiled
    assert "canvas-brain-chip" in compiled
    assert "canvas-account-chip" in compiled
    assert "canvas-account-menu" in compiled
    assert "account-identity-footer" in compiled
    assert "app-shell" in compiled
    assert "canvas-new-session-action" in compiled
    assert "canvas-session-tab" in compiled
    assert "canvas-session-actions" in compiled
    assert "canvas-context-menu" in compiled
    assert "wire-context-menu" in compiled
    assert "node-context-menu" in compiled
    assert "canvas-gesture-hint" in compiled
    assert "graph-health-badge" in compiled
    assert "graph-health-issue-row" in compiled
    assert "graph-health.open" in compiled
    assert "graph-health.issue.focus" in compiled
    assert "health-strip-item" in compiled
    assert "health-strip.toggle" in compiled
    assert "health-strip.self-heal" in compiled
    assert "rail-minimap" in compiled
    assert "rail-minimap-node-rect" in compiled
    assert "rail-minimap.jump" in compiled
    assert "conversation-scrollback" in compiled
    assert "conversation-compact-expand" in compiled
    assert "conversation.compact.expand" in compiled
    assert "conversation-compact-turn" in compiled
    assert "conversation-route-meta" in compiled
    assert "conversation-route-meta-row" in compiled
    assert "conversation-node-scrollback" in compiled
    assert "conversation-search-empty" in compiled
    assert "conversation-ai-body-expanded" in compiled
    assert "conversation-ai-body-compact" in compiled
    assert "conversation-search-bar" in compiled
    assert "conversation.search.update" in compiled
    assert "conversation.search.clear" in compiled
    assert "conversation-reply-composer" in compiled
    assert "conversation.reply.update" in compiled
    assert "conversation.reply.submit" in compiled
    assert "conversation-expanded-turn" in compiled
    assert "conversation-clipped-text" in compiled
    assert "conversation.clipped-text.toggle" in compiled
    assert "conversation-reasoning" in compiled
    assert "conversation-reasoning-step" in compiled
    assert "conversation.reasoning.toggle" in compiled
    assert "wire-promote-palette" in compiled
    assert "wire-promote-result-row" in compiled
    assert "wire-promote.query.update" in compiled
    assert "wire-promote.result.pick" in compiled
    assert "wire-promote.submit" in compiled
    assert "broken-wire-dialog" in compiled
    assert "broken-wire-row" in compiled
    assert "broken-wire.insert-adapter" in compiled
    assert "broken-wire.delete-anyway" in compiled
    assert "node-palette-header" in compiled
    assert "node-palette-search" in compiled
    assert "node-palette-list" in compiled
    assert "node-palette-context-menu" in compiled
    assert "node-palette-item" in compiled
    assert "node-palette-section-header" in compiled
    assert "node-palette-menu-item" in compiled
    assert "node-palette-skill-sidecar" in compiled
    assert "node-properties-panel" in compiled
    assert "node.param.update" in compiled
    assert "node.param.promote" in compiled
    assert "node.param.focus" in compiled
    assert "app-rail" in compiled
    assert "status-strip" in compiled
    assert "update-notifier" in compiled
    assert "global-toast" in compiled
    assert "canvas-toast" in compiled
    assert "canvas-group-dialog" in compiled
    assert "canvas-save-skill-dialog" in compiled
    assert "create-node-modal" in compiled
    assert "ai-node-modal" in compiled
    assert "first-run-profile" in compiled
    assert "lm-ui-node-action" in compiled
    assert "session.create" in compiled
    assert "sessions.filter.set" in compiled
    assert "sessions.select.toggle" in compiled
    assert "sessions.select.visible.toggle" in compiled
    assert "sessions.selected.delete" in compiled
    assert "sessions.select.cancel" in compiled
    assert "sessions.card.activate" in compiled
    assert "sessions.card.menu.toggle" in compiled
    assert "sessions.chat.row.open" in compiled
    assert "sessions.chat.row.menu.toggle" in compiled
    assert "sessions.chat.panel.menu.toggle" in compiled
    assert "sessions.chat.search.update" in compiled
    assert "skills.save.current" in compiled
    assert "skills.search.update" in compiled
    assert "skills.row.spawn" in compiled
    assert "skills.row.view-json" in compiled
    assert "sessions.menu.action" in compiled
    assert "composer.attach" in compiled
    assert "composer.voice.toggle" in compiled
    assert "composer.submit" in compiled
    assert "composer.text.update" in compiled
    assert "composer.form.submit" in compiled
    assert "canvas.composer.submit" in compiled
    assert "canvas.composer.text.update" in compiled
    assert "canvas.composer.mode.set" in compiled
    assert "canvas.toolbar.zoom.in" in compiled
    assert "canvas.toolbar.run" in compiled
    assert "canvas.session.fork" in compiled
    assert "canvas.session.save-skill" in compiled
    assert "canvas.session.save" in compiled
    assert "ai-node.generate" in compiled
    assert "ai-node.add" in compiled
    assert "sessions.tab.activate" in compiled
    assert "sessions.tab.close" in compiled
    assert "canvas.menu.add-node" in compiled
    assert "canvas.menu.snap.toggle" in compiled
    assert "wire.menu.pick-source" in compiled
    assert "wire.menu.disconnect" in compiled
    assert "node.menu.run" in compiled
    assert "node.menu.delete" in compiled
    assert "nodes.palette.search.update" in compiled
    assert "nodes.palette.sort.toggle" in compiled
    assert "nodes.palette.item.add" in compiled
    assert "nodes.palette.item.pin.toggle" in compiled
    assert "nodes.palette.section.toggle" in compiled
    assert "nodes.palette.menu.item.run" in compiled
    assert "nodes.palette.skill.promote" in compiled
    assert "sessions.sync" in compiled
    assert "rail.home.open" in compiled
    assert "rail.search.open" in compiled
    assert "rail.share.open" in compiled
    assert "settings.open" in compiled
    assert "memory.open" in compiled
    assert "graph.health.open" in compiled
    assert "model.picker.open" in compiled
    assert "account.open" in compiled
    assert "account.identity.signin" in compiled
    assert "brain.folders.open" in compiled
    assert "graph.health.open" in compiled
    assert "homeTopGraphLabel" in compiled
    assert "ModelStrip,{model:model,setPickerOpen:setPickerOpen}" not in home_compiled
    assert "BrainChip,null" not in home_compiled
    assert "AccountChip,{compact:true}" not in home_compiled
    assert "HomeGraphHealthChip,null" not in home_compiled
    assert "+ new canvas" in compiled
    old_toolbar_button = (
        'React.createElement("button",{onClick:()=>'
        "onCreateSession&&onCreateSession('untitled'),style:chipBtn(true)},\"+ new canvas\")"
    )
    assert old_toolbar_button not in compiled


def test_ui_surface_bridge_timeout_allows_large_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")

    assert "slot === 'get_grand_map_ui_surface' ? 60000 : 1500" in jsx


def test_grand_map_command_deck_surfaces_emit_node_backed_parts(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": key,
            "title": key.title(),
            "nodes": [_node("ui_command_palette", "Command Palette")]
            if key == "ui"
            else [],
            "wires": [],
        }
        for key in ("ui", "brain", "sessions", "connectors", "cloud", "users", "nodes")
    ])

    shell = grand_map_ui_surface("command-deck-shell", grand_map_path=grand_map)
    header = grand_map_ui_surface("command-deck-header", grand_map_path=grand_map)
    tile = grand_map_ui_surface("command-deck-tile", grand_map_path=grand_map)
    stat = grand_map_ui_surface("command-deck-stat", grand_map_path=grand_map)
    empty = grand_map_ui_surface("command-deck-empty", grand_map_path=grand_map)

    assert shell["ok"] is True
    assert header["ok"] is True
    assert tile["ok"] is True
    assert stat["ok"] is True
    assert empty["ok"] is True
    assert shell["source_node_ids"] == ["ui_command_palette"]
    assert header["source_node_ids"] == ["ui_command_palette"]

    shell_nodes = {node["id"]: node for node in _non_parameter_nodes(shell)}
    assert shell_nodes["ui:grandmap:command-deck-shell"]["data"]["children"] == [
        "ui:grandmap:command-deck-modal",
    ]
    assert shell_nodes["ui:grandmap:command-deck-shell"]["data"]["test_id"] == (
        "command-deck-overlay"
    )
    assert shell_nodes["ui:grandmap:command-deck-modal"]["data"]["stop_click"] is True
    assert shell_nodes["ui:grandmap:command-deck-content"]["data"]["render_slot"] == (
        "slot:command-deck-content"
    )

    header_nodes = {node["id"]: node for node in _non_parameter_nodes(header)}
    assert header_nodes["ui:grandmap:command-deck-header"]["data"]["children"] == [
        "ui:grandmap:command-deck-header-copy",
        "ui:grandmap:command-deck-header-actions",
    ]
    assert header_nodes["ui:grandmap:command-deck-title"]["data"]["bind"] == (
        "slot:command-deck-title"
    )
    assert header_nodes["ui:grandmap:command-deck-refresh"]["data"]["action"] == (
        "command_deck.refresh"
    )
    assert header_nodes["ui:grandmap:command-deck-close"]["data"]["action"] == (
        "command_deck.close"
    )

    tile_nodes = {node["id"]: node for node in _non_parameter_nodes(tile)}
    assert tile_nodes["ui:grandmap:command-deck-tile"]["data"]["children"] == [
        "ui:grandmap:command-deck-tile-head",
        "ui:grandmap:command-deck-tile-content",
    ]
    assert tile_nodes["ui:grandmap:command-deck-tile-title"]["data"]["bind"] == (
        "slot:command-deck-tile-title"
    )
    assert tile_nodes["ui:grandmap:command-deck-tile-content"]["data"]["render_slot"] == (
        "slot:command-deck-tile-content"
    )

    stat_nodes = {node["id"]: node for node in _non_parameter_nodes(stat)}
    assert stat_nodes["ui:grandmap:command-deck-stat-value"]["data"]["bind"] == (
        "slot:command-deck-stat-value"
    )
    assert stat_nodes["ui:grandmap:command-deck-stat-value"]["data"]["state_bind"] == (
        "slot:command-deck-stat-state"
    )

    empty_nodes = {node["id"]: node for node in _non_parameter_nodes(empty)}
    assert empty_nodes["ui:grandmap:command-deck-empty"]["data"]["bind"] == (
        "slot:command-deck-empty-message"
    )
    assert empty_nodes["ui:grandmap:command-deck-empty"]["data"]["test_id"] == "deck-empty"


def test_production_command_deck_uses_grand_map_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    deck = jsx[
        jsx.index("const CommandDeckModalInner ="):
        jsx.index("const CommandDeckModal = React.memo")
    ]

    for surface in (
        "command-deck-shell",
        "command-deck-header",
        "command-deck-tile",
        "command-deck-stat",
        "command-deck-empty",
    ):
        assert f"get_grand_map_ui_surface', '{surface}'" in jsx

    assert "const CommandDeckShellSurface = ({ closeDeck, content, fallback }) =>" in jsx
    assert 'surface="command-deck-shell"' in jsx
    assert "'slot:command-deck-content': content" in jsx
    assert "const deckContent = (" in deck
    assert "const deckFallback = (" in deck
    assert "<CommandDeckShellSurface" in deck
    assert "<CommandDeckHeaderSurface loading={loading} refresh={refresh} closeDeck={closeDeck}/>" in deck
    assert '<CommandDeckTileSurface id="burndown"' in deck
    assert '<CommandDeckTileSurface id="brain"' in deck
    assert '<CommandDeckTileSurface id="compliance"' in deck
    assert '<CommandDeckTileSurface id="code"' in deck
    assert '<CommandDeckTileSurface id="connectors"' in deck
    assert '<CommandDeckTileSurface id="inbox"' in deck
    assert '<CommandDeckTileSurface id="finances"' in deck
    assert "stat('burndown-green', 'green'" in deck
    assert "emptyState('burndown'" in deck
    assert "const tileHead =" not in deck
    assert "tileHead(" not in deck
    assert "style={card}" not in deck
    assert "...card" not in deck


def test_grand_map_skill_json_shell_surface_emits_node_owned_modal(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_skills", "Skill Library")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("skill-json-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["source_node_ids"] == ["brain_skills"]
    nodes = {node["id"]: node for node in _non_parameter_nodes(payload)}
    assert nodes["ui:grandmap:skill-json-shell"]["data"]["children"] == [
        "ui:grandmap:skill-json-modal",
    ]
    assert nodes["ui:grandmap:skill-json-shell"]["data"]["test_id"] == (
        "skill-json-overlay"
    )
    assert nodes["ui:grandmap:skill-json-modal"]["data"]["stop_click"] is True
    assert nodes["ui:grandmap:skill-json-modal"]["data"]["children"] == [
        "ui:grandmap:skill-json-content",
    ]
    assert nodes["ui:grandmap:skill-json-content"]["data"]["render_slot"] == (
        "slot:skill-json-content"
    )


def test_production_skill_json_modal_shell_uses_grand_map_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    modal = jsx[
        jsx.index("const StudioSkillJsonInner ="):
        jsx.index("const StudioSkillJson = React.memo", jsx.index("const StudioSkillJsonInner ="))
    ]

    assert "get_grand_map_ui_surface', 'skill-json-shell'" in jsx
    assert "const SkillJsonShellSurface = ({ close, content, fallback }) =>" in jsx
    assert 'surface="skill-json-shell"' in jsx
    assert "'slot:skill-json-content': content" in jsx
    assert "const skillJsonContent = (" in modal
    assert "const skillJsonFallback = (" in modal
    assert "<SkillJsonShellSurface" in modal
    assert "<div onClick={close} data-testid=\"skill-json-overlay\"" not in modal[
        modal.index("const skillJsonContent = ("):
        modal.index("const skillJsonFallback = (")
    ]


def test_grand_map_memory_explorer_shell_surface_emits_node_owned_modal(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_fact_store", "Fact Store")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("memory-explorer-shell", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["source_node_ids"] == ["brain_fact_store"]
    nodes = {node["id"]: node for node in _non_parameter_nodes(payload)}
    assert nodes["ui:grandmap:memory-explorer-shell"]["data"]["children"] == [
        "ui:grandmap:memory-explorer-modal",
    ]
    assert nodes["ui:grandmap:memory-explorer-shell"]["data"]["test_id"] == (
        "memory-explorer-overlay"
    )
    assert nodes["ui:grandmap:memory-explorer-modal"]["data"]["stop_click"] is True
    assert nodes["ui:grandmap:memory-explorer-modal"]["data"]["children"] == [
        "ui:grandmap:memory-explorer-content",
    ]
    assert nodes["ui:grandmap:memory-explorer-content"]["data"]["render_slot"] == (
        "slot:memory-explorer-content"
    )


def test_production_memory_explorer_modal_shell_uses_grand_map_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    modal = jsx[
        jsx.index("const MemoryExplorerModalInner ="):
        jsx.index(
            "const MemoryExplorerModal = React.memo",
            jsx.index("const MemoryExplorerModalInner ="),
        )
    ]

    assert "get_grand_map_ui_surface', 'memory-explorer-shell'" in jsx
    assert "const MemoryExplorerShellSurface = ({ close, content, fallback }) =>" in jsx
    assert 'surface="memory-explorer-shell"' in jsx
    assert "'slot:memory-explorer-content': content" in jsx
    assert "const memoryExplorerContent = (" in modal
    assert "const memoryExplorerFallback = (" in modal
    assert "<MemoryExplorerShellSurface" in modal
    assert "<div onClick={close} style={{" not in modal[
        modal.index("const memoryExplorerContent = ("):
        modal.index("const memoryExplorerFallback = (")
    ]


def test_grand_map_community_surfaces_emit_generic_node_parts(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "community",
            "title": "Community & Federation",
            "nodes": [_node("community_share_card", "Share to Community")],
            "wires": [],
        },
    ])

    header = grand_map_ui_surface("community-panel-header", grand_map_path=grand_map)
    card = grand_map_ui_surface("community-card", grand_map_path=grand_map)
    message = grand_map_ui_surface("community-message", grand_map_path=grand_map)
    button = grand_map_ui_surface("community-button", grand_map_path=grand_map)
    input_surface = grand_map_ui_surface("community-input", grand_map_path=grand_map)
    member_row = grand_map_ui_surface("community-member-row", grand_map_path=grand_map)
    transport_option = grand_map_ui_surface(
        "community-transport-option",
        grand_map_path=grand_map,
    )

    for payload in (
        header,
        card,
        message,
        button,
        input_surface,
        member_row,
        transport_option,
    ):
        assert payload["ok"] is True
        assert payload["source_node_ids"] == ["community_share_card"]

    header_nodes = {node["id"]: node for node in _non_parameter_nodes(header)}
    assert header_nodes["ui:grandmap:community-panel-header"]["data"]["children"] == [
        "ui:grandmap:community-panel-heading-row",
        "ui:grandmap:community-panel-description",
    ]
    assert header_nodes["ui:grandmap:community-panel-title"]["data"]["bind"] == (
        "slot:community-panel-title"
    )

    card_nodes = {node["id"]: node for node in _non_parameter_nodes(card)}
    assert card_nodes["ui:grandmap:community-card"]["data"]["render_slot"] == (
        "slot:community-card-content"
    )
    assert card_nodes["ui:grandmap:community-card"]["data"]["state_bind"] == (
        "slot:community-card-state"
    )

    message_nodes = {node["id"]: node for node in _non_parameter_nodes(message)}
    assert message_nodes["ui:grandmap:community-message"]["data"]["state_bind"] == (
        "slot:community-message-state"
    )
    assert message_nodes["ui:grandmap:community-message-body"]["data"]["bind"] == (
        "slot:community-message-body"
    )

    button_nodes = {node["id"]: node for node in _non_parameter_nodes(button)}
    assert button_nodes["ui:grandmap:community-button"]["data"]["bind"] == (
        "slot:community-button-label"
    )
    assert button_nodes["ui:grandmap:community-button"]["data"]["action"] == (
        "community.action"
    )
    assert button_nodes["ui:grandmap:community-button"]["data"]["disabled_bind"] == (
        "slot:community-button-disabled"
    )

    input_nodes = {node["id"]: node for node in _non_parameter_nodes(input_surface)}
    assert input_nodes["ui:grandmap:community-input"]["data"]["tag"] == "input"
    assert input_nodes["ui:grandmap:community-input"]["data"]["bind"] == (
        "slot:community-input-value"
    )
    assert input_nodes["ui:grandmap:community-input"]["data"]["action"] == (
        "community.input.update"
    )

    row_nodes = {node["id"]: node for node in _non_parameter_nodes(member_row)}
    assert row_nodes["ui:grandmap:community-member-row"]["data"]["children"] == [
        "ui:grandmap:community-member-avatar",
        "ui:grandmap:community-member-name",
        "ui:grandmap:community-member-role",
        "ui:grandmap:community-member-spacer",
        "ui:grandmap:community-member-joined",
    ]
    assert row_nodes["ui:grandmap:community-member-role"]["data"]["state_bind"] == (
        "slot:community-member-role"
    )

    transport_nodes = {
        node["id"]: node for node in _non_parameter_nodes(transport_option)
    }
    assert transport_nodes["ui:grandmap:community-transport-option"]["data"]["tag"] == (
        "label"
    )
    assert transport_nodes["ui:grandmap:community-transport-option"]["data"]["action"] == (
        "community.transport.select"
    )
    assert transport_nodes["ui:grandmap:community-transport-option"]["data"]["active_bind"] == (
        "slot:community-transport-selected"
    )
    assert transport_nodes["ui:grandmap:community-transport-path"]["data"]["render_slot"] == (
        "slot:community-transport-path"
    )


def test_production_communities_panel_uses_grand_map_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    community = jsx[
        jsx.index("const CommunitiesPanel ="):
        jsx.index("const commandDeckState =")
    ]

    for surface in (
        "community-panel-header",
        "community-card",
        "community-message",
        "community-button",
        "community-input",
        "community-member-row",
        "community-transport-option",
    ):
        assert f"get_grand_map_ui_surface', '{surface}'" in jsx

    assert "<CommunityPanelHeaderSurface/>" in community
    assert '<CommunityCardSurface id="current"' in community
    assert '<CommunityCardSurface id="create"' in community
    assert '<CommunityCardSurface id="invite"' in community
    assert '<CommunityCardSurface id="members"' in community
    assert '<CommunityCardSurface id="transport"' in community
    assert '<CommunityCardSurface id="owned-server"' in community
    assert '<CommunityCardSurface' in community and 'id="join"' in community
    assert 'action="community.create.name.update"' in community
    assert 'action="community.create"' in community
    assert 'action="community.join.code.update"' in community
    assert 'action="community.join"' in community
    assert 'action="community.leave"' in community
    assert 'action="community.transport.apply"' in community
    assert 'action="community.invite.generate"' in community
    assert "<CommunityMemberRowSurface" in community
    assert "<CommunityTransportOptionSurface" in community
    assert "community.transport.select" in community
    assert '<button data-testid="community' not in community
    assert '<input data-testid="community' not in community
    assert 'data-testid="community-member-row"' not in community
    assert "data-testid={'community-transport-'" not in community
    assert "style={{ ...card" not in community


def test_community_and_brain_view_clones_wire_slots_to_surface_state_nodes():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    header = jsx[
        jsx.index("const ensureGrandMapCommunityHeaderNodes ="):
        jsx.index("const cloneGrandMapCommunityTemplate =", jsx.index("const ensureGrandMapCommunityHeaderNodes ="))
    ]
    clone = jsx[
        jsx.index("const cloneGrandMapCommunityTemplate ="):
        jsx.index("const seedGrandMapAppShellFallbackNodes =", jsx.index("const cloneGrandMapCommunityTemplate ="))
    ]

    assert "syncGrandMapSurfaceStateSlots('community-panel-header', rootId, slotMap" in header
    assert "state_key: 'community_panel_header_state_node_id'" in header
    assert "'slot:community-panel-description': (slots && slots.description)" in header
    assert "const clonedSlotMap = {};" in clone
    assert "clonedSlotMap[mappedId] = slotMap[id];" in clone
    assert "syncGrandMapSurfaceStateSlots(surfaceName, rootId, clonedSlotMap" in clone
    assert "state_key: statePrefix + '_state_node_id'" in clone
    assert "'slot:community-member-role': member.role || 'member'" in clone
    assert "'slot:community-transport-selected': option.selected ? 'true' : 'false'" in clone
    assert "'slot:brain-view-scope-state': scope.state || sid" in clone
    assert "'slot:brain-view-header-actions': ''" in clone


def test_grand_map_brain_view_card_surface_emits_node_backed_card(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_layers", "Brain Layers")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("brain-view-card", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["source_node_ids"] == ["brain_layers"]
    nodes = {node["id"]: node for node in _non_parameter_nodes(payload)}
    assert nodes["ui:grandmap:brain-view-card"]["data"]["render_slot"] == (
        "slot:brain-view-card-content"
    )
    assert nodes["ui:grandmap:brain-view-card"]["data"]["state_bind"] == (
        "slot:brain-view-card-state"
    )
    assert nodes["ui:grandmap:brain-view-card"]["data"]["source_map_node"] == (
        "brain_layers"
    )


def test_grand_map_brain_view_scope_and_button_surfaces_emit_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_layers", "Brain Layers")],
            "wires": [],
        },
    ])

    scope = grand_map_ui_surface("brain-view-scope-card", grand_map_path=grand_map)
    button = grand_map_ui_surface("brain-view-button", grand_map_path=grand_map)

    assert scope["ok"] is True
    assert button["ok"] is True
    assert scope["source_node_ids"] == ["brain_layers"]
    assert button["source_node_ids"] == ["brain_layers"]

    scope_nodes = {node["id"]: node for node in _non_parameter_nodes(scope)}
    assert scope_nodes["ui:grandmap:brain-view-scope-card"]["data"]["children"] == [
        "ui:grandmap:brain-view-scope-name",
        "ui:grandmap:brain-view-scope-description",
        "ui:grandmap:brain-view-scope-lock",
    ]
    assert scope_nodes["ui:grandmap:brain-view-scope-card"]["data"]["state_bind"] == (
        "slot:brain-view-scope-state"
    )
    assert scope_nodes["ui:grandmap:brain-view-scope-name"]["data"]["bind"] == (
        "slot:brain-view-scope-name"
    )

    button_nodes = {node["id"]: node for node in _non_parameter_nodes(button)}
    assert button_nodes["ui:grandmap:brain-view-button"]["data"]["bind"] == (
        "slot:brain-view-button-label"
    )
    assert button_nodes["ui:grandmap:brain-view-button"]["data"]["action"] == (
        "brain.view.action"
    )
    assert button_nodes["ui:grandmap:brain-view-button"]["data"]["disabled_bind"] == (
        "slot:brain-view-button-disabled"
    )


def test_grand_map_brain_view_section_surface_emits_parametric_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_layers", "Brain Layers")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("brain-view-section", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:brain-view-section"
    assert payload["source_node_ids"] == ["brain_layers"]
    nodes = {node["id"]: node for node in _non_parameter_nodes(payload)}
    assert nodes["ui:grandmap:brain-view-section"]["data"]["children"] == [
        "ui:grandmap:brain-view-section-title",
        "ui:grandmap:brain-view-section-subtitle",
    ]
    assert nodes["ui:grandmap:brain-view-section-title"]["data"]["bind"] == (
        "slot:brain-view-section-title"
    )
    assert nodes["ui:grandmap:brain-view-section-badge"]["data"]["state_bind"] == (
        "slot:brain-view-section-badge-state"
    )
    assert nodes["ui:grandmap:brain-view-section-subtitle"]["data"]["bind"] == (
        "slot:brain-view-section-subtitle"
    )


def test_grand_map_brain_view_header_surface_emits_parametric_nodes(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_layers", "Brain Layers")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("brain-view-header", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:brain-view-header"
    assert payload["source_node_ids"] == ["brain_layers"]
    nodes = {node["id"]: node for node in _non_parameter_nodes(payload)}
    assert nodes["ui:grandmap:brain-view-header"]["data"]["children"] == [
        "ui:grandmap:brain-view-header-main",
        "ui:grandmap:brain-view-header-actions",
    ]
    assert nodes["ui:grandmap:brain-view-header-title"]["data"]["bind"] == (
        "slot:brain-view-header-title"
    )
    assert nodes["ui:grandmap:brain-view-header-subtitle"]["data"]["bind"] == (
        "slot:brain-view-header-subtitle"
    )
    assert nodes["ui:grandmap:brain-view-header-actions"]["data"]["render_slot"] == (
        "slot:brain-view-header-actions"
    )


def test_grand_map_brain_view_container_surface_emits_render_slot_node(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(grand_map, [
        {
            "key": "brain",
            "title": "Brain",
            "nodes": [_node("brain_layers", "Brain Layers")],
            "wires": [],
        },
    ])

    payload = grand_map_ui_surface("brain-view-container", grand_map_path=grand_map)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:brain-view-container"
    assert payload["source_node_ids"] == ["brain_layers"]
    nodes = {node["id"]: node for node in _non_parameter_nodes(payload)}
    assert nodes["ui:grandmap:brain-view-container"]["data"]["render_slot"] == (
        "slot:brain-view-container-content"
    )
    assert nodes["ui:grandmap:brain-view-container"]["data"]["state_bind"] == (
        "slot:brain-view-container-state"
    )


def test_production_brain_view_flow_cards_use_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert "get_grand_map_ui_surface', 'brain-view-card'" in jsx
    assert "<BrainViewCardSurface id=\"you\"" in brain
    assert "<BrainViewCardSurface id=\"layers\"" in brain
    assert "<BrainViewCardSurface id=\"ai\"" in brain
    assert 'testId="brain-view-you-card"' in brain
    assert 'testId="brain-view-layers-card"' in brain
    assert 'testId="brain-view-ai-card"' in brain
    assert "style={{ ...card, borderTop:`3px solid ${LM.blue}`" not in brain
    assert "...card, border:`2px solid ${LM.accent}`" not in brain
    assert "style={{ ...card, borderTop:`3px solid ${LM.ok}`" not in brain


def test_production_brain_view_scopes_and_dataset_actions_use_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert "get_grand_map_ui_surface', 'brain-view-scope-card'" in jsx
    assert "get_grand_map_ui_surface', 'brain-view-button'" in jsx
    assert "<BrainViewScopeCardSurface key={s.k} scope={s}/>" in brain
    assert "action=\"brain.dataset.scope.select\"" in brain
    assert "action=\"brain.dataset.export\"" in brain
    assert "brain.dataset.scope.select" in brain
    assert "brain.dataset.export" in brain
    assert "setDsScope(scope);" in brain
    assert "runDatasetExport();" in brain
    assert "<button key={s.k} type=\"button\" data-testid={`brain-dataset-scope-${key}`}" not in brain
    assert "<button onClick={runDatasetExport} disabled={dsBusy}" not in brain


def test_production_brain_view_example_loop_and_dataset_panels_use_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert '<BrainViewCardSurface id="one-idea"' in brain
    assert '<BrainViewCardSurface id="worked-example"' in brain
    assert "id={'worked-example-step-' + ci}" in brain
    assert '<BrainViewCardSurface id="learn-back-loop"' in brain
    assert '<BrainViewCardSurface id="dataset-export-panel"' in brain
    assert 'id="one-idea-label" tag="b"' in brain
    assert 'id="worked-example-header"' in brain
    assert 'id="worked-example-body"' in brain
    assert 'id="worked-example-prompt" tag="p"' in brain
    assert 'id="worked-example-prompt-text" tag="b"' in brain
    assert 'id="worked-example-grid"' in brain
    assert "id={'worked-example-step-title-' + ci}" in brain
    assert "id={'worked-example-step-list-' + ci} tag=\"ul\"" in brain
    assert "id={'worked-example-row-' + ci + '-' + ri} tag=\"li\"" in brain
    assert "id={'worked-example-chip-' + ci + '-' + ri} tag=\"span\"" in brain
    assert 'id="learnback-memory" tag="b"' in brain
    assert 'id="learnback-skills" tag="b"' in brain
    assert 'id="learnback-moat" tag="b"' in brain
    assert 'id="dataset-copy"' in brain
    assert 'id="dataset-title"' in brain
    assert 'id="dataset-description"' in brain
    assert 'id="dataset-result-path" tag="span"' in brain
    assert 'testId="brain-one-idea"' in brain
    assert 'testId="brain-worked-example"' in brain
    assert "testId={'brain-worked-step-' + ci}" in brain
    assert 'testId="brain-learnback-loop"' in brain
    assert 'testId="brain-dataset-export"' in brain
    assert "<div style={{ background:LM.bgDeep, color:LM.ink, padding:'13px 22px'" not in brain
    assert "<div style={{ padding:22 }}" not in brain
    assert "<div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12 }}" not in brain
    assert "<div style={{ fontFamily:LM.mono, fontSize:10, fontWeight:600" not in brain
    assert "<ul style={{ margin:0, paddingLeft:16, fontSize:12.5, color:LM.ink }}" not in brain
    assert "<li key={ri} style={{ marginBottom:5 }}" not in brain
    assert "<span style={{ display:'inline-block', fontFamily:LM.mono, fontSize:9" not in brain
    assert '<div data-testid="brain-dataset-export" style={{' not in brain


def test_production_brain_view_section_headings_use_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert "get_grand_map_ui_surface', 'brain-view-section'" in jsx
    assert '<BrainViewSectionSurface' in brain
    assert 'id="geometry-pictures"' in brain
    assert 'id="training-datasets"' in brain
    assert 'id="north-star"' in brain
    assert 'testId="brain-section-geometry"' in brain
    assert 'testId="brain-section-datasets"' in brain
    assert 'testId="brain-section-north-star"' in brain
    assert "<h2 style={secH}>" not in brain
    assert "buildBadge(" not in brain


def test_production_brain_view_header_uses_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert "get_grand_map_ui_surface', 'brain-view-header'" in jsx
    assert '<BrainViewHeaderSurface' in brain
    assert 'testId="brain-view-header"' in brain
    assert "slot:brain-view-header-actions" in jsx
    assert '<h1 style={{ fontFamily:LM.serif, margin:\'0 0 6px\', fontSize:28' not in brain
    assert "The Brain â€” your intelligence layer" not in brain


def test_production_brain_view_small_containers_use_node_surface():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert "get_grand_map_ui_surface', 'brain-view-container'" in jsx
    assert '<BrainViewContainerSurface' in brain
    assert 'testId="brain-view-sub"' in brain
    assert 'testId="brain-scopes"' in brain
    assert 'testId="brain-dataset-scopes"' in brain
    assert 'testId="brain-dataset-result"' in brain
    assert '<div data-testid="brain-view-sub"' not in brain
    assert '<div data-testid="brain-scopes"' not in brain
    assert '<div data-testid="brain-dataset-scopes"' not in brain
    assert '<div data-testid="brain-dataset-result"' not in brain


def test_production_brain_view_shell_and_flow_use_node_containers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert '<BrainViewContainerSurface id="overlay" testId="brain-view-overlay"' in brain
    assert '<BrainViewContainerSurface id="modal" testId="brain-view-modal"' in brain
    assert '<BrainViewContainerSurface id="scroll-body" className="ah-scroll"' in brain
    assert '<BrainViewContainerSurface id="flow-grid" testId="brain-flow-grid"' in brain
    assert 'testId="brain-flow-col-you"' in brain
    assert 'testId="brain-flow-col-brain"' in brain
    assert 'testId="brain-flow-col-ai"' in brain
    assert 'testId="brain-flow-head-you"' in brain
    assert 'testId="brain-flow-head-brain"' in brain
    assert 'testId="brain-flow-head-ai"' in brain
    assert brain.count("<BrainViewContainerSurface") == brain.count("</BrainViewContainerSurface>")
    assert '<div onClick={close} data-testid="brain-view-overlay"' not in brain
    assert '<div onClick={e => e.stopPropagation()} data-testid="brain-view-modal"' not in brain
    assert '<div className="ah-scroll" style={{ flex:1, overflow:\'auto\'' not in brain
    assert "<div style={{\n            display:'grid', gridTemplateColumns:'1fr 1.5fr 1fr'" not in brain


def test_production_brain_view_flow_detail_rows_use_node_containers():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert "if (box.tag) copy.data.tag = box.tag;" in jsx
    assert "id={'you-message-' + i}" in brain
    assert 'id="you-footnote" tag="small"' in brain
    assert 'id="layers-title" tag="h3"' in brain
    assert "id={'layer-row-' + L.key}" in brain
    assert "id={'layer-glyph-' + L.key} tag=\"span\"" in brain
    assert "id={'layer-name-' + L.key} tag=\"span\"" in brain
    assert "id={'layer-description-' + L.key} tag=\"span\"" in brain
    assert "id={'layer-count-' + L.key} tag=\"span\"" in brain
    assert "id={'ai-step-' + i}" in brain
    assert "id={'ai-step-arrow-' + i} tag=\"span\"" in brain
    assert "id={'ai-step-time-' + i} tag=\"span\"" in brain
    assert 'id="ai-footnote" tag="small"' in brain
    assert '<div key={L.key} data-testid={`brain-layer-${L.key}`}' not in brain
    assert "<div key={i} style={{\n                    fontSize:12.5" not in brain
    assert "<small style={{ fontFamily:LM.mono" not in brain


def test_production_brain_view_modal_has_no_raw_leaf_html_tags():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert re.search(r"<(div|span|small|p|b|ul|li)\b", brain) is None


def test_production_brain_view_close_uses_node_button_action():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    brain = jsx[
        jsx.index("const BrainViewModalInner ="):
        jsx.index("const BrainViewModal = React.memo")
    ]

    assert '<BrainViewButtonSurface' in brain
    assert 'testId="brain-view-close"' in brain
    assert 'action="brain.view.close"' in brain
    assert "registerUiHostCapability('brain.view.close'" in brain
    assert "close();" in brain
    assert '<button onClick={close} data-testid="brain-view-close"' not in brain


def test_production_brain_backup_row_uses_node_surfaces_and_real_bridge_actions():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    row = jsx[
        jsx.index("const BrainBackupRow ="):
        jsx.index("// USER-AGENCY MANDATE", jsx.index("const BrainBackupRow ="))
    ]

    assert '<BrainViewCardSurface id="backup-row"' in row
    assert '<BrainViewButtonSurface' in row
    assert 'id="backup-run"' in row
    assert 'id="backup-google"' in row
    assert 'id="backup-email"' in row
    assert 'id="backup-copy"' in row
    assert 'id="backup-title"' in row
    assert 'id="backup-status-copy" testId="brain-backup-status"' in row
    assert 'id="backup-status-busy" tag="span"' in row
    assert 'id="backup-status-ok" tag="span"' in row
    assert 'id="backup-status-error" tag="span"' in row
    assert 'id="backup-status-idle" tag="span"' in row
    assert 'id="backup-cloud-icon" tag="span"' in row
    assert 'id="backup-signin-actions"' in row
    assert 'id="backup-google-icon" tag="span"' in row
    assert 'action="brain.backup.run"' in row
    assert 'action="brain.backup.google"' in row
    assert "registerUiHostCapability('brain.backup.run'" in row
    assert "registerUiHostCapability('brain.backup.google'" in row
    assert "bridgeAsync('cloud_sign_in')" in row
    assert "bridgeAsync('cloud_sign_in_google')" in row
    assert "bridgeAsync('brain_cloud_backup')" in row
    assert re.search(r"<(div|span|small|p|b|ul|li)\b", row) is None
    assert '<div data-testid="brain-backup-row" style={{' not in row
    assert '<button onClick={runBackup}' not in row
    assert '<button onClick={signInGoogle}' not in row


def test_production_brain_browser_shell_controls_use_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    browser = jsx[
        jsx.index("const BrainBrowser ="):
        jsx.index("const CommunityPanelHeaderSurface", jsx.index("const BrainBrowser ="))
    ]

    assert '<BrainViewContainerSurface id="browser" testId="brain-browser"' in browser
    assert 'id="browser-header"' in browser
    assert 'id="browser-heading-copy"' in browser
    assert 'id="browser-title"' in browser
    assert 'id="browser-subtitle"' in browser
    assert 'id="browser-total-memory" tag="span"' in browser
    assert 'id="browser-search-wrap"' in browser
    assert 'id="browser-search-input"' in browser
    assert 'tag="input"' in browser
    assert 'testId="brain-search-input"' in browser
    assert 'id="browser-search-clear" tag="button"' in browser
    assert 'id="browser-view-toggle" testId="brain-view-toggle"' in browser
    assert "id={'browser-view-mode-' + mode} tag=\"button\"" in browser
    assert 'id="browser-loading" testId="brain-browser-loading"' in browser
    assert 'id="browser-degraded" testId="brain-browser-degraded"' in browser
    assert 'id="browser-degraded-detail" tag="span"' in browser
    assert 'id="browser-project-filter" testId="brain-project-filter"' in browser
    assert 'id="browser-project-label" tag="span"' in browser
    assert 'id="browser-project-chip-all" tag="button"' in browser
    assert "id={'browser-project-chip-' + code} tag=\"button\"" in browser
    assert "id={'browser-project-count-' + code} tag=\"span\"" in browser
    assert 'id="browser-project-summary" tag="span"' in browser
    assert 'id="browser-search-results" testId="brain-search-results"' in browser
    assert 'id="browser-search-results-title"' in browser
    assert 'id="browser-search-results-count" tag="span"' in browser
    assert 'id="browser-search-loading"' in browser
    assert 'id="browser-search-empty"' in browser
    assert 'id="browser-search-error" tag="span"' in browser
    assert 'id="browser-search-grid"' in browser
    assert 'id="browser-folders-heading" testId="brain-folders-heading"' in browser
    assert 'id="browser-folders-note"' in browser
    assert 'id="browser-top-heading" testId="brain-top-of-mind"' in browser
    assert 'id="browser-top-note"' in browser
    assert 'id="browser-top-grid"' in browser
    assert 'id="browser-top-empty"' in browser
    assert 'id="browser-facet-heading" testId="brain-facet-lanes"' in browser
    assert 'id="browser-facet-note"' in browser
    assert 'id="browser-timeline-heading" testId="brain-timeline"' in browser
    assert 'id="browser-timeline-note"' in browser
    assert 'id="browser-timeline-ribbon" className="ah-scroll"' in browser
    assert "id={'browser-timeline-day-' + t.date}" in browser
    assert "id={'browser-timeline-date-' + t.date}" in browser
    assert "id={'browser-timeline-count-' + t.date}" in browser
    assert "id={'browser-timeline-headline-' + t.date}" in browser
    assert 'id="browser-archive-tray"' in browser
    assert 'id="browser-archive-toggle" tag="button" testId="brain-archived-toggle"' in browser
    assert 'id="browser-archive-caret" tag="span"' in browser
    assert 'id="browser-archive-count" tag="span"' in browser
    assert 'id="browser-archive-note" tag="span"' in browser
    assert 'id="browser-archive-body"' in browser
    assert 'id="browser-archive-empty" testId="brain-archived-empty"' in browser
    assert 'id="browser-archive-grid"' in browser
    assert "id={'browser-archive-card-' + c.id}" in browser
    assert "id={'browser-restore-' + c.id} tag=\"button\" testId=\"brain-restore-btn\"" in browser
    assert "bridgeAsync('brain_restore', c.id)" in browser
    assert '<div data-testid="brain-browser" style={{' not in browser
    assert '<input\n            data-testid="brain-search-input"' not in browser
    assert '<button key={mode} data-testid={`brain-view-mode-${mode}`}' not in browser
    assert '<div data-testid="brain-view-toggle"' not in browser
    assert '<div data-testid="brain-browser-loading"' not in browser
    assert '<div data-testid="brain-project-filter"' not in browser
    assert '<button data-testid="brain-project-chip-all"' not in browser
    assert '<button key={code} data-testid="brain-project-chip"' not in browser
    assert '<div data-testid="brain-search-results"' not in browser
    assert '<div style={secTitle}>' not in browser
    assert '<div style={{ fontFamily:LM.mono, fontSize:11.5, color:LM.inkMuted' not in browser
    assert '<div style={secTitle} data-testid="brain-folders-heading"' not in browser
    assert '<div style={secTitle} data-testid="brain-top-of-mind"' not in browser
    assert '<div style={secTitle} data-testid="brain-facet-lanes"' not in browser
    assert '<div style={secTitle} data-testid="brain-timeline"' not in browser
    assert '<div className="ah-scroll" style={{ display:\'flex\'' not in browser
    assert '<div key={t.date} data-testid="brain-timeline-day"' not in browser
    assert '<button onClick={() => setShowArchived' not in browser
    assert '<button data-testid="brain-restore-btn"' not in browser
    assert re.search(r"<(div|span|input|button)\b", browser) is None


def test_production_brain_card_uses_node_surfaces_and_real_promote_bridge():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    card = jsx[
        jsx.index("const BrainCard ="):
        jsx.index("// One facet lane", jsx.index("const BrainCard ="))
    ]

    assert "id={'card-' + card.id}" in card
    assert 'testId="brain-card"' in card
    assert '"data-facet":card.facet' in card
    assert "id={'card-headline-' + card.id} tag=\"span\"" in card
    assert "id={'card-uses-' + card.id} tag=\"span\"" in card
    assert "id={'card-why-' + card.id} tag=\"span\"" in card
    assert "id={'card-promote-toggle-' + card.id} tag=\"button\"" in card
    assert "id={'card-details-toggle-' + card.id} tag=\"button\"" in card
    assert "id={'card-promote-picker-' + card.id}" in card
    assert "id={'card-promote-ring-' + card.id + '-' + ring.scope} tag=\"button\"" in card
    assert "id={'card-promote-note-' + card.id}" in card
    assert "id={'card-raw-' + card.id}" in card
    assert "id={'card-raw-subject-label-' + card.id} tag=\"span\"" in card
    assert "id={'card-raw-predicate-label-' + card.id} tag=\"span\"" in card
    assert "id={'card-raw-object-label-' + card.id} tag=\"span\"" in card
    assert "id={'card-raw-scope-label-' + card.id} tag=\"span\"" in card
    assert "id={'card-raw-kind-label-' + card.id} tag=\"span\"" in card
    assert "bridgeAsync('brain_promote', card.id, ring.scope, 0, tid)" in card
    assert re.search(r"<(div|span|button|b)\b", card) is None
    assert re.search(r"</(div|span|button|b)>", card) is None
    assert '<button onClick={() => setShowRaw' not in card
    assert '<button key={ring.scope}' not in card


def test_production_brain_facet_lane_uses_node_surfaces():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    lane = jsx[
        jsx.index("const BrainFacetLane ="):
        jsx.index("const BrainFolderTree", jsx.index("const BrainFacetLane ="))
    ]

    assert "id={'lane-' + lane.facet}" in lane
    assert 'testId={`brain-lane-${lane.facet}`}' in lane
    assert "id={'lane-toggle-' + lane.facet} tag=\"button\"" in lane
    assert "rootProps={{ onClick:() => setOpen(v => !v) }}" in lane
    assert "id={'lane-glyph-' + lane.facet} tag=\"span\"" in lane
    assert "id={'lane-label-' + lane.facet} tag=\"span\"" in lane
    assert "id={'lane-count-' + lane.facet} tag=\"span\"" in lane
    assert "id={'lane-blurb-' + lane.facet} tag=\"span\"" in lane
    assert "id={'lane-inventory-state-' + lane.facet} tag=\"span\"" in lane
    assert "id={'lane-caret-' + lane.facet} tag=\"span\"" in lane
    assert "id={'lane-grid-' + lane.facet}" in lane
    assert "id={'lane-empty-' + lane.facet}" in lane
    assert "id={'lane-cluster-' + lane.facet + '-' + i}" in lane
    assert "id={'lane-cluster-head-' + lane.facet + '-' + i}" in lane
    assert "id={'lane-cluster-label-' + lane.facet + '-' + i} tag=\"span\"" in lane
    assert "id={'lane-cluster-count-' + lane.facet + '-' + i} tag=\"span\"" in lane
    assert "id={'lane-cluster-top-card-' + card.id}" in lane
    assert "rootProps={{ title:card.headline }}" in lane
    assert "id={'lane-cluster-top-caret-' + card.id} tag=\"span\"" in lane
    assert "id={'lane-cluster-top-title-' + card.id} tag=\"span\"" in lane
    assert re.search(r"<(div|span|button|b)\b", lane) is None
    assert re.search(r"</(div|span|button|b)>", lane) is None
    assert '<button onClick={() => setOpen' not in lane
    assert '<div key={c.label + i} data-testid="brain-cluster-card"' not in lane


def test_production_brain_folder_tree_uses_node_surfaces_and_preserves_actions():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    tree = jsx[
        jsx.index("const BrainFolderTree ="):
        jsx.index("// The 4-view browser", jsx.index("const BrainFolderTree ="))
    ]

    assert 'id="folder-tree" testId="brain-folder-tree"' in tree
    assert 'id="folder-tree-empty"' in tree
    assert "const caret = (id, isOpen)" in tree
    assert 'tag="svg"' in tree
    assert 'tag="path"' in tree
    assert "const countPill = (id, n, col)" in tree
    assert "id={'folder-scope-' + fk} testId=\"brain-folder\"" in tree
    assert '"data-folder-kind":"scope"' in tree
    assert "id={'folder-scope-row-' + fk}" in tree
    assert "onClick:() => toggle(fpath)" in tree
    assert "onKeyDown:e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(fpath); } }" in tree
    assert "caret('folder-scope-caret-' + fk, fOpen)" in tree
    assert "folderGlyph('folder-scope-glyph-' + fk, meta.col)" in tree
    assert "id={'folder-scope-label-' + fk} tag=\"span\"" in tree
    assert "countPill('folder-scope-count-' + fk" in tree
    assert "id={'folder-project-' + fk + '-' + code} testId=\"brain-folder\"" in tree
    assert '"data-folder-kind":"project"' in tree
    assert "id={'folder-project-row-' + fk + '-' + code}" in tree
    assert "onClick:() => toggle(ppath)" in tree
    assert "id={'folder-project-label-' + fk + '-' + code} tag=\"span\"" in tree
    assert "id={'folder-leaf-' + c.id} testId=\"brain-folder\"" in tree
    assert '"data-folder-kind":"leaf"' in tree
    assert "id={'folder-leaf-button-' + c.id}" in tree
    assert 'tag="button"' in tree
    assert 'testId="brain-folder-leaf"' in tree
    assert "onClick:() => setOpenLeaf(v => v === c.id ? null : c.id)" in tree
    assert "id={'folder-leaf-headline-' + c.id} tag=\"span\"" in tree
    assert "id={'folder-leaf-detail-' + c.id} testId=\"brain-folder-leaf-detail\"" in tree
    assert "<BrainCard card={c} />" in tree
    assert re.search(r"<(div|span|button|b|svg|path)\b", tree) is None
    assert re.search(r"</(div|span|button|b|svg|path)>", tree) is None
    assert '<button' not in tree
    assert '<svg' not in tree
    assert '<path' not in tree


def test_app_relation_wire_layers_are_right_rail_edit_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    layer_specs = jsx[
        jsx.index("const APP_RELATION_WIRE_LAYER_SPECS ="):
        jsx.index("const appRelationWireLayerSpecForKey", jsx.index("const APP_RELATION_WIRE_LAYER_SPECS ="))
    ]
    properties = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeSummarySurface =", jsx.index("const NodePropertiesSurface ="))
    ]

    assert "const APP_RELATION_WIRE_LAYER_SPECS = wireLayerSpecsForContext({" in layer_specs
    assert "{ id:'presentation', valueKey:'presentation'" in jsx
    assert "capabilities:['draw_projection', 'expose_ui']" in jsx
    assert "{ id:'source_field', valueKey:'src_field'" in jsx
    assert "capabilities:['select_subvalue', 'field_projection', 'geometry_attribute_path', 'image_metadata_path']" in jsx
    assert "{ id:'target_field', valueKey:'dst_field'" in jsx
    assert "capabilities:['wrap_subvalue', 'field_injection', 'input_shape']" in jsx
    assert "{ id:'gate', valueKey:'gate_policy'" in jsx
    assert "{ id:'codec', valueKey:'codec'" in jsx
    assert "{ id:'encryption', valueKey:'encryption'" in jsx
    assert "{ id:'behavior', valueKey:'behavior'" in jsx

    assert "param.wire_layer = spec.id" in jsx
    assert "param.wire_layer_node_id = layerNodeId" in jsx
    assert "'data-wire-layer-node':wireLayerNodeId" in jsx
    assert "isAppRelationWireNode" in properties
    assert "setAppRelationWireLayerValue(LM_GRAPH, node.id, d.args.key, d.args.value)" in properties
    assert "isAppRelationWireLayerNode" in properties
    assert "setAppRelationWireLayerValue(LM_GRAPH, ownerWireId, layerValueKey, d.args.value)" in properties

    setter = jsx[
        jsx.index("const setAppRelationWireLayerValue = (graph, selection, key, value) =>"):
        jsx.index("const applicationBoundaryStateNodeId =", jsx.index("const setAppRelationWireLayerValue = (graph, selection, key, value) =>"))
    ]
    assert "setWireNodeValue('port_binding'" in setter
    assert "if (ref.fromEndpoint)" in setter
    assert "ref.fromEndpoint.from = appRelationWireEndpointWithNode" in setter
    assert "ref.fromEndpoint.data.from_port_node = value" in setter
    assert "if (ref.relationWire)" in setter
    assert "ref.relationWire.from = appRelationWireEndpointWithNode" in setter
    assert "ref.relationWire.data.from_port_node = value" in setter
    assert "if (key === 'from_port_node') data.from_port_node = value;" in setter
def test_relation_runtime_reads_stage_parameter_nodes_and_materializes_open_payload_envelope():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")

    authority = jsx[
        jsx.index("const relationStageAuthorityValue ="):
        jsx.index("const uiActionNodeValue =", jsx.index("const relationStageAuthorityValue ="))
    ]
    assert "_uiParamNodeId(layerNode.id, 'value')" in authority
    assert "if (!layerNode || !valueNode)" in authority
    assert "const gateStage = relationStageAuthorityValue" in authority
    assert "const behaviorStage = relationStageAuthorityValue" in authority
    assert "const presentationStage = relationStageAuthorityValue" in authority
    assert "const allowed = !missingStage" in authority

    envelope = jsx[
        jsx.index("const RELATION_PAYLOAD_ENVELOPE_PARAM_SPECS ="):
        jsx.index("const uiNodePortOwnerWireId =", jsx.index("const RELATION_PAYLOAD_ENVELOPE_PARAM_SPECS ="))
    ]
    for key in (
        "logical_type", "schema_ref", "schema_version", "media_type", "mode",
        "value_ref", "digest", "byte_size", "context_ref",
    ):
        assert f"['{key}'," in envelope
    assert "capabilities:['group', 'payload_envelope', 'inline_payload', 'reference_payload', 'stream_payload', 'content_addressed']" in envelope
    assert "materializeGrandMapParamNode(nodeId, key, value);" in envelope
    assert "ensureRelationPayloadEnvelopeNode(g, nodeId" in jsx

    for stage in ("routing", "aggregation", "history", "runtime"):
        assert f"{{ id:'{stage}'," in jsx


def test_live_toast_proof_edits_the_gate_parameter_node_and_slot_writer_updates_parameter_authority():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    verifier = (_APP.parent / "tools" / "verify_live_toast_relation_authority.cjs").read_text(encoding="utf-8")

    slot_writer = jsx[
        jsx.index("const putGrandMapSlot ="):
        jsx.index("const setGrandMapInlineNodeField =", jsx.index("const putGrandMapSlot ="))
    ]
    assert "materializeGrandMapParamNode(id, 'value', slotValue);" in slot_writer
    assert "gateValueNodeId" in verifier
    assert "window.ahSetUiNodeParam" in verifier
    assert "'value','deny'" in verifier
    assert "'value','allow-if-target-exists'" in verifier


def test_relation_payload_runtime_is_extensible_graph_ordered_and_fail_closed():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    runtime = jsx[
        jsx.index("const RELATION_PAYLOAD_STAGE_PRIMITIVES ="):
        jsx.index("const rightRailPropertyWireId =", jsx.index("const RELATION_PAYLOAD_STAGE_PRIMITIVES ="))
    ]

    assert "const registerRelationPayloadStagePrimitive =" in runtime
    assert "payload_stage_order_receive" in runtime
    assert "payload_stage_order_send" in runtime
    assert "relationStageAuthorityValue(nodes, relationNode, stageId" in runtime
    assert "unknown relation payload primitive" in runtime
    assert "relation payload stage missing or disabled" in runtime
    assert "archhub.codec.json.v1" in runtime
    assert "archhub.crypto.aes-gcm.v1" in runtime
    assert "resolveSecretRef" in runtime
    assert "encrypted relation has no secret-reference node" in runtime
    assert "cryptoApi.subtle.encrypt" in runtime
    assert "cryptoApi.subtle.decrypt" in runtime
    assert "window.__archhubRegisterRelationPayloadPrimitive" in runtime
    assert "window.__archhubInterpretRelationPayload" in runtime


def test_live_relation_payload_proof_covers_geometry_image_crypto_and_tamper_rejection():
    verifier = (_APP.parent / "tools" / "verify_live_relation_payload_runtime.cjs").read_text(encoding="utf-8")

    assert "geometry:{logical_type:'org.khronos.gltf'" in verifier
    assert "image:{media_type:'image/png'" in verifier
    assert "roundTrip" in verifier
    assert "tamperRejected" in verifier
    assert "wrongKeyRejected" in verifier
    assert "secretReferenceOnly" in verifier
    assert "secret://relation-proof/key" in verifier


def test_relation_node_authority_survives_projection_deletion_but_not_relation_deletion():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    authority = jsx[
        jsx.index("const uiActionRelationAuthority ="):
        jsx.index("const uiActionNodeValue =", jsx.index("const uiActionRelationAuthority ="))
    ]
    verifier = (_APP.parent / "tools" / "verify_live_toast_relation_authority.cjs").read_text(encoding="utf-8")

    assert "const stableRelationNodeId" in authority
    assert "if (!relationNode)" in authority
    assert "projectionIsDisposable" in verifier
    assert "projectionAbsent" in verifier
    assert "relationPresent" in verifier


def test_relation_upsert_respects_graph_owned_deletion_history():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    helper = jsx[
        jsx.index("const graphNodeHasAppliedDeletion ="):
        jsx.index("const recordUiActionOperationNode =", jsx.index("const graphNodeHasAppliedDeletion ="))
    ]
    upsert = jsx[
        jsx.index("const upsertAppRelationWireNode ="):
        jsx.index("const RELATION_PAYLOAD_STAGE_PRIMITIVES =", jsx.index("const upsertAppRelationWireNode ="))
    ]

    assert "data.role !== 'graph_operation'" in helper
    assert "latest.operation === 'node.delete'" in helper
    assert "latest.operation === 'wire.delete'" in helper
    assert "if (graphNodeHasAppliedDeletion(g, nodeId)) return null;" in upsert


def test_node_properties_registers_action_handlers_before_controls_are_interactive():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    surface = jsx[
        jsx.index("const NodePropertiesSurface ="):
        jsx.index("const NodeActionsSurface =", jsx.index("const NodePropertiesSurface ="))
    ]

    assert "React.useLayoutEffect(() => {" in surface
    assert "registerUiHostCapability('node.param.update', onUiNodeAction)" in surface


def test_selected_relation_exposes_a_wired_editable_payload_envelope_in_the_right_rail():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    envelope = jsx[
        jsx.index("const ensureRelationPayloadEnvelopeNode ="):
        jsx.index("const uiNodePortOwnerWireId =", jsx.index("const ensureRelationPayloadEnvelopeNode ="))
    ]
    rail_refs = jsx[
        jsx.index("const nodeRailWireAnatomyReferenceParamItems ="):
        jsx.index("const dedupeNodeRailParamItems =", jsx.index("const nodeRailWireAnatomyReferenceParamItems ="))
    ]
    selected = jsx[
        jsx.index("const ensureSelectedRelationWireFullAnatomy ="):
        jsx.index("const ensureSelectedParameterNodeFullAnatomy =", jsx.index("const ensureSelectedRelationWireFullAnatomy ="))
    ]
    verifier = (_APP.parent / "tools" / "verify_app_relation_right_rail_layer_edit.cjs").read_text(encoding="utf-8")

    assert "relation_wire_family:'payload_envelope_attachment'" in envelope
    assert "relation:'owns_payload_envelope'" in envelope
    assert "const attachmentRelationNodeId = upsertAppRelationWireNode(g, attachmentPayload);" in envelope
    assert "role:'wire_endpoint', endpoint:'from'" in envelope
    assert "role:'wire_endpoint', endpoint:'to'" in envelope
    assert "payload_envelope_relation_node_id:attachmentRelationNodeId || ''" in envelope
    assert "addRef('payload_envelope_node', 'payload envelope node'" in rail_refs
    assert "addRef('payload_envelope_relation_node', 'payload envelope relation node'" in rail_refs
    assert "ensureRelationPayloadEnvelopeNode(" in selected
    assert "payload envelope logical type row" in verifier
    assert "founder.payload.geometry-image.v1" in verifier


def test_node_rail_clone_places_properties_before_connections_without_backend_restart():
    jsx = (_APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    clone = jsx[
        jsx.index("const cloneGrandMapNodeRailShellTemplate ="):
        jsx.index("const seedGrandMapNodeRailShellFallbackNodes =", jsx.index("const cloneGrandMapNodeRailShellTemplate ="))
    ]

    order = jsx[
        jsx.index("const GRAND_MAP_NODE_RAIL_CHILD_ORDER ="):
        jsx.index("const syncGrandMapNodeRailChildOrder =", jsx.index("const GRAND_MAP_NODE_RAIL_CHILD_ORDER ="))
    ]
    assert order.index("'ui:grandmap:node-rail-properties'") < order.index("'ui:grandmap:node-rail-connections'")
    assert "syncGrandMapNodeRailChildOrder(g, rootId, mapId);" in clone
    assert "syncUiChildRelation(g.nodes, g.wires, rootId, childId, index, 'node-rail-shell');" in jsx
    assert ".ah-node-property-param-body-node{flex:1;min-width:0;width:100%" in jsx
    assert ".ah-node-property-param-controls-node{display:flex;flex-direction:column;gap:6px;min-width:0;width:100%" in jsx
