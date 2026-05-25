"""WCAG 1.4.3 contrast audit — AgDR-0015 Phase 4 remainder.

Pure-Python util that:
  1. Computes WCAG relative luminance + contrast ratios for hex colours.
  2. Audits a foreground/background pair against the 4.5:1 (body) or
     3:1 (large text / non-text) threshold.
  3. Parses the LM palette out of `studio-lm.jsx` so the audit reflects
     the live tokens (no parallel copy in tests that can drift).

Spec: https://www.w3.org/TR/WCAG21/#contrast-minimum
Formulae:
  Luminance L = 0.2126*R + 0.7152*G + 0.0722*B
    where R, G, B are gamma-corrected sRGB values (`_to_linear`)
  Contrast = (L_lighter + 0.05) / (L_darker + 0.05)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


# WCAG 2.1 thresholds.
WCAG_AA_BODY = 4.5     # normal-size body text
WCAG_AA_LARGE = 3.0    # large-scale text (≥18pt or ≥14pt bold)
WCAG_AAA_BODY = 7.0
WCAG_AAA_LARGE = 4.5


def _parse_hex(hex_str: str) -> tuple[int, int, int]:
    """`#abcdef` → (R, G, B) ints. Accepts `#abc` shorthand."""
    s = hex_str.lstrip("#").strip()
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"bad hex color: {hex_str!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _to_linear(channel_8bit: int) -> float:
    """sRGB → linear light (WCAG)."""
    c = channel_8bit / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance ∈ [0, 1]."""
    r, g, b = _parse_hex(hex_color)
    return (0.2126 * _to_linear(r)
            + 0.7152 * _to_linear(g)
            + 0.0722 * _to_linear(b))


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG contrast ratio ∈ [1, 21]. Symmetric — the order
    doesn't matter; we take lighter/darker."""
    l1 = relative_luminance(fg_hex)
    l2 = relative_luminance(bg_hex)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def passes_aa(fg_hex: str, bg_hex: str, *, large: bool = False) -> bool:
    """AA threshold: 4.5:1 body, 3:1 large/non-text."""
    threshold = WCAG_AA_LARGE if large else WCAG_AA_BODY
    return contrast_ratio(fg_hex, bg_hex) >= threshold


def passes_aaa(fg_hex: str, bg_hex: str, *, large: bool = False) -> bool:
    """AAA threshold: 7:1 body, 4.5:1 large."""
    threshold = WCAG_AAA_LARGE if large else WCAG_AAA_BODY
    return contrast_ratio(fg_hex, bg_hex) >= threshold


# ── LM palette extraction ───────────────────────────────────────────


# Match `key:'#hex',` or `key:"#hex",` inside the `const LM = { ... }`
# top block. Captures keys that hold 6-digit hex colours.
_LM_HEX_LINE_RE = re.compile(
    r"(\b[a-zA-Z][a-zA-Z0-9_]*)\s*:\s*['\"]#([0-9a-fA-F]{6})['\"]")


def extract_lm_palette(jsx_path: str | Path | None = None) -> dict:
    """Pull the canonical dark-theme palette out of studio-lm.jsx.
    Returns dict of `name → '#rrggbb'`. Ignores typography / token
    nested objects (only top-level hex strings are surfaced).

    Source of truth shifted 2026-05-25 — the LM colour tokens are now
    getters reading `_currentTheme`, with the actual palette literals
    living in `THEMES.forge`. The audit always runs against `forge`
    (the default canonical dark theme); blueprint + vellum can be
    audited via the same machinery once palette is parameterised."""
    if jsx_path is None:
        # Locate `app/web_ui/studio-lm.jsx` relative to this file.
        jsx_path = Path(__file__).resolve().parent / "web_ui" / "studio-lm.jsx"
    src = Path(jsx_path).read_text(encoding="utf-8")
    # First try THEMES.forge — the new home for the canonical palette.
    forge_marker = "forge: {"
    start = src.find(forge_marker)
    if start < 0:
        # Back-compat: pre-2026-05-25 source had hex literals inline in
        # `const LM = {`.
        start = src.find("const LM = {")
    if start < 0:
        return {}
    # Find matching close brace by counting depth.
    depth = 0
    i = start
    end = -1
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end < 0:
        return {}
    block = src[start:end + 1]
    out: dict[str, str] = {}
    # THEMES.forge entries are indented 4 spaces (one nesting deeper
    # than the original top-level LM block which was 2 spaces). Accept
    # both depths; reject anything deeper (e.g. brand:{} sub-objects).
    is_forge_block = block.lstrip().startswith("forge")
    max_leading = 4 if is_forge_block else 2
    for match in _LM_HEX_LINE_RE.finditer(block):
        name = match.group(1)
        hex_val = "#" + match.group(2).lower()
        if name in ("LM", "forge"):
            continue
        line_start = block.rfind("\n", 0, match.start()) + 1
        leading = 0
        while line_start + leading < len(block) and block[line_start + leading] == " ":
            leading += 1
        if leading > max_leading:
            continue
        out[name] = hex_val
    return out


