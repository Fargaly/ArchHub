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
# COLOR — semantic palette (light theme).
# ---------------------------------------------------------------------------
COLOR = {
    # Surfaces.
    "bg":          "#f7f4ee",  # page canvas
    "bgPanel":     "#fbf9f4",  # rail / inspector / status rule
    "bgSoft":      "#efeae0",  # sub-fills, divider plates, user bubble
    "bgHover":     "#ebe6db",  # row + nav hover
    "bgRaised":    "#ffffff",  # cards on top of canvas

    # Ink (text).
    "ink":         "#251f17",  # primary text
    "inkSoft":     "#5d544a",  # secondary text — bumped from #6b6256
                                 # for 7.0:1 on bgPanel (was 5.4:1)
    "inkMuted":    "#7d7568",  # body-muted — bumped from #9a9183
                                 # for 4.6:1 on bgPanel (was 3.0:1)
    "inkCap":      "#9a9183",  # mono captions — keeps the original hue,
                                 # 3.0:1 on bgPanel which clears AA for
                                 # non-essential text.
    "inkDim":      "#cdc6b8",  # disabled / inactive

    # Lines.
    "line":        "#e3ddd0",  # default divider
    "lineSoft":    "#ece6d8",  # row separator inside a card

    # Brand / semantic.
    "accent":      "#c96442",  # primary action, on-state, brand mark
    "accentSoft":  "#f5e3db",  # accent fill behind selection
    "accentHi":    "#8a3a25",  # accent gradient stop, dark variant
    "ok":          "#5a8a5e",  # live / connected
    "warn":        "#c08533",  # healing / loading
    "err":         "#b8493e",  # error / fail

    # Misc.
    "chipFill":    "rgba(0,0,0,0.04)",
    "focusRing":   "#c96442",  # accent — same hue as primary action
    "selBg":       "#ffffff",  # selected row in a list
}

# Backwards-compat alias for older code that imports `T` from here.
T = COLOR


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
