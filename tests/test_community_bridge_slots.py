"""Multi-device COMMUNITIES — bridge slots for the BrainViewModal panel.

The community MECHANISM (brain.community_* — 8 daemon tools) was
wired-not-shipped: the GUI lives in `studio-lm.jsx`'s CommunitiesPanel,
backed by 8 `community_*` slots on `ArchHubBridge`. These tests:

  * Pin every slot + the two signals exist (JSX wiring breaks on rename).
  * Verify the OFF-THREAD contract:
      - READS (community_groups / community_members / community_owned_server)
        route through `_cached_async` — the slot body NEVER calls the daemon
        synchronously; it returns a cached/pending snapshot instantly and the
        real `_brain_tool` call runs only on the background pool.
      - WRITES (community_create / community_join_code / community_join /
        community_set_transport / community_leave) run on `_bg_pool` and
        deliver a request_id-stamped answer over `community_op_done`; a
        success also fires `community_changed`.
  * Verify arg→tool mapping + input validation (empty name / empty code /
    bad transport kind reject synchronously, never touching the daemon).

All HTTP I/O is mocked via `monkeypatch` on `BrainClient._call`, and the
background pool is patched to run inline — so these tests NEVER touch the
live brain daemon or mutate real community state.

Tests do NOT require: ArchHub running, the brain daemon running, QtWebEngine.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ─────────────────────── fixtures ────────────────────────────────────


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    """Bridge with no router/engine — community slots only touch
    `memory_gate.BrainClient`, mocked per-test."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    return _bridge_module.ArchHubBridge(
        manager=_StubManager(),
        auto_extract_memory=False,
    )


@pytest.fixture
def mock_brain_call(monkeypatch):
    """Replace `BrainClient._call` with a recorder. `set_response()` /
    `set_router()` drive the reply; `calls` captures every (tool, params)."""
    state = {"calls": [], "response": {"ok": True}, "router": None}

    def fake_call(self, tool, params, timeout=None):
        state["calls"].append({"tool": tool, "params": params,
                               "timeout": timeout})
        if state["router"] is not None:
            return state["router"](tool, params)
        resp = state["response"]
        if isinstance(resp, Exception):
            raise resp
        return resp

    import memory_gate
    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    state["set"] = lambda resp: state.__setitem__("response", resp)
    state["set_router"] = lambda fn: state.__setitem__("router", fn)
    return state


class _SyncPool:
    """Runs submitted work inline so signal-based writes are deterministic
    (no real thread, no waiting on community_op_done)."""

    def submit(self, fn, *a, **k):
        fn(*a, **k)
        return None


def _patch_sync_pool(bridge_inst, monkeypatch):
    monkeypatch.setattr(bridge_inst, "_bg_pool", lambda: _SyncPool())


# ─────────────────────── slot / signal presence ──────────────────────


def test_bridge_has_community_slots():
    """Every community_* slot the JSX panel calls must exist + be callable."""
    from bridge import ArchHubBridge
    required = [
        "community_groups", "community_members", "community_owned_server",
        "community_create", "community_join_code", "community_join",
        "community_set_transport", "community_leave",
    ]
    missing = [m for m in required if not hasattr(ArchHubBridge, m)]
    assert not missing, f"Bridge missing community slots: {missing}"
    for name in required:
        assert callable(getattr(ArchHubBridge, name))


def test_bridge_has_community_signals():
    """The panel re-pulls reads on `community_changed` and correlates writes
    over `community_op_done` (via bridgeAsyncSignal)."""
    from bridge import ArchHubBridge
    for sig in ("community_changed", "community_op_done"):
        assert hasattr(ArchHubBridge, sig), f"missing signal {sig}"


def test_community_slots_return_str_annotation():
    """Each slot returns a JSON `str` — the QWebChannel contract."""
    from bridge import ArchHubBridge
    for name in ("community_groups", "community_members",
                 "community_owned_server", "community_create",
                 "community_join_code", "community_join",
                 "community_set_transport", "community_leave"):
        ann = inspect.signature(getattr(ArchHubBridge, name)).return_annotation
        assert ann is str or ann == "str", (
            f"ArchHubBridge.{name} return annotation {ann!r}, expected str")


