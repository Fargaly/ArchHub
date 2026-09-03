"""active_work.py — the PRODUCER side of THE DRIVE, routed THROUGH the brain.

ONE-SYSTEM (AgDR-0054 S1 + ONE-SYSTEM mandate): this module no longer owns a
separate JSON-file ledger. It is now a thin local shim over the SINGLE
server-authoritative brain ledger (`brain_meta['active_work_v1']` in `brain.db`),
reached via `tools/brain_ledger.py` (daemon → in-process → offline-file
fallback). `completion_gate.py` READS that same brain ledger. There is ONE store.

  - register(gates)  : enqueue work into the BRAIN ledger as leaves.
  - status()         : read the brain ledger's done-rule state (or None).
  - bump()           : record one Stop re-entry against the BRAIN ledger.
  - clear()          : (degraded only) remove the offline file cache.

The legacy file helpers (`*_file`) remain for the OFFLINE fallback path only —
they are not a parallel system; the brain is authoritative whenever reachable.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

# tools/ on sys.path so `import brain_ledger` works when run standalone / as a hook.
_TOOLS = str(Path(__file__).resolve().parent)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

DEFAULT_REL = ".archhub/active_work.json"


def default_path() -> Path:
    """Legacy offline-cache path (degraded fallback only)."""
    env = os.environ.get("ARCHHUB_ACTIVE_WORK")
    return Path(env) if env else (Path.cwd() / DEFAULT_REL)


def _gate_to_leaf(g: dict) -> dict:
    """Translate a completion_gate.Gate dict -> a brain WorkLeaf spec, so the
    producer speaks the brain ledger's vocabulary (the ONE store)."""
    kind = g.get("kind", "manual")
    spec: dict = {}
    if kind == "file_exists":
        spec = {"path": g.get("arg", "")}
    elif kind == "pytest":
        spec = {"selector": g.get("arg", "")}
    elif kind == "grep_clean":
        spec = {"pattern": g.get("arg", ""),
                "paths": [p for p in (g.get("arg2", "") or "").split(",") if p]}
    return {"title": g.get("name", ""), "gate_kind": kind, "gate_spec": spec}


def register(gates: List[dict], *, scope: str = "", cap: int = 12,
             path: Optional[Path] = None, owner_user: Optional[str] = None) -> dict:
    """Open a job: enqueue the done-gates as leaves in the BRAIN ledger. Returns
    the brain_ledger result ({ok, transport, status}). `gates` is a list of
    completion_gate.Gate dicts ({name, kind, arg, arg2, machine_resolvable}).

    `path` is accepted for backward-compat with the old file API but ignored on
    the authoritative (brain) path; it is honoured only in the offline fallback,
    which brain_ledger handles internally."""
    import brain_ledger as bl
    leaves = [_gate_to_leaf(g) for g in gates]
    if not leaves:
        # nothing to enqueue; return current status so callers still get a dict.
        return {"ok": True, "transport": bl.transport(),
                "status": bl.status(owner_user)}
    return bl.add_leaves(leaves, owner_user=owner_user)


def status(path: Optional[Path] = None, *, owner_user: Optional[str] = None) -> Optional[dict]:
    """Read the BRAIN ledger's done-rule state (or None when unreachable)."""
    import brain_ledger as bl
    return bl.status(owner_user)


def bump(path: Optional[Path] = None, *, owner_user: Optional[str] = None) -> int:
    """Record one re-entry against the BRAIN ledger (anti-infinite-grind)."""
    import brain_ledger as bl
    return bl.bump(owner_user)


def clear(path: Optional[Path] = None) -> bool:
    """Close the OFFLINE file cache (degraded path only). The brain ledger is
    closed by releasing leaves (brain.work_release), not by deleting a file —
    so this only clears the local offline cache when one exists."""
    p = Path(path) if path else default_path()
    if p.is_file():
        p.unlink()
        return True
    return False


# ── legacy file helpers (OFFLINE fallback only — NOT a parallel store) ────


def register_file(gates: List[dict], *, scope: str = "", cap: int = 12,
                  path: Optional[Path] = None) -> Path:
    """Write the legacy JSON-file ledger directly. Retained ONLY for the offline
    degraded path + back-compat tests; the authoritative path is `register`."""
    p = Path(path) if path else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"scope": scope, "gates": list(gates),
                    "iterations": 0, "cap": int(cap)}, indent=2),
        encoding="utf-8",
    )
    return p


def status_file(path: Optional[Path] = None) -> Optional[dict]:
    p = Path(path) if path else default_path()
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))  # tolerate BOM


if __name__ == "__main__":  # tiny CLI: register/status/bump/clear
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status() or {}, indent=2))
    elif cmd == "bump":
        print("iterations:", bump())
    elif cmd == "clear":
        print("cleared:", clear())
    else:
        print("usage: active_work.py [status|bump|clear]")
