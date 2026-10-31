import time

import pytest


def _approval_grant(**overrides):
    grant = {
        "kind": "workshop-workflow-approval",
        "digest": "a" * 64,
        "approved_by": "app:founder",
        "current": True,
        "scope": "revit.write",
        "operations": ["revit.set_parameter_by_name", "revit.create_sheets", "revit.renumber_rename"],
        "expires_at": time.time() + 60,
        "caller": "codex",
        "session": "court-session",
        "work": "court-work",
        "input_digest": "0" * 64,
        "action": "revit.set_parameter_by_name",
    }
    grant.update(overrides)
    return grant


def _file_grant(path, **overrides):
    grant = {
        "kind": "cde-write-permit",
        "path": str(path),
        "scope": "exact",
        "operations": ["write_file"],
        "expires_at": time.time() + 60,
        "allow_overwrite": False,
        "digest": "b" * 64,
        "caller": "codex",
        "session": "court-session",
        "work": "court-work",
        "input_digest": "0" * 64,
        "action": "write_file",
    }
    grant.update(overrides)
    return grant


def test_palette_uses_one_engine_set_and_hides_engine_less_speckle_cards():
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES, engine_runs, library_catalogue
    from nodelang.pipeline_engines import PIPELINE_ENGINES

    served = {item["id"]: item for group in library_catalogue() for item in group["items"]}
    assert "h_speckle_receive" not in served
    assert "s_speckle_diff" not in served
    assert "h_write" not in served
    for item in ("b_override_colour", "file_write_excel", "file_write_csv", "file_schedule_excel",
                 "file_export_dwg", "file_export_ifc"):
        assert item not in served
    for item in ("b_all_category", "b_get_parameter", "r_xl_range", "b_set_parameter",
                 "b_create_sheets", "b_renumber", "g_approval_gate"):
        assert item in served
    assert served["s_sort"]["engine"] == "shape.sort"
    assert served["l_if_handoff"]["engine"] == "control.if"
    assert served["l_merge_handoff"]["engine"] == "control.merge"
    for item in served.values():
        assert engine_runs(item["engine"], PIPELINE_ENGINES), item["id"]
        assert not item.get("noEngine"), item["id"]
    assert LIBRARY_ITEM_ENGINES["t_sort"]["engine"] == "shape.sort"


def test_category_read_returns_its_elements(monkeypatch):
    from nodelang import nodeslib_v2_engines as engines

    calls = []

    def fake(operation, arguments):
        calls.append((operation, arguments))
        return {"result": [{"id": 1, "category": arguments["category"]}]}

    monkeypatch.setattr(engines, "_REVIT_BROKER", fake)
    out, shown = engines.revit_elements_of_category({"category": "Walls"}, {})
    assert out["elements"] == [{"id": 1, "category": "Walls"}]
    assert calls == [("revit.elements_of_category", {"category": "Walls", "scope": "document", "session": ""})]
    assert shown == "1 Walls element(s)"


def test_parameter_read_goes_to_fixture_broker_and_reports_missing(monkeypatch):
    from nodelang import nodeslib_v2_engines as engines

    def fake(operation, arguments):
        assert operation == "revit.get_parameter"
        assert arguments["name"] == "Fire Rating"
        return {"result": [
            {"id": 7, "name": "A", "value": "2 HR"},
            {"id": 8, "name": "B", "value": None, "note": "parameter missing"},
        ]}

    monkeypatch.setattr(engines, "_REVIT_BROKER", fake)
    out, shown = engines.revit_get_parameter({"parameter": "Fire Rating"}, {"elements": [{"id": 7}, {"id": 8}]})
    assert out["values"][1]["value"] is None
    assert out["values"][1]["note"] == "parameter missing"
    assert shown == "2 value(s) for Fire Rating"


def test_set_parameter_by_name_requires_verified_grant_before_host(monkeypatch):
    from nodelang import nodeslib_v2_engines as engines

    with pytest.raises(ValueError, match="approval grant"):
        engines.revit_set_parameter({"parameter": "Comments", "value": "Issued"}, {"elements": [{"id": 7}]})

    calls = []
    monkeypatch.setattr(engines, "_REVIT_BROKER", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="input digest|verified binding"):
        engines.revit_set_parameter(
            {"parameter": "Comments", "value": "Issued", "grant": _approval_grant()}, {"elements": [{"id": 7}]})
    assert calls == []


@pytest.mark.parametrize("grant", [
    "approved",
    _approval_grant(current=False),
    _approval_grant(expires_at=1),
    _approval_grant(scope="excel.write"),
    _approval_grant(digest=None),
    _approval_grant(action="revit.create_sheets"),
])
def test_forged_missing_field_expired_or_wrong_scope_grants_make_zero_host_calls(monkeypatch, grant):
    from nodelang import nodeslib_v2_engines as engines

    calls = []
    monkeypatch.setattr(engines, "_REVIT_BROKER", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="approval grant|expired|scope|current|signed|action|digest"):
        engines.revit_set_parameter({"parameter": "Comments", "value": "Issued", "grant": grant}, {"elements": [{"id": 7}]})
    assert calls == []


