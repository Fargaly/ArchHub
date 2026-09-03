"""_claim_worker.py — a ONE-SHOT cross-process claim worker for the
cross-process atomicity test (court latent defect — BrainStore.update_meta is
in-process-locked but NOT process-safe on the autocommit SQLite path).

Each invocation is a SEPARATE OS process with its OWN sqlite connection + its
OWN threading.RLock (so the in-process lock gives ZERO cross-process
protection). It:

  1. opens the SAME on-disk brain.db given on argv,
  2. waits on a file-system barrier (a sentinel file) so N workers fire their
     read-modify-write as close to simultaneously as the OS allows,
  3. calls active_work.next_leaf ONCE (the read-decide-write claim),
  4. prints ONE json line: {"agent": <id>, "leaf": <leaf_id or null>}.

The orchestrating test reads every worker's line and asserts NO leaf id was
claimed by two different workers (no cross-process double-claim) and none was
lost. On the un-fixed autocommit code two workers both SELECT state='open' and
both UPDATE → the same leaf id appears twice (or a claim is lost to
last-writer-wins).

Usage:
    python _claim_worker.py <brain_db> <owner> <agent_id> <barrier_file> <n>
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

from personal_brain import active_work as aw  # noqa: E402
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
    brain_db, owner, agent_id, barrier_file, n = (
        sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), int(sys.argv[5]))

    store = BrainStore.open(brain_db)
    try:
        _barrier(barrier_file, n, agent_id)
        leaf = aw.next_leaf(store, runtime=agent_id, owner_user=owner,
                            agent_id=agent_id)
        sys.stdout.write(json.dumps({
            "agent": agent_id,
            "leaf": (leaf.leaf_id if leaf is not None else None),
        }))
        sys.stdout.flush()
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
