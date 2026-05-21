"""AutoCAD connector — drives Autodesk AutoCAD through the broker.

Part of the broker-backed AEC connector cluster (Revit · AutoCAD · 3ds Max).
Subclasses the uniform `Connector` contract in `connectors/base.py`.

Architecture
------------
The connector runs in ArchHub's own Python process and routes every call
through `acad_broker`:

    ArchHub  ──>  acad_broker.forward(session, path, ...)  ──>  AcadMCP.dll
                  (HTTP localhost:48885..48899)            (in-AutoCAD listener)

`acad_broker.pick_session()` chooses which open AutoCAD instance to hit —
so an architect with two AutoCAD windows open can target one with the
optional `instance` op parameter (matched by session_id / pid / drawing
title — the broker's `prefer=` contract).

The endpoint surface — what the add-in actually exposes
-------------------------------------------------------
Inspecting `payload/sources/acad_mcp/AcadMCPApp.cs` (v0.2.0), the AcadMCP
listener exposes ONLY these routes:

    GET  /ping   → {"status":"ok","service":"acad-mcp","version":"0.2.0"}
    GET  /info   → active document name / path / acad version
    POST /exec   → run a C# script, body {"code": "...",
                  "transaction_name": "..."}

There is NO granular `/layers`, `/blocks`, `/entities` REST endpoint.
Every granular operation in this connector is therefore implemented by
POSTing a small C# script to `/exec`. The script uses the AutoCAD .NET
API (the `AcadScriptContext` exposes `Doc`, `Db`, `Ed`, and a `result`
slot), assigns a JSON-serialisable value to `result`, and the add-in
returns `{"status":"ok","result": <value>}`. This is the real,
documented contract — see `AcadMCPApp.RunCSharpScript` + `SerializeResult`.

ASSUMPTION (documented per the build mandate): the `/exec` C# scripting
route is the canonical way to read drawing data because the shipped DLL
exposes no resource-style endpoints. If a future AcadMCP DLL adds e.g.
`/layers`, the per-op definitions below can be repointed at a direct
path with no contract change. Until then `/exec` is correct and
code-complete.

Note on the /exec transaction
-----------------------------
`RunCSharpScript` already wraps the script in a `Transaction` + a
`DocumentLock`. Read scripts simply iterate the database; the connector
does not open its own nested transaction.

Honesty contract
----------------
This connector NEVER fabricates AutoCAD data. A dead broker, a dead
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
    import acad_broker
except Exception:  # pragma: no cover - broker always ships alongside
    acad_broker = None  # type: ignore


_TX_READ = "ArchHub read"
_TX_WRITE = "ArchHub action"


# ── broker plumbing ─────────────────────────────────────────────────
def _broker_offline_result(op_id: str) -> OpResult:
    """Uniform 'no live AutoCAD' failure. Honest — never fabricated data."""
    if acad_broker is None:
        return OpResult.fail(
            "AutoCAD broker module unavailable in this build.", op_id)
    try:
        running = acad_broker.is_any_alive()
    except Exception:
        running = False
    if running:
        return OpResult.fail(
            "AutoCAD is open but the ArchHub connector isn't responding. "
            "NETLOAD the ArchHub connector inside AutoCAD (or restart it).",
            op_id)
    return OpResult.fail(
        "AutoCAD is not running. Open AutoCAD and load the ArchHub "
        "connector.", op_id)


def _exec(op_id: str, code: str, *, instance: Optional[str] = None,
          tx_name: str = _TX_READ, timeout: float = 30.0) -> Any:
    """POST a C# script to one AutoCAD session's /exec route and return the
    unwrapped `result` value.

    Returns the parsed `result` payload (on success) or an `OpResult`
    (on any failure) — callers check `isinstance(x, OpResult)`. Never raises.
    """
    if acad_broker is None:
        return _broker_offline_result(op_id)
    try:
        session = acad_broker.pick_session(prefer=instance)
    except Exception as ex:
        return OpResult.fail(f"AutoCAD broker error: {ex}", op_id)
    if session is None:
        return _broker_offline_result(op_id)

    body = json.dumps({"code": code, "transaction_name": tx_name}).encode("utf-8")
    try:
        resp = acad_broker.forward(
            session, "/exec", body=body, method="POST", timeout=timeout)
    except Exception as ex:
        return OpResult.fail(f"AutoCAD broker call failed: {ex}", op_id)

    if not isinstance(resp, dict):
        return OpResult.fail(
            "AutoCAD add-in returned a non-JSON response.", op_id)
    if resp.get("status") == "error":
        return OpResult.fail(
            f"AutoCAD add-in error: {resp.get('error', 'unknown error')}",
            op_id)
    # Success shape from AcadMCPApp.RunCSharpScript:
    #   {"status":"ok","result": <serialised ctx.result>}
    return resp.get("result")


def _session_label(instance: Optional[str] = None) -> str:
    """Short 'drawing · pid' label for the chosen session, for previews."""
    if acad_broker is None:
        return ""
    try:
        s = acad_broker.pick_session(prefer=instance)
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
        for key in ("items", "rows", "entities", "values", "data"):
            v = value.get(key)
            if isinstance(v, list):
                return v
        return [value]
    return [value]


# ── instance param (shared) ─────────────────────────────────────────
def _instance_param() -> ParamSpec:
    return ParamSpec(
        id="instance", label="AutoCAD instance", type="text", default="",
        required=False,
        help="Target a specific open AutoCAD window when several are open "
             "(match by drawing name or pid). Empty = most-recent.",
    )


# ── READ operations ─────────────────────────────────────────────────
# Each READ runs a C# script via /exec. AcadScriptContext exposes
# Doc / Db / Ed; the script assigns list[dict] to `result`.

_CS_LAYERS = """
var rows = new List<Dictionary<string,object>>();
var lt = (LayerTable)Db.LayerTableId.GetObject(OpenMode.ForRead);
foreach (ObjectId id in lt) {
    var ltr = (LayerTableRecord)id.GetObject(OpenMode.ForRead);
    rows.Add(new Dictionary<string,object>{
        {"name", ltr.Name},
        {"is_off", ltr.IsOff},
        {"is_frozen", ltr.IsFrozen},
        {"is_locked", ltr.IsLocked},
        {"color", ltr.Color.ColorIndex}
    });
}
result = rows;
"""

_CS_BLOCKS = """
var rows = new List<Dictionary<string,object>>();
var bt = (BlockTable)Db.BlockTableId.GetObject(OpenMode.ForRead);
foreach (ObjectId id in bt) {
    var btr = (BlockTableRecord)id.GetObject(OpenMode.ForRead);
    if (btr.IsLayout) continue;
    rows.Add(new Dictionary<string,object>{
        {"name", btr.Name},
        {"is_anonymous", btr.IsAnonymous},
        {"is_dynamic", btr.IsDynamicBlock},
        {"has_attributes", btr.HasAttributeDefinitions}
    });
}
result = rows;
"""

_CS_ENTITIES = """
var rows = new List<Dictionary<string,object>>();
var bt = (BlockTable)Db.BlockTableId.GetObject(OpenMode.ForRead);
var ms = (BlockTableRecord)bt[BlockTableRecord.ModelSpace]
    .GetObject(OpenMode.ForRead);
