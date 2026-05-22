"""Session ↔ Graph migration tests (ADR-003 Phase 2).

Pins:
  - Session.graph field defaults to None
  - to_dict omits `graph` when None (back-compat with v1.3.x loaders)
  - to_dict emits `graph` when set
  - wrap_legacy_as_graph builds a single conversation.chat node
  - extract_messages_from_graph round-trips the message list
  - update_graph_messages mutates an existing graph's chat node body
  - save_session dual-writes: legacy `_messages` AND new `graph`
  - load_session restores graph onto session.graph
  - Round-trip verification catches graph drift (one of the load-
    bearing invariants from session_io.py:save_session)
  - Pure-parametric session (no chat) still saves + loads
"""
from __future__ import annotations

import sys
import json
import tempfile
import uuid
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


def _mk_msg(role, content):
    """Tiny ChatMessage stand-in matching session_io._msg_to_dict
    contract (has .role and .content attrs)."""
    class M:
        pass
    m = M()
    m.role = role
    m.content = content
    return m


# ── Session.graph field ────────────────────────────────────────────
class TestSessionGraphField:
    def test_new_session_has_graph_none(self):
        from session import Session
        assert Session().graph is None

    def test_to_dict_omits_graph_when_none(self):
        from session import Session
        s = Session()
        d = s.to_dict()
        assert "graph" not in d

    def test_to_dict_includes_graph_when_set(self):
        from session import Session
        s = Session()
        s.graph = {"id": "g1", "nodes": [{"id": "n1",
                     "type": "conversation.chat", "config": {}}]}
        d = s.to_dict()
        assert d["graph"]["id"] == "g1"
        assert d["graph"]["nodes"][0]["type"] == "conversation.chat"


# ── Migrator helpers ───────────────────────────────────────────────
class TestMigrator:
    def test_wrap_legacy_builds_single_conversation_node(self):
        from session import Session
        from session_graph_migrator import wrap_legacy_as_graph
        s = Session()
        msgs = [_mk_msg("user", "hi"),
                _mk_msg("assistant", "hello there")]
        g = wrap_legacy_as_graph(s, msgs, name="my chat")
        assert g["name"] == "my chat"
        assert len(g["nodes"]) == 1
        node = g["nodes"][0]
        assert node["type"] == "conversation.chat"
        body = node["config"]["body"]
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][1]["content"] == "hello there"

    def test_wrap_accepts_pre_dicted_messages(self):
        from session import Session
        from session_graph_migrator import wrap_legacy_as_graph
        s = Session()
        msgs = [{"role": "user", "content": "x"},
                {"role": "assistant", "content": "y"}]
        g = wrap_legacy_as_graph(s, msgs)
        assert len(g["nodes"][0]["config"]["body"]["messages"]) == 2

    def test_wrap_empty_messages_yields_empty_node_body(self):
        from session import Session
        from session_graph_migrator import wrap_legacy_as_graph
        g = wrap_legacy_as_graph(Session(), [])
        assert g["nodes"][0]["config"]["body"]["messages"] == []

    def test_wrap_reuses_session_id(self):
        from session import Session
        from session_graph_migrator import wrap_legacy_as_graph
        s = Session()
        s.id = "fixed-id"
        g = wrap_legacy_as_graph(s, [_mk_msg("user", "x")])
        assert g["id"] == "fixed-id"

    def test_wrap_records_migration_provenance(self):
        from session import Session
        from session_graph_migrator import wrap_legacy_as_graph
        g = wrap_legacy_as_graph(Session(), [_mk_msg("user", "x")])
        assert g["metadata"]["migrated_from"] == "legacy_session"
        assert g["metadata"]["migrated_at"]

    def test_extract_round_trips_messages(self):
        from session import Session
        from session_graph_migrator import (
            wrap_legacy_as_graph, extract_messages_from_graph,
        )
        msgs = [_mk_msg("user", "first"),
                _mk_msg("assistant", "reply"),
                _mk_msg("user", "second")]
        g = wrap_legacy_as_graph(Session(), msgs)
        back = extract_messages_from_graph(g)
        assert len(back) == 3
        assert back[0] == {"role": "user", "content": "first"}
        assert back[-1] == {"role": "user", "content": "second"}

    def test_extract_returns_empty_when_no_chat_node(self):
        from session_graph_migrator import extract_messages_from_graph
        no_chat = {"nodes": [{"type": "host.revit", "config": {}}]}
        assert extract_messages_from_graph(no_chat) == []

    def test_extract_handles_none(self):
        from session_graph_migrator import extract_messages_from_graph
        assert extract_messages_from_graph(None) == []
        assert extract_messages_from_graph({}) == []

    def test_update_graph_messages_replaces_body(self):
        from session import Session
        from session_graph_migrator import (
            wrap_legacy_as_graph, update_graph_messages,
            extract_messages_from_graph,
        )
        g = wrap_legacy_as_graph(Session(), [_mk_msg("user", "first")])
        update_graph_messages(g, [_mk_msg("user", "second"),
                                    _mk_msg("assistant", "answer")])
        back = extract_messages_from_graph(g)
        assert len(back) == 2
        assert back[0]["content"] == "second"
        assert back[1]["role"] == "assistant"


