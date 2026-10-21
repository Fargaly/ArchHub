"""Operational court for governed higher-level catalogue assemblies."""
import json

import pytest

from nodelang.cell_catalog import project_catalog
from nodelang.cell_interactions import InteractionProjectionBroker
from nodelang.cell_state_machine import (
    build_evidence,
    read_evidence,
    read_evidence_admission,
    read_instance_state_machine,
    read_transition,
    transition_machine,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    CAPABILITY_EDIT_VALUE,
    CAPABILITY_TRANSITION,
    build_universal_application,
    connect_universal_roots,
    ensure_universal_interface_value_interactions,
    ensure_universal_operational_transition_interactions,
    instantiate_universal_definition,
    project_universal_canvas,
    submit_universal_edit_value_interaction,
    submit_universal_transition_interaction,
    transition_universal_operational_state,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, InvalidCell


EXPECTED_DOMAIN_NAMES = (
    "Database Transaction",
    "Monetary Intent",
    "Geometry Asset",
    "CDE Governed Asset",
    "Knowledge Branch",
    "Governed Work",
    "Permission Request",
)


def _definition(projection, name):
    return next(item["id"] for item in projection["catalog"] if item["name"] == name)


def test_governed_domain_assemblies_are_released_catalogue_content():
    store, registry = build_universal_application(resolve_map_path())
    catalog = project_catalog(
        store.snapshot(),
        registry.assembly_protocol,
        registry.standard_library.catalog_root,
    )
    assert tuple(item["name"] for item in catalog) == (
        "Ordered List", "Watcher", "Versioned Asset", *EXPECTED_DOMAIN_NAMES,
        "Model Descriptor", "Model Binding", "Cognition Request", "Proposal",
    )
    assert len(registry.standard_library.governed_domains.definition_roots) == 7


@pytest.mark.parametrize("name", EXPECTED_DOMAIN_NAMES)
def test_every_governed_domain_exposes_operational_and_revision_axes(name):
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, name), x=420, y=180
    )
    projection = project_universal_canvas(store, registry)
    assert projection["selected"] == root
    assembly = projection["selected_assembly"]
    assert assembly["operational"] is not None
    assert assembly["operational"]["current_state_label"]
    assert assembly["operational"]["admitted_transitions"]
    assert assembly["lifecycle"] is not None
    wip = next(item for item in assembly["lifecycle"]["states"] if item["name"] == "WIP")
    assert wip["head_count"] == 1


def test_governed_work_exposes_every_control_boundary_as_a_wireable_interface():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Governed Work"), x=420, y=180
    )
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    interfaces = {item["name"]: item for item in assembly["interfaces"]}
    assert interfaces["content"]["mode"] == "state"
    control_interfaces = {
        name: item for name, item in interfaces.items() if name != "content"
    }
    assert set(control_interfaces) == {
        "title", "description", "priority", "external-key", "plan",
        "scope", "cde-container", "requirements", "dependencies",
        "required-capabilities", "applicable-policy", "inputs", "outputs",
    }
    assert all(
        item["mode"] == "connection" for item in control_interfaces.values()
    )
    assert all(item["editable"] for item in control_interfaces.values())

    scope_root = registry.map.domains["brain"]
    scope_source = next(
        port
        for node in initial["nodes"]
        if node["id"] == scope_root
        for port in node["ports"]
        if (
            port["side"] == "source"
            and port["connectable"]
            and port["name"] == "Scope for Governed Work"
        )
    )
    wire_root, _ = connect_universal_roots(
        store,
        registry,
        scope_root,
        root,
        source_interface=scope_source["id"],
        target_interface=interfaces["scope"]["id"],
    )
    projected = project_universal_canvas(store, registry)
    work = next(node for node in projected["nodes"] if node["id"] == root)
    rewired = {
        item["name"]: item for item in work["assembly"]["interfaces"]
    }
    assert rewired["scope"]["target"] == scope_root
    wire = next(wire for wire in projected["wires"] if wire["id"] == wire_root)
    assert wire["source_interface"] == scope_source["id"]
    assert wire["target_interface"] == interfaces["scope"]["id"]


