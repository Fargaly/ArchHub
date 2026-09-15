"""Physical social HTTP boundary; graph admission remains with its caller.

No retries, redirects, worker process or durable state live here. The caller
must atomically reserve the attempt and supply a before_dispatch callback that
revalidates admission and persists the dispatch marker before network access.
Credentials are resolved only here and are never included in returned evidence.
"""
from __future__ import annotations

import http.client
import math
import ssl
import time
from urllib.parse import urlsplit

from .social_connectors import (
    MAX_RESPONSE_BYTES, PROVIDER_ORIGINS, Refusal, WORK_OPERATIONS,
    normalize_work_answer, refusal_answer, verify_prepared,
)


def _failure(state, reason, *, uncertain=False):
    return {"outcome": "uncertain" if uncertain else "failed",
            "result": {"ok": False, "state": state, "reason": reason}}


class SocialHttpHost:
    """Execute a runtime-rebuilt request with a custody-owned token resolver.

    timeout_seconds bounds socket operations and elapsed response reading, not
    the operating system DNS resolver. No claim of a hard DNS deadline is made.
    The resolver atomically checks provider/account custody and returns the
    credential for that exact binding. A prior account-verifier call alone
    cannot protect against replacement before credential resolution.
    """

    def __init__(self, credential_resolver, *, timeout_seconds=20.0):
        if not callable(credential_resolver):
            raise TypeError("social credential resolver must be callable")
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60):
            raise ValueError("social HTTP timeout must be between zero and 60 seconds")
        self._credential_resolver = credential_resolver
        self._timeout = float(timeout_seconds)

    def execute(self, prepared, vault_entry, *, before_dispatch):
        verify_prepared(prepared)
        if prepared.operation not in WORK_OPERATIONS:
            raise Refusal("invalid_input", "operation has no admitted Work response contract")
        if (type(vault_entry) is not str or not vault_entry.strip()
                or len(vault_entry.encode("utf-8")) > 512 or "\0" in vault_entry
                or not callable(before_dispatch)):
            raise Refusal("invalid_input", "social custody or dispatch callback is invalid")
        headers = {}
        allowed = {"accept", "content-type", "linkedin-version", "x-restli-protocol-version"}
        for name, value in prepared.headers:
            if (type(name) is not str or type(value) is not str
                    or name.lower() not in allowed or name.lower() in headers
                    or len(value) > 512 or any(ord(char) < 32 or ord(char) > 126 for char in value)):
                raise Refusal("invalid_input", "social request headers are invalid")
            headers[name.lower()] = value
        try:
            token = self._credential_resolver(
                provider=prepared.provider, account_id=prepared.account_id,
                vault_entry=vault_entry,
            )
            if (type(token) is not str or not 1 <= len(token) <= 16384
                    or any(ord(char) < 33 or ord(char) > 126 for char in token)):
                raise ValueError("invalid credential")
        except Exception:
            return _failure("credential_unavailable", "The admitted credential could not be resolved.")

        # A refusal here propagates to the authority caller. No connection has
        # been constructed, and no HTTP request is silently retried.
        before_dispatch()
        parts = urlsplit(prepared.url)
        target = parts.path + ("?" + parts.query if parts.query else "")
        connection = None
        request_started = False
        deadline = time.monotonic() + self._timeout
        try:
            connection = http.client.HTTPSConnection(
                PROVIDER_ORIGINS[prepared.provider], 443, timeout=self._timeout,
                context=ssl.create_default_context())
            connection.connect()
            headers["authorization"] = "Bearer " + token
            headers["accept-encoding"] = "identity"
            headers["connection"] = "close"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            connection.sock.settimeout(remaining)
            request_started = True
            connection.request(prepared.method, target, body=prepared.body, headers=headers)
            response = connection.getresponse()
            raw = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                part = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("oversize response")
            # Provider responses may echo bearer material. Never return such
            # bytes, even through a nominally successful normalized result.
            response_headers = dict(response.getheaders())
            if (token.encode("ascii") in raw
                    or any(token in str(value) for value in response_headers.values())):
                raise ValueError("credential reflected by provider")
            try:
                result = normalize_work_answer(prepared, response.status, response_headers, bytes(raw))
            except Refusal as refusal:
                result = refusal_answer(refusal)
            return {"outcome": ("succeeded" if result.get("ok") is True else
                                "uncertain" if result.get("state") == "uncertain" else "failed"),
                    "result": result}
        except Exception:
            if request_started and prepared.effect == "write":
                return _failure("uncertain", "The provider may have applied the request; reconcile before retrying.",
                                uncertain=True)
            return _failure("network_error" if request_started else "dispatch_not_connected",
                            "No confirmed provider result is available.")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
