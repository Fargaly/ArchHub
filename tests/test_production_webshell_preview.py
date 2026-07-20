from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tools.production_webshell_preview import (  # noqa: E402
    BRIDGE_SCRIPT_PATH,
    inject_preview_bridge,
    make_server,
    preview_bridge_source,
)


def _domains(path: Path, domains: list[tuple[str, str, list[dict]]]) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "key": key,
                    "title": title,
                    "nodes": nodes,
                    "wires": [],
                }
                for key, title, nodes in domains
            ]
        ),
        encoding="utf-8",
    )


def _map(path: Path, nodes: list[dict]) -> None:
    _domains(path, [("ui", "UI", nodes)])


def _node(node_id: str, title: str, status: str = "partial") -> dict:
    return {"id": node_id, "title": title, "status": status}


def _read(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read()


def _post_json(url: str, payload: dict) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read()


def _runtime_canvas_projection() -> dict:
    return {
        "ok": True,
        "canvas_root": "app:canvas",
        "application_root": "app:application",
        "revision": 7,
        "nodes": [
            {
                "id": "app:domain:ui",
                "label": "UI",
                "x": 100,
                "y": 120,
                "openable": True,
                "selected": False,
                "member_count": 12,
                "connection_count": 18,
                "ports": [{"id": "public"}],
                "physical": {"link0": "cell:a", "link1": "cell:b", "atom_bytes": 0},
            }
        ],
        "wires": [
            {
                "id": "relation:ui-brain",
                "source": "app:domain:ui",
                "source_interface": "public",
                "target": "app:domain:brain",
                "target_interface": "public",
                "source_incidence": "incidence:source",
                "target_incidence": "incidence:target",
                "authority_roots": ["relation:ui-brain"],
                "directed": True,
                "nary": False,
            }
        ],
        "catalog": [{"id": "definition:value"}],
        "properties": [{"id": "property:title"}],
        "selection": [],
        "inspector": {"presentation": {"panels": []}},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


class _FakeRuntimeClient:
    def __init__(self) -> None:
        self.calls = []

    def request(
        self,
        method: str,
        path: str,
        body=None,
        *,
        response_timeout_seconds=None,
    ) -> dict:
        self.calls.append((method, path, body, response_timeout_seconds))
        if (method, path) == ("GET", "/api/universal/canvas"):
            assert body is None
            return _runtime_canvas_projection()
        if (method, path) == ("POST", "/api/universal/interaction"):
            assert type(body) is dict
            return {
                "ok": True,
                "authority": "10.PRODUCT/13.NODE-LANGUAGE",
                "revision": 8,
                "received": body,
            }
        raise AssertionError((method, path))


def test_preview_bridge_is_injected_after_qwebchannel_boot():
    html = "<script>window.bridgeJson = async () => null;</script><script src=\"vendor/react.production.min.js\"></script>"

    injected = inject_preview_bridge(html)

    assert f'<script src="{BRIDGE_SCRIPT_PATH}"></script>' in injected
    assert injected.index(BRIDGE_SCRIPT_PATH) > injected.index("window.bridgeJson")
    assert injected.index(BRIDGE_SCRIPT_PATH) < injected.index("vendor/react.production.min.js")


def test_preview_bridge_source_exposes_qwebchannel_compatible_archhub():
    src = preview_bridge_source()

    assert "get_grand_map_ui_surface" in src
    assert "get_node_grammar" in src
    assert "/__archhub/grand-map-ui-surface" in src
    assert "/__archhub/node-grammar" in src
    assert "get_grand_map_ui_surface: function(surface, done)" in src
    assert "get_node_grammar: function(done)" in src
    assert "if (typeof done === 'function') done(text)" in src
    assert "window.archhubReady = Promise.resolve(window.archhub)" in src
    assert "JSON.stringify(payload)" in src


def test_preview_server_returns_real_grand_map_surface(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _map(
        grand_map,
        [
            _node("ui_design_tokens", "Design Tokens"),
            _node("ui_account_chip", "Account Chip"),
            _node("ui_composer_bar", "Composer Bar"),
            _node("ui_command_palette", "Command Palette"),
        ],
    )

    server = make_server(
        host="127.0.0.1",
        port=0,
        web_ui_dir=ROOT / "app" / "web_ui",
        grand_map_path=grand_map,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        payload = json.loads(
            _read(base + "/__archhub/grand-map-ui-surface?surface=home-top").decode("utf-8")
        )
        html = _read(base + "/").decode("utf-8")
        bridge = _read(base + BRIDGE_SCRIPT_PATH).decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert payload["ok"] is True
    assert payload["root_id"] == "ui:grandmap:home-top"
    assert payload["source"] == str(grand_map)
    assert payload["source_node_ids"] == [
        "ui_design_tokens",
        "ui_account_chip",
        "ui_composer_bar",
        "ui_command_palette",
    ]
    assert '<script src="/__archhub_preview_bridge.js"></script>' in html
    assert "get_grand_map_ui_surface" in bridge


def test_preview_server_returns_canvas_node_card_surfaces_from_authority(tmp_path):
    grand_map = tmp_path / "grand_domains.json"
    _domains(
        grand_map,
        [
            ("ui", "UI", [_node("ui_node_card", "Node Card")]),
            ("canvas", "Canvas", [_node("canvas_node_view", "Canvas Node View")]),
        ],
    )

    server = make_server(
        host="127.0.0.1",
        port=0,
        web_ui_dir=ROOT / "app" / "web_ui",
        grand_map_path=grand_map,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        payloads = {
            surface: json.loads(
                _read(
                    base + "/__archhub/grand-map-ui-surface?surface=" + surface
                ).decode("utf-8")
            )
            for surface in (
                "canvas-node-card",
                "canvas-node-card-header",
                "canvas-node-card-body",
            )
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    for surface, payload in payloads.items():
        assert payload["ok"] is True
        assert payload["surface"] == surface
        assert payload["root_id"] == f"ui:grandmap:{surface}"
        assert payload["source"] == str(grand_map)
        assert payload["source_node_ids"] == ["ui_node_card", "canvas_node_view"]
        assert payload["nodes"]
        assert payload["wires"]


def test_preview_server_routes_universal_canvas_to_universal_cell_authority():
    client = _FakeRuntimeClient()
    with patch(
        "workflows.universal_grand_map_surface._active_runtime_client",
        return_value=client,
    ):
        server = make_server(
            host="127.0.0.1",
            port=0,
            web_ui_dir=ROOT / "app" / "web_ui",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = json.loads(
                _read(
                    base + "/__archhub/grand-map-ui-surface?surface=universal-canvas"
                ).decode("utf-8")
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    assert payload["ok"] is True
    assert payload["surface"] == "universal-canvas"
    assert client.calls == [("GET", "/api/universal/canvas", None, 45.0)]
    assert payload["authority"] == "10.PRODUCT/13.NODE-LANGUAGE"
    assert payload["application_root"]
    assert payload["root_id"]
    assert payload["nodes"]
    assert payload["wires"]
    assert payload["catalog"]
    assert payload["properties"]
    assert payload["wires"][0]["data"]["source_incidence"]
    assert payload["wires"][0]["data"]["target_incidence"]


def test_preview_server_forwards_universal_interaction_to_cell_authority():
    client = _FakeRuntimeClient()
    with patch(
        "workflows.universal_grand_map_surface._active_runtime_client",
        return_value=client,
    ):
        server = make_server(
            host="127.0.0.1",
            port=0,
            web_ui_dir=ROOT / "app" / "web_ui",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            body = {
                "interaction": "interaction:edit-title",
                "control": "control:title",
                "event": "event:input",
                "revision": 7,
                "event_facts": {"value": "Cloud"},
            }
            payload = json.loads(
                _post_json(
                    base + "/__archhub/universal-interaction",
                    body,
                ).decode("utf-8")
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    assert payload == {
        "ok": True,
        "authority": "10.PRODUCT/13.NODE-LANGUAGE",
        "revision": 8,
        "received": body,
    }
    assert client.calls == [
        ("POST", "/api/universal/interaction", body, 45.0),
    ]


def test_preview_server_returns_real_node_grammar():
    server = make_server(
        host="127.0.0.1",
        port=0,
        web_ui_dir=ROOT / "app" / "web_ui",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        payload = json.loads(_read(base + "/__archhub/node-grammar").decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert isinstance(payload, list)
    assert payload
    assert {
        "kind",
        "display",
        "cat",
        "ports",
        "params",
        "legacy_migration_only",
        "authority_status",
        "active_authority",
        "promotion_allowed",
    } <= set(payload[0])
    assert payload[0]["legacy_migration_only"] is True
    assert payload[0]["authority_status"] == "superseded_by_universal_cell"
    assert payload[0]["active_authority"] == "10.PRODUCT/13.NODE-LANGUAGE"
    assert payload[0]["promotion_allowed"] is False
    assert any(entry.get("params") for entry in payload)
