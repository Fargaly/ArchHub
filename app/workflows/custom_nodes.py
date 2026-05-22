"""Custom node-type loader.

The founder wants to mint new node types from the UI without editing
the codebase. Specs are persisted as JSON under
`%LOCALAPPDATA%\\ArchHub\\custom_nodes\\<type>.json` and re-registered
on every bridge boot.

Spec shape (all keys but `type` are optional):

    {
      "type":          "my.custom",
      "category":      "filter",
      "display_name":  "My filter",
      "description":   "Forwards inputs to outputs",
      "icon":          "⌗",
      "inputs":        ["walls"]          # list of names OR
                       [{"name": "...", "type": "list"}],
      "outputs":       ["filtered"],
      "config_schema": {...},
      "impl":          {"kind": "python", "code": "<source>"}
    }

AgDR-0038 — behaviour is data: an `impl` block discriminated by `kind`:

  • passthrough      — each output gets the same-named input (or the
                       first input value); the default when no `impl`.
  • python           — exec a user `execute(config, inputs, ctx) -> dict`
                       body in a RESTRICTED sandbox (no import / open /
                       exec / `__` attrs).  `impl.safe_mode = false`
                       lets a power user opt out.
  • connector        — a typed thin wrapper over a host connector op
                       (connectors.base.run_op); an offline host yields
                       an honest typed error, never a fabricated value.
  • ai               — an LLM-backed capability; routes through the
                       same LLMRouter that chat uses.

Back-compat: a legacy spec with a bare top-level `code` key and no
`impl` is normalised to `{"kind": "python", "code": ...}`, so every
existing custom-node JSON file keeps working.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .graph import Port, PortType
from .registry import NodeSpec, _REGISTRY, register
# AgDR-0038 Delta 4 — reuse the code.python sandbox contract (AgDR-0020)
# so a Capability Node's python body runs with RESTRICTED builtins, not
# the real __builtins__.  One sandbox contract for the whole codebase.
from .nodes.code import _build_safe_builtins, _has_forbidden_token


def custom_nodes_dir() -> Path:
    """Return `%LOCALAPPDATA%\\ArchHub\\custom_nodes` on Windows, or
    `~/.archhub/custom_nodes` elsewhere. Always ensures the dir exists."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base) / "ArchHub" / "custom_nodes"
    else:
        root = Path.home() / ".archhub" / "custom_nodes"
    root.mkdir(parents=True, exist_ok=True)
    return root


_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*$")


def _coerce_port(p: Any) -> Port:
    """Accept either a bare name string or a `{name, type, ...}` dict."""
    if isinstance(p, str):
        return Port(name=p, type=PortType.ANY)
    if isinstance(p, dict):
        try:
            t = PortType(p.get("type", "any"))
        except Exception:
            t = PortType.ANY
        return Port(
            name=str(p.get("name", "")),
            type=t,
            description=str(p.get("description", "") or ""),
        )
    raise ValueError(f"port must be a string or dict, got {type(p).__name__}")


def _spec_from_dict(spec: dict) -> NodeSpec:
    type_name = str(spec.get("type", "")).strip()
    if not type_name or not _TYPE_RE.match(type_name):
        raise ValueError(
            "type is required and must match [A-Za-z][A-Za-z0-9_.-]*")
    inputs = [_coerce_port(p) for p in (spec.get("inputs") or []) if p]
    outputs = [_coerce_port(p) for p in (spec.get("outputs") or []) if p]
    return NodeSpec(
        type=type_name,
        category=str(spec.get("category", "misc") or "misc"),
        display_name=str(spec.get("display_name") or type_name),
        description=str(spec.get("description", "") or ""),
        inputs=inputs,
        outputs=outputs,
        config_schema=spec.get("config_schema") or {},
        icon=str(spec.get("icon", "") or ""),
    )


def _map_outputs(value, output_names: list[str]) -> dict:
    """Shape an executor's raw return into the spec's declared outputs.

    - a dict that already names >=1 declared output -> returned as-is
      (the executor spoke the spec's language).
    - exactly one declared output -> {that_name: value}.
    - otherwise -> {"value": value}.
    """
    if isinstance(value, dict) and output_names and any(
            n in value for n in output_names):
        return value
    if len(output_names) == 1:
        return {output_names[0]: value}
    return {"value": value}


