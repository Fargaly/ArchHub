"""Regression guard: embedded secrets must be REJECTED by the cloud replica
gate (defense-in-depth) and must never persist RAW on disk.

Founder 2026-06-02: AIza (Google) / xoxb- (Slack) / rk_live_ (Stripe) secrets
embedded mid-text slipped the startswith-only `_is_secret_like`, were accepted
by `apply_delta`, and persisted RAW in the per-user replica brain.db on disk.
Fixed: `_is_secret_like` now searches ANYWHERE (after stripping op:// refs) and
`_fragment_has_secret` recurses into extras. These tests lock that in, including
the report's exact on-disk reproduction.
"""
import re
from pathlib import Path

import pytest

import brain_replica as B

# SYNTHETIC fixtures (no real key). Each raw value is assembled from a
# (prefix, body) split so the SOURCE contains no contiguous provider-format
# token — GitHub push-protection / secret-scanning flags a literal `AIzaSy…` /
# `xoxb-…` / `rk_live_…` even when it is obvious filler, which blocked the push
# (2026-06-04). At runtime the joined strings are byte-identical to the real
# provider formats, so the gate assertions below are exactly as strong as before.
_GOOGLE_RAW = "AIza" + "SyA1234567890abcdefGHIJKLMNOPqrstuv"
_SLACK_RAW = "xoxb" + "-123456789012-ABCDEFGHIJKLMNOP"
_STRIPE_RK_RAW = "rk_" + "live_ABCDEFGHIJKLMNOP1234567890"

EMBEDDED = [
    (f"the prod key is {_GOOGLE_RAW} ok", _GOOGLE_RAW),
    (f"slack bot token {_SLACK_RAW} rotate", _SLACK_RAW),
    (f"stripe restricted {_STRIPE_RK_RAW} here", _STRIPE_RK_RAW),
]


@pytest.mark.parametrize("text,raw", EMBEDDED)
def test_embedded_secret_flagged_anywhere(text, raw):
    assert B._is_secret_like(text) is True
    assert B._fragment_has_secret({"text": text})


def test_whole_field_secret_still_flagged():
    assert B._is_secret_like(_GOOGLE_RAW) is True


def test_op_reference_and_benign_not_flagged():
    assert B._is_secret_like("see op://vault/openai/key here") is False
    assert B._is_secret_like("task-12345678 ticket number") is False
    assert B._is_secret_like("report-20260102final.pdf") is False


def test_nested_extra_secret_flagged():
    frag = {"text": "x", "extra": {"skill": {"body":
            f"use {_GOOGLE_RAW} to call it"}}}
    assert B._fragment_has_secret(frag)


@pytest.mark.parametrize("text,raw", EMBEDDED)
def test_embedded_secret_rejected_and_never_on_disk(tmp_path, text, raw):
    """The report's repro: push a fragment with an embedded secret, confirm it
    is REJECTED by apply_delta and the raw value is NOT persisted on disk."""
    rep = B.BrainReplica.open("u_secretleak", root=Path(tmp_path))
    delta = {"fragments": [{
        "id": "f_leak",
        "kind": "fact",
        "scope": "user",
        "owner_user": "u_secretleak",
        "text": text,
        "hlc": "0000000000000001.00000000",
    }], "wiring": []}
    res = rep.apply_delta(delta)

    assert res["accepted"] == 0, "secret-carrying fragment must not be accepted"
    assert any("secret_blocked" in (r.get("reason") or "")
               for r in res["rejected"]), f"not rejected as secret: {res['rejected']}"

    # Not returned from the replica
    blob = repr(rep.list_fragments())
    assert raw not in blob, f"raw secret surfaced via list_fragments: {blob[:200]}"

    # Not in the on-disk replica db bytes (nor its WAL sidecar)
    db_path = Path(tmp_path) / "u_secretleak" / "brain.db"
    for p in (db_path, db_path.with_name("brain.db-wal")):
        if p.exists():
            assert raw.encode() not in p.read_bytes(), f"raw secret on disk in {p.name}"
