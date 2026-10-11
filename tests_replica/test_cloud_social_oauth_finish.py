from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from nodelang import cloud_social_oauth
from nodelang import model_router
from nodelang import social_custody
from nodelang import social_linkedin_signin
from nodelang import social_meta_signin


def _session(tmp_path):
    path = tmp_path / "cloud.json"
    path.write_text(json.dumps({"token": "cloud-bearer", "cloud_base_url": "https://cloud.example"}), encoding="utf-8")
    return path


def _wait_ready(provider: str, seconds: float = 5.0) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        status = cloud_social_oauth.current_status(provider)
        if status.get("phase") == "ready":
            return status
        time.sleep(0.02)
    return cloud_social_oauth.current_status(provider)


def test_fake_cloud_linkedin_grant_finishes_into_executable_dpapi_custody(tmp_path, monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    seen = {"return_url": ""}

    def fake_http(method, url, *, bearer, body=None, headers=None, timeout=10.0):
        assert bearer == "cloud-bearer"
        assert headers and headers["X-ArchHub-Device-Session"]
        if method == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen["return_url"] = query["return_url"][0]
            assert query["nonce"][0]
            return 200, {"auth_url": "https://provider.example/linkedin"}
        assert body == {"grant": "linkedin-grant"}
        return 200, {"account_id": "urn:li:person:desktopUser", "access_token": "AQX-dev-tok", "name": "Desktop"}

    cloud_social_oauth.start("linkedin", path=_session(tmp_path), http=fake_http, opener=lambda url: None)
    deadline = time.time() + 5
    while not seen["return_url"] and time.time() < deadline:
        time.sleep(0.02)
    urllib.request.urlopen(seen["return_url"] + "?provider=linkedin&grant=linkedin-grant", timeout=5).read()
    assert _wait_ready("linkedin")["account_id"] == "urn:li:person:desktopUser"
    account_id, credential = social_linkedin_signin.take_verified()
    model_router.save_social_credential({
        "vault_entry": "social-linkedin-desktopUser",
        "provider": "linkedin",
        "account_id": account_id,
        "token": credential,
    }, verified=True)
    assert social_custody.social_credential(
        provider="linkedin",
        account_id="urn:li:person:desktopUser",
        vault_entry="social-linkedin-desktopUser",
    ) == "AQX-dev-tok"


def test_fake_cloud_meta_grant_finishes_page_into_executable_dpapi_custody(tmp_path, monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    seen = {"return_url": ""}

    def fake_http(method, url, *, bearer, body=None, headers=None, timeout=10.0):
        assert bearer == "cloud-bearer"
        assert headers and headers["X-ArchHub-Device-Session"]
        if method == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            seen["return_url"] = query["return_url"][0]
            assert query["nonce"][0]
            return 200, {"auth_url": "https://provider.example/meta"}
        assert body == {"grant": "meta-grant"}
        return 200, {"account_id": "123456789012345", "access_token": "EAAB-user-token", "name": "Desktop",
                     "pages": [{"id": "112233445566778", "name": "ArchHub Page"}],
                     "page_secrets": {"112233445566778": {"page_token": "EAAB-page-token"}}}

    cloud_social_oauth.start("meta", path=_session(tmp_path), http=fake_http, opener=lambda url: None)
    deadline = time.time() + 5
    while not seen["return_url"] and time.time() < deadline:
        time.sleep(0.02)
    urllib.request.urlopen(seen["return_url"] + "?provider=meta&grant=meta-grant", timeout=5).read()
    assert _wait_ready("meta")["pages"] == [{"id": "112233445566778", "name": "ArchHub Page"}]
    selected = social_meta_signin.take_verified_page("112233445566778")
    model_router.save_social_credential({
        "vault_entry": "social-meta-page-112233445566778",
        "provider": "meta",
        "account_id": selected["page"]["id"],
        "token": selected["page_token"],
    }, verified=True)
    assert social_custody.social_credential(
        provider="meta",
        account_id="112233445566778",
        vault_entry="social-meta-page-112233445566778",
    ) == "EAAB-page-token"
