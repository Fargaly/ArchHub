"""The launcher starts one HTTP server, and that server answers the Studio."""
from __future__ import annotations

import json
import re
from http.client import HTTPConnection
from pathlib import Path

from nodelang.nograph_server import COOKIE, NoGraphServer

ROOT = Path(__file__).resolve().parents[2]


def _studio_paths():
    text = (ROOT / "01.APP/nodelang/studio/api.js").read_text(encoding="utf-8")
    found = set(re.findall(r"""['"](/(?:api|stop-all|resume)[^'"]*)['"]""", text))
    found.update("/api/universal/" + suffix for suffix in re.findall(r"'(brain-[a-z-]+)'", text))
    paths = set()
    for item in found:
        path = item.split("?", 1)[0]
        if path.rstrip("/") == "/api/universal":
            continue
        if path.startswith("/api/") or path in {"/stop-all", "/resume"}:
            paths.add(path)
    return sorted(paths)


def _exchange(connection, method, path, body, headers):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    connection.request(method, path, payload, headers)
    response = connection.getresponse()
    raw = response.read()
    parsed = json.loads(raw.decode("utf-8")) if raw else {}
    return response.status, parsed


def test_the_launcher_starts_one_server_and_it_answers_the_studio(tmp_path, monkeypatch):
    home = tmp_path / "home"
    local = tmp_path / "local"
    roaming = tmp_path / "roaming"
    temp = tmp_path / "temp"
    state = tmp_path / "state"
    for folder in (home, local, roaming, temp, state):
        folder.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setenv("ARCHHUB_TEST_NO_OPEN", "1")

    launcher = (ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8")
    shell = (ROOT / "01.APP/nodelang/nograph_launcher.py").read_text(encoding="utf-8")
    server_source = (ROOT / "01.APP/nodelang/nograph_server.py").read_text(encoding="utf-8")
    _head, boot = launcher.split("from nodelang.nograph_launcher import run as _run_nograph", 1)
    assert "application_server" not in boot
    assert "ApplicationServer" not in boot
    assert shell.count("NoGraphServer(") == 1
    assert "ApplicationServer" not in shell
    assert server_source.count("QuietThreadingHTTPServer(") == 1

    paths = _studio_paths()
    assert "/api/universal/canvas" in paths
    assert "/api/universal/session" in paths
    assert "/api/router/chat" in paths

    server = NoGraphServer(state).start()
    try:
        connection = HTTPConnection("127.0.0.1", server.port)
        status, signed = _exchange(
            connection, "POST", "/api/universal/session", {},
            {"Content-Type": "application/json", "X-ArchHub-Sign-In": "1",
             "Cookie": "%s=%s" % (COOKIE, server._cookie_token)})
        assert status == 200 and signed["ok"] is True
        admitted = {"Content-Type": "application/json",
                    "X-ArchHub-Session": signed["token"], "X-ArchHub-CSRF": signed["csrf"]}
        server.halt_all()
        chat_status, _chat = _exchange(connection, "POST", "/api/router/chat", {"prompt": ""}, admitted)
        assert chat_status != 404
        server.resume_all()
        for path in paths:
            if path in {"/api/universal/session", "/api/router/chat"}:
                continue
            status, _payload = _exchange(connection, "GET", path, None, admitted)
            assert status != 404, path
    finally:
        server.close()
