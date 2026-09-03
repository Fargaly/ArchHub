"""Founder bug 2026-06-20 — "ping notion" -> "notion is not reachable
(unknown)".

The composer ping path is JSX -> bridge.probe_connector(host) -> connector
.probe(). When a token-based REST connector (notion / dropbox / teams /
procore / speckle) has NO token configured, the honest answer is
"not connected — add your token", NOT "(unknown)".

Two defects produced the misleading message:

1. `_cached_async` caches a status-less {"error": ...} dict when a probe
   raises, and the JSX fell through to `(res.status) || 'unknown'`.
2. The host-pill / status surfaces routed `notion` through a process-based
   probe in host_detector that had nothing to do with the token.

These tests lock the fix at the bridge mechanism: probe_connector always
returns a result carrying an honest, named `status` — and a token-based REST
host whose probe yielded no usable status resolves to `unauthorized` with an
actionable note, never "(unknown)".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import pytest  # noqa: E402

import bridge  # noqa: E402


class _NormaliserBridge:
    """Plain stand-in borrowing the real _normalise_probe_status method +
    the class _TOKEN_REST_HOSTS attribute — no Qt construction."""

    _TOKEN_REST_HOSTS = bridge.ArchHubBridge._TOKEN_REST_HOSTS

    def __init__(self):
        self._normalise_probe_status = \
            bridge.ArchHubBridge._normalise_probe_status.__get__(self)


def test_statusless_error_dict_does_not_become_unknown_for_rest_host():
    """The exact founder repro: a probe that raised was cached as
    {"error": ...} (no status). For a token-based REST host this must
    resolve to `unauthorized` with an add-your-token note — never a
    status the JSX renders as "(unknown)"."""
    b = _NormaliserBridge()
    out = b._normalise_probe_status("notion", {"error": "boom"})
    assert out["status"] == "unauthorized", out
    note = out["note"].lower()
    assert "settings" in note and "sign-ins" in note, out
    assert "notion" in note, out
    assert "unknown" not in note, out


@pytest.mark.parametrize("host,display", [
    ("notion", "Notion"),
    ("dropbox", "Dropbox"),
    ("teams", "Teams"),
    ("procore", "Procore"),
    ("speckle", "Speckle"),
])
def test_every_token_rest_host_gets_add_token_message(host, display):
    b = _NormaliserBridge()
    # A completely empty / missing probe result (no status at all).
    out = b._normalise_probe_status(host, {})
    assert out["status"] == "unauthorized", out
    assert display in out["note"], out
    assert "add your token" in out["note"].lower(), out
    assert "unknown" not in out["note"].lower(), out


def test_unauthorized_status_passes_through_with_its_token_hint():
    """When the connector itself returned `unauthorized` + a hint, the
    normaliser preserves it verbatim (the actionable message)."""
    b = _NormaliserBridge()
    hint = ("Notion token not set. Open Settings -> Sign-ins -> Notion and "
            "paste an internal integration token.")
    out = b._normalise_probe_status(
        "notion", {"status": "unauthorized", "note": hint, "detail": {}})
    assert out["status"] == "unauthorized"
    assert out["note"] == hint


def test_valid_statuses_preserved():
    b = _NormaliserBridge()
    for st in ("live", "loaded_dead", "missing", "probing"):
        out = b._normalise_probe_status("notion", {"status": st, "note": "n"})
        assert out["status"] == st, out


def test_non_token_host_statusless_is_missing_not_unknown():
    """A non-token host (e.g. a broker host) with no usable status reports
    `missing`, never "(unknown)"."""
    b = _NormaliserBridge()
    out = b._normalise_probe_status("revit", {"error": "broker down"})
    assert out["status"] == "missing", out
    assert "unknown" not in out["note"].lower(), out


def test_result_is_json_safe():
    """probe_connector json-encodes the result — the normalised dict must
    round-trip cleanly."""
    b = _NormaliserBridge()
    out = b._normalise_probe_status("dropbox", {"error": "x"})
    json.loads(json.dumps(out))
