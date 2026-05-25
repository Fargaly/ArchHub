"""Tests for personal_brain.server tool functions.

Tool functions are tested directly (without FastMCP transport) — the
transport layer is shallow and adds little to test. FastMCP integration
is verified via MCP Inspector in the slice-1 acceptance demo.
"""
from __future__ import annotations

from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    SecretRef,
    Skill,
    WiringAnnounceRequest,
    WiringEntry,
    WriteOp,
    WriteOpType,
)
from personal_brain.server import (
    announce_wiring,
    apply_write,
    make_context_payload,
    queue_skill_mint,
)
from personal_brain.storage import BrainStore

from datetime import datetime, timezone


def _prov():
    return Provenance(
        contributing_agent="claude-sonnet-4.7",
        contributing_user="founder",
        created_at=datetime.now(timezone.utc),
    )


def _store_with_seeded_skills():
    s = BrainStore.open(":memory:")
    s.upsert_skill(Skill(
        id="sk-1",
        name="revit_takeoff",
        description=(
            "Extract wall, floor, room counts and areas from the active "
            "Revit document and return as a structured table for QTO."
        ),
        triggers=["wall count", "takeoff"],
        requires_mcps=["revit-mcp"],
        body="# Revit takeoff\nrevit_info → revit_execute_csharp → summarise",
        examples=[{"input": "wall count", "output": "247"}],
        owner_user="founder",
        provenance=_prov(),
    ))
    s.upsert_skill(Skill(
        id="sk-2",
        name="notion_summarise",
        description=(
            "Read a Notion page by URL or id and produce a 5-bullet "
            "executive summary saved back to the same workspace as a child page."
        ),
        triggers=["summarize notion", "notion summary"],
        requires_mcps=["notion-mcp"],
        body="# Notion summarise\n1. fetch\n2. summarise\n3. create_page",
        examples=[{"input": "summarize notion page", "output": "summary"}],
        owner_user="founder",
        provenance=_prov(),
    ))
    s.write_fragment(Fragment(
        id="f-1", kind=FragmentKind.FACT, text="user prefers metric units",
        owner_user="founder", provenance=_prov(),
    ))
    s.write_fragment(Fragment(
        id="f-2", kind=FragmentKind.FACT,
        text="Tower-A wall type is Generic-200mm",
        owner_user="founder", provenance=_prov(),
    ))
    return s


def test_context_returns_relevant_skills_and_facts():
    store = _store_with_seeded_skills()
    try:
        resp = make_context_payload(
            store=store,
            prompt="Give me the wall takeoff for Tower-A",
            owner_user="founder",
        )
        assert resp.skills, "expected at least one skill retrieved"
        names = {s.name for s in resp.skills}
        assert "revit_takeoff" in names
        assert resp.retrieval_ms >= 0.0
        assert "<brain_context>" in resp.injection
        assert "revit_takeoff" in resp.injection
        assert "Tower-A" in resp.injection or "wall" in resp.injection.lower()
    finally:
        store.close()


def test_context_logs_access():
    store = _store_with_seeded_skills()
    try:
        make_context_payload(
            store=store,
            prompt="Tower-A walls metric",
            owner_user="founder",
        )
        log = store.access_log_for("f-1")
        log2 = store.access_log_for("f-2")
        assert any(row["purpose"] == "brain.context" for row in log + log2), \
            "context retrieval must log access (arXiv 2505.18279)"
    finally:
        store.close()


def test_write_ops_apply():
    store = BrainStore.open(":memory:")
    try:
        f = Fragment(
            id="w-1", kind=FragmentKind.FACT, text="firm uses pnpm",
            owner_user="founder", provenance=_prov(),
        )
        ops = [WriteOp(op=WriteOpType.ADD, fragment=f)]
        resp = apply_write(store=store, ops=ops)
        assert resp.fragments_added == 1
        assert resp.ops_applied == 1
        assert store.count_fragments() == 1
    finally:
        store.close()


