"""VERSION-FOOTER-REAL lane — kill the "still looks 80% / prototype" labels.

The founder opened v1.6.2 and still saw "80% done shit": the footer status bar
hardcoded **"v1.4 prototype"** on every screen, regardless of the real running
version, and a node-output panel showed **"3D VIEWER — COMING SOON"**. Both are
the exact "looks-unfinished / for-show-only" class the founder banned.

Root cause: there was no single version source of truth surfaced to the UI —
the footer hand-typed a frozen "v1.4 prototype" while `get_version()` (reading
the real `VERSION` file the release writes) was ignored, and the version
fallbacks scattered ("1.4.0-alpha" in bridge, "1.5.0-alpha" in settings).

RED→GREEN gates (proven RED by `git stash` of the lane diff):
  • Footer renders the REAL version via `get_version()` — no "v1.4 prototype".
  • The node-output view/model panel is an honest geometry inspector
    ("GEOMETRY · <type> · N verts …") — no "COMING SOON" teaser.
  • Version fallbacks unified to one honest "0.0.0-dev" marker (no stale
    "1.4.0-alpha" / "1.5.0-alpha" that could surface).

Source guards run on the comment-stripped .jsx text (same mechanism as
tests/test_final_shells_graph.py) so a comment mentioning the old literal can't
satisfy a pass. A bundle guard confirms the committed compiled.js carries it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

_WEB = APP_ROOT / "web_ui"
_JSX_SRC = (_WEB / "studio-lm.jsx").read_text(encoding="utf-8")
# Comment-stripped view — an assertion can't be satisfied by a `//` comment.
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
_COMPILED = (_WEB / "studio-lm.compiled.js").read_text(encoding="utf-8")
# The compiled bundle keeps comments; strip `//` there too so the bundle guard
# reflects only emitted code/strings, not the lane's explanatory comments.
_COMPILED_CODE = re.sub(r"//[^\n]*", "", _COMPILED)


def _window(src: str, anchor: str, size: int = 2600) -> str:
    i = src.find(anchor)
    assert i >= 0, f"anchor not found: {anchor!r}"
    return src[i:i + size]


# ───────────────────────── footer version label ─────────────────────────
class TestFooterVersionReal:
    def test_no_v14_prototype_literal_in_source(self):
        """The hardcoded 'v1.4 prototype' footer literal is gone (comments
        excluded — the lane's own comments avoid the exact literal)."""
        present = "v1.4 prototype" in _JSX_CODE
        assert not present, "the hardcoded 'v1.4 prototype' footer literal remains"

    def test_footer_renders_real_version_via_get_version(self):
        """ServerStrip fetches the real version through bridgeAsync('get_version')
        and renders it — the footer is no longer a frozen constant."""
        comp = _window(_JSX_CODE, "const ServerStrip = (", size=5000)
        assert "bridgeAsync('get_version')" in comp, (
            "ServerStrip must fetch the real version via get_version()")
        # The rendered pill uses the fetched `ver` state (v<semver>), not a literal.
        assert "`v${ver}`" in comp, (
            "footer must render the live version state, not a hardcoded string")
        # The fetch is gated on archhubReady — ServerStrip can mount before the
        # bridge connects; a bare mount-time call would stick on the fallback.
        assert "archhubReady" in comp, (
            "version fetch must await window.archhubReady so it doesn't resolve "
            "null before the bridge is live")

    def test_no_prototype_word_in_footer_pill(self):
        """The footer ACTIONS group (settings + version pill) carries no
        'prototype' wording."""
        comp = _window(_JSX_CODE, "GROUP — ACTIONS", size=600)
        assert "prototype" not in comp.lower(), (
            "footer actions group must not call the product a prototype")


# ──────────────────── node-output geometry inspector ────────────────────
class TestGeometryInspectorHonest:
    def test_no_coming_soon_teaser(self):
        """No 'COMING SOON' teaser anywhere in rendered code."""
        assert "COMING SOON" not in _JSX_CODE, "a 'COMING SOON' teaser remains"

    def test_view_model_branch_is_real_inspector(self):
        """The view/model output branch renders an honest GEOMETRY summary built
        from the REAL value (vertex/face/item counts), not a placeholder."""
        comp = _window(_JSX_CODE, "if (as === 'view' || as === 'model')", size=1400)
        assert "GEOMETRY" in comp, "view/model branch must show an honest GEOMETRY label"
        assert "verts" in comp and "face idx" in comp, (
            "the inspector must derive real vertex/face counts from the value")


# ───────────────────── version source-of-truth hygiene ─────────────────────
class TestVersionFallbacksUnified:
    def test_bridge_get_version_no_stale_alpha(self):
        src = (APP_ROOT / "bridge.py").read_text(encoding="utf-8")
        assert "1.4.0-alpha" not in src, "bridge.py keeps a stale '1.4.0-alpha' fallback"
        assert "0.0.0-dev" in src, "bridge.py get_version fallback must be the unified dev marker"

    def test_settings_read_version_no_stale_alpha(self):
        src = (APP_ROOT / "settings_dialog.py").read_text(encoding="utf-8")
        assert "1.5.0-alpha" not in src, "settings_dialog.py keeps a stale '1.5.0-alpha' fallback"
        assert "0.0.0-dev" in src, "settings_dialog.py _read_version fallback must be the unified dev marker"

    def test_version_file_is_semver(self):
        ver = (APP_ROOT.parent / "VERSION").read_text(encoding="utf-8").strip()
        assert re.fullmatch(r"\d+\.\d+\.\d+", ver), f"VERSION must be clean semver, got {ver!r}"


# ──────────────────────────── bundle guard ────────────────────────────
class TestCompiledBundleCarriesFix:
    def test_compiled_has_no_v14_prototype(self):
        assert "v1.4 prototype" not in _COMPILED_CODE, (
            "committed compiled.js still emits 'v1.4 prototype' — recompile needed")

    def test_compiled_has_get_version_footer(self):
        assert "get_version" in _COMPILED_CODE and "GEOMETRY" in _COMPILED_CODE, (
            "committed compiled.js must carry the version-footer + geometry fixes")
