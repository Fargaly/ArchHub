"""Courts for stable same-origin admission across runtime worker handoff."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nodelang.runtime_gateway import (
    BackendGeneration,
    GatewayError,
    RuntimeAdmissionGate,
    RuntimeGateway,
)


class _Backend:
    def __init__(self, name):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _reply(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                payload = json.dumps({
                    "backend": name,
                    "method": self.command,
                    "path": self.path,
                    "body": body.decode("utf-8"),
                    "cookie": self.headers.get("Cookie"),
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)

            do_GET = _reply
            do_POST = _reply

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def test_admission_drain_holds_new_requests_until_next_generation():
    gate = RuntimeAdmissionGate()
    first = BackendGeneration("http://127.0.0.1:9011", 1, "owner-1")
    second = BackendGeneration("http://127.0.0.1:9012", 2, "owner-2")
    gate.activate(first)
    entered = threading.Event()
    release = threading.Event()

    def in_flight():
        with gate.admit() as admitted:
            assert admitted == first
            entered.set()
            release.wait(5)

    active = threading.Thread(target=in_flight)
    active.start()
    assert entered.wait(2)
    drained = []
    drain = threading.Thread(
        target=lambda: drained.append(gate.begin_drain(1, timeout=5))
    )
    drain.start()
    time.sleep(0.05)
    assert drain.is_alive()
    waiting = []
    waiter = threading.Thread(
        target=lambda: (
            waiting.append(next(_admitted(gate)))
        )
    )
    waiter.start()
    release.set()
    active.join(2)
    drain.join(2)
    assert drained == [first]
    assert waiter.is_alive()
    gate.activate(second)
    waiter.join(2)
    assert waiting == [second]


def _admitted(gate):
    with gate.admit(timeout=5) as backend:
        yield backend


def test_gateway_preserves_origin_request_and_switches_only_after_drain():
    first = _Backend("one")
    second = _Backend("two")
    gateway = RuntimeGateway(activation_verifier=lambda _backend: None).start()
    try:
        gateway.activate(BackendGeneration(first.url, 1, "owner-1"))
        request = urllib.request.Request(
            gateway.url + "/thing?q=1",
            data=b"payload",
            method="POST",
            headers={"Cookie": "session=opaque", "Content-Type": "text/plain"},
        )
        response = urllib.request.urlopen(request, timeout=5)
        payload = json.loads(response.read())
        assert payload == {
            "backend": "one", "method": "POST", "path": "/thing?q=1",
            "body": "payload", "cookie": "session=opaque",
        }
        assert response.headers["X-ArchHub-Runtime-Generation"] == "1"

        gateway.gate.begin_drain(1)
        gateway.activate(BackendGeneration(second.url, 2, "owner-2"))
        response = urllib.request.urlopen(gateway.url + "/next", timeout=5)
        assert json.loads(response.read())["backend"] == "two"
        assert response.headers["X-ArchHub-Runtime-Generation"] == "2"
        with pytest.raises(GatewayError, match="did not advance"):
            gateway.activate(BackendGeneration(first.url, 1, "owner-1"))
    finally:
        gateway.close()
        first.close()
        second.close()


def test_gateway_denies_non_loopback_backends_and_times_out_with_retry_after():
    gateway = RuntimeGateway(
        admission_timeout=0.05,
        activation_verifier=lambda _backend: None,
    ).start()
    try:
        with pytest.raises(GatewayError, match="loopback"):
            gateway.activate(BackendGeneration("http://192.0.2.1:80", 1, "owner"))
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(gateway.url + "/waiting", timeout=2)
        assert caught.value.code == 503
        assert caught.value.headers["Retry-After"] == "1"
    finally:
        gateway.close()


def test_gateway_refuses_to_exist_without_authority_verifier():
    with pytest.raises(GatewayError, match="graph-backed"):
        RuntimeGateway()
