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


def _retired_offline_baboom_repair_is_checkpointed_backed_up_and_cleans_staging(
    monkeypatch,
    tmp_path,
):
    state_path = tmp_path / "authority.json.gz"
    database_path = tmp_path / "authority.json.gz.universal.sqlite3"
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    backup_path = recovery / "pre-repair.sqlite3"
    staging_path = recovery / "staging.sqlite3"
    database_path.write_bytes(b"authority")
    order = []

    class FakeKeyProvider:
        @staticmethod
        def default_path():
            return tmp_path / "keys.dpapi"

        def __init__(self, path):
            order.append(("key-provider", path))

    class FakeStore:
        revision = 13

        def __init__(self, path):
            assert Path(path) == database_path.resolve()
            order.append("store-open")

        def snapshot(self):
            order.append("snapshot")
            return SimpleNamespace(revision=12)

        def backup_to(self, path):
            order.append("backup")
            Path(path).write_bytes(b"backup")

        def close(self):
            order.append("store-close")

    class FakeGuard:
        @staticmethod
        def default_path(path):
            assert Path(path) == database_path.resolve()
            return tmp_path / "checkpoint.json"

        def __init__(self, *_args, **_kwargs):
            order.append("guard-open")

        def verify_trusted_prefix(self, _store):
            order.append("checkpoint-verify")

        def bind(self, _store):
            order.append("checkpoint-bind")

        def require_healthy(self):
            order.append("checkpoint-healthy")

        def close(self):
            order.append("guard-close")

    signing_store = SimpleNamespace(close=lambda: order.append("signing-close"))
    signing_authority = SimpleNamespace(store=signing_store)
    def migrate(*_args, **kwargs):
        order.append("migrate")
        assert kwargs["staging_path"] == staging_path.resolve()
        assert kwargs["authentication_context"] is authentication_context
        staging_path.write_bytes(b"disposable")
        Path(str(staging_path) + ".owner.lock").write_bytes(b"1")
        return SimpleNamespace(
            migrated=True,
            revision=13,
            receipt_root="receipt:baboom-repair",
        )

    monkeypatch.setattr(
        authority_bridge, "WindowsDpapiSigningKeyProvider", FakeKeyProvider
    )
    monkeypatch.setattr(authority_bridge, "CellStore", FakeStore)
    monkeypatch.setattr(authority_bridge, "RevisionCheckpointGuard", FakeGuard)
    monkeypatch.setattr(
        authority_bridge,
        "provision_windows_revision_checkpoint_authority",
        lambda path: (
            order.append(("provision", Path(path))),
            signing_authority,
        )[1],
    )
    monkeypatch.setattr(
        authority_bridge,
        "migrate_legacy_baboom_execution_from_durable_store",
        migrate,
    )
    states = iter(("legacy", "current"))
    monkeypatch.setattr(
        authority_bridge,
        "legacy_baboom_execution_migration_state",
        lambda _snapshot: next(states),
    )

    authentication_context = object()
    result = authority_bridge.repair_legacy_baboom_authority(
        state_path=state_path,
        backup_path=backup_path,
        staging_path=staging_path,
        authentication_context=authentication_context,
    )

    assert result["status"] == "repaired"
    assert result["before_revision"] == 12
    assert result["after_revision"] == 13
    assert result["receipt_root"] == "receipt:baboom-repair"
    assert result["checkpoint_healthy"] is True
    assert backup_path.read_bytes() == b"backup"
    assert not staging_path.exists()
    assert not Path(str(staging_path) + ".owner.lock").exists()
    assert order == [
        ("key-provider", tmp_path / "keys.dpapi"),
        ("provision", database_path.resolve()),
        "store-open",
        "guard-open",
        "snapshot",
        "checkpoint-verify",
        "backup",
        "checkpoint-bind",
        "migrate",
        "snapshot",
        "checkpoint-healthy",
        "guard-close",
        "store-close",
        "signing-close",
    ]


def _retired_offline_baboom_repair_refuses_missing_authenticated_context(tmp_path):
    try:
        authority_bridge.repair_legacy_baboom_authority(
            state_path=tmp_path / "authority.json.gz",
            authentication_context=None,
        )
    except PermissionError as exc:
        assert "authenticated graph context" in str(exc)
    else:  # pragma: no cover - this court requires the denial
        raise AssertionError("BABOOM authority repair must require graph authority")


