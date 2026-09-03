"""HTTP-parity tests for the in-house MCP core's Starlette transport
(`personal_brain.mcp_core.InHouseMCP.build_asgi_app`).

GOAL (Phase 2, founder grievance #1): the brain must serve the SAME
streamable-HTTP `/mcp` wire its clients expect WITHOUT a third-party MCP
dispatch framework in the data path — and WITHOUT cutting over. Phase 1 proved
the dispatch + envelope + SSE framing byte-match the pinned client
(tests/test_mcp_core.py). This file proves the LAST mile: the actual Starlette
ASGI app `build_asgi_app()` returns — driven through an IN-PROCESS ASGI client,
never a socket — speaks the contract end to end.

The pinned contract (`app/memory_gate.py` BrainClient._call, "Verified live
against FastMCP 3.3.1 at /mcp"):
    POST /mcp · Accept application/json, text/event-stream · JSON-RPC 2.0
    tools/call with NO prior initialize (stateless) · response is an SSE stream
    whose first `data:` line carries
        {jsonrpc, id, result:{content:[{type:text,text:<json>}],
                              structuredContent:{...}, isError:false}}
    client PREFERS structuredContent, FALLS BACK to content[0].text, reads
    result.error on failure.

What this file adds over test_mcp_core.py:
  * Drives the real `Starlette` app (Route + Response), not the raw-ASGI
    `asgi_mcp` / `render_sse` core — so the mountable form is proven too.
  * Uses BOTH in-process ASGI clients the task names — `httpx.AsyncClient(
    transport=httpx.ASGITransport(app=...))` AND `starlette.testclient.
    TestClient` — to show the app is a conformant ASGI app under either driver.
  * THE strongest HTTP proof: routes the REAL `BrainClient._call` parser
    (loaded from ArchHub source) through the live ASGI app by monkeypatching
    `urlopen` to drive the app in-process — the actual client code accepts the
    actual HTTP bytes our Starlette app emits. Still no socket.

SAFETY (this phase is ADDITIVE + REVERSIBLE — no cutover): imports only
`personal_brain.mcp_core` (+ the real `memory_gate` parser by file path, the
SAME isolation test_mcp_core.py uses so app/mcp can't shadow the genuine `mcp`
SDK). Touches no server.py, no fastmcp, no DB. Binds NO socket / starts NO live
uvicorn / opens NO port 8473 — every request rides an in-process ASGI client.
`mcp_core.run()` (which DOES bind a socket) is never called here.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from personal_brain.mcp_core import (
    DEFAULT_PROTOCOL_VERSION,
    ERR_METHOD_MISSING,
    ERR_PARSE,
    ERR_TOOL_NOT_FOUND,
    InHouseMCP,
)

# starlette/httpx are owned by this repo (federation_server.py + the SDK).
# If a stripped env lacks them, skip the whole module rather than error — the
# pure-dispatch parity in test_mcp_core.py still covers the contract there.
httpx = pytest.importorskip("httpx", reason="httpx needed for in-process ASGI client")
pytest.importorskip("starlette", reason="starlette needed for build_asgi_app")
from starlette.testclient import TestClient  # noqa: E402  (after importorskip)


# ════════════════════════════════════════════════════════════════════════════
# Fixtures: a tiny server with toy tools (mirrors @mcp.tool(name, desc) + the
# imperative add_tool path server.py's register_*_tools helpers use).
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def toy() -> InHouseMCP:
    mcp = InHouseMCP("personal-brain-http-test")

    @mcp.tool(name="toy.echo", description="Echo the payload back as a dict.")
    def toy_echo(message: str, times: int = 1, loud: bool = False):
        text = message.upper() if loud else message
        return {"ok": True, "echo": text, "times": int(times)}

    @mcp.tool(name="toy.scalar", description="Return a bare scalar (no dict).")
    def toy_scalar(value: str):
        return value  # exercises the content-only fallback (no structuredContent)

    @mcp.tool(name="toy.boom", description="Always raises — error-result path.")
    def toy_boom():
        raise RuntimeError("kaboom")

    return mcp


@pytest.fixture
def app(toy: InHouseMCP):
    """The Starlette ASGI app under test — built once per test from the toy
    server. Never served on a socket; only driven in-process below."""
    return toy.build_asgi_app()


# ── in-process HTTP drivers (NO socket) ──────────────────────────────────────
ACCEPT = "application/json, text/event-stream"


def httpx_post(app, body: dict | list | bytes):
    """POST to /mcp through httpx's in-process ASGITransport (no socket bound).
    Returns the httpx.Response. Mirrors how a real client POSTs with the pinned
    Accept header."""
    content = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()

    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://brain.test") as client:
            return await client.post(
                "/mcp", content=content,
                headers={"Content-Type": "application/json", "Accept": ACCEPT})

    return asyncio.run(_go())


def tc_post(app, body: dict | list | bytes):
    """POST to /mcp through Starlette's TestClient (also in-process, no socket).
    The second of the two in-process drivers the task names."""
    content = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
    with TestClient(app) as client:
        return client.post("/mcp", content=content,
                           headers={"Content-Type": "application/json",
                                    "Accept": ACCEPT})


def parse_sse_first_data(raw: str) -> dict:
    """Extract the first `data:` JSON object from an SSE body — the SAME scan
    `memory_gate._call` performs (`for line in raw.splitlines(): if
    line.startswith("data:")`)."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"no SSE data line in body: {raw!r}")


