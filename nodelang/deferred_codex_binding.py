"""Defer Codex identity to the first tools/call, taken from transport request _meta.

Codex Desktop starts one MCP server for an app and multiplexes every conversation
("thread") over it, tagging each tools/call request _meta with its own threadId
(codex-rs core/src/mcp_tool_call.rs: MCP_TOOL_THREAD_ID_META_KEY = "threadId",
with_mcp_tool_call_ids_meta(request_meta, &sess.thread_id.to_string(), ...)). It
passes no CODEX_THREAD_ID environment variable, so env-only identity resolution
raises at startup before any request arrives.

This module serves the Codex coordination server UNBOUND and binds one native
session per threadId on that thread's first call, keyed in a per-threadId map, so
one server owns distinct sessions for distinct threads. The threadId is read ONLY
from the active request's _meta (never from tool arguments, never a process-global
"current agent", never the per-call itemId or a shared sessionId).

A binding is RETAINED in the map before its first effect (the connect), so a
partial or uncertain build is never discarded and never rebuilt: its owner is kept
and the binding is latched with the stage that failed. While latched, no governed
call is served for that thread; only reconciliation reaches the retained owner. A
binding leaves the map only on a confirmed release with a clean Stop observer.
"""
from __future__ import annotations

import json
import os
import threading

from .application_machine_transport import MachineTransportError
from .installed_workshop_coordination import InstalledWorkshopCoordinationClient
from .native_agent_session import NativeAgentSession


# codex-rs attaches the stable thread id under this request _meta key
# (core/src/mcp_tool_call.rs: MCP_TOOL_THREAD_ID_META_KEY = "threadId"). The
# installed codex is 0.159.2 (codex.exe --version), whose per-call _meta also
# carries sessionId; earlier builds (0.153.x) carried itemId instead. A sessionId
# may be shared by child tasks and an itemId is per originating item, so neither is
# identity. Only threadId is, and it is present in every version.
CODEX_THREAD_META_KEY = "threadId"


# Optional, default-OFF capture of the raw request _meta each tools/call carries,
# so a genuine frame from the real Codex client can be recorded without any code
# change: set ARCHHUB_CODEX_META_LOG to a writable scratch path (e.g. via setx,
# never by editing ~/.codex) and the first frames are appended there as JSON lines.
# Unset (production default) it does nothing, changes no behaviour, and never fails
# a request. Diagnostic only; it records transport metadata, not tool arguments.
_CAPTURE_LOCK = threading.Lock()
_CAPTURE_STATE = {"count": 0}
_CAPTURE_LIMIT = 50


