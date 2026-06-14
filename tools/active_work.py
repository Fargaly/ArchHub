"""active_work.py — the PRODUCER side of THE DRIVE's ledger (AgDR-0054).

`completion_gate.py` READS an active-work ledger (the current job's done-gates)
and refuses turn-exit while any gate is red. This module WRITES that ledger:

  - register(gates)  : open a job — record the done-gates the agent must satisfy
  - status()         : read the current ledger (or None)
  - bump()           : record one re-entry (the gate blocked + handed me back)
  - clear()          : close the job — remove the ledger so the gate allows stop

v0 storage = a JSON file at $ARCHHUB_ACTIVE_WORK, else <cwd>/.archhub/active_work.json
(the same path completion_gate reads). The brain-side, server-authoritative,
all-agents version (AgDR-0054 S1) builds on this exact ledger shape — it is the
roadmap slice, recorded in docs/ROADMAP.md, not a chat promise.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

DEFAULT_REL = ".archhub/active_work.json"


def default_path() -> Path:
    env = os.environ.get("ARCHHUB_ACTIVE_WORK")
    return Path(env) if env else (Path.cwd() / DEFAULT_REL)


def register(gates: List[dict], *, scope: str = "", cap: int = 12,
             path: Optional[Path] = None) -> Path:
    """Open a job: write the done-gates that must be green before the agent may
    stop. `gates` is a list of completion_gate.Gate dicts
    ({name, kind, arg, arg2, machine_resolvable})."""
    p = Path(path) if path else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"scope": scope, "gates": list(gates),
                    "iterations": 0, "cap": int(cap)}, indent=2),
        encoding="utf-8",
    )
    return p


def status(path: Optional[Path] = None) -> Optional[dict]:
    p = Path(path) if path else default_path()
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))  # tolerate BOM


def bump(path: Optional[Path] = None) -> int:
    """Record one more re-entry (the gate blocked the stop + fed the agent the
    unfinished list). The cap on these is the anti-infinite-grind backstop."""
    p = Path(path) if path else default_path()
    d = status(p) or {"scope": "", "gates": [], "iterations": 0, "cap": 12}
    d["iterations"] = int(d.get("iterations", 0)) + 1
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d["iterations"]


def clear(path: Optional[Path] = None) -> bool:
    """Close the job: remove the ledger so the gate allows the stop. Returns
    True if a ledger was present and removed."""
    p = Path(path) if path else default_path()
    if p.is_file():
        p.unlink()
        return True
    return False


if __name__ == "__main__":  # tiny CLI: register/status/bump/clear
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status() or {}, indent=2))
    elif cmd == "bump":
        print("iterations:", bump())
    elif cmd == "clear":
        print("cleared:", clear())
    else:
        print("usage: active_work.py [status|bump|clear]")
