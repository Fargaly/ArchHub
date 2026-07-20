"""Wire contract for the lightweight, PID-bound Brain liveness probe."""
from __future__ import annotations

import json
import os
from typing import Any

from personal_brain.server import build_server
from personal_brain.storage import BrainStore


def _call(mcp, name: str) -> dict[str, Any]:
    result = mcp.call_tool(name, {})
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    if isinstance(structured, dict):
        return structured
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        payload = json.loads(item.get("text") or "{}")
        if isinstance(payload, dict):
            return payload
    raise AssertionError(f"missing structured liveness result: {result!r}")


def test_liveness_is_registered_pid_bound_and_not_the_full_diagnostic():
    store = BrainStore.open(":memory:")
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        names = {tool["name"] for tool in mcp.list_tools()}

        payload = _call(mcp, "brain.liveness")

        assert "brain.liveness" in names
        assert payload["ok"] is True
        assert payload["server_pid"] == os.getpid()
        assert isinstance(payload["engine"], dict)
        assert "db_path" not in payload
        assert "owner" not in payload
        assert "personal_sync" not in payload
    finally:
        store.close()
