"""AgDR-0026 Phase 1 — vendor + production React + Babel for studio-lm
cold-start lag fix.

Phase 1 pins:
  - vendored React/ReactDOM/Babel files exist
  - index.html no longer fetches from unpkg.com / any CDN
  - React build is `.production.min.js` (not `.development.js`)
  - Babel-standalone is bundled (Phase 2 will cache its output)
"""
from __future__ import annotations

from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "app" / "web_ui"
INDEX = WEB / "index.html"
VENDOR = WEB / "vendor"
DOCS = Path(__file__).resolve().parents[1] / "docs"


# ─── 1. vendored files exist ─────────────────────────────────────────


def test_vendored_react_production_present():
    p = VENDOR / "react.production.min.js"
    assert p.exists(), "react.production.min.js must be vendored"
    # Production React is much smaller than dev (~10 KB vs ~230 KB).
    assert p.stat().st_size < 50_000


def test_vendored_react_dom_production_present():
    p = VENDOR / "react-dom.production.min.js"
    assert p.exists(), "react-dom.production.min.js must be vendored"
    # Production ReactDOM is much smaller than dev (~130 KB vs ~1.1 MB).
    assert p.stat().st_size < 300_000


def test_vendored_babel_present():
    p = VENDOR / "babel.min.js"
    assert p.exists(), "babel.min.js must be vendored for offline transpile"
    # Babel-standalone is ~3 MB; just sanity-check it's there + non-trivial.
    assert p.stat().st_size > 1_000_000


# ─── 2. index.html points at vendored copies, not CDN ───────────────


def test_index_html_no_cdn_urls():
    text = INDEX.read_text(encoding="utf-8")
    # No unpkg.com or any other CDN for React / Babel.
    assert "unpkg.com" not in text, (
        "index.html still fetches React/Babel from unpkg — cold-start "
        "blocks on offline / slow WiFi"
    )
    assert "cdn.jsdelivr.net" not in text


def test_index_html_loads_vendored_files():
    text = INDEX.read_text(encoding="utf-8")
    # React/ReactDOM are always needed → still eagerly loaded.
    assert 'src="vendor/react.production.min.js"' in text
    assert 'src="vendor/react-dom.production.min.js"' in text
    # Phase 3 (boot-lag root fix, 2026-06-01): babel.min.js is NO LONGER loaded
    # synchronously here. It was 3 MB read+parsed on EVERY launch (even cache
    # hits, where it went unused). The loader now prefers the precompiled
    # on-disk artifacts and lazily <script>-injects babel.min.js ONLY on the
    # in-browser fallback path. So index.html must NOT statically include it.
    assert 'src="vendor/babel.min.js"' not in text, (
        "babel.min.js must NOT be eagerly loaded in index.html — Phase 3 makes "
        "it lazy (jsx-boot.js injects it only on the precompiled-miss fallback)"
    )


def test_index_html_uses_production_react_not_dev():
    """Switching from .development.js to .production.min.js is the
    biggest single perf win on cold start.  Pin it so we don't
    accidentally regress when bumping React."""
    text = INDEX.read_text(encoding="utf-8")
    assert "react.development.js" not in text
    assert "react-dom.development.js" not in text


# ─── Phase 2 — jsx-boot.js + app-boot.jsx ──────────────────────────


def test_jsx_boot_loader_present():
    p = WEB / "jsx-boot.js"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    # The cache key namespace.
    assert "jsx_cache_v1_" in src
    # SHA-256 via WebCrypto.
    assert "SHA-256" in src
    # Babel fallback on cache miss.
    assert "Babel.transform" in src
    # Boot order — studio-lm → app-boot. shared-data.jsx was removed
    # 2026-05-31 (140 lines of stale demo data, zero live consumers); it
    # must NOT be fetched/compiled/eval'd on boot anymore.
    assert "'shared-data.jsx'" not in src
    assert "'studio-lm.jsx'" in src
    assert "'app-boot.jsx'" in src


def test_app_boot_jsx_carries_root_mount():
    p = WEB / "app-boot.jsx"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    # The React mount call moved from index.html into here.
    assert "ReactDOM.createRoot" in src
    assert "ErrorBoundary" in src
    # Bridge pulls still wired.
    assert "pullAll" in src
    assert "get_sessions" in src


def test_index_html_uses_boot_loader_not_inline_babel():
    text = INDEX.read_text(encoding="utf-8")
    # The boot loader replaces the inline <script type="text/babel">.
    assert 'src="jsx-boot.js"' in text
    # No more inline JSX in index.html.
    assert 'type="text/babel"' not in text
    # The JSX files aren't <script>-tagged directly anymore.
    assert 'src="shared-data.jsx"' not in text
    assert 'src="studio-lm.jsx"' not in text


# ─── 3. AgDR-0026 doc exists ────────────────────────────────────────


def test_agdr_0026_exists():
    p = DOCS / "agdr" / "AgDR-0026-studio-lm-cold-start-lag.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: executed" in text
    # The decision names the three concrete fix phases.
    assert "Vendor" in text
    assert "production" in text.lower()
    assert "JSX" in text
    # Acceptance has a concrete time budget.
    assert "loadEventEnd" in text or "≤" in text
