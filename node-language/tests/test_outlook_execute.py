"""outlook_execute_python — universal escape hatch tests.

Solves the 'I have to ship a new macro for every task' problem.
Model writes Python code, runs in COM context with full Outlook
access. Same pattern as revit_execute_csharp / blender_execute_python.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# outlook_execute_python runs user code inside a live Win32 COM context.
# The runner module lazy-imports pywin32, so non-Windows runners skip.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="outlook_execute_python depends on pywin32 / Win32 COM (Windows only)",
)

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestOutlookExecutePython:
    def _stub_com(self):
        """Build stub outlook + ns + inbox for the COM context."""
        ns = MagicMock()
        inbox = MagicMock()
        inbox.Items = []
        sent = MagicMock(); drafts = MagicMock()
        ns.GetDefaultFolder = lambda fid: {
            6: inbox, 5: sent, 16: drafts
        }.get(fid, inbox)
        outlook = MagicMock()
        return outlook, ns, inbox

    def test_empty_code_errors(self):
        from connectors import outlook_runner as r
        with patch("connectors.outlook_runner.com_thread"):
            out = r.execute_python(code="")
        assert out["status"] == "error"

    def test_simple_arithmetic_result(self):
        from connectors import outlook_runner as r
        outlook, ns, _inbox = self._stub_com()
        with patch("connectors.outlook_runner.com_thread"), \
             patch("connectors.outlook_runner._client",
                    return_value=outlook), \
             patch("connectors.outlook_runner._ns",
                    return_value=ns):
            out = r.execute_python(code="result = 2 + 3")
        assert out["status"] == "ok"
        assert out["result"] == 5

    def test_stdout_captured(self):
        from connectors import outlook_runner as r
        outlook, ns, _inbox = self._stub_com()
        with patch("connectors.outlook_runner.com_thread"), \
             patch("connectors.outlook_runner._client",
                    return_value=outlook), \
             patch("connectors.outlook_runner._ns",
                    return_value=ns):
            out = r.execute_python(code="print('hello world')")
        assert out["status"] == "ok"
        assert "hello world" in out["stdout"]

    def test_exception_returns_error_with_traceback(self):
        from connectors import outlook_runner as r
        outlook, ns, _inbox = self._stub_com()
        with patch("connectors.outlook_runner.com_thread"), \
             patch("connectors.outlook_runner._client",
                    return_value=outlook), \
             patch("connectors.outlook_runner._ns",
                    return_value=ns):
            out = r.execute_python(code="1/0")
        assert out["status"] == "error"
        assert "ZeroDivisionError" in out["error"]
        assert "<outlook_execute_python>" in out["traceback"]

    def test_inbox_accessible_as_global(self):
        # Test the inbox global by counting items.
        from connectors import outlook_runner as r
        outlook, ns, _inbox = self._stub_com()
        # Add 4 fake messages.
        fake_msgs = [MagicMock() for _ in range(4)]
        _inbox.Items = fake_msgs
        with patch("connectors.outlook_runner.com_thread"), \
             patch("connectors.outlook_runner._client",
                    return_value=outlook), \
             patch("connectors.outlook_runner._ns",
                    return_value=ns):
            out = r.execute_python(code="result = len(list(inbox.Items))")
        assert out["status"] == "ok"
        assert out["result"] == 4

    def test_non_serialisable_result_falls_back_to_repr(self):
        # COM objects aren't JSON-serialisable — return repr instead.
        from connectors import outlook_runner as r
        outlook, ns, _inbox = self._stub_com()
        with patch("connectors.outlook_runner.com_thread"), \
             patch("connectors.outlook_runner._client",
                    return_value=outlook), \
             patch("connectors.outlook_runner._ns",
                    return_value=ns):
            out = r.execute_python(
                code="class X: pass\nresult = X()")
        assert out["status"] == "ok"
        assert isinstance(out["result"], str)


class TestRegistration:
    def test_outlook_execute_python_registered(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS}
        assert "outlook_execute_python" in names

    def test_filter_always_keeps_execute_python(self):
        # Universal escape hatch should land in EVERY filter result,
        # even when no family-keyword is in the user message.
        from llm_router import _filter_tools_by_relevance
        from tool_engine import TOOLS
        schemas = [{"name": t["name"]} for t in TOOLS]
        for q in (
            "hello",
            "forward all newsletters to bob@",
            "count emails per sender",
            "add a wall in revit",
            "render this scene",
        ):
            out = _filter_tools_by_relevance(
                schemas,
                [{"role": "user", "content": q}],
                cap=12,
            )
            names = {t["name"] for t in out}
            has_any_execute = any("execute" in n for n in names)
            assert has_any_execute, (
                f"No execute tool landed in filter for query "
                f"{q!r} — model has no escape hatch."
            )

    def test_prompt_advertises_escape_hatch(self):
        from unittest.mock import MagicMock
        import llm_router
        from tool_engine import ToolEngine
        mgr = MagicMock(); mgr.entries = []
        router = llm_router.LLMRouter(ToolEngine(mgr))
        p = router._build_system_prompt()
        for tname in ("outlook_execute_python", "revit_execute_csharp",
                       "blender_execute_python"):
            assert tname in p, f"prompt missing {tname}"
        # Phrase must communicate the escape-hatch concept.
        assert "escape hatch" in p.lower()
