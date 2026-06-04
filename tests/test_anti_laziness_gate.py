"""Tests for the anti-laziness Stop-hook gate (transcript parsing + verdict).

The brain policy itself is tested in personal-brain-mcp/tests/test_diligence.py.
Here we pin the HOOK's job: turn a Claude Code transcript into evidence
(last message, proof signals, touched files) and emit a block/allow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
BRAIN_SRC = REPO / "personal-brain-mcp" / "src"
for p in (str(TOOLS), str(BRAIN_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import anti_laziness_gate as gate  # noqa: E402


def _assistant_text(t):
    return {"type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}


def _assistant_tool(name, inp):
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "name": name, "input": inp}]}}


def test_extract_last_message_and_no_signals():
    events = [
        {"type": "user", "message": {"role": "user", "content": "do it"}},
        _assistant_text("All done. The feature is shipped."),
    ]
    ev = gate.extract_signals(events)
    assert ev["last_message"] == "All done. The feature is shipped."
    assert not any(ev["session_signals"].values())
    assert ev["touched_files"] == []


def test_extract_proof_signals_and_touched_files():
    events = [
        _assistant_tool("Write", {"file_path": "app/x.py"}),
        _assistant_tool("Bash", {"command": "python -m pytest tests/ -q"}),
        _assistant_tool("Bash", {"command": "curl -s http://127.0.0.1:8473/mcp"}),
        _assistant_text("Done. Tests green."),
    ]
    ev = gate.extract_signals(events)
    sig = ev["session_signals"]
    assert sig["wrote_files"] is True
    assert sig["ran_tests"] is True
    assert sig["ran_curl"] is True
    assert "app/x.py" in ev["touched_files"]
    assert ev["last_message"] == "Done. Tests green."


def test_local_verdict_blocks_lazy():
    ev = {
        "last_message": "All done. Shipped and fully working.",
        "touched_files": [],
        "session_signals": {"ran_tests": False, "wrote_files": False},
        "file_contents": {},
    }
    v = gate.evaluate_local(ev)
    assert v.get("verdict") == "block"
    assert "CLAIM_WITHOUT_PROOF" in [x["code"] for x in v["violations"]]


def test_local_verdict_allows_proven():
    ev = {
        "last_message": "Done. Endpoint returns 200, tests green.",
        "touched_files": ["app/x.py"],
        "session_signals": {"ran_tests": True, "wrote_files": True},
        "file_contents": {"app/x.py": "def x():\n    return 1\n"},
    }
    v = gate.evaluate_local(ev)
    assert v.get("verdict") == "allow", v


def test_main_blocks_lazy_transcript(tmp_path, monkeypatch, capsys):
    tpath = tmp_path / "lazy.jsonl"
    tpath.write_text("\n".join(json.dumps(e) for e in [
        {"type": "user", "message": {"role": "user", "content": "build"}},
        _assistant_text("All done. Shipped and fully working."),
    ]), encoding="utf-8")
    payload = {"session_id": "t-lazy", "transcript_path": str(tpath),
               "cwd": str(tmp_path), "stop_hook_active": False}
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps(payload)))
    # Force the offline path so the test never depends on a running daemon.
    monkeypatch.setattr(gate, "call_brain", lambda ev: None)
    rc = gate.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert '"decision": "block"' in out
    gate.reset_block_count("t-lazy")


def test_main_allows_diligent_transcript(tmp_path, monkeypatch, capsys):
    tpath = tmp_path / "ok.jsonl"
    tpath.write_text("\n".join(json.dumps(e) for e in [
        _assistant_tool("Bash", {"command": "python -m pytest -q"}),
        _assistant_text("Done. Tests green."),
    ]), encoding="utf-8")
    payload = {"session_id": "t-ok", "transcript_path": str(tpath),
               "cwd": str(tmp_path), "stop_hook_active": False}
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps(payload)))
    monkeypatch.setattr(gate, "call_brain", lambda ev: None)
    rc = gate.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == ""   # allow → no stdout


class _Stdin:
    def __init__(self, data: str):
        self._data = data

    def read(self) -> str:
        return self._data
