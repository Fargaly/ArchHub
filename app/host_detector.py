"""Host / desktop-app auto-detection — probes every host ArchHub knows about.

Companion to llm_detector.py. The LLM detector cares about chat
backends; this one cares about the productivity / creative apps a user
might want to drive from ArchHub (Outlook, Word, Photoshop, etc.).

Called at boot + every ~30s by the host pill refresh in the header.
Cheap probes only — process listing + COM GetActiveObject. No
side-effects (we never START an app here; only check if it's already
running). Per-probe timeout 1.0s so the launch path stays snappy.

Returns a dict per host with:
    status:   "live"        — running process found OR live COM handle
              "missing"     — not detected
              "unavailable" — probe couldn't run (e.g. pywin32 not
                              installed, psutil missing AND PowerShell
                              fallback failed)
    version:  str            — best-effort version string (may be "")
    note:     str            — one-line human reason (tooltip)
    detail:   dict           — extra debug info (pid, exe, com_progid)

JS bridge consumes this via ArchHubBridge.get_all_hosts().
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Optional

from host_aliases import canonical_host

# Cheap per-process cache so the 30s refresh doesn't re-probe inside the
# same Qt tick. Same TTL + shape as llm_detector._CACHE.
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 25.0

# Per-probe timeout — keep launch path snappy. PowerShell fallback can
# be slow on cold-cache Windows; cap it hard.
_PROBE_TIMEOUT = 1.0


# ---------------------------------------------------------------------------
def _cached(key: str, ttl: float = _CACHE_TTL_SECONDS):
    """Decorator-like helper. `key` is the cache slot."""
    def wrap(fn):
        def inner():
            now = time.time()
            if key in _CACHE:
                ts, val = _CACHE[key]
                if now - ts < ttl:
                    return val
            try:
                val = fn()
            except Exception as ex:
                # Never let a probe crash the detector. Surface as
                # "unavailable" so the UI can show a tooltip.
                val = {
                    "status": "unavailable",
                    "version": "",
                    "note": f"probe crashed: {type(ex).__name__}: {ex}"[:200],
                    "detail": {},
                }
            _CACHE[key] = (now, val)
            return val
        return inner
    return wrap


# ---------------------------------------------------------------------------
# Process detection — psutil if available, PowerShell fallback if not.
# Snapshot cache for the raw process table — separate from _CACHE (which
# holds per-probe result dicts). A cold detect_all_hosts() pass calls
# _find_process many times (antigravity, outlook/teams fallbacks, notion,
# 4 broker fallbacks) and one full enumeration costs ~1.6s cold via
# psutil / ~1s+ via PowerShell, so one enumeration must serve them all.
_PROC_SNAPSHOT_TTL_SECONDS = 2.0
_PROC_SNAPSHOT_LOCK = threading.Lock()  # held across the fetch — single-flight
_PROC_SNAPSHOT: Optional[tuple[float, list[dict]]] = None  # (monotonic ts, rows)


def _running_processes() -> list[dict]:
    """Return a list of {name, exe, pid} dicts for every running
    process. Cached for _PROC_SNAPSHOT_TTL_SECONDS (2.0s, monotonic)
    so one enumeration serves the whole probe pass instead of one per
    _find_process call. detect_all_hosts(force=True) busts _CACHE but
    not this snapshot — a forced refresh tolerates <=2s staleness of
    the process table. The lock is held across the fetch so concurrent
    probe threads wait for the in-flight enumeration rather than
    stacking their own; a failed enumeration ([]) is cached too."""
    global _PROC_SNAPSHOT
    with _PROC_SNAPSHOT_LOCK:
        now = time.monotonic()
        if _PROC_SNAPSHOT is not None:
            ts, rows = _PROC_SNAPSHOT
            if now - ts < _PROC_SNAPSHOT_TTL_SECONDS:
                return rows
        rows = _enumerate_processes()
        _PROC_SNAPSHOT = (now, rows)
        return rows


def _enumerate_processes() -> list[dict]:
    """Uncached process-table fetch — call via _running_processes()."""
    try:
        import psutil
        out: list[dict] = []
        for p in psutil.process_iter(["name", "exe", "pid"]):
            try:
                info = p.info
                out.append({
                    "name": (info.get("name") or "").lower(),
                    "exe":  info.get("exe") or "",
                    "pid":  int(info.get("pid") or 0),
                })
            except Exception:
                continue
        return out
    except ImportError:
        pass
    # PowerShell fallback — slower but works without psutil.
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "Get-Process | Select-Object Name,Id,Path | "
               "ConvertTo-Csv -NoTypeInformation"]
        res = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_PROBE_TIMEOUT)
        out: list[dict] = []
        for line in (res.stdout or "").splitlines()[1:]:
            # CSV with quoted fields: "Name","Id","Path"
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[1])
            except Exception:
                continue
            out.append({
                "name": parts[0].lower(),
                "exe":  parts[2] if len(parts) > 2 else "",
                "pid":  pid,
            })
        return out
    except Exception:
        return []


def _find_process(name_substrings: list[str]) -> Optional[dict]:
    """Return the first process whose name matches any substring.
    Match is case-insensitive on the process name (no .exe suffix req)."""
    needles = [s.lower() for s in name_substrings]
    for proc in _running_processes():
        n = proc["name"]
        if not n:
            continue
        for needle in needles:
            if needle in n:
                return proc
    return None


# ---------------------------------------------------------------------------
# COM helpers — pywin32 GetActiveObject pattern (already-running app only).
def _com_get_active(progid: str) -> tuple[Optional[object], str]:
    """Try GetActiveObject(progid). Returns (app, error_msg).
    error_msg is "" on success, a human reason otherwise.

    Note: GetActiveObject does NOT start the app — that's intentional.
    If the user hasn't opened the app, we report "missing" rather than
    launching it on them.
    """
    try:
        import win32com.client as w
    except ImportError:
        return None, "pywin32 not installed"
    try:
        # GetActiveObject hits a running ROT-registered instance only.
        app = w.GetActiveObject(progid)
        return app, ""
    except Exception as ex:
        return None, f"{type(ex).__name__}: {ex}"[:200]


def _com_version(app: object) -> str:
    """Pull a version string off a COM Application object — many Office
    + Adobe apps expose .Version. Fall back to empty string."""
    for attr in ("Version", "version", "AppVersion"):
        try:
            v = getattr(app, attr, None)
            if v:
                return str(v)
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------------------
# Network helper — reused by LM Studio probe.
def _tcp_open(host: str, port: int, timeout: float = 0.3) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _http_json(url: str, timeout: float = 1.0):
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


# ===========================================================================
# Probes — one per host. All return the same shape.
# ===========================================================================

@_cached("lmstudio")
def probe_lmstudio() -> dict:
    """LM Studio — localhost OpenAI-compatible server (port 1234).
    Shape kept compatible with the existing llm_detector.probe_lmstudio
    consumer (status field + note). Adds `version` slot empty since
    LM Studio doesn't expose it over /v1/models."""
    base = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    base = base.rstrip("/")
    if not _tcp_open("127.0.0.1", 1234, timeout=0.3):
        return {
            "status":  "missing",
            "version": "",
            "note":    "LM Studio server not running on :1234",
            "detail":  {"base_url": base},
        }
    data = _http_json(f"{base}/models", timeout=1.0)
    if not data:
        return {
            "status":  "live",
            "version": "",
            "note":    "process up; /v1/models returned nothing",
            "detail":  {"base_url": base},
        }
    raw = data.get("data") or []
    models = [m.get("id") for m in raw if m.get("id")]
    chat = [m for m in models if "embed" not in m.lower()]
    return {
        "status":  "live",
        "version": "",
        "note":    (f"{len(chat)} chat model(s) loaded"
                     if chat else "server up, no chat model loaded"),
        "detail":  {"base_url": base, "models": models},
    }


