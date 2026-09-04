"""Legacy typed-runtime WorkflowRunner.

Wires are real data bridges, not decoration, inside the old typed runtime.
This runner is compatibility machinery while behavior is consumed into the
Universal Cell authority in `10.PRODUCT/13.NODE-LANGUAGE`.

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
import base64
import json
import os
import re
import time
from typing import Any, Callable, Optional

from . import registry
from . import typesystem
from .graph import PortType


LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "superseded_by_universal_cell"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False


def _node_bool(node: dict, key: str, *aliases: str) -> bool:
    """Read a node behavior flag from top-level or config, with aliases."""
    if not isinstance(node, dict):
        return False
    keys = (key,) + aliases
    for k in keys:
        if node.get(k) is True:
            return True
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    return any(cfg.get(k) is True for k in keys)


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


RUNTIME_WIRE_FIELDS = (
    "wire_node",
    "endpoint_nodes",
    "source_endpoint_node",
    "target_endpoint_node",
    "source_cardinality",
    "target_cardinality",
    "fan_in_count",
    "fan_out_count",
    "junction_node",
    "junction_nodes",
    "value_type",
    "schema_ref",
    "gate_policy",
    "codec",
    "encryption",
    "encryption_key_ref",
    "behavior",
    "routing",
    "aggregation",
    "presentation",
    "provenance",
    "history_policy",
    "runtime_state",
)


_BLOCKING_GATE_POLICIES = {
    "0",
    "false",
    "off",
    "disabled",
    "disable",
    "blocked",
    "block",
    "deny",
    "denied",
    "closed",
    "stop",
}


def _wire_gate_blocks(edge: dict) -> bool:
    """Return True when the wire relation's gate layer rejects flow."""
    if edge.get("enabled") is False:
        return True
    policy = str(edge.get("gate_policy") or "").strip().lower()
    if not policy:
        return False
    return (
        policy in _BLOCKING_GATE_POLICIES
        or policy.startswith("deny:")
        or policy.startswith("block:")
    )


def _coerce_port_type(value: Any) -> str:
    return typesystem.normalize_type_ref(value)


def _port_contract(node: dict, port_name: str, direction: str) -> tuple[str, bool]:
    """Read a node port's type/exec contract from canvas or Workflow shape."""
    ports = []
    if direction == "out":
        ports = node.get("outs") or node.get("outputs") or []
    else:
        ports = node.get("ins") or node.get("inputs") or []
    for port in ports:
        if not isinstance(port, dict):
            continue
        name = port.get("id") or port.get("name")
        if name != port_name:
            continue
        raw_type = (
            port.get("t")
            or port.get("type")
            or port.get("speckle_type")
            or "any"
        )
        return _coerce_port_type(raw_type), bool(port.get("exec"))
    return PortType.ANY.value, False


def _input_port_accepts_multiple(node: dict, port_name: str) -> bool:
    for port in node.get("ins") or node.get("inputs") or []:
        if not isinstance(port, dict):
            continue
        if (port.get("id") or port.get("name")) == port_name:
            return bool(port.get("multiple"))
    return False


def _wire_type_block_reason(edge: dict,
                            nodes_by_id: dict[str, dict]) -> str:
    """Return a human-readable reason when the type gate rejects the edge."""
    policy = str(edge.get("gate_policy") or "").strip().lower()
    if "type-compatible" not in policy:
        return ""
    src_node = nodes_by_id.get(edge.get("src_node")) or {}
    dst_node = nodes_by_id.get(edge.get("dst_node")) or {}
    src_type, src_exec = _port_contract(src_node, edge.get("src_port"), "out")
    dst_type, dst_exec = _port_contract(dst_node, edge.get("dst_port"), "in")
    if edge.get("value_type") not in (None, ""):
        src_type = _coerce_port_type(edge.get("value_type"))
    if typesystem.can_wire(src_type, dst_type,
                           output_is_exec=src_exec,
                           input_is_exec=dst_exec):
        return ""
    return f"type_mismatch:{src_type}->{dst_type}"


def _wire_schema_block_reason(edge: dict) -> str:
    policy = str(edge.get("gate_policy") or "").strip().lower()
    if "require-schema" not in policy:
        return ""
    if edge.get("schema_ref") in (None, ""):
        return "schema_required"
    return ""


