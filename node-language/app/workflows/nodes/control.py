"""Control flow nodes — branching, iteration, merging.

Phase 1 is intentionally minimal. The data model supports more, but this
is enough for capturing chat conversations and running them as workflows.

  control.if      — branch on a boolean condition (true / false output ports)
  control.foreach — iterate a list, fan out to a sub-graph (single-step v0)
  control.merge   — coalesce two inputs, prefer first non-null

control.if is the FIRST in-place stem-cell rebuild (G3, the byte-identical
cook). Its logic is no longer a bespoke ``_if_executor`` code blob — it is a
typed sub-graph composed from existing pure cells (``impl.kind=graph``), so the
node's behaviour IS a composition of library primitives, not an opaque
hand-written function. See ``_IF_INNER_GRAPH`` below and
``tests/test_rebuild_in_place_parity.py`` (the parity gate that proved the
rebuild byte-identical to the retired bespoke over its full declared output
contract — true / false / taken — on every input, including the adversarial
ones: None, missing, a non-list, the falsy-string forms, unicode + float).

Why control.if was the clean pick (where the round-1 schedule_builder rebuild
was REFUTED): ``_if_executor`` was a PURE FUNCTION of its two declared input
ports — it read ONLY ``inputs['condition']`` and ``inputs['value']``, its
``config_schema`` was EMPTY (so there was structurally no ``config.get(...)``
fallback for an unwired value to lose), it did NO ``x or []`` falsy-list
normalization, and it had NO ``isinstance``-guard-to-``status:error`` branch
(it has exactly two return shapes, never an error status). So a stem-cell
composition reproduces it EXACTLY on every input — there is nothing for a
pure-cell graph to fail to reproduce.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
# control.if — the in-place stem-cell rebuild (G3 byte-identical cook).
#
# The bespoke truthiness predicate was:
#     truthy = bool(cond) and cond not in ("false", "False", "0", 0, "")
# and the routing was: value -> true (truthy) / false (falsy), plus a `taken`
# label. The rebuild expresses BOTH purely as a sub-graph of existing cells:
#
#   vin    (data.passthrough)  — the `value` entry; fans `value` to gtrue+gfalse
#   pred   (code.expression)   — computes the SAME truthiness `t` from condition
#   gtrue  (code.expression)   — `v if t else None`   -> the `true`  output
#   gfalse (code.expression)   — `None if t else v`   -> the `false` output
#   gtaken (code.expression)   — `"true" if t else "false"` -> the `taken` label
#
# `value` enters through ONE passthrough and fans out via INNER wires (so the
# single facade input seeds a single inner port — the lesson from the round-1
# refutation, where a facade input could only ever seed one inner endpoint).
# `condition` enters `pred`, whose `t` fans to the three gate cells. The facade
# port ids mirror the bespoke signature EXACTLY (condition/value ->
# true/false/taken), so the in-place swap keeps the frozen G4 port contract.
#
# Determinism / total-tolerance: `condition` and `value` are always seeded, so
# every expression has its names defined; `bool(...)`, `... in (...)`, and the
# ternaries never raise on any input — the composition is a pure function with
# no error path, matching the bespoke (which also had none).
_IF_TRUTHY_EXPR = (
    'bool(condition) and condition not in ("false", "False", "0", 0, "")'
)

_IF_INNER_GRAPH = {
    "nodes": [
        {"id": "vin", "type": "data.passthrough", "config": {},
         "ins":  [{"id": "value", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "pred", "type": "code.expression",
         "config": {"expr": _IF_TRUTHY_EXPR},
         "ins":  [{"id": "condition", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gtrue", "type": "code.expression",
         "config": {"expr": "v if t else None"},
         "ins":  [{"id": "v", "t": "any"}, {"id": "t", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gfalse", "type": "code.expression",
         "config": {"expr": "None if t else v"},
         "ins":  [{"id": "v", "t": "any"}, {"id": "t", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gtaken", "type": "code.expression",
         "config": {"expr": '"true" if t else "false"'},
         "ins":  [{"id": "t", "t": "any"}],
         "outs": [{"id": "value", "t": "string"}]},
    ],
    "wires": [
        {"from": ["vin", "value"],  "to": ["gtrue", "v"]},
        {"from": ["vin", "value"],  "to": ["gfalse", "v"]},
        {"from": ["pred", "value"], "to": ["gtrue", "t"]},
        {"from": ["pred", "value"], "to": ["gfalse", "t"]},
        {"from": ["pred", "value"], "to": ["gtaken", "t"]},
    ],
}

# Explicit facade maps — hand-mirrored to the bespoke port signature so the
# derived outer contract is EXACTLY condition/value -> true/false/taken (G4).
_IF_INNER_INPUTS = [
    {"port": "condition", "inner_node": "pred", "inner_port": "condition",
     "type": "any"},
    {"port": "value", "inner_node": "vin", "inner_port": "value",
     "type": "any"},
]
_IF_INNER_OUTPUTS = [
    {"port": "true",  "inner_node": "gtrue",  "inner_port": "value",
     "type": "any"},
    {"port": "false", "inner_node": "gfalse", "inner_port": "value",
     "type": "any"},
    {"port": "taken", "inner_node": "gtaken", "inner_port": "value",
     "type": "string"},
]

# The spec dict (the SAME shape the library / custom-node loader consumes) —
# an `impl.kind=graph` cell. The declared NodeSpec ports below are IDENTICAL to
# the retired bespoke's (condition/value -> true/false/taken), so this is a
# genuine in-place rebuild, not a new type.
_IF_SPEC = {
    "type": "control.if",
    "category": "control",
    "display_name": "If",
    "description": "Pass `value` through `true` or `false` based on "
                   "`condition`.",
    "inputs": [
        {"name": "condition", "type": "any"},
        {"name": "value", "type": "any"},
    ],
    "outputs": [
        {"name": "true", "type": "any"},
        {"name": "false", "type": "any"},
        {"name": "taken", "type": "string"},
    ],
    "config_schema": {},
    "icon": "?",
    "impl": {
        "kind": "graph",
        "graph": _IF_INNER_GRAPH,
        "inner_inputs": _IF_INNER_INPUTS,
        "inner_outputs": _IF_INNER_OUTPUTS,
    },
}


def _register_if_node() -> None:
    """Register control.if as the stem-cell graph composition.

    Built through the EXACT machinery the library / in-place swap path uses
    (``custom_nodes._build_executor`` dispatching on ``impl.kind=graph`` ->
    ``_graph_executor`` -> the nested-WorkflowRunner subgraph engine). ONE
    system: no bespoke executor, no parallel composition mechanism. The
    ``custom_nodes`` import is deferred (it imports ``nodes.code``; importing
    it at this module's top would re-enter the ``nodes`` package mid-load),
    mirroring the deferred ``_subgraph_executor`` import in ``_run_one`` below.

    `condition` keeps ``required=True`` (the retired bespoke marked it so;
    ``_spec_from_dict`` defaults ``required`` to False, so we re-stamp it) — the
    declared contract stays byte-identical to the bespoke, including the
    required flag the graph validator reads.
    """
    from ..custom_nodes import _build_executor, _spec_from_dict

    node_spec = _spec_from_dict(_IF_SPEC)
    for p in node_spec.inputs:
        if p.name == "condition":
            p.required = True
    register(node_spec, _build_executor(_IF_SPEC, node_spec))


_register_if_node()


# ---------------------------------------------------------------------------
# control.merge — the SECOND in-place stem-cell rebuild (same G3 recipe that
# proved control.if). The bespoke coalescer was:
#     a = inputs.get("a"); b = inputs.get("b")
#     chosen = a if a is not None else b
#     return {"value": chosen,
#             "source": "a" if a is not None else ("b" if b is not None else None)}
# i.e. a PURE FUNCTION of its two declared input ports — it read ONLY
# inputs['a'] + inputs['b'], its config_schema was EMPTY (no config.get(...)
# fallback for an unwired value to lose), it did NO `x or []` / `x or y`
# falsy-normalization (it tests `a is not None`, an EXPLICIT None check, so a
# falsy-but-present `a` — 0, "", [], False — is KEPT, never coalesced), and it
# had NO isinstance-guard-to-status:error (exactly two return shapes, never an
# error status). So a stem-cell composition reproduces it EXACTLY on every
# input — there is nothing for a pure-cell graph to fail to reproduce. (This is
# precisely the cleanliness control.if had and round-1's schedule_builder
# lacked: schedule_builder had `rows or []`, a `columns or config.get(...)`
# fallback, AND an isinstance-guard-to-error — all three absent here.)
#
# The rebuild expresses BOTH outputs purely as a sub-graph of existing cells:
#
#   ain    (data.passthrough)  — the `a` entry; fans `a` to gval+gsrc
#   bin    (data.passthrough)  — the `b` entry; fans `b` to gval+gsrc
#   gval   (code.expression)   — `a if a is not None else b`         -> `value`
#   gsrc   (code.expression)   — the 3-way source label              -> `source`
#
# Each facade input enters through ITS OWN passthrough and fans out via INNER
# wires (the round-1 lesson: a facade input can only ever seed ONE inner port,
# so `a` and `b` each need a passthrough to reach BOTH gval and gsrc). The two
# expressions reference the names `a` + `b` (the inner port ids on gval/gsrc),
# both ALWAYS seeded (facade always provides a + b, defaulting to None when
# absent), so `... is not None` + the ternaries never raise on any input — a
# pure function with no error path, matching the bespoke (which also had none).
# The facade port ids mirror the bespoke signature EXACTLY (a/b -> value/source,
# value:any source:string), so the in-place swap keeps the frozen G4 contract.
_MERGE_VALUE_EXPR = "a if a is not None else b"
_MERGE_SOURCE_EXPR = '"a" if a is not None else ("b" if b is not None else None)'

_MERGE_INNER_GRAPH = {
    "nodes": [
        {"id": "ain", "type": "data.passthrough", "config": {},
         "ins":  [{"id": "value", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "bin", "type": "data.passthrough", "config": {},
         "ins":  [{"id": "value", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gval", "type": "code.expression",
         "config": {"expr": _MERGE_VALUE_EXPR},
         "ins":  [{"id": "a", "t": "any"}, {"id": "b", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gsrc", "type": "code.expression",
         "config": {"expr": _MERGE_SOURCE_EXPR},
         "ins":  [{"id": "a", "t": "any"}, {"id": "b", "t": "any"}],
         "outs": [{"id": "value", "t": "string"}]},
    ],
    "wires": [
        {"from": ["ain", "value"], "to": ["gval", "a"]},
        {"from": ["bin", "value"], "to": ["gval", "b"]},
        {"from": ["ain", "value"], "to": ["gsrc", "a"]},
        {"from": ["bin", "value"], "to": ["gsrc", "b"]},
    ],
}

# Explicit facade maps — hand-mirrored to the bespoke port signature so the
# derived outer contract is EXACTLY a/b -> value/source (G4).
_MERGE_INNER_INPUTS = [
    {"port": "a", "inner_node": "ain", "inner_port": "value", "type": "any"},
    {"port": "b", "inner_node": "bin", "inner_port": "value", "type": "any"},
]
_MERGE_INNER_OUTPUTS = [
    {"port": "value",  "inner_node": "gval", "inner_port": "value",
     "type": "any"},
    {"port": "source", "inner_node": "gsrc", "inner_port": "value",
     "type": "string"},
]

# The spec dict (the SAME shape the library / in-place swap path consumes) — an
# `impl.kind=graph` cell. The declared NodeSpec ports below are IDENTICAL to the
# retired bespoke's (a/b -> value/source), so this is a genuine in-place
# rebuild, not a new type.
_MERGE_SPEC = {
    "type": "control.merge",
    "category": "control",
    "display_name": "Merge",
    "description": "Coalesce two inputs; emit the first non-null on `value`.",
    "inputs": [
        {"name": "a", "type": "any"},
        {"name": "b", "type": "any"},
    ],
    "outputs": [
        {"name": "value", "type": "any"},
        {"name": "source", "type": "string"},
    ],
    "config_schema": {},
    "icon": "∪",
    "impl": {
        "kind": "graph",
        "graph": _MERGE_INNER_GRAPH,
        "inner_inputs": _MERGE_INNER_INPUTS,
        "inner_outputs": _MERGE_INNER_OUTPUTS,
    },
}


def _register_merge_node() -> None:
    """Register control.merge as the stem-cell graph composition.

    Built through the EXACT machinery control.if uses
    (``custom_nodes._build_executor`` dispatching on ``impl.kind=graph`` ->
    ``_graph_executor`` -> the nested-WorkflowRunner subgraph engine). ONE
    system: no bespoke executor, no parallel composition mechanism. The
    ``custom_nodes`` import is deferred (it imports ``nodes.code``; importing
    it at this module's top would re-enter the ``nodes`` package mid-load),
    mirroring control.if's ``_register_if_node``.

    The bespoke marked NEITHER input required (both ``a`` and ``b`` were plain
    ``inputs.get``), and ``_spec_from_dict`` defaults ``required`` to False, so
    no re-stamp is needed — the declared contract stays byte-identical.
    """
    from ..custom_nodes import _build_executor, _spec_from_dict

    node_spec = _spec_from_dict(_MERGE_SPEC)
    register(node_spec, _build_executor(_MERGE_SPEC, node_spec))


_register_merge_node()


# ---------------------------------------------------------------------------
# control.foreach — inspect a list AND (additively) map a body sub-graph
# over it. The inspect half (items/count/first/last) is the phase-1 contract
# kept verbatim for back-compat; the map half (a `body` sub-graph cooked
# once per item, results collected into `results`) is the real fan-out the
# library seed (`app/library_seeds.py`) has always advertised for this type.
#
# ONE-SYSTEM: the per-item cook reuses the EXISTING nested-WorkflowRunner
# machinery — `_subgraph_executor` (app/workflows/subgraph.py) builds a fresh
# inner runner per call and seeds each facade input via `subgraph._seed`, and
# `_derive_graph_io` (app/workflows/custom_nodes.py) turns the body graph's
# OPEN ports into the entry/exit maps. No new runner, no new seeding scheme,
# no new registry. The map executor is a thin loop AROUND `_subgraph_executor`.

# Binding convention (matches the library seed: item "bound as `item`"):
# the current item seeds the body's entry port named `item` when one exists,
# else the body's first/sole open input port (so an unnamed body still works).
_ITEM_BIND_NAME = "item"


def _body_is_graph(body) -> bool:
    """True when `body` looks like an inline sub-graph payload — a dict
    carrying a `nodes` list (the shape `compose_subgraph` emits and that
    `subgraph.user` nodes store in `config.inner_graph`)."""
    return isinstance(body, dict) and isinstance(body.get("nodes"), list)


def _pick_entry_port(entry_map: list) -> str | None:
    """Choose which derived entry port the current item binds to.

    Prefer a port named `item` (the seed convention); else the first/sole
    open input port; else None when the body takes no input."""
    if not entry_map:
        return None
    for fp in entry_map:
        if fp.get("inner_port") == _ITEM_BIND_NAME or fp.get("port") == _ITEM_BIND_NAME:
            return fp["port"]
    return entry_map[0]["port"]


def _pick_result_port(exit_map: list) -> str | None:
    """Choose which derived exit port carries the per-item result.

    Prefer a port named `result`/`results`/`value`/`output`; else the
    sole open output port; else None when there are 0 or >1 unnamed
    outputs (then the whole returned dict becomes the result)."""
    if not exit_map:
        return None
    by_name = {fp.get("inner_port"): fp["port"] for fp in exit_map}
    for preferred in ("result", "results", "value", "output"):
        if preferred in by_name:
            return by_name[preferred]
    if len(exit_map) == 1:
        return exit_map[0]["port"]
    return None


def _extract_result(cooked: dict, result_port: str | None):
    """Pull the per-item result value out of a `_subgraph_executor` return.

    `_subgraph_executor` returns `{status, <exit_port>: value, ...}`. When a
    single primary exit port was identified, return that value; otherwise
    return the whole dict minus the bookkeeping `status` key so multi-output
    bodies still surface every value honestly."""
    if result_port is not None:
        return cooked.get(result_port)
    return {k: v for k, v in cooked.items() if k != "status"}


def _run_one(body_graph: dict, entry_port: str | None, result_port: str | None,
             item, ctx) -> tuple[bool, object, object]:
    """Cook the body sub-graph for ONE item via the existing subgraph
    machinery. Returns `(ok, result_value, error)`.

    Each call constructs sub_config from the derived entry/exit maps and a
    FRESH seed value (the current item on the chosen entry port). Because
    `_subgraph_executor` builds its own `WorkflowRunner` + `__seed__*` nodes
    per call, every iteration is isolated — no cross-item cache bleed, no id
    collision. We rely on per-call construction, never on mutating one runner.
    """
    # Deferred import — subgraph imports the runner which imports registry;
    # registry (this module's import root) has no compile-time dep on either.
    from ..subgraph import _subgraph_executor

    entry_map, exit_map = _derive_io(body_graph)
    # Re-pick against the derived maps (the caller's picks were computed from
    # the same maps, so this is consistent; recomputing keeps _run_one usable
    # standalone). entry_port/result_port passed in win when provided.
    e_port = entry_port if entry_port is not None else _pick_entry_port(entry_map)
    r_port = result_port if result_port is not None else _pick_result_port(exit_map)

    sub_config = {
        "inner_graph":   body_graph,
        "inner_inputs":  entry_map,
        "inner_outputs": exit_map,
    }
    seed_inputs = {e_port: item} if e_port is not None else {}
    cooked = _subgraph_executor(sub_config, seed_inputs, ctx)
    if isinstance(cooked, dict) and cooked.get("status") == "error":
        return False, None, cooked.get("error")
    if not isinstance(cooked, dict):
        # _subgraph_executor always returns a dict, but stay defensive.
        return True, cooked, None
    return True, _extract_result(cooked, r_port), None


def _derive_io(body_graph: dict) -> tuple[list, list]:
    """Derive the body's (entry_map, exit_map) from its OPEN ports, reusing
    `_derive_graph_io` from the custom-nodes module (one source of truth for
    open-port → facade derivation). Returns ([], []) if the helper is
    unavailable rather than raising — the caller then treats the body as
    taking no input / producing the whole dict."""
    try:
        from ..custom_nodes import _derive_graph_io
    except Exception:
        return [], []
    try:
        return _derive_graph_io(body_graph)
    except Exception:
        return [], []


def _foreach_executor(config: dict, inputs: dict, ctx) -> dict:
    """For-each / map.

    INSPECT (phase-1, always present, back-compat): emit the normalised
    `items` list plus `count` / `first` / `last`.

    MAP (real fan-out): when a `body` sub-graph is wired, cook it ONCE per
    item — binding the current item to the body's entry port — and collect
    each item's primary output into `results`, in input order.

    Config (matches the library seed):
      parallel       bool — run iterations concurrently (default False).
                     Results are re-sorted to input order regardless, so
                     `results` stays deterministic.
      halt_on_error  bool — default True: stop at the first failing item and
                     return a typed error with the partial results + the
                     failed index. False: append the per-item error marker
                     and continue, surfacing an `errors` list.

    Honesty: a failed item is NEVER a fabricated value — it is a typed error
    (halt) or an `{"error": ...}` marker (continue). With no `body`, the node
    is pure inspect and emits `results: []`."""
    config = config or {}
    items = inputs.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        items = [items]

    # The inspect outputs are ALWAYS computed — back-compat is unconditional.
    out: dict = {
        "items": items,
        "count": len(items),
        "first": items[0] if items else None,
        "last":  items[-1] if items else None,
        "results": [],
        "status": "ok",
    }

    body = inputs.get("body")
    if not _body_is_graph(body):
        # No body wired (or not a graph payload) → pure inspect. `results`
        # stays []; this is the legacy path, fully preserved.
        return out

    if not items:
        return out

    # Derive the body I/O once — the body graph is the same across items.
    entry_map, exit_map = _derive_io(body)
    entry_port = _pick_entry_port(entry_map)
    result_port = _pick_result_port(exit_map)

    halt_on_error = bool(config.get("halt_on_error", True))
    parallel = bool(config.get("parallel", False))

    results: list = [None] * len(items)
    errors: list = []

    if not parallel:
        # ── Sequential (the shipped default) ────────────────────────────
        for i, item in enumerate(items):
            ok, value, error = _run_one(body, entry_port, result_port, item, ctx)
            if ok:
                results[i] = value
                continue
            if halt_on_error:
                out["status"] = "error"
                out["error"] = error
                out["failed_index"] = i
                out["results"] = results[:i]   # partial, honest
                return out
            results[i] = {"error": error}
            errors.append({"index": i, "error": error})
    else:
        # ── Parallel (opt-in) ───────────────────────────────────────────
        # Bounded stdlib thread pool — NO new third-party dep. Each task runs
        # an isolated inner cook (fresh runner per call). We collect by index
        # and re-sort to input order so `results` is deterministic despite
        # out-of-order completion (safer than the seed's "no order" note).
        import concurrent.futures as _cf

        max_workers = min(len(items), 8)
        first_error: dict | None = None
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_to_idx = {
                pool.submit(_run_one, body, entry_port, result_port, item, ctx): i
                for i, item in enumerate(items)
            }
            for fut in _cf.as_completed(fut_to_idx):
                i = fut_to_idx[fut]
                try:
                    ok, value, error = fut.result()
                except Exception as ex:   # defensive — _run_one catches its own
                    ok, value, error = False, None, f"{type(ex).__name__}: {ex}"
                if ok:
                    results[i] = value
                else:
                    results[i] = {"error": error}
                    errors.append({"index": i, "error": error})
                    if first_error is None or i < first_error["index"]:
                        first_error = {"index": i, "error": error}
        if halt_on_error and first_error is not None:
            # Halt semantics under parallel: report the lowest-index failure
            # and the results that DID complete before it (in input order).
            out["status"] = "error"
            out["error"] = first_error["error"]
            out["failed_index"] = first_error["index"]
            out["results"] = results[:first_error["index"]]
            return out

    out["results"] = results
    if errors:
        out["errors"] = sorted(errors, key=lambda e: e["index"])
    return out


register(
    NodeSpec(
        type="control.foreach",
        category="control",
        display_name="For each",
        description=(
            "Map a `body` sub-graph over `items` — cooks the body once per "
            "item (item bound as `item`), collecting per-item output into "
            "`results`. Also emits inspect outputs (count, first, last)."
        ),
        inputs=[Port(name="items", type=PortType.LIST, required=True),
                # ADDED — the body sub-graph cooked per item. NOT required:
                # absent in legacy graphs, which then run pure-inspect.
                Port(name="body", type=PortType.ANY)],
        outputs=[Port(name="results", type=PortType.LIST),   # ADDED — the map output
                 Port(name="items", type=PortType.LIST),     # KEPT (inspect)
                 Port(name="count", type=PortType.NUMBER),    # KEPT (inspect)
                 Port(name="first", type=PortType.ANY),       # KEPT (inspect)
                 Port(name="last",  type=PortType.ANY)],      # KEPT (inspect)
        config_schema={
            "properties": {
                "parallel": {"type": "boolean", "default": False},
                "halt_on_error": {"type": "boolean", "default": True},
            },
        },
        icon="∀",
    ),
    _foreach_executor,
)


# ---------------------------------------------------------------------------
# control.switch — the THIRD in-place stem-cell rebuild (wave-4), the FIRST to
# exercise the NORMALIZATION INFRA. Where control.if / control.merge were clean
# pure functions of their inputs (empty config_schema → nothing to lose), the
# bespoke ``_switch_executor`` carried the one pattern the bare subgraph engine
# does NOT give for free — a CONFIG-FALLBACK:
#     value = inputs.get("value")
#     case  = inputs.get("case")
#     if case is None:                       # ← the config-fallback
#         case = config.get("case")
#     matched = value == case or str(value) == str(case)
#     if matched:  return {"match": value, "default": None, "taken": "match"}
#     return        {"match": None,  "default": value, "taken": "default"}
#
# This is precisely refutation #2 that sank round-1's schedule_builder (a
# ``columns or config.get('columns')`` fallback the subgraph lost because the
# inner runner threads only INPUTS, never the facade node's config). The wave-4
# infra closes it: a ``data.coalesce`` (mode ``none`` → ``x if x is not None
# else fallback``) cell whose ``value`` is seeded from the facade ``case`` INPUT
# and whose ``fallback`` is seeded from the facade node's ``config.get('case')``
# via a CONFIG-SOURCED inner-input (``source:"config"`` + ``config_key:"case"``,
# subgraph.py). That reproduces ``case = inputs.get('case') if
# inputs.get('case') is not None else config.get('case')`` BYTE-IDENTICALLY —
# the config value reaches the inner graph through the config-seed, no longer
# lost. (No ``data.ensure`` here: the bespoke has NO isinstance-guard-to-error —
# its only return shapes are the two routes, never ``status:error`` — so adding
# a type-guard would FABRICATE an error path the bespoke never had. switch is a
# config-fallback rebuild, not a type-guard one.)
#
# The rest is the same recipe control.if/merge proved — pure cells:
#
#   vin    (data.passthrough) — the `value` entry; fans `value` to pred+gmatch+gdefault
#   ccoa   (data.coalesce, mode=none) — the `case` config-fallback: value=case input,
#                                      fallback=config['case'] (config-seed) → resolved case
#   pred   (code.expression)  — the SAME match predicate `value == case or
#                               str(value) == str(case)`            -> `m`
#   gmatch   (code.expression) — `v if m else None`     -> the `match`   output
#   gdefault (code.expression) — `None if m else v`     -> the `default` output
#   gtaken   (code.expression) — `"match" if m else "default"` -> the `taken` label
#
# `value` enters through ONE passthrough and fans out via INNER wires (the
# round-1 lesson: a facade input seeds exactly ONE inner port, so it needs a
# passthrough to reach pred + both gates). `case` enters the coalesce cell
# directly (its `value` port IS the entry; its single output fans only to pred).
# Every expression's names (`value`, `case`, `v`, `m`) are ALWAYS seeded —
# `value`+`case` always flow (facade seeds them, defaulting to None), `m` is
# pred's always-cooked output — so `==`, `str(...)`, and the ternaries never
# raise on any input: a pure function with no error path, matching the bespoke.
# The facade port ids mirror the bespoke signature EXACTLY (value/case ->
# match/default/taken; match:any default:any taken:string), so the in-place swap
# keeps the frozen G4 port contract.
_SWITCH_MATCH_EXPR = "value == case or str(value) == str(case)"

_SWITCH_INNER_GRAPH = {
    "nodes": [
        {"id": "vin", "type": "data.passthrough", "config": {},
         "ins":  [{"id": "value", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        # The config-fallback cell — mode `none` reproduces `case if case is
        # not None else config['case']`. `value` is seeded from the `case`
        # INPUT, `fallback` from the facade `config['case']` (config-seed).
        {"id": "ccoa", "type": "data.coalesce", "config": {"mode": "none"},
         "ins":  [{"id": "value", "t": "any"}, {"id": "fallback", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "pred", "type": "code.expression",
         "config": {"expr": _SWITCH_MATCH_EXPR},
         "ins":  [{"id": "value", "t": "any"}, {"id": "case", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gmatch", "type": "code.expression",
         "config": {"expr": "v if m else None"},
         "ins":  [{"id": "v", "t": "any"}, {"id": "m", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gdefault", "type": "code.expression",
         "config": {"expr": "None if m else v"},
         "ins":  [{"id": "v", "t": "any"}, {"id": "m", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gtaken", "type": "code.expression",
         "config": {"expr": '"match" if m else "default"'},
         "ins":  [{"id": "m", "t": "any"}],
         "outs": [{"id": "value", "t": "string"}]},
    ],
    "wires": [
        # value fans to the predicate + both value-gates.
        {"from": ["vin", "value"],  "to": ["pred", "value"]},
        {"from": ["vin", "value"],  "to": ["gmatch", "v"]},
        {"from": ["vin", "value"],  "to": ["gdefault", "v"]},
        # the resolved (config-fallen-back) case feeds the predicate.
        {"from": ["ccoa", "value"], "to": ["pred", "case"]},
        # the match flag fans to all three gates.
        {"from": ["pred", "value"], "to": ["gmatch", "m"]},
        {"from": ["pred", "value"], "to": ["gdefault", "m"]},
        {"from": ["pred", "value"], "to": ["gtaken", "m"]},
    ],
}

# Explicit facade maps — hand-mirrored to the bespoke port signature so the
# derived outer contract is EXACTLY value/case -> match/default/taken (G4).
# `value` seeds the passthrough; `case` seeds the coalesce's `value` port (the
# INPUT half of the fallback); the coalesce's `fallback` port is seeded from the
# facade node's own ``config['case']`` via a CONFIG-SOURCED entry — this is the
# wave-4 infra reproducing ``inputs.get('case') or-None-fallback config['case']``.
_SWITCH_INNER_INPUTS = [
    {"port": "value", "inner_node": "vin", "inner_port": "value",
     "type": "any"},
    {"port": "case", "inner_node": "ccoa", "inner_port": "value",
     "type": "any"},
    # CONFIG-SEED: the coalesce fallback is the facade node's config['case'],
    # threaded into the inner graph by subgraph.py's source:"config" path. This
    # is the config-fallback the bare subgraph engine lost; the infra closes it
    # byte-identically. `port` is a SYNTHETIC seed-node id (``case_cfg``), NOT a
    # facade input — the outer caller never wires it; it only names the internal
    # ``__seed__case_cfg`` node (subgraph.py builds ``seed_id`` from ``port``),
    # exactly as Part A's test_subgraph_config_seed pins (a config-sourced entry
    # carries a `port` but is filtered out of the facade `ins`). The declared
    # NodeSpec inputs stay value/case — this entry is invisible to the contract.
    {"port": "case_cfg", "inner_node": "ccoa", "inner_port": "fallback",
     "source": "config", "config_key": "case", "type": "any"},
]
_SWITCH_INNER_OUTPUTS = [
    {"port": "match",   "inner_node": "gmatch",   "inner_port": "value",
     "type": "any"},
    {"port": "default", "inner_node": "gdefault", "inner_port": "value",
     "type": "any"},
    {"port": "taken",   "inner_node": "gtaken",   "inner_port": "value",
     "type": "string"},
]

# The spec dict (the SAME shape the library / in-place swap path consumes) — an
# `impl.kind=graph` cell. The declared NodeSpec ports below are IDENTICAL to the
# retired bespoke's (value/case -> match/default/taken), so this is a genuine
# in-place rebuild, not a new type. config_schema keeps the `case` key (the
# config-fallback source the config-seed reads).
_SWITCH_SPEC = {
    "type": "control.switch",
    "category": "control",
    "display_name": "Switch",
    "description": "Route `value` to `match` when it equals `case`, "
                   "else to `default`.",
    "inputs": [
        {"name": "value", "type": "any"},
        {"name": "case", "type": "any"},
    ],
    "outputs": [
        {"name": "match", "type": "any"},
        {"name": "default", "type": "any"},
        {"name": "taken", "type": "string"},
    ],
    "config_schema": {"case": {}},
    "icon": "⎇",
    "impl": {
        "kind": "graph",
        "graph": _SWITCH_INNER_GRAPH,
        "inner_inputs": _SWITCH_INNER_INPUTS,
        "inner_outputs": _SWITCH_INNER_OUTPUTS,
    },
}


def _register_switch_node() -> None:
    """Register control.switch as the stem-cell graph composition.

    Built through the EXACT machinery control.if / control.merge use
    (``custom_nodes._build_executor`` dispatching on ``impl.kind=graph`` ->
    ``_graph_executor`` -> the nested-WorkflowRunner subgraph engine, with the
    wave-4 config-sourced seed threading ``config['case']`` into the inner
    coalesce). ONE system: no bespoke executor, no parallel composition
    mechanism, no new fallback machinery. The ``custom_nodes`` import is deferred
    (it imports ``nodes.code``; importing it at this module's top would re-enter
    the ``nodes`` package mid-load), mirroring the sibling registrations.

    `value` keeps ``required=True`` (the retired bespoke marked it so;
    ``_spec_from_dict`` defaults ``required`` to False, so we re-stamp it) — the
    declared contract stays byte-identical to the bespoke, including the required
    flag the graph validator reads. `case` stays optional (the bespoke marked it
    a plain ``inputs.get``).
    """
    from ..custom_nodes import _build_executor, _spec_from_dict

    node_spec = _spec_from_dict(_SWITCH_SPEC)
    for p in node_spec.inputs:
        if p.name == "value":
            p.required = True
    register(node_spec, _build_executor(_SWITCH_SPEC, node_spec))


_register_switch_node()
