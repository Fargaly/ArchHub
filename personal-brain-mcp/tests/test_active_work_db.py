"""Tests for the SERVER-AUTHORITATIVE active-work ledger (active_work.py) — BRV-01/02.

Proves THE BRAIN-DRIVER CORE is real: the ledger round-trips through a real
brain.db (claim -> status -> release), the brain DRIVES the next leaf to a
runtime (next_leaf claims atomically), and the shared client_hook emits the
<assigned_leaf> pre-prompt block every client prepends.

Mirrors tests/test_active_work.py (the v0 file-ledger gate) but exercises the
brain-side store. The headline gate uses a REAL on-disk brain.db file (NOT
:memory:) and REOPENS it, so persistence is proven against the actual database
the daemon uses — not an ephemeral connection. Runs under pytest AND standalone:
`python personal-brain-mcp/tests/test_active_work_db.py`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make the bundled brain package importable when run standalone.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from personal_brain import active_work as aw  # noqa: E402
from personal_brain import client_hook as ch  # noqa: E402
from personal_brain.active_work import LeafState  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ─────────────────── the headline gate: brain.db round-trip ─────────────


def test_ledger_roundtrips_through_brain_db_file():
    """claim -> status -> release, proven against a REAL on-disk brain.db that
    is closed and REOPENED between writes (durable persistence, not a live
    connection)."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "brain.db"

        # 1) PRODUCE: enqueue one gated leaf, then close the DB entirely.
        s1 = BrainStore.open(db)
        aw.add_leaves(s1, owner_user="founder", leaves=[
            {"title": "build the thing", "gate_kind": "file_exists",
             "gate_spec": {"path": "x.py"}, "priority": 5},
        ])
        s1.close()

        # 2) DRIVE: reopen the SAME file -> the brain hands the runtime its next
        #    leaf and CLAIMS it atomically (open -> claimed). Persist + close.
        s2 = BrainStore.open(db)
        leaf = aw.next_leaf(s2, runtime="claude_code", owner_user="founder")
        assert leaf is not None and leaf.title == "build the thing"
        assert leaf.state == LeafState.CLAIMED
        assert leaf.claimed_by == "claude_code"   # default agent_id = runtime
        leaf_id = leaf.leaf_id
        s2.close()

        # 3) STATUS: reopen -> the claim survived the round-trip; not dry yet
        #    (a claimed leaf is still actionable).
        s3 = BrainStore.open(db)
        st = aw.status(s3, owner_user="founder")
        assert st["exists"] is True
        assert st["counts"]["claimed"] == 1 and st["counts"]["open"] == 0
        assert st["dry"] is False
        # the single brain_meta key holds it; nothing leaked into skills.
        assert s3.get_meta(aw.LEDGER_META_KEY)
        assert s3.count_skills() == 0
        s3.close()

        # 4) RELEASE done -> DONE, with evidence. Reopen -> drive is DRY.
        s4 = BrainStore.open(db)
        done = aw.release(s4, leaf_id=leaf_id, done=True,
                          owner_user="founder", evidence_ref="x.py written")
        assert done.state == LeafState.DONE and done.evidence_ref == "x.py written"
        s4.close()

        s5 = BrainStore.open(db)
        st2 = aw.status(s5, owner_user="founder")
        assert st2["counts"]["done"] == 1
        assert st2["dry"] is True        # nothing actionable left -> done-rule fires
        s5.close()


# ─────────────────── unit behaviour (in-memory is fine) ─────────────────


def test_add_is_additive_under_one_meta_key(store):
    aw.add_leaves(store, owner_user="founder",
                  leaves=[{"title": "a"}, {"title": "b"}])
    # exactly ONE brain_meta key, no table, no skills/fragments leakage.
    assert store.get_meta(aw.LEDGER_META_KEY)
    assert store.count_skills() == 0
    led = aw.get_ledger(store, owner_user="founder")
    assert led is not None and len(led.leaves) == 2


def test_add_is_idempotent_on_title(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "same"}])
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "same"}])
    led = aw.get_ledger(store, owner_user="founder")
    assert len(led.leaves) == 1          # re-adding the same title -> no dup


def test_next_leaf_is_atomic_no_double_claim(store):
    """Two pulls can never grab the same leaf — the brain is the arbiter."""
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "only one"}])
    a = aw.next_leaf(store, runtime="codex", owner_user="founder")
    b = aw.next_leaf(store, runtime="gemini", owner_user="founder")
    assert a is not None and a.title == "only one"
    assert b is None                     # already claimed -> frontier dry for b


