"""Rendered court for canvas wires (G1 item 2): measured in headless Chrome.

At rest (nothing selected) every visible wire reads at 3:1 or better against the
canvas background (stroke x opacity over --bg-canvas), and all resting wires share
one opacity, .72. With a selection, wires take only the two remaining states: .18
outside the selection's context and 1 inside it. Exactly three states exist.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (build_universal_application, project_universal_canvas,
                                             set_universal_selection)
from nodelang.universal_view import project_universal_document

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests_js" / "canvas_wires_rendered_probe.mjs"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright" / "package.json").is_file() \
            or not CHROME.exists():
        pytest.skip("local headless Chrome court runtime is unavailable")
    store, registry = build_universal_application(resolve_map_path())
    html = project_universal_document(store, registry, csrf_token="a" * 32)
    selected = project_universal_canvas(store, registry)
    assert selected["selection"], "the seeded canvas opens with a selection"
    set_universal_selection(store, registry, [])
    rest = project_universal_canvas(store, registry)
    assert rest["selection"] == []
    completed = subprocess.run(["node", str(PROBE)], cwd=ROOT, input=json.dumps({
        "chrome": str(CHROME), "html": html,
        "cases": [{"name": "rest", "projection": rest}, {"name": "selected", "projection": selected}]}),
        text=True, encoding="utf-8", capture_output=True, timeout=300, check=False)
    assert completed.returncode == 0, completed.stderr[-4000:]
    return {row["name"]: row for row in json.loads(completed.stdout)}


def test_resting_wires_read_at_three_to_one_or_better(rendered):
    rest = rendered["rest"]
    assert rest["errors"] == [] and rest["selection"] == "[]" and rest["wires"] > 0, rest
    assert rest["minimumContrast"] >= 3.0, rest["worst"]
    assert rest["opacities"] == [0.72], rest["opacities"]


def test_a_selection_uses_only_the_two_other_states(rendered):
    selected = rendered["selected"]
    assert selected["errors"] == [] and selected["selection"] != "[]" and selected["wires"] > 0, selected
    assert set(selected["opacities"]) <= {0.18, 1.0}, selected["opacities"]
    assert 1.0 in selected["opacities"], "the selection's own wires are at full strength"


def test_the_stylesheets_declare_exactly_three_wire_opacity_rules():
    import re
    from nodelang import application, universal_presentation_seed
    for sheet in (application.STYLESHEET, universal_presentation_seed.STYLESHEET):
        rules = [m.group(0) for m in re.finditer(r"[^{}]*\{[^{}]*\}", sheet)
                 if "universal-wire" in m.group(0).split("{")[0]
                 and "universal-wire-preview" not in m.group(0).split("{")[0]
                 and re.search(r"(^|[;{])opacity:", m.group(0))]
        assert len(rules) == 3, rules
