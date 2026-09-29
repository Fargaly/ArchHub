"""The public MCP door speaks OAuth (MCP authorization 2026-07-28) for Spark and Notion.

Discovery -> dynamic registration -> Google-verified authorization with PKCE S256 ->
one-time code -> one-hour access token for /mcp only -> rotating refresh token. Every
misuse the review named is refused here: wrong audience, client, scope, redirect or
verifier; a reused code or refresh token (which revokes the family); a concurrent
double redemption. Nothing is stored or logged in plaintext.

Run: python -m pytest cloud_backend/tests/test_mcp_oauth.py -q
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import secrets
import threading
import time
import types
import urllib.parse

import pytest

FOUNDER = "founder.desktop@example.test"
REDIRECT = "https://spark.example.test/oauth/callback"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False, follow_redirects=False, base_url="https://testserver")


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _register(client, redirect=REDIRECT):
    r = client.post("/oauth/register", json={"redirect_uris": [redirect], "client_name": "Spark"})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _consent_form(client, client_id, challenge, redirect=REDIRECT):
    r = client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st-1",
        "scope": "mcp:read", "resource": "https://api.archhub.io/mcp"})
    assert r.status_code == 200 and "Approve" in r.text, r.text
    return (re.search(r'name=pending value="([^"]+)"', r.text).group(1),
            re.search(r'name=csrf value="([^"]+)"', r.text).group(1), r)


def _google(monkeypatch, email=FOUNDER):
    import google_auth
    started = {}
    monkeypatch.setattr(google_auth, "build_authorization_url",
                        lambda **kw: started.update(kw) or "https://accounts.google.com/o/oauth2/v2/auth")
    monkeypatch.setattr(google_auth.config, "google_login_enabled", lambda: True)
    monkeypatch.setattr(google_auth, "_exchange_code_for_tokens", lambda code: {"id_token": "t"})
    monkeypatch.setattr(google_auth, "verify_id_token", lambda token: {"email": email, "email_verified": True})
    return started


def _callback(browser, pending):
    """Google's callback for `pending`, arriving in `browser` through the real route."""
    import google_auth
    state = google_auth.encode_state(code_challenge="", redirect="", mcp_grant=pending)
    return browser.get("/v1/auth/google/callback", params={"code": "google-code", "state": state})


def _continue_path(back):
    assert back.status_code == 302, back.text
    location = back.headers["location"]
    assert location.startswith("https://api.archhub.io/oauth/continue"), location
    return location.replace("https://api.archhub.io", "")


def _continue(browser, pending):
    """Google's callback and then the continue step, both in `browser`."""
    return browser.get(_continue_path(_callback(browser, pending)))


def _code(client, monkeypatch, client_id, challenge, email=FOUNDER, redirect=REDIRECT):
    """Consent in this browser, then Google, then the continue step that mints the code."""
    started = _google(monkeypatch, email)
    pending, csrf, _ = _consent_form(client, client_id, challenge, redirect)
    r = client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"})
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com"), r.text
    assert started["mcp_grant"] == pending
    back = _continue(client, pending)
    assert back.status_code == 302, back.text
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(back.headers["location"]).query))
    assert back.headers["location"].startswith(redirect) and query["state"] == "st-1" and query["iss"] == "https://api.archhub.io"
    return query["code"]


def _token(client, **form):
    return client.post("/oauth/token", data=form)


def _grant(client, monkeypatch, email=FOUNDER):
    client_id = _register(client)
    verifier, challenge = _pkce()
    code = _code(client, monkeypatch, client_id, challenge, email=email)
    r = _token(client, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
               client_id=client_id, code_verifier=verifier, resource="https://api.archhub.io/mcp")
    assert r.status_code == 200, r.text
    return client_id, code, verifier, r.json()


def _mcp(client, token, method="tools/list", params=None):
    r = client.post("/mcp", headers={"Authorization": "Bearer " + token,
                                     "Accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    data = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    return r.status_code, (json.loads(data[0]) if data else {})


def test_discovery_names_the_resource_the_server_and_s256(client):
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == "https://api.archhub.io/mcp"
    assert prm["authorization_servers"] == ["https://api.archhub.io"]
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == "https://api.archhub.io"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["authorization_response_iss_parameter_supported"] is True
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "brain.health", "arguments": {}}})
    assert r.status_code == 401
    challenge = r.headers["www-authenticate"]
    assert 'resource_metadata="https://api.archhub.io/.well-known/oauth-protected-resource"' in challenge
    assert 'scope="mcp:read"' in challenge


def test_registration_takes_only_exact_https_or_loopback_redirects(client):
    for bad in ("http://evil.example/cb", "https://*.example/cb", "https://ok.example/cb#frag", ""):
        assert client.post("/oauth/register", json={"redirect_uris": [bad]}).status_code == 400
    assert client.post("/oauth/register", json={"redirect_uris": [REDIRECT],
                                                "token_endpoint_auth_method": "client_secret_basic"}).status_code == 400
    assert _register(client, "http://127.0.0.1:43120/cb")


def test_authorize_refuses_unknown_clients_redirects_pkce_scope_and_audience(client):
    client_id = _register(client)
    _, challenge = _pkce()
    base = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
            "code_challenge": challenge, "code_challenge_method": "S256"}
    assert client.get("/oauth/authorize", params={**base, "client_id": "nobody"}).status_code == 400
    assert client.get("/oauth/authorize", params={**base, "redirect_uri": "https://other.example/cb"}).status_code == 400
    for change, error in (({"code_challenge_method": "plain"}, "invalid_request"),
                          ({"scope": "admin"}, "invalid_scope"),
                          ({"resource": "https://evil.example/mcp"}, "invalid_target")):
        r = client.get("/oauth/authorize", params={**base, **change})
        assert r.status_code == 302 and "error=" + error in r.headers["location"]


def test_the_google_mcp_path_mints_no_desktop_code(client, monkeypatch):
    import db
    client_id = _register(client)
    _, challenge = _pkce()
    _code(client, monkeypatch, client_id, challenge)
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM codes").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 0


def test_a_founder_token_reaches_mcp_and_his_host_tools_but_no_other_route(client, monkeypatch):
    _, _, _, answer = _grant(client, monkeypatch)
    status, body = _mcp(client, answer["access_token"])
    names = [tool["name"] for tool in body["result"]["tools"]]
    assert status == 200 and "brain.health" in names and "hosts.status" in names
    assert client.get("/v1/me", headers={"Authorization": "Bearer " + answer["access_token"]}).status_code == 401
    _, _, _, other = _grant(client, monkeypatch, email="someone.else@studio.example")
    names = [tool["name"] for tool in _mcp(client, other["access_token"])[1]["result"]["tools"]]
    assert "hosts.status" not in names, "host tools stay the founder's, decided on every call"


