"""Auth helpers — magic-link register + PKCE code-exchange.

Flow:
  1. POST /v1/auth/register  { email }
     → server creates/loads user
     → emails the user a one-time `code` (5 min TTL) wrapped in a
        sign-in URL. The user clicks → desktop ArchHub catches the
        redirect on localhost and POSTs /v1/auth/exchange.
  2. POST /v1/auth/exchange  { code, code_verifier }
     → server checks the PKCE challenge stored alongside the code,
        deletes the code, issues a bearer token.
     → returns { token, expires_at, plan }

The desktop client generates the PKCE pair itself, sends the
challenge as part of the sign-in URL the user opens. The challenge
gets stored on the code row so verification at exchange time is
self-contained.
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Optional

import config
import db
import email_sender


async def register_via_email(*, email: str, code_challenge: str,
                              redirect: str = "") -> bool:
    """Create / load the user and email them a sign-in link.
    Returns True on accepted email.

    A brand-new account also gets the one-time welcome email (roadmap
    #P2 onboarding sequence) — detected BEFORE get_or_create_user
    creates the row, sent best-effort so it can never break sign-in."""
    is_new_user = db.get_user_by_email(email) is None
    user = db.get_or_create_user(email)
    code = db.issue_code(user["id"], code_challenge)
    # Build the sign-in link the user clicks. Loops back to their
    # desktop app via the redirect (loopback URL) the client sent.
    # If no redirect was provided (e.g. someone testing in a
    # browser), point them at the public dashboard.
    link_params = {"code": code}
    if redirect:
        link_params["redirect"] = redirect
    link = (
        f"{config.PUBLIC_URL.rstrip('/')}/auth/return?"
        + urllib.parse.urlencode(link_params)
    )
    ok = await email_sender.send_magic_link(to=email, link=link)
    if is_new_user:
        try:
            await email_sender.send_welcome_email(to=email)
        except Exception:
            pass   # welcome is best-effort — never fails the sign-in
    return ok


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
