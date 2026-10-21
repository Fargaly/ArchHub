from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodelang import clean_revit_adapter
from nodelang.clean_host_catalogue_source import HOST_OPERATION_RECORDS
from nodelang import host_brokers
from nodelang.application_server import _CleanAuthorityHttpServer
from nodelang import library_engines
from nodelang import nodeslib_v2_engines as nodeslib
from nodelang.stem_graph_evaluation import evaluate_stem_graph
from nodelang import universal_pipeline
from nodelang.core import Store
from nodelang.domains.selfext import mods_rows, set_mod_enabled, set_mod_param
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


_NEXT10 = {
    "b_all_category": "revit.elements_of_category",
    "b_get_parameter": "revit.get_parameter",
    "r_xl_range": "office.read",
    "text_ops": "text.ops",
    "math_expression": "math.expression",
    "math_series": "math.series",
    "g_approval_gate": "approval.gate",
    "b_set_parameter": "revit.set_parameter_by_name",
    "f_write_table": "excel.write_range",
    "g_rule_check": "library.rule_check",
    "b_create_sheets": "revit.create_sheets",
    "b_renumber": "revit.renumber_rename",
}


def _served_items() -> dict[str, dict]:
    return {item["id"]: item for group in library_engines.library_catalogue() for item in group["items"]}


def test_next10_cards_are_served_from_the_one_catalogue_with_typed_sockets():
    served = _served_items()
    for item_id, engine in _NEXT10.items():
        assert served[item_id]["engine"] == engine
        assert library_engines.LIBRARY_ITEM_ENGINES[item_id]["engine"] == engine
        sockets = library_engines.engine_sockets(engine)
        assert sockets["source"], (item_id, engine, sockets)
        assert sockets["target"] is not None, (item_id, engine, sockets)
    for item_id in ("b_set_parameter", "f_write_table", "b_create_sheets", "b_renumber"):
        assert "grant" in served[item_id]["sockets"]["target"]
    assert "approved" not in served["g_approval_gate"]["params"]
    assert "path" not in served["f_write_table"]["params"]
    assert "session" not in served["b_set_parameter"]["params"]
    assert "session" not in served["b_all_category"]["params"]
    assert served["b_get_parameter"]["params"] == {}
    assert served["b_set_parameter"]["params"] == {}
    assert "title_block" not in served["b_create_sheets"]["params"]
    assert "parameter" in served["b_get_parameter"]["sockets"]["target"]
    assert "elements" in served["b_set_parameter"]["sockets"]["target"]
    assert "els" not in served["b_set_parameter"]["sockets"]["target"]
    assert "els" not in served["b_set_parameter"]["sockets"]["source"]
    assert "els" not in served["b_renumber"]["sockets"]["source"]
    assert "number_format" in served["b_renumber"]["sockets"]["target"]
    assert "number_pattern" not in served["b_renumber"]["sockets"]["target"]


def test_host_write_catalogue_uses_typed_grant_inputs_not_raw_sessions():
    writes = {row["op_id"]: row for row in HOST_OPERATION_RECORDS if row["kind"] == "write"}
    reads = {row["op_id"]: row for row in HOST_OPERATION_RECORDS if row["kind"] == "read"}
    revit_session = reads["revit.list_walls"]["inputs"][0]
    assert revit_session["id"] == "instance"
    assert revit_session["type"] == "revit-document-picker"
    assert revit_session["option_label"] == "document"
    assert revit_session["auto_select_single"] is True
    assert revit_session["text_input"] is False
    for op_id in ("excel.list_workbooks", "word.list_documents", "powerpoint.list_presentations"):
        assert reads[op_id]["inputs"] == []
    assert {field["id"] for field in reads["excel.list_worksheets"]["inputs"]} == {"workbook"}
    assert {field["id"] for field in reads["word.list_paragraphs"]["inputs"]} == {"document"}
    assert {field["id"] for field in reads["powerpoint.list_slides"]["inputs"]} == {"presentation"}
    assert {field["id"] for field in reads["excel.read_range"]["inputs"]} == {"file", "sheet", "range"}
    for op_id in ("revit.set_parameter_by_name", "revit.create_sheets", "revit.renumber_rename"):
        ids = {field["id"] for field in writes[op_id]["inputs"]}
        labels = {field["label"] for field in writes[op_id]["inputs"]}
        types = {field["id"]: field["type"] for field in writes[op_id]["inputs"]}
        assert "instance" not in ids
        assert "Session" not in labels
        assert types["grant"] == "approval-grant"
        assert next(field for field in writes[op_id]["inputs"] if field["id"] == "grant")["help"] == "Comes from the Approval gate."
    assert {field["id"] for field in writes["revit.renumber_rename"]["inputs"]} >= {
        "elements", "number_format", "name_format", "grant",
    }
    assert "name" not in {field["id"] for field in writes["revit.set_parameter_by_name"]["inputs"]}
    assert "parameter" in {field["id"] for field in writes["revit.set_parameter_by_name"]["inputs"]}
    assert writes["excel.write_range"]["description"] == "Rows written to an Excel or CSV file."


