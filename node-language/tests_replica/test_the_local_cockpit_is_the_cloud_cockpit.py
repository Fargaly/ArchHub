"""One cockpit, served from two places, must be the same cockpit.

The audit found the local /cockpit rendering a WIRE PARAMETERS header over
zero rows: this page never loaded the parameter-type registry, and its five
atlas files were stale copies of the cloud's (200 lines behind on the panels
alone). The cloud copy is the one that gets fixed; this court keeps the local
one equal to it wherever the cloud tree is present, and keeps the registry on
the page either way.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "nodelang" / "studio"
CLOUD = ROOT.parent / "12.PRODUCTION" / "cloud_backend" / "cockpit_assets"
ATLAS = ("atlas-panels", "atlas-engine", "atlas-runtime", "atlas-side", "atlas-cockpit")


def _lf(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def test_the_cockpit_page_loads_the_parameter_type_registry_before_the_panels():
    page = (STUDIO / "cockpit.html").read_text(encoding="utf-8")
    assert 'src="/studio/param-types.jsx"' in page
    assert page.index("param-types.jsx") < page.index("atlas-panels.jsx")
    assert (STUDIO / "param-types.jsx").is_file()


def test_the_local_atlas_is_the_cloud_atlas():
    if not CLOUD.is_dir():
        pytest.skip("the cloud tree is not beside this one on this machine")
    drift = [name for name in ATLAS
             if _lf(STUDIO / (name + ".jsx")) != _lf(CLOUD / (name + ".jsx"))]
    assert not drift, "local copies behind the cloud: %s" % ", ".join(drift)


def test_the_wire_inspector_has_its_parameters():
    panels = _lf(STUDIO / "atlas-panels.jsx")
    assert "WIRE_PARAMS" in panels and "PM_TYPES" in panels
