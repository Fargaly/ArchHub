"""3ds Max connector — drives Autodesk 3ds Max through the broker.

Part of the broker-backed AEC connector cluster (Revit · AutoCAD · 3ds Max).
Subclasses the uniform `Connector` contract in `connectors/base.py`.

STATUS — no host-side add-in is DEPLOYED yet
--------------------------------------------
Unlike Revit and AutoCAD, 3ds Max has **no `payload/max/` deployment
directory** — the in-Max listener is not shipped to users yet. The
add-in SOURCE does exist at `payload/sources/max_mcp/max_mcp_startup.py`
(a Python startup script that boots an HTTP server inside 3ds Max), but
until that script is deployed into a user's 3ds Max startup folder, no
listener will ever answer and `probe()` will honestly report `missing`.

This connector is built anyway, in full, so the moment the add-in ships
every operation works with zero connector changes. It calls
`max_broker.forward()` exactly like the Revit / AutoCAD connectors —
the only difference is the add-in it targets does not exist on disk yet.

Architecture
------------
The connector runs in ArchHub's own Python process and routes every call
through `max_broker`:

    ArchHub  ──>  max_broker.forward(session, path, ...)  ──>  MaxMCP startup
                  (HTTP localhost:48886..48899)           (in-Max HTTP server)

`max_broker` mounts every path under the `/max-mcp` prefix automatically
(see `max_broker.Session.url`), so this connector passes bare paths like
`/ping` and `/exec`.

`max_broker.pick_session()` chooses which open 3ds Max instance to hit —
so an architect with two Max windows open can target one with the
optional `instance` op parameter (matched by session_id / pid / scene
title — the broker's `prefer=` contract).

The endpoint surface — what the add-in source exposes
-----------------------------------------------------
Inspecting `payload/sources/max_mcp/max_mcp_startup.py` (v0.2.0), the
MaxMCP server exposes these routes (relative to the /max-mcp prefix):

    GET  /ping            → {"status":"ok","service":"max-mcp","version":...}
    GET  /info            → max version / scene file / object count
    POST /exec            → run Python in-Max, body {"code": "..."}
    POST /exec_maxscript  → run MAXScript, body {"script": "..."}

There is NO granular `/objects`, `/cameras`, `/lights` REST endpoint.
Every granular READ in this connector is implemented by POSTing a small
Python snippet to `/exec`. The snippet uses `pymxs` (exposed as `rt` in
the exec namespace) and assigns a JSON-serialisable value to the
`result` variable; the add-in returns `{"status":"ok","result": <value>}`.

ASSUMPTION (documented per the build mandate): the `/exec` Python route
is the canonical way to read scene data because the add-in source
exposes no resource-style endpoints. If a future MaxMCP build adds e.g.
`/objects`, the per-op definitions below can be repointed at a direct
path with no contract change.

Honesty contract
----------------
This connector NEVER fabricates 3ds Max data. No add-in deployed, a dead
add-in, or a timeout all surface as `OpResult(ok=False, error=...)`.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    register,
)

try:  # broker import is best-effort — a missing broker must not crash import
    import max_broker
except Exception:  # pragma: no cover - broker always ships alongside
    max_broker = None  # type: ignore


# ── broker plumbing ─────────────────────────────────────────────────
def _broker_offline_result(op_id: str) -> OpResult:
    """Uniform 'no live 3ds Max' failure. Honest — never fabricated data."""
    if max_broker is None:
        return OpResult.fail(
            "3ds Max broker module unavailable in this build.", op_id)
    try:
        running = max_broker.is_any_alive()
    except Exception:
        running = False
    if running:
        return OpResult.fail(
            "3ds Max is open but the ArchHub connector isn't responding. "
            "Install/run the ArchHub MaxMCP startup script inside 3ds Max.",
            op_id)
    return OpResult.fail(
        "3ds Max is not running, or the ArchHub MaxMCP add-in has not "
        "been installed yet. Open 3ds Max with the ArchHub connector "
        "loaded.", op_id)


def _exec(op_id: str, path: str, payload: dict, *,
          instance: Optional[str] = None, timeout: float = 30.0) -> Any:
    """POST a JSON body to one 3ds Max session route and return the
    unwrapped `result` value.

    `path` is one of "/exec" (Python) or "/exec_maxscript" (MAXScript) —
    the broker prefixes /max-mcp automatically.

    Returns the parsed `result` payload (on success) or an `OpResult`
    (on any failure) — callers check `isinstance(x, OpResult)`. Never raises.
    """
    if max_broker is None:
        return _broker_offline_result(op_id)
    try:
        session = max_broker.pick_session(prefer=instance)
    except Exception as ex:
        return OpResult.fail(f"3ds Max broker error: {ex}", op_id)
    if session is None:
        return _broker_offline_result(op_id)

    body = json.dumps(payload).encode("utf-8")
    try:
        resp = max_broker.forward(
            session, path, body=body, method="POST", timeout=timeout)
    except Exception as ex:
        return OpResult.fail(f"3ds Max broker call failed: {ex}", op_id)

    if not isinstance(resp, dict):
        return OpResult.fail(
            "3ds Max add-in returned a non-JSON response.", op_id)
    if resp.get("status") == "error":
        err = resp.get("error", "unknown error")
        return OpResult.fail(f"3ds Max add-in error: {err}", op_id)
    # Success shape from max_mcp_startup._run_kind:
    #   {"status":"ok","result": <value>}
    return resp.get("result")


def _exec_python(op_id: str, code: str, *, instance: Optional[str] = None,
                 timeout: float = 30.0) -> Any:
    """Run an in-Max Python snippet via /exec."""
    return _exec(op_id, "/exec", {"code": code},
                 instance=instance, timeout=timeout)


def _session_label(instance: Optional[str] = None) -> str:
    """Short 'scene · pid' label for the chosen session, for previews."""
    if max_broker is None:
        return ""
    try:
        s = max_broker.pick_session(prefer=instance)
    except Exception:
        return ""
    if s is None:
        return ""
    return s.doc_title or s.session_id or f"pid {s.pid}"


def _as_list(value: Any) -> list:
    """Coerce an /exec result into list[dict]/list. Honest about shape."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "rows", "objects", "values", "data"):
            v = value.get(key)
            if isinstance(v, list):
                return v
        return [value]
    return [value]


