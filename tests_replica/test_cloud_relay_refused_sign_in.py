"""A refused cloud sign-in is named, slows the relay, and a new sign-in is picked up without a restart.

The founder's recorded token was issued 2026-06-15 and the cloud's 90-day lifetime ended it on
2026-09-13. From then the relay asked /founder/api/agent-tasks/claim every ~5 s, each answered 403,
while the desktop printed only "cloud map: not published (HTTP 403)".
"""
import io
import urllib.error
from pathlib import Path

from nodelang.cloud_relay import REFUSED_BACKOFF, CloudRelay

ROOT = Path(__file__).resolve().parents[1]


def _relay(loader, code=403):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "Forbidden", {}, io.BytesIO(b'{"detail":"founder_only"}'))
    return CloudRelay(base_url="https://cloud.example", token="old-token-value",
                      respond=lambda utterance: {}, execute=lambda utterance: {},
                      opener=opener, session_loader=loader)


class _OneTurn:
    """A stop event that ends the loop after its first wait and records how long it was asked to wait."""

    def __init__(self):
        self.waits = []

    def is_set(self):
        return bool(self.waits)

    def wait(self, seconds):
        self.waits.append(seconds)


def test_a_refused_sign_in_waits_the_backoff_and_says_to_sign_in_again():
    for code in (401, 403):
        relay = _relay(lambda: {"token": "old-token-value", "base_url": "https://cloud.example"}, code)
        stop = _OneTurn()
        relay.run_forever(interval=4.0, stop=stop)
        assert stop.waits == [REFUSED_BACKOFF] and REFUSED_BACKOFF >= 60
        assert "HTTP %d" % code in relay.last_error and "Sign in again" in relay.last_error
        assert "old-token-value" not in relay.last_error


def test_a_new_sign_in_on_this_machine_is_taken_without_a_restart():
    relay = _relay(lambda: {"token": "new-token-value", "base_url": "https://cloud.example/"})
    stop = _OneTurn()
    relay.run_forever(interval=4.0, stop=stop)
    assert stop.waits == [0.0]
    assert relay.token == "new-token-value" and relay.base_url == "https://cloud.example"
    assert "new-token-value" not in relay.last_error


def test_no_session_on_disk_still_backs_off():
    relay = _relay(lambda: None)
    stop = _OneTurn()
    relay.run_forever(interval=4.0, stop=stop)
    assert stop.waits == [REFUSED_BACKOFF]


def test_the_relay_is_started_with_the_machine_session_loader_and_the_boot_line_names_the_cause():
    relay_source = (ROOT / "nodelang" / "cloud_relay.py").read_text(encoding="utf-8")
    assert "session_loader=lambda: load_cloud_session(appdata)" in relay_source
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "Sign in again under Settings, Account." in launcher