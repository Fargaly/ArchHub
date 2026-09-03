"""CROSS-PROCESS atomicity of the requirement_tree leaf-claim (court defect #5
sibling — the ROMA parallel-executor claim, exposed as MCP tool brain.roma_claim
and driven by roma.run_to_dry).

`test_roma.py` proves claim_leaf's in-process API (refuses non-leaf, refuses a
claim by a DIFFERENT agent, idempotent re-claim by the same agent). But those
run in ONE process. The court's latent defect: `TreeStore` did
``get_meta`` → decide → ``set_meta`` as TWO SEPARATE lock acquisitions. The
RLock inside each acquisition gives ZERO protection across PROCESSES — two
daemons (or a daemon + an in-process hook) each hold their own connection + RLock.
On the autocommit SQLite path (`isolation_level=None`, no `BEGIN IMMEDIATE`) the
SELECT in the load holds no database lock, so process A and process B can BOTH
read state='open' and BOTH write the claim → the SAME tree leaf is double-claimed
across processes (the court reproduced 8/8 forced).

This test fires N SEPARATE OS PROCESSES (real `subprocess.Popen`, each its own
interpreter → own connection → own RLock) that all claim ONE requirement_tree
leaf from ONE on-disk brain.db behind a file-system barrier, and asserts EXACTLY
ONE process wins the leaf (the rest get the typed already-claimed refusal → null).

On the un-fixed branch HEAD (49cc9e9) this FAILS (a node_id is returned by two
processes — the double-claim). After the fix — routing claim_leaf's read-decide-
write through `TreeStore.mutate_tree` → `BrainStore.update_meta`'s
`BEGIN IMMEDIATE … COMMIT` critical section (the SAME cross-process CAS the
active-work ledger already uses) — exactly one process wins each leaf.

Runs under pytest AND standalone:
  python personal-brain-mcp/tests/test_tree_cross_process_atomicity.py
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

import pytest  # noqa: E402

from personal_brain import requirement_tree as rt  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402

_WORKER = Path(__file__).resolve().parent / "_tree_claim_worker.py"


def _seed_one_leaf(brain_db: Path, owner: str = "founder") -> tuple[str, str]:
    """Create a tree with a single machine-checkable LEAF and return
    (tree_id, leaf_node_id). The leaf is OPEN and claimable."""
    s = BrainStore.open(brain_db)
    try:
        tree = rt.create_root(s, title="cross-proc vision", owner_user=owner)
        rt.decompose(s, tree_id=tree.tree_id, node_id=tree.root_id,
                     children=[{"title": "only leaf", "gate_kind": "manual"}])
        leaf = rt.get_tree(s, tree_id=tree.tree_id).leaves()[0]
        return tree.tree_id, leaf.node_id
    finally:
        s.close()


def _spawn_claimers(brain_db: Path, tree_id: str, node_id: str,
                    agents: list[str], barrier: Path) -> list[dict]:
    """Launch one OS process per agent, all blocked on the file barrier, then
    collect each worker's {"agent","leaf"} result. SEPARATE processes = separate
    sqlite connections = separate RLocks (the in-process lock cannot help)."""
    n = len(agents)
    procs = []
    for a in agents:
        p = subprocess.Popen(
            [sys.executable, str(_WORKER), str(brain_db), tree_id, node_id, a,
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


def _assert_exactly_one_winner(results: list[dict], *, node_id: str) -> str:
    """Core invariant: among the claimed (non-null) leaf ids, NONE is claimed by
    two processes, every reported id is THE contested leaf, and exactly one
    process won. Returns the winning agent id."""
    claimed = [r["leaf"] for r in results if r.get("leaf")]
    # the killer assertion: the SAME leaf handed to two processes is a
    # cross-process double-claim (BEGIN IMMEDIATE missing / CAS wrong).
    assert len(claimed) == len(set(claimed)), (
        f"cross-process DOUBLE-CLAIM of requirement_tree leaf: {claimed} — a "
        f"leaf was claimed by two separate processes")
    assert all(c == node_id for c in claimed), (
        f"a worker reported a DIFFERENT node than the contested leaf: {claimed}")
    assert len(claimed) == 1, (
        f"exactly one process must win the single tree leaf; got {results!r}")
    return next(r["agent"] for r in results if r.get("leaf"))


# ───────────────── two processes, one leaf (probabilistic rounds) ─────────


@pytest.mark.parametrize("round_no", range(4))
def test_two_processes_one_tree_leaf_exactly_one_winner(round_no):
    """Two SEPARATE processes race for ONE requirement_tree leaf behind a
    barrier. Exactly one may win — never both. Several rounds because a
    cross-process race is probabilistic; the barrier makes them fire together."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        barrier = root / f"barrier_{round_no}.txt"

        tree_id, node_id = _seed_one_leaf(brain_db)
        results = _spawn_claimers(
            brain_db, tree_id, node_id, ["execA", "execB"], barrier)
        winner = _assert_exactly_one_winner(results, node_id=node_id)

        # the on-disk tree agrees: the leaf is CLAIMED by the single winner.
        s2 = BrainStore.open(brain_db)
        try:
            tree = rt.get_tree(s2, tree_id=tree_id)
            leaf = tree.nodes[node_id]
            assert leaf.state == rt.NodeState.CLAIMED
            assert leaf.claimed_by == winner
        finally:
            s2.close()


