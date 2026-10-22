"""Settings -> Workspaces from the desktop (founder 2026-09-30: "Browse doesn't work,
Add doesn't work"). The desktop's /studio is served by the application server, but
the roots live in the graph the owner holds: the request is forwarded as the owner's
own workspace-roots route and answered by it, with the settings admission the route
expects. No key (founder 2026-10-22). A real CleanCoordinationHost and the real
forwarder over an in-process transport; nothing live is reachable (the `graph`
fixture pins graph_context)."""
from __future__ import annotations

import pytest

from nodelang import workspace_roots_catalogue as roots
from tests_replica.test_workspace_roots_graph_current import graph  # noqa: F401


def _bind(graph, calls):
    def route(body, *, admission=None):
        assert admission == {"principal": roots.settings_principal()}
        calls.append(body)
        return {"answered_by": "the owner's route", "action": body.get("action")}
    graph["owner"]._clean_workspace_roots = route


def test_a_forwarded_request_is_answered_by_the_owners_route(graph):
    calls = []
    _bind(graph, calls)
    answer = roots.forward_workspace_settings({"action": "list"})
    assert answer == {"answered_by": "the owner's route", "action": "list"}
    assert calls == [{"action": "list"}]


def test_the_settings_admission_is_the_routes_expected_principal():
    vendor, session = roots.SETTINGS_IDENTITY
    assert roots.settings_principal().startswith("agent-session.")
    assert vendor == "archhub" and session == "workspace-roots-settings"


def test_a_refusal_and_an_unreachable_owner_come_back_as_refusals(graph):
    graph["context"]["transport"] = lambda payload: {"ok": False, "error": "the owner declined (0x800704c7)"}
    with pytest.raises(roots.WorkspaceRootRefused, match="0x800704c7"):
        roots.forward_workspace_settings({"action": "register"})

    def down(payload):
        raise ConnectionRefusedError("127.0.0.1:8474")
    graph["context"]["transport"] = down
    with pytest.raises(roots.WorkspaceRootRefused, match="not answering"):
        roots.forward_workspace_settings({"action": "register"})
    # Listing never breaks a screen: no reachable owner = no roots yet.
    assert roots.forward_workspace_settings({"action": "list"}) == {"roots": [], "built_in": None}


def test_the_picked_folder_is_a_local_windows_path_or_nothing():
    assert roots.normalized_picked_folder("E:/01.PERSONAL") == "E:" + chr(92) + "01.PERSONAL"
    assert roots.normalized_picked_folder("") == "" and roots.normalized_picked_folder(None) == ""
    with pytest.raises(roots.WorkspaceRootRefused):
        roots.normalized_picked_folder(chr(92) * 2 + "server" + chr(92) + "share")