def test_next10_read_and_pure_nodes_run_on_fixture_brokers(monkeypatch):
    def fake_revit(operation, arguments):
        if operation == "revit.elements_of_category":
            return {"result": [{"id": 7, "category": arguments["category"], "name": "Wall A"}]}
        if operation == "revit.get_parameter":
            return {"result": [{"id": 7, "value": "L1"}]}
        raise AssertionError(operation)

    monkeypatch.setattr(nodeslib, "_REVIT_BROKER", fake_revit)
    els, _ = nodeslib.revit_elements_of_category({"category": "Walls"}, {})
    vals, _ = nodeslib.revit_get_parameter({"parameter": "Level"}, {"elements": els["elements"]})
    assert els["elements"][0]["category"] == "Walls"
    assert vals["values"] == [{"id": 7, "value": "L1"}]
    vals2, _ = nodeslib.revit_get_parameter({}, {"elements": els["elements"], "parameter": "Level"})
    assert vals2["values"] == [{"id": 7, "value": "L1"}]

    text, _ = nodeslib.text_ops({"operation": "replace", "text": "A-101", "pattern": "-", "replacement": "."}, {})
    math_value, _ = nodeslib.expression({"expression": "a + b", "a": "2", "b": "3"}, {})
    series, _ = nodeslib.series({"start": "10", "step": "5", "count": "3"}, {})
    assert text["text"] == "A.101"
    assert math_value["value"] == 5
    assert series["values"] == [10, 15, 20]


