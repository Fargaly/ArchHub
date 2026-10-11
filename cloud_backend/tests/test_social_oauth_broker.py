from __future__ import annotations

import urllib.parse
import urllib.request
import json
import time

import pytest

NONCE = "desktop-nonce-000000000001"


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
    assert answer.json() == {"ok": True, "provider": "linkedin", "state": "missing"}


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
