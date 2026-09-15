"""The released legacy HTTP journey, with one disposable PUBLIC instance."""
import json
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang import universal_application as app
from nodelang.universal_cell import InvalidCell
from nodelang.universal_graphs import project_graph_index


def test_fresh_public_http_create_place_open_and_reopen(tmp_path, monkeypatch):
    public_map = Path(app.__file__).parent / "data/public_runtime_map.json"
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(public_map))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    database = tmp_path / "public-application.sqlite3"

    def start():
        return ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False).start()

    def request(path, body=None, expected=200):
        call = Request(server.url + path, headers={"Content-Type": "application/json",
            "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=30) as response:
                status, result = response.status, json.loads(response.read())
        except HTTPError as exc:
            status, result = exc.code, json.loads(exc.read())
        assert status == expected, result
        if expected == 200:
            assert result.get("ok") is not False, result
        return result

    server = start()
    try:
        initial = request("/api/universal/graphs")
        application_root = initial["canvas"]["application_root"]
        canvas_root = server.universal_registry.canvas_root
        assert initial["current_graph"] == canvas_root
        before_nodes = {node["id"] for node in initial["canvas"]["nodes"]}
        created = request("/api/universal/graph-create", {"title": "My first graph"})
        graph = created["graph"]["id"]
        assert graph != canvas_root
        assert created["current_graph"] == graph
        assert created["canvas"]["application_root"] == application_root
        assert created["canvas"]["scope"]["current"] == graph
        assert created["canvas"]["nodes"] == []
        assert created["canvas"]["wires"] == []
        node = request("/api/universal/node-create", {"title": "My Think",
            "engine": "library.think", "params": {}, "x": 240, "y": 200})["root"]
        inside = request("/api/universal/canvas")
        assert {item["id"] for item in inside["nodes"]} == {node}
        assert inside["application_root"] == application_root
        assert next(row["value"] for row in inside["properties"]
                    if row["owner"] == node and row["label"] == "model") == ""
        top = request("/api/universal/graph-open", {"root": canvas_root})
        assert {item["id"] for item in top["canvas"]["nodes"]} == before_nodes | {graph}
        request("/api/universal/graph-open", {"root": graph})
        revision = server.universal_store.revision
        request("/api/universal/graph-open", {"root": node}, expected=400)
        assert server.universal_store.revision == revision
        request("/api/universal/graph-create", {"title": ""}, expected=400)
        assert server.universal_store.revision == revision
    finally:
        server.close()

    server = start()
    try:
        reopened = request("/api/universal/graphs")
        assert reopened["canvas"]["application_root"] == application_root
        assert reopened["current_graph"] == graph
        assert next(row["title"] for row in reopened["graphs"] if row["id"] == graph) == "My first graph"
        assert {item["id"] for item in reopened["canvas"]["nodes"]} == {node}
        # A raw stored composition is insufficient after its actual signed
        # read grant is revoked. No alternate graph-list owner may reveal it.
        grant = next(row for row in reopened["canvas"]["authorization"]["relationships"]
            if row["kind"] == "delegation" and row["scope"] == graph
            and row["state"] == "active")
        app.revoke_universal_authority_relationship(server.universal_store,
            server.universal_registry, grant["root"], reason="Public fixture access withdrawn")
        with pytest.raises(InvalidCell, match="signed.*grants"):
            project_graph_index(server.universal_store, server.universal_registry)
    finally:
        server.close()
