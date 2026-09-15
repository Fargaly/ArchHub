"""One native Workshop operation over the application's existing graph APIs.

Only in-flight delivery state lives here. Work, delegation, consent, execution
and result authority remain in the application graph. No background polling.
"""
import re
import threading

from .baboom_attach import prepare_workshop_execution_client
from .cell_authorization import AuthorizationDenied
from .existing_workshop_conversation import _admit, read_browser_workshop_model_approval
from .existing_workshop_model_worker import ExistingWorkshopModelWorker, SettledModelWork
from .universal_cell import InvalidCell


# The machine transport may wrap arbitrary remote text. Only reviewed,
# data-free diagnostics may enter a browser status; never retain repr(exc),
# tracebacks, request bodies, capabilities, or the device credential.
_RECOVERY_SAFE_ERRORS = frozenset({
    "Workshop session identity is invalid",
    "Workshop attachment cancelled",
    "The existing native device key is unavailable",
    "Native Workshop attachment requires the authenticated founder",
    "runtime client already has an Agent Session",
    "runtime device credential is invalid",
    "runtime device proof signature is invalid",
    "runtime device proof is invalid",
    "runtime device proof was replayed",
    "runtime device proof challenge is invalid: no challenge with that id is held",
    "runtime device proof challenge is invalid: that challenge was already spent",
    "runtime device proof challenge is invalid: it was minted for another Agent Body entry",
    "runtime device proof challenge is invalid: it was minted for another runtime instance",
    "runtime device custody is not catalog-bound",
    "runtime device custody is revoked",
    "runtime Agent Body does not use device custody",
    "only the founder may bind runtime device custody",
    "runtime Agent Session identity is already bound; renew it instead",
    "runtime Agent Session identity binding drifted",
    "runtime Agent Session identity custody drifted",
    "runtime Agent Session identity credential mode drifted",
    "runtime Agent Session identity evidence drifted",
    "runtime Agent Session identity is not active",
    "runtime Agent Session identity target drifted",
    "runtime Agent Session identity is already bound differently",
    "runtime Agent Session identity binding did not verify",
    "runtime Agent Session catalog continuation drifted",
    "runtime Agent Session continuation is ambiguous",
    "runtime Agent Session surface property drifted",
    "runtime Agent Session surface property is malformed",
    "runtime Agent Session surface property is ambiguous",
    "runtime Agent Session control membership is duplicated",
    "runtime Agent Session is outside one unique catalog capability",
    "runtime Agent Session is outside the active Agent Body",
    "runtime Agent Session patches conflict",
    "runtime Agent Session is unknown",
    "runtime Agent Session capability expired",
    "runtime Agent Session proof is invalid",
    "runtime Agent Session is not active",
    "runtime Agent Session catalog binding drifted",
    "runtime Agent Session device custody drifted",
    "Agent Session enrollment response is invalid",
    "Agent Session challenge shape is invalid",
    "Agent Session enrollment shape is invalid",
    "Agent Session enrollment identity is invalid",
    "authority snapshot revision is stale",
    "authenticated context expired",
    "unknown authenticated context",
    "universal runtime request cancelled",
    "universal runtime is not active",
    "universal runtime pipe is unavailable",
    "universal runtime did not respond",
    "universal runtime response is invalid",
    "universal runtime response binding failed",
    "universal runtime result is invalid",
    "machine request exceeds its size limit",
    "machine response exceeds its size limit",
    "request denied",
    "Recovery requires a fresh worker identity",
    "Workshop execution identity is invalid",
    "Workshop worker binding changed",
    "Failed project evidence changed during recovery",
    "The failed worker no longer owns this Work claim",
    "Project execution must settle before recovery",
    "The failed worker still has a live capability",
    "A newer or ambiguously ordered invocation prevents this retry",
    "An invocation without a settled receipt prevents this retry",
    "An unsettled delegation prevents this retry",
    "Project recovery exceeds its bounded execution registry",
    "Project recovery has ambiguous execution settlement",
    "Work changed after recovery admission; refresh before recovering",
    "Work claimant changed after recovery admission",
    "stale work claim recovery target is not registered",
    "stale work claim recovery target is not claimed",
    "stale work claim recovery has no claimant",
    "stale work claim recovery already owns target",
    "claimed Agent Session still has a live capability",
    "Work recovery returned another claim",
    "Recovered project preparation returned another Work or worker",
})

_RECOVERY_SAFE_ERROR_PATTERNS = (
    (re.compile(r"expected revision [0-9]{1,20}, current revision is [0-9]{1,20}"),
     "recovery_revision_conflict"),
    (re.compile(r"runtime device proof challenge is invalid: it expired [0-9]{1,12}\.[0-9]s ago"),
     "recovery_device_challenge_expired"),
)


def _recovery_error_details(error):
    from .application_machine_transport import MachineTransportError
    if isinstance(error, MachineTransportError):
        error_type, code = "MachineTransportError", "recovery_transport_error"
    elif isinstance(error, AuthorizationDenied):
        error_type, code = "AuthorizationDenied", "recovery_authorization_denied"
    elif isinstance(error, InvalidCell):
        error_type, code = "InvalidCell", "recovery_invalid_state"
    else:
        return {"type":"Exception", "code":"recovery_unexpected_error",
                "message":None, "message_retained":False}
    # Do not call arbitrary __str__ implementations or stringify object args.
    message = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
    retained = message is not None and len(message) <= 256 and message in _RECOVERY_SAFE_ERRORS
    if not retained and message is not None and len(message) <= 256:
        for pattern, diagnostic_code in _RECOVERY_SAFE_ERROR_PATTERNS:
            if pattern.fullmatch(message):
                retained, code = True, diagnostic_code
                break
    return {"type":error_type, "code":code, "message":message if retained else None,
            "message_retained":retained}


def _execution_registry_roots(snapshot, protocol, name):
    from .cell_protocols import read_relation
    members = read_relation(snapshot, protocol.registry(name), budget=8192,
                            retain_projection=False)
    roots = [member.participant_id for member in members
             if member.role_id == protocol.role("registry-member")]
    if len(roots) > 256 or len(set(roots)) != len(roots):
        raise InvalidCell("Project recovery exceeds its bounded execution registry")
    return roots


def _project_failures(snapshot, registry, work, *, result_root=None, receipt_root=None):
    """Read exact failed host evidence; metadata cannot itself admit a retry."""
    import hashlib
    from .cell_connector_execution import read_connector_execution_receipt, read_connector_delegation
    from .cell_value_graph import read_value_graph
    from .existing_workshop_project_execution import PROVIDER, OPERATION
    protocol = registry.baboom_connector_execution_protocol
    roots = ([receipt_root] if receipt_root is not None else
             _execution_registry_roots(snapshot, protocol, "receipt"))
    failures = []
    for root in roots:
        receipt = read_connector_execution_receipt(snapshot, protocol, registry.adapter_protocol, root)
        delegation = read_connector_delegation(snapshot, protocol, registry.adapter_protocol,
                                                receipt.delegation_root)
        if delegation.work_root != work:
            if receipt_root is not None:
                raise AuthorizationDenied("Failed project receipt belongs to another Work")
            continue
        if (receipt.outcome != "failed" or receipt.operation != OPERATION
                or receipt.provider_root != registry.baboom_connector_provider_roots.get(PROVIDER)):
            if receipt_root is not None:
                raise InvalidCell("Recovery requires a settled failed project receipt")
            continue
        expected_root = receipt.grant_root + ":project-result"
        if result_root is not None and result_root != expected_root:
            raise InvalidCell("Failed project result does not match its receipt")
        value = read_value_graph(snapshot, registry.value_graph_protocol, expected_root, max_depth=4)
        expected = {"work", "session", "delegation", "grant", "input_digest", "outcome",
                    "artifact_name", "output_digest", "output_bytes", "error_code", "summary"}
        if (type(value) is not dict or set(value) != expected
                or value["work"] != work or value["session"] != delegation.session_root
                or value["delegation"] != delegation.root_id or value["grant"] != receipt.grant_root
                or value["input_digest"] != receipt.input_digest
                or value["outcome"] != "failed" or value["error_code"] != receipt.error_code
                or type(value["output_bytes"]) is not int or value["output_bytes"] != receipt.output_bytes
                or value["output_digest"] != receipt.output_digest
                or receipt.output_bytes != 0 or receipt.output_digest != hashlib.sha256(b"").hexdigest()):
            raise InvalidCell("Failed project result disagrees with its execution receipt")
        failures.append({"work":work, "result":expected_root, "receipt":receipt.root_id,
            "worker":delegation.session_root, "grant":receipt.grant_root,
            "input_digest":receipt.input_digest, "outcome":"failed", "error":receipt.error_code,
            "created_at":receipt.created_at})
        if len(failures) > 32:
            raise InvalidCell("Selected Work has too many failed results for one bounded projection")
    return failures


def _require_latest_settled_failure(snapshot, registry, work, failure, *, store=None):
    """Unknown invocations require receipts or an older exact local decision."""
    import time
    from .cell_adapters import read_permission
    from .cell_connector_execution import (read_connector_delegation,
        read_connector_execution_grant, read_connector_execution_receipt)
    from .cell_model_execution import (read_model_delegation,
        read_model_execution_grant, read_model_execution_receipt)
    selected_birth = None
    if store is not None:
        if store.revision != snapshot.revision:
            raise InvalidCell("Project settlement snapshot changed")
        selected = read_connector_execution_receipt(snapshot, registry.baboom_connector_execution_protocol,
            registry.adapter_protocol, failure["receipt"])
        selected_delegation = read_connector_delegation(snapshot, registry.baboom_connector_execution_protocol,
            registry.adapter_protocol, selected.delegation_root)
        if selected_delegation.work_root != work:
            raise AuthorizationDenied("Project settlement receipt belongs to another Work")
        selected_birth = store.cell_created_revision(selected.grant_root)
        if selected_birth < 1:
            raise InvalidCell("Project settlement chronology is unavailable")
    families = ((registry.baboom_connector_execution_protocol, read_connector_delegation,
                 read_connector_execution_grant, read_connector_execution_receipt),
                (registry.baboom_model_execution_protocol, read_model_delegation,
                 read_model_execution_grant, read_model_execution_receipt))
    for protocol, read_delegation, read_grant, read_receipt in families:
        delegations = {}
        for root in _execution_registry_roots(snapshot, protocol, "delegation"):
            row = read_delegation(snapshot, protocol, registry.adapter_protocol, root)
            if row.work_root == work:
                delegations[root] = row
        receipts = {}
        settled_delegations = set()
        for root in _execution_registry_roots(snapshot, protocol, "receipt"):
            row = read_receipt(snapshot, protocol, registry.adapter_protocol, root)
            if row.delegation_root not in delegations:
                continue
            if row.grant_root in receipts:
                raise InvalidCell("Project recovery has ambiguous execution settlement")
            receipts[row.grant_root] = row
            settled_delegations.add(row.delegation_root)
            if row.root_id != failure["receipt"] and row.created_at >= failure["created_at"]:
                raise AuthorizationDenied("A newer or ambiguously ordered invocation prevents this retry")
        for root in _execution_registry_roots(snapshot, protocol, "grant"):
            grant = read_grant(snapshot, protocol, registry.adapter_protocol, root)
            if grant.delegation_root in delegations and grant.root_id not in receipts:
                if store is not None and protocol is registry.baboom_connector_execution_protocol:
                    from .workshop_project_resolution import read_project_delivery_resolution
                    decision = read_project_delivery_resolution(snapshot, registry, root, store=store)
                    if decision is not None and decision["grant_revision"] < selected_birth:
                        # This closes only local delivery; the provider remains
                        # unknown and no connector receipt is fabricated.
                        settled_delegations.add(grant.delegation_root)
                        continue
                raise AuthorizationDenied("An invocation without a settled receipt prevents this retry")
        for root, delegation in delegations.items():
            if root in settled_delegations:
                continue
            permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
            if (time.time() < delegation.expires_at and permission.lifecycle_root in
                    (registry.adapter_protocol.states["requested"], registry.adapter_protocol.states["granted"])):
                raise AuthorizationDenied("An unsettled delegation prevents this retry")
    if store is not None and store.revision != snapshot.revision:
        raise InvalidCell("Project settlement snapshot changed")


def _drain_native_process(process):
    """Honor both the retained launch budget and the host's five-second bound."""
    return process.stop(timeout_seconds=min(5, process.launch.stop_timeout_seconds))


