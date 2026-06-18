"""BRIDGE-FINALIZE — two pillar fixes in bridge.py + llm_router.py.

Founder bugs:
  (1) 'router not working' — the auto-fallback chain ROUTED correctly but
      LEAKED: a provider that streamed a few tokens then hit an
      auth/quota/refusal/fabrication wall left its half-message glued in
      front of the WINNING provider's real answer. The fix buffers each
      ATTEMPT's streamed chunks and only commits the WINNER's; the router
      fires `on_attempt_reset` when it abandons an attempt so the loser's
      buffer is dropped (+ a `chat_chunk_retract` signal for live
      consumers). claude_cli HTTP 401 is also treated as an AUTH failure
      (route onward), not a generic fatal error.
  (2) 'brain not working' — in-app recall (`memory_query`) searched the
      STAGING graph.sqlite, not the LIVE brain daemon that holds the
      founder's memory. The fix points memory_query._work() at the brain
      daemon (`brain.browse`) first, mapping its cards into the recall
      envelope, with a graceful fall back to the local graph when the
      daemon is cold (never an error).

RED on origin/main (no `on_attempt_reset` param; raw per-chunk emit; no
`chat_chunk_retract` signal; no `_memory_query_brain`; no
`_claude_cli_is_auth`) → GREEN on fix/fin2-bridge.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402
from tool_engine import ToolEngine  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

# The runner emits its signals from a background thread. With no Qt event
# loop spinning in the test process, a default (auto/queued) cross-thread
# connection would never deliver. DirectConnection runs the receiver
# synchronously on the emitting thread — deterministic + loop-free, which
# is exactly what a unit test wants.
_DIRECT = Qt.ConnectionType.DirectConnection


class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    engine = ToolEngine(manager=_StubManager())
    return _bridge_module.ArchHubBridge(tools=engine, auto_extract_memory=False)


def _drain(call, pred, timeout=6.0):
    """Re-call an async (_cached_async) slot until `pred(parsed)` holds —
    mirrors how the JSX re-pulls on the change signal."""
    deadline = time.time() + timeout
    out = json.loads(call())
    while time.time() < deadline and not pred(out):
        time.sleep(0.02)
        out = json.loads(call())
    return out


# ════════════════════════════════════════════════════════════════════════
# PILLAR 1 — ROUTER OUTPUT HYGIENE
# ════════════════════════════════════════════════════════════════════════

# ── 1a. The signal + the param contract exist (the seam the fix adds) ────

def test_chat_chunk_retract_signal_exists(bridge_inst):
    """The bridge declares a `chat_chunk_retract` signal so a live consumer
    can clear the loser's optimistic paint. RED on main (no such signal)."""
    assert hasattr(bridge_inst, "chat_chunk_retract")
    # It must be a real Qt signal (connectable), not a stray attribute.
    assert hasattr(bridge_inst.chat_chunk_retract, "connect")


def test_complete_accepts_on_attempt_reset():
    """llm_router.complete() accepts an `on_attempt_reset` callback — the
    hook the runner uses to drop a failed attempt's buffered text. RED on
    main (TypeError: unexpected keyword argument)."""
    import inspect
    from llm_router import LLMRouter
    sig = inspect.signature(LLMRouter.complete)
    assert "on_attempt_reset" in sig.parameters


# ── 1b. THE founder bug: partial stream then provider dies → only the
#        winner's text reaches the bubble; a retract is emitted first. ────

class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.model = "winner-model"
        self.tool_invocations = []
        self.routing_note = ""
        self.tool_calls_log = []


def _run_runner_with_fake_router(bridge_inst, router_complete):
    """Install a fake `router.complete`, fire send_chat_history, and block
    until the turn's chat_done lands — capturing every chat_chunk +
    chat_chunk_retract the runner emits (in order)."""
    chunks: list[tuple[str, str]] = []
    retracts: list[tuple[str, str, int]] = []
    done = {"v": False}

    bridge_inst.chat_chunk.connect(
        lambda sid, t: chunks.append((sid, t)), _DIRECT)
    bridge_inst.chat_chunk_retract.connect(
        lambda sid, prov, n: retracts.append((sid, prov, n)), _DIRECT)
    bridge_inst.chat_done.connect(
        lambda sid: done.__setitem__("v", True), _DIRECT)

    class _FakeRouter:
        complete = staticmethod(router_complete)
    bridge_inst.router = _FakeRouter()
    # Persisting the ai.plan turn touches disk / the daemon — irrelevant to
    # output hygiene and slow on a cold daemon. Stub it out.
    bridge_inst._persist_chat_plan = lambda **kw: None

    bridge_inst.send_chat_history("conv-1", "hello", "[]")
    deadline = time.time() + 6.0
    while time.time() < deadline and not done["v"]:
        time.sleep(0.02)
    assert done["v"], "runner never emitted chat_done"
    return chunks, retracts


