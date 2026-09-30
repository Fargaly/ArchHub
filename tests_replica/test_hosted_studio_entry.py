"""Court: the hosted Studio is the application's own /studio, entered by one-use handoff.

Plan B, D6 (a1): the single production authority is the installed application,
so a browser the founder hands off to is the application's own Studio and its
Workshop reads and sends are exactly the desktop's. The handoff is the existing
machine route (the observed Desktop launch only); the Studio is the existing
/studio route; the send is the existing browser Workshop send. This court holds
that path end to end on one fresh owner, and every refusal to zero writes: the
graph revision, the Workshop content rows and the handoff pool are unchanged.

The verified dispatch wrapper stands for authenticated local transport, whose
signatures have their own courts. HTTP handlers run in memory; no installed
state, pipe, provider, key vault, browser or background worker is used.
"""
from email.message import Message
from io import BytesIO
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.conversation_content import prepare_empty_content_binding
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.universal_application import (
    provision_universal_view_session, set_universal_scope,
)
from nodelang.universal_cell import Cell, NULL_CELL_ID
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


def _handoff_request(**overrides):
    return {"runtime_id": "hosted-studio-fixture", "request_id": uuid4().hex,
            "method": "POST", "path": "/api/universal/browser-handoff",
            "body": {}, "session": {}, **overrides}


def _http(server, method, path, *, body=None, cookie=None, csrf=None, host=None):
    handler = object.__new__(server.httpd.RequestHandlerClass)
    handler.server = server.httpd
    handler.path, handler.command = path, method
    handler.request_version = "HTTP/1.1"
    handler.requestline = "%s %s HTTP/1.1" % (method, path)
    handler.headers = Message()
    handler.headers["Host"] = host or urlsplit(server.public_url).netloc
    raw = b"" if body is None else json.dumps(body).encode("utf-8")
    if body is not None:
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = str(len(raw))
    if cookie is not None:
        handler.headers["Cookie"] = "ArchHub-Session=" + cookie
    if csrf is not None:
        handler.headers["X-ArchHub-CSRF"] = csrf
    handler.rfile, handler.wfile = BytesIO(raw), BytesIO()
    (handler.do_POST if method == "POST" else handler.do_GET)()
    head, payload = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    return int(head.split(b" ", 2)[1]), head, payload


def _json(response):
    status, _head, payload = response
    return status, json.loads(payload.decode("utf-8"))


def _refused(response, status, error):
    """A refusal is only evidence when it is refused for the named reason."""
    assert response[0] == status, response[2][:120]
    assert _json(response) == (status, {"ok": False, "error": error})


def _cookie(head):
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"set-cookie: archhub-session="):
            return line.split(b"=", 1)[1].split(b";", 1)[0].decode("ascii")
    return None


def _boot(page):
    marker = b'"csrf": "'
    start = page.index(marker) + len(marker)
    return page[start:page.index(b'"', start)].decode("ascii")


def _owner(tmp_path, monkeypatch):
    from nodelang import application_machine_transport as transport
    from nodelang import application_server as app
    root = Path(transport.__file__).resolve().parents[1]
    peer = transport.MachinePipePeer(12345, 100.0, str(Path(sys.executable).resolve()),
        (sys.executable, str(root / "launch_archhub_test.py")), str(root))
    monkeypatch.setattr(transport, "_observe_machine_process",
                        lambda pid: peer if pid == peer.pid else None)
    monkeypatch.setattr(app, "_verified_machine_pipe_peer", lambda request: peer)
    content = tmp_path / "content.sqlite3"
    server = ApplicationServer(universal_workspace_root=tmp_path,
        conversation_history_path=content,
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False)
    store, registry = server.universal_store, server.universal_registry
    prepared = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
        application_root=registry.application_root, space_root=registry.workshop_root)
    with ConversationHistoryStore(content, instance_id=prepared.binding.instance_id) as history:
        history.ensure_conversation(registry.workshop_root)
    store.commit(prepared.expected_revision, create=prepared.create, replace=prepared.replace)
    founder = server._resolve_browser_session(server.browser_session_token)
    with server.mutation_lock:
        set_universal_scope(store, registry, registry.map.domains["brain"],
            authentication_context=founder.context)
        set_universal_scope(store, registry, registry.workshop_workbench_root,
            authentication_context=founder.context)
    # One enrolled agent: the Workshop participant a founder note is addressed to.
    server.fixture_agent_root = server._enroll_universal_machine_agent_session(
        {"runtime": "codex", "external_session_id": "hosted-studio-agent"},
        runtime_id="a" * 32)["agent_session"]
    server.fixture_content_path = content
    return server


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    server = _owner(tmp_path, monkeypatch)
    try:
        yield server
    finally:
        server.close()


