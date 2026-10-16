"""Installed launcher regressions, retaining the existing signed session owner."""
from types import SimpleNamespace
import pytest

from nodelang.application_machine_transport import MachineNoResponse
from nodelang.baboom_native_host import BaboomNativeHost
from tests_replica.test_baboom_startup_lifecycle import worker_namespace


def test_known_enrollment_survives_a_lost_first_projection(monkeypatch):
    enrolled = []
    transport = SimpleNamespace(agent_session_root="", enrollment_sent=True)

    def enroll(**kwargs):
        enrolled.append(kwargs)
        transport.agent_session_root = "signed-session"

    def busy(**kwargs):
        raise MachineNoResponse("universal runtime did not respond")

    transport.bind_agent_session = enroll
    host = BaboomNativeHost(transport, external_session_id="founder-desktop-baboom",
        device_credential_provider=lambda challenge: {})
    monkeypatch.setattr(host, "poll", busy)
    namespace, _, prepared, delivered, _ = worker_namespace(monkeypatch, host, real_transport=True)
    namespace["_keep_attaching"]()
    assert delivered == [host], "a projection timeout discarded a known signed session"
    assert len(prepared) == 1
    assert len(enrolled) == 1
    assert host._connected
    assert not host._stop.is_set()


def test_native_overlay_ask_round_trips_signed_pipe_with_fake_model(tmp_path, monkeypatch):
    import os
    import time
    from pathlib import Path
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from nodelang.application_machine_transport import UniversalRuntimeClient
    from nodelang.application_server import ApplicationServer
    from nodelang.baboom_native_runtime import create_baboom_native_projection
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from tests_replica.test_application_machine_transport import (
        _bind_runtime_device, _device_credential, _runtime_device_key,
    )

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    descriptor = tmp_path / "runtime.json"
    keys = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"I" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
        machine_key_provider=keys, enable_machine_projection_prewarm=False, live_watch=False).start()
    calls = []

    def fake_model(prompt, context, model, **kwargs):
        calls.append(prompt)
        if kwargs.get("before_dispatch"):
            kwargs["before_dispatch"]()
        return "INSTFIX overlay answer received."

    monkeypatch.setattr(server, "goose_brain", SimpleNamespace(ask=fake_model), raising=False)
    monkeypatch.setattr(server, "_read_agent_model", lambda: "openrouter/free")
    monkeypatch.setattr(server, "_brain_state", lambda: {"ok": True, "facts": 0})
    monkeypatch.setattr(server, "_host_rows", lambda: [])
    from nodelang import pipeline_engines
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda *args: ({"out": ""}, "court"))
    host = window = None
    try:
        key, reference = _runtime_device_key()
        custody = _bind_runtime_device(server, reference, runtime="baboom")
        external = "instfix-overlay"
        transport = UniversalRuntimeClient(descriptor, keys)
        host = BaboomNativeHost(transport, external_session_id=external,
            device_credential_provider=lambda challenge: _device_credential(key, custody, challenge, external),
            emit_steward_signals=False)
        host.connect()
        window = create_baboom_native_projection(host)
        window.start_projection()
        window._open_interaction()
        window._input.setText("Can you answer my question about this project?")
        started = time.monotonic()
        QTest.keyClick(window._input, Qt.Key.Key_Return)
        while window._busy and time.monotonic() - started < 20:
            application.processEvents()
            QTest.qWait(10)
        elapsed = time.monotonic() - started
        assert not window._busy, "BABOOM overlay ask exceeded 20 seconds"
        assert len(calls) == 1
        assert "INSTFIX overlay answer received." in window._report.text()
        evidence = Path(__file__).resolve().parents[1] / "evidence"
        assert window.grab().save(str(evidence / "instfix-baboom-overlay.png"))
        print("CANDIDATE NATIVE OVERLAY: signed-pipe ask answered in %.3f s; fake model calls=%d" % (elapsed, len(calls)))
    finally:
        if window is not None:
            window.stop_projection()
            window.close()
        if host is not None:
            host.stop()
        server.close()


@pytest.mark.parametrize("state", ["reconnecting", "closed"])
def test_offline_companion_is_an_avatar_indicator_not_a_message_panel(state):
    from dataclasses import replace
    from pathlib import Path
    import time
    from PyQt6.QtWidgets import QApplication
    from nodelang.baboom_native_runtime import create_baboom_native_projection
    from tests_replica.test_baboom_native_companion import _Transport
    application = QApplication.instance() or QApplication([])
    host = BaboomNativeHost(_Transport(), external_session_id="instfix-offline",
        device_credential_provider=lambda challenge: {})
    host.connect()
    host._latest = replace(host.latest_snapshot, frame_expires_at=time.time() - 20)
    host.connection_state = state
    window = create_baboom_native_projection(host)
    evidence = Path(__file__).resolve().parents[1] / "evidence"
    try:
        window.start_projection()
        application.processEvents()
        before = evidence / ("instfix-" + state + "-before.png")
        if not before.exists():
            assert window.grab().save(str(before))
        assert not window._report.isVisible(), "offline rendered a wide message panel"
        assert window._message_rect is None
        assert window._open.isVisible() is (state == "closed")
        if state == "closed":
            assert window._open.width() <= 28
        assert window._connection_status.isVisible()
        assert window.grab().save(str(evidence / ("instfix-" + state + "-after.png")))
    finally:
        window.stop_projection()
        window.close()
        host.stop()


def test_slow_projection_does_not_declare_a_proven_runtime_disconnected(monkeypatch):
    host = BaboomNativeHost(SimpleNamespace(agent_session_root="signed-session"), external_session_id="slow-frame",
        device_credential_provider=lambda challenge: {})
    host.connection_state = "live"

    def timeout():
        host._stop.set()
        raise MachineNoResponse("universal runtime did not respond")

    monkeypatch.setattr(host, "poll", timeout)
    host._run()
    assert host.connection_state == "live"
