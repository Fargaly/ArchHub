"""Session history persistence + AUMID icon registration regression tests.

Bug 1: saved sessions only persisted parametric Session.chain, not the
       chat ChatMessage history → reload showed empty conversation.
Bug 2: taskbar icon stayed as pythonw snake even with
       SetCurrentProcessExplicitAppUserModelID set, because Windows
       had no registry mapping from AUMID → icon path.
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
class TestSessionHistory:
    def _fake_msgs(self):
        return [
            {"role": "user", "content": "place a wall",
             "tool_invocations": [], "images": [], "model": ""},
            {"role": "assistant", "content": "Done.",
             "tool_invocations": [
                 {"id": "t1", "tool_name": "revit_execute_csharp",
                  "arguments": {"code": "..."}, "status": "ok",
                  "result": {"status": "ok"}}
             ],
             "images": [], "model": "claude-sonnet"},
            {"role": "user", "content": "now add a door",
             "tool_invocations": [], "images": [], "model": ""},
        ]

    def test_save_then_load_roundtrips_messages(self, tmp_path):
        import session_io
        from session import Session
        sess = Session()
        p = tmp_path / "x.archhub-session.json"
        session_io.save_session(sess, "roundtrip", path=p,
                                  messages=self._fake_msgs())
        _, name, msgs = session_io.load_session_with_messages(p)
        assert name == "roundtrip"
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "place a wall"
        assert msgs[1]["role"] == "assistant"
        assert len(msgs[1]["tool_invocations"]) == 1
        assert msgs[1]["tool_invocations"][0]["tool_name"] == "revit_execute_csharp"

    def test_load_session_without_messages_field(self, tmp_path):
        # Old session files (pre-fix) had no _messages key → must
        # still load cleanly with empty msg list. We can't use the
        # new save_session for this — it refuses empty payloads
        # (that's the point of the v1.0 contract). Write the legacy
        # shape directly to simulate a file from an older install.
        import json, session_io
        p = tmp_path / "legacy.archhub-session.json"
        p.write_text(json.dumps({
            "_name": "legacy",
            "_saved_at": "2026-04-01T00:00:00",
            "parameters": [],
            "chain": [],
            # no _messages key — pre-v1.0 shape
        }), encoding="utf-8")
        _, name, msgs = session_io.load_session_with_messages(p)
        assert name == "legacy"
        assert msgs == []

    def test_msg_to_dict_handles_objects(self):
        # Accept ChatMessage-like duck objects + raw dicts.
        from session_io import _msg_to_dict

        @dataclass
        class FakeMsg:
            role: str = "user"
            content: str = "hello"
            model: str = "x"
            images: list = field(default_factory=list)
            tool_invocations: list = field(default_factory=list)

        d = _msg_to_dict(FakeMsg())
        assert d["role"] == "user"
        assert d["content"] == "hello"
        assert d["model"] == "x"
        # Idempotent on already-dict input.
        again = _msg_to_dict(d)
        assert again == d

    def test_save_reuses_path_on_autosave(self, tmp_path):
        # Saving twice with the SAME path should overwrite, not fork.
        # Both saves must have real content — empty saves now raise
        # EmptySessionError by contract (v1.0).
        import session_io
        from session import Session
        p = tmp_path / "auto.archhub-session.json"
        s = Session()
        msgs_v1 = [{"role": "user", "content": "first",
                     "tool_invocations": [], "images": [], "model": ""}]
        session_io.save_session(s, "v1", path=p, messages=msgs_v1)
        session_io.save_session(s, "v2", path=p,
                                  messages=self._fake_msgs())
        files = list(tmp_path.glob("*.archhub-session.json"))
        assert len(files) == 1   # not 2
        _, name, msgs = session_io.load_session_with_messages(p)
        assert name == "v2"
        assert len(msgs) == 3


# ---------------------------------------------------------------------------
class TestAUMIDRegistration:
    def test_helper_exists_and_signature(self):
        import main
        assert hasattr(main, "_register_aumid_icon")
        # Three positional args: aumid, ico_path, display_name.
        argnames = main._register_aumid_icon.__code__.co_varnames[:3]
        assert argnames == ("aumid", "ico_path", "display_name")

    def test_skips_when_ico_missing(self, tmp_path):
        import main
        # Should not raise even though ico doesn't exist.
        main._register_aumid_icon(
            "io.archhub.test", tmp_path / "nope.ico", "Test"
        )

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="winreg is Windows-only")
    def test_writes_registry_entry_when_ico_present(self, tmp_path):
        import main, winreg
        ico = tmp_path / "fake.ico"
        ico.write_bytes(b"\x00\x00\x01\x00")  # ICO header magic
        aumid = "io.archhub.unittest.aumid"
        try:
            main._register_aumid_icon(aumid, ico, "ArchHub Test")
            # Read it back.
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 rf"Software\Classes\AppUserModelId\{aumid}") as k:
                icon_val, _ = winreg.QueryValueEx(k, "IconResource")
                name_val, _ = winreg.QueryValueEx(k, "DisplayName")
            assert icon_val == f"{ico},0"
            assert name_val == "ArchHub Test"
        finally:
            # Cleanup so we don't pollute the user's hive.
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                                  rf"Software\Classes\AppUserModelId\{aumid}")
            except OSError:
                pass

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="winreg is Windows-only")
    def test_idempotent_skips_rewrite_when_unchanged(self, tmp_path):
        import main, winreg
        ico = tmp_path / "fake.ico"
        ico.write_bytes(b"\x00\x00\x01\x00")
        aumid = "io.archhub.unittest.idem"
        try:
            main._register_aumid_icon(aumid, ico, "X")
            # Second call must not raise + must keep value.
            main._register_aumid_icon(aumid, ico, "X")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 rf"Software\Classes\AppUserModelId\{aumid}") as k:
                icon_val, _ = winreg.QueryValueEx(k, "IconResource")
            assert icon_val == f"{ico},0"
        finally:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                                  rf"Software\Classes\AppUserModelId\{aumid}")
            except OSError:
                pass