def test_failed_attempt_text_is_retracted_then_winner_commits(bridge_inst):
    """A provider streams a partial reply, then the chain abandons it
    (on_attempt_reset) and a SECOND provider streams the real answer.

    Assert: (1) a retract is emitted BEFORE any winner text is committed,
    and (2) the final committed bubble text is ONLY the winner's — the
    loser's half-message never reaches the bubble.
    """
    LOSER = "I cannot read your ema"   # truncated mid-word — the leak
    WINNER = "Here are your 3 open Revit files: A, B, C."

    def fake_complete(*, history, model, on_chunk, on_reasoning,
                      on_tool_invocation, on_attempt_reset=None, **kw):
        # Attempt #1 (provider A): stream a partial, then the chain gives up.
        on_chunk(LOSER)
        if on_attempt_reset:
            on_attempt_reset("claude_cli")
        # Attempt #2 (provider B = winner): stream the real answer in pieces.
        for piece in (WINNER[:18], WINNER[18:]):
            on_chunk(piece)
        return _FakeResp(WINNER)

    chunks, retracts = _run_runner_with_fake_router(bridge_inst, fake_complete)

    committed = "".join(t for (_sid, t) in chunks)
    # The whole leak class: the loser's text must be ABSENT from the bubble.
    assert LOSER not in committed
    assert committed == WINNER
    # A retract fired, naming the dropped provider + a positive char count.
    assert retracts, "expected a chat_chunk_retract before the winner"
    sid, prov, dropped = retracts[0]
    assert sid == "conv-1"
    assert prov == "claude_cli"
    assert dropped == len(LOSER)
    # And it fired BEFORE the winner's first committed chunk (ordering: with
    # buffer-and-commit the winner is committed in ONE flush AFTER the reset).
    assert chunks[0][1] == WINNER  # single committed flush, winner-only


def test_clean_single_provider_stream_is_unaffected(bridge_inst):
    """No fallback → the user still sees the full reply (buffer-and-commit
    must not swallow a normal turn)."""
    MSG = "All good — nothing to switch."

    def fake_complete(*, history, model, on_chunk, on_reasoning,
                      on_tool_invocation, on_attempt_reset=None, **kw):
        for piece in (MSG[:10], MSG[10:]):
            on_chunk(piece)
        return _FakeResp(MSG)

    chunks, retracts = _run_runner_with_fake_router(bridge_inst, fake_complete)
    assert "".join(t for (_sid, t) in chunks) == MSG
    assert retracts == []  # nothing abandoned → no retract


def test_all_providers_exhausted_emits_no_leaked_text(bridge_inst):
    """When EVERY attempt fails (complete raises), the last attempt's
    half-streamed buffer must NOT be committed — the user gets an error,
    never a dangling partial."""
    LEAK = "partial that should vanish"

    def fake_complete(*, history, model, on_chunk, on_reasoning,
                      on_tool_invocation, on_attempt_reset=None, **kw):
        on_chunk(LEAK)
        raise RuntimeError("All configured LLM providers exhausted")

    chunks, retracts = _run_runner_with_fake_router(bridge_inst, fake_complete)
    committed = "".join(t for (_sid, t) in chunks)
    assert LEAK not in committed
    assert committed == ""  # nothing committed on a total failure


# ── 1c. The router itself fires on_attempt_reset on a real fail→win loop ─

def _mk_router():
    from llm_router import LLMRouter
    eng = ToolEngine(manager=_StubManager())
    return LLMRouter(tools=eng)


