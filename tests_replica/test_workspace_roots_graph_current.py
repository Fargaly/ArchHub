"""The permit issuer asks the canonical instance whether the registry files are its
CURRENT projection. A real clean runtime and a real CleanCoordinationHost: the
request is signed with the issuer's own caller key, carries a fresh nonce, and the
answer is a statement the instance signs with its authority key for exactly that
request. The hooks' files are written by owner_change with a court key; revoking a
root in the graph leaves them stale but still valid (with a matching last-good).
No court here reaches the live service or the live key rings.
"""
from __future__ import annotations

import base64
import threading
import uuid

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_coordination_host import (
    CleanCoordinationHost,
    CoordinationIdentity,
    SignedCoordinationRequest,
    sign_coordination_request,
)
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.universal_cell import InvalidCell
from tests_replica.test_clean_server_admission import _provision_clean_runtime
from tests_replica.test_workspace_root_write_admission import _Store, graph_digest
from tests_replica.test_workspace_roots_catalogue import _Key


@pytest.fixture()
def graph(tmp_path, monkeypatch):
    built, provider = _provision_clean_runtime(tmp_path, root_name="graph-current")
    authority = built.location.authority
    keys = WindowsDpapiCallerKeyStore(tmp_path / "graph-current" / "callers.dpapi.json")
    host = CleanCoordinationHost(authority, keys)
    answers = []

    def transport(payload):
        answer = host.dispatch(SignedCoordinationRequest.from_payload(payload))
        answers.append(answer)
        return answer
    instance = roots.CanonicalInstance(authority.manifest.graph_id, authority.manifest.key_id,
                                       authority.manifest.key_version,
                                       authority.manifest.key_fingerprint)
    context = {"transport": transport, "key_store": keys, "provider": provider, "instance": instance}
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
    return {"built": built, "authority": authority, "host": host, "keys": keys, "key": key,
            "files": files, "last_good": last_good, "catalogue": catalogue, "context": context,
            "answers": answers, "provider": provider}


def _admit(graph):
    return roots.root_bound_registration("workspace-roots/client-a/a.md", runtime="claude",
                                         verifier=_Store(graph["key"]),
                                         last_good_path=graph["last_good"], **graph["files"])


def test_an_unchanged_registration_is_admitted_and_the_read_commits_and_binds_nothing(graph):
    before = graph["authority"].store.revision
    container, _digest, entry = _admit(graph)
    assert container == "workspace-root:client-a" and entry["writers"] == ["claude"]
    statement = graph["answers"][-1]["statement"]
    assert statement["graph_id"] == graph["authority"].manifest.graph_id
    assert graph["authority"].store.revision == before, "the state read committed"
    assert graph["host"]._bindings == {}, "the state read created an agent binding"


def test_a_root_the_graph_revoked_is_refused_while_the_old_files_and_last_good_still_verify(graph):
    assert _admit(graph)
    roots.unregister_root(graph["authority"], graph["catalogue"], "client-a",
                          caller=graph["built"].caller, operation_id=str(uuid.uuid4()))
    with pytest.raises(InvalidCell, match="not the graph's current projection"):
        _admit(graph)


def test_a_statement_from_another_instance_is_refused(graph):
    held = graph["context"]["instance"]
    graph["context"]["instance"] = roots.CanonicalInstance(
        "00000000-0000-4000-8000-000000000000", held.key_id, held.key_version, held.key_fingerprint)
    with pytest.raises(InvalidCell, match="not this instance's answer"):
        _admit(graph)


def test_a_statement_under_another_key_is_refused(graph):
    held = graph["context"]["instance"]
    graph["context"]["provider"] = MemorySigningKeyProvider(held.key_id, b"x" * 33)
    with pytest.raises(InvalidCell, match="canonical instance"):
        _admit(graph)


def test_a_replayed_answer_is_refused(graph):
    assert _admit(graph)
    recorded = graph["answers"][-1]
    graph["context"]["transport"] = lambda payload: recorded  # an old, validly signed answer
    with pytest.raises(InvalidCell, match="not this instance's answer"):
        _admit(graph)


def test_an_unavailable_owner_is_refused(graph):
    def down(payload):
        raise ConnectionRefusedError("127.0.0.1:8474")
    graph["context"]["transport"] = down
    with pytest.raises(InvalidCell, match="unavailable"):
        _admit(graph)


def test_the_issuer_key_reads_only_the_state_and_no_other_key_reads_it(graph):
    issuer = CoordinationIdentity(*roots.ISSUER_IDENTITY)
    with pytest.raises(InvalidCell, match="not admitted for this key"):
        graph["host"].dispatch(sign_coordination_request(graph["keys"], issuer, "list_agents", {}))
    other = CoordinationIdentity("codex", "court-other-session")
    with pytest.raises(InvalidCell, match="not admitted for this key"):
        graph["host"].dispatch(sign_coordination_request(
            graph["keys"], other, "workspace_roots_state", {"nonce": "0" * 32}))
    assert graph["host"]._bindings == {}


def test_a_forged_or_malformed_state_request_is_refused(graph):
    issuer = CoordinationIdentity(*roots.ISSUER_IDENTITY)
    request = sign_coordination_request(graph["keys"], issuer, "workspace_roots_state", {"nonce": "a" * 32})
    forged = SignedCoordinationRequest(request.version, request.request_id, request.identity,
                                       request.key_id, request.method, request.parameters,
                                       base64.b64encode(b"\0" * 64).decode("ascii"))
    with pytest.raises(InvalidCell, match="signature"):
        graph["host"].dispatch(forged)
    for parameters in ({}, {"nonce": "short"}, {"nonce": "a" * 32, "root": "client-a"}):
        with pytest.raises(InvalidCell, match="fresh nonce"):
            graph["host"].dispatch(sign_coordination_request(graph["keys"], issuer,
                                                             "workspace_roots_state", parameters))


def test_the_issuer_and_the_owner_share_one_digest_schema():
    body = roots.snapshot_body((), None)
    assert roots.registry_digest(body) == graph_digest(body)


def test_the_default_context_reaches_the_coordination_service_with_no_fallback():
    assert roots._default_graph_context.__module__ == roots.__name__
    assert roots.COORDINATION_ENDPOINT == "http://127.0.0.1:8474/coordination"
