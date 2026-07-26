"""Windows court for the single-owner Universal Cell machine transport."""
import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

import nodelang.application_server as application_server_module
import nodelang.universal_application as universal_application_module
from nodelang.application_machine_transport import (
    BABOOM_NATIVE_FRAME_PROJECTION,
    MachineTransportError,
    UniversalRuntimeClient,
    UniversalRuntimeTransport,
    inspect_runtime_descriptor,
    inspect_stopped_runtime_durable_journal,
    inspect_stopped_runtime_offline_activity,
    inspect_stopped_runtime_trusted_checkpoint,
    runtime_device_proof_payload,
    session_proof_payload,
    validate_baboom_native_frame_payload,
)
from nodelang.application_server import ApplicationServer
from nodelang.cell_agent_body import read_agent_session
from nodelang.cell_baboom_meeting_note_publication import (
    find_baboom_meeting_note_publication,
)
from nodelang.cell_attestations import CourtResult
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_cloud_sessions import device_root_for_thumbprint
from nodelang.cell_compliance import list_compliance_observations
from nodelang.cell_deliberation import read_deliberation_space
from nodelang.cell_device_custody import register_device_custody, revoke_device_custody
from nodelang.cell_device_keys import DeviceProofKeyReference, PLATFORM_PROVIDER
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_protocols import read_relation
from nodelang.cell_roma_requirements import roma_node_root, roma_tree_root
from nodelang.cell_value_graph import read_value_graph
from nodelang.cell_work_claim_transfer import read_work_claim_transfer
from nodelang.cell_work_handoff import read_work_handoff
from nodelang.model_execution_broker import ModelExecutionResult
from nodelang.universal_application import (
    bind_universal_runtime_agent_body_device_custody,
    create_universal_governed_work,
)
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID


def _green_runtime_compliance(_invocation):
    checks = {
        "runtime-detected": True,
        "required-hooks": True,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": True,
        "workshop-authority": True,
    }
    return CourtResult(True, checks, {"adapter": "test-runtime-auditor"})


def _red_runtime_compliance(_invocation):
    checks = {
        "runtime-detected": True,
        "required-hooks": False,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": False,
        "workshop-authority": True,
    }
    return CourtResult(False, checks, {"adapter": "test-runtime-auditor"})


