"""Pass-2 engines for the F19 must-have node gaps.

These are ordinary pipeline effect engines: pure data/file nodes do their work
locally, while BIM and Workshop/Brain nodes cross only the existing narrow
adapters. Courts replace those adapters with fakes; production code never
pretends to have a live host.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import html
import json
import math
import operator
import time
import zipfile
from collections.abc import Mapping
from pathlib import Path

_REVIT_BROKER = None
_WORKSHOP_DELEGATE = None
_WRITE_GRANT_VERIFIER = None
_FILE_WRITE_BROKER = None


def _text(params: Mapping[str, object], name: str, default: str = "") -> str:
    value = params.get(name)
    if value in (None, ""):
        return default
    return str(value)


def _wired(feeds: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in feeds and feeds[name] is not None:
            return feeds[name]
    return None


def _rows(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, Mapping):
        return [dict(value)]
    text = str(value).strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except ValueError:
            return [text]
        return parsed if isinstance(parsed, list) else [parsed]
    return [text]


def _field(row: object, name: str) -> object:
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def _local_output_path(path: object, *, label: str) -> Path:
    text = str(path or "").strip()
    if not text:
        raise ValueError("set %s" % label)
    upper = text.upper()
    if text.startswith(("\\\\", "//")) or upper.startswith(("\\\\?\\UNC", "SMB:", "FILE:")):
        raise ValueError("%s must be a local file, not a network share" % label)
    return Path(text)


def _revit(operation: str, arguments: Mapping[str, object]) -> dict:
    if _REVIT_BROKER is not None:
        return _REVIT_BROKER(operation, dict(arguments))
    from .clean_revit_adapter import invoke
    return invoke(operation, arguments)


def _digest_payload(payload: Mapping[str, object]) -> str:
    data = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _verified_write_grant(
    params: Mapping[str, object], *, operation: str, scope: str,
    input_digest: str, path: Path | None = None,
) -> Mapping[str, object]:
    grant = params.get("grant") or params.get("approval") or params.get("permit")
    if not isinstance(grant, Mapping):
        raise ValueError("host write requires an approval grant")
    if grant.get("revoked") or grant.get("invalid") or grant.get("current") is False:
        raise ValueError("approval grant is not current")
    expires_at = grant.get("expires_at")
    if expires_at is not None and float(expires_at) <= time.time():
        raise ValueError("approval grant expired")
    approved_scope = grant.get("approval_scope")
    if approved_scope is None and scope != "file.write":
        approved_scope = grant.get("scope")
    if approved_scope and approved_scope != scope:
        raise ValueError("approval grant scope does not cover %s" % scope)
    operations = grant.get("operations")
    if isinstance(operations, str):
        operations = [operations]
    elif operations is None and grant.get("operation"):
        operations = [grant.get("operation")]
    if operation != "*" and operations is not None and operation not in operations:
        raise ValueError("approval grant does not cover %s" % operation)
    if not grant.get("digest"):
        raise ValueError("approval grant is not signed")
    required = ("caller", "session", "work", "input_digest", "action")
    if path is not None:
        required = required + ("path",)
    if any(not grant.get(name) for name in required):
        raise ValueError("approval grant missing verified binding")
    if str(grant.get("action")) not in (operation, "*"):
        raise ValueError("approval grant action does not cover %s" % operation)
    if str(grant.get("input_digest")) != input_digest:
        raise ValueError("approval grant input digest does not match")
    if path is not None and Path(str(grant.get("path"))).resolve() != path.resolve():
        raise ValueError("approval grant path does not match")
    if _WRITE_GRANT_VERIFIER is None:
        raise ValueError("verified approval grant verifier is not bound")
    answer = _WRITE_GRANT_VERIFIER({
        "grant": dict(grant),
        "operation": operation,
        "scope": scope,
        "path": str(path) if path is not None else "",
        "input_digest": input_digest,
    })
    if not isinstance(answer, Mapping) or answer.get("ok") is not True:
        raise ValueError(str((answer or {}).get("error") if isinstance(answer, Mapping) else "approval grant refused"))
    return dict(grant)


def _require_grant(
    params: Mapping[str, object], *, operation: str, scope: str,
    input_digest: str,
) -> Mapping[str, object]:
    return _verified_write_grant(params, operation=operation, scope=scope, input_digest=input_digest)


def _params_with_wired_grant(params: Mapping[str, object], feeds: Mapping[str, object]) -> dict:
    held = dict(params)
    grant = _wired(feeds, "grant", "approval", "permit")
    if grant is not None and "grant" not in held:
        held["grant"] = grant
    return held


def _confirmed_write(answer: Mapping[str, object], operation: str) -> Mapping[str, object]:
    if answer.get("ok") is not True:
        raise ValueError(str(answer.get("error") or "%s was not confirmed by the broker" % operation))
    if not answer.get("receipt"):
        raise ValueError("%s needs a confirmed broker receipt" % operation)
    return answer


def _require_file_grant(
    params: Mapping[str, object], *, operation: str, input_digest: str,
) -> Mapping[str, object]:
    grant = params.get("file_grant") or params.get("grant") or params.get("permit")
    if not isinstance(grant, Mapping):
        raise ValueError("file write requires a governed file grant")
    expires_at = grant.get("expires_at")
    if expires_at is not None and float(expires_at) <= time.time():
        raise ValueError("file grant expired")
    operations = grant.get("operations")
    if isinstance(operations, str):
        operations = [operations]
    elif operations is None and grant.get("operation"):
        operations = [grant.get("operation")]
    if operations is not None and operation not in operations:
        raise ValueError("file grant does not cover %s" % operation)
    root = Path(str(grant.get("path") or "")).resolve()
    requested = params.get("path")
    if requested not in (None, "") and Path(str(requested)).resolve() != root:
        raise ValueError("file write path is governed by the grant")
    wanted = root
    scope = str(grant.get("scope") or "exact")
    if scope == "exact":
        allowed = wanted == root
    elif scope in ("descendants", "tree", "under"):
        allowed = wanted == root or root in wanted.parents
    else:
        raise ValueError("file grant scope is invalid")
    if not allowed:
        raise ValueError("file grant scope does not cover %s" % wanted)
    return _verified_write_grant(
        {"grant": grant}, operation=operation, scope="file.write",
        input_digest=input_digest, path=wanted,
    )


def revit_elements_of_category(params: Mapping[str, object], feeds: Mapping[str, object]):
    category = _text(params, "category")
    if not category:
        raise ValueError("set category")
    answer = _revit("revit.elements_of_category", {
        "category": category,
        "scope": _text(params, "scope", "document"),
        "session": _text(params, "session"),
    })
    rows = answer.get("result") or answer.get("elements") or []
    return {"elements": rows, "out": rows}, "%d %s element(s)" % (len(rows), category)


def revit_get_parameter(params: Mapping[str, object], feeds: Mapping[str, object]):
    name = (
        _text(params, "parameter")
        or _text(params, "name")
        or str(_wired(feeds, "parameter") or "").strip()
        or str(_wired(feeds, "name") or "").strip()
    )
    if not name:
        raise ValueError("set parameter name")
    elements = _rows(_wired(feeds, "elements", "els", "in"))
    answer = _revit("revit.get_parameter", {
        "elements": elements, "name": name, "session": _text(params, "session"),
    })
    values = answer.get("result") or answer.get("values") or []
    return {"values": values, "out": values}, "%d value(s) for %s" % (len(values), name)


def revit_set_parameter(params: Mapping[str, object], feeds: Mapping[str, object]):
    params = _params_with_wired_grant(params, feeds)
    operation = "revit.set_parameter_by_name"
    name = (
        _text(params, "parameter")
        or _text(params, "name")
        or str(_wired(feeds, "parameter") or "").strip()
        or str(_wired(feeds, "name") or "").strip()
    )
    if not name:
        raise ValueError("set parameter name")
    value = params.get("value")
    if value in (None, ""):
        value = _wired(feeds, "value")
    elements = _rows(_wired(feeds, "elements", "els", "in"))
    request = {
        "elements": elements, "name": name, "value": value,
    }
    grant = _require_grant(
        params, operation=operation, scope="revit.write",
        input_digest=_digest_payload(request),
    )
    answer = _confirmed_write(_revit(operation, {"grant": grant, "mods_store": params.get("mods_store"), **request}), operation)
    rows = answer.get("result") or answer.get("elements") or []
    return {"elements": rows, "out": rows}, "set %s on %d element(s)" % (name, len(rows))


def revit_create_sheets(params: Mapping[str, object], feeds: Mapping[str, object]):
    params = _params_with_wired_grant(params, feeds)
    operation = "revit.create_sheets"
    rows = _rows(_wired(feeds, "rows", "in"))
    request = {"rows": rows}
    grant = _require_grant(
        params, operation=operation, scope="revit.write",
        input_digest=_digest_payload(request),
    )
    answer = _confirmed_write(_revit(operation, {"grant": grant, "mods_store": params.get("mods_store"), **request}), operation)
    made = answer.get("result") or answer.get("sheets") or []
    return {"sheets": made, "out": made}, "created %d sheet(s)" % len(made)


def revit_renumber_rename(params: Mapping[str, object], feeds: Mapping[str, object]):
    params = _params_with_wired_grant(params, feeds)
    operation = "revit.renumber_rename"
    elements = _rows(_wired(feeds, "elements", "els", "in"))
    number_pattern = (
        _text(params, "number_format")
        or _text(params, "number_pattern")
        or str(_wired(feeds, "number_format") or "").strip()
        or str(_wired(feeds, "number_pattern") or "").strip()
    )
    name_pattern = (
        _text(params, "name_format")
        or _text(params, "name_pattern")
        or str(_wired(feeds, "name_format") or "").strip()
        or str(_wired(feeds, "name_pattern") or "").strip()
    )
    request = {
        "elements": elements, "number_pattern": number_pattern,
        "name_pattern": name_pattern,
    }
    grant = _require_grant(
        params, operation=operation, scope="revit.write",
        input_digest=_digest_payload(request),
    )
    answer = _confirmed_write(_revit(operation, {"grant": grant, "mods_store": params.get("mods_store"), **request}), operation)
    rows = answer.get("result") or answer.get("elements") or []
    return {"elements": rows, "out": rows}, "renumbered/renamed %d element(s)" % len(rows)


def revit_override_color(params: Mapping[str, object], feeds: Mapping[str, object]):
    operation = "revit.override_color_in_view"
    elements = _rows(_wired(feeds, "els", "in", "elements"))
    colour = _text(params, "colour") or _text(params, "color")
    if not colour:
        raise ValueError("set colour")
    request = {
        "elements": elements, "colour": colour, "view": _text(params, "view", "active"),
        "session": _text(params, "session"),
    }
    grant = _require_grant(
        params, operation=operation, scope="revit.write",
        input_digest=_digest_payload(request),
    )
    answer = _confirmed_write(_revit(operation, {"grant": grant, "mods_store": params.get("mods_store"), **request}), operation)
    rows = answer.get("result") or answer.get("elements") or []
    return {"els": rows, "out": rows}, "overrode %d element(s) in %s" % (len(rows), _text(params, "view", "active"))


def _columns(rows: list) -> list[str]:
    found: list[str] = []
    for row in rows:
        if isinstance(row, Mapping):
            for key in row:
                if str(key) not in found:
                    found.append(str(key))
    return found or ["value"]


def _write_csv(rows: list, path: Path) -> None:
    columns = _columns(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_field(row, col) if isinstance(row, Mapping) else row for col in columns])


def _write_xlsx(rows: list, path: Path) -> None:
    columns = _columns(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_rows = [columns]
    for row in rows:
        sheet_rows.append([_field(row, col) if isinstance(row, Mapping) else row for col in columns])
    cells = []
    for r_index, row in enumerate(sheet_rows, 1):
        cell_xml = []
        for c_index, value in enumerate(row, 1):
            col = ""
            n = c_index
            while n:
                n, rem = divmod(n - 1, 26)
                col = chr(65 + rem) + col
            ref = "%s%d" % (col, r_index)
            cell_xml.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (
                ref, html.escape("" if value is None else str(value))))
        cells.append('<row r="%d">%s</row>' % (r_index, "".join(cell_xml)))
    sheet = '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % "".join(cells)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def write_table_file(params: Mapping[str, object], feeds: Mapping[str, object]):
    params = _params_with_wired_grant(params, feeds)
    rows = _rows(_wired(feeds, "rows", "in"))
    grant = params.get("file_grant") or params.get("grant") or params.get("permit")
    if not isinstance(grant, Mapping):
        raise ValueError("file write requires a governed file grant")
    path = _local_output_path(grant.get("path"), label="grant path")
    kind = (_text(params, "format") or path.suffix.lstrip(".") or "xlsx").casefold()
    if kind not in ("csv", "xlsx"):
        raise ValueError("format must be xlsx or csv")
    request = {"rows": rows, "path": str(path), "format": kind}
    grant = _require_file_grant(
        {**params, "grant": grant, "path": params.get("path")},
        operation="write_file",
        input_digest=_digest_payload(request),
    )
    if _FILE_WRITE_BROKER is None:
        raise ValueError("governed file writer is not bound")
    answer = _confirmed_write(_FILE_WRITE_BROKER({
        "operation": "write_file", "path": str(path), "format": kind,
        "rows": rows, "grant": grant, "input_digest": _digest_payload(request),
    }), "write_file")
    return {"file": str(path), "out": str(path)}, "%s written (%d row(s))" % (path.name, len(rows))


def schedule_to_excel(params: Mapping[str, object], feeds: Mapping[str, object]):
    schedule = _text(params, "schedule")
    if not schedule:
        raise ValueError("set schedule")
    grant = params.get("file_grant") or params.get("grant") or params.get("permit")
    if not isinstance(grant, Mapping):
        raise ValueError("file write requires a governed file grant")
    path = _local_output_path(grant.get("path"), label="grant path")
    request = {"schedule": schedule, "path": str(path), "format": "xlsx", "session": _text(params, "session")}
    _require_file_grant(
        {**params, "grant": grant, "path": params.get("path")},
        operation="write_file",
        input_digest=_digest_payload(request),
    )
    if _FILE_WRITE_BROKER is None:
        raise ValueError("governed file writer is not bound")
    answer = _revit("revit.schedule_rows", {"schedule": schedule, "session": _text(params, "session")})
    rows = answer.get("result") or answer.get("rows") or []
    return write_table_file({"path": str(path), "format": "xlsx", "grant": params.get("grant")}, {"rows": rows})


def revit_export(params: Mapping[str, object], feeds: Mapping[str, object]):
    fmt = _text(params, "format", "dwg").casefold()
    if fmt not in ("dwg", "ifc"):
        raise ValueError("format must be dwg or ifc")
    path = _local_output_path(params.get("path"), label="path")
    operation = "revit.export_%s" % fmt
    request = {
        "views": _rows(_wired(feeds, "views", "in")) or _rows(params.get("views")),
        "path": str(path),
        "setup": _text(params, "setup"), "session": _text(params, "session"),
    }
    grant = _require_grant(
        params, operation=operation, scope="revit.write",
        input_digest=_digest_payload(request),
    )
    answer = _confirmed_write(_revit(operation, {"grant": grant, "mods_store": params.get("mods_store"), **request}), operation)
    files = answer.get("result") or answer.get("files") or []
    return {"files": files, "out": files}, "exported %d %s file(s)" % (len(files), fmt.upper())


def text_ops(params: Mapping[str, object], feeds: Mapping[str, object]):
    op = _text(params, "operation", "replace").casefold()
    value = str(_wired(feeds, "text", "in", "value") if _wired(feeds, "text", "in", "value") is not None else params.get("text") or "")
    if op == "replace":
        out = value.replace(_text(params, "pattern"), _text(params, "replacement"))
    elif op == "split":
        out = value.split(_text(params, "separator", ","))
    elif op == "join":
        out = _text(params, "separator", ",").join(str(item) for item in _rows(_wired(feeds, "items", "in") or value))
    elif op == "format":
        out = _text(params, "template", "{value}").format(value=value, **{str(k): v for k, v in params.items()})
    elif op == "pad":
        out = value.rjust(int(params.get("width") or 0), _text(params, "fill", " ")[:1] or " ")
    else:
        raise ValueError("operation must be replace, split, join, format or pad")
    return {"text": out, "out": out}, "%s text" % op


_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "min": min, "max": max, "round": round, "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil}


def _compute(node: ast.AST, names: Mapping[str, object]) -> object:
    if isinstance(node, ast.Expression):
        return _compute(node.body, names)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("expression constants must be numbers")
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ValueError("unknown name %s" % node.id)
        return names[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_compute(node.left, names), _compute(node.right, names))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_compute(node.operand, names))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_compute(arg, names) for arg in node.args])
    raise ValueError("expression contains unsupported syntax")


def expression(params: Mapping[str, object], feeds: Mapping[str, object]):
    expr = _text(params, "expr") or _text(params, "expression")
    if not expr:
        raise ValueError("set expression")
    names = {str(k): v for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    names.update({str(k): v for k, v in feeds.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
    for key in ("a", "b", "c", "x", "y"):
        try:
            names.setdefault(key, float(params[key]))
        except (KeyError, TypeError, ValueError):
            pass
    tree = ast.parse(expr, mode="eval")
    value = _compute(tree, names)
    return {"value": value, "out": value}, "%s = %s" % (expr, value)


def series(params: Mapping[str, object], feeds: Mapping[str, object]):
    start = float(params.get("start") or 0)
    step = float(params.get("step") or 1)
    count = int(params.get("count") or 10)
    if count < 0 or count > 100000:
        raise ValueError("count must be between 0 and 100000")
    values = [start + step * i for i in range(count)]
    return {"values": values, "out": values}, "%d value(s)" % len(values)


def slider(params: Mapping[str, object], feeds: Mapping[str, object]):
    low = float(params.get("min") or 0)
    high = float(params.get("max") or 1)
    step = float(params.get("step") or 0.1)
    value = float(params.get("value") if params.get("value") not in (None, "") else low)
    if high < low or step <= 0:
        raise ValueError("slider range is invalid")
    value = max(low, min(high, value))
    return {"value": value, "out": value}, "slider %s" % value


def approval_gate(params: Mapping[str, object], feeds: Mapping[str, object]):
    params = _params_with_wired_grant(params, feeds)
    value = _wired(feeds, "in", "value")
    operation = _text(params, "operation", "*")
    scope = _text(params, "scope", "revit.write")
    grant = params.get("grant") or params.get("approval") or params.get("permit")
    if not isinstance(grant, Mapping) or not grant.get("digest"):
        raise ValueError("approval required")
    operations = grant.get("operations")
    if isinstance(operations, str):
        operations = [operations]
    elif operations is None and grant.get("operation"):
        operations = [grant.get("operation")]
    if operation != "*" and operations is not None and operation not in operations:
        raise ValueError("approval grant does not cover %s" % operation)
    approved_scope = grant.get("approval_scope") or grant.get("scope")
    if approved_scope and approved_scope != scope:
        raise ValueError("approval grant scope does not cover %s" % scope)
    return {"out": value, "grant": dict(grant)}, "awaiting approved grant"


def remember(params: Mapping[str, object], feeds: Mapping[str, object]):
    text = _text(params, "text") or str(_wired(feeds, "in", "value") or "")
    if not text:
        raise ValueError("nothing to remember")
    from .pipeline_engines import _brain_call
    answer = _brain_call("brain.remember", {"text": text, "source": _text(params, "source", "nodeslib")})
    return {"out": answer}, "remembered"


def delegate_and_await(params: Mapping[str, object], feeds: Mapping[str, object]):
    if _WORKSHOP_DELEGATE is None:
        raise ValueError("Workshop delegate adapter is not bound")
    task = _text(params, "task") or str(_wired(feeds, "in", "value") or "")
    if not task:
        raise ValueError("set task")
    answer = _WORKSHOP_DELEGATE({"agent": _text(params, "agent"), "task": task, "timeout_s": params.get("timeout_s")})
    return {"out": answer}, "delegate answered"


def dry_run_diff(params: Mapping[str, object], feeds: Mapping[str, object]):
    before = _rows(_wired(feeds, "before", "in"))
    after = _rows(_wired(feeds, "after", "proposed")) or _rows(params.get("changes"))
    diff = {"before_count": len(before), "after_count": len(after), "changes": after}
    return {"diff": diff, "out": diff}, "%d proposed change(s), not applied" % len(after)


def host_health(params: Mapping[str, object], feeds: Mapping[str, object]):
    from .pipeline_engines import probe_connectors
    wanted = _text(params, "host").casefold()
    rows = [row for row in probe_connectors() if not wanted or wanted in (row.get("id", "") + " " + row.get("name", "")).casefold()]
    return {"out": rows}, "%d host row(s)" % len(rows)


def evidence_attach(params: Mapping[str, object], feeds: Mapping[str, object]):
    files = _rows(_wired(feeds, "files", "in") or params.get("files") or params.get("path"))
    records = []
    for item in files:
        path = Path(str(item))
        if not path.is_file():
            raise ValueError("evidence file does not exist: %s" % path)
        records.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
    return {"evidence": records, "out": records}, "%d evidence file(s)" % len(records)


ENGINES = {
    "revit.elements_of_category": revit_elements_of_category,
    "revit.get_parameter": revit_get_parameter,
    "revit.set_parameter_by_name": revit_set_parameter,
    "revit.create_sheets": revit_create_sheets,
    "revit.renumber_rename": revit_renumber_rename,
    "text.ops": text_ops,
    "math.expression": expression,
    "math.series": series,
    "input.slider": slider,
    "approval.gate": approval_gate,
    "brain.remember": remember,
    "archhub.dry_run_diff": dry_run_diff,
    "host.health": host_health,
    "evidence.attach": evidence_attach,
}
