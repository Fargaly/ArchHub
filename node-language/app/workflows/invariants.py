"""Engine invariants — the court's layer-0 checkers (SPEC §19 forcings).

Pure checker library over the ONE engine (WorkflowRunner). Zero runner
behaviour change by default: the runner only imports this module when
the opt-in env flag ``ARCHHUB_COURT_INVARIANTS=1`` is set (see
``WorkflowRunner.pull``). Everything here is deterministic, stdlib-only,
LLM-free, and side-effect-free.

Research anchors (steal the SHAPE, cite the source — node-language
formal foundation):

  • impossible-state checking (Ascon-style): after a cook, certain
    runner states are IMPOSSIBLE for an honest engine — a data.reduce
    whose stored value disagrees with an independent fold of the input
    list it actually consumed, a control.foreach whose fan-out doesn't
    match its input collection, a frozen node whose cached state moved.
    We recompute the expectation from the REAL cooked upstream values
    (runner.node_outputs / wire_bus) with independently-written folds —
    never by re-running the same executor code path twice.

  • metamorphic testing (MR-1, oracle-free): full-cook-from-scratch and
    incremental-recook-after-edit must agree on every sink. The engine
    is its own oracle.

  • KPN determinism: the graph is a Kahn process network — the same
    graph cooked on fresh runners must produce identical sink values.

  • operad regroup-invariance (Spivak wiring diagrams): grouping nodes
    into a subgraph.user composite is a semantics-preserving operad
    composition — two different groupings of the same nodes must yield
    identical downstream sink values.

Public API:
    check_impossible_states(workflow, runner, frozen_snapshot=None)
        -> list[violation dict]
    snapshot_frozen(runner) -> dict          (pre-cook frozen snapshot)
    metamorphic_full_vs_incremental(workflow, edit_fn) -> bool
    determinism_check(workflow, n=3) -> list[violation dict]
    regroup_invariance(workflow, grouping_a, grouping_b)
        -> list[violation dict]
    convene(workflow, ...) -> {"green": bool, "violations": [...]}
        Runs all layers cheapest-first, fail-closed: ANY violation (or
        any layer exception) -> green=False.

Violation dicts always carry: {"layer", "kind", "node"?, "detail"}.
"""
from __future__ import annotations

import copy
import json
import math
import os
from typing import Any, Callable, Optional

from .runner import WorkflowRunner, _resolve_field, _wrap_field

# ONE-SYSTEM: reuse the engine's numeric coercion so the checker's
# independent folds never drift from data.reduce's coercion semantics.
# The FOLD logic below is written independently (builtins / math.prod /
# all / any) — only the scalar coercion is shared, deliberately.
try:
    from .nodes.aggregate import _num as _coerce_num
except Exception:                                     # pragma: no cover
    def _coerce_num(x):
        """Local mirror of nodes/aggregate._num (fallback only)."""
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int, float)):
            return x
        try:
            return float(x)
        except Exception:
            return 0


ENV_FLAG = "ARCHHUB_COURT_INVARIANTS"

_MISSING = object()


class InvariantViolation(RuntimeError):
    """Raised by the opt-in runner hook when a cook left the engine in
    an impossible state. Carries the structured violation list."""

    def __init__(self, violations: list):
        self.violations = list(violations or [])
        parts = []
        for v in self.violations:
            parts.append(f"{v.get('kind', '?')} @ {v.get('node', '?')}: "
                         f"{v.get('detail', '')}")
        super().__init__("engine invariant violated — "
                         + "; ".join(parts))


def court_invariants_enabled() -> bool:
    """True when the opt-in post-cook hook should run (env flag)."""
    return os.environ.get(ENV_FLAG, "") == "1"


# ── shared plumbing ──────────────────────────────────────────────────

def _stable(v: Any) -> str:
    """A stable, comparison-safe repr for cooked values."""
    try:
        return json.dumps(v, sort_keys=True, default=repr)
    except Exception:
        return repr(v)


