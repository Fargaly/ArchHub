"""brain_ledger.py — the ONE bridge from the local hooks to the brain's
SERVER-AUTHORITATIVE active-work ledger (AgDR-0054 S1, ONE-SYSTEM mandate).

This is the unification choke point. Before this, `tools/active_work.py`
(+ `tools/completion_gate.py`) wrote a SEPARATE JSON file ledger while the
brain-side `personal_brain.active_work` ledger lived in `brain.db` — TWO
divergent stores for one job (the exact ONE-SYSTEM violation the court refuted).
Now BOTH local tools read/write THROUGH the brain ledger via this module, so
there is ONE ledger of record: `brain_meta['active_work_v1']` in `brain.db`.

Transport (mirrors tools/brainwrap.py + personal_brain.client_hook EXACTLY):

  1. DAEMON (preferred). If the brain daemon answers on $BRAIN_DAEMON_URL,
     every read/write goes over MCP `brain.work_*`. This funnels ALL clients
     (Claude Code / Codex / Gemini / composer / this hook) through the daemon's
     single BrainStore + RLock — so the atomic `update_meta` critical section
     actually protects cross-process concurrency.
  2. IN-PROCESS. If the daemon is down BUT `personal_brain` imports, open the
     SAME on-disk `brain.db` directly (WAL-safe) and call the ledger functions
     in-process. Still the ONE store — just reached without the daemon.
  3. DEGRADED (file cache). Only when the brain is genuinely unreachable AND the
     package can't be imported (e.g. a stripped contributor box) do we fall back
     to the legacy JSON file — and we say so loudly via `transport()`. This is a
     last-resort OFFLINE CACHE, never a parallel system: the moment the brain is
     reachable it is authoritative again. `ARCHHUB_LEDGER_NO_FILE_FALLBACK=1`
     turns even this off (fail-loud) for environments that must never diverge.

Pure stdlib (urllib / json), fail-soft on transport errors so a Stop hook never
bricks a turn — but NEVER silently forks the store.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Optional

DAEMON_URL = os.environ.get("BRAIN_DAEMON_URL", "http://127.0.0.1:8473/mcp")
_TIMEOUT = float(os.environ.get("BRAIN_LEDGER_TIMEOUT", "6"))

# Make the bundled brain package importable for the in-process path (mirror
# brainwrap's sys.path bootstrap: repo/personal-brain-mcp/src).
_TOOLS = Path(__file__).resolve().parent
_REPO = _TOOLS.parent
_BRAIN_SRC = _REPO / "personal-brain-mcp" / "src"
if _BRAIN_SRC.exists() and str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))

# Resolve the owner the same way the brain daemon does, so the local hook reads
# the SAME owner's ledger the server writes (honours a cloud binding via the
# in-process resolver; else env; else 'founder').
DEFAULT_OWNER = (
    os.environ.get("BRAIN_OWNER_USER")
    or os.environ.get("USER")
    or os.environ.get("USERNAME")
    or "founder"
)


# ───────────────────────── MCP transport (daemon) ───────────────────────


def _parse_sse(raw: bytes) -> dict:
    """Pull structuredContent / JSON text out of an MCP SSE response (identical
    wire shape to tools/brainwrap.py + client_hook._parse_sse)."""
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                obj = json.loads(line[5:].strip())
            except Exception:
                continue
            res = obj.get("result") or {}
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            for c in res.get("content") or []:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except Exception:
                        pass
    return {}


def _call_daemon(name: str, arguments: dict[str, Any],
                 *, timeout: float = _TIMEOUT) -> Optional[dict]:
    """POST one MCP tools/call. Returns the structured result, or None on any
    transport failure (caller falls through to the next transport)."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _parse_sse(r.read())
    except Exception:
        return None


_daemon_up: Optional[bool] = None


def _daemon_alive() -> bool:
    """Cheap one-shot daemon probe, memoised per process."""
    global _daemon_up
    if _daemon_up is None:
        res = _call_daemon("brain.health", {}, timeout=2.5)
        _daemon_up = bool(res and res.get("ok"))
    return _daemon_up


# ───────────────────────── in-process transport (brain.db) ──────────────


_store = None
_store_tried = False


