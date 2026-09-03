"""Shared quiet local HTTP transport for ArchHub runtimes."""
from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Ignore ordinary client disconnects while preserving unexpected errors."""

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionAbortedError,
                              ConnectionResetError)):
            return
        super().handle_error(request, client_address)


__all__ = ["QuietThreadingHTTPServer"]
