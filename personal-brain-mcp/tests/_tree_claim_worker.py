"""_tree_claim_worker.py — a ONE-SHOT cross-process claim worker for the
requirement_tree leaf-claim atomicity test (court latent defect — TreeStore did
``get_meta`` → decide → ``set_meta`` as TWO separate lock acquisitions, so the
get→decide→set was NOT cross-process safe on the autocommit SQLite path).

Each invocation is a SEPARATE OS process with its OWN sqlite connection + its
OWN threading.RLock (so the in-process lock gives ZERO cross-process
protection). It:

  1. opens the SAME on-disk brain.db given on argv,
  2. waits on a file-system barrier (a sentinel file) so N workers fire their
     read-modify-write as close to simultaneously as the OS allows,
  3. calls requirement_tree.claim_leaf ONCE on the target leaf (the
     read-decide-write CAS),
  4. prints ONE json line: {"agent": <id>, "leaf": <node_id or null>}.

A worker that WINS the leaf returns its node_id; a worker that LOSES gets the
typed already-claimed-by-another refusal (ValueError) and returns null. The
orchestrating test asserts NO node_id was returned by two different workers
(no cross-process double-claim). On the un-fixed two-lock code two workers both
read state=open and both wrote the claim → the SAME node_id appears twice.

Usage:
    python _tree_claim_worker.py <brain_db> <tree_id> <node_id> <agent_id> <barrier_file> <n>
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from personal_brain import requirement_tree as rt  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


def _barrier(barrier_file: Path, n: int, agent_id: str) -> None:
    """Crude cross-process barrier: each worker appends its id to the sentinel
    file, then spins until the file lists >= n lines. Keeps all workers parked
    until the last one arrives so their claims race as tightly as possible."""
    with barrier_file.open("a", encoding="utf-8") as fh:
        fh.write(agent_id + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    deadline = time.time() + 30.0
    while time.time() < deadline:
        try:
            lines = [x for x in barrier_file.read_text(
                encoding="utf-8").splitlines() if x.strip()]
        except Exception:
            lines = []
        if len(lines) >= n:
            return
        time.sleep(0.002)


def main() -> int:
    brain_db, tree_id, node_id, agent_id, barrier_file, n = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
        Path(sys.argv[5]), int(sys.argv[6]))

    store = BrainStore.open(brain_db)
    try:
        _barrier(barrier_file, n, agent_id)
        won: str | None = None
        try:
            node = rt.claim_leaf(store, tree_id=tree_id, node_id=node_id,
                                 agent_id=agent_id)
            # Only count it as OURS if WE are the recorded claimer. (claim_leaf
            # is idempotent for the same agent; the loser raises instead.)
            if node is not None and node.claimed_by == agent_id:
                won = node.node_id
        except ValueError:
            # already claimed by another process → we lost the CAS. Honest null.
            won = None
        sys.stdout.write(json.dumps({"agent": agent_id, "leaf": won}))
        sys.stdout.flush()
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
