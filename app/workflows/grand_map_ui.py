"""Legacy Grand Map UI-domain projection into the production UI-node shape.

This is migration evidence for old named WebShell surfaces. It is not the
active Node Language authority. The active authority is Universal Cell in
`10.PRODUCT/13.NODE-LANGUAGE`; the `universal-canvas` bridge route is served by
`workflows.universal_grand_map_surface`.

This converter reads the local Grand Map when present and emits legacy
`ui.element` production nodes so existing WebShell surfaces and comparison
courts keep working until each named surface is consumed by Cell-native courts.
It does not embed private Grand Map data in the public app tree.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_UI_COMPONENT_IDS = (
    "ui_design_tokens",
    "ui_account_chip",
    "ui_composer_bar",
    "ui_command_palette",
)


def default_grand_map_path() -> Path:
    """Return the workspace-local Grand Map path when running from ArchHub."""
    archub_root = Path(__file__).resolve().parents[4]
    return archub_root / "30.KNOWLEDGE" / "grand-map" / "data" / "grand_domains.json"


def grand_map_ui_surface(
    surface: str = "home-top",
    *,
    grand_map_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a production LM_GRAPH fragment sourced from the Grand Map UI domain.

    Shape:
        {ok, surface, source, root_id, nodes, wires, source_node_ids}

    Each supported surface is a legacy production app fragment that previously
    had a handwritten JSX source. New authority surfaces should be implemented
    through Universal Cell; do not add new named legacy surfaces here.
    """
    path = Path(grand_map_path) if grand_map_path is not None else default_grand_map_path()

    builders = {
        "home-top": _home_top_surface,
        "home-shell": _home_shell_surface,
        "home-sessions-header": _home_sessions_header_surface,
        "chat-session-row": _chat_session_row_surface,
        "chat-panel-shell": _chat_panel_shell_surface,
        "chat-panel-header": _chat_panel_header_surface,
        "chat-panel-search": _chat_panel_search_surface,
        "chat-panel-list": _chat_panel_list_surface,
        "chat-panel-message": _chat_panel_message_surface,
        "skills-panel-shell": _skills_panel_shell_surface,
        "skills-panel-header": _skills_panel_header_surface,
        "skills-panel-search": _skills_panel_search_surface,
        "skills-panel-list": _skills_panel_list_surface,
        "skills-panel-message": _skills_panel_message_surface,
        "skills-panel-row": _skills_panel_row_surface,
        "search-panel-shell": _search_panel_shell_surface,
        "search-panel-header": _search_panel_header_surface,
        "search-panel-input": _search_panel_input_surface,
        "search-panel-scopes-label": _search_panel_scopes_label_surface,
        "search-panel-scopes-list": _search_panel_scopes_list_surface,
        "search-panel-scope-row": _search_panel_scope_row_surface,
        "search-panel-results-list": _search_panel_results_list_surface,
        "search-panel-empty-state": _search_panel_empty_state_surface,
        "search-panel-hit-row": _search_panel_hit_row_surface,
        "share-panel-shell": _share_panel_shell_surface,
        "share-panel-header": _share_panel_header_surface,
        "share-panel-description": _share_panel_description_surface,
        "share-panel-list": _share_panel_list_surface,
        "share-panel-section-heading": _share_panel_section_heading_surface,
        "share-panel-row": _share_panel_row_surface,
        "share-panel-empty-state": _share_panel_empty_state_surface,
        "share-panel-loading": _share_panel_loading_surface,
        "home-session-toolbar": _home_session_toolbar_surface,
        "home-selection-toolbar": _home_selection_toolbar_surface,
        "home-empty-state": _home_empty_state_surface,
        "home-session-card": _home_session_card_surface,
        "home-session-action-menu": _home_session_action_menu_surface,
        "home-composer-actions": _home_composer_actions_surface,
        "home-composer-body": _home_composer_body_surface,
        "canvas-composer-body": _canvas_composer_body_surface,
        "canvas-composer-help": _canvas_composer_help_surface,
        "canvas-toolbar": _canvas_toolbar_surface,
        "canvas-node-card": _canvas_node_card_surface,
        "canvas-node-card-header": _canvas_node_card_header_surface,
        "canvas-node-card-body": _canvas_node_card_body_surface,
        "canvas-node-socket": _canvas_node_socket_surface,
        "node-output-body": _node_output_body_surface,
        "node-output-param-row": _node_output_param_row_surface,
        "node-result-row": _node_result_row_surface,
        "node-param-display-row": _node_param_display_row_surface,
        "node-typed-param-row": _node_typed_param_row_surface,
        "node-alert-row": _node_alert_row_surface,
        "node-empty-message": _node_empty_message_surface,
        "node-progress-row": _node_progress_row_surface,
        "node-section-label": _node_section_label_surface,
        "node-expression-preview": _node_expression_preview_surface,
        "node-port-row": _node_port_row_surface,
        "node-action-button": _node_action_button_surface,
        "node-stage-preview": _node_stage_preview_surface,
        "node-stage-image-preview": _node_stage_image_preview_surface,
        "node-stage-text-preview": _node_stage_text_preview_surface,
        "node-stage-empty-preview": _node_stage_empty_preview_surface,
        "node-preformatted-preview": _node_preformatted_preview_surface,
        "node-image-preview": _node_image_preview_surface,
        "node-list-preview": _node_list_preview_surface,
        "node-list-preview-item": _node_list_preview_item_surface,
        "node-table-preview": _node_table_preview_surface,
        "node-table-header-cell": _node_table_header_cell_surface,
        "node-table-row": _node_table_row_surface,
        "node-table-cell": _node_table_cell_surface,
        "node-note-display": _node_note_display_surface,
        "node-note-editor": _node_note_editor_surface,
        "node-choice-tile": _node_choice_tile_surface,
        "node-kv-row": _node_kv_row_surface,
        "node-output-port-row": _node_output_port_row_surface,
        "node-icon-button": _node_icon_button_surface,
        "node-markdown-block": _node_markdown_block_surface,
        "node-markdown-list": _node_markdown_list_surface,
        "node-markdown-list-item": _node_markdown_list_item_surface,
        "node-markdown-inline": _node_markdown_inline_surface,
        "node-markdown-link": _node_markdown_link_surface,
        "node-markdown-image": _node_markdown_image_surface,
        "canvas-home-actions": _canvas_home_actions_surface,
        "canvas-model-picker": _canvas_model_picker_surface,
        "model-picker-modal": _model_picker_modal_surface,
        "model-picker-group": _model_picker_group_surface,
        "model-picker-row": _model_picker_row_surface,
        "canvas-router-status": _canvas_router_status_surface,
        "canvas-brain-chip": _canvas_brain_chip_surface,
        "canvas-account-chip": _canvas_account_chip_surface,
        "canvas-account-menu": _canvas_account_menu_surface,
        "account-identity-footer": _account_identity_footer_surface,
        "canvas-new-session-action": _canvas_new_session_action_surface,
        "canvas-session-tab": _canvas_session_tab_surface,
        "canvas-session-actions": _canvas_session_actions_surface,
        "workspace-shell": _workspace_shell_surface,
        "canvas-shell": _canvas_shell_surface,
        "canvas-pan-layer": _canvas_pan_layer_surface,
        "canvas-context-menu": _canvas_context_menu_surface,
        "wire-context-menu": _wire_context_menu_surface,
        "node-context-menu": _node_context_menu_surface,
        "canvas-gesture-hint": _canvas_gesture_hint_surface,
        "graph-health-badge": _graph_health_badge_surface,
        "graph-health-issue-row": _graph_health_issue_row_surface,
        "health-strip-item": _health_strip_item_surface,
        "wire-promote-palette": _wire_promote_palette_surface,
        "wire-promote-result-row": _wire_promote_result_row_surface,
        "broken-wire-dialog": _broken_wire_dialog_surface,
        "broken-wire-row": _broken_wire_row_surface,
        "node-palette-shell": _node_palette_shell_surface,
        "node-palette-header": _node_palette_header_surface,
        "node-palette-search": _node_palette_search_surface,
        "node-palette-list": _node_palette_list_surface,
        "node-palette-group": _node_palette_group_surface,
        "node-palette-context-menu": _node_palette_context_menu_surface,
        "node-palette-item": _node_palette_item_surface,
        "node-palette-section-header": _node_palette_section_header_surface,
        "node-palette-menu-item": _node_palette_menu_item_surface,
        "node-palette-skill-sidecar": _node_palette_skill_sidecar_surface,
        "node-rail-empty-shell": _node_rail_empty_shell_surface,
        "node-rail-shell": _node_rail_shell_surface,
        "node-properties-panel": _node_properties_panel_surface,
        "node-actions-panel": _node_actions_panel_surface,
        "node-summary-panel": _node_summary_panel_surface,
        "node-connections-panel": _node_connections_panel_surface,
        "connector-rail-shell": _connector_rail_shell_surface,
        "connector-controls-panel": _connector_controls_panel_surface,
        "connector-params-panel": _connector_params_panel_surface,
        "connector-description-panel": _connector_description_panel_surface,
        "connector-destructive-warning": _connector_destructive_warning_surface,
        "connector-empty-panel": _connector_empty_panel_surface,
        "connector-run-panel": _connector_run_panel_surface,
        "connector-identity-panel": _connector_identity_panel_surface,
        "connector-connections-panel": _connector_connections_panel_surface,
        "conversation-collapsed-rail": _conversation_collapsed_rail_surface,
        "conversation-header": _conversation_header_surface,
        "conversation-rail-shell": _conversation_rail_shell_surface,
        "rail-minimap": _rail_minimap_surface,
        "rail-minimap-node-rect": _rail_minimap_node_rect_surface,
        "conversation-scrollback": _conversation_scrollback_surface,
        "conversation-day-divider": _conversation_day_divider_surface,
        "conversation-tool-trace": _conversation_tool_trace_surface,
        "conversation-turn-actions": _conversation_turn_actions_surface,
        "conversation-turn": _conversation_turn_surface,
        "conversation-reasoning": _conversation_reasoning_surface,
        "conversation-reasoning-step": _conversation_reasoning_step_surface,
        "conversation-compact-expand": _conversation_compact_expand_surface,
        "conversation-compact-turn": _conversation_compact_turn_surface,
        "conversation-route-meta": _conversation_route_meta_surface,
        "conversation-route-meta-row": _conversation_route_meta_row_surface,
        "conversation-node-scrollback": _conversation_node_scrollback_surface,
        "conversation-search-empty": _conversation_search_empty_surface,
        "conversation-ai-body-expanded": _conversation_ai_body_expanded_surface,
        "conversation-ai-body-compact": _conversation_ai_body_compact_surface,
        "conversation-search-bar": _conversation_search_bar_surface,
        "conversation-reply-composer": _conversation_reply_composer_surface,
        "conversation-expanded-turn": _conversation_expanded_turn_surface,
        "conversation-fabricated-tool-warning": _conversation_fabricated_tool_warning_surface,
        "conversation-code-block": _conversation_code_block_surface,
        "conversation-clipped-text": _conversation_clipped_text_surface,
        "conversation-text-span": _conversation_text_span_surface,
        "conversation-thinking": _conversation_thinking_surface,
        "ai-plan-section": _ai_plan_section_surface,
        "command-deck-shell": _command_deck_shell_surface,
        "command-deck-header": _command_deck_header_surface,
        "command-deck-tile": _command_deck_tile_surface,
        "command-deck-stat": _command_deck_stat_surface,
        "command-deck-empty": _command_deck_empty_surface,
        "skill-json-shell": _skill_json_shell_surface,
        "memory-explorer-shell": _memory_explorer_shell_surface,
        "community-panel-header": _community_panel_header_surface,
        "community-card": _community_card_surface,
        "community-message": _community_message_surface,
        "community-button": _community_button_surface,
        "community-input": _community_input_surface,
        "community-member-row": _community_member_row_surface,
        "community-transport-option": _community_transport_option_surface,
        "brain-view-card": _brain_view_card_surface,
        "brain-view-scope-card": _brain_view_scope_card_surface,
        "brain-view-button": _brain_view_button_surface,
        "brain-view-section": _brain_view_section_surface,
        "brain-view-header": _brain_view_header_surface,
        "brain-view-container": _brain_view_container_surface,
        "app-shell": _app_shell_surface,
        "home-new-session-action": _home_new_session_action_surface,
        "home-rail-shell": _home_rail_shell_surface,
        "rail-drawer-shell": _rail_drawer_shell_surface,
        "sidebar-shell": _sidebar_shell_surface,
        "app-rail": _app_rail_surface,
        "status-strip": _status_strip_surface,
        "update-notifier": _update_notifier_surface,
        "global-toast": _global_toast_surface,
        "canvas-toast": _canvas_toast_surface,
        "canvas-group-dialog": _canvas_group_dialog_surface,
        "canvas-save-skill-dialog": _canvas_save_skill_dialog_surface,
        "create-node-modal": _create_node_modal_surface,
        "ai-node-modal": _ai_node_modal_surface,
        "first-run-profile": _first_run_profile_surface,
    }
    builder = builders.get(surface)
    if builder:
        return _with_parameter_nodes(builder(path, surface))
    return _with_parameter_nodes({
        "ok": False,
        "surface": surface,
        "error": "unknown legacy Grand Map UI surface",
    })


