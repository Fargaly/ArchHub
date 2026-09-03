from __future__ import annotations

import json
from pathlib import Path
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.coordination_workshop import (
    connect_workshop_instance,
    create_workshop_instance,
    install_workshop_catalogue,
)
from nodelang.unified_application_lens import (
    project_unified_scope,
    project_workshop_lens,
    scope_lens_payload,
)
from nodelang.unified_authority import (
    BootstrapManifest,
    composition_root,
    create_unified_authority,
    open_unified_authority,
    read_relation,
    read_scope_level,
)
from nodelang.universal_cell import CellStore, InvalidCell


PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
COMMANDS = uuid.UUID("e6b33ab7-f2de-439f-a2c3-807842801dec")


def _command(label: str) -> str:
    return str(uuid.uuid5(COMMANDS, label))


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return PRIVATE.sign(payload)


def _authority(store=None, provider=None):
    return create_unified_authority(
        store or CellStore(),
        provider or MemorySigningKeyProvider(
            "workshop-lens-court", b"workshop-lens-key" + b"0" * 15
        ),
        key_id="workshop-lens-court",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Workshop lens court session",
        bootstrap_session_public_key=PUBLIC,
        composition_labels=("Workshop", "Agent Sessions", "Grand Map"),
    )


def test_workshop_lens_projects_real_nodes_ports_relations_and_properties():
    authority = _authority()
    caller = _Caller(authority)
    catalogue = install_workshop_catalogue(
        authority,
        operation_id="bc33d86f-9076-4829-887b-4e5c860a11a7",
        caller=caller,
    )
    plan = create_workshop_instance(
        authority,
        catalogue.plan_definition,
        {"title": "Coordinate the clean visual Workshop"},
        caller=caller,
        command_id=_command("plan"),
    )
    objective = composition_root(authority, "Grand Map", caller=caller)
    connected = connect_workshop_instance(
        authority,
        plan.root_id,
        "objective",
        objective,
        caller=caller,
        command_id=_command("objective"),
    )

    lens = project_workshop_lens(authority, caller=caller)
    assert lens.graph_id == authority.manifest.graph_id
    assert lens.revision == authority.store.revision
    assert lens.scope_root == composition_root(
        authority, "Workshop", caller=caller
    )
    assert [node.root_id for node in lens.nodes] == [plan.root_id]
    node = lens.nodes[0]
    assert node.structural_role == "instance"
    assert node.definition_root == catalogue.plan_definition
    assert node.definition_name == "Coordination plan"
    assert node.label == "Plan"
    assert node.state_parameter == "state"
    assert node.state == "draft"
    assert node.panels == ("Overview", "Roles", "Sources", "Courts", "History")
    properties = {item.name: item for item in node.properties}
    assert properties["title"].value == "Coordinate the clean visual Workshop"
    assert properties["title"].editor == "text"
    assert properties["state"].value == "draft"
    assert properties["state"].editor == "choice"

    assert [relation.root_id for relation in lens.relations] == [
        connected.root_id
    ]
    assert node.ports[0].relation_root == connected.root_id
    assert node.ports[0].connection == "objective"
    assert node.ports[0].participant_role == "source"
    assert node.ports[0].other_roots == (objective,)
    assert {item.name for item in lens.catalogue}.issuperset({
        "Coordination plan",
        "Work assignment",
        "Work evidence",
        "Independent review",
        "Coordination message",
    })

    payload = scope_lens_payload(lens)
    assert json.loads(json.dumps(payload))["nodes"][0]["root_id"] == plan.root_id
    authority.store.close()


def test_generic_scope_lens_projects_application_compositions_without_dispatch():
    authority = _authority()
    caller = _Caller(authority)
    lens = project_unified_scope(
        authority,
        authority.manifest.application_root,
        caller=caller,
    )
    assert {node.label for node in lens.nodes}.issuperset({
        "Workshop", "Agent Sessions", "Grand Map",
        "Protocol", "Policy", "Catalogue", "Constitution", "History",
    })
    assert all(node.structural_role == "composition" for node in lens.nodes)
    # Openable is DERIVED, not asserted: a card offers to open only when it
    # holds something the level below would draw. Asserting every node is
    # openable encoded the old bug -- every card offered to expand and every
    # expansion landed on an empty canvas. These bootstrap compositions are
    # created empty, so none of them opens onto anything, and a composition
    # that does hold a member must.
    snapshot = authority.store.snapshot()
    composition_role = authority.role("composition")
    for node in lens.nodes:
        holds = any(
            member.role_id == composition_role
            for member in read_relation(snapshot, node.root_id, budget=4096)
        )
        assert node.openable is holds, (node.label, node.openable, holds)
    assert any(not node.openable for node in lens.nodes)
    assert lens.relations == ()
    authority.store.close()


