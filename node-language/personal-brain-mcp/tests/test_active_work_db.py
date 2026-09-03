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
import threading
import time
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


def test_next_leaf_sequential_no_double_claim(store):
    """Sequential sanity: a second pull on a one-leaf ledger gets nothing.
    (The CONCURRENT proof — the one that actually refutes the TOCTOU race — is
    test_next_leaf_is_atomic_under_real_concurrency below.)"""
    aw.add_leaves(store, owner_user="founder", leaves=[{"title": "only one"}])
    a = aw.next_leaf(store, runtime="codex", owner_user="founder")
    b = aw.next_leaf(store, runtime="gemini", owner_user="founder")
    assert a is not None and a.title == "only one"
    assert b is None                     # already claimed -> frontier dry for b


@pytest.mark.parametrize("round_no", range(8))
def test_next_leaf_is_atomic_under_real_concurrency(round_no):
    """THE refutation killer (court defect #2 — TOCTOU double-claim).

    Two threads call next_leaf on ONE leaf, released together by a barrier, with
    a forced YIELD injected INSIDE the read-modify-write window (right after a
    thread READS the ledger but before it WRITES). On the OLD code the select
    (load→get_meta) released the store lock before the claim (save→set_meta)
    re-acquired it, so both threads read state=OPEN and BOTH claimed the same
    leaf — a double-claim, AND the first claim is lost (last-writer-wins). This
    test FAILS on that code (two non-None winners). After the single-critical-
    section fix (next_leaf routes through BrainStore.update_meta, which holds the
    RLock across get→decide→set), exactly ONE thread wins.

    Runs several rounds because a race is probabilistic; the forced yield makes
    the double-claim deterministic on the buggy code in practice.
    """
    s = BrainStore.open(":memory:")
    try:
        aw.add_leaves(s, owner_user="founder", leaves=[{"title": "only one"}])

        # Force a yield in the OLD code's unlocked window: after load reads the
        # ledger blob (get_meta) and before save writes it (set_meta). The fixed
        # code's critical section uses update_meta's inline read (NOT get_meta),
        # so this yield can't split it — that's the discriminator.
        real_get = s.get_meta
        barrier = threading.Barrier(2)

        def slow_get(key):
            val = real_get(key)
            if key == aw.LEDGER_META_KEY:
                time.sleep(0.05)
            return val

        s.get_meta = slow_get  # type: ignore[assignment]

        results: dict[str, object] = {}

        def pull(name: str):
            barrier.wait()
            results[name] = aw.next_leaf(
                s, runtime=name, owner_user="founder", agent_id=name)

        threads = [threading.Thread(target=pull, args=(n,))
                   for n in ("codex", "gemini")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [n for n, lf in results.items() if lf is not None]
        # exactly ONE thread may win the single leaf — never both (double-claim).
        assert len(winners) == 1, (
            f"double-claim: {winners} both got the one leaf (TOCTOU race)")
        # and the ledger agrees: the leaf is CLAIMED by the single winner.
        led = aw.get_ledger(s, owner_user="founder")
        only = next(iter(led.leaves.values()))
        assert only.state == LeafState.CLAIMED
        assert only.claimed_by == winners[0]
    finally:
        s.close()


def test_concurrent_pulls_on_many_leaves_no_dup_no_loss():
    """Stronger property: N threads pulling from N leaves each get a DISTINCT
    leaf — none claimed twice, none lost. Proves the single-arbiter invariant
    holds under contention, not just for the one-leaf case."""
    s = BrainStore.open(":memory:")
    try:
        n = 12
        aw.add_leaves(s, owner_user="founder",
                      leaves=[{"title": f"leaf-{i}"} for i in range(n)])
        barrier = threading.Barrier(n)
        claimed: list[str] = []
        lock = threading.Lock()

        def pull(name: str):
            barrier.wait()
            leaf = aw.next_leaf(s, runtime=name, owner_user="founder",
                                agent_id=name)
            if leaf is not None:
                with lock:
                    claimed.append(leaf.leaf_id)

        threads = [threading.Thread(target=pull, args=(f"r{i}",))
                   for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # every claim is unique (no leaf handed to two runtimes)...
        assert len(claimed) == len(set(claimed)), "a leaf was double-claimed"
        # ...and all n leaves were claimed (no lost update dropped one).
        assert len(claimed) == n
        st = aw.status(s, owner_user="founder")
        assert st["counts"]["claimed"] == n and st["counts"]["open"] == 0
    finally:
        s.close()


# ─────────────────── durability: corrupt blob must NOT wipe the ledger ───


def test_corrupt_blob_does_not_wipe_ledger_recovers_from_lastgood():
    """Court defect #3 — silent total-ledger loss. A good write leaves a
    last-good copy; a later CORRUPT primary blob must NOT erase every owner's
    work — the loader recovers from last-good and quarantines the bad bytes,
    never silently returns {}."""
    s = BrainStore.open(":memory:")
    try:
        aw.add_leaves(s, owner_user="founder",
                      leaves=[{"title": "precious work"}])
        aw.add_leaves(s, owner_user="teammate",
                      leaves=[{"title": "their work"}])
        # corrupt the PRIMARY ledger blob (simulate a partial/garbled write).
        s.set_meta(aw.LEDGER_META_KEY, '{"founder": {"leaves": {bro')

        # the loader must NOT return {} — it recovers from the last-good copy.
        led = aw.get_ledger(s, owner_user="founder")
        assert led is not None, "ledger was silently wiped on a corrupt read"
        assert any(lf.title == "precious work" for lf in led.leaves.values())
        # the OTHER owner survived too (one bad read can't nuke all owners).
        led2 = aw.get_ledger(s, owner_user="teammate")
        assert led2 is not None and any(
            lf.title == "their work" for lf in led2.leaves.values())

        # the corrupt bytes were quarantined, not discarded.
        corrupt_keys = [k for k in _all_meta_keys(s)
                        if k.startswith(aw.LEDGER_CORRUPT_PREFIX)]
        assert corrupt_keys, "corrupt blob was not quarantined"
    finally:
        s.close()


def test_corrupt_blob_with_no_lastgood_raises_loud_not_silent_wipe():
    """If the blob is corrupt AND there is no recoverable last-good copy, the
    loader RAISES loudly — it must never silently return an empty ledger (the
    'data not persistent' fear). Fail-loud beats silent data loss."""
    s = BrainStore.open(":memory:")
    try:
        # corrupt primary, and NO last-good key written yet.
        s.set_meta(aw.LEDGER_META_KEY, "}{ not json at all")
        with pytest.raises(aw.LedgerCorruptError):
            aw.get_ledger(s, owner_user="founder")
        # and it still quarantined the bad bytes before raising.
        assert any(k.startswith(aw.LEDGER_CORRUPT_PREFIX)
                   for k in _all_meta_keys(s))
    finally:
        s.close()


def _all_meta_keys(store) -> list[str]:
    """Read all brain_meta keys directly (test helper)."""
    with store._lock:  # noqa: SLF001 — test introspection
        rows = store._conn.execute("SELECT key FROM brain_meta").fetchall()
    return [r["key"] for r in rows]


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


def test_work_tools_register_including_assigned_block(store):
    """The brain-driver surface registers additively, INCLUDING the
    daemon-served drive block (brain.work_assigned_block) that wires client_hook
    into the brain-side path (court defect #5 — 'drives no agent')."""
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    names = {t["name"] for t in mcp.list_tools()}
    expected = {
        "brain.work_add", "brain.work_next", "brain.work_claim",
        "brain.work_release", "brain.work_status", "brain.work_get",
        "brain.work_assigned_block",
    }
    assert expected <= names
    # existing handlers untouched (additive only).
    assert {"brain.health", "brain.skill_mint"} <= names


def test_assigned_block_tool_wires_client_hook_and_claims(store):
    """Calling the registered brain.work_assigned_block drives the agent: it
    renders the <assigned_leaf> block AND claims the leaf atomically through the
    SAME store every other tool writes (one ledger). Proves client_hook is wired
    into the brain-side path, not dead code."""
    from personal_brain.server import build_server

    aw.add_leaves(store, owner_user="founder", leaves=[
        {"title": "drive me", "gate_kind": "file_exists",
         "gate_spec": {"path": "y.py"}},
    ])
    mcp = build_server(store=store, default_owner_user="founder")
    # InHouseMCP._tools maps name -> _ToolEntry; .handler is the raw fn.
    handler = mcp._tools["brain.work_assigned_block"].handler
    res = handler(runtime="codex", owner_user="founder")
    assert res["ok"] is True
    assert "<assigned_leaf>" in res["block"] and "drive me" in res["block"]
    assert ch.ASSIGNED_START in res["block"]
    # the SAME ledger now shows the leaf CLAIMED (the brain drove + claimed it).
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["claimed"] == 1 and st["counts"]["open"] == 0


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
