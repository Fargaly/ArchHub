"""One account record across renewal, restart and inline provider connection."""
import json
import time
import pytest
from tests_replica import test_the_desktop_signs_in_by_email as signin_courts

from nodelang import cloud_signin

cloud = signin_courts.cloud


@pytest.fixture(autouse=True)
def isolated_account_secrets(monkeypatch):
    from app import secrets_store
    from nodelang import cloud_session
    monkeypatch.setattr(secrets_store, "_MEMORY_KEYS", {})
    monkeypatch.setattr(cloud_session, "_account_verdicts", {})


def test_local_account_reads_never_wait_for_cloud_and_never_trust_file_email(tmp_path, monkeypatch):
    import threading
    from nodelang import cloud_session
    record = tmp_path / "cloud.json"
    cloud_signin.write_cloud_session(record, {"token": "identity-court", "email": "forged@example.test"})
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def cloud_get(url, token):
        calls.append(url)
        entered.set()
        assert release.wait(5)
        return 200, {"email": "verified@example.test"}

    remember = cloud_session.remember_verified_account
    def remembered(*args):
        try:
            return remember(*args)
        finally:
            done.set()

    monkeypatch.setattr(cloud_session, "_cloud_get", cloud_get)
    monkeypatch.setattr(cloud_session, "remember_verified_account", remembered)
    try:
        started = time.monotonic()
        assert cloud_session.signed_in_cloud_account(record) is None
        assert entered.wait(1)
        for _ in range(10):
            assert cloud_session.signed_in_cloud_account(record) is None
        assert time.monotonic() - started < 1
        assert len(calls) == 1
    finally:
        release.set()
    assert done.wait(2)
    assert cloud_session.signed_in_cloud_account(record) == "verified@example.test"
    cloud_signin.sign_out(record, http=lambda *args, **kwargs: (200, {}), wait=True)
    assert cloud_session.signed_in_cloud_account(record) is None


def test_refresh_updates_the_existing_record_before_expiry(tmp_path):
    record = tmp_path / "cloud.json"
    now = int(time.time())
    cloud_signin.write_cloud_session(record, {"email": "person@example.test", "token": "court-token",
        "expires_at": now + 60, "cloud_base_url": "https://api.archhub.io", "consent": "keep"})
    calls = []

    def http(method, url, **kwargs):
        calls.append((method, url))
        return 200, {"expires_at": now + 90 * 86400}

    cloud_signin.refresh_session(record, now=now, http=http)
    held = cloud_signin.read_cloud_session(record)
    assert held["expires_at"] == now + 90 * 86400
    assert held["token"] == "court-token" and held["consent"] == "keep"
    assert calls == [("POST", "https://api.archhub.io/v1/auth/refresh")]
    assert cloud_signin.sign_in_state(record, now=now + 120)["signed_in"]


def test_relay_waits_for_startup_and_expired_identity_proof_without_stopping(tmp_path, monkeypatch):
    import threading
    from nodelang import cloud_session, cloud_relay, cloud_publish_consent
    appdata = tmp_path / "appdata"
    record = appdata / "ArchHub/brain/cloud.json"
    held = cloud_signin.write_cloud_session(record, {"token": "relay-proof-court", "email": "forged@example.test"})
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def cloud_get(*args):
        entered.set()
        assert release.wait(5)
        return 200, {"email": "verified@example.test"}
    remember = cloud_session.remember_verified_account
    def remembered(*args):
        try:
            return remember(*args)
        finally:
            done.set()
    monkeypatch.setattr(cloud_session, "_cloud_get", cloud_get)
    monkeypatch.setattr(cloud_session, "remember_verified_account", remembered)
    monkeypatch.setattr(cloud_publish_consent, "cloud_publish_allowed", lambda state, account: account == "verified@example.test")
    monkeypatch.setattr(cloud_relay.CloudRelay, "start", lambda self: self)
    relay = cloud_relay.start_cloud_relay(appdata=appdata, state_dir=tmp_path, respond=lambda text: {}, execute=lambda text: {})
    relay._call = lambda *args: calls.append(args) or {}
    relay.map_script = lambda: pytest.fail("map projection read before verified consent")
    try:
        assert entered.wait(1)
        assert relay.poll_once() is None and not relay._stop.is_set() and not calls
        assert relay.push_map(force=True) is None
    finally:
        release.set()
    assert done.wait(2)
    relay.poll_once()
    assert len(calls) == 1 and not relay._stop.is_set()
    key = cloud_session._account_key(held)
    cloud_session._account_verdicts[key] = (0, "verified@example.test")
    entered.clear(); release.clear(); done.clear()
    try:
        relay.poll_once()
        assert entered.wait(1)
        assert len(calls) == 1 and not relay._stop.is_set()
        assert relay.push_map(force=True) is None
    finally:
        release.set()
    assert done.wait(2)
    remember(held, None, None)
    relay.poll_once()
    assert len(calls) == 1 and not relay._stop.is_set(), "offline is not revoked consent"
    remember(held, 401, {})
    relay.poll_once()
    assert len(calls) == 1 and relay._stop.is_set(), "confirmed refusal must stop claims"


