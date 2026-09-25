"""Court: a founder-private read is the application owner's alone.

Every machine route resolves an unbound read to the founder body. For reads
whose projection is the owner's private state -- briefings, device custody,
the BABOOM context/presence/frame/capabilities, the founder's Workshop and
deliberation views, visibility diagnosis -- that would hand the owner's view
to any same-user process that reaches the pipe. They are served in process
only (the 8316782 pattern for the Brain routes); an unbound pipe read of any
of them is refused before the lock, and non-private reads still answer.
"""
import threading

import pytest

import nodelang.application_server as application_server_module
from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider

PRIVATE = sorted(application_server_module._FOUNDER_PRIVATE_MACHINE_READS)
BODIES = {
    "/api/universal/attention": {"projection": "founder-briefing"},
    "/api/universal/baboom-steward-briefing": {"projection": "founder-briefing"},
    "/api/universal/devices": {"projection": "founder-report"},
}


@pytest.fixture
def served(tmp_path):
    descriptor = tmp_path / "owner-only-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"o" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                               machine_key_provider=provider).start()
    try:
        yield server, UniversalRuntimeClient(descriptor, provider)
    finally:
        server.close()


def test_every_private_read_is_an_admitted_get_route():
    source = application_server_module.__file__
    text = open(source, encoding="utf-8").read()
    for path in PRIVATE:
        assert '("GET", "%s")' % path in text, path


@pytest.mark.parametrize("path", PRIVATE)
def test_an_unbound_pipe_read_of_founder_private_state_is_refused(served, path):
    server, client = served
    revision = server.universal_store.revision
    with pytest.raises(MachineTransportError, match="belongs to the application owner"):
        client.request("GET", path, dict(BODIES.get(path, {})), response_timeout_seconds=30)
    assert server.universal_store.revision == revision


def test_the_refusal_never_waits_on_the_graph_lock(served):
    server, client = served
    answer = {}

    def read():
        try:
            client.request("GET", "/api/universal/baboom-steward-briefing",
                           {"projection": "founder-briefing"}, response_timeout_seconds=30)
        except MachineTransportError as exc:
            answer["error"] = str(exc)

    worker = threading.Thread(target=read, daemon=True)
    with server.mutation_lock:
        worker.start()
        worker.join(10)
        assert not worker.is_alive(), "the owner-only refusal waited on mutation_lock"
    assert "belongs to the application owner" in answer["error"]


def test_the_owner_still_reads_its_private_state_in_process(served):
    server, _client = served
    briefing = server.dispatch_universal_machine_route({
        "method": "GET", "path": "/api/universal/baboom-steward-briefing",
        "body": {"projection": "founder-briefing"}})
    assert briefing["projection"] == "founder-local-baboom-steward-briefing"
    devices = server.dispatch_universal_machine_route({
        "method": "GET", "path": "/api/universal/devices", "body": {"projection": "founder-report"}})
    assert devices["agent_session"] == server.universal_registry.agent_body.session.root_id


@pytest.mark.parametrize("path", ["/api/universal/canvas", "/api/universal/work"])
def test_a_non_private_unbound_read_still_answers(served, path):
    server, client = served
    assert path not in application_server_module._FOUNDER_PRIVATE_MACHINE_READS
    answer = client.request("GET", path, {}, response_timeout_seconds=60)
    assert answer["agent_session"] == server.universal_registry.agent_body.session.root_id
