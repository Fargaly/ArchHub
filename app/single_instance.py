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

Cross-platform-safe (TCP loopback works on Windows + Linux + Mac).
Stale lock file is auto-recovered: if connect to old port fails,
the new instance steals the lock and starts fresh.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable, Optional


_LOCK_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
_LOCK_FILE = _LOCK_DIR / ".single-instance"
_HOST = "127.0.0.1"
_HEARTBEAT = "PING\n"
_SHOW = "SHOW\n"


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


def acquire_or_summon(on_summon: Callable[[], None]) -> bool:
    """If another ArchHub is already running, ask it to show + return False
    so the second process exits. Otherwise become the listener and return
    True so the caller continues into normal startup.

    `on_summon` is called from a worker thread when a future second
    launch hits us — it must be thread-safe / queue back to the main
    Qt thread."""
    existing = _read_existing_port()
    if existing and _ping(existing):
        # Tell the running instance to show, then walk away.
        _summon(existing)
        return False

    # Either no lock or stale lock. Bind a fresh ephemeral port.
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
                     daemon=True).start()
    return True


def _serve_forever(sock: socket.socket, on_summon: Callable[[], None]) -> None:
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
