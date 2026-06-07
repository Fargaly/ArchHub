"""Subgraph-as-node: wrap N nodes into a single composite that cooks
its inner graph when pulled.

Founder direction (2026-05-13): a user selects ≥2 nodes on the canvas
and presses Cmd-G (Ctrl-G on Windows). Those nodes — plus the wires
between them — get collapsed into ONE composite node of type
`subgraph.user`. The dangling ports (wires that crossed the selection
boundary) become typed inputs/outputs on the composite. When the
composite is pulled by the WorkflowRunner, it instantiates an inner
WorkflowRunner over its captured graph, feeds it the outer inputs at
the right inner ports, runs to the inner sink nodes, and returns the
mapped outputs.

The composite can also be **expanded** — replacing the single
composite node on the canvas with its inner contents, restoring the
internal wires and reconnecting the dangling ports to the original
outer counterparts. Compose + expand are inverse.

Saved composites become Skills: the JSX side serialises the composite
node's `config.inner_graph` to a Workflow via `workflows.library`.
That makes them shareable + re-droppable from the Skills panel.

Public API:
    compose_subgraph(graph_dict, node_ids: list[str]) -> dict
        Returns a new graph dict with the listed nodes collapsed into a
        single `subgraph.user` node. The new node's config carries:
          {
            "inner_graph": {"nodes": [...], "wires": [...]},
            "inner_inputs":  [{port, inner_node, inner_port, type}],
            "inner_outputs": [{port, inner_node, inner_port, type}],
            "title": "Subgraph (N nodes)",
          }
        The outer wires that crossed the selection boundary are rewritten
        so they connect to the composite's new ports.

    expand_subgraph(graph_dict, subgraph_node_id: str) -> dict
        Inverse: replaces the composite node with its inner_graph
        contents, restores the inner wires, and reconnects the outer
        wires that had been rerouted to the composite's facade ports
        back to the original inner endpoints.

    register_subgraph_executor() -> None
        Registers the `subgraph.user` node type with the workflows
        registry. The executor instantiates a nested `WorkflowRunner`
        over `config.inner_graph`, runs all sinks, and maps the outer
        outputs.

This module is **pure data** — no Qt, no JS bindings. The bridge layer
(app/bridge.py) wraps these functions in QWebChannel slots so the JSX
canvas can call them.
"""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any, Optional

from . import registry
from .graph import Port, PortType


# ───────────────────────── port-shape inference ─────────────────────
# Different node shapes show up in the wild:
#   • JSX canvas nodes: `n.outs = [{id, label, t}, ...]`, `n.ins = [...]`
#   • Workflow.to_dict():  `n["outputs"] = [{name, type, ...}]`, `n["inputs"]`
# The compose/expand path has to handle both — JSX sends graphs in the
# canvas shape, while the workflow runner uses the Workflow shape.
# Below helpers normalise port lookup.

def _node_port_type(node: dict, port_id: str, *,
                     side: str = "out") -> str:
    """Return the type tag for a port on a node, in either shape.

    Falls back to `"any"` when the port can't be found — we'd rather
    accept a slightly-wrong type than refuse the compose entirely."""
    if not node or not port_id:
        return "any"
    # Canvas shape: outs / ins lists of {id, t, label}.
    if side == "out":
        for p in (node.get("outs") or node.get("outputs") or []):
            pid = p.get("id") or p.get("name")
            if pid == port_id:
                return p.get("t") or p.get("type") or "any"
    else:
        for p in (node.get("ins") or node.get("inputs") or []):
            pid = p.get("id") or p.get("name")
            if pid == port_id:
                return p.get("t") or p.get("type") or "any"
    return "any"


def _iter_wires(graph: dict) -> list[dict]:
    """Yield wires in canonical canvas shape `{from:[n,p], to:[n,p]}`.

    Accepts either canvas `wires` or workflow `edges` lists, normalising
    workflow edges into the canvas shape for uniform processing."""
    raw = graph.get("wires") or graph.get("edges") or []
    out: list[dict] = []
    for w in raw:
        if "from" in w and "to" in w:
            out.append({
                "from": list(w["from"]),
                "to":   list(w["to"]),
                # Preserve all other fields so save_graph round-trips.
                **{k: v for k, v in w.items()
                    if k not in ("from", "to")},
            })
        elif "src_node" in w and "dst_node" in w:
            out.append({
                "from": [w["src_node"], w["src_port"]],
                "to":   [w["dst_node"], w["dst_port"]],
                **{k: v for k, v in w.items()
                    if k not in ("src_node", "src_port",
                                  "dst_node", "dst_port")},
            })
    return out


