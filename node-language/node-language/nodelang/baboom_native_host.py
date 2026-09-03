"""Volatile Node Language host for BABOOM's graph-held stewardship presence.

This host is intentionally not a supervisor, task queue, model worker, or
state store. It binds one founder-approved device to the existing Universal
runtime, renews that graph-held presence, reads the bounded BABOOM context
lens, and may record one deduplicated safe stewardship observation. A desktop
or Workshop projection can render its latest in-memory snapshot but cannot
derive authority from it.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from .cell_activity import FOREGROUND_APP_LABELS
from .application_machine_transport import (
    MachineTransportError,
    validate_baboom_native_frame_payload,
)


class BaboomNativeTransport(Protocol):
    """The minimum released transport surface needed by the physical host."""

    agent_session_root: str

    def bind_agent_session(
        self,
        *,
        runtime: str,
        external_session_id: str,
        device_credential_provider: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> dict[str, object]:
        ...

    def renew_runtime_presence(self) -> dict[str, object]:
        ...

    def baboom_context(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        ...

    def baboom_native_frame(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        ...

    def resolve_baboom_command(self, *, utterance: str) -> dict[str, object]:
        ...

    def respond_baboom_command(self, *, utterance: str) -> dict[str, object]:
        ...

    def execute_baboom_command(self, *, utterance: str) -> dict[str, object]:
        ...

    def record_baboom_activity(self, *, app: str) -> dict[str, object]:
        ...

    def record_baboom_steward_signal(
        self,
        *,
        fingerprint: str,
        source: str,
        summary: str,
    ) -> dict[str, object]:
        ...


@dataclass(frozen=True, slots=True)
class BaboomNativeSnapshot:
    """Disposable display state derived from one canonical graph revision."""

    revision: int
    presence_expires_at: float
    frame_issued_at: float
    frame_expires_at: float
    context: Mapping[str, object]
    directive: Mapping[str, object]
    report: Mapping[str, object] | None
    steward_signal_root: str | None


class BaboomNativeHost:
    """Maintain BABOOM presence without acquiring a second semantic authority."""

    _SOURCE = "baboom-native-host"

    def __init__(
        self,
        transport: BaboomNativeTransport,
        *,
        external_session_id: str,
        device_credential_provider: Callable[[Mapping[str, object]], Mapping[str, object]],
        heartbeat_seconds: float = 30.0,
        emit_steward_signals: bool = True,
        activity_provider: Callable[[], str | None] | None = None,
    ) -> None:
        if (
            type(external_session_id) is not str
            or not external_session_id.strip()
            or type(heartbeat_seconds) not in (int, float)
            or not 15.0 <= float(heartbeat_seconds) <= 300.0
            or type(emit_steward_signals) is not bool
            or (activity_provider is not None and not callable(activity_provider))
        ):
            raise ValueError("BABOOM native host configuration is invalid")
        self._transport = transport
        self._external_session_id = external_session_id.strip()
        self._device_credential_provider = device_credential_provider
        self._heartbeat_seconds = float(heartbeat_seconds)
        self._emit_steward_signals = emit_steward_signals
        self._activity_provider = activity_provider
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._last_signal_fingerprint = ""
        self._last_activity_app = ""
        self._last_activity_at = 0.0
        self._latest: BaboomNativeSnapshot | None = None
        self._last_error = ""

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def latest_snapshot(self) -> BaboomNativeSnapshot | None:
        with self._lock:
            return self._latest

    @property
    def last_error(self) -> str:
        """Expose only a bounded operational state, never a transport payload."""
        with self._lock:
            return self._last_error

    def connect(self) -> BaboomNativeSnapshot:
        """Explicitly enroll/renew one approved BABOOM presence capability."""
        with self._lock:
            if not self._transport.agent_session_root:
                self._transport.bind_agent_session(
                    runtime="baboom",
                    external_session_id=self._external_session_id,
                    device_credential_provider=self._device_credential_provider,
                )
            self._connected = True
        return self.poll()

    def poll(self) -> BaboomNativeSnapshot:
        """Read and project one graph revision; no Work or provider action occurs."""
        with self._lock:
            if not self._connected or not self._transport.agent_session_root:
                raise RuntimeError("BABOOM native host is not explicitly connected")
        lease = self._transport.renew_runtime_presence()
        expires_at = lease.get("expires_at")
        if (
            lease.get("agent_session") != self._transport.agent_session_root
            or lease.get("runtime") != "baboom"
            or type(expires_at) not in (int, float)
        ):
            raise RuntimeError("BABOOM native host presence response is invalid")
        self._record_foreground_activity()
        raw_frame = self._transport.baboom_native_frame(response_timeout_seconds=5.0)
        try:
            frame = validate_baboom_native_frame_payload(raw_frame)
        except MachineTransportError as exc:
            raise RuntimeError("BABOOM native frame response is invalid") from exc
        context = frame["context"]
        directive = frame["directive"]
        report = frame["report"]
        revision = frame["revision"]
        if (
            not isinstance(context, Mapping)
            or not isinstance(directive, Mapping)
            or (report is not None and not isinstance(report, Mapping))
            or type(directive.get("motion")) is not str
            or type(directive.get("message")) is not str
            or type(directive.get("compact_message")) is not str
        ):
            raise RuntimeError("BABOOM native frame response is invalid")
        signal_root = self._record_actionable_signal(context)
        snapshot = BaboomNativeSnapshot(
            revision=revision,
            presence_expires_at=float(expires_at),
            frame_issued_at=float(frame["issued_at"]),
            frame_expires_at=float(frame["expires_at"]),
            context=MappingProxyType(dict(context)),
            directive=MappingProxyType(dict(directive)),
            report=(
                MappingProxyType(dict(report)) if report is not None else None
            ),
            steward_signal_root=signal_root,
        )
        with self._lock:
            self._latest = snapshot
            self._last_error = ""
        return snapshot

    def _record_foreground_activity(self) -> None:
        """Renew only an allowlisted, coarse activity lease from this device."""
        if self._activity_provider is None:
            return
        app = self._activity_provider()
        if app is None:
            return
        if type(app) is not str or app not in FOREGROUND_APP_LABELS:
            raise RuntimeError("BABOOM activity provider returned an unreleased app")
        now = time.monotonic()
        if app == self._last_activity_app and now - self._last_activity_at < 30.0:
            return
        result = self._transport.record_baboom_activity(app=app)
        expires_at = result.get("expires_at")
        if (
            result.get("app") != app
            or result.get("agent_session") != self._transport.agent_session_root
            or type(result.get("activity")) is not str
            or type(expires_at) not in (int, float)
            or type(result.get("revision")) is not int
        ):
            raise RuntimeError("BABOOM foreground activity response is invalid")
        self._last_activity_app = app
        self._last_activity_at = now

    def start(self) -> None:
        """Run the volatile heartbeat only after explicit connection succeeds."""
        with self._lock:
            if not self._connected:
                raise RuntimeError("BABOOM native host requires explicit connection")
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="baboom-native-host", daemon=True
            )
            self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        """Stop only this host thread; graph presence expires naturally."""
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise ValueError("BABOOM native host stop timeout is invalid")
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread is not None:
            thread.join(float(timeout_seconds))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def resolve_input(self, utterance: str) -> Mapping[str, object]:
        """Resolve typed input through the graph-held command catalog only.

        This is intentionally not command execution. The caller receives the
        graph-declared proposed intent and must use the separate approval and
        receipt path for any consequential action.
        """
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("BABOOM native input is invalid")
        with self._lock:
            if not self._connected:
                raise RuntimeError("BABOOM native host is not explicitly connected")
        result = self._transport.resolve_baboom_command(utterance=utterance)
        if (
            type(result.get("catalog")) is not str
            or result.get("catalog") != "app:baboom-command-catalog:v1"
            or type(result.get("intent")) is not str
            or type(result.get("payload")) is not str
            or type(result.get("revision")) is not int
        ):
            raise RuntimeError("BABOOM native input resolution is invalid")
        return MappingProxyType(dict(result))

    def respond_input(self, utterance: str) -> Mapping[str, object]:
        """Read the bounded graph-backed detail for one founder request."""
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("BABOOM native input is invalid")
        with self._lock:
            if not self._connected:
                raise RuntimeError("BABOOM native host is not explicitly connected")
        result = self._transport.respond_baboom_command(utterance=utterance)
        command = result.get("command")
        response = result.get("response")
        if (
            not isinstance(command, Mapping)
            or not isinstance(response, Mapping)
            or type(command.get("intent")) is not str
            or type(response.get("kind")) is not str
            or type(response.get("summary")) is not str
            or not isinstance(response.get("data"), Mapping)
        ):
            raise RuntimeError("BABOOM native input response is invalid")
        return MappingProxyType(dict(result))

    def execute_input(self, utterance: str) -> Mapping[str, object]:
        """Create only the exact founder task confirmed by the native surface.

        The transport route accepts only the graph-held ``assign-task`` command.
        It creates idempotent, open Work and cannot claim Work, invoke a model,
        operate a connector, or control the desktop.
        """
        if type(utterance) is not str or not utterance.strip() or len(utterance) > 4_000:
            raise ValueError("BABOOM native input is invalid")
        with self._lock:
            if not self._connected:
                raise RuntimeError("BABOOM native host is not explicitly connected")
        result = self._transport.execute_baboom_command(utterance=utterance)
        if (
            result.get("catalog") != "app:baboom-command-catalog:v1"
            or result.get("intent") != "assign-task"
            or type(result.get("work")) is not str
            or type(result.get("external_key")) is not str
            or type(result.get("created")) is not bool
            or result.get("state") != "open"
            or type(result.get("revision")) is not int
        ):
            raise RuntimeError("BABOOM native task execution is invalid")
        return MappingProxyType(dict(result))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception as exc:
                # The host has no retry ledger or replacement session. It keeps
                # the failure local and awaits the next bounded heartbeat.
                with self._lock:
                    self._last_error = type(exc).__name__
            self._stop.wait(self._heartbeat_seconds)

    def _record_actionable_signal(self, context: Mapping[str, object]) -> str | None:
        if not self._emit_steward_signals:
            return None
        work = context["work"]
        attention = context["attention"]
        if work["blocked"]:
            summary = "Blocked governed work requires founder review."
        elif work["review"]:
            summary = "Governed work is awaiting founder review."
        elif attention["blocked_obligations"]:
            summary = "Blocked obligations require founder review."
        else:
            return None
        state = {
            "work": dict(work),
            "attention": dict(attention),
            "workshop_entry_count": context["workshop"]["entry_count"],
            "meeting_sessions": context["meeting_notes"]["active_sessions"],
        }
        fingerprint = hashlib.sha256(json.dumps(
            state, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")).hexdigest()
        with self._lock:
            if fingerprint == self._last_signal_fingerprint:
                return None
        result = self._transport.record_baboom_steward_signal(
            fingerprint=fingerprint,
            source=self._SOURCE,
            summary=summary,
        )
        signal_root = result.get("signal")
        if type(signal_root) is not str or not signal_root:
            raise RuntimeError("BABOOM native host signal response is invalid")
        with self._lock:
            self._last_signal_fingerprint = fingerprint
        return signal_root


__all__ = [
    "BaboomNativeHost", "BaboomNativeSnapshot", "BaboomNativeTransport",
]
