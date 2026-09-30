"""Rendered court for canvas card states (G1 item 8), measured in headless Chrome.

Selected and focused cards draw with the one selection colour, --accent (no cyan
selection); focus is the selection plus a 2px accent ring; hovering a card never
moves it; each card category resolves to its own colour. The stylesheets declare
one .graph-node:hover, one [data-selected] and one [data-focused] rule.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (build_universal_application, project_universal_canvas,
                                             set_universal_selection)
from nodelang.universal_view import project_universal_document

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests_js" / "canvas_cards_rendered_probe.mjs"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("node") or not (ROOT / "node_modules" / "playwright" / "package.json").is_file() \
            or not CHROME.exists():
        pytest.skip("local headless Chrome court runtime is unavailable")
    store, registry = build_universal_application(resolve_map_path())
    html = project_universal_document(store, registry, csrf_token="a" * 32)
    roots = [node["id"] for node in project_universal_canvas(store, registry)["nodes"]][:2]
    set_universal_selection(store, registry, tuple(roots), focus_root=roots[1])
    projection = project_universal_canvas(store, registry)
    completed = subprocess.run(["node", str(PROBE)], cwd=ROOT, input=json.dumps({
        "chrome": str(CHROME), "html": html, "projection": projection}), text=True, encoding="utf-8",
        capture_output=True, timeout=300, check=False)
    assert completed.returncode == 0, completed.stderr[-4000:]
    return json.loads(completed.stdout)


def test_selection_and_focus_use_the_one_accent_colour(rendered):
    assert rendered["errors"] == []
    assert rendered["selected"] and rendered["focused"], rendered
    for card in rendered["selected"] + rendered["focused"]:
        assert card["border"] == rendered["accent"] and card["borderRight"] == rendered["accent"], card
    accent_numbers = re.findall(r"\d+", rendered["accent"])[:3]
    for card in rendered["focused"]:
        ring = re.match(r"rgba?\(([^)]*)\) 0px 0px 0px 2px", card["shadow"])
        assert ring and re.findall(r"\d+", ring.group(1))[:3] == accent_numbers, card["shadow"]


def test_hovering_a_card_never_moves_it(rendered):
    hover = rendered["hover"]
    assert hover["before"] == hover["after"], hover
    assert hover["transform"] in ("none", ""), hover


def test_every_category_has_its_own_colour(rendered):
    seen = {}
    for card in rendered["categories"]:
        seen.setdefault(card["category"], set()).add(card["resolvedColor"])
    by_colour = {}
    for category, colours in seen.items():
        assert len(colours) == 1, (category, colours)
        by_colour.setdefault(next(iter(colours)), []).append(category)
    assert all(len(names) == 1 for names in by_colour.values()), by_colour


def test_the_stylesheets_declare_one_hover_one_selected_one_focused_rule():
    from nodelang import application, universal_presentation_seed
    for sheet in (application.STYLESHEET, universal_presentation_seed.STYLESHEET):
        selectors = [m.group(1).strip() for m in re.finditer(r"([^{}]+)\{[^{}]*\}", sheet)]
        for selector in ('.graph-node:hover', '.graph-node[data-selected="True"]', '.graph-node[data-focused="True"]'):
            assert selectors.count(selector) == 1, (selector, selectors.count(selector))
        categories = re.findall(r'data-node-category="(\w+)"\]\{--node-color:([^}]*)\}', sheet)
        colours = [colour for _, colour in categories]
        assert len(colours) == len(set(colours)), categories
