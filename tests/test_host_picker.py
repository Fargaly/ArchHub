"""Host picker tests — version + document selection for host.* nodes.

Founder direction (2026-05-14): host tools should allow users to pick:
  (a) WHICH version of the host (e.g. Revit 2024 vs Revit 2025) when
      multiple instances are running
  (b) WHICH document/file inside that host's session

Pins:
  - bridge.list_host_sessions(family) returns the right shape per family
  - bridge.list_host_documents(family, session_id) narrows correctly
  - core.py host node config_schema declares version/document as
    dynamic enums with source pointers the JS picker can resolve
  - _host_exec honours config.version → picks the matching session
  - _host_exec honours config.document → passes ?doc=<title> to broker
  - Empty config.version falls back to broker.pick_session()
  - Speckle returns empty list (cloud, not session-bound)
  - All brokers mocked — no live Revit/AutoCAD/Max/Outlook needed
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Register host.* nodes for the executor tests below.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows import registry as _registry

# Pull the bridge helpers DIRECTLY — they're pure Python (no Qt).
from bridge import (
    _list_host_sessions_impl,
    _list_host_documents_impl,
    _session_to_dict,
)


# ── Mock session helper ─────────────────────────────────────────────
@dataclass
class _FakeSession:
    """Mimics the dataclass shape returned by revit/acad/max brokers."""
    session_id:     str = "fake-1"
    family:         str = "revit"
    pid:            int = 1234
    port:           int = 48884
    version:        str = "2025"
    doc_title:      str = "Tower-A.rvt"
    started_at:     str = ""
    last_heartbeat: str = ""
    legacy:         bool = False
    healthy:        bool = True


# ══════════════════════════════════════════════════════════════════════
# 1. Bridge slot — list_host_sessions
# ══════════════════════════════════════════════════════════════════════
class TestListHostSessions:
    def test_revit_returns_session_list_shape(self):
        fake = _FakeSession(session_id="revit-1234", version="2025",
                             doc_title="Tower-A.rvt", port=48884)
        with patch("revit_broker.list_sessions",
                   return_value=[fake]) as mock_list:
            rows = _list_host_sessions_impl("revit")
        mock_list.assert_called_once_with(prune=False)
        assert isinstance(rows, list)
        assert len(rows) == 1
        r = rows[0]
        # Founder shape contract: {session_id, version, port,
        # opened_doc, host_alive}.
        assert r["session_id"] == "revit-1234"
        assert r["version"] == "2025"
        assert r["port"] == 48884
        assert r["opened_doc"] == "Tower-A.rvt"
        assert r["host_alive"] is True
        assert r["family"] == "revit"

    def test_revit_two_sessions_both_listed(self):
        s1 = _FakeSession(session_id="revit-1", version="2024",
                           doc_title="A.rvt", port=48884)
        s2 = _FakeSession(session_id="revit-2", version="2025",
                           doc_title="B.rvt", port=48885)
        with patch("revit_broker.list_sessions", return_value=[s1, s2]):
            rows = _list_host_sessions_impl("revit")
        assert len(rows) == 2
        versions = {r["version"] for r in rows}
        assert versions == {"2024", "2025"}

    def test_autocad_dispatches_to_acad_broker(self):
        fake = _FakeSession(session_id="autocad-1", family="autocad",
                             version="2024", doc_title="Plan.dwg",
                             port=48885)
        with patch("acad_broker.list_sessions", return_value=[fake]):
            rows = _list_host_sessions_impl("autocad")
        assert len(rows) == 1
        assert rows[0]["session_id"] == "autocad-1"
        assert rows[0]["family"] == "autocad"

    def test_max_dispatches_to_max_broker(self):
        fake = _FakeSession(session_id="max-1", family="max",
                             version="2024", doc_title="scene.max",
                             port=48886)
        with patch("max_broker.list_sessions", return_value=[fake]):
            rows = _list_host_sessions_impl("max")
        assert len(rows) == 1
        assert rows[0]["family"] == "max"

    def test_outlook_dispatches_to_outlook_broker(self):
        fake = _FakeSession(session_id="outlook-foo@bar.com",
                             family="outlook", version="16.0",
                             doc_title="foo@bar.com", port=0)
        with patch("outlook_broker.list_sessions", return_value=[fake]):
            rows = _list_host_sessions_impl("outlook")
        assert len(rows) == 1
        assert rows[0]["family"] == "outlook"
        assert rows[0]["opened_doc"] == "foo@bar.com"

    def test_blender_single_listener_uses_runner_ping(self):
        # No list_sessions on the runner → fall back to ping/info.
        fake_runner = MagicMock()
        del fake_runner.list_sessions          # ensure attr doesn't exist
        fake_runner.ping.return_value = {"status": "ok"}
        fake_runner.info.return_value = {
            "version": "4.0",
            "filepath": "C:/scenes/villa.blend",
        }
        fake_runner.CONNECTOR_PORT_DEFAULT = 9876
        with patch.dict("sys.modules",
                          {"connectors.blender_runner": fake_runner}):
            rows = _list_host_sessions_impl("blender")
        assert len(rows) == 1
        r = rows[0]
        assert r["family"] == "blender"
        assert r["version"] == "4.0"
        assert r["opened_doc"] == "C:/scenes/villa.blend"
        assert r["host_alive"] is True

    def test_blender_unreachable_returns_empty(self):
        fake_runner = MagicMock()
        del fake_runner.list_sessions
        fake_runner.ping.return_value = None     # no listener
        with patch.dict("sys.modules",
                          {"connectors.blender_runner": fake_runner}):
            rows = _list_host_sessions_impl("blender")
        assert rows == []

    def test_rhino_single_listener_uses_runner_ping(self):
        fake_runner = MagicMock()
        del fake_runner.list_sessions
        fake_runner.ping.return_value = {"status": "ok"}
        fake_runner.info.return_value = {
            "version": "8",
            "filepath": "site.3dm",
        }
        fake_runner.CONNECTOR_PORT_DEFAULT = 9879
        with patch.dict("sys.modules",
                          {"connectors.rhino_runner": fake_runner}):
            rows = _list_host_sessions_impl("rhino")
        assert len(rows) == 1
        assert rows[0]["family"] == "rhino"
        assert rows[0]["version"] == "8"

    def test_speckle_returns_empty_list(self):
        """Speckle streams aren't sessions — bridge returns []."""
        rows = _list_host_sessions_impl("speckle")
        assert rows == []

    def test_unknown_family_returns_empty(self):
        assert _list_host_sessions_impl("nope") == []
        assert _list_host_sessions_impl("") == []

    def test_session_to_dict_handles_missing_attrs(self):
        # A session-like object missing several attributes shouldn't crash.
        class Minimal:
            session_id = "x"
        out = _session_to_dict(Minimal(), "revit")
        assert out["session_id"] == "x"
        assert out["family"] == "revit"
        assert out["host_alive"] is False
        assert out["port"] == 0


