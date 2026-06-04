"""Parity tests for the in-house MCP core (`personal_brain.mcp_core`).

GOAL (founder grievance #1): the brain's data-path MCP must NOT depend on a
3rd-party framework. `mcp_core.InHouseMCP` is the ADDITIVE in-house replacement
for the FastMCP slice the brain uses. These tests prove WIRE-PARITY with the
pinned client contract WITHOUT cutting over and WITHOUT binding a socket /
starting a live server — they drive the dispatch + the ASGI handler directly.

The pinned contract (`app/memory_gate.py` BrainClient._call, "Verified live
against FastMCP 3.3.1 at /mcp"):
    POST /mcp · Accept application/json, text/event-stream · JSON-RPC 2.0
    tools/call with NO prior initialize (stateless) · response is an SSE stream
    whose first `data:` line carries
        {jsonrpc, id, result:{content:[{type:text,text:<json>}],
                              structuredContent:{...}, isError:false}}
    client PREFERS structuredContent, FALLS BACK to content[0].text, reads
    result.error on failure.

The strongest proof here: we feed the bytes `mcp_core` renders into the REAL
`BrainClient._call` SSE parser (loaded straight from the ArchHub source, with
`urlopen` monkeypatched so no socket opens) and assert it returns exactly the
tool's dict — i.e. the actual client code accepts our actual wire output.

ADDITIVE: this test imports only `personal_brain.mcp_core` (+ the real
`memory_gate` parser, loaded by file path WITHOUT mutating sys.path so it can't
shadow the genuine `mcp` SDK). It touches no server.py, no fastmcp, no DB.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional  # module-level so get_type_hints resolves forward refs

import pytest

from personal_brain import mcp_core
from personal_brain.mcp_core import (
    DEFAULT_PROTOCOL_VERSION,
    ERR_INVALID_PARAMS,
    ERR_METHOD_MISSING,
    ERR_TOOL_NOT_FOUND,
    InHouseMCP,
    MCPError,
    schema_from_signature,
)


# ════════════════════════════════════════════════════════════════════════════
# Fixtures: a tiny server with toy tools (mirrors the @mcp.tool(name, desc) +
# register_*_tools(mcp, store) shapes server.py actually uses).
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def toy() -> InHouseMCP:
    mcp = InHouseMCP("personal-brain-test")

    @mcp.tool(name="toy.echo", description="Echo the payload back as a dict.")
    def toy_echo(message: str, times: int = 1, loud: bool = False):
        text = (message.upper() if loud else message)
        return {"ok": True, "echo": text, "times": int(times)}

    @mcp.tool(name="toy.scalar", description="Return a bare scalar (no dict).")
    def toy_scalar(value: str):
        # Returns a plain string — exercises the content-only / no-
        # structuredContent fallback path of the contract.
        return value

    @mcp.tool(name="toy.boom", description="Always raises — error-result path.")
    def toy_boom():
        raise RuntimeError("kaboom")

    # Imperative registration path (what register_*_tools helpers use).
    def _added(a: str, b: str = "z"):
        return {"a": a, "b": b}

    mcp.add_tool(name="toy.added", description="Imperatively added tool.",
                 handler=_added)
    return mcp


# Load the REAL BrainClient SSE parser from ArchHub source by FILE PATH, without
# inserting ArchHub/app onto sys.path (which would let app/mcp shadow the real
# `mcp` SDK — the exact pollution conftest.py guards against). memory_gate.py is
# stdlib-only at module level, so a direct spec-load is safe + self-contained.
def _load_memory_gate():
    """Load ArchHub's `app/memory_gate.py` by file path, WITHOUT inserting
    ArchHub/app onto sys.path (which would let app/mcp shadow the genuine `mcp`
    SDK — the pollution conftest.py guards against). Returns the module, or None
    only when the file genuinely isn't in this checkout (→ a real skip).

    NB: the module MUST be registered in sys.modules BEFORE exec_module — its
    module-level `@dataclass` decorators resolve string annotations via
    `sys.modules[cls.__module__].__dict__` on Python 3.12+/3.14, which raises if
    the module isn't yet registered. We register under a private name, run, then
    pop it so nothing stray is left behind. A genuine load error is NOT swallowed
    into a skip — it raises, so a real parity-proof failure is never hidden."""
    here = Path(__file__).resolve()
    # tests/ -> personal-brain-mcp/ -> ArchHub/
    archhub = here.parent.parent.parent
    mg_path = archhub / "app" / "memory_gate.py"
    if not mg_path.exists():
        return None  # genuinely absent → caller skips
    mod_name = "_archhub_memory_gate_for_parity"
    spec = importlib.util.spec_from_file_location(mod_name, mg_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # required before exec_module (3.14 dataclass)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise  # surface load errors loudly — never a silent skip of the proof
    return mod


class _FakeHTTPResponse:
    """Minimal stand-in for the object urllib.request.urlopen returns: a context
    manager exposing `.read()`. No socket — carries our rendered SSE bytes."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _drive_asgi(app_coro_fn, scope: dict, body: bytes) -> dict:
    """Run an ASGI app callable with a single-chunk request body and capture the
    response. NO socket bound — we feed fake receive/send channels. Returns
    {status, headers: {name: value}, body: bytes}."""
    sent: list[dict] = []
    received = [
        {"type": "http.request", "body": body, "more_body": False},
    ]

    async def receive():
        return received.pop(0) if received else {"type": "http.disconnect"}

    async def send(event):
        sent.append(event)

    asyncio.run(app_coro_fn(scope, receive, send))

    start = next(e for e in sent if e["type"] == "http.response.start")
    body_events = [e for e in sent if e["type"] == "http.response.body"]
    out_body = b"".join(e.get("body") or b"" for e in body_events)
    headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return {"status": start["status"], "headers": headers, "body": out_body}


