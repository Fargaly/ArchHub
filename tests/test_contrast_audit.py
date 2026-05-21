"""WCAG 1.4.3 contrast audit — AgDR-0015 Phase 4 remainder.

Two test classes:
  • Math primitives — `relative_luminance`, `contrast_ratio`,
    `passes_aa`, `passes_aaa` for known reference values from the
    WCAG spec.
  • LM palette audit — every canonical pair clears its threshold;
    palette extraction picks up the live tokens from studio-lm.jsx.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from contrast_audit import (  # noqa: E402
    relative_luminance,
    contrast_ratio,
    passes_aa,
    passes_aaa,
    extract_lm_palette,
    audit_palette,
    format_audit_report,
    CANONICAL_PAIRS,
    WCAG_AA_BODY,
    WCAG_AA_LARGE,
)


# ─── 1. math primitives ──────────────────────────────────────────────


def test_relative_luminance_pure_white_is_one():
    assert relative_luminance("#ffffff") == pytest.approx(1.0, abs=1e-9)


def test_relative_luminance_pure_black_is_zero():
    assert relative_luminance("#000000") == pytest.approx(0.0, abs=1e-9)


def test_relative_luminance_mid_grey():
    """sRGB #808080 (50%) has WCAG luminance ≈ 0.2159."""
    val = relative_luminance("#808080")
    assert val == pytest.approx(0.2158, abs=1e-3)


def test_contrast_ratio_black_on_white_is_21():
    """The WCAG maximum: pure black on pure white = 21:1."""
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0,
                                                                    abs=1e-6)


def test_contrast_ratio_is_symmetric():
    """Order shouldn't matter — function takes lighter/darker
    internally."""
    a, b = "#222288", "#cceeff"
    assert contrast_ratio(a, b) == contrast_ratio(b, a)


def test_contrast_ratio_minimum_is_one():
    """Same colour on same colour = 1.0 (no contrast)."""
    assert contrast_ratio("#abcdef", "#abcdef") == pytest.approx(1.0,
                                                                    abs=1e-6)


def test_passes_aa_body_threshold():
    """Black on white passes both AA body + large."""
    assert passes_aa("#000000", "#ffffff") is True
    assert passes_aa("#000000", "#ffffff", large=True) is True


def test_passes_aa_fails_for_low_contrast():
    """Mid-grey on white fails AA body (4.5:1) but might pass AA large."""
    assert passes_aa("#888888", "#ffffff") is False  # 3.5:1 ish


def test_passes_aaa_stricter_than_aa():
    """An accent that clears AA may still fail AAA."""
    # A pair that's ~5:1 — clears AA body (4.5) but fails AAA body (7).
    assert passes_aa("#666666", "#ffffff") is True
    assert passes_aaa("#666666", "#ffffff") is False


def test_passes_short_hex():
    """`#abc` shorthand expands to `#aabbcc`."""
    assert relative_luminance("#fff") == pytest.approx(1.0, abs=1e-9)
    assert relative_luminance("#000") == pytest.approx(0.0, abs=1e-9)


def test_bad_hex_raises():
    with pytest.raises(ValueError):
        relative_luminance("not-a-color")
    with pytest.raises(ValueError):
        relative_luminance("#12345")  # wrong length


# ─── 2. LM palette extraction ────────────────────────────────────────


def test_extract_lm_palette_returns_expected_keys():
    palette = extract_lm_palette()
    # Pin a handful of canonical keys — drift in any of these means
    # the parser or the JSX changed.
    for key in ("bg", "bgPanel", "ink", "inkSoft", "inkMuted",
                 "accent", "ok", "warn", "err", "cyan", "purple", "blue"):
        assert key in palette, f"palette missing {key!r}"


def test_extract_lm_palette_values_are_hex():
    palette = extract_lm_palette()
    for key, val in palette.items():
        assert val.startswith("#")
        assert len(val) == 7  # `#rrggbb`


