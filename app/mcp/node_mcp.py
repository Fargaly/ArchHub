"""Node-as-MCP-server runtime.

ArchHub canvas treats every node as if it spins up its own MCP server.
Each instance owns:

  - a unique `node_id`,
  - a `node_type` (host.revit, doc.csv, conversation.chat, ...),
  - a `config` dict (the same dict the graph editor stores per node),
  - a derived tool surface advertised through MCP messages.

Tools are NOT redefined here. They are pulled from existing sources:

  - host.<family>   → filtered subset of `tool_engine.TOOLS` whose name
                       starts with the family prefix (host.revit → tools
                       beginning with "revit_"; host.autocad → "acad_";
                       host.max → "max_"; host.blender → "blender_";
                       host.rhino → "rhino_"; host.speckle → "speckle_";
                       host.outlook → "outlook_").
  - doc.<family>    → doc-family adapter tools (csv.read_columns,
                       csv.head, csv.row_count, pdf.text, ifc.summary,
                       revit_get_doc_info, ...).
  - conversation.chat → chat.complete, chat.append_message,
                         chat.last_response.

Other nodes / agents call across nodes via `REGISTRY.get(node_id)`
followed by `server.dispatch(method, params)` — pure in-process JSON-RPC
2.0. External agents reach the same surface via QWebChannel bridge slots
on `ArchHubBridge` (see `app/bridge.py`).

This module is intentionally stdlib-only (json, dataclasses, typing). No
sockets, no fastmcp, no third-party JSON-RPC libs. The reasoning is
pragmatic: ArchHub is a desktop app, every node lives in the same Python
process, and the JS canvas already has a typed bridge — message-routing
overhead is a liability, not a feature.

Envelope shape (returned by dispatch and invoke):

    {
        "jsonrpc": "2.0",
        "id":      <int|str|None>,
        "result":  {...}              # on success
    }

    {
        "jsonrpc": "2.0",
        "id":      <int|str|None>,
        "error":   {"code": int, "message": str, "data": {...}}
    }

Tool-call results follow MCP's `tools/call` shape:

    {"content": [{"type": "text", "text": "<json-encoded result>"}],
     "isError": false}

Unavailable adapters never crash dispatch — they return
{"status": "unavailable", "reason": "..."} inside the result envelope so
upstream UI can show a clear hint instead of a stack trace.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─── Constants ──────────────────────────────────────────────────────
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-06-18"           # spec rev currently shipping

# JSON-RPC reserved error codes (subset we use)
ERR_PARSE          = -32700
ERR_INVALID_REQ    = -32600
ERR_METHOD_MISSING = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL       = -32603
# MCP-specific (impl-defined range -32000..-32099)
ERR_TOOL_NOT_FOUND = -32001
ERR_UNAVAILABLE    = -32002


# ─── Family → tool-prefix map for host.* nodes ──────────────────────
# host.<family> publishes tool_engine.TOOLS where name startswith prefix
_HOST_TOOL_PREFIX = {
    "revit":    ("revit_",),
    "autocad":  ("acad_",),
    "max":      ("max_",),
    "blender":  ("blender_",),
    "rhino":    ("rhino_",),
    "speckle":  ("speckle_",),
    "outlook":  ("outlook_",),
}


# ─── Errors ─────────────────────────────────────────────────────────
class MCPError(Exception):
    """Carries a JSON-RPC error envelope. Caught at the dispatch
    boundary and surfaced as `{"error": {...}}`."""

    def __init__(self, code: int, message: str, data: Optional[dict] = None):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = dict(data) if data else None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


# ─── Tool descriptor (MCP-shaped) ───────────────────────────────────
@dataclass
class MCPTool:
    """One tool the node exposes."""
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Any] = field(repr=False)

    def to_mcp(self) -> dict:
        """Serialise to MCP `tools/list` shape."""
        return {
            "name":        self.name,
            "description": self.description,
            "inputSchema": dict(self.input_schema or {"type": "object",
                                                       "properties": {}}),
        }


# ─── NodeMCPServer ──────────────────────────────────────────────────
class NodeMCPServer:
    """One MCP server backing one node.

    The tool surface is derived from `node_type` + `config` at __init__
    time. Calling `list_tools()` returns the JSON-schema'd tool defs;
    `invoke(tool_name, args)` dispatches to the underlying executor.

    Any node type unknown to the derivation rules still produces a
    valid server with an empty tool list — invoke() will reject calls
    with ERR_TOOL_NOT_FOUND, list_tools() returns [], dispatch() still
    answers initialize / tools/list properly. This keeps the canvas
    safe against typos and future node families.
    """

    def __init__(self, *, node_id: str, node_type: str,
                 config: Optional[dict] = None,
                 display_name: Optional[str] = None):
        if not node_id:
            raise ValueError("node_id is required")
        if not node_type:
            raise ValueError("node_type is required")
        self.node_id = str(node_id)
        self.node_type = str(node_type)
        self.config = dict(config or {})
        self.display_name = str(display_name or node_type)
        self._tools: list[MCPTool] = []
        self._build_tool_surface()

    # ── public API ────────────────────────────────────────────────
    def list_tools(self) -> list[dict]:
        """Return MCP-shaped tool defs (name, description, inputSchema)."""
        return [t.to_mcp() for t in self._tools]

    def invoke(self, tool_name: str, args: Optional[dict] = None) -> dict:
        """Invoke one tool by name. Returns a JSON-serialisable result
        envelope. Unknown tools return {"status": "error", ...}; the
        same call via dispatch() raises ERR_TOOL_NOT_FOUND."""
        args = dict(args or {})
        tool = next((t for t in self._tools if t.name == tool_name), None)
        if tool is None:
            return {
                "status":  "error",
                "error":   f"Unknown tool: {tool_name}",
                "node_id": self.node_id,
            }
        try:
            raw = tool.handler(args)
        except MCPError as ex:
            return {"status": "error", "error": ex.message,
                    "code":   ex.code, "data": ex.data,
                    "node_id": self.node_id}
        except Exception as ex:
            return {"status": "error",
                    "error":  f"{type(ex).__name__}: {ex}",
                    "node_id": self.node_id}
        # Coerce non-dict returns into a value envelope so the JSON
        # contract is uniform.
        if isinstance(raw, dict):
            out = dict(raw)
        else:
            out = {"status": "ok", "value": raw}
        out.setdefault("status", "ok")
        out.setdefault("node_id", self.node_id)
        out.setdefault("tool_name", tool_name)
        return out

    # ── MCP message dispatch (JSON-RPC 2.0) ───────────────────────
    def dispatch(self, method: str, params: Optional[dict] = None,
                  *, request_id: Any = None) -> dict:
        """Handle one MCP method call. Always returns a JSON-RPC 2.0
        envelope (`result` on success, `error` on failure)."""
        try:
            if method == "initialize":
                result = self._handle_initialize(params or {})
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                result = self._handle_tools_call(params or {})
            elif method == "ping":
                result = {"alive": True, "node_id": self.node_id,
                           "node_type": self.node_type}
            else:
                raise MCPError(ERR_METHOD_MISSING,
                                f"Method not supported: {method}")
            return {"jsonrpc": JSONRPC_VERSION, "id": request_id,
                    "result": result}
        except MCPError as ex:
            return {"jsonrpc": JSONRPC_VERSION, "id": request_id,
                    "error":   ex.to_dict()}
        except Exception as ex:
            return {"jsonrpc": JSONRPC_VERSION, "id": request_id,
                    "error":   MCPError(
                                ERR_INTERNAL,
                                f"{type(ex).__name__}: {ex}",
                              ).to_dict()}

    # ── MCP method handlers ───────────────────────────────────────
    def _handle_initialize(self, params: dict) -> dict:
        """Mirror MCP `initialize` response. Reports protocol version
        + capabilities + this node's server info."""
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities":    {"tools": {"listChanged": False}},
            "serverInfo":      {
                "name":         f"archhub-node:{self.node_type}",
                "node_id":      self.node_id,
                "display_name": self.display_name,
                "version":      "1.0.0",
            },
        }

    def _handle_tools_call(self, params: dict) -> dict:
        """Handle MCP `tools/call`: dispatch and wrap into MCP's
        `content` list. `isError` reflects the tool's status."""
        name = params.get("name") or ""
        if not isinstance(name, str) or not name:
            raise MCPError(ERR_INVALID_PARAMS,
                            "tools/call requires `name`")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise MCPError(ERR_INVALID_PARAMS,
                            "tools/call `arguments` must be an object")
        tool = next((t for t in self._tools if t.name == name), None)
        if tool is None:
            raise MCPError(ERR_TOOL_NOT_FOUND,
                            f"Unknown tool: {name}",
                            {"node_id": self.node_id,
                             "available": [t.name for t in self._tools]})
        result_envelope = self.invoke(name, args)
        is_error = (result_envelope.get("status") == "error")
        text = json.dumps(result_envelope, default=str, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": bool(is_error),
        }

    # ── Tool-surface derivation ───────────────────────────────────
    def _build_tool_surface(self) -> None:
        """Populate self._tools based on node_type. Pure dispatch —
        no side effects on tool_engine."""
        ntype = self.node_type
        if ntype.startswith("host."):
            family = ntype.split(".", 1)[1]
            self._tools = _build_host_tools(family, self.config,
                                              self.node_id)
        elif ntype.startswith("doc."):
            family = ntype.split(".", 1)[1]
            self._tools = _build_doc_tools(family, self.config,
                                             self.node_id)
        elif ntype == "conversation.chat":
            self._tools = _build_conversation_tools(self.config,
                                                     self.node_id)
        else:
            self._tools = []

    # ── Introspection helpers ─────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "node_id":      self.node_id,
            "node_type":    self.node_type,
            "display_name": self.display_name,
            "tool_count":   len(self._tools),
            "tool_names":   [t.name for t in self._tools],
        }


