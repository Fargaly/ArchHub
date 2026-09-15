"""Reused Session Link native transport; no Workshop authority or message store.

The caller admits the effect and persists its outcome in the existing application.
Discovery is routing evidence, not enrollment or proof of Work ownership. A reply
is not execution/completion evidence. There is no retry, service, or model spawn.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid


def public_delivery_reason(value):
    """Bound only the reported reason; never expose a raw receipt envelope."""
    import re
    text=''.join(' ' if ord(c)<32 or ord(c)==127 else c for c in value).strip()[:512] if type(value) is str else ''
    if re.search(r"(?:uds:|\\\\[.?]\\pipe\\|[\"']?(?:token|authorization)[\"']?\s*[:=]|bearer\s)",text,re.I):
        return 'Recipient reason contained private transport details and was omitted.'
    return text


class _OwnedProcessJob:
    """Windows job closes owned helper descendants; existing host apps are outside."""
    def __init__(self, process):
        self.handle = None
        self._lock = threading.Lock()
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.api, self.handle = api, handle
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not api.AssignProcessToJobObject(handle, int(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def close(self):
        with self._lock:
            if self.handle is not None:
                self.api.CloseHandle(self.handle)
                self.handle = None


class SessionLinkTransport:
    """One bounded owned worker at a time; external host agents are never killed."""

    def __init__(self, node_executable=None, state_dir=None, env=None):
        self._assets = Path(__file__).resolve().parent / "session_link"
        if node_executable is None and getattr(sys, "frozen", False):
            node_executable = Path(sys._MEIPASS) / "runtime" / "node.exe"
        if node_executable is None:
            raise ValueError("an explicit admitted Node executable is required")
        self._node = Path(node_executable)
        if not self._node.is_absolute() or not self._node.is_file():
            raise ValueError("the admitted Node executable is unavailable")
        if state_dir is None or not Path(state_dir).is_absolute():
            raise ValueError("an absolute disposable state directory is required")
        self._state = Path(state_dir).resolve()
        code_root = Path(sys._MEIPASS).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        if self._state.is_relative_to(code_root):
            raise ValueError("transport state must be outside installed code")
        self._env = dict(os.environ)
        self._env.update(env or {})
        self._env["SESSION_LINK_STATE_DIR"] = str(self._state)
        self._env["SESSION_LINK_NODE"] = str(self._node)
        self._closed = threading.Event()
        self._busy = threading.Lock()
        self._lifecycle = threading.Lock()
        self._processes = set()
        self._jobs = {}
        self._attachment = None
        self._pending_cancel = None
        self._cancelling = 0

    def create_channel(self):
        """Same implementation/state, fresh unattached lifetime, no worker."""
        with self._lifecycle:
            if self._closed.is_set():
                raise ValueError("transport closed")
            environment = {**self._env, "CODEX_APP_TOOLS_PIPE_PATH": "", "CODEX_THREAD_ID": ""}
            return type(self)(node_executable=self._node, state_dir=self._state, env=environment)

    def cancel_pending(self, timeout_seconds=8):
        """Stop/join local work while keeping the channel open for detach.

        Caller first stops admitting new work. No external task cancellation or
        grant revocation is implied; a bounded join can remain uncertain.
        """
        budget = self._budget(timeout_seconds)
        with self._lifecycle:
            self._cancelling += 1
            pending = self._pending_cancel
            if pending is not None:
                pending.set()
        joined = False
        try:
            joined = self._busy.acquire(timeout=budget)
            return {"status": "ok" if joined else "uncertain", "worker_stopped": joined,
                    "local_call_joined": joined, "cancel_requested": pending is not None,
                    "external_cancelled": False}
        finally:
            if joined:
                self._busy.release()
            with self._lifecycle:
                self._cancelling -= 1

    def attach_host(self, capability, *, instance_id, destination):
        """Bind a capability delivered by the authenticated instance lifecycle.

        This checks routing scope, not enrollment. Never serialize/log capability.
        Replacing an attachment requires detach first; expiry cannot renew itself.
        """
        required = ("control", "token", "connection_id", "connection_generation",
                    "instance_id", "destination")
        if (type(capability) is not dict
                or any(type(capability.get(k)) is not str or not capability[k] for k in required)
                or capability["instance_id"] != instance_id
                or capability["destination"] != destination
                or not capability["control"].startswith("\\\\.\\pipe\\LOCAL\\session-link-")
                or len(capability["token"]) != 64
                or type(capability.get("expires_at")) not in (int, float)
                or not 0 < capability["expires_at"] - time.time()*1000 <= 900000):
            raise ValueError("invalid or expired scoped attachment")
        if not self._busy.acquire(blocking=False):
            raise ValueError("transport busy; attachment cannot change during a call")
        try:
            with self._lifecycle:
                if self._closed.is_set() or self._attachment is not None:
                    raise ValueError("transport closed or already attached")
                self._attachment = {k: capability[k] for k in (*required, "expires_at")}
        finally:
            self._busy.release()

    def detach_host(self):
        """Revoke the grant through its exact connection; no retry on uncertainty."""
        if self._attachment is None:
            return {"status": "ok", "revoked": False}
        result = self._call({"operation": "detach"}, 5, None)
        if result.get("status") == "ok":
            self._attachment = None
        return result

    @staticmethod
    def _cancel_worker(proc):
        def send():
            try:
                proc.stdin.write(b'{"operation":"cancel"}\n')
                proc.stdin.flush()
            except (OSError, ValueError):
                pass
        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _budget(value):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 < value <= 210):
            raise ValueError("timeout must be finite and within (0, 210] seconds")
        return float(value)

    def discover(self, timeout_seconds=20, *, apps=None):
        """Return exact host descriptors; an unavailable provider is not invented."""
        payload={"operation":"discover"}
        if apps is not None:
            if (type(apps) not in (tuple,list) or not 1 <= len(apps) <= 5
                    or any(app not in {"claude","codex","opencode","antigravity","antigravity-ide"} for app in apps)):
                raise ValueError("Invalid discovery app scope")
            payload["apps"]=list(dict.fromkeys(apps))
        return self._call(payload, self._budget(timeout_seconds), None)

    def request(self, recipient, text, timeout_seconds=180, cancel_event=None,
                *, permission_mode="prompting"):
        """Request a reply from an exact discovered recipient, rechecked by worker.

        cancelled_wait means local waiting stopped, never recipient cancellation.
        uncertain means do not resend before reconciling the external outcome.
        permission_mode is trusted caller policy, never a recipient gate override.
        """
        budget = self._budget(timeout_seconds)
        if (type(recipient) is not dict or recipient.get("app") not in
                {"claude", "codex", "opencode", "antigravity", "antigravity-ide"}
                or type(recipient.get("id")) is not str or not recipient["id"]):
            return {"status": "not_sent", "reason": "invalid_recipient"}
        if type(text) is not str or not text.strip() or len(text) > 32000:
            return {"status": "not_sent", "reason": "invalid_text"}
        if permission_mode not in {"prompting", "bypass"}:
            return {"status": "not_sent", "reason": "invalid_permission_mode"}
        if self._attachment is not None and permission_mode != "prompting":
            return {"status": "not_sent", "reason": "attachment_requires_prompting"}
        return self._call({"operation": "request", "recipient": dict(recipient),
                           "text": text, "permission_mode": permission_mode}, budget, cancel_event)

    def _call(self, payload, budget, cancel_event):
        request_id = str(uuid.uuid4())
        base = {"request_id": request_id, "external_cancelled": False,
                "work_authority": False, "execution_verified": False}
        if self._closed.is_set():
            return {**base, "status": "not_sent", "reason": "transport_closed"}
        if cancel_event is not None and cancel_event.is_set():
            return {**base, "status": "not_sent", "reason": "cancelled_before_start"}
        if not self._busy.acquire(blocking=False):
            return {**base, "status": "not_sent", "reason": "transport_busy"}
        with self._lifecycle:
            if self._closed.is_set() or self._cancelling:
                self._busy.release()
                return {**base, "status": "not_sent", "reason": "transport_stopping"}
            if self._attachment is not None:
                if payload.get("permission_mode", "prompting") != "prompting":
                    self._busy.release()
                    return {**base, "status": "not_sent", "reason": "attachment_requires_prompting"}
                payload = {**payload, "attachment": dict(self._attachment)}
            local_cancel = threading.Event()
            self._pending_cancel = local_cancel
        proc = None
        job = None
        input_written = False
        readers = []
        deadline = time.monotonic() + budget
        output, errors = bytearray(), bytearray()
        overflow = threading.Event()
        try:
            raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
            if len(raw) > 262144:
                return {**base, "status": "not_sent", "reason": "input_limit"}
            self._state.mkdir(parents=True, exist_ok=True)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                [str(self._node), "--max-old-space-size=96", str(self._assets / "worker.mjs")],
                cwd=self._state, env=self._env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
            job = _OwnedProcessJob(proc)
            with self._lifecycle:
                self._processes.add(proc)
                self._jobs[proc] = job

            def drain(stream, target, limit):
                while True:
                    try:
                        chunk = stream.read1(4096)
                    except (OSError, ValueError):
                        return
                    if not chunk:
                        return
                    if len(target) + len(chunk) > limit:
                        overflow.set()
                        return
                    target.extend(chunk)

            for stream, target, limit in [(proc.stdout, output, 1048576), (proc.stderr, errors, 65536)]:
                thread = threading.Thread(target=drain, args=(stream, target, limit), daemon=True)
                thread.start()
                readers.append(thread)
            if self._closed.is_set() or local_cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                return {**base, "status": "not_sent", "reason": "cancelled_before_input"}
            if proc.poll() is not None:
                return {**base, "status": "not_sent", "reason": "worker_exited_before_input"}
            input_written = True
            write_failed = threading.Event()
            def write_request():
                try:
                    proc.stdin.write(raw)
                    proc.stdin.flush()
                except (OSError, ValueError):
                    write_failed.set()
            writer = threading.Thread(target=write_request, daemon=True)
            writer.start()
            readers.append(writer)
            stop_reason = None
            while proc.poll() is None:
                if self._closed.is_set() or local_cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                    stop_reason = "cancelled_wait"
                elif overflow.is_set():
                    stop_reason = "output_limit"
                elif write_failed.is_set():
                    stop_reason = "worker_failure"
                elif time.monotonic() >= deadline:
                    stop_reason = "timeout"
                if stop_reason:
                    if payload['operation']=='discover':
                        # No native message was sent. Close this one owned helper
                        # tree immediately; a blocked inventory must not add grace time.
                        job.close()
                        if proc.poll() is None:proc.kill()
                        break
                    try:
                        readers.append(self._cancel_worker(proc))
                        proc.wait(timeout=2)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        proc.kill()
                    break
                time.sleep(min(.05, max(.001, deadline-time.monotonic())))
            proc.wait(timeout=3)
            for thread in readers:
                thread.join(timeout=1)
            if stop_reason:
                if stop_reason=='timeout' and payload['operation']=='discover':
                    try:
                        # A killed writer may leave an incomplete final line.
                        frames=[json.loads(line) for line in bytes(output).split(b'\n')[:-1]]
                        snapshots=[row for row in frames if type(row) is dict and row.get('event')=='discovery_snapshot']
                        if snapshots:
                            partial=snapshots[-1]
                            if (partial.get('status')!='ok' or type(partial.get('recipients')) is not list
                                    or len(partial['recipients'])>128 or type(partial.get('complete_apps')) is not list):
                                raise ValueError('invalid partial discovery')
                            return {**partial,**base,'event':'result','status':'ok','partial':True,
                                    'reason':'discovery_budget','worker_stopped':proc.poll() is not None}
                    except (ValueError,UnicodeError,TypeError):pass
                return {**base, "status": "cancelled_wait" if stop_reason == "cancelled_wait" else "uncertain",
                        "reason": stop_reason, "worker_stopped": proc.poll() is not None}
            try:
                frames = [json.loads(line) for line in output.decode("utf8").splitlines()]
                results = [r for r in frames if isinstance(r, dict) and r.get("event") == "result"]
                if len(results) != 1 or results[0].get("status") not in {
                        "ok", "replied", "held", "not_sent", "uncertain", "cancelled_wait"}:
                    raise ValueError("bad result")
                result = results[0]
                if result['status']=='held':
                    code=result.get('delivery_status')
                    result={'event':'result','status':'held',
                        'dispatch_attempted':result.get('dispatch_attempted') is True,
                        'delivery_status':code if code in {'held','refused','rejected','denied','expired','dropped'} else 'held',
                        'delivery_reason':public_delivery_reason(result.get('delivery_reason'))}
                if payload["operation"] == "request" and result["status"] == "replied":
                    if result.get("recipient") != payload["recipient"] or not isinstance(result.get("reply", {}).get("text"), str):
                        raise ValueError("reply recipient mismatch")
                return {**result, **base, "worker_stopped": True}
            except (ValueError, UnicodeError, TypeError):
                return {**base, "status": "uncertain", "reason": "invalid_worker_result", "worker_stopped": True}
        except (OSError, ValueError, subprocess.SubprocessError):
            return {**base, "status": "uncertain" if input_written else "not_sent", "reason": "worker_failure"}
        finally:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=3)
                if job is not None:
                    job.close()
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        # Killing a nonreading worker can leave buffered input
                        # that fails to flush when its pipe is closed.
                        pass
                for thread in readers:
                    thread.join(timeout=1)
                with self._lifecycle:
                    self._processes.discard(proc)
                    self._jobs.pop(proc, None)
            with self._lifecycle:
                self._pending_cancel = None
            self._busy.release()

    def close(self):
        self._closed.set()
        with self._lifecycle:
            processes = tuple((proc, self._jobs.get(proc)) for proc in self._processes)
        for proc, job in processes:
            waiter = self._cancel_worker(proc)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            finally:
                if job is not None:
                    job.close()
                waiter.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
