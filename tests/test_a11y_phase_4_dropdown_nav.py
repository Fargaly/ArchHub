"""AgDR-0015 Phase 4 — dropdown / radio-group keyboard nav.

Custom pill pickers (group-style, save-skill mode) need explicit
arrow-key nav + `role="radiogroup"` + `role="radio"` + `aria-checked`
since they're button arrays, not native `<select>`. Tests pin the
ARIA shape + the keyboard handler.
"""
from __future__ import annotations

from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_group_style_pills_have_radiogroup():
    src = _src()
    assert 'aria-labelledby="lm-group-style-label"' in src
    assert 'id="lm-group-style-label"' in src
    # role on container + role on each button.
    assert 'role="radiogroup"' in src


def test_save_skill_mode_pills_have_radiogroup():
    src = _src()
    assert 'aria-labelledby="lm-save-skill-mode-label"' in src
    assert 'id="lm-save-skill-mode-label"' in src


def test_radiogroup_count_at_least_two():
    src = _src()
    assert src.count('role="radiogroup"') >= 2
    # Each radiogroup contains ≥2 `role="radio"` (one per option).
    assert src.count('role="radio"') >= 4


def test_radio_buttons_carry_aria_checked():
    src = _src()
    # aria-checked={active} appears at least twice (one per pill group).
    assert src.count("aria-checked={active}") >= 2


def test_arrow_key_handler_present():
    """Keyboard handler covers ArrowLeft/Right/Up/Down + Home/End."""
    src = _src()
    for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
                 "Home", "End"):
        assert key in src, f"keyboard nav missing {key!r}"


def test_radio_tab_index_roving():
    """Only the active radio gets tabIndex=0; siblings get -1.
    Roving-tabindex pattern from WAI-ARIA Practices."""
    src = _src()
    assert "tabIndex={active ? 0 : -1}" in src