def _http_scope(method: str = "POST", path: str = "/mcp") -> dict:
    return {"type": "http", "method": method, "path": path, "headers": []}


def _parse_sse_first_data(raw: str) -> dict:
    """Extract the first `data:` JSON object from an SSE body — the same scan
    `memory_gate._call` performs."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"no SSE data line in body: {raw!r}")


# ════════════════════════════════════════════════════════════════════════════
# 1. tools/list through dispatch — descriptors are the {name, description,
#    inputSchema} shape, in insertion order, with derived schemas.
# ════════════════════════════════════════════════════════════════════════════
def test_tools_list_dispatch_shape_and_order(toy: InHouseMCP):
    resp = toy.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    tools = resp["result"]["tools"]

    names = [t["name"] for t in tools]
    assert names == ["toy.echo", "toy.scalar", "toy.boom", "toy.added"], (
        "tools/list must preserve insertion order"
    )
    for t in tools:
        assert set(t.keys()) == {"name", "description", "inputSchema"}
        assert t["inputSchema"]["type"] == "object"
        assert "properties" in t["inputSchema"]

    echo = next(t for t in tools if t["name"] == "toy.echo")
    props = echo["inputSchema"]["properties"]
    assert props["message"] == {"type": "string"}
    assert props["times"] == {"type": "integer", "default": 1}
    assert props["loud"] == {"type": "boolean", "default": False}
    # only the no-default param is required
    assert echo["inputSchema"]["required"] == ["message"]


# ════════════════════════════════════════════════════════════════════════════
# 2. tools/call through dispatch — the RESULT envelope EXACTLY matches the
#    memory_gate contract (structuredContent == dict; content[0].text ==
#    json.dumps(dict); isError False).
# ════════════════════════════════════════════════════════════════════════════
def test_tools_call_dispatch_envelope_matches_contract(toy: InHouseMCP):
    resp = toy.dispatch({
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "toy.echo",
                   "arguments": {"message": "hi", "times": 2}},
    })
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 42
    result = resp["result"]

    expected = {"ok": True, "echo": "hi", "times": 2}
    # contract: isError False
    assert result["isError"] is False
    # contract: structuredContent == the dict (client prefers this)
    assert result["structuredContent"] == expected
    # contract: content[0] is a text block whose text == json.dumps(dict)
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == expected
    # the envelope has exactly the three contract keys (no leaked SDK fields)
    assert set(result.keys()) == {"content", "structuredContent", "isError"}


def test_tools_call_scalar_payload_uses_content_fallback(toy: InHouseMCP):
    """A tool returning a bare string has NO structuredContent (it isn't an
    object); the client's documented fallback is content[0].text. Assert the
    envelope omits structuredContent and the text carries the value."""
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "toy.scalar", "arguments": {"value": "plain"}},
    })
    result = resp["result"]
    assert result["isError"] is False
    assert "structuredContent" not in result  # exclude_none dropped it
    assert result["content"][0]["text"] == "plain"


# ════════════════════════════════════════════════════════════════════════════
# 3. Error paths — a JSON-RPC error for unknown method / unknown tool / bad
#    params, and an isError RESULT (not a JSON-RPC error) for a tool that throws.
# ════════════════════════════════════════════════════════════════════════════
def test_unknown_method_returns_jsonrpc_error(toy: InHouseMCP):
    resp = toy.dispatch({"jsonrpc": "2.0", "id": 9, "method": "no.such.method"})
    assert resp["id"] == 9
    assert "result" not in resp
    assert resp["error"]["code"] == ERR_METHOD_MISSING
    assert "no.such.method" in resp["error"]["message"]


def test_unknown_tool_returns_jsonrpc_error(toy: InHouseMCP):
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "toy.nope", "arguments": {}},
    })
    assert "result" not in resp
    assert resp["error"]["code"] == ERR_TOOL_NOT_FOUND
    assert "toy.nope" in resp["error"]["message"]


def test_missing_tool_name_is_invalid_params(toy: InHouseMCP):
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 11, "method": "tools/call",
        "params": {"arguments": {}},
    })
    assert resp["error"]["code"] == ERR_INVALID_PARAMS


def test_tool_exception_becomes_error_result_not_jsonrpc_error(toy: InHouseMCP):
    """A tool that raises yields a RESULT with isError:true (the client raises
    on result.isError) — NOT a transport-level JSON-RPC error."""
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 12, "method": "tools/call",
        "params": {"name": "toy.boom", "arguments": {}},
    })
    assert "error" not in resp  # transport succeeded
    result = resp["result"]
    assert result["isError"] is True
    assert "kaboom" in result["content"][0]["text"]


def test_bad_arguments_is_invalid_params(toy: InHouseMCP):
    """Missing a required argument surfaces as a JSON-RPC invalid-params error
    (parity with FastMCP's pydantic validation)."""
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 13, "method": "tools/call",
        "params": {"name": "toy.echo", "arguments": {}},  # missing `message`
    })
    assert resp["error"]["code"] == ERR_INVALID_PARAMS


