"""Brain reaches work through the application owner, never the Cell database."""
from pathlib import Path
import inspect
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_secret_keys import MemorySigningKeyProvider  # noqa: E402
from personal_brain.universal_runtime import (  # noqa: E402
    UniversalRuntimeBridge,
    UniversalRuntimeUnavailable,
)
from personal_brain.storage import BrainStore  # noqa: E402


def _roma_tree_payload(state="open", claimed_by=None):
    return {
        "tree_id": "rt-bridge",
        "root_id": "root",
        "owner_user": "founder",
        "title": "Brain bridge ROMA route",
        "created_at": "2026-07-20T00:00:00+00:00",
        "updated_at": "2026-07-20T00:00:00+00:00",
        "nodes": {
            "root": {
                "node_id": "root",
                "parent": None,
                "title": "Brain bridge ROMA route",
                "children": ["leaf"],
                "state": "open",
                "gate_kind": "manual",
                "gate_spec": {},
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:00:00+00:00",
            },
            "leaf": {
                "node_id": "leaf",
                "parent": "root",
                "title": "Sync through the application owner",
                "predicate": "Brain syncs ROMA to the same Cell route",
                "children": [],
                "state": state,
                "claimed_by": claimed_by,
                "past_claimants": [claimed_by] if claimed_by else [],
                "gate_kind": "pytest",
                "gate_spec": {
                    "path": "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
                    "selector": "test_brain_bridge_uses_the_signed_runtime_and_same_work_registry",
                },
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:01:00+00:00",
            },
        },
    }


def test_brain_bridge_uses_the_signed_runtime_and_same_work_registry(tmp_path):
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"r" * 32
    )
    descriptor = tmp_path / "active-runtime.json"
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
    ).start()
    bridge = UniversalRuntimeBridge(descriptor, provider)
    try:
        before = bridge.work_list()
        assert before["application"] \
            == server.universal_registry.application_root
        assert before["registry"] \
            == server.universal_registry.governed_work_registry_root
        assert before["items"] == []
        before_index = bridge.work_index()
        assert before_index["registry"] \
            == server.universal_registry.governed_work_registry_root
        assert before_index["items"] == []
        workshop = bridge.workshop_read()
        assert workshop["workshop"] == server.universal_registry.workshop_root
        assert workshop["entries"] == []
        control_ledger = server.universal_registry.brain_control_ledger_root
        control_category = (
            server.universal_registry.brain_control_category_roots[
                "compliance-event"
            ]
        )
        control = bridge.deliberation_append(
            space=control_ledger,
            category=control_category,
            summary="Brain bridge control-ledger court.",
            payload={"owner_user": "founder", "court": "bridge"},
            idempotency_key="brain-bridge-control-ledger",
            created_at="2026-07-21T12:00:00+00:00",
        )
        assert control["space"] == control_ledger
        control_history = bridge.deliberation_read(
            space=control_ledger, limit=10
        )
        assert control_history["entries"][0]["root"] == control["root"]
        assert control_history["entries"][0]["payload"] == {
            "owner_user": "founder", "court": "bridge"
        }
        denied = bridge.workshop_gate(
            ref=server.universal_registry.application_root,
            phase="claim",
        )
        assert denied["allowed"] is False
        said = bridge.workshop_say(
            category="plan",
            text="Use the application-owned Workshop.",
            refs=[server.universal_registry.application_root],
            idempotency_key="brain-bridge-workshop-plan",
            created_at="2026-07-18T10:30:00+00:00",
        )
        assert said["workshop"] == server.universal_registry.workshop_root
        assert said["kind"] == "plan"
        assert bridge.workshop_gate(
            ref=server.universal_registry.application_root,
            phase="claim",
        )["allowed"] is True
        assert bridge.workshop_say(
            category="plan",
            text="Use the application-owned Workshop.",
            refs=[server.universal_registry.application_root],
            idempotency_key="brain-bridge-workshop-plan",
            created_at="2026-07-18T10:30:00+00:00",
        )["root"] == said["root"]

        created = bridge.work_create(
            title="Migrate the Brain ledger",
            description="Brain is a client of the one graph owner",
            priority=100,
            external_key="legacy:leaf:brain",
            references={"scope": server.universal_registry.map.domains["brain"]},
            structured_references={
                "requirements": {
                    "gate": {"kind": "pytest", "spec": {"path": "tests"}}
                }
            },
            x=600,
            y=400,
        )
        after = bridge.work_list()
        assert len(after["items"]) == 1
        assert after["items"][0]["root"] == created["created_root"]
        assert after["items"][0]["membership_wire"] \
            == created["membership_wire"]
        indexed = bridge.work_index()
        assert indexed["total"] == 1
        assert indexed["items"][0]["root"] == created["created_root"]
        assert indexed["items"][0]["interfaces"]["external-key"]["value"] \
            == "legacy:leaf:brain"
        requirements_root = after["items"][0]["interfaces"][
            "requirements"
        ]["target"]
        assert bridge.value_read(requirements_root) == {
            "gate": {"kind": "pytest", "spec": {"path": "tests"}}
        }
        grand_preview = bridge.grand_map_work_preview(limit=3)
        assert grand_preview["ok"] is True
        assert grand_preview["grand_map"] \
            == server.universal_registry.map.grand_map_root
        assert grand_preview["missing_count"] > 3
        grand_sync = bridge.grand_map_work_sync(limit=2)
        assert grand_sync["ok"] is True
        assert grand_sync["created_count"] == 2
        roma_sync = bridge.roma_tree_sync(
            _roma_tree_payload(), source="brain.roma_atomize"
        )
        assert roma_sync["ok"] is True
        assert roma_sync["tree_root"] == "app:roma-tree:rt-bridge"
        assert roma_sync["node_count"] == 2
        roma_projection = bridge.roma_tree_get(tree_id="rt-bridge")
        assert roma_projection["ok"] is True
        leaf_root = "app:roma-tree:rt-bridge:node:leaf"
        assert roma_projection["nodes"][leaf_root]["state"] == "open"
        roma_index = bridge.roma_tree_list()
        assert roma_index["ok"] is True
        assert roma_index["tree_ids"] == ["rt-bridge"]
        assert roma_index["tree_count"] == 1
        bridge.roma_tree_sync(
            _roma_tree_payload(state="claimed", claimed_by="brain-agent"),
            source="brain.roma_claim",
        )
        claimed_tree = bridge.roma_tree_get(tree_id="rt-bridge")
        assert claimed_tree["nodes"][leaf_root]["state"] == "claimed"
        assert claimed_tree["nodes"][leaf_root]["claimed_by"] == "brain-agent"
        grand_index = bridge.work_index()
        grand_keys = {
            item["interfaces"]["external-key"]["value"]
            for item in grand_index["items"]
        }
        assert {"legacy:leaf:brain"} < grand_keys
        assert {
            item["external_key"] for item in grand_preview["items"][:2]
        } <= grand_keys
        enrolled = bridge.bind_agent_session(
            runtime="brainwrap:codex",
            external_session_id="codex-bridge-session",
        )
        assert bridge.agent_session_root == enrolled["agent_session"]
        claimed = bridge.work_transition(
            root_id=created["created_root"], event="claim"
        )
        assert claimed["status"]["counts"]["claimed"] == 1
        assert claimed["status"]["items"][0]["claimant_session"] \
            == bridge.agent_session_root
        released = bridge.work_transition(
            root_id=created["created_root"], event="release"
        )
        assert released["status"]["counts"]["open"] == 1 + grand_sync[
            "created_count"
        ]
    finally:
        server.close()

    source = inspect.getsource(sys.modules["personal_brain.universal_runtime"])
    assert "CellStore" not in source
    assert "sqlite3" not in source
    assert "active_work_v1" not in source


