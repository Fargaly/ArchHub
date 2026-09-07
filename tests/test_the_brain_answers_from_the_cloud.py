"""The founder's brain answers over MCP, from any machine.

The memory has been on the cloud all along -- his replica holds 1,797 facts
and /v1/brain/stats answers in 0.9s -- but sessions speak MCP and this cloud
served only REST. So Claude, Codex and Antigravity all pointed at a LOCAL
daemon on 127.0.0.1:8473: the thing that has to be alive, hold a port and
survive a wedge. Every brain failure he hit came from that (audit,
2026-09-07).

The cloud's own attempt to reach a brain proved the shape of the gap:
founder_cockpit.py dials 127.0.0.1:8473, which inside a Fly container is
that container's loopback, where no brain has ever run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud_backend"))
import brain_mcp  # noqa: E402


class _Replica:
    def __init__(self, fragments):
        self._fragments = fragments

    def export_delta(self, since_hlc=""):
        return {"fragments": self._fragments}


FACTS = [
    {"kind": "fact", "text": "the map is the graph", "subject": "map"},
    {"kind": "fact", "text": "BABOOM attaches by signed session", "subject": "baboom"},
    {"kind": "skill", "text": "not a fact"},
]
FOUNDER = {"email": "founder@example.com", "plan": "studio", "id": "u1"}


def _answer(message, *, user=FOUNDER, replica=None):
    return brain_mcp.answer(
        message,
        resolve_user=lambda: user,
        open_replica=lambda u: replica or _Replica(FACTS),
    )


def _payload(body):
    line = [
        row for row in body.decode("utf-8").splitlines()
        if row.startswith("data:")
    ][0]
    return json.loads(line[5:])


def test_a_client_only_has_to_change_its_url():
    """The wire shape is the one the local daemon speaks."""
    status, body, media = _answer({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-06-18"}})
    assert status == 200
    assert media == "text/event-stream"
    assert body.startswith(b"event: message\ndata: ")
    assert body.endswith(b"\n\n")
    result = _payload(body)["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"]["tools"] == {"listChanged": False}


def test_an_unknown_protocol_is_negotiated_down_never_echoed():
    result = _payload(_answer({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "1999-01-01"}})[1])["result"]
    assert result["protocolVersion"] == brain_mcp.DEFAULT_PROTOCOL


def test_the_tools_are_the_ones_a_session_needs():
    tools = _payload(_answer({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[1])
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert names == {"brain.health", "brain.search", "brain.list_facts"}


def test_health_says_where_it_is_and_whose_it_is():
    said = _payload(_answer({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "brain.health"}})[1])
    held = json.loads(said["result"]["content"][0]["text"])
    assert held["ok"] is True
    assert held["where"] == "cloud", "a session must be able to tell where it read"
    assert held["account"] == FOUNDER["email"]
    assert held["facts"] == 2, "skills are not facts"


def test_search_reads_only_facts_and_honours_the_needle():
    said = _payload(_answer({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "brain.search",
                                        "arguments": {"q": "BABOOM"}}})[1])
    held = json.loads(said["result"]["content"][0]["text"])
    assert held["count"] == 1
    assert "signed session" in held["facts"][0]["text"]


def test_a_signed_out_caller_is_refused_not_served():
    def refuse():
        raise RuntimeError("invalid_token")

    status, body, _media = brain_mcp.answer(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "brain.health"}},
        resolve_user=refuse,
        open_replica=lambda u: _Replica(FACTS),
    )
    assert status == 401
    assert _payload(body)["error"]["code"] == -32001


def test_listing_and_initialising_need_no_account():
    """A client may look before it signs in; it may not READ before it does."""
    for method in ("initialize", "tools/list"):
        status, _body, _media = brain_mcp.answer(
            {"jsonrpc": "2.0", "id": 6, "method": method},
            resolve_user=lambda: (_ for _ in ()).throw(RuntimeError("no")),
            open_replica=lambda u: None,
        )
        assert status == 200


def test_an_unknown_tool_is_named_not_guessed():
    said = _payload(_answer({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                             "params": {"name": "brain.delete_everything"}})[1])
    assert said["error"]["code"] == -32602


def test_a_refusal_is_the_answer_never_a_silent_drop():
    class _Angry:
        def export_delta(self, since_hlc=""):
            raise RuntimeError("replica is unavailable")

    said = _payload(_answer({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                             "params": {"name": "brain.health"}},
                            replica=_Angry())[1])
    assert said["result"]["isError"] is True
    assert "replica is unavailable" in said["result"]["content"][0]["text"]


def test_it_is_read_only():
    """Writes stay on /v1/brain/sync, which owns the secret screening."""
    names = {tool["name"] for tool in brain_mcp.TOOLS}
    assert not any("write" in name or "delete" in name for name in names)
    source = (
        Path(__file__).resolve().parents[1] / "cloud_backend" / "brain_mcp.py"
    ).read_text(encoding="utf-8")
    assert "upsert_fragment" not in source and "apply_delta" not in source


def test_a_notification_is_accepted_without_a_body():
    status, body, _media = _answer(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert status == 202 and body == b""


def test_the_route_itself_answers_not_only_the_dispatcher():
    """A dispatcher that works behind a route that does not is worth nothing.

    The route first read the body with `json.loads`, but main.py has no
    module-level `json`: the NameError was swallowed by the except beside it
    and EVERY request came back 400 with an empty body -- a swallowed error
    that looked exactly like a malformed request (2026-09-07).
    """
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud_backend"))
    import main

    client = TestClient(main.app, base_url="https://testserver",
                        raise_server_exceptions=False)
    answered = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert answered.status_code == 200, answered.text
    assert answered.text.startswith("event: message\ndata: ")
    names = {
        tool["name"]
        for tool in json.loads(
            answered.text.splitlines()[1][5:]
        )["result"]["tools"]
    }
    assert names == {"brain.health", "brain.search", "brain.list_facts"}


def test_a_body_that_is_not_json_is_refused_honestly():
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud_backend"))
    import main

    client = TestClient(main.app, base_url="https://testserver",
                        raise_server_exceptions=False)
    refused = client.post("/mcp", content=b"not json at all",
                          headers={"Content-Type": "application/json"})
    assert refused.status_code == 400
