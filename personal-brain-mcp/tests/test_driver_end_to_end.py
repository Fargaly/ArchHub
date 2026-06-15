"""END-TO-END proof of THE DRIVE wired into the runtime (court defect #5).

The headline defect: the active-work ledger is consumable, but on
`origin/fix/driver-unify-atomic` it was wired into NOTHING at runtime — no
agent pulled a leaf at pre-prompt, no Stop hook ran the brain-reading
completion gate. The ledger could drive, but nothing called it.

This test proves the REAL flow, end to end, against a REAL on-disk brain.db:

  1. WIRING. The installer's Claude Code templates now carry the DRIVE
     (UserPromptSubmit → brain.work_assigned_block) AND the brain-reading Stop
     gate (Stop → tools/completion_gate.py), in ADDITION to the existing
     brain.context recall + anti_laziness_gate. On the un-wired base these
     assertions FAIL (no such entries) → the test is RED before the fix.

  2. PRE-PROMPT PULL. Simulating the pre-prompt hook, an agent (runtime,fit)
     PULLS its next leaf and the brain CLAIMS it atomically — the agent
     receives the <assigned_leaf> context block (the brain drove it).

  3. STOP GATE. Simulating the Stop hook, `tools/completion_gate.py` reads the
     BRAIN ledger (not a forked file) and BLOCKS the turn-exit while that leaf
     is open/claimed, then ALLOWS once the leaf is released DONE.

Steps 2–3 run the SAME code paths the wired templates invoke (the
brain.work_assigned_block handler for the drive; the real completion_gate.py
process for the gate), so a green here means the wiring points at code that
actually drives + gates — not dead config.

Runs under pytest AND standalone:
  python personal-brain-mcp/tests/test_driver_end_to_end.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Make the bundled brain package importable when run standalone.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# repo root = <repo>/personal-brain-mcp/tests/.. /..  → has tools/.
_REPO = Path(__file__).resolve().parents[2]
_COMPLETION_GATE = _REPO / "tools" / "completion_gate.py"

import pytest  # noqa: E402

from personal_brain import active_work as aw  # noqa: E402
from personal_brain import installer  # noqa: E402
from personal_brain.active_work import LeafState  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


# ───────────────────────── helpers ──────────────────────────────────────


def _run_gate(brain_db: Path, owner: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run tools/completion_gate.py EXACTLY as the wired Stop hook would: as a
    subprocess, brain daemon DOWN, pointed at a specific on-disk brain.db + owner
    via env. The gate then reads the brain ledger over its in-process transport
    (the SAME brain.db the drive wrote) and prints its block/allow verdict."""
    env = dict(os.environ)
    env["ARCHHUB_BRAIN_DB"] = str(brain_db)
    env["BRAIN_OWNER_USER"] = owner
    # Force the daemon transport OFF so the gate uses the in-process brain.db
    # path (point it at a dead port). This is the ONE store, just reached
    # without a daemon — NOT the degraded file cache.
    env["BRAIN_DAEMON_URL"] = "http://127.0.0.1:1/mcp"
    return subprocess.run(
        [sys.executable, str(_COMPLETION_GATE)],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120,
    )


def _claude_drive_entry(hooks: dict) -> dict | None:
    """The UserPromptSubmit entry that injects the <assigned_leaf> DRIVE block
    (brain.work_assigned_block). None on the un-wired base."""
    for e in hooks.get("UserPromptSubmit", []):
        if isinstance(e, dict) and e.get("tool") == "brain.work_assigned_block":
            return e
    return None


def _stop_completion_gate_entry(hooks: dict) -> dict | None:
    """The Stop entry that runs the brain-reading completion_gate.py. None on
    the un-wired base (which only wired anti_laziness_gate)."""
    for e in hooks.get("Stop", []):
        if isinstance(e, dict) and "completion_gate" in str(e.get("command", "")):
            return e
    return None


# ───────────────────────── 1. WIRING (RED on base) ──────────────────────


