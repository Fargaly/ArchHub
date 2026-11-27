from __future__ import annotations

import urllib.parse
import urllib.request
import json
import time

import pytest

NONCE = "desktop-nonce-000000000001"


def _social3_config(monkeypatch):
    import config
    for name in ("LINKEDIN_OAUTH_CLIENT_ID", "META_OAUTH_APP_ID", "X_OAUTH_CLIENT_ID", "TIKTOK_OAUTH_CLIENT_KEY"):
        monkeypatch.setattr(config, name, "fake-publisher-app", raising=False)
    for name in ("LINKEDIN_OAUTH_CLIENT_SECRET", "META_OAUTH_APP_SECRET", "X_OAUTH_CLIENT_SECRET", "TIKTOK_OAUTH_CLIENT_SECRET"):
        monkeypatch.setattr(config, name, "fake-cloud-secret", raising=False)
    monkeypatch.setattr(config, "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "fake-coexistence-config", raising=False)
    for provider in ("linkedin", "instagram", "facebook", "whatsapp", "x", "tiktok"):
        redirect = "https://api.archhub.io/oauth/" + provider + "/callback"
        monkeypatch.setattr(config, provider.upper() + "_OAUTH_REDIRECT", redirect, raising=False)
        monkeypatch.setattr(config, provider.upper() + "_OAUTH_REDIRECT_ALLOWLIST", frozenset({redirect}) if provider == "linkedin" else redirect, raising=False)
        monkeypatch.setattr(config, provider.upper() + "_OAUTH_REVIEW_PENDING", "", raising=False)


def _social3_start(client, provider, token):
    return client.get("/oauth/" + provider + "/start", params={
        "return_url": "http://127.0.0.1:48720/oauth/return", "nonce": NONCE + "-" + provider},
        headers={"Authorization": "Bearer " + token, "X-ArchHub-Device-Session": "social3-device"})


@pytest.mark.parametrize("provider,host,scope", [
    ("instagram", "www.facebook.com", "instagram_content_publish"),
    ("facebook", "www.facebook.com", "pages_manage_posts"),
    ("linkedin", "www.linkedin.com", "w_member_social"),
    ("whatsapp", "www.facebook.com", "whatsapp_business_messaging"),
    ("x", "x.com", "tweet.write"),
    ("tiktok", "www.tiktok.com", "video.publish"),
])
def test_social3_authorize_urls_and_one_time_fake_callback(client, monkeypatch, provider, host, scope):
    import hashlib
    import social_oauth
    _social3_config(monkeypatch)
    token = _token_for(provider + "@social3.test")
    started = _social3_start(client, provider, token)
    assert started.status_code == 200, started.text
    url = urllib.parse.urlsplit(started.json()["auth_url"])
    assert url.hostname == host
    query = urllib.parse.parse_qs(url.query)
    assert query["response_type"] == ["code"]
    assert scope in query["scope"][0]
    assert query["client_key" if provider == "tiktok" else "client_id"] == ["fake-publisher-app"]
    assert query["redirect_uri"] == ["https://api.archhub.io/oauth/" + provider + "/callback"]
    state = query["state"][0]
    if provider == "x":
        assert len(state) <= 500
        verifier = social_oauth._pkce(social_oauth._unsign(state))
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"] == [social_oauth._b64(hashlib.sha256(verifier.encode()).digest())]
        assert verifier not in state and verifier not in url.query
    if provider == "tiktok":
        assert "code_challenge" not in query  # TikTok's confidential Web flow.
        assert "," in query["scope"][0]
    if provider == "whatsapp":
        assert query["config_id"] == ["fake-coexistence-config"]
        assert json.loads(query["extras"][0])["featureType"] == "whatsapp_business_app_onboarding"
    monkeypatch.setattr(social_oauth, "_exchange", lambda *args: {"access_token": "fake-provider-token"})
    monkeypatch.setattr(social_oauth, "_profile", lambda *args: {"id": "12345", "sub": "person", "open_id": "tiktok-open-id", "username": "founder", "name": "Founder"})
    monkeypatch.setattr(social_oauth, "_pages", lambda token: {"data": [{"id": "6789", "name": "Page", "access_token": "fake-page-token"}]})
    monkeypatch.setattr(social_oauth, "_instagram", lambda *args: {"instagram_business_account": {"id": "9876", "username": "founder"}})
    callback = client.get("/oauth/" + provider + "/callback", params={"code": "fake-code", "state": state}, follow_redirects=False)
    assert callback.status_code == 302, callback.text
    assert "fake-provider-token" not in callback.headers["location"]
    grant = urllib.parse.parse_qs(urllib.parse.urlsplit(callback.headers["location"]).query)["grant"][0]
    headers = {"Authorization": "Bearer " + token, "X-ArchHub-Device-Session": "social3-device"}
    consumed = client.post("/oauth/" + provider + "/consume", json={"grant": grant}, headers=headers)
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["name"] == "founder"
    assert consumed.json()["access_token"] == "fake-provider-token"
    assert client.post("/oauth/" + provider + "/consume", json={"grant": grant}, headers=headers).status_code == 400
    assert client.get("/oauth/" + provider + "/callback", params={"code": "fake-code", "state": state}, follow_redirects=False).status_code == 400


@pytest.mark.parametrize("provider,label", [("instagram", "Meta"), ("facebook", "Meta"), ("linkedin", "LinkedIn"), ("whatsapp", "Meta"), ("x", "X"), ("tiktok", "TikTok")])
def test_social3_named_missing_app_and_review_blockers(client, monkeypatch, provider, label):
    import config
    _social3_config(monkeypatch)
    token = _token_for(provider + "-blocked@social3.test")
    identifier = "META_OAUTH_APP_ID" if provider in ("instagram", "facebook", "whatsapp") else "TIKTOK_OAUTH_CLIENT_KEY" if provider == "tiktok" else provider.upper() + "_OAUTH_CLIENT_ID"
    monkeypatch.setattr(config, identifier, "")
    missing = client.get("/oauth/" + provider + "/status", headers={"Authorization": "Bearer " + token}).json()
    assert missing["state"] == "missing"
    assert missing["blocker"] == label + " developer app not created (cloud client id missing)"
    monkeypatch.setattr(config, identifier, "fake-publisher-app")
    monkeypatch.setattr(config, provider.upper() + "_OAUTH_REVIEW_APPROVED", "1", raising=False)
    monkeypatch.setattr(config, provider.upper() + "_OAUTH_REVIEW_PENDING", "exact_publish_permission", raising=False)
    blocked = client.get("/oauth/" + provider + "/status", headers={"Authorization": "Bearer " + token}).json()
    assert blocked["state"] == "blocked"
    assert blocked["blocker"] == label + " app review: exact_publish_permission pending"
    assert blocked["review_state"] == "pending"
    assert blocked["publish_blocker"] == blocked["blocker"]
    assert _social3_start(client, provider, token).status_code == 503


def test_whatsapp_phone_identity_comes_from_granted_waba_not_pasted_id(monkeypatch):
    import social_oauth
    _social3_config(monkeypatch)
    def fake_graph(url, token):
        if "/debug_token?" in url:
            return {"data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["123"]}]}}
        assert "/123/phone_numbers?" in url and token == "fake-business-token"
        return {"data": [{"id": "456", "display_phone_number": "+123456"}]}
    monkeypatch.setattr(social_oauth, "_get_json", fake_graph)
    subscribed = []
    monkeypatch.setattr(social_oauth, "_post_bearer", lambda url, token: subscribed.append(url) or {"success": True})
    assert social_oauth._whatsapp_profile("fake-business-token") == {"id": "456", "name": "+123456"}
    assert subscribed == ["https://graph.facebook.com/v25.0/123/subscribed_apps"]


def test_whatsapp_never_guesses_between_multiple_granted_business_phones(monkeypatch):
    import social_oauth
    _social3_config(monkeypatch)
    def fake_graph(url, token):
        if "/debug_token?" in url:
            return {"data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["123", "789"]}]}}
        return {"data": [{"id": "456" if "/123/" in url else "987"}]}
    monkeypatch.setattr(social_oauth, "_get_json", fake_graph)
    with pytest.raises(social_oauth.SocialOAuthError, match="whatsapp_multiple_phone_numbers"):
        social_oauth._whatsapp_profile("fake-business-token")


def test_x_real_exchange_uses_basic_auth_and_pkce_verifier(monkeypatch):
    import contextlib
    import io
    import base64
    import social_oauth
    _social3_config(monkeypatch)
    monkeypatch.setattr(social_oauth, "_exchange", None)
    monkeypatch.setattr(social_oauth, "_profile", None)
    requests = []
    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/oauth2/token"):
            form = urllib.parse.parse_qs(request.data.decode())
            assert form["code_verifier"] == ["fake-per-attempt-verifier"]
            assert form["client_id"] == ["fake-publisher-app"]
            assert "client_secret" not in form
            assert request.get_header("Authorization") == "Basic " + base64.b64encode(b"fake-publisher-app:fake-cloud-secret").decode()
            payload = {"access_token": "fake-x-token", "scope": "tweet.read tweet.write users.read offline.access"}
        else:
            assert request.full_url == "https://api.x.com/2/users/me"
            assert request.get_header("Authorization") == "Bearer fake-x-token"
            payload = {"data": {"id": "12345", "username": "founder", "name": "Founder"}}
        return contextlib.closing(io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(social_oauth.urllib.request, "urlopen", fake_urlopen)
    grant = social_oauth.exchange_and_profile("x", "fake-code", verifier="fake-per-attempt-verifier")
    assert grant == {"provider": "x", "account_id": "12345", "name": "founder", "access_token": "fake-x-token"}
    assert len(requests) == 2


def test_tiktok_real_web_exchange_uses_client_key_and_nested_open_id(monkeypatch):
    import contextlib
    import io
    import social_oauth
    _social3_config(monkeypatch)
    monkeypatch.setattr(social_oauth, "_exchange", None)
    monkeypatch.setattr(social_oauth, "_profile", None)
    def fake_urlopen(request, timeout):
        if request.full_url == "https://open.tiktokapis.com/v2/oauth/token/":
            form = urllib.parse.parse_qs(request.data.decode())
            assert form["client_key"] == ["fake-publisher-app"]
            assert form["client_secret"] == ["fake-cloud-secret"]
            assert "client_id" not in form and "code_verifier" not in form
            payload = {"access_token": "fake-tiktok-token", "scope": "user.info.basic,video.publish,video.upload"}
        else:
            assert request.full_url.startswith("https://open.tiktokapis.com/v2/user/info/?fields=")
            assert request.get_header("Authorization") == "Bearer fake-tiktok-token"
            payload = {"data": {"user": {"open_id": "tiktok-open-id", "display_name": "founder"}}}
        return contextlib.closing(io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(social_oauth.urllib.request, "urlopen", fake_urlopen)
    grant = social_oauth.exchange_and_profile("tiktok", "fake-code")
    assert grant["account_id"] == "tiktok-open-id" and grant["name"] == "founder"


@pytest.mark.parametrize("denial", [False, True])
def test_provider_permission_failure_returns_nonce_bound_local_error_without_secrets(client, monkeypatch, denial):
    import social_oauth
    _social3_config(monkeypatch)
    token = _token_for("permission-failure@social3.test")
    started = _social3_start(client, "instagram", token).json()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(started["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange", lambda *args: {"access_token": "fake-secret-token", "scope": "instagram_basic"})
    answer = client.get("/oauth/instagram/callback", params={"state": state,
        **({"error": "access_denied", "error_description": "instagram_content_publish fake-secret-token"} if denial else {"code": "fake-code"})}, follow_redirects=False)
    assert answer.status_code == 302
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(answer.headers["location"]).query)
    assert query["provider"] == ["instagram"] and query["nonce"] == [NONCE + "-instagram"]
    assert "instagram_content_publish" in query["error"][0]
    assert "fake-secret-token" not in answer.headers["location"]
    assert "grant" not in query


def test_configured_app_does_not_claim_unverified_publishing_review(client, monkeypatch):
    import config
    _social3_config(monkeypatch)
    token = _token_for("review-unknown@social3.test")
    headers = {"Authorization": "Bearer " + token}
    monkeypatch.setattr(config, "INSTAGRAM_OAUTH_REVIEW_APPROVED", "", raising=False)
    answer = client.get("/oauth/instagram/status", headers=headers).json()
    assert answer["state"] == "configured" and answer["review_state"] == "unverified"
    assert answer["publish_blocker"] == "Meta app review: instagram_content_publish, instagram_manage_comments approval not verified"
    monkeypatch.setattr(config, "INSTAGRAM_OAUTH_REVIEW_APPROVED", "1", raising=False)
    assert "publish_blocker" not in client.get("/oauth/instagram/status", headers=headers).json()


def test_whatsapp_launch_serves_signed_sdk_coexistence_page_without_credentials(client, monkeypatch):
    _social3_config(monkeypatch)
    token = _token_for("embedded@social3.test")
    started = _social3_start(client, "whatsapp", token).json()
    # Installed desktops open only this cloud path; it forwards to Meta's own dialog (SDK-popup codes failed the
    # exchange with 100/36008, founder 2026-11-27).
    launch = urllib.parse.urlsplit(started["browser_url"])
    assert launch.path == "/oauth/whatsapp/embedded"
    page = client.get(launch.path + "?" + launch.query, follow_redirects=False)
    assert page.status_code == 302 and page.headers["cache-control"] == "no-store"
    dialog = urllib.parse.urlsplit(page.headers["location"])
    query = urllib.parse.parse_qs(dialog.query)
    assert dialog.netloc == "www.facebook.com" and dialog.path.endswith("/dialog/oauth")
    assert query["client_id"] == ["fake-publisher-app"] and query["config_id"] == ["fake-coexistence-config"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == ["https://api.archhub.io/oauth/whatsapp/callback"]
    assert query["state"] == urllib.parse.parse_qs(launch.query)["state"]
    assert "whatsapp_business_app_onboarding" in query["extras"][0]
    assert "fake-cloud-secret" not in page.headers["location"]
    assert client.get(launch.path, params={"state": "tampered-state"}).status_code == 400
    linkedin = _social3_start(client, "linkedin", token).json()
    wrong_state = urllib.parse.parse_qs(urllib.parse.urlsplit(linkedin["auth_url"]).query)["state"][0]
    assert client.get(launch.path, params={"state": wrong_state}).status_code == 400


def test_whatsapp_real_sdk_code_exchange_and_phone_discovery_use_fake_graph(monkeypatch):
    import contextlib
    import io
    import social_oauth
    _social3_config(monkeypatch)
    monkeypatch.setattr(social_oauth, "_exchange", None)
    monkeypatch.setattr(social_oauth, "_profile", None)
    monkeypatch.setattr(social_oauth, "_whatsapp", None)
    urls = []
    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        if request.full_url.endswith("/oauth/access_token"):
            form = urllib.parse.parse_qs(request.data.decode())
            assert form["client_id"] == ["fake-publisher-app"]
            assert form["client_secret"] == ["fake-cloud-secret"]
            assert form["code"] == ["sdk-business-code"]
            assert form["redirect_uri"] == ["https://api.archhub.io/oauth/whatsapp/callback"]  # same as the dialog's
            payload = {"access_token": "fake-business-token"}
        elif "/debug_token?" in request.full_url:
            assert request.get_header("Authorization") == "Bearer fake-publisher-app|fake-cloud-secret"
            payload = {"data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["123"]}]}}
        elif request.full_url.endswith("/123/subscribed_apps"):
            assert request.get_method() == "POST"
            assert request.get_header("Authorization") == "Bearer fake-business-token"
            payload = {"success": True}
        else:
            assert "/123/phone_numbers?" in request.full_url
            assert request.get_header("Authorization") == "Bearer fake-business-token"
            payload = {"data": [{"id": "456", "display_phone_number": "+123456"}]}
        return contextlib.closing(io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(social_oauth.urllib.request, "urlopen", fake_urlopen)
    grant = social_oauth.exchange_and_profile("whatsapp", "sdk-business-code")
    assert grant == {"provider": "whatsapp", "account_id": "456", "name": "+123456", "access_token": "fake-business-token"}
    assert len(urls) == 4


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import social_oauth
    with social_oauth._LOCK:
        social_oauth._STATES.clear()
        social_oauth._GRANTS.clear()
    # No test reaches Meta: the app webhook counts as registered and history-sync posts are recorded.
    monkeypatch.setattr(social_oauth, "_WEBHOOK_STATE", {"ok": True, "error": ""})
    monkeypatch.setattr(social_oauth, "_post_bearer", lambda url, token, body=None: {"success": True})
    social_oauth._exchange = None
    social_oauth._profile = None
    social_oauth._pages = None
    social_oauth._instagram = None
    return TestClient(main.app, base_url="https://testserver",
                      raise_server_exceptions=False)


def _token_for(address: str) -> str:
    import db
    return db.issue_token(db.get_or_create_user(address)["id"])


def test_linkedin_status_is_missing_until_cloud_publisher_app_is_configured(client):
    token = _token_for("social-owner@example.com")
    answer = client.get("/oauth/linkedin/status",
                        headers={"Authorization": "Bearer " + token})
    assert answer.status_code == 200
    assert answer.json() == {"ok": True, "provider": "linkedin", "state": "missing",
                             "blocker": "LinkedIn developer app not created (cloud client id missing)"}


def test_linkedin_start_uses_cloud_config_and_never_returns_secret(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_ID", "86abc123xyz")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT", "https://api.archhub.io/oauth/linkedin/callback")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/linkedin/callback"}))
    token = _token_for("social-owner@example.com")
    answer = client.get("/oauth/linkedin/start?return_url=http%3A%2F%2F127.0.0.1%3A48720%2Foauth%2Freturn&nonce=" + NONCE,
                        headers={"Authorization": "Bearer " + token,
                                 "X-ArchHub-Device-Session": "desktop-session-1"})
    assert answer.status_code == 200, answer.text
    payload = answer.json()
    assert payload["ok"] is True and payload["provider"] == "linkedin"
    assert "secret-value-1" not in str(payload)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(payload["auth_url"]).query)
    assert query["client_id"] == ["86abc123xyz"]
    assert query["redirect_uri"] == [config.LINKEDIN_OAUTH_REDIRECT]


def test_callback_returns_a_signed_grant_for_the_signed_in_user(client, monkeypatch):
    import config
    import social_oauth
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_ID", "86abc123xyz")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT", "https://api.archhub.io/oauth/linkedin/callback")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/linkedin/callback"}))
    token = _token_for("social-owner@example.com")
    started = client.get("/oauth/linkedin/start?return_url=http%3A%2F%2F127.0.0.1%3A48720%2Foauth%2Freturn&nonce=" + NONCE,
                         headers={"Authorization": "Bearer " + token,
                                  "X-ArchHub-Device-Session": "desktop-session-1"}).json()
    state = urllib.parse.parse_qs(
        urllib.parse.urlsplit(started["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange",
                        lambda provider, code, client_id, secret: {"access_token": "token-" + code})
    monkeypatch.setattr(social_oauth, "_profile",
                        lambda provider, token: {"sub": "founder-linkedin", "name": "Founder"})
    answer = client.get("/oauth/linkedin/callback?code=code-1&state=" + urllib.parse.quote(state),
                        follow_redirects=False)
    assert answer.status_code == 302
    location = answer.headers["location"]
    assert location.startswith("http://127.0.0.1:48720/oauth/return?")
    assert "secret-value-1" not in location and "token-code-1" not in location
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
    assert query["provider"] == ["linkedin"]
    assert query["account_id"] == ["urn:li:person:founder-linkedin"]
    assert query.get("grant")


def test_state_is_one_time_and_bound_to_desktop_session_before_token_release(client, monkeypatch):
    import config
    import social_oauth
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_ID", "86abc123xyz")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT", "https://api.archhub.io/oauth/linkedin/callback")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/linkedin/callback"}))
    token = _token_for("session-bound@example.com")
    started = client.get("/oauth/linkedin/start?return_url=http%3A%2F%2F127.0.0.1%3A48720%2Foauth%2Freturn&nonce=" + NONCE,
                         headers={"Authorization": "Bearer " + token,
                                  "X-ArchHub-Device-Session": "desktop-session-1"}).json()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(started["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange",
                        lambda provider, code, client_id, secret: {"access_token": "token-" + code})
    monkeypatch.setattr(social_oauth, "_profile",
                        lambda provider, token: {"sub": "founder-linkedin", "name": "Founder"})
    answer = client.get("/oauth/linkedin/callback?code=code-1&state=" + urllib.parse.quote(state),
                        follow_redirects=False)
    assert answer.status_code == 302
    again = client.get("/oauth/linkedin/callback?code=code-1&state=" + urllib.parse.quote(state),
                       follow_redirects=False)
    assert again.status_code == 400
    grant = urllib.parse.parse_qs(urllib.parse.urlsplit(answer.headers["location"]).query)["grant"][0]
    refused = client.post("/oauth/linkedin/consume", json={"grant": grant},
                          headers={"Authorization": "Bearer " + token,
                                   "X-ArchHub-Device-Session": "wrong-device"})
    assert refused.status_code == 400


def test_expired_state_is_refused_before_provider_exchange(client, monkeypatch):
    import config
    import db
    import social_oauth
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_ID", "86abc123xyz")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT", "https://api.archhub.io/oauth/linkedin/callback")
    token = _token_for("expired-state@example.com")
    started = client.get("/oauth/linkedin/start?return_url=http%3A%2F%2F127.0.0.1%3A48720%2Foauth%2Freturn&nonce=" + NONCE,
                         headers={"Authorization": "Bearer " + token,
                                  "X-ArchHub-Device-Session": "desktop-session-1"}).json()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(started["auth_url"]).query)["state"][0]
    with db.connect() as con:
        con.execute("UPDATE social_oauth_states SET expires_at = ? WHERE nonce = ?",
                    (int(time.time()) - 1, NONCE))
    monkeypatch.setattr(social_oauth, "_exchange",
                        lambda provider, code, client_id, secret: pytest.fail("expired state exchanged"))
    answer = client.get("/oauth/linkedin/callback?code=code-1&state=" + urllib.parse.quote(state),
                        follow_redirects=False)
    assert answer.status_code == 400
    assert "state_invalid" in answer.text


def test_desktop_consume_receives_provider_token_once_and_never_in_redirect(client, monkeypatch):
    import config
    import social_oauth
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_ID", "86abc123xyz")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT", "https://api.archhub.io/oauth/linkedin/callback")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/linkedin/callback"}))
    token = _token_for("token-device@example.com")
    started = client.get("/oauth/linkedin/start?return_url=http%3A%2F%2F127.0.0.1%3A48720%2Foauth%2Freturn&nonce=" + NONCE,
                         headers={"Authorization": "Bearer " + token,
                                  "X-ArchHub-Device-Session": "desktop-session-1"}).json()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(started["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange",
                        lambda provider, code, client_id, secret: {"access_token": "token-" + code})
    monkeypatch.setattr(social_oauth, "_profile",
                        lambda provider, token: {"sub": "founder-linkedin", "name": "Founder"})
    answer = client.get("/oauth/linkedin/callback?code=code-2&state=" + urllib.parse.quote(state),
                        follow_redirects=False)
    location = answer.headers["location"]
    assert "token-code-2" not in location
    grant = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["grant"][0]
    consumed = client.post("/oauth/linkedin/consume", json={"grant": grant},
                           headers={"Authorization": "Bearer " + token,
                                    "X-ArchHub-Device-Session": "desktop-session-1"})
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["access_token"] == "token-code-2"
    replay = client.post("/oauth/linkedin/consume", json={"grant": grant},
                         headers={"Authorization": "Bearer " + token,
                                  "X-ArchHub-Device-Session": "desktop-session-1"})
    assert replay.status_code == 400


def test_meta_callback_lists_pages_with_fake_graph_and_never_returns_page_tokens_to_ui(client, monkeypatch):
    import config
    import social_oauth
    monkeypatch.setattr(config, "META_OAUTH_APP_ID", "123456789012345")
    monkeypatch.setattr(config, "META_OAUTH_APP_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "META_OAUTH_REDIRECT", "https://api.archhub.io/oauth/meta/callback")
    monkeypatch.setattr(config, "META_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/meta/callback"}))
    token = _token_for("meta-owner@example.com")
    started = client.get("/oauth/meta/start?return_url=http%3A%2F%2F127.0.0.1%3A48721%2Foauth%2Freturn&nonce=" + NONCE,
                         headers={"Authorization": "Bearer " + token,
                                  "X-ArchHub-Device-Session": "desktop-session-1"}).json()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(started["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange",
                        lambda provider, code, client_id, secret: {"access_token": "EAAB-user-token"})
    monkeypatch.setattr(social_oauth, "_profile",
                        lambda provider, token: {"id": "123456789012345", "name": "Founder"})
    monkeypatch.setattr(social_oauth, "_pages",
                        lambda token: {"data": [{"id": "112233445566778", "name": "ArchHub Page",
                                                 "access_token": "EAAB-page-token",
                                                 "tasks": ["CREATE_CONTENT"]}]})
    monkeypatch.setattr(social_oauth, "_instagram",
                        lambda page_id, page_token: {
                            "instagram_business_account": {"id": "17841412345678901", "username": "archhub"}})
    answer = client.get("/oauth/meta/callback?code=code-1&state=" + urllib.parse.quote(state),
                        follow_redirects=False)
    assert answer.status_code == 302, answer.text
    location = answer.headers["location"]
    assert "EAAB-user-token" not in location and "EAAB-page-token" not in location
    grant = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["grant"][0]
    import db
    monkeypatch.setattr(social_oauth, "_MESSAGING_STATE", {"ok": False, "error": ""})
    graph = []
    monkeypatch.setattr(social_oauth, "_post_form", lambda url, form: graph.append((url, form)) or {"success": True})
    assert db.whatsapp_number_owner("112233445566778") is None  # not before the desktop takes the grant
    consumed = client.post("/oauth/meta/consume", json={"grant": grant},
                           headers={"Authorization": "Bearer " + token,
                                    "X-ArchHub-Device-Session": "desktop-session-1"})
    assert consumed.status_code == 200, consumed.text
    payload = consumed.json()
    assert payload["pages"] == [{"id": "112233445566778", "name": "ArchHub Page",
                                 "instagram": {"id": "17841412345678901", "username": "archhub"}}]
    assert "EAAB-page-token" not in json.dumps(payload["pages"])
    assert payload["page_secrets"]["112233445566778"]["page_token"] == "EAAB-page-token"
    # Messenger and Instagram DMs of the granted Page now route to this account.
    owner = db.user_for_token(token)["id"]
    assert db.whatsapp_number_owner("112233445566778") == owner
    assert db.whatsapp_number_owner("17841412345678901") == owner
    assert "receive_blocker" not in payload
    page_url, page_form = graph[0]
    assert page_url == "https://graph.facebook.com/v25.0/112233445566778/subscribed_apps"  # token in the body only
    assert page_form == {"subscribed_fields": "messages,message_echoes", "access_token": "EAAB-page-token"}
    hooks = {form["object"]: form for _url, form in graph[1:]}
    assert set(hooks) == {"page", "instagram"}
    assert all(form["callback_url"].endswith("/webhooks/meta") for form in hooks.values())
    assert hooks["instagram"]["fields"] == "messages"


def test_desktop_meta_broker_holds_page_token_until_selected_page_finish(tmp_path):
    from nodelang import cloud_social_oauth

    cloud_social_oauth._CURRENT.pop("meta", None)
    session = tmp_path / "cloud.json"
    session.write_text(json.dumps({"token": "cloud-bearer", "cloud_base_url": "https://cloud.example"}), encoding="utf-8")
    seen = {"return_url": "", "opened": ""}

    def fake_http(method, url, *, bearer, body=None, headers=None, timeout=10.0):
        assert bearer == "cloud-bearer"
        if method == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen["return_url"] = query["return_url"][0]
            assert query["nonce"][0]
            return 200, {"auth_url": "https://provider.example/meta"}
        assert method == "POST"
        return 200, {"account_id": "123456789012345", "access_token": "EAAB-user-token", "name": "Founder",
                     "pages": [{"id": "112233445566778", "name": "ArchHub Page",
                                "instagram": {"id": "17841412345678901", "username": "archhub"}}],
                     "page_secrets": {"112233445566778": {"page_token": "EAAB-page-token",
                                                          "instagram": {"id": "17841412345678901",
                                                                        "username": "archhub"},
                                                          "instagram_token": "EAAB-page-token"}}}

    payload = cloud_social_oauth.start("meta", path=session, http=fake_http,
                                       opener=lambda url: seen.__setitem__("opened", url))
    assert payload["phase"] in ("starting", "waiting")
    deadline = time.time() + 5
    while not seen["return_url"] and time.time() < deadline:
        time.sleep(0.02)
    urllib.request.urlopen(seen["return_url"] + "?provider=meta&grant=grant-from-cloud", timeout=5).read()
    deadline = time.time() + 5
    while cloud_social_oauth.current_status("meta").get("phase") != "ready" and time.time() < deadline:
        time.sleep(0.02)
    status = cloud_social_oauth.current_status("meta")
    assert status["pages"] == [{"id": "112233445566778", "name": "ArchHub Page",
                                "instagram": {"id": "17841412345678901", "username": "archhub"}}]
    assert "EAAB-page-token" not in json.dumps(status)
    from nodelang import social_meta_signin
    selected = social_meta_signin.take_verified_page("112233445566778")
    assert selected["page_token"] == "EAAB-page-token"
    assert selected["instagram_token"] == "EAAB-page-token"


def test_redirect_uri_must_be_allowlisted_before_authorize(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_ID", "86abc123xyz")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_CLIENT_SECRET", "secret-value-1")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT", "https://evil.example/oauth/linkedin/callback")
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/linkedin/callback"}))
    token = _token_for("redirect-owner@example.com")
    answer = client.get("/oauth/linkedin/start?return_url=http%3A%2F%2F127.0.0.1%3A48720%2Foauth%2Freturn&nonce=" + NONCE,
                        headers={"Authorization": "Bearer " + token,
                                 "X-ArchHub-Device-Session": "desktop-session-1"})
    assert answer.status_code == 400
    assert "redirect_not_allowed" in answer.text


def test_configured_redirect_allowlist_accepts_extra_uri_and_refuses_unlisted(monkeypatch):
    import config
    monkeypatch.setattr(config, "LINKEDIN_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/linkedin/callback",
                                   "https://staging.archhub.test/oauth/linkedin/callback"}))
    monkeypatch.setattr(config, "META_OAUTH_REDIRECT_ALLOWLIST",
                        frozenset({"https://api.archhub.io/oauth/meta/callback"}))
    assert config.social_oauth_redirect_allowed(
        "linkedin", "https://staging.archhub.test/oauth/linkedin/callback")
    assert config.social_oauth_redirect_allowed(
        "linkedin", "https://staging.archhub.test/oauth/linkedin/callback/")
    assert not config.social_oauth_redirect_allowed(
        "linkedin", "https://evil.example/oauth/linkedin/callback")
    assert not config.social_oauth_redirect_allowed(
        "meta", "https://staging.archhub.test/oauth/meta/callback")


def test_db_social_oauth_state_and_grant_consumes_are_one_time():
    import db
    user = db.get_or_create_user("one-time-social@example.com")
    digest = "sha256:" + "a" * 64
    db.issue_social_oauth_state(
        nonce="one-time-nonce",
        user_id=user["id"],
        device_id="desktop-session-1",
        session_digest=digest,
        provider="linkedin",
        return_url="http://127.0.0.1:48720/oauth/return",
        ttl_seconds=600,
    )
    first_state = db.consume_social_oauth_state(
        nonce="one-time-nonce",
        user_id=user["id"],
        device_id="desktop-session-1",
        provider="linkedin",
        now=111111,
    )
    second_state = db.consume_social_oauth_state(
        nonce="one-time-nonce",
        user_id=user["id"],
        device_id="desktop-session-1",
        provider="linkedin",
        now=111111,
    )
    assert first_state and second_state is None

    db.issue_social_oauth_grant(
        handle="one-time-grant",
        user_id=user["id"],
        device_id="desktop-session-1",
        session_digest=digest,
        provider="linkedin",
        account_id="urn:li:person:oneTime",
        name="One Time",
        encrypted_payload="encrypted-token-payload",
        ttl_seconds=300,
    )
    first_grant = db.consume_social_oauth_grant(
        handle="one-time-grant",
        user_id=user["id"],
        device_id="desktop-session-1",
        session_digest=digest,
        provider="linkedin",
        now=111111,
    )
    second_grant = db.consume_social_oauth_grant(
        handle="one-time-grant",
        user_id=user["id"],
        device_id="desktop-session-1",
        session_digest=digest,
        provider="linkedin",
        now=111111,
    )
    assert first_grant and second_grant is None


def test_desktop_start_creates_local_grant_consumer_and_holds_token_until_finish(tmp_path):
    from nodelang import cloud_social_oauth

    session = tmp_path / "cloud.json"
    session.write_text(json.dumps({"token": "cloud-bearer", "cloud_base_url": "https://cloud.example"}), encoding="utf-8")
    seen = {"return_url": "", "opened": ""}

    def fake_http(method, url, *, bearer, body=None, headers=None, timeout=10.0):
        assert bearer == "cloud-bearer"
        if method == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen["return_url"] = query["return_url"][0]
            assert query["nonce"][0]
            assert headers and headers.get("X-ArchHub-Device-Session")
            return 200, {"auth_url": "https://provider.example/authorize"}
        assert method == "POST"
        assert body == {"grant": "grant-from-cloud"}
        return 200, {"account_id": "urn:li:person:desktopUser", "access_token": "AQX-dev-tok", "name": "Desktop"}

    payload = cloud_social_oauth.start("linkedin", path=session, http=fake_http,
                                       opener=lambda url: seen.__setitem__("opened", url))
    assert payload["phase"] in ("starting", "waiting")
    deadline = time.time() + 5
    while not seen["return_url"] and time.time() < deadline:
        time.sleep(0.02)
    assert seen["opened"] == "https://provider.example/authorize"
    urllib.request.urlopen(seen["return_url"] + "?provider=linkedin&grant=grant-from-cloud", timeout=5).read()
    deadline = time.time() + 5
    while cloud_social_oauth.current_status("linkedin").get("phase") != "ready" and time.time() < deadline:
        time.sleep(0.02)
    from nodelang import social_linkedin_signin
    assert social_linkedin_signin.take_verified() == ("urn:li:person:desktopUser", "AQX-dev-tok")


# ------------------------------------------------ WhatsApp inbound webhook --

def _wa_post(client, body: dict, secret: str = "fake-cloud-secret"):
    import hashlib
    import hmac
    raw = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/whatsapp", content=raw,
                       headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature})


def _wa_body(number_id: str, sender: str, name: str, wamid: str, text: str, field: str = "messages") -> dict:
    value = {"messaging_product": "whatsapp",
             "metadata": {"display_phone_number": "+20 100 000 0000", "phone_number_id": number_id}}
    message = {"from": sender, "id": wamid, "timestamp": "1764000000", "type": "text", "text": {"body": text}}
    if field == "smb_message_echoes":
        value["message_echoes"] = [{**message, "from": "201000000000", "to": sender}]
    else:
        value["contacts"] = [{"profile": {"name": name}, "wa_id": sender}]
        value["messages"] = [message]
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": field, "value": value}]}]}


def test_whatsapp_webhook_verification_handshake_uses_derived_token(client, monkeypatch):
    import config
    import social_oauth
    _social3_config(monkeypatch)
    token = social_oauth.whatsapp_verify_token()
    assert token and "fake-cloud-secret" not in token
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "1158201444"})
    assert ok.status_code == 200 and ok.text == "1158201444"
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "1"}).status_code == 403
    monkeypatch.setattr(config, "META_OAUTH_APP_SECRET", "")
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "1"}).status_code == 503


