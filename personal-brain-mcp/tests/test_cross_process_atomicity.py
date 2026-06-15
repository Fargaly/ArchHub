"""CROSS-PROCESS atomicity of the active-work claim (court latent defect).

Defect 4's test (`test_next_leaf_is_atomic_under_real_concurrency`) proves the
claim is atomic across THREADS in ONE process — the `threading.RLock` inside
`BrainStore.update_meta` serialises them. But that lock gives ZERO protection
across PROCESSES: two daemons (or a daemon + an in-process hook) each hold their
own connection and their own RLock. On the autocommit SQLite path
(`isolation_level=None`, no `BEGIN IMMEDIATE`), the `SELECT` inside update_meta
does not hold any database lock, so process A and process B can BOTH read
state='open' and BOTH write the claim → the SAME leaf is double-claimed across
processes (the court reproduced 5/12 natural, 8/8 forced).

This test fires N SEPARATE OS PROCESSES (real `subprocess.Popen`, each its own
interpreter → own connection → own RLock) that all claim from ONE on-disk
brain.db behind a file-system barrier, and asserts:

  * NO leaf id is claimed by two different processes (no cross-process
    double-claim), and
  * every successful claim is distinct and the ledger's claimed-count matches.

On the un-fixed code this FAILS (a leaf id appears for two agents). After the
fix — wrapping the read-decide-write in `BEGIN IMMEDIATE … COMMIT` (a RESERVED
lock that serialises the critical section across connections) plus a
`busy_timeout` so a contending process waits instead of erroring — exactly one
process wins each leaf.

Runs under pytest AND standalone:
  python personal-brain-mcp/tests/test_cross_process_atomicity.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_WORKER = Path(__file__).resolve().parent / "_claim_worker.py"

import pytest  # noqa: E402

from personal_brain import active_work as aw  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


def _spawn_claimers(brain_db: Path, owner: str, agents: list[str],
                    barrier: Path) -> list[dict]:
    """Launch one OS process per agent, all blocked on the file barrier, then
    collect each worker's {"agent","leaf"} result. SEPARATE processes = separate
    sqlite connections = separate RLocks (the in-process lock cannot help)."""
    n = len(agents)
    procs = []
    for a in agents:
        p = subprocess.Popen(
            [sys.executable, str(_WORKER), str(brain_db), owner, a,
             str(barrier), str(n)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        procs.append((a, p))

    results: list[dict] = []
    for a, p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, f"worker {a} failed rc={p.returncode}: {err}"
        line = (out or "").strip()
        assert line, f"worker {a} produced no result; stderr={err!r}"
        results.append(json.loads(line))
    return results


def _assert_no_cross_process_double_claim(results: list[dict], *,
                                          n_leaves: int) -> list[str]:
    """Core invariant: among the claimed (non-null) leaf ids, NONE is claimed by
    two processes, and no more leaves were handed out than exist. Returns the
    list of claimed ids."""
    claimed = [r["leaf"] for r in results if r.get("leaf")]
    # the killer assertion: a leaf handed to two processes is a double-claim.
    assert len(claimed) == len(set(claimed)), (
        f"cross-process DOUBLE-CLAIM: {claimed} — a leaf was claimed by two "
        f"separate processes (BEGIN IMMEDIATE missing / CAS wrong)")
    assert len(claimed) <= n_leaves, (
        f"more claims ({len(claimed)}) than leaves ({n_leaves}) — impossible "
        f"without a lost-update race")
    return claimed


# ───────────────── the one-leaf killer (two processes, one leaf) ─────────


@pytest.mark.parametrize("round_no", range(4))
def test_two_processes_one_leaf_exactly_one_winner(round_no):
    """Two SEPARATE processes race for ONE leaf behind a barrier. Exactly one
    may win — never both. Several rounds because a cross-process race is
    probabilistic; the barrier makes them fire together."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        owner = "founder"
        barrier = root / f"barrier_{round_no}.txt"

        s = BrainStore.open(brain_db)
        aw.add_leaves(s, owner_user=owner, leaves=[{"title": "only one"}])
        s.close()

        results = _spawn_claimers(brain_db, owner, ["procA", "procB"], barrier)
        claimed = _assert_no_cross_process_double_claim(results, n_leaves=1)
        assert len(claimed) == 1, (
            f"exactly one process must win the single leaf; got {results!r}")

        # the on-disk ledger agrees: the leaf is CLAIMED by the single winner.
        s2 = BrainStore.open(brain_db)
        try:
            led = aw.get_ledger(s2, owner_user=owner)
            only = next(iter(led.leaves.values()))
            assert only.state.value == "claimed"
            winner = next(r["agent"] for r in results if r.get("leaf"))
            assert only.claimed_by == winner
        finally:
            s2.close()


