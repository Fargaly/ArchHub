"""Courts for BABOOM's deterministic, graph-native claimed-Work plan draft."""
from __future__ import annotations

from nodelang.cell_value_graph import read_value_graph
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_universal_governed_work,
    create_universal_governed_work,
    draft_universal_baboom_work_plan,
    prepare_universal_baboom_model_cognition_request,
    read_universal_baboom_work_plan,
    project_universal_governed_work_status,
    request_universal_baboom_model_execution,
)


def test_claimed_baboom_work_receives_one_non_executing_plan_value_graph():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    session_root = "app:agent-session:runtime:baboom-work-plan-court"
    session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root=session_root,
        runtime="baboom-execution",
        external_session_fingerprint="a" * 64,
        catalog_entry_root="app:agent-body-catalog:entry:baboom-execution",
        authentication_context=context,
    )
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Prepare a governed BIM coordination review",
        description="Inspect the coordination evidence and preserve the privacy boundary.",
        priority=40,
        external_key="court:baboom-work-plan",
        x=520,
        y=300,
        authentication_context=context,
    )
    claim_universal_governed_work(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )

    empty_root, empty_plan, empty_revision = read_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    assert empty_root is None
    assert empty_plan is None
    assert empty_revision == store.revision

    plan_root, reused, revision = draft_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )

    assert reused is False
    assert revision == store.revision
    plan = read_value_graph(
        store.snapshot(), registry.value_graph_protocol, plan_root
    )
    assert plan["kind"] == "baboom-deterministic-work-plan/v2"
    assert plan["state"] == "draft"
    assert plan["work"] == work_root
    assert plan["execution"] == "none"
    assert plan["model_output"] == "not-used"
    assert plan["priority_assessment"] == {
        "declared_priority": 40,
        "released_order": [
            "Safety and data-loss risk",
            "Founder pin",
            "Blocking dependency",
            "Failed active court",
            "Accepted due work and fairness",
            "Model-proposed relevance",
        ],
        "model_authority": "none",
    }
    assert len(plan["steps"]) == 5
    assert all(step["effect"] != "execute" for step in plan["steps"])

    read_root, read_plan, read_revision = read_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    assert read_root == plan_root
    assert read_revision == revision
    assert read_plan == {
        "state": "draft",
        "summary": "Prepare a governed BIM coordination review",
        "priority_assessment": {
            "declared_priority": 40,
            "released_order": (
                "Safety and data-loss risk",
                "Founder pin",
                "Blocking dependency",
                "Failed active court",
                "Accepted due work and fairness",
                "Model-proposed relevance",
            ),
            "model_authority": "none",
        },
        "steps": (
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
        ),
        "execution": "none",
        "model_output": "not-used",
        "live_activity": {
            "model": "not-requested",
            "connector": "not-requested",
        },
    }

    work = next(
        item
        for item in project_universal_governed_work_status(
            store, registry, authentication_context=context
        )["items"]
        if item["root"] == work_root
    )
    assert work["interfaces"]["plan"]["target"] == plan_root
    assert work["operational"]["current_state_label"] == "CLAIMED"
    assert work["claimant_session"] == session.root_id

    repeated_root, repeated, repeated_revision = draft_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    assert repeated_root == plan_root
    assert repeated is True
    assert repeated_revision == revision


def test_work_plan_live_activity_projects_pending_model_delegation_without_mutation():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    session, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:baboom-work-plan-activity-court",
        runtime="baboom-execution",
        external_session_fingerprint="b" * 64,
        catalog_entry_root="app:agent-body-catalog:entry:baboom-execution",
        authentication_context=context,
    )
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Review live graph activity for one claimed Work",
        description="Prepare a bounded review without an external effect.",
        priority=45,
        external_key="court:baboom-work-plan-activity",
        x=540,
        y=320,
        authentication_context=context,
    )
    claim_universal_governed_work(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    plan_root, _, _ = draft_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    stored_before = read_value_graph(
        store.snapshot(), registry.value_graph_protocol, plan_root
    )
    cognition, _ = prepare_universal_baboom_model_cognition_request(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        provider="local",
        model="qwen3:8b",
        authentication_context=context,
    )
    request_universal_baboom_model_execution(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        provider="local",
        model="qwen3:8b",
        data_class="internal-text",
        cognition_request_root=cognition.root_id,
        authentication_context=context,
    )

    read_root, projected, _ = read_universal_baboom_work_plan(
        store,
        registry,
        agent_session_root=session.root_id,
        work_root=work_root,
        authentication_context=context,
    )

    assert read_root == plan_root
    assert projected is not None
    assert projected["execution"] == "none"
    assert projected["model_output"] == "not-used"
    assert projected["live_activity"] == {
        "model": "awaiting-approval",
        "connector": "not-requested",
    }
    assert read_value_graph(
        store.snapshot(), registry.value_graph_protocol, plan_root
    ) == stored_before
