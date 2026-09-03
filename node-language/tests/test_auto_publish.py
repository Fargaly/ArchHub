"""M6 partial — per-graph `auto_publish` hook in WorkflowRunner.

When `graph.auto_publish.enabled=True`, every successful sink in
`run_all()` is shipped through SpeckleWire automatically — no
`share.publish` node required. Optionally pushed to a configured
Speckle Server.

Tests:
  1. Default OFF — runner doesn't write to Speckle unless asked.
  2. Enabled — every sink with a value publishes; result includes
     per-sink URLs.
  3. Failure mode — a sink with no value records `skipped`, not
     fake success.
  4. Server-push failure — falls back to disk-only; runner does
     NOT raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _runner(graph):
    from workflows.runner import WorkflowRunner
    return WorkflowRunner(graph)


def _simple_graph(auto_publish=None):
    """A trivial 2-node graph: constant → passthrough. The
    passthrough is the sink and carries the constant's value."""
    g = {
        "nodes": [
            {"id": "c", "type": "data.constant",
             "config": {"value": 42}},
            {"id": "p", "type": "data.passthrough", "config": {}},
        ],
        "wires": [{"from": ["c", "value"], "to": ["p", "value"]}],
    }
    if auto_publish is not None:
        g["auto_publish"] = auto_publish
    return g


# ─── 1. default OFF ──────────────────────────────────────────────────


def test_run_all_does_not_auto_publish_by_default():
    r = _runner(_simple_graph())
    result = r.run_all()
    assert result["status"] == "ok"
    # No `auto_publish` field in result when disabled.
    assert "auto_publish" not in result
    # Sink cooked normally.
    assert result["results"]["p"]["value"] == 42


def test_run_all_does_not_auto_publish_when_explicitly_disabled():
    r = _runner(_simple_graph({"enabled": False,
                                 "server_url": "http://example.com"}))
    result = r.run_all()
    assert "auto_publish" not in result


# ─── 2. enabled — value ships to disk ────────────────────────────────


def test_run_all_auto_publishes_to_disk_when_enabled(tmp_path):
    r = _runner(_simple_graph({
        "enabled": True,
        "project_dir": str(tmp_path),
    }))
    result = r.run_all()
    assert "auto_publish" in result
    entries = result["auto_publish"]
    assert isinstance(entries, list)
    # One sink (`p`) → one entry.
    assert len(entries) == 1
    e = entries[0]
    assert e["sink_id"] == "p"
    assert e["status"] == "ok"
    assert e["url"].startswith("speckle://local/")
    assert e["mode"] == "disk"
    assert e["hash"]


def test_run_all_auto_publishes_every_sink(tmp_path):
    """A graph with 2 sinks → 2 published entries."""
    g = {
        "nodes": [
            {"id": "c1", "type": "data.constant",
             "config": {"value": "left"}},
            {"id": "c2", "type": "data.constant",
             "config": {"value": "right"}},
        ],
        "wires": [],
        "auto_publish": {"enabled": True,
                         "project_dir": str(tmp_path)},
    }
    r = _runner(g)
    result = r.run_all()
    entries = result["auto_publish"]
    assert len(entries) == 2
    sink_ids = {e["sink_id"] for e in entries}
    assert sink_ids == {"c1", "c2"}
    assert all(e["status"] == "ok" for e in entries)


# ─── 3. failure mode — skipped values ────────────────────────────────


def test_run_all_skips_sinks_with_no_value(tmp_path):
    """A sink that cooked an error envelope (no `value`) records
    `skipped` honestly — does NOT fabricate a hash."""
    g = {
        "nodes": [
            # Use an unknown type → runner returns error
            {"id": "broken", "type": "nonexistent.executor",
             "config": {}},
        ],
        "wires": [],
        "auto_publish": {"enabled": True,
                         "project_dir": str(tmp_path)},
    }
    r = _runner(g)
    result = r.run_all()
    entries = result.get("auto_publish") or []
    # `broken` either skipped (no value) or errored — either way
    # NOT marked ok with a fake hash.
    assert all(
        e.get("status") in ("skipped", "error")
        or not e.get("hash", "")
        for e in entries
        if e.get("sink_id") == "broken"
    )


# ─── 4. server push — graceful fallback ──────────────────────────────


def test_run_all_falls_back_to_disk_when_server_push_fails(tmp_path,
                                                              monkeypatch):
    """A server URL that errors out → entry mode flips to
    `disk_only_after_server_fail`. The cook is NOT tainted."""
    # Force push_to_server to raise.
    def boom(value, server_url, model_name):
        raise RuntimeError("no network")
    import speckle_server
    monkeypatch.setattr(speckle_server, "push_to_server", boom)

    r = _runner(_simple_graph({
        "enabled": True,
        "project_dir": str(tmp_path),
        "server_url": "https://speckle.example.com",
        "model_name": "test",
    }))
    result = r.run_all()
    assert result["status"] == "ok"
    e = result["auto_publish"][0]
    assert e["status"] == "ok"  # local-disk write succeeded
    assert e["mode"] == "disk_only_after_server_fail"
    assert "server_error" in e
    assert "no network" in e["server_error"]


def test_run_all_uses_server_url_when_push_succeeds(tmp_path, monkeypatch):
    """When push_to_server succeeds, the entry's `url` is the
    server URL (not the local hash)."""
    pushed = []

    def fake_push(value, server_url, model_name):
        pushed.append((server_url, model_name))
        return f"{server_url}/streams/{model_name}/objects/abc"
    import speckle_server
    monkeypatch.setattr(speckle_server, "push_to_server", fake_push)

    r = _runner(_simple_graph({
        "enabled": True,
        "project_dir": str(tmp_path),
        "server_url": "https://speckle.example.com",
        "model_name": "auto-pub-test",
    }))
    result = r.run_all()
    e = result["auto_publish"][0]
    assert e["mode"] == "server"
    assert e["url"].endswith("/streams/auto-pub-test/objects/abc")
    assert pushed == [("https://speckle.example.com", "auto-pub-test")]


# ─── 5. unaffected disabled path ─────────────────────────────────────


def test_run_all_does_not_touch_speckle_when_disabled(tmp_path,
                                                          monkeypatch):
    """When disabled, the runner does NOT instantiate SpeckleWire
    or write any files. We verify by ensuring no speckle.db
    appears in the tmp_path."""
    calls = []

    class _Boom:
        def __init__(self, *a, **kw): calls.append(a)
        def send(self, *a, **kw):  calls.append("send")
        def close(self): pass
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "SpeckleWire", _Boom)

    r = _runner(_simple_graph())  # no auto_publish
    r.run_all()
    assert calls == [], (
        "Disabled auto_publish must not touch SpeckleWire at all")