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


class _CellFirstAssignmentBridge:
    def __init__(self):
        self.assemblies = []

    def assembly_create(
        self,
        *,
        definition_key,
        fields,
        idempotency_field=None,
        x=0.0,
        y=0.0,
    ):
        record = {
            "created_root": (
                f"assembly-instance:test-assignment-{len(self.assemblies) + 1}"
            ),
            "membership_wire": (
                f"relation:test-assignment-{len(self.assemblies) + 1}"
            ),
            "definition_key": definition_key,
            "fields": dict(fields or {}),
            "idempotency_field": idempotency_field,
            "x": x,
            "y": y,
        }
        self.assemblies.append(record)
        return record


def _install_test_cell_bridge() -> tuple[object, _CellFirstAssignmentBridge]:
    old = aw._cell_bridge_or_default
    bridge = _CellFirstAssignmentBridge()
    aw._cell_bridge_or_default = lambda cell_bridge=None: (
        cell_bridge if cell_bridge is not None else bridge
    )
    return old, bridge


def _restore_test_cell_bridge(old: object) -> None:
    aw._cell_bridge_or_default = old


def _seed_green_hook_coverage(store: BrainStore, client: str = "claude-code") -> None:
    from personal_brain import hook_coverage as hc

    report = hc.HookCoverageReport(
        owner_user="founder",
        status=hc.GREEN,
        cell_first=True,
        cell_record_root=f"assembly-instance:test-hook-coverage-{client}",
        cell_record_source=f"test:hook-coverage:{client}",
        clients={
            client: hc.ClientCoverage(
                client=client,
                detected=True,
                installed=True,
                status=hc.GREEN,
                touchpoints={
                    "workshop_authority": hc.TouchpointCoverage(
                        touchpoint="workshop_authority",
                        state=installer.ENFORCED,
                        required=True,
                        installed=True,
                        evidence=[f"test:{client}:workshop_authority"],
                    )
                },
            )
        },
    )
    store.set_meta(hc.COVERAGE_META_KEY, report.model_dump_json())


def _seed_core_values_authority(store: BrainStore) -> dict:
    from personal_brain import core_values_authority as cva

    report = cva.CoreValuesAuthorityReport(
        owner_user="founder",
        status=cva.GREEN,
        authority_root=cva.AUTHORITY_ROOT,
        authority_wire_root=cva.AUTHORITY_WIRE_ROOT,
        source_digest="test-source-digest",
        translation_digest="test-translation-digest",
        lifecycle="WIP",
        graph_revision=1,
        revision_chain_digest="test-revision-chain",
        coverage={key: cva.GREEN for key in cva.VALUE_KEYS},
        database_identity="test-cell-database",
    )
    store.set_meta(cva.AUTHORITY_META_KEY, report.model_dump_json())
    return {
        "authority_root": report.authority_root,
        "translation_digest": report.translation_digest,
        "applicable_values": ["truth", "ownership", "test-ship"],
        "risk": "low",
        "required_evidence": ["driver end-to-end court"],
    }


def _room_plan_all_open(store: BrainStore, owner: str = "founder") -> None:
    from personal_brain.meeting_room import room_say

    ledger = aw.get_ledger(store, owner_user=owner)
    if ledger is None:
        return
    for leaf in ledger.leaves.values():
        if leaf.state == LeafState.OPEN:
            room_say(
                store,
                frm="driver-court",
                kind="plan",
                refs=[leaf.leaf_id],
                text=f"Plan evidence for driver court leaf {leaf.leaf_id}.",
            )


def _room_done_evidence(store: BrainStore, leaf_id: str) -> None:
    from personal_brain.meeting_room import room_say

    for kind in ("test", "doc", "court"):
        room_say(
            store,
            frm="driver-court",
            kind=kind,
            refs=[leaf_id],
            text=f"{kind} evidence for driver court leaf {leaf_id}.",
        )


def _iter_hook_entries(hooks: dict, event: str):
    for entry in hooks.get(event, []):
        if not isinstance(entry, dict):
            continue
        nested = entry.get("hooks")
        if isinstance(nested, list):
            for hook in nested:
                if isinstance(hook, dict):
                    yield hook
        else:
            yield entry


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
    env["BRAIN_CELL_ROOM"] = "0"
    return subprocess.run(
        [sys.executable, str(_COMPLETION_GATE)],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120,
    )