def test_whatsapp_webhook_refuses_bad_or_missing_signature_and_stores_nothing(client, monkeypatch):
    import config
    import db
    _social3_config(monkeypatch)
    user = db.get_or_create_user("wa-sig@social3.test")
    db.link_whatsapp_number(phone_number_id="456", user_id=user["id"])
    body = _wa_body("456", "201111111111", "Contact", "wamid.sig", "hello")
    assert _wa_post(client, body, secret="wrong-secret").status_code == 403
    assert client.post("/webhooks/whatsapp", json=body).status_code == 403
    monkeypatch.setattr(config, "META_OAUTH_APP_SECRET", "")
    assert _wa_post(client, body).status_code == 503
    assert db.list_whatsapp_messages(user_id=user["id"]) == []


def test_whatsapp_ingest_then_read_filtered_by_sender_with_cursor(client, monkeypatch):
    import db
    _social3_config(monkeypatch)
    token = _token_for("wa-read@social3.test")
    user = db.user_for_token(token)
    db.link_whatsapp_number(phone_number_id="456", user_id=user["id"])
    for body in (_wa_body("456", "201111111111", "Sample Contact", "wamid.1", "first"),
                 _wa_body("456", "202222222222", "Someone Else", "wamid.2", "other"),
                 _wa_body("456", "201111111111", "Sample Contact", "wamid.3", "second"),
                 _wa_body("456", "201111111111", "", "wamid.4", "my reply", field="smb_message_echoes")):
        answer = _wa_post(client, body)
        assert answer.status_code == 200 and answer.json() == {"ok": True, "stored": 1}
    assert _wa_post(client, _wa_body("456", "201111111111", "x", "wamid.1", "first")).json()["stored"] == 0  # redelivery
    headers = {"Authorization": "Bearer " + token}
    by_name = client.post("/oauth/whatsapp/messages", json={"contact": "sample"}, headers=headers).json()
    assert [(m["text"], m["direction"]) for m in by_name["messages"]] == [("first", "in"), ("second", "in")]
    by_phone = client.post("/oauth/whatsapp/messages", json={"contact": "+20 111 111 1111"}, headers=headers).json()
    assert [m["text"] for m in by_phone["messages"]] == ["first", "second", "my reply"]
    after = client.post("/oauth/whatsapp/messages", json={"contact": "201111111111", "since": by_phone["messages"][0]["id"]}, headers=headers).json()
    assert [m["text"] for m in after["messages"]] == ["second", "my reply"]
    assert len(client.post("/oauth/whatsapp/messages", json={}, headers=headers).json()["messages"]) == 4
    assert client.post("/oauth/whatsapp/messages", json={}).status_code == 401
    assert client.post("/oauth/whatsapp/messages", json={"since": "0"}, headers=headers).status_code == 400


