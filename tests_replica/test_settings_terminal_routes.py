"""Courts for the lane baboom-settings HTTP paths, on the real application server.

- Settings > Account cloud publish consent: GET reads the one record beside the
  graph that start_cloud_relay reads; POST allow writes it only for the account
  cloud.json holds; POST withdraw deletes it, and a running relay stops at its
  next poll without claiming anything.
- Terminal node: a real shell starts only in a folder inside the admitted
  workspace root; input streams out by offset; Stop ends it; a folder outside
  the root is refused; the canvas Run of a terminal card runs its command.
"""
import json
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang import universal_application as app


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    appdata = tmp_path / "appdata"
    (appdata / "ArchHub" / "brain").mkdir(parents=True)
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("APPDATA", str(appdata))
    workspace = tmp_path / "workspace"
    (workspace / "project").mkdir(parents=True)
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    running = ApplicationServer(universal_state_path=tmp_path / "routes.sqlite3", universal_key_provider=keys,
        universal_workspace_root=workspace, enable_machine_transport=False,
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
        live_watch=False, pipeline_effect_engines=PIPELINE_ENGINES).start()
    running.court_paths = {"state": state_dir, "appdata": appdata, "workspace": workspace, "outside": tmp_path}
    try:
        yield running
    finally:
        running.close()