def test_refresh_response_cannot_resurrect_a_signout(tmp_path):
    record = tmp_path / "cloud.json"
    now = int(time.time())
    cloud_signin.write_cloud_session(record, {"email": "person@example.test", "token": "court-token",
        "expires_at": now + 60})

    def http(*args, **kwargs):
        cloud_signin.sign_out(record, http=lambda *args, **kwargs: (200, {}), wait=True)
        return 200, {"expires_at": now + 86400}

    cloud_signin.refresh_session(record, now=now, http=http)
    assert not cloud_signin.sign_in_state(record)["signed_in"]


def test_refresh_offline_keeps_session_and_never_opens_browser(tmp_path):
    record = tmp_path / "cloud.json"
    now = int(time.time())
    cloud_signin.write_cloud_session(record, {"email": "person@example.test", "token": "court-token",
        "expires_at": now + 60})
    before = record.read_bytes()

    def offline(*args, **kwargs):
        raise OSError("offline")

    cloud_signin.refresh_session(record, now=now, http=offline)
    assert record.read_bytes() == before


def test_signin_and_readers_share_the_one_locator():
    from nodelang import cloud_session
    assert cloud_signin.cloud_session_path is cloud_session.cloud_session_path


def test_default_model_and_brain_sidecars_use_the_canonical_profile(tmp_path, monkeypatch):
    from nodelang import brain_cloud_runner, cloud_session, model_router
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path / "actual-profile"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "wrong-agent-view"))
    record = cloud_session.cloud_session_path()
    cloud_signin.write_cloud_session(record, {"email": "profile@example.test", "token": "profile-court-token"})
    assert model_router.default_cloud_session()["token"] == "profile-court-token"
    assert brain_cloud_runner.device_path() == record.with_name("device.json")
    assert brain_cloud_runner.cursor_path() == record.with_name("sync-cursor.json")
    explicit = tmp_path / "explicit-fake-profile"
    assert brain_cloud_runner.device_path(explicit) == explicit / "ArchHub/brain/device.json"


def test_account_bearer_is_protected_and_plaintext_legacy_is_removed(tmp_path):
    record = tmp_path / "cloud.json"
    record.write_text(json.dumps({"email": "person@example.test", "token": "legacy-court-bearer",
        "expires_at": int(time.time()) + 86400}), encoding="utf-8")
    assert cloud_signin.read_cloud_session(record)["token"] == "legacy-court-bearer"
    metadata = json.loads(record.read_text(encoding="utf-8"))
    assert "token" not in metadata, "the account bearer remained in plain AppData"
    assert metadata["token_ref"]
    assert "legacy-court-bearer" not in record.read_text(encoding="utf-8")


