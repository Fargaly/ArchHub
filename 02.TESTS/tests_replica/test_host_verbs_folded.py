"""Verbs folded from bimwright rvt-mcp (Apache-2.0) and U-C4N Autocad-MCP (MIT).

Each verb is a C# script for the one signed broker /exec. These courts compile
every folded script, wrapped exactly as bridges/sources/shared/ScriptCompiler.cs
wraps it, against the host API assemblies installed on this machine (files only;
no host process is started), and drive the adapters with a recorded broker.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from nodelang import clean_autocad_adapter as acad
from nodelang import clean_revit_adapter as revit
from nodelang import library_engines, pipeline_engines
from nodelang.clean_host_catalogue_source import AUTOCAD_OPERATIONS, REVIT_OPERATIONS

PROGRAMS = Path(r"C:\Program Files\Autodesk")
ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = set(revit._GEOMETRY_VERBS)
REVIT_SAMPLE = {"elements": [11, {"id": 12}], "element_id_1": 11, "element_id_2": 12,
                "categories_a": ["Walls"], "categories_b": "OST_Doors, Windows", "view3d_id": 5,
                "x": 1.5, "y": -2, "z": 1e-05, "dir_x": 1, "dir_y": 0, "dir_z": 0, "room_id": 9,
                "element_id": 11, "category": "Walls", "include_samples": True}
ACAD_SAMPLE = {"name": "A-WALL", "color": 3, "linetype": "DASHED", "lineweight": 0.35, "file": "acadiso.lin"}


def _csc():
    dotnet = shutil.which("dotnet")
    if not dotnet:
        pytest.skip("no .NET SDK to compile with")
    dotnet = Path(dotnet)
    listed = subprocess.run([str(dotnet), "--list-sdks"], capture_output=True, text=True, check=True)
    version, root = listed.stdout.splitlines()[-1].split(" [", 1)
    packs = sorted((dotnet.parent / "packs/Microsoft.NETCore.App.Ref").glob("*"))
    refs = sorted((packs[-1] / "ref").glob("net*/*.dll"))
    return [str(dotnet), str(Path(root.rstrip("]")) / version / "Roslyn/bincore/csc.dll")], refs


def _compile(tmp_path, context, usings, scripts, api, context_name):
    """Compile scripts with the broker's wrapper (ScriptCompiler.BuildSource) at C# 7.3."""
    command, refs = _csc()
    units = [context]
    for index, (label, code) in enumerate(scripts):
        units.append("namespace Gen%d {\n%s\n  public static class Entry {\n"
                     "    public static object Run(%s ctx) {\n      var UIApp = ctx.UIApp;\n"
                     "      var UIDoc = ctx.UIDoc;\n      var Doc   = ctx.Doc;\n      object result = null;\n"
                     "      // %s\n%s\n      ctx.result = result;\n      return result;\n    }\n  }\n}"
                     % (index, "".join("  using %s;\n" % u for u in usings), context_name, label, code))
    source = tmp_path / "verbs.cs"
    source.write_text("\n".join(units), encoding="utf-8")
    built = subprocess.run(command + ["/nologo", "/noconfig", "/nostdlib+", "/target:library", "/langversion:7.3",
                                      "/nowarn:1701,1702", "/out:" + str(tmp_path / "verbs.dll"), str(source)]
                           + ["/r:" + str(p) for p in refs] + ["/r:" + str(p) for p in api],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout[-6000:] + built.stderr[-2000:]


def _build_core(tmp_path, folder):
    """The real broker Core for this Revit year (REVIT2024_OR_GREATER, as the csproj sets it)."""
    command, refs = _csc()
    shared = ROOT / "01.APP/bridges/sources/shared"
    core = tmp_path / "RevitMCPCore.dll"
    built = subprocess.run(command + ["/nologo", "/noconfig", "/nostdlib+", "/target:library", "/langversion:latest",
                                      "/define:REVIT2024_OR_GREATER", "/nowarn:1701,1702", "/out:" + str(core),
                                      str(ROOT / "01.APP/bridges/sources/revit_mcp_core/RevitMCPCore.cs")]
                           + [str(shared / n) for n in ("ScriptCompiler.cs", "ICoreEntryPoint.cs", "ReviewedCore.cs", "BridgeAuth.cs")]
                           + ["/r:" + str(p) for p in refs]
                           + ["/r:" + str(folder / "RevitAPI.dll"), "/r:" + str(folder / "RevitAPIUI.dll")],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout[-6000:] + built.stderr[-2000:]
    return core

def _net8_revit_years():
    years = []
    for folder in sorted(PROGRAMS.glob("Revit 20[2-9][0-9]")):
        if int(folder.name[-4:]) >= 2025 and (folder / "RevitAPI.dll").is_file():
            years.append(folder)
    return years


@pytest.mark.parametrize("folder", _net8_revit_years() or [pytest.param(None, marks=pytest.mark.skip("no Revit 2025+ API installed"))],
                         ids=lambda f: getattr(f, "name", "none"))
def test_every_revit_script_compiles_against_the_installed_revit_api_and_core(tmp_path, folder):
    """Rule F20: every revit.* script, old reads included, on Revit 2025+ where IntegerValue is gone."""
    core = _build_core(tmp_path, folder)
    scripts = [(op, revit._script_for(op, REVIT_SAMPLE)) for op in sorted(GEOMETRY)]
    scripts.append(("volume-box", revit._script_for("revit.find_elements_in_volume",
                                                   {"volume": {"min": [0, 0, 0], "max": [3, 4, 2.5]}, "match": "inside"})))
    scripts.append(("complexity-by-category", revit._script_for("revit.analyze_geometry_complexity", {"categories": ["Walls"]})))
    rows = {"elements": [{"id": 11}], "parameter": "Mark", "value": "A1", "category": "Walls",
            "rows": [{"number": "A101", "name": "Plan"}], "number_format": "A{index:03d}", "name_format": "S{index}"}
    for op in sorted(set(revit._READS) | {"revit.elements_of_category", "revit.get_parameter",
                                          "revit.set_parameter_by_name", "revit.create_sheets", "revit.renumber_rename"}):
        scripts.append((op, revit._script_for(op, rows)))
    # The library authoring cards send their scripts through the same broker.
    scripts += [("tag-rooms", library_engines._TAG_ROOMS),
                ("place-tags", library_engines._PLACE_TAGS % (json.dumps("Doors"), "true")),
                ("place-on-sheet", library_engines._PLACE_ON_SHEET % (json.dumps("A101"), json.dumps("Plan"))),
                ("export-pdf", library_engines._EXPORT_PDF % (json.dumps(r"C:\out"), json.dumps("A101")))]
    _compile(tmp_path, "", ["System", "System.Collections.Generic", "System.Linq", "Autodesk.Revit.DB",
                            "Autodesk.Revit.UI"], scripts, [folder / "RevitAPI.dll", folder / "RevitAPIUI.dll", core],
             "global::RevitMCPCore.ScriptContext")

def _autocad_years():
    return [f for f in sorted(PROGRAMS.glob("AutoCAD 20[2-9][0-9]"))
            if int(f.name[-4:]) >= 2025 and (f / "acdbmgd.dll").is_file()]


@pytest.mark.parametrize("folder", _autocad_years() or [pytest.param(None, marks=pytest.mark.skip("no AutoCAD 2025+ API installed"))],
                         ids=lambda f: getattr(f, "name", "none"))
def test_every_autocad_verb_compiles_against_the_installed_autocad_api(tmp_path, folder):
    context = ("namespace AcadMCP { public class AcadScriptContext { public Autodesk.AutoCAD.ApplicationServices.Document Doc; "
               "public Autodesk.AutoCAD.DatabaseServices.Database Db; public Autodesk.AutoCAD.EditorInput.Editor Ed; "
               "public object UIApp; public object UIDoc; public object result; } }")
    scripts = [(op, acad._script_for(op, ACAD_SAMPLE)) for op in sorted(acad.AUTOCAD_VERBS)]
    scripts.append(("modify-colour-only", acad._script_for("autocad.layer_modify", {"name": "A-WALL", "color": 1})))
    _compile(tmp_path, context, ["System", "System.Collections.Generic", "System.Linq",
                                 "Autodesk.AutoCAD.ApplicationServices", "Autodesk.AutoCAD.DatabaseServices",
                                 "Autodesk.AutoCAD.EditorInput", "Autodesk.AutoCAD.Geometry", "Autodesk.AutoCAD.Runtime"],
             scripts, [folder / name for name in ("acdbmgd.dll", "acmgd.dll", "accoremgd.dll")],
             "global::AcadMCP.AcadScriptContext")


def test_every_folded_verb_is_declared_and_carried_out_both_ways():
    declared_revit = {row["op_id"] for row in REVIT_OPERATIONS}
    assert GEOMETRY <= declared_revit and len(GEOMETRY) == 12
    declared_acad = {row["op_id"]: row for row in AUTOCAD_OPERATIONS}
    assert set(declared_acad) == set(acad.AUTOCAD_VERBS) and len(declared_acad) == 13
    for op, row in declared_acad.items():
        assert (row["kind"] == "write") == (op in acad.AUTOCAD_WRITE_OPS)
        if row["kind"] == "write":
            assert row["inputs"][-1]["id"] == "grant" and row["destructive"]
    for row in REVIT_OPERATIONS:
        if row["op_id"] in GEOMETRY:
            assert row["kind"] == "read" and not row["destructive"]
            arguments = {f["id"]: REVIT_SAMPLE.get(f["id"], f["default"]) for f in row["inputs"] if f["id"] != "instance"}
            if row["op_id"] == "revit.find_elements_in_volume":
                arguments.pop("volume")
            assert revit._script_for(row["op_id"], arguments).startswith(revit._GEO_PRELUDE)


class _Broker:
    """A recorded broker: every /exec body it was sent, and one canned answer."""

    def __init__(self, answer):
        self.calls, self.answer = [], answer

    def __call__(self, port, route, body=None, timeout=None):
        self.calls.append((port, route, body))
        return dict(self.answer)


def _no_host(*_a, **_k):
    raise AssertionError("a refused verb must not reach any host")


# tests/test_symbol_names.py upstream: anything that could end a macro segment.
PAYLOADS = ["CENTER\n_ERASE ALL\n", "CENTER;_ERASE ALL", "CENTER\r_QUIT", 'CENTER"', "CENTER|X", "CENTER<X",
            "CENTER>X", "CENTER?X", "CENTER*X", "CENTER,X", "CENTER=X", "CENTER:X", "CENTER/X", "CENTER\\X", "   "]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_an_illegal_symbol_name_is_refused_before_autocad_is_asked(monkeypatch, payload):
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "broker_sessions", _no_host)
    monkeypatch.setattr(acad, "_require_write_grant", lambda op, args: {"digest": "g"})
    for op, args in (("autocad.layer_create", {"name": payload}), ("autocad.layer_lock", {"name": payload}),
                     ("autocad.layer_create", {"name": "OK", "linetype": payload}),
                     ("autocad.linetype_load", {"name": payload})):
        with pytest.raises(ValueError) as refused:
            acad.invoke(op, args)
        assert payload.strip() == "" or payload not in str(refused.value)  # never echoed back


@pytest.mark.parametrize("name", ["CENTER", "HIDDEN2", "DASHDOT", "ACAD_ISO02W100", "My-Linetype_01"])
def test_ordinary_names_pass_the_symbol_rule(name):
    assert acad.sanitize_symbol_name(name, kind="linetype") == name


@pytest.mark.parametrize("given,stored", [(0.25, 25), (0.35, 35), (2.0, 200), (25, 25), (211, 211),
                                          (-3, -3), (-1, -1), (0, 0), (0.5, 50)])
def test_lineweight_millimetres_and_hundredths_both_land_on_autocad_values(given, stored):
    assert acad.normalize_lineweight(given) == stored


@pytest.mark.parametrize("bad", [0.27, 33, 300, True])
def test_a_lineweight_autocad_does_not_have_is_refused(bad):
    with pytest.raises(ValueError):
        acad.normalize_lineweight(bad)


@pytest.mark.parametrize("args", [{"name": "A", "color": 0}, {"name": "A", "color": 256}, {"name": "A", "color": 2.5},
                                  {"name": "A", "color": "red"}])
def test_layer_colour_must_be_an_aci_index(monkeypatch, args):
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "_require_write_grant", lambda op, a: {"digest": "g"})
    with pytest.raises(ValueError):
        acad.invoke("autocad.layer_modify", args)