# ─── Host.* tool derivation ─────────────────────────────────────────
def _build_host_tools(family: str, config: dict,
                       node_id: str) -> list[MCPTool]:
    """Filter tool_engine.TOOLS by host family. Each tool's handler
    re-invokes the existing ToolEngine if one can be constructed —
    otherwise it returns {"status": "unavailable", "reason": ...}
    so the node remains useful at edit time even when the host or
    tool engine isn't wired up yet."""
    prefixes = _HOST_TOOL_PREFIX.get(family, ())
    if not prefixes:
        return []
    try:
        from tool_engine import TOOLS as _TOOLS   # late import
    except Exception:
        return []
    out: list[MCPTool] = []
    for spec in _TOOLS:
        name = spec.get("name") or ""
        if not any(name.startswith(p) for p in prefixes):
            continue

        # Closure-bind the spec so each handler refers to its own.
        def _make_handler(_spec):
            tool_name = _spec["name"]

            def _handler(args: dict) -> dict:
                try:
                    from tool_engine import ToolEngine    # late import
                    from manager import ConnectorManager  # late import
                except Exception as ex:
                    return {"status": "unavailable",
                            "reason": f"tool_engine unavailable: {ex}"}
                try:
                    mgr = ConnectorManager()
                    engine = ToolEngine(mgr)
                except Exception as ex:
                    return {"status": "unavailable",
                            "reason": f"engine init failed: {ex}"}
                try:
                    res = engine.invoke(
                        tool_name=tool_name,
                        args=dict(args or {}),
                        session_pin=config.get("session_pin"),
                        user_confirmed=bool(config.get("user_confirmed",
                                                         False)),
                    )
                except Exception as ex:
                    return {"status": "error",
                            "error":  f"{type(ex).__name__}: {ex}"}
                return res if isinstance(res, dict) else {
                    "status": "ok", "value": res}

            return _handler

        out.append(MCPTool(
            name=name,
            description=spec.get("description") or "",
            input_schema=dict(spec.get("input_schema") or {}),
            handler=_make_handler(spec),
        ))
    return out


