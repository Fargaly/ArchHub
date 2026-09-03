from __future__ import annotations

from pathlib import Path
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.agent_session_catalogue import (
    create_agent_session,
    install_agent_session_catalogue,
    transition_agent_session,
)
from nodelang.coordination_workshop import (
    connect_workshop_instance,
    create_workshop_instance,
    install_workshop_catalogue,
    read_workshop_instance,
    transition_workshop_instance,
)
from nodelang.unified_authority import (
    BootstrapManifest,
    composition_root,
    create_unified_authority,
    open_unified_authority,
    read_definition,
)
from nodelang.universal_cell import CellStore, InvalidCell


PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
COMMANDS = uuid.UUID("d6a034f3-bf6b-4caf-a684-d4f86bb190ab")


def _command(label: str) -> str:
    return str(uuid.uuid5(COMMANDS, label))


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return PRIVATE.sign(payload)


class _KeyedCaller:
    def __init__(self, authority, session_root, private_key):
        self.actor_root = authority.manifest.principal_root
        self.session_root = session_root
        self.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self._private_key = private_key

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


def _authority(store: CellStore | None = None, provider=None):
    return create_unified_authority(
        store or CellStore(),
        provider or MemorySigningKeyProvider(
            "workshop-court", b"workshop-court-key" + b"0" * 14
        ),
        key_id="workshop-court",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Workshop court session",
        bootstrap_session_public_key=PUBLIC,
        composition_labels=(
            "Workshop", "Grand Map", "Governance", "Agent Sessions", "Projects"
        ),
    )


def _connect(authority, root: str, name: str, target: str) -> None:
    connect_workshop_instance(
        authority,
        root,
        name,
        target,
        caller=_Caller(authority),
        command_id=_command(root + ":" + name),
    )


