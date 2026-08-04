"""Project clean scope lenses into the existing graph-native visual contract."""
from __future__ import annotations

from typing import Mapping

from .clean_scope_interactions import CleanScopeInteractions
from .clean_visual_authority import (
    CleanVisualSystem,
    render_clean_visual_template,
)
from .unified_authority import CallerCommandCapability, UnifiedAuthority


def _port_side(role: str) -> str:
    if role == "source":
        return "source"
    return "target"


def _port_name(port: Mapping[str, object]) -> str:
    connection = port.get("connection")
    if type(connection) is str and connection.strip():
        return connection.strip()
    role = port.get("participant_role")
    return str(role) if role is not None else "link"


def _wire_color(properties: Mapping[str, object]) -> str:
    value = properties.get("color")
    if type(value) is str and value.strip():
        return value
    return "#5ac8fa"


def _node_color(node: Mapping[str, object]) -> str:
    lifecycle = node.get("lifecycle")
    if lifecycle == "published":
        return "#7bd389"
    if lifecycle == "shared":
        return "#f2c14e"
    return "#d97757"


def _node_positions(nodes: list[dict[str, object]]) -> None:
    columns = 3
    x0 = 96
    y0 = 88
    dx = 280
    dy = 180
    for index, node in enumerate(nodes):
        node["x"] = x0 + (index % columns) * dx
        node["y"] = y0 + (index // columns) * dy


def _toolbar_projection(projection: Mapping[str, object]) -> dict[str, object]:
    return {
        "trail": (
            {
                "root": projection["scope"]["current"],
                "label": projection["scope"]["current_label"],
                "key": "toolbar:scope:item:%s" % projection["scope"]["current"],
                "current": True,
                "show_divider": False,
            },
        ),
        "controls": (),
        "zoom_percent": round(float(projection["viewport"]["zoom"]) * 100),
        "selection_count": len(projection["selection"]),
    }


def _library_projection(catalog: list[dict[str, object]]) -> dict[str, object]:
    return {
        "title": "Node Library",
        "count_text": "%s node%s" % (
            len(catalog),
            "" if len(catalog) == 1 else "s",
        ),
    }


def _primitive_projection() -> dict[str, object]:
    return {
        "id": "primitive:cell",
        "label": "Cell",
        "kicker": "Physical floor",
        "fields": ["identity", "link 0", "link 1", "atom"],
        "visible": False,
        "selected": False,
    }


def _section_projection(section_id: str, label: str, definitions: list[str]) -> dict[str, object]:
    return {
        "id": section_id,
        "label": label,
        "definitions": definitions,
    }


def _catalog_projection(items: list[dict[str, object]]) -> list[dict[str, object]]:
    projected = []
    for item in items:
        projected.append({
            "id": item["id"],
            "name": item["name"],
            "version": item["version"],
            "kind": item["kind"],
            "category": "Definitions",
            "description": "%s / %s" % (item["name"], item["version"]),
            "search_text": "%s %s %s" % (
                item["name"],
                item["version"],
                item["kind"],
            ),
            "parts": 1,
            "interfaces": 0,
            "composition_contract": {"root": item["id"]},
            "control": {
                "owner": "control:place:%s" % item["id"],
                "title": "Place assembly",
                "icon": "plus",
                "activation": {
                    "binding": "binding:place:%s" % item["id"],
                    "capability": "capability:instantiate",
                },
            },
        })
    return projected


def _property_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "relation": row["relation"],
            "label": row["name"],
            "value": row["value"],
            "editable": False,
            "control": None,
            "event_fact_input": None,
        }
        for row in rows
    ]


def _selected_node(lens: Mapping[str, object]) -> Mapping[str, object] | None:
    selected_root = lens.get("selected_root")
    if type(selected_root) is not str or not selected_root:
        return None
    return next(
        (item for item in lens["nodes"] if item["root_id"] == selected_root),
        None,
    )


