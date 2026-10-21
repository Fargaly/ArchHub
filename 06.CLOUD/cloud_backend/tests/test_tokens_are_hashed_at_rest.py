"""Courts: bearer tokens are kept only as a digest at rest.

A copy of the cloud database must hold no usable session: the tokens
table keeps SHA-256 digests, and rows written before that (raw
"ah_live_..." values) are hashed in place so nobody is signed out.
"""
from __future__ import annotations

import time


def _stored_tokens():
    import db
    with db.connect() as con:
        return [row["token"] for row in con.execute("SELECT token FROM tokens")]


def test_a_new_token_is_stored_only_as_its_digest():
    import db
    user = db.get_or_create_user("digest@studio.com")
    token = db.issue_token(user["id"])
    stored = _stored_tokens()
    assert token not in stored
    assert stored == ["sha256:" + __import__("hashlib").sha256(token.encode()).hexdigest()]
    assert db.user_for_token(token)["id"] == user["id"]
    assert db.user_for_token(stored[0]) is None, "the digest is not a bearer"


def test_a_plaintext_token_from_before_is_hashed_in_place_and_still_signs_in():
    import db
    user = db.get_or_create_user("longtime@studio.com")
    legacy = "ah_live_" + "L" * 43
    now = int(time.time())
    with db.connect() as con:
        con.execute(
            "INSERT INTO tokens (token, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (legacy, user["id"], now, now + db.TOKEN_TTL_SECONDS))
    db.init_schema()
    db.init_schema()  # idempotent: a second boot changes nothing
    stored = _stored_tokens()
    assert legacy not in stored and len(stored) == 1
    assert db.user_for_token(legacy)["id"] == user["id"], "nobody is signed out"
    assert db.delete_token(legacy) is True
    assert db.user_for_token(legacy) is None