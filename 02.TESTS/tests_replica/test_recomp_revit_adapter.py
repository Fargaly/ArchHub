"""The adapter owns execution; graph engines only shape their inputs/outputs."""
import json
import subprocess

import pytest

from nodelang import clean_revit_adapter as adapter
from nodelang import library_engines as library
from nodelang import pipeline_engines as pipeline
from test_host_verbs_folded import _csc


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
        outputs, _ = pipeline.revit_build_walls({"session": "48884", "level": "Upper"}, {"in": [[0, 0, 1000, 0]]})
        assert outputs["out"] == [9]
    elif surface == "tags":
        outputs, _ = library.tag_rooms({}, {})
        assert outputs["tagged"] == 1
    else:
        outputs, _ = library.publish_pdf({}, {})
        assert outputs["out"] == ["fixture.pdf"]
    assert len(calls) == 1
    assert calls[0][0] == session


_WALLS_COURT = """
using System;
using System.Collections.Generic;
using System.Text.Json;

class Level {
    public string Name;
    public int Id;
}
class Document {
    public int Calls;
    public int Chosen;
    public bool InTransaction;
    public Level[] Levels = {
        new Level { Name = "Ground", Id = 11 },
        new Level { Name = "Upper", Id = 22 }
    };
}
class FilteredElementCollector {
    private readonly Document doc;
    public FilteredElementCollector(Document doc) { this.doc = doc; }
    public IEnumerable<Level> OfClass(Type kind) { return doc.Levels; }
}
class XYZ { public XYZ(double x, double y, double z) {} }
class Line { public static Line CreateBound(XYZ start, XYZ end) { return new Line(); } }
enum BuiltInParameter { WALL_USER_HEIGHT_PARAM }
class Parameter { public void Set(double height) {} }
class Wall {
    public int Id = 901;
    public Parameter get_Parameter(BuiltInParameter name) { return new Parameter(); }
    public static Wall Create(Document doc, Line line, int level, bool structural) {
        if (!doc.InTransaction) throw new Exception("Missing broker transaction");
        doc.Calls++;
        doc.Chosen = level;
        return new Wall();
    }
}
namespace RevitMCPCore {
    public static class RevitIds { public static int Of(int id) { return id; } }
}
class Broker {
    static object Run(Document Doc) {
        object result = null;
        /* PAYLOAD */
        return result;
    }
    static void Main() {
        var doc = new Document();
        doc.InTransaction = true;
        try {
            var result = Run(doc);
            doc.InTransaction = false;
            Console.WriteLine(JsonSerializer.Serialize(new {
                status = "ok", result, transaction = "committed", writes = doc.Calls, level = doc.Chosen
            }));
        } catch (Exception error) {
            doc.InTransaction = false;
            Console.WriteLine(JsonSerializer.Serialize(new {
                status = "error", error = error.Message, transaction = "rolled back", writes = doc.Calls
            }));
        }
    }
}
"""


@pytest.mark.parametrize("level,expected", [
    (None, "level is required"),
    ("   ", "level is required"),
    ("Missing", "unknown level 'Missing'"),
    ("Upper", None),
])
def test_wall_pipeline_executes_level_selection_before_wall_create(tmp_path, monkeypatch, level, expected):
    from nodelang import clean_revit_adapter

    command, refs = _csc()
    runtime = refs[0].parent.name.removeprefix("net") + ".0"
    (tmp_path / "court.runtimeconfig.json").write_text(
        json.dumps({"runtimeOptions": {"framework": {"name": "Microsoft.NETCore.App", "version": runtime}}}),
        encoding="utf-8")
    binary = tmp_path / "court.dll"
    source = tmp_path / "court.cs"
    session = {"port": 48884, "pid": 7, "revit_version": "2026", "document": "Fixture"}
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [session])
    executed = []

    def broker(port, route, body):
        assert (port, route, body["transaction_name"]) == (48884, "/exec", "ArchHub build walls")
        source.write_text(_WALLS_COURT.replace("/* PAYLOAD */", body["code"]), encoding="utf-8")
        subprocess.run(command + ["/nologo", "/noconfig", "/nostdlib+", "/langversion:7.3",
                                   "/out:" + str(binary), str(source)] +
                       ["/r:" + str(reference) for reference in refs], check=True, capture_output=True)
        reply = subprocess.run([command[0], str(binary)], check=True, capture_output=True, text=True)
        result = json.loads(reply.stdout)
        executed.append(result)
        return result

    monkeypatch.setattr(clean_revit_adapter, "_call", broker)
    params = {"session": "48884"}
    if level is not None:
        params["level"] = level
    feeds = {"in": [[0, 0, 1000, 0]]}
    if expected is None:
        outputs, _ = pipeline.revit_build_walls(params, feeds)
        assert outputs == {"out": [901]}
        assert executed == [{"status": "ok", "result": [901], "transaction": "committed",
                             "writes": 1, "level": 22}]
    else:
        with pytest.raises(ValueError, match="levels in the model: Ground, Upper"):
            pipeline.revit_build_walls(params, feeds)
        assert len(executed) == 1 and expected in executed[0]["error"]
        assert executed[0]["transaction"] == "rolled back" and executed[0]["writes"] == 0


def test_dead_catalogue_params_are_removed_without_hiding_live_controls():
    rows = library.LIBRARY_ITEM_ENGINES
    assert rows["tool_baboom"]["params"]["start_with_archhub"] is True
    for row in rows.values():
        assert not {"default_view", "default_tab", "speech_budget_per_hour"} & row.get("params", {}).keys()
