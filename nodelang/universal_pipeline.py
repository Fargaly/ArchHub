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

import re
import time

from pathlib import Path as _Path
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
from .cell_protocols import prepare_remove_relation_members

# Rows the graph keeps for its own bookkeeping: they name what a node IS
# and what it last answered, never what its engine computes with, so they
# are not handed to an engine as a parameter.
_STRUCTURAL = {"engine", "status", "seed"}

# The seed's own identity row. A human-readable title is not an identity:
# the founder renames cards, and the grand map already publishes domains
# whose titles collide with a card's ("Connectors"). This marker is what
# a re-seed matches on.
_SEED_MARKER = "seed"

_SAMPLES = _Path(__file__).resolve().parent / "samples"


def sample_input(name: str) -> str:
    """The absolute path of one shipped sample input.

    The flagship chain shipped with empty inputs, so every node of it
    pended at every boot and the founder's first open showed nothing
    working. These samples are read by the same engines a real file goes
    through -- no special case, no fixture mode.
    """
    return str(_SAMPLES / name)


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


def runtime_presence_state(store, registry, *, now: float | None = None) -> dict:
    """Which signed runtimes hold a live presence lease on this graph.

    The one presence source: the BABOOM Presence card and every BABOOM
    presence route (application_server._machine_agent_runtime_presence)
    read this. Leases live in the graph's presence registry and its
    indexed lease storage; a graph with no presence protocol has none.
    """
    import time as _time

    from .cell_runtime_presence import list_active_runtime_presences

    protocol = getattr(registry, "runtime_presence_protocol", None)
    live = () if protocol is None else list_active_runtime_presences(
        store.snapshot(), protocol, now=_time.time() if now is None else now
    )
    runtimes = sorted({presence.runtime for presence in live})
    return {
        "active_runtime_sessions": len(live),
        "baboom_connected": "baboom" in runtimes,
        "baboom_action_capability_active": "baboom-execution" in runtimes,
        "runtimes": runtimes,
    }


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

    def baboom_presence(params, feeds):
        """Whether a signed BABOOM runtime is attached to THIS graph.

        One source: runtime_presence_state, the same answer the BABOOM
        presence, context and native-frame routes read. It needs no server
        object, which is why the boot run can answer it.
        """
        protocol = getattr(registry, "runtime_presence_protocol", None)
        if protocol is None:
            raise ValueError("this graph holds no runtime-presence protocol")
        state = runtime_presence_state(store, registry)
        runtimes = state["runtimes"]
        return (
            {"out": state},
            "companion %s · %d signed runtime session(s)%s" % (
                "ATTACHED" if state["baboom_connected"] else "not attached",
                state["active_runtime_sessions"],
                "" if not runtimes else " (%s)" % ", ".join(runtimes),
            ),
        )

    return {
        "baboom.status": baboom_status,
        "baboom.presence": baboom_presence,
    }


# The last pipeline run, for anything that shows the canvas state without
# re-running it. Empty until the first run of this process.
_LAST_RUN: dict[str, object] = {}


def last_pipeline_run() -> dict[str, object]:
    """{ran, answered, pending, failed, refused, at} of the most recent run, or {}.

    ``failed`` lists the engines whose effect raised; ``refused`` the engines
    that answered ok=False (a host or connector refusing). Engine names only:
    BABOOM warns from these without receiving node titles or values.
    """
    held = dict(_LAST_RUN)
    for name in ("failed", "refused"):
        if name in held:
            held[name] = list(held[name])
    return held


def _observed_effect_engines(engines, failed, refused):
    """Wrap each effect engine to note a raise (failed) or an ok=False answer (refused).

    A Workshop card refusing the ungated canvas Run is the designed answer, not
    a failure, so approval-gated engines are left unwrapped.
    """
    from .workshop_workflow import approval_required

    def observed(name, effect):
        def run(params, feeds):
            try:
                produced, shown = effect(params, feeds)
            except Exception:
                failed.append(name)
                raise
            if isinstance(produced, Mapping) and produced.get("ok") is False:
                refused.append(name)
            return produced, shown
        return run
    return {
        name: observed(name, effect)
        if callable(effect) and effect is not approval_required else effect
        for name, effect in engines.items()
    }


def _pipeline_port_name(node, interface_root, side, wire_root):
    """Resolve an executable endpoint through its graph-declared interface."""
    ports = node.get("ports") or ()
    matches = [port for port in ports if port.get("id") == interface_root]
    if not interface_root or len(matches) != 1:
        raise InvalidCell("wire %s has no unique %s interface binding" % (wire_root, side))
    port = matches[0]
    name = port.get("name")
    if (
        port.get("owner") != node["id"] or port.get("side") != side
        or port.get("mode") != "connection" or port.get("derived") or not port.get("name_root")
        or type(name) is not str or not name.strip()
    ):
        raise InvalidCell("wire %s has no executable %s interface contract" % (wire_root, side))
    if sum(1 for candidate in ports
           if candidate.get("side") == side and candidate.get("name") == name) != 1:
        raise InvalidCell("wire %s has an ambiguous %s interface name" % (wire_root, side))
    return name


def _pipeline_wire_rows(wire):
    """The rows the evaluator applies to one wire, or None when it is muted.

    enabled, tree, condition and on_fail are carried by the evaluator
    (stem_graph_evaluation._carry). Rows an older build persisted and this
    one does not apply (lacing, throttle_ms, on_fail "pass last") refuse the
    run when they ask for anything but their default, instead of being
    silently ignored.
    """
    parameters = {row["label"]: str(row.get("value", ""))
                  for row in wire.get("params", ()) if row.get("label")}
    enabled = parameters.get("enabled", "true").strip().lower()
    if enabled not in ("true", "false"):
        raise InvalidCell("wire %s has an invalid enabled value" % wire["id"])
    if enabled == "false":
        return None
    for name, default in _HIDDEN_WIRE_PARAMETERS:
        if parameters.get(name, default).strip() != default:
            raise InvalidCell("wire %s requests unsupported %s behavior" % (wire["id"], name))
    defaults = dict(_WIRE_PARAMETERS)
    rows = {
        name: parameters.get(name, defaults[name]).strip()
        for name in ("tree", "condition", "on_fail")
    }
    if rows["tree"] not in _WIRE_CHOICES["tree"]:
        raise InvalidCell("wire %s requests unsupported tree behavior" % wire["id"])
    if rows["on_fail"] not in _WIRE_CHOICES["on_fail"]:
        raise InvalidCell("wire %s requests unsupported on_fail behavior" % wire["id"])
    return rows


def _rules_engine(node) -> str:
    """The engine a node's definition declares in its rules, when it has one.

    A rule row may hold the engine as JSON ({"engine": "shape.count"}) or as
    ``engine: shape.count`` / ``engine=shape.count``.
    """
    import json as _json

    assembly = node.get("assembly") if isinstance(node, Mapping) else None
    for row in (assembly or {}).get("rules") or ():
        text = str((row or {}).get("value") or "").strip()
        if not text:
            continue
        if text.startswith("{"):
            try:
                held = _json.loads(text)
            except ValueError:
                continue
            if isinstance(held, Mapping) and str(held.get("engine") or "").strip():
                return str(held["engine"]).strip()
            continue
        for separator in (":", "="):
            name, found, value = text.partition(separator)
            if found and name.strip() == "engine" and value.strip():
                return value.strip()
    return ""


def _composer_pick(snapshot, registry) -> str:
    """The composer model the graph holds; an unreadable pick is no pick."""
    from .universal_application import read_universal_composer_model
    try:
        current = read_universal_composer_model(snapshot, registry)
    except Exception:
        return ""
    return str(current["value"]).strip() if current["source"] == "graph" else ""


def run_universal_pipeline(
    store,
    registry,
    *,
    effect_engines: Mapping[str, object],
    authentication_context: object | None = None,
    only_roots: object = None,
    mutation_lock: object = None,
    revalidate: object = None,
) -> dict[str, object]:
    """Evaluate every engine-declaring node along its wires; land statuses.

    `only_roots` narrows the run to those nodes (and wires between them):
    an act BABOOM confirms runs its one node, not every effect node left on
    the canvas (audit 2026-09-06: each confirm re-ran every prior act).

    With `mutation_lock` the graph lock is held only to read the plan and to
    land the statuses; the effects run between the two, outside it, because
    an engine may wait a minute on a shell, a host or a provider (a Terminal
    card held every graph route for its whole command). `revalidate` runs
    under the lock before the statuses land and refuses a caller whose
    authority lapsed meanwhile. A node retracted while its effect ran gets no
    status. Without `mutation_lock` the caller holds whatever lock it holds.
    """
    import contextlib
    held_lock = mutation_lock if mutation_lock is not None else contextlib.nullcontext()
    with held_lock:
        stem_nodes, stem_wires, graph_engines = _pipeline_plan(
            store, registry, authentication_context, only_roots)
    failed_engines: list[str] = []
    refused_engines: list[str] = []
    evaluation = evaluate_stem_graph(
        stem_nodes, stem_wires, None,
        _observed_effect_engines(
            {**graph_engines, **dict(effect_engines)},
            failed_engines, refused_engines,
        ),
    )
    with held_lock:
        if callable(revalidate):
            revalidate()
        written = _land_pipeline_statuses(
            store, registry, stem_nodes, evaluation, authentication_context)
        revision = store.revision
    # BABOOM's face reads this: how many cards ran and how many really
    # answered, from the run itself rather than a guess over the graph.
    _LAST_RUN.clear()
    _LAST_RUN.update({
        "ran": len(stem_nodes),
        "answered": len(evaluation.display),
        "pending": len(evaluation.pending),
        "failed": tuple(sorted(set(failed_engines)))[:8],
        "refused": tuple(sorted(set(refused_engines)))[:8],
        "at": time.time(),
    })
    return _pipeline_outcome(stem_nodes, stem_wires, evaluation, written, revision)


def _pipeline_plan(store, registry, authentication_context, only_roots):
    """Under the graph lock: the engine nodes, their enabled wires, graph engines."""
    snapshot = store.snapshot()
    owned = _owner_properties(snapshot, registry)
    projection = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    node_ids = {str(node["id"]) for node in projection.get("nodes", ())}
    if only_roots is not None:
        node_ids &= {str(root) for root in only_roots}
    from .library_engines import MODEL_PICK_ENGINES
    picked: list[str] = []
    stem_nodes = []
    projected_nodes = {str(node["id"]): node for node in projection.get("nodes", ())}
    for root in node_ids:
        rows = owned.get(root) or {}
        # A graph-held engine row wins; a node placed from a definition that
        # declares rules.engine runs that engine without one.
        engine = (rows.get("engine") or ("", ""))[1].strip() or _rules_engine(
            projected_nodes.get(root)
        )
        if not engine:
            continue
        parameters = {
            label: value for label, (_rel, value) in rows.items()
            if label not in _STRUCTURAL
        }
        # A model card left blank runs on the composer pick the graph holds,
        # the one Send and BABOOM read; with no pick it keeps its refusal.
        if engine in MODEL_PICK_ENGINES and not str(
            parameters.get("model") or ""
        ).strip():
            if not picked:
                picked.append(_composer_pick(snapshot, registry))
            if picked[0]:
                parameters["model"] = picked[0]
        stem_nodes.append(StemNode(root, engine, parameters))
    engine_roots = {node.root_id for node in stem_nodes}
    stem_wires = []
    for wire in projection.get("wires", ()):
        source = str(wire.get("source") or "")
        target = str(wire.get("target") or "")
        if source in engine_roots and target in engine_roots:
            carried = _pipeline_wire_rows(wire)
            if carried is None:
                continue
            stem_wires.append(StemWire(
                source, _pipeline_port_name(projected_nodes[source], wire.get("source_interface"), "source", wire["id"]),
                target, _pipeline_port_name(projected_nodes[target], wire.get("target_interface"), "target", wire["id"]),
                **carried,
            ))
    return stem_nodes, stem_wires, _graph_engines(store, registry)


