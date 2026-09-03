"""llm_router transient-network retry detector.

v1.0.2 hotfix — Sentry PYTHON-7 was `httpx.ReadError: WinError 10054`
during a claude-sonnet-4-6 stream. Single retry on the same provider
catches the typical case; real auth/quota failures still fall through
to provider switching.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestTransientNetworkDetector:
    def test_winerror_10054_is_transient(self):
        from llm_router import _looks_like_transient_network
        ex = OSError("[WinError 10054] An existing connection was "
                     "forcibly closed by the remote host")
        assert _looks_like_transient_network(ex) is True

    def test_apiconnectionerror_classname_is_transient(self):
        from llm_router import _looks_like_transient_network
        # Build a class with that name dynamically — we don't want to
        # import openai in the test environment.
        APIConnectionError = type("APIConnectionError",
                                   (Exception,), {})
        ex = APIConnectionError("Connection error.")
        assert _looks_like_transient_network(ex) is True

    def test_httpx_readerror_classname_is_transient(self):
        from llm_router import _looks_like_transient_network
        ReadError = type("ReadError", (Exception,), {})
        ex = ReadError("Server disconnected mid-stream")
        assert _looks_like_transient_network(ex) is True

    def test_502_503_504_are_transient(self):
        from llm_router import _looks_like_transient_network
        for status in ("502 Bad Gateway", "503 Service Unavailable",
                       "504 Gateway Timeout"):
            assert _looks_like_transient_network(Exception(status)) is True

    def test_anthropic_529_overloaded_is_transient(self):
        from llm_router import _looks_like_transient_network
        assert _looks_like_transient_network(
            Exception("Error code: 529 - overloaded_error")
        ) is True

    def test_auth_error_is_not_transient(self):
        from llm_router import _looks_like_transient_network
        # 401 / invalid key shouldn't be retried on the same provider.
        assert _looks_like_transient_network(
            Exception("401 Unauthorized")
        ) is False

    def test_quota_error_is_not_transient(self):
        from llm_router import _looks_like_transient_network
        # Sentry PYTHON-6 — quota hit. Same provider won't recover.
        assert _looks_like_transient_network(
            Exception("You exceeded your current quota, please check "
                       "your plan and billing details.")
        ) is False