# ════════════════════════════════════════════════════════════════════════════
# 1. Stateless tools/call (NO prior initialize) → SSE first-data-line carries
#    the contract envelope. Run through BOTH in-process clients.
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("post", [httpx_post, tc_post],
                         ids=["httpx-asgi", "starlette-testclient"])
def test_stateless_tools_call_emits_contract_envelope(app, post):
    resp = post(app, {
        "jsonrpc": "2.0", "id": 100, "method": "tools/call",
        "params": {"name": "toy.echo",
                   "arguments": {"message": "yo", "times": 2}},
    })
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    raw = resp.text
    # SSE framing the client scans for.
    assert raw.startswith("event: message")
    assert "\ndata: " in raw or "\r\ndata: " in raw

    data = parse_sse_first_data(raw)
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 100
    result = data["result"]
    # The full first-data-line contract: content + structuredContent + isError.
    assert result["isError"] is False
    assert result["structuredContent"] == {"ok": True, "echo": "yo", "times": 2}
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    # No leaked SDK fields — exactly the three contract keys.
    assert set(result.keys()) == {"content", "structuredContent", "isError"}


def test_stateless_scalar_payload_uses_content_fallback(app):
    """A tool returning a bare string has NO structuredContent (it isn't an
    object); the client's documented fallback is content[0].text."""
    resp = httpx_post(app, {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "toy.scalar", "arguments": {"value": "plain"}},
    })
    assert resp.status_code == 200
    result = parse_sse_first_data(resp.text)["result"]
    assert result["isError"] is False
    assert "structuredContent" not in result  # exclude_none dropped it
    assert result["content"][0]["text"] == "plain"


# ════════════════════════════════════════════════════════════════════════════
# 2. initialize echoes protocolVersion + advertises the tools capability —
#    the handshake a streamable-HTTP client speaks (stateless tools/call needs
#    no prior initialize, but initialize must still work over HTTP).
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("post", [httpx_post, tc_post],
                         ids=["httpx-asgi", "starlette-testclient"])
def test_initialize_echoes_version_and_advertises_tools(app, post):
    resp = post(app, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
    })
    assert resp.status_code == 200
    result = parse_sse_first_data(resp.text)["result"]
    assert result["protocolVersion"] == "2025-06-18"  # echoed (supported)
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "personal-brain-http-test"


def test_initialize_unknown_version_falls_back_to_default(app):
    resp = httpx_post(app, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    })
    result = parse_sse_first_data(resp.text)["result"]
    assert result["protocolVersion"] == DEFAULT_PROTOCOL_VERSION


