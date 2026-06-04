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
        "brain_export_dataset",   # Brain #32 — dataset export button
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
        "brain_export_dataset",
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


# ─────────────────────── Brain #32 dataset export ───────────────────


class _SyncPool:
    """Stand-in for the bridge background pool — runs work inline so the
    threaded export slot is deterministic in tests (no real thread / no
    waiting on the brain_dataset_done signal)."""

    def submit(self, fn, *a, **k):
        fn(*a, **k)
        return None


def _patch_sync_pool(bridge_inst, monkeypatch):
    monkeypatch.setattr(bridge_inst, "_bg_pool", lambda: _SyncPool())


def test_brain_export_dataset_returns_started_envelope(
    bridge_inst, mock_brain_call, monkeypatch
):
    """The slot returns immediately with {async, request_id, out_dir,
    scope} — the threaded contract the JSX awaits before listening for
    the brain_dataset_done signal."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "row_count": 3,
                            "files": {"jsonl": {"path": "x", "bytes": 9}}})
    raw = bridge_inst.brain_export_dataset("user", "my-brain")
    data = json.loads(raw)
    assert data.get("async") is True
    assert data.get("request_id")
    assert data.get("scope") == "user"
    assert isinstance(data.get("out_dir"), str) and data["out_dir"]


def test_brain_export_dataset_proxies_to_tool_with_user_scope(
    bridge_inst, mock_brain_call, monkeypatch
):
    """USER scope → brain.dataset_export called with scopes=['user'],
    the dataset_name, and an out_dir. (Pool patched to run inline.)"""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "row_count": 2,
                            "scope_distribution": {"user": 2}})
    bridge_inst.brain_export_dataset("user", "my-brain")
    assert len(mock_brain_call["calls"]) == 1
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.dataset_export"
    assert rec["params"]["scopes"] == ["user"]
    assert rec["params"]["dataset_name"] == "my-brain"
    assert isinstance(rec["params"]["out_dir"], str)
    assert rec["params"]["out_dir"]


def test_brain_export_dataset_maps_collective_scope(
    bridge_inst, mock_brain_call, monkeypatch
):
    """The founder-facing 'collective' key maps to the brain's
    privacy-gated scope string — the export tool routes it through the
    DP aggregate path (no raw rows)."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "mode": "collective_dp",
                            "differential_privacy": True, "row_count": 0})
    bridge_inst.brain_export_dataset("collective", "firm-pool")
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.dataset_export"
    assert rec["params"]["scopes"] == ["collective"]


def test_brain_export_dataset_emits_done_signal_with_request_id(
    bridge_inst, mock_brain_call, monkeypatch
):
    """When the worker finishes it emits brain_dataset_done(result_json)
    carrying the manifest + the stamped request_id the JSX matches on."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "row_count": 5,
                            "files": {"jsonl": {"path": "p", "bytes": 1}}})
    captured: list = []
    bridge_inst.brain_dataset_done.connect(captured.append)

    raw = bridge_inst.brain_export_dataset("user", "my-brain")
    started = json.loads(raw)

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is True
    assert payload.get("row_count") == 5
    # request_id on the signal matches the one returned synchronously.
    assert payload.get("request_id") == started.get("request_id")


def test_brain_export_dataset_degrades_when_daemon_down(
    bridge_inst, monkeypatch
):
    """Daemon unreachable → the worker emits an {ok:false, error} payload
    on brain_dataset_done (never raises); the started envelope still
    comes back so the JSX doesn't hang."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import memory_gate

    def fake_call(self, tool, params, timeout=None):
        raise ConnectionRefusedError("daemon down")
    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    captured: list = []
    bridge_inst.brain_dataset_done.connect(captured.append)

    raw = bridge_inst.brain_export_dataset("user", "my-brain")
    assert json.loads(raw).get("async") is True
    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is False
    assert "error" in payload
    assert payload.get("request_id")


# ─────────────────────── Cloud-DB backup ("Back up my brain") ─────────


def test_bridge_has_cloud_backup_slots():
    """The Brain view's backup button wires to brain_cloud_backup (the
    threaded push) + brain_cloud_backup_status (the enable/disable probe).
    Silent renames break the button."""
    from bridge import ArchHubBridge
    for name in ("brain_cloud_backup", "brain_cloud_backup_status"):
        assert hasattr(ArchHubBridge, name), f"missing slot {name}"
        assert callable(getattr(ArchHubBridge, name))