def test_whatsapp_messages_are_isolated_per_account_and_unlinked_numbers_dropped(client, monkeypatch):
    import db
    _social3_config(monkeypatch)
    owner, other = _token_for("wa-owner@social3.test"), _token_for("wa-other@social3.test")
    db.link_whatsapp_number(phone_number_id="456", user_id=db.user_for_token(owner)["id"])
    db.link_whatsapp_number(phone_number_id="789", user_id=db.user_for_token(other)["id"])
    assert _wa_post(client, _wa_body("456", "201111111111", "A", "wamid.a", "for owner")).json()["stored"] == 1
    assert _wa_post(client, _wa_body("789", "201111111111", "A", "wamid.b", "for other")).json()["stored"] == 1
    assert _wa_post(client, _wa_body("999", "201111111111", "A", "wamid.c", "nobody")).json()["stored"] == 0
    read = lambda token: [m["text"] for m in client.post("/oauth/whatsapp/messages", json={}, headers={"Authorization": "Bearer " + token}).json()["messages"]]
    assert read(owner) == ["for owner"]
    assert read(other) == ["for other"]


def test_whatsapp_consume_links_the_phone_number_to_the_signed_in_account(client, monkeypatch):
    import db
    import social_oauth
    _social3_config(monkeypatch)
    token = _token_for("wa-link@social3.test")
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(_social3_start(client, "whatsapp", token).json()["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange", lambda *args: {"access_token": "fake-business-token"})
    monkeypatch.setattr(social_oauth, "_profile", lambda *args: {"id": "456", "name": "+123456"})
    location = client.get("/oauth/whatsapp/callback", params={"code": "c", "state": state}, follow_redirects=False).headers["location"]
    grant = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["grant"][0]
    assert db.whatsapp_number_owner("456") is None  # not before the desktop takes the grant
    consumed = client.post("/oauth/whatsapp/consume", json={"grant": grant},
                           headers={"Authorization": "Bearer " + token, "X-ArchHub-Device-Session": "social3-device"})
    assert consumed.status_code == 200
    assert db.whatsapp_number_owner("456") == db.user_for_token(token)["id"]


def test_whatsapp_status_registers_the_app_webhook_once_without_founder_steps(client, monkeypatch):
    import social_oauth
    _social3_config(monkeypatch)
    monkeypatch.setattr(social_oauth, "_WEBHOOK_STATE", {"ok": False, "error": ""})
    calls = []
    monkeypatch.setattr(social_oauth, "_post_form", lambda url, form: calls.append((url, form)) or {"success": True})
    headers = {"Authorization": "Bearer " + _token_for("wa-hook@social3.test")}
    first = client.get("/oauth/whatsapp/status", headers=headers).json()
    assert first["webhook_url"].startswith("https://") and first["webhook_url"].endswith("/webhooks/whatsapp")
    assert "receive_blocker" not in first
    url, form = calls[0]
    assert url == "https://graph.facebook.com/v25.0/fake-publisher-app/subscriptions"
    assert "fake-cloud-secret" not in url  # the app token rides in the body only
    assert form["object"] == "whatsapp_business_account"
    assert form["callback_url"] == first["webhook_url"]
    assert form["verify_token"] == social_oauth.whatsapp_verify_token()
    assert set(form["fields"].split(",")) == {"messages", "smb_message_echoes", "history"}
    assert form["access_token"] == "fake-publisher-app|fake-cloud-secret"
    client.get("/oauth/whatsapp/status", headers=headers)
    assert len(calls) == 1  # idempotent: registered once per process


def test_whatsapp_webhook_registration_failure_is_a_status_line_without_secrets(client, monkeypatch, caplog):
    import io
    import urllib.error
    import social_oauth
    _social3_config(monkeypatch)
    monkeypatch.setattr(social_oauth, "_WEBHOOK_STATE", {"ok": False, "error": ""})
    calls = []

    def refused(url, form):
        calls.append(url)
        body = json.dumps({"error": {"code": 100, "message": "bad token fake-cloud-secret"}}).encode()
        raise urllib.error.HTTPError(url + "?access_token=fake-cloud-secret", 400, "Bad Request", {}, io.BytesIO(body))
    monkeypatch.setattr(social_oauth, "_post_form", refused)
    headers = {"Authorization": "Bearer " + _token_for("wa-hook-fail@social3.test")}
    with caplog.at_level("WARNING"):
        answer = client.get("/oauth/whatsapp/status", headers=headers).json()
    assert answer["receive_blocker"] == "WhatsApp webhook not registered: Meta answered HTTP 400"
    assert "fake-cloud-secret" not in json.dumps(answer) and "fake-cloud-secret" not in caplog.text
    assert "Meta answered HTTP 400" in caplog.text
    client.get("/oauth/whatsapp/status", headers=headers)
    assert len(calls) == 2  # a failure is retried on the next status read
    monkeypatch.setattr(social_oauth, "_post_form", lambda url, form: {"success": True})
    assert "receive_blocker" not in client.get("/oauth/whatsapp/status", headers=headers).json()


def test_whatsapp_consume_requests_coexistence_history_and_survives_refusal(client, monkeypatch):
    import urllib.error
    import social_oauth
    _social3_config(monkeypatch)
    sent = []
    monkeypatch.setattr(social_oauth, "_post_bearer", lambda url, token, body=None: sent.append((url, token, body)) or {"success": True})
    token = _token_for("wa-history@social3.test")
    headers = {"Authorization": "Bearer " + token, "X-ArchHub-Device-Session": "social3-device"}
    monkeypatch.setattr(social_oauth, "_exchange", lambda *args: {"access_token": "fake-business-token"})
    monkeypatch.setattr(social_oauth, "_profile", lambda *args: {"id": "456", "name": "+123456"})

    def connect():
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(_social3_start(client, "whatsapp", token).json()["auth_url"]).query)["state"][0]
        location = client.get("/oauth/whatsapp/callback", params={"code": "c", "state": state}, follow_redirects=False).headers["location"]
        grant = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["grant"][0]
        return client.post("/oauth/whatsapp/consume", json={"grant": grant}, headers=headers)

    assert connect().status_code == 200
    assert sent == [("https://graph.facebook.com/v25.0/456/smb_app_data", "fake-business-token",
                     {"messaging_product": "whatsapp", "sync_type": kind}) for kind in ("smb_app_state_sync", "history")]

    def refused(url, token, body=None):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(social_oauth, "_post_bearer", refused)
    assert connect().status_code == 200  # the connection stands when Meta refuses history sync


