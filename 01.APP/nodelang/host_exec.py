"""Two generic nodes: run code in a program, or call one connector action.

Both extend the runners that already exist (host brokers, rhino.exec,
blender.exec, max.exec, office.read, notion_mcp). No second broker.
Every run is admitted by hook_decision.decide before anything is sent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from . import hook_decision

PROGRAMS = (
    ("revit", "Revit"),
    ("acad", "AutoCAD"),
    ("acad-core", "AutoCAD (background)"),
    ("rhino", "Rhino"),
    ("blender", "Blender"),
    ("max", "3ds Max"),
    ("office", "Office"),
)
CONNECTORS = (("notion", "Notion"),)

_CONTROL = frozenset({
    "host", "code", "transaction_name", "transaction", "document",
    "element_limit", "sheet_limit", "min_free_bytes", "max_hidden_core",
    "log_sentinel", "load_module", "isolate_user", "isolate_folder",
    "connector", "action", "args",
})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONSOLE_NAMES = (
    r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
)
_ADMITTED = ("allow", "organize")
_REACHABLE = {"Connected", "Installed", "Ready to connect"}


class ConnectorUnreachable(ValueError):
    """The connector did not return its own tool list."""


def programs():
    return [{"id": key, "label": label} for key, label in PROGRAMS]


def connectors():
    return [{"id": key, "label": label} for key, label in CONNECTORS]


def _whole(value, label):
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError("Set %s." % label)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a whole number." % label) from exc


def _preview_text(args):
    if isinstance(args, str):
        return args
    if isinstance(args, Mapping):
        for key in ("text", "body", "content", "message", "query"):
            held = args.get(key)
            if isinstance(held, str) and held:
                return held
        return json.dumps(dict(args), ensure_ascii=False)
    return "" if args is None else str(args)


def _held(decision, preview=""):
    note = " ".join(decision.get("notes") or []) or " ".join(decision.get("rules") or []) or decision["verdict"]
    word = "Waiting for you" if decision["verdict"] == "ask" else "Failed"
    return {
        "result": None, "log": note, "preview": preview,
        "action": decision["action"], "action_class": decision["action"],
    }, word


def _admit_write(host, code, document, transaction_name):
    """Every host run is action write. The verdict decides whether it is sent."""
    return hook_decision.decide({
        "tool_name": "write",
        "tool_input": {
            "code": code, "host": host, "path": document,
            "transaction_name": transaction_name,
        },
        "cwd": os.getcwd(),
    })


def host_exec(params, feeds=None):
    """Run in program. Inputs bound into the code; outputs result and log."""
    host = str(params.get("host") or "")
    code = params.get("code")
    transaction_name = params.get("transaction_name")
    transaction = params.get("transaction")
    document = params.get("document")
    element_limit = params.get("element_limit")
    sheet_limit = params.get("sheet_limit")
    min_free_bytes = params.get("min_free_bytes")
    max_hidden_core = params.get("max_hidden_core")
    log_sentinel = params.get("log_sentinel")
    load_module = params.get("load_module")
    isolate_user = params.get("isolate_user")
    isolate_folder = params.get("isolate_folder")
    wired = feeds if isinstance(feeds, Mapping) else {}
    if wired.get("code") not in (None, ""):
        code = wired.get("code")
    if wired.get("document") not in (None, ""):
        document = wired.get("document")
    code = "" if code is None else str(code)
    document = "" if document is None else str(document)
    transaction_name = "" if transaction_name is None else str(transaction_name)
    decision = _admit_write(host, code, document, transaction_name)
    if decision["verdict"] not in _ADMITTED:
        return _held(decision)
    if not code.strip():
        return {"result": None, "log": "Add code, then run.", "action": decision["action"]}, "Failed"
    try:
        result, log = _dispatch(
            host, code, transaction_name, transaction, document, wired,
            _whole(element_limit, "the element limit"),
            _whole(sheet_limit, "the sheet limit"),
            _whole(min_free_bytes, "the free memory"),
            _whole(max_hidden_core, "the background limit"),
            "" if log_sentinel is None else str(log_sentinel),
            "" if load_module is None else str(load_module),
            "" if isolate_user is None else str(isolate_user),
            "" if isolate_folder is None else str(isolate_folder),
        )
    except (OSError, ValueError) as exc:
        return {"result": None, "log": str(exc), "action": decision["action"]}, "Failed"
    return {"result": result, "log": log, "action": decision["action"]}, log or host


def _dispatch(host, code, transaction_name, transaction, document, wired,
              element_limit, sheet_limit, min_free_bytes, max_hidden_core,
              log_sentinel, load_module, isolate_user, isolate_folder):
    from . import host_brokers as brokers
    from .clean_revit_adapter import RevitUnreachable
    bindings = _bindings(wired)
    use_transaction = True if transaction is None else bool(transaction)
    if host == "revit":
        elements, sheets = _batch_count(wired)
        if elements > element_limit:
            raise ValueError("This run has %d elements. The limit is %d." % (elements, element_limit))
        if sheets > sheet_limit:
            raise ValueError("This run has %d sheets. The limit is %d." % (sheets, sheet_limit))
    try:
        if host in ("revit", "acad"):
            title = _confirm_document(brokers, host, document)
            script = _script(host, code, bindings, log_sentinel)
            body = {"code": script, "transaction_name": transaction_name,
                    "transaction": use_transaction}
            answer = brokers.broker_call(host, "/exec", body)
            result = answer.get("result", answer) if isinstance(answer, dict) else answer
            if host == "revit":
                made, made_sheets = _result_count(result)
                if made > element_limit or made_sheets > sheet_limit:
                    raise ValueError("The program returned more than this run allows.")
            log = _title(answer) or title
            return result, log
        if host == "acad-core":
            return _core(code, document, bindings, min_free_bytes, max_hidden_core,
                         log_sentinel, load_module, isolate_user, isolate_folder)
        script = _script(host, code, bindings, log_sentinel)
        if host == "rhino":
            out, label = brokers.rhino_exec({"code": script}, {})
        elif host == "blender":
            out, label = brokers.blender_exec({"code": script}, {})
        elif host == "max":
            out, label = brokers.max_exec({"code": script}, {})
        elif host == "office":
            name = next((value for _key, value in bindings if isinstance(value, str)), "")
            out, label = brokers.office_read({"operation": code, "name": name}, {})
        else:
            raise ValueError("Choose a program.")
    except RevitUnreachable as exc:
        raise ValueError(str(exc)) from exc
    if isinstance(out, dict) and out.get("ok") is False:
        raise ValueError(str(out.get("reason") or label or "The program did not run."))
    result = out.get("out", out) if isinstance(out, dict) else out
    return result, str(label or "")


def _bindings(wired):
    rows = []
    for key, value in wired.items():
        if key in _CONTROL or not _IDENT.match(str(key)):
            continue
        rows.append((str(key), value))
    return rows


def _batch_count(wired):
    elements = sheets = 0
    for key, value in wired.items():
        if key in _CONTROL or not isinstance(value, list):
            continue
        if key == "sheets":
            sheets += len(value)
        else:
            elements += len(value)
    return elements, sheets


def _result_count(result):
    if isinstance(result, list):
        return len(result), 0
    if isinstance(result, dict):
        elements = result.get("elements")
        sheets = result.get("sheets")
        count = result.get("count")
        made = len(elements) if isinstance(elements, list) else count if isinstance(count, int) and not isinstance(count, bool) else 0
        return made, len(sheets) if isinstance(sheets, list) else 0
    return 0, 0


def _confirm_document(brokers, host, wanted):
    """Re-read /info and require the same document title before the write."""
    first = brokers.broker_call(host, "/info")
    title = _title(first)
    second = brokers.broker_call(host, "/info")
    again = _title(second)
    if again != title:
        raise ValueError("The document changed before the write. Run again on the current document.")
    if wanted and again != wanted:
        raise ValueError("The open document is %s. This run asks for %s." % (again or "untitled", wanted))
    return again


def _title(info):
    if not isinstance(info, dict):
        return ""
    for key in ("document", "document_title", "title", "document_name"):
        held = info.get(key)
        if held:
            return str(held)
    return ""


def _script(host, code, bindings, sentinel):
    lines = [_assign(host, name, value) for name, value in bindings]
    lines.append(code)
    if host in ("revit", "acad"):
        return _wrap_csharp("\n".join(lines))
    if host == "acad-core":
        safe = str(sentinel).replace("\\", "\\\\").replace('"', '\\"')
        lines.append('(princ "%s")' % safe)
    return "\n".join(lines)


def _wrap_csharp(code):
    """A bare return; is CS0126 in a method that must return a value."""
    body = re.sub(r"(?m)^([ \t]*)return[ \t]*;[ \t]*$", r"\1return null;", code)
    return "object result = null;\n%s\nreturn result;" % body


def _assign(host, name, value):
    literal = _literal(host, value)
    if host in ("revit", "acad"):
        return "var %s = %s;" % (name, literal)
    if host == "acad-core":
        return "(setq %s %s)" % (name, literal)
    return "%s = %s" % (name, literal)


def _literal(host, value):
    if value is None:
        return "null" if host in ("revit", "acad") else "nil" if host == "acad-core" else "None"
    if isinstance(value, bool):
        if host == "acad-core":
            return "T" if value else "nil"
        if host in ("revit", "acad", "max"):
            return "true" if value else "false"
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    packed = json.dumps(value, ensure_ascii=False)
    if host in ("revit", "acad"):
        return json.dumps(packed, ensure_ascii=False)
    return packed


def _local_file(path, label):
    text = str(path or "").strip()
    if not text:
        raise ValueError("Choose a %s." % label)
    if text.startswith(("\\\\", "//")) or text.upper().startswith(("\\\\?\\UNC", "SMB:", "FILE:")):
        raise ValueError("%s must be a local file." % label)
    if not os.path.isfile(text):
        raise ValueError("%s does not exist." % label)
    return text


def find_console(explicit):
    text = str(explicit or "").strip()
    if text:
        return text if os.path.isfile(text) else ""
    for candidate in _CONSOLE_NAMES:
        if os.path.isfile(candidate):
            return candidate
    return ""


def hidden_cores():
    """accoreconsole processes only. The user's own AutoCAD is not one of them."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq accoreconsole.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=flags,
        )
    except OSError as exc:
        raise ValueError("Could not count background AutoCAD.") from exc
    text = (completed.stdout or "") + (completed.stderr or "")
    return text.lower().count("accoreconsole.exe")


