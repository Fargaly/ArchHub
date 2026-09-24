"""Terminal node sessions: a real shell, started in a folder of this ArchHub.

One owner per application server (ApplicationServer.terminal_sessions). A
session is one cmd.exe child (/bin/sh elsewhere) whose START folder must lie
inside the terminal root; its stdout and stderr stream into a bounded buffer
the Terminal node reads by offset; input is written line by line; Stop kills
the whole child tree. Nothing here writes the graph: a terminal is operational
state (SPEC 3.3), and its node holds only its folder and command parameters.

Not a sandbox. Only the start folder is checked. Once running, the shell is an
ordinary cmd.exe with the rights of the signed-in Windows user: it can change
folder and read, write or run anything that user can. Who may start one is the
guard: the application owner only (POST /api/universal/terminal needs
``execute`` and the owner subject; a canvas Run binds the card's engine through
``admitted_engine`` with the same check; everywhere else the card refuses).

Limits: at most MAX_SESSIONS live sessions, MAX_OUTPUT_BYTES of output kept per
session (older output is dropped and the offset says so), a lifetime of
MAX_LIFETIME_SECONDS, below-normal priority and no console window. On Windows
each shell runs in its own Job object with kill-on-close, so Stop, the reaper
and ArchHub exiting end every process the shell started, including ones started
after a tree snapshot would have been taken. Where the Job cannot be created,
Stop falls back to one psutil tree snapshot.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

MAX_SESSIONS = 4
MAX_OUTPUT_BYTES = 256 * 1024
MAX_INPUT_BYTES = 8 * 1024
MAX_LIFETIME_SECONDS = 3600.0
ENGINE_TIMEOUT_SECONDS = 60.0


class TerminalRefused(ValueError):
    """A request the terminal owner refuses; the message is safe to show."""


OWNER_ONLY = "A terminal card runs only on its owner's canvas Run."


def owner_only_engine(params, feeds):
    """library.terminal wherever no owner-checked binding was made for this run."""
    raise TerminalRefused(OWNER_ONLY)


class _Job:
    """A Windows Job object with kill-on-close; inert elsewhere or when refused."""

    def __init__(self, process):
        self._handle = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)

            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                            ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", Basic),
                            ("IoInfo", ctypes.c_ulonglong * 6),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k32.SetInformationJobObject.argtypes = (
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
            k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = k32.CreateJobObjectW(None, None)
            if not handle:
                return
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (not k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                    or not k32.AssignProcessToJobObject(handle, int(process._handle))):
                k32.CloseHandle(handle)
                return
            self._k32 = k32
            self._handle = handle
        except (OSError, AttributeError, ValueError, TypeError):
            self._handle = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def close(self, *, kill: bool) -> None:
        """Release the job; ``kill`` ends its processes first (closing does too)."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        if kill:
            self._k32.TerminateJobObject(handle, 1)
        self._k32.CloseHandle(handle)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class TerminalSession:
    def __init__(self, session_id: str, cwd: Path, process: subprocess.Popen, clock):
        self.id = session_id
        self.cwd = cwd
        self.process = process
        self._clock = clock
        self.started = clock()
        self._lock = threading.Lock()
        self._chunks: list[tuple[int, bytes]] = []  # (start offset, bytes)
        self._end = 0
        self._dropped = 0
        self.stopped = False
        self.job = _Job(process)
        self._reader = threading.Thread(target=self._read, name="archhub-terminal-" + session_id[:8], daemon=True)
        self._reader.start()

    def _read(self) -> None:
        stream = self.process.stdout
        while True:
            try:
                data = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            except (OSError, ValueError):
                break
            if not data:
                break
            with self._lock:
                self._chunks.append((self._end, data))
                self._end += len(data)
                while self._chunks and self._end - self._chunks[0][0] > MAX_OUTPUT_BYTES:
                    start, chunk = self._chunks.pop(0)
                    self._dropped = start + len(chunk)

    def output(self, since: int) -> dict:
        with self._lock:
            since = max(int(since), self._dropped)
            text = b"".join(
                chunk[max(0, since - start):] for start, chunk in self._chunks
                if start + len(chunk) > since
            )
            end = self._end
            dropped = self._dropped
        code = self.process.poll()
        return {
            "id": self.id, "cwd": str(self.cwd),
            "output": text.decode("utf-8", errors="replace"),
            "offset": since, "next": end, "dropped_before": dropped,
            "state": "running" if code is None else ("stopped" if self.stopped else "exited"),
            "exit_code": code,
        }

    def write(self, text: str) -> None:
        if self.process.poll() is not None:
            raise TerminalRefused("The terminal has ended; start a new one.")
        data = (text.rstrip("\r\n") + "\r\n").encode("utf-8")
        if len(data) > MAX_INPUT_BYTES:
            raise TerminalRefused("Terminal input exceeds 8 KB.")
        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise TerminalRefused("The terminal no longer accepts input.") from None

    def kill(self) -> None:
        """End the shell and everything it started (its Job; else one tree snapshot)."""
        self.stopped = True
        if self.job.held:
            self.job.close(kill=True)
        else:
            self._kill_tree_snapshot()
        if self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass
        self._release()

    def _kill_tree_snapshot(self) -> None:
        try:
            import psutil
            try:
                root = psutil.Process(self.process.pid)
                children = root.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                children = []
            for child in reversed(children):
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass

    def _release(self) -> None:
        """After the shell ended: wait for it, then its reader and pipes."""
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self._reader.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except (OSError, ValueError, AttributeError):
                pass


