"""AutoCAD broker — multi-session router for in-AutoCAD MCP listeners.

Mirrors revit_broker exactly. Scans
%LOCALAPPDATA%\\ArchHub\\sessions\\autocad-*.json. AcadMCP.dll v0.3+
writes a session file when it loads, with port + pid + drawing path
+ heartbeat. Closing one AutoCAD instance no longer kills the others.

Public API matches revit_broker / max_broker / outlook_broker so
connector_health and the HOSTS rail can treat all four interchangeably.
"""
from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SESSIONS_DIR = (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                / "ArchHub" / "sessions")
STALE_AFTER_SECONDS = 30.0
PORT_FIRST = 48885
PORT_LAST = 48899
LEGACY_PORT = 48885


@dataclass
class Session:
    session_id: str
    family: str
    pid: int
    port: int
    version: str
    doc_title: str
    started_at: str
    last_heartbeat: str
    file_path: Optional[Path] = None
    legacy: bool = False
    healthy: bool = False

    def url(self, path: str = "/ping") -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"http://localhost:{self.port}{path}"


def _read(p: Path) -> Optional[Session]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return Session(
            session_id=str(d.get("session_id") or p.stem),
            family=str(d.get("family") or "autocad"),
            pid=int(d.get("pid") or 0),
            port=int(d.get("port") or 0),
            version=str(d.get("version") or ""),
            doc_title=str(d.get("doc_title") or ""),
            started_at=str(d.get("started_at") or ""),
            last_heartbeat=str(d.get("last_heartbeat")
                                or d.get("started_at") or ""),
            file_path=p,
        )
    except Exception:
        return None


def _silent(iso: str) -> float:
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
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def list_sessions(*, prune: bool = True) -> list[Session]:
    out: list[Session] = []
    if SESSIONS_DIR.exists():
        for p in sorted(SESSIONS_DIR.glob("autocad-*.json")):
            s = _read(p)
            if s is None:
                continue
            silent = _silent(s.last_heartbeat)
            alive = _probe(s.port, timeout=0.3)
            s.healthy = alive
            if not alive and silent > STALE_AFTER_SECONDS:
                if prune:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                continue
            out.append(s)
    if not any(s.port == LEGACY_PORT for s in out):
        if _probe(LEGACY_PORT, timeout=0.3):
            out.append(Session(
                session_id="autocad-legacy", family="autocad",
                pid=0, port=LEGACY_PORT, version="legacy",
                doc_title="", started_at="", last_heartbeat="",
                legacy=True, healthy=True,
            ))
    out.sort(key=lambda s: (0 if s.healthy else 1,
                            -_silent(s.last_heartbeat) * -1))
    return out


def pick_session(prefer: Optional[str] = None) -> Optional[Session]:
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


def sessions_count() -> int:
    return sum(1 for s in list_sessions(prune=False) if s.healthy)


def is_any_alive() -> bool:
    return bool(list_sessions(prune=False))
