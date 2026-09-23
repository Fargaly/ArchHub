"""Authenticated local transport into the one Universal Cell graph owner.

The pipe is only a physical boundary adapter.  It carries bounded JSON and
binds every request to a running application instance; it does not persist
domain state or own a CellStore.  The application dispatcher remains
responsible for resolving graph-declared routes, authorization, and mutation.
"""
from __future__ import annotations

from collections import deque
from contextvars import ContextVar
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import threading
import time
from typing import Callable, Mapping, Protocol

from .cell_secret_keys import SigningKeyMaterial, SigningKeyProvider
from .cell_revision_checkpoint import RevisionCheckpointGuard
from .cell_signing_authority import (
    project_signing_authority_protocol,
    read_signing_key_descriptor,
    verify_signature_envelope,
    verify_signing_key_descriptor,
)
from .checkpoint_authority_provisioning import (
    default_checkpoint_authority_path,
    default_checkpoint_key_name,
)
from .runtime_gateway import BackendGeneration
from .universal_cell import (
    ReadOnlyJournalError,
    inspect_read_only_cell_journal,
    load_bounded_read_only_cell_snapshot,
    read_only_revision_chain_digest,
)
from .windows_cng_signing_provider import WindowsCngSigningAuthorityProvider


_FORMAT = "archhub.universal-runtime"
_FORMAT_VERSION = 1
_MAX_MESSAGE_BYTES = 256 * 1024
_MAX_CHECKPOINT_AUTHORITY_REVISIONS = 10_000
_MAX_CHECKPOINT_AUTHORITY_CELLS = 500_000
_MAX_CHECKPOINT_REVISION_CELLS = 10_000_000
_REQUEST_ID = re.compile(r"^[A-Fa-f0-9]{32}$")
def _default_machine_response_timeout(method: str, path: str) -> float:
    """Bound long graph receipts without stalling every machine request."""
    route = (method.upper(), path)
    if route == ("POST", "/api/universal/work-court"):
        return 660.0
    if route == ("POST", "/api/universal/agent-session"):
        return 240.0
    return 180.0


_RUNTIME_ID = re.compile(r"^[A-Fa-f0-9]{32}$")
_NULL_CELL_ID = "00000000-0000-0000-0000-000000000000"
BABOOM_NATIVE_FRAME_PROJECTION = "app:baboom-native-frame:v2"
BABOOM_NATIVE_REPORT_KIND = "steward-briefing"
BABOOM_NATIVE_REPORT_SUMMARY = (
    "Founder-local Work, Workshop, and attention briefing."
)


class MachineTransportError(RuntimeError):
    """The runtime descriptor, pipe authentication, or request is invalid."""


class MachineResponseError(MachineTransportError):
    """An authenticated bound error response arrived; effects remain unknown."""
    response_received = True


class MachineContinuationNotEnrolled(MachineTransportError):
    """Exact owner-held refusal receipt proves this continuation issued no capability."""


class MachineEffectOutcomeUnknown(MachineTransportError):
    """A route failed after durable changes; its response is not a refusal proof."""


@dataclass(frozen=True, slots=True)
class MachinePipePeer:
    """Owner-local OS observation; never a request field or graph permission."""
    pid: int
    created_at: float
    executable: str = ""
    argv: tuple[str, ...] = ()
    cwd: str = ""


def _observe_machine_process(pid):
    """OS observation only; never accept process metadata from the request."""
    try:
        import psutil
    except ImportError:
        # Launch metadata is optional for the minimal OS pipe-peer identity.
        # Browser/desktop admission still requires a complete observation.
        return None
    try:
        process = psutil.Process(pid)
        created = process.create_time()
        argv = tuple(process.cmdline())
        if (not argv or len(argv) > 128 or any(type(arg) is not str for arg in argv)
                or sum(len(arg) for arg in argv) > 16384):
            return None
        peer = MachinePipePeer(pid, created, str(Path(process.exe()).resolve()),
                               argv, str(Path(process.cwd()).resolve()))
        if psutil.Process(pid).create_time() != created:
            return None
        return peer
    except (psutil.Error, OSError, ValueError):
        return None


def _desktop_launch_is_admitted(peer, *, product_root=None, python_executable=None):
    """Trusted launch shape, not a human-gesture or same-user isolation proof."""
    if (type(peer) is not MachinePipePeer or not peer.executable or not peer.argv or not peer.cwd
            or type(peer.argv) is not tuple or any(type(arg) is not str for arg in peer.argv)):
        return False
    root = Path(product_root) if product_root is not None else (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1])
    def canonical(path):
        return os.path.normcase(str(Path(path).resolve()))
    executable = canonical(peer.executable)
    args = peer.argv[1:]
    if executable == canonical(root / "ArchHub.exe"):
        return args == ("--desktop-worker",)
    python = python_executable if python_executable is not None else sys.executable
    trusted_python = {canonical(root / ".venv/Scripts/python.exe"),
                      canonical(root / ".venv/Scripts/pythonw.exe")}
    interpreter_paths = [Path(python)]
    if python_executable is None:
        interpreter_paths.append(Path(getattr(sys, "_base_executable", sys.executable)))
    for interpreter in interpreter_paths:
        if interpreter.name.casefold() in {"python.exe", "pythonw.exe"}:
            # Windows venv redirectors can report the base interpreter image
            # while argv[0] names the venv. Never trust argv[0] as image proof.
            trusted_python.update(canonical(interpreter.with_name(name))
                                  for name in ("python.exe", "pythonw.exe"))
        elif interpreter.name.casefold() in {"python", "python3"}:
            trusted_python.add(canonical(interpreter))
    if executable not in trusted_python:
        return False
    if len(args) == 1 and Path(args[0]).is_absolute():
        return canonical(args[0]) == canonical(root / "launch_archhub_test.py")
    if len(args) == 3 and args[:2] == ("-E", "-s") and Path(args[2]).is_absolute():
        # Exact installed VBS launch. Forwarded Qt/plugin or Python options are
        # not application arguments and do not gain Desktop mint authority.
        return canonical(args[2]) == canonical(root / "launch_archhub_test.py")
    return args == ("-m", "nodelang.desktop") and canonical(peer.cwd) == canonical(root)


def desktop_pipe_peer_is_current(peer):
    if type(peer) is not MachinePipePeer or not _desktop_launch_is_admitted(peer):
        return False
    return _observe_machine_process(peer.pid) == peer


def current_process_is_desktop_launch():
    peer = _observe_machine_process(os.getpid())
    return peer is not None and desktop_pipe_peer_is_current(peer)


def peer_matches_process(peer, pid, created_at):
    """Compare owner-local enrollment metadata with a retained OS identity.

    This checks identity only, not liveness or descendant custody. Callers must
    establish both separately. The absolute 10-microsecond allowance covers
    binary64 FILETIME epoch-conversion rounding; it is not a relative tolerance
    or permission lifetime. Malformed or unsupported timestamps fail closed.
    """
    if (type(peer) is not dict or set(peer) != {"pid", "created_at"}
            or type(pid) is not int or not 0 < pid <= 0xffffffff
            or type(peer["pid"]) is not int or peer["pid"] != pid):
        return False
    observed = peer["created_at"]
    # Bound before arithmetic/conversion, also excluding bool, NaN and infinity.
    if any(type(value) not in (int, float) or not 0 < value < 2 ** 32
           for value in (observed, created_at)):
        return False
    return abs(observed - created_at) <= 0.00001


_VERIFIED_PIPE_PEER = ContextVar("verified_machine_pipe_peer", default=None)


def _verified_machine_pipe_peer(request):
    held = _VERIFIED_PIPE_PEER.get()
    if held is None or held[0] is not request:
        return None
    return held[1]


def _read_windows_pipe_peer(connection):
    """Observe the accepted endpoint, retaining no process handle or credential.

    Unsupported/denied observations remain absent for legacy requests. An
    app-owned launcher must require this evidence and match its own retained
    descendant identity; a UUID lookup alone is not physical custody.
    """
    if os.name != "nt":
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    peer_pid = kernel.GetNamedPipeClientProcessId
    peer_pid.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    peer_pid.restype = wintypes.BOOL
    open_process = kernel.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    process_times = kernel.GetProcessTimes
    process_times.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
    process_times.restype = wintypes.BOOL
    wait = kernel.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait.restype = wintypes.DWORD
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = None
    try:
        pipe = connection.fileno()
        pid = wintypes.ULONG()
        if not peer_pid(pipe, ctypes.byref(pid)) or pid.value <= 0:
            return None
        # QUERY_LIMITED_INFORMATION and SYNCHRONIZE; no mutation rights.
        handle = open_process(0x00101000, False, pid.value)
        if not handle:
            return None
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not process_times(handle, ctypes.byref(created), ctypes.byref(exited),
                             ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        created_at = (ticks - 116444736000000000) / 10000000.0
        repeated = wintypes.ULONG()
        if (created_at <= 0 or created_at > time.time()
                or wait(handle, 0) != 258
                or not peer_pid(pipe, ctypes.byref(repeated)) or repeated.value != pid.value):
            return None
        observed = _observe_machine_process(pid.value)
        if (observed is not None and peer_matches_process(
                {"pid": pid.value, "created_at": created_at}, observed.pid, observed.created_at)):
            return observed
        # Other machine operations still use the existing minimal PID custody;
        # founder browser minting requires complete launch metadata below.
        return MachinePipePeer(pid.value, created_at)
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    finally:
        if handle:
            close(handle)


def validate_baboom_native_frame_payload(
    payload: object,
    *,
    now: float | None = None,
) -> dict[str, object]:
    """Validate one expiring, revision-coherent BABOOM projection frame."""
    if type(payload) is not dict:
        raise MachineTransportError("BABOOM native frame response is invalid")
    result = payload
    context = result.get("context")
    directive = result.get("directive")
    report = result.get("report")
    revision = result.get("revision")
    issued_at = result.get("issued_at")
    expires_at = result.get("expires_at")
    if (
        set(result) != {
            "projection", "revision", "issued_at", "expires_at",
            "context", "directive", "report",
        }
        or result.get("projection") != BABOOM_NATIVE_FRAME_PROJECTION
        or type(revision) is not int
        or revision < 0
        or type(issued_at) not in (int, float)
        or type(expires_at) not in (int, float)
        or not isinstance(context, dict)
        or not isinstance(directive, dict)
        or context.get("revision") != revision
        or directive.get("revision") != revision
    ):
        raise MachineTransportError("BABOOM native frame response is invalid")
    issued = float(issued_at)
    expires = float(expires_at)
    current = time.time() if now is None else float(now)
    ttl = directive.get("ttl_seconds")
    action = directive.get("action")
    if (
        not issued == issued
        or not expires == expires
        or not current == current
        or type(ttl) not in (int, float)
        or not 0.0 < float(ttl) <= 60.0
        or not issued < expires
        or expires - issued > float(ttl) + 0.001
        or current >= expires
        or type(action) is not str
    ):
        raise MachineTransportError("BABOOM native frame lease is invalid")
    if not action:
        if report is not None:
            raise MachineTransportError(
                "quiet BABOOM native frame must not carry a report"
            )
        return result
    if type(report) is not dict:
        raise MachineTransportError(
            "actionable BABOOM native frame requires one report"
        )
    data = report.get("data")
    if (
        set(report) != {"kind", "summary", "revision", "data"}
        or report.get("kind") != BABOOM_NATIVE_REPORT_KIND
        or report.get("summary") != BABOOM_NATIVE_REPORT_SUMMARY
        or report.get("revision") != revision
        or type(data) is not dict
        or set(data) != {
            "projection", "revision", "context", "governed_work",
            "workshop", "attention",
        }
        or data.get("projection") != "founder-local-baboom-steward-briefing"
        or data.get("revision") != revision
    ):
        raise MachineTransportError("BABOOM native frame report is invalid")
    for name in ("context", "governed_work", "workshop", "attention"):
        projection = data.get(name)
        if not isinstance(projection, dict) or projection.get("revision") != revision:
            raise MachineTransportError("BABOOM native frame report revision drifted")
    return result


def _secure_pipe_security():
    """Build a protected DACL for this Windows logon session only."""
    try:
        import pywintypes
        import win32api
        import win32con
        import win32security
    except ImportError as exc:
        raise MachineTransportError(
            "pywin32 is required for the secured Windows pipe boundary"
        ) from exc
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    user_sid = win32security.GetTokenInformation(
        token, win32security.TokenUser
    )[0]
    logon_sids = [
        sid for sid, attributes in win32security.GetTokenInformation(
            token, win32security.TokenGroups
        )
        if (attributes & 0xFFFF_FFFF) & 0xC000_0000 == 0xC000_0000
    ]
    if len(logon_sids) != 1:
        raise MachineTransportError("current Windows logon SID is ambiguous")
    logon_sid = logon_sids[0]
    network_sid = win32security.CreateWellKnownSid(
        win32security.WinNetworkSid, None
    )
    anonymous_sid = win32security.CreateWellKnownSid(
        win32security.WinAnonymousSid, None
    )
    system_sid = win32security.CreateWellKnownSid(
        win32security.WinLocalSystemSid, None
    )
    acl = win32security.ACL()
    for denied_sid in (network_sid, anonymous_sid):
        acl.AddAccessDeniedAce(
            win32security.ACL_REVISION, win32con.GENERIC_ALL, denied_sid
        )
    for allowed_sid in (logon_sid, user_sid, system_sid):
        acl.AddAccessAllowedAce(
            win32security.ACL_REVISION, win32con.GENERIC_ALL, allowed_sid
        )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(True, acl, False)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    expected = {
        "deny": {
            win32security.ConvertSidToStringSid(network_sid),
            win32security.ConvertSidToStringSid(anonymous_sid),
        },
        "allow": {
            win32security.ConvertSidToStringSid(logon_sid),
            win32security.ConvertSidToStringSid(user_sid),
            win32security.ConvertSidToStringSid(system_sid),
        },
    }
    return attributes, expected


def _verify_pipe_dacl(handle: int, expected: Mapping[str, set[str]]) -> str:
    """Read back the kernel object's DACL and reject any broader instance."""
    import win32security

    descriptor = win32security.GetSecurityInfo(
        handle,
        win32security.SE_KERNEL_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise MachineTransportError("Windows pipe has a null DACL")
    actual = {"deny": set(), "allow": set()}
    denied_type = win32security.ACCESS_DENIED_ACE_TYPE
    allowed_type = win32security.ACCESS_ALLOWED_ACE_TYPE
    for index in range(acl.GetAceCount()):
        header, _mask, sid = acl.GetAce(index)
        sid_text = win32security.ConvertSidToStringSid(sid)
        if header[0] == denied_type:
            actual["deny"].add(sid_text)
        elif header[0] == allowed_type:
            actual["allow"].add(sid_text)
        else:
            raise MachineTransportError("Windows pipe DACL has an unknown ACE")
    if actual != expected:
        raise MachineTransportError("Windows pipe DACL is broader than declared")
    return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
        descriptor,
        win32security.SDDL_REVISION_1,
        win32security.DACL_SECURITY_INFORMATION,
    )


class _SecureWindowsPipeListener:
    """Pipe listener whose every instance is created with the protected DACL."""

    def __init__(self, address: str) -> None:
        if os.name != "nt":
            raise MachineTransportError("secured named pipes require Windows")
        self._address = address
        self._last_accepted = None
        self._security_attributes, self._expected_dacl = _secure_pipe_security()
        self.security_sddl = ""
        self._handle_queue = [self._new_handle(first=True)]

    def _new_handle(self, *, first: bool = False) -> int:
        import _winapi
        import win32pipe

        open_mode = win32pipe.PIPE_ACCESS_DUPLEX | _winapi.FILE_FLAG_OVERLAPPED
        if first:
            open_mode |= _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
        pipe_mode = (
            win32pipe.PIPE_TYPE_MESSAGE
            | win32pipe.PIPE_READMODE_MESSAGE
            | win32pipe.PIPE_WAIT
            | win32pipe.PIPE_REJECT_REMOTE_CLIENTS
        )
        owned = win32pipe.CreateNamedPipe(
            self._address,
            open_mode,
            pipe_mode,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            65_536,
            65_536,
            win32pipe.NMPWAIT_WAIT_FOREVER,
            self._security_attributes,
        )
        handle = int(owned.Detach())
        try:
            self.security_sddl = _verify_pipe_dacl(handle, self._expected_dacl)
        except Exception:
            _winapi.CloseHandle(handle)
            raise
        return handle

    def accept(self, timeout_seconds=None):
        import _winapi
        from multiprocessing.connection import INFINITE, PipeConnection

        self._handle_queue.append(self._new_handle())
        handle = self._handle_queue.pop(0)
        try:
            overlapped = _winapi.ConnectNamedPipe(handle, overlapped=True)
        except OSError as exc:
            if exc.winerror != _winapi.ERROR_NO_DATA:
                _winapi.CloseHandle(handle)
                raise
        else:
            try:
                waited = _winapi.WaitForMultipleObjects(
                    [overlapped.event], False,
                    INFINITE if timeout_seconds is None else max(1, int(timeout_seconds * 1000))
                )
                if waited == _winapi.WAIT_TIMEOUT:
                    overlapped.cancel()
                    raise TimeoutError("named pipe accept deadline exceeded")
            except Exception:
                overlapped.cancel()
                overlapped.GetOverlappedResult(True)
                _winapi.CloseHandle(handle)
                raise
            else:
                _transferred, error = overlapped.GetOverlappedResult(True)
                if error:
                    _winapi.CloseHandle(handle)
                    raise OSError(error, "ConnectNamedPipe failed")
        self._last_accepted = self._address
        return PipeConnection(handle)

    def close(self) -> None:
        import _winapi

        handles, self._handle_queue = self._handle_queue, []
        for handle in handles:
            _winapi.CloseHandle(handle)


class _AuthenticatedSecurePipeListener:
    def __init__(self, address: str, authkey: bytes) -> None:
        from multiprocessing.connection import answer_challenge, deliver_challenge

        self._listener = _SecureWindowsPipeListener(address)
        self._authkey = authkey
        self._answer_challenge = answer_challenge
        self._deliver_challenge = deliver_challenge

    @property
    def security_sddl(self) -> str:
        return self._listener.security_sddl

    def accept(self, timeout_seconds=None, authentication_timeout_seconds=None):
        connection = (self._listener.accept() if timeout_seconds is None else
                      self._listener.accept(timeout_seconds=timeout_seconds))
        try:
            challenge_connection = connection
            if authentication_timeout_seconds is not None:
                deadline = time.monotonic() + authentication_timeout_seconds

                class BoundedChallenge:
                    def send_bytes(self, value):
                        return connection.send_bytes(value)

                    def recv_bytes(self, maxlength=None):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not connection.poll(remaining):
                            raise TimeoutError("named pipe authentication deadline exceeded")
                        return connection.recv_bytes(maxlength)

                challenge_connection = BoundedChallenge()
            self._deliver_challenge(challenge_connection, self._authkey)
            self._answer_challenge(challenge_connection, self._authkey)
            return connection
        except Exception:
            connection.close()
            raise

    def close(self) -> None:
        self._listener.close()


class ExportableSigningKeyProvider(SigningKeyProvider, Protocol):
    """A current-user provider capable of supplying pipe handshake material."""

    def current(self, key_id: str) -> SigningKeyMaterial:
        ...

    def resolve(self, key_id: str, version: int) -> SigningKeyMaterial:
        ...


def default_runtime_descriptor_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise MachineTransportError("LOCALAPPDATA is unavailable")
    return Path(local) / "ArchHub" / "active-universal-runtime.json"


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def session_proof_payload(
    *,
    runtime_id: str,
    request_id: str,
    method: str,
    path: str,
    body: Mapping[str, object],
    session_root: str,
    capability_id: str | None = None,
) -> bytes:
    """Bind one runtime-session proof to an exact non-replayable request."""
    payload: dict[str, object] = {
        "runtime_id": runtime_id,
        "request_id": request_id,
        "method": method,
        "path": path,
        "body": dict(body),
        "session_root": session_root,
    }
    # Legacy full-session proofs intentionally retain their exact wire shape.
    # A resumed recovery capability names itself so it cannot be replayed as
    # the original mutable session capability.
    if capability_id is not None:
        payload["capability_id"] = capability_id
    return _canonical(payload)


def runtime_device_proof_payload(
    *,
    runtime_id: str,
    runtime: str,
    external_session_id: str,
    challenge_id: str,
    nonce: str,
) -> bytes:
    """Canonical one-time payload for a device-bound Agent Session enrollment."""
    return _canonical({
        "challenge_id": challenge_id,
        "external_session_fingerprint": hashlib.sha256(
            external_session_id.encode("utf-8")
        ).hexdigest(),
        "nonce": nonce,
        "runtime": runtime,
        "runtime_id": runtime_id,
    })


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.%s.tmp" % (path.name, secrets.token_hex(8)))
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical(payload))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _windows_process_is_active(process_id: int) -> bool:
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32
    )
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)
    )
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, 0, process_id)
    if not handle:
        return False
    try:
        code = ctypes.c_uint32()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) \
            and code.value == 259
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True, slots=True)
class RuntimeDescriptor:
    runtime_id: str
    status: str
    pipe: str
    process_id: int
    started_at: str
    stopped_at: str
    application_root: str
    agent_session_root: str
    workshop_root: str
    work_registry_root: str
    database: str
    key_id: str
    key_version: int
    signature: str

    def unsigned(self) -> dict[str, object]:
        return {
            "format": _FORMAT,
            "format_version": _FORMAT_VERSION,
            "runtime_id": self.runtime_id,
            "status": self.status,
            "pipe": self.pipe,
            "process_id": self.process_id,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "application_root": self.application_root,
            "agent_session_root": self.agent_session_root,
            "workshop_root": self.workshop_root,
            "work_registry_root": self.work_registry_root,
            "database": self.database,
            "key_id": self.key_id,
            "key_version": self.key_version,
        }

    def document(self) -> dict[str, object]:
        return {**self.unsigned(), "signature": self.signature}


