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

from .universal_cell import InvalidCell
from .stem_graph_evaluation import (
    StemNode,
    StemWire,
    evaluate_stem_graph,
)
from .universal_application import (
    _canvas_roots,
    _issue_resource_audience_bindings,
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


# The parameters a real graph engine gives a connection, with the same
# defaults the inspector draws. They are ordinary graph rows on the wire's
# own root, so editing one is the ordinary property write every node
# parameter already uses -- no second mechanism for "a wire".
_WIRE_PARAMETERS = (
    ("enabled", "true"),
    ("lacing", "shortest"),
    ("tree", "none"),
    ("condition", ""),
    ("on_fail", "block"),
    ("throttle_ms", "0"),
)


def _ensure_wire_parameters(store, registry, wire_root: str):
    """Give one connection the parameter rows it is drawn with.

    A graph whose wire roots carry no audience binding yet refuses to let
    a connection own a property. That is a missing install, not a broken
    pipeline: the founder's nodes must still seed and run, and the
    inspector still draws the connection with its defaults. So this is
    best-effort by construction -- it adds rows where the graph admits
    them, and stays silent where it does not.
    """
    try:
        # A connection is a resource on this canvas like its endpoints, so
        # it needs the same signed audience binding before it may own a
        # property. Without one the graph refuses the row with "view
        # resource lacks an active signed audience binding" -- correctly,
        # because nothing had ever released the wire to an audience.
        authorization = registry.authorization
        _issue_resource_audience_bindings(
            store,
            authorization,
            resource_roots=(wire_root,),
            lifecycle_root=(
                registry.standard_library.lifecycle_protocol.states["wip"]
            ),
            owner_root=authorization.subject_root,
            administrator_root=authorization.subject_root,
        )
    except Exception:
        return
    try:
        held = (
            _owner_properties(store.snapshot(), registry).get(wire_root) or {}
        )
    except Exception:
        return
    for label, value in _WIRE_PARAMETERS:
        if label in held:
            continue
        try:
            _persist(
                lambda label=label, value=value: create_universal_property(
                    store, registry, wire_root, label, value,
                ),
                store=store,
            )
        except Exception:
            return


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
    ("Skills Library", 240.0, 740.0, {
        "engine": "skills.catalogue", "match": "",
    }),
    ("Thinking Chain", 560.0, 740.0, {
        "engine": "skills.thinking_chain", "topic": "",
    }),
    ("Connectors", 880.0, 740.0, {
        "engine": "connector.status", "connector": "",
    }),
)


def _persist(write, attempts: int = 5, store=None):
    """Run one governed write, re-reading when its revision went stale.

    Placement and property writes each take a snapshot and commit against
    it; a commit landing in between (the graph settles its own visibility
    as it grows) makes that expected revision stale by exactly one. The
    answer is the same as anywhere else in optimistic concurrency: read
    again and repeat. Nothing here is idempotent by accident -- each call
    site below either creates something that does not exist yet or is a
    no-op when it does.
    """
    import time as _time

    for attempt in range(attempts):
        try:
            return write()
        except Exception as clash:
            if attempt == attempts - 1 or "revision" not in str(clash):
                raise
            # Sleeping alone re-runs the write against the SAME in-memory
            # revision, so a store whose journal moved underneath it fails
            # every attempt with one identical off-by-one. Re-adopt the
            # accepted revision first: that is what "read again" means
            # when the journal, not this process, is the authority.
            if store is not None:
                try:
                    store.refresh()
                except Exception:
                    pass
            _time.sleep(0.15)


