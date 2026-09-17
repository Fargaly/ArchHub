"""The cockpit draws the push, and keeps only layout of its own.

SPEC.md:232 -- "No lens may own a duplicate truth field."

The cockpit merged its browser localStorage snapshot into the live push and
DREW SAVED NODES AS REAL: a domain or node the push no longer contained was
still rendered, so localStorage was its only store. The founder opened his
cockpit and read a wall of agent-session cards his graph had already stopped
reporting -- the live map held 18 domains with every session inside one
Runtime Sessions place (audit, 2026-09-07).

Layout is his: where he dragged a card stays local. Content is the graph's.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud_backend" / "cockpit_assets"
APP = ROOT.parent / "13.NODE-LANGUAGE" / "nodelang" / "studio"
COCKPIT = (APP / "atlas-cockpit.jsx").read_text(encoding="utf-8")   # the one source


def _merge_body() -> str:
    start = COCKPIT.index("const mergeLive = (L, S) =>")
    return COCKPIT[start:COCKPIT.index("let data = live", start)]


def test_no_saved_node_or_domain_is_ever_drawn():
    body = _merge_body()
    assert ".concat((S.nodes" not in body, (
        "a saved node the push does not have is localStorage pretending to be "
        "the graph"
    )
    assert ".concat((S.domains" not in body
    assert ".concat((S.wires" not in body, "a wire is a relation, so it is content"


def test_layout_is_still_his():
    """Where he dragged a card must survive a reload."""
    body = _merge_body()
    assert "sd[d.key].x" in body and "sd[d.key].y" in body
    assert "sn[n.id].x" in body and "sn[n.id].y" in body


def test_the_content_comes_from_the_live_push():
    body = _merge_body()
    assert "(L.nodes || []).map" in body
    assert "(L.domains || []).map" in body
    assert "const wires = (L.wires || []);" in body


def test_the_cloud_serves_the_build_of_the_one_source():
    """Two served surfaces, one source: the cloud keeps no .jsx copy of the cockpit."""
    assert not (CLOUD / "atlas-cockpit.jsx").exists(), "a second atlas-cockpit.jsx sits in the cloud tree"


def test_the_page_loads_what_was_actually_built():
    """map.html loads compiled/*.js, so an edited .jsx alone changes nothing."""
    page = (CLOUD / "map.html").read_text(encoding="utf-8")
    assert "compiled/atlas-cockpit.js" in page
    built = (CLOUD / "compiled" / "atlas-cockpit.js").read_text(encoding="utf-8")
    assert "NOTHING is added from the saved snapshot" in built, (
        "rebuild with: node cloud_backend/tools/build_cockpit_assets.js"
    )