def _wire_block_reason(edge: dict,
                       nodes_by_id: dict[str, dict]) -> str:
    if _wire_gate_blocks(edge):
        return str(edge.get("gate_policy") or "blocked")[:200]
    schema_reason = _wire_schema_block_reason(edge)
    if schema_reason:
        return schema_reason[:200]
    try:
        fan_in_count = int(edge.get("fan_in_count") or 1)
    except (TypeError, ValueError):
        fan_in_count = 1
    target_cardinality = str(edge.get("target_cardinality") or "one").lower()
    target_node = nodes_by_id.get(edge.get("dst_node")) or {}
    accepts_many = (
        target_cardinality in {"many", "multiple", "list", "collection", "*"}
        or _input_port_accepts_multiple(target_node, edge.get("dst_port"))
    )
    if fan_in_count > 1 and not accepts_many:
        return "multiple_sources_require_many_target"
    return _wire_type_block_reason(edge, nodes_by_id)[:200]


def _wire_layer_name(edge: dict, key: str) -> str:
    return str(edge.get(key) or "none").strip().lower()


_FORCE_RECOOK_WIRE_BEHAVIORS = {
    "always",
    "always-recook",
    "force",
    "force-recook",
    "live",
    "no-cache",
}


def _wire_forces_source_recook(edge: dict) -> bool:
    """Return True when the behavior layer makes this relation sample live."""
    return _wire_layer_name(edge, "behavior") in _FORCE_RECOOK_WIRE_BEHAVIORS


def _wire_codec_roundtrip(value: Any, codec: str) -> tuple[Any, Any, str]:
    """Encode/decode one wire payload through its codec layer.

    Returns (transport_value, delivered_value, error). The transport value is
    what lives on the wire bus; delivered value is what the downstream input
    receives after decoding.
    """
    if codec in ("", "none", "raw", "pass", "passthrough"):
        return value, value, ""
    if codec in ("json", "application/json"):
        try:
            text = json.dumps(value, sort_keys=True, default=str)
            return text, json.loads(text), ""
        except Exception as ex:
            return None, None, f"codec_json:{type(ex).__name__}: {ex}"
    if codec in ("text", "string", "utf8", "utf-8"):
        text = "" if value is None else str(value)
        return text, text, ""
    if codec in ("base64", "binary", "image-uri"):
        try:
            if isinstance(value, bytes):
                raw = value
                media_type = "application/octet-stream"
                delivered = value
            else:
                raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
                media_type = "application/json"
                delivered = json.loads(raw.decode("utf-8"))
            encoded = base64.b64encode(raw).decode("ascii")
            if codec == "image-uri":
                if isinstance(value, str) and value.startswith("data:image/"):
                    return value, value, ""
                return f"data:{media_type};base64,{encoded}", delivered, ""
            return {
                "codec": f"{codec}:v1",
                "media_type": media_type,
                "data": encoded,
            }, delivered, ""
        except Exception as ex:
            return None, None, f"codec_{codec}:{type(ex).__name__}: {ex}"
    if codec in ("geometry-json", "ifc-fragment", "speckle-object"):
        try:
            text = json.dumps(value, sort_keys=True, default=str)
            return {
                "codec": f"{codec}:v1",
                "payload": json.loads(text),
            }, json.loads(text), ""
        except Exception as ex:
            return None, None, f"codec_{codec}:{type(ex).__name__}: {ex}"
    return None, None, f"unknown_codec:{codec}"


def _resolve_secret_reference(ref: str, ctx: Any) -> Any:
    """Resolve an ``op://`` reference at runtime without storing its value."""
    if not ref or not str(ref).startswith("op://"):
        return None
    for attr in ("resolve_secret_ref", "secret_resolver"):
        resolver = getattr(ctx, attr, None)
        if callable(resolver):
            return resolver(str(ref))
    secrets = getattr(ctx, "secret_refs", None)
    if isinstance(secrets, dict):
        return secrets.get(str(ref))
    return None


