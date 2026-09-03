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
from nodelang.clean_coordination_mcp import (
    LocalCoordinationClient,
    build_server,
    identity_from_environment,
)
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
    return opened, key_store, CleanCoordinationHost(opened.authority, key_store)


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


def test_signed_sessions_coordinate_in_one_graph_and_replay_zero(tmp_path):
    opened, keys, host = _host(tmp_path)
    codex = CoordinationIdentity("codex", "thread-codex", "gpt")
    reviewer = CoordinationIdentity("reviewer", "thread-reviewer", "reviewer")
    try:
        first = host.dispatch(_request(keys, codex, "register_session"))
        host.dispatch(_request(keys, reviewer, "register_session"))
        revision = opened.authority.store.revision
        cell_count = len(opened.authority.store.snapshot().cells)
        replay = host.dispatch(_request(keys, codex, "register_session"))
        assert replay["self"]["session_root"] == first["self"]["session_root"]
        assert opened.authority.store.revision == revision
        assert len(opened.authority.store.snapshot().cells) == cell_count

        agents = host.dispatch(_request(keys, codex, "list_agents"))
        assert agents["count"] == 2
        target = tuple(
            item["session_root"] for item in agents["agents"]
            if item["runtime"] == "reviewer"
        )[0]
        operation = str(uuid.uuid4())
        sent = host.dispatch(_request(
            keys,
            codex,
            "send_message",
            {
                "target": target,
                "message": "Review the accepted clean graph.",
                "idempotency_key": operation,
            },
            "send",
        ))
        message = sent["message"]
        assert message["sender_root"] == first["self"]["session_root"]
        assert message["recipient_root"] == target
        inbox = host.dispatch(_request(
            keys,
            reviewer,
            "inbox",
            {"after_revision": message["created_revision"] - 1},
            "inbox",
        ))
        assert [item["root_id"] for item in inbox["messages"]] == [
            message["root_id"]
        ]
    finally:
        opened.authority.store.close()


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


def test_loopback_transport_uses_signed_runtime_identity(tmp_path):
    opened, keys, host = _host(tmp_path)
    service = build_bound_service(host)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    endpoint = "http://127.0.0.1:%s/coordination" % service.server_address[1]
    try:
        identity = CoordinationIdentity("codex", "thread-transport", "gpt")
        client = LocalCoordinationClient(
            identity,
            endpoint=endpoint,
            key_store=keys,
        )
        registered = client.call("register_session")
        assert registered["self"]["runtime"] == "codex"
        listed = client.call("list_agents")
        assert listed["count"] == 1
        assert listed["self"] == registered["self"]["session_root"]

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


def test_signed_workshop_lens_reads_the_same_graph_and_real_relations(tmp_path):
    opened, keys, host = _host(tmp_path)
    service = build_bound_service(host)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    origin = "http://127.0.0.1:%s" % service.server_address[1]
    try:
        sender = CoordinationIdentity("codex", "thread-lens-sender", "gpt")
        recipient = CoordinationIdentity(
            "reviewer", "thread-lens-recipient", "reviewer"
        )
        sender_session = host.dispatch(
            _request(keys, sender, "register_session", label="sender")
        )["self"]["session_root"]
        recipient_session = host.dispatch(
            _request(keys, recipient, "register_session", label="recipient")
        )["self"]["session_root"]
        sent = host.dispatch(_request(
            keys,
            sender,
            "send_message",
            {
                "target": recipient_session,
                "message": "Review the visible graph-native Workshop lens.",
                "idempotency_key": "cc8723a5-4f2f-4cdf-bd94-9395798e14f2",
            },
            "send-lens-message",
        ))

        sender_client = LocalCoordinationClient(
            sender,
            endpoint=origin + "/coordination",
            key_store=keys,
        )
        payload = sender_client.call("workshop_lens")["lens"]
        assert payload["graph_id"] == opened.authority.manifest.graph_id
        assert payload["revision"] == opened.authority.store.revision
        message_root = sent["message"]["root_id"]
        message = tuple(
            node for node in payload["nodes"] if node["root_id"] == message_root
        )
        assert len(message) == 1
        assert message[0]["definition_name"] == "Coordination message"
        assert message[0]["state"] == "sent"
        relation_roots = {item["root_id"] for item in payload["relations"]}
        assert relation_roots
        assert {port["relation_root"] for port in message[0]["ports"]} == (
            relation_roots
        )
        endpoints = {
            root
            for relation in payload["relations"]
            for _, root in relation["participants"]
        }
        assert {message_root, sender_session, recipient_session}.issubset(endpoints)
        assert {item["name"] for item in payload["catalogue"]}.issuperset({
            "Coordination message", "Work assignment", "Independent review"
        })

        denied = Request(origin + "/workshop-lens", method="GET")
        with pytest.raises(HTTPError) as rejected:
            urlopen(denied, timeout=5)
        assert rejected.value.code == 404
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
        client = LocalCoordinationClient(identity, endpoint=endpoint, key_store=keys)
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
        reopened_host = CleanCoordinationHost(reopened.authority, keys)
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


