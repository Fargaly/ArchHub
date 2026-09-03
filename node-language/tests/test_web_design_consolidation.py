"""Marketing-site design consolidation (WEBSITE lane) — RED->GREEN gate.

The live Astro marketing site (`web/src/`) had drifted off the canonical
ArchHub design: a placeholder layout with a cyan `--accent:#5ec8ff`, system
fonts, no Instrument Serif, and — critically — no self-healing-connectors
section (the app's strongest differentiator, present in the signed reference
`_handoff/archhub/project/ArchHub Website.html` but missing from the live site).

PROTOTYPE-IS-CONTRACT: the shipped Astro site mirrors that reference 1:1 —
canonical terracotta accent `#d97757`, the bg/ink/line ramps, Instrument Serif
display + Inter body, a sticky blurred nav + footer to REAL routes, and the
self-heal block (before/after diff + recovery log + stats).

This pins the load-bearing pieces so a regression FAILS at PR time. It reads
the committed source (no Node, no build) and asserts on it directly — the same
shape as tests/test_build_jsx_precompile.py's committed-artifact checks.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB_SRC = REPO / "web" / "src"
BASE = WEB_SRC / "layouts" / "Base.astro"
INDEX = WEB_SRC / "pages" / "index.astro"

# Canonical token values — these MUST mirror tokens.jsx (window.AH), the
# project source of truth, per the design handoff README.
ACCENT = "#d97757"          # terracotta — the only emotional accent
BG = "#0e0e11"              # base background
INK = "#ece8e0"            # primary ink
LINE = "#26262e"           # hairline


def _read(p: Path) -> str:
    assert p.exists(), f"{p} is missing"
    return p.read_text(encoding="utf-8")


# ── Base.astro: canonical tokens, fonts, nav, footer ────────────────────────

def test_base_carries_canonical_terracotta_token():
    """The accent ramp is terracotta, not the old placeholder cyan."""
    css = _read(BASE)
    assert ACCENT in css, (
        f"Base.astro must define the canonical accent {ACCENT} (terracotta) — "
        f"the only emotional accent in the system."
    )
    # The old placeholder cyan accent must be gone (root cause of the drift).
    assert "#5ec8ff" not in css, (
        "Base.astro still carries the old placeholder cyan accent #5ec8ff — "
        "replace the whole :root with the canonical ArchHub token set."
    )


def test_base_carries_canonical_bg_ink_line_ramps():
    """The bg / ink / line ramps mirror tokens.jsx, not the placeholder set."""
    css = _read(BASE)
    for name, val in (("bg", BG), ("ink", INK), ("line", LINE)):
        assert val in css, f"Base.astro missing canonical --{name} value {val}"


def test_base_uses_instrument_serif_and_inter():
    """Instrument Serif is the display face; Inter is the body face."""
    css = _read(BASE)
    assert "Instrument Serif" in css, (
        "Base.astro must load + use Instrument Serif (the display face)."
    )
    assert "Inter" in css, "Base.astro must use Inter as the body sans."
    # The fonts are actually pulled in (Google Fonts link), not just named.
    assert "fonts.googleapis.com" in css, (
        "Base.astro must link the web fonts (Instrument Serif + Inter)."
    )
    # A --serif token wires the display face into the type system.
    assert re.search(r"--serif\s*:", css), "Base.astro must define a --serif token"


def test_base_has_sticky_blurred_nav_and_footer():
    """Sticky blurred nav + a real footer are part of the shell."""
    css = _read(BASE)
    assert "position:sticky" in css.replace(" ", "") or "position: sticky" in css, (
        "Base.astro nav must be sticky"
    )
    assert "backdrop-filter" in css, "Base.astro nav must use a blur (backdrop-filter)"
    html = css  # single-file component
    assert "<footer" in html and "</footer>" in html, "Base.astro must render a footer"


def test_base_nav_links_to_real_routes():
    """Nav/footer point at routes that actually exist under web/src/pages."""
    html = _read(BASE)
    pages_dir = WEB_SRC / "pages"
    real_routes = {"/"}
    for p in pages_dir.glob("*.astro"):
        if p.stem != "index":
            real_routes.add(f"/{p.stem}")
    # Subdirectory routes: pages/docs/index.astro → /docs (the docs-publish PR
    # ships docs as a directory route, not a top-level *.astro). Recognise any
    # immediate subdir that carries an index.astro or a [...slug].astro page.
    for sub in pages_dir.iterdir():
        if sub.is_dir() and (
            (sub / "index.astro").exists()
            or any(sub.glob("*.astro"))
        ):
            real_routes.add(f"/{sub.name}")
    # /brain is a real static route shipped under public/brain/.
    real_routes.add("/brain")
    hrefs = set(re.findall(r'href="(/[a-z0-9-]*)"', html))
    assert hrefs, "Base.astro must contain in-site nav links"
    bad = {h for h in hrefs if h.rstrip("/") and h.rstrip("/") not in real_routes}
    assert not bad, f"Base.astro links to non-existent routes: {sorted(bad)}"


# ── index.astro: hero, pillars, self-heal, graph, skills ────────────────────

def test_index_hero_headline_drafted_not_generated():
    """The hero carries the signed 'Drafted, not generated' headline with a
    terracotta italic, set in Instrument Serif (the serif class)."""
    html = _read(INDEX)
    low = html.lower()
    assert "drafted" in low and "not generated" in low, (
        "index.astro hero must carry the 'Drafted, not generated' headline."
    )
    assert "serif" in low, "the hero headline must use the Instrument Serif display face"


def test_index_has_three_pillars():
    """Canvas / Composer / Brain — the three pillars."""
    html = _read(INDEX)
    for pillar in ("Canvas", "Composer", "Brain"):
        assert pillar in html, f"index.astro missing the '{pillar}' pillar"


def test_index_has_self_heal_section():
    """The self-healing-connectors section — the app's strongest
    differentiator, absent from the old live site — is present, with the
    before/after diff, the recovery log, and the stats."""
    html = _read(INDEX)
    low = html.lower()
    # The section anchor / id the nav points at.
    assert 'id="heal"' in html or "self-heal" in low or "self-healing" in low, (
        "index.astro must include the self-healing-connectors section."
    )
    # before/after diff
    assert "before" in low and "after" in low, (
        "the self-heal section must show the before/after recovery diff."
    )
    # the recovery log (timeline of WATCH/DIAG/ACTION/OK lines)
    assert "recovery" in low, "the self-heal section must show a recovery log/state"
    # the stats (no manual restarts is the headline stat)
    assert "restart" in low, (
        "the self-heal section must carry the 'manual restarts' stat — the "
        "no-restarts promise is the differentiator."
    )


def test_index_has_graph_audit_and_skills_sections():
    """'A graph you can audit' + 'Skills are JSON you own' sections ship too."""
    html = _read(INDEX)
    low = html.lower()
    assert "audit" in low, "index.astro must carry the 'graph you can audit' section"
    assert "json" in low and "skill" in low, (
        "index.astro must carry the 'skills are JSON you own' section"
    )


# ── AEC voice: no banned generative-AI marketing words, no emoji ────────────

BANNED_WORDS = ("seamless", "powerful", "supercharge", "revolutionary")


def test_no_banned_marketing_words_in_copy():
    """AEC voice: purge generic generative-AI marketing fluff.

    'generate'/'produce' are checked separately because they legitimately
    appear in the *anti*-positioning ('Drafted, not generated'). These four
    have no defensible use in the copy.
    """
    for f in (BASE, INDEX):
        low = _read(f).lower()
        hit = [w for w in BANNED_WORDS if w in low]
        assert not hit, f"{f.name} uses banned marketing words {hit} — use AEC voice"


def test_copy_has_no_emoji():
    """No emoji in user-facing copy (mandate). Allow the geometric/technical
    glyphs the reference uses for node ports + dimension marks (●◈✎❖◇⌭⌗→↗⌥),
    which are typographic marks, not emoji."""
    allowed_marks = set("●◈✎❖◇⌭⌗→↗⌥⌂⚿✓▲★↓✦⊹·—")
    emoji_re = re.compile(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF]"
    )
    for f in (BASE, INDEX):
        text = _read(f)
        hits = [ch for ch in emoji_re.findall(text) if ch not in allowed_marks]
        assert not hits, f"{f.name} contains emoji {hits} — banned in user copy"