# ─── Doc.* tool derivation ──────────────────────────────────────────
def _doc_csv_tools(config: dict, node_id: str) -> list[MCPTool]:
    """CSV doc tools: read_columns, head, row_count.

    Reads via stdlib `csv`. Path comes from config['path']."""
    def _resolve_path(args: dict) -> Optional[str]:
        return (args.get("path")
                or config.get("path")
                or "").strip() or None

    def _load_rows(path: str) -> tuple[list[str], list[list[str]]]:
        import csv as _csv
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            raise MCPError(ERR_INVALID_PARAMS,
                            f"CSV not found: {path}")
        try:
            with p.open("r", encoding="utf-8", newline="") as fh:
                rows_all = list(_csv.reader(fh))
        except UnicodeDecodeError:
            with p.open("r", encoding="latin-1", newline="") as fh:
                rows_all = list(_csv.reader(fh))
        if not rows_all:
            return [], []
        return rows_all[0], rows_all[1:]

    def _read_columns(args: dict) -> dict:
        path = _resolve_path(args)
        if not path:
            return {"status": "error", "error": "path is required"}
        try:
            columns, _rows = _load_rows(path)
        except MCPError as ex:
            return {"status": "error", "error": ex.message}
        return {"status": "ok", "path": path, "columns": columns}

    def _head(args: dict) -> dict:
        path = _resolve_path(args)
        if not path:
            return {"status": "error", "error": "path is required"}
        n = int(args.get("n") or 5)
        try:
            columns, data = _load_rows(path)
        except MCPError as ex:
            return {"status": "error", "error": ex.message}
        return {"status": "ok", "path": path,
                "columns": columns, "rows": data[:max(0, n)],
                "row_count": len(data)}

    def _row_count(args: dict) -> dict:
        path = _resolve_path(args)
        if not path:
            return {"status": "error", "error": "path is required"}
        try:
            _columns, data = _load_rows(path)
        except MCPError as ex:
            return {"status": "error", "error": ex.message}
        return {"status": "ok", "path": path, "row_count": len(data)}

    str_schema = {"type": "object",
                  "properties": {"path": {"type": "string"}},
                  "required": []}
    head_schema = {"type": "object",
                    "properties": {"path": {"type": "string"},
                                    "n": {"type": "integer",
                                           "default": 5}},
                    "required": []}
    return [
        MCPTool("csv.read_columns",
                 "Read a CSV header row. Returns the column names.",
                 str_schema, _read_columns),
        MCPTool("csv.head",
                 "Return the first N rows of a CSV (default 5).",
                 head_schema, _head),
        MCPTool("csv.row_count",
                 "Count data rows (header excluded).",
                 str_schema, _row_count),
    ]