def test_installer_wires_drive_and_completion_gate_into_claude_code(
    tmp_path, monkeypatch,
):
    """The installer's Claude Code template must carry BOTH new touchpoints:
    UserPromptSubmit → brain.work_assigned_block (DRIVE) and Stop →
    completion_gate.py (brain-reading gate), WITHOUT regressing the existing
    brain.context recall + anti_laziness_gate. FAILS on the un-wired base."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    installer.ALL_PLANS["claude-code"].config_path = (
        tmp_path / ".claude" / "settings.json")
    (tmp_path / ".claude").mkdir()

    installer.install_all(only=["claude-code"])
    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    hooks = cfg["hooks"]

    # NEW: the DRIVE injects the assigned leaf at pre-prompt.
    drive = _claude_drive_entry(hooks)
    assert drive is not None, (
        "UserPromptSubmit must ALSO inject the <assigned_leaf> DRIVE via "
        "brain.work_assigned_block — the brain drives no agent without it")
    assert drive.get("server") == "brain"

    # NEW: the Stop hook runs the brain-reading completion gate.
    gate = _stop_completion_gate_entry(hooks)
    assert gate is not None, (
        "Stop must ALSO run tools/completion_gate.py (the brain-reading gate) — "
        "without it no Stop hook reads the ledger to block a premature exit")
    assert gate.get("type") == "command"

    # PRESERVED: the existing recall + anti-laziness wiring is untouched.
    assert any(e.get("tool") == "brain.context"
               for e in hooks["UserPromptSubmit"]), "brain.context recall lost"
    assert any("anti_laziness_gate" in str(e.get("command", ""))
               for e in hooks["Stop"]), "anti_laziness_gate lost"

    # ORDER: the completion gate runs before skill_mint (a blocking gate must
    # fire before the trace is minted), mirroring the anti_laziness gate.
    stop_cmds = hooks["Stop"]
    gate_idx = next(i for i, e in enumerate(stop_cmds)
                    if "completion_gate" in str(e.get("command", "")))
    mint_idx = next((i for i, e in enumerate(stop_cmds)
                     if e.get("tool") == "brain.skill_mint"), len(stop_cmds))
    assert gate_idx < mint_idx, "completion gate must run before skill_mint"


# ───────────────────── 2+3. PULL → CLAIM → STOP-GATE (RED on base) ───────


def test_agent_pulls_leaf_then_completion_gate_blocks_then_allows():
    """The headline end-to-end flow on a REAL brain.db:

      pre-prompt: an agent PULLS + CLAIMS a leaf (gets the <assigned_leaf>).
      stop:       completion_gate.py reads the BRAIN ledger and BLOCKS while
                  the leaf is open/claimed.
      release:    the leaf goes DONE.
      stop again: completion_gate.py now ALLOWS (drive is dry).

    This exercises the SAME drive call the wired UserPromptSubmit hook makes
    (brain.work_assigned_block → client_hook) and the SAME gate process the
    wired Stop hook runs (tools/completion_gate.py)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        owner = "founder"

        # PRODUCE: enqueue one gated leaf whose done-gate is a real file that
        # does NOT exist yet (so the gate is RED until the agent makes it).
        s = BrainStore.open(brain_db)
        aw.add_leaves(s, owner_user=owner, leaves=[
            {"title": "create artifact.py", "gate_kind": "file_exists",
             "gate_spec": {"path": "artifact.py"}, "priority": 5},
        ])

        # PRE-PROMPT PULL: the brain hands the runtime its next leaf via the
        # daemon-served drive block (the SAME handler the wired UserPromptSubmit
        # hook calls). The agent receives the <assigned_leaf> AND the leaf is
        # CLAIMED atomically server-side.
        from personal_brain.server import build_server
        mcp = build_server(store=s, default_owner_user=owner)
        drive = mcp._tools["brain.work_assigned_block"].handler
        res = drive(runtime="claude_code", owner_user=owner)
        assert res["ok"] and "<assigned_leaf>" in res["block"]
        assert "create artifact.py" in res["block"]
        st = aw.status(s, owner_user=owner)
        assert st["counts"]["claimed"] == 1, "the brain did not claim the leaf"
        s.close()   # close so the subprocess opens the same file cleanly (WAL)

        # STOP (leaf still open/claimed, artifact absent): the gate must BLOCK.
        proc = _run_gate(brain_db, owner, cwd=root)
        assert proc.returncode == 0, proc.stderr
        out = (proc.stdout or "").strip()
        assert out, ("completion_gate produced no verdict — it did not read the "
                     f"brain ledger. stderr={proc.stderr!r}")
        verdict = json.loads(out)
        assert verdict.get("decision") == "block", (
            f"gate must BLOCK while the leaf is open; got {verdict!r}")
        # PROOF it read the BRAIN (not a forked file): the source is brain:*.
        assert str(verdict.get("source", "")).startswith("brain:"), (
            f"gate must read the brain ledger, not a fork; source={verdict.get('source')!r}")

        # RELEASE the leaf DONE (the agent finished + the gate's predicate is met).
        s2 = BrainStore.open(brain_db)
        leaf = next(iter(aw.get_ledger(s2, owner_user=owner).leaves.values()))
        assert leaf.state == LeafState.CLAIMED
        aw.release(s2, leaf_id=leaf.leaf_id, done=True, owner_user=owner,
                   evidence_ref="artifact.py written")
        assert aw.status(s2, owner_user=owner)["dry"] is True
        s2.close()

        # STOP again (drive dry): the gate must ALLOW (no block printed).
        proc2 = _run_gate(brain_db, owner, cwd=root)
        assert proc2.returncode == 0, proc2.stderr
        out2 = (proc2.stdout or "").strip()
        assert out2 == "", (
            f"gate must ALLOW once the drive is dry; got block/escalate: {out2!r}")


