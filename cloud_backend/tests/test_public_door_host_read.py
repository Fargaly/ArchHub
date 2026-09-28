"""The public door: one MCP address reads the founder's desktop, and only his.

api.archhub.io/mcp served the account's brain. It now also lists the founder's
host tools -- to his accounts alone -- and answers a live one by queueing a
host-read task that his running application claims over the existing outbound
relay (nodelang/cloud_relay.py) and answers with its own allowlisted read
function. These courts play the application's side over the real queue.

Run: python -m pytest cloud_backend/tests/test_public_door_host_read.py -q
"""
from __future__ import annotations

import json
import threading
import time

import pytest

FOUNDER = "founder.desktop@example.test"
STRANGER = "someone.else@studio.example"
BRAIN = ["brain.health", "brain.search", "brain.list_facts"]
HOST = {"hosts.state", "hosts.status", "revit.sessions", "connector.rows",
        "office.read", "outlook.inbox", "dropbox.list"}
EFFECT_WORDS = ("exec", "screenshot", "send", "write", "draft", "categorize", "delete")


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "6")
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _map_files(tmp_path, monkeypatch):
    """The pushed map lives in a per-test dir, never the dev box's own."""
    import config
    import founder_cockpit
    body = tmp_path / "founder-map.json"
    monkeypatch.setattr(config, "FOUNDER_MAP_STATE", body)
    monkeypatch.setattr(config, "FOUNDER_MAP_PUSHED_AT", tmp_path / "founder-map.pushed-at.json")
    monkeypatch.setattr(founder_cockpit, "_MAP_STATE", body)


def _token(email: str) -> str:
    import db
    return db.issue_token(db.get_or_create_user(email)["id"])


def _rpc(client, method, params=None, token=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    r = client.post("/mcp", headers=headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    data = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    return r.status_code, (json.loads(data[0]) if data else {})


def _listed(client, token=None):
    status, body = _rpc(client, "tools/list", token=token)
    assert status == 200
    return [tool["name"] for tool in body["result"]["tools"]]


def _call(client, token, name, arguments=None):
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, token)


def _play_the_desktop(answer, *, ok=True, delay=0.2):
    """The founder's running application: claim the next host read, answer it."""
    seen = {}

    def run():
        import config
        import db
        for _ in range(25):
            time.sleep(delay)
            task = db.claim_next_agent_task(claimed_by="archhub-app", kinds=("host-read",),
                                            creators=config.founder_emails())
            if task:
                seen["task"] = task
                db.finish_agent_task(task["id"], ok=ok,
                                     result=json.dumps(answer) if ok else answer)
                return
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return seen, thread


def test_only_the_founder_sees_or_calls_his_desktop_tools(client):
    """A stranger's token and no token list the brain alone; a stranger's call
    is an unknown tool and queues nothing; an unsigned call is refused."""
    assert HOST <= set(_listed(client, _token(FOUNDER)))
    assert _listed(client, _token(STRANGER)) == BRAIN
    assert _listed(client) == BRAIN
    status, body = _call(client, _token(STRANGER), "hosts.status")
    assert status == 200 and body["error"]["message"] == "unknown tool"
    assert _call(client, None, "hosts.status")[0] == 401
    import db
    assert db.count_agent_tasks() == 0


def test_no_listed_tool_has_an_effect(client):
    names = _listed(client, _token(FOUNDER))
    assert len(names) > len(BRAIN), "the founder's host group is missing"
    assert [n for n in names if any(word in n for word in EFFECT_WORDS)] == []


def test_a_live_read_is_answered_by_the_founders_desktop(client, caplog):
    token = _token(FOUNDER)
    rows = {"ok": True, "out": [{"subject": "Tender addendum", "unread": True}],
            "label": "1 inbox item(s)"}
    seen, thread = _play_the_desktop(rows)
    status, body = _call(client, token, "outlook.inbox", {"count": 500, "folder": "Sent"})
    thread.join(timeout=10)
    assert status == 200 and "error" not in body, body
    assert json.loads(body["result"]["content"][0]["text"]) == rows
    task = seen["task"]
    assert task["kind"] == "host-read" and task["created_by"] == FOUNDER
    # Only the declared, bounded arguments travel; the token never does.
    assert json.loads(task["directive"]) == {"tool": "outlook.inbox", "args": {"count": 50}}
    import db
    with db.connect() as con:
        stored = json.dumps([dict(r) for r in con.execute("SELECT * FROM agent_tasks")])
    assert token not in stored and token not in caplog.text


def test_a_refused_read_is_an_error_not_data(client):
    seen, thread = _play_the_desktop("PermissionError: not a remote read: 'max.exec'", ok=False)
    status, body = _call(client, _token(FOUNDER), "hosts.status")
    thread.join(timeout=10)
    assert body["result"]["isError"] is True
    assert "refused" in body["result"]["content"][0]["text"]


def test_an_offline_desktop_is_reported_within_the_wait_and_never_replayed(client, monkeypatch):
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "0.6")
    started = time.monotonic()
    status, body = _call(client, _token(FOUNDER), "dropbox.list", {"path": "P-603"})
    assert time.monotonic() - started < 5
    assert body["result"]["isError"] is True
    assert "device_offline" in body["result"]["content"][0]["text"]
    import config
    import db
    # The row is closed: an app that starts later finds nothing to run.
    assert db.claim_next_agent_task(claimed_by="archhub-app", kinds=("host-read",),
                                    creators=config.founder_emails()) is None
    assert [task["status"] for task in db.list_agent_tasks()] == ["failed"]