def test_brain_roma_mcp_handler_syncs_to_application_route(tmp_path, monkeypatch):
    from personal_brain import requirement_tree as rt
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"t" * 32
    )
    descriptor = tmp_path / "roma-mcp-runtime.json"
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
    ).start()
    brain_store = BrainStore.open(":memory:")
    monkeypatch.setattr(
        ur,
        "UniversalRuntimeBridge",
        lambda: UniversalRuntimeBridge(descriptor, provider),
    )
    try:
        mcp = build_server(store=brain_store, default_owner_user="founder")
        out = mcp._tools["brain.roma_atomize"].handler(
            vision="Cell route is the ROMA authority",
            decomposition=[{
                "title": "Sync requirement tree to application route",
                "gate_kind": "manual",
            }],
        )
        assert out["ok"] is True
        assert out["cell_tree_first"] is True
        assert out["cell_tree_root"] == f"app:roma-tree:{out['tree_id']}"
        projected = UniversalRuntimeBridge(
            descriptor, provider
        ).roma_tree_get(tree_id=out["tree_id"])
        assert projected["ok"] is True
        assert projected["tree_root"] == out["cell_tree_root"]
        assert projected["node_count"] == 2
        tree_get = mcp._tools["brain.tree_get"].handler(tree_id=out["tree_id"])
        assert tree_get["ok"] is True
        assert tree_get["authority_source"] == "cell_route"
        assert tree_get["tree"]["title"] == "Cell route is the ROMA authority"
        sweep = mcp._tools["brain.roma_sweep"].handler(tree_id=out["tree_id"])
        assert sweep["ok"] is True
        assert sweep["authority_source"] == "cell_route"
        listed = mcp._tools["brain.roma_list"].handler()
        assert listed["ok"] is True
        assert listed["authority_source"] == "cell_route"
        assert out["tree_id"] in listed["trees"]
        assert out["brain_written"] is False
        assert brain_store.get_meta(rt.TREE_META_KEY) is None
    finally:
        brain_store.close()
        server.close()


