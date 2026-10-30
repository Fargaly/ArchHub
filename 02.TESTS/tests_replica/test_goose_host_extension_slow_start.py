"""Court: BABOOM's private host-read extension survives a slow start on a busy desktop.

Founder 2026-10-30, installed c2491a0: "StreamableHTTP session manager started ... shutting down",
then "BABOOM brain unavailable: The private ArchHub host read extension did not start." The
server came up after a fixed 4 s deadline and was shut down by it, so BABOOM never started.
"""
from __future__ import annotations

import time

import uvicorn

from nodelang import goose_runtime, native_host_tools


class SlowServer:
    def __init__(self, _config):
        self.started, self.should_exit = False, False

    def run(self, sockets=None):
        time.sleep(4.5)  # past the old 4 s deadline, as on the founder's desktop
        self.started = True
        while not self.should_exit:
            time.sleep(0.01)


def test_a_live_server_that_starts_late_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(uvicorn, "Server", SlowServer)
    monkeypatch.setattr(native_host_tools, "register_host_tools", lambda *_args, **_kwargs: None)
    runtime = goose_runtime.GooseRuntime(app_root=tmp_path, state_dir=tmp_path, control=None)
    try:
        runtime._start_host_extension()
        assert runtime.host_extension["url"].startswith("http://127.0.0.1:")
    finally:
        runtime.close()