def test_governed_work_claim_records_actor_and_session_without_publishing():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Governed Work"), x=420, y=180
    )
    before = project_universal_canvas(store, registry)["selected_assembly"]
    claim = next(
        item for item in before["operational"]["admitted_transitions"]
        if item["event_label"] == "claim"
    )
    wip_before = next(
        item for item in before["lifecycle"]["states"]
        if item["name"] == "WIP"
    )["heads"][0]["revision"]
    transition_universal_operational_state(
        store,
        registry,
        root,
        claim["event"],
        before["operational"]["current_state"],
    )
    claimed = project_universal_canvas(store, registry)["selected_assembly"]
    event = claimed["operational"]["history"][-1]
    founder = registry.view_sessions[registry.authorization.subject_root]
    assert claimed["operational"]["current_state_label"] == "CLAIMED"
    assert event["actor"] == registry.authorization.subject_root
    assert event["context"] == [founder.root_id]
    wip_after = next(
        item for item in claimed["lifecycle"]["states"]
        if item["name"] == "WIP"
    )["heads"][0]["revision"]
    assert wip_after == wip_before

    before_stale = store.revision
    with pytest.raises(InvalidCell, match="stale|not admitted"):
        transition_universal_operational_state(
            store,
            registry,
            root,
            claim["event"],
            before["operational"]["current_state"],
        )
    assert store.revision == before_stale


def test_knowledge_branch_submit_uses_a_graph_issued_transition_control():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Knowledge Branch"), x=420, y=180
    )
    authority = registry.authorization
    view = registry.view_sessions[authority.subject_root]
    browser_session_root = "test:knowledge-branch-browser-session"
    store.commit(store.revision, create=(Cell(
        browser_session_root, NULL_CELL_ID, NULL_CELL_ID,
        b"test browser session",
    ),))
    projection = project_universal_canvas(
        store,
        registry,
        authentication_context=authority.session.context(),
    )
    operational = projection["selected_assembly"]["operational"]
    submit = next(
        item for item in operational["admitted_transitions"]
        if item["event_label"] == "submit"
    )
    assert submit["control"] is not None
    interactions = ensure_universal_operational_transition_interactions(
        store, registry, authority.subject_root, projection
    )
    assert interactions == {submit["control"]: next(iter(interactions.values()))}

    broker = InteractionProjectionBroker()
    handle = broker.mint(
        store.snapshot(),
        session_root=browser_session_root,
        subject_root=authority.subject_root,
        view_root=view.root_id,
    )
    broker.issue(
        handle,
        store.snapshot(),
        registry.interaction_protocol,
        tuple(interactions),
        tuple(interactions.values()),
        rule_protocol=registry.rule_protocol,
        transaction_protocol=registry.transaction_protocol,
        admitted_nontransaction_action_roots=(CAPABILITY_TRANSITION,),
    )
    execution = submit_universal_transition_interaction(
        store,
        registry,
        broker,
        handle,
        interaction_root=interactions[submit["control"]],
        control_root=submit["control"],
        event_root=submit["event"],
        expected_revision=store.revision,
        authentication_context=authority.session.context(),
    )
    assert execution.revision == store.revision
    submitted = project_universal_canvas(
        store,
        registry,
        authentication_context=authority.session.context(),
    )["selected_assembly"]
    assert submitted["operational"]["current_state_label"] == "REVIEWING"
    assert submitted["operational"]["history"][-1]["event_label"] == "submit"


