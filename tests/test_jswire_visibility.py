"""JS-WIRE lane — make the live backends VISIBLE in the running UI.

Founder 2026-06-18: every backend is REAL + live (brain daemon 668 facts /
64 skills / 6 workers; router routes + falls back; release_updater downloads
the signed release; signed-in cloud account with a plan + quota). The UI just
didn't SHOW it. This lane wires five surfaces + a company-API proxy. These
tests pin each WIRE so it can't silently regress.

RED→GREEN proof (per the lane's ANTI-LIE / DEFINITION-OF-SHIPPED bar): each
production change lives in app/bridge.py + app/web_ui/studio-lm.jsx. Stash the
working tree (`git stash`) → these tests go RED (the slot/signal/JSX wire is
absent on origin/main); restore (`git stash pop`) → GREEN. The stash run is
recorded in the PR body.

No ArchHub, no brain daemon, no QtWebEngine, no network — all I/O is mocked.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

JSX = (Path(__file__).resolve().parent.parent
       / "app" / "web_ui" / "studio-lm.jsx")
COMPILED = (Path(__file__).resolve().parent.parent
            / "app" / "web_ui" / "studio-lm.compiled.js")


# ─────────────────────── fixtures ────────────────────────────────────


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


class _SyncPool:
    """Run submitted work INLINE so the bridge's bg-pool slots emit their
    result signals on the calling thread — a DirectConnection then delivers
    them synchronously, no Qt event loop needed. Same helper idiom as
    tests/test_cloud_signin_wiring.py::_SyncPool."""

    def submit(self, fn, *a, **k):
        fn(*a, **k)


def _sync_pool(bridge_inst, monkeypatch):
    monkeypatch.setattr(bridge_inst, "_bg_pool", lambda: _SyncPool())


@pytest.fixture(scope="module")
def qapp():
    """A process-wide QApplication so QObject signals are deliverable. Skipped
    cleanly if PyQt6 isn't importable in this environment."""
    pytest.importorskip("PyQt6.QtCore")
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        from PyQt6.QtCore import QCoreApplication as QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv or ["test"])


def _direct(signal, fn):
    """Connect a bridge signal with a DirectConnection so a worker-thread
    emit() runs the Python slot synchronously on the emitting thread (no event
    loop). Falls back to a plain connect if the enum isn't available."""
    try:
        from PyQt6.QtCore import Qt
        signal.connect(fn, Qt.ConnectionType.DirectConnection)
    except Exception:
        signal.connect(fn)


class _StubRouter:
    """Minimal LLMRouter stand-in. complete() records the kwargs it was
    handed (so we can assert on_status was threaded through) + fires a
    status callback, and returns a response carrying a routing_note."""

    def __init__(self):
        self.complete_kwargs = None

    def complete(self, **kwargs):
        self.complete_kwargs = kwargs
        on_status = kwargs.get("on_status")
        if callable(on_status):
            on_status("anthropic quota — switching provider…")

        class _Resp:
            text = "hello from the router"
            model = "claude-sonnet-4"
            routing_note = "claude-sonnet-4 via anthropic"
            tool_calls_log = None
        return _Resp()

    # send_chat_history reads these on the bridge.router; keep them inert.
    def get_token_usage(self):
        return {"model": "claude-sonnet-4", "completions": 1}


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    return _bridge_module.ArchHubBridge(
        manager=_StubManager(),
        auto_extract_memory=False,
    )


