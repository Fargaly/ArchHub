"""AgDR-0015 Phase 4 — a11y baseline nucleus.

Smoke tests that pin the in-place a11y promotion:
  1. JSX file contains `aria-label=` on at least 10 buttons (Phase 4
     nucleus floor — was 0 before this slice).
  2. `:focus-visible` outline CSS is injected for keyboard users.
  3. `prefers-reduced-motion` media query disables animation.
  4. Every line with `<button` + `title="…"` also carries
     `aria-label="…"` (no skipped buttons in the bulk-patch run).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_aria_label_floor_present():
    """Phase 4 nucleus: at least 10 `aria-label=` attributes in JSX.
    Pre-slice baseline was 0/9 per AgDR-0015 audit; this anchors
    the recovery + prevents regression."""
    src = _src()
    count = src.count("aria-label=")
    assert count >= 10, (
        f"a11y nucleus expects ≥10 aria-label attrs, got {count}")


def test_focus_visible_css_injected():
    """Keyboard-focus outline CSS sits in the injected `lm-a11y-styles`
    sheet. Ensures keyboard users see a clear focus ring."""
    src = _src()
    assert "lm-a11y-styles" in src
    assert ":focus-visible" in src
    # The outline uses the LM.accent token (interpolated at runtime).
    assert "outline: 2px solid" in src


def test_reduced_motion_respected():
    """Users with `prefers-reduced-motion: reduce` get animation
    duration collapsed to ~0ms."""
    src = _src()
    assert "prefers-reduced-motion" in src
    assert "animation-duration: 0.001ms" in src


def test_every_titled_button_has_aria_label():
    """A line with both `<button` AND `title="…"` must ALSO carry
    `aria-label="…"`. Guards against future devs adding titled
    icon-only buttons without screen-reader support."""
    src = _src()
    missing: list[tuple[int, str]] = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if "<button" in line and re.search(r'title="[^"]+"', line):
            if 'aria-label=' not in line:
                missing.append((lineno, line.strip()[:120]))
    assert not missing, (
        "Buttons with `title=` but missing `aria-label=`:\n" +
        "\n".join(f"  L{n}: {s}" for n, s in missing))


def test_a11y_style_injection_runs_at_module_load():
    """The IIFE that injects `lm-a11y-styles` runs once at module load
    (next to the wire-styles injector). Pin the call shape so a
    refactor doesn't accidentally remove it."""
    src = _src()
    # Helper exists.
    assert "_injectA11yStyles" in src
    # Set up like the wire-styles equivalent: const = (() => { … })()
    # invoked immediately.
    assert "document.getElementById('lm-a11y-styles')" in src
    assert "document.head.appendChild(s)" in src
