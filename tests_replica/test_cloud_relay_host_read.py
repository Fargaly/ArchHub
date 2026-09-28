"""A remote host read is answered on the founder's desktop by its own read function.

The cloud's /mcp queues {tool, args} as a host-read task; this relay claims it and
runs the SAME local read function the host tools use -- from an allowlist, never
BABOOM, never an effect -- and posts JSON that fits one task row.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nodelang import host_brokers
from nodelang.cloud_relay import CloudRelay
from nodelang.universal_pipeline import wire_parameter_specs

MAP_SCRIPT = 'window.ATLAS_MAP = {"domains":[],"nodes":[],"wires":[]}; window.ATLAS_LIVE = true;'


class _Cloud(BaseHTTPRequestHandler):
    tasks, claims, results, maps = [], [], [], []

    def log_message(self, *_a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/agent-tasks/claim"):
            _Cloud.claims.append(json.loads(raw))
            return self._json({"ok": True, "task": _Cloud.tasks.pop(0) if _Cloud.tasks else None})
        if self.path.endswith("/result"):
            _Cloud.results.append(json.loads(raw))
            return self._json({"ok": True})
        if self.path == "/founder/map-state":
            _Cloud.maps.append(json.loads(raw))
            return self._json({"ok": True})
        return self._json({"ok": False})


@pytest.fixture
def cloud():
    for held in (_Cloud.tasks, _Cloud.claims, _Cloud.results, _Cloud.maps):
        held[:] = []
    server = HTTPServer(("127.0.0.1", 0), _Cloud)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_port
    server.shutdown()
    server.server_close()


def _relay(base, baboom):
    return CloudRelay(
        base_url=base, token="t",
        respond=lambda utterance: baboom.append(("ask", utterance)) or {},
        execute=lambda utterance: baboom.append(("act", utterance)) or {},
        map_script=lambda: MAP_SCRIPT, hosts=lambda: [],
    )


def _read(base, directive, baboom):
    text = directive if isinstance(directive, str) else json.dumps(directive)
    _Cloud.tasks[:] = [{"id": "t1", "kind": "host-read", "directive": text}]
    return _relay(base, baboom).poll_once()


def test_the_relay_asks_the_cloud_for_host_reads(cloud):
    _relay(cloud, []).poll_once()
    assert "host-read" in _Cloud.claims[-1]["kinds"]


def test_a_host_read_runs_the_local_read_function_and_never_baboom(cloud, monkeypatch):
    seen, baboom = [], []

    def dropbox(params, feeds):
        seen.append(dict(params))
        return {"out": [{"name": "A-101.pdf", "dir": False, "bytes": 10}]}, "1 entr(ies)"
    monkeypatch.setitem(host_brokers.ENGINES, "dropbox.list", dropbox)
    out = _read(cloud, {"tool": "dropbox.list", "args": {"path": "P-603", "code": "rm -rf"}}, baboom)
    assert out["ok"] is True and baboom == []
    assert seen == [{"path": "P-603"}], "only the argument the tool reads travels"
    posted = _Cloud.results[-1]
    assert posted["ok"] is True
    assert json.loads(posted["result"])["out"] == [{"name": "A-101.pdf", "dir": False, "bytes": 10}]


def test_anything_off_the_allowlist_is_refused_before_a_host_is_touched(cloud, monkeypatch):
    touched, baboom = [], []
    for name in ("max.exec", "office.read", "outlook.graph.categorize"):
        monkeypatch.setitem(host_brokers.ENGINES, name,
                            lambda params, feeds, name=name: touched.append(name) or ({"out": []}, ""))
    for directive in ({"tool": "max.exec", "args": {"code": "resetMaxFile #noPrompt"}},
                      {"tool": "outlook.graph.categorize", "args": {}},
                      {"tool": "office.read", "args": {"operation": "excel.save_workbook"}},
                      "not json"):
        out = _read(cloud, directive, baboom)
        assert out["ok"] is False
        assert _Cloud.results[-1]["ok"] is False
    assert touched == [] and baboom == []


def test_a_long_answer_still_fits_one_task_row(cloud, monkeypatch):
    rows = [{"id": "row-%04d" % index, "state": "idle", "detail": "x" * 40} for index in range(600)]
    monkeypatch.setitem(host_brokers.ENGINES, "connector.rows",
                        lambda params, feeds: ({"out": rows}, "600 host(s)"))
    _read(cloud, {"tool": "connector.rows", "args": {}}, [])
    posted = _Cloud.results[-1]
    assert posted["ok"] is True and len(posted["result"]) <= 8000
    assert json.loads(posted["result"])["truncated"] is True


def test_the_map_push_carries_the_one_wire_parameter_list(cloud):
    _relay(cloud, []).push_map(force=True)
    assert _Cloud.maps[-1]["wire_params"] == wire_parameter_specs()
