from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import issue_clean_browser_session
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore


def _map_source() -> bytes:
    return json.dumps(
        [
            {
                "key": "brain",
                "title": "Brain and Memory",
                "nodes": [
                    {
                        "id": "brain_attention",
                        "cat": "behavior",
                        "title": "Persistent Attention",
                        "sub": "Keep accepted work visible across sessions",
                        "status": "partial",
                        "params": [
                            {"k": "mode", "v": "steady"},
                            {"k": "window_ms", "v": "150"},
                        ],
                        "evidence_ref": "court:clean-server-visual-projection",
                        "authority_source": "founder",
                    },
                    {
                        "id": "brain_focus",
                        "cat": "logic",
                        "title": "Focus Contract",
                        "sub": "Carry one live focus through the graph",
                        "status": "partial",
                        "params": [
                            {"k": "selection_policy", "v": "exact"},
                        ],
                        "evidence_ref": "court:clean-server-visual-projection",
                        "authority_source": "founder",
                    },
                ],
                "wires": [
                    ["brain_attention", "brain_focus"],
                ],
                "cross": [
                    {
                        "from": "brain_attention",
                        "to_domain": "ui",
                        "why": "Attention must stay visible in the interface",
                    }
                ],
            },
            {
                "key": "ui",
                "title": "UI and Design System",
                "nodes": [
                    {
                        "id": "ui_properties",
                        "cat": "interface",
                        "title": "Properties Rail",
                        "sub": "Edit graph-held parameters",
                        "status": "partial",
                        "params": [
                            {"k": "tabs", "v": ["Use", "Build", "Govern"]},
                        ],
                        "evidence_ref": "court:clean-server-visual-projection",
                        "authority_source": "founder",
                    }
                ],
                "wires": [],
                "cross": [],
            },
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _provision_clean_runtime(tmp_path):
    root = tmp_path / "clean-server-visual-projection"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-server-visual-projection" + b"0" * 3,
    )
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = _map_source()
    built = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    return built, provider


def _start_clean_server(built, provider):
    return ApplicationServer.from_unified_authority(
        built.location.authority,
        browser_authority=built.browser,
        scope_caller=built.caller,
        scope_root=built.grand_map.root_id,
        authority_key_provider=provider,
    ).start()


def _issue_clean_session(built, *, token: str, csrf: str):
    return issue_clean_browser_session(
        built.location.authority,
        built.browser,
        token=token,
        csrf_token=csrf,
        lifetime_seconds=120.0,
        caller=built.caller,
        command_id=str(uuid.uuid4()),
    )


def _json(url, path, payload=None, *, token: str):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-ArchHub-Session": token,
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_clean_server_canvas_uses_existing_graph_visual_descriptors(tmp_path):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        issued = _issue_clean_session(
            built,
            token="clean-visual-token",
            csrf="clean-visual-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-visual-token",
        )
        assert status == 200
        assert canvas["graph_id"] == built.location.authority.manifest.graph_id
        assert canvas["root"] == built.grand_map.root_id
        assert canvas["revision"] == built.location.authority.store.revision
        assert canvas["authorization"]["browser_sessions"] == [
            {"root": issued.root_id}
        ]
        assert canvas.get("toolbar_descriptor"), (
            "clean canvas must expose the existing toolbar graph descriptor"
        )
        assert canvas.get("canvas_heading_descriptor"), (
            "clean canvas must expose the existing heading graph descriptor"
        )
        assert canvas.get("library", {}).get("descriptor"), (
            "clean canvas must expose the existing library shell descriptor"
        )
        assert canvas.get("primitive", {}).get("descriptor"), (
            "clean canvas must expose the existing primitive descriptor"
        )
        assert canvas.get("catalog_sections"), (
            "clean canvas must expose non-empty library sections"
        )
        assert all(
            section.get("descriptor") for section in canvas["catalog_sections"]
        ), "every clean library section must carry a graph descriptor"
        assert canvas.get("inspector", {}).get("shell_descriptor"), (
            "clean canvas must expose the existing inspector shell descriptor"
        )
        assert canvas.get("inspector", {}).get("header_descriptor"), (
            "clean canvas must expose the existing inspector header descriptor"
        )
        assert canvas.get("inspector", {}).get("controls_descriptor"), (
            "clean canvas must expose the existing inspector controls descriptor"
        )
        assert all(
            node.get("card_descriptor") for node in canvas["nodes"]
        ), "every clean canvas node must carry a graph card descriptor"
        assert any(node["ports"] for node in canvas["nodes"])
        assert all(
            port.get("descriptor")
            for node in canvas["nodes"]
            for port in node["ports"]
        ), "every clean canvas port must carry a graph port descriptor"
        assert all(
            item.get("descriptor") for item in canvas["catalog"]
        ), "every clean catalogue item must carry a graph descriptor"
    finally:
        server.close()
        built.location.authority.store.close()


def test_clean_server_scope_interaction_enters_child_scope_with_same_visual_contract(
    tmp_path,
):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        _issue_clean_session(
            built,
            token="clean-scope-token",
            csrf="clean-scope-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-scope-token",
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        binding = next(
            item
            for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == target["id"]
        )
        status, entered = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": binding["interaction"],
                "control": binding["control"],
                "event": binding["event"],
                "revision": canvas["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token="clean-scope-token",
        )
        assert status == 200
        assert entered["root"] == target["id"], (
            "clean scope interaction must return the selected child scope"
        )
        assert entered["scope"]["current"] == target["id"]
        assert entered.get("toolbar_descriptor")
        assert entered.get("canvas_heading_descriptor")
        assert entered.get("library", {}).get("descriptor")
        assert entered.get("inspector", {}).get("shell_descriptor")
        assert all(
            node.get("card_descriptor") for node in entered["nodes"]
        ), "entered clean scope must keep card descriptors"
    finally:
        server.close()
        built.location.authority.store.close()
