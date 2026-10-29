"""AutoCAD verbs carried out through the one signed AutoCAD broker (/exec).

Layer and linetype verb groups folded from U-C4N Autocad-MCP (MIT), upstream
58a05ddfc34a9832c626e82cd88ecdce8e16a62a: backends/contracts/layers.py and
linetypes.py (verbs), backends/com_backend.py (behaviour), security.py
sanitize_symbol_name and backends/base.py normalize_lineweight (argument rules),
tests/test_symbol_names.py (refusals, carried into
02.TESTS/tests_replica/test_host_verbs_folded.py).
Copyright (c) U-C4N; MIT licence text in
03.TOOLS/packaging/windows/licenses/U-C4N-Autocad-MCP-MIT.txt.
Modified: no COM, no SendCommand macro, no second server. Each verb is a C#
script run by bridges/sources/acad_mcp inside its document lock and
transaction; names reach the script only as C# string literals, after the DXF
symbol-name rule refused anything that was never a legal table name.
"""
from __future__ import annotations

import json
from typing import Mapping

from .clean_revit_adapter import RevitUnreachable, broker_sessions, _call


class AutoCADUnreachable(RevitUnreachable):
    """No AutoCAD broker answered, or it refused the verb."""


# security.py _FORBIDDEN_SYMBOL_CHARS / _MAX_SYMBOL_NAME (DXF symbol-table rule).
_FORBIDDEN_SYMBOL_CHARS = set('<>/\\":;?*|,=`')
_MAX_SYMBOL_NAME = 255
# AutoCAD LineWeight enum values (hundredths of a mm) plus ByLayer/ByBlock/Default.
_LINEWEIGHTS = {-3, -2, -1, 0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70,
                80, 90, 100, 106, 120, 140, 158, 200, 211}
# Layers AutoCAD itself owns; deleting them is refused before the host is asked.
_PROTECTED_LAYERS = {"0", "defpoints"}


def sanitize_symbol_name(name: object, *, kind: str = "symbol") -> str:
    """The name if DXF allows it in a symbol table, else refuse without echoing it."""
    candidate = str(name or "").strip()
    if not candidate:
        raise ValueError("%s name rejected: empty." % kind)
    if len(candidate) > _MAX_SYMBOL_NAME:
        raise ValueError("%s name rejected: longer than %d characters." % (kind, _MAX_SYMBOL_NAME))
    offenders = sorted({c for c in candidate if c in _FORBIDDEN_SYMBOL_CHARS or ord(c) < 32})
    if offenders:
        raise ValueError("%s name rejected: DXF symbol-table names cannot contain %s."
                         % (kind, ", ".join(repr(c) for c in offenders)))
    return candidate


def normalize_lineweight(value: object) -> int:
    """Hundredths of a mm; (0, 2.05] is millimetres (no ISO 128 value is above 2.0)."""
    if isinstance(value, bool):
        raise ValueError("lineweight must be a number")
    number = float(value)
    if number < 0:
        result = int(round(number))
    elif number == 0:
        result = 0
    elif number <= 2.05:
        result = int(round(number * 100.0))
    else:
        result = int(round(number))
    if result not in _LINEWEIGHTS:
        raise ValueError("lineweight %s is not an AutoCAD lineweight" % value)
    return result