class ExistingWorkshopNativeHost:
    def __init__(self, server, *, state_dir, descriptor_path, key_provider):
        self.server = server
        self.state_dir, self.descriptor_path = state_dir, descriptor_path
        self.key_provider = key_provider
        self._action = threading.Lock()
        self._cancel = threading.Event()
        self._identity = None
        self._browser_binding = None
        self._retired = {}
        self._retired_local = set()  # Same bounded native cache; never durable authority.
        self._status = {"state": "idle"}
        self._client = self._worker = self._prepared = self._grant = self._settled = None
        self._project = False
        self._recovery_source = None
        self._review_recovery = None
        self._review_recovery_pending = None
        self._review_refresh = None
        self._native = None  # Retained physical owner; graph holds task authority.

    def _native_stop_requested(self):
        held = self._native
        return held is not None and held['stop_requested'].is_set()

    def _request_native_stop(self, binding, *, root, scope, work, request_id):
        """Signal the retained operation without contending with its execution lock."""
        with self.server.mutation_lock:
            self._admit(binding, root, scope, work)
            identity = (*self._binding(binding, root, scope), work, request_id)
            if self._identity != identity or self._native is None:
                raise InvalidCell('Stop requires the exact retained native operation')
            self._native['stop_requested'].set()
            self._set(self._status['state'], stop_requested=True)
        return self.status(binding, root=root, scope=scope)

    def _native_control(self, request_id, deadline):
        import time
        driver = self._native['process']
        while (time.monotonic() < deadline and not self._cancel.is_set()
                and not self._native_stop_requested()):
            event = driver.wait_event(min(0.25, max(0, deadline - time.monotonic())))
            if event is not None and event.get('type') == 'control_response':
                response = event.get('response', {})
                if response.get('request_id') == request_id:
                    if response.get('subtype') != 'success':
                        raise InvalidCell('The connected agent refused Workshop initialization')
                    return response.get('response', {})
            status = driver.status()
            if status['error_code'] or not status['process_alive']:
                raise InvalidCell('The connected agent did not initialize; inspect the retained operation')
        raise InvalidCell('Agent initialization has not completed; do not launch it again')

    def _native_owned_session(self):
        """Match accepted-pipe custody to this retained observed MCP process."""
        import hashlib
        import time
        from .application_machine_transport import peer_matches_process
        held = self._native
        status = held['process'].status(force_observation=True)
        if (status['error_code'] or not status['process_alive'] or not status['initialized']
                or not status['tree_observed'] or status['tree_observation_uncertain']
                or status['tree_observation_pending']):
            raise AuthorizationDenied('The owned agent process could not be confirmed')
        fingerprint = hashlib.sha256(held['profile'].external_session_id.encode()).hexdigest()
        descendants = [row for row in status['remaining_processes']
                       if row['parent_pid'] is not None and row['alive']]
        with self.server._machine_agent_session_lock:
            matches = [root for root, entry in self.server._machine_agent_sessions.items()
                if entry.get('runtime') == 'claude'
                and entry.get('external_session_fingerprint') == fingerprint
                and entry.get('expires_at', 0) > time.time()
                and any(peer_matches_process(entry.get('enrollment_peer'),
                    row['pid'], row['created_at']) for row in descendants)]
        if len(matches) != 1 or held.get('worker') not in (None, matches[0]):
            raise AuthorizationDenied('The enrolled agent is not the owned Workshop child')
        return matches[0]

    def _prepare_native(self, binding, body, identity):
        import sys
        import time
        import uuid
        from pathlib import Path
        from . import universal_application as app
        from .cell_value_graph import read_value_graph
        from .native_workshop_execution import native_material_from_values, prepare_native_work
        from .native_workshop_profile import prepare_claude_workshop_profile, SERVER_NAME
        from .native_workshop_process import NativeWorkshopProcess
        from .native_workshop_tools import WORKSHOP_TASK_TOOL_NAMES
        import psutil

        work = body['work']
        store, registry = self.server.universal_store, self.server.universal_registry
        def material_now():
            self._admit(binding, body['root'], body['scope'], work)
            snapshot = store.snapshot()
            instance = app._instance_projection(snapshot, registry, work)
            interfaces = {row['name']:row for row in instance['interfaces']}
            inputs = read_value_graph(snapshot, registry.value_graph_protocol,
                app._governed_work_interface_target(snapshot, registry, work, 'inputs'))
            requirements = read_value_graph(snapshot, registry.value_graph_protocol,
                app._governed_work_interface_target(snapshot, registry, work, 'requirements'))
            material, raw = native_material_from_values(inputs, requirements,
                title=interfaces['title']['value'], description=interfaces['description']['value'])
            if store.revision != snapshot.revision:
                raise InvalidCell('The selected agent task changed during preparation')
            return material, raw
        with self.server.mutation_lock:
            material, launch_material = material_now()
        if psutil.virtual_memory().available < 8 * 1024**3:
            raise InvalidCell('Not enough free memory to start a Workshop agent alongside active work')
        executable = self.server.model_execution_broker._executable('local-cli:claude')
        python = Path(sys.base_prefix) / 'python.exe'
        if not executable or not python.is_file():
            raise InvalidCell('The selected native agent or its installed Python runtime is unavailable')
        self._identity, self._browser_binding = identity, binding
        self._native = {'process':None, 'profile':None, 'worker':None, 'reservation':None,
                        'terminal':None, 'artifact_result':None, 'result':None,
                        'stop_requested':threading.Event(), 'assignment':None}
        self._set('attaching', mode='agent', request_id=body['request_id'], work=work, approved=False)
        try:
            limits = dict(material['limits'])
            max_turns = limits.pop('max_turns')
            profile = prepare_claude_workshop_profile(install_root=Path(__file__).resolve().parent.parent,
                state_root=self.state_dir, python_executable=python, native_executable=executable,
                external_session_id=str(uuid.uuid4()), work_root=work, model=material['model'],
                tool_names=WORKSHOP_TASK_TOOL_NAMES, max_turns=max_turns)
            self._native['profile'] = profile
            process = NativeWorkshopProcess(profile.launch(**limits))
            self._native['process'] = process  # Retain before any fallible launch step.
            if self._native_stop_requested() or self._cancel.is_set():
                raise InvalidCell('Workshop initialization was cancelled')
            process.start()
            deadline = time.monotonic() + limits['startup_timeout_seconds']
            self._native_control(process.initialize(), deadline)
            while True:
                readiness = self._native_control(process.mcp_status(), deadline)
                servers = readiness.get('mcpServers')
                if (type(servers) is list and len(servers) == 1 and type(servers[0]) is dict
                        and servers[0].get('name') == SERVER_NAME and servers[0].get('status') == 'pending'):
                    if (self._cancel.wait(min(0.25, max(0, deadline - time.monotonic())))
                            or self._native_stop_requested()):
                        raise InvalidCell('Workshop initialization was cancelled')
                    continue  # Read readiness on the same retained child; never relaunch.
                break
            if (type(servers) is not list or len(servers) != 1 or type(servers[0]) is not dict
                    or servers[0].get('name') != SERVER_NAME
                    or servers[0].get('status') != 'connected'
                    or type(servers[0].get('tools')) is not list
                    or len(servers[0]['tools']) != len(WORKSHOP_TASK_TOOL_NAMES)
                    or any(type(tool) is not dict for tool in servers[0]['tools'])
                    or {tool.get('name') for tool in servers[0].get('tools', [])} != set(WORKSHOP_TASK_TOOL_NAMES)):
                raise InvalidCell('The agent did not connect to the exact Workshop tools')
            self._native['readiness'] = readiness
            worker = self._native_owned_session()
            self._native['worker'] = worker
            with self.server.mutation_lock:
                if self._native_stop_requested() or self._cancel.is_set():
                    raise InvalidCell('Workshop initialization was cancelled')
                current_material, current_raw = material_now()
                if current_raw != launch_material:
                    raise AuthorizationDenied('The task or model changed while its agent was starting')
                self._native['assignment'] = 'app:workshop-assignment:native-' + profile.external_session_id
                app.assign_universal_workshop_work(store, registry,
                    assignment_id=self._native['assignment'],
                    work_root=work, agent_session_root=worker, authentication_context=binding.context)
                prepared = prepare_native_work(self.server, work_root=work, session_root=worker,
                    context=binding.context,
                    before_commit=lambda: self._admit(binding, body['root'], body['scope'], work))
            self._prepared = prepared
            self._set('awaiting_approval', worker=worker, delegation=prepared['delegation'],
                input_digest=prepared['input_digest'], model=prepared['model'],
                review_text=prepared['review_text'], artifact_name=prepared['artifact_name'])
        except Exception:
            self._set('uncertain', error='Agent preparation needs reconciliation. The retained child will not be relaunched.')
            if self._native['process'] is not None:
                if self._native_stop_requested():
                    self._stop_native()
                else:
                    self._native['stop'] = _drain_native_process(self._native['process'])
            raise

    def _approve_native(self, binding, digest):
        from .native_workshop_execution import approve_native_work
        if (not self._native or not self._prepared or self._status['state'] != 'awaiting_approval'
                or self._native_stop_requested() or digest != self._prepared['input_digest']):
            raise InvalidCell('Review the current agent task before approving it')
        worker = self._native_owned_session()
        with self.server.mutation_lock:
            self._admit(binding, self._identity[3], self._identity[4], self._identity[5])
            if worker != self._prepared['worker']:
                raise AuthorizationDenied('The reviewed agent changed')
            consent = self.server.adapter_consent_broker
            gesture = consent.mint_from_user_gesture(self._prepared['permission_root'], binding.subject_root)
            approve_native_work(self.server, delegation_root=self._prepared['delegation'],
                reviewed_digest=digest, context=binding.context, consent_broker=consent, consent_handle=gesture,
                before_commit=lambda: self._admit(binding, self._identity[3], self._identity[4], self._identity[5]))
        self._set('awaiting_approval', approved=True)

    def _execute_native(self, binding):
        import time
        from .native_workshop_execution import (reserve_native_turn, consume_native_turn,
            native_artifact_admission, settle_native_turn)
        from .project_work_execution_broker import parse_repair_output, ProjectWorkExecutionResult

        held, prepared = self._native, self._prepared
        if (not held or not prepared or self._status['state'] != 'awaiting_approval'
                or self._status.get('approved') is not True or held['reservation'] is not None
                or held.get('reservation_pending') or self._native_stop_requested()):
            raise InvalidCell('Approve the selected agent task before running it once')
        worker = self._native_owned_session()
        held['profile'].verify()
        def admit():
            if self._cancel.is_set():
                raise AuthorizationDenied('Workshop is shutting down')
            if self._native_stop_requested():
                raise AuthorizationDenied('The native operation was stopped')
            return self._admit(binding, self._identity[3], self._identity[4], self._identity[5])
        server = self.server
        try:
            with server.mutation_lock:
                admit()
                if (server._model_execution_closing or server._model_execution_active
                        or server._project_work_pending is not None):
                    raise InvalidCell('Another application execution must finish first')
                held['reservation_pending'] = True
                reservation = reserve_native_turn(server, delegation_root=prepared['delegation'],
                    session_root=worker, external_session_id=held['profile'].external_session_id,
                    reviewed_digest=prepared['input_digest'], context=binding.context, before_commit=admit)
                held['reservation'] = reservation
                payload = consume_native_turn(server, reservation, context=binding.context, before_dispatch=admit)
                held['payload'] = payload
                server._model_execution_active = True
                server._model_execution_idle.clear()
        except Exception:
            if held.get('reservation_pending'):
                # The owner may have retained the exact reservation before a
                # graph-commit acknowledgement was lost. Never reserve again.
                with server.mutation_lock:
                    candidates = [row for row in getattr(server, '_native_workshop_reservations', {}).values()
                        if row._delegation.root_id == prepared['delegation']
                        and row.external_session_id == held['profile'].external_session_id]
                    if len(candidates) == 1:
                        held['reservation'] = candidates[0]
                self._set('uncertain', error='Task reservation needs reconciliation. No second grant or agent turn will be created.')
                held['stop'] = _drain_native_process(held['process'])
            raise
        driver = held['process']
        self._set('executing', error=None)
        try:
            admit()
            held['turn_id'] = driver.turn(payload['prompt'])
            deadline = time.monotonic() + payload['limits']['turn_timeout_seconds']
            while (time.monotonic() < deadline and not self._cancel.is_set()
                    and not self._native_stop_requested()):
                event = driver.wait_event(0.25)
                if event is not None and event.get('type') == 'result':
                    held['terminal'] = event
                    break
                current = driver.status()
                if current['error_code'] or (current['stdout_eof'] and current['queued_events'] == 0):
                    break
            terminal = held['terminal']
            current = driver.status()
            if terminal is None or current['error_code'] or current['last_turn'] is None or (
                    current['last_turn']['turn_id'] != held['turn_id']
                    or current['last_turn']['outcome'] not in ('returned', 'provider-error')):
                raise InvalidCell('The agent turn has an uncertain outcome; it will not be repeated')
            if not terminal['is_error']:
                try:
                    patch, summary = parse_repair_output(terminal['result'], payload['request']['inputs'])
                except InvalidCell:
                    import hashlib
                    # Parsing has no external effects. Record the confirmed
                    # refused output rather than inventing an uncertain write.
                    held['artifact_result'] = ProjectWorkExecutionResult(
                        outcome='failed', output_digest=hashlib.sha256(b'').hexdigest(),
                        output_bytes=0, error_code='native_output_invalid',
                        artifact_name=payload['artifact_name'], summary='')
                else:
                    publisher = server.project_work_execution_broker
                    if publisher is None:
                        raise InvalidCell('The application artifact publisher is unavailable')
                    held['artifact_result'] = publisher.publish_artifact(patch, payload['artifact_name'],
                        summary=summary, before_publish=lambda: native_artifact_admission(server,
                            reservation, context=binding.context, before_publish=admit))
            result = settle_native_turn(server, reservation, terminal=terminal,
                artifact_result=held['artifact_result'], context=binding.context)
            held['result'] = result
            if result.get('state') != 'settled' or not result.get('receipt'):
                self._set('uncertain', native_result=result,
                    error='Artifact delivery is unconfirmed. The saved attempt will not be repeated.')
            else:
                artifact = ({key:result[key] for key in ('work','result','receipt','name','digest','bytes','summary','outcome')}
                            if result.get('outcome') == 'succeeded' else None)
                self._set('settled', native_result=result, artifact=artifact,
                    error=None if result.get('outcome') == 'succeeded'
                        else 'The agent or artifact writer reported an error. Review the saved outcome.')
        except Exception:
            self._set('uncertain', error='The agent run or artifact delivery needs reconciliation. No task will be replayed.')
            raise
        finally:
            stop = _drain_native_process(driver)
            held['stop'] = stop
            with server.mutation_lock:
                if stop['drained']:
                    server._model_execution_active = False
                    server._model_execution_idle.set()
                else:
                    self._set('uncertain', error='The agent has not fully stopped. Its process ownership is retained.')

    def _stop_native(self):
        held = self._native
        if held is None or held['process'] is None:
            raise InvalidCell('There is no retained native process to stop')
        held['stop_requested'].set()
        result = _drain_native_process(held['process'])
        held['stop'] = result
        if result['drained']:
            with self.server.mutation_lock:
                # Only clear the execution slot if this operation reserved it.
                if held.get('payload') is not None:
                    self.server._model_execution_active = False
                    self.server._model_execution_idle.set()
        if result['drained'] and self._status['state'] in ('settled', 'published', 'publication_uncertain', 'native_cancelled'):
            self._set(self._status['state'], native_drained=True, stop_requested=True)
        else:
            unresolved = held.get('reservation_pending') or held.get('reservation') is not None
            self._set('native_stopped' if result['drained'] and not unresolved else 'uncertain',
                native_drained=result['drained'], stop_requested=True,
                error='Agent stopped; the graph Work and any unresolved result remain saved.' if result['drained']
                      else 'Agent stop is still pending. The retained process will not be replaced.')

    def _cancel_native_preparation(self, binding):
        from .native_workshop_execution import cancel_native_work
        held = self._native
        if (held is None or self._status['state'] not in ('native_stopped', 'native_cancelled')
                or not held.get('worker') or not held.get('assignment')):
            raise InvalidCell('The stopped native assignment needs reconciliation before release')
        try:
            result = cancel_native_work(self.server, work_root=self._identity[5],
                session_root=held['worker'], assignment_root=held['assignment'],
                process=held['process'], context=binding.context,
                delegation_root=self._prepared['delegation'] if self._prepared else None,
                reservation=held.get('reservation'),
                before_commit=lambda: self._admit(binding, self._identity[3], self._identity[4], self._identity[5]))
            if result.get('state') != 'cancelled' or result.get('releasable') is not True:
                raise InvalidCell('Native cancellation is not confirmed')
            held['cancellation'] = result
            self._set('native_cancelled', native_cancellation=result, approved=False,
                error='Agent preparation cancelled. The saved Work can be prepared again after closing this review.')
        except Exception:
            self._set('uncertain', error='Native cancellation needs reconciliation. The saved Work and session evidence remain.')
            raise

    def _read_saved_native_artifact(self, binding, root, scope, work, request_id, result, receipt):
        from .native_workshop_execution import native_saved_artifacts, PROVIDER
        from .cell_model_execution import read_model_execution_receipt
        with self.server.mutation_lock:
            self._admit(binding, root, scope, work, work_action='read')
            snapshot, registry = self.server.universal_store.snapshot(), self.server.universal_registry
            selected = read_model_execution_receipt(snapshot, registry.baboom_model_execution_protocol,
                registry.adapter_protocol, receipt)
            if selected.provider_root != PROVIDER:
                return None
            rows = native_saved_artifacts(snapshot, registry, work, receipt_root=receipt)
            matches = [row for row in rows if row['receipt'] == receipt]
            if not matches:
                return None
            if len(matches) != 1 or matches[0]['result'] != result:
                raise InvalidCell('The selected native artifact does not match its saved receipt')
            artifact = matches[0]
            content = self.server.project_work_execution_broker.read_artifact(artifact['name'], artifact['digest'])
            self._admit(binding, root, scope, work, work_action='read')
            return {'ok':True, 'root':root, 'scope':scope, 'owner':binding.subject_root,
                'view':binding.view_root, 'work':work, 'request_id':request_id,
                'artifact':artifact, 'artifact_text':content, 'state':'saved_artifact', 'mode':'agent'}

    def _publish_native(self, binding):
        from .existing_workshop_conversation import send_browser_workshop
        artifact = self._status.get('artifact')
        if not artifact or self._status['state'] not in ('settled', 'publication_uncertain', 'published'):
            raise InvalidCell('A saved native artifact is required before publication')
        checked = self._read_saved_native_artifact(binding, self._identity[3], self._identity[4],
            self._identity[5], self._identity[6], artifact['result'], artifact['receipt'])
        if checked is None:
            raise InvalidCell('The native artifact receipt is unavailable')
        message = ('Workshop saved a draft artifact: ' + artifact['name'] + '\n\n'
                   + artifact['summary'] + '\n\nReview the patch before applying it. Acceptance is tracked on the Work node.')
        try:
            with self.server.mutation_lock:
                self._admit(binding, self._identity[3], self._identity[4], self._identity[5])
                publication = send_browser_workshop(self.server, binding, {
                    'root':self._identity[3], 'scope':self._identity[4], 'category':'note', 'text':message,
                    'refs':[], 'evidence':[], 'recipients':[binding.subject_root], 'reply_to':None,
                    'idempotency_key':self._identity[6] + ':native-result', 'created_at':None})
            self._set('published', publication=publication)
        except Exception:
            self._set('publication_uncertain', error='The saved artifact announcement needs reconciliation; the agent will not rerun.')
            raise

    def _admit(self, binding, root, scope, work=None, *, work_action="execute"):
        from .universal_application import (_view_session_for_context,
            _session_canvas_roots, _cached_authority_snapshot, _require_application_authorization)
        snapshot, _ = _admit(self.server, binding, root, scope)
        registry = self.server.universal_registry
        identity = registry.authorization.broker.resolve(binding.context)
        if binding.subject_root != registry.authorization.subject_root or identity.subject_root != binding.subject_root:
            raise AuthorizationDenied("Native Workshop execution requires the authenticated founder")
        if work is not None:
            from .cell_protocols import read_relation
            registered = {member.participant_id for member in read_relation(snapshot,
                registry.governed_work_registry_root, budget=100_000)
                if member.role_id == registry.roles["member"]}
            if work not in registered:
                raise InvalidCell("Choose a registered Workshop Work node")
            view, context = _view_session_for_context(registry, binding.context)
            visible, _, _, _ = _session_canvas_roots(snapshot, registry, view, include_trail=True,
                authority_snapshot=_cached_authority_snapshot(snapshot, registry.authorization))
            if work not in visible:
                raise AuthorizationDenied("Workshop Work is no longer on this canvas")
            _require_application_authorization(snapshot, registry, work_action, work,
                authentication_context=context)
        if self.server.universal_store.revision != snapshot.revision:
            raise AuthorizationDenied("Workshop changed during admission; refresh")
        return snapshot.revision

    def _binding(self, binding, root, scope):
        return (self.server.universal_registry.application_root, binding.subject_root,
            binding.view_root, root, scope)

    def status(self, binding, *, root, scope, work=None):
        from .existing_workshop_project_execution import _stable_admission, project_saved_artifacts
        with _stable_admission(self.server, binding.context):
            result = self._status_for_binding(binding, root=root, scope=scope)
            selected = work or (self._identity[5] if self._identity is not None else None)
            result["artifacts"] = []
            result['existing_artifacts'] = []
            result["failures"] = []
            result["local_deliveries"] = []
            result["artifacts_work"] = selected
            result['selected_work_mode'] = None
            if selected is not None:
                self._admit(binding, root, scope, selected, work_action="read")
                from . import universal_application as app
                from .cell_value_graph import read_value_graph
                snapshot = self.server.universal_store.snapshot()
                try:
                    input_root = app._governed_work_interface_target(snapshot,
                        self.server.universal_registry, selected, 'inputs')
                    selected_inputs = read_value_graph(snapshot,
                        self.server.universal_registry.value_graph_protocol, input_root)
                except InvalidCell:
                    selected_inputs = None
                if type(selected_inputs) is dict:
                    if selected_inputs.get('runtime') == 'claude':
                        result['selected_work_mode'] = 'agent'
                    elif {'model','files','artifact_name','data_class'} == set(selected_inputs):
                        result['selected_work_mode'] = 'project'
                result["artifacts"] = project_saved_artifacts(self.server.universal_store.snapshot(),
                    self.server.universal_registry, selected)
                from .native_workshop_execution import native_saved_artifacts
                result['artifacts'] += [{**row, 'mode':'agent'} for row in native_saved_artifacts(
                    self.server.universal_store.snapshot(), self.server.universal_registry, selected)]
                from .native_workshop_execution import existing_session_saved_artifacts
                result['existing_artifacts'] = existing_session_saved_artifacts(
                    self.server, context=binding.context, work_root=selected)
                result["failures"] = _project_failures(self.server.universal_store.snapshot(),
                    self.server.universal_registry, selected)
                from .workshop_project_resolution import project_local_deliveries
                result["local_deliveries"] = project_local_deliveries(self.server.universal_store,
                    self.server.universal_registry, selected)
                if result["local_deliveries"]:
                    from .existing_workshop_project_revision import pending_project_revisions
                    pending = pending_project_revisions(self.server.universal_store.snapshot(),
                        self.server.universal_registry, selected)
                    if len(pending) > 1:
                        raise InvalidCell("Several project revision drafts require resolution")
                    if pending:
                        result["revision_pending"] = pending[0]["revision_id"]
            self._admit(binding, root, scope)
            return result

    def _status_for_binding(self, binding, *, root, scope):
        with self.server.mutation_lock:
            self._admit(binding, root, scope)
            header = {"ok":True, "root":root, "scope":scope,
                "owner":binding.subject_root, "view":binding.view_root}
            if self._identity is not None and self._identity[:5] != self._binding(binding, root, scope):
                return {**header, "state":"unavailable"}
            if self._identity is not None:
                self._admit(binding, root, scope, self._identity[5])
            available = []
            if self._identity is None:
                from .cell_protocols import read_relation
                from .universal_application import _view_session_for_context, _session_canvas_roots
                registry = self.server.universal_registry
                snapshot = self.server.universal_store.snapshot()
                view, _ = _view_session_for_context(registry, binding.context)
                visible, _, _ = _session_canvas_roots(snapshot, registry, view)
                available = [member.participant_id for member in read_relation(snapshot,
                    registry.governed_work_registry_root, budget=100_000)
                    if member.role_id == registry.roles["member"] and member.participant_id in visible]
                if self.server.universal_store.revision != snapshot.revision:
                    raise AuthorizationDenied("Workshop changed during Work selection")
            expiry = self._prepared.get('expires_at') if (self._project or self._native is not None) and isinstance(self._prepared, dict) else None
            review_expiry = {}
            if type(expiry) in (int, float) and 0 < expiry < 253402300800:
                import time
                review_expiry = {'review_expires_at':expiry,
                    'review_expired':time.time() >= expiry}
            return {**header, "available_work": available, **self._status, **review_expiry}

    @staticmethod
    def _released(identity):
        return {"ok":True, "root":identity[3], "scope":identity[4],
            "owner":identity[1], "view":identity[2], "work":identity[5],
            "request_id":identity[6], "state":"released", "released":True}

    def _set(self, state, **fields):
        self._status = {**self._status, **fields, "state": state}

    def invalidate_work_approval(self, work):
        """Clear this host's held approval after the same Work's draft changes.

        Browser and native configuration routes use this one approval owner.
        The caller holds mutation_lock across configuration and invalidation;
        the reentrant lock also protects direct use of this method.
        """
        with self.server.mutation_lock:
            if self._status.get("work") == work and self._status.get("approved"):
                self._set(self._status["state"], approved=False)
                return True
            return False

    def _admit_project_recovery(self, binding, root, scope, work, result_root, receipt_root):
        from .existing_workshop_project_execution import _stable_admission
        from . import universal_application as app
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work)
            store, registry = self.server.universal_store, self.server.universal_registry
            snapshot = store.snapshot()
            failures = _project_failures(snapshot, registry, work,
                                        result_root=result_root, receipt_root=receipt_root)
            if len(failures) != 1:
                raise InvalidCell("Select one exact failed project result to recover")
            failure = failures[0]
            machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
                registry.standard_library.state_machine_protocol, work)
            if (app._text(snapshot, machine.current_state_root).casefold() != "claimed"
                    or app._governed_work_claimant_session(snapshot, registry, work) != failure["worker"]):
                raise AuthorizationDenied("The failed worker no longer owns this Work claim")
            if (not self.server._model_execution_idle.is_set()
                    or self.server._project_work_pending is not None):
                raise AuthorizationDenied("Project execution must settle before recovery")
            if self.server._machine_agent_session_has_live_capability(failure["worker"]):
                raise AuthorizationDenied("The failed worker still has a live capability")
            _require_latest_settled_failure(snapshot, registry, work, failure, store=store)
            self._admit(binding, root, scope, work)
            return failure, snapshot.revision

    def _admit_local_project_recovery(self, binding, root, scope, work, result_root, resolution_root,
            *, allow_revision=None):
        from . import universal_application as app
        from .cell_protocols import read_relation
        from .existing_workshop_project_execution import _stable_admission
        from .workshop_project_resolution import read_project_delivery_resolution, require_latest_project_delivery
        from .existing_workshop_project_revision import pending_project_revisions
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="edit")
            store, registry = self.server.universal_store, self.server.universal_registry
            if type(result_root) is not str or not result_root.endswith(":project-result"):
                raise InvalidCell("Select an exact abandoned local project result")
            grant_root = result_root[:-len(":project-result")]
            decision = read_project_delivery_resolution(store.snapshot(), registry, grant_root, store=store)
            if (decision is None or decision["resolution"] != resolution_root
                    or decision["result"] != result_root or decision["work"] != work
                    or decision["actor"] != binding.subject_root or decision["view"] != binding.view_root
                    or decision["scope"] != scope):
                raise AuthorizationDenied("Local project recovery selection changed")
            if self.server.universal_checkpoint_guard is not None:
                self.server.universal_checkpoint_guard.require_healthy()
            if (self._cancel.is_set() or self.server._model_execution_closing
                    or self.server._model_execution_active or not self.server._model_execution_idle.is_set()
                    or self.server._project_work_pending is not None):
                raise AuthorizationDenied("Project execution must settle before recovery")
            snapshot = store.snapshot()
            pending = pending_project_revisions(snapshot, registry, work)
            if pending and (len(pending) != 1 or pending[0]["revision_id"] != allow_revision):
                raise InvalidCell("Resolve the saved project revision before preparing this Work")
            machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
                registry.standard_library.state_machine_protocol, work)
            rows = read_relation(snapshot, machine.history_root, budget=2048, retain_projection=False)
            if len(rows) > 256:
                raise InvalidCell("Local project recovery claim history exceeds its bound")
            history = app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id)
            claimant = app._governed_work_claimant_session(snapshot, registry, work)
            if (app._text(snapshot, machine.current_state_root).casefold() != "claimed"
                    or type(claimant) is not str or not claimant or not history
                    or app._text(snapshot, history[-1].event_root).casefold() != "claim"
                    or claimant not in history[-1].context_roots):
                raise AuthorizationDenied("Local project recovery requires its exact current Work claim")
            if self.server._machine_agent_session_has_live_capability(claimant):
                raise AuthorizationDenied("The current Work claimant still has a live capability")
            require_latest_project_delivery(store, registry, work, grant_root)
            self._admit(binding, root, scope, work, work_action="edit")
            return {"work":work, "result":result_root, "resolution":resolution_root,
                "grant":grant_root, "worker":claimant, "claim_root":history[-1].root_id,
                "original_worker":decision["worker"], "input_digest":decision["input_digest"],
                "provider_outcome":"unknown", "local_resolution":decision}, snapshot.revision

    def _release_local_project(self, binding, body, identity):
        """Acknowledge only the exact durable local decision, including restart."""
        from .existing_workshop_project_execution import _stable_admission
        from .workshop_project_resolution import read_project_delivery_resolution
        root, scope, work = body["root"], body["scope"], body["work"]
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="edit")
            from .existing_workshop_project_revision import pending_project_revisions
            if (self._status.get("revision_pending") or pending_project_revisions(
                    self.server.universal_store.snapshot(), self.server.universal_registry, work)):
                raise InvalidCell("Resolve the saved project revision before releasing this Work")
            store, registry = self.server.universal_store, self.server.universal_registry
            result_root = body["result"]
            if not result_root.endswith(":project-result"):
                raise InvalidCell("Select the exact local delivery decision before release")
            decision = read_project_delivery_resolution(store.snapshot(), registry,
                result_root[:-len(":project-result")], store=store)
            if (decision is None or decision["result"] != result_root
                    or decision["resolution"] != body["resolution"] or decision["work"] != work
                    or decision["actor"] != binding.subject_root or decision["view"] != binding.view_root
                    or decision["scope"] != scope or decision["provider_outcome"] != "unknown"):
                raise AuthorizationDenied("Local release selection differs from its admitted decision")
            if (self._cancel.is_set() or self.server._model_execution_closing
                    or self.server._model_execution_active or not self.server._model_execution_idle.is_set()
                    or self.server._project_work_pending is not None):
                raise AuthorizationDenied("Local release must wait for the physical execution to drain")
            retired = self._retired.get(body["request_id"])
            if retired is not None and retired != identity:
                raise AuthorizationDenied("Local release belongs to another operation")
            if self._identity is not None:
                selected = self._status.get("local_resolution") or {}
                if (self._identity != identity or self._status.get("state") != "local_delivery_abandoned"
                        or selected.get("result") != result_root
                        or selected.get("resolution") != body["resolution"] or len(self._retired) >= 128):
                    raise AuthorizationDenied("Resolve the current Workshop operation before local release")
                self._retired[body["request_id"]] = identity
                self._retired_local.add(body["request_id"])
                self._identity = self._browser_binding = None
                self._prepared = self._grant = self._settled = None
                self._review_recovery = self._review_recovery_pending = None
                self._project = False
                self._status = {"state":"idle"}
            elif self._status.get("state") != "idle":
                raise AuthorizationDenied("Local release requires an idle native owner")
            # An idle fresh owner has no historical operation to retire. This
            # acknowledgement comes from the exact durable decision instead.
            return {**self._released(identity), "result":result_root, "resolution":body["resolution"]}

    def _recover_project(self, binding, body, identity, *, local=False):
        import hashlib
        source = (body["result"], body["resolution"] if local else body["receipt"])
        recovery_kind = "local_delivery" if local else "failed_project"
        if self._identity == identity:
            if self._recovery_source != source or self._status.get("recovery_kind", "failed_project") != recovery_kind:
                raise InvalidCell("Recovery identity is already bound to another project result")
            return self.status(binding, root=body["root"], scope=body["scope"])
        selected_local = self._status.get("local_resolution") or {}
        retained_source = ((self._status.get("state") == "local_delivery_abandoned"
            and (selected_local.get("result"), selected_local.get("resolution")) == source) if local else
            (self._settled is not None and self._settled.get("outcome") == "failed"
             and (self._settled.get("result"), self._settled.get("receipt")) == source))
        if self._identity is not None and (
                self._identity[:6] != identity[:6] or not self._project or not retained_source):
            raise InvalidCell("Resolve the current Workshop operation before recovering another")
        if len(self._retired) >= 128:
            raise InvalidCell("Workshop recovery exceeds this owner's operation limit")
        root, scope, work = body["root"], body["scope"], body["work"]
        admit = self._admit_local_project_recovery if local else self._admit_project_recovery
        failure, _revision = admit(binding, root, scope, work, *source)
        if self._identity is not None:
            self._retired[self._identity[6]] = self._identity
            if local:
                self._retired_local.add(self._identity[6])
        self._identity, self._browser_binding = identity, binding
        self._recovery_source, self._project = source, True
        self._review_recovery = None
        self._review_recovery_pending = None
        self._client = self._worker = self._prepared = self._grant = self._settled = None
        external_session_id = "workshop-" + body["request_id"]
        self._status = {"state":"attaching", "mode":"project", "approved":False,
                        "recovery_kind":recovery_kind,
                        "request_id":body["request_id"], "work":work, "recovery":failure,
                        "recovery_phase":"device_custody", "recovery_error":None,
                        "recovery_request":{"request_id":body["request_id"], "work":work,
                            "result":source[0], ("resolution" if local else "receipt"):source[1], "external_session_fingerprint":
                            hashlib.sha256(external_session_id.encode("utf-8")).hexdigest()}}
        try:
            def retain(client):
                self._client = client
                self._set("attaching", recovery_phase="session_enrollment")
            prepare_workshop_execution_client(self.server, state_dir=self.state_dir,
                descriptor_path=self.descriptor_path, key_provider=self.key_provider,
                external_session_id=external_session_id,
                authentication_context=binding.context, cancellation_event=self._cancel,
                retain_client=retain)
            self._set("attaching", recovery_phase="worker_binding", worker=self._client.agent_session_root)
            if self._client.agent_session_root == failure["worker"]:
                raise AuthorizationDenied("Recovery requires a fresh worker identity")
            self._worker = ExistingWorkshopModelWorker(self._client)
            self._set("attaching", recovery_phase="workshop_join")
            self._client.request("POST", "/api/universal/workshop", {
                "category":"note", "text":("Preparing a fresh review after abandoned local patch delivery; the prior provider outcome remains unknown. No model call."
                    if local else "Preparing explicit recovery of the selected failed project Work; no model call."),
                "refs":[work], "evidence":[], "recipients":[binding.subject_root], "reply_to":None,
                "idempotency_key":body["request_id"], "created_at":None})
            self._set("attaching", recovery_phase="claim_admission")
            checked, revision = admit(binding, root, scope, work, *source)
            if checked != failure:
                raise AuthorizationDenied("Local project evidence changed during recovery" if local
                    else "Failed project evidence changed during recovery")
            self._set("recovering", recovery_phase="claim_recovery", worker=self._client.agent_session_root)
            recovered = self._client.recover_work_claim(work,
                ("Explicit fresh review after abandoned local delivery; provider unknown. Resolution " + source[1]
                 if local else "Explicit retry of settled failed project receipt " + failure["receipt"]),
                projection="index", expected_claimant=failure["worker"], expected_revision=revision)
            if (recovered.get("recovered") is not True
                    or recovered.get("previous_claimant_session") != failure["worker"]
                    or recovered.get("claimant_session") != self._client.agent_session_root
                    or not recovered.get("release_history_root") or not recovered.get("claim_history_root")):
                raise InvalidCell("Work recovery returned another claim")
            self._set("preparing", recovery_phase="recovery_notice", recovery_claim=recovered["claim_history_root"])
            self._client.request("POST", "/api/universal/workshop", {
                "category":"note", "text":("Recovered the same Work after local delivery was abandoned. The prior provider outcome remains unknown. Resolution: "
                    + source[1] + ". No model has been rerun; the new input requires review and approval." if local else
                    "Recovered the same Work after failed project execution ("
                    + failure["error"] + "). Prior receipt: " + failure["receipt"]
                    + ". No model has been rerun; the next input requires review and approval."),
                "refs":[work], "evidence":[source[1]], "recipients":[binding.subject_root],
                "reply_to":None, "idempotency_key":body["request_id"] + ":recovery", "created_at":None})
            self._set("preparing", recovery_phase="work_plan")
            self._client.request("POST", "/api/universal/work-plan", {"root":work})
            self._set("preparing", recovery_phase="project_prepare")
            self._prepared = self._client.request("POST", "/api/universal/project-work-prepare", {"root":work})
            p = self._prepared
            if p.get("work") != work or p.get("worker") != self._client.agent_session_root:
                raise InvalidCell("Recovered project preparation returned another Work or worker")
            self._set("awaiting_approval", recovery_phase="approval_ready", approved=False, delegation=p["delegation"],
                input_digest=p["input_digest"], model=p["model"], review_text=p["review_text"],
                artifact_name=p["artifact_name"])
        except Exception as error:
            diagnostic = _recovery_error_details(error)
            detail = diagnostic["message"] or diagnostic["code"]
            self._set("uncertain", recovery_error=diagnostic,
                error="Recovery paused at " + self._status["recovery_phase"] + ": " + detail
                    + ". Read the retained claim and result; do not recover or execute again implicitly.")
            raise
        return self.status(binding, root=root, scope=scope)

    def _admit_review_recovery(self, binding, root, scope, work, source, *, inactive_claimant=True):
        """Read historical provenance and actual current claim independently."""
        from . import universal_application as app
        from .existing_workshop_project_execution import _stable_admission, project_saved_artifacts
        from .cell_connector_execution import read_connector_execution_receipt
        from .cell_value_graph import read_value_graph

        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="edit")
            store, registry = self.server.universal_store, self.server.universal_registry
            snapshot = store.snapshot()
            artifacts = project_saved_artifacts(snapshot, registry, work, receipt_root=source[1])
            if len(artifacts) != 1 or artifacts[0]["result"] != source[0]:
                raise InvalidCell("Review recovery requires one exact successful saved artifact")
            receipt = read_connector_execution_receipt(snapshot,
                registry.baboom_connector_execution_protocol, registry.adapter_protocol, source[1])
            machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
                registry.standard_library.state_machine_protocol, work)
            claimant = app._governed_work_claimant_session(snapshot, registry, work)
            if (app._text(snapshot, machine.current_state_root).casefold() != "claimed"
                    or type(claimant) is not str or not claimant):
                raise AuthorizationDenied("Review recovery requires the Work's current claim")
            from .cell_protocols import read_relation
            history_rows = read_relation(snapshot, machine.history_root, budget=2048)
            if len(history_rows) > 256:
                raise InvalidCell("Review recovery exceeds its bounded claim history")
            history = app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id)
            if (not history or app._text(snapshot, history[-1].event_root).casefold() != "claim"
                    or claimant not in history[-1].context_roots):
                raise InvalidCell("Review recovery current claim history is not exact")
            if (not self.server._model_execution_idle.is_set()
                    or self.server._project_work_pending is not None or self._cancel.is_set()):
                raise AuthorizationDenied("Project execution must settle before recovery")
            if inactive_claimant and self.server._machine_agent_session_has_live_capability(claimant):
                raise AuthorizationDenied("The current Work claimant still has a live capability")
            _require_latest_settled_failure(snapshot, registry, work,
                {"receipt":source[1], "created_at":receipt.created_at}, store=store)
            value = read_value_graph(snapshot, registry.value_graph_protocol, source[0], max_depth=4)
            self._admit(binding, root, scope, work, work_action="edit")
            return {"artifact":artifacts[0], "claimant":claimant, "claim_root":history[-1].root_id,
                "settled":{**value, "result":source[0], "receipt":source[1]}}, snapshot.revision

    def _complete_review_recovery(self, binding, *, expected_claim=None):
        """Confirm a retained recovery by reads only, including lost responses."""
        pending = self._review_recovery_pending
        if (pending is None or self._identity != pending["identity"] or self._client is None
                or not self._client.agent_session_root):
            raise InvalidCell("Review recovery has no retained attached worker; no attachment will be repeated")
        root, scope, work = self._identity[3:6]
        worker, source, prior = self._client.agent_session_root, pending["source"], pending["prior"]
        checked, _ = self._admit_review_recovery(binding, root, scope, work, source, inactive_claimant=False)
        if (worker == prior["claimant"] or checked["claimant"] != worker
                or checked["claim_root"] == prior["claim_root"]
                or expected_claim is not None and checked["claim_root"] != expected_claim
                or checked["artifact"] != prior["artifact"] or checked["settled"] != prior["settled"]):
            raise AuthorizationDenied("Recovered review claim has not been confirmed; no claim will be repeated")
        self._review_recovery = {"identity":self._identity, "source":source, "worker":worker,
            "claim":checked["claim_root"], "previous_claimant":prior["claimant"]}
        self._worker = ExistingWorkshopModelWorker(self._client)
        self._prepared = {"work":work, "worker":worker}
        self._settled = checked["settled"]
        artifact = checked["artifact"]
        # This is the existing review-ready state, not a new publication or execution.
        self._set("published", review_recovered=True, recovery_phase="review_ready",
            recovery_claim=checked["claim_root"], receipt=source[1],
            artifact={**artifact, "outcome":"succeeded"}, result_text=artifact["summary"],
            recovery_error=None, error=None)

    def _recover_review(self, binding, body, identity):
        """Attach once to resume review; never prepare a delegation or execute."""
        source = (body["result"], body["receipt"])
        if self._identity == identity:
            if self._recovery_source != source or not self._status.get("review_recovery"):
                raise AuthorizationDenied("Review recovery identity belongs to another source")
            return self.status(binding, root=body["root"], scope=body["scope"])
        if self._identity is not None:
            raise InvalidCell("Resolve the current Workshop operation before recovering a saved review")
        if len(self._retired) >= 128:
            raise InvalidCell("Workshop recovery exceeds this owner's operation limit")
        root, scope, work = body["root"], body["scope"], body["work"]
        prior, _ = self._admit_review_recovery(binding, root, scope, work, source)
        self._identity, self._browser_binding = identity, binding
        self._recovery_source, self._project = source, True
        self._review_recovery = None
        self._review_recovery_pending = {"identity":identity, "source":source, "prior":prior}
        self._client = self._worker = self._prepared = self._grant = self._settled = None
        self._status = {"state":"attaching", "mode":"project", "approved":False,
            "request_id":body["request_id"], "work":work, "review_recovery":True,
            "recovery_phase":"device_custody", "recovery_source":{"result":source[0], "receipt":source[1]},
            "previous_claimant":prior["claimant"]}
        try:
            def retain(client):
                self._client = client
                self._set("attaching", recovery_phase="session_enrollment")
            prepare_workshop_execution_client(self.server, state_dir=self.state_dir,
                descriptor_path=self.descriptor_path, key_provider=self.key_provider,
                external_session_id="workshop-" + body["request_id"],
                authentication_context=binding.context, cancellation_event=self._cancel,
                retain_client=retain)
            worker = self._client.agent_session_root
            if not worker or worker == prior["claimant"]:
                raise AuthorizationDenied("Recovery requires a fresh worker identity")
            self._worker = ExistingWorkshopModelWorker(self._client)
            self._set("attaching", worker=worker, recovery_phase="workshop_join")
            self._client.request("POST", "/api/universal/workshop", {
                "category":"note", "text":"Resuming review of the selected saved Work artifact; no model call.",
                "refs":[work], "evidence":[], "recipients":[binding.subject_root], "reply_to":None,
                "idempotency_key":body["request_id"], "created_at":None})
            checked, revision = self._admit_review_recovery(binding, root, scope, work, source)
            if checked != prior:
                raise AuthorizationDenied("Saved review or current Work claimant changed during recovery")
            self._set("recovering", recovery_phase="claim_recovery")
            recovered = self._client.recover_work_claim(work,
                "Explicit review recovery of saved project receipt " + source[1], projection="index",
                expected_claimant=prior["claimant"], expected_revision=revision)
            if (recovered.get("recovered") is not True
                    or recovered.get("previous_claimant_session") != prior["claimant"]
                    or recovered.get("claimant_session") != worker
                    or type(recovered.get("claim_history_root")) is not str
                    or type(recovered.get("release_history_root")) is not str):
                raise InvalidCell("Work recovery returned another claim")
            if recovered["release_history_root"] not in self.server.universal_store.snapshot().cells:
                raise AuthorizationDenied("Recovered review claim did not verify")
            self._complete_review_recovery(binding, expected_claim=recovered["claim_history_root"])
        except Exception as error:
            diagnostic = _recovery_error_details(error)
            self._set("uncertain", recovery_error=diagnostic,
                error="Saved review recovery needs reconciliation. Read the retained claim; no model was prepared or run.")
            raise
        return self.status(binding, root=root, scope=scope)

    def _reconcile(self, binding):
        """Recover graph evidence only; never issue a grant or call a provider."""
        if self._status.get("review_recovery") and self._review_recovery_pending is not None:
            return self._complete_review_recovery(binding)
        if self._project:
            return self._reconcile_project(binding)
        from . import universal_application as app
        from .cell_protocols import read_relation
        from .cell_model_execution import read_model_delegation, read_model_execution_receipt
        from .existing_workshop_model_result import publish_verified_model_result
        p, grant = self._prepared, self._grant
        if self._status["state"] != "uncertain" or p is None or grant is None:
            raise InvalidCell("No retained execution is available for reconciliation")
        with self.server.mutation_lock:
            self._admit(binding, self._identity[3], self._identity[4], p.work_root)
            if not self.server._model_execution_idle.is_set():
                raise InvalidCell("The physical execution is still settling")
            store, registry = self.server.universal_store, self.server.universal_registry
            snapshot = store.snapshot()
            protocol = registry.baboom_model_execution_protocol
            delegation = read_model_delegation(snapshot, protocol, registry.adapter_protocol, p.delegation_root)
            if (delegation.session_root != p.worker_root or delegation.work_root != p.work_root
                    or delegation.input_digest != p.input_digest or delegation.model != p.model
                    or delegation.cognition_request_root != p.cognition_root
                    or grant.get("delegation") != p.delegation_root):
                raise InvalidCell("Retained execution differs from graph evidence")
            members = read_relation(snapshot, protocol.registry("receipt"), budget=4096)
            if len(members) > 256:
                raise InvalidCell("Receipt recovery exceeds its bounded lookup")
            receipts = []
            for member in members:
                if member.role_id != protocol.role("registry-member"):
                    continue
                receipt = read_model_execution_receipt(snapshot, protocol, registry.adapter_protocol, member.participant_id)
                if receipt.delegation_root == p.delegation_root and receipt.grant_root == grant.get("grant"):
                    receipts.append(receipt)
            if len(receipts) != 1:
                raise InvalidCell("No unique settled receipt exists for this exact execution")
            receipt, proposal_root = receipts[0], None
            if receipt.outcome == "succeeded":
                cp = registry.agent_body.cognition_protocol
                members = read_relation(snapshot, cp.registry("proposal"), budget=4096)
                if len(members) > 256:
                    raise InvalidCell("Proposal recovery exceeds its bounded lookup")
                proposals = []
                for member in members:
                    if member.role_id != cp.role("proposal-member"):
                        continue
                    proposal = app.read_proposal(store, registry.assembly_protocol,
                        registry.standard_library.catalog_root, cp, registry.agent_body.cognition_definitions,
                        registry.adapter_protocol, registry.baboom_cognition_adapter_catalog_root,
                        registry.agent_body.protocol, registry.authorization.protocol, member.participant_id,
                        model_binding_verifier=app._baboom_cognition_model_binding_verifier(registry))
                    if proposal.request_root == p.cognition_root:
                        proposals.append(member.participant_id)
                if len(proposals) != 1:
                    raise InvalidCell("No unique proposal exists for this execution")
                proposal_root = proposals[0]
            checked = publish_verified_model_result(store, registry, agent_session_root=p.worker_root,
                receipt_root=receipt.root_id, proposal_root=proposal_root, recipient_root=binding.subject_root,
                reply_to_root=None, authentication_context=binding.context, inspect_only=True)
            if store.revision != snapshot.revision:
                raise AuthorizationDenied("Recovery evidence changed")
            self._settled = SettledModelWork(p, checked["receipt"], checked["proposal"],
                checked["reconciled"], checked["review_text"])
            self._set("settled", receipt=checked["receipt"], proposal=checked["proposal"],
                reconciled=checked["reconciled"], result_text=checked["review_text"], error=None)

    def perform(self, binding, body):
        fields = {"action", "root", "scope", "work", "request_id", "data_class"}
        structured_fields = set()
        if type(body) is dict and body.get("action") == "revise_project":
            fields.add("draft")
            structured_fields.add("draft")
            if "result" in body or "resolution" in body:
                fields.update(("result", "resolution"))
        if type(body) is dict and body.get("action") == "revise_requirements":
            fields.update(("revision_id", "expected_revision", "expected_target", "expected_digest", "gate"))
            structured_fields.update(("gate", "expected_revision"))
        if type(body) is dict and body.get("action") == "configure_work":
            fields.update(("revision_id", "expected_revision", "purpose", "fields"))
            structured_fields.update(("fields", "expected_revision"))
        if type(body) is dict and body.get("action") == "discard_work_configuration":
            fields.update(("revision_id", "expected_revision"))
            structured_fields.add("expected_revision")
        if type(body) is dict and body.get("action") in ("approve_project", "approve_native"):
            fields.add("input_digest")
        if type(body) is dict and body.get("action") == "refresh_project_review":
            fields.update(("delegation", "input_digest"))
        if type(body) is dict and body.get("action") == "abandon_project":
            fields.update(("grant", "result", "input_digest"))
        if type(body) is dict and body.get("action") in ("recover_project", "recover_review"):
            fields.update(("result", "receipt"))
        if type(body) is dict and (body.get("action") == "recover_local_project"
                or body.get("action") == "release" and ("result" in body or "resolution" in body)):
            fields.update(("result", "resolution"))
        if type(body) is dict and body.get("action") == "read_artifact" and ("result" in body or "receipt" in body):
            fields.update(("result", "receipt"))
        if type(body) is dict and body.get('action') == 'read_publication':
            fields.add('publication')
        if type(body) is not dict or set(body) != fields or any(
                type(body[key]) is not str or not body[key] or len(body[key]) > 4096 for key in fields - structured_fields):
            raise InvalidCell("Native Workshop action fields are invalid")
        if "draft" in structured_fields and (type(body["draft"]) is not dict or set(body["draft"]) != {
                "revision_id", "base_digest", "inputs", "requirements"}):
            raise InvalidCell("Native Workshop revision draft is invalid")
        if "gate" in structured_fields and type(body["gate"]) is not dict:
            raise InvalidCell("Native Workshop gate correction is invalid")
        if "fields" in structured_fields and type(body["fields"]) is not dict:
            raise InvalidCell("Native Workshop configuration is invalid")
        action, root, scope, work, request_id = (body[key] for key in
            ("action", "root", "scope", "work", "request_id"))
        if (action not in ("prepare", "prepare_project", "prepare_native", "approve_native", "stop_native", "recover_project", "recover_local_project", "recover_review", "refresh_project_review", "approve_project", "abandon_project", "execute", "publish", "release", "reconcile", "read_artifact", "read_publication", "read_project", "revise_project", "read_requirements", "revise_requirements", "read_work_configuration", "configure_work", "discard_work_configuration") or len(request_id) > 119
                or body["data_class"] != "public-text"):
            raise InvalidCell("Native Workshop action is invalid")
        if not self._action.acquire(blocking=False):
            if action == 'stop_native':
                return self._request_native_stop(binding, root=root, scope=scope,
                    work=work, request_id=request_id)
            raise InvalidCell("Workshop operation is already running; read its status")
        try:
            if self._cancel.is_set():
                raise InvalidCell("Workshop is shutting down")
            if action == 'read_publication':
                from .native_workshop_execution import _admitted, _existing_read
                with _admitted(self.server, binding.context):
                    self._admit(binding, root, scope, work, work_action='read')
                    publication, content, _ = _existing_read(self.server, binding.context,
                        work, body['publication'])
                    self._admit(binding, root, scope, work, work_action='read')
                    return {'ok': True, 'root': root, 'scope': scope,
                        'owner': binding.subject_root, 'view': binding.view_root,
                        'work': work, 'request_id': request_id, 'publication': body['publication'],
                        'artifact_text': content, 'name': publication['artifact_name'],
                        'digest': publication['artifact_digest'], 'bytes': publication['artifact_bytes']}
            if action == "read_artifact" and "receipt" in body:
                native_artifact = self._read_saved_native_artifact(binding, root, scope, work,
                    request_id, body['result'], body['receipt'])
                if native_artifact is not None:
                    return native_artifact
                return self._read_saved_project_artifact(binding, root, scope, work,
                    request_id, body["result"], body["receipt"])
            if action == "read_project":
                return self._read_project_draft(binding, root, scope, work, request_id)
            if action == "read_requirements":
                return self._read_requirements(binding, root, scope, work, request_id)
            if action == "revise_requirements":
                return self._revise_requirements(binding, body)
            if action == "read_work_configuration":
                return self._read_work_configuration(binding, root, scope, work, request_id)
            if action == "configure_work":
                return self._configure_work(binding, body)
            if action == "discard_work_configuration":
                from .existing_workshop_project_revision import discard_work_configuration
                with self.server.mutation_lock, self.server.universal_registry.authorization.broker.live_context(binding.context):
                    self._admit(binding, root, scope, work, work_action="edit")
                    discarded = discard_work_configuration(self.server, binding, scope=scope, work=work,
                        revision_id=body["revision_id"], expected_revision=body["expected_revision"])
                return {"ok":True, "root":root, "scope":scope, "work":work, "request_id":request_id,
                    "owner":binding.subject_root, "view":binding.view_root, "discard":discarded}
            with self.server.mutation_lock:
                self._admit(binding, root, scope, work)
            identity = (*self._binding(binding, root, scope), work, request_id)
            if action == 'refresh_project_review':
                return self._refresh_project_review(binding, body, identity)
            if action == "release" and "resolution" in body:
                return self._release_local_project(binding, body, identity)
            if request_id in self._retired:
                if action == "release" and self._retired[request_id] == identity:
                    if request_id in self._retired_local:
                        raise InvalidCell("Local release requires its exact result and resolution selectors")
                    return self._released(identity)
                raise InvalidCell("This operation was released; it cannot run again")
            if action == "recover_project":
                return self._recover_project(binding, body, identity)
            if action == "recover_local_project":
                return self._recover_project(binding, body, identity, local=True)
            if action == "recover_review":
                return self._recover_review(binding, body, identity)
            if self._identity is not None and identity != self._identity:
                raise InvalidCell("Reconcile the current Workshop operation before starting another")
            if action == 'prepare_native':
                if self._identity is None:
                    self._prepare_native(binding, body, identity)
                return self.status(binding, root=root, scope=scope)
            if action in ('approve_native', 'stop_native') and self._native is None:
                raise InvalidCell('Prepare a native agent task first')
            if self._native is not None:
                if action == 'approve_native':
                    self._approve_native(binding, body['input_digest'])
                elif action == 'execute':
                    self._execute_native(binding)
                elif action == 'stop_native':
                    self._stop_native()
                    if self._status['state'] == 'native_stopped' and self._native.get('assignment'):
                        self._cancel_native_preparation(binding)
                elif action == 'publish':
                    self._publish_native(binding)
                elif action == 'read_artifact':
                    artifact = self._status.get('artifact')
                    if artifact is None:
                        raise InvalidCell('This native operation has no confirmed artifact')
                    checked = self._read_saved_native_artifact(binding, root, scope, work, request_id,
                        artifact['result'], artifact['receipt'])
                    if checked is None:
                        raise InvalidCell('The saved native artifact is unavailable')
                    return {**self.status(binding, root=root, scope=scope), 'artifact_text':checked['artifact_text']}
                elif action == 'release':
                    failed = (self._status['state'] == 'settled'
                        and type(self._native.get('result')) is dict
                        and self._native['result'].get('state') == 'settled'
                        and self._native['result'].get('outcome') == 'failed')
                    if (self._status['state'] not in ('published', 'native_cancelled') and not failed) or len(self._retired) >= 128:
                        raise InvalidCell('Publish the result, confirm failure, or cancel preparation before closing its operation')
                    observed = self._native['process'].status(force_observation=True)
                    if not observed['drained']:
                        raise InvalidCell('The retained agent has not fully stopped')
                    if self._status['state'] == 'native_cancelled':
                        self._cancel_native_preparation(binding)
                    else:
                        from .native_workshop_execution import release_native_turn_custody
                        release_native_turn_custody(self.server, self._native['reservation'],
                            process=self._native['process'])
                    self._native['profile'].cleanup(process_exited=observed['drained'])
                    self._retired[request_id] = identity
                    self._native = None
                    self._identity = self._browser_binding = self._prepared = None
                    self._status = {'state':'idle'}
                    return self._released(identity)
                elif action == 'reconcile':
                    # Read retained state only. Unknown provider effects are not replayed.
                    driver = self._native.get('process')
                    if driver is not None:
                        observed = driver.status(force_observation=True)
                        self._set(self._status['state'], native_drained=observed['drained'])
                else:
                    raise InvalidCell('This agent operation does not admit the requested action')
                return self.status(binding, root=root, scope=scope)
            if action == "abandon_project":
                from .workshop_project_resolution import abandon_project_delivery
                decision = abandon_project_delivery(self, binding, root=root, scope=scope, work=work,
                    grant_root=body["grant"], result_root=body["result"], input_digest=body["input_digest"])
                self._identity, self._browser_binding, self._project = identity, binding, True
                self._set("local_delivery_abandoned", mode="project", work=work, request_id=request_id,
                    approved=False, local_resolution=decision, artifact=None,
                    error="Local patch delivery was abandoned. The provider outcome remains unknown; no request was repeated.")
                return self.status(binding, root=root, scope=scope)
            if action == "revise_project":
                try:
                    self._revise_project(binding, body)
                except (InvalidCell, AuthorizationDenied):
                    revision_id = body["draft"].get("revision_id")
                    if type(revision_id) is not str or re.fullmatch(r"[a-f0-9]{32}", revision_id) is None:
                        raise
                    # A completed refusal can safely unlock the editor only
                    # when this exact draft never entered the graph. A later
                    # status poll by itself cannot establish that fact.
                    with self.server.mutation_lock:
                        result = self.status(binding, root=root, scope=scope)
                        staged = work + ":project-revision:" + revision_id in self.server.universal_store.snapshot().cells
                    return {**result, "revision_rejection":{"revision_id":revision_id,
                        "staged":staged, "confirmed":True},
                        "error":("Revision draft is saved; reconcile it before changing the request."
                            if staged else "Revision was refused before staging. Check the source, free model and criteria, then reload if the Work changed.")}
                return self.status(binding, root=root, scope=scope)
            if action in ("prepare", "prepare_project"):
                if self._identity is not None:
                    return self.status(binding, root=root, scope=scope)
                self._identity = identity
                self._browser_binding = binding
                self._review_recovery = None
                self._review_recovery_pending = None
                self._project = action == "prepare_project"
                self._set("attaching", request_id=request_id, work=work)
                try:
                    def retain(client):
                        self._client = client
                    if self._client is None:
                        prepare_workshop_execution_client(self.server, state_dir=self.state_dir,
                            descriptor_path=self.descriptor_path, key_provider=self.key_provider,
                            external_session_id="workshop-" + request_id,
                            authentication_context=binding.context, cancellation_event=self._cancel,
                            retain_client=retain)
                    self._worker = ExistingWorkshopModelWorker(self._client)
                    # Use the existing admitted message seam to join; publishing
                    # a receipt cannot manufacture Workshop membership.
                    self._client.request("POST", "/api/universal/workshop", {
                        "category":"note", "text":("Preparing the assigned project repair artifact."
                            if self._project else "Preparing the assigned public review."),
                        "refs":[work], "evidence":[], "recipients":[binding.subject_root],
                        "reply_to":None, "idempotency_key":request_id, "created_at":None})
                    with self.server.mutation_lock:
                        revision = self._admit(binding, root, scope, work)
                    self._set("preparing", worker=self._client.agent_session_root)
                    if self._project:
                        self._client.claim_work(work, expected_revision=revision)
                        self._client.request("POST", "/api/universal/work-plan", {"root":work})
                        self._prepared = self._client.request("POST", "/api/universal/project-work-prepare", {"root":work})
                        p = self._prepared
                        if p.get("work") != work or p.get("worker") != self._client.agent_session_root:
                            raise InvalidCell("Project preparation returned another Work or worker")
                        self._set("awaiting_approval", mode="project", approved=False,
                            delegation=p["delegation"], input_digest=p["input_digest"],
                            model=p["model"], review_text=p["review_text"], artifact_name=p["artifact_name"])
                    else:
                        self._prepared = self._worker.prepare_free_review(work, data_class="public-text",
                            expected_revision=revision)
                        p = self._prepared
                        self._set("awaiting_approval", delegation=p.delegation_root,
                            input_digest=p.input_digest, model=p.model, review_text=p.review_text)
                except Exception:
                    self._set("uncertain", error="Preparation did not return a confirmed result. Do not enroll or claim again.")
                    raise
            elif action == "reconcile":
                self._reconcile(binding)
            elif action == "approve_project":
                self._approve_project(binding, body["input_digest"])
            elif action == "read_artifact":
                artifact_text = self._read_project_artifact()
                return {**self.status(binding, root=root, scope=scope), "artifact_text":artifact_text}
            elif action == "release":
                if self._status.get("revision_pending"):
                    raise InvalidCell("Reconcile the staged Work revision before releasing this operation")
                if self._status["state"] == "local_delivery_abandoned":
                    raise InvalidCell("Local release requires its exact result and resolution selectors")
                if self._status["state"] != "published" or len(self._retired) >= 128:
                    raise InvalidCell("Only a published operation can be released within this owner's recovery limit")
                self._retired[request_id] = identity
                self._identity = self._browser_binding = None
                self._prepared = self._grant = self._settled = None
                self._review_recovery = None
                self._review_recovery_pending = None
                self._project = False
                self._status = {"state":"idle"}
                return self._released(identity)
            elif action == "execute":
                if self._project:
                    self._execute_project(binding)
                    return self.status(binding, root=root, scope=scope)
                if self._status["state"] != "awaiting_approval" or self._prepared is None:
                    return self.status(binding, root=root, scope=scope)
                p = self._prepared
                with self.server.mutation_lock:
                    approval = read_browser_workshop_model_approval(self.server, binding,
                        {"root":root, "scope":scope, "work":work,
                            "delegation":p.delegation_root, "input_digest":p.input_digest})
                if not approval["approved"] or approval["expired"]:
                    raise AuthorizationDenied("Review and approve this exact input before execution")
                self._set("executing")
                try:
                    self._grant = self._client.request("POST", "/api/universal/model-delegation-grant",
                        {"delegation":p.delegation_root})
                    self._settled = self._worker.execute_approved_grant(p, self._grant)
                    self._set("settled", receipt=self._settled.receipt_root,
                        proposal=self._settled.proposal_root, reconciled=self._settled.reconciled,
                        result_text=self._settled.review_text)
                except Exception:
                    self._set("uncertain", error="Execution outcome needs reconciliation. No replacement grant will be issued.")
                    raise
            elif action == "publish":
                if self._project:
                    self._publish_project(binding)
                    return self.status(binding, root=root, scope=scope)
                if self._settled is None or self._status["state"] not in ("settled", "publication_uncertain", "published"):
                    raise InvalidCell("Workshop has no settled result to publish")
                if self._status["state"] != "published":
                    try:
                        result = self._worker.publish_result(self._settled,
                            recipient_root=binding.subject_root)
                        self._set("published", publication=result)
                    except Exception:
                        self._set("publication_uncertain", error="Result publication needs reconciliation; retrying publication will not rerun the model.")
                        raise
            return self.status(binding, root=root, scope=scope)
        finally:
            self._action.release()

    def _read_requirements(self, binding, root, scope, work, request_id):
        """Read one Work's exact requirements for the founder's gate editor."""
        from .existing_workshop_project_execution import _stable_admission
        from .existing_workshop_project_revision import read_work_requirements
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="read")
            value = read_work_requirements(self.server, binding, scope=scope, work=work)
            self._admit(binding, root, scope, work, work_action="read")
        return {"ok":True, "root":root, "scope":scope, "work":work, "request_id":request_id,
            "owner":binding.subject_root, "view":binding.view_root, **value}

    def _revise_requirements(self, binding, body):
        """Correct only an OPEN Work's acceptance gate, on the same Work, as the founder."""
        from .existing_workshop_project_revision import revise_work_requirements
        root, scope, work = body["root"], body["scope"], body["work"]
        with self.server.mutation_lock, self.server.universal_registry.authorization.broker.live_context(binding.context):
            self._admit(binding, root, scope, work, work_action="edit")
            result = revise_work_requirements(self.server, binding, root=root, scope=scope, work=work,
                revision_id=body["revision_id"], expected_revision=body["expected_revision"],
                expected_target=body["expected_target"],
                expected_digest=body["expected_digest"], gate=body["gate"],
                workspace_root=self.server.universal_workspace_root,
                before_binding_commit=lambda: self._admit(binding, root, scope, work, work_action="edit"))
            self.invalidate_work_approval(work)
        return {"ok":True, "root":root, "scope":scope, "work":work, "request_id":body["request_id"],
            "owner":binding.subject_root, "view":binding.view_root, "requirements_revision":result}

    def _read_work_configuration(self, binding, root, scope, work, request_id):
        """Read one Work's configurable inputs, requirements and CDE for the founder editor."""
        from .existing_workshop_project_execution import _stable_admission
        from .existing_workshop_project_revision import read_work_configuration
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="read")
            value = read_work_configuration(self.server, binding, scope=scope, work=work)
            self._admit(binding, root, scope, work, work_action="read")
        return {"ok":True, "root":root, "scope":scope, "work":work, "request_id":request_id,
            "owner":binding.subject_root, "view":binding.view_root, **value}

    def _configure_work(self, binding, body):
        """First-bind or revise an OPEN Work's configuration, on the same Work, as the founder."""
        from .existing_workshop_project_revision import configure_work_interfaces
        root, scope, work = body["root"], body["scope"], body["work"]
        with self.server.mutation_lock, self.server.universal_registry.authorization.broker.live_context(binding.context):
            self._admit(binding, root, scope, work, work_action="edit")
            result = configure_work_interfaces(self.server, binding, root=root, scope=scope, work=work,
                revision_id=body["revision_id"], expected_revision=body["expected_revision"],
                purpose=body["purpose"], fields=body["fields"],
                before_binding_commit=lambda: self._admit(binding, root, scope, work, work_action="edit"))
            self.invalidate_work_approval(work)
        return {"ok":True, "root":root, "scope":scope, "work":work, "request_id":body["request_id"],
            "owner":binding.subject_root, "view":binding.view_root, "work_configuration":result}

    def _read_project_draft(self, binding, root, scope, work, request_id):
        """Read the executable input bindings for the existing repair editor."""
        import hashlib
        from . import universal_application as app
        from .cell_value_graph import read_value_graph
        from .existing_workshop_project_execution import (
            _stable_admission, project_material_from_values)
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="read")
            store, registry = self.server.universal_store, self.server.universal_registry
            snapshot = store.snapshot()
            inputs = read_value_graph(snapshot, registry.value_graph_protocol,
                app._governed_work_interface_target(snapshot, registry, work, "inputs"))
            requirements = read_value_graph(snapshot, registry.value_graph_protocol,
                app._governed_work_interface_target(snapshot, registry, work, "requirements"))
            title = app._governed_work_interface(snapshot, registry, work, "title")["value"]
            description = app._governed_work_interface(snapshot, registry, work, "description")["value"]
            _, raw = project_material_from_values(inputs, requirements,
                title=title, description=description)
            current_digest = hashlib.sha256(raw).hexdigest()
            from .existing_workshop_project_revision import pending_project_revisions
            pending = pending_project_revisions(snapshot, registry, work)
            pending_draft = None
            if pending:
                if len(pending) != 1:
                    raise InvalidCell("Several project revision drafts require resolution")
                saved = pending[0]
                if (saved["owner"] != binding.subject_root or saved["view"] != binding.view_root
                        or saved["workshop"] != root or saved["scope"] != scope
                        or saved["base_digest"] != current_digest
                        or "previous_local_resolution" not in saved):
                    raise InvalidCell("The saved revision requires its original admitted review")
                from .workshop_project_resolution import read_project_delivery_resolution
                result_root = saved["previous_result"]
                if not result_root.endswith(":project-result"):
                    raise InvalidCell("The saved revision has an invalid result")
                decision = read_project_delivery_resolution(snapshot, registry,
                    result_root[:-len(":project-result")], store=store)
                if (decision is None or decision["resolution"] != saved["previous_local_resolution"]
                        or decision["result"] != result_root or decision["work"] != work
                        or decision["actor"] != binding.subject_root or decision["view"] != binding.view_root
                        or decision["scope"] != scope):
                    raise AuthorizationDenied("The saved revision belongs to another local delivery")
                revised_inputs = read_value_graph(snapshot, registry.value_graph_protocol, saved["revised_roots"]["inputs"])
                revised_requirements = read_value_graph(snapshot, registry.value_graph_protocol, saved["revised_roots"]["requirements"])
                _, revised_raw = project_material_from_values(revised_inputs, revised_requirements,
                    title=title, description=description)
                if hashlib.sha256(revised_raw).hexdigest() != saved["input_digest"]:
                    raise InvalidCell("The saved revision payload changed")
                pending_draft = {"revision_id":saved["revision_id"], "base_digest":saved["base_digest"],
                    "input_digest":saved["input_digest"], "inputs":revised_inputs,
                    "requirements":revised_requirements, "result":result_root,
                    "resolution":saved["previous_local_resolution"]}
            self._admit(binding, root, scope, work, work_action="read")
            return {"ok":True, "root":root, "scope":scope, "work":work,
                "owner":binding.subject_root, "view":binding.view_root,
                "request_id":request_id, "state":"draft", "mode":"project",
                "draft":{"title":title, "description":description,
                    "inputs":inputs, "requirements":requirements,
                    "input_digest":current_digest,
                    **({"pending_revision":pending_draft} if pending_draft is not None else {}),
                    "revision":snapshot.revision}}

    def _revise_project(self, binding, body):
        if "resolution" in body:
            return self._revise_local_project(binding, body)
        from . import universal_application as app
        from .existing_workshop_project_execution import project_saved_artifacts
        from .existing_workshop_project_revision import revise_project_values
        from .cell_connector_execution import read_connector_execution_receipt, read_connector_delegation

        if (self._identity is None or not self._project or self._settled is None
                or self._status["state"] != "published"):
            raise InvalidCell("Publish and review this Work's current result before revising it")
        root, scope, work = body["root"], body["scope"], body["work"]
        draft = body["draft"]
        with self.server.mutation_lock, self.server.universal_registry.authorization.broker.live_context(binding.context):
            self._admit(binding, root, scope, work, work_action="edit")
            store, registry = self.server.universal_store, self.server.universal_registry
            snapshot = store.snapshot()
            receipt_root = self._settled.get("receipt")
            if type(receipt_root) is not str:
                raise InvalidCell("The current result has no settled receipt")
            receipt = read_connector_execution_receipt(snapshot,
                registry.baboom_connector_execution_protocol, registry.adapter_protocol, receipt_root)
            delegation = read_connector_delegation(snapshot, registry.baboom_connector_execution_protocol,
                registry.adapter_protocol, receipt.delegation_root)
            machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
                registry.standard_library.state_machine_protocol, work)
            worker = self._client.agent_session_root if self._client is not None else None
            recovered_review = self._review_recovery
            retained_review = (recovered_review is not None
                and recovered_review["identity"] == self._identity
                and recovered_review["source"] == (self._settled.get("result"), receipt_root)
                and recovered_review["worker"] == worker
                and recovered_review["claim"] == self._status.get("recovery_claim")
                and self._status.get("review_recovered") is True)
            if retained_review:
                claim_history = app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id)
                if not claim_history or claim_history[-1].root_id != recovered_review["claim"]:
                    raise AuthorizationDenied("The recovered review's exact Work claim changed")
            if (not worker or self._prepared is None or self._prepared.get("worker") != worker
                    or (delegation.session_root != worker and not retained_review) or delegation.work_root != work
                    or app._text(snapshot, machine.current_state_root).casefold() != "claimed"
                    or app._governed_work_claimant_session(snapshot, registry, work) != worker):
                raise AuthorizationDenied("The retained worker no longer owns this Work claim")
            saved = (project_saved_artifacts(snapshot, registry, work, receipt_root=receipt_root)
                if receipt.outcome == "succeeded" else _project_failures(snapshot, registry, work,
                    receipt_root=receipt_root))
            if len(saved) != 1 or saved[0]["result"] != self._settled.get("result"):
                raise InvalidCell("The selected Work result differs from its durable receipt")
            _require_latest_settled_failure(snapshot, registry, work,
                {"receipt":receipt_root, "created_at":receipt.created_at}, store=store)
            pending = self._status.get("revision_pending")
            if pending and pending != draft.get("revision_id"):
                raise InvalidCell("Recover the existing staged revision before submitting another")
            def revalidate_attempt():
                self._admit(binding, root, scope, work, work_action="edit")
                current = store.snapshot()
                current_machine = app.read_instance_state_machine(current, registry.assembly_protocol,
                    registry.standard_library.state_machine_protocol, work)
                if (app._text(current, current_machine.current_state_root).casefold() != "claimed"
                        or app._governed_work_claimant_session(current, registry, work) != worker):
                    raise AuthorizationDenied("The retained worker no longer owns this Work claim")
                if retained_review:
                    history = app.machine_history(current, registry.standard_library.state_machine_protocol, current_machine.root_id)
                    if not history or history[-1].root_id != recovered_review["claim"]:
                        raise AuthorizationDenied("The recovered review's exact Work claim changed")
                _require_latest_settled_failure(current, registry, work,
                    {"receipt":receipt_root, "created_at":receipt.created_at}, store=store)
            try:
                result = revise_project_values(self.server, binding, root=root, scope=scope,
                    work=work, previous_receipt=receipt_root, before_binding_commit=revalidate_attempt, **draft)
            except Exception:
                revision_id = draft.get("revision_id")
                if (type(revision_id) is str and re.fullmatch(r"[a-f0-9]{32}", revision_id)
                        and work + ":project-revision:" + revision_id in store.snapshot().cells):
                    self._set("published", approved=False, revision_pending=revision_id,
                        error="Revision draft saved; its final binding needs reconciliation. The model was not run.")
                raise
            self._set("published", approved=False, revision_pending=None,
                work_revision=result, error=None)

    def _revise_local_project(self, binding, body):
        """Edit a closed delivery's Work without attaching or issuing a grant."""
        from .existing_workshop_project_revision import revise_project_values

        if self._status["state"] not in ("idle", "local_delivery_abandoned"):
            raise InvalidCell("Close the current local delivery before revising its inputs")
        root, scope, work = body["root"], body["scope"], body["work"]
        draft = body["draft"]
        identity = (*self._binding(binding, root, scope), work, body["request_id"])
        with self.server.mutation_lock, self.server.universal_registry.authorization.broker.live_context(binding.context):
            prior, _ = self._admit_local_project_recovery(binding, root, scope, work,
                body["result"], body["resolution"], allow_revision=draft.get("revision_id"))
            held = self._status.get("local_resolution")
            if held is not None and held != prior["local_resolution"]:
                raise AuthorizationDenied("The retained local delivery differs from this revision")
            pending = self._status.get("revision_pending")
            if pending and pending != draft.get("revision_id"):
                raise InvalidCell("Recover the existing staged revision before submitting another")
            self._identity, self._browser_binding, self._project = identity, binding, True
            self._set("local_delivery_abandoned", mode="project", work=work,
                request_id=body["request_id"], approved=False, artifact=None,
                local_resolution=prior["local_resolution"])

            def revalidate_attempt():
                current, _ = self._admit_local_project_recovery(binding, root, scope, work,
                    body["result"], body["resolution"], allow_revision=draft.get("revision_id"))
                if current != prior:
                    raise AuthorizationDenied("The local decision or current Work claim changed during revision")

            store = self.server.universal_store
            try:
                result = revise_project_values(self.server, binding, root=root, scope=scope,
                    work=work, previous_local_resolution=body["resolution"], previous_result=body["result"],
                    before_binding_commit=revalidate_attempt, **draft)
            except Exception:
                revision_id = draft.get("revision_id")
                if (type(revision_id) is str and re.fullmatch(r"[a-f0-9]{32}", revision_id)
                        and work + ":project-revision:" + revision_id in store.snapshot().cells):
                    self._set("local_delivery_abandoned", approved=False, revision_pending=revision_id,
                        error="Revision draft saved; finish its binding before preparing this Work. No model was run.")
                raise
            self._set("local_delivery_abandoned", approved=False, revision_pending=None,
                work_revision=result, error=None)

    def _admit_project_review_refresh(self, binding, prepared, *, allowed_new=None, expected_claim=None):
        """Bounded graph checks; caller holds mutation lock and browser admission."""
        import hashlib
        import json
        import time
        from . import universal_application as app
        from .cell_protocols import read_relation
        from .cell_adapters import read_permission
        from .cell_connector_execution import (read_connector_delegation, read_connector_provider,
            read_connector_execution_grant, read_connector_execution_receipt)
        from .existing_workshop_project_execution import _material, PROVIDER, OPERATION
        from .workshop_project_resolution import _roots

        server, p = self.server, prepared
        if (self._client is None or self._client.agent_session_root != p['worker']
                or self._grant is not None or self._settled is not None or self._cancel.is_set()
                or not server._model_execution_idle.is_set() or server._model_execution_active
                or server._project_work_pending is not None):
            raise InvalidCell('Finish the current physical operation before refreshing a review')
        self._admit(binding, self._identity[3], self._identity[4], p['work'])
        if not server._machine_agent_session_has_live_capability(p['worker']):
            raise AuthorizationDenied('The retained review worker is no longer live')
        store, registry = server.universal_store, server.universal_registry
        _, _, work = app._baboom_execution_work_context(store, registry,
            agent_session_root=p['worker'], work_root=p['work'], authentication_context=binding.context,
            purpose='Refresh expired project review')
        material, raw = _material(store, registry, p['work'], work)
        if (hashlib.sha256(raw).hexdigest() != p['input_digest'] or material['model'] != p['model']
                or material['artifact_name'] != p['artifact_name']
                or json.loads(p['review_text']) != material):
            raise AuthorizationDenied('The reviewed project material changed')
        snapshot = store.snapshot()
        machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
            registry.standard_library.state_machine_protocol, p['work'])
        history = read_relation(snapshot, machine.history_root, budget=2048, retain_projection=False)
        if (not history or len(history) > 256
                or len({row.participant_id for row in history}) != len(history)
                or any(row.role_id != registry.standard_library.state_machine_protocol.role('history-member') for row in history)
                or app._text(snapshot, machine.current_state_root).casefold() != 'claimed'
                or app._governed_work_claimant_session(snapshot, registry, p['work']) != p['worker']):
            raise AuthorizationDenied('The retained worker no longer owns the claimed Work')
        claim = history[-1].participant_id
        if expected_claim is not None and claim != expected_claim:
            raise AuthorizationDenied('The exact Work claim changed during review refresh')
        protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
        old = read_connector_delegation(snapshot, protocol, adapters, p['delegation'])
        permission = read_permission(snapshot, adapters, old.permission_root)
        provider = read_connector_provider(snapshot, protocol, adapters, old.provider_root)
        if (old.work_root != p['work'] or old.session_root != p['worker'] or old.input_digest != p['input_digest']
                or old.input_bytes != len(raw) or old.provider_root != registry.baboom_connector_provider_roots.get(PROVIDER)
                or provider.operation != OPERATION or time.time() < old.expires_at
                or permission.user_root != binding.subject_root or permission.lifecycle_root != adapters.states['requested']):
            raise AuthorizationDenied('Only an expired, unapproved project delegation may be refreshed')
        old_birth = store.cell_created_revision(old.root_id)
        if type(old_birth) is not int:
            raise InvalidCell('Original delegation birth is unavailable')
        same_work = set()
        for root in _roots(snapshot, protocol, 'delegation'):
            other = read_connector_delegation(snapshot, protocol, adapters, root)
            if other.work_root != p['work']:
                continue
            same_work.add(root)
            if root != old.root_id:
                birth = store.cell_created_revision(root)
                if type(birth) is not int or birth >= old_birth and root != allowed_new:
                    raise InvalidCell('Another project delegation supersedes this review')
        for root in _roots(snapshot, protocol, 'grant'):
            grant = read_connector_execution_grant(snapshot, protocol, adapters, root)
            if grant.delegation_root in (old.root_id, allowed_new):
                raise InvalidCell('A reviewed delegation already has an execution grant')
            if grant.delegation_root in same_work and store.cell_created_revision(root) >= old_birth:
                raise InvalidCell('A newer project invocation prevents review refresh')
        for root in _roots(snapshot, protocol, 'receipt'):
            receipt = read_connector_execution_receipt(snapshot, protocol, adapters, root)
            if receipt.delegation_root in (old.root_id, allowed_new):
                raise InvalidCell('A reviewed delegation already has a settled result')
            if receipt.delegation_root in same_work and store.cell_created_revision(root) >= old_birth:
                raise InvalidCell('A newer project settlement prevents review refresh')
        from .cell_model_execution import (read_model_delegation,
            read_model_execution_grant, read_model_execution_receipt)
        model_protocol = registry.baboom_model_execution_protocol
        model_work = set()
        for root in _roots(snapshot, model_protocol, 'delegation'):
            delegated = read_model_delegation(snapshot, model_protocol, adapters, root)
            if delegated.work_root == p['work']:
                model_work.add(root)
                if store.cell_created_revision(root) >= old_birth:
                    raise InvalidCell('A newer model delegation prevents review refresh')
        for kind, reader in (('grant', read_model_execution_grant), ('receipt', read_model_execution_receipt)):
            for root in _roots(snapshot, model_protocol, kind):
                row = reader(snapshot, model_protocol, adapters, root)
                if row.delegation_root in model_work and store.cell_created_revision(root) >= old_birth:
                    raise InvalidCell('A newer model invocation prevents review refresh')
        if allowed_new is not None:
            fresh = read_connector_delegation(snapshot, protocol, adapters, allowed_new)
            requested = read_permission(snapshot, adapters, fresh.permission_root)
            if (fresh.root_id == old.root_id or store.cell_created_revision(fresh.root_id) <= old_birth
                    or fresh.work_root != old.work_root or fresh.session_root != old.session_root
                    or fresh.provider_root != old.provider_root or fresh.input_digest != old.input_digest
                    or fresh.input_bytes != old.input_bytes or fresh.datatype_root != old.datatype_root
                    or not time.time() < fresh.expires_at <= time.time() + 301
                    or requested.user_root != binding.subject_root or requested.lifecycle_root != adapters.states['requested']):
                raise AuthorizationDenied('Refreshed delegation does not preserve the reviewed input')
        if store.revision != snapshot.revision:
            raise InvalidCell('Project review changed during admission')
        return claim

    def _refresh_project_review(self, binding, body, identity):
        """Explicitly replace expired unapproved preparation; never replay uncertainty."""
        source = (body['delegation'], body['input_digest'])
        if identity != self._identity:
            raise AuthorizationDenied('Refresh belongs to another Workshop operation')
        prior = self._review_refresh
        if prior is not None and prior['identity'] == identity and prior['source'] == source:
            return self.status(binding, root=body['root'], scope=body['scope'])
        if (not self._project or self._status['state'] != 'awaiting_approval'
                or self._status.get('approved') is not False or not isinstance(self._prepared, dict)
                or self._status.get('revision_pending') or self._grant is not None or self._settled is not None):
            raise InvalidCell('Only an unapproved expired project review can be refreshed')
        old = dict(self._prepared)
        client = self._client
        if source != (old.get('delegation'), old.get('input_digest')) or old.get('work') != body['work']:
            raise AuthorizationDenied('Refresh does not match the exact displayed delegation')
        registry = self.server.universal_registry
        with self.server.mutation_lock, registry.authorization.broker.live_context(binding.context):
            claim = self._admit_project_review_refresh(binding, old)
        self._review_refresh = {'identity':identity, 'source':source, 'prepared':old, 'claim':claim}
        self._set('preparing', approved=False, review_refresh={'delegation':source[0],
            'input_digest':source[1], 'request_id':identity[6]}, error=None)
        try:
            # The owner route needs its mutation lock; never hold it across client HTTP.
            fresh = client.request('POST', '/api/universal/project-work-prepare', {'root':body['work']})
            if (not isinstance(fresh, dict) or not isinstance(fresh.get('delegation'), str)
                    or any(fresh.get(key) != old.get(key) for key in
                        ('work','worker','input_digest','model','review_text','artifact_name'))):
                raise InvalidCell('Refreshed preparation returned different project input')
            with self.server.mutation_lock, registry.authorization.broker.live_context(binding.context):
                if identity != self._identity or self._prepared != old or self._client is not client:
                    raise AuthorizationDenied('Retained review changed during refresh')
                self._admit_project_review_refresh(binding, old, allowed_new=fresh['delegation'], expected_claim=claim)
                from .cell_connector_execution import read_connector_delegation
                delegation = read_connector_delegation(self.server.universal_store.snapshot(),
                    registry.baboom_connector_execution_protocol, registry.adapter_protocol, fresh['delegation'])
                if fresh.get('expires_at') != delegation.expires_at:
                    raise InvalidCell('Refreshed review expiry differs from its delegation')
                self._prepared = fresh
                self._set('awaiting_approval', approved=False, delegation=fresh['delegation'],
                    input_digest=fresh['input_digest'], model=fresh['model'], review_text=fresh['review_text'],
                    artifact_name=fresh['artifact_name'], error=None)
        except Exception:
            self._set('uncertain', approved=False,
                error='Review refresh is uncertain. The prior review is retained; no refresh or model call will be repeated.')
            raise
        return self.status(binding, root=body['root'], scope=body['scope'])

    def _approve_project(self, binding, input_digest):
        from . import universal_application as app
        from .existing_workshop_project_execution import _material, PROVIDER, OPERATION
        from .cell_adapters import read_permission, grant_permission
        from .cell_agent_body import read_agent_session
        from .cell_connector_execution import read_connector_delegation, read_connector_provider
        import hashlib
        import time

        if not self._project or self._status["state"] != "awaiting_approval" or not self._prepared:
            raise InvalidCell("Prepare and inspect a project repair first")
        p = self._prepared
        if input_digest != p["input_digest"]:
            raise AuthorizationDenied("Approval does not match the displayed project input")
        with self.server.mutation_lock, self.server.universal_registry.authorization.broker.live_context(binding.context):
            self._admit(binding, self._identity[3], self._identity[4], p["work"])
            store, registry = self.server.universal_store, self.server.universal_registry
            _, _, work = app._baboom_execution_work_context(store, registry,
                agent_session_root=p["worker"], work_root=p["work"],
                authentication_context=binding.context, purpose="Project approval")
            _, raw = _material(store, registry, p["work"], work)
            if hashlib.sha256(raw).hexdigest() != input_digest:
                raise AuthorizationDenied("The project workflow changed; prepare its current input")
            # This is the authenticated browser's explicit approval gesture.
            # The founder browser session is not an enrolled machine runtime.
            snapshot = store.snapshot()
            founder = read_agent_session(snapshot, registry.agent_body.protocol,
                registry.authorization.protocol, registry.agent_body.session.root_id)
            if (founder.subject_root != binding.subject_root
                    or founder.body_root != registry.agent_body.body.root_id
                    or founder.state_root != registry.agent_body.protocol.state("active")):
                raise AuthorizationDenied("Founder approval session is not active")
            delegation = read_connector_delegation(snapshot,
                registry.baboom_connector_execution_protocol, registry.adapter_protocol, p["delegation"])
            if (delegation.work_root != p["work"] or delegation.session_root != p["worker"]
                    or delegation.input_digest != input_digest or delegation.input_bytes != len(raw)
                    or delegation.provider_root != registry.baboom_connector_provider_roots.get(PROVIDER)
                    or time.time() >= delegation.expires_at):
                raise AuthorizationDenied("Reviewed project delegation changed or expired")
            provider = read_connector_provider(snapshot, registry.baboom_connector_execution_protocol,
                registry.adapter_protocol, delegation.provider_root)
            if provider.operation != OPERATION:
                raise AuthorizationDenied("Reviewed project operation changed")
            app._require_application_authorization(snapshot, registry, "execute", delegation.root_id,
                authentication_context=binding.context, resource_lineage_roots=(delegation.work_root,))
            permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
            if permission.user_root != founder.subject_root:
                raise AuthorizationDenied("Project permission belongs to another user")
            if permission.lifecycle_root == registry.adapter_protocol.states["granted"]:
                self._set("awaiting_approval", approved=True)
                return
            if permission.lifecycle_root != registry.adapter_protocol.states["requested"]:
                raise InvalidCell("Project permission is no longer awaiting approval")
            registry.authorization.broker.resolve(binding.context)
            if time.time() >= delegation.expires_at:
                raise AuthorizationDenied("Project delegation expired during approval")
            gesture = self.server.adapter_consent_broker.mint_from_user_gesture(
                delegation.permission_root, founder.subject_root)
            grant_permission(store, registry.adapter_protocol,
                app._connector_execution_catalog_for_provider(registry, provider),
                delegation.permission_root, self.server.adapter_consent_broker, gesture,
                expected_revision=snapshot.revision)
            self._set("awaiting_approval", approved=True)

    def _execute_project(self, binding):
        if self._status["state"] != "awaiting_approval" or not self._prepared:
            return
        if not self._status.get("approved"):
            raise AuthorizationDenied("Approve this exact project repair before running it")
        self._admit(binding, self._identity[3], self._identity[4], self._prepared["work"])
        self._set("executing")
        try:
            self._grant = self._client.request("POST", "/api/universal/connector-delegation-grant",
                {"delegation":self._prepared["delegation"]})
            self._settled = self._client.request("POST", "/api/universal/project-work-execute",
                {"grant":self._grant["grant"], "capability":self._grant["capability"]})
            self._accept_project_result(self._settled)
        except Exception:
            self._set("uncertain", error="Project execution needs reconciliation. No replacement grant will be issued.")
            raise

    def _accept_project_result(self, result):
        p = self._prepared
        if (type(result) is not dict or result.get("work") != p["work"]
                or result.get("delegation") != p["delegation"]
                or result.get("input_digest") != p["input_digest"]
                or result.get("grant") != self._grant["grant"]):
            raise InvalidCell("Project execution returned another operation's result")
        if result.get("outcome") == "uncertain":
            from .workshop_project_resolution import read_project_delivery_resolution
            decision = read_project_delivery_resolution(self.server.universal_store.snapshot(),
                self.server.universal_registry, self._grant["grant"], store=self.server.universal_store)
            if decision is not None:
                self._set("local_delivery_abandoned", local_resolution=decision, approved=False, artifact=None,
                    error="Local patch delivery was abandoned. The provider outcome remains unknown; no request was repeated.")
                return
            self._set("uncertain", error="The host outcome remains uncertain; the task will not rerun.")
            return
        if result.get("outcome") not in ("succeeded", "failed") or not result.get("receipt"):
            raise InvalidCell("Project result has no settled execution receipt")
        self._set("settled", receipt=result.get("receipt"), result_text=result.get("summary") or "",
            artifact={"name":result.get("artifact_name"), "digest":result.get("output_digest"),
                "bytes":result.get("output_bytes"), "summary":result.get("summary"),
                "result":result.get("result"), "receipt":result.get("receipt"),
                "outcome":result.get("outcome")}, error=result.get("error_code") or None)

    def _reconcile_project(self, binding):
        from .existing_workshop_project_execution import _record_result
        from .cell_value_graph import read_value_graph

        if self._grant is None or self._prepared is None:
            raise InvalidCell("No retained project attempt is available; do not prepare another implicitly")
        with self.server.mutation_lock:
            self._admit(binding, self._identity[3], self._identity[4], self._prepared["work"])
            if not self.server._model_execution_idle.is_set():
                raise InvalidCell("Project execution is still settling")
            pending = self.server._project_work_pending
            if pending is not None and pending[1].root_id == self._grant["grant"]:
                self._settled = _record_result(self.server, *pending)
                self.server._project_work_pending = None
            else:
                root = self._grant["grant"] + ":project-result"
                snapshot = self.server.universal_store.snapshot()
                result = read_value_graph(snapshot, self.server.universal_registry.value_graph_protocol, root)
                receipt = self._grant["grant"] + ":project-receipt"
                self._settled = {**result, "result":root, "receipt":receipt if receipt in snapshot.cells else None}
            self._accept_project_result(self._settled)

    def _read_project_artifact(self):
        if not self._project or self._settled is None or self._settled.get("outcome") != "succeeded":
            raise InvalidCell("There is no successful project artifact to read")
        host = self.server.project_work_execution_broker
        if host is None:
            raise InvalidCell("The project artifact host is not connected")
        return host.read_artifact(self._settled["artifact_name"], self._settled["output_digest"])

    def _read_saved_project_artifact(self, binding, root, scope, work, request_id, result_root, receipt_root):
        from .existing_workshop_project_execution import _stable_admission, project_saved_artifacts
        with _stable_admission(self.server, binding.context):
            self._admit(binding, root, scope, work, work_action="read")
            descriptors = project_saved_artifacts(self.server.universal_store.snapshot(),
                self.server.universal_registry, work, receipt_root=receipt_root)
            if len(descriptors) != 1 or descriptors[0]["result"] != result_root:
                raise InvalidCell("Requested artifact does not match its persisted receipt")
            artifact = descriptors[0]
            host = self.server.project_work_execution_broker
            if host is None:
                raise InvalidCell("The project artifact host is not connected")
            content = host.read_artifact(artifact["name"], artifact["digest"])
            if len(content.encode("utf-8")) != artifact["bytes"]:
                raise InvalidCell("Saved artifact size differs from its receipt")
            self._admit(binding, root, scope, work, work_action="read")
            return {"ok":True, "root":root, "scope":scope, "owner":binding.subject_root,
                "view":binding.view_root, "work":work, "request_id":request_id, "mode":"project",
                "state":"saved", "artifact":artifact, "artifact_text":content}

    def _publish_project(self, binding):
        if self._settled is None or self._status["state"] not in ("settled", "publication_uncertain", "published"):
            raise InvalidCell("There is no settled project result to publish")
        if self._status["state"] == "published":
            return
        result = self._settled
        body = ("Repair artifact created: " + str(result["artifact_name"]) + "\n" + str(result["summary"])
            + "\nSHA-256: " + str(result["output_digest"]) + "\nSource files have not been changed."
            if result["outcome"] == "succeeded" else "Project repair failed: " + str(result["error_code"]))
        try:
            publication = self._client.request("POST", "/api/universal/workshop", {
                "category":"note", "text":body, "refs":[self._prepared["work"]], "evidence":[],
                "recipients":[binding.subject_root], "reply_to":None,
                "idempotency_key":self._identity[6] + ":project-result", "created_at":None})
            self._set("published", publication=publication)
        except Exception:
            self._set("publication_uncertain", error="Artifact result publication needs reconciliation; retrying does not rerun the model.")
            raise

    def admit_execution(self, grant_root):
        """Called by the physical execution owner under its mutation lock."""
        if self._grant is not None and self._grant.get("grant") == grant_root:
            if self._cancel.is_set() or self._identity is None:
                raise AuthorizationDenied("Native Workshop execution is closing")
            self._admit(self._browser_binding, self._identity[3], self._identity[4], self._identity[5])
            return {"free_only":True, "reasoning_effort":"none", "max_output_tokens":4096}
        return {}

    def close(self):
        self._cancel.set()
        if self._native is not None:
            # The running operation observes this signal and owns its drain.
            # interrupt() requires an active ready turn, so calling it here
            # would break shutdown for idle or already stopped native agents.
            self._native['stop_requested'].set()
        if not self._action.acquire(timeout=65):
            raise RuntimeError("Workshop operation has not drained; store teardown refused")
        try:
            if self._native is not None and self._native.get('process') is not None:
                observed = _drain_native_process(self._native['process'])
                if not observed['drained']:
                    raise RuntimeError('Native Workshop descendants remain; store teardown refused')
                if self._native.get('profile') is not None:
                    self._native['profile'].cleanup(process_exited=observed['drained'])
        finally:
            self._action.release()
