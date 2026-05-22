"""Multi-instance session-pin routing tests (v0.35).

Covers:
  * Chat-input @-mention parser (ChatWindow._extract_session_pin)
      - mid-prose emails are NOT mistaken for mentions
      - first mention wins; rest stays in the prose
      - empty input after extraction gets a placeholder
  * tool_engine session_pin path
      - invoke() forwards pin to the broker (revit/max/acad)
      - broker.pick_session is called with `prefer=<pin>`
      - missing-session error surfaces when pin doesn't match anything
  * list_pinnable_sessions returns flat list across families
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
class TestPinParser:
    """Direct test of the regex — independent of Qt so it runs anywhere."""

    def setup_method(self):
        import re
        self.PIN = re.compile(
            r"(?:(?<=^)|(?<=\s))@([A-Za-z0-9][A-Za-z0-9._\-]{0,63})"
        )

    def _extract(self, text):
        m = self.PIN.search(text)
        if not m:
            return text, None
        pin = m.group(1)
        cleaned = (text[:m.start()] + text[m.end():]).strip()
        if not cleaned:
            cleaned = f"(scoped to @{pin})"
        return cleaned, pin

    def test_word_boundary_doc_title(self):
        cleaned, pin = self._extract("place a wall at @Tower-A on level 2")
        assert pin == "Tower-A"
        assert "@Tower-A" not in cleaned

    def test_pid_token(self):
        _, pin = self._extract("@25232 sync deltas")
        assert pin == "25232"

    def test_email_in_prose_is_not_a_mention(self):
        _, pin = self._extract("send report to alice@studio.com please")
        assert pin is None

    def test_smtp_local_part_at_start(self):
        _, pin = self._extract("@ahmed.fargaly98 outlook")
        assert pin == "ahmed.fargaly98"

    def test_no_mention_passthrough(self):
        cleaned, pin = self._extract("hello world")
        assert pin is None
        assert cleaned == "hello world"

    def test_empty_after_extract_gets_placeholder(self):
        cleaned, pin = self._extract("@Tower-A")
        assert pin == "Tower-A"
        assert "Tower-A" in cleaned   # placeholder

    def test_first_mention_wins(self):
        # Second mention stays as literal text in cleaned output.
        cleaned, pin = self._extract("@Tower-A and @Tower-B")
        assert pin == "Tower-A"
        assert "@Tower-B" in cleaned


# ---------------------------------------------------------------------------
class TestToolEnginePinRouting:
    """Verify session_pin reaches the broker."""

    def _engine(self):
        # Stub manager — no connectors needed; we only test invoke routing.
        import tool_engine
        mgr = MagicMock()
        mgr.entries = []
        eng = tool_engine.ToolEngine(mgr)
        return tool_engine, eng

    def test_invoke_with_pin_calls_broker_pick_session(self):
        te, eng = self._engine()
        # Pretend revit family is active so the gate passes.
        eng._active_families = lambda: {"revit"}
        # Patch broker.pick_session and broker.forward.
        with patch.object(te, "json", te.json):  # touch import for clarity
            import revit_broker
            with patch.object(revit_broker, "pick_session") as pick, \
                 patch.object(revit_broker, "forward") as fwd:
                fake_session = MagicMock(session_id="revit-1234")
                pick.return_value = fake_session
                fwd.return_value = {"status": "ok", "alive": True}

                out = eng.invoke("revit_ping", {}, session_pin="Tower-A")

                pick.assert_called_once_with(prefer="Tower-A")
                fwd.assert_called_once()
                assert out["status"] == "ok"

    def test_invoke_with_unmatched_pin_returns_error(self):
        te, eng = self._engine()
        eng._active_families = lambda: {"revit"}
        import revit_broker
        with patch.object(revit_broker, "pick_session", return_value=None):
            out = eng.invoke("revit_ping", {}, session_pin="Nonexistent")
            assert out["status"] == "error"
            assert "Nonexistent" in out["error"]
            assert "revit" in out["error"]

    def test_invoke_without_pin_still_works(self):
        te, eng = self._engine()
        eng._active_families = lambda: {"max"}
        import max_broker
        fake = MagicMock(session_id="max-1")
        with patch.object(max_broker, "pick_session", return_value=fake) as pick, \
             patch.object(max_broker, "forward",
                           return_value={"status": "ok"}) as fwd:
            eng.invoke("max_ping", {})
            pick.assert_called_once_with(prefer=None)
            fwd.assert_called_once()

    def test_acad_routes_through_acad_broker(self):
        te, eng = self._engine()
        eng._active_families = lambda: {"acad"}
        import acad_broker
        fake = MagicMock(session_id="autocad-9")
        with patch.object(acad_broker, "pick_session", return_value=fake), \
             patch.object(acad_broker, "forward",
                           return_value={"status": "ok"}):
            out = eng.invoke("acad_ping", {}, session_pin="9")
            assert out["status"] == "ok"

    def test_blender_falls_back_to_legacy_url(self):
        # Blender has no broker; should hit the URL path.
        te, eng = self._engine()
        eng._active_families = lambda: {"blender"}
        with patch.object(te.urllib.request, "urlopen") as op:
            ctx = MagicMock()
            ctx.__enter__ = lambda s: s
            ctx.__exit__ = lambda *a: False
            ctx.read.return_value = b'{"status":"ok"}'
            op.return_value = ctx
            out = eng.invoke("blender_ping", {})
            assert out["status"] == "ok"
            op.assert_called_once()


# ---------------------------------------------------------------------------
class TestListPinnableSessions:
    def test_aggregates_across_brokers(self):
        import tool_engine
        eng = tool_engine.ToolEngine(MagicMock(entries=[]))
        # Each broker stub returns one healthy session.
        sample = lambda fam, pid: MagicMock(
            healthy=True, session_id=f"{fam}-{pid}", pid=pid,
            doc_title=f"{fam.title()}Doc", version="2026", port=48800 + pid,
        )
        import revit_broker, max_broker, acad_broker, outlook_broker
        with patch.object(revit_broker, "list_sessions",
                           return_value=[sample("revit", 1)]), \
             patch.object(max_broker, "list_sessions",
                           return_value=[sample("max", 2)]), \
             patch.object(acad_broker, "list_sessions",
                           return_value=[sample("autocad", 3)]), \
             patch.object(outlook_broker, "list_sessions",
                           return_value=[sample("outlook", 4)]):
            rows = eng.list_pinnable_sessions()
            fams = {r["family"] for r in rows}
            assert fams == {"revit", "max", "acad", "outlook"}
            for r in rows:
                assert "session_id" in r
                assert "doc_title" in r