@_cached("antigravity")
def probe_antigravity() -> dict:
    """Antigravity — Google's AI IDE (Anthropic-backed). Detect by
    process name. The binary ships as `antigravity.exe` on Windows."""
    proc = _find_process(["antigravity"])
    if not proc:
        return {
            "status":  "missing",
            "version": "",
            "note":    "Antigravity process not running",
            "detail":  {},
        }
    return {
        "status":  "live",
        "version": "",
        "note":    f"running (pid={proc['pid']})",
        "detail":  {"pid": proc["pid"], "exe": proc["exe"]},
    }


@_cached("outlook")
def probe_outlook() -> dict:
    """Microsoft Outlook (classic / COM). Live if Outlook.Application
    is dispatchable on the ROT. New Outlook (UWP) won't show up here
    — that's accepted; we surface in the note.
    """
    app, err = _com_get_active("Outlook.Application")
    if app is None:
        # No COM — check the process list to distinguish 'not installed'
        # from 'closed' from 'pywin32 missing'.
        proc = _find_process(["outlook"])
        if "pywin32" in err.lower():
            return {
                "status":  "unavailable",
                "version": "",
                "note":    err,
                "detail":  {},
            }
        if proc:
            # Process running but COM not reachable — usually New
            # Outlook (UWP) or Outlook starting up.
            return {
                "status":  "live",
                "version": "",
                "note":    f"running (pid={proc['pid']}); COM unreachable (maybe New Outlook)",
                "detail":  {"pid": proc["pid"], "exe": proc["exe"]},
            }
        return {
            "status":  "missing",
            "version": "",
            "note":    "Outlook not running",
            "detail":  {"com_error": err},
        }
    version = _com_version(app)
    return {
        "status":  "live",
        "version": version,
        "note":    f"COM reachable (Outlook.Application v{version or '?'})",
        "detail":  {"com_progid": "Outlook.Application"},
    }


