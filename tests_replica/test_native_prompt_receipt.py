"""Real admitted prompt receipts on an isolated test graph; no installed state."""
import hashlib
from contextlib import ExitStack
import sqlite3
from types import SimpleNamespace as NS

import pytest

from nodelang.application_machine_transport import MachineResponseError
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import LocalEd25519KmsProvider
from nodelang.native_agent_session import NativeAgentSession
from nodelang import native_agent_hooks as hook
from nodelang import native_stop_hook as stop


SESSIONS = {"codex": "12345678-1234-4234-9234-123456789abc",
            "claude-code": "12345678-1234-4234-9234-123456789abd"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from nodelang import application_server
    root = tmp_path_factory.mktemp("native-prompt-receipts")
    (root / "ws").mkdir()
    key = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"p" * 32)
    key.add_key("archhub.local.private-root-grants", b"g" * 32)
    authority = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    authority.add_key("archhub.local.court-attestation", b"c" * 32)
    signer = LocalEd25519KmsProvider(provider_id="court.prompt", authority_id="court-prompt")
    with pytest.MonkeyPatch.context() as patch, ExitStack() as cleanup:
        patch.setattr(application_server, "_open_cde_write_signing_provider", lambda *a: signer)
        def no_installed_signing_path():
            pytest.fail("receipt court reached installed signing custody")
        patch.setattr(application_server.WindowsDpapiSigningKeyProvider, "default_path", no_installed_signing_path)
        server = ApplicationServer(enable_machine_transport=True,
            machine_descriptor_path=root / "runtime.json", machine_key_provider=key,
            universal_key_provider=authority, private_root_grants_path=root / "private-grants.json",
            universal_workspace_root=root / "ws", universal_state_path=root / "graph.sqlite3").start()
        cleanup.callback(server.close)
        owners = {}
        for vendor, variable in [("codex", "CODEX_THREAD_ID"), ("claude-code", "CLAUDE_CODE_SESSION_ID")]:
            owner = NativeAgentSession(environment={variable: SESSIONS[vendor]},
                descriptor_path=root / "runtime.json", key_provider=key)
            owner.connect()
            cleanup.callback(owner.close)
            owners[vendor] = owner
        yield NS(server=server, root=root, owners=owners)


def counts(world):
    with sqlite3.connect(world.root / "graph.sqlite3") as connection:
        return connection.execute("SELECT (SELECT MAX(revision) FROM revisions), "
            "(SELECT COUNT(*) FROM cell_versions), (SELECT COUNT(*) FROM current_cells)").fetchone()


def body(vendor, key):
    return {"space": "app:brain-control-ledger:v1",
        "category": "app:brain-control-ledger:v1:category:compliance-event",
        "summary": "Native UserPromptSubmit Completed",
        "payload": {"operation": "native.hook_user_prompt_submit", "status": "Completed",
            "session_fingerprint": stop._fingerprint(stop.canonical_runtime(vendor), SESSIONS[vendor]),
            "external_session_fingerprint": hashlib.sha256(SESSIONS[vendor].encode()).hexdigest(),
            "prompt_sha256": hashlib.sha256(b"real stdin prompt").hexdigest()},
        "idempotency_key": key, "created_at": None}


@pytest.mark.parametrize("vendor", ["codex", "claude-code"])
def test_real_owned_context_and_completed_receipts_never_grow_the_graph(world, monkeypatch, vendor):
    owner = world.owners[vendor]
    values = {}
    vault = NS(get_password=lambda s, k: values.get(k),
        set_password=lambda s, k, v: values.__setitem__(k, v),
        delete_password=lambda s, k: values.pop(k, None))
    recorded = []
    with owner.bound_client() as client:
        direct_baseline = counts(world)
        client.request("POST", "/api/universal/deliberation", body(vendor, "direct-probe-" + vendor))
        assert counts(world) == direct_baseline
        original = client.request
        def observe(method, path, value=None, **kwargs):
            result = original(method, path, value, **kwargs)
            if method == "POST" and path == "/api/universal/deliberation":
                recorded.append(result)
            return result
        monkeypatch.setattr(client, "request", observe)
    host = stop.NativeStopHost(owner, vault=vault).start()
    baseline = counts(world)
    try:
        for _ in range(2):
            result = hook.query_prompt({"hook_event_name": "UserPromptSubmit", "session_id": SESSIONS[vendor],
                "prompt": "real stdin prompt"}, vendor=vendor, vault=vault, environment={})
            assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
            assert counts(world) == baseline
        assert len(recorded) == 2 and recorded[0]["root"] != recorded[1]["root"]
        for receipt in recorded:
            held = world.server._ownership_record_storage().get_record("compliance-event", receipt["root"])
            assert held["owner_root"] == client.agent_session_root
            assert held["payload"]["payload"] == body(vendor, "unused")["payload"]
            assert "real stdin prompt" not in str(held)
    finally:
        assert host.close()


@pytest.mark.parametrize("mutation", ["fingerprint", "stop_digest", "status", "digest", "extra", "space", "category"])
def test_real_receipt_admission_rejects_cross_session_and_wrong_shapes(world, mutation):
    request = body("codex", "bad-" + mutation)
    if mutation == "fingerprint": request["payload"]["external_session_fingerprint"] = "f" * 64
    if mutation == "stop_digest": request["payload"]["session_fingerprint"] = "bad-stop-hash"
    if mutation == "status": request["payload"]["status"] = "Started"
    if mutation == "digest": request["payload"]["prompt_sha256"] = "not-a-digest"
    if mutation == "extra": request["payload"]["prompt"] = "must never be persisted"
    if mutation == "space": request["space"] = "foreign-ledger"
    if mutation == "category": request["category"] = "foreign-category"
    baseline = counts(world)
    with world.owners["codex"].bound_client() as client:
        with pytest.raises(MachineResponseError):
            client.request("POST", "/api/universal/deliberation", request)
    assert counts(world) == baseline


def test_receipt_idempotency_is_scoped_to_its_authenticated_actor(world):
    request = body("codex", "same-key")
    baseline = counts(world)
    with world.owners["codex"].bound_client() as client:
        first = client.request("POST", "/api/universal/deliberation", request)
        again = client.request("POST", "/api/universal/deliberation", request)
    assert first["root"] == again["root"]
    changed = body("codex", "same-key")
    changed["payload"]["prompt_sha256"] = hashlib.sha256(b"changed prompt").hexdigest()
    with world.owners["codex"].bound_client() as client:
        with pytest.raises(MachineResponseError, match="reused"):
            client.request("POST", "/api/universal/deliberation", changed)
    with world.owners["claude-code"].bound_client() as client:
        with pytest.raises(MachineResponseError):
            client.request("POST", "/api/universal/deliberation", request)
        own = client.request("POST", "/api/universal/deliberation", body("claude-code", "same-key"))
    assert own["root"] != first["root"] and counts(world) == baseline


def test_missing_operational_storage_cannot_fall_back_to_graph_receipts(world, monkeypatch):
    baseline = counts(world)
    monkeypatch.setattr(world.server, "_ownership_record_storage", lambda: None)
    with world.owners["codex"].bound_client() as client:
        with pytest.raises(MachineResponseError, match="operational record storage"):
            client.request("POST", "/api/universal/deliberation", body("codex", "no-record-store"))
    assert counts(world) == baseline
