from __future__ import annotations

import threading
import time

import pytest

from nodelang import universal_application as universal_application_module
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_application import AuthorizationDenied, authorize_universal_cde_write
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID


SESSION = "app:agent-session:runtime:private-grant-court"
PATH = "workspace-roots/bbc4/drawings/a.dwg"
REGISTRATION = {
    "id": "bbc4",
    "path": r"E:\synthetic\BBC4",
    "privacy": "private",
    "profile": "client",
    "writers": ["claude"],
    "identity": [1, 2],
}


def _grant_store(tmp_path, *, session=SESSION, runtime="claude", root_digest="a" * 64,
                 operations=("write_file",), expires_at=None, now=None):
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = MemorySigningKeyProvider("private-root-grant-court", b"g" * 32)
    store = PrivateRootGrantStore(
        tmp_path / "private-root-grants.json",
        provider=provider,
        key_id="private-root-grant-court",
    )
    store.grant(
        root_id="bbc4",
        runtime=runtime,
        session_id=session,
        root_digest=root_digest,
        operations=operations,
        expires_at=expires_at or time.time() + 3600,
        now=now,
    )
    return store


def test_local_private_root_grant_is_signed_and_fail_closed(tmp_path):
    store = _grant_store(tmp_path)
    assert store.status(
        root_id="bbc4", runtime="claude", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )["granted"] is True

    raw = (tmp_path / "private-root-grants.json").read_text(encoding="utf-8")
    (tmp_path / "private-root-grants.json").write_text(
        raw.replace('"runtime":"claude"', '"runtime":"codex"'), encoding="utf-8")
    assert store.status(
        root_id="bbc4", runtime="codex", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )["granted"] is False


def test_private_root_grant_status_refuses_wrong_runtime_revoked_and_expired(tmp_path):
    store = _grant_store(tmp_path, operations=("write_file", "apply_patch"))
    assert store.status(
        root_id="bbc4", runtime="codex", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )["granted"] is False

    store.revoke(root_id="bbc4", runtime="claude", session_id=SESSION)
    revoked = store.status(
        root_id="bbc4", runtime="claude", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )
    assert revoked["granted"] is False and revoked["reason"] == "grant revoked"

    issued_at = time.time() - 3600
    expired = _grant_store(tmp_path / "expired", expires_at=time.time() - 1, now=issued_at)
    status = expired.status(
        root_id="bbc4", runtime="claude", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )
    assert status["granted"] is False and status["reason"] == "grant expired"


def test_private_root_grant_refuses_unknown_operation(tmp_path):
    with pytest.raises(InvalidCell, match="operations"):
        _grant_store(tmp_path, operations=("write_file", "unknown-admin-op"))


def test_private_root_grant_status_is_sanitized(tmp_path):
    store = _grant_store(tmp_path)
    status = store.status(
        root_id="bbc4", runtime="claude", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )
    assert status == {"granted": True, "until": status["until"]}
    assert "grant" not in status


def test_concurrent_revoke_wins_over_overlapping_grant(tmp_path):
    store = _grant_store(tmp_path)
    original_read = store._read
    grant_read = threading.Event()

    def slow_grant_read():
        body = original_read()
        if threading.current_thread().name == "overlapping-grant":
            grant_read.set()
            time.sleep(0.2)
        return body

    store._read = slow_grant_read

    grant_thread = threading.Thread(
        name="overlapping-grant",
        target=lambda: store.grant(
            root_id="bbc4",
            runtime="claude",
            session_id=SESSION,
            root_digest="a" * 64,
            operations=("write_file",),
            expires_at=time.time() + 3600,
        ),
    )
    grant_thread.start()
    assert grant_read.wait(2)
    revoke_thread = threading.Thread(
        name="overlapping-revoke",
        target=lambda: store.revoke(root_id="bbc4", runtime="claude", session_id=SESSION),
    )
    revoke_thread.start()
    grant_thread.join(2)
    revoke_thread.join(2)

    status = store.status(
        root_id="bbc4", runtime="claude", session_id=SESSION, operation="write_file",
        root_digest="a" * 64,
    )
    assert status["granted"] is False and status["reason"] == "grant revoked"


