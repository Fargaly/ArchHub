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


def _callback(pending):
    """Google's verified callback, through the real google_auth path: a continue URL, no code."""
    import google_auth
    state = google_auth.encode_state(code_challenge="", redirect="", mcp_grant=pending)
    back = google_auth.exchange_callback(code="google-code", state=state)
    assert back.startswith("https://api.archhub.io/oauth/continue")
    return back.replace("https://api.archhub.io", "")


def _code(client, monkeypatch, client_id, challenge, email=FOUNDER, redirect=REDIRECT):
    """Consent in this browser, then Google, then the continue step that mints the code."""
    started = _google(monkeypatch, email)
    pending, csrf, _ = _consent_form(client, client_id, challenge, redirect)
    r = client.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"})
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com"), r.text
    assert started["mcp_grant"] == pending
    back = client.get(_callback(pending))
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
    import google_auth
    try:
        denied = founder.get(_callback(pending))
    except google_auth.GoogleAuthError:
        denied = None                  # refused at Google's callback already
    assert denied is None or (denied.status_code == 400 and "code=" not in denied.headers.get("location", ""))
    # (c) The attacker approves in HIS browser and makes the founder finish Google in his:
    pending, csrf, _ = _consent_form(attacker, client_id, challenge, evil)
    assert attacker.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "approve"}).status_code == 302
    stolen = founder.get(_callback(pending))
    assert stolen.status_code == 400 and "code=" not in stolen.headers.get("location", "")
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
    assert r.status_code == 503


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
    refused = client.get(_callback(pending))
    assert refused.status_code == 400 and "code=" not in refused.headers.get("location", "")
    assert refused.status_code == 400 and "code=" not in refused.headers.get("location", "")


# -- v3: the second independent review (F1-F7 and the court gaps) --------------
def _browser():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False, follow_redirects=False, base_url="https://testserver")


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
    back = _callback(pending)                      # lands in the founder's browser
    assert founder.get(back).status_code == 400
    for attempt in (back, "/oauth/continue"):      # the attacker's browser, with his cookie
        r = attacker.get(attempt)
        assert r.status_code == 400 and "code=" not in r.headers.get("location", "")
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
    back = _callback(pending)
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
