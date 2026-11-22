"""Observe, without gating, the installed NoGraph worker and Qt window lifecycle."""
import ast
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


def watch_window_close(window, record):
    from PyQt6.QtCore import QEvent, QObject

    class CloseObserver(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Close:
                record("window_close")
            return False

    observer = CloseObserver(window)
    window.installEventFilter(observer)
    return observer


def observe_worker(trace_path):
    """Trace entry/return of the installed methods without controlling their execution."""
    receipt = Path(trace_path)
    pid = os.getpid()
    observers = []
    contended = False
    resumed = False
    owner = recent_owner(receipt.parent)

    def record(observed):
        with receipt.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": observed, "pid": pid, "monotonic_ns": time.monotonic_ns()}) + "\n")

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
            observers.append(watch_window_close(frame.f_locals["window"], record))
        elif event == "call":
            if name == "CloseToTray.__init__":
                observed = "tray_setup"
            elif name == "WindowCommands.perform":
                action = frame.f_locals.get("action")
                if action in ("close", "quit"):
                    observed = "window_request_" + action
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


def window_state(desktop, owner, probe_pid, phase, tray, deadline, settle_seconds, poll_seconds):
    import psutil

    endpoint = urlsplit(owner["endpoint"])
    address = (endpoint.hostname, endpoint.port)
    listener = owner["listener_pid"]
    while True:
        pids = sorted(set(desktop.job.pids()) - {probe_pid})
        windows = [pid for pid, title in desktop.windows() if pid in pids and title == "ArchHub"]
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
            "tray_setup": tray, "visible_window_pids": windows, "job_app_pids": pids, "port_reachable": connected,
            "listener_owned": owned, "listener_http_204": healthy, "port_refused": network_error == "ConnectionRefusedError",
            "ownership_error": ownership_error, "network_error": network_error, "monotonic_ns": time.monotonic_ns()}


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
        sequence.extend((closed.get("monotonic_ns"), by_name.get("window_request_quit")))
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
            "window_close_overlap": close_overlap, "server_shutdown_overlap": teardown_overlap,
            "tray_path_observed": tray, "state_marker_present_after_shutdown": marker_present,
            "recent_writer": writer, "recent_writer_contended_shutdown": contended_shutdown,
            "events": trace, "readbacks": readbacks}