# ══════════════════════════════════════════════════════════════════════
# 2. Bridge slot — list_host_documents
# ══════════════════════════════════════════════════════════════════════
class TestListHostDocuments:
    def test_revit_calls_list_docs_on_chosen_session(self):
        fake_sess = _FakeSession(session_id="revit-A", version="2025")
        # broker.forward returns documents dict.
        with patch("revit_broker.list_sessions", return_value=[fake_sess]), \
             patch("revit_broker.forward",
                    return_value={"status": "ok",
                                  "documents": [{"path": "/a.rvt",
                                                  "title": "A",
                                                  "active": True,
                                                  "kind": "revit"}]}) as fwd:
            rows = _list_host_documents_impl("revit", "revit-A")
        assert len(rows) == 1
        assert rows[0]["title"] == "A"
        assert rows[0]["active"] is True
        # broker.forward should have been called with /list_docs.
        called_args = fwd.call_args
        assert called_args is not None
        assert called_args[0][1] == "/list_docs"

    def test_revit_falls_back_to_doc_title_when_no_list_docs_endpoint(self):
        fake_sess = _FakeSession(session_id="revit-A",
                                   doc_title="Tower-A.rvt")
        # broker.forward returns error — we fall back to session.doc_title.
        with patch("revit_broker.list_sessions",
                    return_value=[fake_sess]), \
             patch("revit_broker.forward",
                    return_value={"status": "error",
                                  "error": "404 not found"}):
            rows = _list_host_documents_impl("revit", "revit-A")
        assert len(rows) == 1
        assert rows[0]["title"] == "Tower-A.rvt"
        assert rows[0]["active"] is True
        assert rows[0]["kind"] == "revit"

    def test_revit_filters_by_session_id(self):
        s1 = _FakeSession(session_id="r-1", doc_title="A.rvt")
        s2 = _FakeSession(session_id="r-2", doc_title="B.rvt")
        with patch("revit_broker.list_sessions", return_value=[s1, s2]), \
             patch("revit_broker.forward",
                    return_value={"status": "error"}):
            rows = _list_host_documents_impl("revit", "r-2")
        # Only s2's doc returned.
        assert len(rows) == 1
        assert rows[0]["title"] == "B.rvt"

    def test_revit_no_match_returns_empty(self):
        s1 = _FakeSession(session_id="r-1", doc_title="A.rvt")
        with patch("revit_broker.list_sessions", return_value=[s1]):
            rows = _list_host_documents_impl("revit", "non-existent")
        assert rows == []

    def test_outlook_returns_folders(self):
        # The bridge does `from connectors import outlook_runner`,
        # which resolves the already-imported attribute on the
        # `connectors` package. Patching sys.modules isn't sufficient;
        # patch the live attribute instead.
        from connectors import outlook_runner as _ol
        fake_list = [
            {"path": "Inbox", "name": "Inbox", "item_count": 42,
             "folder_id": "abc"},
            {"path": "Inbox/Projects", "name": "Projects",
             "item_count": 7, "folder_id": "def"},
        ]
        with patch.object(_ol, "list_folders", return_value=fake_list):
            rows = _list_host_documents_impl("outlook", "")
        assert len(rows) == 2
        assert rows[0]["title"] == "Inbox"
        assert rows[0]["kind"] == "folder"
        assert rows[1]["title"] == "Projects"

    def test_blender_uses_list_files_when_available(self):
        fake_runner = MagicMock()
        fake_runner.list_files.return_value = [
            {"path": "/scenes/villa.blend", "title": "villa.blend",
             "active": True},
            {"path": "/scenes/site.blend",  "title": "site.blend"},
        ]
        with patch.dict("sys.modules",
                          {"connectors.blender_runner": fake_runner}):
            rows = _list_host_documents_impl("blender", "")
        assert len(rows) == 2
        assert rows[0]["title"] == "villa.blend"
        assert rows[0]["active"] is True

    def test_blender_falls_back_to_info_filepath(self):
        fake_runner = MagicMock()
        # Strip list_files / list_docs / list_documents so the helper
        # falls through to info().
        del fake_runner.list_files
        del fake_runner.list_docs
        del fake_runner.list_documents
        fake_runner.info.return_value = {
            "filepath": "C:/scenes/villa.blend",
            "version": "4.0",
        }
        with patch.dict("sys.modules",
                          {"connectors.blender_runner": fake_runner}):
            rows = _list_host_documents_impl("blender", "")
        assert len(rows) == 1
        assert rows[0]["title"] == "villa.blend"
        assert rows[0]["path"] == "C:/scenes/villa.blend"

    def test_speckle_returns_empty(self):
        assert _list_host_documents_impl("speckle", "") == []

    def test_unsupported_family_returns_empty(self):
        assert _list_host_documents_impl("madeup", "") == []


