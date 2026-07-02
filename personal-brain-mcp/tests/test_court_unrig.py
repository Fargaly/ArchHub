"""COURT UN-RIG regressions — the 2026-07-02 forensic audit's attack scripts,
encoded so each exploit now FAILS.

Every test here is a reproduced attack from the audit (21 agents, every finding
independently reproduced). Before the fixes each of these attacks SUCCEEDED:

  1. IDENTITY     — 'Exec-1' judged a leaf claimed by 'exec-1' (case-flip) and
                    ' exec-1 ' (trailing space): exact == on free strings.
  2. UNCLAIMED    — greening a never-claimed leaf skipped the anti-self-cert
                    guard entirely; and a red round-trip cleared claimed_by so
                    the ORIGINAL claimer could come back as the "independent"
                    judge.
  3. GOD-MODE     — set_verdict(is_root_authority=True) bypassed everything,
                    unauthenticated, and the promised logging did not exist.
  4. GATE-BINDING — 'cure cancer' gated on C:/Windows/win.ini went green (the
                    artifact lens never read the claim; any pre-existing file
                    "proved" any leaf).
  5. JURY         — a single applied lens greened a leaf (jury of one), and no
                    confidence notion existed (founder spec
                    selfext_juror_diversity: weighted soft vote, threshold 0.7).
  6. BOOSTING     — a red leaf was "re-decomposed" into an identical-gate clone
                    under a new title, retrying the same gate forever.

Style mirrors test_roma.py: pure + deterministic, in-memory store, no network.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from personal_brain import court_harness as ch
from personal_brain import requirement_tree as rt
from personal_brain import roma
from personal_brain.storage import BrainStore


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_root_token(monkeypatch):
    """Every test starts with NO root token configured — the god-mode path must
    be CLOSED by default; tests that exercise it opt in explicitly."""
    monkeypatch.delenv(ch.ROOT_TOKEN_ENV, raising=False)


def _tree_with_claimed_leaf(store, *, agent_id="exec-1", title="leaf",
                            gate_kind="manual", gate_spec=None):
    """One-leaf tree, leaf CLAIMED by `agent_id`. Returns (tree_id, leaf_id)."""
    tree = rt.create_root(store, title=f"vision-{title}", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id, children=[
        {"title": title, "gate_kind": gate_kind, "gate_spec": gate_spec or {}},
    ])
    leaf_id = rt._node_id(tree.tree_id, tree.root_id, title)
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf_id, agent_id=agent_id)
    return tree.tree_id, leaf_id


# ═══════════════════ 1. IDENTITY — normalization ════════════════════════


def test_case_flip_judge_refused_in_set_verdict(store):
    """ATTACK: leaf claimed by 'exec-1', judge signs as 'Exec-1' → used to
    self-certify green. Now: PermissionError (identities normalized)."""
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="Exec-1")


def test_trailing_space_judge_refused_in_set_verdict(store):
    """ATTACK: judge ' exec-1 ' (trailing/leading spaces) vs claimer 'exec-1'."""
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by=" exec-1 ")


def test_case_flip_refused_by_independence_lens():
    """Same attack at the court layer: the independence lens must refute a
    case-flipped judge (court_harness.py:274 was exact ==)."""
    art = ch.LensVerdict(lens="artifact", refuted=False, applied=True,
                         evidence_ref="x")
    v = ch.lens_independence(claimed_by="exec-1", judged_by="Exec-1",
                             artifact_lens=art)
    assert v.applied and v.refuted
    assert v.failure_mode == "self_certification"
    # trailing space too
    v2 = ch.lens_independence(claimed_by="exec-1", judged_by=" exec-1 ",
                              artifact_lens=art)
    assert v2.refuted


# ═══════════════════ 2. UNCLAIMED BYPASS + CLAIM HISTORY ═════════════════


def test_green_on_unclaimed_leaf_refused(store):
    """ATTACK: greening a leaf that was NEVER claimed skipped the guard
    ('node.claimed_by and ...'). Now: PermissionError — a verdict needs a
    claimed executor to judge against."""
    tree = rt.create_root(store, title="v-unclaimed", owner_user="founder")
    rt.decompose(store, tree_id=tree.tree_id, node_id=tree.root_id,
                 children=[{"title": "leaf"}])
    leaf_id = rt._node_id(tree.tree_id, tree.root_id, "leaf")
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf_id,
                       verdict="green", judged_by="anyone")
    # red / needs_root on an unclaimed leaf are still recordable (only GREEN
    # needs an executor to have stood behind the work).
    n = rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf_id,
                       verdict="needs_root", judged_by="court")
    assert n.state == rt.NodeState.NEEDS_ROOT


def test_red_roundtrip_original_claimer_cannot_regreen(store):
    """ATTACK: red cleared claimed_by, so the ORIGINAL claimer re-entered as
    the 'independent' judge one round-trip later. Now: claim history
    (past_claimants) blocks any past claimant from judging green — even
    case-flipped."""
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                   verdict="red", judged_by="court-X")
    node = rt.get_tree(store, tree_id=tid).nodes[leaf_id]
    assert node.claimed_by is None                  # re-entered the frontier
    assert "exec-1" in node.past_claimants          # ...but the history stays

    # a second executor picks it up
    rt.claim_leaf(store, tree_id=tid, node_id=leaf_id, agent_id="exec-2")
    # the ORIGINAL claimer tries to come back as the judge → refused
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="exec-1")
    # case-flipped boomerang refused too
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="EXEC-1")
    # a genuinely independent judge still can
    n = rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="court-X")
    assert n.state == rt.NodeState.GREEN


# ═══════════════════ 3. GOD-MODE BOOL → AUTHENTICATED + AUDITED ══════════


def test_root_authority_without_token_refused(store):
    """ATTACK: set_verdict(is_root_authority=True) bypassed self-cert with no
    authentication at all. Now: no env token configured → PermissionError,
    whatever the caller passes."""
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="exec-1",
                       is_root_authority=True)
    # even WITH a token argument, no env token == closed path
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="exec-1",
                       is_root_authority=True, root_token="guess")


def test_root_authority_with_wrong_token_refused(store, monkeypatch):
    monkeypatch.setenv(ch.ROOT_TOKEN_ENV, "the-real-token")
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    with pytest.raises(PermissionError):
        rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="exec-1",
                       is_root_authority=True, root_token="wrong")


def test_root_authority_with_token_succeeds_and_is_audited(store, monkeypatch):
    """The founder path still works — authenticated — and EVERY override now
    writes a REAL audit entry (brain_meta['root_override_log_v1']), fixing the
    docstring's false 'it is logged' claim."""
    monkeypatch.setenv(ch.ROOT_TOKEN_ENV, "the-real-token")
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    n = rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                       verdict="green", judged_by="exec-1",
                       is_root_authority=True, root_token="the-real-token")
    assert n.state == rt.NodeState.GREEN

    raw = store.get_meta(rt.ROOT_OVERRIDE_LOG_KEY)
    assert raw, "root override must append to root_override_log_v1"
    log = json.loads(raw)
    assert isinstance(log, list) and len(log) == 1
    entry = log[0]
    assert entry["node_id"] == leaf_id
    assert entry["tree_id"] == tid
    assert entry["judged_by"] == "exec-1"
    assert entry["verdict"] == "green"
    assert entry["ts"]  # timestamp recorded