@pytest.fixture()
def admission_world(tmp_path, monkeypatch):
    store = CellStore()
    store.commit(
        store.revision,
        create=(Cell(SESSION, NULL_CELL_ID, NULL_CELL_ID, b"session"),),
    )
    registry = object()
    calls = []
    grant_store = _grant_store(tmp_path)

    monkeypatch.setattr(
        universal_application_module,
        "read_universal_current_claimed_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Workshop Work was read")),
    )
    monkeypatch.setattr(
        universal_application_module,
        "_require_workshop_execution_gate",
        lambda *_args, **_kwargs: calls.append("workshop"),
    )
    monkeypatch.setattr(
        "nodelang.workspace_roots_catalogue.root_bound_registration",
        lambda path, runtime=None: ("workspace-root:bbc4", "a" * 64, dict(REGISTRATION)),
    )
    return store, registry, grant_store, calls


def test_private_root_writer_with_local_grant_needs_no_workshop_work(admission_world):
    store, registry, grant_store, calls = admission_world
    admission = authorize_universal_cde_write(
        store,
        registry,
        agent_session_root=SESSION,
        operation="write_file",
        path=PATH,
        runtime="claude",
        private_root_grants=grant_store,
    )
    assert admission.work_root == SESSION
    assert admission.claim_binding_root == SESSION
    assert admission.container_id == "GM.nodes.private-root-grant"
    assert admission.root_registration["id"] == "bbc4"
    assert calls == []


def test_private_root_non_writer_runtime_is_admitted_with_local_grant(tmp_path, monkeypatch):
    store = CellStore()
    store.commit(
        store.revision,
        create=(Cell(SESSION, NULL_CELL_ID, NULL_CELL_ID, b"session"),),
    )
    grant_store = _grant_store(tmp_path, runtime="codex")
    monkeypatch.setattr(
        "nodelang.workspace_roots_catalogue.root_bound_registration",
        lambda path, runtime=None: ("workspace-root:bbc4", "a" * 64, dict(REGISTRATION)),
    )
    monkeypatch.setattr(
        universal_application_module,
        "read_universal_current_claimed_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Workshop Work was read")),
    )
    admission = authorize_universal_cde_write(
        store,
        object(),
        agent_session_root=SESSION,
        operation="write_file",
        path=PATH,
        runtime="codex",
        private_root_grants=grant_store,
    )
    assert admission.container_id == "GM.nodes.private-root-grant"


def test_public_root_still_needs_workshop_work(tmp_path, monkeypatch):
    grant_store = _grant_store(tmp_path)
    public_registration = {**REGISTRATION, "privacy": "public"}
    monkeypatch.setattr(
        "nodelang.workspace_roots_catalogue.root_bound_registration",
        lambda path, runtime=None: ("workspace-root:bbc4", "a" * 64, public_registration),
    )
    monkeypatch.setattr(
        universal_application_module,
        "read_universal_current_claimed_work",
        lambda *_args, **_kwargs: (None, 1),
    )
    with pytest.raises(Exception, match="claimed governed Work|Workshop Work"):
        authorize_universal_cde_write(
            CellStore(),
            object(),
            agent_session_root=SESSION,
            operation="write_file",
            path=PATH,
            runtime="claude",
            private_root_grants=grant_store,
        )


