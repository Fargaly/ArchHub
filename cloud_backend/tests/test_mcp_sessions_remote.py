"""Remote MCP clients can open ArchHub sessions through the existing /mcp door.

No live cloud, Notion, Google, or desktop app is contacted here.  The fake MCP
client calls brain_mcp.answer directly with a fake OAuth user and a fake
account-scoped session backend.
"""
from __future__ import annotations

import json

import brain_mcp


USER_A = {"id": "u-a", "email": "owner-a@example.com", "plan": "trial"}
USER_B = {"id": "u-b", "email": "owner-b@example.com", "plan": "trial"}


def _payload(body: bytes) -> dict:
    text = body.decode("utf-8")
    line = [line for line in text.splitlines() if line.startswith("data: ")][0]
    return json.loads(line[len("data: "):])


def _answer(user, method="tools/list", params=None, session_call=None):
    status, body, _media = brain_mcp.answer(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        resolve_user=lambda: user,
        open_replica=lambda _user: object(),
        session_call=session_call,
    )
    assert status == 200
    return _payload(body)


def test_fake_mcp_client_lists_the_four_session_tools():
    listed = _answer(USER_A)
    names = {tool["name"] for tool in listed["result"]["tools"]}

    assert {"list_sessions", "open_session", "send_to_session", "new_session"} <= names


def test_open_session_is_scoped_to_the_oauth_account_and_refuses_another_account():
    sessions = {
        "u-a": {"sess-a": {"id": "sess-a", "title": "A", "state": "idle", "tail": ["a1"]}},
        "u-b": {"sess-b": {"id": "sess-b", "title": "B", "state": "idle", "tail": ["b1"]}},
    }

    def fake_sessions(user, method, arguments):
        mine = sessions[user["id"]]
        if method == "open_session":
            session = mine.get(arguments["id"])
            if not session:
                raise PermissionError("session is not in this ArchHub account")
            return session
        raise KeyError(method)

    opened = _answer(USER_A, "tools/call", {"name": "open_session", "arguments": {"id": "sess-a"}},
                     session_call=fake_sessions)
    refused = _answer(USER_A, "tools/call", {"name": "open_session", "arguments": {"id": "sess-b"}},
                      session_call=fake_sessions)

    assert json.loads(opened["result"]["content"][0]["text"])["tail"] == ["a1"]
    assert refused["result"]["isError"] is True
    assert "not in this ArchHub account" in refused["result"]["content"][0]["text"]


def test_send_to_session_is_ask_only_and_never_executes_or_replays():
    seen = []

    def fake_sessions(user, method, arguments):
        seen.append((user["email"], method, dict(arguments)))
        return {"ok": True, "mode": "ask", "session_id": arguments["id"], "queued": True}

    body = _answer(USER_A, "tools/call", {"name": "send_to_session",
                                          "arguments": {"id": "sess-a", "text": "continue"}},
                   session_call=fake_sessions)

    assert json.loads(body["result"]["content"][0]["text"])["mode"] == "ask"
    assert seen == [("owner-a@example.com", "send_to_session",
                     {"id": "sess-a", "text": "continue", "mode": "ask"})]


def test_new_session_is_ask_gated_and_owned_by_the_oauth_account():
    seen = []

    def fake_sessions(user, method, arguments):
        seen.append((user["email"], method, dict(arguments)))
        return {"id": "sess-new", "title": arguments["title"], "state": "idle"}

    body = _answer(USER_A, "tools/call", {"name": "new_session",
                                          "arguments": {"title": "Remote plan"}},
                   session_call=fake_sessions)

    assert json.loads(body["result"]["content"][0]["text"])["id"] == "sess-new"
    assert seen == [("owner-a@example.com", "new_session",
                     {"title": "Remote plan", "mode": "ask"})]
