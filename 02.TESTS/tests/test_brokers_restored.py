"""Every restored broker is one catalogue card and one gated MCP tool.

Reads and writes stay on the existing engines. This court refuses the call
before any engine runs, so Revit, AutoCAD and Outlook are never touched.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="brokers-restored-"))
for _name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
    _path = _root / _name
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_name] = str(_path)

from nodelang.library_engines import library_catalogue
from nodelang.native_agent_mcp import build_server
from nodelang.native_host_tools import RESTORED_BROKERS
from nodelang.node_params import TYPES

_JSON_TYPE = {
    "text": "string", "file": "string", "path": "string",
    "integer": "integer", "number": "number", "bool": "boolean",
    "list": "array", "object": "object",
}
_BROUGHT_BACK = (
    "outlook.graph.status", "outlook.graph.inbox", "outlook.graph.categories",
    "outlook.graph.categorize", "outlook.imap.status", "outlook.imap.inbox",
    "outlook.imap.message", "outlook.search", "outlook.read_thread",
    "revit.list_walls", "revit.list_doors", "revit.set_parameter_by_name",
    "excel.list_workbooks", "excel.read_range", "notion.connect",
)


def _schema_type(prop):
    kind = prop.get("type")
    if kind:
        return kind
    for item in prop.get("anyOf") or ():
        if item.get("type") and item.get("type") != "null":
            return item["type"]
    return ""


def _payload(answer):
    if isinstance(answer, tuple):
        if len(answer) > 1 and isinstance(answer[1], dict):
            return answer[1]
        content = answer[0]
    else:
        content = answer
    if isinstance(content, dict):
        return content
    if isinstance(content, list) and content:
        text = getattr(content[0], "text", "")
        return json.loads(text) if text else {}
    text = getattr(content, "text", "")
    return json.loads(text) if text else {}


def test_restored_brokers_are_catalogue_cards_and_gated_mcp_tools(monkeypatch):
    """The inventory marked restored is in the one catalogue and the MCP door, typed, and refused before an engine."""
    restored = list(RESTORED_BROKERS)
    assert restored
    assert len({spec["id"] for spec in restored}) == len(restored)
    ops = {spec["op"] for spec in restored}
    missing = [op for op in _BROUGHT_BACK if op not in ops]
    assert missing == []
    assert "outlook.inbox" not in ops

    visible = {
        item["id"]: item
        for group in library_catalogue()
        for item in group["items"]
        if not item.get("hidden")
    }
    for spec in restored:
        card = visible[spec["id"]]
        definitions = {row["id"]: row for row in card.get("paramDefs") or []}
        for name, value in (card.get("params") or {}).items():
            definition = definitions[name]
            assert definition["type"] in TYPES, (spec["id"], name, definition["type"])
            if definition["type"] == "bool":
                assert type(value) is bool
            if definition["type"] in ("integer", "number"):
                assert isinstance(value, (int, float)) and not isinstance(value, bool)

    server = build_server()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    for spec in restored:
        tool = tools[spec["id"]]
        properties = (tool.parameters or {}).get("properties") or {}
        for name, kind in spec["types"].items():
            assert _schema_type(properties[name]) == _JSON_TYPE[kind], (spec["id"], name, properties[name])

    seen = []

    def refuse(payload, vendor="", environment=None):
        seen.append(payload.get("tool_name"))
        return {"verdict": "refuse", "action": "read", "rules": ["court"], "notes": [],
                "findings": [], "scanners": {}, "mode": "court"}

    def boom(*_args, **_kwargs):
        raise AssertionError("a broker engine ran after a refusal")

    monkeypatch.setattr("nodelang.hook_decision.decide", refuse)
    from nodelang import host_brokers
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    for name in list(host_brokers.ENGINES):
        monkeypatch.setitem(host_brokers.ENGINES, name, boom)
    for name in ("revit.read", "revit.verb", "autocad.verb", "office.read"):
        if name in PIPELINE_ENGINES:
            monkeypatch.setitem(PIPELINE_ENGINES, name, boom)

    async def call_all():
        answers = []
        for spec in restored:
            answers.append((spec["id"], await server.call_tool(spec["id"], {})))
        return answers

    for tool_id, answer in asyncio.run(call_all()):
        body = _payload(answer)
        assert body.get("gated") is True, (tool_id, body)
        assert body.get("verdict") == "refuse"
        assert body.get("ok") is False
    assert seen == [spec["id"] for spec in restored]
    assert "outlook.inbox" in ops or "outlook_inbox" in tools
