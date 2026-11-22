"""Observe, without gating, the installed NoGraph worker and Qt window lifecycle."""
import ast
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

def recent_owner(state):
    return state / "data" / "sessions" / "recent.json"


def lock_policy(installed):
    path = installed / "nodelang" / "canvas_documents.py"
    syntax = ast.parse(path.read_text(encoding="utf-8"))
    node = next(part for part in syntax.body if isinstance(part, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "DOCUMENT_NODE" for target in part.targets))
    locker = next(part for part in syntax.body if isinstance(part, ast.FunctionDef) and part.name == "locked")
    policy = ast.literal_eval(node.value)["params"]
    return policy["lock_poll_seconds"], ast.literal_eval(locker.args.defaults[-1])


class RecentWriter:
    """Hold the installed Session Files owner's real cross-process writer lock on this disposable profile."""

    def __init__(self, installed, trace_path):
        self.trace_path = trace_path
        self.owner = recent_owner(trace_path.parent)
        self.poll, self.budget = lock_policy(installed)
        self.stop = threading.Event()
        self.started = threading.Event()
        self.receipt = {}
        self.thread = threading.Thread(target=self._hold, daemon=True)
        self.thread.start()
        if not self.started.wait(self.budget):
            self.stop.set()
            raise RuntimeError("The disposable recent-session lock witness did not start")
        if "acquired_ns" not in self.receipt:
            raise RuntimeError("The disposable recent-session lock was unavailable: " + self.receipt["error"])

    def _hold(self):
        import msvcrt

        key = hashlib.sha1(str(self.owner.resolve()).lower().encode()).hexdigest() + ".lock"
        lock = self.owner.parent / "locks" / key
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            with lock.open("a+b") as handle:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                reason = "installed lock budget expired"
                try:
                    self.receipt.update(owner="data/sessions/recent.json", lock=key, acquired_ns=time.monotonic_ns())
                    deadline = time.monotonic() + self.budget
                    self.started.set()
                    while (remaining := deadline - time.monotonic()) > 0:
                        if self.stop.is_set():
                            reason = "rig cleanup"
                            break
                        if any(row["event"] == "server_close_call" for row in events(self.trace_path)):
                            reason = "observed server_close_call"
                            break
                        self.stop.wait(min(remaining, self.poll))
                finally:
                    handle.seek(0)
                    self.receipt["release_started_ns"] = time.monotonic_ns()
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    self.receipt.update(release=reason, released_ns=time.monotonic_ns())
        except (OSError, ValueError, KeyError) as error:
            self.receipt["error"] = type(error).__name__
        finally:
            self.started.set()

    def close(self):
        self.stop.set()
        self.thread.join(self.budget)
        if self.thread.is_alive():
            raise RuntimeError("The disposable recent-session writer did not release its lock")
        return self.receipt


