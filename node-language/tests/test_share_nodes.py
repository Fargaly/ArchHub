"""Tests for the SHARE category engine nodes — share.{server,publish,subscribe}.

DiskTransport-only path is fully tested. Server-pushing path is mocked
(specklepy ServerTransport requires a live server + auth). Real
end-to-end with a Docker-running server is a separate integration test.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Force registration import.
from workflows.nodes import share  # noqa: F401, E402
from workflows.registry import get as registry_get  # noqa: E402


# ---------------------------------------------------------------------------
# share.server


@pytest.fixture
def share_server_ex():
    _, ex = registry_get("share.server")
    return ex


def test_share_server_fast_path_when_already_running(share_server_ex,
                                                       monkeypatch):
    import speckle_server
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": True, "url": url,
                                       "version": "2.20.0"})
    r = share_server_ex({"port": 3000, "auto_start": True}, {}, None)
    assert r["server_url"] == "http://localhost:3000"
    assert r["status"]["running"] is True
    assert r["status"]["started_now"] is False  # already up, not started by us
    assert r["status"]["version"] == "2.20.0"


def test_share_server_auto_start_false_returns_error(share_server_ex,
                                                       monkeypatch):
    import speckle_server
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    r = share_server_ex({"port": 3000, "auto_start": False}, {}, None)
    assert r["status"]["running"] is False
    assert "auto_start" in r["status"]["error"]


def test_share_server_starts_and_reports_started_now(share_server_ex,
                                                       monkeypatch):
    import speckle_server
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    monkeypatch.setattr(speckle_server, "start_local",
                         lambda **k: {"url": "http://localhost:3000",
                                       "status": "running",
                                       "version": "2.20.0"})
    r = share_server_ex({"port": 3000, "auto_start": True}, {}, None)
    assert r["server_url"] == "http://localhost:3000"
    assert r["status"]["running"] is True
    assert r["status"]["started_now"] is True


def test_share_server_propagates_typed_error(share_server_ex, monkeypatch):
    import speckle_server
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    monkeypatch.setattr(speckle_server, "start_local",
                         lambda **k: {"url": "http://localhost:3000",
                                       "status": "error",
                                       "error": "Docker not installed",
                                       "code": "docker_missing"})
    r = share_server_ex({"port": 3000, "auto_start": True}, {}, None)
    assert r["status"]["running"] is False
    assert r["status"]["code"] == "docker_missing"
    assert "Docker" in r["status"]["error"]


# ---------------------------------------------------------------------------
# share.publish


@pytest.fixture
def share_publish_ex():
    _, ex = registry_get("share.publish")
    return ex


def test_publish_writes_locally_when_no_server_url(share_publish_ex,
                                                     tmp_path, monkeypatch):
    # Redirect default_project_dir so the test SpeckleWire is isolated.
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: tmp_path / "proj")
    r = share_publish_ex({"model_name": "default"},
                          {"value": {"a": 1, "b": "two"}}, None)
    assert r["status"]["ok"] is True
    assert r["model_url"].startswith("speckle://local/")
    assert r["status"]["local_hash"]
    assert r["status"]["server_pushed"] is False


def test_publish_includes_server_url_in_model_url(share_publish_ex,
                                                    tmp_path, monkeypatch):
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: tmp_path / "proj")
    # Mock the server push so the test doesn't actually need a Speckle
    # Server running. We want the model_url to reflect the server URL.

    class _Client:
        def __init__(self, *a, **k):
            pass

    class _Transport:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr("specklepy.api.client.SpeckleClient", _Client)
    monkeypatch.setattr("specklepy.transports.server.ServerTransport",
                         _Transport)
    # Patch operations.send used inside share.publish (server push).
    sent = []
    monkeypatch.setattr("specklepy.api.operations.send",
                         lambda base, transports, **k:
                             sent.append((base, transports)) or "remote_hash")

    r = share_publish_ex({"model_name": "demo",
                           "server_url": "http://localhost:3000"},
                          {"value": [1, 2, 3]}, None)
    assert r["status"]["ok"] is True
    assert "http://localhost:3000" in r["model_url"]
    assert "/streams/demo/objects/" in r["model_url"]
    assert r["status"]["server_pushed"] is True
    assert sent, "server push not attempted"


def test_publish_local_failure_surfaces_error(share_publish_ex,
                                                tmp_path, monkeypatch):
    """If the DiskTransport write blows up, surface the typed error."""
    import speckle_wire

    class _BrokenWire:
        def __init__(self, *a, **k):
            pass

        def send(self, _v):
            raise RuntimeError("disk full")

    monkeypatch.setattr(speckle_wire, "SpeckleWire", _BrokenWire)
    r = share_publish_ex({"model_name": "demo"},
                          {"value": "x"}, None)
    assert r["status"]["ok"] is False
    assert r["status"]["code"] == "local_send_failed"


def test_publish_falls_back_gracefully_when_server_push_fails(
        share_publish_ex, tmp_path, monkeypatch):
    """Server push failure should NOT block local publish — the disk
    write is what matters; the server is best-effort."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: tmp_path / "proj")

    def _explode(*a, **k):
        raise ConnectionRefusedError("server down")

    monkeypatch.setattr("specklepy.api.client.SpeckleClient", _explode)
    r = share_publish_ex({"model_name": "demo",
                           "server_url": "http://localhost:3000"},
                          {"value": "x"}, None)
    # Local succeeded even though server failed.
    assert r["status"]["ok"] is True
    assert r["status"]["server_pushed"] is False
    assert "server" in r["status"]["server_error"].lower() or \
           "refused" in r["status"]["server_error"].lower() or \
           "ConnectionRefusedError" in r["status"]["server_error"]