@pytest.mark.parametrize("name", ["0", "Defpoints", "DEFPOINTS"])
def test_autocad_owned_layers_are_never_deleted(monkeypatch, name):
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "_require_write_grant", lambda op, a: {"digest": "g"})
    with pytest.raises(ValueError):
        acad.invoke("autocad.layer_delete", {"name": name})


@pytest.mark.parametrize("file", [r"C:\evil\x.lin", "../x.lin", "x.txt", "a;b.lin"])
def test_linetype_file_is_a_bare_lin_name_only(monkeypatch, file):
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "_require_write_grant", lambda op, a: {"digest": "g"})
    with pytest.raises(ValueError):
        acad.invoke("autocad.linetype_load", {"name": "CENTER", "file": file})


@pytest.mark.parametrize("op", sorted(acad.AUTOCAD_WRITE_OPS))
def test_every_autocad_write_needs_an_approval_before_any_host(monkeypatch, op):
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "broker_sessions", _no_host)
    with pytest.raises(ValueError, match="approval grant"):
        acad.invoke(op, dict(ACAD_SAMPLE))


def test_autocad_read_runs_on_the_one_acad_broker_and_returns_its_rows(monkeypatch):
    broker = _Broker({"status": "ok", "result": [{"name": "0", "current": True}]})
    monkeypatch.setattr(acad, "_call", broker)
    monkeypatch.setattr(acad, "broker_sessions", lambda service: [
        {"port": 48890, "pid": 7, "document": "plan.dwg", "acad_version": "25.1", "service": "acad-mcp"}]
        if service == "acad" else _no_host())
    answer = acad.invoke("autocad.layer_list", {})
    assert answer["result"] == [{"name": "0", "current": True}] and answer["port"] == 48890
    (port, route, body), = broker.calls
    assert (port, route, body["transaction_name"]) == (48890, "/exec", "ArchHub read")
    assert "receipt" not in answer


