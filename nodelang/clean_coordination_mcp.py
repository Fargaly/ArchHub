"""Coordination tools; default stdio attaches to the installed application's Workshop.

The explicit legacy client remains only for consumers awaiting migration. Failure
to attach to the application must never start a substitute graph owner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping, TYPE_CHECKING
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

if TYPE_CHECKING:
    from .installed_workshop_coordination import InstalledWorkshopCoordinationClient


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
        start_if_missing: bool = True,
    ) -> None:
        if type(start_if_missing) is not bool:
            raise ValueError("start_if_missing must be a boolean")
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
        if start_if_missing:
            ensure_local_coordination_host(endpoint)
        elif not _host_is_healthy(endpoint):
            # An attaching client must never replace a temporarily unavailable
            # owner or start background work. Later request failure also closes
            # normally; call() contains no host-start or request retry path.
            raise RuntimeError("clean coordination host is unavailable")
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
        if (method in {"execute_workshop_task", "run_workshop_task"} and type(payload) is dict and
                payload.get("ok") is False and
                payload.get("message_root") == (parameters or {}).get("message_root") and
                type(payload.get("error")) is str):
            if payload.get("outcome") == "uncertain":
                return payload
            if (payload.get("outcome") == "failed" and
                    all(type(payload.get(key)) is str and payload[key] for key in ("receipt", "effect")) and
                    type(payload.get("accepted_revision")) is int and payload["accepted_revision"] >= 0 and
                    type(payload.get("replayed")) is bool):
                return payload
        if type(payload) is not dict or payload.get("ok") is not True:
            raise RuntimeError("clean coordination response is invalid")
        return payload


def build_server(
    client: LocalCoordinationClient | InstalledWorkshopCoordinationClient | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> FastMCP:
    if client is None:
        # Lazy imports avoid the shared-tool registration cycle. native_agent_mcp
        # calls this factory with its explicitly bound client, so it cannot fall
        # back to LocalCoordinationClient or start a second graph owner.
        from .native_agent_mcp import build_server as build_installed_server
        from .native_agent_session import NativeAgentSession
        return build_installed_server(session=NativeAgentSession(environment=environment))
    control = client
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
        execution_root: str | None = None,
    ) -> dict[str, object]:
        return control.call("followup_task", {
            "target": target,
            "message": message,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
            "reply_to": reply_to,
            "execution_root": execution_root,
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

    @mcp.tool(name="coordination.claim_workshop_message")
    def claim_workshop_message(
        message_root: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Claim a connected task once; this does not grant tool execution.

        Preserve the key for reconciliation. A consumed claim must not be
        retried as fresh work after an uncertain result.
        """
        return control.call("claim_workshop_message", {
            "message_root": message_root,
            "idempotency_key": idempotency_key,
        })

    @mcp.tool(name="coordination.attach_agent")
    def attach_agent(target: str, idempotency_key: str) -> dict[str, object]:
        """Attach an enrolled session through existing source and Workshop policy.

        A replayed receipt is historical, not proof of current membership.
        """
        return control.call("attach_agent", {"target": target, "idempotency_key": idempotency_key})

    @mcp.tool(name="coordination.execute_workshop_task")
    def execute_workshop_task(message_root: str) -> dict[str, object]:
        """Execute the node wired to this worker's read task using its saved inputs.

        The runtime must supply an adapter. Repeating the same task retains
        its execution identity; uncertain results require reconciliation.
        """
        return control.call("execute_workshop_task", {"message_root":message_root})

    @mcp.tool(name="coordination.publish_workshop_result")
    def publish_workshop_result(message_root: str) -> dict[str, object]:
        """Publish this task's receipted outcome as a reply without re-executing it."""
        return control.call("publish_workshop_result", {"message_root":message_root})

    @mcp.tool(name="coordination.run_workshop_task")
    def run_workshop_task(message_root: str, idempotency_key: str) -> dict[str, object]:
        """Claim one targeted task, execute its connected node, and publish the result.

        Use one stable claim UUID. A repeated claim never starts another call.
        If interrupted, reconcile with execute_workshop_task or
        publish_workshop_result; never replace the task to retry an uncertain effect.
        Published results still need independent review.
        """
        return control.call("run_workshop_task", {
            "message_root":message_root, "idempotency_key":idempotency_key})

    @mcp.tool(name="coordination.detach_agent")
    def detach_agent(target: str, idempotency_key: str) -> dict[str, object]:
        """Remove Workshop membership while preserving enrollment and history."""
        return control.call("detach_agent", {"target": target, "idempotency_key": idempotency_key})

    # Keep ordinary content positions separate from clean graph revisions and
    # message Cells. This backend holds an existing process-local capability;
    # constructing the interface never enrolls another installed session.
    from .installed_workshop_coordination import InstalledWorkshopCoordinationClient
    if isinstance(control, InstalledWorkshopCoordinationClient):
        for name in (
            "send_message", "revise_instance", "followup_task", "interrupt_agent", "wait_agent",
            "mark_message_read", "claim_workshop_message", "attach_agent",
            "execute_workshop_task", "publish_workshop_result", "run_workshop_task", "detach_agent",
        ):
            mcp.remove_tool("coordination." + name)

        @mcp.tool(name="coordination.send_message")
        def send_installed_message(
            target: str,
            message: str,
            idempotency_key: str,
            reply_to: str | None = None,
        ) -> dict[str, object]:
            """Send with one caller-held key; reuse that key after a lost reply."""
            if not idempotency_key.strip():
                raise ValueError("a nonempty caller idempotency_key is required")
            return control.call("send_message", {
                "target": target, "message": message,
                "idempotency_key": idempotency_key, "reply_to": reply_to,
            })

        @mcp.tool(name="coordination.read_messages")
        def read_messages(limit: int = 50, before: int | None = None) -> dict[str, object]:
            """Read an admitted ordinary-message page; before is a message sequence."""
            return control.call("read_messages", {"limit": limit, "before": before})

        @mcp.tool(name="coordination.read_message")
        def read_message(message_id: str, sequence: int) -> dict[str, object]:
            """Read and verify one exact ordinary message at its saved sequence."""
            return control.call("read_message", {"message_id": message_id, "sequence": sequence})

        @mcp.tool(name="coordination.acknowledge_message")
        def acknowledge_message(message_id: str, sequence: int, idempotency_key: str) -> dict[str, object]:
            """Submit an explicit acknowledgement reply; this does not claim completion."""
            return control.call("acknowledge_message", {
                "message_id": message_id, "sequence": sequence, "idempotency_key": idempotency_key,
            })

        @mcp.tool(name="coordination.claim_work")
        def claim_work(work_root: str) -> dict[str, object]:
            """Claim an exact Governed Work node; a message ID is not a Work root.

            A claim grants no execution authority. Reconcile an uncertain reply
            against Work state before making another claim.
            """
            return control.call("claim_work", {"work_root": work_root})

    return mcp


def main() -> None:
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-actor',help='Exact existing actor: expose dormant recovery tools without bootstrap')
    args=parser.parse_args()
    if args.expected_actor:
        from .native_agent_session import NativeAgentSession
        from .native_agent_mcp import build_recovery_server
        # The supplied ID is only a constraint. Existing native identity and
        # signed reconciliation must establish custody before any continuation.
        owner=NativeAgentSession(expected_agent_session=args.expected_actor)
        server,_activate=build_recovery_server(owner)
        server.run(transport='stdio')
    else:
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
