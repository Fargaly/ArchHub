from __future__ import annotations

import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import nodelang.authority_bridge as authority_bridge
from nodelang.authority_bridge import main, run_bridge


def test_authority_bridge_probe_is_universal_cell_only(tmp_path):
    state_path = tmp_path / "node-native-wip.json.gz"
    descriptor_path = tmp_path / "active-universal-runtime.json"
    status_path = tmp_path / "authority-bridge.json"

    result = run_bridge(
        state_path=state_path,
        descriptor_path=descriptor_path,
        status_path=status_path,
        probe=True,
    )

    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["status"] in {"active", "degraded"}
    assert result["machine_transport"] is True
    assert result["legacy_runtime_enabled"] is False
    assert result["application"] == "app:archhub"
    assert result["registry"] == "app:governed-work-registry"
    assert result["proof"]["ok"] is True
    assert result["prewarm"]["status"] in {"not-run", "warming", "warm"}
    assert result["proof"]["application"] == result["application"]
    assert result["proof"]["registry"] == result["registry"]
    assert descriptor["status"] == "stopped"
    assert status["status"] == "stopped"
    assert status["legacy_runtime_enabled"] is False


def test_authority_bridge_cli_probe_prints_machine_transport_payload(
    tmp_path,
    capsys,
):
    code = main([
        "--probe",
        "--state-path", str(tmp_path / "node-native-wip.json.gz"),
        "--descriptor-path", str(tmp_path / "active-universal-runtime.json"),
        "--status-path", str(tmp_path / "authority-bridge.json"),
    ])

    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["status"] in {"active", "degraded"}
    assert output["machine_transport"] is True
    assert output["legacy_runtime_enabled"] is False
    assert output["proof"]["ok"] is True
    assert output["prewarm"]["status"] in {"not-run", "warming", "warm"}


def test_authority_bridge_keeps_runtime_active_while_background_prewarm_runs(
    monkeypatch,
    tmp_path,
):
    order = []
    closed = []

    class FakeServer:
        machine_transport = SimpleNamespace(is_serving=True)
        universal_registry = SimpleNamespace(
            application_root="app:archhub",
            governed_work_registry_root="app:governed-work-registry",
            workshop_root="app:workshop",
        )
        _runtime_ownership_root = "ownership:bridge"
        universal_state_path = tmp_path / "universal.sqlite3"
        url = "http://127.0.0.1:65535"
        legacy_runtime_enabled = False
        thread = None

        def start(self):
            order.append("start")

        def close(self):
            closed.append(True)

        def prewarm_universal_machine_read_projections(self):
            raise AssertionError("bridge startup must not synchronously prewarm")

        def universal_machine_projection_prewarm_status(self):
            order.append("prewarm-status")
            return {"ok": False, "status": "warming", "revision": 12}

    def proof(_server, _descriptor_path):
        assert order == ["start", "prewarm-status"]
        order.append("proof")
        return {"ok": True, "proof_route": "GET /api/universal/browser-handoff"}

    monkeypatch.setattr(authority_bridge, "_build_server", lambda **_kwargs: FakeServer())
    monkeypatch.setattr(authority_bridge, "_safe_proof", proof)

    result = authority_bridge.run_bridge(
        state_path=tmp_path / "node-native-wip.json.gz",
        descriptor_path=tmp_path / "active-universal-runtime.json",
        status_path=tmp_path / "authority-bridge.json",
        probe=True,
    )

    assert order == ["start", "prewarm-status", "proof"]
    assert closed == [True]
    assert result["status"] == "active"
    assert result["prewarm"]["status"] == "warming"


def test_authority_bridge_cli_refuses_implicit_persistent_ownership(
    monkeypatch,
):
    invoked = []
    monkeypatch.setattr(
        authority_bridge,
        "run_bridge",
        lambda **_kwargs: invoked.append(True),
    )

    assert main([]) == 2
    assert invoked == []


def test_authority_bridge_exposes_no_offline_baboom_repair_authority():
    assert not hasattr(authority_bridge, "repair_legacy_baboom_authority")
    with pytest.raises(SystemExit):
        main(["--repair-legacy-baboom-authority", "--founder-approved"])


def test_headless_bridge_prewarms_only_the_work_index(monkeypatch, tmp_path):
    captured = {}

    class Credentials:
        token = "t" * 43
        csrf_token = "c" * 43
        custody_id = "custody:test"

    class Vault:
        def __init__(self, _path):
            return None

        def load_or_create(self):
            return Credentials()

    class Server:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(authority_bridge, "BrowserCredentialVault", Vault)
    monkeypatch.setattr(authority_bridge, "ApplicationServer", Server)

    authority_bridge._build_server(
        state_path=tmp_path / "authority.json.gz",
        descriptor_path=tmp_path / "runtime.json",
    )

    assert captured["enable_machine_projection_prewarm"] is True
    assert captured["machine_projection_prewarm_targets"] == ("work",)


