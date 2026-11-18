"""The installed update check, against a local release feed. No source is read as proof."""
from __future__ import annotations

import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest

from nodelang.application_update import ApplicationUpdate
from nodelang import quiet_update as qu

INSTALLED = "20261101-1919-86aa03a"
LATEST = "20261101-2325-f557cb3"
INSTALLER = b"archhub-local-feed-installer"


class _Feed(BaseHTTPRequestHandler):
    release = b""
    installer = b""
    seen = []

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        _Feed.seen.append(path)
        if path == "/latest":
            body = _Feed.release
        elif path.endswith("/" + qu.ASSET_NAME):
            body = _Feed.installer
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def test_update_check_stages_a_newer_build_from_the_local_feed_and_logs(tmp_path, monkeypatch):
    state = Path(os.environ["LOCALAPPDATA"]) / "ArchHub"
    app = tmp_path / "install"
    app.mkdir()
    (app / "BUILD_ID").write_text(INSTALLED, encoding="utf-8")
    (app / "BUILD_METADATA.json").write_text(json.dumps({
        "format": 1, "build_id": INSTALLED, "built_at": "2026-11-01T15:19:00Z",
    }) + "\n", encoding="utf-8")
    digest = hashlib.sha256(INSTALLER).hexdigest()
    body = ("BUILD_ID: %s\nBUILT_AT: 2026-11-01T19:25:00Z\nSHA256 %s: %s\n"
            % (LATEST, qu.ASSET_NAME, digest)).encode("utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Feed)
    port = server.server_address[1]
    asset = "http://127.0.0.1:%d/download/%s" % (port, qu.ASSET_NAME)
    _Feed.release = json.dumps({
        "tag_name": LATEST, "draft": False, "prerelease": False,
        "body": body.decode("utf-8"),
        "assets": [{"name": qu.ASSET_NAME, "size": len(INSTALLER), "browser_download_url": asset}],
    }).encode("utf-8")
    _Feed.installer = INSTALLER
    _Feed.seen = []
    thread = threading.Thread(target=server.serve_forever, name="archhub-update-feed", daemon=True)
    thread.start()
    monkeypatch.setenv("ARCHHUB_UPDATE_FEED", "http://127.0.0.1:%d/latest" % port)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    try:
        result = qu.check_for_update(state, app)
    finally:
        server.shutdown()
        server.server_close()
    assert result["staged"] is True and result["downloaded"] is True, result
    assert result["build_id"] == LATEST
    assert (state / "updates" / qu.ASSET_NAME).read_bytes() == INSTALLER
    marker = json.loads((state / "updates" / "staged.json").read_text(encoding="utf-8"))
    assert marker["build_id"] == LATEST and marker["phase"] == "staged"
    assert (app / "BUILD_ID").read_text(encoding="utf-8") == INSTALLED
    log = (state / "logs" / "updates.log").read_text(encoding="utf-8")
    assert "update: checked latest=%s installed=%s" % (LATEST, INSTALLED) in log
    assert "update: staged %s" % LATEST in log
    assert "/latest" in _Feed.seen and any(path.endswith("/" + qu.ASSET_NAME) for path in _Feed.seen)
    assert state.is_relative_to(Path(os.environ["LOCALAPPDATA"]))


@pytest.mark.parametrize("marker_changes,metadata_id,expected", [
    ({}, LATEST, "idle"),
    ({"build_id": LATEST}, LATEST, "failed"),
    ({"built_at": "2026-11-01T19:25:00Z"}, LATEST, "failed"),
    ({"built_at": "2026-11-02T00:00:00Z"}, LATEST, "failed"),
    ({"built_at": None}, LATEST, "failed"),
    ({"built_at": "invalid time"}, LATEST, "failed"),
    ({}, INSTALLED, "failed"),
    ({"build_id": ""}, LATEST, "failed"),
    ({"build_id": "20261001-110000-1-1-abcdef123456", "built_at": None}, LATEST, "idle"),
    ({"sha256": None}, LATEST, "failed"),
    ({"sha256": "abcd"}, LATEST, "failed"),
    ({"sha256": "x" * 64}, LATEST, "failed"),
])
def test_installed_status_suppresses_only_an_older_rollback(
        tmp_path, monkeypatch, marker_changes, metadata_id, expected):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text(LATEST)
    (app / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": metadata_id, "built_at": "2026-11-01T19:25:00Z"}))
    state = tmp_path / "state"
    marker = state / "updates" / "staged.json"
    marker.parent.mkdir(parents=True)
    failure = {"build_id": INSTALLED, "built_at": "2026-11-01T15:19:00Z", "phase": "rolled_back",
               "rollback_reason": "Setup failed", "sha256": hashlib.sha256(INSTALLER).hexdigest(), **marker_changes}
    original = json.dumps({key: value for key, value in failure.items() if value is not None}).encode()
    marker.write_bytes(original)
    ui = ApplicationUpdate(state, app, request_restart=None, policy=lambda: {"channel": "stable"})
    assert ui.status()["state"] == expected
    assert ui.status()["available_build"] is None
    # A check returning the same failed release must keep the same header as a fresh launch.
    monkeypatch.setattr(qu, "read_latest_release", lambda *args: {"build_id": failure["build_id"]})
    ui._download()
    assert ui.status()["state"] == expected
    assert ui.status()["available_build"] is None
    assert marker.read_bytes() == original


def test_fresh_profile_has_no_failed_update_before_or_after_check(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text(INSTALLED)
    state = tmp_path / "fresh-install"
    state.mkdir()
    ui = ApplicationUpdate(state, app, request_restart=None, policy=lambda: {"channel": "stable"})
    assert ui.status()["state"] == "idle"
    assert not list(state.iterdir())

    monkeypatch.setattr(qu, "read_latest_release", lambda *args: {"build_id": INSTALLED})
    ui.check()
    ui._worker.join(timeout=10)
    assert not ui._worker.is_alive()
    assert ui.status()["state"] == "idle"
    assert ui.status()["available_build"] is None
    assert not (state / "updates" / "staged.json").exists()