def test_a_code_is_used_once_and_a_replay_revokes_its_family(client, monkeypatch):
    client_id, code, verifier, answer = _grant(client, monkeypatch)
    assert _mcp(client, answer["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 200
    again = _token(client, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                   client_id=client_id, code_verifier=verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    assert _mcp(client, answer["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 401, "the replay revoked the tokens it had issued"


@pytest.mark.parametrize("change", [{"client_id": "mcp_client_other"}, {"redirect_uri": "https://other.example/cb"},
                                    {"code_verifier": "x" * 50}, {"resource": "https://evil.example/mcp"}])
def test_a_code_needs_its_own_client_redirect_verifier_and_resource(client, monkeypatch, change):
    client_id = _register(client)
    verifier, challenge = _pkce()
    code = _code(client, monkeypatch, client_id, challenge)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "client_id": client_id, "code_verifier": verifier, **change}
    assert _token(client, **form).status_code == 400


def test_refresh_rotates_and_a_reused_refresh_token_revokes_the_family(client, monkeypatch):
    client_id, _, _, answer = _grant(client, monkeypatch)
    first = _token(client, grant_type="refresh_token", refresh_token=answer["refresh_token"], client_id=client_id)
    assert first.status_code == 200 and first.json()["refresh_token"] != answer["refresh_token"]
    replay = _token(client, grant_type="refresh_token", refresh_token=answer["refresh_token"], client_id=client_id)
    assert replay.status_code == 400
    assert _mcp(client, first.json()["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 401
    wrong = _token(client, grant_type="refresh_token", refresh_token=first.json()["refresh_token"],
                   client_id="mcp_client_other")
    assert wrong.status_code == 400


def test_concurrent_double_redemption_issues_exactly_one_token(client, monkeypatch):
    client_id = _register(client)
    verifier, challenge = _pkce()
    code = _code(client, monkeypatch, client_id, challenge)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "client_id": client_id, "code_verifier": verifier}
    results, gate = [], threading.Barrier(4)

    def redeem():
        gate.wait()
        results.append(_token(client, **form).status_code)
    threads = [threading.Thread(target=redeem) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results) == [200, 400, 400, 400]


def test_codes_and_tokens_are_never_stored_or_logged_in_plaintext(client, monkeypatch, caplog):
    import db
    client_id, code, _, answer = _grant(client, monkeypatch)
    with db.connect() as con:
        dump = json.dumps([[dict(row) for row in con.execute("SELECT * FROM %s" % table)]
                           for table in ("oauth_codes", "oauth_tokens", "oauth_pending", "oauth_families")])
    for secret in (code, answer["access_token"], answer["refresh_token"]):
        assert secret not in dump and secret not in caplog.text

def test_P1_a_registered_attacker_never_receives_a_code_without_this_browsers_approval(monkeypatch):
    """The confused deputy: an attacker's client and redirect, the founder's Google account."""
    from fastapi.testclient import TestClient
    import main
    attacker = TestClient(main.app, raise_server_exceptions=False, follow_redirects=False, base_url="https://testserver")
    founder = TestClient(main.app, raise_server_exceptions=False, follow_redirects=False, base_url="https://testserver")
    evil = "https://attacker.example/cb"
    client_id = _register(attacker, evil)
    _google(monkeypatch)
    _, challenge = _pkce()
    # (a) The founder opens the attacker's link: he gets ArchHub's consent page naming the
    # attacker, never a redirect to Google or to the attacker.
    pending, _, page = _consent_form(founder, client_id, challenge, evil)
    assert "attacker.example" in page.text and page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    # (b) Skipping consent: a Google callback for an unapproved request yields no code.
    denied = _callback(founder, pending)
    assert denied.status_code == 400 and "location" not in denied.headers
    # (c) The attacker approves in HIS browser and makes the founder finish Google in his:
    pending, csrf, _ = _consent_form(attacker, client_id, challenge, evil)
    assert attacker.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    stolen = _callback(founder, pending)
    assert stolen.status_code == 400 and "location" not in stolen.headers
    import db
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_codes").fetchone()[0] == 0


def test_consent_escapes_names_needs_its_csrf_and_deny_returns_access_denied(client, monkeypatch):
    r = client.post("/oauth/register", json={"redirect_uris": [REDIRECT], "client_name": "<script>x</script>"})
    client_id = r.json()["client_id"]
    _google(monkeypatch)
    _, challenge = _pkce()
    pending, csrf, page = _consent_form(client, client_id, challenge)
    assert "<script>x" not in page.text and "&lt;script&gt;" in page.text
    assert client.post("/oauth/consent", data={"pending": pending, "csrf": "wrong", "decision": "approve"}).status_code == 400
    deny = client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "deny"})
    assert deny.status_code == 302 and "error=access_denied" in deny.headers["location"]
    assert client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 400


def test_approval_is_recorded_per_user_and_client(client, monkeypatch):
    import db
    client_id, _, _, _ = _grant(client, monkeypatch)
    with db.connect() as con:
        rows = con.execute("SELECT client_id FROM oauth_approvals").fetchall()
    assert [row[0] for row in rows] == [client_id]


def test_unfinished_requests_are_capped(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING", 2)
    client_id = _register(client)
    _, challenge = _pkce()
    for _ in range(2):
        _consent_form(client, client_id, challenge)
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
                                               "code_challenge": challenge, "code_challenge_method": "S256"})
    assert r.status_code == 200, "a full shared pool makes room instead of refusing"
    assert _live(client_id) == 2, "the oldest unapproved request made the room"


def test_registration_flooding_cannot_lock_out_an_approved_client(client, monkeypatch):
    import oauth_mcp
    approved, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_CLIENTS", 2)
    first_spam = _register(client, "https://spam.example/1")
    assert _register(client, "https://spam.example/2"), "the oldest unused client makes room"
    assert oauth_mcp._client(approved) is not None, "an approved client is never evicted"
    assert oauth_mcp._client(first_spam) is None

def test_a_suspended_account_gets_no_code_and_its_tokens_stop_working(client, monkeypatch):
    import db
    client_id, _, _, answer = _grant(client, monkeypatch)
    assert _mcp(client, answer["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 200
    with db.connect() as con:
        con.execute("UPDATE users SET suspended_at = 1 WHERE email = ?", (FOUNDER,))
    assert _mcp(client, answer["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 401
    _, challenge = _pkce()
    _google(monkeypatch)
    pending, csrf, _ = _consent_form(client, client_id, challenge)
    client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"})
    refused = _continue(client, pending)
    assert refused.status_code == 400 and "code=" not in refused.headers.get("location", "")
    assert refused.status_code == 400 and "code=" not in refused.headers.get("location", "")


# -- v3: the second independent review (F1-F7 and the court gaps) --------------
def _browser():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False, follow_redirects=False, base_url="https://testserver")


def _live(client_id):
    import db
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) FROM oauth_pending WHERE client_id = ?", (client_id,)).fetchone()[0]


def _authorize_params(client_id, challenge, redirect=REDIRECT, **extra):
    return {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "st-1", "scope": "mcp:read", **extra}


def test_F1_the_founders_browser_cannot_be_made_to_approve_a_request_opened_elsewhere(monkeypatch):
    """The attacker opens the request in his browser, scrapes pending+csrf, and has the
    founder's browser POST them (a cross-site form, or any page the founder visits)."""
    import db
    attacker, founder = _browser(), _browser()
    evil = "https://attacker.example/cb"
    client_id = _register(attacker, evil)
    started = _google(monkeypatch)
    _, challenge = _pkce()
    pending, csrf, _ = _consent_form(attacker, client_id, challenge, evil)
    # The founder has his own request open too; its cookie must not stand in for another.
    _consent_form(founder, client_id, challenge, evil)
    for decision in ("approve", "deny"):
        forged = founder.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": decision})
        assert forged.status_code == 400, (decision, forged.status_code, forged.headers.get("location"))
    assert "mcp_grant" not in started, "nothing went to Google for the forged approval"
    with db.connect() as con:
        assert con.execute("SELECT approved FROM oauth_pending WHERE id = ?", (pending,)).fetchone()[0] == 0


def test_F1_a_login_csrf_through_google_still_gives_the_attacker_nothing(monkeypatch):
    """The attacker approves in HIS browser and has the founder finish Google in his."""
    import db
    attacker, founder = _browser(), _browser()
    evil = "https://attacker.example/cb"
    client_id = _register(attacker, evil)
    _google(monkeypatch)
    _, challenge = _pkce()
    pending, csrf, _ = _consent_form(attacker, client_id, challenge, evil)
    assert attacker.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    # The attacker's Google state, finished in the founder's browser (his account).
    stolen = _callback(founder, pending)
    assert stolen.status_code == 400 and "location" not in stolen.headers, "no continue value is ever issued"
    with db.connect() as con:
        assert tuple(con.execute("SELECT verified_email, continue_hash FROM oauth_pending WHERE id = ?",
                                 (pending,)).fetchone()) == (None, None), "the founder's identity was not recorded"
    r = attacker.get("/oauth/continue")            # his browser, his cookie, nothing to present
    assert r.status_code == 400 and "location" not in r.headers
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_codes").fetchone()[0] == 0


@pytest.mark.parametrize("bad", ["https://evil.example\\@spark.example/cb", "https://evil.example\\spark.example/cb",
                                 "https://user@spark.example/cb", "https://user:pw@spark.example/cb",
                                 "https://spark.example/c b", "https://spark.example/cb\t", "https://spark.example/cb\x00",
                                 "https://spark.example/cb\x7f", " https://spark.example/cb"])
def test_F2_a_redirect_with_a_backslash_userinfo_whitespace_or_control_character_is_refused(client, bad):
    import db
    import oauth_mcp
    assert client.post("/oauth/register", json={"redirect_uris": [bad]}).status_code == 400
    # A client row that predates the rule still never gets that redirect honoured.
    oauth_mcp._ensure()
    with db.connect() as con:
        con.execute("INSERT INTO oauth_clients VALUES (?, ?, ?, ?)", ("mcp_client_old", json.dumps([bad]), "Old", 1))
    _, challenge = _pkce()
    r = client.get("/oauth/authorize", params=_authorize_params("mcp_client_old", challenge, bad))
    assert r.status_code == 400 and "location" not in r.headers


def test_F3_the_consent_page_lets_its_form_reach_google_and_the_clients_origin_only(client):
    client_id = _register(client)
    _, challenge = _pkce()
    _, _, page = _consent_form(client, client_id, challenge)
    policy = page.headers["content-security-policy"]
    action = [part.split()[1:] for part in policy.split(";") if part.split()[:1] == ["form-action"]]
    assert action and sorted(action[0]) == sorted(["'self'", "https://accounts.google.com", "https://spark.example.test"]), policy
    assert "frame-ancestors 'none'" in policy and "default-src 'none'" in policy


def test_F4_unfinished_requests_are_capped_per_client_and_per_address(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_CLIENT", 2, raising=False)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 3, raising=False)
    first, second = _register(client), _register(client)
    _, challenge = _pkce()
    for _ in range(2):
        _consent_form(client, first, challenge)
    assert client.get("/oauth/authorize", params=_authorize_params(first, challenge)).status_code == 503
    _consent_form(client, second, challenge)       # another client from the same address: 3rd
    assert client.get("/oauth/authorize", params=_authorize_params(second, challenge)).status_code == 503
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    elsewhere = client.get("/oauth/authorize", params=_authorize_params(second, challenge),
                           headers={"Fly-Client-IP": "203.0.113.9"})
    assert elsewhere.status_code == 200, "one address filling its share never locks out another"


def test_F5_a_suspended_account_gets_no_tokens_from_a_code_or_a_refresh(client, monkeypatch):
    import db
    client_id, _, _, answer = _grant(client, monkeypatch)
    verifier, challenge = _pkce()
    code = _code(client, monkeypatch, client_id, challenge)
    with db.connect() as con:
        con.execute("UPDATE users SET suspended_at = 1 WHERE email = ?", (FOUNDER,))
    refresh = _token(client, grant_type="refresh_token", refresh_token=answer["refresh_token"], client_id=client_id)
    assert refresh.status_code == 400 and refresh.json()["error"] == "invalid_grant", refresh.text
    redeem = _token(client, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                    client_id=client_id, code_verifier=verifier)
    assert redeem.status_code == 400 and redeem.json()["error"] == "invalid_grant", redeem.text
    with db.connect() as con:
        con.execute("UPDATE users SET suspended_at = NULL WHERE email = ?", (FOUNDER,))
    again = _token(client, grant_type="refresh_token", refresh_token=answer["refresh_token"], client_id=client_id)
    assert again.status_code == 400, "a refresh refused while suspended is spent, not replayable"


def test_F6_the_continue_url_carries_no_email_no_request_id_and_works_once_in_the_approving_browser(client, monkeypatch):
    import db
    client_id = _register(client)
    _, challenge = _pkce()
    _google(monkeypatch)
    pending, csrf, _ = _consent_form(client, client_id, challenge)
    client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"})
    back = _continue_path(_callback(client, pending))
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(back).query)
    assert list(query) == ["c"], back
    for leak in (FOUNDER, urllib.parse.quote(FOUNDER), pending):
        assert leak not in back and leak not in urllib.parse.unquote(back)
    for value in query["c"]:
        for piece in value.split("."):
            try:
                decoded = base64.urlsafe_b64decode(piece + "=" * (-len(piece) % 4))
            except Exception:
                continue
            assert FOUNDER.encode() not in decoded and pending.encode() not in decoded
    done = client.get(back)
    assert done.status_code == 302 and "code=" in done.headers["location"]
    assert done.headers.get("referrer-policy") == "no-referrer"
    assert client.get(back).status_code == 400, "a continue value is single-use"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_pending").fetchone()[0] == 0


def test_F7_an_overlong_state_is_refused_not_truncated(client):
    import db
    import oauth_mcp
    client_id = _register(client)
    _, challenge = _pkce()
    assert client.get("/oauth/authorize", params=_authorize_params(client_id, challenge, state="s" * 512)).status_code == 200
    r = client.get("/oauth/authorize", params=_authorize_params(client_id, challenge, state="s" * 513))
    assert r.status_code == 400 and "location" not in r.headers
    oauth_mcp._ensure()
    with db.connect() as con:
        assert [len(row[0]) for row in con.execute("SELECT state FROM oauth_pending")] == [512]


def test_concurrent_redemptions_that_both_read_the_code_still_issue_one_token(client, monkeypatch):
    """Both redemptions are held after their SELECT and before their consuming UPDATE,
    so the only thing between them is the UPDATE's own condition (the atomicity)."""
    import db
    client_id = _register(client)
    verifier, challenge = _pkce()
    code = _code(client, monkeypatch, client_id, challenge)
    gate, real = threading.Barrier(2, timeout=20), db.connect

    class Held:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args):
            if sql.startswith("UPDATE oauth_codes"):
                gate.wait()
            return self._con.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._con, name)

    @contextlib.contextmanager
    def held():
        with real() as con:
            yield Held(con)
    monkeypatch.setattr(db, "connect", held)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "client_id": client_id, "code_verifier": verifier}
    results = []
    threads = [threading.Thread(target=lambda: results.append(_token(client, **form).status_code)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    monkeypatch.setattr(db, "connect", real)
    assert sorted(results) == [200, 400], results
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_tokens").fetchone()[0] == 2, "one access + one refresh, once"


def test_no_code_token_or_browser_secret_reaches_any_log_stream_or_row(client, monkeypatch, caplog, capfd):
    import db
    import logging
    caplog.set_level(logging.DEBUG)
    client_id, code, _, answer = _grant(client, monkeypatch)
    out, err = capfd.readouterr()
    with db.connect() as con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        dump = json.dumps([[dict(row) for row in con.execute("SELECT * FROM %s" % table)] for table in tables], default=str)
    secrets_seen = [code, answer["access_token"], answer["refresh_token"]]
    for secret in secrets_seen:
        for stream, text in (("rows", dump), ("logging", caplog.text), ("stdout", out), ("stderr", err)):
            assert secret not in text, "%s leaked into %s" % (secret[:12], stream)


# -- v3.1: the review of 1abb4fb1 (M1, L1-L4 and the court gaps) --------------
@pytest.fixture
def clock(monkeypatch):
    """oauth_mcp's own clock, moved forward without touching Google's state expiry."""
    import oauth_mcp
    now = {"offset": 0}
    real = time.time
    monkeypatch.setattr(oauth_mcp, "time", types.SimpleNamespace(time=lambda: real() + now["offset"]))
    return now


def test_L1_a_leaked_state_finished_in_another_browser_records_nothing(monkeypatch):
    """The victim approves; the attacker finishes Google with the leaked state in HIS
    browser and HIS account, to link the victim's client to the attacker's account."""
    import db
    victim, attacker = _browser(), _browser()
    client_id = _register(victim)
    _, challenge = _pkce()
    _google(monkeypatch, email="attacker@evil.example")
    pending, csrf, _ = _consent_form(victim, client_id, challenge)
    assert victim.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    stolen = _callback(attacker, pending)
    assert stolen.status_code == 400 and "location" not in stolen.headers
    with db.connect() as con:
        assert con.execute("SELECT verified_email FROM oauth_pending WHERE id = ?", (pending,)).fetchone()[0] is None
    _google(monkeypatch, email=FOUNDER)
    done = _continue(victim, pending)
    assert done.status_code == 302 and "code=" in done.headers["location"], "the victim still finishes normally"
    with db.connect() as con:
        owner = con.execute("SELECT u.email FROM oauth_codes c JOIN users u ON u.id = c.user_id").fetchall()
    assert [row[0] for row in owner] == [FOUNDER]


@pytest.mark.parametrize("bad", ["https://spark.example;x/cb", "https://a.example,b.example/cb",
                                 "https://spark.example'x/cb", 'https://spark.example"x/cb',
                                 "https://spark.example:123456/cb", "https://-spark.example/cb"])
def test_L3_a_redirect_authority_that_could_reach_the_policy_is_refused(client, bad):
    import db
    import oauth_mcp
    assert client.post("/oauth/register", json={"redirect_uris": [bad]}).status_code == 400
    oauth_mcp._ensure()
    with db.connect() as con:
        con.execute("INSERT INTO oauth_clients VALUES (?, ?, ?, ?)", ("mcp_client_old", json.dumps([bad]), "Old", 1))
    _, challenge = _pkce()
    r = client.get("/oauth/authorize", params=_authorize_params("mcp_client_old", challenge, bad))
    assert r.status_code == 400 and "content-security-policy" not in r.headers


def test_L3_ordinary_redirects_still_register(client):
    for good in ("https://spark.example.test/oauth/callback", "https://www.notion.so/oauth/cb?x=1",
                 "http://127.0.0.1:43120/cb", "http://localhost:8080/cb", "http://[::1]:8080/cb"):
        assert client.post("/oauth/register", json={"redirect_uris": [good]}).status_code == 201, good


def test_L2_approving_ones_own_requests_frees_no_room(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_CLIENT", 2)
    _google(monkeypatch)
    client_id = _register(client)
    _, challenge = _pkce()
    for _ in range(2):
        pending, csrf, _ = _consent_form(client, client_id, challenge)
        assert client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    assert client.get("/oauth/authorize", params=_authorize_params(client_id, challenge)).status_code == 503


def test_M1_ipv6_callers_are_counted_per_64(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 2)
    client_id = _register(client)
    _, challenge = _pkce()
    for host in ("2001:db8:1:2::1", "2001:db8:1:2::2"):
        r = client.get("/oauth/authorize", params=_authorize_params(client_id, challenge), headers={"Fly-Client-IP": host})
        assert r.status_code == 200
    rotated = client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                         headers={"Fly-Client-IP": "2001:db8:1:2:ffff:ffff:ffff:ffff"})
    assert rotated.status_code == 503, "a new address inside the same /64 is the same caller"
    other = client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                       headers={"Fly-Client-IP": "2001:db8:1:3::1"})
    assert other.status_code == 200


def test_M1_anonymous_floods_never_take_the_room_of_a_client_someone_approved(client, monkeypatch):
    import oauth_mcp
    known, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING", 2)
    spam = _register(client, "https://spam.example/cb")
    _, challenge = _pkce()
    assert client.get("/oauth/authorize", params=_authorize_params(known, challenge)).status_code == 200
    stranger = _browser()
    for _ in range(3):
        _consent_form(stranger, spam, challenge, "https://spam.example/cb")
    assert _live(spam) == 2, "the anonymous pool rotates its own requests"
    assert _live(known) == 1, "the founder's request is outside the pool and is never rotated out by it"


def test_L4_a_client_sent_fly_client_ip_is_ignored_off_fly(client, monkeypatch):
    import oauth_mcp
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 2)
    client_id = _register(client)
    _, challenge = _pkce()
    answers = [client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                          headers={"Fly-Client-IP": "198.51.100.%d" % n}).status_code for n in range(1, 4)]
    assert answers == [200, 200, 503], answers


