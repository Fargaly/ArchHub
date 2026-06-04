"""Tests for the ROMA "method-that-finishes-everything" encode.

Covers the three additive modules:
  - requirement_tree.py  (store-backed tree ledger over brain_meta)
  - court_harness.py      (the 3-lens external jury — deterministic, real check)
  - roma.py               (atomize / claim / judge / loop-until-dry + MCP tools)

Same philosophy as test_diligence.py / test_reflexion.py: pure + deterministic,
in-memory store only (the live brain.db is never touched), no network. The court
artifact gates run the REAL deterministic probes (py_compile / file_exists) so a
faithful leaf passes and a hallucinated one fails — mirroring
validate_skill_against_trace.
"""
from __future__ import annotations

import os

import pytest

from personal_brain import court_harness as ch
from personal_brain import requirement_tree as rt
from personal_brain import roma
from personal_brain.storage import BrainStore


# Absolute path to a file that definitely exists + compiles: this module's own
# package __init__. Used as a real artifact for the artifact lens.
_PKG_INIT = os.path.join(
    os.path.dirname(rt.__file__), "__init__.py"
)


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ─────────────────────────── requirement_tree ──────────────────────────


def test_create_root_persists_under_brain_meta_key(store):
    tree = rt.create_root(store, title="vision", owner_user="founder")
    # persisted under the single additive key — no new table, no fragments.
    raw = store.get_meta(rt.TREE_META_KEY)
    assert raw and tree.tree_id in raw
    assert store.count_skills() == 0  # nothing leaked into skills
    # root is a leaf until decomposed
    assert tree.nodes[tree.root_id].is_leaf


def test_create_root_is_idempotent(store):
    a = rt.create_root(store, title="same", owner_user="founder")
    b = rt.create_root(store, title="same", owner_user="founder")
    assert a.tree_id == b.tree_id
    assert len(rt.list_trees(store)) == 1


def test_decompose_splits_and_parent_becomes_internal(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id, children=[
        {"title": "a", "gate_kind": "manual"},
        {"title": "b", "gate_kind": "manual"},
    ])
    t = rt.get_tree(store, tree_id=tree.tree_id)
    root = t.nodes[t.root_id]
    assert not root.is_leaf          # has children now
    assert len(root.children) == 2
    assert len(t.leaves()) == 2      # the two children are the leaves


def test_decompose_is_idempotent_on_titles(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "a"}])
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "a"}])  # same title again
    t = rt.get_tree(store, tree_id=tree.tree_id)
    assert len(t.nodes[t.root_id].children) == 1  # no duplicate sibling


def test_decompose_refuses_green_node(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "leaf", "gate_kind": "manual"}])
    t = rt.get_tree(store, tree_id=tree.tree_id)
    leaf = t.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="ex")
    rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                   verdict="green", judged_by="court")
    with pytest.raises(ValueError):
        rt.decompose(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                     children=[{"title": "x"}])


def test_claim_requires_agent_and_refuses_nonleaf(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "leaf"}])
    with pytest.raises(ValueError):
        rt.claim_leaf(store, tree_id=tree.tree_id, node_id=tree.root_id, agent_id="ex")
    with pytest.raises(ValueError):
        rt.claim_leaf(store, tree_id=tree.tree_id,
                      node_id=tree.leaves()[0].node_id if False else
                      rt.get_tree(store, tree_id=tree.tree_id).leaves()[0].node_id,
                      agent_id="")


def test_set_verdict_self_certification_refused(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "leaf"}])
    leaf = rt.get_tree(store, tree_id=tree.tree_id).leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="exec-A")
    # the executor cannot green its own leaf
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                       verdict="green", judged_by="exec-A")
    # an independent judge can
    node = rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          verdict="green", judged_by="court-X")
    assert node.state == rt.NodeState.GREEN
    # founder root authority can override (logged)
    rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                   verdict="green", judged_by="exec-A", is_root_authority=True)


def test_green_propagates_and_sweep_dry(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id, children=[
        {"title": "a"}, {"title": "b"},
    ])
    t = rt.get_tree(store, tree_id=tree.tree_id)
    for leaf in t.leaves():
        rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="ex")
        rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                       verdict="green", judged_by="court")
    status = rt.sweep(store, tree_id=tree.tree_id)
    assert status["dry"] is True
    assert status["root_green"] is True       # derived green bubbled to root
    assert status["green_leaves"] == status["total_leaves"] == 2