# ── save_session dual-write round-trip ─────────────────────────────
class TestDualWriteRoundTrip:
    @pytest.fixture
    def tmp_sessions_dir(self, monkeypatch):
        """Force session_io to write into a temp dir."""
        import session_io
        with tempfile.TemporaryDirectory() as td:
            monkeypatch.setattr(session_io, "SESSIONS_DIR", Path(td))
            yield Path(td)

    def test_save_writes_both_messages_and_graph(self, tmp_sessions_dir):
        import session_io
        from session import Session
        s = Session()
        msgs = [_mk_msg("user", "hello"),
                _mk_msg("assistant", "hi")]
        path = session_io.save_session(s, name="t1", messages=msgs)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["_messages"]) == 2
        assert "graph" in data
        assert len(data["graph"]["nodes"]) == 1
        assert data["graph"]["nodes"][0]["type"] == "conversation.chat"

    def test_load_restores_graph_field(self, tmp_sessions_dir):
        import session_io
        from session import Session
        s = Session()
        msgs = [_mk_msg("user", "x"), _mk_msg("assistant", "y")]
        path = session_io.save_session(s, name="t2", messages=msgs)
        loaded, _name = session_io.load_session(path)
        assert loaded.graph is not None
        assert loaded.graph["nodes"][0]["type"] == "conversation.chat"
        assert len(loaded.graph["nodes"][0]["config"]["body"]["messages"]) == 2

    def test_loaded_graph_round_trips_back_to_messages(self, tmp_sessions_dir):
        import session_io
        from session import Session
        from session_graph_migrator import extract_messages_from_graph
        s = Session()
        msgs = [_mk_msg("user", "alpha"),
                _mk_msg("assistant", "beta")]
        path = session_io.save_session(s, name="t3", messages=msgs)
        loaded, _ = session_io.load_session(path)
        back = extract_messages_from_graph(loaded.graph)
        assert back == [{"role": "user", "content": "alpha"},
                          {"role": "assistant", "content": "beta"}]

    def test_existing_graph_is_preserved_and_updated(self, tmp_sessions_dir):
        """If the canvas authored a graph and added more nodes, the
        save path should preserve those nodes but refresh the chat
        node's messages."""
        import session_io
        from session import Session
        from session_graph_migrator import wrap_legacy_as_graph
        s = Session()
        s.graph = wrap_legacy_as_graph(s, [_mk_msg("user", "old")])
        # Add a second node to simulate canvas authoring.
        s.graph["nodes"].append({
            "id": "host1", "type": "host.revit",
            "config": {"version": "2025"},
            "inputs": [], "outputs": [], "position": {"x": 200, "y": 0},
        })
        # Save with newer messages.
        new_msgs = [_mk_msg("user", "new"),
                    _mk_msg("assistant", "ack")]
        path = session_io.save_session(s, name="t4", messages=new_msgs)
        data = json.loads(path.read_text(encoding="utf-8"))
        node_types = {n["type"] for n in data["graph"]["nodes"]}
        assert node_types == {"conversation.chat", "host.revit"}
        chat = next(n for n in data["graph"]["nodes"]
                     if n["type"] == "conversation.chat")
        assert chat["config"]["body"]["messages"][-1]["content"] == "ack"

    def test_pure_parametric_session_still_saves(self, tmp_sessions_dir):
        """A session with parameters/chain but no messages still saves
        (graph just wraps an empty conversation node)."""
        import session_io
        from session import Session, Parameter, ParamType
        s = Session()
        s.add_parameter(Parameter(name="height", label="Height",
                                    type=ParamType.NUMBER, value=3.0))
        path = session_io.save_session(s, name="param_only",
                                         messages=None)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["parameters"]) == 1
        # Graph exists (with empty chat body) so we always dual-write.
        assert "graph" in data
        chat = next(n for n in data["graph"]["nodes"]
                     if n["type"] == "conversation.chat")
        assert chat["config"]["body"]["messages"] == []


# ── Back-compat with v1.3.x session files (no `graph` key) ─────────
class TestBackCompat:
    def test_legacy_file_without_graph_loads_with_graph_none(self,
                                                                tmp_path):
        """A v1.3.x JSON written before the graph field existed must
        still load — session.graph stays None."""
        import session_io
        # Build a minimal legacy payload.
        legacy = {
            "id":         uuid.uuid4().hex,
            "created_at": 1778600000.0,
            "parameters": [],
            "chain":      [],
            "_name":      "legacy",
            "_saved_at":  "2026-05-12T12:00:00",
            "_messages":  [{"role": "user", "content": "hi"},
                           {"role": "assistant", "content": "yo"}],
        }
        p = tmp_path / "legacy.archhub-session.json"
        p.write_text(json.dumps(legacy), encoding="utf-8")
        session, _name = session_io.load_session(p)
        # Field exists but stays None — round-trip is faithful to the
        # legacy file shape until the next save promotes it.
        assert session.graph is None
        assert session.id == legacy["id"]