# ───────────────── the 8-on-1 killer (8/8 forced double-claim repro) ──────


def test_eight_processes_one_tree_leaf_exactly_one_winner():
    """EIGHT separate processes all claim the SAME one leaf — the direct
    analogue of the court's '8/8 forced double-claim'. Exactly one wins; the
    other seven get the typed already-claimed refusal (→ null). On the un-fixed
    two-lock TreeStore several of the eight all read OPEN and all write the
    claim (the same node_id comes back more than once)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        brain_db = root / "brain.db"
        barrier = root / "barrier_8.txt"

        tree_id, node_id = _seed_one_leaf(brain_db)
        agents = [f"exec{i}" for i in range(8)]
        results = _spawn_claimers(brain_db, tree_id, node_id, agents, barrier)
        winner = _assert_exactly_one_winner(results, node_id=node_id)

        s2 = BrainStore.open(brain_db)
        try:
            leaf = rt.get_tree(s2, tree_id=tree_id).nodes[node_id]
            assert leaf.state == rt.NodeState.CLAIMED and leaf.claimed_by == winner
        finally:
            s2.close()


# ───────────────── BEGIN IMMEDIATE wraps the tree claim (white-box) ───────


def test_tree_claim_runs_inside_begin_immediate_transaction():
    """White-box proof the tree claim is routed through the SAME serialised
    critical section as the active-work ledger: claim_leaf's read-decide-write
    runs inside BrainStore.update_meta's BEGIN IMMEDIATE transaction (RESERVED
    lock). We monkeypatch update_meta to record whether the connection reports
    it is inside a transaction at decide time — the only thing that serialises
    the get→decide→set across separate connections/processes."""
    with tempfile.TemporaryDirectory() as d:
        s = BrainStore.open(Path(d) / "brain.db")
        try:
            tree = rt.create_root(s, title="wb", owner_user="founder")
            rt.decompose(s, tree_id=tree.tree_id, node_id=tree.root_id,
                         children=[{"title": "leaf", "gate_kind": "manual"}])
            node_id = rt.get_tree(s, tree_id=tree.tree_id).leaves()[0].node_id

            seen = {}
            real_update_meta = s.update_meta

            def _spy(key, fn):
                def _wrapped(old):
                    # at decide time we must be INSIDE a write transaction.
                    seen["in_txn"] = bool(s._conn.in_transaction)
                    seen["key"] = key
                    return fn(old)
                return real_update_meta(key, _wrapped)

            s.update_meta = _spy  # type: ignore[assignment]
            rt.claim_leaf(s, tree_id=tree.tree_id, node_id=node_id, agent_id="ex")
            s.update_meta = real_update_meta  # type: ignore[assignment]

            assert seen.get("key") == rt.TREE_META_KEY, (
                "claim_leaf must route through update_meta on the tree key")
            assert seen.get("in_txn") is True, (
                "claim_leaf's critical section must run inside a BEGIN IMMEDIATE "
                "transaction (RESERVED lock) — autocommit gives no cross-process "
                "serialization, so two processes could both claim the leaf")
            # and the claim actually landed.
            leaf = rt.get_tree(s, tree_id=tree.tree_id).nodes[node_id]
            assert leaf.state == rt.NodeState.CLAIMED and leaf.claimed_by == "ex"
        finally:
            s.close()


# ───────────────────── standalone runner (no pytest) ─────────────────────


def _run_standalone() -> int:
    failed = 0
    cases = [
        ("two_processes_one_leaf_round0",
         lambda: test_two_processes_one_tree_leaf_exactly_one_winner(0)),
        ("two_processes_one_leaf_round1",
         lambda: test_two_processes_one_tree_leaf_exactly_one_winner(1)),
        ("eight_processes_one_leaf_exactly_one_winner",
         test_eight_processes_one_tree_leaf_exactly_one_winner),
        ("tree_claim_runs_inside_begin_immediate",
         test_tree_claim_runs_inside_begin_immediate_transaction),
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
