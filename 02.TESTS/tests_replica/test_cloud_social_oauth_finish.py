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


# ------------------------------------------------ account sync: connections (D-051) --

class _FakeAccount:
    """The cloud account-sync owner, in memory: heads per logical path, nothing else."""

    def __init__(self):
        self.heads = {}  # path -> bytes (absent = removed)
        self.lost = set()  # paths sealed under a key the cloud lost
        self.removed = set()  # paths the account removed (answer 410 {"removed": true})
        self.bare_404 = False  # a cloud without the account-sync routes
        self.calls = []

    def put_record(self, path, record):
        from nodelang import account_sync
        self.heads[path] = account_sync.canonical(record)

    def token(self, path):
        return json.loads(self.heads[path])["token"]

    def __call__(self, method, url, *, bearer, body=None, headers=None, timeout=10.0):
        import base64
        import gzip
        import hashlib
        assert bearer == "account-bearer"
        if self.bare_404:
            return 404, {"detail": "Not Found"}
        route = url.split("/v1/account-sync/", 1)[1]
        self.calls.append((method, route.split("?")[0]))
        if route.startswith("manifest"):
            return 200, {"items": [{"logical_path": p, "sha256": hashlib.sha256(c).hexdigest(), "deleted": False,
                                    **({"needs_reconnect": True} if p in self.lost else {})}
                                   for p, c in sorted(self.heads.items())]}
        if route == "item":
            if body.get("deleted"):
                self.heads.pop(body["logical_path"], None)
                self.removed.add(body["logical_path"])
                return 200, {"sha256": ""}
            content = gzip.decompress(base64.b64decode(body["content_b64"]))
            self.heads[body["logical_path"]] = content
            self.lost.discard(body["logical_path"])
            self.removed.discard(body["logical_path"])
            return 200, {"sha256": hashlib.sha256(content).hexdigest()}
        if route.startswith("blob/"):
            path = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["logical_path"][0]
            return 200, {"content_b64": base64.b64encode(gzip.compress(self.heads[path])).decode()}
        path = "connections/" + route.split("/", 1)[1] + ".json"
        if path in self.heads:
            return 200, {"record": json.loads(self.heads[path])}
        return (410, {"removed": True}) if path in self.removed else (404, {"detail": "account_sync_connection_missing"})


def _signed_in_account(monkeypatch, entries, user="user-a"):
    """A fake signed-in ArchHub account over a fake DPAPI cache."""
    from nodelang import account_sync

    class Admitted:
        def check(self):
            return {"admitted": True}

    account = _FakeAccount()
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None, **errors: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    monkeypatch.setattr(model_router, "list_social_credentials", lambda: {"items": [
        {"vault_entry": name, **{k: json.loads(v)[k] for k in ("provider", "account_id")}}
        for name, v in sorted(entries.items())]})
    monkeypatch.setattr(cloud_social_oauth, "_session", lambda path: ("account-bearer", "https://cloud.example"))
    monkeypatch.setattr(account_sync, "_http", account)
    monkeypatch.setattr(account_sync, "_access", Admitted())
    monkeypatch.setattr(account_sync, "_account", lambda: user)
    return account


def _x_local(token):
    from nodelang import account_sync
    return account_sync.canonical({"format": "archhub-social-credential-2", "provider": "x", "account_id": "101",
                                   "token": token, "account_binding": "provider-verified",
                                   "display_name": "Studio X"}).decode()


X_PATH = "connections/social-x-101.json"


def test_local_connections_join_the_account_once_then_resolve_from_it(monkeypatch):
    from nodelang import account_sync
    entries = {"social-x-101": _x_local("x-local-1")}
    account = _signed_in_account(monkeypatch, entries)
    assert account_sync.pull_and_restore("connections/") == {"connections/": {"uploaded": 1, "pulled": 0, "dropped": 0}}
    assert account.token(X_PATH) == "x-local-1"
    assert account_sync.pull_and_restore("connections/")["connections/"]["uploaded"] == 0  # migration ran once
    # The account rotated the token (server refresh, another PC): the call uses it and the cache follows.
    account.put_record(X_PATH, json.loads(_x_local("x-account-2")))
    sent = len(account.calls)
    assert social_custody.social_credential(provider="x", account_id="101", vault_entry="social-x-101") == "x-account-2"
    assert json.loads(entries["social-x-101"])["token"] == "x-account-2"
    assert ("PUT", "item") not in account.calls[sent:]  # filling the cache never writes back