def test_knowledge_branch_review_requires_its_declared_issuer_not_any_adapter():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Knowledge Branch"), x=420, y=180
    )
    protocol = registry.standard_library.state_machine_protocol
    machine = read_instance_state_machine(
        store.snapshot(), registry.assembly_protocol, protocol, root
    )
    submit = next(
        read_transition(store.snapshot(), protocol, transition_root)
        for transition_root in machine.transition_roots
        if store.snapshot().cells[
            read_transition(store.snapshot(), protocol, transition_root).event_root
        ].atom == b"submit"
    )
    actor = "test:knowledge-reviewer"
    other_issuer = "test:other-allowlisted-adapter"
    store.commit(store.revision, create=(
        Cell(actor, NULL_CELL_ID, NULL_CELL_ID, b"Reviewer"),
        Cell(other_issuer, NULL_CELL_ID, NULL_CELL_ID, b"Other adapter"),
    ))
    transition_machine(
        store,
        protocol,
        machine.root_id,
        event_root=submit.event_root,
        expected_state_root=machine.current_state_root,
        actor_root=actor,
    )
    reviewing = read_instance_state_machine(
        store.snapshot(), registry.assembly_protocol, protocol, root
    )
    accept = next(
        read_transition(store.snapshot(), protocol, transition_root)
        for transition_root in reviewing.transition_roots
        if store.snapshot().cells[
            read_transition(store.snapshot(), protocol, transition_root).event_root
        ].atom == b"accept"
    )
    assert len(accept.required_evidence_admission_roots) == 1
    admission = read_evidence_admission(
        store.snapshot(), protocol, accept.required_evidence_admission_roots[0]
    )
    assert store.snapshot().cells[admission.evidence_type_root].atom == b"review record"
    assert store.snapshot().cells[admission.issuer_root].atom == b"review authority"
    projected_accept = next(
        item for item in project_universal_canvas(store, registry)[
            "selected_assembly"
        ]["operational"]["admitted_transitions"]
        if item["event"] == accept.event_root
    )
    assert projected_accept["required_evidence_admissions"] == [{
        "root": admission.root_id,
        "evidence_type": admission.evidence_type_root,
        "evidence_label": "review record",
        "issuer": admission.issuer_root,
        "issuer_label": "review authority",
    }]
    wrong = build_evidence(
        store,
        protocol,
        evidence_id="test:knowledge-review:wrong-issuer",
        evidence_type_root=admission.evidence_type_root,
        payload=b"reviewed",
        issuer_root=other_issuer,
    )
    with pytest.raises(InvalidCell, match="declared admissions"):
        transition_machine(
            store,
            protocol,
            reviewing.root_id,
            event_root=accept.event_root,
            expected_state_root=reviewing.current_state_root,
            actor_root=actor,
            evidence_roots=(wrong,),
            trusted_issuer_roots=(admission.issuer_root, other_issuer),
        )
    right = build_evidence(
        store,
        protocol,
        evidence_id="test:knowledge-review:right-issuer",
        evidence_type_root=admission.evidence_type_root,
        payload=b"reviewed",
        issuer_root=admission.issuer_root,
    )
    transition_machine(
        store,
        protocol,
        reviewing.root_id,
        event_root=accept.event_root,
        expected_state_root=reviewing.current_state_root,
        actor_root=actor,
        evidence_roots=(right,),
        trusted_issuer_roots=(admission.issuer_root, other_issuer),
    )
    assert read_instance_state_machine(
        store.snapshot(), registry.assembly_protocol, protocol, root
    ).current_state_root == accept.to_state_root