def _inproc_store():
    """Open the SAME on-disk brain.db the daemon uses (WAL-safe), memoised.
    Returns a BrainStore or None if the package can't be imported."""
    global _store, _store_tried
    if _store_tried:
        return _store
    _store_tried = True
    try:
        from personal_brain.storage import BrainStore, default_brain_path
        db = os.environ.get("ARCHHUB_BRAIN_DB") or str(default_brain_path())
        _store = BrainStore.open(db)
    except Exception:
        _store = None
    return _store


# ───────────────────────── degraded file cache ──────────────────────────
# Reuse the legacy file shape so an OFFLINE box still has a local catch. This is
# the ONLY place the file is touched, and only when the brain is unreachable.

_FILE_REL = ".archhub/active_work.json"


def _file_path() -> Path:
    env = os.environ.get("ARCHHUB_ACTIVE_WORK")
    return Path(env) if env else (Path.cwd() / _FILE_REL)


def _file_fallback_allowed() -> bool:
    return os.environ.get("ARCHHUB_LEDGER_NO_FILE_FALLBACK", "") not in ("1", "true", "True")


# ───────────────────────── public API (the ONE ledger) ──────────────────


def transport() -> str:
    """Which backend is authoritative right now: 'daemon' | 'inproc' | 'file'.
    Surfaced so callers (and tests) can PROVE they hit the brain, not a fork."""
    if _daemon_alive():
        return "daemon"
    if _inproc_store() is not None:
        return "inproc"
    return "file"


def status(owner_user: Optional[str] = None) -> Optional[dict]:
    """The brain ledger's done-rule state for an owner — the same dict
    `personal_brain.active_work.status` returns ({dry, counts, actionable,
    blocked, iterations, cap, ...}), or None when the brain is unreachable AND
    no file cache exists."""
    owner = owner_user or DEFAULT_OWNER
    if _daemon_alive():
        res = _call_daemon("brain.work_status", {"owner_user": owner})
        if res and res.get("ok"):
            return res
    st = _inproc_store()
    if st is not None:
        from personal_brain import active_work as aw
        return aw.status(st, owner_user=owner)
    # degraded: synthesise a status dict from the file cache (legacy shape).
    if _file_fallback_allowed():
        p = _file_path()
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            return {"owner_user": owner, "exists": True, "dry": False,
                    "iterations": int(d.get("iterations", 0)),
                    "cap": int(d.get("cap", 12)), "_file_cache": True}
    return None


def get_ledger(owner_user: Optional[str] = None) -> Optional[dict]:
    """The whole active-work ledger (every leaf) for an owner, as a plain dict,
    or None when unavailable. This is what completion_gate derives its gates
    from — the brain's actionable leaves ARE the done-gates."""
    owner = owner_user or DEFAULT_OWNER
    if _daemon_alive():
        res = _call_daemon("brain.work_get", {"owner_user": owner})
        if res and res.get("ok"):
            return res.get("ledger")
    st = _inproc_store()
    if st is not None:
        from personal_brain import active_work as aw
        led = aw.get_ledger(st, owner_user=owner)
        return led.model_dump(mode="json") if led is not None else None
    return None


def add_leaves(leaves: list[dict], *, owner_user: Optional[str] = None) -> dict:
    """Enqueue work into the BRAIN ledger (producer). `leaves` =
    [{title, gate_kind?, gate_spec?, fit?, priority?}]. Returns {ok, transport,
    status}. Writes go to the brain; the file cache is updated only in degraded
    mode so an offline box still blocks on something."""
    owner = owner_user or DEFAULT_OWNER
    if _daemon_alive():
        res = _call_daemon("brain.work_add",
                           {"leaves": leaves, "owner_user": owner})
        if res and res.get("ok"):
            return {"ok": True, "transport": "daemon", "status": res.get("status")}
    st = _inproc_store()
    if st is not None:
        from personal_brain import active_work as aw
        aw.add_leaves(st, owner_user=owner, leaves=leaves)
        return {"ok": True, "transport": "inproc",
                "status": aw.status(st, owner_user=owner)}
    if _file_fallback_allowed():
        _file_add_degraded(leaves)
        return {"ok": True, "transport": "file", "degraded": True}
    raise RuntimeError(
        "brain ledger unreachable (no daemon, package import failed) and file "
        "fallback disabled (ARCHHUB_LEDGER_NO_FILE_FALLBACK=1) — refusing to "
        "write a forked ledger."
    )


