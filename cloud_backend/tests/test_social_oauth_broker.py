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
    assert social_oauth._whatsapp_profile("fake-business-token") == {"id": "456", "name": "+123456"}


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
    launch = urllib.parse.urlsplit(started["browser_url"])
    assert launch.path == "/oauth/whatsapp/embedded"
    page = client.get(launch.path + "?" + launch.query)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    html = page.text
    assert 'src="https://connect.facebook.net/en_US/sdk.js"' in html
    assert '"appId":"fake-publisher-app"' in html
    assert '"configId":"fake-coexistence-config"' in html
    assert "FB.init(" in html and "FB.login(" in html
    assert "response_type: 'code'" in html and "override_default_response_type: true" in html
    assert "featureType: 'whatsapp_business_app_onboarding'" in html
    assert "target.searchParams.set('state', settings.state)" in html
    assert "target.searchParams.set('code', code)" in html
    assert '"callback":"https://api.archhub.io/oauth/whatsapp/callback"' in html
    assert "fake-cloud-secret" not in html and "fake-provider-token" not in html
    assert "<input" not in html
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
            assert "redirect_uri" not in form
            payload = {"access_token": "fake-business-token"}
        elif "/debug_token?" in request.full_url:
            assert request.get_header("Authorization") == "Bearer fake-publisher-app|fake-cloud-secret"
            payload = {"data": {"granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["123"]}]}}
        else:
            assert "/123/phone_numbers?" in request.full_url
            assert request.get_header("Authorization") == "Bearer fake-business-token"
            payload = {"data": [{"id": "456", "display_phone_number": "+123456"}]}
        return contextlib.closing(io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(social_oauth.urllib.request, "urlopen", fake_urlopen)
    grant = social_oauth.exchange_and_profile("whatsapp", "sdk-business-code")
    assert grant == {"provider": "whatsapp", "account_id": "456", "name": "+123456", "access_token": "fake-business-token"}
    assert len(urls) == 3


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    import social_oauth
    with social_oauth._LOCK:
        social_oauth._STATES.clear()
        social_oauth._GRANTS.clear()
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
    consumed = client.post("/oauth/meta/consume", json={"grant": grant},
                           headers={"Authorization": "Bearer " + token,
                                    "X-ArchHub-Device-Session": "desktop-session-1"})
    assert consumed.status_code == 200, consumed.text
    payload = consumed.json()
    assert payload["pages"] == [{"id": "112233445566778", "name": "ArchHub Page",
                                 "instagram": {"id": "17841412345678901", "username": "archhub"}}]
    assert "EAAB-page-token" not in json.dumps(payload["pages"])
    assert payload["page_secrets"]["112233445566778"]["page_token"] == "EAAB-page-token"


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