def _color(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("color must be an AutoCAD colour index 1-255")
    try:
        index = int(value)
    except (TypeError, ValueError):
        raise ValueError("color must be an AutoCAD colour index 1-255") from None
    if not 1 <= index <= 255 or index != float(value):
        raise ValueError("color must be an AutoCAD colour index 1-255")
    return index


def _cs(value: object) -> str:
    return json.dumps("" if value is None else str(value))


_PRELUDE = r"""
var db = Doc.Database;
var tr = db.TransactionManager.TopTransaction;
var layers = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
var linetypes = (LinetypeTable)tr.GetObject(db.LinetypeTableId, OpenMode.ForRead);
Func<string,LayerTableRecord> layerNamed = gn => {
    if (!layers.Has(gn)) throw new System.Exception("layer not found: " + gn);
    return (LayerTableRecord)tr.GetObject(layers[gn], OpenMode.ForWrite);
};
Func<string,ObjectId> linetypeNamed = gn => {
    if (!linetypes.Has(gn)) {
        db.LoadLineTypeFile(gn, db.Measurement == MeasurementValue.Metric ? "acadiso.lin" : "acad.lin");
        linetypes = (LinetypeTable)tr.GetObject(db.LinetypeTableId, OpenMode.ForRead);
    }
    if (!linetypes.Has(gn)) throw new System.Exception("linetype not found: " + gn);
    return linetypes[gn];
};
Func<LayerTableRecord,Dictionary<string,object>> layerInfo = gr => new Dictionary<string,object>{
    {"name", gr.Name}, {"color", (int)gr.Color.ColorIndex},
    {"linetype", ((LinetypeTableRecord)tr.GetObject(gr.LinetypeObjectId, OpenMode.ForRead)).Name},
    {"lineweight", (int)gr.LineWeight}, {"frozen", gr.IsFrozen}, {"locked", gr.IsLocked},
    {"visible", !gr.IsOff}, {"current", db.Clayer == gr.ObjectId}
};
"""

# verb -> (flag in the answer, value set): layer_freeze .. layer_show in com_backend.
_FLAG_VERBS = {
    "autocad.layer_freeze": ("frozen", True),
    "autocad.layer_thaw": ("frozen", False),
    "autocad.layer_lock": ("locked", True),
    "autocad.layer_unlock": ("locked", False),
    "autocad.layer_hide": ("visible", False),
    "autocad.layer_show": ("visible", True),
}

_SCRIPTS = {
    "autocad.layer_list": r"""
var rows = new List<Dictionary<string,object>>();
foreach (ObjectId id in layers) rows.Add(layerInfo((LayerTableRecord)tr.GetObject(id, OpenMode.ForRead)));
result = rows;
""",
    "autocad.linetype_list": r"""
var rows = new List<string>();
foreach (ObjectId id in linetypes) rows.Add(((LinetypeTableRecord)tr.GetObject(id, OpenMode.ForRead)).Name);
result = rows;
""",
}

_READ_OPS = frozenset({"autocad.layer_list", "autocad.linetype_list"})
AUTOCAD_WRITE_OPS = frozenset({
    "autocad.layer_create", "autocad.layer_delete", "autocad.layer_set_current",
    "autocad.layer_modify", "autocad.linetype_load", *_FLAG_VERBS,
})
AUTOCAD_VERBS = _READ_OPS | AUTOCAD_WRITE_OPS


def _script_for(op_id: str, arguments: Mapping[str, object]) -> str | None:
    if op_id in _READ_OPS:
        return _PRELUDE + _SCRIPTS[op_id]
    if op_id not in AUTOCAD_WRITE_OPS:
        return None
    if op_id == "autocad.linetype_load":
        name = sanitize_symbol_name(arguments.get("name"), kind="linetype")
        file = str(arguments.get("file") or "").strip()
        # A bare .lin name on AutoCAD's support path; a path would reach the disk unchecked.
        if file and (not file.lower().endswith(".lin") or any(c in file for c in "\\/:")
                     or file != sanitize_symbol_name(file, kind="linetype file")):
            raise ValueError("linetype file must be a .lin file name on AutoCAD's support path")
        return _PRELUDE + "string name = %s;\nstring file = %s;\n" % (_cs(name), _cs(file)) + r"""
if (linetypes.Has(name)) { result = new Dictionary<string,object>{ {"ok", true}, {"name", name}, {"already_loaded", true} }; }
else {
    var lin = file.Length > 0 ? file : (db.Measurement == MeasurementValue.Metric ? "acadiso.lin" : "acad.lin");
    db.LoadLineTypeFile(name, lin);
    linetypes = (LinetypeTable)tr.GetObject(db.LinetypeTableId, OpenMode.ForRead);
    if (!linetypes.Has(name)) throw new System.Exception("linetype " + name + " was not found in " + lin);
    result = new Dictionary<string,object>{ {"ok", true}, {"name", name}, {"file", lin} };
}
"""
    name = sanitize_symbol_name(arguments.get("name"), kind="layer")
    head = "string name = %s;\n" % _cs(name)
    if op_id in _FLAG_VERBS:
        flag, value = _FLAG_VERBS[op_id]
        return _PRELUDE + head + "string flag = %s;\nbool value = %s;\n" % (
            _cs(flag), "true" if value else "false") + r"""
var r = layerNamed(name);
if (flag == "frozen" && value && db.Clayer == r.ObjectId) throw new System.Exception("the current layer cannot be frozen");
if (flag == "frozen") r.IsFrozen = value;
if (flag == "locked") r.IsLocked = value;
if (flag == "visible") r.IsOff = !value;
result = new Dictionary<string,object>{ {"ok", true}, {"layer", r.Name}, {flag, value} };
"""
    if op_id == "autocad.layer_set_current":
        return _PRELUDE + head + r"""
var r = layerNamed(name);
if (r.IsFrozen) throw new System.Exception("a frozen layer cannot be made current");
db.Clayer = r.ObjectId;
result = new Dictionary<string,object>{ {"ok", true}, {"current_layer", r.Name} };
"""
    if op_id == "autocad.layer_delete":
        if name.lower() in _PROTECTED_LAYERS:
            raise ValueError("layer %s belongs to AutoCAD and cannot be deleted" % name)
        return _PRELUDE + head + r"""
var r = layerNamed(name);
if (db.Clayer == r.ObjectId) throw new System.Exception("the current layer cannot be deleted");
var ids = new ObjectIdCollection(new[] { r.ObjectId });
db.Purge(ids);
if (ids.Count == 0) throw new System.Exception("layer " + name + " is in use and was not deleted");
r.Erase();
result = new Dictionary<string,object>{ {"ok", true}, {"deleted", name} };
"""
    create = op_id == "autocad.layer_create"
    color = arguments.get("color", 7 if create else None)
    linetype = arguments.get("linetype", "Continuous" if create else None)
    lineweight = arguments.get("lineweight", -3 if create else None)
    sets = head + "bool create = %s;\n" % ("true" if create else "false")
    sets += "int color = %d;\n" % (_color(color) if color not in (None, "") else 0)
    sets += "string linetype = %s;\n" % _cs(
        sanitize_symbol_name(linetype, kind="linetype") if linetype not in (None, "") else "")
    sets += "int lineweight = %d;\nbool setWeight = %s;\n" % (
        (normalize_lineweight(lineweight), "true") if lineweight not in (None, "") else (0, "false"))
    return _PRELUDE + sets + r"""
LayerTableRecord r;
if (create && !layers.Has(name)) {
    r = new LayerTableRecord { Name = name };
    layers.UpgradeOpen();
    layers.Add(r);
    tr.AddNewlyCreatedDBObject(r, true);
} else r = layerNamed(name);
if (color > 0) r.Color = Autodesk.AutoCAD.Colors.Color.FromColorIndex(Autodesk.AutoCAD.Colors.ColorMethod.ByAci, (short)color);
if (linetype.Length > 0) r.LinetypeObjectId = linetypeNamed(linetype);
if (setWeight) r.LineWeight = (LineWeight)lineweight;
result = layerInfo(r);
"""


def _require_write_grant(op_id: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
    from . import nodeslib_v2_engines as nodeslib
    from .clean_revit_adapter import _effect_arguments
    grant = nodeslib._require_grant(
        arguments, operation=op_id, scope="autocad.write",
        input_digest=nodeslib._digest_payload(_effect_arguments(arguments)),
    )
    # C3: the same pending-write decision every Revit write passes (enforce.inspect_pending).
    from .domains.selfext import before_write_hooks
    annotations = before_write_hooks(arguments.get("mods_store"), op_id, arguments)
    if annotations:
        grant = dict(grant)
        grant["mods_before_write"] = annotations
    return grant


def invoke(op_id: str, arguments: Mapping[str, object]) -> dict:
    """Carry out one declared AutoCAD verb against the one live AutoCAD broker."""
    if op_id not in AUTOCAD_VERBS:
        raise AutoCADUnreachable("this adapter does not carry out %s" % op_id)
    write_grant = _require_write_grant(op_id, arguments) if op_id in AUTOCAD_WRITE_OPS else None
    script = _script_for(op_id, arguments)  # refuses bad arguments before any host is asked
    sessions = broker_sessions("acad")
    wanted = str(arguments.get("instance") or "").strip()
    if wanted:
        sessions = [s for s in sessions if wanted in (str(s.get("pid")), str(s.get("port")))]
    if not sessions:
        raise AutoCADUnreachable("no AutoCAD session answers%s. Open AutoCAD with the ArchHub add-in loaded."
                                 % (" as %s" % wanted if wanted else ""))
    if len(sessions) > 1:
        raise AutoCADUnreachable("%d AutoCAD sessions answer (ports %s); name one as instance"
                                 % (len(sessions), ", ".join(str(s["port"]) for s in sessions)))
    session = sessions[0]
    answer = _call(session["port"], "/exec", {
        "code": script, "transaction_name": "ArchHub write" if write_grant else "ArchHub read"})
    if answer.get("status") != "ok":
        raise AutoCADUnreachable("AutoCAD refused %s: %s" % (op_id, answer.get("error")))
    result = {"port": session["port"], "pid": session.get("pid"), "document": session.get("document"),
              "acad_version": session.get("acad_version"), "result": answer.get("result")}
    if write_grant:
        from . import nodeslib_v2_engines as nodeslib
        result["ok"] = True
        result["receipt"] = {"operation": op_id, "port": session["port"],
                             "grant_digest": write_grant.get("digest"),
                             "result_digest": nodeslib._digest_payload(answer.get("result"))}
    return result


__all__ = ["AUTOCAD_VERBS", "AUTOCAD_WRITE_OPS", "AutoCADUnreachable", "invoke",
           "normalize_lineweight", "sanitize_symbol_name"]