def test_account_switch_and_signout_delete_the_old_protected_record(tmp_path):
    from app import secrets_store
    record = tmp_path / "cloud.json"
    cloud_signin.write_cloud_session(record, {"email": "first@example.test", "token": "first-token"})
    first = json.loads(record.read_text(encoding="utf-8"))["token_ref"]
    cloud_signin.write_cloud_session(record, {"email": "second@example.test", "token": "second-token"})
    assert secrets_store.load_session_secret(first) is None
    second = json.loads(record.read_text(encoding="utf-8"))["token_ref"]
    assert json.loads(secrets_store.load_session_secret(second))["token"] == "second-token"
    cloud_signin.sign_out(record, http=lambda *args, **kwargs: (200, {}), wait=True)
    assert secrets_store.load_session_secret(second) is None
    assert not cloud_signin.sign_in_state(record)["signed_in"]


def test_stale_legacy_file_cannot_replace_the_current_protected_session(tmp_path):
    record = tmp_path / "cloud.json"
    cloud_signin.write_cloud_session(record, {"email": "person@example.test", "token": "new-token"})
    record.write_text(json.dumps({"email": "person@example.test", "token": "stale-token"}), encoding="utf-8")
    assert cloud_signin.read_cloud_session(record)["token"] == "new-token"
    assert "token" not in json.loads(record.read_text(encoding="utf-8"))


def test_format_migration_removes_the_legacy_secret_key_and_reads_reload(tmp_path):
    from app import secrets_store
    record = tmp_path / "cloud.json"
    document = {"email": "format@example.test", "token": "old-format-token"}
    legacy = cloud_signin._session_reference(document).replace(":v1:", ":v0:")
    secrets_store.save_session_secret(legacy, json.dumps(document))
    record.write_text(json.dumps({"email": document["email"], "token_ref": legacy}), encoding="utf-8")
    held = cloud_signin.read_cloud_session(record)
    assert secrets_store.load_session_secret(legacy) is None
    assert held["token_ref"] != legacy and held["token"] == "old-format-token"
    secrets_store.save_session_secret(held["token_ref"], json.dumps({**document, "token": "reloaded-token"}))
    assert cloud_signin.read_cloud_session(record)["token"] == "reloaded-token"


def test_failed_metadata_publish_retains_the_previous_protected_session(tmp_path, monkeypatch):
    record = tmp_path / "cloud.json"
    cloud_signin.write_cloud_session(record, {"email": "rollback@example.test", "token": "old-token"})
    before = record.read_bytes()

    def refused(*args):
        raise OSError("injected metadata publish failure")

    monkeypatch.setattr(cloud_signin, "_write_session_metadata", refused)
    with pytest.raises(OSError):
        cloud_signin.write_cloud_session(record, {"token": "new-token"})
    assert record.read_bytes() == before
    assert cloud_signin.read_cloud_session(record)["token"] == "old-token"


def test_an_unapproved_keyring_backend_fails_closed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import secrets_store
    monkeypatch.setattr(secrets_store, "os_store_refused", lambda: False)
    monkeypatch.setattr(secrets_store, "_try_keyring", lambda: SimpleNamespace(get_keyring=lambda: object()))
    monkeypatch.setattr(secrets_store, "SECRETS_FILE", tmp_path / "never-written.dat")
    with pytest.raises(OSError, match="Windows Credential Manager"):
        secrets_store.save_session_secret("archhub-account-session:v1:" + "0" * 64, "court-only-value")
    assert not secrets_store.SECRETS_FILE.exists()


