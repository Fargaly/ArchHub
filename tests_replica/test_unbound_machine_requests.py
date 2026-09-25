"""Court: an exactly unbound machine request may read, and may never act.

The authenticated local pipe is reachable by any same-user process. A request
with ``session == {}`` claims no actor. It is admitted only as a GET, resolved
by each route to the founder-local read it always was, and is never admitted
to commit; every other method is refused before ``mutation_lock`` is taken.
35393a5 closed the hole where an unbound caller drove BABOOM commands with the
founder body (restart into a staged build); this court keeps it closed across
every admitted route, not a hand-picked list.

Template: the independent verifier's probe (work/verify-red-courts/logs/probe_unbound.py).
"""
import ast
import pathlib
import threading

import pytest

from nodelang.application_machine_transport import (
    MachineTransportError, UniversalRuntimeClient,
)
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "nodelang" / "application_server.py"

# Routes that authenticate an exactly unbound request themselves (enrollment,
# native recovery, the Desktop-launch browser handoff). They still refuse an
# empty body; they are checked for "no commit", not for the refusal text.
SELF_AUTHENTICATING = {
    ("POST", "/api/universal/agent-session"),
    ("POST", "/api/universal/agent-session-challenge"),
    ("POST", "/api/universal/agent-session-resume"),
    ("POST", "/api/universal/agent-session-reconcile"),
    ("POST", "/api/universal/agent-session-continuation-status"),
    ("POST", "/api/universal/browser-handoff"),
}
# Handing the runtime away is not probed against a live server.
NOT_PROBED = {("POST", "/api/universal/runtime-handoff")}
UNBOUND_REFUSAL = "bound runtime Agent Session is required"
# Any refusal of the missing actor counts; the court is red only if a route acts.
UNBOUND_REFUSALS = (UNBOUND_REFUSAL, "Agent Session proof is invalid", "Agent Session is unknown")


def _admitted():
    text = SOURCE.read_text(encoding="utf-8")
    text = text[text.index("def _dispatch_universal_machine_route("):]
    block = text[text.index("        admitted = {\n"):]
    block = block[:block.index("        }\n") + 10]
    return sorted(ast.literal_eval(block.split("=", 1)[1].strip()))


@pytest.fixture
def served(tmp_path):
    descriptor = tmp_path / "unbound-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"u" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                               machine_key_provider=provider).start()
    try:
        yield server, UniversalRuntimeClient(descriptor, provider)
    finally:
        server.close()


def test_the_admitted_route_table_is_read():
    routes = _admitted()
    assert ("POST", "/api/universal/baboom-command") in routes
    assert ("POST", "/api/universal/grand-map-work") in routes
    assert ("GET", "/api/universal/canvas") in routes


def test_an_unbound_request_never_acts_on_any_admitted_route(served):
    server, client = served
    acted = []
    for method, path in _admitted():
        if method == "GET" or (method, path) in NOT_PROBED:
            continue
        revision = server.universal_store.revision
        try:
            answer = client.request(method, path, {}, response_timeout_seconds=30)
        except MachineTransportError as exc:
            if ((method, path) not in SELF_AUTHENTICATING
                    and not any(text in str(exc) for text in UNBOUND_REFUSALS)):
                acted.append((method, path, "refused by the route, not unbound: %s" % exc))
        else:
            acted.append((method, path, "answered %r" % (answer,)[:120]))
        if server.universal_store.revision != revision:
            acted.append((method, path, "committed revision %d -> %d"
                          % (revision, server.universal_store.revision)))
    assert acted == []


def test_an_unbound_refusal_never_waits_on_the_graph_lock(served):
    server, client = served
    answer = {}

    def command():
        try:
            client.request("POST", "/api/universal/baboom-command", {"utterance": "restart"},
                           response_timeout_seconds=30)
        except MachineTransportError as exc:
            answer["error"] = str(exc)

    worker = threading.Thread(target=command, daemon=True)
    with server.mutation_lock:
        worker.start()
        worker.join(10)
        assert not worker.is_alive(), "the unbound refusal waited on mutation_lock"
    assert UNBOUND_REFUSAL in answer["error"]


@pytest.mark.parametrize("path", ["/api/universal/canvas", "/api/universal/work"])
def test_an_unbound_read_still_answers_without_committing(served, path):
    server, client = served
    revision = server.universal_store.revision
    answer = client.request("GET", path, {}, response_timeout_seconds=60)
    assert answer["agent_session"] == server.universal_registry.agent_body.session.root_id
    assert server.universal_store.revision == revision
