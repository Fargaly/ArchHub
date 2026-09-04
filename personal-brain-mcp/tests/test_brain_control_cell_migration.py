"""Court for Brain control-plane meta import into Universal Cell work."""
from pathlib import Path
import inspect
import json
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from personal_brain import compliance_report as cr  # noqa: E402
from personal_brain import hook_coverage as hc  # noqa: E402
from personal_brain import run_report as rr  # noqa: E402
from personal_brain import active_work_cell_migration as bcm  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


class _InProcessRuntimeBridge:
    """Exercise the application dispatcher without owning the Cell store."""

    def __init__(self, server):
        self._server = server

    def _request(self, method, path, body=None):
        return self._server.dispatch_universal_machine_route({
            "method": method,
            "path": path,
            "body": dict(body or {}),
        })

    def work_list(self):
        return self._request("GET", "/api/universal/work")

    def work_create(self, **body):
        return self._request("POST", "/api/universal/work", body)

    def assembly_create(self, **body):
        return self._request("POST", "/api/universal/assembly", body)

    def assembly_field_update(self, **body):
        return self._request("POST", "/api/universal/assembly-field", body)

    def deliberation_append(self, **body):
        return self._request("POST", "/api/universal/deliberation", body)

    def deliberation_read(self, **body):
        return self._request("GET", "/api/universal/deliberation", body)

    def value_read(self, root_id):
        return self._request(
            "POST", "/api/universal/value", {"root": root_id}
        )["value"]


class _MutatingBridge:
    def __init__(self, brain):
        self._brain = brain

    def work_list(self):
        return {"brain_scope": "scope:brain", "items": [], "revision": "r1"}

    def assembly_create(self, **body):  # noqa: ARG002
        self._brain.set_meta(hc.COVERAGE_META_KEY, "{}")
        return {
            "created_root": "assembly-instance:mutated-record",
            "assembly": {"interfaces": []},
        }

    def work_create(self, **body):  # noqa: ARG002
        return {
            "created_root": "assembly-instance:mutated",
            "membership_wire": "relation:mutated",
        }


class _FailingDeliberationBridge:
    def deliberation_append(self, **body):  # noqa: ARG002
        raise RuntimeError("cell ledger refused")


class _RecordingDeliberationBridge:
    def __init__(self):
        self.reads = []

    def deliberation_read(self, **body):
        self.reads.append(body)
        return {"entries": [], "total": 0}


def test_cell_first_control_reads_request_only_the_required_category(store):
    bridge = _RecordingDeliberationBridge()

    compliance = cr.get_compliance_history_cell_first(
        store,
        owner_user="founder",
        limit=7,
        cell_bridge=bridge,
    )
    reports = rr.get_run_reports_cell_first(
        store,
        owner_user="founder",
        limit=3,
        cell_bridge=bridge,
    )

    assert compliance["ok"] is True
    assert reports["ok"] is True
    assert bridge.reads == [
        {
            "space": cr.CELL_CONTROL_LEDGER_ROOT,
            "category": cr.CELL_COMPLIANCE_CATEGORY_ROOT,
            "limit": 7,
        },
        {
            "space": rr.CELL_CONTROL_LEDGER_ROOT,
            "category": rr.CELL_RUN_REPORT_CATEGORY_ROOT,
            "limit": 3,
        },
    ]


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _seed_control_records(store):
    records = {
        hc.COVERAGE_META_KEY: {
            "schema": "hook-coverage/v1",
            "status": "green",
            "clients": {"codex": {"status": "green"}},
        },
        cr.HISTORY_META_KEY: {
            "schema": "archhub-compliance-history/v1",
            "owners": {
                "founder": {
                    "events": [
                        {
                            "event_type": "write_gate_decision",
                            "decision": "deny",
                        }
                    ]
                }
            },
        },
        rr.RUN_REPORT_META_KEY: {
            "schema": "archhub-run-report-ledger/v1",
            "owners": {
                "founder": {
                    "reports": [
                        {
                            "report_id": "rr_1",
                            "sections": {"evidence": ["pytest"]},
                        }
                    ]
                }
            },
        },
    }
    for key, value in records.items():
        store.set_meta(key, json.dumps(value, sort_keys=True))
    return {key: store.get_meta(key) for key in records}