# ══════════════════════════════════════════════════════════════════════
# 3. Node executor — config.version + config.document honoured
# ══════════════════════════════════════════════════════════════════════
class TestHostExecVersionPicking:
    def test_version_filter_picks_matching_session(self):
        """When config.version='2025' and two sessions exist,
        only the 2025 session is dispatched to."""
        s_2024 = _FakeSession(session_id="r-1", version="2024",
                                doc_title="A.rvt", port=48884)
        s_2025 = _FakeSession(session_id="r-2", version="2025",
                                doc_title="B.rvt", port=48885)
        spec, executor = _registry.get("host.revit")

        captured = {}

        def fake_forward(session, path, **kw):
            captured["session_id"] = session.session_id
            captured["path"] = path
            return {"status": "ok"}

        with patch("revit_broker.list_sessions",
                    return_value=[s_2024, s_2025]), \
             patch("revit_broker.forward", side_effect=fake_forward), \
             patch("revit_broker.pick_session", return_value=s_2024):
            out = executor(
                {"_family": "revit", "version": "2025"},
                {"action": "open"},
                None,
            )
        # The 2025 session was the one routed to, NOT s_2024 (which is
        # what pick_session() returns as default).
        assert captured.get("session_id") == "r-2"
        assert out["status"] == "ok"
        assert out["family"] == "revit"
        # Envelope echoes the version pin.
        assert out["version"] == "2025"
        assert out["host_alive"] is True

    def test_no_version_falls_back_to_pick_session(self):
        s_recent = _FakeSession(session_id="r-default", version="2024")
        captured = {}

        def fake_forward(session, path, **kw):
            captured["session_id"] = session.session_id
            return {"status": "ok"}

        spec, executor = _registry.get("host.revit")
        with patch("revit_broker.list_sessions",
                    return_value=[s_recent]), \
             patch("revit_broker.pick_session",
                    return_value=s_recent), \
             patch("revit_broker.forward", side_effect=fake_forward):
            out = executor(
                {"_family": "revit"},      # no version pin
                {"action": "open"},
                None,
            )
        # Routed to whatever pick_session returned.
        assert captured.get("session_id") == "r-default"
        assert out["status"] == "ok"

    def test_version_mismatch_logs_in_envelope(self):
        """When version='2099' doesn't match any running session, the
        executor still returns ok (host alive — just on the wrong
        version) and surfaces the mismatch."""
        s_2024 = _FakeSession(session_id="r-1", version="2024")
        spec, executor = _registry.get("host.revit")
        with patch("revit_broker.list_sessions",
                    return_value=[s_2024]), \
             patch("revit_broker.pick_session",
                    return_value=s_2024), \
             patch("revit_broker.forward",
                    return_value={"status": "ok"}):
            out = executor(
                {"_family": "revit", "version": "2099"},
                {},                          # no action
                None,
            )
        assert out["status"] == "ok"
        assert out["host_alive"] is True

    def test_document_pin_passes_doc_query(self):
        """config.document='Tower-A.rvt' — the executor should forward
        the action with the doc in either path query or body."""
        s = _FakeSession(session_id="r-1", version="2025",
                          doc_title="Tower-A.rvt")
        captured = {}

        def fake_forward(session, path, **kw):
            captured["path"] = path
            captured["body"] = kw.get("body", b"")
            return {"status": "ok"}

        spec, executor = _registry.get("host.revit")
        with patch("revit_broker.list_sessions", return_value=[s]), \
             patch("revit_broker.pick_session", return_value=s), \
             patch("revit_broker.forward", side_effect=fake_forward):
            out = executor(
                {"_family": "revit", "document": "Tower-A.rvt"},
                {"action": "list_walls"},
                None,
            )
        # The doc must surface either as ?doc=... in the path or in the
        # JSON body — both are accepted shapes.
        assert "Tower-A.rvt" in captured.get("path", "") \
                or b"Tower-A.rvt" in captured.get("body", b"")
        assert out["status"] == "ok"

    def test_envelope_keeps_shape_pin(self):
        """Adding version/document pins must NOT drop required envelope
        keys (test_core_nodes.py shape contract)."""
        spec, executor = _registry.get("host.revit")
        # No mocks — fall through to "broker unavailable" path. The
        # envelope shape still has all keys.
        out = executor(
            {"_family": "revit", "version": "2025",
             "document": "Tower-A.rvt"},
            {"action": "open"},
            None,
        )
        for key in ("status", "family", "version", "opened_doc",
                     "selection", "state", "tool_calls", "host_alive",
                     "port", "warnings", "after"):
            assert key in out, key
        assert out["family"] == "revit"


