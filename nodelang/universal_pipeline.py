"""Run the wired pipeline on the universal canvas, and seed the first one.

This is the missing wire between the graph the founder composes and the
engines that do work: nodes whose graph-held `engine` property names an
effect are collected with their wires, evaluated by the SAME stem
evaluator every other run path uses, and each node's answer lands in its
`status` property through the same governed write the inspector uses.
Logic lives on the graph; changing a parameter and running again changes
the result -- no agent required.
"""
from __future__ import annotations

from typing import Mapping

from .stem_graph_evaluation import (
    StemNode,
    StemWire,
    evaluate_stem_graph,
)
from .universal_application import (
    _canvas_roots,
    _one_for_role,
    _text,
    compose_relation_cells,
    connect_universal_roots,
    create_universal_property,
    edit_universal_property,
    instantiate_universal_definition,
    prepare_append_relation_members,
    project_universal_canvas,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell

_STRUCTURAL = {"engine", "status"}


def _owner_properties(snapshot, registry):
    """owner root -> {label: (relation_root, value)} for the whole canvas."""
    _roots, _relations, property_roots = _canvas_roots(snapshot, registry)
    owned: dict[str, dict[str, tuple[str, str]]] = {}
    for relation_root in property_roots:
        try:
            members = read_relation(snapshot, relation_root, budget=64)
        except Exception:
            continue
        owner = _one_for_role(members, registry.roles["owner"])
        label_root = _one_for_role(members, registry.roles["label"])
        value_root = _one_for_role(members, registry.roles["value"])
        if owner is None or label_root is None or value_root is None:
            continue
        label = _text(snapshot, label_root)
        owned.setdefault(owner, {})[label] = (
            relation_root, _text(snapshot, value_root)
        )
    return owned


def _graph_engines(store, registry):
    """Effect engines whose truth IS the graph this server serves."""

    def baboom_status(params, feeds):
        snapshot = store.snapshot()
        catalogs = {
            "model execution": getattr(
                registry, "baboom_model_execution_adapter_catalog_root", None
            ),
            "cognition": getattr(
                registry, "baboom_cognition_adapter_catalog_root", None
            ),
            "connector execution": getattr(
                registry,
                "baboom_connector_execution_adapter_catalog_root",
                None,
            ),
        }
        held = {
            name: bool(root and root in snapshot.cells)
            for name, root in catalogs.items()
        }
        installed = [name for name, ok in held.items() if ok]
        missing = [name for name, ok in held.items() if not ok]
        if not installed:
            raise ValueError(
                "no BABOOM adapter catalogue is installed in this graph"
            )
        note = "" if not missing else " · missing: %s" % ", ".join(missing)
        return (
            {"out": held},
            "%d/%d adapter catalogues installed (%s)%s" % (
                len(installed), len(held), ", ".join(installed), note
            ),
        )

    return {"baboom.status": baboom_status}


def run_universal_pipeline(
    store,
    registry,
    *,
    effect_engines: Mapping[str, object],
    authentication_context: object | None = None,
) -> dict[str, object]:
    """Evaluate every engine-declaring node along its wires; land statuses."""
    snapshot = store.snapshot()
    owned = _owner_properties(snapshot, registry)
    projection = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    node_ids = {str(node["id"]) for node in projection.get("nodes", ())}
    stem_nodes = []
    for root in node_ids:
        rows = owned.get(root) or {}
        engine = (rows.get("engine") or ("", ""))[1].strip()
        if not engine:
            continue
        parameters = {
            label: value for label, (_rel, value) in rows.items()
            if label not in _STRUCTURAL
        }
        stem_nodes.append(StemNode(root, engine, parameters))
    engine_roots = {node.root_id for node in stem_nodes}
    stem_wires = []
    for wire in projection.get("wires", ()):
        source = str(wire.get("source") or "")
        target = str(wire.get("target") or "")
        if source in engine_roots and target in engine_roots:
            stem_wires.append(StemWire(source, "out", target, "in"))
    evaluation = evaluate_stem_graph(
        stem_nodes, stem_wires, None,
        {**_graph_engines(store, registry), **dict(effect_engines)},
    )
    written = 0
    for node in stem_nodes:
        answer = evaluation.display.get(node.root_id)
        if answer is None:
            answer = evaluation.pending.get(node.root_id)
        if answer is None:
            continue
        rows = owned.get(node.root_id) or {}
        held = rows.get("status")
        if held is not None and held[1] == answer:
            continue
        if held is not None:
            edit_universal_property(
                store, registry, held[0], answer,
                mutation_route="/api/universal/run-graph",
                authentication_context=authentication_context,
            )
        else:
            create_universal_property(
                store, registry, node.root_id, "status", answer,
                authentication_context=authentication_context,
            )
        written += 1
    def _lines_like(value):
        return (
            isinstance(value, list) and value
            and all(
                isinstance(row, (list, tuple)) and len(row) >= 4
                and all(isinstance(v, (int, float)) for v in row[:4])
                for row in value[:400]
            )
        )

    previews = {}
    for root, outs in (evaluation.node_outputs or {}).items():
        value = (outs or {}).get("out")
        if _lines_like(value):
            previews[root] = [
                [float(v) for v in row[:4]] for row in value[:400]
            ]
    return {
        "ran": len(stem_nodes),
        "wires": len(stem_wires),
        "display": dict(evaluation.display),
        "pending": dict(evaluation.pending),
        "results": dict(evaluation.results),
        "lines": previews,
        "written": written,
        "revision": store.revision,
    }


def _ensure_pipeline_node_interfaces(store, registry, owner_root: str):
    """Give one pipeline node its exact out/in canvas interfaces.

    A node the founder wires must declare where a wire may land; these are
    the same read-only interface relations a committed wire's endpoints
    receive, registered on the application root like every other
    application-level interface.
    """
    protocol = registry.assembly_protocol
    roles = registry.roles
    token = owner_root.rsplit(":", 1)[-1]
    created = []
    snapshot = store.snapshot()
    create: list[Cell] = []
    registered: list[tuple[str, str]] = []
    for side, name in (("source", "out"), ("target", "in")):
        interface_root = "app:pipeline-interface:%s:%s" % (token, side)
        if interface_root in snapshot.cells:
            continue
        name_root = interface_root + ":name"
        create.append(Cell(
            name_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")
        ))
        presentation_root = "app:canvas-interface:presentation:%s" % side
        if presentation_root not in snapshot.cells and not any(
            cell.id == presentation_root for cell in create
        ):
            create.append(Cell(
                presentation_root, NULL_CELL_ID, NULL_CELL_ID,
                side.encode("ascii"),
            ))
        interface = compose_relation_cells(
            (
                (protocol.role("interface-target"), owner_root),
                (protocol.role("name"), name_root),
                (protocol.role("interface-contract"), protocol.root_id),
                (protocol.role("interface-presentation"), presentation_root),
                (roles["read-only"], roles["read-only"]),
            ),
            relation_id=interface_root,
        )
        create.extend(interface.cells)
        registered.append((
            protocol.role("interface"), interface_root
        ))
        created.append(interface_root)
    if not create:
        return created
    registration = prepare_append_relation_members(
        snapshot,
        registry.application_root,
        registered,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*create, *registration.create),
        replace=registration.replace,
    )
    return created


