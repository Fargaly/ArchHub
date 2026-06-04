"""In-house MCP core — the ADDITIVE, FastMCP-free replacement for the brain's
data-path MCP framework (founder grievance #1: the brain must not depend on a
3rd-party MCP framework in its data path).

Per `docs/prototypes/brain-own-mcp-plan-2026-06-03.html` (Level-C "HYBRID"):
keep the audited low-level `mcp` SDK *types / byte-framing* where reusing them
LOWERS RISK, but RE-OWN the dispatch + the tool registry so no third-party
FastMCP sits in the request path. This module is the daemon sibling of the
proven in-process `app/mcp/node_mcp.py` — it MIRRORS that file's dispatch shape,
error-code constants, and `tools/call` envelope rather than minting a divergent
one (the ONE-SYSTEM tie).

════════════════════════════════════════════════════════════════════════════
SAFETY (load-bearing — this is Phase-1 ADDITIVE + REVERSIBLE):
════════════════════════════════════════════════════════════════════════════
  * NOTHING in the live launch path imports this module. `server.py`,
    `pyproject.toml`, `.githooks`, `brain.db`/`-wal`/`-shm` are all UNCHANGED.
    `InHouseMCP` stands alone behind a flag, ready for a LATER founder-gated
    cutover — it is not wired into `build_server` or `main` this phase.
  * `InHouseMCP` is API-compatible with the slice of FastMCP the brain uses:
      - `mcp = InHouseMCP("personal-brain")`            (== FastMCP("personal-brain"))
      - `@mcp.tool(name=..., description=...)`           (the EXACT 2 kwargs every
                                                          one of server.py's 40
                                                          @mcp.tool call sites uses)
      - `mcp._brain_store = ...` / `mcp._brain_resolve_owner = ...`
                                                          (plain attribute carrier,
                                                          so server.py:1958-1959 +
                                                          register_*_tools(mcp, store)
                                                          keep working verbatim)
      - `mcp.run(transport="http", host=..., port=..., stateless_http=True)`
                                                          (== server.py:2225 shape)
    so the eventual shim is a pure swap of the `FastMCP(...)` constructor.
  * The `mcp` SDK is imported LAZILY (inside functions / methods), so this file
    `py_compile`s with no third-party dependency installed. We REUSE its types
    for the envelope + framing + descriptors (wire-parity true *by construction*
    for the one coupling that must not break); we OWN everything else.

════════════════════════════════════════════════════════════════════════════
THE WIRE CONTRACT this satisfies (pinned in `app/memory_gate.py`
BrainClient._call, "Verified live against FastMCP 3.3.1 at /mcp"):
════════════════════════════════════════════════════════════════════════════
    POST {base_url}/mcp
    Headers: Content-Type: application/json
             Accept: application/json, text/event-stream
    Body:    {jsonrpc, id, method:"tools/call", params:{name, arguments}}   (no
             prior `initialize` — server runs stateless, stateless_http=True)
    Response: text/event-stream (one `event: message` block)
        event: message
        data: {"jsonrpc":"2.0","id":N,
               "result":{"content":[{"type":"text","text":<json>}],
                         "structuredContent":{...}, "isError":false}}
    Client prefers `structuredContent`, falls back to `content[0].text`, and
    reads `result.error` (JSON-RPC error) on failure.

The envelope is built from `mcp.types.CallToolResult(...).model_dump(
by_alias=True, exclude_none=True)` — VERIFIED byte-identical to the shape
`_call` parses — and framed in `mcp.types.JSONRPCResponse` / `JSONRPCError`.
"""
from __future__ import annotations

import inspect
import json
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union


# ─────────────────────── Constants (mirror node_mcp.py — ONE-SYSTEM tie) ────
JSONRPC_VERSION = "2.0"

# Protocol negotiation — OWN our set rather than leaning on an SDK constant we
# don't control. These literals == the verified `mcp.types` values
# (DEFAULT_NEGOTIATED_VERSION / LATEST_PROTOCOL_VERSION) so we negotiate the
# same versions FastMCP does without an import-time dependency on them.
DEFAULT_PROTOCOL_VERSION = "2025-03-26"        # == mcp.types.DEFAULT_NEGOTIATED_VERSION
LATEST_PROTOCOL_VERSION = "2025-11-25"         # == mcp.types.LATEST_PROTOCOL_VERSION
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