def test_autocad_write_with_approval_sends_names_as_data_and_returns_a_receipt(monkeypatch):
    broker = _Broker({"status": "ok", "result": {"ok": True, "layer": "A-WALL", "frozen": True}})
    monkeypatch.setattr(acad, "_call", broker)
    monkeypatch.setattr(acad, "broker_sessions", lambda service: [{"port": 48891, "pid": 8, "service": "acad-mcp"}])
    monkeypatch.setattr(acad, "_require_write_grant", lambda op, a: {"digest": "grant-1"})
    answer = acad.invoke("autocad.layer_freeze", {"name": "A-WALL", "grant": {}})
    assert answer["ok"] and answer["receipt"]["grant_digest"] == "grant-1"
    code = broker.calls[0][2]["code"]
    declared = re.search(r'string name = (".*?");', code).group(1)
    assert json.loads(declared) == "A-WALL" and broker.calls[0][2]["transaction_name"] == "ArchHub write"


def test_two_autocad_sessions_without_a_choice_are_refused(monkeypatch):
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "broker_sessions", lambda service: [{"port": 48890, "pid": 1}, {"port": 48891, "pid": 2}])
    with pytest.raises(acad.AutoCADUnreachable, match="2 AutoCAD sessions"):
        acad.invoke("autocad.layer_list", {})


