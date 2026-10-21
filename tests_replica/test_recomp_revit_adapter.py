"""The adapter owns execution; graph engines only shape their inputs/outputs."""
import pytest

from nodelang import clean_revit_adapter as adapter
from nodelang import library_engines as library
from nodelang import pipeline_engines as pipeline


@pytest.mark.parametrize("surface", ["read", "walls", "tags", "pdf"])
def test_revit_surfaces_share_the_adapter_execution_seam(monkeypatch, surface):
    session = {"port": 48884, "pid": 7, "revit_version": "2026", "document": "Fixture"}
    monkeypatch.setattr(adapter, "live_sessions", lambda: [session])
    calls = []

    def execute(selected, script, transaction, *, timeout=None):
        calls.append((selected, script, transaction, timeout))
        result = {
            "read": [{"id": 9}], "walls": [9],
            "tags": {"tagged": 1, "skipped": 0, "view": "Level 1"},
            "pdf": {"files": ["fixture.pdf"]},
        }[surface]
        return {"status": "ok", "result": result}

    monkeypatch.setattr(adapter, "_execute", execute)
    if surface == "read":
        outputs, _ = pipeline.revit_read({}, {})
        assert outputs["out"] == [{"id": 9}]
    elif surface == "walls":
        outputs, _ = pipeline.revit_build_walls({"session": "48884"}, {"in": [[0, 0, 1000, 0]]})
        assert outputs["out"] == [9]
    elif surface == "tags":
        outputs, _ = library.tag_rooms({}, {})
        assert outputs["tagged"] == 1
    else:
        outputs, _ = library.publish_pdf({}, {})
        assert outputs["out"] == ["fixture.pdf"]
    assert len(calls) == 1
    assert calls[0][0] == session


def test_dead_catalogue_params_are_removed_without_hiding_live_controls():
    rows = library.LIBRARY_ITEM_ENGINES
    assert rows["tool_baboom"]["params"]["start_with_archhub"] is True
    for row in rows.values():
        assert not {"default_view", "default_tab", "speech_budget_per_hour"} & row.get("params", {}).keys()
