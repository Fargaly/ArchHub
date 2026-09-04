"""The cockpit controls the founder's RUNNING application.

A question typed into the cockpit is not answered by the cloud: it is queued
for the founder's app (agent_tasks kind 'app'), the app claims it, puts it to
BABOOM and posts the answer, and the cockpit returns that answer. These courts
play the app's side over the real routes."""
import threading
import time

import pytest

from tests.test_cockpit_agent import FOUNDER_EMAIL, _auth, _sign_in  # noqa: F401


@pytest.fixture(autouse=True)
def _founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    for key in ("NVIDIA_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "6")
    import founder_cockpit
    founder_cockpit.clear_errors()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _play_the_app(client, token, answer, delay=0.3):
    """The founder's application: claim the next instruction, answer it."""
    seen = {}

    def run():
        # The app's relay speaks to the SAME queue the routes expose (the routes
        # are proven on their own below); the sync TestClient cannot serve a
        # second request while the command request is still blocking in it.
        import db
        task = None
        for _ in range(25):                      # the app polls; so does this
            time.sleep(delay)
            task = db.claim_next_agent_task(claimed_by="archhub-app")
            if task:
                break
        seen["task"] = task
        if task:
            db.finish_agent_task(task["id"], ok=True, result=answer)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return seen, thread


def test_a_question_about_the_app_is_answered_by_the_app(client, monkeypatch):
    token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    seen, thread = _play_the_app(client, token, "Blocked: nothing. Focus: BBC4 sheet 12.")
    r = client.post("/founder/api/command", headers=_auth(token),
                    json={"command": "what is blocked?", "confirm": False})
    thread.join(5)
    d = r.json()
    assert r.status_code == 200, r.text
    assert d["action"] == "app" and d["ok"] is True, d
    assert "Blocked: nothing" in d["message"], (d, seen)
    assert seen["task"]["directive"] == "what is blocked?"
    assert seen["task"]["kind"] == "app"


def test_confirm_off_means_the_app_acts(client, monkeypatch):
    token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    seen, thread = _play_the_app(client, token, "Sent to codex.")
    r = client.post("/founder/api/command", headers=_auth(token),
                    json={"command": "tell codex: review the PR", "confirm": True})
    thread.join(5)
    assert r.json()["message"] == "Sent to codex."
    assert seen["task"]["kind"] == "app-execute"


def test_an_unanswered_question_says_so_and_stays_queued(client, monkeypatch):
    monkeypatch.setenv("COCKPIT_APP_RELAY_WAIT_S", "0.2")
    token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    r = client.post("/founder/api/command", headers=_auth(token),
                    json={"command": "blorp zorp", "confirm": False})
    d = r.json()
    assert d["action"] == "app" and d.get("pending_app") is True, d
    assert "not answered yet" in d["message"]
    import db
    assert db.count_agent_tasks("queued") >= 1


def test_only_the_founder_can_claim_or_answer(client, monkeypatch):
    stranger = _sign_in(client, monkeypatch, "stranger@example.com")
    r = client.post("/founder/api/agent-tasks/claim", headers=_auth(stranger), json={})
    assert r.status_code in (401, 403)
    r = client.post("/founder/api/agent-tasks/task_x/result", headers=_auth(stranger),
                    json={"ok": True, "result": "x"})
    assert r.status_code in (401, 403)


def test_idle_claim_is_null_and_result_needs_a_claim(client, monkeypatch):
    token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    import db
    with db.connect() as con:
        con.execute("DELETE FROM agent_tasks")
    r = client.post("/founder/api/agent-tasks/claim", headers=_auth(token), json={})
    assert r.status_code == 200 and r.json()["task"] is None
    r = client.post("/founder/api/agent-tasks/task_nope/result", headers=_auth(token),
                    json={"ok": True, "result": "x"})
    assert r.status_code == 409


def test_the_agent_loop_has_the_app_tool():
    import cockpit_agent
    assert "app_command" in cockpit_agent.TOOLS
    assert cockpit_agent.TOOLS["app_command"]["kind"] == "read"
    assert "app_command" in cockpit_agent.SYSTEM_PROMPT


def test_the_routes_carry_the_whole_claim_answer_read_cycle(client, monkeypatch):
    token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    import app_relay
    task = app_relay.enqueue("agents", actor=FOUNDER_EMAIL)
    r = client.post("/founder/api/agent-tasks/claim", headers=_auth(token),
                    json={"claimed_by": "archhub-app", "kinds": ["app", "app-execute"]})
    assert r.status_code == 200 and r.json()["task"]["id"] == task["id"], r.text
    assert r.json()["task"]["status"] == "claimed"
    r = client.post("/founder/api/agent-tasks/%s/result" % task["id"], headers=_auth(token),
                    json={"ok": True, "result": "3 agent session(s): codex x2, claude x1."})
    assert r.status_code == 200 and r.json()["task"]["status"] == "done"
    r = client.get("/founder/api/agent-tasks/%s" % task["id"], headers=_auth(token))
    assert r.json()["task"]["result"].startswith("3 agent session(s)")
    assert app_relay.wait_for(task["id"], wait_s=0)["status"] == "done"


def test_help_still_answers_as_help(client, monkeypatch):
    token = _sign_in(client, monkeypatch, FOUNDER_EMAIL)
    r = client.post("/founder/api/command", headers=_auth(token),
                    json={"command": "what can you do", "confirm": False})
    assert r.json()["action"] == "help", r.json()