def test_next10_writes_require_gate_and_use_fake_signed_brokers(monkeypatch, tmp_path):
    calls = []
    file_calls = []

    def verify(payload):
        return {"ok": True, "receipt": "fixture"}

    def fake_revit(operation, arguments):
        calls.append((operation, arguments))
        if operation == "revit.set_parameter_by_name":
            return {"ok": True, "receipt": "fixture", "result": [{"id": 7, "Comments": arguments["value"]}]}
        if operation == "revit.create_sheets":
            return {"ok": True, "receipt": "fixture", "result": [{"number": "A101", "name": "Plan"}]}
        if operation == "revit.renumber_rename":
            return {"ok": True, "receipt": "fixture", "result": [{"id": 7, "number": "A-001"}]}
        raise AssertionError(operation)

    def fake_file_writer(payload):
        file_calls.append(payload)
        target = Path(str(payload["path"]))
        if payload["format"] == "csv":
            nodeslib._write_csv(payload["rows"], target)
        else:
            nodeslib._write_xlsx(payload["rows"], target)
        return {"ok": True, "receipt": "fixture", "result": str(target)}

    monkeypatch.setattr(nodeslib, "_WRITE_GRANT_VERIFIER", verify)
    monkeypatch.setattr(nodeslib, "_REVIT_BROKER", fake_revit)
    monkeypatch.setattr(nodeslib, "_FILE_WRITE_BROKER", fake_file_writer)

    def revit_grant(operation, request):
        return {
            "operations": [operation], "scope": "revit.write", "digest": "fixture",
            "caller": "court", "session": "fixture", "work": "fixture",
            "input_digest": nodeslib._digest_payload(request), "action": operation,
        }

    set_request = {"elements": [{"id": 7}], "name": "Comments", "value": "OK"}
    sheet_request = {"rows": [{"number": "A101", "name": "Plan"}]}
    renum_request = {"elements": [{"id": 7}], "number_pattern": "A-{index:03d}", "name_pattern": ""}
    set_gate, _ = nodeslib.approval_gate(
        {"operation": "revit.set_parameter_by_name", "scope": "revit.write",
         "grant": revit_grant("revit.set_parameter_by_name", set_request)},
        {"in": [{"id": 7}]})
    sheet_gate, _ = nodeslib.approval_gate(
        {"operation": "revit.create_sheets", "scope": "revit.write",
         "grant": revit_grant("revit.create_sheets", sheet_request)},
        {"in": sheet_request["rows"]})
    renum_gate, _ = nodeslib.approval_gate(
        {"operation": "revit.renumber_rename", "scope": "revit.write",
         "grant": revit_grant("revit.renumber_rename", renum_request)},
        {"in": [{"id": 7}]})
    set_out, _ = nodeslib.revit_set_parameter(
        {"value": "OK"}, {"els": [{"id": 7}], "name": "Comments", "grant": set_gate["grant"]})
    sheet_out, _ = nodeslib.revit_create_sheets({}, {"rows": [{"number": "A101", "name": "Plan"}], "grant": sheet_gate["grant"]})
    renum_out, _ = nodeslib.revit_renumber_rename(
        {}, {"els": [{"id": 7}], "number_pattern": "A-{index:03d}", "grant": renum_gate["grant"]})
    assert set_out["elements"][0]["Comments"] == "OK"
    assert "els" not in set_out
    assert sheet_out["sheets"][0]["number"] == "A101"
    assert renum_out["elements"][0]["number"] == "A-001"
    assert "els" not in renum_out

    output = tmp_path / "table.csv"
    file_grant = {
        "operations": ["write_file"], "scope": "exact", "path": str(output),
        "digest": "fixture", "caller": "court", "session": "fixture",
        "work": "fixture", "input_digest": nodeslib._digest_payload({"rows": [{"a": 1}], "path": str(output), "format": "csv"}), "action": "write_file",
    }
    written, _ = host_brokers.excel_write_range({"format": "csv", "grant": file_grant}, {"rows": [{"a": 1}]})
    assert Path(written["file"]).read_text(encoding="utf-8").splitlines() == ["a", "1"]
    assert [op for op, _ in calls] == ["revit.set_parameter_by_name", "revit.create_sheets", "revit.renumber_rename"]
    assert len(file_calls) == 1

    with pytest.raises(ValueError, match="host write requires an approval grant"):
        nodeslib.revit_set_parameter({"value": "NO"}, {"elements": [{"id": 7}], "parameter": "Comments"})
    assert [op for op, _ in calls] == ["revit.set_parameter_by_name", "revit.create_sheets", "revit.renumber_rename"]

    bad_file_grant = {**file_grant, "input_digest": "wrong"}
    with pytest.raises(ValueError, match="input digest"):
        host_brokers.excel_write_range({"format": "csv", "grant": bad_file_grant}, {"rows": [{"a": 1}]})
    assert len(file_calls) == 1