def _call_tool(mcp, name, arguments):
    """Invoke an in-house MCP tool synchronously and unwrap the JSON payload
    (mirrors test_cloud_archive_tool._call)."""
    result = mcp.call_tool(name, arguments or {})
    sc = result.get("structuredContent") if isinstance(result, dict) else None
    if sc is not None:
        return sc
    content = result.get("content") if isinstance(result, dict) else None
    if content:
        return json.loads(content[0].get("text", "{}"))
    return result


def test_tree_verdict_mcp_tool_requires_root_token(store, monkeypatch):
    """The unauthenticated god-mode was EXPOSED on brain.tree_verdict. The tool
    now carries root_token and refuses without it."""
    from personal_brain.server import build_server
    monkeypatch.setenv(ch.ROOT_TOKEN_ENV, "mcp-token")
    tid, leaf_id = _tree_with_claimed_leaf(store, agent_id="exec-1")
    mcp = build_server(store=store, default_owner_user="founder")
    tool = {t["name"]: t for t in mcp.list_tools()}["brain.tree_verdict"]
    assert "root_token" in json.dumps(tool["inputSchema"])

    out = _call_tool(mcp, "brain.tree_verdict", {
        "tree_id": tid, "node_id": leaf_id, "verdict": "green",
        "judged_by": "exec-1", "is_root_authority": True,
    })
    assert out["ok"] is False and "PermissionError" in out["error"]
    ok = _call_tool(mcp, "brain.tree_verdict", {
        "tree_id": tid, "node_id": leaf_id, "verdict": "green",
        "judged_by": "exec-1", "is_root_authority": True,
        "root_token": "mcp-token",
    })
    assert ok["ok"] is True and ok["node"]["state"] == "green"