_SEED = (
    ("Sketch Lines", 240.0, 200.0, {
        "engine": "vision.sketch_lines",
        "image_path": "", "mm_per_pixel": "10",
        "threshold": "60", "min_length": "40",
    }),
    ("CAD Lines", 240.0, 380.0, {
        "engine": "cad.read_lines", "file_path": "", "layer": "",
    }),
    ("Line Watcher", 560.0, 290.0, {"engine": "lines.watch"}),
    ("Revit Walls", 880.0, 290.0, {
        "engine": "revit.build_walls",
        "level": "", "height_mm": "3000", "session": "",
    }),
    ("Revit Sessions", 880.0, 470.0, {"engine": "revit.sessions"}),
    ("Brain Recall", 240.0, 560.0, {
        "engine": "brain.recall", "prompt": "ArchHub product state",
    }),
    ("Brain Facts", 560.0, 560.0, {"engine": "brain.facts"}),
    ("BABOOM Status", 880.0, 560.0, {"engine": "baboom.status"}),
    ("BABOOM Presence", 1200.0, 560.0, {"engine": "baboom.presence"}),
)


def seed_wall_pipeline(
    store,
    registry,
    *,
    definition_root: str | None = None,
    image_path: str | None = None,
    authentication_context: object | None = None,
) -> dict[str, object]:
    """Place the founder's first wired pipeline: sketch -> watch -> walls.

    The CAD Lines node is placed unwired next to the sketch source: swap
    the wire and the SAME downstream logic runs from a CAD file instead.
    """
    projection = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    existing = {
        str(node.get("label") or ""): str(node["id"])
        for node in projection.get("nodes", ())
    }
    if definition_root is None:
        catalogue = projection.get("catalog") or ()
        definition_root = next(
            (str(item["id"]) for item in catalogue
             if str(item.get("name")) == "Ordered List"),
            None,
        ) or (str(catalogue[0]["id"]) if catalogue else None)
    if definition_root is None:
        raise ValueError("no released definition is available to place")
    placed: dict[str, str] = {
        title: existing[title]
        for title, _x, _y, _properties in _SEED
        if title in existing
    }
    for title, x, y, properties in _SEED:
        if title in existing:
            continue
        root, _revision = instantiate_universal_definition(
            store, registry, definition_root, x=x, y=y,
            title_override=title,
            authentication_context=authentication_context,
        )
        for label, value in properties.items():
            create_universal_property(
                store, registry, root, label, value,
                authentication_context=authentication_context,
            )
        placed[title] = root
    for root in placed.values():
        _ensure_pipeline_node_interfaces(store, registry, root)
    fresh = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    wire_pairs = {
        (str(wire.get("source") or ""), str(wire.get("target") or ""))
        for wire in fresh.get("wires", ())
    }
    wired = []
    for source, target in (
        ("Sketch Lines", "Line Watcher"),
        ("Line Watcher", "Revit Walls"),
    ):
        source_root = placed.get(source)
        target_root = placed.get(target)
        if not source_root or not target_root:
            continue
        if (source_root, target_root) in wire_pairs:
            continue
        connect_universal_roots(
            store, registry, source_root, target_root,
            source_interface="app:pipeline-interface:%s:source"
            % source_root.rsplit(":", 1)[-1],
            target_interface="app:pipeline-interface:%s:target"
            % target_root.rsplit(":", 1)[-1],
            authentication_context=authentication_context,
        )
        wired.append((source, target))
    if image_path and "Sketch Lines" in placed:
        snapshot = store.snapshot()
        rows = _owner_properties(snapshot, registry).get(
            placed["Sketch Lines"]
        ) or {}
        held = rows.get("image_path")
        if held is not None and held[1] != image_path:
            edit_universal_property(
                store, registry, held[0], image_path,
                authentication_context=authentication_context,
            )
    return {"placed": placed, "wired": wired, "revision": store.revision}