def test_monetary_success_requires_external_evidence_and_does_not_change_cde_head():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Monetary Intent"), x=420, y=180
    )
    protocol = registry.standard_library.state_machine_protocol
    machine = read_instance_state_machine(
        store.snapshot(), registry.assembly_protocol, protocol, root
    )
    projection = project_universal_canvas(store, registry)["selected_assembly"]
    wip_before = next(
        item for item in projection["lifecycle"]["states"]
        if item["name"] == "WIP"
    )["heads"][0]["revision"]
    submit = projection["operational"]["admitted_transitions"][0]
    actor = "test:actor"
    issuer = "test:issuer"
    store.commit(store.revision, create=(
        Cell(actor, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
        Cell(issuer, NULL_CELL_ID, NULL_CELL_ID, b"Allowlisted adapter"),
    ))
    transition_machine(
        store, protocol, machine.root_id,
        event_root=submit["event"],
        expected_state_root=machine.current_state_root,
        actor_root=actor,
    )
    pending = project_universal_canvas(store, registry)["selected_assembly"]
    confirm = next(
        item for item in pending["operational"]["admitted_transitions"]
        if item["event_label"] == "confirm"
    )
    with pytest.raises(InvalidCell, match="evidence"):
        transition_machine(
            store, protocol, machine.root_id,
            event_root=confirm["event"],
            expected_state_root=pending["operational"]["current_state"],
            actor_root=actor,
        )
    evidence_type = confirm["required_evidence_types"][0]["root"]
    evidence = build_evidence(
        store,
        protocol,
        evidence_id="test:evidence:provider-confirmation",
        evidence_type_root=evidence_type,
        payload=b'{"provider_state":"succeeded"}',
        issuer_root=issuer,
    )
    transition_machine(
        store, protocol, machine.root_id,
        event_root=confirm["event"],
        expected_state_root=pending["operational"]["current_state"],
        actor_root=actor,
        evidence_roots=(evidence,),
        trusted_issuer_roots=(issuer,),
    )
    settled = project_universal_canvas(store, registry)["selected_assembly"]
    assert settled["operational"]["current_state_label"] == "SUCCEEDED"
    assert settled["operational"]["history"][-1]["evidence"] == [evidence]
    wip_after = next(
        item for item in settled["lifecycle"]["states"]
        if item["name"] == "WIP"
    )["heads"][0]["revision"]
    assert wip_after == wip_before


def test_geometry_fields_are_separate_wirable_interfaces():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    instantiate_universal_definition(
        store, registry, _definition(initial, "Geometry Asset"), x=420, y=180
    )
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    names = {item["name"] for item in assembly["interfaces"]}
    assert {
        "blob-reference", "media-type", "content-digest", "schema", "units",
        "crs", "transform", "labels", "presentation", "provenance",
    }.issubset(names)


def test_permission_request_separates_decision_admission_and_receipt_evidence():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Permission Request"), x=420, y=180
    )
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    assert assembly["operational"]["current_state_label"] == "PENDING"
    admitted = {
        item["event_label"]: item
        for item in assembly["operational"]["admitted_transitions"]
    }
    assert set(admitted) == {"approve", "reject", "cancel"}
    assert {
        item["label"] for item in admitted["approve"]["required_evidence_types"]
    } == {"user decision"}

    machine = read_instance_state_machine(
        store.snapshot(),
        registry.assembly_protocol,
        registry.standard_library.state_machine_protocol,
        root,
    )
    before = store.revision
    with pytest.raises(InvalidCell, match="incomplete"):
        transition_universal_operational_state(
            store,
            registry,
            root,
            admitted["approve"]["event"],
            machine.current_state_root,
        )
    assert store.revision == before


