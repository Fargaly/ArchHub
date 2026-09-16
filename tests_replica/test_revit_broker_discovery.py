"""Published broker response compatibility without opening or probing Revit."""
import json

import pytest
from nodelang import clean_revit_adapter as adapter

# Suite-wide host isolation replaces live_sessions; retain the implementation
# at collection while still replacing every socket and HTTP call below.
_discover = adapter.live_sessions


@pytest.mark.parametrize("field", ["document_title", "document", "title", "doc"])
def test_broker_title_identifies_open_document_without_exposing_private_fields(monkeypatch, field):
    class Socket:
        def settimeout(self, timeout): pass
        def connect_ex(self, address): return 0
        def close(self): pass
    monkeypatch.setattr(adapter.socket, "socket", Socket)
    monkeypatch.setattr(adapter, "BROKER_PORTS", range(48884, 48885))
    calls = []
    def call(port, route, **kwargs):
        calls.append(route)
        if route == "/ping":
            return {"status":"ok", "pid":123, "revit_version":"2026"}
        return {"status":"ok", field:"Fixture building", "document_path":"private file",
                "username":"private user"}
    monkeypatch.setattr(adapter, "_call", call)
    sessions = _discover()
    assert sessions[0]["document"] == "Fixture building"
    assert adapter._session_for(None, sessions) == sessions[0]
    assert "private" not in json.dumps(sessions)
    assert calls == ["/ping", "/info"]
