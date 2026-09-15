"""One process-local harness attachment shared by Work and Workshop adapters.

This module starts no service and stores no credentials or attachment records.
The server's existing identity guard handles competing processes. A failed
attempt is retained here, but this process-local state cannot guard a restart.
"""
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import re
import threading
import time

from .application_machine_transport import (
    MachineTransportError, UniversalRuntimeClient, _read_descriptor,
)
from .cell_secret_keys import WindowsDpapiSigningKeyProvider


# These are the distinct machine-transport harness bodies in the application
# catalogue. Device-proof BABOOM and unsupported runtimes are not fallbacks.
_NATIVE_IDS = {
    "codex": ("CODEX_THREAD_ID",),
    "claude": ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"),
    "gemini": ("GEMINI_SESSION_ID",),
    "opencode": ("OPENCODE_SESSION_ID",),
}
_RUNTIME_NAMES = {name + suffix: name for name in _NATIVE_IDS
                  for suffix in ("", ".exe", ".cmd")}
_RUNTIME_NAMES.update({"claude-code" + suffix: "claude"
                       for suffix in ("", ".exe", ".cmd")})
_SESSION_ROOT = re.compile(r"app:agent-session:runtime:[0-9a-f]{32}\Z")


@dataclass(frozen=True)
class NativeAgentIdentity:
    runtime: str
    external_session_id: str


def _environment_text(environment, name):
    value = environment.get(name)
    if value is None:
        return None
    if type(value) is not str or "\x00" in value or len(value.encode("utf-8")) > 4096:
        raise ValueError("native agent identity field is invalid")
    return value.strip()


def _runtime(value):
    name = ntpath.basename(value).casefold()
    if not name or name not in _RUNTIME_NAMES:
        raise ValueError("native agent runtime is unsupported")
    return _RUNTIME_NAMES[name]


def resolve_native_agent_identity(environment=None) -> NativeAgentIdentity:
    env = os.environ if environment is None else environment
    if not isinstance(env, Mapping):
        raise TypeError("native agent environment must be a mapping")
    explicit_runtime = _environment_text(env, "ARCHHUB_AGENT_RUNTIME")
    explicit_id = _environment_text(env, "ARCHHUB_EXTERNAL_SESSION_ID")
    if (explicit_runtime is None) != (explicit_id is None) or (
            explicit_runtime is not None and (not explicit_runtime or not explicit_id)):
        raise ValueError("both explicit native agent identity fields are required")
    vendor = _environment_text(env, "ARCHHUB_COORDINATION_VENDOR")
    if vendor is not None and not vendor:
        raise ValueError("native agent vendor is empty")
    selected_runtime = _runtime(explicit_runtime) if explicit_runtime else (_runtime(vendor) if vendor else None)
    if vendor and selected_runtime != _runtime(vendor):
        raise ValueError("native agent runtime identities conflict")
    candidates = []
    for runtime, fields in _NATIVE_IDS.items():
        # A child harness may inherit its parent's native environment. Only a
        # configured selector permits ignoring those unrelated runtime fields.
        if selected_runtime is not None and runtime != selected_runtime:
            continue
        values = {_environment_text(env, name) for name in fields} - {None, ""}
        if len(values) > 1:
            raise ValueError("native agent session identities conflict")
        if values:
            candidates.append(NativeAgentIdentity(runtime, next(iter(values))))
    if selected_runtime == "opencode" or any(candidate.runtime == "opencode" for candidate in candidates):
        native_id = _environment_text(env, "OPENCODE_SESSION_ID")
        if not native_id or re.fullmatch(r"ses_[A-Za-z0-9]+", native_id) is None:
            raise ValueError("actual OpenCode hook session identity is required")
    if explicit_runtime:
        selected = NativeAgentIdentity(selected_runtime, explicit_id)
        if any(candidate != selected for candidate in candidates):
            raise ValueError("explicit and native agent identities conflict")
        return selected
    if len(candidates) != 1 or selected_runtime is not None and candidates[0].runtime != selected_runtime:
        raise ValueError("one unambiguous native agent session identity is required")
    return candidates[0]


