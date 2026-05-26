"""AgDR-0045 — bridge slots for the Settings × Brain wire.

The bridge exposes 8 `brain_*` slots that proxy to MCP tools on the
local brain daemon (port 8473). These tests:

  * Pin every slot exists on `ArchHubBridge` so JSX wiring doesn't
    silently break on rename.
  * Verify `brain_status` returns a JSON envelope (never raises) when
    the daemon is down — the JSX status pulse depends on this.
  * Mock `BrainClient._call` for the rest of the slots so we get
    deterministic JSON-shape assertions without touching the network.

Tests do NOT require:
  * ArchHub to be running
  * The brain daemon to be running
  * QtWebEngine

All HTTP I/O is mocked via `monkeypatch` on `BrainClient`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ─────────────────────── fixtures ────────────────────────────────────


class _StubManager:
    """Stand-in for the connector manager — bridge only needs the
    `active_families` method for slots that aren't brain_*."""
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    """A bridge instance with no router / engine — the brain slots
    only touch `memory_gate.BrainClient`, which we mock per-test."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    return _bridge_module.ArchHubBridge(
        manager=_StubManager(),
        auto_extract_memory=False,
    )


@pytest.fixture
def mock_brain_call(monkeypatch):
    """Replace `BrainClient._call` with a recorder that captures the
    arguments + returns a configurable dict. Use the returned
    `set_response()` to drive the response per test."""
    state = {"calls": [], "response": {"ok": True}}

    def fake_call(self, tool, params, timeout=None):
        state["calls"].append({"tool": tool, "params": params,
                               "timeout": timeout})
        resp = state["response"]
        if isinstance(resp, Exception):
            raise resp
        return resp

    import memory_gate
    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    def set_response(resp):
        state["response"] = resp

    state["set"] = set_response
    return state


# ─────────────────────── slot-presence tests ─────────────────────────


def test_bridge_has_brain_slots():
    """Every brain_* slot named in AgDR-0045 must exist on
    `ArchHubBridge`. Silent renames break JSX wiring."""
    from bridge import ArchHubBridge
    required = [
        "brain_status",
        "brain_firm_create",
        "brain_firm_invite_create",
        "brain_firm_invite_accept",
        "brain_firm_seats",
        "brain_firm_leave",
        "brain_promote",
        "brain_wiring_announce",
    ]
    missing = [m for m in required if not hasattr(ArchHubBridge, m)]
    assert not missing, f"Bridge missing brain slots: {missing}"
    for name in required:
        assert callable(getattr(ArchHubBridge, name)), (
            f"ArchHubBridge.{name} exists but isn't callable."
        )


def test_brain_slots_return_str_annotation():
    """Each brain slot returns a `str` (JSON-encoded) — that's the
    QWebChannel contract. Catch silent return-type drift.

    Note: `from __future__ import annotations` in bridge.py makes
    annotations strings rather than evaluated types, so we accept
    either the `str` type itself OR the string literal "str"."""
    import inspect
    from bridge import ArchHubBridge
    for name in (
        "brain_status",
        "brain_firm_create",
        "brain_firm_invite_create",
        "brain_firm_invite_accept",
        "brain_firm_seats",
        "brain_firm_leave",
        "brain_promote",
        "brain_wiring_announce",
    ):
        fn = getattr(ArchHubBridge, name)
        sig = inspect.signature(fn)
        ann = sig.return_annotation
        assert ann is str or ann == "str", (
            f"ArchHubBridge.{name} return annotation is "
            f"{ann!r}, expected str."
        )


# ─────────────────────── daemon-down behaviour ───────────────────────


def test_brain_status_returns_json_string_when_daemon_down(
    bridge_inst, monkeypatch
):
    """`brain_status()` must return a parseable JSON STRING even when
    the daemon is unreachable. JSX assumes the slot never raises."""
    import memory_gate

    # Force every _call to raise as if daemon refused the connection.
    def fake_call(self, tool, params, timeout=None):
        raise ConnectionRefusedError("daemon down")
    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    # Optional: also force is_available → False (mandate phrasing).
    monkeypatch.setattr(memory_gate.BrainClient, "is_available",
                         lambda self: False)

    raw = bridge_inst.brain_status()
    assert isinstance(raw, str)
    data = json.loads(raw)  # MUST parse — never raise.
    # The envelope. The exact `error` text may vary; what matters is
    # that ok is False and the call did not raise.
    assert data.get("ok") is False
    # Either a top-level `error` OR a nested `health.ok=False` is fine
    # — both signal "daemon unreachable" to JSX.
    has_error = "error" in data or (
        isinstance(data.get("health"), dict) and not data["health"].get("ok")
    )
    assert has_error, f"brain_status envelope lacks failure marker: {data}"


def test_brain_status_returns_ok_envelope_on_success(
    bridge_inst, mock_brain_call
):
    """Happy path: daemon healthy → envelope reports ok=True."""
    mock_brain_call["set"]({"ok": True, "version": "0.4.0",
                            "db_path": "/fake/brain.db"})
    raw = bridge_inst.brain_status()
    data = json.loads(raw)
    assert data.get("ok") is True
    # The slot wraps health in `health` + last_hit alongside.
    assert "health" in data
    assert data["health"].get("ok") is True


# ─────────────────────── per-slot proxy tests ────────────────────────


def test_brain_firm_create_passes_args_to_mcp_tool(
    bridge_inst, mock_brain_call
):
    """`brain_firm_create(name, created_by, force)` must hit
    `brain.firm_create` with the right args."""
    mock_brain_call["set"]({"ok": True, "firm_id": "f-1"})
    raw = bridge_inst.brain_firm_create("ArchHub Studio", "alice", 0)
    data = json.loads(raw)
    assert data.get("ok") is True
    assert data.get("firm_id") == "f-1"
    # One call recorded; tool name correct; args mapped.
    assert len(mock_brain_call["calls"]) == 1
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.firm_create"
    assert rec["params"]["name"] == "ArchHub Studio"
    assert rec["params"]["created_by"] == "alice"
    assert rec["params"]["force"] is False


def test_brain_firm_invite_create_proxies(bridge_inst, mock_brain_call):
    mock_brain_call["set"]({"ok": True, "token": "tok-abc"})
    raw = bridge_inst.brain_firm_invite_create("seat", 24)
    data = json.loads(raw)
    assert data.get("ok") is True
    assert data.get("token") == "tok-abc"
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.firm_invite_create"
    assert rec["params"]["role"] == "seat"
    assert rec["params"]["ttl_hours"] == 24


def test_brain_firm_invite_accept_proxies(bridge_inst, mock_brain_call):
    mock_brain_call["set"]({"ok": True})
    raw = bridge_inst.brain_firm_invite_accept("tok-abc", "bob")
    data = json.loads(raw)
    assert data.get("ok") is True
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.firm_invite_accept"
    assert rec["params"]["token"] == "tok-abc"
    assert rec["params"]["user_id"] == "bob"


def test_brain_firm_seats_proxies(bridge_inst, mock_brain_call):
    mock_brain_call["set"]({"ok": True, "seats": [
        {"user_id": "alice", "role": "admin"},
    ]})
    raw = bridge_inst.brain_firm_seats()
    data = json.loads(raw)
    assert data.get("ok") is True
    assert isinstance(data.get("seats"), list)
    assert mock_brain_call["calls"][0]["tool"] == "brain.firm_seats"


def test_brain_firm_leave_proxies(bridge_inst, mock_brain_call):
    mock_brain_call["set"]({"ok": True})
    raw = bridge_inst.brain_firm_leave()
    data = json.loads(raw)
    assert data.get("ok") is True
    assert mock_brain_call["calls"][0]["tool"] == "brain.firm_leave"


def test_brain_promote_proxies_with_scope_args(bridge_inst, mock_brain_call):
    mock_brain_call["set"]({"ok": True, "promoted": True})
    raw = bridge_inst.brain_promote("frag-1", "firm", 1)
    data = json.loads(raw)
    assert data.get("ok") is True
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.promote"
    assert rec["params"]["fragment_id"] == "frag-1"
    assert rec["params"]["target_scope"] == "firm"
    assert rec["params"]["is_maintainer"] is True


def test_brain_wiring_announce_includes_device_and_cwd(
    bridge_inst, mock_brain_call
):
    """`brain_wiring_announce()` injects device_id (hostname) + cwd
    — BRAIN-FIRST MANDATE wiring contract."""
    mock_brain_call["set"]({"ok": True, "scope_hint": "USER"})
    raw = bridge_inst.brain_wiring_announce()
    data = json.loads(raw)
    assert data.get("ok") is True
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.wiring_announce"
    # Device id is non-empty and cwd looks like a path string.
    assert rec["params"].get("device_id")
    assert isinstance(rec["params"].get("cwd"), str)
    assert len(rec["params"]["cwd"]) > 0


# ─────────────────────── error-shape contract ───────────────────────


def test_brain_slot_returns_error_envelope_on_exception(
    bridge_inst, monkeypatch
):
    """Generic shape: any brain_* slot wraps an exception into
    {ok: false, error: ...} JSON — never raises across the bridge."""
    import memory_gate

    def fake_call(self, tool, params, timeout=None):
        raise RuntimeError("simulated daemon explosion")

    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    raw = bridge_inst.brain_firm_seats()
    data = json.loads(raw)
    assert data.get("ok") is False
    assert "error" in data
    assert "explosion" in data["error"] or "RuntimeError" in data["error"]


def test_brain_slot_returns_error_when_brainclient_import_fails(
    bridge_inst, monkeypatch
):
    """If `memory_gate.BrainClient` can't be constructed (e.g. missing
    deps in a slimmed install), the slot still returns a clean
    JSON envelope. JSX never sees a Python traceback."""
    import memory_gate

    class _Boom:
        def __init__(self, *a, **k):
            raise ImportError("BrainClient unavailable on this device")

    monkeypatch.setattr(memory_gate, "BrainClient", _Boom)

    raw = bridge_inst.brain_firm_leave()
    data = json.loads(raw)
    assert data.get("ok") is False
    assert "error" in data