def _read_descriptor(
    path: Path, key_provider: ExportableSigningKeyProvider
) -> RuntimeDescriptor:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MachineTransportError("runtime descriptor is unreadable") from exc
    expected = {
        "format", "format_version", "runtime_id", "status", "pipe",
        "process_id", "started_at", "stopped_at", "application_root",
        "agent_session_root", "workshop_root", "work_registry_root",
        "database", "key_id", "key_version", "signature",
    }
    if type(payload) is not dict or set(payload) != expected:
        raise MachineTransportError("runtime descriptor has an invalid shape")
    if payload["format"] != _FORMAT or payload["format_version"] != _FORMAT_VERSION:
        raise MachineTransportError("runtime descriptor format is unsupported")
    try:
        descriptor = RuntimeDescriptor(
            runtime_id=str(payload["runtime_id"]),
            status=str(payload["status"]),
            pipe=str(payload["pipe"]),
            process_id=int(payload["process_id"]),
            started_at=str(payload["started_at"]),
            stopped_at=str(payload["stopped_at"]),
            application_root=str(payload["application_root"]),
            agent_session_root=str(payload["agent_session_root"]),
            workshop_root=str(payload["workshop_root"]),
            work_registry_root=str(payload["work_registry_root"]),
            database=str(payload["database"]),
            key_id=str(payload["key_id"]),
            key_version=int(payload["key_version"]),
            signature=str(payload["signature"]),
        )
    except (TypeError, ValueError) as exc:
        raise MachineTransportError("runtime descriptor values are invalid") from exc
    if (
        not _RUNTIME_ID.fullmatch(descriptor.runtime_id)
        or descriptor.status not in {"active", "failed", "stopped"}
        or not descriptor.pipe.startswith(r"\\.\pipe\ArchHub-Universal-")
        or descriptor.process_id <= 0
        or descriptor.key_version < 1
        or not descriptor.application_root
        or not descriptor.agent_session_root
        or not descriptor.workshop_root
        or not descriptor.work_registry_root
    ):
        raise MachineTransportError("runtime descriptor values are invalid")
    if not key_provider.verify(
        descriptor.key_id,
        descriptor.key_version,
        _canonical(descriptor.unsigned()),
        descriptor.signature,
    ):
        raise MachineTransportError("runtime descriptor signature is invalid")
    return descriptor


def inspect_runtime_descriptor(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
) -> dict[str, object]:
    """Return safe, verified liveness facts for one signed descriptor.

    This is operational observation only. It does not make the descriptor a
    source of graph authority, and deliberately excludes its pipe name,
    signature, and database path from the projection.
    """
    try:
        descriptor = _read_descriptor(Path(path), key_provider)
    except MachineTransportError:
        return {"verified": False}
    active = descriptor.status == "active"
    return {
        "verified": True,
        "active": active,
        "owner_alive": (
            _windows_process_is_active(descriptor.process_id) if active else False
        ),
        "application": descriptor.application_root,
    }


def recover_stale_runtime_descriptor(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
) -> RuntimeDescriptor:
    """Release one signed active descriptor whose physical owner is gone."""
    descriptor_path = Path(path).expanduser().resolve()
    descriptor = _read_descriptor(descriptor_path, key_provider)
    if descriptor.status != "active":
        raise MachineTransportError("runtime descriptor is not an active owner")
    if _windows_process_is_active(descriptor.process_id):
        raise MachineTransportError("runtime descriptor owner is still active")
    try:
        inspect_read_only_cell_journal(descriptor.database)
    except ReadOnlyJournalError as exc:
        raise MachineTransportError(
            "stale runtime durable journal is unavailable"
        ) from exc
    unsigned = RuntimeDescriptor(
        descriptor.runtime_id,
        "stopped",
        descriptor.pipe,
        descriptor.process_id,
        descriptor.started_at,
        datetime.now(timezone.utc).isoformat(),
        descriptor.application_root,
        descriptor.agent_session_root,
        descriptor.workshop_root,
        descriptor.work_registry_root,
        descriptor.database,
        descriptor.key_id,
        descriptor.key_version,
        "",
    )
    signature = key_provider.sign(
        unsigned.key_id,
        unsigned.key_version,
        _canonical(unsigned.unsigned()),
    )
    recovered = RuntimeDescriptor(
        unsigned.runtime_id,
        unsigned.status,
        unsigned.pipe,
        unsigned.process_id,
        unsigned.started_at,
        unsigned.stopped_at,
        unsigned.application_root,
        unsigned.agent_session_root,
        unsigned.workshop_root,
        unsigned.work_registry_root,
        unsigned.database,
        unsigned.key_id,
        unsigned.key_version,
        signature,
    )
    _atomic_json(descriptor_path, recovered.document())
    verified = _read_descriptor(descriptor_path, key_provider)
    if verified != recovered:
        raise MachineTransportError("stale runtime recovery did not verify")
    return verified


def inspect_stopped_runtime_durable_journal(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
) -> dict[str, object]:
    """Read bounded journal facts from one signed stopped runtime descriptor.

    This keeps the descriptor's database path inside the local physical
    adapter.  The result exposes no graph roots, process state, or database
    details, and is not authorization or activity proof.
    """
    try:
        descriptor = _read_descriptor(Path(path), key_provider)
    except MachineTransportError:
        return {"available": False, "reason": "signed descriptor is unavailable"}
    if descriptor.status != "stopped":
        return {"available": False, "reason": "signed runtime owner is not stopped"}
    try:
        journal = inspect_read_only_cell_journal(descriptor.database)
    except ReadOnlyJournalError:
        return {"available": False, "reason": "signed durable journal is unavailable"}
    return {
        "available": True,
        "revision": journal.revision,
        "revision_count": journal.revision_count,
        "latest_revision_change_count": journal.latest_revision_change_count,
    }


def inspect_stopped_runtime_trusted_checkpoint(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
) -> dict[str, object]:
    """Verify one stopped runtime's signed durable checkpoint without owning it.

    The main journal is streamed read-only through its checkpoint revision.  A
    separately capped authority snapshot verifies the v2 CNG signature
    envelope.  This establishes durable-byte continuity only; it never
    projects graph activity or authorizes a runtime handoff.
    """
    try:
        descriptor = _read_descriptor(Path(path), key_provider)
    except MachineTransportError:
        return {"available": False, "reason": "signed descriptor is unavailable"}
    if descriptor.status != "stopped":
        return {"available": False, "reason": "signed runtime owner is not stopped"}
    try:
        database = Path(descriptor.database).expanduser().resolve(strict=True)
        checkpoint_path = RevisionCheckpointGuard.default_path(database)
        record = json.loads(checkpoint_path.read_text(encoding="ascii"))
        expected = {
            "format", "format_version", "database", "revision", "digest",
            "issued_at", "envelope_root",
        }
        identity = hashlib.sha256(
            str(database).casefold().encode("utf-8")
        ).hexdigest()
        revision = record.get("revision") if isinstance(record, dict) else None
        digest = record.get("digest") if isinstance(record, dict) else None
        issued_at = record.get("issued_at") if isinstance(record, dict) else None
        envelope_root = record.get("envelope_root") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record) != expected
            or record.get("format") != RevisionCheckpointGuard.FORMAT
            or record.get("format_version") != RevisionCheckpointGuard.VERSION
            or record.get("database") != identity
            or type(revision) is not int
            or revision < 0
            or type(digest) is not str
            or len(digest) != 64
            or type(issued_at) is not str
            or not issued_at.endswith("Z")
            or type(envelope_root) is not str
            or not envelope_root
        ):
            raise ValueError("checkpoint shape is invalid")
        datetime.fromisoformat(issued_at[:-1] + "+00:00")
        authority_snapshot = load_bounded_read_only_cell_snapshot(
            default_checkpoint_authority_path(database),
            max_revisions=_MAX_CHECKPOINT_AUTHORITY_REVISIONS,
            max_current_cells=_MAX_CHECKPOINT_AUTHORITY_CELLS,
            max_version_cells=_MAX_CHECKPOINT_AUTHORITY_CELLS,
        )
        prefix_identity = hashlib.sha256(
            str(database).casefold().encode("utf-8")
        ).hexdigest()
        prefix = "checkpoint-authority:%s:signing" % prefix_identity
        descriptor_root = "checkpoint-authority:%s:descriptor:v2" % (
            prefix_identity,
        )
        protocol = project_signing_authority_protocol(
            authority_snapshot, prefix=prefix
        )
        recorded = read_signing_key_descriptor(
            authority_snapshot, protocol, descriptor_root
        )
        signer = WindowsCngSigningAuthorityProvider(
            provider_id=recorded.values["provider-id"],
            key_name=default_checkpoint_key_name(database),
            create=False,
        )
        signed_descriptor = verify_signing_key_descriptor(
            authority_snapshot, protocol, signer, descriptor_root
        )
        if signed_descriptor.values["purpose"] != RevisionCheckpointGuard.SIGNING_PURPOSE:
            raise ValueError("checkpoint signing purpose is invalid")
        envelope = verify_signature_envelope(
            authority_snapshot,
            protocol,
            signer,
            envelope_root,
            payload=_canonical(record),
            expected_statement_protocol=RevisionCheckpointGuard.STATEMENT_PROTOCOL,
            expected_context=RevisionCheckpointGuard.STATEMENT_CONTEXT,
        )
        if envelope.values["key-descriptor"] != descriptor_root:
            raise ValueError("checkpoint signing descriptor is invalid")
        actual_digest = read_only_revision_chain_digest(
            database,
            revision,
            max_revision_cells=_MAX_CHECKPOINT_REVISION_CELLS,
        )
        if not hmac.compare_digest(actual_digest, digest):
            raise ValueError("checkpoint digest is invalid")
    except Exception:
        return {"available": False, "reason": "signed checkpoint is unavailable"}
    return {
        "available": True,
        "revision": revision,
        "authorizes_handoff": False,
    }


