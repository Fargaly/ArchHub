"""Sign in with Meta gives a provider-verified account, never a typed token.

A fake Meta plays both sides: the browser calls the loopback with the code and
state, then fake Graph endpoints exchange the code and name the signed-in user.
"""
import socket
import time
import urllib.parse
import urllib.request

import pytest

from nodelang import model_router
from nodelang import social_connectors
from nodelang import social_custody
from nodelang import social_meta_signin as signin
from nodelang.universal_application import _APPLICATION_HTTP_ROUTE_SPECS


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _browser(state_override=None, error=None):
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
    seen = {"bearer": []}

    def form(url, body):
        seen["form"] = (url, dict(body))
        return options.pop("token_answer", (200, {"access_token": "EAAB-token", "expires_in": 5184000}))

    def bearer(url, token):
        seen["bearer"].append((url, token))
        if url == signin.USERINFO_URL:
            return options.pop("userinfo_answer", (200, {"id": "123456789012345", "name": "Ahmed F"}))
        if url == signin.PAGES_URL:
            return options.pop("pages_answer", (200, {"data": [
                {"id": "112233445566778", "name": "ArchHub Page", "access_token": "EAAB-page-token"}
            ]}))
        return options.pop("instagram_answer", (200, {
            "instagram_business_account": {"id": "17841412345678901", "username": "archhub"}
        }))

    attempt = signin.MetaSignIn("123456789012345", "secret-value-1", form=form, bearer=bearer,
                                port=_free_port(), wait_seconds=options.pop("wait", 5),
                                opener=options.pop("opener", _browser())).start()
    attempt.thread.join(timeout=10)
    return attempt, seen


def test_the_account_is_the_one_meta_names_and_the_token_is_taken_once():
    attempt, seen = _run()
    status = attempt.status()
    assert status["phase"] == "ready" and status["account_id"] == "meta:user:123456789012345"
    assert status["pages"] == [{"id": "112233445566778", "name": "ArchHub Page",
                                "instagram": {"id": "17841412345678901", "username": "archhub"}}]
    assert "EAAB-token" not in repr(status), "the token never appears in status"
    assert "EAAB-page-token" not in repr(status), "page tokens never appear in status"
    url, form = seen["form"]
    assert url == signin.TOKEN_URL and form["grant_type"] == "authorization_code" and form["code"] == "code-123"
    assert form["redirect_uri"] == attempt.redirect_uri and form["client_id"] == "123456789012345"
    assert seen["bearer"][0] == (signin.USERINFO_URL, "EAAB-token")
    assert seen["bearer"][1] == (signin.PAGES_URL, "EAAB-token")
    selected = attempt.take_page("112233445566778")
    assert selected["page_token"] == "EAAB-page-token"
    assert selected["page"]["id"] == "112233445566778"
    assert selected["instagram"]["id"] == "17841412345678901"
    assert selected["instagram_token"] == "EAAB-page-token"
    with pytest.raises(signin.MetaNotReady):
        attempt.take_page("112233445566778")


def test_a_forged_state_is_refused_and_nothing_is_exchanged():
    attempt, seen = _run(opener=_browser(state_override="forged"), wait=1.5)
    assert attempt.status()["phase"] == "failed" and "form" not in seen


def test_a_denied_consent_a_refused_code_or_an_unnamed_account_enrolls_nothing():
    denied, seen = _run(opener=_browser(error="user_cancelled_login"))
    assert denied.status()["phase"] == "failed" and "form" not in seen
    refused, _ = _run(token_answer=(401, {"error": "invalid_grant"}))
    assert refused.status()["phase"] == "failed"
    unnamed, _ = _run(userinfo_answer=(200, {"id": "bad id!"}))
    assert unnamed.status()["phase"] == "failed"
    for attempt in (denied, refused, unnamed):
        with pytest.raises(signin.MetaNotReady):
            attempt.take_page("112233445566778")


def test_the_redirect_and_scopes_match_graph_publishing_needs():
    assert signin.REDIRECT_URI == "http://127.0.0.1:48721/meta/callback"
    assert signin.SCOPES.split() == [
        "pages_show_list", "pages_read_engagement", "pages_manage_posts",
        "pages_manage_engagement", "instagram_basic", "instagram_content_publish",
        "instagram_manage_comments",
    ]


def test_the_meta_app_is_kept_protected_and_its_secret_never_returned(monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    saved = model_router.save_meta_app({"app_id": "123456789012345", "app_secret": "secret-value-1"})
    assert saved == {"ok": True, "state": "saved", "app_id": "123456789012345", "source": "secrets store"}
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    assert model_router.meta_app() == ("123456789012345", "secret-value-1")
    for bad in ({"app_id": "abc", "app_secret": "secret-value-1"}, {"app_id": "123456789012345", "app_secret": "a b"}):
        with pytest.raises(model_router.ProviderCredentialError):
            model_router.save_meta_app(bad)


def test_only_provider_named_meta_page_and_ig_accounts_are_recorded_as_verified(monkeypatch):
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put({}))
    body = {"vault_entry": "social-meta-123456789012345", "provider": "meta",
            "account_id": "112233445566778", "token": "EAAB-token"}
    assert model_router.save_social_credential(dict(body))["account_binding"] == "operator-declared"
    assert model_router.save_social_credential(dict(body), verified=True)["account_binding"] == "provider-verified"


