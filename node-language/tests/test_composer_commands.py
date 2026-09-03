"""Composer slash-command parser — Python pins.

JSX `FloatingComposer` mirrors this parser so the rules stay in one
place. These tests are the canonical contract — when the JSX side
behaves differently we fix the JSX, not the parser.

Pins:
  * Each command parses correctly with and without explicit node id.
  * `→` is the founder's preferred wire arrow, but `->`, `=>`, and `to`
    also work for keyboard-only typing.
  * `apply_action` produces the same graph shape as the JSX would when
    splicing into LM_GRAPH.
  * Bare `/` opens the help list.
  * Unknown verbs fall back to help with an error message.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from workflows.composer_commands import (
    parse_composer_command, apply_action, COMMANDS, HELP_LINES,
)


# ── shared fixture: a tiny canvas-shape graph ──────────────────────
def _graph():
    return {
        "nodes": [
            {"id": "host_revit", "title": "Revit 2025",
              "outs": [{"id": "opened_doc", "label": "doc",
                          "t": "document"}]},
            {"id": "doc_revit", "title": "Tower-A central",
              "ins":  [{"id": "path", "label": "path", "t": "path"}],
              "outs": [{"id": "summary", "t": "string"}]},
            {"id": "ai", "title": "Conversation"},
        ],
        "wires": [
            {"from": ["host_revit", "opened_doc"],
              "to":   ["doc_revit", "path"]},
        ],
    }


# ── /wire ───────────────────────────────────────────────────────────
def test_parse_wire_with_unicode_arrow():
    a = parse_composer_command(
        "/wire host_revit.opened_doc → doc_revit.path")
    assert a["ok"] is True
    assert a["command"] == "wire"
    assert a["src_node"] == "host_revit"
    assert a["src_port"] == "opened_doc"
    assert a["dst_node"] == "doc_revit"
    assert a["dst_port"] == "path"


@pytest.mark.parametrize("sep", ["->", "=>", "to"])
def test_parse_wire_with_alt_separators(sep):
    a = parse_composer_command(
        f"/wire host_revit.opened_doc {sep} doc_revit.path")
    assert a["ok"] is True
    assert a["command"] == "wire"


def test_parse_wire_missing_endpoints():
    a = parse_composer_command("/wire")
    assert a["ok"] is False
    assert a["command"] == "wire"
    assert "endpoints" in a["error"].lower() or \
            "endpoints" in a["summary"].lower()


def test_parse_wire_bad_endpoint_format():
    # `host_revit-opened_doc` has no dot — should fail.
    a = parse_composer_command(
        "/wire host_revit-opened_doc → doc_revit.path")
    assert a["ok"] is False


# ── /connect alias ─────────────────────────────────────────────────
def test_parse_connect_alias_of_wire():
    a = parse_composer_command(
        "/connect host_revit.opened_doc → doc_revit.path")
    assert a["ok"] is True
    assert a["command"] == "wire"


# ── /freeze ─────────────────────────────────────────────────────────
def test_parse_freeze_uses_focused_when_no_id_given():
    a = parse_composer_command("/freeze", focused_node_id="host_revit")
    assert a["ok"] is True
    assert a["command"] == "freeze"
    assert a["node_id"] == "host_revit"


def test_parse_freeze_with_explicit_id():
    a = parse_composer_command("/freeze doc_revit",
                                focused_node_id="ai")
    assert a["ok"] is True
    assert a["node_id"] == "doc_revit"


def test_parse_freeze_with_no_target_errors():
    a = parse_composer_command("/freeze", focused_node_id=None)
    assert a["ok"] is False


# ── /delete ─────────────────────────────────────────────────────────
def test_parse_delete_focused():
    a = parse_composer_command("/delete", focused_node_id="ai")
    assert a["ok"] is True
    assert a["command"] == "delete"
    assert a["node_id"] == "ai"


def test_parse_delete_with_explicit_id():
    a = parse_composer_command("/delete host_revit")
    assert a["ok"] is True
    assert a["node_id"] == "host_revit"


# ── /rename ─────────────────────────────────────────────────────────
def test_parse_rename_focused_with_title():
    a = parse_composer_command("/rename Tower-A",
                                focused_node_id="host_revit")
    assert a["ok"] is True
    assert a["command"] == "rename"
    assert a["node_id"] == "host_revit"
    assert a["new_title"] == "Tower-A"


def test_parse_rename_requires_focus_and_title():
    a1 = parse_composer_command("/rename Tower-A", focused_node_id=None)
    assert a1["ok"] is False
    a2 = parse_composer_command("/rename", focused_node_id="host_revit")
    assert a2["ok"] is False


# ── /duplicate ──────────────────────────────────────────────────────
def test_parse_duplicate_focused():
    a = parse_composer_command("/duplicate", focused_node_id="ai")
    assert a["ok"] is True
    assert a["command"] == "duplicate"
    assert a["node_id"] == "ai"
    assert a["offset"] == {"x": 30, "y": 30}


# ── /properties ─────────────────────────────────────────────────────
def test_parse_properties():
    a = parse_composer_command("/properties", focused_node_id="ai")
    assert a["ok"] is True
    assert a["command"] == "properties"
    assert a["node_id"] == "ai"


# ── /disconnect ─────────────────────────────────────────────────────
def test_parse_disconnect():
    a = parse_composer_command(
        "/disconnect host_revit.opened_doc → doc_revit.path")
    assert a["ok"] is True
    assert a["command"] == "disconnect"
    assert a["src_node"] == "host_revit"
    assert a["dst_port"] == "path"


# ── bare / & unknowns ──────────────────────────────────────────────
def test_bare_slash_returns_help():
    a = parse_composer_command("/")
    assert a["ok"] is True
    assert a["command"] == "help"
    assert len(a["lines"]) == len(HELP_LINES)


def test_unknown_verb_returns_help_with_error():
    a = parse_composer_command("/wibble")
    assert a["ok"] is False
    assert a["command"] == "help"
    assert "unknown" in a["error"].lower()


def test_passthrough_for_plain_text():
    a = parse_composer_command("hello, how are you?")
    assert a["ok"] is True
    assert a["command"] == "_passthrough"


# ── live shape check — every COMMANDS verb returns an ok descriptor ─
def test_every_command_has_a_parse_path():
    by_name = {
        "wire":       "/wire a.x → b.y",
        "connect":    "/connect a.x → b.y",
        "disconnect": "/disconnect a.x → b.y",
        "freeze":     "/freeze focused",
        "delete":     "/delete focused",
        "rename":     "/rename New title",
        "duplicate":  "/duplicate focused",
        "properties": "/properties focused",
        "createnode": "/createnode type=demo cat=filter",
        "ping":       "/ping outlook",
    }
    for cmd in COMMANDS:
        raw = by_name[cmd]
        a = parse_composer_command(raw, focused_node_id="focused")
        assert a["ok"] is True, f"{cmd}: {a}"
        assert "summary" in a


# ── apply_action: graph mutations match the JSX path ───────────────
def test_apply_wire_appends_to_wires():
    g = _graph()
    a = parse_composer_command(
        "/wire doc_revit.summary → ai.context",
        focused_node_id="ai")
    # The ai node has no `ai.context` input declared but the parser
    # doesn't care — wire endpoints are by string. Add the input slot
    # so apply succeeds without surprise.
    g["nodes"][2]["ins"] = [{"id": "context", "t": "any"}]
    new = apply_action(g, a)
    assert any(w["from"] == ["doc_revit", "summary"]
                 and w["to"] == ["ai", "context"]
                 for w in new["wires"])


def test_apply_disconnect_removes_the_wire():
    g = _graph()
    a = parse_composer_command(
        "/disconnect host_revit.opened_doc → doc_revit.path")
    new = apply_action(g, a)
    assert not any(w["from"] == ["host_revit", "opened_doc"]
                     and w["to"] == ["doc_revit", "path"]
                     for w in new["wires"])
    # Original unchanged.
    assert any(w["from"] == ["host_revit", "opened_doc"]
                 and w["to"] == ["doc_revit", "path"]
                 for w in g["wires"])


def test_apply_freeze_toggles_node_frozen():
    g = _graph()
    a = parse_composer_command("/freeze", focused_node_id="ai")
    once = apply_action(g, a)
    twice = apply_action(once, a)
    ai_once = next(n for n in once["nodes"] if n["id"] == "ai")
    ai_twice = next(n for n in twice["nodes"] if n["id"] == "ai")
    assert ai_once["frozen"] is True
    assert ai_twice["frozen"] is False


def test_apply_delete_removes_node_and_incident_wires():
    g = _graph()
    a = parse_composer_command("/delete doc_revit")
    new = apply_action(g, a)
    assert not any(n["id"] == "doc_revit" for n in new["nodes"])
    assert all(w["from"][0] != "doc_revit" and w["to"][0] != "doc_revit"
                 for w in new["wires"])


def test_apply_rename_sets_title_on_focused():
    g = _graph()
    a = parse_composer_command("/rename Tower-A central",
                                focused_node_id="host_revit")
    new = apply_action(g, a)
    target = next(n for n in new["nodes"] if n["id"] == "host_revit")
    assert target["title"] == "Tower-A central"


def test_apply_duplicate_creates_new_node_with_offset():
    g = _graph()
    g["nodes"][0]["x"] = 100.0
    g["nodes"][0]["y"] = 200.0
    a = parse_composer_command("/duplicate", focused_node_id="host_revit")
    new = apply_action(g, a)
    clones = [n for n in new["nodes"]
                if n["id"] != "host_revit"
                 and (n.get("title") == "Revit 2025")]
    assert len(clones) == 1
    clone = clones[0]
    assert clone["id"] != "host_revit"
    assert clone["x"] == 130.0
    assert clone["y"] == 230.0


def test_apply_properties_is_a_no_op_on_graph():
    """`/properties` should not change the graph — it's a JSX-only
    affordance that pops a modal."""
    g = _graph()
    a = parse_composer_command("/properties", focused_node_id="ai")
    new = apply_action(g, a)
    assert new == g


# ── natural-language intent (spawn_host_chat) ──────────────────────
def test_intent_ping_outlook_returns_spawn_host_chat():
    a = parse_composer_command("ping outlook", "")
    assert a["ok"] is True
    assert a["command"] == "spawn_host_chat"
    assert a["family"] == "outlook"
    assert a["verb"] == "ping"
    assert a["original"] == "ping outlook"


def test_intent_outlook_inbox_returns_spawn_host_chat():
    a = parse_composer_command("outlook inbox", "")
    assert a["ok"] is True
    assert a["command"] == "spawn_host_chat"
    assert a["family"] == "outlook"
    # No recognised verb here — "inbox" isn't in INTENT_VERBS.
    assert a["verb"] is None
    assert a["remainder"] == "inbox"


def test_intent_plain_chat_passthrough():
    a = parse_composer_command("hello there", "")
    assert a["ok"] is True
    assert a["command"] == "_passthrough"


def test_intent_slash_command_takes_precedence_over_intent():
    a = parse_composer_command("/wire a.b → c.d", "")
    assert a["ok"] is True
    assert a["command"] == "wire"
    assert a["src_node"] == "a" and a["src_port"] == "b"
    assert a["dst_node"] == "c" and a["dst_port"] == "d"


def test_intent_list_walls_in_revit():
    a = parse_composer_command("list walls in revit", "")
    assert a["ok"] is True
    assert a["command"] == "spawn_host_chat"
    assert a["family"] == "revit"
    assert a["verb"] == "list"


def test_intent_whats_in_my_outlook():
    a = parse_composer_command("what's in my outlook", "")
    assert a["ok"] is True
    assert a["command"] == "spawn_host_chat"
    assert a["family"] == "outlook"
    assert a["verb"] == "what"
