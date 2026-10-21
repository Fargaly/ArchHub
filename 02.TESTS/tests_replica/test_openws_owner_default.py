"""F62: account-owner default through real isolated Codex machine write admission."""
from __future__ import annotations

import dataclasses
import hashlib
import uuid

import pytest

from nodelang import application_server as app
from nodelang import workspace_roots_catalogue as roots
from nodelang import workspace_roots_signing as signing
from nodelang.application_machine_transport import UniversalRuntimeClient, MachineTransportError
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import LocalEd25519KmsProvider
from nodelang.universal_application import AuthorizationDenied, authorize_universal_cde_write
from tests_replica.test_application_machine_transport import _green_runtime_compliance
from tests_replica.test_workspace_root_write_admission import _Store, _entry, _registry, graph_state
from tests_replica.test_workspace_roots_catalogue import _Key
from tests_replica import test_privgrant_settings as grant_courts
from tests_replica.test_workspace_root_machine_permit import _settings_request


settings = grant_courts.settings


PATH = "workspace-roots/01-personal/BBC4/august-7.txt"
CONTENT = b"BBC4 owner-agent work continues"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("openws", numbered=True)
    patch = pytest.MonkeyPatch()
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP", "TMP"):
        folder = tmp / name
        folder.mkdir()
        patch.setenv(name, str(folder))
    patch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp / "state"))
    private = tmp / "01-personal"
    private.mkdir()
    public = tmp / "public-product"
    public.mkdir()
    key = _Key()
    entries = [{**_entry(private, root_id="01-personal", writers=("codex",)), "privacy": "private"},
               {**_entry(public, root_id="public-product", writers=("codex",)), "privacy": "public"}]
    files = _registry(tmp, key, entries)
    for name in ("snapshot_path", "pin_path", "last_good_path"):
        patch.setattr(roots, "default_" + name, lambda name=name: files[name])
    # Each isolated owner keeps its own authoritative graph statement. Settings' separate
    # owner fixture also publishes a registry and must not change this owner's statement.
    owner_digest = graph_state()["registry_digest"]
    patch.setattr(roots, "verified_graph_state", lambda: {"registry_digest": owner_digest})
    patch.setattr(signing, "CngVerifier", lambda name: _Store(key))
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"w" * 32)
    provider.add_key("archhub.local.private-root-grants", b"g" * 32)
    descriptor = tmp / "runtime.json"
    grant_path = tmp / "private-root-grants.json"
    server = app.ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
        universal_workspace_root=tmp, machine_key_provider=provider,
        private_root_grants_path=grant_path, runtime_compliance_runner=_green_runtime_compliance).start()
    agent = UniversalRuntimeClient(descriptor, provider)
    try:
        kms = LocalEd25519KmsProvider(provider_id="court.openws", authority_id="court-openws")
        server.cde_write_signing_descriptor_root = app._ensure_cde_write_signing_authority(
            server.universal_store, server.universal_registry, kms,
            descriptor_root="court:openws:cde-key")
        server.cde_write_signing_provider = kms
        agent.bind_agent_session(runtime="codex", external_session_id="openws-owner-codex")
        yield server, agent, grant_path, private
    finally:
        server.close()
        patch.undo()


def issue(agent, path=PATH, **options):
    return agent.issue_cde_write_permit(operation="write_file", path=path,
        content_digest=hashlib.sha256(CONTENT).hexdigest(), request_id="openws-" + uuid.uuid4().hex,
        nonce=uuid.uuid4().hex, **options)


def test_owner_codex_no_grant_no_prompt_real_admission_and_write(world, monkeypatch):
    server, agent, grant_path, private = world
    assert not grant_path.exists()
    def forbidden(*args, **kwargs):
        raise AssertionError("owner path opened a grant, prompt or picker")
    monkeypatch.setattr(server.private_root_grants, "status", forbidden)
    monkeypatch.setattr(signing, "CngSigner", forbidden)
    status = agent.private_root_grant_status(path=PATH, operation="write_file")
    assert status["granted"] is True and status["owner_default"] is True
    issued = issue(agent)
    assert issued["container_id"] == "GM.nodes.owner-workspace-default"
    assert issued["agent_session"] == agent.agent_session_root
    consumed = agent.consume_cde_write_permit(permit=issued["permit"], operation="write_file", path=PATH,
        content_digest=hashlib.sha256(CONTENT).hexdigest(), request_id=issued["request_id"])
    assert consumed["kind"] == "consumed"
    target = private / "BBC4" / "august-7.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(CONTENT)
    assert target.read_bytes() == CONTENT
    assert not grant_path.exists(), "owner default must not create a grant record"
    target.unlink()


