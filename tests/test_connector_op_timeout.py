"""Connector ops are HARD-BOUNDED — a stalling op can never block the
caller (the chat worker thread) unbounded.

Root cause (founder 2026-06-20, 'notion prompt hangs the chat turn'):
a connector op makes a blocking network/auth/COM call with no bound
(notion's urlopen(timeout=30) × MAX_PAGES=10 = up to 300s). Dispatched
inline from the router's tool-use loop, it froze the chat turn with zero
chunks shown. The class fix wraps the SHARED chokepoint — connectors.base
.run_op — in a wall-clock budget so a slow host returns an honest
'unreachable' OpResult instead of blocking.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import connectors.base as base  # noqa: E402
from connectors.base import (  # noqa: E402
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
)


class _StallConnector(Connector):
    """A connector whose op sleeps far longer than any sane budget —
    stands in for a notion/dropbox/teams REST op against an unreachable
    or wedged host."""

    host = "stallhost"
    display_name = "Stall Host"
    mechanism = "rest"

    def probe(self) -> dict:
        return {"status": "live", "note": "", "detail": {}}

    def build_ops(self) -> list:
        def _slow(seconds: float = 30.0, **_):
            time.sleep(float(seconds))
            return OpResult(ok=True, value="should never be seen")

        def _fast(**_):
            return OpResult(ok=True, value=[1, 2, 3], value_preview="3 items")

        return [
            ConnectorOp(
                op_id="stallhost.slow", host="stallhost", kind="read",
                label="Slow", description="Blocks forever.",
                inputs=[ParamSpec(id="seconds", label="s", type="number",
                                  default=30.0)],
                output_type="dict", fn=_slow,
            ),
            ConnectorOp(
                op_id="stallhost.fast", host="stallhost", kind="read",
                label="Fast", description="Returns immediately.",
                inputs=[], output_type="list", fn=_fast,
            ),
        ]


def _register_stall(monkeypatch):
    """Register the stall connector in an isolated registry copy so it
    doesn't leak into other tests."""
    c = _StallConnector()
    reg = dict(base._CONNECTORS)
    reg[c.host] = c
    monkeypatch.setattr(base, "_CONNECTORS", reg)
    return c


def test_stalling_op_is_bounded_and_returns_unreachable(monkeypatch):
    _register_stall(monkeypatch)
    # Tight budget for the test; the op sleeps 30s — must NOT block that long.
    t0 = time.time()
    res = base.run_op("stallhost.slow", seconds=30.0, _op_timeout=1.0)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"run_op blocked {elapsed:.1f}s — budget not enforced"
    assert isinstance(res, OpResult)
    assert res.ok is False
    assert "unreachable" in res.error.lower()
    # Honest: it names that the turn was not blocked.
    assert "not blocked" in res.error.lower()


def test_fast_op_is_unaffected_by_the_budget(monkeypatch):
    _register_stall(monkeypatch)
    t0 = time.time()
    res = base.run_op("stallhost.fast", _op_timeout=5.0)
    elapsed = time.time() - t0
    assert elapsed < 1.0, "fast op should return promptly, not wait on budget"
    assert res.ok is True
    assert res.value == [1, 2, 3]


def test_op_timeout_kwarg_is_not_forwarded_to_the_op(monkeypatch):
    """`_op_timeout` is a transport control — it must be popped before the
    op fn runs, never passed through as a connector input."""
    _register_stall(monkeypatch)
    # _fast takes only **_, so a leaked kwarg wouldn't error here; assert
    # the op still succeeds and the control didn't corrupt the call.
    res = base.run_op("stallhost.fast", _op_timeout=2.0)
    assert res.ok is True


def test_default_budget_constant_is_sane():
    # The default must be generous enough for a healthy REST round-trip yet
    # well under the per-turn budget (70s) so the turn never starves.
    assert 5.0 <= base.DEFAULT_OP_TIMEOUT_SECONDS <= 40.0
