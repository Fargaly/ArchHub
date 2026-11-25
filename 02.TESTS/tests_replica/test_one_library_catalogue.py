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


def test_the_studio_boot_reads_the_shipped_starters_without_opening_any_saved_file(tmp_path, monkeypatch):
    from nodelang import session_files
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for index in range(3):
        write_document(str(sessions_directory() / f"saved-{index}.archhub"), new_document(f"Saved {index}"))
    reads = []
    real = session_files.read_document
    monkeypatch.setattr(session_files, "read_document", lambda path: reads.append(path) or real(path))
    server = SimpleNamespace(_hosts=SimpleNamespace(get=lambda: []))

    starters = r_node_library(server, SimpleNamespace(query={"starters": ["1"]}))["templates"]
    assert reads == [], "the starters-only read opens no saved file"
    assert len(starters) == 9 and all(str(row["id"]).startswith("starter:") and row["children"] for row in starters)
    assert "starter:submittal" in {row["id"] for row in starters}

    # The combined reply keeps serving its consumers, and it is the one that reads every saved file.
    combined = r_node_library(server, SimpleNamespace(query={"templates": ["1"]}))["templates"]
    assert len(reads) == 3 and {row["id"] for row in starters} <= {row["id"] for row in combined}

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


def test_design_row_7_and_8_nodes_are_live_executable_and_zero_cards_are_not_built(tmp_path, monkeypatch):
    """Every Library card has a live engine: zero available=False, zero noEngine, zero NOT_BUILT."""
    import asyncio
    import json

    from nodelang.library_engines import COMING_NODE_TYPES, LIBRARY_ITEMS_WITHOUT_ENGINE, NOT_BUILT
    from nodelang.native_agent_mcp import build_server
    from nodelang.session_files import read_document

    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME"):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path / "LOCALAPPDATA" / "ArchHub"))

    assert LIBRARY_ITEMS_WITHOUT_ENGINE == {}
    assert [row["title"] for row in COMING_NODE_TYPES] == [
        "Remote tunnel", "Model JSON", "Check model", "Place views on sheets"]
    rows = [item for group in library_catalogue() for item in group["items"] if not item.get("hidden")]
    assert not [item["id"] for item in rows if item.get("available") is False]
    assert not [item["id"] for item in rows if item.get("noEngine")]
    assert not [item["id"] for item in rows if item.get("reason") == NOT_BUILT]
    by_id = {item["id"]: item for item in rows}

    server = build_server()
    path = str(tmp_path / "live_nodes.archhub")

    def tool(name, **args):
        result = asyncio.run(server.call_tool(name, args))
        content = result[1] if isinstance(result, tuple) else None
        return content.get("result", content) if isinstance(content, dict) else json.loads(result[0].text)

    tool("canvas.new", path=path)
    before = [node["id"] for node in read_document(path)["nodes"]]
    placed_ids = []
    for declared in COMING_NODE_TYPES:
        card = by_id[declared["id"]]
        assert card.get("available") is not False and not card.get("noEngine")
        assert card["cat"] == declared["cat"] and card["title"] == declared["title"] and not card.get("hidden")
        assert {port["id"] for port in declared["ports"]["source"]} <= set(card["sockets"]["source"])
        assert declared["id"] in {row["type"] for row in tool("library.search", query=declared["title"])["items"]}
        placed_ids.append(tool("canvas.add_node", path=path, type=declared["id"])["node"])
    assert [node["id"] for node in read_document(path)["nodes"]] == [*before, *placed_ids]
