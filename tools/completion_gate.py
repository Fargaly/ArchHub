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

ONE-SYSTEM (AgDR-0054 S1 + ONE-SYSTEM mandate): this gate now reads its
done-gates from the BRAIN LEDGER — the single server-authoritative
`brain_meta['active_work_v1']` store the all-agents drive writes — via
`tools/brain_ledger.py`. The gate's pending list is DERIVED from the brain's
actionable (open/claimed) leaves; a DONE leaf is already green, a BLOCKED leaf
escalates to the founder. There is no longer a forked local ledger: the legacy
JSON file is consulted ONLY when the brain is genuinely unreachable (an offline
cache, not a parallel store), and `brain_ledger.transport()` reports which
backend answered so the founder can SEE which store the verdict came from.

Honest scope (do not overclaim): wiring this into ~/.claude/settings.json edits
the founder's GLOBAL config + blocks his live turns -> founder-gated (the one
remaining step). The brain-side adjudication is the authoritative, non-skippable
gate (AgDR-0054 S4).

Stop-hook contract (Claude Code): the gate's done-list comes from the brain
ledger (owner-resolved like the daemon), NOT stdin. When the brain is
unreachable it falls back to a file located via argv[0] or $ARCHHUB_ACTIVE_WORK
(the hook JSON on stdin carries no ledger pointer and is not read). Output
contract: to BLOCK, print {"decision":"block","reason":"...","source":"..."} and
exit 0; to ALLOW, exit 0 with no block. Nothing actionable -> ALLOW (safe
default).
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
    kind: str = "file_exists"   # file_exists | grep_clean | pytest | py_compile | manual
    arg: str = ""               # path / regex / pytest-selector / py_compile target
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
    if g.kind == "py_compile":
        # PASS iff the named module byte-compiles (the brain leaf's py_compile
        # gate, run against the real file).
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", g.arg],
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


def _gate_from_dict(d: dict) -> Gate:
    """Build a Gate from a dict, ignoring private (_-prefixed) hint keys that
    brain_ledger attaches (e.g. _py_compile)."""
    fields = {"name", "kind", "arg", "arg2", "machine_resolvable"}
    return Gate(**{k: v for k, v in d.items() if k in fields})


def _load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate Windows BOM
    gates = [_gate_from_dict(g) for g in data.get("gates", [])]
    return gates, int(data.get("iterations", 0)), int(data.get("cap", CAP_DEFAULT))


def _gates_from_brain():
    """Read done-gates from the BRAIN ledger (the ONE store). Returns
    (gates, iterations, cap, transport) or None when the brain is unreachable.

    This is the ONE-SYSTEM path: the gate's done-list is DERIVED from the brain's
    actionable leaves (the same `brain_meta['active_work_v1']` the server-side
    drive writes), not from a forked local file. A DONE leaf is already green and
    omitted; a BLOCKED leaf surfaces as a needs-root escalation."""
    try:
        import brain_ledger as bl  # tools/ is on sys.path (added in main / by caller)
    except Exception:
        return None
    gate_dicts = bl.leaves_as_gates()
    if gate_dicts is None:
        return None  # brain unreachable -> let caller fall back to the file
    st = bl.status() or {}
    gates = [_gate_from_dict(g) for g in gate_dicts]
    return (gates, int(st.get("iterations", 0)), int(st.get("cap", CAP_DEFAULT)),
            bl.transport())


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # tools/ on sys.path so `import brain_ledger` works when run as a hook.
    _tools = str(Path(__file__).resolve().parent)
    if _tools not in sys.path:
        sys.path.insert(0, _tools)

    # ── ONE-SYSTEM: the brain ledger is authoritative. Read the done-gates from
    # the brain FIRST; the local JSON file is only an offline fallback. ──────
    from_brain = _gates_from_brain()
    if from_brain is not None:
        gates, iters, cap, transport = from_brain
        if not gates:
            # brain reachable + nothing actionable -> allow stop (drive is dry).
            return 0
        v = evaluate(gates, iters, cap, runner=lambda g: run_gate(g, Path.cwd()))
        _emit(v, source=f"brain:{transport}")
        return 0

    # ── DEGRADED: brain genuinely unreachable -> fall back to the local file
    # cache (legacy shape). Located via argv[0] or $ARCHHUB_ACTIVE_WORK. ─────
    ledger: Optional[Path] = None
    if argv:
        ledger = Path(argv[0])
    elif os.environ.get("ARCHHUB_ACTIVE_WORK"):
        ledger = Path(os.environ["ARCHHUB_ACTIVE_WORK"])
    if ledger is None or not ledger.is_file():
        # safe default: nothing registered + brain down -> allow stop.
        return 0
    gates, iters, cap = _load(ledger)
    v = evaluate(gates, iters, cap, runner=lambda g: run_gate(g, Path.cwd()))
    _emit(v, source="file:degraded")
    return 0


def _emit(v: Verdict, *, source: str) -> None:
    """Print the gate verdict in the Stop-hook contract, tagging which store it
    came from so the founder can SEE it read the brain (not a fork)."""
    if v.action == "block":
        print(json.dumps({"decision": "block", "reason": v.reason, "source": source}))
    elif v.action == "escalate":
        sys.stderr.write(f"[completion_gate/{source}] ESCALATE -> founder: " + v.reason + "\n")
        print(json.dumps({"escalate": True, "reason": v.reason, "red": v.red,
                          "source": source}))


if __name__ == "__main__":
    raise SystemExit(main())
