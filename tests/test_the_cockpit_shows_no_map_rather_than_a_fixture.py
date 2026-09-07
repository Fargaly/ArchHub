"""With no push there is no map -- not a fixture that looks like one.

The cockpit fell through to a checked-in, hand-authored map-data.js -- 142 KB
of authored domains and hand-written prose such as "ranked what matters now
surfaces here" -- and served it as if it were the founder's graph. An absent
application has to be VISIBLE, not papered over with something he cannot
tell apart from the real thing (audit, 2026-09-07).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COCKPIT_PY = (ROOT / "cloud_backend" / "founder_cockpit.py").read_text(
    encoding="utf-8"
)
COCKPIT_JSX = (
    ROOT / "cloud_backend" / "cockpit_assets" / "atlas-cockpit.jsx"
).read_text(encoding="utf-8")


def test_no_push_serves_no_map():
    served = COCKPIT_PY[COCKPIT_PY.index('if asset == "map-data.js":'):]
    served = served[:served.index("# The asset name comes off the URL")]
    assert "window.ATLAS_MAP = null; window.ATLAS_LIVE = false;" in served
    assert "_MAP_STATE.is_file()" in served, "a real push is still served"


def test_the_authored_fixture_can_no_longer_be_served_as_the_graph():
    served = COCKPIT_PY[COCKPIT_PY.index('if asset == "map-data.js":'):]
    served = served[:served.index("# The asset name comes off the URL")]
    assert "return Response(" in served
    # The generic file read below must never be reached for map-data.js.
    assert served.count("return Response(") == 2, (
        "both branches answer; nothing falls through to the shipped file"
    )


def test_the_page_draws_nothing_rather_than_a_saved_copy():
    start = COCKPIT_JSX.index("let data = live ?")
    statement = COCKPIT_JSX[start:COCKPIT_JSX.index(";", start)]
    fallback = statement.split("mergeLive(live, saved && saved.M)", 1)[1]
    assert "saved" not in fallback, (
        "with no live push the saved snapshot is the only story, and it "
        "would be drawn as the graph: %r" % fallback.strip()
    )
    assert "window.ATLAS_MAP" not in fallback
    assert "domains: [], nodes: [], wires: []" in fallback


def test_the_badge_says_what_is_actually_true():
    assert "'LIVE PUSH' : 'NO LIVE PUSH'" in COCKPIT_JSX
    assert "AUTHORED MODEL" not in COCKPIT_JSX
    assert "there is no map to draw" in COCKPIT_JSX
