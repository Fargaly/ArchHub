"""GUI idle-stall root fix (2026-06-02) — host-pill probe is OFF the Qt thread.

The Qt MainThread was caught (py-spy) parked in the host-pill refresh: the
6 s `_host_pill_timer` tick called `_refresh_host_pills`, which probed every
broker INLINE on the GUI thread — `*_broker.list_sessions()` port-scans the
48884-48899 MCP range with synchronous `socket.create_connection` + `urlopen`
+ a `ThreadPoolExecutor.map` join. Cold, ~2 s+; the whole UI froze on an idle
timer tick.

The fix fans the blocking probe onto a worker `QThread` and repaints from the
`_host_pills_ready` signal on the GUI thread. These tests are the guard that
the culprit timer-callback stays non-blocking — both statically (the
maintenance-audit timer-callback detector clears it) and structurally (the
method spawns a thread + does not call the blocking probe synchronously, and
the repaint slot does no I/O).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import maintenance_audit as ma  # noqa: E402

CHAT_WINDOW = REPO / "app" / "chat_window.py"


def _chat_window_lines() -> list[str]:
    return CHAT_WINDOW.read_text(encoding="utf-8").splitlines()


def _method_source(name: str) -> str:
    """Return the source of ChatWindow.<name> (top-level method body)."""
    tree = ast.parse(CHAT_WINDOW.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ChatWindow":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    return ast.get_source_segment(
                        CHAT_WINDOW.read_text(encoding="utf-8"), item) or ""
    return ""


# ─── static-audit guard ──────────────────────────────────────────────


def test_refresh_host_pills_is_a_wired_timer_callback():
    """Sanity: the method is actually driven by a QTimer — otherwise the
    detector below proves nothing."""
    names = ma._timer_callback_names(_chat_window_lines())
    assert "_refresh_host_pills" in names


def test_refresh_host_pills_not_flagged_blocking():
    """The maintenance-audit timer-callback + slot detectors must find NO
    blocking I/O in `_refresh_host_pills` — proving the probe moved off the
    Qt thread. If this fails, the blocking probe crept back onto the tick."""
    lines = _chat_window_lines()
    audit = ma.Audit()
    ma.scan_blocking_in_timer_callback(audit, CHAT_WINDOW, lines)
    ma.scan_blocking_in_slot(audit, CHAT_WINDOW, lines)
    offenders = [
        f"{f.cls} @ chat_window.py:{f.line}"
        for f in audit.findings
        if f.cls in ("blocking-in-timer-callback", "blocking-in-pyqtslot")
        and "_refresh_host_pills" in f.detail
    ]
    assert not offenders, (
        "host-pill refresh regressed to blocking the Qt thread:\n  "
        + "\n  ".join(offenders))


# ─── structural guard ────────────────────────────────────────────────


def test_refresh_host_pills_spawns_a_thread():
    """The timer callback must hand the work to a QThread, not run it
    inline."""
    src = _method_source("_refresh_host_pills")
    assert src, "could not locate ChatWindow._refresh_host_pills"
    assert "QThread(" in src and ".start()" in src, (
        "_refresh_host_pills no longer spawns a worker QThread — the "
        "blocking broker probe would run on the Qt GUI thread")
    # The result is delivered via the cross-thread signal, never painted
    # inline from the worker.
    assert "_host_pills_ready.emit" in src


def test_probe_is_not_called_on_gui_thread_path():
    """`_probe_host_status` (the blocking port-scan entry) must be invoked
    only from inside the worker `run`, never directly in the timer
    callback's own GUI-thread statements.

    Inspect the AST so the docstring (which describes the OLD inline call)
    and the nested worker class are excluded — we check only the real
    top-level statements the callback runs on the Qt thread."""
    full = CHAT_WINDOW.read_text(encoding="utf-8")
    tree = ast.parse(full)
    fn = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_refresh_host_pills"):
            fn = node
            break
    assert fn is not None, "could not locate ChatWindow._refresh_host_pills"

    gui_chunks = []
    for i, stmt in enumerate(fn.body):
        # Skip the leading docstring.
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(
                getattr(stmt, "value", None), ast.Constant) and isinstance(
                stmt.value.value, str):
            continue
        # Skip the nested worker class definition (its body legitimately
        # calls the blocking probe — but ON the worker thread).
        if isinstance(stmt, ast.ClassDef):
            continue
        seg = ast.get_source_segment(full, stmt) or ""
        gui_chunks.append(seg)
    gui_only = "\n".join(gui_chunks)
    assert "_probe_host_status" not in gui_only, (
        "_probe_host_status is called on the GUI-thread path of "
        "_refresh_host_pills — it must run only inside the worker thread")


def test_repaint_slot_does_no_io():
    """`_on_host_pills_ready` runs on the GUI thread; it must do widget work
    only — no broker probe, no socket / HTTP. It must not call the blocking
    probe nor any broker list_sessions."""
    src = _method_source("_on_host_pills_ready")
    assert src, "could not locate ChatWindow._on_host_pills_ready"
    for banned in ("_probe_host_status", "list_sessions",
                   "create_connection", "urlopen"):
        assert banned not in src, (
            f"_on_host_pills_ready does blocking work ({banned}) on the Qt "
            f"thread — it must only repaint widgets")
