"""Private-root consent through the existing signed Settings admission.

All registry, grant and runtime files belong to the isolated temporary profile.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from nodelang import application_machine_transport as transport
from nodelang import workspace_roots_catalogue as roots
from nodelang import workspace_roots_signing as signing
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.private_root_grants import DEFAULT_OPERATIONS, PrivateRootGrantStore
from nodelang.cell_protocols import compose_relation_cells
from nodelang.universal_cell import Cell, InvalidCell, NULL_CELL_ID, Snapshot
from tests_replica.test_workspace_root_machine_permit import (
    _clean_settings_owner,
    _settings_request,
)
from tests_replica.test_workspace_root_write_admission import (
    _Store,
    _entry,
    _no_live_graph,
    _registry,
    graph_digest,
    graph_state,
)
from tests_replica.test_workspace_roots_catalogue import _Key


SESSION = "app:agent-session:runtime:picked-private-root-court"
OTHER_SESSION = "app:agent-session:runtime:other-private-root-court"
PATH = "workspace-roots/client-a/drawings/august-7.dwg"


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "isolated-localappdata"))
    folder = tmp_path / "client-a"
    folder.mkdir()
    public = tmp_path / "public-product"
    public.mkdir()
    key = _Key()
    entries = [_entry(folder, writers=("codex",)),
               {**_entry(public, root_id="public-product", writers=("codex",)),
                "privacy": "public"}]
    files = _registry(tmp_path, key, entries)
    monkeypatch.setattr(roots, "default_snapshot_path", lambda: files["snapshot_path"])
    monkeypatch.setattr(roots, "default_pin_path", lambda: files["pin_path"])
    monkeypatch.setattr(roots, "default_last_good_path", lambda: files["last_good_path"])
    monkeypatch.setattr(signing, "CngVerifier", lambda name: _Store(key))
    monkeypatch.setattr(roots, "verified_graph_state", graph_state)
    monkeypatch.setattr(roots, "graph_context", _no_live_graph, raising=False)
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"p" * 32)
    provider.add_key("archhub.local.private-root-grants", b"q" * 32)
    provider.add_key("archhub.unified.bootstrap", b"r" * 32)
    grant_path = tmp_path / "private-root-grants.json"
    server, host, keys = _clean_settings_owner(tmp_path, provider, grant_path)
    _container, digest, _registration = roots.root_bound_registration(PATH, runtime="codex")
    try:
        yield {"server": server, "host": host, "keys": keys,
               "path": grant_path, "digest": digest, "provider": provider,
               "registry_files": files, "registry_blob": key.public_blob()}
    finally:
        server.close()


def _request(settings, body):
    return _settings_request(settings["host"], settings["keys"], body)


def _grant():
    # This is precisely the UI contract: defaults are chosen by the store.
    return {"action": "grant-private-root", "id": "client-a",
            "runtime": "codex", "session_id": SESSION}


def _status(settings, session=SESSION, *, operation="write_file"):
    return settings["server"].private_root_grants.status(
        root_id="client-a", runtime="codex", session_id=session,
        operation=operation, root_digest=settings["digest"])


def test_settings_grants_only_picked_session_lists_real_defaults_and_revokes(settings):
    before = time.time()
    _request(settings, _grant())
    after = time.time()
    assert _status(settings)["granted"] is True
    assert _status(settings, OTHER_SESSION)["granted"] is False
    assert _status(settings, operation="delete")["granted"] is False
    for operation in DEFAULT_OPERATIONS:
        assert _status(settings, operation=operation)["granted"] is True
    listed = _request(settings, {"action": "list"})
    assert listed["private_grant_defaults"] == {
        "operations": list(DEFAULT_OPERATIONS), "expires_after_seconds": 2592000}
    assert len(listed["private_grants"]) == 1
    grant = listed["private_grants"][0]
    assert (grant["root_id"], grant["runtime"], grant["session_id"]) == (
        "client-a", "codex", SESSION)
    assert grant["operations"] == list(DEFAULT_OPERATIONS)
    assert before + 2592000 <= grant["expires_at"] <= after + 2592000
    event = listed["last_private_grant_event"]
    assert (event["action"], event["root_id"], event["runtime"], event["session_id"]) == (
        "grant-private-root", "client-a", "codex", SESSION)
    assert event["expires_at"] == grant["expires_at"]
    assert before <= event["issued_at"] <= after
    revoked = _request(settings, {**_grant(), "action": "revoke-private-root"})
    assert revoked["private_grants"] == []
    assert _status(settings)["granted"] is False
    assert revoked["last_private_grant_event"]["action"] == "revoke-private-root"
    assert _request(settings, {"action": "list"})["private_grants"] == []


def test_settings_refuses_public_root(settings):
    with pytest.raises(roots.WorkspaceRootRefused, match="only a private workspace root"):
        _request(settings, {**_grant(), "id": "public-product"})
    assert not settings["path"].exists()
    assert _status(settings)["granted"] is False


def test_settings_recovers_absent_key_document_and_lists_actual_set_aside_event(settings):
    absent = MemorySigningKeyProvider("archhub.unified.bootstrap", b"x" * 32, version=2)
    PrivateRootGrantStore(settings["path"], provider=absent,
                          key_id="archhub.unified.bootstrap").grant(
        root_id="client-a", runtime="codex", session_id=OTHER_SESSION,
        root_digest=settings["digest"], operations=("write_file",))
    original = settings["path"].read_bytes()
    before = _request(settings, {"action": "list"})
    assert before["private_grants"] == []
    assert settings["path"].read_bytes() == original
    assert _status(settings, OTHER_SESSION)["granted"] is False
    answer = _request(settings, _grant())
    archived = list(settings["path"].parent.glob("private-root-grants.unverifiable-*.json"))
    assert len(archived) == 1
    assert archived[0].read_bytes() == original
    assert _status(settings)["granted"] is True
    assert _status(settings, OTHER_SESSION)["granted"] is False
    assert [row["session_id"] for row in answer["private_grants"]] == [SESSION]
    event = answer["last_private_grant_event"]
    assert "unverifiable document set aside as %s" % archived[0].name in event["message"]
    assert _request(settings, {"action": "list"})["last_private_grant_event"] == event
    receipt = {
        "old_sha256": hashlib.sha256(original).hexdigest(),
        "archived_sha256": hashlib.sha256(archived[0].read_bytes()).hexdigest(),
        "archived_filename": archived[0].name,
        "grant_for_picked": _status(settings)["granted"],
        "grant_for_old": _status(settings, OTHER_SESSION)["granted"],
    }
    (settings["path"].parent / "privgrant-recovery-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def test_settings_list_is_readable_for_empty_and_invalid_grant_documents(settings):
    empty = _request(settings, {"action": "list"})
    assert empty["private_grants"] == []
    assert empty["last_private_grant_event"] is None
    assert not settings["path"].exists()
    invalid = b"not a signed grant document\n"
    settings["path"].write_bytes(invalid)
    answer = _request(settings, {"action": "list"})
    assert answer["private_grants"] == []
    assert settings["path"].read_bytes() == invalid
    assert answer["last_private_grant_event"] is None


def test_settings_list_excludes_expired_grants(settings):
    settings["server"].private_root_grants.grant(
        root_id="client-a", runtime="codex", session_id=SESSION,
        root_digest=settings["digest"], now=time.time() - 120,
        expires_at=time.time() - 60)
    assert _request(settings, {"action": "list"})["private_grants"] == []
    assert _status(settings)["granted"] is False


class _PublicRegistryKey:
    """Verify the parent's synthetic registry without transferring a private key."""

    def __init__(self, blob):
        self.blob = blob
        self.key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(blob[8:40], "big"), int.from_bytes(blob[40:72], "big"),
            ec.SECP256R1()).public_key()

    def public_blob(self):
        return self.blob

    def verify(self, key_id, version, payload, signature):
        raw = bytes.fromhex(signature)
        if key_id != roots.KEY_ID or version != 1 or len(raw) != 64:
            return False
        try:
            self.key.verify(encode_dss_signature(
                int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                payload, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False


def _separate_machine_owner(control, workspace, descriptor, grant_path, files, blob):
    """Child owner has its own volatile session registry and no Settings host."""
    from nodelang.application_server import ApplicationServer
    from tests_replica.test_application_machine_transport import _green_runtime_compliance

    patches = pytest.MonkeyPatch()
    patches.setenv("LOCALAPPDATA", str(Path(workspace) / "isolated-localappdata"))
    patches.setattr(roots, "default_snapshot_path", lambda: Path(files["snapshot_path"]))
    patches.setattr(roots, "default_pin_path", lambda: Path(files["pin_path"]))
    patches.setattr(roots, "default_last_good_path", lambda: Path(files["last_good_path"]))
    public = _PublicRegistryKey(blob)
    patches.setattr(signing, "CngVerifier", lambda name: _Store(public))
    document = json.loads(Path(files["snapshot_path"]).read_text(encoding="utf-8"))
    body = {key: value for key, value in document.items() if key != "signature"}
    patches.setattr(roots, "verified_graph_state", lambda: {"registry_digest": graph_digest(body)})
    patches.setattr(roots, "graph_context", _no_live_graph, raising=False)
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"p" * 32)
    provider.add_key("archhub.local.private-root-grants", b"q" * 32)
    provider.add_key("archhub.unified.bootstrap", b"r" * 32)
    server = None
    try:
        server = ApplicationServer(
            enable_machine_transport=True, machine_descriptor_path=descriptor,
            universal_workspace_root=workspace, private_root_grants_path=grant_path,
            machine_key_provider=provider,
            runtime_compliance_runner=_green_runtime_compliance).start()
        # Preserve the exact-session grant courts with the owner default explicitly off.
        server.private_root_grants.set_own_agents_write_without_asking(False)
        control.send({"ready": True, "pid": os.getpid()})
        while True:
            command = control.recv()
            if command["action"] == "close":
                break
            if command["action"] == "expire":
                with server._machine_agent_session_lock:
                    server._machine_agent_sessions[command["session"]]["expires_at"] = time.time() - 1
                control.send({"expired": True})
            elif command["action"] == "direct-list":
                try:
                    server.dispatch_universal_machine_route({
                        "method": "GET", "path": "/api/universal/private-root-grant",
                        "body": {"action": "list-sessions"}})
                except Exception as exc:
                    control.send({"refused": str(exc)})
                else:
                    control.send({"refused": None})
    except Exception as exc:
        control.send({"error": "%s: %s" % (type(exc).__name__, exc)})
    finally:
        if server is not None:
            server.close()
        patches.undo()
        control.close()


def _child_reply(connection):
    assert connection.poll(180), "isolated machine owner did not answer"
    reply = connection.recv()
    assert "error" not in reply, reply
    return reply


def test_picked_canonical_session_grant_reaches_separate_process_status(
    settings, tmp_path, monkeypatch
):
    descriptor = tmp_path / "separate-owner-machine.json"
    workspace = tmp_path / "machine-owner"
    workspace.mkdir()
    monkeypatch.setattr(transport, "default_runtime_descriptor_path", lambda: descriptor)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    owner = context.Process(target=_separate_machine_owner, args=(
        child, str(workspace), str(descriptor), str(settings["path"]),
        {key: str(value) for key, value in settings["registry_files"].items()},
        settings["registry_blob"]))
    owner.start()
    child.close()
    try:
        ready = _child_reply(parent)
        assert ready["ready"] is True and ready["pid"] != os.getpid()
        chosen = transport.UniversalRuntimeClient(descriptor, settings["provider"])
        other = transport.UniversalRuntimeClient(descriptor, settings["provider"])
        chosen.bind_agent_session(runtime="codex", external_session_id="external-picked-is-not-grant-id")
        other.bind_agent_session(runtime="codex", external_session_id="external-other-is-not-grant-id")
        view = _request(settings, {"action": "list"})
        registry = view["private_grant_sessions"]
        assert registry["status"] == "ok"
        rows = registry["sessions"]
        assert {row["session_id"] for row in rows} == {
            chosen.agent_session_root, other.agent_session_root}
        assert [row["issued_at"] for row in rows] == sorted(
            (row["issued_at"] for row in rows), reverse=True)
        picked = next(row for row in rows if row["session_id"] == chosen.agent_session_root)
        assert picked["runtime"] == "codex"
        assert picked["connected"] is True and picked["selectable"] is True
        assert picked["title"] == "codex Agent Session"
        assert not chosen.private_root_grant_status(path=PATH, operation="write_file")["granted"]
        payload = {"action": "grant-private-root", "id": "client-a",
                   "runtime": picked["runtime"], "session_id": picked["session_id"]}
        assert set(payload) == {"action", "id", "runtime", "session_id"}
        _request(settings, payload)
        status = chosen.private_root_grant_status(path=PATH, operation="write_file")
        assert status["granted"] is True and status["agent_session"] == picked["session_id"]
        other_status = other.private_root_grant_status(path=PATH, operation="write_file")
        assert not other_status["granted"]
        with pytest.raises(transport.MachineTransportError):
            chosen.request("GET", "/api/universal/private-root-grant", {"action": "list-sessions"})
        parent.send({"action": "direct-list"})
        assert _child_reply(parent)["refused"]
        parent.send({"action": "expire", "session": other.agent_session_root})
        assert _child_reply(parent)["expired"] is True
        active = _request(settings, {"action": "list"})["private_grant_sessions"]["sessions"]
        assert [row["session_id"] for row in active] == [chosen.agent_session_root]
        receipt = {
            "picked_session_id": picked["session_id"], "runtime": picked["runtime"],
            "root_id": status["root_id"], "other_session_id": other.agent_session_root,
            "chosen_granted": status["granted"], "other_granted": other_status["granted"],
            "child_pid": ready["pid"],
        }
        (tmp_path / "privgrant-cross-process-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    finally:
        if owner.is_alive():
            parent.send({"action": "close"})
        owner.join(60)
        parent.close()
        assert not owner.is_alive(), "isolated machine owner did not close naturally"


def _session_surface(properties):
    """A real relation snapshot; no runtime startup or filesystem is needed."""
    from nodelang.application_server import ApplicationServer

    roles = {name: "court:role:" + name for name in ("property", "owner", "label", "value")}
    session = "app:agent-session:runtime:display-court"
    cells = {root: Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"") for root in (*roles.values(), session)}
    property_roots = []
    for index, (label, value) in enumerate(properties):
        root = "court:property:%d" % index
        label_root, value_root = root + ":label", root + ":value"
        cells[label_root] = Cell(label_root, NULL_CELL_ID, NULL_CELL_ID, label.encode("utf-8"))
        cells[value_root] = Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
        relation = compose_relation_cells((
            (roles["owner"], session), (roles["label"], label_root), (roles["value"], value_root)),
            relation_id=root)
        cells.update((cell.id, cell) for cell in relation.cells)
        property_roots.append(root)
    canvas = compose_relation_cells(((roles["property"], root) for root in property_roots),
                                    relation_id="court:canvas")
    cells.update((cell.id, cell) for cell in canvas.cells)
    server = ApplicationServer.__new__(ApplicationServer)
    server.universal_registry = SimpleNamespace(roles=roles, canvas_root="court:canvas")
    return server, Snapshot(1, cells), session


def test_duplicate_display_titles_do_not_block_runtime_identity():
    server, snapshot, session = _session_surface([
        ("runtime", "codex"), ("session fingerprint", "a" * 64),
        ("title", "August 7 sheet work"), ("title", "Another display title"),
        ("title", "A third title must not restore an arbitrary choice"),
    ])
    surface = server._machine_session_surface_index(snapshot)
    assert surface[session].get("title") in (None, "", "Session title unavailable")
    assert server._machine_session_surface_values(snapshot, session) == {
        "runtime": "codex", "session fingerprint": "a" * 64}


@pytest.mark.parametrize("identity_label,value", [
    ("runtime", "codex"), ("session fingerprint", "a" * 64),
])
def test_duplicate_runtime_identity_properties_still_refuse(identity_label, value):
    server, snapshot, _session = _session_surface([
        ("runtime", "codex"), ("session fingerprint", "a" * 64),
        (identity_label, value), ("title", "Display title"),
    ])
    with pytest.raises(InvalidCell, match="runtime Agent Session surface property is ambiguous"):
        server._machine_session_surface_index(snapshot)