def stopped_runtime_restart_database(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
) -> Path | None:
    """Resolve the one durable database released by a clean stopped owner.

    A signed stopped descriptor is the former owner's release. Restart is
    admitted only when its CNG-backed checkpoint verifies the exact current
    journal head and the database remains in ArchHub's local authority root.
    """
    descriptor_path = Path(path).expanduser().resolve()
    if not descriptor_path.exists():
        return None
    descriptor = _read_descriptor(descriptor_path, key_provider)
    if descriptor.status != "stopped":
        return None
    trusted = inspect_stopped_runtime_trusted_checkpoint(
        descriptor_path, key_provider
    )
    if trusted.get("available") is not True:
        raise MachineTransportError(
            "stopped Universal authority has no trusted checkpoint"
        )
    try:
        database = Path(descriptor.database).expanduser().resolve(strict=True)
        local_app_data = os.environ.get("LOCALAPPDATA")
        authority_root = (
            Path(local_app_data).expanduser().resolve() / "ArchHub"
            if local_app_data
            else (Path.home() / "AppData" / "Local" / "ArchHub").resolve()
        )
        database.relative_to(authority_root)
        journal = inspect_read_only_cell_journal(database)
    except (OSError, ReadOnlyJournalError, ValueError) as exc:
        raise MachineTransportError(
            "stopped Universal authority database is not restartable"
        ) from exc
    if journal.revision != trusted.get("revision"):
        raise MachineTransportError(
            "stopped Universal authority advanced beyond its trusted checkpoint"
        )
    return database


_STOPPED_RUNTIME_ACTIVITY_SQL = """
WITH RECURSIVE
latest AS NOT MATERIALIZED (
    SELECT cell_id, link0, link1, atom FROM current_cells
),
metadata AS (SELECT MAX(revision) AS revision FROM revisions),
root_chain(source, cursor, depth) AS (
    VALUES
      ('sessions', 'app:agent-body-protocol:registry:session', 0),
      ('presences', 'app:runtime-presence-protocol:root', 0),
      ('work', 'app:governed-work-registry', 0),
      ('ownership', 'app:exclusive-ownership-protocol:root', 0)
    UNION ALL
    SELECT root_chain.source, current.link1, root_chain.depth + 1
    FROM root_chain JOIN latest AS current ON current.cell_id = root_chain.cursor
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
      AND current.link1 <> '00000000-0000-0000-0000-000000000000'
      AND root_chain.depth < 100000
),
root_members AS (
    SELECT root_chain.source, incidence.link0 AS role, incidence.link1 AS participant
    FROM root_chain
    JOIN latest AS current ON current.cell_id = root_chain.cursor
    JOIN latest AS incidence ON incidence.cell_id = current.link0
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
),
sessions AS (
    SELECT participant AS root FROM root_members
    WHERE source = 'sessions'
      AND role = 'app:agent-body-protocol:role:session-member'
      AND participant LIKE 'app:agent-session:runtime:%'
),
session_chain(session_root, cursor, depth) AS (
    SELECT root, root, 0 FROM sessions
    UNION ALL
    SELECT session_chain.session_root, current.link1, session_chain.depth + 1
    FROM session_chain JOIN latest AS current ON current.cell_id = session_chain.cursor
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
      AND current.link1 <> '00000000-0000-0000-0000-000000000000'
      AND session_chain.depth < 100000
),
session_states AS (
    SELECT session_chain.session_root, incidence.link1 AS state
    FROM session_chain
    JOIN latest AS current ON current.cell_id = session_chain.cursor
    JOIN latest AS incidence ON incidence.cell_id = current.link0
    WHERE incidence.link0 = 'app:agent-body-protocol:role:session-state'
),
work_roots AS (
    SELECT participant AS root FROM root_members
    WHERE source = 'work' AND role = 'gm:role:member'
),
work_chain(work_root, cursor, depth) AS (
    SELECT root, root, 0 FROM work_roots
    UNION ALL
    SELECT work_chain.work_root, current.link1, work_chain.depth + 1
    FROM work_chain JOIN latest AS current ON current.cell_id = work_chain.cursor
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
      AND current.link1 <> '00000000-0000-0000-0000-000000000000'
      AND work_chain.depth < 100000
),
work_members AS (
    SELECT work_chain.work_root, incidence.link0 AS role, incidence.link1 AS participant
    FROM work_chain
    JOIN latest AS current ON current.cell_id = work_chain.cursor
    JOIN latest AS incidence ON incidence.cell_id = current.link0
),
stateful_work AS (
    SELECT work_root FROM work_members
    WHERE role = 'app:assembly-protocol:role:capability'
      AND participant = 'app:standard-library:state-machine-protocol:root'
),
machine_roots AS (
    SELECT member.work_root, member.participant AS root
    FROM work_members AS member JOIN stateful_work USING (work_root)
    WHERE member.role = 'app:assembly-protocol:role:rule'
),
machine_chain(work_root, cursor, depth) AS (
    SELECT work_root, root, 0 FROM machine_roots
    UNION ALL
    SELECT machine_chain.work_root, current.link1, machine_chain.depth + 1
    FROM machine_chain JOIN latest AS current ON current.cell_id = machine_chain.cursor
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
      AND current.link1 <> '00000000-0000-0000-0000-000000000000'
      AND machine_chain.depth < 100000
),
work_states AS (
    SELECT machine_chain.work_root, state.atom AS label
    FROM machine_chain
    JOIN latest AS current ON current.cell_id = machine_chain.cursor
    JOIN latest AS incidence ON incidence.cell_id = current.link0
    JOIN latest AS state ON state.cell_id = incidence.link1
    WHERE incidence.link0 = 'app:standard-library:state-machine-protocol:role:current-state'
),
ownership_roots AS (
    SELECT participant AS root FROM root_members
    WHERE source = 'ownership'
      AND role = 'app:exclusive-ownership-protocol:role:ownership-member'
),
ownership_chain(owner_root, cursor, depth) AS (
    SELECT root, root, 0 FROM ownership_roots
    UNION ALL
    SELECT ownership_chain.owner_root, current.link1, ownership_chain.depth + 1
    FROM ownership_chain JOIN latest AS current ON current.cell_id = ownership_chain.cursor
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
      AND current.link1 <> '00000000-0000-0000-0000-000000000000'
      AND ownership_chain.depth < 100000
),
ownership_fields AS (
    SELECT ownership_chain.owner_root, incidence.link0 AS role, incidence.link1 AS participant
    FROM ownership_chain
    JOIN latest AS current ON current.cell_id = ownership_chain.cursor
    JOIN latest AS incidence ON incidence.cell_id = current.link0
),
application_owners AS (
    SELECT resource.owner_root, state.participant AS state,
           CAST(generation_cell.atom AS INTEGER) AS generation
    FROM ownership_fields AS resource
    JOIN ownership_fields AS state USING (owner_root)
    JOIN ownership_fields AS generation USING (owner_root)
    JOIN latest AS generation_cell ON generation_cell.cell_id = generation.participant
    WHERE resource.role = 'app:exclusive-ownership-protocol:role:resource'
      AND resource.participant = 'app:archhub'
      AND state.role = 'app:exclusive-ownership-protocol:role:state'
      AND generation.role = 'app:exclusive-ownership-protocol:role:generation'
),
presence_roots AS (
    SELECT participant AS root FROM root_members
    WHERE source = 'presences'
      AND role = 'app:runtime-presence-protocol:role:presence-member'
),
presence_chain(presence_root, cursor, depth) AS (
    SELECT root, root, 0 FROM presence_roots
    UNION ALL
    SELECT presence_chain.presence_root, current.link1, presence_chain.depth + 1
    FROM presence_chain JOIN latest AS current ON current.cell_id = presence_chain.cursor
    WHERE current.link0 <> '00000000-0000-0000-0000-000000000000'
      AND current.link1 <> '00000000-0000-0000-0000-000000000000'
      AND presence_chain.depth < 100000
),
presence_expiry AS (
    SELECT presence_chain.presence_root, CAST(expiry.atom AS REAL) AS expires_at
    FROM presence_chain
    JOIN latest AS current ON current.cell_id = presence_chain.cursor
    JOIN latest AS incidence ON incidence.cell_id = current.link0
    JOIN latest AS expiry ON expiry.cell_id = incidence.link1
    WHERE incidence.link0 = 'app:runtime-presence-protocol:role:presence-expires-at'
)
SELECT
  (SELECT revision FROM metadata),
  (SELECT COUNT(*) FROM sessions),
  (SELECT COUNT(*) FROM session_states),
  (SELECT COUNT(*) FROM session_states WHERE state = 'app:agent-body-protocol:state:active'),
  (SELECT COUNT(*) FROM work_roots),
  (SELECT COUNT(*) FROM stateful_work),
  (SELECT COUNT(*) FROM work_states),
  (SELECT COUNT(*) FROM work_states WHERE lower(CAST(label AS TEXT)) = 'open'),
  (SELECT COUNT(*) FROM work_states WHERE lower(CAST(label AS TEXT)) = 'claimed'),
  (SELECT COUNT(*) FROM work_states WHERE lower(CAST(label AS TEXT)) = 'blocked'),
  (SELECT COUNT(*) FROM work_states WHERE lower(CAST(label AS TEXT)) = 'review'),
  (SELECT COUNT(*) FROM work_states WHERE lower(CAST(label AS TEXT)) = 'complete'),
  (SELECT COUNT(*) FROM work_states WHERE lower(CAST(label AS TEXT)) = 'cancelled'),
  (SELECT COUNT(*) FROM application_owners),
  (SELECT generation FROM application_owners ORDER BY generation DESC LIMIT 1),
  (SELECT state FROM application_owners ORDER BY generation DESC LIMIT 1),
  (SELECT COUNT(*) FROM presence_roots),
  (SELECT COUNT(*) FROM presence_expiry),
  (SELECT COUNT(*) FROM presence_expiry WHERE expires_at > ?)
"""


def inspect_stopped_runtime_offline_activity(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
    *,
    max_seconds: float = 20.0,
) -> dict[str, object]:
    """Return the bounded activity portion of one stopped recovery observation."""
    return inspect_stopped_runtime_recovery_activity(
        path, key_provider, max_seconds=max_seconds
    )["offline_activity"]


def inspect_stopped_runtime_recovery_activity(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
    *,
    max_seconds: float = 20.0,
) -> dict[str, dict[str, object]]:
    """Read one signed checkpoint and its optional indexed activity projection.

    The checkpoint is verified exactly once.  Its activity projection is a
    physical recovery observation, never a replacement for the live graph
    lens; it can add blockers but cannot authorize a handoff.
    """
    if (
        type(max_seconds) not in (int, float)
        or not 0.1 <= float(max_seconds) <= 60.0
    ):
        return {
            "trusted_checkpoint": {
                "available": False,
                "reason": "offline activity budget is invalid",
            },
            "offline_activity": {
                "available": False,
                "reason": "offline activity budget is invalid",
            },
        }
    trusted = inspect_stopped_runtime_trusted_checkpoint(path, key_provider)
    if trusted.get("available") is not True:
        return {
            "trusted_checkpoint": trusted,
            "offline_activity": {
                "available": False,
                "reason": "trusted checkpoint is unavailable",
            },
        }
    return {
        "trusted_checkpoint": trusted,
        "offline_activity": _project_stopped_runtime_offline_activity(
            path, key_provider, trusted, max_seconds=float(max_seconds)
        ),
    }


