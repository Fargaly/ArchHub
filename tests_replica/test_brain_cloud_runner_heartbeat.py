"""Court: the desktop tells the cloud it is alive while signed in, and only then.

POST /v1/devices/heartbeat {device_id, name} is the founder Cockpit's device
list. brain_cloud_runner sends it about once a minute while an account is
signed in on this machine, with a stable per-install id kept beside the cloud
session, and backs off after failures. Signed out, nothing is sent.
"""
from __future__ import annotations

import json
import re
import threading
import time

import pytest

from nodelang import brain_cloud_runner as runner


def _sign_in(appdata, email="member@studio.test"):
    (appdata / "ArchHub" / "brain").mkdir(parents=True, exist_ok=True)
    (appdata / "ArchHub" / "brain" / "cloud.json").write_text(
        json.dumps({"email": email, "token": "court"}), encoding="utf-8")


def test_signed_out_nothing_is_sent(tmp_path):
    sent = []
    assert runner.heartbeat_now(appdata=tmp_path, post=sent.append) == {"ok": False, "reason": "signed out"}
    assert sent == []
    assert not runner.device_path(tmp_path).exists(), "no id is made for nobody"


def test_signed_in_the_device_says_who_it_is_but_never_its_hostname(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "ACME-LT-1234")
    monkeypatch.setattr(runner.platform, "node", lambda: "ACME-LT-1234")
    monkeypatch.setattr(runner.platform, "system", lambda: "Windows")
    _sign_in(tmp_path)
    sent = []

    def post(body):
        sent.append(body)
        return {"ok": True}
    assert runner.heartbeat_now(appdata=tmp_path, post=post) == {"ok": True}
    assert len(sent) == 1 and set(sent[0]) == {"device_id", "name"}
    assert re.match(r"^[A-Za-z0-9._:-]{1,128}$", sent[0]["device_id"])
    assert sent[0]["name"] == "Windows desktop"
    assert "acme" not in json.dumps(sent).lower(), "the hostname reached the cloud"


def test_a_name_the_person_gave_is_sent_and_the_id_is_kept(tmp_path):
    first = runner.device_id(tmp_path)
    held = json.loads(runner.device_path(tmp_path).read_text(encoding="utf-8"))
    runner.device_path(tmp_path).write_text(json.dumps(dict(held, name="Studio laptop")), encoding="utf-8")
    assert runner.device_name(tmp_path) == "Studio laptop"
    assert runner.device_id(tmp_path) == first


def test_the_device_id_survives_a_restart(tmp_path):
    first = runner.device_id(tmp_path)
    # A restart: nothing in memory, only what the install keeps on disk.
    assert runner.device_id(tmp_path) == first
    assert json.loads(runner.device_path(tmp_path).read_text(encoding="utf-8")) == {"device_id": first}
    assert runner.device_id(tmp_path / "another-install") != first


def test_a_damaged_id_file_is_replaced_by_a_valid_one(tmp_path):
    runner.device_path(tmp_path).parent.mkdir(parents=True)
    runner.device_path(tmp_path).write_text('{"device_id": "bad id with spaces"}', encoding="utf-8")
    assert re.match(r"^[A-Za-z0-9._:-]{1,128}$", runner.device_id(tmp_path))


def test_failures_back_off_and_success_returns_to_a_minute():
    wait = runner.HEARTBEAT_SECONDS
    waits = []
    for _ in range(6):
        wait = runner.next_heartbeat_wait(wait, ok=False)
        waits.append(wait)
    assert waits == [120.0, 240.0, 480.0, 900.0, 900.0, 900.0]
    assert runner.next_heartbeat_wait(900.0, ok=True) == 60.0


def test_the_runner_beats_while_signed_in_and_stops(tmp_path, monkeypatch):
    beats = []
    monkeypatch.setattr(runner, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(runner, "FIRST_PASS_SECONDS", 60.0)  # no sync pass in this court
    monkeypatch.setattr(runner, "heartbeat_now", lambda appdata=None, post=None: beats.append(1) or {"ok": True})
    stop = threading.Event()
    thread = threading.Thread(target=runner._loop, args=(stop, tmp_path), daemon=True)
    thread.start()
    time.sleep(0.4)
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert 3 <= len(beats) <= 12, len(beats)
    assert runner.last_heartbeat()["ok"] is True