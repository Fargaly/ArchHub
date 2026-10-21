"""BABOOM5 acceptance at the native host, shared core and mounted Qt seams."""
from tests_replica.test_goose_brain import packaged
from pathlib import Path
import time
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
from PyQt6.QtWebEngineWidgets import QWebEngineView

from nodelang.baboom_native_host import BaboomNativeHost
from tests_replica.test_baboom_native_host import _Transport


def test_restart_reattaches_without_replaying_an_ask():
    class Transport(_Transport):
        runtime = "runtime-one"
        bound = "runtime-one"

        def replacement_for_current_runtime(self):
            if self.runtime == self.bound:
                return self
            replacement = Transport()
            replacement.runtime = replacement.bound = self.runtime
            return replacement

    transport = Transport()
    host = BaboomNativeHost(transport, external_session_id="baboom5",
        device_credential_provider=lambda challenge: {"proof": "approved"})
    host.connect()
    transport.runtime = "runtime-two"
    start = time.monotonic()
    host.poll()
    assert host._transport is not transport
    assert len(host._transport.binds) == 1
    assert host.latest_snapshot.frame_expires_at > time.time()
    assert host._transport.executions == []
    assert host._transport.briefing_calls == 0
    assert time.monotonic() - start < 2.0
    print("BABOOM5 restart: live within 2.0 seconds; zero command replays")


def test_verified_successor_gets_a_fresh_client_without_old_tokens(monkeypatch, tmp_path):
    from dataclasses import replace
    from nodelang.application_machine_transport import RuntimeDescriptor, UniversalRuntimeClient
    descriptor = RuntimeDescriptor("old", "active", "fake", 1, "", "", "app", "session", "workshop", "work", "", "key", 1, "signature")
    client = UniversalRuntimeClient(tmp_path / "unused.json", object())
    client._baboom_bound_runtime = "old"
    client.agent_session_root = "old-session"
    client._agent_session_token = "old-token"
    monkeypatch.setattr(client, "_verified_owner", lambda: descriptor)
    assert client.replacement_for_current_runtime() is client
    successor = replace(descriptor, runtime_id="new", pipe="new-fake")
    monkeypatch.setattr(client, "_verified_owner", lambda: successor)
    fresh = client.replacement_for_current_runtime()
    assert fresh is not client
    assert fresh._pinned_runtime_descriptor == successor
    assert fresh.agent_session_root == fresh._agent_session_token == ""
    assert fresh.enrollment_sent is False


def test_background_host_automatically_reattaches_within_three_seconds():
    class Transport(_Transport):
        successor = None
        def replacement_for_current_runtime(self): return self.successor or self
    old, successor = Transport(), Transport()
    host = BaboomNativeHost(old, external_session_id="baboom5-background",
        device_credential_provider=lambda _: {})
    host.connect()
    successor.context["revision"] = 99
    host.start()
    try:
        initial = time.monotonic()
        while old.frame_calls < 2 and time.monotonic() - initial < 3.0:
            time.sleep(0.01)
        assert old.frame_calls >= 2, "old runtime is already being polled in the background"
        started = time.monotonic()
        old.successor = successor
        while host.latest_snapshot.revision != 99 and time.monotonic() - started < 3.0:
            time.sleep(0.01)
        assert successor.binds and time.monotonic() - started < 3.0
        assert host.latest_snapshot.revision == 99
        assert host.latest_snapshot.frame_expires_at > time.time()
        assert not successor.executions
    finally:
        host.stop()


def test_live_tool_steps_arrive_before_the_result():
    from nodelang.native_agentic_loop import ToolSpec, run_agentic_tool_loop, observe_steps
    events = []
    def tool(name, arguments):
        assert events[-1]["status"] == "running"
        return "Current drawing read"
    answers = iter([{"tool_calls": [{"id": "one", "name": "host.read", "arguments": {}}]},
                    {"text": "Drawing ready"}])
    with observe_steps(events.append):
        result = run_agentic_tool_loop(lambda *_: next(answers), {"host.read": ToolSpec("host.read", tool)}, [])
    assert [row["status"] for row in events] == ["running", "ok"]
    assert result["answer"] == "Drawing ready"


def test_native_ask_keeps_real_steps_in_the_response(monkeypatch):
    from nodelang import application_server as server
    from tests_replica.test_baboom_open_question_reaches_the_brain import _Owner
    from nodelang import agent_composer, pipeline_engines
    step = {"tool": "host.ping", "status": "ok", "summary": "Programs available"}
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda *_: ({"out": ""}, ""))
    monkeypatch.setattr(agent_composer, "run_agent_composer", lambda *_, **__: {"answer": "Ready", "steps": [step]})
    owner = _Owner()
    owner._effect_engines_with_mods_store = lambda: {}
    result = server.answer_open_question(owner, "Read my programs", None,
        {"command": {"intent": "open-question"}, "response": {}})
    assert result["response"]["data"]["steps"] == [step]


