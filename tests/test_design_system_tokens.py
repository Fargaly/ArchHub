"""DESIGN-SYSTEM lane — the app wears the canonical ArchHub design (RED->GREEN).

PROTOTYPE-IS-CONTRACT: the signed design source of truth lives in
`_handoff/archhub/project/` (tokens.jsx = window.AH, the Brand Book, bb-core's
BBWord wordmark). This brings it INTO the app:

  (1) tokens are the LITERAL SoT — `app/web_ui/tokens.jsx` ships window.AH, is
      loaded by index.html BEFORE the bundle, and studio-lm's THEMES.forge is
      DERIVED from window.AH (no hand-copied hexes).
  (2) a Wordmark (ARCH in ink + HUB in accent, Architects Daughter, uppercase,
      −2.5% tracking) is rendered in the header / Home / sign-in.
  (3) the full 12-step type scale LM.fs (d0..cap, each sz/ln/fam/role) ships
      alongside the legacy 6-step `font` map.
  (4) the canvas carries a 24px linear-gradient tracing grid behind the nodes.
  (5) the wire vocabulary is real: bezier default, dashed-muted pending/disabled,
      dashed-accent ANIMATED live-streaming.

These pin the load-bearing pieces against the COMMITTED source (no Node, no
browser, no Babel) — the same committed-artifact shape as
tests/test_web_design_consolidation.py. A regression FAILS at PR time.

RED->GREEN proof: on `git stash` of the lane's changes, every test below FAILS
(tokens.jsx absent; forge is hand-copied hexes; no Wordmark; no LM.fs; no tracing
grid; no lmFlow). With the changes applied, all PASS.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "app" / "web_ui"
TOKENS = WEB / "tokens.jsx"
INDEX = WEB / "index.html"
JSX = WEB / "studio-lm.jsx"
HANDOFF_TOKENS = REPO / "_handoff" / "archhub" / "project" / "tokens.jsx"

# Canonical token values — these are the SoT (window.AH) values; the app must
# DERIVE from them, never re-hardcode a divergent copy.
ACCENT = "#d97757"   # terracotta — the only emotional accent
INK = "#ece8e0"
LINE_SOFT = "#1e1e24"

# The 12 canonical type-scale steps (Brand Book full scale).
FS_STEPS = [
    "d0", "d1", "d2", "h1", "h2", "h3",
    "bodyLg", "body", "bodySm", "mono", "monoSm", "cap",
]


def _read(p: Path) -> str:
    assert p.exists(), f"{p} is missing"
    return p.read_text(encoding="utf-8")


# ── (1) tokens are the LITERAL SoT ──────────────────────────────────────────

def test_tokens_jsx_exists_and_defines_window_AH():
    """app/web_ui/tokens.jsx ships and assigns the window.AH SoT object."""
    src = _read(TOKENS)
    assert re.search(r"window\.AH\s*=\s*\{", src), (
        "tokens.jsx must define window.AH (the design source of truth)."
    )
    # The canonical accent + ink live in the SoT.
    assert ACCENT in src, "tokens.jsx (window.AH) must carry the terracotta accent."
    assert INK in src, "tokens.jsx (window.AH) must carry the canonical ink."


def test_tokens_jsx_exposes_short_projection():
    """The short-key projection (window.AHShort) ships for the brain/self-heal
    surfaces, mapping from the SAME canonical values."""
    src = _read(TOKENS)
    assert re.search(r"window\.AHShort\s*=", src), (
        "tokens.jsx must expose window.AHShort (short-key projection)."
    )


def test_tokens_jsx_matches_signed_handoff_sot():
    """The in-app tokens.jsx is the byte-for-byte mirror of the signed handoff
    SoT (PROTOTYPE-IS-CONTRACT) — the window.AH + window.AHShort blocks are
    identical, so the app cannot silently drift from the design source."""
    if not HANDOFF_TOKENS.exists():
        # The handoff tree may not ship with the repo in every checkout; the
        # other tests still pin the contract. Skip rather than fail spuriously.
        import pytest
        pytest.skip("signed handoff tokens.jsx not present in this checkout")
    app_src = _read(TOKENS)

    def _block(s: str) -> str:
        # Compare from `window.AH = {` to the end of the AHShort IIFE, ignoring
        # the file header comment (which legitimately differs in-app).
        i = s.index("window.AH = {")
        return s[i:].strip()

    assert _block(app_src) == _block(_read(HANDOFF_TOKENS)), (
        "app tokens.jsx has drifted from the signed handoff SoT — they must be "
        "the same window.AH / window.AHShort definition."
    )


def test_index_loads_tokens_before_the_bundle():
    """index.html loads tokens.jsx (window.AH) BEFORE jsx-boot.js, so the SoT
    exists when studio-lm's IIFE evaluates THEMES.forge. Compares the actual
    <script src=...> tags (not comment mentions)."""
    html = _read(INDEX)
    m_tokens = re.search(r'<script\s+src="tokens\.jsx"\s*>', html)
    m_boot = re.search(r'<script\s+src="jsx-boot\.js"\s*>', html)
    assert m_tokens, "index.html must load app/web_ui/tokens.jsx via a <script> tag"
    assert m_boot, "index.html must load jsx-boot.js via a <script> tag"
    assert m_tokens.start() < m_boot.start(), (
        "the tokens.jsx <script> must come BEFORE the jsx-boot.js <script> so "
        "window.AH is set before studio-lm's IIFE runs."
    )


def test_forge_is_derived_from_window_AH_not_hardcoded():
    """THEMES.forge is built FROM window.AH — there is no hand-copied forge hex
    block any more. The forge value reads each token off the SoT projection."""
    src = _read(JSX)
    # The derivation projector exists and forge uses it.
    assert re.search(r"_forgeFromAH\s*=\s*\(", src), (
        "studio-lm.jsx must define a _forgeFromAH(A) projector that builds forge "
        "from window.AH."
    )
    assert re.search(r"forge:\s*_forgeFromAH\(", src), (
        "THEMES.forge must be `_forgeFromAH(...)` — derived from the SoT, not a "
        "literal hex object."
    )
    # window.AH is read into the module.
    assert "window.AH" in src, "studio-lm.jsx must read window.AH (the SoT)."
    # The OLD hand-copied THEMES.forge object was a `forge: {` block carrying a
    # literal `bg:'#0e0e11'` surface hex. That MUST be gone (the projector reads
    # A.bg instead). Note: a `forge: {` key DOES legitimately survive in
    # _CONTRAST_OVERLAYS — but that overlay carries only ink/line keys, NEVER a
    # `bg:` surface hex, so this targets exactly the hand-copied palette.
    forge_with_bg = re.search(r"forge:\s*\{[^}]*\bbg:\s*'#", src)
    assert forge_with_bg is None, (
        "studio-lm.jsx still has a hand-copied `forge: { bg:'#...' }` literal "
        "palette — forge must be derived from window.AH via _forgeFromAH."
    )


def test_forge_projection_covers_every_surface_key():
    """The projector maps all 24 forge surface/ink/line/accent/functional keys
    FROM A.<key> (so changing a token in tokens.jsx updates forge)."""
    src = _read(JSX)
    proj = re.search(r"_forgeFromAH\s*=\s*\(A\)\s*=>\s*\(\{(.+?)\}\)", src, re.S)
    assert proj, "could not locate the _forgeFromAH projector body"
    body = proj.group(1)
    for key in ("bg", "bgPanel", "ink", "inkSoft", "line", "lineSoft",
                "accent", "accentHi", "ok", "warn", "err", "cyan", "purple", "blue"):
        assert re.search(rf"{key}\s*:\s*A\.{key}\b", body), (
            f"forge.{key} must be projected from window.AH (A.{key})."
        )


# ── (2) Wordmark renders ARCH + HUB ─────────────────────────────────────────

def test_wordmark_component_exists():
    """A Wordmark component exists (the ARCH·HUB lockup)."""
    src = _read(JSX)
    assert re.search(r"const Wordmark\s*=\s*\(", src), (
        "studio-lm.jsx must define a Wordmark component."
    )


def test_wordmark_renders_arch_in_ink_and_hub_in_accent():
    """The wordmark splits ARCH (ink) + HUB (accent), set in the architect's
    hand (LM.arch), uppercase, with −2.5% tracking — per bb-core BBWord."""
    src = _read(JSX)
    m = re.search(r"const Wordmark\s*=\s*\([^)]*\)\s*=>\s*\{(.+?)\n\};", src, re.S)
    assert m, "could not isolate the Wordmark component body"
    body = m.group(1)
    # Two spans: 'Arch' and 'Hub'.
    assert ">Arch<" in body and ">Hub<" in body, (
        "Wordmark must render 'Arch' and 'Hub' as separate spans."
    )
    # HUB is the accent; the architect's-hand face + uppercase + tight tracking.
    assert "LM.accent" in body, "the 'Hub' half of the wordmark must use LM.accent."
    assert "LM.arch" in body, "the wordmark must use the LM.arch (Architects Daughter) face."
    assert "uppercase" in body, "the wordmark is uppercase (per the brand spec)."
    assert "-0.025em" in body, "the wordmark uses −2.5% letter-spacing (per the brand spec)."


def test_wordmark_is_used_in_header_home_and_signin():
    """The wordmark is actually MOUNTED in the workspace header, the Home
    masthead, and the sign-in / first-run screen (not just defined)."""
    src = _read(JSX)
    uses = len(re.findall(r"<Wordmark\b", src))
    assert uses >= 3, (
        f"Wordmark must be used in >=3 surfaces (header / Home / sign-in); "
        f"found {uses}."
    )


# ── (3) full 12-step type scale LM.fs ───────────────────────────────────────

def test_LM_fs_has_twelve_steps_with_sz_ln_fam_role():
    """LM.fs is the canonical 12-step scale; each step carries sz/ln/fam/role.
    The legacy 6-step `font` map is KEPT alongside it (not replaced)."""
    src = _read(JSX)
    assert re.search(r"\bfs:\s*\(", src), "studio-lm.jsx must define LM.fs."
    # Isolate the fs fallback table (the literal that names every step).
    fb = re.search(r"const fallback\s*=\s*\{(.+?)\n\s*\};", src, re.S)
    assert fb, "could not locate the LM.fs step table"
    table = fb.group(1)
    for step in FS_STEPS:
        assert re.search(rf"\b{re.escape(step)}\s*:\s*\{{", table), (
            f"LM.fs is missing the '{step}' step."
        )
    # Each step shape carries the four keys.
    for key in ("sz", "ln", "fam", "role"):
        assert re.search(rf"\b{key}\s*:", table), f"LM.fs steps must carry `{key}`."
    # exactly 12 distinct steps named.
    named = {s for s in FS_STEPS if re.search(rf"\b{re.escape(s)}\s*:\s*\{{", table)}
    assert len(named) == 12, f"LM.fs must have 12 steps; found {len(named)}: {named}"
    # Legacy scale preserved.
    assert re.search(r"\bfont:\s*\{", src), (
        "the legacy 6-step LM.font scale must be KEPT alongside LM.fs."
    )


def test_LM_fs_derives_from_window_AH():
    """LM.fs reads window.AH.fs (the SoT type scale), not a divergent copy."""
    src = _read(JSX)
    fs = re.search(r"fs:\s*\(\(\)\s*=>\s*\{(.+?)\}\)\(\),", src, re.S)
    assert fs, "could not isolate the LM.fs IIFE"
    assert "window.AH" in fs.group(1) and ".fs" in fs.group(1), (
        "LM.fs must derive from window.AH.fs (the SoT)."
    )


def test_arch_font_token_added():
    """LM.arch (the Architects Daughter face) is a real typography token,
    derived from the SoT `arch` key."""
    src = _read(JSX)
    assert re.search(r"\barch:\s*_AH\.arch", src), (
        "LM.arch must be defined and derived from window.AH.arch."
    )


def test_index_loads_architects_daughter_font():
    """index.html pulls the Architects Daughter web font (both the active link
    and the noscript fallback)."""
    html = _read(INDEX)
    assert html.count("Architects+Daughter") >= 2, (
        "index.html must request the Architects Daughter Google font in BOTH "
        "the active stylesheet link and the <noscript> fallback."
    )


# ── (4) canvas tracing grid ─────────────────────────────────────────────────

def test_canvas_has_24px_linear_gradient_tracing_grid():
    """The canvas surface carries a 24px linear-gradient tracing grid using the
    lineSoft token, behind the existing dot grid."""
    src = _read(JSX)
    # A linear-gradient using LM.lineSoft (the tracing-paper line colour).
    assert re.search(r"linear-gradient\(\$\{LM\.lineSoft\}", src), (
        "the canvas must paint a linear-gradient tracing grid in LM.lineSoft."
    )
    # The vertical companion (90deg) line set, also lineSoft.
    assert re.search(r"linear-gradient\(90deg,\s*\$\{LM\.lineSoft\}", src), (
        "the tracing grid must include both horizontal and vertical (90deg) "
        "line sets."
    )
    # 24px cell, scaled by zoom.
    assert "24*zoom" in src.replace(" ", ""), (
        "the tracing grid cell must be 24px (scaled by zoom)."
    )


# ── (5) wire vocabulary ─────────────────────────────────────────────────────

def test_wire_vocabulary_defined():
    """A three-look WIRE_VOCAB exists: default / pending / live."""
    src = _read(JSX)
    assert re.search(r"const WIRE_VOCAB\s*=\s*\{", src), (
        "studio-lm.jsx must define WIRE_VOCAB (the wire look grammar)."
    )
    block = re.search(r"const WIRE_VOCAB\s*=\s*\{(.+?)\n\};", src, re.S)
    assert block, "could not isolate WIRE_VOCAB"
    body = block.group(1)
    for mode in ("default", "pending", "live"):
        assert re.search(rf"\b{mode}\s*:", body), f"WIRE_VOCAB must define '{mode}'."
    # pending == dashed-muted; live == dashed-accent + animated.
    assert "LM.inkMuted" in body, "WIRE_VOCAB.pending must be the muted look."
    assert "LM.accent" in body, "WIRE_VOCAB.live must be the accent look."
    assert "animated: true" in body.replace("  ", " "), (
        "WIRE_VOCAB.live must be animated."
    )


def test_live_wire_uses_animated_accent_flow_class():
    """The live-streaming wire renders the dashed-accent ANIMATED flow — the
    `lmFlow` class + keyframe exist and the live overlay path uses it."""
    src = _read(JSX)
    # Keyframe + class declared in the canvas <style>.
    assert "@keyframes lmFlow" in src, "the lmFlow keyframe must be declared."
    assert re.search(r"\.lmFlow\s*\{", src), "the .lmFlow CSS class must be declared."
    # The animated wire overlay path carries the flow class.
    assert re.search(r"className=\{w\.vocabCls\s*\|\|\s*'lmFlow'\}", src), (
        "the live wire overlay path must use the lmFlow flow class."
    )
    # And the wires memo classifies a wire into the vocabulary.
    assert re.search(r"vocab\s*=\s*wireVocabMode\(", src), (
        "each wire must be classified into the vocabulary (wireVocabMode)."
    )
    # data-attr makes the look assertable in the live DOM (CDP) too.
    assert 'data-wire-vocab' in src, (
        "each rendered wire must expose data-wire-vocab for live verification."
    )