def _project_stopped_runtime_offline_activity(
    path: str | os.PathLike[str],
    key_provider: ExportableSigningKeyProvider,
    trusted: Mapping[str, object],
    *,
    max_seconds: float,
) -> dict[str, object]:
    """Project bounded blockers from an already verified stopped journal.

    The result is a physical recovery observation, never a replacement for the
    live graph lens.  It can add handoff blockers but cannot authorize a
    handoff, create a CellStore owner, or expose roots or content.
    """
    trusted_revision = trusted.get("revision")
    if (
        trusted.get("available") is not True
        or type(trusted_revision) is not int
        or trusted_revision < 0
    ):
        return {"available": False, "reason": "trusted checkpoint is unavailable"}
    try:
        descriptor = _read_descriptor(Path(path), key_provider)
        connection = sqlite3.connect(
            Path(descriptor.database).expanduser().resolve().as_uri() + "?mode=ro",
            uri=True, timeout=1.0, isolation_level=None,
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            indexed = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='current_cells'"
            ).fetchone()
            if indexed != (1,):
                raise ValueError("current Cell index is unavailable")
            deadline = time.monotonic() + max_seconds
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline), 100_000
            )
            row = connection.execute(
                _STOPPED_RUNTIME_ACTIVITY_SQL, (time.time(),)
            ).fetchone()
        finally:
            connection.set_progress_handler(None, 0)
            connection.close()
        if row is None or len(row) != 19:
            raise ValueError("offline activity result is incomplete")
        values = tuple(int(value) if value is not None else None for value in row[:15])
        revision, sessions, session_states, active_sessions, work_total, stateful_work, work_states, open_work, claimed_work, blocked_work, review_work, complete_work, cancelled_work, owner_count, generation = values
        owner_state = row[15]
        presence_roots, presence_expiry, active_presence = (
            int(row[16]), int(row[17]), int(row[18])
        )
        counts = (sessions, session_states, active_sessions, work_total, stateful_work, work_states, open_work, claimed_work, blocked_work, review_work, complete_work, cancelled_work, owner_count, generation, presence_roots, presence_expiry, active_presence)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("offline activity counts are invalid")
        if (
            revision != trusted_revision
            or session_states != sessions
            or active_sessions > sessions
            or stateful_work != work_total
            or work_states != work_total
            or open_work + claimed_work + blocked_work + review_work + complete_work + cancelled_work != work_total
            or owner_count < 1
            or generation < 1
            or owner_state not in {
                "app:exclusive-ownership-protocol:state:active",
                "app:exclusive-ownership-protocol:state:draining",
                "app:exclusive-ownership-protocol:state:released",
                "app:exclusive-ownership-protocol:state:failed",
            }
            or presence_expiry != presence_roots
            or active_presence > presence_roots
        ):
            raise ValueError("offline activity graph shape is invalid")
    except Exception:
        return {"available": False, "reason": "trusted offline activity is unavailable"}
    owner = owner_state.rsplit(":", 1)[-1]
    return {
        "available": True,
        "revision": revision,
        "runtime_owner": {"state": owner, "generation": generation},
        "activity": {
            "active_runtime_sessions": active_sessions,
            "active_runtime_presence_leases": active_presence,
            "work": {
                "total": work_total,
                "open": open_work,
                "claimed": claimed_work,
                "blocked": blocked_work,
                "review": review_work,
                "complete": complete_work,
                "cancelled": cancelled_work,
            },
        },
        "authorizes_handoff": False,
    }