def test_other_account_without_grant_is_refused(world):
    server, agent, grant_path, _private = world
    registry = dataclasses.replace(server.universal_registry, authorization=dataclasses.replace(
        server.universal_registry.authorization, subject_root="another-account"))
    with pytest.raises(AuthorizationDenied, match="grant|claimed governed Work"):
        authorize_universal_cde_write(server.universal_store, registry,
            agent_session_root=agent.agent_session_root, runtime="codex", operation="write_file", path=PATH,
            private_root_grants=server.private_root_grants)
    assert not grant_path.exists()


def test_private_content_toward_public_target_is_refused(world):
    _server, agent, _grant_path, _private = world
    with pytest.raises(MachineTransportError, match="[Pp]rivate.*public"):
        issue(agent, "workspace-roots/public-product/BBC4/august-7.txt")


def test_owner_overwrite_without_verified_copy_is_refused(world):
    _server, agent, _grant_path, private = world
    target = private / "BBC4" / "august-7.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(b"founder original")
    try:
        with pytest.raises(MachineTransportError, match="verified copy"):
            issue(agent)
        assert target.read_bytes() == b"founder original"
    finally:
        target.unlink()


def test_preference_is_reversible_persisted_and_preserved_by_grants(world):
    server, agent, grant_path, _private = world
    store = server.private_root_grants
    try:
        store.set_own_agents_write_without_asking(False)
        assert store.own_agents_write_without_asking() is False
        with pytest.raises(MachineTransportError, match="claimed governed Work"):
            issue(agent)
        from nodelang.private_root_grants import PrivateRootGrantStore
        reopened = PrivateRootGrantStore(grant_path, provider=store.provider)
        assert reopened.own_agents_write_without_asking() is False
        store.grant(root_id="01-personal", runtime="codex", session_id="other-session",
                    root_digest="a" * 64, operations=["write_file"])
        store.revoke(root_id="01-personal", session_id="other-session")
        assert reopened.own_agents_write_without_asking() is False
        store.set_own_agents_write_without_asking(True)
        assert reopened.own_agents_write_without_asking() is True
        assert issue(agent)["container_id"] == "GM.nodes.owner-workspace-default"
    finally:
        grant_path.unlink(missing_ok=True)


def test_verified_copy_allows_owner_edit_and_stays_bound_at_receipt(world):
    _server, agent, _grant_path, private = world
    target = private / "BBC4" / "august-7.txt"
    backup = private / "BBC4" / "august-7-copy.txt"
    target.parent.mkdir(exist_ok=True)
    original = b"founder original safe in verified copy"
    target.write_bytes(original)
    backup.write_bytes(original)
    proof = {"copy_path": "workspace-roots/01-personal/BBC4/august-7-copy.txt"}
    try:
        issued = issue(agent, write_evidence=proof)
        target.write_bytes(CONTENT)
        consumed = agent.consume_cde_write_permit(permit=issued["permit"], operation="write_file", path=PATH,
            content_digest=hashlib.sha256(CONTENT).hexdigest(), request_id=issued["request_id"],
            write_evidence=proof)
        assert consumed["kind"] == "consumed"
        assert backup.read_bytes() == original and target.read_bytes() == CONTENT
    finally:
        target.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)


def test_only_verified_public_source_content_reaches_public_target(world):
    server, agent, _grant_path, private = world
    public = private.parent / "public-product"
    source = public / "public-source.txt"
    secret = private / "private-source.txt"
    source.write_bytes(CONTENT)
    secret.write_bytes(CONTENT)
    destination = "workspace-roots/public-product/published.txt"
    try:
        with pytest.raises(MachineTransportError, match="[Pp]rivate.*public"):
            issue(agent, destination, write_evidence={"source_path":"workspace-roots/01-personal/private-source.txt"})
        issued = issue(agent, destination,
                       write_evidence={"source_path":"workspace-roots/public-product/public-source.txt"})
        assert issued["container_id"] == "GM.nodes.owner-workspace-default"
        assert not server.private_root_grants.path.exists()
    finally:
        source.unlink()
        secret.unlink()


