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
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from nodelang import cloud_signin
from nodelang.cloud_session import DesktopAccess, signed_in_cloud_account

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
            if self.server.me_redirect:
                self.send_response(302)
                self.send_header("Location", self.server.me_redirect)
                self.end_headers()
                return
            accounts = self.server.me_accounts
            if self.server.me_status == 200 and accounts is not None:
                account = accounts.get(auth.removeprefix("Bearer "))
                self._json(200 if account else 401, account or {})
            else:
                self._json(self.server.me_status, self.server.me_body)
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
            if self.server.retire_on_exchange:
                self.server.me_accounts.pop(self.server.retire_on_exchange, None)
            self._json(200, {"token": self.server.exchange_token, "expires_at": 4102444800})
            return
        if self.path == "/v1/auth/logout":
            self.server.seen.append(("logout", self.headers.get("Authorization", "")))
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "no such route"})


@pytest.fixture
def cloud(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FakeCloud)
    # The stand-in cloud is pinned for this court only; the app pins its hosts.
    from nodelang import cloud_relay
    monkeypatch.setattr(cloud_relay, "PINNED_BASES", cloud_relay.PINNED_BASES
                        + ("http://127.0.0.1:%d" % server.server_port,))
    server.seen = []
    server.google_down = False
    server.refuse_exchange = False
    server.exchange_token = "ah_" + "x" * 40
    server.me_status = 200
    server.me_accounts = None
    server.retire_on_exchange = None
    server.me_redirect = None
    server.me_body = {"user_id": "u-42", "email": "Ahmed@Example.com", "plan": "studio"}
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
    held = cloud_signin.read_cloud_session(record)
    assert "token" not in json.loads(record.read_text(encoding="utf-8"))
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


def test_the_email_link_method_is_gone():
    """Google is the only sign-in (founder 2026-09-28): no email link."""
    with pytest.raises(ValueError):
        cloud_signin.SignIn("magic")