def free_bytes():
    if os.name != "nt":
        raise ValueError("Background AutoCAD runs on Windows.")
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_ = (
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ValueError("Could not read free memory.")
    return int(status.ullAvailPhys)


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def launch_console(argv, creationflags):
    completed = subprocess.run(
        list(argv), creationflags=int(creationflags), capture_output=True, text=True,
    )
    return (completed.stdout or "") + (completed.stderr or ""), int(completed.returncode)


def _core(code, document, bindings, min_free_bytes, max_hidden_core,
          log_sentinel, load_module, isolate_user, isolate_folder):
    if hidden_cores() >= max_hidden_core:
        raise ValueError("A background AutoCAD is already running.")
    if free_bytes() < min_free_bytes:
        raise ValueError("Not enough free memory to start background AutoCAD.")
    if not log_sentinel:
        raise ValueError("Set the log mark.")
    if not load_module:
        raise ValueError("Set the AutoCAD module.")
    exe = find_console("")
    if not exe:
        raise ValueError("AutoCAD (background) is not installed.")
    drawing = _local_file(document, "drawing")
    user = isolate_user or os.environ.get("USERNAME") or "archhub"
    folder = Path(isolate_folder) if isolate_folder else Path(tempfile.gettempdir()) / "archhub-acad-core" / user
    if str(folder).startswith(("\\\\", "//")):
        raise ValueError("The isolate folder must be local.")
    folder.mkdir(parents=True, exist_ok=True)
    script_path = folder / "run.scr"
    script_path.write_text(_script("acad-core", code, bindings, log_sentinel), encoding="utf-8")
    before = (hash_file(drawing), hash_file(script_path))
    claim = folder / "claims" / (hashlib.sha256(("\n".join(before)).encode("utf-8")).hexdigest() + ".claim")
    claim.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(claim, "x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("This run already has a claim. It will not run again.") from exc
    with handle:
        handle.write("\n".join(before))
    after = (hash_file(drawing), hash_file(script_path))
    if after != before:
        raise ValueError("The drawing or script changed before the run. It was not started.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    argv = [exe, "/isolate", user, str(folder), "/loadmodule", load_module, "/i", drawing, "/s", str(script_path)]
    log, _status = launch_console(argv, flags)
    if log_sentinel not in log:
        raise ValueError("The background run finished without its log mark.")
    return {"ok": True}, log


def program_state(host):
    """Plain program word for the node header. Never runs code in the document."""
    key = str(host or "")
    label = dict(PROGRAMS).get(key, "")
    if not label:
        return {"id": key, "label": "", "state": "Not available", "reachable": False}
    try:
        state = _state_word(key)
    except (OSError, ValueError):
        state = "Not available"
    return {"id": key, "label": label, "state": state, "reachable": state in _REACHABLE}


def _state_word(host):
    from . import host_brokers as brokers
    if host in ("revit", "acad"):
        rows = brokers.broker_sessions(host, include_document=False)
        return "Connected" if rows else "Not installed"
    if host == "acad-core":
        return "Installed" if find_console("") else "Not installed"
    if host == "rhino":
        out, _label = brokers.rhino_exec({"code": ""}, {})
        return "Connected" if isinstance(out, dict) and out.get("ok") is not False else "Not installed"
    if host == "blender":
        out, _label = brokers.blender_exec({"code": ""}, {})
        return "Connected" if isinstance(out, dict) and out.get("ok") is not False else "Not installed"
    if host == "max":
        out, _label = brokers.max_exec({"code": ""}, {})
        return "Connected" if isinstance(out, dict) and out.get("ok") is not False else "Not installed"
    if host == "office":
        return "Connected" if brokers._com_alive("Excel.Application") else "Not installed"
    return "Not available"


def _notion_tools():
    from . import notion_mcp
    return notion_mcp.list_tools()


def _notion_invoke(action, arguments):
    from . import notion_mcp
    payload = arguments if isinstance(arguments, Mapping) else {}
    return notion_mcp.call_tool(action, payload)


LISTERS = {"notion": _notion_tools}
INVOKERS = {"notion": _notion_invoke}


def connector_actions(connector):
    """Live tool list from the connector itself. Called again on every read."""
    name = str(connector or "").strip()
    if not name:
        return []
    lister = LISTERS.get(name)
    if lister is None:
        raise ConnectorUnreachable("This connector is not connected.")
    try:
        from . import notion_mcp
        rows = lister()
    except (OSError, ValueError, notion_mcp.NotionNotConnected, notion_mcp.NotionToolError) as exc:
        raise ConnectorUnreachable("Could not read actions.") from exc
    if not isinstance(rows, list):
        raise ConnectorUnreachable("Could not read actions.")
    listed = []
    for row in rows:
        if isinstance(row, Mapping) and row.get("name"):
            inputs = [str(item) for item in row.get("inputs") or [] if isinstance(item, str)]
            listed.append({"name": str(row["name"]), "title": str(row.get("title") or row["name"]),
                           "inputs": inputs})
    return listed


def connector_preview(connector, action, args):
    """Classify the action with decide(). Sends show their text and are not sent from here."""
    decision = hook_decision.decide({
        "tool_name": str(action or ""),
        "tool_input": {"text": _preview_text(args), "connector": str(connector or "")},
        "cwd": os.getcwd(),
    })
    preview = _preview_text(args) if decision["action"] in ("send", "publish") else ""
    return {"action_class": decision["action"], "preview": preview, "verdict": decision["verdict"]}


def connector_call(params, feeds=None):
    """Connector action. The action list is live. Sends and posts wait on decide()."""
    connector = str(params.get("connector") or "")
    action = str(params.get("action") or "")
    args = params.get("args")
    wired = feeds if isinstance(feeds, Mapping) else {}
    if "args" in wired:
        args = wired.get("args")
    decision = hook_decision.decide({
        "tool_name": action,
        "tool_input": {
            "text": _preview_text(args),
            "connector": connector,
            "arguments": dict(args) if isinstance(args, Mapping) else {"value": args},
        },
        "cwd": os.getcwd(),
    })
    preview = _preview_text(args) if decision["action"] in ("send", "publish") else ""
    if decision["verdict"] not in _ADMITTED:
        return _held(decision, preview)
    if not action:
        return {"result": None, "log": "Choose an action.", "action": decision["action"],
                "action_class": decision["action"], "preview": preview}, "Failed"
    try:
        listed = connector_actions(connector)
        if action not in {row["name"] for row in listed}:
            raise ConnectorUnreachable("Choose an action from the list.")
        invoker = INVOKERS.get(connector)
        if invoker is None:
            raise ConnectorUnreachable("This connector is not connected.")
        result = invoker(action, args if isinstance(args, Mapping) else {"value": args})
    except (OSError, ValueError) as exc:
        return {"result": None, "log": str(exc), "action": decision["action"],
                "action_class": decision["action"], "preview": preview}, "Failed"
    return {
        "result": result, "log": action, "preview": preview,
        "action": decision["action"], "action_class": decision["action"],
    }, action
