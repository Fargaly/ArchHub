"""Brain retains capabilities; the application graph retains authority."""
from pathlib import Path
import inspect
import sys

import pytest


WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_attestations import CourtResult  # noqa: E402
from nodelang.cell_secret_keys import MemorySigningKeyProvider  # noqa: E402
from personal_brain.universal_runtime import UniversalRuntimeBridge  # noqa: E402
from personal_brain.universal_runtime import UniversalRuntimeUnavailable  # noqa: E402
from personal_brain.universal_session_manager import (  # noqa: E402
    UniversalRuntimeSessionManager,
)
from personal_brain.server import (  # noqa: E402
    WiringAnnounceRequest,
    announce_session_wiring_cell_first,
    build_server,
)
from personal_brain.storage import BrainStore  # noqa: E402


def _green_runtime_compliance(_invocation):
    checks = {
        "runtime-detected": True,
        "required-hooks": True,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": True,
        "workshop-authority": True,
    }
    return CourtResult(True, checks, {"adapter": "session-manager-court"})


def test_manager_reuses_one_graph_session_and_never_owns_a_store(tmp_path):
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"s" * 32
    )
    descriptor = tmp_path / "runtime.json"
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    manager = UniversalRuntimeSessionManager(
        lambda: UniversalRuntimeBridge(descriptor, provider)
    )
    try:
        first = manager.enroll(
            runtime="claude-code", external_session_id="vendor-session-1"
        )
        second = manager.enroll(
            runtime="claude-code", external_session_id="vendor-session-1"
        )
        other = manager.enroll(
            runtime="claude-code", external_session_id="vendor-session-2"
        )
        assert first["reused"] is False
        assert second["reused"] is True
        assert second["agent_session"] == first["agent_session"]
        assert other["agent_session"] != first["agent_session"]

        work = manager.create(
            runtime="claude-code",
            external_session_id="vendor-session-1",
            title="Manager ownership court",
            description="Created through the enrolled graph session manager.",
            priority=100,
            external_key="test:manager-ownership-court",
        )
        claimed = manager.claim_next(
            runtime="claude-code",
            external_session_id="vendor-session-1",
        )
        assert claimed["work"]["root"] == work["created_root"]
        assert claimed["work"]["claimant_session"] \
            == first["agent_session"]
        assert manager.forget(
            runtime="claude-code", external_session_id="vendor-session-1"
        ) is True
        assert manager.forget(
            runtime="claude-code", external_session_id="vendor-session-1"
        ) is False
    finally:
        server.close()

    source = inspect.getsource(
        sys.modules["personal_brain.universal_session_manager"]
    )
    assert "CellStore" not in source
    assert "sqlite3" not in source


def test_unchanged_session_wiring_reuses_one_cell_identity(monkeypatch):
    class FakeBridge:
        def __init__(self):
            self.calls = []

        def deliberation_append(self, **kwargs):
            self.calls.append(kwargs)
            return {"root": "app:brain-control-ledger:v1:entry:wiring"}

    from personal_brain import universal_runtime as ur

    bridge = FakeBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    store = BrainStore.open(":memory:")
    request = WiringAnnounceRequest(
        device_id="codex-session-stable",
        entries=[],
        secret_refs=[],
        cwd=str(WORKSPACE),
        git_remote=None,
    )
    try:
        first = announce_session_wiring_cell_first(
            store=store, req=request, owner_user="founder"
        )
        second = announce_session_wiring_cell_first(
            store=store, req=request, owner_user="founder"
        )
    finally:
        store.close()

    assert first["ok"] is True
    assert second["ok"] is True
    assert len(bridge.calls) == 2
    assert bridge.calls[0]["space"] == "app:brain-control-ledger:v1"
    assert bridge.calls[0]["category"] \
        == "app:brain-control-ledger:v1:category:compliance-event"
    assert bridge.calls[0]["idempotency_key"] \
        == bridge.calls[1]["idempotency_key"]
    assert bridge.calls[0]["idempotency_key"].startswith(
        "brain-control:session-wiring:v2:"
    )
    assert bridge.calls[0]["payload"] == bridge.calls[1]["payload"]
    assert "recorded_at" not in bridge.calls[0]["payload"]


def test_manager_reused_enrollment_uses_compact_work_index():
    class FakeBridge:
        agent_session_root = "app:agent-session:fake"

        def __init__(self):
            self.index_calls = 0

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

        def work_index(self):
            self.index_calls += 1
            return {"revision": 2, "items": ()}

        def work_list(self):  # pragma: no cover - assertion path
            raise AssertionError("reused enrollment must not request full work list")

    bridges = []

    def factory():
        bridge = FakeBridge()
        bridges.append(bridge)
        return bridge

    manager = UniversalRuntimeSessionManager(factory)
    first = manager.enroll(
        runtime="claude-code", external_session_id="vendor-session-1"
    )
    second = manager.enroll(
        runtime="claude-code", external_session_id="vendor-session-1"
    )

    assert first["reused"] is False
    assert second["reused"] is True
    assert second["revision"] == 2
    assert bridges[0].index_calls == 1


