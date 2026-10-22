"""The permit issuer asks the graph's owner whether the registry files are its
CURRENT projection. A real clean runtime and the real CleanCoordinationHost over the
owner: the answer is the owner's own revision and registry digest; no key, no nonce,
no signature (founder 2026-10-22: the account is the identity, never a machine key).
The hooks' files are written by owner_change with a court key; revoking a root in
the graph leaves them stale but still valid (with a matching last-good).
No court here reaches the live service.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
import uuid

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.clean_coordination_host import CleanCoordinationHost
from nodelang.universal_cell import InvalidCell
from tests_replica.test_clean_server_admission import _provision_clean_runtime
from tests_replica.test_workspace_root_write_admission import _Store, graph_digest
from tests_replica.test_workspace_roots_catalogue import _Key


@pytest.fixture()
def graph(tmp_path, monkeypatch):
    # The court can run with --basetemp inside the source tree. Keep its fake
    # built-in workspace separate from the fake client, just as on an instance.
    built_in = tmp_path / "built-in-archhub"
    built_in.mkdir()
    monkeypatch.setattr(roots, "built_in_path", lambda: str(built_in))
    built, provider = _provision_clean_runtime(tmp_path, root_name="graph-current")
    authority = built.location.authority
    # The owner the host delegates to: the desktop's own graph, caller and route.
    owner = SimpleNamespace(
        universal_store=authority.store,
        universal_registry=SimpleNamespace(authorization=SimpleNamespace(subject_root=built.caller.actor_root)),
        clean_authority=authority,
        clean_caller=built.caller,
        _clean_workspace_roots=None,
        dispatch_universal_machine_route=lambda request: (_ for _ in ()).throw(
            InvalidCell("the court owner serves only workspace roots")),
    )
    host = CleanCoordinationHost(owner)
    answers = []

    def transport(payload):
        answer = host.dispatch(payload)
        answers.append(answer)
        return answer

    context = {"transport": transport}
    monkeypatch.setattr(roots, "graph_context", lambda: dict(context))
    key = _Key()
    home = tmp_path / "home"
    files = {"snapshot_path": home / "workspace-roots.json", "pin_path": home / "workspace-roots.pin"}
    catalogue = roots.install_workspace_root_catalogue(authority, operation_id=str(uuid.uuid4()),
                                                       caller=built.caller)
    folder = tmp_path / "client-a"
    folder.mkdir()
    roots.owner_change(
        authority, catalogue,
        {"action": "register", "id": "client-a", "path": str(folder), "privacy": "private",
         "profile": "client", "writers": ["claude"]},
        caller=built.caller, operation_id=str(uuid.uuid4()), lock=threading.RLock(),
        signer_factory=lambda pinned: key, fingerprint_of=key.fingerprint, verifier=key, **files)
    last_good = home / "last-good.json"
    last_good.write_bytes(files["snapshot_path"].read_bytes())  # the hooks verified it too
    return {"built": built, "authority": authority, "owner": owner, "host": host, "key": key,
            "files": files, "last_good": last_good, "catalogue": catalogue, "context": context,
            "answers": answers, "provider": provider}


def _admit(graph):
    return roots.root_bound_registration("workspace-roots/client-a/a.md", runtime="claude",
                                         verifier=_Store(graph["key"]),
                                         last_good_path=graph["last_good"], **graph["files"])


def test_an_unchanged_registration_is_admitted_and_the_read_commits_nothing(graph):
    before = graph["authority"].store.revision
    container, _digest, entry = _admit(graph)
    assert container == "workspace-root:client-a" and entry["writers"] == ["claude"]
    answer = graph["answers"][-1]
    assert answer["graph_id"] == graph["authority"].manifest.graph_id
    assert type(answer["revision"]) is int and type(answer["registry_digest"]) is str
    assert graph["authority"].store.revision == before, "the state read committed"


def test_a_root_the_graph_revoked_is_refused_while_the_old_files_and_last_good_still_verify(graph):
    assert _admit(graph)
    roots.unregister_root(graph["authority"], graph["catalogue"], "client-a",
                          caller=graph["built"].caller, operation_id=str(uuid.uuid4()))
    with pytest.raises(InvalidCell, match="not the graph's current projection"):
        _admit(graph)


def test_an_owner_refusal_is_refused(graph):
    graph["context"]["transport"] = lambda payload: {"ok": False, "error": "owner declined"}
    with pytest.raises(InvalidCell, match="unavailable"):
        _admit(graph)


def test_an_unavailable_owner_is_refused(graph):
    def down(payload):
        raise ConnectionRefusedError("127.0.0.1:8474")
    graph["context"]["transport"] = down
    with pytest.raises(InvalidCell, match="unavailable"):
        _admit(graph)


def test_the_state_read_takes_no_key_and_no_parameters(graph):
    answer = graph["host"].dispatch(
        {"method": "GET", "path": "/api/universal/workspace-roots-state", "body": {}})
    assert set(answer) == {"graph_id", "revision", "registry_digest", "account"}
    assert answer["registry_digest"] == roots.verified_graph_state()["registry_digest"]


def test_the_issuer_and_the_owner_share_one_digest_schema():
    body = roots.snapshot_body((), None)
    assert roots.registry_digest(body) == graph_digest(body)


def test_the_default_context_reaches_the_coordination_service_with_no_fallback():
    assert roots._default_graph_context.__module__ == roots.__name__
    assert roots.COORDINATION_ENDPOINT == "http://127.0.0.1:8474/coordination"
    assert set(roots._default_graph_context()) == {"transport", "settings_transport"}