def test_brain_bridge_fails_closed_without_runtime_descriptor(tmp_path):
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"u" * 32
    )
    bridge = UniversalRuntimeBridge(tmp_path / "missing-runtime.json", provider)

    with pytest.raises(UniversalRuntimeUnavailable):
        bridge.work_list()


def test_brain_bridge_passes_timeout_to_prompt_and_status_projections():
    class _FakeClient:
        def __init__(self):
            self.calls = []

        def request(self, method, path, body=None, **kwargs):
            self.calls.append((method, path, body, kwargs))
            return {"workshop": "app:workshop", "entries": [], "allowed": False}

    client = _FakeClient()
    bridge = UniversalRuntimeBridge.__new__(UniversalRuntimeBridge)
    bridge._transport_error = RuntimeError
    bridge._client = client

    assert bridge.work_list(response_timeout_seconds=5.0)["workshop"] == "app:workshop"
    assert bridge.work_index(response_timeout_seconds=4.0)["workshop"] == "app:workshop"
    assert bridge.workshop_read(response_timeout_seconds=3.0)["entries"] == []
    assert bridge.deliberation_read(
        space="app:brain-control",
        limit=5,
        response_timeout_seconds=2.5,
    )["entries"] == []
    assert bridge.deliberation_append(
        space="app:brain-control",
        category="app:brain-control:compliance-event",
        summary="Timeout-bound deliberation write.",
        payload={"ok": True},
        idempotency_key="timeout-deliberation-write",
        response_timeout_seconds=2.25,
    )["workshop"] == "app:workshop"
    assert bridge.workshop_gate(
        ref="leaf:1",
        phase="claim",
        response_timeout_seconds=2.0,
    )["allowed"] is False
    assert bridge.workshop_say(
        category="plan",
        text="Bounded write.",
        idempotency_key="timeout-write",
        response_timeout_seconds=1.5,
    )["workshop"] == "app:workshop"
    assert bridge.browser_handoff_status(
        response_timeout_seconds=1.0
    )["workshop"] == "app:workshop"
    assert bridge.grand_map_work_preview(
        limit=7,
        include_live=True,
        response_timeout_seconds=0.9,
    )["workshop"] == "app:workshop"
    assert bridge.grand_map_work_sync(
        limit=3,
        response_timeout_seconds=0.8,
    )["workshop"] == "app:workshop"
    assert bridge.roma_tree_get(
        tree_id="rt-bridge",
        response_timeout_seconds=0.7,
    )["workshop"] == "app:workshop"
    assert bridge.roma_tree_sync(
        _roma_tree_payload(),
        source="brain.roma_atomize",
        response_timeout_seconds=0.6,
    )["workshop"] == "app:workshop"

    assert client.calls == [
        (
            "GET",
            "/api/universal/work",
            None,
            {"response_timeout_seconds": 5.0},
        ),
        (
            "GET",
            "/api/universal/work",
            {"projection": "index"},
            {"response_timeout_seconds": 4.0},
        ),
        (
            "GET",
            "/api/universal/workshop",
            None,
            {"response_timeout_seconds": 3.0},
        ),
        (
            "GET",
            "/api/universal/deliberation",
            {"space": "app:brain-control", "limit": 5},
            {"response_timeout_seconds": 2.5},
        ),
        (
            "POST",
            "/api/universal/deliberation",
            {
                "space": "app:brain-control",
                "category": "app:brain-control:compliance-event",
                "summary": "Timeout-bound deliberation write.",
                "payload": {"ok": True},
                "idempotency_key": "timeout-deliberation-write",
                "created_at": None,
            },
            {"response_timeout_seconds": 2.25},
        ),
        (
            "POST",
            "/api/universal/workshop-gate",
            {"ref": "leaf:1", "phase": "claim"},
            {"response_timeout_seconds": 2.0},
        ),
        (
            "POST",
            "/api/universal/workshop",
            {
                "category": "plan",
                "text": "Bounded write.",
                "refs": [],
                "evidence": [],
                "recipients": [],
                "reply_to": None,
                "idempotency_key": "timeout-write",
                "created_at": None,
            },
            {"response_timeout_seconds": 1.5},
        ),
        (
            "GET",
            "/api/universal/browser-handoff",
            None,
            {"response_timeout_seconds": 1.0},
        ),
        (
            "GET",
            "/api/universal/grand-map-work",
            {"limit": 7, "include_live": True},
            {"response_timeout_seconds": 0.9},
        ),
        (
            "POST",
            "/api/universal/grand-map-work",
            {"limit": 3, "include_live": False},
            {"response_timeout_seconds": 0.8},
        ),
        (
            "GET",
            "/api/universal/roma-tree",
            {"tree_id": "rt-bridge"},
            {"response_timeout_seconds": 0.7},
        ),
        (
            "POST",
            "/api/universal/roma-tree",
            {
                "tree": _roma_tree_payload(),
                "source": "brain.roma_atomize",
            },
            {"response_timeout_seconds": 0.6},
        ),
    ]