def create_engine_node(
    store,
    registry,
    *,
    title: str,
    engine: str,
    x: float = 240.0,
    y: float = 200.0,
    properties=None,
    authentication_context: object | None = None,
):
    """Create ONE engine-backed node on the graph, the way the seed does.

    The library used to add a card to local React state; it ran nothing and
    was gone on reload. This is the governed write seed_wall_pipeline performs
    per node: instantiate the released definition, declare the engine and its
    parameters as properties, ensure the pipeline interfaces.
    """
    from .pipeline_engines import PIPELINE_ENGINES
    engine = str(engine or "").strip()
    if engine not in PIPELINE_ENGINES:
        raise ValueError("no engine named %r" % engine)
    title = str(title or engine).strip()[:80]
    projection = project_universal_canvas(store, registry, authentication_context=authentication_context)
    catalogue = projection.get("catalog") or ()
    definition_root = next(
        (str(item["id"]) for item in catalogue if str(item.get("name")) == "Ordered List"),
        None,
    ) or (str(catalogue[0]["id"]) if catalogue else None)
    if definition_root is None:
        raise ValueError("no released definition is available to place")
    root, _revision = _persist(lambda: instantiate_universal_definition(
        store, registry, definition_root, x=float(x), y=float(y),
        title_override=title, authentication_context=authentication_context,
    ), store=store)
    values = {"engine": engine}
    for label, value in dict(properties or {}).items():
        label = str(label).strip()
        if label and label != "engine":
            values[label] = str(value)
    for label, value in values.items():
        _persist(lambda label=label, value=value: create_universal_property(
            store, registry, root, label, value, authentication_context=authentication_context,
        ), store=store)
    _persist(lambda: _ensure_pipeline_node_interfaces(store, registry, root), store=store)
    return {"ok": True, "root": root, "engine": engine, "title": title}


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
        root, _revision = _persist(lambda: instantiate_universal_definition(
            store, registry, definition_root, x=x, y=y,
            title_override=title,
            authentication_context=authentication_context,
        ), store=store)
        for label, value in properties.items():
            _persist(lambda label=label, value=value: create_universal_property(
                store, registry, root, label, value,
                authentication_context=authentication_context,
            ), store=store)
        placed[title] = root
    for root in placed.values():
        _persist(lambda root=root: _ensure_pipeline_node_interfaces(
            store, registry, root
        ), store=store)
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
        _persist(lambda s=source_root, t=target_root: connect_universal_roots(
            store, registry, s, t,
            source_interface="app:pipeline-interface:%s:source"
            % s.rsplit(":", 1)[-1],
            target_interface="app:pipeline-interface:%s:target"
            % t.rsplit(":", 1)[-1],
            authentication_context=authentication_context,
        ), store=store)
        wired.append((source, target))
    # Every connection between seeded nodes carries the six parameters,
    # whether this run drew it or an earlier one did: a wire the founder
    # can select must have something to hold.
    seeded_roots = set(placed.values())
    for wire in project_universal_canvas(
        store, registry, authentication_context=authentication_context
    ).get("wires", ()):
        if (
            str(wire.get("source") or "") in seeded_roots
            and str(wire.get("target") or "") in seeded_roots
        ):
            _ensure_wire_parameters(store, registry, str(wire["id"]))
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


