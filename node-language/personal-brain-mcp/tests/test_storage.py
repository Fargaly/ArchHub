"""Tests for personal_brain.storage.BrainStore.

Slice 1 acceptance: in-memory store opens, schema applies, fragments +
skills + wiring + secrets round-trip, FTS5 search returns hits, access
log records.
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
    SecretRef,
    Skill,
    Visibility,
    WiringEntry,
    WriteOp,
    WriteOpType,
)
from personal_brain.storage import BrainStore


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _prov(user="founder", agent="claude-sonnet-4.7"):
    return Provenance(
        contributing_agent=agent,
        contributing_user=user,
        created_at=datetime.now(timezone.utc),
    )


def test_fragment_roundtrip(store):
    f = Fragment(
        id="frag-1",
        kind=FragmentKind.FACT,
        text="user prefers metric units",
        subject="user",
        predicate="prefers",
        object="metric",
        scope=Scope.USER,
        visibility=Visibility.PRIVATE,
        owner_user="founder",
        confidence=Confidence.EXTRACTED,
        provenance=_prov(),
    )
    inserted = store.write_fragment(f)
    assert inserted
    fetched = store.get_fragment("frag-1")
    assert fetched is not None
    assert fetched.text == "user prefers metric units"
    assert fetched.scope == Scope.USER
    assert fetched.provenance.contributing_agent == "claude-sonnet-4.7"


def test_fragment_fts_search(store):
    for i, txt in enumerate(
        [
            "user prefers metric units",
            "Tower-A wall type is Generic-200mm",
            "firm template is ArchHub-Studio-v2",
            "user uses pnpm not npm",
        ]
    ):
        store.write_fragment(
            Fragment(
                id=f"f-{i}",
                kind=FragmentKind.FACT,
                text=txt,
                owner_user="founder",
                provenance=_prov(),
            )
        )
    hits = store.search_fragments("Tower wall", owner_user="founder", k=5)
    texts = [h.text for h in hits]
    assert any("Tower-A" in t for t in texts)


def test_fragment_touch_reinforcement(store):
    f = Fragment(
        id="frag-touch",
        kind=FragmentKind.FACT,
        text="user uses Revit 2024",
        owner_user="founder",
        provenance=_prov(),
    )
    store.write_fragment(f)
    store.touch_fragment("frag-touch", success=True)
    store.touch_fragment("frag-touch", success=True)
    fetched = store.get_fragment("frag-touch")
    assert fetched.success_count == 2
    assert fetched.last_used_at is not None


def test_skill_upsert_and_search(store):
    s = Skill(
        id="skill-1",
        name="revit_takeoff",
        description=(
            "Extract wall, floor, room counts and areas from the active "
            "Revit document and return as a structured table for QTO."
        ),
        triggers=["wall count", "takeoff", "schedule", "QTO"],
        requires_mcps=["revit-mcp"],
        body="# Revit takeoff\n1. revit_info\n2. revit_execute_csharp(...)\n3. summarise",
        examples=[{"input": "wall count for Tower-A", "output": "247 walls"}],
        owner_user="founder",
        provenance=_prov(),
    )
    inserted = store.upsert_skill(s)
    assert inserted
    hits = store.search_skills("takeoff", owner_user="founder", k=3)
    assert any(h.name == "revit_takeoff" for h in hits)


def test_skill_description_too_short_rejected_by_pydantic():
    with pytest.raises(Exception):
        Skill(
            id="bad",
            name="bad",
            description="too short",  # < 80 chars
            body="x",
            owner_user="founder",
            provenance=_prov(),
        )


def test_wiring_upsert_and_list(store):
    e1 = WiringEntry(
        name="revit-mcp", kind="mcp_server",
        endpoint="http://localhost:48884",
        capabilities=["revit_info", "revit_execute_csharp"],
        device_id="laptop-1",
    )
    e2 = WiringEntry(
        name="notion-mcp", kind="mcp_server",
        endpoint="https://api.notion.com",
        capabilities=["create_page", "search"],
        device_id="laptop-1",
    )
    assert store.upsert_wiring(e1)
    assert store.upsert_wiring(e2)
    entries = store.list_wiring(device_id="laptop-1")
    names = sorted(e.name for e in entries)
    assert names == ["notion-mcp", "revit-mcp"]


def test_secret_ref_stores_ref_only(store):
    r = SecretRef(
        ref="op://personal/notion/token",
        resolver="1password",
        description="Notion API token",
        owner_user="founder",
    )
    assert store.upsert_secret_ref(r)
    refs = store.list_secret_refs("founder")
    assert len(refs) == 1
    assert refs[0].ref == "op://personal/notion/token"
    # NO value ever stored — verify by inspecting raw row
    row = store._conn.execute(
        "SELECT * FROM secret_refs WHERE ref = ?",
        ("op://personal/notion/token",),
    ).fetchone()
    cols = row.keys()
    assert "value" not in cols
    assert "secret" not in cols


def test_access_log_records_reads(store):
    f = Fragment(
        id="audit-1",
        kind=FragmentKind.FACT,
        text="firm Q3 revenue exceeded target",
        scope=Scope.FIRM,
        visibility=Visibility.SHARED_COMPANY,
        owner_user="founder",
        provenance=_prov(),
    )
    store.write_fragment(f)
    store.log_access("founder", "audit-1", purpose="brain.context")
    store.log_access("teammate", "audit-1", purpose="brain.context")
    log = store.access_log_for("audit-1")
    assert len(log) == 2
    readers = {row["reader_user"] for row in log}
    assert readers == {"founder", "teammate"}


def test_write_ops_batch(store):
    f1 = Fragment(
        id="op-1", kind=FragmentKind.FACT, text="fact one",
        owner_user="founder", provenance=_prov(),
    )
    f2 = Fragment(
        id="op-2", kind=FragmentKind.FACT, text="fact two",
        owner_user="founder", provenance=_prov(),
    )
    ops = [
        WriteOp(op=WriteOpType.ADD, fragment=f1),
        WriteOp(op=WriteOpType.ADD, fragment=f2),
        WriteOp(op=WriteOpType.NOOP),
    ]
    resp = store.apply_write_ops(ops)
    assert resp.ops_applied == 3
    assert resp.fragments_added == 2
    assert resp.fragments_noop == 1
    assert resp.errors == []
    assert store.count_fragments() == 2


def test_scope_filter_user_isolation(store):
    store.write_fragment(Fragment(
        id="u-private", kind=FragmentKind.FACT, text="my private note",
        scope=Scope.USER, owner_user="founder", provenance=_prov(),
    ))
    store.write_fragment(Fragment(
        id="g-canon", kind=FragmentKind.FACT, text="my private note global",
        scope=Scope.GLOBAL, owner_user="other_user", provenance=_prov(),
    ))
    # Scope filter = USER + GLOBAL; owner_user='founder' — user scope must be
    # filtered to owner only.
    hits = store.search_fragments(
        "my private",
        scope_filter=[Scope.USER, Scope.GLOBAL],
        owner_user="founder",
    )
    ids = {h.id for h in hits}
    assert "u-private" in ids
    assert "g-canon" in ids  # global visible to all


def test_health_counts(store):
    assert store.count_fragments() == 0
    assert store.count_skills() == 0
    store.write_fragment(Fragment(
        id="x", kind=FragmentKind.FACT, text="x", owner_user="founder",
        provenance=_prov(),
    ))
    assert store.count_fragments() == 1
