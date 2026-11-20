"""The adapter owns execution; graph engines only shape their inputs/outputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from nodelang import clean_revit_adapter as adapter
from nodelang import library_engines as library
from nodelang import pipeline_engines as pipeline
from test_host_verbs_folded import _compile, _csc


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



@pytest.fixture
def ifc_request(tmp_path, monkeypatch):
    from nodelang import enforce, nodeslib_v2_engines as nodeslib
    from nodelang import workspace_roots_catalogue as workspaces

    project = tmp_path / "project"
    project.mkdir()
    source, destination = project / "Model.rvt", project / "Reviewed.ifc"
    source.write_bytes(b"disposable RVT path fixture")
    monkeypatch.setattr(workspaces, "read_registered_roots",
                        lambda: ({"court": {"path": str(project), "privacy": "private"}}, None))
    request = {"project_id": "court", "document": str(source), "path": str(destination),
               "session": "48884", "version": "IFC4RV", "setup": "", "views": []}
    operation = "revit.export_ifc"
    request["pending_write"] = {"kind": "ifc-export", "operation": operation,
                                "target": "workspace-roots/court/Reviewed.ifc",
                                "content": dict(request)}

    def artifact_fixture(pending, _params):
        assert pending == request["pending_write"]
        return {"ok": True, "diagnostics": []}

    # Adapter-only court: the production compiler still needs the IFC artifact rule.
    monkeypatch.setattr(enforce, "inspect_pending", artifact_fixture)
    request["grant"] = {"digest": "unsigned-court-fixture", "caller": "codex", "session": "court",
                        "work": "ifc", "action": operation, "scope": "revit.write",
                        "input_digest": nodeslib._digest_payload(request)}
    monkeypatch.setattr(nodeslib, "_WRITE_GRANT_VERIFIER", lambda envelope: {"ok": envelope["operation"] == operation})
    return request, destination


@pytest.mark.parametrize("field, value", [
    ("document", "changed.rvt"), ("path", "changed.ifc"), ("version", "IFC4DTV"),
    ("setup", "Another setup"), ("project_id", "another"), ("session", "48885"), ("views", [42]),
])
def test_ifc_approval_binds_effect_inputs_before_host_discovery(monkeypatch, ifc_request, field, value):
    request, _destination = ifc_request
    monkeypatch.setattr(adapter, "live_sessions", lambda: pytest.fail("unapproved host discovery"))
    with pytest.raises(ValueError, match="approval grant input digest does not match"):
        adapter.invoke("revit.export_ifc", {**request, field: value})


def test_ifc_pending_target_must_match_registered_path_even_with_approval(monkeypatch, ifc_request):
    from nodelang import nodeslib_v2_engines as nodeslib

    request, _destination = ifc_request
    request["pending_write"]["target"] = "workspace-roots/court/Different.ifc"
    request["grant"]["input_digest"] = nodeslib._digest_payload(adapter._effect_arguments(request))
    monkeypatch.setattr(adapter, "live_sessions", lambda: pytest.fail("wrong pending target reached Revit"))
    with pytest.raises(PermissionError, match="approved path"):
        adapter.invoke("revit.export_ifc", request)


_IFC_FIXTURE = (
    b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\n"
    b"FILE_NAME('Reviewed.ifc','2026-11-20T14:30:00',(''),(''),'Revit','Revit','');\n"
    b"FILE_SCHEMA(('IFC4'));\nENDSEC;\n"
    b"DATA;\n#42=IFCCARTESIANPOINT((0.,0.,0.));\nENDSEC;\nEND-ISO-10303-21;\n"
)
_IFC_DATA = b"DATA;\n#42=IFCCARTESIANPOINT((0.,0.,0.));\n"
_IFC_MALFORMED_FRAMING = {
    "missing data": _IFC_FIXTURE.replace(_IFC_DATA + b"ENDSEC;\n", b""),
    "unterminated data": _IFC_FIXTURE.replace(_IFC_DATA + b"ENDSEC;\n", _IFC_DATA),
    "commented close": _IFC_FIXTURE.replace(_IFC_DATA + b"ENDSEC;\n", _IFC_DATA + b"/* ENDSEC; */\n"),
    "quoted close": _IFC_FIXTURE.replace(_IFC_DATA + b"ENDSEC;\n", b"DATA; #42=IFCLABEL('ENDSEC;');\n"),
    "unclosed entity": _IFC_FIXTURE.replace(b"((0.,0.,0.));", b"((0.,0.,0.);"),
    "commented schema": _IFC_FIXTURE.replace(b"FILE_SCHEMA(('IFC4'));", b"/* FILE_SCHEMA(('IFC4')); */"),
}

@pytest.mark.parametrize("outcome", [
    "ok", "existing", "refused", "partial", "wrong schema", "concurrent", *_IFC_MALFORMED_FRAMING,
])
def test_ifc_only_publishes_complete_confirmed_output(monkeypatch, ifc_request, outcome):
    request, destination = ifc_request
    session = {"port": 48884, "pid": 7, "revit_version": "2027", "document": "Fixture"}
    monkeypatch.setattr(adapter, "live_sessions", lambda: [session])

    def broker(port, route, body, *, timeout):
        assert (port, route, body["transaction_name"], body["transaction"]) == (
            48884, "/exec", "ArchHub IFC export", False)
        staged, = destination.parent.glob(".archhub-ifc-*")
        if outcome == "concurrent":
            destination.write_bytes(b"other process")
        if outcome == "partial":
            (staged / destination.name).write_bytes(_IFC_FIXTURE[:30])
        elif outcome == "wrong schema":
            (staged / destination.name).write_bytes(_IFC_FIXTURE.replace(b"IFC4", b"IFC2X3"))
        else:
            (staged / destination.name).write_bytes(_IFC_MALFORMED_FRAMING.get(outcome, _IFC_FIXTURE))
        if outcome == "refused":
            return {"status": "error", "error": "native refusal"}
        return {"status": "ok", "result": request["version"]}

    if outcome == "existing":
        destination.write_bytes(b"original output")
        monkeypatch.setattr(adapter, "live_sessions", lambda: pytest.fail("existing target reached host"))
    monkeypatch.setattr(adapter, "_call", broker)
    if outcome == "ok":
        receipt = adapter.invoke("revit.export_ifc", request)
        assert receipt["ok"] and receipt["result"] == [str(destination)]
        assert receipt["receipt"]["ifc_sha256"] == hashlib.sha256(_IFC_FIXTURE).hexdigest()
        assert destination.read_bytes() == _IFC_FIXTURE
    else:
        with pytest.raises((ValueError, adapter.RevitUnreachable)):
            adapter.invoke("revit.export_ifc", request)
        if outcome in ("existing", "concurrent"):
            assert destination.read_bytes() == (b"original output" if outcome == "existing" else b"other process")
        else:
            assert not destination.exists()
    assert list(destination.parent.glob(".archhub-ifc-*")) == []


@pytest.mark.parametrize("chunk_size", [1, 7, 64])
def test_ifc_step_framing_handles_compact_records_across_buffers(tmp_path, monkeypatch, chunk_size):
    payload = _IFC_FIXTURE.replace(
        _IFC_DATA,
        b"/* HEADER; ENDSEC; */DATA;#42=IFCLABEL('A; B''s /* text */');",
    ).replace(b"\n", b"")
    path = tmp_path / "Compact.ifc"
    path.write_bytes(payload)
    monkeypatch.setattr(adapter, "_IFC_STEP_CHUNK", chunk_size)
    assert adapter._ifc_step_digest(path, b"IFC4") == hashlib.sha256(payload).hexdigest()


def test_ifc_named_setup_refuses_unreviewed_revit_year(monkeypatch, ifc_request):
    from nodelang import nodeslib_v2_engines as nodeslib

    request, destination = ifc_request
    request["setup"] = request["pending_write"]["content"]["setup"] = "Reviewed Setup"
    request["grant"]["input_digest"] = nodeslib._digest_payload(adapter._effect_arguments(request))
    monkeypatch.setattr(adapter, "live_sessions", lambda: [{"port": 48884, "pid": 7, "revit_version": "2026"}])
    monkeypatch.setattr(adapter, "_execute", lambda *_args, **_kwargs: pytest.fail("unreviewed IFC export"))
    with pytest.raises(adapter.RevitUnreachable, match="Named IFC setups have no reviewed adapter on Revit 2026"):
        adapter.invoke("revit.export_ifc", request)
    assert not destination.exists()
    assert not list(destination.parent.glob(".archhub-ifc-*"))


@pytest.mark.parametrize("year", ["2020", "2023", "2024", "2025", "2027"])
def test_ifc_payload_compiles_against_installed_revit_exporter(tmp_path, year):
    folder = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / f"Autodesk/Revit {year}"
    api = [folder / name for name in ("RevitAPI.dll", "RevitAPIUI.dll", "RevitAPIIFC.dll")]
    if not api[0].is_file():
        pytest.skip(f"Revit {year} SDK files are not installed")
    api.extend(folder / name for name in ("Revit.IFC.Export.dll", "Revit.IFC.Common.dll")
               if (folder / name).is_file())
    if year != "2027":
        name = "IFCExportUI.dll" if year == "2020" else "Autodesk.IFC.Export.UI.dll"
        api.append(folder / "AddIns/IFCExporterUI" / name)
    # Bind the actual Revit API references in the broker's C# 7.3 wrapper.
    numeric_id = "value" if year >= "2024" else "checked((int)value)"
    context = """
