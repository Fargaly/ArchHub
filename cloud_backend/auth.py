"""Auth helpers: the PKCE code exchange that finishes a Google sign-in.

Google (google_auth.py) is the only human sign-in. Its callback mints a
one-time `code` bound to the caller's PKCE challenge; then:

  POST /v1/auth/exchange  { code, code_verifier }
     -> server checks the PKCE challenge stored alongside the code,
        deletes the code, issues a bearer token.
     -> returns { token, expires_at, plan }

The desktop client generates the PKCE pair itself and sends the
challenge to /v1/auth/google/start. The challenge is stored on the code
row so verification at exchange time is self-contained.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import db

# Every account joins one Community Brain (founder decision 2026-09-29: auto-join,
# shared by default). Only what a device releases to the community lake reaches
# it -- published skills and behaviour patterns; client and firm facts never do
# (nodelang.cell_brain_governance). An empty ARCHHUB_DEFAULT_COMMUNITY_ID turns
# the auto-join off.
DEFAULT_COMMUNITY_ID = "archhub-community"
DEFAULT_COMMUNITY_OWNER = "archhub-platform"


def default_community_id() -> str:
    return os.environ.get("ARCHHUB_DEFAULT_COMMUNITY_ID", DEFAULT_COMMUNITY_ID).strip()


def provision_brain(user_id: str) -> Optional[str]:
    """Ensure the user has a cloud brain replica + record the link.

    MAKE-IT-REAL (founder 2026-05-31): closes the gap where signup created
    a `users` row but no brain — the per-user replica only appeared lazily
    on the first /v1/brain/sync. Called from exchange_code the moment a user
    becomes real + authenticated, so EVERY account has a brain slot from
    first login.

    Two effects, both idempotent:
      1. BrainReplica.open(user_id) creates <replicas_root>/<user_id>/brain.db
         (open() already mkdirs + ensures schema — a returning user just
         re-opens the existing replica, no error, no duplicate).
      2. db.set_user_brain_id stamps users.brain_id = user_id (the replica
         identity), making the account→brain link explicit + queryable. A
         returning user whose brain_id is already set is a no-op.

    Returns the brain_id on success, None if provisioning failed. Failure is
    swallowed + logged (never breaks sign-in) — but note the brain_id column
    is ALSO backfilled by db.init_schema, so the link survives even a
    transient replica-open hiccup; the next sync re-creates the dir lazily.
    """
    if not user_id:
        return None
    try:
        import brain_replica
        replica = brain_replica.BrainReplica.open(user_id)
        brain_id = replica.user_id   # == user_id (replica dir is keyed on it)
        db.set_user_brain_id(user_id, brain_id)
        community = default_community_id()
        if community and not db.has_community_optout(community, user_id):
            # INSERT OR IGNORE: a returning user keeps the row they have. A member
            # who left is never re-added by signing in again.
            db.add_community_member(community, user_id, role="member",
                                    owner_pub=DEFAULT_COMMUNITY_OWNER)
        else:
            # Auto-join turned off: the default membership ends at next sign-in.
            db.remove_community_member(DEFAULT_COMMUNITY_ID, user_id)
        return brain_id
    except Exception as ex:   # pragma: no cover - defensive, see note above
        import sys
        print(f"auth.provision_brain: could not provision brain for "
              f"{user_id!r}: {ex}", file=sys.stderr)
        return None


def exchange_code(*, code: str, code_verifier: str
                   ) -> Optional[dict]:
    """Verify PKCE + issue token. Returns the auth response payload
    or None if anything fails."""
    user_id = db.consume_code(code, code_verifier)
    if user_id is None:
        return None
    token = db.issue_token(user_id)
    user = db.get_user(user_id)
    if user is None:
        return None
    # The user is now real + authenticated → guarantee they have a brain
    # slot (per-user replica dir + users.brain_id link). Idempotent: a
    # returning user re-opens their existing replica without duplication.
    provision_brain(user_id)
    return {
        "token": token,
        # Bearer tokens are long-lived (90 days) AND server-side
        # enforced: db.issue_token stamped tokens.expires_at to the
        # same created_at + TOKEN_TTL_SECONDS window. We surface that
        # exact horizon to the client so its cached expiry matches the
        # server's — no drift, no immortal tokens. Client refreshes by
        # re-running sign-in once expired (no refresh endpoint, to keep
        # the API surface tight).
        "expires_at": int(time.time()) + db.TOKEN_TTL_SECONDS,
        "plan": user["plan"],
    }


def logout(*, token: str, all_sessions: bool = False) -> dict:
    """Revoke the caller's bearer token. POST /v1/auth/logout backs this.

    - all_sessions=False (default): revoke just THIS token — the
      current session signs out, other devices stay signed in.
    - all_sessions=True: revoke every token the user holds — "sign out
      of all devices" / post-compromise kill switch.

    Returns {ok, revoked} where `revoked` is the count of tokens
    removed. Idempotent: logging out an already-dead token is ok:true,
    revoked:0 (the desired end-state — token is gone — already holds).
    """
    user = db.user_for_token(token)
    if all_sessions and user is not None:
        revoked = db.delete_tokens_for_user(user["id"])
    else:
        revoked = 1 if db.delete_token(token) else 0
    return {"ok": True, "revoked": revoked}
