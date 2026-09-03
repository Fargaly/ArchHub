"""Re-cook-on-param-change (court verdict 2026-06-01 + cook.recook_trigger).

Before this wiring, dragging a slider in studio-lm.jsx only repainted
(bumpGraph) + debounce-saved — the node's executor was NEVER re-run and
downstream was NEVER invalidated. This suite pins the fix end to end:

  ENGINE  (workflows/runner.py)
    - reachable_sinks(node_id): the sinks reachable DOWNSTREAM of a node
    - recook_from(node_id): mark_dirty + pull reachable sinks → re-cooks
      the edited node AND its downstream chain, leaving unrelated branches
      cached (no full-graph thrash). Reuses pull/mark_dirty/run_all only.

  BRIDGE  (app/bridge.py)
    - recook_node slot returns {request_id,status:'started'} INSTANTLY and
      cooks on a worker thread (off the Qt main thread — never blocks UI),
      serialised under _cook_lock with the other cook slots.

  UI      (app/web_ui/studio-lm.jsx)  — source guards
    - NodeRail.onParamChange + ConnectorRail.setParam schedule a DEBOUNCED
      re-cook (reCookParamTick) on mid-drag ticks and FLUSH (flushReCook) on
      the commit/release edge — never a per-tick cook (no chain-thrash).
    - The re-cook is the off-thread `recook_node` bridge slot.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes triggers registration; do it once.
from workflows import nodes as _nodes_pkg  # noqa: F401,E402
from workflows.runner import WorkflowRunner  # noqa: E402
from workflows.registry import (  # noqa: E402
    register, NodeSpec, get as _get_spec,
)
from workflows.graph import Port, PortType  # noqa: E402


# ── Test-only nodes (mirror test_workflow_runner.py) ────────────────
def _adder_exec(config, inputs, ctx):
    a = float(inputs.get("a", 0) or 0)
    b = float(inputs.get("b", 0) or 0)
    return {"status": "ok", "sum": a + b}


def _passthru_exec(config, inputs, ctx):
    # Emits config.value PLUS whatever arrived on `in` (so it re-cooks
    # when an upstream value changes, like a real transform node).
    base = config.get("value", 0)
    upstream = inputs.get("in")
    out = base if upstream is None else (float(base) + float(upstream))
    return {"status": "ok", "value": out, "out": out}


def _ensure_nodes():
    if _get_spec("_rc.const") is None:
        register(NodeSpec(
            type="_rc.const", category="_rc",
            display_name="RC Const", description="emits config.value",
            inputs=[],
            outputs=[Port(name="value", type=PortType.NUMBER)],
            config_schema={"value": {"type": "number"}}, icon="·",
        ), _passthru_exec)
    if _get_spec("_rc.xform") is None:
        register(NodeSpec(
            type="_rc.xform", category="_rc",
            display_name="RC Xform", description="value = config + in",
            inputs=[Port(name="in", type=PortType.NUMBER)],
            outputs=[Port(name="value", type=PortType.NUMBER),
                      Port(name="out", type=PortType.NUMBER)],
            config_schema={"value": {"type": "number"}}, icon="~",
        ), _passthru_exec)
    if _get_spec("_rc.adder") is None:
        register(NodeSpec(
            type="_rc.adder", category="_rc",
            display_name="RC Adder", description="a + b",
            inputs=[Port(name="a", type=PortType.NUMBER),
                     Port(name="b", type=PortType.NUMBER)],
            outputs=[Port(name="sum", type=PortType.NUMBER)],
            config_schema={}, icon="+",
        ), _adder_exec)


@pytest.fixture(autouse=True)
def _setup():
    _ensure_nodes()


def _node(nid, ntype, value=None, ins=None, outs=None):
    n = {"id": nid, "type": ntype, "config": {},
         "ins": ins or [], "outs": outs or []}
    if value is not None:
        n["config"]["value"] = value
    return n


def _const(nid, value):
    return _node(nid, "_rc.const", value=value,
                 outs=[{"id": "value", "t": "number"}])


def _xform(nid, value=0):
    return _node(nid, "_rc.xform", value=value,
                 ins=[{"id": "in", "t": "number"}],
                 outs=[{"id": "value", "t": "number"},
                        {"id": "out", "t": "number"}])


def _wire(fn, fp, tn, tp):
    return {"from": [fn, fp], "to": [tn, tp]}


def _g(nodes, wires):
    return {"nodes": nodes, "wires": wires}


# A → B → C chain plus an unrelated D (own sink).
def _chain_graph():
    return _g(
        [_const("A", 1), _xform("B", 10), _xform("C", 100),
         _const("D", 999)],
        [_wire("A", "value", "B", "in"),
         _wire("B", "out", "C", "in")],
    )


# ── reachable_sinks ─────────────────────────────────────────────────
class TestReachableSinks:
    def test_sinks_downstream_of_source(self):
        r = WorkflowRunner(_chain_graph())
        # From A the only reachable terminal is C (A→B→C). D is unrelated.
        assert r.reachable_sinks("A") == ["C"]

    def test_sinks_from_middle_node(self):
        r = WorkflowRunner(_chain_graph())
        assert r.reachable_sinks("B") == ["C"]

    def test_sink_node_is_its_own_terminal(self):
        r = WorkflowRunner(_chain_graph())
        assert r.reachable_sinks("C") == ["C"]

    def test_unrelated_branch_not_included(self):
        r = WorkflowRunner(_chain_graph())
        assert "D" not in r.reachable_sinks("A")

    def test_dead_end_node_returns_itself(self):
        # A lone node with no edges is its own sink.
        r = WorkflowRunner(_g([_const("solo", 5)], []))
        assert r.reachable_sinks("solo") == ["solo"]

    def test_unknown_node_returns_empty(self):
        r = WorkflowRunner(_chain_graph())
        assert r.reachable_sinks("nope") == []


# ── recook_from: edited node + downstream re-cook ───────────────────
class TestRecookFrom:
    def _spy(self, type_name):
        """Swap a registered executor for a call-counting spy. Returns
        (counter, restore_fn)."""
        from workflows import registry as _reg
        spec, original = _get_spec(type_name)
        called = {"n": 0}

        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)
        _reg._REGISTRY[type_name] = (_reg._REGISTRY[type_name][0], spy)

        def restore():
            _reg._REGISTRY[type_name] = (
                _reg._REGISTRY[type_name][0], original)
        return called, restore

    def test_recook_runs_edited_node_and_downstream(self):
        """Edit A's param → A, B, and C must all re-cook (the chain
        downstream of the edit)."""
        r = WorkflowRunner(_chain_graph())
        # Prime the whole chain so everything is cached.
        assert r.pull("C")["status"] == "ok"

        a_cnt, a_restore = self._spy("_rc.const")
        x_cnt, x_restore = self._spy("_rc.xform")
        try:
            # Simulate the param edit: mutate A's config like onParamChange.
            r.nodes_by_id["A"]["config"]["value"] = 7
            result = r.recook_from("A")
        finally:
            a_restore(); x_restore()

        assert result["status"] == "ok"
        assert result["recooked_from"] == "A"
        assert result["sinks"] == ["C"]
        # A re-cooked once (const), B + C re-cooked (xform spy → 2).
        assert a_cnt["n"] == 1, "edited node A must re-cook"
        assert x_cnt["n"] == 2, "downstream B + C must both re-cook"
        # New value propagated all the way down: A=7 → B=10+7=17 → C=100+17=117
        assert result["results"]["C"]["value"] == 117

    def test_recook_leaves_unrelated_branch_cached(self):
        """Editing A must NOT re-cook the unrelated D branch — no
        full-graph thrash."""
        r = WorkflowRunner(_chain_graph())
        r.pull("C")
        r.pull("D")

        d_cnt, d_restore = self._spy("_rc.const")
        try:
            r.nodes_by_id["B"]["config"]["value"] = 50
            result = r.recook_from("B")
        finally:
            d_restore()
        # recook_from("B") sinks = [C]; D is untouched → const spy counts
        # only A's re-cook IF A were dirty. A is upstream of B, unchanged,
        # so it stays cached too. D never appears in sinks.
        assert "D" not in result["sinks"]
        # The const spy (shared by A + D) must not have fired for D: A is
        # cached (unchanged upstream of B) and D is unrelated.
        assert d_cnt["n"] == 0, "unrelated/cached const nodes must not re-cook"

    def test_recook_from_sink_recooks_just_that_node(self):
        r = WorkflowRunner(_chain_graph())
        r.pull("C")
        x_cnt, x_restore = self._spy("_rc.xform")
        try:
            r.nodes_by_id["C"]["config"]["value"] = 200
            result = r.recook_from("C")
        finally:
            x_restore()
        assert result["sinks"] == ["C"]
        # Only C re-cooks (B is unchanged upstream → cached).
        assert x_cnt["n"] == 1

    def test_recook_returns_run_all_shape(self):
        r = WorkflowRunner(_chain_graph())
        result = r.recook_from("A")
        # Same keys the bridge/JS expect from run_all + the recook marker.
        for k in ("status", "sinks", "results", "edges_state"):
            assert k in result
        assert result["recooked_from"] == "A"


# ── Bridge slot: off-thread + non-blocking + serialised ─────────────
class TestRecookBridgeSlot:
    def test_recook_node_is_nonblocking_and_off_thread(self):
        """recook_node must return {request_id,status:'started'} instantly
        and cook on a WORKER THREAD — never block the caller (Qt main
        thread). We stub a slow recook_from and assert the slot returns
        fast while the cook runs in the background."""
        import json
        import bridge as _bridge
        from workflows import runner as _runner_mod

        ran = {"thread": None, "done": False}
        real_recook = _runner_mod.WorkflowRunner.recook_from

        def slow_recook(self, node_id):
            ran["thread"] = __import__("threading").current_thread().name
            time.sleep(1.5)
            ran["done"] = True
            return {"status": "ok", "recooked_from": node_id,
                    "sinks": [node_id], "results": {}, "edges_state": []}

        # Minimal stand-in `self`: borrow the real recook_node + _cook_lock,
        # stub out the signals + collaborators it touches.
        class _Sig:
            def emit(self, *a):
                pass

        class _Self:
            pass
        s = _Self()
        s.router = None
        s.tools = None
        s.manager = None
        s.workflow_started = _Sig()
        s.workflow_done = _Sig()
        s.wire_state_changed = _Sig()
        s._cook_lock = _bridge.ArchHubBridge._cook_lock.__get__(s)
        recook_node = _bridge.ArchHubBridge.recook_node.__get__(s)

        graph = json.dumps(_chain_graph())
        _runner_mod.WorkflowRunner.recook_from = slow_recook
        try:
            t0 = time.time()
            raw = recook_node("sess", "A", graph)
            elapsed = time.time() - t0
            assert elapsed < 0.5, f"slot blocked {elapsed:.2f}s — must be async"
            payload = json.loads(raw)
            assert payload["status"] == "started"
            assert "request_id" in payload
            assert payload["request_id"].startswith("rc-")
            # The cook runs on a background (non-main) thread; wait for it.
            deadline = time.time() + 5
            while time.time() < deadline and not ran["done"]:
                time.sleep(0.05)
            assert ran["done"], "background cook never ran"
            assert ran["thread"] != "MainThread", \
                "cook must run OFF the Qt main thread"
        finally:
            _runner_mod.WorkflowRunner.recook_from = real_recook

    def test_recook_node_bad_graph_json_is_handled(self):
        import json
        import bridge as _bridge

        class _Sig:
            def emit(self, *a):
                pass

        class _Self:
            pass
        s = _Self()
        s.router = s.tools = s.manager = None
        s.workflow_started = _Sig()
        s.workflow_done = _Sig()
        s.wire_state_changed = _Sig()
        s._cook_lock = _bridge.ArchHubBridge._cook_lock.__get__(s)
        recook_node = _bridge.ArchHubBridge.recook_node.__get__(s)
        out = json.loads(recook_node("sess", "A", "{not json"))
        assert "error" in out


# ── Source guards: bridge + JSX wiring is actually present ──────────
_BRIDGE_SRC = (APP_ROOT / "bridge.py").read_text(encoding="utf-8")
_JSX_SRC = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")


class TestBridgeSourceGuards:
    def test_recook_slot_holds_cook_lock(self):
        # The recook slot must serialise with the other cooks.
        assert "def recook_node" in _BRIDGE_SRC
        # Three cook slots now hold the lock: run_workflow, run_node, recook_node
        assert _BRIDGE_SRC.count("with self._cook_lock():") >= 3

    def test_recook_slot_calls_recook_from_on_worker_thread(self):
        # The slot body spawns a worker thread and calls recook_from in it.
        assert "runner.recook_from(node_id)" in _BRIDGE_SRC
        # Off-thread: a daemon Thread is started (same idiom as run_node).
        # Slice from the slot def to the NEXT top-level @pyqtSlot / method
        # def (4-space indent), so the nested `def _worker()` stays inside.
        after = _BRIDGE_SRC.split("def recook_node", 1)[1]
        m = re.search(r"\n    (?:@pyqtSlot|def )", after)
        block = after[: m.start()] if m else after
        assert "threading.Thread(target=_worker" in block
        assert "runner.recook_from(node_id)" in block
        assert '"status": "started"' in block


def _jsx_window(anchor, size=700):
    """Grab a fixed-size window of JSX source starting at `anchor`.

    The handler bodies (onParamChange / setParam / ParamSaveFlush) are
    well under `size` chars, so this captures the whole body without the
    brittleness of splitting on `};` (which matches inline object
    literals like `{ [k]: v };`)."""
    i = _JSX_SRC.find(anchor)
    assert i != -1, f"anchor not found in JSX: {anchor!r}"
    return _JSX_SRC[i:i + size]


class TestJsxSourceGuards:
    def test_recook_debounce_helpers_exist(self):
        assert "const reCookParamTick" in _JSX_SRC
        assert "const flushReCook" in _JSX_SRC
        # The re-cook fires the off-thread bridge slot.
        assert "bridgeCall('recook_node'" in _JSX_SRC

    def test_onparamchange_schedules_debounced_recook(self):
        # NodeRail.onParamChange: mid-drag tick → reCookParamTick (debounced);
        # commit/release → flushReCook (flush now).
        block = _jsx_window("const onParamChange")
        assert "reCookParamTick(node.id)" in block
        assert "flushReCook(node.id)" in block
        # The debounced path is the NON-commit branch (no per-tick cook).
        assert "if (commit)" in block

    def test_connector_setparam_schedules_debounced_recook(self):
        block = _jsx_window("const setParam")
        assert "reCookParamTick(node.id)" in block
        assert "flushReCook(node.id)" in block

    def test_recook_is_trailing_debounce_not_per_tick(self):
        # The mid-drag path must go through the idle-reset debounce
        # (reCookParamTick → setTimeout), NOT call recook_node directly on
        # every tick. The only direct bridgeCall('recook_node') is inside
        # _fireReCook, which is invoked by the debounce/flush — never from
        # onParamChange/setParam directly.
        for fn in ("const onParamChange", "const setParam"):
            block = _jsx_window(fn)
            assert "recook_node" not in block, \
                f"{fn} must debounce, not call recook_node per-tick"
        # The debounce uses a trailing idle-reset setTimeout.
        rc_block = _jsx_window("const reCookParamTick", size=400)
        assert "setTimeout" in rc_block
        assert "clearTimeout" in rc_block  # idle-reset

    def test_flush_on_deselect_wired(self):
        # ParamSaveFlush unmount flushes the re-cook (node deselect / rail close).
        psf = _jsx_window("const ParamSaveFlush", size=500)
        assert "flushReCook(nodeId)" in psf


# ── run_node arg-order regression guards (re-cook follow-up fix) ─────
# Latent bug found alongside the re-cook work: the TRIGGER + AGENT call sites
# called `bridgeCall('run_node', node_id)` (single arg). run_node's slot
# signature is (session_id, node_id, graph_json) — so node_id landed in
# session_id and node_id defaulted to "". The slot then looked up a bogus
# session on disk and cooked NOTHING (auto-triggers / agent cooks were silent
# no-ops). The correct LIVE form is (currentSid(), node_id, JSON of LM_GRAPH),
# the same shape the NodeRail "Rerun" button / NodeMenu onRun / re-cook path use.
class TestRunNodeArgOrderGuards:
    def test_no_single_arg_run_node_calls(self):
        """EVERY bridgeCall('run_node', …) must pass currentSid() as the
        FIRST arg — never a bare node id. This pins the whole class shut:
        a single-arg run_node call anywhere reintroduces the bug."""
        # Every run_node call must have currentSid() as its FIRST argument.
        # We match the slot name + the next chars and require the call to
        # begin `bridgeCall('run_node', currentSid()`. A single-arg call
        # (`bridgeCall('run_node', someNodeId)`) fails this — the first arg
        # would be a node id, not the session id.
        # Strip `//` line comments first so the doc comment that *quotes* the
        # old buggy single-arg form isn't mistaken for a live call site.
        code_only = re.sub(r"//[^\n]*", "", _JSX_SRC)
        calls = re.findall(r"bridgeCall\(\s*'run_node'\s*,\s*([^;]*?\))",
                           code_only)
        assert calls, "expected run_node call sites in studio-lm.jsx"
        for call_args in calls:
            assert call_args.lstrip().startswith("currentSid()"), (
                "run_node first arg must be the session id (currentSid()), "
                f"not {call_args.strip()[:40]!r} — single-arg form "
                "reintroduces the node_id-into-session_id bug"
            )

    def test_agent_run_node_uses_live_three_arg_form(self):
        # The composer 'run_node' action (agent tool + onAgentStep replay)
        # cooks a single node via the 3-arg live-graph form.
        block = _jsx_window("case 'run_node':", size=700)
        assert "bridgeCall('run_node', currentSid(), action.node_id, JSON.stringify(LM_GRAPH))" in block

    def test_trigger_handler_recooks_downstream_via_recook_node(self):
        """A fired trigger must re-cook the node + its downstream subgraph
        through the engine's purpose-built propagation (recook_node →
        recook_from = mark_dirty + pull sinks), NOT a hand-rolled per-node
        run_node BFS (which returns cached values when nothing is dirty)."""
        # The onTrigger handler exists and routes the fired node through the
        # off-thread recook slot with the real session id + live graph.
        assert "const onTrigger = (sid, nodeId, payloadJson)" in _JSX_SRC
        assert ("bridgeCall('recook_node', sid || currentSid(), nodeId, "
                "JSON.stringify(LM_GRAPH))") in _JSX_SRC
        # The old hand-rolled BFS that cooked each downstream node with a
        # single-arg run_node is gone.
        assert "bridgeCall('run_node', w.to[0])" not in _JSX_SRC


# ── ENGINE proof: a trigger fire re-cooks the downstream subgraph ───
# This is the behavioural counterpart to the source guard above: the trigger
# handler calls recook_node → runner.recook_from(triggerNode). We prove on the
# engine that recook_from(<trigger>) actually re-cooks the node AND propagates
# fresh values to every downstream node — i.e. the trigger is NOT a no-op.
class TestTriggerCooksDownstream:
    def _spy(self, type_name):
        from workflows import registry as _reg
        spec, original = _get_spec(type_name)
        called = {"n": 0}

        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)
        _reg._REGISTRY[type_name] = (_reg._REGISTRY[type_name][0], spy)

        def restore():
            _reg._REGISTRY[type_name] = (
                _reg._REGISTRY[type_name][0], original)
        return called, restore

    def test_trigger_node_fire_propagates_to_downstream(self):
        """Model a trigger node T → B → C. Firing T (recook_from('T'), the
        exact call the JSX onTrigger handler now makes) must re-cook B and C
        with fresh data — proving auto-triggers cook+propagate, not no-op."""
        # T is a const acting as the trigger source; B, C are downstream xforms.
        g = _g(
            [_const("T", 1), _xform("B", 10), _xform("C", 100)],
            [_wire("T", "value", "B", "in"),
             _wire("B", "out", "C", "in")],
        )
        r = WorkflowRunner(g)
        # Prime the chain (everything cached) — the worst case for a no-op bug:
        # a naive downstream pull would return these cached values.
        assert r.pull("C")["value"] == 111  # T=1 → B=10+1=11 → C=100+11=111

        x_cnt, x_restore = self._spy("_rc.xform")
        try:
            # Trigger fires: its emitted value changed (e.g. a new file landed).
            r.nodes_by_id["T"]["config"]["value"] = 5
            result = r.recook_from("T")
        finally:
            x_restore()

        assert result["status"] == "ok"
        assert result["recooked_from"] == "T"
        assert result["sinks"] == ["C"]
        # Downstream B + C BOTH re-cooked (not served from cache).
        assert x_cnt["n"] == 2, "trigger must re-cook the downstream chain"
        # Fresh value propagated end to end: T=5 → B=10+5=15 → C=100+15=115.
        assert result["results"]["C"]["value"] == 115
