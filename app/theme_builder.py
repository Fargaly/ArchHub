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


def _swap(qss: str, palette: dict) -> str:
    """Replace light hex literals in qss with palette equivalents.

    Case-insensitive matching to handle `#FFF` vs `#fff` etc. We sort
    by length descending so a longer literal never gets partially
    substituted by a shorter one (e.g. `#fff` not eating `#fbf9f4`).
    """
    out = qss
    items = sorted(LIGHT_TO_TOKEN.items(), key=lambda kv: -len(kv[0]))
    for hex_lit, token in items:
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
