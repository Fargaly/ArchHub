"""Save-session contract tests — the load-bearing invariants that
prevent the empty-stub bug class from EVER coming back.

What the bug was
----------------
Pre-v1.0 chat autosave called `save_session(self.session, name)`. The
chat surface kept conversation in `self.history`, NEVER in
`self.session.chain`. save_session faithfully wrote
session.to_dict() = {parameters: [], chain: []}. Files appeared in
the THREADS rail but loaded blank chats.

What we now enforce
-------------------
1. save_session REFUSES to write when messages + parameters + chain
   are all empty. Raises EmptySessionError. Loud failure beats
   silent corruption.
2. After every successful write, save_session re-reads the file and
   asserts message / parameter / chain counts match what was passed
   in. Any mismatch removes the file and raises
   SessionRoundtripError.
3. The chat autosave timer never gets near save_session without
   self.history attached as messages=.
4. A static guardrail (scripts/check_session_saves.py) walks the AST
   of every .py file in the repo and fails CI / pre-commit on any
   save_session(...) call that omits messages=, unless the file is
   on the ALLOWED list with a documented reason.

These five tests pin the contract in place. If a future refactor
re-introduces the bug, one of them blows up before the change can
land.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    sd = tmp_path / "sessions"
    sd.mkdir(parents=True)
    import session_io
    monkeypatch.setattr(session_io, "SESSIONS_DIR", sd)
    return sd


# ---------------------------------------------------------------------------
class TestEmptyRejection:
    def test_empty_session_raises(self, sessions_dir):
        from session_io import save_session, EmptySessionError
        from session import Session
        with pytest.raises(EmptySessionError):
            save_session(Session(), "empty")

    def test_empty_messages_list_also_raises(self, sessions_dir):
        from session_io import save_session, EmptySessionError
        from session import Session
        with pytest.raises(EmptySessionError):
            save_session(Session(), "still empty", messages=[])

    def test_messages_present_writes_successfully(self, sessions_dir):
        from session_io import save_session
        from session import Session
        msgs = [{"role": "user", "content": "hi",
                  "tool_invocations": [], "images": [], "model": ""}]
        path = save_session(Session(), "with_msgs", messages=msgs)
        assert path.exists()

    def test_parameters_only_writes_successfully(self, sessions_dir):
        # Skills-style save: parametric content but no chat. Must work.
        from session_io import save_session
        from session import Session, Parameter, ParamType
        s = Session()
        s.parameters["x"] = Parameter(
            name="x", label="X", value=42, type=ParamType.NUMBER,
        )
        path = save_session(s, "params_only")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data.get("parameters") or []) == 1

    def test_graph_nodes_only_writes_successfully(self, sessions_dir):
        """A canvas-authored graph (host / AI nodes) is NOT empty even with
        no chat messages / parameters / chain. Regression guard for the
        2026-06-02 "ping rhino saved but empty" bug: the ping spawned a Host
        + Conversation node but kept the chat in the NODE body (not
        session.history), so _payload_is_empty wrongly returned True and
        save_session refused — persisting a nodes:[] stub. A graph with
        nodes must save."""
        from session_io import save_session
        from session import Session
        s = Session()
        s.graph = {
            "nodes": [
                {"id": "h_rhino", "cat": "host", "title": "Rhino"},
                {"id": "i_conv", "cat": "ai", "title": "Conversation"},
            ],
            "wires": [{"from": ["h_rhino", "view"], "to": ["i_conv", "ctx"]}],
        }
        path = save_session(s, "ping rhino")  # must NOT raise EmptySessionError
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len((data.get("graph") or {}).get("nodes") or []) == 2


# ---------------------------------------------------------------------------
class TestRoundtripVerify:
    def test_roundtrip_preserves_message_count(self, sessions_dir):
        from session_io import save_session, load_session_with_messages
        from session import Session
        msgs = [{"role": "user", "content": f"msg {i}",
                  "tool_invocations": [], "images": [], "model": ""}
                for i in range(7)]
        path = save_session(Session(), "seven", messages=msgs)
        _, _, restored = load_session_with_messages(path)
        assert len(restored) == 7

    def test_serializer_drop_triggers_roundtrip_error(
            self, sessions_dir, monkeypatch):
        # Force the verify step to see a mismatched count by
        # monkeypatching json.loads to drop _messages on the way back.
        from session_io import save_session, SessionRoundtripError
        from session import Session
        import session_io
        real_loads = json.loads
        def lossy_loads(s, *a, **kw):
            d = real_loads(s, *a, **kw)
            if isinstance(d, dict) and "_messages" in d:
                d["_messages"] = []
            return d
        monkeypatch.setattr(session_io.json, "loads", lossy_loads)
        msgs = [{"role": "user", "content": "x",
                  "tool_invocations": [], "images": [], "model": ""}]
        with pytest.raises(SessionRoundtripError):
            save_session(Session(), "lossy", messages=msgs)

    def test_corrupt_file_is_unlinked_on_failure(
            self, sessions_dir, monkeypatch):
        from session_io import save_session, SessionRoundtripError
        from session import Session
        import session_io
        real_loads = json.loads
        def lossy_loads(s, *a, **kw):
            d = real_loads(s, *a, **kw)
            if isinstance(d, dict) and "_messages" in d:
                d["_messages"] = []
            return d
        monkeypatch.setattr(session_io.json, "loads", lossy_loads)
        msgs = [{"role": "user", "content": "x",
                  "tool_invocations": [], "images": [], "model": ""}]
        try:
            save_session(Session(), "vanishing", messages=msgs)
        except SessionRoundtripError:
            pass
        # The file must NOT remain on disk — half-written data is
        # worse than nothing.
        remaining = list(sessions_dir.glob("*.archhub-session.json"))
        assert remaining == []


# ---------------------------------------------------------------------------
class TestStaticGuardrail:
    """Walk every .py file in the repo. Any save_session(...) call
    that omits messages= must be on the ALLOWED list."""

    def test_grep_scan_passes(self):
        script = REPO_ROOT / "scripts" / "check_session_saves.py"
        assert script.exists(), "Guardrail script missing"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Static guardrail flagged unsafe save_session calls:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_guardrail_catches_an_unsafe_call(self, tmp_path):
        # Plant a fake unsafe call + run the AST visitor directly.
        # subprocess version was flaky because the script scans
        # REPO_ROOT regardless of cwd; this is the equivalent
        # unit-level check.
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from check_session_saves import scan_file
        fake = tmp_path / "bad.py"
        fake.write_text(
            "from session_io import save_session\n"
            "save_session(session, 'name')\n",
            encoding="utf-8",
        )
        unsafe = scan_file(fake)
        assert len(unsafe) == 1
        # And a safe call must NOT trigger.
        good = tmp_path / "good.py"
        good.write_text(
            "from session_io import save_session\n"
            "save_session(session, 'name', messages=history)\n",
            encoding="utf-8",
        )
        assert scan_file(good) == []
