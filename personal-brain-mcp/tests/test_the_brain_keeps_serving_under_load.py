"""One slow tool must not silence the whole daemon.

Measured on the founder's machine, 2026-09-06 04:20: `initialize` answered in
0.0 s while every `tools/call` hung, and the launcher's watchdog had to kill
the process to get the brain back. Every HTTP dispatch went through
`asyncio.to_thread`, which uses the DEFAULT executor shared by everything else
in the process, so a handful of slow tools took the server down with them.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time

import pytest

from personal_brain import mcp_core


class _Server:
    """Just enough of the server to exercise the dispatch lane."""

    _TOOL_LANE_WORKERS = mcp_core.__dict__.get("_TOOL_LANE_WORKERS", 8)

    def __init__(self, render):
        self.render_sse = render

    _tool_lane = mcp_core._StreamableHTTPServer._tool_lane if hasattr(
        mcp_core, "_StreamableHTTPServer") else None


def _dispatch_owner():
    """The class that carries the tool lane, whatever it is called."""
    for value in vars(mcp_core).values():
        if inspect.isclass(value) and hasattr(value, "_dispatch_in_tool_lane"):
            return value
    raise AssertionError("no class carries _dispatch_in_tool_lane")


def test_tool_work_runs_off_the_shared_default_executor():
    owner = _dispatch_owner()
    source = inspect.getsource(owner._dispatch_in_tool_lane)
    assert "run_in_executor" in source and "_tool_lane()" in source
    assert "asyncio.to_thread" not in source
    lane = inspect.getsource(owner._tool_lane)
    assert "ThreadPoolExecutor" in lane and "max_workers" in lane
    handler = inspect.getsource(owner)
    assert "_dispatch_in_tool_lane(message)" in handler


def test_a_call_that_never_returns_releases_its_caller():
    owner = _dispatch_owner()
    holder = owner.__new__(owner)
    holder._TOOL_CALL_BUDGET_SECONDS = 0.3
    holder._TOOL_LANE_WORKERS = 2
    started = []

    def never_returns(_message):
        started.append(time.time())
        time.sleep(30)
        return "too late"

    holder.render_sse = never_returns
    began = time.monotonic()
    answer = asyncio.run(holder._dispatch_in_tool_lane({"id": 7}))
    spent = time.monotonic() - began
    assert spent < 5.0, "the caller waited %.1fs" % spent
    assert started, "the work really was dispatched"
    assert answer.startswith("event: message")
    payload = json.loads(answer.split("data: ", 1)[1].strip())
    assert payload["id"] == 7
    assert payload["error"]["code"] == -32000
    assert "did not finish" in payload["error"]["message"]


def test_a_normal_call_is_returned_untouched():
    owner = _dispatch_owner()
    holder = owner.__new__(owner)
    holder._TOOL_CALL_BUDGET_SECONDS = 5.0
    holder._TOOL_LANE_WORKERS = 2
    holder.render_sse = lambda message: "event: message"
    assert asyncio.run(holder._dispatch_in_tool_lane({"id": 1})) == "event: message"


def test_the_budget_is_generous_enough_for_real_work():
    """brain.context takes about 8 s on the founder's store; a tight budget
    would turn working tools into errors."""
    owner = _dispatch_owner()
    assert owner._TOOL_CALL_BUDGET_SECONDS >= 60