def test_one_connect_click_signs_in_then_opens_provider_authorize(tmp_path, monkeypatch):
    from urllib import parse as url_parse, request as url_request
    from nodelang import cloud_social_oauth as broker
    record = tmp_path / "cloud.json"
    seen, returned = [], {}
    monkeypatch.setattr(cloud_signin, "_CURRENT", {})
    monkeypatch.setattr(broker, "_CURRENT", {})
    original_begin = cloud_signin.begin

    def account_http(method, url, **kwargs):
        seen.append("account:" + url_parse.urlsplit(url).path)
        if "/google/start?" in url:
            query = url_parse.parse_qs(url_parse.urlsplit(url).query)
            return 200, {"auth_url": query["redirect"][0] + "?" + url_parse.urlencode(
                {"code": "court-code", "state": query["state"][0]})}
        if url.endswith("/exchange"):
            return 200, {"token": "court-token", "expires_at": int(time.time()) + 90 * 86400}
        return 200, {"email": "person@example.test", "user_id": "court-user"}

    def provider_http(method, url, **kwargs):
        seen.append("provider:" + url_parse.urlsplit(url).path)
        assert kwargs["bearer"] == "court-token"
        if method == "GET":
            returned["url"] = url_parse.parse_qs(url_parse.urlsplit(url).query)["return_url"][0]
            return 200, {"auth_url": "https://provider.example/authorize"}
        return 200, {"account_id": "court-account", "access_token": "court-provider-token", "name": "Court Person"}

    def browser(url):
        if url == "https://provider.example/authorize":
            seen.append("provider:authorize")
            url = returned["url"] + "?provider=linkedin&grant=court-grant"
        url_request.urlopen(url, timeout=5).read()

    monkeypatch.setattr(cloud_signin, "begin", lambda method, **kwargs:
        original_begin(method, http=account_http, **kwargs))
    assert broker.status("linkedin", path=record)["state"] == "signin_required"
    broker.start("linkedin", path=record, opener=browser, http=provider_http)
    deadline = time.monotonic() + 10
    while broker.current_status("linkedin")["phase"] not in ("ready", "failed") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert broker.current_status("linkedin")["phase"] == "ready"
    assert seen.count("account:/v1/auth/google/start") == 1
    assert seen.count("provider:authorize") == 1
    assert seen.index("account:/v1/me") < seen.index("provider:authorize")
    assert cloud_signin.sign_in_state(record)["signed_in"]
    assert broker.current_status("linkedin")["name"] == "Court Person"
    broker._CURRENT["linkedin"].thread.join(5)


def test_signed_out_connection_keeps_connect_enabled(monkeypatch):
    from nodelang import social_connections, cloud_social_oauth
    monkeypatch.setattr(cloud_social_oauth, "status", lambda provider: {"state": "signin_required"})
    row = social_connections.connection("linkedin", accounts=[], attempt={"phase": "idle"})
    assert row["can_connect"] and row["state"] == "not_connected" and not row["blocker"]


def test_connect_cancellation_wakes_the_existing_signin_waiter(tmp_path, monkeypatch):
    import threading
    from nodelang import cloud_social_oauth
    account = cloud_signin.SignIn("google", path=tmp_path / "cloud.json")
    monkeypatch.setattr(cloud_signin, "_CURRENT", {"attempt": account})
    monkeypatch.setattr(cloud_signin, "begin", lambda *args, **kwargs: account.status())
    entered = threading.Event()
    wait = cloud_signin.wait_for_change
    def waiting(*args, **kwargs):
        entered.set()
        return wait(*args, **kwargs)
    monkeypatch.setattr(cloud_signin, "wait_for_change", waiting)
    provider = cloud_social_oauth.CloudSocialAttempt("linkedin", "", "https://api.archhub.io",
        session_path=tmp_path / "cloud.json", http=lambda *args, **kwargs: pytest.fail("cancelled Connect authorized a provider")).start()
    assert entered.wait(2)
    provider.cancel()
    provider.thread.join(2)
    assert not provider.thread.is_alive() and provider.status()["error"] == "cancelled"
    assert not account._cancel, "cancelling Connect must not cancel a shared account sign-in"


def test_connect_cannot_miss_signin_completion_between_status_and_session_reads(tmp_path, monkeypatch):
    from nodelang import cloud_social_oauth
    account = cloud_signin.SignIn("google", path=tmp_path / "cloud.json")
    account._set(phase="exchanging")
    monkeypatch.setattr(cloud_signin, "_CURRENT", {"attempt": account})
    monkeypatch.setattr(cloud_signin, "begin", lambda *args, **kwargs: account.status())
    reads, waited = [], []
    def completing(path):
        reads.append(path)
        if len(reads) == 1:
            account._set(phase="done")
            return "", "https://api.archhub.io"
        return "court-completed-token", "https://api.archhub.io"
    wait = cloud_signin.wait_for_change
    def observed(previous, **kwargs):
        assert previous["phase"] != "done", "Connect waited for a completed sign-in to change again"
        waited.append(previous["phase"])
        return wait(previous, timeout=0, cancelled=kwargs["cancelled"])
    monkeypatch.setattr(cloud_social_oauth, "_session", completing)
    monkeypatch.setattr(cloud_signin, "wait_for_change", observed)
    provider = cloud_social_oauth.CloudSocialAttempt("linkedin", "", "https://api.archhub.io", session_path=tmp_path / "cloud.json")
    assert provider._sign_in()
    assert provider._token == "court-completed-token" and waited == ["exchanging"]


