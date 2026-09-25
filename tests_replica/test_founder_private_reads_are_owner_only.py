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
from tests_replica.test_baboom_native_frame_lock_hold import enrolled  # noqa: F401  (fixture)

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


def test_the_owner_still_reads_its_project_content_in_process(served):
    server, _client = served
    for path in ("/api/universal/canvas", "/api/universal/work",
                 "/api/universal/workshop-assignments", "/api/universal/grand-map-work",
                 "/api/universal/roma-tree"):
        answer = server.dispatch_universal_machine_route(
            {"method": "GET", "path": path, "body": {}})
        assert type(answer) is dict, path


# The unbound GETs that stay open (reasons beside _FOUNDER_PRIVATE_MACHINE_READS).
OPEN = frozenset({
    "/api/universal/providers", "/api/universal/hosts", "/api/universal/models",
    "/api/universal/mcp-broker", "/api/universal/runtime-backend",
    "/api/universal/runtime-handoff-readiness", "/api/universal/browser-handoff",
})
BOUND_ONLY = frozenset({
    "/api/universal/work-current", "/api/universal/work-claim-transfer",
    "/api/universal/work-handoff",
})


def test_every_admitted_get_is_classified_private_open_or_bound():
    import re
    text = open(application_server_module.__file__, encoding="utf-8").read()
    admitted = set(re.findall(r'\("GET", "(/api/universal/[a-z0-9/_-]+)"\)', text))
    classified = set(PRIVATE) | OPEN | BOUND_ONLY
    assert admitted == classified, sorted(admitted ^ classified)
    assert not set(PRIVATE) & OPEN


@pytest.mark.parametrize("path", ["/api/universal/runtime-backend", "/api/universal/browser-handoff"])
def test_an_open_unbound_read_still_answers(served, path):
    server, client = served
    assert path not in application_server_module._FOUNDER_PRIVATE_MACHINE_READS
    revision = server.universal_store.revision
    answer = client.request("GET", path, {}, response_timeout_seconds=60)
    assert answer["application"] == server.universal_registry.application_root
    assert server.universal_store.revision == revision


def test_a_bound_baboom_session_still_reads_canvas_and_work(enrolled):
    server, baboom = enrolled
    revision = server.universal_store.revision
    canvas = baboom.request("GET", "/api/universal/canvas", {}, response_timeout_seconds=60)
    work = baboom.request("GET", "/api/universal/work", {}, response_timeout_seconds=60)
    assert canvas["agent_session"] == work["agent_session"] == baboom.agent_session_root
    assert server.universal_store.revision == revision
