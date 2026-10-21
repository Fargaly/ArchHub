"""Court (fix 3): AutoCAD is recognised by its broker's own identity and never counted as Revit.

Founder report 2026-09-23: AutoCAD open with its broker read "absent" and was counted as a
Revit session. The broker answers /ping with service "acad-mcp" and /info with document_name
and acad_version (bridges/sources/acad_mcp/AcadMCPApp.cs); discovery kept only a title string,
so every caller that looked for document["acad_version"] found nothing. Only the two broker
HTTP answers are fixtures; no host is reached.
"""
import json

from nodelang import clean_revit_adapter as adapter
from nodelang import pipeline_engines

_discover = adapter.live_sessions   # conftest replaces it per test; keep the implementation

REVIT = 48884
ACAD = 48885


def _fake_brokers(monkeypatch, exec_calls):
    class Socket:
        def settimeout(self, timeout): pass
        def connect_ex(self, address): return 0 if address[1] in (REVIT, ACAD) else 1
        def close(self): pass

    def call(port, route, body=None, **kwargs):
        if route == "/ping":
            if port == REVIT:
                return {"status": "ok", "pid": 101, "revit_version": "2026", "version": "1.0"}
            return {"status": "ok", "service": "acad-mcp", "version": "0.3.0", "port": ACAD, "pid": 202}
        if route == "/info":
            if port == REVIT:
                return {"status": "ok", "document_title": "Tower model"}
            return {"status": "ok", "document_name": "Plan.dwg", "document_path": "C:/private/Plan.dwg",
                    "acad_version": "25.0.0.0"}
        if route == "/exec":
            exec_calls.append((port, body.get("transaction_name")))
            return {"status": "ok", "result": [{"x1": 0, "y1": 0, "x2": 1000, "y2": 0, "layer": "A-WALL"}]}
        raise AssertionError("unexpected broker route %r" % route)
    monkeypatch.setattr(adapter.socket, "socket", Socket)
    monkeypatch.setattr(adapter, "BROKER_PORTS", range(REVIT, ACAD + 1))
    monkeypatch.setattr(adapter, "_call", call)
    monkeypatch.setattr(adapter, "live_sessions", _discover)


def test_autocad_session_keeps_its_identity_and_version_without_private_fields(monkeypatch):
    _fake_brokers(monkeypatch, [])
    revit, acad = _discover()
    assert revit["revit_version"] == "2026" and revit["document"] == "Tower model"
    assert acad["service"] == "acad-mcp" and acad["acad_version"] == "25.0.0.0", acad
    assert acad["document"] == "Plan.dwg"
    assert "private" not in json.dumps([revit, acad])


def test_connectors_count_autocad_as_autocad_and_revit_as_revit(monkeypatch):
    _fake_brokers(monkeypatch, [])
    rows = {row["id"]: row for row in pipeline_engines.probe_connectors()}
    assert rows["autocad"]["state"] == "connected" and rows["autocad"]["detail"] == "1 session(s)", rows["autocad"]
    assert rows["revit"]["state"] == "connected" and rows["revit"]["detail"] == "1 session(s)", rows["revit"]
    out, said = pipeline_engines.revit_sessions({}, {})
    assert [session["port"] for session in out["out"]] == [REVIT], said


def test_live_autocad_lines_are_read_from_the_autocad_broker(monkeypatch):
    calls = []
    _fake_brokers(monkeypatch, calls)
    out, said = pipeline_engines.cad_lines_from_host({"layer": "A-WALL"}, {})
    assert out["out"] == [[0.0, 0.0, 1000.0, 0.0]] and calls == [(ACAD, "ArchHub read lines")], (said, calls)