def test_saved_old_revit_socket_and_param_names_migrate_before_stem_run(monkeypatch):
    class PlanOwner:
        def _graph_held_operations(self):
            return {}

    calls = []

    def fake_revit(operation, arguments):
        calls.append((operation, arguments))
        if operation == "revit.elements_of_category":
            return {"result": [{"id": 7, "category": arguments["category"]}]}
        if operation == "revit.get_parameter":
            return {"result": [{"id": 7, "name": arguments["name"], "value": "L1"}]}
        raise AssertionError(operation)

    monkeypatch.setattr(nodeslib, "_REVIT_BROKER", fake_revit)
    payload = {
        "nodes": [
            {"id": "source", "engine": "revit.elements_of_category",
             "parameter_defaults": {"category": "Walls"}, "properties": []},
            {"id": "param", "engine": "revit.get_parameter",
             "parameter_defaults": {"name": "Level"}, "properties": []},
        ],
        "wires": [
            {"source": "source", "target": "param",
             "properties": {"source_interface": "els", "target_interface": "els"}},
        ],
    }
    nodes, wires, held = _CleanAuthorityHttpServer._clean_stem_plan(PlanOwner(), payload)
    assert wires[0].source_interface == "elements"
    assert wires[0].target_interface == "elements"
    assert nodes[1].parameters["parameter"] == "Level"

    ev = evaluate_stem_graph(nodes, wires, held, {
        "revit.elements_of_category": nodeslib.revit_elements_of_category,
        "revit.get_parameter": nodeslib.revit_get_parameter,
    })
    assert ev.node_outputs["param"]["values"] == [{"id": 7, "name": "Level", "value": "L1"}]
    assert calls == [
        ("revit.elements_of_category", {"category": "Walls", "scope": "document", "session": ""}),
        ("revit.get_parameter", {"elements": [{"id": 7, "category": "Walls"}], "name": "Level", "session": ""}),
    ]


def test_saved_graph_run_migrates_old_revit_socket_names_before_execution(monkeypatch):
    class Store:
        revision = 7

        def snapshot(self):
            return object()

    calls = []

    def fake_revit(operation, arguments):
        calls.append((operation, arguments))
        if operation == "revit.elements_of_category":
            return {"result": [{"id": 7, "category": arguments["category"]}]}
        if operation == "revit.get_parameter":
            return {"result": [{"id": 7, "name": arguments["name"], "value": "L1"}]}
        raise AssertionError(operation)

    projection = {
        "nodes": [
            {"id": "source", "ports": [
                {"id": "source-els", "owner": "source", "side": "source",
                 "mode": "connection", "derived": False, "name": "els",
                 "name_root": "source-els:name"},
            ]},
            {"id": "target", "ports": [
                {"id": "target-els", "owner": "target", "side": "target",
                 "mode": "connection", "derived": False, "name": "els",
                 "name_root": "target-els:name"},
            ]},
        ],
        "wires": [
            {"id": "wire-old-els", "source": "source", "target": "target",
             "source_interface": "source-els", "target_interface": "target-els",
             "params": []},
        ],
    }
    owned = {
        "source": {
            "engine": ("p-engine", "revit.elements_of_category"),
            "category": ("p-category", "Walls"),
        },
        "target": {
            "engine": ("p-engine", "revit.get_parameter"),
            "name": ("p-name", "Level"),
        },
    }
    monkeypatch.setattr(nodeslib, "_REVIT_BROKER", fake_revit)
    monkeypatch.setattr(universal_pipeline, "project_universal_canvas",
                        lambda *args, **kwargs: projection)
    monkeypatch.setattr(universal_pipeline, "_owner_properties",
                        lambda *args, **kwargs: owned)
    monkeypatch.setattr(universal_pipeline, "_land_pipeline_statuses",
                        lambda *args, **kwargs: 0)

    outcome = universal_pipeline.run_universal_pipeline(
        Store(), object(), effect_engines=nodeslib.ENGINES,
    )
    assert outcome["pending"] == {}
    assert outcome["display"]["target"] == "1 value(s) for Level"
    assert calls == [
        ("revit.elements_of_category", {"category": "Walls", "scope": "document", "session": ""}),
        ("revit.get_parameter", {"elements": [{"id": 7, "category": "Walls"}], "name": "Level", "session": ""}),
    ]


