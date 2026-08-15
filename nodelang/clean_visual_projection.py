"""Project clean scope lenses into the existing graph-native visual contract."""
from __future__ import annotations

from typing import Mapping

from .clean_design_catalogue import read_design_catalogue
from .universal_cell import InvalidCell
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
            if lens["scope_root"] not in scopes:
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


def _toolbar_projection(
    projection: Mapping[str, object],
    control_rows: list[dict[str, object]],
) -> dict[str, object]:
    """The toolbar draws the controls the graph declares for its zone.

    An empty tuple here was the toolbar half of the same invention as the
    library's: the projector answering for the graph. The zone and the
    order are graph facts, so the toolbar's contents and their sequence
    are decided by revising the catalogue, not by editing this.
    """
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
        "controls": tuple(
            {
                "owner": control["owner"],
                "title": control["title"],
                "icon": control["icon"],
                "activation": {
                    "binding": control["activation"]["binding"],
                    "capability": control["activation"]["capability"],
                    "arguments": dict(control["activation"]["arguments"]),
                },
            }
            for control in control_rows
            if control["zone"] == "canvas-toolbar" and control["applicable"]
        ),
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


def _catalog_projection(
    items: list[dict[str, object]],
    place_control: dict[str, object],
) -> list[dict[str, object]]:
    """Each library row carries the control that places it.

    The row and the catalogue must agree exactly -- the client compares
    the rendered binding, capability, icon and title against the
    catalogue and refuses a row that drifted from it. Carrying the
    control here is what makes that comparison an agreement between two
    readings of one graph fact rather than between the graph and a
    constant.
    """
    projected = []
    for item in items:
        projected.append({
            "control": {
                "owner": place_control["owner"],
                "title": place_control["title"],
                "icon": place_control["icon"],
                "activation": {
                    "binding": place_control["activation"]["binding"],
                    "capability": place_control["activation"]["capability"],
                },
            },
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


def _condition_operand(operand, facts, depth):
    if "fact" in operand:
        if operand["fact"] not in facts:
            raise InvalidCell("control condition fact is missing")
        return facts[operand["fact"]]
    if "literal" in operand:
        text = operand["literal"]
        if text in ("true", "false"):
            return text == "true"
        try:
            return int(text)
        except ValueError:
            return text
    return _applicable(operand, facts, depth + 1)


def _applicable(condition, facts, depth=0):
    """Whether a control applies, from the condition the graph declares.

    Five operators, mirrored from the catalogue's own evaluator, over the
    condition carried as data. Unknown data fails closed: a control whose
    condition cannot be understood is refused, never shown by default.
    """
    if condition is None:
        return False
    if depth > 8:
        raise InvalidCell("control condition nests too deeply")
    operator = condition.get("operator")
    values = [
        _condition_operand(operand, facts, depth)
        for operand in condition.get("operands", ())
    ]
    if operator == "true":
        if values:
            raise InvalidCell("true condition cannot have operands")
        return True
    if operator == "truthy":
        if len(values) != 1:
            raise InvalidCell("truthy condition requires one operand")
        return bool(values[0])
    if operator == "equal":
        if len(values) != 2:
            raise InvalidCell("equal condition requires two operands")
        return values[0] == values[1]
    if operator == "at-least":
        if len(values) != 2 or any(
            type(value) not in (int, float) for value in values
        ):
            raise InvalidCell("at-least condition requires two numbers")
        return values[0] >= values[1]
    if operator == "all":
        if not values or any(type(value) is not bool for value in values):
            raise InvalidCell("all condition requires boolean operands")
        return all(values)
    raise InvalidCell("control condition operator is not admitted")


def _catalogue_rows(authority, caller, facts):
    """Read the controls and icons the graph holds, or refuse.

    No default catalogue, no minimum set, no empty-but-shaped stub. A
    graph that was never given a catalogue must produce a canvas that
    fails loudly, because a projector-side answer to a graph-side absence
    is exactly the invention this removes.
    """
    catalogue = read_design_catalogue(authority, caller=caller)
    if catalogue is None:
        raise InvalidCell("the graph holds no design-system catalogue")
    icon_rows = {
        row["name"]: {
            "root": row["root"],
            "name": row["name"],
            "view_box": row["view_box"],
            "primitives": [
                {
                    "root": "%s:%s" % (row["root"], primitive["order"]),
                    "order": primitive["order"],
                    "tag": primitive["tag"],
                    "attributes": dict(primitive["attributes"]),
                }
                for primitive in row["primitives"]
            ],
        }
        for row in catalogue["icons"]
    }
    by_root = {row["root"]: row for row in icon_rows.values()}
    control_rows = []
    for row in catalogue["controls"]:
        activation = row.get("activation")
        control_rows.append({
            "root": row["owner"],
            "owner": row["owner"],
            "label": row["label"],
            "title": row["title"],
            "zone": row["zone"],
            "order": row["order"],
            "icon": row["icon"],
            "activation": None if activation is None else {
                "binding": activation["binding"],
                "capability": activation["capability"],
                "arguments": dict(activation["arguments"]),
            },
            "condition": None if activation is None else activation["condition"],
            "applicable": activation is not None and _applicable(
                row["activation"]["condition"], facts
            ),
        })
    return (
        control_rows,
        list(icon_rows.values()),
        by_root,
        catalogue.get("stylesheet", ""),
    )


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
            # The client lays out from x and y. They are read from the
            # position the graph holds, never invented here: a node the
            # graph has not placed has no place, and the canvas must say
            # so rather than scatter it somewhere plausible.
            "x": (item.get("position") or {}).get("x"),
            "y": (item.get("position") or {}).get("y"),
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

    # Facts the graph-held conditions are evaluated against. They come
    # from the lens, so one catalogue yields a different applicable set as
    # the scope and selection change.
    control_rows, icon_rows, _icons_by_root, stylesheet = _catalogue_rows(
        authority,
        caller,
        {
            "scope-parent-present": bool(lens.get("scope_parent_root")),
            "selection-count": len(lens.get("selected_roots") or ()),
            "focus-is-composition": bool(lens.get("selected_root")),
            "can-undo": False,
            "can-redo": False,
        },
    )
    place_control = next(
        (
            control for control in control_rows
            if control["zone"] == "library" and control["applicable"]
        ),
        None,
    )
    if place_control is None:
        raise InvalidCell(
            "the graph declares no applicable library place control"
        )
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
    ], place_control)
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
                },
                "control_catalog": {"controls": control_rows},
                "icon_catalog": {"icons": icon_rows},
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
        _toolbar_projection(projection, control_rows),
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
    # Chrome and content are separate facts. The shell is chrome and renders
    # whenever the scope projects at all; panels are content and may
    # legitimately be empty -- an inspector with zero tabs, never no
    # inspector. Collapsing the two blanked the inspector for every scope the
    # graph had not seeded, which no court could reach because every court
    # bootstraps a freshly seeded graph.
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
