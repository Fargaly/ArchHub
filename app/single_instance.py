"""Single-instance lock + summon-existing-window pattern.

Prevents the 'click icon, nothing happens' bug:
  Before — VBS spawns pythonw, ChatWindow's hidden state stays
            hidden, second instance dies silently behind X-button
            close-to-tray, no window comes to front.
  After  — first launch creates a TCP listener on 127.0.0.1 in an
            ephemeral port range; writes the port number into a
            lock file at %LOCALAPPDATA%/ArchHub/.single-instance.
            Second launch reads the lock file, sends 'SHOW' to that
            port, then exits 0. Existing instance receives 'SHOW',
            calls window.show_centered() + activates.

reopen=latest (founder, 2026-06-04 — "tackle this from the roots"):
  The summon path above strands new code. The running install app is
  the post-sync child (launched with --no-dev-source-sync) so it never
  re-syncs; on a SECOND launch, the old behaviour SUMMONS the stale
  instance (SHOW) and exits — it never asks whether the repo has NEW
  code. So committed code never reaches the running app unless the
  founder FULLY quits + reopens (non-obvious with close-to-tray).
  Fix: a launch may pass `should_supersede` to acquire_or_summon. When
  an instance is running AND that predicate says "there is new code to
  load", we send 'QUIT' to the old instance (graceful app-quit + lock
  release), wait — bounded — for the lock to free, then fall through to
  bind a fresh port so THIS launch becomes the listener and continues
  into normal startup (where it syncs + starts on the new code). The
  branch is gated + graceful-degrades: no predicate, predicate False,
  or any error/timeout → summon exactly as before.

Cross-platform-safe (TCP loopback works on Windows + Linux + Mac).

STALE-LOCK HARDENING (founder #70, 2026-06-22 — "survive a missing/stale lock"):
  A MISSING or STALE lock must NEVER refuse the launch and must NEVER spawn a
  duplicate. "Stale" has THREE independent detectors, any one of which reclaims:
    1. PORT DEAD  — the lock's port no longer answers our PING handshake
       (crash-without-release: the original liveness check; still primary).
    2. PID DEAD   — the lock records the owning PID; if that process is gone
       the lock is stale even if some UNRELATED process recycled the port
       (a foreign listener can't crash us into refusing to start).
    3. TOO OLD    — the lock records a write timestamp; a lock older than
       ``_LOCK_MAX_AGE_SEC`` whose PID we cannot positively confirm alive is
       treated as a leftover and reclaimed (belt-and-braces for the rare case
       a recycled PID confuses the alive check).
  A lock is considered LIVE only when it positively passes ALL applicable
  checks (PID alive when known AND port answers PING). Anything else is
  reclaimed: the lock is rewritten atomically and THIS launch becomes the
  single instance. The legacy bare-port lock format is still read (treated as
  unknown PID/ts) so an in-flight upgrade never strands a running app.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional


_LOCK_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
_LOCK_FILE = _LOCK_DIR / ".single-instance"
_HOST = "127.0.0.1"
_HEARTBEAT = "PING\n"
_SHOW = "SHOW\n"
_QUIT = "QUIT\n"

# A lock older than this whose owner PID can't be confirmed alive is reclaimed.
# Generous (a real instance refreshes nothing but keeps answering PING, so the
# PORT-DEAD + PID-DEAD checks carry liveness; this age is only the last-ditch
# guard against a recycled-PID + recycled-port coincidence).
_LOCK_MAX_AGE_SEC = 7 * 24 * 3600


def _pid_alive(pid: Optional[int]) -> Optional[bool]:
    """Cross-platform 'is this PID running?' check.

    Returns True (alive), False (definitely gone), or None (unknown — we could
    not determine it, e.g. PID not recorded or the OS check was inconclusive).
    None is treated conservatively by callers (fall back to the PING check), so
    an inconclusive result never causes us to wrongly steal a live lock NOR to
    wrongly refuse to start over a dead one.

    No Qt, no third-party deps — safe at module-import time, before
    QApplication exists (single_instance runs at the very top of boot)."""
    if not pid or pid <= 0:
        return None
    try:
        if sys.platform == "win32":
            # OpenProcess(SYNCHRONIZE) succeeds for a live PID; ERROR_INVALID_
            # PARAMETER (87) means no such process. A still-open handle to an
            # EXITED process returns WAIT_OBJECT_0 from WaitForSingleObject, so
            # we distinguish a running process (WAIT_TIMEOUT) from a zombie.
            import ctypes
            SYNCHRONIZE = 0x00100000
            # use_last_error=True so ctypes.get_last_error() reflects the real
            # Win32 error from OpenProcess (the shared windll handle does not
            # capture it -> we'd read 0 and wrongly return None / inconclusive).
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not handle:
                err = ctypes.get_last_error()
                # ERROR_ACCESS_DENIED (5) => the process EXISTS (owned by another
                # user / elevated): treat as alive. ERROR_INVALID_PARAMETER (87)
                # => no such PID.
                if err == 5:
                    return True
                if err == 87:
                    return False
                return None
            try:
                WAIT_TIMEOUT = 0x00000102
                rc = kernel32.WaitForSingleObject(handle, 0)
                return rc == WAIT_TIMEOUT  # signalled => exited; timeout => alive
            finally:
                kernel32.CloseHandle(handle)
        else:
            # POSIX: signal 0 probes existence without delivering a signal.
            # ESRCH => gone; EPERM => exists but not ours (alive).
            import errno
            try:
                os.kill(int(pid), 0)
                return True
            except OverflowError:
                # pid too large for pid_t (e.g. a recorded 4e9 value) -> it
                # cannot name a running process -> DEFINITELY dead, not unknown.
                # Returning None here would fall through to the PING check and a
                # recycled foreign listener could keep a dead lock alive,
                # refusing to start. (POSIX-only; Windows OpenProcess -> err 87.)
                return False
            except OSError as ex:  # noqa: PERF203
                if ex.errno == errno.ESRCH:
                    return False
                if ex.errno == errno.EINVAL:
                    # invalid/out-of-range pid value -> not a live process.
                    return False
                if ex.errno == errno.EPERM:
                    return True
                return None
    except Exception:
        return None


def _read_lock() -> Optional[dict]:
    """Parse the lock file into ``{port, pid, ts}`` (pid/ts may be None for the
    legacy bare-port format), or None when absent/unparseable.

    Tolerates BOTH the new JSON format ``{"port":N,"pid":N,"ts":F}`` and the
    legacy plain-integer port file (pre-#70) — a running pre-upgrade instance
    must never be mis-read as stale."""
    if not _LOCK_FILE.exists():
        return None
    try:
        raw = _LOCK_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw:
        return None
    # New JSON format.
    if raw[:1] == "{":
        try:
            d = json.loads(raw)
            port = int(d.get("port"))
            pid = d.get("pid")
            ts = d.get("ts")
            return {"port": port,
                    "pid": int(pid) if pid not in (None, "") else None,
                    "ts": float(ts) if ts not in (None, "") else None}
        except Exception:
            return None
    # Legacy bare-port format: unknown pid/ts -> liveness falls back to PING.
    try:
        port = int(raw)
        ts = None
        try:
            ts = _LOCK_FILE.stat().st_mtime
        except Exception:
            ts = None
        return {"port": port, "pid": None, "ts": ts}
    except Exception:
        return None


def _read_existing_port() -> Optional[int]:
    """Back-compat shim: the bare owning port (new JSON or legacy format)."""
    d = _read_lock()
    return d["port"] if d else None


def _is_lock_stale(d: Optional[dict]) -> bool:
    """True when the lock should be RECLAIMED (missing / dead-port / dead-pid /
    too-old). The single source of truth for "can I take this lock?".

    A lock is LIVE (returns False) only when it positively passes every
    applicable check: the owner PID (when recorded) is alive AND the port
    answers our PING handshake. If the PID is recorded and DEFINITELY dead, the
    lock is stale immediately — no need to PING (a recycled foreign listener on
    the same port can't keep a dead instance's lock alive). If the PID is
    unknown/inconclusive we defer to the PING check (legacy locks, cross-user).
    A very old lock whose PID we can't confirm alive is reclaimed as a leftover.
    """
    if not d:
        return True  # missing lock -> reclaim (start cleanly)
    # Detector 2 — PID DEAD. If the lock records an owner PID and that process
    # is DEFINITELY gone, the lock is stale outright: a foreign process that
    # recycled the same port can't keep a dead instance's lock alive, and we
    # don't even need to PING.
    pid = d.get("pid")
    if pid and _pid_alive(pid) is False:
        return True

    # Detector 1 — PORT DEAD. The lock is LIVE only if its port answers our PING
    # handshake. A dead/wedged/recycled-by-something-else port means there is no
    # ArchHub instance to summon, so we must reclaim — never refuse to start.
    port = d.get("port")
    if not port or not _ping(int(port)):
        return True

    # Detector 3 — TOO OLD. The port answered, but if the lock is ancient AND we
    # cannot positively confirm the recorded PID is alive (recycled PID + a
    # foreign listener answering a PING-shaped probe is a vanishingly rare
    # coincidence, but we guard it), treat it as a leftover and reclaim.
    ts = d.get("ts")
    if (ts and (time.time() - float(ts)) > _LOCK_MAX_AGE_SEC
            and not (pid and _pid_alive(pid) is True)):
        return True

    return False  # LIVE — PID not dead, port answers, not an unconfirmed antique


def _write_lock(port: int) -> None:
    """Atomically write the lock with our port + PID + timestamp.

    Atomic = write a temp file in the SAME dir then ``os.replace`` (atomic on
    Windows + POSIX), so a concurrent reader never sees a half-written lock and
    a reclaim can't race a torn file. Best-effort: falls back to a direct write
    if the atomic replace is unavailable."""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"port": int(port), "pid": int(os.getpid()),
                          "ts": time.time()})
    tmp = _LOCK_FILE.with_name(_LOCK_FILE.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(_LOCK_FILE))
    except Exception:
        try:
            _LOCK_FILE.write_text(payload, encoding="utf-8")
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass


def _ping(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((_HOST, port), timeout=timeout) as s:
            s.sendall(_HEARTBEAT.encode())
            data = s.recv(64)
            return data.startswith(b"PONG")
    except Exception:
        return False


def _summon(port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((_HOST, port), timeout=timeout) as s:
            s.sendall(_SHOW.encode())
            return True
    except Exception:
        return False


def _quit(port: int, timeout: float = 4.0) -> bool:
    """Ask the running instance to quit gracefully, then wait — bounded —
    for it to release the lock (stop answering PING).

    Returns True ONLY when the old instance is confirmed gone (its port no
    longer answers) within `timeout`. On any connect error, send error, or
    timeout it returns False so the caller graceful-degrades to summon.

    The whole operation is hard-bounded by `timeout` so a wedged old
    instance can never hang the new launch — worst case the founder gets
    the old window (exactly today's behaviour)."""
    deadline = time.monotonic() + timeout
    # 1) Send QUIT and read the BYE ack. A short connect/recv budget keeps
    #    a half-dead peer from eating the whole deadline here.
    try:
        with socket.create_connection((_HOST, port), timeout=1.5) as s:
            s.settimeout(1.5)
            s.sendall(_QUIT.encode())
            try:
                s.recv(64)  # expect b"BYE\n"; absence is non-fatal, we poll below
            except Exception:
                pass
    except Exception:
        return False
    # 2) Poll until the old listener stops answering (lock released by the
    #    graceful shutdown tail), bounded by the remaining deadline.
    while time.monotonic() < deadline:
        if not _ping(port, timeout=0.5):
            return True
        try:
            time.sleep(0.1)
        except Exception:
            pass
    # Final check right at the deadline.
    return not _ping(port, timeout=0.5)


def quit_existing(timeout: float = 4.0) -> bool:
    """Public helper: if an instance is running, ask it to quit and wait
    (bounded) for the lock to free. Returns True when no instance is
    running afterwards (either none was, or the running one quit). Returns
    False if an instance is still alive after `timeout`.

    Used by the reopen=latest path so a fresh launch can take over after
    new code is detected. Safe + graceful: any error → False (caller falls
    back to summon / normal startup)."""
    d = _read_lock()
    if not d:
        return True
    if _is_lock_stale(d):
        return True  # stale lock (dead port / dead PID / too old) — nobody home
    try:
        return _quit(int(d["port"]), timeout=timeout)
    except Exception:
        return False


def quit_running_instance(timeout: float = 4.0) -> bool:
    """Sync-path alias of quit_existing (reopen=latest PRIMARY fix).

    dev_source_sync.maybe_sync_and_relaunch calls this in the PARENT, before
    it relaunches the synced child + os._exit(0): if an old single-instance is
    running on stale code, ask it to QUIT and wait — bounded by `timeout` — for
    the lock to free, so the relaunched child finds NO instance and becomes the
    listener on the NEW code. Returns True when no instance is running afterwards
    (none was, stale lock, or the running one quit); False if one is still alive
    after `timeout`. Graceful by construction (delegates to quit_existing): any
    error → False, and the caller syncs + relaunches regardless (worst case =
    today's behaviour). Plain socket calls only — no Qt — so it is safe at
    module-import time, before QApplication exists."""
    return quit_existing(timeout=timeout)


def acquire_or_summon(
    on_summon: Callable[[], None],
    *,
    should_supersede: Optional[Callable[[], bool]] = None,
    on_quit: Optional[Callable[[], None]] = None,
) -> bool:
    """If another ArchHub is already running, ask it to show + return False
    so the second process exits. Otherwise become the listener and return
    True so the caller continues into normal startup.

    `on_summon` is called from a worker thread when a future second
    launch hits us — it must be thread-safe / queue back to the main
    Qt thread.

    `should_supersede` (reopen=latest, optional): a predicate the caller
    wires to "is there new code to load?" (e.g. dev_source_sync.needs_sync).
    When an instance is already running AND this predicate returns True, we
    ask the old instance to QUIT, wait — bounded — for it to release the
    lock, and on success fall through to bind a fresh port (this launch
    becomes the listener + continues into startup, where it syncs + starts
    fresh). When the predicate is absent / returns False / raises, OR the
    quit times out, we summon-and-exit exactly as before (graceful degrade).

    `on_quit` (optional): called from a worker thread when a future launch
    asks US to quit (mirrors `on_summon`). Must marshal a graceful
    QApplication.quit() back to the main Qt thread."""
    # Read + classify the lock ONCE. A MISSING or STALE lock (dead port / dead
    # owner PID / too-old leftover) is reclaimed — we fall straight through to
    # bind a fresh port and become the single instance. We NEVER refuse to start
    # over a stale lock, and we NEVER summon a dead instance (that would just
    # fail silently and leave the user with no window).
    existing_lock = _read_lock()
    is_stale = _is_lock_stale(existing_lock)
    existing = existing_lock["port"] if (existing_lock and not is_stale) else None

    if existing is not None:
        # A LIVE instance is confirmed running. reopen=latest: only when the
        # caller wired a predicate AND it says "there is new code" do we try to
        # take over. Any error in the predicate, a False result, or a
        # failed/timed-out quit all fall through to summon-and-exit (today's
        # exact behaviour).
        if should_supersede is not None:
            superseded = False
            try:
                if should_supersede():
                    if _quit(existing):
                        superseded = True  # old instance gone → become the new listener
            except Exception:
                superseded = False  # any error → summon exactly as before
            if not superseded:
                _summon(existing)
                return False
            # Fall through: lock is free, bind a fresh port below.
        else:
            # Tell the running instance to show, then walk away.
            _summon(existing)
            return False

    # Either no lock, a stale lock we just reclaimed, or we superseded a live
    # instance. Bind a fresh ephemeral port + atomically claim the lock with our
    # PID + timestamp, so the NEXT launch can detect us as live (or, if we die,
    # detect our dead PID and reclaim cleanly).
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((_HOST, 0))
    except OSError:
        # Couldn't bind — let the caller continue anyway, single-instance
        # protection silently disabled.
        return True
    sock.listen(8)
    port = sock.getsockname()[1]

    _write_lock(port)

    threading.Thread(target=_serve_forever,
                     args=(sock, on_summon),
                     kwargs={"on_quit": on_quit},
                     daemon=True).start()
    return True


def _serve_forever(
    sock: socket.socket,
    on_summon: Callable[[], None],
    *,
    on_quit: Optional[Callable[[], None]] = None,
) -> None:
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        try:
            with conn:
                conn.settimeout(2)
                data = conn.recv(64)
                if data.startswith(b"PING"):
                    conn.sendall(b"PONG\n")
                elif data.startswith(b"SHOW"):
                    try:
                        on_summon()
                    except Exception:
                        pass
                    conn.sendall(b"OK\n")
                elif data.startswith(b"QUIT"):
                    # reopen=latest: a fresh launch detected new code and is
                    # taking over. Ack first so the client can begin polling
                    # for our lock to release, THEN trigger a graceful quit
                    # (marshalled to the Qt main thread by the caller). The
                    # clean-shutdown tail + atexit release() free the lock;
                    # this daemon thread dies with the process.
                    try:
                        conn.sendall(b"BYE\n")
                    except Exception:
                        pass
                    if on_quit is not None:
                        try:
                            on_quit()
                        except Exception:
                            pass
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


def release() -> None:
    """Best-effort lock cleanup. Call from atexit.

    Only deletes the lock if it is OURS (records our PID) — or is the legacy
    bare-port format / unparseable. This prevents a slow-exiting instance from
    clobbering a lock that a SUCCESSOR launch already reclaimed and rewrote with
    its own PID (which would leave the new instance lockless). Best-effort and
    never raises."""
    try:
        if not _LOCK_FILE.exists():
            return
        d = _read_lock()
        # Reclaim only our own / unowned lock; leave a successor's lock intact.
        if d is None or d.get("pid") in (None, os.getpid()):
            _LOCK_FILE.unlink()
    except Exception:
        pass
