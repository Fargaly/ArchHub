"""JSX-side signal-wiring + spawn-id contract source guards.

These lock in the six confirmed JSX-side fixes so the dead-path class
cannot silently regress (the bugs were exactly "signal emitted, no JS
subscriber" / "handler reads the wrong shape"):

  1. LIVE WIRE-STATE — `wire_state_changed` now has a subscriber that
     stamps per-edge state into a store the wires memo reads; cook-end
     `edges_state` is applied too.
  2. SINGLE-NODE COOK RESULT — `onWorkflowDone` routes a kind:"node"
     flat payload (stamped with node_id) onto the right canvas node, not
     just the `results` map.
  3. BACKEND notice TOAST — `notice` now has a subscriber → canvas toast.
  4. workflow_started — explicitly documented as no-consumer-needed
     (no fake consumer); sessions_changed is consumed in app-boot.jsx.
  5. BROKEN-WIRE adapter — the slot forwards a JSON filter blob so the
     adapter search filters by port type (was crammed into a scalar).
  6. SPAWN-ID CONTRACT (JSX half) — spawn_host_chat places the node
     under action.node_id via _forceId; all addNodeFromLibrary id-mint
     branches honor _forceId.

Source guards (grep the .jsx / .py text) — they don't need a live
canvas; the LIVE behaviour (animation paints, toast shows) is called out
in the task report as requiring a running window to fully confirm.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

_JSX_SRC = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
_BRIDGE_SRC = (APP_ROOT / "bridge.py").read_text(encoding="utf-8")
_COMPILED = (APP_ROOT / "web_ui" / "studio-lm.compiled.js").read_text(
    encoding="utf-8")
# Comment-stripped view so an assertion can't be satisfied by a comment.
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
# Whitespace-collapsed views (source aligns wire() calls with padding; the
# compiled bundle strips spaces) — lets a substring check ignore spacing.
_JSX_FLAT = re.sub(r"\s+", " ", _JSX_CODE)
_COMPILED_FLAT = re.sub(r"\s+", " ", _COMPILED)


def _jsx_window(anchor: str, size: int = 900) -> str:
    i = _JSX_CODE.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return _JSX_CODE[i:i + size]


# ── (1) live wire-state animation ───────────────────────────────────
class TestLiveWireState:
    def test_subscribes_to_wire_state_changed(self):
        assert "wire('wire_state_changed', onWireState)" in _JSX_FLAT, (
            "wire_state_changed must be subscribed (was emitted with no "
            "JS receiver)")

    def test_onwirestate_writes_store_and_repaints(self):
        block = _jsx_window("const onWireState", size=300)
        assert "LM_WIRE_STATE[" in block
        assert "bumpGraph()" in block

    def test_wire_state_store_and_canonical_edge_id_exist(self):
        assert "LM_WIRE_STATE" in _JSX_CODE
        assert "const lmWireEdgeId" in _JSX_CODE
        # The id derivation MUST mirror the runner (src.port-dst.port).
        block = _jsx_window("const lmWireEdgeId", size=220)
        assert "f[0]}.${f[1]}-${t[0]}.${t[1]}" in block

    def test_wires_memo_overlays_live_state(self):
        # Anchor on the CODE (the explainer is a comment, stripped from
        # _JSX_CODE). The memo reads the live store keyed by the canonical
        # edge id + maps it through wireStateMeta.
        assert "LM_WIRE_STATE[lmWireEdgeId(w)]" in _JSX_CODE
        block = _jsx_window("LM_WIRE_STATE[lmWireEdgeId(w)]", size=400)
        assert "wireStateMeta" in block

    def test_workflow_done_applies_edges_state(self):
        block = _jsx_window("const onWorkflowDone", size=1400)
        assert "_applyEdgesState(res.edges_state)" in block


# ── (2) single-node cook result → canvas ────────────────────────────
class TestSingleNodeCookResult:
    def test_bridge_stamps_node_id_on_run_node_payload(self):
        # The run_node worker must stamp the cooked node_id onto its flat
        # payload so the JS handler can route it. (run_node's worker is the
        # FIRST runner.pull(node_id) call site in the file.)
        block = _BRIDGE_SRC.split("runner.pull(node_id)", 1)[1][:900]
        assert '"node_id" not in res_dict' in block
        assert '{**res_dict, "node_id": node_id}' in block

    def test_onworkflowdone_routes_node_payload(self):
        block = _jsx_window("const onWorkflowDone", size=1400)
        # Handles BOTH the results map AND a flat node_id-stamped payload.
        assert "res.results" in block
        assert "res.node_id" in block
        assert "node.cooked = cooked" in block


# ── (3) backend notice toast ────────────────────────────────────────
class TestNoticeToast:
    def test_subscribes_to_notice(self):
        assert "wire('notice', onNotice)" in _JSX_FLAT

    def test_onnotice_emits_canvas_toast(self):
        block = _jsx_window("const onNotice", size=420)
        assert "lm-canvas-toast" in block
        # level → kind mapping present.
        assert "'err'" in block and "'warn'" in block


# ── (4) workflow_started documented, not faked ──────────────────────
class TestUnconsumedSignalsDocumented:
    def test_workflow_started_not_subscribed_but_documented(self):
        # No fake consumer: there must be NO wire('workflow_started', …).
        assert "wire('workflow_started'" not in _JSX_CODE
        # But it IS documented near the wiring block.
        assert "workflow_started" in _JSX_SRC

    def test_sessions_changed_consumed_in_app_boot(self):
        boot = (APP_ROOT / "web_ui" / "app-boot.jsx").read_text(
            encoding="utf-8")
        assert "wire('sessions_changed')" in boot


# ── (5) broken-wire adapter arg shape ───────────────────────────────
class TestBrokenWireAdapter:
    def test_slot_detects_json_filter_blob(self):
        # The slot must parse a JSON object in arg1 + forward in/out types.
        # (Window must clear the long docstring — use a generous span.)
        block = _BRIDGE_SRC.split("def library_suggest_swaps", 1)[1][:3500]
        assert 'in_types' in block and 'out_types' in block
        assert '_nt[:1] == "{"' in block
        assert 'args["in_types"]' in block

    def test_jsx_passes_in_out_types_filter(self):
        block = _jsx_window("Searching adapter", size=900)
        assert "in_types:[srcType]" in block
        assert "out_types:[dstType]" in block


# ── (6) spawn-id contract (JSX half) ────────────────────────────────
class TestSpawnIdContractJsx:
    def test_onagentstep_passes_node_id_into_spawn_action(self):
        block = _jsx_window("if (tool === 'spawn_node')", size=320)
        assert "node_id:" in block
        assert "a.node_id" in block

    def test_spawn_host_chat_uses_action_node_id_as_force_id(self):
        block = _jsx_window("const _forcedConvId", size=600)
        assert "action.node_id" in block
        assert "_forceId: _forcedConvId" in block

    def test_all_add_node_branches_honor_force_id(self):
        # Three id-minting branches: custom, grammar, legacy. Each must
        # prefer libItem._forceId before minting a uid. (Whitespace-flat:
        # the custom branch wraps `_forceId` and `||` across two lines.)
        assert _JSX_FLAT.count("libItem._forceId ||") == 3, (
            "every addNodeFromLibrary id-mint branch (custom/grammar/"
            "legacy) must honor _forceId so a forced spawn id lands")

    def test_wire_and_run_node_replay_resolve_against_args(self):
        # add_wire / run_node replay cases read args.* (which carry the
        # router-minted spawn id the model referenced).
        wire_block = _jsx_window("} else if (tool === 'add_wire')", size=200)
        assert "args.src_node" in wire_block and "args.dst_node" in wire_block
        run_block = _jsx_window("} else if (tool === 'run_node')", size=160)
        assert "args.node_id" in run_block


# ── (7) PLAN-MODE WRITE GATE wired end-to-end (jury LENS 3) ──────────
# The defect the jury refuted: the bridge agent_step slot accepts `mode` and
# run_agent_step gates host-writes on it (REAL, tested in test_plan_mode_gate),
# but the JSX never used it — (1) the agent_step call sent only 3 args so the
# backend always gated at the default, blind to Plan/Auto/YOLO; (2) onAgentStep
# ignored the backend a.gated/a.approval payload; (3) the client gate called a
# dead bridgeCall('composer_write_gate', …) slot that does not exist in
# bridge.py. These guards pin the corrective wiring so the class cannot regress.
class TestPlanModeGateWiring:
    def test_agent_step_call_sends_live_composer_mode_arg(self):
        # The sole agent_step call must pass a 4th/5th arg sourced from the LIVE
        # composer mode — NOT a bare 'plan' literal. Positional order matches
        # bridge.py agent_step(user_msg, graph_json, focused_node_id, mode), so
        # the mode lands in the `mode` param and the backend gates per the
        # user's selection. The arg derives from the in-scope React `mode` with
        # a window.__archhub_composer_mode fallback (the documented live mirror).
        block = _jsx_window("bridgeCall('agent_step'", size=240)
        # 5-arg form: ..., focusId || '', <mode-expr>)
        assert "bridgeCall('agent_step'" in block
        assert "_composerMode" in block, (
            "agent_step must send the live composer mode as the trailing arg")
        # The mode source is the LIVE mode, not a hard-coded literal: the
        # expression references the window mirror (proves it is not `'plan'`
        # baked in as the sole source). Use the whitespace-flat view so the
        # `mode ||` that wraps across source lines is matched.
        src_flat = _JSX_FLAT.split("const _composerMode", 1)[1][:160]
        assert "window.__archhub_composer_mode" in src_flat
        assert "= mode ||" in src_flat, (
            "the live React `mode` must be the primary source (not a literal)")

    def test_agent_step_call_is_not_three_args_only(self):
        # Guard the exact regression: the call must NOT be the old 3-arg form
        # (t, graph, focusId) with nothing after focusId. The trailing arg
        # after `focusId || ''` must be the mode expression.
        block = _jsx_window("bridgeCall('agent_step'", size=160)
        assert "focusId || '', _composerMode" in block or \
               "focusId||'',_composerMode" in re.sub(r"\s+", "", block), (
            "agent_step must carry a 4th positional mode arg after focusId")

    def test_onagentstep_honors_backend_gate(self):
        # onAgentStep must READ the backend gate markers (a.gated /
        # a.approval) — not blindly rebuild an executable action.
        block = _jsx_window("if (!step || !Array.isArray(step.actions))",
                            size=1400)
        assert "a.gated" in block, "onAgentStep must read a.gated"
        assert "a.approval" in block, "onAgentStep must read a.approval"
        assert "approval_required" in block, (
            "onAgentStep must recognise the typed approval_required payload")

    def test_onagentstep_routes_gated_action_to_approval_surface(self):
        # A gated action is routed to the SAME approval surface the client gate
        # uses (lm-approval-request → ApprovalQueue) — and the gate-branch
        # short-circuits (return) so it is NOT also re-dispatched through
        # lm-composer-action (no double-gate / double-run on the agent path).
        block = _jsx_window("const _gated = !!(a && (a.gated", size=1750)
        assert "lm-approval-request" in block, (
            "gated agent actions must route to lm-approval-request")
        # The detail shape matches what ApprovalQueue.onReq reads.
        assert "action: held" in block and "cmd: held.command" in block
        # Short-circuits after surfacing the approval (no fall-through to the
        # executable-action builder + lm-composer-action dispatch).
        assert "return;" in block

    def test_no_double_dispatch_on_gated_agent_path(self):
        # Belt-and-braces: inside the gate branch there is NO
        # lm-composer-action dispatch (that would double-run the held write).
        # Slice from the gate test to the `let action = null;` that begins the
        # ungated path.
        head = _JSX_CODE.split("const _gated = !!(a && (a.gated", 1)[1]
        gate_branch = head.split("let action = null;", 1)[0]
        assert "lm-composer-action" not in gate_branch, (
            "the gated agent path must NOT dispatch lm-composer-action — "
            "the approval grant re-dispatches it exactly once")

    def test_dead_composer_write_gate_bridgecall_removed(self):
        # The dead pretense — bridgeCall('composer_write_gate', …) to a slot
        # that never existed in bridge.py — must be GONE from source AND the
        # compiled bundle. (MAKE-IT-REAL: no dead calls.)
        assert "composer_write_gate" not in _JSX_SRC, (
            "the dead composer_write_gate bridgeCall must be removed from source")
        assert "composer_write_gate" not in _COMPILED, (
            "the dead composer_write_gate call must be gone from the bundle")
        # And bridge.py never defined such a slot (one gate of record, not a
        # second pretending).
        assert "composer_write_gate" not in _BRIDGE_SRC

    def test_client_gate_still_surfaces_approval_for_direct_writes(self):
        # The REAL client-side gate (direct, non-agent composer writes) is
        # untouched: still suppresses + dispatches lm-approval-request.
        block = _jsx_window("const _gated = (mode === 'plan' || mode === 'auto')",
                            size=1100)
        assert "lm-approval-request" in block
        assert "return;" in block  # gate closed — nothing mutates until approved


# ── compiled bundle parity (the app loads the .compiled.js) ──────────
class TestCompiledBundleParity:
    def test_new_wiring_in_compiled_bundle(self):
        # Babel preserves single quotes + strips inter-token spaces; match
        # the minified form (flat view tolerates either).
        assert "wire('wire_state_changed',onWireState)" in _COMPILED_FLAT
        assert "wire('notice',onNotice)" in _COMPILED_FLAT
        assert "LM_WIRE_STATE" in _COMPILED
        assert "_forcedConvId" in _COMPILED

    def test_plan_mode_gate_wiring_in_compiled_bundle(self):
        # The end-to-end gate wiring (jury LENS 3) is present in the bundle the
        # app actually loads — not just the source.
        assert "bridgeCall('agent_step',t,JSON.stringify(LM_GRAPH)," \
               "focusId||'',_composerMode)" in _COMPILED_FLAT
        assert "_composerMode=mode||" in _COMPILED_FLAT
        assert "a.gated||" in _COMPILED_FLAT
        assert "composer_write_gate" not in _COMPILED