# ═══════════════════ 4. GATE-BINDING — pre-existing artifacts ════════════


def test_cure_cancer_gated_on_preexisting_file_refuted(store, tmp_path):
    """THE win.ini ATTACK: a leaf titled 'cure cancer' gated on a file that
    existed long before the leaf went green. Now: a target whose mtime
    predates leaf_created_at REFUTES, and the verdict reason names the leaf's
    title/predicate (the claim is finally IN the evidence string)."""
    winini = tmp_path / "win.ini"
    winini.write_text("[fonts]\n", encoding="utf-8")
    ancient = time.time() - 10 * 365 * 24 * 3600
    os.utime(winini, (ancient, ancient))            # pre-existing artifact

    tree = roma.atomize(store, vision="cure cancer vision", owner_user="founder",
        decomposition=[{"title": "cure cancer",
                        "predicate": "cancer is cured",
                        "gate_kind": "file_exists",
                        "gate_spec": {"path": str(winini)}}])
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="exec-1")
    out = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          judged_by="court-X",
                          context={"evidence": {
                              "last_message": "did the work; wrote files",
                              "session_signals": {"wrote_files": True}}})
    assert out["court"]["verdict"] == "red"
    assert "pre-existing artifact refused" in out["court"]["reason"]
    assert "cure cancer" in out["court"]["reason"]      # claim bound to gate
    assert "cancer is cured" in out["court"]["reason"]
    assert out["node"]["state"] == "red"


def test_fresh_file_created_after_leaf_passes(store, tmp_path):
    """The honest path still greens: an artifact WRITTEN AFTER the leaf was
    created proves new work."""
    artifact = tmp_path / "new_work.py"
    tree = roma.atomize(store, vision="real work", owner_user="founder",
        decomposition=[{"title": "write the module",
                        "gate_kind": "py_compile",
                        "gate_spec": {"path": str(artifact)}}])
    artifact.write_text("VALUE = 42\n", encoding="utf-8")  # work AFTER leaf
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="exec-1")
    out = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          judged_by="court-X",
                          context={"evidence": {
                              "last_message": "wrote the module; ran checks",
                              "session_signals": {"wrote_files": True}}})
    assert out["court"]["verdict"] == "green"
    assert out["node"]["state"] == "green"