foreach (ObjectId id in ms) {
    var ent = id.GetObject(OpenMode.ForRead) as Entity;
    if (ent == null) continue;
    rows.Add(new Dictionary<string,object>{
        {"handle", ent.Handle.ToString()},
        {"type", ent.GetType().Name},
        {"layer", ent.Layer}
    });
}
result = rows;
"""

_CS_LAYOUTS = """
var rows = new List<Dictionary<string,object>>();
var ld = (DBDictionary)Db.LayoutDictionaryId.GetObject(OpenMode.ForRead);
foreach (DBDictionaryEntry de in ld) {
    var lay = de.Value.GetObject(OpenMode.ForRead) as Layout;
    if (lay == null) continue;
    rows.Add(new Dictionary<string,object>{
        {"name", lay.LayoutName},
        {"tab_order", lay.TabOrder},
        {"is_model", lay.ModelType}
    });
}
result = rows;
"""

_CS_SELECTION = """
var rows = new List<Dictionary<string,object>>();
var psr = Ed.SelectImplied();
if (psr.Status == Autodesk.AutoCAD.EditorInput.PromptStatus.OK
    && psr.Value != null) {
    foreach (Autodesk.AutoCAD.EditorInput.SelectedObject so in psr.Value) {
        if (so == null) continue;
        var ent = so.ObjectId.GetObject(OpenMode.ForRead) as Entity;
        if (ent == null) continue;
        rows.Add(new Dictionary<string,object>{
            {"handle", ent.Handle.ToString()},
            {"type", ent.GetType().Name},
            {"layer", ent.Layer}
        });
    }
}
result = rows;
"""

_CS_XREFS = """
var rows = new List<Dictionary<string,object>>();
var bt = (BlockTable)Db.BlockTableId.GetObject(OpenMode.ForRead);
foreach (ObjectId id in bt) {
    var btr = (BlockTableRecord)id.GetObject(OpenMode.ForRead);
    if (!btr.IsFromExternalReference) continue;
    rows.Add(new Dictionary<string,object>{
        {"name", btr.Name},
        {"path", btr.PathName ?? ""},
        {"is_resolved", btr.IsResolved},
        {"is_unloaded", btr.IsUnloaded}
    });
}
result = rows;
"""


def _read_list(op_id: str, code: str, noun: str,
               instance: Optional[str] = None) -> OpResult:
    """Run a list-producing /exec read and wrap it in an OpResult."""
    res = _exec(op_id, code, instance=instance, tx_name=_TX_READ)
    if isinstance(res, OpResult):
        return res
    rows = _as_list(res)
    label = _session_label(instance)
    preview = f"{len(rows)} {noun}{'s' if len(rows) != 1 else ''}"
    if label:
        preview += f" · {label}"
    return OpResult(ok=True, value=rows, op_id=op_id, value_preview=preview)


def _list_layers(instance: str = "") -> OpResult:
    return _read_list(
        "autocad.list_layers", _CS_LAYERS, "layer", instance or None)


def _list_blocks(instance: str = "") -> OpResult:
    return _read_list(
        "autocad.list_blocks", _CS_BLOCKS, "block", instance or None)


def _list_entities(instance: str = "") -> OpResult:
    return _read_list(
        "autocad.list_entities", _CS_ENTITIES, "entity", instance or None)


def _list_layouts(instance: str = "") -> OpResult:
    return _read_list(
        "autocad.list_layouts", _CS_LAYOUTS, "layout", instance or None)


def _get_selection(instance: str = "") -> OpResult:
    return _read_list(
        "autocad.get_selection", _CS_SELECTION, "entity", instance or None)


def _list_xrefs(instance: str = "") -> OpResult:
    return _read_list(
        "autocad.list_xrefs", _CS_XREFS, "xref", instance or None)


# Founder bug 2026-05-15: "what do you see in AutoCAD" — the AI fabricated
# "no drawings open" while AutoCAD had 3 drawings open. There was no op to
# list the open documents. This is that op — verified live against the
# DocumentManager, returns every open .dwg + the active one.
_CS_DOCUMENTS = (
    "var dm = Autodesk.AutoCAD.ApplicationServices.Application"
    ".DocumentManager; "
    "var docs = new System.Collections.Generic.List<object>(); "
    "foreach (Autodesk.AutoCAD.ApplicationServices.Document d in dm) { "
    "docs.Add(new System.Collections.Generic.Dictionary<string,object>{ "
    "{\"name\", System.IO.Path.GetFileName(d.Name)}, "
    "{\"path\", d.Name}, "
    "{\"is_active\", d == dm.MdiActiveDocument} }); } "
    "result = new System.Collections.Generic.Dictionary<string,object>{ "
    "{\"count\", docs.Count}, "
    "{\"active\", dm.MdiActiveDocument != null ? "
    "System.IO.Path.GetFileName(dm.MdiActiveDocument.Name) : \"\"}, "
    "{\"documents\", docs} };"
)


def _list_documents(instance: str = "") -> OpResult:
    """Every open AutoCAD drawing + which one is active. Honest: if the
    broker is offline this returns OpResult.fail, never an empty 'no docs'."""
    res = _exec("autocad.list_documents", _CS_DOCUMENTS,
                instance=instance or None, tx_name=_TX_READ)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {}
    count = int(data.get("count", 0) or 0)
    active = str(data.get("active", "") or "")
    docs = data.get("documents") or []
    preview = (f"{count} drawing{'s' if count != 1 else ''} open"
               + (f" · active: {active}" if active else ""))
    return OpResult(ok=True, value=data, op_id="autocad.list_documents",
                     value_preview=preview)


# ── ACTION operations ───────────────────────────────────────────────
def _run_command(instance: str = "", command: str = "") -> OpResult:
    """Run an AutoCAD command-line command. DESTRUCTIVE — may mutate the
    drawing.

    The command string is sent to the active document. Whitespace is the
    AutoCAD command separator (e.g. "_ZOOM E " zoom-extents). A trailing
    space is appended if missing so the command actually fires.
    """
    op_id = "autocad.run_command"
    cmd = str(command or "").strip()
    if not cmd:
        return OpResult.fail("command is empty — nothing to run.", op_id)
    if not cmd.endswith(" "):
        cmd = cmd + " "
    # SendStringToExecute queues the command on the document's command
    # line; we report it as dispatched (AutoCAD runs it asynchronously).
    cmd_json = json.dumps(cmd)
    code = f"""
