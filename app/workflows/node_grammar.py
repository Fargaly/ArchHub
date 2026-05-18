"""ArchHub node grammar — the canonical primitive node set.

Single source of truth for the redesigned node system. See
`docs/NODE_GRAMMAR.md` for the rationale.

The old model enumerated 80 `LM_LIBRARY` nodes the engine never caught
up to — 0 of 80 ran. This module replaces that catalogue with a SMALL
set of primitive node *kinds*. Users compose everything from these
primitives plus saved Skills.

A primitive is NOT a single node type — it is a family. Its concrete
engine `type` (the registry key `WorkflowRunner` dispatches on) is
selected by the primitive's defining parameter. Example: the `ai`
primitive resolves to `conversation.chat` / `llm.complete` /
`llm.complete_with_tools` / `llm.classify` depending on its `action`.

`engine_type(kind, params)` returns the registry type a placed node
dispatches to (or `None` for the connector / note special cases).

Honesty guarantee: `engine_types` only ever names types that are
*actually registered* in `workflows.registry`. The grounding test
(`tests/test_node_grammar.py`) asserts this — so this file can never
drift back into an aspirational catalogue. A primitive whose executor
does not exist yet is `NEEDS_EXECUTOR` with an empty `engine_types`
and a roadmap-slice note; it is not placeable until the slice ships.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Build status ──────────────────────────────────────────────────────
READY = "ready"                  # every engine type it resolves to exists
NEEDS_EXECUTOR = "needs-executor"  # executor must be built — see `note`
UX_ONLY = "ux-only"              # never executes (e.g. a sticky note)

# Primitives that run via a path OTHER than the node registry. As of
# slice 2 the `connector` master node became a real registry executor
# (`connector.run`), so this set is empty — kept as the mechanism for
# any future non-registry kind. The grounding test exempts members of
# this set from the registry-resolution check.
NON_REGISTRY_KINDS: set[str] = set()


@dataclass(frozen=True)
class Primitive:
    """One primitive node kind in the grammar."""
    kind: str          # canvas-facing node kind, e.g. "connector"
    display: str       # human label
    cat: str           # display group / colour family
    selector: str      # param whose value picks the engine type ("" = fixed)
    engine_types: dict[str, str]  # selector-value -> REGISTERED engine type
                                  # ("" key = the fixed type when selector is "")
    status: str        # READY | NEEDS_EXECUTOR | UX_ONLY
    note: str = ""

    def engine_type_for(self, params: dict | None) -> str | None:
        """The registry type this node dispatches on, given its params.
        None for non-registry kinds, UX-only kinds, or an unresolved
        selector value."""
        if not self.engine_types:
            return None
        if not self.selector:
            return self.engine_types.get("")
        params = params or {}
        return self.engine_types.get(str(params.get(self.selector, "")))


# ── The grammar — ~12 primitives. Order = library display order. ──────
PRIMITIVES: list[Primitive] = [
    Primitive(
        "input", "Input", "input", "",
        {"": "input.parameter"}, READY,
        "graph input; value/file/host-pick are input-UX variants over "
        "the one input.parameter executor",
    ),
    Primitive(
        "constant", "Constant", "input", "",
        {"": "data.constant"}, READY,
        "a literal typed value",
    ),
    Primitive(
        "connector", "Connector", "connector", "",
        {"": "connector.run"}, READY,
        "MASTER host node — one per host. `host` + `op` config select "
        "the operation; the op's ConnectorOp.inputs render in the right "
        "panel. Runs the connector contract through the `connector.run` "
        "engine executor (folds the run_op path into the runner).",
    ),
    Primitive(
        "ai", "AI", "ai", "action",
        {
            "chat": "conversation.chat",
            "complete": "llm.complete",
            "tools": "llm.complete_with_tools",
            "classify": "llm.classify",
        }, READY,
        "MASTER AI node — `action` picks the engine type. vision / "
        "extract / embed actions are added when their executors ship.",
    ),
    Primitive(
        "logic", "Logic", "logic", "kind",
        {
            "if": "control.if",
            "merge": "control.merge",
            "foreach": "control.foreach",
        }, READY,
        "branch / flow; `switch` is a slice-5 follow-up",
    ),
    Primitive(
        "output", "Output", "output", "",
        {"": "output.parameter"}, READY,
        "graph output / sink",
    ),
    Primitive(
        "skill", "Skill", "skill", "",
        {"": "subgraph.user"}, READY,
        "a saved Skill graph placed as ONE node (recursive — "
        "save-as-Skill, then reuse; subgraph reference semantics)",
    ),
    Primitive(
        "filter", "Filter", "shape", "",
        {"": "filter.apply"}, READY,
        "keep / drop list items by a `field` / `op` / `match` predicate",
    ),
    Primitive(
        "transform", "Transform", "shape", "",
        {"": "transform.apply"}, READY,
        "map / reshape data — `op`: count / pick / first / last / "
        "unique / sort / flatten / identity",
    ),
    Primitive(
        "watch", "Watch", "watch", "",
        {"": "watch.preview"}, READY,
        "watcher — passes data through + emits a preview; `as` "
        "(list / table / json / ...) is the JSX render hint",
    ),
    Primitive(
        "trigger", "Trigger", "watch", "on",
        {}, NEEDS_EXECUTOR,
        "fires the graph (manual / schedule / file / host-event) — "
        "workflows/ triggers wired as a node in ROADMAP slice 6",
    ),
    Primitive(
        "note", "Note", "note", "",
        {}, UX_ONLY,
        "comment / sticky — never executes",
    ),
]

# The founder's primitive families (the 2026-05-18 intent). The grammar
# must cover each; the grounding test asserts coverage so a future edit
# cannot quietly drop one.
FOUNDER_FAMILIES = ("input", "output", "connector", "ai", "watch", "logic")

_BY_KIND: dict[str, Primitive] = {p.kind: p for p in PRIMITIVES}


def get_primitive(kind: str) -> Primitive | None:
    return _BY_KIND.get(kind)


def engine_type(kind: str, params: dict | None = None) -> str | None:
    """Registry type a placed node of `kind` dispatches on, given its
    params. None for connector (run_op path), note (UX-only), and any
    not-yet-built primitive."""
    p = _BY_KIND.get(kind)
    return p.engine_type_for(params) if p else None


def _ports_for(engine_t: str) -> dict:
    """The {in, out} ports of an engine type, read from its registry
    NodeSpec. Empty when the type is not registered. The canvas needs
    port ids that MATCH the engine port names — wires reference port
    ids and the runner reads inputs by that name — so the palette
    sources ports from the engine, never invents them."""
    if not engine_t:
        return {"in": [], "out": []}
    try:
        from .registry import get as _reg_get
        tup = _reg_get(engine_t)
    except Exception:
        tup = None
    if not tup:
        return {"in": [], "out": []}
    spec = tup[0]

    def _p(ports) -> list[dict]:
        out: list[dict] = []
        for prt in ports or []:
            ptype = getattr(getattr(prt, "type", None), "name", None) or "ANY"
            out.append({"id": getattr(prt, "name", ""), "type": ptype})
        return out
    return {"in": _p(spec.inputs), "out": _p(spec.outputs)}


def grammar_payload() -> list[dict]:
    """Serialisable grammar — what the bridge exposes to the JSX canvas
    so the library palette is built from ONE source (no JS-side copy
    that can drift). Each entry carries the engine ports (from the
    registry) the canvas needs to draw + wire a placed node. Consumed
    by the `get_node_grammar` bridge slot."""
    out: list[dict] = []
    for p in PRIMITIVES:
        # Representative engine type for the port shape. Selector
        # primitives (ai/logic) refine ports when the selector value
        # changes — that refinement is handled canvas-side.
        rep = next(iter(p.engine_types.values()), "")
        out.append({
            "kind": p.kind, "display": p.display, "cat": p.cat,
            "selector": p.selector, "engine_types": dict(p.engine_types),
            "status": p.status, "note": p.note,
            "ports": _ports_for(rep),
        })
    return out


# ── canvas → engine adapter ───────────────────────────────────────────
def _params_to_config(params) -> dict:
    """Fold a canvas node's `params` into the flat `config` dict the
    engine executors read. Canvas params are a list of `{k, v, ...}`;
    an already-dict form (engine-native nodes) passes through."""
    if isinstance(params, dict):
        return dict(params)
    cfg: dict = {}
    for p in params or []:
        if isinstance(p, dict) and "k" in p:
            cfg[p["k"]] = p.get("v")
    return cfg


def normalize_canvas_graph(graph: dict) -> dict:
    """Stamp each canvas node with the engine `type` + `config` that
    `WorkflowRunner` dispatches on — the canvas/engine "one node model".

    The runner already normalises EDGES ({from,to} ↔ {src_node,...});
    only nodes need this. Rules:
      - a node that already carries a real `type` is left untouched
        (engine-native nodes);
      - otherwise `type` is resolved from the node's `kind` (new model)
        or `cat` (legacy) via `engine_type()`;
      - a node whose kind/cat does not resolve is left WITHOUT a `type`
        — the runner then returns an honest `no executor` error rather
        than fabricating a result.
    `config` is always present, folded from `params` unless already a
    dict. Pure: returns a new graph, never mutates the input."""
    if not isinstance(graph, dict):
        return graph
    out_nodes = []
    for n in graph.get("nodes") or []:
        n = dict(n)
        cfg = (n["config"] if isinstance(n.get("config"), dict)
               else _params_to_config(n.get("params")))
        n["config"] = cfg
        if not n.get("type"):
            kind = n.get("kind") or n.get("cat") or ""
            t = engine_type(kind, cfg)
            if t:
                n["type"] = t
        out_nodes.append(n)
    return {**graph, "nodes": out_nodes}
