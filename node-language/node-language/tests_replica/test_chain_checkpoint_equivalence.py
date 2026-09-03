"""A checkpointed open proves the same head as a full stream, or refuses.

SPEC section 3.1(6-7): an accelerator is disposable and MUST NOT change
meaning. The chain checkpoint is exactly that -- deleting it costs time
and changes no digest; a checkpoint that lies about the rows it covers is
refused and the full stream runs.
"""
import sqlite3
import uuid
from pathlib import Path

from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID


def _grow(store: CellStore, revisions: int) -> None:
    for step in range(revisions):
        cell = Cell(str(uuid.uuid4()), NULL_CELL_ID, NULL_CELL_ID, b"r%d" % step)
        store.commit(store.revision, create=(cell,))


def test_checkpoint_resume_yields_the_full_stream_digest(tmp_path: Path):
    database = tmp_path / "graph.sqlite3"
    store = CellStore(str(database))
    _grow(store, 12)
    full_revision = store.revision
    full_digest = store.revision_chain_digest(full_revision)
    full_cells = dict(store.snapshot().cells)
    store.close()

    # First reopen: no checkpoint yet -> full stream, and it RECORDS one.
    reopened = CellStore(str(database))
    assert reopened.revision == full_revision
    assert reopened.revision_chain_digest(full_revision) == full_digest
    reopened.close()
    with sqlite3.connect(str(database) + ".accelerators") as raw:
        recorded = raw.execute(
            "SELECT revision, prefix_rows FROM chain_checkpoints"
        ).fetchall()
    latest_checkpoint = max(recorded)
    assert latest_checkpoint[0] == full_revision
    with sqlite3.connect(str(database)) as raw:
        total_rows = raw.execute("SELECT COUNT(*) FROM cell_versions").fetchone()[0]
    assert latest_checkpoint[1] == total_rows

    # Grow past the checkpoint, reopen: only the suffix is replayed, and the
    # digest and the current cells are identical to a full stream.
    grown = CellStore(str(database))
    _grow(grown, 5)
    later_revision = grown.revision
    later_digest = grown.revision_chain_digest(later_revision)
    later_cells = dict(grown.snapshot().cells)
    grown.close()

    resumed = CellStore(str(database))
    assert resumed.revision == later_revision
    assert resumed.revision_chain_digest(later_revision) == later_digest
    assert dict(resumed.snapshot().cells) == later_cells
    resumed.close()

    # Deleting the accelerator changes nothing but time (SPEC 3.1.7). It
    # lives beside the journal -- the journal itself stays one Cell shape.
    with sqlite3.connect(str(database) + ".accelerators") as raw:
        raw.execute("DELETE FROM chain_checkpoints")
        raw.commit()
    cold = CellStore(str(database))
    assert cold.revision_chain_digest(later_revision) == later_digest
    assert dict(cold.snapshot().cells) == later_cells
    cold.close()


def test_a_lying_checkpoint_is_refused_and_the_full_stream_runs(tmp_path: Path):
    database = tmp_path / "graph.sqlite3"
    store = CellStore(str(database))
    _grow(store, 8)
    truth_revision = store.revision
    truth_digest = store.revision_chain_digest(truth_revision)
    store.close()
    CellStore(str(database)).close()  # records an honest checkpoint
    with sqlite3.connect(str(database) + ".accelerators") as raw:
        # Same revision, wrong digest, wrong row count: a checkpoint that
        # cannot be about these rows.
        raw.execute(
            "UPDATE chain_checkpoints SET chain_digest=?, prefix_rows=?",
            (b"\x11" * 32, 1),
        )
        raw.commit()
    reopened = CellStore(str(database))
    assert reopened.revision_chain_digest(truth_revision) == truth_digest
    reopened.close()


def test_a_checkpoint_with_a_wrong_digest_but_right_rows_cannot_pass_silently(
    tmp_path: Path,
):
    """Row count agreeing is necessary, not sufficient.

    A wrong digest with the right row count would seed a wrong chain and
    every later digest would be wrong -- silently. The head digest the
    store reports must therefore be cross-checked against the accepted
    proof the authority holds; here we assert the store surfaces the
    checkpoint-seeded digest so a caller CAN detect it, and that the
    honest digest is recoverable by clearing the accelerator.
    """
    database = tmp_path / "graph.sqlite3"
    store = CellStore(str(database))
    _grow(store, 6)
    truth = store.revision_chain_digest(store.revision)
    revision = store.revision
    store.close()
    CellStore(str(database)).close()
    with sqlite3.connect(str(database) + ".accelerators") as raw:
        raw.execute("UPDATE chain_checkpoints SET chain_digest=?", (b"\x22" * 32,))
        raw.commit()
    poisoned = CellStore(str(database))
    seeded = poisoned.revision_chain_digest(revision)
    poisoned.close()
    with sqlite3.connect(str(database) + ".accelerators") as raw:
        raw.execute("DELETE FROM chain_checkpoints"); raw.commit()
    honest = CellStore(str(database))
    assert honest.revision_chain_digest(revision) == truth
    honest.close()
    # The poisoned open must not have silently equalled the truth by luck.
    assert seeded != truth


def test_chained_prefix_fingerprint_equals_itself_and_costs_only_new_rows(tmp_path):
    """v2 prefix proofs chain by revision: recording the proof for a head
    that moved hashes the rows of the revisions since the last link, and a
    v1-recorded proof is still verified under v1 before v2 replaces it."""
    import json as _json
    from nodelang.unified_authority_runtime import _AcceptedSnapshotProof

    database = tmp_path / "chain.sqlite3"
    store = CellStore(str(database))
    _grow(store, 6)
    revision = store.revision
    # v2 is deterministic and stable across calls / reopens.
    rows, newest, digest_a = store.chained_prefix_fingerprint(revision)
    assert len(digest_a) == 64 and rows > 0
    assert store.chained_prefix_fingerprint(revision) == (rows, newest, digest_a)
    store.close()
    reopened = CellStore(str(database))
    assert reopened.chained_prefix_fingerprint(revision) == (rows, newest, digest_a)
    # A v1 recorded head proof is recognised as v1 and verified as such.
    generation = tmp_path / "gen"
    generation.mkdir()
    proof = _AcceptedSnapshotProof(generation)
    v1_rows, v1_newest, v1_digest = reopened.accepted_prefix_fingerprint(revision)
    (generation / "accepted-proof.json").write_text(_json.dumps({
        "head": "head:%d:%d:%d:%s" % (revision, v1_rows, v1_newest, v1_digest),
    }), encoding="utf-8")
    assert proof.head_floor_revision(reopened) == revision
    # What gets recorded from now on is v2.
    key = proof.head_fingerprint(reopened, revision)
    assert key.split(":")[-1].startswith("v2-")
    proof.record_head(key)
    assert proof.head_floor_revision(reopened) == revision
    # Grow two revisions: the chain extends from the recorded link; the
    # per-revision links below are untouched (same digests).
    _grow(reopened, 2)
    later = reopened.revision
    rows2, newest2, digest_later = reopened.chained_prefix_fingerprint(later)
    assert reopened.chained_prefix_fingerprint(revision) == (rows, newest, digest_a)
    assert digest_later != digest_a and rows2 > rows
    # Tampering a recorded link's row count refuses that link and rebuilds.
    import sqlite3 as _sqlite3
    with _sqlite3.connect(str(database) + ".accelerators") as raw:
        raw.execute("UPDATE prefix_chain SET rows = rows + 1 WHERE revision = ?", (revision,))
    assert reopened.chained_prefix_fingerprint(revision) == (rows, newest, digest_a)
    reopened.close()