def test_skill_mint_persists_trace_and_returns_proposal():
    store = BrainStore.open(":memory:")
    try:
        trace = {
            "user_message": "Push the figma component spec to Code Connect",
            "trace_id": "tr-1",
            "tool_calls": [
                {"name": "figma_get_design_context", "status": "ok"},
                {"name": "gh_pr_create", "status": "ok"},
            ],
            "outcome": "success",
        }
        result = queue_skill_mint(
            store=store,
            trace=trace,
            outcome="success",
            owner_user="founder",
            contributing_agent="claude-sonnet-4.7",
            session_id="sess-42",
        )
        assert result.queued
        assert result.proposed_name
        assert result.novelty_score >= 0.0
        assert result.success_score == 1.0
        # Trace fragment persisted with kind=trace
        all_frags = store.search_fragments("figma", k=5)
        assert any(f.kind == FragmentKind.TRACE for f in all_frags)
    finally:
        store.close()


def test_skill_mint_below_floor_not_queued():
    store = BrainStore.open(":memory:")
    try:
        trace = {
            "user_message": "open browser",
            "tool_calls": [{"name": "navigate", "status": "ok"}],  # only 1
            "outcome": "success",
        }
        result = queue_skill_mint(
            store=store, trace=trace, outcome="success",
            owner_user="founder", contributing_agent="claude-sonnet-4.7",
        )
        assert not result.queued
        assert "below mint floor" in result.reason
    finally:
        store.close()


def test_skill_mint_failure_outcome_not_queued():
    store = BrainStore.open(":memory:")
    try:
        result = queue_skill_mint(
            store=store, trace={"tool_calls": []}, outcome="failed",
            owner_user="founder", contributing_agent="gpt-5",
        )
        assert not result.queued
        assert "no mint" in result.reason
    finally:
        store.close()


def test_wiring_announce_registers_entries():
    store = BrainStore.open(":memory:")
    try:
        req = WiringAnnounceRequest(
            device_id="laptop-1",
            entries=[
                WiringEntry(name="revit-mcp", kind="mcp_server",
                             endpoint="http://localhost:48884",
                             device_id="laptop-1"),
                WiringEntry(name="notion-mcp", kind="mcp_server",
                             endpoint="https://api.notion.com",
                             device_id="laptop-1"),
            ],
            secret_refs=[
                SecretRef(ref="op://personal/notion/token",
                           resolver="1password", owner_user="founder"),
            ],
            cwd="/home/founder/some-project",
            git_remote="git@github.com:founder/some-project.git",
        )
        resp = announce_wiring(store=store, req=req, owner_user="founder")
        assert resp.registered == 2
        assert resp.scope_hint  # one of the Scope values
        entries = store.list_wiring(device_id="laptop-1")
        assert len(entries) == 2
        refs = store.list_secret_refs("founder")
        assert len(refs) == 1
    finally:
        store.close()


def test_scope_filter_in_context_excludes_other_users_private():
    store = BrainStore.open(":memory:")
    try:
        # founder's private fact
        store.write_fragment(Fragment(
            id="founder-private", kind=FragmentKind.FACT,
            text="founder secret note about Tower-A",
            scope=Scope.USER, owner_user="founder", provenance=_prov(),
        ))
        # teammate's private fact (same SCOPE=user but different owner)
        store.write_fragment(Fragment(
            id="teammate-private", kind=FragmentKind.FACT,
            text="teammate secret note about Tower-A",
            scope=Scope.USER, owner_user="teammate", provenance=_prov(),
        ))
        resp = make_context_payload(
            store=store, prompt="Tower-A note", owner_user="founder",
        )
        fact_ids = {f.id for f in resp.facts}
        assert "founder-private" in fact_ids
        assert "teammate-private" not in fact_ids, \
            "user-scope facts must be owner-filtered (arXiv 2505.18279)"
    finally:
        store.close()