# ─────────────────────── READS · off-thread contract ─────────────────


def test_community_groups_returns_instant_pending_without_blocking(
    bridge_inst, mock_brain_call
):
    """READ: the slot returns the honest cached/pending snapshot INSTANTLY on
    the calling (Qt main) thread — the heavy `brain.community_groups` call is
    deferred to the `_cached_async` background pool, never run in the slot
    body. The first call must come back fast with `pending` regardless of how
    slow the daemon is."""
    # A slow daemon proves the slot doesn't block: if the body called it
    # synchronously this slot would take >1s; instead it returns at once.
    import time

    def slow_groups(tool, params):
        time.sleep(1.0)
        return {"ok": True, "current_community_id": None, "communities": []}
    mock_brain_call["set_router"](slow_groups)

    t0 = time.time()
    data = json.loads(bridge_inst.community_groups())
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"slot blocked {elapsed:.2f}s — not off-thread"
    assert data.get("pending") is True


def test_community_groups_lands_real_data_on_second_call(
    bridge_inst, mock_brain_call
):
    """The cached refresh runs the real `brain.community_groups` call on the
    background pool; once it lands, the next call serves the live data.
    Mirrors test_bridge_nonblocking's poll idiom — we poll the slot's RETURN
    value (the warm cache, written under the lock by the worker thread)
    rather than the cross-thread signal callback, which needs a Qt event loop
    to invoke a Python slot."""
    import time
    mock_brain_call["set"]({
        "ok": True,
        "current_community_id": "comm-x",
        "communities": [{"community_id": "comm-x", "name": "Fleet",
                         "role": "owner",
                         "transport": {"kind": "cloud_relay",
                                       "base_url": "", "note": ""}}],
    })
    # First call kicks the background refresh + returns pending instantly.
    assert json.loads(bridge_inst.community_groups()).get("pending") is True
    # Poll until the off-thread refresh warms the cache.
    deadline = time.time() + 5.0
    data = None
    while time.time() < deadline:
        data = json.loads(bridge_inst.community_groups())
        if not data.get("pending"):
            break
        time.sleep(0.03)
    assert data and data.get("ok") is True, f"never warmed: {data}"
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.community_groups"
    assert data.get("current_community_id") == "comm-x"
    assert data["communities"][0]["role"] == "owner"


def _await_cached(bridge_inst, slot, *args, timeout=5.0):
    """Drive a `_cached_async` READ slot to its warm value: kick the
    background refresh, then POLL the slot's return value until it stops
    reporting `pending` (the worker writes the cache under the lock, so the
    warm value is observable on the next call — no Qt event loop needed,
    unlike the cross-thread `community_changed` signal callback). Mirrors
    test_bridge_nonblocking's poll idiom."""
    import time
    getattr(bridge_inst, slot)(*args)  # kick the refresh
    deadline = time.time() + timeout
    data = json.loads(getattr(bridge_inst, slot)(*args))
    while data.get("pending") and time.time() < deadline:
        time.sleep(0.03)
        data = json.loads(getattr(bridge_inst, slot)(*args))
    return data


def test_community_members_passes_community_id(bridge_inst, mock_brain_call):
    """READ: an explicit community_id is forwarded to brain.community_members."""
    mock_brain_call["set"]({"ok": True, "community_id": "comm-x",
                            "members": [{"member_id": "alice", "role": "owner"}]})
    data = _await_cached(bridge_inst, "community_members", "comm-x")
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.community_members"
    assert rec["params"].get("community_id") == "comm-x"
    assert data["members"][0]["member_id"] == "alice"