def test_successor_not_sent_enrollment_can_recover_without_replaying_unknown():
    from nodelang.application_machine_transport import MachineNotSent
    class Transport(_Transport):
        enrollment_sent = False
        replacement = None
        fail_once = False
        def replacement_for_current_runtime(self):
            return self.replacement or self
        def bind_agent_session(self, **kwargs):
            if self.fail_once:
                self.fail_once = False
                raise MachineNotSent("successor is starting")
            return super().bind_agent_session(**kwargs)
    transport, successor = Transport(), Transport()
    host = BaboomNativeHost(transport, external_session_id="baboom5-recovery",
        device_credential_provider=lambda _: {})
    host.connect()
    transport.replacement = successor
    successor.fail_once = True
    import pytest
    with pytest.raises(MachineNotSent):
        host.poll()
    host.poll()
    assert len(successor.binds) == 1
    assert host.connection_state == "live"
    assert not successor.executions


def test_blocked_transport_identity_check_does_not_freeze_the_projection():
    import threading
    transport = _Transport()
    host = BaboomNativeHost(transport, external_session_id="baboom5-lock",
        device_credential_provider=lambda _: {})
    host.connect()
    entered, release = threading.Event(), threading.Event()
    def replacement():
        entered.set()
        assert release.wait(2)
        return transport
    transport.replacement_for_current_runtime = replacement
    worker = threading.Thread(target=host.poll)
    worker.start()
    assert entered.wait(1)
    try:
        assert host._lock.acquire(timeout=0.05), "projection must never await a model/tool transport lock"
        try:
            assert host.latest_snapshot is not None
        finally:
            host._lock.release()
    finally:
        release.set()
        worker.join(2)


def _wait(app, predicate, seconds=5):
    from PyQt6.QtTest import QTest
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "UI did not settle within its bounded wait"