def _connector_executor(impl: dict, output_names: list[str]):
    """impl.kind=connector (AgDR-0038 slice 2) — a typed thin wrapper
    over a host connector op.

    impl keys:
      host, op   select the connector operation
      arg_map    {op_param: input_name} — remap node inputs to op params
                 (identity mapping when absent)
      args       {op_param: literal}    — static params, merged under inputs

    Calls connectors.base.run_op. An offline host returns an honest
    typed error — never a fabricated value (connector-honesty mandate).
    """
    host = str(impl.get("host", "") or "").strip()
    op = str(impl.get("op", "") or "").strip()
    op_id = op if "." in op else (f"{host}.{op}" if host and op else "")
    arg_map = impl.get("arg_map") or {}
    static = impl.get("args") or {}

    def _exec(_config: dict, inputs: dict, _ctx) -> dict:
        if not op_id:
            return {"error": "connector impl needs `host` + `op`"}
        inputs = inputs or {}
        if arg_map:
            params = {p: inputs.get(src) for p, src in arg_map.items()}
        else:
            params = dict(inputs)
        params = {**static, **params}
        try:
            from connectors.base import run_op
        except Exception as ex:
            return {"error": f"connectors unavailable: {ex}"}
        res = run_op(op_id, **params)
        if not getattr(res, "ok", False):
            return {"error": getattr(res, "error", "") or f"{op_id} failed",
                    "op_id": op_id}
        return _map_outputs(getattr(res, "value", None), output_names)

    return _exec


def _ai_executor(impl: dict, output_names: list[str]):
    """impl.kind=ai (AgDR-0038 slice 2) — an LLM-backed capability.

    impl keys:
      model            model id, or "auto" (default)
      prompt_template  str.format-ed with the node inputs
      output_parse     "text" (default) | "json"

    Routes through ctx.router — the same LLMRouter chat uses. No router
    in context -> an honest `missing_dep` error, not a fabricated answer.
    """
    model = str(impl.get("model") or "auto")
    template = str(impl.get("prompt_template") or "")
    parse = str(impl.get("output_parse") or "text").lower()

    def _exec(_config: dict, inputs: dict, ctx) -> dict:
        if ctx is None or not getattr(ctx, "router", None):
            return {"status": "missing_dep",
                    "error": "no LLM router in execution context — set a "
                             "provider key in Settings -> Providers"}
        inputs = inputs or {}
        try:
            prompt = template.format(**inputs)
        except Exception:
            prompt = template          # unfilled placeholder — send as-is
        if not prompt.strip():
            return {"error": "ai impl has an empty prompt_template"}
        buf: list[str] = []
        try:
            response = ctx.router.complete(
                history=[{"role": "user", "content": prompt}],
                model=model,
                on_chunk=lambda piece: buf.append(piece),
                on_tool_invocation=lambda inv: None,
            )
        except Exception as ex:
            return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}
        text = getattr(response, "text", "") or "".join(buf)
        if parse == "json":
            import json as _json
            try:
                parsed = _json.loads(text)
            except Exception:
                return {"error": "ai output is not valid JSON "
                                 "(impl.output_parse=json)", "raw": text}
            return _map_outputs(parsed, output_names)
        return _map_outputs(text, output_names)

    return _exec


def _ports_of(node: dict, side: str) -> list[dict]:
    """A node's ports as [{id, type}] — read from the node's own
    ins/outs (canvas shape) or inputs/outputs (workflow shape), else
    resolved from the registry NodeSpec by `type`."""
    keys = ("ins", "inputs") if side == "in" else ("outs", "outputs")
    for k in keys:
        lst = node.get(k)
        if isinstance(lst, list) and lst:
            out: list[dict] = []
            for p in lst:
                if isinstance(p, dict):
                    pid = p.get("id") or p.get("name")
                    if pid:
                        out.append({"id": pid,
                                    "type": p.get("t") or p.get("type") or "any"})
                elif isinstance(p, str):
                    out.append({"id": p, "type": "any"})
            return out
    try:
        from .registry import get as _rget
        hit = _rget(str(node.get("type") or ""))
        if hit:
            spec = hit[0]
            ports = spec.inputs if side == "in" else spec.outputs
            return [{"id": p.name,
                     "type": getattr(p.type, "value", str(p.type))}
                    for p in ports]
    except Exception:
        pass
    return []