def call(server, path, body=None, expected=200):
    request = Request(server.url + path, headers={"Content-Type": "application/json", "Origin": server.url,
        "Cookie": "ArchHub-Session=" + server.browser_session_token,
        "X-ArchHub-CSRF": server.browser_csrf_token},
        data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(request, timeout=60) as response:
            status, result = response.status, json.loads(response.read())
    except HTTPError as exc:
        status, result = exc.code, json.loads(exc.read())
    assert status == expected, (path, status, result)
    return result


def test_cloud_publish_consent_is_one_record_the_relay_obeys(server):
    from nodelang.cloud_publish_consent import CONSENT_FILE, cloud_publish_allowed
    from nodelang.cloud_relay import CloudRelay
    record = server.court_paths["state"] / CONSENT_FILE
    assert call(server, "/api/universal/cloud-publish-consent") == {"ok": True, "allowed": False, "account": ""}
    # No cloud.json: consent is recorded for a signed-in account only.
    refused = call(server, "/api/universal/cloud-publish-consent", {"allow": True}, expected=409)
    assert "Sign in" in refused["error"] and not record.exists()
    (server.court_paths["appdata"] / "ArchHub" / "brain" / "cloud.json").write_text(
        json.dumps({"email": "Owner@Example.com", "token": "t"}), encoding="utf-8")
    allowed = call(server, "/api/universal/cloud-publish-consent", {"allow": True})
    assert allowed == {"ok": True, "allowed": True, "account": "owner@example.com"}
    assert cloud_publish_allowed(server.court_paths["state"]), "start_cloud_relay now starts the relay"
    claims = []

    def opener(request, timeout):
        claims.append(request.full_url)
        raise AssertionError("a withdrawn consent must not claim cloud work")

    relay = CloudRelay(base_url="https://api.archhub.io", token="t", respond=dict, execute=dict,
        opener=opener, consent=lambda: cloud_publish_allowed(server.court_paths["state"]))
    withdrawn = call(server, "/api/universal/cloud-publish-consent", {"allow": False})
    assert withdrawn == {"ok": True, "allowed": False, "account": ""} and not record.exists()
    assert relay.poll_once() is None and claims == [], "the running relay claims nothing after withdrawal"
    assert relay._stop.is_set() and "withdrawn" in relay.last_error
    call(server, "/api/universal/cloud-publish-consent", {"allow": "yes"}, expected=400)


def _wait_for(server, session, needle, seconds=15):
    deadline = time.monotonic() + seconds
    seen = ""
    while time.monotonic() < deadline:
        seen = call(server, "/api/universal/terminal?" + urlencode({"id": session, "since": 0}))["output"]
        if needle in seen:
            return seen
        time.sleep(0.1)
    raise AssertionError("terminal never printed %r: %r" % (needle, seen[-400:]))


def test_terminal_runs_a_real_shell_only_inside_the_admitted_scope(server):
    import psutil
    started = call(server, "/api/universal/terminal", {"action": "start", "cwd": "project"})
    session = started["id"]
    assert started["state"] == "running"
    assert Path(started["cwd"]) == (server.court_paths["workspace"] / "project").resolve()
    shell = psutil.Process(server.terminal_sessions._get(session).process.pid)
    call(server, "/api/universal/terminal", {"action": "input", "id": session, "text": "echo terminal-court-%CD%"})
    shown = _wait_for(server, session, "terminal-court-")
    assert str((server.court_paths["workspace"] / "project").resolve()) in shown, "the shell runs in the admitted folder"
    stopped = call(server, "/api/universal/terminal", {"action": "stop", "id": session})
    assert stopped["state"] == "stopped" and stopped["exit_code"] is not None
    assert not shell.is_running() or shell.status() == psutil.STATUS_ZOMBIE, "Stop ends the shell"
    after = call(server, "/api/universal/terminal", {"action": "input", "id": session, "text": "echo late"}, expected=409)
    assert "ended" in after["error"]
    outside = call(server, "/api/universal/terminal",
        {"action": "start", "cwd": str(server.court_paths["outside"])}, expected=409)
    assert "outside" in outside["error"]
    escape = call(server, "/api/universal/terminal", {"action": "start", "cwd": "project/../.."}, expected=409)
    assert "outside" in escape["error"]


def test_the_terminal_card_is_placed_and_its_run_uses_the_same_owner(server):
    from nodelang.terminal_sessions import owner_only_engine
    # Only run-graph binds the owner-checked engine; the standing binding refuses.
    assert server.pipeline_effect_engines["library.terminal"] is owner_only_engine
    produced, shown = server.terminal_sessions.engine({"cwd": "project", "command": "echo card-run"}, {})
    assert produced["ok"] is True and "card-run" in produced["out"] and shown == "exit 0"
    with pytest.raises(Exception, match="outside"):
        server.terminal_sessions.engine({"cwd": str(server.court_paths["outside"]), "command": "echo x"}, {})
    created = call(server, "/api/universal/node-create",
        {"title": "Terminal", "engine": "library.terminal", "params": {"cwd": "project", "command": "echo from-the-card"}})
    root = created["root"]
    outcome = call(server, "/api/universal/run-graph", {})
    assert outcome["display"].get(root) == "exit 0", outcome


def _timed(server, path, body=None, expected=200):
    started = time.perf_counter()
    result = call(server, path, body, expected)
    return (time.perf_counter() - started) * 1000.0, result


def test_settings_reads_never_wait_on_a_port_scan_or_a_silent_brain(server, monkeypatch):
    """The Settings click path is a gate (founder: smoothness). On 35d3e8f /hosts ran a live
    port scan in the request (5.4 s), /providers probed two closed localhost ports (0.44 s)
    and /brain-export held the graph lock while the brain was silent."""
    import threading
    from nodelang import model_router, pipeline_engines
    release = threading.Event()

    def slow_hosts():
        release.wait(5)
        return [{"id": "revit", "name": "Revit", "state": "absent", "detail": "", "drive": True}]

    monkeypatch.setattr(server, "_probe_hosts", slow_hosts)
    monkeypatch.setattr(model_router, "probe_local_runtimes", lambda: (release.wait(5), {1234: True, 11434: False})[1])
    ms, first = _timed(server, "/api/universal/hosts")
    assert first["probing"] is True and ms < 150, (ms, first)
    # The first read in a process also pays the one-time secrets-store import
    # (about 0.27 s); the gate is every read after it, still while the probe hangs.
    call(server, "/api/universal/providers")
    ms, providers = _timed(server, "/api/universal/providers")
    local = {row["id"]: row["state"] for row in providers["providers"]}
    assert local["lmstudio"] == "checking" and ms < 150, (ms, local)
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and call(server, "/api/universal/hosts").get("probing"):
        time.sleep(0.05)
    ms, answered = _timed(server, "/api/universal/hosts")
    assert answered["connectors"][0]["name"] == "Revit" and ms < 150, (ms, answered)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        local = {row["id"]: row["state"] for row in call(server, "/api/universal/providers")["providers"]}
        if local["lmstudio"] != "checking":
            break
        time.sleep(0.05)
    assert local == {**local, "lmstudio": "running", "ollama": "not running"}

    silent = threading.Event()

    def brain(tool, arguments, *, budget=None):
        assert budget == 4.0, "the Brain tab asks with the short budget"
        silent.wait(2)
        raise pipeline_engines.BrainSilent("no answer on the brain port")

    monkeypatch.setattr(pipeline_engines, "_brain_call", brain)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(result=call(
        server, "/api/universal/brain-export", {"limit": 500, "quick": True}, expected=503)))
    worker.start()
    time.sleep(0.2)
    ms, _canvas = _timed(server, "/api/universal/canvas")
    assert worker.is_alive(), "the brain read was still waiting"
    assert ms < 1500, "a silent brain no longer holds the graph lock (%.0f ms)" % ms
    silent.set()
    worker.join(10)
    assert outcome["result"] == {"ok": False, "error": "Brain not answering",
                                 "detail": "no answer on the brain port"}


