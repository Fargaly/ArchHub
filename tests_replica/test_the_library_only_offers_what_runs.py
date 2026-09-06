"""The node library may only offer cards that actually run.

The library listed fifty-three cards. Twenty-two carried an engine, and
studio-lm.jsx creates a node on the graph only when libItem.engine is set
(studio-lm.jsx:386-393), so dropping any of the other thirty-one put a
card in local React state alone: invisible to Run, never written to the
graph, gone on reload.

This court holds the engine side of that gap shut. It reads the real
LM_LIBRARY out of the studio source rather than a copy, so the numbers
here move the moment the library does.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from nodelang.library_engines import (
    LIBRARY_ENGINES,
    LIBRARY_ITEMS_WITHOUT_ENGINE,
    LIBRARY_ITEM_ENGINES,
)

_STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio" / "studio-lm.jsx"

_LINES = [
    [0.0, 0.0, 3000.0, 0.0],
    [3000.0, 0.0, 3000.0, 4000.0],
]

_ROWS = [
    {"name": "W1", "type": "Basic Wall", "level": "L1", "height": 3000},
    {"name": "W2", "type": "Curtain Wall", "level": "L1", "height": 6000},
    {"name": "W3", "type": "Basic Wall", "level": "L2", "height": 2400},
]

# One representative placement per engine: the parameters the card is
# dropped with, and a wired input that engine can actually answer over.
_PLACEMENTS = {
    "library.filter_field": ({"field": "type", "value": "Basic Wall"}, _ROWS),
    "library.filter_compare": (
        {"field": "height", "operator": ">", "value": "2500"}, _ROWS),
    "library.filter_rule": ({"rule": "item.height >= 3000"}, _ROWS),
    "library.set_field": ({"field": "Comments", "value": "checked"}, _ROWS),
    "library.move": ({"dx": "100", "dy": "50"}, _LINES),
    "library.rotate": ({"degrees": "90"}, _LINES),
    "library.scale": ({"factor": "2"}, _LINES),
    "library.group_by": ({"by": "type"}, _ROWS),
    "library.sort_by": ({"by": "height", "direction": "desc"}, _ROWS),
    "library.if": ({"rule": "item.height > 1000"}, _ROWS),
    "library.switch": ({"key": "a"}, _ROWS),
    "library.loop": ({}, _ROWS),
    "library.merge": ({"mode": "dedupe"}, [[1, 2], [2, 3]]),
    "library.add_text": ({"text": "FFL +0.00", "x": "10"}, _ROWS),
    "library.dimensions": ({"style": "aligned"}, _LINES),
    "library.build_schedule": ({"columns": "name,type"}, _ROWS),
    "library.make_legend": ({"by": "type"}, _ROWS),
    "library.save_skill": ({"path": ""}, "a saved run"),
    # The five that came later: placed so the shape court runs them without
    # a model key, a brain, Outlook or a desktop - each answers honestly.
    "library.think": ({"prompt": "total wall length"}, _ROWS),
    "library.match_skill": ({"intent": "tag rooms"}, {}),
    "library.embed": ({}, {}),
    "library.notify": ({"message": "sheet set published"}, {}),
    "library.draft_email": ({"to": "eng@firm.com"}, {}),
}

# Engines whose input is a stream: with nothing wired they must answer an
# empty stream, never a manufactured one. add_text is left out because its
# content is a parameter, not a feed -- it is covered on its own below.
_STREAM_ENGINES = [
    name for name in _PLACEMENTS
    if name not in ("library.if", "library.switch", "library.save_skill",
                    "library.add_text",
                    # These five act on a prompt, an intent, a query, a
                    # message or a draft, not on a wired stream; their
                    # empty answers are courted in test_five_more_cards_run.
                    "library.think", "library.match_skill", "library.embed",
                    "library.notify", "library.draft_email")
]


def _library_items():
    """Every LM_LIBRARY card in the studio source, with its engine or None."""
    source = _STUDIO.read_text(encoding="utf-8", errors="replace")
    start = source.index("const LM_LIBRARY = [")
    end = source.index(chr(10) + "];", start)
    items = {}
    for line in source[start:end].splitlines():
        found = re.search(r"id:'([a-z0-9_]+)'", line)
        if not found:
            continue
        engine = re.search(r"engine:'([^']+)'", line)
        items[found.group(1)] = engine.group(1) if engine else None
    return items


def _answered(engine_name, params, wired):
    engine = LIBRARY_ENGINES[engine_name]
    feeds = {} if wired is None else {"in": wired}
    return engine(dict(params), feeds)


def test_every_added_engine_answers_the_shared_shape(tmp_path):
    """(params, feeds) in, (outputs mapping, one display line) out."""
    assert set(_PLACEMENTS) == set(LIBRARY_ENGINES), (
        "every engine needs a placement in this court")
    for name, (params, wired) in _PLACEMENTS.items():
        if name == "library.save_skill":
            params = dict(params, path=str(tmp_path / "saved" / "SKILL.md"))
        answer = _answered(name, params, wired)
        assert isinstance(answer, tuple) and len(answer) == 2, name
        outputs, display = answer
        assert isinstance(outputs, dict), name
        assert all(isinstance(key, str) for key in outputs), name
        assert isinstance(display, str) and display.strip(), name


def test_an_engine_with_no_input_answers_empty_rather_than_inventing():
    for name in _STREAM_ENGINES:
        params = dict(_PLACEMENTS[name][0])
        outputs, display = _answered(name, params, None)
        held = outputs["out"]
        emptied = held["rows"] if isinstance(held, dict) else held
        assert emptied == [], (name, held)
        assert "nothing is wired in" == display, (name, display)


def test_add_text_with_no_stream_carries_only_the_note_it_was_given():
    """The note is a parameter, so it stands alone; no rows appear with it."""
    outputs, shown = _answered(
        "library.add_text", {"text": "FFL +0.00", "x": "10"}, None)
    assert outputs["out"] == [
        {"kind": "text", "text": "FFL +0.00", "x": 10.0, "y": 0.0}]
    assert "on 0 rows" in shown


def test_the_branch_engines_pass_nothing_when_nothing_is_wired():
    for name in ("library.if", "library.switch"):
        outputs, display = _answered(name, _PLACEMENTS[name][0], None)
        assert outputs == {}, name
        assert display == "nothing is wired in", name


def test_save_skill_writes_nothing_when_nothing_is_wired(tmp_path):
    destination = tmp_path / "unwired" / "SKILL.md"
    outputs, display = _answered(
        "library.save_skill", {"path": str(destination)}, None)
    assert outputs == {"out": ""}
    assert "nothing saved" in display
    assert not destination.exists()


def test_every_library_card_either_runs_or_says_it_cannot():
    """The library offered 53 cards; 31 of them vanished on reload.

    Dropping a card with no engine put it in the browser's memory only:
    invisible to Run, never written to the graph, gone on the next reload.
    Twenty of those got real engines first; five more followed (think,
    match_skill, embed, draft_email, notify) once the model route, the
    brain, Outlook and the tray gave them something real to do. The six
    that remain are marked so the drop refuses out loud instead of
    pretending. This court holds the LANDED state, not the plan.
    """
    items = _library_items()
    assert len(items) == 53, len(items)
    wired = {item for item, engine in items.items() if engine}
    assert len(wired) == 47, sorted(wired)

    for item, wiring in LIBRARY_ITEM_ENGINES.items():
        assert items.get(item) == wiring["engine"], (
            "%s is mapped to %s but the library says %r"
            % (item, wiring["engine"], items.get(item)))

    bare = set(items) - wired
    assert bare == set(LIBRARY_ITEMS_WITHOUT_ENGINE), sorted(bare)
    source = _STUDIO.read_text(encoding="utf-8", errors="replace")
    for item in bare:
        line = [l for l in source.splitlines() if "id:'%s'" % item in l]
        assert line and "noEngine:true" in line[0], (
            "%s can never run and is not marked: %s" % (item, line[:1]))
    assert "libItem.noEngine" in source, "the drop must refuse, not vanish"


def test_every_mapped_card_names_an_engine_that_exists():
    for item, wiring in LIBRARY_ITEM_ENGINES.items():
        assert wiring["engine"] in LIBRARY_ENGINES, item
        assert isinstance(wiring["params"], dict), item


def test_filters_keep_only_rows_that_match():
    kept, _shown = _answered(
        "library.filter_field", {"field": "type", "value": "Basic Wall"}, _ROWS)
    assert [row["name"] for row in kept["out"]] == ["W1", "W3"]
    dropped, _shown = _answered(
        "library.filter_field",
        {"field": "level", "value": "L1", "mode": "drop"}, _ROWS)
    assert [row["name"] for row in dropped["out"]] == ["W3"]
    tall, _shown = _answered(
        "library.filter_compare",
        {"field": "height", "operator": ">=", "value": "3000"}, _ROWS)
    assert [row["name"] for row in tall["out"]] == ["W1", "W2"]
    ruled, _shown = _answered(
        "library.filter_rule", {"rule": "item.level == L2"}, _ROWS)
    assert [row["name"] for row in ruled["out"]] == ["W3"]


def test_a_rule_this_version_cannot_evaluate_is_refused_by_name():
    with pytest.raises(ValueError) as refusal:
        _answered("library.filter_rule", {"rule": "item.height.match(/x/)"}, _ROWS)
    assert "not one this version evaluates" in str(refusal.value)


def test_geometry_moves_the_real_coordinates():
    moved, shown = _answered("library.move", {"dx": "100", "dy": "50"}, _LINES)
    assert moved["out"][0] == [100.0, 50.0, 3100.0, 50.0]
    assert "stream only" in shown
    turned, _shown = _answered("library.rotate", {"degrees": "90"}, _LINES)
    x1, y1, x2, y2 = turned["out"][0]
    assert math.isclose(x2, 0.0, abs_tol=1e-6) and math.isclose(y2, 3000.0)
    grown, _shown = _answered("library.scale", {"factor": "2"}, _LINES)
    assert grown["out"][1] == [6000.0, 0.0, 6000.0, 8000.0]


def test_rows_without_coordinates_pass_through_and_are_counted():
    mixed = _LINES + [{"name": "W1"}]
    moved, shown = _answered("library.move", {"dx": "10"}, mixed)
    assert moved["out"][-1] == {"name": "W1"}
    assert "1 carry no coordinates" in shown


def test_set_field_says_it_changed_the_stream_not_the_host():
    written, shown = _answered(
        "library.set_field", {"field": "Comments", "value": "checked"}, _ROWS)
    assert all(row["Comments"] == "checked" for row in written["out"])
    assert _ROWS[0].get("Comments") is None
    assert "stream only" in shown


def test_group_and_sort_reuse_the_evaluator():
    grouped, _shown = _answered("library.group_by", {"by": "type"}, _ROWS)
    assert {group["key"] for group in grouped["out"]} == {
        "Basic Wall", "Curtain Wall"}
    ordered, _shown = _answered(
        "library.sort_by", {"by": "height", "direction": "desc"}, _ROWS)
    assert [row["height"] for row in ordered["out"]] == [6000, 3000, 2400]


def test_logic_passes_one_branch_only():
    passed, shown = _answered("library.if", {"rule": "item.height > 5000"}, _ROWS)
    assert passed["out"] == _ROWS and shown == "true"
    blocked, shown = _answered(
        "library.if", {"rule": "item.height > 90000"}, _ROWS)
    assert blocked == {} and shown.startswith("false")
    taken, shown = _answered("library.switch", {"key": "b"}, _ROWS)
    assert taken["out"] == _ROWS and "b" in shown
    looped, shown = _answered("library.loop", {}, _ROWS)
    assert looped["each"] == _ROWS[0] and looped["out"] == _ROWS
    assert "3 items" in shown


def test_merge_concats_and_dedupes():
    joined, _shown = _answered(
        "library.merge", {"mode": "concat"}, [[1, 2], [2, 3]])
    assert joined["out"] == [1, 2, 2, 3]
    unique, _shown = _answered(
        "library.merge", {"mode": "dedupe"}, [[1, 2], [2, 3]])
    assert unique["out"] == [1, 2, 3]


def test_annotations_are_computed_not_invented():
    measured, shown = _answered("library.dimensions", {}, _LINES)
    assert [round(row["length_mm"]) for row in measured["out"]] == [3000, 4000]
    assert "stream only" in shown
    none_at_all, shown = _answered("library.dimensions", {}, _ROWS)
    assert none_at_all["out"] == []
    assert "3 rows are not lines" in shown
    noted, _shown = _answered(
        "library.add_text", {"text": "FFL +0.00", "x": "10"}, _ROWS)
    assert noted["out"][-1] == {
        "kind": "text", "text": "FFL +0.00", "x": 10.0, "y": 0.0}


def test_compose_reads_columns_it_was_given():
    table, shown = _answered(
        "library.build_schedule", {"columns": "name,type"}, _ROWS)
    assert table["out"]["columns"] == ["name", "type"]
    assert table["out"]["rows"][0] == ["W1", "Basic Wall"]
    assert shown == "3 rows x 2 columns"
    derived, _shown = _answered("library.build_schedule", {}, _ROWS)
    assert derived["out"]["columns"] == ["name", "type", "level", "height"]
    legend, _shown = _answered("library.make_legend", {"by": "type"}, _ROWS)
    assert legend["out"] == [
        {"symbol": "Basic Wall", "count": 2},
        {"symbol": "Curtain Wall", "count": 1},
    ]


def test_save_skill_writes_a_skill_the_catalogue_can_read(tmp_path):
    destination = tmp_path / "my-run" / "SKILL.md"
    outputs, shown = _answered(
        "library.save_skill",
        {"path": str(destination), "name": "wall-audit",
         "description": "Audit walls."},
        "step one",
    )
    assert outputs["out"] == str(destination)
    written = destination.read_text(encoding="utf-8")
    assert "name: wall-audit" in written
    assert "description: Audit walls." in written
    assert "step one" in written
    assert "wall-audit" in shown
    with pytest.raises(ValueError) as refusal:
        _answered("library.save_skill", {"path": str(destination)}, "again")
    assert "already exists" in str(refusal.value)


def test_save_skill_refuses_a_network_destination():
    for path in ("\\\\server\\share\\SKILL.md", "//server/share/SKILL.md"):
        with pytest.raises(ValueError) as refusal:
            _answered("library.save_skill", {"path": path}, "text")
        assert "local file" in str(refusal.value)


def test_no_filter_returns_more_rows_than_it_was_handed():
    for name in ("library.filter_field", "library.filter_compare",
                 "library.filter_rule"):
        params, wired = _PLACEMENTS[name]
        kept, _shown = _answered(name, params, wired)
        assert len(kept["out"]) <= len(wired), name
