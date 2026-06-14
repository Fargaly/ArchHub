"""completion_gate.py - THE DRIVE: refuse turn-exit while work is unfinished.

AgDR-0054 "THE DRIVE" (v0, per-agent fast-catch). The agent has no intrinsic
drive-to-completion; this externalizes it. A Stop hook calls this when the
agent tries to end a turn:

  - all done-gates green  -> ALLOW the stop (exit 0, no output)
  - any red + machine-resolvable + under the iteration cap -> BLOCK the stop
        (print {"decision":"block","reason": "NOT DONE: <red> ..."}) so the
        agent is handed back in instead of leaving
  - any red that needs a human (machine_resolvable=False) OR the cap is hit ->
        ESCALATE: allow the stop but emit an honest escalation. Never a silent
        quit, never a fake-done, never an infinite grind.

Honest scope (do not overclaim): this is the per-agent EARLY catch. It is NOT
yet wired into ~/.claude/settings.json (that install edits the founder's global
config + blocks his live turns -> founder-gated), and the server-authoritative,
all-agents adjudication lives brain-side (AgDR-0054 S1/S4 + slice-4) -- this
local hook is skippable and therefore not authoritative on its own.

Stop-hook contract (Claude Code): this gate is driven by the active_work LEDGER,
NOT stdin — it locates the ledger via argv[0] or $ARCHHUB_ACTIVE_WORK (the hook
JSON on stdin carries no ledger pointer and is not read). Output contract: to
BLOCK, print {"decision":"block","reason": "..."} and exit 0; to ALLOW, exit 0
with no block. With no ledger registered it ALLOWS (safe default); the
authoritative, non-skippable gate is the brain-side adjudication (AgDR-0054 S1/S4).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

CAP_DEFAULT = 12  # max consecutive blocks before escalate (anti-infinite-grind)

# THE NO-LATER DETECTOR (shared by every surface: Claude Code hook, the ArchHub
# composer, the ai.plan planner). Bare deferral is banned. A legitimate not-now
# item is a STRUCTURED gate in the active_work ledger, NOT a prose tag (a
# co-located 'safety-gated:' in free text was a trivial bypass — removed).
_DEFERRAL = re.compile(
    r"(?i)\b("
    r"later|for now|next session|follow[\s-]?up|to be done|for hardening|"
    r"nice[\s-]?to[\s-]?have|partial(?:ly)?|punt|defer(?:red)?|"
    r"i['’]?ll (?:wire|finish|do|add|build|handle)|"
    r"TODO|FIXME"
    r")\b"
)


def scan_deferral(text: str) -> List[str]:
    """Return the distinct deferral markers in `text` (empty if clean).

    A PURE detector — it flags 'later/partial/TODO/...' wherever they occur and
    does NOT exempt on a co-located 'safety-gated:'/'depends-on:' tag, which was
    a trivial bypass ("I'll do X later, safety-gated: n/a"). A legitimate not-now
    item must be a STRUCTURED gate in the active_work ledger
    (machine_resolvable=False / a depends_on field), never a word in a reply."""
    if not text:
        return []
    return sorted({m.lower() for m in _DEFERRAL.findall(text)})


@dataclass
class Gate:
    name: str
    kind: str = "file_exists"   # file_exists | grep_clean | pytest | manual
    arg: str = ""               # path / regex / pytest-selector
    arg2: str = ""              # grep_clean: comma-separated relative paths
    machine_resolvable: bool = True  # human-only gates set False -> escalate


@dataclass
class Verdict:
    action: str                 # allow | block | escalate
    reason: str = ""
    red: List[str] = field(default_factory=list)


def run_gate(g: Gate, root: Path) -> bool:
    """Run one gate against reality. Return True iff it PASSES (green)."""
    if g.kind == "file_exists":
        return (root / g.arg).exists()
    if g.kind == "grep_clean":
        # PASS iff the pattern matches NOWHERE in the given files (no deferral markers).
        pat = re.compile(g.arg)
        for rel in (p.strip() for p in g.arg2.split(",") if p.strip()):
            fp = root / rel
            if fp.is_file() and pat.search(fp.read_text(encoding="utf-8", errors="ignore")):
                return False
        return True
    if g.kind == "pytest":
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", g.arg],
            cwd=str(root), capture_output=True,
        )
        return proc.returncode == 0
    if g.kind == "manual":
        return False  # a manual/unverifiable gate is never auto-green -> escalate
    raise ValueError(f"unknown gate kind: {g.kind!r}")


def evaluate(
    gates: List[Gate],
    iterations: int,
    cap: int = CAP_DEFAULT,
    runner: Optional[Callable[[Gate], bool]] = None,
) -> Verdict:
    """Pure decision core. `runner(gate) -> passes?` is injected for testing."""
    run = runner if runner is not None else (lambda g: run_gate(g, Path.cwd()))
    red = [g for g in gates if not run(g)]
    if not red:
        return Verdict("allow")
    needs_root = [g for g in red if not g.machine_resolvable]
    if needs_root:
        return Verdict(
            "escalate",
            reason="needs you: " + ", ".join(g.name for g in needs_root),
            red=[g.name for g in red],
        )
    if iterations >= cap:
        return Verdict(
            "escalate",
            reason=f"cap {cap} hit, still red: " + ", ".join(g.name for g in red),
            red=[g.name for g in red],
        )
    return Verdict(
        "block",
        reason="NOT DONE: " + ", ".join(g.name for g in red) + ". continue.",
        red=[g.name for g in red],
    )


def _load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate Windows BOM
    gates = [Gate(**g) for g in data.get("gates", [])]
    return gates, int(data.get("iterations", 0)), int(data.get("cap", CAP_DEFAULT))


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Locate the active_work ledger via argv[0] or $ARCHHUB_ACTIVE_WORK. (The
    # Stop-hook stdin JSON carries no ledger pointer, so it is not read.)
    ledger: Optional[Path] = None
    if argv:
        ledger = Path(argv[0])
    elif os.environ.get("ARCHHUB_ACTIVE_WORK"):
        ledger = Path(os.environ["ARCHHUB_ACTIVE_WORK"])
    if ledger is None or not ledger.is_file():
        # v0 safe default: nothing registered -> allow stop. (Brain-side
        # adjudication is the authoritative path; this local hook never
        # blocks blindly.)
        return 0
    gates, iters, cap = _load(ledger)
    v = evaluate(gates, iters, cap, runner=lambda g: run_gate(g, Path.cwd()))
    if v.action == "block":
        print(json.dumps({"decision": "block", "reason": v.reason}))
    elif v.action == "escalate":
        sys.stderr.write("[completion_gate] ESCALATE -> founder: " + v.reason + "\n")
        print(json.dumps({"escalate": True, "reason": v.reason, "red": v.red}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
