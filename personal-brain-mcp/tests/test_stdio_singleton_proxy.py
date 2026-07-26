from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest
from mcp.shared.message import SessionMessage
import mcp.types as mt

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from personal_brain import server  # noqa: E402
from personal_brain import stdio_http_proxy as proxy  # noqa: E402

_LIVE_ACCEPTANCE_ENV = "ARCHHUB_RUN_LIVE_BRAIN_PROXY_ACCEPTANCE"


def _sm(payload: dict) -> SessionMessage:
    return SessionMessage(mt.JSONRPCMessage.model_validate(payload))


def _payload(message: SessionMessage) -> dict:
    return message.message.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )


def test_no_arg_stdio_launch_reuses_singleton_before_building(
    monkeypatch,
):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
    called = {"proxy": False}

    def fake_proxy() -> bool:
        called["proxy"] = True
        return True

    monkeypatch.setattr(proxy, "run_stdio_proxy_if_healthy", fake_proxy)
    monkeypatch.setattr(
        server,
        "build_server",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("build_server must not run through no-arg stdio proxy")
        ),
    )

    server.main([])

    assert called["proxy"] is True


@pytest.mark.parametrize(
    "failure",
    [
        lambda: False,
        lambda: (_ for _ in ()).throw(proxy.SingletonDaemonUnavailable("down")),
        lambda: (_ for _ in ()).throw(RuntimeError("proxy runtime failed")),
    ],
)
def test_no_arg_stdio_launch_fails_closed_without_building(
    monkeypatch,
    failure,
):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
    monkeypatch.setattr(proxy, "run_stdio_proxy_if_healthy", failure)
    monkeypatch.setattr(
        server,
        "build_server",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("build_server must not run after proxy failure")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 2


def test_explicit_local_stdio_preserves_local_fallback(monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
    monkeypatch.setattr(
        server,
        "_run_stdio_singleton_proxy_if_available",
        lambda: (_ for _ in ()).throw(
            AssertionError("explicit standalone stdio must bypass singleton proxy")
        ),
    )
    run_calls: list[dict] = []

    class FakeServer:
        def run(self, **kwargs):
            run_calls.append(kwargs)

    monkeypatch.setattr(server, "build_server", lambda **_kwargs: FakeServer())

    server.main(["--local-stdio"])

    assert run_calls == [{"transport": "stdio"}]


def test_main_stdio_entrypoint_defaults_to_no_arg_singleton_proxy(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(server, "main", lambda argv=None: calls.append(argv))

    server.main_stdio()

    assert calls == [[]]


def test_default_stdio_escape_hatch_is_ignored(monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
    monkeypatch.setenv("BRAIN_STDIO_ALLOW_LOCAL", "1")
    monkeypatch.setattr(proxy, "run_stdio_proxy_if_healthy", lambda: False)
    monkeypatch.setattr(
        server,
        "build_server",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("default stdio must not build local Brain")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 2


def test_http_daemon_launch_bypasses_stale_stdio_guard(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(
        server,
        "_run_stdio_singleton_proxy_if_available",
        lambda: (_ for _ in ()).throw(
            AssertionError("--http path must not call stale stdio guard")
        ),
    )
    monkeypatch.setattr(
        server,
        "_http_runtime_services_suspended",
        lambda: (True, "test"),
    )
    run_calls: list[dict] = []

    class FakeServer:
        def run(self, **kwargs):
            run_calls.append(kwargs)

    monkeypatch.setattr(server, "build_server", lambda **_kwargs: FakeServer())

    server.main(["--http", "9999"])

    assert run_calls == [{
        "transport": "http",
        "host": "127.0.0.1",
        "port": 9999,
        "stateless_http": True,
    }]


@pytest.mark.parametrize(
    "health",
    [
        {},
        {"ok": True},
        {"ok": True, "server_pid": 0},
        {"ok": "true", "server_pid": 106564},
    ],
)
def test_proxy_health_requires_true_ok_and_positive_integer_pid(monkeypatch, health):
    monkeypatch.setattr(proxy, "probe_health", lambda **_kwargs: health)
    monkeypatch.setattr(
        proxy,
        "_run_sdk_transport_bridge",
        lambda _url: (_ for _ in ()).throw(
            AssertionError("bridge must not run for untrusted health")
        ),
    )

    with pytest.raises(proxy.SingletonDaemonUnavailable):
        proxy.run_stdio_proxy_if_healthy()


def test_sdk_transport_bridge_pumps_requests_notifications_and_server_messages(
    monkeypatch,
):
    client_messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "brain.health", "arguments": {}},
        },
    ]
    http_seen: list[dict] = []
    stdio_seen: list[dict] = []

    @asynccontextmanager
    async def fake_stdio_server():
        stdio_writer, stdio_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        stdio_write, stdio_reader = anyio.create_memory_object_stream[SessionMessage](10)

        async def feed_client() -> None:
            async with stdio_writer:
                for message in client_messages:
                    await stdio_writer.send(_sm(message))

        async def capture_client() -> None:
            async with stdio_reader:
                async for message in stdio_reader:
                    stdio_seen.append(_payload(message))

        async with anyio.create_task_group() as tg:
            tg.start_soon(feed_client)
            tg.start_soon(capture_client)
            yield stdio_read, stdio_write
            tg.cancel_scope.cancel()

    @asynccontextmanager
    async def fake_streamable_http_client(_url: str, *, terminate_on_close: bool):
        http_writer, http_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        http_write, http_reader = anyio.create_memory_object_stream[SessionMessage](10)

        async def fake_daemon() -> None:
            async with http_reader, http_writer:
                async for message in http_reader:
                    payload = _payload(message)
                    http_seen.append(payload)
                    if "id" not in payload:
                        # Accepted notification: SDK transport represents the
                        # Streamable HTTP 202/no-body case by emitting nothing.
                        continue
                    if payload["id"] == 2:
                        await anyio.sleep(0.05)
                    await http_writer.send(_sm({
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {"for": payload["id"]},
                    }))
                    await http_writer.send(_sm({
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"method": payload["method"]},
                    }))

        async with anyio.create_task_group() as tg:
            tg.start_soon(fake_daemon)
            yield http_read, http_write, lambda: "session-id"
            tg.cancel_scope.cancel()

    monkeypatch.setattr(proxy, "stdio_server", fake_stdio_server)
    monkeypatch.setattr(proxy, "streamable_http_client", fake_streamable_http_client)

    async def run_with_bound() -> None:
        with anyio.fail_after(2):
            await proxy._run_sdk_transport_bridge("http://127.0.0.1:8473/mcp")

    anyio.run(run_with_bound)

    assert [message["method"] for message in http_seen] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert [message.get("id") for message in stdio_seen if "id" in message] == [
        1,
        2,
        3,
    ]
    assert any(
        message.get("method") == "notifications/progress"
        for message in stdio_seen
    )


def test_sdk_transport_bridge_fails_closed_when_pending_response_times_out(
    monkeypatch,
):
    monkeypatch.setenv("BRAIN_STDIO_PROXY_EOF_DRAIN_SEC", "0.1")
    client_messages = [
        {"jsonrpc": "2.0", "id": "lost", "method": "tools/list", "params": {}},
    ]
    http_seen: list[dict] = []
    stdio_seen: list[dict] = []

    @asynccontextmanager
    async def fake_stdio_server():
        stdio_writer, stdio_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        stdio_write, stdio_reader = anyio.create_memory_object_stream[SessionMessage](10)

        async def feed_client() -> None:
            async with stdio_writer:
                for message in client_messages:
                    await stdio_writer.send(_sm(message))

        async def capture_client() -> None:
            async with stdio_reader:
                async for message in stdio_reader:
                    stdio_seen.append(_payload(message))

        async with anyio.create_task_group() as tg:
            tg.start_soon(feed_client)
            tg.start_soon(capture_client)
            yield stdio_read, stdio_write
            tg.cancel_scope.cancel()

    @asynccontextmanager
    async def fake_streamable_http_client(_url: str, *, terminate_on_close: bool):
        http_writer, http_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        http_write, http_reader = anyio.create_memory_object_stream[SessionMessage](10)

        async def fake_daemon() -> None:
            async with http_reader, http_writer:
                async for message in http_reader:
                    http_seen.append(_payload(message))
                    # This simulates a daemon/transport defect: the client
                    # request was accepted but its response never arrives.

        async with anyio.create_task_group() as tg:
            tg.start_soon(fake_daemon)
            yield http_read, http_write, lambda: "session-id"
            tg.cancel_scope.cancel()

    monkeypatch.setattr(proxy, "stdio_server", fake_stdio_server)
    monkeypatch.setattr(proxy, "streamable_http_client", fake_streamable_http_client)

    async def run_with_bound() -> None:
        with anyio.fail_after(2):
            await proxy._run_sdk_transport_bridge("http://127.0.0.1:8473/mcp")

    with pytest.raises(ExceptionGroup) as exc:
        anyio.run(run_with_bound)

    assert exc.value.subgroup(proxy.SingletonDaemonUnavailable) is not None
    assert [message.get("id") for message in http_seen] == ["lost"]
    assert stdio_seen == []


def test_live_envless_stdio_subprocess_reuses_daemon_and_leaves_no_child():
    if os.environ.get(_LIVE_ACCEPTANCE_ENV) != "1":
        pytest.skip(f"set {_LIVE_ACCEPTANCE_ENV}=1 for live singleton acceptance")
    if sys.platform != "win32":
        pytest.skip("process-orphan acceptance is Windows-specific")

    health = proxy.probe_health()
    daemon_pid = health.get("server_pid")
    if health.get("ok") is not True or not isinstance(daemon_pid, int) or daemon_pid <= 0:
        pytest.skip("supervised Brain daemon is not healthy")

    before_processes = _stale_brain_processes()
    assert before_processes == []
    before = _stale_brain_process_ids()

    async def run_client() -> tuple[list[str], dict, str, list[dict]]:
        env = _minimal_subprocess_env()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "personal_brain.server"],
            env=env,
            cwd=str(_SRC.parent),
            encoding="utf-8",
            encoding_error_handler="replace",
        )
        with tempfile.TemporaryFile(
            mode="w+",
            encoding="utf-8",
            errors="replace",
        ) as errlog:
            with anyio.fail_after(20):
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        health_result = await session.call_tool("brain.health", {})
                        observed_children = await anyio.to_thread.run_sync(
                            _stale_brain_processes,
                        )
                        await anyio.sleep(0.2)
            errlog.seek(0)
            stderr = errlog.read()
        health_text = health_result.content[0].text
        return [
            tool.name for tool in tools.tools
        ], json.loads(health_text), stderr, observed_children

    (
        tool_names,
        proxied_health,
        stderr,
        transient_children,
    ) = anyio.run(run_client)
    after = _stale_brain_processes()
    leaked = [
        process for process in after
        if process["ProcessId"] not in before
    ]

    assert "brain.health" in tool_names
    assert proxied_health.get("server_pid") == daemon_pid
    assert "stdio singleton proxy ON" in stderr
    assert f"pid {daemon_pid}" in stderr
    proxy_children = [
        process for process in transient_children
        if process.get("ParentProcessId") == os.getpid()
    ]
    assert proxy_children
    assert all(
        int(process.get("WorkingSetSize", 0)) < 512 * 1024 * 1024
        for process in proxy_children
    )
    assert leaked == []


def _stale_brain_process_ids() -> set[int]:
    return {int(process["ProcessId"]) for process in _stale_brain_processes()}


def _minimal_subprocess_env() -> dict[str, str]:
    keep = [
        "APPDATA",
        "COMSPEC",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "SystemDrive",
        "SystemRoot",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    ]
    env = {
        name: os.environ[name]
        for name in keep
        if name in os.environ
    }
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(_SRC),
    })
    return env


def _stale_brain_processes() -> list[dict]:
    command = r"""
$rows = Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -match 'personal_brain\.server' -and
    $_.CommandLine -notmatch '--http'
  } |
  Select-Object ProcessId, ParentProcessId, WorkingSetSize, CommandLine
if ($null -eq $rows) { '[]' }
else { $rows | ConvertTo-Json -Compress }
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    output = result.stdout.strip()
    if not output:
        return []
    data = json.loads(output)
    if isinstance(data, dict):
        return [data]
    return data
