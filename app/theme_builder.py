"""Theme builder — rebuilds theme.qss with active palette substituted in.

Why
---
theme.qss is 600+ lines of QSS with ~244 hardcoded hex literals (the
ChatWindow-era styling). Refactoring all of those into per-selector
token reads is a separate PR; this module is the pragmatic shortcut so
the dark theme actually works on every surface (chat included) today.

How
---
We treat theme.qss as a template. At app start (and on theme toggle)
we read the file, run a small list of string replacements that swap
the light hex tokens for whatever the active palette has, and apply
the resulting QSS to the QApplication.

This way:
  - theme.qss stays human-readable (still hex, not interpolations).
  - Dark mode works on every selector that referenced one of the
    mapped light hex values.
  - When we eventually refactor theme.qss to consume tokens directly,
    this module becomes a thin pass-through and can be dropped.

Map below covers every distinct light hex literal in theme.qss as of
v0.27.5. If theme.qss adds a new color, add it here too.
"""
from __future__ import annotations

from pathlib import Path

from design_tokens import COLOR, current

# Light-theme hex literals appearing in theme.qss → token name in
# design_tokens.COLOR. We resolve via current() so swap is automatic.
#
# Source-of-truth: theme.qss "Tokens (light)" comment block at the top.
LIGHT_TO_TOKEN = {
    # Surfaces.
    "#f7f4ee": "bg",
    "#fbf9f4": "bgPanel",
    "#efeae0": "bgSoft",
    "#ebe6db": "bgHover",
    "#f3eee5": "bgSoft",      # gradient-only stop, close enough
    "#ffffff": "bgRaised",
    "#fff":     "bgRaised",
    # Lines.
    "#e3ddd0": "line",
    "#ece6d8": "lineSoft",
    # Inks.
    "#251f17": "ink",
    "#1a1612": "ink",
    "#6b6256": "inkSoft",
    "#5d544a": "inkSoft",
    "#3a3128": "inkSoft",
    "#9a9183": "inkMuted",
    "#7a7064": "inkMuted",
    "#7d7568": "inkMuted",
    "#cdc6b8": "inkDim",
    # Brand / semantic.
    "#c96442": "accent",
    "#d97757": "accent",       # accent variant — same role
    "#f5e3db": "accentSoft",
    "#8a3a25": "accentHi",
    "#5a8a5e": "ok",
    "#c08533": "warn",
    "#b8493e": "err",
}


import re


# `#ffffff` shows up two ways in theme.qss: as raised-card backgrounds
# (~20 places) AND as text color on the terra primary button (line 278:
# `color: #ffffff;`). Earlier passes naively swapped every #ffffff to
# bgRaised, which painted the white "Send" / "Open chat" button text
# dark grey on top of a dark-grey button — invisible. The fix is to
# only swap `background…: #fff` patterns, leaving `color: #fff` alone.
_BG_PROP_RE = re.compile(
    r"(?P<prop>background(?:-color)?\s*:\s*)(?P<hex>#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}))",
    re.IGNORECASE,
)


def _swap(qss: str, palette: dict) -> str:
    """Replace light hex literals with palette equivalents.

    Two-stage:
      1. Walk every `background:` / `background-color:` declaration and
         swap the hex against the LIGHT_TO_TOKEN map. Preserves the
         CSS property name + spacing.
      2. Walk the rest of the QSS and swap the non-#ffffff entries
         (text colors, borders, gradients) the simple way. We DON'T
         touch #ffffff at this stage so `color: #fff` survives.
    """
    # Stage 1: targeted background swaps.
    def _bg_repl(m: re.Match) -> str:
        hex_lit = m.group("hex").lower()
        # Expand 3-digit hex (#fff) to 6-digit (#ffffff) for map lookup.
        if len(hex_lit) == 4:
            hex_lit = "#" + "".join(c * 2 for c in hex_lit[1:])
        token = LIGHT_TO_TOKEN.get(hex_lit)
        if not token:
            return m.group(0)
        target = palette.get(token)
        if not target:
            return m.group(0)
        return m.group("prop") + target
    out = _BG_PROP_RE.sub(_bg_repl, qss)

    # Stage 2: non-background swaps. Skip the "always-white" entries
    # so `color: #ffffff;` and `border: 2px solid #ffffff;` survive.
    items = sorted(LIGHT_TO_TOKEN.items(), key=lambda kv: -len(kv[0]))
    for hex_lit, token in items:
        if hex_lit in ("#ffffff", "#fff"):
            continue   # Stage 1 already handled the bg case; leave text/border white.
        target = palette.get(token)
        if not target:
            continue
        out = _ireplace(out, hex_lit, target)
    return out


def _ireplace(s: str, needle: str, repl: str) -> str:
    """Case-insensitive str.replace."""
    needle_lo = needle.lower()
    out = []
    i = 0
    n_len = len(needle)
    while i < len(s):
        if s[i:i + n_len].lower() == needle_lo:
            out.append(repl)
            i += n_len
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def build_global_qss(theme_qss_path: Path) -> str:
    """Return theme.qss with the active palette substituted in. Falls
    back to the raw file contents if anything goes wrong so we never
    leave the app unstyled."""
    try:
        raw = theme_qss_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    try:
        return _swap(raw, current())
    except Exception:
        return raw
