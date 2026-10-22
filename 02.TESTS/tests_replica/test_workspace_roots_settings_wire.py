"""Settings -> Workspaces over the REAL wire (founder 2026-10-01 13:20: Add showed
"the ArchHub graph owner is not answering (HTTPError)"). The owner DID answer: its
coordination service sends a refusal as HTTP 400 with {"ok": false, "error": ...},
and urllib raises that as HTTPError, which the forwarder reported as an unreachable
owner and dropped the owner's reason. An HTTP status with a JSON refusal is an
answer; only a missing or unreadable answer is "not answering".

A real CleanCoordinationRequestHandler on an ephemeral loopback port and the real
production transport (_default_graph_context); nothing live is reachable; no key."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.clean_coordination_service import build_bound_service
from tests_replica.test_workspace_roots_graph_current import graph  # noqa: F401

REFUSAL = "the workspace-roots signing key is refused: signing key unavailable: 0x80090022"


def _serve(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return "http://127.0.0.1:%d/coordination" % server.server_address[1]


@pytest.fixture()
def wire(graph, tmp_path, monkeypatch):
    """The production graph context, pointed at a real service over the fixture graph."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(roots, "graph_context", roots._default_graph_context)
    servers = []

    def start(server):
        servers.append(server)
        monkeypatch.setenv("ARCHHUB_COORDINATION_ENDPOINT", _serve(server))
    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_an_owner_refusal_over_http_reaches_the_window_with_its_reason(graph, wire):
    def refuse(body, *, admission):
        assert admission == {"principal": roots.settings_principal()}
        raise roots.WorkspaceRootRefused(REFUSAL)
    graph["owner"]._clean_workspace_roots = refuse
    wire(build_bound_service(graph["host"], port=0))
    with pytest.raises(roots.WorkspaceRootRefused) as refused:
        roots.forward_workspace_settings({"action": "prepare", "change": {"action": "register"}})
    assert str(refused.value) == REFUSAL
    assert "not answering" not in str(refused.value)


def test_an_answer_over_http_still_comes_back(graph, wire):
    def answer(body, *, admission):
        assert admission == {"principal": roots.settings_principal()}
        return {"prepared": {"needs_key": True}}
    graph["owner"]._clean_workspace_roots = answer
    wire(build_bound_service(graph["host"], port=0))
    assert roots.forward_workspace_settings(
        {"action": "prepare", "change": {"action": "register"}}) == {"prepared": {"needs_key": True}}


def test_the_state_over_http_is_the_owners_digest(graph, wire):
    wire(build_bound_service(graph["host"], port=0))
    state = roots.verified_graph_state()
    assert state["graph_id"] == graph["authority"].manifest.graph_id
    assert type(state["revision"]) is int and type(state["registry_digest"]) is str


class _NotJson(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return None

    def do_POST(self):  # noqa: N802
        self.send_response(502)
        self.send_header("Content-Length", "7")
        self.end_headers()
        self.wfile.write(b"gateway")


def test_a_status_without_an_owner_answer_is_still_not_answering(graph, wire):
    wire(ThreadingHTTPServer(("127.0.0.1", 0), _NotJson))
    with pytest.raises(roots.WorkspaceRootRefused, match=r"not answering \(HTTPError\)"):
        roots.forward_workspace_settings({"action": "register"})
