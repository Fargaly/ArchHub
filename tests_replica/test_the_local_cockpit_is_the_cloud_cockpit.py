"""One cockpit, served from two places, must be the same cockpit.

The audit found the local /cockpit rendering a WIRE PARAMETERS header over
zero rows: this page never loaded the parameter-type registry, and its five
atlas files were stale copies of the cloud's (200 lines behind on the panels
alone). The cloud copy is the one that gets fixed; this court keeps the local
one equal to it wherever the cloud tree is present, and keeps the registry on
the page either way.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "nodelang" / "studio"
CLOUD = ROOT.parent / "12.PRODUCTION" / "cloud_backend" / "cockpit_assets"
# ONE SOURCE (founder, 2026-09-17): every cockpit module lives here, tokens.jsx and param-types.jsx
# shared with Studio. The cloud tree holds no copy; its build compiles these files.
ATLAS = ("tokens", "param-types", "cockpit-core", "hub-kit", "atlas-engine", "atlas-runtime",
         "atlas-panels", "atlas-side", "atlas-cockpit")


def _lf(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def test_the_cockpit_page_loads_the_parameter_type_registry_before_the_panels():
    page = (STUDIO / "cockpit.html").read_text(encoding="utf-8")
    assert 'src="/studio/param-types.jsx"' in page
    assert page.index("param-types.jsx") < page.index("atlas-panels.jsx")
    assert (STUDIO / "param-types.jsx").is_file()


def test_the_cloud_holds_no_copy_of_a_cockpit_source():
    if not CLOUD.is_dir():
        pytest.skip("the cloud tree is not beside this one on this machine")
    copies = [name + ".jsx" for name in ATLAS if (CLOUD / (name + ".jsx")).exists()]
    copies += ["map-data.js"] if (CLOUD / "map-data.js").exists() else []
    assert not copies, "cockpit sources copied into the cloud tree: %s" % ", ".join(copies)


def test_the_cloud_bundle_is_the_build_of_these_sources():
    if not CLOUD.is_dir():
        pytest.skip("the cloud tree is not beside this one on this machine")
    manifest = json.loads((CLOUD / "compiled" / "manifest.json").read_text(encoding="utf-8"))
    built = {entry["module"]: entry["source_sha256"] for entry in manifest["files"]}
    stale = [name for name in ATLAS
             if built.get(name) != hashlib.sha256((STUDIO / (name + ".jsx")).read_bytes()).hexdigest()]
    assert not stale, ("the cloud bundle is not the build of the current source for %s; run "
                       "node cloud_backend/tools/build_cockpit_assets.js" % ", ".join(stale))


def test_the_wire_inspector_has_its_parameters():
    panels = _lf(STUDIO / "atlas-panels.jsx")
    assert "WIRE_PARAMS" in panels and "PM_TYPES" in panels