# ── instance param (shared) ─────────────────────────────────────────
def _instance_param() -> ParamSpec:
    return ParamSpec(
        id="instance", label="3ds Max instance", type="text", default="",
        required=False,
        help="Target a specific open 3ds Max window when several are open "
             "(match by scene name or pid). Empty = most-recent.",
    )


# ── READ operations ─────────────────────────────────────────────────
# Each READ runs a Python snippet via /exec. `rt` is pymxs.runtime in the
# add-in's exec namespace; the snippet assigns to `result`.

_PY_SCENE_INFO = """
result = {
    "max_version": str(rt.maxVersion()[0]),
    "scene_file": str(rt.maxFilePath) + str(rt.maxFileName),
    "object_count": int(rt.objects.count),
    "current_time": float(rt.currentTime),
    "animation_range_end": float(rt.animationRange.end),
}
"""

_PY_OBJECTS = """
rows = []
for o in rt.objects:
    rows.append({
        "name": str(o.name),
        "class": str(rt.classOf(o)),
        "is_hidden": bool(o.isHidden),
    })
result = rows
"""

_PY_CAMERAS = """
rows = []
for o in rt.cameras:
    rows.append({
        "name": str(o.name),
        "class": str(rt.classOf(o)),
    })
result = rows
"""

_PY_LIGHTS = """
rows = []
for o in rt.lights:
    rows.append({
        "name": str(o.name),
        "class": str(rt.classOf(o)),
    })
result = rows
"""

_PY_MATERIALS = """
rows = []
seen = set()
for o in rt.objects:
    m = getattr(o, "material", None)
    if m is None:
        continue
    nm = str(m.name)
    if nm in seen:
        continue
    seen.add(nm)
    rows.append({
        "name": nm,
        "class": str(rt.classOf(m)),
    })
result = rows
"""

_PY_SELECTION = """
rows = []
for o in rt.selection:
    rows.append({
        "name": str(o.name),
        "class": str(rt.classOf(o)),
    })
result = rows
"""


def _read_list(op_id: str, code: str, noun: str,
               instance: Optional[str] = None) -> OpResult:
    """Run a list-producing /exec read and wrap it in an OpResult."""
    res = _exec_python(op_id, code, instance=instance)
    if isinstance(res, OpResult):
        return res
    rows = _as_list(res)
    label = _session_label(instance)
    preview = f"{len(rows)} {noun}{'s' if len(rows) != 1 else ''}"
    if label:
        preview += f" · {label}"
    return OpResult(ok=True, value=rows, op_id=op_id, value_preview=preview)


