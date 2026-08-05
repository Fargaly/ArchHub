"""Project clean scope lenses into the existing graph-native visual contract."""
from __future__ import annotations

from typing import Mapping

from .clean_scope_interactions import CleanScopeInteractions
from .clean_visual_authority import (
    CleanVisualSystem,
    render_clean_visual_template,
)
from .unified_authority import (
    COMMAND_BUDGET,
    CallerCommandCapability,
    UnifiedAuthority,
    decode_value,
    relation_members,
)


def _scope_panel_rows(
    authority: UnifiedAuthority,
    lens: Mapping[str, object],
) -> list[dict[str, object]]:
    """Read the panels the graph declares applicable to this scope.

    Panels are compositions the graph holds, named by the scope's one
    applicability relation. The relation is reached forwards -- definition to
    current revision to evidence -- never by searching for something that
    points back. A scope whose revisions carry no applicability projects no
    panels: absence of the declaration is absence of the tabs, not a cue to
    invent Python defaults.
    """
    snapshot = authority.store.snapshot()
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for node in lens["nodes"]:
        definition_root = node.get("definition_root")
        if type(definition_root) is not str or definition_root in seen:
            continue
        seen.add(definition_root)
        try:
            current = next(
                member.participant_id
                for member in relation_members(snapshot, definition_root)
                if member.role_id == authority.role("current-revision")
            )
        except (StopIteration, Exception):
            continue
        for member in relation_members(snapshot, current):
            if member.role_id != authority.role("evidence"):
                continue
            try:
                carried = relation_members(snapshot, member.participant_id)
            except Exception:
                continue
            conforms = [
                each.participant_id
                for each in carried
                if each.role_id == authority.role("conforms-to")
            ]
            if conforms != [authority.shape("relation")]:
                continue
            scopes = [
                each.participant_id
                for each in carried
                if each.role_id == authority.role("scope")
            ]
            if scopes != [lens["scope_root"]]:
                continue
            for each in carried:
                if each.role_id != authority.role("object"):
                    continue
                panel_root = each.participant_id
                if panel_root in {row["id"] for row in rows}:
                    continue
                try:
                    label_root = next(
                        inner.participant_id
                        for inner in relation_members(snapshot, panel_root)
                        if inner.role_id == authority.role("label")
                    )
                    label = decode_value(authority, snapshot, label_root)
                except (StopIteration, Exception):
                    continue
                rows.append({
                    "id": panel_root,
                    "label": str(label),
                    "applicability_root": member.participant_id,
                })
    return rows


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
            "parameters": item["parameters"],
            "interfaces": item["interfaces"],
            "presentation": item["presentation"],
            "category": "Definitions",
            "description": "%s / %s" % (item["name"], item["version"]),
            "search_text": "%s %s %s" % (
                item["name"],
                item["version"],
                item["kind"],
            ),
            # "parts" and the interface count are presentation summaries.
            # The interface contract itself is carried above, straight from
            # the definition, so it is not restated here as a constant.
            "parts": 1,
            "interface_count": len(item["interfaces"]),
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
    # The editor and its constraints are declared by the definition in the
    # graph. Dropping them here and hardcoding a default is how a rail stops
    # describing the thing it claims to describe.
    return [
        {
            "relation": row.get("property_root") or row["relation"],
            "owner": row.get("owner_root") or row["relation"],
            "property_root": row.get("property_root"),
            "name_root": row.get("name_root"),
            "value_root": row.get("value_root"),
            "presentation_root": row.get("presentation_root"),
            "history_root": row.get("history_root"),
            "predecessor_root": row.get("predecessor_root"),
            "label": row["name"],
            "value": row["value"],
            "editor": row.get("editor"),
            "constraints": dict(row.get("constraints") or {}),
            "editable": row.get("editor") is not None,
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
            # Appearance is whatever the definition declares, carried with
            # the cell that declares it. A Python default here would be the
            # fallback the graph-held presentation court exists to catch.
            "color": item.get("resolved_color"),
            "icon": item.get("icon"),
            "color_token": item.get("color_token"),
            "resolved_color": item.get("resolved_color"),
            "position": item.get("position"),
            "presentation_root": item.get("presentation_root"),
            "icon_root": item.get("icon_root"),
            "color_token_root": item.get("color_token_root"),
            "position_root": item.get("position_root"),
            # Each node carries its own graph-held property rows so the rail
            # and the node agree without a second projection pass.
            "properties": _property_rows([
                {
                    "relation": item["root_id"],
                    "name": row["name"],
                    "value": row["value"],
                    "editor": row["editor"],
                    "constraints": row["constraints"],
                    "property_root": row["property_root"],
                    "owner_root": row["owner_root"],
                    "name_root": row["name_root"],
                    "value_root": row["value_root"],
                    "history_root": row.get("history_root"),
                    "predecessor_root": row.get("predecessor_root"),
                    "presentation_root": item.get("presentation_root"),
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
                # What a socket permits is declared by its interface, not by
                # a constant here. Absent a declaration it stays closed.
                "connectable": bool(port.get("interface_root")),
                "read_only": not port.get("interface_root"),
                "editable": bool(port.get("editable")),
                "interface_root": port.get("interface_root"),
                "direction": port.get("direction"),
                "multiple": port.get("multiple"),
                "permission": port.get("permission"),
                "source_incidence": port.get("source_incidence"),
                "target_incidence": port.get("target_incidence"),
                "authority_roots": list(port.get("authority_roots") or ()),
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
    for node in nodes:
        position = node.get("position")
        if isinstance(position, Mapping):
            node["x"] = position.get("x")
            node["y"] = position.get("y")

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
            "parameters": item["parameters"],
            "interfaces": item["interfaces"],
            "presentation": item["presentation"],
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

    scope_panels = _scope_panel_rows(authority, lens)
    selected = _selected_node(lens)
    if selected is None:
        selected_root = None
        selected_title = None
        properties = []
    else:
        selected_root = selected["root_id"]
        selected_title = selected["label"]
        properties = _property_rows([
            {
                "relation": selected_root,
                "name": row["name"],
                "value": row["value"],
                "editor": row["editor"],
                "constraints": row["constraints"],
                "property_root": row["property_root"],
                "owner_root": row["owner_root"],
                "name_root": row["name_root"],
                "value_root": row["value_root"],
                "history_root": row.get("history_root"),
                "predecessor_root": row.get("predecessor_root"),
                "presentation_root": selected.get("presentation_root"),
            }
            for row in selected["properties"]
        ])
    # The tabs are the graph's declaration for this scope, selection or not.
    # Selection changes what the panels present, never which panels exist.
    panels = tuple(
        {
            "id": row["id"],
            "label": row["label"],
            "applicability_root": row["applicability_root"],
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
        for index, row in enumerate(scope_panels)
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
    # With no panels there is nothing to shell. This was wrong as a projector
    # guard while panels were Python strings -- the descriptors court and the
    # deleted-panels court then reached here with identical state and demanded
    # opposite results. Panels are graph compositions now: a fresh scope holds
    # its seeded panel and shells; a scope whose declarations were revised
    # away holds none and shells nothing.
    projection["inspector"]["shell_descriptor"] = [] if not panels else render_clean_visual_template(
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