# JSON-RPC 2.0 reserved error codes (== node_mcp.py:71-75).
ERR_PARSE = -32700
ERR_INVALID_REQ = -32600
ERR_METHOD_MISSING = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603
# MCP impl-defined range -32000..-32099 (== node_mcp.py:77).
ERR_TOOL_NOT_FOUND = -32001


# ─────────────────────── Errors (== node_mcp.py:95-109) ────────────────────
class MCPError(Exception):
    """Carries a JSON-RPC error envelope. Caught at the dispatch boundary and
    surfaced as `{"error": {...}}`. Byte-identical to node_mcp.MCPError so error
    envelopes match the in-process sibling."""

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


# ─────────────────────── signature → JSON-schema (OWNED) ────────────────────
# Python annotation → JSON-schema "type". Mirrors node_mcp's hand-written
# schemas (str→"string", int→"integer", …) so the in-house tool descriptors
# look like the proven sibling's.
_PY_TO_JSON: dict[Any, str] = {
    str: "string",
    bool: "boolean",       # NB: check bool before int (bool ⊂ int in Python)
    int: "integer",
    float: "number",
    list: "array",
    dict: "object",
    type(None): "null",
}


def _annotation_to_schema(ann: Any) -> dict[str, Any]:
    """Map ONE parameter annotation to a JSON-schema fragment.

    Handles the annotation shapes server.py's 40 handlers actually use:
      - bare builtins (str, int, bool, float, list, dict),
      - `Optional[X]` / `X | None`  → `anyOf:[{X},{"type":"null"}]`
        (the FastMCP/pydantic dialect: NOT "X made non-required"),
      - `list[T]` / `dict[K, V]`    → array/object (with `items` when knowable),
      - anything unknown            → {} (permissive, like a missing schema).
    """
    if ann is inspect.Parameter.empty or ann is Any:
        return {}

    origin = typing.get_origin(ann)
    args = typing.get_args(ann)

    # Optional[X] / Union[..., None] / X | None
    if origin is Union or (_UNION_TYPE is not None and origin is _UNION_TYPE):
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1 and len(args) == 2:
            # Optional[X] → anyOf of X and null (matches pydantic's emission).
            inner = _annotation_to_schema(non_none[0])
            return {"anyOf": [inner or {}, {"type": "null"}]}
        # General union → anyOf of each member.
        return {"anyOf": [(_annotation_to_schema(a) or {}) for a in args]}

    # Parameterised generics: list[T], dict[K, V], etc.
    if origin in (list, typing.List):  # type: ignore[attr-defined]
        schema: dict[str, Any] = {"type": "array"}
        if args:
            item = _annotation_to_schema(args[0])
            if item:
                schema["items"] = item
        return schema
    if origin in (dict, typing.Dict):  # type: ignore[attr-defined]
        return {"type": "object"}
    if origin in (tuple, typing.Tuple):  # type: ignore[attr-defined]
        return {"type": "array"}

    # Bare builtin types.
    if isinstance(ann, type):
        for py_t, js in _PY_TO_JSON.items():
            # bool first (it precedes int in _PY_TO_JSON dict order in 3.7+).
            if ann is py_t:
                return {"type": js}
        # subclass fallthrough (e.g. enum.IntEnum) — best effort.
        if issubclass(ann, bool):
            return {"type": "boolean"}
        if issubclass(ann, int):
            return {"type": "integer"}
        if issubclass(ann, float):
            return {"type": "number"}
        if issubclass(ann, str):
            return {"type": "string"}

    return {}


# `int | None` (PEP 604) has a distinct origin (types.UnionType) from
# typing.Union on 3.10+. Resolve it once at import; None on older Pythons.
try:  # pragma: no cover - trivial version probe
    import types as _types_mod

    _UNION_TYPE: Any = getattr(_types_mod, "UnionType", None)
except Exception:  # pragma: no cover
    _UNION_TYPE = None


