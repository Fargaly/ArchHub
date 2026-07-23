"""Courts for the Cell-ledger Core Values authority audit route."""
from __future__ import annotations

import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
SRC = Path(__file__).resolve().parents[1] / "src"
for path in (NODE_LANGUAGE, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from nodelang.application_server import ApplicationServer  # noqa: E402
from personal_brain import core_values_authority as cva  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


class _InProcessRuntimeBridge:
    def __init__(self, server) -> None:
        self._server = server

    def deliberation_append(self, **body):
        return self._server.dispatch_universal_machine_route({
            "method": "POST", "path": "/api/universal/deliberation",
            "body": dict(body),
        })

    def deliberation_read(self, **body):
        return self._server.dispatch_universal_machine_route({
            "method": "GET", "path": "/api/universal/deliberation",
            "body": dict(body),
        })


class _FailingBridge:
    def deliberation_append(self, **body):  # noqa: ARG002
        raise RuntimeError("ledger unavailable")


def _green_authority() -> dict[str, object]:
    return {
        "authority_root": cva.AUTHORITY_ROOT,
        "authority_wire_root": cva.AUTHORITY_WIRE_ROOT,
        "source_digest": "source-digest",
        "translation_digest": "translation-digest",
        "lifecycle": "WIP",
        "graph_revision": 42,
        "revision_chain_digest": "revision-digest",
        "coverage": {key: "green" for key in cva.VALUE_KEYS},
        "database_identity": "database-identity",
    }


def test_core_values_audit_is_cell_ledger_only_and_readable():
    store = BrainStore.open(":memory:")
    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = cva.audit_cell_first(
            store,
            owner_user="founder",
            loader=_green_authority,
            cell_bridge=bridge,
        )
        assert result["ok"] is True
        assert result["brain_written"] is False
        assert result["report"]["cell_first"] is True
        assert result["cell_record"]["root"] == result["report"]["cell_entry_root"]
        assert store.get_meta(cva.AUTHORITY_META_KEY) is None

        report = cva.get_report_cell_first(
            store, owner_user="founder", cell_bridge=bridge
        )
        assert report is not None
        assert report.status == cva.GREEN
        assert report.translation_digest == "translation-digest"
        assert report.cell_entry_root == result["cell_record"]["root"]
    finally:
        server.close()
        store.close()


def test_core_values_audit_fails_closed_without_writing_metadata():
    store = BrainStore.open(":memory:")
    try:
        result = cva.audit_cell_first(
            store,
            owner_user="founder",
            loader=_green_authority,
            cell_bridge=_FailingBridge(),
        )
        assert result["ok"] is False
        assert result["brain_written"] is False
        assert "ledger unavailable" in result["error"]
        assert store.get_meta(cva.AUTHORITY_META_KEY) is None
    finally:
        store.close()