@pytest.fixture
def bridge_with_router(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    return _bridge_module.ArchHubBridge(
        router=_StubRouter(),
        manager=_StubManager(),
        auto_extract_memory=False,
    )


def _parse(raw):
    assert isinstance(raw, str), f"slot must return a JSON string, got {type(raw)}"
    return json.loads(raw)


# ═══════════════════════ S1 — BRAIN cold-start ═══════════════════════


def test_s1_get_brain_stats_cold_falls_back_to_health_counts(
        bridge_inst, monkeypatch):
    """No turn yet (_LAST_BRAIN_STATS empty) → get_brain_stats must NOT
    return idle/empty. It falls back to the cached brain.health snapshot and
    returns the daemon's REAL skill/fact counts with cold:true + available:true.
    THIS is the wire that turns 'brain · idle' into 'brain · 64s · 668f · ready'
    on a fresh open."""
    import memory_gate
    monkeypatch.setattr(memory_gate, "_LAST_BRAIN_STATS", {}, raising=False)

    # Mock the daemon health round-trip the cold path reuses.
    def fake_brain_tool(self, tool, args, timeout=4.0):
        assert tool == "brain.health"
        return {"ok": True, "skills": 64, "facts": 668}
    import bridge as _bridge_module
    monkeypatch.setattr(_bridge_module.ArchHubBridge, "_brain_tool",
                        fake_brain_tool, raising=True)

    out = _parse(bridge_inst.get_brain_stats())
    # The background-pool refresh may not have landed on the FIRST call (cached
    # async returns the empty placeholder, then re-pulls). Poll briefly.
    import time
    for _ in range(50):
        if out.get("available"):
            break
        time.sleep(0.02)
        out = _parse(bridge_inst.get_brain_stats())

    assert out.get("cold") is True, "cold snapshot must be flagged cold:true"
    assert out.get("available") is True, "reachable daemon → available:true"
    assert out.get("skills_n") == 64, "real daemon skill count, not 0"
    assert out.get("facts_n") == 668, "real daemon fact count, not 0"
    assert out.get("ts"), "cold snapshot carries a ts so the chip leaves 'idle'"


def test_s1_warm_stats_still_win_over_cold(bridge_inst, monkeypatch):
    """A real post-turn hit (has ts, no cold flag) is returned verbatim —
    the cold fallback only fires when there's no turn yet."""
    import memory_gate
    warm = {"ts": 123.0, "skills_n": 3, "facts_n": 9, "retrieval_ms": 42,
            "available": True}
    monkeypatch.setattr(memory_gate, "_LAST_BRAIN_STATS", warm, raising=False)
    out = _parse(bridge_inst.get_brain_stats())
    assert out.get("ts") == 123.0
    assert not out.get("cold"), "a warm hit must NOT be flagged cold"
    assert out.get("retrieval_ms") == 42


# ═══════════════════════ S2 — ROUTER status ═══════════════════════════


def test_s2_chat_status_signal_exists():
    """The chat_status signal must exist near chat_chunk so JSX can subscribe."""
    import bridge as _bridge_module
    assert hasattr(_bridge_module.ArchHubBridge, "chat_status"), \
        "chat_status pyqtSignal missing — JSX route-meta line has nothing to wire"


def test_s2_send_chat_history_threads_on_status_and_emits_answered_by(
        bridge_with_router, qapp):
    """send_chat_history must pass on_status into router.complete AND emit a
    final 'answered by <routing_note>' on chat_status. Both were discarded
    before — the routing was invisible."""
    emitted = []
    # send_chat_history runs the router on a raw daemon thread → DirectConnection
    # so the slot fires synchronously on that thread (no event loop to pump).
    _direct(bridge_with_router.chat_status,
            lambda sid, txt: emitted.append((sid, txt)))

    bridge_with_router.send_chat_history("sess-1", "hi", "[]")
    # send_chat_history runs the router on a daemon thread; wait until the FINAL
    # 'answered by' status lands (it's emitted after complete() returns, so we
    # must not break on the first 'switching provider' note — a race).
    import time
    router = bridge_with_router.router
    for _ in range(150):
        if router.complete_kwargs is not None and \
                any(t.startswith("answered by") for (_s, t) in emitted):
            break
        time.sleep(0.02)

    assert router.complete_kwargs is not None, "router.complete was never called"
    assert "on_status" in router.complete_kwargs, \
        "on_status was NOT threaded into router.complete — fallback notes lost"
    assert callable(router.complete_kwargs["on_status"])

    texts = [t for (_s, t) in emitted]
    assert any("switching provider" in t for t in texts), \
        "router on_status fallback note was not emitted on chat_status"
    assert any(t.startswith("answered by") and "anthropic" in t for t in texts), \
        "final 'answered by <routing_note>' was not emitted on chat_status"


# ═══════════════════════ S3 — UPDATES (release) ═══════════════════════


def test_s3_apply_update_release_branch_runs_signed_installer(monkeypatch, tmp_path):
    """On an installer build (no git, source root None) the apply path must drive
    the signed-release flow (download_asset → run_installer) so the in-app
    Relaunch button installs the REAL release — not fall through to a blind
    updater.restart() that would relaunch the OLD version. (The visible gap S3
    closes is the banner lighting up for kind:'release'; this pins the apply
    path stays the tested signed-release flow.)"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import bridge as _bridge_module
    inst = _bridge_module.ArchHubBridge(manager=_StubManager(),
                                        auto_extract_memory=False)

    calls = {"download": 0, "install": 0, "restart": 0}

    import dev_source_sync as dss
    monkeypatch.setattr(dss, "is_git_checkout", lambda root: False)
    monkeypatch.setattr(dss, "find_source_root", lambda root: None)

    import release_updater as ru
    fake_path = tmp_path / "ArchHub-Setup.exe"

    class _Info:
        tag = "v1.5.0"
        error = ""
    monkeypatch.setattr(ru, "has_update_available", lambda: (True, _Info(), "1.4.0"))
    monkeypatch.setattr(ru, "download_asset",
                        lambda info: (calls.__setitem__("download", calls["download"] + 1), fake_path)[1])
    monkeypatch.setattr(ru, "run_installer",
                        lambda path, silent=True, relaunch=True: calls.__setitem__("install", calls["install"] + 1))

    import updater
    monkeypatch.setattr(updater, "restart",
                        lambda: calls.__setitem__("restart", calls["restart"] + 1))

    inst._apply_update_work()
    assert calls["download"] == 1, "release branch did not download the signed asset"
    assert calls["install"] == 1, "release branch did not run the signed installer"
    # MUST NOT blind-restart the OLD version — run_installer handles the relaunch.
    assert calls["restart"] == 0, "release branch must NOT fall through to updater.restart()"


# ═══════════════════════ S4 — ACCOUNT enrich ══════════════════════════


def test_s4_cloud_status_includes_plan_and_remaining(bridge_inst, monkeypatch):
    """cloud_status must fold plan + remaining from cloud_usage.snapshot() so
    the AccountChip can render 'cloud · {plan} · {remaining} left'."""
    import cloud_client
    import cloud_usage
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: True)
    monkeypatch.setattr(cloud_client, "base_url", lambda: "https://archhub-cloud.fly.dev")
    monkeypatch.setattr(cloud_usage, "snapshot",
                        lambda: {"plan": "pro", "remaining_messages": 472})

    out = _parse(bridge_inst.cloud_status())
    assert out.get("signed_in") is True
    assert out.get("plan") == "pro", "plan not surfaced from cloud_usage.snapshot"
    assert out.get("remaining") == 472, "remaining not surfaced from cloud_usage.snapshot"


def test_s4_cloud_status_cold_meter_kicks_refresh(bridge_inst, monkeypatch):
    """Signed in but the usage meter is cold (None) → cloud_status must kick
    cloud_usage.refresh_async (off-thread) so the chip re-pulls when it lands.
    plan/remaining stay empty/None (never fabricated) on this call."""
    import cloud_client
    import cloud_usage
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: True)
    monkeypatch.setattr(cloud_client, "base_url", lambda: "https://x")
    monkeypatch.setattr(cloud_usage, "snapshot", lambda: None)
    kicked = {"n": 0}
    monkeypatch.setattr(cloud_usage, "refresh_async",
                        lambda cb=None: kicked.__setitem__("n", kicked["n"] + 1))

    out = _parse(bridge_inst.cloud_status())
    assert out.get("signed_in") is True
    assert out.get("plan") == ""
    assert out.get("remaining") is None
    assert kicked["n"] == 1, "cold meter did not kick refresh_async"


# ═══════════════════════ S5 — SESSIONS sync ═══════════════════════════


def test_s5_sync_slots_exist():
    import bridge as _bridge_module
    for slot in ("cloud_sync_sessions", "cloud_sync_status"):
        assert hasattr(_bridge_module.ArchHubBridge, slot), f"{slot} slot missing"


def test_s5_sync_status_defensive_when_backend_absent(bridge_inst, monkeypatch):
    """cloud_sync.status() raising / missing must degrade to a typed empty
    {available:false}, never crash the bridge."""
    import cloud_sync

    def boom():
        raise RuntimeError("git not installed")
    monkeypatch.setattr(cloud_sync, "status", boom)
    out = _parse(bridge_inst.cloud_sync_status())
    assert out.get("available") is False
    assert "reason" in out


def test_s5_sync_sessions_pending_when_fn_absent(bridge_inst, monkeypatch):
    """cloud_sync.sync_sessions is built by the SESSIONS-IMPL lane. When it's
    absent THIS lane must still report a clean {available:false, reason:'pending'}
    via the sessions_synced signal — proving lane independence."""
    import cloud_sync
    if hasattr(cloud_sync, "sync_sessions"):
        monkeypatch.delattr(cloud_sync, "sync_sessions", raising=False)
    _sync_pool(bridge_inst, monkeypatch)   # bg pool runs inline → signal delivers
    seen = []
    bridge_inst.sessions_synced.connect(lambda j: seen.append(json.loads(j)))
    out = _parse(bridge_inst.cloud_sync_sessions())
    assert out.get("async") is True
    assert seen, "sessions_synced never fired"
    assert seen[0].get("available") is False
    assert seen[0].get("reason") == "pending"


# ═══════════════════════ S6 — COMPANY slots ═══════════════════════════


def test_s6_company_slots_exist():
    import bridge as _bridge_module
    for slot in ("companies_list", "company_create", "company_detail",
                 "company_invite", "company_accept_invite",
                 "company_remove_member", "company_set_role"):
        assert hasattr(_bridge_module.ArchHubBridge, slot), f"{slot} slot missing"


def test_s6_company_list_proxies_request_and_returns_data(bridge_inst, monkeypatch):
    """companies_list must proxy GET /v1/companies/mine via cloud_client and
    deliver the JSON on company_op_done."""
    import cloud_client
    captured = {}

    def fake_request(method, path, body=None):
        captured["method"] = method
        captured["path"] = path
        return {"status": "ok", "json": {"companies": [{"id": "c1"}]}}
    monkeypatch.setattr(cloud_client, "_request", fake_request)
    _sync_pool(bridge_inst, monkeypatch)   # bg pool runs inline → signal delivers

    seen = []
    bridge_inst.company_op_done.connect(lambda j: seen.append(json.loads(j)))
    out = _parse(bridge_inst.companies_list())
    assert out.get("async") is True
    assert captured.get("method") == "GET"
    assert captured.get("path") == "/v1/companies/mine"
    assert seen and seen[0].get("ok") is True
    assert seen[0]["data"]["companies"][0]["id"] == "c1"


def test_s6_company_401_maps_to_signed_out(bridge_inst, monkeypatch):
    """A 401 (or not_signed_in) from cloud_client must surface as
    error:'signed_out' so the TEAM-UI routes to sign-in, not a raw error."""
    import cloud_client

    def fake_request(method, path, body=None):
        return {"status": "error", "error": "http_401"}
    monkeypatch.setattr(cloud_client, "_request", fake_request)
    _sync_pool(bridge_inst, monkeypatch)   # bg pool runs inline → signal delivers

    seen = []
    bridge_inst.company_op_done.connect(lambda j: seen.append(json.loads(j)))
    bridge_inst.company_create("Acme")
    assert seen and seen[0].get("ok") is False
    assert seen[0].get("error") == "signed_out", \
        "401 must map to signed_out, got " + str(seen[0])


# ═══════════════════ JSX structural wiring (the visible end) ═══════════


def test_jsx_surfaces_present():
    """The JSX must carry the user-visible wiring for all five surfaces —
    DEFINITION-OF-SHIPPED: a visible affordance, not just a backend slot."""
    src = JSX.read_text(encoding="utf-8")
    # S1 — cold-ready label path in BrainChip.
    assert "coldReady" in src, "BrainChip cold-ready state missing"
    assert "· ready`" in src, "BrainChip 'ready' label missing"
    # S2 — chat_status subscription + the route-meta line under the bubble.
    assert "wire('chat_status'" in src, "chat_status not subscribed in JSX"
    assert 'data-testid="route-meta"' in src, "router meta line not rendered"
    # S2 — ModelStrip real router state (no more hardcoded green latency dot).
    assert "get_provider_stats" in src, "ModelStrip does not read provider stats"
    assert "data-router-blocked" in src, "ModelStrip blocked-provider state missing"
    # S4 — AccountChip plan/remaining label.
    assert "data-account-plan" in src, "AccountChip plan attribute missing"
    assert "left`" in src or "left'" in src, "AccountChip 'left' label missing"
    # S5 — Sync sessions button.
    assert 'data-testid="sync-sessions-btn"' in src, "Sync sessions button missing"
    assert "cloud_sync_sessions" in src, "Sync button does not call the slot"
    assert "<SyncSessionsButton/>" in src, "Sync button not mounted in Home header"


def test_jsx_no_pictographic_emoji_in_new_copy():
    """Mandate: NO pictographic emoji in user-facing copy. The new wires use
    only typographic dingbats (⌬ ⇉ ⟳ · ▾) already in the design system. Scope
    this to the NEW label/badge strings this lane added (a pre-existing 📎 in
    the composer attachment button, line ~6109, is out of this lane's scope —
    asserting on the whole file would flag unrelated legacy copy)."""
    src = JSX.read_text(encoding="utf-8")
    # The exact new user-facing strings introduced by this lane.
    new_strings = [
        "⌬ brain · ${skillsN}s · ${factsN}f · ready",
        "⌬ brain · idle",
        "Personal-brain live: ${skillsN} skills + ${factsN} facts loaded",
        "router → ${routedLeaf}",
        "${stateText} · ${blocked} blocked",
        "${remaining} left",
        "sync sessions",
        "sync pending",
    ]
    # Pictographic plane only — astral emoji + the dingbat/symbol blocks that
    # carry an emoji presentation. (We do NOT flag the BMP dingbats the design
    # system curates: ⌬ ⇉ ⟳ ● ▾ etc.)
    pictographic = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000026FF]")
    for s in new_strings:
        assert s in src, f"expected new label string missing: {s!r}"
        bad = pictographic.findall(s)
        assert not bad, f"pictographic emoji {bad!r} in new copy {s!r}"


def test_compiled_sha_parity():
    """The compiled artifact must embed the live .jsx sha — boot loads the
    precompiled bundle only when they match. A stale compiled.js means the
    user runs OLD UI even though the .jsx changed."""
    import hashlib
    src_sha = hashlib.sha256(JSX.read_bytes()).hexdigest()
    head = COMPILED.read_text(encoding="utf-8", errors="replace")[:4096]
    m = re.search(r"ARCHHUB_JSX_SRC_SHA256:\s*([0-9a-f]{64})", head)
    assert m, "compiled.js missing the embedded source-sha header"
    assert m.group(1) == src_sha, (
        "compiled.js is STALE vs studio-lm.jsx — run tools/build_jsx.py")
