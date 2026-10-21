"""Shared quiet local HTTP transport for ArchHub runtimes."""
from __future__ import annotations

import sys
from http.server import HTTPServer, ThreadingHTTPServer


def create_http_server(address, handler, *, threaded=False):
    """Construct local transport, preserving each caller's concurrency policy."""
    if threaded:
        return ThreadingHTTPServer(address, handler)
    return HTTPServer(address, handler)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Ignore ordinary client disconnects while preserving unexpected errors."""

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionAbortedError,
                              ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def local_browser_admission_error(headers, expected_port: int) -> str | None:
    """Refuse a request that only LOOKS local to the browser.

    Every same-origin proof these servers rely on is a header the browser
    fills in, and DNS rebinding makes an attacker's page genuinely
    same-origin: it re-resolves its own hostname to 127.0.0.1, so no preflight
    is sent and script may read the reply. The one header that still tells the
    truth is Host -- it carries the name the CLIENT dialled, and a rebound page
    dialled the attacker's domain, not loopback. One admission, applied by every
    loopback HTTP surface (clean canvas, application server, runtime gateway).
    Returns None when admitted, else the refusal to answer with a 403.
    """
    origin = headers.get("Origin")
    if origin not in {
        None,
        "http://127.0.0.1:%s" % expected_port,
        "http://localhost:%s" % expected_port,
        "http://127.0.0.1",
        "http://localhost",
    }:
        return "origin denied"
    if headers.get("Host", "") not in {
        "127.0.0.1:%s" % expected_port,
        "localhost:%s" % expected_port,
    }:
        return "host denied"
    return None


__all__ = ["create_http_server", "HTTPServer", "ThreadingHTTPServer",
           "QuietThreadingHTTPServer", "local_browser_admission_error"]
