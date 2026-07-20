"""Court for non-destructive migration of the Brain JSON ledger into Cells."""
from pathlib import Path
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_attestations import CourtResult  # noqa: E402
from nodelang.cell_secret_keys import MemorySigningKeyProvider  # noqa: E402
from personal_brain import active_work as legacy  # noqa: E402
from personal_brain.active_work_cell_migration import (  # noqa: E402
    migrate_active_work_to_cells,
)
from personal_brain.storage import BrainStore  # noqa: E402
from personal_brain.server import build_server  # noqa: E402
from personal_brain.universal_runtime import UniversalRuntimeBridge  # noqa: E402
from personal_brain.universal_runtime import UniversalRuntimeUnavailable  # noqa: E402
from personal_brain.universal_session_manager import (  # noqa: E402
    UniversalRuntimeSessionManager,
)


def _green_runtime_compliance(_invocation):
    checks = {
        "runtime-detected": True,
        "required-hooks": True,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": True,
        "workshop-authority": True,
    }
    return CourtResult(True, checks, {"adapter": "brain-bridge-court"})


class _InProcessRuntimeBridge:
    """Exercise the application dispatcher without a second graph owner."""

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

    def value_read(self, root_id):
        return self._request(
            "POST", "/api/universal/value", {"root": root_id}
        )["value"]


class _CountingBridge(_InProcessRuntimeBridge):
    def __init__(self, server):
        super().__init__(server)
        self.work_list_calls = 0

    def work_list(self):
        self.work_list_calls += 1
        return super().work_list()


class _TimeoutAfterCreateBridge(_InProcessRuntimeBridge):
    def work_create(self, **body):
        super().work_create(**body)
        raise UniversalRuntimeUnavailable("universal runtime did not respond")


class _IndexOnlyBridge(_InProcessRuntimeBridge):
    def __init__(self, server):
        super().__init__(server)
        self.work_index_calls = 0

    def work_index(self):
        self.work_index_calls += 1
        return self._request(
            "GET", "/api/universal/work", {"projection": "index"}
        )

    def work_list(self):  # pragma: no cover - this is the assertion
        raise AssertionError("migration must use the compact work index")


class _MutatingBridge:
    def __init__(self, brain):
        self._brain = brain

    def work_list(self):
        return {"brain_scope": "scope:brain", "items": [], "revision": "r1"}

    def work_create(self, **body):  # noqa: ARG002
        self._brain.set_meta(legacy.LEDGER_META_KEY, "{}")
        return {
            "created_root": "assembly-instance:mutated",
            "membership_wire": "relation:mutated",
        }


def test_legacy_work_import_is_complete_idempotent_and_source_preserving():
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[
            {
                "title": "Migrate Brain authority",
                "gate_kind": "pytest",
                "gate_spec": {"path": "tests/test_brain.py", "args": ["-q"]},
                "cde_container": {"container_id": "brain", "tier": "T1"},
                "governance_context": {"policy": "core-values"},
                "fit": ["python", "governance"],
                "priority": 100,
            },
            {
                "title": "Retire the JSON mutation path",
                "gate_kind": "grep_clean",
                "gate_spec": {"pattern": "active_work_v1"},
                "fit": ["python"],
                "priority": 90,
            },
        ],
    )
    source_before = brain.get_meta(legacy.LEDGER_META_KEY)

    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        first = migrate_active_work_to_cells(brain, bridge=bridge)
        assert first["source_preserved"] is True
        assert first["complete"] is True
        assert first["remaining"] == 0
        assert len(first["imported"]) == 2
        assert first["skipped"] == []
        assert brain.get_meta(legacy.LEDGER_META_KEY) == source_before

        work = bridge.work_list()["items"]
        assert len(work) == 2
        by_key = {
            item["interfaces"]["external-key"]["value"]: item
            for item in work
        }
        ledger = legacy.get_ledger(brain, owner_user="founder")
        migrated = by_key[next(
            leaf.leaf_id for leaf in ledger.leaves.values()
            if leaf.title == "Migrate Brain authority"
        )]
        requirements = bridge.value_read(
            migrated["interfaces"]["requirements"]["target"]
        )
        assert requirements == {
            "gate": {
                "kind": "pytest",
                "spec": {"path": "tests/test_brain.py", "args": ["-q"]},
            }
        }
        assert bridge.value_read(
            migrated["interfaces"]["cde-container"]["target"]
        ) == {"container_id": "brain", "tier": "T1"}
        assert bridge.value_read(
            migrated["interfaces"]["required-capabilities"]["target"]
        ) == ["python", "governance"]
        provenance = bridge.value_read(
            migrated["interfaces"]["inputs"]["target"]
        )
        assert provenance["source"]["digest"] == first["source_digest"]
        assert provenance["leaf"]["state"] == "open"
        assert provenance["migration_state_policy"].startswith(
            "legacy state is evidence"
        )

        second = migrate_active_work_to_cells(brain, bridge=bridge)
        assert second["imported"] == []
        assert second["complete"] is True
        assert len(second["skipped"]) == 2
        assert brain.get_meta(legacy.LEDGER_META_KEY) == source_before
        assert len(bridge.work_list()["items"]) == 2
    finally:
        server.close()
        brain.close()


