"""The cockpit controls THIS application, and BABOOM controls the agents.

2026-09-04 the founder: "the core of the cockpit is that I control what I am
working with, control the agents, make them talk to each other". These courts
play the cloud and the coordination host so the relay and the agent link are
proven without a network."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class _FakeCloud(BaseHTTPRequestHandler):
    tasks = []          # queued rows the app may claim
    results = []        # (task_id, body) the app posted
    maps = []           # raw map bodies pushed
    auth = []

    def log_message(self, *_a):  # quiet
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _FakeCloud.auth.append(self.headers.get("Authorization"))
        if self.path == "/founder/api/agent-tasks/claim":
            task = _FakeCloud.tasks.pop(0) if _FakeCloud.tasks else None
            return self._json(200, {"ok": True, "task": task})
        if self.path.startswith("/founder/api/agent-tasks/") and self.path.endswith("/result"):
            _FakeCloud.results.append((self.path.split("/")[-2], json.loads(raw)))
            return self._json(200, {"ok": True})
        if self.path == "/founder/map-state":
            _FakeCloud.maps.append(raw)
            return self._json(200, {"ok": True, "bytes": len(raw)})
        return self._json(404, {"ok": False})


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_port


def test_the_app_claims_a_cockpit_question_and_posts_baboom_answer():
    from nodelang.cloud_relay import CloudRelay
    server, base = _serve(_FakeCloud)
    _FakeCloud.tasks[:] = [
        {"id": "task_1", "kind": "app", "directive": "what is blocked?"},
        {"id": "task_2", "kind": "app-execute", "directive": "tell codex: hi"},
    ]
    _FakeCloud.results[:] = []
    asked = []
    relay = CloudRelay(
        base_url=base, token="tok-founder",
        respond=lambda u: asked.append(("respond", u)) or {"response": {"kind": "attention", "summary": "Nothing is blocked.", "data": {"focus": "BBC4"}}},
        execute=lambda u: asked.append(("execute", u)) or {"kind": "agent-messaged", "summary": "Sent to codex.", "data": {}},
    )
    try:
        first = relay.poll_once(); second = relay.poll_once(); third = relay.poll_once()
    finally:
        server.shutdown()
    assert asked == [("respond", "what is blocked?"), ("execute", "tell codex: hi")]
    assert first["result"].startswith("Nothing is blocked.") and "focus: BBC4" in first["result"]
    assert second == {"task": "task_2", "ok": True, "result": "Sent to codex."}
    assert third is None
    assert [r[0] for r in _FakeCloud.results] == ["task_1", "task_2"]
    assert all(a == "Bearer tok-founder" for a in _FakeCloud.auth)


def test_a_refusal_is_posted_as_the_answer_never_dropped():
    from nodelang.cloud_relay import CloudRelay
    server, base = _serve(_FakeCloud)
    _FakeCloud.tasks[:] = [{"id": "task_9", "kind": "app", "directive": "run engine nope.x"}]
    _FakeCloud.results[:] = []
    def boom(_u):
        raise ValueError("no engine named 'nope.x'")
    relay = CloudRelay(base_url=base, token="t", respond=boom, execute=boom)
    try:
        out = relay.poll_once()
    finally:
        server.shutdown()
    assert out["ok"] is False and "no engine named" in out["result"]
    assert _FakeCloud.results[-1][1] == {"ok": False, "result": out["result"]}


def test_the_live_map_is_republished_only_when_it_changes():
    from nodelang.cloud_relay import CloudRelay
    server, base = _serve(_FakeCloud)
    _FakeCloud.maps[:] = []
    script = ["window.ATLAS_MAP = {\"domains\": [1]}; window.ATLAS_LIVE = true;"]
    relay = CloudRelay(base_url=base, token="t", respond=lambda u: {}, execute=lambda u: {}, map_script=lambda: script[0])
    try:
        assert relay.push_map(force=True)["ok"] is True
        assert relay.push_map(min_interval=0) is None         # unchanged -> no push
        script[0] = "window.ATLAS_MAP = {\"domains\": [1, 2]}; window.ATLAS_LIVE = true;"
        assert relay.push_map(min_interval=0)["bytes"] > 0    # changed -> pushed
        assert relay.push_map() is None                       # inside the interval -> wait
    finally:
        server.shutdown()
    # the relay adds its control block to every push; the map itself is untouched
    assert [json.loads(m)["domains"] for m in _FakeCloud.maps] == [[1], [1, 2]]
    assert all("control" in json.loads(m) for m in _FakeCloud.maps)


def test_render_answer_reads_both_response_and_execution_shapes():
    from nodelang.cloud_relay import render_answer
    assert render_answer({"response": {"kind": "brain-health", "summary": "Brain: 2337 facts.", "data": {"facts": 2337}}}) == "Brain: 2337 facts.\nfacts: 2337"
    text = render_answer({"kind": "agents-online", "summary": "2 agent session(s).", "data": {"agents": [{"session": "s1", "provider": "codex"}, {"session": "s2"}]}})
    assert text == "2 agent session(s).\nagents: s1; s2"
    assert "Untick" in render_answer({"kind": "x", "summary": "Ready.", "data": {"requires": "explicit execute"}})


def test_the_relay_is_inert_without_session_or_consent(tmp_path):
    from nodelang.cloud_relay import load_cloud_session, start_cloud_relay
    assert load_cloud_session(tmp_path) is None
    assert start_cloud_relay(appdata=tmp_path, state_dir=tmp_path, respond=lambda u: {}, execute=lambda u: {}) is None
    (tmp_path / "ArchHub" / "brain").mkdir(parents=True)
    (tmp_path / "ArchHub" / "brain" / "cloud.json").write_text(json.dumps({"token": "abc", "cloud_base_url": "https://api.archhub.io/"}), encoding="utf-8")
    assert load_cloud_session(tmp_path) == {"token": "abc", "base_url": "https://api.archhub.io"}


def test_baboom_resolves_an_agent_by_name_to_the_newest_online_session():
    from nodelang.baboom_agent_link import resolve_target
    rows = [
        {"session_root": "s:codex:old", "provider": "codex", "runtime": "codex-cli", "status": "offline", "revision": 10},
        {"session_root": "s:codex:new", "provider": "codex", "runtime": "codex-cli", "status": "online", "revision": 40},
        {"session_root": "s:claude:1", "provider": "anthropic", "runtime": "claude-code", "status": "online", "revision": 30},
    ]
    assert resolve_target("codex", rows)["session_root"] == "s:codex:new"
    assert resolve_target("claude", rows)["session_root"] == "s:claude:1"
    assert resolve_target("s:codex:old", rows)["session_root"] == "s:codex:old"
    assert resolve_target("gemini", rows) is None and resolve_target("", rows) is None


def test_the_launcher_starts_the_relay_after_baboom_attaches():
    src = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert src.index("baboom_window.start_projection()") < src.index("start_cloud_relay")
    assert "map_script=lambda: _atlas(server.universal_store, server.universal_registry)" in src
    assert '"  cockpit    :"' in src


def test_baboom_knows_the_agent_verbs():
    import inspect
    import nodelang.universal_application as ua
    specs = {spec[0]: spec[1] for spec in ua._BABOOM_COMMAND_SPECS}
    assert "agents" in specs["agents-online"] and "agent-message" in specs and "agent-interrupt" in specs
    resolver = inspect.getsource(ua.resolve_universal_baboom_utterance)
    assert '"agents-online"' in resolver and '"agent-message"' in resolver and '"agent-interrupt"' in resolver
    assert "(?:tell|message|msg|ask)" in resolver and "(?:interrupt|stop)" in resolver
    responder = inspect.getsource(ua.respond_universal_baboom_utterance)
    assert 'intent == "agents-online"' in responder and "baboom_agent_link.list_agents()" in responder
    assert '"requires": "explicit execute"' in responder
    executor = inspect.getsource(ua.execute_universal_baboom_utterance)
    assert "baboom_agent_link.resolve_target" in executor
    assert "baboom_agent_link.send_message" in executor and "baboom_agent_link.interrupt_agent" in executor
    assert "no agent named" in executor


def test_the_agent_link_is_one_signed_identity_per_install(tmp_path):
    from nodelang import baboom_agent_link as link
    first = link.session_id(tmp_path)
    assert first == link.session_id(tmp_path) and len(first) == 32
    assert link.VENDOR == "archhub" and link.MODEL == "baboom"


def test_the_push_carries_a_control_block_from_baboom_answers():
    from nodelang.cloud_relay import CloudRelay
    server, base = _serve(_FakeCloud)
    _FakeCloud.maps[:] = []
    def respond(u):
        if u == "agents":
            return {"response": {"kind": "agents-online", "summary": "2", "data": {"agents": [{"session": "s1", "provider": "codex", "status": "online"}]}}}
        return {"response": {"kind": "governed-work-report", "summary": "Work: 3 active.", "data": {"items": [{"title": "wire the cockpit", "state": "claimed", "agent": "codex"}]}}}
    relay = CloudRelay(base_url=base, token="t", respond=respond, execute=lambda u: {},
                       map_script=lambda: "window.ATLAS_MAP = {\"domains\": [], \"nodes\": [], \"wires\": []}; window.ATLAS_LIVE = true;",
                       hosts=lambda: [{"id": "revit", "name": "Revit", "state": "connected", "detail": "live"}])
    try:
        assert relay.push_map(force=True)["ok"] is True
    finally:
        server.shutdown()
    pushed = json.loads(_FakeCloud.maps[-1])
    assert pushed["control"]["agents"][0]["provider"] == "codex"
    assert pushed["control"]["work_summary"] == "Work: 3 active."
    assert pushed["control"]["work_items"][0] == {"title": "wire the cockpit", "state": "claimed", "agent": "codex"}
    assert pushed["control"]["hosts"][0]["state"] == "connected"