def test_next10_rule_check_reports_pass_fail_and_adapter_owns_revit_scripts():
    rows = [{"id": 1, "height": 3600}, {"id": 2, "height": 2400}]
    report, shown = library_engines.rule_check({"parameter": "height", "operator": ">", "value": "3000"}, {"in": rows})
    assert report["pass"] == [{"id": 1, "height": 3600}]
    assert report["fail"] == [{"id": 2, "height": 2400}]
    assert report["report"]["passed"] == 1 and report["report"]["failed"] == 1
    assert "1 pass, 1 fail" in shown

    for op in ("revit.set_parameter_by_name", "revit.create_sheets", "revit.renumber_rename"):
        assert clean_revit_adapter._script_for(op, {"elements": [{"id": 7}], "rows": [{"number": "A101"}], "name": "Comments"}) is not None


def test_live_revit_write_adapter_refuses_before_exec_without_verified_grant(monkeypatch):
    exec_calls = []
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [{
        "port": 48884, "pid": 7, "revit_version": "2026", "document": "Court.rvt",
    }])
    monkeypatch.setattr(clean_revit_adapter, "_call", lambda *args, **kwargs: exec_calls.append(args) or {"status": "ok"})

    with pytest.raises(ValueError, match="host write requires an approval grant"):
        clean_revit_adapter.invoke("revit.set_parameter_by_name", {
            "elements": [{"id": 7}], "name": "Comments", "value": "NO",
        })
    assert exec_calls == []


def test_live_revit_write_adapter_returns_confirmed_receipt(monkeypatch):
    def verify(payload):
        return {"ok": True, "receipt": "fixture"}

    monkeypatch.setattr(nodeslib, "_WRITE_GRANT_VERIFIER", verify)
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [{
        "port": 48884, "pid": 7, "revit_version": "2026", "document": "Court.rvt",
    }])
    monkeypatch.setattr(clean_revit_adapter, "_call", lambda *args, **kwargs: {
        "status": "ok", "result": [{"id": 7, "changed": True}],
    })
    request = {"elements": [{"id": 7}], "name": "Comments", "value": "OK"}
    grant = {
        "operations": ["revit.set_parameter_by_name"], "scope": "revit.write",
        "digest": "fixture", "caller": "court", "session": "fixture",
        "work": "fixture", "input_digest": nodeslib._digest_payload(request),
        "action": "revit.set_parameter_by_name",
    }

    answer = clean_revit_adapter.invoke("revit.set_parameter_by_name", {**request, "grant": grant})
    assert answer["ok"] is True
    assert answer["receipt"]["operation"] == "revit.set_parameter_by_name"


def test_live_revit_adapter_dispatches_to_the_selected_document_session(monkeypatch):
    captured = []

    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [
        {"port": 48884, "pid": 7, "revit_version": "2026", "document": "Tower-A.rvt"},
        {"port": 48885, "pid": 8, "revit_version": "2026", "document": "Tower-B.rvt"},
    ])

    def fake_call(port, route, body=None, **kwargs):
        captured.append((port, route, body))
        return {"status": "ok", "result": [{"id": 1, "name": "Tower B Wall"}]}

    monkeypatch.setattr(clean_revit_adapter, "_call", fake_call)

    answer = clean_revit_adapter.invoke("revit.list_walls", {"instance": "48885"})

    assert answer["port"] == 48885
    assert answer["document"] == "Tower-B.rvt"
    assert captured[0][0] == 48885
    assert captured[0][1] == "/exec"
    assert captured[0][2]["transaction_name"] == "ArchHub read"
    assert "FilteredElementCollector" in captured[0][2]["code"]


def test_live_revit_renumber_adapter_formats_padded_index_before_exec(monkeypatch):
    captured = []

    def verify(payload):
        return {"ok": True, "receipt": "fixture"}

    def fake_call(port, route, body=None, **kwargs):
        captured.append((route, body))
        return {"status": "ok", "result": [{"id": 7, "number": "A-001"}]}

    request = {"elements": [{"id": 7}], "number_format": "A-{index:03d}", "name_format": ""}
    grant = {
        "operations": ["revit.renumber_rename"], "scope": "revit.write",
        "digest": "fixture", "caller": "court", "session": "fixture",
        "work": "fixture", "input_digest": nodeslib._digest_payload(request),
        "action": "revit.renumber_rename",
    }
    monkeypatch.setattr(nodeslib, "_WRITE_GRANT_VERIFIER", verify)
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [{
        "port": 48884, "pid": 7, "revit_version": "2026", "document": "Court.rvt",
    }])
    monkeypatch.setattr(clean_revit_adapter, "_call", fake_call)

    answer = clean_revit_adapter.invoke("revit.renumber_rename", {**request, "grant": grant})
    code = captured[0][1]["code"]
    assert answer["ok"] is True
    assert "System.Text.RegularExpressions.Regex.Replace" in code
    assert 'number.ToString("D" + width)' in code
    assert '.Replace("{index}"' not in code