def _legacy_signed_store(tmp_path, *, forge=False):
    """A grant written by an earlier build under the retired key id archhub.unified.bootstrap."""
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = MemorySigningKeyProvider("archhub.unified.bootstrap", b"u" * 32)
    provider.add_key("archhub.local.private-root-grants", b"l" * 32)
    legacy = PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider,
                                   key_id="archhub.unified.bootstrap")
    legacy.grant(root_id="bbc4", runtime="claude", session_id=SESSION, root_digest="a" * 64,
                 operations=("write_file",), expires_at=time.time() + 3600)
    if forge:
        import json
        document = json.loads((tmp_path / "private-root-grants.json").read_text(encoding="utf-8"))
        document["grants"][0]["runtime"] = "codex"
        (tmp_path / "private-root-grants.json").write_text(json.dumps(document), encoding="utf-8")
    return provider


def test_a_grant_signed_under_the_retired_key_id_is_verified_and_resigned(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore
    import json

    provider = _legacy_signed_store(tmp_path)
    current = PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider)
    result = current.status(root_id="bbc4", runtime="claude", session_id=SESSION,
                            operation="write_file", root_digest="a" * 64)
    assert result["granted"] is True, result
    document = json.loads((tmp_path / "private-root-grants.json").read_text(encoding="utf-8"))
    assert document["key_id"] == "archhub.local.private-root-grants"
    assert len(document["grants"]) == 1


def test_a_tampered_retired_key_grant_is_still_refused(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = _legacy_signed_store(tmp_path, forge=True)
    current = PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider)
    result = current.status(root_id="bbc4", runtime="codex", session_id=SESSION,
                            operation="write_file", root_digest="a" * 64)
    assert result["granted"] is False

def _status(store, runtime="claude"):
    return store.status(root_id="bbc4", runtime=runtime, session_id=SESSION,
                        operation="write_file", root_digest="a" * 64)


def test_a_retired_key_grant_is_preserved_unchanged_by_the_migration(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore
    import json

    provider = _legacy_signed_store(tmp_path)
    path = tmp_path / "private-root-grants.json"
    before = json.loads(path.read_text(encoding="utf-8"))["grants"]
    _status(PrivateRootGrantStore(path, provider=provider))
    assert json.loads(path.read_text(encoding="utf-8"))["grants"] == before


def test_revoke_on_retired_key_state_takes_one_lock_and_revokes(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = _legacy_signed_store(tmp_path)
    current = PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider)
    assert current.revoke(root_id="bbc4") == 1
    assert _status(current) == {"granted": False, "reason": "grant revoked"}


def test_grant_on_retired_key_state_takes_one_lock_and_keeps_old_grants(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = _legacy_signed_store(tmp_path)
    current = PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider)
    current.grant(root_id="other", runtime="claude", session_id=SESSION, root_digest="b" * 64,
                  operations=("write_file",), expires_at=time.time() + 3600)
    assert {g["root_id"] for g in current.list()} == {"bbc4", "other"}
    assert _status(current)["granted"] is True


def test_a_revoke_after_a_stale_retired_read_is_never_overwritten(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = _legacy_signed_store(tmp_path)
    path = tmp_path / "private-root-grants.json"
    reader = PrivateRootGrantStore(path, provider=provider)
    writer = PrivateRootGrantStore(path, provider=provider)
    _, retired = reader._load()          # unlocked read sees the retired document
    assert retired is True
    assert writer.revoke(root_id="bbc4") == 1   # another holder revokes in between
    reader._migrate_retired()            # migration decides again under the lock
    assert _status(reader) == {"granted": False, "reason": "grant revoked"}


BBC4_SESSION = "app:agent-session:runtime:bbc4-court"


def _unverifiable_store(tmp_path):
    """The live failure class: a document signed by a key no ring on this machine holds."""
    from nodelang.private_root_grants import PrivateRootGrantStore

    lost = MemorySigningKeyProvider("archhub.unified.bootstrap", b"x" * 32)
    PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=lost,
                          key_id="archhub.unified.bootstrap").grant(
        root_id="client-a", runtime="claude", session_id=SESSION, root_digest="a" * 64,
        operations=("write_file",), expires_at=time.time() + 3600)
    provider = MemorySigningKeyProvider("archhub.unified.bootstrap", b"u" * 32)
    provider.add_key("archhub.local.private-root-grants", b"l" * 32)
    return PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider)