# ════════════════════════════════════════════════════════════════════════════
# 4. initialize + ping + notifications — the methods a streamable-HTTP client
#    speaks. Stateless tools/call needs no prior initialize, but the handshake
#    must still work + negotiate the protocol version.
# ════════════════════════════════════════════════════════════════════════════
def test_initialize_negotiates_protocol_and_advertises_tools(toy: InHouseMCP):
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
    })
    result = resp["result"]
    assert result["protocolVersion"] == "2025-06-18"  # echoed (supported)
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "personal-brain-test"


def test_initialize_unknown_version_falls_back_to_default(toy: InHouseMCP):
    resp = toy.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    })
    assert resp["result"]["protocolVersion"] == DEFAULT_PROTOCOL_VERSION


def test_ping_returns_empty_result(toy: InHouseMCP):
    resp = toy.dispatch({"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert resp["result"] == {}


def test_notification_returns_none(toy: InHouseMCP):
    # No `id` + a notifications/* method → no response object at all.
    assert toy.dispatch({"jsonrpc": "2.0",
                         "method": "notifications/initialized"}) is None


def test_bad_jsonrpc_version_is_invalid_request(toy: InHouseMCP):
    resp = toy.dispatch({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert resp["error"]["code"] == mcp_core.ERR_INVALID_REQ


# ════════════════════════════════════════════════════════════════════════════
# 5. Streamable-HTTP POST /mcp — drive the ASGI handler DIRECTLY (no socket).
#    Stateless tools/call (no prior initialize) returns text/event-stream whose
#    first data: line is the JSON-RPC response with the contract envelope.
# ════════════════════════════════════════════════════════════════════════════
def test_asgi_mcp_stateless_tools_call_emits_sse_contract(toy: InHouseMCP):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 100, "method": "tools/call",
        "params": {"name": "toy.echo", "arguments": {"message": "yo"}},
    }).encode("utf-8")

    out = _drive_asgi(toy.asgi_mcp, _http_scope("POST", "/mcp"), body)

    assert out["status"] == 200
    assert out["headers"]["content-type"] == "text/event-stream"
    raw = out["body"].decode("utf-8")
    # SSE framing the client scans for
    assert raw.startswith("event: message\n")
    assert "\ndata: " in raw

    data = _parse_sse_first_data(raw)
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 100
    result = data["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"ok": True, "echo": "yo", "times": 1}
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_asgi_mcp_get_is_405(toy: InHouseMCP):
    out = _drive_asgi(toy.asgi_mcp, _http_scope("GET", "/mcp"), b"")
    assert out["status"] == 405


def test_asgi_mcp_wrong_path_is_404(toy: InHouseMCP):
    out = _drive_asgi(toy.asgi_mcp, _http_scope("POST", "/other"), b"")
    assert out["status"] == 404


def test_asgi_mcp_bad_json_emits_parse_error_sse(toy: InHouseMCP):
    out = _drive_asgi(toy.asgi_mcp, _http_scope("POST", "/mcp"), b"{not json")
    assert out["status"] == 200  # SSE transport still 200; error is in-band
    data = _parse_sse_first_data(out["body"].decode("utf-8"))
    assert data["error"]["code"] == mcp_core.ERR_PARSE


# ════════════════════════════════════════════════════════════════════════════
# 6. THE strongest parity proof — feed mcp_core's rendered SSE bytes into the
#    REAL BrainClient._call parser (no socket; urlopen monkeypatched). Asserts
#    the actual client code returns exactly the tool's dict on success and
#    raises on the error path.
# ════════════════════════════════════════════════════════════════════════════
def test_real_memory_gate_parser_accepts_our_wire_success(toy: InHouseMCP, monkeypatch):
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    # Render exactly what our ASGI /mcp would write for this tools/call.
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "toy.echo",
                   "arguments": {"message": "wire", "times": 3, "loud": True}},
    }
    sse_bytes = toy.render_sse(request)

    # Patch urlopen on the loaded module so _call reads our bytes (no socket).
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = req.data
        return _FakeHTTPResponse(sse_bytes)

    monkeypatch.setattr(mg.urllib.request, "urlopen", _fake_urlopen)

    client = mg.BrainClient(base_url="http://127.0.0.1:8473")
    got = client._call("toy.echo",
                       {"message": "wire", "times": 3, "loud": True})

    # The real client returns structuredContent (its preferred branch) — which
    # is exactly the dict our tool produced.
    assert got == {"ok": True, "echo": "WIRE", "times": 3}
    # And it spoke the pinned wire: POST /mcp + the SSE Accept header.
    assert captured["url"].endswith("/mcp")
    assert "text/event-stream" in captured["headers"].get("accept", "")


def test_real_memory_gate_parser_falls_back_to_text_content(toy: InHouseMCP, monkeypatch):
    """When a tool returns a scalar (no structuredContent), the real client's
    documented fallback is to json-parse content[0].text. Prove our wire drives
    that branch too."""
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    # A tool whose payload is a JSON object encoded only in text would still set
    # structuredContent; to exercise the fallback we render a result whose
    # structuredContent is absent. toy.scalar returns a bare string, so its text
    # is the raw string — _call returns {"text": ...} for non-JSON text. Use a
    # tool that returns a JSON-encoded dict as a *string* is not possible via
    # make_tool_result (dict → structuredContent). So assert the scalar path:
    request = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "toy.scalar", "arguments": {"value": "plain-text"}},
    }
    sse_bytes = toy.render_sse(request)
    monkeypatch.setattr(mg.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeHTTPResponse(sse_bytes))

    client = mg.BrainClient(base_url="http://127.0.0.1:8473")
    got = client._call("toy.scalar", {"value": "plain-text"})
    # content[0].text == "plain-text"; not JSON → client wraps as {"text": ...}
    assert got == {"text": "plain-text"}


