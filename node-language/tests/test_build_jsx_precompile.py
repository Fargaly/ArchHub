"""Boot-lag root fix (founder, 2026-06-01 "FIX THE BOOT LAG ROOT") — tests.

The fix: precompile the JSX to disk (tools/build_jsx.py), keep it fresh at
launch (app/main.py pre-launch hook), and have the loader (jsx-boot.js) prefer
the precompiled .js when its embedded sha matches the live .jsx — loading it
directly with NO in-browser Babel and NO 3 MB babel.min.js parse. babel.min.js
is lazily injected ONLY on the fallback path.

These tests pin every load-bearing piece so a regression FAILS at PR time:

  1. build_jsx produces a sha-matching artifact (REAL build, needs Node) +
     is idempotent (second run rebuilds nothing).
  2. The COMMITTED artifacts on disk are fresh — embedded sha matches the live
     source (pure-Python sha, no Node) — so the founder's first relaunch is
     already fast and the artifacts never silently go stale.
  3. The loader gate logic exists in jsx-boot.js: precompiled-first, sha gate,
     lazy babel on fallback only.
  4. index.html no longer loads babel.min.js synchronously.
  5. main.py has the pre-launch precompile hook.
  6. The splash floor was trimmed off the 350ms dead-time.

The end-to-end load-precompiled-and-mount proof (eval the artifact with NO
Babel + mount <StudioLM/> + a TDZ positive control + the timing delta) lives in
tools/verify_precompiled.cjs (Node + jsdom + real vendored React).
"""
from __future__ import annotations

import hashlib
import importlib
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB_UI = REPO / "app" / "web_ui"
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

JSX_FILES = ["studio-lm.jsx", "app-boot.jsx"]


def _src_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _embedded_sha(compiled: Path) -> str | None:
    if not compiled.exists():
        return None
    head = compiled.read_text(encoding="utf-8", errors="replace")[:4096]
    m = re.search(r"ARCHHUB_JSX_SRC_SHA256:\s*([0-9a-f]{64})", head)
    return m.group(1) if m else None


def _have_node() -> bool:
    return bool(shutil.which("node") or shutil.which("node.exe"))


# ── 1. build_jsx produces a sha-matching artifact + is idempotent ───────────
# (Real build → needs Node. Skips cleanly where Node is absent, e.g. some CI.)

@pytest.mark.skipif(not _have_node(), reason="node not on PATH")
def test_build_jsx_produces_sha_matching_artifact(tmp_path):
    """build_one writes a compiled artifact whose embedded sha == source sha."""
    build_jsx = importlib.import_module("build_jsx")
    for name in JSX_FILES:
        res = build_jsx.build_one(name, force=True)
        assert res["status"] == "built", f"{name}: {res}"
        out = build_jsx.compiled_path_for(name)
        assert out.exists(), f"{name}: artifact not written"
        live_sha = _src_sha(WEB_UI / name)
        assert _embedded_sha(out) == live_sha, (
            f"{name}: embedded sha must equal live source sha"
        )
        # The artifact must be real compiled JS (JSX lowered to createElement),
        # not the raw source copied through.
        body = out.read_text(encoding="utf-8")
        assert "React.createElement" in body, f"{name}: not Babel-compiled"


@pytest.mark.skipif(not _have_node(), reason="node not on PATH")
def test_build_jsx_is_idempotent():
    """A second build_all with everything current rebuilds NOTHING — the
    pre-launch hook is a fast no-op when no .jsx changed."""
    build_jsx = importlib.import_module("build_jsx")
    build_jsx.build_all(force=True)          # make everything current
    summary = build_jsx.build_all()          # re-run, no force
    assert summary["ok"] is True
    assert summary["any_built"] is False, (
        "idempotent re-run must skip all (got builds: "
        f"{[r for r in summary['results'] if r['status']=='built']})"
    )
    for r in summary["results"]:
        assert r["status"] == "skipped", r


@pytest.mark.skipif(not _have_node(), reason="node not on PATH")
def test_build_jsx_check_passes_after_build():
    build_jsx = importlib.import_module("build_jsx")
    build_jsx.build_all(force=True)
    assert build_jsx.check_all() is True


# ── 2. The COMMITTED artifacts on disk are fresh (pure-Python; no Node) ──────

def test_compiled_artifacts_exist_and_committed():
    """The precompiled artifacts must be present in-tree so the founder's
    FIRST relaunch is already fast (no recompile)."""
    for name in JSX_FILES:
        out = WEB_UI / (name[: -len(".jsx")] + ".compiled.js")
        assert out.exists(), (
            f"{out.name} missing — commit the precompiled artifact so first "
            f"relaunch is fast. Run: python tools/build_jsx.py"
        )


