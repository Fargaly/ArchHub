"""The public door admits claude.ai and ChatGPT by their metadata documents, and xAI by a bearer header.

A Client ID Metadata Document is fetched only for those hosts. The founder mints
the xAI bearer with his account token; that bearer lists the gated desktop
effects, and host.exec is queued as host-effect for the outbound relay.

Run: python -m pytest cloud_backend/tests/test_remote_agent_door.py -q
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time

import pytest

FOUNDER = "founder.desktop@example.test"
STRANGER = "someone.else@studio.example"
CLAUDE = "https://claude.ai/.well-known/oauth-client"
CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
EFFECTS = {"canvas.run", "host.exec", "connector.call"}


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "6")
    return TestClient(main.app, raise_server_exceptions=False, follow_redirects=False,
                      base_url="https://testserver")


def _token(email: str) -> str:
    import db
    return db.issue_token(db.get_or_create_user(email)["id"])


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _rpc(client, method, params=None, token=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    response = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    data = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    return response.status_code, (json.loads(data[0]) if data else {})


def _listed(client, token):
    status, body = _rpc(client, "tools/list", token=token)
    assert status == 200, body
    return [tool["name"] for tool in body["result"]["tools"]]


def _authorize(client, client_id, redirect):
    _verifier, challenge = _pkce()
    return client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st-1",
        "scope": "mcp:read mcp:workshop", "resource": "https://api.archhub.io/mcp"})


def test_discovery_advertises_client_metadata_documents_and_header_bearers(client):
    meta = client.get("/.well-known/oauth-authorization-server")
    assert meta.status_code == 200
    body = meta.json()
    assert body["client_id_metadata_document_supported"] is True
    assert body["bearer_methods_supported"] == ["header"]
    resource = client.get("/.well-known/oauth-protected-resource")
    assert resource.json()["bearer_methods_supported"] == ["header"]


def test_an_unpinned_metadata_host_is_never_fetched(client, monkeypatch):
    import oauth_mcp

    def fetched(url):
        raise AssertionError("fetched %s" % url)

    monkeypatch.setattr(oauth_mcp, "fetch_cimd", fetched)
    response = _authorize(client, "https://evil.example/client.json", "https://evil.example/cb")
    assert response.status_code == 400
    assert "unknown client" in response.text


def test_claude_ai_is_named_on_the_consent_page_from_its_metadata_document(client, monkeypatch):
    import oauth_mcp
    document = {
        "client_id": CLAUDE,
        "client_name": "Claude",
        "redirect_uris": [CLAUDE_REDIRECT],
        "token_endpoint_auth_method": "none",
    }
    monkeypatch.setattr(oauth_mcp, "fetch_cimd", lambda url: json.dumps(document))
    response = _authorize(client, CLAUDE, CLAUDE_REDIRECT)
    assert response.status_code == 200, response.text
    assert "Claude" in response.text
    assert "claude.ai" in response.text


def test_the_founder_mints_an_xai_bearer_and_a_stranger_cannot(client):
    minted = client.post("/oauth/bearer", headers={"Authorization": "Bearer " + _token(FOUNDER)})
    assert minted.status_code == 200, minted.text
    token = minted.json()["access_token"]
    assert token.startswith("ah_mcp_at_")
    assert EFFECTS <= set(_listed(client, token))
    refused = client.post("/oauth/bearer", headers={"Authorization": "Bearer " + _token(STRANGER)})
    assert refused.status_code == 403


def test_host_exec_is_queued_as_a_host_effect_for_the_desktop(client):
    minted = client.post("/oauth/bearer", headers={"Authorization": "Bearer " + _token(FOUNDER)})
    token = minted.json()["access_token"]
    seen = {}

    def play():
        import config
        import db
        for _ in range(25):
            time.sleep(0.2)
            task = db.claim_next_agent_task(claimed_by="archhub-app", kinds=("host-effect",),
                                            creators=config.founder_emails())
            if task:
                seen["task"] = task
                db.finish_agent_task(task["id"], ok=True, result=json.dumps({"ok": True, "held": False}))
                return

    thread = threading.Thread(target=play, daemon=True)
    thread.start()
    status, body = _rpc(client, "tools/call", {
        "name": "host.exec",
        "arguments": {"engine": "revit.info", "params": {"view": "plan"}, "extra": "dropped"},
    }, token)
    thread.join(timeout=10)
    assert status == 200 and "error" not in body, body
    task = seen["task"]
    assert task["kind"] == "host-effect"
    directive = json.loads(task["directive"])
    assert directive["tool"] == "host.exec"
    assert directive["args"]["engine"] == "revit.info"
    assert "extra" not in directive["args"]
    assert token not in task["directive"]
