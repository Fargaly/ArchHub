"""a11y wave-2 APPLY layer — source pins (founder-authorized 2026-06-10).

The 2026-06-03 pass applied only reduce_motion and deliberately deferred
font_size / contrast / screen_reader pending a design decision. That decision
landed ("you have full authority... proceed"), and the apply layer shipped:

    window.__archhubApplyA11y(prefs)  — ONE idempotent apply point
      reduce_motion -> html.lm-reduce-motion       (pre-existing)
      font_size     -> Chromium-native root zoom   (small .9 / large 1.1 / xl 1.25)
      contrast      -> per-theme high-contrast token overlay (survives theme switch)
      screen_reader -> html.lm-sr-optimized + #lm-sr-live polite region
                       announcing canvas toasts

Live-CDP-verified 2026-06-10 on an isolated instance: zoom 1.25 applied +
cleared; both classes toggled; the live region announced a dispatched canvas
toast verbatim; high-contrast survived a forge->blueprint switch.

These pins keep the apply layer from silently regressing back to the deferral
(the markers below are load-bearing identifiers, not comments) in BOTH the
source .jsx and the precompiled artifact the app actually loads.
"""
from __future__ import annotations

import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(os.path.dirname(_HERE), "app", "web_ui")
_JSX = os.path.join(_WEB, "studio-lm.jsx")
_COMPILED = os.path.join(_WEB, "studio-lm.compiled.js")

# Load-bearing markers of the apply layer.
_MARKERS = (
    "__archhubApplyA11y",      # the one apply point
    "lm-high-contrast",        # contrast class
    "lm-sr-optimized",         # screen-reader class
    "lm-sr-live",              # polite live region id
    "_CONTRAST_OVERLAYS",      # per-theme high-contrast token overlays
    "xlarge:1.25",             # the zoom map's extreme — font_size really maps to zoom
    "calc(100vw / ",           # ZOOM COMPENSATION on the #root mount — without
                               # it the zoomed app paints zoom× wider than the
                               # window and the right edge (filter chips,
                               # "+ new canvas") clips off-screen (founder
                               # 2026-06-11 screenshot). vw/vh ONLY — a %-based
                               # compensation on <html> resolves against the
                               # zoomed box and over-shrinks (clips) instead.
    "calc(100vh / ",           # …and the HEIGHT half: without it the bottom
                               # edge (status bar, SETTINGS rail icon) clips
                               # off-screen the same way (Copilot, PR #104).
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_jsx_source_carries_the_apply_layer():
    src = _read(_JSX)
    missing = [m for m in _MARKERS if m not in src]
    assert not missing, f"a11y apply layer regressed — missing from .jsx: {missing}"


def test_compiled_artifact_carries_the_apply_layer():
    """The app loads the PRECOMPILED bundle, not the .jsx — a stale artifact
    would mean the founder's app silently lacks the apply layer even though
    the source has it (exactly the stale-bundle race seen during the live
    verify). Pin the markers in the artifact too."""
    if not os.path.exists(_COMPILED):
        pytest.skip("precompiled artifact not present (built at launch)")
    out = _read(_COMPILED)
    missing = [m for m in _MARKERS if m not in out]
    assert not missing, f"compiled bundle stale — missing: {missing} (run tools/build_jsx)"


def test_mount_handler_routes_through_the_apply_point():
    """The StudioLM root's get_a11y_prefs mount effect must hand the prefs to
    __archhubApplyA11y — not re-implement a partial apply inline (the shape
    that produced the original applied-only-motion drift)."""
    src = _read(_JSX)
    i = src.find("get_a11y_prefs'")
    assert i != -1, "get_a11y_prefs mount handler not found"
    window = src[i:i + 600]
    assert "__archhubApplyA11y" in window, (
        "mount handler no longer routes prefs through __archhubApplyA11y")
