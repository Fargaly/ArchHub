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
    Returns True on accepted email."""
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
    return await email_sender.send_magic_link(to=email, link=link)


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
    return {
        "token": token,
        # Bearer tokens are long-lived (90 days). Client refreshes by
        # re-running sign-in if expired; we don't surface a refresh
        # endpoint to keep the API surface tight.
        "expires_at": int(time.time()) + 90 * 24 * 3600,
        "plan": user["plan"],
    }
