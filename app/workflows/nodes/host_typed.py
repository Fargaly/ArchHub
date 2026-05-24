"""Typed host nodes — AgDR-0041 Property 1 (host swap).

Same wire works against any AEC host. Swap the `host` param to flip
between Revit / Rhino / 3ds Max / Blender. Underneath, every typed
node delegates to the existing `connectors.base.run_op` contract,
so the canvas semantics ("Import mesh", "Read walls", "Export
viewport") stay constant while the implementation moves.

Why typed wrappers when `connector.run` already exists:
  - canvas shows "Import mesh" not "connector + op:import_mesh"
  - port types are explicit (Mesh in / Path out) — drives the
    type-compatible swap suggestions (AgDR-0041 P2)
  - the `host` param's enum drives the swap-dropdown UI
  - one node mints all 4 host bindings (less repetition)

Op-id resolution is a simple `{host}.{typed_op}` mapping; the
connector module owns the actual implementation per host (some
hosts may not implement every op — `run_op` returns an honest
`status: error` and the runner propagates as `upstream_error`).
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


_HOSTS = ("revit", "rhino", "3dsmax", "blender")


def _resolve_op_id(host: str, typed_op: str) -> str:
    """Map typed-host primitive → fully-qualified connector op-id.

    Resolution is `{host}.{typed_op}`. Future special cases (e.g.
    different op name per host) get coded here, not in node specs."""
    host = (host or "").strip().lower()
    typed_op = (typed_op or "").strip().lower()
    if not host or not typed_op:
        return ""
    # 3dsmax connector module is registered under "max" today
    family = "max" if host == "3dsmax" else host
    return f"{family}.{typed_op}"


def _typed_host_executor(typed_op: str):
    """Closure factory — each typed node spec gets its own executor
    that knows its op shorthand. The `host` config selects target."""
    def _exec(config: dict, inputs: dict, _ctx) -> dict:
        cfg = config or {}
        host = str(cfg.get("host", "") or "").strip()
        if not host:
            return {"status": "error",
                    "error": f"{typed_op} needs a `host` config (one of "
                             f"{', '.join(_HOSTS)})"}
        op_id = _resolve_op_id(host, typed_op)
        if not op_id:
            return {"status": "error",
                    "error": f"could not resolve op_id for host={host!r} "
                             f"typed_op={typed_op!r}"}
        # Operation parameters = config minus selectors + wired inputs.
        params: dict[str, Any] = {k: v for k, v in cfg.items()
                                   if k not in ("host",)}
        if inputs:
            params.update(inputs)
        try:
            from connectors.base import run_op
        except Exception as ex:
            return {"status": "error",
                    "error": f"connectors unavailable: {ex}"}
        res = run_op(op_id, **params)
        if not getattr(res, "ok", False):
            return {"status": "error", "op_id": op_id,
                    "error": getattr(res, "error", "") or f"{op_id} failed"}
        return {"value": getattr(res, "value", None),
                "host": host, "op_id": op_id,
                "preview": getattr(res, "value_preview", "")}
    return _exec


# ── host.import_mesh ───────────────────────────────────────────────

register(NodeSpec(
    type="host.import_mesh",
    category="host",
    display_name="Import mesh",
    description=("Import a .glb / .obj / .ply mesh into the target host. "
                 "Same wire, different desktop app — swap the `host` "
                 "param to flip between Revit (as Mass family), Rhino "
                 "(as Block), 3ds Max (as Editable Mesh), or Blender "
                 "(as Mesh object)."),
    inputs=[
        Port(name="mesh", type=PortType.ANY, required=True),
    ],
    outputs=[
        Port(name="value", type=PortType.ANY),
    ],
    config_schema={
        "host": {"type": "string", "required": True,
                  "options": list(_HOSTS)},
        "name": {"type": "string"},
        "layer": {"type": "string"},
    },
    icon="⌖",
), _typed_host_executor("import_mesh"))


# ── host.read_walls ────────────────────────────────────────────────

register(NodeSpec(
    type="host.read_walls",
    category="host",
    display_name="Read walls",
    description=("Pull the active view's / current selection's walls "
                 "from the target host. Output is a typed list of wall "
                 "rows (id, family, type, length, area, level, etc)."),
    inputs=[],
    outputs=[
        Port(name="value", type=PortType.LIST),
    ],
    config_schema={
        "host":  {"type": "string", "required": True,
                   "options": list(_HOSTS)},
        "scope": {"type": "string", "default": "view",
                   "options": ["view", "selection", "all"]},
    },
    icon="▦",
), _typed_host_executor("read_walls"))


# ── host.export_viewport ───────────────────────────────────────────

register(NodeSpec(
    type="host.export_viewport",
    category="host",
    display_name="Export viewport",
    description=("Render the host's active view as an image + depth-map "
                 "pair. Output suitable for ControlNet Depth → SDXL "
                 "diffusion (AgDR-0041 Use case A)."),
    inputs=[],
    outputs=[
        Port(name="image", type=PortType.ANY),
        Port(name="depth", type=PortType.ANY),
    ],
    config_schema={
        "host":   {"type": "string", "required": True,
                    "options": list(_HOSTS)},
        "view":   {"type": "string", "default": "3D"},
        "width":  {"type": "integer", "default": 2048},
        "height": {"type": "integer", "default": 1536},
    },
    icon="◳",
), _typed_host_executor("export_viewport"))


# ── host.run_script ────────────────────────────────────────────────

register(NodeSpec(
    type="host.run_script",
    category="host",
    display_name="Run script",
    description=("Execute a snippet inside the host's scripting context "
                 "(Revit Python Shell, Rhino script, MaxScript, Blender "
                 "BPY). The op-id maps to `{host}.run_script` — host "
                 "decides which interpreter."),
    inputs=[
        Port(name="code",   type=PortType.STRING, required=True),
        Port(name="params", type=PortType.OBJECT),
    ],
    outputs=[
        Port(name="value", type=PortType.ANY),
    ],
    config_schema={
        "host": {"type": "string", "required": True,
                  "options": list(_HOSTS)},
    },
    icon="</>",
), _typed_host_executor("run_script"))