def test_pre_existing_ok_requires_root_token(store, tmp_path, monkeypatch):
    """gate_spec['pre_existing_ok']=true is honoured ONLY on the root-token
    path — without the token the stale artifact still refutes."""
    old = tmp_path / "old.txt"
    old.write_text("x", encoding="utf-8")
    ancient = time.time() - 3600 * 24 * 30
    os.utime(old, (ancient, ancient))

    tree = roma.atomize(store, vision="grandfathered", owner_user="founder",
        decomposition=[{"title": "leaf", "gate_kind": "file_exists",
                        "gate_spec": {"path": str(old), "pre_existing_ok": True}}])
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="exec-1")
    ev = {"evidence": {"last_message": "verified the existing artifact; ran checks",
                       "session_signals": {"ran_tests": True}}}
    # no token → the flag is a no-op, stale still refutes
    out = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          judged_by="court-X", context=dict(ev))
    assert out["court"]["verdict"] == "red"
    # with the authenticated root token the founder may grandfather it
    # (re-claim first: the red round-trip freed the leaf, and a green needs a
    # claimed executor to judge against)
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="exec-2")
    monkeypatch.setenv(ch.ROOT_TOKEN_ENV, "tok")
    out2 = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                           judged_by="court-X",
                           context={**ev, "root_token": "tok"})
    assert out2["court"]["verdict"] == "green"


# ═══════════════════ 5. JUROR DIVERSITY + CONFIDENCE SOFT-VOTE ═══════════


def _fresh_py(tmp_path):
    p = tmp_path / "fresh.py"
    p.write_text("X = 1\n", encoding="utf-8")
    return str(p)


def test_jury_of_one_needs_root(tmp_path):
    """ATTACK: the artifact lens alone greened a machine-gated leaf. Now: an
    unclaimed leaf with no executor evidence leaves ONLY the artifact lens
    applied → a jury of one is not a jury → needs_root, never green."""
    v = ch.convene_court(
        node_id="n1", gate_kind="py_compile",
        gate_spec={"path": _fresh_py(tmp_path)},
        claimed_by=None, judged_by="court-X",   # nobody claimed, no evidence
    )
    applied = [l for l in v.lenses if l.applied]
    assert len(applied) == 1 and applied[0].lens == "artifact"
    assert v.verdict == "needs_root" and v.green is False
    assert "jury of one" in v.reason


def test_low_confidence_soft_vote_needs_root(tmp_path):
    """Founder spec: green needs sum(conf*weight)/sum(weights) >= 0.7 over the
    applied non-refuted lenses. A passing-but-weak artifact probe (confidence
    0.2) drags the vote under threshold → needs_root."""
    def weak_probe(gate_spec, context):
        return ch.ProbeResult(passed=True, confidence=0.2,
                              detail="matched, but weakly", evidence_ref="weak:x")

    v = ch.convene_court(
        node_id="n1", gate_kind="weak_gate", gate_spec={},
        claimed_by="exec-1", judged_by="court-X",
        extra_probes={"weak_gate": weak_probe},
        context={"evidence": {"last_message": "did it; ran tests",
                              "session_signals": {"ran_tests": True}}},
    )
    # no lens refuted, 3 applied — but the weighted vote is
    # (0.2*2 + 1*1 + 1*1) / 4 = 0.60 < 0.70
    assert not any(l.refuted for l in v.lenses)
    assert v.verdict == "needs_root" and v.green is False
    assert "soft-vote" in v.reason


def test_full_confidence_soft_vote_greens(tmp_path):
    """Control: the same jury at full confidence clears the threshold."""
    v = ch.convene_court(
        node_id="n1", gate_kind="py_compile",
        gate_spec={"path": _fresh_py(tmp_path)},
        claimed_by="exec-1", judged_by="court-X",
        context={"evidence": {"last_message": "did it; ran tests",
                              "session_signals": {"ran_tests": True}}},
    )
    assert v.verdict == "green" and v.green is True


def test_refuted_lens_is_red_regardless_of_confidence():
    """Fail-closed ABSOLUTE: a refuted lens is red no matter how confident the
    other jurors are — confidence never rescues a refutation."""
    def confident_fail(gate_spec, context):
        return ch.ProbeResult(passed=False, confidence=1.0,
                              detail="artifact wrong", evidence_ref="x")

    v = ch.convene_court(
        node_id="n1", gate_kind="g", gate_spec={},
        claimed_by="exec-1", judged_by="court-X",
        extra_probes={"g": confident_fail},
        context={"evidence": {"last_message": "did it; ran tests",
                              "session_signals": {"ran_tests": True}}},
    )
    assert v.verdict == "red" and v.green is False
    art = [l for l in v.lenses if l.lens == "artifact"][0]
    assert art.refuted and art.failure_mode


