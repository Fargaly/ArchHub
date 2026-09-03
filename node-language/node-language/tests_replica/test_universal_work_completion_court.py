"""Independent completion court over exact graph-owned work and sessions."""
from __future__ import annotations

import json
import hashlib

import pytest

from nodelang.application_machine_transport import (
    MachineTransportError,
    UniversalRuntimeClient,
)
from nodelang.application_server import ApplicationServer
from nodelang.cell_attestations import CourtResult
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_protocols import read_relation, remove_relation_member
from nodelang.cell_state_machine import (
    machine_history,
    read_instance_state_machine,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    adjudicate_universal_governed_work,
    attest_universal_runtime_compliance,
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_next_universal_governed_work,
    create_universal_governed_work,
    project_universal_governed_work_status,
    restore_universal_application,
    transition_universal_governed_work,
)
from nodelang.universal_cell import CellStore


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


def _work(client, *, title, proof):
    return client.request("POST", "/api/universal/work", {
        "title": title,
        "priority": 100,
        "structured_references": {
            "requirements": {
                "gate": {
                    "kind": "file_exists",
                    "spec": {"path": proof},
                },
            },
            "cde-container": {
                "container_id": "court-test",
                "allowed_paths": ["."],
            },
        },
        "x": 720,
        "y": 480,
    })


def _submit(agent, root):
    claimed = agent.claim_next_work()
    assert claimed["work"]["root"] == root
    return agent.request("POST", "/api/universal/work-transition", {
        "root": root,
        "event": "submit",
        "evidence": json.dumps({"artifact": root, "verdict": "green"}),
    })


