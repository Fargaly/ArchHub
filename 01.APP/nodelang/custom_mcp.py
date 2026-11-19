"""Custom MCP servers the person adds in Settings > Connections: one owner, one file.

File: <state>/settings/mcp_servers.json holds names, URLs, commands and arguments only.
Header and environment values (tokens, keys) go to the OS credential store through
app.secrets_store under ``mcp-<id>-<kind>-<NAME>``; the file keeps only their names.

Each enabled server registers as connector ``mcp:<id>`` (host_exec.register_connector),
so its live tools show in the Library "Connector action" node, reach every agent through
ArchHub's own MCP server (native_host_tools mcp_call), and every call passes decide()
like any other connector action.

A remote server that answers 401 signs in in the browser: MCP authorization (protected-resource
and authorization-server metadata, dynamic client registration, PKCE, loopback), the same flow
notion_mcp runs for Notion. The grant is kept under ``mcp-<id>-oauth-grant``.

Prior art: VS Code / Cursor / Claude Desktop "mcpServers" JSON (command+args+env, or
url+headers), Docker MCP Gateway (one gateway re-exposing many servers to any client), and the
MCP authorization spec as Claude Code and VS Code run it for remote servers.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from urllib.parse import urlparse

from .user_paths import state_directory

PREFIX = "mcp:"
MCP_NODE = {"id": "mcp.servers", "params": {"timeout_seconds": 20.0}}  # one request to a tool server
SIGN_IN_NEEDED = "needs you to sign in"
_SLUG = re.compile(r"[^a-z0-9]+")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")


class McpRefused(ValueError):
    """The entry cannot be added or the server did not answer as MCP."""


def _file():
    from .nograph_server import JsonFile
    return JsonFile(state_directory() / "settings" / "mcp_servers.json", {"servers": []})


def _secrets():
    from app import secrets_store  # noqa: PLC0415
    return secrets_store


def _slug(text):
    return _SLUG.sub("-", str(text or "").casefold()).strip("-")[:40] or "server"


def _secret_key(server_id, kind, name):
    return "mcp-%s-%s-%s" % (server_id, kind, name)


def _one(name, spec):
    """(entry, {(kind, NAME): value}) from one mcpServers-style spec."""
    if not isinstance(spec, Mapping):
        raise McpRefused("Each server needs a url or a command.")
    url = str(spec.get("url") or spec.get("serverUrl") or "").strip()
    command = str(spec.get("command") or "").strip()
    secrets = {}
    for kind, field in (("env", "env"), ("header", "headers")):
        values = spec.get(field) or {}
        if not isinstance(values, Mapping):
            raise McpRefused("%s must be a list of names and values." % field)
        for key, value in values.items():
            if not _NAME.match(str(key)):
                raise McpRefused("%s is not a valid %s name." % (key, kind))
            secrets[(kind, str(key))] = str(value)
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise McpRefused("The address must start with https://.")
        if parsed.username or parsed.password:
            raise McpRefused("Put the password in a header, not in the address.")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise McpRefused("Only https:// addresses, or http:// on this PC.")
        _refuse_secret_in_url(url, parsed)
        entry = {"transport": "http", "url": url, "name": name or parsed.hostname}
    elif command:
        args = spec.get("args") or []
        if not isinstance(args, list):
            raise McpRefused("args must be a list.")
        from .runtime_credentials import assert_not_a_secret
        for value in (command, *map(str, args)):
            try:
                assert_not_a_secret(value, "An argument")
            except ValueError as exc:
                raise McpRefused("An argument looks like a key. Put it under env so it goes to "
                                 "Windows Credential Manager.") from exc
        entry = {"transport": "stdio", "command": command, "args": [str(a) for a in args],
                 "name": name or os.path.splitext(os.path.basename(command))[0]}
    else:
        raise McpRefused("Each server needs a url or a command.")
    return entry, secrets


_SECRET_QUERY = re.compile(r"(?i)(key|token|secret|password|passwd|pwd|auth|sig|signature|credential)")


def _refuse_secret_in_url(url, parsed):
    """A key in the address would be saved in plain text in mcp_servers.json: refused, the header way is offered."""
    from urllib.parse import parse_qsl
    from .runtime_credentials import assert_not_a_secret
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _SECRET_QUERY.search(name):
            raise McpRefused("The address carries a key (%s=). Put it under headers so it goes to "
                             "Windows Credential Manager." % name)
        try:
            assert_not_a_secret(value, "The address")
        except ValueError as exc:
            raise McpRefused("The address carries something that looks like a key. Put it under headers "
                             "so it goes to Windows Credential Manager.") from exc
    for part in (parsed.path, parsed.fragment):
        for piece in re.split(r"[/;=&]", part or ""):
            try:
                assert_not_a_secret(piece, "The address")
            except ValueError as exc:
                raise McpRefused("The address carries something that looks like a key. Put it under headers "
                                 "so it goes to Windows Credential Manager.") from exc


def parse(text):
    """[(entry, secrets)] from a URL, a command line, or an mcp.json snippet."""
    text = str(text or "").strip()
    if not text:
        raise McpRefused("Paste an address, a command, or an mcp.json snippet.")
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise McpRefused("That JSON could not be read: %s" % exc.msg) from exc
        group = data.get("mcpServers") or data.get("servers") or data.get("mcp", {}).get("servers") \
            if isinstance(data, Mapping) else None
        if isinstance(group, Mapping):
            return [_one(str(name), spec) for name, spec in group.items()]
        if isinstance(data, Mapping) and ("url" in data or "command" in data):
            return [_one(str(data.get("name") or ""), data)]
        if isinstance(data, Mapping) and data and all(isinstance(v, Mapping) for v in data.values()):
            return [_one(str(name), spec) for name, spec in data.items()]
        raise McpRefused("No servers found in that JSON.")
    if re.match(r"^https?://", text, re.I):
        return [_one("", {"url": text})]
    parts = shlex.split(text, posix=os.name != "nt")
    parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]
    return [_one("", {"command": parts[0], "args": parts[1:]})]


def servers():
    """Every saved server, without secret values."""
    rows = _file().read().get("servers")
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def add(text, *, store=None):
    """Save each server in ``text``; secret values go to the credential store. Returns the new rows."""
    store = store or _secrets()
    parsed = parse(text)
    rows = servers()
    taken = {row["id"] for row in rows}
    added = []
    for entry, secrets in parsed:
        base = _slug(entry["name"])
        server_id, n = base, 2
        while server_id in taken:
            server_id, n = "%s-%d" % (base, n), n + 1
        taken.add(server_id)
        for (kind, name), value in secrets.items():
            store.save_api_key(_secret_key(server_id, kind, name), value)
        row = {**entry, "id": server_id, "enabled": True,
               "env": sorted(n for k, n in secrets if k == "env"),
               "headers": sorted(n for k, n in secrets if k == "header")}
        rows.append(row)
        added.append(row)
    _file().write({"servers": rows})
    register_all()
    return added


def remove(server_id, *, store=None):
    store = store or _secrets()
    rows = servers()
    row = next((r for r in rows if r["id"] == server_id), None)
    if row is None:
        raise McpRefused("No such tool server.")
    for kind, names in (("env", row.get("env") or []), ("header", row.get("headers") or []),
                        ("oauth", ["grant"] if row.get("auth") == "oauth" else [])):
        for name in names:
            store.delete_api_key(_secret_key(server_id, kind, name))
    _file().write({"servers": [r for r in rows if r["id"] != server_id]})
    register_all()
    return {"removed": server_id}


def set_enabled(server_id, enabled):
    rows = servers()
    if not any(r["id"] == server_id for r in rows):
        raise McpRefused("No such tool server.")
    for r in rows:
        if r["id"] == server_id:
            r["enabled"] = bool(enabled)
    _file().write({"servers": rows})
    register_all()
    return {"id": server_id, "enabled": bool(enabled)}


def _secret_values(row, kind, store):
    names = row.get("env" if kind == "env" else "headers") or []
    return {name: store.load_api_key(_secret_key(row["id"], kind, name)) or "" for name in names}


def _grant_header(row, store, opener=None):
    from .notion_mcp import _load_grant, _refresh
    import time
    key = _secret_key(row["id"], "oauth", "grant")
    grant = _load_grant(store.load_api_key, key)
    if grant is None:
        raise McpRefused("%s %s." % (row["name"], SIGN_IN_NEEDED))
    if float(grant.get("expires_at") or 0) < time.time() + 30:
        try:
            grant = _refresh(grant, store.save_api_key, opener, key)
        except Exception as exc:  # refused or expired: the person signs in again
            raise McpRefused("%s %s." % (row["name"], SIGN_IN_NEEDED)) from exc
    return {"Authorization": "Bearer " + grant["access_token"]}


def _rpc_http(row, method, params, store, opener=None):
    import urllib.error
    headers = {k: v for k, v in _secret_values(row, "header", store).items() if v}
    if row.get("auth") == "oauth":
        headers.update(_grant_header(row, store, opener))
    url = row["url"]
    try:
        return _rpc_http_once(url, method, params, headers, opener)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise McpRefused("%s %s." % (row["name"], SIGN_IN_NEEDED)) from exc
        raise


def _rpc_http_once(url, method, params, headers, opener):
    from .notion_mcp import _json_or_sse, _post
    _raw, session = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "ArchHub", "version": "1"}}}, headers, timeout=MCP_NODE["params"]["timeout_seconds"], opener=opener)
    headers = {**headers, **({"Mcp-Session-Id": session} if session else {})}
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers, timeout=MCP_NODE["params"]["timeout_seconds"], opener=opener)
    raw, _ = _post(url, {"jsonrpc": "2.0", "id": 2, "method": method, "params": dict(params)},
                   headers, timeout=MCP_NODE["params"]["timeout_seconds"], opener=opener)
    return _json_or_sse(raw)


def _rpc_stdio(row, method, params, store):
    # shortcut: one process per call (start, initialize, one request, close); keep a live session
    # per server only when a slow-starting server makes nodes or agents wait.
    command = shutil.which(row["command"]) or row["command"]
    env = {**os.environ, **{k: v for k, v in _secret_values(row, "env", store).items() if v}}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        child = subprocess.Popen([command, *row.get("args", [])], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                 creationflags=flags)
    except OSError as exc:
        raise McpRefused("%s could not start: %s" % (row["name"], exc.strerror or exc)) from exc
    answers, done = {}, threading.Event()

    def reader():
        for line in child.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") in (1, 2):
                answers[message["id"]] = message
                if message["id"] == 2 or "error" in message:
                    done.set()
        done.set()

    threading.Thread(target=reader, daemon=True).start()

    def send(message):
        child.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        child.stdin.flush()

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "ArchHub", "version": "1"}}})
        waited = threading.Event()
        for _ in range(int(MCP_NODE["params"]["timeout_seconds"] * 10)):
            if 1 in answers or done.is_set():
                break
            waited.wait(0.1)
        if 1 not in answers:
            raise McpRefused("%s did not answer as an MCP server." % row["name"])
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": method, "params": dict(params)})
        done.wait(MCP_NODE["params"]["timeout_seconds"])
        if 2 not in answers:
            raise McpRefused("%s did not answer %s in time." % (row["name"], method))
        return answers[2]
    except OSError as exc:
        raise McpRefused("%s stopped: %s" % (row["name"], exc)) from exc
    finally:
        try:
            child.stdin.close()
            child.terminate()
            child.wait(3)
        except (OSError, subprocess.TimeoutExpired):
            child.kill()


def rpc(row, method, params, *, store=None, opener=None):
    """One MCP request to the server; the result mapping, or McpRefused."""
    store = store or _secrets()
    try:
        answer = (_rpc_http(row, method, params, store, opener) if row["transport"] == "http"
                  else _rpc_stdio(row, method, params, store))
    except McpRefused:
        raise
    except Exception as exc:  # network, HTTP status, unreadable body: one plain reason
        raise McpRefused("%s did not answer: %s" % (row["name"], exc)) from exc
    if not isinstance(answer, Mapping) or "error" in answer:
        error = answer.get("error") if isinstance(answer, Mapping) else answer
        raise McpRefused(str(error.get("message") if isinstance(error, Mapping) else error))
    result = answer.get("result")
    if not isinstance(result, Mapping):
        raise McpRefused("%s answered with no result." % row["name"])
    return result


def list_tools(row, **kw):
    rows = []
    for tool in rpc(row, "tools/list", {}, **kw).get("tools") or []:
        if isinstance(tool, Mapping) and tool.get("name"):
            schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), Mapping) else {}
            props = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
            notes = tool.get("annotations") if isinstance(tool.get("annotations"), Mapping) else {}
            read_only = notes.get("readOnlyHint") is True  # a label for people only; never an authorization
            rows.append({"name": str(tool["name"]),
                         "title": str(tool.get("title") or tool.get("description") or tool["name"]),
                         "inputs": [str(k) for k in props], "readOnly": read_only})
    return rows



def call_tool(row, name, arguments, **kw):
    result = rpc(row, "tools/call", {"name": name, "arguments": dict(arguments or {})}, **kw)
    text = " ".join(str(b.get("text") or "") for b in result.get("content") or ()
                    if isinstance(b, Mapping)).strip()
    if result.get("isError"):
        raise McpRefused(text or "The tool refused the call.")
    return result.get("structuredContent") or text or result


def _find(server_id):
    row = next((r for r in servers() if r["id"] == server_id and r.get("enabled", True)), None)
    if row is None:
        raise McpRefused("This tool server is off or removed.")
    return row


def register_all():
    """Register every enabled server as connector mcp:<id>; drop removed or switched-off ones."""
    from . import host_exec
    wanted = {PREFIX + r["id"]: r for r in servers() if r.get("enabled", True)}
    for key in [k for k in host_exec.LISTERS if k.startswith(PREFIX) and k not in wanted]:
        host_exec.LISTERS.pop(key, None)
        host_exec.INVOKERS.pop(key, None)
    for key, row in wanted.items():
        server_id = row["id"]
        host_exec.register_connector(
            key, row["name"],
            lambda sid=server_id: list_tools(_find(sid)),
            lambda action, arguments, sid=server_id: call_tool(_find(sid), action, arguments))
    return sorted(wanted)


def _get_json(url, opener=None):
    import urllib.request
    from .notion_mcp import USER_AGENT
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with (opener or urllib.request.urlopen)(request, timeout=MCP_NODE["params"]["timeout_seconds"]) as response:
        return json.loads(response.read().decode("utf-8"))


def discover(url, opener=None):
    """The server's sign-in endpoints from its published metadata (MCP authorization, RFC 9728 / RFC 8414)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise McpRefused("Only a tool server on an https:// address signs in.")
    origin = "%s://%s" % (parsed.scheme, parsed.netloc)
    issuer = origin
    for candidate in (origin + "/.well-known/oauth-protected-resource" + parsed.path.rstrip("/"),
                      origin + "/.well-known/oauth-protected-resource"):
        try:
            servers_ = _get_json(candidate, opener).get("authorization_servers") or []
        except Exception:  # not published there; the next place, then the server's own origin
            continue
        if servers_:
            issuer = str(servers_[0]).rstrip("/")
            break
    issued = urlparse(issuer)
    if issued.scheme != "https" or not issued.netloc or issued.username or issued.password:
        raise McpRefused("The server names a sign-in address that is not https; nothing was fetched from it.")
    meta = None
    for candidate in ("%s://%s/.well-known/oauth-authorization-server%s" % (issued.scheme, issued.netloc, issued.path),
                      "%s://%s/.well-known/openid-configuration%s" % (issued.scheme, issued.netloc, issued.path)):
        try:
            meta = _get_json(candidate, opener)
            break
        except Exception:
            continue
    if not isinstance(meta, Mapping) or not meta.get("authorization_endpoint") or not meta.get("token_endpoint"):
        raise McpRefused("This server does not publish how to sign in.")
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        value = meta.get(key)
        if value and urlparse(str(value)).scheme != "https":
            raise McpRefused("The sign-in address is not https.")
    return {"authorize": meta["authorization_endpoint"], "token": meta["token_endpoint"],
            "register": meta.get("registration_endpoint") or ""}


