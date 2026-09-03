from __future__ import annotations

import hashlib

import pytest

from nodelang.cell_attestations import CourtResult, read_court_attestation
from nodelang.cell_compliance import read_compliance_observation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    attest_universal_runtime_compliance,
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_next_universal_governed_work,
    claim_universal_governed_work,
    create_universal_governed_work,
    project_universal_governed_work_status,
    restore_universal_application,
)


class _RuntimeComplianceRunner:
    def __init__(self, *, green: bool) -> None:
        self.green = green
        self.invocations = []

    def __call__(self, invocation):
        self.invocations.append(invocation)
        checks = {
            "runtime-detected": self.green,
            "required-hooks": self.green,
            "schema-valid": self.green,
            "brain-connected": self.green,
            "scope-gate": self.green,
            "workshop-authority": self.green,
        }
        return CourtResult(
            passed=self.green,
            checks=checks,
            details={"adapter": "court-runtime-compliance"},
        )


def _application(*, green: bool):
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    runner = _RuntimeComplianceRunner(green=green)
    store, registry = build_universal_application(
        resolve_map_path(),
        key_provider=provider,
        runtime_compliance_runner=runner,
    )
    return store, registry, runner


def _session(store, registry, label: str):
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()
    root = "app:agent-session:runtime:" + label
    session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root=root,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=registry.authorization.session.context(),
    )
    return session.root_id, fingerprint


def _work(store, registry):
    root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Claim only after runtime compliance",
        priority=100,
        x=400,
        y=300,
        authentication_context=registry.authorization.session.context(),
    )
    return root


def _state(store, registry, work_root):
    status = project_universal_governed_work_status(
        store,
        registry,
        authentication_context=registry.authorization.session.context(),
    )
    return next(
        item["operational"]["current_state_label"]
        for item in status["items"] if item["root"] == work_root
    )


def test_machine_runtime_cannot_claim_without_current_graph_compliance():
    store, registry, _runner = _application(green=True)
    work_root = _work(store, registry)
    session_root, _fingerprint = _session(store, registry, "missing-court")

    with pytest.raises(PermissionError, match="compliance"):
        claim_next_universal_governed_work(
            store,
            registry,
            agent_session_root=session_root,
            authentication_context=registry.authorization.session.context(),
        )

    assert _state(store, registry, work_root) == "OPEN"


def test_green_signed_observation_is_bound_to_exact_session_and_allows_claim():
    store, registry, runner = _application(green=True)
    work_root = _work(store, registry)
    session_root, fingerprint = _session(store, registry, "green-court")

    observation, evidence_root, revision = attest_universal_runtime_compliance(
        store,
        registry,
        agent_session_root=session_root,
        runtime="codex",
        external_session_fingerprint=fingerprint,
    )
    assert revision == store.revision
    assert runner.invocations
    evidence = read_court_attestation(
        store.snapshot(), registry.attestation_protocol, evidence_root
    )
    assert evidence.result_root == registry.attestation_protocol.states["passed"]
    bound = read_compliance_observation(
        store.snapshot(), registry.compliance_protocol, observation.root_id
    )
    assert bound.subject_root == session_root
    founder_entry = next(
        entry for entry in registry.agent_body_catalog.entries.values()
        if entry.runtime == "*"
    )
    assert bound.policy_root == founder_entry.policy_root
    assert bound.evidence_root == evidence_root

    claimed = claim_next_universal_governed_work(
        store,
        registry,
        agent_session_root=session_root,
        compliance_observation_root=observation.root_id,
        authentication_context=registry.authorization.session.context(),
    )
    assert claimed["claimed"] is True
    assert claimed["work"]["root"] == work_root
    assert _state(store, registry, work_root) == "CLAIMED"


def test_red_or_other_session_compliance_cannot_change_work_state():
    store, registry, _runner = _application(green=False)
    work_root = _work(store, registry)
    session_a, fingerprint = _session(store, registry, "red-court-a")
    session_b, _ = _session(store, registry, "red-court-b")
    observation, evidence_root, _ = attest_universal_runtime_compliance(
        store,
        registry,
        agent_session_root=session_a,
        runtime="codex",
        external_session_fingerprint=fingerprint,
    )
    evidence = read_court_attestation(
        store.snapshot(), registry.attestation_protocol, evidence_root
    )
    assert evidence.result_root == registry.attestation_protocol.states["failed"]

    for session_root in (session_a, session_b):
        with pytest.raises(PermissionError):
            claim_next_universal_governed_work(
                store,
                registry,
                agent_session_root=session_root,
                compliance_observation_root=observation.root_id,
                authentication_context=registry.authorization.session.context(),
            )
        assert _state(store, registry, work_root) == "OPEN"


def test_runtime_compliance_authority_restores_and_re_admits_its_runner():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"u" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"v" * 32)
    runner = _RuntimeComplianceRunner(green=True)
    store, registry = build_universal_application(
        resolve_map_path(),
        key_provider=provider,
        runtime_compliance_runner=runner,
    )
    work_root = _work(store, registry)
    session_root, fingerprint = _session(
        store, registry, "restored-compliance-court"
    )

    restored_store, restored = restore_universal_application(
        resolve_map_path(),
        store,
        key_provider=provider,
        runtime_compliance_runner=runner,
    )
    observation, _evidence_root, _revision = (
        attest_universal_runtime_compliance(
            restored_store,
            restored,
            agent_session_root=session_root,
            runtime="codex",
            external_session_fingerprint=fingerprint,
        )
    )
    claimed = claim_universal_governed_work(
        restored_store,
        restored,
        agent_session_root=session_root,
        work_root=work_root,
        compliance_observation_root=observation.root_id,
        authentication_context=restored.authorization.session.context(),
    )
    assert claimed["claimed"] is True
    assert claimed["work"]["root"] == work_root