def _doc_revit_tools(config: dict, node_id: str) -> list[MCPTool]:
    """Revit doc tools: re-export the small introspection slice of
    tool_engine that's truly read-only — ping, info — plus a thin
    `revit_get_doc_info` wrapper aliased onto the existing
    `revit_info` endpoint."""
    try:
        from tool_engine import TOOLS as _TOOLS
    except Exception:
        return []

    def _make_handler(spec):
        tool_name = spec["name"]

        def _handler(args: dict) -> dict:
            try:
                from tool_engine import ToolEngine
                from manager import ConnectorManager
            except Exception as ex:
                return {"status": "unavailable",
                        "reason": f"tool_engine unavailable: {ex}"}
            try:
                engine = ToolEngine(ConnectorManager())
                return engine.invoke(tool_name, dict(args or {}),
                                       session_pin=config.get(
                                           "session_pin"),
                                       user_confirmed=True)
            except Exception as ex:
                return {"status": "error",
                        "error":  f"{type(ex).__name__}: {ex}"}

        return _handler

    out: list[MCPTool] = []
    info_spec = next((s for s in _TOOLS
                       if s.get("name") == "revit_info"), None)
    if info_spec is not None:
        out.append(MCPTool(
            "revit_get_doc_info",
            "Return open Revit document info: title, path, units, "
            "active view, version.",
            dict(info_spec.get("input_schema") or {}),
            _make_handler(info_spec),
        ))
        out.append(MCPTool(
            info_spec["name"],
            info_spec.get("description") or "",
            dict(info_spec.get("input_schema") or {}),
            _make_handler(info_spec),
        ))
    ping_spec = next((s for s in _TOOLS
                       if s.get("name") == "revit_ping"), None)
    if ping_spec is not None:
        out.append(MCPTool(
            ping_spec["name"],
            ping_spec.get("description") or "",
            dict(ping_spec.get("input_schema") or {}),
            _make_handler(ping_spec),
        ))
    return out