def test_the_consent_cookie_is_host_only_secure_httponly_and_lax(client):
    import oauth_mcp
    client_id = _register(client)
    _, challenge = _pkce()
    _, _, page = _consent_form(client, client_id, challenge)
    cookies = [value for key, value in page.headers.multi_items() if key.lower() == "set-cookie"]
    assert len(cookies) == 1, cookies
    parts = [part.strip() for part in cookies[0].split(";")]
    assert parts[0].split("=", 1)[0] == "__Host-archhub_mcp_consent"
    attrs = {part.split("=", 1)[0].lower(): (part.split("=", 1)[1] if "=" in part else True) for part in parts[1:]}
    assert attrs.get("secure") is True and attrs.get("httponly") is True, attrs
    assert str(attrs.get("samesite")).lower() == "lax" and attrs.get("path") == "/" and "domain" not in attrs, attrs
    assert 0 < int(attrs["max-age"]) <= oauth_mcp.PENDING_TTL


def _approved(client, monkeypatch):
    _google(monkeypatch)
    client_id = _register(client)
    _, challenge = _pkce()
    pending, csrf, _ = _consent_form(client, client_id, challenge)
    return client_id, pending, csrf


def test_an_expired_request_cannot_be_approved(client, monkeypatch, clock):
    import oauth_mcp
    _, pending, csrf = _approved(client, monkeypatch)
    clock["offset"] = oauth_mcp.PENDING_TTL + 1
    assert client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 400


