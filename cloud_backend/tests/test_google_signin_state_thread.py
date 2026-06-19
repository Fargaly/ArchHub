"""STATE-THREADING verification for Sign in with Google.

Bug this proves fixed: the desktop client's GoogleSignInWorker generates a
CSRF `state`, sets it as its loopback server's `expected_state`, and sends it
to GET /v1/auth/google/start?...&state=<state>. The loopback callback handler
(app/cloud_auth.py _CallbackHandler.do_GET) REJECTS the final redirect when
`state != expected_state` ("Security state mismatch. Please retry from the
app."). The backend used to DROP that client state entirely - it never put it
into the signed state and never echoed it on the final /auth/return redirect -
so the loopback always saw `?code=...` with no `state` and refused every Google
sign-in.

The fix threads the client's `state` through the backend's SIGNED state (so it
is tamper-proof - only trusted after the HMAC verifies) and echoes it on the
final loopback redirect. BOTH CSRF layers stay intact:
  * backend signed-state CSRF (backend <-> Google) - unchanged, still verified.
  * client echoed-state CSRF (client <-> loopback) - now actually delivered.

These tests assert (additively, without weakening any existing check):
  (a) a client `state` passed to build_authorization_url round-trips through
      encode_state -> decode_state as `app_state`;
  (b) exchange_callback includes `state=<app_state>` in the returned
      /auth/return URL when the (verified) signed state carried one;
  (c) a signed state WITHOUT app_state still works (magic-link compat) and the
      return URL omits `state` - i.e. the change is purely additive.

It reuses the SAME monkeypatched-Google + real-_assert_claims pattern as the
adversarial / verify suites (the signing of state goes through the genuine
HMAC encode/decode helpers - no signature is bypassed).
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse

import pytest


TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
TEST_CLIENT_SECRET = "test-oauth-client-secret-value"
EMAIL = "ahmed.fargaly98@gmail.com"
REDIRECT_BASE = "https://archhub-cloud.fly.dev"
REDIRECT_URI = REDIRECT_BASE + "/v1/auth/google/callback"


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


@pytest.fixture()
def google_env(monkeypatch):
    """Turn Google login ON with test creds (config read at call time)."""
    import config
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", TEST_CLIENT_SECRET)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_REDIRECT", REDIRECT_URI)
    monkeypatch.setattr(config, "PUBLIC_URL", REDIRECT_BASE)
    assert config.google_login_enabled() is True
    return config


@pytest.fixture()
def patched_google(monkeypatch, google_env):
    """Monkeypatch the two outbound-to-Google calls to a VALID token, routing
    the claims through the REAL _assert_claims gate (never around it)."""
    import google_auth
    captured = {}

    def fake_exchange(code: str) -> dict:
        captured["exchanged_code"] = code
        return {"id_token": "FAKE.VALID.IDTOKEN", "token_type": "Bearer"}

    def fake_verify(id_token: str) -> dict:
        captured["verified_id_token"] = id_token
        return google_auth._assert_claims({
            "iss": "https://accounts.google.com",
            "aud": TEST_CLIENT_ID,
            "sub": "1234567890",
            "email": EMAIL,
            "email_verified": "true",
            "exp": int(time.time()) + 3600,
        })

    monkeypatch.setattr(google_auth, "_exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(google_auth, "verify_id_token", fake_verify)
    return captured


@pytest.fixture()
def client(google_env):
    from fastapi.testclient import TestClient
    import main
    # Do NOT follow the 302 - inspect the Location (it carries code + state).
    return TestClient(main.app, follow_redirects=False)


def _decode_state_payload(state: str) -> dict:
    body = state.partition(".")[0]
    pad = "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))


# ===========================================================================
# (a) app_state round-trips encode_state -> decode_state (unit-level)
# ===========================================================================
class TestAppStateRoundTrips:
    def test_encode_decode_carries_app_state(self, google_env):
        """A client state passed as app_state survives the signed-state
        round-trip and is recovered verbatim by decode_state."""
        import google_auth
        app_state = secrets.token_urlsafe(16)
        state = google_auth.encode_state(
            code_challenge="cc", redirect="http://127.0.0.1:9/cb",
            app_state=app_state)
        payload = google_auth.decode_state(state)
        assert payload["as"] == app_state
        # The pre-existing fields are still carried unchanged.
        assert payload["cc"] == "cc"
        assert payload["rd"] == "http://127.0.0.1:9/cb"

    def test_build_authorization_url_threads_app_state_into_signed_state(
            self, google_env):
        """build_authorization_url(app_state=...) must pack it into the SAME
        signed `state` query param Google echoes back - verified under the
        real HMAC gate, so it is tamper-proof."""
        import google_auth
        app_state = "client-csrf-" + secrets.token_urlsafe(8)
        _, challenge = _pkce_pair()
        url = google_auth.build_authorization_url(
            code_challenge=challenge,
            redirect="http://127.0.0.1:53111/cb",
            app_state=app_state)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        signed_state = qs["state"][0]
        # The app_state rides INSIDE the verified payload (only trusted after
        # the signature verifies) - decode_state proves the HMAC holds.
        payload = google_auth.decode_state(signed_state)
        assert payload["as"] == app_state
        assert payload["cc"] == challenge
        # The app_state is NOT a separate cleartext query param - it lives only
        # inside the signed state (Google's `state` is the backend signed one).
        assert "app_state" not in qs
        assert "as" not in qs

    def test_app_state_default_empty_and_omitted_from_payload(self, google_env):
        """No app_state supplied -> decode_state reports "" (magic-link compat).
        Backward-compat: an OLD state (no `as` key) also decodes to "".
        """
        import google_auth
        # New encode without app_state.
        state = google_auth.encode_state(code_challenge="cc", redirect="rd")
        assert google_auth.decode_state(state).get("as", "") == ""
        # Simulate a legacy/foreign signed state that never had an `as` key but
        # is otherwise validly signed: build the payload then sign it the same
        # way encode_state does, so the HMAC still verifies.
        import hmac as _hmac
        import hashlib as _hashlib
        payload = {"cc": "cc", "rd": "rd", "n": "abc",
                   "exp": int(time.time()) + 600}
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"),
                       sort_keys=True).encode()).rstrip(b"=").decode()
        sig = _hmac.new(TEST_CLIENT_SECRET.encode("utf-8"),
                        body.encode("ascii"), _hashlib.sha256).digest()
        legacy = body + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        assert google_auth.decode_state(legacy).get("as", "") == ""


# ===========================================================================
# (b) exchange_callback echoes state=<app_state> on the /auth/return URL
# ===========================================================================
class TestCallbackEchoesAppState:
    def test_exchange_callback_includes_state_when_app_state_present(
            self, google_env, patched_google):
        """When the signed state carries app_state, the /auth/return URL the
        callback builds includes state=<app_state> so the desktop loopback's
        expected_state CSRF check passes."""
        import google_auth
        app_state = "loopback-state-" + secrets.token_urlsafe(8)
        signed = google_auth.encode_state(
            code_challenge="cc", redirect="http://127.0.0.1:53682/cb",
            app_state=app_state)
        return_url = google_auth.exchange_callback(code="g-code", state=signed)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(return_url).query)
        assert q.get("state") == [app_state]
        assert q.get("redirect") == ["http://127.0.0.1:53682/cb"]
        assert q.get("code") and q["code"][0]

    def test_full_callback_route_forwards_state_to_loopback(
            self, client, patched_google):
        """End-to-end through the real /v1/auth/google/start + callback routes:
        the client `state` query param given to /start is echoed back on the
        final /auth/return redirect's `state` - the property whose absence
        produced 'Security state mismatch'."""
        client_state = secrets.token_urlsafe(16)
        _, challenge = _pkce_pair()
        desktop_redirect = "http://127.0.0.1:53682/cb"
        # Step 1: /start WITH the client state (as GoogleSignInWorker sends).
        r1 = client.get("/v1/auth/google/start", params={
            "code_challenge": challenge,
            "redirect": desktop_redirect,
            "state": client_state,
        })
        assert r1.status_code == 200, r1.text
        signed_state = urllib.parse.parse_qs(
            urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
        # The signed state carries the client state inside the verified payload.
        assert _decode_state_payload(signed_state)["as"] == client_state
        # Step 2: Google redirects back to the callback with the signed state.
        r2 = client.get("/v1/auth/google/callback", params={
            "code": "google-code", "state": signed_state,
        })
        assert r2.status_code == 302, r2.text
        loc = urllib.parse.urlparse(r2.headers["location"])
        assert loc.path == "/auth/return", r2.headers["location"]
        ret_qs = urllib.parse.parse_qs(loc.query)
        # The FINAL redirect to the desktop loopback carries the SAME state the
        # client set as expected_state -> the loopback CSRF check passes.
        assert ret_qs.get("state") == [client_state], r2.headers["location"]
        assert ret_qs.get("redirect") == [desktop_redirect]
        assert ret_qs.get("code") and ret_qs["code"][0]


# ===========================================================================
# (c) magic-link compat: no app_state -> return URL omits state (additive)
# ===========================================================================
class TestNoAppStateMagicLinkCompat:
    def test_callback_without_app_state_omits_state_in_return_url(
            self, google_env, patched_google):
        """A signed state WITHOUT app_state (the pre-fix shape / a Google flow
        where the client sent no state) still works and the /auth/return URL
        does NOT add a `state` param - proving the change is additive and the
        magic-link finisher behaviour is unchanged."""
        import google_auth
        signed = google_auth.encode_state(
            code_challenge="cc", redirect="http://127.0.0.1:7/cb")
        return_url = google_auth.exchange_callback(code="g-code", state=signed)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(return_url).query)
        assert "state" not in q, return_url
        assert q.get("redirect") == ["http://127.0.0.1:7/cb"]
        assert q.get("code") and q["code"][0]

    def test_start_without_state_param_has_empty_app_state(
            self, client, patched_google):
        """Hitting /start with NO state query param yields a signed state whose
        app_state is empty, and the callback's /auth/return omits state."""
        _, challenge = _pkce_pair()
        r1 = client.get("/v1/auth/google/start", params={
            "code_challenge": challenge,
            "redirect": "http://127.0.0.1:7/cb",
        })
        signed_state = urllib.parse.parse_qs(
            urllib.parse.urlparse(r1.json()["auth_url"]).query)["state"][0]
        assert _decode_state_payload(signed_state).get("as", "") == ""
        r2 = client.get("/v1/auth/google/callback", params={
            "code": "g-code", "state": signed_state,
        })
        assert r2.status_code == 302, r2.text
        q = urllib.parse.parse_qs(
            urllib.parse.urlparse(r2.headers["location"]).query)
        assert "state" not in q, r2.headers["location"]