def _writes(server):
    """Everything a refused hosted request could have written."""
    database = sqlite3.connect("file:%s?mode=ro" % server.fixture_content_path.as_posix(), uri=True)
    try:
        rows = database.execute("SELECT count(*) FROM messages").fetchone()[0]
    finally:
        database.close()
    return (server.universal_store.revision, rows, len(server._browser_handoff_tokens),
            server.browser_bootstrap_token)


def _workshop_query(server):
    registry = server.universal_registry
    return "/api/universal/workshop?" + urlencode(
        {"root": registry.workshop_root, "scope": registry.workshop_workbench_root})


def _send(server, text, **overrides):
    registry = server.universal_registry
    body = {"root": registry.workshop_root, "scope": registry.workshop_workbench_root,
            "category": "note", "text": text, "refs": [], "evidence": [],
            "recipients": [server.fixture_agent_root],
            "reply_to": None, "idempotency_key": "hosted-" + uuid4().hex, "created_at": None}
    body.update(overrides)
    return body


def _enter(server):
    """The hosted entry: one handoff, one GET of its Studio URL, the cookie it sets."""
    handoff = server._dispatch_verified_machine_route(_handoff_request())
    return handoff, _http(server, "GET", urlsplit(handoff["studio_url"]).path + "?"
                          + urlsplit(handoff["studio_url"]).query)


def test_the_hosted_entry_is_a_one_use_handoff_into_the_apps_own_studio(hosted):
    server = hosted
    before = server.universal_store.revision
    handoff, (status, head, page) = _enter(server)
    studio = urlsplit(handoff["studio_url"])
    token = parse_qs(studio.query)["bootstrap"][0]
    assert (studio.scheme, studio.netloc, studio.path) == ("http", urlsplit(server.public_url).netloc, "/studio")
    assert parse_qs(urlsplit(handoff["document_url"]).query)["bootstrap"][0] == token
    assert handoff["one_use"] is True and handoff["session_root"] == server.browser_session_root
    # The Studio page itself, booted with the application's own session and CSRF.
    assert status == 200 and b"<html" in page.lower()
    cookie = _cookie(head)
    assert cookie == server.browser_session_token
    csrf = _boot(page)
    assert csrf == server.browser_csrf_token
    assert server.universal_store.revision == before
    # One use: the same URL, without the cookie, is refused and writes nothing.
    held = _writes(server)
    _refused(_http(server, "GET", studio.path + "?" + studio.query),
        403, "desktop bootstrap is required")
    assert _writes(server) == held
    # The entered browser reads and sends the desktop's Workshop: conversation content.
    status, transcript = _json(_http(server, "GET", _workshop_query(server), cookie=cookie))
    assert status == 200, transcript
    assert transcript["storage"] == "conversation-content" and transcript["can_send"] is True
    status, sent = _json(_http(server, "POST", "/api/universal/workshop",
        body=_send(server, "Hosted Studio note"), cookie=cookie, csrf=csrf))
    assert status == 200, sent
    assert sent["storage"] == "conversation-content"
    revision, rows, _, _ = _writes(server)
    assert revision == before and rows == held[1] + 1
    status, transcript = _json(_http(server, "GET", _workshop_query(server), cookie=cookie))
    assert status == 200 and "Hosted Studio note" in json.dumps(transcript)


def test_an_expired_handoff_enters_nothing(hosted, monkeypatch):
    from nodelang import application_server as app
    server = hosted
    handoff = server._dispatch_verified_machine_route(_handoff_request())
    clock = app.time.monotonic() + app._BROWSER_HANDOFF_SECONDS + 1
    monkeypatch.setattr(app.time, "monotonic", lambda: clock)
    held = _writes(server)
    studio = urlsplit(handoff["studio_url"])
    refused = _http(server, "GET", studio.path + "?" + studio.query)
    _refused(refused, 403, "desktop bootstrap is required")
    assert _cookie(refused[1]) is None
    revision, rows, pool, startup = _writes(server)
    assert (revision, rows, startup) == (held[0], held[1], held[3]) and pool == 0


@pytest.mark.parametrize("csrf", ["missing", "stale", "forged"])
def test_the_hosted_send_enforces_csrf_with_zero_writes(hosted, csrf):
    server = hosted
    _handoff, (status, head, _page) = _enter(server)
    assert status == 200
    cookie = _cookie(head)
    presented = {"missing": None,
                 "stale": server.issue_browser_session(
                     server.universal_registry.authorization.session.context())[1],
                 "forged": "f" * 43}[csrf]
    held = _writes(server)
    _refused(_http(server, "POST", "/api/universal/workshop",
        body=_send(server, "No CSRF, no note"), cookie=cookie, csrf=presented),
        403, "browser CSRF digest drifted")
    assert _writes(server) == held