def test_completion_gate_blocks_on_open_leaf_via_real_brain_db():
    """Tighter unit of the same property: a single OPEN (unclaimed) leaf with a
    failing file_exists gate makes the brain-reading completion_gate BLOCK; once
    the file exists AND the leaf is DONE, it ALLOWS. Proves the gate's pending
    list is DERIVED from the brain's actionable leaves on the real artifact."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        owner = "founder"
        s = BrainStore.open(brain_db)
        aw.add_leaves(s, owner_user=owner, leaves=[
            {"title": "ship feature", "gate_kind": "file_exists",
             "gate_spec": {"path": "done.flag"}},
        ])
        s.close()

        # OPEN leaf, gate file absent → BLOCK.
        p1 = _run_gate(brain_db, owner, cwd=root)
        v1 = json.loads((p1.stdout or "{}").strip() or "{}")
        assert v1.get("decision") == "block", f"expected block, got {v1!r}"

        # Make the gate's predicate real AND mark the leaf DONE → ALLOW.
        (root / "done.flag").write_text("ok", encoding="utf-8")
        s2 = BrainStore.open(brain_db)
        lid = next(iter(aw.get_ledger(s2, owner_user=owner).leaves))
        aw.release(s2, leaf_id=lid, done=True, owner_user=owner)
        s2.close()

        p2 = _run_gate(brain_db, owner, cwd=root)
        assert (p2.stdout or "").strip() == "", (
            f"expected ALLOW, got {p2.stdout!r} / {p2.stderr!r}")


# ───────────────────── standalone runner (no pytest required) ────────────


def _run_standalone() -> int:
    import contextlib  # noqa: F401

    failed = 0
    # the wiring test needs monkeypatch+tmp_path; run only the env-driven ones
    # standalone (the wiring test runs under pytest).
    standalone = [
        test_agent_pulls_leaf_then_completion_gate_blocks_then_allows,
        test_completion_gate_blocks_on_open_leaf_via_real_brain_db,
    ]
    for fn in standalone:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(standalone) - failed}/{len(standalone)} passed (standalone)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
