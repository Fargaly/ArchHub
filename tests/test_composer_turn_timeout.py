"""Composer turn HANG guard — root-fix for "I write and get nothing back".

Live bug (2026-06-22): a composer submit fired `agent_step` → the bridge
started its ArchHubAgentStep thread → but `agent_step_done` NEVER fired
(85s+). The bridge runner emits agent_step_done on BOTH success and
exception, so the ONLY explanation is that `run_agent_step` was BLOCKING
with no return — `router.complete()` makes a provider/LLM socket call (and
a tool-loop) with NO enforced wall-clock bound, and nothing in
`llm_router.complete` bounds the TOTAL turn time.

Root fix: `run_agent_step` runs the provider round-trip on a worker thread
joined for at most COMPOSER_TURN_DEADLINE_SECONDS and, on overrun, returns
an honest `timed_out` result instead of blocking forever. The bridge
runner adds a strictly-larger last-resort ceiling so even a hung deadline
can't keep the UI spinning.

These tests prove, WITHOUT a live model:
  (1) a HANGING router (complete() that blocks ~forever) makes
      run_agent_step return a timed_out fallback result well within the
      deadline — it NEVER hangs the caller.
  (2) the returned result carries the honest timed_out shape the JSX +
      bridge consume (timed_out:true, error:"turn_timeout", text set).
  (3) a normal (fast) router still returns a clean non-timeout result —
      the deadline never penalises a healthy turn (no regression).
"""
from __future__ import annotations

import importlib.util as _ilu
import sys
import threading
import time
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _load_app_composer_agent():
    """Load app/agents/composer_agent.py by EXPLICIT PATH under a
    non-colliding module name (the repo-root `agents` package would
    otherwise shadow it in full-suite collection order)."""
    spec = _ilu.spec_from_file_location(
        "_app_agents_composer_agent_timeout",
        str(APP / "agents" / "composer_agent.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CA = _load_app_composer_agent()


class _HangingRouter:
    """A provider that BLOCKS ~forever inside complete() — the exact hang
    that left agent_step_done unfired. The event lets the test release the
    blocked worker on teardown so no thread leaks."""

    def __init__(self):
        self.released = threading.Event()
        self.entered = threading.Event()

    def complete(self, *, history, model, on_chunk=None,
                 on_tool_invocation=None, extra_tools=None, **kwargs):
        self.entered.set()
        # Block until explicitly released (or a generous safety cap so a
        # broken test can never wedge the suite). In the real bug this was
        # an unbounded provider socket read.
        self.released.wait(timeout=30.0)

        class _Resp:
            text = "(should never be seen — we time out first)"
            tool_invocations: list = []
        return _Resp()


class _FastRouter:
    """A healthy provider that returns immediately — proves the deadline
    never penalises a normal turn."""

    def complete(self, *, history, model, on_chunk=None,
                 on_tool_invocation=None, extra_tools=None, **kwargs):
        if on_chunk is not None:
            on_chunk("hello from a healthy provider")

        class _Resp:
            text = "hello from a healthy provider"
            tool_invocations: list = []
        return _Resp()


def test_hanging_provider_returns_timed_out_within_deadline(monkeypatch):
    """A blocking router must NOT hang run_agent_step. Shorten the deadline
    so the test is fast, then assert run_agent_step returns a timed_out
    result well inside it."""
    monkeypatch.setattr(_CA, "COMPOSER_TURN_DEADLINE_SECONDS", 1.5,
                        raising=True)
    # WARM the lazy-import path (completion_gate + tools) with a fast
    # router first, so the timed measurement below reflects ONLY the
    # deadline-bounded provider round-trip — not one-time cold-import cost
    # that lives outside the wall-clock budget.
    _CA.run_agent_step(user_msg="warm", graph={"nodes": []},
                       router=_FastRouter(), mode="yolo")

    router = _HangingRouter()

    t0 = time.monotonic()
    result = _CA.run_agent_step(
        user_msg="build me a wall",
        graph={"nodes": [], "wires": []},
        router=router,
        mode="yolo",
    )
    elapsed = time.monotonic() - t0

    # Released the blocked worker; it dies as a daemon regardless.
    router.released.set()

    # The router was actually entered (we really exercised the blocking
    # path, not some early return).
    assert router.entered.is_set(), "router.complete was never reached"
    # Returned at ~the 1.5s deadline plus scheduling slack — NEVER the 30s
    # the hang would otherwise take, and never the 85s+ live hang. (Bounded
    # to deadline + slack now that cold-import cost is warmed above.)
    assert elapsed < 4.0, f"run_agent_step took {elapsed:.1f}s — it HUNG"
    # Honest timeout shape the bridge + JSX consume.
    assert result.get("timed_out") is True
    assert result.get("error") == "turn_timeout"
    assert result.get("text"), "timed_out result must carry a user message"
    assert "actions" in result


def test_fast_provider_is_not_timed_out():
    """No regression: a healthy, fast router returns a clean non-timeout
    result — the deadline only fires on a real stall."""
    result = _CA.run_agent_step(
        user_msg="hi",
        graph={"nodes": [], "wires": []},
        router=_FastRouter(),
        mode="yolo",
    )
    assert not result.get("timed_out")
    assert result.get("error") != "turn_timeout"
    assert result.get("text") == "hello from a healthy provider"


def test_deadline_constant_exists_and_is_sane():
    """Code-shape guard: the wall-clock budget the fix relies on exists and
    is a positive, bounded number (so a refactor can't silently drop it)."""
    d = getattr(_CA, "COMPOSER_TURN_DEADLINE_SECONDS", None)
    assert isinstance(d, (int, float)) and 0 < d <= 600