def test_brain_cloud_backup_status_reports_not_signed_in(
    bridge_inst, monkeypatch
):
    """No cloud token → {signed_in: false}. The JSX keeps the button in the
    honest 'Sign in to enable' state. Probe does NO network I/O."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token", lambda: None)
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    raw = bridge_inst.brain_cloud_backup_status()
    data = json.loads(raw)
    assert data.get("signed_in") is False
    assert data.get("cloud_url") == "http://127.0.0.1:8789"


def test_brain_cloud_backup_status_reports_signed_in(
    bridge_inst, monkeypatch
):
    """A present token → {signed_in: true}. The JSX enables the button."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token",
                        lambda: "sk_test_fake_for_unit_test")
    raw = bridge_inst.brain_cloud_backup_status()
    data = json.loads(raw)
    assert data.get("signed_in") is True


def test_brain_cloud_backup_emits_need_signin_when_no_token(
    bridge_inst, monkeypatch
):
    """No token → the worker emits {ok:false, need_signin:true} on
    brain_backup_done (never a fake success); the started envelope comes
    back so the JSX doesn't hang. This is the honest-disabled path — the
    agent never signs in (founder's manual step)."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token", lambda: None)
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")

    captured: list = []
    bridge_inst.brain_backup_done.connect(captured.append)

    raw = bridge_inst.brain_cloud_backup()
    started = json.loads(raw)
    assert started.get("async") is True
    assert started.get("request_id")

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is False
    assert payload.get("need_signin") is True
    assert payload.get("request_id") == started.get("request_id")


def test_brain_cloud_backup_posts_delta_and_reports_synced(
    bridge_inst, monkeypatch, tmp_path
):
    """Slice-17 fanout: token present → the worker gathers USER+FIRM+
    COMMUNITY rows from brain.fanout_export, POSTs the delta to
    /v1/brain/sync (Bearer auth), and emits {ok:true, synced:N} carrying the
    server's `accepted` count + request_id. (Replaces the old USER-only
    dataset_export + JSONL path.)"""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token", lambda: "tok-test")
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")

    import memory_gate

    # brain.fanout_export now returns fragment rows directly (no JSONL file).
    # A firm row is included to prove non-USER scope rides the push.
    def fake_call(self, tool, params, timeout=None):
        if tool == "brain.fanout_export":
            assert params["scopes"] == ["user", "firm", "community"]
            return {"ok": True, "count": 2, "fragments": [
                {"id": "f1", "kind": "fact", "text": "ACME uses Revit",
                 "subject": "ACME", "predicate": "uses", "object": "Revit",
                 "scope": "user", "owner_user": "Fargaly", "extra": {},
                 "hlc": "0000000000000001000"},
                {"id": "f2", "kind": "fact", "text": "firm wall lib",
                 "scope": "firm", "firm_id": "firm-K", "owner_user": "Fargaly",
                 "extra": {}, "hlc": "0000000000000002000"},
            ]}
        if tool == "brain.community_groups":
            return {"ok": True, "communities": []}  # no relay communities
        if tool == "brain.fanout_apply":
            return {"ok": True, "applied": 0, "skipped": 0, "refused": 0}
        raise AssertionError(f"unexpected brain tool {tool}")
    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    # Capture the HTTP POST cloud_client.brain_sync makes to /v1/brain/sync —
    # assert the Bearer header + delta, return a realistic server response.
    posted = {}

    class _FakeResp:
        def __init__(self, body): self._b = body
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False
        status = 200

    def fake_urlopen(req, timeout=None):
        posted["url"] = req.full_url
        posted["auth"] = req.headers.get("Authorization")
        posted["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(json.dumps({
            "accepted": 2, "rejected": [],
            "new_hlc": "0000000000000009.abcdabcd",
            "merged": {"fragments": [], "wiring": []},
            "firm_keys": ["firm-K"], "community_keys": [],
        }).encode("utf-8"))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    captured: list = []
    bridge_inst.brain_backup_done.connect(captured.append)

    raw = bridge_inst.brain_cloud_backup()
    started = json.loads(raw)
    assert started.get("async") is True

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is True
    assert payload.get("synced") == 2
    assert payload.get("new_hlc") == "0000000000000009.abcdabcd"
    assert payload.get("request_id") == started.get("request_id")

    # Transport assertions — real Bearer auth + BOTH scopes in the delta.
    assert posted["url"] == "http://127.0.0.1:8789/v1/brain/sync"
    assert posted["auth"] == "Bearer tok-test"
    frag_ids = {f["id"] for f in posted["body"]["delta"]["fragments"]}
    assert frag_ids == {"f1", "f2"}, "USER + FIRM scope both pushed (fanout)"
    # since_hlc is sent (full pull); community_keys present when relay groups.
    assert "since_hlc" in posted["body"]
