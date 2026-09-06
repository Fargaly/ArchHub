"""A busy brain is not a missing authority.

The founder's session was refused at the stop gate with "Universal work
authority is unavailable" while the brain was up and answering: one 6 second
attempt had landed during a heavy tool call. The gate now tries twice, the
second time patiently, before calling anything unavailable.
"""
from __future__ import annotations

import importlib.util
import inspect
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _brainwrap():
    spec = importlib.util.spec_from_file_location(
        "brainwrap_under_test", ROOT / "tools" / "brainwrap.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_slow_first_answer_is_waited_out_not_declared_missing(monkeypatch):
    module = _brainwrap()
    tries = []

    class _Answer:
        def __enter__(self):
            return self
        def __exit__(self, *_exc):
            return False
        def read(self):
            return b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\\"ok\\": true}"}]}}\n\n'

    def urlopen(_request, timeout=None):
        tries.append(timeout)
        if len(tries) == 1:
            raise TimeoutError("the daemon was busy")
        return _Answer()

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    out = module.call_tool("brain.universal_work_status", {})
    assert out == {"ok": True}, out
    assert len(tries) == 2, tries
    assert tries[1] > tries[0], "the second attempt must be the patient one"


def test_a_daemon_that_never_answers_is_still_reported(monkeypatch):
    module = _brainwrap()
    calls = []

    def urlopen(_request, timeout=None):
        calls.append(timeout)
        raise TimeoutError("silent")

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    assert module.call_tool("brain.universal_work_status", {}) is None
    assert len(calls) == 2, "two attempts, then the honest None"


def test_the_gate_still_denies_on_a_real_absence():
    module = _brainwrap()
    source = inspect.getsource(module)
    assert "Universal work authority is unavailable; stop denied." in source


def _verdict_with(module, monkeypatch, *, held):
    monkeypatch.setattr(module, "call_tool", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "_port_held", lambda *_a, **_k: held)
    return module._completion_gate_verdict


def test_a_booting_brain_that_holds_its_port_does_not_deny(monkeypatch):
    """After the founder's app relaunches, the fresh brain holds :8473 for
    minutes before its tools answer. That restart orphaned every enrolment,
    so nothing is left to protect; the gate must let the session stop."""
    module = _brainwrap()
    verdict = _verdict_with(module, monkeypatch, held=True)
    sig = inspect.signature(verdict)
    kwargs = {name: "s1" if name == "session_id" else "claude"
              for name in sig.parameters if name in ("session_id", "runtime")}
    for name in sig.parameters:
        if name not in kwargs and sig.parameters[name].default is inspect._empty:
            kwargs[name] = None
    denied, _reason = verdict(**kwargs)
    assert denied is False


def test_a_dead_port_still_denies(monkeypatch):
    module = _brainwrap()
    verdict = _verdict_with(module, monkeypatch, held=False)
    sig = inspect.signature(verdict)
    kwargs = {name: "s1" if name == "session_id" else "claude"
              for name in sig.parameters if name in ("session_id", "runtime")}
    for name in sig.parameters:
        if name not in kwargs and sig.parameters[name].default is inspect._empty:
            kwargs[name] = None
    denied, reason = verdict(**kwargs)
    assert denied is True and "unavailable" in reason