def test_an_expired_request_is_not_verified_by_google(client, monkeypatch, clock):
    import oauth_mcp
    _, pending, csrf = _approved(client, monkeypatch)
    assert client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    clock["offset"] = oauth_mcp.PENDING_TTL + 1
    back = _callback(client, pending)
    assert back.status_code == 400 and "location" not in back.headers


def test_an_expired_request_cannot_be_continued(client, monkeypatch, clock):
    import oauth_mcp
    _, pending, csrf = _approved(client, monkeypatch)
    assert client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    path = _continue_path(_callback(client, pending))
    clock["offset"] = oauth_mcp.PENDING_TTL + 1
    r = client.get(path)
    assert r.status_code == 400 and "location" not in r.headers


def test_an_expired_code_is_refused(client, monkeypatch, clock):
    import oauth_mcp
    client_id = _register(client)
    verifier, challenge = _pkce()
    code = _code(client, monkeypatch, client_id, challenge)
    clock["offset"] = oauth_mcp.CODE_TTL + 1
    r = _token(client, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
               client_id=client_id, code_verifier=verifier)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_an_expired_access_token_stops_working(client, monkeypatch, clock):
    import oauth_mcp
    _, _, _, answer = _grant(client, monkeypatch)
    assert _mcp(client, answer["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 200
    clock["offset"] = oauth_mcp.ACCESS_TTL + 1
    assert _mcp(client, answer["access_token"], "tools/call", {"name": "brain.health", "arguments": {}})[0] == 401


def test_an_expired_refresh_token_is_refused(client, monkeypatch, clock):
    import oauth_mcp
    client_id, _, _, answer = _grant(client, monkeypatch)
    clock["offset"] = oauth_mcp.REFRESH_TTL + 1
    r = _token(client, grant_type="refresh_token", refresh_token=answer["refresh_token"], client_id=client_id)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_the_production_access_log_never_carries_a_one_time_value(capfd):
    """The real uvicorn access log, as the Dockerfile runs it (--access-log --log-level debug)."""
    import logging
    import httpx
    import uvicorn
    import main
    import oauth_mcp
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=0, log_level="debug", access_log=True))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 30
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        assert getattr(oauth_mcp, "_ACCESS_FILTER", None) in logging.getLogger("uvicorn.access").filters, \
            "the redaction survives uvicorn's own logging configuration"
        values = ["C" + secrets.token_hex(12), "G" + secrets.token_hex(12), "S" + secrets.token_hex(12),
                  "D" + secrets.token_hex(12)]
        with httpx.Client(base_url="http://127.0.0.1:%d" % port) as http:
            http.get("/oauth/continue", params={"c": values[0]})
            http.get("/v1/auth/google/callback", params={"code": values[1], "state": values[2]})
            http.get("/oauth/authorize", params={"client_id": "nobody", "state": values[2]})
            http.get("/auth/return", params={"code": values[3]})
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        logged = "".join(capfd.readouterr())
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logging.getLogger(name).handlers.clear()
    assert "GET /oauth/continue" in logged and "GET /v1/auth/google/callback" in logged, logged[-3000:]
    assert "GET /auth/return" in logged, logged[-3000:]
    for value in values:
        assert value not in logged, "%s reached the access log" % value[:4]


