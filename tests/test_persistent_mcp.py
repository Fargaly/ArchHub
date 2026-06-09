"""Persistent-MCP selection logic (the chat-can't-touch-hosts fix, 2026-06-09).

The Claude-Code-CLI brain raced a COLD per-turn stdio MCP spawn (snapshotting 0
tools → fabricating host calls). The fix runs ONE persistent HTTP/SSE archhub MCP
the app starts on launch, and `claude_cli_client` points `--mcp-config` at the
ready SSE url WHEN it's up — falling back to the historical stdio spawn when it
isn't (zero regression).

These tests pin the SELECTION + FALLBACK: `_persistent_mcp_url` returns the url
iff something is serving on the port, and `_write_mcp_config` emits an `sse`
entry when up vs a stdio `command` entry when down. (The full end-to-end —
claude connecting + seeing 153 tools — is proven live; it needs the `claude` CLI
+ host auth, so it can't run headless in CI.)
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from llm_providers import claude_cli_client as c  # noqa: E402


def test_persistent_mcp_url_none_when_nothing_serving(monkeypatch):
    # A port nothing is listening on → no persistent server → None (→ stdio).
    monkeypatch.setattr(c, "_MCP_HTTP_PORT", 49321)
    assert c._persistent_mcp_url() is None


def test_persistent_mcp_url_when_serving(monkeypatch):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    monkeypatch.setattr(c, "_MCP_HTTP_PORT", port)
    try:
        assert c._persistent_mcp_url() == f"http://127.0.0.1:{port}/sse"
    finally:
        srv.close()


def _read_cfg(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_write_mcp_config_prefers_sse_when_serving(monkeypatch, tmp_path):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    monkeypatch.setattr(c, "_MCP_HTTP_PORT", port)
    monkeypatch.setattr(c.tempfile, "gettempdir", lambda: str(tmp_path))
    try:
        # call the method without running __init__ (which needs the claude CLI)
        path = c.ClaudeCliClient._write_mcp_config(object.__new__(c.ClaudeCliClient))
        cfg = _read_cfg(path)["mcpServers"]["archhub"]
        assert cfg.get("type") == "sse"
        assert cfg.get("url") == f"http://127.0.0.1:{port}/sse"
        assert "command" not in cfg          # NOT the stdio spawn
    finally:
        srv.close()


def test_write_mcp_config_falls_back_to_stdio_when_down(monkeypatch, tmp_path):
    monkeypatch.setattr(c, "_MCP_HTTP_PORT", 49322)   # nothing serving
    monkeypatch.setattr(c.tempfile, "gettempdir", lambda: str(tmp_path))
    # only meaningful if the stdio server file exists (it does in the repo)
    if not Path(c._MCP_SERVER).exists():
        return
    path = c.ClaudeCliClient._write_mcp_config(object.__new__(c.ClaudeCliClient))
    cfg = _read_cfg(path)["mcpServers"]["archhub"]
    assert "command" in cfg                  # historical stdio spawn (fallback)
    assert "type" not in cfg                 # NOT sse