def _retired_offline_baboom_repair_accepts_an_already_current_single_authority(
    monkeypatch,
    tmp_path,
):
    state_path = tmp_path / "authority.json.gz"
    database_path = tmp_path / "authority.json.gz.universal.sqlite3"
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    backup_path = recovery / "pre-repair.sqlite3"
    database_path.write_bytes(b"authority")

    class Store:
        revision = 23

        def __init__(self, _path):
            return None

        def snapshot(self):
            return SimpleNamespace(revision=23)

        def backup_to(self, path):
            Path(path).write_bytes(b"backup")

        def close(self):
            return None

    class Guard:
        @staticmethod
        def default_path(_path):
            return tmp_path / "checkpoint.json"

        def __init__(self, *_args, **_kwargs):
            return None

        def verify_trusted_prefix(self, _store):
            return None

        def bind(self, _store):
            return None

        def require_healthy(self):
            return None

        def close(self):
            return None

    class KeyProvider:
        @staticmethod
        def default_path():
            return tmp_path / "keys.dpapi"

        def __init__(self, _path):
            return None

    signing_authority = SimpleNamespace(
        store=SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(authority_bridge, "CellStore", Store)
    monkeypatch.setattr(authority_bridge, "RevisionCheckpointGuard", Guard)
    monkeypatch.setattr(
        authority_bridge, "WindowsDpapiSigningKeyProvider", KeyProvider
    )
    monkeypatch.setattr(
        authority_bridge,
        "provision_windows_revision_checkpoint_authority",
        lambda _path: signing_authority,
    )
    monkeypatch.setattr(
        authority_bridge,
        "legacy_baboom_execution_migration_state",
        lambda _snapshot: "current",
    )
    monkeypatch.setattr(
        authority_bridge,
        "migrate_legacy_baboom_execution_from_durable_store",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("current authority must not be migrated")
        ),
    )
    result = authority_bridge.repair_legacy_baboom_authority(
        state_path=state_path,
        backup_path=backup_path,
        authentication_context=object(),
    )

    assert result["status"] == "already-current"
    assert result["catalog_state_before"] == "current"
    assert result["migration_revision"] == 23
    assert result["receipt_root"] is None
    assert result["before_revision"] == result["after_revision"] == 23
    assert not backup_path.exists()


def _retired_offline_baboom_repair_rejects_artifacts_outside_recovery_root(
    tmp_path,
):
    state_path = tmp_path / "authority.json.gz"
    database_path = tmp_path / "authority.json.gz.universal.sqlite3"
    database_path.write_bytes(b"authority")

    with pytest.raises(ValueError, match="dedicated ArchHub recovery"):
        authority_bridge.repair_legacy_baboom_authority(
            state_path=state_path,
            backup_path=tmp_path / "outside.sqlite3",
            authentication_context=object(),
        )


def _retired_existing_recovery_backup_requires_exact_revision_chain(
    monkeypatch,
    tmp_path,
):
    backup_path = tmp_path / "backup.sqlite3"
    backup_path.write_bytes(b"backup")
    store = SimpleNamespace(
        revision=31,
        revision_chain_digest=lambda revision: (
            "source-digest" if revision == 31 else ""
        ),
    )
    monkeypatch.setattr(
        authority_bridge,
        "inspect_read_only_cell_journal",
        lambda path: (
            SimpleNamespace(revision=31)
            if Path(path) == backup_path
            else None
        ),
    )
    monkeypatch.setattr(
        authority_bridge,
        "read_only_revision_chain_digest",
        lambda path, revision: (
            "source-digest"
            if Path(path) == backup_path and revision == 31
            else ""
        ),
    )

    authority_bridge._require_matching_recovery_backup(store, backup_path)

    monkeypatch.setattr(
        authority_bridge,
        "read_only_revision_chain_digest",
        lambda _path, _revision: "different-digest",
    )
    try:
        authority_bridge._require_matching_recovery_backup(store, backup_path)
    except RuntimeError as exc:
        assert "digest does not match" in str(exc)
    else:  # pragma: no cover - this court requires the denial
        raise AssertionError("mismatched recovery backup must be denied")


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