def test_real_memory_gate_parser_raises_on_error_result(toy: InHouseMCP, monkeypatch):
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    request = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "toy.boom", "arguments": {}},
    }
    sse_bytes = toy.render_sse(request)
    monkeypatch.setattr(mg.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeHTTPResponse(sse_bytes))

    client = mg.BrainClient(base_url="http://127.0.0.1:8473")
    with pytest.raises(RuntimeError):
        client._call("toy.boom", {})


def test_real_memory_gate_parser_raises_on_jsonrpc_error(toy: InHouseMCP, monkeypatch):
    """A transport-level JSON-RPC error (unknown tool) must make the real client
    raise too — it reads `data.error` before `result`."""
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    request = {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "toy.ghost", "arguments": {}},
    }
    sse_bytes = toy.render_sse(request)
    monkeypatch.setattr(mg.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeHTTPResponse(sse_bytes))

    client = mg.BrainClient(base_url="http://127.0.0.1:8473")
    with pytest.raises(RuntimeError):
        client._call("toy.ghost", {})


# ════════════════════════════════════════════════════════════════════════════
# 7. schema_from_signature — the OWNED signature→JSON-schema derivation,
#    including the FastMCP/pydantic Optional[X] dialect (anyOf + default null).
# ════════════════════════════════════════════════════════════════════════════
def test_schema_optional_uses_anyof_null_dialect():
    def fn(a: str, b: Optional[str] = None, c: int = 3):
        return None

    schema = schema_from_signature(fn)
    assert schema["type"] == "object"
    assert schema["required"] == ["a"]
    assert schema["properties"]["a"] == {"type": "string"}
    # Optional[str]=None → anyOf:[{string},{null}] with default null (the
    # verified pydantic emission, NOT "string made non-required").
    b = schema["properties"]["b"]
    assert b["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert b["default"] is None
    assert schema["properties"]["c"] == {"type": "integer", "default": 3}


def test_schema_one_unresolvable_annotation_does_not_poison_siblings():
    """Robustness: a single forward-ref that can't be resolved must NOT collapse
    the rest of the schema to {} — each param resolves independently. Build a
    function whose annotations are strings (PEP 563) where one names a type that
    doesn't exist, and assert the resolvable siblings still get real schemas."""
    src = (
        "def fn(a: str, b: 'NoSuchType' = None, c: int = 7):\n"
        "    return None\n"
    )
    ns: dict = {}
    exec(compile(src, "<dynamic>", "exec"), ns)  # noqa: S102 - controlled src
    fn = ns["fn"]
    # Force PEP-563 string annotations regardless of exec environment.
    fn.__annotations__ = {"a": "str", "b": "NoSuchType", "c": "int"}

    schema = schema_from_signature(fn)
    assert schema["properties"]["a"] == {"type": "string"}   # sibling intact
    assert schema["properties"]["c"] == {"type": "integer", "default": 7}
    assert schema["properties"]["b"] == {"default": None}     # unresolved → {}
    assert schema["required"] == ["a"]


def test_schema_pep604_optional_union():
    def fn(x: "int | None" = None):
        return None

    schema = schema_from_signature(fn)
    x = schema["properties"]["x"]
    assert x["anyOf"] == [{"type": "integer"}, {"type": "null"}]


def test_schema_containers_and_zero_arg():
    def fn(items: list, mapping: dict, names: "list[str]"):
        return None

    schema = schema_from_signature(fn)
    assert schema["properties"]["items"] == {"type": "array"}
    assert schema["properties"]["mapping"] == {"type": "object"}
    assert schema["properties"]["names"] == {"type": "array",
                                             "items": {"type": "string"}}

    def zero():
        return None

    z = schema_from_signature(zero)
    assert z == {"type": "object", "properties": {}, "required": []}


# ════════════════════════════════════════════════════════════════════════════
# 8. FastMCP-compatibility surface — the API the eventual one-line cutover
#    depends on: construction, attribute carrier, dup-guard, run() seam.
# ════════════════════════════════════════════════════════════════════════════
def test_attribute_carrier_like_fastmcp():
    """server.py sets mcp._brain_store / mcp._brain_resolve_owner and
    register_*_tools(mcp, store) read them back. Prove the carrier works."""
    mcp = InHouseMCP("personal-brain")
    sentinel = object()
    mcp._brain_store = sentinel
    mcp._brain_resolve_owner = lambda: "founder"
    assert mcp._brain_store is sentinel
    assert mcp._brain_resolve_owner() == "founder"


def test_duplicate_tool_name_rejected():
    mcp = InHouseMCP("dup")

    @mcp.tool(name="x", description="first")
    def first():
        return {}

    with pytest.raises(ValueError):
        @mcp.tool(name="x", description="second")
        def second():
            return {}


def test_decorator_returns_function_unchanged():
    mcp = InHouseMCP("x")

    def handler(a: str):
        return {"a": a}

    wrapped = mcp.tool(name="t", description="d")(handler)
    assert wrapped is handler  # zero-rewrite: still a plain callable
    assert handler("v") == {"a": "v"}  # still directly callable


def test_call_tool_is_the_pure_core(toy: InHouseMCP):
    """call_tool returns the bare RESULT object (no JSON-RPC envelope)."""
    result = toy.call_tool("toy.added", {"a": "A"})
    assert result["structuredContent"] == {"a": "A", "b": "z"}
    assert result["isError"] is False


def test_call_tool_unknown_raises_tool_not_found(toy: InHouseMCP):
    with pytest.raises(MCPError) as ei:
        toy.call_tool("nope", {})
    assert ei.value.code == ERR_TOOL_NOT_FOUND


def test_run_http_serves_build_asgi_app_via_uvicorn(monkeypatch):
    """Phase-2: run(transport="http", ...) serves build_asgi_app() via uvicorn.
    Proves the seam is FILLED with the right wiring WITHOUT binding a socket —
    we monkeypatch uvicorn.run to capture the (app, host, port) it is handed and
    assert the served app is an ASGI callable that answers POST /mcp. No port is
    opened (the patched uvicorn.run never listens)."""
    import uvicorn  # available in this env (federation_server.py owns it)

    captured: dict = {}

    def _fake_uvicorn_run(app, host=None, port=None, **kw):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        # Do NOT listen — just record. This is the seam the real server fills.

    monkeypatch.setattr(uvicorn, "run", _fake_uvicorn_run)

    mcp = InHouseMCP("x")

    @mcp.tool(name="t.ping", description="ping")
    def t_ping():
        return {"pong": True}

    mcp.run(transport="http", host="127.0.0.1", port=8473, stateless_http=True)

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8473
    app = captured["app"]
    # The served app is the Starlette /mcp app — callable + answers POST /mcp.
    assert callable(app)
    out = _drive_asgi(app, _http_scope("POST", "/mcp"), json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "t.ping", "arguments": {}},
    }).encode("utf-8"))
    assert out["status"] == 200
    data = _parse_sse_first_data(out["body"].decode("utf-8"))
    assert data["result"]["structuredContent"] == {"pong": True}

    # streamable-http is an accepted alias for the same path.
    captured.clear()
    mcp.run(transport="streamable-http", host="0.0.0.0", port=9999)
    assert captured["port"] == 9999


