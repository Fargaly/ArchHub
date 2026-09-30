"""Rendered court for canvas card ports (G1 item 3, Ping's amendment): measured in
headless Chrome, never computed. Every port starts below the bottom of the card's
rendered content rows; no content row overflows its line (long titles, values and
params end in an ellipsis instead of wrapping into the ports); a card without a value
row still keeps its ports under its content; zoom 0.5 / 0.82 / 2 and a viewport resize
change none of that; and a resize costs a bounded number of layouts (no thrashing).
The page is the real document and canvas script; requests are answered from the
projection by the browser itself (tests_js/canvas_ports_rendered_probe.mjs).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application, project_universal_canvas
from nodelang.universal_view import project_universal_document

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests_js" / "canvas_ports_rendered_probe.mjs"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
LONG = "A very long card title that would wrap onto a second and third line " * 3


def _walk(descriptor, visit):
    visit(descriptor)
    for child in descriptor.get("children") or []:
        _walk(child, visit)


def _variant(projection, change):
    changed = copy.deepcopy(projection)
    for node in changed["nodes"]:
        for descriptor in node.get("card_descriptor") or []:
            change(descriptor)
    return changed


def _long_text(descriptor):
    def visit(item):
        if str(item.get("class") or "").split()[:1] in (["node-title"], ["node-value"], ["node-head"]):
            item["text"] = LONG
    _walk(descriptor, visit)


def _no_value(descriptor):
    descriptor["children"] = [child for child in descriptor.get("children") or []
                              if "node-value" not in str(child.get("class") or "")]


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright" / "package.json").is_file() \
            or not CHROME.exists():
        pytest.skip("local headless Chrome court runtime is unavailable")
    store, registry = build_universal_application(resolve_map_path())
    html = project_universal_document(store, registry, csrf_token="a" * 32)
    projection = project_universal_canvas(store, registry)
    cases = [{"name": "as-projected", "projection": projection},
             {"name": "long-text", "projection": _variant(projection, _long_text)},
             {"name": "no-value-row", "projection": _variant(projection, _no_value)}]
    for zoom in (0.5, 2.0, 0.1):
        zoomed = copy.deepcopy(projection)
        zoomed["viewport"] = {**zoomed.get("viewport", {}), "zoom": zoom}
        cases.append({"name": "zoom-%s" % zoom, "projection": zoomed})
    # A dense column of 12 cards, 174 px apart as the map lays them out.
    stack = copy.deepcopy(projection)
    kept = stack["nodes"][:12]
    for index, node in enumerate(kept):
        node["x"], node["y"] = 60.0, 92.0 + index * 174.0
    ids = {node["id"] for node in kept}
    stack["nodes"] = kept
    stack["wires"] = [wire for wire in stack.get("wires", [])
                      if wire.get("source") in ids and wire.get("target") in ids]
    for zoom in (0.5, 0.1):
        column = copy.deepcopy(stack)
        column["viewport"] = {**column.get("viewport", {}), "zoom": zoom}
        cases.append({"name": "stack-zoom-%s" % zoom, "projection": column})
    completed = subprocess.run(["node", str(PROBE)], cwd=ROOT, input=json.dumps({
        "chrome": str(CHROME), "html": html, "cases": cases}), text=True, encoding="utf-8",
        capture_output=True, timeout=900, check=False)
    assert completed.returncode == 0, completed.stderr[-4000:]
    return {row["name"]: row for row in json.loads(completed.stdout)}


CASES = ["as-projected", "long-text", "no-value-row", "zoom-0.5", "zoom-2.0", "zoom-0.1",
         "stack-zoom-0.5", "stack-zoom-0.1"]


@pytest.mark.parametrize("case", CASES)
def test_every_rendered_port_sits_below_the_rendered_content(rendered, case):
    row = rendered[case]
    assert row["errors"] == [], row["errors"]
    for moment in ("before", "after"):
        measured = row[moment]
        assert measured["cards"] > 0 and measured["ports"] > 0, (moment, measured)
        assert measured["failures"] == [], (case, moment, measured["failures"][:6])


def test_a_resize_does_not_thrash_layout(rendered):
    # One resize: the browser lays out once or twice; per-card measure-then-write
    # loops would cost one layout per card (17 cards here).
    for case, row in rendered.items():
        # Five resizes. Thrash is a script forcing layout: more than one layout per
        # frame that passed. Each resize may cost at most one layout per frame plus
        # two (the resize and the redraw read), and never anywhere near one per wire
        # (136 wires; the two-phase redraw's predecessor cost 545 for one resize).
        # On a quiet machine this measures 2-3 layouts over 4-6 frames.
        for sample in row["resizeSamples"]:
            assert sample["layouts"] <= sample["frames"] + 2, (case, row["resizeSamples"])
            assert sample["layouts"] < 20, (case, row["resizeSamples"])


@pytest.mark.parametrize("case", CASES)
def test_taller_cards_never_cover_a_neighbour(rendered, case):
    """(a'): the band gap grows with the socket scale only down to zoom 0.5."""
    for moment in ("before", "after"):
        measured = rendered[case][moment]
        assert measured["overlapCount"] == 0, (case, moment, measured["overlaps"])
