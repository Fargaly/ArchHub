"""Court: the CDE write gate reaches the live native owner, and fails closed (live 717, 2026-10-01).

The gate (governance app_write_authority.AppWriteAuthority, a command-hook
process) bound a NEW Agent Session for every write while the session's native
MCP owner already held the live binding, and the application refused it:
"runtime Agent Session identity is already bound; renew it instead".

Gate v2 (Ping's required changes):
- the gate asks through the owner's per-session pipe first;
- only a PRE-dispatch "no owner" (no record, or the pipe never took the
  connection) may fall back to the hook's own route (self.run, which may
  enroll), at most once;
- after the request is sent, a timeout, closed pipe, wrong or result-less reply,
  or an application refusal fails closed: self.run and _enroll run ZERO times;
- a changed owner actor is refused with zero application calls;
- a real application issues a same-actor permit and consumes its receipt.

The governance module is outside this repository: ARCHHUB_GOVERNANCE_HOOKS
names the hooks folder under test (required; the court fails without it).
Temp state, memory keys and an in-memory owner vault only: no live
application, no DPAPI key ring, no :8474.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
import uuid
from types import SimpleNamespace as NS

import psutil
import pytest

from nodelang import native_stop_hook as hook
from nodelang.cell_secret_keys import MemorySigningKeyProvider

PRODUCT = Path(__file__).resolve().parents[1]
SESSION = '71743447-6dd5-4050-bc4f-d228f7a1d91e'
ACTOR = 'app:agent-session:runtime:' + 'e' * 32
PERMIT = 'brain.universal_cde_write_permit'
RECEIPT = 'brain.universal_cde_write_receipt'
KEY = MemorySigningKeyProvider('archhub.local.universal-runtime-pipe', b'g' * 32)
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows secured pipe')


def _permit_args(session=SESSION, **changes):
    return {'session_id': session, 'vendor': 'claude', 'operation': 'apply_patch',
            'path': '10.PRODUCT/13.NODE-LANGUAGE/nodelang/court_gate_target.py',
            'content_digest': 'd' * 64, 'request_id': 'toolu_court:0:' + 'a' * 32,
            'nonce': 'n' * 32, **changes}


def _memory_vault():
    values = {}
    return NS(get_password=lambda service, key: values.get(key),
              set_password=lambda service, key, value: values.__setitem__(key, value),
              delete_password=lambda service, key: values.pop(key, None), values=values)


@pytest.fixture
def vault(monkeypatch):
    made = _memory_vault()
    # The gate never passes a vault; the owner record is read from this one.
    monkeypatch.setattr(hook, '_vault', lambda: made)
    return made


class Gate:
    """The governance AppWriteAuthority under test, with its own route counted."""

    def __init__(self, tmp_path, monkeypatch):
        folder = os.environ.get('ARCHHUB_GOVERNANCE_HOOKS', '').strip()
        source = Path(folder) / 'app_write_authority.py' if folder else None
        if source is None or not source.is_file():
            pytest.fail('ARCHHUB_GOVERNANCE_HOOKS must name the governance hooks folder under test')
        monkeypatch.setenv('ARCHHUB_PRODUCT_ROOT', str(PRODUCT))
        spec = importlib.util.spec_from_file_location('court_app_write_authority_%s' % uuid.uuid4().hex,
                                                      source)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.authority = self.module.AppWriteAuthority(
            descriptor_path=tmp_path / 'gate-runtime.json', key_provider=KEY,
            directory=tmp_path / 'gate-sessions', protect=lambda data: data, unprotect=lambda data: data)
        self.run_calls, self.enroll_calls = [], []
        original_run = self.authority.run

        def counted_run(runtime, session_id, operation):
            self.run_calls.append((runtime, session_id))
            return original_run(runtime, session_id, operation)

        def counted_enroll(path, runtime, session_id):
            self.enroll_calls.append((runtime, session_id))
            raise self.module.AppWriteAuthorityError('court: the hook route enrolled')

        self.authority.run = counted_run
        self.authority._enroll = counted_enroll

    def __call__(self, name, arguments, timeout=5.0):
        return self.authority(name, arguments, timeout=timeout)


@pytest.fixture
def gate(tmp_path, monkeypatch):
    return Gate(tmp_path, monkeypatch)


class FakeClient:
    def __init__(self, behaviour):
        self.agent_session_root = ACTOR
        self.behaviour = behaviour
        self.calls = []

    def issue_cde_write_permit(self, **body):
        self.calls.append(('permit', body))
        return self.behaviour(body)

    consume_cde_write_permit = issue_cde_write_permit


class FakeOwner:
    def __init__(self, behaviour, status_actor=ACTOR):
        self._identity = NS(runtime='claude', external_session_id=SESSION)
        self.client = FakeClient(behaviour)
        self.status_actor = status_actor
        self.entered = 0

    def owner_status(self):
        return {'state': 'bound', 'agent_session': self.status_actor,
                'pinned': {'instance_digest': 'i' * 64}}

    def bound_client(self):
        owner = self

        class Held:
            def __enter__(self):
                owner.entered += 1
                return owner.client

            def __exit__(self, *exc):
                return False
        return Held()


def _host(owner, vault):
    return hook.NativeStopHost(owner, vault=vault).start()


# -- (1) after dispatch the gate never enrolls or retries -----------------------

def _slow(body):
    time.sleep(2.5)
    return {'permit': 'late'}


def _unserialisable(body):
    return {'permit': object()}       # the owner cannot send it: the pipe closes unanswered


def _denied(body):
    raise RuntimeError('CDE write permit denied: the Work does not grant this path')


@pytest.mark.parametrize('case', ['timeout', 'eof', 'wrong_response', 'missing_result', 'denial'])
def test_after_dispatch_the_gate_fails_closed_and_never_enrolls(case, gate, vault):
    behaviour = {'timeout': _slow, 'eof': _unserialisable, 'denial': _denied}.get(
        case, lambda body: {'permit': 'p'})
    owner = FakeOwner(behaviour)
    host = _host(owner, vault)
    if case == 'wrong_response':
        host._handle = lambda request: {'request_id': 'f' * 32, 'fingerprint': request['fingerprint'],
                                        'result': {'permit': 'someone else'}}
    elif case == 'missing_result':
        host._handle = lambda request: {'request_id': request['request_id'],
                                        'fingerprint': request['fingerprint']}
    try:
        with pytest.raises(gate.module.AppWriteAuthorityError) as refused:
            gate(PERMIT, _permit_args(), timeout=0.5 if case == 'timeout' else 5.0)
        assert gate.run_calls == [], 'the gate fell back to its own route after the owner was asked'
        assert gate.enroll_calls == [], 'the gate enrolled after the owner was asked'
        assert 'not retried' in str(refused.value)
        if case == 'denial':
            assert 'does not grant this path' in str(refused.value)
        if case in ('timeout', 'eof', 'denial'):
            assert len(owner.client.calls) == 1   # sent exactly once, never replayed
    finally:
        host.close()


# -- (2) a changed owner actor is refused with zero application calls -----------

def test_a_changed_owner_actor_is_refused_with_no_application_call(gate, vault):
    owner = FakeOwner(lambda body: {'permit': 'p'})
    host = _host(owner, vault)
    try:
        owner.status_actor = 'app:agent-session:runtime:' + 'c' * 32   # the owner moved on
        with pytest.raises(gate.module.AppWriteAuthorityError) as refused:
            gate(PERMIT, _permit_args())
        assert 'actor' in str(refused.value)
        assert owner.client.calls == [] and owner.entered == 0
        assert gate.run_calls == [] and gate.enroll_calls == []
    finally:
        host.close()


# -- pre-dispatch: the only bounded fallback --------------------------------------

def test_no_owner_record_uses_the_hook_route_exactly_once(gate, vault):
    with pytest.raises(gate.module.AppWriteAuthorityError, match='court: the hook route enrolled'):
        gate(PERMIT, _permit_args())
    assert gate.run_calls == [('claude', SESSION)]
    assert gate.enroll_calls == [('claude', SESSION)]


def test_an_owner_pipe_that_never_connects_uses_the_hook_route_exactly_once(gate, vault):
    fingerprint = hook._fingerprint('claude', SESSION)
    vault.values[fingerprint] = json.dumps({
        'version': 1, 'fingerprint': fingerprint, 'key': 'a' * 64,
        'endpoint': r'\\.\pipe\ArchHub.NativeStop.' + uuid.uuid4().hex,   # nobody listens
        'pid': os.getpid(), 'created_at': psutil.Process().create_time(),
        'actor': ACTOR, 'instance': 'i' * 64})
    with pytest.raises(gate.module.AppWriteAuthorityError, match='court: the hook route enrolled'):
        gate(PERMIT, _permit_args())
    assert gate.run_calls == [('claude', SESSION)]
    assert gate.enroll_calls == [('claude', SESSION)]


# -- (3) a real application: same-actor permit issued, receipt consumed -----------

def test_real_application_issues_the_same_actor_permit_and_consumes_its_receipt(
        tmp_path, gate, vault):
    from nodelang import application_server as application_server_module
    from nodelang import commit_intent
    from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_signing_authority import LocalEd25519KmsProvider
    from nodelang.native_agent_session import NativeAgentSession
    from nodelang.universal_application import create_universal_governed_work
    from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance
    from tests_replica.workshop_gate_support import open_execution_gate

    workspace = tmp_path / 'ws'
    workspace.mkdir()
    descriptor = tmp_path / 'court-runtime.json'
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                               machine_key_provider=KEY, universal_workspace_root=workspace,
                               universal_state_path=tmp_path / 'court-graph.sqlite3',
                               runtime_compliance_runner=_green_runtime_compliance).start()
    owner = host = None
    try:
        signer = LocalEd25519KmsProvider(provider_id='court.gate', authority_id='court-gate')
        server.cde_write_signing_provider = signer
        with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub', reason='court signing key'):
            server.cde_write_signing_descriptor_root = application_server_module._ensure_cde_write_signing_authority(
                server.universal_store, server.universal_registry, signer,
                descriptor_root='court:cde-write-signing-key:v1')
        target = '10.PRODUCT/13.NODE-LANGUAGE/nodelang/court_gate_target.py'
        container = {
            'container_id': 'GM.nodes.court-gate', 'source_requirement': 'court:gate',
            'domain': 'nodes', 'tier': 'T1', 'lifecycle_state': 'WIP', 'suitability_status': 'S0',
            'revision': 'P01', 'owner': 'founder', 'checker': 'court', 'allowed_paths': [target],
            'gate_kind': 'pytest',
            'gate_spec': {'path': '10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py'},
            'write_grants': [{'path': target, 'scope': 'exact', 'operations': ['apply_patch']}],
        }
        with commit_intent.declare(commit_intent.USER_ACTION, actor='app:identity:founder', reason='court work'):
            work_root, _wire, _revision = create_universal_governed_work(
                server.universal_store, server.universal_registry, title='Court gate',
                description='court', priority=100, external_key='court:gate',
                structured_references={'cde-container': container}, x=320, y=240)
        open_execution_gate(server, work_root, 'gate')

        binds = []

        class Counted(UniversalRuntimeClient):
            def bind_agent_session(self, **kwargs):
                binds.append(kwargs.get('runtime'))
                return super().bind_agent_session(**kwargs)

        owner = NativeAgentSession(environment={'CLAUDE_CODE_SESSION_ID': SESSION},
                                   descriptor_path=descriptor, key_provider=KEY, client_factory=Counted)
        owner.connect()
        with owner.bound_client() as client:
            actor = client.agent_session_root
            client.request('POST', '/api/universal/workshop', {
                'category': 'plan', 'text': 'Exercise the gate through the owner.', 'refs': [work_root],
                'evidence': [], 'recipients': [], 'reply_to': None,
                'idempotency_key': 'court:gate:plan', 'created_at': '2026-10-01T00:00:00+00:00'})
            client.claim_work(work_root)
        assert binds == ['claude']

        # The defect, on the real application: a second bind for this live identity is refused.
        with pytest.raises(MachineTransportError, match='already bound; renew it instead'):
            UniversalRuntimeClient(descriptor, KEY).bind_agent_session(
                runtime='claude', external_session_id=SESSION)

        host = hook.NativeStopHost(owner, vault=vault).start()
        digest = hashlib.sha256(b'court gate content').hexdigest()
        request = dict(session_id=SESSION, vendor='claude', operation='apply_patch', path=target,
                       content_digest=digest, request_id='toolu_court_gate:0:' + 'b' * 32)
        issued = gate(PERMIT, dict(request, nonce='court-gate-nonce'), timeout=25.0)
        assert issued['agent_session'] == actor
        assert issued['work'] == work_root
        assert issued['content_digest'] == digest and issued['path'] == target
        consumed = gate(RECEIPT, dict(request, permit=issued['permit']), timeout=25.0)
        assert consumed['kind'] == 'consumed'
        assert consumed['permit'] == issued['permit'] and consumed['work'] == work_root
        assert gate.run_calls == [] and gate.enroll_calls == []
        assert binds == ['claude'], 'the gate route made another binding'
    finally:
        if host is not None:
            host.close()
        if owner is not None:
            try:
                owner.close()
            except Exception:
                pass
        server.close()
