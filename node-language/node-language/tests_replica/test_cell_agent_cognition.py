"""Adversarial courts for graph-native, proposal-only agent cognition."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import nodelang.cell_agent_cognition as cognition_module
from nodelang.cell_adapters import (
    bootstrap_adapter_protocol,
    build_adapter_catalog,
    build_adapter_definition,
    release_adapter_definition,
)
from nodelang.cell_agent_body import (
    append_context_entry,
    begin_agent_session,
    bootstrap_agent_body_protocol,
    compose_agent_body,
    read_agent_body,
    read_agent_session,
)
from nodelang.cell_agent_cognition import (
    bind_agent_body_model,
    bootstrap_agent_cognition_protocol,
    build_agent_cognition_definitions,
    build_cognition_budget,
    build_model_descriptor,
    create_cognition_request,
    create_proposal,
    make_model_binding_verifier,
    make_proposal_verifier,
    open_agent_cognition_protocol,
    provision_session_cognition,
    read_cognition_request,
    read_model_binding,
    read_model_descriptor,
    read_proposal,
    release_model_descriptor,
    revoke_model_descriptor,
)
from nodelang.cell_authorization import (
    AuthenticationBroker,
    AuthorizationDenied,
    AuthorizationRequest,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
)
from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    build_catalog,
    compose_catalog_instance,
    compose_relation_backed_catalog_instance,
    verify_released_catalog,
    verify_released_definition,
)
from nodelang.cell_relation_contract import (
    compose_validated_relation,
    open_relation_contract_protocol,
    read_relation_contract,
    resolve_relation_contract_authority,
)
from nodelang.cell_status_ledger import current_status, open_status_ledger_protocol
from nodelang.cell_protocols import compose_relation_cells, read_relation, rewire_incidence
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


ROOTS = {
    "identity": b"Founder agent",
    "owner-role": b"owner",
    "context": b"Authorized context",
    "provenance": b"Verified source",
    "trust": b"trusted",
    "sensitivity": b"internal",
    "audience": b"founder",
    "lifecycle": b"WIP",
    "purpose": b"Operate ArchHub",
    "context-interface": b"read context",
    "registry-interface": b"edit registry",
    "provider": b"Test model provider",
    "model": b"Test model",
    "model-revision": b"model-sha256:001",
    "input-contract": b"ArchHub context manifest v1",
    "modality-text": b"text",
    "data-policy": b"synthetic and T0 only",
    "descriptor-evidence": b"tests_replica/test_cell_agent_cognition.py",
    "proposal-payload": b'{"operation":"inspect"}',
}


def _request(world, action, object_root, *, lineage=(), interface=None):
    return AuthorizationRequest(
        action_root=world["authorization"].actions[action],
        object_root=object_root,
        resource_lineage_roots=tuple(lineage),
        interface_root=interface,
        purpose_root="purpose",
        classification_root="sensitivity",
        audience_root="audience",
        lifecycle_state_root="lifecycle",
        operational_state_root=world["agent"].state("active"),
    )


def _world(database=None):
    store = CellStore(database)
    assembly = bootstrap_assembly_protocol(store, prefix="test:assembly")
    cognition = bootstrap_agent_cognition_protocol(store, prefix="test:cognition")
    definitions = build_agent_cognition_definitions(
        store,
        assembly,
        cognition,
        prefix="test:cognition-library",
    )
    catalog = build_catalog(
        store,
        assembly,
        definitions.roots,
        catalog_id="test:catalog:v1",
        version="1.0.0",
    )
    store.commit(
        store.revision,
        create=tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
            for root, atom in ROOTS.items()
        ),
    )
    model_identity = compose_relation_cells(
        (
            (cognition.role("descriptor-provider"), "provider"),
            (cognition.role("descriptor-model"), "model"),
            (cognition.role("descriptor-model-revision"), "model-revision"),
        ),
        relation_id="test:model-identity:v1",
    )
    store.commit(store.revision, create=model_identity.cells)
    adapter = bootstrap_adapter_protocol(store, prefix="test:adapter")
    model_adapter = build_adapter_definition(
        store,
        adapter,
        adapter_id="test:model-adapter:v1",
        name="Test proposal-only model adapter",
        actions=("model.propose",),
        locations=(),
        location_roots=(model_identity.build.root_id,),
        datatypes=("application/archhub-proposal+graph",),
        evidence="tests_replica/test_cell_agent_cognition.py",
    )
    release_adapter_definition(store, adapter, model_adapter.root_id)
    adapter_catalog = build_adapter_catalog(
        store,
        adapter,
        (model_adapter.root_id,),
        catalog_id="test:adapter-catalog:v1",
        version="1.0.0",
    )
    agent = bootstrap_agent_body_protocol(store, prefix="test:agent-body")
    authorization = bootstrap_authorization_protocol(
        store, prefix="test:authorization"
    )
    store.commit(
        store.revision,
        create=(
            *compose_relation_cells(
                (("owner-role", "identity"),), relation_id="view"
            ).cells,
            *compose_relation_cells(
                (("owner-role", "identity"),), relation_id="scope"
            ).cells,
        ),
    )
    actions = authorization.actions
    rule_specs = (
        ("create", "identity", None, None, None, None),
        ("inspect", "view", None, None, None, "owner-role"),
        ("traverse", "scope", None, None, None, "owner-role"),
        ("edit", "scope", "registry-interface", "purpose", "sensitivity", None),
        ("read", "context", "context-interface", "purpose", "sensitivity", None),
    )
    rules = tuple(
        build_authorization_rule(
            store,
            authorization,
            rule_id="test:rule:%s:%s" % (action, object_root),
            effect="permit",
            principal_root="identity",
            object_root=object_root,
            action_root=actions[action],
            interface_root=interface,
            purpose_root=purpose,
            classification_root=classification,
            audience_root="audience",
            lifecycle_state_root="lifecycle",
            operational_state_root=agent.state("active"),
            subject_relation_root=owner_relation,
        )
        for (
            action,
            object_root,
            interface,
            purpose,
            classification,
            owner_relation,
        ) in rule_specs
    )
    policy = build_authorization_policy(
        store,
        authorization,
        rules,
        policy_id="test:agent-policy",
        version="1.0.0",
    )
    releases = PolicyReleaseBroker()
    release_authorization_policy(
        store,
        authorization,
        policy,
        releases,
        releases.mint_from_trusted_administrator(policy, "identity"),
        administrator_root="identity",
    )
    broker = AuthenticationBroker()
    auth_context = broker.mint_authenticated_context(
        "identity",
        tenant_root=None,
        assurance_root="trust",
        lifetime_seconds=120,
    )
    return {
        "store": store,
        "assembly": assembly,
        "cognition": cognition,
        "definitions": definitions,
        "catalog": catalog,
        "adapter": adapter,
        "model_adapter": model_adapter.root_id,
        "adapter_catalog": adapter_catalog,
        "agent": agent,
        "authorization": authorization,
        "policy": policy,
        "rules": rules,
        "broker": broker,
        "auth_context": auth_context,
    }


def _descriptor(
    world,
    *,
    descriptor_id="test:model-descriptor:v1",
    data_policy_roots=("sensitivity",),
    provider_root="provider",
    model_root="model",
    model_revision_root="model-revision",
):
    store = world["store"]
    adapter = world["adapter"]
    budget = build_cognition_budget(
        store,
        world["cognition"],
        budget_id=descriptor_id + ":budget",
        max_context_entries=8,
        max_input_bytes=65536,
        max_output_bytes=4096,
        max_latency_ms=30000,
        max_cost_microunits=0,
    )
    adapter_projection = cognition_module.verify_released_adapter(
        store.snapshot(), adapter, world["model_adapter"]
    )
    descriptor = build_model_descriptor(
        store,
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        descriptor_id=descriptor_id,
        provider_root=provider_root,
        model_root=model_root,
        model_revision_root=model_revision_root,
        input_contract_root="input-contract",
        output_definition_root=world["definitions"].proposal_root,
        modality_roots=("modality-text",),
        context_limit=8,
        data_policy_roots=data_policy_roots,
        evidence_roots=("descriptor-evidence",),
        version="1.0.0",
        budget_root=budget,
        adapter_action_root=adapter_projection.action_roots[0],
        adapter_location_root=adapter_projection.location_roots[0],
        adapter_datatype_root=adapter_projection.datatype_roots[0],
        reviewer_root="identity",
    )
    release_model_descriptor(
        store,
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "edit",
            descriptor.root_id,
            lineage=("scope",),
            interface="registry-interface",
        ),
        descriptor.root_id,
        reviewer_root="identity",
        policy_root=world["policy"],
    )
    return read_model_descriptor(
        store.snapshot(),
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        descriptor.root_id,
    )


def _body(world):
    return compose_agent_body(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        AuthorizationRequest(
            action_root=world["authorization"].actions["create"],
            object_root="identity",
            audience_root="audience",
            lifecycle_state_root="lifecycle",
            operational_state_root=world["agent"].state("active"),
        ),
        body_id="agent-body",
        identity_root="identity",
        authority_policy_root=world["policy"],
        authority_action_roots=tuple(
            world["authorization"].actions[name]
            for name in ("create", "inspect", "traverse", "read", "edit")
        ),
        authority_rule_roots=world["rules"],
        lifecycle_root="lifecycle",
        state_root=world["agent"].state("active"),
        visibility_root="audience",
    )


def _binding_verifier(world):
    return make_model_binding_verifier(
        world["cognition"],
        world["assembly"],
        world["catalog"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
    )


def _proposal_verifier(world):
    return make_proposal_verifier(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        model_binding_verifier=_binding_verifier(world),
    )


def _bind(world, descriptor, *, binding_id="test:model-binding:v1"):
    return bind_agent_body_model(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "edit",
            "agent-body",
            lineage=("scope",),
            interface="registry-interface",
        ),
        binding_id=binding_id,
        body_root="agent-body",
        descriptor_root=descriptor.root_id,
        adapter_root=world["model_adapter"],
        policy_roots=(world["policy"],),
        budget_root=descriptor.budget_root,
    )


def _session(world):
    verifier = _binding_verifier(world)
    return begin_agent_session(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        AuthorizationRequest(
            action_root=world["authorization"].actions["inspect"],
            object_root="view",
            audience_root="audience",
            lifecycle_state_root="lifecycle",
            operational_state_root=world["agent"].state("active"),
        ),
        AuthorizationRequest(
            action_root=world["authorization"].actions["traverse"],
            object_root="scope",
            audience_root="audience",
            lifecycle_state_root="lifecycle",
            operational_state_root=world["agent"].state("active"),
        ),
        session_id="agent-session",
        body_root="agent-body",
        subject_root="identity",
        owner_role_root="owner-role",
        view_session_root="view",
        scope_root="scope",
        focus_root=world["agent"].state("unbound"),
        assignment_root=world["agent"].state("unbound"),
        model_binding_verifier=verifier,
    )


def _append_context(world):
    verifier = _binding_verifier(world)
    return append_context_entry(
        world["store"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "read",
            "context",
            lineage=("scope",),
            interface="context-interface",
        ),
        _request(
            world,
            "edit",
            "agent-session:context-registry",
            lineage=("scope",),
            interface="registry-interface",
        ),
        session_root="agent-session",
        context_root="context",
        provenance_root="provenance",
        trust_root="trust",
        sensitivity_root="sensitivity",
        audience_root="audience",
        lifecycle_root="lifecycle",
        purpose_root="purpose",
        idempotency_key="context-selection-1",
        model_binding_verifier=verifier,
    )


def _provision_cognition(world):
    return provision_session_cognition(
        world["store"],
        world["cognition"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "edit",
            "agent-session",
            lineage=("scope",),
            interface="registry-interface",
        ),
        session_root="agent-session",
        model_binding_verifier=_binding_verifier(world),
    )


def _cognition_request(world, context_entry_root):
    return create_cognition_request(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        (
            _request(
                world,
                "read",
                "context",
                lineage=("scope",),
                interface="context-interface",
            ),
        ),
        _request(
            world,
            "edit",
            "agent-session:cognition-request-registry",
            lineage=("scope",),
            interface="registry-interface",
        ),
        session_root="agent-session",
        context_entry_roots=(context_entry_root,),
        intent_root="purpose",
        purpose_root="purpose",
        idempotency_key="request-1",
        model_binding_verifier=_binding_verifier(world),
    )


def _proposal(world, request_root, *, rationale="Inspect the authorised context"):
    return create_proposal(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "edit",
            "agent-session:proposal-registry",
            lineage=("scope",),
            interface="registry-interface",
        ),
        request_root=request_root,
        operation_root=world["definitions"].model_descriptor_root,
        payload_root="proposal-payload",
        target_roots=("context",),
        rationale=rationale,
        uncertainty=0.25,
        evidence_roots=("context",),
        idempotency_key="proposal-1",
        model_binding_verifier=_binding_verifier(world),
    )


def test_cognition_protocol_and_four_released_definitions_are_graph_authority():
    world = _world()
    protocol = open_agent_cognition_protocol(
        world["store"].snapshot(), prefix="test:cognition"
    )
    assert protocol == world["cognition"]
    assert world["definitions"].roots == (
        world["definitions"].model_descriptor_root,
        world["definitions"].model_binding_root,
        world["definitions"].cognition_request_root,
        world["definitions"].proposal_root,
    )
    catalog = verify_released_catalog(
        world["store"].snapshot(), world["assembly"], world["catalog"]
    )
    assert catalog.definition_roots == world["definitions"].roots
    for root in world["definitions"].roots:
        verify_released_definition(
            world["store"].snapshot(), world["assembly"], root
        )


def test_cognition_definitions_publish_released_graph_held_relation_contracts():
    world = _world()
    snapshot = world["store"].snapshot()
    contract_roots = []
    protocol_roots = []
    for root in world["definitions"].roots:
        definition = verify_released_definition(
            snapshot, world["assembly"], root
        )
        assert len(definition.rule_roots) == 1
        assert len(definition.capability_roots) == 1
        assert len(definition.obligation_roots) == 3
        relation_protocol = open_relation_contract_protocol(
            snapshot, definition.capability_roots[0], budget=100_000
        )
        contract = read_relation_contract(
            snapshot,
            relation_protocol,
            definition.rule_roots[0],
            budget=100_000,
        )
        assert contract.lifecycle_root == relation_protocol.state("released")
        contract_roots.append(contract.root_id)
        protocol_roots.append(relation_protocol.root_id)
    assert len(set(contract_roots)) == 4
    assert len(set(protocol_roots)) == 1


def test_cognition_instance_shares_protected_contract_instead_of_cloning_it():
    world = _world()
    snapshot = world["store"].snapshot()
    definition_root = world["definitions"].model_descriptor_root
    definition = verify_released_definition(
        snapshot, world["assembly"], definition_root
    )
    contract_root = definition.rule_roots[0]
    assert contract_root in definition.shared_roots
    assert contract_root not in definition.part_roots

    composed = compose_catalog_instance(
        snapshot,
        world["assembly"],
        world["catalog"],
        definition_root,
        token="shared-cognition-contract",
    )
    assert contract_root not in composed.instance.cell_map
    world["store"].commit(snapshot.revision, create=composed.cells)
    members = read_relation(
        world["store"].snapshot(), composed.instance.root_id, budget=100_000
    )
    assert [
        member.participant_id for member in members
        if member.role_id == world["assembly"].role("rule")
    ] == [contract_root]
    protocol = open_relation_contract_protocol(
        world["store"].snapshot(), definition.capability_roots[0], budget=100_000
    )
    assert read_relation_contract(
        world["store"].snapshot(), protocol, contract_root, budget=100_000
    ).root_id == contract_root


def test_validated_cognition_relation_is_wrapped_as_one_visible_wip_instance():
    world = _world()
    descriptor = _descriptor(world)
    snapshot = world["store"].snapshot()
    definition_root = world["definitions"].model_descriptor_root
    definition = verify_released_definition(
        snapshot, world["assembly"], definition_root
    )
    authority = resolve_relation_contract_authority(
        snapshot,
        capability_roots=definition.capability_roots,
        rule_roots=definition.rule_roots,
        budget=100_000,
    )
    descriptor_members = read_relation(
        snapshot, descriptor.root_id, budget=100_000
    )
    candidate = compose_validated_relation(
        snapshot,
        authority.protocol,
        authority.contract.root_id,
        ((member.role_id, member.participant_id)
         for member in descriptor_members),
        relation_id="candidate:model-descriptor",
        budget=100_000,
    )
    wrapped = compose_relation_backed_catalog_instance(
        snapshot,
        world["assembly"],
        world["catalog"],
        definition_root,
        candidate,
        token="relation-backed-model-descriptor",
    )
    world["store"].commit(snapshot.revision, create=wrapped.cells)
    instance_members = read_relation(
        world["store"].snapshot(), wrapped.instance.root_id, budget=100_000
    )
    assert candidate.root_id in {
        member.participant_id for member in instance_members
        if member.role_id == world["assembly"].role("part")
    }
    assert authority.contract.root_id in {
        member.participant_id for member in instance_members
        if member.role_id == world["assembly"].role("rule")
    }
    assert read_relation(
        world["store"].snapshot(), candidate.root_id, budget=100_000
    )


def test_descriptor_release_and_binding_pin_the_exact_model_and_adapter():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    binding = _bind(world, descriptor)
    verifier = _binding_verifier(world)
    body = read_agent_body(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-body",
        model_binding_verifier=verifier,
    )
    assert body.model_binding_root == binding.root_id
    assert binding.descriptor_root == descriptor.root_id
    assert binding.adapter_root == world["model_adapter"]
    assert binding.descriptor_digest == descriptor.digest
    assert binding.creation_revision == world["store"].cell_created_revision(
        binding.root_id
    )


def test_descriptor_cannot_claim_a_model_outside_adapter_identity_capability():
    world = _world()
    with pytest.raises(InvalidCell, match="model identity capability"):
        _descriptor(world, provider_root="data-policy")


def test_session_binding_is_historical_and_does_not_follow_body_rebinding():
    world = _world()
    first = _descriptor(world)
    _body(world)
    first_binding = _bind(world, first)
    session = _session(world)
    assert session.model_binding_root == first_binding.root_id

    second = _descriptor(world, descriptor_id="test:model-descriptor:v2")
    second_binding = _bind(world, second, binding_id="test:model-binding:v2")
    verifier = _binding_verifier(world)
    current_body = read_agent_body(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-body",
        model_binding_verifier=verifier,
    )
    restored_session = read_agent_session(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-session",
        model_binding_verifier=verifier,
    )
    assert current_body.model_binding_root == second_binding.root_id
    assert restored_session.model_binding_root == first_binding.root_id


def test_unbound_session_cannot_create_cognition_or_proposal():
    world = _world()
    _body(world)
    _session(world)
    revision = world["store"].revision
    with pytest.raises(InvalidCell, match="model binding"):
        provision_session_cognition(
            world["store"],
            world["cognition"],
            world["agent"],
            world["authorization"],
            world["broker"],
            world["auth_context"],
            _request(
                world,
                "edit",
                "agent-session",
                lineage=("scope",),
                interface="registry-interface",
            ),
            session_root="agent-session",
            model_binding_verifier=_binding_verifier(world),
        )
    assert world["store"].revision == revision


def test_cognition_module_has_no_provider_execution_or_effect_path():
    source = Path(cognition_module.__file__).read_text(encoding="utf-8").lower()
    for forbidden in (
        "import openai",
        "import anthropic",
        "from openai",
        "from anthropic",
        "invoke(",
        "requests.",
        "httpx.",
        "subprocess",
        "socket",
        "effect receipt",
    ):
        assert forbidden not in source


def test_tampered_descriptor_binding_and_catalogue_fail_closed():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    binding = _bind(world, descriptor)
    snapshot = world["store"].snapshot()
    members = read_relation(snapshot, descriptor.root_id, budget=100_000)
    model_incidence = next(
        member.incidence_id
        for member in members
        if member.role_id == world["cognition"].role("descriptor-model")
    )
    rewire_incidence(world["store"], model_incidence, "provider")
    with pytest.raises(
        InvalidCell, match="descriptor.*drifted|model identity capability"
    ):
        read_model_descriptor(
            world["store"].snapshot(),
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            descriptor.root_id,
        )
    with pytest.raises(InvalidCell):
        read_model_binding(
            world["store"].snapshot(),
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            binding.root_id,
        )


def test_cognition_request_and_proposal_are_immutable_bounded_graph_records():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    binding = _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    session_cognition = _provision_cognition(world)
    assert session_cognition.request_registry_root == (
        "agent-session:cognition-request-registry"
    )

    request = _cognition_request(world, entry_root)
    assert request.binding_root == binding.root_id
    assert request.context_entry_roots == (entry_root,)
    assert request.context_roots == ("context",)
    assert request.source_revision + 1 == world["store"].cell_created_revision(
        request.root_id
    )
    assert request.revision_chain_digest == world["store"].revision_chain_digest(
        request.source_revision
    )
    before_target = world["store"].read("context")
    before_revision = world["store"].revision

    proposal = _proposal(world, request.root_id)
    assert proposal.request_root == request.root_id
    assert proposal.session_root == "agent-session"
    assert proposal.binding_root == binding.root_id
    assert proposal.target_roots == ("context",)
    assert proposal.state_root == world["cognition"].state("proposed")
    assert world["store"].read("context") == before_target
    assert world["store"].revision == before_revision + 1

    verifier = _proposal_verifier(world)
    session = read_agent_session(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-session",
        model_binding_verifier=_binding_verifier(world),
        proposal_verifier=verifier,
    )
    assert session.proposal_roots == (proposal.root_id,)
    assert read_proposal(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        proposal.root_id,
        model_binding_verifier=_binding_verifier(world),
    ) == proposal

    replay_revision = world["store"].revision
    assert _cognition_request(world, entry_root) == request
    assert _proposal(world, request.root_id) == proposal
    assert world["store"].revision == replay_revision
    with pytest.raises(InvalidCell, match="reused for other content"):
        _proposal(world, request.root_id, rationale="Different content")


def test_descriptor_release_is_an_authenticated_graph_mutation():
    world = _world()
    store = world["store"]
    adapter = cognition_module.verify_released_adapter(
        store.snapshot(), world["adapter"], world["model_adapter"]
    )
    budget = build_cognition_budget(
        store,
        world["cognition"],
        budget_id="test:unreleased-descriptor:budget",
        max_context_entries=2,
        max_input_bytes=1024,
        max_output_bytes=512,
        max_latency_ms=1000,
        max_cost_microunits=0,
    )
    descriptor = build_model_descriptor(
        store,
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        descriptor_id="test:unreleased-descriptor",
        provider_root="provider",
        model_root="model",
        model_revision_root="model-revision",
        input_contract_root="input-contract",
        output_definition_root=world["definitions"].proposal_root,
        modality_roots=("modality-text",),
        context_limit=2,
        data_policy_roots=("data-policy",),
        evidence_roots=("descriptor-evidence",),
        version="1.0.0",
        budget_root=budget,
        adapter_action_root=adapter.action_roots[0],
        adapter_location_root=adapter.location_roots[0],
        adapter_datatype_root=adapter.datatype_roots[0],
        reviewer_root="identity",
    )
    unauthorised_context = world["broker"].mint_authenticated_context(
        "provider",
        tenant_root=None,
        assurance_root="trust",
        lifetime_seconds=120,
    )
    with pytest.raises(AuthorizationDenied):
        release_model_descriptor(
            store,
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["agent"],
            world["authorization"],
            world["broker"],
            unauthorised_context,
            _request(
                world,
                "edit",
                descriptor.root_id,
                lineage=("scope",),
                interface="registry-interface",
            ),
            descriptor.root_id,
            reviewer_root="identity",
            policy_root=world["policy"],
        )
    assert read_model_descriptor(
        store.snapshot(),
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        descriptor.root_id,
        require_released=False,
    ).lifecycle_root == world["cognition"].state("draft")

    release_model_descriptor(
        store,
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "edit",
            descriptor.root_id,
            lineage=("scope",),
            interface="registry-interface",
        ),
        descriptor.root_id,
        reviewer_root="identity",
        policy_root=world["policy"],
    )
    released = read_model_descriptor(
        store.snapshot(),
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        descriptor.root_id,
    )
    assert released.release_request_root in store.snapshot().cells
    assert released.release_receipt_root in store.snapshot().cells
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        release_model_descriptor(
            store,
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["agent"],
            world["authorization"],
            world["broker"],
            world["auth_context"],
            _request(
                world,
                "edit",
                descriptor.root_id,
                lineage=("scope",),
                interface="registry-interface",
            ),
            descriptor.root_id,
            reviewer_root="identity",
            policy_root=world["policy"],
        )


def test_descriptor_revocation_is_separate_authenticated_status_and_blocks_use():
    world = _world()
    descriptor = _descriptor(world)
    body = _body(world)
    revoke_model_descriptor(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["agent"],
        world["authorization"],
        world["broker"],
        world["auth_context"],
        _request(
            world,
            "edit",
            descriptor.root_id,
            lineage=("scope",),
            interface="registry-interface",
        ),
        descriptor.root_id,
        reviewer_root="identity",
        policy_root=world["policy"],
    )
    snapshot = world["store"].snapshot()
    status = open_status_ledger_protocol(
        snapshot,
        prefix=world["definitions"].status_ledger_root.removesuffix(":root"),
    )
    event = current_status(snapshot, status, descriptor.root_id)
    assert event is not None
    assert event.state_root == status.state("revoked")
    assert event.subject_digest == descriptor.digest
    with pytest.raises(InvalidCell, match="revoked"):
        read_model_descriptor(
            snapshot,
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            descriptor.root_id,
        )
    with pytest.raises(InvalidCell, match="revoked"):
        bind_agent_body_model(
            world["store"],
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            world["broker"],
            world["auth_context"],
            _request(
                world,
                "edit",
                body.root_id,
                lineage=("scope",),
                interface="registry-interface",
            ),
            binding_id="binding:revoked-descriptor",
            body_root=body.root_id,
            descriptor_root=descriptor.root_id,
            adapter_root=world["model_adapter"],
            policy_roots=(world["policy"],),
            budget_root=descriptor.budget_root,
        )


def test_binding_rechecks_authentication_at_commit_boundary(monkeypatch):
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    revision = world["store"].revision
    evaluate = cognition_module._evaluate_agent_requests

    def revoke_after_evaluation(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        world["broker"].revoke(world["auth_context"])
        return result

    monkeypatch.setattr(
        cognition_module, "_evaluate_agent_requests", revoke_after_evaluation
    )
    with pytest.raises(AuthorizationDenied, match="unknown authenticated context"):
        _bind(world, descriptor)
    assert world["store"].revision == revision
    assert "test:model-binding:v1" not in world["store"].snapshot().cells
    assert read_agent_body(
        world["store"].snapshot(),
        world["agent"],
        world["authorization"],
        "agent-body",
    ).model_binding_root is None


def test_binding_receipt_and_session_binding_tampering_fail_closed():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    binding = _bind(world, descriptor)
    _session(world)
    snapshot = world["store"].snapshot()
    receipt_members = read_relation(
        snapshot, binding.authorization_receipt_root, budget=100_000
    )
    reason_root = next(
        member.participant_id
        for member in receipt_members
        if member.role_id == world["agent"].role("receipt-reason")
    )
    reason_cell = snapshot.cells[reason_root]
    world["store"].commit(
        snapshot.revision,
        replace=(Cell(
            reason_cell.id,
            reason_cell.link0,
            reason_cell.link1,
            b"default-deny",
        ),),
    )
    with pytest.raises(InvalidCell, match="authorization evidence"):
        read_model_binding(
            world["store"].snapshot(),
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            binding.root_id,
        )

    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    members = read_relation(
        world["store"].snapshot(), "agent-session", budget=100_000
    )
    incidence = next(
        member.incidence_id
        for member in members
        if member.role_id == world["agent"].role("session-model-binding")
    )
    rewire_incidence(world["store"], incidence, "provider")
    with pytest.raises(InvalidCell):
        read_agent_session(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-session",
            model_binding_verifier=_binding_verifier(world),
        )


def test_request_rechecks_authentication_and_publishes_no_partial_manifest(
    monkeypatch,
):
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    revision = world["store"].revision
    evaluate = cognition_module._evaluate_agent_requests

    def revoke_after_evaluation(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        world["broker"].revoke(world["auth_context"])
        return result

    monkeypatch.setattr(
        cognition_module, "_evaluate_agent_requests", revoke_after_evaluation
    )
    with pytest.raises(AuthorizationDenied, match="unknown authenticated context"):
        _cognition_request(world, entry_root)
    assert world["store"].revision == revision
    assert not any(
        root.startswith("cognition-request:")
        for root in world["store"].snapshot().cells
    )


def test_proposal_rejects_out_of_context_target_and_oversized_graph_payload():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    request = _cognition_request(world, entry_root)
    revision = world["store"].revision
    provider_before = world["store"].read("provider")
    with pytest.raises(AuthorizationDenied, match="authorised context"):
        create_proposal(
            world["store"],
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            world["broker"],
            world["auth_context"],
            _request(
                world,
                "edit",
                "agent-session:proposal-registry",
                lineage=("scope",),
                interface="registry-interface",
            ),
            request_root=request.root_id,
            operation_root=world["definitions"].proposal_root,
            payload_root="proposal-payload",
            target_roots=("provider",),
            rationale="Change a target outside the authorised manifest",
            uncertainty=0.5,
            evidence_roots=("context",),
            idempotency_key="outside-target",
            model_binding_verifier=_binding_verifier(world),
        )
    assert world["store"].revision == revision
    assert world["store"].read("provider") == provider_before

    world["store"].commit(
        world["store"].revision,
        create=(Cell(
            "oversized-payload",
            NULL_CELL_ID,
            NULL_CELL_ID,
            b"x" * 5000,
        ),),
    )
    oversized_revision = world["store"].revision
    with pytest.raises(InvalidCell, match="byte budget"):
        create_proposal(
            world["store"],
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            world["broker"],
            world["auth_context"],
            _request(
                world,
                "edit",
                "agent-session:proposal-registry",
                lineage=("scope",),
                interface="registry-interface",
            ),
            request_root=request.root_id,
            operation_root=world["definitions"].proposal_root,
            payload_root="oversized-payload",
            target_roots=("context",),
            rationale="Oversized output",
            uncertainty=0.5,
            evidence_roots=("context",),
            idempotency_key="oversized",
            model_binding_verifier=_binding_verifier(world),
        )
    assert world["store"].revision == oversized_revision


def test_proposal_rechecks_authentication_at_commit_boundary(monkeypatch):
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    request = _cognition_request(world, entry_root)
    revision = world["store"].revision
    evaluate = cognition_module._evaluate_agent_requests

    def revoke_after_evaluation(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        world["broker"].revoke(world["auth_context"])
        return result

    monkeypatch.setattr(
        cognition_module, "_evaluate_agent_requests", revoke_after_evaluation
    )
    with pytest.raises(AuthorizationDenied, match="unknown authenticated context"):
        _proposal(world, request.root_id)
    assert world["store"].revision == revision
    assert read_relation(
        world["store"].snapshot(),
        "agent-session:proposal-registry",
        budget=100_000,
    ) == ()
    assert read_relation(
        world["store"].snapshot(),
        world["cognition"].registry("proposal"),
        budget=100_000,
    ) == ()


def test_request_proposal_and_binding_reopen_from_sqlite(tmp_path):
    database = tmp_path / "agent-cognition.sqlite3"
    world = _world(database)
    descriptor = _descriptor(world)
    _body(world)
    binding = _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    request = _cognition_request(world, entry_root)
    proposal = _proposal(world, request.root_id)
    revision = world["store"].revision
    digest = world["store"].revision_chain_digest()
    world["store"].close()

    reopened = CellStore(database)
    assert reopened.revision == revision
    assert reopened.revision_chain_digest() == digest
    verifier = make_model_binding_verifier(
        world["cognition"],
        world["assembly"],
        world["catalog"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
    )
    assert read_model_binding(
        reopened.snapshot(),
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        binding.root_id,
    ) == binding
    assert read_cognition_request(
        reopened,
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        request.root_id,
        model_binding_verifier=verifier,
    ) == request
    assert read_proposal(
        reopened,
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        proposal.root_id,
        model_binding_verifier=verifier,
    ) == proposal
    reopened.close()


def _proposal_world():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    request = _cognition_request(world, entry_root)
    proposal = _proposal(world, request.root_id)
    return world, descriptor, request, proposal


def test_reopening_proposal_traverses_all_four_graph_held_contracts(monkeypatch):
    world, _descriptor_root, _request_root, proposal = _proposal_world()
    snapshot = world["store"].snapshot()
    expected_contracts = {
        verify_released_definition(snapshot, world["assembly"], root).rule_roots[0]
        for root in world["definitions"].roots
    }
    validated = set()
    actual_validate = cognition_module.validate_relation

    def recording_validate(*args, **kwargs):
        validated.add(args[2])
        return actual_validate(*args, **kwargs)

    monkeypatch.setattr(cognition_module, "validate_relation", recording_validate)
    assert read_proposal(
        world["store"],
        world["assembly"],
        world["catalog"],
        world["cognition"],
        world["definitions"],
        world["adapter"],
        world["adapter_catalog"],
        world["agent"],
        world["authorization"],
        proposal.root_id,
        model_binding_verifier=_binding_verifier(world),
    ) == proposal
    assert validated == expected_contracts


def test_released_descriptor_pins_referenced_semantic_content():
    world = _world()
    descriptor = _descriptor(world)
    snapshot = world["store"].snapshot()
    model = snapshot.cells["model"]
    world["store"].commit(
        snapshot.revision,
        replace=(Cell(model.id, model.link0, model.link1, b"Other model"),),
    )
    with pytest.raises(InvalidCell, match="descriptor.*drifted"):
        read_model_descriptor(
            world["store"].snapshot(),
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            descriptor.root_id,
        )


def test_proposal_pins_payload_content_and_session_uses_the_full_verifier():
    world, _descriptor_root, _request_root, proposal = _proposal_world()
    snapshot = world["store"].snapshot()
    payload = snapshot.cells[proposal.payload_root]
    world["store"].commit(
        snapshot.revision,
        replace=(Cell(
            payload.id,
            payload.link0,
            payload.link1,
            b'{"operation":"different"}',
        ),),
    )
    with pytest.raises(InvalidCell, match="payload|Proposal.*drifted"):
        read_proposal(
            world["store"],
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            proposal.root_id,
            model_binding_verifier=_binding_verifier(world),
        )

    world, _descriptor_root, _request_root, proposal = _proposal_world()
    snapshot = world["store"].snapshot()
    target_incidence = next(
        member.incidence_id
        for member in read_relation(snapshot, proposal.root_id, budget=100_000)
        if member.role_id == world["cognition"].role("proposal-target")
    )
    rewire_incidence(world["store"], target_incidence, "provider")
    forged = replace(proposal, target_roots=("provider",), digest="")
    digest_cell = world["store"].read(proposal.digest_root)
    world["store"].commit(
        world["store"].revision,
        replace=(Cell(
            digest_cell.id,
            digest_cell.link0,
            digest_cell.link1,
            cognition_module._proposal_digest(
                world["store"].snapshot(), forged
            ).encode("ascii"),
        ),),
    )
    with pytest.raises((InvalidCell, AuthorizationDenied)):
        read_agent_session(
            world["store"].snapshot(),
            world["agent"],
            world["authorization"],
            "agent-session",
            model_binding_verifier=_binding_verifier(world),
            proposal_verifier=_proposal_verifier(world),
        )


def test_cognition_request_enforces_input_bytes_and_data_policy():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    snapshot = world["store"].snapshot()
    context = snapshot.cells["context"]
    world["store"].commit(
        snapshot.revision,
        replace=(Cell(
            context.id,
            context.link0,
            context.link1,
            b"x" * 70_000,
        ),),
    )
    with pytest.raises(InvalidCell, match="input.*byte|context.*budget"):
        _cognition_request(world, entry_root)

    world = _world()
    descriptor = _descriptor(world, data_policy_roots=("data-policy",))
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    with pytest.raises(AuthorizationDenied, match="data policy"):
        _cognition_request(world, entry_root)


def test_request_receipts_bind_the_complete_authorization_decision():
    world = _world()
    descriptor = _descriptor(world)
    _body(world)
    _bind(world, descriptor)
    _session(world)
    entry_root = _append_context(world)
    _provision_cognition(world)
    request = _cognition_request(world, entry_root)
    receipt_root = request.read_receipt_roots[0]
    snapshot = world["store"].snapshot()
    action_incidence = next(
        member.incidence_id
        for member in read_relation(snapshot, receipt_root, budget=100_000)
        if member.role_id == world["agent"].role("receipt-action")
    )
    rewire_incidence(
        world["store"],
        action_incidence,
        world["authorization"].actions["edit"],
    )
    with pytest.raises(InvalidCell, match="evidence|receipt"):
        read_cognition_request(
            world["store"],
            world["assembly"],
            world["catalog"],
            world["cognition"],
            world["definitions"],
            world["adapter"],
            world["adapter_catalog"],
            world["agent"],
            world["authorization"],
            request.root_id,
            model_binding_verifier=_binding_verifier(world),
        )


def test_descriptor_release_has_no_parallel_trusted_reviewer_mint():
    assert not hasattr(cognition_module, "CognitionReleaseBroker")
