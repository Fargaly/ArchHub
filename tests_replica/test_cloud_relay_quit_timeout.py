"""Quit must not leave the graph retained because the relay was mid-request.

2026-09-24 12:02 the founder app logged "shutdown : INCOMPLETE (cloud relay: TimeoutError)":
the launcher joined the relay for 6 s while its HTTP request may run for relay.timeout (20 s).
"""
import json
import time
from pathlib import Path

import pytest

from nodelang.cloud_relay import CloudRelay

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_CLOSE = "cloud_relay.close(timeout_seconds=min(30.0, cloud_relay.timeout + 2.0))"


class _Answer:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _slow_relay(block_seconds=8.0):
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        time.sleep(block_seconds)  # a claim in flight when the founder quits
        return _Answer({"task": None})

    relay = CloudRelay(base_url="https://cloud.example", token="t",
                       respond=lambda utterance: {}, execute=lambda utterance: {},
                       opener=opener)
    return relay, calls


def test_the_launcher_waits_out_one_relay_request():
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert LAUNCHER_CLOSE in launcher
    assert "cloud_relay.close(timeout_seconds=6.0)" not in launcher


def test_close_returns_cleanly_while_a_request_is_in_flight_and_the_old_bound_refused():
    old, _ = _slow_relay()
    new, _ = _slow_relay()
    old.start(), new.start()
    time.sleep(0.3)  # both workers are inside the blocked claim
    try:
        with pytest.raises(TimeoutError, match="graph close is unsafe"):
            old.close(timeout_seconds=6.0)
        cloud_relay = new
        started = time.monotonic()
        eval(LAUNCHER_CLOSE, {"min": min}, {"cloud_relay": cloud_relay})
        assert not new._thread.is_alive()  # the worker can no longer touch the graph
        assert time.monotonic() - started < new.timeout + 2.0
    finally:
        old._thread.join(10.0)
        new._thread.join(10.0)
    assert not old._thread.is_alive()


def test_a_stopped_relay_starts_no_new_request():
    relay, calls = _slow_relay(block_seconds=0.0)
    relay.request_stop()
    assert relay.poll_once() is None
    assert calls == []
