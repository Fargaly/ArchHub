from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _runtime_baboom_context() -> dict:
    return {
        "cell_native": True,
        "context_lens": "app:baboom-context:v2",
        "revision": 123,
        "work": {
            "total": 6,
            "open": 2,
            "claimed": 1,
            "blocked": 0,
            "review": 0,
        },
        "workshop": {
            "entry_count": 2,
            "category_counts": {"plan": 1, "test": 1},
        },
        "attention": {
            "open_obligations": 3,
            "blocked_obligations": 0,
            "active_focus": True,
        },
        "presence": {
            "active_runtime_sessions": 1,
            "baboom_connected": True,
            "baboom_execution_active": False,
        },
        "device": {
            "enrollment_handoff_available": True,
            "current_runtime_proven": True,
            "active_baboom_devices": 1,
        },
        "suggestion": "Offer the next approved governed work for claim.",
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
        assert body is None
        assert (method, path) == ("GET", "/api/universal/baboom-context")
        return _runtime_baboom_context()


def test_workshop_reads_baboom_from_canonical_graph_context_lens():
    from workflows.baboom_cell_surface import baboom_context_projection

    client = FakeRuntimeClient()
    state = baboom_context_projection(runtime_client=client)

    assert client.calls == [("GET", "/api/universal/baboom-context", None, 3.0)]
    assert state["ok"] is True
    assert state["node_native"] is True
    assert state["mode"] == "canonical-graph-projection"
    assert state["authority"] == "Universal Cell graph runtime"
    assert state["transport_source"] == "10.PRODUCT/13.NODE-LANGUAGE"
    assert state["context_lens"] == "app:baboom-context:v2"
    assert state["root_id"] == "app:baboom-context:v2"
    assert state["work_counts"]["open"] == 2
    assert state["work_total"] == 6
    assert state["workshop"]["entry_count"] == 2
    assert state["presence"]["baboom_connected"] is True
    assert state["device"]["current_runtime_proven"] is True


def test_baboom_surface_does_not_open_a_side_cell_store():
    source = (APP / "workflows" / "baboom_cell_surface.py").read_text(
        encoding="utf-8"
    )

    assert '"/api/universal/baboom-context"' in source
    assert '"/api/universal/work"' not in source
    forbidden = (
        "CellStore",
        "sqlite3",
        "authority.sqlite3",
        "open_baboom_authority",
        "restore_baboom_authority",
    )
    assert [term for term in forbidden if term in source] == []


def test_baboom_surface_imports_transport_from_canonical_node_authority_only():
    from workflows import baboom_cell_surface

    runtime_root = baboom_cell_surface._canonical_node_authority_root()
    # node-language/ inside the repository (main since #306) or the sibling
    # worktree on the founder workstation -- whichever the code itself found.
    expected = next(
        candidate for candidate in (APP.parent / "node-language", APP.parent.parent / "13.NODE-LANGUAGE")
        if (candidate / "nodelang").is_dir()
    )

    assert runtime_root.samefile(expected)
    source = (APP / "workflows" / "baboom_cell_surface.py").read_text(
        encoding="utf-8"
    )
    assert '"13.NODE-LANGUAGE"' in source
    assert '"12.PRODUCTION" / "node_runtime"' not in source


def test_bridge_exposes_runtime_baboom_context_projection():
    import bridge

    class DummyBridge:
        pass

    with patch(
        "workflows.baboom_cell_surface._active_runtime_client",
        return_value=FakeRuntimeClient(),
    ):
        payload = json.loads(
            bridge.ArchHubBridge.get_baboom_context_projection(DummyBridge())
        )

    assert payload["node_native"] is True
    assert payload["mode"] == "canonical-graph-projection"
    assert payload["context_lens"] == "app:baboom-context:v2"
    assert payload["work_counts"]["open"] == 2
    assert payload["source"] == "active-universal-runtime"
