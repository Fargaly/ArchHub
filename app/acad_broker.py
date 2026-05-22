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
import urllib.error
import urllib.request
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

# Service identifier returned by AcadMCP.dll's /ping endpoint. The
# phantom-legacy bug — Revit hijacked port 48885 (range collision) but
# the old TCP-only probe couldn't tell — is closed by verifying the
# /ping payload's `service` field before accepting a session as live.
_EXPECTED_SERVICE = "acad-mcp"


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
    """Cheap TCP-only liveness — port is open or closed. Use
    `_probe_service` instead when the answer "wrong service is on this
    port" matters (legacy-port detection, phantom-session prevention)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_service(port: int, *, timeout: float = 0.5) -> bool:
    return _ping_service(port, timeout=timeout) is not None


def _ping_service(port: int, *, timeout: float = 0.5) -> Optional[dict]:
    """GET /ping. Returns the full payload dict if the response's
    `service` field matches AcadMCP, else None. Used by port-range
    discovery to populate Session metadata without a session file."""
    try:
        with urllib.request.urlopen(
                f"http://localhost:{port}/ping", timeout=timeout) as r:
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
    """Parallel port-range probe — finds AcadMCP instances that the
    session-file scan missed (older DLL, scrubbed file, MCP rebind).
    See revit_broker._discover_in_port_range for rationale."""
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
            session_id=f"autocad-{payload.get('pid') or port}",
            family="autocad",
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
        for p in sorted(SESSIONS_DIR.glob("autocad-*.json")):
            s = _read(p)
            if s is None:
                continue
            silent = _silent(s.last_heartbeat)
            # Verify the port's responding service IS AcadMCP — port
            # reuse / collision (Revit on 48885) would otherwise mark a
            # dead session as alive.
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
    # Port-range discovery — covers AcadMCP instances that didn't
    # write a session file. Parallel probe with service verification.
    known_ports = {s.port for s in out}
    out.extend(_discover_in_port_range(known_ports, timeout=0.4))

    if not any(s.port == LEGACY_PORT for s in out):
        # Legacy fallback fires only when the right service is on the
        # port — never on a port hijacked by another host.
        if _probe_service(LEGACY_PORT, timeout=0.4):
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


# ---------------------------------------------------------------------------
def forward(session: Session, path: str, *, body: Optional[bytes] = None,
            method: str = "GET", timeout: float = 30.0) -> dict:
    """Forward an HTTP call to one AutoCAD session."""
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
                # Audit 2026-05-21 — non-JSON 2xx is an error, not ok.
                return {"status": "error",
                        "error": "non-JSON response from host",
                        "raw": raw[:500]}
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}",
                "session": session.session_id}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "session": session.session_id}
