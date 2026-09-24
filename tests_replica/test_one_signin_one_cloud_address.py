"""One sign-in, one cloud address (founder, 2026-09-24).

"we said one source for everything" / "how many places do we sign in to the
cloud and the cockpit?" / "how many domains?"

  (a) The cockpit opened from the app spends the app's own session
      (cloud.json, written by Settings > Account) for a one-time claim link,
      so it never asks to sign in again. The companion looked for cloud.json
      under LOCALAPPDATA while sign-in writes it under APPDATA, so its
      "Open the cockpit" never carried the session.
  (b) Settings > Account says what the session actually is: signed in until
      a date, or "sign-in expired" with a button. On 2026-09-24 it showed an
      email and "Sign out" over a 90-day-old token the cloud refused (403).
  (c) No code path defaults to archhub-cloud.fly.dev; the cloud is
      https://api.archhub.io.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from nodelang import cloud_relay, cloud_signin

ROOT = Path(__file__).resolve().parents[1]
FLY_HOST = "archhub-cloud.fly.dev"
BEARER = "ah_" + "s" * 40


import pytest


@pytest.fixture(autouse=True)
def _fresh_founder_answers(monkeypatch):
    """The founder answer lives in process memory only; each court starts empty."""
    monkeypatch.setattr(cloud_signin, "_FOUNDER", {})
    monkeypatch.setattr(cloud_signin, "_PROBED", {})


def _record(tmp_path: Path, **fields) -> Path:
    path = tmp_path / "ArchHub" / "brain" / "cloud.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    held = {"token": BEARER, "email": "founder@example.com",
            "cloud_base_url": "https://api.archhub.io"}
    held.update(fields)
    path.write_text(json.dumps(held), encoding="utf-8")
    return path


class _Cloud:
    """Stands in for http_json: records calls, answers per path."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, method, url, *, body=None, headers=None, timeout=15.0):
        self.calls.append((method, url, dict(headers or {})))
        for suffix, answer in self.answers.items():
            if url.endswith(suffix):
                return answer
        raise AssertionError("unexpected cloud call " + url)


# ---- (a) the cockpit opens on the app's session -------------------------------

def test_a_the_app_mints_the_cockpit_link_from_its_own_session(tmp_path):
    path = _record(tmp_path, expires_at=4_000_000_000)
    cloud = _Cloud({"/founder/api/browser-code": (
        200, {"claim_url": "https://api.archhub.io/founder/claim?code=one-time"})})
    link = cloud_signin.cockpit_link(path, http=cloud, now=1_900_000_000)
    assert link == {"ok": True, "state": "signed_in",
                    "url": "https://api.archhub.io/founder/claim?code=one-time"}
    method, url, headers = cloud.calls[0]
    assert (method, url) == ("POST", "https://api.archhub.io/founder/api/browser-code")
    assert headers["Authorization"] == "Bearer " + BEARER


def test_a_an_expired_session_never_opens_a_sign_in_page(tmp_path):
    path = _record(tmp_path, expires_at=1_000)
    cloud = _Cloud({})
    link = cloud_signin.cockpit_link(path, http=cloud, now=1_900_000_000)
    assert link["ok"] is False and link["state"] == "expired" and not link.get("url")
    assert cloud.calls == [], "an expired session must not be sent to the cloud"


def test_a_a_refused_session_is_recorded_as_expired(tmp_path):
    """401 is a refused session."""
    path = _record(tmp_path, expires_at=4_000_000_000)
    cloud = _Cloud({"/founder/api/browser-code": (401, {"detail": "invalid_token"})})
    link = cloud_signin.cockpit_link(path, http=cloud, now=1_900_000_000)
    assert link["ok"] is False and link["state"] == "expired"
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["state"] == "expired"


def test_a_a_stale_session_behind_founder_only_is_expired(tmp_path):
    """The cockpit says founder_only to a dead session too; /v1/me decides."""
    path = _record(tmp_path, expires_at=4_000_000_000)
    cloud = _Cloud({"/founder/api/browser-code": (403, {"detail": "founder_only"}),
                    "/v1/me": (401, {"detail": "invalid_token"})})
    link = cloud_signin.cockpit_link(path, http=cloud, now=1_900_000_000)
    assert link["state"] == "expired"
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["state"] == "expired"


def test_a_a_non_founder_403_keeps_the_session_signed_in(tmp_path):
    """Verifier finding 2026-09-24: another account's founder_only 403 read as expired."""
    path = _record(tmp_path, expires_at=4_000_000_000)
    cloud = _Cloud({"/founder/api/browser-code": (403, {"detail": "founder_only"}),
                    "/v1/me": (200, {"email": "founder@example.com", "founder": False})})
    link = cloud_signin.cockpit_link(path, http=cloud, now=1_900_000_000)
    assert link["ok"] is False and link["state"] == "signed_in" and link["founder"] is False
    state = cloud_signin.sign_in_state(path, now=1_900_000_000)
    assert state["state"] == "signed_in" and state["signed_in"] is True
    assert state["founder"] is False
    held = json.loads(path.read_text(encoding="utf-8"))
    assert "refused_at" not in held and "founder" not in held