def _member(server):
    store, registry = server.universal_store, server.universal_registry
    member_root = "hosted-fixture:member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Member browser"),))
    provision_universal_view_session(store, registry, member_root,
        visible_roots=(registry.visible_roots[0],))
    authority = registry.authorization
    context = authority.broker.mint_authenticated_context(member_root,
        tenant_root=authority.tenant_root, assurance_root=authority.assurance_root,
        lifetime_seconds=120)
    token, csrf = server.issue_browser_session(context)
    return member_root, token, csrf


def test_a_non_founder_neither_enters_nor_sends_with_zero_writes(hosted):
    server = hosted
    member_root, token, csrf = _member(server)
    held = _writes(server)
    # The member's own browser session reaches neither the founder's Workshop view nor its send.
    _refused(_http(server, "GET", _workshop_query(server), cookie=token),
        403, "authorization denied: default-deny")
    _refused(_http(server, "POST", "/api/universal/workshop",
        body=_send(server, "Member note"), cookie=token, csrf=csrf),
        403, "authorization denied: default-deny")
    # A caller that is not the founder's observed Desktop launch cannot mint the entry.
    with pytest.raises(AuthorizationDenied, match="runtime Agent Session is unknown"):
        server._dispatch_verified_machine_route(_handoff_request(
            session={"root": member_root, "proof": "not-the-desktop"}))
    assert _writes(server) == held


def test_a_wrong_instance_or_scope_is_refused_with_zero_writes(hosted, tmp_path, monkeypatch):
    server = hosted
    (tmp_path / "other-instance").mkdir()
    other = _owner(tmp_path / "other-instance", monkeypatch)
    try:
        _handoff, (status, head, _page) = _enter(server)
        cookie, csrf = _cookie(head), server.browser_csrf_token
        foreign = other._dispatch_verified_machine_route(_handoff_request())
        held, held_other = _writes(server), _writes(other)
        # The other instance's one-use entry does not open this instance's Studio,
        foreign_url = urlsplit(foreign["studio_url"])
        refused = _http(server, "GET", foreign_url.path + "?" + foreign_url.query)
        _refused(refused, 403, "desktop bootstrap is required")
        assert _cookie(refused[1]) is None
        # and this instance's session is nothing to the other instance.
        _refused(_http(other, "GET", _workshop_query(other), cookie=cookie),
            403, "browser session is unknown")
        _refused(_http(other, "POST", "/api/universal/workshop",
            body=_send(other, "Wrong instance"), cookie=cookie, csrf=csrf),
            403, "browser session is unknown")
        # A Workshop outside the current canvas scope is refused.
        registry = server.universal_registry
        _refused(_http(server, "POST", "/api/universal/workshop",
            body=_send(server, "Wrong scope", scope=registry.map.domains["brain"]),
            cookie=cookie, csrf=csrf), 403, "Workshop scope changed; refresh the canvas")
        _refused(_http(server, "GET", "/api/universal/workshop?" + urlencode(
            {"root": registry.workshop_root, "scope": registry.map.domains["brain"]}),
            cookie=cookie), 403, "Workshop scope changed; refresh the canvas")
        assert _writes(server) == held
        assert _writes(other)[:2] == held_other[:2]
    finally:
        other.close()


def test_identity_substitution_is_refused_with_zero_writes(hosted):
    server = hosted
    member_root, member_token, member_csrf = _member(server)
    _handoff, (status, head, _page) = _enter(server)
    cookie, csrf = _cookie(head), server.browser_csrf_token
    held = _writes(server)
    # The send carries no author: naming one, the founder's or another's, is refused.
    for field, value in (("actor", member_root), ("actor", server.browser_session_root),
                         ("sender", member_root)):
        _refused(_http(server, "POST", "/api/universal/workshop",
            body=_send(server, "Substituted author", **{field: value}), cookie=cookie, csrf=csrf),
            400, "Workshop message fields are invalid")
    # One session's CSRF never admits another session's cookie, in either direction.
    _refused(_http(server, "POST", "/api/universal/workshop",
        body=_send(server, "Member CSRF on founder cookie"), cookie=cookie, csrf=member_csrf),
        403, "browser CSRF digest drifted")
    _refused(_http(server, "POST", "/api/universal/workshop",
        body=_send(server, "Founder CSRF on member cookie"), cookie=member_token, csrf=csrf),
        403, "browser CSRF digest drifted")
    assert _writes(server) == held