def fake_approval_webview(monkeypatch):
    # WebEngine cannot start on this Windows offscreen QPA backend. The actual
    # HTML/card is mounted and clicked by studio_baboom5.test.cjs; this court
    # exercises its native channel without creating a second Chromium process.
    from PyQt6.QtCore import QObject
    from PyQt6.QtWidgets import QWidget
    import PyQt6.QtWebEngineWidgets as engine
    import PyQt6.QtWebChannel as channel
    class Page(QObject):
        def setBackgroundColor(self, _): pass
        def setWebChannel(self, _): pass
    class View(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self._page = Page(self)
        def page(self): return self._page
        def setHtml(self, html, base): self.html = html
    class Channel(QObject):
        def registerObject(self, name, value): self.bridge = value
    monkeypatch.setattr(engine, "QWebEngineView", View)
    monkeypatch.setattr(channel, "QWebChannel", Channel)


def test_native_shared_approval_adapter_executes_exactly_once(tmp_path, monkeypatch):
    fake_approval_webview(monkeypatch)
    from tests_replica.test_baboom_native_companion import _t13_window
    app, window = _t13_window(tmp_path, "approval.png")
    transport = window.controller._host._transport
    executed = []
    transport.execute_baboom_command = lambda **kwargs: executed.append(kwargs["utterance"]) or {
        "command": {"catalog":"app:baboom-command-catalog:v1", "intent":"remember"},
        "kind":"remembered", "summary":"Remembered blue in your Brain.", "data":{"written":1}}
    window.start_projection()
    window._submitted_utterance = "remember: blue"
    window._open_interaction()
    window._apply_response({"command": {"intent": "remember"}, "response": {
        "kind": "remember-ready", "summary": "Remember blue in your Brain?",
        "data": {"requires": "explicit execute", "confirm_utterance": "confirm " + "a" * 32}}})
    try:
        window._confirm.click()
        assert window._approval.isVisible()
        assert not executed
        assert "ARCHHUB_APPROVAL_CARD" in window._approval.html
        window._approval_bridge.decide(window._approval_binding, "approve")
        _wait(app, lambda: len(executed) == 1 and not window._busy)
        assert executed == ["confirm " + "a" * 32]
        assert window._report.text() == "Remembered blue in your Brain."
        window._approval_bridge.decide("a" * 64, "approve")
        assert len(executed) == 1
    finally:
        window.stop_projection()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_native_busy_ask_stays_responsive_after_frame_expiry_and_dismiss_fences_result(tmp_path):
    from dataclasses import replace
    from tests_replica.test_baboom_native_companion import _t13_window
    app, window = _t13_window(tmp_path, "busy.png")
    window.start_projection()
    host = window.controller._host
    window._open_interaction()
    window._busy = True
    window._transient_report = "brain.context · running"
    host._latest = replace(host.latest_snapshot, frame_expires_at=time.time() - 60)
    window.refresh()
    assert "running" in window._report.text()
    assert not hasattr(window, "_open")
    host.connection_state = "reconnecting"
    window._submitted_utterance = "remember: blue"
    window._apply_response({"command": {"intent": "remember"}, "response": {
        "kind": "remember-ready", "summary": "Remember blue?", "data": {"requires": "explicit execute"}}})
    assert window._confirm.isVisible(), "authenticated response keeps its Review visible before the heartbeat lands"
    assert window._pending_task_utterance == "remember: blue"
    host._transport = object()
    window.refresh()
    assert window._pending_task_utterance is None
    assert not window._confirm.isVisible(), "a successor cannot inherit the old owner's approval"
    generation = window._interaction_generation
    window._close_interaction()
    window._apply_response({"generation": generation, "payload": {"response": {
        "kind": "answer", "summary": "obsolete", "data": {}}}})
    assert "obsolete" not in window._report.text()
    window.stop_projection()
    window.close()


def test_companion_idle_and_asking_render(tmp_path):
    from pathlib import Path
    from PyQt6.QtWidgets import QApplication
    from nodelang.baboom_native_companion import BaboomNativeCompanionController, create_baboom_native_companion_window
    from nodelang.baboom_visual_assets import inspect_baboom_sprite_atlas_v2
    app = QApplication.instance() or QApplication([])
    host = BaboomNativeHost(_Transport(), external_session_id="baboom5-render",
        device_credential_provider=lambda _: {}, emit_steward_signals=False)
    host._transport.context["work"] = {"total":0,"open":0,"claimed":0,"blocked":0,"review":0}
    host.connect()
    atlas = inspect_baboom_sprite_atlas_v2(Path("nodelang/data/baboom/spritesheet.png"))
    window = create_baboom_native_companion_window(BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ()))
    try:
        window.start_projection()
        app.processEvents()
        window.refresh()
        idle = window.grab().toImage()
        sprite = window._sprite_rect
        assert any(idle.pixelColor(x,y).red() > idle.pixelColor(x,y).green() * 1.3
            and idle.pixelColor(x,y).red() > 80 and idle.pixelColor(x,y).alpha() > 0
            for x in range(sprite.left(),sprite.right()) for y in range(sprite.top(),sprite.bottom())), (
                window._frame.source, sprite, window._sprite.size(), window.geometry())
        assert idle.save("evidence/BABOOM5-idle-final.png")
        window._open_interaction()
        window._input.setText("Check the doors in this model")
        app.processEvents()
        assert window._send.isVisible()
        assert window.grab().save("evidence/BABOOM5-asking-final.png")
    finally:
        window.stop_projection()
        window.close()


def test_natural_ask_draft_waits_for_single_use_approval(monkeypatch):
    import json
    from types import SimpleNamespace
    from nodelang import agent_composer as composer, universal_application as app
    from tests_replica.test_agent_composer_action_gate import _Store
    projection = {"nodes": (), "catalog": ({"name": "Review", "id": "definition-root"},), "revision": 1}
    monkeypatch.setattr(app, "project_universal_canvas", lambda *_, **__: projection)
    monkeypatch.setattr(composer, "_chat", lambda *_, **__: json.dumps({
        "actions": [{"op": "place", "definition": "Review"}], "answer": "Proposed Review node."}))
    writes = []
    monkeypatch.setattr(composer, "_apply_draft_actions", lambda *args, **kwargs:
        writes.append(args[4]) or {"answer": "Review node placed.", "applied": [{"ok": True}]})
    store = _Store()
    result = composer.run_agent_composer(store, object(), "Add a Review node to the canvas",
        model="openrouter/free", preview_only=True)
    assert writes == []
    ledger = app.BaboomConfirmations()
    nonce = ledger.issue(intent="composer-draft", utterance=json.dumps({
        "actions": result["pending_actions"], "source_revision": result["source_revision"], "answer": result["answer"]}))
    registry = SimpleNamespace(baboom_command_catalog=SimpleNamespace(root_id="app:baboom-command-catalog:v1"))
    receipt = app.execute_universal_baboom_utterance(store, registry, utterance="confirm " + nonce, confirmations=ledger)
    assert len(writes) == 1
    assert receipt["kind"] == "draft-applied"
    app.execute_universal_baboom_utterance(store, registry, utterance="confirm " + nonce, confirmations=ledger)
    assert len(writes) == 1