def _derive_graph_io(inner_graph: dict) -> tuple[list, list]:
    """AgDR-0039 slice 3 — derive a composite node's typed I/O from its
    inner graph's OPEN ports: an input port with no incoming wire is a
    composite input; an output port with no outgoing wire is a
    composite output. Port ids are bare when unique, node-qualified on
    collision."""
    nodes = inner_graph.get("nodes") or []
    wires = inner_graph.get("wires") or inner_graph.get("edges") or []
    wired_in: set = set()
    wired_out: set = set()
    for w in wires:
        if "from" in w and "to" in w:
            wired_out.add((w["from"][0], w["from"][1]))
            wired_in.add((w["to"][0], w["to"][1]))
        elif "src_node" in w:
            wired_out.add((w["src_node"], w["src_port"]))
            wired_in.add((w["dst_node"], w["dst_port"]))

    def _collect(side: str, wired: set) -> list:
        facade: list = []
        taken: set = set()
        for n in nodes:
            nid = n.get("id")
            if not nid:
                continue
            for p in _ports_of(n, side):
                if (nid, p["id"]) in wired:
                    continue
                port_id = p["id"]
                if port_id in taken:
                    port_id = f"{nid}.{p['id']}"
                taken.add(port_id)
                facade.append({"port": port_id, "inner_node": nid,
                               "inner_port": p["id"], "type": p["type"]})
        return facade

    return _collect("in", wired_in), _collect("out", wired_out)


def _graph_executor(impl: dict, output_names: list[str]):
    """impl.kind=graph (AgDR-0039) — a node whose logic IS a typed
    sub-graph. The whole point: logic is composed from modular elements
    (primitives, connector ops, other Capability Nodes), not a code blob.

    Runs through the existing subgraph machinery — a nested
    WorkflowRunner cooks the inner graph, outer inputs seed the inner
    entry ports, the inner exit ports map back out.

    impl keys:
      graph          {nodes, wires} — the inner logic graph
      inner_inputs   [{port, inner_node, inner_port, type}]  entry map
      inner_outputs  [{port, inner_node, inner_port, type}]  exit map
    """
    inner_graph = impl.get("graph") or impl.get("inner_graph") or {}
    inner_inputs = impl.get("inner_inputs")
    inner_outputs = impl.get("inner_outputs")
    # AgDR-0039 slice 3 — when the I/O maps are absent, auto-derive them
    # from the inner graph's open ports. Wire the inside; the outer
    # contract appears. One source of truth.
    if inner_inputs is None or inner_outputs is None:
        d_in, d_out = _derive_graph_io(inner_graph)
        if inner_inputs is None:
            inner_inputs = d_in
        if inner_outputs is None:
            inner_outputs = d_out
    sub_config = {
        "inner_graph":   inner_graph,
        "inner_inputs":  inner_inputs,
        "inner_outputs": inner_outputs,
    }

    def _exec(_config: dict, inputs: dict, ctx) -> dict:
        try:
            from .subgraph import _subgraph_executor
        except Exception as ex:
            return {"error": f"subgraph machinery unavailable: {ex}"}
        return _subgraph_executor(sub_config, inputs or {}, ctx)

    return _exec


def _resolve_impl(spec_dict: dict) -> dict:
    """Normalise any spec to its `impl` block (AgDR-0038).

    - an explicit `impl` dict carrying a `kind` → used as-is
    - a legacy bare top-level `code` key, no `impl` → treated as
      `{"kind": "python", "code": code}` (back-compat — every existing
      custom-node file keeps working)
    - neither → `{"kind": "passthrough"}`
    """
    impl = spec_dict.get("impl")
    if isinstance(impl, dict) and impl.get("kind"):
        return dict(impl)
    code = (spec_dict.get("code") or "").strip()
    if code:
        return {"kind": "python", "code": code}
    return {"kind": "passthrough"}