def test_meta_page_and_instagram_credentials_resolve_for_existing_work_paths(monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    model_router.save_social_credential({
        "vault_entry": "social-meta-page-112233445566778", "provider": "meta",
        "account_id": "112233445566778", "token": "EAAB-page-token"}, verified=True)
    model_router.save_social_credential({
        "vault_entry": "social-meta-ig-17841412345678901", "provider": "meta",
        "account_id": "17841412345678901", "token": "EAAB-page-token"}, verified=True)
    assert social_custody.social_account_binding(provider="meta", account_id="112233445566778",
                                                 vault_entry="social-meta-page-112233445566778") == "provider-verified"
    assert social_custody.social_account_binding(provider="meta", account_id="17841412345678901",
                                                 vault_entry="social-meta-ig-17841412345678901") == "provider-verified"
    facebook, _ = social_connectors.social_material_from_values({
        "operation": "facebook.page_post", "account_id": "112233445566778",
        "vault_entry": "social-meta-page-112233445566778", "arguments": {"message": "Hello"}})
    instagram, _ = social_connectors.social_material_from_values({
        "operation": "instagram.reply", "account_id": "17841412345678901",
        "vault_entry": "social-meta-ig-17841412345678901",
        "arguments": {"comment_id": "998877665544332", "message": "Hello"}})
    assert facebook.account_id == "112233445566778" and facebook.operation == "facebook.page_post"
    assert instagram.account_id == "17841412345678901" and instagram.operation == "instagram.reply"


def test_the_settings_routes_are_declared_for_every_graph():
    declared = {(method, path) for method, path, _ in _APPLICATION_HTTP_ROUTE_SPECS}
    for route in (("POST", "/api/universal/social-meta-app"), ("GET", "/api/universal/social-meta-signin"),
                  ("POST", "/api/universal/social-meta-signin"), ("POST", "/api/universal/social-meta-finish"),
                  ("GET", "/api/universal/social-credentials")):
        assert route in declared, route


def test_local_social_credential_listing_returns_identity_not_token(monkeypatch):
    import base64
    import json

    class Store:
        SECRETS_FILE = r"C:\Users\fargaly\AppData\Roaming\ArchHub\secrets.dat"
        def _dpapi(self, data, protect):
            return data

    entries = {
        "social-meta-page-112233445566778": json.dumps({
            "format": "archhub-social-credential-2", "provider": "meta",
            "account_id": "112233445566778", "token": "EAAB-page-token",
            "account_binding": "provider-verified"}, separators=(",", ":"), sort_keys=True),
        "social-meta-legacy": json.dumps({
            "format": "archhub-social-credential-1", "provider": "meta",
            "account_id": "meta:user:older", "token": "EAAB-legacy"},
            separators=(",", ":"), sort_keys=True),
    }
    raw = model_router._CREDENTIAL_DPAPI_MARK + base64.b64encode(
        json.dumps(entries, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    monkeypatch.setattr(model_router, "_application_secrets_store", lambda: Store())
    monkeypatch.setattr(model_router, "_credential_file_bytes", lambda path: raw)
    answer = model_router.list_social_credentials()
    assert answer["ok"] is True and len(answer["items"]) == 2
    text = json.dumps(answer)
    assert "EAAB" not in text and "token" not in text
    by_vault = {item["vault_entry"]: item for item in answer["items"]}
    assert by_vault["social-meta-page-112233445566778"]["account_binding"] == "provider-verified"
    assert by_vault["social-meta-legacy"]["account_binding"] == "operator-declared"


def test_settings_offers_meta_sign_in_and_the_page_never_holds_the_token():
    from pathlib import Path
    studio = Path(signin.__file__).resolve().parent / "studio"
    page = (studio / "studio-lm.jsx").read_text(encoding="utf-8")
    transport = (studio / "studio-existing-workshop.js").read_text(encoding="utf-8")
    assert "<SettingsMetaSignIn transport={transport}/>" in page
    assert "post('/api/universal/social-meta-app', {app_id, app_secret})" in transport
    assert "post('/api/universal/social-meta-signin', {})" in transport
    assert "get('/api/universal/social-meta-signin')" in transport
    assert "post('/api/universal/social-meta-finish', {page_id})" in transport, "finish sends no token"
    assert "result.account_binding !== 'provider-verified'" in transport
    assert "Use {page.name || page.id}" in page


def test_cancel_ends_the_wait_and_frees_the_port():
    attempt = signin.MetaSignIn("123456789012345", "secret-value-1", port=_free_port(), wait_seconds=60,
                                opener=lambda url: None).start()
    try:
        deadline = time.monotonic() + 5
        while attempt.status()["phase"] == "starting" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert attempt.status()["phase"] == "waiting", attempt.status()
        port = urllib.parse.urlsplit(attempt.redirect_uri).port
        attempt.cancel()
        attempt.thread.join(timeout=5)
        assert attempt.status()["phase"] == "failed" and attempt.status()["error"] == "cancelled"
        with socket.socket() as again:
            again.bind(("127.0.0.1", port))
    finally:
        attempt.cancel()