def watch_window_close(window, record, handle_changed=None):
    from PyQt6.QtCore import QEvent, QObject

    class CloseObserver(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Close:
                record("window_close")
            elif handle_changed and event.type() == QEvent.Type.WinIdChange:
                handle_changed()
            return False

    observer = CloseObserver(window)
    window.installEventFilter(observer)
    return observer


def native_quit_request(trace_path):
    return Path(trace_path).with_name("f38-native-quit")


def watch_native_actions(window, view, trace_path, record, poll):
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

    def hwnd_if_created():
        if window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return int(window.winId())
        return None

    def handle_changed():
        record("native_hwnd_changed", hwnd=hwnd_if_created())

    observer = watch_window_close(window, record, handle_changed)
    actions = [action for tray in QApplication.instance().findChildren(QSystemTrayIcon)
               if tray.contextMenu() is not None for action in tray.contextMenu().actions()
               if tray.isVisible() and action.isEnabled() and action.text() == "Quit ArchHub"]
    timer = QTimer(observer)
    request = native_quit_request(trace_path)

    def quit_if_requested():
        if request.is_file():
            timer.stop()
            record("window_request_quit", hwnd=hwnd_if_created(), action="Quit ArchHub")
            actions[0].trigger()

    if len(actions) == 1:
        timer.timeout.connect(quit_if_requested)
        timer.start(round(poll * 1000))

    def navigation_finished(ok):
        if ok and view.url().path() == "/studio":
            record("studio_navigation_finished")

    view.loadFinished.connect(navigation_finished)
    record("native_window_ready", hwnd=hwnd_if_created(), tray_quit_available=len(actions) == 1)
    return observer, timer


def observe_worker(trace_path):
    """Trace entry/return of the installed methods without controlling their execution."""
    receipt = Path(trace_path)
    pid = os.getpid()
    observers = []
    contended = False
    resumed = False
    owner = recent_owner(receipt.parent)

    def record(observed, **facts):
        with receipt.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": observed, "pid": pid, "monotonic_ns": time.monotonic_ns(), **facts}) + "\n")

    def trace(frame, event, callable_value):
        nonlocal contended, resumed
        module = frame.f_globals.get("__name__")
        if (not resumed and module == "nodelang.canvas_documents" and frame.f_code.co_name == "locked"
                and event in ("c_exception", "c_return") and getattr(callable_value, "__name__", None) == "locking"
                and frame.f_locals.get("path") == owner and threading.current_thread().name == "archhub-nograph-warm"):
            if not contended and event == "c_exception":
                contended = True
                record("recent_writer_contended")
            elif contended and event == "c_return":
                resumed = True
                record("recent_writer_resumed")
        if event not in ("call", "return"):
            return
        if module not in ("nodelang.nograph_server", "nodelang.window_commands"):
            return
        name = frame.f_code.co_qualname
        observed = None
        if module == "nodelang.nograph_server":
            if name == "NoGraphServer._warm_after_listen":
                observed = "warm_" + event
            elif name == "NoGraphServer.close":
                observed = "server_close_" + event
        elif name == "WindowCommands.__init__" and event == "return":
            installed = Path(frame.f_code.co_filename).resolve().parents[1]
            poll, _budget = lock_policy(installed)
            observers.append(watch_native_actions(frame.f_locals["window"], frame.f_locals["view"], receipt, record, poll))
        elif event == "call":
            if name == "CloseToTray.__init__":
                observed = "tray_setup"
            elif name == "CloseToTray.quit":
                observed = "tray_quit_entered"
        if observed:
            record(observed)


    threading.setprofile(trace)
    sys.setprofile(trace)


def events(trace_path, listener_pid=None):
    if not trace_path.is_file():
        return []
    # A live worker can be in the middle of appending the final record.
    complete, _, _ = trace_path.read_bytes().rpartition(b"\n")
    return [row for row in map(json.loads, complete.splitlines()) if listener_pid is None or row["pid"] == listener_pid]


def window_state(desktop, owner, phase, tray, deadline, settle_seconds, poll_seconds):
    import psutil

    endpoint = urlsplit(owner["endpoint"])
    address = (endpoint.hostname, endpoint.port)
    listener = owner["listener_pid"]
    while True:
        pids = sorted(desktop.job.pids())
        handles = [{"pid": pid, "hwnd": hwnd} for pid, title, hwnd in desktop.windows(with_handles=True)
                   if pid in pids and title == "ArchHub"]
        windows = [row["pid"] for row in handles]
        owned = False
        ownership_error = None
        if listener in pids:
            try:
                owned = any(row.status == psutil.CONN_LISTEN and row.laddr == address
                            for row in psutil.Process(listener).net_connections(kind="tcp"))
            except psutil.Error as ownership_failure:
                ownership_error = type(ownership_failure).__name__
        connected = False
        healthy = False
        network_error = None
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                with socket.create_connection(address, timeout=min(remaining, settle_seconds)):
                    connected = True
                remaining = deadline - time.monotonic()
                if owned and remaining > 0:
                    with urllib.request.urlopen(owner["endpoint"], timeout=min(remaining, settle_seconds)) as response:
                        healthy = response.status == 204
            except OSError as network_failure:
                network_error = type(network_failure).__name__
        stopped = not pids and network_error == 'ConnectionRefusedError'
        if phase == "before" or (phase == "close" and not windows and (tray or stopped)) or (phase == "quit" and stopped):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(remaining, poll_seconds))
    return {"phase": phase, "launch_pid": owner["pid"], "listener_pid": listener, "listener_port": endpoint.port,
            "tray_setup": tray, "visible_window_pids": windows, "visible_windows": handles,
            "job_app_pids": pids, "port_reachable": connected,
            "listener_owned": owned, "listener_http_204": healthy, "port_refused": network_error == "ConnectionRefusedError",
            "ownership_error": ownership_error, "network_error": network_error, "monotonic_ns": time.monotonic_ns()}


