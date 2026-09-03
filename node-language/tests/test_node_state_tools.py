"""AgDR-0041 Properties 3 + 6 — Composer can flip node freeze / bypass.

The Composer should be able to say "freeze the upscale node" and have
that translated into a set_node delta the UI applies to the canvas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tool_engine import ToolEngine  # noqa: E402


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return ToolEngine(manager=_StubManager())


# ── node_freeze ────────────────────────────────────────────────────


def test_freeze_default_state_true(engine):
    out = engine._invoke_node_handler("node_freeze", {"node_id": "n_42"})
    assert out["status"] == "ok"
    assert out["op"] == "set_node"
    assert out["node_id"] == "n_42"
    assert out["patch"] == {"frozen": True}
    assert "❄" in out["note"]


def test_freeze_explicit_state_false(engine):
    out = engine._invoke_node_handler(
        "node_freeze", {"node_id": "n_42", "state": False})
    assert out["patch"] == {"frozen": False}


def test_freeze_missing_node_id_errors(engine):
    out = engine._invoke_node_handler("node_freeze", {})
    assert out["status"] == "error"
    assert "node_id" in out["error"]


# ── node_bypass ────────────────────────────────────────────────────


def test_bypass_default_state_true(engine):
    out = engine._invoke_node_handler("node_bypass", {"node_id": "n_99"})
    assert out["status"] == "ok"
    assert out["op"] == "set_node"
    assert out["node_id"] == "n_99"
    assert out["patch"] == {"bypassed": True}
    assert "○" in out["note"]


def test_bypass_explicit_state_false(engine):
    out = engine._invoke_node_handler(
        "node_bypass", {"node_id": "n_99", "state": False})
    assert out["patch"] == {"bypassed": False}


def test_bypass_missing_node_id_errors(engine):
    out = engine._invoke_node_handler("node_bypass", {})
    assert out["status"] == "error"


# ── TOOLS registry surface ──────────────────────────────────────────


def test_freeze_and_bypass_tools_registered(engine):
    """LLM must see node_freeze + node_bypass in the tool surface."""
    from tool_engine import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "node_freeze" in names
    assert "node_bypass" in names
