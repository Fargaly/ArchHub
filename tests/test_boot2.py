"""BOOT2: real clean HTTP Home answers while its read-only warm-up is held."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import nodelang.application_server as servers
from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session, _json, _provision_clean_runtime, _start_clean_server,
)


def test_home_answers_before_catalogue_and_interactions_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    built, provider = _provision_clean_runtime(tmp_path)
    _issue_clean_session(built, token="boot2", csrf="boot2-csrf")
    authority = built.location.authority
    before = authority.store.revision
    entered, release = threading.Event(), threading.Event()
    derive = servers.derive_clean_scope_interactions

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(15), "court never released warm-up"
        return derive(*args, **kwargs)

    monkeypatch.setattr(servers, "derive_clean_scope_interactions", held)
    pool = ThreadPoolExecutor(max_workers=1)
    server = None
    future = pool.submit(_start_clean_server, built, provider)
    try:
        assert entered.wait(10)
        assert future.done() or future.result(timeout=2), (
            "server construction must not wait for catalogue/interaction warm-up"
        )
        server = future.result(timeout=2)
        started = time.perf_counter()
        status, home = _json(server.url, "/api/universal/canvas?screen=home", token="boot2")
        assert status == 200, home
        assert home["projection"] == "home"
        assert home["root"] == built.grand_map.root_id
        assert home["revision"] == before
        assert home["warmup"]["state"] == "almost_ready"
        assert home["nodes"] == [] and home["catalog"] == []
        assert time.perf_counter() - started < 2
        with urlopen(server.url + "/studio?key=" + server.clean_canvas_key, timeout=2) as response:
            assert b"studio-ready-status" in response.read()
        status, progress = _json(server.url, "/api/universal/boot", token="boot2")
        assert status == 200 and progress["state"] == "almost_ready"
        assert not server._boot_ready.is_set()
        assert authority.store.revision == before, "Home and warm-up must not write Cells"
        release.set()
        assert server._boot_ready.wait(15)
        status, progress = _json(server.url, "/api/universal/boot", token="boot2")
        assert status == 200 and progress["state"] == "ready"
        status, canvas = _json(server.url, "/api/universal/canvas", token="boot2")
        assert status == 200 and canvas["catalog"], canvas
        assert authority.store.revision == before
    finally:
        release.set()
        if server is None:
            server = future.result(timeout=20)
        server.close()
        pool.shutdown(wait=True)
        authority.store.close()


def test_warm_failure_is_visible_and_canvas_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    built, provider = _provision_clean_runtime(tmp_path)
    _issue_clean_session(built, token="boot2-fail", csrf="boot2-fail-csrf")

    def refused(*args, **kwargs):
        raise RuntimeError("fixture warm-up refusal")

    monkeypatch.setattr(servers, "derive_clean_scope_interactions", refused)
    server = None
    try:
        server = _start_clean_server(built, provider)
        assert server._boot_ready.wait(10)
        status, state = _json(server.url, "/api/universal/boot", token="boot2-fail")
        assert status == 200 and state["state"] == "failed"
        assert "unavailable" in state["message"].lower()
        status, canvas = _json(server.url, "/api/universal/canvas", token="boot2-fail")
        assert status == 403 and "warm-up" in canvas["error"]
    finally:
        if server:
            server.close()
        built.location.authority.store.close()


def test_boot_progress_requires_browser_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        with pytest.raises(HTTPError) as refused:
            urlopen(server.url + "/api/universal/boot", timeout=2)
        assert refused.value.code == 403
        assert json.loads(refused.value.read())["ok"] is False
    finally:
        server.close()
        built.location.authority.store.close()
