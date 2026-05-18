"""WorkflowRunner — wires are real data bridges, not decoration.

Per ADR-003 + the wire-as-data-bridge research:
  • Each edge carries a typed runtime VALUE (not just a position record).
  • Execution is **lazy + dirty + cached** (Houdini cook-graph pattern).
  • A node's `cache_key` = hash(config + sorted upstream cache_keys).
  • `pull(node_id)` walks upstream, only re-executes dirty parents.
  • Values flow forward via `WireBus` (in-process dict, never serialized).
  • Persistence whitelist + size cap keeps session.graph small.

This module is **engine-only** — no Qt, no widgets. The bridge (app/
bridge.py) wraps `runner.pull` + emits the wire-state signals to JS.

Public API:
    runner = WorkflowRunner(graph_dict)
    runner.pull("node_id")        → outputs dict for that node
    runner.mark_dirty("node_id")  → cascades dirty downstream
    runner.wire_state("edge_id")  → "idle"|"flowing"|"cached"|"stale"|...
    runner.wire_value("edge_id")  → the in-memory value (never persisted
                                     if size > MAX_PERSIST_BYTES)

WireBus is kept in-process. The on-disk `Edge.value_preview` is
populated on each cook with `repr(value)[:200]` so hover tooltips on
the canvas can show what the wire just carried, but the actual blob
never bloats the JSON.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Optional

from . import registry
from . import typesystem
from .graph import PortType


# ── profound-wire field selectors ───────────────────────────────────
# A small dotted-path resolver. Supports:
#   "a.b.c"          — walk attrs / dict keys
#   "items[0]"       — list index
#   "items[-1].name" — chained
#   "a['b c']"       — bracketed string key with spaces
# Missing pieces resolve to None instead of raising. This keeps a
# slightly-wrong selector from blowing up the whole graph cook — the
# downstream node just sees None on that input.
_TOKEN_RE = re.compile(
    r"""
    (?P<dot>\.)
    | \[ \s* (?P<idx>-?\d+) \s* \]
    | \[ \s* (?P<sqkey>'[^']*'|\"[^\"]*\") \s* \]
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


def _tokenize_path(path: str) -> list:
    """Split a dotted/bracketed path into ('key'|'idx', value) tokens."""
    if not path:
        return []
    toks: list = []
    i = 0
    while i < len(path):
        m = _TOKEN_RE.match(path, i)
        if not m:
            i += 1
            continue
        if m.group("dot"):
            pass
        elif m.group("idx") is not None:
            toks.append(("idx", int(m.group("idx"))))
        elif m.group("sqkey") is not None:
            toks.append(("key", m.group("sqkey")[1:-1]))
        elif m.group("name") is not None:
            toks.append(("key", m.group("name")))
        i = m.end()
    return toks


def _resolve_field(value: Any, path: str) -> Any:
    """Walk a dotted/bracketed path through dicts/lists/attrs.

    Returns None on any miss (keyError / indexError / no-attr) so the
    caller can decide whether to treat that as a soft failure. Never
    raises for normal lookup misses — only for genuinely malformed
    paths handled implicitly by the tokenizer."""
    if not path:
        return value
    cur = value
    for kind, key in _tokenize_path(path):
        if cur is None:
            return None
        if kind == "idx":
            try:
                cur = cur[key]
            except (IndexError, TypeError, KeyError):
                return None
        else:  # 'key'
            if isinstance(cur, dict):
                if key in cur:
                    cur = cur[key]
                else:
                    return None
            else:
                # Attribute access on objects — whitelist only public
                # attrs. Dunders and private names ('_x', '__class__',
                # '__subclasses__'…) could walk Python internals and
                # leak / DoS via large traversals. Return None instead.
                if hasattr(cur, key) and not key.startswith("_"):
                    cur = getattr(cur, key, None)
                else:
                    return None
    return cur


def _wrap_field(value: Any, path: str) -> Any:
    """Inverse of _resolve_field — wrap `value` into a nested dict so
    that resolving `path` on the result returns `value`.

    Used to package an incoming value into a sub-key of a structured
    input slot. List-index segments become integer-keyed dicts (we keep
    it simple — receivers that care can index into them).
    """
    if not path:
        return value
    toks = _tokenize_path(path)
    if not toks:
        return value
    cur: Any = value
    for kind, key in reversed(toks):
        if kind == "idx":
            cur = {int(key): cur}
        else:
            cur = {key: cur}
    return cur


def _enumerate_paths(value: Any, *, max_depth: int = 4,
                      max_items: int = 200,
                      _prefix: str = "",
                      _out: Optional[list] = None) -> list:
    """Walk a sample value and return every dotted path you could pass
    to `_resolve_field` to fetch a sub-value.

    Used by the bridge `list_wire_fields` slot — given the last value
    that flowed on a wire, the canvas can show the user a picker of
    available sub-fields. Stays bounded so a huge selection dict doesn't
    enumerate a million paths."""
    out = _out if _out is not None else []
    if len(out) >= max_items or max_depth < 0:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            seg = key if (key.replace("_", "").isalnum()
                          and key and not key[0].isdigit()) \
                  else f"['{key}']"
            path = (f"{_prefix}.{seg}"
                    if _prefix and not seg.startswith("[") else
                    f"{_prefix}{seg}" if _prefix else seg)
            out.append(path)
            if isinstance(v, (dict, list)):
                _enumerate_paths(v, max_depth=max_depth - 1,
                                  max_items=max_items, _prefix=path,
                                  _out=out)
            if len(out) >= max_items:
                return out
    elif isinstance(value, list):
        # Enumerate first few indices only — show last item too because
        # AI message lists often want messages[-1].content.
        n = len(value)
        idxs = list(range(min(3, n)))
        if n > 0:
            idxs.append(-1)
        for i in idxs:
            path = f"{_prefix}[{i}]"
            out.append(path)
            if isinstance(value[i], (dict, list)):
                _enumerate_paths(value[i], max_depth=max_depth - 1,
                                  max_items=max_items, _prefix=path,
                                  _out=out)
            if len(out) >= max_items:
                return out
    return out


# Persistence whitelist — Python types we'll happily cache to the WireBus.
# Larger types (GEOMETRY / IMAGE / IFC / DOCUMENT) live only in the per-cook
# in-memory map; we never pickle them back so a 50 MB IFC model can't
# bloat session.graph on reload.
PERSISTABLE_TYPES = (str, int, float, bool, list, dict, tuple, type(None))

MAX_PERSIST_BYTES = 64 * 1024   # 64 KB upper bound per wire cache


def _wire_safe(v):
    """Return True if `v` is small + simple enough to keep on the WireBus.

    Whitelist-by-type + size-cap. Anything else stays off the bus so the
    runner can still cook the graph but reload won't carry the blob."""
    try:
        if v is None:
            return True
        if isinstance(v, PERSISTABLE_TYPES):
            try:
                import json as _j
                return len(_j.dumps(v, default=str).encode('utf-8')) <= MAX_PERSIST_BYTES
            except Exception:
                return False
        return False
    except Exception:
        return False


class CycleDetected(RuntimeError):
    """Raised when a pull would traverse a cycle. The canvas's drop-
    validation calls `would_create_cycle` to prevent these at edit time,
    but the runner double-checks at run time."""


class WorkflowRunner:
    """Cook a node graph the Houdini way: lazy, dirty, cached."""

    # ── construction ────────────────────────────────────────────────
    def __init__(self, graph: dict, *,
                  router: Any = None,
                  tool_engine: Any = None,
                  manager: Any = None,
                  ctx: Any = None):
        # Graph shape matches the JSX prototype's LM_GRAPH + the
        # Workflow.to_dict shape:
        #   {"nodes": [{id, type, config, position, ins?, outs?, ...}],
        #    "wires"|"edges": [{from:[node,port], to:[node,port]}]
        #                  OR [{id, src_node, src_port, dst_node, dst_port}]}
        #
        # ctx threading: executors receive a context object whose attrs
        # the live-cook executors (conversation.chat, host.*) reach into:
        #   ctx.router       — LLMRouter (for conversation.chat round-trips)
        #   ctx.tool_engine  — ToolEngine (for tool-call execution)
        #   ctx.manager      — provider config manager
        # Callers can either pass these as kwargs (legacy bridge style)
        # or hand in a prebuilt ctx (any object with the right attrs).
        if ctx is None:
            from types import SimpleNamespace
            ctx = SimpleNamespace(router=router,
                                   tool_engine=tool_engine,
                                   manager=manager)
        self.ctx = ctx
        self.nodes_by_id: dict[str, dict] = {}
        for n in graph.get("nodes") or []:
            nid = n.get("id")
            if not nid:
                continue
            self.nodes_by_id[nid] = dict(n)

        self.edges: list[dict] = []
        for e in (graph.get("wires") or graph.get("edges") or []):
            # Normalise to a canonical {src_node, src_port, dst_node, dst_port}
            if "from" in e and "to" in e:
                f, t = e["from"], e["to"]
                edge = {
                    "id":       e.get("id") or f"{f[0]}.{f[1]}-{t[0]}.{t[1]}",
                    "src_node": f[0], "src_port": f[1],
                    "dst_node": t[0], "dst_port": t[1],
                    "cache_key": e.get("cache_key", ""),
                    "state":     e.get("state", "idle"),
                    "src_field": e.get("src_field", "") or "",
                    "dst_field": e.get("dst_field", "") or "",
                }
            else:
                edge = {
                    "id":       e.get("id") or
                                f"{e['src_node']}.{e['src_port']}-"
                                f"{e['dst_node']}.{e['dst_port']}",
                    "src_node": e["src_node"], "src_port": e["src_port"],
                    "dst_node": e["dst_node"], "dst_port": e["dst_port"],
                    "cache_key": e.get("cache_key", ""),
                    "state":     e.get("state", "idle"),
                    "src_field": e.get("src_field", "") or "",
                    "dst_field": e.get("dst_field", "") or "",
                }
            self.edges.append(edge)

        # WireBus: edge_id → value. Never persisted.
        self.wire_bus: dict[str, Any] = {}
        # Per-node fresh cache_keys + last-run state.
        self.node_cache_keys: dict[str, str] = {}
        self.node_outputs: dict[str, dict] = {}
        self.node_dirty: set[str] = set(self.nodes_by_id.keys())
        # Wire-state subscriber (bridge wires this to QWebChannel signal).
        self._on_wire_state: Optional[Callable[[str, str, str], None]] = None
        # Re-entrancy guard for auto-rerun loops.
        self._visiting: set[str] = set()

    # ── observation ─────────────────────────────────────────────────
    def on_wire_state(self,
                       cb: Callable[[str, str, str], None]) -> None:
        """Register a `cb(edge_id, state, preview)` listener.

        Called whenever a wire flips state. The bridge wires this to a
        Qt signal so the JS canvas can update wire stroke patterns.
        """
        self._on_wire_state = cb

    def _emit(self, edge_id: str, state: str,
              preview: str = "") -> None:
        try:
            for e in self.edges:
                if e["id"] == edge_id:
                    e["state"] = state
                    if preview:
                        e["value_preview"] = preview
                    break
        except Exception:
            pass
        if self._on_wire_state:
            try:
                self._on_wire_state(edge_id, state, preview)
            except Exception:
                pass

    # ── topology ────────────────────────────────────────────────────
    def _upstream_edges(self, node_id: str) -> list[dict]:
        return [e for e in self.edges if e["dst_node"] == node_id]

    def _downstream_edges(self, node_id: str) -> list[dict]:
        return [e for e in self.edges if e["src_node"] == node_id]

    def would_create_cycle(self, src_node: str, dst_node: str) -> bool:
        """Returns True if adding src→dst would create a cycle.

        Pure DFS from `dst_node` looking for `src_node`. The canvas
        calls this before committing a drop so cycles are prevented at
        edit time rather than crashing the runner."""
        if src_node == dst_node:
            return True
        seen = {dst_node}
        stack = [dst_node]
        while stack:
            n = stack.pop()
            for e in self._downstream_edges(n):
                nxt = e["dst_node"]
                if nxt == src_node:
                    return True
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        return False

    # ── dirty cascade ───────────────────────────────────────────────
    def mark_dirty(self, node_id: str) -> set[str]:
        """Stamp this node + every descendant as dirty.

        Returns the set of node ids touched so the bridge can push wire-
        state=stale events for incident edges."""
        touched: set[str] = set()
        stack = [node_id]
        while stack:
            n = stack.pop()
            if n in touched:
                continue
            touched.add(n)
            self.node_dirty.add(n)
            for e in self._downstream_edges(n):
                stack.append(e["dst_node"])
                # Edge enters "stale" state — values still in WireBus
                # but no longer authoritative.
                self._emit(e["id"], "stale",
                            e.get("value_preview") or "")
        return touched

    # ── cache key ───────────────────────────────────────────────────
    def _compute_cache_key(self, node_id: str) -> str:
        node = self.nodes_by_id.get(node_id) or {}
        h = hashlib.sha256()
        h.update(node.get("type", "").encode("utf-8"))
        cfg = node.get("config") or {}
        try:
            h.update(json.dumps(cfg, sort_keys=True,
                                  default=str).encode("utf-8"))
        except Exception:
            h.update(repr(cfg).encode("utf-8"))
        for e in sorted(self._upstream_edges(node_id),
                          key=lambda x: (x["dst_port"], x["src_node"])):
            h.update(e["dst_port"].encode("utf-8"))
            parent_key = self.node_cache_keys.get(e["src_node"], "")
            h.update(parent_key.encode("utf-8"))
            # Profound-wire selectors are part of the cache key — changing
            # the selector should invalidate the downstream cache even if
            # the upstream cooked value hasn't changed.
            sf = e.get("src_field") or ""
            df = e.get("dst_field") or ""
            if sf or df:
                h.update(b"|sf|")
                h.update(sf.encode("utf-8"))
                h.update(b"|df|")
                h.update(df.encode("utf-8"))
        return h.hexdigest()

    # ── pull (lazy + cached) ────────────────────────────────────────
    def pull(self, node_id: str) -> dict:
        """Cook this node (if dirty) + return its outputs dict.

        Recursively pulls upstream parents first. Caches results so a
        second pull with no upstream change returns immediately.

        Frozen nodes (`node.frozen == True`) short-circuit: they return
        their last cached outputs (or a sentinel) without re-cooking.
        This is the Houdini "bypass" pattern — let the user pin a node's
        state while iterating upstream parts of the graph.
        """
        if node_id in self._visiting:
            raise CycleDetected(f"cycle through {node_id}")
        if node_id not in self.nodes_by_id:
            return {"status": "error", "error": f"unknown node {node_id}"}

        node = self.nodes_by_id[node_id]
        if node.get("frozen") is True:
            return self.node_outputs.get(node_id,
                {"status": "ok", "frozen": True})
        node_type = node.get("type") or ""
        # Pull upstream first.
        inputs: dict[str, Any] = {}
        self._visiting.add(node_id)
        try:
            for e in self._upstream_edges(node_id):
                parent_out = self.pull(e["src_node"])
                if isinstance(parent_out, dict):
                    if parent_out.get("status") == "error":
                        # Propagate as upstream_error on the edge.
                        self._emit(e["id"], "upstream_error",
                                    repr(parent_out.get("error", ""))[:200])
                        return {"status": "upstream_error",
                                "from": e["src_node"],
                                "error": parent_out.get("error")}
                    value = parent_out.get(e["src_port"])
                else:
                    value = parent_out
                # "Profound wire" — apply src_field on the way out of
                # the source (pick a sub-value), then dst_field on the
                # way in to the destination (wrap into a sub-key).
                sf = e.get("src_field") or ""
                if sf:
                    value = _resolve_field(value, sf)
                df = e.get("dst_field") or ""
                if df:
                    value = _wrap_field(value, df)
                inputs[e["dst_port"]] = value
                # Park value on the bus + emit "flowing" then "cached".
                # Only whitelisted, size-capped values go on the wire bus —
                # see PERSISTABLE_TYPES / MAX_PERSIST_BYTES at module scope.
                if _wire_safe(value):
                    self.wire_bus[e["id"]] = value
                self._emit(e["id"], "flowing")
        finally:
            self._visiting.discard(node_id)

        new_key = self._compute_cache_key(node_id)
        old_key = self.node_cache_keys.get(node_id, "")
        if (new_key == old_key and node_id not in self.node_dirty
                and node_id in self.node_outputs):
            # Cache hit — flip incident edges back to "cached".
            for e in self._downstream_edges(node_id):
                if e["id"] in self.wire_bus:
                    self._emit(e["id"], "cached")
            return self.node_outputs[node_id]

        # Look up executor for this type.
        spec_tup = registry.get(node_type)
        if not spec_tup:
            err = {"status": "error",
                    "error": f"no executor for {node_type!r}"}
            self.node_outputs[node_id] = err
            return err
        _spec, executor = spec_tup

        cfg = dict(node.get("config") or {})
        try:
            outputs = executor(cfg, inputs, self.ctx)
            if not isinstance(outputs, dict):
                outputs = {"value": outputs}
        except Exception as ex:
            outputs = {"status": "error",
                        "error": f"{type(ex).__name__}: {ex}"}

        # Stash + flip wires to "cached".
        self.node_outputs[node_id] = outputs
        self.node_cache_keys[node_id] = new_key
        self.node_dirty.discard(node_id)
        for e in self._downstream_edges(node_id):
            v = outputs.get(e["src_port"]) if isinstance(outputs, dict) else None
            # See PERSISTABLE_TYPES / MAX_PERSIST_BYTES at module scope —
            # keeps large or unwhitelisted payloads off the bus.
            if _wire_safe(v):
                self.wire_bus[e["id"]] = v
            try:
                preview = repr(v)[:200]
            except Exception:
                preview = type(v).__name__
            self._emit(e["id"], "cached", preview)

        return outputs

    # ── workflow-level run (Houdini "render", Comfy "queue") ────────
    def run_all(self) -> dict:
        """Cook every sink node in the graph (nodes with no downstream
        edges). Pulls cascade upstream automatically via `pull`. Frozen
        nodes are skipped. Returns a per-node result map."""
        downstream_targets = {e["src_node"] for e in self.edges}
        sinks = [nid for nid in self.nodes_by_id
                  if nid not in downstream_targets]
        if not sinks:
            # No clear sinks (e.g. all nodes feed each other) — cook
            # every non-frozen node so user gets some progress.
            sinks = [nid for nid, n in self.nodes_by_id.items()
                      if not n.get("frozen")]
        out: dict[str, dict] = {}
        for nid in sinks:
            try:
                out[nid] = self.pull(nid)
            except CycleDetected as ex:
                out[nid] = {"status": "error", "error": str(ex)}
        return {"status": "ok",
                "sinks": sinks,
                "results": out,
                "edges_state": [
                    {"id": e["id"], "state": e.get("state", "idle")}
                    for e in self.edges
                ]}

    # ── observability ───────────────────────────────────────────────
    def wire_state(self, edge_id: str) -> str:
        for e in self.edges:
            if e["id"] == edge_id:
                return e.get("state", "idle")
        return "unknown"

    def wire_value(self, edge_id: str) -> Any:
        return self.wire_bus.get(edge_id)

    def persistable_state(self) -> dict:
        """Return a dict suitable for stashing into session.graph.

        Keeps cache_keys + states (so reopen detects "still fresh") but
        drops the actual values (those re-cook on demand)."""
        return {
            "edges": [
                {"id": e["id"],
                 "cache_key": e.get("cache_key", ""),
                 "state":     e.get("state", "idle"),
                 "value_preview": e.get("value_preview", "")}
                for e in self.edges
            ],
            "node_cache_keys": dict(self.node_cache_keys),
        }
