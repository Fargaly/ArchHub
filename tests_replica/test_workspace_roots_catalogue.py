"""Workspace roots live in the one graph: signed commands, a pinned key, a projection.

The graph is a throwaway authority (Governance composition). Signing uses an
in-memory ECDSA P-256 key standing in for the CNG key; the CNG key's own courts
live in test_workspace_roots_signing.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import threading
import uuid

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from nodelang import workspace_roots_catalogue as roots
from nodelang import workspace_roots_signing as roots_signing
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.unified_authority import (
    BootstrapManifest,
    create_unified_authority,
    open_unified_authority,
)
from nodelang.universal_cell import CellStore, InvalidCell


FOUNDER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(7, 39)))
FOUNDER_PUBLIC = FOUNDER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)
OPERATIONS = uuid.UUID("4f7d2d0e-5b6f-4f7e-9b1d-3c1f0a9e2b71")


def _op(label: str) -> str:
    return str(uuid.uuid5(OPERATIONS, label))


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = FOUNDER_PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return FOUNDER_PRIVATE.sign(payload)


class _Key:
    """An ECDSA P-256 signer/verifier with the CNG wire format (raw r||s, hex)."""

    def __init__(self):
        self._private = ec.generate_private_key(ec.SECP256R1())

    def public_blob(self) -> bytes:
        numbers = self._private.public_key().public_numbers()
        return (b"ECS1" + (32).to_bytes(4, "little")
                + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big"))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.public_blob()).hexdigest()

    def sign(self, payload: bytes) -> str:
        r, s = decode_dss_signature(self._private.sign(payload, ec.ECDSA(hashes.SHA256())))
        return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()

    def verify(self, key_id, version, payload, signature) -> bool:
        try:
            raw = bytes.fromhex(signature)
            if key_id != roots.KEY_ID or version != 1 or len(raw) != 64:
                return False
            self._private.public_key().verify(
                encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                     int.from_bytes(raw[32:], "big")),
                payload, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False

    def verify_blob(self, blob, key_id, version, payload, signature) -> bool:
        return bytes(blob) == self.public_blob() and self.verify(key_id, version, payload, signature)


def _authority(database):
    provider = MemorySigningKeyProvider("roots-court", b"r" * 32)
    authority = create_unified_authority(
        CellStore(database),
        provider,
        key_id="roots-court",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Workspace roots court",
        bootstrap_session_public_key=FOUNDER_PUBLIC,
        composition_labels=("Governance", "Projects"),
    )
    return authority, provider


@pytest.fixture()
def graph(tmp_path):
    authority, provider = _authority(tmp_path / "roots.sqlite3")
    caller = _Caller(authority)
    catalogue = roots.install_workspace_root_catalogue(
        authority, operation_id=_op("install"), caller=caller
    )
    key = _Key()
    files = {"snapshot_path": tmp_path / "home" / "workspace-roots.json",
             "pin_path": tmp_path / "home" / "workspace-roots.pin"}
    return {"authority": authority, "provider": provider, "caller": caller,
            "catalogue": catalogue, "key": key, "files": files,
            "database": tmp_path / "roots.sqlite3", "tmp": tmp_path}




class _Owner:
    """Stands in for the Windows prompt: approves or declines each signature."""

    def __init__(self, key, approve=True):
        self.key, self.approve, self.asked, self.pins = key, approve, 0, []

    def factory(self, pinned):
        self.pins.append(pinned)
        owner = self

        class Signer:
            def sign(self, payload):
                owner.asked += 1
                if not owner.approve:
                    raise roots_signing.SigningUnavailable("the owner declined (0x800704c7)")
                return owner.key.sign(payload)
        return Signer()


def _change(g, request, owner=None, lock=None):
    owner = owner or _Owner(g["key"])
    return roots.owner_change(
        g["authority"], g["catalogue"], request, caller=g["caller"],
        operation_id=str(uuid.uuid4()), lock=lock or threading.RLock(),
        signer_factory=owner.factory, fingerprint_of=g["key"].fingerprint,
        verifier=g["key"], **g["files"])


def _register(g, root_id, folder, privacy="private", owner=None):
    return _change(g, {"action": "register", "id": root_id, "path": str(folder),
                       "privacy": privacy, "profile": "client", "writers": ["claude"]}, owner)


def _state(g):
    return roots.read_state(g["authority"], g["catalogue"], caller=g["caller"])


def test_install_is_published_once_and_answered_from_the_head(graph):
    again = roots.install_workspace_root_catalogue(
        graph["authority"], operation_id=_op("install-again"), caller=graph["caller"])
    assert again == graph["catalogue"]


def test_the_first_registration_pins_the_key_and_projects_a_matching_snapshot(graph, tmp_path):
    folder = tmp_path / "client-a"
    folder.mkdir()
    view = _register(graph, "client-a", folder)
    assert view["projection"] == "match" and view["key_pinned"]
    assert view["built_in"] == {"id": "archhub", "path": roots.BUILT_IN_PATH, "removable": False}
    assert view["promise"] == ("Removing a workspace only stops ArchHub from governing it. "
                               "Your files are never deleted.")
    _revision, state, pin = _state(graph)
    assert pin == graph["key"].fingerprint()
    assert [(r["root_id"], r["state"], r["privacy"]) for r in state] == [
        ("client-a", "registered", "private")]
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert document["format_version"] == 3 and document["graph_revision"] == 2
    assert document["removed"] == []
    assert document["key_fingerprint"] == graph["key"].fingerprint()
    assert [entry["id"] for entry in document["roots"]] == ["client-a"]
    assert json.loads(graph["files"]["pin_path"].read_text(encoding="utf-8")) == {
        "format": roots.PIN_FORMAT, "key_id": roots.KEY_ID,
        "fingerprint": graph["key"].fingerprint(), "public_blob": graph["key"].public_blob().hex()}


def test_later_signatures_are_made_only_by_the_graph_pinned_key(graph, tmp_path):
    for name in ("client-a", "client-b"):
        (tmp_path / name).mkdir()
    first = _Owner(graph["key"])
    _register(graph, "client-a", tmp_path / "client-a", owner=first)
    assert first.pins == [None, graph["key"].fingerprint()]
    later = _Owner(graph["key"])
    _register(graph, "client-b", tmp_path / "client-b", owner=later)
    assert later.pins == [graph["key"].fingerprint()], "a later signer was not given the pin"


def test_unregister_changes_only_the_state_and_keeps_history_and_files(graph, tmp_path):
    folder = tmp_path / "client-a"
    folder.mkdir()
    (folder / "keep.txt").write_text("client work", encoding="utf-8")
    _register(graph, "client-a", folder)
    view = _change(graph, {"action": "unregister", "id": "client-a"})
    assert view["projection"] == "match"
    assert (folder / "keep.txt").read_text(encoding="utf-8") == "client work"
    _revision, state, _pin = _state(graph)
    assert [(r["root_id"], r["state"], r["path"]) for r in state] == [
        ("client-a", "unregistered", str(folder))]
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert document["roots"] == [] and document["graph_revision"] == 3
    with pytest.raises(roots.WorkspaceRootRefused, match="already unregistered"):
        _change(graph, {"action": "unregister", "id": "client-a"})
    with pytest.raises(roots.WorkspaceRootRefused, match="already used"):
        _register(graph, "client-a", folder)


def test_reverse_order_registrations_project_matching_files(graph, tmp_path):
    for name in ("zeta", "alpha", "mid"):
        (tmp_path / name).mkdir()
    for name in ("zeta", "alpha", "mid"):
        view = _register(graph, name, tmp_path / name)
        assert view["projection"] == "match", name
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["roots"]] == ["alpha", "mid", "zeta"]
    assert roots.boot_check(graph["authority"], graph["catalogue"], caller=graph["caller"],
                            verifier=graph["key"], **graph["files"]) == "match"
    view = _change(graph, {"action": "unregister", "id": "alpha"})
    assert view["projection"] == "match"


def test_a_declined_owner_prompt_changes_nothing(graph, tmp_path):
    folder = tmp_path / "client-a"
    folder.mkdir()
    declined = _Owner(graph["key"], approve=False)
    before = graph["authority"].store.revision
    with pytest.raises(roots.WorkspaceRootRefused, match="did not approve"):
        _register(graph, "client-a", folder, owner=declined)
    assert declined.asked == 1
    assert graph["authority"].store.revision == before, "the graph changed without approval"
    assert not graph["files"]["snapshot_path"].exists() and not graph["files"]["pin_path"].exists()
    _register(graph, "client-a", folder)
    before = graph["authority"].store.revision
    with pytest.raises(roots.WorkspaceRootRefused, match="did not approve"):
        _change(graph, {"action": "unregister", "id": "client-a"}, _Owner(graph["key"], False))
    assert graph["authority"].store.revision == before
    assert [r["state"] for r in _state(graph)[1]] == ["registered"]


def test_a_graph_that_moves_during_approval_is_refused(graph, tmp_path):
    for name in ("client-a", "client-b"):
        (tmp_path / name).mkdir()
    _register(graph, "client-a", tmp_path / "client-a")

    class Racing(_Owner):
        def factory(self, pinned):
            inner = super().factory(pinned)
            test_graph = graph

            class Signer:
                def sign(self, payload):
                    _change(test_graph, {"action": "unregister", "id": "client-a"})
                    return inner.sign(payload)
            return Signer()
    with pytest.raises(roots.WorkspaceRootRefused, match="changed while waiting"):
        _register(graph, "client-b", tmp_path / "client-b", owner=Racing(graph["key"]))
    assert [r["root_id"] for r in _state(graph)[1]] == ["client-a"]


def test_the_reopened_graph_verifies_and_holds_the_same_roots_and_history(graph, tmp_path):
    folder = tmp_path / "client-b"
    folder.mkdir()
    _register(graph, "client-b", folder, privacy="public")
    _change(graph, {"action": "unregister", "id": "client-b"})
    before = _state(graph)
    manifest = graph["authority"].manifest.to_json()
    graph["authority"].store.close()
    reopened = open_unified_authority(CellStore(graph["database"]),
                                      BootstrapManifest.from_json(manifest), graph["provider"])
    after = roots.read_state(reopened, graph["catalogue"], caller=_Caller(reopened))
    assert after == before


def test_a_different_key_is_never_pinned_over_the_graph_pin(graph, tmp_path):
    folder = tmp_path / "client-a"
    folder.mkdir()
    _register(graph, "client-a", folder)
    with pytest.raises(InvalidCell, match="already pinned"):
        roots.pin_signing_key(graph["authority"], graph["catalogue"], "ab" * 32,
                              caller=graph["caller"], operation_id=_op("other"))


def test_no_root_is_committed_before_a_key_is_pinned(graph, tmp_path):
    folder = tmp_path / "client-c"
    folder.mkdir()
    values = roots.admit_folder(str(folder), "client-c", "private", "client", ["claude"], ())
    with pytest.raises(InvalidCell, match="pinned"):
        roots.register_root(graph["authority"], graph["catalogue"], values,
                            caller=graph["caller"], operation_id=_op("early"))


@pytest.mark.parametrize("case", ["drive-root", "missing", "inside-archhub", "bad-id",
                                  "archhub-id", "bad-writer", "bad-privacy", "nested"])
def test_folders_the_hooks_would_refuse_are_refused_before_any_prompt(graph, tmp_path, case):
    outer = tmp_path / "outer"
    (outer / "inner").mkdir(parents=True)
    _register(graph, "outer", outer)
    ok = tmp_path / "fine"
    ok.mkdir()
    path, root_id, privacy, writers = {
        "drive-root": ("C:" + chr(92), "x", "private", ["claude"]),
        "missing": (str(tmp_path / "nope"), "x", "private", ["claude"]),
        "inside-archhub": (roots.BUILT_IN_PATH + chr(92) + "20.CLIENTS", "x", "private", ["claude"]),
        "bad-id": (str(ok), "Bad Id", "private", ["claude"]),
        "archhub-id": (str(ok), "archhub", "private", ["claude"]),
        "bad-writer": (str(ok), "x", "private", ["someone"]),
        "bad-privacy": (str(ok), "x", "secret", ["claude"]),
        "nested": (str(outer / "inner"), "x", "private", ["claude"]),
    }[case]
    owner = _Owner(graph["key"])
    with pytest.raises(roots.WorkspaceRootRefused):
        _change(graph, {"action": "register", "id": root_id, "path": path, "privacy": privacy,
                        "profile": "client", "writers": writers}, owner)
    assert owner.asked == 0, "the owner was asked about a refused folder"


@pytest.mark.parametrize("request_body", [
    None, {"action": "delete", "id": "x"}, {"action": "unregister"},
    {"action": "unregister", "id": "x", "path": "C:/x"}, {"action": "list", "extra": 1}],
    ids=["none", "unknown-action", "no-id", "extra-field", "list-extra"])
def test_malformed_requests_are_refused(graph, request_body):
    with pytest.raises(roots.WorkspaceRootRefused):
        _change(graph, request_body)


def test_the_boot_check_sees_every_divergence(graph, tmp_path):
    folder = tmp_path / "client-e"
    folder.mkdir()

    def check():
        return roots.boot_check(graph["authority"], graph["catalogue"], caller=graph["caller"],
                                verifier=graph["key"], **graph["files"])
    assert check() == "missing"
    _register(graph, "client-e", folder)
    assert check() == "match"
    assert _change(graph, {"action": "list"})["projection"] == "match"
    snapshot = graph["files"]["snapshot_path"]
    original = snapshot.read_bytes()
    snapshot.write_bytes(original.replace(b'"private"', b'"public"'))
    assert check() == "unsigned"
    snapshot.write_bytes(original)
    pin_file = graph["files"]["pin_path"]
    kept_pin = pin_file.read_bytes()
    pin_file.write_text(json.dumps({"format": roots.PIN_FORMAT, "key_id": roots.KEY_ID,
                                    "fingerprint": "cd" * 32}), encoding="utf-8")
    assert check() == "unpinned"
    pin_file.write_bytes(kept_pin)
    assert check() == "match"
    # The graph moved but the hooks' files did not (a crash between commit and write).
    roots.unregister_root(graph["authority"], graph["catalogue"], "client-e",
                          caller=graph["caller"], operation_id=_op("unregister-e"))
    assert check() == "mismatch"
    view = _change(graph, {"action": "republish"})
    assert view["projection"] == "match" and check() == "match"
    snapshot.unlink()
    assert check() == "mismatch"


def test_republish_before_any_registration_is_refused(graph):
    with pytest.raises(roots.WorkspaceRootRefused, match="nothing is registered"):
        _change(graph, {"action": "republish"})


def test_a_substitute_signer_is_refused_by_the_pin_before_anything_commits(graph, tmp_path):
    for name in ("client-f", "client-g"):
        (tmp_path / name).mkdir()
    _register(graph, "client-f", tmp_path / "client-f")
    before = graph["authority"].store.revision

    def substitute(pinned):
        raise roots_signing.SigningUnavailable("the existing signing key is not the pinned key; refused")
    with pytest.raises(roots.WorkspaceRootRefused, match="not the pinned key"):
        roots.owner_change(
            graph["authority"], graph["catalogue"],
            {"action": "register", "id": "client-g", "path": str(tmp_path / "client-g"),
             "privacy": "private", "profile": "client", "writers": ["claude"]},
            caller=graph["caller"], operation_id=str(uuid.uuid4()), lock=threading.RLock(),
            signer_factory=substitute, fingerprint_of=graph["key"].fingerprint,
            verifier=graph["key"], **graph["files"])
    assert graph["authority"].store.revision == before


def test_the_projection_is_read_by_the_hooks_as_valid_with_the_roots(graph, tmp_path, monkeypatch):
    """End to end: graph -> signed projection -> the live hook reader (stage 1 v4)."""
    import importlib.util
    hooks = Path(__file__).resolve().parents[1] / "governance_hooks"
    if not (hooks / "workspace_roots.py").exists():
        pytest.skip("the governance hook reader is not beside this tree")
    monkeypatch.syspath_prepend(str(hooks))
    spec = importlib.util.spec_from_file_location("workspace_roots_v4", hooks / "workspace_roots.py")
    reader = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, reader)
    spec.loader.exec_module(reader)
    for name in ("client-a", "client-p"):
        (tmp_path / name).mkdir()
    _register(graph, "client-a", tmp_path / "client-a")
    _register(graph, "client-p", tmp_path / "client-p", privacy="public")

    class Public:
        def public_blob(self):
            return graph["key"].public_blob()

        def verify(self, *args):
            return graph["key"].verify(*args)

        def verify_blob(self, blob, *args):
            return blob == graph["key"].public_blob() and graph["key"].verify(*args)
    registry = reader.load(path=graph["files"]["snapshot_path"], provider=Public(),
                           last_good=tmp_path / "local" / "last-good.json",
                           pin=graph["files"]["pin_path"])
    assert registry.state == "valid", registry.reason
    assert [(r.id, r.privacy) for r in registry.registered] == [("client-a", "private"),
                                                               ("client-p", "public")]
    _change(graph, {"action": "unregister", "id": "client-a"})
    registry = reader.load(path=graph["files"]["snapshot_path"], provider=Public(),
                           last_good=tmp_path / "local" / "last-good.json",
                           pin=graph["files"]["pin_path"])
    assert registry.state == "valid" and [r.id for r in registry.registered] == ["client-p"]

    class Impostor(Public):
        def public_blob(self):
            return b"another key"
    registry = reader.load(path=graph["files"]["snapshot_path"], provider=Impostor(),
                           last_good=tmp_path / "local" / "last-good.json",
                           pin=graph["files"]["pin_path"])
    assert registry.state == "degraded" and registry.registered == ()


def test_a_removed_folder_is_a_signed_tombstone_until_registered_again(graph, tmp_path):
    """Founder decision 2026-09-30: a folder that was registered and then removed
    stays blocked for agent writes until it is registered again; the snapshot the
    hooks verify carries it as a signed tombstone, never a silent list edit."""
    folder = tmp_path / "client-a"
    folder.mkdir()
    _register(graph, "client-a", folder)
    _change(graph, {"action": "unregister", "id": "client-a"})
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert document["roots"] == []
    assert document["removed"] == [{"id": "client-a", "path": str(folder),
                                    "identity": list(roots.folder_identity(str(folder)))}]
    # Registered again (a new id; ids are never reused): the tombstone is gone.
    view = _register(graph, "client-a-again", folder)
    assert view["projection"] == "match"
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["roots"]] == ["client-a-again"]
    assert document["removed"] == []
    # Removed twice: one tombstone per folder.
    _change(graph, {"action": "unregister", "id": "client-a-again"})
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["removed"]] == ["client-a"]


def test_registering_a_parent_lifts_the_tombstone_of_a_removed_child_inside_it(graph, tmp_path):
    """Founder decision 2026-09-30: he registers the parent (E:/01.PERSONAL) to cover
    BBC4 inside it. The child's tombstone goes; an unrelated tombstone stays."""
    parent = tmp_path / "01.PERSONAL"
    child = parent / "BBC4"
    child.mkdir(parents=True)
    elsewhere = tmp_path / "old-client"
    elsewhere.mkdir()
    _register(graph, "bbc4", child)
    _register(graph, "old-client", elsewhere)
    _change(graph, {"action": "unregister", "id": "bbc4"})
    _change(graph, {"action": "unregister", "id": "old-client"})
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["removed"]] == ["bbc4", "old-client"]
    view = _register(graph, "personal", parent)
    assert view["projection"] == "match"
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["roots"]] == ["personal"]
    assert [entry["id"] for entry in document["removed"]] == ["old-client"]


def test_a_sibling_sharing_the_parents_name_prefix_keeps_its_tombstone(graph, tmp_path):
    parent = tmp_path / "Clients"
    parent.mkdir()
    sibling = tmp_path / "Clients-2024"
    sibling.mkdir()
    _register(graph, "old-2024", sibling)
    _change(graph, {"action": "unregister", "id": "old-2024"})
    _register(graph, "clients", parent)
    document = json.loads(graph["files"]["snapshot_path"].read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["removed"]] == ["old-2024"]
