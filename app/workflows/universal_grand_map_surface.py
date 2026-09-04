"""Read-only bridge from the public app slot to Universal Cell authority.

This module is deliberately an adapter, not a new authority. It lets the public
bridge serve a Universal Cell projection through the existing
get_grand_map_ui_surface slot while legacy named surfaces remain intact until
their consumers are ported.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Protocol


RUNTIME_PROJECTION_TIMEOUT_SECONDS = 45.0
ACTIVE_CELL_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
RUNTIME_AUTHORITY_LABEL = "Universal Cell graph runtime"
AUTHORITY_PASSTHROUGH_FIELDS = (
    "agent_session",
    "application",
    "scope",
    "focus",
    "obligations",
    "authoring",
    "selected",
    "selected_title",
    "selected_relation",
    "selected_interface",
    "selected_interfaces",
    "selected_definition",
    "selected_assembly",
    "physical",
    "configuration",
    "interaction_projection",
    "toolbar_descriptor",
    "canvas_heading_descriptor",
    "canvas_signature",
)


class _RuntimeCanvasClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        ...


def _canonical_node_authority_root() -> Path:
    # node-language/ inside this repository first (PR #306); the sibling
    # 13.NODE-LANGUAGE worktree is the founder-workstation fallback.
    repo_root = Path(__file__).resolve().parents[2]
    product_root = Path(__file__).resolve().parents[3]
    candidates = (repo_root / "node-language", product_root / "13.NODE-LANGUAGE")
    root = next((c for c in candidates if (c / "nodelang").is_dir()), None)
    if root is None:
        raise FileNotFoundError(str(candidates[0]))
    return root


def _ensure_authority_path() -> Path:
    root = _canonical_node_authority_root()
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def _active_runtime_client() -> _RuntimeCanvasClient:
    _ensure_authority_path()
    from nodelang.application_machine_transport import (  # type: ignore
        UniversalRuntimeClient,
        default_runtime_descriptor_path,
    )
    from nodelang.cell_secret_keys import (  # type: ignore
        WindowsDpapiSigningKeyProvider,
    )

    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    return UniversalRuntimeClient(default_runtime_descriptor_path(), provider)


def _runtime_canvas(
    runtime_client: _RuntimeCanvasClient | None = None,
) -> dict[str, object]:
    client = runtime_client or _active_runtime_client()
    return client.request(
        "GET",
        "/api/universal/canvas",
        response_timeout_seconds=RUNTIME_PROJECTION_TIMEOUT_SECONDS,
    )


def universal_canvas_interaction(
    payload: dict[str, object],
    *,
    runtime_client: _RuntimeCanvasClient | None = None,
) -> dict[str, Any]:
    """Submit a declared Universal Cell interaction through runtime authority."""
    if type(payload) is not dict:
        return {
            "ok": False,
            "authority": ACTIVE_CELL_AUTHORITY,
            "runtime_authority": RUNTIME_AUTHORITY_LABEL,
            "transport_source": "10.PRODUCT/13.NODE-LANGUAGE",
            "error": "universal interaction payload must be a JSON object",
        }
    client = runtime_client or _active_runtime_client()
    return client.request(
        "POST",
        "/api/universal/interaction",
        payload,
        response_timeout_seconds=RUNTIME_PROJECTION_TIMEOUT_SECONDS,
    )


def universal_grand_map_surface(
    surface: str = "universal-canvas",
    *,
    runtime_client: _RuntimeCanvasClient | None = None,
) -> dict[str, Any]:
    """Return the Universal Cell canvas through the legacy bridge envelope."""
    requested_surface = (surface or "universal-canvas").strip() or "universal-canvas"
    if requested_surface != "universal-canvas":
        return {
            "ok": False,
            "surface": requested_surface,
            "source": "active-universal-runtime",
            "authority": ACTIVE_CELL_AUTHORITY,
            "runtime_authority": RUNTIME_AUTHORITY_LABEL,
            "transport_source": "10.PRODUCT/13.NODE-LANGUAGE",
            "error": "unknown Universal Cell surface",
        }
    projection = _runtime_canvas(runtime_client)
    nodes = []
    for node in projection.get("nodes", []):
        nodes.append({
            "id": node["id"],
            "type": "universal.cell.surface",
            "title": node.get("label") or node["id"],
            "x": node.get("x", 0),
            "y": node.get("y", 0),
            "data": {
                "authority": "Universal Cell",
                "source_cell": node["id"],
                "openable": bool(node.get("openable")),
                "selected": bool(node.get("selected")),
                "member_count": node.get("member_count", 0),
                "connection_count": node.get("connection_count", 0),
                "ports": node.get("ports", []),
                "physical": node.get("physical", {}),
            },
        })
    wires = []
    for wire in projection.get("wires", []):
        wires.append({
            "id": wire["id"],
            "from": {
                "node": wire.get("source"),
                "port": wire.get("source_interface"),
            },
            "to": {
                "node": wire.get("target"),
                "port": wire.get("target_interface"),
            },
            "data": {
                "authority": "Universal Cell",
                "source_incidence": wire.get("source_incidence"),
                "target_incidence": wire.get("target_incidence"),
                "authority_roots": wire.get("authority_roots", []),
                "directed": wire.get("directed", False),
                "nary": wire.get("nary", False),
            },
        })
    payload = {
        "ok": True,
        "surface": requested_surface,
        "source": "active-universal-runtime",
        "authority": ACTIVE_CELL_AUTHORITY,
        "runtime_authority": RUNTIME_AUTHORITY_LABEL,
        "transport_source": "10.PRODUCT/13.NODE-LANGUAGE",
        "authority_projection_keys": sorted(str(key) for key in projection.keys()),
        "root_id": projection["canvas_root"],
        "application_root": projection["application_root"],
        "revision": projection["revision"],
        "nodes": nodes,
        "wires": wires,
        "catalog": projection.get("catalog", []),
        "properties": projection.get("properties", []),
        "selection": projection.get("selection", []),
        "inspector": projection.get("inspector", {}),
        "machine_projection": projection.get("machine_projection", {}),
        "viewport": projection.get("viewport", {}),
    }
    for field in AUTHORITY_PASSTHROUGH_FIELDS:
        if field in projection:
            payload[field] = projection[field]
    return payload
