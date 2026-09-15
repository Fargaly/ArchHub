"""Signed runtime evidence for one app-owned, restricted native Workshop turn.

This court does not certify external CLI hooks or a private Brain connection.
It preserves the legacy court and proves the distinct graph-bound native profile.
There is no listener, enrollment, provider call or permission mint in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from types import MappingProxyType

from .cell_adapters import read_permission
from .cell_attestations import CourtResult, COURT_PREDICATE_TYPE, build_court_definition, verify_court_definition
from .cell_model_execution import read_model_delegation, read_model_execution_grant
from .cell_protocols import read_relation, prepare_append_relation_members
from .cell_value_graph import read_value_graph
from .universal_cell import InvalidCell, overlay_read_snapshot

COURT = "app:court:native-workshop-runtime-compliance:v1"
PROVIDER = "app:model-provider:native-workshop-turn:claude:v1"
CHECKS = ("subject-digest", "owned-pipe-peer", "restricted-profile", "bound-session",
          "exact-work-admission", "graph-tool-gates")
BUILDER = "https://archhub.local/builder/native-workshop-runtime-compliance"


def _require(value, message):
    if not value:
        raise InvalidCell(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def graph_binding(snapshot, registry, session_root):
    """One exact graph identity; no lifetime scan of accumulated executions."""
    protocol, adapters = registry.baboom_model_execution_protocol, registry.adapter_protocol
    root = session_root + ":native-workshop-delegation:v1"
    if root not in snapshot.cells:
        return None
    delegation = read_model_delegation(snapshot, protocol, adapters, root)
    _require(delegation.session_root == session_root and delegation.provider_root == PROVIDER
             and not delegation.cognition_request_root and time.time() < delegation.expires_at,
             "Native compliance delegation is expired or has different semantics")
    grant = read_model_execution_grant(snapshot, protocol, adapters, root + ":grant")
    _require(grant.delegation_root == root and grant.session_root == session_root
             and time.time() < grant.expires_at,
             "Native compliance requires its exact current execution grant")
    permission = read_permission(snapshot, adapters, delegation.permission_root)
    _require(permission.lifecycle_root == adapters.states["granted"],
             "Native compliance requires current user consent")
    value = read_value_graph(snapshot, registry.value_graph_protocol, root + ":input")
    _require(type(value) is dict and value.get("session") == session_root
             and value.get("work") == delegation.work_root
             and value.get("contract") == "native-workshop-task-v1"
             and hashlib.sha256(_canonical(value)).hexdigest() == delegation.input_digest,
             "Native compliance sealed input changed")
    return {"nativeDelegation": root, "nativeGrant": grant.root_id,
            "nativeInputDigest": delegation.input_digest, "nativeWork": delegation.work_root,
            "nativeProfile": value["contract"]}


def _request_owner(registry):
    from .application_server import _VERIFIED_MACHINE_PEER_CONTEXT
    current = _VERIFIED_MACHINE_PEER_CONTEXT.get()
    _require(current is not None and current[0].universal_registry is registry,
             "Native compliance requires its current accepted request")
    return current[0]


def _profile_parameters(server, session_root):
    from .native_workshop_profile import NativeWorkshopProfile
    host = getattr(server, "_existing_workshop_native_host", None)
    held = host._native if host is not None else None
    _require(type(held) is dict and held.get("worker") == session_root
             and not host._native_stop_requested() and not host._cancel.is_set()
             and not server._model_execution_closing, "Native runtime is stopping or no longer owned")
    profile = held.get("profile")
    _require(type(profile) is NativeWorkshopProfile, "Native profile custody is unavailable")
    profile.verify()
    sources = getattr(profile, "source_digests", None)
    _require(isinstance(sources, (dict, MappingProxyType)) and 0 < len(sources) <= 32
             and all(type(key) is str and type(value) is str and len(value) == 64
                     for key, value in sources.items()), "Native task-server source custody is unavailable")
    # These are selected disk fingerprints, not an attestation of all loaded code.
    return {"nativeCodeDigest": hashlib.sha256(_canonical(dict(sources))).hexdigest(),
            "nativeProfileDigest": hashlib.sha256(_canonical({"argv": profile.argv,
                "configs": dict(profile.config_digests), "sources": dict(sources)})).hexdigest()}


def evidence_contract(snapshot, registry, session_root, parameters):
    binding = graph_binding(snapshot, registry, session_root)
    if binding is None:
        # Missing native graph admission must not borrow a legacy green audit.
        from .application_server import _VERIFIED_MACHINE_PEER_CONTEXT
        current = _VERIFIED_MACHINE_PEER_CONTEXT.get()
        host = getattr(current[0], "_existing_workshop_native_host", None) if current else None
        held = host._native if host is not None else None
        profile = held.get("profile") if type(held) is dict else None
        if (current and current[0].universal_registry is registry and profile is not None
                and hashlib.sha256(profile.external_session_id.encode()).hexdigest()
                == parameters.get("sessionFingerprint")):
            raise InvalidCell("Owned native session has no admitted graph delegation")
        return registry.runtime_compliance_court_root, parameters
    _require(COURT in snapshot.cells, "Restricted native compliance court is unavailable")
    physical = _profile_parameters(_request_owner(registry), session_root)
    return COURT, MappingProxyType({**parameters, **binding, **physical})


def require_current_native_custody(registry, *, subject_name, subject_content, parameters):
    """Recheck live custody at admission without minting or replaying evidence."""
    from .cell_attestations import CourtInvocation
    server = _request_owner(registry)
    runner = getattr(server, "_native_workshop_compliance_runner", None)
    _require(type(runner) is NativeWorkshopComplianceRunner and runner.server is server,
             "Restricted native compliance runner is unavailable")
    result = runner(CourtInvocation(subject_name, hashlib.sha256(subject_content).hexdigest(),
                                    subject_content, parameters))
    _require(result.passed and set(result.checks) == set(CHECKS) and all(result.checks.values()),
             "Current native runtime custody or graph admission changed")


class _PreparedCourt:
    def __init__(self, snapshot):
        self.base, self.current = snapshot, snapshot
        self.create, self.replace = {}, {}
    @property
    def revision(self):
        return self.current.revision
    def snapshot(self):
        return self.current
    def read(self, root):
        return self.current.cells[root]
    def commit(self, expected_revision, *, create=(), replace=()):
        _require(expected_revision == self.revision, "Native court preparation drifted")
        create, replace = tuple(create), tuple(replace)
        self.current = overlay_read_snapshot(self.current, create=create, replace=replace)
        for cell in create:
            self.create[cell.id] = cell
        for cell in replace:
            (self.create if cell.id in self.create else self.replace)[cell.id] = cell
        return self.revision


def install_native_workshop_compliance(server):
    """Bind the product court before transport start; legacy runner is unchanged."""
    existing = getattr(server, "_native_workshop_compliance_runner", None)
    if existing is not None:
        _require(type(existing) is NativeWorkshopComplianceRunner and existing.server is server,
                 "Native compliance owner binding changed")
        return existing
    registry, store = server.universal_registry, server.universal_store
    with server.mutation_lock:
        pending = _PreparedCourt(store.snapshot())
        legacy = verify_court_definition(pending.snapshot(), registry.attestation_protocol,
                                         registry.runtime_compliance_court_root)
        policy_digest = pending.read(legacy.policy_digest_root).atom.decode("utf-8")
        if COURT not in pending.snapshot().cells:
            build_court_definition(pending, registry.attestation_protocol, court_id=COURT,
                name="Restricted native Workshop runtime compliance", builder_id=BUILDER,
                runner_version="1.0.0", policy_digest=policy_digest, checks=CHECKS)
        definition = verify_court_definition(pending.snapshot(), registry.attestation_protocol, COURT)
        _require(pending.read(definition.builder_root).atom.decode() == BUILDER
                 and pending.read(definition.name_root).atom == b"Restricted native Workshop runtime compliance"
                 and pending.read(definition.predicate_type_root).atom.decode() == COURT_PREDICATE_TYPE
                 and pending.read(definition.runner_version_root).atom == b"1.0.0"
                 and pending.read(definition.policy_digest_root).atom.decode() == policy_digest
                 and tuple(pending.read(root).atom.decode() for root in definition.check_roots) == CHECKS,
                 "Restricted native compliance court contract drifted")
        members = read_relation(pending.snapshot(), registry.application_root, budget=100000)
        held = [row for row in members if row.role_id == registry.roles["member"]
                and row.participant_id == COURT]
        _require(len(held) <= 1, "Native compliance court membership is ambiguous")
        if not held:
            patch = prepare_append_relation_members(pending.snapshot(), registry.application_root,
                ((registry.roles["member"], COURT),), budget=100000)
            pending.commit(pending.revision, create=patch.create, replace=patch.replace)
        if pending.create or pending.replace:
            context = registry.authorization.session.context()
            registry.authorization.broker.commit_authenticated(context, store, pending.base.revision,
                create=tuple(pending.create.values()), replace=tuple(pending.replace.values()))
        runner = NativeWorkshopComplianceRunner(server)
        registry.attestation_broker.admit_court(store.snapshot(), registry.attestation_protocol, COURT, runner)
        server._native_workshop_compliance_runner = runner
        return runner


class NativeWorkshopComplianceRunner:
    """Observe current owner custody; no claims, hooks, retries or provider calls."""
    def __init__(self, server):
        self.server = server

    def __call__(self, invocation):
        checks = {name: False for name in CHECKS}
        details = {"adapter": "restricted-native-workshop-v1", "status": "red"}
        try:
            self._observe(invocation, checks, details)
        except Exception as error:
            details["errorType"] = type(error).__name__
        passed = all(checks.values())
        details["status"] = "green" if passed else "red"
        return CourtResult(passed, MappingProxyType(checks), MappingProxyType(details))

    def _observe(self, invocation, checks, details):
        from . import universal_application as app
        from .application_server import _VERIFIED_MACHINE_PEER_CONTEXT
        from .application_machine_transport import MachinePipePeer, peer_matches_process
        from .native_workshop_execution import _reservation, _validated, _invocation
        from .native_workshop_profile import NativeWorkshopProfile, SERVER_NAME
        from .native_workshop_tools import WORKSHOP_TASK_TOOL_NAMES
        server, registry, store = self.server, self.server.universal_registry, self.server.universal_store
        with server.mutation_lock:
            session, entry, parameters, content = app._runtime_compliance_subject(
                store.snapshot(), registry, invocation.subject_name)
            court, expected = evidence_contract(store.snapshot(), registry, session.root_id, parameters)
            _require(court == COURT and dict(invocation.external_parameters) == dict(expected)
                     and invocation.subject_content == content
                     and invocation.subject_digest == hashlib.sha256(content).hexdigest(),
                     "Native court subject or grant binding changed")
            checks["subject-digest"] = True
            current = _VERIFIED_MACHINE_PEER_CONTEXT.get()
            _require(current is not None and current[0] is server and type(current[2]) is MachinePipePeer,
                     "Native court requires its current accepted pipe peer")
            request, peer = current[1], current[2]
            request_session, binding = server._machine_agent_binding_for_request(request)
            _require(request_session == session.root_id and entry.runtime == "claude"
                     and entry.credential_mode == "machine-transport"
                     and binding.get("runtime") == "claude"
                     and binding.get("external_session_fingerprint") == parameters["sessionFingerprint"]
                     and type(binding.get("expires_at")) in (int, float)
                     and math.isfinite(binding["expires_at"]) and time.time() < binding["expires_at"],
                     "Native court request session is not currently bound")
            checks["bound-session"] = True
            host = getattr(server, "_existing_workshop_native_host", None)
            held = host._native if host is not None else None
            _require(type(held) is dict and held.get("worker") == session.root_id
                     and not host._native_stop_requested()
                     and host._native_owned_session() == session.root_id
                     and peer_matches_process(binding.get("enrollment_peer"), peer.pid, peer.created_at),
                     "Native court peer is not the retained child")
            checks["owned-pipe-peer"] = True
            profile = held.get("profile")
            _require(type(profile) is NativeWorkshopProfile and profile.work_root == expected["nativeWork"]
                     and hashlib.sha256(profile.external_session_id.encode()).hexdigest()
                         == parameters["sessionFingerprint"], "Native profile identity changed")
            profile.verify()
            argv = profile.argv
            _require(argv.count("--tools") == 1 and argv[argv.index("--tools") + 1] == ""
                     and "--strict-mcp-config" in argv and "--setting-sources=" in argv,
                     "Native built-in or server scope changed")
            readiness = held.get("readiness")
            servers = readiness.get("mcpServers") if type(readiness) is dict else None
            _require(type(servers) is list and len(servers) == 1 and type(servers[0]) is dict
                     and servers[0].get("name") == SERVER_NAME and servers[0].get("status") == "connected"
                     and type(servers[0].get("tools")) is list
                     and len(servers[0]["tools"]) == len(WORKSHOP_TASK_TOOL_NAMES)
                     and all(type(row) is dict for row in servers[0]["tools"])
                     and {row.get("name") for row in servers[0]["tools"]} == set(WORKSHOP_TASK_TOOL_NAMES),
                     "Native connected tool inventory is not exact")
            checks["restricted-profile"] = True
            reservation = _reservation(server, held.get("reservation"))
            _require(reservation._consumed and reservation._settled is None
                     and reservation._grant.root_id == expected["nativeGrant"]
                     and held.get("payload", {}).get("grant") == expected["nativeGrant"]
                     and server._model_execution_active is True
                     and not server._model_execution_idle.is_set(),
                     "Native court has no current consumed owner grant")
            delegation, provider, material = _validated(server, expected["nativeDelegation"],
                expected["nativeInputDigest"], host._browser_binding.context, publication=True)
            _invocation(server, delegation, provider)
            _require(material == reservation._material and host._identity[5] == expected["nativeWork"],
                     "Native court Work material changed")
            checks["exact-work-admission"] = True
            current_profile = _profile_parameters(server, session.root_id)
            _require(all(expected[name] == value for name, value in current_profile.items()),
                     "Native task-server disk source or profile changed")
            details["codeDigest"] = current_profile["nativeCodeDigest"]
            details["work"] = expected["nativeWork"]
            details["grant"] = expected["nativeGrant"]
            checks["graph-tool-gates"] = True