def test_revit_write_requires_confirmed_broker_receipt(monkeypatch):
    from nodelang import nodeslib_v2_engines as engines

    request = {"elements": [{"id": 7}], "name": "Comments", "value": "Issued"}
    grant = _approval_grant(input_digest=engines._digest_payload(request))
    verifier_calls = []
    monkeypatch.setattr(engines, "_WRITE_GRANT_VERIFIER", lambda req: verifier_calls.append(req) or {"ok": True})
    monkeypatch.setattr(engines, "_REVIT_BROKER", lambda *_: {"ok": False, "error": "broker refused"})
    with pytest.raises(ValueError, match="broker refused"):
        engines.revit_set_parameter(
            {"parameter": "Comments", "value": "Issued", "grant": grant}, {"elements": [{"id": 7}]})
    assert verifier_calls[0]["operation"] == "revit.set_parameter_by_name"


def test_excel_write_is_hidden_without_governed_file_writer(tmp_path, monkeypatch):
    from nodelang.nodeslib_v2_engines import write_table_file

    target = tmp_path / "schedule.xlsx"
    calls = []
    monkeypatch.setattr("nodelang.nodeslib_v2_engines._FILE_WRITE_BROKER", lambda req: calls.append(req))
    with pytest.raises(ValueError, match="input digest|verifier"):
        write_table_file({"path": str(target), "format": "xlsx", "grant": _file_grant(target)}, {
            "rows": [{"Number": "A101", "Name": "Plan"}]})
    assert calls == []
    assert not target.exists()


def test_denied_file_write_preserves_existing_bytes(tmp_path):
    from nodelang import nodeslib_v2_engines as engines

    target = tmp_path / "schedule.csv"
    target.write_bytes(b"keep-me")
    request = {"rows": [{"number": "A-001"}], "path": str(target), "format": "csv"}
    grant = _file_grant(target, input_digest=engines._digest_payload(request))
    with pytest.raises(ValueError, match="not bound"):
        engines.write_table_file({"path": str(target), "format": "csv", "grant": grant}, {
            "rows": [{"number": "A-001"}]})
    assert target.read_bytes() == b"keep-me"


def test_excel_read_range_uses_fixture_workbook_only(tmp_path):
    from nodelang import host_brokers
    from nodelang.nodeslib_v2_engines import _write_xlsx

    workbook = tmp_path / "fixture.xlsx"
    _write_xlsx([{"number": "A-001", "name": "Plan"}, {"number": "A-002", "name": "Section"}], workbook)
    out, shown = host_brokers.office_read(
        {"operation": "excel.read_range", "file": str(workbook), "sheet": "Sheet1", "range": "A1:B3"}, {})
    assert out["out"]["rows"] == [["number", "name"], ["A-001", "Plan"], ["A-002", "Section"]]
    assert shown == "excel.read_range: 3"


def test_expression_is_right_and_unsafe_input_is_refused():
    from nodelang.nodeslib_v2_engines import expression

    out, shown = expression({"expression": "a * 2 + b", "a": "4", "b": "3"}, {})
    assert out["value"] == 11
    assert shown == "a * 2 + b = 11.0"
    with pytest.raises(ValueError, match="unsupported syntax"):
        expression({"expression": "__import__('os').system('echo bad')"}, {})


def test_approval_gate_blocks_until_approved():
    from nodelang import nodeslib_v2_engines as engines

    with pytest.raises(ValueError, match="approval required"):
        engines.approval_gate({"approved": "false"}, {"in": {"change": 1}})
    out, shown = engines.approval_gate({"operation": "revit.set_parameter_by_name", "grant": _approval_grant()}, {"in": {"change": 1}})
    assert out["out"] == {"change": 1}
    assert out["grant"]["digest"] == "a" * 64
    assert shown == "awaiting approved grant"
    with pytest.raises(ValueError, match="does not cover"):
        engines.approval_gate({"operation": "revit.override_color_in_view", "grant": _approval_grant()}, {"in": {"change": 1}})


def test_dry_run_diff_shows_changes_without_applying_them():
    from nodelang.nodeslib_v2_engines import dry_run_diff

    before = [{"id": 1, "name": "A"}]
    proposed = [{"id": 1, "name": "B"}]
    out, shown = dry_run_diff({}, {"before": before, "after": proposed})
    assert out["diff"] == {"before_count": 1, "after_count": 1, "changes": proposed}
    assert before == [{"id": 1, "name": "A"}]
    assert shown == "1 proposed change(s), not applied"


def test_mesh_preview_drops_bad_vertices_and_faces_positionally():
    from nodelang.stem_graph_evaluation import _mesh_preview

    mesh = _mesh_preview({
        "vertices": [
            ["bad", 1, 2],
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [9, 9],
            [float("nan"), 0, 0],
            [0, float("inf"), 0],
        ],
        "faces": [[0, 1, 2], [1, 2, 3], [4, 1, 2], [1, "x", 3]],
    })
    assert mesh["vertices"] == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert mesh["faces"] == [[0, 1, 2]]
    assert mesh["shape"] == {"vertices": 3, "faces": 1}