@_cached("teams")
def probe_teams() -> dict:
    """Microsoft Teams desktop. Process probe primarily. Optional
    Microsoft Graph token (in env or secrets_store) bumps status note.
    """
    proc = _find_process(["teams", "ms-teams"])
    has_graph = False
    try:
        from secrets_store import load_api_key  # type: ignore
        has_graph = bool(load_api_key("ms_graph"))
    except Exception:
        pass
    # Env var as a secondary source — covers headless / dev runs.
    if not has_graph:
        has_graph = bool(os.environ.get("MS_GRAPH_TOKEN"))
    if not proc and not has_graph:
        return {
            "status":  "missing",
            "version": "",
            "note":    "Teams not running, no Graph token",
            "detail":  {"graph_token": False},
        }
    if proc:
        return {
            "status":  "live",
            "version": "",
            "note":    (f"running (pid={proc['pid']})"
                         + (" + Graph token configured" if has_graph else "")),
            "detail":  {"pid": proc["pid"], "exe": proc["exe"],
                         "graph_token": has_graph},
        }
    # No process but Graph token present — call it live (cloud path).
    return {
        "status":  "live",
        "version": "",
        "note":    "Graph token configured (desktop not running)",
        "detail":  {"graph_token": True},
    }


@_cached("word")
def probe_word() -> dict:
    """Microsoft Word — COM via Word.Application."""
    return _office_com_probe("Word.Application", "Word", ["winword"])


@_cached("excel")
def probe_excel() -> dict:
    """Microsoft Excel — COM via Excel.Application."""
    return _office_com_probe("Excel.Application", "Excel", ["excel"])


@_cached("powerpoint")
def probe_powerpoint() -> dict:
    """Microsoft PowerPoint — COM via PowerPoint.Application."""
    return _office_com_probe(
        "PowerPoint.Application", "PowerPoint", ["powerpnt"])


@_cached("photoshop")
def probe_photoshop() -> dict:
    """Adobe Photoshop — COM via Photoshop.Application."""
    return _office_com_probe(
        "Photoshop.Application", "Photoshop", ["photoshop"])


@_cached("illustrator")
def probe_illustrator() -> dict:
    """Adobe Illustrator — COM via Illustrator.Application."""
    return _office_com_probe(
        "Illustrator.Application", "Illustrator", ["illustrator"])


@_cached("indesign")
def probe_indesign() -> dict:
    """Adobe InDesign — COM via InDesign.Application."""
    return _office_com_probe(
        "InDesign.Application", "InDesign", ["indesign"])


def _office_com_probe(progid: str, display: str,
                       proc_needles: list[str]) -> dict:
    """Shared COM probe for Office / Adobe desktop apps.

    Priority: COM GetActiveObject (most reliable when app is running) →
    process listing (fallback when app is in COM-unfriendly state).
    """
    app, err = _com_get_active(progid)
    if app is not None:
        version = _com_version(app)
        return {
            "status":  "live",
            "version": version,
            "note":    f"{display} COM reachable (v{version or '?'})",
            "detail":  {"com_progid": progid},
        }
    if "pywin32" in err.lower():
        # pywin32 missing — fall back to process detection so we still
        # give the UI something useful.
        proc = _find_process(proc_needles)
        if proc:
            return {
                "status":  "live",
                "version": "",
                "note":    f"{display} running (pywin32 missing — process only)",
                "detail":  {"pid": proc["pid"], "exe": proc["exe"]},
            }
        return {
            "status":  "unavailable",
            "version": "",
            "note":    err,
            "detail":  {},
        }
    proc = _find_process(proc_needles)
    if proc:
        return {
            "status":  "live",
            "version": "",
            "note":    f"{display} running (pid={proc['pid']}); COM unreachable",
            "detail":  {"pid": proc["pid"], "exe": proc["exe"],
                         "com_error": err},
        }
    return {
        "status":  "missing",
        "version": "",
        "note":    f"{display} not running",
        "detail":  {"com_error": err},
    }