# ------------------------------------- Messenger + Instagram inbound webhook --

def _dm_body(obj: str, account: str, sender: str, mid: str, text: str, echo: bool = False) -> dict:
    message = {"mid": mid, "text": text, **({"is_echo": True} if echo else {})}
    party = {"sender": {"id": account if echo else sender}, "recipient": {"id": sender if echo else account}}
    return {"object": obj, "entry": [{"id": account, "time": 1764000000000, "messaging": [
        {**party, "timestamp": 1764000000123, "message": message},
        {**party, "timestamp": 1764000000456, "read": {"mid": mid}}]}]}  # a read receipt is not a message


def _meta_post(client, body: dict, secret: str = "fake-cloud-secret"):
    import hashlib
    import hmac
    raw = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/meta", content=raw,
                       headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature})


def test_meta_webhook_verifies_and_refuses_bad_signature_for_messenger(client, monkeypatch):
    import db
    import social_oauth
    _social3_config(monkeypatch)
    token = social_oauth.whatsapp_verify_token()
    ok = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    user = db.get_or_create_user("dm-sig@social3.test")
    db.link_whatsapp_number(phone_number_id="5550001", user_id=user["id"], network="messenger")
    body = _dm_body("page", "5550001", "7770001", "m_sig", "hello")
    assert _meta_post(client, body, secret="wrong-secret").status_code == 403
    assert client.post("/webhooks/meta", json=body).status_code == 403
    assert db.list_whatsapp_messages(user_id=user["id"]) == []


