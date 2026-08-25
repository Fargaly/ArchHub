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
    _decode_data_value as decode_data_value,
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
                # A tab says what it presents. One that does not is not
                # offered: the same rule this reader already applies to
                # the applicability itself, carried one level down. A
                # projector that filled this in would decide the content
                # of every panel, which is how they all came to show the
                # same thing.
                try:
                    presenter_root = next(
                        inner.participant_id
                        for inner in relation_members(snapshot, panel_root)
                        if inner.role_id == authority.role("presentation")
                    )
                    presenter = decode_value(authority, snapshot, presenter_root)
                except (StopIteration, Exception):
                    continue
                if type(presenter) is not str or not presenter.strip():
                    continue
                # A tab is a place to look, and two declarations of the
                # same place are the same place. Every definition on a
                # canvas declares its own panel, so a scope holding five
                # kinds of node showed five tabs all reading "Properties",
                # all presenting the same thing. Same label AND same
                # presenter is one tab; anything the founder could tell
                # apart still gets its own.
                if any(
                    row["label"] == str(label)
                    and row["presenter"] == presenter.strip()
                    for row in rows
                ):
                    continue
                rows.append({
                    "id": panel_root,
                    "label": str(label),
                    "presenter": presenter.strip(),
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


def _wire_color(properties: Mapping[str, object], default: str) -> str:
    """The wire's own colour, or the palette the graph declares.

    The fallback used to be a literal written here, which meant every
    wire that did not carry a colour was drawn in a shade the graph had
    never heard of -- and drawn over the stylesheet, so revising the
    palette changed everything except the wires.
    """
    value = properties.get("color")
    if type(value) is str and value.strip():
        return value
    return default


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
        "trail": tuple(
            {
                "root": entry["root"],
                "label": entry["label"],
                "key": "toolbar:scope:item:%s" % entry["root"],
                "current": bool(entry.get("current")),
                "show_divider": index > 0,
            }
            for index, entry in enumerate(projection["scope"]["trail"])
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
            # Both readers of this field render a count: the graph-held
            # row descriptor concatenates it in front of " interface(s)",
            # and the client coerces it with Number() to size a placed
            # card. Handing them the contract map printed a raw mapping
            # on every library row and sized every card as if it had no
            # interfaces at all. The contract is carried under its name.
            "interfaces": len(item["interfaces"]),
            "interface_contract": item["interfaces"],
            "presentation": item["presentation"],
            # The library groups by what the definition SAYS it is -- the
            # category its presentation declares (Input, Logic, Shape, AI,
            # ...). A definition that declares none sits under Definitions.
            "category": (
                str(item["presentation"].get("category")).strip()
                if isinstance(item.get("presentation"), dict)
                and str(item["presentation"].get("category") or "").strip()
                else "Definitions"
            ),
            "description": (
                str(item["presentation"].get("description")).strip()
                if isinstance(item.get("presentation"), dict)
                and str(item["presentation"].get("description") or "").strip()
                else "%s / %s" % (item["name"], item["version"])
            ),
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
            # A relation is a definition with participants to choose.
            # Stamping a contract on every entry sent all of them down
            # the relation-composer path, where placement asks for an
            # interaction that is only ever bound for entries WITHOUT a
            # contract -- so the library filled up and not one card
            # could be placed. A definition declaring no interface has
            # nothing to compose; it is a thing to put on the canvas.
            # A stem node -- a definition whose presentation says it places
            # as a card -- lands on the canvas with its ports unbound and is
            # wired afterwards, as every node did in 1.4. Only a definition
            # that does not say so and declares interfaces goes through the
            # relation composer to choose its participants first.
            "composition_contract": (
                None
                if (
                    isinstance(item.get("presentation"), dict)
                    and item["presentation"].get("placement") == "card"
                )
                else ({"root": item["id"]} if item["interfaces"] else None)
            ),
        })
    return projected


def latest_run_rows(
    authority: UnifiedAuthority,
    snapshot,
    node_root: str,
    *,
    limit: int = 200,
) -> tuple[str, list[dict[str, object]], int]:
    """What this node last returned, and the operation that returned it.

    A run is recorded against the node that asked for it, and every
    receipt the graph has ever signed hangs off the history root in the
    order it was signed. Reading backwards from the newest therefore
    finds the last run of a node without an index -- relations only walk
    forwards, and this one already does.

    The walk is bounded. A graph accumulates a receipt per revision
    forever, and a panel that re-read all of them would get slower every
    time anyone did anything. Not finding a run inside the bound reads as
    no run, which is the honest answer for a node nobody has run lately.
    """
    try:
        history = relation_members(snapshot, authority.manifest.history_root)
    except Exception:
        return "", [], 0
    result_role = authority.role("result")
    presentation_role = authority.role("presentation")
    property_role = authority.role("property")
    name_role = authority.role("name")
    value_role = authority.role("value")
    for member in reversed(history[-limit:]):
        try:
            receipt = relation_members(snapshot, member.participant_id)
        except Exception:
            continue
        effects = [
            each.participant_id for each in receipt
            if each.role_id == result_role
        ]
        if not effects:
            continue
        try:
            carried = relation_members(snapshot, effects[0])
        except Exception:
            continue
        presentations = [
            each.participant_id for each in carried
            if each.role_id == presentation_role
        ]
        if not presentations:
            continue
        # Read the subject before anything else. A receipt carries what
        # the run returned, which for a read of a large model is every
        # row it found; decoding that to discover the run belonged to a
        # different node made looking for a node with no runs cost more
        # than running one. The subject alone answers that question.
        held: dict[str, object] = {}
        try:
            properties = [
                each.participant_id
                for each in relation_members(snapshot, presentations[0])
                if each.role_id == property_role
            ]
            fields: dict[str, str] = {}
            for property_root in properties:
                parts = relation_members(snapshot, property_root)
                key = next(
                    decode_data_value(authority, snapshot, part.participant_id)
                    for part in parts if part.role_id == name_role
                )
                fields[str(key)] = next(
                    part.participant_id
                    for part in parts if part.role_id == value_role
                )
            subject_root = fields.get("subject")
            if subject_root is None:
                continue
            if decode_data_value(
                authority, snapshot, subject_root
            ) != node_root:
                continue
            for key, value_root in fields.items():
                held[key] = decode_data_value(authority, snapshot, value_root)
        except Exception:
            continue
        outcome = held.get("outcome")
        rows = outcome.get("result") if isinstance(outcome, Mapping) else None
        if not isinstance(rows, list):
            rows = []
        kept = [row for row in rows if isinstance(row, Mapping)]
        # What the host found, which is not always what the graph kept.
        returned = held.get("rows_returned")
        return (
            str(held.get("operation") or ""),
            kept,
            returned if isinstance(returned, int) else len(kept),
        )
    return "", [], 0


def _panel_input(
    presenter: str,
    authority: UnifiedAuthority,
    selected_root: str | None,
    selected: Mapping[str, object] | None,
    properties: list,
) -> dict[str, object]:
    """What one panel is given to draw, decided by what it presents.

    Every panel used to receive the same thing, which is why they all
    drew the same thing. A presenter names what a tab is for, and the
    input follows from that name -- read from the graph in each case,
    never assembled here from something the graph did not say.
    """
    shared: dict[str, object] = {
        "selected": selected_root,
        "properties": properties,
        "operation": selected.get("operation") if selected else None,
    }
    if presenter != "result":
        return shared
    operation, rows, returned = ("", [], 0)
    if selected_root:
        operation, rows, returned = latest_run_rows(
            authority, authority.store.snapshot(), selected_root
        )
    return {
        **shared,
        # The summary names the run that produced these rows, which is
        # not always the operation the node declares now: a node can be
        # repointed after it ran.
        "operation": _run_summary(operation, len(rows), returned),
        "rows": [_row_line(row) for row in rows],
    }


def _run_summary(operation: str, shown: int, returned: int) -> str | None:
    """What the panel says a run returned, including what it left out.

    A capped answer that reads like a whole one is the failure this
    exists to prevent. The graph records both counts; the person looking
    at the rows is who needs to know, so the difference is said here
    rather than left in a cell nobody opens.
    """
    if not operation:
        return None
    if returned > shown:
        return "%s  --  showing %d of %d rows" % (operation, shown, returned)
    return "%s  --  %d rows" % (operation, shown)


def _row_line(row: Mapping[str, object]) -> str:
    """One row of a host answer, as a line a person can read.

    A row is whatever the host returned, and this build has no idea what
    a workset or a sheet is -- rightly, since the shape of the answer
    belongs to the host that gave it. So every field is shown, in a
    stable order, and none is chosen over another: picking which fields
    matter would be this file inventing a schema the host never stated.
    """
    return "  ".join(
        "%s: %s" % (key, row[key]) for key in sorted(row)
    )


def _focus_is_composition(lens: Mapping[str, object]) -> bool:
    """Whether the focused node is a composition that can be dissolved.

    The old fact was bool(selected_root) -- any focus at all -- which lit
    the Ungroup control for a plain instance and made the toolbar lie.
    """
    selected_root = lens.get("selected_root")
    if type(selected_root) is not str or not selected_root:
        return False
    for item in lens["nodes"]:
        if item["root_id"] != selected_root:
            continue
        return item.get("structural_role") == "composition"
    return False


def _focus_declares_operation(
    lens: Mapping[str, object],
    declared_by_definition: Mapping[str, Mapping[str, object]] | None = None,
) -> bool:
    """Whether the focused node runs: a host operation, or a stem engine.

    Both are the same button. A node that declares rules.operation runs
    on its host; a node whose definition declares rules.engine runs the
    scope's stem graph. A node declaring neither keeps no dead Run.
    """
    selected_root = lens.get("selected_root")
    if type(selected_root) is not str or not selected_root:
        return False
    for item in lens["nodes"]:
        if item["root_id"] != selected_root:
            continue
        operation = item.get("operation")
        if type(operation) is str and operation.strip():
            return True
        declared = (declared_by_definition or {}).get(
            item.get("definition_root") or ""
        )
        return bool((declared or {}).get("engine"))
    return False


def _text_or_none(value: object) -> str | None:
    if type(value) is str and value.strip():
        return value.strip()
    return None


def _node_title(item: Mapping[str, object]) -> str:
    """What this node is called, preferring what it says about itself.

    An instance takes its label from the definition it was made from, so a
    canvas of two hundred requirements drew two hundred cards all reading
    "Requirement composition" -- every card identical, none of them saying
    anything. The definition supplies a title property for exactly this,
    and when an instance carries one it is that instance's name.

    A composition is not renamed: its label is its own, held on the cell
    rather than borrowed from a shape, and a title property on it names
    something the composition contains rather than the composition.
    """
    if item.get("structural_role") != "instance":
        return str(item["label"])
    # A definition that declares a label has named these nodes deliberately,
    # and revising that label is how the graph renames them. Only when it
    # declares none -- so the label falls back to the definition's own name,
    # and every instance of it is called the same thing -- does the instance
    # get to answer for itself.
    if str(item["label"]) != str(item.get("definition_name") or ""):
        return str(item["label"])
    for row in item.get("properties") or ():
        if row.get("name") != "title":
            continue
        value = row.get("value")
        if type(value) is str and value.strip():
            return value.strip()
    return str(item["label"])


def _property_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    # The editor and its constraints are declared by the definition in the
    # graph. Dropping them here and hardcoding a default is how a rail stops
    # describing the thing it claims to describe.
    return [
        {
            "relation": row.get("property_root") or row["relation"],
            # The owner is WHO holds the property, and a row key is not
            # anybody: falling back to it sent "<root>:value" as the owner
            # of every edit, and the server refused each one as a target
            # its scope does not hold -- for a card the founder had just
            # selected. A row with no owner is not editable rather than
            # editable against a name nothing answers to.
            "owner": row.get("owner_root") or "",
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
            # Whether the value varies across the selection is a fact the
            # row has to state. The descriptor chooses an empty input when
            # it is mixed, and an unstated fact reads as mixed -- so every
            # property in the panel showed a blank box over a value the
            # graph was holding. These rows are one node's properties, so
            # there is nothing for them to vary across.
            "mixed": False,
            "control": None,
            "event_fact_input": None,
        }
        for row in rows
    ]


def _selected_relation(lens: Mapping[str, object]):
    """The relation the founder picked, when the selection names one."""
    selected_root = lens.get("selected_root")
    if type(selected_root) is not str or not selected_root:
        return None
    return next(
        (item for item in lens.get("relations", ())
         if item["root_id"] == selected_root),
        None,
    )


def _relation_end_label(lens: Mapping[str, object], root: str) -> str:
    """What a wire's end is called on this canvas."""
    node = next(
        (item for item in lens["nodes"] if item["root_id"] == root), None,
    )
    if node is None:
        return root[:12]
    return _node_title(node)


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
            # What the founder must type before this can run. These
            # interactions take nothing: a scope-open names its target, and
            # a run names the node the focus already holds. Leaving the
            # list out entirely is not the same statement -- the client
            # reads a missing list as an interaction whose inputs it was
            # never told about, and refuses it.
            "event_facts": [],
        })
    # Opening a node is not the only interaction a scope offers. A toolbar
    # control the graph has declared an interaction for must carry it too,
    # or the client refuses to activate the button and does so silently --
    # a Run that looks live and does nothing.
    for control_root in sorted(interactions.bindings.get(scope_root) or ()):
        if any(entry["control"] == control_root for entry in bindings):
            continue
        binding = interactions.binding_for(scope_root, control_root)
        if binding is None:
            continue
        bindings.append({
            "interaction": binding.interaction_root,
            "control": binding.control_root,
            "event": interactions.event_root,
            "event_facts": [],
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
        dict(catalogue.get("tokens") or {}),
    )


def _project_clean_visual_canvas_unscoped(
    authority: UnifiedAuthority,
    visual: CleanVisualSystem,
    lens: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
    session_root: str,
    subject_root: str,
    interactions: CleanScopeInteractions | None = None,
    door_root: str | None = None,
    door_label: str | None = None,
) -> dict[str, object]:
    selected_root = lens.get("selected_root")
    selected_roots = tuple(lens.get("selected_roots") or ())
    nodes: list[dict[str, object]] = []
    # What each definition declares, by root: category (for the card's
    # colour + head) and its interface contract (for declared sockets).
    declared_by_definition = {
        entry["root_id"]: {
            "category": (
                str(entry["presentation"].get("category")).strip()
                if isinstance(entry.get("presentation"), dict)
                and str(entry["presentation"].get("category") or "").strip()
                else None
            ),
            "interfaces": (
                entry.get("interfaces")
                if isinstance(entry.get("interfaces"), dict)
                else {}
            ),
            # What the definition RUNS as, and the defaults it runs
            # with. The stem evaluator reads both off the node so a
            # Run gesture needs no second lens pass.
            "engine": (
                str(entry["rules"].get("engine")).strip()
                if isinstance(entry.get("rules"), dict)
                and str(entry["rules"].get("engine") or "").strip()
                else None
            ),
            "parameters": (
                entry.get("parameters")
                if isinstance(entry.get("parameters"), dict)
                else {}
            ),
        }
        for entry in lens["catalogue"]
    }
    # (card, relation, end) -> the socket on that card. Filled while the
    # cards are built, read when the wires are.
    socket_of_wire_end: dict[tuple[str, str, str], str] = {}
    for item in lens["nodes"]:
        rows_by_label = {
            str(row.get("name")): row.get("value")
            for row in (item.get("properties") or ())
            if isinstance(row, dict) and row.get("name")
        }
        node = {
            "id": item["root_id"],
            "label": _node_title(item),
            "assembly": item.get("definition_name"),
            # What kind of thing this is, what state it is in, and what it
            # says about itself -- all read from the graph: the definition's
            # name, and the node's own status / description properties when
            # it declares them. A card that read "ASSEMBLY / v" and
            # "2 cells / 0 interface" told the founder about the plumbing
            # and nothing about the requirement.
            # Empty text, not null, when absent: the template language
            # tests presence with length(), and a null has none.
            "kind": _text_or_none(item.get("definition_name")) or "",
            "status": _text_or_none(rows_by_label.get("status")) or "",
            "summary": _text_or_none(
                rows_by_label.get("sub")
                if rows_by_label.get("sub") is not None
                else rows_by_label.get("description")
            ) or "",
            # What this node runs, when it runs anything. A node that DOES
            # something has to say so where the canvas can read it, or the
            # Run it offers has nothing to point at.
            "operation": item.get("operation"),
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
                    "relation": (
                        row["property_root"]
                        or "%s:%s" % (item["root_id"], row["name"])
                    ),
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
            # Which socket on this card belongs to which wire END. The
            # canvas draws a wire to the socket its endpoint names, and
            # nothing named one: every one of 344 endpoints pointed at an
            # interface no card rendered, so every line was drawn to a
            # card EDGE instead. The card, the wire and the socket looked
            # unrelated because, in the projection, they were.
            socket_of_wire_end[(
                item["root_id"],
                port["relation_root"],
                _port_side(port["participant_role"]),
            )] = port_projection["id"]
        declared = declared_by_definition.get(
            item.get("definition_root") or "", None
        )
        node["category"] = (declared or {}).get("category") or ""
        node["engine"] = (declared or {}).get("engine")
        node["parameter_defaults"] = {
            str(name): (
                spec.get("default") if isinstance(spec, dict) else spec
            )
            for name, spec in ((declared or {}).get("parameters") or {}).items()
        }
        # Declared sockets: the typed ports the definition promises, drawn
        # unwired so a node reads and wires like a node (1.4's grammar).
        # A wire made from one is an explicit relation node between the two
        # instances, created by the direct connect route; existing wired
        # ports above stay exactly as they were.
        wired_names = {p.get("name") for p in node["ports"]}
        if declared and declared["interfaces"]:
            input_index = 0
            output_index = 0
            for interface_name in sorted(declared["interfaces"]):
                contract = declared["interfaces"][interface_name]
                if not isinstance(contract, dict):
                    continue
                direction = str(contract.get("direction") or "input")
                side = "source" if direction == "output" else "target"
                if interface_name in wired_names:
                    continue
                index = output_index if side == "source" else input_index
                if side == "source":
                    output_index += 1
                else:
                    input_index += 1
                socket = {
                    "id": "decl:%s:%s" % (item["root_id"], interface_name),
                    "name": interface_name,
                    "side": side,
                    "mode": "declared",
                    "connectable": True,
                    "read_only": False,
                    "editable": False,
                    "interface_root": None,
                    "direction": direction,
                    "multiple": bool(contract.get("multiple")),
                    "permission": None,
                    "source_incidence": None,
                    "target_incidence": None,
                    "authority_roots": [],
                    "selected": False,
                    "context": False,
                    "relation_root": "decl:%s:%s" % (item["root_id"], interface_name),
                    "participant_role": side,
                    "connection": interface_name,
                    "other_roots": [],
                    "port_index": str(index),
                    "value_type": str(contract.get("type") or "any"),
                    "connect_route": "direct",
                }
                socket["descriptor"] = render_clean_visual_template(
                    authority,
                    visual,
                    "canvas-port",
                    {**socket, "node_id": node["id"]},
                    caller=caller,
                )
                node["ports"].append(socket)
        nodes.append(node)
    # Every declared input socket in the scope is a drop target for every
    # declared output socket: the client lights them and the direct
    # connect route makes the relation.
    # EVERY socket on this canvas can be wired, not only the ones a stem
    # definition declared: eleven of three hundred and forty-four ports
    # could start a wire, so every domain and requirement card was
    # unwireable and the canvas looked broken to anyone holding a mouse.
    input_targets = [
        {"id": node["id"], "interface": port["name"]}
        for node in nodes
        for port in node["ports"]
        if port["side"] == "target" and port.get("name")
    ]
    for node in nodes:
        for port in node["ports"]:
            if port["side"] == "source" and port.get("name"):
                port["connect_control"] = "direct:connect"
                port["connect_choices"] = [
                    {"id": target["id"], "interface": target["interface"]}
                    for target in input_targets
                    if target["id"] != node["id"]
                ]
    for node in nodes:
        position = node.get("position")
        if isinstance(position, Mapping):
            node["x"] = position.get("x")
            node["y"] = position.get("y")

    # Facts the graph-held conditions are evaluated against. They come
    # from the lens, so one catalogue yields a different applicable set as
    # the scope and selection change.
    control_rows, icon_rows, _icons_by_root, stylesheet, tokens = _catalogue_rows(
        authority,
        caller,
        {
            "scope-parent-present": bool(lens.get("scope_parent_root")),
            "selection-count": len(lens.get("selected_roots") or ()),
            "focus-is-composition": _focus_is_composition(lens),
            # Whether the focused node declares a host operation, read from
            # the definition it was made from rather than guessed from its
            # name: a node that DOES something says so in its rules.
            "focus-is-operation": _focus_declares_operation(
                lens, declared_by_definition
            ),
            "can-undo": False,
            "can-redo": False,
        },
    )
    wire_default_color = tokens.get("accent") or ""
    if not wire_default_color:
        raise InvalidCell("the graph holds no accent colour for its wires")

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
            # The exact socket each end belongs to, when this scope draws
            # the card that carries it.
            "source_interface": socket_of_wire_end.get(
                (source, relation["root_id"], "source")
            ),
            "target_interface": socket_of_wire_end.get(
                (target, relation["root_id"], "target")
            ),
            "selected": relation["root_id"] in selected_roots,
            # The stylesheet hides a wire that is not in context, so a
            # projector that called every wire out-of-context drew a
            # canvas of connections and then made all of them invisible.
            # Context is relative to the selection: with nothing
            # selected nothing is being set aside, so every wire is in
            # context; with a selection, the wires that touch it are.
            "context": (
                not selected_roots
                or source in selected_roots
                or target in selected_roots
            ),
            "color": _wire_color(relation["properties"], wire_default_color),
            "width": 2,
            "dash": None,
            "directed": source is not None and target is not None,
            "nary": len(participants) > 2,
            "properties": dict(relation["properties"]),
        })

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

    # One section per declared category, in the palette's reading order,
    # then everything that declares none. The order is the 1.4 palette's.
    _ORDER = ("Input", "Output", "Watch", "Trigger", "Logic", "Shape", "AI",
              "Note", "Skill", "Connector")
    by_category: dict[str, list[str]] = {}
    for item in catalog:
        by_category.setdefault(str(item.get("category") or "Definitions"), []).append(item["id"])
    ordered = [c for c in _ORDER if c in by_category] + sorted(
        c for c in by_category if c not in _ORDER and c != "Definitions"
    ) + (["Definitions"] if "Definitions" in by_category else [])
    # The client holds the library to one order: the sections, flattened,
    # must read exactly as the catalogue does. The catalogue is therefore
    # laid out in section order -- a re-grouped library is the same release,
    # in the palette's reading order.
    by_id = {item["id"]: item for item in catalog}
    catalog[:] = [
        by_id[definition]
        for category in ordered
        for definition in by_category[category]
    ]
    catalog_sections = [
        _section_projection(
            "library-section:%s" % category.lower().replace(" ", "-"),
            category,
            by_category[category],
        )
        for category in ordered
    ]
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
    selected_relation = _selected_relation(lens) if selected is None else None
    if selected is None and selected_relation is not None:
        # A wire the founder picked says what it joins and why. Without
        # this the inspector answered nothing for a selected relation, so
        # every line on the canvas was a shell: it could not be read, and
        # a thing that cannot be read cannot be judged wrong.
        selected_root = selected_relation["root_id"]
        selected_title = "Relation"
        properties = _property_rows([
            {
                "relation": "%s:%s" % (selected_root, name),
                "name": name,
                "value": value,
                "editor": None,
                "constraints": {},
                "property_root": "",
                "owner_root": "",
                "name_root": "",
                "value_root": "",
                "history_root": None,
                "predecessor_root": None,
                "presentation_root": None,
            }
            for name, value in sorted(
                (str(key), item)
                for key, item in selected_relation["properties"].items()
            )
        ] + [
            {
                "relation": "%s:end:%s" % (selected_root, role),
                "name": str(role),
                "value": _relation_end_label(lens, root),
                "editor": None,
                "constraints": {},
                "property_root": "",
                "owner_root": "",
                "name_root": "",
                "value_root": "",
                "history_root": None,
                "predecessor_root": None,
                "presentation_root": None,
            }
            for role, root in selected_relation["participants"]
        ])
    elif selected is None:
        selected_root = None
        selected_title = None
        properties = []
    else:
        selected_root = selected["root_id"]
        # The inspector names the same thing the card names.
        selected_title = _node_title(selected)
        properties = _property_rows([
            {
                # The row key must NAME THE ROW: keying every row on the
                # owner gave five inputs one identity, and the client's
                # duplicate-mount guard took the whole render down on the
                # first reconcile after an edit.
                "relation": (
                    row["property_root"]
                    or "%s:%s" % (selected_root, row["name"])
                ),
                "name": row["name"],
                "value": row["value"],
                "editor": row["editor"],
                "constraints": row["constraints"],
                "property_root": row["property_root"],
                # Which node the row belongs to is known here even when the
                # property cell does not name it: it is the node whose
                # panel this is.
                "owner_root": row["owner_root"] or selected_root,
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
                "presenter": row["presenter"],
                "descriptor": render_clean_visual_template(
                    authority,
                    visual,
                    row["presenter"],
                    _panel_input(
                        row["presenter"],
                        authority,
                        selected_root,
                        selected,
                        properties,
                    ),
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
            # The door the founder came in through stands first in the
            # trail when the scope shown is below it: that entry is the
            # way back, and the graph declares the interaction for it.
            "trail": [
                *(
                    [{
                        "root": door_root,
                        "label": door_label or "Map",
                        "current": False,
                    }]
                    if door_root and door_root != lens["scope_root"] else []
                ),
                {
                    "root": lens["scope_root"],
                    "label": lens["scope_label"] or "Scope",
                    "current": True,
                },
            ],
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
        # Where the founder is looking is held on the view session, and the
        # lens already reads it. Answering with a literal meant zoom and pan
        # were signed into the graph and then overwritten by 1.0 on the way
        # back out -- the canvas snapping home after every gesture.
        "viewport": {
            "pan_x": 0.0, "pan_y": 0.0, "zoom": 1.0,
            # A view that has never been panned records nothing, and a
            # partial record is still a record. Filling per key rather than
            # all-or-nothing means a stored zoom survives even when no pan
            # was ever taken, and every reader gets a whole viewport.
            **dict(lens.get("viewport") or {}),
        },
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


def project_clean_visual_canvas(
    authority: UnifiedAuthority,
    visual: CleanVisualSystem,
    lens: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
    session_root: str,
    subject_root: str,
    interactions: CleanScopeInteractions | None = None,
    door_root: str | None = None,
    door_label: str | None = None,
) -> dict[str, object]:
    """One projection request shares one template-plan cache.

    The engine already carries a store-bound plan cache with commit
    invalidation (view_template_projection_scope); only the universal
    app entered it. The clean projector rendered ~494 descriptors per
    click, each building a fresh cache, so one warm click re-read the
    same template cells 93,294 times -- 1.2s of the 0.150s the founder
    is owed (SPEC 11.14).
    """
    from .cell_view_template import view_template_projection_scope

    with view_template_projection_scope(authority.store):
        return _project_clean_visual_canvas_unscoped(
            authority,
            visual,
            lens,
            caller=caller,
            session_root=session_root,
            subject_root=subject_root,
            interactions=interactions,
            door_root=door_root,
            door_label=door_label,
        )
