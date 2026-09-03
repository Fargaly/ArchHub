"""Tests for the ROMA standing DISPATCHER (`dispatcher.run_standing` + status).

Same philosophy as test_roma.py / test_diligence.py: pure + deterministic,
in-memory store only (the live brain.db is never touched), no network, no real
subprocess, no sleeping. The dispatcher's seams (store, kill-switch path, fleet,
court runner, app-detector, clock) are all injected so each behaviour is proven
hermetically.

What is proven here (the spec's acceptance set):
  * one tick claims → builds FREE → court-verifies → set_verdict GREEN on a real
    buildable leaf (gate runs the REAL deterministic file_exists probe);
  * a kill-switch file present → the loop exits IMMEDIATELY (0 iterations, no
    claim, no build) — checked BEFORE any work;
  * idle_only with a simulated app-in-use → PAUSED, no claim/build;
  * a 'manual' leaf → needs_root (escalated to the founder), NEVER auto-built;
  * cost_usd stays 0.0 throughout (the FREE firewall), and a metered worker is
    REFUSED.

RED-before-GREEN: with dispatcher.py absent the module import fails and every
test errors; the file makes them pass.
"""
from __future__ import annotations

import os

import pytest

from personal_brain import dispatcher as dz
from personal_brain import requirement_tree as rt
from personal_brain.storage import BrainStore


# A real artifact for the artifact lens: this package's own __init__.py — it
# exists, so a file_exists-gated leaf can legitimately go GREEN. Mirrors
# test_roma's _PKG_INIT.
_PKG_INIT = os.path.join(os.path.dirname(rt.__file__), "__init__.py")


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def _tree_with_buildable_leaf(store, *, gate_kind="file_exists", gate_spec=None):
    """A 1-leaf tree whose single leaf is BUILDABLE (machine-gated). Returns
    (tree_id, leaf_node_id).

    GATE-BINDING (court un-rig): the default artifact must be FRESH — written
    AFTER the leaf exists — because the court now refutes a file whose mtime
    predates the leaf (a pre-existing file cannot prove new work). So the
    default gate targets a temp file written after decompose, no longer the
    package's own (ancient) __init__.py."""
    import tempfile
    import uuid
    tree = rt.create_root(store, title="standing-dispatcher vision", owner_user="founder")
    fresh = None
    if gate_spec is None:
        fresh = os.path.join(tempfile.gettempdir(),
                             f"dispatcher-leaf-{uuid.uuid4().hex}.txt")
        gate_spec = {"path": fresh}
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id, children=[
        {"title": "leaf A", "predicate": "the artifact exists",
         "gate_kind": gate_kind,
         "gate_spec": gate_spec},
    ])
    if fresh is not None:  # the "work": the artifact appears AFTER the leaf
        with open(fresh, "w", encoding="utf-8") as fh:
            fh.write("real artifact\n")
    leaf_id = rt._node_id(tree.tree_id, tree.root_id, "leaf A")
    return tree.tree_id, leaf_id


# ─────────────────────────── happy path: one green tick ─────────────────────


def test_one_tick_claims_builds_free_then_court_greens_the_leaf(store, tmp_path):
    """A single tick: claim → FREE build → court verify → set_verdict GREEN."""
    tid, leaf_id = _tree_with_buildable_leaf(store)

    # A FAKE free fleet: reports a free build + closing evidence, zero cost.
    calls = {"n": 0}

    def fake_fleet(leaf, ctx):
        calls["n"] += 1
        # The worker is the EXECUTOR; it must not be the court identity.
        assert ctx.get("executor_id") == dz.DISPATCHER_AGENT_ID
        return dz.WorkerOutcome(
            built=True, provider="codex",
            evidence={"last_message": "built leaf A; file written + verified"},
            cost_usd=0.0,
        )

    out = dz.run_standing(
        store=store,
        max_iterations=1,
        idle_only=False,                         # don't gate on the app here
        killswitch_path=str(tmp_path / "nope.stop"),  # absent → no kill
        fleet=fake_fleet,
        sleep_fn=lambda _s: None,                 # never really sleep
    )

    # The free worker ran exactly once.
    assert calls["n"] == 1
    # The leaf is GREEN, recorded by the COURT (not the worker's word).
    leaf = rt.get_tree(store, tree_id=tid).nodes[leaf_id]
    assert leaf.state == rt.NodeState.GREEN
    assert leaf.verdict == "green"
    # Anti-self-certify held: the judge differs from the claimer.
    assert leaf.claimed_by == dz.DISPATCHER_AGENT_ID
    assert leaf.judged_by == dz.DISPATCHER_COURT_ID
    assert leaf.judged_by != leaf.claimed_by
    # Status reflects one green, the FREE provider, and ZERO cost.
    assert out["leaves_greened"] == 1
    assert out["leaves_claimed"] == 1
    assert "codex" in out["providers_used"]
    assert out["cost_usd"] == 0.0
    assert out["running"] is False


