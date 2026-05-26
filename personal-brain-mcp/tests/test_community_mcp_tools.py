"""Tests for the 4 community MCP tools added to server.py.

The tools wrap personal_brain.community primitives so the FastMCP
transport can drive subscribe / unsubscribe / list / poll_now from
clients (Claude Code, ArchHub Brain tab, etc.). These tests exercise
the tool wiring through the FastMCP `call_tool` surface — which is the
same path real clients hit — plus the underlying community state to
prove the wrappers actually mutate persistent storage.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from personal_brain.server import build_server
from personal_brain.storage import BrainStore


def _call(mcp, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke an MCP tool via FastMCP's `call_tool` and unwrap the JSON
    payload. FastMCP returns a ToolResult with a `.structured_content`
    or `.content` block — both work here because all 4 community tools
    return dict payloads."""
    result = asyncio.run(mcp.call_tool(name, arguments or {}))
    # FastMCP ≥ 2 ToolResult exposes `.structured_content` for dict returns
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        return sc
    data = getattr(result, "data", None)
    if data is not None:
        return data
    # Fallback: content list with TextContent JSON
    content = getattr(result, "content", None)
    if content:
        import json as _json
        for item in content:
            txt = getattr(item, "text", None)
            if txt:
                try:
                    return _json.loads(txt)
                except Exception:
                    continue
    raise AssertionError(f"unrecognised ToolResult shape: {result!r}")


def _server(tmp_path):
    store = BrainStore.open(str(tmp_path / "brain.db"))
    mcp = build_server(store=store, default_owner_user="founder")
    return mcp, store


def test_community_subscribe_then_list_shows_it(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        resp = _call(mcp, "brain.community_subscribe", {
            "actor_url": "http://peer-firm.test/actor",
            "display_name": "Peer Firm A",
        })
        assert resp["ok"] is True
        sub = resp["subscription"]
        assert sub["actor_url"] == "http://peer-firm.test/actor"
        assert sub["display_name"] == "Peer Firm A"
        assert sub["subscribed_at"], "subscribed_at must be ISO-formatted"

        listed = _call(mcp, "brain.community_list", {})
        assert listed["ok"] is True
        urls = [s["actor_url"] for s in listed["subscriptions"]]
        assert "http://peer-firm.test/actor" in urls
        # display_name round-trips
        peer = next(s for s in listed["subscriptions"]
                    if s["actor_url"] == "http://peer-firm.test/actor")
        assert peer["display_name"] == "Peer Firm A"
    finally:
        store.close()


def test_community_unsubscribe_empties_list(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        _call(mcp, "brain.community_subscribe", {
            "actor_url": "http://gone.test/actor",
            "display_name": "Ephemeral Peer",
        })
        # Confirm the subscription is in place
        before = _call(mcp, "brain.community_list", {})
        assert any(s["actor_url"] == "http://gone.test/actor"
                   for s in before["subscriptions"])

        unsub = _call(mcp, "brain.community_unsubscribe",
                      {"actor_url": "http://gone.test/actor"})
        assert unsub["ok"] is True
        assert unsub["removed"] is True

        after = _call(mcp, "brain.community_list", {})
        assert all(s["actor_url"] != "http://gone.test/actor"
                   for s in after["subscriptions"])

        # Idempotent second unsubscribe → removed: False
        again = _call(mcp, "brain.community_unsubscribe",
                      {"actor_url": "http://gone.test/actor"})
        assert again["ok"] is True
        assert again["removed"] is False
    finally:
        store.close()


def test_community_poll_now_empty_returns_ok_empty(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        resp = _call(mcp, "brain.community_poll_now", {})
        assert resp["ok"] is True
        assert resp["results"] == []
    finally:
        store.close()


def test_community_poll_now_with_mocked_fetch_returns_result(tmp_path,
                                                              monkeypatch):
    """Subscribe + monkeypatch community.fetch_outbox to inject one
    Activity. Poll should produce exactly one PollResult, even if the
    Activity is quarantined (cold-start reputation tends to quarantine
    fresh peers — what matters is that the wire is intact)."""
    from personal_brain import community as community_mod

    # Inject a single Pattern-shaped Activity. The contributor hash is
    # 'peer-X'; the driver may accept or quarantine depending on cold-
    # start floors. Either way the wire produced one PollResult.
    fake_outbox = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": "http://peer.test/outbox",
        "type": "OrderedCollection",
        "totalItems": 1,
        "orderedItems": [
            {
                "type": "Create",
                "id": "http://peer.test/activity/1",
                "actor": "http://peer.test/actor",
                "object": {
                    "type": "Pattern",
                    "pattern_id": "p-mock-1",
                    "kind": "skill_usage",
                    "summary": "mock skill use",
                    "statistics": {"count": 42},
                    "contributor_firm_hash": "peer-X",
                },
            }
        ],
    }

    def fake_fetch(actor_url, *, timeout_s=5.0, http_client=None):
        return fake_outbox

    monkeypatch.setattr(community_mod, "fetch_outbox", fake_fetch)

    mcp, store = _server(tmp_path)
    try:
        sub = _call(mcp, "brain.community_subscribe", {
            "actor_url": "http://peer.test/actor",
            "display_name": "Mock Peer",
        })
        assert sub["ok"] is True

        poll = _call(mcp, "brain.community_poll_now", {})
        assert poll["ok"] is True
        assert len(poll["results"]) == 1
        r = poll["results"][0]
        assert r["actor_url"] == "http://peer.test/actor"
        assert r["ok"] is True
        assert r["activities_fetched"] == 1
        # The single activity was either accepted or quarantined or rejected
        # — total decisions must equal the fetch count.
        total_decisions = r["accepted"] + r["quarantined"] + r["rejected"]
        assert total_decisions == 1
    finally:
        store.close()