def sign_in(server_id, *, store=None, opener=None, open_browser=None, connect=None):
    """Sign in to a remote server in the browser; the grant goes to the credential store, never the file."""
    import webbrowser
    from .notion_mcp import connect as oauth_connect
    store = store or _secrets()
    rows = servers()
    row = next((r for r in rows if r["id"] == server_id), None)
    if row is None or row.get("transport") != "http":
        raise McpRefused("Only a tool server with a web address signs in.")
    endpoints = discover(row["url"], opener)
    result = (connect or oauth_connect)(endpoints=endpoints, grant_key=_secret_key(server_id, "oauth", "grant"),
                                        label=row["name"], resource=row["url"], opener=opener,
                                        open_browser=open_browser or webbrowser.open,
                                        load=store.load_api_key, save=store.save_api_key)
    if not result.get("ok"):
        raise McpRefused(result.get("error") or "Sign-in did not finish.")
    for r in rows:
        if r["id"] == server_id:
            r["auth"] = "oauth"
    _file().write({"servers": rows})
    register_all()
    return {"id": server_id, "signedIn": True}


def agent_tools(server_id=""):
    """What an agent sees: the servers, or one server's live tools. Same answer on every agent surface."""
    if not server_id:
        return {"ok": True, "servers": [{"id": r["id"], "name": r["name"], "enabled": r.get("enabled", True)}
                                        for r in servers()]}
    try:
        return {"ok": True, "server": server_id, "tools": list_tools(_find(server_id))}
    except McpRefused as refused:
        return {"ok": False, "reason": str(refused)}


def agent_call(server_id, tool, arguments=None):
    """One tool call for an agent, through connector.call: sends and writes wait on decide() like any connector."""
    from .host_exec import connector_call
    out, label = connector_call({"connector": PREFIX + server_id, "action": tool, "args": dict(arguments or {})})
    # label is the tool name on success, "Waiting for you" when held for Approve, "Failed" otherwise
    return {"ok": label not in ("Failed", "Waiting for you"), "label": label, **out}


def status_rows(probe: Callable | None = None):
    """Settings rows: each server with its live tool count or the reason it failed."""
    out = []
    for row in servers():
        shown = {k: row.get(k) for k in ("id", "name", "transport", "url", "command", "args", "enabled", "env", "headers")}
        if not row.get("enabled", True):
            out.append({**shown, "status": "off", "tools": []})
            continue
        try:
            tools = (probe or list_tools)(row)
            out.append({**shown, "status": "%d tools" % len(tools), "tools": tools})
        except McpRefused as exc:
            out.append({**shown, "status": "failed: %s" % exc, "tools": []})
    return out


__all__ = ["McpRefused", "PREFIX", "add", "call_tool", "list_tools", "parse", "register_all",
           "remove", "servers", "set_enabled", "status_rows"]
