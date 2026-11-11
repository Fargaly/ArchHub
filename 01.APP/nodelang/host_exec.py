"""Two generic nodes: run code in a program, or call one connector action.

Both extend the runners that already exist (host brokers, rhino.exec,
blender.exec, max.exec, office.read, notion_mcp, and the connector engines
already registered on those brokers). No second broker.
Every run is admitted by hook_decision.decide before anything is sent.
A Python run is the same write admission, in the app's own interpreter.
"""
from __future__ import annotations

import hashlib
import ast
import json
import os
import re
import shutil
import subprocess
import sys
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
    ("python", "Python"),
)


def script_is_pure(code):
    """Only bounded, expression-based Python can re-solve without approval."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, TypeError):
        return False
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
               ast.If, ast.IfExp, ast.Expr, ast.Dict, ast.List, ast.Tuple, ast.Constant,
               ast.Name, ast.Load, ast.Store, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
               ast.Subscript, ast.Slice, ast.Call, ast.keyword, ast.operator, ast.unaryop,
               ast.boolop, ast.cmpop)
    calls = {'str', 'int', 'float', 'bool', 'len', 'min', 'max', 'sum', 'abs', 'round', 'sorted', 'list', 'dict', 'tuple'}
    return (len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
            and tree.body[0].name == 'run' and not tree.body[0].decorator_list
            and all(isinstance(n, allowed)
                    and not (isinstance(n, ast.FunctionDef) and n is not tree.body[0])
                    and not (isinstance(n, (ast.Name, ast.arg)) and (getattr(n, 'id', getattr(n, 'arg', '')).startswith('_')))
                    and not (isinstance(n, ast.Call) and (not isinstance(n.func, ast.Name) or n.func.id not in calls))
                    for n in ast.walk(tree)))


def script_python(params, feeds):
    """Script nodes reuse the existing timed Python process, never a second runner."""
    code = params.get('code', '')
    if not isinstance(code, str) or len(code) > 65536:
        raise ValueError('Script code must be text, up to 64 KiB.')
    if params.get('kind', 'pure') not in ('pure', 'effect'):
        raise ValueError('Script kind must be Pure or Effect.')
    inputs = {key: value for key, value in feeds.items() if key not in ('code', 'kind', 'timeout')}
    if 'a' in params:
        inputs.setdefault('a', params['a'])
    result, log = _python(code + '\nresult = run(**_archhub_inputs)', {'_archhub_inputs': inputs}, params.get('timeout', 30))
    if not isinstance(result, dict):
        raise ValueError('Return a dictionary with one value per output.')
    return result, log or 'Script returned %d outputs' % len(result)

_CONTROL = frozenset({
    "host", "code", "transaction_name", "transaction", "document",
    "element_limit", "sheet_limit", "min_free_bytes", "max_hidden_core",
    "log_sentinel", "load_module", "isolate_user", "isolate_folder",
    "connector", "action", "args", "timeout",
})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONSOLE_NAMES = (
    r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
)
_ADMITTED = ("allow", "organize")
_REACHABLE = {"Connected", "Installed", "Ready to connect"}
_TIMED_OUT = object()


class ConnectorUnreachable(ValueError):
    """The connector did not return its own tool list."""


def programs():
    return [{"id": key, "label": label} for key, label in PROGRAMS]


def connectors():
    """Every connector that has registered a live action list."""
    _ensure_registry()
    return [{"id": key, "label": _LABELS.get(key, key)} for key in sorted(LISTERS)]


def _whole(value, label):
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError("Set %s." % label)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a whole number." % label) from exc


def _node_timeout():
    """The host.exec timeout parameter. Empty runs use this, not a second literal."""
    from .library_engines import LIBRARY_ITEM_ENGINES
    return LIBRARY_ITEM_ENGINES["host_exec"]["params"]["timeout"]


def _limit_seconds(time_limit):
    """Node time limit. An empty value uses the host.exec timeout parameter."""
    if time_limit is None or time_limit == "":
        time_limit = _node_timeout()
    seconds = _whole(time_limit, "the time limit")
    if seconds < 1:
        raise ValueError("The time limit must be at least 1.")
    return seconds


def _captured(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _wait_timed_out(exc):
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return True
    return isinstance(getattr(exc, "reason", None), TimeoutError)


def _timeout_log(exc):
    text = _captured(getattr(exc, "stdout", None)) + _captured(getattr(exc, "stderr", None))
    if text.strip():
        return text
    reason = getattr(exc, "reason", None)
    return _captured(reason if reason is not None else exc)


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
    time_limit = params.get("timeout")
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
        seconds = _limit_seconds(time_limit)
        result, log = _dispatch(
            host, code, transaction_name, transaction, document, _bound(params, wired),
            _whole(element_limit, "the element limit"),
            _whole(sheet_limit, "the sheet limit"),
            _whole(min_free_bytes, "the free memory"),
            _whole(max_hidden_core, "the background limit"),
            "" if log_sentinel is None else str(log_sentinel),
            "" if load_module is None else str(load_module),
            "" if isolate_user is None else str(isolate_user),
            "" if isolate_folder is None else str(isolate_folder),
            seconds,
        )
    except (OSError, ValueError) as exc:
        return {"result": None, "log": str(exc), "action": decision["action"]}, "Failed"
    if result is _TIMED_OUT:
        return {"result": "Timed out", "log": log, "action": decision["action"]}, "Timed out"
    return {"result": result, "log": log, "action": decision["action"]}, log or host


def _dispatch(host, code, transaction_name, transaction, document, wired,
              element_limit, sheet_limit, min_free_bytes, max_hidden_core,
              log_sentinel, load_module, isolate_user, isolate_folder, seconds):
    bindings = _bindings(wired)
    if host == "python":
        return _python(code, dict(bindings), seconds)
    from . import host_brokers as brokers
    from .clean_revit_adapter import RevitUnreachable
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
            try:
                answer = brokers.broker_call(host, "/exec", body, timeout=seconds)
            except OSError as exc:
                if not _wait_timed_out(exc):
                    raise
                return _TIMED_OUT, _timeout_log(exc)
            result = answer.get("result", answer) if isinstance(answer, dict) else answer
            if host == "revit":
                made, made_sheets = _result_count(result)
                if made > element_limit or made_sheets > sheet_limit:
                    raise ValueError("The program returned more than this run allows.")
            log = _title(answer) or title
            return result, log
        if host == "acad-core":
            return _core(code, document, bindings, min_free_bytes, max_hidden_core,
                         log_sentinel, load_module, isolate_user, isolate_folder, seconds)
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


def _user_parameters(mapping):
    """Parameter values a workflow can name. Built-in controls stay controls."""
    if not isinstance(mapping, Mapping):
        return {}
    return {
        str(key): value
        for key, value in mapping.items()
        if key not in _CONTROL and _IDENT.match(str(key))
    }


def _bound(params, wired):
    """User parameters and wired feeds, as one set of code variables. A wire wins."""
    merged = _user_parameters(params)
    merged.update(_user_parameters(wired))
    return merged


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


def launch_console(argv, creationflags, timeout=None):
    """Run one owned console. The time limit stops that process and no other."""
    seconds = _limit_seconds(timeout)
    try:
        completed = subprocess.run(
            list(argv), creationflags=int(creationflags), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=seconds,
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run already called kill() on this Popen only.
        return _timeout_log(exc), "timed_out"
    return _captured(completed.stdout) + _captured(completed.stderr), int(completed.returncode)


def _core(code, document, bindings, min_free_bytes, max_hidden_core,
          log_sentinel, load_module, isolate_user, isolate_folder, seconds):
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
    log, status = launch_console(argv, flags, seconds)
    if status == "timed_out":
        return _TIMED_OUT, log
    if log_sentinel not in log:
        raise ValueError("The background run finished without its log mark.")
    return {"ok": True}, log


_PYTHON_MARK = "ARCHHUB-RESULT "
_PYTHON_RUNNER = r"""
import json, sys
request = json.load(sys.stdin)
if not request.get("network"):
    import socket
    def _blocked(*_args, **_kwargs):
        raise OSError("This Python run has no network.")
    class _Socket(socket.socket):
        def connect(self, address):
            raise OSError("This Python run has no network.")
        def connect_ex(self, address):
            raise OSError("This Python run has no network.")
    socket.socket = _Socket
    socket.create_connection = _blocked
