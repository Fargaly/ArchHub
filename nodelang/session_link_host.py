"""Private, bounded IPC from an existing authenticated client to Session Link.

No enrollment, daemon or credential persistence. Child stdout is protocol data,
never diagnostic output; only explicitly selected result fields leave here.
"""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


_LIMIT = 65536
_STATUSES = {"attached", "not_attached", "ok", "detached", "uncertain",
             "not_sent", "cancelled_wait"}
_STAGES = {"scope", "delegate", "attach", "detach", "host_ipc"}
_REASONS = {"invalid_lifetime", "invalid_connection", "scope_mismatch", "scope_unavailable",
    "delegation_result_invalid", "application_refused", "attachment_result_invalid",
    "handoff_unconfirmed", "detach_unconfirmed", "host_deadline", "client_protocol_error",
    "duplicate_host_request", "invalid_operation", "host_failure", "input_limit",
    "invalid_frame", "parent_disconnected"}
_ERROR_CODES = {"owner_changed", "session_expired", "session_unknown", "transport_failed",
                "client_failed", "protocol_failed"}


def _client_error(exc):
    from .application_machine_transport import MachineTransportError
    # Compare exact fixed messages, never return arbitrary exception text.
    return {"universal runtime owner changed; reconnect through admitted enrollment":"owner_changed",
        "runtime Agent Session capability expired":"session_expired",
        "runtime Agent Session is unknown":"session_unknown"}.get(str(exc),
        "transport_failed" if isinstance(exc, MachineTransportError) else "client_failed")


def _result(value):
    if type(value) is not dict or value.get("status") not in _STATUSES:
        raise ValueError("invalid private host result")
    clean = {"status": value["status"]}
    for key, allowed in (("stage", _STAGES), ("reason", _REASONS), ("error_code", _ERROR_CODES)):
        if type(value.get(key)) is str and value[key] in allowed:
            clean[key] = value[key]
    for key in ("attached", "detached", "revoked", "worker_stopped",
                "local_call_joined", "external_cancelled"):
        if type(value.get(key)) is bool:
            clean[key] = value[key]
    # Do not propagate arbitrary strings, including errors or added token fields.
    instance = value.get("instance_id")
    if type(instance) is str and len(instance) == 64 and all(c in "0123456789abcdef" for c in instance):
        clean["instance_id"] = instance
    expiry = value.get("expires_at")
    if type(expiry) in (int, float) and math.isfinite(expiry):
        clean["expires_at"] = expiry
    return clean


def run_host_handoff(client, *, node_executable, state_directory,
                     operation, connection=None, ttl_seconds=300):
    """Use the caller's bound client; capture and dispose of all private frames.

    Caller holds its identity/generation guard throughout this operation. The
    three client methods retain their own finite machine-response deadlines.
    An uncertain result never triggers a retry or another enrollment.
    """
    if operation not in {"attach", "detach"}:
        raise ValueError("invalid host operation")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
        raise ValueError("invalid host lifetime")
    node = Path(node_executable).resolve(strict=True)
    state = Path(state_directory).resolve(strict=True)
    if not node.is_file() or not state.is_dir():
        raise ValueError("existing host runtime and state directory required")
    worker = Path(__file__).with_name("session_link") / "host-worker.mjs"
    request = {"operation": operation}
    if operation == "attach":
        if type(connection) is not dict:
            raise ValueError("exact host connection required")
        request.update(connection=connection, ttl_seconds=ttl_seconds)
    def encode(value):
        data = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
        if len(data) > _LIMIT:
            raise ValueError("private host frame too large")
        return data
    initial = encode(request)
    env = dict(os.environ)
    env.update(SESSION_LINK_PRIVATE_HOST_IPC="1", SESSION_LINK_STATE_DIR=str(state))
    frames = queue.Queue(maxsize=4)
    stopped = threading.Event()
    process = subprocess.Popen([str(node), str(worker)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, bufsize=0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    def read_frames():
        try:
            while not stopped.is_set():
                line = process.stdout.readline(_LIMIT + 1)
                if not line or len(line) > _LIMIT or not line.endswith(b"\n"):
                    frames.put_nowait(None)
                    return
                frames.put_nowait(line)
        except (OSError, ValueError, queue.Full):
            stopped.set()
    reader = threading.Thread(target=read_frames, name="session-link-host-stdio", daemon=True)
    reader.start()
    deadline = time.monotonic() + 115
    writers = []
    def send(data):
        finished = threading.Event()
        failed = threading.Event()
        def write_frame():
            try:
                remaining = memoryview(data)
                while remaining:
                    count = process.stdin.write(remaining)
                    if not count:
                        raise OSError("private pipe closed")
                    remaining = remaining[count:]
            except (OSError, ValueError):
                failed.set()
            finally:
                finished.set()
        writer = threading.Thread(target=write_frame, name="session-link-host-write", daemon=True)
        writers.append(writer)
        writer.start()
        if not finished.wait(max(0, deadline - time.monotonic())) or failed.is_set():
            raise OSError("private host write unconfirmed")
    expected = ["session_link_scope", "attach_session_link"] if operation == "attach" else ["detach_session_link"]
    failure = None
    try:
        send(initial)
        calls = 0
        while not stopped.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = frames.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if raw is None:
                break
            frame = json.loads(raw)
            raw = None
            if type(frame) is not dict:
                break
            if frame.get("event") == "result":
                result = _result(frame.get("result"))
                if failure:
                    result.update(failure)
                return result
            if (frame.get("event") != "client_call" or calls >= len(expected)
                    or type(frame.get("id")) is not int or frame["id"] != calls + 1
                    or frame.get("method") != expected[calls]):
                break
            method = expected[calls]
            args = frame.get("args")
            if (type(args) is not list or len(args) != (1 if method == "attach_session_link" else 0)
                    or args and type(args[0]) is not dict):
                break
            calls += 1
            response = {"event": "client_result", "id": calls, "ok": False}
            try:
                response.update(ok=True, result=getattr(client, method)(*args))
            except Exception as exc:
                # Raw exceptions can contain authenticated request data.
                failure = {"stage":{"session_link_scope":"scope", "attach_session_link":"attach",
                    "detach_session_link":"detach"}[method], "error_code":_client_error(exc)}
            finally:
                frame = args = None
            send(encode(response))
            response = None
    except (OSError, ValueError, TypeError):
        pass
    finally:
        stopped.set()
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for writer in writers:
            writer.join(timeout=1)
        try:
            process.stdin.close()
        except OSError:
            pass
        reader.join(timeout=5)
        try:
            process.stdout.close()
        except OSError:
            pass
    return {"status": "uncertain", **(failure or {"stage":"host_ipc", "error_code":"protocol_failed"})}
