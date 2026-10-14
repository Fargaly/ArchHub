"""UPD2 p9: two-root gesture replies are read from both real HTTP owners."""
import json
import secrets
from pathlib import Path
from urllib.parse import urlencode

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session, _json, _provision_clean_runtime, _start_clean_server,
)


def _select_two(server, token, csrf):
    status, canvas = _json(server.url, "/api/universal/canvas", token=token)
    assert status == 200, canvas
    roots = [node["id"] for node in canvas["nodes"][:2]]
    assert len(roots) == 2
    status, answer = _json(server.url, "/api/universal/gesture", {
        "roots": roots, "focus": roots[-1], "expected_scope": canvas["scope"]["current"],
    }, token=token, csrf=csrf)
    assert status == 200, answer
    # The full reply of both owners must carry the committed selection. This
    # catches a primary-only response without inferring it from the request.
    assert set(answer["selection"]) == set(roots)
    assert answer["selected"] == roots[-1]
    assert [node["id"] for node in answer["nodes"] if node["selected"]] == roots
    status, readback = _json(server.url, "/api/universal/canvas", token=token)
    assert status == 200, readback
    assert [node["id"] for node in readback["nodes"] if node["selected"]] == roots
    return canvas


def test_existing_server_gesture_two_roots_and_graph_chat_reply(tmp_path, monkeypatch):
    from nodelang import agent_composer, pipeline_engines, universal_application

    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(
        Path(universal_application.__file__).parent / "data" / "public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda *args: ({"out": ""}, ""))
    calls = []

    def provider(prompt, context_block, model, **kwargs):
        calls.append(prompt)
        return json.dumps({"actions": [], "answer": "p9 graph reply"})

    monkeypatch.setattr(agent_composer, "_chat", provider)
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    def start():
        return ApplicationServer(universal_state_path=tmp_path / "app.sqlite3", universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False).start()

    server = start()
    try:
        token, csrf = server.browser_session_token, server.browser_csrf_token
        canvas = _select_two(server, token, csrf)
        scope = canvas["scope"]["current"]
        status, cleared = _json(server.url, "/api/universal/gesture", {
            "roots": [], "focus": None, "expected_scope": scope,
        }, token=token, csrf=csrf)
        assert status == 200, cleared
        assert cleared["selection"] == []
        # Empty roots clear selection but the gesture protocol retains primary
        # focus when focus is null. Graph sends name their graph context explicitly.
        assert cleared["selected"] == canvas["nodes"][1]["id"]
        assert all(not node["selected"] for node in cleared["nodes"])
        status, answer = _json(server.url, "/api/universal/agent", {
            "prompt": "p9 ordinary graph send", "model": "court/free",
            "graph": True, "graph_id": canvas["scope"]["current"], "request_id": "p9-chat",
        }, token=token, csrf=csrf)
        assert status == 200, answer
        assert answer["answer"] == "p9 graph reply"
        assert answer["delivery"]["state"] == "replied"
        assert calls == ["p9 ordinary graph send"]
        transcript_path = "/api/universal/workshop-transcript?" + urlencode({
            "node": "graph:" + scope, "scope": scope,
        })
        status, transcript = _json(server.url, transcript_path, token=token)
        assert status == 200, transcript
        assert transcript["node"] == "graph:" + scope
        assert [(row["kind"], row["text"]) for row in transcript["rows"]] == [
            ("message", "p9 ordinary graph send"), ("reply", "p9 graph reply"),
        ]
        assert answer["delivery"]["message_id"] == transcript["rows"][0]["id"]
        assert answer["delivery"]["reply_message_id"] == transcript["rows"][1]["id"]
        status, reopened_graph = _json(server.url, "/api/universal/graph-open", {
            "root": scope,
        }, token=token, csrf=csrf)
        assert status == 200, reopened_graph
        assert reopened_graph["canvas"]["scope"]["current"] == scope
        status, reopened_transcript = _json(server.url, transcript_path, token=token)
        assert status == 200, reopened_transcript
        assert reopened_transcript["node"] == transcript["node"]
        assert reopened_transcript["conversation_root"] == transcript["conversation_root"]
        assert reopened_transcript["rows"] == transcript["rows"]
        assert calls == ["p9 ordinary graph send"], "graph reopen never calls the provider again"
    finally:
        server.close()

    # A second real HTTP owner reopens the saved SQLite graph/content. Nothing
    # depends on the first browser's local turn cache or a fake transcript store.
    server = start()
    try:
        token = server.browser_session_token
        status, durable = _json(server.url, transcript_path, token=token)
        assert status == 200, durable
        assert durable["node"] == transcript["node"]
        assert durable["conversation_root"] == transcript["conversation_root"]
        assert durable["rows"] == transcript["rows"]
        assert calls == ["p9 ordinary graph send"]
    finally:
        server.close()


def test_clean_server_gesture_two_root_reply(tmp_path):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        token, csrf = "p9-gesture-token", "p9-gesture-csrf"
        _issue_clean_session(built, token=token, csrf=csrf)
        _select_two(server, token, csrf)
    finally:
        server.close()
        built.location.authority.store.close()
