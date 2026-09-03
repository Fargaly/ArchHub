"""ArchHub design tokens — single source of truth for the Studio system.

Why this file exists
--------------------
Before this module the Studio palette lived in three places at once:
the comment block in `theme.qss`, the `T = {...}` dict in
`studio_shell.py`, and ~80 hardcoded hex literals scattered across both
files. Drift was inevitable. This module is the single source — both
`theme.qss` (via documented token mapping) and the Python shell consume
the same values.

Component documentation lives at the bottom — terse but enough to keep
six teams from re-inventing the same row layout.

Token categories
----------------
COLOR    — semantic palette (light theme; dark variant deferred)
SPACE    — spacing scale (4px rhythm)
RADIUS   — border-radius scale
TYPE     — typography scale + family stack
ELEV     — elevation tiers (border + shadow combined for QSS)
MOTION   — durations + easings (not enforced by Qt, but referenced here)

Accessibility intent
--------------------
- Body text contrast on bgPanel ≥ 4.5:1 (WCAG AA).
- Caption text on bgPanel ≥ 3:1 (WCAG AA for non-essential text).
- Focus ring visible on every interactive element (keyboard nav).
- Tap targets ≥ 28×28 visible, ≥ 36×36 hit area (relaxed from the
  44px mobile rule because this is desktop with mouse-precise input).

Component vocabulary
--------------------
See COMPONENTS docstring at the bottom for: button, row, card, KV,
status item, toggle, nav item, chip, list-row, skill-card.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# BRAND — identity v0.1 (May 2026, from brand.jsx in the handoff bundle).
# ---------------------------------------------------------------------------
BRAND = {
    "name":      "ArchHub",
    "tagline":   "Talk to your AEC stack.",
    "tagShort1": "Drafting table for AI.",
    "tagShort2": "One chat. Every host.",
    "tagShort3": "Skills, not prompts.",
    "version":   "v0.1",
    # Voice rules — keep handy for status/error strings.
    # ✅ "Dimensioned 47 walls in active view."
    # ❌ "Successfully completed your task! 🎉"
    # ✅ "Revit dropped — reconnecting on :7331."
    # ❌ "Oops! Something went wrong."
    "voice": [
        "Dimensional, technical, calm.",
        "No emoji. No exclamation points.",
        "We talk about drawings, not 'outputs'.",
    ],
    # Seven art-direction principles.
    "principles": [
        "Paper-first — even dark mode is graphite, never black.",
        "Drafted, not designed — show the gridlines.",
        "One warm color — terracotta is the only emotional accent.",
        "Calm density — info-rich without noise.",
        "Italic for soul — romance lives in the italic serif.",
        "No stock photos — real architecture or nothing at all.",
        "Quiet motion — things settle, dimension, heal.",
    ],
}


# ---------------------------------------------------------------------------
# COLOR (light theme) — paper · clay · graphite · ochre.
#
# Brand v0.1 mapping (from brand.jsx):
#   terra      = clay terracotta (primary, only emotional accent)
#   terraDeep  = darker terracotta (gradients, hover)
#   ochre      = dimensional ochre (secondary — sun on stone)
#   graphite   = drafting graphite (tertiary — display ink for dark)
#   cyan       = drafting cyan (technical accent — sparingly)
#   paper      = warm paper canvas
#   paperSoft  = secondary paper (cards, sub-fills)
#   paperLine  = paper-line divider
#
# Older code referred to bg/bgPanel/accent etc.; those are kept as aliases
# below so we don't have to touch every call site at once.
# ---------------------------------------------------------------------------
COLOR = {
    # Brand-named tokens (preferred, matches brand.jsx).
    "terra":      "#c96442",
    "terraDeep":  "#8a3a25",
    "ochre":      "#d9a445",
    "graphite":   "#2a2a2e",
    "cyan":       "#3a8a8a",
    "paper":      "#f7f4ee",
    "paperSoft":  "#efeae0",
    "paperLine":  "#e3ddd0",

    # Legacy semantic aliases (kept so existing call sites still work).
    "bg":          "#f7f4ee",  # page canvas == paper
    "bgPanel":     "#fbf9f4",  # rail / inspector / status rule
    "bgSoft":      "#efeae0",  # sub-fills, divider plates == paperSoft
    "bgHover":     "#ebe6db",  # row + nav hover
    "bgRaised":    "#ffffff",  # cards on top of canvas

    # Ink (text).
    "ink":         "#1a1612",  # primary text — pulled from brand.jsx
    "inkSoft":     "#3a3128",  # secondary text — pulled from brand.jsx
    "inkMuted":    "#7a7064",  # body-muted (4.5:1 on bgPanel) — brand
    "inkCap":      "#9a9183",  # mono captions (3:1 OK for non-essential)
    "inkDim":      "#cdc6b8",  # disabled / inactive

    # Lines.
    "line":        "#e3ddd0",  # default divider == paperLine
    "lineSoft":    "#ece6d8",  # row separator inside a card

    # Brand-action aliases.
    "accent":      "#c96442",  # == terra
    "accentSoft":  "#f5e3db",
    "accentHi":    "#8a3a25",  # == terraDeep
    "ok":          "#5a8a5e",
    "warn":        "#c08533",
    "err":         "#b8493e",

    # Misc.
    "chipFill":    "rgba(0,0,0,0.04)",
    "focusRing":   "#c96442",  # accent — same hue as primary action
    "selBg":       "#ffffff",
}

# Backwards-compat alias for older code that imports `T` from here.
T = COLOR


# ---------------------------------------------------------------------------
# COLOR_DARK — graphite, not black. Per brand principle 01 + studio.jsx
# (handoff dark token block). Surfaces feel like material, not screens.
# Terracotta carries the same weight; everything else is functional.
#
# Why these specific values? They come straight from
# `archhub/project/studio.jsx`'s `dark` token block. Earlier I had bumped
# them lighter by ~10 ticks each, which produced a "muddy three shades
# of grey" effect — cards floated on cards on panels in distinct visible
# rectangles, against the brand-direction "calm density" goal. The
# handoff values are deliberately low-contrast: panels and cards differ
# by ~5 in lightness, so cards register as borders + a tiny lift, not
# new rectangles.
# ---------------------------------------------------------------------------
COLOR_DARK = {
    "terra":      "#d97757",
    "terraDeep":  "#8a3a25",
    "ochre":      "#d9a445",
    "graphite":   "#161618",
    "cyan":       "#5fb3b3",
    "paper":      "#0f0f12",   # true graphite page canvas
    "paperSoft":  "#1d1d22",
    "paperLine":  "#26262d",

    # Surfaces — only ~5 lightness ticks between bg/panel/raised.
    "bg":          "#0f0f12",
    "bgPanel":     "#161618",
    "bgSoft":      "#1d1d22",
    "bgHover":     "#23232a",
    "bgRaised":    "#1d1d22",

    # Ink.
    "ink":         "#ece8e0",
    "inkSoft":     "#9b938a",
    "inkMuted":    "#5e5750",
    "inkCap":      "#5e5750",
    "inkDim":      "#3a3530",

    # Lines — barely-there.
    "line":        "#26262d",
    "lineSoft":    "#1d1d23",

    # Brand-action.
    "accent":      "#d97757",
    "accentSoft":  "#3a201a",
    "accentHi":    "#a04832",
    "ok":          "#7ec18e",
    "warn":        "#e5b25a",
    "err":         "#e6705f",

    "chipFill":    "rgba(255,255,255,0.04)",
    "focusRing":   "#d97757",
    "selBg":       "#1d1d22",
}


# Mutable runtime palette — `theme.set('dark')` swaps the `T` reference
# wholesale. Module-level `T` and `COLOR` always point at light;
# call `current()` to get the active palette inside Qt code.
#
# Default = dark (graphite, never black — brand principle 01). Light
# remains opt-in via the cog menu or `set_theme('light')`. Persisted
# preference overrides this default at startup.
_ACTIVE = "dark"


def set_theme(name: str) -> None:
    """Switch active theme — 'light' or 'dark'. Persisted via secrets_store
    on call (best effort)."""
    global _ACTIVE
    if name not in ("light", "dark"):
        return
    _ACTIVE = name
    try:
        from secrets_store import save_setting
        save_setting("theme_mode", name)
    except Exception:
        pass


def current() -> dict:
    """Return the currently-active palette dict."""
    return COLOR_DARK if _ACTIVE == "dark" else COLOR


def active_theme() -> str:
    return _ACTIVE


def load_theme_pref() -> None:
    """Read persisted preference once at app start."""
    global _ACTIVE
    try:
        from secrets_store import load_setting
        v = (load_setting("theme_mode") or "light").strip().lower()
        if v in ("light", "dark"):
            _ACTIVE = v
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SPACE — 4px spacing scale.
# ---------------------------------------------------------------------------
SPACE = {
    "xs":  4,
    "sm":  8,
    "md":  12,
    "lg":  16,
    "xl":  24,
    "2xl": 32,
    "3xl": 40,
    "4xl": 56,
}


# ---------------------------------------------------------------------------
# RADIUS — corner scale.
# ---------------------------------------------------------------------------
RADIUS = {
    "none": 0,
    "xs":   3,    # bar / pill micro
    "sm":   5,    # inline tag / hover plate
    "md":   6,    # nav button / chip
    "lg":   8,    # KV row / card
    "xl":   10,   # composer
    "pill": 999,  # round pill (model picker)
}


# ---------------------------------------------------------------------------
# TYPE — typography scale (size · weight · line-height · letter-spacing).
# Family stacks first so consumers can compose freely.
# ---------------------------------------------------------------------------
TYPE = {
    "fontSerif":  "'Instrument Serif', 'Lora', 'Georgia', serif",
    "fontSans":   "'Inter', 'Segoe UI', system-ui, sans-serif",
    "fontMono":   "'JetBrains Mono', 'Cascadia Mono', 'Consolas', monospace",

    # Display / heading scale (serif).
    "display":    {"size": 56, "weight": 400, "tracking": "-0.025em"},
    "h1":         {"size": 40, "weight": 400, "tracking": "-0.02em"},
    "h2":         {"size": 21, "weight": 400, "tracking": "-0.01em"},

    # Body scale (sans).
    "bodyLg":     {"size": 14, "weight": 400, "tracking": "0"},
    "body":       {"size": 13, "weight": 400, "tracking": "0"},
    "bodySm":     {"size": 12, "weight": 400, "tracking": "0"},
    "label":      {"size": 12.5, "weight": 500, "tracking": "0"},

    # Mono scale.
    "monoData":   {"size": 12,   "weight": 400, "tracking": "0.02em"},
    "monoBody":   {"size": 11.5, "weight": 400, "tracking": "0.04em"},
    "monoMuted":  {"size": 10.5, "weight": 400, "tracking": "0.04em"},
    "monoCap":    {"size": 9.5,  "weight": 400, "tracking": "0.12em"},
    "monoStat":   {"size": 10,   "weight": 400, "tracking": "0.10em"},
}


# ---------------------------------------------------------------------------
# ELEV — elevation tiers (border + (future) shadow).
# Qt5/6 doesn't render box-shadow in QSS, so for now elevation is just
# 1px borders. Documented so we have a single decision point if/when we
# add a QGraphicsDropShadowEffect-based elevation later.
# ---------------------------------------------------------------------------
ELEV = {
    "flat":     "border: 1px solid {line};",
    "raised":   "border: 1px solid {line};",   # placeholder — same as flat
    "floating": "border: 1px solid {line};",   # placeholder
}


# ---------------------------------------------------------------------------
# MOTION — duration / easing tokens.
# ---------------------------------------------------------------------------
MOTION = {
    "durFast":   120,
    "durMed":    180,
    "durSlow":   240,
    "easeOut":   "cubic-bezier(0.2, 0.8, 0.2, 1)",
    "easeIn":    "cubic-bezier(0.4, 0, 1, 1)",
}


# ---------------------------------------------------------------------------
# QSS helpers — convert token records into QSS fragments.
# ---------------------------------------------------------------------------
def t(scale: dict, key: str) -> str:
    """Render a TYPE record into the QSS font block."""
    rec = scale[key]
    return (
        f"font-size:{rec['size']}px; "
        f"font-weight:{rec['weight']}; "
        f"letter-spacing:{rec['tracking']};"
    )


def focus_ring_qss(*selectors: str) -> str:
    """Generate `:focus` rules that draw a visible 2px accent ring on
    keyboard focus (no visual change on mouse-only focus thanks to
    Qt6's StrongFocus default)."""
    if not selectors:
        return ""
    sel = ", ".join(f"{s}:focus" for s in selectors)
    return (
        f"{sel} {{ "
        f"  outline: none; "
        f"  border: 2px solid {COLOR['focusRing']}; "
        f"}}"
    )


# ---------------------------------------------------------------------------
# COMPONENTS — terse contract for the six most-reused atoms.
# Anyone editing studio_shell or theme.qss should match these exactly.
# ---------------------------------------------------------------------------
COMPONENTS = """
1. NAV ITEM (rail)
   - Height 32 · padding 7×10 · radius RADIUS.md
   - Default: bg=transparent · color=inkSoft · border=transparent
   - Hover:   bg=bgHover · color=ink
   - Active:  bg=bgRaised · color=ink · border=line · weight 500
   - Focus:   2px accent ring (handled by focus_ring_qss)

2. HOST ROW (rail)
   - Padding 5×9 · radius sm
   - Layout: dot (10) · name (1fr) · port-mono · toggle
   - Hover plate: bg=bgHover · radius sm
   - Toggle hit ≥ 36×24 (visual 24×14 with 6/5 padding inside)

3. THREAD ROW (rail)
   - Padding 5×9 · radius sm · cursor pointer
   - Hover plate: bg=bgHover · radius sm
   - Truncate text with ellipsis at row width

4. LIST ROW (centre cards)
   - Padding 10×14 · separator: 1px lineSoft (none on first row)
   - Hover: bg=bgPanel
   - Cells: leading dot/icon (12) · text (1fr) · trailing meta (mono)

5. KV ROW (inspector)
   - Padding 10×12 · radius lg · bg=bgRaised · border=1px line
   - Two stacked rows: caption (monoCap) · value (monoData)

6. STATUS ITEM (status rule)
   - 26px tall total · monoStat
   - Items separated by 14px gap
   - Trailing right group reserved for shortcut hints

Tokens these consume:
   - COLOR: bg/bgPanel/bgRaised/bgHover/ink/inkSoft/inkMuted/inkCap/
            line/lineSoft/accent/ok/warn/err/focusRing
   - SPACE: xs..3xl
   - RADIUS: sm/md/lg
   - TYPE:  body/label/monoCap/monoData/monoMuted/monoStat
"""
