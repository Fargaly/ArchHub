"""Sign in with LinkedIn gives a provider-verified account, never a typed one.

A fake LinkedIn plays both sides: the browser (it calls the loopback with the code and
the exact state) and the provider (token exchange, /v2/userinfo). No network is used.
"""
import socket
import threading
import time
import urllib.parse
import urllib.request

import pytest

from nodelang import model_router
from nodelang import social_linkedin_signin as signin
from nodelang.universal_application import _APPLICATION_HTTP_ROUTE_SPECS


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _browser(state_override=None, error=None):
    """Stand in for the browser: follow the consent URL straight to the loopback."""
    def opener(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        back = {"state": state_override or query["state"]}
        back.update({"error": error} if error else {"code": "code-123"})
        time.sleep(0.2)
        try:
            urllib.request.urlopen(query["redirect_uri"] + "?" + urllib.parse.urlencode(back), timeout=5).read()
        except Exception:
            pass
    return opener


def _run(**options):
    seen = {}

    def form(url, body):
        seen["form"] = (url, dict(body))
        return options.pop("token_answer", (200, {"access_token": "AQX-token", "expires_in": 5184000}))

    def bearer(url, token):
        seen["bearer"] = (url, token)
        return options.pop("userinfo_answer", (200, {"sub": "782bbtaQ", "name": "Ahmed F"}))

    attempt = signin.LinkedInSignIn("86abc123xyz", "secret-value-1", form=form, bearer=bearer,
                                    port=_free_port(), wait_seconds=options.pop("wait", 5),
                                    opener=options.pop("opener", _browser())).start()
    attempt.thread.join(timeout=10)
    return attempt, seen


def test_the_account_is_the_one_linkedin_names_and_the_token_is_taken_once():
    attempt, seen = _run()
    status = attempt.status()
    assert status["phase"] == "ready" and status["account_id"] == "urn:li:person:782bbtaQ"
    assert "AQX-token" not in repr(status), "the token never appears in status"
    url, form = seen["form"]
    assert url == signin.TOKEN_URL and form["grant_type"] == "authorization_code" and form["code"] == "code-123"
    assert form["redirect_uri"] == attempt.redirect_uri and form["client_id"] == "86abc123xyz"
    assert seen["bearer"] == (signin.USERINFO_URL, "AQX-token")
    assert attempt.take() == ("urn:li:person:782bbtaQ", "AQX-token")
    with pytest.raises(RuntimeError):
        attempt.take()


def test_a_forged_state_is_refused_and_nothing_is_exchanged():
    attempt, seen = _run(opener=_browser(state_override="forged"), wait=1.5)
    assert attempt.status()["phase"] == "failed" and "form" not in seen


def test_a_denied_consent_a_refused_code_or_an_unnamed_account_enrolls_nothing():
    denied, seen = _run(opener=_browser(error="user_cancelled_login"))
    assert denied.status()["phase"] == "failed" and "form" not in seen
    refused, _ = _run(token_answer=(401, {"error": "invalid_grant"}))
    assert refused.status()["phase"] == "failed"
    unnamed, _ = _run(userinfo_answer=(200, {"sub": "bad sub!"}))
    assert unnamed.status()["phase"] == "failed"
    for attempt in (denied, refused, unnamed):
        with pytest.raises(RuntimeError):
            attempt.take()


def test_the_redirect_is_fixed_because_linkedin_matches_it_exactly():
    assert signin.REDIRECT_URI == "http://127.0.0.1:48720/linkedin/callback"
    assert signin.SCOPES.split() == ["openid", "profile", "w_member_social"]


def test_the_linkedin_app_is_kept_protected_and_its_secret_never_returned(monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    saved = model_router.save_linkedin_app({"client_id": "86abc123xyz", "client_secret": "secret-value-1"})
    assert saved == {"ok": True, "state": "saved", "client_id": "86abc123xyz", "source": "secrets store"}
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    assert model_router.linkedin_app() == ("86abc123xyz", "secret-value-1")
    for bad in ({"client_id": "x", "client_secret": "secret-value-1"}, {"client_id": "86abc123xyz", "client_secret": "a b"}):
        with pytest.raises(model_router.ProviderCredentialError):
            model_router.save_linkedin_app(bad)


def test_only_a_provider_named_account_is_recorded_as_verified(monkeypatch):
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put({}))
    body = {"vault_entry": "social-linkedin-782bbtaQ", "provider": "linkedin",
            "account_id": "urn:li:person:782bbtaQ", "token": "AQX-token"}
    assert model_router.save_social_credential(dict(body))["account_binding"] == "operator-declared"
    assert model_router.save_social_credential(dict(body), verified=True)["account_binding"] == "provider-verified"


def test_the_settings_routes_are_declared_for_every_graph():
    declared = {(method, path) for method, path, _ in _APPLICATION_HTTP_ROUTE_SPECS}
    for route in (("POST", "/api/universal/social-linkedin-app"), ("GET", "/api/universal/social-linkedin-signin"),
                  ("POST", "/api/universal/social-linkedin-signin"), ("POST", "/api/universal/social-linkedin-finish")):
        assert route in declared, route

def test_settings_offers_linkedin_sign_in_and_the_page_never_holds_the_token():
    from pathlib import Path
    studio = Path(signin.__file__).resolve().parent / "studio"
    page = (studio / "studio-lm.jsx").read_text(encoding="utf-8")
    transport = (studio / "studio-existing-workshop.js").read_text(encoding="utf-8")
    assert "<SettingsLinkedInSignIn transport={transport}/>" in page
    assert "post('/api/universal/social-linkedin-app', {client_id, client_secret})" in transport
    assert "post('/api/universal/social-linkedin-signin', {})" in transport
    assert "get('/api/universal/social-linkedin-signin')" in transport
    assert "post('/api/universal/social-linkedin-finish', {})" in transport, "finish sends no token"
    assert "result.account_binding !== 'provider-verified'" in transport

# -- v2: the loopback listener (review items 2 and 3) and the stored binding (item 4) --
def _waiting(attempt, seconds=5.0):
    deadline = time.monotonic() + seconds
    while attempt.status()["phase"] == "starting" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert attempt.status()["phase"] == "waiting", attempt.status()
    return urllib.parse.urlsplit(attempt.redirect_uri).port


def test_no_other_socket_can_bind_the_callback_port_while_the_attempt_holds_it():
    attempt = signin.LinkedInSignIn("86abc123xyz", "secret-value-1", port=_free_port(), wait_seconds=30,
                                    opener=lambda url: None).start()
    try:
        port = _waiting(attempt)
        intruder = socket.socket()
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            with pytest.raises(OSError):
                intruder.bind(("127.0.0.1", port))
        finally:
            intruder.close()
    finally:
        attempt.cancel()
        attempt.thread.join(timeout=10)


def test_a_silent_connection_cannot_stall_the_one_callback():
    """A local process connects and sends nothing; LinkedIn's real redirect still lands."""
    held = []

    def opener(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        port = urllib.parse.urlsplit(query["redirect_uri"]).port
        silent = socket.create_connection(("127.0.0.1", port), timeout=5)
        held.append(silent)                       # stays open, sends nothing
        time.sleep(0.3)
        back = urllib.parse.urlencode({"state": query["state"], "code": "code-123"})
        try:
            urllib.request.urlopen(query["redirect_uri"] + "?" + back, timeout=signin.READ_SECONDS + 10).read()
        except Exception:
            pass

    attempt, _ = _run(opener=opener, wait=signin.READ_SECONDS + 20)
    try:
        attempt.thread.join(timeout=signin.READ_SECONDS + 15)
        assert attempt.status()["phase"] == "ready", attempt.status()
    finally:
        for sock in held:
            sock.close()


def test_cancel_ends_the_wait_and_frees_the_port():
    attempt = signin.LinkedInSignIn("86abc123xyz", "secret-value-1", port=_free_port(), wait_seconds=60,
                                    opener=lambda url: None).start()
    port = _waiting(attempt)
    attempt.cancel()
    attempt.thread.join(timeout=5)
    assert attempt.status()["phase"] == "failed" and attempt.status()["error"] == "cancelled"
    with socket.socket() as again:
        again.bind(("127.0.0.1", port))
    with pytest.raises(signin.LinkedInNotReady):
        attempt.take()


def test_the_verified_binding_is_stored_with_the_token_and_read_back_by_custody(monkeypatch):
    import json as _json
    from nodelang import social_custody
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    verified = {"vault_entry": "social-linkedin-782bbtaQ", "provider": "linkedin",
                "account_id": "urn:li:person:782bbtaQ", "token": "AQX-token"}
    model_router.save_social_credential(dict(verified), verified=True)
    record = _json.loads(entries["social-linkedin-782bbtaQ"])
    assert record["format"] == "archhub-social-credential-2" and record["account_binding"] == "provider-verified"
    declared = dict(verified, vault_entry="social-linkedin-declared")
    model_router.save_social_credential(declared)
    assert "account_binding" not in _json.loads(entries["social-linkedin-declared"]), "declared stays format 1"
    read = lambda name: social_custody.social_account_binding(provider="linkedin", account_id="urn:li:person:782bbtaQ",
                                                              vault_entry=name)
    assert read("social-linkedin-782bbtaQ") == "provider-verified"
    assert read("social-linkedin-declared") == "operator-declared"
    assert social_custody.social_credential(provider="linkedin", account_id="urn:li:person:782bbtaQ",
                                            vault_entry="social-linkedin-782bbtaQ") == "AQX-token"


def test_a_wildcard_listener_on_the_same_port_never_receives_the_callback():
    """Windows lets another socket bind 0.0.0.0 on this port; LinkedIn redirects to
    127.0.0.1, which the more specific listener (this attempt) receives."""
    intruders = []

    def opener(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        port = urllib.parse.urlsplit(query["redirect_uri"]).port
        intruder = socket.socket()
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            intruder.bind(("0.0.0.0", port))
            intruder.listen(5)
            intruder.settimeout(0.5)
            intruders.append(intruder)
        except OSError:
            intruder.close()                  # this platform refuses the wildcard bind outright
        back = urllib.parse.urlencode({"state": query["state"], "code": "code-123"})
        time.sleep(0.2)
        try:
            urllib.request.urlopen(query["redirect_uri"] + "?" + back, timeout=5).read()
        except Exception:
            pass

    attempt, seen = _run(opener=opener)
    try:
        assert attempt.status()["phase"] == "ready" and seen["form"][1]["code"] == "code-123"
        for intruder in intruders:
            with pytest.raises(socket.timeout):
                intruder.accept()
    finally:
        for intruder in intruders:
            intruder.close()


# -- v2.1 ------------------------------------------------------------------------------------
def test_a_port_already_held_by_another_socket_fails_closed_and_opens_nothing():
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    opened = []
    try:
        attempt = signin.LinkedInSignIn("86abc123xyz", "secret-value-1", port=squatter.getsockname()[1],
                                        wait_seconds=5, opener=opened.append).start()
        attempt.thread.join(timeout=5)
        status = attempt.status()
        assert status["phase"] == "failed" and "busy" in status["error"], status
        assert opened == [], "LinkedIn's consent page is never opened toward someone else's listener"
    finally:
        squatter.close()


def test_status_never_reports_the_consent_url_or_its_state():
    attempt = signin.LinkedInSignIn("86abc123xyz", "secret-value-1", port=_free_port(), wait_seconds=30,
                                    opener=lambda url: None).start()
    try:
        _waiting(attempt)
        status = attempt.status()
        assert "url" not in status and not any("state=" in str(value) for value in status.values()), status
    finally:
        attempt.cancel()
        attempt.thread.join(timeout=10)
