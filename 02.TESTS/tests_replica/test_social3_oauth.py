"""Six provider desktop callbacks use only fake broker HTTP and loopback."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request

import pytest

from nodelang import cloud_social_oauth as oauth


@pytest.mark.parametrize("provider,account", [
    ("instagram", "9876"), ("facebook", "6789"),
    ("linkedin", "urn:li:person:12345"), ("whatsapp", "12345"),
    ("x", "12345"), ("tiktok", "tiktok-open-id"),
])
def test_six_fake_cloud_callbacks_hold_target_token_for_single_custody_consume(monkeypatch, provider, account):
    monkeypatch.setattr(oauth, "_session", lambda path: ("fake-cloud-session", "https://fake-broker.test"))
    monkeypatch.setattr(oauth, "_CURRENT", {})
    seen = {}

    def fake_http(method, url, *, bearer, body=None, headers=None, timeout=10):
        assert bearer == "fake-cloud-session"
        assert headers["X-ArchHub-Device-Session"]
        if method == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen["return"] = query["return_url"][0]
            assert query["nonce"][0]
            return 200, {"auth_url": "https://provider-signin.test/" + provider}
        assert body == {"grant": "fake-grant"}
        return 200, {"account_id": account, "name": "founder", "access_token": "fake-provider-token",
                     "pages": [{"id": "6789", "name": "founder", "instagram": {"id": "9876", "username": "founder"}}],
                     "page_secrets": {"6789": {"page_token": "fake-page-token", "instagram_token": "fake-ig-token"}}}

    def fake_browser(url):
        assert url == "https://provider-signin.test/" + provider
        with urllib.request.urlopen(seen["return"] + "?provider=" + provider + "&grant=fake-grant", timeout=3) as response:
            assert response.status == 200

    oauth.start(provider, http=fake_http, opener=fake_browser)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        current = oauth.current_status(provider)
        if current["phase"] in ("ready", "failed"):
            break
        time.sleep(0.01)
    assert current["phase"] == "ready", current
    assert current["name"] == "founder" and current["account_id"] == account
    assert "fake-provider-token" not in str(current)
    account_id, credential = oauth.take_verified(provider)
    assert account_id == account
    assert credential == {"instagram": "fake-ig-token", "facebook": "fake-page-token"}.get(provider, "fake-provider-token")
    assert oauth.current_status(provider)["name"] == "founder"
    with pytest.raises(oauth.SocialGrantNotReady):
        oauth.take_verified(provider)


@pytest.mark.parametrize("provider", ["instagram", "facebook"])
def test_multiple_discovered_accounts_require_an_explicit_provider_choice(provider):
    attempt = oauth.CloudSocialAttempt(provider, "fake-session", "https://fake-broker.test")
    attempt._state.update(phase="select_account")
    attempt._pages = {
        "123": {"id": "123", "name": "Page One", "instagram": {"id": "456", "username": "first"}},
        "789": {"id": "789", "name": "Page Two", "instagram": {"id": "987", "username": "second"}},
    }
    attempt._page_secrets = {"123": {"page_token": "page-one", "instagram_token": "ig-one"},
                             "789": {"page_token": "page-two", "instagram_token": "ig-two"}}
    with pytest.raises(oauth.SocialGrantNotReady):
        attempt.take()
    with pytest.raises(oauth.SocialGrantNotReady):
        attempt.select_account("not-a-provider-discovered-id")
    assert attempt.select_account("987" if provider == "instagram" else "789") == (
        ("987", "ig-two") if provider == "instagram" else ("789", "page-two"))
    assert not attempt._page_secrets


@pytest.mark.parametrize("provider", ["instagram", "facebook", "linkedin", "whatsapp", "x", "tiktok"])
def test_cloud_configuration_blocker_is_visible_and_does_not_open_browser(monkeypatch, provider):
    monkeypatch.setattr(oauth, "_session", lambda path: ("fake-session", "https://fake-broker.test"))
    result = oauth.status(provider, http=lambda *args, **kwargs: (200, {
        "state": "blocked", "blocker": provider + " app review: publish_permission pending"}))
    assert result == {"state": "blocked", "blocker": provider + " app review: publish_permission pending"}
    result = oauth.status(provider, http=lambda *args, **kwargs: (200, {
        "state": "blocked", "blocker": provider + " app review: publish_permission pending",
        "publish_blocker": provider + " app review: publish_permission pending", "review_state": "pending"}))
    assert result["review_state"] == "pending"
    assert result["publish_blocker"] == result["blocker"]
    opened = []
    attempt = oauth.CloudSocialAttempt(provider, "fake-session", "https://fake-broker.test", opener=opened.append,
        http=lambda *args, **kwargs: (503, {"detail": {"blocker": provider + " developer app not created"}}))
    attempt._run()
    assert attempt.status()["error"] == provider + " developer app not created"
    assert opened == []


def test_nonce_bound_provider_denial_reaches_desktop_without_timeout(monkeypatch):
    import urllib.error
    monkeypatch.setattr(oauth, "_session", lambda path: ("fake-session", "https://fake-broker.test"))
    monkeypatch.setattr(oauth, "_CURRENT", {})
    seen = {}
    def fake_http(method, url, **kwargs):
        assert method == "GET"  # A refused callback never consumes a token.
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        seen.update(return_url=query["return_url"][0], nonce=query["nonce"][0])
        return 200, {"auth_url": "https://provider-signin.test/instagram"}
    def fake_browser(url):
        failure = {"provider": "instagram", "error": "instagram permission not granted: instagram_content_publish", "nonce": "wrong-nonce"}
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(seen["return_url"] + "?" + urllib.parse.urlencode(failure), timeout=2)
        assert oauth.current_status("instagram")["phase"] == "waiting"
        failure["nonce"] = seen["nonce"]
        with urllib.request.urlopen(seen["return_url"] + "?" + urllib.parse.urlencode(failure), timeout=2) as response:
            assert response.status == 200
    oauth.start("instagram", opener=fake_browser, http=fake_http)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        current = oauth.current_status("instagram")
        if current["phase"] == "failed":
            break
        time.sleep(0.01)
    assert current["phase"] == "failed"
    assert current["error"] == "instagram permission not granted: instagram_content_publish"


def test_transport_exception_fails_visibly_and_releases_local_listener():
    import socket
    def broken(*args, **kwargs):
        raise OSError("private-provider-token-must-not-render")
    attempt = oauth.CloudSocialAttempt("x", "fake-session", "https://fake-broker.test", http=broken)
    attempt._run()
    assert attempt.status()["phase"] == "failed"
    assert attempt.status()["error"] == "Cloud social OAuth broker unavailable; retry provider sign-in"
    assert attempt._server is None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", attempt._port))


@pytest.mark.parametrize("launch,accepted", [
    ("https://fake-broker.test/oauth/whatsapp/embedded?state=signed-state", True),
    ("https://untrusted.test/oauth/whatsapp/embedded?state=signed-state", False),
    ("https://fake-broker.test/other-path?state=signed-state", False),
])
def test_whatsapp_opens_only_cloud_origin_sdk_kickoff(launch, accepted):
    opened = []
    attempt = None
    def browser(url):
        opened.append(url)
        attempt._cancel = True
    attempt = oauth.CloudSocialAttempt("whatsapp", "fake-session", "https://fake-broker.test", opener=browser,
        http=lambda *args, **kwargs: (200, {"auth_url": "https://www.facebook.com/v25.0/dialog/oauth?state=signed-state", "browser_url": launch}), wait_seconds=1)
    attempt._run()
    assert opened == ([launch] if accepted else [])
    if not accepted:
        assert attempt.status()["error"] == "WhatsApp Embedded Signup launch did not match the ArchHub cloud"


def test_whatsapp_messages_reads_the_cloud_inbox_with_contact_filter_in_the_body(monkeypatch):
    monkeypatch.setattr(oauth, "_session", lambda path: ("fake-cloud-session", "https://fake-broker.test"))
    seen = []

    def fake_http(method, url, *, bearer, body=None, headers=None, timeout=10):
        seen.append((method, url, body))
        assert bearer == "fake-cloud-session"
        return 200, {"ok": True, "messages": [{"id": 7, "wamid": "wamid.7", "direction": "in", "contact": "201111111111",
                                              "contact_name": "Sample Contact", "kind": "text", "text": "hello", "sent_at": 1}],
                     "next": 7}

    answer = oauth.whatsapp_messages("Sample", 3, http=fake_http)
    assert answer["ok"] is True and answer["next"] == 7 and answer["messages"][0]["text"] == "hello"
    # The contact never rides in the URL (the cloud access log records URLs).
    assert seen == [("POST", "https://fake-broker.test/oauth/whatsapp/messages", {"contact": "Sample", "since": 3, "limit": 50})]
    monkeypatch.setattr(oauth, "_session", lambda path: ("", "https://fake-broker.test"))
    assert oauth.whatsapp_messages(http=fake_http)["state"] == "signin_required"


def test_social_node_reads_new_whatsapp_messages_into_its_inbox(monkeypatch):
    from nodelang.social_surface import SocialSurface

    class Store:
        held = {"state": {}}

        def read(self):
            return self.held

        def update(self, patch):
            self.held = {**self.held, **patch}

    pages = {0: {"ok": True, "messages": [
                {"id": 1, "wamid": "wamid.1", "direction": "in", "contact": "201111111111", "contact_name": "Sample Contact", "text": "first", "sent_at": 1},
                {"id": 2, "wamid": "wamid.2", "direction": "out", "contact": "201111111111", "contact_name": "", "text": "my reply", "sent_at": 2}],
                 "next": 2},
             2: {"ok": True, "messages": [], "next": 2}}
    monkeypatch.setattr(oauth, "whatsapp_messages", lambda since=0, limit=50, **_: pages[since])
    owner = SocialSurface(Store())
    out = owner.dispatch("read_whatsapp_inbox", [])
    assert out["result"] == {"added": 1, "cursor": 2}
    inbox = out["state"]["social"]["inbox"]
    assert [(m["from"], m["platform"], m["text"], m["unread"]) for m in inbox] == [("Sample Contact", "WhatsApp Business", "first", True)]
    assert owner.dispatch("read_whatsapp_inbox", [])["result"] == {"added": 0, "cursor": 2}  # cursor: no duplicates
    monkeypatch.setattr(oauth, "whatsapp_messages", lambda **_: {"ok": False, "state": "signin_required", "messages": []})
    with pytest.raises(ValueError, match="Sign in"):
        owner.dispatch("read_whatsapp_inbox", [])
