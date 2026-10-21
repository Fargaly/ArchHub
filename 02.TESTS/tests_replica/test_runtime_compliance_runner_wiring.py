from __future__ import annotations

import json

import pytest

from nodelang.application_machine_transport import (
    MachineResponseError,
    UniversalRuntimeClient,
)
from nodelang.cell_agent_body import read_agent_session
from nodelang.cell_attestations import CourtResult, read_court_attestation
from nodelang.cell_compliance import latest_compliance_observation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    _agent_body_catalog_entry_for_session,
    attest_universal_runtime_compliance,
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_next_universal_governed_work,
    create_universal_governed_work,
    project_universal_governed_work_status,
)
from nodelang.universal_cell import CellStore


CHECKS = (
    "runtime-detected",
    "required-hooks",
    "schema-valid",
    "brain-connected",
    "scope-gate",
    "workshop-authority",
)


def _court_result(*, failed=()):
    failed = set(failed)
    checks = {name: name not in failed for name in CHECKS}
    return CourtResult(
        passed=not failed,
        checks=checks,
        details={
            "adapter": "test-physical-runtime-auditor",
            "reason": (
                "ok" if not failed
                else "runtime compliance checks failed: %s" % ", ".join(sorted(failed))
            ),
        },
    )


def _server(tmp_path, monkeypatch, runner):
    from nodelang import application_server as server_module

    monkeypatch.setattr(
        server_module, "run_physical_runtime_compliance_court", runner
    )
    descriptor = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"w" * 32
    )
    server = server_module.ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor,
        machine_key_provider=provider,
        universal_workspace_root=tmp_path,
    ).start()
    return server, UniversalRuntimeClient(descriptor, provider)


def _work(server, key):
    root, _wire, _revision = create_universal_governed_work(
        server.universal_store,
        server.universal_registry,
        title="Runtime compliance wiring",
        description="Claim only with server-side runtime audit.",
        priority=10,
        external_key=key,
        x=20,
        y=20,
        authentication_context=(
            server.universal_registry.authorization.session.context()
        ),
    )
    return root


def _claim(client, work_root):
    return client.claim_work(work_root)


def _latest_payload(server, session_root):
    snapshot = server.universal_store.snapshot()
    session = read_agent_session(
        snapshot,
        server.universal_registry.agent_body.protocol,
        server.universal_registry.authorization.protocol,
        session_root,
    )
    entry = _agent_body_catalog_entry_for_session(
        snapshot, server.universal_registry, session
    )
    observation = latest_compliance_observation(
        snapshot,
        server.universal_registry.compliance_protocol,
        subject_root=session_root,
        policy_root=entry.policy_root,
    )
    assert observation is not None
    evidence = read_court_attestation(
        snapshot,
        server.universal_registry.attestation_protocol,
        observation.evidence_root,
    )
    return json.loads(snapshot.cells[evidence.payload_root].atom.decode("utf-8"))


def test_default_server_runner_allows_compliant_work_claim(tmp_path, monkeypatch):
    calls = []

    def runner(invocation):
        calls.append(invocation.external_parameters["runtime"])
        return _court_result()

    server, client = _server(tmp_path, monkeypatch, runner)
    try:
        work_root = _work(server, "court:runtime-runner:green")
        client.bind_agent_session(
            runtime="codex", external_session_id="court-runtime-runner-green"
        )
        result = _claim(client, work_root)
    finally:
        server.close()

    assert calls == ["codex"]
    assert result["claimed"] is True
    assert result["compliance_evidence"].startswith("attestation:evidence:")


def test_default_server_runner_refuses_and_names_failed_check(tmp_path, monkeypatch):
    def runner(_invocation):
        return _court_result(failed={"required-hooks"})

    server, client = _server(tmp_path, monkeypatch, runner)
    try:
        work_root = _work(server, "court:runtime-runner:red")
        client.bind_agent_session(
            runtime="codex", external_session_id="court-runtime-runner-red"
        )
        with pytest.raises(MachineResponseError, match="compliance policy"):
            _claim(client, work_root)
        payload = _latest_payload(server, client.agent_session_root)
    finally:
        server.close()

    predicate = payload["predicate"]
    assert predicate["result"] == "fail"
    assert predicate["checks"]["required-hooks"] is False
    assert "required-hooks" in predicate["details"]["reason"]


def test_no_attached_universal_runner_still_fails_closed_unavailable():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(),
        key_provider=provider,
    )
    session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:unavailable-runner",
        runtime="codex",
        external_session_fingerprint="a" * 64,
        authentication_context=registry.authorization.session.context(),
    )
    work_root, _wire, _revision = create_universal_governed_work(
        store,
        registry,
        title="Unavailable runtime auditor",
        priority=10,
        x=20,
        y=20,
        authentication_context=registry.authorization.session.context(),
    )

    observation, evidence_root, _ = attest_universal_runtime_compliance(
        store,
        registry,
        agent_session_root=session.root_id,
        runtime="codex",
        external_session_fingerprint="a" * 64,
    )
    evidence = read_court_attestation(
        store.snapshot(), registry.attestation_protocol, evidence_root
    )
    payload = json.loads(
        store.snapshot().cells[evidence.payload_root].atom.decode("utf-8")
    )

    assert payload["predicate"]["details"]["reason"] == (
        "runtime compliance adapter unavailable"
    )
    with pytest.raises(PermissionError, match="compliance policy"):
        claim_next_universal_governed_work(
            store,
            registry,
            agent_session_root=session.root_id,
            compliance_observation_root=observation.root_id,
            authentication_context=registry.authorization.session.context(),
        )
    status = [
        item for item in project_universal_governed_work_status(
            store,
            registry,
            authentication_context=registry.authorization.session.context(),
        )["items"]
        if item["root"] == work_root
    ]
    assert status[0]["operational"]["current_state_label"] == "OPEN"


def test_shared_runtime_prepare_attaches_physical_runner(monkeypatch, tmp_path):
    from nodelang import application_server as server_module

    calls = []

    def runner(invocation):
        calls.append(invocation.external_parameters["runtime"])
        return _court_result()

    monkeypatch.setattr(
        server_module, "run_physical_runtime_compliance_court", runner
    )
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"s" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"t" * 32)
    from tests_replica.test_universal_cell_cloud_authority import (
        _SharedJournal,
        _SharedJournalState,
    )

    store = CellStore(journal=_SharedJournal(
        _SharedJournalState(), "court:shared-runtime-compliance"
    ))
    prepared = server_module.prepare_shared_universal_runtime(
        store, key_provider=provider, court_workspace_root=tmp_path
    )
    session, _ = begin_universal_runtime_agent_session(
        prepared.store,
        prepared.registry,
        session_root="app:agent-session:runtime:shared-runner",
        runtime="codex",
        external_session_fingerprint="b" * 64,
        authentication_context=prepared.registry.authorization.session.context(),
    )

    observation, _evidence_root, _ = attest_universal_runtime_compliance(
        prepared.store,
        prepared.registry,
        agent_session_root=session.root_id,
        runtime="codex",
        external_session_fingerprint="b" * 64,
    )

    assert calls == ["codex"]
    assert observation.result_root == (
        prepared.registry.compliance_protocol.state("satisfied")
    )
