"""Courts for the session-bound CDE claim handoff lifecycle.

The JSON state is a non-authoritative hook projection.  It must not disappear
because a later prompt finds no new Work or because Brain is briefly
unreachable; signed write admission still rechecks the graph-held Session and
Work claim.  Only an exact-session release/cleanup or expiry may remove it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
BRAIN_SRC = ROOT / "personal-brain-mcp" / "src"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(BRAIN_SRC))

import brainwrap  # noqa: E402
from personal_brain import active_work  # noqa: E402


def _container(*, expires_at: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "container_id": "GM.governance.signed-cde-receipt-hook",
        "source_requirement": "founder:cde-claim-lifecycle",
        "domain": "brain",
        "tier": "T1",
        "lifecycle_state": "WIP",
        "suitability_status": "S0",
        "revision": "P01",
        "owner": "founder",
        "checker": "court",
        "allowed_paths": ["10.PRODUCT/12.PRODUCTION/tools/brainwrap.py"],
        "gate_kind": "pytest",
        "gate_spec": {"path": "tests/test_cde_claim_lifecycle.py"},
        "map_status": "partial",
    }
    if expires_at is not None:
        value["expires_at"] = expires_at
    return value


def _leaf(*, expires_at: str | None = None) -> dict[str, object]:
    return {
        "leaf_id": "work:cde-lifecycle",
        "title": "CDE lifecycle",
        "cde_container": _container(expires_at=expires_at),
    }


class _ToolRegistry:
    def __init__(self, manager) -> None:
        self._universal_runtime_session_manager = manager
        self.handlers = {}

    def tool(self, *, name: str, description: str):
        del description

        def register(handler):
            self.handlers[name] = handler
            return handler

        return register


class _EmptyFrontierManager:
    def enroll(self, *, runtime: str, external_session_id: str):
        return {
            "agent_session": f"app:agent-session:{runtime}:{external_session_id}",
            "runtime": runtime,
            "reused": True,
            "revision": 41,
        }

    def claim_next(self, *, runtime: str, external_session_id: str):
        del runtime, external_session_id
        return {"claimed": False, "work": None, "status": {"revision": 41}}


class _UnavailableManager(_EmptyFrontierManager):
    def claim_next(self, *, runtime: str, external_session_id: str):
        del runtime, external_session_id
        raise RuntimeError("temporary daemon failure")


def _direct_assignment_handler(manager):
    registry = _ToolRegistry(manager)
    active_work.register_active_work_tools(registry, object())
    return registry.handlers["brain.work_assigned_block"]


def test_wrapper_empty_frontier_preserves_exact_session_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    brainwrap._write_active_cde_state(
        _leaf(), runtime="codex", session_id="session-a"
    )
    path = brainwrap._active_cde_state_path(
        runtime="codex", session_id="session-a"
    )

    with patch.object(
        brainwrap,
        "call_tool",
        return_value={
            "ok": True,
            "universal": True,
            "agent_session": "app:agent-session:a",
            "block": "",
            "leaf": None,
        },
    ):
        assert brainwrap.fetch_drive_block(
            runtime="codex", session_id="session-a"
        ) == ""

    assert path.exists()


def test_wrapper_daemon_failure_preserves_exact_session_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    brainwrap._write_active_cde_state(
        _leaf(), runtime="codex", session_id="session-a"
    )
    path = brainwrap._active_cde_state_path(
        runtime="codex", session_id="session-a"
    )

    with patch.object(brainwrap, "call_tool", return_value=None):
        assert brainwrap.fetch_drive_block(
            runtime="codex", session_id="session-a"
        ) == ""

    assert path.exists()


def test_missing_session_never_erases_runtime_fallback_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    brainwrap._write_active_cde_state(_leaf(), runtime="codex", session_id="")
    path = brainwrap._active_cde_state_path(runtime="codex", session_id="")

    with patch.object(brainwrap, "call_tool") as call:
        assert brainwrap.fetch_drive_block(runtime="codex", session_id="") == ""

    call.assert_not_called()
    assert path.exists()


def test_explicit_cleanup_clears_only_the_exact_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    for session_id in ("session-a", "session-b"):
        brainwrap._write_active_cde_state(
            _leaf(), runtime="codex", session_id=session_id
        )
    path_a = brainwrap._active_cde_state_path(
        runtime="codex", session_id="session-a"
    )
    path_b = brainwrap._active_cde_state_path(
        runtime="codex", session_id="session-b"
    )

    brainwrap._clear_active_cde_state(
        runtime="codex", session_id="session-a"
    )

    assert not path_a.exists()
    assert path_b.exists()


def test_state_projection_records_the_exact_session_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    brainwrap._write_active_cde_state(
        _leaf(), runtime="codex", session_id="session-a"
    )
    path = brainwrap._active_cde_state_path(
        runtime="codex", session_id="session-a"
    )

    state = json.loads(path.read_text(encoding="utf-8"))

    assert state["runtime"] == "codex"
    assert state["session_id"] == "session-a"


def test_expired_recovery_projection_is_not_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    brainwrap._write_active_cde_state(
        _leaf(expires_at=expired), runtime="codex", session_id="session-a"
    )
    path = brainwrap._active_cde_state_path(
        runtime="codex", session_id="session-a"
    )

    with patch.object(brainwrap, "call_tool", return_value=None):
        brainwrap.fetch_drive_block(runtime="codex", session_id="session-a")

    assert not path.exists()


def test_direct_hook_empty_frontier_preserves_exact_session_claim(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    active_work._write_active_cde_state(
        _leaf(), runtime="claude-code", session_id="session-a"
    )
    path = active_work._active_cde_state_path(
        runtime="claude-code", session_id="session-a"
    )

    result = _direct_assignment_handler(_EmptyFrontierManager())(
        runtime="claude-code", session_id="session-a", owner_user="founder"
    )

    assert result["ok"] is True
    assert result["leaf"] is None
    assert path.exists()


def test_direct_hook_daemon_failure_preserves_exact_session_claim(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ARCHHUB_ACTIVE_CDE_STATE", raising=False)
    active_work._write_active_cde_state(
        _leaf(), runtime="claude-code", session_id="session-a"
    )
    path = active_work._active_cde_state_path(
        runtime="claude-code", session_id="session-a"
    )

    result = _direct_assignment_handler(_UnavailableManager())(
        runtime="claude-code", session_id="session-a", owner_user="founder"
    )

    assert result["ok"] is False
    assert result["code"] == "universal_work_unavailable"
    assert path.exists()
