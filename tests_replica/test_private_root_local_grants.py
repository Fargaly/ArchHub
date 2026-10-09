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


def test_private_root_non_writer_runtime_is_refused_even_with_local_grant(tmp_path, monkeypatch):
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
    with pytest.raises(AuthorizationDenied, match="not a writer"):
        authorize_universal_cde_write(
            store,
            object(),
            agent_session_root=SESSION,
            operation="write_file",
            path=PATH,
            runtime="codex",
            private_root_grants=grant_store,
        )


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