def test_dangling_child_ref_blocks_false_green_sweep(store):
    """Regression (false-green bug): a corrupted / partially-written persisted
    doc whose root declares a child id ABSENT from `nodes` must NEVER report a
    full green sweep. Fail-closed: the dangling ref blocks the parent from
    greening AND keeps sweep.dry False."""
    import json
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "a"}])
    root_id = tree.root_id
    # Inject a DANGLING child id into the root via the public set_meta path
    # (simulates a corrupted / partially-written brain_meta doc) BEFORE greening.
    doc = json.loads(store.get_meta(rt.TREE_META_KEY))
    doc[tree.tree_id]["nodes"][root_id]["children"].append("ghost-missing-id")
    store.set_meta(rt.TREE_META_KEY, json.dumps(doc))
    # Green the one REAL leaf — under the bug the root would falsely green here.
    leaf = rt.get_tree(store, tree_id=tree.tree_id).leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="ex")
    rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                   verdict="green", judged_by="court")
    status = rt.sweep(store, tree_id=tree.tree_id)
    t = rt.get_tree(store, tree_id=tree.tree_id)
    assert t.nodes[root_id].state != rt.NodeState.GREEN   # root did NOT go green
    assert status["dry"] is False                          # not a false "done"
    assert status["root_green"] is False
    assert status["dangling_refs"]                         # surfaced, not silent


def test_red_bumps_attempts_and_reopens(store):
    tree = rt.create_root(store, title="v", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "a"}])
    leaf = rt.get_tree(store, tree_id=tree.tree_id).leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="ex")
    n = rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                       verdict="red", judged_by="court")
    assert n.state == rt.NodeState.RED and n.attempts == 1
    assert n.claimed_by is None  # re-enters the frontier
    assert any(x.node_id == leaf.node_id
               for x in rt.open_leaves(store, tree_id=tree.tree_id))


# ─────────────────────────── court_harness ─────────────────────────────


def test_artifact_lens_py_compile_passes_on_real_module():
    v = ch.lens_artifact(
        gate_kind="py_compile",
        gate_spec={"path": _PKG_INIT},
        context={},
    )
    assert v.applied and not v.refuted and v.evidence_ref


def test_artifact_lens_refutes_missing_file():
    v = ch.lens_artifact(
        gate_kind="file_exists",
        gate_spec={"path": "/no/such/file/anywhere.xyz"},
        context={},
    )
    assert v.applied and v.refuted


def test_artifact_lens_inapplicable_for_manual():
    v = ch.lens_artifact(gate_kind="manual", gate_spec={}, context={})
    assert v.applied is False and v.refuted is False


def test_diligence_lens_refutes_short_claim():
    v = ch.lens_diligence(context={"evidence": {
        "last_message": "shipped, all done!", "session_signals": {}}})
    assert v.applied and v.refuted  # claim-without-proof


def test_diligence_lens_passes_proven_claim():
    v = ch.lens_diligence(context={"evidence": {
        "last_message": "done; ran pytest",
        "session_signals": {"ran_tests": True}}})
    assert v.applied and not v.refuted


def test_independence_lens_refuses_self_cert():
    art = ch.LensVerdict(lens="artifact", refuted=False, applied=True,
                         evidence_ref="x")
    v = ch.lens_independence(claimed_by="exec-A", judged_by="exec-A",
                             artifact_lens=art)
    assert v.refuted


def test_convene_court_green_on_real_artifact():
    verdict = ch.convene_court(
        node_id="n1", gate_kind="py_compile",
        gate_spec={"path": _PKG_INIT},
        claimed_by="exec-A", judged_by="court-X",
        context={"evidence": {"last_message": "done; wrote files",
                              "session_signals": {"wrote_files": True}}},
    )
    assert verdict.green is True and verdict.verdict == "green"


def test_convene_court_red_when_artifact_refuted():
    verdict = ch.convene_court(
        node_id="n1", gate_kind="file_exists",
        gate_spec={"path": "/nope.nope"},
        claimed_by="exec-A", judged_by="court-X",
    )
    assert verdict.green is False and verdict.verdict == "red"


