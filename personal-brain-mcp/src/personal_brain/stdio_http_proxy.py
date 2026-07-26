"""SDK-backed stdio-to-HTTP MCP proxy for default stdio launches.

Fresh managed config uses the singleton Streamable HTTP daemon directly. A
client can still launch a no-arg stdio command transport
(`python -m personal_brain.server` or `personal-brain-stdio`). In that default
stdio case, this module reuses the supervised daemon through the official MCP
Python SDK instead of constructing a second heavy Brain process.

Protocol basis: MCP 2025-11-25 Streamable HTTP requires client JSON-RPC
notifications and responses to be POSTed, accepted notifications may return
202/no body, and request SSE streams may carry server messages before the
matching response. Both sides of this bridge use the official SDK transports:
`mcp.server.stdio.stdio_server` and
`mcp.client.streamable_http.streamable_http_client`.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import anyio
from mcp.client.streamable_http import streamable_http_client
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
import mcp.types as mt

DEFAULT_DAEMON_URL = "http://127.0.0.1:8473/mcp"
_OFF_VALUES = {"0", "off", "false", "no", "disabled"}
DEFAULT_HEALTH_TIMEOUT_SEC = 2.0
DEFAULT_EOF_DRAIN_SEC = 5.0


class SingletonDaemonUnavailable(RuntimeError):
    pass


def stdio_singleton_proxy_enabled() -> bool:
    value = os.environ.get("BRAIN_STDIO_SINGLETON_PROXY", "1").strip().lower()
    return value not in _OFF_VALUES


def run_stdio_proxy_if_healthy(*, url: str = DEFAULT_DAEMON_URL) -> bool:
    if not stdio_singleton_proxy_enabled():
        return False
    health = probe_health(url=url)
    server_pid = health.get("server_pid")
    if health.get("ok") is not True or not isinstance(server_pid, int) or server_pid <= 0:
        raise SingletonDaemonUnavailable("singleton Brain daemon is unavailable")
    print(
        "[brain] stdio singleton proxy ON"
        f" - reusing daemon pid {server_pid}",
        file=sys.stderr,
        flush=True,
    )
    anyio.run(_run_sdk_transport_bridge, url)
    return True


def probe_health(*, url: str = DEFAULT_DAEMON_URL) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": "stdio-singleton-probe",
        "method": "tools/call",
        "params": {"name": "brain.health", "arguments": {}},
    }
    response = anyio.run(
        _request_response_once,
        url,
        request,
        _health_timeout(),
    )
    try:
        text = response["result"]["content"][0]["text"]
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


async def _run_sdk_transport_bridge(url: str) -> None:
    pending = _PendingResponses()
    async with stdio_server() as (
        stdio_read,
        stdio_write,
    ), streamable_http_client(url, terminate_on_close=False) as (
        http_read,
        http_write,
        _get_session_id,
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(_pump_client_to_http, stdio_read, http_write, pending)
            tg.start_soon(_pump_http_to_client, http_read, stdio_write, pending)


async def _pump_client_to_http(
    source: Any,
    destination: Any,
    pending: "_PendingResponses",
) -> None:
    try:
        async with destination:
            async for item in source:
                if isinstance(item, Exception):
                    raise item
                await pending.add_from_client(item)
                await destination.send(item)
            await pending.wait_empty(_eof_drain_timeout())
    finally:
        await destination.aclose()


async def _pump_http_to_client(
    source: Any,
    destination: Any,
    pending: "_PendingResponses",
) -> None:
    try:
        async with destination:
            async for item in source:
                if isinstance(item, Exception):
                    raise item
                await pending.remove_from_server(item)
                await destination.send(item)
    finally:
        await destination.aclose()


class _PendingResponses:
    def __init__(self) -> None:
        self._ids: set[Any] = set()
        self._condition = anyio.Condition()

    async def add_from_client(self, message: SessionMessage) -> None:
        payload = _payload(message)
        if "id" not in payload or "method" not in payload:
            return
        async with self._condition:
            self._ids.add(payload["id"])
            self._condition.notify_all()

    async def remove_from_server(self, message: SessionMessage) -> None:
        payload = _payload(message)
        if not _is_matching_response(payload, payload.get("id")):
            return
        async with self._condition:
            self._ids.discard(payload.get("id"))
            self._condition.notify_all()

    async def wait_empty(self, timeout_s: float) -> None:
        with anyio.move_on_after(timeout_s) as scope:
            async with self._condition:
                while self._ids:
                    await self._condition.wait()
        async with self._condition:
            remaining = sorted(str(value) for value in self._ids)
        if scope.cancel_called or remaining:
            raise SingletonDaemonUnavailable(
                "timed out waiting for singleton daemon responses: "
                + ", ".join(remaining)
            )


async def _request_response_once(
    url: str,
    request: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    async with streamable_http_client(url, terminate_on_close=False) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        await write_stream.send(_session_message(request))
        with anyio.fail_after(timeout_s):
            async for item in read_stream:
                if isinstance(item, Exception):
                    raise item
                payload = _payload(item)
                if _is_matching_response(payload, request.get("id")):
                    return payload
    raise SingletonDaemonUnavailable("singleton Brain daemon returned no health response")


def _session_message(value: dict[str, Any]) -> SessionMessage:
    return SessionMessage(mt.JSONRPCMessage.model_validate(value))


def _payload(message: SessionMessage) -> dict[str, Any]:
    value = message.message.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    if not isinstance(value, dict):
        raise ValueError("MCP SDK emitted non-object JSON-RPC message")
    return value


def _is_matching_response(payload: dict[str, Any], req_id: Any) -> bool:
    return payload.get("id") == req_id and ("result" in payload or "error" in payload)


def _health_timeout() -> float:
    return _float_env("BRAIN_STDIO_PROXY_HEALTH_TIMEOUT_SEC", DEFAULT_HEALTH_TIMEOUT_SEC)


def _eof_drain_timeout() -> float:
    return _float_env("BRAIN_STDIO_PROXY_EOF_DRAIN_SEC", DEFAULT_EOF_DRAIN_SEC)


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, str(default))))
    except ValueError:
        return default