def test_an_unknown_autocad_verb_is_refused_by_name():
    with pytest.raises(acad.AutoCADUnreachable):
        acad.invoke("autocad.invented", {})
    with pytest.raises(acad.AutoCADUnreachable):
        acad.invoke("revit.list_levels", {})


@pytest.mark.parametrize("op,args", [
    ("revit.get_element_bounding_box", {}),
    ("revit.get_element_bounding_box", {"elements": ["11; Doc.Delete"]}),
    ("revit.get_element_bounding_box", {"elements": [True]}),
    ("revit.measure_distance_between_elements", {"element_id_1": 1}),
    ("revit.clash_detection", {"categories_a": ["Walls"]}),
    ("revit.clash_detection", {"categories_a": ["W"], "categories_b": ["D"], "strategy": "magic"}),
    ("revit.raycast_from_point", {"view3d_id": 1, "x": 0, "y": 0, "z": 0, "dir_x": 0, "dir_y": 0, "dir_z": 0}),
    ("revit.raycast_from_point", {"view3d_id": 1, "x": float("nan"), "y": 0, "z": 0, "dir_x": 1, "dir_y": 0, "dir_z": 0}),
    ("revit.find_elements_in_volume", {}),
    ("revit.find_elements_in_volume", {"room_id": 3, "limit": 0}),
    ("revit.project_point_onto_face", {"element_id": 1, "x": 0, "y": 0, "z": 0, "face_index": -1}),
    ("revit.find_overlapping_elements", {}),
    ("revit.analyze_geometry_complexity", {}),
    ("revit.get_element_geometry", {"elements": [1], "sample_limit": 10000}),
])
def test_bad_geometry_arguments_are_refused_before_revit_is_asked(monkeypatch, op, args):
    monkeypatch.setattr(revit, "_call", _no_host)
    monkeypatch.setattr(revit, "live_sessions", _no_host)
    with pytest.raises(ValueError):
        revit.invoke(op, args)


