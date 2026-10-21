"""The canvas asks the RUNNING server what it can reach, over HTTP."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from nodelang.application_server import ApplicationServer
from nodelang.cell_capabilities import CAPABILITIES


def _get(server, path):
    """The canvas presents its browser session; so does this court."""
    request = urllib.request.Request(server.url + path)
    request.add_header("X-ArchHub-Session", server.browser_session_token)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_unauthenticated(server, path):
    try:
        with urllib.request.urlopen(server.url + path, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as denied:
        return denied.code, json.loads(denied.read().decode("utf-8"))


def test_the_running_server_answers_what_it_can_reach():
    server = ApplicationServer().start()
    try:
        status, body = _get(server, "/api/universal/capabilities")
    finally:
        server.close()
    assert status == 200
    assert body["ok"] is True
    assert body["missing"] == []
    assert len(body["capabilities"]) == len(CAPABILITIES)
    assert all(item["present"] for item in body["capabilities"])


def test_every_capability_reports_the_root_it_installed():
    server = ApplicationServer().start()
    try:
        _status, body = _get(server, "/api/universal/capabilities")
    finally:
        server.close()
    reported = {item["name"]: item["root"] for item in body["capabilities"]}
    for name, root, _key in CAPABILITIES:
        assert reported[name] == root


def test_the_answer_names_the_revision_it_was_read_at():
    server = ApplicationServer().start()
    try:
        _status, body = _get(server, "/api/universal/capabilities")
    finally:
        server.close()
    assert isinstance(body["revision"], int)
    assert body["revision"] > 0


def test_an_unauthenticated_caller_is_told_nothing_about_the_graph():
    server = ApplicationServer().start()
    try:
        status, body = _get_unauthenticated(server, "/api/universal/capabilities")
    finally:
        server.close()
    assert status == 403
    assert "capabilities" not in body
