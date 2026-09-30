"""A clean server whose own workspace root was not resolved at start refuses
every workspace-roots request before any read or change, even after the shared
resolver would now succeed: it never adopts a root resolved later."""
from __future__ import annotations

import pytest

from nodelang import workspace_roots_catalogue as roots
from nodelang.application_server import _CleanAuthorityHttpServer


class _Untouchable:
    def __getattr__(self, name):  # any read or change of the authority fails the court
        raise AssertionError("the workspace-roots handler touched the authority: " + name)


@pytest.mark.parametrize("action", [{"action": "list"},
                                    {"action": "unregister", "id": "alpha"},
                                    {"action": "republish"}])
def test_an_unresolved_start_root_refuses_before_anything_even_when_resolvable_now(
        monkeypatch, action):
    server = object.__new__(_CleanAuthorityHttpServer)
    server.clean_workspace_root = None          # start-time resolution failed
    server.clean_authority = _Untouchable()
    server.clean_caller = None
    server.workspace_roots_boot = "match"
    # The shared resolver would succeed now (map or environment changed later).
    monkeypatch.setattr(roots, "built_in_path", lambda: "C:\\Elsewhere\\00.ARCHUB")
    with pytest.raises(roots.WorkspaceRootRefused, match="not resolved at start"):
        server._clean_workspace_roots(dict(action))