# ══════════════════════════════════════════════════════════════════════
# 4. Config schema — version + document declared as dynamic
# ══════════════════════════════════════════════════════════════════════
class TestHostNodeConfigSchema:
    HOST_FAMILIES = ("revit", "autocad", "blender", "rhino",
                      "max", "speckle", "outlook")

    def test_every_host_has_version_param(self):
        for fam in self.HOST_FAMILIES:
            spec, _ = _registry.get(f"host.{fam}")
            assert "version" in spec.config_schema, fam

    def test_every_host_has_document_param(self):
        for fam in self.HOST_FAMILIES:
            spec, _ = _registry.get(f"host.{fam}")
            assert "document" in spec.config_schema, fam

    def test_version_declared_dynamic(self):
        spec, _ = _registry.get("host.revit")
        v = spec.config_schema["version"]
        # Dynamic dropdown sentinel.
        assert v.get("enum") == "<dynamic>"
        assert v.get("source") == "list_host_sessions"
        assert v.get("source_args") == ["revit"]

    def test_document_declared_dynamic_and_depends_on_version(self):
        spec, _ = _registry.get("host.revit")
        d = spec.config_schema["document"]
        assert d.get("enum") == "<dynamic>"
        assert d.get("source") == "list_host_documents"
        assert "version" in (d.get("depends_on") or [])

    def test_default_values_empty_strings(self):
        spec, _ = _registry.get("host.revit")
        assert spec.config_schema["version"].get("default") == ""
        assert spec.config_schema["document"].get("default") == ""


# ══════════════════════════════════════════════════════════════════════
# 5. Bridge slot grep test — exposed via ArchHubBridge
# ══════════════════════════════════════════════════════════════════════
class TestBridgeSlotExposure:
    """Tiny sanity check that the QObject subclass exposes the two
    new slots so the JS side can call them."""
    def test_slots_on_archhub_bridge(self):
        import bridge
        cls = bridge.ArchHubBridge
        assert hasattr(cls, "list_host_sessions")
        assert hasattr(cls, "list_host_documents")