Doc.SendStringToExecute({cmd_json}, true, false, false);
result = new Dictionary<string,object>{{
    {{"dispatched", true}}, {{"command", {cmd_json}}} }};
"""
    res = _exec(op_id, code, instance=instance or None, tx_name=_TX_WRITE)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    return OpResult(
        ok=True, value=data, op_id=op_id,
        value_preview=f"dispatched: {cmd.strip()}")


def _set_layer(instance: str = "", layer: str = "",
               create: bool = True) -> OpResult:
    """Set the current (active) layer of the drawing. DESTRUCTIVE.

    `layer` — layer name to make current. `create` — create the layer if
    it does not exist.
    """
    op_id = "autocad.set_layer"
    name = str(layer or "").strip()
    if not name:
        return OpResult.fail("layer name is required.", op_id)
    name_json = json.dumps(name)
    create_cs = "true" if create else "false"
    code = f"""
var lt = (LayerTable)Db.LayerTableId.GetObject(OpenMode.ForWrite);
string want = {name_json};
ObjectId target = ObjectId.Null;
if (lt.Has(want)) {{
    target = lt[want];
}} else if ({create_cs}) {{
    var ltr = new LayerTableRecord();
    ltr.Name = want;
    target = lt.Add(ltr);
    Db.TransactionManager.TopTransaction.AddNewlyCreatedDBObject(ltr, true);
}}
if (target == ObjectId.Null) {{
    result = new Dictionary<string,object>{{
        {{"set", false}}, {{"error", "layer not found"}} }};
}} else {{
    Db.Clayer = target;
    result = new Dictionary<string,object>{{
        {{"set", true}}, {{"layer", want}} }};
}}
"""
    res = _exec(op_id, code, instance=instance or None, tx_name=_TX_WRITE)
    if isinstance(res, OpResult):
        return res
    data = res if isinstance(res, dict) else {"result": res}
    if data.get("set") is False:
        return OpResult.fail(
            f"Could not set layer: {data.get('error', 'unknown')}", op_id)
    return OpResult(
        ok=True, value=data, op_id=op_id,
        value_preview=f"current layer = {data.get('layer', name)}")


# ── connector ───────────────────────────────────────────────────────
class AutoCADConnector(Connector):
    """Autodesk AutoCAD — drives the host through the multi-session broker."""

    host = "autocad"
    display_name = "Autodesk AutoCAD"
    mechanism = "broker"

    def probe(self) -> dict:
        """Honest broker probe — mirrors host_detector._probe_broker.

        live         — an AutoCAD session's listener answered /ping.
        loaded_dead  — an AutoCAD process is running but no listener
                       answers (the ArchHub connector isn't NETLOADed).
        missing      — no AutoCAD running at all.
        """
        if acad_broker is None:
            return {"status": "missing",
                    "note": "AutoCAD broker module unavailable in this build.",
                    "detail": {}}
        try:
            count = acad_broker.sessions_count()
        except Exception as ex:
            return {"status": "missing",
                    "note": f"AutoCAD broker probe failed: {ex}", "detail": {}}
        if count >= 1:
            try:
                session = acad_broker.pick_session()
            except Exception:
                session = None
            ping: dict = {}
            if session is not None:
                try:
                    ping = acad_broker.forward(
                        session, "/ping", method="GET", timeout=2.0)
                except Exception:
                    ping = {}
            if isinstance(ping, dict) and ping.get("status") == "error":
                return {
                    "status": "loaded_dead",
                    "note": ("AutoCAD is open but the ArchHub connector "
                             "stopped responding — NETLOAD it inside "
                             "AutoCAD."),
                    "detail": {"sessions": count},
                }
            doc = ""
            try:
                doc = session.doc_title if session else ""
            except Exception:
                doc = ""
            return {
                "status": "live",
                "note": (f"AutoCAD broker live · {count} session"
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
            any_files = acad_broker.is_any_alive()
        except Exception:
            any_files = False
        if any_files:
            return {
                "status": "loaded_dead",
                "note": ("AutoCAD is open but the ArchHub connector isn't "
                         "responding — open AutoCAD and NETLOAD the ArchHub "
                         "connector."),
                "detail": {"sessions": 0},
            }
        return {
            "status": "missing",
            "note": "AutoCAD is not running. Open AutoCAD and load the "
                    "ArchHub connector.",
            "detail": {"sessions": 0},
        }

    def build_ops(self) -> list:
        inst = _instance_param()
        return [
            # ---- READS ----
            ConnectorOp(
                op_id="autocad.list_documents", host="autocad", kind="read",
                label="List open drawings",
                description=("Every .dwg currently open in AutoCAD plus "
                             "which one is active. Use this to answer "
                             "'what is open / what do you see'."),
                inputs=[inst], output_type="any", destructive=False,
                fn=_list_documents,
            ),
            ConnectorOp(
                op_id="autocad.list_layers", host="autocad", kind="read",
                label="List layers",
                description="Every layer with on/frozen/locked state.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_layers,
            ),
            ConnectorOp(
                op_id="autocad.list_blocks", host="autocad", kind="read",
                label="List blocks",
                description="Every block definition in the drawing.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_blocks,
            ),
            ConnectorOp(
                op_id="autocad.list_entities", host="autocad", kind="read",
                label="List entities",
                description="Every entity in model space with layer/type.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_entities,
            ),
            ConnectorOp(
                op_id="autocad.list_layouts", host="autocad", kind="read",
                label="List layouts",
                description="Every paper-space layout in the drawing.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_layouts,
            ),
            ConnectorOp(
                op_id="autocad.get_selection", host="autocad", kind="read",
                label="Get selection",
                description="Entities currently selected in AutoCAD.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_get_selection,
            ),
            ConnectorOp(
                op_id="autocad.list_xrefs", host="autocad", kind="read",
                label="List xrefs",
                description="Every external reference with resolve state.",
                inputs=[inst], output_type="list", destructive=False,
                fn=_list_xrefs,
            ),
            # ---- ACTIONS ----
            ConnectorOp(
                op_id="autocad.run_command", host="autocad", kind="action",
                label="Run command",
                description="Run an AutoCAD command-line command.",
                inputs=[
                    inst,
                    ParamSpec(id="command", label="Command", type="text",
                              default="", required=True,
                              help="AutoCAD command string, e.g. '_ZOOM E'."),
                ],
                output_type="any", destructive=True,
                fn=_run_command,
            ),
            ConnectorOp(
                op_id="autocad.set_layer", host="autocad", kind="action",
                label="Set current layer",
                description="Make a layer the current drawing layer.",
                inputs=[
                    inst,
                    ParamSpec(id="layer", label="Layer name", type="text",
                              default="", required=True,
                              help="Layer to make current."),
                    ParamSpec(id="create", label="Create if missing",
                              type="bool", default=True,
                              help="Create the layer when it doesn't exist."),
                ],
                output_type="any", destructive=True,
                fn=_set_layer,
            ),
            # ── M5 parity (AgDR-0017 send-pattern, AutoCAD symmetric)
            # send is kind=read because it does NOT mutate AutoCAD —
            # it ships an upstream value through SpeckleWire.
            ConnectorOp(
                op_id="autocad.send_to_speckle", host="autocad",
                kind="read",
                label="Send to Speckle",
                description="Wrap upstream value + write through "
                            "SpeckleWire. Optional push to a Speckle "
                            "Server. Does not mutate AutoCAD.",
                inputs=[
                    inst,
                    ParamSpec(id="value", label="Value", type="any",
                              default=None,
                              help="The upstream value to send. List, "
                                   "dict or scalar — shape preserved."),
                    ParamSpec(id="model_name", label="Model name",
                              type="text", default="autocad",
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
                fn=_acad_send_to_speckle_op,
            ),
        ]


def _acad_send_to_speckle_op(instance: str = "", value: Any = None,
                               model_name: str = "autocad",
                               server_push: bool = False,
                               server_url: str = "") -> OpResult:
    """`autocad.send_to_speckle` thin wrapper. Reuses the canonical
    `send_to_speckle` in `revit_speckle_ops` with `source_host='autocad'`
    so the Speckle commit carries `archhub_source: 'autocad'`."""
    from connectors.revit_speckle_ops import send_to_speckle
    result = send_to_speckle(
        value=value, model_name=model_name,
        server_push=bool(server_push), server_url=server_url,
        source_host="autocad")
    if result.get("status") == "error":
        return OpResult.fail(result.get("error", ""),
                              "autocad.send_to_speckle")
    return OpResult(ok=True, value=result,
                     op_id="autocad.send_to_speckle",
                     value_preview=f"{result.get('url', '')} "
                                   f"({result.get('item_count', 0)} items)")


register(AutoCADConnector())