@pytest.mark.parametrize(
    "failure",
    (
        "runtime Agent Session is unknown",
        "runtime Agent Session capability expired",
    ),
)
def test_manager_reenrolls_after_runtime_invalidates_session(failure):
    class FakeBridge:
        def __init__(self, index):
            self.index = index
            self.agent_session_root = (
                f"app:agent-session:runtime:bridge-{index}"
            )

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": self.index,
                "expires_at": "soon",
            }

        def work_index(self):
            if self.index == 1:
                raise UniversalRuntimeUnavailable(failure)
            return {"revision": self.index, "items": ()}

    bridges = []

    def factory():
        bridge = FakeBridge(len(bridges) + 1)
        bridges.append(bridge)
        return bridge

    manager = UniversalRuntimeSessionManager(factory)
    first = manager.enroll(
        runtime="codex", external_session_id="vendor-session-1"
    )
    second = manager.enroll(
        runtime="codex", external_session_id="vendor-session-1"
    )

    assert first["agent_session"].endswith("bridge-1")
    assert second["agent_session"].endswith("bridge-2")
    assert second["reused"] is False
    assert second["reconnected"] is True
    assert len(bridges) == 2


def test_manager_keeps_binding_on_transient_runtime_unavailability():
    class FakeBridge:
        agent_session_root = "app:agent-session:runtime:bridge-1"

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

        def work_index(self):
            raise UniversalRuntimeUnavailable(
                "universal runtime pipe is unavailable"
            )

    bridges = []

    def factory():
        bridge = FakeBridge()
        bridges.append(bridge)
        return bridge

    manager = UniversalRuntimeSessionManager(factory)
    manager.enroll(
        runtime="codex", external_session_id="vendor-session-1"
    )
    with pytest.raises(
        UniversalRuntimeUnavailable,
        match="pipe is unavailable",
    ):
        manager.enroll(
            runtime="codex", external_session_id="vendor-session-1"
        )

    assert len(bridges) == 1


def test_manager_work_status_falls_back_to_compact_index_when_full_is_too_large():
    class FakeBridge:
        agent_session_root = "app:agent-session:fake"

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

        def work_list(self):
            raise UniversalRuntimeUnavailable("machine response exceeds its size limit")

        def work_index(self):
            return {
                "revision": 3,
                "items": ({
                    "root": "work:one",
                    "interfaces": {
                        "external-key": {"value": "leaf:one"},
                    },
                },),
            }

        def value_read(self, root_id):  # pragma: no cover - compact index only
            raise AssertionError(root_id)

    manager = UniversalRuntimeSessionManager(lambda: FakeBridge())
    manager.enroll(
        runtime="claude-code", external_session_id="vendor-session-1"
    )

    status = manager.work_status(
        runtime="claude-code", external_session_id="vendor-session-1"
    )

    assert status["projection"] == "index"
    assert status["full_projection_unavailable"] is True
    assert "size limit" in status["full_projection_error"]
    assert status["items"] == [{
        "root": "work:one",
        "interfaces": {
            "external-key": {"value": "leaf:one"},
        },
        "resolved": {},
    }]


def test_manager_creates_compact_work_without_changing_ui_selection():
    class FakeBridge:
        agent_session_root = "app:agent-session:runtime:bridge-1"

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

        def work_create(self, **kwargs):
            self.create_kwargs = kwargs
            return {"created_root": "work:created", "revision": 2}

    bridge = FakeBridge()
    manager = UniversalRuntimeSessionManager(lambda: bridge)
    manager.enroll(runtime="codex-desktop", external_session_id="session-1")

    created = manager.create(
        runtime="codex-desktop",
        external_session_id="session-1",
        title="Bounded repair",
        external_key="repair:bounded",
        structured_references={"cde-container": {"tier": "T1"}},
    )

    assert created == {"created_root": "work:created", "revision": 2}
    assert bridge.create_kwargs["compact_references"] is True
    assert bridge.create_kwargs["select_created"] is False


