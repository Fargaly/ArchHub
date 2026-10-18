from __future__ import annotations

from dataclasses import replace
import asyncio
import hashlib
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_coordination_host import (
    CleanCoordinationHost,
    CoordinationIdentity,
    SignedCoordinationRequest,
    sign_coordination_request,
)
from nodelang.native_agent_mcp import build_server
from nodelang.clean_coordination_service import (
    MAX_REQUEST_BYTES,
    build_bound_service,
)
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.coordination_workshop import create_workshop_instance
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority import composition_root
from nodelang.unified_authority_runtime import open_current_authority
from nodelang.universal_cell import InvalidCell
from nodelang.workspace_roots_catalogue import SETTINGS_IDENTITY


pytestmark = pytest.mark.skipif(
    __import__("os").name != "nt",
    reason="the production caller-key boundary uses Windows DPAPI",
)


def _map_source() -> bytes:
    return json.dumps([{
        "key": "brain",
        "title": "Brain and Memory",
        "nodes": [{
            "id": "brain_attention",
            "cat": "behavior",
            "title": "Persistent attention",
            "sub": "Keep accepted work visible",
            "status": "partial",
            "params": [],
            "evidence_ref": "court:coordination-host",
            "authority_source": "founder",
        }],
        "wires": [],
        "cross": [],
    }], sort_keys=True, separators=(",", ":")).encode()


def _host(tmp_path):
    root = tmp_path / "runtime"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-coordination-host-key" + b"0" * 5,
    )
    key_store = WindowsDpapiCallerKeyStore(tmp_path / "callers.dpapi.json")
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
    built.location.authority.store.close()
    opened = open_current_authority(root, provider)
    return opened, key_store, CleanCoordinationHost(
        opened.authority, key_store, runtime_root=root
    )


def _request(key_store, identity, method, parameters=None, label="request"):
    return sign_coordination_request(
        key_store,
        identity,
        method,
        parameters or {},
        request_id=str(uuid.uuid5(
            uuid.UUID("281761be-9f1c-4c88-bad3-aae746f32d08"),
            "%s:%s" % (identity.session_instance_id, label),
        )),
    )


def _attach(host, key_store, identity, *session_roots):
    """Workshop messages need both sessions attached (326b6579): the signed
    attach_agent path, the same one an installed agent uses."""
    for session_root in session_roots:
        host.dispatch(_request(key_store, identity, "attach_agent", {
            "target": session_root,
            "idempotency_key": str(uuid.uuid5(
                uuid.UUID("5a0c4f2e-2b0e-4f7e-9d0a-6f1c2b3d4e5f"), session_root)),
        }, "attach:" + session_root))




def test_request_signature_and_session_key_binding_fail_closed(tmp_path):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity("codex", "thread-codex")
    try:
        baseline_revision = opened.authority.store.revision
        baseline_cells = len(opened.authority.store.snapshot().cells)
        request = _request(keys, identity, "register_session")
        with pytest.raises(InvalidCell, match="signature"):
            host.dispatch(replace(request, signature="AAAA"))
        assert opened.authority.store.revision == baseline_revision
        assert len(opened.authority.store.snapshot().cells) == baseline_cells
        other = CoordinationIdentity("codex", "another-thread")
        keys.ensure(other.key_id)
        with pytest.raises(InvalidCell, match="not bound"):
            host.dispatch(replace(request, key_id=other.key_id))
        assert opened.authority.store.revision == baseline_revision
        assert len(opened.authority.store.snapshot().cells) == baseline_cells
    finally:
        opened.authority.store.close()


def test_wire_request_rejects_type_coercion_before_signature_verification():
    identity = CoordinationIdentity("codex", "thread-exact", "gpt")
    payload = {
        "version": "archhub-clean-coordination-v1",
        "request_id": "f7489b84-2712-4db0-94f1-a2e2fa0b08cb",
        "identity": {
            "vendor": identity.vendor,
            "session_instance_id": identity.session_instance_id,
            "model": identity.model,
        },
        "key_id": identity.key_id,
        "method": "register_session",
        "parameters": {},
        "signature": "AAAA",
    }
    for path, replacement in (
        (("version",), 1),
        (("method",), True),
        (("identity", "vendor"), ["codex"]),
    ):
        candidate = json.loads(json.dumps(payload))
        if len(path) == 1:
            candidate[path[0]] = replacement
        else:
            candidate[path[0]][path[1]] = replacement
        with pytest.raises(InvalidCell, match="identity is invalid"):
            SignedCoordinationRequest.from_payload(candidate)


def test_host_releases_no_second_store_or_coordination_ledger():
    source = (
        Path(__file__).parents[1] / "nodelang" / "clean_coordination_host.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3",
        "jsonl",
        "UniversalRuntimeSessionManager",
        "coordination_send",
        "external_session_id",
        "message_queue",
    ):
        assert forbidden not in source


