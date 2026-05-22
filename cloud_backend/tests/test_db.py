"""SQLite DAO tests."""
from __future__ import annotations

import time


def test_get_or_create_user_creates_with_trial_plan():
    import db
    u = db.get_or_create_user("alice@studio.com")
    assert u["email"] == "alice@studio.com"
    assert u["plan"] == "trial"
    assert u["msg_used"] == 0
    assert u["msg_limit"] > 0


def test_get_or_create_user_is_idempotent():
    import db
    a = db.get_or_create_user("alice@studio.com")
    b = db.get_or_create_user("ALICE@studio.com")  # case-insensitive
    assert a["id"] == b["id"]


def test_increment_usage_decreases_remaining():
    import db
    u = db.get_or_create_user("bob@studio.com")
    start = u["msg_limit"] - u["msg_used"]
    rem = db.increment_usage(u["id"], 5)
    assert rem == start - 5
    rem = db.increment_usage(u["id"], 3)
    assert rem == start - 8


def test_quota_remaining_clamps_at_zero():
    import db
    u = db.get_or_create_user("ceo@studio.com")
    db.increment_usage(u["id"], u["msg_limit"] + 100)
    assert db.quota_remaining(u["id"]) == 0


def test_update_user_plan_resets_used():
    import db
    u = db.get_or_create_user("upgrader@studio.com")
    db.increment_usage(u["id"], 10)
    db.update_user_plan(u["id"], plan="solo")
    u2 = db.get_user(u["id"])
    assert u2["plan"] == "solo"
    assert u2["msg_used"] == 0
    assert u2["msg_limit"] == 500


def test_pkce_code_roundtrip():
    import base64, hashlib
    import db
    u = db.get_or_create_user("pkce@studio.com")
    verifier = "abc123xyz456_verifier_value_long_enough"
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
    )
    code = db.issue_code(u["id"], challenge)
    user_id = db.consume_code(code, verifier)
    assert user_id == u["id"]
    # Code is single-use.
    assert db.consume_code(code, verifier) is None


def test_pkce_verifier_mismatch_rejected():
    import db
    u = db.get_or_create_user("wrongpkce@studio.com")
    code = db.issue_code(u["id"], "fake_challenge")
    assert db.consume_code(code, "any_verifier") is None


def test_token_issue_and_lookup():
    import db
    u = db.get_or_create_user("tokeneer@studio.com")
    token = db.issue_token(u["id"])
    assert token.startswith("ah_live_")
    found = db.user_for_token(token)
    assert found is not None
    assert found["id"] == u["id"]


def test_invalid_token_returns_none():
    import db
    assert db.user_for_token("ah_live_nonexistent") is None


def test_get_user_by_stripe_id():
    import db
    u = db.get_or_create_user("stripey@studio.com")
    db.update_user_plan(u["id"], plan="studio", stripe_id="cus_TEST123")
    found = db.get_user_by_stripe_id("cus_TEST123")
    assert found is not None
    assert found["email"] == "stripey@studio.com"
    assert found["plan"] == "studio"


def test_log_usage_writes_row():
    import db
    u = db.get_or_create_user("logger@studio.com")
    db.log_usage(u["id"], model="gpt-4o-mini",
                  input_toks=120, output_toks=44, cost_micros=18)
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM usage_log WHERE user_id = ?",
            (u["id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-4o-mini"
    assert rows[0]["input_toks"] == 120
    assert rows[0]["output_toks"] == 44
