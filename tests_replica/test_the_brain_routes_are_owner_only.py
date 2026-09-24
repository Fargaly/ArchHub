"""Court: the Brain routes are the application owner's alone.

/api/universal/brain-export, -forget, -edit and -remember read or change the
founder's memory. They admit exactly what POST /api/universal/terminal admits:
the request's own browser binding, still live, holding execute, and the
application owner. A binding of another subject, or one that holds only edit,
gets a 403 JSON refusal and the Brain is never asked. The owner still works.
"""
import json

import pytest

from nodelang import application_server as srv
from nodelang import pipeline_engines
from tests_replica.test_settings_terminal_routes import _other_subject, call, server  # noqa: F401

ROUTES = {
    "/api/universal/brain-export": {"limit": 5},
    "/api/universal/brain-forget": {"id": "f-1"},
    "/api/universal/brain-edit": {"id": "f-1", "text": "Walls are 250 mm"},
    "/api/universal/brain-remember": {"text": "Doors are 900 mm"},
}


@pytest.fixture
def brain(monkeypatch):
    asked = []

    def fake(tool, arguments, *, budget=None):
        asked.append(tool)
        if tool == "brain.list_facts":
            return json.dumps({"ok": True, "folders": []})
        return json.dumps({"ok": True})
    monkeypatch.setattr(pipeline_engines, "_brain_call", fake)
    return asked


def test_a_binding_of_another_subject_is_refused_on_every_brain_route(server, brain, monkeypatch):
    _other_subject(server, monkeypatch)
    for path, body in ROUTES.items():
        refused = call(server, path, body, expected=403)
        assert refused["ok"] is False, path
    assert brain == [], "the Brain was asked for a non-owner"


def _execute_action_root(server):
    from nodelang.cell_cloud_routes import find_cloud_route, resolve_cloud_route
    snapshot = server.universal_store.snapshot()
    route = find_cloud_route(snapshot, server.universal_registry.cloud_route_protocol,
                             method="POST", path_template="/api/universal/terminal")
    return resolve_cloud_route(snapshot, route).action_root


def test_an_edit_only_binding_is_refused_on_every_brain_route(server, brain, monkeypatch):
    """The binding holds edit but not execute: the graph refuses execute only."""
    execute = _execute_action_root(server)
    real = srv.require_authorization

    def edit_only(snapshot, protocol, policy_root, broker, context, request, *args, **kwargs):
        if request.action_root == execute:
            raise srv.AuthorizationDenied("execute is not granted to this binding")
        return real(snapshot, protocol, policy_root, broker, context, request, *args, **kwargs)
    monkeypatch.setattr(srv, "require_authorization", edit_only)
    server._route_authorization_cache.clear()
    for path, body in ROUTES.items():
        call(server, path, body, expected=403)
    assert brain == [], "the Brain was asked for an edit-only binding"


def test_the_owner_still_reads_and_changes_the_brain(server, brain):
    for path, body in ROUTES.items():
        assert call(server, path, body)["ok"] is True, path
    assert brain == ["brain.list_facts", "brain.delete_fact", "brain.edit_fact", "brain.write"]


def test_the_route_table_asks_execute_for_every_brain_route():
    from nodelang import universal_application as app
    source = __import__("pathlib").Path(app.__file__).read_text(encoding="utf-8")
    for path in ROUTES:
        assert '("POST", "%s", "execute")' % path in source, path