def test_lane_stands_alone_when_no_fleet_is_present(store, tmp_path):
    """No free fleet wired (free_fleet absent / fleet=None) → the routing step
    no-ops, but the court still judges the (already-real) artifact GREEN. The
    lane builds + verifies on its own."""
    tid, leaf_id = _tree_with_buildable_leaf(store)

    out = dz.run_standing(
        store=store, max_iterations=1, idle_only=False,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=None,                               # <- no worker reachable
        sleep_fn=lambda _s: None,
    )

    leaf = rt.get_tree(store, tree_id=tid).nodes[leaf_id]
    assert leaf.state == rt.NodeState.GREEN       # court greened the real file
    assert out["leaves_greened"] == 1
    assert out["cost_usd"] == 0.0


# ─────────────────────────── kill-switch ────────────────────────────────────


def test_killswitch_present_exits_immediately_with_zero_iterations(store, tmp_path):
    """A kill-switch file present → the loop returns WITHOUT claiming or building
    even one leaf. Checked BEFORE any work."""
    tid, leaf_id = _tree_with_buildable_leaf(store)
    ks = tmp_path / "dispatcher.stop"
    ks.write_text("stop", encoding="utf-8")        # kill-switch armed

    fleet_calls = {"n": 0}

    def fleet(leaf, ctx):
        fleet_calls["n"] += 1
        return dz.WorkerOutcome(built=True, provider="codex")

    out = dz.run_standing(
        store=store, max_iterations=10, idle_only=False,
        killswitch_path=str(ks), fleet=fleet,
        sleep_fn=lambda _s: None,
    )

    # ZERO work: no claim, no build, no green.
    assert out["iterations"] == 0
    assert out["leaves_claimed"] == 0
    assert out["leaves_greened"] == 0
    assert fleet_calls["n"] == 0
    assert out["stopped_reason"] == "killswitch"
    # The leaf is untouched (still OPEN — never claimed).
    leaf = rt.get_tree(store, tree_id=tid).nodes[leaf_id]
    assert leaf.state == rt.NodeState.OPEN
    assert leaf.claimed_by is None


