"""Application court for signed runtime ownership and orderly handoff state."""
import http.cookiejar
import json
import threading
import urllib.request

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang.cell_attestations import read_court_attestation
from nodelang.cell_exclusive_ownership import (
    read_ownership,
    read_ownership_transition,
    verify_ownership_authority,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.universal_application import restore_universal_application
from nodelang.universal_cell import CellStore, InvalidCell
from nodelang.runtime_credentials import BrowserCredentialVault
from nodelang.runtime_gateway import RuntimeGateway


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"o" * 32)
    return provider


def test_persistent_server_records_signed_active_drain_release(tmp_path):
    path = tmp_path / "runtime-owner.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    ownership_root = server._runtime_ownership_root
    try:
        ownership = read_ownership(
            server.universal_store.snapshot(),
            registry.ownership_protocol,
            ownership_root,
        )
        assert ownership.resource_root == registry.application_root
        assert ownership.holder_root == server._runtime_holder_root
        assert ownership.generation == 1
        assert ownership.state_root == registry.ownership_protocol.states["active"]
        attestation = read_court_attestation(
            server.universal_store.snapshot(),
            registry.attestation_protocol,
            ownership.evidence_roots[0],
        )
        assert attestation.court_root == registry.runtime_ownership_court_root
        assert attestation.result_root == registry.attestation_protocol.states["passed"]
    finally:
        server.close()

    reopened = CellStore(path)
    ownerships = verify_ownership_authority(
        reopened.snapshot(), registry.ownership_protocol
    )
    assert len(ownerships) == 1
    released = ownerships[0]
    assert released.root_id == ownership_root
    assert released.state_root == registry.ownership_protocol.states["released"]
    transitions = tuple(
        read_ownership_transition(
            reopened.snapshot(), registry.ownership_protocol, root
        )
        for root in released.transition_roots
    )
    assert tuple(item.from_state_root for item in transitions) == (
        registry.ownership_protocol.states["active"],
        registry.ownership_protocol.states["draining"],
    )
    assert tuple(item.to_state_root for item in transitions) == (
        registry.ownership_protocol.states["draining"],
        registry.ownership_protocol.states["released"],
    )
    assert all(
        read_court_attestation(
            reopened.snapshot(),
            registry.attestation_protocol,
            item.evidence_root,
        ).result_root == registry.attestation_protocol.states["passed"]
        for item in transitions
    )
    reopened.close()


def test_in_memory_second_server_is_denied_before_graph_mutation():
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    first = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    try:
        revision = store.revision
        with pytest.raises(InvalidCell, match="already has a live runtime owner"):
            ApplicationServer(
                universal_store=store,
                universal_registry=registry,
            )
        assert store.revision == revision
    finally:
        first.close()


def test_worker_handoff_preserves_browser_session_and_advances_owner(tmp_path):
    path = tmp_path / "handoff.sqlite3"
    provider = _provider()
    credentials = BrowserCredentialVault(
        tmp_path / "browser.dpapi"
    ).load_or_create()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    first = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        browser_session_credentials=credentials,
    ).start()
    session_root = first.browser_session_root
    first_owner = first._runtime_ownership_root
    first.close(preserve_browser_session=True)

    reopened = CellStore(path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    second = ApplicationServer(
        universal_store=reopened,
        universal_registry=restored,
        browser_session_credentials=credentials,
    ).start()
    try:
        assert second.browser_session_root == session_root
        assert second.browser_session_token == credentials.token
        assert second._resolve_browser_session(credentials.token).session_root \
            == session_root
        ownerships = verify_ownership_authority(
            second.universal_store.snapshot(), restored.ownership_protocol
        )
        assert len(ownerships) == 2
        assert ownerships[0].root_id == first_owner
        assert ownerships[0].state_root \
            == restored.ownership_protocol.states["released"]
        assert ownerships[1].root_id == second._runtime_ownership_root
        assert ownerships[1].generation == 2
        assert ownerships[1].state_root \
            == restored.ownership_protocol.states["active"]
    finally:
        second.close()


def test_runtime_backend_generation_is_exact_signed_owner(tmp_path):
    descriptor_path = tmp_path / "runtime-backend-generation.json"
    provider = _provider()
    provider.add_key("archhub.local.universal-runtime-pipe", b"m" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=provider
    )
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
    ).start()
    try:
        backend = UniversalRuntimeClient(
            descriptor_path, provider
        ).runtime_backend_generation()
        ownership = read_ownership(
            server.universal_store.snapshot(),
            registry.ownership_protocol,
            backend.ownership_root,
        )
        assert backend.url == server.url
        assert backend.generation == ownership.generation == 1
        assert ownership.state_root == registry.ownership_protocol.states[
            "active"
        ]
    finally:
        server.close()


