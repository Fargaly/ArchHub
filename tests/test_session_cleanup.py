"""Stub-session cleanup (post-v1.0 fix).

Pre-v1.0 autosave wrote files with no _messages, no parameters, no
chain — sessions that looked saved in the THREADS rail but loaded
an empty chat. After the fix:
  * list_sessions() filters them out by default
  * cleanup_empty_sessions() returns count purged
  * include_empty=True still lets tooling see everything
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    """Redirect session_io.SESSIONS_DIR to a tmp dir for the test."""
    sd = tmp_path / "sessions"
    sd.mkdir(parents=True)
    import session_io
    monkeypatch.setattr(session_io, "SESSIONS_DIR", sd)
    return sd


def _write_stub(sd: Path, name: str) -> Path:
    """Write a pre-fix empty stub session."""
    p = sd / f"{name}.archhub-session.json"
    p.write_text(json.dumps({
        "_name": name, "_saved_at": "2026-05-01T00:00:00",
        "parameters": [], "chain": [],
        # no _messages key — exactly the bug case
    }), encoding="utf-8")
    return p


def _write_real(sd: Path, name: str, msgs: int = 2) -> Path:
    """Write a post-fix session with actual chat content.

    Must include at least one ASSISTANT message with non-empty content,
    otherwise the v1.0 tighter filter treats it as a stub (which is
    correct — a chat with only user messages and no assistant reply
    means the LLM call never produced anything)."""
    p = sd / f"{name}.archhub-session.json"
    payload_msgs = []
    for i in range(max(1, msgs - 1)):
        payload_msgs.append({"role": "user", "content": f"msg {i}"})
    payload_msgs.append(
        {"role": "assistant", "content": "the reply"}
    )
    p.write_text(json.dumps({
        "_name": name, "_saved_at": "2026-05-10T00:00:00",
        "parameters": [], "chain": [],
        "_messages": payload_msgs,
    }), encoding="utf-8")
    return p


def _write_user_only(sd: Path, name: str) -> Path:
    """A chat that crashed mid-turn: user message saved, assistant
    empty. Counts as a stub by the new filter."""
    p = sd / f"{name}.archhub-session.json"
    p.write_text(json.dumps({
        "_name": name, "_saved_at": "2026-05-10T00:00:00",
        "parameters": [], "chain": [],
        "_messages": [
            {"role": "user", "content": "ping"},
            {"role": "assistant", "content": ""},
        ],
    }), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
class TestListSessionsFilter:
    def test_empty_stubs_hidden_by_default(self, sessions_dir):
        _write_stub(sessions_dir, "stub1")
        _write_stub(sessions_dir, "stub2")
        from session_io import list_sessions
        assert list_sessions() == []

    def test_real_sessions_show(self, sessions_dir):
        _write_real(sessions_dir, "real_session")
        from session_io import list_sessions
        rows = list_sessions()
        assert len(rows) == 1
        assert rows[0][1] == "real_session"

    def test_mixed_only_real_returned(self, sessions_dir):
        _write_stub(sessions_dir, "stub")
        _write_real(sessions_dir, "real")
        from session_io import list_sessions
        names = {r[1] for r in list_sessions()}
        assert names == {"real"}

    def test_include_empty_shows_everything(self, sessions_dir):
        _write_stub(sessions_dir, "stub")
        _write_real(sessions_dir, "real")
        from session_io import list_sessions
        names = {r[1] for r in list_sessions(include_empty=True)}
        assert names == {"stub", "real"}

    def test_session_with_params_only_kept(self, sessions_dir):
        # Params alone count as content — don't lose param-only sessions.
        p = sessions_dir / "params_only.archhub-session.json"
        p.write_text(json.dumps({
            "_name": "params_only", "_saved_at": "2026-05-09",
            "parameters": [{"name": "x", "value": 1}],
            "chain": [],
        }), encoding="utf-8")
        from session_io import list_sessions
        names = {r[1] for r in list_sessions()}
        assert "params_only" in names

    def test_user_only_session_hidden(self, sessions_dir):
        # Chat that crashed mid-turn: user typed something, assistant
        # never replied. Saved as {user:'ping', assistant:''}. The
        # new filter treats this as a stub — without an assistant
        # response, there's nothing to reload, so the rail shouldn't
        # surface it. This is the bug class that hit user with
        # "PING OUTLOOK → blank assistant" after Anthropic + OpenAI
        # ran out of credits + the streaming race ate the chunk.
        _write_user_only(sessions_dir, "crashed_chat")
        from session_io import list_sessions
        assert list_sessions() == []

    def test_session_with_empty_assistant_treated_as_stub(self, sessions_dir):
        # Same shape as above but written slightly differently —
        # multiple user msgs, last assistant is empty string.
        p = sessions_dir / "stuck.archhub-session.json"
        p.write_text(json.dumps({
            "_name": "stuck", "_saved_at": "2026-05-11",
            "parameters": [], "chain": [],
            "_messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "second"},
                {"role": "assistant", "content": ""},
            ],
        }), encoding="utf-8")
        from session_io import list_sessions
        # At least ONE non-empty assistant → KEPT.
        names = {r[1] for r in list_sessions()}
        assert "stuck" in names


# ---------------------------------------------------------------------------
class TestCleanupHelper:
    def test_removes_stubs_returns_count(self, sessions_dir):
        _write_stub(sessions_dir, "a")
        _write_stub(sessions_dir, "b")
        _write_real(sessions_dir, "c")
        from session_io import cleanup_empty_sessions, list_sessions
        n = cleanup_empty_sessions()
        assert n == 2
        # Only the real one remains.
        rows = list_sessions(include_empty=True)
        assert len(rows) == 1
        assert rows[0][1] == "c"

    def test_no_op_when_directory_clean(self, sessions_dir):
        _write_real(sessions_dir, "a")
        from session_io import cleanup_empty_sessions
        assert cleanup_empty_sessions() == 0

    def test_no_op_when_directory_missing(self, tmp_path, monkeypatch):
        import session_io
        monkeypatch.setattr(session_io, "SESSIONS_DIR",
                             tmp_path / "does_not_exist")
        assert session_io.cleanup_empty_sessions() == 0