class TerminalSessions:
    """The one terminal owner for an application: admitted root, bounded sessions."""

    def __init__(self, admitted_root, *, clock=time.monotonic, shell=None, create=False):
        """``admitted_root`` bounds the START folder only; ``create`` makes it on first use."""
        root = Path(admitted_root).expanduser().resolve()
        if not create and not root.is_dir():
            raise ValueError("terminal admitted root must be an existing folder")
        self.admitted_root = root
        self._create = bool(create)
        self._clock = clock
        self._shell = shell
        self._lock = threading.Lock()
        self._sessions: dict[str, TerminalSession] = {}

    def resolve_cwd(self, cwd) -> Path:
        """The start folder, resolved (symlinks and ..), refused unless inside the root."""
        if self._create:
            try:
                self.admitted_root.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise TerminalRefused("The terminal folder could not be created.") from None
        text = str(cwd or "").strip()
        candidate = Path(text) if text else self.admitted_root
        if not candidate.is_absolute():
            candidate = self.admitted_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            raise TerminalRefused("That folder does not exist.") from None
        if not resolved.is_dir():
            raise TerminalRefused("That path is not a folder.")
        if not _inside(resolved, self.admitted_root):
            raise TerminalRefused(
                "That folder is outside this ArchHub's terminal folder (%s)." % self.admitted_root)
        return resolved

    def _argv(self):
        if self._shell is not None:
            return list(self._shell)
        if os.name == "nt":
            return [os.environ.get("COMSPEC") or "cmd.exe", "/Q", "/K"]
        return ["/bin/sh", "-i"]

    def _reap_locked(self) -> None:
        now = self._clock()
        for session in list(self._sessions.values()):
            if session.process.poll() is None and now - session.started >= MAX_LIFETIME_SECONDS:
                session.kill()
        ended = [key for key, session in self._sessions.items() if session.process.poll() is not None]
        for key in ended:
            self._sessions[key].job.close(kill=True)
        for key in ended[: max(0, len(ended) - 4 * MAX_SESSIONS)]:
            self._sessions.pop(key, None)

    def start(self, cwd=None) -> dict:
        folder = self.resolve_cwd(cwd)
        with self._lock:
            self._reap_locked()
            live = [s for s in self._sessions.values() if s.process.poll() is None]
            if len(live) >= MAX_SESSIONS:
                raise TerminalRefused("%d terminals are already running; stop one first." % MAX_SESSIONS)
            flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                     | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            process = subprocess.Popen(
                self._argv(), cwd=str(folder), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                shell=False, creationflags=flags,
            )
            session = TerminalSession(uuid.uuid4().hex, folder, process, self._clock)
            self._sessions[session.id] = session
        return session.output(0)

    def _get(self, session_id) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(str(session_id or ""))
        if session is None:
            raise TerminalRefused("No such terminal.")
        return session

    def output(self, session_id, since=0) -> dict:
        return self._get(session_id).output(int(since or 0))

    def write(self, session_id, text) -> dict:
        if type(text) is not str:
            raise TerminalRefused("Terminal input must be text.")
        session = self._get(session_id)
        session.write(text)
        return session.output(0)

    def stop(self, session_id) -> dict:
        session = self._get(session_id)
        session.kill()
        return session.output(0)

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            if session.process.poll() is None:
                session.kill()
            else:
                session.job.close(kill=True)

    def admitted_engine(self, admit):
        """library.terminal for one run whose ``admit()`` re-checks the caller at call time.

        ``admit`` raises unless the caller of this run is the application owner
        holding ``execute`` -- the check POST /api/universal/terminal makes. It
        runs before any shell starts, even for a card with no command.
        """
        def engine(params, feeds):
            admit()
            return self.engine(params, feeds)
        return engine

    def engine(self, params, feeds):
        """library.terminal on a Run: one command in the node's folder, then the shell exits."""
        command = str(params.get("command") or "").strip()
        if not command:
            for key in ("in", "text", "value"):
                if isinstance(feeds.get(key), str) and feeds[key].strip():
                    command = feeds[key].strip()
                    break
        if not command:
            # Nothing to run is not a refusal: the card is used interactively.
            return ({"out": ""},
                    "Open the terminal on this card, or set its command to run it on Run.")
        started = self.start(params.get("cwd"))
        session = self._get(started["id"])
        session.write(command)
        session.write("exit")
        deadline = self._clock() + ENGINE_TIMEOUT_SECONDS
        while session.process.poll() is None and self._clock() < deadline:
            time.sleep(0.05)
        if session.process.poll() is None:
            session.kill()
            held = session.output(0)
            return ({"out": held["output"], "ok": False, "reason": "timed out"},
                    "stopped after %d s" % ENGINE_TIMEOUT_SECONDS)
        session._reader.join(timeout=2)
        held = session.output(0)
        session.job.close(kill=True)
        return ({"out": held["output"], "ok": held["exit_code"] == 0, "exit_code": held["exit_code"]},
                "exit %s" % held["exit_code"])


__all__ = ["OWNER_ONLY", "TerminalRefused", "TerminalSession", "TerminalSessions", "owner_only_engine"]