def bump(owner_user: Optional[str] = None) -> int:
    """Record one Stop-hook re-entry against the BRAIN ledger (the
    anti-infinite-grind counter the gate reads). Returns the new count."""
    owner = owner_user or DEFAULT_OWNER
    if _daemon_alive():
        # brain.work_status returns iterations; bump via a dedicated path if the
        # daemon exposes it, else fall through to in-process.
        st = _inproc_store()
        if st is not None:
            from personal_brain import active_work as aw
            return aw.bump_iteration(st, owner_user=owner)
    st = _inproc_store()
    if st is not None:
        from personal_brain import active_work as aw
        return aw.bump_iteration(st, owner_user=owner)
    if _file_fallback_allowed():
        return _file_bump_degraded()
    raise RuntimeError("brain ledger unreachable and file fallback disabled")


# ── degraded file helpers (legacy shape; offline-only) ───────────────────


def _file_add_degraded(leaves: list[dict]) -> None:
    p = _file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            existing = {}
    # store leaves as completion_gate-shaped gates so the offline gate can run.
    gates = existing.get("gates", [])
    for lf in leaves:
        gates.append({
            "name": lf.get("title", ""),
            "kind": _GATE_KIND_MAP.get(lf.get("gate_kind", "manual"), "manual"),
            "arg": _gate_arg_from_spec(lf.get("gate_kind", "manual"),
                                       lf.get("gate_spec") or {}),
            "machine_resolvable": lf.get("gate_kind", "manual") != "manual",
        })
    p.write_text(json.dumps({"gates": gates,
                             "iterations": int(existing.get("iterations", 0)),
                             "cap": int(existing.get("cap", 12)),
                             "_degraded_offline_cache": True}, indent=2),
                 encoding="utf-8")


def _file_bump_degraded() -> int:
    p = _file_path()
    d = {"gates": [], "iterations": 0, "cap": 12}
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    d["iterations"] = int(d.get("iterations", 0)) + 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d["iterations"]


# ── leaf-gate → completion_gate.Gate mapping (the ONE translation) ───────
# A brain WorkLeaf's (gate_kind, gate_spec) maps to a completion_gate Gate so
# the gate evaluates the SAME predicate the brain leaf carries. completion_gate
# natively runs file_exists / grep_clean / pytest / py_compile / manual; the
# live-DOM 'cdp' gate isn't runnable from a bare hook -> it escalates (manual).
_GATE_KIND_MAP = {
    "file_exists": "file_exists",
    "pytest": "pytest",
    "grep_clean": "grep_clean",
    "py_compile": "py_compile",
    "manual": "manual",
    "cdp": "manual",          # live-DOM gate is not machine-runnable from a bare hook -> escalate
}


def _gate_arg_from_spec(gate_kind: str, gate_spec: dict) -> str:
    """Extract the single positional arg completion_gate.Gate.arg expects from a
    brain leaf's gate_spec (path / selector / pattern / module-to-compile)."""
    if gate_kind == "file_exists":
        return gate_spec.get("path", "")
    if gate_kind == "pytest":
        return gate_spec.get("selector", "")
    if gate_kind == "grep_clean":
        return gate_spec.get("pattern", "")
    if gate_kind == "py_compile":
        return gate_spec.get("path", "")
    return ""


def leaves_as_gates(owner_user: Optional[str] = None) -> Optional[list[dict]]:
    """Render the brain ledger's ACTIONABLE (open/claimed, not done/blocked)
    leaves as completion_gate Gate dicts. A DONE leaf is already green (omitted);
    a BLOCKED leaf is a needs-root escalation, surfaced as a non-machine gate.
    Returns None when the brain is unreachable (so the gate can decide its own
    safe default)."""
    led = get_ledger(owner_user)
    if led is None:
        return None
    gates: list[dict] = []
    for lf in (led.get("leaves") or {}).values():
        state = lf.get("state")
        if state == "done":
            continue  # already verified-complete — not a pending gate
        gk = lf.get("gate_kind", "manual")
        spec = lf.get("gate_spec") or {}
        if state == "blocked":
            # escalate, never silently allow: a blocked leaf needs the founder.
            gates.append({"name": lf.get("title", ""), "kind": "manual",
                          "arg": "", "machine_resolvable": False})
            continue
        gates.append({
            "name": lf.get("title", ""),
            "kind": _GATE_KIND_MAP.get(gk, "manual"),
            "arg": _gate_arg_from_spec(gk, spec),
            "arg2": ",".join(spec.get("paths", [])) if gk == "grep_clean" else "",
            "machine_resolvable": gk not in ("manual", "cdp"),
        })
    return gates
