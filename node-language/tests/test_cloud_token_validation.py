"""Regression tests for cloud bearer-token plausibility (defense-in-depth).

A REAL bearer comes from POST /v1/auth/exchange and is ALWAYS long (32+ chars).
A tiny junk token like the 7-char "ah_test" must NEVER be persisted or honoured:
before the conftest APPDATA-isolation fix such a test stub leaked into the
developer's real cloud.json and left a stub that makes the app read "not signed
in" and silently breaks cross-device sync. cloud_client now adds two guards:

  * set_token() REFUSES a non-empty-but-implausible token (no write, no clobber).
  * current_token() IGNORES a junk token already on disk (self-heal, no rewrite).

These tests pin both guards + the no-clobber + a realistic round-trip + the
SECURITY floor that the refusal log NEVER contains the raw token (fingerprint
only). conftest.py isolates APPDATA, so every set_token() / cloud.json write here
lands in a throwaway per-test dir — the developer's real cloud.json is untouched.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# The exact 7-char junk sentinel from the leaked-state bug.
_JUNK = "ah_test"
# A realistic-length bearer (43 chars — clearly >= MIN_TOKEN_LEN).
_VALID = "ah_" + "z" * 40


# ── (a) set_token(junk) persists NOTHING + current_token() is None ─────────
def test_set_token_junk_persists_nothing():
    """set_token('ah_test') (7 chars) is refused: cloud.json is never written
    and current_token() reports signed-out."""
    import cloud_client as c

    assert c.current_token() is None          # clean start (isolated APPDATA)
    c.set_token(_JUNK, expires_at=time.time() + 3600)

    # Nothing persisted — the file must not even exist (no prior good token).
    assert not c.cloud_json_path().exists(), (
        "a refused junk token must not create/write cloud.json"
    )
    assert c.current_token() is None
    assert c.is_signed_in() is False


# ── (b) pre-seeded leaked cloud.json {"token":"ah_test"} → ignored on read ──
def test_preseeded_junk_token_is_ignored_on_read():
    """Simulate the LEAKED state: cloud.json already holds a 7-char token.
    current_token() must treat it as absent (self-heal) WITHOUT rewriting the
    file (a getter has no side effects)."""
    import cloud_client as c

    path = c.cloud_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": _JUNK}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    assert c.current_token() is None          # junk ignored
    assert c.is_signed_in() is False

    # The getter did NOT modify the file (no side effects; dev's file untouched).
    assert path.read_text(encoding="utf-8") == before


# ── (c) junk does NOT clobber a previously-set valid token ─────────────────
def test_junk_token_does_not_clobber_valid_token():
    """A valid token is set first; a later junk set_token() is refused and must
    leave the good token intact (current_token() still returns the valid one)."""
    import cloud_client as c

    c.set_token(_VALID, expires_at=time.time() + 3600)
    assert c.current_token() == _VALID

    c.set_token(_JUNK, expires_at=time.time() + 3600)   # refused, no clobber

    assert c.current_token() == _VALID
    assert c.is_signed_in() is True


# ── (d) realistic-length token round-trips through set_token -> current_token
def test_valid_token_roundtrips():
    """A realistic-length bearer persists and reads back unchanged."""
    import cloud_client as c

    c.set_token(_VALID, expires_at=time.time() + 3600)
    assert c.current_token() == _VALID
    assert c.is_signed_in() is True


# ── (e) the refusal log NEVER contains the raw token (fingerprint only) ─────
def test_refusal_log_never_contains_raw_token(caplog):
    """SECURITY: the guard's warning emits a FINGERPRINT (len + last 2 chars),
    never the raw token. Use a longer-than-2 junk token so 'last 2 chars' can't
    coincide with the whole string, then assert the full token is absent from
    every record/message while the length fingerprint IS present."""
    import cloud_client as c

    junk = "junkjunk_token12"[:15]   # 15 chars: implausible (< 16), > 2 long
    assert not c._is_plausible_token(junk)

    with caplog.at_level(logging.WARNING, logger="archhub.cloud_client"):
        c.set_token(junk, expires_at=time.time() + 3600)

    # A warning was emitted by the guard.
    msgs = [r.getMessage() for r in caplog.records]
    assert any("refusing implausible token" in m for m in msgs), (
        f"expected a refusal warning, got: {msgs}"
    )
    # The RAW token never appears in any record message or its raw args.
    for r in caplog.records:
        assert junk not in r.getMessage(), "raw token leaked into log message"
        for a in (r.args or ()):
            assert junk not in str(a), "raw token leaked into log args"
    # The fingerprint (length) IS present — proving we logged the safe form.
    assert any(f"len={len(junk)}" in m for m in msgs)
    # And it was refused (nothing persisted).
    assert c.current_token() is None