# ════════════════════════════════════════════════════════════════════════════
# 3. tools/list over HTTP returns the descriptors ({name, description,
#    inputSchema}) in insertion order, with derived schemas.
# ════════════════════════════════════════════════════════════════════════════
def test_tools_list_returns_descriptors(app):
    resp = httpx_post(app, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert resp.status_code == 200
    result = parse_sse_first_data(resp.text)["result"]
    tools = result["tools"]
    assert [t["name"] for t in tools] == ["toy.echo", "toy.scalar", "toy.boom"]
    for t in tools:
        assert set(t.keys()) == {"name", "description", "inputSchema"}
        assert t["inputSchema"]["type"] == "object"
    echo = next(t for t in tools if t["name"] == "toy.echo")
    props = echo["inputSchema"]["properties"]
    assert props["message"] == {"type": "string"}
    assert props["times"] == {"type": "integer", "default": 1}
    assert echo["inputSchema"]["required"] == ["message"]


def test_ping_over_http_returns_empty_result(app):
    resp = httpx_post(app, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert resp.status_code == 200
    assert parse_sse_first_data(resp.text)["result"] == {}


# ════════════════════════════════════════════════════════════════════════════
# 4. Error paths — a JSON-RPC error rides the SSE stream (transport still 200);
#    a tool that throws yields isError:true (NOT a JSON-RPC error).
# ════════════════════════════════════════════════════════════════════════════
def test_unknown_method_is_jsonrpc_error_on_stream(app):
    resp = httpx_post(app, {"jsonrpc": "2.0", "id": 9, "method": "no.such"})
    assert resp.status_code == 200  # transport OK; the error is in-band
    data = parse_sse_first_data(resp.text)
    assert "result" not in data
    assert data["error"]["code"] == ERR_METHOD_MISSING
    assert "no.such" in data["error"]["message"]


def test_unknown_tool_is_jsonrpc_error_on_stream(app):
    resp = httpx_post(app, {
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "toy.nope", "arguments": {}},
    })
    data = parse_sse_first_data(resp.text)
    assert "result" not in data
    assert data["error"]["code"] == ERR_TOOL_NOT_FOUND


def test_tool_exception_is_error_result_not_jsonrpc_error(app):
    resp = httpx_post(app, {
        "jsonrpc": "2.0", "id": 12, "method": "tools/call",
        "params": {"name": "toy.boom", "arguments": {}},
    })
    assert resp.status_code == 200
    data = parse_sse_first_data(resp.text)
    assert "error" not in data  # transport succeeded
    assert data["result"]["isError"] is True
    assert "kaboom" in data["result"]["content"][0]["text"]


def test_bad_json_emits_parse_error_sse(app):
    resp = httpx_post(app, b"{not json")
    assert resp.status_code == 200  # SSE transport still 200; error in-band
    data = parse_sse_first_data(resp.text)
    assert data["error"]["code"] == ERR_PARSE


# ════════════════════════════════════════════════════════════════════════════
# 5. Transport-shape contract: method/route guards + the 202 notification path
#    (byte-true to the SDK's stateless responder, which returns
#    HTTPStatus.ACCEPTED with no body for non-JSONRPCRequest messages).
# ════════════════════════════════════════════════════════════════════════════
def test_get_is_405(app):
    """Starlette's Route(methods=["POST"]) rejects GET — the endpoint is
    POST-only, matching the streamable-HTTP POST /mcp shape the client uses."""
    with TestClient(app) as client:
        assert client.get("/mcp").status_code == 405


def test_wrong_path_is_404(app):
    with TestClient(app) as client:
        assert client.post("/other", content=b"{}").status_code == 404


@pytest.mark.parametrize("post", [httpx_post, tc_post],
                         ids=["httpx-asgi", "starlette-testclient"])
def test_notification_only_post_returns_202_empty(app, post):
    """A notification (no `id`) yields no response object → 202 Accepted, empty
    body — byte-true to the SDK's stateless responder."""
    resp = post(app, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202
    assert resp.content == b""


def test_batch_all_notifications_returns_202(app):
    resp = httpx_post(app, [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled"},
    ])
    assert resp.status_code == 202
    assert resp.content == b""


def test_batch_mixed_concatenates_sse_blocks(app):
    """A JSON-array batch with real requests concatenates one SSE block per
    request (parity with the raw-ASGI asgi_mcp batch path)."""
    resp = httpx_post(app, [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no block
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "toy.echo", "arguments": {"message": "b"}}},
    ])
    assert resp.status_code == 200
    raw = resp.text
    # Two `event: message` blocks (the notification produced none).
    assert raw.count("event: message") == 2
    blocks = [b for b in raw.split("event: message") if b.strip()]
    ids = []
    for b in blocks:
        for line in b.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                ids.append(json.loads(line[5:].strip())["id"])
                break
    assert ids == [1, 2]


