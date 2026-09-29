"""The application's side of a root-bound write permit: the same pinned, signed
registry the hooks read, one captured key blob, the live folder identity and the
root's writers. Synthetic folders and an in-memory court key.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.cell_cde_authority import _path
from nodelang.universal_cell import InvalidCell
from tests_replica.test_workspace_roots_catalogue import _Key


class _Store:
    """A key store answering one blob per read (the swap court changes it)."""

    def __init__(self, *keys):
        self.keys, self.reads = list(keys), 0

    def public_blob(self):
        key = self.keys[min(self.reads, len(self.keys) - 1)]
        self.reads += 1
        return key.public_blob()

    def verify_blob(self, blob, key_id, version, payload, signature):
        for key in self.keys:
            if key.public_blob() == bytes(blob):
                return key.verify(key_id, version, payload, signature)
        return False


# The graph's current projection in these courts: the newest registry a court
# published (current=True). test_workspace_roots_graph_current.py proves the
# real seam against a clean coordination host.
_GRAPH = {"digest": None}


# The registry digest schema, stated here independently of the module so the
# court fails if the issuer's and the owner's schemas ever drift apart.
DIGEST_SCHEMA = "archhub.workspace-roots.registry-digest/v1"


def graph_digest(body):
    return hashlib.sha256(roots.canonical({"schema": DIGEST_SCHEMA, "body": body})).hexdigest()


def graph_state():
    """The verified statement a canonical instance would return (seam stand-in)."""
    if _GRAPH["digest"] is None:
        raise OSError("no graph answered")
    return {"purpose": "archhub.workspace-roots-state/v1", "graph_id": "court", "request_id": "r",
            "nonce": "0" * 32, "revision": 1, "registry_digest": _GRAPH["digest"]}


def _no_live_graph():
    raise AssertionError("a court reached for the live coordination service")


@pytest.fixture(autouse=True)
def _graph_is_the_newest_registry(monkeypatch):
    monkeypatch.setattr(roots, "verified_graph_state", graph_state, raising=False)
    monkeypatch.setattr(roots, "graph_context", _no_live_graph, raising=False)


def _registry(tmp_path, key, entries, *, pin=None, signer=None, revision=3, target=None,
              current=True):
    body = {"format": roots.SNAPSHOT_FORMAT, "format_version": roots.SNAPSHOT_VERSION,
            "key_id": roots.KEY_ID, "key_version": 1,
            "key_fingerprint": pin or key.fingerprint(), "graph_revision": revision, "roots": entries}
    files = {"snapshot_path": target or (tmp_path / "workspace-roots.json"),
             "pin_path": tmp_path / "workspace-roots.pin",
             "last_good_path": tmp_path / "last-good.json"}
    files["snapshot_path"].write_bytes(roots.canonical(
        {**body, "signature": (signer or key).sign(roots.canonical(body))}))
    if current:
        _GRAPH["digest"] = graph_digest(body)
    files["pin_path"].write_bytes(roots.canonical(
        {"format": roots.PIN_FORMAT, "key_id": roots.KEY_ID, "fingerprint": pin or key.fingerprint()}))
    return files


def _entry(folder, root_id="client-a", writers=("claude",)):
    return {"id": root_id, "path": str(folder), "privacy": "private", "profile": "client",
            "writers": list(writers), "identity": list(roots.folder_identity(str(folder)))}


@pytest.fixture()
def world(tmp_path):
    folder = tmp_path / "client-a"
    folder.mkdir()
    key = _Key()
    return {"tmp": tmp_path, "folder": folder, "key": key,
            "files": _registry(tmp_path, key, [_entry(folder)])}


def test_the_permit_path_form_is_admitted_by_the_cde_path_rules():
    assert _path("workspace-roots/client-a/sub/a.md") == "workspace-roots/client-a/sub/a.md"
    for bad in ("workspace-roots/../x", "/workspace-roots/a/b", "C:/x/a.md", "workspace-roots//a"):
        with pytest.raises(InvalidCell):
            _path(bad)


def test_a_registered_writer_is_admitted_and_bound_to_the_registration(world):
    container_id, digest = roots.root_bound_admission(
        "workspace-roots/client-a/sub/a.md", runtime="claude",
        verifier=_Store(world["key"]), **world["files"])
    assert container_id == "workspace-root:client-a"
    entry = json.loads(world["files"]["snapshot_path"].read_text(encoding="utf-8"))["roots"][0]
    assert digest == hashlib.sha256(roots.canonical(
        {"root": entry, "key": world["key"].fingerprint()})).hexdigest()


@pytest.mark.parametrize("path", ["workspace-roots/client-b/a.md", "workspace-roots/client-a",
                                  "workspace-roots/Client-A/a.md", "workspace-roots/client-a/../x"])
def test_an_unregistered_or_malformed_root_path_is_refused(world, path):
    with pytest.raises(InvalidCell):
        roots.root_bound_admission(path, runtime="claude", verifier=_Store(world["key"]),
                                   **world["files"])


def test_a_runtime_that_is_not_a_writer_is_refused(world):
    with pytest.raises(InvalidCell, match="not a writer"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="codex",
                                   verifier=_Store(world["key"]), **world["files"])


def test_a_swapped_folder_is_refused(world):
    import shutil
    shutil.rmtree(world["folder"])
    world["folder"].mkdir()
    with pytest.raises(InvalidCell, match="unavailable"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(world["key"]), **world["files"])


def test_no_pin_no_permit(world):
    world["files"]["pin_path"].unlink()
    with pytest.raises(InvalidCell, match="unavailable"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(world["key"]), **world["files"])


def test_a_key_that_is_not_the_pinned_key_admits_nothing(world):
    with pytest.raises(InvalidCell, match="not the pinned key"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(_Key()), **world["files"])


def test_a_key_swapped_after_the_pin_check_admits_nothing(world, tmp_path):
    """The store answers the pinned key first, then a substitute that signed a forged
    registry naming the pin: verification uses the ONE captured blob."""
    substitute = _Key()
    forged_dir = tmp_path / "forged"
    forged_dir.mkdir()
    files = _registry(forged_dir, world["key"], [_entry(world["folder"], writers=("codex",))],
                      signer=substitute)
    store = _Store(world["key"], substitute)
    with pytest.raises(InvalidCell, match="does not verify"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="codex",
                                   verifier=store, **files)
    assert store.reads == 1, "the key store was read again after the pin check"


def test_an_unsigned_registry_admits_nothing(world):
    document = json.loads(world["files"]["snapshot_path"].read_text(encoding="utf-8"))
    document["roots"][0]["writers"] = ["claude", "codex"]
    world["files"]["snapshot_path"].write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(InvalidCell, match="does not verify"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="codex",
                                   verifier=_Store(world["key"]), **world["files"])


def test_the_real_verifier_checks_the_exact_blob_it_is_given():
    from nodelang.workspace_roots_signing import CngVerifier
    key, other = _Key(), _Key()
    verifier = CngVerifier("ArchHub-court-never-created")
    signature = key.sign(b"payload")
    key_id = "cng:ArchHub-court-never-created"
    assert verifier.verify_blob(key.public_blob(), key_id, 1, b"payload", signature)
    assert not verifier.verify_blob(other.public_blob(), key_id, 1, b"payload", signature)
    assert not verifier.verify_blob(key.public_blob(), key_id, 1, b"payload!", signature)


# --- v2 (Ping): a replayed older registry is refused against the hooks' last-good copy.

def _last_good(world, revision, entries=None, signer=None):
    """The hooks' last-good copy at `revision` (a signed snapshot, like the hooks keep)."""
    scratch = world["tmp"] / ("kept-%d" % revision)
    scratch.mkdir(exist_ok=True)
    written = _registry(scratch, world["key"], entries if entries is not None else [_entry(world["folder"])],
                        revision=revision, signer=signer, current=False)
    world["files"]["last_good_path"].write_bytes(written["snapshot_path"].read_bytes())


