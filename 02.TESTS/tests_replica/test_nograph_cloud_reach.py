"""A remote agent's read reaches this PC's brokers through the NoGraph server.

Root cause (CLOUDREACH, 2026-10-28): NoGraphServer never started the existing
cloud relay, so every cloud /mcp host read came back device_offline. The server
now starts cloud_relay.start_cloud_relay (same Credential Manager session, same
recorded consent) and claims host-read tasks only. This court runs the real
server and the real relay against a loopback stand-in for the cloud queue.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from nodelang import clean_revit_adapter, cloud_relay, cloud_session
from nodelang.cloud_publish_consent import record_cloud_publish_consent
from nodelang.nograph_server import NoGraphServer

ACCOUNT = "owner@example.com"
SESSIONS = [{"port": 48884, "document": "S3"}]


class _Cloud(BaseHTTPRequestHandler):
    tasks, claims, results = [], [], []

    def log_message(self, *_a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == cloud_relay.CLAIM_PATH:
            _Cloud.claims.append(body)
            payload = {"task": _Cloud.tasks.pop(0) if _Cloud.tasks else None}
        else:
            _Cloud.results.append((self.path, body))
            payload = {"ok": True}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _until(check, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def _cloud(monkeypatch, tmp_path):
    cloud = HTTPServer(("127.0.0.1", 0), _Cloud)
    threading.Thread(target=cloud.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % cloud.server_address[1]
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))  # never the real profile
    monkeypatch.setattr(cloud_relay, "load_cloud_session", lambda appdata=None: {"token": "t", "base_url": base})
    monkeypatch.setattr(cloud_session, "signed_in_cloud_account", lambda *a, **k: ACCOUNT)
    monkeypatch.setattr(clean_revit_adapter, "live_sessions", lambda: SESSIONS)
    _Cloud.tasks[:], _Cloud.claims[:], _Cloud.results[:] = [], [], []
    return cloud


def test_remote_revit_read_is_answered_by_the_nograph_server(monkeypatch, tmp_path):
    cloud = _cloud(monkeypatch, tmp_path)
    record_cloud_publish_consent(tmp_path, account=ACCOUNT)
    _Cloud.tasks.append({"id": "t1", "kind": cloud_relay.HOST_READ,
                         "directive": json.dumps({"tool": "revit.sessions", "args": {}})})
    server = NoGraphServer(tmp_path).start()
    try:
        assert server.cloud_relay is not None
        assert _until(lambda: _Cloud.results)
        path, body = _Cloud.results[0]
        assert path == cloud_relay.RESULT_PATH % "t1"
        assert body["ok"] is True
        assert json.loads(body["result"]) == {"ok": True, "sessions": SESSIONS}
        # Host reads only: never BABOOM instructions, Workshop or session calls.
        assert _Cloud.claims[0]["kinds"] == [cloud_relay.HOST_READ]
    finally:
        server.close()
        cloud.shutdown()
    assert server.cloud_relay is None


def test_a_write_is_refused_before_any_host_is_touched(monkeypatch, tmp_path):
    cloud = _cloud(monkeypatch, tmp_path)
    record_cloud_publish_consent(tmp_path, account=ACCOUNT)
    _Cloud.tasks.append({"id": "t2", "kind": cloud_relay.HOST_READ,
                         "directive": json.dumps({"tool": "revit.execute_csharp", "args": {}})})
    server = NoGraphServer(tmp_path).start()
    try:
        assert _until(lambda: _Cloud.results)
        assert _Cloud.results[0][1]["ok"] is False
        assert "not a remote read" in _Cloud.results[0][1]["result"]
    finally:
        server.close()
        cloud.shutdown()


def test_without_consent_the_relay_stays_off(monkeypatch, tmp_path):
    cloud = _cloud(monkeypatch, tmp_path)
    server = NoGraphServer(tmp_path).start()
    try:
        assert server.cloud_relay is None
        assert not _until(lambda: _Cloud.claims, seconds=1.0)
    finally:
        server.close()
        cloud.shutdown()
