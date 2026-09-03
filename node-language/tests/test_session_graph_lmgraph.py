"""SESSIONS-GRAPH lane — every chat session opens as a MODULAR node graph.

RED→GREEN gate for the fix to the founder bug "every chat session opens as ONE
flat conversation node" (64/67 sessions were a single `conversation.chat` blob).

Two root causes, both gated here:
  1. WRAP-AS-ONE: the message log was wrapped into ONE node, hiding the per-turn
     structure. `session_graph_migrator.decompose_legacy_as_graph` +
     `workflows.graph_to_lmgraph.decompose_session_to_graph` now decompose a
     chat into one node per turn + a tool node per tool call.
  2. SHAPE MISMATCH: the emitted graph used the workflows.graph shape
     (`type` / `inputs` / `outputs`) but the JSX canvas renderer dispatches on
     `kind` / `cat` and draws sockets from `ins` / `outs`. The new translator
     `workflows.graph_to_lmgraph.translate_graph_to_lmgraph` maps to the
     LM_GRAPH shape the renderer needs.

RED on origin/main: `workflows.graph_to_lmgraph` does not exist (ImportError)
and the migrator has no `decompose_legacy_as_graph`, so EVERY test in this file
errors/fails. GREEN on the lane branch. Proven via `git stash` in the PR body.

Pure data tests — no Qt, no LLM, no I/O, no dependency on the user's real
on-disk sessions (a self-contained legacy-session fixture is built in-test).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ── Fixtures: ChatMessage + Session stand-ins matching the real contract ──
class _Msg:
    """ChatMessage stand-in: role / content (+ optional tool_invocations),
    matching what session_io stores and chat_to_workflow reads."""
    def __init__(self, role, content, tool_invocations=None):
        self.role = role
        self.content = content
        self.tool_invocations = tool_invocations or []


class _Session:
    """Session stand-in carrying just id + graph (what the decomposer reads)."""
    def __init__(self, sid="sess_test", graph=None):
        self.id = sid
        self.graph = graph


def _legacy_chat_messages():
    """A realistic multi-turn legacy chat: 2 user turns, 2 assistant turns, the
    first assistant turn calls two tools. This is the structure that lived ONLY
    in the message log of a wrapped single-node session."""
    return [
        _Msg("user", "List the walls then summarise them."),
        _Msg("assistant", "On it.", tool_invocations=[
            {"tool_name": "Read", "arguments": {"file_path": "/a/walls.txt"},
             "status": "called", "result": "ok"},
            {"tool_name": "ToolSearch", "arguments": {"query": "walls"},
             "status": "called", "result": "ok"},
        ]),
        _Msg("user", "Now count them."),
        _Msg("assistant", "There are 12 walls."),
    ]


# A graph dict in the workflows.graph shape (Workflow.to_dict / wrap_legacy):
# nodes carry `type` + `inputs`/`outputs` + `config` + `position`, NO kind/cat.
def _workflows_graph_shape():
    return {
        "id": "g_test",
        "name": "test",
        "nodes": [
            {"id": "in1", "type": "input.parameter", "label": "Prompt",
             "config": {"name": "prompt", "default": "hi"},
             "inputs": [],
             "outputs": [{"name": "value", "type": "string"}],
             "position": {"x": 0.0, "y": 0.0}},
            {"id": "llm1", "type": "conversation.chat", "label": "Chat",
             "config": {"model": "auto",
                        "body": {"messages": [
                            {"role": "user", "content": "hi"},
                            {"role": "assistant", "content": "hello"}]}},
             "inputs": [{"name": "prompt", "type": "string"}],
             "outputs": [{"name": "text", "type": "string"},
                         {"name": "tool_invocations", "type": "list"}],
             "position": {"x": 0.0, "y": 0.0}},
            {"id": "tool1", "type": "tool.Read", "label": "Read",
             "config": {},
             "inputs": [{"name": "file_path", "type": "any"}],
             "outputs": [{"name": "result", "type": "tool_result"},
                         {"name": "ok", "type": "boolean"}],
             "position": {"x": 0.0, "y": 0.0}},
            {"id": "out1", "type": "output.parameter", "label": "Answer",
             "config": {"name": "answer"},
             "inputs": [{"name": "value", "type": "string"}],
             "outputs": [{"name": "value", "type": "string"}],
             "position": {"x": 0.0, "y": 0.0}},
        ],
        "edges": [
            {"id": "e1", "src_node": "in1", "src_port": "value",
             "dst_node": "llm1", "dst_port": "prompt"},
            {"id": "e2", "src_node": "llm1", "src_port": "tool_invocations",
             "dst_node": "tool1", "dst_port": "file_path"},
            {"id": "e3", "src_node": "llm1", "src_port": "text",
             "dst_node": "out1", "dst_port": "value"},
        ],
    }


# The JSX renderer's per-node contract: it dispatches on `kind`/`cat` and draws
# sockets from `ins`/`outs` (arrays of {id, label, t}). This validator is the
# machine-checkable form of "the JSX-expected shape validates".
def _assert_lmgraph_node_shape(n):
    assert isinstance(n, dict)
    for key in ("id", "kind", "cat", "ins", "outs"):
        assert key in n, f"node missing {key!r}: {n!r}"
    assert isinstance(n["id"], str) and n["id"]
    assert isinstance(n["kind"], str) and n["kind"]
    assert isinstance(n["cat"], str) and n["cat"]
    assert isinstance(n["ins"], list), "ins must be a list (JSX maps over it)"
    assert isinstance(n["outs"], list), "outs must be a list"
    for port in list(n["ins"]) + list(n["outs"]):
        assert isinstance(port, dict)
        assert "id" in port and "t" in port, f"port not {{id,label,t}}: {port!r}"


def _assert_lmgraph_wires_resolve(g):
    """Every wire is {from:[nodeId,portId], to:[nodeId,portId]} and BOTH ends
    resolve to a node + a port on that node — otherwise the JSX wire vanishes."""
    by_id = {n["id"]: n for n in g["nodes"]}
    for w in g["wires"]:
        assert isinstance(w.get("from"), list) and len(w["from"]) == 2
        assert isinstance(w.get("to"), list) and len(w["to"]) == 2
        sn = by_id.get(w["from"][0])
        tn = by_id.get(w["to"][0])
        assert sn is not None, f"wire from unknown node {w['from'][0]!r}"
        assert tn is not None, f"wire to unknown node {w['to'][0]!r}"
        if w["from"][1]:
            assert any(p["id"] == w["from"][1] for p in sn["outs"]), \
                f"wire src port {w['from'][1]!r} not on {sn['kind']!r}"
        if w["to"][1]:
            assert any(p["id"] == w["to"][1] for p in tn["ins"]), \
                f"wire dst port {w['to'][1]!r} not on {tn['kind']!r}"


# ── 1. The pure translator: workflows.graph shape → LM_GRAPH shape ────────
class TestTranslator:
    def test_module_importable(self):
        # RED on origin/main: this module does not exist there.
        import workflows.graph_to_lmgraph  # noqa: F401

    def test_translate_maps_type_to_kind_and_cat(self):
        from workflows.graph_to_lmgraph import translate_graph_to_lmgraph
        lm = translate_graph_to_lmgraph(_workflows_graph_shape())
        assert len(lm["nodes"]) == 4
        by_kind = {n["kind"]: n for n in lm["nodes"]}
        # conversation.chat → ai_chat / cat ai (the visible grammar primitive,
        # NOT the hidden legacy `ai` master).
        assert "ai_chat" in by_kind
        assert by_kind["ai_chat"]["cat"] == "ai"
        # input.parameter → parameter / input; output.parameter → result / output
        assert "parameter" in by_kind and by_kind["parameter"]["cat"] == "input"
        assert "result" in by_kind and by_kind["result"]["cat"] == "output"
        # tool.Read has no grammar primitive → prefix fallback to cat connector.
        assert "tool.Read" in by_kind
        assert by_kind["tool.Read"]["cat"] == "connector"

    def test_translate_populates_ins_outs_arrays(self):
        from workflows.graph_to_lmgraph import translate_graph_to_lmgraph
        lm = translate_graph_to_lmgraph(_workflows_graph_shape())
        for n in lm["nodes"]:
            _assert_lmgraph_node_shape(n)
        by_kind = {n["kind"]: n for n in lm["nodes"]}
        # The chat node's outputs become {id,label,t} ports.
        chat_outs = {p["id"] for p in by_kind["ai_chat"]["outs"]}
        assert "text" in chat_outs and "tool_invocations" in chat_outs

    def test_translate_edges_become_wires(self):
        from workflows.graph_to_lmgraph import translate_graph_to_lmgraph
        lm = translate_graph_to_lmgraph(_workflows_graph_shape())
        assert "wires" in lm and len(lm["wires"]) == 3
        for w in lm["wires"]:
            assert isinstance(w["from"], list) and isinstance(w["to"], list)
        _assert_lmgraph_wires_resolve(lm)

    def test_chat_node_carries_messages(self):
        from workflows.graph_to_lmgraph import translate_graph_to_lmgraph
        lm = translate_graph_to_lmgraph(_workflows_graph_shape())
        chat = next(n for n in lm["nodes"] if n["kind"] == "ai_chat")
        assert isinstance(chat.get("messages"), list)
        assert len(chat["messages"]) == 2
        # SESSION-REOPEN FIX: messages come back in the canvas {me,text} shape
        # the JSX renderer reads — NOT the persisted {role,content}. A
        # conversation.chat node stores config.body.messages as {role,content};
        # the translator must map role 'user' → me:true, content → text.
        assert chat["messages"][0]["me"] is True
        assert chat["messages"][0]["text"] == "hi"
        assert chat["messages"][1]["me"] is False
        assert chat["messages"][1]["text"] == "hello"
        # The divergent persisted keys must NOT leak onto the canvas message.
        assert "role" not in chat["messages"][0]
        assert "content" not in chat["messages"][0]

    def test_empty_graph_safe(self):
        from workflows.graph_to_lmgraph import translate_graph_to_lmgraph
        assert translate_graph_to_lmgraph(None) == {"nodes": [], "wires": []}
        assert translate_graph_to_lmgraph({}) == {"nodes": [], "wires": []}


# ── 2. Per-turn decomposition: a chat becomes a MODULAR graph (root cause 1) ─
class TestDecomposition:
    def test_migrator_decompose_is_multinode(self):
        # RED on origin/main: decompose_legacy_as_graph does not exist there.
        from session_graph_migrator import decompose_legacy_as_graph
        g = decompose_legacy_as_graph(_Session(), _legacy_chat_messages(),
                                      name="chat")
        # Per-turn: 2 inputs + 2 llm + 2 tools + 1 output = 7 nodes (>1).
        assert len(g["nodes"]) > 1
        types = [n["type"] for n in g["nodes"]]
        assert any(t == "input.parameter" for t in types)
        assert any(t and t.startswith("llm.") for t in types)
        assert any(t and t.startswith("tool.") for t in types)
        assert any(t == "output.parameter" for t in types)

    def test_decompose_session_to_graph_is_modular_lmgraph(self):
        """THE headline assertion: a legacy chat → an LM_GRAPH with >1 node,
        each with kind+cat+ins+outs, JSX-shape valid, wires all resolve."""
        from workflows.graph_to_lmgraph import decompose_session_to_graph
        g = decompose_session_to_graph(_Session(), _legacy_chat_messages(),
                                       name="chat")
        assert len(g["nodes"]) > 1, "a chat must decompose into MANY nodes"
        for n in g["nodes"]:
            _assert_lmgraph_node_shape(n)
        _assert_lmgraph_wires_resolve(g)
        # The modular pieces are present + typed for the canvas.
        cats = {n["cat"] for n in g["nodes"]}
        assert {"input", "ai", "connector", "output"} <= cats
        # The conversation rail rides on an ai_chat node with all the turns.
        ai = [n for n in g["nodes"] if n["cat"] == "ai"]
        assert ai and ai[0]["kind"] == "ai_chat"
        assert len(ai[0].get("messages") or []) == len(_legacy_chat_messages())

    def test_tool_nodes_have_resolvable_ports(self):
        """Tool nodes (no grammar/registry spec) must still carry ins/outs so
        their wires render — incl. a no-argument tool call."""
        from workflows.graph_to_lmgraph import decompose_session_to_graph
        msgs = [
            _Msg("user", "screenshot please"),
            _Msg("assistant", "done", tool_invocations=[
                {"tool_name": "screenshot", "arguments": {},  # NO args
                 "status": "called", "result": "ok"}]),
        ]
        g = decompose_session_to_graph(_Session(), msgs, name="c")
        tool_nodes = [n for n in g["nodes"] if n["kind"].startswith("tool.")]
        assert tool_nodes, "expected a tool node"
        for tn in tool_nodes:
            assert tn["ins"], "tool node must have an in-port for its wire"
            assert tn["outs"], "tool node must have out-ports"
        _assert_lmgraph_wires_resolve(g)

    def test_real_multinode_graph_passes_through(self):
        """A session that already has a real user-built multi-node graph is
        translated 1:1 (NOT re-decomposed from messages)."""
        from workflows.graph_to_lmgraph import decompose_session_to_graph
        sess = _Session(graph=_workflows_graph_shape())
        g = decompose_session_to_graph(sess, [], name="c")
        assert len(g["nodes"]) == 4  # the stored graph, translated
        for n in g["nodes"]:
            _assert_lmgraph_node_shape(n)

    def test_empty_session_still_renders_one_node(self):
        """No messages, no graph → a single conversation node (so the canvas is
        never blank). The ONLY case that is legitimately single-node."""
        from workflows.graph_to_lmgraph import decompose_session_to_graph
        g = decompose_session_to_graph(_Session(), [], name="c")
        assert len(g["nodes"]) >= 1
        for n in g["nodes"]:
            _assert_lmgraph_node_shape(n)


# ── 2b. SESSION-REOPEN BUG — chat-composer sessions reopen with the chat ──
# THE regression gate for the founder bug: real chat-composer sessions reopened
# with an EMPTY canvas because two schemas diverged — the conversation persisted
# as `conversation.chat` config.body.messages [{role,content}] (and/or top-level
# `_messages`), but the live canvas renders an ai node's messages reading
# m.me / m.text ([{me,text}]). So the reopened node found no me/text and showed
# blank. The load boundary (`decompose_session_to_graph`) must hand the canvas a
# `cat:'ai'` node whose messages carry the conversation as [{me,text}].
class TestSessionReopenCanvasShape:
    def _write_conversation_chat_session(self, tmp_path):
        """Write a REAL on-disk session file in the chat-composer schema: a
        single `conversation.chat` node with the conversation under
        config.body.messages as {role,content}, plus the legacy `_messages`
        mirror session_io writes. Returns the file path."""
        import json
        sid = "sess_reopen_" + uuid.uuid4().hex[:8]
        convo = [
            {"role": "user", "content": "What walls are on level 2?"},
            {"role": "assistant", "content": "There are 8 walls on level 2."},
            {"role": "user", "content": "Tag them."},
            {"role": "assistant", "content": "Tagged all 8."},
        ]
        data = {
            "id": sid,
            "created_at": "2026-06-01T00:00:00",
            "parameters": [],
            "chain": [],
            "graph": {
                "id": sid,
                "name": "wall tags",
                "schema_version": "1.0",
                "nodes": [
                    {"id": "conv_abc123", "type": "conversation.chat",
                     "label": "Conversation",
                     "config": {"model": "auto",
                                "body": {"messages": convo}},
                     "inputs": [], "outputs": [],
                     "position": {"x": 0.0, "y": 0.0}},
                ],
                "edges": [],
            },
            # session_io mirrors the conversation into `_messages` too.
            "_messages": [
                {"role": m["role"], "content": m["content"],
                 "model": "", "images": [], "tool_invocations": [],
                 "timestamp": ""}
                for m in convo
            ],
            "_name": "wall tags",
            "_saved_at": "2026-06-01T00:00:00",
        }
        p = tmp_path / (sid + ".archhub-session.json")
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p, convo

    def test_conversation_chat_fixture_reopens_with_me_text_messages(self, tmp_path):
        """Load a `conversation.chat`-schema session fixture through the REAL
        load path and assert the canvas graph has a cat:'ai' node whose messages
        carry the conversation as [{me,text}] — order/role mapping preserved."""
        from session_io import load_session_with_messages
        from workflows.graph_to_lmgraph import decompose_session_to_graph

        p, convo = self._write_conversation_chat_session(tmp_path)
        session, name, messages = load_session_with_messages(p)
        g = decompose_session_to_graph(session, messages, name=session.id)

        # A cat:'ai' node exists (the canvas would otherwise render empty).
        ai = [n for n in g["nodes"] if n.get("cat") == "ai"]
        assert ai, "load produced NO cat:'ai' node — canvas would be EMPTY"
        chat = next((n for n in ai if n.get("kind") == "ai_chat"), ai[0])
        msgs = chat.get("messages") or []

        # The conversation is present, IN ORDER, in the canvas {me,text} shape.
        assert len(msgs) == len(convo), "messages lost on reopen"
        for got, src in zip(msgs, convo):
            assert "me" in got and "text" in got, \
                f"canvas message not {{me,text}}: {got!r}"
            assert got["me"] is (src["role"] == "user")
            assert got["text"] == src["content"]
            # The persisted {role,content} keys must not leak through.
            assert "role" not in got and "content" not in got

    def test_normaliser_is_idempotent_and_lossless(self):
        """A message ALREADY in canvas {me,text} shape (a re-loaded canvas
        graph node) passes through unchanged; model/images preserved."""
        from workflows.graph_to_lmgraph import _canvas_messages
        already = [
            {"me": True, "text": "hi", "time": "10:00"},
            {"me": False, "text": "hello", "model": {"name": "Claude"},
             "images": ["/a.png"]},
        ]
        out = _canvas_messages(already)
        assert out[0]["me"] is True and out[0]["text"] == "hi"
        assert out[0].get("time") == "10:00"
        assert out[1]["model"] == {"name": "Claude"}
        assert out[1]["images"] == ["/a.png"]
        # Mixed: {role,content} carrying model/images normalises too.
        mixed = [{"role": "assistant", "content": "ok",
                  "model": "auto", "images": ["/b.png"]}]
        m = _canvas_messages(mixed)[0]
        assert m["me"] is False and m["text"] == "ok"
        assert m["model"] == "auto" and m["images"] == ["/b.png"]


# ── 3. The reverse map is DERIVED from the grammar (anti-drift) ───────────
class TestReverseMapGrounding:
    def test_kind_cat_derived_from_grammar(self):
        """Every (kind, cat) the translator assigns for a grammar engine type
        matches what node_grammar would give a freshly-placed node of that
        kind — so the map can't drift from the palette."""
        from workflows.graph_to_lmgraph import kind_cat_for_type
        from workflows.node_grammar import get_primitive
        for engine_type, expect_kind in (
            ("conversation.chat", "ai_chat"),
            ("llm.complete", "ai_complete"),
            ("input.parameter", "parameter"),
            ("output.parameter", "result"),
        ):
            kind, cat = kind_cat_for_type(engine_type)
            assert kind == expect_kind
            prim = get_primitive(kind)
            assert prim is not None, f"{kind} not a grammar primitive"
            assert prim.cat == cat, f"cat drift for {kind}: {prim.cat} != {cat}"