def test_signed_progress_frames_keep_request_binding_and_final_result(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    from nodelang import application_machine_transport as machine
    from nodelang.native_agentic_loop import publish_step
    class Connection:
        def __init__(self): self.responses = []; self.request = None
        def poll(self, _): return True
        def send_bytes(self, raw):
            if self.request is None:
                self.request = raw
                server._serve_connection(self.server_side())
            else: self.responses.append(raw)
        def recv_bytes(self, _): return self.responses.pop(0)
        def close(self): pass
        def server_side(self):
            return SimpleNamespace(poll=lambda _:True, recv_bytes=lambda _:self.request,
                send_bytes=lambda raw:self.responses.append(raw))
    server = object.__new__(machine.UniversalRuntimeTransport)
    server.runtime_id = "runtime-court"
    server.after_response = None
    server._remember = lambda _: None
    def dispatch(request):
        publish_step({"tool": "graph.read", "status": "running", "summary": ""})
        publish_step({"tool": "graph.read", "status": "ok", "summary": "Read canvas"})
        return {"answer": "Canvas ready"}
    server.dispatch = dispatch
    connection = Connection()
    monkeypatch.setattr(machine, "Client", lambda *_, **__:connection)
    client = machine.UniversalRuntimeClient(tmp_path / "unused.json", SimpleNamespace(resolve=lambda *_:SimpleNamespace(secret=b"court")))
    monkeypatch.setattr(client, "_verified_owner", lambda:SimpleNamespace(runtime_id="runtime-court",pipe="fake",key_id="key",key_version=1))
    events = []
    result = client.request("POST", "/api/universal/baboom-command-response", {"utterance":"read", "stream_steps":True}, on_progress=events.append)
    assert [row["status"] for row in events] == ["running", "ok"]
    assert result == {"answer": "Canvas ready"}


def test_closed_app_control_uses_the_installer_shortcut_without_launching(monkeypatch, tmp_path):
    from dataclasses import replace
    from PyQt6.QtGui import QDesktopServices
    from tests_replica.test_baboom_native_companion import _t13_window
    shortcut = tmp_path / "Microsoft/Windows/Start Menu/Programs/ArchHub.lnk"
    shortcut.parent.mkdir(parents=True)
    shortcut.touch()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    app, window = _t13_window(tmp_path, "offline.png")
    try:
        host = window.controller._host
        host._latest = replace(host.latest_snapshot, frame_expires_at=time.time() - 60)
        host.connection_state = "closed"
        window.start_projection()
        assert not hasattr(window, "_open")
        assert not window._report.isVisible()
        assert not window.isVisible()
        assert "Reconnecting" in window._tray.toolTip()
        assert window._tray_open.text() == "Open ArchHub"
        window._tray_open.trigger()
        from pathlib import Path
        assert [Path(value) for value in opened] == [shortcut]
    finally:
        window.stop_projection()
        window.close()


def test_ask_over_fake_transport_uses_goose_and_shows_host_result(monkeypatch, tmp_path, packaged):
    from nodelang import agent_composer, application_server, universal_application, pipeline_engines
    from nodelang.native_agentic_loop import observe_steps
    from tests_replica.test_agent_composer_action_gate import _Store
    from tests_replica.test_baboom_open_question_reaches_the_brain import _Owner
    from tests_replica.test_baboom_native_companion import _t13_window
    app, window = _t13_window(tmp_path, "core.png")
    owner = _Owner()
    owner.universal_store = _Store()
    owner._read_agent_model = lambda: "openrouter/free"
    monkeypatch.setattr(universal_application, "project_universal_canvas", lambda *_, **__: {"nodes": [], "catalog": [], "revision": 1})
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda *_: ({"out": ""}, ""))
    from nodelang.goose_adapter import GooseAdapter
    packaged.runtime.start()
    owner.goose_brain = GooseAdapter(packaged.runtime)
    def respond(*, utterance, on_progress):
        with observe_steps(on_progress):
            return application_server.answer_open_question(owner, utterance, None,
                {"command": {"intent": "open-question"}, "response": {}})
    window.controller._host._transport.respond_baboom_command = respond
    try:
        window.start_projection()
        window._say("What can you see?")
        _wait(app, lambda: not window._busy)
        assert packaged.calls == [("GET", "/api/universal/hosts", {})]
        assert "court-fixture.3dm" in window._report.text()
        assert "hosts_state" in window._report.text()
        assert window._steps["hosts_state"]["status"] == "ok"
        window.grab().save(str(Path(__file__).resolve().parents[2] / "05.EVIDENCE/GOOSE-face.png"))
    finally:
        window.stop_projection()
        window.close()
