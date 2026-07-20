from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _runtime_canvas_projection() -> dict:
    return {
        "ok": True,
        "agent_session": "agent:founder",
        "application": "app:archhub",
        "canvas_root": "app:canvas",
        "application_root": "app:application",
        "revision": 42,
        "scope": {
            "root": "scope:founder",
            "lifecycle": "WIP",
            "visibility": "founder",
        },
        "nodes": [
            {
                "id": "app:domain:brain",
                "label": "Brain",
                "x": 120,
                "y": 180,
                "openable": True,
                "selected": False,
                "member_count": 24,
                "connection_count": 35,
                "ports": [{"id": "public"}],
                "physical": {
                    "linked": True,
                    "atom_bytes": 0,
                },
            }
        ],
        "wires": [
            {
                "id": "relation:brain-ui",
                "source": "app:domain:brain",
                "source_interface": "public",
                "target": "app:domain:ui",
                "target_interface": "public",
                "source_incidence": "incidence:source",
                "target_incidence": "incidence:target",
                "authority_roots": ["relation:brain-ui"],
                "directed": True,
                "nary": False,
            }
        ],
        "catalog": [{"id": "definition:list"}],
        "properties": [{"id": "property:title"}],
        "selection": [],
        "selected": "app:domain:brain",
        "selected_title": "Brain",
        "inspector": {"lens": "machine-summary"},
        "machine_projection": {
            "kind": "bounded-canvas-summary",
            "node_count": 1,
            "wire_count": 1,
            "node_limit": 96,
            "wire_limit": 192,
        },
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


class FakeRuntimeClient:
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
                "authority": "Universal Cell graph runtime",
                "revision": 43,
                "received": body,
            }
        raise AssertionError((method, path))


def test_universal_canvas_surface_is_sourced_from_universal_cell_authority():
    from workflows.universal_grand_map_surface import universal_grand_map_surface

    client = FakeRuntimeClient()
    payload = universal_grand_map_surface(
        "universal-canvas",
        runtime_client=client,
    )

    assert payload["ok"] is True
    assert payload["surface"] == "universal-canvas"
    assert client.calls == [("GET", "/api/universal/canvas", None, 45.0)]
    assert payload["authority"] == "Universal Cell graph runtime"
    assert payload["transport_source"] == "10.PRODUCT/12.PRODUCTION/node_runtime"
    assert payload["authority_projection_keys"] == sorted(
        _runtime_canvas_projection().keys()
    )
    assert payload["agent_session"] == "agent:founder"
    assert payload["application"] == "app:archhub"
    assert payload["scope"] == {
        "root": "scope:founder",
        "lifecycle": "WIP",
        "visibility": "founder",
    }
    assert payload["selected"] == "app:domain:brain"
    assert payload["selected_title"] == "Brain"
    assert payload["root_id"]
    assert payload["application_root"]
    assert payload["source"] == "active-universal-runtime"
    assert payload["root_id"] == "app:canvas"
    assert len(payload["nodes"]) == 1
    assert payload["wires"]
    assert payload["catalog"]
    assert payload["properties"]
    assert payload["machine_projection"]["kind"] == "bounded-canvas-summary"

    first_node = payload["nodes"][0]
    assert first_node["type"] == "universal.cell.surface"
    assert first_node["data"]["authority"] == "Universal Cell"
    assert first_node["data"]["source_cell"] == first_node["id"]
    assert first_node["data"]["ports"]
    assert set(first_node["data"]["physical"]) == {"linked", "atom_bytes"}

    first_wire = payload["wires"][0]
    assert first_wire["from"]["node"]
    assert first_wire["to"]["node"]
    assert first_wire["from"]["port"]
    assert first_wire["to"]["port"]
    assert first_wire["data"]["source_incidence"]
    assert first_wire["data"]["target_incidence"]
    assert first_wire["data"]["authority_roots"]


def test_universal_canvas_interaction_is_forwarded_to_runtime_authority():
    from workflows.universal_grand_map_surface import universal_canvas_interaction

    client = FakeRuntimeClient()
    payload = {
        "interaction": "interaction:edit-title",
        "control": "control:title",
        "event": "event:input",
        "revision": 42,
        "event_facts": {"value": "Cloud"},
    }

    result = universal_canvas_interaction(payload, runtime_client=client)

    assert result == {
        "ok": True,
        "authority": "Universal Cell graph runtime",
        "revision": 43,
        "received": payload,
    }
    assert client.calls == [
        ("POST", "/api/universal/interaction", payload, 45.0),
    ]


def test_universal_canvas_adapter_does_not_build_or_open_authority():
    source = (
        APP / "workflows" / "universal_grand_map_surface.py"
    ).read_text(encoding="utf-8")

    assert '"/api/universal/canvas"' in source
    assert '"13.NODE-LANGUAGE"' not in source
    forbidden = (
        "build_universal_application",
        "project_universal_canvas",
        "CellStore",
        "sqlite3",
        "restore_baboom_authority",
    )
    assert [term for term in forbidden if term in source] == []


def test_universal_canvas_adapter_imports_transport_from_tracked_node_runtime_only():
    from workflows import universal_grand_map_surface

    runtime_root = universal_grand_map_surface._node_runtime_root()
    expected = APP.parent / "node_runtime"

    assert runtime_root.samefile(expected)


def test_bridge_slot_can_serve_universal_canvas_without_legacy_surface_provider():
    import bridge

    class DummyBridge:
        pass

    with patch(
        "workflows.grand_map_ui.grand_map_ui_surface",
        side_effect=AssertionError("legacy provider must not serve universal-canvas"),
    ), patch(
        "workflows.universal_grand_map_surface._active_runtime_client",
        return_value=FakeRuntimeClient(),
    ):
        raw = bridge.ArchHubBridge.get_grand_map_ui_surface(
            DummyBridge(), "universal-canvas"
        )

    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["surface"] == "universal-canvas"
    assert payload["authority"] == "Universal Cell graph runtime"
    assert payload["transport_source"] == "10.PRODUCT/12.PRODUCTION/node_runtime"
    assert payload["source"] == "active-universal-runtime"
    assert payload["nodes"]
    assert payload["wires"]


def test_bridge_slot_forwards_universal_interaction_without_legacy_mutation():
    import bridge

    class DummyBridge:
        pass

    payload = {
        "interaction": "interaction:edit-title",
        "control": "control:title",
        "event": "event:input",
        "revision": 42,
        "event_facts": {"value": "Cloud"},
    }
    client = FakeRuntimeClient()
    with patch(
        "workflows.universal_grand_map_surface._active_runtime_client",
        return_value=client,
    ):
        raw = bridge.ArchHubBridge.submit_universal_interaction(
            DummyBridge(),
            json.dumps(payload),
        )

    assert json.loads(raw)["received"] == payload
    assert client.calls == [
        ("POST", "/api/universal/interaction", payload, 45.0),
    ]


def test_bridge_slot_rejects_unknown_universal_surface_without_legacy_fallback():
    import bridge

    class DummyBridge:
        pass

    with patch(
        "workflows.grand_map_ui.grand_map_ui_surface",
        side_effect=AssertionError("legacy provider must not serve universal-*"),
    ):
        raw = bridge.ArchHubBridge.get_grand_map_ui_surface(
            DummyBridge(), "universal-future-surface"
        )

    payload = json.loads(raw)
    assert payload == {
        "ok": False,
        "surface": "universal-future-surface",
        "source": "active-universal-runtime",
        "authority": "Universal Cell graph runtime",
        "transport_source": "10.PRODUCT/12.PRODUCTION/node_runtime",
        "error": "unknown Universal Cell surface",
    }