def test_brain_control_records_import_as_cell_work_and_preserve_source(store):
    source_before = _seed_control_records(store)
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        first = bcm.migrate_brain_control_records_to_cells(
            store,
            bridge=bridge,
            owner_user="founder",
        )
        assert first["source_preserved"] is True
        assert len(first["imported"]) == 3
        assert first["skipped"] == []
        assert first["missing"] == []
        assert {
            item["meta_key"] for item in first["imported"]
        } == {
            hc.COVERAGE_META_KEY,
            cr.HISTORY_META_KEY,
            rr.RUN_REPORT_META_KEY,
        }
        assert all(item["record_root"] for item in first["imported"])
        assert {
            key: store.get_meta(key) for key in source_before
        } == source_before

        work = bridge.work_list()["items"]
        by_external = {
            item["interfaces"]["external-key"]["value"]: item
            for item in work
        }
        hook_external = next(
            item["external_key"]
            for item in bcm._source_records(store)
            if item["meta_key"] == hc.COVERAGE_META_KEY
        )
        hook_work = by_external[hook_external]
        plan = bridge.value_read(hook_work["interfaces"]["plan"]["target"])
        assert plan["record_root"] == first["imported"][0]["record_root"]
        assert plan["record_definition"] == "knowledge-branch"
        inputs = bridge.value_read(
            hook_work["interfaces"]["inputs"]["target"]
        )
        assert inputs["source"]["meta_key"] == hc.COVERAGE_META_KEY
        assert inputs["source"]["record_root"] == first["imported"][0]["record_root"]
        assert inputs["source"]["digest"] == first["imported"][0]["digest"]
        assert inputs["record"]["payload"]["status"] == "green"
        assert inputs["migration_state_policy"].startswith(
            "legacy Brain meta row remains evidence"
        )
        policy = bridge.value_read(
            hook_work["interfaces"]["applicable-policy"]["target"]
        )
        assert policy["authority"] == "10.PRODUCT/13.NODE-LANGUAGE"
        assert policy["promotion_allowed"] is False
        requirements = bridge.value_read(
            hook_work["interfaces"]["requirements"]["target"]
        )
        assert requirements["gate"]["kind"] == "pytest"

        second = bcm.migrate_brain_control_records_to_cells(
            store,
            bridge=bridge,
            owner_user="founder",
        )
        assert second["imported"] == []
        assert len(second["skipped"]) == 3
        assert all(item["record_root"] for item in second["skipped"])
        assert {
            key: store.get_meta(key) for key in source_before
        } == source_before
        assert len(bridge.work_list()["items"]) == 3
    finally:
        server.close()


def test_brain_control_import_uses_stable_work_identity_when_digest_changes(store):
    _seed_control_records(store)
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        first = bcm.migrate_brain_control_records_to_cells(
            store,
            bridge=bridge,
            owner_user="founder",
        )
        assert len(first["imported"]) == 3
        changed = {
            "schema": "hook-coverage/v1",
            "status": "yellow",
            "clients": {"codex": {"status": "yellow"}},
        }
        store.set_meta(
            hc.COVERAGE_META_KEY,
            json.dumps(changed, sort_keys=True),
        )
        second = bcm.migrate_brain_control_records_to_cells(
            store,
            bridge=bridge,
            owner_user="founder",
        )
        assert second["imported"] == []
        assert len(second["skipped"]) == 3
        assert len(bridge.work_list()["items"]) == 3
    finally:
        server.close()


def test_brain_control_import_reports_missing_records_without_fake_success(store):
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = bcm.migrate_brain_control_records_to_cells(
            store,
            bridge=bridge,
        )
        assert result["record_count"] == 0
        assert result["imported"] == []
        assert result["missing"] == [
            hc.COVERAGE_META_KEY,
            cr.HISTORY_META_KEY,
            rr.RUN_REPORT_META_KEY,
        ]
        assert bridge.work_list()["items"] == ()
    finally:
        server.close()


