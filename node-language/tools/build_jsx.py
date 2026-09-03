#!/usr/bin/env python
"""build_jsx.py — precompile ArchHub's JSX to disk so boot never recompiles.

Boot-lag root cause (founder, 2026-06-01 "FIX THE BOOT LAG ROOT"):
  app/web_ui/studio-lm.jsx (~708 KB) was Babel-compiled IN-BROWSER on every
  cache-miss boot (~1.9 s), AND the 3 MB vendored babel.min.js was loaded
  synchronously on EVERY launch (even cache hits, where it's unused).

This tool runs the app's EXACT Babel transform AHEAD OF TIME, in Node, using
the same vendored `app/web_ui/vendor/babel.min.js`. It writes

    app/web_ui/studio-lm.compiled.js
    app/web_ui/app-boot.compiled.js

each with a header comment that embeds the SHA-256 of the source .jsx it was
built from. The loader (jsx-boot.js) reads that header: if the embedded sha
matches the live .jsx sha, it loads the precompiled .js directly via <script>
(NO Babel, NO localStorage round-trip, ~instant) — otherwise it falls back to
the in-browser Babel path and lazily injects babel.min.js.

Transform options — IDENTICAL semantics to the in-browser path:
  presets: [['env', {targets: {chrome: <N>}}], 'react']
  sourceType: 'script'

WHY a pinned chrome target (not bare 'env'):
  In QtWebEngine, babel-standalone auto-targets the LIVE Chromium (this build
  reports Chromium 140) → it PRESERVES const/let → real TDZ semantics. Bare
  Node has no live browser, so preset-env downlevels const→var and ERASES the
  TDZ. We pin a modern chrome target so the on-disk artifact reproduces the
  app's real const-preserving transform byte-for-behaviour. Default 140 matches
  the bundled QtWebEngine; override with --chrome / ARCHHUB_JSX_CHROME.

Idempotent: if a compiled file already exists AND its embedded source-sha
matches the current source sha, that file is skipped ("up to date"). So the
pre-launch hook is a fast no-op when nothing changed, and recompiles only the
.jsx that actually changed.

Usage:
    python tools/build_jsx.py             # build/refresh both artifacts
    python tools/build_jsx.py --check     # exit 1 if any artifact is stale
    python tools/build_jsx.py --force     # rebuild even if sha matches
    python tools/build_jsx.py --chrome 112

Programmatic (used by app/main.py pre-launch hook):
    from build_jsx import build_all
    build_all()        # returns a summary dict; never raises on Node-missing
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

# ── Paths ───────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_UI = REPO_ROOT / "app" / "web_ui"
VENDOR_BABEL = WEB_UI / "vendor" / "babel.min.js"

# Source .jsx → compiled .js. Order is irrelevant here (each is independent);
# the loader controls eval order (studio-lm before app-boot).
JSX_FILES = ["studio-lm.jsx", "app-boot.jsx"]

# Default chrome target: the QtWebEngine Chromium major this app ships with.
# Anything >= 112 preserves const; 140 is exact for the current bundle.
DEFAULT_CHROME = os.environ.get("ARCHHUB_JSX_CHROME", "140")

# Header markers the loader (jsx-boot.js) greps for.
SHA_MARKER = "ARCHHUB_JSX_SRC_SHA256:"
SRC_MARKER = "ARCHHUB_JSX_SRC:"


# ── sha helpers ─────────────────────────────────────────────────────
def source_sha(path: Path) -> str:
    """SHA-256 of the raw source bytes.

    MUST match the loader's WebCrypto digest, which hashes the exact text
    returned by fetch().text(). fetch() preserves the file's bytes verbatim
    (no newline translation), so we hash raw bytes here too — never re-encode
    through a normalised string.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def embedded_sha(compiled_path: Path) -> Optional[str]:
    """Read the SHA the compiled artifact was built from, or None."""
    if not compiled_path.exists():
        return None
    try:
        # The marker lives in the first few header lines; read a small prefix.
        with compiled_path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except Exception:
        return None
    for line in head.splitlines():
        idx = line.find(SHA_MARKER)
        if idx != -1:
            return line[idx + len(SHA_MARKER):].strip()
    return None


def compiled_path_for(jsx_name: str) -> Path:
    return WEB_UI / (jsx_name[: -len(".jsx")] + ".compiled.js")


# ── Node detection ──────────────────────────────────────────────────
def _node_exe() -> Optional[str]:
    return shutil.which("node") or shutil.which("node.exe")


# The Node driver. Loads the SAME vendored babel.min.js the browser ships
# (the UMD bundle's CommonJS branch returns the `Babel` object — identical
# transform engine + version as the in-browser <script> path), then runs the
# exact transform and writes the compiled code to stdout. Source is passed via
# a temp file (avoids arg-length / quoting limits for a 708 KB file).
_NODE_DRIVER = r"""
'use strict';
const fs = require('fs');
const babelPath = process.argv[2];
const srcPath = process.argv[3];
const chrome = process.argv[4];
let Babel;
try {
  Babel = require(babelPath);          // UMD → CommonJS export of Babel
} catch (e) {
  console.error('BUILD_JSX_NODE_ERROR: cannot load babel: ' + (e && e.message || e));
  process.exit(11);
}
if (!Babel || typeof Babel.transform !== 'function') {
  console.error('BUILD_JSX_NODE_ERROR: babel.transform unavailable after require');
  process.exit(11);
}
const src = fs.readFileSync(srcPath, 'utf8');
let out;
try {
  out = Babel.transform(src, {
    presets: [['env', { targets: { chrome: String(chrome) } }], 'react'],
    sourceType: 'script',
  });
} catch (e) {
  console.error('BUILD_JSX_NODE_ERROR: transform failed: ' + (e && e.message || e));
  process.exit(12);
}
process.stdout.write(out.code || '');
"""