def test_a_the_relay_never_lapses_a_non_founder_session(tmp_path, monkeypatch):
    import urllib.error
    path = _record(tmp_path, expires_at=4_000_000_000)
    monkeypatch.setattr(cloud_signin, "http_json", _Cloud(
        {"/v1/me": (200, {"email": "founder@example.com", "founder": False})}))
    relay = cloud_relay.CloudRelay(base_url="https://api.archhub.io", token=BEARER,
                                   respond=lambda text: {}, execute=lambda text: {},
                                   session_path=path)
    refused = urllib.error.HTTPError("https://api.archhub.io/founder/x", 403, "Forbidden", {}, None)
    relay._after_session_refused(refused)
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["state"] == "signed_in"
    relay._after_session_refused(
        urllib.error.HTTPError("https://api.archhub.io/founder/x", 401, "Unauthorized", {}, None))
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["state"] == "expired"


def test_a_the_companion_reads_the_one_session_record(tmp_path, monkeypatch):
    appdata, local = tmp_path / "roaming", tmp_path / "local"
    _record(appdata, expires_at=4_000_000_000)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    cloud = _Cloud({"/founder/api/browser-code": (
        200, {"claim_url": "https://api.archhub.io/founder/claim?code=c1"})})
    monkeypatch.setattr(cloud_signin, "http_json", cloud)
    assert cloud_relay.cockpit_url(appdata) == "https://api.archhub.io/founder/claim?code=c1"
    from nodelang import baboom_native_companion as companion
    helper = inspect.getsource(companion).split("def _open_cockpit", 1)[1].split("\n        def ", 1)[0]
    assert "LOCALAPPDATA" not in helper, "cloud.json lives under APPDATA"
    assert "https://api.archhub.io/founder" not in helper


def test_a_settings_opens_the_cockpit_inside_the_app():
    from nodelang.universal_application import _APPLICATION_HTTP_ROUTE_SPECS
    assert ("POST", "/api/universal/cockpit-link", "execute") in _APPLICATION_HTTP_ROUTE_SPECS
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "'/api/universal/cockpit-link'" in server and "cockpit_link(" in server
    html = (ROOT / "nodelang" / "studio" / "studio.html").read_text(encoding="utf-8")
    assert "window.ARCHHUB_COCKPIT_LINK" in html
    account = (ROOT / "nodelang" / "studio" / "studio-account.jsx").read_text(encoding="utf-8")
    assert "Open the cockpit" in account and "ARCHHUB_COCKPIT_LINK" in account
    assert "Link for another device" in account
    card = account.split("function CloudSessionCard", 1)[1].split("function SettingsAccount", 1)[0]
    gated = card.split("s.founder === true &&", 1)
    assert len(gated) == 2 and "Open the cockpit" in gated[1] and "Open the cockpit" not in gated[0], (
        "the cockpit button is offered only to the account that owns it")


def test_a_the_cloud_says_who_owns_the_cockpit(tmp_path):
    path = _record(tmp_path, expires_at=4_000_000_000)
    cloud = _Cloud({"/v1/me": (200, {"email": "founder@example.com", "founder": True})})
    assert cloud_signin.session_summary(path, now=1_900_000_000, http=cloud)["founder"] is True
    assert "founder" not in json.loads(path.read_text(encoding="utf-8")), "never written to the file"


def test_a_a_typed_founder_flag_is_not_trusted(tmp_path):
    """Verifier D2: "founder": true typed into cloud.json showed the cockpit buttons."""
    path = _record(tmp_path, expires_at=4_000_000_000, founder=True,
                   token="ah_" + "t" * 40)
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["founder"] is False
    cloud = _Cloud({"/v1/me": (200, {"email": "founder@example.com", "founder": False})})
    assert cloud_signin.session_summary(path, now=1_900_000_000, http=cloud)["founder"] is False
    assert [url for _m, url, _h in cloud.calls] == ["https://api.archhub.io/v1/me"]


def test_a_an_older_cloud_is_asked_on_its_founder_route(tmp_path):
    path = _record(tmp_path, expires_at=4_000_000_000, token="ah_" + "o" * 40)
    cloud = _Cloud({"/v1/me": (200, {"email": "founder@example.com"}),
                    "/founder/api/system": (200, {})})
    assert cloud_signin.session_summary(path, now=1_900_000_000, http=cloud)["founder"] is True