def test_brain_control_import_fails_if_source_meta_mutates_mid_import(store):
    _seed_control_records(store)

    with pytest.raises(
        RuntimeError,
        match="legacy Brain control-plane evidence changed",
    ):
        bcm.migrate_brain_control_records_to_cells(
            store,
            bridge=_MutatingBridge(store),
        )


def test_compliance_event_append_syncs_current_record_to_cells(store):
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = cr.append_compliance_event(
            store,
            owner_user="founder",
            cell_bridge=bridge,
            event={
                "event_type": "write_gate_decision",
                "decision": "deny",
                "code": "missing_active_cde",
            },
        )

        assert result["ok"] is True
        assert result["cell_sync"]["ok"] is True
        assert result["cell_sync"]["record_count"] == 1
        assert result["cell_sync"]["imported"][0]["meta_key"] == cr.HISTORY_META_KEY
        work = bridge.work_list()["items"]
        assert len(work) == 1
        record_root = result["cell_sync"]["imported"][0]["record_root"]
        assert record_root
        inputs = bridge.value_read(work[0]["interfaces"]["inputs"]["target"])
        assert inputs["source"]["record_root"] == record_root
        assert inputs["record"]["payload"]["owners"]["founder"]["events"][0][
            "decision"
        ] == "deny"
    finally:
        server.close()


def test_run_report_append_syncs_report_and_history_records_to_cells(store):
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = rr.append_run_report(
            store,
            owner_user="founder",
            leaf_id="leaf-1",
            runtime="codex",
            agent_id="session-1",
            cell_bridge=bridge,
            report={
                "what_i_did": ["Added report"],
                "where_we_are": ["Report is mirrored"],
                "evidence": ["test_brain_control_cell_migration.py"],
                "problems_risks": [],
                "whats_next": ["Retire Brain meta write path"],
            },
        )

        assert result["ok"] is True
        assert result["cell_sync"]["ok"] is True
        assert result["cell_sync"]["record_count"] == 2
        assert {
            item["meta_key"] for item in result["cell_sync"]["imported"]
        } == {cr.HISTORY_META_KEY, rr.RUN_REPORT_META_KEY}
        work = bridge.work_list()["items"]
        assert len(work) == 2
        by_title = {
            item["interfaces"]["title"]["value"]: item
            for item in work
        }
        run_work = by_title["Consume Brain control record: Run Reports"]
        inputs = bridge.value_read(
            run_work["interfaces"]["inputs"]["target"]
        )
        report = inputs["record"]["payload"]["owners"]["founder"]["reports"][0]
        assert report["leaf_id"] == "leaf-1"
        assert report["runtime"] == "codex"
    finally:
        server.close()