def test_a_wrong_state_is_refused_and_the_attempt_keeps_waiting(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    landed = {}

    def browser(url):
        # The fake cloud's Google auth_url IS the app's loopback + its state.
        landed["redirect"] = url.split("?")[0]
        landed["state"] = parse_qs(urlparse(url).query)["state"][0]

    attempt = cloud_signin.SignIn("google", base_url=base, path=record, opener=browser).start()
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


def test_sign_out_forgets_the_session_and_keeps_the_rest(tmp_path):
    """The bearer goes only to a pinned cloud host, never to the base the file names."""
    record = tmp_path / "cloud.json"
    cloud_signin.write_cloud_session(record, {
        "token": "ah_" + "y" * 40, "email": "ahmed@example.com", "user_id": "u-42",
        "cloud_base_url": "https://api.archhub.io", "sync_cursor": "hlc-17",
        "expires_at": 4_000_000_000})
    seen = []

    def http(method, url, *, body=None, headers=None, timeout=15.0):
        seen.append((method, url, (headers or {}).get("Authorization")))
        return (200, {"email": "ahmed@example.com", "founder": False}) if url.endswith("/v1/me") else (200, {})

    summary = cloud_signin.session_summary(record, http=http)
    assert (summary["state"], summary["signed_in"], summary["email"]) == (
        "signed_in", True, "ahmed@example.com")
    out = cloud_signin.sign_out(record, wait=True, http=http)
    assert out == {"signed_in": False, "email": ""}
    held = json.loads(record.read_text(encoding="utf-8"))
    assert "token" not in held and "email" not in held and held["sync_cursor"] == "hlc-17"
    assert signed_in_cloud_account(record) is None
    assert seen[-1] == ("POST", "https://api.archhub.io/v1/auth/logout", "Bearer ah_" + "y" * 40)


@pytest.mark.parametrize("raises", [False, True])
def test_browser_dispatch_failure_allows_a_fresh_attempt(cloud, tmp_path, monkeypatch, raises):
    monkeypatch.setattr(cloud_signin, "_CURRENT", {"attempt": None})
    record = tmp_path / "cloud.json"
    options = {"base_url": f"http://127.0.0.1:{cloud.server_port}", "path": record}

    def refused(url):
        if raises:
            raise OSError("private dispatch details " + url)
        return False

    cloud_signin.begin("google", opener=refused, **options)
    first = cloud_signin._CURRENT["attempt"]
    state = _wait(first)
    assert state["phase"] == "failed" and state["error_code"] == "browser_open_failed"
    assert state["url"] == "" and state["error"] == "Could not open the browser. Check your default browser and choose Retry."
    assert not record.exists()
    assert [kind for kind, _ in cloud.seen] == ["google/start"]
    cloud_signin.begin("google", opener=_browser_that_follows, **options)
    second = cloud_signin._CURRENT["attempt"]
    assert second is not first and _wait(second)["phase"] == "done"
    assert [kind for kind, _ in cloud.seen] == ["google/start", "google/start", "exchange", "me"]


def test_a_second_click_joins_the_waiting_attempt(cloud, tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_signin, "_CURRENT", {"attempt": None})
    landed = {}
    opened = []

    def browser(url):
        opened.append(url)
        landed["redirect"] = url.split("?")[0]
        landed["state"] = parse_qs(urlparse(url).query)["state"][0]

    base = f"http://127.0.0.1:{cloud.server_port}"
    first = cloud_signin.begin("google", base_url=base, path=tmp_path / "cloud.json", opener=browser)
    assert first["phase"] in ("starting", "waiting")
    _wait(cloud_signin._CURRENT["attempt"], phases=("waiting",))
    again = cloud_signin.begin("google", base_url=base, path=tmp_path / "cloud.json", opener=browser)
    assert again["method"] == "google" and len(opened) == 1, "one browser tab, not two"
    urllib.request.urlopen(landed["redirect"] + "?" + urlencode(
        {"code": "real", "state": landed["state"]}), timeout=5).read()
    _wait(cloud_signin._CURRENT["attempt"])
    assert cloud_signin.current_status()["phase"] == "done"


def test_google_is_the_only_method():
    for gone in ("typed-box", "magic"):
        with pytest.raises(ValueError):
            cloud_signin.SignIn(gone)
    assert cloud_signin.METHODS == ("google",)


def test_studio_endpoint_uses_one_google_login_and_reports_its_real_phase(cloud, tmp_path, monkeypatch):
    from nodelang import cloud_session
    from nodelang.nograph_server import NoGraphServer

    record = tmp_path / "login" / "cloud.json"
    base = f"http://127.0.0.1:{cloud.server_port}"
    monkeypatch.setattr(cloud_signin, "_CURRENT", {"attempt": None})
    monkeypatch.setattr(cloud_signin, "cloud_session_path", lambda: record)
    monkeypatch.setattr(cloud_session, "cloud_session_path", lambda: record)
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)
    monkeypatch.setattr(NoGraphServer, "ensure_cloud_relay", lambda _server: None)
    opened = []
    begin = cloud_signin.begin

    def browser_redirect(method):
        return begin(method, base_url=base, path=record, opener=opened.append)

    monkeypatch.setattr(cloud_signin, "begin", browser_redirect)
    server = NoGraphServer(tmp_path / "app", desktop_access=DesktopAccess(record)).start()

    def call(path, body=None, subject=""):
        request = urllib.request.Request(server.public_url + "/api/universal/" + path,
            data=json.dumps(body).encode() if body is not None else None, headers={
                "X-ArchHub-Session": server.browser_session_token,
                "X-ArchHub-CSRF": server.browser_csrf_token,
                "X-ArchHub-Desktop-Subject": subject,
                "Content-Type": "application/json",
            })
        try:
            with urllib.request.urlopen(request, timeout=8) as reply:
                return reply.status, json.load(reply)
        except urllib.error.HTTPError as failed:
            return failed.code, json.load(failed)

    try:
        assert call("desktop-access")[1]["state"] == "signed_out"
        assert call("cloud-session")[0] == 401
        assert "must be google" in call("cloud-signin", {"method": "magic", "email": "typed@example.com"})[1]["error"]
        assert opened == [] and cloud.seen == []
        assert call("cloud-signin", {"method": "google"})[0] == 200
        _wait(cloud_signin._CURRENT["attempt"], phases=("waiting",))
        assert call("cloud-signin")[1]["phase"] == "waiting"
        assert call("cloud-signin", {"method": "google"})[1]["phase"] == "waiting"
        assert len(opened) == 1
        assert not call("desktop-access")[1]["admitted"]
        _browser_that_follows(opened[0])
        assert _wait(cloud_signin._CURRENT["attempt"])["phase"] == "done"
        assert call("cloud-signin")[1]["phase"] == "done"
        assert call("desktop-access")[1]["subject"] == "u-42"
        assert call("cloud-session", subject="u-42")[0] == 200
        assert call("cloud-signout", {})[1]["signed_in"] is False
        assert call("desktop-access")[1]["state"] == "signed_out"
    finally:
        server.close()


