"""History compression tests — _compress_content + _compress_inv.

Live bug: a single outlook_execute_python invocation dumped 232 KB
of email-body text into the assistant turn. That message got re-sent
to the LLM on every subsequent turn, blowing up the prompt cache +
risking context-window overflow.

Fix: compress past tool-invocation result blobs in history_dicts
before the LLM call. On-disk session keeps the full content; only
the runtime prompt gets shortened.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestCompressContent:
    def test_short_passes_through(self, qapp=None):
        from chat_window import _compress_content
        assert _compress_content("hello world") == "hello world"
        assert _compress_content("") == ""

    def test_long_text_truncated_with_marker(self):
        from chat_window import _compress_content
        text = "x" * 10_000
        out = _compress_content(text)
        assert len(out) < len(text)
        assert "truncated" in out

    def test_truncation_keeps_head_and_tail(self):
        from chat_window import _compress_content
        text = "HEAD" * 100 + "M" * 5000 + "TAIL" * 100
        out = _compress_content(text)
        assert out.startswith("HEAD")
        assert out.endswith("TAIL")


class TestCompressInv:
    def _inv(self, result):
        from tool_engine import ToolInvocation
        return ToolInvocation(
            id="x", tool_name="outlook_execute_python",
            arguments={"code": "..."}, status="ok", result=result,
        )

    def test_small_dict_passes_through(self):
        from chat_window import _compress_inv
        inv = self._inv({"status": "ok", "count": 7})
        d = _compress_inv(inv)
        assert d["result"]["status"] == "ok"
        assert d["result"]["count"] == 7

    def test_big_string_field_truncated(self):
        from chat_window import _compress_inv
        big = "y" * 10_000
        inv = self._inv({"status": "ok", "stdout": big})
        d = _compress_inv(inv)
        assert len(d["result"]["stdout"]) < len(big)
        assert "truncated" in d["result"]["stdout"]

    def test_status_and_error_preserved_verbatim(self):
        from chat_window import _compress_inv
        inv = self._inv({"status": "error",
                          "error": "X" * 5000,
                          "details": "Y" * 5000})
        d = _compress_inv(inv)
        # status + error preserved verbatim (already short or
        # diagnostically critical).
        assert d["result"]["status"] == "error"
        assert d["result"]["error"] == "X" * 5000
        # Other fields truncated.
        assert len(d["result"]["details"]) < 5000

    def test_string_result_truncated(self):
        from chat_window import _compress_inv
        inv = self._inv("z" * 10_000)
        d = _compress_inv(inv)
        assert isinstance(d["result"], str)
        assert len(d["result"]) < 10_000
        assert "truncated" in d["result"]
