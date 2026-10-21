"""UPD3 GR: Studio authority's gesture Undo/Redo reaches both real HTTP owners."""
from pathlib import Path
import secrets
import uuid

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session, _json, _provision_clean_runtime, _start_clean_server,
)


@pytest.fixture(params=("existing", "clean"))
def owner(request, tmp_path, monkeypatch):
    if request.param == "clean":
        built, provider = _provision_clean_runtime(tmp_path)
        server = _start_clean_server(built, provider)
        token, csrf = "upd3-gr-token", "upd3-gr-csrf"
        _issue_clean_session(built, token=token, csrf=csrf)
        store = built.location.authority.store
    else:
        from nodelang import universal_application
        monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(
            Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
        keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
        keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
        server = ApplicationServer(
            universal_state_path=tmp_path / "app.sqlite3", universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False).start()
        token, csrf = server.browser_session_token, server.browser_csrf_token
        store = server.universal_store

    def command(path, body=None):
        return _json(server.url, path, body, token=token, csrf=csrf)

    try:
        yield request.param, command, store
    finally:
        server.close()
        if request.param == "clean":
            store.close()


def _activation(canvas, control):
    binding = next(row for row in canvas["interaction_projection"]["bindings"]
                   if row["control"] == control)
    return {"control": control, "interaction": binding["interaction"],
            "event": binding["event"], "revision": canvas["interaction_projection"]["revision"]}


def _group(canvas, root):
    return next(node for node in canvas["nodes"] if node["id"] == root)


def test_member_drag_out_then_gesture_undo_redo_repaints_and_hides_member(owner):
    kind, command, store = owner
    status, canvas = command("/api/universal/canvas")
    assert status == 200, canvas
    roots = [node["id"] for node in canvas["nodes"][:2]]
    assert len(roots) == 2
    scope = canvas["scope"]["current"]
    status, selected = command("/api/universal/gesture", {
        "roots": roots, "focus": roots[-1], "expected_scope": scope,
    })
    assert status == 200, selected
    status, grouped = command("/api/universal/interaction", _activation(
        selected, "app:control:canvas:group"))
    assert status == 200, grouped
    group = next(node["id"] for node in grouped["nodes"]
                 if node.get("composition") and node.get("member_count") == 2)
    assert roots[0] not in {node["id"] for node in grouped["nodes"]}

    membership = {"member": roots[0], "from_group": group, "to_group": "",
                  "position": {"x": 123, "y": 456}}
    if kind == "existing":
        body = _activation(grouped, "app:control:canvas:remove-member")
        body.update(membership=membership, expected_scope=scope, command_id=str(uuid.uuid4()))
        status, removed = command("/api/universal/interaction", body)
    else:
        status, removed = command("/api/universal/gesture", {
            "membership": membership, "expected_scope": scope,
        })
    assert status == 200, removed
    assert _group(removed, group)["member_count"] == 1
    assert roots[0] in {node["id"] for node in removed["nodes"]}

    # History commands cannot consume a different scope or another edit.
    before = store.revision
    for body in (
        {"undo": True, "expected_scope": "wrong-scope"},
        {"undo": True, "redo": True, "expected_scope": scope},
        {"undo": True, "roots": [], "expected_scope": scope},
        {"undo": True, "membership": membership, "expected_scope": scope},
    ):
        status, refused = command("/api/universal/gesture", body)
        assert status != 200 and refused["ok"] is False, refused
        assert store.revision == before, "a refused history gesture changed the graph"

    for direction, expected_count, member_visible in (
        ("undo", 2, False), ("redo", 1, True), ("undo", 2, False),
    ):
        status, changed = command("/api/universal/gesture", {
            direction: True, "expected_scope": scope,
        })
        assert status == 200, (direction, changed)
        assert _group(changed, group)["member_count"] == expected_count
        assert (roots[0] in {node["id"] for node in changed["nodes"]}) is member_visible
        assert changed["action_history"]["can_redo"] is (direction == "undo")
        # The next viewport delta must carry the same history state before
        # any full refresh; otherwise Studio loses its enabled Redo button.
        status, delta = command("/api/universal/gesture", {
            "expected_scope": scope,
            "viewport": {**changed["viewport"], "pan_x": changed["viewport"]["pan_x"] + 1},
            "projection_mode": "interaction-delta-v1",
            "projection_revision": changed["revision"],
        })
        assert status == 200, delta
        assert delta["projection_mode"] == "interaction-delta-v1", delta
        assert delta["action_history"] == changed["action_history"]
        status, readback = command("/api/universal/canvas")
        assert status == 200, readback
        assert _group(readback, group)["member_count"] == expected_count
        assert (roots[0] in {node["id"] for node in readback["nodes"]}) is member_visible
