"""The desktop signs in to the cloud with an email account, not a typed box.

The audit of 2026-09-06 found the app made zero calls to the auth API: its
sign-up wizard wrote a localStorage flag, and the only real cloud identity on
the founder's machine was a cloud.json typed by hand. This court runs the
whole dance against a fake cloud: the app opens the browser on the cloud's
sign-in, the cloud lands a one-time code on the app's loopback, PKCE exchange
mints the token, /v1/me names the account, and cloud.json - the record the
relay and the brain already trust - holds it. Wrong state is refused, a
refused exchange fails out loud, sign-out forgets the session.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from nodelang import cloud_signin
from nodelang.cloud_session import signed_in_cloud_account

ROOT = Path(__file__).resolve().parents[1]


class _FakeCloud(BaseHTTPRequestHandler):
    """archhub-cloud as the desktop sees it: google/start, exchange, me, logout."""

    def log_message(self, fmt, *args):
        pass

    def _json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/v1/auth/google/start":
            self.server.seen.append(("google/start", query))
            if self.server.google_down:
                self._json(503, {"detail": "google_login_unconfigured"})
                return
            redirect = query["redirect"][0]
            state = query["state"][0]
            self._json(200, {"auth_url": redirect + "?" + urlencode(
                {"code": "one-time-code", "state": state})})
            return
        if parsed.path == "/v1/me":
            auth = self.headers.get("Authorization", "")
            self.server.seen.append(("me", auth))
            self._json(200, {"user_id": "u-42", "email": "Ahmed@Example.com", "plan": "studio"})
            return
        self._json(404, {"error": "no such route"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/auth/exchange":
            self.server.seen.append(("exchange", body))
            if self.server.refuse_exchange:
                self._json(400, {"error": "code_expired"})
                return
            self._json(200, {"token": "ah_" + "x" * 40, "expires_at": 4102444800})
            return
        if self.path == "/v1/auth/logout":
            self.server.seen.append(("logout", self.headers.get("Authorization", "")))
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "no such route"})


@pytest.fixture
def cloud():
    server = HTTPServer(("127.0.0.1", 0), _FakeCloud)
    server.seen = []
    server.google_down = False
    server.refuse_exchange = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _browser_that_follows(url: str) -> None:
    """The founder's browser: consent is instant, the cloud lands on the loopback."""
    urllib.request.urlopen(url, timeout=5).read()


def _wait(attempt, phases=("done", "failed"), seconds=10.0):
    started = time.monotonic()
    while attempt.status()["phase"] not in phases:
        assert time.monotonic() - started < seconds, attempt.status()
        time.sleep(0.02)
    return attempt.status()


def test_google_sign_in_lands_the_account_in_cloud_json(cloud, tmp_path):
    record = tmp_path / "ArchHub" / "brain" / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    attempt = cloud_signin.SignIn("google", base_url=base, path=record,
                                  opener=_browser_that_follows).start()
    state = _wait(attempt)
    assert state["phase"] == "done" and state["email"] == "ahmed@example.com", state
    held = json.loads(record.read_text(encoding="utf-8"))
    assert held["token"].startswith("ah_") and held["email"] == "ahmed@example.com"
    assert held["user_id"] == "u-42" and held["cloud_base_url"] == base
    assert signed_in_cloud_account(record) == "ahmed@example.com"
    kinds = [kind for kind, _ in cloud.seen]
    assert kinds == ["google/start", "exchange", "me"], kinds
    _, start_query = cloud.seen[0]
    assert start_query["client"] == ["desktop"] and start_query["code_challenge"][0]
    assert start_query["redirect"][0].startswith("http://127.0.0.1:")
    _, exchange_body = cloud.seen[1]
    assert exchange_body["code"] == "one-time-code" and exchange_body["code_verifier"]
    _, me_auth = cloud.seen[2]
    assert me_auth == "Bearer " + held["token"]


