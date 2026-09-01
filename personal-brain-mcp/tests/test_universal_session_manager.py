"""Brain retains capabilities; the application graph retains authority."""
from pathlib import Path
import hashlib
import inspect
import sys
import threading
import time

import pytest


WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_attestations import CourtResult  # noqa: E402
from nodelang.cell_deliberation import read_deliberation_entry  # noqa: E402
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


def test_unchanged_session_wiring_reuses_one_cell_identity():
    class FakeManager:
        def __init__(self):
            self.calls = []

        def deliberation_append(self, **kwargs):
            self.calls.append(kwargs)
            return {"root": "app:brain-control-ledger:v1:entry:wiring"}

    manager = FakeManager()
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
            store=store,
            req=request,
            owner_user="founder",
            runtime_session_manager=manager,
            runtime="codex",
            external_session_id="codex-session-stable",
        )
        second = announce_session_wiring_cell_first(
            store=store,
            req=request,
            owner_user="founder",
            runtime_session_manager=manager,
            runtime="codex",
            external_session_id="codex-session-stable",
        )
    finally:
        store.close()

    assert first["ok"] is True
    assert second["ok"] is True
    assert len(manager.calls) == 2
    assert manager.calls[0]["space"] == "app:brain-control-ledger:v1"
    assert manager.calls[0]["category"] \
        == "app:brain-control-ledger:v1:category:compliance-event"
    assert manager.calls[0]["idempotency_key"] \
        == manager.calls[1]["idempotency_key"]
    assert manager.calls[0]["idempotency_key"].startswith(
        "brain-control:session-wiring:v3:"
    )
    assert manager.calls[0]["payload"] == manager.calls[1]["payload"]
    assert manager.calls[0]["payload"]["session_fingerprint"] == hashlib.sha256(
        b"codex-session-stable"
    ).hexdigest()
    assert "device_id" not in manager.calls[0]["payload"]
    assert "recorded_at" not in manager.calls[0]["payload"]


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


def test_manager_renews_held_capability_without_reprovisioning_graph_session():
    renewed = threading.Event()

    class FakeClient:
        def __init__(self, root):
            self.root = root
            self.calls = 0

        def renew_agent_session(self):
            self.calls += 1
            renewed.set()
            return {
                "agent_session": self.root,
                "session_token": "r" * 48,
                "expires_at": time.time() + 30.0,
                "revision": 11,
            }

    class FakeBridge:
        agent_session_root = "app:agent-session:runtime:renewed"

        def __init__(self):
            self.bind_calls = 0
            self._client = FakeClient(self.agent_session_root)

        def bind_agent_session(self, *, runtime, external_session_id):
            self.bind_calls += 1
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 11,
                "expires_at": time.time() + 0.08,
            }

        def work_index(self):
            return {"revision": 11, "items": ()}

    bridges = []

    def factory():
        bridge = FakeBridge()
        bridges.append(bridge)
        return bridge

    manager = UniversalRuntimeSessionManager(
        factory,
        renewal_lead_seconds=0.06,
        renewal_poll_seconds=0.005,
    )
    try:
        first = manager.enroll(
            runtime="codex", external_session_id="vendor-session-renew"
        )
        assert renewed.wait(0.5)
        second = manager.enroll(
            runtime="codex", external_session_id="vendor-session-renew"
        )
    finally:
        manager.close()

    assert first["agent_session"] == second["agent_session"]
    assert second["reused"] is True
    assert len(bridges) == 1
    assert bridges[0].bind_calls == 1
    assert bridges[0]._client.calls == 1
    assert manager.renewal_failures() == {}