def test_live_revit_write_adapter_denied_approval_makes_zero_host_calls(monkeypatch):
    session_calls = []
    exec_calls = []
    monkeypatch.setattr(nodeslib, "_WRITE_GRANT_VERIFIER", lambda payload: {"ok": False, "error": "approval denied by court"})
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: session_calls.append("scan") or [])
    monkeypatch.setattr(clean_revit_adapter, "_call", lambda *args, **kwargs: exec_calls.append(args) or {"status": "ok"})
    request = {"elements": [{"id": 7}], "name": "Comments", "value": "NO"}
    grant = {
        "operations": ["revit.set_parameter_by_name"], "scope": "revit.write",
        "digest": "fixture", "caller": "court", "session": "fixture",
        "work": "fixture", "input_digest": nodeslib._digest_payload(request),
        "action": "revit.set_parameter_by_name",
    }

    with pytest.raises(ValueError, match="approval denied by court"):
        clean_revit_adapter.invoke("revit.set_parameter_by_name", {**request, "grant": grant})

    assert session_calls == []
    assert exec_calls == []


def _revit_write_grant(request):
    return {
        "operations": ["revit.set_parameter_by_name"], "scope": "revit.write",
        "digest": "fixture", "caller": "court", "session": "fixture",
        "work": "fixture", "input_digest": nodeslib._digest_payload({
            key: value for key, value in request.items() if key != "mods_store"
        }), "action": "revit.set_parameter_by_name",
    }


def _revit_write_request(count, mods_store):
    return {
        "elements": [{"id": index + 1} for index in range(count)],
        "name": "Comments", "value": "OK", "host": "Revit", "document": "Court.rvt",
        "mods_store": mods_store,
    }


def test_mods_before_write_hooks_run_at_revit_write_choke_point(monkeypatch, tmp_path):
    exec_calls = []
    monkeypatch.setattr(nodeslib, "_WRITE_GRANT_VERIFIER", lambda payload: {"ok": True, "receipt": "fixture"})
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: [{
        "port": 48884, "pid": 7, "revit_version": "2026", "document": "Court.rvt",
    }])
    monkeypatch.setattr(clean_revit_adapter, "_call", lambda *args, **kwargs: exec_calls.append(args) or {"status": "ok"})

    store = CellStore(tmp_path / "owner.sqlite3")
    refused = _revit_write_request(101, store)
    with pytest.raises(PermissionError, match="Element limit refused .*101 elements exceeds Limit 100"):
        clean_revit_adapter.invoke("revit.set_parameter_by_name", {**refused, "grant": _revit_write_grant(refused)})
    assert exec_calls == []

    passed = _revit_write_request(99, store)
    assert clean_revit_adapter.invoke("revit.set_parameter_by_name", {**passed, "grant": _revit_write_grant(passed)})["ok"] is True
    set_mod_enabled(store, "element-limit", False)
    off = _revit_write_request(101, store)
    assert clean_revit_adapter.invoke("revit.set_parameter_by_name", {**off, "grant": _revit_write_grant(off)})["ok"] is True
    set_mod_enabled(store, "element-limit", True)
    set_mod_param(store, "element-limit", "Limit", "200")
    larger = _revit_write_request(150, store)
    answer = clean_revit_adapter.invoke("revit.set_parameter_by_name", {**larger, "grant": _revit_write_grant(larger)})
    assert answer["receipt"]["mods_before_write"][0] == {
        "mod": "blast-radius", "label": "Blast radius",
        "host_count": 1, "document_count": 1, "element_count": 150,
    }
    assert answer["receipt"]["mods_before_write_details"] == [{
        "mod": "blast-radius", "label": "Blast radius", "host": "revit",
        "document": "Court.rvt", "elements": 150, "operation_scope": "selection",
    }]
    assert len(exec_calls) == 3
    fired = {row["id"]: row["fired_today"] for row in mods_rows(store)["rows"]}
    assert fired["element-limit"] == 1
    assert fired["blast-radius"] == 3