def test_permission_parameters_and_authenticated_decision_use_normal_properties():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Permission Request"), x=420, y=180
    )
    values = {
        "requester": registry.authorization.subject_root,
        "action": "device-key.enroll",
        "object": "device:this-machine",
        "parameters": '{"provider":"platform","algorithm":"ES256"}',
        "reason": "Bind a non-exporting device proof key",
        "expires-at": "2100-01-01T00:00:00Z",
    }
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    authority = registry.authorization
    view = registry.view_sessions[authority.subject_root]
    browser_session_root = "test:permission-request-browser-session"
    store.commit(store.revision, create=(Cell(
        browser_session_root, NULL_CELL_ID, NULL_CELL_ID,
        b"test browser session",
    ),))
    for name, value in values.items():
        projection = project_universal_canvas(
            store,
            registry,
            authentication_context=authority.session.context(),
        )
        interface = next(
            item for item in projection["selected_interfaces"]
            if item["name"] == name
        )
        assert interface["editable"] is True
        interactions, _facts, _specifications = (
            ensure_universal_interface_value_interactions(
                store, registry, authority.subject_root, projection
            )
        )
        broker = InteractionProjectionBroker()
        handle = broker.mint(
            store.snapshot(),
            session_root=browser_session_root,
            subject_root=authority.subject_root,
            view_root=view.root_id,
        )
        broker.issue(
            handle,
            store.snapshot(),
            registry.interaction_protocol,
            tuple(interactions),
            tuple(interactions.values()),
            rule_protocol=registry.rule_protocol,
            transaction_protocol=registry.transaction_protocol,
            admitted_nontransaction_action_roots=(CAPABILITY_EDIT_VALUE,),
        )
        execution = submit_universal_edit_value_interaction(
            store,
            registry,
            broker,
            handle,
            interaction_root=interactions[interface["control"]],
            control_root=interface["control"],
            event_root="app:interaction-event:change",
            event_facts=[{
                "input": interface["event_fact_input"],
                "value": value,
            }],
            expected_revision=store.revision,
            authentication_context=authority.session.context(),
        )
        assert execution.revision == store.revision

    pending = project_universal_canvas(store, registry)["selected_assembly"]
    approve = next(
        item for item in pending["operational"]["admitted_transitions"]
        if item["event_label"] == "approve"
    )
    assert approve["user_decision"] is True
    assert approve["control"] is not None
    interactions = ensure_universal_operational_transition_interactions(
        store,
        registry,
        authority.subject_root,
        project_universal_canvas(
            store,
            registry,
            authentication_context=authority.session.context(),
        ),
    )
    broker = InteractionProjectionBroker()
    handle = broker.mint(
        store.snapshot(),
        session_root=browser_session_root,
        subject_root=authority.subject_root,
        view_root=view.root_id,
    )
    broker.issue(
        handle,
        store.snapshot(),
        registry.interaction_protocol,
        tuple(interactions),
        tuple(interactions.values()),
        rule_protocol=registry.rule_protocol,
        transaction_protocol=registry.transaction_protocol,
        admitted_nontransaction_action_roots=(CAPABILITY_TRANSITION,),
    )
    before = store.revision
    execution = submit_universal_transition_interaction(
        store,
        registry,
        broker,
        handle,
        interaction_root=interactions[approve["control"]],
        control_root=approve["control"],
        event_root=approve["event"],
        expected_revision=store.revision,
        authentication_context=authority.session.context(),
    )
    assert store.revision == before + 1
    assert execution.revision == store.revision
    approved = project_universal_canvas(store, registry)["selected_assembly"]
    assert approved["operational"]["current_state_label"] == "APPROVED"
    evidence_root = approved["operational"]["history"][-1]["evidence"][0]
    evidence = read_evidence(
        store.snapshot(), registry.standard_library.state_machine_protocol,
        evidence_root,
    )
    assert evidence.issuer_root == registry.authorization.subject_root
    payload = json.loads(evidence.payload)
    assert payload["decision"] == "approve"
    assert payload["request"] == root
    assert len(payload["request_digest"]) == 64
    assert "provider" not in payload

    execute = next(
        item for item in approved["operational"]["admitted_transitions"]
        if item["event_label"] == "execute"
    )
    assert execute["user_decision"] is False
    with pytest.raises(InvalidCell, match="evidence"):
        transition_universal_operational_state(
            store,
            registry,
            root,
            execute["event"],
            approved["operational"]["current_state"],
        )


def test_properties_command_executes_only_current_admitted_transition():
    store, registry = build_universal_application(resolve_map_path())
    initial = project_universal_canvas(store, registry)
    root, _ = instantiate_universal_definition(
        store, registry, _definition(initial, "Monetary Intent"), x=420, y=180
    )
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    submit = next(
        item for item in assembly["operational"]["admitted_transitions"]
        if item["event_label"] == "submit"
    )
    transition_universal_operational_state(
        store,
        registry,
        root,
        submit["event"],
        assembly["operational"]["current_state"],
    )
    pending = project_universal_canvas(store, registry)["selected_assembly"]
    assert pending["operational"]["current_state_label"] == "PENDING"
    assert pending["operational"]["history"][-1]["actor"] == (
        registry.authorization.subject_root
    )
    with pytest.raises(InvalidCell, match="stale"):
        transition_universal_operational_state(
            store,
            registry,
            root,
            submit["event"],
            assembly["operational"]["current_state"],
        )