def test_community_owned_server_reports_docker_state(
    bridge_inst, mock_brain_call
):
    """READ: owned-server readiness flows through (docker_available + code
    drive the panel's 'install Docker Desktop' hint)."""
    mock_brain_call["set"]({"ok": True, "reachable": False,
                            "docker_available": False, "can_start": False,
                            "code": "docker_missing",
                            "message": "Install Docker Desktop first."})
    data = _await_cached(bridge_inst, "community_owned_server")
    assert mock_brain_call["calls"][0]["tool"] == "brain.community_owned_server"
    assert data["docker_available"] is False
    assert data["code"] == "docker_missing"


def test_reads_degrade_to_honest_empty_when_daemon_down(
    bridge_inst, monkeypatch
):
    """Daemon unreachable → reads return an honest empty payload (never a
    fabricated community / member / server), and never raise."""
    import memory_gate

    def boom(self, tool, params, timeout=None):
        raise ConnectionRefusedError("daemon down")
    monkeypatch.setattr(memory_gate.BrainClient, "_call", boom)

    g = _await_cached(bridge_inst, "community_groups")
    assert g.get("communities") == []
    m = _await_cached(bridge_inst, "community_members")
    assert m.get("members") == []
    s = _await_cached(bridge_inst, "community_owned_server")
    assert s.get("docker_available") is False


# ─────────────────────── WRITES · off-thread + signal ────────────────


def test_community_create_returns_async_ack_and_proxies(
    bridge_inst, mock_brain_call, monkeypatch
):
    """WRITE: returns {async, request_id} instantly; the worker calls
    brain.community_create with the name and emits community_op_done +
    community_changed with the stamped request_id."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True,
                            "community": {"community_id": "comm-new",
                                          "name": "Fleet", "role": "owner"},
                            "is_owner": True})
    op_done, changed = [], []
    bridge_inst.community_op_done.connect(op_done.append)
    bridge_inst.community_changed.connect(lambda: changed.append(1))

    raw = bridge_inst.community_create("Fleet", "")
    started = json.loads(raw)
    assert started.get("async") is True
    assert started.get("request_id")

    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.community_create"
    assert rec["params"]["name"] == "Fleet"
    assert len(op_done) == 1
    payload = json.loads(op_done[0])
    assert payload.get("ok") is True
    assert payload.get("request_id") == started.get("request_id")
    assert changed, "community_changed must fire on a successful write"


def test_community_create_does_not_set_transport(
    bridge_inst, mock_brain_call, monkeypatch
):
    """Transport is the founder's explicit later CHOICE — create must NOT
    silently pick one (no transport_kind in the create call)."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "community": {}, "is_owner": True})
    bridge_inst.community_create("Fleet", "")
    rec = mock_brain_call["calls"][0]
    assert "transport_kind" not in rec["params"]


def test_community_create_rejects_empty_name_without_daemon(
    bridge_inst, mock_brain_call, monkeypatch
):
    """Empty name → synchronous {ok:false} reject, NO daemon call, NO pool."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    data = json.loads(bridge_inst.community_create("   ", ""))
    assert data.get("ok") is False
    assert "name" in (data.get("error") or "")
    assert mock_brain_call["calls"] == []


def test_community_join_code_passes_role_and_ttl(
    bridge_inst, mock_brain_call, monkeypatch
):
    """WRITE (owner-only): forwards role + ttl_hours; the {url} comes back on
    community_op_done for the panel's invite + copy button."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "token": "tok",
                            "url": "archhub://community/join?code=tok",
                            "role": "member", "ttl_hours": 168})
    op_done = []
    bridge_inst.community_op_done.connect(op_done.append)
    bridge_inst.community_join_code("member", 168, "")
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.community_join_code"
    assert rec["params"]["role"] == "member"
    assert rec["params"]["ttl_hours"] == 168
    payload = json.loads(op_done[0])
    assert payload["url"].startswith("archhub://community/join?code=")