def test_messenger_and_instagram_ingest_and_network_filter_keep_whatsapp_default(client, monkeypatch):
    import db
    _social3_config(monkeypatch)
    token = _token_for("dm-read@social3.test")
    user = db.user_for_token(token)
    db.link_whatsapp_number(phone_number_id="456", user_id=user["id"])
    db.link_whatsapp_number(phone_number_id="5550001", user_id=user["id"], network="messenger")
    db.link_whatsapp_number(phone_number_id="17840001", user_id=user["id"], network="instagram")
    assert _wa_post(client, _wa_body("456", "201111111111", "Sample Contact", "wamid.1", "on whatsapp")).json()["stored"] == 1
    assert _meta_post(client, _dm_body("page", "5550001", "7770001", "m_1", "on messenger")).json() == {"ok": True, "stored": 1}
    assert _meta_post(client, _dm_body("page", "5550001", "7770001", "m_2", "page reply", echo=True)).json()["stored"] == 1
    assert _meta_post(client, _dm_body("instagram", "17840001", "8880001", "ig_1", "on instagram")).json()["stored"] == 1
    assert _meta_post(client, _dm_body("instagram", "17840001", "8880001", "ig_1", "on instagram")).json()["stored"] == 0  # redelivery
    headers = {"Authorization": "Bearer " + token}
    read = lambda **f: client.post("/oauth/whatsapp/messages", json=f, headers=headers).json()["messages"]
    # No network = the WhatsApp-only answer it gave before.
    assert [(m["text"], m["network"]) for m in read()] == [("on whatsapp", "whatsapp")]
    assert [(m["text"], m["direction"], m["contact"], m["sent_at"]) for m in read(network="messenger")] == [
        ("on messenger", "in", "7770001", 1764000000), ("page reply", "out", "7770001", 1764000000)]
    assert [m["text"] for m in read(network="instagram")] == ["on instagram"]
    assert [m["network"] for m in read(network="all")] == ["whatsapp", "messenger", "messenger", "instagram"]
    assert [m["text"] for m in read(network="all", contact="8880001")] == ["on instagram"]
    assert client.post("/oauth/whatsapp/messages", json={"network": "telegram"}, headers=headers).status_code == 400


