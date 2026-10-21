"""Launcher-owned packaged Goose and a private view of existing host MCP tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time

from .goose_adapter import AcpTransport, GooseAdapter, GooseRefused


class GooseRuntime:
    def __init__(self, *, app_root, state_dir, control, process_factory=subprocess.Popen):
        self.app_root = Path(app_root).resolve()
        self.work_dir = Path(state_dir).resolve() / "goose"
        self.control = control
        self.process_factory = process_factory
        self.transport = None
        self.http = None
        self.thread = None
        self.socket = None
        self.host_extension = None
        self.job = None

    def start(self):
        if self.transport is not None:
            return self
        package = self.app_root / "runtime" / "goose"
        binary = package / "goose.exe"
        try:
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            with binary.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if manifest["version"] != "1.54.0" or digest != manifest["executable_sha256"]:
                raise ValueError
            if manifest["archive_sha256"] != "5c39bc91c3eadc231847e21a8a469e778431084437b233a63a950fee22db6239":
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise GooseRefused("The packaged Goose brain is missing or has a different digest. Repair the ArchHub package.") from None
        self.work_dir.mkdir(parents=True, exist_ok=True)
        config = self.work_dir / "config"
        config.mkdir(exist_ok=True)
        (config / "config.yaml").write_text(json.dumps({
            "GOOSE_PROVIDER": "openrouter", "GOOSE_MODEL": "openrouter/free",
            "GOOSE_MODE": "approve", "extensions": {}, "telemetry_enabled": False,
        }), encoding="utf-8")
        try:
            self._start_host_extension()
            # Allow only OS bootstrap variables. No inherited agent identity,
            # arbitrary provider URL, plugin, paid fallback or developer config.
            env = {k: v for k, v in os.environ.items() if k.upper() in {
                "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "COMSPEC",
                "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PATH",
            }}
            env.update({"GOOSE_PATH_ROOT": str(self.work_dir), "GOOSE_PROVIDER": "openrouter",
                        "GOOSE_MODEL": "openrouter/free", "GOOSE_MODE": "approve",
                        "GOOSE_TELEMETRY_ENABLED": "false", "OLLAMA_HOST": "http://127.0.0.1:11434"})
            from .model_router import discover_key, ModelRouteRefused
            try:
                key, _ = discover_key("openrouter")
            except ModelRouteRefused:
                key = ""
            if key:
                env["OPENROUTER_API_KEY"] = key
            process = self.process_factory([str(binary), "acp"], cwd=str(self.work_dir), env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.transport = AcpTransport(process)
            from .session_link_transport import _OwnedProcessJob
            self.job = _OwnedProcessJob(process)
            init = self.transport.request("initialize", {"protocolVersion": 1,
                "clientInfo": {"name": "ArchHub BABOOM", "version": "1"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}},
                deadline=time.monotonic() + 10.0)
            if init.get("protocolVersion") != 1:
                raise GooseRefused("The packaged Goose ACP version is incompatible.")
            return self
        except BaseException:
            self.close()
            raise

    def _start_host_extension(self):
        from mcp.server.fastmcp import FastMCP
        from .native_host_tools import register_host_tools
        import uvicorn
        token = secrets.token_urlsafe(32)
        mcp = FastMCP("archhub-hosts", json_response=True, stateless_http=True)
        register_host_tools(mcp, self.control, read_only=True)
        app = mcp.streamable_http_app()

        class Auth:
            def __init__(self, app):
                self.app = app
            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    headers = dict(scope["headers"])
                    if not secrets.compare_digest(headers.get(b"authorization", b""), ("Bearer " + token).encode()):
                        await send({"type": "http.response.start", "status": 401, "headers": []})
                        await send({"type": "http.response.body", "body": b"Unauthorized"})
                        return
                await self.app(scope, receive, send)

        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(16)
        port = self.socket.getsockname()[1]
        self.http = uvicorn.Server(uvicorn.Config(Auth(app), log_level="error", access_log=False, lifespan="on"))
        self.thread = threading.Thread(target=lambda: self.http.run(sockets=[self.socket]),
                                       name="archhub-goose-host-read", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 4
        while not self.http.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                raise GooseRefused("The private ArchHub host read extension did not start.")
            time.sleep(0.01)
        self.host_extension = {"type": "http", "name": "archhub-hosts",
            "url": f"http://127.0.0.1:{port}/mcp", "headers": [{"name": "Authorization", "value": "Bearer " + token}]}

    def close(self):
        try:
            if self.transport is not None:
                self.transport.close()
        finally:
            if self.job is not None:
                self.job.close()
        if self.http is not None:
            self.http.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=3)
        if self.socket is not None:
            self.socket.close()


def start_goose_for_baboom(server, host, *, app_root, state_dir, cancellation_event=None):
    """Called by the real launcher after the signed companion host connects."""
    current = getattr(server, "goose_runtime", None)
    if current is not None:
        return current
    runtime = GooseRuntime(app_root=app_root, state_dir=state_dir, control=host)
    try:
        runtime.start()
    except BaseException:
        runtime.close()
        raise
    server.goose_runtime = runtime
    server.goose_brain = GooseAdapter(runtime)
    if cancellation_event is not None and cancellation_event.is_set():
        runtime.close()
        raise GooseRefused("ArchHub is closing; Goose startup was cancelled.")
    return runtime