def test_mods_state_survives_restart_in_application_cellstore(tmp_path):
    path = tmp_path / "app.sqlite3"
    store = CellStore(path)
    set_mod_enabled(store, "element-limit", False)
    set_mod_param(store, "element-limit", "Limit", "7")
    store.close()

    reopened = CellStore(path)
    row = next(row for row in mods_rows(reopened)["rows"] if row["id"] == "element-limit")
    assert row["enabled"] is False
    assert row["nodes"][0]["params"]["Limit"] == 7


def test_corrupt_mods_state_is_visible_and_not_reset(tmp_path):
    store = CellStore(tmp_path / "app.sqlite3")
    owner = Cell("app:archhub:mods:owner", NULL_CELL_ID, NULL_CELL_ID, b"mods-owner")
    corrupt = Cell("app:archhub:mods:owner:element-limit", owner.id, NULL_CELL_ID, b"{")
    store.commit(store.revision, create=(owner, corrupt))

    with pytest.raises(InvalidCell, match="Mods state is unreadable: element-limit"):
        mods_rows(store)
    assert store.read(corrupt.id).atom == b"{"


def test_legacy_owner_graph_migrates_into_application_cellstore(tmp_path):
    path = tmp_path / "app.sqlite3"
    legacy_root = path.with_suffix(path.suffix + ".mods")
    legacy_root.mkdir()
    legacy_store = Store()
    enabled = legacy_store.add(
        "param", "element-limit enabled",
        floor={"op": "value", "value": True}, actor="mods-owner",
    )
    fired = legacy_store.add(
        "param", "element-limit fired today",
        floor={"op": "value", "value": 0}, actor="mods-owner",
    )
    params = legacy_store.add(
        "param", "element-limit owner params",
        floor={"op": "value", "value": {"Limit": 7}}, actor="mods-owner",
    )
    legacy_store.add(
        "group", "Mod owner: element-limit",
        inner=[enabled, fired, params],
        params={"enabled": enabled, "fired_today": fired, "params": params},
        actor="mods-owner",
    )
    legacy_file = legacy_root / "mods-owner.graph.json"
    legacy_file.write_text(
        json.dumps({"schema": "archhub.mods.owner-graph.v1", "nodes": legacy_store.nodes}),
        encoding="utf-8",
    )

    store = CellStore(path)
    row = next(row for row in mods_rows(store)["rows"] if row["id"] == "element-limit")

    assert row["enabled"] is True
    assert row["nodes"][0]["params"]["Limit"] == 7
    assert not legacy_file.exists()
    assert (legacy_root / "mods-owner.graph.json.migrated").is_file()
    assert json.loads(store.read("app:archhub:mods:owner:element-limit").atom)["params"] == {"Limit": 7}


def test_legacy_owner_params_migrates_and_is_archived(tmp_path):
    path = tmp_path / "app.sqlite3"
    legacy_root = path.with_suffix(path.suffix + ".mods")
    legacy_root.mkdir()
    legacy_file = legacy_root / "owner-params.json"
    legacy_file.write_text(
        json.dumps({"builtins": {"element-limit": {"enabled": True, "params": {"Limit": 7}}}}),
        encoding="utf-8",
    )

    store = CellStore(path)
    row = next(row for row in mods_rows(store)["rows"] if row["id"] == "element-limit")

    assert row["enabled"] is True
    assert row["nodes"][0]["params"]["Limit"] == 7
    assert not legacy_file.exists()
    assert (legacy_root / "owner-params.json.migrated").is_file()