def test_router_fires_on_attempt_reset_when_provider_401s(monkeypatch):
    """At the router level: provider A raises a 401 mid-turn, provider B
    succeeds. complete() must FIRE on_attempt_reset('A') and RETURN B's
    response — never raise the 401 as fatal."""
    router = _mk_router()
    seq = iter([("anthropic", "sonnet", "n1"), ("google", "flash", "n2")])
    monkeypatch.setattr(router, "_route", lambda h, m: next(seq))
    monkeypatch.setattr(router, "_get_client", lambda p: object())
    monkeypatch.setattr(router, "configured_providers", lambda: ["anthropic", "google"])

    def fake_once(*, provider, on_chunk, **kw):
        if provider == "anthropic":
            on_chunk("half answer from A")
            raise RuntimeError("Error code: 401 - {'type':'authentication_error'}")
        on_chunk("real answer from B")
        return _FakeResp("real answer from B")
    monkeypatch.setattr(router, "_complete_once", fake_once)

    reset_calls: list[str] = []
    streamed: list[str] = []
    resp = router.complete(
        history=[{"role": "user", "content": "hi"}],
        model="auto",
        on_chunk=lambda p: streamed.append(p),
        on_attempt_reset=lambda prov: reset_calls.append(prov),
    )
    assert resp.text == "real answer from B"
    assert reset_calls == ["anthropic"]   # the loser was announced
    # The router streams BOTH (it doesn't buffer — the bridge does); the
    # point of the router test is that the RESET signal fired so the bridge
    # CAN drop A. (The bridge-level tests above prove the drop.)
    assert "half answer from A" in streamed
    assert "real answer from B" in streamed


# ── 1d. claude_cli HTTP 401 is classified as AUTH (route onward) ─────────

def test_claude_cli_401_is_auth():
    from llm_router import _claude_cli_is_auth
    ex = RuntimeError("claude CLI error: HTTP 401 Unauthorized")
    assert _claude_cli_is_auth(ex) is True


def test_claude_cli_worded_logout_is_auth():
    """The CLI often words it ('please log in', 'not authenticated',
    'oauth token has expired') with no bare 401 — still AUTH."""
    from llm_router import _claude_cli_is_auth
    for msg in ("claude CLI error: not authenticated — please log in",
                "claude CLI error: OAuth token has expired",
                "claude CLI error: you are logged out"):
        assert _claude_cli_is_auth(RuntimeError(msg)) is True


def test_claude_cli_crash_is_not_auth():
    """A non-auth CLI crash must NOT be mislabelled auth."""
    from llm_router import _claude_cli_is_auth
    assert _claude_cli_is_auth(RuntimeError("claude CLI: spawn ENOENT")) is False


def test_bare_401_still_auth_or_quota():
    """Belt-and-braces: the generic classifier already catches a bare 401
    / unauthorized (covers the API providers + the CLI's coded form)."""
    from llm_router import _looks_like_auth_or_quota
    assert _looks_like_auth_or_quota(RuntimeError("401 Unauthorized")) is True
    assert _looks_like_auth_or_quota(RuntimeError("invalid api key")) is True


def test_claude_cli_401_routes_onward_not_fatal(monkeypatch):
    """End-to-end at the router: a claude_cli 401 must fall through to the
    next provider, not blow up the whole turn."""
    router = _mk_router()
    seq = iter([("claude_cli", "sonnet", "n1"), ("ollama", "command-r", "n2")])
    monkeypatch.setattr(router, "_route", lambda h, m: next(seq))
    monkeypatch.setattr(router, "_get_client", lambda p: object())
    monkeypatch.setattr(router, "configured_providers", lambda: ["claude_cli", "ollama"])

    def fake_once(*, provider, on_chunk, **kw):
        if provider == "claude_cli":
            raise RuntimeError("claude CLI error: HTTP 401 Unauthorized")
        return _FakeResp("ollama saved the turn")
    monkeypatch.setattr(router, "_complete_once", fake_once)

    resp = router.complete(history=[{"role": "user", "content": "hi"}],
                           model="auto")
    assert resp.text == "ollama saved the turn"
    # claude_cli got blocked with an auth-class reason (not a generic crash).
    assert router.is_provider_blocked("claude_cli")
    assert "invalid key" in router.block_reason("claude_cli") \
        or "signed out" in router.block_reason("claude_cli")


# ════════════════════════════════════════════════════════════════════════
# PILLAR 2 — BRAIN RECALL UNIFY (memory_query → live brain daemon)
# ════════════════════════════════════════════════════════════════════════