def test_stdio_identity_has_no_random_fallback_and_schema_has_no_sender():
    identity = identity_from_environment({
        "ARCHHUB_COORDINATION_VENDOR": "codex",
        "CODEX_THREAD_ID": "thread-exact",
    })
    assert identity.session_instance_id == "thread-exact"
    gemini = identity_from_environment({
        "ARCHHUB_COORDINATION_VENDOR": "gemini",
        "GEMINI_SESSION_ID": "gemini-session-exact",
    })
    assert gemini.session_instance_id == "gemini-session-exact"
    with pytest.raises(RuntimeError, match="random fallback is denied"):
        identity_from_environment({"ARCHHUB_COORDINATION_VENDOR": "codex"})
    with pytest.raises(RuntimeError, match="random fallback is denied"):
        identity_from_environment({
            "ARCHHUB_COORDINATION_VENDOR": "codex",
            "ARCHHUB_COORDINATION_SESSION_ID": "caller-selected",
        })

    class _Client:
        def call(self, method, parameters=None, **_kwargs):
            return {"ok": True, "method": method, "parameters": parameters or {}}

    server = build_server(_Client())
    tools = asyncio.run(server.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in tools}
    assert set(schemas) == {
        "coordination.register_session",
        "coordination.list_agents",
        "coordination.scope_lens",
        "coordination.workshop_lens",
        "coordination.revise_instance",
        "coordination.send_message",
        "coordination.followup_task",
        "coordination.interrupt_agent",
        "coordination.wait_agent",
        "coordination.mark_message_read",
    }
    for schema in schemas.values():
        properties = schema["properties"]
        assert "sender" not in properties
        assert "vendor" not in properties
        assert "session_id" not in properties


def test_workshop_lens_rejects_wrong_session_signature_and_no_founder_substitute(
    tmp_path,
):
    opened, keys, host = _host(tmp_path)
    identity = CoordinationIdentity("codex", "thread-lens-auth", "gpt")
    try:
        host.dispatch(_request(keys, identity, "register_session"))
        request = _request(keys, identity, "workshop_lens", label="lens-auth")
        with pytest.raises(InvalidCell, match="signature"):
            host.dispatch(replace(request, signature="AAAA"))
        accepted = host.dispatch(request)
        assert accepted["lens"]["graph_id"] == opened.authority.manifest.graph_id
        assert accepted["lens"]["revision"] == opened.authority.store.revision

        host_source = (
            Path(__file__).parents[1]
            / "nodelang"
            / "clean_coordination_host.py"
        ).read_text(encoding="utf-8")
        coordinator_source = (
            Path(__file__).parents[1]
            / "nodelang"
            / "clean_agent_coordination.py"
        ).read_text(encoding="utf-8")
        assert "project_workshop_lens" not in host_source
        assert "caller=self._binding.caller" in coordinator_source
    finally:
        opened.authority.store.close()