@pytest.mark.parametrize(
    "failure",
    (
        "runtime Agent Session is unknown",
        "runtime Agent Session capability expired",
        "runtime Agent Session proof is invalid",
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


def test_manager_reconnects_after_real_expiry_and_writes_as_exact_session(
    tmp_path,
):
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"r" * 32
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
    external_session_id = "court-expired-session-reconnect"
    try:
        first = manager.enroll(
            runtime="codex", external_session_id=external_session_id
        )
        with server._machine_agent_session_lock:
            server._machine_agent_sessions[first["agent_session"]][
                "expires_at"
            ] = 0.0

        reconnected = manager.enroll(
            runtime="codex", external_session_id=external_session_id
        )

        assert reconnected["reconnected"] is True
        assert reconnected["agent_session"] == first["agent_session"]
        fingerprint = hashlib.sha256(
            external_session_id.encode("utf-8")
        ).hexdigest()
        receipt = manager.deliberation_append(
            runtime="codex",
            external_session_id=external_session_id,
            space=server.universal_registry.brain_control_ledger_root,
            category=server.universal_registry.brain_control_category_roots[
                "compliance-event"
            ],
            summary="Runtime Agent Session wiring",
            payload={
                "operation": "brain.hook_session_start",
                "session_fingerprint": fingerprint,
                "entry_count": 0,
                "entries": [],
                "secret_ref_count": 0,
                "secret_ref_hashes": [],
                "cwd_sha256": "a" * 64,
                "git_remote_sha256": "b" * 64,
            },
            idempotency_key="court:expired-session-wiring",
        )
        entry = read_deliberation_entry(
            server.universal_store.snapshot(),
            server.universal_registry.deliberation_protocol,
            receipt["root"],
        )
        assert entry.actor_root == first["agent_session"]
        with pytest.raises(
            UniversalRuntimeUnavailable,
            match="receipt is not admitted",
        ):
            manager.deliberation_append(
                runtime="codex",
                external_session_id=external_session_id,
                space=server.universal_registry.brain_control_ledger_root,
                category=server.universal_registry.brain_control_category_roots[
                    "compliance-event"
                ],
                summary="Runtime Agent Session wiring",
                payload={
                    "operation": "brain.hook_session_start",
                    "session_fingerprint": "0" * 64,
                    "entry_count": 0,
                    "entries": [],
                    "secret_ref_count": 0,
                    "secret_ref_hashes": [],
                    "cwd_sha256": "a" * 64,
                    "git_remote_sha256": "b" * 64,
                },
                idempotency_key="court:forged-session-wiring",
            )
    finally:
        server.close()


def test_manager_heartbeat_rotates_real_capability_without_graph_commit(
    tmp_path,
):
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"h" * 32
    )
    descriptor = tmp_path / "runtime.json"
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        machine_session_lifetime_seconds=5.0,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    manager = UniversalRuntimeSessionManager(
        lambda: UniversalRuntimeBridge(descriptor, provider),
        renewal_lead_seconds=4.8,
        renewal_poll_seconds=0.01,
    )
    try:
        first = manager.enroll(
            runtime="codex", external_session_id="court-heartbeat-session"
        )
        revision_after_enrollment = server.universal_store.revision
        with server._machine_agent_session_lock:
            first_token = server._machine_agent_sessions[
                first["agent_session"]
            ]["token"]

        deadline = time.monotonic() + 2.0
        renewed_token = first_token
        while renewed_token == first_token and time.monotonic() < deadline:
            time.sleep(0.01)
            with server._machine_agent_session_lock:
                renewed_token = server._machine_agent_sessions[
                    first["agent_session"]
                ]["token"]

        assert renewed_token != first_token
        assert server.universal_store.revision == revision_after_enrollment
        second = manager.enroll(
            runtime="codex", external_session_id="court-heartbeat-session"
        )
        assert second["reused"] is True
        assert second["agent_session"] == first["agent_session"]
        assert server.universal_store.revision == revision_after_enrollment
        with server._machine_agent_session_lock:
            assert tuple(server._machine_agent_sessions) == (
                first["agent_session"],
            )
    finally:
        manager.close()
        server.close()


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


def test_manager_work_status_uses_compact_index_without_full_projection():
    class FakeBridge:
        agent_session_root = "app:agent-session:fake"

        def bind_agent_session(self, *, runtime, external_session_id):
            return {
                "agent_session": self.agent_session_root,
                "runtime": runtime,
                "revision": 1,
                "expires_at": "soon",
            }

        def work_list(self):  # pragma: no cover - assertion path
            raise AssertionError("agent status must not request the full Work graph")

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
    assert "full_projection_unavailable" not in status
    assert "full_projection_error" not in status
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

        def deliberation_append(self, **kwargs):
            self.calls.append(("deliberation-append", kwargs))
            return {
                "root": "app:brain-control-ledger:v1:entry:session-1"
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

    manager = FakeManager()
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
        assert manager.calls[0] == (
            "enroll",
            {
                "runtime": "claude-code",
                "external_session_id": "claude-session-7",
            },
        )
        receipt_call = manager.calls[1]
        assert receipt_call[0] == "deliberation-append"
        assert receipt_call[1]["runtime"] == "claude-code"
        assert receipt_call[1]["external_session_id"] == "claude-session-7"
        assert receipt_call[1]["space"] == "app:brain-control-ledger:v1"
        assert receipt_call[1]["category"] \
            == "app:brain-control-ledger:v1:category:compliance-event"
        assert receipt_call[1]["summary"] == "Runtime Agent Session wiring"
        assert receipt_call[1]["payload"]["session_fingerprint"] \
            == hashlib.sha256(b"claude-session-7").hexdigest()
        assert "device_id" not in receipt_call[1]["payload"]
        assert receipt_call[1]["idempotency_key"].startswith(
            "brain-control:session-wiring:v3:"
        )
        assert manager.calls[2:] == [
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


def test_brain_session_hook_enrolls_before_receipt_and_keeps_brain_unwritten():
    class FakeManager:
        def __init__(self):
            self.calls = []

        def enroll(self, **kwargs):
            self.calls.append(("enroll", kwargs))
            return {
                "agent_session": "app:agent-session:runtime:test",
                "reused": False,
            }

        def deliberation_append(self, **kwargs):
            self.calls.append(("deliberation-append", kwargs))
            raise RuntimeError("cell unavailable")

    manager = FakeManager()
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
        assert [call[0] for call in manager.calls] == [
            "enroll", "deliberation-append"
        ]
        assert manager.calls[1][1]["payload"]["session_fingerprint"] \
            == hashlib.sha256(b"claude-session-7").hexdigest()
        assert started["universal_runtime_connected"] is True
        assert started["universal_agent_session"] \
            == "app:agent-session:runtime:test"
    finally:
        store.close()
