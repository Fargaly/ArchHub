"""Court: reading the ROMA tree never writes the graph.

GET /api/universal/roma-tree with no tree id installed the ROMA requirement
protocol and linked it into the application and Brain scopes (``create=True``)
-- two revisions from a read on an in-memory graph, and "graph commit refused:
no declared intent" on a persistent graph behind the commit gate (verifier,
2026-09-25). Installing it is the sync's work (POST roma-tree); a read on a
graph without ROMA answers an empty index and commits nothing.
"""
import secrets
from pathlib import Path

import pytest

from nodelang import universal_application as app
from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider


def _persistent(tmp_path, monkeypatch, descriptor, provider):
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
        str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    return ApplicationServer(
        universal_state_path=tmp_path / "graph.sqlite3", universal_key_provider=keys,
        universal_workspace_root=tmp_path, enable_machine_transport=True,
        machine_descriptor_path=descriptor, machine_key_provider=provider,
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
        live_watch=False,
    ).start()


@pytest.fixture(params=["in-memory", "persistent"])
def served(request, tmp_path, monkeypatch):
    descriptor = tmp_path / "roma-read-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"R" * 32)
    if request.param == "in-memory":
        server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                                   machine_key_provider=provider).start()
    else:
        server = _persistent(tmp_path, monkeypatch, descriptor, provider)
    try:
        yield server, descriptor, provider
    finally:
        server.close()


def _owner_read(server, body):
    # roma-tree is owner-only over the pipe; the owner reads it in process.
    return server.dispatch_universal_machine_route(
        {"method": "GET", "path": "/api/universal/roma-tree", "body": body})


def test_the_owner_roma_index_read_commits_nothing(served):
    server, descriptor, provider = served
    assert "app:roma-requirement-protocol:root" not in server.universal_store.snapshot().cells
    revision = server.universal_store.revision
    index = _owner_read(server, {})
    assert index["tree_count"] == 0 and index["protocol"] is None
    assert server.universal_store.revision == revision


def test_an_unbound_roma_read_is_refused_without_committing(served):
    server, descriptor, provider = served
    revision = server.universal_store.revision
    with pytest.raises(Exception, match="belongs to the application owner"):
        UniversalRuntimeClient(descriptor, provider).request("GET", "/api/universal/roma-tree", {})
    assert server.universal_store.revision == revision


def test_a_bound_roma_index_read_commits_nothing(served):
    server, descriptor, provider = served
    client = UniversalRuntimeClient(descriptor, provider)
    client.bind_agent_session(runtime="codex", external_session_id="roma-read-court")
    revision = server.universal_store.revision
    index = client.request("GET", "/api/universal/roma-tree", {})
    assert index["tree_count"] == 0
    assert server.universal_store.revision == revision


def test_a_roma_tree_read_without_the_protocol_is_refused_without_committing(served):
    server, descriptor, provider = served
    revision = server.universal_store.revision
    with pytest.raises(Exception, match="not installed"):
        _owner_read(server, {"tree_id": "rt-absent"})
    assert server.universal_store.revision == revision