def _new_id(prefix: str = "subgraph") -> str:
    """A short, collision-resistant id for new composite nodes."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ───────────────────────── compose ──────────────────────────────────

def compose_subgraph(graph: dict,
                      node_ids: list[str],
                      *,
                      title: str = "",
                      composite_id: Optional[str] = None) -> dict:
    """Collapse the listed nodes into a single `subgraph.user` node.

    Args:
        graph: A graph dict with `nodes` + (`wires` or `edges`).
        node_ids: The ids of nodes to wrap. Must be ≥2 ids that exist
            in `graph["nodes"]`.
        title: Optional title for the composite node.
        composite_id: Optional explicit id (else auto-generated).

    Returns:
        A new graph dict (the input is not mutated) with:
          • the listed nodes removed
          • all wires entirely-inside the selection moved into the
            composite's `inner_graph`
          • outer wires that crossed the boundary rewritten to terminate
            on the composite's new facade ports
          • a single new node of type `subgraph.user` with
            `config.inner_graph`, `config.inner_inputs`,
            `config.inner_outputs`, `ins`, and `outs` populated

    Raises:
        ValueError if `node_ids` is empty, contains unknown ids, or is
        not a list.
    """
    if not isinstance(node_ids, (list, tuple, set)):
        raise ValueError("node_ids must be a list of ids")
    inner_ids = list(dict.fromkeys(node_ids))   # dedupe + preserve order
    if len(inner_ids) < 1:
        raise ValueError("compose_subgraph requires at least 1 node id")

    nodes_by_id = {n.get("id"): n for n in (graph.get("nodes") or []) if n.get("id")}
    missing = [nid for nid in inner_ids if nid not in nodes_by_id]
    if missing:
        raise ValueError(f"unknown node ids: {missing}")

    inner_set = set(inner_ids)
    wires = _iter_wires(graph)

    # Partition wires:
    #   inner — both endpoints inside selection (kept verbatim inside).
    #   in-bound — source outside, dest inside (becomes a composite input).
    #   out-bound — source inside, dest outside (becomes a composite output).
    #   external — both outside (left alone in the new graph).
    inner_wires: list[dict] = []
    inbound:  list[dict] = []
    outbound: list[dict] = []
    external: list[dict] = []
    for w in wires:
        src_in = w["from"][0] in inner_set
        dst_in = w["to"][0]   in inner_set
        if src_in and dst_in:
            inner_wires.append(w)
        elif (not src_in) and dst_in:
            inbound.append(w)
        elif src_in and (not dst_in):
            outbound.append(w)
        else:
            external.append(w)

    # Build composite-facade ports. Each inbound wire becomes ONE input
    # port on the composite (dedup by inner endpoint so two outer wires
    # into the same inner dst_port share one facade port).
    facade_inputs: list[dict] = []
    seen_in: dict[tuple, str] = {}   # (inner_node, inner_port) → facade port id
    for w in inbound:
        inner_node, inner_port = w["to"]
        key = (inner_node, inner_port)
        if key in seen_in:
            continue
        port_id = f"in__{inner_node}__{inner_port}"
        port_type = _node_port_type(nodes_by_id[inner_node],
                                      inner_port, side="in")
        seen_in[key] = port_id
        facade_inputs.append({
            "port":       port_id,
            "inner_node": inner_node,
            "inner_port": inner_port,
            "type":       port_type,
            "label":      f"{inner_node}.{inner_port}",
        })

    facade_outputs: list[dict] = []
    seen_out: dict[tuple, str] = {}
    for w in outbound:
        inner_node, inner_port = w["from"]
        key = (inner_node, inner_port)
        if key in seen_out:
            continue
        port_id = f"out__{inner_node}__{inner_port}"
        port_type = _node_port_type(nodes_by_id[inner_node],
                                      inner_port, side="out")
        seen_out[key] = port_id
        facade_outputs.append({
            "port":       port_id,
            "inner_node": inner_node,
            "inner_port": inner_port,
            "type":       port_type,
            "label":      f"{inner_node}.{inner_port}",
        })

    # Place the composite roughly at the centroid of its inner nodes
    # so the canvas drops it somewhere sensible.
    xs = [float((nodes_by_id[nid].get("x") or
                  (nodes_by_id[nid].get("position") or {}).get("x")
                  or 0)) for nid in inner_ids]
    ys = [float((nodes_by_id[nid].get("y") or
                  (nodes_by_id[nid].get("position") or {}).get("y")
                  or 0)) for nid in inner_ids]
    cx = (sum(xs) / len(xs)) if xs else 0.0
    cy = (sum(ys) / len(ys)) if ys else 0.0

    new_node_id = composite_id or _new_id("subgraph")
    new_title = title or f"Subgraph ({len(inner_ids)} nodes)"

    inner_nodes_copy = [copy.deepcopy(nodes_by_id[nid])
                          for nid in inner_ids]
    inner_graph_payload = {
        "nodes": inner_nodes_copy,
        "wires": [copy.deepcopy(w) for w in inner_wires],
    }

    composite_node = {
        "id":   new_node_id,
        "type": "subgraph.user",
        "cat":  "compose",
        "title": new_title,
        "sub":   f"{len(inner_ids)} nodes · {len(inner_wires)} wires",
        "x":    cx, "y": cy,
        "w":    260, "h": max(120, 90 + 20 * max(
                                  len(facade_inputs), len(facade_outputs))),
        # Canvas-shape ports so the JSX renderer shows sockets.
        "ins":  [{"id": p["port"], "label": p["label"], "t": p["type"]}
                  for p in facade_inputs],
        "outs": [{"id": p["port"], "label": p["label"], "t": p["type"]}
                  for p in facade_outputs],
        "config": {
            "inner_graph":   inner_graph_payload,
            "inner_inputs":  facade_inputs,
            "inner_outputs": facade_outputs,
            "title":         new_title,
        },
    }

    # Build the new outer graph.
    new_nodes = [copy.deepcopy(n) for n in (graph.get("nodes") or [])
                  if n.get("id") not in inner_set]
    new_nodes.append(composite_node)

    new_wires: list[dict] = [copy.deepcopy(w) for w in external]
    for w in inbound:
        inner_node, inner_port = w["to"]
        facade_port = seen_in[(inner_node, inner_port)]
        rewritten = copy.deepcopy(w)
        rewritten["to"] = [new_node_id, facade_port]
        new_wires.append(rewritten)
    for w in outbound:
        inner_node, inner_port = w["from"]
        facade_port = seen_out[(inner_node, inner_port)]
        rewritten = copy.deepcopy(w)
        rewritten["from"] = [new_node_id, facade_port]
        new_wires.append(rewritten)

    new_graph: dict[str, Any] = {
        "nodes": new_nodes,
        "wires": new_wires,
    }
    # Preserve any extra top-level keys (id, name, schema_version…).
    for k, v in (graph or {}).items():
        if k not in ("nodes", "wires", "edges"):
            new_graph[k] = copy.deepcopy(v)
    return new_graph


# ───────────────────────── expand ───────────────────────────────────

def expand_subgraph(graph: dict, subgraph_node_id: str) -> dict:
    """Inverse of `compose_subgraph` — replaces the composite node with
    its inner contents and reconnects the outer wires that were routed
    to its facade ports back to the original inner endpoints.

    Args:
        graph: The outer graph.
        subgraph_node_id: The id of a `subgraph.user` node in `graph`.

    Returns:
        A new graph dict (input not mutated) with:
          • the composite node removed
          • its inner nodes + inner wires restored
          • outer wires that touched its facade ports rewritten to
            terminate at the original inner endpoints

    Raises:
        ValueError if the node is not found or is not a subgraph.user.
    """
    nodes_by_id = {n.get("id"): n for n in (graph.get("nodes") or [])
                    if n.get("id")}
    composite = nodes_by_id.get(subgraph_node_id)
    if composite is None:
        raise ValueError(f"node {subgraph_node_id!r} not found")
    if (composite.get("type") or "") != "subgraph.user":
        raise ValueError(
            f"node {subgraph_node_id!r} is not a subgraph.user node "
            f"(type={composite.get('type')!r})")

    cfg = composite.get("config") or {}
    inner_graph = cfg.get("inner_graph") or {}
    inner_inputs = cfg.get("inner_inputs") or []
    inner_outputs = cfg.get("inner_outputs") or []

    # Build facade-port → inner endpoint maps for rewriting outer wires.
    in_map: dict[str, tuple[str, str]] = {
        p["port"]: (p["inner_node"], p["inner_port"])
        for p in inner_inputs
    }
    out_map: dict[str, tuple[str, str]] = {
        p["port"]: (p["inner_node"], p["inner_port"])
        for p in inner_outputs
    }

    # Reassemble nodes — all outer nodes minus the composite, plus the
    # inner nodes from the composite's stash.
    new_nodes = [copy.deepcopy(n) for n in (graph.get("nodes") or [])
                  if n.get("id") != subgraph_node_id]
    for n in (inner_graph.get("nodes") or []):
        new_nodes.append(copy.deepcopy(n))

    # Reassemble wires:
    #   • outer wires that didn't touch the composite — kept verbatim
    #   • outer wires INTO the composite — rerouted to the inner dst
    #   • outer wires OUT OF the composite — rerouted from the inner src
    #   • inner wires — restored verbatim
    new_wires: list[dict] = []
    for w in _iter_wires(graph):
        src_n, src_p = w["from"]
        dst_n, dst_p = w["to"]
        if src_n != subgraph_node_id and dst_n != subgraph_node_id:
            new_wires.append(copy.deepcopy(w))
            continue
        if src_n == subgraph_node_id and dst_n == subgraph_node_id:
            # Loop wire on the composite itself — drop it. Spec doesn't
            # allow facade→facade wires; they'd indicate a graph that
            # never went through compose_subgraph in the first place.
            continue
        if dst_n == subgraph_node_id:
            inner = in_map.get(dst_p)
            if inner is None:
                # Unknown facade port — keep wire as-is (degenerate).
                new_wires.append(copy.deepcopy(w))
                continue
            rewritten = copy.deepcopy(w)
            rewritten["to"] = [inner[0], inner[1]]
            new_wires.append(rewritten)
        else:    # src_n == composite
            inner = out_map.get(src_p)
            if inner is None:
                new_wires.append(copy.deepcopy(w))
                continue
            rewritten = copy.deepcopy(w)
            rewritten["from"] = [inner[0], inner[1]]
            new_wires.append(rewritten)
    for w in _iter_wires(inner_graph):
        new_wires.append(copy.deepcopy(w))

    new_graph: dict[str, Any] = {
        "nodes": new_nodes,
        "wires": new_wires,
    }
    for k, v in (graph or {}).items():
        if k not in ("nodes", "wires", "edges"):
            new_graph[k] = copy.deepcopy(v)
    return new_graph


# ───────────────────────── add_wire helper ──────────────────────────
# Pure-Python equivalent of the JSX composer `/wire` command path —
# tests pin this so we don't have to test JS.

_WIRE_TOKEN = re.compile(
    r"^\s*([A-Za-z0-9_\-]+)\s*\.\s*([A-Za-z0-9_\-]+)\s*$")


def parse_wire_endpoint(token: str) -> Optional[tuple[str, str]]:
    """Parse `node.port` → `(node, port)` or None on bad input."""
    if not token:
        return None
    m = _WIRE_TOKEN.match(token)
    if not m:
        return None
    return (m.group(1), m.group(2))


def add_wire(graph: dict,
              src_node: str, src_port: str,
              dst_node: str, dst_port: str) -> dict:
    """Add a wire to the graph (idempotent — duplicates are skipped).

    This is the Python equivalent of the JSX `/wire` composer command.
    Tests pin the shape so the JSX path can be verified against it.

    Returns:
        A new graph dict with the wire appended.
    """
    nodes_by_id = {n.get("id"): n for n in (graph.get("nodes") or [])
                    if n.get("id")}
    if src_node not in nodes_by_id:
        raise ValueError(f"unknown src node: {src_node!r}")
    if dst_node not in nodes_by_id:
        raise ValueError(f"unknown dst node: {dst_node!r}")
    new_graph: dict[str, Any] = copy.deepcopy(graph)
    wires = new_graph.setdefault("wires", [])
    # Idempotent — skip exact duplicates.
    for w in wires:
        if "from" in w and "to" in w:
            if (w["from"][0] == src_node and w["from"][1] == src_port and
                    w["to"][0] == dst_node and w["to"][1] == dst_port):
                return new_graph
    wires.append({
        "from": [src_node, src_port],
        "to":   [dst_node, dst_port],
    })
    return new_graph


# ───────────────────────── executor + registration ──────────────────

def _subgraph_executor(config: dict, inputs: dict, ctx: Any) -> dict:
    """Executor for the `subgraph.user` node type.

    Instantiates a nested WorkflowRunner over `config.inner_graph`,
    pulls every inner sink, and returns the mapped outputs.

    Outer inputs at the composite's facade ports get attached to the
    inner graph by seeding the inner sources: we materialise a
    constant-style override per facade-input so the inner consumer
    sees the outer value. This is done by stashing a per-port `_seed`
    on a wrapper node that the inner runner pulls from.

    Seed source — `input` (default) vs `config`:
        Each `inner_inputs` entry seeds an inner port. By default
        (`source` absent or `"input"`) the seed value is pulled from
        the outer `inputs` at the facade port id — the historical
        behaviour, unchanged. An entry MAY instead carry
        ``"source": "config"`` + ``"config_key": k`` to seed that inner
        port from ``config.get(k)`` (the FACADE node's own config)
        rather than from a wire. This lets a rebuilt config-fallback
        node wire BOTH an input-seed and a config-seed into a coalesce
        expression inside the inner graph, reproducing
        ``inputs.get(x) or config.get(x)`` byte-identically — closing
        the gap that the inner runner only ever threads INPUTS, never
        the node's config. A missing/None `config_key` seeds ``None``
        (total-tolerant — never raises).

    Returns a dict mapping the composite's outer output port ids to
    values cooked at the corresponding inner endpoints.
    """
    # Defer the import — `runner` imports `registry`, and `registry`
    # has no compile-time dep on the runner.
    from .runner import WorkflowRunner

    inner_graph = (config or {}).get("inner_graph") or {}
    inner_inputs  = (config or {}).get("inner_inputs")  or []
    inner_outputs = (config or {}).get("inner_outputs") or []

    # Materialise the inner graph + inject a tiny "seed" node per
    # facade input. Each seed exposes a single output port carrying
    # the outer value, and we rewire any inner wire whose source was
    # the (inner_node, inner_port) to instead pull from the seed.
    #
    # Why not pass `inputs` directly into the WorkflowRunner? Because
    # WorkflowRunner walks UPSTREAM from sinks — there's no concept of
    # "external input" except via a node. Seed nodes are the cleanest
    # way to bridge outer values into an inner graph.
    seeded_nodes = list(inner_graph.get("nodes") or [])
    seeded_wires = list(_iter_wires(inner_graph))

    # Per the spec: facade-input `port` → (inner_node, inner_port).
    # An inbound wire in the outer graph terminated at that
    # (inner_node, inner_port). Inside the inner graph there's no wire
    # corresponding to that input (it was an OUTER wire). So we need
    # to seed the inner_port directly.
    cfg = config or {}
    for fp in inner_inputs:
        port_id     = fp["port"]
        inner_node  = fp["inner_node"]
        inner_port  = fp["inner_port"]
        # Seed source: "input" (default — pull from the outer wire) or
        # "config" (pull from the facade node's own config). Any value
        # other than "config" preserves the historical input behaviour.
        if fp.get("source") == "config":
            value = cfg.get(fp.get("config_key"))
        else:
            value = inputs.get(port_id)
        seed_id     = f"__seed__{port_id}"
        # The seed node exposes a single port named "value".
        seeded_nodes.append({
            "id":   seed_id,
            "type": "subgraph._seed",
            "config": {"value": value},
            "outs": [{"id": "value", "label": port_id, "t": fp.get("type", "any")}],
        })
        seeded_wires.append({
            "from": [seed_id, "value"],
            "to":   [inner_node, inner_port],
        })

    # Make sure the seed type is registered (idempotent).
    _ensure_seed_type()

    inner_runner = WorkflowRunner({
        "nodes": seeded_nodes,
        "wires": seeded_wires,
    }, ctx=ctx)

    # Cook each output: pull the inner_node, take its inner_port.
    out: dict[str, Any] = {"status": "ok"}
    for fp in inner_outputs:
        port_id     = fp["port"]
        inner_node  = fp["inner_node"]
        inner_port  = fp["inner_port"]
        try:
            cooked = inner_runner.pull(inner_node)
        except Exception as ex:
            out[port_id] = None
            out["status"] = "error"
            out["error"]  = f"{type(ex).__name__}: {ex}"
            continue
        if isinstance(cooked, dict):
            # Propagate an inner error whether it surfaced DIRECTLY on this
            # output endpoint (status:"error") or was carried here from a
            # deeper inner node (runner.py stamps an upstream miss as
            # status:"upstream_error"). Both mean "an inner cell failed", so
            # the composite must error EXACTLY as a bespoke that early-returned
            # {status:error} would — this lets a data.ensure(on_fail=error)
            # guard sitting UPSTREAM of the output extractors propagate out of
            # the subgraph (the wave-4 type-guard path).
            if cooked.get("status") in ("error", "upstream_error"):
                out[port_id] = None
                out["status"] = "error"
                out["error"]  = cooked.get("error")
            else:
                out[port_id] = cooked.get(inner_port)
        else:
            out[port_id] = cooked

    # If there were no declared outputs, also cook every sink so the
    # caller can still see a result.
    if not inner_outputs:
        out["inner_run"] = inner_runner.run_all()
    return out


def _seed_executor(config: dict, inputs: dict, ctx: Any) -> dict:
    """The seed node simply returns its stashed value on port `value`."""
    return {"status": "ok", "value": (config or {}).get("value")}


_SEED_REGISTERED = False


def _ensure_seed_type() -> None:
    """Register the internal `subgraph._seed` node type once. The seed
    is used to bridge outer values into a nested inner graph during
    subgraph execution. It's private to this module — never appears in
    a user's authored graph."""
    global _SEED_REGISTERED
    if _SEED_REGISTERED:
        return
    if registry.get("subgraph._seed") is not None:
        _SEED_REGISTERED = True
        return
    registry.register(
        registry.NodeSpec(
            type="subgraph._seed", category="control",
            display_name="(seed)",
            description="Internal seed node used by subgraph.user — "
                        "carries an outer value into an inner graph.",
            inputs=[],
            outputs=[Port(name="value", type=PortType.ANY)],
            config_schema={}, icon="·",
        ),
        _seed_executor,
    )
    _SEED_REGISTERED = True


_SUBGRAPH_REGISTERED = False


def register_subgraph_executor() -> None:
    """Register the `subgraph.user` node type with the workflows
    registry. Idempotent — safe to call from package __init__ and
    test setup.

    The registered spec uses ANY-typed ports because the actual ports
    are dynamic (declared per-composite in `config.inner_inputs`/
    `inner_outputs`). The runner pulls the actual ports off the node's
    canvas-shape `ins`/`outs` fields at runtime.
    """
    global _SUBGRAPH_REGISTERED
    if _SUBGRAPH_REGISTERED:
        return
    if registry.get("subgraph.user") is not None:
        _SUBGRAPH_REGISTERED = True
        return
    registry.register(
        registry.NodeSpec(
            type="subgraph.user", category="compose",
            display_name="Subgraph",
            description="Composite node — cooks a captured inner graph "
                        "with outer inputs mapped to inner entry points.",
            inputs=[],                            # dynamic per node
            outputs=[],                           # dynamic per node
            config_schema={
                "type": "object",
                "properties": {
                    "inner_graph":  {"type": "object"},
                    "inner_inputs": {"type": "array"},
                    "inner_outputs":{"type": "array"},
                    "title":        {"type": "string"},
                },
            },
            icon="□",
        ),
        _subgraph_executor,
    )
    _ensure_seed_type()
    _SUBGRAPH_REGISTERED = True


# Auto-register when this module is imported so the workflows package
# `__init__` simply has to `from . import subgraph` to wire it up.
register_subgraph_executor()