class _SignedHostFixture:
    def __init__(self, identity, *, endpoint, key_store):
        self.identity, self.endpoint, self.keys = identity, endpoint, key_store

    def call(self, method, parameters=None, **kwargs):
        request = sign_coordination_request(self.keys, self.identity, method, parameters or {})
        packet = Request(self.endpoint, data=json.dumps(request.to_payload()).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urlopen(packet) as response:
            return json.load(response)


def test_loopback_transport_uses_signed_runtime_identity(tmp_path):
    opened, keys, host = _host(tmp_path)
    service = build_bound_service(host)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    endpoint = "http://127.0.0.1:%s/coordination" % service.server_address[1]
    try:
        identity = CoordinationIdentity("codex", "thread-transport", "gpt")
        client = _SignedHostFixture(
            identity,
            endpoint=endpoint,
            key_store=keys,
        )
        registered = client.call("register_session")
        assert registered["self"]["runtime"] == "codex"

        denied = Request(
            endpoint,
            data=b"{}",
            method="POST",
            headers={"Origin": "https://attacker.example"},
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(denied, timeout=5)
        assert rejected.value.code == 403

        wrong_host = Request(
            endpoint,
            data=b"{}",
            method="POST",
            headers={"Host": "attacker.example"},
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(wrong_host, timeout=5)
        assert rejected.value.code == 403

        oversized = Request(
            endpoint,
            data=b"x" * (MAX_REQUEST_BYTES + 1),
            method="POST",
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(oversized, timeout=5)
        assert rejected.value.code == 413
    finally:
        service.shutdown()
        service.server_close()
        thread.join(timeout=5)
        opened.authority.store.close()




def test_signed_generic_lens_revises_exact_instance_and_reopens_same_graph(
    tmp_path,
):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity("codex", "thread-visual-editor", "gpt")
    workshop = composition_root(
        opened.authority, "Workshop", caller=host._founder
    )
    plan = create_workshop_instance(
        opened.authority,
        host._workshop.plan_definition,
        {"title": "Original graph-held title"},
        caller=host._founder,
        command_id="0256b5bd-b685-4d2a-92bf-dd9a2d8b44df",
    )
    service = build_bound_service(host)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    endpoint = "http://127.0.0.1:%s/coordination" % service.server_address[1]
    command = "fa7df7b8-d504-4819-ab34-7961c586b5a5"
    try:
        client = _SignedHostFixture(identity, endpoint=endpoint, key_store=keys)
        client.call("register_session")
        before = client.call("scope_lens", {"scope_root": workshop})["lens"]
        assert before["graph_id"] == opened.authority.manifest.graph_id
        assert before["revision"] == opened.authority.store.revision
        selected = next(
            node for node in before["nodes"] if node["root_id"] == plan.root_id
        )
        assert next(
            item["value"] for item in selected["properties"]
            if item["name"] == "title"
        ) == "Original graph-held title"

        parameters = {
            "instance_root": plan.root_id,
            "scope_root": workshop,
            "changes": {"title": "Edited through the signed graph command"},
            "expected_revision": before["revision"],
            "idempotency_key": command,
        }
        changed = client.call("revise_instance", parameters)
        assert changed["lens"]["graph_id"] == before["graph_id"]
        assert changed["lens"]["revision"] == changed["revision"]
        assert changed["revision"] == before["revision"] + 1
        assert changed["accepted_revision"] == changed["revision"]
        edited = next(
            node for node in changed["lens"]["nodes"]
            if node["root_id"] == plan.root_id
        )
        assert next(
            item["value"] for item in edited["properties"]
            if item["name"] == "title"
        ) == "Edited through the signed graph command"
        replay = client.call("revise_instance", parameters)
        assert replay["replayed"] is True
        assert replay["revision"] == changed["revision"]

        create_workshop_instance(
            opened.authority,
            host._workshop.evidence_definition,
            {"summary": "Independent unrelated accepted commit"},
            caller=host._founder,
            command_id="feaf2812-816e-49eb-8c2f-662f73230e8a",
        )
        revision_after_other_commit = opened.authority.store.revision
        cells_before_retry = len(opened.authority.store.snapshot().cells)
        late_replay = client.call("revise_instance", parameters)
        assert late_replay["replayed"] is True
        assert late_replay["accepted_revision"] == changed["accepted_revision"]
        assert late_replay["revision"] == revision_after_other_commit
        assert late_replay["lens"]["revision"] == revision_after_other_commit
        assert len(opened.authority.store.snapshot().cells) == cells_before_retry
    finally:
        service.shutdown()
        service.server_close()
        thread.join(timeout=5)
        graph_id = opened.authority.manifest.graph_id
        revision = opened.authority.store.revision
        opened.authority.store.close()

    reopened = open_current_authority(
        tmp_path / "runtime", opened.authority.key_provider
    )
    try:
        reopened_host = CleanCoordinationHost(
            reopened.authority, keys, runtime_root=tmp_path / "runtime"
        )
        reopened_lens = reopened_host.dispatch(_request(
            keys,
            identity,
            "scope_lens",
            {"scope_root": workshop},
            "reopened-lens",
        ))["lens"]
        assert reopened_lens["graph_id"] == graph_id
        assert reopened_lens["revision"] == revision
        reopened_plan = next(
            node for node in reopened_lens["nodes"]
            if node["root_id"] == plan.root_id
        )
        assert next(
            item["value"] for item in reopened_plan["properties"]
            if item["name"] == "title"
        ) == "Edited through the signed graph command"
    finally:
        reopened.authority.store.close()


def test_mcp_schema_has_only_two_message_tools_and_no_sender():
    server = build_server()
    tools = asyncio.run(server.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in tools}
    assert {"send", "read"} <= set(schemas)
    assert not any(name.startswith("coordination.") for name in schemas)
    for name in ("send", "read"):
        assert not {"sender", "vendor", "session_id", "context"} & schemas[name]["properties"].keys()


def test_coordination_catalogue_names_are_dispatchable_by_the_names_clients_call(tmp_path):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity("codex", "thread-catalogue-parity", "gpt")
    try:
        server = build_server()
        tools = asyncio.run(server.list_tools())
        aliases = {
            "coordination.register_session": "register_session",
            "coordination.scope_lens": "scope_lens",
        }
        for listed, host_method in aliases.items():
            assert listed not in {tool.name for tool in tools}
            params = {"scope_root": opened.authority.manifest.application_root} if host_method == "scope_lens" else {}
            assert host.dispatch(_request(keys, identity, host_method, params, "plain:" + host_method))["ok"] is True
            assert host.dispatch(_request(keys, identity, listed, params, "dotted:" + host_method))["ok"] is True
    finally:
        opened.authority.store.close()


def test_raw_dotted_signed_execute_run_and_wait_use_canonical_handlers(tmp_path, monkeypatch):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity("codex", "thread-dotted-execute", "gpt")
    try:
        host.dispatch(_request(keys, identity, "register_session"))
        with host._changed:
            _bundle, coordinator = host._binding(identity)
        calls = []

        def execute(message_root, *, invoker):
            calls.append(("execute", message_root))
            return type("Result", (), {
                "root_id": "app:effect:execute",
                "receipt_root": "app:receipt:execute",
                "revision": opened.authority.store.revision,
                "replayed": False,
            })()

        def run(message_root, *, command_id, invoker):
            calls.append(("run", message_root, str(command_id)))
            return {"message_root": message_root, "effect": "app:effect:run",
                    "receipt": "app:receipt:run", "accepted_revision": opened.authority.store.revision,
                    "replayed": False}

        monkeypatch.setattr(coordinator, "execute_claimed_task", execute)
        monkeypatch.setattr(coordinator, "run_workshop_task", run)


        assert host.dispatch(_request(keys, identity, "coordination.execute_workshop_task",
            {"message_root": "app:message:execute"}, "dotted-execute"))["effect"] == "app:effect:execute"
        assert host.dispatch(_request(keys, identity, "coordination.run_workshop_task",
            {"message_root": "app:message:run", "idempotency_key": str(uuid.uuid4())}, "dotted-run"))["effect"] == "app:effect:run"
        assert calls[0][:2] == ("execute", "app:message:execute")
        assert calls[1][:2] == ("run", "app:message:run")
    finally:
        opened.authority.store.close()


def test_dotted_and_bare_denials_are_equivalent(tmp_path):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity("codex", "thread-denial-equivalence", "gpt")
    outsider = CoordinationIdentity("codex", "thread-denial-outsider", "gpt")

    def refusal(request):
        with pytest.raises(InvalidCell) as exc:
            host.dispatch(request)
        return str(exc.value)

    try:
        bare = _request(keys, identity, "scope_lens", label="bad-signature-bare")
        dotted = _request(keys, identity, "coordination.scope_lens", label="bad-signature-dotted")
        assert refusal(replace(bare, signature="AAAA")) == refusal(replace(dotted, signature="AAAA"))
        assert refusal(replace(bare, identity=outsider)) == refusal(replace(dotted, identity=outsider))
        host.dispatch(_request(keys, identity, "register_session"))
        assert refusal(_request(keys, identity, "revise_instance", {}, "refused-bare")) == refusal(
            _request(keys, identity, "coordination.revise_instance", {}, "refused-dotted"))
    finally:
        opened.authority.store.close()




def test_workspace_settings_handler_typeerror_is_not_replayed_without_admission(tmp_path):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity(*SETTINGS_IDENTITY)
    calls = []

    def handler(body, *, admission):
        calls.append((body, admission))
        raise TypeError("admission side effect exploded after one call")

    host._workspace_settings = handler
    try:
        request = _request(
            keys,
            identity,
            "workspace_roots_settings",
            {"body": {"action": "grant-private-root"}},
        )
        with pytest.raises(TypeError, match="admission side effect"):
            host.dispatch(request)
        assert len(calls) == 1
        assert calls[0][1]["principal"] == identity.normalized().key_id
    finally:
        opened.authority.store.close()