def schema_from_signature(fn: Callable[..., Any]) -> dict[str, Any]:
    """Derive a JSON-schema `inputSchema` from a handler's signature — the
    OWNED equivalent of what FastMCP derives from the function via pydantic.

    Rules (chosen to match the brain's existing hand-written schemas in
    node_mcp.py + the FastMCP dialect the parity test pins):
      - every non-VAR parameter (excluding `self`) becomes a property,
      - a parameter with NO default is `required`,
      - a parameter WITH a default keeps that default under `"default"`
        (so re-emitting an existing schema is loss-free),
      - `Optional[X]` → `anyOf:[{X},{"type":"null"}]` with `default:null` when
        the Python default is None (the verified pydantic emission),
      - `*args` / `**kwargs` are ignored (tools take a flat arguments object).
    Always returns a well-formed object schema, even for a zero-arg tool.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return {"type": "object", "properties": {}, "required": []}

    # Resolve string / forward-ref annotations to real types. `from __future__
    # import annotations` (used across this codebase) makes EVERY annotation a
    # string at runtime, so `param.annotation` would be e.g. "int | None" /
    # "list[str]" — which must be evaluated before mapping to JSON-schema.
    # `get_type_hints` evaluates them against the function's own globals in ONE
    # shot; but if a SINGLE annotation is unresolvable it raises for the whole
    # function, which would silently degrade every param to {}. So we keep the
    # bulk result when it succeeds and fall back to PER-PARAMETER evaluation
    # otherwise — one exotic hint never poisons its siblings.
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    fn_globals = getattr(fn, "__globals__", {}) or {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL,
                           inspect.Parameter.VAR_KEYWORD):
            continue

        annotation = _resolve_annotation(name, param, hints, fn_globals)
        prop = _annotation_to_schema(annotation)
        has_default = param.default is not inspect.Parameter.empty
        if has_default:
            # JSON can only carry JSON-able defaults; skip the rest silently.
            if _is_jsonable(param.default):
                prop = dict(prop)
                prop["default"] = param.default
        else:
            required.append(name)

        properties[name] = prop or {}

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    # Always include `required` (possibly empty) — matches node_mcp.py's
    # hand-written schemas, which always carry a `required` list.
    schema["required"] = required
    return schema


def _resolve_annotation(name: str, param: "inspect.Parameter",
                        hints: dict, fn_globals: dict) -> Any:
    """Best resolution of ONE parameter's annotation to a real type.

    Order: (1) the bulk `get_type_hints` result, (2) if the raw annotation is a
    string (PEP 563 / `from __future__ import annotations`), eval THAT one string
    against the function's globals + `typing` — so a single unresolvable sibling
    can't have collapsed the whole function, (3) the raw annotation as-is
    (`_annotation_to_schema` maps an unresolved string to {}, i.e. permissive)."""
    if name in hints:
        return hints[name]
    ann = param.annotation
    if isinstance(ann, str):
        env = {"typing": typing}
        env.update(vars(typing))   # Optional, Union, List, ... by bare name
        env.update(fn_globals)     # the handler's own imported names win
        try:
            return eval(ann, env)  # noqa: S307 - evaluating a type annotation
        except Exception:
            return ann
    return ann


def _is_jsonable(value: Any) -> bool:
    """True if `value` round-trips through json.dumps (so it can be a schema
    default). Cheap try/except — defaults are tiny."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


# ─────────────────────── Envelope (REUSES mcp.types) ────────────────────────
def make_tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """Build the `tools/call` RESULT object the client contract pins, using the
    audited `mcp.types` envelope so it is byte-identical to FastMCP's output.

    Returns the dict:
        {"content": [{"type":"text","text": <json>}],
         "structuredContent": <obj-when-dict>, "isError": <bool>}

    VERIFIED: `CallToolResult(content=[TextContent(...)],
    structuredContent=..., isError=...).model_dump(by_alias=True,
    exclude_none=True)` yields exactly this shape — the shape
    `memory_gate.BrainClient._call` parses (prefers structuredContent, falls
    back to content[0].text).

    `structuredContent` is only set when `payload` is a JSON object (dict),
    because MCP's `structuredContent` is an object; scalars / lists ride in the
    text content only (and `exclude_none=True` drops the absent field — the
    client then uses content[0].text, which is exactly its documented
    fallback).
    """
    from mcp import types as t  # lazy: py_compile needs no SDK

    text = _to_text(payload)
    structured = payload if isinstance(payload, dict) else None
    result = t.CallToolResult(
        content=[t.TextContent(type="text", text=text)],
        structuredContent=structured,
        isError=bool(is_error),
    )
    return result.model_dump(by_alias=True, exclude_none=True)