def test_the_old_mailed_marker_is_refused(cloud, tmp_path):
    """The email link's fixed state "archhub" opened the loopback without
    this attempt's own state. With email sign-in gone, only the state this
    attempt sent through Google is accepted."""
    base = f"http://127.0.0.1:{cloud.server_port}"
    google = cloud_signin.SignIn("google", base_url=base, path=tmp_path / "g.json",
                                 opener=lambda _url: None).start()
    waiting = _wait(google, phases=("waiting",))
    loopback = waiting["url"].split("?", 1)[0]
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(loopback + "?" + urlencode({"code": "x", "state": "archhub"}), timeout=5)
    assert refused.value.code == 400
    assert google.status()["phase"] == "waiting"
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


def _saved_desktop_session(cloud, record):
    base = f"http://127.0.0.1:{cloud.server_port}"
    cloud_signin.write_cloud_session(record, {"token": "ah_" + "q" * 40,
                                               "email": "edited-metadata@example.com",
                                               "user_id": "edited-metadata",
                                               "cloud_base_url": base})
    return base


def test_desktop_access_fails_closed_and_recovers_with_a_fresh_cloud_answer(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    gate = DesktopAccess(record)
    assert gate.check()["state"] == "signed_out" and cloud.seen == []
    _saved_desktop_session(cloud, record)
    assert gate.check() == {"ok": True, "admitted": True, "state": "admitted",
                            "subject": "u-42", "email": "ahmed@example.com"}
    cloud.me_status = 503
    assert gate.check() == {"ok": True, "admitted": False, "state": "unavailable",
                            "subject": None, "email": None}
    cloud.me_status = 401
    assert gate.check()["state"] == "session_invalid"
    cloud.me_status = 200
    cloud.me_body = {"email": "unbound@example.net"}
    assert gate.check()["state"] == "unavailable"
    cloud.me_body = {"user_id": "u-43", "email": "UserB@example.com"}
    assert gate.check()["subject"] == "u-43"
    cloud_signin.write_cloud_session(record, {"expires_at": int(time.time()) - 1})
    previous = len(cloud.seen)
    assert gate.check()["state"] == "session_invalid" and len(cloud.seen) == previous


def test_desktop_access_does_not_forward_bearer_on_redirect(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    base = _saved_desktop_session(cloud, record)
    # Another actual HTTP endpoint should see zero requests, even on localhost.
    sink = HTTPServer(("127.0.0.1", 0), _FakeCloud)
    sink.seen = []
    worker = threading.Thread(target=sink.serve_forever, daemon=True)
    worker.start()
    cloud.me_redirect = f"http://127.0.0.1:{sink.server_port}/v1/me"
    try:
        assert DesktopAccess(record).check()["state"] == "unavailable"
        code, _ = cloud_signin.http_json("GET", base + "/v1/me",
                                       headers={"Authorization": "Bearer redirect-test"})
        assert code == 302
        assert len(cloud.seen) == 2 and sink.seen == []
    finally:
        sink.shutdown()
        sink.server_close()


def test_desktop_http_admission_protects_work_and_rebinds_initial_canvas(cloud, tmp_path, monkeypatch):
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import SessionFiles

    record = tmp_path / "cloud.json"
    state = tmp_path / "desktop"
    calls = []
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)

    def initial(_files, body, **options):
        if body["action"] == "run":
            cloud.me_status = 503  # Admission passed, but a downstream effect has not yet begun.
            return options["invoke"]("fixture", lambda *_: pytest.fail("offline effect dispatched"), {}, {})
        calls.append(body["action"])
        return {"ok": True, "path": "first-user-original.archhub"}

    monkeypatch.setattr(SessionFiles, "dispatch", initial)
    server = NoGraphServer(state, desktop_access=DesktopAccess(record)).start()

    def call(path, body=None, *, subject="u-42"):
        req = urllib.request.Request(server.public_url + path,
            data=json.dumps(body).encode() if body is not None else None, headers={
                "X-ArchHub-Session": server.browser_session_token,
                "X-ArchHub-CSRF": server.browser_csrf_token,
                "X-ArchHub-Desktop-Subject": subject,
                "Content-Type": "application/json",
            })
        try:
            with urllib.request.urlopen(req, timeout=8) as reply:
                return reply.status, json.load(reply)
        except urllib.error.HTTPError as failed:
            return failed.code, json.load(failed)

    status = "/api/universal/desktop-access"
    try:
        assert call(status)[1]["state"] == "signed_out"
        code, denied = call("/api/session-files", {"action": "initial"})
        assert (code, denied["code"], denied["state"], calls) == (401, "desktop_access_required", "signed_out", [])
        _saved_desktop_session(cloud, record)
        assert call(status)[1]["subject"] == "u-42"
        assert call("/api/session-files", {"action": "initial"})[1]["path"] == "first-user-original.archhub"
        code, rejected = call("/api/session-files", {"action": "run"})
        assert (code, rejected["code"], rejected["state"]) == (503, "desktop_access_required", "unavailable")
        assert call("/api/session-files", {"action": "initial"})[0] == 503
        cloud.me_status = 200
        cloud.me_body = {"user_id": "u-43", "email": "b@example.com"}
        assert call(status)[1]["subject"] == "u-43"
        assert call("/api/session-files", {"action": "initial"})[0] == 401
        assert call("/api/commands", subject="u-43")[0] == 200
        assert calls == ["initial"]
    finally:
        server.close()


def test_native_desktop_tool_and_trigger_are_blocked_without_cloud_admission(tmp_path):
    import anyio
    from mcp import types
    from nodelang.canvas_triggers import TriggerService
    from nodelang.native_agent_mcp import build_server

    gate = DesktopAccess(tmp_path / "cloud.json")
    server = build_server(desktop_access=gate, mailbox_call=lambda *_: pytest.fail("offline mailbox reached"))
    handler = server._mcp_server.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(params=types.CallToolRequestParams(name="task.list", arguments={}))
    result = anyio.run(handler, request).root
    assert result.isError
    assert json.loads(result.content[0].text)["code"] == "desktop_access_required"
    triggers = TriggerService(files=object(), require_access=gate.require)
    assert triggers.dispatch(("unopened.archhub", "t1"), "trigger.schedule", {}) == "desktop_access_required"
    assert not triggers.running and not triggers.fired


def test_cloud_answer_cannot_admit_after_local_signout(cloud, tmp_path):
    record = tmp_path / "cloud.json"
    _saved_desktop_session(cloud, record)

    def signout_during_probe(_endpoint, _bearer):
        cloud_signin.write_cloud_session(record, {"token": None})
        return 200, {"user_id": "u-42", "email": "a@example.com"}

    assert DesktopAccess(record, fetch=signout_during_probe).check()["state"] == "session_invalid"


def test_simultaneous_admissions_share_only_the_inflight_cloud_verdict(cloud, tmp_path, monkeypatch):
    from concurrent.futures import Future, ThreadPoolExecutor
    from nodelang import cloud_session

    record = tmp_path / "cloud.json"
    _saved_desktop_session(cloud, record)
    started, follower, release = threading.Event(), threading.Event(), threading.Event()
    calls = []

    class ObservedFuture(Future):
        def result(self):
            follower.set()
            return super().result()

    def fetch(_endpoint, _bearer):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
            return 200, {"user_id": "u-42", "email": "a@example.com"}
        return 503, {}

    monkeypatch.setattr(cloud_session, "Future", ObservedFuture)
    gate = DesktopAccess(record, fetch=fetch)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(gate.check)
        try:
            assert started.wait(5)
            second = workers.submit(gate.check)
            assert follower.wait(5)
        finally:
            release.set()
        assert first.result()["admitted"] and second.result()["admitted"]
    assert len(calls) == 1
    assert gate.check()["state"] == "unavailable"
    assert len(calls) == 2


def _desktop_request(server, path, *, body=None, subject=""):
    req = urllib.request.Request(server.public_url + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-ArchHub-Session": server.browser_session_token,
                 "X-ArchHub-CSRF": server.browser_csrf_token,
                 "X-ArchHub-Desktop-Subject": subject, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def test_queued_canvas_write_is_refused_even_if_the_cloud_reconnects(cloud, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from nodelang import canvas_documents
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import new_document, read_document, write_document

    record = tmp_path / "cloud.json"
    _saved_desktop_session(cloud, record)
    path = tmp_path / "fixture.archhub"
    document = new_document("Before")
    write_document(path, document)
    original = path.read_bytes()
    queued = threading.Event()
    lock = canvas_documents.locked

    @contextmanager
    def observing_lock(candidate, *args, **kwargs):
        if Path(candidate) == path:
            queued.set()
        with lock(candidate, *args, **kwargs):
            yield

    monkeypatch.setattr(canvas_documents, "locked", observing_lock)
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)
    server = NoGraphServer(tmp_path / "profile", desktop_access=DesktopAccess(record)).start()
    payload = {"action": "autosave", "path": str(path), "document": {**document, "title": "After"}}
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            with lock(path):
                write = workers.submit(_desktop_request, server, "/api/session-files", body=payload, subject="u-42")
                assert queued.wait(5)
                cloud.me_status = 503
                assert _desktop_request(server, "/api/universal/desktop-access")[1]["state"] == "unavailable"
                cloud.me_status = 200
                assert _desktop_request(server, "/api/universal/desktop-access")[1]["admitted"]
            code, result = write.result()
        assert (code, result["code"]) == (503, "desktop_access_required")
        assert path.read_bytes() == original
        status, _ = _desktop_request(server, "/api/session-files", body=payload, subject="u-42")
        assert status == 200 and read_document(path)["title"] == "After"
    finally:
        server.close()


def test_relaunch_automatically_recovers_only_the_bound_credentials(cloud, tmp_path, monkeypatch):
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import new_document, write_document

    state = tmp_path / "profile"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)
    metadata = state / "data/sessions"
    metadata.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "retained.archhub"
    document = new_document("Retained")
    write_document(path, document)
    original = path.read_bytes()
    pointer = metadata / "current.json"
    pointer.write_text(json.dumps({"id": document["id"], "path": str(path)}), encoding="utf-8")
    record = state / "brain/cloud.json"
    base = _saved_desktop_session(cloud, record)

    def open_as(subject):
        app = NoGraphServer(state, desktop_access=DesktopAccess(record)).start()
        app.native_file_picker = lambda *args: str(path)
        return app, lambda action: _desktop_request(app, "/api/session-files", body={"action": action}, subject=subject)

    server, call = open_as("u-42")
    try:
        assert call("initial")[1]["path"] == ""  # an unsigned legacy pointer is never replayed
        assert call("open")[1]["document"]["title"] == "Retained"
        assert "desktop_resume" in json.loads(pointer.read_bytes())
    finally:
        server.close()
    server, call = open_as("u-42")
    try:
        assert call("initial")[1]["path"] == str(path)
    finally:
        server.close()

    cloud_signin.write_cloud_session(record, {"token": "ah_" + "r" * 40, "cloud_base_url": base})
    cloud.me_body = {"user_id": "u-43", "email": "b@example.com"}
    monkeypatch.setattr("sys.argv", ["launcher.py", str(path)])  # an old deep link cannot bypass account binding
    server, call = open_as("u-43")
    try:
        assert call("initial")[1]["path"] == ""
        assert call("catalogue")[1]["recent"] == []
        assert call("open")[1]["document"]["title"] == "Retained"  # explicit Windows-profile picker still works
        assert path.read_bytes() == original
    finally:
        server.close()


def _sign_in_again(cloud, record, token):
    cloud.exchange_token = token
    attempt = cloud_signin.SignIn("google", base_url=f"http://127.0.0.1:{cloud.server_port}", path=record,
                                  opener=_browser_that_follows).start()
    assert _wait(attempt)["phase"] == "done"
    assert cloud_signin.read_cloud_session(record)["token"] == token


def test_same_verified_account_recovers_after_ordinary_sign_in_rotation(cloud, tmp_path, monkeypatch):
    import subprocess
    import sys
    from app import secrets_store
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import new_document, write_document

    state = tmp_path / "profile"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setattr(secrets_store, "_MEMORY_KEYS", {})
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)
    record = cloud_signin.cloud_session_path()
    base = f"http://127.0.0.1:{cloud.server_port}"
    old, renewed, other, returned = ("ah_" + char * 40 for char in "abcd")
    same_account = {"user_id": "u-42", "email": "changed@example.com"}
    cloud.me_accounts = {old: cloud.me_body, renewed: same_account,
                         other: {**same_account, "user_id": "u-43"}, returned: same_account}

    _sign_in_again(cloud, record, old)
    path = tmp_path / "existing.archhub"
    document = new_document("Retain across account credential changes")
    write_document(path, document)
    original = path.read_bytes()
    app = NoGraphServer(state, desktop_access=DesktopAccess(record)).start()

    def call(action, subject="u-42", **body):
        return _desktop_request(app, "/api/session-files", subject=subject, body={"action": action, **body})

    try:
        assert call("open", path=str(path))[1]["document"]["id"] == document["id"]
        metadata = state / "data" / "sessions"
        current, recent = (metadata / name for name in ("current.json", "recent.json"))
        before = current.read_bytes(), recent.read_bytes()
        assert json.loads(before[0])["desktop_resume"].startswith("v2:")
        cloud.retire_on_exchange = old
        _sign_in_again(cloud, record, renewed)
        assert call("initial")[1]["path"] == str(path)
        assert [row["path"] for row in call("catalogue")[1]["recent"]] == [str(path)]

        cloud.me_status = 503
        assert call("initial")[0] == 503
        cloud.me_status = 401
        assert call("catalogue")[0] == 401
        cloud.me_status = 200
        cloud_signin.sign_out(record, wait=True)
        assert call("initial")[0] == 401

        _sign_in_again(cloud, record, other)
        assert call("initial", subject="u-43")[1]["path"] == ""
        assert call("catalogue", subject="u-43")[1]["recent"] == []
        _sign_in_again(cloud, record, returned)
        assert call("initial")[1]["path"] == str(path)
        assert (current.read_bytes(), recent.read_bytes(), path.read_bytes()) == (*before, original)
    finally:
        app.close()

    # The court supplies only its synthetic vault entries to a new interpreter.
    # No in-process DesktopAccess signer, account cache or SessionFiles instance survives.
    probe = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app import secrets_store
