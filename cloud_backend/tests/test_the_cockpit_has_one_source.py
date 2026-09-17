"""The founder cockpit has ONE source, and the cloud serves the build of it.

Founder, 2026-09-17: "exactly as I sent it" and "I do not want a million sources for the thing".
The cockpit modules lived twice, in 13.NODE-LANGUAGE/nodelang/studio and in cloud_backend/cockpit_assets,
and were mirrored by hand, so they drifted: the deployed side panel was the library he had rejected, and
the cloud tokens lacked the theme store Studio reads. The .jsx now live only in the studio tree
(tokens.jsx and param-types.jsx shared with Studio); tools/build_cockpit_assets.js compiles from there
and writes only compiled output here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

MODULES = ("tokens", "param-types", "cockpit-core", "hub-kit", "atlas-engine", "atlas-runtime",
           "atlas-panels", "atlas-side", "atlas-cockpit")
BACKEND = Path(__file__).resolve().parents[1]
ASSETS = BACKEND / "cockpit_assets"
COMPILED = ASSETS / "compiled"
BUILD = BACKEND / "tools" / "build_cockpit_assets.js"
STUDIO = Path(__file__).resolve().parents[3] / "13.NODE-LANGUAGE" / "nodelang" / "studio"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_no_cockpit_source_is_copied_into_the_cloud_tree():
    copies = sorted(path.name for path in ASSETS.glob("*.jsx"))
    if (ASSETS / "map-data.js").exists():
        copies.append("map-data.js")   # the map is served from the live push, never from a file here
    assert not copies, "cockpit sources copied into cockpit_assets: %s" % ", ".join(copies)


def test_the_build_compiles_from_the_studio_tree():
    script = BUILD.read_text(encoding="utf-8")
    assert "'13.NODE-LANGUAGE', 'nodelang', 'studio'" in script
    assert "ARCHHUB_STUDIO_SOURCES" in script
    assert "path.join(root, name + '.jsx')" not in script, "the build still reads a copy in cockpit_assets"
    for module in MODULES:
        assert "'%s'" % module in script, module


def test_every_module_is_built_and_the_manifest_names_its_source():
    manifest = json.loads((COMPILED / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_root"] == "13.NODE-LANGUAGE/nodelang/studio"
    entries = {entry["module"]: entry for entry in manifest["files"]}
    assert set(MODULES) <= set(entries), sorted(set(MODULES) - set(entries))
    for module in MODULES:
        assert _sha(COMPILED / (module + ".js")) == entries[module]["output_sha256"], (
            "%s.js is not the output the manifest records" % module)


def test_the_bundle_is_the_build_of_the_current_source():
    if not STUDIO.is_dir():
        pytest.skip("the cockpit source tree is not beside this checkout")
    manifest = json.loads((COMPILED / "manifest.json").read_text(encoding="utf-8"))
    built = {entry["module"]: entry["source_sha256"] for entry in manifest["files"]}
    stale = [module for module in MODULES if built.get(module) != _sha(STUDIO / (module + ".jsx"))]
    assert not stale, ("compiled bundle is behind its source for %s; run "
                       "node cloud_backend/tools/build_cockpit_assets.js" % ", ".join(stale))