def _fernet_key_from_context(edge: dict, ctx: Any) -> bytes | None:
    """Resolve a Fernet key without requiring graph-stored secrets.

    Runtime can provide an ``op://`` key reference resolver, a scoped context
    key, or an environment key. Raw key material on a graph edge is forbidden.
    """
    encryption = _wire_layer_name(edge, "encryption")
    scoped_attrs = {
        "local-key": ("local_wire_fernet_key", "ARCHHUB_LOCAL_WIRE_FERNET_KEY"),
        "workspace-key": ("workspace_wire_fernet_key", "ARCHHUB_WORKSPACE_WIRE_FERNET_KEY"),
        "user-key": ("user_wire_fernet_key", "ARCHHUB_USER_WIRE_FERNET_KEY"),
    }
    attr_name, env_name = scoped_attrs.get(encryption, ("wire_fernet_key", "ARCHHUB_WIRE_FERNET_KEY"))
    key_ref = str(edge.get("encryption_key_ref") or "")
    raw = (
        _resolve_secret_reference(key_ref, ctx)
        or getattr(ctx, attr_name, None)
        or getattr(ctx, "wire_fernet_key", None)
        or os.environ.get(env_name)
        or os.environ.get("ARCHHUB_WIRE_FERNET_KEY")
    )
    if raw in (None, ""):
        return None
    if isinstance(raw, bytes):
        return raw
    return str(raw).encode("utf-8")


def _wire_transport_roundtrip(value: Any, edge: dict,
                              ctx: Any) -> tuple[Any, Any, str]:
    """Apply codec/encryption layers as a real wire transport.

    Downstream receives the decoded/decrypted value. The WireBus receives the
    transported representation, so encrypted wires do not expose plaintext via
    `wire_value`.
    """
    codec = _wire_layer_name(edge, "codec")
    encryption = _wire_layer_name(edge, "encryption")
    if edge.get("_raw_encryption_key_present"):
        return None, None, "raw_encryption_key_forbidden"
    key_ref = str(edge.get("encryption_key_ref") or "")
    if key_ref and not key_ref.startswith("op://"):
        return None, None, "encryption_key_ref_must_be_op_reference"
    if encryption in ("", "none", "off", "false", "0"):
        return _wire_codec_roundtrip(value, codec)

    if encryption == "redacted":
        transport_codec = codec if codec not in ("", "none", "raw", "pass", "passthrough") else "json"
        _transport_value, delivered_value, err = _wire_codec_roundtrip(value, transport_codec)
        if err:
            return None, None, err
        return {
            "redacted": True,
            "scheme": "redacted:v1",
            "codec": transport_codec,
            "value_type": type(value).__name__,
        }, delivered_value, ""

    if encryption == "secret-ref":
        if isinstance(value, str) and value.startswith("op://"):
            return {
                "secret_ref": value,
                "scheme": "secret-ref:v1",
            }, value, ""
        return None, None, "secret_ref_required"

    if encryption == "external-kms":
        return None, None, "encryption_kms_resolver_missing"

    if encryption not in ("fernet", "fernet:v1", "local-fernet",
                          "local-key", "workspace-key", "user-key"):
        return None, None, f"unknown_encryption:{encryption}"

    # Encryption needs bytes. If no codec was selected, JSON is the reversible
    # default for ordinary graph values.
    transport_codec = codec if codec not in ("", "none", "raw", "pass", "passthrough") else "json"
    encoded, decoded, err = _wire_codec_roundtrip(value, transport_codec)
    if err:
        return None, None, err
    key = _fernet_key_from_context(edge, ctx)
    if not key:
        return None, None, "encryption_key_missing:fernet"
    try:
        from cryptography.fernet import Fernet
        fernet = Fernet(key)
        raw = encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")
        token = fernet.encrypt(raw)
        restored_raw = fernet.decrypt(token)
        if transport_codec in ("json", "application/json"):
            restored_value = json.loads(restored_raw.decode("utf-8"))
        elif transport_codec in ("text", "string", "utf8", "utf-8"):
            restored_value = restored_raw.decode("utf-8")
        else:
            restored_value = decoded
        envelope = {
            "encrypted": True,
            "scheme": "fernet:v1",
            "codec": transport_codec,
            "token": token.decode("ascii"),
        }
        return envelope, restored_value, ""
    except Exception as ex:
        return None, None, f"encryption_fernet:{type(ex).__name__}: {ex}"


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


