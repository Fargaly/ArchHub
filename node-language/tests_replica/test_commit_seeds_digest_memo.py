"""A signed commit hands its own digest to the verify path.

The digest a head signs is computed over exactly the cells the commit
publishes. Recomputing it on the next authenticated request re-hashes
every cell in the graph -- measured at ~50s per governed command on the
live 5.26M-cell graph, which is what made every canvas gesture cost close
to a minute. These courts hold the seeding to its two honesty bounds:
the memo carries the committed mapping itself (never an id alone), and
verification still runs its structural and signature checks for real.
"""
from pathlib import Path

SOURCE = Path(
    r"C:\Users\fargaly\00.ARCHUB\10.PRODUCT\13.NODE-LANGUAGE"
    r"\nodelang\unified_authority.py"
).read_text(encoding="utf-8")


def test_the_commit_seeds_the_digest_it_just_computed():
    assert "_SNAPSHOT_DIGEST_CACHE[key] = (committed.cells, normalized_digest)" \
        in SOURCE


def test_the_memo_is_keyed_by_the_committed_mapping_not_a_bare_id():
    """An id is stable while its object lives, not unique across time."""
    seeding = SOURCE[SOURCE.index("committed = authority.store.snapshot()"):]
    seeding = seeding[:seeding.index("return committed_revision")]
    assert "id(committed.cells)" in seeding
    assert "(committed.cells, normalized_digest)" in seeding


def test_the_seed_is_guarded_by_the_expected_revision():
    """A concurrent writer between commit and snapshot() must not be
    answered for: the seed only lands when the snapshot is the exact
    revision this commit produced."""
    seeding = SOURCE[SOURCE.index("committed = authority.store.snapshot()"):]
    seeding = seeding[:seeding.index("return committed_revision")]
    assert "if committed.revision == revision:" in seeding


def test_head_verification_itself_is_not_seeded():
    """Only the hash is memoized. The verdict cache stays earned: shape,
    payload and signature checks run for real on first verification."""
    seeding = SOURCE[SOURCE.index("committed = authority.store.snapshot()"):]
    seeding = seeding[:seeding.index("return committed_revision")]
    assert "_HEAD_VERDICT_CACHE" not in seeding


def test_functional_round_trip_verify_hits_the_seeded_digest(tmp_path):
    """On a real provisioned runtime: commit, then verify the head with the
    digest memo poisoned to a wrong value. If verification recomputed, the
    poison would be ignored and it would pass; it refusing proves the
    verify path consumed the digest the commit seeded."""
    import hashlib
    import uuid
    from pathlib import Path

    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.clean_runtime_bootstrap import provision_clean_runtime
    from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
    from nodelang.unified_authority import (
        _HEAD_VERDICT_CACHE,
        _SNAPSHOT_DIGEST_CACHE,
        _verify_exact_snapshot_head,
        declare_definition,
    )
    from nodelang.universal_cell import InvalidCell

    root = tmp_path / "digest-memo-court"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap", b"digest-memo-court" + b"0" * 16,
    )
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = (
        b'[{"key":"court","title":"Court domain","nodes":[{"id":"court_a",'
        b'"cat":"note","title":"Court requirement","sub":"held","status":'
        b'"vision","params":[],"evidence_ref":"","authority_source":"court"}]'
        b',"wires":[],"cross":[]}]'
    )
    built = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    authority = built.location.authority
    try:
        _SNAPSHOT_DIGEST_CACHE.clear()
        _HEAD_VERDICT_CACHE.clear()
        declare_definition(
            authority, "Seed court", caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        snapshot = authority.store.snapshot()
        seeded = [
            key for key, (cells, _) in _SNAPSHOT_DIGEST_CACHE.items()
            if cells is snapshot.cells and key[1] == snapshot.revision
        ]
        assert seeded, "commit did not seed the digest for its own snapshot"
        # A head signed since the v2 formula verifies from the store's set
        # accumulator, moved by each commit -- never a whole-graph pass. So
        # the seed that must be consumed is one level down: poison the
        # accumulator the commit left for its own revision. A verifier
        # that re-hashed the graph would ignore the poison and pass; one
        # that reads what the commit left refuses.
        held = authority.store._set_accumulators
        assert snapshot.revision in held, (
            "commit did not leave the accumulator for its own revision"
        )
        held[snapshot.revision] = (held[snapshot.revision] + 1) % (1 << 2048)
        try:
            _verify_exact_snapshot_head(authority, snapshot)
        except InvalidCell:
            poisoned_refused = True
        else:
            poisoned_refused = False
        assert poisoned_refused, (
            "verification re-hashed the graph instead of reading what the "
            "commit left"
        )
    finally:
        _SNAPSHOT_DIGEST_CACHE.clear()
        _HEAD_VERDICT_CACHE.clear()
        authority.store.close()