def test_bridge_proof_is_bounded_and_proof_failures_are_safe_status(monkeypatch, tmp_path):
    captured = {}

    class FakeClient:
        def __init__(self, descriptor_path, key_provider):
            captured["descriptor_path"] = descriptor_path
            captured["key_provider"] = key_provider

        def request(self, method, path, body, **kwargs):
            captured["request"] = (method, path, body, kwargs)
            return {
                "application": "app:archhub",
                "agent_session": "app:agent-session:founder",
                "supported": True,
                "one_use_route": "POST /api/universal/browser-handoff",
                "revision": 42,
                "server_url": "http://127.0.0.1:61663",
            }

    server = SimpleNamespace(
        machine_transport=SimpleNamespace(key_provider=object()),
        universal_registry=SimpleNamespace(
            application_root="app:archhub",
            governed_work_registry_root="app:governed-work-registry",
            workshop_root="app:workshop",
        ),
    )
    monkeypatch.setattr(authority_bridge, "UniversalRuntimeClient", FakeClient)

    proof = authority_bridge._proof(server, tmp_path / "descriptor.json")

    assert proof["ok"] is True
    assert captured["request"] == (
        "GET",
        "/api/universal/browser-handoff",
        {},
        {"response_timeout_seconds": authority_bridge.BRIDGE_PROOF_TIMEOUT_SECONDS},
    )
    assert proof["proof_route"] == "GET /api/universal/browser-handoff"

    monkeypatch.setattr(
        authority_bridge,
        "_proof",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("universal runtime did not respond")),
    )
    assert authority_bridge._safe_proof(server, tmp_path / "descriptor.json") == {
        "ok": False,
        "reason": "machine transport did not answer inside the bridge proof window",
        "error_type": "RuntimeError",
    }


def test_bridge_proof_retries_transient_transport_timeout(monkeypatch, tmp_path):
    calls = []

    def flaky_proof(_server, _descriptor_path):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("universal runtime did not respond")
        return {"ok": True, "proof_route": "GET /api/universal/browser-handoff"}

    monkeypatch.setattr(authority_bridge, "_proof", flaky_proof)
    monkeypatch.setattr(authority_bridge.time, "sleep", lambda _seconds: None)

    proof = authority_bridge._safe_proof(SimpleNamespace(), tmp_path / "descriptor.json")

    assert proof == {"ok": True, "proof_route": "GET /api/universal/browser-handoff"}
    assert len(calls) == 2


def test_authority_bridge_persists_a_pipe_worker_failure(monkeypatch, tmp_path):
    status_path = tmp_path / "authority-bridge.json"
    closed = []

    class DeadThread:
        def join(self, timeout):
            assert timeout == 1.0

        def is_alive(self):
            return True

    server = SimpleNamespace(
        thread=DeadThread(),
        machine_transport=SimpleNamespace(is_serving=False),
        universal_registry=SimpleNamespace(
            application_root="app:archhub",
            governed_work_registry_root="app:governed-work-registry",
            workshop_root="app:workshop",
        ),
        _runtime_ownership_root="ownership:bridge",
        universal_state_path=tmp_path / "universal.sqlite3",
        url="http://127.0.0.1:65535",
        legacy_runtime_enabled=False,
        start=lambda: None,
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(authority_bridge, "_build_server", lambda **_kwargs: server)
    monkeypatch.setattr(authority_bridge, "_safe_proof", lambda *_args: {"ok": True})

    try:
        authority_bridge.run_bridge(
            state_path=tmp_path / "node-native-wip.json.gz",
            descriptor_path=tmp_path / "active-universal-runtime.json",
            status_path=status_path,
            stop_event=threading.Event(),
        )
    except RuntimeError as exc:
        assert str(exc) == "authority bridge machine transport worker stopped"
    else:  # pragma: no cover - the assertion above is the court's purpose
        raise AssertionError("dead machine transport must fail the bridge")

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert closed == [True]
    assert payload["status"] == "failed"
    assert payload["proof"] == {
        "ok": False,
        "reason": "machine transport worker stopped",
        "error_type": "RuntimeError",
    }


def test_authority_bridge_stays_alive_until_an_explicit_stop(monkeypatch, tmp_path):
    state_path = tmp_path / "node-native-wip.json.gz"
    descriptor_path = tmp_path / "active-universal-runtime.json"
    status_path = tmp_path / "authority-bridge.json"
    stop_event = threading.Event()
    failures = []
    entered_loop = threading.Event()
    closed = []

    class AliveThread:
        def join(self, timeout):
            assert timeout == 1.0
            entered_loop.set()
            stop_event.wait(0.01)

        def is_alive(self):
            return True

    server = SimpleNamespace(
        thread=AliveThread(),
        machine_transport=SimpleNamespace(is_serving=True),
        universal_registry=SimpleNamespace(
            application_root="app:archhub",
            governed_work_registry_root="app:governed-work-registry",
            workshop_root="app:workshop",
        ),
        _runtime_ownership_root="ownership:bridge",
        universal_state_path=tmp_path / "universal.sqlite3",
        url="http://127.0.0.1:65535",
        legacy_runtime_enabled=False,
        start=lambda: None,
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(authority_bridge, "_build_server", lambda **_kwargs: server)
    monkeypatch.setattr(authority_bridge, "_safe_proof", lambda *_args: {"ok": True})

    def run():
        try:
            authority_bridge.run_bridge(
                state_path=state_path,
                descriptor_path=descriptor_path,
                status_path=status_path,
                stop_event=stop_event,
            )
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered_loop.wait(1.0)
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        assert payload["status"] == "active"
        assert payload["proof"]["ok"] is True
        assert worker.is_alive()
    finally:
        stop_event.set()
        worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert failures == []
    assert closed == [True]
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "stopped"