_ATLAS_COLORS = (
    "#d97757", "#5fb3b3", "#7898d6", "#a98cd6", "#e8896a", "#5fc4d4",
    "#7ec18e", "#b89cdb", "#e5b25a", "#6a9bcc", "#8fd0a0", "#e0916a",
    "#69c0c0", "#d4a94a", "#c98ab8",
)


def project_atlas_map(store, registry, *, authentication_context=None):
    """The cockpit map IS the live graph: domains and their members.

    One model, three names -- brain, cockpit, grand map. This projects
    the founder's actual graph into the atlas shape the cockpit renders,
    so what the cockpit shows is what the application is.
    """
    import json as _json

    from .universal_application import _nested_canvas_scope

    snapshot = store.snapshot()
    projection = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    owned = _owner_properties(snapshot, registry)

    def rows_of(root):
        return {
            label: (rel, value)
            for label, (rel, value) in (owned.get(root) or {}).items()
        }

    domains = []
    nodes = []
    top = [n for n in projection.get("nodes", ()) if n.get("openable")]
    per_row = 4
    for index, item in enumerate(top):
        key = str(item["id"])
        colour = _ATLAS_COLORS[index % len(_ATLAS_COLORS)]
        gx = 40 + (index % per_row) * 650
        gy = 40 + (index // per_row) * 560
        domains.append({
            "key": key, "title": str(item.get("label") or key)[:24],
            "x": gx, "y": gy, "w": 560, "h": 480, "col": colour,
        })
        try:
            member_roots, _rels, _props = _nested_canvas_scope(
                snapshot, registry, key
            )
        except Exception:
            member_roots = ()
        for spot, member in enumerate(tuple(member_roots)[:24]):
            held = rows_of(member)
            data = {label: value for label, (_r, value) in held.items()}
            title = data.get("title") or data.get("label") or member
            params = [
                {"k": label, "v": str(value)[:48], "rel": rel, "t": "string"}
                for label, (rel, value) in held.items()
                if label not in {
                    "title", "label", "status", "position_x", "position_y",
                    "engine",
                }
            ][:4]
            nodes.append({
                "id": member, "dom": key,
                "cat": "logic" if not data.get("engine") else "read",
                "title": str(title)[:60],
                "sub": str(data.get("engine") or data.get("status") or "")[:80],
                "status": "live" if data.get("status") else "partial",
                "params": params,
                "x": gx + 40 + (spot % 2) * 260,
                "y": gy + 60 + (spot // 2) * 120,
            })
    # The founder's brain facts live INSIDE the Brain & Memory domain --
    # brain, cockpit, grand map: one model. Daemon down = domain shown
    # without facts, honestly, never a crash.
    brain_domain = next(
        (d for d in domains if "brain" in d["title"].casefold()), None
    )
    if brain_domain is not None:
        try:
            from .pipeline_engines import _brain_call
            listing = str(_brain_call("brain.list_facts", {}))
            facts = [
                line.strip() for line in listing.splitlines() if line.strip()
            ][:12]
            for spot, fact in enumerate(facts):
                nodes.append({
                    "id": "brain-fact:%d" % spot,
                    "dom": brain_domain["key"], "cat": "ai",
                    "title": fact[:58] or "fact",
                    "sub": "brain fact · live from :8473",
                    "status": "live", "params": [],
                    "x": brain_domain["x"] + 40 + (spot % 2) * 260,
                    "y": brain_domain["y"] + 60 + (spot // 2) * 90,
                })
        except Exception:
            pass
    return "window.ATLAS_MAP = %s; window.ATLAS_LIVE = true;" % _json.dumps({
        "domains": domains, "nodes": nodes, "wires": [],
    })


__all__ = ["run_universal_pipeline", "seed_wall_pipeline", "project_atlas_map"]