# -- v3.2: the review of v3.1 (the reserve, per-client-per-address, courts) ----
def test_L1_a_forged_cookie_for_the_request_is_refused_at_google_by_the_browser_hash(monkeypatch):
    """The attacker knows the pending id (it is in the consent form) and sends a cookie
    naming it with his own secret; only browser_hash in the UPDATE stops him."""
    import db
    victim, attacker = _browser(), _browser()
    client_id = _register(victim)
    _, challenge = _pkce()
    _google(monkeypatch, email="attacker@evil.example")
    pending, csrf, _ = _consent_form(victim, client_id, challenge)
    assert victim.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    attacker.cookies.set("__Host-archhub_mcp_consent", pending + ".forged-secret")
    stolen = _callback(attacker, pending)
    assert stolen.status_code == 400 and "location" not in stolen.headers
    with db.connect() as con:
        assert con.execute("SELECT verified_email FROM oauth_pending WHERE id = ?", (pending,)).fetchone()[0] is None


def test_the_shared_pool_is_not_entered_by_approving_ones_own_client(client, monkeypatch):
    """Any Google account can approve its own client; that must not buy reserved room."""
    import oauth_mcp
    self_approved, _, _, _ = _grant(client, monkeypatch, email="someone.else@studio.example")
    founders, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING", 2)
    _, challenge = _pkce()
    assert client.get("/oauth/authorize", params=_authorize_params(founders, challenge)).status_code == 200
    stranger = _browser()
    for _ in range(3):
        assert stranger.get("/oauth/authorize", params=_authorize_params(self_approved, challenge)).status_code == 200
    assert _live(self_approved) == 2, "a self-approved client is in the shared pool and rotates within it"
    assert _live(founders) == 1