def test_run_stdio_transport_is_not_implemented():
    """stdio has no in-house loop yet (the brain's wire is HTTP); run("stdio")
    raises NotImplementedError naming the supported transports. The seam exists
    with the FastMCP signature; only HTTP is served this phase."""
    mcp = InHouseMCP("x")
    with pytest.raises(NotImplementedError):
        mcp.run(transport="stdio")


def test_handle_raw_roundtrip_and_parse_error(toy: InHouseMCP):
    out = toy.handle_raw(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "ping"}))
    assert json.loads(out)["result"] == {}
    # bad JSON → -32700 parse error
    err = json.loads(toy.handle_raw("{bad"))
    assert err["error"]["code"] == mcp_core.ERR_PARSE
    # notification → None (no response string)
    assert toy.handle_raw(json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized"})) is None


def test_importing_mcp_core_does_not_mutate_syspath():
    """Guard: (re)importing mcp_core must not itself mutate sys.path — in
    particular it must never insert ArchHub/app (which would shadow the genuine
    `mcp` SDK, the pollution conftest.py fights). We measure the SPECIFIC
    guarantee about THIS module by snapshotting sys.path around a fresh import,
    rather than asserting a global process invariant (a sibling test in the full
    suite legitimately puts app/ on the path at collection time — that's not
    mcp_core's doing, and conftest re-pins the real `mcp` around it)."""
    import importlib

    before = list(sys.path)
    importlib.reload(mcp_core)
    after = list(sys.path)
    assert before == after, (
        f"mcp_core import mutated sys.path: added {set(after) - set(before)}"
    )
    # And the module pulls no app/ path of its own at import time.
    assert "ArchHub" not in "".join(
        p for p in (set(after) - set(before))
    )