def _scene_info(instance: str = "") -> OpResult:
    """Scene-level facts: version, file, object count, timeline."""
    op_id = "max.scene_info"
    res = _exec_python(op_id, _PY_SCENE_INFO, instance=instance or None)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    label = _session_label(instance or None)
    n = data.get("object_count", "?")
    preview = f"{n} objects"
    if label:
        preview += f" · {label}"
    return OpResult(ok=True, value=data, op_id=op_id, value_preview=preview)


def _list_objects(instance: str = "") -> OpResult:
    return _read_list(
        "max.list_objects", _PY_OBJECTS, "object", instance or None)


def _list_cameras(instance: str = "") -> OpResult:
    return _read_list(
        "max.list_cameras", _PY_CAMERAS, "camera", instance or None)


def _list_lights(instance: str = "") -> OpResult:
    return _read_list(
        "max.list_lights", _PY_LIGHTS, "light", instance or None)


def _list_materials(instance: str = "") -> OpResult:
    return _read_list(
        "max.list_materials", _PY_MATERIALS, "material", instance or None)


def _get_selection(instance: str = "") -> OpResult:
    return _read_list(
        "max.get_selection", _PY_SELECTION, "object", instance or None)


# ── ACTION operations ───────────────────────────────────────────────
def _run_maxscript(instance: str = "", script: str = "") -> OpResult:
    """Run a MAXScript string in 3ds Max. DESTRUCTIVE — may mutate the scene.

    The script is sent to the dedicated /exec_maxscript route; whatever
    the MAXScript expression evaluates to is returned as `result`.
    """
    op_id = "max.run_maxscript"
    src = str(script or "").strip()
    if not src:
        return OpResult.fail("script is empty — nothing to run.", op_id)
    res = _exec(op_id, "/exec_maxscript", {"script": src},
                instance=instance or None)
    if isinstance(res, OpResult):
        return res
    # MAXScript result can be any JSON value (or a repr string).
    if isinstance(res, (list, dict)):
        preview = (f"{len(res)} item{'s' if len(res) != 1 else ''}"
                   if isinstance(res, list)
                   else f"{len(res)} field{'s' if len(res) != 1 else ''}")
    else:
        s = "—" if res is None else str(res)
        preview = s if len(s) <= 80 else s[:80] + "…"
    return OpResult(ok=True, value=res, op_id=op_id, value_preview=preview)