def _land_pipeline_statuses(store, registry, stem_nodes, evaluation, authentication_context):
    """Under the graph lock: each answer lands as its node's status, read afresh."""
    owned = _owner_properties(store.snapshot(), registry)
    written = 0
    for node in stem_nodes:
        answer = evaluation.display.get(node.root_id)
        if answer is None:
            answer = evaluation.pending.get(node.root_id)
        if answer is None:
            continue
        rows = owned.get(node.root_id)
        if rows is None:
            continue  # retracted while its effect ran
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
    return written


def _pipeline_outcome(stem_nodes, stem_wires, evaluation, written, revision):
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
        "revision": revision,
    }


def _pipeline_interface_cells(snapshot, registry, owner_root: str, engine, planned):
    """The cells and registrations one engine card's missing sockets need.

    ``planned`` holds cell ids already planned in the same commit, so a
    shared presentation cell is created once. Nothing is committed here.
    """
    from .library_engines import engine_sockets

    protocol = registry.assembly_protocol
    token = owner_root.rsplit(":", 1)[-1]
    create: list[Cell] = []
    registered: list[tuple[str, str]] = []
    created: list[str] = []
    sockets = engine_sockets(engine or "")
    wanted = [("source", "out"), ("target", "in")] + [
        (side, name)
        for side in ("source", "target")
        for name in sockets[side]
        if name not in ("out", "in")
    ]
    for side, name in wanted:
        interface_root = (
            "app:pipeline-interface:%s:%s" % (token, side)
            if name in ("out", "in")
            else "app:pipeline-interface:%s:%s:%s" % (token, side, name)
        )
        if interface_root in snapshot.cells or interface_root in planned:
            continue
        name_root = interface_root + ":name"
        create.append(Cell(
            name_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")
        ))
        presentation_root = "app:canvas-interface:presentation:%s" % side
        if presentation_root not in snapshot.cells and presentation_root not in planned:
            planned.add(presentation_root)
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
            ),
            relation_id=interface_root,
        )
        create.extend(interface.cells)
        planned.add(interface_root)
        registered.append((protocol.role("interface"), interface_root))
        created.append(interface_root)
    return create, registered, created


def _commit_interfaces(store, registry, snapshot, create, registered):
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


def _ensure_pipeline_node_interfaces(store, registry, owner_root: str, engine: str | None = None):
    """Give one pipeline node its exact named canvas interfaces.

    A node the founder wires must declare where a wire may land, registered
    on the application root like every other application-level interface.
    They carry no read-only role: an engine's sockets are where a new wire
    is drawn from and dropped on, not a committed wire's endpoints. Every
    card has out and in; a logic card also gets the branches its engine
    produces and the inputs it reads (library_engines.ENGINE_SOCKETS).
    """
    snapshot = store.snapshot()
    create, registered, created = _pipeline_interface_cells(
        snapshot, registry, owner_root, engine, set()
    )
    if create:
        _commit_interfaces(store, registry, snapshot, create, registered)
    return created


def ensure_logic_card_sockets(store, registry) -> int:
    """Admitted migration: give logic cards placed before 2026-09-24 their
    named sockets (if: false/condition, switch: a/b/c/key, loop: each,
    merge: b).

    Only engine cards this module placed (they already hold the pipeline
    out socket) whose engine declares extra sockets are touched. Every
    missing socket lands in ONE commit, then the view sessions index them
    (the existing visibility growth law, its own commit); a graph with none
    missing makes no commit and returns 0. The caller declares the
    migration intent.
    """
    from .library_engines import ENGINE_SOCKETS

    snapshot = store.snapshot()
    planned: set[str] = set()
    create: list[Cell] = []
    registered: list[tuple[str, str]] = []
    added = 0
    for owner_root, rows in sorted(_owner_properties(snapshot, registry).items()):
        engine = (rows.get("engine") or ("", ""))[1].strip()
        if engine not in ENGINE_SOCKETS:
            continue
        token = owner_root.rsplit(":", 1)[-1]
        if "app:pipeline-interface:%s:source" % token not in snapshot.cells:
            continue
        cells, members, created = _pipeline_interface_cells(
            snapshot, registry, owner_root, engine, planned
        )
        create.extend(cells)
        registered.extend(members)
        added += len(created)
    if create:
        _commit_interfaces(store, registry, snapshot, create, registered)
        # The view sessions index the interfaces they may show. Index the new
        # sockets now, under the same admitted migration, so the next boot
        # finds nothing left to catch up (it did: one visibility commit).
        from .universal_application import _ensure_visibility_scope_projections
        _ensure_visibility_scope_projections(store, registry)
    return added


_PIPELINE_SOCKET = re.compile(r"app:pipeline-interface:[0-9A-Za-z_-]+:(?:source|target)")


def release_pipeline_socket_read_only(store, registry) -> int:
    """Admitted migration: drop the read-only role from engine out/in sockets.

    Engine sockets placed before 2026-09-24 carried it, so no wire could be
    dropped on them. Only interfaces this module mints (registered on the
    application root under the pipeline-interface prefix) are touched, and
    only their (read-only, read-only) member; a graph with none left makes
    no commit. The caller declares the migration intent.
    """
    snapshot = store.snapshot()
    interface_role = registry.assembly_protocol.role("interface")
    read_only = registry.roles["read-only"]
    replace: dict[str, Cell] = {}
    released = 0
    for member in read_relation(
        snapshot, registry.application_root, budget=100_000
    ):
        root = member.participant_id
        if member.role_id != interface_role or not _PIPELINE_SOCKET.fullmatch(root):
            continue
        held = read_relation(snapshot, root, budget=64)
        drop = [
            item.incidence_id for item in held
            if item.role_id == read_only and item.participant_id == read_only
        ]
        if not drop:
            continue
        patch = prepare_remove_relation_members(snapshot, root, drop, budget=64)
        for cell in patch.replace:
            replace[cell.id] = cell
        released += 1
    if replace:
        store.commit(snapshot.revision, replace=tuple(replace.values()))
    return released


# The parameters a real graph engine gives a connection, with the same
# defaults the inspector draws. They are ordinary graph rows on the wire's
# own root, so editing one is the ordinary property write every node
# parameter already uses -- no second mechanism for "a wire".
# THE wire parameter list: Studio and the cockpit draw these rows from
# GET /api/universal/node-library ("wire_parameters"), the run applies them
# (stem_graph_evaluation._carry) and a new connection is given these rows.
# Nothing else declares them.
WIRE_PARAMETER_SPECS = (
    {"k": "enabled", "label": "Enabled", "type": "toggle", "def": True,
     "help": "Mute the connection without deleting it — downstream sees nothing."},
    {"k": "tree", "label": "Data tree", "type": "menu", "def": "none",
     "opts": ["none", "flatten", "graft", "simplify"],
     "help": "Restructure on the way through — flatten to one list, graft each item "
             "into its own branch, simplify removes empty levels."},
    {"k": "condition", "label": "Condition", "type": "text", "def": "", "page": "Rules",
     "help": "The wire only carries when this holds, e.g. count > 0 or value >= 10. "
             "Empty means always."},
    {"k": "on_fail", "label": "On block", "type": "menu", "def": "block",
     "opts": ["block", "pass empty"], "page": "Rules",
     "help": "What downstream receives when the condition blocks: nothing (block) "
             "or an empty list."},
)


def _row_default(value) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


_WIRE_PARAMETERS = tuple((spec["k"], _row_default(spec["def"])) for spec in WIRE_PARAMETER_SPECS)
_WIRE_CHOICES = {spec["k"]: tuple(spec["opts"]) for spec in WIRE_PARAMETER_SPECS if spec.get("opts")}


def wire_parameter_specs() -> list:
    """The wire rows as Studio and the cockpit draw them (a copy)."""
    return [dict(spec, opts=list(spec["opts"])) if spec.get("opts") else dict(spec)
            for spec in WIRE_PARAMETER_SPECS]
# Persisted by earlier builds, applied by none: a run refuses anything but
# the default rather than ignoring it.
_HIDDEN_WIRE_PARAMETERS = (("lacing", "shortest"), ("throttle_ms", "0"))


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


# The founder's first canvas: the one piece of real work, and nothing else.
# Every entry carries a "seed" marker: that, not the title, is what a
# re-seed matches on, and the shipped sample inputs are what make the
# flagship chain answer on first open.
# Placement is a grid of 320 x 260 cells (a card is 210 wide and at most ~200
# tall with its rows), so no two cards overlap and the wired chain reads left
# to right on one row. The points apply only to cards a seed CREATES; an
# adopted card that overlaps another is re-placed once by the canvas-content
# migration (settle_canvas_content), a card the user pinned never.
_SEED = (
    ("Sketch Lines", 240.0, 200.0, {
        "seed": "sketch-lines",
        "engine": "vision.sketch_lines",
        "image_path": sample_input("sample-plan.png"),
        "mm_per_pixel": "10",
        "threshold": "60", "min_length": "40", "max_gap": "8",
    }),
    ("CAD Lines", 240.0, 460.0, {
        "seed": "cad-lines",
        "engine": "cad.read_lines",
        "file_path": sample_input("sample-plan.dxf"), "layer": "",
    }),
    ("Line Watcher", 560.0, 200.0, {
        "seed": "line-watcher", "engine": "lines.watch",
    }),
    ("Revit Walls", 880.0, 200.0, {
        "seed": "revit-walls",
        "engine": "revit.build_walls",
        "level": "", "height_mm": "3000", "session": "",
    }),
    ("Revit Sessions", 880.0, 460.0, {
        "seed": "revit-sessions", "engine": "revit.sessions",
    }),
)