def test_lens_source_has_no_product_named_render_dispatch():
    source = (
        Path(__file__).parents[1]
        / "nodelang"
        / "unified_application_lens.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        'if label == "Workshop"',
        'if label == "Brain"',
        'if definition.name ==',
        '"kind":',
        "sqlite3",
        "jsonl",
    ):
        assert forbidden not in source


def test_scope_level_is_revision_exact_and_does_not_leak_newer_instances():
    authority = _authority()
    caller = _Caller(authority)
    catalogue = install_workshop_catalogue(
        authority,
        operation_id="cbe2fb19-b345-4e89-afeb-f1859bf5a74d",
        caller=caller,
    )
    workshop = composition_root(authority, "Workshop", caller=caller)
    first = create_workshop_instance(
        authority,
        catalogue.plan_definition,
        {"title": "First accepted snapshot"},
        caller=caller,
        command_id=_command("first-revision-plan"),
    )
    accepted_revision = authority.store.revision
    second = create_workshop_instance(
        authority,
        catalogue.plan_definition,
        {"title": "Newer plan"},
        caller=caller,
        command_id=_command("second-revision-plan"),
    )
    historical = read_scope_level(
        authority,
        workshop,
        scope_root=workshop,
        caller=caller,
        at_revision=accepted_revision,
    )
    current = read_scope_level(
        authority,
        workshop,
        scope_root=workshop,
        caller=caller,
    )
    assert historical.revision == accepted_revision
    assert set(historical.composition_roots) == {first.root_id}
    assert set(current.composition_roots) == {first.root_id, second.root_id}
    authority.store.close()


def test_scope_lens_rejects_a_key_not_bound_to_the_graph_session():
    authority = _authority()
    wrong_private = Ed25519PrivateKey.generate()

    class _WrongCaller:
        actor_root = authority.manifest.principal_root
        session_root = authority.manifest.bootstrap_session_root
        public_key = wrong_private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

        @staticmethod
        def sign(payload: bytes) -> bytes:
            return wrong_private.sign(payload)

    with pytest.raises(InvalidCell):
        project_workshop_lens(authority, caller=_WrongCaller())
    authority.store.close()


def test_workshop_lens_reopens_as_the_same_graph_revision_and_payload(tmp_path):
    database = tmp_path / "workshop-lens.sqlite3"
    provider = MemorySigningKeyProvider(
        "workshop-lens-court", b"workshop-lens-key" + b"0" * 15
    )
    authority = _authority(CellStore(database), provider)
    caller = _Caller(authority)
    catalogue = install_workshop_catalogue(
        authority,
        operation_id="8e95fa8b-d94f-41db-b8c9-f34661458bf0",
        caller=caller,
    )
    plan = create_workshop_instance(
        authority,
        catalogue.plan_definition,
        {"title": "Persist the exact Workshop lens"},
        caller=caller,
        command_id=_command("persisted-plan"),
    )
    connect_workshop_instance(
        authority,
        plan.root_id,
        "objective",
        composition_root(authority, "Grand Map", caller=caller),
        caller=caller,
        command_id=_command("persisted-objective"),
    )
    before = scope_lens_payload(project_workshop_lens(authority, caller=caller))
    manifest = authority.manifest.to_json()
    revision = authority.store.revision
    authority.store.close()

    reopened = open_unified_authority(
        CellStore(database),
        BootstrapManifest.from_json(manifest),
        provider,
    )
    try:
        after = scope_lens_payload(
            project_workshop_lens(reopened, caller=_Caller(reopened))
        )
        assert reopened.manifest.graph_id == before["graph_id"]
        assert reopened.store.revision == revision == before["revision"]
        assert after == before
    finally:
        reopened.store.close()
