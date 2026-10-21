"""Every private-root grant outcome leaves one non-secret receipt line.

Drives the desktop's real Settings route (Studio session over HTTP) and the
store-level receipt. All files live in the isolated temporary profile.
"""
from __future__ import annotations

import json

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.application_server import ApplicationServer
from nodelang.map_import import resolve_map_path
from nodelang.private_root_grants import GRANT_EVENT_LOG, record_grant_event
from nodelang.universal_application import build_universal_application
from tests_replica.test_application_server_governance import _json

ROUTE = "/api/universal/workspace-roots"
GRANT = {"action": "grant-private-root", "id": "01-personal", "runtime": "codex",
         "session_id": "app:agent-session:runtime:receipt-court"}


def _lines(directory):
    path = directory / GRANT_EVENT_LOG
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture()
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    store, registry = build_universal_application(resolve_map_path())
    server = ApplicationServer(universal_store=store, universal_registry=registry).start()
    try:
        yield server, tmp_path / "localappdata" / "ArchHub" / "governance"
    finally:
        server.close()


def test_a_refused_settings_grant_on_the_desktop_route_is_recorded_with_its_exact_text(
        desktop, monkeypatch):
    server, receipts = desktop

    def refuse(body):
        raise roots.WorkspaceRootRefused("the graph owner refused the court grant")

    monkeypatch.setattr(roots, "forward_workspace_settings", refuse)
    status, answer = _json(server.url, ROUTE, {**GRANT, "operations": ["write_file"]},
                           token=server.browser_session_token)
    assert status >= 400, answer
    [line] = _lines(receipts)
    assert line["stage"] == "desktop" and line["outcome"] == "refused"
    assert line["message"] == "WorkspaceRootRefused: the graph owner refused the court grant"
    assert (line["action"], line["id"], line["runtime"], line["session_id"]) == (
        GRANT["action"], GRANT["id"], GRANT["runtime"], GRANT["session_id"])
    assert set(line) == {"at", "stage", "outcome", "message", "action", "id", "runtime", "session_id"}


def test_an_accepted_settings_grant_records_the_owner_answer_and_a_list_records_nothing(
        desktop, monkeypatch):
    server, receipts = desktop
    monkeypatch.setattr(roots, "forward_workspace_settings", lambda body: {
        "roots": [], "last_private_grant_event": {"message": "Agent access granted."}})
    status, answer = _json(server.url, ROUTE, GRANT, token=server.browser_session_token)
    assert status == 200, answer
    status, _ = _json(server.url, ROUTE, {"action": "list"}, token=server.browser_session_token)
    assert status == 200
    [line] = _lines(receipts)
    assert (line["stage"], line["outcome"], line["message"]) == (
        "desktop", "ok", "Agent access granted.")


def test_a_grant_without_a_session_is_never_recorded(desktop, monkeypatch):
    server, receipts = desktop
    monkeypatch.setattr(roots, "forward_workspace_settings", lambda body: {})
    status, _ = _json(server.url, ROUTE, GRANT)
    assert status in (401, 403)
    assert _lines(receipts) == []


def test_session_picker_refusal_is_recorded_once_per_distinct_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(roots, "_last_session_refusal", None)

    class _Store:
        path = tmp_path / "private-root-grants.json"
        provider = None

        def list(self):
            return []

    from nodelang import application_machine_transport as transport

    class _Refusing:
        def __init__(self, *args):
            pass

        def request(self, *args):
            raise RuntimeError("requires the authenticated local Settings reader")

    monkeypatch.setattr(transport, "UniversalRuntimeClient", _Refusing)
    monkeypatch.setattr(transport, "default_runtime_descriptor_path", lambda: tmp_path / "none.json")
    for _ in range(2):
        view = roots.private_grant_settings_view(_Store())
        assert view["private_grant_sessions"]["status"] == "unavailable"
    [line] = _lines(tmp_path)
    assert (line["stage"], line["outcome"]) == ("list-sessions", "unavailable")
    assert line["message"] == "RuntimeError: requires the authenticated local Settings reader"


def test_an_unwritable_receipt_never_changes_the_outcome(tmp_path, capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    record_grant_event("owner", "ok", "Agent access granted.", GRANT, directory=blocker)
    assert "private-grant receipt not written" in capsys.readouterr().err


def test_the_receipt_keeps_no_secret_fields(tmp_path):
    record_grant_event("owner", "refused", "x", {**GRANT, "signature": "s" * 64,
                       "admission_ticket": "t", "operations": ["write_file"]}, directory=tmp_path)
    [line] = _lines(tmp_path)
    assert "signature" not in line and "admission_ticket" not in line and "operations" not in line
