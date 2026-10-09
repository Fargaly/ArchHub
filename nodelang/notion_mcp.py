"""Notion through Notion's own hosted MCP server, signed in with OAuth.

The founder never copies a token: ``connect()`` registers ArchHub as an OAuth
client with Notion (RFC 7591 dynamic registration), opens Notion's consent
page in the browser, receives the one-time code on a loopback port, and
keeps the resulting grant (access + refresh token) in the secrets store.
``search()`` then calls the ``notion-search`` tool of https://mcp.notion.com/mcp
with that grant, refreshing it when Notion says it expired.

Reference: developers.notion.com/guides/mcp/build-mcp-client (OAuth 2.0 +
PKCE, dynamic client registration, Streamable HTTP transport).
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping

MCP_URL = "https://mcp.notion.com/mcp"
AUTHORIZE_URL = "https://mcp.notion.com/authorize"
TOKEN_URL = "https://mcp.notion.com/token"
REGISTER_URL = "https://mcp.notion.com/register"
GRANT_KEY = "notion-mcp"
CALLBACK_PATH = "/notion/callback"
# Notion's edge (Cloudflare) refuses the default Python client signature (error 1010).
USER_AGENT = "ArchHub/1.0 (+https://archhub.io)"


class NotionNotConnected(RuntimeError):
    """No usable Notion grant is held: never signed in, or Notion refused it."""


class NotionToolError(RuntimeError):
    """Notion answered the tool call with an error or a body ArchHub cannot read."""


def _post(url: str, body: Mapping[str, object] | str, headers: Mapping[str, str] | None = None,
          timeout: float = 20.0, opener: Callable | None = None):
    data = body if isinstance(body, str) else json.dumps(body)
    content = "application/x-www-form-urlencoded" if isinstance(body, str) else "application/json"
    request = urllib.request.Request(url, data=data.encode("utf-8"), method="POST",
                                     headers={"Content-Type": content, "Accept": "application/json, text/event-stream",
                                              "User-Agent": USER_AGENT,
                                              **dict(headers or {})})
    with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        session = response.headers.get("Mcp-Session-Id") if response.headers else None
    return raw, session


def _json_or_sse(raw: str) -> dict:
    """An MCP answer arrives as JSON or as one Server-Sent Event carrying JSON."""
    text = raw.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise ValueError("Notion MCP answered with no JSON body")


def _load_grant(load: Callable[[str], str | None]) -> dict | None:
    raw = load(GRANT_KEY)
    if not raw:
        return None
    try:
        grant = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(grant, dict) or not grant.get("access_token") or grant.get("refused"):
        return None
    if float(grant.get("expires_at") or 0) < time.time() + 30 and not grant.get("refresh_token"):
        return None
    return grant


def _secrets():
    from app import secrets_store  # noqa: PLC0415
    return secrets_store.load_api_key, secrets_store.save_api_key


def connected(load: Callable[[str], str | None] | None = None) -> bool:
    """A usable grant is held (unexpired or refreshable, not refused). A search verifies it."""
    if load is None:
        try:
            load, _save = _secrets()
        except Exception:
            return False
    return _load_grant(load) is not None


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def connect(*, timeout: float = 300.0, open_browser: Callable[[str], object] = webbrowser.open,
            opener: Callable | None = None, load: Callable | None = None, save: Callable | None = None) -> dict:
    """Run Notion's consent once and keep the grant. Returns {ok, workspace?}."""
    if load is None or save is None:
        load, save = _secrets()
    received: dict[str, str] = {}
    done = threading.Event()
    state = secrets.token_urlsafe(24)

    class Callback(http.server.BaseHTTPRequestHandler):
        def _page(self, status: int, text: str):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<p>%s</p>" % text).encode("utf-8"))

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self._page(404, "Not found."); return
            query = dict(urllib.parse.parse_qsl(parsed.query))
            # Only the pending sign-in's own answer counts, and only once; a stray or
            # replayed callback neither ends the sign-in nor claims anything.
            if query.get("state") != state or done.is_set():
                self._page(400, "This answer does not belong to ArchHub's pending Notion sign-in.")
                return
            received.update(query)
            done.set()
            self._page(200, "Notion answered. ArchHub is finishing the sign-in; you can close this tab."
                       if "code" in query else "Notion sign-in was not allowed. You can close this tab.")

        def log_message(self, *args):  # silence
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Callback)
    redirect_uri = "http://127.0.0.1:%d%s" % (server.server_address[1], CALLBACK_PATH)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        raw, _ = _post(REGISTER_URL, {
            "client_name": "ArchHub",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }, opener=opener)
        client = json.loads(raw)
        client_id = str(client.get("client_id") or "")
        if not client_id:
            return {"ok": False, "error": "Notion did not register ArchHub as a client"}
        verifier, challenge = _pkce()
        open_browser(AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        }))
        if not done.wait(timeout):
            return {"ok": False, "error": "Notion sign-in was not completed in time"}
        if "code" not in received:
            return {"ok": False, "error": received.get("error_description") or received.get("error")
                    or "Notion sign-in answered without a code"}
        try:
            raw, _ = _post(TOKEN_URL, urllib.parse.urlencode({
                "grant_type": "authorization_code", "code": received["code"], "redirect_uri": redirect_uri,
                "client_id": client_id, "code_verifier": verifier,
            }), opener=opener)
            token = json.loads(raw)
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": "Notion refused the sign-in code (HTTP %s)" % exc.code}
        except ValueError:
            return {"ok": False, "error": "Notion answered the sign-in with no readable grant"}
        if not token.get("access_token"):
            return {"ok": False, "error": "Notion returned no access grant"}
        grant = {"client_id": client_id, "access_token": token["access_token"],
                 "refresh_token": token.get("refresh_token") or "",
                 "expires_at": time.time() + float(token.get("expires_in") or 3600)}
        save(GRANT_KEY, json.dumps(grant))
        return {"ok": True}
    finally:
        server.shutdown()
        server.server_close()