from nodelang import cloud_relay
from nodelang.cloud_session import DesktopAccess
from nodelang.session_files import SessionFiles
cloud_relay.PINNED_BASES += (sys.argv[2],)
secrets_store._MEMORY_KEYS.update(json.load(sys.stdin))
auth = DesktopAccess(Path(sys.argv[3])).check(bind_resume=True)
assert auth["admitted"] and auth["subject"] == "u-42"
files = SessionFiles(sign_resume_pointer=auth["_sign_resume_pointer"])
print(json.dumps([files.dispatch({"action": "initial"})["path"], [row["path"] for row in files.recent()]]))
"""
    app_source = Path(__file__).resolve().parents[2] / "01.APP"
    child = subprocess.run([sys.executable, "-B", "-c", probe, str(app_source), base, str(record)],
                           input=json.dumps(secrets_store._MEMORY_KEYS), capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == [str(path), [str(path)]]
    assert (current.read_bytes(), recent.read_bytes(), path.read_bytes()) == (*before, original)
    key = next(value for value in secrets_store._MEMORY_KEYS.values() if re.fullmatch(r"[0-9a-f]{64}", value))
    assert all(key.encode() not in file.read_bytes() for file in (record, current, recent, path))


@pytest.mark.parametrize("legacy", ["still-admitted", "revoked-before-exchange", "first-read"])
def test_legacy_recovery_migrates_only_with_a_trusted_bearer(cloud, tmp_path, monkeypatch, legacy):
    import hmac
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import new_document, write_document

    state = tmp_path / "profile"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)
    record = cloud_signin.cloud_session_path()
    old, new = "ah_" + "x" * 40, "ah_" + "y" * 40
    cloud.me_accounts = {old: cloud.me_body, new: cloud.me_body}
    _sign_in_again(cloud, record, old)

    metadata = state / "data" / "sessions"
    metadata.mkdir(parents=True, exist_ok=True)
    current, recent = (metadata / name for name in ("current.json", "recent.json"))
    path = tmp_path / "legacy.archhub"
    document = new_document("Original legacy Canvas")
    write_document(path, document)
    original = path.read_bytes()

    def old_pointer(identity, location):
        payload = json.dumps(["u-42", identity, location], ensure_ascii=False, separators=(",", ":"))
        digest = hmac.digest(old.encode(), b"ArchHub desktop resume v1\0" + payload.encode(), "sha256").hex()
        return {"id": identity, "path": location, "desktop_resume": digest}

    good = old_pointer(str(path), str(path))
    forged = {**good, "path": str(tmp_path / "tampered.archhub")}
    unsigned = {"id": "unsigned", "path": str(tmp_path / "unsigned.archhub")}
    current.write_text(json.dumps(old_pointer(document["id"], str(path))), encoding="utf-8")
    recent.write_text(json.dumps([good, forged, unsigned]), encoding="utf-8")

    if legacy != "first-read":
        if legacy == "revoked-before-exchange":
            cloud.me_accounts.pop(old)
        cloud.retire_on_exchange = old
        _sign_in_again(cloud, record, new)
        assert not cloud.me_accounts.get(old)

    app = NoGraphServer(state, desktop_access=DesktopAccess(record)).start()
    app.native_file_picker = lambda *args: str(path)

    def call(action):
        return _desktop_request(app, "/api/session-files", body={"action": action}, subject="u-42")[1]

    try:
        if legacy == "revoked-before-exchange":
            assert call("initial")["path"] == ""
            assert call("catalogue")["recent"] == []
            assert not json.loads(current.read_bytes())["desktop_resume"].startswith("v2:")
            assert call("open")["document"]["id"] == document["id"]
        else:
            assert call("initial")["path"] == str(path)
            assert [row["path"] for row in call("catalogue")["recent"]] == [str(path)]
            assert json.loads(current.read_bytes())["desktop_resume"].startswith("v2:")
            from nodelang.user_paths import strip_test_write
            rows = strip_test_write(json.loads(recent.read_bytes()))
            assert rows[0]["desktop_resume"].startswith("v2:")
            assert rows[1:] == [forged, unsigned]
            pointer = json.loads(current.read_bytes())
            current.write_text(json.dumps({**pointer, "path": forged["path"]}), encoding="utf-8")
            assert call("initial")["path"] == ""
        assert path.read_bytes() == original
    finally:
        app.close()

@pytest.mark.parametrize("consumer", ["interface", "fork", "library", "settings"])
def test_implicit_canvas_consumers_follow_the_verified_account(cloud, tmp_path, monkeypatch, consumer):
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import catalogue, new_document, write_document

    state = tmp_path / "profile"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _server: None)
    record = cloud_signin.cloud_session_path()
    first, second = "ah_" + "a" * 40, "ah_" + "b" * 40
    cloud.me_accounts = {first: cloud.me_body, second: {**cloud.me_body, "user_id": "u-43"}}
    item = next(row for row in catalogue() if row["id"] == "n_text")

    def fixture(title):
        path = tmp_path / (title + ".archhub")
        doc = new_document(title)
        doc["properties"]["settings"] = {"Appearance.Theme": "Dark"}
        doc["nodes"].append({"id": "seed", "item": item["id"], "type": item["engine"],
                             "title": "Seed", "position": {"x": 0, "y": 0}, "params": item["params"]})
        write_document(path, doc)
        return path, doc["id"]

    a_path, a_id = fixture("First account")
    b_path, b_id = fixture("Second account")
    _sign_in_again(cloud, record, first)
    app = NoGraphServer(state, desktop_access=DesktopAccess(record)).start()
    app.files["settings"].update({"appearanceTheme": "Light", "settingsScope": "Session"})

    def request(route, body, subject):
        return _desktop_request(app, route, body=body, subject=subject)

    def open_file(path, subject):
        return request("/api/session-files", {"action": "open", "path": str(path)}, subject)

    def canvas(op, args, subject):
        return request("/api/universal/canvas-op", {"op": op, "args": args}, subject)

    def settings(function, subject, args=(), destination=None):
        body = {"function": function, "args": list(args)}
        if destination is not None:
            body["context"] = {"settingsDestination": destination}
        return request("/api/universal/settings-action", body, subject)

    def operate(subject, path):
        op, args = {
            "interface": ("add_interface_element", ["Button", str(path)]),
            "fork": ("fork_node", ["seed"]),
            "library": ("import_mcp_tool", ["disposable", "fixture tool"]),
        }[consumer]
        return canvas(op, args, subject)

    try:
        assert open_file(a_path, "u-42")[0] == 200
        if consumer == "settings":
            status, reply = settings("readEffectivePreferences", "u-42")
            assert status == 200 and reply["result"]["settingsDestination"]["session"] == a_id
        else:
            assert operate("u-42", a_path)[0] == 200
        original = a_path.read_bytes()

        _sign_in_again(cloud, record, second)
        if consumer == "settings":
            status, reply = settings("readEffectivePreferences", "u-43")
            assert status == 200
            result = reply["result"]
            assert result["settingsDestination"]["session"] == "" and not result["settingsScopes"]["Session"]
            assert next(row["value"] for row in result["appearanceSettings"] if row["id"] == "Appearance.Theme") == "Light"
            destination = result["settingsDestination"]
            assert settings("setSettingsScope", "u-43", ["User"], destination)[0] == 200
            status, reply = settings("exportPreferences", "u-43", ["All"])
            assert status == 200 and "Session" not in reply["result"]["settingsExport"]["scopes"]
        else:
            status, reply = operate("u-43", a_path)
            assert status == 409 and "Open a" in reply["error"]
            if consumer == "library":
                status, reply = canvas("prepare_mcp_tool", ["disposable", "fixture tool"], "u-43")
                assert status == 200 and reply["result"]["node"]["title"] == "fixture tool"
        assert a_path.read_bytes() == original

        assert open_file(b_path, "u-43")[0] == 200
        if consumer == "settings":
            status, reply = settings("readEffectivePreferences", "u-43")
            assert status == 200 and reply["result"]["settingsDestination"]["session"] == b_id
        else:
            assert operate("u-43", b_path)[0] == 200
        assert a_path.read_bytes() == original
    finally:
        app.close()

def test_mixed_legacy_recent_rows_keep_valid_entries_during_explicit_open(cloud, tmp_path, monkeypatch):
    from nodelang.session_files import SessionFiles, new_document, write_document
    from nodelang.user_paths import strip_test_write

    state = tmp_path / "profile"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    record = cloud_signin.cloud_session_path()
    _sign_in_again(cloud, record, "ah_" + "a" * 40)
    access = DesktopAccess(record).check(bind_resume=True)
    files = SessionFiles(sign_resume_pointer=access["_sign_resume_pointer"])
    old, legacy, opened = [tmp_path / (name + ".archhub") for name in ("older", "legacy", "newly opened")]
    for path in (old, legacy, opened):
        write_document(path, new_document(path.stem))
    original = {path: path.read_bytes() for path in (old, legacy, opened)}

    assert files.dispatch({"action": "open", "path": str(old)})["path"] == str(old)
    recent = files.metadata / "recent.json"
    signed = strip_test_write(json.loads(recent.read_bytes()))[0]
    unsigned = {"path": str(legacy), "title": "Legacy recent"}
    mixed = [None, {"path": []}, "old scalar", {}, unsigned, signed]
    recent.write_text(json.dumps(mixed), encoding="utf-8")
    before = recent.read_bytes()

    assert [row["path"] for row in SessionFiles().recent()] == [str(legacy), str(old)]
    assert [row["path"] for row in files.recent()] == [str(old)]
    assert recent.read_bytes() == before

    assert files.dispatch({"action": "open", "path": str(opened)})["path"] == str(opened)
    rows = strip_test_write(json.loads(recent.read_bytes()))
    assert rows[0]["path"] == str(opened) and rows[0]["desktop_resume"].startswith("v2:")
    assert rows[1:] == [unsigned, signed]
    assert [row["path"] for row in files.recent()] == [str(opened), str(old)]
    assert all(path.read_bytes() == content for path, content in original.items())
