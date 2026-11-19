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

from nodelang.hook_decision import draft_only
from nodelang.library_engines import library_catalogue
from nodelang.native_agent_mcp import build_server
from nodelang.native_host_tools import FOLDED_PROGRAMS, RESTORED_BROKERS, _program
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
    # R192: Revit and AutoCAD verbs are reached through <program>_search / <program>_run, not listed one by one.
    folded = [spec for spec in restored if _program(spec) in FOLDED_PROGRAMS]
    assert len(folded) > 50
    assert not [spec["id"] for spec in folded if spec["id"] in tools]
    for program in FOLDED_PROGRAMS:
        assert program + "_search" in tools and program + "_run" in tools
    for spec in restored:
        if spec in folded:
            continue
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

    from mcp.server.fastmcp.exceptions import ToolError

    async def call(name, arguments):
        try:
            return _payload(await server.call_tool(name, arguments))
        except ToolError as error:  # a host-effect permission refusal: refused before any engine
            return {"ok": False, "refused": str(error)}

    async def call_all():
        answers = []
        for spec in restored:
            if spec in folded:
                found = await call(_program(spec) + "_search", {"query": spec["id"]})
                assert spec["id"] in [row["tool"] for row in found["tools"]], spec["id"]
                answers.append((spec, await call(_program(spec) + "_run", {"tool": spec["id"]})))
            else:
                answers.append((spec, await call(spec["id"], {})))
        return answers

    # Never ran (the engines raise if touched): a read is refused by the decision; a write is held for Approve
    # ("Waiting for approval") or refused by the host-effect permission, both before any engine.
    outcomes = {}
    for spec, body in asyncio.run(call_all()):
        if body.get("gated") is True:
            assert body.get("verdict") == "refuse" and body.get("ok") is False, (spec["id"], body)
            outcomes[spec["id"]] = "refused"
        elif body.get("status") == "Waiting for approval":
            assert spec["kind"] != "read" and body.get("approvalId"), (spec["id"], body)
            outcomes[spec["id"]] = "held"
        elif draft_only(spec["id"]):
            # DRAFTNOASK: a draft in his own mailbox asks the one decision directly (no card, no host permission);
            # this court's decision refuses everything, so the draft is refused by its rule before any engine.
            assert spec["kind"] != "read" and body.get("refused", "").endswith("Refused: court"), (spec["id"], body)
            outcomes[spec["id"]] = "refused"
        else:
            assert spec["kind"] != "read" and "host effect permission" in body.get("refused", ""), (spec["id"], body)
            outcomes[spec["id"]] = "refused"
    assert sorted(outcomes) == sorted(spec["id"] for spec in restored)
    assert all(spec["kind"] != "read" or outcomes[spec["id"]] == "refused" for spec in restored)
    assert outcomes.get("b_set_parameter") in ("held", "refused")
    assert set(seen) <= {spec["id"] for spec in restored}
    assert "outlook.inbox" in ops or "outlook_inbox" in tools


def test_a_folded_write_through_revit_run_is_held_for_approve_not_run(monkeypatch):
    """R192: with Revit effects allowed, b_set_parameter via revit_run waits for Approve; no engine runs."""
    from nodelang import host_brokers
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    from nodelang.user_paths import state_directory

    def boom(*_args, **_kwargs):
        raise AssertionError("a broker engine ran before Approve")

    for name in list(host_brokers.ENGINES):
        monkeypatch.setitem(host_brokers.ENGINES, name, boom)
    for name in ("revit.read", "revit.verb", "autocad.verb"):
        if name in PIPELINE_ENGINES:
            monkeypatch.setitem(PIPELINE_ENGINES, name, boom)
    settings = state_directory() / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    before = settings.read_bytes() if settings.exists() else None
    settings.write_text(json.dumps({"host_effects": {"revit": True}}), encoding="utf-8")
    try:
        body = _payload(asyncio.run(build_server().call_tool("revit_run", {"tool": "b_set_parameter"})))
        assert body.get("status") == "Waiting for approval" and body.get("approvalId"), body
        from nodelang import hook_decision
        ran = []
        mock_verb = lambda params, _feeds=None: (ran.append(params) or {"ok": True}, "Done")
        monkeypatch.setitem(host_brokers.ENGINES, "revit.verb", mock_verb)
        monkeypatch.setitem(PIPELINE_ENGINES, "revit.verb", mock_verb)
        [card] = [c for c in hook_decision.ask_reviews() if c["id"] == body["approvalId"]]
        approved = hook_decision.ask_apply(card["id"], card["input_digest"], "approve")
        assert approved["status"] == "approved"
        assert len(ran) == 1 and ran[0].get("operation") == "revit.set_parameter_by_name"

        # Invalid argument type is rejected without creating an approval
        bad = _payload(asyncio.run(build_server().call_tool("revit_run", {"tool": "b_set_parameter", "arguments": {"elements": "bad"}})))
        assert bad.get("ok") is False and "must be list" in bad.get("error", "")
    finally:
        if before is None:
            settings.unlink()
        else:
            settings.write_bytes(before)


def test_an_outlook_draft_runs_without_approve_and_a_send_is_held_until_approved(monkeypatch):
    """DRAFTNOASK at the agent door, real decision, stubbed Outlook boundary: under Ask first a reply draft runs once
    with no card; the same draft aimed at a public target is held on one card, and only Approve sends it, once."""
    from nodelang import hook_decision, native_host_tools
    sent = []
    monkeypatch.setattr(native_host_tools, "_run_engine", lambda engine, params: sent.append((engine, params["to"])) or {"ok": True})
    folder = hook_decision._settings_dir(os.environ)
    folder.mkdir(parents=True, exist_ok=True)
    permissions = folder / "permissions.json"
    before = permissions.read_bytes() if permissions.exists() else None
    permissions.write_text(json.dumps({"runMode": "Ask first", "tools": {}}), encoding="utf-8")
    try:
        server = build_server(mailbox_call=lambda *args, **kwargs: {})
        draft = {"to": "client@example.com", "subject": "Re: sheets", "body": "Dear client", "reply_to": "msg-1"}
        cards = len(hook_decision.ask_reviews())
        assert _payload(asyncio.run(server.call_tool("outlook_reply_draft", draft))) == {"ok": True}
        assert sent == [("outlook.reply_draft", "client@example.com")] and len(hook_decision.ask_reviews()) == cards
        public = {**draft, "to": "https://example.com/p"}
        held = _payload(asyncio.run(server.call_tool("outlook_reply_draft", public)))
        assert held.get("status") == "Waiting for approval" and held.get("approvalId"), held
        assert len(sent) == 1, "a send never reaches Outlook before Approve"
        [card] = [c for c in hook_decision.ask_reviews() if c["id"] == held["approvalId"]]
        assert hook_decision.ask_apply(card["id"], card["input_digest"], "approve")["status"] == "approved"
        assert sent[1:] == [("outlook.reply_draft", "https://example.com/p")]
    finally:
        if before is None:
            permissions.unlink()
        else:
            permissions.write_bytes(before)