def test_a_suspended_founder_account_reserves_nothing(client, monkeypatch):
    import db
    import oauth_mcp
    founders, _, _, _ = _grant(client, monkeypatch)
    with db.connect() as con:
        con.execute("UPDATE users SET suspended_at = 1 WHERE email = ?", (FOUNDER,))
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING", 1)
    _, challenge = _pkce()
    for _ in range(2):
        assert client.get("/oauth/authorize", params=_authorize_params(founders, challenge)).status_code == 200
    assert _live(founders) == 1, "a suspended founder's client is in the shared pool (size 1 here)"


def test_a_full_storage_ceiling_ends_even_a_verified_strangers_request_and_says_so(client, monkeypatch):
    """Outside the founder's lane nothing is protected: finishing Google needs only some
    Google account. The ended request's person is sent back to their app."""
    import oauth_mcp
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_ALL", 1)
    _google(monkeypatch, email="someone.else@studio.example")
    client_id = _register(client)
    _, challenge = _pkce()
    first = _browser()
    pending, csrf, _ = _consent_form(first, client_id, challenge)
    assert first.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    back = _continue_path(_callback(first, pending))    # Google verified; the continue step is pending
    assert _browser().get("/oauth/authorize", params=_authorize_params(client_id, challenge)).status_code == 200
    ended = first.get(back)
    assert ended.status_code == 400 and "has ended" in ended.text, "the continue step says the sign-in ended"


def test_knowing_a_public_client_id_cannot_lock_that_client_out(client, monkeypatch):
    """With the shipped constants: one address's share of one client binds first."""
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    assert oauth_mcp.MAX_PENDING_PER_CLIENT < oauth_mcp.MAX_PENDING_PER_ADDRESS, "the per-client share must bind"
    public = _register(client)
    _, challenge = _pkce()
    attacker = {"Fly-Client-IP": "203.0.113.50"}
    answers = [client.get("/oauth/authorize", params=_authorize_params(public, challenge), headers=attacker).status_code
               for _ in range(oauth_mcp.MAX_PENDING_PER_CLIENT + 1)]
    assert answers == [200] * oauth_mcp.MAX_PENDING_PER_CLIENT + [503], answers
    other = client.get("/oauth/authorize", params=_authorize_params(_register(client), challenge), headers=attacker)
    assert other.status_code == 200, "the same address still reaches another client"
    founder = client.get("/oauth/authorize", params=_authorize_params(public, challenge),
                         headers={"Fly-Client-IP": "198.51.100.20"})
    assert founder.status_code == 200


def test_an_ipv4_mapped_caller_is_the_same_ipv4_caller(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 2)
    client_id = _register(client)
    _, challenge = _pkce()
    answers = [client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                          headers={"Fly-Client-IP": host}).status_code
               for host in ("198.51.100.7", "::ffff:198.51.100.7", "::ffff:c633:6407")]
    assert answers == [200, 200, 503], answers


@pytest.mark.parametrize("bad", ["https://[zz]/cb", "https://[::1/cb", "http://[/cb"])
def test_a_malformed_authority_is_a_400_not_a_500(client, bad):
    assert client.post("/oauth/register", json={"redirect_uris": [bad]}).status_code == 400


# -- v3.3: the review of v3.2 (the founder's client_id is public) ----------------
def test_the_founder_still_gets_a_slot_when_his_public_client_id_fills_the_ceiling(client, monkeypatch):
    """An attacker names the founder's approved client from many /64s until the storage
    ceiling is full; the founder's own authorize still gets a pending request, the
    oldest unapproved one is the one that goes, and an approved one is never evicted."""
    import db
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    founders, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_ALL", 6)
    _, challenge = _pkce()
    held = _browser()
    pending, csrf, _ = _consent_form(held, founders, challenge)
    assert held.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    attacker = _browser()
    for n in range(12):                       # the attacker: many /64s in many /48s
        r = attacker.get("/oauth/authorize", params=_authorize_params(founders, challenge),
                         headers={"Fly-Client-IP": "2001:db8:%x:%x::1" % (n, n)})
        assert r.status_code == 200, (n, r.status_code)
    founder = _browser()
    mine = founder.get("/oauth/authorize", params=_authorize_params(founders, challenge),
                       headers={"Fly-Client-IP": "198.51.100.44"})
    assert mine.status_code == 200 and "Approve" in mine.text, "the founder is never refused by the ceiling"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_pending").fetchone()[0] == 6
        assert con.execute("SELECT approved FROM oauth_pending WHERE id = ?", (pending,)).fetchone()[0] == 1, \
            "never-approved requests are evicted before an approved one"


def test_ipv6_callers_are_also_counted_per_48(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_NETWORK", 3)
    client_id = _register(client)
    _, challenge = _pkce()
    answers = [client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                          headers={"Fly-Client-IP": "2001:db8:7:%x::1" % n}).status_code for n in range(4)]
    assert answers == [200, 200, 200, 503], "four /64s of one /48 are one network"
    other = client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                       headers={"Fly-Client-IP": "2001:db8:8::1"})
    assert other.status_code == 200


def test_a_pending_table_made_before_the_network_column_is_upgraded(client):
    import db
    import oauth_mcp
    with db.connect() as con:
        con.execute("DROP TABLE IF EXISTS oauth_pending")
        con.execute(oauth_mcp.SCHEMA.split("CREATE TABLE IF NOT EXISTS oauth_pending")[1].split(");")[0]
                    .join(["CREATE TABLE oauth_pending", ")"]).replace("    network        TEXT NOT NULL DEFAULT '-',\n", "")
                    .replace("    continue_hash  TEXT,\n    lane           TEXT NOT NULL DEFAULT ''\n",
                             "    continue_hash  TEXT\n"))
        columns = {row[1] for row in con.execute("PRAGMA table_info(oauth_pending)")}
        assert "network" not in columns and "lane" not in columns, columns
    client_id = _register(client)
    _, challenge = _pkce()
    assert client.get("/oauth/authorize", params=_authorize_params(client_id, challenge)).status_code == 200
    with db.connect() as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(oauth_pending)")}
        assert "network" in columns and "lane" in columns, columns


