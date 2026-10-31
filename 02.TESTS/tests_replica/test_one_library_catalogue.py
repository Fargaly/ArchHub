"""The served library is one catalogue: every engine, every host tool, every skill file, typed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from nodelang.library_engines import library_catalogue
from nodelang.native_host_tools import HOST_TOOLS
from nodelang.node_params import TYPES, coerce
from nodelang.nograph_server import r_node_library
from nodelang.pipeline_engines import PIPELINE_ENGINES
from nodelang.session_files import catalogue, new_document, skills_directory, write_document


def test_the_real_catalogue_lists_every_engine_and_skill_with_typed_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    skill = new_document("Wall schedule")
    skill["id"] = "wallschedule"
    folder = skills_directory()
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