# ---------------------------------------------------------------------------
# share.subscribe


@pytest.fixture
def share_subscribe_ex():
    _, ex = registry_get("share.subscribe")
    return ex


def test_subscribe_no_source_url_errors(share_subscribe_ex):
    r = share_subscribe_ex({}, {"source_url": ""}, None)
    assert r["status"]["ok"] is False
    assert r["status"]["code"] == "no_source"


def test_subscribe_speckle_local_scheme_roundtrip(share_subscribe_ex,
                                                    tmp_path, monkeypatch):
    """Publish via share.publish, then subscribe with the resulting
    speckle://local/<hash> URL — should round-trip the value."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: tmp_path / "proj")
    _, publish_ex = registry_get("share.publish")
    pub = publish_ex({"model_name": "x"},
                      {"value": {"a": 1, "b": [2, 3]}}, None)
    assert pub["status"]["ok"] is True
    sub = share_subscribe_ex({},
                              {"source_url": pub["model_url"]}, None)
    assert sub["status"]["ok"] is True
    assert sub["status"]["source"] == "local"
    assert sub["value"] == {"a": 1, "b": [2, 3]}


def test_subscribe_bare_hash_tries_local(share_subscribe_ex,
                                           tmp_path, monkeypatch):
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: tmp_path / "proj")
    wire = speckle_wire.SpeckleWire()
    h = wire.send([10, 20, 30])
    r = share_subscribe_ex({}, {"source_url": h}, None)
    assert r["status"]["ok"] is True
    assert r["value"] == [10, 20, 30]


def test_subscribe_invalid_hash_errors_gracefully(share_subscribe_ex,
                                                    tmp_path, monkeypatch):
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: tmp_path / "proj")
    r = share_subscribe_ex({},
                            {"source_url": "definitely-not-a-hash-12345"},
                            None)
    assert r["status"]["ok"] is False
    assert r["status"]["code"] in ("bad_url", "local_receive_failed")


def test_subscribe_http_url_parses_stream_and_hash(share_subscribe_ex,
                                                     monkeypatch):
    """The http(s) branch should parse out stream_id + hash + server base."""

    # Stub the Speckle client / transport / operations to avoid network.
    class _Client:
        def __init__(self, *a, **k):
            pass

    class _Transport:
        def __init__(self, *a, **k):
            pass

    class _Base:
        archhubShape = "json"
        archhubJson = '"hello-from-server"'

    monkeypatch.setattr("specklepy.api.client.SpeckleClient", _Client)
    monkeypatch.setattr("specklepy.transports.server.ServerTransport",
                         _Transport)
    monkeypatch.setattr("specklepy.api.operations.receive",
                         lambda h, **k: _Base())
    r = share_subscribe_ex({},
                            {"source_url":
                              "http://localhost:3000/streams/demo/objects/abc123"},
                            None)
    assert r["status"]["ok"] is True
    assert r["status"]["source"] == "server"
    assert r["status"]["server"] == "http://localhost:3000"
    assert r["value"] == "hello-from-server"


def test_subscribe_bad_http_url_shape_errors(share_subscribe_ex):
    r = share_subscribe_ex({},
                            {"source_url": "http://localhost:3000/just/garbage"},
                            None)
    assert r["status"]["ok"] is False
    assert r["status"]["code"] == "bad_url_shape"


# ---------------------------------------------------------------------------
# Registry shape


@pytest.mark.parametrize("type_name, in_ports, out_ports", [
    ("share.server",    set(),              {"server_url", "status"}),
    ("share.publish",   {"value"},          {"model_url", "status"}),
    ("share.subscribe", {"source_url"},     {"value", "status"}),
])
def test_share_node_registered_with_expected_shape(type_name, in_ports, out_ports):
    spec, ex = registry_get(type_name)
    assert callable(ex)
    assert {p.name for p in spec.inputs} == in_ports
    assert {p.name for p in spec.outputs} == out_ports