def test_extract_lm_palette_specific_values():
    """The canonical tokens snapshot at this commit."""
    palette = extract_lm_palette()
    assert palette["bg"] == "#0e0e11"
    assert palette["ink"] == "#ece8e0"
    assert palette["accent"] == "#d97757"


# ─── 3. canonical pair audit ─────────────────────────────────────────


def test_audit_returns_one_row_per_canonical_pair():
    rows = audit_palette()
    assert len(rows) == len(CANONICAL_PAIRS)


def test_audit_primary_text_passes_aa_body():
    """ink-on-bg + ink-on-bgPanel must clear 4.5:1 (body)."""
    rows = audit_palette()
    by_pair = {r["pair"]: r for r in rows}
    assert by_pair["ink on bg"]["pass"] is True
    assert by_pair["ink on bg"]["ratio"] >= WCAG_AA_BODY
    assert by_pair["ink on bgPanel"]["pass"] is True


def test_audit_secondary_text_passes_aa_body():
    """inkSoft on bg/bgPanel should be ≥4.5 — secondary text is
    still readable body text in our UI (used for descriptions /
    sub-titles, not just labels)."""
    rows = audit_palette()
    by_pair = {r["pair"]: r for r in rows}
    # Either passes (good); flag if not so we see the gap.
    soft_bg = by_pair["inkSoft on bg"]
    assert soft_bg["ratio"] >= WCAG_AA_BODY, (
        f"inkSoft on bg: {soft_bg['ratio']:.2f} — bump inkSoft brighter "
        f"or restrict to large-text-only")


def test_audit_accent_passes_aa_large():
    """Accent (orange CTA / border) on canvas must clear 3:1
    (large text + non-text contrast)."""
    rows = audit_palette()
    by_pair = {r["pair"]: r for r in rows}
    assert by_pair["accent on bg"]["pass"] is True
    assert by_pair["accent on bg"]["ratio"] >= WCAG_AA_LARGE


def test_audit_status_colours_pass_aa_large():
    """OK / WARN / ERR status colours need 3:1 against canvas."""
    rows = audit_palette()
    by_pair = {r["pair"]: r for r in rows}
    for pair in ("ok on bg", "warn on bg", "err on bg"):
        r = by_pair[pair]
        assert r["pass"] is True, (
            f"{pair}: {r['ratio']} below threshold {r['threshold']}")


def test_audit_advisory_rows_dont_fail():
    """Advisory entries (inkMuted etc.) are informational — they
    should still appear in the report, but `pass: True` regardless
    of ratio (caller decides)."""
    rows = audit_palette()
    advisory = [r for r in rows if r.get("level") == "advisory"]
    assert advisory, "expected ≥1 advisory row"
    for r in advisory:
        # Advisory always passes (no hard threshold).
        assert r["pass"] is True


def test_audit_report_formats_one_line_per_pair():
    rows = audit_palette()
    report = format_audit_report(rows)
    # One line per pair.
    assert len(report.splitlines()) == len(rows)
    # Every line contains either ✓ or ✗.
    for line in report.splitlines():
        assert ("✓" in line) or ("✗" in line)


# ─── 4. regression — none of the canonical pairs ever fall below ─────


def test_no_aa_body_pair_falls_below_threshold():
    """Pinned regression: any drop in AA-body pair below 4.5:1
    breaks this test, surfacing the contrast regression in CI."""
    rows = audit_palette()
    body_fails = [r for r in rows
                  if r["level"] == "aa_body" and not r["pass"]]
    assert not body_fails, (
        "AA-body pairs below 4.5:1:\n" +
        "\n".join(f"  {r['pair']}: {r['ratio']:.2f}:1"
                  for r in body_fails))


def test_no_aa_large_pair_falls_below_threshold():
    rows = audit_palette()
    large_fails = [r for r in rows
                    if r["level"] == "aa_large" and not r["pass"]]
    assert not large_fails, (
        "AA-large pairs below 3:1:\n" +
        "\n".join(f"  {r['pair']}: {r['ratio']:.2f}:1"
                  for r in large_fails))
