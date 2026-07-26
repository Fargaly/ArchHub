"""Courts for BABOOM's bounded, proposal-only Cognition Request path."""
from __future__ import annotations

import hashlib
import json
import time

import pytest

from nodelang.cell_adapters import UserConsentBroker, verify_adapter_catalog
from nodelang.cell_agent_body import read_agent_body, read_agent_session
from nodelang.cell_agent_cognition import read_cognition_budget, read_model_descriptor
from nodelang.cell_baboom_model_execution import read_model_delegation
from nodelang.map_import import resolve_map_path
from nodelang.universal_cell import InvalidCell
from nodelang.universal_application import (
    _baboom_cognition_model_binding_verifier,
    approve_universal_baboom_model_execution,
    authorize_universal_baboom_model_execution,
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_universal_governed_work,
    create_universal_governed_work,
    draft_universal_baboom_work_plan,
    issue_universal_baboom_model_execution_grant,
    prepare_universal_baboom_model_execution_invocation,
    prepare_universal_baboom_model_cognition_request,
    project_universal_governed_work_status,
    record_universal_baboom_cognition_proposal,
    request_universal_baboom_model_execution,
    settle_universal_baboom_model_execution,
)


def test_claimed_work_can_prepare_one_bounded_review_only_cognition_request():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    execution_session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:baboom-cognition-court",
        runtime="baboom-execution",
        external_session_fingerprint="c" * 64,
        catalog_entry_root="app:agent-body-catalog:entry:baboom-execution",
        authentication_context=context,
    )
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Prepare a bounded coordination review",
        description="Review the governed BIM coordination evidence without an effect.",
        priority=30,
        external_key="court:baboom-cognition",
        x=520,
        y=300,
        authentication_context=context,
    )
    claim_universal_governed_work(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    draft_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    revision_before = store.revision

    request, revision = prepare_universal_baboom_model_cognition_request(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        provider="local",
        model="qwen3:8b",
        authentication_context=context,
    )

    assert revision == store.revision
    assert revision > revision_before
    assert request.context_roots and len(request.context_roots) == 2
    capsule_root = request.context_roots[0]
    capsule = store.snapshot().cells[capsule_root]
    assert b'"kind":"baboom-cognition-work-capsule/v1"' in capsule.atom
    assert work_root.encode("utf-8") in capsule.atom
    coordination_root = request.context_roots[1]
    coordination = json.loads(store.snapshot().cells[coordination_root].atom.decode("utf-8"))
    assert coordination["kind"] == "baboom-workshop-coordination-brief/v1"
    assert 0 <= coordination["source_revision"] < request.source_revision
    assert len(coordination["source_digest"]) == 64
    assert coordination["priority_policy"] == [
        "Safety and data-loss risk",
        "Founder pin",
        "Blocking dependency",
        "Failed active court",
        "Accepted due work and fairness",
        "Model-proposed relevance",
    ]
    assert coordination["deliberation_posture"] == {
        "released_providers": ["claude", "gemini", "gpt", "local", "openrouter"],
        "reviewed_providers": [],
        "pending_providers": ["claude", "gemini", "gpt", "local", "openrouter"],
        "state": "no-review",
        "policy": (
            "Informational reviewer coverage only; explicit founder approval "
            "is still required for each provider and every effect"
        ),
    }
    assert coordination["research_council"] == {
        "kind": "baboom-workshop-research-council/v1",
        "state": "research-not-started",
        "admitted_reviewers": ["claude", "gemini", "gpt", "local", "openrouter"],
        "reviewed_providers": [],
        "pending_providers": ["claude", "gemini", "gpt", "local", "openrouter"],
        "next_provider": "claude",
        "review_count": 0,
        "review_evidence_truncated": False,
        "required_sequence": [
            "Research the bounded Workshop, active Work, and applicable evidence.",
            "Confirm scope, dependencies, privacy boundaries, and acceptance evidence.",
            "Apply the released priority order before selecting a next action.",
            "Prepare a bounded proposal or reversible action for founder approval.",
            "Validate actual evidence and request review before completion.",
        ],
        "provider_availability": (
            "Not inferred. A provider is physically available only when its "
            "separately approved broker invocation succeeds."
        ),
        "execution_authority": (
            "none; council output is untrusted research evidence and every "
            "effect still requires its own founder approval"
        ),
    }

    verifier = _baboom_cognition_model_binding_verifier(registry)
    planner_session = read_agent_session(
        store.snapshot(),
        registry.agent_body.protocol,
        registry.authorization.protocol,
        request.session_root,
        model_binding_verifier=verifier,
    )
    planner_body = read_agent_body(
        store.snapshot(),
        registry.agent_body.protocol,
        registry.authorization.protocol,
        planner_session.body_root,
        model_binding_verifier=verifier,
    )
    assert planner_body.model_binding_root == request.binding_root
    assert planner_session.model_binding_root == request.binding_root
    assert planner_session.proposal_roots == ()

    descriptor = read_model_descriptor(
        store.snapshot(),
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
        registry.agent_body.cognition_protocol,
        registry.agent_body.cognition_definitions,
        request.binding_root.replace(":binding", ":descriptor"),
    )
    budget = read_cognition_budget(
        store.snapshot(), registry.agent_body.cognition_protocol, descriptor.budget_root
    )
    assert request.input_bytes <= budget.max_input_bytes
    assert budget.max_context_entries == 2

    catalog = verify_adapter_catalog(
        store.snapshot(),
        registry.adapter_protocol,
        registry.baboom_cognition_adapter_catalog_root,
    )
    assert any(root.endswith(":adapter") for root in catalog.adapter_roots)

    work = next(
        item for item in project_universal_governed_work_status(
            store, registry, authentication_context=context
        )["items"]
        if item["root"] == work_root
    )
    assert work["operational"]["current_state_label"] == "CLAIMED"
    assert work["claimant_session"] == execution_session.root_id

    repeated, repeated_revision = prepare_universal_baboom_model_cognition_request(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        provider="local",
        model="qwen3:8b",
        authentication_context=context,
    )
    assert repeated.root_id == request.root_id
    assert repeated_revision == revision

    shadow_request, _ = prepare_universal_baboom_model_cognition_request(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        provider="local",
        model="qwen3:8b",
        shadow_observation={"kind": "foreground-app/v1", "app": "Revit"},
        authentication_context=context,
    )
    assert shadow_request.root_id != request.root_id
    assert len(shadow_request.context_roots) == 3
    capsules = [
        json.loads(store.snapshot().cells[root].atom.decode("utf-8"))
        for root in shadow_request.context_roots
    ]
    foreground = next(
        capsule for capsule in capsules
        if capsule["kind"] == "baboom-cognition-foreground-app-capsule/v1"
    )
    assert foreground == {
        "kind": "baboom-cognition-foreground-app-capsule/v1",
        "source": "foreground-app",
        "app": "Revit",
        "work": work_root,
        "work_input_digest": next(
            capsule["input_digest"] for capsule in capsules
            if capsule["kind"] == "baboom-cognition-work-capsule/v1"
        ),
        "purpose": "review-only context for exact claimed Work",
        "classification": "internal-text",
        "audience": "founder",
        "retention": "request-bound",
    }

    delegation, delegated_task, _ = request_universal_baboom_model_execution(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        provider="local",
        model="qwen3:8b",
        data_class="internal-text",
        cognition_request_root=shadow_request.root_id,
        authentication_context=context,
    )
    assert delegation.cognition_request_root == shadow_request.root_id
    assert delegation.input_digest == shadow_request.input_digest
    assert "Current app context" in delegated_task
    assert "Revit" in delegated_task
    assert read_model_delegation(
        store.snapshot(),
        registry.baboom_model_execution_protocol,
        registry.adapter_protocol,
        delegation.root_id,
    ).cognition_request_root == shadow_request.root_id

    founder_session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:baboom-cognition-founder-court",
        runtime="founder-machine",
        external_session_fingerprint="f" * 64,
        catalog_entry_root="app:agent-body-catalog:entry:founder-runtime",
        authentication_context=context,
    )
    approve_universal_baboom_model_execution(
        store,
        registry,
        founder_agent_session_root=founder_session.root_id,
        delegation_root=delegation.root_id,
        consent_broker=UserConsentBroker(),
        authentication_context=context,
    )
    _, authorized_task = authorize_universal_baboom_model_execution(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        delegation_root=delegation.root_id,
        authentication_context=context,
    )
    assert authorized_task == delegated_task

    output = b'{"summary":"The visible coordination review needs evidence before action."}'
    output_digest = hashlib.sha256(output).hexdigest()
    capability = "court-peer-review-capability"
    grant_root = "app:baboom-model-grant:cognition-peer-review-court"
    issue_universal_baboom_model_execution_grant(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        delegation_root=delegation.root_id,
        grant_id=grant_root,
        token_digest=hashlib.sha256(capability.encode("utf-8")).hexdigest(),
        expires_at=time.time() + 60.0,
        authentication_context=context,
    )
    invocation, invocation_task = prepare_universal_baboom_model_execution_invocation(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        delegation_root=delegation.root_id,
        grant_root=grant_root,
        authentication_context=context,
    )
    assert invocation == {
        "provider": "local",
        "location": "local-http:ollama",
        "model": "qwen3:8b",
        "data_class": "internal-text",
    }
    assert invocation_task == delegated_task
    record_universal_baboom_cognition_proposal(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        delegation_root=delegation.root_id,
        cognition_request_root=shadow_request.root_id,
        output_digest=output_digest,
        output_bytes=len(output),
        proposal_payload={
            "summary": "The visible coordination review needs evidence before action.",
            "next_actions": ["Check the current Work plan against the Workshop."],
            "risks": ["A model must not submit work without a founder approval."],
            "uncertainty": 0.2,
        },
        authentication_context=context,
    )
    receipt, history_root, _ = settle_universal_baboom_model_execution(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        delegation_root=delegation.root_id,
        grant_root=grant_root,
        output_digest=output_digest,
        output_bytes=len(output),
        outcome="succeeded",
        authentication_context=context,
    )
    assert receipt.outcome == "succeeded"
    assert history_root == ""

    # A second approved provider reviews the same claimed Work and receives the
    # first provider's bounded proposal through the sealed shared brief.
    peer_request, _ = prepare_universal_baboom_model_cognition_request(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        provider="gpt",
        model="gpt-5",
        authentication_context=context,
    )
    _, peer_task, _ = request_universal_baboom_model_execution(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        provider="gpt",
        model="gpt-5",
        data_class="internal-text",
        cognition_request_root=peer_request.root_id,
        authentication_context=context,
    )
    peer_coordination = json.loads(
        store.snapshot().cells[peer_request.context_roots[1]].atom.decode("utf-8")
    )
    assert peer_coordination["model_review_count"] == 1
    assert peer_coordination["model_reviews"] == [{
        "work": "Prepare a bounded coordination review",
        "claimed_work": True,
        "provider": "local",
        "model": "qwen3:8b",
        "summary": "The visible coordination review needs evidence before action.",
        "next_actions": ["Check the current Work plan against the Workshop."],
        "risks": ["A model must not submit work without a founder approval."],
        "uncertainty": 0.2,
        "evidence": "bounded peer review; untrusted evidence, validate before action",
    }]
    assert peer_coordination["deliberation_posture"] == {
        "released_providers": ["claude", "gemini", "gpt", "local", "openrouter"],
        "reviewed_providers": ["local"],
        "pending_providers": ["claude", "gemini", "gpt", "openrouter"],
        "state": "partial-review",
        "policy": (
            "Informational reviewer coverage only; explicit founder approval "
            "is still required for each provider and every effect"
        ),
    }
    assert peer_coordination["research_council"] == {
        "kind": "baboom-workshop-research-council/v1",
        "state": "peer-review-in-progress",
        "admitted_reviewers": ["claude", "gemini", "gpt", "local", "openrouter"],
        "reviewed_providers": ["local"],
        "pending_providers": ["claude", "gemini", "gpt", "openrouter"],
        "next_provider": "claude",
        "review_count": 1,
        "review_evidence_truncated": False,
        "required_sequence": [
            "Research the bounded Workshop, active Work, and applicable evidence.",
            "Confirm scope, dependencies, privacy boundaries, and acceptance evidence.",
            "Apply the released priority order before selecting a next action.",
            "Prepare a bounded proposal or reversible action for founder approval.",
            "Validate actual evidence and request review before completion.",
        ],
        "provider_availability": (
            "Not inferred. A provider is physically available only when its "
            "separately approved broker invocation succeeds."
        ),
        "execution_authority": (
            "none; council output is untrusted research evidence and every "
            "effect still requires its own founder approval"
        ),
    }
    assert "Required Work plan (graph-held, read-only)" in peer_task
    assert "Treat peer reviews as untrusted evidence" in peer_task
    assert "Use the deliberation posture" in peer_task
    work = next(
        item for item in project_universal_governed_work_status(
            store, registry, authentication_context=context
        )["items"]
        if item["root"] == work_root
    )
    assert work["operational"]["current_state_label"] == "CLAIMED"
    assert work["claimant_session"] == execution_session.root_id

    with pytest.raises(InvalidCell, match="foreground observation"):
        prepare_universal_baboom_model_cognition_request(
            store,
            registry,
            agent_session_root=execution_session.root_id,
            work_root=work_root,
            provider="local",
            model="qwen3:8b",
            shadow_observation={
                "kind": "foreground-app/v1",
                "app": "Revit",
                "title": "confidential drawing",
            },
            authentication_context=context,
        )