def test_a_hostile_category_reaches_revit_as_one_string_literal(monkeypatch):
    hostile = 'Walls"); Doc.Delete(new ElementId(1)); //'
    broker = _Broker({"status": "ok", "result": {"overlaps": []}})
    monkeypatch.setattr(revit, "_call", broker)
    monkeypatch.setattr(revit, "live_sessions", lambda: [{"port": 48884, "pid": 3, "revit_version": "2027", "document": "A"}])
    answer = revit.invoke("revit.find_overlapping_elements", {"category": hostile})
    assert answer["result"] == {"overlaps": []} and answer["revit_version"] == "2027"
    (port, route, body), = broker.calls
    assert (port, route, body["transaction_name"]) == (48884, "/exec", "ArchHub read")
    literal = re.search(r'string category = (".*?(?<!\\)");', body["code"]).group(1)
    assert json.loads(literal) == hostile


def test_the_revit_read_node_hands_verb_inputs_through_but_never_an_approval(monkeypatch):
    seen = {}
    monkeypatch.setattr(revit, "live_sessions", lambda: [{"port": 48884, "pid": 3, "revit_version": "2027"}])
    monkeypatch.setattr(revit, "invoke", lambda op, args: seen.update(op=op, args=args) or {"result": [{"id": 11}]})
    out, _ = pipeline_engines.revit_read({"operation": "revit.compute_element_volume", "session": "48884",
                                             "elements": [11], "grant": {"digest": "x"}}, {})
    assert out == {"out": [{"id": 11}]} and seen["op"] == "revit.compute_element_volume"
    assert seen["args"] == {"elements": [11], "instance": "48884"}


def test_autocad_verb_node_runs_the_verb_and_carries_the_wired_approval(monkeypatch):
    seen = {}

    def fake_invoke(op, args):
        seen.update(op=op, args=args)
        return {"result": {"ok": True, "layer": "A-WALL", "locked": True}, "port": 48890,
                "receipt": {"operation": op, "grant_digest": "g"}}

    monkeypatch.setattr(acad, "invoke", fake_invoke)
    out, said = pipeline_engines.PIPELINE_ENGINES["autocad.verb"](
        {"operation": "autocad.layer_lock", "name": "A-WALL", "session": "48890"}, {"grant": {"digest": "g"}})
    assert seen == {"op": "autocad.layer_lock", "args": {"name": "A-WALL", "grant": {"digest": "g"}, "instance": "48890"}}
    assert out["out"]["locked"] is True and out["receipt"]["operation"] == "autocad.layer_lock"
    assert "autocad.layer_lock" in said


def test_every_folded_verb_carries_the_node_contract_effect_flag():
    """C2: anything that writes to a host model is side-effect; reads are pure."""
    for row in [*AUTOCAD_OPERATIONS, *(r for r in REVIT_OPERATIONS if r["op_id"] in GEOMETRY)]:
        assert row["effect"] == ("side-effect" if row["kind"] == "write" else "pure"), row["op_id"]
        assert all(field["type"] for field in row["inputs"])  # every socket is typed

def test_an_approved_autocad_write_still_passes_the_one_pending_write_decision(monkeypatch):
    """C3: approval alone is not enough; the exact pending value goes through enforce, as Revit writes do."""
    from nodelang import nodeslib_v2_engines as nodeslib
    monkeypatch.setattr(nodeslib, "_require_grant", lambda arguments, **_: {"digest": "g"})
    monkeypatch.setattr(acad, "_call", _no_host)
    monkeypatch.setattr(acad, "broker_sessions", _no_host)
    with pytest.raises(PermissionError, match="pending-write"):
        acad.invoke("autocad.layer_freeze", {"name": "A-WALL", "grant": {"digest": "g"}})
    with pytest.raises(PermissionError, match="pending-write"):
        acad.invoke("autocad.layer_freeze", {"name": "A-WALL", "grant": {"digest": "g"},
                                             "pending_write": {"operation": "autocad.layer_freeze",
                                                               "content": {"name": "OTHER"}}})