def _to_text(payload: Any) -> str:
    """JSON-encode a tool payload for the text content block. Strings pass
    through as-is (so a tool that returns a plain string isn't double-quoted);
    everything else is json.dumps'd with `default=str` (matches node_mcp.py's
    `json.dumps(..., default=str)`)."""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(str(payload), ensure_ascii=False)


# ─────────────────────── Tool registry entry (OWNED) ───────────────────────
@dataclass
class _ToolEntry:
    """One registered tool. `.to_descriptor()` returns the `tools/list` shape
    {name, description, inputSchema} (== node_mcp.MCPTool.to_mcp())."""

    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any] = field(repr=False)

    def to_descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": dict(self.input_schema or {
                "type": "object", "properties": {}, "required": []}),
        }


# ─────────────────────── InHouseMCP — the FastMCP-compatible drop-in ────────
class InHouseMCP:
    """The brain's OWN MCP server object — a drop-in for the FastMCP slice the
    brain uses, with ZERO third-party framework in the dispatch path.

    Construction + decorator + attribute-carrier are signature-identical to
    FastMCP, so a later founder-gated cutover is a one-line swap of
    `FastMCP("personal-brain")` → `InHouseMCP("personal-brain")` in
    `server.build_server`. The 40 `@mcp.tool(name=..., description=...)` call
    sites, the `mcp._brain_store = ...` carrier, and the
    `register_*_tools(mcp, store)` helpers all keep working verbatim.

    Layering:
      tool registry + dispatch + schema   →  OWNED here (no fastmcp import)
      envelope + framing + descriptors     →  REUSED from mcp.types (wire-parity
                                              by construction)
    """

    def __init__(self, name: str, *, version: str = "0.1.0"):
        self.name = str(name)
        self.version = str(version)
        self._tools: dict[str, _ToolEntry] = {}
        # No threads, no I/O — matches FastMCP("...") + build_server purity so
        # unit tests that construct it (or call build_server) spawn nothing.

    # ── registry ───────────────────────────────────────────────────────────
    def tool(self, *, name: str, description: str = "") -> Callable[[Callable], Callable]:
        """Decorator: register `fn` as the tool `name`. Signature-identical to
        FastMCP's `@mcp.tool(name=..., description=...)`. Derives the
        inputSchema from the function signature and RETURNS `fn` UNCHANGED (the
        zero-rewrite key — a decorated handler is still a plain callable).

        Duplicate `name` raises ValueError (guards a double-registration
        regression — FastMCP also rejects dup tool names)."""
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.add_tool(
                name=name,
                description=description,
                handler=fn,
                input_schema=schema_from_signature(fn),
            )
            return fn
        return _decorator

    def add_tool(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
        input_schema: Optional[dict] = None,
    ) -> _ToolEntry:
        """Imperative registration — for `register_*_tools` helpers that build
        handlers programmatically. Same registry write as the decorator. When
        `input_schema` is omitted it is derived from the handler signature."""
        if not name:
            raise ValueError("tool name is required")
        if name in self._tools:
            raise ValueError(f"duplicate tool registration: {name!r}")
        if input_schema is None:
            input_schema = schema_from_signature(handler)
        entry = _ToolEntry(
            name=str(name),
            description=str(description or ""),
            input_schema=dict(input_schema or {}),
            handler=handler,
        )
        self._tools[entry.name] = entry
        return entry

    def list_tools(self) -> list[dict]:
        """`tools/list` payload — descriptors in insertion order."""
        return [e.to_descriptor() for e in self._tools.values()]

    def get_tool(self, name: str) -> Optional["_ToolEntry"]:
        """FastMCP-parity accessor: return the REAL registered tool entry for
        `name` (the `_ToolEntry` already in the registry — carrying `.name`,
        `.description`, `.input_schema`, `.handler`), or `None` if no tool by
        that name is registered.

        ONE-SYSTEM: a read-only view over the SAME `self._tools` registry that
        `tool` / `add_tool` write and `list_tools` / `call_tool` / `dispatch`
        read — not a parallel store and not a stub. Synchronous, matching the
        rest of this in-house surface (no coroutine)."""
        return self._tools.get(name)

    # ── invocation + envelope ────────────────────────────────────────────────
    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict[str, Any]:
        """Invoke tool `name` with the flat `arguments` object and return the
        `tools/call` RESULT object (content + structuredContent + isError).

        Pure + sync + transport-free — the unit-testable core. A tool that
        raises is caught and surfaced as `isError: true` with the error text in
        the content block (the client then raises on `isError`), EXCEPT an
        unknown tool, which raises `MCPError(ERR_TOOL_NOT_FOUND)` so dispatch
        emits a JSON-RPC error (parity with node_mcp's `_handle_tools_call`)."""
        args = dict(arguments or {})
        entry = self._tools.get(name)
        if entry is None:
            raise MCPError(
                ERR_TOOL_NOT_FOUND,
                f"Unknown tool: {name}",
                {"available": list(self._tools.keys())},
            )
        try:
            raw = entry.handler(**args)
        except MCPError:
            raise
        except TypeError as ex:
            # Bad arguments (missing required / unexpected kwarg) — invalid
            # params, surfaced as a JSON-RPC error like FastMCP's validation.
            raise MCPError(ERR_INVALID_PARAMS,
                           f"invalid arguments for {name}: {ex}")
        except Exception as ex:
            # A tool that fails returns an ERROR RESULT (isError:true), not a
            # JSON-RPC error — matches MCP semantics + the client's
            # `result.isError` branch.
            return make_tool_result(
                {"error": f"{type(ex).__name__}: {ex}"}, is_error=True)
        return make_tool_result(raw, is_error=False)

    # ── JSON-RPC 2.0 dispatch (OWNED) ────────────────────────────────────────
    def dispatch(self, message: dict) -> Optional[dict]:
        """Handle ONE JSON-RPC 2.0 request object and return the response
        object — or `None` for a notification (no `id`). The single entry every
        transport drives. Mirrors node_mcp.NodeMCPServer.dispatch + adds the
        `initialize` / `ping` / `notifications/*` methods a streamable-HTTP
        client speaks.

        Methods: initialize · ping · tools/list · tools/call · (notifications
        are accepted + ignored). Unknown method → ERR_METHOD_MISSING."""
        if not isinstance(message, dict):
            return self._error_response(None, ERR_INVALID_REQ,
                                        "request must be a JSON object")
        if message.get("jsonrpc") != JSONRPC_VERSION:
            return self._error_response(message.get("id"), ERR_INVALID_REQ,
                                        "jsonrpc must be '2.0'")

        method = message.get("method")
        req_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return self._error_response(req_id, ERR_INVALID_PARAMS,
                                        "params must be an object")

        # Notifications (e.g. notifications/initialized) carry no id and expect
        # NO response. Stateless clients may still send them; accept silently.
        is_notification = "id" not in message
        if isinstance(method, str) and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            else:
                raise MCPError(ERR_METHOD_MISSING,
                               f"Method not found: {method}")
        except MCPError as ex:
            if is_notification:
                return None
            return self._error_response(req_id, ex.code, ex.message, ex.data)
        except Exception as ex:  # pragma: no cover - defensive
            if is_notification:
                return None
            return self._error_response(
                req_id, ERR_INTERNAL, f"{type(ex).__name__}: {ex}")

        if is_notification:
            return None
        return self._success_response(req_id, result)

    def handle_raw(self, raw: Union[str, bytes]) -> Optional[str]:
        """Parse a raw JSON-RPC string → dispatch → json.dumps the response (or
        None for a notification). `-32700` on unparseable JSON. Convenience seam
        for a future stdio loop; not wired into any transport this phase."""
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except Exception:
                resp = self._error_response(None, ERR_PARSE, "invalid encoding")
                return json.dumps(resp)
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            resp = self._error_response(None, ERR_PARSE, "parse error")
            return json.dumps(resp)
        resp = self.dispatch(message)
        if resp is None:
            return None
        return json.dumps(resp)

    # ── method handlers ──────────────────────────────────────────────────────
    def _handle_initialize(self, params: dict) -> dict:
        """`initialize` response: negotiate the protocol version + advertise the
        tools capability + report serverInfo. Shaped via `mcp.types`
        (InitializeResult) so it is byte-identical to FastMCP's."""
        from mcp import types as t  # lazy

        requested = params.get("protocolVersion")
        negotiated = (
            requested
            if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS
            else DEFAULT_PROTOCOL_VERSION
        )
        init = t.InitializeResult(
            protocolVersion=negotiated,
            capabilities=t.ServerCapabilities(
                tools=t.ToolsCapability(listChanged=False)),
            serverInfo=t.Implementation(name=self.name, version=self.version),
        )
        return init.model_dump(by_alias=True, exclude_none=True)

    def _handle_tools_call(self, params: dict) -> dict:
        """`tools/call`: validate params, then return the RESULT object from
        `call_tool`. Param validation raises MCPError → JSON-RPC error (parity
        with node_mcp._handle_tools_call)."""
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise MCPError(ERR_INVALID_PARAMS, "tools/call requires `name`")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise MCPError(ERR_INVALID_PARAMS,
                           "tools/call `arguments` must be an object")
        return self.call_tool(name, arguments)

    # ── JSON-RPC framing (REUSES mcp.types, falls back to a dict) ────────────
    def _success_response(self, req_id: Any, result: dict) -> dict:
        try:
            from mcp import types as t

            resp = t.JSONRPCResponse(
                jsonrpc=JSONRPC_VERSION, id=req_id, result=result)
            return resp.model_dump(by_alias=True, exclude_none=True)
        except Exception:  # pragma: no cover - SDK absent / odd id
            return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}

    def _error_response(self, req_id: Any, code: int, message: str,
                        data: Optional[dict] = None) -> dict:
        try:
            from mcp import types as t

            err = t.ErrorData(code=int(code), message=str(message), data=data)
            resp = t.JSONRPCError(jsonrpc=JSONRPC_VERSION, id=req_id, error=err)
            return resp.model_dump(by_alias=True, exclude_none=True)
        except Exception:  # pragma: no cover - SDK absent / odd id
            error: dict[str, Any] = {"code": int(code), "message": str(message)}
            if data is not None:
                error["data"] = data
            return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": error}

    # ── introspection ────────────────────────────────────────────────────────
    def server_info(self) -> dict:
        from mcp import types as t

        return t.Implementation(
            name=self.name, version=self.version).model_dump(exclude_none=True)

    # ── streamable-HTTP POST /mcp (stateless) — the SSE responder ────────────
    def render_sse(self, message: dict) -> bytes:
        """Render ONE JSON-RPC request → the streamable-HTTP SSE body bytes the
        client reads: a single `event: message` block whose `data:` line is the
        JSON-RPC response. This is the exact shape `memory_gate._call` scans
        for (`for line in raw.splitlines(): if line.startswith("data:")`).

        A notification (no response) yields an empty body. Pure + transport-free
        — the unit-testable heart of the HTTP handler; no socket involved."""
        resp = self.dispatch(message)
        if resp is None:
            return b""
        return _sse_encode(resp)

    async def asgi_mcp(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Stateless streamable-HTTP POST /mcp handler as a raw ASGI app.

        OWNED end-to-end — no FastMCP, no Starlette routing. Reads the JSON-RPC
        body, dispatches it, and writes back `text/event-stream` with one
        `event: message` block (matching FastMCP 3.3.1's stateless_http
        responder, which the pinned client parses). `stateless` by definition:
        every POST is self-contained; no session id, no prior `initialize`
        required for `tools/call`.

        Drive it directly in tests with a fake (scope, receive, send) — it never
        binds a socket. A future cutover mounts this at POST `/mcp` (or hands it
        to the SDK's StreamableHTTPSessionManager) WITHOUT touching the registry
        / dispatch / envelope above."""
        if scope.get("type") != "http":  # pragma: no cover - defensive
            return

        method = (scope.get("method") or "GET").upper()
        path = scope.get("path") or "/"
        if not path.rstrip("/").endswith("/mcp"):
            await _asgi_json(send, 404, {"error": "not found"})
            return
        if method != "POST":
            await _asgi_json(send, 405, {"error": "method not allowed",
                                         "allow": "POST"})
            return

        # Read the full request body from the ASGI receive channel.
        body = await _asgi_read_body(receive)
        try:
            message = json.loads(body) if body else {}
        except (TypeError, ValueError):
            resp = self._error_response(None, ERR_PARSE, "parse error")
            await _asgi_sse(send, _sse_encode(resp))
            return

        # Batch requests (a JSON array) — render each; concatenate the blocks.
        if isinstance(message, list):
            chunks = [self.render_sse(m) for m in message]
            await _asgi_sse(send, b"".join(c for c in chunks if c))
            return

        await _asgi_sse(send, self.render_sse(message))

    # ── Starlette app factory: POST /mcp (stateless) — the mountable form ────
    def build_asgi_app(self) -> "Any":
        """Build a Starlette ASGI app exposing the stateless streamable-HTTP
        `POST /mcp` endpoint, driven by OUR `dispatch` and emitting the SSE shape
        `memory_gate.BrainClient._call` parses. This is the mountable sibling of
        the raw-ASGI `asgi_mcp` above — same dispatch, same envelope, same SSE
        framing — packaged as a Starlette `Route` + `Response` so a later cutover
        can `app.mount("/", mcp.build_asgi_app())` (or serve it via uvicorn from
        `run()`) without re-touching the registry / dispatch / envelope.

        REUSE-VS-HANDROLL (audited 2026-06-03 against the installed `mcp` SDK
        1.27.0 / fastmcp 3.3.1): we do NOT use `StreamableHTTPSessionManager`.
        Its `__init__(self, app: MCPServer, ...)` requires a full low-level
        `mcp.server.Server`, and its stateless path
        (`_handle_stateless_request`) opens anyio streams via
        `http_transport.connect()` and then calls
        `self.app.run(read, write, ..., stateless=True)` — i.e. it drives the
        SDK's OWN dispatch loop with NO seam for `InHouseMCP.dispatch`. Mounting
        it would drag the third-party MCP dispatch framework back into the
        brain's data path — the exact founder-grievance Phase 1 re-owned. So we
        hand-roll a one-route Starlette app over `self.dispatch` and REUSE the
        SDK only for the `mcp.types` envelope/framing (already byte-verified by
        tests/test_mcp_core.py §§5-6).

        Stateless by construction: every POST is self-contained; `tools/call`
        needs no prior `initialize`, no session id is read or issued. A
        notification (no `id`) → `202 Accepted`, empty body — byte-true to the
        SDK's stateless responder, which returns `HTTPStatus.ACCEPTED` for any
        non-`JSONRPCRequest` message (mcp/server/streamable_http.py:508-515).
        Bad JSON → `200` + an in-band JSON-RPC parse-error SSE (the transport
        succeeds; the error rides the stream), matching `asgi_mcp`.

        Imports starlette LAZILY (inside this method) so the module keeps
        `py_compile`-ing and importing with no third-party dep installed — the
        same discipline as the lazy `mcp` import and the
        `test_importing_mcp_core_does_not_mutate_syspath` guard.

        Tests drive THIS app through an in-process ASGI client (httpx
        ASGITransport / starlette TestClient) — never a socket, never a live
        uvicorn, never port 8473.
        """
        from starlette.applications import Starlette          # lazy
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Route

        sse_headers = {"cache-control": "no-cache"}

        async def _mcp_endpoint(request: "Request") -> "Response":
            raw = await request.body()
            try:
                message = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                err = self._error_response(None, ERR_PARSE, "parse error")
                return Response(
                    content=_sse_encode(err),
                    status_code=200,
                    media_type="text/event-stream",
                    headers=sse_headers,
                )

            # Batch (JSON array): render each block, concatenate — parity with
            # asgi_mcp. All-notifications → 202 (nothing to stream).
            if isinstance(message, list):
                chunks = [self.render_sse(m) for m in message]
                body = b"".join(c for c in chunks if c)
                if not body:
                    return Response(status_code=202)
                return Response(
                    content=body,
                    status_code=200,
                    media_type="text/event-stream",
                    headers=sse_headers,
                )

            body = self.render_sse(message)
            if not body:
                # Notification(s) only — no response object. 202 Accepted, empty
                # body: byte-true to the SDK's stateless responder.
                return Response(status_code=202)
            return Response(
                content=body,
                status_code=200,
                media_type="text/event-stream",
                headers=sse_headers,
            )

        return Starlette(routes=[Route("/mcp", _mcp_endpoint, methods=["POST"])])

    # ── run() — FastMCP-compatible transport (Phase 2: serves via uvicorn) ───
    def run(
        self,
        transport: str = "stdio",
        host: str = "127.0.0.1",
        port: int = 8473,
        stateless_http: bool = True,
        **kwargs: Any,
    ) -> None:
        """FastMCP-compatible `run(...)` — same SIGNATURE the brain's launch path
        uses (server.py:2225 `server.run(transport="http", host=..., port=...,
        stateless_http=True)`), so the eventual founder-gated cutover is a pure
        swap of the constructor with NO call-site change.

        Phase 2 fills this seam: for the HTTP transports
        (`"http"` / `"streamable-http"`) it serves `build_asgi_app()` — the
        stateless `POST /mcp` Starlette app over OUR dispatch — with **uvicorn**.
        uvicorn is imported LAZILY here (like the `mcp` / `starlette` imports
        elsewhere) so the module still `py_compile`s and imports with no
        third-party dep installed; the import cost is paid only when a server is
        actually started.

        This DOES bind a socket — it is the real server. It is NOT wired into the
        brain's live launch this phase (server.py still constructs `FastMCP`, not
        `InHouseMCP`); a later founder-gated cutover flips the constructor. The
        unit/parity tests NEVER call `run()` against a socket — they drive
        `build_asgi_app()` through an in-process ASGI client (httpx
        ASGITransport / starlette TestClient), so coverage never opens a port.

        `stateless_http` is accepted for signature-parity and is the ONLY mode
        the app implements (every POST is self-contained — see
        `build_asgi_app`); it is structurally true, so the flag needs no branch.
        `transport="stdio"` (the FastMCP default) has no in-house loop yet and
        raises NotImplementedError naming the supported transports — stdio is not
        the brain's wire (the client speaks HTTP), so it is out of Phase-2 scope.
        """
        t = (transport or "").lower()
        if t in ("http", "streamable-http", "streamable_http"):
            import uvicorn  # lazy: py_compile / import need no server dep

            app = self.build_asgi_app()
            # log_level="warning" mirrors federation_server.py's uvicorn.run —
            # quiet by default; the brain owns its own logging.
            uvicorn.run(app, host=host, port=int(port),
                        log_level=kwargs.pop("log_level", "warning"))
            return
        raise NotImplementedError(
            f"mcp_core.run: unsupported transport {transport!r}. "
            "Supported: 'http' / 'streamable-http' (served via uvicorn over "
            "build_asgi_app()). stdio has no in-house loop yet; drive "
            "dispatch() / call_tool() directly, or serve build_asgi_app() / "
            "asgi_mcp() on any ASGI host."
        )


# ─────────────────────── SSE + ASGI helpers (OWNED, stdlib-only) ────────────
def _sse_encode(obj: dict) -> bytes:
    """Encode one JSON-RPC response as a Server-Sent-Events `message` block:

        event: message\\n
        data: <json>\\n
        \\n

    `data:` carries the compact JSON. The blank line terminates the event.
    Matches FastMCP 3.3.1's stateless responder, which the pinned client reads
    by scanning `data:` lines (`memory_gate._call`)."""
    data = json.dumps(obj, ensure_ascii=False)
    return f"event: message\ndata: {data}\n\n".encode("utf-8")


async def _asgi_read_body(receive: Callable) -> bytes:
    """Drain the ASGI `http.request` body (handles chunked `more_body`)."""
    chunks: list[bytes] = []
    while True:
        event = await receive()
        if event.get("type") != "http.request":
            # `http.disconnect` or anything else ends the read.
            break
        chunks.append(event.get("body") or b"")
        if not event.get("more_body"):
            break
    return b"".join(chunks)


async def _asgi_sse(send: Callable, body: bytes) -> None:
    """Send a 200 `text/event-stream` ASGI response carrying `body`."""
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/event-stream"),
            (b"cache-control", b"no-cache"),
            (b"connection", b"keep-alive"),
        ],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _asgi_json(send: Callable, status: int, obj: dict) -> None:
    """Send a small JSON ASGI response (for 404 / 405 / parse errors)."""
    body = json.dumps(obj).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": int(status),
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


__all__ = [
    "InHouseMCP",
    "MCPError",
    "_sse_encode",
    "schema_from_signature",
    "make_tool_result",
    "JSONRPC_VERSION",
    "DEFAULT_PROTOCOL_VERSION",
    "LATEST_PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "ERR_PARSE",
    "ERR_INVALID_REQ",
    "ERR_METHOD_MISSING",
    "ERR_INVALID_PARAMS",
    "ERR_INTERNAL",
    "ERR_TOOL_NOT_FOUND",
]
