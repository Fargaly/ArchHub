from __future__ import annotations

import inspect
from pathlib import Path
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.agent_session_catalogue import (
    create_agent_session,
    install_agent_session_catalogue,
    transition_agent_session,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_agent_coordination import (
    BoundAgentSession,
    GraphAgentCoordinator,
)
from nodelang.coordination_workshop import install_workshop_catalogue
from nodelang.unified_authority import (
    BootstrapManifest,
    create_unified_authority,
    open_unified_authority,
)
from nodelang.universal_cell import CellStore, InvalidCell


FOUNDER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
FOUNDER_PUBLIC = FOUNDER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
COMMANDS = uuid.UUID("72558bf4-4f1a-40ec-b789-44ce5fb27c35")


def _command(label: str) -> str:
    return str(uuid.uuid5(COMMANDS, label))


class _Caller:
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


def _foundation(database):
    provider = MemorySigningKeyProvider(
        "coordination-court", b"coordination-court-key" + b"0" * 11
    )
    authority = create_unified_authority(
        CellStore(database),
        provider,
        key_id="coordination-court",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Coordination court",
        bootstrap_session_public_key=FOUNDER_PUBLIC,
        composition_labels=(
            "Workshop", "Grand Map", "Governance", "Agent Sessions", "Projects"
        ),
    )
    founder = _Caller(
        authority,
        authority.manifest.bootstrap_session_root,
        FOUNDER_PRIVATE,
    )
    sessions = install_agent_session_catalogue(
        authority,
        operation_id=_command("session-catalogue"),
        caller=founder,
    )
    workshop = install_workshop_catalogue(
        authority,
        operation_id=_command("workshop-catalogue"),
        caller=founder,
    )
    return authority, provider, founder, sessions, workshop


def _session(authority, catalogue, founder, label, private_key, runtime):
    bundle = create_agent_session(
        authority,
        catalogue,
        label=label,
        runtime=runtime,
        provider="provider-neutral",
        model="provider-selected",
        public_key=private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        operation_id=_command("create-" + runtime),
        caller=founder,
    )
    caller = _Caller(authority, bundle.session_root, private_key)
    transition_agent_session(
        authority,
        bundle,
        "online",
        caller=caller,
        command_id=_command(runtime + "-online"),
    )
    return bundle, caller


def test_bound_agents_message_through_one_workshop_and_restart(tmp_path):
    database = tmp_path / "clean-coordination.sqlite3"
    authority, provider, founder, sessions, workshop = _foundation(database)
    sender_private = Ed25519PrivateKey.generate()
    recipient_private = Ed25519PrivateKey.generate()
    sender_bundle, sender_caller = _session(
        authority, sessions, founder, "Builder", sender_private, "codex"
    )
    recipient_bundle, recipient_caller = _session(
        authority, sessions, founder, "Reviewer", recipient_private, "reviewer"
    )
    sender = GraphAgentCoordinator(
        authority,
        sessions,
        workshop,
        BoundAgentSession(sender_bundle, sender_caller),
    )
    recipient = GraphAgentCoordinator(
        authority,
        sessions,
        workshop,
        BoundAgentSession(recipient_bundle, recipient_caller),
    )

    agents = sender.list_agents()
    assert {agent.bundle.session_root for agent in agents} == {
        sender_bundle.session_root,
        recipient_bundle.session_root,
    }
    operation = _command("send-first-message")
    message = sender.send_message(
        target_session_root=recipient_bundle.session_root,
        body="Review the exact accepted graph revision.",
        operation_id=operation,
    )
    assert message.sender_root == sender_bundle.session_root
    assert message.recipient_root == recipient_bundle.session_root
    assert message.state == "sent"
    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)
    replay = sender.send_message(
        target_session_root=recipient_bundle.session_root,
        body="Review the exact accepted graph revision.",
        operation_id=operation,
    )
    assert replay.root_id == message.root_id
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count

    inbox = recipient.inbox(after_revision=message.created_revision - 1)
    assert tuple(item.root_id for item in inbox) == (message.root_id,)
    with pytest.raises(InvalidCell, match="connected caller session"):
        sender.mark_message_read(message.root_id, command_id=_command("spoof-read"))
    recipient.mark_message_read(
        message.root_id,
        command_id=_command("recipient-read"),
    )
    assert recipient.inbox()[0].state == "read"

    manifest = authority.manifest.to_json()
    authority.store.close()
    reopened = open_unified_authority(
        CellStore(database),
        BootstrapManifest.from_json(manifest),
        provider,
    )
    reopened_recipient = GraphAgentCoordinator(
        reopened,
        sessions,
        workshop,
        BoundAgentSession(
            recipient_bundle,
            _Caller(reopened, recipient_bundle.session_root, recipient_private),
        ),
    )
    restored = reopened_recipient.inbox()
    assert len(restored) == 1
    assert restored[0].root_id == message.root_id
    assert restored[0].state == "read"
    reopened.store.close()


def test_coordination_adapter_has_no_caller_selected_sender_or_side_ledger():
    parameters = inspect.signature(GraphAgentCoordinator.send_message).parameters
    assert "sender" not in parameters
    assert "vendor" not in parameters
    assert "session_id" not in parameters
    source = (
        Path(__file__).parents[1] / "nodelang" / "clean_agent_coordination.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "external_session_id",
        "sqlite3",
        "jsonl",
        "sleep(",
        "coordination_send",
        "UniversalRuntimeSessionManager",
    ):
        assert forbidden not in source
