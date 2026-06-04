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

Op-id resolution maps each typed primitive to the REAL op-id that
host's connector implements (see `_OP_ALIASES`). The connectors name
their ops with host-native verbs (`list_walls`, `run_maxscript`, …),
so a naive `{host}.{typed_op}` would point at ops that don't exist —
the contract break this module's resolver fixes. Every resolved op-id
is a real `ConnectorOp`; with the host offline the connector returns an
honest "<host> is not running" — never an "unknown op" lie or a
fabricated value.
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


_HOSTS = ("revit", "rhino", "3dsmax", "blender")


# Per-host op-alias table — typed primitive → the REAL connector op verb
# that host implements. Where a host's connector already names the op
# identically (e.g. import_mesh / export_viewport after AgDR-0041 P1),
# the entry is the identity; where the host uses a native verb it maps
# to that verb. `read_walls` only has a literal walls concept in Revit;
# the other hosts have no wall primitive, so the typed "pull the host's
# elements" intent routes to each host's generic object/element list —
# keeping the host-swap promise real (same wire, native elements back).
_OP_ALIASES: dict[str, dict[str, str]] = {
    "revit": {
        "import_mesh":      "import_mesh",
        "read_walls":       "list_walls",
        "export_viewport":  "export_viewport",
        "run_script":       "run_script",
    },
    "rhino": {
        "import_mesh":      "import_mesh",
        "read_walls":       "list_objects",
        "export_viewport":  "export_viewport",
        "run_script":       "run_script",
    },
    "max": {
        "import_mesh":      "import_mesh",
        "read_walls":       "list_objects",
        "export_viewport":  "export_viewport",
        "run_script":       "run_maxscript",
    },
    "blender": {
        "import_mesh":      "import_mesh",
        "read_walls":       "list_objects",
        "export_viewport":  "export_viewport",
        "run_script":       "run_script",
    },
}


def _resolve_op_id(host: str, typed_op: str) -> str:
    """Map a typed-host primitive → the fully-qualified connector op-id
    that the chosen host actually implements.

    Looks the typed op up in `_OP_ALIASES[family]`; falls back to the
    identity verb if a host has no override for that op (so a future
    typed op that every connector names identically still resolves
    without touching this table). Returns "" for empty inputs."""
    host = (host or "").strip().lower()
    typed_op = (typed_op or "").strip().lower()
    if not host or not typed_op:
        return ""
    # 3dsmax connector module is registered under "max" today.
    family = "max" if host == "3dsmax" else host
    verb = _OP_ALIASES.get(family, {}).get(typed_op, typed_op)
    return f"{family}.{verb}"


# Typed input/config port → native connector param renames, applied
# before the param-id filter. The typed node uses canvas-friendly names
# ("code" for a script body); some connector ops name the same param
# natively ("script" on max.run_maxscript). Keyed by (family, typed_op).
_PARAM_RENAMES: dict[tuple[str, str], dict[str, str]] = {
    ("max", "run_script"): {"code": "script"},
}


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
        # Apply typed→native param renames for this host (e.g. the
        # `code` script body becomes `script` for max.run_maxscript).
        family = "max" if host.lower() == "3dsmax" else host.lower()
        renames = _PARAM_RENAMES.get((family, typed_op))
        if renames:
            for src, dst in renames.items():
                if src in params:
                    params[dst] = params.pop(src)
        try:
            from connectors.base import run_op, get as _get_connector
        except Exception as ex:
            return {"status": "error",
                    "error": f"connectors unavailable: {ex}"}
        # Filter params to the ones the resolved op actually declares, so
        # a typed-node config key the op doesn't take (e.g. read_walls'
        # `scope`, or width/height the host ignores) can never blow up a
        # live cook with an unexpected-keyword TypeError. When the
        # connector or op can't be resolved (host module absent), we leave
        # params untouched and let run_op surface the honest error.
        try:
            connector = _get_connector(family)
            op = connector.op(op_id) if connector is not None else None
            if op is not None and op.inputs:
                allowed = {p.id for p in op.inputs}
                params = {k: v for k, v in params.items() if k in allowed}
        except Exception:
            pass
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
                 "diffusion (AgDR-0041 Use case A). `view` may be passed "
                 "as an input port (dynamic — wire it from upstream) OR "
                 "as a config default."),
    inputs=[
        # `view` is wireable — dynamic view selection from an upstream
        # node — but defaults to config.view when no wire is connected.
        # The typed executor merges config + inputs so a wired value
        # overrides the config default at cook time.
        Port(name="view", type=PortType.STRING),
    ],
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