def test_committed_artifacts_sha_matches_live_source():
    """The embedded sha of each committed artifact must equal the live .jsx
    sha. If this fails, the artifact is STALE — `python tools/build_jsx.py`
    regenerates it. (This is the gate the loader uses to pick the fast path;
    a stale artifact would silently fall back to the slow Babel boot.)"""
    for name in JSX_FILES:
        out = WEB_UI / (name[: -len(".jsx")] + ".compiled.js")
        live = _src_sha(WEB_UI / name)
        emb = _embedded_sha(out)
        assert emb == live, (
            f"{out.name} is STALE (embedded {emb} != live {live}). "
            f"Run: python tools/build_jsx.py"
        )


def test_artifact_sha_header_matches_webcrypto_digest():
    """The loader computes the live sha via WebCrypto over fetch().text().
    That equals hashlib.sha256(raw bytes) ONLY if the source is BOM-free UTF-8.
    Pin that invariant so a BOM/encoding change can't silently break the gate
    (which would force every boot onto the slow fallback)."""
    for name in JSX_FILES:
        raw = (WEB_UI / name).read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf", f"{name}: has a UTF-8 BOM — breaks sha gate"
        # round-trip: decode as UTF-8 (fetch().text()) then re-encode (TextEncoder)
        assert raw.decode("utf-8").encode("utf-8") == raw, (
            f"{name}: not byte-stable through UTF-8 decode/encode"
        )


# ── 3. Loader gate logic: precompiled-first, sha gate, lazy babel ───────────

def _jsx_boot() -> str:
    return (WEB_UI / "jsx-boot.js").read_text(encoding="utf-8")


def test_loader_prefers_precompiled_with_sha_gate():
    boot = _jsx_boot()
    # Reads the .compiled.js for each file.
    assert "compiledUrlFor" in boot and ".compiled.js" in boot
    # Reads the embedded sha header (same marker build_jsx writes).
    assert "ARCHHUB_JSX_SRC_SHA256" in boot
    assert "readEmbeddedSha" in boot
    # The gate: embedded sha === live src sha → take precompiled path.
    assert "tryPrecompiled" in boot
    assert re.search(r"embedded\s*===\s*srcSha", boot), (
        "loader must gate the fast path on embedded sha === live src sha"
    )


def test_loader_lazy_loads_babel_only_on_fallback():
    boot = _jsx_boot()
    # Babel is injected via a lazy <script>, not assumed present.
    assert "ensureBabel" in boot
    assert "vendor/babel.min.js" in boot
    # The lazy loader builds a <script> for babel (not a static include).
    assert re.search(r"ensureBabel[\s\S]{0,400}vendor/babel\.min\.js", boot), (
        "babel.min.js must be lazily script-injected inside ensureBabel"
    )
    # ensureBabel is only awaited inside the Babel-compile fallback path.
    assert "await ensureBabel()" in boot


def test_loader_falls_back_to_babel_compile_path():
    """The in-browser fallback (Babel.transform + localStorage cache) must
    still exist — no white screen when an artifact is missing/stale."""
    boot = _jsx_boot()
    assert "compileWithBabel" in boot
    assert "Babel.transform" in boot
    assert "jsx_cache_v1_" in boot          # localStorage fallback cache kept
    assert "presets: ['env', 'react']" in boot or "presets:['env','react']" in boot


# ── 4. index.html no longer loads babel.min.js synchronously ────────────────

def test_index_html_does_not_eagerly_load_babel():
    html = (WEB_UI / "index.html").read_text(encoding="utf-8")
    # No static <script src=".../babel.min.js"> tag anymore.
    assert not re.search(r'<script[^>]+src=["\'][^"\']*babel\.min\.js', html), (
        "index.html must NOT load babel.min.js synchronously — it's lazy now"
    )
    # React is still eagerly loaded (always needed).
    assert re.search(r'<script[^>]+react\.production\.min\.js', html)
    # The boot loader is still wired.
    assert "jsx-boot.js" in html


# ── 5. main.py pre-launch precompile hook ───────────────────────────────────

def test_main_has_prelaunch_precompile_hook():
    main_src = (REPO / "app" / "main.py").read_text(encoding="utf-8")
    assert "_precompile_jsx_at_startup" in main_src
    assert "build_jsx" in main_src
    # Hook is actually invoked at import time (before the page loads).
    assert re.search(r"^_precompile_jsx_at_startup\(\)", main_src, re.M), (
        "the precompile hook must be called at startup, not just defined"
    )


# ── 6. Splash floor trimmed off the 350ms dead-time ─────────────────────────

def test_splash_floor_trimmed():
    boot = (WEB_UI / "app-boot.jsx").read_text(encoding="utf-8")
    # The 350ms floor is gone.
    assert "}, 350)" not in boot, "the 350ms splash floor must be trimmed"
    # A precompiled-aware, smaller floor is used.
    assert "__archhub_jsx_boot" in boot and "precompiled" in boot
    # Floors are <= 120ms.
    floors = [int(x) for x in re.findall(r"floor\s*=\s*(\d+)", boot)]
    assert floors, "expected a `floor = <ms>` assignment in SplashFader"
    assert max(floors) <= 120, f"splash floor must be <=120ms, got {floors}"