def test_copy_proof_cannot_leak_private_data_or_escape_its_registered_folder(world):
    _server, agent, _grant_path, private = world
    public = private.parent / "public-product"
    target = private / "BBC4" / "august-7.txt"
    copy = public / "leaked-copy.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(b"private original")
    copy.write_bytes(b"private original")
    try:
        with pytest.raises(MachineTransportError, match="separate private file"):
            issue(agent, write_evidence={"copy_path":"workspace-roots/public-product/leaked-copy.txt"})
        with pytest.raises(MachineTransportError, match="invalid"):
            issue(agent, write_evidence={"copy_path":"workspace-roots/01-personal/../outside.txt"})
    finally:
        target.unlink()
        copy.unlink()




def test_settings_toggle_changes_same_store_without_creating_grants(settings):
    first = _settings_request(settings["host"], settings["keys"], {"action":"list"})
    assert first["own_agents_write_without_asking"] is True
    assert not settings["path"].exists()
    off = _settings_request(settings["host"], settings["keys"], {"action":"set-own-agents-write","enabled":False})
    assert off["own_agents_write_without_asking"] is False and off["private_grants"] == []
    on = _settings_request(settings["host"], settings["keys"], {"action":"set-own-agents-write","enabled":True})
    assert on["own_agents_write_without_asking"] is True and on["private_grants"] == []


def test_owner_delete_without_verified_copy_is_refused(world):
    _server, agent, _grant_path, _private = world
    with pytest.raises(MachineTransportError, match="verified copy"):
        agent.issue_cde_write_permit(operation="delete", path=PATH,
            content_digest=hashlib.sha256(CONTENT).hexdigest(),
            request_id="openws-delete-" + uuid.uuid4().hex, nonce=uuid.uuid4().hex)


def test_changed_backup_cannot_reuse_an_issued_owner_permit(world):
    _server, agent, _grant_path, private = world
    target = private / "BBC4" / "august-7.txt"
    backup = private / "BBC4" / "august-7-copy.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(b"original")
    backup.write_bytes(b"original")
    proof = {"copy_path":"workspace-roots/01-personal/BBC4/august-7-copy.txt"}
    try:
        issued = issue(agent, write_evidence=proof)
        backup.write_bytes(b"replaced copy")
        with pytest.raises(MachineTransportError, match="container|digest|authority"):
            agent.consume_cde_write_permit(permit=issued["permit"], operation="write_file", path=PATH,
                content_digest=hashlib.sha256(CONTENT).hexdigest(), request_id=issued["request_id"],
                write_evidence=proof)
        assert target.read_bytes() == b"original"
    finally:
        target.unlink()
        backup.unlink()


def test_unavailable_grant_key_does_not_lock_out_owner(world, monkeypatch):
    from nodelang.cell_secret_keys import SigningKeyError
    server, agent, grant_path, _private = world
    store = server.private_root_grants
    store.set_own_agents_write_without_asking(False)
    fingerprint = store.provider.key_fingerprint
    def unavailable(key_id, version):
        if key_id == store.key_id:
            raise SigningKeyError("grant key is unavailable")
        return fingerprint(key_id, version)
    monkeypatch.setattr(store.provider, "key_fingerprint", unavailable)
    try:
        assert store.own_agents_write_without_asking() is True
        assert issue(agent)["container_id"] == "GM.nodes.owner-workspace-default"
    finally:
        grant_path.unlink(missing_ok=True)


def test_owner_directory_creation_is_routine_not_deletion(world):
    _server, agent, _grant_path, private = world
    path = "workspace-roots/01-personal/new-folder"
    digest = hashlib.sha256(b"").hexdigest()
    issued = agent.issue_cde_write_permit(operation="mkdir", path=path, content_digest=digest,
        request_id="openws-mkdir-" + uuid.uuid4().hex, nonce=uuid.uuid4().hex)
    target = private / "new-folder"
    target.mkdir()
    try:
        assert agent.consume_cde_write_permit(permit=issued["permit"], operation="mkdir", path=path,
            content_digest=digest, request_id=issued["request_id"])["kind"] == "consumed"
    finally:
        target.rmdir()