class UniversalRuntimeTransport:
    """One authenticated pipe owned by the running ApplicationServer."""

    def __init__(
        self,
        dispatch: Callable[[Mapping[str, object]], Mapping[str, object]],
        *,
        application_root: str,
        agent_session_root: str,
        workshop_root: str,
        work_registry_root: str,
        database: str = "",
        descriptor_path: str | os.PathLike[str] | None = None,
        key_provider: ExportableSigningKeyProvider,
        key_id: str = "archhub.local.universal-runtime-pipe",
        after_response: Callable[
            [Mapping[str, object], Mapping[str, object]], None
        ] | None = None,
    ) -> None:
        if os.name != "nt":
            raise MachineTransportError("Universal runtime pipe requires Windows")
        self.dispatch = dispatch
        self.application_root = application_root
        self.agent_session_root = agent_session_root
        self.workshop_root = workshop_root
        self.work_registry_root = work_registry_root
        self.database = database
        self.descriptor_path = Path(
            descriptor_path or default_runtime_descriptor_path()
        ).expanduser().resolve()
        self.key_provider = key_provider
        self.key_material = key_provider.current(key_id)
        self.after_response = after_response
        self.runtime_id = secrets.token_hex(16)
        self.pipe = r"\\.\pipe\ArchHub-Universal-%s" % self.runtime_id
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._listener: _AuthenticatedSecurePipeListener | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._seen_lock = threading.Lock()
        self.pipe_security_sddl = ""
        self._last_accept_error = ""

    def _descriptor(self, status: str, *, stopped_at: str = "") -> RuntimeDescriptor:
        unsigned = RuntimeDescriptor(
            self.runtime_id,
            status,
            self.pipe,
            os.getpid(),
            self.started_at,
            stopped_at,
            self.application_root,
            self.agent_session_root,
            self.workshop_root,
            self.work_registry_root,
            self.database,
            self.key_material.key_id,
            self.key_material.version,
            "",
        )
        signature = self.key_provider.sign(
            self.key_material.key_id,
            self.key_material.version,
            _canonical(unsigned.unsigned()),
        )
        return RuntimeDescriptor(
            unsigned.runtime_id,
            unsigned.status,
            unsigned.pipe,
            unsigned.process_id,
            unsigned.started_at,
            unsigned.stopped_at,
            unsigned.application_root,
            unsigned.agent_session_root,
            unsigned.workshop_root,
            unsigned.work_registry_root,
            unsigned.database,
            unsigned.key_id,
            unsigned.key_version,
            signature,
        )

    def _remember(self, request_id: str) -> None:
        with self._seen_lock:
            if request_id in self._seen:
                raise MachineTransportError("machine request replay was denied")
            self._seen.add(request_id)
            self._seen_order.append(request_id)
            while len(self._seen_order) > 4096:
                expired = self._seen_order.popleft()
                self._seen.discard(expired)

    def _decode_request(self, raw: bytes) -> dict[str, object]:
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise MachineTransportError("machine request is not valid JSON") from exc
        required = {
            "runtime_id", "request_id", "method", "path", "body", "session"
        }
        if type(request) is not dict or set(request) != required:
            raise MachineTransportError("machine request shape is invalid")
        if request["runtime_id"] != self.runtime_id:
            raise MachineTransportError("machine request targets a stale runtime")
        request_id = request["request_id"]
        if type(request_id) is not str or not _REQUEST_ID.fullmatch(request_id):
            raise MachineTransportError("machine request identity is invalid")
        if (
            type(request["method"]) is not str
            or type(request["path"]) is not str
            or type(request["body"]) is not dict
            or type(request["session"]) is not dict
        ):
            raise MachineTransportError("machine request values are invalid")
        return request

    def _serve_connection(self, connection) -> None:
        request_id = ""
        try:
            if not connection.poll(5.0):
                raise MachineTransportError("machine request timed out")
            request = self._decode_request(
                connection.recv_bytes(_MAX_MESSAGE_BYTES)
            )
            request_id = str(request["request_id"])
            self._remember(request_id)
            try:
                peer = _read_windows_pipe_peer(connection)
            except Exception:
                # Optional physical observation cannot weaken or replace the
                # existing signed request admission. Native launch requires it.
                peer = None
            peer_context = _VERIFIED_PIPE_PEER.set((request, peer))
            try:
                result = dict(self.dispatch(request))
            finally:
                _VERIFIED_PIPE_PEER.reset(peer_context)
            response = {
                "ok": True,
                "runtime_id": self.runtime_id,
                "request_id": request_id,
                "result": result,
            }
        except Exception as exc:
            response = {
                "ok": False,
                "runtime_id": self.runtime_id,
                "request_id": request_id,
                "error": str(exc),
            }
            if isinstance(exc, MachineEffectOutcomeUnknown):
                response['effect_outcome'] = 'unknown'
        try:
            raw = _canonical(response)
        except (TypeError, ValueError, UnicodeError):
            response = {"ok": False, "runtime_id": self.runtime_id,
                "request_id": request_id, "error": "machine response serialization failed",
                "effect_outcome": "unknown"}
            raw = _canonical(response)
        if len(raw) > _MAX_MESSAGE_BYTES:
            response = {
                "ok": False,
                "runtime_id": self.runtime_id,
                "request_id": request_id,
                "error": "machine response exceeds its size limit",
                "effect_outcome": "unknown",
            }
            raw = _canonical(response)
        try:
            connection.send_bytes(raw)
        except (BrokenPipeError, EOFError, OSError):
            # A client can abandon a slow request. That request must not kill
            # the single-owner listener or strand later sessions.
            return
        if response.get("ok") is True and self.after_response is not None:
            self.after_response(request, response)

    def _serve_connection_and_close(self, connection) -> None:
        try:
            self._serve_connection(connection)
        finally:
            try:
                connection.close()
            except (EOFError, OSError):
                pass

    def _run(self) -> None:
        listener = self._listener
        if listener is None:
            return
        consecutive_accept_failures = 0
        while not self._stop.is_set():
            try:
                connection = listener.accept()
            except AuthenticationError:
                continue
            except (EOFError, OSError) as exc:
                if self._stop.is_set():
                    break
                consecutive_accept_failures += 1
                self._last_accept_error = type(exc).__name__
                if consecutive_accept_failures >= 8:
                    _atomic_json(
                        self.descriptor_path,
                        self._descriptor(
                            "failed",
                            stopped_at=datetime.now(timezone.utc).isoformat(),
                        ).document(),
                    )
                    break
                self._stop.wait(0.05)
                continue
            consecutive_accept_failures = 0
            self._last_accept_error = ""
            if self._stop.is_set():
                connection.close()
                continue
            threading.Thread(
                target=self._serve_connection_and_close,
                args=(connection,),
                name="archhub-universal-runtime-request",
                daemon=True,
            ).start()

    def start(self) -> "UniversalRuntimeTransport":
        if self._thread is not None:
            return self
        if self.descriptor_path.exists():
            existing = _read_descriptor(
                self.descriptor_path, self.key_provider
            )
            if (
                existing.status == "active"
                and _windows_process_is_active(existing.process_id)
            ):
                raise MachineTransportError(
                    "another universal graph owner is already active"
                )
        self._listener = _AuthenticatedSecurePipeListener(
            self.pipe, self.key_material.secret
        )
        self.pipe_security_sddl = self._listener.security_sddl
        self._thread = threading.Thread(
            target=self._run,
            name="archhub-universal-runtime-pipe",
            daemon=True,
        )
        self._thread.start()
        _atomic_json(self.descriptor_path, self._descriptor("active").document())
        return self

    @property
    def is_serving(self) -> bool:
        """Whether the authenticated listener is still able to accept work."""
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop.is_set()
        )

    def close(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        if self._thread.is_alive():
            def wake_listener() -> None:
                try:
                    wake = Client(
                        self.pipe,
                        family="AF_PIPE",
                        authkey=self.key_material.secret,
                    )
                    wake.close()
                except (EOFError, OSError):
                    return

            wake_thread = threading.Thread(
                target=wake_listener,
                name="archhub-runtime-pipe-wake",
                daemon=True,
            )
            wake_thread.start()
            wake_thread.join(timeout=1)
        if self._listener is not None:
            self._listener.close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise MachineTransportError("runtime pipe did not stop")
        try:
            current = _read_descriptor(
                self.descriptor_path, self.key_provider
            )
        except MachineTransportError:
            current = None
        if current is not None and current.runtime_id == self.runtime_id:
            _atomic_json(
                self.descriptor_path,
                self._descriptor(
                    "stopped", stopped_at=datetime.now(timezone.utc).isoformat()
                ).document(),
            )
        self._thread = None


class UniversalRuntimeClient:
    """Strict client for one signed active runtime descriptor."""

    def __init__(
        self,
        descriptor_path: str | os.PathLike[str],
        key_provider: ExportableSigningKeyProvider,
        *,
        cancellation_event: threading.Event | None = None,
    ) -> None:
        self.descriptor_path = Path(descriptor_path).expanduser().resolve()
        self.key_provider = key_provider
        self.agent_session_root = ""
        self._agent_session_token = ""
        self._agent_session_expires_at = 0.0
        self._agent_session_capability_id = ""
        self._agent_session_access = "full"
        self._runtime_presence_expires_at = 0.0
        self._runtime_presence_generation: int | None = None
        self._continuation_request = None
        self._request_lock = threading.RLock()
        self._cancellation_event = cancellation_event
        self._pinned_runtime_descriptor: RuntimeDescriptor | None = None

    def pin_runtime_descriptor(self, descriptor: RuntimeDescriptor) -> None:
        """Keep this client on one owner; replacement requires a new binding.

        The descriptor is verified again inside the actual request path. A
        preliminary read alone cannot prevent a descriptor swap before dispatch.
        """
        if type(descriptor) is not RuntimeDescriptor or descriptor.status != "active":
            raise MachineTransportError("an active runtime descriptor is required")
        with self._request_lock:
            if self._pinned_runtime_descriptor not in (None, descriptor):
                raise MachineTransportError("runtime client is already pinned to another owner")
            self._pinned_runtime_descriptor = descriptor

    def _check_cancelled(self) -> None:
        if self._cancellation_event is not None and self._cancellation_event.is_set():
            raise MachineTransportError("universal runtime request cancelled")

    def bind_agent_session(
        self,
        *,
        runtime: str,
        external_session_id: str,
        expected_agent_session: str | None = None,
        device_credential_provider: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        """Enroll and retain one process-local graph Agent Session capability."""
        if self.agent_session_root or self._agent_session_token:
            raise MachineTransportError("runtime client already has an Agent Session")
        if self._continuation_request is not None:
            raise MachineTransportError("native continuation outcome requires its retained status; no enrollment retry")
        body: dict[str, object] = {
            "runtime": runtime,
            "external_session_id": external_session_id,
        }
        if expected_agent_session is not None:
            if type(expected_agent_session) is not str or not re.fullmatch(
                    r"app:agent-session:runtime:[a-f0-9]{32}", expected_agent_session):
                raise MachineTransportError("conditional enrollment requires an exact existing actor")
            body["expected_agent_session"] = expected_agent_session
            body["continuation_id"] = f"{int(time.time()):08x}"+secrets.token_hex(12)
            self._continuation_request = dict(body)
        if device_credential_provider is not None:
            challenge = self.request(
                "POST",
                "/api/universal/agent-session-challenge",
                {"runtime": runtime},
            )
            credential = device_credential_provider(challenge)
            if type(credential) is not dict:
                raise MachineTransportError("runtime device credential is invalid")
            body["device_credential"] = credential
        result = self.request("POST", "/api/universal/agent-session", body)
        return self._accept_agent_session_result(result, expected_agent_session)

    def _accept_agent_session_result(self, result, expected_agent_session=None):
        root = result.get("agent_session")
        token = result.get("session_token")
        expires_at = result.get("expires_at")
        if (
            type(root) is not str
            or (expected_agent_session is not None and
                (root != expected_agent_session or result.get("continued") is not True))
            or not root.startswith("app:agent-session:runtime:")
            or type(token) is not str
            or len(token) < 32
            or type(expires_at) not in (int, float)
            or float(expires_at) <= time.time()
        ):
            raise MachineTransportError("Agent Session enrollment response is invalid")
        self.agent_session_root = root
        self._agent_session_token = token
        self._agent_session_expires_at = float(expires_at)
        self._agent_session_capability_id = ""
        self._agent_session_access = "full"
        return result

    @property
    def agent_session_access(self) -> str:
        """Expose the volatile capability class without inventing graph state."""
        return self._agent_session_access

    def reconcile_agent_session(self, *, runtime, external_session_id, expected_agent_session, projection=None, cursor=None):
        """Inspect existing custody without enrollment, renewal or state reset."""
        with self._request_lock:
            if self.agent_session_root or self._agent_session_token:
                raise MachineTransportError("native reconciliation requires an unbound inspection client")
            if projection not in (None, "effects"):
                raise MachineTransportError("Native reconciliation projection is invalid")
            body = {
                "runtime":runtime, "external_session_id":external_session_id,
                "expected_agent_session":expected_agent_session}
            if projection is not None:
                body["projection"] = projection
            if cursor is not None:
                if projection != "effects" or type(cursor) is not str or re.fullmatch(r"[0-9a-f]{32}", cursor) is None:
                    raise MachineTransportError("Native effects cursor is invalid")
                body["cursor"] = cursor
            result = self.request("POST", "/api/universal/agent-session-reconcile", body)
            if (result.get("agent_session") != expected_agent_session
                    or result.get("runtime") != runtime
                    or result.get("binding_status") not in {"absent","retained","expired"}
                    or result.get("historical_attempt_outcome") != "unknown"
                    or result.get("continuation_authorized") is not False
                    or "session_token" in result or "capability" in result):
                raise MachineTransportError("native reconciliation response is invalid")
            if projection == "effects":
                effects = result.get("effects")
                if (type(effects) is not dict or effects.get("projection") != "effects"
                        or effects.get("agent_session") != expected_agent_session
                        or effects.get("revision") != result.get("revision")
                        or effects.get("settlement_performed") is not False
                        or effects.get("disclosure") not in {"minimal", "bound-peer"}
                        or type(effects.get("pending_permits")) is not list
                        or len(effects["pending_permits"]) > 16 or type(effects.get("truncated")) is not bool
                        or len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > 65536):
                    raise MachineTransportError("native effects inspection response is invalid")
                next_cursor = effects.get('next_cursor')
                receipts = effects.get('receipt_references')
                if (type(receipts) is not list or len(receipts) + len(effects['pending_permits']) > 16
                        or (next_cursor is not None and (type(next_cursor) is not str
                            or re.fullmatch('[a-f0-9]{32}', next_cursor) is None))
                        or effects['truncated'] != (next_cursor is not None)
                        or (effects['disclosure'] == 'bound-peer' and result.get('binding_matches_caller') is not True)
                        or any(key.startswith('_') for key in effects)):
                    raise MachineTransportError('Native effects continuation or custody is invalid')
                if effects['disclosure'] == 'minimal' and (receipts or any(
                        type(row) is not dict or set(row) != {'permit','state','issued_at','expires_at'}
                        for row in effects['pending_permits'])):
                    raise MachineTransportError('Native effects minimal disclosure is invalid')
            return result

    def recover_agent_session_continuation(self):
        """Read the retained attempt once per explicit call; never mint again."""
        with self._request_lock:
            if self.agent_session_root or self._agent_session_token or self._continuation_request is None:
                raise MachineTransportError("native continuation has no uncertain retained attempt")
            held = self._continuation_request
            response = self.request("POST", "/api/universal/agent-session-continuation-status", dict(held))
            if (type(response) is dict and set(response) == {'continuation_id','agent_session','outcome'}
                    and response['continuation_id'] == held['continuation_id']
                    and response['agent_session'] == held['expected_agent_session']
                    and response['outcome'] == 'not-enrolled'):
                raise MachineContinuationNotEnrolled('Exact native continuation was refused before enrollment')
            if (response.get("continuation_id") != held["continuation_id"]
                    or response.get("agent_session") != held["expected_agent_session"]
                    or response.get("outcome") != "confirmed" or type(response.get("result")) is not dict):
                raise MachineTransportError("native continuation outcome remains unavailable; no enrollment retry")
            return self._accept_agent_session_result(response["result"],held["expected_agent_session"])

    def resume_agent_session(
        self,
        *,
        runtime: str,
        external_session_id: str,
        device_credential_provider: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> dict[str, object]:
        """Read an existing device-proofed graph session without taking it over.

        This is deliberately not a second enrollment and not a mutable session
        renewal. The server issues a separate, short-lived read capability for
        the exact graph-held session so a restarted companion can recover its
        context while the original worker remains uninterrupted.
        """
        if self.agent_session_root or self._agent_session_token:
            raise MachineTransportError("runtime client already has an Agent Session")
        challenge = self.request(
            "POST",
            "/api/universal/agent-session-challenge",
            {"runtime": runtime},
        )
        credential = device_credential_provider(challenge)
        if type(credential) is not dict:
            raise MachineTransportError("runtime device credential is invalid")
        result = self.request("POST", "/api/universal/agent-session-resume", {
            "runtime": runtime,
            "external_session_id": external_session_id,
            "device_credential": credential,
        })
        root = result.get("agent_session")
        token = result.get("session_token")
        capability_id = result.get("capability")
        expires_at = result.get("expires_at")
        if (
            type(root) is not str
            or not root.startswith("app:agent-session:runtime:")
            or type(token) is not str
            or len(token) < 32
            or type(capability_id) is not str
            or not capability_id.startswith("machine-recovery:")
            or result.get("access") != "recovery-read"
            or result.get("continued") is not True
            or type(expires_at) not in (int, float)
            or float(expires_at) <= time.time()
        ):
            raise MachineTransportError("Agent Session recovery response is invalid")
        self.agent_session_root = root
        self._agent_session_token = token
        self._agent_session_expires_at = float(expires_at)
        self._agent_session_capability_id = capability_id
        self._agent_session_access = "recovery-read"
        return result

    def renew_agent_session(self) -> dict[str, object]:
        """Rotate the process capability without changing graph identity."""
        with self._request_lock:
            if not self.agent_session_root or not self._agent_session_token:
                raise MachineTransportError("runtime client has no Agent Session")
            if self._agent_session_access != "full":
                raise MachineTransportError(
                    "recovered runtime Agent Session is read-only and cannot renew"
                )
            result = self._request_once(
                "POST", "/api/universal/agent-session-renew", {}
            )
            if result.get("agent_session") != self.agent_session_root:
                raise MachineTransportError("Agent Session renewal identity drifted")
            token = result.get("session_token")
            expires_at = result.get("expires_at")
            if (
                type(token) is not str
                or len(token) < 32
                or type(expires_at) not in (int, float)
                or float(expires_at) <= time.time()
            ):
                raise MachineTransportError(
                    "Agent Session renewal response is invalid"
                )
            self._agent_session_token = token
            self._agent_session_expires_at = float(expires_at)
            return result

    def release_agent_session(self, release_id, *, recover=False):
        """Release once; a lost response is recovered by an exact read only.

        Retain the old token in this client for bounded server receipt proof.
        Never renew it or use it for ordinary operations after this attempt.
        """
        with self._request_lock:
            if (not self.agent_session_root or not self._agent_session_token
                    or type(release_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", release_id)):
                raise MachineTransportError("native release identity is invalid")
            held = getattr(self, "_agent_session_release_id", None)
            if held is not None and held != release_id:
                raise MachineTransportError("native release request changed")
            if recover and held is None:
                raise MachineTransportError("native release has no retained attempt")
            if held is not None and not recover:
                raise MachineTransportError("native release requires read-only recovery")
            if not recover and self._agent_session_access != "full":
                raise MachineTransportError("native release requires full owner")
            self._agent_session_release_id = release_id
            self._agent_session_access = "release-uncertain"
            path = "/api/universal/agent-session-release-status" if recover else "/api/universal/agent-session-release"
            result = self._request_once("POST", path, {"release_id": release_id})
            if (recover and result.get("released") is False and result.get("retained") is True
                    and result.get("release_id") == release_id
                    and result.get("agent_session") == self.agent_session_root):
                self._agent_session_access = "full"
                self._agent_session_release_id = None
                return result
            if (result.get("released") is not True or result.get("release_id") != release_id
                    or result.get("agent_session") != self.agent_session_root):
                raise MachineTransportError("native release response does not match owner")
            self._agent_session_access = "released"
            return result

    def _session_link_request(self, body, *, timeout_seconds):
        """Use this already-bound client; never enroll or borrow another caller."""
        with self._request_lock:
            if (not self.agent_session_root or not self._agent_session_token
                    or self._agent_session_access != "full"):
                raise MachineTransportError("Session Link requires a fully bound Agent Session")
            return self.request("POST", "/api/universal/agent-session-link", body,
                                response_timeout_seconds=timeout_seconds)

    def session_link_scope(self) -> dict[str, object]:
        result = self._session_link_request({"phase": "scope"}, timeout_seconds=10)
        fields = ("instance_id", "destination_fingerprint")
        if any(type(result.get(key)) is not str
               or not re.fullmatch(r"[0-9a-f]{64}", result[key]) for key in fields):
            raise MachineTransportError("Session Link scope response is invalid")
        return {key: result[key] for key in fields}

    def attach_session_link(self, capability) -> dict[str, object]:
        """Transfer the host grant only inside the existing authenticated request."""
        if type(capability) is not dict or type(capability.get("instance_id")) is not str:
            raise MachineTransportError("Session Link attachment is invalid")
        result = self._session_link_request(
            {"phase": "attach", "capability": dict(capability)}, timeout_seconds=35)
        if (result.get("attached") is not True
                or result.get("instance_id") != capability["instance_id"]
                or type(result.get("expires_at")) not in (int, float)
                or not math.isfinite(result["expires_at"])):
            raise MachineTransportError("Session Link attachment response is invalid")
        # Even an unexpected server field cannot echo the bearer capability.
        return {key: result[key] for key in ("attached", "instance_id", "expires_at")}

    def detach_session_link(self) -> dict[str, object]:
        result = self._session_link_request({"phase": "detach"}, timeout_seconds=20)
        if result.get("status") not in {"ok", "uncertain"}:
            raise MachineTransportError("Session Link detach response is invalid")
        clean = {"status": result["status"]}
        for key in ("detached", "revoked", "local_call_joined", "worker_stopped"):
            if key in result:
                if type(result[key]) is not bool:
                    raise MachineTransportError("Session Link detach response is invalid")
                clean[key] = result[key]
        return clean

    def renew_runtime_presence(self) -> dict[str, object]:
        """Refresh this device-proofed session's indexed runtime presence lease."""
        with self._request_lock:
            if not self.agent_session_root or not self._agent_session_token:
                raise MachineTransportError(
                    "runtime presence requires a bound Agent Session"
                )
            body = {}
            if self._runtime_presence_generation is not None:
                body["expected_generation"] = self._runtime_presence_generation
            result = self._request_once(
                "POST", "/api/universal/runtime-presence", body
            )
            expires_at = result.get("expires_at")
            generation = result.get("generation")
            if (
                result.get("agent_session") != self.agent_session_root
                or type(result.get("runtime")) is not str
                or type(expires_at) not in (int, float)
                or float(expires_at) <= time.time()
                or type(result.get("revision")) is not int
                or type(generation) is bool
                or not isinstance(generation, int)
                or generation <= 0
            ):
                raise MachineTransportError(
                    "runtime presence response is invalid"
                )
            self._runtime_presence_expires_at = float(expires_at)
            self._runtime_presence_generation = generation
            return result

    def runtime_backend_generation(self) -> BackendGeneration:
        """Read the exact active worker generation through machine authority."""
        result = self.request("GET", "/api/universal/runtime-backend", {})
        if set(result) != {
            "application", "generation", "ownership_root", "server_url"
        }:
            raise MachineTransportError(
                "runtime backend generation response shape is invalid"
            )
        if (
            type(result["application"]) is not str
            or not result["application"]
            or type(result["server_url"]) is not str
            or not result["server_url"].startswith("http://127.0.0.1:")
            or type(result["generation"]) is not int
            or result["generation"] <= 0
            or type(result["ownership_root"]) is not str
            or not result["ownership_root"]
        ):
            raise MachineTransportError(
                "runtime backend generation response values are invalid"
            )
        return BackendGeneration(
            result["server_url"],
            result["generation"],
            result["ownership_root"],
        )

    def _governed_runtime_handoff(
        self,
        phase: str,
        work_root: str,
        backend: BackendGeneration,
    ) -> dict[str, object]:
        if not self.agent_session_root:
            raise MachineTransportError(
                "runtime handoff requires a bound Agent Session"
            )
        if phase not in {"prepare", "finalize"}:
            raise MachineTransportError("runtime handoff phase is invalid")
        if type(work_root) is not str or not work_root:
            raise MachineTransportError("runtime handoff Work is invalid")
        if type(backend) is not BackendGeneration:
            raise MachineTransportError("runtime handoff backend is invalid")
        result = self.request("POST", "/api/universal/runtime-handoff", {
            "phase": phase,
            "work": work_root,
            "server_url": backend.url,
            "generation": backend.generation,
            "ownership_root": backend.ownership_root,
        })
        expected = {
            "application", "agent_session", "generation", "ownership_root",
            "phase", "work",
        }
        if phase == "finalize":
            expected.add("signal_after_response")
        if set(result) != expected:
            raise MachineTransportError("runtime handoff response shape is invalid")
        expected_phase = "draining" if phase == "prepare" else "released"
        if (
            result["agent_session"] != self.agent_session_root
            or result["generation"] != backend.generation
            or result["ownership_root"] != backend.ownership_root
            or result["phase"] != expected_phase
            or result["work"] != work_root
            or (
                phase == "finalize"
                and result["signal_after_response"] is not True
            )
        ):
            raise MachineTransportError("runtime handoff response binding failed")
        return result

    def prepare_runtime_handoff(
        self, work_root: str, backend: BackendGeneration
    ) -> dict[str, object]:
        return self._governed_runtime_handoff("prepare", work_root, backend)

    def finalize_runtime_handoff(
        self, work_root: str, backend: BackendGeneration
    ) -> dict[str, object]:
        return self._governed_runtime_handoff("finalize", work_root, backend)

    def baboom_context(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Read BABOOM's content-free graph lens for one live projection."""
        result = self.request(
            "GET",
            "/api/universal/baboom-context",
            {},
            response_timeout_seconds=response_timeout_seconds,
        )
        # The exact shape the graph projects. It stayed frozen at the twelve
        # keys of an earlier lens while the projection grew five more, so
        # this reader could not accept any real response (2026-09-07).
        expected = {
            "cell_native", "context_lens", "revision", "work", "workshop",
            "attention", "presence", "activity", "meeting_notes", "device",
            "persona_form", "suggestion",
            "agents", "brain", "canvas", "hosts", "update",
        }
        if set(result) != expected:
            raise MachineTransportError("BABOOM context response shape is invalid")
        if (
            result["cell_native"] is not True
            or result["context_lens"] != "app:baboom-context:v3"
            or type(result["revision"]) is not int
            or result["revision"] < 0
            or type(result["persona_form"]) is not str
            or type(result["suggestion"]) is not str
        ):
            raise MachineTransportError("BABOOM context response values are invalid")
        work = result["work"]
        attention = result["attention"]
        workshop = result["workshop"]
        presence = result["presence"]
        activity = result["activity"]
        meeting_notes = result["meeting_notes"]
        device = result["device"]
        if (
            not isinstance(work, dict)
            or set(work) != {"total", "open", "claimed", "blocked", "review"}
            or any(type(value) is not int or value < 0 for value in work.values())
            or not isinstance(attention, dict)
            or set(attention) != {
                "open_obligations", "blocked_obligations", "active_focus",
            }
            or type(attention["open_obligations"]) is not int
            or attention["open_obligations"] < 0
            or type(attention["blocked_obligations"]) is not int
            or attention["blocked_obligations"] < 0
            or type(attention["active_focus"]) is not bool
            or not isinstance(workshop, dict)
            or set(workshop) not in (
                {"entry_count", "category_counts"},
                {"entry_count", "category_counts", "category_counts_complete"},
            )
            or type(workshop.get("category_counts_complete", True)) is not bool
            or (workshop.get("category_counts_complete") is False
                and workshop.get("category_counts") != {})
            or type(workshop["entry_count"]) is not int
            or workshop["entry_count"] < 0
            or not isinstance(workshop["category_counts"], dict)
            or any(
                type(name) is not str or type(count) is not int or count < 0
                for name, count in workshop["category_counts"].items()
            )
            or not isinstance(presence, dict)
            or set(presence) != {
                "active_runtime_sessions", "baboom_connected",
                "baboom_action_capability_active",
            }
            or type(presence["active_runtime_sessions"]) is not int
            or presence["active_runtime_sessions"] < 0
            or type(presence["baboom_connected"]) is not bool
            or type(presence["baboom_action_capability_active"]) is not bool
            or not isinstance(activity, dict)
            or set(activity) != {"active_baboom_devices", "foreground_apps"}
            or type(activity["active_baboom_devices"]) is not int
            or activity["active_baboom_devices"] < 0
            or not isinstance(activity["foreground_apps"], dict)
            or any(
                type(name) is not str or type(count) is not int or count < 0
                for name, count in activity["foreground_apps"].items()
            )
            or not isinstance(meeting_notes, dict)
            or set(meeting_notes) != {"active_sessions"}
            or type(meeting_notes["active_sessions"]) is not int
            or meeting_notes["active_sessions"] < 0
            or not isinstance(device, dict)
            or set(device) != {
                "enrollment_handoff_available", "current_runtime_proven",
                "active_baboom_devices", "native_identity_provider_configured",
                "issued_cloud_sessions", "remote_gateway_serving",
            }
            or type(device["active_baboom_devices"]) is not int
            or device["active_baboom_devices"] < 0
            or type(device["issued_cloud_sessions"]) is not int
            or device["issued_cloud_sessions"] < 0
            or any(
                type(device[name]) is not bool
                for name in (
                    "enrollment_handoff_available", "current_runtime_proven",
                    "native_identity_provider_configured", "remote_gateway_serving",
                )
            )
        ):
            raise MachineTransportError("BABOOM context response values are invalid")
        return result

    def baboom_native_frame(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Read one expiring BABOOM context/directive/report frame."""
        result = self.request(
            "GET",
            "/api/universal/baboom-native-frame",
            {},
            response_timeout_seconds=response_timeout_seconds,
        )
        return validate_baboom_native_frame_payload(result)

    def resolve_baboom_command(self, *, utterance: str) -> dict[str, object]:
        """Resolve text through the graph-held BABOOM command vocabulary."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("BABOOM command utterance is invalid")
        result = self.request("POST", "/api/universal/baboom-command", {
            "utterance": utterance,
        })
        if (
            set(result) != {"catalog", "intent", "payload", "revision"}
            or result.get("catalog") != "app:baboom-command-catalog:v1"
            or type(result.get("intent")) is not str
            or type(result.get("payload")) is not str
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError("BABOOM command resolution is invalid")
        return result

    def respond_baboom_command(self, *, utterance: str) -> dict[str, object]:
        """Read the detailed founder-safe response for one command."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("BABOOM command utterance is invalid")
        result = self.request("POST", "/api/universal/baboom-command-response", {
            "utterance": utterance,
        })
        command = result.get("command")
        response = result.get("response")
        if (
            set(result) != {"command", "response"}
            or not isinstance(command, dict)
            or not isinstance(response, dict)
            or type(command.get("intent")) is not str
            or type(response.get("kind")) is not str
            or type(response.get("summary")) is not str
            or not isinstance(response.get("data"), dict)
        ):
            raise MachineTransportError("BABOOM command response is invalid")
        return result

    def execute_baboom_command(self, *, utterance: str) -> dict[str, object]:
        """Create one explicit founder-assigned Work through graph authority."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("BABOOM command utterance is invalid")
        result = self.request("POST", "/api/universal/baboom-command-execute", {
            "utterance": utterance,
        })
        # Assigning Work has its own exact shape and keeps its exact check.
        if result.get("intent") == "assign-task":
            if (
                set(result) != {"catalog", "intent", "work", "external_key", "created", "state", "revision"}
                or result.get("catalog") != "app:baboom-command-catalog:v1"
                or type(result.get("work")) is not str
                or type(result.get("external_key")) is not str
                or type(result.get("created")) is not bool
                or result.get("state") != "open"
                or type(result.get("revision")) is not int
            ):
                raise MachineTransportError("BABOOM command execution is invalid")
            return result
        # Every OTHER act BABOOM performs -- run an engine on the graph, send or
        # interrupt an agent -- reports what it did: kind, one sentence, data.
        # Before 2026-09-04 this validator admitted assign-task alone, so those
        # acts could not cross the transport at all.
        command = result.get("command")
        if (
            not isinstance(command, Mapping)
            or command.get("catalog") != "app:baboom-command-catalog:v1"
            or type(result.get("kind")) is not str
            or not result["kind"]
            or type(result.get("summary")) is not str
            or not result["summary"]
            or not isinstance(result.get("data"), Mapping)
            or set(result) - {"kind", "summary", "data", "command"}
        ):
            raise MachineTransportError("BABOOM command execution is invalid")
        return result

    def record_baboom_activity(self, *, app: str) -> dict[str, object]:
        """Renew one released, content-free foreground app activity lease."""
        if type(app) is not str or not app:
            raise ValueError("BABOOM activity app is invalid")
        result = self.request("POST", "/api/universal/baboom-activity", {"app": app})
        expires_at = result.get("expires_at")
        if (
            set(result) != {"activity", "app", "expires_at", "agent_session", "revision"}
            or type(result.get("activity")) is not str
            or result.get("app") != app
            or type(expires_at) not in (int, float)
            or result.get("agent_session") != self.agent_session_root
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError("BABOOM activity response is invalid")
        return result

    def record_baboom_steward_signal(
        self,
        *,
        fingerprint: str,
        source: str,
        summary: str,
    ) -> dict[str, object]:
        """Persist one bounded observation through the released BABOOM route."""
        if (
            type(fingerprint) is not str
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            or type(source) is not str
            or type(summary) is not str
        ):
            raise MachineTransportError("BABOOM Steward signal request is invalid")
        result = self.request("POST", "/api/universal/baboom-steward-signal", {
            "fingerprint": fingerprint,
            "source": source,
            "summary": summary,
        })
        if (
            set(result) != {"signal", "agent_session", "revision"}
            or type(result["signal"]) is not str
            or not result["signal"].startswith("app:baboom-steward-signal:")
            or result["agent_session"] != self.agent_session_root
            or type(result["revision"]) is not int
            or result["revision"] < 0
        ):
            raise MachineTransportError("BABOOM Steward signal response is invalid")
        return result

    def create_device_handoff_work(
        self,
        *,
        title: str,
        description: str,
        priority: int,
        scope: str,
        target_device_custody: str,
        handoff_key: str,
        payload_digest: str,
        expires_at: float,
        x: float,
        y: float,
    ) -> dict[str, object]:
        """Create one device-targeted Work through the primary graph."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "device handoff requires a bound device-proof Agent Session"
            )
        result = self.request("POST", "/api/universal/work-handoff", {
            "title": title,
            "description": description,
            "priority": priority,
            "scope": scope,
            "target_device_custody": target_device_custody,
            "handoff_key": handoff_key,
            "payload_digest": payload_digest,
            "expires_at": expires_at,
            "x": x,
            "y": y,
        })
        if (
            not isinstance(result.get("work_root"), str)
            or not isinstance(result.get("membership_wire"), str)
            or not isinstance(result.get("handoff_root"), str)
            or not isinstance(result.get("source_device_custody"), str)
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError("device handoff creation response is invalid")
        return result

    def create_device_handoff_work_for_device_ref(
        self,
        *,
        title: str,
        description: str,
        priority: int,
        scope: str,
        target_device_ref: str,
        handoff_key: str,
        payload_digest: str,
        expires_at: float,
        x: float,
        y: float,
    ) -> dict[str, object]:
        """Create a handoff from one opaque, graph-resolved device selector."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "device handoff requires a bound device-proof Agent Session"
            )
        result = self.request("POST", "/api/universal/work-handoff", {
            "title": title,
            "description": description,
            "priority": priority,
            "scope": scope,
            "target_device_ref": target_device_ref,
            "handoff_key": handoff_key,
            "payload_digest": payload_digest,
            "expires_at": expires_at,
            "x": x,
            "y": y,
        })
        if (
            not isinstance(result.get("work_root"), str)
            or not isinstance(result.get("membership_wire"), str)
            or not isinstance(result.get("handoff_root"), str)
            or not isinstance(result.get("source_device_custody"), str)
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError(
                "selected device handoff creation response is invalid"
            )
        return result

    def list_device_handoffs(self) -> dict[str, object]:
        """Read this device's custody-filtered handoffs from the graph."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "device handoff projection requires a bound device-proof Agent Session"
            )
        result = self.request("GET", "/api/universal/work-handoff")
        expected = {
            "projection", "application", "agent_session", "device_custody",
            "revision", "items",
        }
        if (
            set(result) != expected
            or result.get("projection") != "device-handoff-v1"
            or result.get("agent_session") != self.agent_session_root
            or not isinstance(result.get("application"), str)
            or not isinstance(result.get("device_custody"), str)
            or type(result.get("revision")) is not int
            or not isinstance(result.get("items"), (list, tuple))
        ):
            raise MachineTransportError("device handoff projection response is invalid")
        return result

    def list_work_claim_transfers(self) -> dict[str, object]:
        """Read this device's content-free claim continuations from the graph."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "work claim transfer projection requires a bound device-proof Agent Session"
            )
        result = self.request("GET", "/api/universal/work-claim-transfer")
        expected = {
            "projection", "application", "agent_session", "device_custody",
            "revision", "items",
        }
        if (
            set(result) != expected
            or result.get("projection") != "work-claim-transfer-v1"
            or result.get("agent_session") != self.agent_session_root
            or not isinstance(result.get("application"), str)
            or not isinstance(result.get("device_custody"), str)
            or type(result.get("revision")) is not int
            or not isinstance(result.get("items"), (list, tuple))
        ):
            raise MachineTransportError(
                "work claim transfer projection response is invalid"
            )
        return result

    def initiate_work_claim_transfer(
        self,
        *,
        work_root: str,
        target_device_ref: str,
        transfer_key: str,
        confirmation_digest: str,
        expires_at: float,
    ) -> dict[str, object]:
        """Release one claimed Work into a target-only graph reservation."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "work claim transfer requires a bound device-proof Agent Session"
            )
        result = self.request("POST", "/api/universal/work-claim-transfer", {
            "root": work_root,
            "target_device_ref": target_device_ref,
            "transfer_key": transfer_key,
            "confirmation_digest": confirmation_digest,
            "expires_at": expires_at,
        })
        expected = {
            "application", "workshop", "compliance_observation",
            "compliance_evidence", "transfer_key", "state", "expires_at",
            "target_device_ref", "policy_revision", "release_receipt_root",
            "revision", "reused",
        }
        if (
            set(result) != expected
            or result.get("state") != "released"
            or result.get("transfer_key") != transfer_key
            or result.get("target_device_ref") != target_device_ref
            or type(result.get("expires_at")) not in (int, float)
            or type(result.get("policy_revision")) is not int
            or not isinstance(result.get("release_receipt_root"), str)
            or type(result.get("revision")) is not int
            or type(result.get("reused")) is not bool
        ):
            raise MachineTransportError("work claim transfer response is invalid")
        return result

    def claim_work_claim_transfer(self, transfer_key: str) -> dict[str, object]:
        """Claim one incoming target-custody reservation by its opaque key."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "work claim transfer requires a bound device-proof Agent Session"
            )
        result = self.request(
            "POST", "/api/universal/work-claim-transfer-claim",
            {"transfer_key": transfer_key},
        )
        required = {
            "application", "workshop", "compliance_observation",
            "compliance_evidence", "claimed", "reused", "work",
            "history_root", "revision", "status",
        }
        if (
            set(result) != required
            or result.get("claimed") is not True
            or result.get("reused") is not False
            or not isinstance(result.get("work"), dict)
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError("work claim transfer claim response is invalid")
        return result

    def cancel_work_claim_transfer(
        self, *, transfer_key: str, cancellation_digest: str,
    ) -> dict[str, object]:
        """Cancel one source-owned continuation without creating another Work."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "work claim transfer cancellation requires a bound device-proof Agent Session"
            )
        result = self.request(
            "POST",
            "/api/universal/work-claim-transfer-cancel",
            {
                "transfer_key": transfer_key,
                "cancellation_digest": cancellation_digest,
            },
        )
        expected = {
            "application", "workshop", "compliance_observation",
            "compliance_evidence", "transfer_key", "state",
            "cancellation_receipt_root", "revision", "reused",
        }
        if (
            set(result) != expected
            or result.get("transfer_key") != transfer_key
            or result.get("state") != "cancelled"
            or not isinstance(result.get("cancellation_receipt_root"), str)
            or type(result.get("revision")) is not int
            or type(result.get("reused")) is not bool
        ):
            raise MachineTransportError(
                "work claim transfer cancellation response is invalid"
            )
        return result

    def record_device_handoff_receipt(
        self,
        *,
        handoff_key: str,
        kind: str,
        receipt_digest: str,
    ) -> dict[str, object]:
        """Append a bounded delivery or cancellation receipt to the graph."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "device handoff receipt requires a bound device-proof Agent Session"
            )
        result = self.request("POST", "/api/universal/work-handoff-receipt", {
            "handoff_key": handoff_key,
            "kind": kind,
            "receipt_digest": receipt_digest,
        })
        if (
            not isinstance(result.get("handoff_root"), str)
            or not isinstance(result.get("receipt_root"), str)
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError("device handoff receipt response is invalid")
        return result

    def browser_handoff(self) -> dict[str, object]:
        """Issue a one-use visible browser handoff through the active authority."""
        return self.request("POST", "/api/universal/browser-handoff", {})

    def browser_handoff_status(self) -> dict[str, object]:
        """Read visible browser handoff readiness without issuing a token."""
        return self.request("GET", "/api/universal/browser-handoff", {})

    def founder_attention_briefing(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Read the bounded founder-local Focus and Obligation explanation."""
        result = self.request(
            "GET",
            "/api/universal/attention",
            {"projection": "founder-briefing"},
            response_timeout_seconds=response_timeout_seconds,
        )
        expected = {
            "application", "agent_session", "projection", "revision", "focus",
            "open_obligations", "blocked_obligations", "protected", "truncated",
            "obligations",
        }
        if set(result) != expected:
            raise MachineTransportError("founder attention briefing response is invalid")
        focus = result["focus"]
        if (
            not isinstance(result["application"], str)
            or not isinstance(result["agent_session"], str)
            or result["projection"] != "founder-local-attention-briefing"
            or type(result["revision"]) is not int
            or result["revision"] < 0
            or type(result["open_obligations"]) is not int
            or result["open_obligations"] < 0
            or type(result["blocked_obligations"]) is not int
            or result["blocked_obligations"] < 0
            or type(result["protected"]) is not int
            or result["protected"] < 0
            or type(result["truncated"]) is not bool
            or type(focus) is not dict
            or set(focus) != {"active", "label", "reasons"}
            or type(focus["active"]) is not bool
            or not isinstance(focus["label"], str)
            or not isinstance(focus["reasons"], list)
            or len(focus["reasons"]) > 4
            or not isinstance(result["obligations"], list)
            or len(result["obligations"]) > 3
            or result["protected"] > len(result["obligations"])
        ):
            raise MachineTransportError("founder attention briefing response is invalid")
        if any(not isinstance(reason, str) for reason in focus["reasons"]):
            raise MachineTransportError("founder attention reasons are invalid")
        for obligation in result["obligations"]:
            if (
                type(obligation) is not dict
                or set(obligation) != {"priority", "state", "label", "protected"}
                or not isinstance(obligation["priority"], str)
                or not isinstance(obligation["state"], str)
                or not isinstance(obligation["label"], str)
                or type(obligation["protected"]) is not bool
            ):
                raise MachineTransportError(
                    "founder attention obligation is invalid"
                )
        return result

    def founder_baboom_steward_briefing(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Read one revision-bound founder-local BABOOM oversight lens."""
        result = self.request(
            "GET",
            "/api/universal/baboom-steward-briefing",
            {"projection": "founder-briefing"},
            response_timeout_seconds=response_timeout_seconds,
        )
        expected = {
            "projection", "revision", "context", "governed_work",
            "workshop", "attention",
        }
        if (
            set(result) != expected
            or result.get("projection") != "founder-local-baboom-steward-briefing"
            or type(result.get("revision")) is not int
            or result["revision"] < 0
            or not all(
                isinstance(result.get(name), dict)
                for name in ("context", "governed_work", "workshop", "attention")
            )
        ):
            raise MachineTransportError("founder BABOOM Steward briefing is invalid")
        return result

    def founder_workshop_report(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Read the bounded founder-local Workshop projection.

        The transport validates its compact schema so an older raw Workshop
        endpoint cannot be mistaken for the protected report surface.
        """
        result = self.request(
            "GET",
            "/api/universal/workshop",
            {"projection": "founder-report"},
            response_timeout_seconds=response_timeout_seconds,
        )
        expected = {
            "application", "agent_session", "workshop", "projection",
            "revision", "count", "protected", "truncated", "entries",
        }
        if set(result) != expected:
            raise MachineTransportError("founder Workshop report response is invalid")
        if (
            not isinstance(result["application"], str)
            or not isinstance(result["agent_session"], str)
            or not isinstance(result["workshop"], str)
            or result["projection"] != "founder-local-workshop-report"
            or type(result["revision"]) is not int
            or type(result["count"]) is not int
            or type(result["protected"]) is not int
            or type(result["truncated"]) is not bool
            or not isinstance(result["entries"], list)
            or len(result["entries"]) > 8
        ):
            raise MachineTransportError("founder Workshop report response is invalid")
        for entry in result["entries"]:
            if (
                type(entry) is not dict
                or set(entry) != {"sequence", "kind", "text", "created_at", "protected"}
                or type(entry["sequence"]) is not int
                or not isinstance(entry["kind"], str)
                or not isinstance(entry["text"], str)
                or not isinstance(entry["created_at"], str)
                or type(entry["protected"]) is not bool
            ):
                raise MachineTransportError("founder Workshop report entry is invalid")
        return result

    def founder_device_custody_report(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Read the bounded founder-only device custody posture."""
        result = self.request(
            "GET",
            "/api/universal/devices",
            {"projection": "founder-report"},
            response_timeout_seconds=response_timeout_seconds,
        )
        expected = {
            "application", "agent_session", "projection", "revision",
            "registered", "active", "revoked", "hardware_backed",
            "reported", "truncated", "devices",
        }
        if set(result) != expected:
            raise MachineTransportError(
                "founder device custody response is invalid"
            )
        counts = ("revision", "registered", "active", "revoked", "hardware_backed", "reported")
        if (
            not isinstance(result["application"], str)
            or not isinstance(result["agent_session"], str)
            or result["projection"] != "founder-local-device-custody-report"
            or any(type(result[name]) is not int or result[name] < 0 for name in counts)
            or type(result["truncated"]) is not bool
            or not isinstance(result["devices"], list)
            or result["reported"] != len(result["devices"])
            or len(result["devices"]) > 12
            or result["active"] + result["revoked"] != result["registered"]
        ):
            raise MachineTransportError(
                "founder device custody response is invalid"
            )
        refs: set[str] = set()
        for device in result["devices"]:
            if (
                type(device) is not dict
                or set(device) != {
                    "device_ref", "label", "state", "hardware_backed",
                    "baboom_bound", "runtime_present", "baboom_present",
                }
                or type(device["device_ref"]) is not str
                or len(device["device_ref"]) != 31
                or not device["device_ref"].startswith("device_")
                or any(ch not in "0123456789abcdef" for ch in device["device_ref"][7:])
                or not isinstance(device["label"], str)
                or device["state"] not in {"active", "revoked"}
                or any(
                    type(device[name]) is not bool
                    for name in (
                        "hardware_backed", "baboom_bound", "runtime_present",
                        "baboom_present",
                    )
                )
                or device["baboom_present"] and not device["runtime_present"]
                or device["runtime_present"] and device["state"] != "active"
            ):
                raise MachineTransportError(
                    "founder device custody row is invalid"
                )
            if device["device_ref"] in refs:
                raise MachineTransportError(
                    "founder device custody selector is duplicated"
                )
            refs.add(device["device_ref"])
        return result

    def revoke_founder_device_custody(
        self,
        *,
        device_ref: str,
        reason_code: str,
    ) -> dict[str, object]:
        """Request one explicit founder device-custody revocation."""
        if (
            type(device_ref) is not str
            or len(device_ref) != 31
            or not device_ref.startswith("device_")
            or any(ch not in "0123456789abcdef" for ch in device_ref[7:])
            or type(reason_code) is not str
            or reason_code not in {
                "access-removed", "compromised", "lost", "retired",
            }
        ):
            raise MachineTransportError(
                "founder device custody revocation request is invalid"
            )
        result = self.request(
            "POST",
            "/api/universal/device-custody-revoke",
            {"device_ref": device_ref, "reason_code": reason_code},
        )
        expected = {
            "application", "agent_session", "device_ref", "state",
            "reason_code", "revision",
        }
        if (
            set(result) != expected
            or not isinstance(result["application"], str)
            or not isinstance(result["agent_session"], str)
            or result["device_ref"] != device_ref
            or result["state"] != "revoked"
            or result["reason_code"] != reason_code
            or type(result["revision"]) is not int
            or result["revision"] < 0
        ):
            raise MachineTransportError(
                "founder device custody revocation response is invalid"
            )
        return result

    def claim_next_work(self) -> dict[str, object]:
        if not self.agent_session_root:
            raise MachineTransportError(
                "next work requires a bound runtime Agent Session"
            )
        return self.request("POST", "/api/universal/work-next", {})

    def current_claimed_work(self) -> dict[str, str] | None:
        """Read the one graph-held Work currently claimed by this session."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "current work requires a bound runtime Agent Session"
            )
        result = self.request("GET", "/api/universal/work-current", {})
        if (
            not isinstance(result, dict)
            or result.get("agent_session") != self.agent_session_root
            or type(result.get("revision")) is not int
            or isinstance(result.get("revision"), bool)
        ):
            raise MachineTransportError("current Work response is invalid")
        work = result.get("work")
        if work is None:
            return None
        if (
            not isinstance(work, dict)
            or set(work) != {"root", "title"}
            or not isinstance(work.get("root"), str)
            or not work["root"]
            or not isinstance(work.get("title"), str)
            or not work["title"].strip()
        ):
            raise MachineTransportError("current Work response is invalid")
        return {"root": work["root"], "title": work["title"]}

    def current_claimed_work_detail(self) -> dict[str, object]:
        """Read this session's claimed Work interfaces and exact claim metadata.

        Preserve the snapshot revision for consumers. This read is not an
        approved execution plan and does not include review/complete Work.
        The response wait is ten seconds; renewal and pipe connection setup
        remain outside a strict wall-clock deadline.
        """
        return self._current_work_projection("detail", frozenset({"claimed"}))

    def work_release_recovery(self, work_root: str, claim_binding: str, after_revision: int) -> dict[str, object]:
        """Inspect exact original-claim history; false remains unresolved."""
        if not self.agent_session_root:
            raise MachineTransportError("Work release recovery requires a bound runtime Agent Session")
        result = self.request("GET", "/api/universal/work-current", {
            "projection": "release-recovery", "work_root": work_root,
            "claim_binding": claim_binding, "after_revision": after_revision,
        }, response_timeout_seconds=10.0)
        if (type(result) is not dict or set(result) != {"projection", "work_root", "agent_session",
                "claim_binding", "revision", "after_revision", "released", "history_root", "receipt_reconstructed"}
                or result["projection"] != "release-recovery" or result["work_root"] != work_root
                or result["agent_session"] != self.agent_session_root or result["claim_binding"] != claim_binding
                or result["after_revision"] != after_revision or type(result["revision"]) is not int
                or type(after_revision) is not int or result["revision"] < after_revision
                or type(result["released"]) is not bool or result["receipt_reconstructed"] is not False
                or (result["released"] and (type(result["history_root"]) is not str or not result["history_root"]))
                or (not result["released"] and result["history_root"] is not None)):
            raise MachineTransportError("Work release recovery projection is invalid")
        return result

    def selected_work_configuration(self, work_root, *, revision_id=None):
        result = self.request('GET', '/api/universal/work-current',
            {'projection':'selected-configuration', 'work_root':work_root,
             **({'revision_id':revision_id} if revision_id is not None else {})}, response_timeout_seconds=15.0)
        if (type(result) is not dict or result.get('agent_session') != self.agent_session_root
                or result.get('projection') != 'selected-configuration'
                or type(result.get('work')) is not dict or result['work'].get('root') != work_root
                or type(result['work'].get('configuration')) is not dict
                or type(result.get('revision')) is not int
                or result['work']['configuration'].get('revision') != result['revision']):
            raise MachineTransportError('Selected Work configuration response is invalid')
        return result

    def configure_selected_work(self, proposal, *, reconcile=False):
        result = self.request('POST', '/api/universal/work-configuration',
            {**proposal, 'phase':'reconcile' if reconcile else 'stage'}, response_timeout_seconds=20.0)
        if (type(result) is not dict or result.get('agent_session') != self.agent_session_root
                or result.get('work_root') != proposal['work_root']
                or result.get('revision_id') != proposal['revision_id']
                or type(result.get('revision')) is not int
                or result['revision'] < proposal['expected_revision']
                or result.get('execution_authorized') is not False
                or result.get('projection') != ('configuration-recovery' if reconcile else 'configuration-result')):
            raise MachineTransportError('Native Work configuration outcome is uncertain')
        if reconcile:
            if (type(result.get('applied')) is not bool or type(result.get('staged')) is not bool
                    or type(result.get('not_staged')) is not bool
                    or result['staged'] and result['not_staged']
                    or result.get('receipt_reconstructed') is not False):
                raise MachineTransportError('Native Work configuration recovery is invalid')
        elif (type(result.get('configuration')) is not dict
                or result['configuration'].get('staged') is not True
                or type(result['configuration'].get('applied')) is not bool
                or result['configuration'].get('revision_id') != proposal['revision_id']
                or result['configuration'].get('revision') != result['revision']):
            raise MachineTransportError('Native Work configuration application is unconfirmed')
        return result

    def current_work_configuration(self) -> dict[str, object]:
        """Read bounded configuration of this authenticated session's current Work."""
        if not self.agent_session_root:
            raise MachineTransportError("Work configuration requires a bound runtime Agent Session")
        result = self.request("GET", "/api/universal/work-current", {"projection": "configuration"},
                              response_timeout_seconds=10.0)
        if (type(result) is not dict or set(result) != {"agent_session", "work", "projection", "revision"}
                or result["agent_session"] != self.agent_session_root or result["projection"] != "configuration"
                or type(result["revision"]) is not int or result["revision"] < 0
                or len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > 65536):
            raise MachineTransportError("Work configuration envelope is invalid")
        work = result["work"]
        if work is not None:
            if (type(work) is not dict or set(work) != {"root", "configuration"}
                    or type(work["root"]) is not str or not work["root"].startswith("assembly-instance:")
                    or len(work["root"].encode("utf-8")) > 512 or type(work["configuration"]) is not dict):
                raise MachineTransportError("Work configuration identity is invalid")
            config = work["configuration"]
            if (config.get("revision") != result["revision"] or config.get("state") != "claimed"
                    or config.get("editable") is not False or type(config.get("fields")) is not dict
                    or set(config["fields"]) != {"inputs", "requirements", "cde-container"}):
                raise MachineTransportError("Work configuration projection is invalid")
        return result

    def current_work_assignment(self) -> dict[str, object]:
        """Read one pending assignment (claimed/review/blocked), never approval.

        Null means no pending assignment, not completion proof. The response
        wait is ten seconds; renewal/connection setup has no absolute deadline.
        """
        return self._current_work_projection("assignment", frozenset({"claimed", "review", "blocked"}))

    def _current_work_projection(self, projection: str, states: frozenset[str]) -> dict[str, object]:
        if not self.agent_session_root:
            raise MachineTransportError("current Work " + projection + " requires a bound runtime Agent Session")
        result = self.request("GET", "/api/universal/work-current", {"projection": projection},
                              response_timeout_seconds=10.0)
        if (type(result) is not dict
                or set(result) != {"agent_session", "revision", "projection", "work"}
                or result["agent_session"] != self.agent_session_root
                or result["projection"] != projection
                or type(result["revision"]) is not int or result["revision"] < 0):
            raise MachineTransportError("current Work " + projection + " envelope is invalid")
        work = result["work"]
        if work is None:
            return result
        def root(value):
            return type(value) is str and bool(value.strip()) and len(value.encode("utf-8")) <= 512
        if (type(work) is not dict or not root(work.get("root"))
                or not work["root"].startswith("assembly-instance:")
                or work.get("claimant_session") != self.agent_session_root
                or not root(work.get("claimant_agent_body")) or not root(work.get("claim_binding"))
                or type(work.get("interfaces")) not in (list, tuple)
                or not 0 < len(work["interfaces"]) <= 256
                or type(work.get("operational")) is not dict
                or type(work["operational"].get("current_state_label")) is not str
                or work["operational"]["current_state_label"].casefold() not in states):
            raise MachineTransportError("current Work " + projection + " claim is invalid")
        names, roots = set(), set()
        for interface in work["interfaces"]:
            if (type(interface) is not dict or interface.get("owner") != work["root"]
                    or not root(interface.get("id")) or not root(interface.get("target"))
                    or not root(interface.get("name")) or type(interface.get("value")) is not str
                    or interface["id"] in roots or interface["name"] in names):
                raise MachineTransportError("current Work " + projection + " interface is invalid")
            roots.add(interface["id"])
            names.add(interface["name"])
        if projection == "assignment":
            requirements = work.get("requirements")
            interfaces = [item for item in work["interfaces"] if item["name"] == "requirements"]
            if (type(requirements) is not dict
                    or set(requirements) != {"interface", "target", "wired", "value"}
                    or len(interfaces) != 1
                    or requirements["interface"] != interfaces[0]["id"]
                    or requirements["target"] != interfaces[0]["target"]
                    or type(requirements["wired"]) is not bool
                    or (not requirements["wired"] and requirements["value"] is not None)):
                raise MachineTransportError("current Work assignment requirements are invalid")
        return result

    def issue_cde_write_permit(
        self,
        *,
        operation: str,
        path: str,
        content_digest: str,
        request_id: str,
        nonce: str,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Request one short-lived permit derived from this session's Work.

        Optional timeout bounds the response wait, not renewal or connection.
        """
        if not self.agent_session_root:
            raise MachineTransportError(
                "CDE write permit requires a bound runtime Agent Session"
            )
        if any(
            type(value) is not str or not value
            for value in (operation, path, request_id, nonce)
        ):
            raise MachineTransportError("CDE write permit request is invalid")
        if (
            type(content_digest) is not str
            or len(content_digest) != 64
            or any(character not in "0123456789abcdef" for character in content_digest)
        ):
            raise MachineTransportError(
                "CDE write permit content digest is invalid"
            )
        timeout_options = {}
        if response_timeout_seconds is not None:
            if (not isinstance(response_timeout_seconds, (int, float))
                    or isinstance(response_timeout_seconds, bool)
                    or not 0 < response_timeout_seconds <= _default_machine_response_timeout(
                        "POST", "/api/universal/cde-write-permit")):
                raise MachineTransportError("universal runtime response timeout is invalid")
            timeout_options["response_timeout_seconds"] = float(response_timeout_seconds)
        result = self.request(
            "POST",
            "/api/universal/cde-write-permit",
            {
                "operation": operation,
                "path": path,
                "content_digest": content_digest,
                "request_id": request_id,
                "nonce": nonce,
            },
            **timeout_options,
        )
        expected = {
            "permit", "agent_session", "work", "claim_binding",
            "container_root", "container_id", "container_digest",
            "operation", "path", "content_digest", "request_id",
            "authority_revision", "expires_at", "revision",
        }
        if (
            not isinstance(result, dict)
            or set(result) != expected
            or result["agent_session"] != self.agent_session_root
            or result["operation"] != operation
            or result["path"] != path.replace("\\", "/")
            or result["content_digest"] != content_digest
            or result["request_id"] != request_id
            or any(
                type(result[name]) is not str or not result[name]
                for name in (
                    "permit", "work", "claim_binding", "container_root",
                    "container_id", "container_digest",
                )
            )
            or len(result["container_digest"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in result["container_digest"]
            )
            or type(result["authority_revision"]) is not int
            or type(result["revision"]) is not int
            or result["authority_revision"] != result["revision"]
            or type(result["expires_at"]) not in (int, float)
        ):
            raise MachineTransportError(
                "CDE write permit response is invalid"
            )
        return result

    def consume_cde_write_permit(
        self,
        *,
        permit: str,
        operation: str,
        path: str,
        content_digest: str,
        request_id: str,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Record one exact write result against its graph-held permit.

        Optional timeout bounds the response wait, not renewal or connection.
        """
        if not self.agent_session_root:
            raise MachineTransportError(
                "CDE write receipt requires a bound runtime Agent Session"
            )
        if any(
            type(value) is not str or not value
            for value in (permit, operation, path, request_id)
        ):
            raise MachineTransportError("CDE write receipt request is invalid")
        if (
            type(content_digest) is not str
            or len(content_digest) != 64
            or any(character not in "0123456789abcdef" for character in content_digest)
        ):
            raise MachineTransportError(
                "CDE write receipt content digest is invalid"
            )
        timeout_options = {}
        if response_timeout_seconds is not None:
            if (not isinstance(response_timeout_seconds, (int, float))
                    or isinstance(response_timeout_seconds, bool)
                    or not 0 < response_timeout_seconds <= _default_machine_response_timeout(
                        "POST", "/api/universal/cde-write-receipt")):
                raise MachineTransportError("universal runtime response timeout is invalid")
            timeout_options["response_timeout_seconds"] = float(response_timeout_seconds)
        result = self.request(
            "POST",
            "/api/universal/cde-write-receipt",
            {
                "permit": permit,
                "operation": operation,
                "path": path,
                "content_digest": content_digest,
                "request_id": request_id,
            },
            **timeout_options,
        )
        expected = {
            "receipt", "permit", "kind", "receipt_digest",
            "agent_session", "work", "claim_binding", "container_root",
            "revision",
        }
        if (
            not isinstance(result, dict)
            or set(result) != expected
            or result["permit"] != permit
            or result["kind"] != "consumed"
            or result["agent_session"] != self.agent_session_root
            or any(
                type(result[name]) is not str or not result[name]
                for name in (
                    "receipt", "work", "claim_binding", "container_root"
                )
            )
            or type(result["receipt_digest"]) is not str
            or len(result["receipt_digest"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in result["receipt_digest"]
            )
            or type(result["revision"]) is not int
        ):
            raise MachineTransportError(
                "CDE write receipt response is invalid"
            )
        return result

    def claim_work(self, work_root: str, *, expected_revision: int | None = None) -> dict[str, object]:
        """Claim one exact open governed Work under this Agent Session."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "exact work claim requires a bound runtime Agent Session"
            )
        if type(work_root) is not str or not work_root:
            raise MachineTransportError("exact work claim target is invalid")
        body = {"root":work_root}
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision < 0:
                raise MachineTransportError("exact work claim revision is invalid")
            body["expected_revision"] = expected_revision
        return self.request("POST", "/api/universal/work-claim", body)

    def recover_work_claim(
        self,
        work_root: str,
        evidence: str,
        *,
        projection: str = "status",
        expected_claimant: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        """Recover and claim work abandoned by a stale runtime capability."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "stale work claim recovery requires a bound runtime Agent Session"
            )
        if type(work_root) is not str or not work_root:
            raise MachineTransportError("stale work claim recovery target is invalid")
        if type(evidence) is not str:
            raise MachineTransportError("stale work claim recovery evidence is invalid")
        if projection not in {"status", "index"}:
            raise MachineTransportError(
                "stale work claim recovery projection is invalid"
            )
        body: dict[str, object] = {"root": work_root, "evidence": evidence}
        if expected_claimant is not None or expected_revision is not None:
            if (type(expected_claimant) is not str or not expected_claimant
                    or type(expected_revision) is not int or expected_revision < 0):
                raise MachineTransportError("stale work claim recovery admission is invalid")
            body.update(expected_claimant=expected_claimant, expected_revision=expected_revision)
        if projection == "index":
            body["projection"] = "index"
        return self.request(
            "POST",
            "/api/universal/work-claim-recover",
            body,
        )

    def bind_runtime_device_custody(
        self,
        *,
        runtime: str,
        custody_root: str,
    ) -> dict[str, object]:
        """Bind one enrolled custody root through a founder machine session."""
        if not self.agent_session_root:
            raise MachineTransportError(
                "runtime device custody binding requires a bound founder Agent Session"
            )
        result = self.request(
            "POST",
            "/api/universal/agent-body-device-custody",
            {"runtime": runtime, "custody_root": custody_root},
        )
        if (
            result.get("runtime") != runtime
            or type(result.get("catalog_entry")) is not str
            or type(result.get("agent_body")) is not str
            or result.get("custody_root") != custody_root
            or type(result.get("revision")) is not int
        ):
            raise MachineTransportError(
                "runtime device custody binding response is invalid"
            )
        return result

    def adjudicate_work(
        self,
        work_root: str,
        *,
        projection: str = "status",
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        if not self.agent_session_root:
            raise MachineTransportError(
                "work court requires a bound runtime Agent Session"
            )
        if projection not in {"status", "index"}:
            raise MachineTransportError("work court projection is invalid")
        body: dict[str, object] = {"root": work_root}
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision < 0:
                raise MachineTransportError("work court expected revision is invalid")
            body["expected_revision"] = expected_revision
        if projection == "index":
            body["projection"] = "index"
        return self.request(
            "POST", "/api/universal/work-court", body
        )

    def recover_work_court(
        self,
        work_root: str,
        evidence: str,
        *,
        projection: str = "status",
    ) -> dict[str, object]:
        if not self.agent_session_root:
            raise MachineTransportError(
                "stale work court recovery requires a bound runtime Agent Session"
            )
        if type(work_root) is not str or not work_root:
            raise MachineTransportError("stale work court recovery target is invalid")
        if type(evidence) is not str:
            raise MachineTransportError("stale work court recovery evidence is invalid")
        if projection not in {"status", "index"}:
            raise MachineTransportError(
                "stale work court recovery projection is invalid"
            )
        body: dict[str, object] = {"root": work_root, "evidence": evidence}
        if projection == "index":
            body["projection"] = "index"
        return self.request(
            "POST", "/api/universal/work-court-recover", body
        )

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        request_id: str | None = None,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Send one authenticated request with an optional caller wait bound.

        Authority, request binding, and the server's execution are unchanged.
        The bound only controls how long this caller waits for a response. It
        lets non-authoritative projections such as BABOOM's context lens fail
        fast instead of inheriting the long court/work timeout.
        """
        self._check_cancelled()
        with self._request_lock:
            self._check_cancelled()
            if self._agent_session_access in {"release-uncertain", "released"}:
                raise MachineTransportError("native owner released or release uncertain; use exact release recovery")
            if (
                self.agent_session_root
                and self._agent_session_access == "full"
                and path != "/api/universal/agent-session-renew"
                and time.time() >= self._agent_session_expires_at - 60.0
            ):
                self.renew_agent_session()
            return self._request_once(
                method,
                path,
                body,
                request_id=request_id,
                response_timeout_seconds=response_timeout_seconds,
            )

    def _request_once(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        request_id: str | None = None,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        self._check_cancelled()
        descriptor = _read_descriptor(self.descriptor_path, self.key_provider)
        if descriptor.status != "active":
            raise MachineTransportError("universal runtime is not active")
        if self._pinned_runtime_descriptor is not None and descriptor != self._pinned_runtime_descriptor:
            raise MachineTransportError("universal runtime owner changed; reconnect through admitted enrollment")
        material = self.key_provider.resolve(
            descriptor.key_id, descriptor.key_version
        )
        identity = request_id or secrets.token_hex(16)
        request_body = dict(body or {})
        session = {}
        if self.agent_session_root and self._agent_session_token:
            proof = hmac.new(
                self._agent_session_token.encode("utf-8"),
                session_proof_payload(
                    runtime_id=descriptor.runtime_id,
                    request_id=identity,
                    method=method,
                    path=path,
                    body=request_body,
                    session_root=self.agent_session_root,
                    capability_id=(self._agent_session_capability_id or None),
                ),
                hashlib.sha256,
            ).hexdigest()
            session = {"root": self.agent_session_root, "proof": proof}
            if self._agent_session_capability_id:
                session["capability"] = self._agent_session_capability_id
        request = {
            "runtime_id": descriptor.runtime_id,
            "request_id": identity,
            "method": method,
            "path": path,
            "body": request_body,
            "session": session,
        }
        raw = _canonical(request)
        if len(raw) > _MAX_MESSAGE_BYTES:
            raise MachineTransportError("machine request exceeds its size limit")
        try:
            connection = Client(
                descriptor.pipe, family="AF_PIPE", authkey=material.secret
            )
        except (EOFError, OSError) as exc:
            raise MachineTransportError("universal runtime pipe is unavailable") from exc
        try:
            self._check_cancelled()
            connection.send_bytes(raw)
            default_timeout = _default_machine_response_timeout(method, path)
            if response_timeout_seconds is None:
                response_timeout = default_timeout
            elif (
                not isinstance(response_timeout_seconds, (int, float))
                or isinstance(response_timeout_seconds, bool)
                or not 0 < float(response_timeout_seconds) <= default_timeout
            ):
                raise MachineTransportError("universal runtime response timeout is invalid")
            else:
                response_timeout = float(response_timeout_seconds)
            if self._cancellation_event is None:
                if not connection.poll(response_timeout):
                    raise MachineTransportError("universal runtime did not respond")
            else:
                deadline = time.monotonic() + response_timeout
                while True:
                    self._check_cancelled()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MachineTransportError("universal runtime did not respond")
                    if connection.poll(min(0.1, remaining)):
                        self._check_cancelled()
                        break
            response = json.loads(
                connection.recv_bytes(_MAX_MESSAGE_BYTES).decode("utf-8")
            )
        except (EOFError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MachineTransportError("universal runtime response is invalid") from exc
        finally:
            connection.close()
        expected = {"ok", "runtime_id", "request_id"}
        if (
            type(response) is not dict
            or not expected.issubset(response)
            or response["runtime_id"] != descriptor.runtime_id
            or response["request_id"] != identity
        ):
            raise MachineTransportError("universal runtime response binding failed")
        if response["ok"] is False:
            if response.get("effect_outcome") == "unknown":
                raise MachineTransportError(str(response.get("error") or "request outcome unknown"))
            raise MachineResponseError(str(response.get("error") or "request denied"))
        if response["ok"] is not True:
            raise MachineTransportError("universal runtime response status is invalid")
        result = response.get("result")
        if type(result) is not dict:
            raise MachineTransportError("universal runtime result is invalid")
        return result


__all__ = [
    "BABOOM_NATIVE_FRAME_PROJECTION",
    "BABOOM_NATIVE_REPORT_KIND",
    "BABOOM_NATIVE_REPORT_SUMMARY",
    "MachineTransportError",
    "MachineResponseError",
    "RuntimeDescriptor",
    "UniversalRuntimeClient",
    "UniversalRuntimeTransport",
    "default_runtime_descriptor_path",
    "inspect_runtime_descriptor",
    "recover_stale_runtime_descriptor",
    "inspect_stopped_runtime_durable_journal",
    "inspect_stopped_runtime_offline_activity",
    "inspect_stopped_runtime_recovery_activity",
    "inspect_stopped_runtime_trusted_checkpoint",
    "stopped_runtime_restart_database",
    "runtime_device_proof_payload",
    "session_proof_payload",
    "validate_baboom_native_frame_payload",
]