def _has_node_native_runtime_nodes(graph: dict) -> bool:
    """True when the graph carries first-class runtime plumbing nodes.

    The bridge normally calls node_grammar.normalize_canvas_graph before
    constructing a runner. Direct runner callers must get the same wire and
    parameter-node authority instead of silently depending on legacy flat
    inline config/edges.
    """
    if not isinstance(graph, dict):
        return False
    from .node_grammar import node_capabilities

    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        capabilities = node_capabilities(node)
        if capabilities.intersection({"parameter", "port", "relation-stage"}):
            return True
        if ("relation" in capabilities
                and (data.get("relation_family") == "workflow_wire"
                     or data.get("wire_family") == "workflow_wire")):
            return True
    return False


def _runner_graph(graph: dict) -> dict:
    """Return the executable graph shape used by WorkflowRunner.

    For legacy/engine-native graphs this is the original graph. For
    node-native workflow graphs, normalize once so wire nodes, layer nodes,
    parameter nodes, and presentation edges resolve to the same runtime edge
    model the bridge uses.
    """
    if not _has_node_native_runtime_nodes(graph):
        return graph
    from .node_grammar import normalize_canvas_graph
    return normalize_canvas_graph(graph)


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
        graph = _runner_graph(graph)
        self.nodes_by_id: dict[str, dict] = {}
        for n in graph.get("nodes") or []:
            nid = n.get("id")
            if not nid:
                continue
            self.nodes_by_id[nid] = dict(n)

        relation_records = (
            graph["relations"] if "relations" in graph
            else graph.get("wires") or graph.get("edges") or []
        )
        self.relations: list[dict] = []
        for e in relation_records:
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
            for key in RUNTIME_WIRE_FIELDS:
                value = e.get(key)
                if value not in (None, ""):
                    edge[key] = value
            if e.get("encryption_key") not in (None, ""):
                edge["_raw_encryption_key_present"] = True
            self.relations.append(edge)

        # Compatibility view for bridge/tests that still use the historic
        # name. It is the same list object, never a second topology model.
        self.edges = self.relations

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
        # AgDR-0034 deferred-audit fix (c) — serialise cook trees.
        # pull() mutates _visiting + wire_bus; two threads pulling the
        # same runner corrupt both. An RLock lets the recursive
        # (same-thread) upstream pulls re-enter freely while a second
        # thread blocks until the first cook tree finishes.
        import threading as _threading
        self._lock = _threading.RLock()
        # AgDR-0017 + M6 partial — per-graph `auto_publish` opts.
        # Shape: {"enabled": bool, "server_url": str, "model_name": str,
        #         "project_dir": str|None}. When `enabled=True`, every
        # successful sink in `run_all` is shipped through SpeckleWire
        # (+ optional server push) automatically, no `share.publish`
        # node required. The user sets this per-graph at save time.
        ap = graph.get("auto_publish") or {}
        self.auto_publish: dict = {
            "enabled":    bool(ap.get("enabled", False)),
            "server_url": str(ap.get("server_url", "") or ""),
            "model_name": str(ap.get("model_name", "") or "default"),
            "project_dir": ap.get("project_dir"),
        }

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
            for e in self.relations:
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
        return [e for e in self.relations if e["dst_node"] == node_id]

    def _downstream_edges(self, node_id: str) -> list[dict]:
        return [e for e in self.relations if e["src_node"] == node_id]

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
            for key in (
                "value_type",
                "schema_ref",
                "gate_policy",
                "codec",
                "encryption",
                "encryption_key_ref",
                "behavior",
            ):
                value = e.get(key)
                if value not in (None, ""):
                    h.update(f"|{key}|".encode("utf-8"))
                    h.update(str(value).encode("utf-8"))
        return h.hexdigest()

    # ── pull (lazy + cached) ────────────────────────────────────────
    def pull(self, node_id: str) -> dict:
        """Thread-safe entry point — serialises a whole cook tree per
        runner (AgDR-0034 audit fix c). The RLock lets a recursive
        upstream pull on the SAME thread re-enter freely; a second
        thread blocks until the first cook tree completes.

        OPT-IN court hook (SPEC §19 layer 0): when the env flag
        ``ARCHHUB_COURT_INVARIANTS=1`` is set, every cook is followed
        by an impossible-state scan (workflows/invariants.py) and a
        violation RAISES ``InvariantViolation``. The default path is
        byte-identical to before — one env read, no import, no check."""
        with self._lock:
            if os.environ.get("ARCHHUB_COURT_INVARIANTS", "") != "1":
                return self._pull(node_id)
            from . import invariants
            snap = invariants.snapshot_frozen(self)
            out = self._pull(node_id)
            bad = invariants.check_impossible_states(
                None, self, frozen_snapshot=snap)
            if bad:
                raise invariants.InvariantViolation(bad)
            return out

    def _pull(self, node_id: str) -> dict:
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
        if _node_bool(node, "frozen"):
            return self.node_outputs.get(node_id,
                {"status": "ok", "frozen": True})
        node_type = node.get("type") or ""
        # Pull upstream first.
        inputs: dict[str, Any] = {}
        self._visiting.add(node_id)
        try:
            for e in self._upstream_edges(node_id):
                block_reason = _wire_block_reason(e, self.nodes_by_id)
                if block_reason:
                    self._emit(e["id"], "blocked", block_reason)
                    continue
                if _wire_forces_source_recook(e):
                    self.node_dirty.add(e["src_node"])
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
                transport_value, delivered_value, wire_error = (
                    _wire_transport_roundtrip(value, e, self.ctx)
                )
                if wire_error:
                    self._emit(e["id"], "error", wire_error[:200])
                    return {"status": "wire_error",
                            "from": e["src_node"],
                            "edge": e["id"],
                            "error": wire_error}
                target_cardinality = str(e.get("target_cardinality") or "one").lower()
                accepts_many = (
                    target_cardinality in {"many", "multiple", "list", "collection", "*"}
                    or _input_port_accepts_multiple(node, e["dst_port"])
                )
                if accepts_many:
                    existing = inputs.get(e["dst_port"])
                    if existing is None:
                        inputs[e["dst_port"]] = [delivered_value]
                    elif isinstance(existing, list):
                        existing.append(delivered_value)
                    else:
                        inputs[e["dst_port"]] = [existing, delivered_value]
                else:
                    inputs[e["dst_port"]] = delivered_value
                # Park value on the bus + emit "flowing" then "cached".
                # Only whitelisted, size-capped values go on the wire bus —
                # see PERSISTABLE_TYPES / MAX_PERSIST_BYTES at module scope.
                if _wire_safe(transport_value):
                    self.wire_bus[e["id"]] = transport_value
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

        # Bypass — AgDR-0041 Property 6 (founder, 2026-05-24). Skip
        # execute entirely + pass upstream inputs straight through to
        # downstream outputs. Greedy match: out_port name == in_port
        # name (best), else first in_port with same type, else None.
        # No cache held; re-cooks every upstream change.
        if _node_bool(node, "bypass", "bypassed"):
            outputs: dict[str, Any] = {}
            outs = node.get("outs") or []
            ins = node.get("ins") or []
            in_by_name = {p.get("id") or p.get("name"): p
                          for p in ins if isinstance(p, dict)}
            for op in outs:
                if not isinstance(op, dict):
                    continue
                op_name = op.get("id") or op.get("name")
                op_type = op.get("t") or op.get("type")
                if op_name and op_name in inputs:
                    outputs[op_name] = inputs[op_name]
                    continue
                # type-only fallback
                for ip in ins:
                    ip_name = ip.get("id") or ip.get("name")
                    ip_type = ip.get("t") or ip.get("type")
                    if ip_type and ip_type == op_type and ip_name in inputs:
                        outputs[op_name] = inputs[ip_name]
                        break
                else:
                    outputs.setdefault(op_name, None)
            outputs.setdefault("status", "ok")
            outputs["bypassed"] = True
            self.node_outputs[node_id] = outputs
            self.node_cache_keys[node_id] = new_key
            self.node_dirty.discard(node_id)
            for e in self._downstream_edges(node_id):
                v = outputs.get(e["src_port"])
                if _wire_safe(v):
                    self.wire_bus[e["id"]] = v
                try:
                    preview = "○ bypassed"
                except Exception:
                    preview = "bypassed"
                self._emit(e["id"], "cached", preview)
            return outputs

        # Look up executor for this type.
        spec_tup = registry.get(node_type)
        if not spec_tup:
            err = {"status": "error",
                    "error": f"no executor for {node_type!r}"}
            self.node_outputs[node_id] = err
            return err
        _spec, executor = spec_tup

        cfg = dict(node.get("config") or {})
        _ctx_node_missing = object()
        _ctx_prev_node = getattr(self.ctx, "node", _ctx_node_missing)
        try:
            try:
                setattr(self.ctx, "node", node)
            except Exception:
                pass
            outputs = executor(cfg, inputs, self.ctx)
            if not isinstance(outputs, dict):
                outputs = {"value": outputs}
        except Exception as ex:
            outputs = {"status": "error",
                        "error": f"{type(ex).__name__}: {ex}"}
        finally:
            try:
                if _ctx_prev_node is _ctx_node_missing:
                    delattr(self.ctx, "node")
                else:
                    setattr(self.ctx, "node", _ctx_prev_node)
            except Exception:
                pass

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

    def _edge_state_entry(self, edge: dict) -> dict:
        entry = {
            "id": edge["id"],
            "state": edge.get("state", "idle"),
        }
        preview = edge.get("value_preview") or ""
        if preview:
            entry["preview"] = preview
        if edge["id"] in self.wire_bus:
            transport_value = self.wire_bus.get(edge["id"])
            if _wire_safe(transport_value):
                entry["transport_value"] = transport_value
        for key in ("src_field", "dst_field", *RUNTIME_WIRE_FIELDS):
            value = edge.get(key)
            if value not in (None, ""):
                entry[key] = value
        presentation = str(edge.get("presentation") or "").strip().lower()
        if presentation:
            entry["presentation_state"] = (
                "hidden" if presentation == "hidden" else "visible"
            )
        return entry

    def _edges_state(self) -> list[dict]:
        return [self._edge_state_entry(e) for e in self.relations]

    # ── workflow-level run (Houdini "render", Comfy "queue") ────────
    def run_all(self) -> dict:
        """Cook every sink node in the graph (nodes with no downstream
        edges). Pulls cascade upstream automatically via `pull`. Frozen
        nodes are skipped. Returns a per-node result map.

        AgDR-0017 + M6 partial: if `graph.auto_publish.enabled=True`,
        each sink's value is shipped through SpeckleWire automatically
        after the cook (+ optional server push). Failure to publish
        does NOT taint the cook — `published` list includes both
        successes and failures honestly."""
        downstream_targets = {e["src_node"] for e in self.relations}
        sinks = [nid for nid in self.nodes_by_id
                  if nid not in downstream_targets]
        if not sinks:
            # No clear sinks (e.g. all nodes feed each other) — cook
            # every non-frozen node so user gets some progress.
            sinks = [nid for nid, n in self.nodes_by_id.items()
                      if not _node_bool(n, "frozen")]
        out: dict[str, dict] = {}
        for nid in sinks:
            try:
                out[nid] = self.pull(nid)
            except CycleDetected as ex:
                out[nid] = {"status": "error", "error": str(ex)}
        published = self._maybe_auto_publish_sinks(out) \
            if self.auto_publish.get("enabled") else None
        result = {"status": "ok",
                   "sinks": sinks,
                   "results": out,
                   "edges_state": self._edges_state()}
        if published is not None:
            result["auto_publish"] = published
        return result

    # ── reachable-sinks downstream of a node ────────────────────────
    def reachable_sinks(self, node_id: str) -> list[str]:
        """The sink nodes (no downstream edges) reachable by walking
        DOWNSTREAM from `node_id`, inclusive.

        Used by `recook_from`: after a param edit on `node_id`, the only
        cooks that need re-running are the chains BETWEEN the edited node
        and the sinks it feeds — not every sink in the graph. If the
        edited node IS a sink (or a dead-end with no clear sink path),
        it's its own terminal and we return just `[node_id]` so the edit
        still re-cooks itself.
        """
        if node_id not in self.nodes_by_id:
            return []
        downstream_targets = {e["src_node"] for e in self.relations}
        seen: set[str] = set()
        sinks: list[str] = []
        stack = [node_id]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            outs = self._downstream_edges(n)
            if not outs:
                # n has no downstream edges → it's a sink (terminal).
                if n in self.nodes_by_id and n not in sinks:
                    sinks.append(n)
                continue
            for e in outs:
                stack.append(e["dst_node"])
        if not sinks:
            # Defensive: a cycle or odd topology left no terminal — cook
            # the edited node itself so its param change still takes.
            return [node_id] if node_id in self.nodes_by_id else []
        return sinks

    def recook_from(self, node_id: str) -> dict:
        """Re-cook the edited node + everything downstream of it.

        This is the param-edit cook path (court verdict + cook.recook_
        trigger): a slider/param change on `node_id` invalidates that
        node AND every node fed by it. We `mark_dirty(node_id)` (cascades
        the dirty flag + flips incident edges to "stale" downstream), then
        `pull` each reachable sink — the lazy walk re-cooks the edited
        node and the whole chain between it and the sinks, while branches
        unrelated to the edit stay cached (no full-graph thrash).

        Reuses the exact lazy+dirty+cached machinery as `pull`/`run_all`;
        invents no new dataflow. Returns the same shape as `run_all` so
        the bridge can treat the payload identically."""
        self.mark_dirty(node_id)
        sinks = self.reachable_sinks(node_id)
        out: dict[str, dict] = {}
        for nid in sinks:
            try:
                out[nid] = self.pull(nid)
            except CycleDetected as ex:
                out[nid] = {"status": "error", "error": str(ex)}
        published = self._maybe_auto_publish_sinks(out) \
            if self.auto_publish.get("enabled") else None
        result = {"status": "ok",
                   "recooked_from": node_id,
                   "sinks": sinks,
                   "results": out,
                   "edges_state": self._edges_state()}
        if published is not None:
            result["auto_publish"] = published
        return result

    def _maybe_auto_publish_sinks(self, sink_results: dict) -> list:
        """Ship every successful sink's value through SpeckleWire +
        optionally push to the configured server. Returns a list of
        per-sink outcomes — always honest, never raises."""
        published: list[dict] = []
        try:
            import sys as _sys
            from pathlib import Path as _Path
            APP = _Path(__file__).resolve().parents[1]
            if str(APP) not in _sys.path:
                _sys.path.insert(0, str(APP))
            from speckle_wire import SpeckleWire, default_project_dir
        except Exception as ex:
            return [{"status": "error",
                      "error": f"SpeckleWire unavailable: {ex}"}]
        ap = self.auto_publish
        pdir = ap.get("project_dir") or default_project_dir()
        try:
            wire = SpeckleWire(pdir)
        except Exception as ex:
            return [{"status": "error",
                      "error": f"SpeckleWire init failed: {ex}"}]
        try:
            for sink_id, sink_out in (sink_results or {}).items():
                if not isinstance(sink_out, dict):
                    continue
                value = sink_out.get("value")
                if value is None:
                    published.append({"sink_id": sink_id,
                                       "status": "skipped",
                                       "reason": "no value"})
                    continue
                try:
                    hash_id = wire.send(value)
                except Exception as ex:
                    published.append({"sink_id": sink_id,
                                       "status": "error",
                                       "error": f"send failed: {ex}"})
                    continue
                entry = {"sink_id": sink_id, "status": "ok",
                          "hash": hash_id,
                          "url": f"speckle://local/{hash_id}",
                          "mode": "disk"}
                # Optional server push.
                if ap.get("server_url"):
                    try:
                        from speckle_server import push_to_server
                        url = push_to_server(
                            value, ap["server_url"],
                            ap.get("model_name") or "default")
                        entry["url"] = url
                        entry["mode"] = "server"
                    except Exception as ex:
                        entry["mode"] = "disk_only_after_server_fail"
                        entry["server_error"] = (
                            f"{type(ex).__name__}: {ex}")
                published.append(entry)
        finally:
            try: wire.close()
            except Exception: pass  # audit: deliberate-fail-soft — best-effort wire close in finally; published data already sent
        return published

    # ── observability ───────────────────────────────────────────────
    def wire_state(self, edge_id: str) -> str:
        for e in self.relations:
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
                {k: v for k, v in {
                    "id": e["id"],
                    "cache_key": e.get("cache_key", ""),
                    "state": e.get("state", "idle"),
                    "value_preview": e.get("value_preview", ""),
                    **{key: e.get(key) for key in RUNTIME_WIRE_FIELDS},
                }.items() if v not in (None, "")}
                for e in self.relations
            ],
            "node_cache_keys": dict(self.node_cache_keys),
        }