def _maybe_capture(extra):
    path = os.environ.get("ARCHHUB_CODEX_META_LOG")
    if not path or extra is None:
        return
    try:
        with _CAPTURE_LOCK:
            if _CAPTURE_STATE["count"] >= _CAPTURE_LIMIT:
                return
            _CAPTURE_STATE["count"] += 1
            seq = _CAPTURE_STATE["count"]
        line = json.dumps({"seq": seq, "request_meta": extra}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except Exception:
        pass  # capture is diagnostic; it must never affect the request


def _request_meta_extra():
    """The active MCP request's _meta extra fields, or None outside a request.

    Read from the low-level server's request contextvar, which the server sets to
    the live RequestContext for the duration of each request (its `.meta` is the
    request params `_meta`, a pydantic model that preserves unknown keys under
    model_extra because RequestParams.Meta is declared with extra="allow").
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
    except Exception as exc:  # pragma: no cover - mcp import guard
        raise MachineTransportError("MCP request context is unavailable") from exc
    try:
        context = request_ctx.get()
    except LookupError:
        return None
    meta = getattr(context, "meta", None)
    if meta is None:
        result = {}
    else:
        extra = getattr(meta, "model_extra", None)
        if extra is None:
            extra = meta if isinstance(meta, dict) else {}
        result = dict(extra)
    _maybe_capture(result)
    return result


def current_codex_thread_id():
    """The threadId of the active Codex request, taken only from transport _meta.

    Refuses when there is no active request, when _meta carries no threadId, or
    when the value is malformed. Tool arguments are never consulted, so a model
    cannot supply or spoof an identity through a tool's parameters.
    """
    extra = _request_meta_extra()
    if extra is None:
        raise MachineTransportError(
            "Codex coordination requires an active request; no identity outside a tools/call")
    value = extra.get(CODEX_THREAD_META_KEY)
    if type(value) is not str or not value.strip():
        raise MachineTransportError(
            "Codex coordination requires a threadId in the request _meta")
    thread_id = value.strip()
    if "\x00" in thread_id or len(thread_id.encode("utf-8")) > 200:
        raise MachineTransportError("Codex request threadId is malformed")
    return thread_id


def is_deferred_codex_environment(environment=None):
    """A Codex MCP launch with no pre-resolved session: identity must defer to _meta."""
    env = os.environ if environment is None else environment
    vendor = str(env.get("ARCHHUB_COORDINATION_VENDOR", "")).strip().lower()
    thread = str(env.get("CODEX_THREAD_ID", "")).strip()
    explicit = str(env.get("ARCHHUB_EXTERNAL_SESSION_ID", "")).strip()
    explicit_runtime = str(env.get("ARCHHUB_AGENT_RUNTIME", "")).strip()
    return vendor == "codex" and not thread and not explicit and not explicit_runtime


class _Binding:
    """One thread's binding, retained from creation and latched on any build failure."""

    __slots__ = ("owner", "control", "supervisor", "state", "failure")

    def __init__(self, owner):
        self.owner = owner
        self.control = None
        self.supervisor = None
        self.state = "building"  # building -> bound | failed | released-observer-unclean
        self.failure = None      # {"stage": connect|control|keeper, "detail": ...}


class DeferredCodexRuntime:
    """One native session per Codex threadId, each bound on that thread's first call.

    The owner/control/supervisor factories are injectable so routing, refusal and
    recovery are exercised without an installed descriptor, DPAPI custody or a real
    Stop host.
    """

    def __init__(self, environment=None, *, session_factory=None, control_factory=None,
                 supervisor_factory=None):
        base = dict(os.environ if environment is None else environment)
        # Deferred mode is chosen only when these are absent; keep them out so a
        # per-thread session resolves to exactly (codex, threadId) and nothing else.
        for name in ("CODEX_THREAD_ID", "ARCHHUB_EXTERNAL_SESSION_ID", "ARCHHUB_AGENT_RUNTIME"):
            base.pop(name, None)
        self._base = base
        self._session_factory = session_factory or (
            lambda environment: NativeAgentSession(environment=environment))
        if control_factory is None:
            from .native_agent_mcp import _OwnedWorkshopClient
            control_factory = _OwnedWorkshopClient
        self._control_factory = control_factory
        # Injectable so courts drive the per-binding Stop observer without a real
        # host; default builds the real StopHostSupervisor for each thread's binding.
        self._supervisor_factory = supervisor_factory
        self._lock = threading.RLock()
        self._bundles = {}  # thread_id -> _Binding

    def _start_supervisor(self, owner):
        """Start this binding's own Stop observer. Optional: a failure never fails
        the binding (matches the eager serve() behaviour), it just leaves no host."""
        factory = self._supervisor_factory
        if factory is None:
            def factory(owner):
                from .native_stop_hook import StopHostSupervisor
                supervisor = StopHostSupervisor(owner)
                try:
                    owner._stop_supervisor = supervisor  # read by native.owner_status
                except Exception:
                    pass
                return supervisor.start()
        try:
            return factory(owner)
        except Exception:
            return None

    def _build(self, thread_id):
        """Build under the lock. The binding is retained BEFORE the first effect, so
        a failure at any stage latches it in place; the owner is never discarded,
        auto-closed or rebuilt, and an uncertain connect is never retried."""
        env = dict(self._base)
        env["ARCHHUB_COORDINATION_VENDOR"] = "codex"
        env["ARCHHUB_AGENT_RUNTIME"] = "codex"
        env["ARCHHUB_EXTERNAL_SESSION_ID"] = thread_id
        owner = self._session_factory(environment=env)
        identity = getattr(owner, "_identity", None)
        if (identity is None or getattr(identity, "runtime", None) != "codex"
                or getattr(identity, "external_session_id", None) != thread_id):
            # Pre-effect configuration error (no connect yet): nothing to retain.
            raise MachineTransportError("Codex deferred identity did not resolve to this thread")
        binding = _Binding(owner)
        self._bundles[thread_id] = binding  # retained before the first effect (connect)
        try:
            client = owner.connect()
        except Exception as exc:
            # Unknown enrollment outcome: keep the owner, latch, never retry/close.
            binding.state = "failed"
            binding.failure = {"stage": "connect", "detail": str(exc)[:160]}
            raise
        try:
            binding.control = self._control_factory(owner, client)
        except Exception as exc:
            # The owner holds a live or uncertain capability: retain and latch; do
            # NOT auto-close (a retained/uncertain release would leave it uncached).
            binding.state = "failed"
            binding.failure = {"stage": "control", "detail": str(exc)[:160]}
            raise
        binding.supervisor = self._start_supervisor(owner)
        keeper = getattr(owner, "start_lease_keeper", None)
        if callable(keeper):
            try:
                keeper()
            except Exception as exc:
                binding.state = "failed"
                binding.failure = {"stage": "keeper", "detail": str(exc)[:160]}
                raise  # retained + latched; the Stop observer stays for reconciliation
        binding.state = "bound"
        return binding

    def bundle_for(self, thread_id, *, recovery=False):
        if type(thread_id) is not str or not thread_id:
            raise MachineTransportError("a Codex threadId is required")
        with self._lock:
            binding = self._bundles.get(thread_id)
            if binding is not None:
                if binding.state == "failed" and not recovery:
                    raise MachineTransportError(
                        "Codex thread is latched after a failed %s stage; no governed call is "
                        "served until it is reconciled" % (binding.failure or {}).get("stage"))
                return binding
            return self._build(thread_id)

    def current(self):
        """Governed resolution: refuses a latched thread (no rebuild, no retry)."""
        return self.bundle_for(current_codex_thread_id(), recovery=False)

    def recovery_binding(self, thread_id):
        """Reconciliation resolution: reaches the retained owner even when latched."""
        return self.bundle_for(thread_id, recovery=True)

    def bound_thread_ids(self):
        with self._lock:
            return tuple(self._bundles)

    def latched_threads(self):
        with self._lock:
            return tuple(t for t, b in self._bundles.items() if b.state == "failed")

    @staticmethod
    def _owner_is_validated_bound(owner):
        """The owner reports a live, same-owner bound state (not uncertain/needs-recovery)."""
        try:
            status = owner.owner_status()
        except Exception:
            return False
        return (isinstance(status, dict) and status.get("state") == "bound"
                and not status.get("recovery_required"))

    def resume(self, thread_id):
        """Stage-aware completion of a latched binding after reconciliation.

        Only runs when the retained owner is a VALIDATED same-owner bound session
        (its own recover_* has already settled it). It completes the remaining stages
        -- control, then Stop observer, then lease keeper -- WITHOUT replaying connect
        and WITHOUT minting a new owner or re-enrolling, and clears the latch only on
        full success. If completion fails, the ORIGINAL stage and outcome are kept.
        """
        with self._lock:
            binding = self._bundles.get(thread_id)
            if binding is None:
                raise MachineTransportError("no Codex binding to resume for this thread")
            if binding.state != "failed":
                return {"state": binding.state, "resumed": False}
            original = dict(binding.failure or {})
            owner = binding.owner
            if not self._owner_is_validated_bound(owner):
                # Not reconciled yet: keep the latch untouched, do nothing.
                return {"state": "failed", "stage": original.get("stage"), "resumed": False,
                        "reason": "owner is not a validated bound same-owner; reconcile first"}
            try:
                client = owner.require_client()  # the already-bound client; never connect()
                if binding.control is None:
                    binding.control = self._control_factory(owner, client)
                if binding.supervisor is None:
                    binding.supervisor = self._start_supervisor(owner)
                keeper = getattr(owner, "start_lease_keeper", None)
                if callable(keeper):
                    keeper()
            except Exception as exc:
                # Keep the original stage and outcome; the latch is not cleared.
                return {"state": "failed", "stage": original.get("stage"), "resumed": False,
                        "detail": str(exc)[:160]}
            binding.state = "bound"
            binding.failure = None
            return {"state": "bound", "resumed": True}

    def close(self):
        """Release every per-thread binding and report each outcome accurately.

        A binding leaves the map ONLY on a CONFIRMED release (owner.close returned
        released=True) AND a clean Stop observer. A released owner whose observer
        did not stop cleanly is KEPT as a residual cleanup obligation. An uncertain
        or raising release is kept with its outcome and never replayed. Held under
        the lock so a concurrent bind cannot be lost.
        """
        with self._lock:
            items = list(self._bundles.items())
            outcomes = {}
            keep = {}
            for thread_id, binding in items:
                observer_clean = True
                if binding.supervisor is not None:
                    try:
                        observer_clean = binding.supervisor.close() is True
                    except Exception:
                        observer_clean = False
                closer = getattr(binding.owner, "close", None)
                if not callable(closer):
                    released, result = True, None
                else:
                    try:
                        result = closer()
                    except Exception as exc:
                        outcomes[thread_id] = {"state": "error", "detail": str(exc)[:160],
                                               "observer_clean": observer_clean}
                        keep[thread_id] = binding  # unresolved release: keep, no replay
                        continue
                    released = isinstance(result, dict) and result.get("released") is True
                if released and observer_clean:
                    outcomes[thread_id] = {"state": "released", "observer_clean": True}
                elif released:
                    binding.state = "released-observer-unclean"
                    outcomes[thread_id] = {"state": "released_observer_unclean", "observer_clean": False}
                    keep[thread_id] = binding  # keep the observer cleanup obligation
                else:
                    outcomes[thread_id] = {"state": "retained", "result": result,
                                           "observer_clean": observer_clean}
                    keep[thread_id] = binding
            self._bundles = keep
        released = sum(1 for outcome in outcomes.values() if outcome["state"] == "released")
        return {"threads": len(items), "released": released,
                "retained": sorted(keep), "outcomes": outcomes}


class RoutingCodexControl(InstalledWorkshopCoordinationClient):
    """Coordination client that resolves to the active thread's bound control.

    It IS an InstalledWorkshopCoordinationClient (so build_coordination_server
    exposes the installed Workshop tools), but it builds no client of its own: the
    base __init__ is bypassed and every GOVERNED operation routes to the per-thread
    control, which refuses a latched thread.
    """

    def __init__(self, runtime):
        self._runtime = runtime

    def _control(self):
        return self._runtime.current().control

    def call(self, method, parameters=None, **kwargs):
        return self._control().call(method, parameters, **kwargs)

    def bound_client(self):
        return self._control().bound_client()

    def __getattr__(self, name):
        if name == "_runtime":
            raise AttributeError(name)
        return getattr(self._runtime.current().control, name)


class RoutingCodexOwner:
    """Owner facade that resolves to the active thread's bound native session.

    Carries the deferred marker so the MCP builder skips the eager startup connect
    and binds per thread instead. Holds no session itself. Governed owner methods
    refuse a latched thread; reconciliation methods reach its retained owner.
    """

    is_deferred_router = True
    _RECOVERY_ATTRS = frozenset({
        "rebind_owner", "recover_rebind_owner", "recover_connection",
        "inspect_enrollment", "settle_effect",
    })

    def __init__(self, runtime):
        self._runtime = runtime
        self._routing_control = RoutingCodexControl(runtime)

    def control(self):
        return self._routing_control

    def connect(self):
        # The builder must not connect a deferred owner at startup; expose the
        # routing control so any direct caller still routes per thread.
        return self._routing_control

    def close(self):
        """Shutdown: release every per-thread binding this router created."""
        return self._runtime.close()

    def owner_status(self):
        # Outside a request (startup probe) there is no thread to read; report
        # deferred rather than raising. Within a request, status reaches the owner
        # even when latched, so a failed binding stays inspectable for recovery.
        try:
            thread_id = current_codex_thread_id()
        except MachineTransportError:
            return {"state": "deferred", "generation": 0, "agent_session": None,
                    "deferred_runtime": "codex",
                    "bound_threads": list(self._runtime.bound_thread_ids()),
                    "latched_threads": list(self._runtime.latched_threads())}
        return self._runtime.recovery_binding(thread_id).owner.owner_status()

    def resume(self):
        """Complete a latched binding after a validated same-owner reconciliation."""
        return self._runtime.resume(current_codex_thread_id())

    def __getattr__(self, name):
        if name in ("_runtime", "_routing_control"):
            raise AttributeError(name)
        if name == "_stop_supervisor":
            # The real native_agent_mcp._with_stop_host reads this via getattr(owner,
            # "_stop_supervisor", None) on the owner_status tool path, which must work
            # for a latched thread so its status stays inspectable for reconciliation.
            # Resolve recovery-safe; absent (e.g. connect-latched) -> AttributeError -> None.
            try:
                thread_id = current_codex_thread_id()
            except MachineTransportError:
                raise AttributeError(name)
            return getattr(self._runtime.recovery_binding(thread_id).owner, name)
        recovery = name in RoutingCodexOwner._RECOVERY_ATTRS
        binding = self._runtime.bundle_for(current_codex_thread_id(), recovery=recovery)
        return getattr(binding.owner, name)


def owner_for_environment(environment=None, *, session_factory=None, control_factory=None,
                         supervisor_factory=None):
    """Pick the native owner for a launch: a deferred Codex router, else a session."""
    if is_deferred_codex_environment(environment):
        return RoutingCodexOwner(DeferredCodexRuntime(
            environment, session_factory=session_factory, control_factory=control_factory,
            supervisor_factory=supervisor_factory))
    if session_factory is not None:
        return session_factory(environment=environment)
    return NativeAgentSession(environment=environment)


__all__ = [
    "CODEX_THREAD_META_KEY", "DeferredCodexRuntime", "RoutingCodexControl",
    "RoutingCodexOwner", "current_codex_thread_id", "is_deferred_codex_environment",
    "owner_for_environment",
]