def _refused(grant: dict, save: Callable, why: str):
    save(GRANT_KEY, json.dumps({**grant, "refused": True}))
    return NotionNotConnected(why)


def _refresh(grant: dict, save: Callable, opener: Callable | None) -> dict:
    if not grant.get("refresh_token"):
        raise _refused(grant, save, "the Notion sign-in expired; connect Notion again")
    try:
        raw, _ = _post(TOKEN_URL, urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": grant["refresh_token"], "client_id": grant["client_id"],
        }), opener=opener)
        token = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise _refused(grant, save, "Notion refused the saved sign-in; connect Notion again") from exc
        raise
    except ValueError as exc:
        raise NotionToolError("Notion answered the refresh with no readable grant") from exc
    if not token.get("access_token"):
        raise _refused(grant, save, "the Notion sign-in expired; connect Notion again")
    grant = {**grant, "access_token": token["access_token"],
             "refresh_token": token.get("refresh_token") or grant["refresh_token"],
             "expires_at": time.time() + float(token.get("expires_in") or 3600)}
    save(GRANT_KEY, json.dumps(grant))
    return grant


def call_tool(name: str, arguments: Mapping[str, object], *, opener: Callable | None = None,
              load: Callable | None = None, save: Callable | None = None) -> dict:
    """Call one Notion MCP tool with the held grant; refresh once if it expired."""
    if load is None or save is None:
        load, save = _secrets()
    grant = _load_grant(load)
    if grant is None:
        raise NotionNotConnected("Notion is not connected")
    if float(grant.get("expires_at") or 0) < time.time() + 30:
        grant = _refresh(grant, save, opener)
    for attempt in range(2):
        auth = {"Authorization": "Bearer " + grant["access_token"]}
        try:
            raw, session = _post(MCP_URL, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "ArchHub", "version": "1"}}}, auth, opener=opener)
            headers = {**auth, **({"Mcp-Session-Id": session} if session else {})}
            _post(MCP_URL, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers, opener=opener)
            raw, _ = _post(MCP_URL, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                     "params": {"name": name, "arguments": dict(arguments)}}, headers, opener=opener)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 0:
                grant = _refresh(grant, save, opener)
                continue
            if exc.code == 401:
                raise _refused(grant, save, "Notion refused the refreshed sign-in; connect Notion again") from exc
            raise
        try:
            answer = _json_or_sse(raw)
        except ValueError as exc:
            raise NotionToolError("Notion answered %s with a body ArchHub cannot read" % name) from exc
        if "error" in answer:
            error = answer["error"]
            raise NotionToolError(str(error.get("message") if isinstance(error, Mapping) else error))
        result = answer.get("result")
        if not isinstance(result, Mapping):
            raise NotionToolError("Notion answered %s with no result" % name)
        if result.get("isError"):
            text = " ".join(str(block.get("text") or "") for block in result.get("content") or ()
                            if isinstance(block, Mapping)).strip()
            raise NotionToolError(text or "Notion refused the %s call" % name)
        return result
    raise NotionNotConnected("Notion refused the refreshed sign-in")


def search(query: str, **kw) -> list[dict]:
    """Notion search rows: id, title, url, type, from the notion-search tool."""
    result = call_tool("notion-search", {"query": query or ""}, **kw)
    rows: list[dict] = []
    texts = [block.get("text") for block in result.get("content") or ()
             if isinstance(block, Mapping) and block.get("type") == "text" and block.get("text")]
    if not texts:
        raise NotionToolError("Notion search answered with no results body")
    for text in texts:
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise NotionToolError("Notion search answered: %s" % text[:200]) from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("results"), list):
            raise NotionToolError("Notion search answered without a results list")
        for item in payload["results"]:
            if isinstance(item, Mapping):
                rows.append({"id": item.get("id"), "title": item.get("title") or "",
                             "url": item.get("url") or "", "object": item.get("type") or "page"})
    return rows
