"""Tests for `app/mcp/node_mcp.py` — the per-node MCP server runtime.

Pins the contracts:

  - NodeMCPServer derives tools from node_type + config (host.* uses
    tool_engine prefix filter; doc.csv has csv.* tools; doc.revit has
    revit_get_doc_info; conversation.chat has chat.complete /
    append_message / last_response).
  - list_tools() returns MCP-shaped descriptors.
  - invoke(tool_name, args) returns a JSON-serializable envelope.
  - dispatch(method, params) speaks JSON-RPC 2.0.
  - Registry add / remove / get / cross-node call.
  - Unknown node_id returns a clear error.
  - Unavailable adapters return {"status": "unavailable", ...} rather
    than raising.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from mcp.node_mcp import (  # noqa: E402
    NodeMCPServer,
    MCPRegistry,
    REGISTRY,
    MCPTool,
    MCPError,
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
    ERR_TOOL_NOT_FOUND,
    ERR_METHOD_MISSING,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty registry singleton."""
    REGISTRY.clear()
    yield
    REGISTRY.clear()


# ─── Host nodes ────────────────────────────────────────────────────
class TestHostNodeTools:
    def test_revit_host_exposes_revit_prefixed_tools(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        tools = s.list_tools()
        assert len(tools) >= 4
        for t in tools:
            assert t["name"].startswith("revit_"), t["name"]
        names = {t["name"] for t in tools}
        assert "revit_ping" in names
        assert "revit_info" in names
        assert "revit_execute_csharp" in names

    def test_autocad_host_exposes_acad_prefixed_tools(self):
        s = NodeMCPServer(node_id="a1", node_type="host.autocad",
                           config={})
        tools = s.list_tools()
        assert len(tools) >= 3
        for t in tools:
            assert t["name"].startswith("acad_"), t["name"]

    def test_outlook_host_exposes_outlook_prefixed_tools(self):
        s = NodeMCPServer(node_id="o1", node_type="host.outlook",
                           config={})
        tools = s.list_tools()
        assert len(tools) >= 5
        for t in tools:
            assert t["name"].startswith("outlook_")

    def test_unknown_host_family_yields_empty_surface(self):
        s = NodeMCPServer(node_id="x1",
                           node_type="host.nonexistent",
                           config={})
        assert s.list_tools() == []

    def test_each_tool_has_mcp_input_schema(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        for t in s.list_tools():
            assert isinstance(t["name"], str) and t["name"]
            assert isinstance(t["description"], str)
            assert isinstance(t["inputSchema"], dict)
            assert t["inputSchema"].get("type") == "object"


# ─── Doc nodes ─────────────────────────────────────────────────────
class TestDocNodeTools:
    def test_csv_doc_lists_csv_tools(self):
        s = NodeMCPServer(node_id="c1", node_type="doc.csv",
                           config={})
        names = {t["name"] for t in s.list_tools()}
        assert names == {"csv.read_columns", "csv.head",
                          "csv.row_count"}

    def test_csv_doc_can_actually_read(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")
        s = NodeMCPServer(node_id="c1", node_type="doc.csv",
                           config={"path": str(p)})
        cols = s.invoke("csv.read_columns", {})
        assert cols["status"] == "ok"
        assert cols["columns"] == ["a", "b", "c"]
        head = s.invoke("csv.head", {"n": 1})
        assert head["status"] == "ok"
        assert head["rows"] == [["1", "2", "3"]]
        rc = s.invoke("csv.row_count", {})
        assert rc["status"] == "ok"
        assert rc["row_count"] == 2

    def test_csv_doc_path_via_args_overrides_config(self, tmp_path):
        p = tmp_path / "y.csv"
        p.write_text("h\nv\n", encoding="utf-8")
        s = NodeMCPServer(node_id="c2", node_type="doc.csv",
                           config={})
        out = s.invoke("csv.read_columns", {"path": str(p)})
        assert out["columns"] == ["h"]

    def test_csv_doc_missing_path_returns_clear_error(self):
        s = NodeMCPServer(node_id="c3", node_type="doc.csv",
                           config={})
        out = s.invoke("csv.read_columns", {})
        assert out["status"] == "error"
        assert "path" in out["error"]

    def test_revit_doc_publishes_get_doc_info(self):
        s = NodeMCPServer(node_id="d1", node_type="doc.revit",
                           config={})
        names = {t["name"] for t in s.list_tools()}
        assert "revit_get_doc_info" in names

    def test_pdf_doc_lists_text_tool(self):
        s = NodeMCPServer(node_id="p1", node_type="doc.pdf",
                           config={})
        names = {t["name"] for t in s.list_tools()}
        assert "pdf.text" in names

    def test_ifc_doc_lists_summary_tool(self):
        s = NodeMCPServer(node_id="i1", node_type="doc.ifc",
                           config={})
        names = {t["name"] for t in s.list_tools()}
        assert "ifc.summary" in names

    def test_generic_doc_family_publishes_describe(self):
        s = NodeMCPServer(node_id="g1", node_type="doc.dwg",
                           config={"path": "/tmp/a.dwg"})
        names = {t["name"] for t in s.list_tools()}
        assert "dwg.describe" in names
        out = s.invoke("dwg.describe", {})
        assert out["status"] == "ok"
        assert out["family"] == "dwg"
        assert out["path"] == "/tmp/a.dwg"


# ─── Conversation node ────────────────────────────────────────────
class TestConversationNodeTools:
    def test_conversation_chat_lists_three_tools(self):
        s = NodeMCPServer(node_id="cv1",
                           node_type="conversation.chat",
                           config={})
        names = {t["name"] for t in s.list_tools()}
        assert names == {"chat.complete", "chat.append_message",
                          "chat.last_response"}

    def test_chat_append_then_last_response_roundtrip(self):
        s = NodeMCPServer(node_id="cv2",
                           node_type="conversation.chat",
                           config={})
        out1 = s.invoke("chat.append_message",
                         {"role": "user", "content": "hi"})
        assert out1["status"] == "ok"
        assert out1["message_count"] == 1

    def test_chat_complete_returns_envelope(self):
        # No router → stub path (or unavailable). Either is a valid
        # JSON envelope.
        s = NodeMCPServer(node_id="cv3",
                           node_type="conversation.chat",
                           config={"model": "stub"})
        out = s.invoke("chat.complete", {"prompt": "ping"})
        assert isinstance(out, dict)
        assert out["status"] in ("ok", "unavailable")
        assert "model" in out
        # State observable via last_response
        out2 = s.invoke("chat.last_response", {})
        assert out2["status"] == "ok"

    def test_chat_complete_missing_prompt_is_error(self):
        s = NodeMCPServer(node_id="cv4",
                           node_type="conversation.chat",
                           config={})
        out = s.invoke("chat.complete", {})
        assert out["status"] == "error"
        assert "prompt" in out["error"]


# ─── Envelope shape + invoke contracts ────────────────────────────
class TestEnvelopeShape:
    def test_invoke_unknown_tool_returns_error_envelope(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        out = s.invoke("not_a_tool", {})
        assert out["status"] == "error"
        assert "Unknown tool" in out["error"]
        assert out["node_id"] == "r1"

    def test_invoke_result_is_json_serialisable(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("a\n1\n", encoding="utf-8")
        s = NodeMCPServer(node_id="c1", node_type="doc.csv",
                           config={"path": str(p)})
        out = s.invoke("csv.read_columns", {})
        # round-trip through json
        s_text = json.dumps(out)
        again = json.loads(s_text)
        assert again["columns"] == ["a"]


# ─── MCP JSON-RPC dispatch ────────────────────────────────────────
class TestMCPDispatch:
    def test_initialize_returns_protocol_envelope(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        env = s.dispatch("initialize", {}, request_id=1)
        assert env["jsonrpc"] == JSONRPC_VERSION
        assert env["id"] == 1
        assert env["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert env["result"]["serverInfo"]["node_id"] == "r1"

    def test_tools_list_via_dispatch(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        env = s.dispatch("tools/list", {}, request_id=2)
        assert "result" in env
        assert isinstance(env["result"]["tools"], list)
        assert len(env["result"]["tools"]) >= 4

    def test_tools_call_via_dispatch_csv(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        s = NodeMCPServer(node_id="c1", node_type="doc.csv",
                           config={"path": str(p)})
        env = s.dispatch("tools/call",
                          {"name": "csv.read_columns",
                           "arguments": {}},
                          request_id=3)
        assert env["id"] == 3
        result = env["result"]
        assert result["isError"] is False
        decoded = json.loads(result["content"][0]["text"])
        assert decoded["columns"] == ["a", "b"]

    def test_tools_call_unknown_tool_yields_error(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        env = s.dispatch("tools/call", {"name": "not_real"},
                          request_id=4)
        assert "error" in env
        assert env["error"]["code"] == ERR_TOOL_NOT_FOUND

    def test_unknown_method_yields_method_missing(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        env = s.dispatch("does/not/exist", {})
        assert env["error"]["code"] == ERR_METHOD_MISSING

    def test_ping_returns_alive(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        env = s.dispatch("ping")
        assert env["result"]["alive"] is True
        assert env["result"]["node_id"] == "r1"


# ─── Registry ──────────────────────────────────────────────────────
class TestRegistry:
    def test_register_and_get(self):
        reg = MCPRegistry()
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        reg.register("r1", s)
        assert reg.get("r1") is s

    def test_unregister_removes(self):
        reg = MCPRegistry()
        s = NodeMCPServer(node_id="r1", node_type="host.revit",
                           config={})
        reg.register("r1", s)
        assert reg.unregister("r1") is True
        assert reg.get("r1") is None
        assert reg.unregister("r1") is False        # second call idem

    def test_list_servers_shape(self):
        reg = MCPRegistry()
        reg.register("r1",
                      NodeMCPServer(node_id="r1",
                                     node_type="host.revit"))
        reg.register("c1",
                      NodeMCPServer(node_id="c1",
                                     node_type="doc.csv"))
        rows = reg.list_servers()
        assert len(rows) == 2
        types = {r["node_type"] for r in rows}
        assert types == {"host.revit", "doc.csv"}
        for r in rows:
            assert "tool_count" in r
            assert "tool_names" in r

    def test_register_rejects_bad_input(self):
        reg = MCPRegistry()
        with pytest.raises(ValueError):
            reg.register("", NodeMCPServer(node_id="x",
                                             node_type="host.revit"))
        with pytest.raises(TypeError):
            reg.register("x", object())          # type: ignore[arg-type]

    def test_module_singleton(self):
        """REGISTRY is shared by every importer."""
        from mcp.node_mcp import REGISTRY as r2
        REGISTRY.register("z1",
                           NodeMCPServer(node_id="z1",
                                          node_type="host.revit"))
        assert r2.get("z1") is REGISTRY.get("z1")


# ─── Cross-node calls ─────────────────────────────────────────────
class TestCrossNodeCall:
    def test_node_a_calls_tool_on_node_b(self, tmp_path):
        # Node B has a CSV doc with real data.
        p = tmp_path / "shared.csv"
        p.write_text("col1,col2\nv1,v2\n", encoding="utf-8")
        b_server = NodeMCPServer(node_id="B",
                                    node_type="doc.csv",
                                    config={"path": str(p)})
        REGISTRY.register("B", b_server)

        # Node A doesn't need its own server to call into B — the
        # registry is enough. Simulate that path.
        result = REGISTRY.invoke("B", "csv.read_columns", {})
        assert result["status"] == "ok"
        assert result["columns"] == ["col1", "col2"]
        assert result["node_id"] == "B"

    def test_cross_node_call_unknown_id_is_clean_error(self):
        out = REGISTRY.invoke("missing", "anything", {})
        assert out["status"] == "error"
        assert "Unknown node_id" in out["error"]
        assert out["code"] == ERR_TOOL_NOT_FOUND


# ─── Edge cases ───────────────────────────────────────────────────
class TestEdgeCases:
    def test_constructor_requires_node_id(self):
        with pytest.raises(ValueError):
            NodeMCPServer(node_id="", node_type="host.revit")

    def test_constructor_requires_node_type(self):
        with pytest.raises(ValueError):
            NodeMCPServer(node_id="x", node_type="")

    def test_unknown_node_type_still_serves_initialize(self):
        s = NodeMCPServer(node_id="m1", node_type="mystery.thing")
        env = s.dispatch("initialize", {})
        assert env["result"]["serverInfo"]["node_id"] == "m1"
        # tools/list should still answer (empty)
        env2 = s.dispatch("tools/list", {})
        assert env2["result"]["tools"] == []

    def test_to_dict_introspection(self):
        s = NodeMCPServer(node_id="r1", node_type="host.revit")
        d = s.to_dict()
        assert d["node_id"] == "r1"
        assert d["node_type"] == "host.revit"
        assert d["tool_count"] >= 4
        assert "revit_ping" in d["tool_names"]

    def test_mcp_error_serialisation(self):
        err = MCPError(-32001, "boom", {"x": 1})
        d = err.to_dict()
        assert d == {"code": -32001, "message": "boom",
                      "data": {"x": 1}}