# Status readers have no inputs and no outputs: they are not work on the
# user's canvas, they are what a lens shows (SPEC 6). Each one is seeded
# into the lens that owns what it reads. Positions are chosen by
# canvas_placement.free_slot inside that lens, never by a constant.
_LENS_SEED = (
    ("Brain Recall", "brain", {
        "seed": "brain-recall",
        "engine": "brain.recall", "prompt": "ArchHub product state",
    }),
    ("Brain Facts", "brain", {
        "seed": "brain-facts", "engine": "brain.facts",
    }),
    ("BABOOM Status", "cockpit", {
        "seed": "baboom-status", "engine": "baboom.status",
    }),
    ("BABOOM Presence", "cockpit", {
        "seed": "baboom-presence", "engine": "baboom.presence",
    }),
    # Named for what it does, not for the domain it reads: the grand map
    # already publishes a domain titled "Connectors", and a title match
    # against it is exactly how this card lost its engine.
    ("Connector Status", "cockpit", {
        "seed": "connector-status",
        "engine": "connector.status", "connector": "",
    }),
    ("Skills Library", "workshop", {
        "seed": "skills-library",
        "engine": "skills.catalogue", "match": "",
    }),
    ("Thinking Chain", "workshop", {
        "seed": "thinking-chain",
        "engine": "skills.thinking_chain", "topic": "",
    }),
)

# Every card the seed declares, wherever it lives.
_ALL_SEED = (
    *((title, properties) for title, _x, _y, properties in _SEED),
    *((title, properties) for title, _lens, properties in _LENS_SEED),
)
_LENS_OF_MARKER = {
    properties[_SEED_MARKER]: lens for _title, lens, properties in _LENS_SEED
}


def lens_scope_root(registry, lens: str) -> str:
    """The graph scope that IS one lens: Brain, Cockpit or the Workshop.

    Brain and Cockpit are grand-map domains; the Workshop is the Workbench
    scope inside Brain that Workshop navigation opens.
    """
    if lens == "workshop":
        return registry.workshop_workbench_root
    return registry.map.domains[lens]


def scope_card_bounds(snapshot, registry, scope_root: str) -> dict:
    """root -> (x, y, w, h) for every positioned member of one scope."""
    from .canvas_placement import card_size, drawn_rows
    from .universal_application import _property_index, _rows_by_label

    members = read_relation(snapshot, scope_root, budget=200_000)
    roots = [m.participant_id for m in members
             if m.role_id == registry.roles["member"]]
    property_roots = tuple(
        m.participant_id for m in members
        if m.role_id == registry.roles["property"]
    )
    if roots and not property_roots and scope_root != registry.canvas_root:
        # A scope that indexes members only (Models & Agents): the canvas
        # indexes every property, so the positions are read from there.
        property_roots = _canvas_roots(snapshot, registry)[2]
    index = _property_index(snapshot, registry, property_roots)
    bounds = {}
    for root in roots:
        rows = _rows_by_label(snapshot, index.get(root, ()))
        if "position_x" not in rows or "position_y" not in rows:
            continue
        try:
            x = float(_text(snapshot, rows["position_x"].value_root))
            y = float(_text(snapshot, rows["position_y"].value_root))
        except (TypeError, ValueError):
            continue
        engine = (
            _text(snapshot, rows["engine"].value_root) if "engine" in rows else ""
        )
        bounds[root] = (x, y, *card_size(engine, drawn_rows(rows)))
    return bounds