def test_restore_backfills_legacy_governed_work_claim_binding():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"l" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    map_path = resolve_map_path()
    store, registry = build_universal_application(
        map_path,
        key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    context = registry.authorization.session.context()
    session_root = "app:agent-session:runtime:legacy-claim-court"
    fingerprint = hashlib.sha256(b"legacy-claim-court").hexdigest()
    session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root=session_root,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=context,
    )
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Backfill one legacy claim relation",
        x=720,
        y=480,
        authentication_context=context,
    )
    compliance, _evidence_root, _ = attest_universal_runtime_compliance(
        store,
        registry,
        agent_session_root=session.root_id,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=context,
    )
    claimed = claim_next_universal_governed_work(
        store,
        registry,
        agent_session_root=session.root_id,
        compliance_observation_root=compliance.root_id,
        authentication_context=context,
    )
    original_binding = claimed["work"]["claim_binding"]
    machine = read_instance_state_machine(
        store.snapshot(),
        registry.assembly_protocol,
        registry.standard_library.state_machine_protocol,
        work_root,
    )
    claim_event = machine_history(
        store.snapshot(),
        registry.standard_library.state_machine_protocol,
        machine.root_id,
    )[-1]
    context_role = registry.standard_library.state_machine_protocol.role(
        "context"
    )
    event_binding_incidence = next(
        member.incidence_id
        for member in read_relation(store.snapshot(), claim_event.root_id, budget=64)
        if member.role_id == context_role
        and member.participant_id == original_binding
    )
    registry_binding_incidence = next(
        member.incidence_id
        for member in read_relation(
            store.snapshot(),
            registry.governed_work_claim_binding_registry_root,
            budget=100_000,
        )
        if member.role_id == registry.governed_work_claim_binding_roles[
            "binding-member"
        ]
        and member.participant_id == original_binding
    )
    remove_relation_member(store, claim_event.root_id, event_binding_incidence)
    remove_relation_member(
        store,
        registry.governed_work_claim_binding_registry_root,
        registry_binding_incidence,
    )

    store, restored = restore_universal_application(
        map_path,
        store,
        key_provider=provider,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    status = project_universal_governed_work_status(
        store,
        restored,
        authentication_context=restored.authorization.session.context(),
    )
    item = next(row for row in status["items"] if row["root"] == work_root)
    assert item["claimant_session"] == session.root_id
    assert item["claimant_agent_body"] == restored.agent_body.body.root_id
    assert item["claim_binding"].startswith("app:governed-work-claim-binding:")
    assert item["claim_binding"] != original_binding


def test_independent_court_alone_accepts_or_returns_submitted_work(tmp_path):
    descriptor = tmp_path / "runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"w" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    owner = UniversalRuntimeClient(descriptor, provider)
    agent = UniversalRuntimeClient(descriptor, provider)
    other = UniversalRuntimeClient(descriptor, provider)
    try:
        (tmp_path / "green.flag").write_text("proven", encoding="utf-8")
        green = _work(owner, title="Green work", proof="green.flag")
        red = _work(owner, title="Red work", proof="missing.flag")
        enrolled = agent.bind_agent_session(
            runtime="codex", external_session_id="court-owner"
        )
        other.bind_agent_session(
            runtime="gemini-cli", external_session_id="court-other"
        )

        _submit(agent, green["created_root"])
        with pytest.raises(MachineTransportError, match="submitting Agent Session"):
            other.adjudicate_work(green["created_root"])
        with pytest.raises(MachineTransportError, match="agent allowlist"):
            agent.request("POST", "/api/universal/work-transition", {
                "root": green["created_root"],
                "event": "accept",
                "evidence": "forged",
            })
        accepted = agent.adjudicate_work(green["created_root"])
        assert accepted["passed"] is True
        assert accepted["event"] == "accept"
        assert accepted["status"]["counts"]["complete"] == 1

        _submit(agent, red["created_root"])
        returned = agent.adjudicate_work(red["created_root"])
        assert returned["passed"] is False
        assert returned["event"] == "return"
        assert returned["status"]["counts"]["claimed"] == 1
        item = next(
            value for value in returned["status"]["items"]
            if value["root"] == red["created_root"]
        )
        assert item["claimant_session"] == enrolled["agent_session"]

        snapshot = server.universal_store.snapshot()
        assert server.universal_registry.work_completion_court_root in snapshot.cells
        machine = read_instance_state_machine(
            snapshot,
            server.universal_registry.assembly_protocol,
            server.universal_registry.standard_library.state_machine_protocol,
            red["created_root"],
        )
        last = machine_history(
            snapshot,
            server.universal_registry.standard_library.state_machine_protocol,
            machine.root_id,
        )[-1]
        assert last.actor_root \
            == server.universal_registry.work_completion_court_root
        assert returned["attestation_root"] in last.context_roots
        assert enrolled["agent_session"] in last.context_roots
    finally:
        server.close()


def test_court_rejects_path_escape_without_reading_outside_cde(tmp_path):
    descriptor = tmp_path / "runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"x" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    owner = UniversalRuntimeClient(descriptor, provider)
    agent = UniversalRuntimeClient(descriptor, provider)
    try:
        escaped = _work(owner, title="Escaping work", proof="../outside.flag")
        agent.bind_agent_session(
            runtime="codex", external_session_id="court-escape"
        )
        _submit(agent, escaped["created_root"])
        result = agent.adjudicate_work(escaped["created_root"])
        assert result["passed"] is False
        assert result["event"] == "return"
    finally:
        server.close()


def test_court_definition_attestation_and_completion_survive_restart(tmp_path):
    database = tmp_path / "application.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    (tmp_path / "durable.flag").write_text("durable", encoding="utf-8")
    store, registry = build_universal_application(
        resolve_map_path(),
        CellStore(database),
        key_provider=provider,
        court_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    context = registry.authorization.session.context()
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Durable court work",
        priority=100,
        structured_references={
            "requirements": {
                "gate": {
                    "kind": "file_exists",
                    "spec": {"path": "durable.flag"},
                },
            },
            "cde-container": {"allowed_paths": ["."]},
        },
        x=500,
        y=500,
        authentication_context=context,
    )
    session_root = "app:agent-session:runtime:durable-court"
    fingerprint = hashlib.sha256(b"durable-court-session").hexdigest()
    begin_universal_runtime_agent_session(
        store,
        registry,
        session_root=session_root,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=context,
    )
    compliance, _evidence_root, _ = attest_universal_runtime_compliance(
        store,
        registry,
        agent_session_root=session_root,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=context,
    )
    claimed = claim_next_universal_governed_work(
        store,
        registry,
        agent_session_root=session_root,
        compliance_observation_root=compliance.root_id,
        authentication_context=context,
    )
    assert claimed["work"]["root"] == work_root
    transition_universal_governed_work(
        store,
        registry,
        work_root,
        "submit",
        agent_session_root=session_root,
        evidence_payload="durable artifact proof",
        authentication_context=context,
    )
    completed = adjudicate_universal_governed_work(
        store,
        registry,
        work_root,
        requesting_agent_session_root=session_root,
        workspace_root=tmp_path,
        authentication_context=context,
    )
    attestation_root = completed["attestation_root"]
    assert completed["passed"] is True
    store.close()

    restored_store = CellStore(database)
    restored_store, restored = restore_universal_application(
        resolve_map_path(),
        restored_store,
        key_provider=provider,
        court_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    try:
        status = project_universal_governed_work_status(
            restored_store,
            restored,
            authentication_context=restored.authorization.session.context(),
        )
        assert status["counts"]["complete"] == 1
        assert attestation_root in restored_store.snapshot().cells
        assert restored.work_completion_court_root \
            == "app:court:work-completion"
    finally:
        restored_store.close()
