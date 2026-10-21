"""Courts for graph-governed browser sessions with protected credentials."""
import hashlib

import pytest

from nodelang.cell_browser_sessions import (
    BrowserSessionDenied,
    bootstrap_browser_session_protocol,
    issue_browser_session,
    list_browser_session_roots,
    project_browser_session_protocol,
    read_browser_session,
    revoke_browser_session,
    verify_browser_session,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _authority_roots(store):
    roots = {
        "subject": "test:browser-session:subject",
        "view": "test:browser-session:view",
        "tenant": "test:browser-session:tenant",
        "assurance": "test:browser-session:assurance",
    }
    store.commit(
        store.revision,
        create=tuple(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8"))
            for name, root in roots.items()
        ),
    )
    return roots


def _issue(store, protocol, roots, *, now=1000.0, lifetime=120.0):
    token = "opaque-browser-token"
    csrf = "opaque-csrf-token"
    session_root, revision = issue_browser_session(
        store,
        protocol,
        subject_root=roots["subject"],
        view_root=roots["view"],
        tenant_root=roots["tenant"],
        assurance_root=roots["assurance"],
        token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        csrf_digest=hashlib.sha256(csrf.encode("utf-8")).hexdigest(),
        issued_at=now,
        lifetime_seconds=lifetime,
    )
    return session_root, revision, token, csrf


def test_browser_session_is_one_relation_vocabulary_and_one_atomic_issue():
    store = CellStore()
    protocol = bootstrap_browser_session_protocol(store)
    roots = _authority_roots(store)
    before = store.revision

    session_root, revision, token, csrf = _issue(store, protocol, roots)

    assert revision == before + 1 == store.revision
    assert project_browser_session_protocol(store.snapshot()) == protocol
    session = read_browser_session(store.snapshot(), protocol, session_root)
    assert session.subject_root == roots["subject"]
    assert session.view_root == roots["view"]
    assert session.tenant_root == roots["tenant"]
    assert session.assurance_root == roots["assurance"]
    assert session.state_root == protocol.states["active"]
    assert list_browser_session_roots(store.snapshot(), protocol) == (
        session_root,
    )
    verified = verify_browser_session(
        store.snapshot(),
        protocol,
        session_root,
        token=token,
        csrf_token=csrf,
        require_csrf=True,
        now=1001.0,
    )
    assert verified == session

    graph_bytes = b"\n".join(cell.atom for cell in store.snapshot().cells.values())
    assert token.encode("utf-8") not in graph_bytes
    assert csrf.encode("utf-8") not in graph_bytes
    assert hashlib.sha256(token.encode("utf-8")).hexdigest().encode() in graph_bytes
    assert hashlib.sha256(csrf.encode("utf-8")).hexdigest().encode() in graph_bytes


def test_browser_session_denies_wrong_credentials_expiry_and_forgery():
    store = CellStore()
    protocol = bootstrap_browser_session_protocol(store)
    roots = _authority_roots(store)
    session_root, _, token, csrf = _issue(store, protocol, roots)

    with pytest.raises(BrowserSessionDenied, match="credential"):
        verify_browser_session(
            store.snapshot(), protocol, session_root, token="wrong", now=1001.0
        )
    with pytest.raises(BrowserSessionDenied, match="CSRF"):
        verify_browser_session(
            store.snapshot(),
            protocol,
            session_root,
            token=token,
            csrf_token="wrong",
            require_csrf=True,
            now=1001.0,
        )
    with pytest.raises(BrowserSessionDenied, match="expired"):
        verify_browser_session(
            store.snapshot(), protocol, session_root, token=token, now=1120.0
        )
    with pytest.raises(BrowserSessionDenied, match="registered"):
        verify_browser_session(
            store.snapshot(),
            protocol,
            "forged:browser-session",
            token=token,
            csrf_token=csrf,
            require_csrf=True,
            now=1001.0,
        )


def test_graph_revocation_is_atomic_visible_and_immediately_denied():
    store = CellStore()
    protocol = bootstrap_browser_session_protocol(store)
    roots = _authority_roots(store)
    session_root, _, token, csrf = _issue(store, protocol, roots)
    before = store.revision

    revision = revoke_browser_session(
        store, protocol, session_root, reason="User signed out"
    )

    assert revision == before + 1 == store.revision
    revoked = read_browser_session(store.snapshot(), protocol, session_root)
    assert revoked.state_root == protocol.states["revoked"]
    assert len(revoked.revocation_reason_roots) == 1
    reason_root = revoked.revocation_reason_roots[0]
    assert store.read(reason_root).atom == b"User signed out"
    with pytest.raises(BrowserSessionDenied, match="revoked"):
        verify_browser_session(
            store.snapshot(),
            protocol,
            session_root,
            token=token,
            csrf_token=csrf,
            require_csrf=True,
            now=1001.0,
        )
    assert revoke_browser_session(
        store, protocol, session_root, reason="duplicate close"
    ) == revision


def test_browser_session_rejects_invalid_digests_and_unbounded_lifetime():
    store = CellStore()
    protocol = bootstrap_browser_session_protocol(store)
    roots = _authority_roots(store)
    kwargs = dict(
        subject_root=roots["subject"],
        view_root=roots["view"],
        tenant_root=roots["tenant"],
        assurance_root=roots["assurance"],
        token_digest="0" * 64,
        csrf_digest="1" * 64,
    )
    with pytest.raises(ValueError, match="one hour"):
        issue_browser_session(
            store, protocol, lifetime_seconds=3601, **kwargs
        )
    with pytest.raises(InvalidCell, match="digest"):
        issue_browser_session(
            store,
            protocol,
            token_digest="not-a-digest",
            csrf_digest="1" * 64,
            subject_root=roots["subject"],
            view_root=roots["view"],
            tenant_root=roots["tenant"],
            assurance_root=roots["assurance"],
        )
