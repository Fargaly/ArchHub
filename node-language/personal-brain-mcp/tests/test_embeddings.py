"""Slice 2 — embeddings + retrieval tests.

Lexical fallback must be deterministic and correctly rank semantically
related items higher than unrelated ones for the typical case.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain.embeddings import (
    Embedder,
    LexicalEmbedder,
    cosine,
    get_embedder,
    reset_default_embedder,
    score_against_query,
    triple_score,
)
from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Skill,
)
from personal_brain.retrieval import (
    retrieve_facts,
    retrieve_mixed,
    retrieve_skills,
)
from personal_brain.storage import BrainStore


def _prov():
    return Provenance(
        contributing_agent="claude-sonnet-4.7",
        contributing_user="founder",
        created_at=datetime.now(timezone.utc),
    )


# ─────────────────────── embedder unit tests ───────────────────────────


def test_lexical_embedder_deterministic():
    emb = LexicalEmbedder(dim=512)
    v1 = emb.encode("Tower-A wall takeoff")
    v2 = emb.encode("Tower-A wall takeoff")
    assert v1 == v2
    assert len(v1) == 512


def test_lexical_cosine_similar_higher_than_unrelated():
    emb = LexicalEmbedder()
    v_query = emb.encode("revit wall takeoff for Tower-A")
    v_related = emb.encode("extract wall counts from Revit document")
    v_unrelated = emb.encode("send notion page summary to teammate")
    s_related = emb.cosine(v_query, v_related)
    s_unrelated = emb.cosine(v_query, v_unrelated)
    assert s_related > s_unrelated
    assert s_related > 0.0


def test_lexical_zero_for_empty():
    emb = LexicalEmbedder()
    v_empty = emb.encode("")
    v_word = emb.encode("hello")
    # cosine with all-zero vector is 0
    assert emb.cosine(v_empty, v_word) == 0.0


def test_lexical_normalised():
    emb = LexicalEmbedder()
    v = emb.encode("hello world this is a test")
    # L2 norm should be ~1
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6 or norm == 0.0


def test_get_embedder_returns_protocol():
    reset_default_embedder()
    emb = get_embedder(prefer="lexical")
    assert isinstance(emb, Embedder)
    assert emb.dim > 0
    assert emb.backend_name


def test_cosine_function_handles_mismatch():
    assert cosine([1.0, 0.0], [1.0]) == 0.0
    assert cosine([], []) == 0.0


def test_score_against_query_orders_by_relevance():
    items = [
        {"text": "send notion page summary"},
        {"text": "extract revit wall counts and floor areas"},
        {"text": "random unrelated stuff about cooking"},
    ]
    ranked = score_against_query(
        "revit walls", items, text_attr="text",
        embedder=LexicalEmbedder(),
    )
    # Best match comes first
    assert "revit wall" in ranked[0][0]["text"].lower()


def test_triple_score_recency_dominates_when_alpha_high():
    fresh = triple_score(
        relevance=0.5, recency_seconds=60, half_life_seconds=3600,
        alpha=10.0, beta=0.0, gamma=0.0,
    )
    stale = triple_score(
        relevance=0.5, recency_seconds=3600 * 24 * 30, half_life_seconds=3600,
        alpha=10.0, beta=0.0, gamma=0.0,
    )
    assert fresh > stale


def test_triple_score_relevance_overrides_recency_when_gamma_high():
    relevant = triple_score(
        relevance=0.9, recency_seconds=1e9, half_life_seconds=3600,
        alpha=1.0, beta=0.0, gamma=10.0,
    )
    irrelevant_fresh = triple_score(
        relevance=0.0, recency_seconds=10, half_life_seconds=3600,
        alpha=1.0, beta=0.0, gamma=10.0,
    )
    assert relevant > irrelevant_fresh


# ─────────────────────── retrieval integration ─────────────────────────


@pytest.fixture
def seeded_store():
    s = BrainStore.open(":memory:")
    skills = [
        Skill(
            id="sk-revit",
            name="revit_takeoff",
            description=(
                "Extract wall, floor, room counts and total areas from the "
                "active Revit document and return a structured QTO table."
            ),
            triggers=["wall count", "takeoff", "QTO", "schedule"],
            requires_mcps=["revit-mcp"],
            body="# Revit takeoff",
            examples=[{"input": "Tower-A wall count", "output": "247"}],
            owner_user="founder",
            provenance=_prov(),
            success_count=10, fail_count=1,
        ),
        Skill(
            id="sk-notion",
            name="notion_summarise",
            description=(
                "Read a Notion page by URL or id and produce a 5-bullet "
                "executive summary saved back to the workspace as child page."
            ),
            triggers=["summarize notion", "notion summary"],
            requires_mcps=["notion-mcp"],
            body="# Notion summarise",
            examples=[{"input": "summarize notion", "output": "..."}],
            owner_user="founder",
            provenance=_prov(),
            success_count=5, fail_count=0,
        ),
        Skill(
            id="sk-figma",
            name="figma_handoff",
            description=(
                "Push a figma frame's design context to GitHub via Code "
                "Connect — generates the component map and opens a PR."
            ),
            triggers=["figma handoff", "code connect"],
            requires_mcps=["figma-mcp", "github-mcp"],
            body="# Figma handoff",
            examples=[{"input": "handoff frame", "output": "PR url"}],
            owner_user="founder",
            provenance=_prov(),
            success_count=3, fail_count=2,
        ),
    ]
    for sk in skills:
        s.upsert_skill(sk)

    facts = [
        Fragment(
            id="f-units", kind=FragmentKind.FACT,
            text="user prefers metric units for all Revit work",
            subject="user", predicate="prefers", object="metric",
            owner_user="founder", provenance=_prov(),
            success_count=20, half_life_days=60,
        ),
        Fragment(
            id="f-wall", kind=FragmentKind.FACT,
            text="Tower-A standard wall type is Generic-200mm with rebar",
            subject="Tower-A", predicate="wall_type", object="Generic-200mm",
            owner_user="founder", provenance=_prov(),
            success_count=8, half_life_days=30,
        ),
        Fragment(
            id="f-pnpm", kind=FragmentKind.FACT,
            text="user uses pnpm not npm for all js projects",
            subject="user", predicate="uses", object="pnpm",
            owner_user="founder", provenance=_prov(),
            success_count=12,
        ),
        Fragment(
            id="f-firm", kind=FragmentKind.FACT,
            text="firm template is ArchHub-Studio-v2 for new projects",
            subject="firm", predicate="template", object="ArchHub-Studio-v2",
            owner_user="founder", provenance=_prov(),
        ),
    ]
    for f in facts:
        s.write_fragment(f)
    yield s
    s.close()


def test_retrieve_skills_ranks_revit_first_for_revit_query(seeded_store):
    skills = retrieve_skills(
        seeded_store, "give me the wall takeoff for Tower-A",
        owner_user="founder", k=3, embedder=LexicalEmbedder(),
    )
    assert skills
    assert skills[0].name == "revit_takeoff"


def test_retrieve_skills_ranks_notion_first_for_notion_query(seeded_store):
    skills = retrieve_skills(
        seeded_store, "summarize this notion page",
        owner_user="founder", k=3, embedder=LexicalEmbedder(),
    )
    assert skills
    assert skills[0].name == "notion_summarise"


def test_retrieve_facts_returns_relevant_only(seeded_store):
    facts = retrieve_facts(
        seeded_store, "wall type for Tower-A",
        owner_user="founder", k=4, embedder=LexicalEmbedder(),
    )
    assert facts
    # f-wall is most relevant
    assert any(f.id == "f-wall" for f in facts)
    # f-pnpm should NOT be top-ranked
    top_ids = [f.id for f in facts[:2]]
    assert "f-pnpm" not in top_ids


def test_retrieve_mixed_returns_both_and_timing(seeded_store):
    skills, facts, elapsed = retrieve_mixed(
        seeded_store, "Revit wall takeoff Tower-A metric",
        owner_user="founder", k_skills=3, k_facts=4,
        embedder=LexicalEmbedder(),
    )
    assert skills
    assert facts
    assert elapsed >= 0.0
    # Recency-blind result should still rank Revit skill #1
    assert skills[0].name == "revit_takeoff"


def test_retrieve_handles_empty_query(seeded_store):
    skills = retrieve_skills(
        seeded_store, "", owner_user="founder", k=2,
        embedder=LexicalEmbedder(),
    )
    # Empty query → fallback to most-recent skills (no panic)
    assert isinstance(skills, list)


def test_retrieval_advances_last_used_at(seeded_store):
    before = seeded_store.get_skill("sk-revit").last_used_at
    retrieve_skills(
        seeded_store, "wall takeoff", owner_user="founder", k=1,
        embedder=LexicalEmbedder(),
    )
    after = seeded_store.get_skill("sk-revit").last_used_at
    # last_used_at must have advanced (reconsolidation signal)
    if before is None:
        assert after is not None
    else:
        assert after > before
