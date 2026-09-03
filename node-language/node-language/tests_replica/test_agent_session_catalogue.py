from __future__ import annotations

import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.agent_session_catalogue import (
    create_agent_session,
    install_agent_session_catalogue,
    read_agent_session,
    transition_agent_session,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.unified_authority import (
    BootstrapManifest,
    create_unified_authority,
    open_unified_authority,
    revoke_session,
)
from nodelang.universal_cell import CellStore, InvalidCell


FOUNDER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
FOUNDER_PUBLIC = FOUNDER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
COMMANDS = uuid.UUID("94fe7015-32ba-41c4-9000-d644f57a980d")


def _command(label: str) -> str:
    return str(uuid.uuid5(COMMANDS, label))


class _Caller:
    def __init__(self, authority, session_root=None, private_key=None):
        self.actor_root = authority.manifest.principal_root
        self.session_root = session_root or authority.manifest.bootstrap_session_root
        self._private_key = private_key or FOUNDER_PRIVATE
        self.public_key = self._private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


def _authority(store=None, provider=None):
    return create_unified_authority(
        store or CellStore(),
        provider or MemorySigningKeyProvider("session-court", b"s" * 32),
        key_id="session-court",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Session catalogue court",
        bootstrap_session_public_key=FOUNDER_PUBLIC,
        composition_labels=("Agent Sessions", "Workshop", "Projects"),
    )


def test_agent_session_is_openable_catalogue_state_inside_one_credentialed_node(
    tmp_path,
):
    database = tmp_path / "agent-sessions.sqlite3"
    provider = MemorySigningKeyProvider("session-court", b"s" * 32)
    authority = _authority(CellStore(database), provider)
    founder = _Caller(authority)
    catalogue = install_agent_session_catalogue(
        authority,
        operation_id="d4c69920-695a-40f9-85a6-1fa75876c116",
        caller=founder,
    )
    private_key = Ed25519PrivateKey.generate()
    bundle = create_agent_session(
        authority,
        catalogue,
        label="Codex clean session",
        runtime="codex",
        provider="openai",
        model="provider-selected",
        public_key=private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        operation_id="4cc492c1-9dfc-4eb4-8edb-c6c41dc0dcdd",
        caller=founder,
    )
    agent = _Caller(authority, bundle.session_root, private_key)
    before = authority.store.revision
    with pytest.raises(InvalidCell, match="connected caller session"):
        transition_agent_session(
            authority,
            bundle,
            "online",
            caller=founder,
            command_id=_command("founder-cannot-impersonate-session"),
        )
    assert authority.store.revision == before

    transition_agent_session(
        authority,
        bundle,
        "online",
        caller=agent,
        command_id=_command("session-online"),
    )
    transition_agent_session(
        authority,
        bundle,
        "busy",
        caller=agent,
        command_id=_command("session-busy"),
    )
    projected = read_agent_session(authority, bundle, caller=agent)
    assert projected["state"]["values"] == {
        "model": "provider-selected",
        "provider": "openai",
        "runtime": "codex",
        "status": "busy",
    }
    assert projected["session_root"] == bundle.session_root
    assert projected["state_root"] == bundle.state_root

    manifest = authority.manifest.to_json()
    revision = authority.store.revision
    authority.store.close()
    reopened_store = CellStore(database)
    reopened = open_unified_authority(
        reopened_store,
        BootstrapManifest.from_json(manifest),
        provider,
    )
    reopened_agent = _Caller(reopened, bundle.session_root, private_key)
    restored = read_agent_session(reopened, bundle, caller=reopened_agent)
    assert restored["state"]["values"]["status"] == "busy"
    assert reopened_store.revision == revision

    revoke_session(
        reopened,
        bundle.session_root,
        caller=_Caller(reopened),
        command_id=_command("revoke-agent-session"),
    )
    with pytest.raises(InvalidCell, match="revoked|binding"):
        transition_agent_session(
            reopened,
            bundle,
            "offline",
            caller=reopened_agent,
            command_id=_command("revoked-session-offline"),
        )
    reopened_store.close()