def test_a_new_pc_receives_the_account_connections_and_removal_follows_the_account(monkeypatch):
    from nodelang import account_sync
    entries = {}
    account = _signed_in_account(monkeypatch, entries)
    account.put_record(X_PATH, json.loads(_x_local("x-account-1")))
    assert account_sync.pull_and_restore("connections/")["connections/"]["pulled"] == 1
    assert json.loads(entries["social-x-101"])["token"] == "x-account-1"
    # Removed from the account on another PC: refused here, then dropped from this PC's cache.
    account.heads.clear()
    account.removed.add(X_PATH)
    try:
        social_custody.social_credential(provider="x", account_id="101", vault_entry="social-x-101")
        raise AssertionError("a connection removed from the account still resolved")
    except ValueError as refused:
        assert "removed from your ArchHub account" in str(refused)
    assert entries == {}  # the confirmed revocation dropped the cached copy at once
    assert account_sync.pull_and_restore("connections/")["connections/"]["dropped"] == 0
    # Connecting on this PC puts it on the account; removing it here removes it from the account.
    model_router.save_social_credential({"vault_entry": "social-x-101", "provider": "x", "account_id": "101",
                                         "token": "x-local-3", "display_name": "Studio X"}, verified=True)
    assert account.token(X_PATH) == "x-local-3"
    model_router.revoke_social_credential({"vault_entry": "social-x-101", "provider": "x", "account_id": "101"})
    assert account.heads == {} and entries == {}


def test_signed_out_or_offline_uses_this_pcs_cache(monkeypatch):
    from nodelang import account_sync
    entries = {"social-x-101": _x_local("x-local-1")}
    _signed_in_account(monkeypatch, entries)
    monkeypatch.setattr(cloud_social_oauth, "_session", lambda path: ("", "https://cloud.example"))
    assert account_sync.pull_and_restore() == {}
    assert social_custody.social_credential(provider="x", account_id="101", vault_entry="social-x-101") == "x-local-1"


def test_each_account_keeps_its_own_sync_record(monkeypatch):
    from nodelang import account_sync
    entries = {"social-x-101": _x_local("x-local-1")}
    _signed_in_account(monkeypatch, entries, user="user-a")
    account_sync.pull_and_restore("connections/")
    assert X_PATH in account_sync._state()["base"]
    monkeypatch.setattr(account_sync, "_account", lambda: "user-b")
    assert account_sync._state()["base"] == {}  # another account on this PC starts its own migration


def test_a_connection_the_account_can_no_longer_open_heals_from_this_pc_or_asks_to_reconnect(monkeypatch):
    from nodelang import account_sync, social_connections
    entries = {"social-x-101": _x_local("x-local-1")}
    account = _signed_in_account(monkeypatch, entries)
    monkeypatch.setattr(cloud_social_oauth, "status", lambda provider: {"state": "saved"})
    account_sync.pull_and_restore("connections/")
    # The cloud lost its key: this PC still holds the connection, so it goes up again.
    account.lost.add(X_PATH)
    assert account_sync.pull_and_restore("connections/")["connections/"].get("healed") == 1
    assert X_PATH not in account.lost and account.token(X_PATH) == "x-local-1"
    # A new PC with nothing local: Settings > Social shows Reconnect, nothing is dropped from the account.
    entries.clear()
    monkeypatch.setattr(account_sync, "_account", lambda: "user-a-new-pc")
    account.lost.add(X_PATH)
    assert account_sync.pull_and_restore("connections/")["connections/"]["pulled"] == 0
    row = social_connections.connection("x", accounts=[], attempt={"phase": "idle"})
    assert row["state"] == "blocked" and row["blocker"].startswith("Reconnect")
    assert X_PATH in account.heads


def test_a_cloud_without_the_route_or_a_bare_404_serves_the_cache_never_removed(monkeypatch):
    from nodelang import account_sync
    entries = {"social-x-101": _x_local("x-local-1")}
    account = _signed_in_account(monkeypatch, entries)
    account_sync.pull_and_restore("connections/")  # previously synced
    account.bare_404 = True  # the deployed cloud has no /v1/account-sync yet
    assert social_custody.social_credential(provider="x", account_id="101", vault_entry="social-x-101") == "x-local-1"
    account.bare_404 = False
    account.heads.clear()  # never stored there and not removed: a plain 404 is not a revocation
    assert social_custody.social_credential(provider="x", account_id="101", vault_entry="social-x-101") == "x-local-1"
    assert "social-x-101" in entries


def test_only_the_explicit_410_removed_answer_revokes_and_drops_the_cache(monkeypatch):
    from nodelang import account_sync
    entries = {"social-x-101": _x_local("x-local-1")}
    account = _signed_in_account(monkeypatch, entries)
    account_sync.pull_and_restore("connections/")
    account.heads.clear()
    account.removed.add(X_PATH)
    try:
        social_custody.social_credential(provider="x", account_id="101", vault_entry="social-x-101")
        raise AssertionError("a revoked connection still resolved")
    except ValueError as refused:
        assert "removed from your ArchHub account" in str(refused)
    assert entries == {}