def test_manager_claims_one_exact_work_without_global_queue_projection():
    class FakeBridge:
        agent_session_root = "app:agent-session:runtime:bridge-1"

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

        def _request(self, method, path, body):
            self.request = (method, path, body)
            return {
                "claimed": True,
                "work": {"root": body["root"]},
                "revision": 2,
            }

        def work_next(self):  # pragma: no cover - assertion path
            raise AssertionError("exact claim must not scan the global queue")

    bridge = FakeBridge()
    manager = UniversalRuntimeSessionManager(lambda: bridge)
    manager.enroll(runtime="codex-desktop", external_session_id="session-1")

    claimed = manager.claim_exact(
        runtime="codex-desktop",
        external_session_id="session-1",
        root_id="work:exact",
    )

    assert claimed["work"]["root"] == "work:exact"
    assert bridge.request == (
        "POST",
        "/api/universal/work-transition",
        {
            "root": "work:exact",
            "event": "claim",
            "evidence": "",
            "projection": "receipt-v1",
        },
    )


def test_manager_delegates_cde_permit_and_receipt_to_bound_runtime_client():
    class FakeClient:
        def issue_cde_write_permit(self, **kwargs):
            self.issued = kwargs
            return {"permit": "permit:1", **kwargs}

        def consume_cde_write_permit(self, **kwargs):
            self.consumed = kwargs
            return {"receipt": "receipt:1", **kwargs}

    class FakeBridge:
        agent_session_root = "app:agent-session:runtime:bridge-1"

        def __init__(self):
            self._client = FakeClient()

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

    bridge = FakeBridge()
    manager = UniversalRuntimeSessionManager(lambda: bridge)
    manager.enroll(runtime="codex", external_session_id="session-1")
    permit = manager.issue_cde_write_permit(
        runtime="codex",
        external_session_id="session-1",
        operation="apply_patch",
        path="00.GOVERNANCE/hooks/pretooluse_validate.py",
        content_digest="a" * 64,
        request_id="request-1",
        nonce="nonce-1",
    )
    receipt = manager.consume_cde_write_permit(
        runtime="codex",
        external_session_id="session-1",
        permit=permit["permit"],
        operation="apply_patch",
        path="00.GOVERNANCE/hooks/pretooluse_validate.py",
        content_digest="a" * 64,
        request_id="request-1",
    )

    assert permit["permit"] == "permit:1"
    assert receipt["receipt"] == "receipt:1"
    assert bridge._client.issued["nonce"] == "nonce-1"
    assert bridge._client.consumed["permit"] == "permit:1"


