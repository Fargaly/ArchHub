"""The single desktop closes through its launcher, never through a gateway worker."""
from pathlib import Path
import runpy

from nodelang import desktop


def test_canonical_close_request_does_not_start_a_supervisor_or_second_runtime(monkeypatch):
    calls = []
    def closed(path, *, run_name):
        calls.append((Path(path).name, run_name))
        raise SystemExit(0)
    monkeypatch.setattr(runpy, 'run_path', closed)
    try:
        desktop.main()
    except SystemExit as stopped:
        assert stopped.code == 0
    else:
        raise AssertionError('the launcher exit must propagate')
    assert calls == [('launcher.py', '__main__')]
