"""Explicit standalone fallback for the Universal Cell machine transport.

The normal ArchHub ApplicationServer is the production owner of the signed
transport. This module exists only for an explicitly chosen headless authority
or an isolated proof; it must never silently become a second owner of a graph
already served by the normal application host.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

from .application_machine_transport import (
    UniversalRuntimeClient,
    default_runtime_descriptor_path,
)
from .application_server import ApplicationServer
from .cell_attestations import CourtInvocation, CourtResult
from .persistence import default_state_path
from .runtime_credentials import BrowserCredentialVault


BRIDGE_HEARTBEAT_SECONDS = 5.0
BRIDGE_PROOF_INTERVAL_SECONDS = 30.0
BRIDGE_PROOF_TIMEOUT_SECONDS = 15.0
BRIDGE_PROOF_ATTEMPTS = 2
BRIDGE_PROOF_RETRY_DELAY_SECONDS = 0.5
_RUNTIME_COMPLIANCE_CHECKS = (
    "runtime-detected",
    "required-hooks",
    "schema-valid",
    "brain-connected",
    "scope-gate",
    "workshop-authority",
)


def default_status_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return root / "ArchHub" / "authority-bridge.json"


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(".%s.%s.tmp" % (path.name, os.getpid()))
    temp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temp.replace(path)


def _runtime_compliance_runner(
    invocation: CourtInvocation,
) -> CourtResult:
    """Observe vendor wiring; leave all policy and evidence in the Cell court."""
    failed = {name: False for name in _RUNTIME_COMPLIANCE_CHECKS}
    runtime = invocation.external_parameters.get("runtime", "")
    try:
        brain_source = (
            Path(__file__).resolve().parents[2]
            / "12.PRODUCTION"
            / "personal-brain-mcp"
            / "src"
        )
        if not brain_source.is_dir():
            raise RuntimeError("Brain physical adapter source is unavailable")
        source = str(brain_source)
        if source not in sys.path:
            sys.path.insert(0, source)
        from personal_brain.hook_coverage import (
            observe_runtime_compliance,
        )

        observation = observe_runtime_compliance(runtime)
        checks = observation.get("checks")
        if (
            type(checks) is not dict
            or set(checks) != set(_RUNTIME_COMPLIANCE_CHECKS)
            or any(type(value) is not bool for value in checks.values())
        ):
            raise RuntimeError(
                "Brain physical adapter returned an invalid observation"
            )
        return CourtResult(
            passed=all(checks.values()),
            checks=checks,
            details={
                "adapter": "personal-brain-hook-auditor-v1",
                "client": str(observation.get("client") or "unknown"),
                "status": str(observation.get("status") or "red"),
                "issueCount": str(observation.get("issue_count") or 0),
            },
        )
    except Exception as exc:
        return CourtResult(
            passed=False,
            checks=failed,
            details={
                "adapter": "personal-brain-hook-auditor-v1",
                "status": "red",
                "errorType": type(exc).__name__,
            },
        )


def _build_server(
    *,
    state_path: Path,
    descriptor_path: Path,
) -> ApplicationServer:
    credentials = BrowserCredentialVault(
        Path(state_path).with_name("browser-session-v1.dpapi")
    ).load_or_create()
    return ApplicationServer(
        host="127.0.0.1",
        port=0,
        state_path=state_path,
        live_watch=False,
        enable_machine_transport=True,
        enable_machine_projection_prewarm=True,
        machine_descriptor_path=descriptor_path,
        browser_session_credentials=credentials,
        runtime_compliance_runner=_runtime_compliance_runner,
    )


def _proof(server: ApplicationServer, descriptor_path: Path) -> dict[str, object]:
    """Bounded, authenticated proof that the bridge still serves its graph.

    This deliberately avoids the governed-work index. The bridge heartbeat is a
    liveness/ownership proof, not a queue projection, and a heavy projection must
    not be able to degrade the authority owner by timing out its own proof loop.
    """
    client = UniversalRuntimeClient(
        descriptor_path,
        server.machine_transport.key_provider,
    )
    handoff = client.request(
        "GET",
        "/api/universal/browser-handoff",
        {},
        response_timeout_seconds=BRIDGE_PROOF_TIMEOUT_SECONDS,
    )
    return {
        "ok": (
            handoff.get("application")
            == server.universal_registry.application_root
            and handoff.get("supported") is True
            and handoff.get("one_use_route")
            == "POST /api/universal/browser-handoff"
        ),
        "application": handoff.get("application"),
        "registry": server.universal_registry.governed_work_registry_root,
        "agent_session": handoff.get("agent_session"),
        "revision": handoff.get("revision"),
        "server_url": handoff.get("server_url"),
        "workshop": server.universal_registry.workshop_root,
        "proof_route": "GET /api/universal/browser-handoff",
    }


def _safe_proof(server: ApplicationServer, descriptor_path: Path) -> dict[str, object]:
    """Turn a runtime-proof failure into safe operational status, never a restart."""
    last_exc: Exception | None = None
    for attempt in range(BRIDGE_PROOF_ATTEMPTS):
        try:
            return _proof(server, descriptor_path)
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < BRIDGE_PROOF_ATTEMPTS:
                time.sleep(BRIDGE_PROOF_RETRY_DELAY_SECONDS)
    assert last_exc is not None
    message = str(last_exc).casefold()
    if "did not respond" in message:
        reason = "machine transport did not answer inside the bridge proof window"
    elif "pipe" in message or "descriptor" in message:
        reason = "machine transport is unavailable"
    else:
        reason = "machine transport proof failed"
    return {
        "ok": False,
        "reason": reason,
        "error_type": type(last_exc).__name__,
    }


def _safe_prewarm(server: ApplicationServer) -> dict[str, object]:
    """Read background projection-prewarm status without blocking bridge liveness."""
    status = getattr(server, "universal_machine_projection_prewarm_status", None)
    if not callable(status):
        return {
            "ok": True,
            "status": "skipped",
            "reason": "server has no machine projection prewarm status",
        }
    try:
        return status()
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "reason": "machine projection prewarm status failed",
            "error_type": type(exc).__name__,
        }


def _machine_transport_is_serving(server: ApplicationServer) -> bool:
    """Require the pipe worker as well as the HTTP projection to stay alive."""
    transport = server.machine_transport
    return transport is not None and transport.is_serving


def _terminal_proof(exc: Exception) -> dict[str, object]:
    """Keep a bounded, non-secret reason when a bridge exits unexpectedly."""
    message = str(exc).casefold()
    if "machine transport" in message:
        reason = "machine transport worker stopped"
    elif "http worker" in message:
        reason = "authority bridge HTTP worker stopped"
    else:
        reason = "authority bridge stopped unexpectedly"
    return {
        "ok": False,
        "reason": reason,
        "error_type": type(exc).__name__,
    }


def bridge_payload(
    *,
    server: ApplicationServer,
    descriptor_path: Path,
    state_path: Path,
    status: str,
    proof: dict[str, object] | None = None,
    prewarm: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema": "archhub-authority-bridge-runtime/v1",
        "status": status,
        "pid": os.getpid(),
        "server_url": server.url,
        "state_path": str(state_path),
        "universal_state_path": str(server.universal_state_path or ""),
        "descriptor_path": str(descriptor_path),
        "machine_transport": server.machine_transport is not None,
        "application": server.universal_registry.application_root,
        "registry": server.universal_registry.governed_work_registry_root,
        "ownership_root": server._runtime_ownership_root,
        "legacy_runtime_enabled": bool(server.legacy_runtime_enabled),
        "proof": dict(proof or {}),
        "prewarm": dict(prewarm or {}),
        "observed_at": time.time(),
    }


def _bridge_runtime_status(
    proof: dict[str, object],
    prewarm: dict[str, object],
) -> str:
    return (
        "active"
        if proof.get("ok") is True and prewarm.get("ok") is True
        else "degraded"
    )


def run_bridge(
    *,
    state_path: Path | None = None,
    descriptor_path: Path | None = None,
    status_path: Path | None = None,
    probe: bool = False,
    stop_event: threading.Event | None = None,
) -> dict[str, object]:
    resolved_state = Path(state_path or default_state_path()).expanduser().resolve()
    resolved_descriptor = Path(
        descriptor_path or default_runtime_descriptor_path()
    ).expanduser().resolve()
    resolved_status = Path(status_path or default_status_path()).expanduser().resolve()
    server = _build_server(
        state_path=resolved_state,
        descriptor_path=resolved_descriptor,
    )
    server.start()
    terminal_proof: dict[str, object] | None = None
    try:
        prewarm = _safe_prewarm(server)
        proof = _safe_proof(server, resolved_descriptor)
        payload = bridge_payload(
            server=server,
            descriptor_path=resolved_descriptor,
            state_path=resolved_state,
            status=_bridge_runtime_status(proof, prewarm),
            proof=proof,
            prewarm=prewarm,
        )
        _atomic_json(resolved_status, payload)
        if probe:
            return payload
        next_heartbeat = time.monotonic() + BRIDGE_HEARTBEAT_SECONDS
        next_proof = time.monotonic() + BRIDGE_PROOF_INTERVAL_SECONDS
        while stop_event is None or not stop_event.is_set():
            server.thread.join(timeout=1.0)
            if server.thread is None or not server.thread.is_alive():
                raise RuntimeError("authority bridge HTTP worker stopped")
            if not _machine_transport_is_serving(server):
                raise RuntimeError("authority bridge machine transport worker stopped")
            now = time.monotonic()
            if now >= next_proof:
                proof = _safe_proof(server, resolved_descriptor)
                next_proof = now + BRIDGE_PROOF_INTERVAL_SECONDS
            if now >= next_heartbeat:
                prewarm = getattr(
                    server,
                    "universal_machine_projection_prewarm_status",
                    lambda: prewarm,
                )()
                _atomic_json(
                    resolved_status,
                    bridge_payload(
                        server=server,
                        descriptor_path=resolved_descriptor,
                        state_path=resolved_state,
                        status=_bridge_runtime_status(proof, prewarm),
                        proof=proof,
                        prewarm=prewarm,
                    ),
                )
                next_heartbeat = now + BRIDGE_HEARTBEAT_SECONDS
    except Exception as exc:
        terminal_proof = _terminal_proof(exc)
        _atomic_json(
            resolved_status,
            bridge_payload(
                server=server,
                descriptor_path=resolved_descriptor,
                state_path=resolved_state,
                status="failed",
                proof=terminal_proof,
                prewarm=getattr(
                    server,
                    "universal_machine_projection_prewarm_status",
                    lambda: {},
                )(),
            ),
        )
        raise
    finally:
        server.close()
        if terminal_proof is None:
            stopped = bridge_payload(
                server=server,
                descriptor_path=resolved_descriptor,
                state_path=resolved_state,
                status="stopped",
            )
            _atomic_json(resolved_status, stopped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the headless Universal Cell authority bridge."
    )
    parser.add_argument("--state-path", default="")
    parser.add_argument("--descriptor-path", default="")
    parser.add_argument("--status-path", default="")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Start, prove machine transport, print JSON, then stop.",
    )
    parser.add_argument(
        "--standalone-owner",
        action="store_true",
        help=(
            "explicitly run this headless process as the graph's only "
            "machine-transport owner"
        ),
    )
    args = parser.parse_args(argv)

    if not args.probe and not args.standalone_owner:
        print(json.dumps({
            "schema": "archhub-authority-bridge-runtime/v1",
            "status": "blocked",
            "ok": False,
            "reason": (
                "headless authority ownership requires --standalone-owner; "
                "the normal ApplicationServer is the default owner"
            ),
        }, sort_keys=True), file=sys.stderr)
        return 2

    try:
        result = run_bridge(
            state_path=Path(args.state_path) if args.state_path else None,
            descriptor_path=(
                Path(args.descriptor_path) if args.descriptor_path else None
            ),
            status_path=Path(args.status_path) if args.status_path else None,
            probe=args.probe,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({
            "schema": "archhub-authority-bridge-runtime/v1",
            "status": "failed",
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }, sort_keys=True), file=sys.stderr)
        return 1
    if args.probe:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