def test_legacy_work_import_can_run_as_bounded_batches_without_rescan():
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[
            {"title": "Batch leaf 1", "priority": 30},
            {"title": "Batch leaf 2", "priority": 20},
            {"title": "Batch leaf 3", "priority": 10},
        ],
    )
    source_before = brain.get_meta(legacy.LEDGER_META_KEY)

    server = ApplicationServer().start()
    bridge = _CountingBridge(server)
    try:
        first = migrate_active_work_to_cells(brain, bridge=bridge, limit=1)
        assert len(first["imported"]) == 1
        assert first["remaining"] == 2
        assert first["complete"] is False
        assert first["migration_limit"] == 1
        assert bridge.work_list_calls == 1
        assert brain.get_meta(legacy.LEDGER_META_KEY) == source_before

        second = migrate_active_work_to_cells(brain, bridge=bridge, limit=1)
        assert len(second["imported"]) == 1
        assert len(second["skipped"]) == 1
        assert second["remaining"] == 1
        assert second["complete"] is False
        assert bridge.work_list_calls == 2

        third = migrate_active_work_to_cells(brain, bridge=bridge, limit=1)
        assert len(third["imported"]) == 1
        assert len(third["skipped"]) == 2
        assert third["remaining"] == 0
        assert third["complete"] is True
        assert bridge.work_list_calls == 3
        assert len(bridge.work_list()["items"]) == 3
    finally:
        server.close()
        brain.close()


def test_legacy_work_import_can_be_confined_to_explicit_leaf_ids():
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[
            {"title": "Authority split leaf", "priority": 30},
            {"title": "Out of scope monetization leaf", "priority": 20},
        ],
    )
    ledger = legacy.get_ledger(brain, owner_user="founder")
    target = next(
        leaf.leaf_id for leaf in ledger.leaves.values()
        if leaf.title == "Authority split leaf"
    )

    server = ApplicationServer().start()
    bridge = _InProcessRuntimeBridge(server)
    try:
        result = migrate_active_work_to_cells(
            brain,
            bridge=bridge,
            leaf_ids=[target],
        )
        assert [item["leaf_id"] for item in result["imported"]] == [target]
        assert result["excluded"] == 1
        assert result["remaining"] == 0
        assert result["complete"] is True
        assert result["leaf_id_filter_count"] == 1
        work = bridge.work_list()["items"]
        assert len(work) == 1
        assert work[0]["interfaces"]["external-key"]["value"] == target
    finally:
        server.close()
        brain.close()


def test_legacy_work_import_prefers_compact_runtime_index():
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[{"title": "Indexed migration leaf", "priority": 30}],
    )

    server = ApplicationServer().start()
    bridge = _IndexOnlyBridge(server)
    try:
        result = migrate_active_work_to_cells(brain, bridge=bridge)
        assert len(result["imported"]) == 1
        assert bridge.work_index_calls == 1
        index = bridge.work_index()
        assert index["total"] == 1
        assert index["items"][0]["interfaces"]["external-key"]["value"] \
            == result["imported"][0]["leaf_id"]
    finally:
        server.close()
        brain.close()


