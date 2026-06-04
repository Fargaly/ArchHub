"""Composer turn → ai.plan node persistence (AgDR-0021 + founder demand
2026-06-01: "type in ArchHub → real AI responds → becomes a NODE").

`bridge._persist_chat_plan` writes one ai.plan record per Composer chat
turn — prompt + reasoning + tool-calls + result — so the turn is an
inspectable, replayable canvas artefact (the ai.plan History modal +
Inspector read it back via get_plan_history), not just a transient chat
bubble.

These tests pin the persistence shape + round-trip through the public
bridge slot. No LLM call — we drive the helper directly with a captured
turn, exactly as send_chat_history's runner does after router.complete.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


@pytest.fixture
def bridge():
    from bridge import ArchHubBridge
    return ArchHubBridge()


@pytest.fixture
def use_tmp_project(monkeypatch, tmp_path):
    """Point default_project_dir at a tmp dir so the persisted record +
    the read-back slot agree, without touching the real %LOCALAPPDATA%."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))
    return tmp_path


def test_persist_chat_plan_writes_record(bridge, use_tmp_project):
    bridge._persist_chat_plan(
        prompt="What is ArchHub?",
        model="claude_cli:sonnet",
        result="A graph-first AI workspace for AEC.",
        reasoning=["thought about the question", "answered concisely"],
        tool_calls=[],
        routing_note="local Claude Code · no API credit",
    )
    raw = bridge.get_plan_history("", 10)
    out = json.loads(raw)
    assert out["count"] == 1, out
    rec = out["records"][0]
    assert rec["prompt"] == "What is ArchHub?"
    assert rec["model"] == "claude_cli:sonnet"
    assert rec["result"] == "A graph-first AI workspace for AEC."
    assert rec["reasoning"] == ["thought about the question",
                                 "answered concisely"]
    assert rec["status"] == "ok"
    assert rec["source"] == "composer_chat"
    assert rec["routing_note"] == "local Claude Code · no API credit"


def test_persist_chat_plan_records_tool_calls(bridge, use_tmp_project):
    bridge._persist_chat_plan(
        prompt="List open Revit docs",
        model="claude_cli:sonnet",
        result="Found 1 document: A.rvt",
        reasoning=["called the revit tool"],
        tool_calls=[{
            "tool_name": "revit.list_documents",
            "arguments": {},
            "status": "ok",
            "result": {"ok": True, "docs": ["A.rvt"]},
        }],
        routing_note="",
    )
    out = json.loads(bridge.get_plan_history("", 10))
    rec = out["records"][0]
    # `plan` is the canonical tool-invocation list the JSX node renders.
    assert len(rec["plan"]) == 1
    assert rec["plan"][0]["tool_name"] == "revit.list_documents"
    assert rec["plan"][0]["status"] == "ok"


def test_persist_chat_plan_deterministic_id_replays_slot(bridge,
                                                          use_tmp_project):
    """Same prompt+model → same plan_id (matches the ai.plan executor
    contract), so a re-ask overwrites rather than duplicating."""
    for result in ("first answer", "second answer"):
        bridge._persist_chat_plan(
            prompt="same prompt", model="claude_cli:sonnet",
            result=result, reasoning=[], tool_calls=[], routing_note="",
        )
    out = json.loads(bridge.get_plan_history("", 10))
    assert out["count"] == 1  # one slot, overwritten
    assert out["records"][0]["result"] == "second answer"


def test_persist_chat_plan_empty_turn_marks_status(bridge, use_tmp_project):
    """A turn with no result + no tools persists with status 'empty' so
    the History view shows it honestly rather than dropping it."""
    bridge._persist_chat_plan(
        prompt="…", model="auto", result="",
        reasoning=[], tool_calls=[], routing_note="",
    )
    out = json.loads(bridge.get_plan_history("", 10))
    assert out["count"] == 1
    assert out["records"][0]["status"] == "empty"


def test_persist_chat_plan_never_raises(bridge, monkeypatch):
    """Persistence is best-effort — a failure to resolve the project dir
    must NOT raise (the chat bubble already rendered; the record is the
    durable extra)."""
    import speckle_wire

    def _boom():
        raise RuntimeError("no project dir")

    monkeypatch.setattr(speckle_wire, "default_project_dir", _boom)
    # Should swallow the error, not propagate.
    bridge._persist_chat_plan(
        prompt="x", model="m", result="y",
        reasoning=[], tool_calls=[], routing_note="",
    )