def test_brain_session_hook_and_work_tools_delegate_without_copying_state(monkeypatch):
    class FakeManager:
        def __init__(self):
            self.calls = []

        def enroll(self, **kwargs):
            self.calls.append(("enroll", kwargs))
            return {
                "agent_session": "app:agent-session:runtime:test",
                "reused": False,
            }

        def work_status(self, **kwargs):
            self.calls.append(("status", kwargs))
            return {"revision": 7, "items": []}

        def claim_next(self, **kwargs):
            self.calls.append(("next", kwargs))
            return {"revision": 8, "claimed": False, "work": None}

        def claim_exact(self, **kwargs):
            self.calls.append(("claim-exact", kwargs))
            return {
                "revision": 8,
                "claimed": True,
                "work": {"root": kwargs["root_id"]},
            }

        def issue_cde_write_permit(self, **kwargs):
            self.calls.append(("cde-permit", kwargs))
            return {"permit": "permit:test", "revision": 10}

        def consume_cde_write_permit(self, **kwargs):
            self.calls.append(("cde-receipt", kwargs))
            return {"receipt": "receipt:test", "revision": 11}

        def create(self, **kwargs):
            self.calls.append(("create", kwargs))
            return {"revision": 8, "root": "work:created"}

        def transition(self, **kwargs):
            self.calls.append(("transition", kwargs))
            return {"revision": 8, "history_root": "history:test"}

        def adjudicate(self, **kwargs):
            self.calls.append(("court", kwargs))
            return {"revision": 9, "passed": True, "event": "accept"}

    class FakeCellBridge:
        def __init__(self):
            self.created = []

        def deliberation_append(
            self,
            **kwargs,
        ):
            record = {
                "root": (
                    "app:brain-control-ledger:v1:entry:session-%s"
                    % (len(self.created) + 1)
                ),
                **kwargs,
            }
            self.created.append(record)
            return record

    from personal_brain import universal_runtime as ur

    manager = FakeManager()
    cell_bridge = FakeCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: cell_bridge)
    store = BrainStore.open(":memory:")
    mcp = build_server(store=store, runtime_session_manager=manager)
    try:
        started = mcp._tools["brain.hook_session_start"].handler(
            session_id="claude-session-7",
            cwd=str(WORKSPACE),
            vendor="claude-code",
        )
        assert started["cell_first"] is True
        assert started["brain_written"] is True
        assert started["cell_record_root"] \
            == "app:brain-control-ledger:v1:entry:session-1"
        assert started["universal_runtime_connected"] is True
        assert started["universal_agent_session"] \
            == "app:agent-session:runtime:test"
        status = mcp._tools["brain.universal_work_status"].handler(
            session_id="claude-session-7", vendor="claude-code"
        )
        assert status == {"revision": 7, "items": []}
        next_work = mcp._tools["brain.universal_work_next"].handler(
            session_id="claude-session-7", vendor="claude-code"
        )
        assert next_work["claimed"] is False
        exact = mcp._tools["brain.universal_work_claim"].handler(
            session_id="claude-session-7",
            vendor="claude-code",
            work_root="work:exact",
        )
        assert exact["work"]["root"] == "work:exact"
        permit = mcp._tools["brain.universal_cde_write_permit"].handler(
            session_id="claude-session-7",
            vendor="claude-code",
            operation="apply_patch",
            path="00.GOVERNANCE/hooks/pretooluse_validate.py",
            content_digest="a" * 64,
            request_id="request-7",
            nonce="nonce-7",
        )
        assert permit["permit"] == "permit:test"
        receipt = mcp._tools["brain.universal_cde_write_receipt"].handler(
            session_id="claude-session-7",
            vendor="claude-code",
            permit="permit:test",
            operation="apply_patch",
            path="00.GOVERNANCE/hooks/pretooluse_validate.py",
            content_digest="a" * 64,
            request_id="request-7",
        )
        assert receipt["receipt"] == "receipt:test"
        created = mcp._tools["brain.universal_work_create"].handler(
            session_id="claude-session-7",
            vendor="claude-code",
            title="Create only in the graph",
            external_key="test:create-only-in-graph",
            description="No Brain ledger write is permitted.",
            priority=7,
            references={"source": "test"},
            structured_references={"gate": {"kind": "manual"}},
        )
        assert created == {"revision": 8, "root": "work:created"}
        changed = mcp._tools["brain.universal_work_transition"].handler(
            session_id="claude-session-7",
            vendor="claude-code",
            work_root="work:test",
            event="claim",
            evidence="",
        )
        assert changed["history_root"] == "history:test"
        court = mcp._tools["brain.universal_work_court"].handler(
            session_id="claude-session-7",
            vendor="claude-code",
            work_root="work:test",
        )
        assert court["passed"] is True
        assert manager.calls == [
            (
                "enroll",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                },
            ),
            (
                "status",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                },
            ),
            (
                "next",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                },
            ),
            (
                "claim-exact",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                    "root_id": "work:exact",
                },
            ),
            (
                "cde-permit",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                    "operation": "apply_patch",
                    "path": "00.GOVERNANCE/hooks/pretooluse_validate.py",
                    "content_digest": "a" * 64,
                    "request_id": "request-7",
                    "nonce": "nonce-7",
                },
            ),
            (
                "cde-receipt",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                    "permit": "permit:test",
                    "operation": "apply_patch",
                    "path": "00.GOVERNANCE/hooks/pretooluse_validate.py",
                    "content_digest": "a" * 64,
                    "request_id": "request-7",
                },
            ),
            (
                "create",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                    "title": "Create only in the graph",
                    "description": "No Brain ledger write is permitted.",
                    "priority": 7,
                    "external_key": "test:create-only-in-graph",
                    "references": {"source": "test"},
                    "structured_references": {"gate": {"kind": "manual"}},
                },
            ),
            (
                "transition",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                    "root_id": "work:test",
                    "event": "claim",
                    "evidence": "",
                },
            ),
            (
                "court",
                {
                    "runtime": "claude-code",
                    "external_session_id": "claude-session-7",
                    "root_id": "work:test",
                },
            ),
        ]
    finally:
        store.close()


def test_brain_session_hook_cell_failure_does_not_enroll(monkeypatch):
    class FakeManager:
        def __init__(self):
            self.calls = []

        def enroll(self, **kwargs):
            self.calls.append(("enroll", kwargs))
            return {"agent_session": "should-not-exist", "reused": False}

    class FailingCellBridge:
        def deliberation_append(self, **_kwargs):
            raise RuntimeError("cell unavailable")

    from personal_brain import universal_runtime as ur

    manager = FakeManager()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: FailingCellBridge())
    store = BrainStore.open(":memory:")
    mcp = build_server(store=store, runtime_session_manager=manager)
    try:
        started = mcp._tools["brain.hook_session_start"].handler(
            session_id="claude-session-7",
            cwd=str(WORKSPACE),
            vendor="claude-code",
        )
        assert started["ok"] is False
        assert started["cell_first"] is True
        assert started["brain_written"] is False
        assert "cell unavailable" in started["error"]
        assert manager.calls == []
    finally:
        store.close()