# A realistic brain.browse reply with a query → `search` cards (the shape
# organize._card emits: id / kind / headline / salience / why).
_BRAIN_REPLY = {
    "ok": True,
    "search": [
        {"id": "frag:revit:001", "kind": "fact",
         "headline": "JPD17 Revit broker runs on port 48885",
         "salience": 0.91, "why": "matches your search",
         "details": {"text": "..."}},
        {"id": "frag:skill:002", "kind": "skill",
         "headline": "revfix.py repairs glued revision reasons",
         "salience": 0.77, "why": "matches your search"},
    ],
}


def test_memory_query_routes_to_brain_daemon(bridge_inst, monkeypatch):
    """memory_query._work() queries the LIVE brain daemon (brain.browse)
    and returns ITS results — mapped into the {id,kind,label,score,why}
    envelope. RED on main (memory_query only read graph.sqlite via
    self.tools.invoke; the daemon was never consulted)."""
    seen: dict = {}

    def fake_brain_tool(tool, args, timeout=4.0):
        seen["tool"] = tool
        seen["args"] = args
        return dict(_BRAIN_REPLY)
    monkeypatch.setattr(bridge_inst, "_brain_tool", fake_brain_tool)
    # If the daemon path were skipped, the local graph would answer EMPTY
    # on this fresh tmp install — so a non-empty result here proves the
    # daemon path ran.
    out = _drain(
        lambda: bridge_inst.memory_query(json.dumps({"question": "revit broker"})),
        lambda o: o.get("count", 0) > 0 or o.get("source") == "brain")

    assert seen.get("tool") == "brain.browse"
    assert seen["args"].get("query") == "revit broker"
    assert out["status"] == "ok"
    assert out["source"] == "brain"
    assert out["count"] == 2
    ids = [r["id"] for r in out["results"]]
    assert ids == ["frag:revit:001", "frag:skill:002"]
    first = out["results"][0]
    # Daemon card → envelope mapping.
    assert first["label"] == "JPD17 Revit broker runs on port 48885"
    assert first["kind"] == "fact"
    assert first["score"] == 0.91
    assert first["why"] == "matches your search"


def test_memory_query_brain_honors_kinds_and_limit(bridge_inst, monkeypatch):
    """The daemon-path mapper applies the same kinds / limit filters the
    envelope advertises."""
    monkeypatch.setattr(bridge_inst, "_brain_tool",
                        lambda tool, args, timeout=4.0: dict(_BRAIN_REPLY))
    out = _drain(
        lambda: bridge_inst.memory_query(json.dumps({
            "question": "revit", "kinds": ["skill"], "limit": 5})),
        lambda o: o.get("source") == "brain")
    assert out["status"] == "ok"
    assert out["count"] == 1
    assert out["results"][0]["kind"] == "skill"


def test_memory_query_falls_back_to_graph_when_daemon_cold(bridge_inst,
                                                            monkeypatch):
    """Daemon down / unreachable → memory_query degrades to the local
    graph.sqlite ranker and returns a graceful empty (NOT an error). This
    is what keeps a fresh machine (no daemon) working + preserves the
    existing local-graph contract."""
    # Simulate a dead daemon: _brain_tool reports not-ok.
    monkeypatch.setattr(
        bridge_inst, "_brain_tool",
        lambda tool, args, timeout=4.0: {"ok": False,
                                         "error": "brain daemon unreachable"})
    out = _drain(
        lambda: bridge_inst.memory_query(json.dumps({"question": "nothing here"})),
        lambda o: o.get("status") == "ok")
    assert out["status"] == "ok"          # graceful, never an error
    assert out["results"] == []           # empty graph on tmp install
    assert out["count"] == 0
    assert out.get("source") != "brain"   # came from the fallback path


def test_memory_query_brain_helper_returns_none_when_no_search(bridge_inst,
                                                               monkeypatch):
    """An `ok` reply that lacks a `search` array (older daemon build) must
    return None from the helper so the caller falls back — not a crash, not
    a fabricated empty."""
    monkeypatch.setattr(bridge_inst, "_brain_tool",
                        lambda tool, args, timeout=4.0: {"ok": True})
    res = bridge_inst._memory_query_brain({"question": "x"})
    assert res is None


def test_memory_query_helper_present(bridge_inst):
    assert hasattr(bridge_inst, "_memory_query_brain")
    assert callable(bridge_inst._memory_query_brain)
