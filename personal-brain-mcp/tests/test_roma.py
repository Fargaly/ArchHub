"""Tests for the ROMA "method-that-finishes-everything" encode.

Covers the three additive modules:
  - requirement_tree.py  (Cell-route authority plus Brain metadata projection)
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
import inspect

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


class _ObserveCellBridge:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.created = []
        self.synced = []
        self.route_trees = {}

    def assembly_create(
        self,
        *,
        definition_key,
        fields,
        idempotency_field=None,
        x=0.0,
        y=0.0,
    ):
        if self.fail:
            raise RuntimeError("cell unavailable")
        record = {
            "created_root": f"assembly-instance:roma-{len(self.created) + 1}",
            "definition_key": definition_key,
            "fields": dict(fields or {}),
            "idempotency_field": idempotency_field,
        }
        self.created.append(record)
        return record

    def roma_tree_sync(self, tree, *, source="brain.roma", **_kwargs):
        if self.fail:
            raise RuntimeError("cell unavailable")
        self.route_trees[str(tree["tree_id"])] = dict(tree)
        record = {
            "ok": True,
            "tree_root": f"app:roma-tree:{tree['tree_id']}",
            "tree": dict(tree),
            "source": source,
            "node_count": len(tree.get("nodes", {})),
            "edge_count": sum(
                len(node.get("children", []))
                for node in tree.get("nodes", {}).values()
            ),
        }
        self.synced.append(record)
        return record

    def roma_tree_get(self, *, tree_id, **_kwargs):
        if self.fail:
            raise RuntimeError("cell unavailable")
        try:
            return self._project_tree(self.route_trees[str(tree_id)])
        except KeyError as ex:
            raise RuntimeError("cell tree not found") from ex

    def roma_tree_list(self, **_kwargs):
        if self.fail:
            raise RuntimeError("cell unavailable")
        trees = []
        for tree_id, tree in sorted(self.route_trees.items()):
            nodes = tree.get("nodes", {})
            edge_count = sum(len(node.get("children", []))
                             for node in nodes.values())
            trees.append({
                "tree_root": f"app:roma-tree:{tree_id}",
                "tree_id": tree_id,
                "title": tree.get("title", ""),
                "owner": tree.get("owner_user", "founder"),
                "node_count": len(nodes),
                "edge_count": edge_count,
                "frontier_count": len([
                    node for node in nodes.values()
                    if not node.get("children") and node.get("state") != "green"
                ]),
            })
        return {
            "ok": True,
            "schema": "archhub-roma-requirement-tree-cell-index/v1",
            "tree_ids": [tree["tree_id"] for tree in trees],
            "tree_count": len(trees),
            "trees": trees,
        }

    @staticmethod
    def _project_tree(tree):
        tree_id = str(tree["tree_id"])
        nodes = tree.get("nodes", {})
        root_for_id = {
            node_id: f"app:roma-tree:{tree_id}:node:{node_id}"
            for node_id in nodes
        }
        projected_nodes = {}
        edges = []
        for node_id, node in nodes.items():
            root = root_for_id[node_id]
            children = [root_for_id[child] for child in node.get("children", [])]
            for child in node.get("children", []):
                edges.append(f"app:roma-tree:{tree_id}:edge:{node_id}:{child}")
            projected_nodes[root] = {
                "root": root,
                "node_id": node_id,
                "parent": node.get("parent") or "",
                "title": node.get("title") or "",
                "predicate": node.get("predicate") or "",
                "state": node.get("state") or "open",
                "gate_kind": node.get("gate_kind") or "manual",
                "gate_spec": dict(node.get("gate_spec") or {}),
                "verdict": node.get("verdict") or "",
                "evidence_ref": node.get("evidence_ref") or "",
                "claimed_by": node.get("claimed_by") or "",
                "past_claimants": list(node.get("past_claimants") or []),
                "judged_by": node.get("judged_by") or "",
                "attempts": int(node.get("attempts") or 0),
                "created_at": node.get("created_at"),
                "updated_at": node.get("updated_at"),
                "children": children,
            }
        frontier = [
            node for node in projected_nodes.values()
            if not node["children"] and node["state"] != "green"
        ]
        return {
            "ok": True,
            "schema": "archhub-roma-requirement-tree-cell/v1",
            "tree_root": f"app:roma-tree:{tree_id}",
            "tree_id": tree_id,
            "owner": tree.get("owner_user", "founder"),
            "title": tree.get("title", ""),
            "created_at": tree.get("created_at"),
            "updated_at": tree.get("updated_at"),
            "root_node": root_for_id[tree["root_id"]],
            "node_count": len(projected_nodes),
            "edge_count": len(edges),
            "nodes": projected_nodes,
            "edges": edges,
            "frontier": frontier,
        }


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


def test_set_verdict_self_certification_refused(store, monkeypatch):
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
    # founder root authority can override — but ONLY authenticated by the root
    # token (env + matching arg); the bare bool no longer works (audit defect 3).
    monkeypatch.setenv("ARCHHUB_ROOT_TOKEN", "sekrit-42")
    rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                   verdict="green", judged_by="exec-A", is_root_authority=True,
                   root_token="sekrit-42")


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


def test_judge_leaf_records_verdict(store, tmp_path):
    # GATE-BINDING: the artifact must be FRESH (written after the leaf was
    # created) — judge_leaf now refutes pre-existing files, so the test writes
    # its artifact after atomize, mirroring real executor work.
    artifact = tmp_path / "fresh_leaf_artifact.py"
    tree = roma.atomize(store, vision="v", owner_user="founder",
        decomposition=[{"title": "compiles", "gate_kind": "py_compile",
                        "gate_spec": {"path": str(artifact)}}])
    artifact.write_text("X = 1\n", encoding="utf-8")  # work done AFTER the leaf
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="ex")
    out = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          judged_by="court-X")
    assert out["court"]["verdict"] == "green"
    assert out["node"]["state"] == "green"


def test_run_to_dry_reaches_full_green_sweep(store, tmp_path):
    # The executor WRITES the artifacts (fresh files, after the leaves were
    # created) — a pre-existing file no longer proves a leaf (gate-binding).
    paths = {"a": tmp_path / "leaf_a.py", "b": tmp_path / "leaf_b.py"}
    tree = roma.atomize(store, vision="two real leaves", owner_user="founder",
        decomposition=[
            {"title": "a", "gate_kind": "py_compile", "gate_spec": {"path": str(paths["a"])}},
            {"title": "b", "gate_kind": "py_compile", "gate_spec": {"path": str(paths["b"])}},
        ])

    def executor(leaf, ctx):
        paths[leaf.title].write_text(f"# built {leaf.title}\nX = 1\n", encoding="utf-8")
        return {"last_message": f"did {leaf.title}; wrote files",
                "session_signals": {"wrote_files": True}}

    final = roma.run_to_dry(
        store, tree_id=tree.tree_id, executor=executor, judged_by="court-Z",
        context={"executor_id": "exec-loop"}, max_rounds=5,
    )
    assert final["dry"] is True and final["root_green"] is True
    assert final["green_leaves"] == 2
    assert final["rounds_run"] >= 1


def test_run_to_dry_re_decomposes_red_leaf(store, tmp_path):
    # A leaf that always refutes (missing file), with an auto_decompose that
    # splits it into a real (compilable) child → the tree converges. The
    # executor WRITES the child's artifact (fresh file — gate-binding).
    fixed = tmp_path / "fixed_child.py"
    tree = roma.atomize(store, vision="recover", owner_user="founder",
        decomposition=[{"title": "bad", "gate_kind": "file_exists",
                        "gate_spec": {"path": "/missing.zzz"}}])

    def executor(leaf, ctx):
        if leaf.title == "fixed-child":
            fixed.write_text("X = 1\n", encoding="utf-8")
        return {"last_message": "attempted; wrote files",
                "session_signals": {"wrote_files": True}}

    splits = {"count": 0}

    def auto_decompose(node):
        # Only split the original bad leaf, once, into a compilable child.
        # (The child's gate DIFFERS from the parent's — identical-gate clones
        # are refused by decompose since the boosting fix.)
        if node.title == "bad" and splits["count"] == 0:
            splits["count"] += 1
            return [{"title": "fixed-child", "gate_kind": "py_compile",
                     "gate_spec": {"path": str(fixed)}}]
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


def test_atomize_cell_first_syncs_without_brain_projection(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur

    bridge = _ObserveCellBridge()

    def _bridge_factory():
        assert store.get_meta(rt.TREE_META_KEY) is None
        return bridge

    monkeypatch.setattr(ur, "UniversalRuntimeBridge", _bridge_factory)

    out = roma.atomize_cell_first(
        store,
        vision="cell first direct atomize",
        owner_user="founder",
        decomposition=[{"title": "leaf", "gate_kind": "manual"}],
    )

    assert out["ok"] is True
    assert out["authority_source"] == "cell_route"
    assert out["brain_written"] is False
    assert bridge.synced[0]["source"] == "roma.atomize_cell_first"
    assert bridge.synced[0]["tree"]["tree_id"] == out["tree_id"]
    assert store.get_meta(rt.TREE_META_KEY) is None


def test_judge_leaf_cell_first_syncs_verdict_to_route(store, monkeypatch, tmp_path):
    from personal_brain import universal_runtime as ur

    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    artifact = tmp_path / "cell_first_judge.py"
    atomized = roma.atomize_cell_first(
        store,
        vision="cell first judge",
        owner_user="founder",
        decomposition=[{
            "title": "leaf",
            "gate_kind": "py_compile",
            "gate_spec": {"path": str(artifact)},
        }],
    )
    tree = rt.tree_from_cell_projection(
        bridge.roma_tree_get(tree_id=atomized["tree_id"])
    )
    leaf = tree.leaves()[0]
    artifact.write_text("X = 1\n", encoding="utf-8")
    roma.claim_leaf_cell_first(
        store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="exec-a"
    )

    out = roma.judge_leaf_cell_first(
        store, tree_id=tree.tree_id, node_id=leaf.node_id, judged_by="court-a"
    )

    assert out["ok"] is True
    assert out["authority_source"] == "cell_route"
    assert out["court"]["verdict"] == "green"
    projected = bridge.roma_tree_get(tree_id=tree.tree_id)
    leaf_root = f"app:roma-tree:{tree.tree_id}:node:{leaf.node_id}"
    assert projected["nodes"][leaf_root]["state"] == "green"
    assert rt.get_tree(store, tree_id=tree.tree_id) is None


def test_run_to_dry_cell_first_uses_route_for_loop_writes(
    store, monkeypatch, tmp_path,
):
    from personal_brain import universal_runtime as ur

    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    artifact = tmp_path / "cell_first_loop.py"
    atomized = roma.atomize_cell_first(
        store,
        vision="cell first loop",
        owner_user="founder",
        decomposition=[{
            "title": "leaf",
            "gate_kind": "py_compile",
            "gate_spec": {"path": str(artifact)},
        }],
    )

    def executor(leaf, ctx):
        artifact.write_text("X = 1\n", encoding="utf-8")
        return {
            "last_message": "wrote and verified cell first loop",
            "session_signals": {"wrote_files": True},
        }

    final = roma.run_to_dry_cell_first(
        store,
        tree_id=atomized["tree_id"],
        executor=executor,
        judged_by="court-loop",
        context={"executor_id": "exec-loop"},
        max_rounds=3,
    )

    assert final["dry"] is True
    assert final["authority_source"] == "cell_route"
    sources = [item["source"] for item in bridge.synced]
    assert "roma.atomize_cell_first" in sources
    assert "roma.claim_leaf_cell_first" in sources
    assert "roma.judge_leaf_cell_first" in sources
    assert store.get_meta(rt.TREE_META_KEY) is None


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


def test_tree_create_mcp_syncs_tree_route_before_projection(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.tree_create"].handler(title="cell rooted vision")

    assert out["ok"] is True
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is True
    assert out["cell_tree_root"] == f"app:roma-tree:{out['tree_id']}"
    assert bridge.created == []
    assert bridge.synced[0]["source"] == "brain.tree_create"
    assert bridge.synced[0]["tree"]["tree_id"] == out["tree_id"]
    assert store.get_meta(rt.TREE_META_KEY)


def test_tree_create_mcp_cell_failure_prevents_tree_write(store, monkeypatch):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.tree_create"].handler(title="denied vision")

    assert out["ok"] is False
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is False
    assert "cell unavailable" in out["error"]
    assert store.get_meta(rt.TREE_META_KEY) is None


def test_tree_decompose_mcp_cell_failure_prevents_tree_mutation(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    tree = rt.create_root(store, title="vision", owner_user="founder")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.tree_decompose"].handler(
        tree_id=tree.tree_id,
        node_id=tree.root_id,
        children=[{"title": "leaf", "gate_kind": "manual"}],
    )

    assert out["ok"] is False
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is False
    reloaded = rt.get_tree(store, tree_id=tree.tree_id)
    assert reloaded.nodes[tree.root_id].children == []


def test_tree_verdict_mcp_cell_failure_prevents_verdict_write(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    tree = rt.create_root(store, title="vision", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "leaf", "gate_kind": "manual"}])
    leaf = rt.get_tree(store, tree_id=tree.tree_id).leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="executor")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.tree_verdict"].handler(
        tree_id=tree.tree_id,
        node_id=leaf.node_id,
        verdict="green",
        judged_by="court",
    )

    assert out["ok"] is False
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is False
    reloaded = rt.get_tree(store, tree_id=tree.tree_id).nodes[leaf.node_id]
    assert reloaded.state == rt.NodeState.CLAIMED
    assert reloaded.verdict is None


def test_roma_atomize_mcp_cell_failure_prevents_tree_write(store, monkeypatch):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.roma_atomize"].handler(
        vision="denied roma vision",
        decomposition=[{"title": "leaf", "gate_kind": "manual"}],
    )

    assert out["ok"] is False
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is False
    assert store.get_meta(rt.TREE_META_KEY) is None


def test_roma_judge_mcp_cell_failure_prevents_verdict_write(
    store, monkeypatch, tmp_path,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    artifact = tmp_path / "fresh_roma_leaf.py"
    tree = roma.atomize(store, vision="v", owner_user="founder",
        decomposition=[{"title": "leaf", "gate_kind": "py_compile",
                        "gate_spec": {"path": str(artifact)}}])
    artifact.write_text("X = 1\n", encoding="utf-8")
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="executor")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.roma_judge"].handler(
        tree_id=tree.tree_id,
        node_id=leaf.node_id,
        judged_by="court",
    )

    assert out["ok"] is False
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is False
    assert "court" not in out
    reloaded = rt.get_tree(store, tree_id=tree.tree_id).nodes[leaf.node_id]
    assert reloaded.state == rt.NodeState.CLAIMED
    assert reloaded.verdict is None


def test_roma_public_claim_refuses_legacy_tree_fallback(store, monkeypatch):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    legacy = roma.atomize(
        store,
        vision="legacy tree cannot become governed authority",
        owner_user="founder",
        decomposition=[{"title": "leaf", "gate_kind": "manual"}],
    )
    leaf = legacy.leaves()[0]
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", _ObserveCellBridge)
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.roma_claim"].handler(
        tree_id=legacy.tree_id,
        node_id=leaf.node_id,
        agent_id="executor",
    )

    assert out["ok"] is False
    assert out["cell_first"] is True
    assert out["cell_tree_first"] is True
    assert out["brain_written"] is False
    unchanged = rt.get_tree(store, tree_id=legacy.tree_id).nodes[leaf.node_id]
    assert unchanged.state == rt.NodeState.OPEN
    assert unchanged.claimed_by is None


def test_roma_mcp_writes_only_the_actual_cell_tree(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    bridge = _ObserveCellBridge()

    def _bridge_factory():
        assert store.get_meta(rt.TREE_META_KEY) is None
        return bridge

    monkeypatch.setattr(ur, "UniversalRuntimeBridge", _bridge_factory)
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.roma_atomize"].handler(
        vision="route first",
        decomposition=[{"title": "leaf", "gate_kind": "manual"}],
    )

    assert out["ok"] is True
    assert out["cell_tree_first"] is True
    assert bridge.created == []
    assert bridge.synced[0]["source"] == "brain.roma_atomize"
    assert bridge.synced[0]["tree"]["tree_id"] == out["tree_id"]
    assert out["brain_written"] is False
    assert store.get_meta(rt.TREE_META_KEY) is None


def test_tree_read_mcp_prefers_cell_route_over_brain_projection(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    brain_tree = rt.create_root(
        store, title="brain projection title", owner_user="founder"
    )
    route_tree = rt.build_root_tree(
        title="cell route title",
        owner_user="founder",
        tree_id=brain_tree.tree_id,
    )
    rt._decompose_tree(
        route_tree,
        tree_id=route_tree.tree_id,
        node_id=route_tree.root_id,
        children=[{
            "title": "route leaf",
            "predicate": "read tools use the Cell route",
            "gate_kind": "manual",
        }],
    )
    bridge = _ObserveCellBridge()
    bridge.roma_tree_sync(
        route_tree.model_dump(mode="json"), source="test.cell_route"
    )
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    mcp = build_server(store=store, default_owner_user="founder")

    got = mcp._tools["brain.tree_get"].handler(tree_id=brain_tree.tree_id)
    swept = mcp._tools["brain.tree_sweep"].handler(tree_id=brain_tree.tree_id)
    frontier = mcp._tools["brain.tree_frontier"].handler(
        tree_id=brain_tree.tree_id
    )

    assert got["ok"] is True
    assert got["authority_source"] == "cell_route"
    assert got["tree"]["title"] == "cell route title"
    assert got["tree"]["root_id"] == route_tree.root_id
    assert swept["authority_source"] == "cell_route"
    assert swept["total_leaves"] == 1
    assert frontier["authority_source"] == "cell_route"
    assert frontier["frontier"][0]["title"] == "route leaf"


def test_roma_list_prefers_cell_registry_over_brain_projection(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    rt.create_root(store, title="brain-only tree", owner_user="founder")
    route_tree = rt.build_root_tree(
        title="cell-listed tree",
        owner_user="founder",
        tree_id="route-tree-id",
    )
    bridge = _ObserveCellBridge()
    bridge.roma_tree_sync(
        route_tree.model_dump(mode="json"), source="test.cell_registry"
    )
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.roma_list"].handler()

    assert out["ok"] is True
    assert out["authority_source"] == "cell_route"
    assert out["trees"] == ["route-tree-id"]
    assert out["cell_tree_index"]["tree_count"] == 1


def test_tree_backfill_cell_syncs_existing_brain_projection_trees(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    first = rt.create_root(store, title="first legacy tree", owner_user="founder")
    second = rt.create_root(store, title="second legacy tree", owner_user="founder")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.tree_backfill_cell"].handler(limit=10)

    assert out["ok"] is True
    assert out["schema"] == "archhub-requirement-tree-cell-backfill/v1"
    assert out["synced_count"] == 2
    assert out["failed_count"] == 0
    assert sorted(item["tree_id"] for item in out["results"]) == sorted([
        first.tree_id,
        second.tree_id,
    ])
    assert sorted(bridge.route_trees) == sorted([first.tree_id, second.tree_id])
    assert all(item["source"] == "brain.tree_backfill_cell"
               for item in bridge.synced)


def test_tree_backfill_cell_reports_failure_without_deleting_projection(
    store, monkeypatch,
):
    from personal_brain import universal_runtime as ur
    from personal_brain.server import build_server

    tree = rt.create_root(store, title="legacy tree", owner_user="founder")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    mcp = build_server(store=store, default_owner_user="founder")

    out = mcp._tools["brain.tree_backfill_cell"].handler(tree_ids=[tree.tree_id])

    assert out["ok"] is False
    assert out["synced_count"] == 0
    assert out["failed_count"] == 1
    assert out["results"][0]["status"] == "cell_sync_failed"
    assert rt.get_tree(store, tree_id=tree.tree_id) is not None


def test_roma_mcp_handlers_do_not_call_receipt_assembly_for_tree_writes():
    source = (
        inspect.getsource(rt.register_tree_tools)
        + inspect.getsource(roma.register_roma_tools)
    )
    assert "create_requirement_tree_cell_receipt(" not in source
    assert "sync_requirement_tree_cell_graph(" in source


def test_public_roma_handlers_cannot_write_or_fallback_to_brain_projection():
    source = inspect.getsource(roma.register_roma_tools)
    assert "save_tree_projection_after_cell_sync(" not in source
    assert "allow_legacy_fallback=False" in source


def test_roma_mcp_read_handlers_use_authority_first_helpers():
    source = (
        inspect.getsource(rt.register_tree_tools)
        + inspect.getsource(roma.register_roma_tools)
    )
    assert "read_tree_authority_first(" in source
    assert "list_trees_authority_first(" in source
    assert "rt.sweep(store" not in source
    assert "rt.frontier(store" not in source
    assert "rt.list_trees(store)" not in source


def test_tree_backfill_cell_is_registered_as_additive_sync():
    source = inspect.getsource(rt.register_tree_tools)
    helper = inspect.getsource(rt.backfill_requirement_trees_to_cell_graph)
    assert "brain.tree_backfill_cell" in source
    assert "backfill_requirement_trees_to_cell_graph(" in source
    assert "sync_requirement_tree_cell_graph(" in helper
    assert ".delete(" not in helper


def test_direct_cell_first_roma_helpers_sync_cell_route():
    source = (
        inspect.getsource(roma.atomize_cell_first)
        + inspect.getsource(roma.decompose_cell_first)
        + inspect.getsource(roma.claim_leaf_cell_first)
        + inspect.getsource(roma.judge_leaf_cell_first)
        + inspect.getsource(roma.server_verify_leaf_cell_first)
        + inspect.getsource(roma.run_to_dry_cell_first)
    )
    assert source.count("sync_requirement_tree_cell_graph(") >= 5
    assert "rt.set_verdict(" not in source
    assert "rt.claim_leaf(store" not in source