def test_convene_court_needs_root_for_manual_leaf():
    verdict = ch.convene_court(
        node_id="n1", gate_kind="manual", gate_spec={},
        claimed_by="exec-A", judged_by="court-X",
    )
    assert verdict.verdict == "needs_root"  # unverifiable → founder


def test_convene_court_require_diligence_blocks_without_evidence():
    verdict = ch.convene_court(
        node_id="n1", gate_kind="py_compile",
        gate_spec={"path": _PKG_INIT},
        claimed_by="exec-A", judged_by="court-X",
        require_diligence=True,  # no evidence supplied
    )
    assert verdict.verdict == "red"


# ─────────────────────────── roma orchestration ────────────────────────


def test_atomize_builds_nested_tree(store):
    tree = roma.atomize(store, vision="ship it", owner_user="founder",
        decomposition=[
            {"title": "parent", "children": [
                {"title": "child1", "gate_kind": "manual"},
                {"title": "child2", "gate_kind": "manual"},
            ]},
            {"title": "loner", "gate_kind": "manual"},
        ])
    # parent is internal; child1/child2/loner are leaves
    leaf_titles = sorted(n.title for n in tree.leaves())
    assert leaf_titles == ["child1", "child2", "loner"]


def test_judge_leaf_records_verdict(store):
    tree = roma.atomize(store, vision="v", owner_user="founder",
        decomposition=[{"title": "compiles", "gate_kind": "py_compile",
                        "gate_spec": {"path": _PKG_INIT}}])
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="ex")
    out = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          judged_by="court-X")
    assert out["court"]["verdict"] == "green"
    assert out["node"]["state"] == "green"


def test_run_to_dry_reaches_full_green_sweep(store):
    tree = roma.atomize(store, vision="two real leaves", owner_user="founder",
        decomposition=[
            {"title": "a", "gate_kind": "py_compile", "gate_spec": {"path": _PKG_INIT}},
            {"title": "b", "gate_kind": "py_compile", "gate_spec": {"path": _PKG_INIT}},
        ])

    def executor(leaf, ctx):
        return {"last_message": f"did {leaf.title}; wrote files",
                "session_signals": {"wrote_files": True}}

    final = roma.run_to_dry(
        store, tree_id=tree.tree_id, executor=executor, judged_by="court-Z",
        context={"executor_id": "exec-loop"}, max_rounds=5,
    )
    assert final["dry"] is True and final["root_green"] is True
    assert final["green_leaves"] == 2
    assert final["rounds_run"] >= 1


def test_run_to_dry_re_decomposes_red_leaf(store):
    # A leaf that always refutes (missing file), with an auto_decompose that
    # splits it into a real (compilable) child → the tree converges.
    tree = roma.atomize(store, vision="recover", owner_user="founder",
        decomposition=[{"title": "bad", "gate_kind": "file_exists",
                        "gate_spec": {"path": "/missing.zzz"}}])

    def executor(leaf, ctx):
        return {"last_message": "attempted; wrote files",
                "session_signals": {"wrote_files": True}}

    splits = {"count": 0}

    def auto_decompose(node):
        # Only split the original bad leaf, once, into a compilable child.
        if node.title == "bad" and splits["count"] == 0:
            splits["count"] += 1
            return [{"title": "fixed-child", "gate_kind": "py_compile",
                     "gate_spec": {"path": _PKG_INIT}}]
        return []

    final = roma.run_to_dry(
        store, tree_id=tree.tree_id, executor=executor, judged_by="court-Z",
        context={"executor_id": "exec-loop"}, max_rounds=6,
        auto_decompose=auto_decompose,
    )
    assert splits["count"] == 1            # the red leaf was split, not retried forever
    assert final["dry"] is True            # and the tree converged to green
    assert final["root_green"] is True


# ─────────────────────────── MCP tool registration ─────────────────────


def test_roma_tools_register_additively(store):
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    # InHouseMCP.list_tools() is SYNCHRONOUS and returns a list of descriptor
    # dicts ({"name", "description", "inputSchema"}); read the "name" key.
    names = {t["name"] for t in mcp.list_tools()}
    expected = {
        "brain.roma_atomize", "brain.roma_decompose", "brain.roma_claim",
        "brain.roma_judge", "brain.roma_sweep", "brain.roma_frontier",
        "brain.roma_list",
    }
    assert expected <= names
    # existing handlers untouched
    assert {"brain.health", "brain.enforce_diligence", "brain.skill_mint"} <= names
