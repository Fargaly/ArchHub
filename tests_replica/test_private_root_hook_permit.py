from __future__ import annotations

import hashlib
import importlib
import os
import sys
import time
from pathlib import Path

import pytest


CONTENT = "synthetic private root write"


def _hooks_dir():
    configured = os.environ.get("ARCHHUB_GOVERNANCE_HOOKS", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).parents[1] / "_gov" / "hooks"


@pytest.fixture()
def broker(monkeypatch):
    hooks = _hooks_dir()
    monkeypatch.syspath_prepend(str(hooks))
    for name in ("governed_write_broker", "cde_gate", "path_identity"):
        sys.modules.pop(name, None)
    return importlib.import_module("governed_write_broker")


def _event(folder):
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "vendor": "codex",
        "session_id": "court-private-root",
        "tool_use_id": "private-root-tool-use",
        "cwd": str(folder),
        "tool_input": {
            "file_path": str(folder / "drawings" / "synthetic.dwg"),
            "content": CONTENT,
        },
    }


def _binding(folder):
    import path_identity
    return {"id": "bbc4", "path": str(folder), "identity": list(path_identity.identity(folder))}


def test_private_root_hook_requests_owner_permit_without_work_claim(broker, tmp_path):
    folder = tmp_path / "bbc4"
    (folder / "drawings").mkdir(parents=True)
    calls = []

    def transport(name, arguments, *, timeout=25.0):
        calls.append((name, dict(arguments)))
        assert name == "brain.universal_cde_write_permit"
        assert "work" not in arguments and "work_root" not in arguments
        assert arguments["path"] == "workspace-roots/bbc4/drawings/synthetic.dwg"
        return {
            "permit": "private-root-permit",
            "expires_at": time.time() + 60,
            "operation": arguments["operation"],
            "path": arguments["path"],
            "content_digest": arguments["content_digest"],
            "request_id": arguments["request_id"],
            "root_registration": _binding(folder),
        }

    prepared = broker.prepare_signed_write_event(
        _event(folder),
        vendor="codex",
        workspace_root=folder,
        path_prefix="workspace-roots/bbc4/",
        root_binding=_binding(folder),
        pending_root=tmp_path / "pending",
        transport=transport,
    )
    assert prepared["allow"] is True, prepared
    assert prepared["permit_count"] == 1
    assert len(calls) == 1
    assert calls[0][1]["content_digest"] == hashlib.sha256(CONTENT.encode()).hexdigest()


def test_private_root_hook_refuses_when_owner_denies_grant(broker, tmp_path):
    folder = tmp_path / "bbc4"
    (folder / "drawings").mkdir(parents=True)

    def transport(name, arguments, *, timeout=25.0):
        raise broker.BrainToolError("no grant: ask the founder in Settings > Workspaces")

    prepared = broker.prepare_signed_write_event(
        _event(folder),
        vendor="codex",
        workspace_root=folder,
        path_prefix="workspace-roots/bbc4/",
        root_binding=_binding(folder),
        pending_root=tmp_path / "pending",
        transport=transport,
    )
    assert prepared["allow"] is False
    assert prepared["code"] == "signed_write_permit_denied"
    assert "no grant" in prepared["message"]