# ───────────────── the N-on-N property (no dup, no loss) ─────────────────


def test_many_processes_many_leaves_no_dup_no_loss():
    """N separate processes pull from N leaves; each must get a DISTINCT leaf —
    none claimed twice across processes, none lost. The cross-process analogue
    of the in-thread `test_concurrent_pulls_on_many_leaves_no_dup_no_loss`."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        owner = "founder"
        barrier = root / "barrier_many.txt"
        n = 8

        s = BrainStore.open(brain_db)
        aw.add_leaves(s, owner_user=owner,
                      leaves=[{"title": f"leaf-{i}"} for i in range(n)])
        s.close()

        agents = [f"proc{i}" for i in range(n)]
        results = _spawn_claimers(brain_db, owner, agents, barrier)
        claimed = _assert_no_cross_process_double_claim(results, n_leaves=n)
        # with N processes and N leaves, every leaf is claimed exactly once.
        assert len(claimed) == n, (
            f"expected all {n} leaves claimed across processes, got "
            f"{len(claimed)}: {results!r}")

        s2 = BrainStore.open(brain_db)
        try:
            st = aw.status(s2, owner_user=owner)
            assert st["counts"]["claimed"] == n and st["counts"]["open"] == 0
        finally:
            s2.close()


# ───────────────── BEGIN IMMEDIATE wraps the claim (white-box) ───────────


def test_update_meta_uses_begin_immediate_for_cross_process_serialization():
    """White-box proof the fix is the RIGHT one: BrainStore.update_meta wraps its
    read-decide-write in a BEGIN IMMEDIATE … COMMIT transaction so the critical
    section holds a RESERVED database lock for the whole get→decide→set — the
    only thing that serialises it across separate connections/processes on the
    autocommit path. We assert the transaction actually opened (the connection
    reports it is inside a transaction at decide time) and a busy_timeout is set
    so a contending process waits rather than erroring 'database is locked'."""
    with tempfile.TemporaryDirectory() as d:
        s = BrainStore.open(Path(d) / "brain.db")
        try:
            seen = {}

            def fn(old):
                # at decide time we must be INSIDE a write transaction (the
                # RESERVED lock is held) — not in autocommit.
                seen["in_txn"] = bool(s._conn.in_transaction)
                return "v1", "ok"

            assert s.update_meta("k", fn) == "ok"
            assert seen.get("in_txn") is True, (
                "update_meta must run its critical section inside a BEGIN "
                "IMMEDIATE transaction (RESERVED lock) — autocommit gives no "
                "cross-process serialization")
            # the value still persisted (COMMIT happened).
            assert s.get_meta("k") == "v1"
            # busy_timeout is set so a contending connection WAITS for the lock.
            bt = s._conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert int(bt) > 0, "busy_timeout must be set so claims wait, not error"
        finally:
            s.close()


# ───────────────────── standalone runner (no pytest) ─────────────────────


def _run_standalone() -> int:
    failed = 0
    cases = [
        ("two_processes_one_leaf_round0",
         lambda: test_two_processes_one_leaf_exactly_one_winner(0)),
        ("two_processes_one_leaf_round1",
         lambda: test_two_processes_one_leaf_exactly_one_winner(1)),
        ("many_processes_many_leaves_no_dup_no_loss",
         test_many_processes_many_leaves_no_dup_no_loss),
        ("update_meta_uses_begin_immediate",
         test_update_meta_uses_begin_immediate_for_cross_process_serialization),
    ]
    for name, fn in cases:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(cases) - failed}/{len(cases)} passed (standalone)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