def _build_executor(spec_dict: dict, node_spec: NodeSpec):
    """Return a callable matching the registry's executor signature.

    Dispatches on `impl.kind` (AgDR-0038). A python body runs in the
    restricted sandbox (Delta 4 — closes the arbitrary-code-execution
    hole: the exec namespace gets a curated builtins dict, never the
    real `__builtins__`). Any failure to build a python executor falls
    back to passthrough so the node still renders + runs.
    """
    output_names = [p.name for p in node_spec.outputs]

    def _passthrough(_config: dict, inputs: dict, _ctx) -> dict:
        # Map each output to the input with the same name, falling back
        # to the first input value when there's no name match.
        first_val = next(iter(inputs.values()), None) if inputs else None
        out: dict = {}
        for name in output_names:
            out[name] = inputs.get(name, first_val)
        return out

    impl = _resolve_impl(spec_dict)
    kind = str(impl.get("kind") or "passthrough")

    if kind == "passthrough":
        return _passthrough

    if kind == "graph":
        return _graph_executor(impl, output_names)

    if kind == "connector":
        return _connector_executor(impl, output_names)

    if kind == "ai":
        return _ai_executor(impl, output_names)

    if kind != "python":
        def _unknown_kind(_config: dict, _inputs: dict, _ctx) -> dict:
            return {"error": f"unknown impl.kind '{kind}'"}
        return _unknown_kind

    # ── kind == "python" ────────────────────────────────────────────
    code = (impl.get("code") or "").strip()
    if not code:
        return _passthrough

    # safe_mode defaults TRUE — a minted node is sandboxed unless a
    # power user explicitly opts out. Same contract as code.python.
    safe = bool(impl.get("safe_mode", True))
    if safe and _has_forbidden_token(code):
        def _forbidden(_config: dict, _inputs: dict, _ctx) -> dict:
            return {"error": "code contains forbidden tokens — no "
                             "import / open / exec / eval / __ attrs "
                             "(set impl.safe_mode=false to opt out)"}
        return _forbidden

    # Delta 4 — the security fix. Restricted builtins for a sandboxed
    # node; an empty dict (Python injects the real builtins) only when
    # the power user has explicitly opted out.
    namespace: dict = {"__builtins__": _build_safe_builtins()} if safe else {}
    try:
        exec(code, namespace, namespace)   # noqa: S102 — sandboxed above
    except Exception:
        return _passthrough
    fn = namespace.get("execute")
    if not callable(fn):
        return _passthrough

    def _runner(config: dict, inputs: dict, ctx) -> dict:
        try:
            result = fn(config, inputs, ctx)
            return result if isinstance(result, dict) else {"value": result}
        except Exception as ex:
            return {"error": f"{type(ex).__name__}: {ex}"}

    return _runner


def write_spec(spec: dict) -> Path:
    """Persist a spec to disk. Returns the absolute path."""
    node_spec = _spec_from_dict(spec)   # validates shape
    path = custom_nodes_dir() / f"{node_spec.type}.json"
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def register_spec(spec: dict) -> NodeSpec:
    """Validate, register, and return the NodeSpec. Replaces any prior
    registration for the same type so an edit doesn't crash."""
    node_spec = _spec_from_dict(spec)
    # Replace existing registration (registry.register raises on dupes).
    _REGISTRY.pop(node_spec.type, None)
    register(node_spec, _build_executor(spec, node_spec))
    return node_spec


def delete_spec(type_id: str) -> bool:
    """AgDR-0028 — delete a custom node by type id.  Unregisters from
    the live registry AND removes the spec file on disk.  Returns True
    if a file was actually removed.

    Founder demand 2026-05-21: library actions must include "delete
    custom node" — leaving an orphan registered (but unfile'd) would
    mean the node returns on next launch."""
    if not type_id:
        return False
    _REGISTRY.pop(type_id, None)
    path = custom_nodes_dir() / f"{type_id}.json"
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception:
            return False
    return False


def load_all() -> list[str]:
    """Scan the custom_nodes dir and register every spec we find.

    Returns the list of type names that were registered (empty list on
    a fresh install). Bad specs are skipped silently — they shouldn't
    bring the whole bridge down."""
    out: list[str] = []
    for path in sorted(custom_nodes_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            node_spec = register_spec(data)
            out.append(node_spec.type)
        except Exception:
            continue
    return out


def list_specs() -> list[dict]:
    """Return every persisted custom-node spec dict (raw, for the UI's
    MY NODES section). Bad files skipped."""
    out: list[dict] = []
    for path in sorted(custom_nodes_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("type"):
                out.append(data)
        except Exception:
            continue
    return out
