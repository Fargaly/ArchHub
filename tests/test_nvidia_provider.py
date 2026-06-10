"""NVIDIA NIM provider — behavioral pins (founder 2026-06-10 "can we utilize
NVIDIA models?"; Copilot review on #101 asked for behavior over grep).

The nvidia: prefix rides the existing OpenAI-compatible client at NVIDIA's
fixed cloud endpoint. One NVIDIA_API_KEY (or a saved 'nvidia' store key)
unlocks every catalog row. The provider short-circuits the generic api-key
gate so a missing key yields NVIDIA-specific guidance, not "No API key
configured for nvidia".
"""
from __future__ import annotations

import os
import sys

import pytest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

import llm_router  # noqa: E402


def _router():
    """Construct LLMRouter without a real ToolEngine — the methods under test
    (configured_providers, _get_client for nvidia) never touch self.tools."""
    r = object.__new__(llm_router.LLMRouter)
    r._clients = {}
    r._blocklist = {}
    r._block_reasons = {}
    return r


def test_nvidia_models_in_catalog():
    nv = [m for m in llm_router.KNOWN_MODELS if m[0].startswith("nvidia:")]
    assert len(nv) >= 4, "nvidia rows missing from KNOWN_MODELS"
    # real NIM catalog ids are org/name shaped
    assert all("/" in i.split(":", 1)[1] for i, _ in nv), [i for i, _ in nv]


def test_env_key_makes_nvidia_a_configured_provider(monkeypatch):
    """BEHAVIOR (Copilot #2): NVIDIA_API_KEY alone — no saved store key —
    must make configured_providers() include 'nvidia'."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-xxxxxxxxxxxxxxxx")
    r = _router()
    assert "nvidia" in r.configured_providers()


def test_env_key_builds_a_client_without_a_store_key(monkeypatch):
    """BEHAVIOR (Copilot #1): with only NVIDIA_API_KEY set, _get_client must
    short-circuit the generic gate and build the NVIDIA client — NOT raise
    'No API key configured for nvidia'."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-xxxxxxxxxxxxxxxx")
    r = _router()
    client = r._get_client("nvidia")
    assert client is not None
    base = getattr(getattr(client, "_client", None), "base_url", "")
    # Exact-equality check (not a substring) — CodeQL flags `"domain" in url`
    # as incomplete URL sanitization even in test assertions.
    assert str(base).rstrip("/") == "https://integrate.api.nvidia.com/v1", (
        f"wrong endpoint: {base!r}")


def test_no_key_raises_nvidia_specific_error(monkeypatch):
    """BEHAVIOR (Copilot #1/#3): no env key + no store key → the NVIDIA
    guidance, never the generic 'No API key configured' message."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(llm_router, "load_api_key",
                        lambda p: "" if p == "nvidia" else llm_router.load_api_key(p))
    r = _router()
    r._clients.pop("nvidia", None)
    with pytest.raises(RuntimeError) as ei:
        r._get_client("nvidia")
    msg = str(ei.value)
    assert "NVIDIA_API_KEY" in msg, f"not the NVIDIA-specific error: {msg!r}"
    assert "No API key configured for nvidia" not in msg