def _home_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = [
        "sessions_threads_rail",
        "sessions_open_session",
        "sessions_cloud_sync",
        "ui_design_tokens",
        "ui_composer_bar",
    ]
    sources = {
        "sessions_threads_rail": session_nodes.get("sessions_threads_rail"),
        "sessions_open_session": session_nodes.get("sessions_open_session"),
        "sessions_cloud_sync": session_nodes.get("sessions_cloud_sync"),
        "ui_design_tokens": ui_nodes.get("ui_design_tokens"),
        "ui_composer_bar": ui_nodes.get("ui_composer_bar"),
    }
    missing = [node_id for node_id in source_ids if not sources[node_id]]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map home source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:home-shell"
    slot_defs = [
        ("styles", "slot:home-shell-styles", "ui_design_tokens"),
        ("top", "slot:home-shell-top", "ui_design_tokens"),
        ("plan", "slot:home-shell-plan", "sessions_threads_rail"),
        ("sessions", "slot:home-shell-sessions", "sessions_threads_rail"),
        ("selection", "slot:home-shell-selection", "sessions_threads_rail"),
        ("content", "slot:home-shell-content", "sessions_open_session"),
        ("composer", "slot:home-shell-composer", "ui_composer_bar"),
    ]
    nodes = [
        _el(
            root_id,
            "main",
            "",
            cls="ah-home-shell-node ah-scroll",
            children=[f"ui:grandmap:home-shell-{key}" for key, _slot, _src in slot_defs],
            source_node=sources["sessions_threads_rail"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:home-shell-{key}",
            "div",
            "",
            cls=f"ah-home-shell-{key}-slot-node",
            render_slot=slot,
            source_node=sources[source_id],
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _app_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["nl_ui_app_is_graph", "ui_design_tokens"]
    sources = {
        "nl_ui_app_is_graph": ui_nodes.get("nl_ui_app_is_graph"),
        "ui_design_tokens": ui_nodes.get("ui_design_tokens"),
    }
    missing = [node_id for node_id in source_ids if not sources[node_id]]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map app-shell source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:app-shell"
    slot_defs = [
        ("rail", "slot:app-shell-rail", "nl_ui_app_is_graph"),
        ("main", "slot:app-shell-main", "nl_ui_app_is_graph"),
        ("inspector", "slot:app-shell-inspector", "nl_ui_app_is_graph"),
        ("status", "slot:app-shell-status", "ui_design_tokens"),
        ("overlays", "slot:app-shell-overlays", "nl_ui_app_is_graph"),
    ]
    nodes = [
        _slot("slot:app-shell-mode", "app shell mode", "home"),
        _slot("slot:app-shell-inspector-focus", "app shell inspector focus", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-app-shell-node",
            state_bind="slot:app-shell-mode",
            test_id="app-shell",
            children=[f"ui:grandmap:app-shell-{key}" for key, _slot, _src in slot_defs],
            source_node=sources["nl_ui_app_is_graph"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:app-shell-{key}",
            "div",
            "",
            cls=f"ah-app-shell-{key}-slot-node",
            render_slot=slot,
            state_bind="slot:app-shell-inspector-focus" if key == "inspector" else "",
            source_node=sources[source_id],
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_top_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }

    missing = [node_id for node_id in _UI_COMPONENT_IDS if node_id not in ui_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:home-top"
    nodes = [
        _slot("slot:model", "model", ""),
        _slot("slot:signed", "signed", "sign in"),
        _slot("slot:session-count", "sessions", ""),
        _slot("slot:brain", "brain", "brain: idle"),
        _slot("slot:graph", "graph", "graph: no canvas open"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-uisurface-top",
            children=[
                "ui_design_tokens",
                "ui_command_palette",
                "ui_account_chip",
                "ui_composer_bar",
                "ui:grandmap:brain",
                "ui:grandmap:graph",
            ],
            source_node=None,
        ),
        _el(
            "ui_design_tokens",
            "span",
            "",
            cls="ah-uiwm",
            children=["ui:grandmap:arch", "ui:grandmap:hub"],
            source_node=ui_nodes["ui_design_tokens"],
        ),
        _el(
            "ui:grandmap:arch",
            "span",
            "Arch",
            cls="ah-uiwm-ink",
            source_node=ui_nodes["ui_design_tokens"],
        ),
        _el(
            "ui:grandmap:hub",
            "span",
            "Hub",
            cls="ah-uiwm-acc",
            source_node=ui_nodes["ui_design_tokens"],
        ),
        _el(
            "ui_account_chip",
            "button",
            "account: ",
            cls="ah-uichip",
            bind="slot:signed",
            action="account.open",
            source_node=ui_nodes["ui_account_chip"],
        ),
        _el(
            "ui_composer_bar",
            "span",
            "sessions: ",
            cls="ah-uichip",
            bind="slot:session-count",
            source_node=ui_nodes["ui_composer_bar"],
        ),
        _el(
            "ui_command_palette",
            "button",
            "model: ",
            cls="ah-uichip",
            bind="slot:model",
            action="model.picker.open",
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:brain",
            "button",
            "",
            cls="ah-uichip",
            bind="slot:brain",
            action="brain.folders.open",
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:graph",
            "button",
            "",
            cls="ah-uichip",
            bind="slot:graph",
            action="graph.health.open",
            source_node=ui_nodes["ui_command_palette"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })

    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": list(_UI_COMPONENT_IDS),
    }


def _home_sessions_header_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_threads_rail", "sessions_open_session"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:sessions-header"
    nodes = [
        _slot("slot:session-count", "sessions", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-sessions-header-node",
            children=[
                "ui:grandmap:sessions-title",
                "ui:grandmap:sessions-count",
                "ui:grandmap:sessions-action",
            ],
            source_node=None,
        ),
        _el(
            "ui:grandmap:sessions-title",
            "span",
            "Sessions",
            cls="ah-sessions-title-node",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:sessions-count",
            "span",
            "",
            cls="ah-sessions-count-node",
            bind="slot:session-count",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:sessions-action",
            "span",
            "",
            cls="ah-sessions-action-node",
            source_node=session_nodes["sessions_open_session"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _chat_session_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_threads_rail", "sessions_open_session"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:chat-session-row"
    nodes = [
        _slot("slot:chat-session-title", "session title", "Session"),
        _slot("slot:chat-session-state", "session state", "idle"),
        _slot("slot:chat-session-active", "active session", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-chat-session-row-node",
            active_bind="slot:chat-session-active",
            active_value="true",
            children=[
                "ui:grandmap:chat-session-open",
                "ui:grandmap:chat-session-more",
                "ui:grandmap:chat-session-menu",
            ],
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-session-open",
            "button",
            "",
            cls="ah-chat-session-open-node",
            action="sessions.chat.row.open",
            args={"id": ""},
            active_bind="slot:chat-session-active",
            active_value="true",
            children=[
                "ui:grandmap:chat-session-dot",
                "ui:grandmap:chat-session-title",
            ],
            source_node=session_nodes["sessions_open_session"],
        ),
        _el(
            "ui:grandmap:chat-session-dot",
            "span",
            "",
            cls="ah-chat-session-dot-node",
            state_bind="slot:chat-session-state",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-session-title",
            "span",
            "",
            cls="ah-chat-session-title-node",
            bind="slot:chat-session-title",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-session-more",
            "button",
            "...",
            cls="ah-chat-session-more-node",
            action="sessions.chat.row.menu.toggle",
            args={"id": ""},
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-session-menu",
            "div",
            "",
            cls="ah-chat-session-menu-slot-node",
            render_slot="slot:chat-session-menu",
            source_node=session_nodes["sessions_threads_rail"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _chat_panel_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "sessions_threads_rail"
    if source_id not in session_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session node: " + source_id,
        }

    source_node = session_nodes[source_id]
    root_id = "ui:grandmap:chat-panel-shell"
    slot_defs = [
        ("header", "slot:chat-panel-shell-header"),
        ("search", "slot:chat-panel-shell-search"),
        ("list", "slot:chat-panel-shell-list"),
        ("menu", "slot:chat-panel-shell-menu"),
        ("account", "slot:chat-panel-shell-account"),
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-chat-panel-shell-node",
            children=[f"ui:grandmap:chat-panel-shell-{key}" for key, _slot in slot_defs],
            source_node=source_node,
        ),
    ]
    for key, slot in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:chat-panel-shell-{key}",
            "div",
            "",
            cls=f"ah-chat-panel-shell-{key}-slot-node",
            render_slot=slot,
            source_node=source_node,
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _chat_panel_header_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_threads_rail", "sessions_open_session"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:chat-panel-header"
    nodes = [
        _slot("slot:chat-panel-title", "panel title", "Chats"),
        _slot("slot:chat-panel-active-session", "active session", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-chat-panel-header-node",
            children=[
                "ui:grandmap:chat-panel-title",
                "ui:grandmap:chat-panel-spacer",
                "ui:grandmap:chat-panel-menu",
                "ui:grandmap:chat-panel-new",
            ],
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-panel-title",
            "span",
            "",
            cls="ah-chat-panel-title-node",
            bind="slot:chat-panel-title",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-panel-spacer",
            "div",
            "",
            cls="ah-chat-panel-spacer-node",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-panel-menu",
            "button",
            "...",
            cls="ah-chat-panel-icon-node",
            action="sessions.chat.panel.menu.toggle",
            args={"id": ""},
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:chat-panel-new",
            "button",
            "+",
            cls="ah-chat-panel-icon-node ah-chat-panel-new-node",
            action="session.create",
            args={"title": "untitled"},
            source_node=session_nodes["sessions_open_session"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _chat_panel_search_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "sessions_threads_rail"
    if source_id not in session_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session node: " + source_id,
        }

    root_id = "ui:grandmap:chat-panel-search"
    nodes = [
        _slot("slot:chat-search-query", "chat search", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-chat-panel-search-wrap-node",
            children=["ui:grandmap:chat-search-row"],
            source_node=session_nodes[source_id],
        ),
        _el(
            "ui:grandmap:chat-search-row",
            "div",
            "",
            cls="ah-chat-search-row-node",
            children=[
                "ui:grandmap:chat-search-icon",
                "ui:grandmap:chat-search-input",
            ],
            source_node=session_nodes[source_id],
        ),
        _el(
            "ui:grandmap:chat-search-icon",
            "span",
            "search",
            cls="ah-chat-search-icon-node",
            source_node=session_nodes[source_id],
        ),
        _el(
            "ui:grandmap:chat-search-input",
            "input",
            "",
            cls="ah-chat-search-input-node",
            bind="slot:chat-search-query",
            action="sessions.chat.search.update",
            input_type="text",
            placeholder="Search chats...",
            source_node=session_nodes[source_id],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _chat_panel_list_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "sessions_threads_rail"
    if source_id not in session_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session node: " + source_id,
        }

    root_id = "ui:grandmap:chat-panel-list"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-chat-panel-list-node ah-scroll",
            render_slot="slot:chat-panel-list-content",
            test_id="chat-panel-list",
            source_node=session_nodes[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _chat_panel_message_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "sessions_threads_rail"
    if source_id not in session_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session node: " + source_id,
        }

    root_id = "ui:grandmap:chat-panel-message"
    nodes = [
        _slot("slot:chat-panel-message", "chat panel message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-chat-panel-message-node",
            bind="slot:chat-panel-message",
            test_id="chat-panel-message",
            source_node=session_nodes[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _skills_panel_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }

    source_node = brain_nodes[source_id]
    root_id = "ui:grandmap:skills-panel-shell"
    slot_defs = [
        ("header", "slot:skills-panel-shell-header"),
        ("search", "slot:skills-panel-shell-search"),
        ("list", "slot:skills-panel-shell-list"),
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-skills-panel-shell-node",
            children=[f"ui:grandmap:skills-panel-shell-{key}" for key, _slot in slot_defs],
            source_node=source_node,
        ),
    ]
    for key, slot in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:skills-panel-shell-{key}",
            "div",
            "",
            cls=f"ah-skills-panel-shell-{key}-slot-node",
            render_slot=slot,
            source_node=source_node,
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _skills_panel_header_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }

    root_id = "ui:grandmap:skills-panel-header"
    nodes = [
        _slot("slot:skills-panel-title", "skills title", "Skills"),
        _slot("slot:skills-panel-count", "saved skills", "0"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-skills-panel-header-node",
            children=[
                "ui:grandmap:skills-panel-title",
                "ui:grandmap:skills-panel-count",
                "ui:grandmap:skills-panel-spacer",
                "ui:grandmap:skills-panel-save",
            ],
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-panel-title",
            "span",
            "",
            cls="ah-skills-panel-title-node",
            bind="slot:skills-panel-title",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-panel-count",
            "span",
            "",
            cls="ah-skills-panel-count-node",
            bind="slot:skills-panel-count",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-panel-spacer",
            "div",
            "",
            cls="ah-skills-panel-spacer-node",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-panel-save",
            "button",
            "+",
            cls="ah-skills-panel-save-node",
            action="skills.save.current",
            source_node=brain_nodes[source_id],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _skills_panel_search_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }

    root_id = "ui:grandmap:skills-panel-search"
    nodes = [
        _slot("slot:skills-search-query", "skills search", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-skills-panel-search-wrap-node",
            children=["ui:grandmap:skills-search-row"],
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-search-row",
            "div",
            "",
            cls="ah-skills-search-row-node",
            children=[
                "ui:grandmap:skills-search-icon",
                "ui:grandmap:skills-search-input",
            ],
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-search-icon",
            "span",
            "search",
            cls="ah-skills-search-icon-node",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-search-input",
            "input",
            "",
            cls="ah-skills-search-input-node",
            bind="slot:skills-search-query",
            action="skills.search.update",
            input_type="text",
            placeholder="Search saved skills...",
            source_node=brain_nodes[source_id],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _skills_panel_list_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }

    root_id = "ui:grandmap:skills-panel-list"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-skills-panel-list-node ah-scroll",
            render_slot="slot:skills-panel-list-content",
            test_id="skills-panel-list",
            source_node=brain_nodes[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _skills_panel_message_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }

    root_id = "ui:grandmap:skills-panel-message"
    nodes = [
        _slot("slot:skills-panel-message", "skills panel message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-skills-panel-message-node",
            bind="slot:skills-panel-message",
            test_id="skills-panel-message",
            source_node=brain_nodes[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _skills_panel_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }

    root_id = "ui:grandmap:skills-row"
    nodes = [
        _slot("slot:skills-row-name", "skill name", "Skill"),
        _slot("slot:skills-row-sub", "skill description", ""),
        _slot("slot:skills-row-mode", "skill mode", "private"),
        _slot("slot:skills-row-badge", "skill badge", "P"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-skills-row-node",
            action="skills.row.spawn",
            draggable=True,
            drag_mime="application/x-archhub-skill",
            drag_payload={},
            children=[
                "ui:grandmap:skills-row-main",
                "ui:grandmap:skills-row-sub",
            ],
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-row-main",
            "div",
            "",
            cls="ah-skills-row-main-node",
            children=[
                "ui:grandmap:skills-row-mark",
                "ui:grandmap:skills-row-name",
                "ui:grandmap:skills-row-json",
                "ui:grandmap:skills-row-badge",
            ],
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-row-mark",
            "span",
            "*",
            cls="ah-skills-row-mark-node",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-row-name",
            "span",
            "",
            cls="ah-skills-row-name-node",
            bind="slot:skills-row-name",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-row-json",
            "button",
            "{ }",
            cls="ah-skills-row-json-node",
            action="skills.row.view-json",
            stop_click=True,
            test_id="skill-row-view-json",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-row-badge",
            "span",
            "",
            cls="ah-skills-row-badge-node",
            bind="slot:skills-row-badge",
            state_bind="slot:skills-row-mode",
            source_node=brain_nodes[source_id],
        ),
        _el(
            "ui:grandmap:skills-row-sub",
            "div",
            "",
            cls="ah-skills-row-sub-node",
            bind="slot:skills-row-sub",
            source_node=brain_nodes[source_id],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _command_deck_source_node(path: Path, source_id: str = "ui_command_palette") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    domains = ("ui", "brain", "sessions", "connectors", "cloud", "users", "nodes")
    try:
        domain_nodes = {key: _load_domain_nodes(path, key) for key in domains}
    except Exception as ex:
        return None, {
            "ok": False,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    for nodes in domain_nodes.values():
        node = nodes.get(source_id)
        if node is not None:
            return node, None
    return None, {
        "ok": False,
        "source": str(path),
        "error": "missing Grand Map command deck source node: " + source_id,
    }


def _command_deck_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _command_deck_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:command-deck-shell"
    nodes = [
        _slot("slot:command-deck-content", "command deck content", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-command-deck-overlay-node",
            children=["ui:grandmap:command-deck-modal"],
            test_id="command-deck-overlay",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-modal",
            "div",
            "",
            cls="ah-command-deck-modal-node",
            children=["ui:grandmap:command-deck-content"],
            test_id="command-deck-modal",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-content",
            "div",
            "",
            cls="ah-command-deck-content-slot-node",
            render_slot="slot:command-deck-content",
            source_node=source_node,
        ),
    ]
    nodes[2]["data"]["stop_click"] = True
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _command_deck_header_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _command_deck_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:command-deck-header"
    nodes = [
        _slot("slot:command-deck-title", "command deck title", "Command Deck"),
        _slot("slot:command-deck-description", "command deck description", ""),
        _slot("slot:command-deck-refresh-label", "command deck refresh label", "Refresh"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-command-deck-header-node",
            children=[
                "ui:grandmap:command-deck-header-copy",
                "ui:grandmap:command-deck-header-actions",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-header-copy",
            "div",
            "",
            cls="ah-command-deck-header-copy-node",
            children=[
                "ui:grandmap:command-deck-title",
                "ui:grandmap:command-deck-description",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-title",
            "h1",
            "",
            cls="ah-command-deck-title-node",
            bind="slot:command-deck-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-description",
            "p",
            "",
            cls="ah-command-deck-description-node",
            bind="slot:command-deck-description",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-header-actions",
            "div",
            "",
            cls="ah-command-deck-header-actions-node",
            children=[
                "ui:grandmap:command-deck-refresh",
                "ui:grandmap:command-deck-close",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-refresh",
            "button",
            "",
            cls="ah-command-deck-refresh-node",
            bind="slot:command-deck-refresh-label",
            action="command_deck.refresh",
            test_id="command-deck-refresh",
            data_attrs={"aria-label": "Refresh the Command Deck"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-close",
            "button",
            "x",
            cls="ah-command-deck-close-node",
            action="command_deck.close",
            test_id="command-deck-close",
            data_attrs={"aria-label": "Close the Command Deck"},
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _command_deck_tile_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _command_deck_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:command-deck-tile"
    nodes = [
        _slot("slot:command-deck-tile-title", "command deck tile title", "Tile"),
        _slot("slot:command-deck-tile-source", "command deck tile source", "source"),
        _el(
            root_id,
            "section",
            "",
            cls="ah-command-deck-tile-node",
            children=[
                "ui:grandmap:command-deck-tile-head",
                "ui:grandmap:command-deck-tile-content",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-tile-head",
            "div",
            "",
            cls="ah-command-deck-tile-head-node",
            children=[
                "ui:grandmap:command-deck-tile-title",
                "ui:grandmap:command-deck-tile-source",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-tile-title",
            "h3",
            "",
            cls="ah-command-deck-tile-title-node",
            bind="slot:command-deck-tile-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-tile-source",
            "span",
            "",
            cls="ah-command-deck-tile-source-node",
            bind="slot:command-deck-tile-source",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-tile-content",
            "div",
            "",
            cls="ah-command-deck-tile-content-node",
            render_slot="slot:command-deck-tile-content",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _command_deck_stat_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _command_deck_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:command-deck-stat"
    nodes = [
        _slot("slot:command-deck-stat-label", "command deck stat label", "label"),
        _slot("slot:command-deck-stat-value", "command deck stat value", "0"),
        _slot("slot:command-deck-stat-state", "command deck stat state", "default"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-command-deck-stat-node",
            children=[
                "ui:grandmap:command-deck-stat-value",
                "ui:grandmap:command-deck-stat-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-stat-value",
            "span",
            "",
            cls="ah-command-deck-stat-value-node",
            bind="slot:command-deck-stat-value",
            state_bind="slot:command-deck-stat-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:command-deck-stat-label",
            "span",
            "",
            cls="ah-command-deck-stat-label-node",
            bind="slot:command-deck-stat-label",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _command_deck_empty_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _command_deck_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:command-deck-empty"
    nodes = [
        _slot("slot:command-deck-empty-message", "command deck empty message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-command-deck-empty-node",
            bind="slot:command-deck-empty-message",
            test_id="deck-empty",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["ui_command_palette"],
    }


def _skill_json_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_skills"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }
    source_node = brain_nodes[source_id]
    root_id = "ui:grandmap:skill-json-shell"
    nodes = [
        _slot("slot:skill-json-content", "skill json content", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-skill-json-overlay-node",
            children=["ui:grandmap:skill-json-modal"],
            test_id="skill-json-overlay",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:skill-json-modal",
            "div",
            "",
            cls="ah-skill-json-modal-node",
            children=["ui:grandmap:skill-json-content"],
            test_id="skill-json-modal",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:skill-json-content",
            "div",
            "",
            cls="ah-skill-json-content-slot-node",
            render_slot="slot:skill-json-content",
            source_node=source_node,
        ),
    ]
    nodes[2]["data"]["stop_click"] = True
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _memory_explorer_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        brain_nodes = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "brain_fact_store"
    if source_id not in brain_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map brain node: " + source_id,
        }
    source_node = brain_nodes[source_id]
    root_id = "ui:grandmap:memory-explorer-shell"
    nodes = [
        _slot("slot:memory-explorer-content", "memory explorer content", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-memory-explorer-overlay-node",
            children=["ui:grandmap:memory-explorer-modal"],
            test_id="memory-explorer-overlay",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:memory-explorer-modal",
            "div",
            "",
            cls="ah-memory-explorer-modal-node",
            children=["ui:grandmap:memory-explorer-content"],
            test_id="memory-explorer-modal",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:memory-explorer-content",
            "div",
            "",
            cls="ah-memory-explorer-content-slot-node",
            render_slot="slot:memory-explorer-content",
            source_node=source_node,
        ),
    ]
    nodes[2]["data"]["stop_click"] = True
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _community_source_node(path: Path, source_id: str = "community_share_card") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        community = _load_domain_nodes(path, "community")
    except Exception as ex:
        return None, {
            "ok": False,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    node = community.get(source_id)
    if node is None:
        return None, {
            "ok": False,
            "source": str(path),
            "error": "missing Grand Map community source node: " + source_id,
        }
    return node, None


def _community_panel_header_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-panel-header"
    nodes = [
        _slot("slot:community-panel-title", "community panel title", "Communities"),
        _slot("slot:community-panel-badge", "community panel badge", "multi-device"),
        _slot("slot:community-panel-description", "community panel description", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-community-panel-header-node",
            children=[
                "ui:grandmap:community-panel-heading-row",
                "ui:grandmap:community-panel-description",
            ],
            test_id="communities-panel-header",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-panel-heading-row",
            "div",
            "",
            cls="ah-community-panel-heading-row-node",
            children=[
                "ui:grandmap:community-panel-title",
                "ui:grandmap:community-panel-badge",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-panel-title",
            "h2",
            "",
            cls="ah-community-panel-title-node",
            bind="slot:community-panel-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-panel-badge",
            "span",
            "",
            cls="ah-community-panel-badge-node",
            bind="slot:community-panel-badge",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-panel-description",
            "p",
            "",
            cls="ah-community-panel-description-node",
            bind="slot:community-panel-description",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["community_share_card"],
    }


def _community_card_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-card"
    nodes = [
        _slot("slot:community-card-content", "community card content", ""),
        _slot("slot:community-card-state", "community card state", "default"),
        _el(
            root_id,
            "section",
            "",
            cls="ah-community-card-node",
            state_bind="slot:community-card-state",
            render_slot="slot:community-card-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["community_share_card"],
    }


def _community_message_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-message"
    nodes = [
        _slot("slot:community-message-title", "community message title", ""),
        _slot("slot:community-message-body", "community message body", ""),
        _slot("slot:community-message-state", "community message state", "default"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-community-message-node",
            children=[
                "ui:grandmap:community-message-title",
                "ui:grandmap:community-message-body",
            ],
            state_bind="slot:community-message-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-message-title",
            "div",
            "",
            cls="ah-community-message-title-node",
            bind="slot:community-message-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-message-body",
            "div",
            "",
            cls="ah-community-message-body-node",
            bind="slot:community-message-body",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["community_share_card"],
    }


def _community_button_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-button"
    nodes = [
        _slot("slot:community-button-label", "community button label", "Action"),
        _slot("slot:community-button-disabled", "community button disabled", "false"),
        _slot("slot:community-button-state", "community button state", "primary"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-community-button-node",
            bind="slot:community-button-label",
            action="community.action",
            state_bind="slot:community-button-state",
            disabled_bind="slot:community-button-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["community_share_card"],
    }


def _community_input_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-input"
    nodes = [
        _slot("slot:community-input-value", "community input value", ""),
        _el(
            root_id,
            "input",
            "",
            cls="ah-community-input-node",
            bind="slot:community-input-value",
            action="community.input.update",
            input_type="text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["community_share_card"],
    }


def _community_member_row_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-member-row"
    nodes = [
        _slot("slot:community-member-initial", "community member initial", "?"),
        _slot("slot:community-member-id", "community member id", "unknown device"),
        _slot("slot:community-member-role", "community member role", "member"),
        _slot("slot:community-member-joined", "community member joined", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-community-member-row-node",
            children=[
                "ui:grandmap:community-member-avatar",
                "ui:grandmap:community-member-name",
                "ui:grandmap:community-member-role",
                "ui:grandmap:community-member-spacer",
                "ui:grandmap:community-member-joined",
            ],
            test_id="community-member-row",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-member-avatar",
            "span",
            "",
            cls="ah-community-member-avatar-node",
            bind="slot:community-member-initial",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-member-name",
            "span",
            "",
            cls="ah-community-member-name-node",
            bind="slot:community-member-id",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-member-role",
            "span",
            "",
            cls="ah-community-member-role-node",
            bind="slot:community-member-role",
            state_bind="slot:community-member-role",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-member-spacer",
            "span",
            "",
            cls="ah-community-member-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-member-joined",
            "span",
            "",
            cls="ah-community-member-joined-node",
            bind="slot:community-member-joined",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["community_share_card"],
    }


def _community_transport_option_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _community_source_node(path)
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:community-transport-option"
    nodes = [
        _slot("slot:community-transport-name", "community transport name", "Transport"),
        _slot("slot:community-transport-tag", "community transport tag", ""),
        _slot("slot:community-transport-description", "community transport description", ""),
        _slot("slot:community-transport-selected", "community transport selected", "false"),
        _slot("slot:community-transport-path", "community transport path slot", ""),
        _el(
            root_id,
            "label",
            "",
            cls="ah-community-transport-option-node",
            children=[
                "ui:grandmap:community-transport-heading",
                "ui:grandmap:community-transport-description",
                "ui:grandmap:community-transport-path",
            ],
            action="community.transport.select",
            active_bind="slot:community-transport-selected",
            active_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-heading",
            "div",
            "",
            cls="ah-community-transport-heading-node",
            children=[
                "ui:grandmap:community-transport-radio",
                "ui:grandmap:community-transport-name",
                "ui:grandmap:community-transport-tag",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-radio",
            "span",
            "",
            cls="ah-community-transport-radio-node",
            children=["ui:grandmap:community-transport-radio-dot"],
            active_bind="slot:community-transport-selected",
            active_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-radio-dot",
            "span",
            "",
            cls="ah-community-transport-radio-dot-node",
            visible_when={"bind": "slot:community-transport-selected", "value": "true"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-name",
            "span",
            "",
            cls="ah-community-transport-name-node",
            bind="slot:community-transport-name",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-tag",
            "span",
            "",
            cls="ah-community-transport-tag-node",
            bind="slot:community-transport-tag",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-description",
            "div",
            "",
            cls="ah-community-transport-description-node",
            bind="slot:community-transport-description",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:community-transport-path",
            "div",
            "",
            cls="ah-community-transport-path-node",
            render_slot="slot:community-transport-path",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["community_share_card"],
    }


def _brain_source_node(path: Path, source_id: str = "brain_layers") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        brain = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return None, {
            "ok": False,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    node = brain.get(source_id)
    if node is None:
        return None, {
            "ok": False,
            "source": str(path),
            "error": "missing Grand Map brain source node: " + source_id,
        }
    return node, None


def _brain_view_card_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _brain_source_node(path, "brain_layers")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:brain-view-card"
    nodes = [
        _slot("slot:brain-view-card-content", "brain view card content", ""),
        _slot("slot:brain-view-card-state", "brain view card state", "default"),
        _el(
            root_id,
            "section",
            "",
            cls="ah-brain-view-card-node",
            state_bind="slot:brain-view-card-state",
            render_slot="slot:brain-view-card-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["brain_layers"],
    }


def _brain_view_scope_card_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _brain_source_node(path, "brain_layers")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:brain-view-scope-card"
    nodes = [
        _slot("slot:brain-view-scope-name", "brain view scope name", "Scope"),
        _slot("slot:brain-view-scope-description", "brain view scope description", ""),
        _slot("slot:brain-view-scope-lock", "brain view scope lock", ""),
        _slot("slot:brain-view-scope-state", "brain view scope state", "default"),
        _el(
            root_id,
            "section",
            "",
            cls="ah-brain-view-scope-card-node",
            children=[
                "ui:grandmap:brain-view-scope-name",
                "ui:grandmap:brain-view-scope-description",
                "ui:grandmap:brain-view-scope-lock",
            ],
            state_bind="slot:brain-view-scope-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-scope-name",
            "div",
            "",
            cls="ah-brain-view-scope-name-node",
            bind="slot:brain-view-scope-name",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-scope-description",
            "div",
            "",
            cls="ah-brain-view-scope-description-node",
            bind="slot:brain-view-scope-description",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-scope-lock",
            "div",
            "",
            cls="ah-brain-view-scope-lock-node",
            bind="slot:brain-view-scope-lock",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["brain_layers"],
    }


def _brain_view_button_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _brain_source_node(path, "brain_layers")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:brain-view-button"
    nodes = [
        _slot("slot:brain-view-button-label", "brain view button label", "Action"),
        _slot("slot:brain-view-button-disabled", "brain view button disabled", "false"),
        _slot("slot:brain-view-button-state", "brain view button state", "default"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-brain-view-button-node",
            bind="slot:brain-view-button-label",
            action="brain.view.action",
            state_bind="slot:brain-view-button-state",
            disabled_bind="slot:brain-view-button-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["brain_layers"],
    }


def _brain_view_section_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _brain_source_node(path, "brain_layers")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:brain-view-section"
    nodes = [
        _slot("slot:brain-view-section-title", "brain view section title", "Section"),
        _slot("slot:brain-view-section-subtitle", "brain view section subtitle", ""),
        _slot("slot:brain-view-section-badge", "brain view section badge", "built"),
        _slot("slot:brain-view-section-badge-state", "brain view section badge state", "built"),
        _el(
            root_id,
            "section",
            "",
            cls="ah-brain-view-section-node",
            children=[
                "ui:grandmap:brain-view-section-title",
                "ui:grandmap:brain-view-section-subtitle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-section-title",
            "h2",
            "",
            cls="ah-brain-view-section-title-node",
            bind="slot:brain-view-section-title",
            children=["ui:grandmap:brain-view-section-badge"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-section-badge",
            "span",
            "",
            cls="ah-brain-view-section-badge-node",
            bind="slot:brain-view-section-badge",
            state_bind="slot:brain-view-section-badge-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-section-subtitle",
            "p",
            "",
            cls="ah-brain-view-section-subtitle-node",
            bind="slot:brain-view-section-subtitle",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["brain_layers"],
    }


def _brain_view_header_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _brain_source_node(path, "brain_layers")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:brain-view-header"
    nodes = [
        _slot("slot:brain-view-header-title", "brain view header title", "The Brain"),
        _slot("slot:brain-view-header-subtitle", "brain view header subtitle", ""),
        _slot("slot:brain-view-header-actions", "brain view header actions", ""),
        _el(
            root_id,
            "header",
            "",
            cls="ah-brain-view-header-node",
            children=[
                "ui:grandmap:brain-view-header-main",
                "ui:grandmap:brain-view-header-actions",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-header-main",
            "div",
            "",
            cls="ah-brain-view-header-main-node",
            children=[
                "ui:grandmap:brain-view-header-title",
                "ui:grandmap:brain-view-header-subtitle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-header-title",
            "h1",
            "",
            cls="ah-brain-view-header-title-node",
            bind="slot:brain-view-header-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-header-subtitle",
            "p",
            "",
            cls="ah-brain-view-header-subtitle-node",
            bind="slot:brain-view-header-subtitle",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:brain-view-header-actions",
            "div",
            "",
            cls="ah-brain-view-header-actions-node",
            render_slot="slot:brain-view-header-actions",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["brain_layers"],
    }


def _brain_view_container_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _brain_source_node(path, "brain_layers")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:brain-view-container"
    nodes = [
        _slot("slot:brain-view-container-content", "brain view container content", ""),
        _slot("slot:brain-view-container-state", "brain view container state", "default"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-brain-view-container-node",
            render_slot="slot:brain-view-container-content",
            state_bind="slot:brain-view-container-state",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["brain_layers"],
    }


def _home_new_session_action_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "sessions_open_session"
    if source_id not in session_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session node: " + source_id,
        }
    root_id = "ui:grandmap:new-session-action"
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": [
            _el(
                root_id,
                "button",
                "+ new canvas",
                cls="ah-node-action-button",
                action="session.create",
                args={"title": "untitled"},
                source_node=session_nodes[source_id],
            ),
        ],
        "wires": [],
        "source_node_ids": [source_id],
    }


def _home_session_toolbar_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_cloud_sync", "sessions_threads_rail", "sessions_open_session"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:session-toolbar"
    children = [
        "ui:grandmap:session-sync",
        "ui:grandmap:session-filter-all",
        "ui:grandmap:session-filter-mine",
        "ui:grandmap:session-filter-workflows",
        "ui:grandmap:session-select-toggle",
        "ui:grandmap:new-session-action",
    ]
    nodes = [
        _slot("slot:session-filter", "filter", "all"),
        _slot("slot:select-mode", "select mode", "false"),
        _slot("slot:session-sync-label", "sync", "sync sessions"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-session-toolbar-node",
            children=children,
            source_node=None,
        ),
        _el(
            "ui:grandmap:session-sync",
            "button",
            "",
            cls="ah-node-chip-button",
            bind="slot:session-sync-label",
            action="sessions.sync",
            source_node=session_nodes["sessions_cloud_sync"],
        ),
        *[
            _el(
                f"ui:grandmap:session-filter-{name}",
                "button",
                name,
                cls="ah-node-chip-button",
                action="sessions.filter.set",
                args={"filter": name},
                active_bind="slot:session-filter",
                active_value=name,
                source_node=session_nodes["sessions_threads_rail"],
            )
            for name in ("all", "mine", "workflows")
        ],
        _el(
            "ui:grandmap:session-select-toggle",
            "button",
            "select",
            cls="ah-node-chip-button",
            action="sessions.select.toggle",
            active_bind="slot:select-mode",
            active_value="true",
            text_cases={
                "bind": "slot:select-mode",
                "values": {"true": "done", "false": "select"},
                "default": "select",
            },
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:new-session-action",
            "button",
            "+ new canvas",
            cls="ah-node-action-button",
            action="session.create",
            args={"title": "untitled"},
            source_node=session_nodes["sessions_open_session"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_selection_toolbar_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_threads_rail", "sessions_clear_graph"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:selection-toolbar"
    children = [
        "ui:grandmap:session-select-all",
        "ui:grandmap:session-selected-count",
        "ui:grandmap:session-delete-selected",
        "ui:grandmap:session-select-cancel",
    ]
    nodes = [
        _slot("slot:selected-count", "selected", "0"),
        _slot("slot:all-visible-selected", "all visible selected", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-selection-toolbar-node",
            children=children,
            source_node=None,
        ),
        _el(
            "ui:grandmap:session-select-all",
            "button",
            "select all",
            cls="ah-node-chip-button",
            action="sessions.select.visible.toggle",
            text_cases={
                "bind": "slot:all-visible-selected",
                "values": {"true": "clear all", "false": "select all"},
                "default": "select all",
            },
            active_bind="slot:all-visible-selected",
            active_value="true",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-selected-count",
            "span",
            "",
            cls="ah-selection-count-node",
            bind="slot:selected-count",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-delete-selected",
            "button",
            "Delete ",
            cls="ah-node-danger-button",
            action="sessions.selected.delete",
            bind="slot:selected-count",
            disabled_bind="slot:selected-count",
            disabled_value="0",
            source_node=session_nodes["sessions_clear_graph"],
        ),
        _el(
            "ui:grandmap:session-select-cancel",
            "button",
            "Cancel",
            cls="ah-node-chip-button",
            action="sessions.select.cancel",
            source_node=session_nodes["sessions_threads_rail"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_empty_state_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_threads_rail"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:home-empty-state"
    nodes = [
        _slot(
            "slot:empty-state-message",
            "empty state message",
            "No sessions yet. Type a title above and hit Enter.",
        ),
        _el(
            root_id,
            "div",
            "",
            cls="ah-empty-state-node",
            children=["ui:grandmap:empty-state-message"],
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:empty-state-message",
            "span",
            "",
            cls="ah-empty-state-message-node",
            bind="slot:empty-state-message",
            source_node=session_nodes["sessions_threads_rail"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_session_card_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_session_object", "sessions_open_session", "sessions_threads_rail"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:session-card"
    nodes = [
        _slot("slot:session-id", "session id", ""),
        _slot("slot:session-title", "title", ""),
        _slot("slot:session-state", "state", ""),
        _slot("slot:session-when", "when", ""),
        _slot("slot:session-last", "last", ""),
        _slot("slot:session-file", "file", ""),
        _slot("slot:session-selected", "selected", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-session-card-node",
            role="button",
            tab_index=0,
            action="sessions.card.activate",
            active_bind="slot:session-selected",
            active_value="true",
            children=[
                "ui:grandmap:session-card-top",
                "ui:grandmap:session-card-title",
                "ui:grandmap:session-card-last",
                "ui:grandmap:session-card-footer",
                "ui:grandmap:session-card-menu",
                "ui:grandmap:session-card-menu-slot",
            ],
            source_node=session_nodes["sessions_session_object"],
        ),
        _el(
            "ui:grandmap:session-card-top",
            "div",
            "",
            cls="ah-session-card-top-node",
            children=[
                "ui:grandmap:session-card-state",
                "ui:grandmap:session-card-when",
            ],
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-card-state",
            "span",
            "",
            cls="ah-session-card-state-node",
            bind="slot:session-state",
            source_node=session_nodes["sessions_session_object"],
        ),
        _el(
            "ui:grandmap:session-card-when",
            "span",
            "",
            cls="ah-session-card-when-node",
            bind="slot:session-when",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-card-title",
            "div",
            "",
            cls="ah-session-card-title-node",
            bind="slot:session-title",
            source_node=session_nodes["sessions_session_object"],
        ),
        _el(
            "ui:grandmap:session-card-last",
            "div",
            "",
            cls="ah-session-card-last-node",
            bind="slot:session-last",
            source_node=session_nodes["sessions_session_object"],
        ),
        _el(
            "ui:grandmap:session-card-footer",
            "div",
            "",
            cls="ah-session-card-footer-node",
            bind="slot:session-file",
            source_node=session_nodes["sessions_session_object"],
        ),
        _el(
            "ui:grandmap:session-card-menu",
            "button",
            "...",
            cls="ah-session-card-menu-node",
            action="sessions.card.menu.toggle",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-card-menu-slot",
            "div",
            "",
            cls="ah-session-card-menu-slot-node",
            render_slot="slot:session-card-menu",
            source_node=session_nodes["sessions_threads_rail"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_session_action_menu_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = [
        "sessions_threads_rail",
        "sessions_open_session",
        "sessions_version_history",
        "sessions_clear_graph",
    ]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:session-action-menu"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-session-action-menu-node",
            children=[
                "ui:grandmap:session-action-rename",
                "ui:grandmap:session-action-fork",
                "ui:grandmap:session-action-duplicate",
                "ui:grandmap:session-action-separator",
                "ui:grandmap:session-action-delete",
            ],
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-action-rename",
            "button",
            "Rename",
            cls="ah-session-menu-item-node",
            action="sessions.menu.action",
            args={"action": "rename"},
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-action-fork",
            "button",
            "Fork",
            cls="ah-session-menu-item-node",
            action="sessions.menu.action",
            args={"action": "fork"},
            source_node=session_nodes["sessions_open_session"],
        ),
        _el(
            "ui:grandmap:session-action-duplicate",
            "button",
            "Duplicate",
            cls="ah-session-menu-item-node",
            action="sessions.menu.action",
            args={"action": "duplicate"},
            source_node=session_nodes["sessions_version_history"],
        ),
        _el(
            "ui:grandmap:session-action-separator",
            "div",
            "",
            cls="ah-session-menu-separator-node",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:session-action-delete",
            "button",
            "Delete",
            cls="ah-session-menu-item-node ah-session-menu-danger-node",
            action="sessions.menu.action",
            args={"action": "delete"},
            source_node=session_nodes["sessions_clear_graph"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_composer_actions_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_composer_bar"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    root_id = "ui:grandmap:composer-actions"
    nodes = [
        _slot("slot:composer-recording", "recording", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-composer-actions-node",
            children=[
                "ui:grandmap:composer-attach",
                "ui:grandmap:composer-voice",
                "ui:grandmap:composer-send",
            ],
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-attach",
            "button",
            "attach",
            cls="ah-composer-tool-node",
            action="composer.attach",
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-voice",
            "button",
            "voice",
            cls="ah-composer-tool-node",
            action="composer.voice.toggle",
            active_bind="slot:composer-recording",
            active_value="true",
            text_cases={
                "bind": "slot:composer-recording",
                "values": {"true": "stop rec", "false": "voice"},
                "default": "voice",
            },
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-send",
            "button",
            "Send",
            cls="ah-composer-send-node",
            action="composer.submit",
            source_node=ui_nodes[source_id],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _home_composer_body_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_composer_bar"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    root_id = "ui:grandmap:composer-body"
    nodes = [
        _slot("slot:composer-drag-over", "drag over", "false"),
        _slot("slot:composer-attachment-count", "attachments", "0"),
        _slot("slot:composer-title", "message", ""),
        _slot("slot:composer-placeholder", "placeholder", "Start a new session..."),
        _el(
            root_id,
            "form",
            "",
            cls="ah-composer-body-node",
            action="composer.form.submit",
            active_bind="slot:composer-drag-over",
            active_value="true",
            children=[
                "ui:grandmap:composer-attachments",
                "ui:grandmap:composer-file-input",
                "ui:grandmap:composer-row",
            ],
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-attachments",
            "div",
            "attachments: ",
            cls="ah-composer-attachments-node",
            bind="slot:composer-attachment-count",
            active_bind="slot:composer-attachment-count",
            active_value="0",
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-file-input",
            "input",
            "",
            cls="ah-composer-file-input-node",
            input_type="file",
            multiple=True,
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-row",
            "div",
            "",
            cls="ah-composer-row-node",
            children=[
                "ui:grandmap:composer-slash",
                "ui:grandmap:composer-textarea",
                "ui:grandmap:composer-actions-mount",
            ],
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-slash",
            "span",
            "/",
            cls="ah-composer-slash-node",
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-textarea",
            "textarea",
            "",
            cls="ah-composer-textarea-node",
            bind="slot:composer-title",
            action="composer.text.update",
            submit_action="composer.submit",
            placeholder="Start a new session...  (Enter to send)",
            source_node=ui_nodes[source_id],
        ),
        _el(
            "ui:grandmap:composer-actions-mount",
            "div",
            "",
            cls="ah-composer-actions-mount-node",
            surface_ref="home-composer-actions",
            source_node=ui_nodes[source_id],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_composer_body_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_composer_bar"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-composer-body"
    mode_nodes = [
        _el(
            "ui:grandmap:canvas-composer-mode-plan",
            "button",
            "P",
            cls="ah-canvas-composer-mode-node",
            action="canvas.composer.mode.set",
            args={"mode": "plan"},
            active_bind="slot:canvas-composer-mode",
            active_value="plan",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-mode-auto",
            "button",
            "A",
            cls="ah-canvas-composer-mode-node",
            action="canvas.composer.mode.set",
            args={"mode": "auto"},
            active_bind="slot:canvas-composer-mode",
            active_value="auto",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-mode-yolo",
            "button",
            "Y",
            cls="ah-canvas-composer-mode-node ah-canvas-composer-mode-danger-node",
            action="canvas.composer.mode.set",
            args={"mode": "yolo"},
            active_bind="slot:canvas-composer-mode",
            active_value="yolo",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-mode-extend",
            "button",
            "X",
            cls="ah-canvas-composer-mode-node",
            action="canvas.composer.mode.set",
            args={"mode": "extend"},
            active_bind="slot:canvas-composer-mode",
            active_value="extend",
            source_node=source_node,
        ),
    ]
    nodes = [
        _slot("slot:canvas-composer-drag-over", "drag over", "false"),
        _slot("slot:canvas-composer-attachment-count", "attachments", "0"),
        _slot("slot:canvas-composer-text", "message", ""),
        _slot("slot:canvas-composer-recording", "recording", "false"),
        _slot("slot:canvas-composer-mode", "mode", "plan"),
        _el(
            root_id,
            "form",
            "",
            cls="ah-canvas-composer-body-node",
            action="canvas.composer.submit",
            active_bind="slot:canvas-composer-drag-over",
            active_value="true",
            children=[
                "ui:grandmap:canvas-composer-attachments",
                "ui:grandmap:canvas-composer-file-input",
                "ui:grandmap:canvas-composer-row",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-attachments",
            "div",
            "attachments: ",
            cls="ah-canvas-composer-attachments-node",
            bind="slot:canvas-composer-attachment-count",
            active_bind="slot:canvas-composer-attachment-count",
            active_value="0",
            children=["ui:grandmap:canvas-composer-attachments-clear"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-attachments-clear",
            "button",
            "clear",
            cls="ah-canvas-composer-clear-node",
            action="canvas.composer.attachments.clear",
            disabled_bind="slot:canvas-composer-attachment-count",
            disabled_value="0",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-file-input",
            "input",
            "",
            cls="ah-canvas-composer-file-input-node",
            input_type="file",
            multiple=True,
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-row",
            "div",
            "",
            cls="ah-canvas-composer-row-node",
            children=[
                "ui:grandmap:canvas-composer-slash",
                "ui:grandmap:canvas-composer-textarea",
                "ui:grandmap:canvas-composer-attach",
                "ui:grandmap:canvas-composer-voice",
                "ui:grandmap:canvas-composer-mode-picker",
                "ui:grandmap:canvas-composer-send",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-slash",
            "span",
            "/",
            cls="ah-canvas-composer-slash-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-textarea",
            "textarea",
            "",
            cls="ah-canvas-composer-textarea-node",
            bind="slot:canvas-composer-text",
            action="canvas.composer.text.update",
            submit_action="canvas.composer.submit",
            placeholder="Reply, ping a host, or type / for commands...  (Enter to send)",
            test_id="canvas-composer-textarea",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-attach",
            "button",
            "attach",
            cls="ah-canvas-composer-tool-node",
            action="canvas.composer.attach",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-voice",
            "button",
            "voice",
            cls="ah-canvas-composer-tool-node",
            action="canvas.composer.voice.toggle",
            active_bind="slot:canvas-composer-recording",
            active_value="true",
            text_cases={
                "bind": "slot:canvas-composer-recording",
                "values": {"true": "stop rec", "false": "voice"},
                "default": "voice",
            },
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-mode-picker",
            "div",
            "",
            cls="ah-canvas-composer-mode-picker-node",
            role="radiogroup",
            test_id="composer-mode-picker",
            children=[
                "ui:grandmap:canvas-composer-mode-plan",
                "ui:grandmap:canvas-composer-mode-auto",
                "ui:grandmap:canvas-composer-mode-yolo",
                "ui:grandmap:canvas-composer-mode-extend",
            ],
            source_node=source_node,
        ),
        *mode_nodes,
        _el(
            "ui:grandmap:canvas-composer-send",
            "button",
            "Send",
            cls="ah-canvas-composer-send-node",
            action="canvas.composer.submit",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_composer_help_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-composer-help"
    commands = [
        ("wire", "/wire", "connect two nodes by name"),
        ("freeze", "/freeze", "pause focused node"),
        ("delete", "/delete", "remove focused node"),
        ("rename", "/rename", "edit focused node title"),
        ("duplicate", "/duplicate", "copy focused node"),
        ("disconnect", "/disconnect", "cut wires on focused node"),
        ("properties", "/properties", "open inspector"),
        ("createnode", "/createnode", "type=foo cat=filter inputs=walls outputs=filtered"),
    ]
    children = ["ui:grandmap:canvas-composer-help-title"] + [
        f"ui:grandmap:canvas-composer-help-{key}" for key, _cmd, _desc in commands
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-composer-help-node",
            children=children,
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-composer-help-title",
            "div",
            "SLASH COMMANDS",
            cls="ah-canvas-composer-help-title-node",
            source_node=source_node,
        ),
    ]
    for key, command, description in commands:
        row_id = f"ui:grandmap:canvas-composer-help-{key}"
        cmd_id = f"{row_id}-command"
        desc_id = f"{row_id}-description"
        nodes.extend([
            _el(
                row_id,
                "div",
                "",
                cls="ah-canvas-composer-help-row-node",
                children=[cmd_id, desc_id],
                source_node=source_node,
            ),
            _el(
                cmd_id,
                "span",
                command,
                cls="ah-canvas-composer-help-command-node",
                source_node=source_node,
            ),
            _el(
                desc_id,
                "span",
                description,
                cls="ah-canvas-composer-help-description-node",
                source_node=source_node,
            ),
        ])

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_toolbar_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-toolbar"
    nodes = [
        _slot("slot:canvas-zoom-percent", "zoom", "100"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-toolbar-node",
            children=[
                "ui:grandmap:canvas-zoom-in",
                "ui:grandmap:canvas-zoom-out",
                "ui:grandmap:canvas-zoom-label",
                "ui:grandmap:canvas-fit",
                "ui:grandmap:canvas-toolbar-separator",
                "ui:grandmap:canvas-run-workflow",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-zoom-in",
            "button",
            "+",
            cls="ah-canvas-toolbar-button-node",
            action="canvas.toolbar.zoom.in",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-zoom-out",
            "button",
            "-",
            cls="ah-canvas-toolbar-button-node",
            action="canvas.toolbar.zoom.out",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-zoom-label",
            "div",
            "",
            cls="ah-canvas-toolbar-zoom-node",
            bind="slot:canvas-zoom-percent",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-fit",
            "button",
            "fit",
            cls="ah-canvas-toolbar-button-node",
            action="canvas.toolbar.fit",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-toolbar-separator",
            "div",
            "",
            cls="ah-canvas-toolbar-separator-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-run-workflow",
            "button",
            "RUN",
            cls="ah-canvas-toolbar-run-node",
            action="canvas.toolbar.run",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_session_actions_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-session-actions"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-header-actions-node",
            children=[
                "ui:grandmap:canvas-action-fork",
                "ui:grandmap:canvas-action-save-skill",
                "ui:grandmap:canvas-action-save",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-action-fork",
            "button",
            "fork",
            cls="ah-canvas-header-button-node",
            action="canvas.session.fork",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-action-save-skill",
            "button",
            "save as skill",
            cls="ah-canvas-header-button-node",
            action="canvas.session.save-skill",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-action-save",
            "button",
            "save",
            cls="ah-canvas-header-button-node ah-canvas-header-primary-node",
            action="canvas.session.save",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_model_picker_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-model-picker"
    nodes = [
        _slot("slot:canvas-model-label", "model", "Auto (router picks)"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-canvas-model-picker-node",
            action="model.picker.open",
            children=[
                "ui:grandmap:canvas-model-mark",
                "ui:grandmap:canvas-model-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-model-mark",
            "span",
            "A",
            cls="ah-canvas-model-mark-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-model-label",
            "span",
            "",
            cls="ah-canvas-model-label-node",
            bind="slot:canvas-model-label",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _model_picker_sources(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    required = {
        "ui": ["ui_command_palette"],
        "models": ["models_router", "models_registry"],
    }
    try:
        domains = {key: _load_domain_nodes(path, key) for key in required}
    except Exception as ex:
        return {}, {
            "ok": False,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domains[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                sources[node_id] = node
    if missing:
        return {}, {
            "ok": False,
            "source": str(path),
            "error": "missing Grand Map model-picker source nodes: " + ", ".join(missing),
        }
    return sources, None


def _model_picker_modal_surface(path: Path, surface: str) -> dict[str, Any]:
    sources, error = _model_picker_sources(path)
    if error:
        return {"surface": surface, **error}

    root_id = "ui:grandmap:model-picker-modal"
    ui_node = sources["ui_command_palette"]
    router_node = sources["models_router"]
    nodes = [
        _slot("slot:model-picker-query", "model picker query", ""),
        _slot("slot:model-picker-has-results", "model picker has results", "true"),
        _slot("slot:model-picker-empty-message", "model picker empty message", "No models match. Sign in to a provider in Settings to enable more."),
        _el(
            root_id,
            "div",
            "",
            cls="ah-model-picker-backdrop-node",
            action="model-picker.close",
            data_attrs={"data-no-pan": "true"},
            children=["ui:grandmap:model-picker-panel"],
            source_node=ui_node,
        ),
        _el(
            "ui:grandmap:model-picker-panel",
            "div",
            "",
            cls="ah-model-picker-panel-node",
            role="dialog",
            action="model-picker.noop",
            data_attrs={"aria-label": "Model picker"},
            children=[
                "ui:grandmap:model-picker-search-row",
                "ui:grandmap:model-picker-empty",
                "ui:grandmap:model-picker-groups",
            ],
            source_node=ui_node,
        ),
        _el(
            "ui:grandmap:model-picker-search-row",
            "div",
            "",
            cls="ah-model-picker-search-row-node",
            children=[
                "ui:grandmap:model-picker-search-mark",
                "ui:grandmap:model-picker-search-input",
                "ui:grandmap:model-picker-esc",
            ],
            source_node=ui_node,
        ),
        _el("ui:grandmap:model-picker-search-mark", "span", "search", cls="ah-model-picker-search-mark-node", source_node=ui_node),
        _el(
            "ui:grandmap:model-picker-search-input",
            "input",
            "",
            cls="ah-model-picker-search-input-node",
            bind="slot:model-picker-query",
            action="model-picker.query.update",
            key_actions={
                "Escape": {
                    "key": "escape",
                    "action": "model-picker.close",
                    "args": {"node_id": "ui:grandmap:model-picker-search-input"},
                },
            },
            placeholder="Search models or paste an OpenRouter id...",
            test_id="model-picker-query",
            source_node=router_node,
        ),
        _el("ui:grandmap:model-picker-esc", "kbd", "esc", cls="ah-model-picker-esc-node", source_node=ui_node),
        _el(
            "ui:grandmap:model-picker-empty",
            "div",
            "",
            cls="ah-model-picker-empty-node",
            bind="slot:model-picker-empty-message",
            visible_when={"bind": "slot:model-picker-has-results", "value": "false"},
            source_node=router_node,
        ),
        _el(
            "ui:grandmap:model-picker-groups",
            "div",
            "",
            cls="ah-model-picker-groups-node",
            render_slot="slot:model-picker-groups",
            visible_when={"bind": "slot:model-picker-has-results", "value": "true"},
            source_node=router_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["ui_command_palette", "models_router", "models_registry"],
    }


def _model_picker_group_surface(path: Path, surface: str) -> dict[str, Any]:
    sources, error = _model_picker_sources(path)
    if error:
        return {"surface": surface, **error}

    root_id = "ui:grandmap:model-picker-group"
    router_node = sources["models_router"]
    nodes = [
        _slot("slot:model-picker-group-name", "model picker group name", "MODELS"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-model-picker-group-node",
            children=[
                "ui:grandmap:model-picker-group-name",
                "ui:grandmap:model-picker-group-items",
            ],
            source_node=router_node,
        ),
        _el("ui:grandmap:model-picker-group-name", "div", "", cls="ah-model-picker-group-name-node", bind="slot:model-picker-group-name", source_node=router_node),
        _el("ui:grandmap:model-picker-group-items", "div", "", cls="ah-model-picker-group-items-node", render_slot="slot:model-picker-group-items", source_node=router_node),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["ui_command_palette", "models_router", "models_registry"],
    }


def _model_picker_row_surface(path: Path, surface: str) -> dict[str, Any]:
    sources, error = _model_picker_sources(path)
    if error:
        return {"surface": surface, **error}

    root_id = "ui:grandmap:model-picker-row"
    registry_node = sources["models_registry"]
    nodes = [
        _slot("slot:model-picker-row-name", "model picker row name", "Model"),
        _slot("slot:model-picker-row-sub", "model picker row sub", ""),
        _slot("slot:model-picker-row-latency", "model picker row latency", "0ms"),
        _slot("slot:model-picker-row-tag", "model picker row tag", "BYO"),
        _slot("slot:model-picker-row-initial", "model picker row initial", "M"),
        _slot("slot:model-picker-row-selected", "model picker row selected", "false"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-model-picker-row-node",
            action="model-picker.pick",
            active_bind="slot:model-picker-row-selected",
            children=[
                "ui:grandmap:model-picker-row-mark",
                "ui:grandmap:model-picker-row-copy",
                "ui:grandmap:model-picker-row-latency",
                "ui:grandmap:model-picker-row-tag",
            ],
            source_node=registry_node,
        ),
        _el("ui:grandmap:model-picker-row-mark", "span", "", cls="ah-model-picker-row-mark-node", bind="slot:model-picker-row-initial", source_node=registry_node),
        _el(
            "ui:grandmap:model-picker-row-copy",
            "div",
            "",
            cls="ah-model-picker-row-copy-node",
            children=[
                "ui:grandmap:model-picker-row-name",
                "ui:grandmap:model-picker-row-sub",
            ],
            source_node=registry_node,
        ),
        _el("ui:grandmap:model-picker-row-name", "div", "", cls="ah-model-picker-row-name-node", bind="slot:model-picker-row-name", source_node=registry_node),
        _el("ui:grandmap:model-picker-row-sub", "div", "", cls="ah-model-picker-row-sub-node", bind="slot:model-picker-row-sub", source_node=registry_node),
        _el("ui:grandmap:model-picker-row-latency", "span", "", cls="ah-model-picker-row-latency-node", bind="slot:model-picker-row-latency", source_node=registry_node),
        _el("ui:grandmap:model-picker-row-tag", "span", "", cls="ah-model-picker-row-tag-node", bind="slot:model-picker-row-tag", source_node=registry_node),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["ui_command_palette", "models_router", "models_registry"],
    }


def _canvas_router_status_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-router-status"
    nodes = [
        _slot("slot:canvas-router-label", "routed model", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-router-status-node",
            children=[
                "ui:grandmap:canvas-router-mark",
                "ui:grandmap:canvas-router-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-router-mark",
            "span",
            "auto",
            cls="ah-canvas-router-mark-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-router-label",
            "span",
            "",
            cls="ah-canvas-router-label-node",
            bind="slot:canvas-router-label",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_brain_chip_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-brain-chip"
    nodes = [
        _slot("slot:canvas-brain-label", "brain label", "brain idle"),
        _slot("slot:canvas-brain-state", "brain state", "idle"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-canvas-brain-chip-node",
            bind="slot:canvas-brain-label",
            state_bind="slot:canvas-brain-state",
            action="brain.folders.open",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _canvas_account_chip_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_account_chip"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-account-chip"
    nodes = [
        _slot("slot:canvas-account-label", "account label", "Sign in"),
        _slot("slot:canvas-account-state", "account state", "signed-out"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-canvas-account-chip-node",
            state_bind="slot:canvas-account-state",
            action="account.chip.activate",
            children=[
                "ui:grandmap:canvas-account-dot",
                "ui:grandmap:canvas-account-label",
                "ui:grandmap:canvas-account-caret",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-dot",
            "span",
            "",
            cls="ah-canvas-account-dot-node",
            state_bind="slot:canvas-account-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-label",
            "span",
            "",
            cls="ah-canvas-account-label-node",
            bind="slot:canvas-account-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-caret",
            "span",
            "v",
            cls="ah-canvas-account-caret-node",
            state_bind="slot:canvas-account-state",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_account_menu_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_account_chip"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-account-menu"
    nodes = [
        _slot("slot:canvas-account-email", "account email", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-account-menu-node",
            role="menu",
            children=[
                "ui:grandmap:canvas-account-menu-email",
                "ui:grandmap:canvas-account-menu-account",
                "ui:grandmap:canvas-account-menu-dashboard",
                "ui:grandmap:canvas-account-menu-signout",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-menu-email",
            "div",
            "",
            cls="ah-canvas-account-menu-email-node",
            bind="slot:canvas-account-email",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-menu-account",
            "button",
            "Account",
            cls="ah-canvas-account-menu-item-node",
            role="menuitem",
            action="account.menu.account",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-menu-dashboard",
            "button",
            "Open cloud dashboard",
            cls="ah-canvas-account-menu-item-node",
            role="menuitem",
            action="account.menu.dashboard",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:canvas-account-menu-signout",
            "button",
            "Sign out",
            cls="ah-canvas-account-menu-item-node ah-canvas-account-menu-danger-node",
            role="menuitem",
            action="account.menu.signout",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _account_identity_footer_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_account_chip"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:account-identity"
    nodes = [
        _slot("slot:account-identity-label", "account label", "Sign in"),
        _slot("slot:account-identity-sub", "account subline", "ArchHub Cloud"),
        _slot("slot:account-identity-initial", "account initial", ">"),
        _slot("slot:account-identity-state", "account state", "signed-out"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-account-identity-node",
            action="account.identity.signin",
            state_bind="slot:account-identity-state",
            test_id="account-identity",
            title="Sign in to ArchHub Cloud",
            data_attrs={"aria-label": "Sign in to ArchHub Cloud"},
            children=[
                "ui:grandmap:account-identity-avatar",
                "ui:grandmap:account-identity-copy",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:account-identity-avatar",
            "div",
            "",
            cls="ah-account-identity-avatar-node",
            bind="slot:account-identity-initial",
            state_bind="slot:account-identity-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:account-identity-copy",
            "div",
            "",
            cls="ah-account-identity-copy-node",
            children=[
                "ui:grandmap:account-identity-name",
                "ui:grandmap:account-identity-tag",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:account-identity-name",
            "div",
            "",
            cls="ah-account-identity-name-node",
            bind="slot:account-identity-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:account-identity-tag",
            "div",
            "",
            cls="ah-account-identity-tag-node",
            bind="slot:account-identity-sub",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_new_session_action_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "sessions_open_session"
    if source_id not in session_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session node: " + source_id,
        }

    root_id = "ui:grandmap:canvas-new-session-action"
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": [
            _el(
                root_id,
                "button",
                "+",
                cls="ah-canvas-tab-add-node",
                action="session.create",
                args={"title": "untitled"},
                source_node=session_nodes[source_id],
            ),
        ],
        "wires": [],
        "source_node_ids": [source_id],
    }


def _canvas_home_actions_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["ui_sidebar_rail", "ui_design_tokens"]
    missing = [node_id for node_id in source_ids if node_id not in ui_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:canvas-home-actions"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-home-actions-node",
            children=[
                "ui:grandmap:canvas-home-grid",
                "ui:grandmap:canvas-home-wordmark",
                "ui:grandmap:canvas-home-divider",
            ],
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:canvas-home-grid",
            "button",
            "",
            cls="ah-canvas-home-button-node",
            action="rail.home.open",
            children=["ui:grandmap:canvas-home-grid-mark"],
            test_id="canvas-home-grid",
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:canvas-home-grid-mark",
            "span",
            "",
            cls="ah-canvas-home-grid-mark-node",
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:canvas-home-wordmark",
            "button",
            "",
            cls="ah-canvas-home-wordmark-node",
            action="rail.home.open",
            children=[
                "ui:grandmap:canvas-home-wordmark-arch",
                "ui:grandmap:canvas-home-wordmark-hub",
            ],
            test_id="canvas-home-wordmark",
            source_node=ui_nodes["ui_design_tokens"],
        ),
        _el(
            "ui:grandmap:canvas-home-wordmark-arch",
            "span",
            "Arch",
            cls="ah-canvas-home-wordmark-ink-node",
            source_node=ui_nodes["ui_design_tokens"],
        ),
        _el(
            "ui:grandmap:canvas-home-wordmark-hub",
            "span",
            "Hub",
            cls="ah-canvas-home-wordmark-accent-node",
            source_node=ui_nodes["ui_design_tokens"],
        ),
        _el(
            "ui:grandmap:canvas-home-divider",
            "div",
            "",
            cls="ah-canvas-home-divider-node",
            source_node=ui_nodes["ui_design_tokens"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _canvas_session_tab_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        session_nodes = _load_domain_nodes(path, "sessions")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["sessions_threads_rail", "sessions_open_session"]
    missing = [node_id for node_id in source_ids if node_id not in session_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map session nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:canvas-session-tab"
    nodes = [
        _slot("slot:canvas-tab-id", "session id", ""),
        _slot("slot:canvas-tab-title", "session title", "untitled"),
        _slot("slot:canvas-tab-state", "session state", "idle"),
        _slot("slot:canvas-tab-active", "active tab", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-session-tab-node",
            action="sessions.tab.activate",
            args={"id": ""},
            active_bind="slot:canvas-tab-active",
            active_value="true",
            children=[
                "ui:grandmap:canvas-session-tab-state",
                "ui:grandmap:canvas-session-tab-title",
                "ui:grandmap:canvas-session-tab-close",
            ],
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:canvas-session-tab-state",
            "span",
            "",
            cls="ah-canvas-session-tab-state-node",
            state_bind="slot:canvas-tab-state",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:canvas-session-tab-title",
            "span",
            "",
            cls="ah-canvas-session-tab-title-node",
            bind="slot:canvas-tab-title",
            source_node=session_nodes["sessions_threads_rail"],
        ),
        _el(
            "ui:grandmap:canvas-session-tab-close",
            "button",
            "x",
            cls="ah-canvas-session-tab-close-node",
            action="sessions.tab.close",
            args={"id": ""},
            source_node=session_nodes["sessions_open_session"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _workspace_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        canvas_nodes = _load_domain_nodes(path, "canvas")
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["canvas_lm_graph_state", "canvas_node_view", "ui_node_card"]
    sources = {
        "canvas_lm_graph_state": canvas_nodes.get("canvas_lm_graph_state"),
        "canvas_node_view": canvas_nodes.get("canvas_node_view"),
        "ui_node_card": ui_nodes.get("ui_node_card"),
    }
    missing = [node_id for node_id in source_ids if not sources[node_id]]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map workspace source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:workspace-shell"
    slot_defs = [
        ("header", "slot:workspace-shell-header", "canvas_lm_graph_state"),
        ("canvas", "slot:workspace-shell-canvas", "canvas_lm_graph_state"),
        ("rail", "slot:workspace-shell-rail", "ui_node_card"),
    ]
    nodes = [
        _el(
            root_id,
            "main",
            "",
            cls="ah-workspace-shell-node",
            children=[f"ui:grandmap:workspace-shell-{key}" for key, _slot, _src in slot_defs],
            source_node=sources["canvas_lm_graph_state"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:workspace-shell-{key}",
            "div",
            "",
            cls=f"ah-workspace-shell-{key}-slot-node",
            render_slot=slot,
            source_node=sources[source_id],
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _canvas_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        canvas_nodes = _load_domain_nodes(path, "canvas")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["canvas_lm_graph_state", "canvas_node_view"]
    missing = [node_id for node_id in source_ids if node_id not in canvas_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map canvas source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:canvas-shell"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-shell-node",
            children=["ui:grandmap:canvas-shell-content"],
            source_node=canvas_nodes["canvas_lm_graph_state"],
        ),
        _el(
            "ui:grandmap:canvas-shell-content",
            "div",
            "",
            cls="ah-canvas-shell-content-slot-node",
            render_slot="slot:canvas-shell-content",
            source_node=canvas_nodes["canvas_node_view"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _canvas_pan_layer_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        canvas_nodes = _load_domain_nodes(path, "canvas")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["canvas_lm_graph_state", "canvas_node_view"]
    missing = [node_id for node_id in source_ids if node_id not in canvas_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map canvas source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:canvas-pan-layer"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-pan-layer-node",
            children=["ui:grandmap:canvas-pan-layer-content"],
            source_node=canvas_nodes["canvas_lm_graph_state"],
        ),
        _el(
            "ui:grandmap:canvas-pan-layer-content",
            "div",
            "",
            cls="ah-canvas-pan-layer-content-slot-node",
            render_slot="slot:canvas-pan-layer-content",
            source_node=canvas_nodes["canvas_node_view"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _canvas_node_card_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
        canvas_nodes = _load_domain_nodes(path, "canvas")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["ui_node_card", "canvas_node_view"]
    sources = {
        "ui_node_card": ui_nodes.get("ui_node_card"),
        "canvas_node_view": canvas_nodes.get("canvas_node_view"),
    }
    missing = [node_id for node_id in source_ids if not sources[node_id]]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map canvas node-card source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:canvas-node-card"
    slot_defs = [
        ("header", "slot:canvas-node-card-header", "ui_node_card"),
        ("body", "slot:canvas-node-card-body", "canvas_node_view"),
        ("sockets", "slot:canvas-node-card-sockets", "canvas_node_view"),
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="lm-node ah-canvas-node-card-node",
            children=[f"ui:grandmap:canvas-node-card-{key}" for key, _slot, _src in slot_defs],
            source_node=sources["ui_node_card"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:canvas-node-card-{key}",
            "div",
            "",
            cls=f"ah-canvas-node-card-{key}-slot-node",
            render_slot=slot,
            source_node=sources[source_id],
        ))

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _canvas_node_card_sources(path: Path, surface: str, label: str) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any] | None]:
    try:
        ui_nodes = _load_ui_nodes(path)
        canvas_nodes = _load_domain_nodes(path, "canvas")
    except Exception as ex:
        return None, {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["ui_node_card", "canvas_node_view"]
    sources = {
        "ui_node_card": ui_nodes.get("ui_node_card"),
        "canvas_node_view": canvas_nodes.get("canvas_node_view"),
    }
    missing = [node_id for node_id in source_ids if not sources[node_id]]
    if missing:
        return None, {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"missing Grand Map {label} source nodes: " + ", ".join(missing),
        }
    return sources, None


def _canvas_node_card_header_surface(path: Path, surface: str) -> dict[str, Any]:
    sources, error = _canvas_node_card_sources(path, surface, "canvas node-card header")
    if error:
        return error
    assert sources is not None

    root_id = "ui:grandmap:canvas-node-card-header"
    children = [
        "ui:grandmap:canvas-node-card-header-icon",
        "ui:grandmap:canvas-node-card-header-label",
        "ui:grandmap:canvas-node-card-header-spacer",
        "ui:grandmap:canvas-node-card-header-status",
        "ui:grandmap:canvas-node-card-header-actions",
    ]
    nodes = [
        _slot("slot:canvas-node-card-icon", "node category icon", ""),
        _slot("slot:canvas-node-card-label", "node category label", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-node-card-header-node",
            children=children,
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-header-icon",
            "span",
            "",
            cls="ah-canvas-node-card-header-icon-node",
            bind="slot:canvas-node-card-icon",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-header-label",
            "span",
            "",
            cls="ah-canvas-node-card-header-label-node",
            bind="slot:canvas-node-card-label",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-header-spacer",
            "div",
            "",
            cls="ah-canvas-node-card-header-spacer-node",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-header-status",
            "div",
            "",
            cls="ah-canvas-node-card-header-status-slot-node",
            render_slot="slot:canvas-node-card-status",
            source_node=sources["canvas_node_view"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-header-actions",
            "div",
            "",
            cls="ah-canvas-node-card-header-actions-slot-node",
            render_slot="slot:canvas-node-card-actions",
            source_node=sources["canvas_node_view"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_node_card", "canvas_node_view"],
    }


def _canvas_node_card_body_surface(path: Path, surface: str) -> dict[str, Any]:
    sources, error = _canvas_node_card_sources(path, surface, "canvas node-card body")
    if error:
        return error
    assert sources is not None

    root_id = "ui:grandmap:canvas-node-card-body"
    children = [
        "ui:grandmap:canvas-node-card-body-title",
        "ui:grandmap:canvas-node-card-body-subtitle",
        "ui:grandmap:canvas-node-card-body-detail",
    ]
    nodes = [
        _slot("slot:canvas-node-card-title", "node title", ""),
        _slot("slot:canvas-node-card-subtitle", "node subtitle", ""),
        _slot("slot:canvas-node-card-subtitle-hidden", "node subtitle hidden", "true"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-node-card-body-node",
            children=children,
            source_node=sources["canvas_node_view"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-body-title",
            "div",
            "",
            cls="ah-canvas-node-card-body-title-node",
            bind="slot:canvas-node-card-title",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-body-subtitle",
            "div",
            "",
            cls="ah-canvas-node-card-body-subtitle-node",
            bind="slot:canvas-node-card-subtitle",
            hidden_bind="slot:canvas-node-card-subtitle-hidden",
            hidden_value="true",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:canvas-node-card-body-detail",
            "div",
            "",
            cls="ah-canvas-node-card-body-detail-slot-node",
            render_slot="slot:canvas-node-card-detail",
            source_node=sources["canvas_node_view"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_node_card", "canvas_node_view"],
    }


def _node_output_body_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-output-body"
    nodes = [
        _slot("slot:node-output-preview-hidden", "node output preview hidden", "true"),
        _slot("slot:node-output-preview-text-hidden", "node output preview text hidden", "true"),
        _slot("slot:node-output-preview-render-hidden", "node output preview render hidden", "true"),
        _slot("slot:node-output-preview-state", "node output preview state", "empty"),
        _slot("slot:node-output-preview-text", "node output preview text", "No output yet - run this node first."),
        _slot("slot:node-output-preview-action-label", "node output preview action label", "preview"),
        _slot("slot:node-output-save-label", "node output save label", "save"),
        _slot("slot:node-output-save-disabled", "node output save disabled", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-output-body-node",
            children=[
                "ui:grandmap:node-output-params",
                "ui:grandmap:node-output-preview",
                "ui:grandmap:node-output-preview-render",
                "ui:grandmap:node-output-actions",
            ],
            style={"marginTop": 8, "display": "flex", "flexDirection": "column", "gap": 7},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-params",
            "div",
            "",
            cls="ah-node-output-params-node",
            render_slot="slot:node-output-params",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-preview",
            "div",
            "",
            cls="ah-node-output-preview-node",
            bind="slot:node-output-preview-text",
            state_bind="slot:node-output-preview-state",
            hidden_bind="slot:node-output-preview-text-hidden",
            hidden_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-preview-render",
            "div",
            "",
            cls="ah-node-output-preview-render-node",
            render_slot="slot:node-output-preview-render",
            state_bind="slot:node-output-preview-state",
            hidden_bind="slot:node-output-preview-render-hidden",
            hidden_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-actions",
            "div",
            "",
            cls="ah-node-output-actions-node",
            children=[
                "ui:grandmap:node-output-preview-action",
                "ui:grandmap:node-output-save-action",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-preview-action",
            "button",
            "",
            cls="ah-node-output-button-node",
            bind="slot:node-output-preview-action-label",
            action="node-output.preview.toggle",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-save-action",
            "button",
            "",
            cls="ah-node-output-button-node ah-node-output-button-primary-node",
            bind="slot:node-output-save-label",
            action="node-output.save",
            disabled_bind="slot:node-output-save-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_output_param_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-output-param-row"
    nodes = [
        _slot("slot:node-output-param-key", "node output param key", ""),
        _slot("slot:node-output-param-value", "node output param value", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-output-param-row-node",
            children=[
                "ui:grandmap:node-output-param-key",
                "ui:grandmap:node-output-param-value",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-param-key",
            "span",
            "",
            cls="ah-node-output-param-key-node",
            bind="slot:node-output-param-key",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-param-value",
            "div",
            "",
            cls="ah-node-output-param-value-node",
            bind="slot:node-output-param-value",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_result_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-result-row"
    nodes = [
        _slot("slot:node-result-icon", "node result icon", ""),
        _slot("slot:node-result-value", "node result value", ""),
        _slot("slot:node-result-ms", "node result milliseconds", ""),
        _slot("slot:node-result-state", "node result state", "ok"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-result-row-node",
            children=[
                "ui:grandmap:node-result-icon",
                "ui:grandmap:node-result-value",
                "ui:grandmap:node-result-ms",
            ],
            state_bind="slot:node-result-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-result-icon",
            "span",
            "",
            cls="ah-node-result-icon-node",
            bind="slot:node-result-icon",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-result-value",
            "span",
            "",
            cls="ah-node-result-value-node",
            bind="slot:node-result-value",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-result-ms",
            "span",
            "",
            cls="ah-node-result-ms-node",
            bind="slot:node-result-ms",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_param_display_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-param-display-row"
    nodes = [
        _slot("slot:node-param-display-key", "node param display key", ""),
        _slot("slot:node-param-display-value", "node param display value", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-param-display-row-node",
            children=[
                "ui:grandmap:node-param-display-key",
                "ui:grandmap:node-param-display-leader",
                "ui:grandmap:node-param-display-value",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-param-display-key",
            "span",
            "",
            cls="ah-node-param-display-key-node",
            bind="slot:node-param-display-key",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-param-display-leader",
            "div",
            "",
            cls="ah-node-param-display-leader-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-param-display-value",
            "span",
            "",
            cls="ah-node-param-display-value-node",
            bind="slot:node-param-display-value",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_typed_param_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-typed-param-row"
    nodes = [
        _slot("slot:node-typed-param-key", "node typed param key", ""),
        _slot("slot:node-typed-param-value", "node typed param value", ""),
        _slot("slot:node-typed-param-indicator", "node typed param indicator", ""),
        _slot("slot:node-typed-param-state", "node typed param state", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-typed-param-row-node",
            children=[
                "ui:grandmap:node-typed-param-key",
                "ui:grandmap:node-typed-param-value-wrap",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-typed-param-key",
            "span",
            "",
            cls="ah-node-typed-param-key-node",
            bind="slot:node-typed-param-key",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-typed-param-value-wrap",
            "span",
            "",
            cls="ah-node-typed-param-value-wrap-node",
            state_bind="slot:node-typed-param-state",
            children=[
                "ui:grandmap:node-typed-param-indicator",
                "ui:grandmap:node-typed-param-value",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-typed-param-indicator",
            "span",
            "",
            cls="ah-node-typed-param-indicator-node",
            bind="slot:node-typed-param-indicator",
            state_bind="slot:node-typed-param-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-typed-param-value",
            "span",
            "",
            cls="ah-node-typed-param-value-node",
            bind="slot:node-typed-param-value",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_alert_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-alert-row"
    nodes = [
        _slot("slot:node-alert-icon", "node alert icon", ""),
        _slot("slot:node-alert-text", "node alert text", ""),
        _slot("slot:node-alert-state", "node alert state", "warn"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-alert-row-node",
            children=[
                "ui:grandmap:node-alert-icon",
                "ui:grandmap:node-alert-text",
            ],
            state_bind="slot:node-alert-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-alert-icon",
            "span",
            "",
            cls="ah-node-alert-icon-node",
            bind="slot:node-alert-icon",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-alert-text",
            "span",
            "",
            cls="ah-node-alert-text-node",
            bind="slot:node-alert-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_empty_message_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-empty-message"
    nodes = [
        _slot("slot:node-empty-message-text", "node empty message text", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-empty-message-node",
            bind="slot:node-empty-message-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_progress_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-progress-row"
    nodes = [
        _slot("slot:node-progress-label", "node progress label", ""),
        _slot("slot:node-progress-percent", "node progress percent", "0%"),
        _slot("slot:node-progress-state", "node progress state", "active"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-progress-row-node",
            children=[
                "ui:grandmap:node-progress-header",
                "ui:grandmap:node-progress-track",
            ],
            state_bind="slot:node-progress-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-progress-header",
            "div",
            "",
            cls="ah-node-progress-header-node",
            children=[
                "ui:grandmap:node-progress-label",
                "ui:grandmap:node-progress-spacer",
                "ui:grandmap:node-progress-percent",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-progress-label",
            "span",
            "",
            cls="ah-node-progress-label-node",
            bind="slot:node-progress-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-progress-spacer",
            "div",
            "",
            cls="ah-node-progress-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-progress-percent",
            "span",
            "",
            cls="ah-node-progress-percent-node",
            bind="slot:node-progress-percent",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-progress-track",
            "div",
            "",
            cls="ah-node-progress-track-node",
            children=["ui:grandmap:node-progress-fill"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-progress-fill",
            "div",
            "",
            cls="ah-node-progress-fill-node",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_section_label_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-section-label"
    nodes = [
        _slot("slot:node-section-label-text", "node section label text", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-section-label-node",
            bind="slot:node-section-label-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_expression_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-expression-preview"
    nodes = [
        _slot("slot:node-expression-preview-text", "node expression preview text", ""),
        _slot("slot:node-expression-preview-state", "node expression preview state", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-expression-preview-node",
            bind="slot:node-expression-preview-text",
            state_bind="slot:node-expression-preview-state",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_port_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-port-row"
    nodes = [
        _slot("slot:node-port-row-icon", "node port row icon", ""),
        _slot("slot:node-port-row-label", "node port row label", ""),
        _slot("slot:node-port-row-type", "node port row type", ""),
        _slot("slot:node-port-row-state", "node port row state", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-port-row-node",
            state_bind="slot:node-port-row-state",
            children=[
                "ui:grandmap:node-port-row-icon",
                "ui:grandmap:node-port-row-label",
                "ui:grandmap:node-port-row-type",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-port-row-icon",
            "span",
            "",
            cls="ah-node-port-row-icon-node",
            bind="slot:node-port-row-icon",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-port-row-label",
            "span",
            "",
            cls="ah-node-port-row-label-node",
            bind="slot:node-port-row-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-port-row-type",
            "span",
            "",
            cls="ah-node-port-row-type-node",
            bind="slot:node-port-row-type",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_action_button_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-action-button"
    nodes = [
        _slot("slot:node-action-button-label", "node action button label", ""),
        _slot("slot:node-action-button-disabled", "node action button disabled", "false"),
        _slot("slot:node-action-button-state", "node action button state", ""),
        _el(
            root_id,
            "button",
            "",
            cls="ah-node-action-button-node",
            bind="slot:node-action-button-label",
            disabled_bind="slot:node-action-button-disabled",
            state_bind="slot:node-action-button-state",
            action="node-action-button.press",
            args={"button_id": ""},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_note_display_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-note-display"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-note-display-node",
            double_action="node-note-display.edit",
            render_slot="slot:node-note-display-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_note_editor_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-note-editor"
    nodes = [
        _slot("slot:node-note-editor-text", "node note draft text", ""),
        _el(
            root_id,
            "textarea",
            "",
            cls="ah-node-note-editor-node",
            bind="slot:node-note-editor-text",
            action="node-note-editor.change",
            rows=5,
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_choice_tile_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-choice-tile"
    nodes = [
        _slot("slot:node-choice-tile-title", "node choice tile title", ""),
        _slot("slot:node-choice-tile-subtitle", "node choice tile subtitle", ""),
        _slot("slot:node-choice-tile-status", "node choice tile status", ""),
        _slot("slot:node-choice-tile-state", "node choice tile state", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-choice-tile-node",
            state_bind="slot:node-choice-tile-state",
            action="node-choice-tile.press",
            args={"choice_id": ""},
            children=[
                "ui:grandmap:node-choice-tile-dot",
                "ui:grandmap:node-choice-tile-content",
                "ui:grandmap:node-choice-tile-status",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-choice-tile-dot",
            "span",
            "",
            cls="ah-node-choice-tile-dot-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-choice-tile-content",
            "div",
            "",
            cls="ah-node-choice-tile-content-node",
            children=[
                "ui:grandmap:node-choice-tile-title",
                "ui:grandmap:node-choice-tile-subtitle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-choice-tile-title",
            "span",
            "",
            cls="ah-node-choice-tile-title-node",
            bind="slot:node-choice-tile-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-choice-tile-subtitle",
            "span",
            "",
            cls="ah-node-choice-tile-subtitle-node",
            bind="slot:node-choice-tile-subtitle",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-choice-tile-status",
            "span",
            "",
            cls="ah-node-choice-tile-status-node",
            bind="slot:node-choice-tile-status",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_kv_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-kv-row"
    nodes = [
        _slot("slot:node-kv-row-key", "node key value row key", ""),
        _slot("slot:node-kv-row-value", "node key value row value", ""),
        _slot("slot:node-kv-row-state", "node key value row state", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-kv-row-node",
            state_bind="slot:node-kv-row-state",
            children=["ui:grandmap:node-kv-row-key", "ui:grandmap:node-kv-row-value"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-kv-row-key",
            "span",
            "",
            cls="ah-node-kv-row-key-node",
            bind="slot:node-kv-row-key",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-kv-row-value",
            "span",
            "",
            cls="ah-node-kv-row-value-node",
            bind="slot:node-kv-row-value",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_output_port_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-output-port-row"
    nodes = [
        _slot("slot:node-output-port-row-key", "node output port key", ""),
        _slot("slot:node-output-port-row-description", "node output port description", ""),
        _slot("slot:node-output-port-row-type", "node output port type", "any"),
        _slot("slot:node-output-port-row-state", "node output port state", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-output-port-row-node",
            state_bind="slot:node-output-port-row-state",
            action="node-output-port-row.press",
            args={"output_id": ""},
            children=[
                "ui:grandmap:node-output-port-row-key",
                "ui:grandmap:node-output-port-row-description",
                "ui:grandmap:node-output-port-row-type",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-port-row-key",
            "span",
            "",
            cls="ah-node-output-port-row-key-node",
            bind="slot:node-output-port-row-key",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-port-row-description",
            "span",
            "",
            cls="ah-node-output-port-row-description-node",
            bind="slot:node-output-port-row-description",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-output-port-row-type",
            "span",
            "",
            cls="ah-node-output-port-row-type-node",
            bind="slot:node-output-port-row-type",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_icon_button_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-icon-button"
    nodes = [
        _slot("slot:node-icon-button-icon", "node icon button icon", ""),
        _slot("slot:node-icon-button-label", "node icon button label", ""),
        _slot("slot:node-icon-button-active", "node icon button active", "false"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-node-icon-button-node",
            active_bind="slot:node-icon-button-active",
            action="node-icon-button.press",
            args={"button_id": ""},
            children=[
                "ui:grandmap:node-icon-button-icon",
                "ui:grandmap:node-icon-button-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-icon-button-icon",
            "span",
            "",
            cls="ah-node-icon-button-icon-node",
            bind="slot:node-icon-button-icon",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-icon-button-label",
            "span",
            "",
            cls="ah-node-icon-button-label-node",
            bind="slot:node-icon-button-label",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_markdown_block_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-markdown-block"
    nodes = [
        _slot("slot:node-markdown-block-kind", "node markdown block kind", "p"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-markdown-block-node",
            state_bind="slot:node-markdown-block-kind",
            render_slot="slot:node-markdown-block-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_markdown_list_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-markdown-list"
    nodes = [
        _el(
            root_id,
            "ul",
            "",
            cls="ah-node-markdown-list-node",
            render_slot="slot:node-markdown-list-items",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_markdown_list_item_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-markdown-list-item"
    nodes = [
        _el(
            root_id,
            "li",
            "",
            cls="ah-node-markdown-list-item-node",
            render_slot="slot:node-markdown-list-item-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_markdown_inline_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-markdown-inline"
    nodes = [
        _slot("slot:node-markdown-inline-text", "node markdown inline text", ""),
        _slot("slot:node-markdown-inline-kind", "node markdown inline kind", "text"),
        _el(
            root_id,
            "span",
            "",
            cls="ah-node-markdown-inline-node",
            bind="slot:node-markdown-inline-text",
            state_bind="slot:node-markdown-inline-kind",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_markdown_link_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-markdown-link"
    nodes = [
        _slot("slot:node-markdown-link-text", "node markdown link text", ""),
        _slot("slot:node-markdown-link-href", "node markdown link href", ""),
        _el(
            root_id,
            "a",
            "",
            cls="ah-node-markdown-link-node",
            bind="slot:node-markdown-link-text",
            href_bind="slot:node-markdown-link-href",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_markdown_image_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-markdown-image"
    nodes = [
        _slot("slot:node-markdown-image-src", "node markdown image source", ""),
        _slot("slot:node-markdown-image-alt", "node markdown image alt", "markdown image"),
        _el(
            root_id,
            "img",
            "",
            cls="ah-node-markdown-image-node",
            src_bind="slot:node-markdown-image-src",
            alt_bind="slot:node-markdown-image-alt",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_stage_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-stage-preview"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-stage-preview-node",
            render_slot="slot:node-stage-preview-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_stage_image_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-stage-image-preview"
    nodes = [
        _slot("slot:node-stage-image-preview-src", "node stage image preview source", ""),
        _slot("slot:node-stage-image-preview-alt", "node stage image preview alt", "node output preview"),
        _el(
            root_id,
            "img",
            "",
            cls="ah-node-stage-image-preview-node",
            src_bind="slot:node-stage-image-preview-src",
            alt_bind="slot:node-stage-image-preview-alt",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_stage_text_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-stage-text-preview"
    nodes = [
        _slot("slot:node-stage-text-preview-text", "node stage text preview text", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-stage-text-preview-node",
            bind="slot:node-stage-text-preview-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_stage_empty_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-stage-empty-preview"
    nodes = [
        _slot("slot:node-stage-empty-preview-text", "node stage empty preview text", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-stage-empty-preview-node",
            bind="slot:node-stage-empty-preview-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_preformatted_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-preformatted-preview"
    nodes = [
        _slot("slot:node-preformatted-preview-text", "node preformatted preview text", ""),
        _el(
            root_id,
            "pre",
            "",
            cls="ah-node-preformatted-preview-node",
            bind="slot:node-preformatted-preview-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_image_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-image-preview"
    nodes = [
        _slot("slot:node-image-preview-src", "node image preview source", ""),
        _slot("slot:node-image-preview-alt", "node image preview alt", "watch"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-image-preview-node",
            children=["ui:grandmap:node-image-preview-img"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-image-preview-img",
            "img",
            "",
            cls="ah-node-image-preview-img-node",
            src_bind="slot:node-image-preview-src",
            alt_bind="slot:node-image-preview-alt",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_list_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-list-preview"
    nodes = [
        _el(
            root_id,
            "ul",
            "",
            cls="ah-node-list-preview-node",
            render_slot="slot:node-list-preview-items",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_list_preview_item_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-list-preview-item"
    nodes = [
        _slot("slot:node-list-preview-item-text", "node list preview item text", ""),
        _slot("slot:node-list-preview-item-state", "node list preview item state", ""),
        _el(
            root_id,
            "li",
            "",
            cls="ah-node-list-preview-item-node",
            bind="slot:node-list-preview-item-text",
            state_bind="slot:node-list-preview-item-state",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_table_preview_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-table-preview"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-table-preview-node",
            children=["ui:grandmap:node-table-preview-table"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-table-preview-table",
            "table",
            "",
            cls="ah-node-table-preview-table-node",
            children=[
                "ui:grandmap:node-table-preview-head",
                "ui:grandmap:node-table-preview-body",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-table-preview-head",
            "thead",
            "",
            cls="ah-node-table-preview-head-node",
            children=["ui:grandmap:node-table-preview-head-row"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-table-preview-head-row",
            "tr",
            "",
            cls="ah-node-table-preview-head-row-node",
            render_slot="slot:node-table-preview-header",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-table-preview-body",
            "tbody",
            "",
            cls="ah-node-table-preview-body-node",
            render_slot="slot:node-table-preview-rows",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_table_header_cell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-table-header-cell"
    nodes = [
        _slot("slot:node-table-header-cell-text", "node table header cell text", ""),
        _slot("slot:node-table-header-cell-align", "node table header cell align", ""),
        _el(
            root_id,
            "th",
            "",
            cls="ah-node-table-header-cell-node",
            bind="slot:node-table-header-cell-text",
            state_bind="slot:node-table-header-cell-align",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_table_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-table-row"
    nodes = [
        _slot("slot:node-table-row-state", "node table row state", ""),
        _el(
            root_id,
            "tr",
            "",
            cls="ah-node-table-row-node",
            state_bind="slot:node-table-row-state",
            render_slot="slot:node-table-row-cells",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_table_cell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-table-cell"
    nodes = [
        _slot("slot:node-table-cell-text", "node table cell text", ""),
        _slot("slot:node-table-cell-align", "node table cell align", ""),
        _el(
            root_id,
            "td",
            "",
            cls="ah-node-table-cell-node",
            bind="slot:node-table-cell-text",
            state_bind="slot:node-table-cell-align",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _canvas_node_socket_surface(path: Path, surface: str) -> dict[str, Any]:
    sources, error = _canvas_node_card_sources(path, surface, "canvas node socket")
    if error:
        return error
    assert sources is not None

    root_id = "ui:grandmap:canvas-node-socket"
    children = [
        "ui:grandmap:canvas-node-socket-dot",
        "ui:grandmap:canvas-node-socket-label",
    ]
    nodes = [
        _slot("slot:canvas-node-socket-label", "socket label", ""),
        _slot("slot:canvas-node-socket-side", "socket side", ""),
        _slot("slot:canvas-node-socket-type", "socket type", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-node-socket-node",
            children=children,
            data_attrs={"data-lm-socket-surface": "1"},
            source_node=sources["canvas_node_view"],
        ),
        _el(
            "ui:grandmap:canvas-node-socket-dot",
            "span",
            "",
            cls="ah-canvas-node-socket-dot-node",
            data_attrs={"data-lm-socket-dot": "1"},
            source_node=sources["canvas_node_view"],
        ),
        _el(
            "ui:grandmap:canvas-node-socket-label",
            "span",
            "",
            cls="ah-canvas-node-socket-label-node",
            bind="slot:canvas-node-socket-label",
            source_node=sources["ui_node_card"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_node_card", "canvas_node_view"],
    }


def _canvas_context_menu_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-context-menu"
    item_defs = [
        ("add-node", "Add node...", "canvas.menu.add-node", ""),
        ("paste", "Paste", "canvas.menu.paste", ""),
        ("sep-a", "", "", "sep"),
        ("fit", "Fit graph to view", "canvas.menu.fit", ""),
        ("zoom-100", "Zoom to 100%", "canvas.menu.zoom-100", ""),
        ("sep-b", "", "", "sep"),
        ("snap", "Snap to grid", "canvas.menu.snap.toggle", "toggle"),
        ("auto-layout", "Auto-layout", "canvas.menu.auto-layout", ""),
        ("sep-c", "", "", "sep"),
        ("reset-positions", "Reset positions", "canvas.menu.reset-positions", ""),
        ("clear", "Clear all nodes", "canvas.menu.clear", "danger"),
    ]
    children = [f"ui:grandmap:canvas-menu-{key}" for key, _text, _action, _kind in item_defs]
    nodes = [
        _slot("slot:canvas-snap-to-grid", "snap", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-context-menu-node",
            children=children,
            source_node=source_node,
        ),
    ]
    for key, text, action, kind in item_defs:
        node_id = f"ui:grandmap:canvas-menu-{key}"
        if kind == "sep":
            nodes.append(_el(
                node_id,
                "div",
                "",
                cls="ah-canvas-context-menu-separator-node",
                source_node=source_node,
            ))
            continue
        cls = "ah-canvas-context-menu-item-node"
        if kind == "danger":
            cls += " ah-canvas-context-menu-danger-node"
        if kind == "toggle":
            cls += " ah-canvas-context-menu-toggle-node"
        nodes.append(_el(
            node_id,
            "button",
            text,
            cls=cls,
            action=action,
            active_bind="slot:canvas-snap-to-grid" if kind == "toggle" else "",
            active_value="true" if kind == "toggle" else "",
            source_node=source_node,
        ))

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _wire_context_menu_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:wire-context-menu"
    item_defs = [
        ("pick-source", "Pick source field...", "wire.menu.pick-source", ""),
        ("pick-dest", "Pick destination field...", "wire.menu.pick-dest", ""),
        ("sep-a", "", "", "sep"),
        ("toggle-gate", "Block wire", "wire.menu.toggle-gate", "gate"),
        ("toggle-codec", "Encode base64", "wire.menu.toggle-codec", "codec"),
        ("toggle-presentation", "Hide wire", "wire.menu.toggle-presentation", "presentation"),
        ("sep-runtime", "", "", "sep"),
        ("swap-target", "Swap target...", "wire.menu.swap-target", ""),
        ("freeze-target", "Freeze target", "wire.menu.freeze-target", "frozen"),
        ("bypass-target", "Bypass target", "wire.menu.bypass-target", "bypassed"),
        ("sep-b", "", "", "sep"),
        ("disconnect", "Disconnect", "wire.menu.disconnect", "danger"),
    ]
    children = [f"ui:grandmap:wire-menu-{key}" for key, _text, _action, _kind in item_defs]
    nodes = [
        _slot("slot:wire-target-frozen", "frozen", "false"),
        _slot("slot:wire-target-bypassed", "bypassed", "false"),
        _slot("slot:wire-gate-blocked", "gate blocked", "false"),
        _slot("slot:wire-codec-base64", "codec base64", "false"),
        _slot("slot:wire-presentation-hidden", "presentation hidden", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-wire-context-menu-node",
            children=children,
            source_node=source_node,
        ),
    ]
    for key, text, action, kind in item_defs:
        node_id = f"ui:grandmap:wire-menu-{key}"
        if kind == "sep":
            nodes.append(_el(
                node_id,
                "div",
                "",
                cls="ah-wire-context-menu-separator-node",
                source_node=source_node,
            ))
            continue
        cls = "ah-wire-context-menu-item-node"
        if kind == "danger":
            cls += " ah-wire-context-menu-danger-node"
        text_cases = None
        active_bind = ""
        if kind == "frozen":
            active_bind = "slot:wire-target-frozen"
            text_cases = {
                "bind": "slot:wire-target-frozen",
                "values": {"true": "Unfreeze target", "false": "Freeze target"},
                "default": "Freeze target",
            }
        elif kind == "bypassed":
            active_bind = "slot:wire-target-bypassed"
            text_cases = {
                "bind": "slot:wire-target-bypassed",
                "values": {"true": "Un-bypass target", "false": "Bypass target"},
                "default": "Bypass target",
            }
        elif kind == "gate":
            active_bind = "slot:wire-gate-blocked"
            text_cases = {
                "bind": "slot:wire-gate-blocked",
                "values": {"true": "Open wire gate", "false": "Block wire gate"},
                "default": "Block wire gate",
            }
        elif kind == "codec":
            active_bind = "slot:wire-codec-base64"
            text_cases = {
                "bind": "slot:wire-codec-base64",
                "values": {"true": "Decode to plain text", "false": "Encode as base64"},
                "default": "Encode as base64",
            }
        elif kind == "presentation":
            active_bind = "slot:wire-presentation-hidden"
            text_cases = {
                "bind": "slot:wire-presentation-hidden",
                "values": {"true": "Show wire", "false": "Hide wire"},
                "default": "Hide wire",
            }
        nodes.append(_el(
            node_id,
            "button",
            text,
            cls=cls,
            action=action,
            active_bind=active_bind,
            active_value="true" if active_bind else "",
            text_cases=text_cases,
            source_node=source_node,
        ))

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_context_menu_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-context-menu"
    item_defs = [
        ("run", "Run", "node.menu.run", ""),
        ("freeze", "Freeze / unfreeze (hold cached)", "node.menu.freeze", ""),
        ("bypass", "Bypass / un-bypass (skip + passthrough)", "node.menu.bypass", ""),
        ("rename", "Rename", "node.menu.rename", ""),
        ("duplicate", "Duplicate", "node.menu.duplicate", ""),
        ("save-skill", "Save as Skill", "node.menu.save-skill", ""),
        ("flatten", "Flatten selected nodes to Code", "node.menu.flatten", "flattenable"),
        ("expand", "Expand subgraph", "node.menu.expand", "is-subgraph"),
        ("disentangle", "Disentangle (snapshot)", "node.menu.disentangle", "shared-skill"),
        ("sep-a", "", "", "sep"),
        ("disconnect", "Disconnect all", "node.menu.disconnect", ""),
        ("properties", "Properties", "node.menu.properties", ""),
        ("sep-b", "", "", "sep"),
        ("delete", "Delete", "node.menu.delete", "danger"),
    ]
    children = [f"ui:grandmap:node-menu-{key}" for key, _text, _action, _kind in item_defs]
    nodes = [
        _slot("slot:node-menu-is-subgraph", "is subgraph", "false"),
        _slot("slot:node-menu-shared-skill", "shared skill", "false"),
        _slot("slot:node-menu-flattenable", "flattenable", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-context-menu-node",
            children=children,
            source_node=source_node,
        ),
    ]
    hidden_slots = {
        "flattenable": "slot:node-menu-flattenable",
        "is-subgraph": "slot:node-menu-is-subgraph",
        "shared-skill": "slot:node-menu-shared-skill",
    }
    for key, text, action, kind in item_defs:
        node_id = f"ui:grandmap:node-menu-{key}"
        if kind == "sep":
            nodes.append(_el(
                node_id,
                "div",
                "",
                cls="ah-node-context-menu-separator-node",
                source_node=source_node,
            ))
            continue
        cls = "ah-node-context-menu-item-node"
        if kind == "danger":
            cls += " ah-node-context-menu-danger-node"
        hidden_bind = hidden_slots.get(kind, "")
        nodes.append(_el(
            node_id,
            "button",
            text,
            cls=cls,
            action=action,
            hidden_bind=hidden_bind,
            hidden_value="false" if hidden_bind else "",
            source_node=source_node,
        ))

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _canvas_gesture_hint_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-gesture-hint"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-gesture-hint-node",
            children=[
                "ui:grandmap:canvas-hint-scroll",
                "ui:grandmap:canvas-hint-sep-a",
                "ui:grandmap:canvas-hint-drag",
                "ui:grandmap:canvas-hint-sep-b",
                "ui:grandmap:canvas-hint-menu",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:canvas-hint-scroll", "span", "scroll -> zoom", cls="", source_node=source_node),
        _el("ui:grandmap:canvas-hint-sep-a", "span", ".", cls="ah-canvas-gesture-separator-node", source_node=source_node),
        _el("ui:grandmap:canvas-hint-drag", "span", "drag -> pan", cls="", source_node=source_node),
        _el("ui:grandmap:canvas-hint-sep-b", "span", ".", cls="ah-canvas-gesture-separator-node", source_node=source_node),
        _el("ui:grandmap:canvas-hint-menu", "span", "right-click -> menu", cls="", source_node=source_node),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _graph_health_badge_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "canvas": ["canvas_wire_layer"],
        "nodes": ["nodes_validator"],
    }
    try:
        domains = {key: _load_domain_nodes(path, key) for key in required}
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domains[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                sources[node_id] = node
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map graph-health source nodes: " + ", ".join(missing),
        }

    canvas_node = sources["canvas_wire_layer"]
    validator_node = sources["nodes_validator"]
    root_id = "ui:grandmap:graph-health-badge"
    nodes = [
        _slot("slot:graph-health-open", "graph health open", "false"),
        _slot("slot:graph-health-state", "graph health state", "ok"),
        _slot("slot:graph-health-summary", "graph health summary", "ok"),
        _slot("slot:graph-health-errors", "graph health errors", "0 err"),
        _slot("slot:graph-health-warnings", "graph health warnings", "0 warn"),
        _slot("slot:graph-health-has-issues", "graph health has issues", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-graph-health-root-node",
            data_attrs={
                "data-no-pan": "true",
                "data-testid": "graph-health-badge",
            },
            children=[
                "ui:grandmap:graph-health-collapsed",
                "ui:grandmap:graph-health-panel",
            ],
            source_node=canvas_node,
        ),
        _el(
            "ui:grandmap:graph-health-collapsed",
            "button",
            "",
            cls="ah-graph-health-button-node",
            action="graph-health.open",
            state_bind="slot:graph-health-state",
            visible_when={"bind": "slot:graph-health-open", "value": "false"},
            data_attrs={"aria-label": "graph health"},
            children=[
                "ui:grandmap:graph-health-summary",
                "ui:grandmap:graph-health-label",
            ],
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-summary",
            "span",
            "",
            cls="ah-graph-health-summary-node",
            bind="slot:graph-health-summary",
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-label",
            "span",
            "HEALTH v",
            cls="ah-graph-health-label-node",
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-panel",
            "div",
            "",
            cls="ah-graph-health-panel-node",
            role="dialog",
            visible_when={"bind": "slot:graph-health-open", "value": "true"},
            data_attrs={
                "data-testid": "graph-health-panel",
                "aria-label": "Graph health",
            },
            children=[
                "ui:grandmap:graph-health-panel-head",
                "ui:grandmap:graph-health-panel-body",
            ],
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-panel-head",
            "div",
            "",
            cls="ah-graph-health-head-node",
            children=[
                "ui:grandmap:graph-health-title",
                "ui:grandmap:graph-health-error-count",
                "ui:grandmap:graph-health-warning-count",
                "ui:grandmap:graph-health-self-heal",
                "ui:grandmap:graph-health-close",
            ],
            source_node=validator_node,
        ),
        _el("ui:grandmap:graph-health-title", "span", "GRAPH HEALTH", cls="ah-graph-health-title-node", source_node=validator_node),
        _el("ui:grandmap:graph-health-error-count", "span", "", cls="ah-graph-health-error-count-node", bind="slot:graph-health-errors", source_node=validator_node),
        _el("ui:grandmap:graph-health-warning-count", "span", "", cls="ah-graph-health-warning-count-node", bind="slot:graph-health-warnings", source_node=validator_node),
        _el(
            "ui:grandmap:graph-health-self-heal",
            "button",
            "* heals",
            cls="ah-graph-health-self-heal-node",
            action="graph-health.self-heal",
            test_id="graph-health-self-heal",
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-close",
            "button",
            "x",
            cls="ah-graph-health-close-node",
            action="graph-health.close",
            data_attrs={"aria-label": "close health panel"},
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-panel-body",
            "div",
            "",
            cls="ah-graph-health-body-node",
            children=[
                "ui:grandmap:graph-health-empty",
                "ui:grandmap:graph-health-issue-list",
            ],
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:graph-health-empty",
            "div",
            "",
            cls="ah-graph-health-empty-node",
            visible_when={"bind": "slot:graph-health-has-issues", "value": "false"},
            children=[
                "ui:grandmap:graph-health-empty-dot",
                "ui:grandmap:graph-health-empty-title",
                "ui:grandmap:graph-health-empty-sub",
            ],
            source_node=validator_node,
        ),
        _el("ui:grandmap:graph-health-empty-dot", "div", "ok", cls="ah-graph-health-empty-dot-node", source_node=validator_node),
        _el("ui:grandmap:graph-health-empty-title", "div", "all clean - graph valid", cls="ah-graph-health-empty-title-node", source_node=validator_node),
        _el("ui:grandmap:graph-health-empty-sub", "div", "edits revalidate live", cls="ah-graph-health-empty-sub-node", source_node=validator_node),
        _el(
            "ui:grandmap:graph-health-issue-list",
            "div",
            "",
            cls="ah-graph-health-issue-list-node",
            render_slot="slot:graph-health-issues",
            visible_when={"bind": "slot:graph-health-has-issues", "value": "true"},
            source_node=validator_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["canvas_wire_layer", "nodes_validator"],
    }


def _graph_health_issue_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        nodes_domain = _load_domain_nodes(path, "nodes")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "nodes_validator"
    if source_id not in nodes_domain:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map graph-health source node: " + source_id,
        }
    source_node = nodes_domain[source_id]
    root_id = "ui:grandmap:graph-health-issue-row"
    nodes = [
        _slot("slot:graph-health-issue-level", "graph health issue level", "warn"),
        _slot("slot:graph-health-issue-code", "graph health issue code", ""),
        _slot("slot:graph-health-issue-target", "graph health issue target", ""),
        _slot("slot:graph-health-issue-has-target", "graph health issue has target", "false"),
        _slot("slot:graph-health-issue-message", "graph health issue message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-graph-health-issue-row-node",
            action="graph-health.issue.focus",
            state_bind="slot:graph-health-issue-level",
            test_id="graph-health-issue",
            children=[
                "ui:grandmap:graph-health-issue-head",
                "ui:grandmap:graph-health-issue-message",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:graph-health-issue-head",
            "div",
            "",
            cls="ah-graph-health-issue-head-node",
            children=[
                "ui:grandmap:graph-health-issue-level",
                "ui:grandmap:graph-health-issue-code",
                "ui:grandmap:graph-health-issue-target",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:graph-health-issue-level", "span", "", cls="ah-graph-health-issue-level-node", bind="slot:graph-health-issue-level", source_node=source_node),
        _el("ui:grandmap:graph-health-issue-code", "span", "", cls="ah-graph-health-issue-code-node", bind="slot:graph-health-issue-code", source_node=source_node),
        _el(
            "ui:grandmap:graph-health-issue-target",
            "span",
            "@",
            cls="ah-graph-health-issue-target-node",
            bind="slot:graph-health-issue-target",
            visible_when={"bind": "slot:graph-health-issue-has-target", "value": "true"},
            source_node=source_node,
        ),
        _el("ui:grandmap:graph-health-issue-message", "div", "", cls="ah-graph-health-issue-message-node", bind="slot:graph-health-issue-message", source_node=source_node),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _health_strip_item_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "canvas": ["canvas_wire_layer"],
        "nodes": ["nodes_validator"],
    }
    try:
        domains = {key: _load_domain_nodes(path, key) for key in required}
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domains[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                sources[node_id] = node
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map health-strip source nodes: " + ", ".join(missing),
        }

    canvas_node = sources["canvas_wire_layer"]
    validator_node = sources["nodes_validator"]
    root_id = "ui:grandmap:health-strip-item"
    nodes = [
        _slot("slot:health-strip-open", "health strip open", "false"),
        _slot("slot:health-strip-hidden", "health strip hidden", "false"),
        _slot("slot:health-strip-state", "health strip state", "ok"),
        _slot("slot:health-strip-label", "health strip label", "healthy"),
        _slot("slot:health-strip-errors", "health strip errors", "0 err"),
        _slot("slot:health-strip-warnings", "health strip warnings", "0 warn"),
        _slot("slot:health-strip-has-issues", "health strip has issues", "false"),
        _slot("slot:health-strip-empty", "health strip empty", "graph valid - 0 issues"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-health-strip-root-node",
            data_attrs={"data-no-pan": "true"},
            children=[
                "ui:grandmap:health-strip-button",
                "ui:grandmap:health-strip-overlay",
            ],
            source_node=canvas_node,
        ),
        _el(
            "ui:grandmap:health-strip-button",
            "button",
            "",
            cls="ah-health-strip-button-node",
            bind="slot:health-strip-label",
            action="health-strip.toggle",
            state_bind="slot:health-strip-state",
            visible_when={"bind": "slot:health-strip-hidden", "value": "false"},
            test_id="health-strip-item",
            data_attrs={"title": "Graph health"},
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-overlay",
            "div",
            "",
            cls="ah-health-strip-overlay-node",
            action="health-strip.close",
            visible_when={"bind": "slot:health-strip-open", "value": "true"},
            children=["ui:grandmap:health-strip-panel"],
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-panel",
            "div",
            "",
            cls="ah-health-strip-panel-node",
            role="dialog",
            action="health-strip.noop",
            data_attrs={"aria-label": "Graph health"},
            children=[
                "ui:grandmap:health-strip-head",
                "ui:grandmap:health-strip-body",
            ],
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-head",
            "div",
            "",
            cls="ah-health-strip-head-node",
            children=[
                "ui:grandmap:health-strip-title",
                "ui:grandmap:health-strip-error-count",
                "ui:grandmap:health-strip-warning-count",
                "ui:grandmap:health-strip-self-heal",
                "ui:grandmap:health-strip-close",
            ],
            source_node=validator_node,
        ),
        _el("ui:grandmap:health-strip-title", "span", "GRAPH HEALTH", cls="ah-health-strip-title-node", source_node=validator_node),
        _el("ui:grandmap:health-strip-error-count", "span", "", cls="ah-health-strip-error-count-node", bind="slot:health-strip-errors", source_node=validator_node),
        _el("ui:grandmap:health-strip-warning-count", "span", "", cls="ah-health-strip-warning-count-node", bind="slot:health-strip-warnings", source_node=validator_node),
        _el(
            "ui:grandmap:health-strip-self-heal",
            "button",
            "* heals",
            cls="ah-health-strip-self-heal-node",
            action="health-strip.self-heal",
            test_id="health-strip-self-heal",
            data_attrs={"title": "Self-Heal Inspector - recovery timeline"},
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-close",
            "button",
            "x",
            cls="ah-health-strip-close-node",
            action="health-strip.close",
            data_attrs={"aria-label": "close health panel"},
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-body",
            "div",
            "",
            cls="ah-health-strip-body-node",
            children=[
                "ui:grandmap:health-strip-empty",
                "ui:grandmap:health-strip-issue-list",
            ],
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-empty",
            "div",
            "",
            cls="ah-health-strip-empty-node",
            bind="slot:health-strip-empty",
            visible_when={"bind": "slot:health-strip-has-issues", "value": "false"},
            source_node=validator_node,
        ),
        _el(
            "ui:grandmap:health-strip-issue-list",
            "div",
            "",
            cls="ah-health-strip-issue-list-node",
            render_slot="slot:health-strip-issues",
            visible_when={"bind": "slot:health-strip-has-issues", "value": "true"},
            source_node=validator_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["canvas_wire_layer", "nodes_validator"],
    }


def _node_actions_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-actions-panel"
    action_defs = [
        ("rerun", "\u21bb Rerun this node", "node.rail.rerun", "primary"),
        ("pin-skill", "Pin to skill", "node.rail.pin-skill", ""),
        ("branch", "Branch from here", "node.rail.branch", ""),
        ("disconnect", "Disconnect all", "node.rail.disconnect", "danger"),
    ]
    children = [f"ui:grandmap:node-action-{key}" for key, _text, _action, _kind in action_defs]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-actions-panel-node",
            children=children,
            source_node=source_node,
        ),
    ]
    for key, text, action, kind in action_defs:
        cls = "ah-node-action-button-node"
        if kind == "primary":
            cls += " ah-node-action-primary-node"
        if kind == "danger":
            cls += " ah-node-action-danger-node"
        nodes.append(_el(
            f"ui:grandmap:node-action-{key}",
            "button",
            text,
            cls=cls,
            action=action,
            source_node=source_node,
        ))

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_summary_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-summary-panel"
    nodes = [
        _slot("slot:node-summary-icon", "node summary icon", ""),
        _slot("slot:node-summary-label", "node summary label", ""),
        _slot("slot:node-summary-title", "node summary title", ""),
        _slot("slot:node-summary-subtitle", "node summary subtitle", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-summary-panel-node",
            children=[
                "ui:grandmap:node-summary-meta",
                "ui:grandmap:node-summary-title",
                "ui:grandmap:node-summary-subtitle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-summary-meta",
            "div",
            "",
            cls="ah-node-summary-meta-node",
            children=[
                "ui:grandmap:node-summary-icon",
                "ui:grandmap:node-summary-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-summary-icon",
            "span",
            "",
            cls="ah-node-summary-icon-node",
            bind="slot:node-summary-icon",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-summary-label",
            "span",
            "",
            cls="ah-node-summary-label-node",
            bind="slot:node-summary-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-summary-title",
            "div",
            "",
            cls="ah-node-summary-title-node",
            bind="slot:node-summary-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-summary-subtitle",
            "div",
            "",
            cls="ah-node-summary-subtitle-node",
            bind="slot:node-summary-subtitle",
            hidden_bind="slot:node-summary-subtitle",
            hidden_value="",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_connections_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-connections-panel"
    nodes = [
        _slot("slot:node-connections-has-receives", "has receives", "false"),
        _slot("slot:node-connections-has-sends", "has sends", "false"),
        _slot("slot:node-connection-pin-label", "pin label", ""),
        _slot("slot:node-connection-pin-value", "pin value", ""),
        _slot("slot:node-connection-pin-anatomy", "pin wire anatomy", ""),
        _slot("slot:node-connection-port-label", "port node label", ""),
        _slot("slot:node-connection-other-port-label", "other port node label", ""),
        _slot("slot:node-connection-junction-label", "wire junction label", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-connections-panel-node",
            children=[
                "ui:grandmap:node-connections-heading",
                "ui:grandmap:node-connections-box",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-heading",
            "div",
            "CONNECTIONS",
            cls="ah-node-connections-heading-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-box",
            "div",
            "",
            cls="ah-node-connections-box-node",
            children=[
                "ui:grandmap:node-connections-receives",
                "ui:grandmap:node-connections-sends",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-receives",
            "div",
            "",
            cls="ah-node-connections-group-node",
            hidden_bind="slot:node-connections-has-receives",
            hidden_value="false",
            children=[
                "ui:grandmap:node-connections-receives-title",
                "ui:grandmap:node-connections-receives-list",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-receives-title",
            "div",
            "RECEIVES",
            cls="ah-node-connections-group-title-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-receives-list",
            "div",
            "",
            cls="ah-node-connections-list-node",
            children=[],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-sends",
            "div",
            "",
            cls="ah-node-connections-group-node",
            hidden_bind="slot:node-connections-has-sends",
            hidden_value="false",
            children=[
                "ui:grandmap:node-connections-sends-title",
                "ui:grandmap:node-connections-sends-list",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-sends-title",
            "div",
            "SENDS",
            cls="ah-node-connections-group-title-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connections-sends-list",
            "div",
            "",
            cls="ah-node-connections-list-node",
            children=[],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-pin-row",
            "div",
            "",
            cls="ah-node-connection-pin-row-node",
            children=[
                "ui:grandmap:node-connection-pin-dot",
                "ui:grandmap:node-connection-pin-label",
                "ui:grandmap:node-connection-pin-line",
                "ui:grandmap:node-connection-pin-value",
                "ui:grandmap:node-connection-pin-anatomy",
                "ui:grandmap:node-connection-port-strip",
                "ui:grandmap:node-connection-junction-strip",
                "ui:grandmap:node-connection-layer-strip",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-pin-dot",
            "span",
            "",
            cls="ah-node-connection-pin-dot-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-pin-label",
            "span",
            "",
            cls="ah-node-connection-pin-label-node",
            bind="slot:node-connection-pin-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-pin-line",
            "div",
            "",
            cls="ah-node-connection-pin-line-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-pin-value",
            "span",
            "",
            cls="ah-node-connection-pin-value-node",
            bind="slot:node-connection-pin-value",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-pin-anatomy",
            "span",
            "",
            cls="ah-node-connection-pin-anatomy-node",
            bind="slot:node-connection-pin-anatomy",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-port-strip",
            "span",
            "",
            cls="ah-node-connection-port-strip-node",
            children=[
                "ui:grandmap:node-connection-port-chip",
                "ui:grandmap:node-connection-other-port-chip",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-port-chip",
            "button",
            "",
            cls="ah-node-connection-port-chip-node",
            bind="slot:node-connection-port-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-other-port-chip",
            "button",
            "",
            cls="ah-node-connection-port-chip-node ah-node-connection-other-port-chip-node",
            bind="slot:node-connection-other-port-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-junction-strip",
            "span",
            "",
            cls="ah-node-connection-junction-strip-node",
            children=[
                "ui:grandmap:node-connection-junction-chip",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-junction-chip",
            "button",
            "",
            cls="ah-node-connection-junction-chip-node",
            bind="slot:node-connection-junction-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-layer-strip",
            "span",
            "",
            cls="ah-node-connection-layer-strip-node",
            children=[
                "ui:grandmap:node-connection-layer-chip",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-connection-layer-chip",
            "button",
            "",
            cls="ah-node-connection-layer-chip-node",
            bind="slot:node-connection-layer-label",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_rail_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-rail-shell"
    nodes = [
        _el(
            root_id,
            "aside",
            "",
            cls="ah-node-rail-shell-node ah-scroll",
            children=[
                "ui:grandmap:node-rail-summary",
                "ui:grandmap:node-rail-properties",
                "ui:grandmap:node-rail-connections",
                "ui:grandmap:node-rail-special",
                "ui:grandmap:node-rail-plan",
                "ui:grandmap:node-rail-actions",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-rail-summary",
            "div",
            "",
            cls="ah-node-rail-summary-slot-node",
            render_slot="slot:node-rail-summary",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-rail-connections",
            "div",
            "",
            cls="ah-node-rail-connections-slot-node",
            render_slot="slot:node-rail-connections",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-rail-properties",
            "div",
            "",
            cls="ah-node-rail-properties-slot-node",
            render_slot="slot:node-rail-properties",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-rail-special",
            "div",
            "",
            cls="ah-node-rail-special-slot-node",
            render_slot="slot:node-rail-special",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-rail-plan",
            "div",
            "",
            cls="ah-node-rail-plan-slot-node",
            render_slot="slot:node-rail-plan",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-rail-actions",
            "div",
            "",
            cls="ah-node-rail-actions-slot-node",
            render_slot="slot:node-rail-actions",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_rail_empty_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    root_id = "ui:grandmap:node-rail-empty-shell"
    nodes = [
        _el(
            root_id,
            "aside",
            "",
            cls="ah-node-rail-empty-shell-node",
            source_node=ui_nodes[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _connector_rail_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-rail-shell"
    slot_defs = [
        ("flush", "slot:connector-rail-flush"),
        ("identity", "slot:connector-rail-identity"),
        ("controls", "slot:connector-rail-controls"),
        ("description", "slot:connector-rail-description"),
        ("destructive", "slot:connector-rail-destructive"),
        ("empty", "slot:connector-rail-empty"),
        ("params", "slot:connector-rail-params"),
        ("run", "slot:connector-rail-run"),
        ("connections", "slot:connector-rail-connections"),
    ]
    children = [f"ui:grandmap:connector-rail-{key}" for key, _slot in slot_defs]
    nodes = [
        _el(
            root_id,
            "aside",
            "",
            cls="ah-connector-rail-shell-node ah-scroll",
            children=children,
            source_node=source_node,
        ),
    ]
    for key, slot_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:connector-rail-{key}",
            "div",
            "",
            cls=f"ah-connector-rail-{key}-slot-node",
            render_slot=slot_id,
            source_node=source_node,
        ))

    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _connector_controls_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-controls-panel"
    nodes = [
        _slot("slot:connector-host-state", "connector host state", "unconfigured"),
        _slot("slot:connector-host-value", "connector host value", ""),
        _slot("slot:connector-host-display", "connector host display", "Connector"),
        _slot("slot:connector-host-mechanism", "connector host mechanism", "LOCKED"),
        _slot("slot:connector-op-value", "connector operation value", ""),
        _slot("slot:connector-op-count", "connector operation count", "0"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-controls-panel-node",
            children=[
                "ui:grandmap:connector-host-picker",
                "ui:grandmap:connector-host-badge-panel",
                "ui:grandmap:connector-op-picker",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-picker",
            "div",
            "",
            cls="ah-connector-host-picker-node",
            visible_when={"bind": "slot:connector-host-state", "values": ["unconfigured"]},
            children=[
                "ui:grandmap:connector-host-picker-label",
                "ui:grandmap:connector-host-select",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-picker-label",
            "div",
            "HOST",
            cls="ah-connector-control-label-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-select",
            "select",
            "",
            cls="ah-connector-control-select-node",
            bind="slot:connector-host-value",
            action="connector.host.pick",
            children=[
                "ui:grandmap:connector-host-placeholder",
                "ui:grandmap:connector-host-option",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-placeholder",
            "option",
            "pick a host",
            option_value="",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-option",
            "option",
            "Host",
            option_value="host",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-badge-panel",
            "div",
            "",
            cls="ah-connector-host-badge-panel-node",
            visible_when={"bind": "slot:connector-host-state", "values": ["configured"]},
            children=[
                "ui:grandmap:connector-host-badge-label",
                "ui:grandmap:connector-host-badge",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-badge-label",
            "div",
            "HOST",
            cls="ah-connector-control-label-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-badge",
            "div",
            "",
            cls="ah-connector-host-badge-node",
            children=[
                "ui:grandmap:connector-host-dot",
                "ui:grandmap:connector-host-display",
                "ui:grandmap:connector-host-mechanism",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-dot",
            "span",
            "",
            cls="ah-connector-host-dot-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-display",
            "span",
            "",
            cls="ah-connector-host-display-node",
            bind="slot:connector-host-display",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-host-mechanism",
            "span",
            "",
            cls="ah-connector-host-mechanism-node",
            bind="slot:connector-host-mechanism",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-op-picker",
            "div",
            "",
            cls="ah-connector-op-picker-node",
            visible_when={"bind": "slot:connector-host-state", "values": ["configured"]},
            children=[
                "ui:grandmap:connector-op-picker-label",
                "ui:grandmap:connector-op-select",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-op-picker-label",
            "div",
            "OPERATION",
            cls="ah-connector-control-label-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-op-select",
            "select",
            "",
            cls="ah-connector-control-select-node",
            bind="slot:connector-op-value",
            action="connector.op.pick",
            children=[
                "ui:grandmap:connector-op-placeholder",
                "ui:grandmap:connector-op-option",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-op-placeholder",
            "option",
            "pick an operation",
            option_value="",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-op-option",
            "option",
            "Operation",
            option_value="op",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _connector_params_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
        node_nodes = _load_domain_nodes(path, "nodes")
        canvas_nodes = _load_domain_nodes(path, "canvas")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    required = {
        "ui_node_card": ui_nodes.get("ui_node_card"),
        "nodes_param_promote": node_nodes.get("nodes_param_promote"),
        "canvas_inline_param_edit": canvas_nodes.get("canvas_inline_param_edit"),
    }
    missing = [key for key, value in required.items() if value is None]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map node(s): " + ", ".join(missing),
        }

    sources = {key: value for key, value in required.items() if value is not None}
    root_id = "ui:grandmap:connector-params-panel"
    nodes = [
        _slot("slot:connector-params-visible", "connector params visible", "false"),
        _slot("slot:connector-params-empty-visible", "connector params empty visible", "false"),
        _slot("slot:connector-params-heading-visible", "connector params heading visible", "true"),
        _slot("slot:connector-params-heading", "connector params heading", "PARAMETERS"),
        _slot("slot:connector-param-tab-label", "connector param tab label", "PARAMETERS"),
        _slot("slot:connector-param-tab-active", "connector param tab active", "false"),
        _slot("slot:connector-param-key", "connector param key", "value"),
        _slot("slot:connector-param-label", "connector param label", "value"),
        _slot("slot:connector-param-value", "connector param value", ""),
        _slot("slot:connector-param-control", "connector param control", "text"),
        _slot("slot:connector-param-type", "connector param type", "text"),
        _slot("slot:connector-param-required", "connector param required", "false"),
        _slot("slot:connector-param-help-visible", "connector param help visible", "false"),
        _slot("slot:connector-param-help", "connector param help", ""),
        _slot("slot:connector-param-loading", "connector param loading", "false"),
        _slot("slot:connector-param-promoted", "connector param promoted", "false"),
        _slot("slot:connector-param-min", "connector param min", ""),
        _slot("slot:connector-param-max", "connector param max", ""),
        _slot("slot:connector-param-step", "connector param step", ""),
        _slot("slot:connector-param-option-label", "connector param option label", ""),
        _slot("slot:connector-param-option-value", "connector param option value", ""),
        _slot("slot:connector-param-option-active", "connector param option active", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-params-panel-node",
            visible_when={"bind": "slot:connector-params-visible", "values": ["true"]},
            children=[
                "ui:grandmap:connector-param-tabs",
                "ui:grandmap:connector-param-heading",
                "ui:grandmap:connector-param-empty",
                "ui:grandmap:connector-param-list",
            ],
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:connector-param-tabs",
            "div",
            "",
            cls="ah-connector-param-tabs-node",
            children=["ui:grandmap:connector-param-tab"],
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:connector-param-tab",
            "button",
            "",
            cls="ah-connector-param-tab-node",
            bind="slot:connector-param-tab-label",
            action="connector.params.tab",
            active_bind="slot:connector-param-tab-active",
            active_value="true",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:connector-param-heading",
            "div",
            "",
            cls="ah-connector-param-heading-node",
            bind="slot:connector-params-heading",
            visible_when={"bind": "slot:connector-params-heading-visible", "values": ["true"]},
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:connector-param-empty",
            "div",
            "No parameters - this op takes its input from a wired upstream node.",
            cls="ah-connector-param-empty-node",
            visible_when={"bind": "slot:connector-params-empty-visible", "values": ["true"]},
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:connector-param-list",
            "div",
            "",
            cls="ah-connector-param-list-node",
            children=["ui:grandmap:connector-param-row"],
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:connector-param-row",
            "div",
            "",
            cls="ah-connector-param-row-node",
            children=[
                "ui:grandmap:connector-param-promote",
                "ui:grandmap:connector-param-body",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-promote",
            "button",
            "⊙",
            cls="ah-connector-param-promote-node",
            action="connector.param.promote",
            active_bind="slot:connector-param-promoted",
            active_value="true",
            source_node=sources["nodes_param_promote"],
        ),
        _el(
            "ui:grandmap:connector-param-body",
            "div",
            "",
            cls="ah-connector-param-body-node",
            children=[
                "ui:grandmap:connector-param-meta",
                "ui:grandmap:connector-param-controls",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-meta",
            "div",
            "",
            cls="ah-connector-param-meta-node",
            children=[
                "ui:grandmap:connector-param-provenance",
                "ui:grandmap:connector-param-label",
                "ui:grandmap:connector-param-required",
                "ui:grandmap:connector-param-loading",
                "ui:grandmap:connector-param-help",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-provenance",
            "span",
            "",
            cls="ah-connector-param-provenance-node",
            state_bind="slot:connector-param-type",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-label",
            "span",
            "",
            cls="ah-connector-param-label-node",
            bind="slot:connector-param-label",
            action="connector.param.focus",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-required",
            "span",
            "required",
            cls="ah-connector-param-required-node",
            visible_when={"bind": "slot:connector-param-required", "values": ["true"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-loading",
            "span",
            "loading...",
            cls="ah-connector-param-loading-node",
            visible_when={"bind": "slot:connector-param-loading", "values": ["true"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-help",
            "span",
            "?",
            cls="ah-connector-param-help-node",
            visible_when={"bind": "slot:connector-param-help-visible", "values": ["true"]},
            data_attrs={"aria-label": "parameter help"},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-controls",
            "div",
            "",
            cls="ah-connector-param-controls-node",
            children=[
                "ui:grandmap:connector-param-text-input",
                "ui:grandmap:connector-param-number-input",
                "ui:grandmap:connector-param-slider-input",
                "ui:grandmap:connector-param-select",
                "ui:grandmap:connector-param-boolean-input",
                "ui:grandmap:connector-param-textarea",
                "ui:grandmap:connector-param-multi-options",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-text-input",
            "input",
            "",
            cls="ah-connector-param-input-node",
            input_type="text",
            bind="slot:connector-param-value",
            action="connector.param.update",
            visible_when={"bind": "slot:connector-param-control", "values": ["text", "file"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-number-input",
            "input",
            "",
            cls="ah-connector-param-input-node",
            input_type="number",
            bind="slot:connector-param-value",
            action="connector.param.update",
            value_cast="number",
            visible_when={"bind": "slot:connector-param-control", "values": ["number"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-slider-input",
            "input",
            "",
            cls="ah-connector-param-slider-node",
            input_type="range",
            bind="slot:connector-param-value",
            action="connector.param.update",
            value_cast="number",
            visible_when={"bind": "slot:connector-param-control", "values": ["slider"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-select",
            "select",
            "",
            cls="ah-connector-param-input-node",
            bind="slot:connector-param-value",
            action="connector.param.update",
            visible_when={"bind": "slot:connector-param-control", "values": ["select"]},
            children=[
                "ui:grandmap:connector-param-select-placeholder",
                "ui:grandmap:connector-param-option",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-select-placeholder",
            "option",
            "pick",
            option_value="",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-option",
            "option",
            "",
            option_value="",
            bind="slot:connector-param-option-label",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-boolean-input",
            "input",
            "",
            cls="ah-connector-param-boolean-node",
            input_type="checkbox",
            bind="slot:connector-param-value",
            action="connector.param.update",
            value_cast="boolean",
            visible_when={"bind": "slot:connector-param-control", "values": ["boolean"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-textarea",
            "textarea",
            "",
            cls="ah-connector-param-input-node ah-connector-param-textarea-node",
            bind="slot:connector-param-value",
            action="connector.param.update",
            visible_when={"bind": "slot:connector-param-control", "values": ["list", "multi-text"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-multi-options",
            "div",
            "",
            cls="ah-connector-param-multi-options-node",
            visible_when={"bind": "slot:connector-param-control", "values": ["multi"]},
            children=["ui:grandmap:connector-param-multi-option"],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:connector-param-multi-option",
            "button",
            "",
            cls="ah-connector-param-multi-option-node",
            bind="slot:connector-param-option-label",
            action="connector.param.multi.toggle",
            active_bind="slot:connector-param-option-active",
            active_value="true",
            source_node=sources["canvas_inline_param_edit"],
        ),
    ]
    nodes_by_id = {node["id"]: node for node in nodes}
    nodes_by_id[root_id]["data"]["group_nodes"] = [
        "ui:grandmap:connector-param-tabs",
        "ui:grandmap:connector-param-tab",
        "ui:grandmap:connector-param-heading",
        "ui:grandmap:connector-param-empty",
        "ui:grandmap:connector-param-list",
        "ui:grandmap:connector-param-row",
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [
            "ui_node_card",
            "nodes_param_promote",
            "canvas_inline_param_edit",
        ],
    }


def _connector_description_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-description-panel"
    nodes = [
        _slot("slot:connector-description-visible", "connector description visible", "false"),
        _slot("slot:connector-description", "connector description", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-description-panel-node",
            bind="slot:connector-description",
            visible_when={"bind": "slot:connector-description-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _connector_destructive_warning_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-destructive-warning"
    nodes = [
        _slot("slot:connector-destructive-visible", "connector destructive visible", "false"),
        _slot("slot:connector-destructive-message", "connector destructive message",
              "mutates the host - runs only on explicit click"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-destructive-warning-node",
            bind="slot:connector-destructive-message",
            visible_when={"bind": "slot:connector-destructive-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _connector_empty_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-empty-panel"
    nodes = [
        _slot("slot:connector-empty-visible", "connector empty visible", "false"),
        _slot("slot:connector-empty-message", "connector empty message",
              "Pick a host to see its operations. One Connector node runs any operation on any connected app - Revit, Excel, Outlook, and more."),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-empty-panel-node",
            bind="slot:connector-empty-message",
            visible_when={"bind": "slot:connector-empty-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _connector_run_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-run-panel"
    nodes = [
        _slot("slot:connector-run-visible", "connector run visible", "false"),
        _slot("slot:connector-run-label", "connector run label", "Run op"),
        _slot("slot:connector-run-disabled", "connector run disabled", "false"),
        _slot("slot:connector-result-visible", "connector result visible", "false"),
        _slot("slot:connector-result-state", "connector result state", "idle"),
        _slot("slot:connector-result-title", "connector result title", ""),
        _slot("slot:connector-result-message", "connector result message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-run-panel-node",
            visible_when={"bind": "slot:connector-run-visible", "values": ["true"]},
            children=[
                "ui:grandmap:connector-run-button",
                "ui:grandmap:connector-result",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-run-button",
            "button",
            "",
            cls="ah-connector-run-button-node",
            bind="slot:connector-run-label",
            action="connector.run",
            disabled_bind="slot:connector-run-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-result",
            "div",
            "",
            cls="ah-connector-result-node",
            visible_when={"bind": "slot:connector-result-visible", "values": ["true"]},
            state_bind="slot:connector-result-state",
            children=[
                "ui:grandmap:connector-result-title",
                "ui:grandmap:connector-result-message",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-result-title",
            "div",
            "",
            cls="ah-connector-result-title-node",
            bind="slot:connector-result-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-result-message",
            "div",
            "",
            cls="ah-connector-result-message-node",
            bind="slot:connector-result-message",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _connector_identity_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-identity-panel"
    nodes = [
        _slot("slot:connector-identity-label", "connector identity label", "CONNECTOR"),
        _slot("slot:connector-identity-title", "connector identity title", "Connector"),
        _slot("slot:connector-identity-subtitle", "connector identity subtitle",
              "one node - every host, every operation"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-identity-panel-node",
            children=[
                "ui:grandmap:connector-identity-meta",
                "ui:grandmap:connector-identity-title",
                "ui:grandmap:connector-identity-subtitle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-identity-meta",
            "div",
            "",
            cls="ah-connector-identity-meta-node",
            children=[
                "ui:grandmap:connector-identity-dot",
                "ui:grandmap:connector-identity-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-identity-dot",
            "span",
            "",
            cls="ah-connector-identity-dot-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-identity-label",
            "span",
            "",
            cls="ah-connector-identity-label-node",
            bind="slot:connector-identity-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-identity-title",
            "div",
            "",
            cls="ah-connector-identity-title-node",
            bind="slot:connector-identity-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-identity-subtitle",
            "div",
            "",
            cls="ah-connector-identity-subtitle-node",
            bind="slot:connector-identity-subtitle",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _connector_connections_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:connector-connections-panel"
    nodes = [
        _slot("slot:connector-connection-pin-label", "connector pin label", ""),
        _slot("slot:connector-connection-pin-value", "connector pin value", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-connector-connections-panel-node",
            children=[
                "ui:grandmap:connector-connections-heading",
                "ui:grandmap:connector-connections-box",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connections-heading",
            "div",
            "CONNECTIONS",
            cls="ah-connector-connections-heading-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connections-box",
            "div",
            "",
            cls="ah-connector-connections-box-node",
            children=[],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connection-pin-row",
            "div",
            "",
            cls="ah-connector-connection-pin-row-node",
            children=[
                "ui:grandmap:connector-connection-pin-dot",
                "ui:grandmap:connector-connection-pin-label",
                "ui:grandmap:connector-connection-pin-line",
                "ui:grandmap:connector-connection-pin-value",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connection-pin-dot",
            "span",
            "",
            cls="ah-connector-connection-pin-dot-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connection-pin-label",
            "span",
            "",
            cls="ah-connector-connection-pin-label-node",
            bind="slot:connector-connection-pin-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connection-pin-line",
            "div",
            "",
            cls="ah-connector-connection-pin-line-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:connector-connection-pin-value",
            "span",
            "",
            cls="ah-connector-connection-pin-value-node",
            bind="slot:connector-connection-pin-value",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_collapsed_rail_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-collapsed-rail"
    nodes = [
        _slot("slot:conversation-collapsed-label", "conversation collapsed label", "CONVERSATION · 0"),
        _el(
            root_id,
            "aside",
            "",
            cls="ah-conversation-collapsed-rail-node",
            children=[
                "ui:grandmap:conversation-collapsed-chevron",
                "ui:grandmap:conversation-collapsed-label",
            ],
            action="conversation.rail.expand",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-collapsed-chevron",
            "span",
            "‹",
            cls="ah-conversation-collapsed-chevron-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-collapsed-label",
            "span",
            "",
            cls="ah-conversation-collapsed-label-node",
            bind="slot:conversation-collapsed-label",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_header_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-header"
    nodes = [
        _slot("slot:conversation-icon", "conversation icon", "AI"),
        _slot("slot:conversation-label", "conversation label", "CONVERSATION"),
        _slot("slot:conversation-count", "conversation message count", "0 msgs"),
        _slot("slot:conversation-title", "conversation title", "Conversation"),
        _slot("slot:conversation-subtitle", "conversation subtitle", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-header-node",
            children=[
                "ui:grandmap:conversation-header-meta",
                "ui:grandmap:conversation-header-title",
                "ui:grandmap:conversation-header-subtitle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-meta",
            "div",
            "",
            cls="ah-conversation-header-meta-node",
            children=[
                "ui:grandmap:conversation-header-collapse",
                "ui:grandmap:conversation-header-icon",
                "ui:grandmap:conversation-header-label",
                "ui:grandmap:conversation-header-spacer",
                "ui:grandmap:conversation-header-count",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-collapse",
            "button",
            "›",
            cls="ah-conversation-header-collapse-node",
            action="conversation.rail.collapse",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-icon",
            "span",
            "",
            cls="ah-conversation-header-icon-node",
            bind="slot:conversation-icon",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-label",
            "span",
            "",
            cls="ah-conversation-header-label-node",
            bind="slot:conversation-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-spacer",
            "div",
            "",
            cls="ah-conversation-header-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-count",
            "span",
            "",
            cls="ah-conversation-header-count-node",
            bind="slot:conversation-count",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-title",
            "div",
            "",
            cls="ah-conversation-header-title-node",
            bind="slot:conversation-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-header-subtitle",
            "div",
            "",
            cls="ah-conversation-header-subtitle-node",
            bind="slot:conversation-subtitle",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_rail_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-rail-shell"
    nodes = [
        _el(
            root_id,
            "aside",
            "",
            cls="ah-conversation-rail-shell-node",
            children=[
                "ui:grandmap:conversation-rail-minimap",
                "ui:grandmap:conversation-rail-header",
                "ui:grandmap:conversation-rail-scrollback",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-rail-minimap",
            "div",
            "",
            cls="ah-conversation-rail-minimap-node",
            render_slot="slot:conversation-rail-minimap",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-rail-header",
            "div",
            "",
            cls="ah-conversation-rail-header-mount-node",
            render_slot="slot:conversation-rail-header",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-rail-scrollback",
            "div",
            "",
            cls="ah-conversation-rail-scrollback-mount-node",
            render_slot="slot:conversation-rail-scrollback",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_day_divider_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-day-divider"
    nodes = [
        _slot("slot:conversation-day-label", "conversation day label", "TODAY"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-day-divider-node",
            children=[
                "ui:grandmap:conversation-day-line-start",
                "ui:grandmap:conversation-day-label",
                "ui:grandmap:conversation-day-line-end",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-day-line-start",
            "span",
            "",
            cls="ah-conversation-day-line-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-day-label",
            "span",
            "",
            cls="ah-conversation-day-label-node",
            bind="slot:conversation-day-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-day-line-end",
            "span",
            "",
            cls="ah-conversation-day-line-node",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_tool_trace_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-tool-trace"
    nodes = [
        _slot("slot:conversation-tool-trace-row", "tool trace row", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-tool-trace-node",
            children=[
                "ui:grandmap:conversation-tool-trace-title",
                "ui:grandmap:conversation-tool-trace-list",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-tool-trace-title",
            "div",
            "TOOL TRACE",
            cls="ah-conversation-tool-trace-title-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-tool-trace-list",
            "div",
            "",
            cls="ah-conversation-tool-trace-list-node",
            children=[],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-tool-trace-row",
            "div",
            "",
            cls="ah-conversation-tool-trace-row-node",
            bind="slot:conversation-tool-trace-row",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_turn_actions_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-turn-actions"
    nodes = [
        _slot("slot:conversation-turn-tokens", "conversation turn tokens", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-turn-actions-node",
            children=[
                "ui:grandmap:conversation-turn-regen",
                "ui:grandmap:conversation-turn-branch",
                "ui:grandmap:conversation-turn-edit",
                "ui:grandmap:conversation-turn-copy",
                "ui:grandmap:conversation-turn-spacer",
                "ui:grandmap:conversation-turn-tokens",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-regen",
            "button",
            "↻ regen",
            cls="ah-conversation-turn-action-node",
            action="conversation.turn.regen",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-branch",
            "button",
            "⎘ branch",
            cls="ah-conversation-turn-action-node",
            action="conversation.turn.branch",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-edit",
            "button",
            "✎ edit",
            cls="ah-conversation-turn-action-node",
            action="conversation.turn.edit",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-copy",
            "button",
            "⧉ copy",
            cls="ah-conversation-turn-action-node",
            action="conversation.turn.copy",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-spacer",
            "div",
            "",
            cls="ah-conversation-turn-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-tokens",
            "span",
            "",
            cls="ah-conversation-turn-tokens-node",
            bind="slot:conversation-turn-tokens",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_turn_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-turn"
    nodes = [
        _slot("slot:conversation-turn-role", "conversation turn role", "assistant"),
        _slot("slot:conversation-turn-avatar", "conversation turn avatar", "A"),
        _slot("slot:conversation-turn-name", "conversation turn name", "AI"),
        _slot("slot:conversation-turn-time", "conversation turn time", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-turn-node",
            children=[
                "ui:grandmap:conversation-turn-avatar",
                "ui:grandmap:conversation-turn-content",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-avatar",
            "div",
            "",
            cls="ah-conversation-turn-avatar-node",
            bind="slot:conversation-turn-avatar",
            state_bind="slot:conversation-turn-role",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-content",
            "div",
            "",
            cls="ah-conversation-turn-content-node",
            children=[
                "ui:grandmap:conversation-turn-meta",
                "ui:grandmap:conversation-turn-body",
                "ui:grandmap:conversation-turn-reasoning",
                "ui:grandmap:conversation-turn-actions-mount",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-meta",
            "div",
            "",
            cls="ah-conversation-turn-meta-node",
            children=[
                "ui:grandmap:conversation-turn-name",
                "ui:grandmap:conversation-turn-time",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-name",
            "span",
            "",
            cls="ah-conversation-turn-name-node",
            bind="slot:conversation-turn-name",
            state_bind="slot:conversation-turn-role",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-time",
            "span",
            "",
            cls="ah-conversation-turn-time-node",
            bind="slot:conversation-turn-time",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-body",
            "div",
            "",
            cls="ah-conversation-turn-body-node",
            render_slot="slot:conversation-turn-body",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-reasoning",
            "div",
            "",
            cls="ah-conversation-turn-reasoning-node",
            render_slot="slot:conversation-turn-reasoning",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-turn-actions-mount",
            "div",
            "",
            cls="ah-conversation-turn-actions-mount-node",
            render_slot="slot:conversation-turn-actions",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_reasoning_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-reasoning"
    nodes = [
        _slot("slot:conversation-reasoning-open", "conversation reasoning open", "false"),
        _slot("slot:conversation-reasoning-chevron", "conversation reasoning chevron", ">"),
        _slot("slot:conversation-reasoning-label", "conversation reasoning label", "reasoning"),
        _slot("slot:conversation-reasoning-count", "conversation reasoning count", "0 steps"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-reasoning-node",
            children=[
                "ui:grandmap:conversation-reasoning-toggle",
                "ui:grandmap:conversation-reasoning-panel",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-toggle",
            "button",
            "",
            cls="ah-conversation-reasoning-toggle-node",
            action="conversation.reasoning.toggle",
            state_bind="slot:conversation-reasoning-open",
            children=[
                "ui:grandmap:conversation-reasoning-chevron",
                "ui:grandmap:conversation-reasoning-label",
                "ui:grandmap:conversation-reasoning-count",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-chevron",
            "span",
            "",
            cls="ah-conversation-reasoning-chevron-node",
            bind="slot:conversation-reasoning-chevron",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-label",
            "span",
            "",
            cls="ah-conversation-reasoning-label-node",
            bind="slot:conversation-reasoning-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-count",
            "span",
            "",
            cls="ah-conversation-reasoning-count-node",
            bind="slot:conversation-reasoning-count",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-panel",
            "div",
            "",
            cls="ah-conversation-reasoning-panel-node",
            render_slot="slot:conversation-reasoning-steps",
            visible_when={"bind": "slot:conversation-reasoning-open", "value": "true"},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_reasoning_step_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-reasoning-step"
    nodes = [
        _slot("slot:conversation-reasoning-step-index", "conversation reasoning step index", "1."),
        _slot("slot:conversation-reasoning-step-text", "conversation reasoning step text", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-reasoning-step-node",
            children=[
                "ui:grandmap:conversation-reasoning-step-index",
                "ui:grandmap:conversation-reasoning-step-text",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-step-index",
            "span",
            "",
            cls="ah-conversation-reasoning-step-index-node",
            bind="slot:conversation-reasoning-step-index",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reasoning-step-text",
            "span",
            "",
            cls="ah-conversation-reasoning-step-text-node",
            bind="slot:conversation-reasoning-step-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_compact_expand_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-compact-expand"
    nodes = [
        _slot("slot:conversation-compact-expand-count", "conversation compact expand count", "0 earlier messages"),
        _slot("slot:conversation-compact-expand-action", "conversation compact expand action", "expand + search"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-conversation-compact-expand-node",
            action="conversation.compact.expand",
            children=[
                "ui:grandmap:conversation-compact-expand-icon",
                "ui:grandmap:conversation-compact-expand-count",
                "ui:grandmap:conversation-compact-expand-spacer",
                "ui:grandmap:conversation-compact-expand-action",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-expand-icon",
            "span",
            "?",
            cls="ah-conversation-compact-expand-icon-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-expand-count",
            "span",
            "",
            cls="ah-conversation-compact-expand-count-node",
            bind="slot:conversation-compact-expand-count",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-expand-spacer",
            "span",
            "",
            cls="ah-conversation-compact-expand-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-expand-action",
            "span",
            "",
            cls="ah-conversation-compact-expand-action-node",
            bind="slot:conversation-compact-expand-action",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_compact_turn_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-compact-turn"
    nodes = [
        _slot("slot:conversation-compact-turn-role", "conversation compact turn role", "assistant"),
        _slot("slot:conversation-compact-turn-avatar", "conversation compact turn avatar", "A"),
        _slot("slot:conversation-compact-turn-name", "conversation compact turn name", "AI"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-compact-turn-node",
            children=[
                "ui:grandmap:conversation-compact-turn-avatar",
                "ui:grandmap:conversation-compact-turn-content",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-turn-avatar",
            "div",
            "",
            cls="ah-conversation-compact-turn-avatar-node",
            bind="slot:conversation-compact-turn-avatar",
            state_bind="slot:conversation-compact-turn-role",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-turn-content",
            "div",
            "",
            cls="ah-conversation-compact-turn-content-node",
            children=[
                "ui:grandmap:conversation-compact-turn-name",
                "ui:grandmap:conversation-compact-turn-body",
                "ui:grandmap:conversation-compact-turn-reasoning",
                "ui:grandmap:conversation-compact-turn-route",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-turn-name",
            "div",
            "",
            cls="ah-conversation-compact-turn-name-node",
            bind="slot:conversation-compact-turn-name",
            visible_when={"bind": "slot:conversation-compact-turn-role", "value": "assistant"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-turn-body",
            "div",
            "",
            cls="ah-conversation-compact-turn-body-node",
            render_slot="slot:conversation-compact-turn-body",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-turn-reasoning",
            "div",
            "",
            cls="ah-conversation-compact-turn-reasoning-node",
            render_slot="slot:conversation-compact-turn-reasoning",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-compact-turn-route",
            "div",
            "",
            cls="ah-conversation-compact-turn-route-node",
            render_slot="slot:conversation-compact-turn-route",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_route_meta_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-route-meta"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-route-meta-node",
            render_slot="slot:conversation-route-meta-rows",
            test_id="route-meta",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _conversation_route_meta_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-route-meta-row"
    nodes = [
        _slot("slot:conversation-route-meta-row-text", "conversation route meta row text", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-route-meta-row-node",
            children=[
                "ui:grandmap:conversation-route-meta-row-arrow",
                "ui:grandmap:conversation-route-meta-row-text",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-route-meta-row-arrow",
            "span",
            "⇉",
            cls="ah-conversation-route-meta-row-arrow-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-route-meta-row-text",
            "span",
            "",
            cls="ah-conversation-route-meta-row-text-node",
            bind="slot:conversation-route-meta-row-text",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_node_scrollback_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-node-scrollback"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-node-scrollback-node ah-scroll",
            render_slot="slot:conversation-node-scrollback-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _conversation_search_empty_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-search-empty"
    nodes = [
        _slot("slot:conversation-search-empty-query", "conversation search empty query", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-search-empty-node",
            children=[
                "ui:grandmap:conversation-search-empty-prefix",
                "ui:grandmap:conversation-search-empty-query",
                "ui:grandmap:conversation-search-empty-suffix",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-empty-prefix",
            "span",
            "No matches for \"",
            cls="ah-conversation-search-empty-prefix-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-empty-query",
            "span",
            "",
            cls="ah-conversation-search-empty-query-node",
            bind="slot:conversation-search-empty-query",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-empty-suffix",
            "span",
            "\".",
            cls="ah-conversation-search-empty-suffix-node",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_ai_body_expanded_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-ai-body-expanded"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-ai-body-expanded-node",
            children=[
                "ui:grandmap:conversation-ai-body-expanded-search",
                "ui:grandmap:conversation-ai-body-expanded-scrollback",
                "ui:grandmap:conversation-ai-body-expanded-reply",
            ],
            style={"marginTop": 9, "display": "flex", "flexDirection": "column", "gap": 7},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-ai-body-expanded-search",
            "div",
            "",
            cls="ah-conversation-ai-body-expanded-search-node",
            render_slot="slot:conversation-ai-body-search",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-ai-body-expanded-scrollback",
            "div",
            "",
            cls="ah-conversation-ai-body-expanded-scrollback-node",
            render_slot="slot:conversation-ai-body-scrollback",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-ai-body-expanded-reply",
            "div",
            "",
            cls="ah-conversation-ai-body-expanded-reply-node",
            render_slot="slot:conversation-ai-body-reply",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_ai_body_compact_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-ai-body-compact"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-ai-body-compact-node",
            children=[
                "ui:grandmap:conversation-ai-body-compact-expand",
                "ui:grandmap:conversation-ai-body-compact-turns",
            ],
            style={"marginTop": 9, "display": "flex", "flexDirection": "column", "gap": 9},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-ai-body-compact-expand",
            "div",
            "",
            cls="ah-conversation-ai-body-compact-expand-node",
            render_slot="slot:conversation-ai-body-compact-expand",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-ai-body-compact-turns",
            "div",
            "",
            cls="ah-conversation-ai-body-compact-turns-node",
            render_slot="slot:conversation-ai-body-compact-turns",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_search_bar_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-search-bar"
    nodes = [
        _slot("slot:conversation-search-query", "conversation search query", ""),
        _slot("slot:conversation-search-count", "conversation search count", "0/0"),
        _slot("slot:conversation-search-clear-hidden", "conversation search clear hidden", "true"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-search-bar-node",
            children=[
                "ui:grandmap:conversation-search-icon",
                "ui:grandmap:conversation-search-input",
                "ui:grandmap:conversation-search-count",
                "ui:grandmap:conversation-search-clear",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-icon",
            "svg",
            "",
            cls="ah-conversation-search-icon-node",
            children=[
                "ui:grandmap:conversation-search-icon-circle",
                "ui:grandmap:conversation-search-icon-path",
            ],
            data_attrs={
                "width": "10",
                "height": "10",
                "viewBox": "0 0 24 24",
                "fill": "none",
                "stroke": "currentColor",
                "strokeWidth": "2",
            },
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-icon-circle",
            "circle",
            "",
            data_attrs={"cx": "11", "cy": "11", "r": "7"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-icon-path",
            "path",
            "",
            data_attrs={"d": "M21 21l-4.3-4.3"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-input",
            "input",
            "",
            cls="ah-conversation-search-input-node",
            bind="slot:conversation-search-query",
            action="conversation.search.update",
            placeholder="Search this conversation...",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-count",
            "span",
            "",
            cls="ah-conversation-search-count-node",
            bind="slot:conversation-search-count",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-search-clear",
            "button",
            "x",
            cls="ah-conversation-search-clear-node",
            action="conversation.search.clear",
            hidden_bind="slot:conversation-search-clear-hidden",
            hidden_value="true",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_reply_composer_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-reply-composer"
    nodes = [
        _slot("slot:conversation-reply-value", "conversation reply value", ""),
        _slot("slot:conversation-reply-send-disabled", "conversation reply send disabled", "true"),
        _slot("slot:conversation-reply-send-label", "conversation reply send label", "Send enter"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-reply-composer-node",
            children=[
                "ui:grandmap:conversation-reply-slash",
                "ui:grandmap:conversation-reply-input",
                "ui:grandmap:conversation-reply-send",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reply-slash",
            "span",
            "/",
            cls="ah-conversation-reply-slash-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reply-input",
            "textarea",
            "",
            cls="ah-conversation-reply-input-node",
            bind="slot:conversation-reply-value",
            action="conversation.reply.update",
            submit_action="conversation.reply.submit",
            placeholder="Reply...  (Shift+Enter = new line)",
            rows=1,
            auto_grow=True,
            auto_grow_max=140,
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-reply-send",
            "button",
            "",
            cls="ah-conversation-reply-send-node",
            bind="slot:conversation-reply-send-label",
            action="conversation.reply.submit",
            disabled_bind="slot:conversation-reply-send-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_expanded_turn_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-expanded-turn"
    nodes = [
        _slot("slot:conversation-expanded-turn-role", "conversation expanded turn role", "assistant"),
        _slot("slot:conversation-expanded-turn-avatar", "conversation expanded turn avatar", "A"),
        _slot("slot:conversation-expanded-turn-name", "conversation expanded turn name", "AI"),
        _slot("slot:conversation-expanded-turn-time", "conversation expanded turn time", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-expanded-turn-node",
            children=[
                "ui:grandmap:conversation-expanded-turn-avatar",
                "ui:grandmap:conversation-expanded-turn-content",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-expanded-turn-avatar",
            "div",
            "",
            cls="ah-conversation-expanded-turn-avatar-node",
            bind="slot:conversation-expanded-turn-avatar",
            state_bind="slot:conversation-expanded-turn-role",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-expanded-turn-content",
            "div",
            "",
            cls="ah-conversation-expanded-turn-content-node",
            children=[
                "ui:grandmap:conversation-expanded-turn-meta",
                "ui:grandmap:conversation-expanded-turn-body",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-expanded-turn-meta",
            "div",
            "",
            cls="ah-conversation-expanded-turn-meta-node",
            children=[
                "ui:grandmap:conversation-expanded-turn-name",
                "ui:grandmap:conversation-expanded-turn-time",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-expanded-turn-name",
            "span",
            "",
            cls="ah-conversation-expanded-turn-name-node",
            bind="slot:conversation-expanded-turn-name",
            state_bind="slot:conversation-expanded-turn-role",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-expanded-turn-time",
            "span",
            "",
            cls="ah-conversation-expanded-turn-time-node",
            bind="slot:conversation-expanded-turn-time",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-expanded-turn-body",
            "div",
            "",
            cls="ah-conversation-expanded-turn-body-node",
            render_slot="slot:conversation-expanded-turn-body",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _rail_minimap_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:rail-minimap"
    nodes = [
        _slot("slot:rail-minimap-visible", "rail minimap visible", "true"),
        _slot("slot:rail-minimap-ready", "rail minimap ready", "false"),
        _slot("slot:rail-minimap-title", "rail minimap title", "MAP - CLICK TO JUMP"),
        _slot("slot:rail-minimap-empty", "rail minimap empty", "OPEN SESSION FOR MAP"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-rail-minimap-root-node",
            visible_when={"bind": "slot:rail-minimap-visible", "value": "true"},
            children=[
                "ui:grandmap:rail-minimap-empty",
                "ui:grandmap:rail-minimap-live",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-minimap-empty",
            "div",
            "",
            cls="ah-rail-minimap-empty-node",
            bind="slot:rail-minimap-empty",
            visible_when={"bind": "slot:rail-minimap-ready", "value": "false"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-minimap-live",
            "div",
            "",
            cls="ah-rail-minimap-live-node",
            visible_when={"bind": "slot:rail-minimap-ready", "value": "true"},
            children=[
                "ui:grandmap:rail-minimap-title",
                "ui:grandmap:rail-minimap-board",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-minimap-title",
            "div",
            "",
            cls="ah-rail-minimap-title-node",
            bind="slot:rail-minimap-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-minimap-board",
            "div",
            "",
            cls="ah-rail-minimap-board-node",
            action="rail-minimap.jump",
            test_id="rail-minimap-board",
            render_slot="slot:rail-minimap-nodes",
            children=["ui:grandmap:rail-minimap-viewport"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-minimap-viewport",
            "div",
            "",
            cls="ah-rail-minimap-viewport-node",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _rail_minimap_node_rect_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:rail-minimap-node-rect"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-rail-minimap-node-rect-node",
            data_attrs={"aria-hidden": "true"},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _conversation_scrollback_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-scrollback"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-scrollback-node ah-scroll",
            test_id="conversation-scrollback",
            render_slot="slot:conversation-scrollback-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _conversation_fabricated_tool_warning_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-fabricated-tool-warning"
    nodes = [
        _slot("slot:conversation-fabricated-tool-title", "fabricated tool title", "● FABRICATED TOOL CALL — IGNORED"),
        _slot(
            "slot:conversation-fabricated-tool-body",
            "fabricated tool body",
            "The AI tried to fake a tool call and invent a result. It cannot touch a host from chat. To do this for real, add the matching connector-op node from the library and run it.",
        ),
        _slot("slot:conversation-fabricated-tool-clean", "fabricated tool cleaned text", ""),
        _slot("slot:conversation-fabricated-tool-clean-hidden", "fabricated tool clean hidden", "true"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-fabricated-tool-warning-node",
            children=[
                "ui:grandmap:conversation-fabricated-tool-title",
                "ui:grandmap:conversation-fabricated-tool-body",
                "ui:grandmap:conversation-fabricated-tool-clean",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-fabricated-tool-title",
            "div",
            "",
            cls="ah-conversation-fabricated-tool-title-node",
            bind="slot:conversation-fabricated-tool-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-fabricated-tool-body",
            "div",
            "",
            cls="ah-conversation-fabricated-tool-body-node",
            bind="slot:conversation-fabricated-tool-body",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-fabricated-tool-clean",
            "div",
            "",
            cls="ah-conversation-fabricated-tool-clean-node",
            bind="slot:conversation-fabricated-tool-clean",
            hidden_bind="slot:conversation-fabricated-tool-clean-hidden",
            hidden_value="true",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_code_block_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-code-block"
    nodes = [
        _slot("slot:conversation-code-language", "code language", "code"),
        _slot("slot:conversation-code-lines", "code line count", "0 lines"),
        _slot("slot:conversation-code-toggle", "code toggle label", "collapse"),
        _slot("slot:conversation-code-toggle-hidden", "code toggle hidden", "true"),
        _slot("slot:conversation-code-state", "code block state", "open"),
        _slot("slot:conversation-code-body", "code body", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-code-block-node",
            children=[
                "ui:grandmap:conversation-code-header",
                "ui:grandmap:conversation-code-body",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-header",
            "div",
            "",
            cls="ah-conversation-code-header-node",
            children=[
                "ui:grandmap:conversation-code-language",
                "ui:grandmap:conversation-code-lines",
                "ui:grandmap:conversation-code-spacer",
                "ui:grandmap:conversation-code-copy",
                "ui:grandmap:conversation-code-toggle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-language",
            "span",
            "",
            cls="ah-conversation-code-language-node",
            bind="slot:conversation-code-language",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-lines",
            "span",
            "",
            cls="ah-conversation-code-lines-node",
            bind="slot:conversation-code-lines",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-spacer",
            "div",
            "",
            cls="ah-conversation-code-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-copy",
            "button",
            "copy",
            cls="ah-conversation-code-action-node",
            action="conversation.code.copy",
            args={"block_id": ""},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-toggle",
            "button",
            "",
            cls="ah-conversation-code-action-node ah-conversation-code-toggle-node",
            bind="slot:conversation-code-toggle",
            action="conversation.code.toggle",
            args={"block_id": ""},
            hidden_bind="slot:conversation-code-toggle-hidden",
            hidden_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-code-body",
            "pre",
            "",
            cls="ah-conversation-code-body-node",
            bind="slot:conversation-code-body",
            state_bind="slot:conversation-code-state",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _conversation_clipped_text_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-clipped-text"
    nodes = [
        _slot("slot:conversation-clipped-text-value", "conversation clipped text value", ""),
        _slot("slot:conversation-clipped-text-streaming", "conversation clipped text streaming", "false"),
        _slot("slot:conversation-clipped-text-long", "conversation clipped text long", "false"),
        _slot("slot:conversation-clipped-text-toggle-label", "conversation clipped text toggle label", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-conversation-clipped-text-node",
            children=[
                "ui:grandmap:conversation-clipped-text-value",
                "ui:grandmap:conversation-clipped-text-caret",
                "ui:grandmap:conversation-clipped-text-toggle",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-clipped-text-value",
            "span",
            "",
            cls="ah-conversation-clipped-text-value-node",
            bind="slot:conversation-clipped-text-value",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-clipped-text-caret",
            "span",
            "",
            cls="ah-conversation-clipped-text-caret-node",
            visible_when={"bind": "slot:conversation-clipped-text-streaming", "value": "true"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-clipped-text-toggle",
            "button",
            "",
            cls="ah-conversation-clipped-text-toggle-node",
            bind="slot:conversation-clipped-text-toggle-label",
            action="conversation.clipped-text.toggle",
            visible_when={"bind": "slot:conversation-clipped-text-long", "value": "true"},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _conversation_text_span_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-text-span"
    nodes = [
        _slot("slot:conversation-text-body", "conversation text body", ""),
        _el(
            root_id,
            "span",
            "",
            cls="ah-conversation-text-span-node",
            bind="slot:conversation-text-body",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _conversation_thinking_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:conversation-thinking"
    nodes = [
        _slot("slot:conversation-thinking-label", "thinking label", "thinking"),
        _el(
            root_id,
            "span",
            "",
            cls="ah-conversation-thinking-node",
            children=[
                "ui:grandmap:conversation-thinking-dot-0",
                "ui:grandmap:conversation-thinking-dot-1",
                "ui:grandmap:conversation-thinking-dot-2",
                "ui:grandmap:conversation-thinking-label",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-thinking-dot-0",
            "span",
            "",
            cls="ah-conversation-thinking-dot-node ah-conversation-thinking-dot-0-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-thinking-dot-1",
            "span",
            "",
            cls="ah-conversation-thinking-dot-node ah-conversation-thinking-dot-1-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-thinking-dot-2",
            "span",
            "",
            cls="ah-conversation-thinking-dot-node ah-conversation-thinking-dot-2-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:conversation-thinking-label",
            "span",
            "",
            cls="ah-conversation-thinking-label-node",
            bind="slot:conversation-thinking-label",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _ai_plan_section_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_node_card"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:ai-plan-section"
    metric_ids = [
        "ui:grandmap:ai-plan-metric-plan-id",
        "ui:grandmap:ai-plan-metric-calls",
        "ui:grandmap:ai-plan-metric-model",
        "ui:grandmap:ai-plan-metric-source",
    ]
    decision_ids = [
        "ui:grandmap:ai-plan-decision-1",
        "ui:grandmap:ai-plan-decision-2",
        "ui:grandmap:ai-plan-decision-3",
    ]
    nodes = [
        _slot("slot:ai-plan-state", "ai plan state", "loading"),
        _slot("slot:ai-plan-status", "ai plan status", "loading"),
        _slot("slot:ai-plan-loading", "ai plan loading text", "loading..."),
        _slot("slot:ai-plan-empty", "ai plan empty text", ""),
        _slot("slot:ai-plan-id", "ai plan id", ""),
        _slot("slot:ai-plan-calls", "ai plan calls", ""),
        _slot("slot:ai-plan-model", "ai plan model", ""),
        _slot("slot:ai-plan-source", "ai plan source", ""),
        _slot("slot:ai-plan-decisions-visible", "ai plan decisions visible", "false"),
        _slot("slot:ai-plan-decision-1", "ai plan decision 1", ""),
        _slot("slot:ai-plan-decision-1-visible", "ai plan decision 1 visible", "false"),
        _slot("slot:ai-plan-decision-2", "ai plan decision 2", ""),
        _slot("slot:ai-plan-decision-2-visible", "ai plan decision 2 visible", "false"),
        _slot("slot:ai-plan-decision-3", "ai plan decision 3", ""),
        _slot("slot:ai-plan-decision-3-visible", "ai plan decision 3 visible", "false"),
        _slot("slot:ai-plan-replay-disabled", "ai plan replay disabled", "true"),
        _slot("slot:ai-plan-open-disabled", "ai plan open disabled", "true"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-ai-plan-section-node",
            children=[
                "ui:grandmap:ai-plan-heading",
                "ui:grandmap:ai-plan-loading",
                "ui:grandmap:ai-plan-empty",
                "ui:grandmap:ai-plan-metrics",
                "ui:grandmap:ai-plan-decisions-heading",
                "ui:grandmap:ai-plan-decisions",
                "ui:grandmap:ai-plan-actions",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-heading",
            "div",
            "PLAN ",
            cls="ah-ai-plan-heading-node",
            bind="slot:ai-plan-status",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-loading",
            "div",
            "",
            cls="ah-ai-plan-loading-node",
            bind="slot:ai-plan-loading",
            visible_when={"bind": "slot:ai-plan-state", "values": ["loading"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-empty",
            "div",
            "",
            cls="ah-ai-plan-empty-node",
            bind="slot:ai-plan-empty",
            visible_when={"bind": "slot:ai-plan-state", "values": ["empty"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-metrics",
            "div",
            "",
            cls="ah-ai-plan-metrics-node",
            visible_when={"bind": "slot:ai-plan-state", "values": ["ready"]},
            children=metric_ids,
            source_node=source_node,
        ),
        _ai_plan_metric_node(
            "ui:grandmap:ai-plan-metric-plan-id",
            "Plan id",
            "slot:ai-plan-id",
            source_node,
        ),
        _ai_plan_metric_node(
            "ui:grandmap:ai-plan-metric-calls",
            "Tool calls - ok / total",
            "slot:ai-plan-calls",
            source_node,
        ),
        _ai_plan_metric_node(
            "ui:grandmap:ai-plan-metric-model",
            "Model",
            "slot:ai-plan-model",
            source_node,
        ),
        _ai_plan_metric_node(
            "ui:grandmap:ai-plan-metric-source",
            "Source",
            "slot:ai-plan-source",
            source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-decisions-heading",
            "div",
            "DECISIONS",
            cls="ah-ai-plan-decisions-heading-node",
            visible_when={"bind": "slot:ai-plan-decisions-visible", "values": ["true"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-decisions",
            "div",
            "",
            cls="ah-ai-plan-decisions-node",
            visible_when={"bind": "slot:ai-plan-decisions-visible", "values": ["true"]},
            children=decision_ids,
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-decision-1",
            "span",
            "",
            cls="ah-ai-plan-decision-node",
            bind="slot:ai-plan-decision-1",
            visible_when={"bind": "slot:ai-plan-decision-1-visible", "values": ["true"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-decision-2",
            "span",
            "",
            cls="ah-ai-plan-decision-node",
            bind="slot:ai-plan-decision-2",
            visible_when={"bind": "slot:ai-plan-decision-2-visible", "values": ["true"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-decision-3",
            "span",
            "",
            cls="ah-ai-plan-decision-node",
            bind="slot:ai-plan-decision-3",
            visible_when={"bind": "slot:ai-plan-decision-3-visible", "values": ["true"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-actions",
            "div",
            "",
            cls="ah-ai-plan-actions-node",
            visible_when={"bind": "slot:ai-plan-state", "values": ["ready"]},
            children=[
                "ui:grandmap:ai-plan-replay",
                "ui:grandmap:ai-plan-open",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-replay",
            "button",
            "Replay from cache",
            cls="ah-ai-plan-action-node ah-ai-plan-replay-node",
            action="ai.plan.replay",
            disabled_bind="slot:ai-plan-replay-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-plan-open",
            "button",
            "Open full table",
            cls="ah-ai-plan-action-node ah-ai-plan-open-node",
            action="ai.plan.open_file",
            disabled_bind="slot:ai-plan-open-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _ai_plan_metric_node(
    node_id: str,
    label: str,
    value_slot: str,
    source_node: dict[str, Any],
) -> dict[str, Any]:
    return _el(
        node_id,
        "div",
        label + ": ",
        cls="ah-ai-plan-metric-node",
        bind=value_slot,
        source_node=source_node,
    )


def _node_palette_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "ui": ["ui_sidebar_rail", "ui_command_palette"],
        "nodes": ["nodes_library_search"],
        "brain": ["brain_skills"],
        "connectors": ["connectors_panel"],
    }
    try:
        domain_nodes = {
            key: _load_domain_nodes(path, key)
            for key in required
        }
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }

    source_nodes: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domain_nodes[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                source_nodes[node_id] = node
    source_ids = [
        "ui_sidebar_rail",
        "ui_command_palette",
        "nodes_library_search",
        "brain_skills",
        "connectors_panel",
    ]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map node palette source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:node-palette-shell"
    slot_defs = [
        ("styles", "slot:node-palette-shell-styles", "ui_command_palette"),
        ("header", "slot:node-palette-shell-header", "ui_sidebar_rail"),
        ("menu", "slot:node-palette-shell-menu", "ui_sidebar_rail"),
        ("search", "slot:node-palette-shell-search", "nodes_library_search"),
        ("list", "slot:node-palette-shell-list", "nodes_library_search"),
        ("footer", "slot:node-palette-shell-footer", "ui_sidebar_rail"),
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-shell-node",
            children=[f"ui:grandmap:node-palette-shell-{key}" for key, _slot, _src in slot_defs],
            source_node=source_nodes["ui_sidebar_rail"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:node-palette-shell-{key}",
            "div",
            "",
            cls=f"ah-node-palette-shell-{key}-slot-node",
            render_slot=slot,
            source_node=source_nodes[source_id],
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _wire_promote_palette_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "ui": ["ui_command_palette"],
        "nodes": ["nodes_library_search"],
    }
    try:
        domains = {key: _load_domain_nodes(path, key) for key in required}
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }

    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domains[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                sources[node_id] = node
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map wire-promote source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:wire-promote-palette"
    nodes = [
        _slot("slot:wire-promote-title", "wire promote title", "ADD NODE"),
        _slot("slot:wire-promote-hint", "wire promote hint", "enter pick - esc close"),
        _slot("slot:wire-promote-query", "wire promote query", ""),
        _slot("slot:wire-promote-empty-message", "wire promote empty message", "No matches - try a different query."),
        _slot("slot:wire-promote-has-results", "wire promote has results", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-wire-promote-backdrop-node",
            action="wire-promote.close",
            children=["ui:grandmap:wire-promote-panel"],
            source_node=sources["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:wire-promote-panel",
            "div",
            "",
            cls="ah-wire-promote-panel-node",
            role="dialog",
            action="wire-promote.noop",
            data_attrs={"data-no-pan": "true", "aria-label": "Add node"},
            children=[
                "ui:grandmap:wire-promote-header",
                "ui:grandmap:wire-promote-search-wrap",
                "ui:grandmap:wire-promote-results",
                "ui:grandmap:wire-promote-footer",
            ],
            source_node=sources["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:wire-promote-header",
            "div",
            "",
            cls="ah-wire-promote-header-node",
            children=[
                "ui:grandmap:wire-promote-title",
                "ui:grandmap:wire-promote-spacer",
                "ui:grandmap:wire-promote-hint",
            ],
            source_node=sources["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:wire-promote-title",
            "span",
            "",
            cls="ah-wire-promote-title-node",
            bind="slot:wire-promote-title",
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-spacer",
            "div",
            "",
            cls="ah-wire-promote-spacer-node",
            source_node=sources["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:wire-promote-hint",
            "span",
            "",
            cls="ah-wire-promote-hint-node",
            bind="slot:wire-promote-hint",
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-search-wrap",
            "div",
            "",
            cls="ah-wire-promote-search-wrap-node",
            children=["ui:grandmap:wire-promote-query-input"],
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-query-input",
            "input",
            "",
            cls="ah-wire-promote-input-node",
            bind="slot:wire-promote-query",
            action="wire-promote.query.update",
            input_type="text",
            submit_action="wire-promote.submit",
            placeholder='add node... (~note, "text", =expr, 0<5<10)',
            test_id="wire-promote-query",
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-results",
            "div",
            "",
            cls="ah-wire-promote-results-node ah-scroll",
            children=[
                "ui:grandmap:wire-promote-empty",
                "ui:grandmap:wire-promote-result-slot",
            ],
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-empty",
            "div",
            "",
            cls="ah-wire-promote-empty-node",
            bind="slot:wire-promote-empty-message",
            hidden_bind="slot:wire-promote-has-results",
            hidden_value="true",
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-result-slot",
            "div",
            "",
            cls="ah-wire-promote-result-slot-node",
            render_slot="slot:wire-promote-results",
            source_node=sources["nodes_library_search"],
        ),
        _el(
            "ui:grandmap:wire-promote-footer",
            "div",
            'prefixes: ~note - "text" - =expr - 0<5<10',
            cls="ah-wire-promote-footer-node",
            source_node=sources["nodes_library_search"],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["ui_command_palette", "nodes_library_search"],
    }


def _wire_promote_result_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        nodes_domain = _load_domain_nodes(path, "nodes")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "nodes_library_search"
    if source_id not in nodes_domain:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map wire-promote source node: " + source_id,
        }

    source_node = nodes_domain[source_id]
    root_id = "ui:grandmap:wire-promote-result-row"
    nodes = [
        _slot("slot:wire-promote-result-title", "result title", "Node"),
        _slot("slot:wire-promote-result-sub", "result subtitle", ""),
        _slot("slot:wire-promote-result-cat", "result category", "node"),
        _slot("slot:wire-promote-result-active", "result active", "false"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-wire-promote-result-node",
            action="wire-promote.result.pick",
            active_bind="slot:wire-promote-result-active",
            active_value="true",
            children=[
                "ui:grandmap:wire-promote-result-dot",
                "ui:grandmap:wire-promote-result-copy",
                "ui:grandmap:wire-promote-result-cat",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:wire-promote-result-dot",
            "span",
            "",
            cls="ah-wire-promote-result-dot-node",
            state_bind="slot:wire-promote-result-cat",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:wire-promote-result-copy",
            "span",
            "",
            cls="ah-wire-promote-result-copy-node",
            children=[
                "ui:grandmap:wire-promote-result-title",
                "ui:grandmap:wire-promote-result-sub",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:wire-promote-result-title",
            "span",
            "",
            cls="ah-wire-promote-result-title-node",
            bind="slot:wire-promote-result-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:wire-promote-result-sub",
            "span",
            "",
            cls="ah-wire-promote-result-sub-node",
            bind="slot:wire-promote-result-sub",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:wire-promote-result-cat",
            "span",
            "",
            cls="ah-wire-promote-result-cat-node",
            bind="slot:wire-promote-result-cat",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _broken_wire_dialog_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "ui": ["ui_modal_system"],
        "canvas": ["canvas_wire_layer"],
    }
    try:
        domains = {key: _load_domain_nodes(path, key) for key in required}
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domains[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                sources[node_id] = node
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map broken-wire source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:broken-wire-dialog"
    nodes = [
        _slot("slot:broken-wire-node-title", "broken wire node title", ""),
        _slot("slot:broken-wire-count-label", "broken wire count label", "breaks 0 wires"),
        _slot("slot:broken-wire-adapter-label", "broken wire adapter label", "library.suggest_swaps - auto-bridge first broken pair"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-broken-wire-backdrop-node",
            action="broken-wire.close",
            data_attrs={
                "data-no-pan": "true",
                "data-testid": "broken-wire-dialog-backdrop",
            },
            children=["ui:grandmap:broken-wire-panel"],
            source_node=sources["ui_modal_system"],
        ),
        _el(
            "ui:grandmap:broken-wire-panel",
            "div",
            "",
            cls="ah-broken-wire-panel-node",
            role="dialog",
            action="broken-wire.noop",
            data_attrs={
                "data-testid": "broken-wire-dialog",
                "aria-modal": "true",
                "aria-label": "Broken wires",
            },
            children=[
                "ui:grandmap:broken-wire-header",
                "ui:grandmap:broken-wire-body",
            ],
            source_node=sources["ui_modal_system"],
        ),
        _el(
            "ui:grandmap:broken-wire-header",
            "div",
            "",
            cls="ah-broken-wire-header-node",
            children=[
                "ui:grandmap:broken-wire-status-dot",
                "ui:grandmap:broken-wire-title",
                "ui:grandmap:broken-wire-close",
            ],
            source_node=sources["canvas_wire_layer"],
        ),
        _el("ui:grandmap:broken-wire-status-dot", "span", "", cls="ah-broken-wire-status-dot-node", source_node=sources["canvas_wire_layer"]),
        _el(
            "ui:grandmap:broken-wire-title",
            "span",
            "Deleting ",
            cls="ah-broken-wire-title-node",
            children=[
                "ui:grandmap:broken-wire-title-node-name",
                "ui:grandmap:broken-wire-title-count",
            ],
            source_node=sources["canvas_wire_layer"],
        ),
        _el("ui:grandmap:broken-wire-title-node-name", "code", "", cls="ah-broken-wire-node-name-node", bind="slot:broken-wire-node-title", source_node=sources["canvas_wire_layer"]),
        _el("ui:grandmap:broken-wire-title-count", "span", " ", cls="ah-broken-wire-count-node", bind="slot:broken-wire-count-label", source_node=sources["canvas_wire_layer"]),
        _el("ui:grandmap:broken-wire-close", "button", "x", cls="ah-broken-wire-close-node", action="broken-wire.cancel", data_attrs={"aria-label": "close"}, source_node=sources["ui_modal_system"]),
        _el(
            "ui:grandmap:broken-wire-body",
            "div",
            "",
            cls="ah-broken-wire-body-node",
            children=[
                "ui:grandmap:broken-wire-explain",
                "ui:grandmap:broken-wire-list",
                "ui:grandmap:broken-wire-actions",
            ],
            source_node=sources["canvas_wire_layer"],
        ),
        _el("ui:grandmap:broken-wire-explain", "div", "Type mismatch - upstream port cannot feed downstream port directly.", cls="ah-broken-wire-explain-node", source_node=sources["canvas_wire_layer"]),
        _el("ui:grandmap:broken-wire-list", "div", "", cls="ah-broken-wire-list-node", render_slot="slot:broken-wire-rows", source_node=sources["canvas_wire_layer"]),
        _el(
            "ui:grandmap:broken-wire-actions",
            "div",
            "",
            cls="ah-broken-wire-actions-node",
            children=[
                "ui:grandmap:broken-wire-insert-adapter",
                "ui:grandmap:broken-wire-cancel",
                "ui:grandmap:broken-wire-delete",
            ],
            source_node=sources["ui_modal_system"],
        ),
        _broken_wire_action_node(
            "ui:grandmap:broken-wire-insert-adapter",
            "Insert adapter",
            "slot:broken-wire-adapter-label",
            "broken-wire.insert-adapter",
            "primary",
            sources["ui_modal_system"],
        ),
        _broken_wire_action_node(
            "ui:grandmap:broken-wire-cancel",
            "Restore node",
            "cancel delete",
            "broken-wire.cancel",
            "secondary",
            sources["ui_modal_system"],
        ),
        _broken_wire_action_node(
            "ui:grandmap:broken-wire-delete",
            "Delete anyway, leave dangling",
            "cook will surface upstream_error on next run",
            "broken-wire.delete-anyway",
            "danger",
            sources["ui_modal_system"],
        ),
    ]
    expanded_nodes: list[dict[str, Any]] = []
    for node in nodes:
        child_nodes = node.pop("_children", [])
        expanded_nodes.append(node)
        expanded_nodes.extend(child_nodes)
    nodes = expanded_nodes
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": ["ui_modal_system", "canvas_wire_layer"],
    }


def _broken_wire_action_node(
    node_id: str,
    title: str,
    subtitle: str,
    action: str,
    tone: str,
    source_node: dict[str, Any],
) -> dict[str, Any]:
    subtitle_id = f"{node_id}-sub"
    title_id = f"{node_id}-title"
    bind = subtitle if subtitle.startswith("slot:") else ""
    return _el(
        node_id,
        "button",
        "",
        cls=f"ah-broken-wire-action-node ah-broken-wire-action-{tone}-node",
        action=action,
        children=[title_id, subtitle_id],
        source_node=source_node,
    ) | {"_children": [
        _el(title_id, "div", title, cls="ah-broken-wire-action-title-node", source_node=source_node),
        _el(subtitle_id, "div", "" if bind else subtitle, cls="ah-broken-wire-action-sub-node", bind=bind, source_node=source_node),
    ]}


def _broken_wire_row_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        canvas_nodes = _load_domain_nodes(path, "canvas")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "canvas_wire_layer"
    if source_id not in canvas_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map broken-wire source node: " + source_id,
        }
    source_node = canvas_nodes[source_id]
    root_id = "ui:grandmap:broken-wire-row"
    nodes = [
        _slot("slot:broken-wire-row-src", "broken wire source", ""),
        _slot("slot:broken-wire-row-src-type", "broken wire source type", ""),
        _slot("slot:broken-wire-row-dst", "broken wire destination", ""),
        _slot("slot:broken-wire-row-dst-type", "broken wire destination type", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-broken-wire-row-node",
            children=[
                "ui:grandmap:broken-wire-row-src",
                "ui:grandmap:broken-wire-row-src-type",
                "ui:grandmap:broken-wire-row-arrow",
                "ui:grandmap:broken-wire-row-dst",
                "ui:grandmap:broken-wire-row-dst-type",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:broken-wire-row-src", "span", "", cls="ah-broken-wire-row-src-node", bind="slot:broken-wire-row-src", source_node=source_node),
        _el("ui:grandmap:broken-wire-row-src-type", "span", "", cls="ah-broken-wire-row-type-node", bind="slot:broken-wire-row-src-type", source_node=source_node),
        _el("ui:grandmap:broken-wire-row-arrow", "span", "->", cls="ah-broken-wire-row-arrow-node", source_node=source_node),
        _el("ui:grandmap:broken-wire-row-dst", "span", "", cls="ah-broken-wire-row-dst-node", bind="slot:broken-wire-row-dst", source_node=source_node),
        _el("ui:grandmap:broken-wire-row-dst-type", "span", "", cls="ah-broken-wire-row-type-node", bind="slot:broken-wire-row-dst-type", source_node=source_node),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_palette_list_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        nodes_domain = _load_domain_nodes(path, "nodes")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "nodes_library_search"
    if source_id not in nodes_domain:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map node palette source node: " + source_id,
        }

    root_id = "ui:grandmap:node-palette-list"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-list-node ah-scroll",
            render_slot="slot:node-palette-list-content",
            test_id="node-palette-list",
            source_node=nodes_domain[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_palette_group_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        nodes_domain = _load_domain_nodes(path, "nodes")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "nodes_library_search"
    if source_id not in nodes_domain:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map node palette source node: " + source_id,
        }

    source_node = nodes_domain[source_id]
    root_id = "ui:grandmap:node-palette-group"
    nodes = [
        _slot("slot:nodes-palette-group-title", "palette group title", "GROUP"),
        _slot("slot:nodes-palette-group-count", "palette group count", "0"),
        _slot("slot:nodes-palette-group-kind", "palette group kind", "group"),
        _slot("slot:nodes-palette-group-open", "palette group open", "true"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-group-node",
            state_bind="slot:nodes-palette-group-kind",
            children=[
                "ui:grandmap:node-palette-group-header",
                "ui:grandmap:node-palette-group-body",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-group-header",
            "div",
            "",
            cls="ah-node-palette-group-header-slot-node",
            render_slot="slot:nodes-palette-group-header",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-group-body",
            "div",
            "",
            cls="ah-node-palette-group-body-node",
            render_slot="slot:nodes-palette-group-content",
            hidden_bind="slot:nodes-palette-group-open",
            hidden_value="false",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _node_palette_context_menu_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map node palette source node: " + source_id,
        }

    root_id = "ui:grandmap:node-palette-context-menu"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-context-menu-node",
            render_slot="slot:node-palette-context-menu-content",
            test_id="node-palette-context-menu",
            source_node=ui_nodes[source_id],
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _node_palette_header_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["ui_sidebar_rail", "ui_command_palette"]
    missing = [node_id for node_id in source_ids if node_id not in ui_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI nodes: " + ", ".join(missing),
        }
    root_id = "ui:grandmap:node-palette-header"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-header-node",
            children=[
                "ui:grandmap:node-palette-title",
                "ui:grandmap:node-palette-hint",
                "ui:grandmap:node-palette-header-spacer",
            ],
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:node-palette-title",
            "span",
            "Nodes",
            cls="ah-node-palette-title-node",
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:node-palette-hint",
            "span",
            "drag - right-click",
            cls="ah-node-palette-hint-node",
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:node-palette-header-spacer",
            "div",
            "",
            cls="ah-node-palette-spacer-node",
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _node_palette_search_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-palette-search"
    nodes = [
        _slot("slot:nodes-palette-search", "node search", ""),
        _slot("slot:nodes-palette-sort", "sort mode", "default"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-search-wrap-node",
            children=["ui:grandmap:node-palette-search-row"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-search-row",
            "div",
            "",
            cls="ah-node-palette-search-node",
            children=[
                "ui:grandmap:node-palette-search-input",
                "ui:grandmap:node-palette-sort",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-search-input",
            "input",
            "",
            cls="ah-node-palette-search-input-node",
            bind="slot:nodes-palette-search",
            action="nodes.palette.search.update",
            input_type="text",
            placeholder="Search nodes...",
            test_id="node-palette-search",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-sort",
            "button",
            "A-Z",
            cls="ah-node-palette-sort-node",
            action="nodes.palette.sort.toggle",
            active_bind="slot:nodes-palette-sort",
            active_value="az",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_palette_item_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-palette-item"
    nodes = [
        _slot("slot:nodes-palette-item-title", "node title", "Node"),
        _slot("slot:nodes-palette-item-sub", "node subtitle", ""),
        _slot("slot:nodes-palette-item-effect", "node effect", ""),
        _slot("slot:nodes-palette-item-pinned", "pinned", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-item-node",
            double_action="nodes.palette.item.add",
            draggable=True,
            drag_payload={},
            children=[
                "ui:grandmap:node-palette-item-dot",
                "ui:grandmap:node-palette-item-copy",
                "ui:grandmap:node-palette-item-effect",
                "ui:grandmap:node-palette-item-pin",
                "ui:grandmap:node-palette-item-add",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-dot",
            "span",
            "",
            cls="ah-node-palette-item-dot-node",
            state_bind="slot:nodes-palette-item-effect",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-copy",
            "div",
            "",
            cls="ah-node-palette-item-copy-node",
            children=[
                "ui:grandmap:node-palette-item-title",
                "ui:grandmap:node-palette-item-sub",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-title",
            "div",
            "",
            cls="ah-node-palette-item-title-node",
            bind="slot:nodes-palette-item-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-sub",
            "div",
            "",
            cls="ah-node-palette-item-sub-node",
            bind="slot:nodes-palette-item-sub",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-effect",
            "span",
            "",
            cls="ah-node-palette-item-effect-node",
            bind="slot:nodes-palette-item-effect",
            state_bind="slot:nodes-palette-item-effect",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-pin",
            "button",
            "*",
            cls="ah-node-palette-item-pin-node",
            action="nodes.palette.item.pin.toggle",
            active_bind="slot:nodes-palette-item-pinned",
            active_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-item-add",
            "span",
            "+",
            cls="ah-node-palette-item-add-node",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_palette_section_header_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-palette-section-header"
    nodes = [
        _slot("slot:nodes-palette-section-title", "section title", "SECTION"),
        _slot("slot:nodes-palette-section-count", "section count", "0"),
        _slot("slot:nodes-palette-section-open", "section open", "false"),
        _slot("slot:nodes-palette-section-toggleable", "section toggleable", "false"),
        _slot("slot:nodes-palette-section-kind", "section kind", "section"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-section-node",
            action="nodes.palette.section.toggle",
            state_bind="slot:nodes-palette-section-kind",
            children=[
                "ui:grandmap:node-palette-section-chevron",
                "ui:grandmap:node-palette-section-title",
                "ui:grandmap:node-palette-section-count",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-section-chevron",
            "span",
            "",
            cls="ah-node-palette-section-chevron-node",
            hidden_bind="slot:nodes-palette-section-toggleable",
            hidden_value="false",
            text_cases={
                "bind": "slot:nodes-palette-section-open",
                "values": {"true": "v", "false": ">"},
                "default": ">",
            },
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-section-title",
            "span",
            "",
            cls="ah-node-palette-section-title-node",
            bind="slot:nodes-palette-section-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-section-count",
            "span",
            " - ",
            cls="ah-node-palette-section-count-node",
            bind="slot:nodes-palette-section-count",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_palette_menu_item_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-palette-menu-item"
    nodes = [
        _slot("slot:nodes-palette-menu-label", "menu label", ""),
        _slot("slot:nodes-palette-menu-kind", "menu kind", "action"),
        _slot("slot:nodes-palette-menu-danger", "menu danger", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-menu-item-node",
            state_bind="slot:nodes-palette-menu-kind",
            children=[
                "ui:grandmap:node-palette-menu-separator",
                "ui:grandmap:node-palette-menu-header",
                "ui:grandmap:node-palette-menu-button",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-menu-separator",
            "div",
            "",
            cls="ah-node-palette-menu-separator-node",
            state_bind="slot:nodes-palette-menu-kind",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-menu-header",
            "div",
            "",
            cls="ah-node-palette-menu-header-node",
            bind="slot:nodes-palette-menu-label",
            state_bind="slot:nodes-palette-menu-kind",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-menu-button",
            "button",
            "",
            cls="ah-node-palette-menu-button-node",
            bind="slot:nodes-palette-menu-label",
            action="nodes.palette.menu.item.run",
            active_bind="slot:nodes-palette-menu-danger",
            active_value="true",
            state_bind="slot:nodes-palette-menu-kind",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_palette_skill_sidecar_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_command_palette"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }
    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:node-palette-skill-sidecar"
    nodes = [
        _slot("slot:nodes-palette-skill-badge", "skill badge", "P"),
        _slot("slot:nodes-palette-skill-shared", "skill shared", "false"),
        _slot("slot:nodes-palette-skill-promotable", "skill promotable", "true"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-palette-skill-sidecar-node",
            children=[
                "ui:grandmap:node-palette-skill-badge",
                "ui:grandmap:node-palette-skill-promote",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-skill-badge",
            "span",
            "",
            cls="ah-node-palette-skill-badge-node",
            bind="slot:nodes-palette-skill-badge",
            active_bind="slot:nodes-palette-skill-shared",
            active_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:node-palette-skill-promote",
            "button",
            "?",
            cls="ah-node-palette-skill-promote-node",
            action="nodes.palette.skill.promote",
            hidden_bind="slot:nodes-palette-skill-promotable",
            hidden_value="false",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _node_properties_panel_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
        canvas_nodes = _load_domain_nodes(path, "canvas")
        node_nodes = _load_domain_nodes(path, "nodes")
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = [
        "ui_node_card",
        "ui_modal_system",
        "canvas_inline_param_edit",
        "nodes_param_promote",
    ]
    sources = {
        "ui_node_card": ui_nodes.get("ui_node_card"),
        "ui_modal_system": ui_nodes.get("ui_modal_system"),
        "canvas_inline_param_edit": canvas_nodes.get("canvas_inline_param_edit"),
        "nodes_param_promote": node_nodes.get("nodes_param_promote"),
    }
    missing = [node_id for node_id in source_ids if not sources.get(node_id)]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map node properties sources: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:node-properties-panel"
    nodes = [
        _slot("slot:node-title", "node title", ""),
        _slot("slot:node-subtitle", "node subtitle", ""),
        _slot("slot:node-category", "node category", ""),
        _slot("slot:node-param-count", "node param count", "0"),
        _slot("slot:node-property-help", "node property help",
              "This node's settings - its definition."),
        _slot("slot:node-param-key", "node param key", ""),
        _slot("slot:node-param-value", "node param value", ""),
        _slot("slot:node-param-type", "node param type", ""),
        _slot("slot:node-param-control", "node param control", "text"),
        _slot("slot:node-param-min", "node param minimum", ""),
        _slot("slot:node-param-max", "node param maximum", ""),
        _slot("slot:node-param-step", "node param step", ""),
        _slot("slot:node-param-promoted", "node param promoted", "false"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-node-properties-panel-node",
            children=[
                "ui:grandmap:node-properties-heading",
                "ui:grandmap:node-properties-help",
                "ui:grandmap:node-properties-list",
            ],
            source_node=sources["ui_modal_system"],
        ),
        _el(
            "ui:grandmap:node-properties-heading",
            "div",
            "",
            cls="ah-node-properties-heading-node",
            children=[
                "ui:grandmap:node-properties-kicker",
                "ui:grandmap:node-properties-title",
                "ui:grandmap:node-properties-subtitle",
                "ui:grandmap:node-properties-count",
            ],
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:node-properties-kicker",
            "div",
            "PROPERTIES",
            cls="ah-node-properties-kicker-node",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:node-properties-title",
            "div",
            "",
            cls="ah-node-properties-title-node",
            bind="slot:node-title",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:node-properties-subtitle",
            "div",
            "",
            cls="ah-node-properties-subtitle-node",
            bind="slot:node-subtitle",
            source_node=sources["ui_node_card"],
        ),
        _el(
            "ui:grandmap:node-properties-count",
            "div",
            "params: ",
            cls="ah-node-properties-count-node",
            bind="slot:node-param-count",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-properties-help",
            "div",
            "",
            cls="ah-node-properties-help-node",
            bind="slot:node-property-help",
            source_node=sources["ui_modal_system"],
        ),
        _el(
            "ui:grandmap:node-properties-list",
            "div",
            "",
            cls="ah-node-properties-list-node",
            children=[],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-row",
            "div",
            "",
            cls="ah-node-property-param-row-node",
            children=[
                "ui:grandmap:node-property-param-promote",
                "ui:grandmap:node-property-param-body",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-promote",
            "button",
            "⊙",
            cls="ah-node-property-param-promote-node",
            action="node.param.promote",
            active_bind="slot:node-param-promoted",
            active_value="true",
            visible_when={"bind": "slot:node-param-promotable", "values": ["true"]},
            source_node=sources["nodes_param_promote"],
        ),
        _el(
            "ui:grandmap:node-property-param-body",
            "div",
            "",
            cls="ah-node-property-param-body-node",
            children=[
                "ui:grandmap:node-property-param-label",
                "ui:grandmap:node-property-param-controls",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-label",
            "label",
            "",
            cls="ah-node-property-param-label-node",
            bind="slot:node-param-key",
            action="node.param.focus",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-controls",
            "div",
            "",
            cls="ah-node-property-param-controls-node",
            children=[
                "ui:grandmap:node-property-param-text-input",
                "ui:grandmap:node-property-param-number-input",
                "ui:grandmap:node-property-param-slider-input",
                "ui:grandmap:node-property-param-select",
                "ui:grandmap:node-property-param-boolean-input",
                "ui:grandmap:node-property-param-color-input",
            ],
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-text-input",
            "input",
            "",
            cls="ah-node-property-param-input-node",
            input_type="text",
            bind="slot:node-param-value",
            action="node.param.update",
            visible_when={"bind": "slot:node-param-control", "values": ["text"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-number-input",
            "input",
            "",
            cls="ah-node-property-param-input-node ah-node-property-param-number-node",
            input_type="number",
            bind="slot:node-param-value",
            action="node.param.update",
            value_cast="number",
            visible_when={"bind": "slot:node-param-control", "values": ["number", "slider"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-slider-input",
            "input",
            "",
            cls="ah-node-property-param-slider-node",
            input_type="range",
            input_min=0,
            input_max=100,
            input_step=1,
            bind="slot:node-param-value",
            action="node.param.update",
            value_cast="number",
            visible_when={"bind": "slot:node-param-control", "values": ["slider"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-select",
            "select",
            "",
            cls="ah-node-property-param-input-node ah-node-property-param-select-node",
            bind="slot:node-param-value",
            action="node.param.update",
            visible_when={"bind": "slot:node-param-control", "values": ["select"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-option",
            "option",
            "",
            cls="ah-node-property-param-option-node",
            option_value="",
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-boolean-input",
            "input",
            "",
            cls="ah-node-property-param-boolean-node",
            input_type="checkbox",
            bind="slot:node-param-value",
            action="node.param.update",
            value_cast="boolean",
            visible_when={"bind": "slot:node-param-control", "values": ["boolean"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
        _el(
            "ui:grandmap:node-property-param-color-input",
            "input",
            "",
            cls="ah-node-property-param-input-node ah-node-property-param-color-node",
            input_type="color",
            bind="slot:node-param-value",
            action="node.param.update",
            visible_when={"bind": "slot:node-param-control", "values": ["color"]},
            source_node=sources["canvas_inline_param_edit"],
        ),
    ]
    nodes_by_id = {node["id"]: node for node in nodes}
    nodes_by_id[root_id]["data"]["group_nodes"] = [
        "ui:grandmap:node-properties-heading",
        "ui:grandmap:node-properties-help",
        "ui:grandmap:node-properties-list",
        "ui:grandmap:node-property-param-row",
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _home_rail_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_sidebar_rail"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:home-rail-shell"
    nodes = [
        _el(
            root_id,
            "aside",
            "",
            cls="ah-home-rail-shell-node",
            children=["ui:grandmap:home-rail-icon-rail"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:home-rail-icon-rail",
            "div",
            "",
            cls="ah-home-rail-icon-rail-slot-node",
            render_slot="slot:home-rail-icon-rail",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _rail_drawer_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_sidebar_rail"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:rail-drawer-shell"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-rail-drawer-overlay-node",
            children=["ui:grandmap:rail-drawer-frame"],
            action="rail.drawer.close",
            args={"reason": "backdrop"},
            state_bind="slot:rail-drawer-panel",
            test_id="rail-drawer-overlay",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-drawer-frame",
            "div",
            "",
            cls="ah-rail-drawer-frame-node",
            children=[
                "ui:grandmap:rail-drawer-header",
                "ui:grandmap:rail-drawer-body",
            ],
            stop_click=True,
            test_id="rail-drawer",
            data_attrs={"data-rail-drawer": ""},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-drawer-header",
            "div",
            "",
            cls="ah-rail-drawer-header-node",
            children=[
                "ui:grandmap:rail-drawer-title",
                "ui:grandmap:rail-drawer-spacer",
                "ui:grandmap:rail-drawer-close",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-drawer-title",
            "span",
            "",
            cls="ah-rail-drawer-title-node",
            bind="slot:rail-drawer-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-drawer-spacer",
            "div",
            "",
            cls="ah-rail-drawer-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-drawer-close",
            "button",
            "\u2715",
            cls="ah-rail-drawer-close-node",
            action="rail.drawer.close",
            args={"reason": "button"},
            test_id="rail-drawer-close",
            title="Close (Esc)",
            data_attrs={"aria-label": "Close panel"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:rail-drawer-body",
            "div",
            "",
            cls="ah-rail-drawer-body-node",
            render_slot="slot:rail-drawer-body",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _sidebar_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_sidebar_rail"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:sidebar-shell"
    nodes = [
        _el(
            root_id,
            "aside",
            "",
            cls="ah-sidebar-shell-node",
            children=[
                "ui:grandmap:sidebar-icon-rail",
                "ui:grandmap:sidebar-active-panel",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:sidebar-icon-rail",
            "div",
            "",
            cls="ah-sidebar-icon-rail-slot-node",
            render_slot="slot:sidebar-icon-rail",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:sidebar-active-panel",
            "div",
            "",
            cls="ah-sidebar-active-panel-slot-node",
            render_slot="slot:sidebar-active-panel",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": [source_id],
    }


def _search_panel_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "ui": ["ui_command_palette"],
        "sessions": ["sessions_threads_rail"],
        "canvas": ["canvas_lm_graph_state"],
        "brain": ["brain_skills", "brain_fact_store"],
        "nodes": ["nodes_library_search"],
        "connectors": ["connectors_panel"],
    }
    try:
        domain_nodes = {
            key: _load_domain_nodes(path, key)
            for key in required
        }
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }

    source_nodes: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domain_nodes[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                source_nodes[node_id] = node
    source_ids = [
        "ui_command_palette",
        "sessions_threads_rail",
        "canvas_lm_graph_state",
        "brain_skills",
        "brain_fact_store",
        "nodes_library_search",
        "connectors_panel",
    ]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map search source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:search-panel-shell"
    slot_defs = [
        ("header", "slot:search-panel-shell-header", "ui_command_palette"),
        ("search", "slot:search-panel-shell-search", "ui_command_palette"),
        ("scopes", "slot:search-panel-shell-scopes", "ui_command_palette"),
        ("results", "slot:search-panel-shell-results", "canvas_lm_graph_state"),
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-panel-shell-node",
            children=[f"ui:grandmap:search-panel-shell-{key}" for key, _slot, _src in slot_defs],
            source_node=source_nodes["ui_command_palette"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:search-panel-shell-{key}",
            "div",
            "",
            cls=f"ah-search-panel-shell-{key}-slot-node",
            render_slot=slot,
            source_node=source_nodes[source_id],
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _search_source_node(path: Path, source_id: str = "ui_command_palette") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    domains = ("ui", "sessions", "canvas", "brain", "nodes", "connectors")
    try:
        domain_nodes = {key: _load_domain_nodes(path, key) for key in domains}
    except Exception as ex:
        return None, {
            "ok": False,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    for nodes in domain_nodes.values():
        node = nodes.get(source_id)
        if node is not None:
            return node, None
    return None, {
        "ok": False,
        "source": str(path),
        "error": "missing Grand Map search source node: " + source_id,
    }


def _search_panel_header_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-panel-header"
    nodes = [
        _slot("slot:search-panel-title", "search panel title", "Search"),
        _slot("slot:search-panel-shortcut", "search panel shortcut", "CMD+K"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-panel-header-node",
            children=[
                "ui:grandmap:search-panel-title",
                "ui:grandmap:search-panel-spacer",
                "ui:grandmap:search-panel-shortcut",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-panel-title",
            "span",
            "",
            cls="ah-search-panel-title-node",
            bind="slot:search-panel-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-panel-spacer",
            "div",
            "",
            cls="ah-search-panel-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-panel-shortcut",
            "kbd",
            "",
            cls="ah-search-panel-shortcut-node",
            bind="slot:search-panel-shortcut",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _search_panel_input_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-panel-input"
    nodes = [
        _slot("slot:search-query", "search query", ""),
        _slot("slot:search-placeholder", "search placeholder", "everything in studio..."),
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-input-wrap-node",
            children=["ui:grandmap:search-input-row"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-input-row",
            "div",
            "",
            cls="ah-search-input-row-node",
            children=[
                "ui:grandmap:search-input-icon",
                "ui:grandmap:search-input-field",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-input-icon",
            "span",
            "search",
            cls="ah-search-input-icon-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-input-field",
            "input",
            "",
            cls="ah-search-input-field-node",
            bind="slot:search-query",
            action="search.query.update",
            placeholder="everything in studio...",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _search_panel_scopes_label_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-panel-scopes-label"
    nodes = [
        _slot("slot:search-scopes-label", "search scopes label", "SCOPES"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-scopes-label-node",
            bind="slot:search-scopes-label",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["ui_command_palette"],
    }


def _search_panel_scopes_list_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-panel-scopes-list"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-scopes-list-node",
            render_slot="slot:search-panel-scopes-list-content",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["ui_command_palette"],
    }


def _search_panel_scope_row_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-scope-row"
    nodes = [
        _slot("slot:search-scope-key", "search scope key", "all"),
        _slot("slot:search-scope-sub", "search scope sub", "everything"),
        _slot("slot:search-scope-count", "search scope count", "0"),
        _slot("slot:search-scope-active", "search scope active", "false"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-search-scope-row-node",
            active_bind="slot:search-scope-active",
            active_value="true",
            action="search.scope.pick",
            children=[
                "ui:grandmap:search-scope-key",
                "ui:grandmap:search-scope-sub",
                "ui:grandmap:search-scope-count",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-scope-key",
            "span",
            "",
            cls="ah-search-scope-key-node",
            bind="slot:search-scope-key",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-scope-sub",
            "span",
            "",
            cls="ah-search-scope-sub-node",
            bind="slot:search-scope-sub",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-scope-count",
            "span",
            "",
            cls="ah-search-scope-count-node",
            bind="slot:search-scope-count",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["ui_command_palette"],
    }


def _search_panel_results_list_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "canvas_lm_graph_state")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-panel-results-list"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-results-list-node ah-scroll",
            render_slot="slot:search-panel-results-list-content",
            test_id="search-panel-results-list",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["canvas_lm_graph_state"],
    }


def _search_panel_empty_state_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "ui_command_palette")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-empty-state"
    nodes = [
        _slot("slot:search-empty-visible", "search empty visible", "false"),
        _slot("slot:search-empty-message", "search empty message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-search-empty-state-node",
            bind="slot:search-empty-message",
            visible_when={"bind": "slot:search-empty-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["ui_command_palette"],
    }


def _search_panel_hit_row_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _search_source_node(path, "canvas_lm_graph_state")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:search-hit-row"
    nodes = [
        _slot("slot:search-hit-kind", "search hit kind", "hit"),
        _slot("slot:search-hit-label", "search hit label", ""),
        _slot("slot:search-hit-sub", "search hit sub", ""),
        _slot("slot:search-hit-sub-visible", "search hit sub visible", "false"),
        _slot("slot:search-hit-disabled", "search hit disabled", "false"),
        _el(
            root_id,
            "button",
            "",
            cls="ah-search-hit-row-node",
            action="search.hit.activate",
            disabled_bind="slot:search-hit-disabled",
            disabled_value="true",
            children=[
                "ui:grandmap:search-hit-kind",
                "ui:grandmap:search-hit-body",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-hit-kind",
            "span",
            "",
            cls="ah-search-hit-kind-node",
            bind="slot:search-hit-kind",
            state_bind="slot:search-hit-kind",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-hit-body",
            "div",
            "",
            cls="ah-search-hit-body-node",
            children=[
                "ui:grandmap:search-hit-label",
                "ui:grandmap:search-hit-sub",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-hit-label",
            "div",
            "",
            cls="ah-search-hit-label-node",
            bind="slot:search-hit-label",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:search-hit-sub",
            "div",
            "",
            cls="ah-search-hit-sub-node",
            bind="slot:search-hit-sub",
            visible_when={"bind": "slot:search-hit-sub-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["canvas_lm_graph_state"],
    }


def _share_panel_shell_surface(path: Path, surface: str) -> dict[str, Any]:
    required = {
        "sessions": ["sessions_share_export"],
        "brain": ["brain_skills"],
        "community": ["community_share_card"],
        "cloud": ["cloud_sync_client"],
        "users": ["users_account_chip"],
    }
    try:
        domain_nodes = {
            key: _load_domain_nodes(path, key)
            for key in required
        }
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }

    source_nodes: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for domain, node_ids in required.items():
        for node_id in node_ids:
            node = domain_nodes[domain].get(node_id)
            if node is None:
                missing.append(node_id)
            else:
                source_nodes[node_id] = node
    source_ids = [
        "sessions_share_export",
        "brain_skills",
        "community_share_card",
        "cloud_sync_client",
        "users_account_chip",
    ]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map share source nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:share-panel-shell"
    slot_defs = [
        ("header", "slot:share-panel-shell-header", "community_share_card"),
        ("description", "slot:share-panel-shell-description", "sessions_share_export"),
        ("list", "slot:share-panel-shell-list", "sessions_share_export"),
    ]
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-panel-shell-node",
            children=[f"ui:grandmap:share-panel-shell-{key}" for key, _slot, _src in slot_defs],
            test_id="rail-share",
            source_node=source_nodes["sessions_share_export"],
        ),
    ]
    for key, slot, source_id in slot_defs:
        nodes.append(_el(
            f"ui:grandmap:share-panel-shell-{key}",
            "div",
            "",
            cls=f"ah-share-panel-shell-{key}-slot-node",
            render_slot=slot,
            source_node=source_nodes[source_id],
        ))
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _share_source_node(path: Path, source_id: str = "sessions_share_export") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        sessions = _load_domain_nodes(path, "sessions")
        community = _load_domain_nodes(path, "community")
        brain = _load_domain_nodes(path, "brain")
    except Exception as ex:
        return None, {
            "ok": False,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    node = sessions.get(source_id) or community.get(source_id) or brain.get(source_id)
    if node is None:
        return None, {
            "ok": False,
            "source": str(path),
            "error": "missing Grand Map share source node: " + source_id,
        }
    return node, None


def _share_panel_header_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-header"
    nodes = [
        _slot("slot:share-panel-title", "share panel title", "Share & publish"),
        _slot("slot:share-panel-count", "shareable count", "0 SHAREABLE"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-panel-header-node",
            children=[
                "ui:grandmap:share-panel-title",
                "ui:grandmap:share-panel-count",
                "ui:grandmap:share-panel-spacer",
                "ui:grandmap:share-panel-add",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-panel-title",
            "span",
            "",
            cls="ah-share-panel-title-node",
            bind="slot:share-panel-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-panel-count",
            "span",
            "",
            cls="ah-share-panel-count-node",
            bind="slot:share-panel-count",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-panel-spacer",
            "div",
            "",
            cls="ah-share-panel-spacer-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-panel-add",
            "button",
            "+",
            cls="ah-share-panel-add-node",
            action="share.canvas",
            data_attrs={"aria-label": "Share the current canvas as a new skill"},
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["sessions_share_export"],
    }


def _share_panel_description_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-description"
    nodes = [
        _slot("slot:share-panel-description", "share panel description",
              "Hand a skill or a whole session to a teammate - each export writes a real, re-loadable file you can link or paste."),
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-panel-description-node",
            bind="slot:share-panel-description",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["sessions_share_export"],
    }


def _share_panel_list_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-list"
    nodes = [
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-panel-list-node ah-scroll",
            render_slot="slot:share-panel-list-content",
            test_id="rail-share-list",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["sessions_share_export"],
    }


def _share_panel_section_heading_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-section-heading"
    nodes = [
        _slot("slot:share-section-title", "share section title", "SECTION"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-section-heading-node",
            bind="slot:share-section-title",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["sessions_share_export"],
    }


def _share_panel_row_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-row"
    nodes = [
        _slot("slot:share-row-icon", "share row icon", "*"),
        _slot("slot:share-row-title", "share row title", ""),
        _slot("slot:share-row-badge", "share row badge", ""),
        _slot("slot:share-row-badge-visible", "share row badge visible", "false"),
        _slot("slot:share-row-badge-state", "share row badge state", "private"),
        _slot("slot:share-row-count", "share row count", ""),
        _slot("slot:share-row-count-visible", "share row count visible", "false"),
        _slot("slot:share-row-publish-visible", "share row publish visible", "false"),
        _slot("slot:share-row-busy", "share row busy", "false"),
        _slot("slot:share-row-note-visible", "share row note visible", "false"),
        _slot("slot:share-row-note", "share row note", ""),
        _slot("slot:share-row-note-kind", "share row note kind", "info"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-row-node",
            test_id="rail-share-row",
            children=[
                "ui:grandmap:share-row-main",
                "ui:grandmap:share-row-actions",
                "ui:grandmap:share-row-note",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-main",
            "div",
            "",
            cls="ah-share-row-main-node",
            children=[
                "ui:grandmap:share-row-icon",
                "ui:grandmap:share-row-title",
                "ui:grandmap:share-row-badge",
                "ui:grandmap:share-row-count",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-icon",
            "span",
            "",
            cls="ah-share-row-icon-node",
            bind="slot:share-row-icon",
            state_bind="slot:share-row-badge-state",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-title",
            "span",
            "",
            cls="ah-share-row-title-node",
            bind="slot:share-row-title",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-badge",
            "span",
            "",
            cls="ah-share-row-badge-node",
            bind="slot:share-row-badge",
            state_bind="slot:share-row-badge-state",
            visible_when={"bind": "slot:share-row-badge-visible", "values": ["true"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-count",
            "span",
            "",
            cls="ah-share-row-count-node",
            bind="slot:share-row-count",
            visible_when={"bind": "slot:share-row-count-visible", "values": ["true"]},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-actions",
            "div",
            "",
            cls="ah-share-row-actions-node",
            children=[
                "ui:grandmap:share-row-copy-link",
                "ui:grandmap:share-row-export-json",
                "ui:grandmap:share-row-publish",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-copy-link",
            "button",
            "Copy link",
            cls="ah-share-row-action-node",
            action="share.row.export",
            args={"want": "link"},
            disabled_bind="slot:share-row-busy",
            disabled_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-export-json",
            "button",
            "Export JSON",
            cls="ah-share-row-action-node",
            action="share.row.export",
            args={"want": "json"},
            disabled_bind="slot:share-row-busy",
            disabled_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-publish",
            "button",
            "Publish",
            cls="ah-share-row-action-node",
            action="share.row.publish",
            visible_when={"bind": "slot:share-row-publish-visible", "values": ["true"]},
            disabled_bind="slot:share-row-busy",
            disabled_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:share-row-note",
            "div",
            "",
            cls="ah-share-row-note-node",
            bind="slot:share-row-note",
            state_bind="slot:share-row-note-kind",
            visible_when={"bind": "slot:share-row-note-visible", "values": ["true"]},
            test_id="rail-share-note",
            source_node=source_node,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": ["sessions_share_export"],
    }


def _share_panel_empty_state_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-empty-state"
    nodes = [
        _slot("slot:share-empty-visible", "share empty visible", "false"),
        _slot("slot:share-empty-message", "share empty message", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-empty-state-node",
            bind="slot:share-empty-message",
            visible_when={"bind": "slot:share-empty-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["sessions_share_export"],
    }


def _share_panel_loading_surface(path: Path, surface: str) -> dict[str, Any]:
    source_node, error = _share_source_node(path, "sessions_share_export")
    if error:
        return {**error, "surface": surface}
    root_id = "ui:grandmap:share-panel-loading"
    nodes = [
        _slot("slot:share-loading-visible", "share loading visible", "false"),
        _slot("slot:share-loading-message", "share loading message", "loading your shareables..."),
        _el(
            root_id,
            "div",
            "",
            cls="ah-share-loading-node",
            bind="slot:share-loading-message",
            visible_when={"bind": "slot:share-loading-visible", "values": ["true"]},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": ["sessions_share_export"],
    }


def _app_rail_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["ui_sidebar_rail", "ui_command_palette", "ui_modal_system"]
    missing = [node_id for node_id in source_ids if node_id not in ui_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI nodes: " + ", ".join(missing),
        }
    root_id = "ui:grandmap:app-rail"
    def rail_button(
        node_id: str,
        label: str,
        *,
        action: str,
        test_id: str,
        source_node: dict[str, Any],
        icon_children: list[dict[str, Any]],
        active_value: str = "",
    ) -> list[dict[str, Any]]:
        icon_id = f"{node_id}-icon"
        label_id = f"{node_id}-label"
        svg_id = f"{node_id}-svg"
        button = _el(
            node_id,
            "button",
            "",
            cls="ah-rail-button-node",
            children=[icon_id, label_id],
            action=action,
            active_bind="slot:rail-active" if active_value else "",
            active_value=active_value,
            test_id=test_id,
            source_node=source_node,
        )
        icon = _el(
            icon_id,
            "span",
            "",
            cls="ah-rail-icon-node",
            children=[svg_id],
            source_node=source_node,
        )
        label_node = _el(
            label_id,
            "span",
            label,
            cls="ah-rail-label-node",
            source_node=source_node,
        )
        svg = _el(
            svg_id,
            "svg",
            "",
            children=[child["id"] for child in icon_children],
            data_attrs={
                "width": "17" if label == "home" else "16",
                "height": "17" if label == "home" else "16",
                "viewBox": "0 0 24 24",
                "fill": "none",
                **({} if label == "home" else {
                    "stroke": "currentColor",
                    "strokeWidth": "1.8",
                }),
            },
            source_node=source_node,
        )
        return [button, icon, label_node, svg, *icon_children]

    home_icon = [
        _el(
            "ui:grandmap:rail-home-path",
            "path",
            "",
            data_attrs={
                "d": "M3 21 V12 a9 9 0 0 1 18 0 V21",
                "stroke": "currentColor",
                "strokeWidth": "2",
                "strokeLinecap": "round",
            },
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:rail-home-dot",
            "circle",
            "",
            data_attrs={
                "cx": "12",
                "cy": "8.5",
                "r": "1.6",
                "fill": "currentColor",
            },
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
    ]
    search_icon = [
        _el(
            "ui:grandmap:rail-search-circle",
            "circle",
            "",
            data_attrs={"cx": "11", "cy": "11", "r": "7"},
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el(
            "ui:grandmap:rail-search-path",
            "path",
            "",
            data_attrs={"d": "M21 21l-4.3-4.3", "strokeLinecap": "round"},
            source_node=ui_nodes["ui_command_palette"],
        ),
    ]
    share_icon = [
        _el(
            "ui:grandmap:rail-share-path-a",
            "path",
            "",
            data_attrs={"d": "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"},
            source_node=ui_nodes["ui_modal_system"],
        ),
        _el(
            "ui:grandmap:rail-share-path-b",
            "path",
            "",
            data_attrs={"d": "M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"},
            source_node=ui_nodes["ui_modal_system"],
        ),
    ]
    settings_icon = [
        _el(
            "ui:grandmap:rail-settings-circle",
            "circle",
            "",
            data_attrs={"cx": "12", "cy": "12", "r": "3"},
            source_node=ui_nodes["ui_modal_system"],
        ),
        _el(
            "ui:grandmap:rail-settings-path",
            "path",
            "",
            data_attrs={
                "d": "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
            },
            source_node=ui_nodes["ui_modal_system"],
        ),
    ]

    nodes = [
        _slot("slot:rail-active", "active rail item", "home"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-app-rail-node",
            children=[
                "ui:grandmap:rail-home",
                "ui:grandmap:rail-search",
                "ui:grandmap:rail-spacer",
                "ui:grandmap:rail-divider",
                "ui:grandmap:rail-share",
                "ui:grandmap:rail-settings",
            ],
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        *rail_button(
            "ui:grandmap:rail-home",
            "home",
            action="rail.home.open",
            active_value="home",
            test_id="rail-home",
            source_node=ui_nodes["ui_sidebar_rail"],
            icon_children=home_icon,
        ),
        *rail_button(
            "ui:grandmap:rail-search",
            "search",
            action="rail.search.open",
            active_value="search",
            test_id="rail-search",
            source_node=ui_nodes["ui_command_palette"],
            icon_children=search_icon,
        ),
        _el(
            "ui:grandmap:rail-spacer",
            "div",
            "",
            cls="ah-rail-spacer-node",
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:rail-divider",
            "div",
            "",
            cls="ah-rail-divider-node",
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        *rail_button(
            "ui:grandmap:rail-share",
            "share",
            action="rail.share.open",
            test_id="rail-share-icon",
            source_node=ui_nodes["ui_modal_system"],
            icon_children=share_icon,
        ),
        *rail_button(
            "ui:grandmap:rail-settings",
            "settings",
            action="settings.open",
            test_id="rail-settings",
            source_node=ui_nodes["ui_modal_system"],
            icon_children=settings_icon,
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _status_strip_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = [
        "ui_sidebar_rail",
        "ui_command_palette",
        "ui_account_chip",
        "ui_composer_bar",
    ]
    missing = [node_id for node_id in source_ids if node_id not in ui_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI nodes: " + ", ".join(missing),
        }
    root_id = "ui:grandmap:status-strip"
    nodes = [
        _slot("slot:status-runtime", "runtime", "server"),
        _slot("slot:status-session", "session", ""),
        _slot("slot:status-model", "model", ""),
        _slot("slot:status-memory", "memory", "memory"),
        _slot("slot:status-health", "health", "healthy"),
        _slot("slot:status-version", "version", "ArchHub"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-status-strip-node",
            children=[
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
            ],
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el(
            "ui:grandmap:status-runtime",
            "button",
            "",
            cls="ah-status-item-node",
            bind="slot:status-runtime",
            action="settings.open",
            source_node=ui_nodes["ui_sidebar_rail"],
        ),
        _el("ui:grandmap:status-sep-a", "span", "", cls="ah-status-separator-node", source_node=ui_nodes["ui_sidebar_rail"]),
        _el(
            "ui:grandmap:status-session",
            "span",
            "",
            cls="ah-status-item-node",
            bind="slot:status-session",
            source_node=ui_nodes["ui_composer_bar"],
        ),
        _el(
            "ui:grandmap:status-model",
            "button",
            "",
            cls="ah-status-item-node",
            bind="slot:status-model",
            action="settings.open",
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el("ui:grandmap:status-sep-b", "span", "", cls="ah-status-separator-node", source_node=ui_nodes["ui_sidebar_rail"]),
        _el(
            "ui:grandmap:status-memory",
            "button",
            "",
            cls="ah-status-item-node",
            bind="slot:status-memory",
            action="memory.open",
            source_node=ui_nodes["ui_account_chip"],
        ),
        _el(
            "ui:grandmap:status-health",
            "button",
            "",
            cls="ah-status-health-node",
            bind="slot:status-health",
            action="graph.health.open",
            source_node=ui_nodes["ui_command_palette"],
        ),
        _el("ui:grandmap:status-spacer", "div", "", cls="ah-status-spacer-node", source_node=ui_nodes["ui_sidebar_rail"]),
        _el(
            "ui:grandmap:status-settings",
            "button",
            "settings",
            cls="ah-status-item-node",
            action="settings.open",
            source_node=ui_nodes["ui_modal_system"] if "ui_modal_system" in ui_nodes else ui_nodes["ui_sidebar_rail"],
        ),
        _el("ui:grandmap:status-sep-c", "span", "", cls="ah-status-separator-node", source_node=ui_nodes["ui_sidebar_rail"]),
        _el(
            "ui:grandmap:status-version",
            "button",
            "",
            cls="ah-status-item-node",
            bind="slot:status-version",
            action="application.focus",
            args={"node_id": "app:archhub"},
            source_node=ui_nodes["ui_design_tokens"] if "ui_design_tokens" in ui_nodes else ui_nodes["ui_sidebar_rail"],
        ),
    ]
    wires = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _update_notifier_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_ids = ["ui_modal_system", "ui_design_tokens"]
    missing = [node_id for node_id in source_ids if node_id not in ui_nodes]
    if missing:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI nodes: " + ", ".join(missing),
        }

    root_id = "ui:grandmap:update-notifier"
    source_node = ui_nodes["ui_modal_system"]
    token_source = ui_nodes["ui_design_tokens"]
    nodes = [
        _slot("slot:update-current", "update current version", "?"),
        _slot("slot:update-latest", "update latest version", "latest"),
        _slot("slot:update-busy", "update busy", "false"),
        _slot("slot:update-relaunch-label", "update relaunch label", "Relaunch to update"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-update-banner-node",
            test_id="update-banner",
            children=[
                "ui:grandmap:update-icon",
                "ui:grandmap:update-copy",
                "ui:grandmap:update-relaunch",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-icon",
            "span",
            "update",
            cls="ah-update-icon-node",
            source_node=token_source,
        ),
        _el(
            "ui:grandmap:update-copy",
            "div",
            "",
            cls="ah-update-copy-node",
            children=[
                "ui:grandmap:update-title",
                "ui:grandmap:update-version-line",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-title",
            "span",
            "Update available",
            cls="ah-update-title-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-version-line",
            "span",
            "",
            cls="ah-update-version-line-node",
            children=[
                "ui:grandmap:update-current",
                "ui:grandmap:update-arrow",
                "ui:grandmap:update-latest",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-current",
            "span",
            "",
            cls="ah-update-version-node ah-update-current-node",
            bind="slot:update-current",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-arrow",
            "span",
            " -> ",
            cls="ah-update-arrow-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-latest",
            "span",
            "",
            cls="ah-update-version-node ah-update-latest-node",
            bind="slot:update-latest",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:update-relaunch",
            "button",
            "",
            cls="ah-update-relaunch-node",
            bind="slot:update-relaunch-label",
            action="update.relaunch",
            disabled_bind="slot:update-busy",
            disabled_value="true",
            test_id="update-relaunch",
            source_node=source_node,
        ),
    ]
    wires = _child_wires(nodes)
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": wires,
        "source_node_ids": source_ids,
    }


def _global_toast_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    root_id = "ui:grandmap:global-toast"
    source_node = ui_nodes[source_id]
    nodes = [
        _slot("slot:global-toast-message", "global toast message", ""),
        _slot("slot:global-toast-kind", "global toast kind", "info"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-global-toast-node",
            bind="slot:global-toast-message",
            state_bind="slot:global-toast-kind",
            test_id="global-toast",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _canvas_toast_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    root_id = "ui:grandmap:canvas-toast"
    source_node = ui_nodes[source_id]
    nodes = [
        _slot("slot:canvas-toast-message", "canvas toast message", ""),
        _slot("slot:canvas-toast-kind", "canvas toast kind", "info"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-canvas-toast-node",
            bind="slot:canvas-toast-message",
            state_bind="slot:canvas-toast-kind",
            test_id="canvas-toast",
            data_attrs={"data-no-pan": "true"},
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": [],
        "source_node_ids": [source_id],
    }


def _radio_key_actions(
    values: list[str],
    index: int,
    action: str,
    arg_name: str,
) -> dict[str, dict[str, Any]]:
    count = len(values)
    previous_value = values[(index - 1) % count]
    next_value = values[(index + 1) % count]
    return {
        "ArrowLeft": {"action": action, "args": {arg_name: previous_value}},
        "ArrowUp": {"action": action, "args": {arg_name: previous_value}},
        "ArrowRight": {"action": action, "args": {arg_name: next_value}},
        "ArrowDown": {"action": action, "args": {arg_name: next_value}},
        "Home": {"action": action, "args": {arg_name: values[0]}},
        "End": {"action": action, "args": {arg_name: values[-1]}},
    }


def _canvas_group_dialog_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-group-dialog"
    style_values = ["input", "connector", "ai", "transform", "output", "note"]
    style_ids = [
        f"ui:grandmap:group-style-{style}"
        for style in style_values
    ]
    nodes = [
        _slot("slot:group-title", "group title", "Group"),
        _slot("slot:group-style", "group style", "transform"),
        _slot("slot:group-selection-count", "group selected nodes", "0 nodes in selection"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-group-dialog-backdrop-node",
            action="canvas.group.cancel",
            children=["ui:grandmap:group-dialog-panel"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-dialog-panel",
            "div",
            "",
            cls="ah-group-dialog-panel-node",
            role="dialog",
            action="canvas.group.noop",
            data_attrs={
                "data-no-pan": "true",
                "aria-modal": "true",
                "aria-label": "New group",
            },
            children=[
                "ui:grandmap:group-dialog-title",
                "ui:grandmap:group-dialog-count",
                "ui:grandmap:group-title-field",
                "ui:grandmap:group-style-field",
                "ui:grandmap:group-dialog-actions",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-dialog-title",
            "div",
            "New group",
            cls="ah-group-dialog-title-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-dialog-count",
            "div",
            "",
            cls="ah-group-dialog-count-node",
            bind="slot:group-selection-count",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-title-field",
            "div",
            "",
            cls="ah-group-field-node",
            children=[
                "ui:grandmap:group-title-label",
                "ui:grandmap:group-title-input",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-title-label",
            "div",
            "TITLE",
            cls="ah-group-field-label-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-title-input",
            "input",
            "",
            cls="ah-group-title-input-node",
            bind="slot:group-title",
            action="canvas.group.title.update",
            submit_action="canvas.group.create",
            input_type="text",
            test_id="group-title-input",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-style-field",
            "div",
            "",
            cls="ah-group-field-node",
            children=[
                "ui:grandmap:group-style-label",
                "ui:grandmap:group-style-list",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-style-label",
            "div",
            "STYLE",
            cls="ah-group-field-label-node",
            data_attrs={"id": "lm-group-style-label"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-style-list",
            "div",
            "",
            cls="ah-group-style-list-node",
            role="radiogroup",
            data_attrs={"aria-labelledby": "lm-group-style-label"},
            children=style_ids,
            source_node=source_node,
        ),
        *[
            _el(
                f"ui:grandmap:group-style-{style}",
                "button",
                style.upper(),
                cls=f"ah-group-style-button-node ah-group-style-{style}-node",
                role="radio",
                action="canvas.group.style.set",
                args={"style": style},
                key_actions=_radio_key_actions(
                    style_values,
                    index,
                    "canvas.group.style.set",
                    "style",
                ),
                active_bind="slot:group-style",
                active_value=style,
                source_node=source_node,
            )
            for index, style in enumerate(style_values)
        ],
        _el(
            "ui:grandmap:group-dialog-actions",
            "div",
            "",
            cls="ah-group-dialog-actions-node",
            children=[
                "ui:grandmap:group-cancel",
                "ui:grandmap:group-create",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-cancel",
            "button",
            "Cancel",
            cls="ah-group-cancel-node",
            action="canvas.group.cancel",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:group-create",
            "button",
            "Create",
            cls="ah-group-create-node",
            action="canvas.group.create",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _canvas_save_skill_dialog_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:canvas-save-skill-dialog"
    nodes = [
        _slot("slot:save-skill-name", "skill name", "untitled skill"),
        _slot("slot:save-skill-description", "skill description", ""),
        _slot("slot:save-skill-category", "skill category", ""),
        _slot("slot:save-skill-mode", "skill mode", "shared"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-save-skill-backdrop-node",
            action="canvas.save-skill.cancel",
            children=["ui:grandmap:save-skill-panel"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:save-skill-panel",
            "div",
            "",
            cls="ah-save-skill-panel-node",
            role="dialog",
            action="canvas.save-skill.noop",
            data_attrs={
                "data-no-pan": "true",
                "aria-modal": "true",
                "aria-label": "Save as Skill",
            },
            children=[
                "ui:grandmap:save-skill-title",
                "ui:grandmap:save-skill-name-field",
                "ui:grandmap:save-skill-description-field",
                "ui:grandmap:save-skill-category-field",
                "ui:grandmap:save-skill-mode-field",
                "ui:grandmap:save-skill-actions",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:save-skill-title", "div", "Save as Skill", cls="ah-save-skill-title-node", source_node=source_node),
        _save_skill_field_node(
            "ui:grandmap:save-skill-name-field",
            "ui:grandmap:save-skill-name-label",
            "ui:grandmap:save-skill-name-input",
            "NAME",
            "input",
            "slot:save-skill-name",
            "canvas.save-skill.name.update",
            source_node,
            input_type="text",
            submit_action="canvas.save-skill.save",
            test_id="save-skill-name-input",
        ),
        _save_skill_field_node(
            "ui:grandmap:save-skill-description-field",
            "ui:grandmap:save-skill-description-label",
            "ui:grandmap:save-skill-description-input",
            "DESCRIPTION",
            "textarea",
            "slot:save-skill-description",
            "canvas.save-skill.description.update",
            source_node,
            placeholder="What does this skill do?",
            test_id="save-skill-description-input",
        ),
        _save_skill_field_node(
            "ui:grandmap:save-skill-category-field",
            "ui:grandmap:save-skill-category-label",
            "ui:grandmap:save-skill-category-input",
            "CATEGORY",
            "input",
            "slot:save-skill-category",
            "canvas.save-skill.category.update",
            source_node,
            input_type="text",
            submit_action="canvas.save-skill.save",
            placeholder="e.g. revit, takeoff, qa",
            test_id="save-skill-category-input",
        ),
        _el(
            "ui:grandmap:save-skill-mode-field",
            "div",
            "",
            cls="ah-save-skill-field-node",
            children=[
                "ui:grandmap:save-skill-mode-label",
                "ui:grandmap:save-skill-mode-list",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:save-skill-mode-label",
            "div",
            "MODE",
            cls="ah-save-skill-field-label-node",
            data_attrs={"id": "lm-save-skill-mode-label"},
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:save-skill-mode-list",
            "div",
            "",
            cls="ah-save-skill-mode-list-node",
            role="radiogroup",
            data_attrs={"aria-labelledby": "lm-save-skill-mode-label"},
            children=[
                "ui:grandmap:save-skill-mode-shared",
                "ui:grandmap:save-skill-mode-private",
            ],
            source_node=source_node,
        ),
        _save_skill_mode_node(
            "ui:grandmap:save-skill-mode-shared",
            "Shared (reference)",
            "Edit once, every placement updates.",
            "shared",
            source_node,
        ),
        _save_skill_mode_node(
            "ui:grandmap:save-skill-mode-private",
            "Private (copy)",
            "A snapshot stamped at save time.",
            "private",
            source_node,
        ),
        _el(
            "ui:grandmap:save-skill-actions",
            "div",
            "",
            cls="ah-save-skill-actions-node",
            children=[
                "ui:grandmap:save-skill-cancel",
                "ui:grandmap:save-skill-save",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:save-skill-cancel",
            "button",
            "Cancel",
            cls="ah-save-skill-cancel-node",
            action="canvas.save-skill.cancel",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:save-skill-save",
            "button",
            "Save",
            cls="ah-save-skill-save-node",
            action="canvas.save-skill.save",
            source_node=source_node,
        ),
    ]
    expanded_nodes: list[dict[str, Any]] = []
    for node in nodes:
        child_nodes = node.pop("_children", [])
        expanded_nodes.append(node)
        expanded_nodes.extend(child_nodes)
    nodes = expanded_nodes
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _save_skill_field_node(
    field_id: str,
    label_id: str,
    control_id: str,
    label: str,
    tag: str,
    bind: str,
    action: str,
    source_node: dict[str, Any],
    *,
    input_type: str = "",
    submit_action: str = "",
    placeholder: str = "",
    test_id: str = "",
) -> dict[str, Any]:
    return _el(
        field_id,
        "div",
        "",
        cls="ah-save-skill-field-node",
        children=[
            label_id,
            control_id,
        ],
        source_node=source_node,
    ) | {"_children": [
        _el(label_id, "div", label, cls="ah-save-skill-field-label-node", source_node=source_node),
        _el(
            control_id,
            tag,
            "",
            cls=f"ah-save-skill-{label.lower()}-input-node".replace(" ", "-"),
            bind=bind,
            action=action,
            input_type=input_type,
            submit_action=submit_action,
            placeholder=placeholder,
            test_id=test_id,
            source_node=source_node,
        ),
    ]}


def _save_skill_mode_node(
    node_id: str,
    title: str,
    hint: str,
    value: str,
    source_node: dict[str, Any],
) -> dict[str, Any]:
    values = ["shared", "private"]
    return _el(
        node_id,
        "button",
        "",
        cls=f"ah-save-skill-mode-node ah-save-skill-mode-{value}-node",
        role="radio",
        action="canvas.save-skill.mode.set",
        args={"mode": value},
        key_actions=_radio_key_actions(
            values,
            values.index(value),
            "canvas.save-skill.mode.set",
            "mode",
        ),
        active_bind="slot:save-skill-mode",
        active_value=value,
        children=[
            f"{node_id}-label",
            f"{node_id}-hint",
        ],
        source_node=source_node,
    ) | {"_children": [
        _el(f"{node_id}-label", "span", title, cls="ah-save-skill-mode-label-node", source_node=source_node),
        _el(f"{node_id}-hint", "span", hint, cls="ah-save-skill-mode-hint-node", source_node=source_node),
    ]}


def _create_node_modal_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:create-node-modal"
    nodes = [
        _slot("slot:create-node-type", "create node type", ""),
        _slot("slot:create-node-category", "create node category", "filter"),
        _slot("slot:create-node-inputs", "create node inputs", ""),
        _slot("slot:create-node-outputs", "create node outputs", ""),
        _el(
            root_id,
            "div",
            "",
            cls="ah-create-node-backdrop-node",
            action="create-node.cancel",
            children=["ui:grandmap:create-node-panel"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:create-node-panel",
            "div",
            "",
            cls="ah-create-node-panel-node",
            role="dialog",
            action="create-node.noop",
            data_attrs={
                "data-no-pan": "true",
                "aria-modal": "true",
                "aria-label": "Create custom node",
            },
            children=[
                "ui:grandmap:create-node-title",
                "ui:grandmap:create-node-type-field",
                "ui:grandmap:create-node-category-field",
                "ui:grandmap:create-node-inputs-field",
                "ui:grandmap:create-node-outputs-field",
                "ui:grandmap:create-node-actions",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:create-node-title", "div", "Create custom node", cls="ah-create-node-title-node", source_node=source_node),
        *_create_node_field(
            "type",
            "Type ID",
            "slot:create-node-type",
            "create-node.type.update",
            "my.filter",
            source_node,
            submit_action="create-node.create",
        ),
        *_create_node_field(
            "category",
            "Category",
            "slot:create-node-category",
            "create-node.category.update",
            "filter",
            source_node,
            submit_action="create-node.create",
        ),
        *_create_node_field(
            "inputs",
            "Inputs (comma)",
            "slot:create-node-inputs",
            "create-node.inputs.update",
            "walls, view",
            source_node,
            submit_action="create-node.create",
        ),
        *_create_node_field(
            "outputs",
            "Outputs (comma)",
            "slot:create-node-outputs",
            "create-node.outputs.update",
            "filtered",
            source_node,
            submit_action="create-node.create",
        ),
        _el(
            "ui:grandmap:create-node-actions",
            "div",
            "",
            cls="ah-create-node-actions-node",
            children=[
                "ui:grandmap:create-node-cancel",
                "ui:grandmap:create-node-create",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:create-node-cancel",
            "button",
            "Cancel",
            cls="ah-create-node-cancel-node",
            action="create-node.cancel",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:create-node-create",
            "button",
            "Create",
            cls="ah-create-node-create-node",
            action="create-node.create",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _create_node_field(
    key: str,
    label: str,
    bind: str,
    action: str,
    placeholder: str,
    source_node: dict[str, Any],
    *,
    submit_action: str = "",
) -> list[dict[str, Any]]:
    field_id = f"ui:grandmap:create-node-{key}-field"
    label_id = f"ui:grandmap:create-node-{key}-label"
    input_id = f"ui:grandmap:create-node-{key}-input"
    return [
        _el(
            field_id,
            "div",
            "",
            cls="ah-create-node-field-node",
            children=[label_id, input_id],
            source_node=source_node,
        ),
        _el(label_id, "div", label.upper(), cls="ah-create-node-field-label-node", source_node=source_node),
        _el(
            input_id,
            "input",
            "",
            cls="ah-create-node-input-node",
            bind=bind,
            action=action,
            input_type="text",
            submit_action=submit_action,
            placeholder=placeholder,
            test_id=f"create-node-{key}-input",
            source_node=source_node,
        ),
    ]


def _ai_node_modal_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:ai-node-modal"
    examples = [
        "Keep only walls taller than 3 meters",
        "Count elements grouped by level",
        "Round every number in a list to 2 decimals",
        "Filter rooms whose area is below a threshold",
    ]
    example_ids = [f"ui:grandmap:ai-node-example-{i}" for i, _ in enumerate(examples)]
    nodes = [
        _slot("slot:ai-node-desc", "ai node description", ""),
        _slot("slot:ai-node-phase", "ai node phase", "idle"),
        _slot("slot:ai-node-can-draft", "ai node can draft", "false"),
        _slot("slot:ai-node-error", "ai node error", ""),
        _slot("slot:ai-node-result-title", "ai node result title", ""),
        _slot("slot:ai-node-result-type", "ai node result type", ""),
        _slot("slot:ai-node-result-category", "ai node result category", "transform"),
        _slot("slot:ai-node-result-description", "ai node result description", ""),
        _slot("slot:ai-node-result-inputs", "ai node result inputs", "none"),
        _slot("slot:ai-node-result-outputs", "ai node result outputs", "none"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-ai-node-backdrop-node",
            action="ai-node.close",
            children=["ui:grandmap:ai-node-panel"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-panel",
            "div",
            "",
            cls="ah-ai-node-panel-node",
            action="ai-node.noop",
            data_attrs={
                "data-no-pan": "true",
                "aria-modal": "true",
                "aria-labelledby": "lm-ai-node-modal-title",
            },
            children=[
                "ui:grandmap:ai-node-header",
                "ui:grandmap:ai-node-copy",
                "ui:grandmap:ai-node-idle",
                "ui:grandmap:ai-node-working",
                "ui:grandmap:ai-node-done",
                "ui:grandmap:ai-node-error",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-header",
            "div",
            "",
            cls="ah-ai-node-header-node",
            children=[
                "ui:grandmap:ai-node-glyph",
                "ui:grandmap:ai-node-title",
                "ui:grandmap:ai-node-spacer",
                "ui:grandmap:ai-node-close",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:ai-node-glyph", "span", "+", cls="ah-ai-node-glyph-node", source_node=source_node),
        _el("ui:grandmap:ai-node-title", "span", "Create a node with AI", cls="ah-ai-node-title-node", source_node=source_node),
        _el("ui:grandmap:ai-node-spacer", "div", "", cls="ah-ai-node-spacer-node", source_node=source_node),
        _el(
            "ui:grandmap:ai-node-close",
            "button",
            "x",
            cls="ah-ai-node-close-node",
            action="ai-node.close",
            disabled_bind="slot:ai-node-phase",
            disabled_value="working",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-copy",
            "div",
            "Describe the node in plain words. The AI designs its typed inputs, outputs and logic, then registers it in your library.",
            cls="ah-ai-node-copy-node",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-idle",
            "div",
            "",
            cls="ah-ai-node-section-node ah-ai-node-idle-node",
            visible_when={"bind": "slot:ai-node-phase", "value": "idle"},
            children=[
                "ui:grandmap:ai-node-desc-input",
                "ui:grandmap:ai-node-examples",
                "ui:grandmap:ai-node-idle-actions",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-desc-input",
            "textarea",
            "",
            cls="ah-ai-node-desc-node",
            bind="slot:ai-node-desc",
            action="ai-node.desc.update",
            placeholder="e.g. keep only the walls taller than 3 metres",
            test_id="ai-node-desc-input",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-examples",
            "div",
            "",
            cls="ah-ai-node-examples-node",
            children=example_ids,
            source_node=source_node,
        ),
        *[
            _el(
                example_id,
                "button",
                example,
                cls="ah-ai-node-example-node",
                action="ai-node.example.pick",
                args={"desc": example},
                source_node=source_node,
            )
            for example_id, example in zip(example_ids, examples)
        ],
        _el(
            "ui:grandmap:ai-node-idle-actions",
            "div",
            "",
            cls="ah-ai-node-actions-node",
            children=[
                "ui:grandmap:ai-node-shortcut",
                "ui:grandmap:ai-node-cancel",
                "ui:grandmap:ai-node-draft",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:ai-node-shortcut", "span", "cmd/ctrl enter to draft", cls="ah-ai-node-shortcut-node", source_node=source_node),
        _el("ui:grandmap:ai-node-cancel", "button", "Cancel", cls="ah-ai-node-secondary-node", action="ai-node.close", source_node=source_node),
        _el(
            "ui:grandmap:ai-node-draft",
            "button",
            "Draft node",
            cls="ah-ai-node-primary-node",
            action="ai-node.generate",
            disabled_bind="slot:ai-node-can-draft",
            disabled_value="false",
            source_node=source_node,
        ),
        _ai_node_working_section(source_node),
        _ai_node_done_section(source_node),
        _ai_node_error_section(source_node),
    ]
    expanded_nodes: list[dict[str, Any]] = []
    for node in nodes:
        child_nodes = node.pop("_children", [])
        expanded_nodes.append(node)
        expanded_nodes.extend(child_nodes)
    nodes = expanded_nodes
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _ai_node_working_section(source_node: dict[str, Any]) -> dict[str, Any]:
    dot_ids = [f"ui:grandmap:ai-node-working-dot-{i}" for i in range(3)]
    return _el(
        "ui:grandmap:ai-node-working",
        "div",
        "",
        cls="ah-ai-node-section-node ah-ai-node-working-node",
        visible_when={"bind": "slot:ai-node-phase", "value": "working"},
        children=[
            "ui:grandmap:ai-node-working-dots",
            "ui:grandmap:ai-node-working-label",
            "ui:grandmap:ai-node-working-desc",
        ],
        source_node=source_node,
    ) | {"_children": [
        _el("ui:grandmap:ai-node-working-dots", "div", "", cls="ah-ai-node-working-dots-node", children=dot_ids, source_node=source_node),
        *[
            _el(dot_id, "span", "", cls=f"ah-ai-node-working-dot-node ah-ai-node-working-dot-{i}-node", source_node=source_node)
            for i, dot_id in enumerate(dot_ids)
        ],
        _el("ui:grandmap:ai-node-working-label", "div", "Designing your node...", cls="ah-ai-node-working-label-node", source_node=source_node),
        _el("ui:grandmap:ai-node-working-desc", "div", "", cls="ah-ai-node-working-desc-node", bind="slot:ai-node-desc", source_node=source_node),
    ]}


def _ai_node_done_section(source_node: dict[str, Any]) -> dict[str, Any]:
    return _el(
        "ui:grandmap:ai-node-done",
        "div",
        "",
        cls="ah-ai-node-section-node ah-ai-node-done-node",
        visible_when={"bind": "slot:ai-node-phase", "value": "done"},
        children=[
            "ui:grandmap:ai-node-result-card",
            "ui:grandmap:ai-node-done-actions",
        ],
        source_node=source_node,
    ) | {"_children": [
        _el(
            "ui:grandmap:ai-node-result-card",
            "div",
            "",
            cls="ah-ai-node-result-card-node",
            children=[
                "ui:grandmap:ai-node-result-header",
                "ui:grandmap:ai-node-result-description",
                "ui:grandmap:ai-node-result-ports",
                "ui:grandmap:ai-node-result-type",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:ai-node-result-header",
            "div",
            "",
            cls="ah-ai-node-result-header-node",
            children=[
                "ui:grandmap:ai-node-result-glyph",
                "ui:grandmap:ai-node-result-title",
                "ui:grandmap:ai-node-result-category",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:ai-node-result-glyph", "span", "+", cls="ah-ai-node-result-glyph-node", source_node=source_node),
        _el("ui:grandmap:ai-node-result-title", "span", "", cls="ah-ai-node-result-title-node", bind="slot:ai-node-result-title", source_node=source_node),
        _el("ui:grandmap:ai-node-result-category", "span", "", cls="ah-ai-node-result-category-node", bind="slot:ai-node-result-category", source_node=source_node),
        _el("ui:grandmap:ai-node-result-description", "div", "", cls="ah-ai-node-result-description-node", bind="slot:ai-node-result-description", source_node=source_node),
        _el(
            "ui:grandmap:ai-node-result-ports",
            "div",
            "",
            cls="ah-ai-node-result-ports-node",
            children=[
                "ui:grandmap:ai-node-result-inputs",
                "ui:grandmap:ai-node-result-outputs",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:ai-node-result-inputs", "span", "in: ", cls="ah-ai-node-result-inputs-node", bind="slot:ai-node-result-inputs", source_node=source_node),
        _el("ui:grandmap:ai-node-result-outputs", "span", "out: ", cls="ah-ai-node-result-outputs-node", bind="slot:ai-node-result-outputs", source_node=source_node),
        _el("ui:grandmap:ai-node-result-type", "div", "", cls="ah-ai-node-result-type-node", bind="slot:ai-node-result-type", source_node=source_node),
        _el(
            "ui:grandmap:ai-node-done-actions",
            "div",
            "",
            cls="ah-ai-node-actions-node",
            children=[
                "ui:grandmap:ai-node-create-another",
                "ui:grandmap:ai-node-add",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:ai-node-create-another", "button", "Create another", cls="ah-ai-node-secondary-node", action="ai-node.reset", source_node=source_node),
        _el("ui:grandmap:ai-node-add", "button", "Add to canvas", cls="ah-ai-node-primary-node", action="ai-node.add", source_node=source_node),
    ]}


def _ai_node_error_section(source_node: dict[str, Any]) -> dict[str, Any]:
    return _el(
        "ui:grandmap:ai-node-error",
        "div",
        "",
        cls="ah-ai-node-section-node ah-ai-node-error-section-node",
        visible_when={"bind": "slot:ai-node-phase", "value": "error"},
        children=[
            "ui:grandmap:ai-node-error-message",
            "ui:grandmap:ai-node-error-actions",
        ],
        source_node=source_node,
    ) | {"_children": [
        _el("ui:grandmap:ai-node-error-message", "div", "", cls="ah-ai-node-error-message-node", bind="slot:ai-node-error", source_node=source_node),
        _el(
            "ui:grandmap:ai-node-error-actions",
            "div",
            "",
            cls="ah-ai-node-actions-node",
            children=[
                "ui:grandmap:ai-node-error-cancel",
                "ui:grandmap:ai-node-error-try",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:ai-node-error-cancel", "button", "Cancel", cls="ah-ai-node-secondary-node", action="ai-node.close", source_node=source_node),
        _el("ui:grandmap:ai-node-error-try", "button", "Try again", cls="ah-ai-node-primary-node", action="ai-node.reset", source_node=source_node),
    ]}


def _first_run_profile_surface(path: Path, surface: str) -> dict[str, Any]:
    try:
        ui_nodes = _load_ui_nodes(path)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": f"{type(ex).__name__}: {ex}",
        }
    source_id = "ui_modal_system"
    if source_id not in ui_nodes:
        return {
            "ok": False,
            "surface": surface,
            "source": str(path),
            "error": "missing Grand Map UI node: " + source_id,
        }

    source_node = ui_nodes[source_id]
    root_id = "ui:grandmap:first-run-profile"
    role_options = ["", "Architect", "Engineer", "BIM Manager", "Designer", "Project Manager", "Drafter", "Student", "Other"]
    discipline_options = ["", "Architecture", "Structural", "MEP", "Civil", "Interior Design", "Landscape", "Urban Design", "Other"]
    nodes = [
        _slot("slot:first-run-firm", "firm", ""),
        _slot("slot:first-run-role", "role", ""),
        _slot("slot:first-run-discipline", "discipline", ""),
        _slot("slot:first-run-saving", "saving", "false"),
        _slot("slot:first-run-save-disabled", "save disabled", "true"),
        _slot("slot:first-run-save-label", "save label", "Save"),
        _el(
            root_id,
            "div",
            "",
            cls="ah-first-run-backdrop-node",
            children=["ui:grandmap:first-run-panel"],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:first-run-panel",
            "div",
            "",
            cls="ah-first-run-panel-node",
            role="dialog",
            data_attrs={
                "data-no-pan": "true",
                "aria-modal": "true",
                "aria-label": "Welcome",
            },
            children=[
                "ui:grandmap:first-run-wordmark",
                "ui:grandmap:first-run-title",
                "ui:grandmap:first-run-copy",
                "ui:grandmap:first-run-firm-field",
                "ui:grandmap:first-run-role-field",
                "ui:grandmap:first-run-discipline-field",
                "ui:grandmap:first-run-actions",
            ],
            source_node=source_node,
        ),
        _el("ui:grandmap:first-run-wordmark", "div", "", cls="ah-first-run-wordmark-node", render_slot="slot:first-run-wordmark", source_node=source_node),
        _el("ui:grandmap:first-run-title", "div", "Welcome", cls="ah-first-run-title-node", source_node=source_node),
        _el(
            "ui:grandmap:first-run-copy",
            "div",
            "A couple of details about your practice - tailors host suggestions and defaults. Change them any time in Settings.",
            cls="ah-first-run-copy-node",
            source_node=source_node,
        ),
        *_first_run_input_field("firm", "Firm / company", "slot:first-run-firm", "first-run.firm.update", "e.g. Foster + Partners", source_node),
        *_first_run_select_field("role", "Your role", "slot:first-run-role", "first-run.role.update", role_options, source_node),
        *_first_run_select_field("discipline", "Discipline", "slot:first-run-discipline", "first-run.discipline.update", discipline_options, source_node),
        _el(
            "ui:grandmap:first-run-actions",
            "div",
            "",
            cls="ah-first-run-actions-node",
            children=[
                "ui:grandmap:first-run-skip",
                "ui:grandmap:first-run-save",
            ],
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:first-run-skip",
            "button",
            "Skip",
            cls="ah-first-run-skip-node",
            action="first-run.skip",
            disabled_bind="slot:first-run-saving",
            disabled_value="true",
            source_node=source_node,
        ),
        _el(
            "ui:grandmap:first-run-save",
            "button",
            "",
            cls="ah-first-run-save-node",
            bind="slot:first-run-save-label",
            action="first-run.save",
            disabled_bind="slot:first-run-save-disabled",
            disabled_value="true",
            source_node=source_node,
        ),
    ]
    return {
        "ok": True,
        "surface": surface,
        "source": str(path),
        "root_id": root_id,
        "nodes": nodes,
        "wires": _child_wires(nodes),
        "source_node_ids": [source_id],
    }


def _first_run_input_field(
    key: str,
    label: str,
    bind: str,
    action: str,
    placeholder: str,
    source_node: dict[str, Any],
) -> list[dict[str, Any]]:
    field_id = f"ui:grandmap:first-run-{key}-field"
    label_id = f"ui:grandmap:first-run-{key}-label"
    input_id = f"ui:grandmap:first-run-{key}-input"
    return [
        _el(field_id, "div", "", cls="ah-first-run-field-node", children=[label_id, input_id], source_node=source_node),
        _el(label_id, "div", label.upper(), cls="ah-first-run-field-label-node", source_node=source_node),
        _el(
            input_id,
            "input",
            "",
            cls="ah-first-run-input-node",
            bind=bind,
            action=action,
            input_type="text",
            placeholder=placeholder,
            test_id=f"first-run-{key}-input",
            source_node=source_node,
        ),
    ]


def _first_run_select_field(
    key: str,
    label: str,
    bind: str,
    action: str,
    options: list[str],
    source_node: dict[str, Any],
) -> list[dict[str, Any]]:
    field_id = f"ui:grandmap:first-run-{key}-field"
    label_id = f"ui:grandmap:first-run-{key}-label"
    select_id = f"ui:grandmap:first-run-{key}-select"
    option_ids = [f"ui:grandmap:first-run-{key}-option-{i}" for i, _ in enumerate(options)]
    return [
        _el(field_id, "div", "", cls="ah-first-run-field-node", children=[label_id, select_id], source_node=source_node),
        _el(label_id, "div", label.upper(), cls="ah-first-run-field-label-node", source_node=source_node),
        _el(
            select_id,
            "select",
            "",
            cls="ah-first-run-select-node",
            bind=bind,
            action=action,
            children=option_ids,
            test_id=f"first-run-{key}-select",
            source_node=source_node,
        ),
        *[
            _el(
                option_id,
                "option",
                option if option else "- select -",
                option_value=option,
                source_node=source_node,
            )
            for option_id, option in zip(option_ids, options)
        ],
    ]


def _load_ui_nodes(path: Path) -> dict[str, dict[str, Any]]:
    return _load_domain_nodes(path, "ui")


def _load_domain_nodes(path: Path, key: str) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Grand Map root must be a domain list")
    domain = next((d for d in data if d.get("key") == key), None)
    if not domain:
        raise ValueError(f"Grand Map has no {key} domain")
    out: dict[str, dict[str, Any]] = {}
    for node in domain.get("nodes") or []:
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            out[node_id] = node
    return out


def _title(node: dict[str, Any]) -> str:
    return str(node.get("title") or node.get("id") or "")


def _child_wires(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wires: list[dict[str, Any]] = []
    for node in nodes:
        for child_id in node.get("data", {}).get("children", []) or []:
            wires.append({
                "id": f"w:{node['id']}->{child_id}",
                "from": {"node": node["id"], "port": "child"},
                "to": {"node": child_id, "port": "parent"},
            })
    return wires


def _el(
    node_id: str,
    tag: str,
    text: str,
    *,
    cls: str = "",
    children: list[str] | None = None,
    role: str = "",
    tab_index: int | None = None,
    bind: str = "",
    action: str = "",
    args: dict[str, Any] | None = None,
    double_action: str = "",
    double_args: dict[str, Any] | None = None,
    key_actions: dict[str, Any] | None = None,
    draggable: bool | None = None,
    drag_mime: str = "",
    drag_payload: dict[str, Any] | None = None,
    active_bind: str = "",
    active_value: str = "",
    state_bind: str = "",
    disabled_bind: str = "",
    disabled_value: str = "",
    hidden_bind: str = "",
    hidden_value: str = "",
    text_cases: dict[str, Any] | None = None,
    input_type: str = "",
    input_min: Any = None,
    input_max: Any = None,
    input_step: Any = None,
    rows: int | None = None,
    auto_grow: bool = False,
    auto_grow_max: int | None = None,
    option_value: Any = None,
    visible_when: dict[str, Any] | None = None,
    value_cast: str = "",
    multiple: bool = False,
    placeholder: str = "",
    src_bind: str = "",
    href_bind: str = "",
    alt_bind: str = "",
    alt: str = "",
    surface_ref: str = "",
    submit_action: str = "",
    test_id: str = "",
    render_slot: str = "",
    style: dict[str, Any] | None = None,
    data_attrs: dict[str, Any] | None = None,
    title: str = "",
    stop_click: bool | None = None,
    source_node: dict[str, Any] | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"tag": tag}
    if text:
        data["text"] = text
    if cls:
        data["cls"] = cls
    if role:
        data["role"] = role
    if tab_index is not None:
        data["tab_index"] = tab_index
    if children:
        data["children"] = children
    if bind:
        data["bind"] = bind
    if action:
        data["action"] = action
        data["args"] = dict(args or {})
    if double_action:
        data["double_action"] = double_action
        data["double_args"] = dict(double_args or {})
    if key_actions:
        data["key_actions"] = dict(key_actions)
    if draggable is not None:
        data["draggable"] = bool(draggable)
    if drag_mime:
        data["drag_mime"] = drag_mime
    if drag_payload is not None:
        data["drag_payload"] = dict(drag_payload)
    if active_bind:
        data["active_bind"] = active_bind
        data["active_value"] = active_value
    if state_bind:
        data["state_bind"] = state_bind
    if disabled_bind:
        data["disabled_bind"] = disabled_bind
        data["disabled_value"] = disabled_value
    if hidden_bind:
        data["hidden_bind"] = hidden_bind
        data["hidden_value"] = hidden_value
    if text_cases:
        data["text_cases"] = text_cases
    if input_type:
        data["input_type"] = input_type
    if input_min is not None:
        data["input_min"] = input_min
    if input_max is not None:
        data["input_max"] = input_max
    if input_step is not None:
        data["input_step"] = input_step
    if rows is not None:
        data["rows"] = rows
    if auto_grow:
        data["auto_grow"] = True
    if auto_grow_max is not None:
        data["auto_grow_max"] = auto_grow_max
    if option_value is not None:
        data["option_value"] = option_value
    if visible_when:
        data["visible_when"] = dict(visible_when)
    if value_cast:
        data["value_cast"] = value_cast
    if multiple:
        data["multiple"] = True
    if placeholder:
        data["placeholder"] = placeholder
    if src_bind:
        data["src_bind"] = src_bind
    if href_bind:
        data["href_bind"] = href_bind
    if alt_bind:
        data["alt_bind"] = alt_bind
    if alt:
        data["alt"] = alt
    if surface_ref:
        data["surface_ref"] = surface_ref
    if submit_action:
        data["submit_action"] = submit_action
    if test_id:
        data["test_id"] = test_id
    if render_slot:
        data["render_slot"] = render_slot
    if style:
        data["style"] = dict(style)
    if data_attrs is not None:
        data["data_attrs"] = dict(data_attrs)
    if title:
        data["title"] = title
    if stop_click is not None:
        data["stop_click"] = bool(stop_click)
    if source_node is not None:
        data["source_map_node"] = source_node.get("id")
        data["source_title"] = source_node.get("title")
        data["source_status"] = source_node.get("status")
    params = _params_from_data(data)
    return {
        "id": node_id,
        "type": "ui.element",
        "data": data,
        "config": _config_from_params(params),
        "config_schema": _config_schema_from_params(params),
        "params": params,
        "cat": "ui",
        "x": 0,
        "y": 0,
        "w": 168,
        "h": 66,
        "title": text or tag,
        "sub": "ui.element",
        "ins": [{"id": "parent", "label": "in", "t": "ui"}],
        "outs": [{"id": "child", "label": "out", "t": "ui"}],
    }


def _slot(node_id: str, title: str, value: Any) -> dict[str, Any]:
    params = [_param("value", value, label="value")]
    return {
        "id": node_id,
        "type": "data.constant",
        "data": {"value": value},
        "config": {"value": value},
        "config_schema": {"value": {"type": _schema_type(value), "default": value}},
        "params": params,
        "cat": "data",
        "x": 0,
        "y": 0,
        "w": 168,
        "h": 66,
        "title": title,
        "sub": "live slot",
        "ins": [],
        "outs": [{"id": "value", "label": "value", "t": "any"}],
    }


def _with_parameter_nodes(payload: dict[str, Any]) -> dict[str, Any]:
    # This builder is a legacy bridge over typed LM_GRAPH UI nodes. Keep it
    # visibly non-authoritative until every served surface is consumed by the
    # Universal Cell application graph.
    payload.setdefault("authority", "legacy-handbuilt-grand-map-ui-projection")
    payload.setdefault("authority_status", "superseded_migration_evidence")
    payload.setdefault("promotion_allowed", False)
    payload.setdefault(
        "superseded_by",
        "10.PRODUCT/13.NODE-LANGUAGE Universal Cell authority",
    )
    if not payload.get("ok") or not isinstance(payload.get("nodes"), list):
        return payload

    nodes = payload["nodes"]
    wires = payload.setdefault("wires", [])
    if not isinstance(wires, list):
        wires = []
        payload["wires"] = wires

    existing_node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    existing_wire_ids = {str(wire.get("id")) for wire in wires if wire.get("id")}
    additions: list[dict[str, Any]] = []

    for node in list(nodes):
        node_data = node.get("data", {})
        if isinstance(node_data, dict) and node_data.get("role") == "parameter":
            continue
        params = node.get("params")
        if not isinstance(params, list) or not params:
            continue

        data = node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            node["data"] = data

        param_node_ids: list[str] = []
        for param in params:
            if not isinstance(param, dict) or not param.get("k"):
                continue
            param_node_id = _param_node_id(str(node["id"]), str(param["k"]))
            param_node_ids.append(param_node_id)
            if param_node_id not in existing_node_ids:
                additions.append(_parameter_node(node, param, param_node_id))
                existing_node_ids.add(param_node_id)

            wire_id = f"w:param:{node['id']}->{param_node_id}"
            if wire_id not in existing_wire_ids:
                wires.append({
                    "id": wire_id,
                    "from": {"node": node["id"], "port": f"param:{param['k']}"},
                    "to": {"node": param_node_id, "port": "owner"},
                })
                existing_wire_ids.add(wire_id)

        if param_node_ids:
            data["param_nodes"] = param_node_ids
            child_ids = data.get("children") if isinstance(data.get("children"), list) else []
            existing_group_ids = (
                data.get("group_nodes") if isinstance(data.get("group_nodes"), list) else []
            )
            data["group_nodes"] = list(dict.fromkeys(
                list(existing_group_ids) + list(child_ids) + param_node_ids
            ))

        action_node_ids: list[str] = []
        if node.get("type") == "ui.element":
            for action_key, args_key in (
                ("action", "args"),
                ("submit_action", "args"),
                ("double_action", "double_args"),
            ):
                action_value = data.get(action_key)
                if not action_value:
                    continue
                owner_id = str(node["id"])
                action_node_id = _action_node_id(owner_id, action_key, str(action_value))
                action_param_node_id = _param_node_id(owner_id, action_key)
                action_node_ids.append(action_node_id)

                action_node = _action_behavior_node(
                    node,
                    action_key,
                    str(action_value),
                    data.get(args_key, {}),
                    action_param_node_id,
                    action_node_id,
                )
                if action_node_id not in existing_node_ids:
                    additions.append(action_node)
                    existing_node_ids.add(action_node_id)

                for action_param in action_node.get("params", []):
                    if not isinstance(action_param, dict) or not action_param.get("k"):
                        continue
                    action_param_id = _param_node_id(action_node_id, str(action_param["k"]))
                    if action_param_id not in existing_node_ids:
                        additions.append(_parameter_node(action_node, action_param, action_param_id))
                        existing_node_ids.add(action_param_id)
                    action_param_wire_id = f"w:param:{action_node_id}->{action_param_id}"
                    if action_param_wire_id not in existing_wire_ids:
                        wires.append({
                            "id": action_param_wire_id,
                            "from": {"node": action_node_id, "port": f"param:{action_param['k']}"},
                            "to": {"node": action_param_id, "port": "owner"},
                        })
                        existing_wire_ids.add(action_param_wire_id)

                owner_wire_id = f"w:ui-action:{_safe_param_key(owner_id)}:{_safe_param_key(action_key)}:owner"
                if owner_wire_id not in existing_wire_ids:
                    wires.append({
                        "id": owner_wire_id,
                        "from": {"node": owner_id, "port": f"action:{action_key}"},
                        "to": {"node": action_node_id, "port": "owner"},
                        "data": {
                            "role": "ui_action_relation",
                            "relation": "emits_behavior",
                            "owner": owner_id,
                            "action_node": action_node_id,
                            "action_key": action_key,
                            "action": str(action_value),
                        },
                    })
                    existing_wire_ids.add(owner_wire_id)

                behavior_param_wire_id = f"w:ui-action:{_safe_param_key(owner_id)}:{_safe_param_key(action_key)}:param"
                if behavior_param_wire_id not in existing_wire_ids:
                    wires.append({
                        "id": behavior_param_wire_id,
                        "from": {"node": action_param_node_id, "port": "value"},
                        "to": {"node": action_node_id, "port": "action_param"},
                        "data": {
                            "role": "ui_action_parameter_relation",
                            "relation": "configures_behavior",
                            "owner": owner_id,
                            "action_node": action_node_id,
                            "parameter_node": action_param_node_id,
                            "action_key": action_key,
                            "action": str(action_value),
                        },
                    })
                    existing_wire_ids.add(behavior_param_wire_id)

        if action_node_ids:
            data["action_nodes"] = list(dict.fromkeys(
                list(data.get("action_nodes") if isinstance(data.get("action_nodes"), list) else [])
                + action_node_ids
            ))
            data["group_nodes"] = list(dict.fromkeys(
                list(data.get("group_nodes") if isinstance(data.get("group_nodes"), list) else [])
                + action_node_ids
            ))

        binding_wire_ids: list[str] = []
        for binding_key, source_id in _ui_binding_refs(data):
            owner_id = str(node["id"])
            wire_id = (
                f"w:ui-binding:{_safe_param_key(str(source_id))}"
                f"->{_safe_param_key(owner_id)}:{_safe_param_key(binding_key)}"
            )
            binding_wire_ids.append(wire_id)
            if wire_id not in existing_wire_ids:
                wires.append({
                    "id": wire_id,
                    "from": {"node": str(source_id), "port": "value"},
                    "to": {"node": owner_id, "port": f"binding:{binding_key}"},
                    "data": {
                        "role": "ui_binding_relation",
                        "relation": f"drives_{binding_key}",
                        "source_node": str(source_id),
                        "target_node": owner_id,
                        "binding_key": binding_key,
                        "value_key": binding_key,
                    },
                })
                existing_wire_ids.add(wire_id)

        if binding_wire_ids:
            data["binding_wires"] = list(dict.fromkeys(
                list(data.get("binding_wires") if isinstance(data.get("binding_wires"), list) else [])
                + binding_wire_ids
            ))

    nodes.extend(additions)
    return payload


def _parameter_node(owner: dict[str, Any], param: dict[str, Any], node_id: str) -> dict[str, Any]:
    owner_id = str(owner["id"])
    key = str(param["k"])
    value = param.get("v")
    value_type = str(param.get("type") or _param_type(value))
    label = str(param.get("label") or key.replace("_", " "))
    data = {
        "role": "parameter",
        "adapts_to": str(owner.get("type", "")),
        "capabilities": ["store_value", "drive_owner_config"],
        "owner": owner_id,
        "key": key,
        "label": label,
        "value": value,
        "value_type": value_type,
    }
    params = [
        _param("owner", owner_id, label="owner"),
        _param("key", key, label="key"),
        _param("value", value, label="value"),
    ]
    return {
        "id": node_id,
        "type": "stem.node",
        "data": data,
        "config": _config_from_params(params),
        "config_schema": _config_schema_from_params(params),
        "params": params,
        "cat": "param",
        "x": owner.get("x", 0),
        "y": owner.get("y", 0),
        "w": 168,
        "h": 54,
        "title": f"{owner.get('title') or owner_id}.{key}",
        "sub": "parameter node",
        "ins": [{"id": "owner", "label": "owner", "t": "node"}],
        "outs": [{"id": "value", "label": "value", "t": value_type}],
    }


def _action_behavior_node(
    owner: dict[str, Any],
    action_key: str,
    action: str,
    args: Any,
    action_param_node_id: str,
    node_id: str,
) -> dict[str, Any]:
    owner_id = str(owner["id"])
    args_value = args if isinstance(args, (dict, list)) else {}
    args_json = json.dumps(args_value, sort_keys=True)
    params = [
        _param("owner", owner_id, label="owner"),
        _param("action_key", action_key, label="action key"),
        _param("action", action, label="action"),
        _param("action_param_node_id", action_param_node_id, label="action param node"),
        _param("args_json", args_json, label="args json"),
        _param("event_count", 0, label="event count"),
    ]
    return {
        "id": node_id,
        "type": "stem.node",
        "kind": "behavior",
        "data": {
            "role": "ui_action",
            "owner": owner_id,
            "action_key": action_key,
            "action": action,
            "action_param_node_id": action_param_node_id,
            "args": args_value,
            "args_json": args_json,
            "event_count": 0,
            "capabilities": ["emit_event", "drive_behavior", "audit", "presentation_trigger"],
        },
        "config": _config_from_params(params),
        "config_schema": _config_schema_from_params(params),
        "params": params,
        "cat": "action",
        "x": owner.get("x", 0),
        "y": owner.get("y", 0),
        "w": 184,
        "h": 66,
        "title": f"{owner.get('title') or owner_id}.{action_key}",
        "sub": "ui action behavior node",
        "ins": [
            {"id": "owner", "label": "owner", "t": "node"},
            {"id": "action_param", "label": "action param", "t": "text"},
            {"id": "args", "label": "args", "t": "object"},
        ],
        "outs": [
            {"id": "event", "label": "event", "t": "event"},
            {"id": "command", "label": "command", "t": "command"},
        ],
    }


def _action_node_id(owner_id: str, action_key: str, action: str) -> str:
    return f"action:{_safe_param_key(owner_id)}:{_safe_param_key(action_key)}:{_safe_param_key(action)}"


def _ui_binding_refs(data: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for key in (
        "bind",
        "active_bind",
        "state_bind",
        "disabled_bind",
        "hidden_bind",
        "src_bind",
        "href_bind",
        "alt_bind",
    ):
        value = data.get(key)
        if isinstance(value, str) and value:
            refs.append((key, value))

    text_cases = data.get("text_cases")
    if isinstance(text_cases, dict):
        value = text_cases.get("bind")
        if isinstance(value, str) and value:
            refs.append(("text_cases.bind", value))

    visible_when = data.get("visible_when")
    if isinstance(visible_when, dict):
        value = visible_when.get("bind")
        if isinstance(value, str) and value:
            refs.append(("visible_when.bind", value))

    return list(dict.fromkeys(refs))


def _param_node_id(owner_id: str, key: str) -> str:
    return f"param:{owner_id}:{_safe_param_key(key)}"


def _safe_param_key(key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in key)
    return safe.strip("-") or "value"


def _params_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [_param(key, value) for key, value in data.items()]


def _param(key: str, value: Any, *, label: str | None = None) -> dict[str, Any]:
    return {
        "k": key,
        "label": label or key.replace("_", " "),
        "type": _param_type(value),
        "v": value,
    }


def _config_from_params(params: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(param["k"]): param.get("v") for param in params if param.get("k")}


def _config_schema_from_params(params: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(param["k"]): {
            "type": _schema_type(param.get("v")),
            "default": param.get("v"),
            "description": f"Editable UI node parameter: {param.get('label') or param['k']}",
        }
        for param in params
        if param.get("k")
    }


def _param_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "json"
    return "text"


def _schema_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


__all__ = ["default_grand_map_path", "grand_map_ui_surface"]
