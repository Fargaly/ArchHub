"""Tests for app/memory_gate.py — Layer 5 enforcement (AgDR-0044 Slice 4).

Brain availability is mocked: BrainClient.is_available + .context + .write +
.skill_mint are stubbed so tests run with no real daemon.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make app/ importable
APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from memory_gate import (  # noqa: E402
    BrainClient,
    GateDecision,
    MemoryGate,
    MemoryTurnState,
    _collect_op_refs,
    _strip_secrets,
    _summarise_result,
    _synthesize_fragment,
)


# ─────────────────────── helpers ───────────────────────────────────────


def _make_gate_with_mock_brain(
    *,
    available: bool = True,
    context_payload=None,
    write_resp=None,
    mint_resp=None,
) -> MemoryGate:
    client = MagicMock(spec=BrainClient)
    client.is_available.return_value = available
    client.context.return_value = context_payload
    client.write.return_value = write_resp or {"ops_applied": 1, "fragments_added": 1}
    client.skill_mint.return_value = mint_resp or {"queued": True, "novelty_score": 0.5}
    client.wiring_announce.return_value = {"registered": 0}
    # Tests pass mocks directly; bypass the resilience wrapper so the
    # MagicMock's stubbed return values are seen unchanged.
    return MemoryGate(client=client, resilient=False)


# ─────────────────────── unit ──────────────────────────────────────────


def test_collect_op_refs_walks_nested_args():
    args = {
        "secret": "op://personal/notion/token",
        "nested": {
            "key": "vault://aws/prod/key",
            "list": ["wcm://archhub/license", "plain-string"],
        },
        "plain": "no-secret",
    }
    refs = _collect_op_refs(args)
    assert set(refs) == {
        "op://personal/notion/token",
        "vault://aws/prod/key",
        "wcm://archhub/license",
    }


def test_strip_secrets_replaces_refs_and_key_prefixes():
    args = {
        "token": "op://x/y/z",
        "api_key": "sk-abcdef123",
        "github_token": "ghp_abcdef",
        "name": "regular-value",
    }
    clean = _strip_secrets(args)
    assert clean["token"] == "<secret>"
    assert clean["api_key"] == "<secret>"
    assert clean["github_token"] == "<secret>"
    assert clean["name"] == "regular-value"


def test_summarise_result_handles_kinds():
    assert _summarise_result(None) == "no result"
    assert _summarise_result(42) == "42"
    assert _summarise_result("hello") == "hello"
    assert "status=ok" in _summarise_result({"status": "ok"})
    assert "list[3]" in _summarise_result([1, 2, 3])


def test_synthesize_fragment_shape():
    frag = _synthesize_fragment(
        tool_name="revit_info",
        arguments={"foo": "bar", "secret": "op://x/y/z"},
        result={"status": "ok", "result": "Tower-A"},
        contributing_agent="claude-sonnet-4.7",
        owner_user="founder",
        session_id="s-1",
    )
    assert frag["kind"] == "fact"
    assert frag["subject"] == "revit_info"
    assert frag["owner_user"] == "founder"
    assert "Tower-A" in frag["object"] or "ok" in frag["text"]
    # provenance present
    assert frag["provenance"]["contributing_agent"] == "claude-sonnet-4.7"
    assert frag["provenance"]["session_id"] == "s-1"
    # secret in args was stripped before hashing the id
    assert "op://" not in str(frag)


# ─────────────────────── gate flow ─────────────────────────────────────


def test_pre_prompt_brain_unavailable_returns_empty_injection():
    gate = _make_gate_with_mock_brain(available=False)
    state = MemoryTurnState()
    decision = gate.pre_prompt(state, user_message="hello", owner_user="founder")
    assert decision.allow
    assert decision.augmentation["injection"] == ""
    assert state.context_injected is False


def test_pre_prompt_with_brain_injects():
    payload = {
        "injection": "<brain_context>\n## skills\n- foo\n</brain_context>",
        "skills": [{"name": "foo"}],
        "facts": [],
        "secret_refs": [],
        "retrieval_ms": 12.3,
    }
    gate = _make_gate_with_mock_brain(available=True, context_payload=payload)
    state = MemoryTurnState()
    decision = gate.pre_prompt(state, user_message="do a thing", owner_user="founder")
    assert decision.allow
    assert "<brain_context>" in decision.augmentation["injection"]
    assert state.context_injected is True
    assert state.context_payload == payload


def test_pre_prompt_empty_message_short_circuits():
    gate = _make_gate_with_mock_brain(available=True)
    state = MemoryTurnState()
    decision = gate.pre_prompt(state, user_message="", owner_user="founder")
    assert decision.allow
    assert decision.reason == "empty prompt"
    # Brain context never even called
    gate.client.context.assert_not_called()


def test_pre_execute_collects_secret_refs():
    gate = _make_gate_with_mock_brain(available=True)
    state = MemoryTurnState()
    decision = gate.pre_execute(
        state,
        tool_name="notion_create_page",
        arguments={"token": "op://personal/notion/token", "title": "x"},
    )
    assert decision.allow
    assert decision.augmentation["secret_refs_to_resolve"] == ["op://personal/notion/token"]
    assert len(state.secret_resolutions) == 1
    assert state.secret_resolutions[0]["ref"] == "op://personal/notion/token"


def test_post_execute_writes_to_brain_on_success():
    gate = _make_gate_with_mock_brain(available=True)
    state = MemoryTurnState()
    gate.post_execute(
        state,
        tool_name="revit_info",
        arguments={"doc": "active"},
        result={"status": "ok", "result": "Tower-A.rvt"},
        status="ok",
        contributing_agent="claude-sonnet-4.7",
        owner_user="founder",
        session_id="s-1",
    )
    # brain.write was called with 1 ADD op
    gate.client.write.assert_called_once()
    args = gate.client.write.call_args.args
    ops = args[0] if args else gate.client.write.call_args.kwargs.get("ops")
    assert ops[0]["op"] == "add"
    assert ops[0]["fragment"]["subject"] == "revit_info"
    assert state.write_ops_emitted == 1
    assert state.tool_invocations[0]["name"] == "revit_info"


def test_post_execute_failure_skips_brain_write():
    gate = _make_gate_with_mock_brain(available=True)
    state = MemoryTurnState()
    gate.post_execute(
        state, tool_name="x", arguments={}, result=None, status="error",
        contributing_agent="claude", owner_user="founder",
    )
    # failed tool calls are recorded but not written to brain
    gate.client.write.assert_not_called()
    assert state.write_ops_emitted == 0
    # but the tool invocation still appears on the trace
    assert state.tool_invocations[0]["status"] == "error"


def test_post_execute_strips_secrets_from_trace():
    gate = _make_gate_with_mock_brain(available=True)
    state = MemoryTurnState()
    gate.post_execute(
        state,
        tool_name="github_create_pr",
        arguments={"pat": "ghp_abcdefghij", "title": "test"},
        result={"status": "ok"},
        status="ok",
        contributing_agent="gpt-5",
        owner_user="founder",
    )
    invocation = state.tool_invocations[0]
    assert invocation["args"]["pat"] == "<secret>"
    assert invocation["args"]["title"] == "test"


def test_stop_calls_skill_mint():
    gate = _make_gate_with_mock_brain(
        available=True,
        mint_resp={"queued": True, "novelty_score": 0.7, "proposed_name": "revit_flow"},
    )
    state = MemoryTurnState(session_id="s-42", trace_id="t-1")
    state.tool_invocations = [
        {"name": "revit_info", "status": "ok"},
        {"name": "revit_execute_csharp", "status": "ok"},
    ]
    result = gate.stop(
        state, outcome="success", contributing_agent="claude-sonnet-4.7",
        owner_user="founder",
    )
    assert result is not None
    assert result["queued"]
    gate.client.skill_mint.assert_called_once()
    kwargs = gate.client.skill_mint.call_args.kwargs
    assert kwargs["outcome"] == "success"
    assert kwargs["contributing_agent"] == "claude-sonnet-4.7"
    assert kwargs["session_id"] == "s-42"


def test_stop_brain_unavailable_returns_none():
    gate = _make_gate_with_mock_brain(available=False)
    state = MemoryTurnState()
    result = gate.stop(state, outcome="success", contributing_agent="x",
                        owner_user="founder")
    assert result is None
    gate.client.skill_mint.assert_not_called()


def test_full_turn_flow_brain_available():
    """End-to-end of a typical turn through all 4 hook points."""
    gate = _make_gate_with_mock_brain(
        available=True,
        context_payload={"injection": "<brain_context>...</brain_context>",
                         "skills": [], "facts": [], "secret_refs": []},
    )
    state = MemoryTurnState(session_id="s-1", trace_id="t-1")

    # 1. pre-prompt
    d1 = gate.pre_prompt(state, user_message="summarize Tower-A walls",
                         owner_user="founder")
    assert d1.augmentation["injection"]

    # 2. pre-execute → 3. post-execute (twice)
    for tool_name in ("revit_info", "revit_execute_csharp"):
        d2 = gate.pre_execute(state, tool_name=tool_name, arguments={})
        assert d2.allow
        gate.post_execute(state, tool_name=tool_name, arguments={},
                          result={"status": "ok"}, status="ok",
                          contributing_agent="claude-sonnet-4.7",
                          owner_user="founder", session_id="s-1")

    # 4. stop
    mint = gate.stop(state, outcome="success",
                     contributing_agent="claude-sonnet-4.7",
                     owner_user="founder")
    assert mint is not None

    # State sanity
    assert len(state.tool_invocations) == 2
    assert state.write_ops_emitted == 2
    assert state.context_injected


def test_full_turn_flow_brain_unavailable_does_not_break():
    """Brain down = no exceptions, gate stays advisory, turn proceeds."""
    gate = _make_gate_with_mock_brain(available=False)
    state = MemoryTurnState(session_id="s-1")

    d1 = gate.pre_prompt(state, user_message="hello", owner_user="founder")
    assert d1.allow
    assert d1.augmentation["injection"] == ""

    d2 = gate.pre_execute(state, tool_name="x", arguments={})
    assert d2.allow

    # post_execute swallows
    gate.post_execute(state, tool_name="x", arguments={}, result=None,
                      status="ok", contributing_agent="x",
                      owner_user="founder")
    # no exception; brain.write never called (because is_available False)
    gate.client.write.assert_not_called()

    # stop returns None
    assert gate.stop(state, outcome="success",
                      contributing_agent="x", owner_user="founder") is None