def test_host_state_answers_from_the_published_snapshot_without_waking_the_desktop(client):
    hosts = [{"id": "revit", "name": "Revit 2025", "state": "live", "detail": "P-603.rvt"}]
    r = client.post("/founder/map-state", headers={"Authorization": "Bearer " + _token(FOUNDER)},
                    json={"nodes": [], "control": {"hosts": hosts}})
    assert r.status_code == 200, r.text
    status, body = _call(client, _token(FOUNDER), "hosts.state")
    answer = json.loads(body["result"]["content"][0]["text"])
    assert answer["ok"] is True and answer["hosts"] == hosts and answer["live"] is True
    import db
    assert db.count_agent_tasks() == 0


def test_the_desktop_claims_only_what_the_founders_accounts_queued(client):
    """The claim took the oldest queued task of ANY account."""
    import db
    auth = {"Authorization": "Bearer " + _token(FOUNDER)}
    claim = {"claimed_by": "archhub-app", "kinds": ["app", "app-execute", "host-read"]}
    foreign = db.enqueue_agent_task(directive="delete everything", created_by=STRANGER,
                                    kind="app-execute")
    r = client.post("/founder/api/agent-tasks/claim", headers=auth, json=claim)
    assert r.status_code == 200 and r.json()["task"] is None
    assert db.get_agent_task(foreign["id"])["status"] == "queued"
    own = db.enqueue_agent_task(directive='{"args":{},"tool":"hosts.status"}',
                                created_by="Founder@Example.test", kind="host-read")
    r = client.post("/founder/api/agent-tasks/claim", headers=auth, json=claim)
    assert r.json()["task"]["id"] == own["id"]


def test_every_founder_secret_name_admits_and_none_set_admits_nobody(monkeypatch):
    import config
    for name in ("FOUNDER_EMAILS", "FOUNDER_EMAIL", "ARCHHUB_FOUNDER_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    assert config.founder_emails() == frozenset()
    monkeypatch.setenv("ARCHHUB_FOUNDER_EMAIL", " Cloud@Example.test ")
    monkeypatch.setenv("FOUNDER_EMAIL", "desktop@example.test")
    assert config.founder_emails() == {"cloud@example.test", "desktop@example.test"}
    monkeypatch.setenv("FOUNDER_EMAILS", "a@x.test,b@x.test")
    assert config.founder_emails() == {"a@x.test", "b@x.test",
                                       "cloud@example.test", "desktop@example.test"}


def test_the_cockpit_serves_the_wire_list_the_app_pushed(client):
    auth = {"Authorization": "Bearer " + _token(FOUNDER)}
    rows = [{"k": "enabled", "label": "Enabled", "type": "toggle", "def": True}]
    assert client.post("/founder/map-state", headers=auth,
                       json={"nodes": [], "wire_params": rows}).status_code == 200
    asset = client.get("/founder/map-assets/map-data.js", headers=auth).text
    assert "window.WIRE_PARAMS = " + json.dumps(rows) + ";" in asset
    assert 'window.WIRE_PARAMS_ERROR = "";' in asset