def post_owned_close(desktop, pid, hwnd):
    """Deliver the system title-bar Close command to this Job's visible, exact ArchHub HWND."""
    if pid not in desktop.job.pids() or (pid, "ArchHub", hwnd) not in desktop.windows(with_handles=True):
        raise RuntimeError("The installed ArchHub HWND is no longer visible on the owned hidden desktop")
    post = desktop.u32.PostMessageW
    post.argtypes = (w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    post.restype = w.BOOL
    wm_syscommand, sc_close = 0x0112, 0xF060
    requested = time.monotonic_ns()
    if not post(hwnd, wm_syscommand, sc_close, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"event": "window_request_close", "pid": pid, "hwnd": hwnd,
            "monotonic_ns": requested, "action": "WM_SYSCOMMAND/SC_CLOSE"}


def run_native_actions(desktop, owner, writer, deadline, settle_seconds, readbacks, commands):
    """Run the existing Qt window and tray actions without waiting for Studio JavaScript."""
    listener = owner["listener_pid"]
    ready_by = min(deadline, writer.receipt["acquired_ns"] / 1_000_000_000 + writer.budget)
    while (remaining := ready_by - time.monotonic()) > 0:
        trace = events(writer.trace_path, listener)
        ready = next((row for row in trace if row["event"] == "native_window_ready"), None)
        contended = any(row["event"] == "recent_writer_contended" for row in trace)
        window_revision = next((row for row in reversed(trace)
                                if row["event"] in ("native_window_ready", "native_hwnd_changed")), None)
        if ready and contended and window_revision["hwnd"]:
            hwnd = window_revision["hwnd"]
            if (listener, "ArchHub", hwnd) in desktop.windows(with_handles=True):
                break
        time.sleep(min(remaining, writer.poll))
    else:
        raise RuntimeError("The Job-owned native window and real warm-up contention were not both available before the writer bound")

    tray = any(row["event"] == "tray_setup" for row in trace)
    if tray and not ready["tray_quit_available"]:
        raise RuntimeError("The installed tray does not expose one visible, enabled Quit ArchHub action")
    before = window_state(desktop, owner, "before", tray, deadline, settle_seconds, writer.poll)
    readbacks["before"] = before
    if not before["listener_http_204"] or {"pid": listener, "hwnd": hwnd} not in before["visible_windows"]:
        raise RuntimeError("The installed visible HWND and healthy listener do not share the admitted owner PID")

    commands.append(post_owned_close(desktop, listener, hwnd))
    closed = window_state(desktop, owner, "close", tray, deadline, settle_seconds, writer.poll)
    readbacks["close"] = closed
    if closed["visible_windows"]:
        raise RuntimeError("The native Close request did not hide or close the owned window")
    if tray:
        get_pid = desktop.u32.GetWindowThreadProcessId
        get_pid.argtypes = (w.HWND, ctypes.POINTER(w.DWORD))
        get_pid.restype = w.DWORD
        hidden_pid = w.DWORD()
        get_pid(hwnd, ctypes.byref(hidden_pid))
        closed.update(closed_hwnd=hwnd, closed_hwnd_pid=hidden_pid.value)
        if hidden_pid.value != listener:
            raise RuntimeError("Normal Close did not preserve the selected ArchHub HWND on the admitted PID")
        if not closed["listener_owned"] or not closed["listener_http_204"]:
            raise RuntimeError("Normal Close did not retain the admitted listener for the tray action")
        native_quit_request(writer.trace_path).touch(exist_ok=False)
        readbacks["quit"] = window_state(desktop, owner, "quit", tray, deadline, settle_seconds, writer.poll)


def observed_overlap(by_name, event):
    start, finish, observed = (by_name.get(name) for name in ("warm_call", "warm_return", event))
    if start is None or finish is None or observed is None or not start < finish:
        return "NOT EXERCISED"
    return "PASS" if start <= observed < finish else "NOT EXERCISED"


def verdict(trace, readbacks, marker_present, writer=None):
    before, closed, quit = (readbacks.get(phase, {}) for phase in ("before", "close", "quit"))
    by_name = {}
    for row in trace:
        by_name.setdefault(row["event"], row["monotonic_ns"])
    tray = "tray_setup" in by_name
    ended = quit if tray else closed
    sequence = [before.get("monotonic_ns"), by_name.get("window_request_close"), by_name.get("window_close")]
    if tray:
        sequence.extend((closed.get("monotonic_ns"), by_name.get("window_request_quit"), by_name.get("tray_quit_entered")))
    sequence.extend((by_name.get("server_close_call"), by_name.get("server_close_return"), ended.get("monotonic_ns")))
    ordered = None not in sequence and all(left < right for left, right in zip(sequence, sequence[1:]))
    native = (ordered and before.get("visible_window_pids") and before.get("listener_http_204")
              and closed and not closed.get("visible_window_pids")
              and (not tray or (closed.get("listener_owned") and closed.get("listener_http_204")))
              and ended and not ended.get("job_app_pids") and ended.get("port_refused")
              and not marker_present)
    close_overlap = observed_overlap(by_name, "window_close")
    teardown_overlap = observed_overlap(by_name, "server_close_call")
    contention_order = (by_name.get("warm_call"), by_name.get("recent_writer_contended"),
                        by_name.get("window_close"), by_name.get("server_close_call"),
                        (writer or {}).get("release_started_ns"), by_name.get("recent_writer_resumed"),
                        by_name.get("warm_return"))
    contended_shutdown = (writer is not None and writer.get("release") == "observed server_close_call"
                          and writer.get("released_ns") is not None
                          and None not in contention_order
                          and writer["acquired_ns"] < contention_order[1]
                          and all(left < right for left, right in zip(contention_order, contention_order[1:])))
    if not native:
        result, reason = "FAIL", "The ordered native Close and clean listener/process shutdown were not both verified."
    elif writer is not None and not contended_shutdown:
        result, reason = "NOT EXERCISED", "The real warm-up worker did not prove the recent-session writer contention through shutdown."
    elif close_overlap == "PASS" and teardown_overlap == "PASS":
        result, reason = "PASS", "The actual installed worker was in flight at both native Close and server shutdown."
    else:
        result, reason = "NOT EXERCISED", "Both native Close and server shutdown must overlap the actual worker."
    return {"result": result, "reason": reason, "native_close_and_shutdown": bool(native),
            "studio_navigation_finished_ns": by_name.get("studio_navigation_finished"),
            "window_close_overlap": close_overlap, "server_shutdown_overlap": teardown_overlap,
            "tray_path_observed": tray, "state_marker_present_after_shutdown": marker_present,
            "recent_writer": writer, "recent_writer_contended_shutdown": contended_shutdown,
            "events": trace, "readbacks": readbacks}