def _interaction_bindings(
    interactions: CleanScopeInteractions | None,
    scope_root: str,
    nodes: list[dict[str, object]],
) -> list[dict[str, object]]:
    if interactions is None:
        return []
    bindings: list[dict[str, object]] = []
    for node in nodes:
        if not node["openable"]:
            continue
        binding = interactions.binding_for(scope_root, node["id"])
        if binding is None:
            continue
        bindings.append({
            "interaction": binding.interaction_root,
            "control": binding.control_root,
            "event": interactions.event_root,
        })
    return bindings


def project_clean_visual_canvas(
    authority: UnifiedAuthority,
    visual: CleanVisualSystem,
    lens: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
    session_root: str,
    subject_root: str,
    interactions: CleanScopeInteractions | None = None,
) -> dict[str, object]:
    selected_root = lens.get("selected_root")
    selected_roots = tuple(lens.get("selected_roots") or ())
    nodes: list[dict[str, object]] = []
    for item in lens["nodes"]:
        node = {
            "id": item["root_id"],
            "label": item["label"],
            "assembly": item.get("definition_name"),
            "composition": item["structural_role"] == "composition",
            "openable": bool(item["openable"]),
            "member_count": len(item["properties"]),
            "connection_count": len(item["ports"]),
            "selected": item["root_id"] in selected_roots,
            "focused": item["root_id"] == selected_root,
            "color": _node_color(item),
            # Each node carries its own graph-held property rows so the rail
            # and the node agree without a second projection pass.
            "properties": _property_rows([
                {
                    "relation": item["root_id"],
                    "name": row["name"],
                    "value": row["value"],
                }
                for row in item["properties"]
            ]),
            "ports": [],
        }
        for index, port in enumerate(item["ports"]):
            port_projection = {
                "id": "%s:%s:%s" % (
                    item["root_id"],
                    port["relation_root"],
                    index,
                ),
                "name": _port_name(port),
                "side": _port_side(port["participant_role"]),
                "mode": "connection",
                "connectable": False,
                "read_only": True,
                "editable": False,
                "selected": False,
                "context": False,
                "relation_root": port["relation_root"],
                "participant_role": port["participant_role"],
                "connection": port["connection"],
                "other_roots": list(port["other_roots"]),
            }
            port_projection["descriptor"] = render_clean_visual_template(
                authority,
                visual,
                "canvas-port",
                {
                    **port_projection,
                    "node_id": node["id"],
                },
                caller=caller,
            )
            node["ports"].append(port_projection)
        nodes.append(node)
    _node_positions(nodes)

    wires = []
    for relation in lens["relations"]:
        participants = [
            {"role": role, "root": root}
            for role, root in relation["participants"]
        ]
        source = next(
            (item["root"] for item in participants if item["role"] == "source"),
            None,
        )
        target = next(
            (item["root"] for item in participants if item["role"] == "target"),
            None,
        )
        wires.append({
            "id": relation["root_id"],
            "segment": 0,
            "participants": participants,
            "source": source,
            "target": target,
            "selected": False,
            "context": False,
            "color": _wire_color(relation["properties"]),
            "width": 2,
            "dash": None,
            "directed": source is not None and target is not None,
            "nary": len(participants) > 2,
            "properties": dict(relation["properties"]),
        })

    catalog = _catalog_projection([
        {
            "id": item["root_id"],
            "name": item["name"],
            "version": item["version"],
            "kind": item["lifecycle"],
        }
        for item in lens["catalogue"]
    ])
    for item in catalog:
        item["descriptor"] = render_clean_visual_template(
            authority,
            visual,
            "library-definition",
            item,
            caller=caller,
        )

    catalog_sections = [_section_projection(
        "library-section:definitions",
        "Definitions",
        [item["id"] for item in catalog],
    )]
    for section in catalog_sections:
        section["descriptor"] = render_clean_visual_template(
            authority,
            visual,
            "library-section",
            section,
            caller=caller,
        )

    for node in nodes:
        node["card_descriptor"] = render_clean_visual_template(
            authority,
            visual,
            "canvas-card",
            node,
            caller=caller,
        )

    selected = _selected_node(lens)
    if selected is None:
        selected_root = None
        selected_title = None
        properties = []
        panels = ()
    else:
        selected_root = selected["root_id"]
        selected_title = selected["label"]
        properties = _property_rows([
            {
                "relation": selected_root,
                "name": row["name"],
                "value": row["value"],
            }
            for row in selected["properties"]
        ])
        panels = tuple(
            {
                "id": "panel:%s" % panel_label.casefold(),
                "label": panel_label,
                "active": index == 0,
                "components": [{
                    "presenter": "properties",
                    "descriptor": render_clean_visual_template(
                        authority,
                        visual,
                        "properties",
                        {
                            "selected": selected_root,
                            "properties": properties,
                        },
                        caller=caller,
                    ),
                }],
            }
            for index, panel_label in enumerate(selected["panels"])
        )
    projection = {
        "graph_id": lens["graph_id"],
        "revision": lens["revision"],
        "root": lens["scope_root"],
        "scope": {
            "current": lens["scope_root"],
            "current_label": lens["scope_label"] or "Scope",
            "trail": [{
                "root": lens["scope_root"],
                "label": lens["scope_label"] or "Scope",
                "current": True,
            }],
        },
        "selected": selected_root,
        "selected_title": selected_title,
        "selection": list(selected_roots),
        "focus": selected_root,
        "nodes": nodes,
        "wires": wires,
        "catalog": catalog,
        "catalog_sections": catalog_sections,
        "library": _library_projection(catalog),
        "primitive": _primitive_projection(),
        "properties": properties,
        "viewport": {"pan_x": 0.0, "pan_y": 0.0, "zoom": 1.0},
        "configuration": {
            "design_system": {
                "components": {
                    "card": {"width": {"value": "220px"}},
                    "canvas": {"grid-size": {"value": "16px"}},
                    "control_catalog": [],
                }
            }
        },
        "inspector": {
            "lenses": [
                {
                    "id": "use",
                    "name": "use",
                    "label": "Use",
                    "active": True,
                }
            ] if selected_root is not None else [],
            "presentation": {"panels": list(panels)},
        },
        "interaction_projection": {
            "revision": lens["revision"],
            # Every binding names graph-held identities that the installed
            # interaction set already published. Without an installed set the
            # canvas offers no interaction rather than inventing one.
            "bindings": _interaction_bindings(
                interactions,
                lens["scope_root"],
                nodes,
            ),
        },
        "authorization": {
            "subject": subject_root,
            "browser_sessions": [{"root": session_root}],
        },
    }
    projection["toolbar_descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "canvas-toolbar",
        _toolbar_projection(projection),
        caller=caller,
    )
    projection["canvas_heading_descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "canvas-heading",
        {
            "root": projection["scope"]["current"],
            "label": projection["scope"]["current_label"],
        },
        caller=caller,
    )
    projection["library"]["descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "library-shell",
        projection["library"],
        caller=caller,
    )
    projection["primitive"]["descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "library-primitive",
        projection["primitive"],
        caller=caller,
    )
    projection["inspector"]["header_descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "inspector-header",
        projection,
        caller=caller,
    )
    projection["inspector"]["controls_descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "inspector-controls",
        projection,
        caller=caller,
    )
    projection["inspector"]["shell_descriptor"] = render_clean_visual_template(
        authority,
        visual,
        "inspector-shell",
        {
            "selected": projection["selected"],
            "panels": tuple(
                {
                    "id": panel["id"],
                    "key": "inspector-tabpanel:%s" % panel["id"],
                    "panel_id": "inspector-panel-%s" % index,
                    "tab_id": "inspector-tab-%s" % index,
                    "active": bool(panel["active"]),
                }
                for index, panel in enumerate(panels)
            ),
        },
        caller=caller,
    )
    return projection


__all__ = ["project_clean_visual_canvas"]