def test_every_library_card_can_be_placed_including_notify(server):
    """o_notify declared a "title" parameter, which every placed card already holds, so it
    could never be placed ("property label already exists"). It is notice_title now."""
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    assert "title" not in LIBRARY_ITEM_ENGINES["o_notify"]["params"]
    placed = call(server, "/api/universal/node-create", {"title": "notify", "engine": "library.notify",
        "params": dict(LIBRARY_ITEM_ENGINES["o_notify"]["params"], message="sheet set published")})
    assert placed["root"]
    for item, wiring in sorted(LIBRARY_ITEM_ENGINES.items()):
        clashes = set(wiring["params"]) & {"title", "label", "definition"}
        assert not clashes, (item, clashes)


# ---- v2 courts (verifier defects D1, D2, D5, D6, D7, D8) ----

def _other_subject(server, monkeypatch):
    """Every browser resolve answers the same context under another subject."""
    import dataclasses
    real = server._resolve_browser_session

    def resolve(token, **kwargs):
        return dataclasses.replace(real(token, **kwargs), subject_root="subject:someone-else")
    monkeypatch.setattr(server, "_resolve_browser_session", resolve)


def test_a_terminal_card_runs_only_for_the_owner_with_execute(server, monkeypatch):
    """D1: run-graph needs only edit; the card's shell needs what POST /terminal needs."""
    from nodelang import application_server as srv
    from nodelang.terminal_sessions import TerminalRefused
    marker = server.court_paths["workspace"] / "project" / "d1-marker.txt"
    root = call(server, "/api/universal/node-create", {"title": "Terminal", "engine": "library.terminal",
        "params": {"cwd": "project", "command": "echo ran>d1-marker.txt"}})["root"]
    real_route = server.require_universal_http_route

    def edit_without_execute(method, path, **kwargs):
        if path == "/api/universal/terminal":
            raise srv.AuthorizationDenied("execute is not granted")
        return real_route(method, path, **kwargs)
    monkeypatch.setattr(server, "require_universal_http_route", edit_without_execute)
    refused = call(server, "/api/universal/run-graph", {})
    assert not marker.exists(), "an edit-only binding ran a shell command"
    assert "owner" in str(refused["pending"].get(root) or refused["display"].get(root)), refused
    monkeypatch.setattr(server, "require_universal_http_route", real_route)
    with monkeypatch.context() as other:
        _other_subject(server, other)
        call(server, "/api/universal/run-graph", {})
    assert not marker.exists(), "a binding of another subject ran a shell command"
    with pytest.raises(TerminalRefused):
        server.pipeline_effect_engines["library.terminal"](
            {"cwd": "project", "command": "echo ran>d1-marker.txt"}, {})
    assert not marker.exists(), "a run other than the owner's canvas Run spawned a shell"
    assert call(server, "/api/universal/run-graph", {})["display"].get(root) == "exit 0"
    assert marker.exists(), "the owner's own Run still runs the card"


def test_a_running_terminal_card_does_not_hold_the_graph_lock(server):
    """D2: the effect runs outside owner.mutation_lock; the status still lands."""
    import threading
    root = call(server, "/api/universal/node-create", {"title": "Terminal", "engine": "library.terminal",
        "params": {"cwd": "project", "command": "ping -n 4 127.0.0.1 >nul"}})["root"]
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(result=call(server, "/api/universal/run-graph", {})))
    worker.start()

    def shell_running():
        return any(s.process.poll() is None for s in list(server.terminal_sessions._sessions.values()))
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not shell_running():
            time.sleep(0.02)
        assert shell_running(), "the card's shell never started"
        free = server.mutation_lock.acquire(timeout=1.0)
        if free:
            server.mutation_lock.release()
        assert free, "the graph lock was held while the terminal engine waited on its shell"
        assert worker.is_alive(), "the lock was probed while the engine was still waiting"
    finally:
        worker.join(30)
    assert outcome["result"]["display"].get(root) == "exit 0", outcome