# ---------------------------------------------------------------------------
# Token-based REST connectors — Notion, Dropbox, Teams, Procore, Speckle.
#
# These hosts are NOT local desktop apps the user runs; they are cloud REST
# APIs that ArchHub authenticates with a saved integration token (via
# secrets_store.load_api_key). The honest "is this host usable?" question is
# therefore "is a token configured + accepted?" — NOT "is a process named
# `notion` running?".
#
# Founder bug 2026-06-20: pinging `notion` reported "not reachable (unknown)"
# even though api.notion.com was reachable — the real situation was simply NO
# TOKEN CONFIGURED. The old `probe_notion` here detected a desktop process
# (or, worse, any process whose name merely CONTAINED "notion") and reported a
# misleading `live`/`missing` that had nothing to do with whether the REST
# connector could actually be used. That was also a ONE-SYSTEM violation: two
# parallel notions of "notion status" (this process probe + the REST
# connector's token-aware `probe()`).
#
# Root fix: for the whole token-based REST class, DEFER to the connector's own
# `probe()` (it already distinguishes the three honest states — token missing,
# token rejected (401), token present but network/timeout) and map its result
# into the host_detector shape. Status `unauthorized` is the actionable
# "not connected — add your token" state; we surface it as-is so callers can
# show the connector's own token hint instead of "(unknown)".
TOKEN_REST_HOSTS = frozenset(
    {"notion", "dropbox", "teams", "procore", "speckle"})


def _rest_connector_status(host_id: str, display: str) -> dict:
    """Map a token-based REST connector's `probe()` into the host_detector
    shape {status, version, note, detail}.

    The connector probe returns one of:
      unauthorized — no token, OR token rejected (401). `note` carries the
                     actionable "add/replace your token in Settings ->
                     Sign-ins -> X" hint. We pass this through verbatim so the
                     ping/status surfaces show a clear, fixable message and
                     NEVER "(unknown)".
      live         — token present + accepted by the API.
      missing      — token present but the API was unreachable / errored
                     (network, timeout, 5xx).

    Never raises: a probe that itself errors is reported as `unavailable`
    with the error note, so a single bad connector can't crash detection."""
    try:
        from connectors.base import get as _get_connector
        c = _get_connector(host_id)
        if c is None:
            # Lazily import the connector module so it self-registers — the
            # detector can run before the full connector registry is loaded.
            # REST connectors carry no heavy host SDK, so this is cheap.
            try:
                import importlib
                importlib.import_module(f"connectors.{host_id}_connector")
                c = _get_connector(host_id)
            except Exception:
                c = None
        if c is None:
            return {"status": "unavailable", "version": "",
                    "note": f"{display} connector not registered",
                    "detail": {}}
        pr = c.probe() or {}
    except Exception as ex:
        return {"status": "unavailable", "version": "",
                "note": f"{display} probe failed: "
                        f"{type(ex).__name__}: {ex}"[:200],
                "detail": {}}
    status = str(pr.get("status") or "missing")
    note = str(pr.get("note") or "")
    detail = pr.get("detail") if isinstance(pr.get("detail"), dict) else {}
    # An empty/garbled probe must still resolve to an HONEST, named state —
    # never a status-less dict that downstream renders as "(unknown)".
    if status not in ("live", "loaded_dead", "missing", "unauthorized"):
        status = "missing"
        note = note or f"{display} status unknown — re-check the connection"
    if not note:
        note = (f"{display} not connected — add your token in "
                f"Settings -> Sign-ins -> {display}"
                if status == "unauthorized" else f"{display} {status}")
    return {"status": status, "version": "", "note": note, "detail": detail}


def probe_notion() -> dict:
    """Notion — a token-based REST connector, NOT a desktop app.

    Defers to the Notion REST connector's token-aware `probe()` so the status
    reflects whether an integration token is configured + accepted, rather
    than whether some `notion`-named desktop process happens to be running.
    No token -> `unauthorized` with the actionable token hint (never
    "(unknown)")."""
    return _rest_connector_status("notion", "Notion")


# ── Broker-backed AEC hosts ────────────────────────────────────────────
# Founder demand 2026-05-15: "ALL connectors should be working — when I
# ping AutoCAD it should work." Revit / AutoCAD / 3ds Max / Blender talk
# to ArchHub through a host-side add-in that serves an HTTP listener on a
# fixed port. We probe that listener directly so the agent + UI report
# the TRUTH — live, host-running-but-addin-dead, or fully offline — and
# never hallucinate a result against a dead broker.
_BROKER_PORTS = {
    "revit":   48884,
    "autocad": 48885,
    "max":     48886,
    "blender": 9876,
}
_BROKER_PROCESS = {
    "revit":   ["revit.exe"],
    "autocad": ["acad.exe", "autocad.exe"],
    "max":     ["3dsmax.exe"],
    "blender": ["blender.exe"],
}