def test_messenger_and_instagram_messages_are_isolated_per_account(client, monkeypatch):
    import db
    _social3_config(monkeypatch)
    owner, other = _token_for("dm-owner@social3.test"), _token_for("dm-other@social3.test")
    db.link_whatsapp_number(phone_number_id="5550002", user_id=db.user_for_token(owner)["id"], network="messenger")
    db.link_whatsapp_number(phone_number_id="17840002", user_id=db.user_for_token(other)["id"], network="instagram")
    assert _meta_post(client, _dm_body("page", "5550002", "7770002", "m_a", "for owner")).json()["stored"] == 1
    assert _meta_post(client, _dm_body("instagram", "17840002", "8880002", "ig_b", "for other")).json()["stored"] == 1
    assert _meta_post(client, _dm_body("page", "5559999", "7770002", "m_c", "nobody")).json()["stored"] == 0
    read = lambda token: [m["text"] for m in client.post("/oauth/whatsapp/messages", json={"network": "all"},
                                                         headers={"Authorization": "Bearer " + token}).json()["messages"]]
    assert read(owner) == ["for owner"]
    assert read(other) == ["for other"]


# ------------------------------------------------ account sync: connections (D-051) --

def _sync_headers(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def _x_record(token: str = "x-access-1") -> dict:
    return {"format": "archhub-social-credential-2", "provider": "x", "account_id": "101",
            "token": token, "account_binding": "provider-verified", "display_name": "Studio X"}


def _sync_put(client, token: str, path: str, content: bytes | None, base: str = ""):
    import base64
    import gzip
    body = {"logical_path": path, "base_sha256": base, "device_id": "pc-a"}
    body.update({"deleted": True} if content is None else
                {"content_b64": base64.b64encode(gzip.compress(content)).decode()})
    return client.put("/v1/account-sync/item", json=body, headers=_sync_headers(token))


def _sync_user(token: str) -> str:
    import db
    return db.user_for_token(token)["id"]


def test_account_connections_are_per_account_encrypted_and_listed_without_tokens(client, monkeypatch):
    import account_sync
    import brain_replica
    monkeypatch.setattr(account_sync, "_KEY_CACHE", None)
    owner, other = _token_for("sync-owner@sync.test"), _token_for("sync-other@sync.test")
    stored = _sync_put(client, owner, "connections/social-x-101.json", account_sync.canonical(_x_record()))
    assert stored.status_code == 200, stored.text
    listed = client.get("/v1/account-sync/manifest", headers=_sync_headers(owner)).json()
    assert [row["logical_path"] for row in listed["items"]] == ["connections/social-x-101.json"]
    assert "x-access-1" not in json.dumps(listed)
    # At rest under the account's replica folder: ciphertext only.
    root = brain_replica.DEFAULT_REPLICAS_ROOT / _sync_user(owner) / "account_sync"
    assert not any(b"x-access-1" in path.read_bytes() for path in root.rglob("*") if path.is_file())
    # Another account sees nothing and cannot read it.
    assert client.get("/v1/account-sync/manifest", headers=_sync_headers(other)).json()["items"] == []
    assert client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(other)).status_code == 404
    sha = stored.json()["sha256"]
    assert client.get("/v1/account-sync/blob/" + sha, params={"logical_path": "connections/social-x-101.json"},
                      headers=_sync_headers(other)).status_code == 404
    opened = client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(owner)).json()
    assert opened["record"]["token"] == "x-access-1"
    # Removing it from the account (a tombstone) stops every PC from resolving it.
    assert _sync_put(client, owner, "connections/social-x-101.json", None, sha).status_code == 200
    removed = client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(owner))
    assert removed.status_code == 410 and removed.json() == {"removed": True}
    # Never stored is not "removed": a plain 404.
    assert client.post("/v1/account-sync/connection/social-x-999", headers=_sync_headers(owner)).status_code == 404
    assert client.get("/v1/account-sync/manifest").status_code == 401