def test_stop_ends_processes_the_shell_started_later(server):
    """D5: the shell's Job object ends a child started after the shell, not only a snapshot."""
    import os
    import psutil
    if os.name != "nt":
        pytest.skip("Job objects are Windows")
    session = call(server, "/api/universal/terminal", {"action": "start", "cwd": "project"})["id"]
    held = server.terminal_sessions._get(session)
    assert held.job.held, "the shell runs inside its own Job object"
    call(server, "/api/universal/terminal", {"action": "input", "id": session,
        "text": "start /b ping -n 60 127.0.0.1 >nul"})
    deadline = time.monotonic() + 10
    pings = []
    while time.monotonic() < deadline and not pings:
        pings = [p for p in psutil.Process(held.process.pid).children(recursive=True)
                 if p.name().lower() == "ping.exe"]
        time.sleep(0.1)
    assert pings, "the background child started"
    call(server, "/api/universal/terminal", {"action": "stop", "id": session})
    psutil.wait_procs(pings, timeout=5)
    assert not any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in pings), \
        "Stop left a child running"


def test_the_terminal_route_rechecks_its_binding_before_starting(server, monkeypatch):
    """D6: admitted at the top of the request, re-resolved under live_context before the shell."""
    from nodelang import application_server as srv
    real = server._resolve_browser_session
    calls = []

    def revoked_after_admission(token, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise srv.AuthorizationDenied("browser session is unknown")
        return real(token, **kwargs)
    monkeypatch.setattr(server, "_resolve_browser_session", revoked_after_admission)
    before = set(server.terminal_sessions._sessions)
    call(server, "/api/universal/terminal", {"action": "start", "cwd": "project"}, expected=403)
    assert set(server.terminal_sessions._sessions) == before, "a revoked binding started a shell"


def _sign_in(server, email):
    cloud = server.court_paths["appdata"] / "ArchHub" / "brain" / "cloud.json"
    if email is None:
        cloud.unlink(missing_ok=True)
    else:
        cloud.write_text(json.dumps({"email": email, "token": "t-" + email}), encoding="utf-8")


def test_cloud_publish_consent_is_the_signed_in_accounts(server, monkeypatch):
    """D7: consent granted by one account opens nothing after sign-out or an account switch."""
    from nodelang.cloud_relay import CloudRelay, start_cloud_relay
    monkeypatch.setattr(CloudRelay, "start", lambda self: self)
    state, appdata = server.court_paths["state"], server.court_paths["appdata"]
    _sign_in(server, "owner@example.com")
    assert call(server, "/api/universal/cloud-publish-consent", {"allow": True})["allowed"] is True
    relay = start_cloud_relay(appdata=appdata, state_dir=state, respond=dict, execute=dict)
    assert relay is not None and relay.consent() is True
    _sign_in(server, "other@example.com")
    assert call(server, "/api/universal/cloud-publish-consent") == {"ok": True, "allowed": False, "account": ""}
    assert relay.consent() is False, "a running relay keeps publishing for another account"
    assert relay.poll_once() is None and relay._stop.is_set()
    assert start_cloud_relay(appdata=appdata, state_dir=state, respond=dict, execute=dict) is None
    _sign_in(server, None)
    assert call(server, "/api/universal/cloud-publish-consent")["allowed"] is False
    _sign_in(server, "owner@example.com")
    assert call(server, "/api/universal/cloud-publish-consent")["allowed"] is True, \
        "the granting account still holds it"


def test_cloud_publish_consent_read_is_owner_only(server, monkeypatch):
    """D8: the consent record, with its email, is read by the application owner only."""
    _sign_in(server, "owner@example.com")
    call(server, "/api/universal/cloud-publish-consent", {"allow": True})
    _other_subject(server, monkeypatch)
    denied = call(server, "/api/universal/cloud-publish-consent", expected=403)
    assert "owner@example.com" not in json.dumps(denied)
