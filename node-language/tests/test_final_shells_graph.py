"""FINAL-SHELLS-GRAPH lane — close the last shells + fix the illogical session graph.

RED→GREEN gates for the four founder-caught fakes (proven RED via `git stash`
of the lane diff, GREEN on the branch — see the PR body):

  FIX 1 — GRAPH-HEALTH CHIP: the Home top-bar chip looked clickable but its
          onClick fired a DIFFERENT surface (the self-heal inspector) — a dead
          end for "graph health". It now dispatches `lm-graph-health-open` and
          the footer HealthStripItem listens + opens its real issue-list popover.
          ALSO: on Home with no canvas open it showed a confident green "healthy"
          about a graph not on screen — now an honest neutral "no canvas open".

  FIX 2 — FAKE ACCOUNT CHIPS: the ChatsPanel footer AND the Nodes-panel footer
          hardcoded avatar 'F' + name 'Fargaly' + 'BYO · CLOUD'. Replaced by ONE
          <AccountIdentity/> fed by REAL cloud_status (email/plan) + the live
          provider tags (shared providerTag table). No fabricated name/plan.

  FIX 3 — CLEAR ALL NODES: the canvas context-menu handler set wires=[] then
          only iterated `userNodes`, leaving LM_GRAPH.nodes populated while it
          toasted "Cleared" — a lie. It now clears ALL nodes+wires+groups and
          the toast states what was actually cleared.

  FIX 4 — SESSION GRAPH LOGICAL CLEANUP: a long chat opened as ~66 stacked
          identical reasoning cards in one column. The migrator now COLLAPSES
          consecutive same-kind reasoning turns into ONE "Thinking ×N" node and
          lays the graph out as a real left→right DAG (multiple columns), while
          keeping round-trip safety + canvas-built sessions unchanged.

JSX fixes are gated by SOURCE guards on the comment-stripped .jsx text (the same
mechanism tests/test_jsx_signal_wiring.py uses — an assertion can't be satisfied
by a comment). FIX 4 is gated by PURE data tests on the owned migrator. The
LIVE behaviour (popover opens, toast shows, canvas paints columns) is called out
in the PR's CDP testids section as requiring a running window to fully confirm.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

_JSX_SRC = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
# Comment-stripped view so an assertion can't be satisfied by a comment that
# merely MENTIONS the old literal / the old behaviour. Same mechanism as
# tests/test_jsx_signal_wiring.py — strip `//` line comments. (The lane keeps
# its own explanatory comments free of the exact rendered literals so this is
# sufficient; a `/* … */` block-comment strip is intentionally avoided — a
# non-greedy DOTALL sweep over a ~1 MB source is needless work here.)
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
_JSX_FLAT = re.sub(r"\s+", " ", _JSX_CODE)


def _window(anchor: str, size: int = 2600) -> str:
    i = _JSX_CODE.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return _JSX_CODE[i:i + size]


# ─────────────────────── FIX 1 — graph-health chip ───────────────────────
class TestFix1GraphHealthChip:
    def test_chip_dispatches_real_health_open_event(self):
        """The Home chip must dispatch lm-graph-health-open (open the REAL
        detail), NOT the old dead-end self-heal-inspector event."""
        win = _window("data-testid=\"home-graph-health-chip\" data-graph-state=\"active\"")
        assert "lm-graph-health-open" in win, (
            "active graph-health chip must dispatch lm-graph-health-open")

    def test_chip_no_longer_routes_to_self_heal_inspector(self):
        """The active chip's onClick must NOT fire the self-heal inspector
        (that was the dead-end pointing the user at a different element)."""
        # The whole chip component window — from the comment-stripped start of
        # the component to the end of the active-state button.
        comp = _window("const HomeGraphHealthChip", size=4000)
        # The active button (the one rendered when a graph IS open) must not
        # dispatch the self-heal inspector. We assert the inspector event does
        # not appear anywhere in the chip — the chip's job is graph health.
        assert "lm-self-heal-inspector-open" not in comp, (
            "graph-health chip must not route to the self-heal inspector")

    def test_chip_honest_empty_state_when_no_canvas(self):
        """On Home with an empty LM_GRAPH the chip is a neutral 'no canvas
        open', NOT a green 'healthy'. Gated by the empty-state branch."""
        comp = _window("const HomeGraphHealthChip", size=4000)
        assert "data-graph-state=\"empty\"" in comp
        assert "no canvas open" in comp
        # The empty branch is driven by a real node-count check, not a constant.
        assert "hasGraph" in comp and "LM_GRAPH.nodes.length" in _JSX_CODE

    def test_footer_health_strip_listens_for_open_event(self):
        """The footer HealthStripItem must subscribe to lm-graph-health-open and
        open its popover — otherwise the chip's dispatch has no receiver."""
        comp = _window("const HealthStripItem", size=2600)
        assert "lm-graph-health-open" in comp, (
            "HealthStripItem must listen for lm-graph-health-open")
        assert "setOpen(true)" in comp, (
            "HealthStripItem must open its popover on the event")


