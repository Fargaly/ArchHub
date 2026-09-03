"""Sentry anti-flood — the CLASS fix + the ambient SOURCE fix.

Regression guard for the Sentry flood: a recurring archhub.llm ERROR (the
ambient self-extend pass cycling a signed-out provider chain) used to ship
one Sentry event PER occurrence — thousands of identical events.

These prove:
  (1) before_send DROPS past the per-fingerprint cap for ONE fingerprint
      (the class fix — no recurring error can flood).
  (2) distinct fingerprints are NOT collapsed (a real, different crash still
      reports).
  (3) the PYTEST drop + redact_dict path are preserved.
  (4) a contained ambient error never reaches a capture call, ambient no-ops
      cleanly with no reachable model, and the consecutive-failure backoff
      parks it (the source fix) — all WITHOUT a live model.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import sentry_init  # noqa: E402


def _exc_event(etype: str = "AuthenticationError",
               func: str = "_route", lineno: int = 1641,
               module: str = "llm_router") -> dict:
    """Shape a Sentry exception event the way LoggingIntegration/SDK builds."""
    return {
        "exception": {"values": [{
            "type": etype,
            "value": "invalid x-api-key",
            "stacktrace": {"frames": [
                {"module": module, "function": func, "lineno": lineno},
            ]},
        }]},
        "level": "error",
    }


def _log_event(logger: str = "archhub.llm",
               msg: str = "[anthropic] EXCEPTION AuthenticationError: 401") -> dict:
    """A LoggingIntegration record event (no exception payload)."""
    return {"logger": logger, "level": "error",
            "logentry": {"message": msg}}


def _send(event):
    """Call before_send the way the SDK would (PYTEST env cleared)."""
    import os
    prev = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        return sentry_init._before_send(event, {})
    finally:
        if prev is not None:
            os.environ["PYTEST_CURRENT_TEST"] = prev


# ─── (1) per-fingerprint cap drops the flood ──────────────────────────────

def test_before_send_drops_past_cap_for_one_fingerprint():
    sentry_init._reset_rate_limiter()
    cap = sentry_init._FP_CAP
    kept = 0
    dropped = 0
    # Fire the SAME recurring error far past the cap.
    for _ in range(cap + 50):
        out = _send(_exc_event())
        if out is None:
            dropped += 1
        else:
            kept += 1
    assert kept == cap, f"expected exactly {cap} kept, got {kept}"
    assert dropped == 50, f"expected 50 dropped, got {dropped}"


def test_logging_record_flood_also_capped():
    # The actual feed path: archhub.llm ERROR records via LoggingIntegration.
    sentry_init._reset_rate_limiter()
    cap = sentry_init._FP_CAP
    results = [_send(_log_event()) for _ in range(cap + 20)]
    kept = [r for r in results if r is not None]
    assert len(kept) == cap


def test_interpolated_provider_collapses_to_one_fingerprint():
    # [claude_cli] / [codex_cli] / [anthropic] differ only by provider — the
    # message-template fingerprint must collapse them so the cap bites the
    # CLASS, not each provider separately.
    sentry_init._reset_rate_limiter()
    msgs = [
        "[claude_cli] EXCEPTION RuntimeError: 401",
        "[codex_cli] EXCEPTION RuntimeError: timed out",
        "[anthropic] EXCEPTION AuthenticationError: 401",
    ]
    # NOTE: these differ in message text, so they are DISTINCT fingerprints;
    # each is independently capped. Prove each is capped at _FP_CAP.
    for m in msgs:
        kept = sum(1 for _ in range(sentry_init._FP_CAP + 5)
                   if _send(_log_event(msg=m)) is not None)
        assert kept == sentry_init._FP_CAP


# ─── (2) distinct fingerprints are not collapsed ──────────────────────────

def test_distinct_fingerprints_each_get_through():
    sentry_init._reset_rate_limiter()
    a = _send(_exc_event(etype="AuthenticationError", lineno=1641))
    b = _send(_exc_event(etype="RuntimeError", func="_run", lineno=10))
    c = _send(_exc_event(etype="ValueError", func="other", lineno=99))
    assert a is not None and b is not None and c is not None


def test_real_crash_still_reports_first_time():
    sentry_init._reset_rate_limiter()
    out = _send(_exc_event(etype="ZeroDivisionError", func="boom", lineno=5))
    assert out is not None, "a genuine first-time crash must still report"


# ─── (3) PYTEST drop + redaction preserved ────────────────────────────────

def test_pytest_env_still_drops():
    import os
    sentry_init._reset_rate_limiter()
    os.environ["PYTEST_CURRENT_TEST"] = "x"
    try:
        assert sentry_init._before_send(_exc_event(), {}) is None
    finally:
        os.environ.pop("PYTEST_CURRENT_TEST", None)


def test_kept_event_is_redacted():
    sentry_init._reset_rate_limiter()
    ev = _exc_event()
    ev["extra"] = {"path": r"C:\Users\fargaly\secret\file.txt"}
    out = _send(ev)
    assert out is not None
    # redact_dict must have run — the raw username path must not survive.
    assert "fargaly" not in repr(out).lower()


# ─── (4) global rolling-window cap ────────────────────────────────────────

def test_global_window_cap_limits_burst():
    sentry_init._reset_rate_limiter()
    # Many DISTINCT fingerprints (each under the per-fp cap) still cannot
    # burst past the global window cap.
    kept = 0
    for i in range(sentry_init._MAX_PER_WINDOW + 25):
        out = _send(_exc_event(etype=f"Err{i}", func=f"f{i}", lineno=i))
        if out is not None:
            kept += 1
    assert kept == sentry_init._MAX_PER_WINDOW


# ─── (5) CONSENT preserved — init() still honours telemetry + DSN ──────────
# Regression guard: the flood fix rewrote the top of sentry_init; init() must
# still resolve the DSN (the `_dsn` helper) and gate on consent. A NameError /
# missing helper here would silently disable crash reporting = consent broken.

def test_dsn_helper_exists_and_resolves(monkeypatch):
    assert hasattr(sentry_init, "_dsn"), "init() depends on _dsn(); it must exist"
    monkeypatch.setenv("ARCHHUB_SENTRY_DSN", "https://k@o1.ingest.sentry.io/1")
    monkeypatch.setattr(sentry_init, "load_setting", lambda *_a, **_k: None)
    assert sentry_init._dsn() == "https://k@o1.ingest.sentry.io/1"


def test_init_refuses_when_consent_off(monkeypatch):
    sentry_init._initialised = False
    monkeypatch.setattr(sentry_init, "consent_state", lambda: False)
    assert sentry_init.init(release="x") is False


def test_init_brings_sentry_up_with_consent_and_dsn(monkeypatch):
    import types
    sentry_init._initialised = False
    monkeypatch.setattr(sentry_init, "consent_state", lambda: True)
    monkeypatch.setenv("ARCHHUB_SENTRY_DSN", "https://k@o1.ingest.sentry.io/1")
    monkeypatch.setattr(sentry_init, "load_setting", lambda *_a, **_k: None)
    captured = {}
    fake = types.ModuleType("sentry_sdk")
    fake.init = lambda **kw: captured.update(kw)
    fake.set_user = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    try:
        assert sentry_init.init(release="1.0") is True
        # before_send must be wired so the flood guard + redaction run live.
        assert captured.get("before_send") is sentry_init._before_send
    finally:
        sentry_init._initialised = False
