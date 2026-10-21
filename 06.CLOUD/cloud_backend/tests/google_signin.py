"""Sign a test user in the only way a person signs in: Google.

Drives the REAL /v1/auth/google/start -> /v1/auth/google/callback ->
/auth/return -> /v1/auth/exchange routes. Only the two outbound calls to
Google (token exchange, id_token verification) are replaced, and the
replacement still runs the real google_auth._assert_claims trust gate.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse

CLIENT_ID = "test-client-id.apps.googleusercontent.com"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def use_google(monkeypatch, email: str, *, name: str | None = None) -> None:
    """Turn Google sign-in on with test credentials; Google vouches for `email`."""
    import config
    import google_auth
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "test-oauth-secret")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_REDIRECT",
                        config.PUBLIC_URL.rstrip("/") + "/v1/auth/google/callback")

    def exchange(code: str) -> dict:
        return {"id_token": "TEST.ID.TOKEN", "token_type": "Bearer"}

    def verify(id_token: str) -> dict:
        claims = {
            "iss": "https://accounts.google.com", "aud": CLIENT_ID,
            "sub": "sub-" + email, "email": email, "email_verified": True,
            "exp": int(time.time()) + 3600,
        }
        if name is not None:
            claims["name"] = name
        return google_auth._assert_claims(claims)

    monkeypatch.setattr(google_auth, "_exchange_code_for_tokens", exchange)
    monkeypatch.setattr(google_auth, "verify_id_token", verify)


def google_code(client, monkeypatch, email: str, *, challenge: str = "",
                name: str | None = None) -> str:
    """Run Google sign-in for `email`; return the one-time code it mints."""
    use_google(monkeypatch, email, name=name)
    started = client.get("/v1/auth/google/start",
                         params={"code_challenge": challenge})
    assert started.status_code == 200, started.text
    auth_url = started.json()["auth_url"]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)["state"][0]
    back = client.get("/v1/auth/google/callback",
                      params={"code": "google-code", "state": state},
                      follow_redirects=False)
    assert back.status_code == 302, back.text
    query = urllib.parse.parse_qs(urllib.parse.urlparse(back.headers["location"]).query)
    return query["code"][0]


def google_sign_in(client, monkeypatch, email: str, *,
                   name: str | None = None) -> str:
    """Google sign-in with a desktop PKCE pair; return the bearer token."""
    verifier, challenge = pkce_pair()
    code = google_code(client, monkeypatch, email, challenge=challenge, name=name)
    r = client.post("/v1/auth/exchange",
                    json={"code": code, "code_verifier": verifier})
    assert r.status_code == 200, r.text
    return r.json()["token"]