class BuildError(RuntimeError):
    pass


def _run_babel_node(jsx_path: Path, chrome: str) -> str:
    """Invoke Node to Babel-transform `jsx_path`; return compiled JS."""
    node = _node_exe()
    if not node:
        raise BuildError("node not found on PATH — cannot precompile JSX")
    if not VENDOR_BABEL.exists():
        raise BuildError(f"vendored babel missing at {VENDOR_BABEL}")

    # Write the driver to a temp .cjs so Node treats it as CommonJS regardless
    # of any ambient package.json "type":"module".
    with tempfile.NamedTemporaryFile(
        "w", suffix=".cjs", delete=False, encoding="utf-8"
    ) as drv:
        drv.write(_NODE_DRIVER)
        driver_path = drv.name
    try:
        proc = subprocess.run(
            [node, driver_path, str(VENDOR_BABEL), str(jsx_path), str(chrome)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=240,
        )
    finally:
        try:
            os.unlink(driver_path)
        except OSError:
            pass

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"node exit {proc.returncode}"
        raise BuildError(f"Babel transform via Node failed: {err}")
    code = proc.stdout
    if not code or not code.strip():
        raise BuildError(
            f"Babel produced empty output for {jsx_path.name} "
            f"(stderr: {(proc.stderr or '').strip()[:200]})"
        )
    return code


def _header(jsx_name: str, sha: str, chrome: str) -> str:
    """The header comment block prepended to every compiled artifact."""
    return (
        "// ===================================================================\n"
        "// AUTO-GENERATED by tools/build_jsx.py — DO NOT EDIT BY HAND.\n"
        f"// {SRC_MARKER} {jsx_name}\n"
        f"// {SHA_MARKER} {sha}\n"
        f"// Transform: vendored babel.min.js · presets[env(chrome>={chrome}),react] · sourceType:script\n"
        "// The loader (app/web_ui/jsx-boot.js) loads this file directly when the\n"
        "// embedded sha matches the live .jsx sha — no in-browser Babel, no\n"
        "// localStorage round-trip. Stale? Re-run: python tools/build_jsx.py\n"
        "// ===================================================================\n"
    )


def build_one(jsx_name: str, chrome: str = DEFAULT_CHROME,
              force: bool = False) -> dict:
    """Build/refresh one artifact. Returns a status dict.

    status: 'skipped' (sha matched), 'built', or 'error'.
    """
    jsx_path = WEB_UI / jsx_name
    out_path = compiled_path_for(jsx_name)
    if not jsx_path.exists():
        return {"file": jsx_name, "status": "error",
                "error": f"source missing: {jsx_path}"}

    src_sha = source_sha(jsx_path)
    if not force and embedded_sha(out_path) == src_sha:
        return {"file": jsx_name, "status": "skipped", "sha": src_sha,
                "out": out_path.name}

    try:
        compiled = _run_babel_node(jsx_path, chrome)
    except BuildError as ex:
        return {"file": jsx_name, "status": "error", "error": str(ex)}

    text = _header(jsx_name, src_sha, chrome) + compiled
    # Atomic write: tmp in the same dir + replace, so a crash mid-write never
    # leaves a half-written artifact the loader might pick up.
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, out_path)
    return {"file": jsx_name, "status": "built", "sha": src_sha,
            "out": out_path.name, "bytes": len(text)}


def build_all(chrome: str = DEFAULT_CHROME, force: bool = False,
              quiet: bool = True) -> dict:
    """Build/refresh every JSX artifact. Safe to call from the app's
    pre-launch hook: never raises — a Node-missing / transform error is
    captured per-file so the app can still launch on the in-browser
    fallback path.
    """
    results = [build_one(n, chrome=chrome, force=force) for n in JSX_FILES]
    summary = {
        "ok": all(r["status"] != "error" for r in results),
        "any_built": any(r["status"] == "built" for r in results),
        "results": results,
    }
    if not quiet:
        for r in results:
            if r["status"] == "error":
                print(f"  [build_jsx] {r['file']}: ERROR — {r.get('error')}")
            else:
                print(f"  [build_jsx] {r['file']}: {r['status']} "
                      f"-> {r.get('out')}")
    return summary


def check_all(chrome: str = DEFAULT_CHROME) -> bool:
    """True iff every artifact exists and its sha matches the live source."""
    for n in JSX_FILES:
        jsx_path = WEB_UI / n
        out_path = compiled_path_for(n)
        if not jsx_path.exists():
            continue
        if embedded_sha(out_path) != source_sha(jsx_path):
            return False
    return True


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Precompile ArchHub JSX to disk.")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any artifact is stale (no writes)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when sha matches")
    ap.add_argument("--chrome", default=DEFAULT_CHROME,
                    help=f"preset-env chrome target (default {DEFAULT_CHROME})")
    ap.add_argument("--json", action="store_true",
                    help="print a JSON summary")
    args = ap.parse_args(argv)

    if args.check:
        fresh = check_all(chrome=args.chrome)
        if args.json:
            print(json.dumps({"fresh": fresh}))
        else:
            print("up to date" if fresh else "STALE — run: python tools/build_jsx.py")
        return 0 if fresh else 1

    summary = build_all(chrome=args.chrome, force=args.force, quiet=False)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        built = [r["file"] for r in summary["results"] if r["status"] == "built"]
        skipped = [r["file"] for r in summary["results"] if r["status"] == "skipped"]
        if built:
            print(f"build_jsx: built {len(built)} — {', '.join(built)}")
        if skipped:
            print(f"build_jsx: up to date, skipped {len(skipped)} - "
                  f"{', '.join(skipped)}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
