"""Control flow nodes — branching, iteration, merging.

Phase 1 is intentionally minimal. The data model supports more, but this
is enough for capturing chat conversations and running them as workflows.

  control.if      — branch on a boolean condition (true / false output ports)
  control.foreach — iterate a list, fan out to a sub-graph (single-step v0)
  control.merge   — coalesce two inputs, prefer first non-null
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
def _if_executor(config: dict, inputs: dict, ctx) -> dict:
    cond = inputs.get("condition")
    truthy = bool(cond) and cond not in ("false", "False", "0", 0, "")
    value = inputs.get("value")
    if truthy:
        return {"true": value, "false": None, "taken": "true"}
    return {"true": None, "false": value, "taken": "false"}


register(
    NodeSpec(
        type="control.if",
        category="control",
        display_name="If",
        description="Pass `value` through `true` or `false` based on `condition`.",
        inputs=[
            Port(name="condition", type=PortType.ANY, required=True),
            Port(name="value",     type=PortType.ANY),
        ],
        outputs=[
            Port(name="true",  type=PortType.ANY),
            Port(name="false", type=PortType.ANY),
            Port(name="taken", type=PortType.STRING),
        ],
        config_schema={},
        icon="?",
    ),
    _if_executor,
)


# ---------------------------------------------------------------------------
def _merge_executor(config: dict, inputs: dict, ctx) -> dict:
    a = inputs.get("a")
    b = inputs.get("b")
    chosen = a if a is not None else b
    return {"value": chosen, "source": "a" if a is not None else ("b" if b is not None else None)}


register(
    NodeSpec(
        type="control.merge",
        category="control",
        display_name="Merge",
        description="Coalesce two inputs; emit the first non-null on `value`.",
        inputs=[Port(name="a", type=PortType.ANY), Port(name="b", type=PortType.ANY)],
        outputs=[Port(name="value", type=PortType.ANY),
                 Port(name="source", type=PortType.STRING)],
        config_schema={},
        icon="∪",
    ),
    _merge_executor,
)


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
def _switch_executor(config: dict, inputs: dict, ctx) -> dict:
    """Route `value` to `match` when it equals `case` (wired input, else
    config), otherwise to `default`. A value-equality router — distinct
    from control.if, which branches on a boolean condition."""
    value = inputs.get("value")
    case = inputs.get("case")
    if case is None:
        case = (config or {}).get("case")
    matched = value == case or str(value) == str(case)
    if matched:
        return {"match": value, "default": None, "taken": "match"}
    return {"match": None, "default": value, "taken": "default"}


register(
    NodeSpec(
        type="control.switch",
        category="control",
        display_name="Switch",
        description="Route `value` to `match` when it equals `case`, "
                    "else to `default`.",
        inputs=[Port(name="value", type=PortType.ANY, required=True),
                Port(name="case",  type=PortType.ANY)],
        outputs=[Port(name="match",   type=PortType.ANY),
                 Port(name="default", type=PortType.ANY),
                 Port(name="taken",   type=PortType.STRING)],
        config_schema={"case": {}},
        icon="⎇",
    ),
    _switch_executor,
)