class _RecordedModelBroker:
    """A physical-boundary double; it never launches a provider process."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def execute(self, *, provider, location, model, data_class, task):
        self.calls.append({
            "provider": provider,
            "location": location,
            "model": model,
            "data_class": data_class,
            "task": task,
        })
        output = (
            b'{"summary":"Review the bounded Workshop evidence.",'
            b'"next_actions":["Request review before an effect."],'
            b'"risks":["Unapproved action is denied."],"uncertainty":0.2}'
        )
        return ModelExecutionResult(
            "succeeded",
            hashlib.sha256(output).hexdigest(),
            len(output),
            "",
            {
                "summary": "Review the bounded Workshop evidence.",
                "next_actions": ["Request review before an effect."],
                "risks": ["Unapproved action is denied."],
                "uncertainty": 0.2,
            },
        )

    def model_provider_readiness(self):
        return {
            provider: {
                "location": location,
                "state": "test-ready",
                "evidence": "test host observation",
                "execution_authority": "requires graph request, approval, and one-use grant",
            }
            for provider, location in (
                ("gpt", "local-cli:codex"),
                ("claude", "local-cli:claude"),
                ("gemini", "local-cli:gemini"),
                ("openrouter", "network:openrouter"),
                ("local", "local-http:ollama"),
            )
        }


def test_machine_work_claim_fails_closed_on_red_runtime_compliance(tmp_path):
    descriptor_path = tmp_path / "red-runtime-compliance.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"q" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        runtime_compliance_runner=_red_runtime_compliance,
    ).start()
    founder = UniversalRuntimeClient(descriptor_path, provider)
    agent = UniversalRuntimeClient(descriptor_path, provider)
    try:
        created = founder.request("POST", "/api/universal/work", {
            "title": "Runtime compliance must precede assignment",
            "priority": 100,
            "x": 320,
            "y": 240,
        })
        agent.bind_agent_session(
            runtime="codex", external_session_id="red-compliance-court"
        )
        with pytest.raises(MachineTransportError, match="compliance"):
            agent.claim_work(created["created_root"])
        projected = founder.request("GET", "/api/universal/work")
        assert projected["items"][0]["operational"][
            "current_state_label"
        ] == "OPEN"
        observations = list_compliance_observations(
            server.universal_store.snapshot(),
            server.universal_registry.compliance_protocol,
        )
        assert len(observations) == 1
        assert observations[0].result_root == (
            server.universal_registry.compliance_protocol.states[
                "unsatisfied"
            ]
        )
    finally:
        server.close()


def test_generic_deliberation_route_writes_an_openable_cell_payload(tmp_path):
    descriptor_path = tmp_path / "brain-control-ledger.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"l" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        ledger = server.universal_registry.brain_control_ledger_root
        category = server.universal_registry.brain_control_category_roots[
            "compliance-event"
        ]
        payload = {
            "event_id": "court:brain-control:1",
            "owner": "founder",
            "result": {"green": True, "checks": ["one", "two"]},
        }
        created = client.request("POST", "/api/universal/deliberation", {
            "space": ledger,
            "category": category,
            "summary": "Compliance court completed.",
            "payload": payload,
            "idempotency_key": "court:brain-control:1",
            "created_at": "2026-07-21T12:00:00+00:00",
        })
        assert created["space"] == ledger
        assert created["category_root"] == category
        assert read_value_graph(
            server.universal_store.snapshot(),
            server.universal_registry.value_graph_protocol,
            created["payload_root"],
        ) == payload

        listed = client.request("GET", "/api/universal/deliberation", {
            "space": ledger,
            "limit": 10,
        })
        assert listed["entries"] == [{
            "root": created["root"],
            "actor": server.universal_registry.authorization.subject_root,
            "category_root": category,
            "summary": "Compliance court completed.",
            "reference_roots": [created["payload_root"]],
            "payload": payload,
            "created_at": "2026-07-21T12:00:00+00:00",
            "sequence": 1,
            "idempotency_key": "court:brain-control:1",
        }]
    finally:
        server.close()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _runtime_device_key():
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    public_jwk = {
        "crv": "P-256",
        "kty": "EC",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }
    document = json.dumps(
        public_jwk, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    thumbprint = _b64url(hashlib.sha256(document).digest())
    return key, DeviceProofKeyReference(
        "court-runtime-device",
        PLATFORM_PROVIDER,
        "ES256",
        thumbprint,
        public_jwk,
        True,
    )


def _register_runtime_device(server, reference):
    device_root = device_root_for_thumbprint(reference.thumbprint)
    server.universal_store.commit(
        server.universal_store.revision,
        create=(Cell(
            device_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            ("device-proof-key-thumbprint:" + reference.thumbprint).encode("ascii"),
        ),),
    )
    custody_root, _ = register_device_custody(
        server.universal_store,
        server.universal_registry.device_custody_protocol,
        reference,
    )
    return custody_root


def _bind_runtime_device(server, reference, *, runtime="baboom"):
    custody_root = _register_runtime_device(server, reference)
    bind_universal_runtime_agent_body_device_custody(
        server.universal_store,
        server.universal_registry,
        runtime=runtime,
        custody_root=custody_root,
    )
    return custody_root


def _device_credential(key, custody_root, challenge, external_session_id):
    payload = runtime_device_proof_payload(
        runtime_id=challenge["runtime_id"],
        runtime=challenge["runtime"],
        external_session_id=external_session_id,
        challenge_id=challenge["challenge_id"],
        nonce=challenge["nonce"],
    )
    der = key.sign(
        hashlib.sha256(payload).digest(),
        ec.ECDSA(utils.Prehashed(hashes.SHA256())),
    )
    left, right = utils.decode_dss_signature(der)
    return {
        "challenge_id": challenge["challenge_id"],
        "custody_root": custody_root,
        "signature": _b64url(
            left.to_bytes(32, "big") + right.to_bytes(32, "big")
        ),
    }


def test_runtime_descriptor_inspection_reports_a_stale_signed_owner(
    tmp_path,
    monkeypatch,
):
    descriptor_path = tmp_path / "runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"d" * 32
    )
    transport = UniversalRuntimeTransport(
        lambda _request: {},
        application_root="app:archhub",
        agent_session_root="app:agent-session:founder",
        workshop_root="app:workshop",
        work_registry_root="app:governed-work-registry",
        descriptor_path=descriptor_path,
        key_provider=provider,
    ).start()
    try:
        monkeypatch.setattr(
            "nodelang.application_machine_transport._windows_process_is_active",
            lambda _pid: False,
        )
        assert inspect_runtime_descriptor(descriptor_path, provider) == {
            "verified": True,
            "active": True,
            "owner_alive": False,
            "application": "app:archhub",
        }
        assert inspect_stopped_runtime_trusted_checkpoint(
            descriptor_path, provider
        ) == {
            "available": False,
            "reason": "signed runtime owner is not stopped",
        }
    finally:
        transport.close()


def test_stopped_runtime_durable_probe_hides_database_and_never_starts_an_owner(
    tmp_path,
):
    descriptor_path = tmp_path / "stopped-runtime.json"
    database_path = tmp_path / "stopped-runtime.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"e" * 32
    )
    store = CellStore(database_path)
    store.commit(store.revision, create=[
        Cell("durable-probe", NULL_CELL_ID, NULL_CELL_ID, b"current"),
    ])
    transport = UniversalRuntimeTransport(
        lambda _request: {},
        application_root="app:archhub",
        agent_session_root="app:agent-session:founder",
        workshop_root="app:workshop",
        work_registry_root="app:governed-work-registry",
        database=str(database_path),
        descriptor_path=descriptor_path,
        key_provider=provider,
    ).start()
    try:
        assert inspect_stopped_runtime_durable_journal(
            descriptor_path, provider
        ) == {
            "available": False,
            "reason": "signed runtime owner is not stopped",
        }
    finally:
        transport.close()
    try:
        observed = inspect_stopped_runtime_durable_journal(
            descriptor_path, provider
        )
        assert observed == {
            "available": True,
            "revision": 1,
            "revision_count": 2,
            "latest_revision_change_count": 1,
        }
        assert "database" not in observed
        store.commit(store.revision, replace=[
            Cell("durable-probe", NULL_CELL_ID, NULL_CELL_ID, b"still-owned"),
        ])
    finally:
        store.close()


def test_stopped_runtime_offline_activity_projects_indexed_blockers_without_another_owner(
    tmp_path,
    monkeypatch,
):
    """A stopped journal can add blockers while its original owner stays open."""
    descriptor_path = tmp_path / "offline-activity-runtime.json"
    database_path = tmp_path / "offline-activity.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"a" * 32
    )
    store = CellStore(database_path)

    def create(*cells):
        store.commit(store.revision, create=cells)

    def cell(cell_id, link0=NULL_CELL_ID, link1=NULL_CELL_ID, atom=b""):
        return Cell(cell_id, link0, link1, atom)

    try:
        # The synthetic graph is deliberately minimal, but uses the same
        # protocol roots and current-Cell index as a stopped Universal owner.
        create(*(cell(item) for item in (
            "app:agent-body-protocol:role:session-member",
            "app:agent-body-protocol:role:session-state",
            "app:agent-body-protocol:state:active",
            "gm:role:member",
            "app:assembly-protocol:role:capability",
            "app:assembly-protocol:role:rule",
            "app:standard-library:state-machine-protocol:root",
            "app:standard-library:state-machine-protocol:role:current-state",
            "app:exclusive-ownership-protocol:role:ownership-member",
            "app:exclusive-ownership-protocol:role:resource",
            "app:exclusive-ownership-protocol:role:state",
            "app:exclusive-ownership-protocol:role:generation",
            "app:exclusive-ownership-protocol:state:released",
            "app:archhub",
        )))
        create(cell("work:one:state", atom=b"OPEN"), cell("owner:generation", atom=b"1"))
        create(cell("session:state", "app:agent-body-protocol:role:session-state", "app:agent-body-protocol:state:active"))
        create(cell("app:agent-session:runtime:one", "session:state"))
        create(cell("sessions:member", "app:agent-body-protocol:role:session-member", "app:agent-session:runtime:one"))
        create(cell("app:agent-body-protocol:registry:session", "sessions:member"))
        create(cell("work:state-member", "app:standard-library:state-machine-protocol:role:current-state", "work:one:state"))
        create(cell("work:machine", "work:state-member"))
        create(cell("work:rule-member", "app:assembly-protocol:role:rule", "work:machine"))
        create(cell("work:rule-carrier", "work:rule-member"))
        create(cell("work:capability-member", "app:assembly-protocol:role:capability", "app:standard-library:state-machine-protocol:root"))
        create(cell("work:one", "work:capability-member", "work:rule-carrier"))
        create(cell("work:registry-member", "gm:role:member", "work:one"))
        create(cell("app:governed-work-registry", "work:registry-member"))
        create(cell("owner:generation-member", "app:exclusive-ownership-protocol:role:generation", "owner:generation"))
        create(cell("owner:generation-carrier", "owner:generation-member"))
        create(cell("owner:state-member", "app:exclusive-ownership-protocol:role:state", "app:exclusive-ownership-protocol:state:released"))
        create(cell("owner:state-carrier", "owner:state-member", "owner:generation-carrier"))
        create(cell("owner:resource-member", "app:exclusive-ownership-protocol:role:resource", "app:archhub"))
        create(cell("owner:one", "owner:resource-member", "owner:state-carrier"))
        create(cell("ownership:registry-member", "app:exclusive-ownership-protocol:role:ownership-member", "owner:one"))
        create(cell("app:exclusive-ownership-protocol:root", "ownership:registry-member"))
        create(cell("app:runtime-presence-protocol:root"))

        transport = UniversalRuntimeTransport(
            lambda _request: {},
            application_root="app:archhub",
            agent_session_root="app:agent-session:founder",
            workshop_root="app:workshop",
            work_registry_root="app:governed-work-registry",
            database=str(database_path),
            descriptor_path=descriptor_path,
            key_provider=provider,
        ).start()
        transport.close()
        monkeypatch.setattr(
            "nodelang.application_machine_transport.inspect_stopped_runtime_trusted_checkpoint",
            lambda *_args: {
                "available": True,
                "revision": store.revision,
                "authorizes_handoff": False,
            },
        )

        projected = inspect_stopped_runtime_offline_activity(
            descriptor_path, provider, max_seconds=3.0
        )

        assert projected == {
            "available": True,
            "revision": store.revision,
            "runtime_owner": {"state": "released", "generation": 1},
            "activity": {
                "active_runtime_sessions": 1,
                "active_runtime_presence_leases": 0,
                "work": {
                    "total": 1,
                    "open": 1,
                    "claimed": 0,
                    "blocked": 0,
                    "review": 0,
                    "complete": 0,
                    "cancelled": 0,
                },
            },
            "authorizes_handoff": False,
        }
        # The projection's SQLite mode=ro/query_only path cannot replace or
        # release the existing durable owner.
        store.commit(store.revision, create=[cell("owner-remains-open")])
    finally:
        store.close()


def test_machine_descriptor_points_to_cell_authority_not_a_transport_model(tmp_path):
    descriptor_path = tmp_path / "cell-authority-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"c" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        assert set(descriptor) == {
            "format", "format_version", "runtime_id", "status", "pipe",
            "process_id", "started_at", "stopped_at", "application_root",
            "agent_session_root", "workshop_root", "work_registry_root",
            "database", "key_id", "key_version", "signature",
        }
        assert not {
            "kind", "type", "params", "ports", "routes", "permissions",
            "work_items", "workshop_entries", "children", "token", "secret",
        }.intersection(descriptor)

        safe_inspection = inspect_runtime_descriptor(descriptor_path, provider)
        assert set(safe_inspection) == {
            "verified", "active", "owner_alive", "application",
        }
        assert safe_inspection["application"] \
            == server.universal_registry.application_root

        snapshot = server.universal_store.snapshot()
        descriptor_roots = {
            "application_root": server.universal_registry.application_root,
            "agent_session_root": (
                server.universal_registry.agent_body.session.root_id
            ),
            "workshop_root": server.universal_registry.workshop_root,
            "work_registry_root": (
                server.universal_registry.governed_work_registry_root
            ),
        }
        for field, root in descriptor_roots.items():
            assert descriptor[field] == root
            assert root in snapshot.cells
            assert read_relation(snapshot, root, budget=100_000)

        session = read_agent_session(
            snapshot,
            server.universal_registry.agent_body.protocol,
            server.universal_registry.authorization.protocol,
            descriptor["agent_session_root"],
        )
        assert session.body_root \
            == server.universal_registry.agent_body.body.root_id
        assert session.subject_root == (
            server.universal_registry.authorization.subject_root
        )
        assert session.state_root \
            == server.universal_registry.agent_body.protocol.state("active")

        tampered = dict(descriptor)
        tampered["agent_session_root"] = "app:agent-session:forged"
        descriptor_path.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(MachineTransportError, match="signature"):
            UniversalRuntimeClient(descriptor_path, provider).request(
                "GET", "/api/universal/work"
            )
    finally:
        server.close()


def test_slow_client_request_does_not_kill_listener_or_block_shutdown(tmp_path):
    descriptor_path = tmp_path / "slow-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"s" * 32
    )

    def dispatch(request):
        if request["path"] == "/slow":
            time.sleep(10.5)
        return {"path": request["path"]}

    transport = UniversalRuntimeTransport(
        dispatch,
        application_root="court:application",
        agent_session_root="court:agent-session",
        workshop_root="court:workshop",
        work_registry_root="court:work-registry",
        descriptor_path=descriptor_path,
        key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        assert client.request("GET", "/slow") == {"path": "/slow"}
        assert client.request("GET", "/after-slow") == {
            "path": "/after-slow"
        }
    finally:
        started = time.monotonic()
        transport.close()
        assert time.monotonic() - started < 7.0


def test_client_can_bound_a_projection_wait_without_weakening_runtime_authority(tmp_path):
    descriptor_path = tmp_path / "bounded-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"t" * 32
    )

    def dispatch(request):
        if request["path"] == "/slow-observation":
            time.sleep(0.4)
        return {"path": request["path"]}

    transport = UniversalRuntimeTransport(
        dispatch,
        application_root="court:application",
        agent_session_root="court:agent-session",
        workshop_root="court:workshop",
        work_registry_root="court:work-registry",
        descriptor_path=descriptor_path,
        key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        started = time.monotonic()
        with pytest.raises(MachineTransportError, match="did not respond"):
            client.request(
                "GET",
                "/slow-observation",
                response_timeout_seconds=0.05,
            )
        assert time.monotonic() - started < 0.25
        time.sleep(0.45)
        assert client.request("GET", "/after-bounded-observation") == {
            "path": "/after-bounded-observation"
        }
    finally:
        transport.close()


def test_slow_request_does_not_block_later_clients(tmp_path):
    descriptor_path = tmp_path / "concurrent-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"c" * 32
    )
    slow_started = threading.Event()

    def dispatch(request):
        if request["path"] == "/slow":
            slow_started.set()
            time.sleep(2.0)
        return {"path": request["path"]}

    transport = UniversalRuntimeTransport(
        dispatch,
        application_root="court:application",
        agent_session_root="court:agent-session",
        workshop_root="court:workshop",
        work_registry_root="court:work-registry",
        descriptor_path=descriptor_path,
        key_provider=provider,
    ).start()
    slow_result = {}

    def run_slow():
        slow_result["value"] = UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/slow")

    worker = threading.Thread(target=run_slow, daemon=True)
    try:
        worker.start()
        assert slow_started.wait(timeout=2)
        started = time.monotonic()
        assert UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/after-slow") == {"path": "/after-slow"}
        assert time.monotonic() - started < 1.5
        worker.join(timeout=5)
        assert slow_result["value"] == {"path": "/slow"}
    finally:
        transport.close()


def test_slow_work_index_read_does_not_block_later_machine_requests(
    tmp_path,
    monkeypatch,
):
    descriptor_path = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"q" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    slow_started = threading.Event()
    original_index = application_server_module.project_universal_governed_work_index

    def slow_index(*args, **kwargs):
        slow_started.set()
        time.sleep(2.0)
        return original_index(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module,
        "project_universal_governed_work_index",
        slow_index,
    )
    slow_result = {}

    def run_slow_read():
        slow_result["value"] = UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/api/universal/work", {"projection": "index"})

    worker = threading.Thread(target=run_slow_read, daemon=True)
    try:
        worker.start()
        assert slow_started.wait(timeout=2)
        started = time.monotonic()
        handoff = UniversalRuntimeClient(
            descriptor_path, provider
        ).browser_handoff()
        assert handoff["one_use"] is True
        assert time.monotonic() - started < 1.5
        worker.join(timeout=5)
        assert slow_result["value"]["registry"] == (
            server.universal_registry.governed_work_registry_root
        )
    finally:
        server.close()


def test_browser_handoff_status_does_not_wait_for_mutation_lock(tmp_path):
    descriptor_path = tmp_path / "handoff-status-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"h" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    result = {}
    error = {}

    def read_status():
        try:
            result["value"] = UniversalRuntimeClient(
                descriptor_path, provider
            ).browser_handoff_status()
        except Exception as exc:
            error["value"] = exc

    worker = threading.Thread(target=read_status, daemon=True)
    try:
        with server.mutation_lock:
            started = time.monotonic()
            worker.start()
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert time.monotonic() - started < 1.5
        assert "value" not in error
        assert result["value"]["supported"] is True
        assert result["value"]["server_url"] == server.url
    finally:
        worker.join(timeout=5)
        server.close()


def test_grand_map_work_machine_route_creates_cell_native_work(tmp_path):
    descriptor_path = tmp_path / "grand-map-work-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"m" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        preview = client.request(
            "GET", "/api/universal/grand-map-work", {"limit": 4}
        )
        assert preview["ok"] is True
        assert preview["grand_map"] == server.universal_registry.map.grand_map_root
        assert preview["work_registry"] == (
            server.universal_registry.governed_work_registry_root
        )
        assert preview["missing_count"] > 4
        assert len(preview["items"]) == 4

        synced = client.request(
            "POST", "/api/universal/grand-map-work", {"limit": 2}
        )
        assert synced["ok"] is True
        assert synced["created_count"] == 2
        index = client.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        assert index["total"] == 2
        assert {
            item["interfaces"]["external-key"]["value"]
            for item in index["items"]
        } == {item["external_key"] for item in preview["items"][:2]}

        after = client.request(
            "GET", "/api/universal/grand-map-work", {"limit": 4}
        )
        assert after["existing_count"] == 2
        assert after["missing_count"] == preview["missing_count"] - 2
        with pytest.raises(MachineTransportError, match="shape"):
            client.request(
                "GET",
                "/api/universal/grand-map-work",
                {"limit": 2, "path": "forbidden.json"},
            )
    finally:
        server.close()


def _roma_transport_tree(state="open", claimed_by=None):
    return {
        "tree_id": "rt-transport",
        "root_id": "root",
        "owner_user": "founder",
        "title": "Signed transport ROMA route",
        "created_at": "2026-07-20T00:00:00+00:00",
        "updated_at": "2026-07-20T00:00:00+00:00",
        "nodes": {
            "root": {
                "node_id": "root",
                "parent": None,
                "title": "Signed transport ROMA route",
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
                "title": "Sync through machine transport",
                "predicate": "agent route writes the same Cell graph",
                "children": [],
                "state": state,
                "claimed_by": claimed_by,
                "past_claimants": [claimed_by] if claimed_by else [],
                "gate_kind": "pytest",
                "gate_spec": {
                    "path": "tests_replica/test_application_machine_transport.py",
                    "selector": "test_roma_tree_machine_route_syncs_and_projects_cell_graph",
                },
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:01:00+00:00",
            },
        },
    }


def test_roma_tree_machine_route_syncs_and_projects_cell_graph(tmp_path):
    descriptor_path = tmp_path / "roma-tree-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"o" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        synced = client.request(
            "POST",
            "/api/universal/roma-tree",
            {"tree": _roma_transport_tree(), "source": "brain.roma_atomize"},
        )
        assert synced["ok"] is True
        assert synced["tree_root"] == roma_tree_root("rt-transport")
        assert synced["node_count"] == 2
        assert synced["edge_count"] == 1

        index = client.request("GET", "/api/universal/roma-tree", {})
        assert index["ok"] is True
        assert index["tree_ids"] == ["rt-transport"]
        assert index["tree_count"] == 1
        assert index["trees"][0]["tree_root"] == roma_tree_root("rt-transport")

        projected = client.request(
            "GET", "/api/universal/roma-tree", {"tree_id": "rt-transport"}
        )
        leaf_root = roma_node_root("rt-transport", "leaf")
        assert projected["ok"] is True
        assert projected["tree_root"] == roma_tree_root("rt-transport")
        assert projected["nodes"][leaf_root]["state"] == "open"
        assert projected["frontier"][0]["root"] == leaf_root
        assert projected["nodes"][leaf_root]["gate_spec"]["selector"] == (
            "test_roma_tree_machine_route_syncs_and_projects_cell_graph"
        )

        client.request(
            "POST",
            "/api/universal/roma-tree",
            {
                "tree": _roma_transport_tree(
                    state="claimed", claimed_by="agent-a"
                ),
                "source": "brain.roma_claim",
            },
        )
        claimed = client.request(
            "GET", "/api/universal/roma-tree", {"tree_id": "rt-transport"}
        )
        assert claimed["nodes"][leaf_root]["state"] == "claimed"
        assert claimed["nodes"][leaf_root]["claimed_by"] == "agent-a"

        with pytest.raises(MachineTransportError, match="shape"):
            client.request(
                "GET",
                "/api/universal/roma-tree",
                {"tree_id": "rt-transport", "path": "forbidden.json"},
            )
    finally:
        server.close()


def test_universal_http_route_authorization_is_cached_per_revision(
    tmp_path, monkeypatch
):
    descriptor_path = tmp_path / "route-cache-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"r" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    original_find = application_server_module.find_cloud_route
    calls = {"count": 0}

    def counted_find(*args, **kwargs):
        calls["count"] += 1
        return original_find(*args, **kwargs)

    monkeypatch.setattr(application_server_module, "find_cloud_route", counted_find)
    try:
        context = server.universal_registry.authorization.session.context()
        first = server.require_universal_http_route(
            "GET",
            "/api/universal/browser-handoff",
            authentication_context=context,
        )
        second = server.require_universal_http_route(
            "GET",
            "/api/universal/browser-handoff",
            authentication_context=context,
        )
        assert first == second
        assert calls["count"] == 1

        server.universal_store.commit(server.universal_store.revision, create=(
            Cell("test:route-cache-bump", NULL_CELL_ID, NULL_CELL_ID, b""),
        ))
        server.require_universal_http_route(
            "GET",
            "/api/universal/browser-handoff",
            authentication_context=context,
        )
        assert calls["count"] == 2
    finally:
        server.close()


def test_baboom_context_does_not_wait_for_mutation_lock(tmp_path):
    descriptor_path = tmp_path / "baboom-context-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"b" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    result = {}
    error = {}

    def read_context():
        try:
            result["value"] = UniversalRuntimeClient(
                descriptor_path, provider
            ).request("GET", "/api/universal/baboom-context")
        except Exception as exc:
            error["value"] = exc

    worker = threading.Thread(target=read_context, daemon=True)
    try:
        with server.mutation_lock:
            started = time.monotonic()
            worker.start()
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert time.monotonic() - started < 1.5
        assert "value" not in error
        assert result["value"]["cell_native"] is True
        assert result["value"]["context_lens"] == "app:baboom-context:v3"
    finally:
        worker.join(timeout=5)
        server.close()


def test_runtime_handoff_readiness_is_revision_bound_and_content_free(tmp_path):
    descriptor_path = tmp_path / "runtime-handoff-readiness.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"h" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        revision = server.universal_store.revision
        idle = client.request("GET", "/api/universal/runtime-handoff-readiness")
        assert server.universal_store.revision == revision
        assert idle == {
            "cell_native": True,
            "projection": "app:runtime-handoff-readiness:v1",
            "revision": revision,
            "runtime_owner": {"state": "active", "generation": 1},
            "activity": {
                "active_runtime_owners": 1,
                "active_runtime_sessions": 0,
                "active_runtime_presence_leases": 0,
                "pending_or_active_work": 0,
                "work": {
                    "total": 0,
                    "open": 0,
                    "claimed": 0,
                    "blocked": 0,
                    "review": 0,
                },
            },
            "founder_review": {
                "required": True,
                "graph_clear": False,
                "blockers": ["one canonical runtime owner is active"],
            },
        }

        client.request("POST", "/api/universal/work", {
            "title": "Sensitive handoff detail must not leave the graph",
            "description": "A detailed Work body must remain private.",
            "priority": 20,
            "external_key": "runtime-handoff-readiness-content-free",
            "references": {"scope": server.universal_registry.map.domains["brain"]},
            "x": 520,
            "y": 340,
        })
        active = client.request("GET", "/api/universal/runtime-handoff-readiness")
        assert active["revision"] == server.universal_store.revision
        assert active["activity"] == {
            "active_runtime_owners": 1,
            "active_runtime_sessions": 0,
            "active_runtime_presence_leases": 0,
            "pending_or_active_work": 1,
            "work": {
                "total": 1,
                "open": 1,
                "claimed": 0,
                "blocked": 0,
                "review": 0,
            },
        }
        assert active["founder_review"] == {
            "required": True,
            "graph_clear": False,
            "blockers": [
                "one canonical runtime owner is active",
                "1 pending or active governed Work item(s)",
            ],
        }
        serialized = json.dumps(active, sort_keys=True)
        assert "Sensitive handoff detail" not in serialized
        assert "detailed Work body" not in serialized
        assert "app:agent-session" not in serialized
    finally:
        server.close()


def test_baboom_presence_route_is_a_graph_directive_without_work_content(tmp_path):
    descriptor_path = tmp_path / "baboom-presence-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"p" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        idle = client.request("GET", "/api/universal/baboom-presence")
        created = client.request("POST", "/api/universal/work", {
            "title": "Sensitive companion work title",
            "description": "This detailed Work body must remain outside presence.",
            "priority": 20,
            "external_key": "baboom-presence-content-free",
            "references": {"scope": server.universal_registry.map.domains["brain"]},
            "x": 520,
            "y": 340,
        })
        directive = client.request("GET", "/api/universal/baboom-presence")

        assert created["created_root"].startswith("assembly-instance:")
        assert set(directive) == {
            "projection", "revision", "fingerprint", "persona_form", "motion",
            "message", "context", "compact_message", "ttl_seconds", "action",
            "action_label",
        }
        assert directive["projection"] == "app:baboom-companion-directive:v1"
        assert directive["revision"] == server.universal_store.revision
        assert directive["fingerprint"] != idle["fingerprint"]
        assert directive["action"] == "claim-next-governed-work"
        assert directive["motion"] == "working"
        assert directive["message"] == "1 Work item is ready to claim."
        assert idle["message"] == "No governed Work needs attention."
        assert idle["compact_message"] == ""
        text = json.dumps(directive, sort_keys=True)
        assert "Sensitive companion work title" not in text
        assert "detailed Work body" not in text
    finally:
        server.close()


def test_baboom_native_frame_keeps_host_context_and_directive_on_one_revision(tmp_path):
    descriptor_path = tmp_path / "baboom-native-frame-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"f" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        quiet = client.baboom_native_frame()
        created = client.request("POST", "/api/universal/work", {
            "title": "Private native frame Work title",
            "description": "Private native frame Work detail must not render.",
            "priority": 20,
            "external_key": "baboom-native-frame-content-free",
            "references": {"scope": server.universal_registry.map.domains["brain"]},
            "x": 520,
            "y": 340,
        })
        frame = client.baboom_native_frame()

        assert created["created_root"].startswith("assembly-instance:")
        assert quiet["projection"] == BABOOM_NATIVE_FRAME_PROJECTION
        assert quiet["directive"]["message"] == "No governed Work needs attention."
        assert quiet["directive"]["compact_message"] == ""
        assert quiet["report"] is None
        assert frame["projection"] == BABOOM_NATIVE_FRAME_PROJECTION
        assert frame["revision"] == server.universal_store.revision
        assert frame["issued_at"] < frame["expires_at"]
        assert frame["context"]["revision"] == frame["revision"]
        assert frame["directive"]["revision"] == frame["revision"]
        assert frame["directive"]["motion"] == "working"
        assert frame["report"]["kind"] == "steward-briefing"
        assert frame["report"]["revision"] == frame["revision"]
        assert frame["report"]["data"]["revision"] == frame["revision"]
        assert frame["report"]["data"]["governed_work"]["items"][0] == {
            "state": "open",
            "title": "Private native frame Work title",
            "priority": 20,
            "model_state": "",
        }
        text = json.dumps(frame, sort_keys=True)
        assert "Private native frame Work title" in text
        assert "Private native frame Work detail" not in text
        assert created["created_root"] not in text

        expired = json.loads(json.dumps(frame))
        expired["issued_at"] = time.time() - 24.0
        expired["expires_at"] = time.time() - 12.0
        with pytest.raises(MachineTransportError, match="lease"):
            validate_baboom_native_frame_payload(expired)

        drifted = json.loads(json.dumps(frame))
        drifted["report"]["data"]["attention"]["revision"] += 1
        with pytest.raises(MachineTransportError, match="revision drifted"):
            validate_baboom_native_frame_payload(drifted)

        codex = UniversalRuntimeClient(descriptor_path, provider)
        codex.bind_agent_session(
            runtime="codex",
            external_session_id="native-frame-non-baboom-denial",
        )
        with pytest.raises(MachineTransportError, match="founder or BABOOM"):
            codex.baboom_native_frame()
    finally:
        server.close()


def test_machine_transport_executes_only_one_idempotent_founder_baboom_task(tmp_path):
    descriptor_path = tmp_path / "baboom-command-execute-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"q" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        created = client.execute_baboom_command(
            utterance="Assign task: prepare the bounded Workshop review"
        )
        replayed = client.execute_baboom_command(
            utterance="Assign task: prepare the bounded Workshop review"
        )

        assert created["intent"] == "assign-task"
        assert created["state"] == "open"
        assert created["created"] is True
        assert replayed["created"] is False
        assert replayed["work"] == created["work"]
        assert replayed["external_key"] == created["external_key"]
    finally:
        server.close()


def test_baboom_capability_route_projects_only_released_graph_adapters(tmp_path):
    descriptor_path = tmp_path / "baboom-capabilities-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"k" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        model_execution_broker=_RecordedModelBroker(),
    ).start()
    try:
        report = UniversalRuntimeClient(descriptor_path, provider).request(
            "GET", "/api/universal/baboom-capabilities"
        )

        assert report["projection"] == "founder-local-baboom-capability-report"
        assert report["revision"] == server.universal_store.revision
        assert {
            entry["root"] for entry in report["models"]
        } == set(server.universal_registry.baboom_model_provider_roots.values())
        assert {
            entry["operation"] for entry in report["connectors"]
        } == {
            "archhub.department.run_once",
            "notion.append_blocks",
            "teams.list_meetings",
            "teams.open_meeting",
        }
        assert "GET /api/universal/baboom-capabilities" in report["routes"]
        assert "POST /api/universal/model-delegation-execute" in report["routes"]
        assert report["routes"] == sorted(set(report["routes"]))
        assert set(report["physical_model_readiness"]) == {
            "gpt", "claude", "gemini", "openrouter", "local",
        }
        assert all(
            entry["state"] == "test-ready"
            and entry["released_provider_root"]
            == server.universal_registry.baboom_model_provider_roots[provider]
            for provider, entry in report["physical_model_readiness"].items()
        )
        assert "transient host observation" in report["physical_readiness_authority"]
    finally:
        server.close()


def test_mcp_broker_routes_bind_one_tool_to_the_existing_connector_lifecycle(
    tmp_path,
):
    descriptor_path = tmp_path / "mcp-broker-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"m" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    execution_external_id = "mcp-broker-runtime-execution"

    def device_credential(challenge):
        return _device_credential(
            key, custody_root, challenge, execution_external_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="mcp-broker-runtime-founder",
        )
        enrollment = founder.request("POST", "/api/universal/mcp-server-register", {
            "transport": "stdio",
            "config_digest": hashlib.sha256(b"local-mcp-config").hexdigest(),
            "data_classes": ["internal-text"],
        })
        assert enrollment["transport"] == "stdio"
        assert enrollment["data_classes"] == ["internal-text"]

        created = founder.request("POST", "/api/universal/work", {
            "title": "Prepare one MCP-bound coordination review",
            "description": "The runtime court must not retain raw tool input.",
            "priority": 75,
            "external_key": "mcp-broker-runtime-route-court",
            "references": {
                "scope": server.universal_registry.map.domains["connectors"],
            },
            "x": 880,
            "y": 560,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=execution_external_id,
            device_credential_provider=device_credential,
        )
        claim = execution.claim_next_work()
        assert claim["work"]["root"] == created["created_root"]

        negotiated = execution.request(
            "POST", "/api/universal/mcp-server-negotiate", {
                "root": created["created_root"],
                "server": enrollment["server"],
                "protocol_version": "2025-06-18",
                "capabilities_digest": hashlib.sha256(b"tools").hexdigest(),
                "manifest_digest": hashlib.sha256(b"private-manifest").hexdigest(),
                "tools": [{
                    "name_digest": hashlib.sha256(b"private-tool").hexdigest(),
                    "schema_digest": hashlib.sha256(b'{"type":"object"}').hexdigest(),
                    "data_class": "internal-text",
                }],
            },
        )
        assert negotiated["work"] == created["created_root"]
        assert len(negotiated["tools"]) == 1
        raw_input = b'{"private":"argument"}'
        delegated = execution.request(
            "POST", "/api/universal/mcp-tool-delegation", {
                "root": created["created_root"],
                "tool": negotiated["tools"][0],
                "input_digest": hashlib.sha256(raw_input).hexdigest(),
                "input_bytes": len(raw_input),
            },
        )
        assert delegated["negotiation"] == negotiated["negotiation"]
        assert raw_input.decode("ascii") not in repr(
            server.universal_store.snapshot().cells
        )

        founder.request("POST", "/api/universal/connector-delegation-approve", {
            "delegation": delegated["delegation"],
        })
        grant = execution.request(
            "POST", "/api/universal/connector-delegation-grant", {
                "delegation": delegated["delegation"],
            },
        )
        settled = execution.request(
            "POST", "/api/universal/connector-delegation-receipt", {
                "grant": grant["grant"],
                "capability": grant["capability"],
                "outcome": "failed",
                "output_digest": hashlib.sha256(b"").hexdigest(),
                "output_bytes": 0,
                "error_code": "local.transport-unavailable",
            },
        )
        assert settled["history_root"] == ""
        broker = founder.request("GET", "/api/universal/mcp-broker")
        assert broker["registered_servers"] == 1
        assert broker["active_negotiations"] == 1
        assert broker["active_tools"] == 1
    finally:
        server.close()


def test_baboom_context_uses_compact_work_index_not_full_status(
    tmp_path,
    monkeypatch,
):
    descriptor_path = tmp_path / "baboom-context-index-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"x" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()

    def fail_full_status(*args, **kwargs):
        raise AssertionError("BABOOM context must not build full work status")

    monkeypatch.setattr(
        universal_application_module,
        "project_universal_governed_work_status",
        fail_full_status,
    )
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        created = client.request("POST", "/api/universal/work", {
            "title": "Compact index only",
            "description": "BABOOM must receive counts, not full work bodies",
            "priority": 20,
            "external_key": "active-work:compact-index-only",
            "references": {"scope": server.universal_registry.map.domains["brain"]},
            "x": 520,
            "y": 340,
        })
        assert created["created_root"].startswith("assembly-instance:")
        context = client.request("GET", "/api/universal/baboom-context")
        assert context["cell_native"] is True
        assert context["context_lens"] == "app:baboom-context:v3"
        assert context["work"] == {
            "total": 1,
            "open": 1,
            "claimed": 0,
            "blocked": 0,
            "review": 0,
        }
        text = json.dumps(context, sort_keys=True)
        assert "Compact index only" not in text
        assert created["created_root"] not in text
    finally:
        server.close()


def test_workshop_read_does_not_wait_for_mutation_lock(tmp_path):
    descriptor_path = tmp_path / "workshop-read-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"s" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    result = {}
    error = {}

    def read_workshop():
        try:
            result["value"] = UniversalRuntimeClient(
                descriptor_path, provider
            ).request("GET", "/api/universal/workshop")
        except Exception as exc:
            error["value"] = exc

    worker = threading.Thread(target=read_workshop, daemon=True)
    try:
        with server.mutation_lock:
            started = time.monotonic()
            worker.start()
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert time.monotonic() - started < 1.5
        assert "value" not in error
        assert result["value"]["workshop"] == server.universal_registry.workshop_root
    finally:
        worker.join(timeout=5)
        server.close()


def test_canvas_read_does_not_wait_for_mutation_lock(tmp_path):
    descriptor_path = tmp_path / "canvas-read-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"v" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    result = {}
    error = {}

    def read_canvas():
        try:
            result["value"] = UniversalRuntimeClient(
                descriptor_path, provider
            ).request("GET", "/api/universal/canvas")
        except Exception as exc:
            error["value"] = exc

    worker = threading.Thread(target=read_canvas, daemon=True)
    try:
        with server.mutation_lock:
            started = time.monotonic()
            worker.start()
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert time.monotonic() - started < 1.5
        assert "value" not in error
        assert result["value"]["ok"] is True
        assert result["value"]["canvas_root"] == server.universal_registry.canvas_root
        assert result["value"]["inspector"]["lens"] == "machine-summary"
        assert isinstance(result["value"]["nodes"], list)
        assert isinstance(result["value"]["wires"], list)
    finally:
        worker.join(timeout=5)
        server.close()


def test_machine_canvas_read_uses_bounded_summary_not_full_browser_projection(
    tmp_path, monkeypatch
):
    descriptor_path = tmp_path / "bounded-canvas-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"y" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()

    def forbidden_projection(*_args, **_kwargs):
        raise AssertionError(
            "full browser canvas projection must not serve machine route"
        )

    monkeypatch.setattr(
        application_server_module,
        "project_universal_canvas",
        forbidden_projection,
    )
    try:
        result = UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/api/universal/canvas")
        assert result["ok"] is True
        assert result["inspector"]["lens"] == "machine-summary"
    finally:
        server.close()


def test_machine_canvas_read_does_not_expand_browser_interfaces(
    tmp_path, monkeypatch
):
    descriptor_path = tmp_path / "fast-canvas-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"f" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()

    def forbidden_browser_expansion(*_args, **_kwargs):
        raise AssertionError(
            "machine canvas must not expand browser interfaces"
        )

    monkeypatch.setattr(
        universal_application_module,
        "_instance_projection",
        forbidden_browser_expansion,
    )
    monkeypatch.setattr(
        universal_application_module,
        "_canvas_endpoint",
        forbidden_browser_expansion,
    )
    try:
        result = UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/api/universal/canvas")
        assert result["ok"] is True
        assert result["inspector"]["lens"] == "machine-summary"
        assert result["machine_projection"]["kind"] == "bounded-canvas-summary"
        node_ids = {node["id"] for node in result["nodes"]}
        for wire in result["wires"]:
            assert wire["source"] in node_ids
            assert wire["target"] in node_ids
            assert wire["source_interface"]
            assert wire["target_interface"]
    finally:
        server.close()


def test_machine_canvas_read_does_not_scan_global_canvas_or_full_catalog(
    tmp_path, monkeypatch
):
    descriptor_path = tmp_path / "bounded-canvas-scan-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"g" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()

    def forbidden_full_scan(*_args, **_kwargs):
        raise AssertionError(
            "machine canvas must use bounded session roots, not full scans"
        )

    monkeypatch.setattr(
        universal_application_module,
        "_canvas_roots",
        forbidden_full_scan,
    )
    monkeypatch.setattr(
        universal_application_module,
        "_validate_node_library_sections",
        forbidden_full_scan,
    )
    try:
        result = UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/api/universal/canvas")
        assert result["ok"] is True
        assert result["inspector"]["lens"] == "machine-summary"
        assert result["machine_projection"]["kind"] == "bounded-canvas-summary"
        assert len(result["catalog"]) <= 64
    finally:
        server.close()


def test_machine_canvas_read_is_cached_per_cell_revision(tmp_path, monkeypatch):
    descriptor_path = tmp_path / "cached-canvas-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"z" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    original_canvas = application_server_module.project_universal_machine_canvas
    calls = {"count": 0}

    def counted_canvas(*args, **kwargs):
        calls["count"] += 1
        return original_canvas(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module,
        "project_universal_machine_canvas",
        counted_canvas,
    )
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        first = client.request("GET", "/api/universal/canvas")
        second = client.request("GET", "/api/universal/canvas")
        assert first["revision"] == second["revision"]
        assert calls["count"] == 1

        server.universal_store.commit(server.universal_store.revision, create=(
            Cell("test:canvas-cache-bump", NULL_CELL_ID, NULL_CELL_ID, b""),
        ))
        third = client.request("GET", "/api/universal/canvas")
        assert third["revision"] == server.universal_store.revision
        assert calls["count"] == 2
    finally:
        server.close()


def test_machine_workshop_read_is_cached_per_cell_revision(tmp_path, monkeypatch):
    descriptor_path = tmp_path / "cached-workshop-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"c" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    original_list = application_server_module.list_deliberation_entries
    calls = {"count": 0}

    def counted_list(*args, **kwargs):
        calls["count"] += 1
        return original_list(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module,
        "list_deliberation_entries",
        counted_list,
    )
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        first = client.request("GET", "/api/universal/workshop")
        second = client.request("GET", "/api/universal/workshop")
        assert first["revision"] == second["revision"]
        assert calls["count"] == 1

        server.universal_store.commit(server.universal_store.revision, create=(
            Cell("test:workshop-cache-bump", NULL_CELL_ID, NULL_CELL_ID, b""),
        ))
        third = client.request("GET", "/api/universal/workshop")
        assert third["revision"] != first["revision"]
        assert calls["count"] == 2
    finally:
        server.close()


def test_machine_work_index_is_cached_per_cell_revision(tmp_path, monkeypatch):
    descriptor_path = tmp_path / "cached-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"w" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    original_index = application_server_module.project_universal_governed_work_index
    calls = {"count": 0}

    def counted_index(*args, **kwargs):
        calls["count"] += 1
        return original_index(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module,
        "project_universal_governed_work_index",
        counted_index,
    )
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        first = client.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        second = client.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        assert first["revision"] == second["revision"]
        assert calls["count"] == 1

        server.universal_store.commit(server.universal_store.revision, create=(
            Cell("test:work-index-cache-bump", NULL_CELL_ID, NULL_CELL_ID, b""),
        ))
        third = client.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        assert third["revision"] == server.universal_store.revision
        assert calls["count"] == 2
    finally:
        server.close()


def test_machine_projection_prewarm_primes_read_caches(tmp_path, monkeypatch):
    descriptor_path = tmp_path / "prewarm-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"p" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    original_index = application_server_module.project_universal_governed_work_index
    calls = {"count": 0}

    def counted_index(*args, **kwargs):
        calls["count"] += 1
        return original_index(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module,
        "project_universal_governed_work_index",
        counted_index,
    )
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        status = server.prewarm_universal_machine_read_projections()

        assert status["ok"] is True
        assert status["status"] == "warm"
        assert status["baboom_lens"] == "app:baboom-context:v3"
        assert status["work_total"] == 0
        assert status["canvas_roots"] > 0
        assert calls["count"] == 1

        work = client.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        canvas = client.request("GET", "/api/universal/canvas")
        context = client.request("GET", "/api/universal/baboom-context")

        assert work["revision"] == status["revision"]
        assert canvas["revision"] == status["revision"]
        assert context["revision"] == status["revision"]
        assert context["context_lens"] == "app:baboom-context:v3"
        assert calls["count"] == 1
        assert server.universal_machine_projection_prewarm_status()["ok"] is True
    finally:
        server.close()


def test_concurrent_machine_work_index_requests_share_inflight_projection(
    tmp_path,
    monkeypatch,
):
    descriptor_path = tmp_path / "inflight-index-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"i" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    original_index = application_server_module.project_universal_governed_work_index
    entered = threading.Event()
    release = threading.Event()
    calls = {"count": 0}
    calls_lock = threading.Lock()

    def slow_index(*args, **kwargs):
        with calls_lock:
            calls["count"] += 1
        entered.set()
        assert release.wait(timeout=5)
        return original_index(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module,
        "project_universal_governed_work_index",
        slow_index,
    )
    results = []
    errors = []

    def read_index():
        try:
            results.append(UniversalRuntimeClient(
                descriptor_path, provider
            ).request("GET", "/api/universal/work", {"projection": "index"}))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=read_index, daemon=True)
    second = threading.Thread(target=read_index, daemon=True)
    try:
        first.start()
        assert entered.wait(timeout=5)
        second.start()
        time.sleep(0.25)
        assert calls["count"] == 1
        release.set()
        first.join(timeout=10)
        second.join(timeout=10)
        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        assert len(results) == 2
        assert results[0]["revision"] == results[1]["revision"]
        assert calls["count"] == 1
    finally:
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)
        server.close()


def test_compact_work_index_exposes_state_and_claimant(tmp_path):
    descriptor_path = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"w" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    agent = UniversalRuntimeClient(descriptor_path, provider)
    try:
        created_root, _membership_wire, _revision = create_universal_governed_work(
            server.universal_store,
            server.universal_registry,
            title="Compact work index ownership proof",
            description="Compact index exposes state without full work projection.",
            priority=10,
            external_key="court:compact-index:claimant",
            x=320,
            y=240,
        )
        open_index = client.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        open_item = next(
            item for item in open_index["items"]
            if item["root"] == created_root
        )
        assert open_item["operational"]["current_state_label"] == "OPEN"
        assert open_item["claimant_session"] is None
        enrolled = agent.bind_agent_session(
            runtime="codex",
            external_session_id="court-compact-index-claimant",
        )
        session_root = enrolled["agent_session"]
        agent.request("POST", "/api/universal/workshop", {
            "category": "plan",
            "text": "Claiming compact-index court work.",
            "refs": [created_root],
            "evidence": [],
            "recipients": [],
            "reply_to": None,
            "idempotency_key": "court:compact-index:claimant:plan",
            "created_at": "2026-07-19T00:00:00+00:00",
        })
        agent.request("POST", "/api/universal/work-transition", {
            "root": created_root,
            "event": "claim",
            "evidence": "",
        })
        claimed_index = agent.request(
            "GET", "/api/universal/work", {"projection": "index"}
        )
        claimed_item = next(
            item for item in claimed_index["items"]
            if item["root"] == created_root
        )
        assert claimed_item["operational"]["current_state_label"] == "CLAIMED"
        assert claimed_item["claimant_session"] == session_root
        assert claimed_item["claimant_agent_body"] == (
            server.universal_registry.agent_body.body.root_id
        )
        assert claimed_item["claim_binding"].startswith(
            "app:governed-work-claim-binding:"
        )
    finally:
        server.close()


def test_compact_work_index_does_not_expand_instance_interfaces(
    tmp_path, monkeypatch
):
    descriptor_path = tmp_path / "compact-index-no-interface-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"n" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    try:
        created_root, _membership_wire, _revision = create_universal_governed_work(
            server.universal_store,
            server.universal_registry,
            title="No interface expansion",
            description="The compact index derives field cells directly.",
            priority=7,
            external_key="court:compact-index:no-interface-expansion",
            x=320,
            y=240,
        )
        snapshot = server.universal_store.snapshot()
        protocol = server.universal_registry.assembly_protocol
        original_read_relation = universal_application_module.read_relation
        instance_members = original_read_relation(
            snapshot, created_root, budget=100_000
        )
        forbidden_roots = {
            member.participant_id for member in instance_members
            if member.role_id == protocol.role("interface")
        }

        def guarded_read_relation(snapshot, relation_root, *args, **kwargs):
            if relation_root in forbidden_roots:
                raise AssertionError(
                    "compact work index must not expand instance interfaces"
                )
            return original_read_relation(
                snapshot, relation_root, *args, **kwargs
            )

        monkeypatch.setattr(
            universal_application_module,
            "read_relation",
            guarded_read_relation,
        )
        projected = UniversalRuntimeClient(
            descriptor_path, provider
        ).request("GET", "/api/universal/work", {"projection": "index"})
        item = next(
            item for item in projected["items"]
            if item["root"] == created_root
        )
        assert item["interfaces"]["external-key"]["value"] == (
            "court:compact-index:no-interface-expansion"
        )
        assert item["interfaces"]["title"]["value"] == "No interface expansion"
    finally:
        server.close()


def test_stale_work_claim_recovery_requires_dead_capability(tmp_path):
    descriptor_path = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"r" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    agent_a = UniversalRuntimeClient(descriptor_path, provider)
    agent_b = UniversalRuntimeClient(descriptor_path, provider)
    agent_c = UniversalRuntimeClient(descriptor_path, provider)
    try:
        (tmp_path / "green.flag").write_text("green", encoding="utf-8")
        work_root, _membership_wire, _revision = create_universal_governed_work(
            server.universal_store,
            server.universal_registry,
            title="Recover stale claimed work",
            description="A lost runtime token must not lock governed work forever.",
            priority=10,
            external_key="court:stale-claim:recover",
            structured_references={
                "requirements": {
                    "gate": {
                        "kind": "file_exists",
                        "spec": {"path": "green.flag"},
                    },
                },
                "cde-container": {
                    "container_id": "court-test",
                    "allowed_paths": ["."],
                },
            },
            x=320,
            y=240,
        )
        session_a = agent_a.bind_agent_session(
            runtime="codex",
            external_session_id="court-stale-claim-a",
        )["agent_session"]
        session_b = agent_b.bind_agent_session(
            runtime="gemini",
            external_session_id="court-stale-claim-b",
        )["agent_session"]
        session_c = agent_c.bind_agent_session(
            runtime="codex",
            external_session_id="court-stale-claim-c",
        )["agent_session"]
        agent_a.request("POST", "/api/universal/workshop", {
            "category": "plan",
            "text": "Claiming stale-claim recovery court work.",
            "refs": [work_root],
            "evidence": [],
            "recipients": [],
            "reply_to": None,
            "idempotency_key": "court:stale-claim:recover:plan",
            "created_at": "2026-07-19T00:00:00+00:00",
        })
        agent_a.claim_work(work_root)
        with pytest.raises(MachineTransportError, match="live capability"):
            agent_b.recover_work_claim(work_root, "live sessions cannot be stolen")
        with server._machine_agent_session_lock:
            server._machine_agent_sessions.pop(session_a)
        recovered = agent_b.recover_work_claim(
            work_root,
            "Original runtime capability was lost during bridge restart.",
            projection="index",
        )
        assert recovered["projection"] == "index"
        assert recovered["previous_claimant_session"] == session_a
        assert recovered["claimant_session"] == session_b
        item = next(
            item for item in recovered["status"]["items"]
            if item["root"] == work_root
        )
        assert item["operational"]["current_state_label"] == "CLAIMED"
        assert item["claimant_session"] == session_b
        submitted = agent_b.request("POST", "/api/universal/work-transition", {
            "root": work_root,
            "event": "submit",
            "evidence": "Compact transition response after stale recovery.",
            "projection": "index",
        })
        assert submitted["projection"] == "index"
        submitted_item = next(
            item for item in submitted["status"]["items"]
            if item["root"] == work_root
        )
        assert submitted_item["operational"]["current_state_label"] == "REVIEW"
        with pytest.raises(MachineTransportError, match="live capability"):
            agent_c.recover_work_court(
                work_root,
                "live submitter cannot be stolen",
                projection="index",
            )
        with server._machine_agent_session_lock:
            server._machine_agent_sessions.pop(session_b)
        court = agent_c.recover_work_court(
            work_root,
            "Submitting runtime capability was lost during bridge restart.",
            projection="index",
        )
        assert court["recovered"] is True
        assert court["recovering_agent_session"] == session_c
        assert court["submitted_claimant_session"] == session_b
        assert court["projection"] == "index"
        assert court["passed"] is True
        assert court["event"] == "accept"
        completed_item = next(
            item for item in court["status"]["items"]
            if item["root"] == work_root
        )
        assert completed_item["operational"]["current_state_label"] == "COMPLETE"
    finally:
        server.close()


def test_stale_review_with_invalid_court_input_returns_and_reclaims(tmp_path):
    descriptor_path = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"i" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    submitter = UniversalRuntimeClient(descriptor_path, provider)
    recoverer = UniversalRuntimeClient(descriptor_path, provider)
    try:
        work_root, _membership_wire, _revision = create_universal_governed_work(
            server.universal_store,
            server.universal_registry,
            title="Malformed review recovery",
            description="Missing court inputs should return and reclaim.",
            priority=10,
            external_key="court:stale-review:invalid-input",
            x=320,
            y=240,
        )
        submitter_session = submitter.bind_agent_session(
            runtime="codex",
            external_session_id="court-stale-review-submit",
        )["agent_session"]
        recoverer_session = recoverer.bind_agent_session(
            runtime="gemini",
            external_session_id="court-stale-review-recover",
        )["agent_session"]
        submitter.claim_work(work_root)
        submitted = submitter.request("POST", "/api/universal/work-transition", {
            "root": work_root,
            "event": "submit",
            "evidence": "Submitted without court requirements.",
            "projection": "index",
        })
        submitted_item = next(
            item for item in submitted["status"]["items"]
            if item["root"] == work_root
        )
        assert submitted_item["operational"]["current_state_label"] == "REVIEW"
        with server._machine_agent_session_lock:
            server._machine_agent_sessions.pop(submitter_session)
        recovered = recoverer.recover_work_court(
            work_root,
            "Submitted work has invalid court inputs.",
            projection="index",
        )
        assert recovered["passed"] is False
        assert recovered["event"] == "return"
        assert recovered["submitted_claimant_session"] == submitter_session
        assert recovered["recovering_agent_session"] == recoverer_session
        assert "value-graph root" in recovered["court_error"]
        item = next(
            item for item in recovered["status"]["items"]
            if item["root"] == work_root
        )
        assert item["operational"]["current_state_label"] == "CLAIMED"
        assert item["claimant_session"] == recoverer_session
    finally:
        server.close()


def test_baboom_device_proof_selects_its_catalog_body_and_fails_closed(tmp_path):
    descriptor_path = tmp_path / "baboom-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"b" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(server, reference)
    external_session_id = "baboom-device-proof-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        unproven = UniversalRuntimeClient(descriptor_path, provider)
        with pytest.raises(MachineTransportError, match="credential"):
            unproven.bind_agent_session(
                runtime="baboom", external_session_id=external_session_id
            )

        baboom = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = baboom.bind_agent_session(
            runtime="baboom",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert enrolled["catalog_entry"] == (
            "app:agent-body-catalog:entry:baboom"
        )
        assert enrolled["agent_body"] == "app:agent-body:baboom"
        lease = baboom.renew_runtime_presence()
        assert lease["agent_session"] == enrolled["agent_session"]
        native_frame = baboom.baboom_native_frame()
        assert native_frame["projection"] == BABOOM_NATIVE_FRAME_PROJECTION
        assert native_frame["revision"] == native_frame["context"]["revision"]
        activity = baboom.record_baboom_activity(app="Revit")
        assert activity["activity"].startswith("baboom-activity:sha256:")
        assert activity["app"] == "Revit"
        assert activity["agent_session"] == enrolled["agent_session"]
        assert activity["expires_at"] > time.time()
        meeting_notes = baboom.request(
            "POST", "/api/universal/baboom-meeting-notes", {"action": "start"}
        )
        assert meeting_notes["meeting_notes"].startswith(
            "baboom-meeting-notes:session:"
        )
        assert meeting_notes["state"] == "active"
        assert meeting_notes["agent_session"] == enrolled["agent_session"]
        assert meeting_notes["expires_at"] > time.time()
        with pytest.raises(MachineTransportError, match="action is not released"):
            baboom.request(
                "POST",
                "/api/universal/baboom-meeting-notes",
                {"action": "record"},
            )
        with pytest.raises(MachineTransportError, match="app is not released"):
            baboom.request(
                "POST",
                "/api/universal/baboom-activity",
                {"app": "Sensitive Client Portal"},
            )
        session = read_agent_session(
            server.universal_store.snapshot(),
            server.universal_registry.agent_body.protocol,
            server.universal_registry.authorization.protocol,
            enrolled["agent_session"],
        )
        assert session.body_root == "app:agent-body:baboom"
        presence = UniversalRuntimeClient(descriptor_path, provider).request(
            "GET", "/api/universal/baboom-context"
        )
        assert presence["presence"] == {
            "active_runtime_sessions": 1,
            "baboom_connected": True,
            "baboom_action_capability_active": False,
        }
        assert presence["device"]["active_baboom_devices"] == 1
        assert presence["activity"] == {
            "active_baboom_devices": 1,
            "foreground_apps": {"Revit": 1},
        }
        assert presence["meeting_notes"] == {"active_sessions": 1}
        assert presence["persona_form"] == "librarian"
        closed_notes = baboom.request(
            "POST", "/api/universal/baboom-meeting-notes", {"action": "stop"}
        )
        assert closed_notes["state"] == "closed"
        post_close = UniversalRuntimeClient(descriptor_path, provider).request(
            "GET", "/api/universal/baboom-context"
        )
        assert post_close["meeting_notes"] == {"active_sessions": 0}
        assert post_close["persona_form"] == "bim-wizard"
        assert enrolled["agent_session"] not in json.dumps(presence)
        with server._machine_agent_session_lock:
            server._machine_agent_sessions.clear()
        reconnected = UniversalRuntimeClient(descriptor_path, provider)
        continued = reconnected.bind_agent_session(
            runtime="baboom",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert continued["continued"] is True
        assert continued["agent_session"] == enrolled["agent_session"]
        baboom = reconnected
        renewed_lease = baboom.renew_runtime_presence()
        assert renewed_lease["agent_session"] == enrolled["agent_session"]

        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM proof court",
            "description": "Claim only through its released device-bound body.",
            "priority": 80,
            "external_key": "baboom-device-proof-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "device-proof"},
                "required-capabilities": ["governance"],
            },
            "x": 840,
            "y": 540,
        })
        claim = baboom.claim_next_work()
        assert claim["claimed"] is True
        assert claim["work"]["root"] == created["created_root"]
        assert claim["work"]["claimant_agent_body"] == "app:agent-body:baboom"
        with pytest.raises(MachineTransportError, match="does not admit"):
            baboom.request("POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "release",
                "evidence": "",
            })
        with pytest.raises(MachineTransportError, match="does not admit"):
            baboom.request("POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "submit",
                "evidence": "untrusted completion",
            })

        replay_client = UniversalRuntimeClient(descriptor_path, provider)
        replay_challenge = replay_client.request(
            "POST",
            "/api/universal/agent-session-challenge",
            {"runtime": "baboom"},
        )
        replay_body = {
            "runtime": "baboom",
            "external_session_id": "baboom-replay-court",
            "device_credential": _device_credential(
                key,
                custody_root,
                replay_challenge,
                "baboom-replay-court",
            ),
        }
        replay_client.request("POST", "/api/universal/agent-session", replay_body)
        with pytest.raises(MachineTransportError, match="challenge"):
            UniversalRuntimeClient(descriptor_path, provider).request(
                "POST", "/api/universal/agent-session", replay_body
            )

        revoke_device_custody(
            server.universal_store,
            server.universal_registry.device_custody_protocol,
            custody_root,
            reason="court revocation",
        )
        with pytest.raises(MachineTransportError, match="custody is revoked"):
            baboom.claim_next_work()
        assert founder.request("GET", "/api/universal/baboom-context")[
            "device"
        ]["active_baboom_devices"] == 0
    finally:
        server.close()


def test_cloud_gateway_device_binding_requires_the_same_device_as_baboom_session(
    tmp_path,
):
    descriptor_path = tmp_path / "cloud-device-binding-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"g" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(server, reference)
    external_session_id = "cloud-device-binding-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        # Before an Agent Session exists, remote enrollment must already bind
        # the DPoP device identity to the challenged Device Custody.
        challenge = server.dispatch_universal_machine_route({
            "method": "POST",
            "path": "/api/universal/agent-session-challenge",
            "body": {"runtime": "baboom"},
        })
        enrollment = {
            "runtime": "baboom",
            "external_session_id": external_session_id,
            "device_credential": _device_credential(
                key, custody_root, challenge, external_session_id
            ),
        }
        pending = {
            "runtime_id": challenge["runtime_id"],
            "request_id": "a" * 32,
            "method": "POST",
            "path": "/api/universal/agent-session",
            "body": enrollment,
            "session": {},
        }
        cloud_device_root = "device-proof-key:sha256:" + reference.thumbprint
        server.verify_universal_cloud_request_device(
            pending, cloud_device_root=cloud_device_root
        )
        with pytest.raises(AuthorizationDenied, match="does not match"):
            server.verify_universal_cloud_request_device(
                pending,
                cloud_device_root="device-proof-key:sha256:" + "A" * 43,
            )

        baboom = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = baboom.bind_agent_session(
            runtime="baboom",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        request_id = "b" * 32
        request = {
            "runtime_id": "cloud-gateway-runtime-0001",
            "request_id": request_id,
            "method": "GET",
            "path": "/api/universal/baboom-context",
            "body": {},
            "session": {
                "root": enrolled["agent_session"],
                "proof": hmac.new(
                    baboom._agent_session_token.encode("utf-8"),
                    session_proof_payload(
                        runtime_id="cloud-gateway-runtime-0001",
                        request_id=request_id,
                        method="GET",
                        path="/api/universal/baboom-context",
                        body={},
                        session_root=enrolled["agent_session"],
                    ),
                    hashlib.sha256,
                ).hexdigest(),
            },
        }
        server.verify_universal_cloud_request_device(
            request, cloud_device_root=cloud_device_root
        )
        with pytest.raises(AuthorizationDenied, match="does not match"):
            server.verify_universal_cloud_request_device(
                request,
                cloud_device_root="device-proof-key:sha256:" + "A" * 43,
            )
    finally:
        server.close()


def test_baboom_execution_can_draft_one_non_executing_plan_for_its_exact_claim(tmp_path):
    descriptor_path = tmp_path / "baboom-work-plan-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"p" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-work-plan-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM work plan transport court",
            "description": "Prepare a review without executing any action.",
            "priority": 80,
            "external_key": "baboom-work-plan-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "work-plan"},
                "required-capabilities": ["governance"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert enrolled["agent_body"] == "app:agent-body:baboom"
        claim = execution.claim_next_work()
        assert claim["work"]["root"] == created["created_root"]

        drafted = execution.request("POST", "/api/universal/work-plan", {
            "root": created["created_root"],
        })
        assert drafted["work"] == created["created_root"]
        assert drafted["state"] == "draft"
        assert drafted["reused"] is False
        plan = read_value_graph(
            server.universal_store.snapshot(),
            server.universal_registry.value_graph_protocol,
            drafted["plan"],
        )
        assert plan["execution"] == "none"
        assert plan["model_output"] == "not-used"
        assert len(plan["steps"]) == 5

        viewed = execution.request("POST", "/api/universal/work-plan-read", {
            "root": created["created_root"],
        })
        assert viewed["work"] == created["created_root"]
        assert viewed["plan_root"] == drafted["plan"]
        assert viewed["revision"] == drafted["revision"]
        assert viewed["plan"] == {
            "state": "draft",
            "summary": "BABOOM work plan transport court",
            "priority_assessment": {
                "declared_priority": 80,
                "released_order": [
                    "Safety and data-loss risk",
                    "Founder pin",
                    "Blocking dependency",
                    "Failed active court",
                    "Accepted due work and fairness",
                    "Model-proposed relevance",
                ],
                "model_authority": "none",
            },
            "steps": [
                {
                    "order": 1,
                    "title": "Research the bounded Workshop, active Work, and applicable evidence.",
                    "effect": "none",
                },
                {
                    "order": 2,
                    "title": "Confirm scope, dependencies, privacy boundaries, and acceptance evidence.",
                    "effect": "none",
                },
                {
                    "order": 3,
                    "title": "Apply the released priority order before selecting a next action.",
                    "effect": "none",
                },
                {
                    "order": 4,
                    "title": "Prepare a bounded proposal or reversible action for founder approval.",
                    "effect": "approval-required",
                },
                {
                    "order": 5,
                    "title": "Validate actual evidence and request review before completion.",
                    "effect": "approval-required",
                },
            ],
            "execution": "none",
            "model_output": "not-used",
            "live_activity": {
                "model": "not-requested",
                "connector": "not-requested",
            },
        }

        status = execution.request("GET", "/api/universal/work")
        item = next(
            candidate for candidate in status["items"]
            if candidate["root"] == created["created_root"]
        )
        assert item["operational"]["current_state_label"] == "CLAIMED"
        assert item["claimant_session"] == enrolled["agent_session"]
        assert item["interfaces"]["plan"]["target"] == drafted["plan"]

        repeated = execution.request("POST", "/api/universal/work-plan", {
            "root": created["created_root"],
        })
        assert repeated["plan"] == drafted["plan"]
        assert repeated["reused"] is True
        assert repeated["revision"] == drafted["revision"]
    finally:
        server.close()


def test_baboom_execution_can_prepare_one_sealed_cognition_request(tmp_path):
    descriptor_path = tmp_path / "baboom-cognition-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"c" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-cognition-transport-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM Cognition transport court",
            "description": "Prepare a governed review with no provider call.",
            "priority": 80,
            "external_key": "baboom-cognition-transport-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "model-cognition"},
                "required-capabilities": ["governance"],
            },
            "x": 860,
            "y": 560,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        claim = execution.claim_next_work()
        assert claim["work"]["root"] == created["created_root"]
        execution.request("POST", "/api/universal/work-plan", {
            "root": created["created_root"],
        })

        prepared = execution.request("POST", "/api/universal/model-cognition", {
            "root": created["created_root"],
            "provider": "local",
            "model": "qwen3:8b",
        })
        assert prepared["work"] == created["created_root"]
        assert prepared["state"] == "prepared"
        assert prepared["provider"] == "local"
        assert prepared["model"] == "qwen3:8b"
        assert prepared["request"].startswith("cognition-request:")
        assert prepared["context"]
        assert prepared["input_bytes"] > 0
        assert prepared["binding"].endswith(":binding")

        status = execution.request("GET", "/api/universal/work")
        item = next(
            candidate for candidate in status["items"]
            if candidate["root"] == created["created_root"]
        )
        assert item["operational"]["current_state_label"] == "CLAIMED"
        assert item["claimant_session"] == enrolled["agent_session"]
        assert item["model_execution"]["latest"] is None

        repeated = execution.request("POST", "/api/universal/model-cognition", {
            "root": created["created_root"],
            "provider": "local",
            "model": "qwen3:8b",
        })
        assert repeated["request"] == prepared["request"]
        assert repeated["revision"] == prepared["revision"]
    finally:
        server.close()


def test_baboom_model_broker_executes_only_the_graph_grant_and_settles_one_receipt(tmp_path):
    descriptor_path = tmp_path / "baboom-model-broker-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"b" * 32
    )
    broker = _RecordedModelBroker()
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        model_execution_broker=broker,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-model-broker-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM model broker court",
            "description": "Execute only a founder-approved graph delegation.",
            "priority": 80,
            "external_key": "baboom-model-broker-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "model-broker"},
                "required-capabilities": ["governance"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        execution.claim_work(created["created_root"])
        execution.request("POST", "/api/universal/work-plan", {
            "root": created["created_root"],
        })
        cognition = execution.request("POST", "/api/universal/model-cognition", {
            "root": created["created_root"],
            "provider": "local",
            "model": "court-local-model",
        })
        delegation = execution.request("POST", "/api/universal/model-delegation", {
            "root": created["created_root"],
            "provider": "local",
            "model": "court-local-model",
            "data_class": "internal-text",
            "cognition_request": cognition["request"],
        })
        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-model-broker-founder-court",
        )
        founder.request("POST", "/api/universal/model-delegation-approve", {
            "delegation": delegation["delegation"],
        })
        grant = execution.request("POST", "/api/universal/model-delegation-grant", {
            "delegation": delegation["delegation"],
        })
        settled = execution.request("POST", "/api/universal/model-delegation-execute", {
            "grant": grant["grant"],
            "capability": grant["capability"],
        })

        assert len(broker.calls) == 1
        assert broker.calls[0]["provider"] == "local"
        assert broker.calls[0]["location"] == "local-http:ollama"
        assert broker.calls[0]["model"] == "court-local-model"
        assert broker.calls[0]["data_class"] == "internal-text"
        assert "Required Work plan (graph-held, read-only)" in broker.calls[0]["task"]
        assert "Shared Workshop coordination brief (sealed, read-only)" in broker.calls[0]["task"]
        assert settled["reconciled"] is True
        assert settled["history_root"] == ""
        assert settled["work_advanced"] is False
        assert settled["receipt"].startswith("app:baboom-model-receipt:")
        assert settled["proposal"].startswith("proposal:")
        assert settled["status"]["counts"]["claimed"] == 1
        with pytest.raises(MachineTransportError, match="replayed"):
            execution.request("POST", "/api/universal/model-delegation-execute", {
                "grant": grant["grant"],
                "capability": grant["capability"],
            })
        assert len(broker.calls) == 1
    finally:
        server.close()


def test_baboom_execution_body_rejects_generic_submit_and_reports_failed_receipt(tmp_path):
    descriptor_path = tmp_path / "baboom-execution-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"e" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-execution-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM execution receipt court",
            "description": "Complete only through BABOOM action-capability receipt.",
            "priority": 80,
            "external_key": "baboom-execution-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "execution-body"},
                "required-capabilities": ["governance"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert enrolled["agent_body"] == "app:agent-body:baboom"
        claim = execution.claim_next_work()
        assert claim["work"]["root"] == created["created_root"]
        with pytest.raises(MachineTransportError, match="reserved for model receipt"):
            execution.request("POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "submit",
                "evidence": "provider=local; outcome=completed; output_digest=court",
            })
        with pytest.raises(MachineTransportError, match="reserved for model receipt"):
            execution.request("POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "block",
                "evidence": "operator requested a generic block",
            })
        execution.request("POST", "/api/universal/work-plan", {
            "root": created["created_root"],
        })
        cognition = execution.request("POST", "/api/universal/model-cognition", {
            "root": created["created_root"],
            "provider": "local",
            "model": "court-local-model",
        })
        delegation = execution.request("POST", "/api/universal/model-delegation", {
            "root": created["created_root"],
            "provider": "local",
            "model": "court-local-model",
            "data_class": "internal-text",
            "cognition_request": cognition["request"],
        })
        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-failure-founder-court",
        )
        founder.request("POST", "/api/universal/model-delegation-approve", {
            "delegation": delegation["delegation"],
        })
        grant = execution.request("POST", "/api/universal/model-delegation-grant", {
            "delegation": delegation["delegation"],
        })
        failed = execution.request("POST", "/api/universal/model-delegation-receipt", {
            "grant": grant["grant"],
            "capability": grant["capability"],
            "outcome": "failed",
            "output_digest": hashlib.sha256(b"").hexdigest(),
            "output_bytes": 0,
            "error_code": "worker-failed",
        })
        assert failed["history_root"] == ""
        assert failed["status"]["counts"]["claimed"] == 1
        assert failed["status"]["model_execution"] == {
            "total": 1,
            "awaiting_approval": 0,
            "ready": 0,
            "expired": 0,
            "succeeded": 0,
            "failed": 1,
        }
        latest = failed["status"]["items"][0]["model_execution"]["latest"]
        assert latest["state"] == "failed"
        assert latest["error_code"] == "worker-failed"
        recovered = execution.request(
            "POST",
            "/api/universal/model-delegation-recover",
            {"receipt": failed["receipt"]},
        )
        assert recovered["receipt"] == failed["receipt"]
        assert recovered["history_root"].startswith("state-event:")
        assert recovered["status"]["counts"]["blocked"] == 1
        assert recovered["status"]["counts"]["claimed"] == 0
        assert recovered["status"]["model_execution"]["failed"] == 1
        assert (
            recovered["status"]["items"][0]["operational"]["current_state_label"].casefold()
            == "blocked"
        )
        with pytest.raises(MachineTransportError, match="reserved for model receipt"):
            execution.request("POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "resume",
                "evidence": "operator requested a generic resume",
            })
        resumed = execution.request(
            "POST",
            "/api/universal/model-delegation-resume",
            {"receipt": failed["receipt"]},
        )
        assert resumed["receipt"] == failed["receipt"]
        assert resumed["history_root"].startswith("state-event:")
        assert resumed["status"]["counts"]["claimed"] == 1
        assert resumed["status"]["counts"]["blocked"] == 0
        assert (
            resumed["status"]["items"][0]["operational"]["current_state_label"].casefold()
            == "claimed"
        )
        with pytest.raises(MachineTransportError, match="already consumed"):
            execution.request(
                "POST",
                "/api/universal/model-delegation-recover",
                {"receipt": failed["receipt"]},
            )
        with pytest.raises(MachineTransportError, match="requires blocked Work"):
            execution.request(
                "POST",
                "/api/universal/model-delegation-resume",
                {"receipt": failed["receipt"]},
            )
    finally:
        server.close()


def test_baboom_execution_reconnects_to_its_exact_session_after_transport_loss(tmp_path):
    descriptor_path = tmp_path / "baboom-execution-continuation-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"c" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-execution-continuation-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM execution continuation court",
            "description": "Continue only with the same device-proofed graph session.",
            "priority": 80,
            "external_key": "baboom-execution-continuation-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "execution-continuation"},
                "required-capabilities": ["governance"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert enrolled["continued"] is False
        session_root = enrolled["agent_session"]
        exact = execution.claim_work(created["created_root"])
        assert exact["claimed"] is True
        assert exact["reused"] is False
        assert exact["work"]["root"] == created["created_root"]

        # A companion restart may recover its graph-held claim, but it cannot
        # seize the original mutable capability or disturb that live worker.
        recovered = UniversalRuntimeClient(descriptor_path, provider)
        resumed = recovered.resume_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert resumed["agent_session"] == session_root
        assert resumed["access"] == "recovery-read"
        assert recovered.agent_session_access == "recovery-read"
        assert recovered.current_claimed_work()["root"] == created["created_root"]
        with pytest.raises(MachineTransportError, match="read-only"):
            recovered.claim_next_work()
        assert execution.claim_next_work()["work"]["root"] == created["created_root"]

        # A server restart loses only this in-memory capability map. The graph
        # session and claim remain, so a fresh device proof may restore it.
        with server._machine_agent_session_lock:
            server._machine_agent_sessions.clear()
        revision_before_reconnect = server.universal_store.revision
        reconnected = UniversalRuntimeClient(descriptor_path, provider)
        continued = reconnected.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert continued["continued"] is True
        assert continued["agent_session"] == session_root
        assert continued["revision"] == revision_before_reconnect
        reused = reconnected.claim_next_work()
        assert reused["claimed"] is True
        assert reused["reused"] is True
        assert reused["work"]["root"] == created["created_root"]

        with pytest.raises(MachineTransportError, match="proof is invalid"):
            execution.claim_next_work()
        with pytest.raises(MachineTransportError, match="already bound"):
            UniversalRuntimeClient(descriptor_path, provider).bind_agent_session(
                runtime="baboom-execution",
                external_session_id=external_session_id,
                device_credential_provider=provider_for,
            )
    finally:
        server.close()


def test_baboom_execution_model_delegation_requires_founder_approval_and_one_receipt(tmp_path):
    descriptor_path = tmp_path / "baboom-model-delegation-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"m" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-model-delegation-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM delegated model court",
            "description": "Run only after the founder approves one provider request.",
            "priority": 80,
            "external_key": "baboom-model-delegation-court",
            "references": {
                "scope": server.universal_registry.map.domains["orchestration"],
            },
            "structured_references": {
                "requirements": {"court": "model-delegation"},
                "required-capabilities": ["governance"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        claim = execution.claim_next_work()
        assert claim["work"]["root"] == created["created_root"]
        execution.request("POST", "/api/universal/work-plan", {
            "root": created["created_root"],
        })
        with pytest.raises(MachineTransportError, match="observation shape is invalid"):
            execution.request("POST", "/api/universal/model-cognition", {
                "root": created["created_root"],
                "provider": "local",
                "model": "court-local-model",
                "observation": {
                    "kind": "foreground-app/v1",
                    "app": "Revit",
                    "title": "Confidential project.rvt",
                },
            })
        cognition = execution.request("POST", "/api/universal/model-cognition", {
            "root": created["created_root"],
            "provider": "local",
            "model": "court-local-model",
            "observation": {
                "kind": "foreground-app/v1",
                "app": "Revit",
            },
        })
        assert cognition["state"] == "prepared"
        delegation = execution.request("POST", "/api/universal/model-delegation", {
            "root": created["created_root"],
            "provider": "local",
            "model": "court-local-model",
            "data_class": "internal-text",
            "cognition_request": cognition["request"],
        })
        assert delegation["work"] == created["created_root"]
        assert "BABOOM delegated model court" in delegation["task"]
        assert "Shared Workshop coordination brief (sealed, read-only)" in delegation["task"]
        assert (
            "Current app context (founder-confirmed metadata only): Revit. "
            "Do not infer document or screen content."
            in delegation["task"]
        )
        with pytest.raises(MachineTransportError, match="not granted"):
            execution.request("POST", "/api/universal/model-delegation-grant", {
                "delegation": delegation["delegation"],
            })

        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-model-founder-court",
        )
        approved = founder.request("POST", "/api/universal/model-delegation-approve", {
            "delegation": delegation["delegation"],
        })
        assert approved["approved"] is True
        grant = execution.request("POST", "/api/universal/model-delegation-grant", {
            "delegation": delegation["delegation"],
        })
        assert grant["delegation"] == delegation["delegation"]
        settled = execution.request("POST", "/api/universal/model-delegation-receipt", {
            "grant": grant["grant"],
            "capability": grant["capability"],
            "outcome": "succeeded",
            "output_digest": hashlib.sha256(b"court model output").hexdigest(),
            "output_bytes": 18,
            "error_code": "",
            "cognition_request": cognition["request"],
            "proposal": {
                "summary": "Prepare a bounded coordination review.",
                "next_actions": [
                    "Inspect the governing evidence.",
                    "Request review before any effect.",
                ],
                "risks": ["The provider output requires founder review."],
                "uncertainty": 0.2,
            },
        })
        assert settled["receipt"].startswith("app:baboom-model-receipt:")
        assert settled["proposal"].startswith("proposal:")
        assert settled["history_root"] == ""
        assert settled["work_advanced"] is False
        assert settled["status"]["counts"]["claimed"] == 1
        assert settled["status"]["model_execution"]["succeeded"] == 1
        proposal_members = read_relation(
            server.universal_store.snapshot(), settled["proposal"], budget=100_000
        )
        payload_root = next(
            member.participant_id for member in proposal_members
            if member.role_id == server.universal_registry.agent_body.cognition_protocol.role(
                "proposal-payload"
            )
        )
        payload = json.loads(
            server.universal_store.snapshot().cells[payload_root].atom.decode(
                "utf-8"
            )
        )
        assert payload == {
            "kind": "baboom-model-review-proposal/v1",
            "summary": "Prepare a bounded coordination review.",
            "next_actions": [
                "Inspect the governing evidence.",
                "Request review before any effect.",
            ],
            "risks": ["The provider output requires founder review."],
            "uncertainty": 0.2,
            "provider": "local",
            "model": "court-local-model",
            "output_digest": hashlib.sha256(b"court model output").hexdigest(),
            "output_bytes": 18,
        }
        with pytest.raises(MachineTransportError, match="replayed"):
            execution.request("POST", "/api/universal/model-delegation-receipt", {
                "grant": grant["grant"],
                "capability": grant["capability"],
                "outcome": "succeeded",
                "output_digest": hashlib.sha256(b"replay").hexdigest(),
                "output_bytes": 6,
                "error_code": "",
            })
    finally:
        server.close()


def test_baboom_connector_delegation_requires_founder_approval_and_one_receipt(tmp_path):
    descriptor_path = tmp_path / "baboom-connector-delegation-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"n" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-connector-delegation-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "Prepare the founder's next meeting brief",
            "description": "Read the approved calendar source after the founder authorizes it.",
            "priority": 80,
            "external_key": "baboom-connector-delegation-court",
            "references": {
                "scope": server.universal_registry.map.domains["connectors"],
            },
            "structured_references": {
                "requirements": {"court": "connector-delegation"},
                "required-capabilities": ["calendar"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        claim = execution.claim_next_work()
        assert claim["work"]["root"] == created["created_root"]
        raw_input = b'{"limit":5,"calendar":"founder-private"}'
        delegation = execution.request("POST", "/api/universal/connector-delegation", {
            "root": created["created_root"],
            "provider": "teams-meetings",
            "input_digest": hashlib.sha256(raw_input).hexdigest(),
            "input_bytes": len(raw_input),
            "data_class": "internal-metadata",
        })
        assert delegation["work"] == created["created_root"]
        assert delegation["operation"] == "teams.list_meetings"
        assert "founder-private" not in repr(server.universal_store.snapshot().cells)
        with pytest.raises(MachineTransportError, match="not granted"):
            execution.request("POST", "/api/universal/connector-delegation-grant", {
                "delegation": delegation["delegation"],
            })

        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-connector-founder-court",
        )
        approved = founder.request(
            "POST", "/api/universal/connector-delegation-approve", {
                "delegation": delegation["delegation"],
            }
        )
        assert approved["approved"] is True
        grant = execution.request("POST", "/api/universal/connector-delegation-grant", {
            "delegation": delegation["delegation"],
        })
        assert grant["delegation"] == delegation["delegation"]
        settled = execution.request("POST", "/api/universal/connector-delegation-receipt", {
            "grant": grant["grant"],
            "capability": grant["capability"],
            "outcome": "succeeded",
            "output_digest": hashlib.sha256(b"two meetings").hexdigest(),
            "output_bytes": 12,
            "error_code": "",
        })
        assert settled["receipt"].startswith("app:baboom-connector-receipt:")
        assert settled["history_root"].startswith("state-event:")
        assert settled["status"]["counts"]["review"] == 1
        assert settled["status"]["connector_execution"]["succeeded"] == 1
        latest = settled["status"]["items"][0]["connector_execution"]["latest"]
        assert latest["operation"] == "teams.list_meetings"
        assert latest["state"] == "succeeded"
        with pytest.raises(MachineTransportError, match="replayed"):
            execution.request("POST", "/api/universal/connector-delegation-receipt", {
                "grant": grant["grant"],
                "capability": grant["capability"],
                "outcome": "succeeded",
                "output_digest": hashlib.sha256(b"replay").hexdigest(),
                "output_bytes": 6,
                "error_code": "",
            })
    finally:
        server.close()


def test_consented_notion_delegation_requires_same_live_baboom_consent(tmp_path):
    descriptor_path = tmp_path / "baboom-consented-notion-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"s" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(server, reference, runtime="baboom")
    bind_universal_runtime_agent_body_device_custody(
        server.universal_store,
        server.universal_registry,
        runtime="baboom-execution",
        custody_root=custody_root,
    )
    presence_external_id = "baboom-consented-notion-presence"
    execution_external_id = "baboom-consented-notion-execution"

    def presence_credential(challenge):
        return _device_credential(
            key, custody_root, challenge, presence_external_id
        )

    def execution_credential(challenge):
        return _device_credential(
            key, custody_root, challenge, execution_external_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "Publish approved founder meeting notes",
            "description": "Append one founder-supplied meeting note only with live consent.",
            "priority": 80,
            "external_key": "baboom-consented-notion-court",
            "references": {
                "scope": server.universal_registry.map.domains["connectors"],
            },
            "structured_references": {
                "requirements": {"court": "consented-notion"},
                "required-capabilities": ["meeting-notes"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=execution_external_id,
            device_credential_provider=execution_credential,
        )
        execution.renew_runtime_presence()
        assert execution.claim_next_work()["work"]["root"] == created["created_root"]
        raw_input = b'{"text":"Founder decision","block_id":"local"}'
        request = {
            "root": created["created_root"],
            "provider": "notion-consented-meeting-note",
            "input_digest": hashlib.sha256(raw_input).hexdigest(),
            "input_bytes": len(raw_input),
            "data_class": "internal-text",
        }
        with pytest.raises(MachineTransportError, match="live BABOOM consent"):
            execution.request("POST", "/api/universal/connector-delegation", request)

        baboom = UniversalRuntimeClient(descriptor_path, provider)
        baboom.bind_agent_session(
            runtime="baboom",
            external_session_id=presence_external_id,
            device_credential_provider=presence_credential,
        )
        baboom.renew_runtime_presence()
        consent = baboom.request(
            "POST", "/api/universal/baboom-meeting-notes", {"action": "start"}
        )
        delegation = execution.request(
            "POST", "/api/universal/connector-delegation", request
        )
        assert delegation["meeting_note_publication"].startswith(
            "app:baboom-meeting-note-publication:binding:"
        )
        binding = find_baboom_meeting_note_publication(
            server.universal_store.snapshot(),
            server.universal_registry.baboom_meeting_note_publication_protocol,
            delegation["delegation"],
        )
        assert binding is not None
        assert binding.meeting_notes_root == consent["meeting_notes"]
        assert "Founder decision" not in repr(server.universal_store.snapshot().cells)

        baboom.request(
            "POST", "/api/universal/baboom-meeting-notes", {"action": "stop"}
        )
        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-consented-notion-founder",
        )
        founder.request(
            "POST",
            "/api/universal/connector-delegation-approve",
            {"delegation": delegation["delegation"]},
        )
        with pytest.raises(MachineTransportError, match="live BABOOM consent"):
            execution.request(
                "POST",
                "/api/universal/connector-delegation-grant",
                {"delegation": delegation["delegation"]},
            )
    finally:
        server.close()


def test_baboom_connector_failure_blocks_then_resumes_exact_work(tmp_path):
    descriptor_path = tmp_path / "baboom-connector-recovery-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"r" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _bind_runtime_device(
        server, reference, runtime="baboom-execution"
    )
    external_session_id = "baboom-connector-recovery-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "BABOOM connector recovery court",
            "description": "Block only from one failed connector receipt.",
            "priority": 80,
            "external_key": "baboom-connector-recovery-court",
            "references": {
                "scope": server.universal_registry.map.domains["connectors"],
            },
            "structured_references": {
                "requirements": {"court": "connector-recovery"},
                "required-capabilities": ["calendar"],
            },
            "x": 840,
            "y": 540,
        })
        execution = UniversalRuntimeClient(descriptor_path, provider)
        execution.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert execution.claim_next_work()["work"]["root"] == created["created_root"]
        raw_input = b'{"limit":2}'
        delegation = execution.request("POST", "/api/universal/connector-delegation", {
            "root": created["created_root"],
            "provider": "teams-meetings",
            "input_digest": hashlib.sha256(raw_input).hexdigest(),
            "input_bytes": len(raw_input),
            "data_class": "internal-metadata",
        })
        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-connector-recovery-founder-court",
        )
        founder.request("POST", "/api/universal/connector-delegation-approve", {
            "delegation": delegation["delegation"],
        })
        grant = execution.request("POST", "/api/universal/connector-delegation-grant", {
            "delegation": delegation["delegation"],
        })
        failed = execution.request("POST", "/api/universal/connector-delegation-receipt", {
            "grant": grant["grant"],
            "capability": grant["capability"],
            "outcome": "failed",
            "output_digest": hashlib.sha256(b"").hexdigest(),
            "output_bytes": 0,
            "error_code": "connector-timeout",
        })
        assert failed["history_root"] == ""
        assert failed["status"]["counts"]["claimed"] == 1
        assert failed["status"]["connector_execution"]["failed"] == 1
        recovered = execution.request(
            "POST",
            "/api/universal/connector-delegation-recover",
            {"receipt": failed["receipt"]},
        )
        assert recovered["receipt"] == failed["receipt"]
        assert recovered["history_root"].startswith("state-event:")
        assert recovered["status"]["counts"]["blocked"] == 1
        resumed = execution.request(
            "POST",
            "/api/universal/connector-delegation-resume",
            {"receipt": failed["receipt"]},
        )
        assert resumed["receipt"] == failed["receipt"]
        assert resumed["history_root"].startswith("state-event:")
        assert resumed["status"]["counts"]["claimed"] == 1
        with pytest.raises(MachineTransportError, match="already consumed"):
            execution.request(
                "POST",
                "/api/universal/connector-delegation-recover",
                {"receipt": failed["receipt"]},
            )
    finally:
        server.close()


def test_founder_machine_session_binds_enrolled_device_to_baboom(tmp_path):
    descriptor_path = tmp_path / "founder-device-binding-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"f" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _register_runtime_device(server, reference)
    external_session_id = "baboom-founder-binding-court"

    def provider_for(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        with pytest.raises(MachineTransportError, match="bound founder"):
            founder.bind_runtime_device_custody(
                runtime="baboom", custody_root=custody_root
            )

        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="founder-device-binding-court",
        )
        bound = founder.bind_runtime_device_custody(
            runtime="baboom", custody_root=custody_root
        )
        assert bound["catalog_entry"] == (
            "app:agent-body-catalog:entry:baboom"
        )
        assert bound["agent_body"] == "app:agent-body:baboom"
        assert bound["custody_root"] == custody_root

        baboom = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = baboom.bind_agent_session(
            runtime="baboom",
            external_session_id=external_session_id,
            device_credential_provider=provider_for,
        )
        assert enrolled["agent_body"] == "app:agent-body:baboom"
        with pytest.raises(MachineTransportError, match="device-proof"):
            founder.renew_runtime_presence()
        lease = baboom.renew_runtime_presence()
        assert lease["agent_session"] == enrolled["agent_session"]
        assert lease["runtime"] == "baboom"
        context = baboom.request("GET", "/api/universal/baboom-context")
        assert context["presence"]["baboom_connected"] is True
        assert context["device"] == {
            "enrollment_handoff_available": True,
            "current_runtime_proven": True,
            "active_baboom_devices": 1,
            "native_identity_provider_configured": False,
            "issued_cloud_sessions": 0,
            "remote_gateway_serving": False,
        }
        with pytest.raises(MachineTransportError, match="founder machine"):
            baboom.bind_runtime_device_custody(
                runtime="baboom", custody_root=custody_root
            )
    finally:
        server.close()


def test_baboom_native_transport_reads_the_bounded_lens_and_records_one_signal(tmp_path):
    descriptor_path = tmp_path / "baboom-native-host-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"n" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    key, reference = _runtime_device_key()
    custody_root = _register_runtime_device(server, reference)
    external_session_id = "baboom-native-host-transport-court"

    def device_credential(challenge):
        return _device_credential(
            key, custody_root, challenge, external_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        founder.bind_agent_session(
            runtime="founder-machine",
            external_session_id="baboom-native-host-founder-court",
        )
        founder.bind_runtime_device_custody(
            runtime="baboom", custody_root=custody_root
        )
        baboom = UniversalRuntimeClient(descriptor_path, provider)
        enrolled = baboom.bind_agent_session(
            runtime="baboom",
            external_session_id=external_session_id,
            device_credential_provider=device_credential,
        )
        lease = baboom.renew_runtime_presence()
        context = baboom.baboom_context()
        signal = baboom.record_baboom_steward_signal(
            fingerprint=hashlib.sha256(b"baboom-native-host-court").hexdigest(),
            source="baboom-native-host",
            summary="Blocked governed work requires founder review.",
        )

        assert lease["agent_session"] == enrolled["agent_session"]
        assert context["cell_native"] is True
        assert context["context_lens"] == "app:baboom-context:v3"
        assert context["presence"]["baboom_connected"] is True
        assert signal["agent_session"] == enrolled["agent_session"]
        assert signal["signal"].startswith("app:baboom-steward-signal:")
    finally:
        server.close()


def test_device_handoff_work_is_one_graph_policy_bound_to_target_custody(tmp_path):
    descriptor_path = tmp_path / "device-handoff-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"h" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    source_key, source_reference = _runtime_device_key()
    target_key, target_reference = _runtime_device_key()
    source_custody = _bind_runtime_device(server, source_reference)
    target_custody = _bind_runtime_device(server, target_reference)
    source_session_id = "court-device-handoff-source"
    target_session_id = "court-device-handoff-target"

    def source_credential(challenge):
        return _device_credential(
            source_key, source_custody, challenge, source_session_id
        )

    def target_credential(challenge):
        return _device_credential(
            target_key, target_custody, challenge, target_session_id
        )

    try:
        source = UniversalRuntimeClient(descriptor_path, provider)
        target = UniversalRuntimeClient(descriptor_path, provider)
        source.bind_agent_session(
            runtime="baboom",
            external_session_id=source_session_id,
            device_credential_provider=source_credential,
        )
        target.bind_agent_session(
            runtime="baboom",
            external_session_id=target_session_id,
            device_credential_provider=target_credential,
        )
        source.renew_runtime_presence()
        target.renew_runtime_presence()

        description = "Review the active model coordination issue and draft next actions."
        handoff_key = hashlib.sha256(b"court-device-handoff").hexdigest()
        payload_digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
        created = source.create_device_handoff_work(
            title="Targeted device handoff court",
            description=description,
            priority=50,
            scope="gm:domain:orchestration",
            target_device_custody=target_custody,
            handoff_key=handoff_key,
            payload_digest=payload_digest,
            expires_at=time.time() + 600,
            x=420.0,
            y=260.0,
        )
        assert created["source_device_custody"] == source_custody
        handoff = read_work_handoff(
            server.universal_store.snapshot(),
            server.universal_registry.work_handoff_protocol,
            created["handoff_root"],
        )
        assert handoff.target_device_custody_root == target_custody
        assert handoff.payload_digest == payload_digest
        assert handoff.state_root == (
            server.universal_registry.work_handoff_protocol.states["prepared"]
        )
        source_handoffs = source.list_device_handoffs()
        target_handoffs = target.list_device_handoffs()
        assert source_handoffs["device_custody"] == source_custody
        assert target_handoffs["device_custody"] == target_custody
        assert len(source_handoffs["items"]) == len(target_handoffs["items"]) == 1
        assert source_handoffs["items"][0]["direction"] == "outgoing"
        assert target_handoffs["items"][0]["direction"] == "incoming"
        assert source_handoffs["items"][0]["handoff_state"] == "prepared"
        assert target_handoffs["items"][0]["claimable"] is False
        assert target_handoffs["items"][0]["description"] == description
        with pytest.raises(MachineTransportError, match="reserved"):
            target.claim_work(created["work_root"])

        receipt_digest = hashlib.sha256(
            b"court graph delivery receipt"
        ).hexdigest()
        receipt = source.record_device_handoff_receipt(
            handoff_key=handoff_key,
            kind="delivery",
            receipt_digest=receipt_digest,
        )
        assert receipt["handoff_root"] == created["handoff_root"]
        delivered_source = source.list_device_handoffs()["items"]
        delivered_target = target.list_device_handoffs()["items"]
        assert delivered_source[0]["direction"] == "outgoing"
        assert delivered_source[0]["handoff_state"] == "delivered"
        assert delivered_source[0]["claimable"] is False
        assert delivered_target[0]["direction"] == "incoming"
        assert delivered_target[0]["handoff_state"] == "delivered"
        assert delivered_target[0]["claimable"] is True
        with pytest.raises(MachineTransportError, match="reserved"):
            source.claim_work(created["work_root"])
        assert source.claim_next_work()["claimed"] is False

        claimed = target.claim_work(created["work_root"])
        assert claimed["work"]["root"] == created["work_root"]
        assert claimed["work"]["claimant_session"] == target.agent_session_root
        current = read_work_handoff(
            server.universal_store.snapshot(),
            server.universal_registry.work_handoff_protocol,
            created["handoff_root"],
        )
        assert current.state_root == (
            server.universal_registry.work_handoff_protocol.states["delivered"]
        )
        handoff_atoms = b"\n".join(
            cell.atom for cell in server.universal_store.snapshot().cells.values()
            if cell.id.startswith("work-handoff")
        )
        assert description.encode("utf-8") not in handoff_atoms
        assert payload_digest.encode("ascii") in handoff_atoms
    finally:
        server.close()


def test_baboom_device_handoff_resolves_an_opaque_active_device_selector(tmp_path):
    descriptor_path = tmp_path / "device-selector-handoff-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"s" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    source_key, source_reference = _runtime_device_key()
    target_key, target_reference = _runtime_device_key()
    source_custody = _bind_runtime_device(
        server, source_reference, runtime="baboom-execution"
    )
    target_custody = _bind_runtime_device(
        server, target_reference, runtime="baboom-execution"
    )
    source_session_id = "court-device-selector-source"
    target_session_id = "court-device-selector-target"

    def source_credential(challenge):
        return _device_credential(
            source_key, source_custody, challenge, source_session_id
        )

    def target_credential(challenge):
        return _device_credential(
            target_key, target_custody, challenge, target_session_id
        )

    try:
        source = UniversalRuntimeClient(descriptor_path, provider)
        target = UniversalRuntimeClient(descriptor_path, provider)
        source.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=source_session_id,
            device_credential_provider=source_credential,
        )
        target.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=target_session_id,
            device_credential_provider=target_credential,
        )
        source.renew_runtime_presence()
        target.renew_runtime_presence()
        target_ref = universal_application_module._founder_device_custody_ref(
            target_custody
        )
        description = "Draft the next governed action for the active Workshop issue."
        handoff_key = hashlib.sha256(b"court-device-selector-handoff").hexdigest()
        created = source.create_device_handoff_work_for_device_ref(
            title="Selected device handoff court",
            description=description,
            priority=45,
            scope="gm:domain:orchestration",
            target_device_ref=target_ref,
            handoff_key=handoff_key,
            payload_digest=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            expires_at=time.time() + 600,
            x=460.0,
            y=300.0,
        )

        handoff = read_work_handoff(
            server.universal_store.snapshot(),
            server.universal_registry.work_handoff_protocol,
            created["handoff_root"],
        )
        handoff_atoms = b"\n".join(
            cell.atom for cell in server.universal_store.snapshot().cells.values()
            if cell.id.startswith("work-handoff")
        )
        assert handoff.source_device_custody_root == source_custody
        assert handoff.target_device_custody_root == target_custody
        assert target_ref.encode("utf-8") not in handoff_atoms
        assert target_custody.encode("utf-8") not in handoff_atoms
        with pytest.raises(MachineTransportError, match="unavailable or ambiguous"):
            source.create_device_handoff_work_for_device_ref(
                title="Self handoff must fail",
                description=description,
                priority=45,
                scope="gm:domain:orchestration",
                target_device_ref=universal_application_module._founder_device_custody_ref(
                    source_custody
                ),
                handoff_key=hashlib.sha256(b"court-device-selector-self").hexdigest(),
                payload_digest=hashlib.sha256(description.encode("utf-8")).hexdigest(),
                expires_at=time.time() + 600,
                x=470.0,
                y=300.0,
            )
    finally:
        server.close()


def test_claimed_work_transfers_between_baboom_devices_without_copying_work(tmp_path):
    descriptor_path = tmp_path / "work-claim-transfer-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"t" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    source_key, source_reference = _runtime_device_key()
    target_key, target_reference = _runtime_device_key()
    source_custody = _bind_runtime_device(
        server, source_reference, runtime="baboom-execution"
    )
    target_custody = _bind_runtime_device(
        server, target_reference, runtime="baboom-execution"
    )
    source_session_id = "court-claim-transfer-source"
    target_session_id = "court-claim-transfer-target"

    def source_credential(challenge):
        return _device_credential(
            source_key, source_custody, challenge, source_session_id
        )

    def target_credential(challenge):
        return _device_credential(
            target_key, target_custody, challenge, target_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "Transfer one existing BIM coordination review",
            "description": "Review the held coordination note without copying it.",
            "priority": 75,
            "x": 420.0,
            "y": 280.0,
        })
        source = UniversalRuntimeClient(descriptor_path, provider)
        target = UniversalRuntimeClient(descriptor_path, provider)
        source.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=source_session_id,
            device_credential_provider=source_credential,
        )
        target.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=target_session_id,
            device_credential_provider=target_credential,
        )
        source.renew_runtime_presence()
        target.renew_runtime_presence()
        source_claim = source.claim_work(created["created_root"])
        assert source_claim["work"]["root"] == created["created_root"]
        target_device_ref = universal_application_module._founder_device_custody_ref(
            target_custody
        )

        transfer_key = hashlib.sha256(b"court-work-claim-transfer").hexdigest()
        confirmation_digest = hashlib.sha256(
            b"founder confirmed exact target device"
        ).hexdigest()
        with pytest.raises(MachineTransportError, match="not registered"):
            target.claim_work_claim_transfer(transfer_key)
        initiated = source.initiate_work_claim_transfer(
            work_root=created["created_root"],
            target_device_ref=target_device_ref,
            transfer_key=transfer_key,
            confirmation_digest=confirmation_digest,
            expires_at=time.time() + 600,
        )
        assert initiated["state"] == "released"
        assert source.claim_next_work()["claimed"] is False

        source_items = source.list_work_claim_transfers()["items"]
        target_items = target.list_work_claim_transfers()["items"]
        assert source_items == [{
            "transfer_key": transfer_key,
            "direction": "outgoing",
            "issued_at": source_items[0]["issued_at"],
            "expires_at": source_items[0]["expires_at"],
            "state": "released",
            "claimable": False,
        }]
        assert target_items == [{
            "transfer_key": transfer_key,
            "direction": "incoming",
            "issued_at": target_items[0]["issued_at"],
            "expires_at": target_items[0]["expires_at"],
            "state": "released",
            "claimable": True,
        }]
        assert {
            key for item in target_items for key in item
        } == {
            "transfer_key", "direction", "issued_at", "expires_at",
            "state", "claimable",
        }
        claimed = target.claim_work_claim_transfer(transfer_key)
        assert claimed["work"]["root"] == created["created_root"]
        assert claimed["work"]["claimant_session"] == target.agent_session_root
        with pytest.raises(MachineTransportError, match="not claimable"):
            source.claim_work_claim_transfer(transfer_key)

        transfer = read_work_claim_transfer(
            server.universal_store.snapshot(),
            server.universal_registry.work_claim_transfer_protocol,
            "work-claim-transfer:sha256:" + transfer_key,
        )
        assert transfer.work_root == created["created_root"]
        assert transfer.source_agent_session_root == source.agent_session_root
        assert transfer.target_device_custody_root == target_custody
        assert transfer.state_root == (
            server.universal_registry.work_claim_transfer_protocol.states["claimed"]
        )
        transfer_atoms = b"\n".join(
            cell.atom for cell in server.universal_store.snapshot().cells.values()
            if cell.id.startswith("work-claim-transfer")
        )
        assert b"Review the held coordination note" not in transfer_atoms
        assert b"Transfer one existing BIM coordination review" not in transfer_atoms
        assert confirmation_digest.encode("ascii") in transfer_atoms
    finally:
        server.close()


def test_prepared_work_claim_transfer_recovers_without_an_unattached_reservation(
    tmp_path, monkeypatch,
):
    descriptor_path = tmp_path / "work-claim-transfer-retry-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"u" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    source_key, source_reference = _runtime_device_key()
    target_key, target_reference = _runtime_device_key()
    source_custody = _bind_runtime_device(
        server, source_reference, runtime="baboom-execution"
    )
    target_custody = _bind_runtime_device(
        server, target_reference, runtime="baboom-execution"
    )
    source_session_id = "court-claim-transfer-retry-source"
    target_session_id = "court-claim-transfer-retry-target"

    def source_credential(challenge):
        return _device_credential(
            source_key, source_custody, challenge, source_session_id
        )

    def target_credential(challenge):
        return _device_credential(
            target_key, target_custody, challenge, target_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "Resume the same BIM coordination review",
            "description": "Keep this review on one Work root after a release fault.",
            "priority": 75,
            "x": 420.0,
            "y": 280.0,
        })
        source = UniversalRuntimeClient(descriptor_path, provider)
        target = UniversalRuntimeClient(descriptor_path, provider)
        source.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=source_session_id,
            device_credential_provider=source_credential,
        )
        target.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=target_session_id,
            device_credential_provider=target_credential,
        )
        source.renew_runtime_presence()
        target.renew_runtime_presence()
        source.claim_work(created["created_root"])

        transfer_key = hashlib.sha256(b"court-work-claim-transfer-retry").hexdigest()
        confirmation_digest = hashlib.sha256(
            b"founder confirmed retry target"
        ).hexdigest()
        target_device_ref = universal_application_module._founder_device_custody_ref(
            target_custody
        )
        original_transition = universal_application_module.transition_universal_governed_work

        def fail_release(*args, **kwargs):
            if len(args) >= 4 and args[3] == "release":
                raise RuntimeError("court release interruption")
            return original_transition(*args, **kwargs)

        monkeypatch.setattr(
            universal_application_module,
            "transition_universal_governed_work",
            fail_release,
        )
        with pytest.raises(MachineTransportError, match="court release interruption"):
            source.initiate_work_claim_transfer(
                work_root=created["created_root"],
                target_device_ref=target_device_ref,
                transfer_key=transfer_key,
                confirmation_digest=confirmation_digest,
                expires_at=time.time() + 600,
            )
        monkeypatch.setattr(
            universal_application_module,
            "transition_universal_governed_work",
            original_transition,
        )

        prepared = read_work_claim_transfer(
            server.universal_store.snapshot(),
            server.universal_registry.work_claim_transfer_protocol,
            "work-claim-transfer:sha256:" + transfer_key,
        )
        assert prepared.state_root == (
            server.universal_registry.work_claim_transfer_protocol.states["prepared"]
        )
        bound = universal_application_module._governed_work_claim_transfer_policy(
            server.universal_store.snapshot(),
            server.universal_registry,
            created["created_root"],
        )
        assert bound is not None
        assert bound.root_id == prepared.root_id

        retried = source.initiate_work_claim_transfer(
            work_root=created["created_root"],
            target_device_ref=target_device_ref,
            transfer_key=transfer_key,
            confirmation_digest=confirmation_digest,
            expires_at=time.time() + 900,
        )
        assert retried["state"] == "released"
        assert retried["reused"] is False
        assert retried["release_receipt_root"] in server.universal_store.snapshot().cells

        repeated = source.initiate_work_claim_transfer(
            work_root=created["created_root"],
            target_device_ref=target_device_ref,
            transfer_key=transfer_key,
            confirmation_digest=confirmation_digest,
            expires_at=time.time() + 1_200,
        )
        assert repeated["state"] == "released"
        assert repeated["reused"] is True
        assert repeated["release_receipt_root"] == retried["release_receipt_root"]

        claimed = target.claim_work_claim_transfer(transfer_key)
        assert claimed["work"]["root"] == created["created_root"]
    finally:
        server.close()


def test_source_cancellation_restores_normal_claimability_without_copying_work(tmp_path):
    descriptor_path = tmp_path / "work-claim-transfer-cancel-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"v" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    source_key, source_reference = _runtime_device_key()
    target_key, target_reference = _runtime_device_key()
    source_custody = _bind_runtime_device(
        server, source_reference, runtime="baboom-execution"
    )
    target_custody = _bind_runtime_device(
        server, target_reference, runtime="baboom-execution"
    )
    source_session_id = "court-claim-transfer-cancel-source"
    target_session_id = "court-claim-transfer-cancel-target"

    def source_credential(challenge):
        return _device_credential(
            source_key, source_custody, challenge, source_session_id
        )

    def target_credential(challenge):
        return _device_credential(
            target_key, target_custody, challenge, target_session_id
        )

    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        created = founder.request("POST", "/api/universal/work", {
            "title": "Recover one BIM coordination review after continuation cancellation",
            "description": "Cancel a device continuation without copying this Work.",
            "priority": 75,
            "x": 420.0,
            "y": 280.0,
        })
        source = UniversalRuntimeClient(descriptor_path, provider)
        target = UniversalRuntimeClient(descriptor_path, provider)
        source.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=source_session_id,
            device_credential_provider=source_credential,
        )
        target.bind_agent_session(
            runtime="baboom-execution",
            external_session_id=target_session_id,
            device_credential_provider=target_credential,
        )
        source.renew_runtime_presence()
        target.renew_runtime_presence()
        source.claim_work(created["created_root"])
        transfer_key = hashlib.sha256(
            b"court-work-claim-transfer-cancellation"
        ).hexdigest()
        confirmation_digest = hashlib.sha256(
            b"founder confirmed target for cancellation court"
        ).hexdigest()
        cancellation_digest = hashlib.sha256(
            b"founder confirmed cancellation"
        ).hexdigest()
        target_device_ref = universal_application_module._founder_device_custody_ref(
            target_custody
        )
        released = source.initiate_work_claim_transfer(
            work_root=created["created_root"],
            target_device_ref=target_device_ref,
            transfer_key=transfer_key,
            confirmation_digest=confirmation_digest,
            expires_at=time.time() + 600,
        )
        assert released["state"] == "released"

        cancelled = source.cancel_work_claim_transfer(
            transfer_key=transfer_key,
            cancellation_digest=cancellation_digest,
        )
        assert cancelled["state"] == "cancelled"
        assert cancelled["reused"] is False
        assert cancelled["cancellation_receipt_root"] in server.universal_store.snapshot().cells
        repeated = source.cancel_work_claim_transfer(
            transfer_key=transfer_key,
            cancellation_digest=cancellation_digest,
        )
        assert repeated["state"] == "cancelled"
        assert repeated["reused"] is True
        assert repeated["cancellation_receipt_root"] == cancelled["cancellation_receipt_root"]

        source_items = source.list_work_claim_transfers()["items"]
        assert source_items[0]["state"] == "cancelled"
        assert source_items[0]["claimable"] is False
        with pytest.raises(MachineTransportError, match="not claimable"):
            target.claim_work_claim_transfer(transfer_key)
        restored = target.claim_work(created["created_root"])
        assert restored["claimed"] is True
        assert restored["work"]["root"] == created["created_root"]
        assert restored["work"]["claimant_session"] == target.agent_session_root

        transfer = read_work_claim_transfer(
            server.universal_store.snapshot(),
            server.universal_registry.work_claim_transfer_protocol,
            "work-claim-transfer:sha256:" + transfer_key,
        )
        assert transfer.state_root == (
            server.universal_registry.work_claim_transfer_protocol.states["cancelled"]
        )
        assert universal_application_module._governed_work_claim_transfer_policy(
            server.universal_store.snapshot(),
            server.universal_registry,
            created["created_root"],
        ) is None
        transfer_atoms = b"\n".join(
            cell.atom for cell in server.universal_store.snapshot().cells.values()
            if cell.id.startswith("work-claim-transfer")
        )
        assert b"Cancel a device continuation" not in transfer_atoms
        assert b"Recover one BIM coordination review" not in transfer_atoms
        assert cancellation_digest.encode("ascii") in transfer_atoms
    finally:
        server.close()


def test_machine_workshop_admission_rejects_protected_content_without_commit(tmp_path):
    descriptor_path = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"p" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        before = read_deliberation_space(
            server.universal_store.snapshot(),
            server.universal_registry.deliberation_protocol,
            server.universal_registry.workshop_root,
        )
        revision_before = server.universal_store.revision
        entry_template = {
            "category": "plan",
            "refs": [server.universal_registry.application_root],
            "evidence": [],
            "recipients": [],
            "reply_to": None,
            "created_at": "2026-07-20T10:00:00+00:00",
        }
        for index, protected_text in enumerate((
            "Plan token=context-secret must not enter the Workshop graph.",
            r"Review C:\\Users\\fargaly\\00.ARCHUB\\20.CLIENTS\\model.rvt",
            "Bearer abcdefghijklmnopqrstuvwxyz",
        ), start=1):
            with pytest.raises(MachineTransportError, match="protected content"):
                client.request("POST", "/api/universal/workshop", {
                    **entry_template,
                    "text": protected_text,
                    "idempotency_key": f"court:workshop:protected:{index}",
                })
            current = read_deliberation_space(
                server.universal_store.snapshot(),
                server.universal_registry.deliberation_protocol,
                server.universal_registry.workshop_root,
            )
            assert server.universal_store.revision == revision_before
            assert current.entry_roots == before.entry_roots

        accepted = client.request("POST", "/api/universal/workshop", {
            **entry_template,
            "text": "Record the machine-transport Workshop admission court.",
            "idempotency_key": "court:workshop:admission:accepted",
        })
        assert accepted["ok"] is True
        assert server.universal_store.revision > revision_before
        after = read_deliberation_space(
            server.universal_store.snapshot(),
            server.universal_registry.deliberation_protocol,
            server.universal_registry.workshop_root,
        )
        assert after.entry_roots == (accepted["root"],)
    finally:
        server.close()


def test_machine_transport_is_authenticated_replay_safe_and_cell_backed(tmp_path):
    descriptor_path = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"p" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    client = UniversalRuntimeClient(descriptor_path, provider)
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        assert descriptor["status"] == "active"
        assert descriptor["application_root"] \
            == server.universal_registry.application_root
        assert descriptor["agent_session_root"] \
            == server.universal_registry.agent_body.session.root_id
        assert descriptor["workshop_root"] \
            == server.universal_registry.workshop_root
        assert descriptor["work_registry_root"] \
            == server.universal_registry.governed_work_registry_root
        assert "secret" not in descriptor
        assert "token" not in descriptor
        pipe_dacl = server.machine_transport.pipe_security_sddl
        assert "(D;;FA;;;NU)" in pipe_dacl
        assert "(D;;FA;;;AN)" in pipe_dacl
        assert "(A;;FA;;;SY)" in pipe_dacl
        assert "S-1-5-5-" in pipe_dacl

        initial = client.request(
            "GET", "/api/universal/work", request_id="1" * 32
        )
        assert initial["application"] \
            == server.universal_registry.application_root
        assert initial["agent_session"] \
            == server.universal_registry.agent_body.session.root_id
        assert initial["registry"] \
            == server.universal_registry.governed_work_registry_root
        assert initial["items"] == []
        assert initial["workshop_status"]["root"] \
            == server.universal_registry.workshop_root
        assert initial["workshop_status"]["entry_count"] == 0
        assert initial["workshop_status"]["categories"]
        assert initial["workshop_status"]["phases"]
        assert initial["workshop_status"]["requirements"]
        workshop = client.request("GET", "/api/universal/workshop")
        assert workshop["workshop"] == server.universal_registry.workshop_root
        assert workshop["entries"] == []
        assert workshop["categories"] \
            == dict(server.universal_registry.workshop_category_roots)
        handoff_status = client.browser_handoff_status()
        assert handoff_status["application"] \
            == server.universal_registry.application_root
        assert handoff_status["server_url"] == server.url
        assert handoff_status["supported"] is True
        assert handoff_status["one_use_route"] \
            == "POST /api/universal/browser-handoff"
        browser_handoff = client.browser_handoff()
        assert browser_handoff["application"] \
            == server.universal_registry.application_root
        assert browser_handoff["server_url"] == server.url
        assert browser_handoff["document_url"].startswith(
            server.url + "/?bootstrap="
        )
        assert browser_handoff["one_use"] is True
        assert browser_handoff["session_root"] == server.browser_session_root
        with urllib.request.urlopen(
            browser_handoff["document_url"], timeout=30
        ) as response:
            page = response.read().decode("utf-8")
        assert response.headers["Cache-Control"] == "no-store"
        assert "class=\"archhub-app\"" in page
        with pytest.raises(urllib.error.HTTPError) as replay:
            urllib.request.urlopen(browser_handoff["document_url"], timeout=30)
        assert replay.value.code == 403
        gate = client.request("POST", "/api/universal/workshop-gate", {
            "ref": server.universal_registry.application_root,
            "phase": "claim",
        })
        assert gate["allowed"] is False
        assert gate["ref"] == server.universal_registry.application_root
        assert gate["phase_root"] \
            == server.universal_registry.workshop_phase_roots["claim"]
        assert gate["missing"]
        entry_body = {
            "category": "plan",
            "text": "Record the machine-transport Workshop admission court.",
            "refs": [server.universal_registry.application_root],
            "evidence": [],
            "recipients": [],
            "reply_to": None,
            "idempotency_key": "court:workshop:plan:1",
            "created_at": "2026-07-18T10:00:00+00:00",
        }
        appended = client.request(
            "POST", "/api/universal/workshop", entry_body
        )
        assert appended["ok"] is True
        assert appended["workshop"] \
            == server.universal_registry.workshop_root
        assert appended["kind"] == "plan"
        assert appended["refs"] == [
            server.universal_registry.application_root
        ]
        workshop_after = client.request("GET", "/api/universal/workshop")
        assert [item["root"] for item in workshop_after["entries"]] \
            == [appended["root"]]
        founder_workshop_report = client.founder_workshop_report()
        assert set(founder_workshop_report) == {
            "application", "agent_session", "workshop", "projection",
            "revision", "count", "protected", "truncated", "entries",
        }
        assert founder_workshop_report["projection"] == (
            "founder-local-workshop-report"
        )
        assert founder_workshop_report["count"] == 1
        assert founder_workshop_report["protected"] == 0
        assert founder_workshop_report["entries"] == [{
            "sequence": 1,
            "kind": "plan",
            "text": "Record the machine-transport Workshop admission court.",
            "created_at": "2026-07-18T10:00:00+00:00",
            "protected": False,
        }]
        founder_report_text = json.dumps(founder_workshop_report, sort_keys=True)
        assert "context-secret" not in founder_report_text
        assert appended["root"] not in founder_report_text
        founder_attention_briefing = client.founder_attention_briefing()
        assert set(founder_attention_briefing) == {
            "application", "agent_session", "projection", "revision", "focus",
            "open_obligations", "blocked_obligations", "protected", "truncated",
            "obligations",
        }
        assert founder_attention_briefing["projection"] == (
            "founder-local-attention-briefing"
        )
        assert founder_attention_briefing["focus"] == {
            "active": True,
            "label": "Current ArchHub focus",
            "reasons": ["Initial application focus"],
        }
        attention_text = json.dumps(founder_attention_briefing, sort_keys=True)
        assert "app:focus" not in attention_text
        assert server.universal_registry.authorization.session.root_id not in attention_text
        baboom_context = client.request(
            "GET", "/api/universal/baboom-context"
        )
        assert set(baboom_context) == {
            "cell_native", "context_lens", "revision", "work",
            "workshop", "attention", "presence", "activity", "meeting_notes",
            "device", "persona_form", "suggestion",
        }
        assert baboom_context["cell_native"] is True
        assert baboom_context["context_lens"] == "app:baboom-context:v3"
        assert baboom_context["work"] == {
            "total": 0,
            "open": 0,
            "claimed": 0,
            "blocked": 0,
            "review": 0,
        }
        assert baboom_context["workshop"]["entry_count"] == 1
        assert baboom_context["workshop"]["category_counts"]["plan"] == 1
        assert set(baboom_context["attention"]) == {
            "open_obligations", "blocked_obligations", "active_focus",
        }
        assert isinstance(baboom_context["attention"]["open_obligations"], int)
        assert isinstance(baboom_context["attention"]["blocked_obligations"], int)
        assert isinstance(baboom_context["attention"]["active_focus"], bool)
        assert baboom_context["presence"] == {
            "active_runtime_sessions": 0,
            "baboom_connected": False,
            "baboom_action_capability_active": False,
        }
        assert baboom_context["meeting_notes"] == {"active_sessions": 0}
        assert baboom_context["device"] == {
            "enrollment_handoff_available": True,
            "current_runtime_proven": False,
            "active_baboom_devices": 0,
            "native_identity_provider_configured": False,
            "issued_cloud_sessions": 0,
            "remote_gateway_serving": False,
        }
        assert baboom_context["suggestion"] == "No governed work needs action."
        context_text = json.dumps(baboom_context, sort_keys=True)
        assert "raw-workshop-text" not in context_text
        assert "context-secret" not in context_text
        assert appended["root"] not in context_text
        claim_gate = client.request("POST", "/api/universal/workshop-gate", {
            "ref": server.universal_registry.application_root,
            "phase": "claim",
        })
        assert claim_gate["allowed"] is True
        assert claim_gate["missing"] == []
        repeated = client.request(
            "POST", "/api/universal/workshop", entry_body
        )
        assert repeated["root"] == appended["root"]
        assert repeated["sequence"] == appended["sequence"]
        assert client.request("GET", "/api/universal/workshop")["entries"] \
            == workshop_after["entries"]
        assert initial["baboom"]["catalog_entry"] \
            == "app:agent-body-catalog:entry:baboom"
        assert initial["baboom"]["agent_body"] == "app:agent-body:baboom"
        assert initial["baboom"]["control"] == "app:agent-control:baboom"
        assert initial["baboom"]["runtime"] == "baboom"
        assert initial["baboom"]["action_capability"] == {
            "catalog_entry": "app:agent-body-catalog:entry:baboom-execution",
            "control": "app:agent-capability:baboom:execution-control",
            "credential_mode": "device-proof",
            "runtime_profile": "baboom-execution",
            "work_events": ["claim", "submit", "block", "resume", "release"],
        }
        assert initial["baboom"]["model_execution"] \
            == initial["model_execution"]

        with pytest.raises(MachineTransportError, match="replay"):
            client.request(
                "GET", "/api/universal/work", request_id="1" * 32
            )

        canvas = client.request("GET", "/api/universal/canvas")
        assert canvas["ok"] is True
        assert canvas["application"] \
            == server.universal_registry.application_root
        assert canvas["agent_session"] \
            == server.universal_registry.agent_body.session.root_id
        assert canvas["canvas_root"]
        assert canvas["application_root"] \
            == server.universal_registry.application_root
        assert canvas["nodes"]
        assert isinstance(canvas["wires"], list)
        assert canvas["machine_projection"]["kind"] \
            == "bounded-canvas-summary"
        assert canvas["machine_projection"]["node_count"] >= len(canvas["nodes"])
        assert canvas["machine_projection"]["wire_count"] >= len(canvas["wires"])
        revision_before_unbound_claim = server.universal_store.revision
        with pytest.raises(
            MachineTransportError,
            match="(?:bound runtime Agent Session|proof is invalid)",
        ):
            client.request("POST", "/api/universal/work-next", {})
        assert server.universal_store.revision == revision_before_unbound_claim

        brain_root = server.universal_registry.map.domains["brain"]
        created = client.request("POST", "/api/universal/work", {
            "title": "Move Brain work authority into the graph",
            "description": "One writer, one registry, one relation authority",
            "priority": 100,
            "external_key": "active-work:cell-migration",
            "references": {"scope": brain_root},
            "structured_references": {
                "requirements": {
                    "gate": {"kind": "pytest", "spec": {"path": "tests"}},
                    "owner": "founder",
                },
                "required-capabilities": ["python", "governance"],
            },
            "x": 720,
            "y": 480,
        })
        assert created["created_root"].startswith("assembly-instance:")
        assert created["membership_wire"] in (
            server.universal_store.snapshot().cells
        )

        projected = client.request("GET", "/api/universal/work")
        assert len(projected["items"]) == 1
        item = projected["items"][0]
        assert item["root"] == created["created_root"]
        assert item["membership_wire"] == created["membership_wire"]
        assert item["interfaces"]["title"]["value"] \
            == "Move Brain work authority into the graph"
        assert item["interfaces"]["scope"]["target"] == brain_root
        requirements_root = item["interfaces"]["requirements"]["target"]
        capabilities_root = item["interfaces"][
            "required-capabilities"
        ]["target"]
        assert read_value_graph(
            server.universal_store.snapshot(),
            server.universal_registry.value_graph_protocol,
            requirements_root,
        ) == {
            "gate": {"kind": "pytest", "spec": {"path": "tests"}},
            "owner": "founder",
        }
        assert read_value_graph(
            server.universal_store.snapshot(),
            server.universal_registry.value_graph_protocol,
            capabilities_root,
        ) == ["python", "governance"]
        baboom_context_after_work = client.request(
            "GET", "/api/universal/baboom-context"
        )
        assert baboom_context_after_work["work"] == {
            "total": 1,
            "open": 1,
            "claimed": 0,
            "blocked": 0,
            "review": 0,
        }
        assert (
            baboom_context_after_work["suggestion"]
            == "Offer the next approved governed work for claim."
        )
        assert "Move Brain work authority" not in json.dumps(
            baboom_context_after_work, sort_keys=True
        )

        agent_a = UniversalRuntimeClient(descriptor_path, provider)
        agent_b = UniversalRuntimeClient(descriptor_path, provider)
        external_a = "codex-session-not-for-persistence"
        enrolled_a = agent_a.bind_agent_session(
            runtime="codex", external_session_id=external_a
        )
        enrolled_b = agent_b.bind_agent_session(
            runtime="gemini", external_session_id="gemini-session-b"
        )
        session_a = enrolled_a["agent_session"]
        session_b = enrolled_b["agent_session"]
        assert session_a != session_b
        with pytest.raises(MachineTransportError, match="founder-local"):
            agent_a.founder_workshop_report()
        with pytest.raises(MachineTransportError, match="founder-local"):
            agent_a.founder_attention_briefing()
        runtime_plan = agent_a.request("POST", "/api/universal/workshop", {
            "category": "plan",
            "text": "Runtime session owns this Workshop entry.",
            "refs": [created["created_root"]],
            "evidence": [],
            "recipients": [],
            "reply_to": None,
            "idempotency_key": "court:workshop:runtime-plan:1",
            "created_at": "2026-07-18T11:00:00+00:00",
        })
        assert runtime_plan["actor"] == session_a
        assert runtime_plan["kind"] == "plan"
        runtime_workshop = agent_a.request("GET", "/api/universal/workshop")
        assert runtime_workshop["entries"][-1]["actor"] == session_a
        runtime_gate = agent_a.request(
            "POST", "/api/universal/workshop-gate",
            {"ref": created["created_root"], "phase": "claim"},
        )
        assert runtime_gate["allowed"] is True
        live_space = read_deliberation_space(
            server.universal_store.snapshot(),
            server.universal_registry.deliberation_protocol,
            server.universal_registry.workshop_root,
        )
        assert session_a in live_space.participant_roots
        old_session_token = agent_a._agent_session_token
        renewed_a = agent_a.renew_agent_session()
        assert renewed_a["agent_session"] == session_a
        assert agent_a._agent_session_token != old_session_token
        stale_agent_a = UniversalRuntimeClient(descriptor_path, provider)
        stale_agent_a.agent_session_root = session_a
        stale_agent_a._agent_session_token = old_session_token
        stale_agent_a._agent_session_expires_at = time.time() + 60
        with pytest.raises(MachineTransportError, match="proof is invalid"):
            stale_agent_a.request(
                "POST", "/api/universal/work-transition", {
                    "root": created["created_root"],
                    "event": "claim",
                    "evidence": "",
                }
            )
        snapshot = server.universal_store.snapshot()
        assert all(cell.atom != external_a.encode("utf-8") for cell in snapshot.cells.values())
        assert any(
            cell.atom == hashlib.sha256(external_a.encode("utf-8")).hexdigest().encode("utf-8")
            for cell in snapshot.cells.values()
        )

        revision_before_claim = server.universal_store.revision
        claimed = agent_a.request(
            "POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "claim",
                "evidence": "",
            }
        )
        assert claimed["status"]["counts"]["claimed"] == 1
        claimed_item = claimed["status"]["items"][0]
        assert claimed_item["claimant_session"] == session_a
        assert claimed_item["claimant_agent_body"] == (
            server.universal_registry.agent_body.body.root_id
        )
        binding_root = claimed_item["claim_binding"]
        assert binding_root.startswith("app:governed-work-claim-binding:")
        assert claimed["compliance_observation"]
        assert claimed["compliance_evidence"]
        assert claimed["revision"] == server.universal_store.revision
        assert server.universal_store.revision > revision_before_claim
        binding_members = read_relation(
            server.universal_store.snapshot(), binding_root, budget=32
        )
        binding_roles = server.universal_registry.governed_work_claim_binding_roles
        binding_values = {
            member.role_id: member.participant_id for member in binding_members
        }
        assert binding_values == {
            binding_roles["work"]: created["created_root"],
            binding_roles["agent-session"]: session_a,
            binding_roles["agent-body"]: (
                server.universal_registry.agent_body.body.root_id
            ),
            binding_roles["transition"]: binding_values[
                binding_roles["transition"]
            ],
        }
        assert server.universal_store.snapshot().cells[
            binding_values[binding_roles["transition"]]
        ].atom == b"claim"
        assert binding_root in {
            member.participant_id
            for member in read_relation(
                server.universal_store.snapshot(),
                server.universal_registry.governed_work_claim_binding_registry_root,
                budget=100_000,
            )
            if member.role_id == binding_roles["binding-member"]
        }
        with pytest.raises(
            MachineTransportError, match="only the claiming Agent Session"
        ):
            agent_b.request(
                "POST", "/api/universal/work-transition", {
                    "root": created["created_root"],
                    "event": "release",
                    "evidence": "",
                }
            )
        original_token = agent_a._agent_session_token
        agent_a._agent_session_token = "forged-session-capability"
        with pytest.raises(MachineTransportError, match="proof is invalid"):
            agent_a.request(
                "POST", "/api/universal/work-transition", {
                    "root": created["created_root"],
                    "event": "release",
                    "evidence": "",
                }
            )
        agent_a._agent_session_token = original_token
        released = agent_a.request(
            "POST", "/api/universal/work-transition", {
                "root": created["created_root"],
                "event": "release",
                "evidence": "",
            }
        )
        assert released["status"]["counts"]["open"] == 1
        assert released["status"]["items"][0]["claimant_session"] is None

        lower = client.request("POST", "/api/universal/work", {
            "title": "Second graph work",
            "priority": 10,
            "x": 920,
            "y": 480,
        })
        next_a = agent_a.claim_next_work()
        assert next_a["claimed"] is True
        assert next_a["work"]["root"] == created["created_root"]
        assert next_a["work"]["claimant_session"] == session_a
        next_b = agent_b.claim_next_work()
        assert next_b["claimed"] is True
        assert next_b["work"]["root"] == lower["created_root"]
        assert next_b["work"]["claimant_session"] == session_b
        repeated_a = agent_a.claim_next_work()
        assert repeated_a["claimed"] is True
        assert repeated_a["reused"] is True
        assert repeated_a["work"]["root"] == created["created_root"]
        agent_c = UniversalRuntimeClient(descriptor_path, provider)
        agent_c.bind_agent_session(
            runtime="cursor", external_session_id="cursor-session-c"
        )
        empty = agent_c.claim_next_work()
        assert empty["claimed"] is False
        assert empty["work"] is None
        for agent, root in (
            (agent_a, created["created_root"]),
            (agent_b, lower["created_root"]),
        ):
            agent.request("POST", "/api/universal/work-transition", {
                "root": root,
                "event": "release",
                "evidence": "",
            })

        expiring = UniversalRuntimeClient(descriptor_path, provider)
        expiring.bind_agent_session(
            runtime="cursor", external_session_id="cursor-expiry-court"
        )
        server._machine_agent_sessions[
            expiring.agent_session_root
        ]["expires_at"] = time.time() - 1.0
        with pytest.raises(MachineTransportError, match="capability expired"):
            expiring.request(
                "POST", "/api/universal/work-transition", {
                    "root": created["created_root"],
                    "event": "claim",
                    "evidence": "",
                }
            )

        canvas = server.project_interaction_canvas(
            server._resolve_browser_session(server.browser_session_token)
        )
        visible = {node["id"] for node in canvas["nodes"]}
        assert requirements_root in visible
        assert capabilities_root in visible
        assert session_a in visible
        assert session_b in visible

        binding_claim = agent_a.claim_next_work()
        binding_root = binding_claim["work"]["claim_binding"]
        binding_roles = server.universal_registry.governed_work_claim_binding_roles
        binding_members = read_relation(
            server.universal_store.snapshot(), binding_root, budget=32
        )
        body_incidence = next(
            member.incidence_id
            for member in binding_members
            if member.role_id == binding_roles["agent-body"]
        )
        snapshot = server.universal_store.snapshot()
        incidence = snapshot.cells[body_incidence]
        server.universal_store.commit(
            snapshot.revision,
            replace=(Cell(
                incidence.id,
                incidence.link0,
                agent_b.agent_session_root,
                incidence.atom,
            ),),
        )
        with pytest.raises(MachineTransportError, match="claim binding is missing"):
            client.request("GET", "/api/universal/work")

        wrong_provider = MemorySigningKeyProvider(
            "archhub.local.universal-runtime-pipe", b"x" * 32
        )
        with pytest.raises(MachineTransportError, match="signature"):
            UniversalRuntimeClient(
                descriptor_path, wrong_provider
            ).request("GET", "/api/universal/work")

        tampered = dict(descriptor)
        tampered["work_registry_root"] = "forged:registry"
        descriptor_path.write_text(
            json.dumps(tampered), encoding="utf-8"
        )
        with pytest.raises(MachineTransportError, match="signature"):
            client.request("GET", "/api/universal/work")
        descriptor_path.write_text(
            json.dumps(descriptor), encoding="utf-8"
        )
    finally:
        server.close()

    stopped = json.loads(descriptor_path.read_text(encoding="utf-8"))
    assert stopped["status"] == "stopped"
    assert stopped["runtime_id"] == descriptor["runtime_id"]
    with pytest.raises(MachineTransportError, match="not active"):
        client.request("GET", "/api/universal/work")