def test_compliance_event_cell_first_writes_only_the_graph_ledger(store):
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = cr.append_compliance_event_cell_first(
            store,
            owner_user="founder",
            cell_bridge=bridge,
            event={
                "event_type": "write_gate_decision",
                "decision": "deny",
                "code": "missing_active_cde",
            },
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["event"]["cell_entry_root"]
        assert result["event"]["cell_payload_root"]
        assert store.get_meta(cr.HISTORY_META_KEY) is None
        history = cr.get_compliance_history_cell_first(
            store,
            owner_user="founder",
            limit=1,
            cell_bridge=bridge,
        )
        event = history["events"][0]
        assert event["cell_entry_root"] == result["event"]["cell_entry_root"]
        assert event["cell_payload_root"] == result["event"]["cell_payload_root"]
        assert event["decision"] == "deny"
    finally:
        server.close()


def test_compliance_event_cell_first_fails_closed_before_brain_write(store):
    result = cr.append_compliance_event_cell_first(
        store,
        owner_user="founder",
        cell_bridge=_FailingDeliberationBridge(),
        event={
            "event_type": "write_gate_decision",
            "decision": "deny",
        },
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert "cell ledger refused" in result["error"]
    assert store.get_meta(cr.HISTORY_META_KEY) is None


def test_run_report_cell_first_writes_only_the_graph_ledger(store):
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = rr.append_run_report_cell_first(
            store,
            owner_user="founder",
            leaf_id="leaf-2",
            runtime="codex",
            agent_id="session-2",
            cell_bridge=bridge,
            report={
                "what_i_did": ["Built cell-first run report"],
                "where_we_are": ["Run report is a Cell record first"],
                "evidence": ["test_brain_control_cell_migration.py"],
                "problems_risks": [],
                "whats_next": ["Retire legacy run report append"],
            },
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["report"]["cell_entry_root"]
        assert result["report"]["cell_payload_root"]
        assert store.get_meta(rr.RUN_REPORT_META_KEY) is None
        assert store.get_meta(cr.HISTORY_META_KEY) is None
        latest = rr.get_run_reports_cell_first(
            store,
            owner_user="founder",
            leaf_id="leaf-2",
            limit=1,
            cell_bridge=bridge,
        )
        report = latest["reports"][0]
        assert report["cell_entry_root"] == result["report"]["cell_entry_root"]
        assert report["runtime"] == "codex"
        assert result["compliance_event"]["ok"] is True
        assert result["compliance_event"]["cell_first"] is True
    finally:
        server.close()


def test_run_report_cell_first_fails_closed_before_brain_write(store):
    result = rr.append_run_report_cell_first(
        store,
        owner_user="founder",
        leaf_id="leaf-2",
        runtime="codex",
        agent_id="session-2",
        cell_bridge=_FailingDeliberationBridge(),
        report={
            "what_i_did": ["This must not persist"],
            "where_we_are": ["Cell create failed"],
            "evidence": ["failure"],
            "problems_risks": [],
            "whats_next": ["retry"],
        },
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert "cell ledger refused" in result["error"]
    assert store.get_meta(rr.RUN_REPORT_META_KEY) is None
    assert store.get_meta(cr.HISTORY_META_KEY) is None


def test_brain_control_bridge_does_not_open_cell_store_or_sqlite():
    source = inspect.getsource(bcm)

    assert "CellStore" not in source
    assert "sqlite3" not in source
    assert "from nodelang" not in source


def test_runtime_assembly_route_creates_and_edits_standard_library_record():
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        before = server.universal_store.revision
        created = bridge.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": "brain-control:manual",
                "scope": "founder/brain-control",
                "claims": "initial claim",
                "provenance": "test",
            },
            idempotency_field="source",
            x=500,
            y=600,
        )
        assert created["ok"] is True
        assert created["definition_key"] == "knowledge-branch"
        assert created["existing"] is False
        assert created["revision"] == before + 1
        assert server.universal_store.revision == before + 1
        by_name = {
            item["name"]: item
            for item in created["assembly"]["interfaces"]
        }
        assert by_name["source"]["value"] == "brain-control:manual"
        assert by_name["claims"]["editable"] is True

        edited = bridge.assembly_field_update(
            root=created["created_root"],
            interface=by_name["claims"]["id"],
            value="edited claim",
        )
        edited_by_name = {
            item["name"]: item
            for item in edited["assembly"]["interfaces"]
        }
        assert edited_by_name["claims"]["value"] == "edited claim"

        before_repeat = server.universal_store.revision
        repeated = bridge.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": "brain-control:manual",
                "scope": "founder/brain-control",
                "claims": "ignored by idempotency",
                "provenance": "test",
            },
            idempotency_field="source",
            x=500,
            y=600,
        )
        assert repeated["existing"] is True
        assert repeated["created_root"] == created["created_root"]
        assert server.universal_store.revision == before_repeat
    finally:
        server.close()


def test_runtime_assembly_route_wires_structured_fields_as_value_graphs():
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    claims = {
        "operation": "brain.skill_mint",
        "tool_call_count": 2,
        "redacted": True,
    }
    try:
        created = bridge.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": "brain-control:structured-claim",
                "scope": "founder/brain-control",
                "provenance": "test",
            },
            structured_fields={"claims": claims},
            idempotency_field="source",
            x=500,
            y=600,
        )
        assert created["ok"] is True
        attached = created["structured_fields"]["claims"]
        assert bridge.value_read(attached["value_root"]) == claims
        assert attached["relation_root"] in server.universal_store.snapshot().cells
        interface = next(
            item for item in created["assembly"]["interfaces"]
            if item["name"] == "claims"
        )
        assert interface["value"] != json.dumps(claims, sort_keys=True)
    finally:
        server.close()
