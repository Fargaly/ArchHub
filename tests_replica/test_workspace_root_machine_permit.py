"""A root-bound CDE write permit through the real machine transport.

The application admits workspace-roots/<id>/<path> only when the owner's pinned,
signed registry holds the root (never older than the hooks' last-good copy), the
runtime is one of the root's writers, AND the session's claimed Work grants that
exact path and operation in its own CDE container. Synthetic folder; the
registry is signed by an in-memory court key.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

import nodelang.application_server as application_server_module
from nodelang import workspace_roots_catalogue as roots
from nodelang import workspace_roots_signing as signing
from nodelang.clean_coordination_host import (
    CleanCoordinationHost,
    CoordinationIdentity,
    sign_coordination_request,
)
from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_cde_authority import read_cde_write_permit
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import LocalEd25519KmsProvider
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.universal_application import create_universal_governed_work
from nodelang.workspace_roots_catalogue import (
    find_workspace_root_catalogue,
    install_workspace_root_catalogue,
)
from tests_replica.test_application_machine_transport import _green_runtime_compliance
from tests_replica.test_workspace_root_write_admission import (
    _GRAPH, _Store, _entry, _no_live_graph, _registry, graph_state)
from tests_replica.test_workspace_roots_catalogue import _Key
from tests_replica.workshop_gate_support import open_execution_gate

PATH = "workspace-roots/client-a/drawings/a.dwg"
ROOT_GRANT = {"path": "workspace-roots/client-a", "scope": "descendants", "operations": ["write_file"]}
UNRELATED_GRANT = {"path": "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
                   "scope": "exact", "operations": ["write_file"]}


def _map_source() -> bytes:
    return json.dumps([{
        "key": "workspace-root",
        "title": "Workspace Root",
        "nodes": [],
        "wires": [],
        "cross": [],
    }], sort_keys=True, separators=(",", ":")).encode()


def _clean_settings_owner(tmp_path, provider, grant_path):
    root = tmp_path / "clean-owner"
    key_store = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = _map_source()
    built = provision_clean_runtime(
        root,
        provider,
        key_store,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    server = ApplicationServer.from_unified_authority(
        built.location.authority,
        browser_authority=built.browser,
        authority_key_provider=provider,
        scope_caller=built.caller,
        scope_root=built.grand_map.root_id,
        private_root_grants_path=grant_path,
        private_root_grant_provider=provider,
    ).start()
    if find_workspace_root_catalogue(built.location.authority, caller=built.caller) is None:
        install_workspace_root_catalogue(
            built.location.authority,
            operation_id=str(uuid.uuid4()),
            caller=built.caller,
        )
    host = CleanCoordinationHost(built.location.authority, key_store)
    host.bind_workspace_settings(server.clean_authority, server._clean_workspace_roots)
    return server, host, key_store


def _settings_request(host, key_store, body):
    identity = CoordinationIdentity(*roots.SETTINGS_IDENTITY)
    return host.dispatch(sign_coordination_request(
        key_store,
        identity,
        "workspace_roots_settings",
        {"body": body},
        request_id=str(uuid.uuid4()),
    ))


def _container(grant):
    return {
        "container_id": "GM.nodes.workspace-root-court",
        "source_requirement": "court:workspace-root-permit",
        "domain": "nodes",
        "tier": "T1",
        "lifecycle_state": "WIP",
        "suitability_status": "S0",
        "revision": "P01",
        "owner": "founder",
        "checker": "court",
        "allowed_paths": [grant["path"]],
        "gate_kind": "pytest",
        "gate_spec": {"path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py"},
        "write_grants": [grant],
    }


@pytest.fixture()
def runtime(tmp_path, monkeypatch, request):
    grant, writers, registered = request.param
    folder = tmp_path / "client-a"
    folder.mkdir()
    key = _Key()
    files = _registry(tmp_path, key, [_entry(folder, writers=writers)] if registered else [])
    monkeypatch.setattr(roots, "default_snapshot_path", lambda: files["snapshot_path"])
    monkeypatch.setattr(roots, "default_pin_path", lambda: files["pin_path"])
    monkeypatch.setattr(roots, "default_last_good_path", lambda: files["last_good_path"], raising=False)
    monkeypatch.setattr(signing, "CngVerifier", lambda name: _Store(key))
    monkeypatch.setattr(roots, "verified_graph_state", graph_state, raising=False)
    monkeypatch.setattr(roots, "graph_context", _no_live_graph, raising=False)
    descriptor_path = tmp_path / "workspace-root-permit.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"w" * 32)
    provider.add_key("archhub.local.private-root-grants", b"g" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor_path,
                               universal_workspace_root=tmp_path,
                               private_root_grants_path=tmp_path / "private-root-grants.json",
                               machine_key_provider=provider,
                               runtime_compliance_runner=_green_runtime_compliance).start()
    agent = UniversalRuntimeClient(descriptor_path, provider)
    try:
        cde_provider = LocalEd25519KmsProvider(provider_id="court.workspace-root",
                                               authority_id="court-workspace-root")
        server.cde_write_signing_descriptor_root = (
            application_server_module._ensure_cde_write_signing_authority(
                server.universal_store, server.universal_registry, cde_provider,
                descriptor_root="court:cde-write-signing-key:v1"))
        server.cde_write_signing_provider = cde_provider
        work_root, _wire, _revision = create_universal_governed_work(
            server.universal_store, server.universal_registry,
            title="Write inside a registered workspace root",
            description="Root-bound permits need the owner's registry AND this Work's grant.",
            priority=100, external_key="court:workspace-root-permit",
            structured_references={"cde-container": _container(grant)}, x=320, y=240)
        open_execution_gate(server, work_root, "workspace-root-permit")
        agent.bind_agent_session(runtime="codex", external_session_id="court-workspace-root")
        agent.request("POST", "/api/universal/workshop", {
            "category": "plan", "text": "Write inside the registered root.", "refs": [work_root],
            "evidence": [], "recipients": [], "reply_to": None,
            "idempotency_key": "court:workspace-root-permit:plan",
            "created_at": "2026-09-29T00:00:00+00:00"})
        agent.claim_work(work_root)
        yield {"server": server, "agent": agent, "work": work_root, "key": key, "files": files,
               "folder": folder, "tmp": tmp_path}
    finally:
        server.close()


def _issue(world, operation="write_file", suffix=""):
    return world["agent"].issue_cde_write_permit(
        operation=operation, path=PATH, content_digest=hashlib.sha256(b"client drawing").hexdigest(),
        request_id="court-root-request" + suffix, nonce="court-root-nonce" + suffix)


def _last_good(world, revision):
    kept = world["tmp"] / "kept"
    kept.mkdir(exist_ok=True)
    written = _registry(kept, world["key"], [_entry(world["folder"], writers=("codex",))], revision=revision,
                        current=False)
    world["files"]["last_good_path"].write_bytes(written["snapshot_path"].read_bytes())


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_a_registered_writer_with_a_granting_work_is_issued_and_consumed(runtime):
    issued = _issue(runtime)
    assert issued["work"] == runtime["work"] and issued["path"] == PATH
    assert issued["container_id"] == "GM.nodes.workspace-root-court"
    permit = read_cde_write_permit(runtime["server"].universal_store.snapshot(),
                                   runtime["server"].universal_registry.cde_write_authority_protocol,
                                   issued["permit"])
    assert permit.path == PATH
    consumed = runtime["agent"].consume_cde_write_permit(
        permit=issued["permit"], operation="write_file", path=PATH,
        content_digest=hashlib.sha256(b"client drawing").hexdigest(), request_id="court-root-request")
    assert consumed["kind"] == "consumed" and consumed["work"] == runtime["work"]


def test_a_private_root_settings_grant_reaches_status_permit_receipt_and_revoke(
    tmp_path, monkeypatch
):
    folder = tmp_path / "client-a"
    folder.mkdir()
    key = _Key()
    files = _registry(tmp_path, key, [_entry(folder, writers=("codex",))])
    monkeypatch.setattr(roots, "default_snapshot_path", lambda: files["snapshot_path"])
    monkeypatch.setattr(roots, "default_pin_path", lambda: files["pin_path"])
    monkeypatch.setattr(roots, "default_last_good_path", lambda: files["last_good_path"], raising=False)
    monkeypatch.setattr(signing, "CngVerifier", lambda name: _Store(key))
    monkeypatch.setattr(roots, "verified_graph_state", graph_state, raising=False)
    monkeypatch.setattr(roots, "graph_context", _no_live_graph, raising=False)
    descriptor_path = tmp_path / "private-root-machine.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"p" * 32)
    provider.add_key("archhub.local.private-root-grants", b"q" * 32)
    provider.add_key("archhub.unified.bootstrap", b"r" * 32)
    grant_path = tmp_path / "private-root-grants.json"
    settings_server, settings_host, settings_keys = _clean_settings_owner(
        tmp_path, provider, grant_path)
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        universal_workspace_root=tmp_path,
        private_root_grants_path=grant_path,
        machine_key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    agent = UniversalRuntimeClient(descriptor_path, provider)
    try:
        cde_provider = LocalEd25519KmsProvider(
            provider_id="court.private-root", authority_id="court-private-root")
        server.cde_write_signing_descriptor_root = (
            application_server_module._ensure_cde_write_signing_authority(
                server.universal_store, server.universal_registry, cde_provider,
                descriptor_root="court:private-root-cde-write-signing-key:v1"))
        server.cde_write_signing_provider = cde_provider
        agent.bind_agent_session(runtime="codex", external_session_id="court-private-root")
        _container, digest, _registration = roots.root_bound_registration(PATH, runtime="codex")

        _settings_request(settings_host, settings_keys, {
            "action": "grant-private-root",
            "id": "client-a",
            "runtime": "codex",
            "session_id": agent.agent_session_root,
            "operations": ["write_file"],
        })
        status = agent.private_root_grant_status(path=PATH, operation="write_file")
        assert status["granted"] is True and status["agent_session"] == agent.agent_session_root

        issued = _issue({"agent": agent}, suffix="-private")
        assert issued["work"] == agent.agent_session_root
        consumed = agent.consume_cde_write_permit(
            permit=issued["permit"], operation="write_file", path=PATH,
            content_digest=hashlib.sha256(b"client drawing").hexdigest(),
            request_id="court-root-request-private")
        assert consumed["kind"] == "consumed" and consumed["work"] == agent.agent_session_root

        _settings_request(settings_host, settings_keys, {
            "action": "revoke-private-root",
            "id": "client-a",
            "runtime": "codex",
            "session_id": agent.agent_session_root,
        })
        denied = agent.private_root_grant_status(path=PATH, operation="write_file")
        assert denied["granted"] is False and denied["reason"] == "grant revoked"
        with pytest.raises(MachineTransportError, match="claimed governed Work"):
            _issue({"agent": agent}, suffix="-revoked")
    finally:
        server.close()
        settings_server.close()


@pytest.mark.parametrize("runtime", [(UNRELATED_GRANT, ("codex",), True)], indirect=True)
def test_a_work_that_does_not_grant_the_root_path_is_refused(runtime):
    with pytest.raises(MachineTransportError, match="not granted"):
        _issue(runtime)


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_an_operation_the_work_does_not_grant_is_refused(runtime):
    with pytest.raises(MachineTransportError, match="not granted"):
        _issue(runtime, operation="apply_patch")


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("claude",), True)], indirect=True)
def test_a_runtime_that_is_not_a_root_writer_is_refused(runtime):
    with pytest.raises(MachineTransportError, match="not a writer"):
        _issue(runtime)


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), False)], indirect=True)
def test_an_unregistered_root_is_refused_even_with_a_granting_work(runtime):
    with pytest.raises(MachineTransportError, match="not a registered"):
        _issue(runtime)


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_a_replayed_older_registry_is_refused_at_issue_and_at_receipt(runtime):
    issued = _issue(runtime)
    _last_good(runtime, 9)  # the hooks have since verified a newer registry
    with pytest.raises(MachineTransportError, match="replay"):
        runtime["agent"].consume_cde_write_permit(
            permit=issued["permit"], operation="write_file", path=PATH,
            content_digest=hashlib.sha256(b"client drawing").hexdigest(), request_id="court-root-request")
    with pytest.raises(MachineTransportError, match="replay"):
        _issue(runtime, suffix="-2")


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_a_permit_is_void_when_the_same_root_id_is_registered_to_another_folder(runtime):
    """Issued under folder A; the same id then names folder B (a newer signed
    registry, same Work grant, same writer): the receipt must refuse the old permit."""
    issued = _issue(runtime)
    other = runtime["tmp"] / "client-b-folder"
    other.mkdir()
    _registry(runtime["tmp"], runtime["key"], [_entry(other, writers=("codex",))], revision=4)
    with pytest.raises(MachineTransportError):
        runtime["agent"].consume_cde_write_permit(
            permit=issued["permit"], operation="write_file", path=PATH,
            content_digest=hashlib.sha256(b"client drawing").hexdigest(), request_id="court-root-request")
    fresh = _issue(runtime, suffix="-b")  # a new permit under the new registration is admitted
    assert fresh["container_digest"] != issued["container_digest"]


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_a_root_the_graph_revoked_is_refused_at_issue_and_at_receipt(runtime):
    """The files stay signed, pinned and newest; only the graph moved on."""
    issued = _issue(runtime)
    _GRAPH["digest"] = "cd" * 32
    with pytest.raises(MachineTransportError, match="current projection"):
        runtime["agent"].consume_cde_write_permit(
            permit=issued["permit"], operation="write_file", path=PATH,
            content_digest=hashlib.sha256(b"client drawing").hexdigest(), request_id="court-root-request")
    with pytest.raises(MachineTransportError, match="current projection"):
        _issue(runtime, suffix="-3")
