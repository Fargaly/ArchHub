"""revit_ping names each open document; a busy Revit is "busy" with its last known document.

Fake bridge only: session files in the isolated state folder and a fake signed
broker answering /ping on its listener thread and /info on the (maybe busy) UI thread.
"""
from __future__ import annotations

import json

import pytest

from nodelang import clean_revit_adapter, host_brokers, native_host_tools
from nodelang.user_paths import state_directory


@pytest.fixture
def bridge(monkeypatch):
    """port -> {"pid", "title", "busy"}; ping always answers, /info only when not busy."""
    hosts, calls = {}, []
    monkeypatch.setattr(host_brokers, "_LAST_DOCUMENT", {})
    monkeypatch.setattr(host_brokers, "_port_open", lambda port, **_k: port in hosts)
    monkeypatch.setattr(host_brokers, "_windows_process_table",
                        lambda: {h["pid"]: {"name": "revit.exe"} for h in hosts.values()})

    def call(port, route, body=None, timeout=30):
        calls.append((port, route))
        host = hosts[port]
        if route == "/ping":
            return {"status": "ok", "pid": host["pid"], "revit_version": "2027", "service": "revit-mcp"}
        if host["busy"]:
            raise TimeoutError("isolated busy host")
        return {"status": "ok", "document_title": host["title"], "document_path": "private path"}
    monkeypatch.setattr(clean_revit_adapter, "_call", call)

    def add(port, pid, title, busy=False):
        hosts[port] = {"pid": pid, "title": title, "busy": busy}
        folder = state_directory() / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        # What the add-in writes: no document field.
        (folder / ("revit-%d.json" % pid)).write_text(json.dumps(
            {"family": "revit", "port": port, "pid": pid, "version": "2027"}), encoding="utf-8")
    return hosts, add, calls


def test_ping_names_both_open_documents(bridge):
    _, add, _ = bridge
    add(48884, 101, "S3")
    add(48885, 102, "OPT 03")
    reply = native_host_tools._sessions("revit")
    assert reply["ok"] is True
    assert [(s["port"], s["document"]) for s in reply["sessions"]] == [(48884, "S3"), (48885, "OPT 03")]
    assert all("state" not in s for s in reply["sessions"])
    assert "private" not in json.dumps(reply)


def test_ping_names_the_one_open_document(bridge):
    _, add, calls = bridge
    add(48884, 101, "S3")
    [session] = native_host_tools._sessions("revit")["sessions"]
    assert session["document"] == "S3" and session["revit_version"] == "2027"
    assert calls == [(48884, "/ping"), (48884, "/info")]


def test_busy_host_is_busy_with_last_known_document(bridge):
    hosts, add, _ = bridge
    add(48884, 101, "S3")
    add(48885, 102, "OPT 03")
    native_host_tools._sessions("revit")
    hosts[48885]["busy"] = True
    sessions = native_host_tools._sessions("revit")["sessions"]
    assert sessions[0]["document"] == "S3" and "state" not in sessions[0]
    assert sessions[1]["document"] == "OPT 03" and sessions[1]["state"] == "busy"
    info = host_brokers.broker_call("revit", "/info", port=48885, timeout=1.5)
    assert info["status"] == "busy" and info["ok"] is False
    assert info["document"] == "OPT 03" and info["port"] == 48885


def test_busy_host_never_seen_is_busy_not_missing(bridge):
    _, add, _ = bridge
    add(48885, 102, "OPT 03", busy=True)
    [session] = native_host_tools._sessions("revit")["sessions"]
    assert session["port"] == 48885 and session["state"] == "busy" and session["document"] == ""
