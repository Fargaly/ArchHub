"""SLICE C — learning must be CONSUMED, not just recorded.

Forensic-audit defects this file gates (2026-07-02 audit, each reproduced):

  1. SKILLS NEVER COUNTED — `make_context_payload` touched facts only; no
     skill-usage incrementer existed anywhere, so the federation sharing
     gate (`derive_skill_usage_patterns`, success_count >= 3) was
     unsatisfiable by construction. Gate: returning a skill in the payload
     increments its success_count ROW (real sqlite store), and 3 touches
     make the skill shareable.

  2. SYNC WIPES REINFORCEMENT — `_fragment_to_wire` omitted success_count /
     fail_count / last_used_at and the apply path upserted with excluded.*,
     zeroing local counters. Gate: the wire dict carries the three fields;
     apply merges max(local, remote) and never lowers local evidence.
     Mirrored for skills (personal_cloud_sync + sync_worker paths).

  3. LOOP FACTS UNRETRIEVABLE — self_extend:: facts (exact-token ids) never
     surfaced in brain.context. Gate: with ARCHHUB_HYBRID_RECALL default ON,
     an exact-code query surfaces the self_extend fact past 10 harvest
     decoys; with the env set to '0' the behavior equals pure dense
     (hybrid_alpha=1.0) exactly — and the fact is buried again, proving the
     lane (not luck) did the work.

Every assertion is against real values (sqlite rows, ranked id lists); a
stub that no-ops the incrementer, drops the wire fields, or skips the
hybrid lane fails these tests.

Run: cd personal-brain-mcp && PYTHONPATH=src python -m pytest tests/test_learning_consumed.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain import personal_cloud_sync as P
from personal_brain.federation import derive_skill_usage_patterns
from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Skill,
    Visibility,
)
from personal_brain.retrieval import retrieve_facts
from personal_brain.server import make_context_payload
from personal_brain.storage import BrainStore

OWNER = "u_learn"


def _prov() -> Provenance:
    return Provenance(
        contributing_agent="test",
        contributing_user=OWNER,
        created_at=datetime.now(timezone.utc),
    )


def _fact(fid: str, text: str, subject: str | None = None) -> Fragment:
    return Fragment(
        id=fid, kind=FragmentKind.FACT, text=text, subject=subject,
        scope=Scope.USER, visibility=Visibility.PRIVATE, owner_user=OWNER,
        confidence=Confidence.EXTRACTED, provenance=_prov(),
    )


def _skill(sid: str = "sk_sketchup", name: str = "sketchup_bridge") -> Skill:
    return Skill(
        id=sid,
        name=name,
        description=(
            "Drive the sketchup connector bridge: import skp geometry into "
            "the archhub graph and keep node params live across recooks."
        ),
        triggers=["sketchup connector", "import skp"],
        body="1. open bridge\n2. import skp\n3. verify node graph",
        scope=Scope.USER,
        visibility=Visibility.PRIVATE,
        owner_user=OWNER,
        provenance=_prov(),
    )


def _sync(store: BrainStore) -> P.PersonalCloudSync:
    # tick() is never called — only the wire/apply helpers are exercised,
    # so no config/network is involved.
    return P.PersonalCloudSync(store, owner_user=OWNER)


# ════════════════ 1. skills are COUNTED on the read path ════════════════


def test_build_context_increments_skill_success_count_row():
    s = BrainStore.open(":memory:")
    try:
        s.upsert_skill(_skill())
        assert s.get_skill("sk_sketchup").success_count == 0

        payload = make_context_payload(
            store=s, prompt="sketchup connector", owner_user=OWNER,
        )
        assert [sk.id for sk in payload.skills] == ["sk_sketchup"]

        row = s.get_skill("sk_sketchup")
        assert row.success_count == 1  # the row, not the in-payload copy
        assert row.last_used_at is not None
    finally:
        s.close()


def test_federation_gate_reachable_after_three_context_touches():
    s = BrainStore.open(":memory:")
    try:
        s.upsert_skill(_skill())

        for expected in (1, 2):
            make_context_payload(
                store=s, prompt="sketchup connector", owner_user=OWNER,
            )
            assert s.get_skill("sk_sketchup").success_count == expected

        # 2 touches: still below the sharing gate — pattern list empty.
        assert derive_skill_usage_patterns(
            [s.get_skill("sk_sketchup")], firm_id="firm1",
        ) == []

        make_context_payload(
            store=s, prompt="sketchup connector", owner_user=OWNER,
        )
        sk = s.get_skill("sk_sketchup")
        assert sk.success_count == 3

        pats = derive_skill_usage_patterns([sk], firm_id="firm1")
        assert len(pats) == 1
        assert pats[0].statistics["success_count"] == 3
        assert pats[0].kind == "skill_usage"
    finally:
        s.close()


def test_touch_skill_failure_lane_counts_separately():
    s = BrainStore.open(":memory:")
    try:
        s.upsert_skill(_skill())
        s.touch_skill("sk_sketchup", success=True)
        s.touch_skill("sk_sketchup", success=False)
        row = s.get_skill("sk_sketchup")
        assert (row.success_count, row.fail_count) == (1, 1)
    finally:
        s.close()


# ════════════ 2. sync round-trip preserves reinforcement ════════════════


def test_fragment_wire_carries_counters_and_roundtrips():
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    try:
        a.write_fragment(_fact("f_rt", "cornice profile offset is -300"))
        for _ in range(5):
            a.touch_fragment("f_rt", success=True)
        for _ in range(2):
            a.touch_fragment("f_rt", success=False)

        wire = _sync(a)._fragment_to_wire(a.get_fragment("f_rt"))
        assert wire["success_count"] == 5
        assert wire["fail_count"] == 2
        assert wire["last_used_at"]  # ISO string, not None

        # Round-trip into a store that has never seen the fragment.
        assert _sync(b)._apply_remote_fragment(wire, OWNER) is True
        got = b.get_fragment("f_rt")
        assert got.success_count == 5
        assert got.fail_count == 2
        assert got.last_used_at is not None
    finally:
        a.close()
        b.close()


def test_apply_never_lowers_local_fragment_evidence():
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    try:
        a.write_fragment(_fact("f_max", "broker port for revit session"))
        for _ in range(2):
            a.touch_fragment("f_max", success=True)
        wire = _sync(a)._fragment_to_wire(a.get_fragment("f_max"))
        assert wire["success_count"] == 2

        # Local replica has MORE evidence than the remote copy.
        b.write_fragment(_fact("f_max", "broker port for revit session"))
        for _ in range(8):
            b.touch_fragment("f_max", success=True)
        b.touch_fragment("f_max", success=False)
        local_used = b.get_fragment("f_max").last_used_at

        assert _sync(b)._apply_remote_fragment(wire, OWNER) is True
        got = b.get_fragment("f_max")
        assert got.success_count == 8      # max(8 local, 2 remote) — not wiped
        assert got.fail_count == 1         # max(1 local, 0 remote)
        assert got.last_used_at >= local_used  # never rewound
    finally:
        a.close()
        b.close()


def test_skill_wire_roundtrip_and_max_merge_personal_cloud_sync():
    a = BrainStore.open(":memory:")
    b = BrainStore.open(":memory:")
    try:
        a.upsert_skill(_skill())
        for _ in range(4):
            a.touch_skill("sk_sketchup", success=True)

        wires = _sync(a)._collect_user_skills_as_fragments(OWNER)
        assert len(wires) == 1
        assert wires[0]["extra"]["skill"]["success_count"] == 4

        # Local replica already has the skill with MORE evidence.
        b.upsert_skill(_skill())
        for _ in range(7):
            b.touch_skill("sk_sketchup", success=True)

        assert _sync(b)._apply_remote_skill(wires[0], OWNER) is True
        got = b.get_skill("sk_sketchup")
        assert got.success_count == 7  # max(7 local, 4 remote)

        # And a virgin store keeps the remote evidence intact (round-trip).
        c = BrainStore.open(":memory:")
        try:
            assert _sync(c)._apply_remote_skill(wires[0], OWNER) is True
            assert c.get_skill("sk_sketchup").success_count == 4
        finally:
            c.close()
    finally:
        a.close()
        b.close()


def test_sync_worker_skill_apply_merges_max():
    from personal_brain.sync_worker import SyncWorker

    s = BrainStore.open(":memory:")
    try:
        s.upsert_skill(_skill())
        for _ in range(5):
            s.touch_skill("sk_sketchup", success=True)
        local_used = s.get_skill("sk_sketchup").last_used_at

        worker = SyncWorker(s, transport=object())  # apply helper only
        remote = _skill().model_dump(mode="json")
        remote["success_count"] = 2
        remote["fail_count"] = 3
        remote["last_used_at"] = "2020-01-01T00:00:00+00:00"
        worker._write_remote_skill_into_store(remote)

        got = s.get_skill("sk_sketchup")
        assert got.success_count == 5   # max(5 local, 2 remote)
        assert got.fail_count == 3      # max(0 local, 3 remote)
        assert got.last_used_at >= local_used  # stale remote never rewinds
    finally:
        s.close()


def test_sync_worker_fragment_apply_carries_and_merges_counters():
    from personal_brain.sync_worker import SyncWorker

    s = BrainStore.open(":memory:")
    try:
        worker = SyncWorker(s, transport=object())
        f = _fact("f_sw", "missoni facade slab edge").model_dump(mode="json")
        f["success_count"] = 6
        f["fail_count"] = 1
        f["last_used_at"] = "2026-01-01T00:00:00+00:00"
        worker._write_remote_fragment_into_store(f)
        got = s.get_fragment("f_sw")
        assert (got.success_count, got.fail_count) == (6, 1)

        # Local now gains more evidence; a stale remote copy can't lower it.
        for _ in range(4):
            s.touch_fragment("f_sw", success=True)  # 6 → 10
        worker._write_remote_fragment_into_store(f)
        assert s.get_fragment("f_sw").success_count == 10
    finally:
        s.close()


# ═══════════ 3. self_extend:: loop facts surface in context ═════════════

_TARGET_ID = "self_extend::connector::sketchup"
_TARGET_TEXT = (
    "self_extend::connector::sketchup — loop minted SELF_EXTEND bridge that "
    "imports skp geometry via the sketchup python bridge into archhub graph nodes"
)
_DECOY_WORDS = [
    "alpha", "bravo", "charlie", "delta", "echo",
    "foxtrot", "golf", "hotel", "india",
]
_CODE_QUERY = "sketchup connector self-extended SELF_EXTEND"
_PROSE_QUERY = "sketchup connector self-extended"


def _seed_recall_store() -> BrainStore:
    """Target self_extend fact + 10 harvest decoys. Nine decoys are dense-lane
    magnets (short texts made of the query's own prose tokens), the tenth is a
    low-relevance sink so min-max normalization has a floor below the target."""
    s = BrainStore.open(":memory:")
    s.write_fragment(_fact(_TARGET_ID, _TARGET_TEXT, subject=_TARGET_ID))
    for i, word in enumerate(_DECOY_WORDS):
        s.write_fragment(_fact(
            f"harvest::{i}",
            f"harvest note {word}: sketchup connector self extended capture "
            "of the sketchup connector self extended session",
        ))
    s.write_fragment(_fact(
        "harvest::sink",
        "harvest archive of sketchup meetup photos and unrelated lunch "
        "receipts from the studio trip last spring",
    ))
    return s


def _context_fact_ids(monkeypatch, env_value: str | None, query: str) -> list[str]:
    """Fresh identically-seeded store per call — make_context_payload touches
    rows (reconsolidation), so runs must not share state to be comparable."""
    if env_value is None:
        monkeypatch.delenv("ARCHHUB_HYBRID_RECALL", raising=False)
    else:
        monkeypatch.setenv("ARCHHUB_HYBRID_RECALL", env_value)
    s = _seed_recall_store()
    try:
        payload = make_context_payload(store=s, prompt=query, owner_user=OWNER)
        return [f.id for f in payload.facts]
    finally:
        s.close()


def test_self_extend_fact_surfaces_with_hybrid_default_on(monkeypatch):
    # Env UNSET → default ON ('1'): the exact-code query must surface the
    # self_extend fact past the 10 harvest decoys.
    ids_default = _context_fact_ids(monkeypatch, None, _CODE_QUERY)
    assert _TARGET_ID in ids_default
    assert ids_default[0] == _TARGET_ID  # BM25 idf spike puts it first

    # Explicit '1' behaves identically to unset.
    assert _context_fact_ids(monkeypatch, "1", _CODE_QUERY) == ids_default


def test_hybrid_off_equals_pure_dense_and_buries_the_fact(monkeypatch):
    ids_off = _context_fact_ids(monkeypatch, "0", _CODE_QUERY)

    # '0' kills the lane entirely: bit-identical to hybrid_alpha=1.0 on the
    # same seed (the ORIGINAL pure-dense path).
    s = _seed_recall_store()
    try:
        pure = [
            f.id for f in retrieve_facts(
                s, _CODE_QUERY, owner_user=OWNER, k=8, hybrid_alpha=1.0,
            )
        ]
    finally:
        s.close()
    assert ids_off == pure

    # …and pure dense is exactly the audited failure: the loop fact is
    # buried below the harvest decoys, absent from the payload.
    assert _TARGET_ID not in ids_off


def test_prose_query_is_regression_free_with_lane_on(monkeypatch):
    # No exact-code token → predict_alpha returns 1.0 → lane ON must be
    # bit-identical to lane OFF (zero-risk default preserved by the
    # predictor itself).
    ids_on = _context_fact_ids(monkeypatch, None, _PROSE_QUERY)
    ids_off = _context_fact_ids(monkeypatch, "0", _PROSE_QUERY)
    assert ids_on == ids_off