def test_killswitch_default_path_is_localappdata(monkeypatch, tmp_path):
    """The default kill-switch lives under %LOCALAPPDATA%/ArchHub/."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    p = dz.default_killswitch_path()
    assert p.name == "dispatcher.stop"
    assert "ArchHub" in str(p)
    assert str(tmp_path) in str(p)


# ─────────────────────────── idle gate (off-while-in-app) ───────────────────


def test_idle_only_pauses_while_app_in_use_no_build(store, tmp_path):
    """idle_only=True + a simulated app-in-use → the tick PAUSES: no claim, no
    build. The leaf is left untouched."""
    tid, leaf_id = _tree_with_buildable_leaf(store)
    fleet_calls = {"n": 0}

    def fleet(leaf, ctx):
        fleet_calls["n"] += 1
        return dz.WorkerOutcome(built=True, provider="codex")

    out = dz.run_standing(
        store=store,
        max_iterations=2,                          # bound the paused run
        idle_only=True,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=fleet,
        app_in_use_fn=lambda: True,                # <- founder's app is open
        sleep_fn=lambda _s: None,                  # don't actually wait
    )

    # PAUSED every tick: nothing claimed, nothing built, nothing greened.
    assert fleet_calls["n"] == 0
    assert out["leaves_claimed"] == 0
    assert out["leaves_greened"] == 0
    assert out["paused_reason"] == "app_in_use"
    leaf = rt.get_tree(store, tree_id=tid).nodes[leaf_id]
    assert leaf.state == rt.NodeState.OPEN          # untouched


def test_idle_only_false_builds_even_when_app_in_use(store, tmp_path):
    """idle_only=False ignores the app gate (an explicit opt-in to run anyway)."""
    tid, leaf_id = _tree_with_buildable_leaf(store)
    out = dz.run_standing(
        store=store, max_iterations=1, idle_only=False,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=None,
        app_in_use_fn=lambda: True,                # app open, but gate is off
        sleep_fn=lambda _s: None,
    )
    assert out["leaves_greened"] == 1


# ─────────────────────────── manual leaf → needs_root ───────────────────────


def test_manual_leaf_escalates_to_needs_root_never_auto_built(store, tmp_path):
    """A 'manual' (no machine gate) leaf is NEVER auto-built — it escalates to
    needs_root (the founder)."""
    tid, leaf_id = _tree_with_buildable_leaf(store, gate_kind="manual", gate_spec={})

    fleet_calls = {"n": 0}

    def fleet(leaf, ctx):
        fleet_calls["n"] += 1
        return dz.WorkerOutcome(built=True, provider="codex")

    out = dz.run_standing(
        store=store, max_iterations=3, idle_only=False,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=fleet,
        sleep_fn=lambda _s: None,
    )

    # The worker was NEVER called on a manual leaf.
    assert fleet_calls["n"] == 0
    assert out["leaves_greened"] == 0
    assert out["leaves_escalated"] >= 1
    # The leaf is NEEDS_ROOT (reserved for the founder), not green, not claimed.
    leaf = rt.get_tree(store, tree_id=tid).nodes[leaf_id]
    assert leaf.state == rt.NodeState.NEEDS_ROOT
    assert leaf.claimed_by is None


# ─────────────────────────── the money firewall (FREE) ──────────────────────


def test_cost_is_always_zero_in_status():
    """status() always reports cost_usd == 0.0 (the dispatcher never spends)."""
    assert dz.status()["cost_usd"] == 0.0


def test_metered_worker_outcome_is_refused():
    """The free guard REFUSES any non-zero-cost outcome — a paid call is a hard
    error, never a silently-recorded build."""
    with pytest.raises(dz.MeteredProviderError):
        dz._free_guard(dz.WorkerOutcome(built=True, provider="openai-api",
                                        cost_usd=0.01))
    # A free outcome passes through untouched.
    ok = dz._free_guard(dz.WorkerOutcome(built=True, provider="codex", cost_usd=0.0))
    assert ok.cost_usd == 0.0


def test_metered_worker_does_not_green_a_leaf_and_keeps_cost_zero(store, tmp_path):
    """End-to-end: a fleet that tries to charge is refused; the leaf is NOT
    greened by a metered build and the run's cost stays 0.0."""
    tid, leaf_id = _tree_with_buildable_leaf(store)

    def paid_fleet(leaf, ctx):
        return dz.WorkerOutcome(built=True, provider="openai-api", cost_usd=5.0)

    out = dz.run_standing(
        store=store, max_iterations=1, idle_only=False,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=paid_fleet,
        sleep_fn=lambda _s: None,
    )

    # The metered worker was refused → no FREE evidence reached the court, so the
    # diligence lens never saw a closing message from a paid provider. The run's
    # cost is still 0.0 (the dispatcher never records a paid build).
    assert out["cost_usd"] == 0.0
    assert "openai-api" not in out["providers_used"]


# ─────────────────────────── frontier dry → stop ────────────────────────────


def test_dry_frontier_stops(store, tmp_path):
    """No buildable leaves anywhere → the loop stops promptly (frontier_dry)."""
    # A tree whose only leaf is already GREEN → nothing claimable.
    tid, leaf_id = _tree_with_buildable_leaf(store)
    # Green it out of band (independent judge) so the frontier is dry.
    rt.claim_leaf(store, tree_id=tid, node_id=leaf_id, agent_id="someone")
    rt.set_verdict(store, tree_id=tid, node_id=leaf_id, verdict="green",
                   judged_by="another", evidence_ref=_PKG_INIT)

    out = dz.run_standing(
        store=store, max_iterations=5, idle_only=False,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=None, sleep_fn=lambda _s: None,
    )
    assert out["stopped_reason"] == "frontier_dry"
    assert out["leaves_claimed"] == 0


# ─────────────────────────── status() shape ─────────────────────────────────


def test_status_has_the_spec_keys(store, tmp_path):
    """status() returns the keys the spec names."""
    dz.run_standing(
        store=store, max_iterations=1, idle_only=False,
        killswitch_path=str(tmp_path / "nope.stop"),
        fleet=None, sleep_fn=lambda _s: None,
    )
    s = dz.status()
    for key in ("running", "paused_reason", "iterations", "leaves_greened",
                "providers_used", "cost_usd", "killswitch"):
        assert key in s, f"status() missing spec key '{key}'"
    assert s["cost_usd"] == 0.0
