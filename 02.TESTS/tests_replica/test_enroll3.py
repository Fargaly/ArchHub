"""ENROLL3: sampled policy work and real pipe timeout recovery."""
import threading
import time

import pytest

from nodelang import cell_authorization as authorization
from nodelang.application_machine_transport import MachineNoResponse, UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import Cell, NULL_CELL_ID
from nodelang.cell_protocols import read_relation


def test_route_policy_is_verified_once_across_unrelated_commits(monkeypatch):
    server = ApplicationServer(enable_machine_transport=False, live_watch=False,
                               enable_machine_projection_prewarm=False)
    calls = []
    original = authorization._policy_digest
    def digest(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(authorization, '_policy_digest', digest)
    try:
        context = server.universal_registry.authorization.session.context()
        for number in range(3):
            server.universal_store.commit(server.universal_store.revision,
                create=(Cell('enroll3:unrelated:%s' % number, NULL_CELL_ID, NULL_CELL_ID, b''),))
            server.require_universal_http_route('POST', '/api/universal/agent-session',
                                                authentication_context=context)
        assert len(calls) == 1, 'unchanged released policy was hashed again'
    finally:
        server.close()


def test_ready_enrollment_rechecks_subject_ownership(tmp_path):
    descriptor = tmp_path / 'runtime.json'
    provider = MemorySigningKeyProvider('archhub.local.universal-runtime-pipe', b'S' * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
        machine_key_provider=provider, live_watch=False, enable_machine_projection_prewarm=False).start()
    try:
        first = UniversalRuntimeClient(descriptor, provider)
        result = first.bind_agent_session(runtime='codex', external_session_id='enroll3-subject')
        protocol = server.universal_registry.agent_body.protocol
        member = next(row for row in read_relation(server.universal_store.snapshot(), result['agent_session'])
                      if row.role_id == protocol.role('session-subject'))
        cell = server.universal_store.read(member.incidence_id)
        server.universal_store.commit(server.universal_store.revision, replace=(
            Cell(cell.id, cell.link0, server.universal_registry.application_root, cell.atom),))
        replay = UniversalRuntimeClient(descriptor, provider)
        with pytest.raises(Exception, match='subject'):
            replay.bind_agent_session(runtime='codex', external_session_id='enroll3-subject')
    finally:
        server.close()


@pytest.mark.parametrize('retry_inflight', [False, True])
def test_timed_out_pipe_enrollment_finishes_and_first_retry_returns_it(tmp_path, monkeypatch, retry_inflight):
    descriptor = tmp_path / 'runtime.json'
    provider = MemorySigningKeyProvider('archhub.local.universal-runtime-pipe', b'3' * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
        machine_key_provider=provider, live_watch=False, enable_machine_projection_prewarm=False).start()
    client = UniversalRuntimeClient(descriptor, provider)
    finished = threading.Event()
    calls = []
    original = server._ensure_universal_workshop_participant
    def participant(root):
        calls.append(root)
        time.sleep(6)
        original(root)
        finished.set()
    monkeypatch.setattr(server, '_ensure_universal_workshop_participant', participant)
    try:
        started = time.monotonic()
        with pytest.raises(MachineNoResponse):
            client.bind_agent_session(runtime='codex', external_session_id='enroll3-timeout')
        assert 4.5 <= time.monotonic() - started < 6
        if not retry_inflight:
            assert finished.wait(10), 'disconnected caller cancelled server enrollment'
        started = time.monotonic()
        result = client.bind_agent_session(runtime='codex', external_session_id='enroll3-timeout')
        assert time.monotonic() - started < 5
        assert finished.is_set() and calls == [result['agent_session']]
        binding = server._machine_agent_sessions[result['agent_session']]
        assert binding['enrollment_result'] == result
        assert len(server._machine_agent_sessions) == 1
    finally:
        finished.wait(10)
        server.close()
