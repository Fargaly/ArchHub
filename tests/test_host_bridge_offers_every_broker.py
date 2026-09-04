"""The agent bridge (archhub-hosts MCP) offers every broker the app has."""
from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "payload" / "bridge" / "server.py"


def test_bridge_tools_cover_every_host():
    src = SERVER.read_text(encoding="utf-8")
    tools = set(re.findall(r"@mcp\.tool\(\)\s*\ndef (\w+)\(", src))
    for name in ("revit_ping", "revit_execute_csharp", "acad_ping", "acad_execute_csharp", "max_ping", "max_execute_maxscript",
                 "blender_ping", "blender_execute_python", "rhino_ping", "rhino_execute_python", "office_read",
                 "outlook_inbox", "notion_search", "dropbox_list", "hosts_state"):
        assert name in tools, name
    assert "nodelang import host_brokers" in src, "one broker implementation for the app and every agent"