def test_account_sync_refuses_credentials_outside_connections(client):
    token = _token_for("sync-nokey@sync.test")
    refused = _sync_put(client, token, "settings/router.json", b'{"key": "sk-live-looking"}')
    assert refused.status_code == 400 and "refuses_credentials" in refused.text


def test_connection_key_is_random_on_the_cloud_and_survives_restart_and_secret_rotation(client, monkeypatch):
    import os
    import account_sync
    import brain_replica
    import config
    monkeypatch.setattr(account_sync, "_KEY_CACHE", None)
    monkeypatch.setattr(config, "SOCIAL_OAUTH_STATE_SECRET", "state-secret-1")
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "google-secret-1")
    token = _token_for("sync-key@sync.test")
    assert _sync_put(client, token, "connections/social-x-101.json", account_sync.canonical(_x_record())).status_code == 200
    key_file = account_sync._key_path()
    held = key_file.read_bytes()
    assert key_file.is_file() and brain_replica.DEFAULT_REPLICAS_ROOT not in key_file.parents
    assert b"secret-1" not in held
    if os.name != "nt":
        assert key_file.stat().st_mode & 0o777 == 0o600
    # A restart (empty cache) with every OAuth secret rotated or gone still opens the stored connection.
    monkeypatch.setattr(account_sync, "_KEY_CACHE", None)
    monkeypatch.setattr(config, "GOOGLE_OAUTH_CLIENT_SECRET", "google-secret-2")
    monkeypatch.setattr(config, "SOCIAL_OAUTH_STATE_SECRET", "")
    opened = client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(token))
    assert opened.status_code == 200 and opened.json()["record"]["token"] == "x-access-1"
    assert key_file.read_bytes() == held and b"secret" not in opened.content