def test_next_leaf_priority_then_fifo(store):
    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "low", "priority": 1},
        {"title": "high", "priority": 9},
    ])
    first = aw.next_leaf(store, runtime="claude_code", owner_user="founder")
    assert first.title == "high"         # highest priority pulled first


def test_fit_gating_specialised_leaf_not_handed_to_wrong_runtime(store):
    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "revit job", "fit": ["revit"]},
    ])
    # a runtime that can't do revit gets nothing...
    assert aw.next_leaf(store, runtime="codex", fit=["python"],
                        owner_user="founder") is None
    # ...but one that offers 'revit' is handed it.
    got = aw.next_leaf(store, runtime="claude_code", fit=["revit", "python"],
                       owner_user="founder")
    assert got is not None and got.title == "revit job"


def test_release_not_done_reopens_and_bumps_attempts(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "retry me"}])
    leaf = aw.next_leaf(store, runtime="codex", owner_user="founder")
    re = aw.release(store, leaf_id=leaf.leaf_id, done=False,
                    owner_user="founder", note="gate red")
    assert re.state == LeafState.OPEN    # back on the frontier
    assert re.attempts == 1 and re.claimed_by is None
    # it can be pulled again (re-work loop).
    again = aw.next_leaf(store, runtime="codex", owner_user="founder")
    assert again is not None and again.leaf_id == leaf.leaf_id


def test_release_blocked_escalates_not_dry(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "needs you"}])
    leaf = aw.next_leaf(store, runtime="codex", owner_user="founder")
    bl = aw.release(store, leaf_id=leaf.leaf_id, done=False, blocked=True,
                    owner_user="founder", note="need a credential")
    assert bl.state == LeafState.BLOCKED
    st = aw.status(store, owner_user="founder")
    assert st["blocked"] == [leaf.leaf_id]
    assert st["dry"] is False            # a blocked leaf is NOT done


def test_claim_specific_refuses_self_certify_anchor_and_double_claim(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "x"}])
    led = aw.get_ledger(store, owner_user="founder")
    lid = next(iter(led.leaves))
    aw.claim(store, leaf_id=lid, agent_id="agent-A", owner_user="founder")
    # a DIFFERENT agent cannot steal it.
    with pytest.raises(ValueError):
        aw.claim(store, leaf_id=lid, agent_id="agent-B", owner_user="founder")
    # empty agent_id is refused (no anti-self-cert anchor).
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "y"}])
    led2 = aw.get_ledger(store, owner_user="founder")
    yid = [k for k, v in led2.leaves.items() if v.title == "y"][0]
    with pytest.raises(ValueError):
        aw.claim(store, leaf_id=yid, agent_id="", owner_user="founder")


def test_bump_iteration_persists(store):
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "x"}])
    assert aw.bump_iteration(store, owner_user="founder") == 1
    assert aw.bump_iteration(store, owner_user="founder") == 2
    assert aw.status(store, owner_user="founder")["iterations"] == 2


def test_status_empty_ledger_is_idle_not_done(store):
    st = aw.status(store, owner_user="nobody")
    assert st["exists"] is False and st["dry"] is False   # idle != done


# ─────────────────── BRV-02: the client_hook pre-prompt block ────────────


def test_client_hook_inproc_drives_and_formats_assigned_leaf(store):
    """The shared pre-prompt helper, in-process: claims the next leaf via the
    brain and renders the <assigned_leaf> block every client prepends."""
    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "wire the panel", "gate_kind": "pytest",
         "gate_spec": {"selector": "tests/test_panel.py"}},
    ])
    block = ch.assigned_leaf_block(runtime="codex", store=store,
                                   owner_user="founder")
    assert "<assigned_leaf>" in block and "</assigned_leaf>" in block
    assert "wire the panel" in block
    assert "brain.work_release" in block         # tells the client how to report
    assert ch.ASSIGNED_START in block and ch.ASSIGNED_END in block
    # the helper actually CLAIMED it (the brain drove the agent).
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 1


def test_client_hook_empty_when_frontier_dry(store):
    # no leaves at all -> the drive is idle -> the block is empty (turn not
    # blocked by an idle drive).
    assert ch.assigned_leaf_block(runtime="codex", store=store,
                                  owner_user="founder") == ""


def test_format_assigned_leaf_is_empty_for_none():
    assert ch.format_assigned_leaf({}) == ""


# ─────────────────── standalone runner (no pytest required) ─────────────


def _run_standalone() -> int:
    import contextlib

    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        s = None
        try:
            if "store" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                s = BrainStore.open(":memory:")
                fn(s)
            else:
                fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
        finally:
            if s is not None:
                with contextlib.suppress(Exception):
                    s.close()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
