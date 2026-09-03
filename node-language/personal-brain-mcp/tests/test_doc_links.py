"""Tests for BrainStore.doc_links — Track C (Documentation track).

Per the Content Ecosystem plan, section 4. The doc_links method is
scaffolded (not production-grade backlinks); these tests pin the
honest contract: empty store returns empty lists; two docs that
mention each other return each other; the freshness score is bounded
to 0.0–1.0.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import BrainStore


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _prov(user: str = "founder") -> Provenance:
    return Provenance(
        contributing_agent="claude-opus-4.7",
        contributing_user=user,
        created_at=datetime.now(timezone.utc),
    )


def _doc_fragment(
    slug: str,
    text: str,
    *,
    deps: list[str] | None = None,
    freshness: float | None = None,
) -> Fragment:
    extra: dict = {"deps": deps or []}
    if freshness is not None:
        extra["freshness_score"] = freshness
    return Fragment(
        id=f"doc:{slug}",
        kind=FragmentKind.DOCUMENT,
        text=text,
        subject=f"docs/{slug}.md",
        predicate="document_index",
        object=slug,
        scope=Scope.USER,
        visibility=Visibility.PRIVATE,
        owner_user="founder",
        confidence=Confidence.EXTRACTED,
        provenance=_prov(),
        extra=extra,
    )


def test_empty_store_returns_empty_lists(store):
    """No documents indexed → backlinks/forward_links both empty."""
    out = store.doc_links("docs/ROADMAP.md")
    assert out["ok"] is True
    assert out["file"] == "docs/ROADMAP.md"
    assert out["backlinks"] == []
    assert out["forward_links"] == []
    assert 0.0 <= out["freshness_score"] <= 1.0
    assert "note" in out  # honesty marker per ANTI-LIE


def test_two_docs_linking_each_other(store):
    """Doc A's text mentions Doc B's path → B's backlinks contain A,
    and vice versa. forward_links comes from extra.deps."""
    a = _doc_fragment(
        "ROADMAP",
        "See docs/STRATEGY.md for vision details.",
        deps=["docs/STRATEGY.md"],
        freshness=0.9,
    )
    b = _doc_fragment(
        "STRATEGY",
        "Tracked roadmap items live in docs/ROADMAP.md.",
        deps=["docs/ROADMAP.md"],
        freshness=0.7,
    )
    store.write_fragment(a)
    store.write_fragment(b)

    out_a = store.doc_links("docs/ROADMAP.md")
    out_b = store.doc_links("docs/STRATEGY.md")

    # ROADMAP is mentioned in STRATEGY.text → STRATEGY shows up as a
    # backlink to ROADMAP.
    assert "STRATEGY" in out_a["backlinks"]
    # And conversely.
    assert "ROADMAP" in out_b["backlinks"]

    # Forward links read from extra.deps on the doc itself.
    assert "docs/STRATEGY.md" in out_a["forward_links"]
    assert "docs/ROADMAP.md" in out_b["forward_links"]

    # Freshness honoured.
    assert out_a["freshness_score"] == pytest.approx(0.9)
    assert out_b["freshness_score"] == pytest.approx(0.7)


def test_freshness_score_bounded_0_to_1(store):
    """Freshness score is always clamped to [0.0, 1.0] even if the
    stored extra.freshness_score is out of band."""
    # Stored as 1.5 → clamped to 1.0
    over = _doc_fragment("OVER", "content", freshness=1.5)
    # Stored as -0.3 → clamped to 0.0
    under = _doc_fragment("UNDER", "content", freshness=-0.3)
    # Stored as 0.42 → unchanged
    mid = _doc_fragment("MID", "content", freshness=0.42)
    # No freshness → default 0.5
    no_fresh = _doc_fragment("NOFRESH", "content")

    for f in (over, under, mid, no_fresh):
        store.write_fragment(f)

    assert store.doc_links("docs/OVER.md")["freshness_score"] == 1.0
    assert store.doc_links("docs/UNDER.md")["freshness_score"] == 0.0
    assert store.doc_links("docs/MID.md")["freshness_score"] == pytest.approx(0.42)
    out_nf = store.doc_links("docs/NOFRESH.md")
    assert 0.0 <= out_nf["freshness_score"] <= 1.0
    assert out_nf["freshness_score"] == 0.5
