"""Accessibility prefs round-trip: secrets_store ↔ bridge.get_a11y_prefs.

2026-06-03 — the AccessibilityTab's controls were made REAL. The Settings
tab persists prefs locally via `secrets_store.save_setting` under stable
keys; the React UI reads them back via the `get_a11y_prefs` bridge slot to
apply reduce-motion. This test pins that contract end-to-end on the Python
side:

  save_setting(<a11y keys>) → bridge.get_a11y_prefs() returns matching JSON
  with the correct TYPES, reduce_motion True/False both round-trip, and
  sane DEFAULTS appear when nothing is saved.

conftest.py's autouse `_isolate_secrets_store` redirects secrets_store to a
throwaway per-test dir, so these save_setting calls never touch real
machine state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst():
    # get_a11y_prefs reads only secrets_store — no tool engine / manager
    # needed. auto_extract_memory=False keeps the boot hook from racing.
    return _bridge_module.ArchHubBridge(
        manager=_StubManager(), auto_extract_memory=False)


def test_defaults_when_unset(bridge_inst):
    """No prefs saved yet → well-shaped defaults, never an error/raise."""
    out = json.loads(bridge_inst.get_a11y_prefs())
    assert out == {
        "reduce_motion": False,
        "screen_reader": False,
        "font_size": "default",
        "contrast": "default",
    }
    # Types are exactly what the JSX boot effect relies on.
    assert isinstance(out["reduce_motion"], bool)
    assert isinstance(out["screen_reader"], bool)
    assert isinstance(out["font_size"], str)
    assert isinstance(out["contrast"], str)


def test_full_round_trip(bridge_inst):
    """The 4 keys the AccessibilityTab writes come back verbatim."""
    from secrets_store import save_setting
    save_setting("a11y_reduce_motion", True)
    save_setting("a11y_screen_reader", True)
    save_setting("a11y_font_size", "large")
    save_setting("a11y_contrast", "high")

    out = json.loads(bridge_inst.get_a11y_prefs())
    assert out["reduce_motion"] is True
    assert out["screen_reader"] is True
    assert out["font_size"] == "large"
    assert out["contrast"] == "high"
    # Bools must be real JSON booleans, not truthy strings/ints.
    assert isinstance(out["reduce_motion"], bool)
    assert isinstance(out["screen_reader"], bool)


def test_reduce_motion_false_round_trips(bridge_inst):
    """The critical case for the UI toggle: a saved False must read back
    as False (not the unset default, not a truthy coercion) so the boot
    effect REMOVES html.lm-reduce-motion."""
    from secrets_store import save_setting
    save_setting("a11y_reduce_motion", False)
    save_setting("a11y_screen_reader", False)

    out = json.loads(bridge_inst.get_a11y_prefs())
    assert out["reduce_motion"] is False
    assert out["screen_reader"] is False


def test_reduce_motion_true_round_trips(bridge_inst):
    """Saved True reads back as True so the boot effect ADDS the class."""
    from secrets_store import save_setting
    save_setting("a11y_reduce_motion", True)

    out = json.loads(bridge_inst.get_a11y_prefs())
    assert out["reduce_motion"] is True
    # screen_reader was never set → still the default False.
    assert out["screen_reader"] is False


def test_partial_save_fills_rest_with_defaults(bridge_inst):
    """Only one key saved → the others fall back to defaults cleanly."""
    from secrets_store import save_setting
    save_setting("a11y_font_size", "xlarge")

    out = json.loads(bridge_inst.get_a11y_prefs())
    assert out["font_size"] == "xlarge"
    assert out["contrast"] == "default"
    assert out["reduce_motion"] is False
    assert out["screen_reader"] is False


def test_slot_present_and_callable(bridge_inst):
    assert hasattr(bridge_inst, "get_a11y_prefs")
    assert callable(bridge_inst.get_a11y_prefs)
    # Always returns a JSON string, never raises.
    assert isinstance(bridge_inst.get_a11y_prefs(), str)