def free_scope_slot(snapshot, registry, scope_root: str, size=None,
                    *, origin=None, occupied=()):
    """The first free position inside one scope for a card of ``size``."""
    from .canvas_placement import ORIGIN, card_size, free_slot

    held = list(scope_card_bounds(snapshot, registry, scope_root).values())
    return free_slot(
        (*held, *occupied), size or card_size(),
        origin=origin or ORIGIN,
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
    x: float | None = 240.0,
    y: float | None = 200.0,
    properties=None,
    instance_token: str | None = None,
    authentication_context: object | None = None,
    item: str | None = None,
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
    values = {"engine": engine}
    for label, value in dict(properties or {}).items():
        label = str(label).strip()
        if label and label != "engine":
            values[label] = str(value)
    # The engine catalogue owns declared defaults for every placement surface.
    # Persist them as ordinary editable graph properties; UI cards need no copy.
    from .library_engines import LIBRARY_ITEM_ENGINES
    item = str(item or "").strip()
    if item:
        # The library card placed names itself: its defaults are the ones,
        # even when several cards share this engine (where type / category /
        # level are all library.filter_field). The graph-held entry wins
        # over the seed constant once the library is installed.
        chosen = engine_library_entry(store.snapshot(), item) or LIBRARY_ITEM_ENGINES.get(item)
        if chosen is None or chosen.get("engine") != engine:
            raise ValueError("library card %r does not run engine %r" % (item, engine))
        catalogue_items = [chosen]
    else:
        # No card named: the graph-held library decides (SPEC 4.5); the seed
        # constant answers only before the library is installed.
        installed = read_engine_library(store.snapshot())
        if installed is not None:
            catalogue_items = [entry for group in installed for entry in group["items"]
                               if entry.get("engine") == engine]
        else:
            catalogue_items = [entry for entry in LIBRARY_ITEM_ENGINES.values()
                               if entry.get("engine") == engine]
    # Shared engines can have different item-specific defaults. An engine name
    # alone cannot choose between them; preserve explicit caller parameters.
    if len(catalogue_items) == 1:
        for label, value in catalogue_items[0].get("params", {}).items():
            if label != "engine":
                values.setdefault(label, str(value))
    root = None if instance_token is None else "assembly-instance:" + instance_token
    if root is not None and root in store.snapshot().cells:
        from .universal_application import select_universal_root, _property_index, _view_session_for_context
        if root not in {row["id"] for row in projection.get("nodes", ())}:
            raise InvalidCell("The reserved Agent node is outside the admitted canvas")
        snapshot = store.snapshot()
        view, _ = _view_session_for_context(registry, authentication_context)
        lens_roots = tuple(member.participant_id for member in read_relation(
            snapshot, view.properties_lens_root, budget=100_000)
            if member.role_id == registry.roles["scope"])
        properties = _property_index(snapshot, registry, lens_roots).get(root, ())
        for label, value in {"definition":definition_root, **values}.items():
            rows = [row for row in properties if _text(snapshot, row.label_root) == label]
            if len(rows) != 1 or _text(snapshot, rows[0].value_root) != value:
                raise InvalidCell("The reserved Agent node parameters changed; review its binding")
        select_universal_root(store, registry, root, authentication_context=authentication_context)
    else:
        # ONE tracked transaction places the card: the instance, its parameters
        # and its sockets. Placing them in separate writes left the instance
        # referenced by writes the history does not take back, so Undo of a
        # placement was refused ("created Cell gained references after the
        # recorded transaction"; founder smoke 2026-10-01).
        import uuid as _uuid
        token = instance_token or _uuid.uuid4().hex

        def place():
            snapshot = store.snapshot()
            sockets, registered, _created = _pipeline_interface_cells(
                snapshot, registry, "assembly-instance:" + token, engine, set()
            )
            return instantiate_universal_definition(
                store, registry, definition_root,
                x=(float(x) if x is not None else None),
                y=(float(y) if y is not None else None),
                title_override=title, authentication_context=authentication_context,
                instance_token=token, initial_properties=values,
                owned_interface_cells=tuple(sockets), owned_interface_members=tuple(registered),
            )

        root, _revision = _persist(place, store=store)
    _persist(lambda: _ensure_pipeline_node_interfaces(store, registry, root, engine), store=store)
    return {"ok": True, "root": root, "engine": engine, "title": title}


def seed_wall_pipeline(
    store,
    registry,
    *,
    definition_root: str | None = None,
    image_path: str | None = None,
    authentication_context: object | None = None,
    settle_guard=None,
) -> dict[str, object]:
    """Place the founder's first wired pipeline: sketch -> watch -> walls.

    The CAD Lines node is placed unwired next to the sketch source: swap
    the wire and the SAME downstream logic runs from a CAD file instead.
    Both read a shipped sample, so the chain answers on first open on a
    machine that has neither Revit nor AutoCAD.

    Seeding is idempotent over the MARKER, never the title. A card is
    adopted only when it carries this seed's marker (or, once, when it
    carries both the title and the very engine this entry declares), and
    an adopted card gets every property row it is missing. Matching on
    the title alone silently cost the founder a card: the grand map
    publishes a domain titled "Connectors", the seed adopted it, wrote no
    engine row onto it, and skipped its own twelfth node.
    """
    projection = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    snapshot = store.snapshot()
    owned = _owner_properties(snapshot, registry)
    visible = [str(node["id"]) for node in projection.get("nodes", ())]
    by_title: dict[str, str] = {}
    for node in projection.get("nodes", ()):
        by_title.setdefault(str(node.get("label") or ""), str(node["id"]))
    # The marker is matched over the whole canvas, not the level on screen:
    # a seed run while another scope is open used to find no marker there
    # and place a second set of twelve cards. A card on screen is preferred
    # only when a marker is already held twice.
    members = _canvas_roots(snapshot, registry)[0]
    # A status card lives in its lens; the marker is matched there first,
    # so a lens card is never placed twice because the canvas lacks it.
    lens_members = []
    for lens in dict.fromkeys(_LENS_OF_MARKER.values()):
        lens_root = lens_scope_root(registry, lens)
        if lens_root in snapshot.cells:
            lens_members.extend(
                member.participant_id
                for member in read_relation(snapshot, lens_root, budget=200_000)
                if member.role_id == registry.roles["member"]
            )
    by_marker: dict[str, str] = {}
    for root in (*visible, *lens_members, *members):
        marker = (owned.get(root) or {}).get(_SEED_MARKER)
        if marker is not None and marker[1].strip():
            by_marker.setdefault(marker[1].strip(), root)
    if definition_root is None:
        catalogue = projection.get("catalog") or ()
        definition_root = next(
            (str(item["id"]) for item in catalogue
             if str(item.get("name")) == "Ordered List"),
            None,
        ) or (str(catalogue[0]["id"]) if catalogue else None)
    if definition_root is None:
        raise ValueError("no released definition is available to place")
    placed: dict[str, str] = {}
    created: list[str] = []
    adopted: list[str] = []
    completed: list[str] = []
    skipped: list[dict[str, str]] = []
    lens_slots: dict[str, list] = {}

    def lens_position(lens):
        """A free slot in the lens, clear of the cards this run placed."""
        from .canvas_placement import card_size
        lens_root = lens_scope_root(registry, lens)
        taken = lens_slots.setdefault(lens, [])
        x, y = free_scope_slot(
            store.snapshot(), registry, lens_root, occupied=taken
        )
        taken.append((x, y, *card_size()))
        return lens_root, x, y

    entries = (
        *((title, None, x, y, properties) for title, x, y, properties in _SEED),
        *((title, lens, None, None, properties)
          for title, lens, properties in _LENS_SEED),
    )
    for title, lens, x, y, properties in entries:
        marker = str(properties[_SEED_MARKER])
        root = by_marker.get(marker)
        if root is None:
            # One-time migration off the old title match: a card an earlier
            # build of THIS seed placed carries the title and the engine but
            # no marker. Requiring the engine to match too is what keeps a
            # stranger of the same name (a grand-map domain) out.
            candidate = by_title.get(title)
            if candidate is not None and (
                (owned.get(candidate) or {}).get("engine", ("", ""))[1].strip()
                == str(properties["engine"])
            ):
                root = candidate
        try:
            if root is None and lens is not None:
                # Placed inside its lens with every row in the same commit:
                # a row written afterwards would name an owner outside the
                # open canvas, and the graph refuses that.
                import uuid as _uuid
                lens_root, x, y = lens_position(lens)
                initial = {label: str(value) for label, value in properties.items()}
                root, _revision = _persist(
                    lambda: instantiate_universal_definition(
                        store, registry, definition_root, x=x, y=y,
                        title_override=title,
                        authentication_context=authentication_context,
                        activate_view=False,
                        placement_scope_root=lens_root,
                        instance_token=_uuid.uuid4().hex,
                        initial_properties=initial,
                    ),
                    store=store,
                )
                held = {label: ("", value) for label, value in initial.items()}
                created.append(title)
            elif root is None:
                root, _revision = _persist(
                    lambda: instantiate_universal_definition(
                        store, registry, definition_root, x=x, y=y,
                        title_override=title,
                        authentication_context=authentication_context,
                    ),
                    store=store,
                )
                held: dict[str, tuple[str, str]] = {}
                created.append(title)
            else:
                held = dict(owned.get(root) or {})
                adopted.append(title)
            for label, value in properties.items():
                value = str(value)
                current = held.get(label)
                # A row the founder filled in is his; only a missing row, or
                # one still holding the blank this seed used to ship, is
                # written. That is what makes an adopted card complete.
                if current is not None and (
                    current[1].strip() or not value.strip()
                ):
                    continue
                if current is None:
                    _persist(
                        lambda label=label, value=value: (
                            create_universal_property(
                                store, registry, root, label, value,
                                authentication_context=authentication_context,
                            )
                        ),
                        store=store,
                    )
                else:
                    _persist(
                        lambda relation=current[0], value=value: (
                            edit_universal_property(
                                store, registry, relation, value,
                                authentication_context=authentication_context,
                            )
                        ),
                        store=store,
                    )
                completed.append("%s.%s" % (title, label))
            placed[title] = root
        except Exception as refusal:
            # A card that cannot be seeded is named and counted. It used to
            # be invisible: eleven cards where twelve were declared, and
            # nothing anywhere said so.
            skipped.append({"title": title, "why": str(refusal)})
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
    on_screen = {str(node["id"]) for node in fresh.get("nodes", ())}
    wired = []
    for source, target in (
        ("Sketch Lines", "Line Watcher"),
        ("Line Watcher", "Revit Walls"),
    ):
        source_root = placed.get(source)
        target_root = placed.get(target)
        if not source_root or not target_root:
            continue
        # Cards adopted from another level were wired where they live; a
        # connection is only drawn between cards on the open canvas.
        if source_root not in on_screen or target_root not in on_screen:
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
    # A lens card an earlier seed put on the canvas, a duplicate chain, a
    # contact or a session left on the canvas: one admitted move puts each
    # where it belongs. On a new graph there is nothing to move.
    # The same admitted migration the launcher runs in the background, under
    # the same intent; settle_canvas_content lets one run per graph at a time.
    from . import commit_intent
    with commit_intent.declare(
        commit_intent.MIGRATION, actor=registry.application_root,
        reason="move canvas content to its lenses; tombstone the duplicate seed set",
    ):
        # ``settle_guard`` is the caller's commit guard (its owner's mutation
        # lock, then the live context), the one the background run takes.
        settled = settle_canvas_content(
            store, registry, authentication_context=authentication_context,
            guard=settle_guard,
        )
    counts = {
        "declared": len(_ALL_SEED),
        "placed": len(created),
        "adopted": len(adopted),
        "completed": len(completed),
        "skipped": len(skipped),
    }
    # Said out loud, into launcher.log, every boot. A seed that loses a card
    # must never again be able to lose it quietly.
    print(
        "  seed       : %d declared · %d placed · %d adopted · "
        "%d row(s) completed · %d skipped%s" % (
            counts["declared"], counts["placed"], counts["adopted"],
            counts["completed"], counts["skipped"],
            "" if not skipped else " (%s)" % ", ".join(
                entry["title"] for entry in skipped
            ),
        ),
        flush=True,
    )
    return {
        "placed": placed,
        "created": created,
        "adopted": adopted,
        "completed": completed,
        "skipped": skipped,
        "counts": counts,
        "wired": wired,
        "settled": settled,
        "revision": store.revision,
    }



_ATLAS_COLORS = (
    "#d97757", "#5fb3b3", "#7898d6", "#a98cd6", "#e8896a", "#5fc4d4",
    "#7ec18e", "#b89cdb", "#e5b25a", "#6a9bcc", "#8fd0a0", "#e0916a",
    "#69c0c0", "#d4a94a", "#c98ab8",
)


def _is_private_value(label: object, value: object) -> bool:
    """True for a file location, which never leaves the machine in full."""
    text = str(value)
    key = str(label).casefold()
    looks_like_path = (
        len(text) > 2 and (text[1:3] == ":" + chr(92) or text.startswith((chr(92) * 2, "/", "~")))
    )
    return key.endswith("_path") or key in {"path", "file", "image"} or looks_like_path


def _atlas_param(label, rel, value) -> dict:
    """One map parameter: the display value, and the full value to edit.

    A value cut to 48 characters is only for display; editing it must start
    from the whole value, or saving writes the cut copy back over the graph.
    A file location is shown by name only and is not editable here.
    """
    row = {"k": label, "v": _public_value(label, value), "rel": rel, "t": "string"}
    if _is_private_value(label, value):
        row["editable"] = False
    else:
        row["full"] = str(value)
    return row


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


# A session is a real thing with real state, so it belongs on the map -- but
# it is ONE place holding many sessions, not one place PER session. The
# founder's canvas held 60 app:agent-session roots against 15 authored
# domains, and his cockpit drew 95 domains, seventeen of them identical
# cards reading "baboom Agent Ses..." (2026-09-07).
_ATLAS_SESSION_ROOT = "app:agent-session:"
_ATLAS_SESSION_DOMAIN = "runtime"
_ATLAS_SESSION_TITLE = "Runtime Sessions"

# Pure wiring: an incidence, a candidate, a dynamic property row. These carry
# nothing a person reads or acts on, so they are not drawn as places. They
# remain in the graph exactly as they are; the map simply is not their lens.
_ATLAS_WIRING_ROOTS = (
    "app:canvas-relation",
    "app:dynamic:property",
    "relation-candidate",
    "assembly-instance",
)


def _is_atlas_session(root: str) -> bool:
    """True for one runtime agent session -- a place's member, not a place."""
    return root.startswith(_ATLAS_SESSION_ROOT)


def _is_atlas_wiring(root: str) -> bool:
    """True when a scope is an incidence or candidate with nothing to show."""
    return any(root.startswith(prefix) for prefix in _ATLAS_WIRING_ROOTS)


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
    # "Openable" only means a scope has members, and the runtime opens one
    # per attach. Sessions stay ON the map -- they are real and they have
    # state -- but as members of one Runtime Sessions place. Only pure
    # wiring is left undrawn, and both rules are named, never an allowlist,
    # so a domain the founder authors tomorrow is never silently hidden.
    openable = [
        n for n in projection.get("nodes", ()) if n.get("openable")
    ]
    session_scopes = [
        n for n in openable if _is_atlas_session(str(n.get("id") or ""))
    ]
    top = [
        n for n in openable
        if not _is_atlas_session(str(n.get("id") or ""))
        and not _is_atlas_wiring(str(n.get("id") or ""))
    ]
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
                _atlas_param(label, rel, value)
                for label, (rel, value) in held.items()
                if label not in {
                    "title", "label", "status", "position_x", "position_y",
                    "engine", _SEED_MARKER,
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
                # What the last Run actually answered, word for word; the
                # status above is only the map's colour class.
                "status_text": str(data.get("status") or ""),
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
    # ONE Runtime Sessions place holding every session the runtime opened,
    # with what each one actually is: which runtime attached, and whether it
    # still holds presence. A place that only counts things is decoration;
    # this one says which session is live and which is finished, so the
    # founder can see an attach that never let go.
    if session_scopes:
        seat = len(domains)
        session_x = 40 + (seat % per_row) * 650
        session_y = 40 + (seat // per_row) * 560
        domains.append({
            "key": _ATLAS_SESSION_DOMAIN, "root": _ATLAS_SESSION_ROOT,
            "title": _ATLAS_SESSION_TITLE,
            "x": session_x, "y": session_y, "w": 560, "h": 480,
            "col": _ATLAS_COLORS[seat % len(_ATLAS_COLORS)],
        })
        for spot, scope in enumerate(session_scopes[:24]):
            root = str(scope.get("id") or "")
            held = rows_of(root)
            data = {label: value for label, (_r, value) in held.items()}
            runtime = str(data.get("runtime") or "").strip()
            state = str(data.get("state") or data.get("status") or "").strip()
            nodes.append({
                "id": root, "dom": _ATLAS_SESSION_DOMAIN, "cat": "ai",
                "engine": None,
                "title": (runtime or str(scope.get("label") or "session"))[:28],
                "sub": root.rsplit(":", 1)[-1][:18],
                "status": "live" if state in {"active", "live"} else "vision",
                "params": [
                    {"k": label, "v": _public_value(label, value), "rel": rel,
                     "t": "string"}
                    for label, (rel, value) in held.items()
                    if label in {"runtime", "state", "status", "opened_at"}
                ][:4],
                "evidence_ref": "",
                "x": session_x + 30 + (spot % 3) * 175,
                "y": session_y + 60 + (spot // 3) * 96,
            })
    # The founder's brain facts live INSIDE the Brain & Memory domain --
    # brain, cockpit, grand map: one model. No application Brain bound =
    # domain shown without facts, honestly, never a crash.
    brain_domain = next(
        (d for d in domains if "brain" in d["title"].casefold()), None
    )
    if brain_domain is not None:
        try:
            from .app_brain import list_facts
            # Twelve cards want twelve facts: one page of the application's
            # Brain, read from this graph (no daemon, nothing dialed).
            listing = list_facts(limit=12)
            facts = [fact["name"] for folder in listing["folders"] for fact in folder["facts"]][:12]
            for spot, fact in enumerate(facts):
                nodes.append({
                    "id": "brain-fact:%d" % spot,
                    "dom": brain_domain["key"], "cat": "ai",
                    "title": fact[:58] or "fact",
                    "sub": "brain fact · in this graph",
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
    from .cell_identity import record_authority_relationship_revocation
    from .universal_application import (
        _session_canvas_roots,
        _view_session_for_context,
        prepare_universal_retraction,
    )

    snapshot = store.snapshot()
    view_session, _context = _view_session_for_context(
        registry, authentication_context
    )
    visible_roots, _relations, _properties, trail = _session_canvas_roots(
        snapshot, registry, view_session, include_trail=True
    )
    if root not in visible_roots:
        raise InvalidCell("that node is not on this canvas")
    # The card, the interfaces it owns, the wires ending on it and their
    # properties leave together, at the level the card is on; the result is
    # proved before the commit.
    create, replace, revocations, grants = prepare_universal_retraction(
        snapshot, registry, view_session, root, scope_root=trail[-1]
    )
    store.commit(snapshot.revision, create=create, replace=replace)
    broker = registry.authorization.relationship_broker
    for grant in grants:
        broker.record_generation(grant.root_id, grant.generation)
    for revocation in revocations:
        record_authority_relationship_revocation(
            broker, revocation, store.revision
        )
    return {"retracted": root, "revision": store.revision}


# ------------------------------------------- canvas content, where it belongs --
# The founder's canvas held twelve seeded cards (seven of them status
# readers with no inputs or outputs), Workshop contact routing records as
# raw JSON cells and every runtime agent session; the Workbench held a
# second seeded set. SPEC 6: the Use layer shows no raw Cells, protocol
# internals or JSON, and every status reader belongs to a lens. This
# admitted migration MOVES membership; it never deletes a root or rewrites
# history. Its record is a relation, so a graph holding it commits nothing.
CANVAS_CONTENT_MIGRATION_ROOT = "app:canvas-content-migration:v1"
_NATIVE_CONTACT_KIND = "native-contact"
# Rows that say where a card stands or what it last answered, not what the
# user put in it: "status" is the run's last answer (see _STRUCTURAL), and
# the next run rewrites it. Two copies differing only here hold the same.
_NOT_HELD = frozenset({"position_x", "position_y", "placed", "status"})
_MIGRATION_BATCH_PREFIX = CANVAS_CONTENT_MIGRATION_ROOT + ":batch:"
_MIGRATION_SKIP_PREFIX = CANVAS_CONTENT_MIGRATION_ROOT + ":skip:"


def _migration_digest(value) -> str:
    """A short, stable name for the state a skip was recorded against."""
    import hashlib
    import json as _json

    return hashlib.sha256(_json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()[:32]


def _migration_batch_relations(snapshot) -> list:
    """Every batch relation any run of the migration committed.

    Read from the journal's own key order (``ids_with_prefix``), never a
    scan: an interrupted run's batches are found by the run that finishes.
    """
    from .universal_cell import ids_with_prefix

    return sorted(
        root for root in ids_with_prefix(snapshot.cells, _MIGRATION_BATCH_PREFIX)
        if len(root) == len(_MIGRATION_BATCH_PREFIX) + 32
        and all(ch in "0123456789abcdef" for ch in root[len(_MIGRATION_BATCH_PREFIX):])
    )


def _grouped_roots(snapshot, registry, roots) -> set:
    """Every root inside a group the USER made, at any depth.

    A grouped card still holds its ``app:canvas`` row; taking it off the
    canvas would break the group, so the plan counts it as touched. A scope
    the application built the same way (the Workshop Workbench holds every
    session Work was assigned to) is not a group the user made.
    """
    from .universal_application import _user_composition_root

    member = registry.roles["member"]
    grouped: set = set()
    seen: set = set()
    pending = list(dict.fromkeys(roots))
    while pending:
        root = pending.pop()
        if root in seen:
            continue
        seen.add(root)
        if not _user_composition_root(snapshot, registry, root):
            continue
        for part in read_relation(snapshot, root, budget=300_000):
            if part.role_id == member:
                grouped.add(part.participant_id)
                pending.append(part.participant_id)
    return grouped


def _wired_holders(snapshot, registry, scopes, candidates) -> set:
    """Which of ``candidates`` a wire ends on: one pass over each scope's wires."""
    from .universal_application import _canvas_interface_owner_in

    wired: set = set()
    if not candidates:
        return wired
    ends = (registry.roles["source"], registry.roles["target"])
    for scope in dict.fromkeys(scopes):
        if scope not in snapshot.cells:
            continue
        for member in read_relation(snapshot, scope, budget=300_000):
            if (member.role_id != registry.roles["relation"]
                    or member.participant_id not in snapshot.cells):
                continue
            for part in read_relation(snapshot, member.participant_id, budget=64):
                if part.role_id not in ends:
                    continue
                for root in candidates:
                    if root not in wired and (
                        part.participant_id == root
                        or _canvas_interface_owner_in(
                            snapshot, registry, part.participant_id, frozenset((root,)))
                    ):
                        wired.add(root)
    return wired


def _native_contact_cell(snapshot, root: str) -> bool:
    """A Workshop contact routing record: a terminal Cell holding its JSON."""
    import json as _json

    cell = snapshot.cells.get(root)
    if cell is None or cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        return False
    try:
        held = _json.loads(bytes(cell.atom).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(held, dict) and held.get("kind") == _NATIVE_CONTACT_KIND


def plan_canvas_content(snapshot, registry, owned=None) -> dict:
    """What leaves the canvas and where it goes. Reads; writes nothing.

    Cards are matched by their seed MARKER, never by title, on the canvas
    and in every lens. Per marker exactly one card is kept: a pipeline card
    on the canvas, a status card preferably where it already lives in its
    lens (else it moves there). A copy is tombstoned only when the kept
    card already holds everything it does: each of its row values (where
    it stands and what it last answered aside) and no wire of its own. A
    copy the user touched -- wired, placed by hand or put in a group -- is
    the one kept; when copies differ, or more than one was touched, none is
    tombstoned and the marker is reported as a skip. A card in a group the
    user made never leaves the canvas: that too is a reported skip.
    Returns moves (root, from scope, to scope, why), tombstones
    (root, from scope, kept root) and skips; ``None`` as a from scope is
    the top canvas, and as a to scope means the root only leaves it.
    """
    from .universal_application import _USER_PLACEMENT

    owned = _owner_properties(snapshot, registry) if owned is None else owned
    member_role = registry.roles["member"]
    canvas = _canvas_roots(snapshot, registry)[0]
    lens_roots = {lens: lens_scope_root(registry, lens)
                  for lens in dict.fromkeys(_LENS_OF_MARKER.values())}
    holders: dict[str, list[tuple[str, str | None]]] = {}

    def marker_of(root):
        return ((owned.get(root) or {}).get(_SEED_MARKER) or ("", ""))[1].strip()

    for root in canvas:
        if marker_of(root):
            holders.setdefault(marker_of(root), []).append((root, None))
    lens_members: list[str] = []
    for lens_root in dict.fromkeys(lens_roots.values()):
        if lens_root not in snapshot.cells:
            continue
        for member in read_relation(snapshot, lens_root, budget=300_000):
            if member.role_id != member_role:
                continue
            lens_members.append(member.participant_id)
            if marker_of(member.participant_id):
                holders.setdefault(marker_of(member.participant_id), []).append(
                    (member.participant_id, lens_root))
    grouped = _grouped_roots(snapshot, registry, (*canvas, *lens_members))
    moves: list[tuple[str, str | None, str, str]] = []
    tombstones: list[tuple[str, str | None, str]] = []
    kept_on_canvas: list[str] = []
    skips: list[dict] = []
    contested = {root for held in holders.values()
                 if len({root for root, _scope in held}) > 1 for root, _scope in held}
    wired = _wired_holders(
        snapshot, registry, (registry.canvas_root, *lens_roots.values()), contested)

    def rows_of(root):
        return {label: value for label, (_relation, value) in (owned.get(root) or {}).items()
                if label not in _NOT_HELD}

    def by_hand(root):
        return ((owned.get(root) or {}).get("placed") or ("", ""))[1] == _USER_PLACEMENT

    def covers(keeper, other):
        mine = rows_of(keeper)
        return all(mine.get(label) == value for label, value in rows_of(other).items())

    def left_alone(root, why):
        skips.append({
            "key": "root:" + root, "roots": [root], "why": why,
            "digest": _migration_digest(["root", root, why, sorted(rows_of(root).items())]),
        })

    for marker, held in sorted(holders.items()):
        lens = _LENS_OF_MARKER.get(marker)
        if lens is None:
            ranked = sorted(held, key=lambda item: item[1] is not None)
        else:
            home = lens_roots[lens]
            ranked = sorted(held, key=lambda item: (item[1] != home, item[1] is not None))
        roots = list(dict.fromkeys(root for root, _scope in ranked))
        if len(roots) > 1:
            touched = [root for root in roots
                       if root in wired or by_hand(root) or root in grouped]
            if len(touched) > 1:
                keeper, why = None, "more than one copy is wired, placed by hand or grouped"
            else:
                choices = touched or roots
                keeper = next((root for root in choices
                               if all(covers(root, other) for other in roots)), None)
                why = "its copies hold different values"
            if keeper is None:
                skips.append({
                    "key": "marker:" + marker, "roots": sorted(roots), "why": why,
                    "digest": _migration_digest(["marker", marker, sorted(
                        [root, scope, sorted(rows_of(root).items()),
                         root in wired, by_hand(root)]
                        for root, scope in held)]),
                })
                continue
            ranked = ([item for item in ranked if item[0] == keeper]
                      + [item for item in ranked if item[0] != keeper])
        keep = ranked[0]
        if lens is None and keep[1] is None:
            kept_on_canvas.append(keep[0])
        if lens is not None and keep[1] != lens_roots[lens]:
            if keep[1] is None and keep[0] in grouped:
                left_alone(keep[0], "it is in a group the user made")
            else:
                moves.append((keep[0], keep[1], lens_roots[lens], "lens:" + lens))
        for root, scope in ranked[1:]:
            if root != keep[0]:
                tombstones.append((root, scope, keep[0]))
    workbench = registry.workshop_workbench_root
    for root in canvas:
        if root in grouped and (
            _native_contact_cell(snapshot, root)
            or root.startswith("app:agent-session:runtime:")
        ):
            left_alone(root, "it is in a group the user made")
        elif _native_contact_cell(snapshot, root):
            moves.append((root, None, workbench, "contact"))
        elif root.startswith("app:agent-session:runtime:"):
            # A session only leaves the canvas. It stays whole where it
            # already lives: the agent registry the Workshop sidebar reads,
            # Models & Agents, and the Workbench when Work was assigned to
            # it (Workshop deliberation references it there).
            moves.append((root, None, None, "session"))
    return {"moves": moves, "tombstones": tombstones, "kept": kept_on_canvas,
            "skips": skips}


# Every point a seed table ever gave a pipeline card (git log -p of this
# file: 454e78a and dddccf6 wrote the first table, 8cc3463 the current one).
# A card standing EXACTLY on one was never moved by hand. "placed" exists
# only since 4f981f0 (2026-09-25); a card moved by hand before that stands
# anywhere else, and is never re-placed.
_SEED_POINTS_EVER = {
    "sketch-lines": frozenset({(240.0, 200.0)}),
    "cad-lines": frozenset({(240.0, 380.0), (240.0, 460.0)}),
    "line-watcher": frozenset({(560.0, 290.0), (560.0, 200.0)}),
    "revit-walls": frozenset({(880.0, 290.0), (880.0, 200.0)}),
    "revit-sessions": frozenset({(880.0, 470.0), (880.0, 460.0)}),
}


def plan_canvas_spacing(snapshot, registry, owned, seed_roots, drawn=None) -> dict:
    """New points for seeded canvas cards that overlap another card.

    Judged on the user's canvas only: ``drawn`` is what the view's top
    canvas shows (its visibility index); the application's cards are drawn
    in the System view. Only a card still standing exactly on a point a
    seed table gave it may move; a card the user placed by hand -- marked
    ``placed = user``, or simply standing anywhere else -- never moves. An overlapping seed card goes back to its own seed-table
    point when that is free, else to the first free slot. Reads only.
    """
    from .canvas_placement import card_size, drawn_rows, free_slot, intersects
    from .universal_application import _USER_PLACEMENT, _user_canvas_root

    table = {properties[_SEED_MARKER]: (x, y) for _t, x, y, properties in _SEED}

    def rect(root):
        rows = owned.get(root) or {}
        try:
            x = float(rows["position_x"][1]); y = float(rows["position_y"][1])
        except (KeyError, TypeError, ValueError):
            return None
        return (x, y, *card_size(rows.get("engine", ("", ""))[1], drawn_rows(rows)))

    rects = {}
    candidates = _canvas_roots(snapshot, registry)[0] if drawn is None else drawn
    for root in candidates:
        if root in seed_roots or _user_canvas_root(snapshot, registry, root):
            found = rect(root)
            if found is not None:
                rects[root] = found
    order = sorted(
        (root for root in seed_roots if root in rects),
        key=lambda root: list(table).index(
            ((owned.get(root) or {}).get(_SEED_MARKER) or ("", ""))[1]
        ) if ((owned.get(root) or {}).get(_SEED_MARKER) or ("", ""))[1] in table else 99,
    )
    def on_a_seed_point(root):
        marker = ((owned.get(root) or {}).get(_SEED_MARKER) or ("", ""))[1]
        points = set(_SEED_POINTS_EVER.get(marker, ()))
        if marker in table:
            points.add(table[marker])
        return (rects[root][0], rects[root][1]) in points

    movable = [
        root for root in order
        if ((owned.get(root) or {}).get("placed") or ("", ""))[1] != _USER_PLACEMENT
        and on_a_seed_point(root)
    ]

    def clashes(root, rect_):
        return any(intersects(rect_, value) for key, value in rects.items() if key != root)

    moves = {}
    # First each overlapping card tries its own seed-table point (a grid in
    # which no two cards meet), so the chain keeps its left-to-right reading.
    for root in movable:
        mine = rects[root]
        home = table.get(((owned.get(root) or {}).get(_SEED_MARKER) or ("", ""))[1])
        if home is None or not clashes(root, mine) or (mine[0], mine[1]) == home:
            continue
        trial = (home[0], home[1], mine[2], mine[3])
        if not clashes(root, trial):
            rects[root] = trial
            moves[root] = home
    # Whatever still overlaps takes the first free slot.
    for root in movable:
        mine = rects[root]
        if clashes(root, mine):
            others = [value for key, value in rects.items() if key != root]
            point = free_slot(others, (mine[2], mine[3]))
            rects[root] = (point[0], point[1], mine[2], mine[3])
            moves[root] = point
    return moves


def migration_tombstones(snapshot, registry) -> set:
    """Every root the canvas-content migration tombstoned (graph facts only)."""
    member_role = registry.roles["member"]
    found = set()
    # Every batch any run committed, finished or not: the final record names
    # them only once the whole move is done.
    for batch in _migration_batch_relations(snapshot):
        found.update(
            part.participant_id
            for part in read_relation(snapshot, batch, budget=4096)
            if part.role_id == member_role
        )
    return found


_SETTLING_GUARD = __import__("threading").Lock()
_SETTLING: "dict" = __import__("weakref").WeakKeyDictionary()


def settle_canvas_content(store, registry, *, authentication_context=None,
                          dry_run: bool = False, batch_size: int = 12,
                          lock=None, guard=None, pause: float = 0.05,
                          after_batch=None) -> dict:
    """One migration run per graph at a time; see _settle_canvas_content.

    The launcher's background thread and seed_wall_pipeline both call this.
    A second caller while a run is in flight returns at once and writes
    nothing (``in_flight``); two runs planned from different heads would
    tombstone the same copy in two batches and race for the final record.
    """
    with _SETTLING_GUARD:
        turn = _SETTLING.get(store)
        if turn is None:
            turn = _SETTLING[store] = __import__("threading").Lock()
    if not turn.acquire(blocking=False):
        return {"moved": 0, "tombstoned": 0, "skipped": [], "committed": False,
                "batches": [], "in_flight": True}
    try:
        return _settle_canvas_content(
            store, registry, authentication_context=authentication_context,
            dry_run=dry_run, batch_size=batch_size, lock=lock, guard=guard,
            pause=pause, after_batch=after_batch)
    finally:
        turn.release()


def _settle_canvas_content(store, registry, *, authentication_context=None,
                           dry_run: bool = False, batch_size: int = 12,
                           lock=None, guard=None, pause: float = 0.05,
                           after_batch=None) -> dict:
    """Admitted migration: move canvas content into its lens, in small batches.

    Smoothness is a gate: the application opens and answers while this
    runs. Each batch is PLANNED AGAIN from its own base snapshot -- the
    owner properties, the duplicate sets, what is wired, pinned or grouped
    -- then prepared and proved WITHOUT the mutation lock; ``lock`` (the
    owner's mutation lock) is held only for the revision check and the one
    commit of that batch, and the time it is held is measured and returned.
    ``guard`` (a callable returning a context manager) replaces ``lock`` when
    the commit needs more than one lock: the launcher passes the owner's
    mutation lock THEN the broker's live context, the order every admitted
    write takes. A batch whose base moved underneath it is planned again.
    So a card the user edits, wires, pins, groups or moves while this runs
    is judged by what it is at the commit that would touch it: it drops out
    of the plan (reported as changed) instead of being tombstoned or moved
    on an old reading. Between batches the thread yields (``pause``).

    For every planned root: it leaves the level it stands on through the
    same retraction the delete gesture uses (the view's top canvas, or the
    scope relation it was placed in); on the top canvas its ``member``
    incidence also leaves ``app:canvas`` (its property incidences stay,
    exactly the shape of a card placed inside a scope); and it becomes a
    member of its lens with its properties. A duplicate is given no new
    home: a batch relation names it, beside the reason. A skip is recorded
    (a relation) so the next open does not retry it unchanged. The final
    record (``CANVAS_CONTENT_MIGRATION_ROOT``, also the done marker) names
    every batch any run committed, and is written only when nothing is left
    behind. Every root and all history remain. The caller declares the
    migration intent (in the thread that runs this).
    """
    import contextlib
    import time as _time
    import uuid as _uuid

    from .cell_authorization import AuthorizationDenied
    from .cell_identity import record_authority_relationship_revocation
    from .universal_application import (
        _apply_view_scope_exposure,
        _prepare_active_top_scope_exposure_extension,
        _session_canvas_roots,
        _view_session_for_context,
        _visibility_scope_projection,
        advance_canvas_accelerator,
        note_canvas_membership_change,
        overlay_read_snapshot,
        prepare_universal_retraction,
    )
    from .universal_cell import Snapshot

    if guard is None:
        held_lock = contextlib.nullcontext() if lock is None else lock
        guard = lambda: held_lock
    first = store.snapshot()
    if CANVAS_CONTENT_MIGRATION_ROOT in first.cells:
        return {"moved": 0, "tombstoned": 0, "skipped": [], "committed": False,
                "batches": [], "done": True}
    view_session, _context = _view_session_for_context(
        registry, authentication_context
    )
    member_role = registry.roles["member"]
    visible_role = registry.roles["visible"]
    base = {"snapshot": first}
    # The owner properties of the plan the current batch was made from.
    ctx = {"owned": {}}
    state = {"create": {}, "replace": {}, "revocations": [], "grants": []}

    def drawn_now(graph):
        return tuple(
            member.participant_id
            for member in read_relation(graph, view_session.visibility_root, budget=300_000)
            if member.role_id == visible_role
        )

    def current():
        # The staged graph at the batch's BASE revision: the batch commits
        # once against it, so every grant and revocation prepared on it
        # expects exactly that commit.
        snapshot = base["snapshot"]
        overlay = overlay_read_snapshot(
            snapshot, create=tuple(state["create"].values()),
            replace=tuple(state["replace"].values()),
        )
        return Snapshot(snapshot.revision, overlay.cells)

    def absorb(new_create=(), new_replace=()):
        for cell in new_create:
            state["create"][cell.id] = cell
        for cell in new_replace:
            if cell.id in state["create"]:
                state["create"][cell.id] = cell
            else:
                state["replace"][cell.id] = cell

    def leave(root, scope):
        """Take ``root`` off the level it stands on."""
        staged = current()
        relation = view_session.visibility_root if scope is None else scope
        placed_role = visible_role if scope is None else member_role
        if any(
            member.participant_id == root and member.role_id == placed_role
            for member in read_relation(staged, relation, budget=300_000)
        ):
            made, changed, revoked, granted = prepare_universal_retraction(
                staged, registry, view_session, root, scope, lens_move=True,
                # A top-canvas retraction is proved once per batch, below. A
                # nested one still proves its level, which is how an
                # unopenable scope is told apart.
                prove=scope is not None,
            )
            absorb(made, changed)
            state["revocations"].extend(revoked)
            state["grants"].extend(granted)
        if scope is None:
            staged = current()
            leaving = tuple(
                member.incidence_id
                for member in read_relation(staged, registry.canvas_root, budget=300_000)
                if member.role_id == member_role and member.participant_id == root
            )
            if leaving:
                patch = prepare_remove_relation_members(
                    staged, registry.canvas_root, leaving, budget=300_000
                )
                absorb((), patch.replace)

    def leave_scope(root, scope):
        """Take ``root`` out of a scope relation the canvas cannot open.

        A scope over its bounded projection (the Workbench holds every
        agent session) cannot be read by the nested reader the retraction
        proves against, so the card's own incidences are removed directly:
        its member row, its property rows, and the wires ending on the
        interfaces it owns. The top-canvas proof still runs before commit.
        """
        from .universal_application import _canvas_interface_owner_in

        staged = current()
        owners = frozenset((root,))
        properties = {relation for relation, _value in (ctx["owned"].get(root) or {}).values()}
        doomed = []
        for member in read_relation(staged, scope, budget=300_000):
            participant = member.participant_id
            if member.role_id == member_role and participant == root:
                doomed.append(member.incidence_id)
            elif member.role_id == registry.roles["property"] and participant in properties:
                doomed.append(member.incidence_id)
            elif member.role_id == registry.roles["relation"]:
                ends = [
                    part.participant_id
                    for part in read_relation(staged, participant, budget=64)
                    if part.role_id in (registry.roles["source"], registry.roles["target"])
                ] if participant in staged.cells else []
                if any(
                    end == root or _canvas_interface_owner_in(staged, registry, end, owners)
                    for end in ends
                ):
                    doomed.append(member.incidence_id)
        if doomed:
            patch = prepare_remove_relation_members(
                staged, scope, tuple(doomed), budget=300_000
            )
            absorb((), patch.replace)

    def arrive(root, scope):
        """Make ``root`` a member of ``scope`` with its properties."""
        staged = current()
        held = {
            (member.role_id, member.participant_id)
            for member in read_relation(staged, scope, budget=300_000)
        }
        wanted = tuple(pair for pair in (
            (member_role, root),
            *((registry.roles["property"], relation)
              for relation, _value in (ctx["owned"].get(root) or {}).values()),
        ) if pair not in held)
        if not wanted:
            return
        if (member_role, root) not in held:
            made, changed, granted = _prepare_active_top_scope_exposure_extension(
                staged, registry, view_session, root, scope
            )
            absorb(made, changed)
            state["grants"].extend(granted)
            staged = current()
        patch = prepare_append_relation_members(staged, scope, wanted, budget=300_000)
        absorb(patch.create, patch.replace)

    def place(root, x, y):
        """Write a card's two position values: the gesture a hand move makes."""
        staged = current()
        for label, value in (("position_x", x), ("position_y", y)):
            relation = (ctx["owned"].get(root) or {}).get(label)
            if relation is None:
                continue
            value_root = _one_for_role(
                read_relation(staged, relation[0], budget=64), registry.roles["value"]
            )
            if value_root is None or value_root not in staged.cells:
                continue
            held = staged.cells[value_root]
            absorb((), (Cell(held.id, held.link0, held.link1,
                             str(float(value)).encode("utf-8")),))

    def settle_in(root, scope):
        """A card arriving in a lens lands in free space there, never on a card."""
        from .canvas_placement import card_size, drawn_rows, free_slot, intersects
        rows = ctx["owned"].get(root) or {}
        try:
            x = float(rows["position_x"][1]); y = float(rows["position_y"][1])
        except (KeyError, TypeError, ValueError):
            return
        size = card_size(rows.get("engine", ("", ""))[1], drawn_rows(rows))
        staged = current()
        others = [rect for key, rect in scope_card_bounds(staged, registry, scope).items()
                  if key != root]
        if any(intersects((x, y, *size), rect) for rect in others):
            place(root, *free_slot(others, size))

    def one(action, root, origin, target, why, moved, tombstoned):
        if origin is None:
            leave(root, origin)
        else:
            try:
                leave(root, origin)
            except InvalidCell as refusal:
                if "openable" not in str(refusal) and "bounded" not in str(refusal):
                    raise
                leave_scope(root, origin)
        if action == "move" and target is None:
            moved.append({"root": root, "scope": None, "why": why})
        elif target is not None:
            arrive(root, target)
            settle_in(root, target)
            moved.append({"root": root, "scope": target, "why": why})
        else:
            tombstoned.append({
                "root": root, "from": origin or registry.canvas_root, "why": why,
            })

    def work_digest(action, root, origin, target, owned):
        return _migration_digest(["work", action, root, origin, target, sorted(
            (label, value) for label, (_relation, value) in (owned.get(root) or {}).items())])

    def planned(snapshot):
        """The whole plan at ``snapshot``: the work left, and what is skipped.

        A duplicate set the user touched in more than one copy is resolved
        "keep both" once recorded (coordinator decision 2026-09-29): it is
        never asked about or retried, and it does not hold the run open. A
        move the graph refused is recorded too and is not retried unchanged;
        it is re-planned only once its card changes (a new digest), and it
        does hold the run open ("outstanding")."""
        owned = _owner_properties(snapshot, registry)
        plan = plan_canvas_content(snapshot, registry, owned)
        work = [
            *(("move", root, origin, target, why)
              for root, origin, target, why in plan["moves"]),
            *(("tombstone", root, origin, None, "duplicate of " + kept)
              for root, origin, kept in plan["tombstones"]),
        ]
        recorded = lambda digest: _MIGRATION_SKIP_PREFIX + digest in snapshot.cells
        new_skips = [skip for skip in plan["skips"] if not recorded(skip["digest"])]
        parked = [item for item in work
                  if recorded(work_digest(*item[:4], owned))]
        work = [item for item in work if item not in parked]
        outstanding = len(parked)
        return owned, plan, work, new_skips, outstanding

    size = max(1, int(batch_size))
    refused: dict = {}        # (action, root) -> this run's refusal record
    executed: set = set()     # (action, root) this run committed
    first_work: set | None = None
    moved_all: list[dict[str, str]] = []
    tombstoned_all: list[dict[str, str]] = []
    spaced: dict = {}
    batches: list[dict[str, object]] = []
    latest_skips: list = []
    outstanding = 0
    carried = False
    number = 0
    while True:
        finished = False
        for attempt in range(5):
            started = _time.perf_counter()
            base["snapshot"] = store.snapshot()
            owned, plan, work, latest_skips, outstanding = planned(base["snapshot"])
            ctx["owned"] = owned
            plan_seconds = _time.perf_counter() - started
            if first_work is None:
                first_work = {(item[0], item[1]) for item in work}
            if not dry_run:
                # Already committed by this run and planned again: the move
                # did not take effect. Say so once instead of looping.
                for action, root, origin, target, _why in work:
                    if (action, root) in executed and (action, root) not in refused:
                        refused[(action, root)] = {
                            "root": root, "action": action,
                            "why": "the move did not take effect",
                            "digest": work_digest(action, root, origin, target, owned),
                        }
            work = [item for item in work
                    if (item[0], item[1]) not in refused
                    and not (dry_run and (item[0], item[1]) in executed)]
            chunk = work[:size]
            last = len(work) <= size
            off_canvas = {root for _a, root, origin, _t, _w in chunk if origin is None}
            if not chunk and not plan_canvas_spacing(
                base["snapshot"], registry, owned, set(plan.get("kept", ())),
                drawn_now(base["snapshot"]),
            ):
                finished = True
                break
            state.update(create={}, replace={}, revocations=[], grants=[])
            moved: list[dict[str, str]] = []
            tombstoned: list[dict[str, str]] = []
            failed: list[dict[str, str]] = []
            for action, root, origin, target, why in chunk:
                saved = {
                    "create": dict(state["create"]), "replace": dict(state["replace"]),
                    "revocations": list(state["revocations"]),
                    "grants": list(state["grants"]),
                }
                try:
                    one(action, root, origin, target, why, moved, tombstoned)
                except (InvalidCell, AuthorizationDenied) as refusal:
                    # The graph refused this one move: it is skipped and
                    # recorded. Anything else is a defect and stops the run.
                    state.update(saved)
                    failed.append({"root": root, "action": action,
                                   "why": str(refusal)[:300],
                                   "digest": work_digest(action, root, origin, target, owned)})
            relation_root = None
            if tombstoned:
                relation_root = "%s:batch:%s" % (
                    CANVAS_CONTENT_MIGRATION_ROOT, _uuid.uuid4().hex)
                reason_root = relation_root + ":why"
                absorb((
                    Cell(reason_root, NULL_CELL_ID, NULL_CELL_ID, (
                        "duplicate seed cards tombstoned: %s" % "; ".join(
                            "%s is a %s" % (item["root"], item["why"])
                            for item in tombstoned)
                    ).encode("utf-8")),
                    *compose_relation_cells((
                        (registry.roles["why"], reason_root),
                        (registry.roles["scope"], registry.canvas_root),
                        *((member_role, item["root"]) for item in tombstoned),
                    ), relation_id=relation_root).cells,
                ))
            chunk_spaced = {}
            if last:
                # The seed cards kept on the canvas stop overlapping (the
                # gesture a hand move makes); nothing the user moved moves.
                chunk_spaced = plan_canvas_spacing(
                    base["snapshot"], registry, owned, set(plan.get("kept", ())),
                    drawn_now(current()),
                )
                for root, (x, y) in chunk_spaced.items():
                    place(root, x, y)
            # Proved by the reader the next boot runs, before anything is
            # written, and outside the lock. A batch beside a user group signs
            # the group's grants through the new exposure entry, and a grant
            # counts only once it is recorded after its commit (as group,
            # ungroup and retraction record theirs). Such a batch is proved
            # before the commit the way a card taken off beside a group is --
            # the projection and the exposure partition -- and by the whole
            # reader right after the commit, over the committed graph.
            staged = current()
            if state["grants"]:
                visible, relations, properties, _interfaces = (
                    _visibility_scope_projection(staged, registry, view_session)
                )
                _apply_view_scope_exposure(
                    staged, registry, view_session, registry.canvas_root,
                    (visible, relations, properties),
                )
            else:
                _session_canvas_roots(staged, registry, view_session)
            prepared = _time.perf_counter() - started
            if dry_run:
                held = 0.0
                committed = False
            else:
                with guard():
                    locked = _time.perf_counter()
                    stale = store.revision != base["snapshot"].revision
                    if not stale:
                        store.commit(
                            base["snapshot"].revision,
                            create=tuple(state["create"].values()),
                            replace=tuple(state["replace"].values()),
                        )
                    held = _time.perf_counter() - locked
                if stale:
                    continue
                committed = True
                committed_revision = store.revision
                broker = registry.authorization.relationship_broker
                for grant in state["grants"]:
                    broker.record_generation(grant.root_id, grant.generation)
                for revocation in state["revocations"]:
                    record_authority_relationship_revocation(
                        broker, revocation, committed_revision)
                if state["grants"]:
                    _session_canvas_roots(store.snapshot(), registry, view_session)
                # Accelerator only: the remembered canvas answer is carried
                # across this batch instead of rebuilt by the next read. The
                # note is checked against the graph by the reader.
                note_canvas_membership_change(
                    store,
                    base_revision=base["snapshot"].revision,
                    revision=committed_revision,
                    # The store commits only Cells whose content differs;
                    # the note names exactly those, or it would never match.
                    cells=(
                        cell_id
                        for cell_id, cell in (
                            *state["create"].items(), *state["replace"].items()
                        )
                        if base["snapshot"].cells.get(cell_id) != cell
                    ),
                    removed=(
                        *(item["root"] for item in moved if item["root"] in off_canvas),
                        *(item["root"] for item in tombstoned
                          if item["from"] == registry.canvas_root),
                    ),
                    positions={
                        root: point for root, point in chunk_spaced.items()
                    },
                    scopes={
                        scope for _a, _r, origin, target, _w in chunk
                        for scope in (origin, target) if scope is not None
                    },
                    revoked=(
                        revocation.relationship_root
                        for revocation in state["revocations"]
                    ),
                    granted=(grant.root_id for grant in state["grants"]),
                )
                try:
                    carried = advance_canvas_accelerator(
                        store, registry,
                        authentication_context=authentication_context,
                    )
                except Exception:
                    carried = False
            break
        else:
            raise InvalidCell("canvas-content batch %d kept going stale" % number)
        if finished:
            break
        for item in failed:
            refused[(item["action"], item["root"])] = item
        refused_now = {(item["action"], item["root"]) for item in failed}
        executed.update((action, root) for action, root, *_ in chunk
                        if (action, root) not in refused_now)
        moved_all.extend(moved)
        tombstoned_all.extend(tombstoned)
        spaced.update(chunk_spaced)
        batches.append({
            "batch": number, "roots": len(chunk), "attempts": attempt + 1,
            "plan_seconds": round(plan_seconds, 3),
            "prepare_seconds": round(prepared, 3), "lock_seconds": round(held, 4),
            "canvas_carried": bool(committed and carried),
            "cells": [len(state["create"]), len(state["replace"])],
            "committed": committed,
        })
        if after_batch is not None:
            after_batch(batches[-1])
        if not dry_run:
            print("  canvas     : batch %d committed, %d root(s), plan %.1f s, lock held "
                  "%.1f ms, prepared %.1f s, canvas answer %s" % (
                      number + 1, len(chunk), plan_seconds, held * 1000, prepared,
                      "carried" if carried else "left to rebuild"),
                  flush=True)
            _time.sleep(max(0.0, float(pause)))
        number += 1
        if last:
            break
    # Planned at the start but neither done nor refused: its card changed
    # while this ran (edited, wired, pinned, grouped, moved), so the plan
    # made at its batch no longer held it.
    changed = sorted(
        (action, root) for action, root in (first_work or set())
        if (action, root) not in executed and (action, root) not in refused
    )
    new_skips = [
        *({"root": ", ".join(skip["roots"]), "roots": list(skip["roots"]),
           "action": "keep", "why": skip["why"], "digest": skip["digest"]}
          for skip in latest_skips),
        *({**item, "roots": [item["root"]]} for item in refused.values()),
    ]
    # Done when nothing is left behind: no move refused now or earlier. A
    # duplicate set kept "keep both" is resolved, not left behind. That
    # includes a first look that finds nothing to do at all, so the next
    # open does not plan again.
    done = not refused and not outstanding
    kept_records = [_MIGRATION_SKIP_PREFIX + skip["digest"] for skip in plan["skips"]]
    recorded_now = 0
    record_written = False
    if not dry_run and (new_skips or done):
        for attempt in range(5):
            head = store.snapshot()
            cells = []
            for skip in new_skips:
                skip_root = _MIGRATION_SKIP_PREFIX + skip["digest"]
                if skip_root in head.cells:
                    continue
                reason_root = skip_root + ":why"
                cells.append(Cell(reason_root, NULL_CELL_ID, NULL_CELL_ID, ((
                    "both copies kept, never retried: %s (%s)"
                    if skip.get("action") == "keep" else
                    "canvas content left in place: %s (%s)")
                    % (", ".join(skip["roots"]), skip["why"])).encode("utf-8")))
                cells.extend(compose_relation_cells((
                    (registry.roles["why"], reason_root),
                    (registry.roles["scope"], registry.canvas_root),
                    *((member_role, root) for root in skip["roots"] if root in head.cells),
                ), relation_id=skip_root).cells)
            if done and CANVAS_CONTENT_MIGRATION_ROOT not in head.cells:
                every_batch = _migration_batch_relations(head)
                reason_root = CANVAS_CONTENT_MIGRATION_ROOT + ":why"
                cells.append(Cell(reason_root, NULL_CELL_ID, NULL_CELL_ID, (
                    "canvas content settled in its lenses; %d batch relation(s) "
                    "name the tombstoned duplicate seed cards; %d duplicate set(s) "
                    "the user touched in more than one copy: both kept"
                    % (len(every_batch), len(kept_records))
                ).encode("utf-8")))
                cells.extend(compose_relation_cells((
                    (registry.roles["why"], reason_root),
                    (registry.roles["scope"], registry.canvas_root),
                    *((member_role, batch) for batch in every_batch),
                    *((member_role, kept) for kept in kept_records),
                ), relation_id=CANVAS_CONTENT_MIGRATION_ROOT).cells)
            if not cells:
                break
            with guard():
                stale = store.revision != head.revision
                if not stale:
                    store.commit(head.revision, create=tuple(cells))
            if stale:
                continue
            record_written = True
            recorded_now = len(new_skips)
            note_canvas_membership_change(
                store, base_revision=head.revision, revision=store.revision,
                cells=(cell.id for cell in cells),
            )
            try:
                advance_canvas_accelerator(
                    store, registry, authentication_context=authentication_context)
            except Exception:
                pass
            break
        else:
            raise InvalidCell("canvas-content record kept going stale")
    by_reason: dict[str, int] = {}
    for item in moved_all:
        key = item["why"].split(":", 1)[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    if not dry_run and batches:
        print(
            "  canvas     : %d card(s) moved to their lens %s, %d duplicate(s) "
            "tombstoned, %d overlapping card(s) re-placed, %d skipped, %d changed "
            "while it ran, %d batch(es), longest lock %.1f ms" % (
                len(moved_all), by_reason, len(tombstoned_all), len(spaced),
                len(new_skips), len(changed), len(batches),
                max(batch["lock_seconds"] for batch in batches) * 1000),
            flush=True,
        )
    return {
        "moved": len(moved_all), "tombstoned": len(tombstoned_all),
        "skipped": new_skips, "recorded_skips": outstanding + recorded_now,
        "changed": [{"action": action, "root": root} for action, root in changed],
        "done": bool(done and not dry_run),
        "committed": bool(not dry_run and (batches or record_written)),
        "revision": store.revision, "by_reason": by_reason,
        "moves": moved_all, "tombstones": tombstoned_all,
        "spaced": {root: list(point) for root, point in spaced.items()},
        "batches": batches,
    }


# ------------------------------------------------ the graph-held node library --
# SPEC 4.5: catalogue membership, category and order are graph relations. The
# engine-card library lives here: one root relation whose members are the
# sections in order, each section a relation whose members are its cards in
# order, each card a relation holding its item id, title, summary, engine and
# default parameters. library_engines.LIBRARY_PRESENTATION and
# LIBRARY_ITEM_ENGINES are only the seed that installs these relations once;
# GET /api/universal/node-library reads the graph, so editing a relation
# changes the served library.
ENGINE_LIBRARY_ROOT = "app:engine-library:v1"
_ENGINE_LIBRARY_ROLES = {
    name: "app:engine-library:role:%s:v1" % name
    for name in ("section", "entry", "label", "item", "title", "summary",
                 "engine", "params")
}


def engine_library_section_root(category: str) -> str:
    return "app:engine-library:section:%s" % category


def engine_library_entry_root(item: str) -> str:
    return "app:engine-library:entry:%s" % item


def _text_cell(root: str, text: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, str(text).encode("utf-8"))


def _entry_cells(item: str, title: str, summary: str, wiring) -> list:
    import json as _json

    roles = _ENGINE_LIBRARY_ROLES
    entry = engine_library_entry_root(item)
    fields = (
        ("item", item), ("title", title), ("summary", summary),
        ("engine", wiring["engine"]),
        ("params", _json.dumps(wiring["params"], sort_keys=True)),
    )
    cells = [_text_cell(entry + ":" + name, value) for name, value in fields]
    relation = compose_relation_cells(
        tuple((roles[name], entry + ":" + name) for name, _value in fields),
        relation_id=entry,
    )
    return [*cells, *relation.cells]


def seed_engine_library(store, registry) -> int:
    """Admitted migration: install the node library as graph relations.

    Installs what the seed lists and the graph does not hold yet, in ONE
    commit; a card whose entry relation already exists is never touched
    (an edit or a removal made on the graph stands). A graph holding every
    entry makes no commit and returns 0. The caller declares the intent.
    """
    from .library_engines import LIBRARY_ITEM_ENGINES, LIBRARY_PRESENTATION

    roles = _ENGINE_LIBRARY_ROLES
    snapshot = store.snapshot()
    create: list = []
    replace: dict = {}
    added = 0
    root_members = []
    if ENGINE_LIBRARY_ROOT not in snapshot.cells:
        create.extend(_text_cell(role, name) for name, role in roles.items()
                      if role not in snapshot.cells)
    for category, rows in LIBRARY_PRESENTATION:
        section = engine_library_section_root(category)
        new_entries = []
        for item, title, summary in rows:
            wiring = LIBRARY_ITEM_ENGINES.get(item)
            if wiring is None or engine_library_entry_root(item) in snapshot.cells:
                continue
            create.extend(_entry_cells(item, title, summary, wiring))
            new_entries.append((roles["entry"], engine_library_entry_root(item)))
            added += 1
        if section not in snapshot.cells:
            if not new_entries:
                continue
            create.append(_text_cell(section + ":label", category))
            create.extend(compose_relation_cells(
                ((roles["label"], section + ":label"), *new_entries),
                relation_id=section,
            ).cells)
            root_members.append((roles["section"], section))
        elif new_entries:
            patch = prepare_append_relation_members(
                snapshot, section, new_entries, budget=100_000)
            create.extend(patch.create)
            replace.update({cell.id: cell for cell in patch.replace})
    if ENGINE_LIBRARY_ROOT not in snapshot.cells:
        if not root_members:
            return 0
        create.extend(compose_relation_cells(
            tuple(root_members), relation_id=ENGINE_LIBRARY_ROOT).cells)
    elif root_members:
        patch = prepare_append_relation_members(
            snapshot, ENGINE_LIBRARY_ROOT, root_members, budget=100_000)
        create.extend(patch.create)
        replace.update({cell.id: cell for cell in patch.replace})
    if not create and not replace:
        return 0
    store.commit(snapshot.revision, create=tuple(create), replace=tuple(replace.values()))
    return added


def _read_engine_library_entry(snapshot, entry_root: str):
    import json as _json

    roles = _ENGINE_LIBRARY_ROLES
    held = {}
    for member in read_relation(snapshot, entry_root, budget=64):
        for name, role in roles.items():
            if member.role_id == role:
                held[name] = _text(snapshot, member.participant_id)
    if not {"item", "title", "summary", "engine", "params"} <= set(held):
        return None
    try:
        params = _json.loads(held["params"])
    except ValueError:
        return None
    if not isinstance(params, dict):
        return None
    return {"id": held["item"], "title": held["title"], "sub": held["summary"],
            "engine": held["engine"], "params": {str(k): str(v) for k, v in params.items()}}


def read_engine_library(snapshot):
    """The node library as the graph holds it, or None before it is installed.

    Sections in their relation order; cards in their section order; the
    category of a card is the section that holds it. A card whose engine
    this build does not run is marked noEngine, never dropped.
    """
    from .library_engines import engine_sockets
    from .pipeline_engines import PIPELINE_ENGINES

    if ENGINE_LIBRARY_ROOT not in snapshot.cells:
        return None
    roles = _ENGINE_LIBRARY_ROLES
    groups = []
    for section in read_relation(snapshot, ENGINE_LIBRARY_ROOT, budget=256):
        if section.role_id != roles["section"]:
            continue
        members = read_relation(snapshot, section.participant_id, budget=1024)
        label = next((_text(snapshot, m.participant_id) for m in members
                      if m.role_id == roles["label"]), "")
        items = []
        for member in members:
            if member.role_id != roles["entry"]:
                continue
            entry = _read_engine_library_entry(snapshot, member.participant_id)
            if entry is None:
                continue
            entry["cat"] = label
            entry["sockets"] = {side: list(names)
                                for side, names in engine_sockets(entry["engine"]).items()}
            if entry["engine"] not in PIPELINE_ENGINES:
                entry["noEngine"] = True
                entry["reason"] = "engine %s is not in this build" % entry["engine"]
            items.append(entry)
        groups.append({"cat": label, "items": items})
    return groups


def engine_library_entry(snapshot, item: str):
    """One card as the graph holds it (engine and defaults), or None."""
    root = engine_library_entry_root(str(item or ""))
    if root not in snapshot.cells:
        return None
    return _read_engine_library_entry(snapshot, root)

__all__ = ["run_universal_pipeline", "seed_wall_pipeline", "project_atlas_map", "retract_universal_node"]