class NativeAgentSession:
    """Own one client; an uncertain enrollment is never repeated by this object.

    Explicit constructor dependencies support isolated signed-descriptor tests.
    Production defaults require existing installed descriptor and DPAPI custody.
    bind_agent_session retains the transport's finite response wait (currently
    240 seconds); AF_PIPE connection setup has no strict wall-clock deadline.
    """

    def __init__(self, *, environment=None, descriptor_path=None, key_provider=None,
                 client_factory=UniversalRuntimeClient, expected_agent_session=None):
        if expected_agent_session is not None and (
                type(expected_agent_session) is not str or not _SESSION_ROOT.fullmatch(expected_agent_session)):
            raise ValueError("Conditional native continuation requires an exact existing actor")
        self._expected_agent_session = expected_agent_session
        self._environment = os.environ if environment is None else environment
        self._identity = resolve_native_agent_identity(self._environment)
        self._opencode_custody = None
        if self._identity.runtime == "opencode":
            from .opencode_native_custody import OpenCodeProcessCustody
            self._opencode_custody = OpenCodeProcessCustody(
                self._identity.external_session_id, environment=self._environment)
        local = _environment_text(self._environment, "LOCALAPPDATA")
        if descriptor_path is None:
            if not local:
                raise ValueError("existing installed runtime location is unavailable")
            descriptor_path = Path(local) / "ArchHub" / "active-universal-runtime.json"
        self._descriptor_path = Path(descriptor_path).expanduser().resolve()
        self._key_provider = key_provider
        self._key_path = None if key_provider is not None else (
            Path(local) / "ArchHub" / "keys" / "authority-signing-v1.dpapi.json" if local else None)
        if key_provider is None and self._key_path is None:
            raise ValueError("existing installed signing custody is unavailable")
        self._factory = client_factory
        self._lock = threading.RLock()
        self._state = "unbound"
        self._client = None
        self._descriptor = None
        self._session_root = None
        self._generation = 0
        self._active_calls = 0
        self._continued = False
        self._rebind_candidate = None
        self._hook_rebind_guard = None
        self._retired_release = None

    def register_hook_rebind_guard(self, guard):
        """Private composition registers retained OS custody, never an MCP argument."""
        with self._lock:
            if (self._environment.get("ARCHHUB_NATIVE_WORKSHOP_OWNER") != "claude-stdio-v1"
                    or self._identity.runtime != "claude" or not callable(guard)
                    or self._hook_rebind_guard is not None):
                raise MachineTransportError("Native hook recovery registration is invalid")
            self._require_bound()
            guard()
            self._hook_rebind_guard = guard

    @property
    def generation(self):
        with self._lock:
            return self._generation

    @staticmethod
    def _owner_fingerprint(descriptor):
        return hashlib.sha256(json.dumps(descriptor.document(), sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

    @staticmethod
    def _instance_identity(descriptor):
        return (descriptor.application_root, descriptor.agent_session_root,
            descriptor.workshop_root, descriptor.work_registry_root,
            os.path.normcase(str(Path(descriptor.database).resolve())))

    def owner_status(self):
        """Read nonsecret owner identities even when ordinary tools are stale."""
        with self._lock:
            self._check_identity()
            def project(descriptor):
                if descriptor is None:
                    return None
                instance = hashlib.sha256(json.dumps(self._instance_identity(descriptor),
                    separators=(",", ":")).encode()).hexdigest()
                return {"fingerprint": self._owner_fingerprint(descriptor),
                    "runtime_id": descriptor.runtime_id, "application": descriptor.application_root,
                    "instance_digest": instance}
            try:
                current = self._read_owner()
                current_error = None
            except (OSError, ValueError, MachineTransportError):
                current, current_error = None, "verified_active_owner_unavailable"
            expired = self._lease_expired()
            return {"state": self._state, "generation": self._generation,
                "agent_session": self._session_root, "pinned": project(self._descriptor),
                "current": project(current), "current_error": current_error,
                "rebind_pending": self._rebind_candidate is not None,
                "retired_release": None if self._retired_release is None else {
                    "release_id": self._retired_release["release_id"],
                    "owner_fingerprint": self._owner_fingerprint(self._retired_release["descriptor"]),
                    "historical_attempt_outcome": "unknown"},
                "lease_expired": expired,
                "recovery_required": bool(self._session_root and (
                    self._state != "bound" or current != self._descriptor
                    or current_error is not None or expired is not False))}

    def _lease_expired(self):
        """Local lease deadline only; unknown remote custody is not expiry proof."""
        expires = getattr(self._client, "_agent_session_expires_at", None)
        if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= 0:
            return None
        return time.time() >= expires

    def rebind_owner(self, *, expected_old_owner, expected_new_owner):
        """Explicit same-instance enrollment once; never retry the failed action."""
        with self._lock:
            self._check_identity()
            if self._environment.get("ARCHHUB_NATIVE_WORKSHOP_OWNER"):
                if self._hook_rebind_guard is None:
                    raise MachineTransportError("Private hook composition requires its separately admitted rebind")
                self._hook_rebind_guard()
            if self._state != "bound" or self._rebind_candidate is not None:
                raise MachineTransportError("Native rebind is unavailable or uncertain; no enrollment retry")
            if self._active_calls:
                raise MachineTransportError("Native rebind cannot run inside an active tool call")
            if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                   for value in (expected_old_owner, expected_new_owner)):
                raise ValueError("Both exact owner fingerprints are required")
            old, current = self._descriptor, self._read_owner()
            if (old is None or self._owner_fingerprint(old) != expected_old_owner
                    or self._owner_fingerprint(current) != expected_new_owner):
                raise MachineTransportError("Native owner selection changed; inspect owners again")
            if current.runtime_id == old.runtime_id:
                if current != old:
                    raise MachineTransportError("Native owner descriptor changed without a new identity")
                if self._lease_expired() is not True:
                    raise MachineTransportError("Native rebind requires a different owner or an expired lease")
            if self._instance_identity(current) != self._instance_identity(old):
                raise MachineTransportError("Native rebind cannot change application or database identity")
            # Validate the retained client itself without pretending the old
            # descriptor is still current. Never repair caller-tampered state.
            retained = self._client
            if (retained is None or retained.agent_session_root != self._session_root
                    or retained._pinned_runtime_descriptor != old or retained.agent_session_access != "full"
                    or retained.key_provider is not self._key_provider
                    or Path(retained.descriptor_path).resolve() != self._descriptor_path):
                raise MachineTransportError("Retained native binding changed")
            candidate = NativeAgentSession(environment=self._environment,
                descriptor_path=self._descriptor_path, key_provider=self._key_provider,
                client_factory=self._factory, expected_agent_session=self._session_root)
            self._rebind_candidate = candidate
            self._state = "rebinding"
            try:
                client = candidate.connect(expected_owner=expected_new_owner)
                if (candidate._descriptor != current or candidate._session_root != self._session_root
                        or candidate._continued is not True or self._read_owner() != current):
                    raise MachineTransportError("Native rebind did not continue the exact graph session")
                candidate.require_client()
                self._check_identity()
                if self._hook_rebind_guard is not None:
                    self._hook_rebind_guard()
                self._client, self._descriptor = client, current
                self._generation += 1
                self._state = "bound"
                self._rebind_candidate = None
                return self.owner_status()
            except BaseException:
                self._state = "uncertain"
                # Retain both the old binding and attempted enrollment. A lost
                # reply is not permission to enroll again or replay a tool.
                raise

    @staticmethod
    def _require_retired_owner_process(descriptor):
        """Conservative absence proof: inaccessible or reused PIDs remain refused."""
        import psutil

        try:
            process = psutil.Process(descriptor.process_id)
            if process.is_running():
                raise MachineTransportError("Previous native owner process is still present")
        except psutil.NoSuchProcess:
            return
        except psutil.Error as exc:
            raise MachineTransportError("Previous native owner retirement is unverified") from exc

    def continue_retired_release(self, *, expected_old_owner, expected_new_owner):
        """Continue the same actor after owner death; old release stays unknown."""
        with self._lock:
            self._check_identity()
            if (self._state != "release-uncertain" or self._active_calls
                    or self._rebind_candidate is not None or self._retired_release is not None):
                raise MachineTransportError("Retired release continuation is unavailable or already attempted")
            if self._environment.get("ARCHHUB_NATIVE_WORKSHOP_OWNER"):
                if self._hook_rebind_guard is None:
                    raise MachineTransportError("Private hooks require admitted continuation custody")
                self._hook_rebind_guard()
            if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                   for value in (expected_old_owner, expected_new_owner)):
                raise ValueError("Both exact owner fingerprints are required")
            old, current, retained = self._descriptor, self._read_owner(), self._client
            release_id = getattr(self, "_release_id", None)
            if (old is None or current.runtime_id == old.runtime_id
                    or self._owner_fingerprint(old) != expected_old_owner
                    or self._owner_fingerprint(current) != expected_new_owner
                    or self._instance_identity(old) != self._instance_identity(current)
                    or type(release_id) is not str or re.fullmatch(r"[0-9a-f]{32}", release_id) is None
                    or retained is None or retained.agent_session_root != self._session_root
                    or retained._pinned_runtime_descriptor != old
                    or retained.key_provider is not self._key_provider
                    or Path(retained.descriptor_path).resolve() != self._descriptor_path):
                raise MachineTransportError("Retired release identity or instance changed")
            self._require_retired_owner_process(old)
            inspection = self.inspect_enrollment(expected_owner=expected_new_owner)
            if (inspection.get("agent_session") != self._session_root
                    or inspection.get("binding_status") != "absent"
                    or type(inspection.get("active_operations")) is not int
                    or inspection["active_operations"] != 0
                    or inspection.get("historical_attempt_outcome") != "unknown"
                    or inspection.get("continuation_authorized") is not False):
                raise MachineTransportError("Current native custody does not admit retired release continuation")
            self._require_retired_owner_process(old)
            if self._read_owner() != current:
                raise MachineTransportError("Current owner changed after custody inspection")
            candidate = NativeAgentSession(environment=self._environment, descriptor_path=self._descriptor_path,
                key_provider=self._key_provider, client_factory=self._factory, expected_agent_session=self._session_root)
            self._retired_release = {"client": retained, "descriptor": old, "release_id": release_id}
            self._rebind_candidate, self._state = candidate, "rebinding"
            try:
                client = candidate.connect(expected_owner=expected_new_owner)
                if (candidate._descriptor != current or candidate._session_root != self._session_root
                        or candidate._continued is not True or self._read_owner() != current):
                    raise MachineTransportError("Retired release continuation changed the original actor")
                candidate.require_client()
                self._check_identity()
                if self._hook_rebind_guard is not None:
                    self._hook_rebind_guard()
                self._client, self._descriptor = client, current
                self._generation += 1
                self._continued = True
                self._state, self._rebind_candidate = "bound", None
                self._release_id = None
                return self.owner_status()
            except BaseException:
                self._state = "uncertain"
                raise

    @property
    def state(self):
        with self._lock:
            return self._state

    def recover_rebind_owner(self, *, expected_failed_owner, expected_current_owner):
        """Recover the exact retained continuation response; no new connect."""
        with self._lock:
            self._check_identity()
            if self._environment.get("ARCHHUB_NATIVE_WORKSHOP_OWNER"):
                if self._hook_rebind_guard is None:
                    raise MachineTransportError("Private hook recovery requires its admitted custody guard")
                self._hook_rebind_guard()
            candidate = self._rebind_candidate
            current = self._read_owner()
            if (self._state != "uncertain" or self._active_calls or candidate is None
                    or candidate._descriptor != current
                    or self._owner_fingerprint(current) != expected_current_owner
                    or self._owner_fingerprint(candidate._descriptor) != expected_failed_owner
                    or self._instance_identity(current) != self._instance_identity(self._descriptor)
                    or candidate._identity != self._identity):
                raise MachineTransportError("Native continuation recovery custody changed")
            client = candidate._client
            held = getattr(client,"_continuation_request",None)
            if (held is None or held.get("expected_agent_session") != self._session_root
                    or held.get("runtime") != self._identity.runtime
                    or held.get("external_session_id") != self._identity.external_session_id
                    or client._pinned_runtime_descriptor != current
                    or client.key_provider is not self._key_provider
                    or Path(client.descriptor_path).resolve() != self._descriptor_path):
                raise MachineTransportError("No exact retained native continuation attempt is available")
            from .application_machine_transport import MachineContinuationNotEnrolled
            try:
                result = client.recover_agent_session_continuation()
            except MachineContinuationNotEnrolled:
                # Only this exact candidate is settled. Preserve the original
                # client, owner, generation, and every prior effect uncertainty.
                if self._retired_release is not None or self._read_owner() != current:
                    raise MachineTransportError('Retired release or changed owner requires separate recovery')
                self._check_identity()
                if self._hook_rebind_guard is not None:
                    self._hook_rebind_guard()
                self._rebind_candidate = None
                self._state = 'bound'
                return {**self.owner_status(), 'continuation_outcome':'not-enrolled'}
            if (result.get("agent_session") != self._session_root or result.get("continued") is not True
                    or result.get("runtime") != self._identity.runtime
                    or result.get("agent_body") != "app:agent-body:"+self._identity.runtime
                    or result.get("catalog_entry") != "app:agent-body-catalog:v1:"+self._identity.runtime
                    or self._read_owner() != current):
                raise MachineTransportError("Recovered native continuation identity did not verify")
            self._check_identity()
            if self._hook_rebind_guard is not None:
                self._hook_rebind_guard()
            self._client, self._descriptor = client, current
            self._generation += 1
            self._continued = True
            self._state = "bound"
            self._rebind_candidate = None
            if self._retired_release is not None:
                self._release_id = None
            return self.owner_status()

    def inspect_enrollment(self, *, expected_owner, projection=None, cursor=None):
        """Read exact current custody with an unbound client; retain all state."""
        with self._lock:
            self._check_identity()
            actor = self._session_root or self._expected_agent_session
            current = self._read_owner()
            if (actor is None or self._owner_fingerprint(current) != expected_owner
                    or (self._descriptor is not None and
                        self._instance_identity(current) != self._instance_identity(self._descriptor))):
                raise MachineTransportError("Native enrollment inspection owner or actor changed")
            keys = self._key_provider
            inspection = self._factory(self._descriptor_path, keys)
            if (not isinstance(inspection,UniversalRuntimeClient) or inspection.agent_session_root
                    or inspection._agent_session_token or inspection.key_provider is not keys):
                raise MachineTransportError("Native inspection requires its own unbound client")
            inspection.pin_runtime_descriptor(current)
            result = inspection.reconcile_agent_session(runtime=self._identity.runtime,
                external_session_id=self._identity.external_session_id,expected_agent_session=actor,
                **({"projection": projection} if projection is not None else {}),
                **({"cursor": cursor} if cursor is not None else {}))
            if self._read_owner() != current:
                raise MachineTransportError("Native owner changed during enrollment inspection")
            self._check_identity()
            return {**result,"owner_fingerprint":expected_owner}

    def recover_connection(self, *, expected_owner):
        """Recover a conditional initial connection using only its outcome ID."""
        with self._lock:
            self._check_identity()
            current = self._read_owner()
            client = self._client
            held = getattr(client,"_continuation_request",None)
            if (self._state != "uncertain" or self._active_calls or self._rebind_candidate is not None
                    or self._expected_agent_session is None or self._descriptor != current
                    or self._owner_fingerprint(current) != expected_owner
                    or held is None or held.get("expected_agent_session") != self._expected_agent_session
                    or held.get("runtime") != self._identity.runtime
                    or held.get("external_session_id") != self._identity.external_session_id
                    or client._pinned_runtime_descriptor != current
                    or client.key_provider is not self._key_provider):
                raise MachineTransportError("No exact conditional native connection can be recovered")
            if self._environment.get("ARCHHUB_NATIVE_WORKSHOP_OWNER"):
                if self._hook_rebind_guard is None:
                    raise MachineTransportError("Private hook recovery requires its admitted custody guard")
                self._hook_rebind_guard()
            result = client.recover_agent_session_continuation()
            if (result.get("runtime") != self._identity.runtime
                    or result.get("agent_body") != "app:agent-body:"+self._identity.runtime
                    or result.get("catalog_entry") != "app:agent-body-catalog:v1:"+self._identity.runtime
                    or self._read_owner() != current):
                raise MachineTransportError("Recovered native connection identity did not verify")
            self._check_identity()
            if self._hook_rebind_guard is not None:
                self._hook_rebind_guard()
            self._session_root = self._expected_agent_session
            self._continued = True
            self._generation += 1
            self._state = "bound"
            return self.owner_status()

    def _check_identity(self):
        if self._opencode_custody is not None:
            self._opencode_custody.check()
        if (self._hook_rebind_guard is not None
                and self._environment.get("ARCHHUB_NATIVE_WORKSHOP_OWNER") != "claude-stdio-v1"):
            raise MachineTransportError("Native hook ownership mode changed")
        if resolve_native_agent_identity(self._environment) != self._identity:
            raise MachineTransportError("native agent identity changed; attachment is retained")

    def _existing_key_provider(self):
        """Resolve existing custody before any descriptor read; never provision."""
        if self._key_provider is None:
            if not self._key_path.is_file():
                raise MachineTransportError("existing signing keyring is missing")
            self._key_provider = WindowsDpapiSigningKeyProvider(self._key_path)
        elif isinstance(self._key_provider, WindowsDpapiSigningKeyProvider) and not self._key_provider.path.is_file():
            raise MachineTransportError("existing signing keyring is missing")
        return self._key_provider

    def _read_owner(self):
        if (not self._descriptor_path.is_file()
                or self._descriptor_path.stat().st_size > 65536):
            raise MachineTransportError("existing runtime descriptor is unavailable")
        descriptor = _read_descriptor(self._descriptor_path, self._existing_key_provider())
        if descriptor.status != "active" or not descriptor.database or not Path(descriptor.database).is_file():
            raise MachineTransportError("an active persistent installed owner is required")
        return descriptor

    def _require_bound(self):
        self._check_identity()
        if self._state != "bound":
            raise MachineTransportError("native agent attachment is not bound; no automatic enrollment retry")
        client = self._client
        if (self._read_owner() != self._descriptor
                or client._pinned_runtime_descriptor != self._descriptor
                or Path(client.descriptor_path).resolve() != self._descriptor_path
                or client.key_provider is not self._key_provider
                or client.agent_session_root != self._session_root
                or client.agent_session_access != "full"
                or type(client._agent_session_token) is not str or len(client._agent_session_token) < 32):
            raise MachineTransportError("native agent client or owner binding changed")
        return client

    def require_client(self) -> UniversalRuntimeClient:
        """Return the same guarded client without performing enrollment."""
        with self.bound_client() as client:
            return client

    @contextmanager
    def bound_client(self):
        """Hold instance then client locks through a tool call; never enroll.

        Callers must enter this before taking the client request lock, so Work
        and Workshop adapters share one lock order with connect().
        """
        with self._lock:
            if self._client is None:
                raise MachineTransportError("native agent attachment has no bound client")
            with self._client._request_lock:
                client = self._require_bound()
                self._active_calls += 1
                try:
                    yield client
                    # Preserve an operation exception; validate normal returns.
                    self._require_bound()
                finally:
                    self._active_calls -= 1

    def attach_workshop_host(self, connection, *, node_executable,
                             state_directory, ttl_seconds=300):
        """Attach the exact existing bridge through this session's bound client."""
        from .session_link_host import run_host_handoff
        with self.bound_client() as client:
            return run_host_handoff(client, node_executable=node_executable,
                state_directory=state_directory, operation="attach",
                connection=connection, ttl_seconds=ttl_seconds)

    def detach_workshop_host(self):
        """Detach through this bound owner, even if local Node is unavailable.

        The application already owns channel cancellation and revocation. No
        host delegation or child process is necessary to request retirement.
        """
        with self.bound_client() as client:
            return client.detach_session_link()

    def close(self):
        """Explicit capability release; preserve identity and uncertain custody."""
        with self._lock:
            if self._state == "released":
                return dict(self._release_result)
            if self._state not in {"bound", "release-uncertain"}:
                raise MachineTransportError("native owner cannot release from current state")
            self._check_identity()
            if self._active_calls or self._rebind_candidate is not None:
                raise MachineTransportError("native owner has an active operation or rebind")
            if self._read_owner() != self._descriptor:
                raise MachineTransportError("native release runtime owner changed")
            recover = self._state == "release-uncertain"
            if not recover:
                import uuid
                self._require_bound()
                self._release_id = f"{int(time.time()):08x}" + uuid.uuid4().hex[:24]
            self._state = "release-uncertain"
            result = self._client.release_agent_session(self._release_id, recover=recover)
            self._check_identity()
            if (recover and result.get("released") is False and result.get("retained") is True
                    and result.get("agent_session") == self._session_root
                    and result.get("release_id") == self._release_id
                    and self._read_owner() == self._descriptor):
                self._state = "bound"
                self._release_id = None
                return dict(result)
            if (result.get("agent_session") != self._session_root
                    or result.get("release_id") != self._release_id
                    or result.get("released") is not True
                    or self._read_owner() != self._descriptor):
                raise MachineTransportError("native release reply or runtime drifted")
            self._release_result = dict(result)
            self._state = "released"
            return dict(result)

    def connect(self, *, expected_owner=None) -> UniversalRuntimeClient:
        with self._lock:
            if self._state == "bound":
                if expected_owner is not None and self._owner_fingerprint(self._descriptor) != expected_owner:
                    raise MachineTransportError("Native connection owner does not match expected owner")
                return self.require_client()
            if self._state != "unbound":
                raise MachineTransportError("native agent attachment is uncertain; no automatic enrollment retry")
            # Reserve the attempt before any effect-capable dependency is called.
            self._state = "attaching"
            try:
                self._check_identity()
                self._descriptor = self._read_owner()
                if expected_owner is not None and self._owner_fingerprint(self._descriptor) != expected_owner:
                    raise MachineTransportError("Native connection owner changed before enrollment")
                self._client = self._factory(self._descriptor_path, self._key_provider)
                client = self._client
                if not isinstance(client, UniversalRuntimeClient):
                    raise MachineTransportError("native attachment requires its own runtime client")
                with client._request_lock:
                    if (client.agent_session_root or client._agent_session_token
                            or client._pinned_runtime_descriptor is not None
                            or Path(client.descriptor_path).resolve() != self._descriptor_path
                            or client.key_provider is not self._key_provider):
                        raise MachineTransportError("native attachment cannot borrow an existing client binding")
                    client.pin_runtime_descriptor(self._descriptor)
                    conditional = ({"expected_agent_session":self._expected_agent_session}
                        if self._expected_agent_session is not None else {})
                    result = client.bind_agent_session(runtime=self._identity.runtime,
                        external_session_id=self._identity.external_session_id, **conditional)
                    self._check_identity()
                    runtime = self._identity.runtime
                    root = result.get("agent_session") if type(result) is dict else None
                    expires = result.get("expires_at") if type(result) is dict else None
                    if (type(result) is not dict or result.get("runtime") != runtime
                            or type(root) is not str or not _SESSION_ROOT.fullmatch(root)
                            or root == self._descriptor.agent_session_root
                            or result.get("agent_body") != "app:agent-body:" + runtime
                            or result.get("catalog_entry") != "app:agent-body-catalog:v1:" + runtime
                            or result.get("session_token") != client._agent_session_token
                            or client.agent_session_root != root or client.agent_session_access != "full"
                            or type(expires) not in (int, float) or not math.isfinite(expires)
                            or expires <= time.time() or client._agent_session_expires_at != expires
                            or self._read_owner() != self._descriptor
                            or client._pinned_runtime_descriptor != self._descriptor):
                        raise MachineTransportError("native agent enrollment reply does not match this attachment")
                    self._session_root = root
                    self._continued = result.get("continued") is True
                    self._generation += 1
                    self._state = "bound"
                    return client
            except BaseException:
                # Keep even a partially populated client; never hide lost-reply
                # uncertainty by replacing it with another enrollment attempt.
                self._state = "uncertain"
                raise


__all__ = ["NativeAgentIdentity", "NativeAgentSession", "resolve_native_agent_identity"]