# ─────────────────────── FIX 2 — account identity ───────────────────────
class TestFix2AccountIdentity:
    def test_no_fargaly_literal_remains_in_code(self):
        """No rendered 'Fargaly' literal may remain (comments excluded)."""
        # Pre-compute booleans so a FAIL doesn't make pytest's assertion
        # introspection render the ~1 MB flattened source (which would stall the
        # run). The old fakes rendered `>Fargaly<` and used 'Fargaly' string
        # literals; comment-stripped view, so the lane's own comments don't count.
        rendered = ">Fargaly<" in _JSX_FLAT
        as_literal = ("'Fargaly'" in _JSX_CODE) or ('"Fargaly"' in _JSX_CODE)
        assert not rendered, "rendered 'Fargaly' literal remains"
        assert not as_literal, "a 'Fargaly' string literal remains in code"

    def test_no_byo_cloud_plan_literal_remains_in_code(self):
        """No rendered 'BYO · CLOUD' plan literal may remain (comments excluded)."""
        present = "BYO · CLOUD" in _JSX_CODE
        assert not present, "the fabricated 'BYO · CLOUD' plan literal remains in code"

    def test_account_identity_component_exists(self):
        assert "const AccountIdentity = ()" in _JSX_CODE, (
            "AccountIdentity component must exist")

    def test_account_identity_reads_real_cloud_status(self):
        """AccountIdentity must source email/plan from cloud_status — the same
        slot AccountChip uses — not from literals."""
        comp = _window("const AccountIdentity = ()", size=4200)
        assert "bridgeAsync('cloud_status')" in comp
        assert "setEmail" in comp and "setPlan" in comp

    def test_account_identity_uses_real_provider_tag(self):
        """The provider tag must come from the shared providerTag/accessTagsFor
        table (the real CLOUD/BYO/LOCAL mapping), not a literal."""
        comp = _window("const AccountIdentity = ()", size=4200)
        assert "accessTagsFor" in comp
        assert "get_models" in comp, "tags derived from the live model list"

    def test_account_identity_signed_out_is_honest(self):
        """Signed-out must render an honest 'Sign in', never a fabricated name."""
        comp = _window("const AccountIdentity = ()", size=4200)
        assert "data-account-state=\"signed-out\"" in comp
        assert "Sign in" in comp

    def test_rendered_in_both_footers(self):
        """<AccountIdentity/> must be rendered in BOTH panel footers so they
        can't drift — exactly the failure of the two duplicated literals."""
        assert _JSX_CODE.count("<AccountIdentity/>") >= 2, (
            "AccountIdentity must render in both the Chats and Nodes footers")

    def test_provider_tag_table_is_shared_single_source(self):
        """The provider→tag / provider→label maps are module-level (one source);
        ModelPicker references them instead of a private copy that could drift."""
        assert "const providerTag = " in _JSX_CODE
        assert "const providerGroupLabel = " in _JSX_CODE
        # ModelPicker now aliases the shared helpers rather than redefining maps.
        assert "const tagFor = providerTag" in _JSX_CODE
        assert "const groupLabel = providerGroupLabel" in _JSX_CODE


# ─────────────────────── FIX 3 — clear all nodes ───────────────────────
class TestFix3ClearAllNodes:
    def test_clear_all_empties_lm_graph_nodes(self):
        """onClearAll must set LM_GRAPH.nodes = [] (not just wires) so the
        canvas is truly cleared — the toast was lying before."""
        win = _window("onClearAll={()", size=1400)
        assert "LM_GRAPH.nodes = []" in win, (
            "clear-all must empty LM_GRAPH.nodes")
        assert "LM_GRAPH.wires = []" in win
        assert "LM_GRAPH.groups = []" in win

    def test_clear_all_toast_matches_reality(self):
        """The toast must report what was actually cleared (a count / empty
        state), not an unconditional 'Cleared' over a still-populated graph."""
        win = _window("onClearAll={()", size=1400)
        # Truthful toast: states the count cleared, or 'already empty'.
        assert "Cleared ${had}" in win or "Cleared $" in win
        assert "already empty" in win
        # And it must NOT be the old unconditional bare 'Cleared'.
        assert "flashToast('Cleared')" not in win, (
            "bare unconditional 'Cleared' toast must be gone")

    def test_clear_all_persists(self):
        win = _window("onClearAll={()", size=1400)
        assert "saveCurrentGraph()" in win, "clear-all must persist the empty graph"