namespace = {}
namespace.update(request.get("bindings") or {})
try:
    exec(compile(request.get("code") or "", "<python>", "exec"), namespace, namespace)
except Exception as exc:
    sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc))
    sys.exit(1)
sys.stdout.write("\n" + "ARCHHUB-RESULT ")
json.dump(namespace.get("result"), sys.stdout, default=str)
"""
_CONNECTOR_CODE = re.compile(r"\b(connector_call|notion_mcp|outlook_graph|dropbox_list)\b")


def app_python():
    """The app venv interpreter. The running interpreter stands in until that venv exists."""
    nodelang = Path(__file__).resolve().parent
    names = ("python.exe", "python")
    for root in (nodelang.parent, nodelang.parent.parent, nodelang):
        for name in names:
            for folder in ("Scripts", "bin"):
                candidate = root / ".venv" / folder / name
                if candidate.is_file():
                    return str(candidate)
    return sys.executable


def _python_env(python, scratch):
    system = os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot") or r"C:\Windows"
    return {
        "SYSTEMROOT": system,
        "WINDIR": system,
        "PATH": str(Path(python).resolve().parent) + os.pathsep + str(Path(system) / "System32"),
        "TEMP": str(scratch),
        "TMP": str(scratch),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _json_bindings(bindings):
    packed = {}
    for key, value in bindings.items():
        try:
            json.dumps(value)
        except TypeError as exc:
            raise ValueError("Parameter %s cannot be sent to Python." % key) from exc
        packed[key] = value
    return packed


def _python(code, bindings, seconds):
    """Run in the app interpreter. The caller already admitted this as a write.

    The process is separate, isolated, and stopped at the node's time limit.
    Sockets stay closed unless the code itself is a connector call.
    """
    seconds = _limit_seconds(seconds)
    python = app_python()
    if not os.path.isfile(python):
        raise ValueError("Python is not installed.")
    scratch = Path(tempfile.mkdtemp(prefix="archhub-python-"))
    payload = json.dumps({
        "code": code,
        "bindings": _json_bindings(bindings),
        "network": bool(_CONNECTOR_CODE.search(code)),
    })
    try:
        completed = subprocess.run(
            [python, "-I", "-B", "-c", _PYTHON_RUNNER],
            input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=seconds, cwd=str(scratch), env=_python_env(python, scratch),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("The Python run timed out.") from exc
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    lines = (completed.stdout or "").splitlines()
    result_line = None
    kept = []
    for line in lines:
        if line.startswith(_PYTHON_MARK):
            result_line = line[len(_PYTHON_MARK):]
        else:
            kept.append(line)
    err = (completed.stderr or "").strip()
    if err:
        kept.append(err)
    log = "\n".join(kept).strip()
    if completed.returncode:
        raise ValueError(log or "Python did not run.")
    if result_line is None:
        raise ValueError(log or "Python did not return a result.")
    try:
        result = json.loads(result_line)
    except ValueError as exc:
        raise ValueError("Python returned a result ArchHub cannot read.") from exc
    return result, log


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
    if host == "python":
        return "Installed" if os.path.isfile(app_python()) else "Not installed"
    return "Not available"


def _notion_tools():
    from . import notion_mcp
    return notion_mcp.list_tools()


def _notion_invoke(action, arguments):
    from . import notion_mcp
    payload = arguments if isinstance(arguments, Mapping) else {}
    return notion_mcp.call_tool(action, payload)


LISTERS = {}
INVOKERS = {}
_LABELS = {
    "notion": "Notion",
    "outlook-new": "Outlook (New / Microsoft Graph)",
    "outlook": "Outlook",
    "outlook-imap": "Company mail",
    "dropbox": "Dropbox",
    "office": "Office",
}
_NOT_A_CONNECTOR = frozenset({"connector.rows"})
_COM_WRITE = frozenset({"outlook.reply_draft", "outlook.forward_draft"})
_PROGRAM_PREFIX = ("max.", "rhino.", "blender.")
_OFFICE_PREFIX = ("excel.", "pdf.", "office.")


def _connector_id(engine_name):
    """Which connector an already-registered engine belongs to. Program hosts are not connectors."""
    name = str(engine_name or "")
    if name in _NOT_A_CONNECTOR or name in _COM_WRITE or name.startswith(_PROGRAM_PREFIX):
        return ""
    if name.startswith("outlook.graph."):
        return "outlook-new"
    if name.startswith("outlook.imap."):
        return "outlook-imap"
    if name.startswith("notion."):
        return ""
    if name.startswith(_OFFICE_PREFIX):
        return "office"
    head, sep, _tail = name.partition(".")
    return head if sep else ""


def _actions_of(connector_id):
    def list_actions():
        from .host_brokers import ACTION_FIELDS, ENGINES
        rows = []
        for name in sorted(ENGINES):
            if _connector_id(name) != connector_id:
                continue
            rows.append({"name": name, "title": name, "inputs": list(ACTION_FIELDS.get(name, ()))})
        if not rows:
            raise ConnectorUnreachable("Could not read actions.")
        return rows
    return list_actions


def _invoke_of(connector_id):
    def invoke(action, arguments):
        from .host_brokers import ENGINES
        if _connector_id(action) != connector_id or action not in ENGINES:
            raise ConnectorUnreachable("Choose an action from the list.")
        payload = arguments if isinstance(arguments, Mapping) else {}
        answer = ENGINES[action](payload, {})
        if isinstance(answer, tuple):
            out = answer[0]
            label = answer[1] if len(answer) > 1 else ""
        else:
            out, label = answer, ""
        if isinstance(out, dict) and out.get("ok") is False:
            raise ValueError(str(out.get("reason") or label or "The connector did not run."))
        if isinstance(out, dict) and "out" in out:
            return out["out"]
        return out
    return invoke


def register_connector(connector_id, label, list_actions, invoke):
    """One connector adds itself. connector.call reads whatever is registered."""
    key = str(connector_id or "").strip()
    if not key:
        raise ValueError("Name the connector.")
    if not callable(list_actions) or not callable(invoke):
        raise ValueError("A connector needs its action list and its call.")
    LISTERS[key] = list_actions
    INVOKERS[key] = invoke
    if label:
        _LABELS[key] = str(label)
    return key


def _ensure_registry():
    """Fill any connector the brokers already registered. A prior registration is kept."""
    if "notion" not in LISTERS:
        LISTERS["notion"] = _notion_tools
        INVOKERS["notion"] = _notion_invoke
    from .host_brokers import ENGINES
    seen = []
    for name in ENGINES:
        cid = _connector_id(name)
        if cid and cid not in seen:
            seen.append(cid)
    for cid in seen:
        if cid not in LISTERS:
            LISTERS[cid] = _actions_of(cid)
            INVOKERS[cid] = _invoke_of(cid)


def connector_actions(connector):
    """Live tool list from the connector itself. Called again on every read."""
    name = str(connector or "").strip()
    if not name:
        return []
    _ensure_registry()
    lister = LISTERS.get(name)
    if lister is None:
        raise ConnectorUnreachable("This connector is not connected.")
    try:
        rows = lister()
    except (OSError, ValueError) as exc:
        raise ConnectorUnreachable("Could not read actions.") from exc
    except Exception as exc:
        from . import notion_mcp
        if isinstance(exc, (notion_mcp.NotionNotConnected, notion_mcp.NotionToolError)):
            raise ConnectorUnreachable("Could not read actions.") from exc
        raise
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


def _action_args(args, params, wired):
    """A parameter named args, or each other user parameter, is the action's arguments.

    A wired args value wins on the same key. A wired args value that is not a
    mapping replaces the arguments, as a direct args wire always has.
    """
    extras = _bound(params, wired)
    if isinstance(args, Mapping):
        merged = {**dict(args), **extras}
    elif extras:
        merged = {"value": args, **extras} if args not in (None, "") else dict(extras)
    else:
        merged = args
    if isinstance(wired, Mapping) and "args" in wired:
        incoming = wired.get("args")
        if isinstance(merged, Mapping) and isinstance(incoming, Mapping):
            merged = {**merged, **dict(incoming)}
        else:
            merged = incoming
    return merged


def connector_call(params, feeds=None):
    """Connector action. The action list is live. Sends and posts wait on decide()."""
    connector = str(params.get("connector") or "")
    action = str(params.get("action") or "")
    wired = feeds if isinstance(feeds, Mapping) else {}
    args = _action_args(params.get("args"), params, wired)
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