def _bbc4_grant(store, **extra):
    return store.grant(root_id="01-personal", runtime="codex", session_id=BBC4_SESSION,
                       root_digest="b" * 64, operations=("write_file",),
                       expires_at=time.time() + 3600, **extra)


def _bbc4_status(store, session=BBC4_SESSION):
    return store.status(root_id="01-personal", runtime="codex", session_id=session,
                        operation="write_file", root_digest="b" * 64)


def _set_aside(tmp_path):
    return [p for p in tmp_path.iterdir() if ".unverifiable-" in p.name]


def test_an_unverifiable_document_refuses_reads_and_ordinary_grants_without_moving(tmp_path):
    from nodelang.universal_cell import InvalidCell
    import hashlib

    store = _unverifiable_store(tmp_path)
    path = tmp_path / "private-root-grants.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert _bbc4_status(store)["granted"] is False
    with pytest.raises(InvalidCell, match="not pinned"):
        _bbc4_grant(store)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not _set_aside(tmp_path)


def test_a_settings_grant_sets_the_unverifiable_document_aside_and_trusts_none_of_it(tmp_path):
    store = _unverifiable_store(tmp_path)
    before = (tmp_path / "private-root-grants.json").read_bytes()
    _bbc4_grant(store, replace_unverifiable=True)
    archived = _set_aside(tmp_path)
    assert len(archived) == 1 and archived[0].read_bytes() == before
    assert [(g["root_id"], g["runtime"], g["session_id"]) for g in store.list()] == [
        ("01-personal", "codex", BBC4_SESSION)]
    assert _bbc4_status(store)["granted"] is True
    assert _bbc4_status(store, session="app:agent-session:runtime:other")["granted"] is False
    assert _status(store)["granted"] is False   # the old client-a/claude entry is not trusted


def test_a_verifiable_document_is_never_set_aside(tmp_path):
    from nodelang.private_root_grants import PrivateRootGrantStore

    provider = MemorySigningKeyProvider("archhub.local.private-root-grants", b"l" * 32)
    store = PrivateRootGrantStore(tmp_path / "private-root-grants.json", provider=provider)
    store.grant(root_id="other", runtime="claude", session_id=SESSION, root_digest="c" * 64,
                operations=("write_file",), expires_at=time.time() + 3600)
    _bbc4_grant(store, replace_unverifiable=True)
    assert not _set_aside(tmp_path)
    assert {g["root_id"] for g in store.list()} == {"other", "01-personal"}


def test_a_failed_signature_leaves_the_unverifiable_document_in_place(tmp_path, monkeypatch):
    store = _unverifiable_store(tmp_path)
    path = tmp_path / "private-root-grants.json"
    before = path.read_bytes()

    def refuse(*_args, **_kwargs):
        raise RuntimeError("signing unavailable")

    monkeypatch.setattr(store.provider, "sign", refuse)
    with pytest.raises(RuntimeError):
        _bbc4_grant(store, replace_unverifiable=True)
    assert path.read_bytes() == before
    assert not _set_aside(tmp_path)


def test_settings_grants_after_set_aside_keep_each_other_and_revoke_wins(tmp_path):
    store = _unverifiable_store(tmp_path)
    _bbc4_grant(store, replace_unverifiable=True)
    store.grant(root_id="01-personal", runtime="claude", session_id=SESSION, root_digest="b" * 64,
                operations=("write_file",), expires_at=time.time() + 3600, replace_unverifiable=True)
    assert len(_set_aside(tmp_path)) == 1
    assert {g["runtime"] for g in store.list()} == {"codex", "claude"}
    assert store.revoke(root_id="01-personal", runtime="codex") == 1
    assert _bbc4_status(store) == {"granted": False, "reason": "grant revoked"}