# -- v3.4: the review of v3.3 --------------------------------------------------------------
def test_F1_a_flood_that_approves_its_own_requests_still_leaves_the_founder_a_slot(client, monkeypatch):
    """Approve needs only the attacker's own cookie and csrf, no sign-in; his approved
    rows must not become permanent. Only a Google-verified request is kept."""
    import db
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    _google(monkeypatch)
    founders, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_ALL", 6)
    _, challenge = _pkce()
    verified = _browser()
    kept, kept_csrf, _ = _consent_form(verified, founders, challenge)
    assert verified.post("/oauth/consent", data={"pending": kept, "csrf": kept_csrf, "decision": "approve"}).status_code == 302
    _continue_path(_callback(verified, kept))       # this one Google verified
    for n in range(12):
        attacker = _browser()
        page = attacker.get("/oauth/authorize", params=_authorize_params(founders, challenge),
                            headers={"Fly-Client-IP": "2001:db8:%x:%x::1" % (n, n)})
        assert page.status_code == 200, (n, page.status_code)
        pending = re.search(r'name=pending value="([^"]+)"', page.text).group(1)
        csrf = re.search(r'name=csrf value="([^"]+)"', page.text).group(1)
        assert attacker.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"},
                             headers={"Fly-Client-IP": "2001:db8:%x:%x::1" % (n, n)}).status_code == 302
    founder = _browser()
    mine = founder.get("/oauth/authorize", params=_authorize_params(founders, challenge),
                       headers={"Fly-Client-IP": "198.51.100.44"})
    assert mine.status_code == 200 and "Approve" in mine.text, "self-approved flood rows are evicted"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_pending").fetchone()[0] == 6
        assert con.execute("SELECT verified_email FROM oauth_pending WHERE id = ?", (kept,)).fetchone()[0] == FOUNDER, \
            "a Google-verified request survives every eviction"


def test_F2_ipv4_callers_are_also_counted_per_24(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_NETWORK", 3)
    client_id = _register(client)
    _, challenge = _pkce()
    answers = [client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                          headers={"Fly-Client-IP": "203.0.113.%d" % n}).status_code for n in range(1, 5)]
    assert answers == [200, 200, 200, 503], "four addresses of one /24 are one network"
    other = client.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                       headers={"Fly-Client-IP": "198.51.100.1"})
    assert other.status_code == 200


def test_F3_a_concurrent_first_request_adding_the_network_column_is_not_an_error(client, monkeypatch):
    """Two first requests after a deploy both see the column missing; the second ALTER
    finds it present. That must not surface as an error."""
    import contextlib
    import db
    import oauth_mcp
    oauth_mcp._ensure()                                 # the column exists now
    real = db.connect

    class Stale:
        def __init__(self, con):
            self._con = con
            self.looked = False

        def execute(self, sql, *args):
            if sql.startswith("PRAGMA table_info(oauth_pending)") and not self.looked:
                self.looked = True                      # the first look predates the other ALTER
                return [row for row in self._con.execute(sql, *args) if row[1] != "network"]
            return self._con.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._con, name)

    @contextlib.contextmanager
    def stale():
        with real() as con:
            yield Stale(con)
    monkeypatch.setattr(db, "connect", stale)
    oauth_mcp._ensure()
    monkeypatch.setattr(db, "connect", real)
    client_id = _register(client)
    _, challenge = _pkce()
    assert client.get("/oauth/authorize", params=_authorize_params(client_id, challenge)).status_code == 200


# -- v3.5: the founder's lane (review of v3.4) ----------------------------------------------
def _verified_flood(monkeypatch, client_id, challenge, count, emails):
    """Strangers approve and finish Google with their OWN accounts, never continuing."""
    import google_auth
    for n in range(count):
        email = emails[n % len(emails)]
        monkeypatch.setattr(google_auth, "verify_id_token",
                            (lambda e: lambda token: {"email": e, "email_verified": True})(email))
        stranger = _browser()
        page = stranger.get("/oauth/authorize", params=_authorize_params(client_id, challenge),
                            headers={"Fly-Client-IP": "2001:db8:%x:%x::1" % (n, n)})
        assert page.status_code == 200, (n, page.status_code)
        pending = re.search(r'name=pending value="([^"]+)"', page.text).group(1)
        csrf = re.search(r'name=csrf value="([^"]+)"', page.text).group(1)
        assert stranger.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
        _continue_path(_callback(stranger, pending))


def test_a_verified_request_flood_never_locks_the_founder_out(client, monkeypatch):
    import db
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    founders, _, _, _ = _grant(client, monkeypatch)        # this browser now carries his lane
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_ALL", 6)
    _, challenge = _pkce()
    lane = client.get("/oauth/authorize", params=_authorize_params(founders, challenge))
    assert lane.status_code == 200
    lane_row = re.search(r'name=pending value="([^"]+)"', lane.text).group(1)
    _google(monkeypatch)
    _verified_flood(monkeypatch, founders, challenge, 12, ["x%d@evil.example" % n for n in range(12)])
    mine = client.get("/oauth/authorize", params=_authorize_params(founders, challenge))
    assert mine.status_code == 200, "the founder's lane is outside every shared ceiling"
    stranger_room = _browser().get("/oauth/authorize", params=_authorize_params(founders, challenge),
                                   headers={"Fly-Client-IP": "198.51.100.44"})
    assert stranger_room.status_code == 200, "even without his lane he gets a slot: verified strangers are evicted"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_pending WHERE lane = ''").fetchone()[0] == 6
        assert con.execute("SELECT lane FROM oauth_pending WHERE id = ?", (lane_row,)).fetchone()[0] == FOUNDER, \
            "a request in the founder's lane is never evicted by strangers"


def test_a_cgnat_neighbour_filling_the_founders_address_and_network_never_blocks_him(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    founders, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 2)
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_NETWORK", 2)
    _, challenge = _pkce()
    shared = {"Fly-Client-IP": "100.64.0.9"}                # one carrier-grade NAT address
    neighbour = _browser()
    assert [neighbour.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=shared).status_code
            for _ in range(3)] == [200, 200, 503]
    assert client.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=shared).status_code == 200


def test_one_account_holds_at_most_two_verified_requests(client, monkeypatch):
    import db
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    _google(monkeypatch)
    client_id = _register(client)
    _, challenge = _pkce()
    _verified_flood(monkeypatch, client_id, challenge, 5, ["one@evil.example"])
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM oauth_pending WHERE verified_email = ?",
                           ("one@evil.example",)).fetchone()[0] == oauth_mcp.MAX_VERIFIED_PER_EMAIL


