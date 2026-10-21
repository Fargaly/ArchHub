"""Court: Settings -> Theme shows exactly the themes the graph offers.

The Theme tab drew three hard-coded cards (System / Dark / Light) that no graph
fact backed: offered_themes() is ('forge',) because vellum lacks nine
foundation colours and blueprint has none, yet "Light" was on screen. The
canvas now carries configuration.design_system.themes and the tab draws one
card per offered theme.
"""
from __future__ import annotations

from pathlib import Path

from nodelang.application_server import ApplicationServer
from nodelang.cell_theme_sets import DEFAULT_THEME, THEMES, offered_themes
from tests_replica.test_universal_interaction_server import _json

STUDIO_LM = Path(__file__).resolve().parents[1] / "nodelang" / "studio" / "studio-lm.jsx"


def test_the_canvas_carries_the_offered_themes_and_the_active_one():
    server = ApplicationServer().start()
    try:
        status, canvas = _json(server, "/api/universal/canvas")
        assert status == 200
        themes = canvas["configuration"]["design_system"]["themes"]
        assert [t["name"] for t in themes["offered"]] == list(offered_themes())
        assert all(t["label"] == THEMES[t["name"]] for t in themes["offered"])
        assert themes["active"] == DEFAULT_THEME
    finally:
        server.close()


def test_the_theme_tab_draws_cards_only_from_the_offered_list():
    source = STUDIO_LM.read_text(encoding="utf-8")
    start = source.index("const SettingsTheme = () =>")
    tab = source[start:source.index("\n};\n", start)]
    assert "config?.design_system?.themes?.offered" in tab
    for invented in ("'System',", "'Light',", "'follows OS'"):
        assert invented not in tab, invented