def test_the_magic_link_opens_the_cloud_sign_in_with_pkce(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    opened = []

    def browser(url):
        opened.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        # The cloud's /signin page mails a link; the link lands here.
        urllib.request.urlopen(query["redirect"][0] + "?" + urlencode(
            {"code": "mailed-code", "state": query["state"][0]}), timeout=5).read()

    attempt = cloud_signin.SignIn("magic", base_url=base, path=record, opener=browser).start()
    state = _wait(attempt)
    assert state["phase"] == "done", state
    parsed = urlparse(opened[0])
    query = parse_qs(parsed.query)
    assert parsed.path == "/signin" and query["client"] == ["desktop"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", query["challenge"][0]), "S256 challenge"
    assert query["redirect"][0].endswith("/cb")
    assert cloud.seen[0][1]["code"] == "mailed-code"


def test_a_wrong_state_is_refused_and_the_attempt_keeps_waiting(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    landed = {}

    def browser(url):
        query = parse_qs(urlparse(url).query)
        landed["redirect"] = query["redirect"][0]
        landed["state"] = query["state"][0]

    attempt = cloud_signin.SignIn("magic", base_url=base, path=record, opener=browser).start()
    _wait(attempt, phases=("waiting",))
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(landed["redirect"] + "?" + urlencode(
            {"code": "stolen", "state": "forged"}), timeout=5)
    assert refused.value.code == 400
    assert attempt.status()["phase"] == "waiting" and not record.exists()
    urllib.request.urlopen(landed["redirect"] + "?" + urlencode(
        {"code": "real", "state": landed["state"]}), timeout=5).read()
    assert _wait(attempt)["phase"] == "done"


def test_a_refused_exchange_fails_out_loud_and_writes_nothing(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    cloud.refuse_exchange = True
    base = f"http://127.0.0.1:{cloud.server_port}"
    attempt = cloud_signin.SignIn("google", base_url=base, path=record,
                                  opener=_browser_that_follows).start()
    state = _wait(attempt)
    assert state["phase"] == "failed" and state["error"] == "code_expired", state
    assert not record.exists()


def test_google_unavailable_is_named_before_any_browser_opens(cloud, tmp_path):
    cloud.google_down = True
    opened = []
    attempt = cloud_signin.SignIn(
        "google", base_url=f"http://127.0.0.1:{cloud.server_port}",
        path=tmp_path / "cloud.json", opener=opened.append).start()
    state = _wait(attempt)
    assert state["phase"] == "failed" and "google_login_unconfigured" in state["error"]
    assert opened == []


def test_sign_out_forgets_the_session_and_keeps_the_rest(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    cloud_signin.write_cloud_session(record, {
        "token": "ah_" + "y" * 40, "email": "ahmed@example.com", "user_id": "u-42",
        "cloud_base_url": base, "sync_cursor": "hlc-17"})
    assert cloud_signin.session_summary(record) == {"signed_in": True, "email": "ahmed@example.com"}
    out = cloud_signin.sign_out(record, wait=True)
    assert out == {"signed_in": False, "email": ""}
    held = json.loads(record.read_text(encoding="utf-8"))
    assert "token" not in held and "email" not in held and held["sync_cursor"] == "hlc-17"
    assert signed_in_cloud_account(record) is None
    assert cloud.seen == [("logout", "Bearer ah_" + "y" * 40)]


def test_a_second_click_joins_the_waiting_attempt(cloud, tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_signin, "_CURRENT", {"attempt": None})
    landed = {}
    opened = []

    def browser(url):
        opened.append(url)
        query = parse_qs(urlparse(url).query)
        landed["redirect"] = query["redirect"][0]
        landed["state"] = query["state"][0]

    base = f"http://127.0.0.1:{cloud.server_port}"
    first = cloud_signin.begin("magic", base_url=base, path=tmp_path / "cloud.json", opener=browser)
    assert first["phase"] in ("starting", "waiting")
    _wait(cloud_signin._CURRENT["attempt"], phases=("waiting",))
    again = cloud_signin.begin("google", base_url=base, path=tmp_path / "cloud.json", opener=browser)
    assert again["method"] == "magic" and len(opened) == 1, "one browser tab, not two"
    urllib.request.urlopen(landed["redirect"] + "?" + urlencode(
        {"code": "real", "state": landed["state"]}), timeout=5).read()
    _wait(cloud_signin._CURRENT["attempt"])
    assert cloud_signin.current_status()["phase"] == "done"


def test_only_the_two_real_methods_exist():
    with pytest.raises(ValueError):
        cloud_signin.SignIn("typed-box")
    assert cloud_signin.METHODS == ("google", "magic")


def test_the_app_declares_the_sign_in_routes():
    declared = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    for route in (
        '("GET", "/api/universal/cloud-session", "read")',
        '("GET", "/api/universal/cloud-signin", "read")',
        '("POST", "/api/universal/cloud-signin", "execute")',
        '("POST", "/api/universal/cloud-signout", "execute")',
    ):
        assert route in declared, route
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    for path in ("/api/universal/cloud-session", "/api/universal/cloud-signin",
                 "/api/universal/cloud-signout"):
        assert server.count(path) >= 1, path


def test_the_studio_signs_in_through_the_cloud_not_a_typed_email():
    studio = ROOT / "nodelang" / "studio"
    account = (studio / "studio-account.jsx").read_text(encoding="utf-8")
    assert "ARCHHUB_CLOUD_SIGNIN" in account and "Continue with Google" in account
    assert "Email me a sign-in link" in account
    assert "field('WORK EMAIL'" not in account, "a typed email is not an identity"
    page = (studio / "studio.html").read_text(encoding="utf-8")
    for name in ("ARCHHUB_CLOUD_SESSION", "ARCHHUB_CLOUD_SIGNIN",
                 "ARCHHUB_CLOUD_SIGNIN_STATUS", "ARCHHUB_CLOUD_SIGNOUT"):
        assert name in page, name
    shell = (studio / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "ARCHHUB_CLOUD_SIGNOUT" in shell and "ARCHHUB_CLOUD_SESSION" in shell


def test_the_mailed_link_lands_with_the_clouds_fixed_marker(cloud, tmp_path):
    """/auth/return forwards state "archhub" on the magic path (the mailed link
    carries no state). The magic attempt accepts that marker; the Google
    attempt does not, and a forged code still fails the PKCE exchange."""
    record = tmp_path / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    landed = {}

    def browser(url):
        query = parse_qs(urlparse(url).query)
        landed["redirect"] = query["redirect"][0]

    attempt = cloud_signin.SignIn("magic", base_url=base, path=record, opener=browser).start()
    _wait(attempt, phases=("waiting",))
    urllib.request.urlopen(landed["redirect"] + "?" + urlencode({"code": "mailed", "state": "archhub"}), timeout=5).read()
    assert _wait(attempt)["phase"] == "done"

    opened = []
    google = cloud_signin.SignIn("google", base_url=base, path=tmp_path / "g.json", opener=lambda url: opened.append(url)).start()
    _wait(google, phases=("waiting",))
    # The fake cloud's auth_url IS the loopback with the right state; hit the
    # same loopback with the marker instead and expect the refusal.
    loopback = opened[0].split("?")[0]
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(loopback + "?" + urlencode({"code": "x", "state": "archhub"}), timeout=5)
    assert refused.value.code == 400
    google.cancel()


def test_a_cloud_that_drops_the_exchange_fails_out_loud(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"

    def http(method, url, **options):
        if url.endswith("/v1/auth/exchange"):
            raise TimeoutError("timed out")
        return cloud_signin.http_json(method, url, **options)

    attempt = cloud_signin.SignIn("google", base_url=base, path=record, opener=_browser_that_follows, http=http).start()
    state = _wait(attempt)
    assert state["phase"] == "failed" and "did not answer the exchange" in state["error"]
    assert not record.exists()


def test_sign_out_returns_before_the_cloud_answers(tmp_path):
    """The app serves sign-out under its one mutation lock: the file is cleared
    at once and the cloud is told on its own thread."""
    record = tmp_path / "cloud.json"
    cloud_signin.write_cloud_session(record, {"token": "ah_" + "z" * 40, "email": "a@b.c", "cloud_base_url": "http://127.0.0.1:9"})
    started = threading.Event()
    released = threading.Event()

    def slow_http(method, url, **options):
        started.set()
        released.wait(5)
        return 200, {}

    t0 = time.monotonic()
    out = cloud_signin.sign_out(record, http=slow_http)
    assert time.monotonic() - t0 < 1.0 and out == {"signed_in": False, "email": ""}
    assert signed_in_cloud_account(record) is None, "the file is forgotten before the cloud answers"
    assert started.wait(2), "the cloud is still told"
    released.set()