def _probe_broker(family: str) -> dict:
    """Probe one broker-backed host. Returns the standard shape.

    status:
      live          — add-in listener answered /ping.
      loaded_dead   — host process running but listener not answering
                      (add-in not NETLOADed / crashed).
      missing       — host process not running at all.
    """
    family = canonical_host(family)
    port = _BROKER_PORTS.get(family)
    if port is None:
        return {"status": "missing", "version": "",
                 "note": f"{family}: no broker port", "detail": {}}
    listener_up = _tcp_open("127.0.0.1", port, timeout=0.3)
    if listener_up:
        data = _http_json(f"http://127.0.0.1:{port}/ping", timeout=0.8) or {}
        return {"status": "live", "version": str(data.get("version", "")),
                 "note": f"{family} broker live on :{port}",
                 "detail": {"port": port, **(data if isinstance(data, dict) else {})}}
    # Listener down — is the host even open?
    proc = None
    try:
        proc = _find_process(_BROKER_PROCESS.get(family, []))
    except Exception:
        proc = None
    if proc:
        return {"status": "loaded_dead", "version": "",
                 "note": (f"{family} is running but the ArchHub add-in "
                          f"isn't responding on :{port} — load the "
                          f"connector inside {family}"),
                 "detail": {"port": port, "pid": getattr(proc, "pid", None)}}
    return {"status": "missing", "version": "",
             "note": f"{family} not running",
             "detail": {"port": port}}


@_cached("revit")
def probe_revit() -> dict:
    return _probe_broker("revit")


@_cached("autocad")
def probe_autocad() -> dict:
    return _probe_broker("autocad")


@_cached("max")
def probe_max() -> dict:
    return _probe_broker("max")


@_cached("blender")
def probe_blender() -> dict:
    return _probe_broker("blender")


PROBERS = {
    "revit":        probe_revit,
    "autocad":      probe_autocad,
    "max":          probe_max,
    "blender":      probe_blender,
    "lmstudio":     probe_lmstudio,
    "antigravity":  probe_antigravity,
    "outlook":      probe_outlook,
    "teams":        probe_teams,
    "word":         probe_word,
    "excel":        probe_excel,
    "powerpoint":   probe_powerpoint,
    "photoshop":    probe_photoshop,
    "illustrator":  probe_illustrator,
    "indesign":     probe_indesign,
    "notion":       probe_notion,
}


HOST_DISPLAY = {
    "revit":        "Revit",
    "autocad":      "AutoCAD",
    "max":          "3ds Max",
    "blender":      "Blender",
    "lmstudio":     "LM Studio",
    "antigravity":  "Antigravity",
    "outlook":      "Outlook",
    "teams":        "Microsoft Teams",
    "word":         "Word",
    "excel":        "Excel",
    "powerpoint":   "PowerPoint",
    "photoshop":    "Photoshop",
    "illustrator":  "Illustrator",
    "indesign":     "InDesign",
    "notion":       "Notion",
}


def detect_all_hosts(*, force: bool = False) -> dict[str, dict]:
    """Probe every host in PROBERS. Returns a dict keyed by host id.

    Each probe is wrapped in try/except inside the @_cached decorator,
    so a single bad probe never crashes the whole detector.

    Pass force=True to bust the per-process cache (e.g. user clicked
    Refresh in Settings).
    """
    if force:
        _CACHE.clear()
    out: dict[str, dict] = {}
    for hid, probe in PROBERS.items():
        try:
            out[hid] = probe()
        except Exception as ex:
            out[hid] = {
                "status":  "unavailable",
                "version": "",
                "note":    f"probe failed: {type(ex).__name__}: {ex}"[:200],
                "detail":  {},
            }
    return out


def live_hosts() -> list[str]:
    """Ids of hosts currently `status=='live'`."""
    return [hid for hid, info in detect_all_hosts().items()
            if info.get("status") == "live"]


def display_label(hid: str) -> str:
    canonical = canonical_host(hid)
    return HOST_DISPLAY.get(canonical, canonical.title())


if __name__ == "__main__":
    # Quick CLI smoke test: `py -3.14 host_detector.py`
    import json
    print(json.dumps(detect_all_hosts(), indent=2, default=str))
