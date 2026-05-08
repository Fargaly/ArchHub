"""Revit broker — multi-session router for the in-Revit MCP listeners.

Architecture (v0.27.5+)
-----------------------
Every Revit instance now binds its OWN free port from the range
[48884..48899] and publishes a session file at:

    %LOCALAPPDATA%\\ArchHub\\sessions\\revit-{pid}.json

Each session file is rewritten every 10 s as a heartbeat. When Revit
shuts down it deletes its file. When Revit crashes the file goes stale
and we prune it after 30 s of silence.

Public API
----------
    list_sessions(*, prune=True)        -> list[Session]
    pick_session(prefer=None)            -> Session | None
    forward(session, path, *, body=None,
            method="GET", timeout=2.0)   -> dict
    is_any_alive()                       -> bool
    cleanup_stale()                      -> int   (count pruned)
    sessions_count()                     -> int   (alive sessions)

Why this exists
---------------
Old behaviour: only ONE Revit instance could load RevitMCP.dll because
the listener hard-coded port 48884. Two Revit instances → second one's
listener silently failed (port collision). Closing that one Revit
killed the only listener — ArchHub thought Revit was dead even if
another instance was open. This module + the v0.3.0 RevitMCP DLL fix
both.

Legacy DLLs (v0.2.0) still bind 48884 directly and publish no session
file. We pick those up via a fallback probe of port 48884 so a stale
deployment still works during the rolling DLL upgrade.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SESSIONS_DIR = (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                / "ArchHub" / "sessions")

# Stale threshold — sessions that haven't heartbeat'd within this many
# seconds AND don't respond to a probe get pruned. Generous so we don't
# kill a session that's mid-long-running command.
STALE_AFTER_SECONDS = 30.0

# Port range — must match RevitMCPApp.cs.
PORT_FIRST = 48884
PORT_LAST = 48899

# Legacy fallback (v0.2.0 DLL).
LEGACY_PORT = 48884


@dataclass
class Session:
    session_id:    str
    family:        str
    pid:           int
    port:          int
    version:       str
    doc_title:     str
    started_at:    str
    last_heartbeat: str
    file_path:     Optional[Path] = None
    legacy:        bool = False
    healthy:       bool = False

    def url(self, path: str = "/ping") -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"http://localhost:{self.port}{path}"


# ---------------------------------------------------------------------------
def _read_session_file(p: Path) -> Optional[Session]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return Session(
            session_id=str(d.get("session_id") or p.stem),
            family=str(d.get("family") or "revit"),
            pid=int(d.get("pid") or 0),
            port=int(d.get("port") or 0),
            version=str(d.get("version") or ""),
            doc_title=str(d.get("doc_title") or ""),
            started_at=str(d.get("started_at") or ""),
            last_heartbeat=str(d.get("last_heartbeat") or d.get("started_at") or ""),
            file_path=p,
        )
    except Exception:
        return None


def _seconds_since(iso: str) -> float:
    if not iso:
        return 1e9
    try:
        ts = datetime.fromisoformat(iso.rstrip("Z"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return 1e9


def _probe(port: int, *, timeout: float = 0.4) -> bool:
    """Quick TCP connect probe — cheaper than a full HTTP /ping."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_http(port: int, *, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/ping", timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


# ---------------------------------------------------------------------------
def list_sessions(*, prune: bool = True) -> list[Session]:
    """Return all known Revit sessions, newest-heartbeat first.

    `prune` — also delete stale session files (>30 s silence + dead port).
    """
    out: list[Session] = []
    if SESSIONS_DIR.exists():
        for p in sorted(SESSIONS_DIR.glob("revit-*.json")):
            s = _read_session_file(p)
            if s is None:
                continue
            silent_for = _seconds_since(s.last_heartbeat)
            alive = _probe(s.port, timeout=0.3)
            s.healthy = alive
            if not alive and silent_for > STALE_AFTER_SECONDS:
                if prune:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                continue
            out.append(s)

    # Legacy v0.2.0 DLL fallback — single hardcoded port, no session file.
    # Only add if no v0.3.0+ session is already present on that port.
    if not any(s.port == LEGACY_PORT for s in out):
        if _probe(LEGACY_PORT, timeout=0.3):
            out.append(Session(
                session_id="revit-legacy",
                family="revit",
                pid=0,
                port=LEGACY_PORT,
                version="legacy(<=0.2)",
                doc_title="",
                started_at="",
                last_heartbeat="",
                legacy=True,
                healthy=True,
            ))

    # Sort: healthiest + newest heartbeat first.
    out.sort(
        key=lambda s: (
            0 if s.healthy else 1,
            -_seconds_since(s.last_heartbeat) * -1,  # newer = smaller seconds-since
        )
    )
    return out


def pick_session(prefer: Optional[str] = None) -> Optional[Session]:
    """Choose one session.

    `prefer` — match against session_id, pid (str), or doc_title substring.
    Falls back to most-recent healthy.
    """
    sessions = list_sessions()
    healthy = [s for s in sessions if s.healthy]
    if not healthy:
        return None
    if prefer:
        prefer = str(prefer).strip().lower()
        for s in healthy:
            if (prefer in s.session_id.lower()
                or prefer == str(s.pid)
                or (s.doc_title and prefer in s.doc_title.lower())):
                return s
    return healthy[0]


def is_any_alive() -> bool:
    return bool(list_sessions(prune=False))


def sessions_count() -> int:
    return sum(1 for s in list_sessions(prune=False) if s.healthy)


def cleanup_stale() -> int:
    """Force-prune stale session files. Returns count removed."""
    if not SESSIONS_DIR.exists():
        return 0
    removed = 0
    for p in SESSIONS_DIR.glob("revit-*.json"):
        s = _read_session_file(p)
        if s is None:
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
            continue
        silent = _seconds_since(s.last_heartbeat)
        if silent > STALE_AFTER_SECONDS and not _probe(s.port, timeout=0.3):
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    return removed


# ---------------------------------------------------------------------------
def forward(session: Session, path: str, *, body: Optional[bytes] = None,
            method: str = "GET", timeout: float = 5.0) -> dict:
    """Forward an HTTP call to the chosen session. Returns parsed JSON
    or {'status': 'error', 'error': ...}."""
    url = session.url(path)
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw) if raw else {"status": "ok"}
            except Exception:
                return {"status": "ok", "raw": raw}
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}",
                "session": session.session_id}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "session": session.session_id}