def test_lens_verdicts_carry_failure_mode_and_confidence():
    """Each lens result now carries the founder-spec fields."""
    art = ch.lens_artifact(gate_kind="file_exists",
                           gate_spec={"path": "/no/such/file.xyz"}, context={})
    assert art.refuted and art.failure_mode != ""
    assert 0.0 <= art.confidence <= 1.0
    d = art.to_dict()
    assert "failure_mode" in d and "confidence" in d


# ═══════════════════ 6. BOOSTING — no cosmetic clones ════════════════════


def test_identical_gate_clone_of_red_leaf_raises(store):
    """ATTACK: a red leaf 're-decomposed' into a child with the SAME gate_kind
    + gate_spec under a new title — the same check retried forever. Now:
    ValueError."""
    tid, leaf_id = _tree_with_claimed_leaf(
        store, agent_id="exec-1", gate_kind="file_exists",
        gate_spec={"path": "/missing.zzz"})
    rt.set_verdict(store, tree_id=tid, node_id=leaf_id,
                   verdict="red", judged_by="court-X")
    with pytest.raises(ValueError, match="cosmetic clone"):
        rt.decompose(store, tree_id=tid, node_id=leaf_id, children=[
            {"title": "leaf — re-verify the real artifact",
             "gate_kind": "file_exists", "gate_spec": {"path": "/missing.zzz"}},
        ])
    # a child whose gate actually DIFFERS is a real split → allowed
    tree = rt.decompose(store, tree_id=tid, node_id=leaf_id, children=[
        {"title": "narrower check", "gate_kind": "file_exists",
         "gate_spec": {"path": "/missing.zzz", "contains": "marker"}},
    ])
    assert len(tree.nodes[leaf_id].children) == 1


def test_second_round_forces_require_diligence(store, tmp_path):
    """BOOSTING guard: a leaf on its 2nd round (one red already) is judged with
    require_diligence FORCED — no executor evidence → red, even though the
    artifact itself would pass."""
    artifact = tmp_path / "round2.py"
    tree = roma.atomize(store, vision="rounds", owner_user="founder",
        decomposition=[{"title": "leaf", "gate_kind": "py_compile",
                        "gate_spec": {"path": str(artifact)}}])
    artifact.write_text("X = 1\n", encoding="utf-8")
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="exec-1")
    rt.set_verdict(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                   verdict="red", judged_by="court-X")     # round 1 failed
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                  agent_id="exec-2")
    out = roma.judge_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id,
                          judged_by="court-X",
                          require_diligence=False)          # caller says lax...
    # ...but round >= 2 forces show-the-work: no evidence → red.
    assert out["court"]["verdict"] == "red"
    assert "require_diligence" in out["court"]["reason"]


# ═══════════════════ 7. DEFAULTS — never-reward-short is ON ══════════════


def test_run_to_dry_defaults_require_diligence_true(store, tmp_path):
    """AUDIT defect 7: run_to_dry now defaults require_diligence=True — an
    executor that returns NO closing evidence cannot green a leaf, even with a
    passing artifact."""
    import inspect
    assert inspect.signature(roma.run_to_dry).parameters[
        "require_diligence"].default is True

    artifact = tmp_path / "lazy.py"
    tree = roma.atomize(store, vision="lazy exec", owner_user="founder",
        decomposition=[{"title": "leaf", "gate_kind": "py_compile",
                        "gate_spec": {"path": str(artifact)}}])

    def lazy_executor(leaf, ctx):
        artifact.write_text("X = 1\n", encoding="utf-8")
        return {}                                   # no closing evidence

    final = roma.run_to_dry(store, tree_id=tree.tree_id, executor=lazy_executor,
                            judged_by="court-Z",
                            context={"executor_id": "exec-loop"}, max_rounds=2)
    assert final["dry"] is False
    assert final["green_leaves"] == 0