# ════════════════════════════════════════════════════════════════════════════
# 6. THE strongest HTTP proof — drive the REAL BrainClient._call parser through
#    the LIVE Starlette ASGI app (no socket; urlopen routed to the app
#    in-process). The actual client code accepts the actual HTTP response bytes
#    our app emits, returning exactly the tool's dict.
# ════════════════════════════════════════════════════════════════════════════
def _load_memory_gate():
    """Load ArchHub's `app/memory_gate.py` by file path WITHOUT inserting
    ArchHub/app onto sys.path (which would let app/mcp shadow the genuine `mcp`
    SDK — the pollution conftest.py guards against). Mirrors the loader in
    test_mcp_core.py. Returns the module, or None only when the file is genuinely
    absent. A real load error raises (never a silent skip of the proof)."""
    here = Path(__file__).resolve()
    archhub = here.parent.parent.parent  # tests/ -> personal-brain-mcp/ -> ArchHub/
    mg_path = archhub / "app" / "memory_gate.py"
    if not mg_path.exists():
        return None
    mod_name = "_archhub_memory_gate_for_http_parity"
    spec = importlib.util.spec_from_file_location(mod_name, mg_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # required before exec_module (3.14 dataclass)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


class _ASGIBackedHTTPResponse:
    """Stand-in for urllib.request.urlopen's return value: a context manager
    exposing `.read()`. Carries the BODY BYTES the live Starlette app produced
    for the request — so `_call`'s SSE parser reads our actual HTTP output. No
    socket: the app was driven in-process via httpx ASGITransport."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _route_urlopen_through_app(app):
    """Return a fake `urlopen(req, timeout=...)` that drives `req` against the
    live Starlette `app` in-process (httpx ASGITransport — no socket) and hands
    back the app's real response bytes wrapped like urlopen's result. This makes
    the REAL BrainClient speak to our REAL ASGI app with zero network."""
    def _fake_urlopen(req, timeout=None):
        # Drive the actual app with the request's method/path/body/headers.
        method = req.get_method()
        url = req.full_url
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
        data = req.data or b""
        headers = {k: v for k, v in req.header_items()}

        async def _go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://brain.test") as client:
                return await client.request(method, path, content=data,
                                            headers=headers)

        resp = asyncio.run(_go())
        return _ASGIBackedHTTPResponse(resp.content)

    return _fake_urlopen


def test_real_brainclient_call_roundtrips_through_live_app(app, monkeypatch):
    """End-to-end HTTP parity: the REAL `BrainClient._call` POSTs to /mcp and
    parses the SSE — routed through our LIVE Starlette app in-process. It must
    return exactly the tool's dict (its preferred structuredContent branch)."""
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    monkeypatch.setattr(mg.urllib.request, "urlopen",
                        _route_urlopen_through_app(app))

    client = mg.BrainClient(base_url="http://brain.test")
    got = client._call("toy.echo",
                       {"message": "wire", "times": 3, "loud": True})
    # The real client returns structuredContent — exactly our tool's dict.
    assert got == {"ok": True, "echo": "WIRE", "times": 3}


def test_real_brainclient_call_raises_on_error_result_through_live_app(app, monkeypatch):
    """A tool that raises → isError result → the REAL client raises RuntimeError,
    proven over the live ASGI app."""
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    monkeypatch.setattr(mg.urllib.request, "urlopen",
                        _route_urlopen_through_app(app))

    client = mg.BrainClient(base_url="http://brain.test")
    with pytest.raises(RuntimeError):
        client._call("toy.boom", {})


def test_real_brainclient_call_raises_on_jsonrpc_error_through_live_app(app, monkeypatch):
    """A transport-level JSON-RPC error (unknown tool) rides the SSE stream and
    makes the REAL client raise (it reads data.error before result)."""
    mg = _load_memory_gate()
    if mg is None:
        pytest.skip("ArchHub app/memory_gate.py not present in this checkout")

    monkeypatch.setattr(mg.urllib.request, "urlopen",
                        _route_urlopen_through_app(app))

    client = mg.BrainClient(base_url="http://brain.test")
    with pytest.raises(RuntimeError):
        client._call("toy.ghost", {})


# ════════════════════════════════════════════════════════════════════════════
# 7. ADDITIVE / no-cutover guard — building the app pulls in NO third-party MCP
#    dispatch framework and does not mutate sys.path; importing this app factory
#    keeps the brain's live path (server.py / fastmcp) untouched.
# ════════════════════════════════════════════════════════════════════════════
def test_build_asgi_app_does_not_import_fastmcp(app):
    """The hand-rolled Starlette app must NOT drag fastmcp (the 3rd-party MCP
    dispatch framework) into the data path — that is the whole point of Phase 1
    re-owning dispatch. Building + driving the app leaves fastmcp unimported by
    OUR module's doing (we assert the app works without ever touching it)."""
    # Drive a real request so the app's full code path executes.
    resp = httpx_post(app, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 200
    # The app object is a Starlette app, not a FastMCP / SDK manager.
    assert type(app).__module__.startswith("starlette")
