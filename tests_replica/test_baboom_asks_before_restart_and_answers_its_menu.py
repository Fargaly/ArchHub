"""BABOOM asks before it restarts, and every row of its menu answers.

Audit and reviews 2026-09-29/30 (founder: "fix BABOOM's bugs"):
- the read-only respond route restarted the application whenever an update was
  staged; respond now only describes the staged build and issues a single-use
  confirmation; execute installs exactly the confirmed build, re-read on disk;
- anything that could execute on the founder session (the cockpit relay) could
  type "restart to update build X" or "remember: X" with no respond step;
- "Repo status" (and two more catalogue commands) answered "BABOOM cannot do
  ... in this build yet";
- "Remember..." prefilled "remember: ", which matched nothing.
These courts speak to a real graph, the real machine route, the real updater
and the real relay entry.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import threading
import types
from pathlib import Path

import pytest

from nodelang import app_brain
from nodelang import application_server as server_module
from nodelang.cell_brain_governance import SEALED, classification, may_release
from nodelang.universal_cell import InvalidCell

ROOT = Path(__file__).resolve().parents[1]
RESPOND = "/api/universal/baboom-command-response"
EXECUTE = "/api/universal/baboom-command-execute"


@pytest.fixture(scope="module")
def graph():
    from nodelang.map_import import resolve_map_path
    from nodelang.universal_application import build_universal_application
    return build_universal_application(resolve_map_path())


@pytest.fixture
def brain(graph):
    store, registry = graph
    app_brain.bind(store, registry)
    yield app_brain
    app_brain.unbind(store)


def _server(graph, *, staged=None, request_restart=None):
    """The real machine dispatcher over a real graph; only I/O seams are faked.

    ``state["caller"]`` is the Agent Session the pipe resolves for a signed
    request; ``state["staged"]`` is what the 30 s staged-update cache holds.
    Every server method the routes use is the real one: a missing one fails.
    """
    store, registry = graph
    founder = registry.agent_body.session.root_id
    state = {"caller": founder, "staged": dict(staged or {})}
    restarts = []
    fake = types.SimpleNamespace(
        universal_store=store,
        universal_registry=registry,
        universal_checkpoint_guard=None,
        mutation_lock=threading.RLock(),
        conversation_content=None,
        require_universal_http_route=lambda *a, **k: None,
        _resolve_universal_machine_agent_session=lambda request: state["caller"],
        _brain_state=lambda: {"ok": True, "facts": 7},
        _host_rows=lambda: [],
        _staged_update=lambda: dict(state["staged"]),
        _desktop_request_update_restart=request_restart or restarts.append,
    )
    for name in ("_require_founder_machine_session", "_baboom_machine_content_reader",
                 "_baboom_brain_remember", "_baboom_brain_holds", "_baboom_confirm_ledger",
                 "_restart_to_confirmed_update"):
        setattr(fake, name, types.MethodType(getattr(server_module.ApplicationServer, name), fake))

    def call(path, utterance, *, piped=False):
        request = {"method": "POST", "path": path, "body": {"utterance": utterance}}
        if piped:  # a signed request over the pipe, as the companion sends it
            request.update(runtime_id="0" * 32, request_id="1" * 32,
                           session={"root": "app:agent-session:runtime:" + "2" * 32})
        return server_module.ApplicationServer._dispatch_universal_machine_route(fake, request)

    call.fake, call.state = fake, state
    return call, restarts


def _offer(call, utterance):
    """Respond, as the companion does, and return the confirmation it issued."""
    response = call(RESPOND, utterance)["response"]
    assert response["data"]["requires"] == "explicit execute", response
    confirm = response["data"]["confirm_utterance"]
    assert re.fullmatch(r"confirm [0-9a-f]{32}", confirm), confirm
    return response, confirm


def _respond(graph, utterance, **kwargs):
    from nodelang.universal_application import respond_universal_baboom_utterance
    store, registry = graph
    return respond_universal_baboom_utterance(
        store, registry, utterance=utterance,
        authentication_context=registry.authorization.session.context(),
        brain_state={"ok": True, "facts": 7}, hosts=[], **kwargs)["response"]


def _relay(call):
    """The launcher's real relay entries (_cockpit_respond, _cockpit_execute)
    over the real machine routes, through the same signed BABOOM host."""
    source = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [n for n in tree.body if getattr(n, "name", None) in {"_cockpit_respond", "_cockpit_execute"}]
    assert len(nodes) == 2
    namespace = {
        "_baboom_stop": threading.Event(), "_baboom_off_reason": None,
        "baboom_host": types.SimpleNamespace(
            respond_input=lambda utterance: call(RESPOND, utterance, piped=True),
            execute_input=lambda utterance: call(EXECUTE, utterance, piped=True)),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "launch_archhub_test.py", "exec"), namespace)
    return namespace["_cockpit_respond"], namespace["_cockpit_execute"]


def _relay_execute(call):
    return _relay(call)[1]


# -- 1. restart: only on a confirmation, only into the confirmed build -------

def test_respond_with_an_update_staged_does_not_restart(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    response, _confirm = _offer(call, "restart to update")
    assert restarts == [], "the read-only respond route restarted his application"
    assert response["kind"] == "update-ready" and response["data"]["build_id"] == "b-2"
    assert "b-2" in response["summary"]


def test_execute_restarts_into_the_build_the_founder_confirmed(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    _response, confirm = _offer(call, "restart to update")
    result = call(EXECUTE, confirm)
    assert restarts == ["b-2"], "the confirmed build id goes down to the updater"
    assert result["kind"] == "update-ready" and "b-2" in result["summary"]


def test_a_confirm_for_one_build_never_installs_another(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    _response, confirm = _offer(call, "restart to update")
    call.state["staged"] = {"build_id": "b-3", "tag": "v10"}
    result = call(EXECUTE, confirm)
    assert restarts == [], "a confirm for b-2 installed b-3"
    assert result["kind"] == "update-changed" and "b-3" in result["summary"]


INSTALLED = ("20260916-2130-e733a13", "2026-09-16T17:24:00Z")
ON_DISK = ("20260917-0900-0a1b2c3", "2026-09-17T05:00:00Z")
SHOWN = "20260917-0800-0d0d0d0"


def _stage_on_disk(tmp_path):
    """A real verified staged build in a real updates directory (quiet_update's own path)."""
    import io
    from nodelang import quiet_update as qu

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    app, state = tmp_path / "ArchHub", tmp_path / "ArchHub-Test"
    app.mkdir(parents=True)
    (app / "BUILD_ID").write_text(INSTALLED[0], encoding="utf-8")
    (app / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": INSTALLED[0], "built_at": INSTALLED[1]}), encoding="utf-8")
    installer = ("installer for " + ON_DISK[0]).encode("ascii")
    tag = "build-" + ON_DISK[0]
    release = {"tag_name": tag, "draft": False, "prerelease": False,
               "body": "BUILD_ID: %s\nBUILT_AT: %s\nSHA256 %s: %s\n" % (
                   ON_DISK[0], ON_DISK[1], qu.ASSET_NAME, hashlib.sha256(installer).hexdigest()),
               "assets": [{"name": qu.ASSET_NAME, "size": len(installer),
                           "browser_download_url": "https://github.com/Fargaly/ArchHub/releases/download/%s/%s"
                           % (tag, qu.ASSET_NAME)}]}

    def opener(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        return Response(json.dumps(release).encode("utf-8") if url == qu.RELEASE_API else installer)

    staged = qu.stage_if_newer(state, app, opener=opener)
    assert staged["staged"] and staged["build_id"] == ON_DISK[0], staged
    return state, app


def test_the_updater_rereads_disk_and_refuses_a_build_the_cache_missed(graph, tmp_path):
    """Shown one build (the 30 s cache), another staged on disk: nothing installs."""
    from nodelang.application_update import ApplicationUpdate
    state_dir, app_dir = _stage_on_disk(tmp_path)
    requested = []
    update = ApplicationUpdate(state_dir, app_dir, request_restart=lambda: requested.append("restart"))
    call, _ = _server(graph, staged={"build_id": SHOWN}, request_restart=update.reload)
    _response, confirm = _offer(call, "restart to update")
    result = call(EXECUTE, confirm)
    assert requested == [], "the updater restarted into a build he never confirmed"
    assert result["kind"] == "update-changed" and ON_DISK[0] in result["summary"]
    assert result["data"]["restart"] is False


def test_the_updater_installs_the_confirmed_build_when_it_is_the_one_on_disk(graph, tmp_path):
    from nodelang.application_update import ApplicationUpdate
    state_dir, app_dir = _stage_on_disk(tmp_path)
    requested = []
    update = ApplicationUpdate(state_dir, app_dir, request_restart=lambda: requested.append("restart"))
    call, _ = _server(graph, staged={"build_id": ON_DISK[0]}, request_restart=update.reload)
    _response, confirm = _offer(call, "restart to update")
    result = call(EXECUTE, confirm)
    assert requested == ["restart"] and result["kind"] == "update-ready"


def test_typed_restart_words_without_a_confirmation_do_nothing(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    for typed in ("restart to update", "restart to update build b-2"):
        with pytest.raises(InvalidCell):
            call(EXECUTE, typed)
    assert restarts == []


def test_the_relay_never_receives_a_confirmation_and_cannot_confirm(graph, brain):
    """Founder decision 2026-09-30: restart and remember are confirmed on the
    desktop companion only. A cockpit respond gets no confirmation, and a
    confirmation that leaked from the desktop is refused on the relay."""
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    relay_respond, relay_execute = _relay(call)
    for utterance in ("restart to update", "remember: the relay fact about the Staller slab"):
        offered = relay_respond(utterance)["response"]["data"]
        assert "confirm_utterance" not in offered, offered
        assert offered["requires"] == "confirm on the desktop"
    _response, leaked = _offer(call, "restart to update")
    with pytest.raises(RuntimeError, match="desktop only"):
        relay_execute(leaked)
    assert restarts == []
    call(EXECUTE, leaked)  # the desktop's own press still works
    assert restarts == ["b-2"]


def test_a_relay_execute_without_a_confirmation_is_refused(graph, brain):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    relay = _relay_execute(call)
    with pytest.raises(InvalidCell):
        relay("restart to update build b-2")
    with pytest.raises(InvalidCell):
        relay("remember: the relay wrote this fact")
    assert restarts == []
    assert "the relay wrote this fact" not in {f["text"] for f in brain.context("relay wrote fact")["facts"]}


def test_a_used_confirmation_never_acts_twice(graph, brain):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    _response, confirm = _offer(call, "restart to update")
    call(EXECUTE, confirm)
    again = call(EXECUTE, confirm)
    assert restarts == ["b-2"] and again["kind"] == "already-done"
    said = "the replayed Missoni soffit is 90 mm"
    _response, confirm = _offer(call, "remember: " + said)
    first = call(EXECUTE, confirm)
    second = call(EXECUTE, confirm)
    assert first["kind"] == "remembered" and second["kind"] == "already-done"
    held = [f for f in brain.context("replayed Missoni soffit")["facts"] if f["text"] == said]
    assert len(held) == 1, "a double press stored the fact twice"


def test_a_failed_act_is_not_reported_done_and_a_re_press_acts(graph):
    """The Brain is not bound when he presses: nothing is stored, and the
    re-press (once the Brain answers) stores it -- never "Already done"."""
    store, registry = graph
    said = "the failed-then-kept Missoni coping is 40 mm"
    call, _ = _server(graph)
    _response, confirm = _offer(call, "remember: " + said)
    app_brain.unbind(store)
    with pytest.raises(InvalidCell, match="did not keep it"):
        call(EXECUTE, confirm)
    app_brain.bind(store, registry)
    try:
        again = call(EXECUTE, confirm)
        assert again["kind"] == "remembered", again
        held = [f for f in app_brain.context("failed kept Missoni coping")["facts"] if f["text"] == said]
        assert len(held) == 1
    finally:
        app_brain.unbind(store)


def test_a_concurrent_press_waits_and_reports_the_real_outcome(graph, brain, monkeypatch):
    import time as _time
    said = "the concurrently pressed Missoni parapet is 1100 mm"
    call, _ = _server(graph)
    _response, confirm = _offer(call, "remember: " + said)
    real_write = brain.write

    def slow_write(ops, *, actor=None):
        _time.sleep(0.3)
        return real_write(ops, actor=actor)

    monkeypatch.setattr(brain, "write", slow_write)
    results = []
    presses = [threading.Thread(target=lambda: results.append(call(EXECUTE, confirm))) for _ in range(2)]
    presses[0].start()
    _time.sleep(0.05)
    presses[1].start()
    for press in presses:
        press.join(10)
    kinds = sorted(result["kind"] for result in results)
    assert kinds == ["already-done", "remembered"], results
    done = next(result for result in results if result["kind"] == "already-done")
    assert "Remembered in your Brain" in done["summary"], "the second press reports the real outcome"
    held = [f for f in brain.context("concurrently pressed Missoni parapet")["facts"] if f["text"] == said]
    assert len(held) == 1


def test_a_second_press_during_a_pending_restart_never_reports_completion(graph):
    """Review 2026-09-30: the confirmation was settled before the restart
    callback ran. The real route now keeps it running through the callback:
    a second press waits, and when the callback fails after it may have
    scheduled a shutdown, neither press reports completion and the
    confirmation is never replayed."""
    import time as _time
    gate, entered, calls = threading.Event(), threading.Event(), []

    def lifecycle(build_id):
        calls.append(build_id)
        entered.set()
        gate.wait(10)
        raise RuntimeError("desktop lifecycle lost after scheduling")

    call, _ = _server(graph, staged={"build_id": "b-2", "tag": "v9"}, request_restart=lifecycle)
    _response, confirm = _offer(call, "restart to update")
    outcomes = {}

    def press(name):
        try:
            outcomes[name] = call(EXECUTE, confirm)
        except Exception as refusal:  # noqa: BLE001 -- the court records what each press saw
            outcomes[name] = refusal

    first = threading.Thread(target=press, args=("first",))
    first.start()
    assert entered.wait(10), "the restart callback never ran"
    press("second")  # answered at once, never waits
    assert isinstance(outcomes["second"], InvalidCell) and "still running" in str(outcomes["second"])
    gate.set()
    first.join(10)
    assert isinstance(outcomes["first"], InvalidCell) and "not known" in str(outcomes["first"])
    with pytest.raises(InvalidCell, match="not known"):
        call(EXECUTE, confirm)
    assert calls == ["b-2"], "an uncertain restart was requested again"


def test_a_pending_real_restart_never_holds_the_graph_lock(tmp_path):
    """The real ApplicationUpdate.reload -> Event.set, held pending by the
    updater's own lock (a concurrent update check). While the confirmation
    is running: a second press is answered at once, and an unrelated graph
    mutation (a task) completes. Then the real reload finishes, the event is
    set, and the confirmation is spent."""
    from nodelang.application_update import ApplicationUpdate
    from nodelang.map_import import resolve_map_path
    from nodelang.universal_application import build_universal_application
    graph = build_universal_application(resolve_map_path())  # its own: this court creates Work
    state_dir, app_dir = _stage_on_disk(tmp_path)
    restart_requested = threading.Event()
    update = ApplicationUpdate(state_dir, app_dir, request_restart=restart_requested.set)
    call, _ = _server(graph, staged={"build_id": ON_DISK[0]}, request_restart=update.reload)
    _response, confirm = _offer(call, "restart to update")
    outcome = {}
    with update._lock:  # the updater is busy: reload waits here
        first = threading.Thread(target=lambda: outcome.setdefault("first", call(EXECUTE, confirm)))
        first.start()
        deadline = __import__("time").monotonic() + 10
        ledger = call.fake._baboom_confirm_ledger()
        while not any(r["state"] == "running" for r in ledger._used.values()):
            assert __import__("time").monotonic() < deadline, "the confirmation never started"
            __import__("time").sleep(0.01)
        with pytest.raises(InvalidCell, match="still running"):
            call(EXECUTE, confirm)
        assert call.fake.mutation_lock.acquire(timeout=2), "a pending restart held the graph lock"
        call.fake.mutation_lock.release()
        task = call(EXECUTE, "Assign task: check the stair schedule while an update waits")
        assert task["created"] in (True, False) and task["state"] == "open"
        assert not restart_requested.is_set()
    first.join(10)
    assert restart_requested.is_set(), "the real reload never requested the restart"
    assert outcome["first"]["kind"] == "update-ready"
    assert call(EXECUTE, confirm)["kind"] == "already-done"


def test_a_committed_remember_whose_answer_was_lost_is_reconciled_not_rewritten(graph, brain, monkeypatch):
    """The write commits and its answer is lost: the re-press finds the fact
    by its receipt id and settles; it never writes a second time."""
    said = "the lost-answer Missoni cornice is 450 mm"
    call, _ = _server(graph)
    _response, confirm = _offer(call, "remember: " + said)
    real_write, writes = brain.write, []

    def committed_then_lost(ops, *, actor=None):
        writes.append(ops)
        real_write(ops, actor=actor)
        raise OSError("response lost after commit")

    monkeypatch.setattr(brain, "write", committed_then_lost)
    with pytest.raises(InvalidCell, match="not known"):
        call(EXECUTE, confirm)
    again = call(EXECUTE, confirm)
    assert again["kind"] == "remembered" and again["data"]["reconciled"] is True, again
    assert len(writes) == 1, "the re-press wrote the fact a second time"
    held = [f for f in brain.context("lost answer Missoni cornice")["facts"] if f["text"] == said]
    assert len(held) == 1


def test_an_uncertain_remember_that_left_nothing_is_written_once_on_re_press(graph, brain, monkeypatch):
    said = "the never-written Missoni plinth is 150 mm"
    call, _ = _server(graph)
    _response, confirm = _offer(call, "remember: " + said)
    real_write = brain.write

    def lost_before_commit(ops, *, actor=None):
        raise OSError("pipe closed before the write")

    monkeypatch.setattr(brain, "write", lost_before_commit)
    with pytest.raises(InvalidCell, match="not known"):
        call(EXECUTE, confirm)
    monkeypatch.setattr(brain, "write", real_write)
    again = call(EXECUTE, confirm)
    assert again["kind"] == "remembered" and not again["data"].get("reconciled"), again
    held = [f for f in brain.context("never written Missoni plinth")["facts"] if f["text"] == said]
    assert len(held) == 1


def test_an_act_in_flight_is_never_evicted_from_the_ledger():
    from nodelang.universal_application import BaboomConfirmations
    ledger = BaboomConfirmations()
    pending = ledger.issue(intent="remember", utterance="remember: the pending one")
    assert ledger.take(pending)[0] == "fresh"
    for index in range(ledger._kept_used + 10):
        nonce = ledger.issue(intent="remember", utterance="remember: fact %d" % index)
        assert ledger.take(nonce)[0] == "fresh"
        ledger.settle(nonce, {"kind": "remembered", "summary": "ok"})
    assert ledger._used[pending]["state"] == "running", "an act in flight lost its record"
    assert ledger.take(pending)[0] == "running", "a press during the act is answered at once"
    ledger.settle(pending, {"kind": "remembered", "summary": "Remembered."})
    state, record = ledger.take(pending)
    assert state == "used" and record["result"]["summary"] == "Remembered."


def test_the_confirmed_build_is_the_only_build_the_next_boot_can_arm(graph, tmp_path, monkeypatch):
    """reload(expected) records the confirmed build; arm_update refuses to arm
    any other staged build, and the next boot installs only what was armed."""
    from nodelang import application_update_recovery as recovery
    from nodelang.application_update import ApplicationUpdate
    state_dir, app_dir = _stage_on_disk(tmp_path)
    update = ApplicationUpdate(state_dir, app_dir, request_restart=lambda: None)
    update.reload(ON_DISK[0])
    assert update.confirmed_build == ON_DISK[0]
    monkeypatch.setattr(recovery, "_capture", lambda *a: {"staged": {"build_id": "20260918-0900-0e0e0e0"}})
    with pytest.raises(ValueError, match="not the confirmed build"):
        recovery.arm_update(state_dir, app_dir, None, None, None, expected_build=update.confirmed_build)
    assert not (state_dir / "updates" / recovery._MARKER_NAME).exists()
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "expected_build=server.application_update.confirmed_build" in launcher


def test_an_expired_confirmation_is_refused(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    ledger = call.fake._baboom_confirm_ledger()
    now = [1000.0]
    ledger._clock = lambda: now[0]
    _response, confirm = _offer(call, "restart to update")
    now[0] += ledger.lifetime_seconds + 1
    with pytest.raises(InvalidCell):
        call(EXECUTE, confirm)
    assert restarts == []


def test_a_confirmation_that_was_never_issued_is_refused(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2", "tag": "v9"})
    with pytest.raises(InvalidCell):
        call(EXECUTE, "confirm " + "d" * 32)
    assert restarts == []


def test_execute_with_nothing_staged_does_not_restart(graph):
    call, restarts = _server(graph, staged={"build_id": "b-2"})
    _response, confirm = _offer(call, "restart to update")
    call.state["staged"] = {}
    result = call(EXECUTE, confirm)
    assert restarts == [] and result["data"]["restart"] is False


def test_the_route_that_can_restart_proves_who_asked(graph):
    """Over the pipe, only the founder session reaches the restart."""
    call, restarts = _server(graph, staged={"build_id": "b-2"})
    _response, confirm = _offer(call, "restart to update")
    call.state["caller"] = "app:agent-session:runtime:" + "9" * 32
    with pytest.raises(server_module.AuthorizationDenied):
        call(EXECUTE, confirm, piped=True)
    assert restarts == []
    call.state["caller"] = graph[1].agent_body.session.root_id
    call(EXECUTE, confirm, piped=True)
    assert restarts == ["b-2"]


# -- 2. every menu row answers ------------------------------------------------

def _menu_phrases():
    source = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    menu = source[source.index("def contextMenuEvent"):source.index("def mousePressEvent")]
    phrases = set(re.findall(r'_say\("([^"%]+)"\)', menu))
    know = menu[menu.index('k = menu.addMenu("Know")'):menu.index("menu.addSeparator()")]
    phrases |= {phrase for _label, phrase in re.findall(r'\("([^"]+)", "([^"]+)"\)', know)}
    graph_rows = menu[menu.index('g = menu.addMenu('):menu.index('w = menu.addMenu(')]
    phrases |= {"run %s on the graph" % e for e in re.findall(r'\("[^"]+", "([a-z_]+\.[a-z_]+)"\)', graph_rows)}
    host_rows = menu[menu.index('h = menu.addMenu('):menu.index('k = menu.addMenu(')]
    phrases |= {"open " + h for _l, h in re.findall(r'\("([^"]+)", "([a-z]+)"\)', host_rows)}
    assert "repo status" in phrases and "brain health" in phrases
    return sorted(phrases)


@pytest.mark.parametrize("phrase", _menu_phrases())
def test_every_menu_phrase_answers(graph, phrase, monkeypatch):
    from nodelang import baboom_agent_link
    monkeypatch.setattr(baboom_agent_link, "list_agents", lambda: [])
    response = _respond(graph, phrase)
    assert response["kind"] != "not-in-this-build", response["summary"]


@pytest.mark.parametrize("phrase", [
    "repo status", "audit repository", "audit worktree",
    "check brain maintenance readiness",
    "show model result", "show latest model result",
])
def test_the_catalogue_commands_that_had_no_handler_answer(graph, phrase):
    response = _respond(graph, phrase)
    assert response["kind"] != "not-in-this-build", response["summary"]
    assert response["summary"].strip()


def test_repo_status_runs_git_outside_the_graph_lock(graph, monkeypatch):
    import subprocess
    call, _ = _server(graph)
    seen = []

    def held_elsewhere():
        # The lock is re-entrant: ask from another thread whether it is free.
        free = []
        probe = threading.Thread(target=lambda: free.append(
            call.fake.mutation_lock.acquire(blocking=False) and (call.fake.mutation_lock.release() or True)))
        probe.start()
        probe.join()
        return not free[0]

    def fake_run(args, **kwargs):
        seen.append((list(args), held_elsewhere()))
        return subprocess.CompletedProcess(args, 0, "## main\n M a.py\n?? b.py\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = call(RESPOND, "repo status")
    assert seen and "status" in seen[0][0], "repo status must read the checkout"
    assert seen[0][1] is False, "git ran while the graph mutation lock was held"
    response = result["response"]
    assert response["kind"] == "repo-status"
    assert response["data"]["changed"] == 1 and response["data"]["untracked"] == 1


def test_brain_maintenance_readiness_follows_brain_health(graph):
    from nodelang.universal_application import respond_universal_baboom_utterance
    store, registry = graph
    context = registry.authorization.session.context()
    down = respond_universal_baboom_utterance(
        store, registry, utterance="check brain maintenance readiness",
        authentication_context=context, brain_state={"ok": False, "facts": 0}, hosts=[])
    assert down["response"]["data"]["ready"] is False


def test_the_menu_offers_remember_and_the_catalogue_holds_it():
    import nodelang.universal_application as ua
    assert "remember" in ua._BABOOM_ACT_INTENTS
    assert any(intent == "remember" for intent, _aliases in ua._BABOOM_COMMAND_SPECS)


@pytest.mark.parametrize("phrase", ["tell an agent", "agent-message", "interrupt an agent", "agent-interrupt"])
def test_the_bare_agent_phrases_answer_instead_of_crashing(graph, phrase):
    """The catalogue alias used to reach json.loads with its own words."""
    response = _respond(graph, phrase)
    assert response["kind"].endswith("-howto"), response
    call, _ = _server(graph)
    with pytest.raises(InvalidCell, match="name the agent"):
        call(EXECUTE, phrase)


# -- 2b. remember writes the founder's Brain, sealed, once per confirmation --

def test_remember_asks_first_then_the_fact_is_recallable_and_sealed(graph, brain):
    store, _registry = graph
    said = "the Missoni stair riser is 172 mm"
    call, _ = _server(graph)
    response, confirm = _offer(call, "remember: " + said)
    assert response["kind"] == "remember-ready"
    digest = hashlib.sha256(said.encode("utf-8")).hexdigest()
    assert response["data"]["sha256"] == digest and response["data"]["length"] == len(said)
    assert "%d characters" % len(said) in response["summary"] and digest[:12] in response["summary"]
    assert said not in {f["text"] for f in brain.context("Missoni stair riser")["facts"]}, "respond must not write"
    result = call(EXECUTE, confirm)
    assert result["kind"] == "remembered", result
    match = [f for f in brain.context("Missoni stair riser")["facts"] if f["text"] == said]
    assert match
    fragment = match[0]["id"]
    snapshot = store.snapshot()
    assert classification(snapshot, session_root=brain.SESSION_ROOT,
                          fragment_id=fragment).ceiling == SEALED
    for lake in ("personal", "community"):
        assert may_release(snapshot, session_root=brain.SESSION_ROOT,
                           fragment_id=fragment, to_lake=lake).allowed is False


def test_the_remember_confirmation_holds_the_whole_fact(graph, brain):
    """A long fact is shown cut short but the confirmation stores all of it."""
    said = "the Staller facade module schedule " + "x" * 200 + " ends here"
    call, _ = _server(graph)
    response, confirm = _offer(call, "remember: " + said)
    assert "..." in response["summary"] and "%d characters" % len(said) in response["summary"]
    call(EXECUTE, confirm)
    assert said in {f["text"] for f in brain.context("Staller facade module schedule")["facts"]}


def test_remembering_again_never_overwrites_an_edited_fact(graph, brain):
    said = "the Jumeirah villa slab is 250 mm"
    call, _ = _server(graph)
    call(EXECUTE, _offer(call, "remember: " + said)[1])
    first = [f["id"] for f in brain.context("Jumeirah villa slab")["facts"] if f["text"] == said]
    assert len(first) == 1
    assert brain.edit_fact(first[0], "the Jumeirah villa slab is 300 mm")["ok"] is True
    call(EXECUTE, _offer(call, "remember: " + said)[1])
    texts = {f["id"]: f["text"] for f in brain.context("Jumeirah villa slab")["facts"]}
    assert texts[first[0]] == "the Jumeirah villa slab is 300 mm", "the edit was overwritten"
    assert said in texts.values()


def test_remember_over_the_pipe_needs_the_founder_session(graph, brain):
    said = "the Staller cladding module is 1200 mm"
    call, _ = _server(graph)
    _response, confirm = _offer(call, "remember: " + said)
    call.state["caller"] = "app:agent-session:runtime:" + "9" * 32
    with pytest.raises(server_module.AuthorizationDenied):
        call(EXECUTE, confirm, piped=True)
    assert said not in {f["text"] for f in brain.context("Staller cladding")["facts"]}


def test_remember_with_nothing_to_remember_writes_nothing(graph):
    response = _respond(graph, "remember")
    assert response["kind"] == "remember-empty"
    assert "requires" not in response["data"]