# ── Built-in audit suite — the pairs that matter most ───────────────


# Canonical foreground/background pairs for the dark theme. Each entry:
# (fg_key, bg_key, expectation, note).
#
# `expectation` levels:
#   'aa_body'   — must clear 4.5:1
#   'aa_large'  — must clear 3:1 (large text / non-text)
#   'advisory'  — informational only (e.g. inkMuted body); doesn't fail
#                 the build but surfaces in the audit report.
CANONICAL_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    # Primary readability.
    ("ink",      "bg",       "aa_body",  "Body text on canvas"),
    ("ink",      "bgPanel",  "aa_body",  "Body text on side-panel"),
    ("inkSoft",  "bg",       "aa_body",  "Secondary text on canvas"),
    ("inkSoft",  "bgPanel",  "aa_body",  "Secondary text on side-panel"),
    # CTA contrast — accent is interactive, treat as non-text 3:1
    # (the accent fills a button or border; the TEXT on it stays high).
    ("accent",   "bg",       "aa_large", "Accent border / CTA fill on canvas"),
    ("accent",   "bgPanel",  "aa_large", "Accent on side-panel"),
    # Status colours over canvas — used inline next to body text.
    ("ok",       "bg",       "aa_large", "OK status colour"),
    ("warn",     "bg",       "aa_large", "WARN status colour"),
    ("err",      "bg",       "aa_large", "ERR status colour"),
    # Muted text — only used for hints/labels at ≥12pt; flagged advisory.
    ("inkMuted", "bg",       "advisory", "Muted hint text — labels only"),
)


def audit_palette(palette: dict | None = None) -> list[dict]:
    """Run the canonical-pair audit. Returns a list of `{pair, fg, bg,
    ratio, threshold, level, pass, note}`. Caller decides what's a
    blocking failure."""
    palette = palette or extract_lm_palette()
    out: list[dict] = []
    for fg_key, bg_key, expectation, note in CANONICAL_PAIRS:
        fg = palette.get(fg_key)
        bg = palette.get(bg_key)
        if not fg or not bg:
            out.append({
                "pair": f"{fg_key} on {bg_key}",
                "fg": fg, "bg": bg, "ratio": None,
                "level": expectation, "pass": False,
                "note": note,
                "error": "palette key missing",
            })
            continue
        ratio = contrast_ratio(fg, bg)
        threshold = (WCAG_AA_BODY if expectation == "aa_body"
                     else WCAG_AA_LARGE if expectation == "aa_large"
                     else None)
        ok = (threshold is None) or (ratio >= threshold)
        out.append({
            "pair": f"{fg_key} on {bg_key}",
            "fg": fg, "bg": bg, "ratio": round(ratio, 2),
            "threshold": threshold, "level": expectation,
            "pass": bool(ok),
            "note": note,
        })
    return out


def format_audit_report(rows: Iterable[dict]) -> str:
    """Human-readable one-line-per-pair report."""
    out_lines: list[str] = []
    for r in rows:
        if r.get("error"):
            out_lines.append(
                f"  ✗ {r['pair']:30s}  ERROR: {r['error']}")
            continue
        mark = "✓" if r["pass"] else "✗"
        ratio_str = (f"{r['ratio']:.2f}:1"
                     if r.get("ratio") is not None else "—")
        thresh_str = (f"≥{r['threshold']:.1f}:1"
                      if r.get("threshold") is not None else "advisory")
        out_lines.append(
            f"  {mark} {r['pair']:30s}  {ratio_str:>10s}  "
            f"{thresh_str:>11s}  ({r['note']})")
    return "\n".join(out_lines)


__all__ = [
    "WCAG_AA_BODY", "WCAG_AA_LARGE", "WCAG_AAA_BODY", "WCAG_AAA_LARGE",
    "CANONICAL_PAIRS",
    "relative_luminance", "contrast_ratio",
    "passes_aa", "passes_aaa",
    "extract_lm_palette",
    "audit_palette", "format_audit_report",
]
