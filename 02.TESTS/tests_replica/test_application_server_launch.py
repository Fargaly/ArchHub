"""Launch court for the one-owner Universal machine-transport boundary."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import nodelang.application_server as application_server


ROOT = Path(__file__).resolve().parents[2]


def test_primary_server_cli_refuses_a_second_machine_transport_owner(monkeypatch):
    calls = []
    monkeypatch.setattr(application_server, "ApplicationServer", lambda *a, **k: calls.append(k))
    with pytest.raises(ValueError, match="independent server launch flags are retired"):
        application_server.main(['--machine-transport'])
    assert calls == []


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
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert len(records) == 1, result.stdout
    proof = records[0]
    assert proof["legacy_module_loaded"] is False
    assert proof["legacy_runtime_enabled"] is False
    assert proof["universal_revision"] > 0
    assert proof["universal_cells"] > 0


def test_constructed_server_can_release_before_http_thread_starts():
    server = application_server.ApplicationServer(fresh=True)

    assert server.thread is None
    server.close()
    assert server.httpd.socket.fileno() == -1


def test_primary_server_cli_refuses_a_retired_state_selection(monkeypatch):
    calls = []
    monkeypatch.setattr(application_server, "ApplicationServer", lambda *a, **k: calls.append(k))
    with pytest.raises(ValueError, match="independent server launch flags are retired"):
        application_server.main(['--state-path', 'retired-state'])
    assert calls == []


def test_primary_server_cli_refuses_a_second_gateway_owner(monkeypatch):
    calls = []
    monkeypatch.setattr(application_server, "ApplicationServer", lambda *a, **k: calls.append(k))
    with pytest.raises(ValueError, match="independent server launch flags are retired"):
        application_server.main(['--public-server-url', 'http://127.0.0.1:8495'])
    assert calls == []


def test_primary_server_cli_refuses_an_independent_cloud_desktop_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(application_server, "ApplicationServer", lambda *a, **k: calls.append(k))
    with pytest.raises(ValueError, match="independent server launch flags are retired"):
        application_server.main(['--enable-universal-cloud-gateway'])
    assert calls == []