def _doc_pdf_tools(config: dict, node_id: str) -> list[MCPTool]:
    """PDF doc tools: text extraction via optional pypdf."""
    def _resolve_path(args: dict) -> Optional[str]:
        return (args.get("path") or config.get("path")
                or "").strip() or None

    def _pdf_text(args: dict) -> dict:
        path = _resolve_path(args)
        if not path:
            return {"status": "error", "error": "path is required"}
        try:
            import pypdf   # type: ignore
        except Exception:
            return {"status": "unavailable",
                    "reason": "pypdf not installed",
                    "hint":   "pip install pypdf"}
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            return {"status": "error",
                    "error":  f"file not found: {path}"}
        try:
            reader = pypdf.PdfReader(str(p))
            pages = []
            for i, page in enumerate(reader.pages):
                if i >= 50:
                    break
                pages.append(page.extract_text() or "")
        except Exception as ex:
            return {"status": "error",
                    "error":  f"{type(ex).__name__}: {ex}"}
        return {"status": "ok", "path": path,
                "page_count": len(reader.pages),
                "text":       "\n\n".join(pages)[:200_000]}

    schema = {"type": "object",
              "properties": {"path": {"type": "string"}},
              "required": []}
    return [
        MCPTool("pdf.text",
                 "Extract text from a PDF (first 50 pages).",
                 schema, _pdf_text),
    ]


def _doc_ifc_tools(config: dict, node_id: str) -> list[MCPTool]:
    """IFC doc tools: summary via optional ifcopenshell."""
    def _resolve_path(args: dict) -> Optional[str]:
        return (args.get("path") or config.get("path")
                or "").strip() or None

    def _ifc_summary(args: dict) -> dict:
        path = _resolve_path(args)
        if not path:
            return {"status": "error", "error": "path is required"}
        try:
            import ifcopenshell   # type: ignore
        except Exception:
            return {"status": "unavailable",
                    "reason": "ifcopenshell not installed",
                    "hint":   "pip install ifcopenshell"}
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            return {"status": "error",
                    "error":  f"file not found: {path}"}
        try:
            f = ifcopenshell.open(str(p))
            elt_types = ("IfcWall", "IfcDoor", "IfcWindow", "IfcSlab",
                         "IfcColumn", "IfcBeam", "IfcSpace", "IfcStair")
            counts = {t: len(f.by_type(t)) for t in elt_types}
        except Exception as ex:
            return {"status": "error",
                    "error":  f"{type(ex).__name__}: {ex}"}
        return {"status": "ok", "path": path,
                "schema": getattr(f, "schema", ""),
                "element_counts": counts,
                "total_elements": sum(counts.values())}

    schema = {"type": "object",
              "properties": {"path": {"type": "string"}},
              "required": []}
    return [
        MCPTool("ifc.summary",
                 "Read an IFC file. Returns schema + element counts.",
                 schema, _ifc_summary),
    ]


def _doc_generic_tools(family: str, config: dict,
                        node_id: str) -> list[MCPTool]:
    """Fallback for doc families with no rich adapter — return a
    single `doc.describe` tool so the node has *something* to publish.
    Keeps the canvas honest: every doc node is an MCP server, even
    when the underlying parser isn't ready yet."""
    def _describe(_args: dict) -> dict:
        return {"status": "ok", "family": family,
                "path":   config.get("path") or "",
                "version": config.get("version") or "",
                "note":   f"No rich parser registered for doc.{family}; "
                          f"node still publishes metadata."}

    return [MCPTool(
        f"{family}.describe",
        f"Return metadata for the doc.{family} node (no parser).",
        {"type": "object", "properties": {}, "required": []},
        _describe,
    )]


def _build_doc_tools(family: str, config: dict,
                      node_id: str) -> list[MCPTool]:
    if family == "csv":
        return _doc_csv_tools(config, node_id)
    if family == "revit":
        return _doc_revit_tools(config, node_id)
    if family == "pdf":
        return _doc_pdf_tools(config, node_id)
    if family == "ifc":
        return _doc_ifc_tools(config, node_id)
    # dwg, blender, 3dm, max → publish a describe stub so the node
    # is still a real MCP server (founder direction: every node).
    return _doc_generic_tools(family, config, node_id)


