"""HARD PER-TURN BUDGET — a chat turn ALWAYS yields a real reply +
chat_done within the budget, even when the worker thread is blocked in a
sync provider/connector call.

Root cause (founder 2026-06-20): a notion-mentioning prompt blocked the
chat worker INSIDE router.complete() (a stalled connector op). The router
buffers streamed text and flushes only when complete() returns — so a
blocked turn showed ZERO chat_chunk for >78s and never finished. The fix
is an INDEPENDENT watchdog thread (not the blocked worker) that fires the
tools-disabled plain-LLM fallback (or an honest backstop line) + chat_done
at the deadline. A QTimer on the worker can't fire — it's blocked — so the
watchdog must be its own thread; these tests lock that.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import bridge  # noqa: E402


class _Sig:
    """Thread-safe stand-in for a pyqtSignal — records (session, *args)."""
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def emit(self, *args):
        with self._lock:
            self.calls.append(args)

    def count(self):
        with self._lock:
            return len(self.calls)

    def texts(self):
        with self._lock:
            return [a[1] for a in self.calls if len(a) > 1]


class _LLMResponse:
    def __init__(self, text, routing_note=""):
        self.text = text
        self.model = "test-model"
        self.routing_note = routing_note
        self.tool_invocations = []
        self.tool_calls_log = []


class _BlockedRouter:
    """complete() blocks forever (the notion-stall class). _plain_llm_fallback
    answers honestly with tools off — exactly what the watchdog must invoke."""
    def __init__(self, fallback_text="here is a plain answer"):
        self.fallback_text = fallback_text
        self.complete_entered = threading.Event()
        self._release = threading.Event()

    def complete(self, **kw):
        self.complete_entered.set()
        # Block like a wedged provider/connector. Released at teardown so the
        # daemon worker can exit cleanly.
        self._release.wait(timeout=30)
        return _LLMResponse("late winner that must NOT double-post")

    def _plain_llm_fallback(self, **kw):
        if self.fallback_text is None:
            return None
        return _LLMResponse(self.fallback_text)


class _UnreachableRouter(_BlockedRouter):
    """complete() blocks AND the plain-LLM fallback is unreachable — the
    watchdog must still close the turn with the honest backstop line."""
    def __init__(self):
        super().__init__(fallback_text=None)


def _make_dummy(router):
    d = type("D", (), {})()
    d.router = router
    d._selected_model = "auto"
    d._chat_turn_budget_s = 1.0          # shrink the 70s budget for the test
    d.chat_chunk = _Sig()
    d.chat_done = _Sig()
    d.chat_error = _Sig()
    d.chat_status = _Sig()
    d.chat_reasoning = _Sig()
    d.chat_chunk_retract = _Sig()
    d._persist_chat_plan = lambda **kw: None
    return d


def _run(dummy):
    bridge.ArchHubBridge.send_chat_history(
        dummy, "sess1", "summarize my notion notes briefly", "[]")


def test_blocked_turn_yields_fallback_reply_and_done(monkeypatch):
    r = _BlockedRouter(fallback_text="answering without host tools: here goes")
    dummy = _make_dummy(r)
    t0 = time.time()
    _run(dummy)
    # Wait for the watchdog to close the turn (budget 1s + slack).
    deadline = time.time() + 6
    while time.time() < deadline and dummy.chat_done.count() == 0:
        time.sleep(0.05)
    assert r.complete_entered.is_set(), "router.complete was never entered"
    assert dummy.chat_done.count() == 1, "watchdog must fire exactly one chat_done"
    texts = "".join(dummy.chat_chunk.texts())
    assert "here goes" in texts, f"fallback reply not emitted; got {texts!r}"
    # Real reply landed well within the budget, not after a 30s+ block.
    assert time.time() - t0 < 6
    # release the blocked worker so its daemon thread exits cleanly
    r._release.set()


def test_blocked_turn_with_unreachable_fallback_uses_backstop():
    r = _UnreachableRouter()
    dummy = _make_dummy(r)
    _run(dummy)
    deadline = time.time() + 6
    while time.time() < deadline and dummy.chat_done.count() == 0:
        time.sleep(0.05)
    assert dummy.chat_done.count() == 1
    texts = "".join(dummy.chat_chunk.texts())
    # Honest backstop — never an empty turn.
    assert texts.strip(), "turn closed with an EMPTY reply — backstop missing"
    assert "too long" in texts.lower() or "stopped waiting" in texts.lower()
    r._release.set()


def test_no_double_done_when_worker_returns_after_watchdog():
    """The blocked worker's complete() eventually returns AFTER the watchdog
    closed the turn. It must NOT post a second reply or a second chat_done."""
    r = _BlockedRouter(fallback_text="watchdog answer")
    dummy = _make_dummy(r)
    _run(dummy)
    deadline = time.time() + 6
    while time.time() < deadline and dummy.chat_done.count() == 0:
        time.sleep(0.05)
    assert dummy.chat_done.count() == 1
    # Now release the worker; give it time to run its terminal block.
    r._release.set()
    time.sleep(1.0)
    assert dummy.chat_done.count() == 1, "worker double-fired chat_done"
    texts = "".join(dummy.chat_chunk.texts())
    assert "double-post" not in texts, "late worker leaked a second reply"


def test_fast_reply_does_not_wait_for_budget():
    """A normal fast reply marks the turn done immediately; the watchdog
    stands down and never injects a fallback. The fast path is untouched."""
    class _FastRouter:
        def complete(self, *, on_chunk, **kw):
            on_chunk("hello ")
            on_chunk("world")
            return _LLMResponse("hello world")
        def _plain_llm_fallback(self, **kw):
            raise AssertionError("fallback must NOT run on the fast path")

    dummy = _make_dummy(_FastRouter())
    dummy._chat_turn_budget_s = 30.0     # long budget; fast reply must beat it
    t0 = time.time()
    _run(dummy)
    deadline = time.time() + 4
    while time.time() < deadline and dummy.chat_done.count() == 0:
        time.sleep(0.02)
    elapsed = time.time() - t0
    assert dummy.chat_done.count() == 1
    assert elapsed < 4, f"fast reply waited on the budget ({elapsed:.1f}s)"
    texts = "".join(dummy.chat_chunk.texts())
    assert "hello world" in texts
