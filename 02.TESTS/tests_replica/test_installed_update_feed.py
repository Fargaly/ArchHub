"""The installed update check, against a local release feed. No source is read as proof."""
from __future__ import annotations

import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

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
    log = (state / "launcher.log").read_text(encoding="utf-8")
    assert "update: checked latest=%s installed=%s" % (LATEST, INSTALLED) in log
    assert "update: staged %s" % LATEST in log
    assert "/latest" in _Feed.seen and any(path.endswith("/" + qu.ASSET_NAME) for path in _Feed.seen)
    assert state.is_relative_to(Path(os.environ["LOCALAPPDATA"]))