def test_workshop_is_one_graph_native_plan_assignment_review_and_report(tmp_path):
    database = tmp_path / "workshop.sqlite3"
    provider = MemorySigningKeyProvider(
        "workshop-court", b"workshop-court-key" + b"0" * 14
    )
    store = CellStore(database)
    authority = _authority(store, provider)
    caller = _Caller(authority)
    workshop = composition_root(authority, "Workshop", caller=caller)
    grand_map = composition_root(authority, "Grand Map", caller=caller)
    governance = composition_root(authority, "Governance", caller=caller)
    session_catalogue = install_agent_session_catalogue(
        authority,
        operation_id="253b74c9-7541-47b9-b2e4-df6f22fdaf15",
        caller=caller,
    )
    builder_private = Ed25519PrivateKey.generate()
    reviewer_private = Ed25519PrivateKey.generate()
    builder = create_agent_session(
        authority,
        session_catalogue,
        label="Builder session",
        runtime="codex",
        provider="openai",
        model="provider-selected",
        public_key=builder_private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        operation_id="5202150c-0238-493e-aa90-dd79e8c151af",
        caller=caller,
    )
    reviewer = create_agent_session(
        authority,
        session_catalogue,
        label="Independent reviewer session",
        runtime="independent-review",
        provider="provider-neutral",
        model="provider-selected",
        public_key=reviewer_private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        operation_id="aa31e7e9-018f-4bbf-b38d-757107434fe6",
        caller=caller,
    )
    builder_caller = _KeyedCaller(
        authority, builder.session_root, builder_private
    )
    reviewer_caller = _KeyedCaller(
        authority, reviewer.session_root, reviewer_private
    )
    transition_agent_session(
        authority,
        builder,
        "online",
        caller=builder_caller,
        command_id=_command("builder-online"),
    )
    transition_agent_session(
        authority,
        reviewer,
        "online",
        caller=reviewer_caller,
        command_id=_command("reviewer-online"),
    )
    catalogue = install_workshop_catalogue(
        authority,
        operation_id="94d74a73-96d5-47d6-bf9a-1ab91a4e1181",
        caller=caller,
    )
    for root in (
        catalogue.plan_definition,
        catalogue.assignment_definition,
        catalogue.evidence_definition,
        catalogue.review_definition,
    ):
        assert read_definition(authority, root, caller=caller).lifecycle == "published"

    plan = create_workshop_instance(
        authority,
        catalogue.plan_definition,
        {"title": "Build the graph-native Workshop"},
        caller=caller,
        command_id=_command("create-plan"),
    )
    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)
    with pytest.raises(InvalidCell, match="missing a required connection"):
        transition_workshop_instance(
            authority,
            plan.root_id,
            "state",
            "accepted",
            caller=caller,
            command_id=_command("accept-plan-too-early"),
        )
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count

    plan_targets = {
        "objective": grand_map,
        "authority": authority.manifest.constitution_root,
        "research": governance,
        "architect": authority.manifest.principal_root,
        "critique": authority.manifest.policy_root,
        "builder": builder.session_root,
        "verifier": reviewer.session_root,
        "steward": authority.manifest.constitution_root,
        "red-court": authority.manifest.policy_root,
        "task-graph": grand_map,
    }
    for name, target in plan_targets.items():
        _connect(authority, plan.root_id, name, target)
    transition_workshop_instance(
        authority,
        plan.root_id,
        "state",
        "accepted",
        caller=caller,
        command_id=_command("accept-plan"),
    )

    assignment = create_workshop_instance(
        authority,
        catalogue.assignment_definition,
        {"title": "Implement the bounded Workshop path"},
        caller=caller,
        command_id=_command("create-assignment"),
    )
    assignment_targets = {
        "obligation": grand_map,
        "assignee": builder.session_root,
        "scope": workshop,
        "plan": plan.root_id,
        "court": authority.manifest.policy_root,
    }
    for name, target in assignment_targets.items():
        _connect(authority, assignment.root_id, name, target)
    transition_workshop_instance(
        authority,
        assignment.root_id,
        "state",
        "assigned",
        caller=caller,
        command_id=_command("assign-work"),
    )
    transition_workshop_instance(
        authority,
        assignment.root_id,
        "state",
        "working",
        caller=builder_caller,
        command_id=_command("start-work"),
    )

    evidence = create_workshop_instance(
        authority,
        catalogue.evidence_definition,
        {"summary": "Focused and restart courts passed"},
        scope_root=assignment.root_id,
        caller=caller,
        command_id=_command("create-evidence"),
    )
    for name, target in {
        "subject": assignment.root_id,
        "producer": builder.session_root,
        "artifact": authority.manifest.history_root,
    }.items():
        _connect(authority, evidence.root_id, name, target)
    transition_workshop_instance(
        authority,
        evidence.root_id,
        "status",
        "pass",
        caller=builder_caller,
        command_id=_command("pass-evidence"),
    )
    _connect(authority, assignment.root_id, "report", evidence.root_id)
    transition_workshop_instance(
        authority,
        assignment.root_id,
        "state",
        "review",
        caller=builder_caller,
        command_id=_command("submit-review"),
    )

    review = create_workshop_instance(
        authority,
        catalogue.review_definition,
        {"summary": "Independent graph evidence accepted"},
        scope_root=assignment.root_id,
        caller=caller,
        command_id=_command("create-review"),
    )
    for name, target in {
        "assignment": assignment.root_id,
        "reviewer": reviewer.session_root,
        "evidence": evidence.root_id,
    }.items():
        _connect(authority, review.root_id, name, target)
    transition_workshop_instance(
        authority,
        review.root_id,
        "decision",
        "pass",
        caller=reviewer_caller,
        command_id=_command("pass-review"),
    )
    for name, target in {
        "reviewer": reviewer.session_root,
        "review": review.root_id,
        "evidence": evidence.root_id,
    }.items():
        _connect(authority, assignment.root_id, name, target)
    accepted = transition_workshop_instance(
        authority,
        assignment.root_id,
        "state",
        "accepted",
        caller=reviewer_caller,
        command_id=_command("accept-assignment"),
    )
    projection = read_workshop_instance(
        authority, assignment.root_id, caller=caller
    )
    connection_names = {
        relation.properties["connection"]
        for relation in projection["relations"].values()
    }
    assert accepted.root_id == assignment.root_id
    assert projection["instance"]["values"]["state"] == "accepted"
    assert {
        "obligation", "assignee", "scope", "plan", "court", "report",
        "reviewer", "review", "evidence",
    }.issubset(connection_names)

    manifest_text = authority.manifest.to_json()
    revision = authority.store.revision
    store.close()
    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest_text),
        provider,
    )
    restored = read_workshop_instance(
        reopened, assignment.root_id, caller=_Caller(reopened)
    )
    replay = transition_workshop_instance(
        reopened,
        assignment.root_id,
        "state",
        "accepted",
        caller=_KeyedCaller(
            reopened, reviewer.session_root, reviewer_private
        ),
        command_id=_command("accept-assignment"),
    )
    assert restored["instance"]["values"]["state"] == "accepted"
    assert restored["instance"]["root"] == assignment.root_id
    assert replay.replayed is True
    assert reopened_store.revision == revision
    retention = reopened_store.retention_stats()
    assert retention["current_cell_count"] <= 37_720
    assert retention["version_cell_count"] <= 37_920
    assert retention["revision_count"] <= 66
    reopened_store.close()


def test_workshop_rejects_builder_as_its_own_verifier():
    authority = _authority()
    caller = _Caller(authority)
    catalogue = install_workshop_catalogue(
        authority,
        operation_id="bb2a20ff-6fd4-4a18-ac69-ef93b9bd1405",
        caller=caller,
    )
    plan = create_workshop_instance(
        authority,
        catalogue.plan_definition,
        {"title": "Invalid self-review plan"},
        caller=caller,
        command_id=_command("create-self-review-plan"),
    )
    same_session = authority.manifest.bootstrap_session_root
    targets = {
        "objective": authority.manifest.application_root,
        "authority": authority.manifest.constitution_root,
        "research": authority.manifest.policy_root,
        "architect": same_session,
        "critique": same_session,
        "builder": same_session,
        "verifier": same_session,
        "steward": same_session,
        "red-court": authority.manifest.policy_root,
        "task-graph": authority.manifest.application_root,
    }
    for name, target in targets.items():
        _connect(authority, plan.root_id, name, target)
    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)
    with pytest.raises(InvalidCell, match="independent participants"):
        transition_workshop_instance(
            authority,
            plan.root_id,
            "state",
            "accepted",
            caller=caller,
            command_id=_command("accept-self-review-plan"),
        )
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count