def test_a_a_forged_host_never_receives_the_session(tmp_path, monkeypatch):
    """Verifier D3: the bearer went to whatever host cloud.json named."""
    path = _record(tmp_path, expires_at=4_000_000_000, token="ah_" + "f" * 40,
                   cloud_base_url="https://evil.example")
    cloud = _Cloud({"/v1/me": (200, {"email": "founder@example.com", "founder": True}),
                    "/founder/api/browser-code": (
                        200, {"claim_url": "https://api.archhub.io/founder/claim?code=z"}),
                    "/v1/auth/logout": (200, {})})
    cloud_signin.session_summary(path, now=1_900_000_000, http=cloud)
    cloud_signin.cockpit_link(path, now=1_900_000_000, http=cloud)
    monkeypatch.setattr(cloud_relay, "DEFAULT_BASE", cloud_relay.DEFAULT_BASE)
    assert cloud_relay.cockpit_url(tmp_path).startswith("https://api.archhub.io/")
    cloud_signin.sign_out(path, http=cloud, wait=True)
    hosts = {url.split("/", 3)[2] for _m, url, _h in cloud.calls}
    assert hosts == {"api.archhub.io"}, hosts
    assert cloud_signin.pinned_base({"cloud_base_url": "https://archhub-cloud.fly.dev/"}) ==         "https://archhub-cloud.fly.dev"
    desktop = (ROOT / "nodelang" / "desktop.py").read_text(encoding="utf-8")
    assert "def createWindow" in desktop, "window.open must open an ArchHub window, not nothing"


# ---- (b) Settings > Account says the real state --------------------------------

def test_b_an_expired_record_reads_expired(tmp_path):
    path = _record(tmp_path, expires_at=1_000)
    state = cloud_signin.sign_in_state(path, now=1_900_000_000)
    assert state["state"] == "expired" and state["signed_in"] is False
    assert state["email"] == "founder@example.com"
    summary = cloud_signin.session_summary(path, now=1_900_000_000)
    assert summary["state"] == "expired" and summary["signed_in"] is False


def test_b_a_live_record_reads_signed_in_until(tmp_path):
    path = _record(tmp_path, expires_at=4_000_000_000)
    state = cloud_signin.sign_in_state(path, now=1_900_000_000)
    assert state == {"state": "signed_in", "signed_in": True, "founder": False,
                     "email": "founder@example.com", "expires_at": 4_000_000_000}


def test_b_a_record_without_expiry_is_asked_once(tmp_path):
    """Records written before expires_at was kept: the cloud says."""
    path = _record(tmp_path)
    cloud = _Cloud({"/v1/me": (401, {"detail": "invalid_token"})})
    state = cloud_signin.session_summary(path, now=1_900_000_000, http=cloud)
    assert state["state"] == "expired"
    assert cloud_signin.session_summary(path, now=1_900_000_000, http=_Cloud({}))["state"] == "expired"


def test_b_signing_in_again_clears_the_refusal(tmp_path):
    path = _record(tmp_path, expires_at=4_000_000_000)
    cloud_signin.record_refusal(path, BEARER, now=1_900_000_000)
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["state"] == "expired"
    cloud_signin.write_cloud_session(path, {"token": "ah_" + "n" * 40, "refused_at": None,
                                            "expires_at": 4_000_000_000})
    assert cloud_signin.sign_in_state(path, now=1_900_000_000)["state"] == "signed_in"
    source = inspect.getsource(cloud_signin.SignIn._run)
    assert '"refused_at": None' in source


def test_b_settings_shows_expired_and_the_date():
    account = (ROOT / "nodelang" / "studio" / "studio-account.jsx").read_text(encoding="utf-8")
    assert "Sign-in expired" in account and "sign in again" in account
    assert "Signed in until" in account
    card = account.split("function CloudSessionCard", 1)[1].split("function SettingsAccount", 1)[0]
    assert "ARCHHUB_CLOUD_SESSION" in card, "the panel must read the live session, not localStorage"
    assert "<CloudSignIn" in card.split("s.state === 'expired'", 1)[1], "expired shows the sign-in button"
    panel = account.split("function SettingsAccount", 1)[1]
    assert "<CloudSessionCard" in panel


# ---- (c) one cloud address ---------------------------------------------------------

_SCANNED = ("nodelang", "desktop", "tools", "legacy_engine", "packaging")
_SUFFIXES = {".py", ".js", ".jsx", ".html", ".json", ".ps1", ".toml", ".vbs", ".spec"}


def test_c_no_code_path_names_the_fly_host():
    hits = []
    files = [ROOT / "launch_archhub_test.py"]
    for folder in _SCANNED:
        files += [p for p in (ROOT / folder).rglob("*") if p.suffix in _SUFFIXES]
    for path in files:
        if not path.is_file() or "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # The DNS record's CNAME target is the one place the Fly name belongs.
        # ...and a host pin (PINNED_BASES, FOUNDER_CHECK_BASES), which only
        # ever narrows where a bearer may go.
        text = text.replace('("https://api.archhub.io", "https://%s")' % FLY_HOST, "")
        text = text.replace('"api_target": "%s"' % FLY_HOST, "").replace(
            '{"k":"api_target","v":"%s"}' % FLY_HOST, "")
        if FLY_HOST in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], hits