namespace RevitMCPCore {
    using Autodesk.Revit.DB;
    using Autodesk.Revit.UI;
    public class ScriptContext { public UIApplication UIApp; public UIDocument UIDoc;
                                 public Document Doc; public object result; }
    public static class RevitIds { public static ElementId Id(long value) => new ElementId(%s); }
}
""" % numeric_id
    source, output = tmp_path / "Model.rvt", tmp_path / "Reviewed.ifc"
    scripts = [("IFC default", adapter._ifc_script(source, output, "IFC2x3CV2", "", 0, revit_year=year)),
               ("IFC named", adapter._ifc_script(source, output, "IFC2x3CV2", "Reviewed Setup", 42, revit_year=year))]
    _compile(tmp_path, context, ["System", "System.Collections.Generic", "System.Linq", "Autodesk.Revit.DB",
                                 "Autodesk.Revit.UI"], scripts, api, "global::RevitMCPCore.ScriptContext")


def test_dead_catalogue_params_are_removed_without_hiding_live_controls():
    rows = library.LIBRARY_ITEM_ENGINES
    assert rows["tool_baboom"]["params"]["start_with_archhub"] is True
    for row in rows.values():
        assert not {"default_view", "default_tab", "speech_budget_per_hour"} & row.get("params", {}).keys()