def test_the_lane_is_only_for_a_founder_browser_proven_by_a_signed_cookie(client, monkeypatch):
    import db
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 1)
    _, _, _, _ = _grant(client, monkeypatch, email="someone.else@studio.example")
    assert "__Host-archhub_mcp_founder" not in client.cookies, "a non-founder sign-in mints no lane"
    founders, _, _, _ = _grant(client, monkeypatch)
    lane = client.cookies.get("__Host-archhub_mcp_founder")
    assert lane, "a completed founder sign-in mints the lane cookie"
    _, challenge = _pkce()
    here = {"Fly-Client-IP": "203.0.113.77"}
    forged = _browser()
    body, _, mac = lane.partition(".")
    forged.cookies.set("__Host-archhub_mcp_founder", body + "." + ("0" if mac[0] != "0" else "1") + mac[1:])
    assert forged.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code == 200
    assert forged.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code == 503, \
        "a tampered lane cookie is an ordinary caller"
    assert client.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code == 200
    with db.connect() as con:
        con.execute("UPDATE users SET suspended_at = 1 WHERE email = ?", (FOUNDER,))
    assert client.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code == 503, \
        "a suspended founder has no lane"
    monkeypatch.setenv("FOUNDER_EMAIL", "someone.new@example.test")
    with db.connect() as con:
        con.execute("UPDATE users SET suspended_at = NULL WHERE email = ?", (FOUNDER,))
    assert client.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code == 503, \
        "an address no longer configured as founder has no lane"


def test_an_ended_sign_in_sends_the_person_back_to_their_app_or_says_so(client, monkeypatch):
    import oauth_mcp
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_ALL", 1)
    _google(monkeypatch, email="someone.else@studio.example")
    client_id = _register(client)
    _, challenge = _pkce()
    first = _browser()
    pending, csrf, _ = _consent_form(first, client_id, challenge)
    assert first.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    assert _browser().get("/oauth/authorize", params=_authorize_params(client_id, challenge)).status_code == 200
    back = _callback(first, pending)                     # his request was evicted meanwhile
    assert back.status_code == 302, back.text
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(back.headers["location"]).query))
    assert back.headers["location"].startswith(REDIRECT) and query["error"] == "access_denied" and query["state"] == "st-1"
    unknown = _callback(first, "no-such-request")
    assert unknown.status_code == 400 and "has ended" in unknown.text and "location" not in unknown.headers
    assert client.get("/oauth/continue", params={"c": "nothing"}).status_code == 400


def test_an_alter_that_fails_for_another_reason_is_still_an_error(client, monkeypatch):
    import contextlib
    import sqlite3
    import db
    import oauth_mcp
    real = db.connect

    class Broken:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args):
            if sql.startswith("PRAGMA table_info(oauth_pending)"):
                return [row for row in self._con.execute(sql, *args) if row[1] != "lane"]
            if sql.startswith("ALTER TABLE oauth_pending ADD COLUMN lane"):
                raise sqlite3.OperationalError("disk I/O error")
            return self._con.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._con, name)

    @contextlib.contextmanager
    def broken():
        with real() as con:
            yield Broken(con)
    monkeypatch.setattr(db, "connect", broken)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        oauth_mcp._ensure()


def test_the_founders_lane_is_bounded_by_his_own_oldest_requests(client, monkeypatch):
    import db
    import oauth_mcp
    founders, _, _, _ = _grant(client, monkeypatch)
    monkeypatch.setattr(oauth_mcp, "MAX_FOUNDER_LANE", 2)
    _, challenge = _pkce()
    rows = []
    for _ in range(3):
        page = client.get("/oauth/authorize", params=_authorize_params(founders, challenge))
        assert page.status_code == 200
        rows.append(re.search(r'name=pending value="([^"]+)"', page.text).group(1))
    with db.connect() as con:
        live = [row[0] for row in con.execute("SELECT id FROM oauth_pending WHERE lane = ?", (FOUNDER,))]
    assert sorted(live) == sorted(rows[1:]), "the lane holds at most MAX_FOUNDER_LANE; his own oldest goes"


def test_the_lane_key_is_domain_separated_from_the_state_secret(client, monkeypatch):
    """A cookie signed with the raw state secret (or any other use of it) is not a lane."""
    import base64 as b64
    import hashlib as hl
    import hmac as hm
    import google_auth
    import oauth_mcp
    monkeypatch.setenv("FLY_APP_NAME", "archhub-cloud")
    monkeypatch.setattr(oauth_mcp, "MAX_PENDING_PER_ADDRESS", 1)
    founders, _, _, _ = _grant(client, monkeypatch)
    body = b64.urlsafe_b64encode(json.dumps({"e": FOUNDER, "x": int(time.time()) + 3600},
                                            separators=(",", ":")).encode()).decode().rstrip("=")
    here = {"Fly-Client-IP": "203.0.113.88"}
    _, challenge = _pkce()
    for key in (google_auth._state_secret(), hl.sha256(google_auth._state_secret()).digest()):
        forged = _browser()
        forged.cookies.set("__Host-archhub_mcp_founder", body + "." + hm.new(key, body.encode(), hl.sha256).hexdigest())
        assert forged.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code in (200, 503)
        assert forged.get("/oauth/authorize", params=_authorize_params(founders, challenge), headers=here).status_code == 503, \
            "a cookie keyed without the lane's own label is an ordinary caller"
    assert oauth_mcp._lane_key() not in (google_auth._state_secret(), hl.sha256(google_auth._state_secret()).digest())


def test_a_stolen_lane_cookie_buys_queue_priority_and_never_a_code_for_the_founder(client, monkeypatch):
    import db
    founders, _, _, _ = _grant(client, monkeypatch)
    lane = client.cookies.get("__Host-archhub_mcp_founder")
    _, challenge = _pkce()
    # The founder has a request in flight.
    pending, csrf, _ = _consent_form(client, founders, challenge)
    assert client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    thief = _browser()
    thief.cookies.set("__Host-archhub_mcp_founder", lane)
    stolen = _callback(thief, pending)                      # the lane cookie is not the consent cookie
    assert stolen.status_code == 400 and "location" not in stolen.headers
    # The thief's own flow works (it is only queue priority) and yields a code for HIS account.
    _google(monkeypatch, email="thief@evil.example")
    code = _code(thief, monkeypatch, founders, challenge, email="thief@evil.example")
    with db.connect() as con:
        owner = con.execute("SELECT u.email FROM oauth_codes c JOIN users u ON u.id = c.user_id WHERE c.code_hash = ?",
                            (hashlib.sha256(code.encode()).hexdigest(),)).fetchone()[0]
    assert owner == "thief@evil.example"