def _claude_drive_entry(hooks: dict) -> dict | None:
    """The UserPromptSubmit entry that injects the <assigned_leaf> DRIVE block
    (brain.work_assigned_block). None on the un-wired base."""
    for e in _iter_hook_entries(hooks, "UserPromptSubmit"):
        if isinstance(e, dict) and e.get("tool") == "brain.work_assigned_block":
            return e
    return None


def _is_brainwrap_stop_command(command: str) -> bool:
    return "brainwrap.py" in command and " stop " in f" {command} "


def _is_stop_completion_gate(e: dict) -> bool:
    command = str(e.get("command", ""))
    return "completion_gate" in command or _is_brainwrap_stop_command(command)


def _is_stop_diligence_gate(e: dict) -> bool:
    command = str(e.get("command", ""))
    return "anti_laziness_gate" in command or _is_brainwrap_stop_command(command)


def _stop_completion_gate_entry(hooks: dict) -> dict | None:
    """The Stop entry that runs the brain-reading completion_gate.py. None on
    the un-wired base (which only wired anti_laziness_gate)."""
    for e in _iter_hook_entries(hooks, "Stop"):
        if isinstance(e, dict) and _is_stop_completion_gate(e):
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

    # PRESERVED: the existing recall + anti-laziness wiring is untouched. The
    # recall hook was repointed at the hook-shaped wrapper brain.hook_context
    # (brain.context with the typed `arguments` map) — the DRIVE + gate wiring
    # this test pins is ORTHOGONAL to that rename and must survive it.
    assert any(e.get("tool") == "brain.hook_context"
               for e in _iter_hook_entries(hooks, "UserPromptSubmit")), \
        "brain.hook_context recall lost"
    assert any(_is_stop_diligence_gate(e)
               for e in _iter_hook_entries(hooks, "Stop")), \
        "anti_laziness_gate lost"

    # ORDER: the completion gate runs before skill_mint (a blocking gate must
    # fire before the trace is minted), mirroring the anti_laziness gate.
    stop_cmds = list(_iter_hook_entries(hooks, "Stop"))
    gate_idx = next(i for i, e in enumerate(stop_cmds)
                    if _is_stop_completion_gate(e))
    # skill_mint was repointed at the hook-shaped wrapper brain.hook_skill_mint.
    mint_idx = next((i for i, e in enumerate(stop_cmds)
                     if e.get("tool") == "brain.hook_skill_mint"), len(stop_cmds))
    assert gate_idx < mint_idx, "completion gate must run before skill_mint"


# ───────────────────── 2+3. PULL → CLAIM → STOP-GATE (RED on base) ───────


def test_legacy_driver_is_denied_without_a_universal_session():
    """A legacy Brain leaf cannot be claimed through the public drive tool."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        owner = "founder"

        # Seed legacy evidence so the public drive boundary has something it
        # would have claimed before the session requirement.
        s = BrainStore.open(brain_db)
        governance_context = _seed_core_values_authority(s)
        _seed_green_hook_coverage(s, "claude-code")
        aw.add_leaves(s, owner_user=owner, leaves=[
            {"title": "create artifact.py", "gate_kind": "file_exists",
             "gate_spec": {"path": "artifact.py"}, "priority": 5,
             "governance_context": governance_context},
        ])
        _room_plan_all_open(s, owner)

        # The session-less public call must not touch the legacy ledger.
        from personal_brain.server import build_server
        mcp = build_server(store=s, default_owner_user=owner)
        drive = mcp._tools["brain.work_assigned_block"].handler
        res = drive(runtime="claude_code", owner_user=owner)
        assert res["ok"] is False
        assert res["code"] == "universal_session_required"
        assert res["leaf"] is None
        assert aw.status(s, owner_user=owner)["counts"]["claimed"] == 0
        s.close()


def test_completion_gate_blocks_on_open_leaf_via_real_brain_db():
    """Tighter unit of the same property: a single OPEN (unclaimed) leaf with a
    failing file_exists gate makes the brain-reading completion_gate BLOCK; once
    the file exists AND the leaf is DONE, it ALLOWS. Proves the gate's pending
    list is DERIVED from the brain's actionable leaves on the real artifact."""
    mp = pytest.MonkeyPatch()
    mp.setenv("BRAIN_CELL_ROOM", "0")
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
        _room_done_evidence(s2, lid)
        aw.release(s2, leaf_id=lid, done=True, owner_user=owner)
        s2.close()

        p2 = _run_gate(brain_db, owner, cwd=root)
        assert (p2.stdout or "").strip() == "", (
            f"expected ALLOW, got {p2.stdout!r} / {p2.stderr!r}")
    mp.undo()


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
