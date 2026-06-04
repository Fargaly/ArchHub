"""Brain #32 day-2 · brain.cloud_archive MCP tool wiring tests.

Closes the dead-code gap: cloud_archive.upload_dataset existed + was
tested for guard branches but had no MCP tool surface and no caller —
it was unreachable. These tests prove the tool is registered and drives
upload_dataset through the same FastMCP `call_tool` path real clients
hit, exercising the guard branches (missing local_dir / boto3 absent)
so a bad call returns a clean {ok: False, error: ...} rather than
raising.
"""
from __future__ import annotations

from typing import Any

from personal_brain.server import build_server
from personal_brain.storage import BrainStore
from personal_brain.cloud_archive import _is_boto3_available


def _call(mcp, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke an MCP tool via the in-house `call_tool` and unwrap the JSON
    payload (mirrors test_community_mcp_tools._call).

    InHouseMCP.call_tool is SYNCHRONOUS and returns the `tools/call` RESULT
    envelope as a plain dict ({"content": [...], "structuredContent": {...},
    "isError": bool}) — so we read the dict directly, preferring the
    structuredContent object and falling back to the text content block."""
    result = mcp.call_tool(name, arguments or {})
    return _unwrap(result)


def _unwrap(result: Any) -> dict[str, Any]:
    # In-house dict envelope (camelCase keys), with object-attribute fallbacks.
    sc = result.get("structuredContent") if isinstance(result, dict) \
        else getattr(result, "structured_content", None)
    if sc is not None:
        return sc
    data = result.get("data") if isinstance(result, dict) \
        else getattr(result, "data", None)
    if data is not None:
        return data
    content = result.get("content") if isinstance(result, dict) \
        else getattr(result, "content", None)
    if content:
        import json as _json
        for item in content:
            txt = item.get("text") if isinstance(item, dict) \
                else getattr(item, "text", None)
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


def test_cloud_archive_tool_is_registered(tmp_path):
    """The tool must be resolvable in the FastMCP tool registry under
    its public name (get_tool returns the Tool, or None if absent)."""
    mcp, store = _server(tmp_path)
    try:
        tool = mcp.get_tool("brain.cloud_archive")
        assert tool is not None, "brain.cloud_archive not registered"
        assert getattr(tool, "name", None) == "brain.cloud_archive"
    finally:
        store.close()


def test_cloud_archive_tool_missing_local_dir_returns_error(tmp_path):
    """A non-existent local_dir must return ok:False without crashing.

    When boto3 is absent the guard trips first (boto3 error); when it is
    present, the local_dir-not-found guard trips. Either way the call is
    a clean failure, never an exception."""
    mcp, store = _server(tmp_path)
    try:
        resp = _call(mcp, "brain.cloud_archive", {
            "local_dir": str(tmp_path / "does_not_exist"),
            "bucket": "any-bucket",
            "access_key_ref": "ak",
            "secret_key_ref": "sk",
        })
        assert resp["ok"] is False
        assert "error" in resp and resp["error"]
        if _is_boto3_available():
            assert "not found" in resp["error"].lower()
        else:
            assert "boto3" in resp["error"].lower()
    finally:
        store.close()


def test_cloud_archive_tool_boto3_absent_is_clean(tmp_path):
    """With boto3 absent (the typical test env) the tool surfaces the
    module's clean ok:False — not an exception."""
    if _is_boto3_available():
        import pytest
        pytest.skip("boto3 installed — boto3-absent branch covered when missing")
    mcp, store = _server(tmp_path)
    try:
        resp = _call(mcp, "brain.cloud_archive", {
            "local_dir": str(tmp_path),
            "bucket": "b",
            "access_key_ref": "x",
            "secret_key_ref": "y",
        })
        assert resp["ok"] is False
        assert "boto3" in resp["error"].lower()
    finally:
        store.close()
