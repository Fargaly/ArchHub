"""Tests for app/speckle_server.py — lifecycle helpers (M1.5).

Docker subprocess + Speckle Server itself are mocked; tests verify the
shape of the lifecycle module (API contract, error paths, idempotency).
A real Docker-running test belongs in a separate integration suite
that's skipped when Docker isn't installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import speckle_server  # noqa: E402


# ---------------------------------------------------------------------------
# docker_available


def test_docker_available_returns_bool():
    # Pure shape check — actual presence depends on machine.
    assert isinstance(speckle_server.docker_available(), bool)


def test_docker_available_false_when_cli_missing(monkeypatch):
    monkeypatch.setattr(speckle_server.shutil, "which", lambda _x: None)
    assert speckle_server.docker_available() is False


def test_docker_available_false_when_daemon_down(monkeypatch):
    monkeypatch.setattr(speckle_server.shutil, "which",
                         lambda _x: "/usr/local/bin/docker")
    class _CP:
        returncode = 1
        stdout = ""
        stderr = "Cannot connect to the Docker daemon"
    monkeypatch.setattr(speckle_server.subprocess, "run",
                         lambda *a, **k: _CP())
    assert speckle_server.docker_available() is False


# ---------------------------------------------------------------------------
# is_running


def test_is_running_returns_false_when_unreachable(monkeypatch):
    monkeypatch.setattr(speckle_server, "_health_probe", lambda *a, **k: None)
    r = speckle_server.is_running("http://localhost:9999")
    assert r["running"] is False
    assert r["url"] == "http://localhost:9999"


def test_is_running_returns_true_when_healthy(monkeypatch):
    monkeypatch.setattr(speckle_server, "_health_probe",
                         lambda *a, **k: {"endpoint": "/api/health",
                                          "payload": {"version": "2.20.0"}})
    r = speckle_server.is_running("http://localhost:3000")
    assert r["running"] is True
    assert r["url"] == "http://localhost:3000"
    assert r["version"] == "2.20.0"


# ---------------------------------------------------------------------------
# start_local — error paths (no Docker invocation)


def test_start_local_fast_path_when_already_running(monkeypatch):
    """Idempotent — no Docker touch if the server already responds."""
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": True, "url": url,
                                       "version": "2.20.0"})
    called = []
    monkeypatch.setattr(speckle_server.subprocess, "run",
                         lambda *a, **k: called.append(a) or None)
    r = speckle_server.start_local(port=3000)
    assert r["status"] == "running"
    assert r["url"] == "http://localhost:3000"
    assert called == [], "should not touch docker when already running"


def test_start_local_errors_when_docker_missing(monkeypatch):
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    monkeypatch.setattr(speckle_server, "docker_available", lambda: False)
    r = speckle_server.start_local(port=3000)
    assert r["status"] == "error"
    assert r["code"] == "docker_missing"
    assert "Docker" in r["error"]


def test_start_local_returns_starting_when_wait_false(monkeypatch, tmp_path):
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    monkeypatch.setattr(speckle_server, "docker_available", lambda: True)
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")
    monkeypatch.setattr(speckle_server.subprocess, "run",
                         lambda *a, **k: mock.Mock(returncode=0))
    r = speckle_server.start_local(port=3000, wait=False)
    assert r["status"] == "starting"
    assert "compose_path" in r


def test_start_local_compose_failure_surfaces_typed_error(monkeypatch,
                                                            tmp_path):
    import subprocess as _sp
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    monkeypatch.setattr(speckle_server, "docker_available", lambda: True)
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")

    def _fail(*a, **k):
        raise _sp.CalledProcessError(
            1, "docker compose up", stderr="pull failed: rate limited",
        )

    monkeypatch.setattr(speckle_server.subprocess, "run", _fail)
    r = speckle_server.start_local(port=3000)
    assert r["status"] == "error"
    assert r["code"] == "compose_failed"
    assert "pull failed" in r["error"]


def test_start_local_timeout_surfaces_typed_error(monkeypatch, tmp_path):
    """Compose ran fine but the server never became ready."""
    import subprocess as _sp
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    monkeypatch.setattr(speckle_server, "docker_available", lambda: True)
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")
    monkeypatch.setattr(speckle_server.subprocess, "run",
                         lambda *a, **k: mock.Mock(returncode=0,
                                                    stdout="", stderr=""))
    # Force the wait to spin once then "time out" — set timeout to 0.01s
    # via monkey-patch on the constant.
    monkeypatch.setattr(speckle_server, "_POLL_TIMEOUT", 0.01)
    monkeypatch.setattr(speckle_server, "_POLL_INTERVAL", 0.005)
    r = speckle_server.start_local(port=3000)
    assert r["status"] == "error"
    assert r["code"] == "server_unhealthy"


# ---------------------------------------------------------------------------
# stop_local


def test_stop_local_errors_when_docker_missing(monkeypatch):
    monkeypatch.setattr(speckle_server, "docker_available", lambda: False)
    r = speckle_server.stop_local()
    assert r["ok"] is False
    assert r["code"] == "docker_missing"


def test_stop_local_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(speckle_server, "docker_available", lambda: True)
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")
    monkeypatch.setattr(speckle_server.subprocess, "run",
                         lambda *a, **k: mock.Mock(returncode=0))
    r = speckle_server.stop_local()
    assert r["ok"] is True


# ---------------------------------------------------------------------------
# status — combined report


def test_status_returns_combined_report(monkeypatch):
    monkeypatch.setattr(speckle_server, "docker_available", lambda: True)
    monkeypatch.setattr(speckle_server, "is_running",
                         lambda url: {"running": False, "url": url})
    s = speckle_server.status()
    assert "docker_available" in s
    assert "compose_template_bundled" in s
    assert "user_data_dir" in s
    assert "running" in s


# ---------------------------------------------------------------------------
# _ensure_compose_at_user_dir — writes inline template when bundled absent


def test_ensure_compose_writes_fallback_when_bundled_missing(monkeypatch,
                                                                tmp_path):
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")
    monkeypatch.setattr(speckle_server, "_BUNDLED_COMPOSE",
                         tmp_path / "nonexistent.yml")
    p = speckle_server._ensure_compose_at_user_dir()
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "speckle-server" in content
    assert "postgres" in content
    assert "redis" in content


def test_ensure_compose_uses_bundled_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")
    fake_bundled = tmp_path / "bundled.yml"
    fake_bundled.write_text("# bundled marker\nservices: {}\n",
                             encoding="utf-8")
    monkeypatch.setattr(speckle_server, "_BUNDLED_COMPOSE", fake_bundled)
    p = speckle_server._ensure_compose_at_user_dir()
    assert "bundled marker" in p.read_text(encoding="utf-8")


def test_ensure_compose_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(speckle_server, "_USER_DIR", tmp_path / "speckle")
    monkeypatch.setattr(speckle_server, "_BUNDLED_COMPOSE",
                         tmp_path / "nonexistent.yml")
    p1 = speckle_server._ensure_compose_at_user_dir()
    original = p1.read_text(encoding="utf-8")
    # Modify it to simulate user-edits surviving subsequent calls.
    p1.write_text(original + "\n# user-edit\n", encoding="utf-8")
    p2 = speckle_server._ensure_compose_at_user_dir()
    assert p1 == p2
    assert "# user-edit" in p2.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# push_to_server — canonical server-push entry-point (M2-Python AgDR-0017)


def test_push_to_server_returns_canonical_url(monkeypatch):
    """A successful push returns `<server>/streams/<model>/objects/<hash>`."""
    import speckle_server as ss

    # Stub the three specklepy imports the function reaches into.
    class _FakeClient:
        def __init__(self, host, use_ssl):
            self.host = host
            self.use_ssl = use_ssl

    class _FakeTransport:
        def __init__(self, client, stream_id):
            self.client = client
            self.stream_id = stream_id

    sent_args = {}

    class _FakeOperations:
        @staticmethod
        def send(base, transports, *, use_default_cache):
            sent_args["base"] = base
            sent_args["transports"] = transports
            sent_args["cache"] = use_default_cache
            return "abc1234567890"

    monkeypatch.setattr(
        "specklepy.api.client.SpeckleClient", _FakeClient,
        raising=False)
    monkeypatch.setattr(
        "specklepy.transports.server.ServerTransport", _FakeTransport,
        raising=False)
    monkeypatch.setattr(
        "specklepy.api.operations", _FakeOperations, raising=False)

    url = ss.push_to_server({"x": 1}, "https://speckle.example.com",
                             "my-model")
    assert url == "https://speckle.example.com/streams/my-model/objects/abc1234567890"
    # Wire is shipped without the system-wide cache (per AgDR-0012
    # use_default_cache=False invariant).
    assert sent_args["cache"] is False


def test_push_to_server_propagates_exceptions(monkeypatch):
    """Any specklepy failure surfaces as an exception — the caller
    decides whether to fall back gracefully. push_to_server NEVER
    silently swallows errors."""
    import speckle_server as ss

    class _Boom:
        def __init__(self, host, use_ssl):
            raise RuntimeError("no network")

    monkeypatch.setattr(
        "specklepy.api.client.SpeckleClient", _Boom, raising=False)
    import pytest
    with pytest.raises(Exception):
        ss.push_to_server({"x": 1}, "http://localhost:3000", "m")


def test_push_to_server_strips_trailing_slash(monkeypatch):
    """A server URL with a trailing slash should produce a clean URL
    (no double slashes)."""
    import speckle_server as ss

    class _FC:
        def __init__(self, host, use_ssl): pass

    class _FT:
        def __init__(self, client, stream_id): pass

    class _Ops:
        @staticmethod
        def send(base, transports, *, use_default_cache):
            return "hash"

    monkeypatch.setattr(
        "specklepy.api.client.SpeckleClient", _FC, raising=False)
    monkeypatch.setattr(
        "specklepy.transports.server.ServerTransport", _FT, raising=False)
    monkeypatch.setattr(
        "specklepy.api.operations", _Ops, raising=False)
    url = ss.push_to_server({"x": 1}, "http://localhost:3000/", "m")
    assert "://localhost:3000/streams" in url
    assert "::" not in url


def test_revit_send_to_speckle_server_push_uses_push_to_server(monkeypatch,
                                                                  tmp_path):
    """The Revit op delegates server push to the canonical
    `push_to_server`. Tests the integration path that was a stub
    before this slice."""
    from connectors import revit_speckle_ops

    calls = []

    def fake_push(value, server_url, model_name):
        calls.append((server_url, model_name))
        return f"{server_url}/streams/{model_name}/objects/zzz"

    # The op imports `from speckle_server import push_to_server`
    # at call time, so patching the module attribute is enough.
    import speckle_server as ss
    monkeypatch.setattr(ss, "push_to_server", fake_push)

    result = revit_speckle_ops.send_to_speckle(
        value={"hello": "world"},
        model_name="m1",
        project_dir=str(tmp_path),
        server_push=True,
        server_url="http://localhost:3000",
    )
    assert result["mode"] == "server"
    assert result["url"].endswith("/streams/m1/objects/zzz")
    assert calls == [("http://localhost:3000", "m1")]