def test_c_the_default_cloud_is_the_one_address():
    assert cloud_relay.DEFAULT_BASE == "https://api.archhub.io"
    assert re.search(r"base_url or DEFAULT_BASE", inspect.getsource(cloud_signin.SignIn.__init__))


# ---- (d) one pinned-host source: the bearer never leaves the pinned hosts ----------

class _Answer:
    status = 200

    def __init__(self, body: bytes):
        self._body = body

    def read(self, *_limit):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_d_a_forged_cloud_json_sends_nothing_off_the_pinned_hosts(tmp_path, monkeypatch):
    """Verifier D3 (2026-09-24): cloud.json pointed at evil.example drew the bearer
    to https://evil.example/v1/models. Every cloud reader now takes its host from
    cloud_relay.pinned_cloud_base, the one pin."""
    import urllib.request
    from nodelang import cloud_publish_consent, model_catalogue, model_router

    appdata = tmp_path
    evil_bearer = "ah_" + "e" * 40
    path = _record(appdata, token=evil_bearer, expires_at=4_000_000_000,
                   cloud_base_url="https://evil.example")
    monkeypatch.setenv("APPDATA", str(appdata))
    sent: list = []

    def urlopen(request, timeout=None, **_kw):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        sent.append((url, request.get_header("Authorization") if hasattr(request, "get_header") else None))
        if url.endswith("/founder/api/browser-code"):
            return _Answer(b'{"claim_url": "https://api.archhub.io/founder/claim?code=z"}')
        if url.endswith("/v1/me"):
            return _Answer(b'{"email": "founder@example.com", "founder": true}')
        if url.endswith("/v1/models"):
            return _Answer(b'{"data": [{"id": "anthropic/claude-sonnet-5"}]}')
        if url.endswith("/v1/chat/completions"):
            return _Answer(b'{"choices": [{"message": {"content": "ok"}}]}')
        return _Answer(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    # model catalogue, as the models route reads it
    session = cloud_relay.load_cloud_session(appdata)
    assert session["base_url"] == "https://api.archhub.io"
    model_catalogue.cloud_models(session, opener=urlopen, timeout=1.0)
    # chat, discovering the session itself
    try:
        model_router.route_chat("cloud/gpt-4o", [{"role": "user", "content": "hi"}],
                                environ={}, secrets_loader=lambda _name: "", timeout=1.0)
    except Exception:
        pass
    assert model_router.resolve_model_route(
        "cloud/gpt-4o", cloud_base_url="https://evil.example").url.startswith("https://api.archhub.io/")
    # relay poll, started exactly as the app starts it
    monkeypatch.setattr(cloud_publish_consent, "cloud_publish_allowed", lambda _state: True)
    monkeypatch.setattr(cloud_relay.CloudRelay, "start", lambda self: self)
    relay = cloud_relay.start_cloud_relay(appdata=appdata, state_dir=tmp_path,
                                          respond=lambda text: {}, execute=lambda text: {})
    assert relay is not None
    try:
        relay.poll_once()
    except Exception:
        pass
    # /v1/me, cockpit link, sign-in and sign-out
    cloud_signin.session_summary(path)
    cloud_signin.cockpit_link(path)
    assert cloud_signin.SignIn("magic", base_url="https://evil.example", path=path).base_url == "https://api.archhub.io"
    cloud_signin.sign_out(path, wait=True)

    reached = {url.split("/", 3)[2] for url, _auth in sent}
    carried = [url for url, auth in sent if auth == "Bearer " + evil_bearer]
    assert sent, "the probe must have exercised the readers"
    assert reached <= {"api.archhub.io"}, sent
    assert {"/v1/models", "/v1/chat/completions", "/v1/me", "/founder/api/browser-code",
            "/v1/auth/logout"} <= {"/" + url.split("/", 3)[3] for url in carried}, carried
    assert any("/founder/api/agent-tasks/claim" in url for url, _a in sent), sent


def test_d_the_pin_is_written_once():
    """One source: cloud_signin and every reader import cloud_relay's pin."""
    sources = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "nodelang").glob("*.py")}
    pin = '("https://api.archhub.io", "https://archhub-cloud.fly.dev")'
    owners = sorted(name for name, text in sources.items() if pin in text)
    assert owners == ["cloud_relay.py"], owners
    for name in ("cloud_signin.py", "model_router.py", "model_catalogue.py"):
        assert "pinned_cloud_base" in sources[name], name
