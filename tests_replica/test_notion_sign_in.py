"""Notion connects with Notion's own sign-in; nobody copies a token.

A fake Notion stands in for mcp.notion.com: dynamic client registration, the
browser consent (the test follows the authorize URL to the loopback callback
the way the browser would), the code-for-grant exchange, the MCP search call,
and an expired grant that is refreshed once.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request

from nodelang import host_brokers, notion_mcp


class _Response(io.BytesIO):
    def __init__(self, body, session=None):
        super().__init__(body.encode("utf-8"))
        self.headers = {"Mcp-Session-Id": session} if session else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNotion:
    def __init__(self):
        self.calls = []
        self.expired_once = False
        self.tool_error = False
        self.refresh_refused = False
        self.exchange_refused = False

    def __call__(self, request, timeout=None):
        url, body = request.full_url, request.data.decode("utf-8")
        auth = request.get_header("Authorization") or ""
        self.calls.append((url, body, auth))
        if url == notion_mcp.REGISTER_URL:
            assert json.loads(body)["token_endpoint_auth_method"] == "none"
            return _Response(json.dumps({"client_id": "client-1"}))
        if url == notion_mcp.TOKEN_URL:
            form = dict(urllib.parse.parse_qsl(body))
            if form["grant_type"] == "authorization_code" and self.exchange_refused:
                raise urllib.error.HTTPError(url, 400, "invalid_grant", {}, None)
            if form["grant_type"] == "refresh_token" and self.refresh_refused:
                raise urllib.error.HTTPError(url, 400, "invalid_grant", {}, None)
            if form["grant_type"] == "authorization_code":
                assert form["code"] == "code-1" and form["code_verifier"]
                return _Response(json.dumps({"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}))
            assert form == {"grant_type": "refresh_token", "refresh_token": "refresh-1", "client_id": "client-1"}
            return _Response(json.dumps({"access_token": "access-2", "expires_in": 3600}))
        assert url == notion_mcp.MCP_URL
        if self.expired_once and auth == "Bearer access-1":
            raise urllib.error.HTTPError(url, 401, "expired", {}, None)
        message = json.loads(body)
        if message.get("method") == "tools/call" and self.tool_error:
            # The real failed-tool shape: a result flagged isError with plain text, not a JSON-RPC error.
            return _Response(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
                "isError": True, "content": [{"type": "text", "text": "Notion access denied"}]}}))
        if message.get("method") == "tools/call":
            assert message["params"] == {"name": "notion-search", "arguments": {"query": "roadmap"}}
            payload = {"results": [{"id": "p1", "title": "Roadmap", "url": "https://notion.so/p1", "type": "page"}]}
            return _Response("event: message\ndata: " + json.dumps(
                {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}))
        return _Response(json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": {}}), session="s-1")


def _store():
    held = {}
    return held, held.get, held.__setitem__


def _browser_that_allows(url):
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert query["code_challenge_method"] == "S256" and query["client_id"] == "client-1"
    back = query["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "code-1", "state": query["state"]})
    urllib.request.urlopen(back, timeout=5).read()


def test_connect_signs_in_once_and_search_reads_notion_with_the_grant():
    notion, (held, load, save) = FakeNotion(), _store()
    assert notion_mcp.connect(timeout=10, open_browser=_browser_that_allows, opener=notion, load=load, save=save) == {"ok": True}
    grant = json.loads(held[notion_mcp.GRANT_KEY])
    assert (grant["client_id"], grant["access_token"], grant["refresh_token"]) == ("client-1", "access-1", "refresh-1")
    rows = notion_mcp.search("roadmap", opener=notion, load=load, save=save)
    assert rows == [{"id": "p1", "title": "Roadmap", "url": "https://notion.so/p1", "object": "page"}]


def test_a_refused_consent_keeps_no_grant():
    notion, (held, load, save) = FakeNotion(), _store()

    def deny(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        urllib.request.urlopen(query["redirect_uri"] + "?" + urllib.parse.urlencode(
            {"error": "access_denied", "state": query["state"]}), timeout=5).read()

    answer = notion_mcp.connect(timeout=10, open_browser=deny, opener=notion, load=load, save=save)
    assert answer["ok"] is False and "access_denied" in answer["error"]
    assert notion_mcp.GRANT_KEY not in held


def test_an_expired_grant_is_refreshed_once_and_kept():
    notion, (held, load, save) = FakeNotion(), _store()
    notion_mcp.connect(timeout=10, open_browser=_browser_that_allows, opener=notion, load=load, save=save)
    notion.expired_once = True
    assert notion_mcp.search("roadmap", opener=notion, load=load, save=save)[0]["title"] == "Roadmap"
    assert json.loads(held[notion_mcp.GRANT_KEY])["access_token"] == "access-2"


def test_the_notion_host_asks_for_a_sign_in_not_a_token(monkeypatch):
    monkeypatch.setattr(host_brokers, "_notion_token", lambda: "")
    monkeypatch.setattr(notion_mcp, "connected", lambda load=None: False)
    out, label = host_brokers.notion_search({"query": "x"}, {})
    assert "notion.connect" in label and "token" not in label


def test_a_failed_tool_call_is_an_error_never_zero_results(monkeypatch):
    notion, (held, load, save) = FakeNotion(), _store()
    notion_mcp.connect(timeout=10, open_browser=_browser_that_allows, opener=notion, load=load, save=save)
    notion.tool_error = True
    try:
        notion_mcp.search("roadmap", opener=notion, load=load, save=save)
    except notion_mcp.NotionToolError as exc:
        assert "Notion access denied" in str(exc)
    else:
        raise AssertionError("a refused tool call read as results")
    monkeypatch.setattr(host_brokers, "_notion_token", lambda: "")
    monkeypatch.setattr(notion_mcp, "connected", lambda load=None: True)

    def refused(query, **kw):
        raise notion_mcp.NotionToolError("Notion access denied")

    monkeypatch.setattr(notion_mcp, "search", refused)
    out, label = host_brokers.notion_search({"query": "x"}, {})
    assert out["ok"] is False and out["out"] == [] and "Notion access denied" in label


def test_a_refused_refresh_reads_as_needs_sign_in_not_connected():
    notion, (held, load, save) = FakeNotion(), _store()
    notion_mcp.connect(timeout=10, open_browser=_browser_that_allows, opener=notion, load=load, save=save)
    assert notion_mcp.connected(load) is True
    notion.expired_once, notion.refresh_refused = True, True
    try:
        notion_mcp.search("roadmap", opener=notion, load=load, save=save)
    except notion_mcp.NotionNotConnected:
        pass
    else:
        raise AssertionError("a refused refresh read as connected")
    assert notion_mcp.connected(load) is False, "the host must say needs-sign-in after Notion refused the grant"


def test_an_expired_grant_with_no_refresh_is_not_connected():
    held, load, save = _store()
    held[notion_mcp.GRANT_KEY] = json.dumps({"client_id": "c", "access_token": "a", "refresh_token": "", "expires_at": 1})
    assert notion_mcp.connected(load) is False


def test_a_callback_with_the_wrong_state_is_refused_and_the_real_one_still_completes():
    notion, (held, load, save) = FakeNotion(), _store()
    answers = []

    def stray_then_allow(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        stray = query["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "evil", "state": "not-ours"})
        try:
            urllib.request.urlopen(stray, timeout=5)
        except urllib.error.HTTPError as exc:
            answers.append((exc.code, exc.read().decode("utf-8")))
        _browser_that_allows(url)

    assert notion_mcp.connect(timeout=10, open_browser=stray_then_allow, opener=notion, load=load, save=save) == {"ok": True}
    assert answers and answers[0][0] == 400 and "connected" not in answers[0][1]
    assert json.loads(held[notion_mcp.GRANT_KEY])["access_token"] == "access-1"


def test_a_refused_code_exchange_saves_nothing_and_says_so():
    notion, (held, load, save) = FakeNotion(), _store()
    notion.exchange_refused = True
    pages = []

    def allow_and_read(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        back = query["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "code-1", "state": query["state"]})
        pages.append(urllib.request.urlopen(back, timeout=5).read().decode("utf-8"))

    answer = notion_mcp.connect(timeout=10, open_browser=allow_and_read, opener=notion, load=load, save=save)
    assert answer["ok"] is False and "refused the sign-in code" in answer["error"]
    assert notion_mcp.GRANT_KEY not in held
    assert "is connected" not in pages[0], "the browser is never told it is connected before the grant is saved"
