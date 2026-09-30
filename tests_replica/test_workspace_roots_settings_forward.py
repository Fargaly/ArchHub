"""Settings -> Workspaces from the desktop (founder 2026-09-30: "Browse doesn't work,
Add doesn't work"). The desktop's /studio is served by the application server, but
the roots live in the graph the clean owner holds: the request is forwarded, signed
with the settings key, and answered by the owner's own workspace-roots route.

A real CleanCoordinationHost and the real forwarder over an in-process transport;
nothing live is reachable (the `graph` fixture pins graph_context)."""
from __future__ import annotations

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.clean_coordination_host import CoordinationIdentity, sign_coordination_request
from nodelang.universal_cell import InvalidCell
from tests_replica.test_workspace_roots_graph_current import graph  # noqa: F401


def _bind(graph, calls):
    def route(body):
        calls.append(body)
        return {"answered_by": "the owner's route", "action": body.get("action")}
    graph["host"].bind_workspace_settings(graph["authority"], route)


def test_a_forwarded_request_is_answered_by_the_owners_route(graph):
    calls = []
    _bind(graph, calls)
    answer = roots.forward_workspace_settings({"action": "list"})
    assert answer == {"answered_by": "the owner's route", "action": "list"}
    assert calls == [{"action": "list"}]


def test_an_owner_without_the_route_refuses(graph):
    with pytest.raises(InvalidCell, match="serves no workspace settings"):
        roots.forward_workspace_settings({"action": "list"})


def test_the_settings_key_asks_only_for_settings_and_no_other_key_may(graph):
    _bind(graph, [])
    settings = CoordinationIdentity(*roots.SETTINGS_IDENTITY)
    for method, parameters in (("list_agents", {}), ("workspace_roots_state", {"nonce": "0" * 32})):
        with pytest.raises(InvalidCell, match="not admitted for this key"):
            graph["host"].dispatch(sign_coordination_request(graph["keys"], settings, method, parameters))
    for other in (CoordinationIdentity(*roots.ISSUER_IDENTITY), CoordinationIdentity("codex", "court-other")):
        with pytest.raises(InvalidCell, match="not admitted for this key"):
            graph["host"].dispatch(sign_coordination_request(
                graph["keys"], other, "workspace_roots_settings", {"body": {"action": "list"}}))
    assert graph["host"]._bindings == {}


def test_only_the_owner_binds_the_route():
    from nodelang.clean_coordination_host import CleanCoordinationHost
    host = CleanCoordinationHost.__new__(CleanCoordinationHost)
    host.authority = object()
    with pytest.raises(InvalidCell):
        host.bind_workspace_settings(object(), lambda body: {})


def test_a_refusal_and_an_unreachable_owner_come_back_as_refusals(graph):
    graph["context"]["transport"] = lambda payload: {"ok": False, "error": "the owner declined (0x800704c7)"}
    with pytest.raises(roots.WorkspaceRootRefused, match="0x800704c7"):
        roots.forward_workspace_settings({"action": "register"})

    def down(payload):
        raise ConnectionRefusedError("127.0.0.1:8474")
    graph["context"]["transport"] = down
    with pytest.raises(roots.WorkspaceRootRefused, match="not answering"):
        roots.forward_workspace_settings({"action": "list"})


def test_the_picked_folder_is_a_local_windows_path_or_nothing():
    assert roots.normalized_picked_folder("E:/01.PERSONAL") == "E:" + chr(92) + "01.PERSONAL"
    assert roots.normalized_picked_folder("") == "" and roots.normalized_picked_folder(None) == ""
    with pytest.raises(roots.WorkspaceRootRefused):
        roots.normalized_picked_folder(chr(92) * 2 + "server" + chr(92) + "share")