def _values_equal(expected: Any, actual: Any) -> bool:
    """Tolerant equality — floats compare with isclose, bools exactly."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        try:
            return math.isclose(float(expected), float(actual),
                                rel_tol=1e-9, abs_tol=1e-12)
        except Exception:
            return expected == actual
    return _stable(expected) == _stable(actual)


def _sink_ids(runner: WorkflowRunner) -> list[str]:
    """Nodes with no downstream edges — same rule as run_all."""
    downstream_targets = {e["src_node"] for e in runner.edges}
    return [nid for nid in runner.nodes_by_id
            if nid not in downstream_targets]


def _consumed_input(runner: WorkflowRunner, node_id: str,
                    port: str) -> Any:
    """Reconstruct the value the runner ACTUALLY fed into `node_id` at
    `port`, from the parents' real cooked outputs (node_outputs) with
    the same src_field/dst_field selectors the runner applied. Falls
    back to the wire_bus (the value that physically flowed). Returns
    the _MISSING sentinel when nothing checkable exists.

    This is deliberately NOT a re-cook — it only reads state the last
    cook left behind, so comparing against it is a genuine cross-check
    of the executor, not the same code path run twice."""
    value: Any = _MISSING
    for e in runner._upstream_edges(node_id):
        if e.get("dst_port") != port:
            continue
        parent_out = runner.node_outputs.get(e["src_node"], _MISSING)
        if parent_out is _MISSING:
            if e["id"] in runner.wire_bus:
                value = runner.wire_bus[e["id"]]
            continue
        if isinstance(parent_out, dict):
            v = parent_out.get(e["src_port"])
        else:
            v = parent_out
        sf = e.get("src_field") or ""
        if sf:
            v = _resolve_field(v, sf)
        df = e.get("dst_field") or ""
        if df:
            v = _wrap_field(v, df)
        value = v      # last edge wins, mirroring runner input assembly
    return value


def _independent_reduce(op: str, items_value: Any, init: Any) -> Any:
    """Recompute what data.reduce MUST have produced, with folds built
    from different primitives than the executor's sequential lambda
    table (builtins sum/min/max, math.prod, all/any). Semantics mirror
    nodes/aggregate exactly (identity per op, init pass-through, _num
    coercion). Returns _MISSING for an unknown op (the executor errors
    on those, and errored cooks are skipped upstream of this call)."""
    if items_value is None:
        items: list = []
    elif isinstance(items_value, (list, tuple)):
        items = list(items_value)
    else:
        items = [items_value]

    if op == "sum":
        base = init if init is not None else 0
        return base + sum(_coerce_num(x) for x in items)
    if op == "product":
        base = init if init is not None else 1
        return base * math.prod(_coerce_num(x) for x in items)
    if op == "min":
        coerced = [_coerce_num(x) for x in items]
        if init is not None:
            return min([init] + coerced) if coerced else init
        return min(coerced) if coerced else None
    if op == "max":
        coerced = [_coerce_num(x) for x in items]
        if init is not None:
            return max([init] + coerced) if coerced else init
        return max(coerced) if coerced else None
    if op == "count":
        base = init if init is not None else 0
        return base + len(items)
    if op == "concat":
        if not items:
            return init if init is not None else ""
        head = str(init) if init is not None else ""
        return head + "".join(str(x) for x in items)
    if op == "and":
        acc = init if init is not None else True
        if not acc or not items:
            return acc
        return all(bool(x) for x in items)
    if op == "or":
        acc = init if init is not None else False
        if acc or not items:
            return acc
        return any(bool(x) for x in items)
    return _MISSING


# ── layer 0a: impossible states ──────────────────────────────────────

def snapshot_frozen(runner: WorkflowRunner) -> dict:
    """Snapshot every frozen node's (cache_key, outputs-repr) BEFORE a
    cook. `check_impossible_states(frozen_snapshot=...)` compares the
    post-cook state against this — the frozen bypass path never writes
    node_outputs / node_cache_keys, so ANY drift means an executor (or
    a rogue code path) mutated a pinned node mid-cook."""
    snap: dict = {}
    for nid, node in runner.nodes_by_id.items():
        if node.get("frozen") is True:
            snap[nid] = (runner.node_cache_keys.get(nid),
                         _stable(runner.node_outputs.get(nid)))
    return snap


def check_impossible_states(workflow: Optional[dict],
                            runner: WorkflowRunner,
                            frozen_snapshot: Optional[dict] = None
                            ) -> list:
    """Scan a cooked runner for states an honest engine cannot reach.

    (a) data.reduce: its stored `value` must equal an independent fold
        of the input list it actually consumed (see _consumed_input +
        _independent_reduce — different code, same real inputs).
    (b) control.foreach: its emitted `items`/`count`/`first`/`last`
        must be internally consistent AND match the consumed input
        collection; a wired body's `results` fan-out must be one-per-
        item (status ok only — halted cooks legitimately truncate).
    (c) frozen: a node marked `frozen: True` must not have had its
        cached outputs / cache key moved by the cook (needs a pre-cook
        `frozen_snapshot` from `snapshot_frozen`).

    `workflow` is accepted for signature parity with the other layers;
    the cooked truth lives on the runner. Returns violation dicts —
    empty list == clean."""
    violations: list = []

    for nid, node in runner.nodes_by_id.items():
        ntype = node.get("type") or ""
        out = runner.node_outputs.get(nid)
        if not isinstance(out, dict):
            continue

        # ── (a) data.reduce vs independent fold ─────────────────────
        if ntype == "data.reduce":
            if out.get("status") != "ok":
                continue                     # errored cooks self-report
            items_v = _consumed_input(runner, nid, "items")
            if items_v is _MISSING:
                continue                     # nothing checkable flowed
            init_v = _consumed_input(runner, nid, "init")
            init = None if init_v is _MISSING else init_v
            op = str((node.get("config") or {}).get("op", "sum") or "sum")
            expected = _independent_reduce(op, items_v, init)
            if expected is _MISSING:
                continue
            actual = out.get("value")
            if not _values_equal(expected, actual):
                violations.append({
                    "layer": "impossible_state",
                    "kind": "reduce_mismatch",
                    "node": nid,
                    "op": op,
                    "expected": expected,
                    "actual": actual,
                    "detail": (f"data.reduce {nid!r}: independent {op} of "
                               f"consumed items gives {expected!r}, cook "
                               f"stored {actual!r}"),
                })

        # ── (b) control.foreach fan-out consistency ─────────────────
        elif ntype == "control.foreach":
            items_out = out.get("items")
            if not isinstance(items_out, list):
                violations.append({
                    "layer": "impossible_state",
                    "kind": "foreach_items_not_list",
                    "node": nid,
                    "detail": (f"control.foreach {nid!r} emitted non-list "
                               f"items: {type(items_out).__name__}"),
                })
                continue
            items_v = _consumed_input(runner, nid, "items")
            if items_v is not _MISSING:
                if items_v is None:
                    normalized: list = []
                elif isinstance(items_v, list):
                    normalized = items_v
                else:
                    normalized = [items_v]
                if _stable(items_out) != _stable(normalized):
                    violations.append({
                        "layer": "impossible_state",
                        "kind": "foreach_items_mismatch",
                        "node": nid,
                        "detail": (f"control.foreach {nid!r} emitted items "
                                   f"!= consumed collection "
                                   f"({len(items_out)} vs {len(normalized)})"),
                    })
            if out.get("count") != len(items_out):
                violations.append({
                    "layer": "impossible_state",
                    "kind": "foreach_count_mismatch",
                    "node": nid,
                    "expected": len(items_out),
                    "actual": out.get("count"),
                    "detail": (f"control.foreach {nid!r}: count="
                               f"{out.get('count')!r} but emitted "
                               f"{len(items_out)} items"),
                })
            if items_out:
                if not _values_equal(out.get("first"), items_out[0]):
                    violations.append({
                        "layer": "impossible_state",
                        "kind": "foreach_first_mismatch",
                        "node": nid,
                        "detail": (f"control.foreach {nid!r}: first="
                                   f"{out.get('first')!r} != items[0]="
                                   f"{items_out[0]!r}"),
                    })
                if not _values_equal(out.get("last"), items_out[-1]):
                    violations.append({
                        "layer": "impossible_state",
                        "kind": "foreach_last_mismatch",
                        "node": nid,
                        "detail": (f"control.foreach {nid!r}: last="
                                   f"{out.get('last')!r} != items[-1]="
                                   f"{items_out[-1]!r}"),
                    })
            results = out.get("results")
            if (out.get("status") == "ok" and isinstance(results, list)
                    and results and len(results) != len(items_out)):
                violations.append({
                    "layer": "impossible_state",
                    "kind": "foreach_fanout_mismatch",
                    "node": nid,
                    "expected": len(items_out),
                    "actual": len(results),
                    "detail": (f"control.foreach {nid!r} fanned out "
                               f"{len(results)} results for "
                               f"{len(items_out)} items"),
                })

    # ── (c) frozen nodes must not move during a cook ─────────────────
    for nid, (ck, orepr) in (frozen_snapshot or {}).items():
        node = runner.nodes_by_id.get(nid)
        if not node or node.get("frozen") is not True:
            continue        # unfrozen since snapshot — legit user edit
        now_ck = runner.node_cache_keys.get(nid)
        now_repr = _stable(runner.node_outputs.get(nid))
        if now_ck != ck or now_repr != orepr:
            violations.append({
                "layer": "impossible_state",
                "kind": "frozen_mutated",
                "node": nid,
                "detail": (f"frozen node {nid!r} was mutated by a cook: "
                           f"cache_key {ck!r}→{now_ck!r}, "
                           f"outputs {orepr[:80]}→{now_repr[:80]}"),
            })
    return violations


# ── layer 1: metamorphic MR-1 (full vs incremental) ──────────────────

def metamorphic_full_vs_incremental(workflow: dict,
                                    edit_fn: Callable[[dict], Any]
                                    ) -> bool:
    """MR-1, the native oracle-free check: cook full from scratch on a
    fresh runner over the EDITED graph; apply the same edit to an
    already-used runner and incremental-recook (the exact
    onParamChange → recook_from path); compare ALL sink values.

    `edit_fn(graph_copy)` mutates the graph copy in place (config /
    params level only — the changed nodes are diffed out automatically,
    so it needs no return value). Topology edits (added/removed nodes
    or wire changes) are out of MR-1's scope and raise ValueError —
    fail-closed, never silently green."""
    used = WorkflowRunner(copy.deepcopy(workflow))
    used.run_all()

    edited = copy.deepcopy(workflow)
    ret = edit_fn(edited)
    if isinstance(ret, dict) and "nodes" in ret:
        edited = ret            # edit_fn returned a replacement graph

    orig_nodes = {n.get("id"): n for n in (workflow.get("nodes") or [])
                  if n.get("id")}
    new_nodes = {n.get("id"): n for n in (edited.get("nodes") or [])
                 if n.get("id")}
    if set(orig_nodes) != set(new_nodes) or \
            _stable(workflow.get("wires") or workflow.get("edges") or []) \
            != _stable(edited.get("wires") or edited.get("edges") or []):
        raise ValueError(
            "metamorphic_full_vs_incremental: edit_fn changed the graph "
            "topology — MR-1 covers config/param edits only")
    changed = [nid for nid in new_nodes
               if _stable(new_nodes[nid]) != _stable(orig_nodes[nid])]

    # Full cook from scratch on the edited graph.
    fresh = WorkflowRunner(copy.deepcopy(edited))
    fresh.run_all()

    # Incremental recook on the used runner — the live-edit path.
    for nid in changed:
        used.nodes_by_id[nid] = dict(copy.deepcopy(new_nodes[nid]))
        used.recook_from(nid)

    for sink in _sink_ids(fresh):
        if _stable(fresh.node_outputs.get(sink)) \
                != _stable(used.node_outputs.get(sink)):
            return False
    return True


# ── layer 2: KPN determinism ─────────────────────────────────────────

def determinism_check(workflow: dict, n: int = 3) -> list:
    """Cook the same graph on `n` fresh runners — every sink must land
    on bit-identical values (the KPN forcing). Returns violations."""
    violations: list = []
    baseline: Optional[dict] = None
    for i in range(max(2, int(n))):
        r = WorkflowRunner(copy.deepcopy(workflow))
        r.run_all()
        sig = {nid: _stable(r.node_outputs.get(nid))
               for nid in _sink_ids(r)}
        if baseline is None:
            baseline = sig
            continue
        if sig != baseline:
            diff = [nid for nid in sig
                    if sig.get(nid) != baseline.get(nid)]
            violations.append({
                "layer": "determinism",
                "kind": "nondeterministic_cook",
                "node": diff[0] if diff else None,
                "run": i,
                "detail": (f"fresh-runner cook #{i} diverged from cook #0 "
                           f"at sink(s) {diff}"),
            })
    return violations


# ── layer 3: operad regroup-invariance ───────────────────────────────

def regroup_invariance(workflow: dict,
                       grouping_a: list,
                       grouping_b: list) -> list:
    """Group the same nodes two different ways via the EXISTING
    compose_subgraph (subgraph.user composites), cook both on fresh
    runners, and require every surviving downstream sink to match the
    ungrouped baseline (operad composition is semantics-preserving).

    Each grouping is a list of node-id lists; groups are composed in
    order. Returns violations — empty == invariant holds."""
    from .subgraph import compose_subgraph   # already-registered engine

    violations: list = []
    base = WorkflowRunner(copy.deepcopy(workflow))
    base.run_all()
    base_sinks = {nid: _stable(base.node_outputs.get(nid))
                  for nid in _sink_ids(base)}

    for label, grouping in (("a", grouping_a), ("b", grouping_b)):
        g = copy.deepcopy(workflow)
        for i, ids in enumerate(grouping or []):
            g = compose_subgraph(g, list(ids),
                                 composite_id=f"__regroup_{label}_{i}")
        r = WorkflowRunner(g)
        r.run_all()
        shared = [nid for nid in _sink_ids(r) if nid in base_sinks]
        if not shared:
            violations.append({
                "layer": "regroup",
                "kind": "no_comparable_sinks",
                "node": None,
                "detail": (f"grouping {label!r} left no sink shared with "
                           f"the ungrouped baseline — nothing to compare"),
            })
            continue
        for nid in shared:
            got = _stable(r.node_outputs.get(nid))
            if got != base_sinks[nid]:
                violations.append({
                    "layer": "regroup",
                    "kind": "regroup_divergence",
                    "node": nid,
                    "grouping": label,
                    "detail": (f"sink {nid!r} under grouping {label!r} "
                               f"cooked {got[:120]} but ungrouped baseline "
                               f"cooked {base_sinks[nid][:120]}"),
                })
    return violations


# ── convene: all layers, cheapest-first, fail-closed ─────────────────

def convene(workflow: dict, *,
            edit_fns: Any = None,
            grouping_a: Optional[list] = None,
            grouping_b: Optional[list] = None,
            determinism_n: int = 3) -> dict:
    """Run every invariant layer over `workflow`, cheapest-first.

    Fail-closed: ANY violation from ANY layer — including a layer that
    raised — flips green to False. Optional layers (metamorphic needs
    `edit_fns`; regroup needs both groupings) are skipped when their
    inputs are absent, and the `layers` list records what actually ran
    so a skipped layer can never masquerade as a passed one."""
    violations: list = []
    layers_run: list = []

    # Layer 0 — impossible states (2 cooks of one runner; the second
    # cook is the frozen-mutation probe against the snapshot).
    try:
        r = WorkflowRunner(copy.deepcopy(workflow))
        r.run_all()
        snap = snapshot_frozen(r)
        r.run_all()
        violations += check_impossible_states(workflow, r,
                                              frozen_snapshot=snap)
        layers_run.append("impossible_states")
    except Exception as ex:
        violations.append({"layer": "impossible_states",
                           "kind": "exception",
                           "node": None,
                           "detail": f"{type(ex).__name__}: {ex}"})

    # Layer 1 — metamorphic MR-1 (2 cooks per edit).
    if edit_fns is not None:
        fns = edit_fns if isinstance(edit_fns, (list, tuple)) \
            else [edit_fns]
        for i, fn in enumerate(fns):
            try:
                if not metamorphic_full_vs_incremental(workflow, fn):
                    violations.append({
                        "layer": "metamorphic",
                        "kind": "full_vs_incremental_divergence",
                        "node": None,
                        "edit": i,
                        "detail": (f"edit #{i}: incremental recook "
                                   f"disagrees with full cook at a sink"),
                    })
            except Exception as ex:
                violations.append({"layer": "metamorphic",
                                   "kind": "exception",
                                   "node": None, "edit": i,
                                   "detail": f"{type(ex).__name__}: {ex}"})
        layers_run.append("metamorphic")

    # Layer 2 — determinism (n cooks).
    try:
        violations += determinism_check(workflow, n=determinism_n)
        layers_run.append("determinism")
    except Exception as ex:
        violations.append({"layer": "determinism", "kind": "exception",
                           "node": None,
                           "detail": f"{type(ex).__name__}: {ex}"})

    # Layer 3 — regroup invariance (3 cooks + composes).
    if grouping_a is not None and grouping_b is not None:
        try:
            violations += regroup_invariance(workflow,
                                             grouping_a, grouping_b)
            layers_run.append("regroup")
        except Exception as ex:
            violations.append({"layer": "regroup", "kind": "exception",
                               "node": None,
                               "detail": f"{type(ex).__name__}: {ex}"})

    return {"green": not violations,
            "violations": violations,
            "layers": layers_run}