# ─────────────────────── FIX 4 — session graph cleanup ───────────────────────
class _Msg:
    def __init__(self, role, content, tool_invocations=None):
        self.role = role
        self.content = content
        self.tool_invocations = tool_invocations or []


class _Session:
    def __init__(self, sid="sess_test", graph=None):
        self.id = sid
        self.graph = graph


def _wall_of_reasoning(n=66):
    """The founder's case: one user intent, then N back-to-back pure-reasoning
    assistant turns, then a real tool turn, then the answer."""
    msgs = [_Msg("user", "do the analysis")]
    for i in range(n):
        msgs.append(_Msg("assistant", f"reasoning step {i}"))
    msgs.append(_Msg("user", "now read the file"))
    msgs.append(_Msg("assistant", "reading", tool_invocations=[
        {"tool_name": "Read", "arguments": {"file_path": "/x"},
         "status": "called", "result": "ok"}]))
    msgs.append(_Msg("assistant", "there are 12 walls"))
    return msgs


class TestFix4Collapse:
    def test_collapse_merges_consecutive_reasoning_into_one(self):
        from session_graph_migrator import collapse_consecutive_turns
        coll = collapse_consecutive_turns(_wall_of_reasoning(66))
        # user, [66 reasoning → 1], user, assistant(tool), assistant = 5
        assert len(coll) == 5, f"expected 5 logical turns, got {len(coll)}"
        collapsed_asst = [m for m in coll if m.get("_collapsed_count")]
        assert len(collapsed_asst) == 1
        assert collapsed_asst[0]["_collapsed_count"] == 66

    def test_tool_turn_is_never_collapsed(self):
        """An assistant turn that calls a tool stays its own turn — it's a real
        decision, not 'thinking'."""
        from session_graph_migrator import collapse_consecutive_turns
        msgs = [
            _Msg("assistant", "a", tool_invocations=[
                {"tool_name": "Read", "arguments": {}}]),
            _Msg("assistant", "b", tool_invocations=[
                {"tool_name": "Grep", "arguments": {}}]),
        ]
        coll = collapse_consecutive_turns(msgs)
        assert len(coll) == 2, "tool-bearing turns must not collapse together"
        assert all(not m.get("_collapsed_count") for m in coll)

    def test_alternating_turns_not_collapsed(self):
        from session_graph_migrator import collapse_consecutive_turns
        msgs = [_Msg("user", "q1"), _Msg("assistant", "a1"),
                _Msg("user", "q2"), _Msg("assistant", "a2")]
        coll = collapse_consecutive_turns(msgs)
        assert len(coll) == 4
        assert all(not m.get("_collapsed_count") for m in coll)

    def test_decompose_collapses_n_reasoning_into_one_node(self):
        """The HEADLINE: 66 consecutive reasoning turns → ONE llm node, not 66.
        The whole graph is a handful of distinct nodes, not a 66-card stack."""
        from session_graph_migrator import decompose_legacy_as_graph
        g = decompose_legacy_as_graph(_Session(), _wall_of_reasoning(66),
                                      name="chat")
        llm_nodes = [n for n in g["nodes"]
                     if (n.get("type") or "").startswith("llm.")]
        # 3 assistant turns after collapse (thinking×66, tool turn, answer).
        assert len(llm_nodes) == 3, (
            f"66 reasoning turns must collapse — expected 3 llm nodes, "
            f"got {len(llm_nodes)}")
        # The collapsed node is labelled + carries the count.
        thinking = [n for n in llm_nodes if "×" in (n.get("label") or "")]
        assert thinking, "a 'Thinking ×N' node must exist"
        assert thinking[0]["config"]["collapsed_count"] == 66
        assert thinking[0]["config"]["collapsed"] is True
        # The whole graph is small + logical, not a wall.
        assert len(g["nodes"]) <= 12, (
            f"a collapsed chat graph must be a clean ~handful of nodes, "
            f"got {len(g['nodes'])}")

    def test_layout_is_multi_column_dag_not_a_stacked_column(self):
        """The layout must produce MULTIPLE x columns (a real left→right DAG),
        not all-same-x (the top-down column the founder hates)."""
        from session_graph_migrator import decompose_legacy_as_graph
        g = decompose_legacy_as_graph(_Session(), _wall_of_reasoning(66),
                                      name="chat")
        xs = sorted({round(n["position"]["x"], 1) for n in g["nodes"]})
        assert len(xs) > 1, (
            f"layout must branch into multiple columns, got a single x: {xs}")

    def test_layout_dag_orders_by_dependency_depth(self):
        """A downstream node sits to the RIGHT of its upstream node."""
        from session_graph_migrator import layout_dag
        nodes = [{"id": "a", "position": {"x": 0, "y": 0}},
                 {"id": "b", "position": {"x": 0, "y": 0}},
                 {"id": "c", "position": {"x": 0, "y": 0}}]
        edges = [{"src_node": "a", "dst_node": "b"},
                 {"src_node": "b", "dst_node": "c"}]
        layout_dag(nodes, edges)
        by_id = {n["id"]: n for n in nodes}
        assert by_id["a"]["position"]["x"] < by_id["b"]["position"]["x"]
        assert by_id["b"]["position"]["x"] < by_id["c"]["position"]["x"]

    def test_round_trip_still_recovers_all_messages(self):
        """Round-trip safety: the on-disk wrap form still recovers EVERY message
        verbatim — the collapse only affects the canvas decomposition."""
        from session_graph_migrator import (
            wrap_legacy_as_graph, extract_messages_from_graph)
        msgs = _wall_of_reasoning(66)
        wrapped = wrap_legacy_as_graph(_Session(), msgs, name="chat")
        back = extract_messages_from_graph(wrapped)
        assert len(back) == len(msgs), (
            f"round-trip lost messages: {len(back)} != {len(msgs)}")
        assert back[0] == {"role": "user", "content": "do the analysis"}
        assert back[-1] == {"role": "assistant", "content": "there are 12 walls"}

    def test_full_pipeline_rail_keeps_full_history(self):
        """Through the real bridge path (graph_to_lmgraph), the ai_chat rail
        still carries the FULL un-collapsed conversation (expandable to turns),
        even though the node graph is collapsed."""
        from workflows.graph_to_lmgraph import decompose_session_to_graph
        msgs = _wall_of_reasoning(66)
        lm = decompose_session_to_graph(_Session(), msgs, name="chat")
        ai = [n for n in lm["nodes"] if n.get("cat") == "ai"]
        assert ai and ai[0]["kind"] == "ai_chat"
        assert len(ai[0].get("messages") or []) == len(msgs), (
            "the chat rail must keep the full history for expansion")
        # And the LM_GRAPH is multi-column (real DAG) too.
        xs = sorted({round(n["x"], 1) for n in lm["nodes"]})
        assert len(xs) > 1

    def test_canvas_built_session_unchanged(self):
        """A real user-built (canvas) graph passes through 1:1 with its OWN
        positions honoured — revfix-style sessions render exactly as today."""
        from workflows.graph_to_lmgraph import decompose_session_to_graph
        built = {"id": "g", "nodes": [
            {"id": "a", "type": "host.revit", "config": {},
             "inputs": [], "outputs": [], "position": {"x": 100.0, "y": 100.0}},
            {"id": "b", "type": "transform.apply", "config": {},
             "inputs": [], "outputs": [], "position": {"x": 400.0, "y": 100.0}},
        ], "edges": [{"id": "e", "src_node": "a", "src_port": "out",
                      "dst_node": "b", "dst_port": "in"}]}
        lm = decompose_session_to_graph(_Session(graph=built), [], name="revfix")
        assert len(lm["nodes"]) == 2, "canvas graph must pass through 1:1"
        xs = sorted(round(n["x"], 1) for n in lm["nodes"])
        assert xs == [100.0, 400.0], (
            "canvas-built node positions must be honoured exactly, not relaid")

    def test_empty_chat_still_single_node(self):
        """No messages → the single conversation-node wrap (canvas never blank).
        The collapse must not change this legitimate single-node case."""
        from session_graph_migrator import decompose_legacy_as_graph
        g = decompose_legacy_as_graph(_Session(), [], name="empty")
        assert len(g["nodes"]) == 1
        assert g["nodes"][0]["type"] == "conversation.chat"
