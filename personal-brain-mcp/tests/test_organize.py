"""Tests for personal_brain.organize — facet organization + embedding backfill.

Acceptance (founder guardrails):
  1. brain_reembed fills every NULL/empty embedding and is idempotent (a
     second pass embeds zero new rows).
  2. brain_organize is idempotent — a second run reports the same facet
     counts and performs no further merges.
  3. MERGE only fires for pairs that are cosine>=0.95 AND same subject AND
     same predicate; rows that differ on subject/predicate, or that are below
     threshold, are NOT merged.
  4. ARCHIVE sets valid_until on a stale trace (kind=trace, >30d, 0 successes)
     and does NOT hard-delete it; Decisions/Capability rows are never touched.
  5. HALF-LIFE-BY-KIND sets half_life_days per facet/kind every cycle
     (decision→180, capability→3650 pinned, trace→30, fact/rule→90), with
     predicate facets winning over kind buckets, leaving non-covered kinds
     untouched, and is idempotent (a second pass writes nothing).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from personal_brain.embeddings import LexicalEmbedder
from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Skill,
)
from personal_brain.organize import (
    CLUSTER_ASSIGN_THRESHOLD,
    FACET_SKILLS,
    HALF_LIFE_CAPABILITY,
    HALF_LIFE_DECISION,
    HALF_LIFE_FACT,
    HALF_LIFE_TRACE,
    MERGE_COSINE_THRESHOLD,
    brain_browse,
    brain_organize,
    brain_reembed,
    category_label,
    detect_project,
    facet_for,
    half_life_for,
    promote_skill_fragments,
    slugify_skill_name,
)
from personal_brain.storage import BrainStore


# Deterministic, zero-dep embedder — matches the live daemon backend (fastembed
# absent → LexicalEmbedder) so cosine thresholds in these tests are stable.
EMB = LexicalEmbedder()


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _prov(*, created_at=None, resources=None):
    return Provenance(
        contributing_agent="claude-opus-4-8",
        contributing_user="founder",
        created_at=created_at or datetime.now(timezone.utc),
        accessed_resources=resources or [],
    )


def _frag(
    fid,
    text,
    *,
    kind=FragmentKind.FACT,
    subject=None,
    predicate=None,
    obj=None,
    success=0,
    created_at=None,
    extra=None,
    resources=None,
) -> Fragment:
    return Fragment(
        id=fid,
        kind=kind,
        text=text,
        subject=subject,
        predicate=predicate,
        object=obj,
        scope=Scope.USER,
        owner_user="founder",
        provenance=_prov(created_at=created_at, resources=resources),
        success_count=success,
        extra=extra or {},
    )


# ─────────────────────── facet + label units ───────────────────────────


def test_facet_partition_by_predicate(store):
    cap = _frag("c1", "Input node", subject="Input", predicate="capability")
    dec = _frag("d1", "AgDR decision", subject="X", predicate="decision")
    mem = _frag("m1", "some fact", subject="Y", predicate="is")
    assert facet_for(cap) == "Capability"
    assert facet_for(dec) == "Decisions"
    assert facet_for(mem) == "Memory"


def test_category_label_from_extra_then_text(store):
    a = _frag("a", "whatever", extra={"category": "gotcha"})
    assert category_label(a) == "gotcha"
    b = _frag("b", 'Output {"category": "io", "in_types": []}')
    assert category_label(b) == "io"
    c = _frag("c", "no category anywhere here xyz")
    assert category_label(c) is None


# ─────────────────────── reembed ───────────────────────────────────────


def test_reembed_fills_null_and_is_idempotent(store):
    for i in range(5):
        store.write_fragment(_frag(f"f{i}", f"fragment number {i} about walls"))
    # Precondition: every row has a NULL/empty embedding.
    rows = store._conn.execute(
        "SELECT COUNT(*) n FROM fragments "
        "WHERE embedding_blob IS NULL OR length(embedding_blob)=0"
    ).fetchone()["n"]
    assert rows == 5

    r1 = brain_reembed(store, embedder=EMB)
    assert r1["rows_embedded"] == 5
    assert r1["dim"] == EMB.dim
    assert r1["backend"] == EMB.backend_name

    # Every row now carries a vector.
    null_after = store._conn.execute(
        "SELECT COUNT(*) n FROM fragments "
        "WHERE embedding_blob IS NULL OR length(embedding_blob)=0"
    ).fetchone()["n"]
    assert null_after == 0
    assert store.get_fragment("f0").embedding is not None

    # Idempotent — a second pass embeds nothing new.
    r2 = brain_reembed(store, embedder=EMB)
    assert r2["rows_embedded"] == 0
    assert r2["already_had"] == 5

    # brain_meta stamped.
    assert store.get_meta("embed.backend") == EMB.backend_name
    assert store.get_meta("embed.dim") == str(EMB.dim)


# ─────────────────────── organize idempotency ──────────────────────────


def test_organize_idempotent_facets_and_no_repeat_merge(store):
    store.write_fragment(_frag("c1", "Input node", subject="Input", predicate="capability"))
    store.write_fragment(_frag("d1", "Node redesign", subject="Redesign", predicate="decision"))
    store.write_fragment(_frag("m1", "gotcha about hosts", subject="Host", predicate="is",
                               extra={"category": "gotcha"}))
    store.write_fragment(_frag("m2", "render farm note", subject="Farm", predicate="is",
                               extra={"category": "render"}))

    r1 = brain_organize(store, embedder=EMB)
    assert r1["facet_counts"]["Capability"] == 1
    assert r1["facet_counts"]["Decisions"] == 1
    assert r1["facet_counts"]["Memory"] == 2
    assert r1["merges"] == 0  # all distinct subjects → nothing to merge

    # Labels written to extra_json.
    assert store.get_fragment("m1").extra.get("facet") == "Memory"
    assert store.get_fragment("m1").extra.get("cluster_label") == "gotcha"
    assert store.get_fragment("c1").extra.get("facet") == "Capability"

    # Second run — same facet counts, still zero merges, count unchanged.
    n_before = store.count_fragments()
    r2 = brain_organize(store, embedder=EMB)
    assert r2["facet_counts"] == r1["facet_counts"]
    assert r2["merges"] == 0
    assert store.count_fragments() == n_before

    # brain_meta persisted.
    assert store.get_meta("organize.last_run") is not None
    assert store.get_meta("organize.clusters") is not None


# ─────────────────────── merge threshold ───────────────────────────────


def test_merge_only_when_same_subject_predicate_and_high_cosine(store):
    # Pair A: identical text + same subject + same predicate → MUST merge.
    shared_text = "Speckle wire sends a Base subtree over DiskTransport offline"
    store.write_fragment(_frag("dup_keep", shared_text, subject="Speckle wire",
                               predicate="use-case", success=5))
    store.write_fragment(_frag("dup_loser", shared_text, subject="Speckle wire",
                               predicate="use-case", success=1,
                               resources=["mcp://speckle"]))
    # Pair B: same subject+predicate but very DIFFERENT text → below 0.95.
    store.write_fragment(_frag("diff_text", "completely unrelated content about Revit doors and windows",
                               subject="Speckle wire", predicate="use-case", success=0))
    # Pair C: identical text but DIFFERENT predicate → must NOT merge.
    store.write_fragment(_frag("other_pred", shared_text, subject="Speckle wire",
                               predicate="anti-pattern", success=0))

    r = brain_organize(store, embedder=EMB)

    # Exactly one merge happened (dup_keep + dup_loser).
    assert r["merges"] == 1
    # Loser deleted, keeper survives (higher success_count).
    assert store.get_fragment("dup_loser") is None
    keeper = store.get_fragment("dup_keep")
    assert keeper is not None
    assert keeper.success_count == 5
    # Provenance unioned — keeper picked up loser's resource.
    assert "mcp://speckle" in keeper.provenance.accessed_resources
    # Below-threshold + different-predicate rows untouched.
    assert store.get_fragment("diff_text") is not None
    assert store.get_fragment("other_pred") is not None

    # Sanity: the kept/loser pair really was >=0.95 and the diff pair really
    # was below — guards the test against a vacuous pass.
    v_keep = EMB.encode("Speckle wire sends a Base subtree over DiskTransport offline Speckle wire")
    v_diff = EMB.encode("completely unrelated content about Revit doors and windows Speckle wire")
    assert EMB.cosine(v_keep, v_keep) >= MERGE_COSINE_THRESHOLD
    assert EMB.cosine(v_keep, v_diff) < MERGE_COSINE_THRESHOLD


# ─────────────────────── archive (never delete) ────────────────────────


def test_archive_stale_trace_sets_valid_until_not_delete(store):
    old = datetime.now(timezone.utc) - timedelta(days=45)
    recent = datetime.now(timezone.utc) - timedelta(days=5)

    store.write_fragment(_frag("trace_old", "trace - old session", kind=FragmentKind.TRACE,
                               success=0, created_at=old))
    store.write_fragment(_frag("trace_recent", "trace - recent", kind=FragmentKind.TRACE,
                               success=0, created_at=recent))
    store.write_fragment(_frag("trace_used", "trace - old but reinforced", kind=FragmentKind.TRACE,
                               success=2, created_at=old))
    # A stale DECISION must never be archived.
    store.write_fragment(_frag("dec_old", "old decision", subject="D", predicate="decision",
                               kind=FragmentKind.FACT, success=0, created_at=old))

    r = brain_organize(store, embedder=EMB)

    assert r["archived"] == 1
    # Old zero-success trace ARCHIVED, not deleted.
    archived = store.get_fragment("trace_old")
    assert archived is not None, "archive must NOT hard-delete"
    assert archived.valid_until is not None
    # Recent trace + reinforced trace untouched.
    assert store.get_fragment("trace_recent").valid_until is None
    assert store.get_fragment("trace_used").valid_until is None
    # Decision row untouched (protected facet).
    assert store.get_fragment("dec_old").valid_until is None

    # Idempotent — a second pass archives nothing more (valid_until already set).
    r2 = brain_organize(store, embedder=EMB)
    assert r2["archived"] == 0


# ─────────────────────── nearest-centroid for unlabeled Memory ─────────


def test_unlabeled_memory_assigned_or_unfiled(store):
    # Two strongly-labeled anchors give centroids.
    store.write_fragment(_frag("lab1", "render farm gpu lighting bake exposure render render",
                               subject="A", predicate="is", extra={"category": "render"}))
    store.write_fragment(_frag("lab2", "host probe revit autocad rhino reachability host host",
                               subject="B", predicate="is", extra={"category": "host"}))
    # Unlabeled Memory row whose text leans 'render'.
    store.write_fragment(_frag("unl", "gpu render lighting exposure bake", subject="C", predicate="is"))

    r = brain_organize(store, embedder=EMB)
    unl = store.get_fragment("unl")
    assert unl.extra.get("facet") == "Memory"
    # It got SOME cluster_label (keyword guess, centroid match, or 'unfiled')
    # — never left without a label.
    assert unl.extra.get("cluster_label") in {"render", "host", "unfiled"}
    # Every unlabeled Memory row is accounted for by exactly one tier.
    assert r["assigned_by_keyword"] + r["assigned_by_centroid"] + r["unfiled"] >= 1


def test_centroid_path_assigns_row_with_no_vocab_token(store):
    # Anchor with an explicit label whose distinctive words are NOT in the
    # known-category vocabulary, so the unlabeled probe row can't keyword-match
    # and is forced down the embedding-centroid tier.
    store.write_fragment(_frag(
        "anchor", "zorblax quffin snarvel wibble zorblax quffin", subject="A",
        predicate="is", extra={"category": "gotcha"},
    ))
    store.write_fragment(_frag(
        "probe", "zorblax quffin snarvel wibble", subject="B", predicate="is",
    ))
    r = brain_organize(store, embedder=EMB)
    # No vocab token in either → keyword tier can't fire; centroid must.
    assert r["assigned_by_keyword"] == 0
    assert r["assigned_by_centroid"] == 1
    assert store.get_fragment("probe").extra.get("cluster_label") == "gotcha"


# ─────────────────────── half-life by facet / kind ─────────────────────


def test_half_life_for_unit_mapping_and_precedence():
    """half_life_for: predicate facets beat kind; non-covered kinds → None."""
    # decision predicate → 180 (even though kind=document, like the live rows).
    dec = _frag("d", "a decision", kind=FragmentKind.DOCUMENT,
                subject="X", predicate="decision")
    assert half_life_for(dec) == HALF_LIFE_DECISION == 180.0
    # capability predicate → 3650, and it WINS over the kind=fact→90 rule
    # (capability rows are themselves kind=fact in the live brain).
    cap = _frag("c", "a node capability", kind=FragmentKind.FACT,
                subject="Y", predicate="capability")
    assert half_life_for(cap) == HALF_LIFE_CAPABILITY == 3650.0
    # plain fact (non-decision, non-capability predicate) → 90.
    fact = _frag("f", "some rule", kind=FragmentKind.FACT,
                 subject="Z", predicate="rule")
    assert half_life_for(fact) == HALF_LIFE_FACT == 90.0
    # trace → 30.
    tr = _frag("t", "trace - x", kind=FragmentKind.TRACE)
    assert half_life_for(tr) == HALF_LIFE_TRACE == 30.0
    # skill / setup / etc are not covered → None (left untouched by organize).
    sk = _frag("s", "a procedure", kind=FragmentKind.SKILL, predicate="procedure")
    assert half_life_for(sk) is None
    setup = _frag("u", "a setup", kind=FragmentKind.SETUP, predicate="seat")
    assert half_life_for(setup) is None


def test_organize_sets_half_life_by_facet_and_kind(store):
    """The organize pass stamps the right half_life per facet/kind, leaving
    non-covered kinds at their default."""
    # All start at the model default (30.0).
    store.write_fragment(_frag("dec", "old decision", kind=FragmentKind.DOCUMENT,
                               subject="D", predicate="decision"))
    store.write_fragment(_frag("cap", "Input node capability", kind=FragmentKind.FACT,
                               subject="Input", predicate="capability"))
    store.write_fragment(_frag("fact", "a plain fact about hosts", kind=FragmentKind.FACT,
                               subject="Host", predicate="is"))
    store.write_fragment(_frag("trace", "trace - session", kind=FragmentKind.TRACE,
                               success=2))  # success>0 so it is NOT archived
    store.write_fragment(_frag("skill", "a procedure", kind=FragmentKind.SKILL,
                               subject="S", predicate="procedure"))

    # Precondition: every row sits at the 30.0 default.
    assert all(
        store.get_fragment(i).half_life_days == 30.0
        for i in ("dec", "cap", "fact", "trace", "skill")
    )

    r = brain_organize(store, embedder=EMB)

    assert store.get_fragment("dec").half_life_days == 180.0
    assert store.get_fragment("cap").half_life_days == 3650.0
    assert store.get_fragment("fact").half_life_days == 90.0
    assert store.get_fragment("trace").half_life_days == 30.0
    # Skill is not covered by the policy → untouched at its default.
    assert store.get_fragment("skill").half_life_days == 30.0

    # Result reports the work + the resulting distribution over covered rows.
    # dec(180) + cap(3650) were genuinely changed from 30; fact 30→90 changed;
    # trace stays 30 but is "set" (already correct → no write). So updates = 3.
    assert r["half_life_updates"] == 3
    assert r["half_life_distribution"] == {"30": 1, "90": 1, "180": 1, "3650": 1}


def test_organize_half_life_is_idempotent(store):
    """A second organize pass re-stamps NOTHING (half_life_updates == 0) —
    no churn against the live WAL."""
    store.write_fragment(_frag("dec", "decision", kind=FragmentKind.DOCUMENT,
                               subject="D", predicate="decision"))
    store.write_fragment(_frag("cap", "capability", kind=FragmentKind.FACT,
                               subject="C", predicate="capability"))
    store.write_fragment(_frag("fact", "fact", kind=FragmentKind.FACT,
                               subject="F", predicate="is"))

    r1 = brain_organize(store, embedder=EMB)
    assert r1["half_life_updates"] == 3  # all three moved off the 30.0 default

    r2 = brain_organize(store, embedder=EMB)
    assert r2["half_life_updates"] == 0  # idempotent — nothing left to change
    # Values still correct after the no-op second pass.
    assert store.get_fragment("dec").half_life_days == 180.0
    assert store.get_fragment("cap").half_life_days == 3650.0
    assert store.get_fragment("fact").half_life_days == 90.0


def test_organize_half_life_preserves_embedding(store):
    """Re-stamping half_life must not drop a fragment's vector (write_fragment
    re-packs fragment.embedding)."""
    store.write_fragment(_frag("cap", "capability node about walls", kind=FragmentKind.FACT,
                               subject="Wall", predicate="capability"))
    # Give it a vector first (mirrors the live reembed pass).
    brain_reembed(store, embedder=EMB)
    assert store.get_fragment("cap").embedding is not None

    brain_organize(store, embedder=EMB)

    frag = store.get_fragment("cap")
    assert frag.half_life_days == 3650.0
    assert frag.embedding is not None  # vector survived the half_life write


# ───────────────── skill-fragment promotion (founder gap-close) ──────────
#
# A prior harvest ingested ~49 mined procedures as kind=skill FRAGMENTS
# (name/trigger/broker_tool/steps in text + extra) because brain.write can't
# write the skills table and the human names violate the Skill.name regex.
# promote_skill_fragments lifts each into a proper `skills` row + deletes the
# now-duplicated fragment. These tests cover: slugify rules, upsert creates a
# valid Skill, fragment removed after promote, idempotency, and existing-skill
# collision skipped.


def _skill_frag(
    fid,
    skill_name,
    description,
    *,
    triggers=None,
    requires_mcps=None,
    body=None,
    examples="YES",
    scope=Scope.USER,
    owner_user="Fargaly",
):
    """Mint a harvested skill-FRAGMENT in the exact shape the live harvest used:
    kind=skill, the human name + structured fields packed into extra_json, and
    the description carried in `text`."""
    extra = {
        "category": "skill",
        "source": "session-harvest",
        "skill_name": skill_name,
        "triggers": triggers if triggers is not None else [f"User asks to {skill_name.lower()}"],
        "requires_mcps": requires_mcps if requires_mcps is not None else ["some_broker /exec"],
        "body": body if body is not None else (
            f"TRIGGER: do {skill_name}.\nBROKER/TOOL: some_broker /exec.\nSTEPS: step one; step two."
        ),
        "examples": examples,
        "confidence": 0.9,
        "facet": "Memory",
        "cluster_label": "skill",
    }
    return Fragment(
        id=fid,
        kind=FragmentKind.SKILL,
        text=description,
        subject=skill_name,
        predicate="procedure",
        object=(requires_mcps[0] if requires_mcps else "some_broker /exec"),
        scope=scope,
        owner_user=owner_user,
        provenance=_prov(),
        extra=extra,
    )


# ---- slugify rules -------------------------------------------------------


def test_slugify_basic_rules():
    # lowercase, spaces -> _, illegal stripped, collapsed, trimmed.
    assert slugify_skill_name("Hello World") == "hello_world"
    assert slugify_skill_name("AutoCAD batch DWG->PDF publish") == "autocad_batch_dwg_pdf_publish"
    # '&' becomes 'and'; apostrophes dropped (not turned into _).
    assert slugify_skill_name("Cats & Dogs") == "cats_and_dogs"
    assert slugify_skill_name("agent's claim") == "agents_claim"
    # leading/trailing/duplicate separators trimmed.
    assert slugify_skill_name("  --Foo..Bar--  ") == "foo_bar"


def test_slugify_must_start_with_letter_and_be_valid():
    pat = re.compile(r"^[a-z][a-z0-9_\-]*$")
    # leading digit -> prefixed so it starts with a letter.
    s = slugify_skill_name("123 go")
    assert s.startswith("s_") and pat.match(s)
    # all-illegal / empty -> a valid non-empty fallback (>=2 chars).
    s2 = slugify_skill_name("   ")
    assert pat.match(s2) and len(s2) >= 2
    s3 = slugify_skill_name("***")
    assert pat.match(s3) and len(s3) >= 2


def test_slugify_truncates_to_64_no_trailing_underscore():
    long = "word " * 40  # ~200 chars of words
    s = slugify_skill_name(long)
    assert len(s) <= 64
    assert not s.endswith("_")
    assert re.match(r"^[a-z][a-z0-9_\-]*$", s)


def test_slugify_dedupe_suffix_on_collision():
    taken: set[str] = set()
    a = slugify_skill_name("Edit revision table", taken=taken)
    b = slugify_skill_name("Edit revision table", taken=taken)
    c = slugify_skill_name("Edit revision table", taken=taken)
    assert a == "edit_revision_table"
    assert b == "edit_revision_table_2"
    assert c == "edit_revision_table_3"
    # all distinct + valid + within budget
    assert len({a, b, c}) == 3
    for s in (a, b, c):
        assert re.match(r"^[a-z][a-z0-9_\-]*$", s) and len(s) <= 64


def test_slugify_dedupe_suffix_keeps_length_budget():
    base = "x" * 64
    taken = {base}
    s = slugify_skill_name(base, taken=taken)
    assert s != base and len(s) <= 64 and s.endswith("_2")


# ---- upsert creates a valid Skill ---------------------------------------


def test_promote_creates_valid_skill_with_all_fields(store):
    store.write_fragment(
        _skill_frag(
            "harvest:001",
            "Edit AutoCAD revision-table attributes in bulk via accoreconsole",
            "Open each .dwg headlessly, find the title-block attribute block, "
            "and rewrite the DATE attribute wherever REV matches, then save.",
            triggers=["change the date for revision R in each AutoCAD file"],
            requires_mcps=["accoreconsole.exe /i <dwg> /s <_fixdate.scr>"],
        )
    )
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 1
    assert res["total_candidates"] == 1

    sk = store.get_skill(
        slugify_skill_name(
            "Edit AutoCAD revision-table attributes in bulk via accoreconsole"
        )
    )
    # name was slugified to the regex
    assert sk is not None
    assert re.match(r"^[a-z][a-z0-9_\-]*$", sk.name)
    # round-trips through the Skill model (regex name, >=80 desc, etc.)
    Skill(**sk.model_dump())
    # mapped fields
    assert sk.triggers == ["change the date for revision R in each AutoCAD file"]
    assert sk.requires_mcps == ["accoreconsole.exe /i <dwg> /s <_fixdate.scr>"]
    assert "STEPS" in sk.body or "save" in sk.body.lower()
    assert len(sk.description) >= 80
    # eval_queries synthesized (1-2)
    assert 1 <= len(sk.eval_queries) <= 2
    assert all(q.get("should_trigger") for q in sk.eval_queries)
    # provenance carried + breadcrumb added
    assert any(
        "promoted_from_fragment:harvest:001" in r
        for r in sk.provenance.accessed_resources
    )
    # broker-driven (write) procedure -> host_write side-effect
    assert sk.side_effects == "host_write"


def test_promote_pads_short_description_to_min_length(store):
    # A terse harvest description (<80 chars) must be padded to clear the
    # Skill.description >=80 floor without crashing the upsert.
    store.write_fragment(
        _skill_frag("harvest:short", "Probe Rhino bridge", "Ping the Rhino bridge.")
    )
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 1
    sk = store.get_skill("probe_rhino_bridge")
    assert sk is not None and len(sk.description) >= 80
    Skill(**sk.model_dump())


def test_promote_makes_skill_retrievable(store):
    store.write_fragment(
        _skill_frag(
            "harvest:cdp",
            "Live-verify a UI feature on the running ArchHub via CDP",
            "Attach to ArchHub QtWebEngine remote-debug endpoint and "
            "Runtime.evaluate to query and click DOM affordances as proof.",
        )
    )
    promote_skill_fragments(store, owner_user="Fargaly")
    hits = store.search_skills(
        "verify UI feature ArchHub CDP", owner_user="Fargaly", k=5
    )
    assert any(
        h.name == "live_verify_a_ui_feature_on_the_running_archhub_via_cdp"
        for h in hits
    )


# ---- fragment removed after promote -------------------------------------


def test_promote_deletes_fragment_after_promotion(store):
    store.write_fragment(
        _skill_frag(
            "harvest:del",
            "Backfill brain skills",
            "Backfill skills from traces idempotently and safely without dupes.",
        )
    )
    assert store.get_fragment("harvest:del") is not None
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 1
    assert res["deleted_fragments"] == 1
    # the skill-fragment is GONE from the Memory facet
    assert store.get_fragment("harvest:del") is None
    # but a proper skill now exists
    assert store.get_skill("backfill_brain_skills") is not None


def test_dry_run_promotes_nothing_and_leaves_fragment(store):
    store.write_fragment(
        _skill_frag(
            "harvest:dry",
            "Dry run skill",
            "A procedure used to verify the dry-run path leaves state untouched.",
        )
    )
    res = promote_skill_fragments(store, owner_user="Fargaly", dry_run=True)
    assert res["dry_run"] is True
    assert res["promoted"] == 1  # planned
    assert res["deleted_fragments"] == 0  # but nothing deleted
    assert store.get_fragment("harvest:dry") is not None  # still there
    assert store.count_skills() == 0  # nothing upserted
    assert len(res["slug_map"]) == 1


# ---- idempotent (2nd run promotes 0) ------------------------------------


def test_promote_is_idempotent_second_run_zero(store):
    # Three GENUINELY distinct procedures (distinct vocabulary, so the
    # near-dup guard does not collapse them) — mirrors the real 49 harvest.
    store.write_fragment(
        _skill_frag("harvest:idem0", "Export Revit sheets to PDF",
                    "Batch export Revit sheet views to PDF files using a named print set and a filename rule.")
    )
    store.write_fragment(
        _skill_frag("harvest:idem1", "Probe Rhino bridge health",
                    "Open an HTTP connection to the in-Rhino bridge on port 9879 and confirm it answers a ping.")
    )
    store.write_fragment(
        _skill_frag("harvest:idem2", "Reconcile Excel submittal log",
                    "Compare a master spreadsheet status column against a dated folder of deliverables and flag strays.")
    )
    r1 = promote_skill_fragments(store, owner_user="Fargaly")
    assert r1["promoted"] == 3
    assert r1["deleted_fragments"] == 3
    n_after = store.count_skills()

    r2 = promote_skill_fragments(store, owner_user="Fargaly")
    assert r2["promoted"] == 0
    assert r2["skipped_duplicate"] == 0
    assert r2["deleted_fragments"] == 0
    assert r2["total_candidates"] == 0
    assert store.count_skills() == n_after  # no churn

    # meta stamped
    assert store.get_meta("skills.promote.last_run") is not None


# ---- existing-skill collision skipped (DEDUPE) --------------------------


def test_promote_skips_same_slug_existing_skill(store):
    # Pre-seed a proper skill whose name equals the slug the fragment will get.
    existing = Skill(
        id="pre-existing-1",
        name="probe_rhino_bridge",
        description=(
            "Existing canonical skill for probing the Rhino MCP bridge in a "
            "live Rhino 8 session over HTTP on port 9879 without relaunch."
        ),
        body="existing body",
        owner_user="Fargaly",
        provenance=_prov(),
    )
    assert store.upsert_skill(existing) is True
    store.write_fragment(
        _skill_frag(
            "harvest:collide",
            "Probe Rhino bridge",
            "A second description of probing the Rhino bridge that should be skipped.",
        )
    )
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 0
    assert res["skipped_duplicate"] == 1
    assert res["skipped"][0]["duplicate_of"] == "probe_rhino_bridge"
    # existing skill kept unchanged (description not overwritten)
    kept = store.get_skill("probe_rhino_bridge")
    assert kept.description.startswith("Existing canonical skill")
    # the near-dup fragment is left in place (not silently deleted)
    assert store.get_fragment("harvest:collide") is not None


def test_promote_skips_near_identical_description(store):
    # Different name (different slug) but near-identical description -> skipped.
    existing = Skill(
        id="pre-existing-2",
        name="autocad_dwg_to_pdf_publisher",
        description=(
            "Headlessly publish each AutoCAD drawing file to PDF using "
            "accoreconsole and a publish script across the project folder batch."
        ),
        body="b",
        owner_user="Fargaly",
        provenance=_prov(),
    )
    store.upsert_skill(existing)
    store.write_fragment(
        _skill_frag(
            "harvest:near",
            "AutoCAD batch DWG to PDF publish via accoreconsole",
            "Headlessly publish each AutoCAD drawing file to PDF using "
            "accoreconsole and a publish script across the project folder batch.",
        )
    )
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 0
    assert res["skipped_duplicate"] == 1
    assert res["skipped"][0]["duplicate_of"] == "autocad_dwg_to_pdf_publisher"


def test_promote_distinct_skills_not_falsely_deduped(store):
    # Two genuinely different procedures must BOTH promote (no false dedupe).
    store.write_fragment(
        _skill_frag(
            "harvest:a",
            "Export Revit sheets to PDF",
            "Batch export Revit sheet views to PDF files using the print set and a naming rule.",
        )
    )
    store.write_fragment(
        _skill_frag(
            "harvest:b",
            "Reconcile Excel submittal log",
            "Compare a master Excel submittal status column against a dated submittal folder and move strays.",
        )
    )
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 2
    assert res["skipped_duplicate"] == 0


def test_browse_shows_promoted_skills_lane_not_skill_fragments(store):
    """After promotion the harvested skill-FRAGMENTS are deleted, so the browser
    must surface the real skills from the skills table in a 'How-to / Skills'
    lane — otherwise the founder's skills lane would go empty (the gap this
    closes). Verifies: (a) before promote, no skills lane / empty; (b) after
    promote, the lane carries the promoted skill; (c) the skill-fragment no
    longer appears as a Memory card; (d) a query surfaces the skill in search.
    """
    store.write_fragment(
        _skill_frag(
            "harvest:lane",
            "Export Revit sheets to PDF via the print set",
            "Batch export Revit sheet views to PDF files using a named print "
            "set and a deterministic filename rule across the whole sheet list.",
        )
    )
    # Before: the harvested fragment is a Memory card; no skills lane yet.
    before = brain_browse(store, owner_user="Fargaly")
    facets_before = {f["facet"]: f for f in before["facets"]}
    assert facets_before.get(FACET_SKILLS, {"count": 0})["count"] == 0
    assert before["totals"].get(FACET_SKILLS, 0) == 0

    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 1 and res["deleted_fragments"] == 1

    after = brain_browse(store, owner_user="Fargaly", query="export Revit sheets PDF")
    facets_after = {f["facet"]: f for f in after["facets"]}
    # (a) The skills lane now exists and carries the promoted skill.
    assert FACET_SKILLS in facets_after
    lane = facets_after[FACET_SKILLS]
    assert lane["count"] == 1
    assert after["totals"][FACET_SKILLS] == 1
    # The skills lane is shown FIRST (it's the 'what can I do' lane).
    assert after["facets"][0]["facet"] == FACET_SKILLS
    # The card headline is the plain description, kind=skill, with the slug
    # + triggers tucked under details.
    card = lane["clusters"][0]["top"][0]
    assert card["kind"] == "skill"
    assert card["details"]["name"] == "export_revit_sheets_to_pdf_via_the_print_set"
    assert card["details"]["triggers"]
    # (c) The deleted skill-fragment is gone from every fragment lane.
    all_frag_ids = [
        c["id"]
        for f in after["facets"] if f["facet"] != FACET_SKILLS
        for cl in f["clusters"] for c in cl["top"]
    ] + [c["id"] for c in after["top_of_mind"]]
    assert "harvest:lane" not in all_frag_ids
    # (d) The query path surfaces the promoted skill as a search card.
    search_ids = {c["id"] for c in after.get("search", [])}
    assert "promoted-skill-harvest:lane" in search_ids


def test_promote_collision_suffix_for_two_same_named_fragments(store):
    # Two harvested fragments with the SAME human name but DISTINCT
    # descriptions -> both promote, second gets a _2 slug suffix.
    store.write_fragment(
        _skill_frag(
            "harvest:dup1",
            "Sync the thing",
            "First distinct way of syncing the thing using the alpha broker and a manifest file.",
        )
    )
    store.write_fragment(
        _skill_frag(
            "harvest:dup2",
            "Sync the thing",
            "Totally separate beta procedure that pushes records over websocket with retry and backoff.",
        )
    )
    res = promote_skill_fragments(store, owner_user="Fargaly")
    assert res["promoted"] == 2
    slugs = sorted(m["slug"] for m in res["slug_map"])
    assert slugs == ["sync_the_thing", "sync_the_thing_2"]


# ─────────────────── project-code EXTRACTION (detect_project) ────────────
#
# Acceptance (founder gap-close 2026-06-01 — accurate EXTRACTION, not the
# deferred fabricated project_id assignment):
#   A. detect_project maps named-tower aliases + literal codes + the P-###
#      series to a canonical code, scanning text/subject/object/extra/prov.
#   B. WORD BOUNDARIES: 'install'/'installer' never read as the Staller tower;
#      a bare 'P461x' / 'BBC40' does not match.
#   C. MULTI-PROJECT GUARD: a row naming ≥2 projects returns None (stays
#      general) — no fabricated primary.
#   D. brain_organize tags ONLY Memory-facet facts (kind=fact, predicate not
#      capability/decision); it sets extra.project and NEVER project_id.
#   E. Idempotent: a second organize pass tags zero new rows + leaves
#      extra.project untouched, and never writes the ACL-gated project_id.


def test_detect_project_alias_map_staller_missoni():
    # "Staller" + both "Ellie/Elie Saab" spellings -> P-674; "Missoni" -> P-679.
    assert detect_project(_frag("t1", "Work on the Staller tower facade")) == "P-674"
    assert detect_project(_frag("t2", "Staller by Ellie Saab Tower model")) == "P-674"
    assert detect_project(_frag("t3", "the Elie Saab podium")) == "P-674"
    assert detect_project(_frag("t4", "Missoni Residential Tower XREF")) == "P-679"


def test_detect_project_literal_codes_and_pseries_canonical():
    # Literal codes.
    assert detect_project(_frag("c1", "BBC4 master xlsx lives on Sheet2")) == "BBC4"
    assert detect_project(_frag("c2", "doc 4300-BH3D-990370 in Revit")) == "BH3D"
    assert detect_project(_frag("c3", "BB3D spelling variant of the project")) == "BH3D"
    assert detect_project(_frag("c4", "active folder 26000-KIN on disk")) == "26000-KIN"
    # P-### canonicalised to 'P-###' regardless of separator.
    assert detect_project(_frag("p1", "files under P-674 on baserver")) == "P-674"
    assert detect_project(_frag("p2", "the P 679 drawings")) == "P-679"
    assert detect_project(_frag("p3", "project P461 archived")) == "P-461"


def test_detect_project_scans_subject_object_and_extra():
    # subject-only.
    assert detect_project(_frag("s1", "no code here", subject="BBC4 master xlsx")) == "BBC4"
    # object-only.
    assert detect_project(
        _frag("o1", "geometry path", obj="\\\\BASERVER\\Ongoing\\P-679 Missoni\\")
    ) == "P-679"
    # extra-only (the harvest stores some project hints in structured extra).
    assert detect_project(
        _frag("e1", "submittal pipeline steps", extra={"what_worked": "across 3 BBC4 sessions"})
    ) == "BBC4"


def test_detect_project_word_boundary_no_false_positive_on_installer():
    # The load-bearing safety case: a loose 'stall?er' matches 'install' /
    # 'installer'. detect_project must NOT read these daemon/installer rows as
    # the Staller (P-674) tower.
    assert detect_project(_frag("f1", "brain installer hardcodes the path")) is None
    assert detect_project(_frag("f2", "DO NOT touch installer.py or server.py")) is None
    assert detect_project(_frag("f3", "python -m personal_brain.installer auto-wires")) is None
    # And a digit run that isn't a clean P-### token does not match.
    assert detect_project(_frag("f4", "ticket P4610 and value 1679 in a path")) is None
    # 'BBC40' / 'BBC4X' must NOT match the BBC4 code (boundary after the 4).
    assert detect_project(_frag("f5", "the BBC40 build and BBC4X variant")) is None


def test_detect_project_multi_project_guard_returns_none():
    # A row naming several projects is a CROSS-project fact -> stays general.
    inventory = _frag(
        "m1",
        "workspace inventory: 26000-KIN, BBC4, P461, P603, P674, P973 plus more",
    )
    assert detect_project(inventory) is None
    file_locs = _frag(
        "m2",
        "P-674 Staller by Ellie Saab and P-679 Missoni both live on BASERVER",
    )
    assert detect_project(file_locs) is None
    # Exactly one project (even if its alias + code co-occur) still resolves —
    # 'Staller' and 'P-674' are the SAME project, so this is single, not multi.
    one = _frag("m3", "P-674 Staller by Ellie Saab tower, Miral DD submission")
    assert detect_project(one) == "P-674"


def test_detect_project_none_when_no_project_named():
    assert detect_project(_frag("n1", "QWebChannel slots are async, return a Promise")) is None
    assert detect_project(_frag("n2", "")) is None


def test_brain_organize_tags_only_memory_facts():
    s = BrainStore.open(":memory:")
    try:
        # Memory facts that name exactly one project -> tagged.
        s.write_fragment(_frag("mem-bbc4", "BBC4 master xlsx on Sheet2", predicate="data_on"))
        s.write_fragment(
            _frag("mem-missoni", "X-REF on \\\\BASERVER P-679 Missoni", predicate="located_at")
        )
        # Capability row that happens to mention a project -> NOT tagged
        # (machine catalog is not project-specific; the research's warning).
        s.write_fragment(
            _frag("cap-x", "Revit connector used on BBC4", subject="revit", predicate="capability")
        )
        # Decision row mentioning a project -> NOT tagged.
        s.write_fragment(
            _frag("dec-x", "Chose Speckle for P-674", subject="wire", predicate="decision")
        )
        # A skill-KIND fragment naming a project -> NOT tagged (only kind=fact).
        s.write_fragment(
            _frag("skill-x", "procedure for BBC4", kind=FragmentKind.SKILL, predicate="skill")
        )
        # A Memory fact with NO project -> left untagged/general.
        s.write_fragment(_frag("mem-none", "QWebChannel slots are async", predicate="is"))

        res = brain_organize(s, embedder=EMB, owner_user="founder")

        assert res["projects_tagged"] == 2
        assert res["projects_by_code"] == {"BBC4": 1, "P-679": 1}

        def proj(fid):
            return (s.get_fragment(fid).extra or {}).get("project")

        assert proj("mem-bbc4") == "BBC4"
        assert proj("mem-missoni") == "P-679"
        # Protected facets + non-fact kinds + no-project rows carry NO tag.
        assert proj("cap-x") is None
        assert proj("dec-x") is None
        assert proj("skill-x") is None
        assert proj("mem-none") is None

        # CRITICAL SAFETY: the ACL-gated project_id column is NEVER written.
        for fid in ("mem-bbc4", "mem-missoni", "cap-x", "dec-x", "skill-x", "mem-none"):
            assert s.get_fragment(fid).project_id is None
    finally:
        s.close()


def test_brain_organize_multi_project_row_left_general():
    s = BrainStore.open(":memory:")
    try:
        s.write_fragment(
            _frag(
                "multi",
                "P-674 Staller and P-679 Missoni both on BASERVER",
                subject="firm project file locations",
                predicate="are",
            )
        )
        res = brain_organize(s, embedder=EMB, owner_user="founder")
        assert res["projects_tagged"] == 0
        assert res["projects_left_general"] == 1
        assert (s.get_fragment("multi").extra or {}).get("project") is None
        assert s.get_fragment("multi").project_id is None
    finally:
        s.close()


def test_brain_organize_project_tag_is_idempotent():
    s = BrainStore.open(":memory:")
    try:
        s.write_fragment(_frag("mem-bbc4", "BBC4 master xlsx on Sheet2", predicate="data_on"))
        s.write_fragment(
            _frag("mem-674", "Staller by Ellie Saab Miral DD", predicate="workflow-pattern")
        )

        first = brain_organize(s, embedder=EMB, owner_user="founder")
        assert first["projects_tagged"] == 2

        # Second pass: tags already match -> ZERO new writes (idempotent), and
        # the per-code census still reports the true state.
        second = brain_organize(s, embedder=EMB, owner_user="founder")
        assert second["projects_tagged"] == 0
        assert second["projects_by_code"] == {"BBC4": 1, "P-674": 1}

        # Tags persisted unchanged; project_id still untouched.
        assert (s.get_fragment("mem-bbc4").extra or {}).get("project") == "BBC4"
        assert (s.get_fragment("mem-674").extra or {}).get("project") == "P-674"
        assert s.get_fragment("mem-bbc4").project_id is None
        assert s.get_fragment("mem-674").project_id is None
    finally:
        s.close()


# ─────────────────── browse project breakdown + filter ──────────────────
#
# Acceptance (founder gap-close 2026-06-01 — surface the project tags):
#   F. brain_browse returns a `projects` per-project fact census (always the
#      complete set, even while a filter is active) + echoes the active filter.
#   G. Every fragment card carries its extra.project (None for general rows).
#   H. Passing project=CODE scopes top_of_mind + lanes + archived to that
#      project's facts only; the skills lane (cross-project) is suppressed.
#   I. A filtered search returns only that project's matching facts.


def _collect_card_ids(payload):
    """Every fragment-card id across top_of_mind + the (non-skill) facet lanes."""
    ids = {c["id"] for c in payload["top_of_mind"]}
    for f in payload["facets"]:
        if f["facet"] == FACET_SKILLS:
            continue
        for cl in f["clusters"]:
            for c in cl["top"]:
                ids.add(c["id"])
    return ids


def test_browse_projects_breakdown_and_card_project_field(store):
    # Two BBC4 facts, one P-674 fact, one general (no project) fact.
    store.write_fragment(_frag("b1", "BBC4 master xlsx on Sheet2", predicate="data_on"))
    store.write_fragment(_frag("b2", "BBC4 submittal QC folder reconcile", predicate="workflow-pattern"))
    store.write_fragment(_frag("s1", "Staller by Ellie Saab Miral DD", predicate="workflow-pattern"))
    store.write_fragment(_frag("g1", "QWebChannel slots are async", predicate="is"))
    # Tag them (organize stamps extra.project).
    brain_organize(store, embedder=EMB, owner_user="founder")

    view = brain_browse(store, owner_user="founder")
    # (F) census reflects the true per-project counts; general row excluded.
    assert view["projects"] == {"BBC4": 2, "P-674": 1}
    assert view["project"] is None
    # (G) every card exposes the project organize stamped (None for general).
    # Build the expected map from the store, then assert each card that DOES
    # surface carries the right value (top-3-per-cluster means not every id is
    # guaranteed to appear, but the ones that do must be correct).
    expected = {fid: (store.get_fragment(fid).extra or {}).get("project")
                for fid in ("b1", "b2", "s1", "g1")}
    seen_any = {}
    for f in view["facets"]:
        if f["facet"] == FACET_SKILLS:
            continue
        for cl in f["clusters"]:
            for c in cl["top"]:
                if c["id"] in expected:
                    assert c["project"] == expected[c["id"]]
                    seen_any[c["id"]] = c["project"]
    for c in view["top_of_mind"]:
        if c["id"] in expected:
            assert c["project"] == expected[c["id"]]
            seen_any[c["id"]] = c["project"]
    # At least one project-tagged card and the general card actually surfaced,
    # proving the field is threaded for both the tagged and untagged cases.
    assert any(v == "BBC4" for v in seen_any.values())
    assert "g1" in seen_any and seen_any["g1"] is None


def test_browse_project_filter_scopes_view(store):
    store.write_fragment(_frag("b1", "BBC4 master xlsx on Sheet2", predicate="data_on"))
    store.write_fragment(_frag("b2", "BBC4 submittal QC folder reconcile", predicate="workflow-pattern"))
    store.write_fragment(_frag("s1", "Staller by Ellie Saab Miral DD", predicate="workflow-pattern"))
    store.write_fragment(_frag("g1", "QWebChannel slots are async", predicate="is"))
    brain_organize(store, embedder=EMB, owner_user="founder")

    # (H) filter to BBC4 → only the two BBC4 facts appear; the census stays
    # complete (so the chip-row still offers every project).
    view = brain_browse(store, owner_user="founder", project="BBC4")
    assert view["project"] == "BBC4"
    assert view["projects"] == {"BBC4": 2, "P-674": 1}
    ids = _collect_card_ids(view)
    assert ids == {"b1", "b2"}
    # Memory facet count reflects only the filtered rows.
    mem = {f["facet"]: f for f in view["facets"]}.get("Memory")
    assert mem is not None and mem["count"] == 2

    # Filtering to P-674 yields only the Staller fact.
    view2 = brain_browse(store, owner_user="founder", project="P-674")
    assert _collect_card_ids(view2) == {"s1"}


def test_browse_project_filter_hides_skills_lane(store):
    # A promoted skill exists + one project-tagged fact.
    store.write_fragment(
        _skill_frag(
            "harvest:p",
            "Reconcile BBC submittal folder",
            "Reconcile the master xlsx against a dated submittal folder, matching "
            "column D and moving stray rows into a not-on-master bucket per QC.",
        )
    )
    store.write_fragment(_frag("b1", "BBC4 master xlsx on Sheet2", predicate="data_on"))
    promote_skill_fragments(store, owner_user="founder")
    brain_organize(store, embedder=EMB, owner_user="founder")

    # Unfiltered: the skills lane is present (it's the first lane).
    unfiltered = brain_browse(store, owner_user="founder")
    assert any(f["facet"] == FACET_SKILLS and f["count"] > 0 for f in unfiltered["facets"])

    # Filtered to a project: skills (cross-project) are suppressed.
    filtered = brain_browse(store, owner_user="founder", project="BBC4")
    assert all(f["facet"] != FACET_SKILLS for f in filtered["facets"])
    assert filtered["totals"].get(FACET_SKILLS, 0) == 0


def test_browse_filtered_search_scopes_to_project(store):
    # Same noun ("master") in a BBC4 fact and a P-674 fact; a project-scoped
    # search must return only the selected project's hit.
    store.write_fragment(_frag("b1", "BBC4 master xlsx on Sheet2", predicate="data_on"))
    store.write_fragment(_frag("s1", "Staller master plan drawing set", predicate="workflow-pattern"))
    brain_organize(store, embedder=EMB, owner_user="founder")

    res = brain_browse(store, owner_user="founder", query="master", project="BBC4")
    hit_ids = {c["id"] for c in res.get("search", [])}
    assert "b1" in hit_ids
    assert "s1" not in hit_ids  # P-674 fact excluded by the project filter