# ─── conversation.chat tool derivation ──────────────────────────────
def _build_conversation_tools(config: dict,
                                node_id: str) -> list[MCPTool]:
    """In-memory chat tools. State lives on a dict captured by closure,
    so subsequent calls observe one another. This is sufficient for
    the in-process MCP model — a future remote MCP can swap this for
    a real backing store."""
    state: dict[str, Any] = {
        "messages": list(config.get("body", {}).get("messages") or []),
        "last_response": "",
        "model": config.get("model", "auto"),
    }

    def _complete(args: dict) -> dict:
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return {"status": "error", "error": "prompt is required"}
        model = args.get("model") or state["model"]
        # Append the user turn before attempting completion so the
        # state is observable even if the router is offline.
        state["messages"].append({"role": "user", "content": prompt})
        try:
            from llm_router import LLMRouter  # late import
        except Exception:
            response_text = f"[stub-{model}] {prompt[:80]}"
            state["messages"].append({"role": "assistant",
                                       "content": response_text})
            state["last_response"] = response_text
            return {"status": "ok", "stub": True,
                    "response": response_text,
                    "model":    model,
                    "messages": list(state["messages"])}
        try:
            router = LLMRouter()
            response = router.complete(
                history=list(state["messages"]),
                model=model,
                on_chunk=lambda _piece: None,
                on_tool_invocation=lambda _inv: None,
            )
            response_text = getattr(response, "text", "") or ""
        except Exception as ex:
            response_text = ""
            state["messages"].append({"role": "assistant",
                                       "content": response_text})
            state["last_response"] = response_text
            return {"status": "unavailable",
                    "reason": f"{type(ex).__name__}: {ex}",
                    "model":  model,
                    "messages": list(state["messages"])}
        state["messages"].append({"role": "assistant",
                                   "content": response_text})
        state["last_response"] = response_text
        return {"status": "ok",
                "response": response_text,
                "model":    getattr(response, "model", model),
                "messages": list(state["messages"])}

    def _append_message(args: dict) -> dict:
        role = (args.get("role") or "user").strip()
        content = args.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        state["messages"].append({"role": role, "content": content})
        return {"status": "ok",
                "message_count": len(state["messages"])}

    def _last_response(_args: dict) -> dict:
        return {"status": "ok",
                "response": state["last_response"],
                "model":    state["model"]}

    return [
        MCPTool(
            "chat.complete",
            "Run a chat completion: append the user prompt, invoke "
            "the router, return the assistant response.",
            {"type": "object",
             "properties": {
                 "prompt": {"type": "string"},
                 "model":  {"type": "string"},
             },
             "required": ["prompt"]},
            _complete,
        ),
        MCPTool(
            "chat.append_message",
            "Append a message to the conversation without running "
            "the LLM. Useful for seeding context.",
            {"type": "object",
             "properties": {
                 "role":    {"type": "string",
                              "enum": ["user", "assistant", "system"]},
                 "content": {"type": "string"},
             },
             "required": ["content"]},
            _append_message,
        ),
        MCPTool(
            "chat.last_response",
            "Return the most recent assistant response in the "
            "conversation.",
            {"type": "object", "properties": {}, "required": []},
            _last_response,
        ),
    ]


# ─── MCP Registry ───────────────────────────────────────────────────
class MCPRegistry:
    """Process-wide lookup table keyed by node_id.

    The canvas owns node lifecycle: when a node is added, it calls
    REGISTRY.register(node_id, server); when removed, unregister.
    Cross-node tool calls walk the registry rather than the graph so
    callers don't need a graph reference.
    """

    def __init__(self) -> None:
        self._servers: dict[str, NodeMCPServer] = {}

    def register(self, node_id: str,
                  server: NodeMCPServer) -> NodeMCPServer:
        if not node_id:
            raise ValueError("node_id is required")
        if not isinstance(server, NodeMCPServer):
            raise TypeError("server must be a NodeMCPServer")
        self._servers[str(node_id)] = server
        return server

    def unregister(self, node_id: str) -> bool:
        return self._servers.pop(str(node_id), None) is not None

    def get(self, node_id: str) -> Optional[NodeMCPServer]:
        return self._servers.get(str(node_id))

    def list_servers(self) -> list[dict]:
        return [s.to_dict() for s in self._servers.values()]

    def clear(self) -> None:
        """Test helper — drop every registered server."""
        self._servers.clear()

    # Cross-node convenience: invoke a tool on another node by id.
    def invoke(self, node_id: str, tool_name: str,
                args: Optional[dict] = None) -> dict:
        server = self.get(node_id)
        if server is None:
            return {"status": "error",
                    "error":  f"Unknown node_id: {node_id}",
                    "code":   ERR_TOOL_NOT_FOUND}
        return server.invoke(tool_name, args or {})


# Module-level singleton — survives for the life of the Python process.
REGISTRY = MCPRegistry()