# ── connector ───────────────────────────────────────────────────────
class MaxConnector(Connector):
    """Autodesk 3ds Max — drives the host through the multi-session broker.

    No host-side add-in is deployed yet (no `payload/max/`); until the
    MaxMCP startup script ships, `probe()` honestly reports `missing`.
    """

    host = "max"
    display_name = "Autodesk 3ds Max"
    mechanism = "broker"

    def probe(self) -> dict:
        """Honest broker probe — mirrors host_detector._probe_broker.

        live         — a 3ds Max session's listener answered /ping.
        loaded_dead  — a 3ds Max process is running but no listener
                       answers (the ArchHub MaxMCP add-in isn't loaded).
        missing      — no 3ds Max running, or no add-in deployed at all.

        Note: because no `payload/max/` add-in is shipped yet, the common
        real-world result here is `missing` even when 3ds Max is open —
        that is correct and honest, not a bug.
        """
        if max_broker is None:
            return {"status": "missing",
                    "note": "3ds Max broker module unavailable in this build.",
                    "detail": {}}
        try:
            count = max_broker.sessions_count()
        except Exception as ex:
            return {"status": "missing",
                    "note": f"3ds Max broker probe failed: {ex}", "detail": {}}
        if count >= 1:
            try:
                session = max_broker.pick_session()
            except Exception:
                session = None
            ping: dict = {}
            if session is not None:
                try:
                    ping = max_broker.forward(
                        session, "/ping", method="GET", timeout=2.0)
                except Exception:
                    ping = {}
            if isinstance(ping, dict) and ping.get("status") == "error":
                return {
                    "status": "loaded_dead",
                    "note": ("3ds Max is open but the ArchHub connector "
                             "stopped responding — reload the MaxMCP "
                             "startup script."),
                    "detail": {"sessions": count},
                }
            doc = ""
            try:
                doc = session.doc_title if session else ""
            except Exception:
                doc = ""
            return {
                "status": "live",
                "note": (f"3ds Max broker live · {count} session"
                         f"{'s' if count != 1 else ''}"
                         + (f" · {doc}" if doc else "")),
                "detail": {
                    "sessions": count,
                    "version": str(ping.get("version", "")
                                    if isinstance(ping, dict) else ""),
                    "doc_title": doc,
                },
            }
        try:
            any_files = max_broker.is_any_alive()
        except Exception:
            any_files = False
        if any_files:
            return {
                "status": "loaded_dead",
                "note": ("3ds Max is open but the ArchHub connector isn't "
                         "responding — install/run the ArchHub MaxMCP "
                         "startup script."),
                "detail": {"sessions": 0},
            }
        return {
            "status": "missing",
            "note": ("3ds Max is not running, or the ArchHub MaxMCP add-in "
                     "is not installed yet. Open 3ds Max with the ArchHub "
                     "connector loaded."),
            "detail": {"sessions": 0},
        }

    def build_ops(self) -> list:
        inst = _instance_param()
        return [
            # ---- READS ----
            ConnectorOp(
                op_id="max.scene_info", host="max", kind="read",
                label="Scene info",
                description="Version, scene file, object count, timeline.",
                inputs=[inst], output_type="any", destructive=False,
                fn=_scene_info,
            ),
            ConnectorOp(
                op_id="max.list_objects", host="max", kind="read",
                label="List objects",
                description="Every scene object with class and visibility.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_objects,
            ),
            ConnectorOp(
                op_id="max.list_cameras", host="max", kind="read",
                label="List cameras",
                description="Every camera in the scene.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_cameras,
            ),
            ConnectorOp(
                op_id="max.list_lights", host="max", kind="read",
                label="List lights",
                description="Every light in the scene.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_lights,
            ),
            ConnectorOp(
                op_id="max.list_materials", host="max", kind="read",
                label="List materials",
                description="Every material applied to a scene object.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_materials,
            ),
            ConnectorOp(
                op_id="max.get_selection", host="max", kind="read",
                label="Get selection",
                description="Objects currently selected in 3ds Max.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_get_selection,
            ),
            # ---- ACTIONS ----
            ConnectorOp(
                op_id="max.run_maxscript", host="max", kind="action",
                label="Run MAXScript",
                description="Run a MAXScript string in 3ds Max.",
                inputs=[
                    inst,
                    ParamSpec(id="script", label="MAXScript", type="text",
                              default="", required=True,
                              help="MAXScript source to evaluate."),
                ],
                output_type="any", destructive=True,
                fn=_run_maxscript,
            ),
            # ── M5 parity (AgDR-0017 send-pattern, 3ds Max symmetric)
            ConnectorOp(
                op_id="max.send_to_speckle", host="max",
                kind="read",
                label="Send to Speckle",
                description="Wrap upstream value + write through "
                            "SpeckleWire. Optional push to a Speckle "
                            "Server. Does not mutate 3ds Max.",
                inputs=[
                    inst,
                    ParamSpec(id="value", label="Value", type="any",
                              default=None,
                              help="The upstream value to send. List, "
                                   "dict or scalar — shape preserved."),
                    ParamSpec(id="model_name", label="Model name",
                              type="text", default="max",
                              help="The model name stamped on the "
                                   "Speckle commit."),
                    ParamSpec(id="server_push", label="Push to server",
                              type="boolean", default=False,
                              help="If true, also push to the configured "
                                   "Speckle Server."),
                    ParamSpec(id="server_url", label="Server URL",
                              type="text", default="",
                              help="Speckle Server URL "
                                   "(http://localhost:3000 for local)."),
                ],
                output_type="any", destructive=False,
                fn=_max_send_to_speckle_op,
            ),
        ]


def _max_send_to_speckle_op(instance: str = "", value: Any = None,
                              model_name: str = "max",
                              server_push: bool = False,
                              server_url: str = "") -> OpResult:
    """`max.send_to_speckle` thin wrapper. Reuses the canonical
    `send_to_speckle` in `revit_speckle_ops` with
    `source_host='max'`."""
    from connectors.revit_speckle_ops import send_to_speckle
    result = send_to_speckle(
        value=value, model_name=model_name,
        server_push=bool(server_push), server_url=server_url,
        source_host="max")
    if result.get("status") == "error":
        return OpResult.fail(result.get("error", ""),
                              "max.send_to_speckle")
    return OpResult(ok=True, value=result,
                     op_id="max.send_to_speckle",
                     value_preview=f"{result.get('url', '')} "
                                   f"({result.get('item_count', 0)} items)")


register(MaxConnector())
