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


_EXPECTED_SERVICE = "revit-mcp"


def _probe_service(port: int, *, timeout: float = 0.5) -> bool:
    """GET /ping + verify service==revit-mcp. Prevents port-collision
    phantom sessions (Acad / Max binding the same port range)."""
    return _ping_service(port, timeout=timeout) is not None


def _ping_service(port: int, *, timeout: float = 0.5) -> Optional[dict]:
    """GET /ping. Returns the full response dict if `service` matches
    the expected RevitMCP id, else None. Used by port-range discovery
    to learn pid / revit_version without needing a session file.

    AgDR-0023: payload may carry a `compiler` field — values:
      • `subprocess_csc` — modern path, no Roslyn in AppDomain
      • `in_process_roslyn` — legacy path, conflicts with other addins
      • absent → treated as `unknown` (pre-AgDR-0023 RevitMCP build)
    `_warn_legacy_compiler_once(port, compiler)` logs a one-time
    deprecation when the legacy path is detected."""
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
            _warn_legacy_compiler_once(port, data.get("compiler"))
            return data
    except (urllib.error.URLError, OSError, ValueError):
        return None


# AgDR-0023 — RevitMCP Roslyn isolation. Track the (port, compiler)
# pairs we've already warned about so the deprecation message fires
# ONCE per port + lifetime of the process. Class-of-bug: in-process
# Roslyn collides with pyRevit / Speckle Roslyn — fix is subprocess
# csc.exe inside RevitMCP. ArchHub Python-side surfaces the warning
# upfront so the founder isn't surprised mid-cook.
_LEGACY_COMPILER_WARNED: set = set()


def _warn_legacy_compiler_once(port: int, compiler) -> None:
    if not compiler:
        return  # absent field — pre-AgDR-0023 RevitMCP; silent.
    compiler = str(compiler).lower().strip()
    if compiler != "in_process_roslyn":
        return
    key = (int(port), compiler)
    if key in _LEGACY_COMPILER_WARNED:
        return
    _LEGACY_COMPILER_WARNED.add(key)
    import logging
    logging.getLogger("revit_broker").warning(
        "RevitMCP on port %d uses in-process Roslyn (deprecated per "
        "AgDR-0023) — conflicts with pyRevit / Speckle when their "
        "Roslyn versions differ. Update RevitMCP to the subprocess_csc "
        "build to coexist with every add-in. See docs/RUN-REVIT.md.",
        port)


def _discover_in_port_range(known_ports: set,
                              *, timeout: float = 0.4) -> list[Session]:
    """Parallel-probe the configured port range for any responding
    RevitMCP instance. Built so ArchHub can attach to Revit even when:
      • the in-Revit DLL never wrote a session file (older v0.2 DLL)
      • the session file was deleted / scrubbed
      • RevitMCP rebound to a different port at runtime
    Synthesises a Session entry from /ping payload (pid + version).
    Excludes ports already covered by session files (`known_ports`).
    """
    import concurrent.futures as _cf

    candidates = [p for p in range(PORT_FIRST, PORT_LAST + 1)
                  if p not in known_ports]
    if not candidates:
        return []
    found: list[Session] = []
    # Parallel probe — 16 ports × 0.4s timeout serial = 6.4s worst-case;
    # parallel collapses to ~0.4s + overhead.
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(
            lambda p: (p, _ping_service(p, timeout=timeout)),
            candidates,
        ))
    for port, payload in results:
        if not payload:
            continue
        found.append(Session(
            session_id=f"revit-{payload.get('pid') or port}",
            family="revit",
            pid=int(payload.get("pid") or 0),
            port=port,
            version=str(payload.get("revit_version") or ""),
            doc_title=str(payload.get("doc_title") or ""),
            started_at="",
            last_heartbeat="",
            file_path=None,
            legacy=False,
            healthy=True,
        ))
    return found


# ---------------------------------------------------------------------------
# AgDR-0034 deferred-audit fix — list_sessions probes up to 16 ports per
# call (parallel, 0.4 s each). Rapid callers (host-pill refresh,
# connector probes, dropdowns) hammered that scan. A short-TTL cache
# coalesces a burst into ONE scan; 2.5 s is recent enough that a
# newly-opened Revit still surfaces within a couple seconds.
_LIST_TTL_S = 2.5
_list_cache: dict = {"at": 0.0, "result": None}


def list_sessions(*, prune: bool = True) -> list[Session]:
    """Return all known Revit sessions, newest-heartbeat first.

    `prune` — also delete stale session files (>30 s silence + dead port).
    Results are cached for ~2.5 s — a burst of calls costs one port scan.
    """
    import time as _t
    _now = _t.monotonic()
    _cached = _list_cache.get("result")
    if _cached is not None and (_now - _list_cache["at"]) < _LIST_TTL_S:
        return list(_cached)

    out: list[Session] = []
    if SESSIONS_DIR.exists():
        for p in sorted(SESSIONS_DIR.glob("revit-*.json")):
            s = _read_session_file(p)
            if s is None:
                continue
            silent_for = _seconds_since(s.last_heartbeat)
            # Identity-aware probe — verifies port owner is RevitMCP
            # (not AcadMCP or MaxMCP that happens to be on the port).
            alive = _probe_service(s.port, timeout=0.4)
            s.healthy = alive
            if not alive and silent_for > STALE_AFTER_SECONDS:
                if prune:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                continue
            out.append(s)

    # Port-range discovery — finds RevitMCP instances that did NOT
    # write a session file (older DLL, scrubbed file, race after MCP
    # already bound). Probes the configured port range in parallel.
    # Dedup against session-file ports above.
    known_ports = {s.port for s in out}
    out.extend(_discover_in_port_range(known_ports, timeout=0.4))

    # Legacy v0.2.0 DLL fallback — single hardcoded port, no session file.
    # Service-verified probe so a wrong host on 48884 can't impersonate.
    if not any(s.port == LEGACY_PORT for s in out):
        if _probe_service(LEGACY_PORT, timeout=0.4):
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
    _list_cache["at"] = _now
    _list_cache["result"] = out
    return list(out)   # copy — a caller mutating the list can't corrupt the cache


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
                # Audit 2026-05-21: a non-JSON 2xx body (HTML error page,
                # partial write, wrong listener on the port) used to be
                # reported as {"status":"ok"} — a connector op then
                # surfaced garbage as real data.  Honest status:
                # non-JSON == error.
                return {"status": "error",
                        "error": "non-JSON response from host",
                        "raw": raw[:500],
                        "session": session.session_id}
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}",
                "session": session.session_id}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "session": session.session_id}
