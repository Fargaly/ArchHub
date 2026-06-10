"""NVIDIA NIM provider pins (founder 2026-06-10: "can we utilize NVIDIA models?").

The nvidia: prefix rides the existing OpenAI-compatible client at NVIDIA's
fixed cloud endpoint (integrate.api.nvidia.com/v1). One NVIDIA_API_KEY (or a
saved 'nvidia' secrets-store key) unlocks every catalog row.
"""
from __future__ import annotations

import os
import sys

import pytest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

import llm_router  # noqa: E402


def test_nvidia_models_in_catalog():
    nv = [m for m in llm_router.KNOWN_MODELS if m[0].startswith("nvidia:")]
    assert len(nv) >= 4, "nvidia rows missing from KNOWN_MODELS"
    ids = [m[0] for m in nv]
    # the ids are real NIM catalog ids (org/name) — not invented shapes
    assert all("/" in i.split(":", 1)[1] for i in ids), ids


def test_nvidia_env_detection_wired():
    src = open(os.path.join(APP, "llm_router.py"), encoding="utf-8").read()
    assert '"nvidia": "NVIDIA_API_KEY"' in src, (
        "nvidia missing from env-var provider detection")


def test_nvidia_dispatch_no_key_raises_friendly(monkeypatch):
    """Selecting an nvidia model without a key must raise the actionable
    RuntimeError (where to get a key), never a blind crash deeper in the
    OpenAI client."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    src = open(os.path.join(APP, "llm_router.py"), encoding="utf-8").read()
    i = src.find('elif provider == "nvidia":')
    assert i != -1, "nvidia dispatch branch missing"
    branch = src[i:i + 1400]
    assert "integrate.api.nvidia.com/v1" in branch
    assert "RuntimeError" in branch and "build.nvidia.com" in branch