def test_community_join_code_owner_only_error_rides_back(
    bridge_inst, mock_brain_call, monkeypatch
):
    """A member device gets the daemon's honest owner-only error over
    community_op_done — never a fabricated invite."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": False, "error": "not the community owner"})
    op_done = []
    bridge_inst.community_op_done.connect(op_done.append)
    bridge_inst.community_join_code("member", 168, "")
    payload = json.loads(op_done[0])
    assert payload.get("ok") is False
    assert "owner" in payload.get("error", "")


def test_community_join_passes_code(bridge_inst, mock_brain_call, monkeypatch):
    """WRITE: the second-device join forwards the pasted code/URL."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True,
                            "community": {"community_id": "comm-x"},
                            "is_owner": False})
    bridge_inst.community_join("archhub://community/join?code=abc", "")
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.community_join"
    assert rec["params"]["code"] == "archhub://community/join?code=abc"


def test_community_join_rejects_empty_code_without_daemon(
    bridge_inst, mock_brain_call, monkeypatch
):
    _patch_sync_pool(bridge_inst, monkeypatch)
    data = json.loads(bridge_inst.community_join("  ", ""))
    assert data.get("ok") is False
    assert mock_brain_call["calls"] == []


@pytest.mark.parametrize("kind,url", [
    ("cloud_relay", ""),
    ("disk", r"C:\Users\me\Dropbox\fleet"),
    ("speckle", "http://localhost:3000"),
])
def test_community_set_transport_forwards_each_choice(
    bridge_inst, mock_brain_call, monkeypatch, kind, url
):
    """WRITE: each of the 3 founder transport choices maps to
    brain.community_set_transport with kind + base_url."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True, "community": {"transport": {
        "kind": kind, "base_url": url, "note": ""}}})
    bridge_inst.community_set_transport(kind, url, "")
    rec = mock_brain_call["calls"][0]
    assert rec["tool"] == "brain.community_set_transport"
    assert rec["params"]["transport_kind"] == kind
    assert rec["params"]["transport_base_url"] == url


def test_community_set_transport_rejects_bad_kind_without_daemon(
    bridge_inst, mock_brain_call, monkeypatch
):
    """An unknown transport kind rejects synchronously — no daemon call."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    data = json.loads(bridge_inst.community_set_transport("ftp", "", ""))
    assert data.get("ok") is False
    assert mock_brain_call["calls"] == []


def test_community_leave_proxies_and_signals(
    bridge_inst, mock_brain_call, monkeypatch
):
    """WRITE: leave proxies to brain.community_leave and fires the re-pull."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": True})
    changed = []
    bridge_inst.community_changed.connect(lambda: changed.append(1))
    op_done = []
    bridge_inst.community_op_done.connect(op_done.append)
    bridge_inst.community_leave("")
    assert mock_brain_call["calls"][0]["tool"] == "brain.community_leave"
    assert json.loads(op_done[0]).get("ok") is True
    assert changed


def test_write_failure_does_not_fire_changed(
    bridge_inst, mock_brain_call, monkeypatch
):
    """A failed write reports {ok:false} on community_op_done but must NOT
    fire community_changed (nothing changed → no needless re-pull)."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    mock_brain_call["set"]({"ok": False, "error": "no community on device"})
    changed = []
    bridge_inst.community_changed.connect(lambda: changed.append(1))
    op_done = []
    bridge_inst.community_op_done.connect(op_done.append)
    bridge_inst.community_set_transport("cloud_relay", "", "")
    assert json.loads(op_done[0]).get("ok") is False
    assert changed == []


def test_write_degrades_when_daemon_down(bridge_inst, monkeypatch):
    """Daemon unreachable mid-write → community_op_done carries {ok:false,
    error} (never raises); the async ack still returns so the JSX doesn't
    hang."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import memory_gate

    def boom(self, tool, params, timeout=None):
        raise ConnectionRefusedError("daemon down")
    monkeypatch.setattr(memory_gate.BrainClient, "_call", boom)

    op_done = []
    bridge_inst.community_op_done.connect(op_done.append)
    raw = bridge_inst.community_create("Fleet", "")
    assert json.loads(raw).get("async") is True
    payload = json.loads(op_done[0])
    assert payload.get("ok") is False
    assert "error" in payload
    assert payload.get("request_id")
