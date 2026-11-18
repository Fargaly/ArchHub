"""The served library is one catalogue: every engine, every host tool, every skill file, typed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from nodelang.library_engines import library_catalogue
from nodelang.native_host_tools import HOST_TOOLS
from nodelang.node_params import TYPES, coerce
from nodelang.nograph_server import r_node_library
from nodelang.pipeline_engines import PIPELINE_ENGINES
from nodelang.session_files import catalogue, new_document, sessions_directory, write_document


def test_the_real_catalogue_lists_every_engine_and_skill_with_typed_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    skill = new_document("Wall schedule")
    skill["id"] = "wallschedule"
    folder = sessions_directory()
    write_document(str(folder / "wallschedule.archhub"), skill)
    (folder / "broken.archhub").write_text("{", encoding="utf-8")

    rows = [item for group in library_catalogue() for item in group["items"] if not item.get("hidden")]
    by_id = {item["id"]: item for item in rows}
    assert set(PIPELINE_ENGINES) <= {item.get("engine") for item in rows}
    assert {spec["id"] for spec in HOST_TOOLS} <= set(by_id)
    held = by_id["skill:wallschedule"]
    assert held["title"] == "Wall schedule"
    assert str(held["path"]).endswith("wallschedule.archhub")
    assert all(not str(item.get("path", "")).endswith("broken.archhub") for item in rows)

    number = by_id["n_number"]
    assert number["params"]["value"] == 0 and type(number["params"]["value"]) is int
    assert number["params"]["min"] is None and number["params"]["max"] is None
    value_def = next(row for row in number["paramDefs"] if row["id"] == "value")
    assert value_def["type"] == "number" and value_def.get("min") is None and value_def.get("max") is None
    assert any(port.get("id") == "value" and port.get("type") == "number" for port in number["ports"]["source"])

    for item in rows:
        definitions = {row["id"]: row for row in item.get("paramDefs") or []}
        for name, value in (item.get("params") or {}).items():
            definition = definitions[name]
            assert definition["type"] in TYPES, (item["id"], name, definition["type"])
            if definition["type"] in ("number", "integer"):
                assert value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)), (
                    item["id"], name, value)
            if definition["type"] == "bool":
                assert type(value) is bool, (item["id"], name, value)

    with pytest.raises(ValueError):
        coerce("number", 11, {"min": 0, "max": 10})
    assert coerce("number", 3, {"min": None, "max": None}) == 3
    assert coerce("number", "", {"optional": True}) is None

    served = r_node_library(
        SimpleNamespace(_hosts=SimpleNamespace(get=lambda: [])),
        SimpleNamespace(query={"templates": ["1"]}))
    templates = {row["id"]: row for row in served["templates"]}
    assert any(str(key).startswith("starter:") for key in templates)
    assert templates["skill:wallschedule"]["title"] == "Wall schedule"
    assert str(templates["skill:wallschedule"]["path"]).endswith("wallschedule.archhub")

    flat = {row["id"]: row for row in catalogue()}
    assert flat["skill:wallschedule"]["title"] == "Wall schedule"
    assert flat["n_number"]["params"]["value"] == 0 and flat["n_number"]["params"]["min"] is None


def test_the_shelf_tree_names_every_card_category_once_in_the_design_order(tmp_path, monkeypatch):
    """A card keeps the category its own declaration gives; the tree only names and orders those categories."""
    from nodelang.library_engines import LIBRARY_PRESENTATION, LIBRARY_TREE
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    declared = {category for category, _rows in LIBRARY_PRESENTATION}
    shown = [category for _row, _label, _icon, categories in LIBRARY_TREE for category in categories]
    assert len(shown) == len(set(shown)), "a card category sits in one tree row only"
    assert set(shown) == declared
    served = {item["cat"] for group in library_catalogue() for item in group["items"]}
    assert served <= set(shown), served - set(shown)
    # The collapse owner accepts a tree row's id, so opening and closing a row can be kept.
    assert {row for row, _label, _icon, _shown in LIBRARY_TREE} <= declared
    assert [label for _row, label, _icon, _shown in LIBRARY_TREE][:9] == [
        "Programs", "Files", "Workflows and skills", "Starts a run", "Checks and standards",
        "Agents and AI", "Lists and data", "Change geometry", "Decide and branch"]
    by_row = {row: set(categories) for row, _label, _icon, categories in LIBRARY_TREE}
    assert served & by_row["host"] and served & by_row["trigger"] and served & by_row["governance"]


def test_the_settings_action_serves_the_tree_and_starts_it_closed_until_he_chooses(tmp_path):
    from nodelang.library_engines import LIBRARY_TREE
    from nodelang.nograph_server import JsonFile, r_settings_action

    def action(function, args=()):
        server = SimpleNamespace(files={"companion": None, "settings": JsonFile(tmp_path / "settings.json", {})})
        return r_settings_action(server, SimpleNamespace(body={"function": function, "args": args}))["result"]

    first = action("readLibraryCollapsed")
    assert [(row["id"], row["label"], row["icon"], tuple(row["categories"])) for row in first["libraryTree"]] == list(LIBRARY_TREE)
    assert first["libraryCollapsed"] == [row for row, _label, _icon, _shown in LIBRARY_TREE]
    assert action("setLibraryCollapsed", [["host"]])["libraryCollapsed"] == ["host"]
    assert action("setLibraryCollapsed", [[]])["libraryCollapsed"] == []
    assert action("readLibraryCollapsed")["libraryCollapsed"] == [], "his own choice of everything open is kept"


def test_a_coming_node_type_says_so_in_its_own_declaration_and_no_path_places_it(tmp_path, monkeypatch):
    """Design rows 7 and 8: shown in the Library as designed, marked not available by the node type itself, never placed."""
    import asyncio
    import json

    from mcp.server.fastmcp.exceptions import ToolError

    from nodelang.library_engines import COMING_NODE_TYPES, NOT_BUILT
    from nodelang.native_agent_mcp import build_server
    from nodelang.session_files import read_document

    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME"):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path / "LOCALAPPDATA" / "ArchHub"))

    assert [row["title"] for row in COMING_NODE_TYPES] == [
        "Remote tunnel", "Model JSON", "Check model", "Place views on sheets"]
    assert all(row["available"] is False for row in COMING_NODE_TYPES)
    by_id = {item["id"]: item for group in library_catalogue() for item in group["items"]}

    server = build_server()
    path = str(tmp_path / "coming.archhub")

    def tool(name, **args):
        result = asyncio.run(server.call_tool(name, args))
        content = result[1] if isinstance(result, tuple) else None
        return content.get("result", content) if isinstance(content, dict) else json.loads(result[0].text)

    tool("canvas.new", path=path)
    before = read_document(path)["nodes"]
    for declared in COMING_NODE_TYPES:
        card = by_id[declared["id"]]
        # The catalogue row carries the node type's own mark; nothing beside it lists these cards.
        assert card["available"] is False and card["noEngine"] is True and card["reason"] == NOT_BUILT
        assert card["cat"] == declared["cat"] and card["title"] == declared["title"] and not card.get("hidden")
        assert {port["id"] for port in declared["ports"]["source"]} <= set(card["sockets"]["source"])
        for kind in (declared["id"], declared["title"], declared["engine"]):
            with pytest.raises(ToolError, match="non-executable node type"):
                tool("canvas.add_node", path=path, type=kind)
        # Searching its name may find built cards that share a word; it never offers the coming card itself.
        assert declared["id"] not in {row["type"] for row in tool("library.search", query=declared["title"])["items"]}
    assert read_document(path)["nodes"] == before, "a refused card leaves the canvas file as it was"

    # A built card carries no mark and is placed as before.
    assert "available" not in by_id["n_number"] and not by_id["n_number"].get("noEngine")
    placed = tool("canvas.add_node", path=path, type="n_number")["node"]
    assert [node["id"] for node in read_document(path)["nodes"]] == [*(node["id"] for node in before), placed]