def test_stable_gateway_holds_browser_request_across_real_worker_handoff(tmp_path):
    path = tmp_path / "gateway-handoff.sqlite3"
    provider = _provider()
    credentials = BrowserCredentialVault(
        tmp_path / "browser-gateway.dpapi"
    ).load_or_create()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    first = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        browser_session_credentials=credentials,
    ).start()
    candidate = {"server": first}

    def verify(backend):
        assert candidate["server"].prove_runtime_backend_generation() == backend

    gateway = RuntimeGateway(
        admission_timeout=120.0,
        backend_timeout=60.0,
        activation_verifier=verify,
    ).start()
    second = None
    try:
        first_backend = first.prove_runtime_backend_generation()
        assert first_backend.generation == 1
        gateway.activate(first_backend)

        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookies)
        )
        response = opener.open(
            gateway.url + "/?bootstrap=" + first.browser_bootstrap_token,
            timeout=60,
        )
        assert response.status == 200
        assert response.headers["X-ArchHub-Runtime-Generation"] == "1"
        session_cookie = next(
            cookie for cookie in cookies if cookie.name == "ArchHub-Session"
        )
        assert session_cookie.value == credentials.token
        stable_url = gateway.url
        session_root = first.browser_session_root
        first_owner = first_backend.ownership_root

        assert gateway.gate.begin_drain(1, timeout=60) == first_backend
        held = {}
        entered = threading.Event()

        def request_during_handoff():
            entered.set()
            request = urllib.request.Request(
                stable_url + "/api/state",
                headers={"Cookie": "ArchHub-Session=" + credentials.token},
            )
            response = urllib.request.urlopen(request, timeout=120)
            held["generation"] = response.headers[
                "X-ArchHub-Runtime-Generation"
            ]
            held["payload"] = json.loads(response.read())

        waiting = threading.Thread(target=request_during_handoff)
        waiting.start()
        assert entered.wait(2)
        first.close(preserve_browser_session=True)

        reopened = CellStore(path)
        reopened, restored = restore_universal_application(
            resolve_map_path(), reopened, key_provider=provider
        )
        second = ApplicationServer(
            universal_store=reopened,
            universal_registry=restored,
            browser_session_credentials=credentials,
        ).start()
        candidate["server"] = second
        second_backend = second.prove_runtime_backend_generation()
        assert second_backend.generation == 2
        assert second.browser_session_root == session_root
        assert gateway.url == stable_url
        assert waiting.is_alive()
        gateway.activate(second_backend)
        waiting.join(120)
        assert not waiting.is_alive()
        assert held["generation"] == "2"
        assert held["payload"]["ok"] is True
        assert held["payload"]["universal_runtime_ownership"] \
            == second_backend.ownership_root

        ownerships = verify_ownership_authority(
            second.universal_store.snapshot(), restored.ownership_protocol
        )
        assert [item.generation for item in ownerships] == [1, 2]
        assert ownerships[0].root_id == first_owner
        assert ownerships[0].state_root \
            == restored.ownership_protocol.states["released"]
        assert ownerships[1].state_root \
            == restored.ownership_protocol.states["active"]
    finally:
        if second is not None:
            second.close()
        elif first.thread is not None and first.thread.is_alive():
            first.close()
        gateway.close()