def test_publish_review_never_blocks_connecting_or_reading(monkeypatch):
    # Founder 2026-11-26: WhatsApp showed "blocked · Meta app review" although connecting his own number needs no review.
    from nodelang import social_connections
    monkeypatch.setattr(cloud_social_oauth, "status", lambda provider: {
        "state": "configured", "review_state": "unverified",
        "publish_blocker": "Meta app review: whatsapp_business_management, whatsapp_business_messaging approval not verified"})
    row = social_connections.connection("whatsapp", accounts=[], attempt={"phase": "idle"})
    assert row["state"] == "not_connected" and row["blocker"] == "" and row["can_connect"] is True
    assert row["publish_blocker"].startswith("Meta app review")


def test_rows_speak_plainly_and_hide_cloud_key_names(monkeypatch):
    # Founder 2026-11-26 screenshot: "not_connected", "connecting", "LinkedIn cloud publisher app secret missing".
    from nodelang import social_connections
    monkeypatch.setattr(cloud_social_oauth, "status", lambda provider: {"state": "configured"})
    assert social_connections.connection("whatsapp", accounts=[], attempt={"phase": "idle"})["status"] == "Not connected"
    assert social_connections.connection("whatsapp", accounts=[], attempt={"phase": "waiting"})["status"] == "Finish signing in in your browser"
    monkeypatch.setattr(cloud_social_oauth, "status", lambda provider: {
        "state": "blocked", "blocker": "LinkedIn cloud publisher app secret missing"})
    row = social_connections.connection("linkedin", accounts=[], attempt={"phase": "idle"})
    assert row["status"] == row["blocker"] == "Needs setup on ArchHub's side"
    assert row["detail"] == "LinkedIn cloud publisher app secret missing"


def test_restore_refused_item_is_skipped_and_marked_reconnect(monkeypatch, tmp_path):
    import base64, gzip, hashlib
    from nodelang import account_sync
    # A connection item this PC refuses to cache never fails the Connections read (gate 400).
    content = b'{"provider":"meta","display_name":"x"}'
    sha = hashlib.sha256(content).hexdigest()

    def http(method, url, bearer=None, body=None):
        if "/manifest" in url:
            return 200, {"items": [{"logical_path": "zz/a.json", "sha256": sha}]}
        if "/blob/" in url:
            return 200, {"content_b64": base64.b64encode(gzip.compress(content)).decode()}
        return 200, {}

    def refuse(path, data):
        raise ValueError("invalid_social_credential")

    monkeypatch.setattr(account_sync, "_http", http)
    monkeypatch.setattr(account_sync, "_access", type("A", (), {"check": lambda self: {"admitted": True}})())
    monkeypatch.setattr(account_sync._cloud, "_session", lambda _o: ("t", "https://x"))
    monkeypatch.setattr(account_sync, "_state_path", lambda: tmp_path / "sync-state.json")
    monkeypatch.setattr(account_sync, "_account", lambda: "qa")
    monkeypatch.setitem(account_sync._NAMESPACES, "zz/",
                        {"items": dict, "cache": refuse, "drop": lambda p, m: None, "conflicts": False})

    assert account_sync.pull_and_restore("zz/") == {"zz/": {"uploaded": 0, "pulled": 0, "dropped": 0}}
    assert account_sync.needs_reconnect("zz/") == ["zz/a.json"]


def test_connections_answer_within_budget_from_the_last_known_status(monkeypatch):
    import threading
    import time
    from nodelang import account_sync, social_connections

    hang = threading.Event()
    answers = {"whatsapp": {"state": "saved"}}

    def status(provider):
        if provider in answers:
            return answers[provider]
        hang.wait(5)
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(social_connections.broker, "status", status)
    monkeypatch.setattr(account_sync, "pull_and_restore", lambda _p: hang.wait(5))
    monkeypatch.setattr(social_connections.model_router, "list_social_credentials", lambda: {"items": []})
    monkeypatch.setattr(social_connections, "_LAST", {"linkedin": {"state": "saved"}})
    started = time.monotonic()
    rows = {row["provider"]: row for row in social_connections.rows(budget=0.5)}
    hang.set()
    assert time.monotonic() - started < 2
    assert rows["whatsapp"]["state"] == "not_connected" and rows["whatsapp"]["can_connect"]
    assert rows["linkedin"]["state"] == "not_connected"  # last known status answers for a slow cloud
    assert rows["x"]["blocker"] == "Couldn't reach ArchHub's servers"