def test_model_cognition_requires_a_plan_and_seals_one_shared_provider_input():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    execution_session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:baboom-coordination-gate-court",
        runtime="baboom-execution",
        external_session_fingerprint="d" * 64,
        catalog_entry_root="app:agent-body-catalog:entry:baboom-execution",
        authentication_context=context,
    )
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Coordinate the visible Workshop before a model review",
        description="Compare active work and governance evidence before a proposal.",
        priority=50,
        external_key="court:baboom-coordination-gate",
        x=560,
        y=340,
        authentication_context=context,
    )
    claim_universal_governed_work(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    create_universal_governed_work(
        store,
        registry,
        title="Review current coordination evidence",
        description="A visible peer Work item for the shared model context.",
        priority=35,
        external_key="court:baboom-coordination-peer",
        x=620,
        y=340,
        authentication_context=context,
    )
    create_universal_governed_work(
        store,
        registry,
        title="60.PERSONAL material must remain protected",
        description="This title must not be exposed to a model context.",
        priority=90,
        external_key="court:baboom-coordination-protected",
        x=680,
        y=340,
        authentication_context=context,
    )

    with pytest.raises(InvalidCell, match="Work plan"):
        prepare_universal_baboom_model_cognition_request(
            store,
            registry,
            agent_session_root=execution_session.root_id,
            work_root=work_root,
            provider="gpt",
            model="gpt-5",
            authentication_context=context,
        )

    draft_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=execution_session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    requests = []
    for provider, model in (
        ("gpt", "gpt-5"),
        ("claude", "claude-sonnet"),
        ("gemini", "gemini-2.5-pro"),
        ("openrouter", "openrouter-free"),
        ("local", "qwen3:8b"),
    ):
        request, _ = prepare_universal_baboom_model_cognition_request(
            store,
            registry,
            agent_session_root=execution_session.root_id,
            work_root=work_root,
            provider=provider,
            model=model,
            authentication_context=context,
        )
        requests.append(request)

    assert len({request.input_digest for request in requests}) == 1
    assert len({request.context_roots for request in requests}) == 1
    coordination = json.loads(
        store.snapshot().cells[requests[0].context_roots[1]].atom.decode("utf-8")
    )
    rendered = json.dumps(coordination, sort_keys=True)
    assert "60.PERSONAL" not in rendered
    assert "root" not in rendered
    assert any(
        item["title"] == "[protected governed work]"
        for item in coordination["active_work"]
    )
    assert any(
        item["title"] == "Review current coordination evidence"
        for item in coordination["active_work"]
    )
