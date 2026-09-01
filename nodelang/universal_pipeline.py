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
        stem_nodes, stem_wires, None, effect_engines
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
    return {
        "ran": len(stem_nodes),
        "wires": len(stem_wires),
        "display": dict(evaluation.display),
        "pending": dict(evaluation.pending),
        "results": dict(evaluation.results),
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


__all__ = ["run_universal_pipeline", "seed_wall_pipeline"]
