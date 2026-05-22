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
  • connector / ai   — reserved for AgDR-0038 slice 2; until then they
                       return an honest typed error, never a fake result.

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


# AgDR-0038 — `impl.kind`s reserved for slice 2 (typed connector-op
# wrappers + LLM-backed executors). Declared-but-not-executable until
# then; slice 1 surfaces them as an honest typed error.
_SLICE2_KINDS = ("connector", "ai")


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

    if kind in _SLICE2_KINDS:
        # Declared but not yet executable. Surface it honestly rather
        # than fabricate a result (connector-honesty mandate).
        def _slice2_pending(_config: dict, _inputs: dict, _ctx) -> dict:
            return {"error": f"impl.kind '{kind}' is not available until "
                             f"AgDR-0038 slice 2"}
        return _slice2_pending

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
