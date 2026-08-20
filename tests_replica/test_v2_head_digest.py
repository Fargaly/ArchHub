"""The head digest costs what a commit changes, and still catches what it must.

v1 signed a fold over every cell in sorted order: ~16-50 s per commit and
again per head at the next open on the founder's 5.27M-cell graph. v2 signs
an additive set accumulator the store moves per commit. These courts hold
v2 to what v1 guaranteed:

* a v2 head verifies, and a single tampered atom in its snapshot fails it;
* heads recorded under v1 still verify next to v2 heads in one chain audit;
* the accumulator a commit leaves equals a from-scratch pass (no drift).
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from nodelang.cell_set_digest import (
    DIGEST_V2_PREFIX, is_v2_digest, set_accumulator,
)
from nodelang.universal_cell import Cell, InvalidCell, Snapshot


def _provision(tmp_path):
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.clean_runtime_bootstrap import provision_clean_runtime
    from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore

    root = tmp_path / "v2-digest-court"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap", b"v2-digest-court" + b"0" * 17,
    )
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = (
        b'[{"key":"court","title":"Court domain","nodes":[{"id":"court_a",'
        b'"cat":"note","title":"Court requirement","sub":"held","status":'
        b'"vision","params":[],"evidence_ref":"","authority_source":"court"}]'
        b',"wires":[],"cross":[]}]'
    )
    return provision_clean_runtime(
        root, provider, caller_keys, caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )


def _recorded_head_digest(authority, snapshot):
    from nodelang.unified_authority import (
        _current_head_member, _decode_value, _single_member,
    )
    head = _current_head_member(authority, snapshot).participant_id
    return _decode_value(
        authority, snapshot,
        _single_member(snapshot, head, authority.role("snapshot-digest")),
    )


def test_a_v2_head_verifies_and_one_tampered_atom_fails_it(tmp_path):
    from nodelang.unified_authority import (
        _HEAD_VERDICT_CACHE, _verify_exact_snapshot_head, declare_definition,
    )
    built = _provision(tmp_path)
    authority = built.location.authority
    try:
        _HEAD_VERDICT_CACHE.clear()
        declare_definition(
            authority, "V2 court", caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        snapshot = authority.store.snapshot()
        recorded = _recorded_head_digest(authority, snapshot)
        assert is_v2_digest(recorded), recorded
        _verify_exact_snapshot_head(authority, snapshot)

        # The accumulator the commit left is exactly a from-scratch pass.
        assert authority.store.set_accumulator(snapshot) == set_accumulator(
            snapshot.cells.values()
        )

        # Tamper one atom of a cell that is not the head record, present
        # the same revision: the digest must not match.
        victim = next(
            cell for cell in snapshot.cells.values()
            if cell.atom and cell.id != "0" * 32
        )
        forged_cells = dict(snapshot.cells)
        forged_cells[victim.id] = Cell(
            victim.id, victim.link0, victim.link1, victim.atom + b"\x00"
        )
        forged = Snapshot(snapshot.revision, forged_cells)
        _HEAD_VERDICT_CACHE.clear()
        with pytest.raises(InvalidCell, match="snapshot digest does not match"):
            _verify_exact_snapshot_head(authority, forged)
    finally:
        _HEAD_VERDICT_CACHE.clear()
        authority.store.close()


def test_v1_heads_still_verify_beside_v2_heads_in_one_chain_audit(tmp_path):
    from nodelang import unified_authority as ua
    built = _provision(tmp_path)
    authority = built.location.authority
    try:
        ua._HEAD_VERDICT_CACHE.clear()
        # One commit signed the old way: the v1 fold over the projected
        # snapshot, exactly as every head on the live graph was recorded.
        real = ua._committed_head_digest

        def v1_digest(auth, base, *, create, replace, blank_atom_roots):
            projected = ua.overlay_read_snapshot(
                base, create=tuple(create), replace=tuple(replace),
            )
            return ua._normalized_snapshot_digest(
                projected, tuple(blank_atom_roots),
            )
        ua._committed_head_digest = v1_digest
        try:
            ua.declare_definition(
                authority, "Old formula", caller=built.caller,
                command_id=str(uuid.uuid4()),
            )
        finally:
            ua._committed_head_digest = real
        old_snapshot = authority.store.snapshot()
        old_recorded = _recorded_head_digest(authority, old_snapshot)
        assert not is_v2_digest(old_recorded) and len(old_recorded) == 64
        # Then one commit the new way, on top of it.
        ua.declare_definition(
            authority, "New formula", caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        new_snapshot = authority.store.snapshot()
        assert is_v2_digest(_recorded_head_digest(authority, new_snapshot))
        # The full audit walks v2 -> v1 -> ... -> bootstrap and passes.
        ua._verify_current_head(authority, new_snapshot, None)
        # And each head verifies on its own under its own formula.
        ua._HEAD_VERDICT_CACHE.clear()
        ua._verify_exact_snapshot_head(authority, new_snapshot)
        ua._verify_exact_snapshot_head(authority, authority.store.at(old_snapshot.revision))
    finally:
        ua._HEAD_VERDICT_CACHE.clear()
        authority.store.close()


def test_the_v2_marker_is_the_value_not_a_new_role():
    """No new head role: the formula rides in the recorded digest string,
    so a graph bootstrapped before v2 signs v2 heads without migration."""
    assert DIGEST_V2_PREFIX == "v2:"
    src = Path(__file__).parents[1].joinpath(
        "nodelang", "unified_authority.py"
    ).read_text(encoding="utf-8")
    assert '"digest-formula"' not in src
    assert "_expected_head_digest(" in src and "_committed_head_digest(" in src


def test_a_recorded_accumulator_is_reused_only_while_the_rows_it_covers_stand(tmp_path):
    """The seed is persisted beside the journal and trusted under the
    same gate as the other proof caches: fence present, same row count and
    newest rowid at or before the revision. A row that claims a revision
    whose version rows differ is ignored; a reopened store then re-hashes
    and still verifies its v2 head."""
    import sqlite3
    from nodelang.universal_cell import CellStore, Cell, NULL_CELL_ID
    from nodelang.cell_set_digest import SET_HASH_BYTES

    database = tmp_path / "acc.sqlite3"
    store = CellStore(str(database))
    ids = [NULL_CELL_ID]
    for step in range(5):
        cells = [Cell("c%d-%d" % (step, k), ids[-1], NULL_CELL_ID, b"x") for k in range(3)]
        store.commit(store.revision, create=cells)
        ids.extend(c.id for c in cells)
    head = store.snapshot()
    truth = store.set_accumulator(head)  # full pass, then recorded
    store.close()

    sidecar = str(database) + ".accelerators"
    with sqlite3.connect(sidecar) as raw:
        rows = raw.execute("SELECT revision, rows, newest FROM set_accumulators").fetchall()
    assert rows, "the full pass must leave its accumulator beside the journal"
    assert head.revision in {r[0] for r in rows}

    # Reopened: the recorded row is reused (no full pass) -- prove by
    # poisoning it and seeing the poison come back, exactly as the
    # checkpoint courts do.
    with sqlite3.connect(sidecar) as raw:
        raw.execute(
            "UPDATE set_accumulators SET accumulator=? WHERE revision=?",
            ((truth + 1).to_bytes(SET_HASH_BYTES, "big"), head.revision),
        )
    reopened = CellStore(str(database))
    assert reopened.set_accumulator(reopened.snapshot()) == truth + 1
    reopened.close()

    # A row whose covered-row count no longer matches is refused and the
    # store re-hashes for real.
    with sqlite3.connect(sidecar) as raw:
        raw.execute("UPDATE set_accumulators SET rows = rows + 1 WHERE revision=?", (head.revision,))
    honest = CellStore(str(database))
    assert honest.set_accumulator(honest.snapshot()) == truth
    honest.close()
