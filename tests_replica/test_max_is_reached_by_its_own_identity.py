"""Court (fix 4): 3ds Max is reached only through a listener that answers as MaxMCP.

Founder report 2026-09-23: 3ds Max was hard-coded to 127.0.0.1:48886, the port AutoCAD's
broker listens on, so MAXScript went to AutoCAD. MaxMCP binds the first free port from
48886 to 48899 and answers /max-mcp/ping with service "max-mcp"
(bridges/sources/max_mcp/max_mcp_startup.py). Sockets and HTTP answers are fixtures.
"""
from nodelang import host_brokers as hosts

ACAD, MAX = 48886, 48887


def _fake(monkeypatch, listening):
    sent = []

    def port_open(port, timeout=0.15):
        return port in listening

    def http(url, body=None, headers=None, timeout=20.0):
        sent.append((url, body))
        if ":%d/" % ACAD in url:
            return {"status": "error", "error": "Unknown route: /max-mcp/ping"}
        if url.endswith("/max-mcp/ping"):
            return {"status": "ok", "service": "max-mcp", "version": "0.2.0"}
        return {"status": "ok", "result": "ran"}
    monkeypatch.setattr(hosts, "_port_open", port_open)
    monkeypatch.setattr(hosts, "_http", http)
    monkeypatch.setattr(hosts, "_running", lambda names: False, raising=False)
    monkeypatch.setattr(hosts, "_installed", lambda paths: False, raising=False)
    return sent


def test_maxscript_goes_to_the_listener_that_answers_as_maxmcp_never_to_autocad(monkeypatch):
    sent = _fake(monkeypatch, {ACAD, MAX})
    out, said = hosts.max_exec({"code": "box()"}, {})
    assert said == "ran in 3ds Max", (said, sent)
    executed = [(url, body) for url, body in sent if body is not None]
    assert executed == [("http://127.0.0.1:%d/max-mcp/exec_maxscript" % MAX, {"script": "box()"})], sent
    assert not any(":%d/" % ACAD in url and body is not None for url, body in sent), "nothing is sent to AutoCAD"


def test_autocad_alone_is_not_3ds_max(monkeypatch):
    sent = _fake(monkeypatch, {ACAD})
    out, said = hosts.max_exec({"code": "box()"}, {})
    assert out["ok"] is False and "max-mcp" in said, said
    assert all(body is None for _url, body in sent), "no MAXScript was sent anywhere: %r" % sent
    row = next(row for row in hosts.probe_host_rows() if row["id"] == "max")
    assert row["state"] != "connected", row


def test_the_max_row_names_the_port_maxmcp_answers_on(monkeypatch):
    _fake(monkeypatch, {ACAD, MAX})
    row = next(row for row in hosts.probe_host_rows() if row["id"] == "max")
    assert row["state"] == "connected" and ":%d" % MAX in row["detail"], row
