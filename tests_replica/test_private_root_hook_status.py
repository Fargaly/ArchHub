from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


def _hooks_dir():
    configured = os.environ.get("ARCHHUB_GOVERNANCE_HOOKS", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).parents[1] / "_gov" / "hooks"


@pytest.fixture()
def authority_module(monkeypatch):
    hooks = _hooks_dir()
    monkeypatch.syspath_prepend(str(hooks))
    sys.modules.pop("app_write_authority", None)
    return importlib.import_module("app_write_authority")


def test_app_write_authority_dispatches_private_root_grant_status(authority_module):
    authority = object.__new__(authority_module.AppWriteAuthority)
    seen = {}

    class Client:
        def private_root_grant_status(self, **kwargs):
            seen.update(kwargs)
            return {"granted": True, "until": 1800.0, "agent_session": "app:agent-session:1"}

    def run(runtime, session_id, operation):
        seen["runtime"] = runtime
        seen["session_id"] = session_id
        return operation(Client())

    authority.run = run
    result = authority(
        authority_module.PRIVATE_ROOT_STATUS,
        {
            "vendor": "codex",
            "session_id": "court-session",
            "path": "workspace-roots/bbc4/__grant_status__",
            "operation": "write_file",
        },
        timeout=7.0,
    )
    assert result["granted"] is True
    assert seen == {
        "runtime": "codex",
        "session_id": "court-session",
        "path": "workspace-roots/bbc4/__grant_status__",
        "operation": "write_file",
        "response_timeout_seconds": 7.0,
    }
