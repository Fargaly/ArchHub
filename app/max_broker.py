"""3ds Max broker — multi-session router for in-Max startup scripts.

Mirrors revit_broker exactly: scans
%LOCALAPPDATA%\\ArchHub\\sessions\\max-*.json, builds Session records
(pid · port · scene file · max version · last_heartbeat), prunes stale
files. Used by connector_health and the HOSTS rail to surface
"3ds Max · 2 sess" when the architect has two Max instances open.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SESSIONS_DIR = (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                / "ArchHub" / "sessions")

STALE_AFTER_SECONDS = 30.0
PORT_FIRST = 48886
PORT_LAST = 48899
LEGACY_PORT = 48886

# Service identifier returned by max_mcp_startup.py's /max-mcp/ping
# endpoint. Verified before accepting a session as live to defeat port
# collision (Revit on 48886) showing a phantom max-legacy entry.
_EXPECTED_SERVICE = "max-mcp"
_PING_PATH = "/max-mcp/ping"


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
        return f"http://localhost:{self.port}/max-mcp{path}"


def _read_session_file(p: Path) -> Optional[Session]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return Session(
            session_id=str(d.get("session_id") or p.stem),
            family=str(d.get("family") or "max"),
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
    """Cheap TCP-only liveness — see `_probe_service` for identity-aware."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_service(port: int, *, timeout: float = 0.5) -> bool:
    return _ping_service(port, timeout=timeout) is not None


def _ping_service(port: int, *, timeout: float = 0.5) -> Optional[dict]:
    """GET /max-mcp/ping. Returns the payload dict if `service` matches
    max-mcp, else None. Drives port-range discovery."""
    try:
        with urllib.request.urlopen(
                f"http://localhost:{port}{_PING_PATH}", timeout=timeout) as r:
            if r.status >= 400:
                return None
            try:
                data = json.loads(r.read().decode("utf-8") or "{}")
            except Exception:
                return None
            if str(data.get("service") or "").lower() != _EXPECTED_SERVICE:
                return None
            return data
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _discover_in_port_range(known_ports: set,
                              *, timeout: float = 0.4) -> list[Session]:
    """Parallel port-range probe for MaxMCP. Catches instances missing
    a session file (older add-in, scrubbed file, MCP rebind)."""
    import concurrent.futures as _cf

    candidates = [p for p in range(PORT_FIRST, PORT_LAST + 1)
                  if p not in known_ports]
    if not candidates:
        return []
    found: list[Session] = []
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(
            lambda p: (p, _ping_service(p, timeout=timeout)),
            candidates,
        ))
    for port, payload in results:
        if not payload:
            continue
        found.append(Session(
            session_id=f"max-{payload.get('pid') or port}",
            family="max",
            pid=int(payload.get("pid") or 0),
            port=port,
            version=str(payload.get("version") or ""),
            doc_title=str(payload.get("doc_title") or ""),
            started_at="",
            last_heartbeat="",
            file_path=None,
            legacy=False,
            healthy=True,
        ))
    return found


def list_sessions(*, prune: bool = True) -> list[Session]:
    out: list[Session] = []
    if SESSIONS_DIR.exists():
        for p in sorted(SESSIONS_DIR.glob("max-*.json")):
            s = _read_session_file(p)
            if s is None:
                continue
            silent = _seconds_since(s.last_heartbeat)
            alive = _probe_service(s.port, timeout=0.4)
            s.healthy = alive
            if not alive and silent > STALE_AFTER_SECONDS:
                if prune:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                continue
            out.append(s)
    # Port-range discovery — covers MaxMCP instances that didn't
    # write a session file. Parallel probe with service verification.
    known_ports = {s.port for s in out}
    out.extend(_discover_in_port_range(known_ports, timeout=0.4))

    if not any(s.port == LEGACY_PORT for s in out):
        if _probe_service(LEGACY_PORT, timeout=0.4):
            out.append(Session(
                session_id="max-legacy", family="max",
                pid=0, port=LEGACY_PORT, version="legacy",
                doc_title="", started_at="", last_heartbeat="",
                legacy=True, healthy=True,
            ))
    out.sort(key=lambda s: (0 if s.healthy else 1,
                            -_seconds_since(s.last_heartbeat) * -1))
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


# ---------------------------------------------------------------------------
def forward(session: Session, path: str, *, body: Optional[bytes] = None,
            method: str = "GET", timeout: float = 30.0) -> dict:
    """Forward an HTTP call to one Max session. Path is appended after
    the /max-mcp prefix the startup script mounts on."""
    import urllib.error, urllib.request
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