def test_a_snapshot_older_than_the_last_good_copy_is_a_replay(world):
    _last_good(world, 5)
    with pytest.raises(InvalidCell, match="replay"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(world["key"]), **world["files"])


def test_a_snapshot_at_or_after_the_last_good_copy_is_admitted(world):
    for revision in (3, 2):
        _last_good(world, revision)
        assert roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                          verifier=_Store(world["key"]), **world["files"])


def test_a_forged_last_good_copy_admits_nothing(world):
    _last_good(world, 1, signer=_Key())
    with pytest.raises(InvalidCell, match="last-good copy does not verify"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(world["key"]), **world["files"])


def test_a_registry_that_is_not_the_graphs_current_projection_admits_nothing(world):
    _GRAPH["digest"] = "ab" * 32  # the graph moved on (e.g. revoked the root); files stale
    with pytest.raises(InvalidCell, match="not the graph's current projection"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(world["key"]), **world["files"])


def test_an_unavailable_graph_admits_nothing(world, monkeypatch):
    def unavailable():
        raise OSError("connection refused")
    monkeypatch.setattr(roots, "verified_graph_state", unavailable)
    with pytest.raises(InvalidCell, match="unavailable"):
        roots.root_bound_admission("workspace-roots/client-a/a.md", runtime="claude",
                                   verifier=_Store(world["key"]), **world["files"])