def test_legacy_work_import_recovers_when_create_times_out_after_commit():
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[{"title": "Timeout after commit", "priority": 40}],
    )

    server = ApplicationServer().start()
    bridge = _TimeoutAfterCreateBridge(server)
    try:
        result = migrate_active_work_to_cells(
            brain,
            bridge=bridge,
            recovery_attempts=1,
            recovery_sleep=0.0,
        )
        assert len(result["imported"]) == 1
        assert result["imported"][0]["recovered_after_timeout"] is True
        assert len(bridge.work_list()["items"]) == 1
    finally:
        server.close()
        brain.close()


def test_legacy_work_import_fails_if_source_row_mutates_mid_import():
    brain = BrainStore.open(":memory:")
    try:
        legacy.add_leaves(
            brain,
            owner_user="founder",
            leaves=[{"title": "mutation must fail"}],
        )

        with pytest.raises(RuntimeError, match="legacy active-work evidence changed"):
            migrate_active_work_to_cells(brain, bridge=_MutatingBridge(brain))
    finally:
        brain.close()


def test_session_aware_assigned_block_claims_only_from_cell_graph(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"m" * 32
    )
    descriptor = tmp_path / "runtime.json"
    application = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    manager = UniversalRuntimeSessionManager(
        lambda: UniversalRuntimeBridge(descriptor, provider)
    )
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[{
            "title": "Cell-native assignment",
            "gate_kind": "pytest",
            "gate_spec": {"path": "tests/court.py"},
            "cde_container": {
                "container_id": "GM.nodes.runtime",
                "allowed_paths": ["10.PRODUCT/13.NODE-LANGUAGE/"],
            },
            "priority": 100,
        }],
    )
    source_before = brain.get_meta(legacy.LEDGER_META_KEY)
    mcp = build_server(store=brain, runtime_session_manager=manager)
    tool = mcp._tools["brain.work_assigned_block"].handler
    try:
        assigned = tool(
            runtime="codex",
            session_id="codex-session-1",
            owner_user="founder",
        )
        assert assigned["ok"] is True
        assert assigned["status"]["counts"]["claimed"] == 1
        assert assigned["universal"] is True
        assert assigned["leaf"]["title"] == "Cell-native assignment"
        assert assigned["leaf"]["work_root"].startswith(
            "assembly-instance:"
        )
        assert assigned["leaf"]["cde_container"]["container_id"] \
            == "GM.nodes.runtime"
        assert "brain.universal_work_transition" in assigned["block"]
        assert brain.get_meta(legacy.LEDGER_META_KEY) == source_before

        repeated = tool(
            runtime="codex",
            session_id="codex-session-1",
            owner_user="founder",
        )
        assert repeated["leaf"]["work_root"] \
            == assigned["leaf"]["work_root"]
        assert repeated["status"]["counts"]["claimed"] == 1

        other = tool(
            runtime="codex",
            session_id="codex-session-2",
            owner_user="founder",
        )
        assert other["ok"] is True
        assert other["leaf"] is None
        assert other["block"] == ""
        assert brain.get_meta(legacy.LEDGER_META_KEY) == source_before
    finally:
        application.close()
        brain.close()


def test_assigned_block_requires_a_universal_session_before_legacy_claim():
    brain = BrainStore.open(":memory:")
    legacy.add_leaves(
        brain,
        owner_user="founder",
        leaves=[{
            "title": "Legacy assignment must not be claimed",
            "gate_kind": "pytest",
            "gate_spec": {"path": "tests/court.py"},
            "priority": 100,
        }],
    )
    source_before = brain.get_meta(legacy.LEDGER_META_KEY)
    mcp = build_server(store=brain)
    tool = mcp._tools["brain.work_assigned_block"].handler
    try:
        denied = tool(runtime="codex", owner_user="founder")
        assert denied == {
            "ok": False,
            "owner_user": "founder",
            "blocked": True,
            "universal": True,
            "code": "universal_session_required",
            "error": (
                "A Universal Agent Session is required before work can be "
                "claimed."
            ),
            "block": "",
            "leaf": None,
        }
        assert brain.get_meta(legacy.LEDGER_META_KEY) == source_before
        assert legacy.status(brain, owner_user="founder")["counts"] == {
            "open": 1,
            "claimed": 0,
            "done": 0,
            "blocked": 0,
        }
    finally:
        brain.close()
