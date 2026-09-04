"""Provider-bound MCP stdio adapter for the clean coordination host."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from urllib.request import Request, urlopen
import uuid

from mcp.server.fastmcp import FastMCP

from .clean_coordination_host import (
    CoordinationIdentity,
    sign_coordination_request,
)
from .runtime_caller_capability import WindowsDpapiCallerKeyStore
from .universal_cell import InvalidCell


DEFAULT_ENDPOINT = "http://127.0.0.1:8474/coordination"


def _health_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))


def _host_is_healthy(endpoint: str) -> bool:
    try:
        with urlopen(
            Request(_health_url(endpoint), method="GET"),
            timeout=2,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return type(payload) is dict and payload.get("ok") is True
    except Exception:
        return False


def ensure_local_coordination_host(endpoint: str = DEFAULT_ENDPOINT) -> None:
    """Start exactly one hidden clean graph owner when the local host is absent."""
    if _host_is_healthy(endpoint):
        return
    if endpoint != DEFAULT_ENDPOINT:
        raise RuntimeError("clean coordination host is unavailable")
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    lock_path = Path(local) / "ArchHub" / "unified-authority" / "host-start.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b", buffering=0) as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
        stream.seek(0)
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        try:
            if _host_is_healthy(endpoint):
                return
            flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "nodelang.clean_coordination_service",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8474",
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
            )
            deadline = time.monotonic() + 90.0
            while time.monotonic() < deadline:
                if _host_is_healthy(endpoint):
                    return
                if process.poll() is not None:
                    break
                time.sleep(0.25)
            raise RuntimeError("clean coordination host failed to start")
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def identity_from_environment(
    environment: Mapping[str, str] | None = None,
) -> CoordinationIdentity:
    env = os.environ if environment is None else environment
    vendor = str(env.get("ARCHHUB_COORDINATION_VENDOR", "")).strip().lower()
    if not vendor:
        raise RuntimeError("ARCHHUB_COORDINATION_VENDOR is required")
    candidates = {
        "codex": ("CODEX_THREAD_ID",),
        "claude": ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"),
        "gemini": ("GEMINI_SESSION_ID",),
        "antigravity": ("ANTIGRAVITY_SESSION_ID",),
        # OpenCode passes no session variable to MCP servers; its config carries a
        # stable identity per install, set by the plugin per session when it can.
        "opencode": ("OPENCODE_SESSION_ID", "ARCHHUB_COORDINATION_SESSION"),
    }.get(vendor, ())
    derived = next(
        (
            str(env.get(name, "")).strip()
            for name in candidates
            if str(env.get(name, "")).strip()
        ),
        "",
    )
    session_id = derived
    if not session_id:
        raise RuntimeError(
            "a stable provider session identity is required; random fallback is denied"
        )
    model = str(
        env.get("ARCHHUB_COORDINATION_MODEL", "provider-selected")
    ).strip()
    return CoordinationIdentity(vendor, session_id, model).normalized()


class LocalCoordinationClient:
    def __init__(
        self,
        identity: CoordinationIdentity,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        key_store: WindowsDpapiCallerKeyStore | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.path != "/coordination"
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1024 <= parsed.port <= 65535
        ):
            raise InvalidCell("local coordination endpoint is not admitted")
        self.identity = identity.normalized()
        self.endpoint = endpoint
        ensure_local_coordination_host(endpoint)
        self.key_store = key_store or WindowsDpapiCallerKeyStore(
            WindowsDpapiCallerKeyStore.default_path()
        )
        self.key_store.ensure(self.identity.key_id)

    def call(
        self,
        method: str,
        parameters: Mapping[str, object] | None = None,
        *,
        timeout_seconds: float = 35.0,
    ) -> dict[str, object]:
        signed = sign_coordination_request(
            self.key_store,
            self.identity,
            method,
            parameters or {},
        )
        body = json.dumps(
            signed.to_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except Exception:
                detail = "coordination request was denied"
            raise RuntimeError(str(detail)) from exc
        except (URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("clean coordination host is unavailable") from exc
        if type(payload) is not dict or payload.get("ok") is not True:
            raise RuntimeError("clean coordination response is invalid")
        return payload


def build_server(
    client: LocalCoordinationClient | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> FastMCP:
    control = client or LocalCoordinationClient(
        identity_from_environment(environment)
    )
    mcp = FastMCP("archhub-clean-agent-coordination")

    @mcp.tool(name="coordination.register_session")
    def register_session() -> dict[str, object]:
        return control.call("register_session")

    @mcp.tool(name="coordination.list_agents")
    def list_agents() -> dict[str, object]:
        return control.call("list_agents")

    @mcp.tool(name="coordination.workshop_lens")
    def workshop_lens() -> dict[str, object]:
        return control.call("workshop_lens")

    @mcp.tool(name="coordination.scope_lens")
    def scope_lens(scope_root: str) -> dict[str, object]:
        return control.call("scope_lens", {"scope_root": scope_root})

    @mcp.tool(name="coordination.revise_instance")
    def revise_instance(
        instance_root: str,
        scope_root: str,
        changes: dict[str, object],
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        return control.call("revise_instance", {
            "instance_root": instance_root,
            "scope_root": scope_root,
            "changes": changes,
            "expected_revision": expected_revision,
            "idempotency_key": idempotency_key,
        })

    @mcp.tool(name="coordination.send_message")
    def send_message(
        target: str,
        message: str,
        idempotency_key: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, object]:
        return control.call("send_message", {
            "target": target,
            "message": message,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
            "reply_to": reply_to,
        })

    @mcp.tool(name="coordination.followup_task")
    def followup_task(
        target: str,
        message: str,
        idempotency_key: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, object]:
        return control.call("followup_task", {
            "target": target,
            "message": message,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
            "reply_to": reply_to,
        })

    @mcp.tool(name="coordination.interrupt_agent")
    def interrupt_agent(
        target: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        return control.call("interrupt_agent", {
            "target": target,
            "message": reason,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
        })

    @mcp.tool(name="coordination.wait_agent")
    def wait_agent(
        after_revision: int = 0,
        target: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> dict[str, object]:
        return control.call(
            "wait_agent",
            {
                "after_revision": after_revision,
                "target": target,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds=float(timeout_seconds) + 5.0,
        )

    @mcp.tool(name="coordination.mark_message_read")
    def mark_message_read(
        message_root: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        return control.call("mark_message_read", {
            "message_root": message_root,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
        })

    return mcp


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_ENDPOINT",
    "LocalCoordinationClient",
    "build_server",
    "ensure_local_coordination_host",
    "identity_from_environment",
]
