"""Launch court for the one-owner Universal machine-transport boundary."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import nodelang.application_server as application_server


ROOT = Path(__file__).resolve().parents[1]


class _CompletedThread:
    def join(self) -> None:
        return None


class _FakeCredentialVault:
    @staticmethod
    def default_path():
        return "court-browser-session.dpapi"

    def __init__(self, _path) -> None:
        return None

    def load_or_create(self):
        return object()


def test_primary_server_cli_can_own_signed_machine_transport(tmp_path, monkeypatch):
    captured = {}

    class FakeServer:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.thread = _CompletedThread()
            self.bootstrap_url = "http://127.0.0.1:8482/?bootstrap=court"

        def start(self):
            return self

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(application_server, "ApplicationServer", FakeServer)
    monkeypatch.setattr(application_server, "BrowserCredentialVault", _FakeCredentialVault)

    descriptor = tmp_path / "active-universal-runtime.json"
    application_server.main([
        "--state-path", str(tmp_path / "state.json.gz"),
        "--machine-transport",
        "--machine-descriptor-path", str(descriptor),
    ])

    assert captured["kwargs"]["enable_machine_transport"] is True
    assert captured["kwargs"]["machine_descriptor_path"] == str(descriptor)
    assert captured["closed"] is True


def test_universal_server_boot_does_not_load_the_retired_typed_runtime():
    code = """
import json
import sys
from nodelang.application_server import ApplicationServer

server = ApplicationServer(fresh=True).start()
try:
    print(json.dumps({
        'legacy_module_loaded': 'nodelang.application' in sys.modules,
        'legacy_runtime_enabled': server.legacy_runtime_enabled,
        'universal_revision': server.universal_store.revision,
        'universal_cells': len(server.universal_store.snapshot().cells),
    }))
finally:
    server.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    proof = json.loads(result.stdout)
    assert proof["legacy_module_loaded"] is False
    assert proof["legacy_runtime_enabled"] is False
    assert proof["universal_revision"] > 0
    assert proof["universal_cells"] > 0


def test_primary_server_cli_leaves_machine_transport_off_without_explicit_flag(
    tmp_path,
    monkeypatch,
):
    captured = {}

    class FakeServer:
        thread = _CompletedThread()
        bootstrap_url = "http://127.0.0.1:8482/?bootstrap=court"

        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        def start(self):
            return self

        def close(self):
            return None

    monkeypatch.setattr(application_server, "ApplicationServer", FakeServer)
    monkeypatch.setattr(application_server, "BrowserCredentialVault", _FakeCredentialVault)

    application_server.main(["--state-path", str(tmp_path / "state.json.gz")])

    assert captured["kwargs"]["enable_machine_transport"] is False
    assert captured["kwargs"]["machine_descriptor_path"] is None


def test_primary_server_cli_passes_explicit_graph_cloud_gateway_configuration(
    tmp_path,
    monkeypatch,
):
    captured = {}

    class FakeServer:
        thread = _CompletedThread()
        bootstrap_url = "http://127.0.0.1:8482/?bootstrap=court"

        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        def start(self):
            return self

        def close(self):
            return None

    monkeypatch.setattr(application_server, "ApplicationServer", FakeServer)
    monkeypatch.setattr(application_server, "BrowserCredentialVault", _FakeCredentialVault)

    application_server.main([
        "--state-path", str(tmp_path / "state.json.gz"),
        "--enable-universal-cloud-gateway",
        "--cloud-host", "127.0.0.1",
        "--cloud-port", "9443",
        "--cloud-resource-origin", "https://gateway.archhub.test",
        "--cloud-tls-certificate-file", str(tmp_path / "certificate.pem"),
        "--cloud-tls-private-key-file", str(tmp_path / "private-key.pem"),
    ])

    assert captured["kwargs"]["enable_universal_cloud_gateway"] is True
    assert captured["kwargs"]["cloud_resource_origin"] == (
        "https://gateway.archhub.test"
    )
    assert captured["kwargs"]["cloud_tls_certificate_file"] == str(
        tmp_path / "certificate.pem"
    )
    assert captured["kwargs"]["cloud_tls_private_key_file"] == str(
        tmp_path / "private-key.pem"
    )