def _public_value(label: object, value: object) -> str:
    """A property value as the published map may show it.

    File locations stay on the machine: a path-shaped value (or any *_path
    property) is reduced to its file name before it leaves for the cockpit.
    """
    text = str(value)
    key = str(label).casefold()
    looks_like_path = (
        len(text) > 2 and (text[1:3] == ":" + chr(92) or text.startswith((chr(92) * 2, "/", "~")))
    )
    if key.endswith("_path") or key in {"path", "file", "image"} or looks_like_path:
        name = text.replace(chr(92), "/").rstrip("/").rsplit("/", 1)[-1]
        return name[:48]
    return text[:48]


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
    wires = []
    relation_roots: list[tuple[str, str]] = []   # (relation root, atlas domain key)
    top = [n for n in projection.get("nodes", ()) if n.get("openable")]
    # The authored cockpit seed names the grand-map domains by their short key
    # ("ui", "brain"); the graph holds them as "gm:domain:ui". Emit the seed's
    # key so the cockpit merges live and authored as ONE domain -- with two
    # names the same domain was drawn twice in one grid cell (2026-09-04).
    # Grand-map domains come first so they land on the seed's cells; every
    # other openable scope follows in the free cells after them.
    _GM = "gm:domain:"
    top = sorted(top, key=lambda n: (0 if str(n["id"]).startswith(_GM) else 1))

    def atlas_key_of(root: str) -> str:
        return root[len(_GM):] if root.startswith(_GM) else root

    per_row = 4
    for index, item in enumerate(top):
        key = str(item["id"])
        atlas_key = atlas_key_of(key)
        colour = _ATLAS_COLORS[index % len(_ATLAS_COLORS)]
        gx = 40 + (index % per_row) * 650
        gy = 40 + (index // per_row) * 560
        domains.append({
            "key": atlas_key, "root": key,
            "title": str(item.get("label") or atlas_key)[:24],
            "x": gx, "y": gy, "w": 560, "h": 480, "col": colour,
        })
        try:
            member_roots, scoped_relations, _props = _nested_canvas_scope(
                snapshot, registry, key
            )
        except Exception:
            member_roots, scoped_relations = (), ()
        relation_roots.extend((rel, atlas_key) for rel in scoped_relations)
        for spot, member in enumerate(tuple(member_roots)[:24]):
            held = rows_of(member)
            data = {label: value for label, (_r, value) in held.items()}
            title = data.get("title") or data.get("label") or member
            params = [
                {"k": label, "v": _public_value(label, value), "rel": rel, "t": "string"}
                for label, (rel, value) in held.items()
                if label not in {
                    "title", "label", "status", "position_x", "position_y",
                    "engine",
                }
            ][:4]
            nodes.append({
                "id": member, "dom": atlas_key,
                # The engine this node runs, so the cockpit's Run button can
                # run THIS node in the founder's app instead of animating.
                "engine": str(data.get("engine") or "") or None,
                "cat": "logic" if not data.get("engine") else "read",
                "title": str(title)[:60],
                "sub": str(data.get("engine") or data.get("status") or "")[:80],
                "status": "live" if data.get("status") else "partial",
                "params": params,
                "x": gx + 40 + (spot % 2) * 260,
                "y": gy + 60 + (spot // 2) * 120,
            })
    # The wires ARE the graph's relations: every scoped relation whose source
    # and target both stand on the map becomes a wire, cross-domain included.
    # The cockpit drew nothing inside a domain because the push carried
    # "wires": [] (founder 2026-09-04: "where are the wires?").
    emitted = {node["id"] for node in nodes}
    roles = registry.roles

    def owner_on_map(participant: str) -> str | None:
        # A wire ends on an interface or a property of a node, not on the node
        # itself; the canvas resolves the endpoint the same way. Climb the id
        # to the node that stands on the map.
        candidate = str(participant or "")
        while candidate:
            if candidate in emitted:
                return candidate
            parent, separator, _tail = candidate.rpartition(":")
            if not separator:
                return None
            candidate = parent
        return None

    seen_wires: set[tuple[str, str]] = set()
    for relation_root, domain_key in relation_roots:
        try:
            members = read_relation(snapshot, relation_root, budget=256)
            source = owner_on_map(_one_for_role(members, roles["source"]))
            target = owner_on_map(_one_for_role(members, roles["target"]))
        except Exception:
            continue
        if not source or not target or source == target:
            continue
        if (source, target) in seen_wires:
            continue
        seen_wires.add((source, target))
        why = ""
        try:
            why_root = _one_for_role(members, roles["why"])
            if why_root:
                held = rows_of(why_root)
                why = str((held.get("title") or held.get("label") or ("", ""))[1] or "")[:80]
        except Exception:
            why = ""
        wires.append({"a": source, "b": target, "why": why or relation_root[:40], "dom": domain_key})
    # The canvas the studio draws already resolves every top-level wire to its
    # endpoints (a domain, or a node on the top level); those are the
    # cross-domain links the cockpit bundles. Intra-domain wires appear above
    # when a scoped relation's endpoints climb to nodes on the map.
    atlas_of = {str(node["id"]): atlas_key_of(str(node["id"])) for node in top}
    for wire in projection.get("wires", ()):
        try:
            a = atlas_of.get(str(wire.get("source")), str(wire.get("source")))
            b = atlas_of.get(str(wire.get("target")), str(wire.get("target")))
        except Exception:
            continue
        known = emitted | set(atlas_of.values())
        if a not in known or b not in known or a == b or (a, b) in seen_wires:
            continue
        seen_wires.add((a, b))
        wires.append({"a": a, "b": b, "why": str(wire.get("title") or wire.get("id") or "")[:60], "dom": atlas_of.get(str(wire.get("source")), "")})
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
        "domains": domains, "nodes": nodes, "wires": wires,
        # The seed's layout grid, so the cockpit snaps and resolves cells
        # against the same lattice the push was laid out on.
        "grid": {"x0": 40, "y0": 40, "px": 650, "py": 560, "dw": 560, "dh": 480},
    })




def retract_universal_node(
    store,
    registry,
    root: str,
    *,
    authentication_context=None,
):
    """Take one node off the canvas without erasing what it was.

    The graph is append-only: a node is never destroyed, it stops being
    VISIBLE. Its cells, its history and its receipts remain readable --
    which is what makes an undo possible and an audit honest -- while the
    canvas and every projection stop carrying it.
    """
    from .cell_protocols import prepare_remove_relation_members
    from .universal_application import (
        _session_canvas_roots,
        _view_session_for_context,
        read_relation,
    )

    snapshot = store.snapshot()
    view_session, _context = _view_session_for_context(
        registry, authentication_context
    )
    visible_roots, _relations, _properties = _session_canvas_roots(
        snapshot, registry, view_session
    )
    if root not in visible_roots:
        raise InvalidCell("that node is not on this canvas")
    members = read_relation(
        snapshot, view_session.visibility_root, budget=100_000
    )
    doomed = tuple(
        member.incidence_id for member in members
        if member.participant_id == root
    )
    if not doomed:
        raise InvalidCell("that node has no visibility to retract")
    patch = prepare_remove_relation_members(
        snapshot, view_session.visibility_root, doomed, budget=100_000
    )
    store.commit(snapshot.revision, replace=patch.replace)
    return {"retracted": root, "revision": store.revision}


__all__ = ["run_universal_pipeline", "seed_wall_pipeline", "project_atlas_map", "retract_universal_node"]
