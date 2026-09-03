"""Claude Code CLI provider — stream-json event parsing (AgDR-0021 +
founder demand 2026-06-01: "see everything in nodes — REASONING,
tool-calls").

The `claude -p --output-format stream-json --verbose` invocation emits a
JSONL event stream. `ClaudeCliClient._parse_stream` turns it into the
provider-client contract:
  • assistant `text` blocks → on_chunk (streamed) + final text
  • `thinking` blocks + `post_turn_summary` → on_reasoning frames
  • MCP `tool_use` + matching `tool_result` → tool_calls_log
  • `result` event → final text + usage; is_error raises

These tests pin the parser against canned event streams — no subprocess,
no network, no `claude` binary required (so they run in CI too).
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
def client():
    """A ClaudeCliClient instance WITHOUT touching __init__ (which needs
    the real `claude` binary on PATH). We only exercise the pure
    `_parse_stream` method, so build a bare instance."""
    from llm_providers.claude_cli_client import ClaudeCliClient
    return ClaudeCliClient.__new__(ClaudeCliClient)


def _jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


# ─── text streaming ──────────────────────────────────────────────────


def test_parse_stream_streams_text_and_returns_final(client):
    raw = _jsonl(
        {"type": "system", "subtype": "init", "mcp_servers": []},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "Hello world",
         "usage": {"input_tokens": 5, "output_tokens": 2}},
    )
    chunks: list[str] = []
    out = client._parse_stream(raw, chunks.append, lambda _s: None)
    assert out["type"] == "final"
    assert out["text"] == "Hello world"
    # Streamed the two text blocks, did NOT re-emit the final blob.
    assert chunks == ["Hello ", "world"]
    assert out["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}


def test_parse_stream_emits_final_once_when_nothing_streamed(client):
    """A turn whose text only arrives in the `result` event (no assistant
    text blocks) still emits exactly once via on_chunk."""
    raw = _jsonl(
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "just the result"},
    )
    chunks: list[str] = []
    out = client._parse_stream(raw, chunks.append, lambda _s: None)
    assert out["text"] == "just the result"
    assert chunks == ["just the result"]


# ─── reasoning surfacing ─────────────────────────────────────────────


def test_parse_stream_surfaces_thinking_as_reasoning(client):
    raw = _jsonl(
        {"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "Let me work through this."},
            {"type": "text", "text": "Answer."},
        ]}},
        {"type": "result", "is_error": False, "result": "Answer."},
    )
    reasoning: list[str] = []
    client._parse_stream(raw, lambda _p: None, reasoning.append)
    assert "Let me work through this." in reasoning


def test_parse_stream_surfaces_post_turn_summary_as_reasoning(client):
    raw = _jsonl(
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "144"},
        ]}},
        {"type": "system", "subtype": "post_turn_summary",
         "status_detail": "calculated 12 x 12 = 144"},
        {"type": "result", "is_error": False, "result": "144"},
    )
    reasoning: list[str] = []
    client._parse_stream(raw, lambda _p: None, reasoning.append)
    assert "calculated 12 x 12 = 144" in reasoning


# ─── tool-call capture ───────────────────────────────────────────────


def test_parse_stream_captures_tool_use_and_result(client):
    raw = _jsonl(
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_1",
             "name": "mcp__archhub__revit__list_documents",
             "input": {"foo": "bar"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_1",
             "content": "{\"ok\": true, \"docs\": [\"A.rvt\"]}"},
        ]}},
        {"type": "result", "is_error": False, "result": "Found A.rvt"},
    )
    reasoning: list[str] = []
    out = client._parse_stream(raw, lambda _p: None, reasoning.append)
    log = out["tool_calls_log"]
    assert len(log) == 1
    assert log[0]["name"] == "mcp__archhub__revit__list_documents"
    assert log[0]["input"] == {"foo": "bar"}
    # The matching tool_result was attached.
    assert log[0]["result"] == "{\"ok\": true, \"docs\": [\"A.rvt\"]}"
    # The call surfaced as a reasoning frame with a humanised name.
    assert any("revit.list_documents" in r for r in reasoning)


# ─── error handling ──────────────────────────────────────────────────


def test_parse_stream_raises_on_error_result(client):
    raw = _jsonl(
        {"type": "result", "is_error": True,
         "subtype": "error_max_turns",
         "result": "hit the wall"},
    )
    with pytest.raises(RuntimeError) as ei:
        client._parse_stream(raw, lambda _p: None, lambda _s: None)
    assert "hit the wall" in str(ei.value)


def test_parse_stream_ignores_garbage_lines(client):
    """Non-JSON lines (stray stderr that leaked into stdout) are skipped,
    not fatal."""
    raw = "not json at all\n" + _jsonl(
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "ok"}]}},
        {"type": "result", "is_error": False, "result": "ok"},
    )
    chunks: list[str] = []
    out = client._parse_stream(raw, chunks.append, lambda _s: None)
    assert out["text"] == "ok"
