"""Tests for personal_brain.storage.BrainStore.a11y_prefs.

Track E (Accessibility) deliverable from the Content Ecosystem wave
(2026-05-26). The storage primitive backs the AccessibilityTab in
``app/settings_dialog.py`` and the future ``brain.a11y_prefs`` MCP
tool.

Contract (audit doc §5):
- get on empty store returns DEFAULT_A11Y_PREFS.
- set persists; subsequent get returns the merged result.
- set with bad mode raises ValueError.
- set with bad prefs payload returns ``{ok: False, ...}``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow running from repo root without an installed package.
PB_ROOT = Path(__file__).resolve().parent.parent / "personal-brain-mcp" / "src"
if str(PB_ROOT) not in sys.path:
    sys.path.insert(0, str(PB_ROOT))

from personal_brain.storage import BrainStore


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ── 1. get on empty store → defaults ──────────────────────────────────
def test_get_empty_returns_defaults(store):
    """First read on a fresh store must return DEFAULT_A11Y_PREFS.

    No fragment exists yet — the call should not raise, and the four
    documented keys must be present at their default values.
    """
    resp = store.a11y_prefs("get", owner_user="founder")
    assert resp["ok"] is True
    assert resp["mode"] == "get"
    prefs = resp["prefs"]
    # All four documented keys at their defaults.
    assert prefs["font_size"] == "medium"
    assert prefs["contrast"] == "normal"
    assert prefs["reduce_motion"] is False
    assert prefs["screen_reader_optimised"] is False


# ── 2. set persists ───────────────────────────────────────────────────
def test_set_persists(store):
    """After set, the underlying fragment exists with predicate=a11y."""
    payload = {
        "font_size": "large",
        "contrast": "high",
        "reduce_motion": True,
        "screen_reader_optimised": True,
    }
    resp = store.a11y_prefs("set", prefs=payload, owner_user="founder")
    assert resp["ok"] is True
    assert resp["mode"] == "set"
    assert resp["prefs"]["font_size"] == "large"

    # Direct fragment lookup confirms it landed at the canonical id.
    frag = store.get_fragment("a11y:founder")
    assert frag is not None
    assert frag.predicate == "a11y"
    assert frag.kind.value == "setup"
    assert frag.scope.value == "user"
    assert frag.owner_user == "founder"
    # object holds the JSON-serialised payload.
    assert "large" in (frag.object or "")
    assert "high" in (frag.object or "")


# ── 3. get after set returns set values ───────────────────────────────
def test_get_after_set_returns_set_values(store):
    """Round-trip: set then get must return the same values, merged on
    top of defaults so a partial set leaves unset keys at default."""
    store.a11y_prefs(
        "set",
        prefs={"font_size": "xlarge", "reduce_motion": True},
        owner_user="founder",
    )
    resp = store.a11y_prefs("get", owner_user="founder")
    assert resp["ok"] is True
    prefs = resp["prefs"]
    # Set values survived.
    assert prefs["font_size"] == "xlarge"
    assert prefs["reduce_motion"] is True
    # Unset values still at default.
    assert prefs["contrast"] == "normal"
    assert prefs["screen_reader_optimised"] is False

    # Per-user isolation: a different user still sees defaults.
    other = store.a11y_prefs("get", owner_user="ada")
    assert other["prefs"]["font_size"] == "medium"
    assert other["prefs"]["reduce_motion"] is False


# ── 4. bad mode raises ────────────────────────────────────────────────
def test_set_with_bad_mode_raises(store):
    """ANTI-LIE: bad mode must blow up loudly, not silently no-op."""
    with pytest.raises(ValueError, match="mode must be"):
        store.a11y_prefs("toggle", prefs={}, owner_user="founder")
    with pytest.raises(ValueError):
        store.a11y_prefs("", prefs={}, owner_user="founder")
    with pytest.raises(ValueError):
        store.a11y_prefs("delete", owner_user="founder")


# ── Bonus: set without prefs payload is rejected gracefully ───────────
def test_set_without_prefs_returns_error(store):
    """set mode without a prefs dict returns ok=False, not raises."""
    resp = store.a11y_prefs("set", prefs=None, owner_user="founder")
    assert resp["ok"] is False
    assert "prefs" in resp["error"]
    resp2 = store.a11y_prefs("set", prefs="not a dict", owner_user="founder")
    assert resp2["ok"] is False