@pytest.mark.parametrize("identity", ["pending", "signed_out", "verified"])
def test_remember_never_attributes_pending_account_identity_to_local(identity, monkeypatch):
    from nodelang import application_server, cloud_session
    from nodelang.cell_authorization import AuthorizationDenied
    monkeypatch.setattr(cloud_session, "signed_in_cloud_account", lambda *, pending=None:
        pending if identity == "pending" else "verified@example.test" if identity == "verified" else None)
    if identity == "pending":
        with pytest.raises(AuthorizationDenied, match="no fact was written"):
            application_server.brain_remember_ops("court fact")
    else:
        ops = application_server.brain_remember_ops("court fact")
        expected = "local" if identity == "signed_out" else "verified@example.test"
        assert ops[0]["fragment"]["owner_user"] == expected
        assert ops[0]["fragment"]["provenance"]["contributing_user"] == expected


def test_google_signin_restart_and_real_installer_cleanup_preserve_session(cloud, tmp_path, monkeypatch):
    import hashlib
    import subprocess
    import sys
    from pathlib import Path
    from tests_replica.test_the_desktop_signs_in_by_email import _browser_that_follows, _wait
    from tests_replica.test_a_colleague_machine_is_not_the_founders import _sweep_harness, _v1_install, ISCC
    from app import secrets_store
    protected_profile = tmp_path / "protected-profile"
    monkeypatch.setattr(secrets_store, "os_store_refused", lambda: False)
    monkeypatch.setattr(secrets_store, "_try_keyring", lambda: None)
    monkeypatch.setattr(secrets_store, "SECRETS_FILE", protected_profile / "ArchHub/secrets.dat")
    assert ISCC.is_file(), "Inno Setup is required for the actual cleanup court"
    record = tmp_path / "roaming/ArchHub/brain/cloud.json"
    attempt = cloud_signin.SignIn("google", base_url="http://127.0.0.1:%d" % cloud.server_port,
        path=record, opener=_browser_that_follows).start()
    assert _wait(attempt)["phase"] == "done"
    assert b'"token"' not in record.read_bytes()
    assert b'"token"' not in secrets_store.SECRETS_FILE.read_bytes()
    original = hashlib.sha256(record.read_bytes()).hexdigest()
    read = "from pathlib import Path; import sys; from app import secrets_store; secrets_store._try_keyring=lambda:None; from nodelang import cloud_relay; cloud_relay.PINNED_BASES += (sys.argv[2],); from nodelang.cloud_signin import sign_in_state; assert sign_in_state(Path(sys.argv[1]))['signed_in']; print('fresh process: signed in')"
    environment = dict(__import__("os").environ, LOCALAPPDATA=str(protected_profile))
    environment.pop("ARCHHUB_TEST_SECRET_STORE", None)
    restarted = subprocess.run([sys.executable, "-B", "-c", read, str(record), "http://127.0.0.1:%d" % cloud.server_port],
        cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True, text=True, timeout=30)
    assert restarted.returncode == 0, restarted.stderr
    install = tmp_path / "local/ArchHub"
    _v1_install(install)
    sweep = _sweep_harness(tmp_path / "inno")
    for _upgrade in range(2):
        subprocess.run([str(sweep), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/root=" + str(install)],
            capture_output=True, timeout=30)
        assert not (install / "01.APP/app/main.py").exists(), "production upgrade cleanup did not execute"
        assert hashlib.sha256(record.read_bytes()).hexdigest() == original
        assert cloud_signin.sign_in_state(record)["signed_in"]
    print("ACCOUNT: Google PKCE -> fresh process signed in; real Inno upgrade cleanup retained session bytes 2/2")