def test_a_lost_key_shows_needs_reconnect_never_a_wrong_decrypt_and_a_reupload_heals(client, monkeypatch):
    import account_sync
    monkeypatch.setattr(account_sync, "_KEY_CACHE", None)
    token = _token_for("sync-lost@sync.test")
    assert _sync_put(client, token, "connections/social-x-101.json", account_sync.canonical(_x_record())).status_code == 200
    # The data volume lost the key file: the cloud makes a new key at next use.
    account_sync._key_path().unlink()
    monkeypatch.setattr(account_sync, "_KEY_CACHE", None)
    listed = client.get("/v1/account-sync/manifest", headers=_sync_headers(token)).json()["items"]
    assert [(row["logical_path"], row.get("needs_reconnect")) for row in listed] == [("connections/social-x-101.json", True)]
    refused = client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(token))
    assert refused.status_code == 409 and "connection_needs_reconnect" in refused.text and "x-access-1" not in refused.text
    # A PC that still holds the connection uploads it again: healed under the new key, nothing dropped.
    assert _sync_put(client, token, "connections/social-x-101.json", account_sync.canonical(_x_record())).status_code == 200
    assert "needs_reconnect" not in client.get("/v1/account-sync/manifest", headers=_sync_headers(token)).json()["items"][0]
    assert client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(token)).json()["record"]["token"] == "x-access-1"


def test_consume_keeps_the_grant_on_the_account_and_refreshes_it_server_side(client, monkeypatch):
    import account_sync
    import social_oauth
    monkeypatch.setattr(account_sync, "_KEY_CACHE", None)
    _social3_config(monkeypatch)
    token = _token_for("sync-consume@sync.test")
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(_social3_start(client, "x", token).json()["auth_url"]).query)["state"][0]
    monkeypatch.setattr(social_oauth, "_exchange", lambda *args: {
        "access_token": "x-access-1", "refresh_token": "x-refresh-1", "expires_in": 7200})
    monkeypatch.setattr(social_oauth, "_profile", lambda *args: {"data": {"id": "101", "username": "studio"}})
    location = client.get("/oauth/x/callback", params={"code": "c", "state": state}, follow_redirects=False).headers["location"]
    grant = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["grant"][0]
    consumed = client.post("/oauth/x/consume", json={"grant": grant},
                           headers={"Authorization": "Bearer " + token, "X-ArchHub-Device-Session": "social3-device"})
    assert consumed.status_code == 200 and "x-refresh-1" not in consumed.text
    listed = client.get("/v1/account-sync/manifest", headers=_sync_headers(token)).json()["items"]
    assert [row["logical_path"] for row in listed] == ["connections/social-x-101.json"]
    user_id = _sync_user(token)
    assert account_sync._held_refresh(user_id, "social-x-101")["refresh_token"] == "x-refresh-1"
    # The desktop re-uploading the same record keeps the cloud-held refresh token.
    record = json.loads(account_sync.read_item(user_id, "connections/social-x-101.json")[1])
    assert _sync_put(client, token, "connections/social-x-101.json", account_sync.canonical(record)).status_code == 200
    assert account_sync._held_refresh(user_id, "social-x-101")["refresh_token"] == "x-refresh-1"
    # Due for refresh: the cloud refreshes and serves the new token, never the refresh token.
    account_sync._keep_refresh(user_id, "social-x-101", {**account_sync._held_refresh(user_id, "social-x-101"), "expires_at": 1})
    calls = []
    monkeypatch.setattr(account_sync, "_refresher", lambda provider, refresh: calls.append((provider, refresh)) or {
        "access_token": "x-access-2", "refresh_token": "x-refresh-2", "expires_in": 7200})
    opened = client.post("/v1/account-sync/connection/social-x-101", headers=_sync_headers(token))
    assert opened.status_code == 200 and calls == [("x", "x-refresh-1")]
    assert opened.json()["record"]["token"] == "x-access-2" and "refresh" not in opened.text
    assert account_sync._held_refresh(user_id, "social-x-101")["refresh_token"] == "x-refresh-2"
    assert json.loads(account_sync.read_item(user_id, "connections/social-x-101.json")[1])["token"] == "x-access-2"


def test_whatsapp_number_found_through_businesses_when_meta_skips_the_number_step(monkeypatch):
    # Founder 2026-11-27: Meta answered "has been connected to ArchHub" with no target ids; no number linked.
    import social_oauth
    _social3_config(monkeypatch)
    def fake_graph(url, token):
        if "/debug_token?" in url:
            return {"data": {"granular_scopes": [{"scope": "whatsapp_business_management"}]}}
        if "/me/businesses?" in url:
            return {"data": [{"id": "111"}]}
        if "/111/owned_whatsapp_business_accounts?" in url:
            return {"data": [{"id": "123"}]}
        if "/111/client_whatsapp_business_accounts?" in url:
            return {"data": []}
        assert "/123/phone_numbers?" in url
        return {"data": [{"id": "456", "display_phone_number": "+123456"}]}
    monkeypatch.setattr(social_oauth, "_get_json", fake_graph)
    subscribed = []
    monkeypatch.setattr(social_oauth, "_post_bearer", lambda url, token: subscribed.append(url) or {"success": True})
    assert social_oauth._whatsapp_profile("fake-business-token") == {"id": "456", "name": "+123456"}
    assert subscribed == ["https://graph.facebook.com/v25.0/123/subscribed_apps"]
