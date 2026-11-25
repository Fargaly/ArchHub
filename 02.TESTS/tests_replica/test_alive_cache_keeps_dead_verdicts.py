"""Founder 2026-11-25: agents were very slow. 6016 declaration rows overflowed the 4096 liveness cache, which then
cleared on every pass and re-asked Windows about every dead PID (830 ms per pass, ~1 core per process)."""
from nodelang import agent_declarations as ad


def test_dead_verdicts_survive_overflow_so_dead_rows_are_never_asked_again(monkeypatch):
    import psutil
    calls = []

    class Gone:
        def __init__(self, pid):
            calls.append(pid)
            raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", Gone)
    monkeypatch.setattr(ad, "_VERDICTS", {})
    rows = [{"pid": 100000 + i, "created_at": 1.0} for i in range(6016)]
    for row in rows:
        assert ad._alive(row) is False
    first = len(calls)
    assert first == 6016
    for row in rows:
        assert ad._alive(row) is False
    assert len(calls) == first, "a second pass must not ask the OS about any dead row"
