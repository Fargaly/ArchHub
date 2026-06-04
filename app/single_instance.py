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
Stale lock file is auto-recovered: if connect to old port fails,
the new instance steals the lock and starts fresh.
"""
from __future__ import annotations

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


def _read_existing_port() -> Optional[int]:
    if not _LOCK_FILE.exists():
        return None
    try:
        text = _LOCK_FILE.read_text(encoding="utf-8").strip()
        return int(text)
    except Exception:
        return None


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
    existing = _read_existing_port()
    if not existing:
        return True
    if not _ping(existing):
        return True  # stale lock — nobody home, treat as quit
    try:
        return _quit(existing, timeout=timeout)
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
    existing = _read_existing_port()
    if existing and _ping(existing):
        # An instance is running. reopen=latest: only when the caller wired a
        # predicate AND it says "there is new code" do we try to take over.
        # Any error in the predicate, a False result, or a failed/timed-out
        # quit all fall through to summon-and-exit (today's exact behaviour).
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

    # Either no lock, stale lock, or we just superseded the old instance.
    # Bind a fresh ephemeral port.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((_HOST, 0))
    except OSError:
        # Couldn't bind — let the caller continue anyway, single-instance
        # protection silently disabled.
        return True
    sock.listen(8)
    port = sock.getsockname()[1]

    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE.write_text(str(port), encoding="utf-8")

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
    """Best-effort lock cleanup. Call from atexit."""
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
    except Exception:
        pass
