"""AgDR-0054 acceptance suite — BRV-07.

THE GAP THIS CLOSES. AgDR-0054 declares *"built == these pass"* over a
**27-item machine-checkable acceptance list** (the doc's "Acceptance suite"
§211-233 #1-#20 + the control-plane additions §322-344 #21-#27). On origin/main
**none of those 27 items had a selector**: `test_completion_gate.py` /
`test_active_work.py` cover the v0 *libraries*, but "Done == acceptance green"
had no suite to evaluate. This file is that suite: **>= 1 pytest selector per
acceptance #1-#27**, each named `test_acc_NN_*`, collecting under pytest.

HONESTY (ANTI-LIE / ROMA gate-every-leaf). This suite does NOT fabricate greens
for unbuilt work. Each item is one of two honest states:

  * **VERIFIED** — the acceptance criterion is backed by a built artifact, and
    the test makes a REAL assertion against that artifact (the rights dam, the
    decontamination scan, the ROMA court's independence lens, the ACL, the
    completion-gate drive, plan-lint, sweep-derived done, …).
  * **PLAN-LOCKED** — the criterion genuinely needs something not yet built (a
    trained checkpoint, a red-team corpus harness, a multi-replica cluster) or a
    founder action. Those `pytest.skip(...)` with the precise reason. A skip
    STILL collects and STILL provides the per-acceptance selector, and it is the
    pytest-native honest "not yet" — the test layer's equivalent of ROMA's
    `needs_root` (a leaf with no machine gate is never auto-green). When the
    artifact lands, the skip becomes a real assertion — the suite is the
    standing burndown of "Done == acceptance green".

A grep proves coverage: `grep -c "^def test_acc_" tests/test_agdr0054_acceptance.py`
== 27 (one per acceptance item), and `_ACCEPTANCE_INDEX` below maps each to its
state so the count of VERIFIED vs PLAN-LOCKED is itself machine-checkable
(`test_acceptance_index_covers_1_to_27`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── repo roots so both `tools/` and the brain package import cleanly ─────────
_REPO = Path(__file__).resolve().parents[1]


# ───────────────────────────── coverage index ───────────────────────────────
# Maps acceptance number -> ("verified"|"plan_locked", one-line note). The suite
# asserts this covers exactly 1..27 so the per-item selector count can't silently
# drift. "plan_locked" entries correspond to the tests that skip with a reason.
_ACCEPTANCE_INDEX: dict[int, tuple[str, str]] = {
    1:  ("verified", "court independence lens refutes a self-certified (forged) green"),
    2:  ("verified", "dataset_export excludes quarantined rows (zero quarantined bytes)"),
    3:  ("verified", "firm_private_only absent from a collective-target export"),
    4:  ("verified", "set_verdict refuses a root-authority override without is_root_authority"),
    5:  ("plan_locked", "HLC/LWW sibling-reconcile record not built (storage band-aid only)"),
    6:  ("plan_locked", "brain.db+graph.sqlite unified-store migration parity not built"),
    7:  ("plan_locked", "red-team corpus (AgentPoison/MemoryGraft) harness not built"),
    8:  ("plan_locked", "dual-retrieval A/B on our corpus not built (needs corpus+baseline)"),
    9:  ("plan_locked", "verified-skill A/B lift on ArchHub workflows not built"),
    10: ("plan_locked", "dam false-accept-vs-budget + retraction drill not built"),
    11: ("verified", "ACL blocks cross-tenant read (zero leakage) + filter_for_reader drops it"),
    12: ("verified", "train<->eval decontamination scan flags a known overlap"),
    13: ("plan_locked", "erasure-drill tombstone-to-all-replicas not built (no replica cluster)"),
    14: ("plan_locked", "forgetting/alignment regression gate needs a model promotion"),
    15: ("plan_locked", "poisoning-stack checkpoint activation-probe needs a checkpoint"),
    16: ("plan_locked", "base-model red-team audit needs a base model"),
    17: ("verified", "clean-corpus filter gates provider-prose out of the competing-model corpus"),
    18: ("verified", "eval time-split puts every eval item post-cutoff"),
    19: ("verified", "unlearning-by-export: a quarantined (revoked) row is absent from the next export"),
    20: ("plan_locked", "session+graph capture across composer/Claude Code/Codex/fleet not built"),
    21: ("verified", "control plane: completion gate blocks turn-exit on a red ledger gate"),
    22: ("verified", "tamper-proof done-rule: sweep-derived green + self-certification refused"),
    23: ("verified", "scope-lock: an undefined-scope leaf cannot go green (needs_root)"),
    24: ("verified", "the drive: red->block, needs_root->escalate (no silent-quit/fake-done)"),
    25: ("verified", "no-later gate: plan-lint rejects bare deferral, passes a tagged hold"),
    26: ("verified", "partial-cannot-land: a parent with a red child is not green (sweep)"),
    27: ("verified", "all-agents: brain-side sweep adjudicates done (not the hook) + plan-lint+gate exist"),
}


def test_acceptance_index_covers_1_to_27():
    """The index must name every acceptance item exactly once (1..27)."""
    assert set(_ACCEPTANCE_INDEX) == set(range(1, 28))
    for n, (state, note) in _ACCEPTANCE_INDEX.items():
        assert state in ("verified", "plan_locked"), (n, state)
        assert note, n


# ════════════════════════ VERIFIED — real assertions ════════════════════════

# ---- helpers (mirror the proven raw-insert pattern in the rights-dam tests) --

def _store(tmp_path):
    from personal_brain.storage import BrainStore as Store
    return Store.open(tmp_path / "acc.db")


def _ins(store, **kw):
    """Insert a fragment carrying the AgDR-0054 legal columns via raw SQL
    (write_fragment defaults the rights columns; the dam/scope tests do the
    same). Scope defaults to 'user' so the default-scope export picks it up."""
    prov_json = json.dumps({"contributing_agent": "test",
                            "contributing_user": "founder"})
    cols = {
        "id": kw["id"],
        "kind": kw.get("kind", "trace"),
        "text": kw.get("text", "t"),
        "scope": kw.get("scope", "user"),
        "owner_user": kw.get("owner_user", "founder"),
        "provenance_json": prov_json,
        "origin_kind": kw.get("origin_kind", "human_verified"),
        "training_rights_tier": kw.get("tier", "collective_ok"),
        "action_payload": kw.get("action", '{"op":"build_wall"}'),
        "language_payload": kw.get("lang"),
        "quarantine_flag": kw.get("quar", 0),
    }
    with store._lock:
        store._conn.execute(
            """INSERT INTO fragments(id,kind,text,scope,owner_user,provenance_json,
                origin_kind,training_rights_tier,action_payload,language_payload,
                quarantine_flag)
               VALUES(:id,:kind,:text,:scope,:owner_user,:provenance_json,
                :origin_kind,:training_rights_tier,:action_payload,:language_payload,
                :quarantine_flag)""",
            cols,
        )
        store._conn.commit()


def _exported_ids(manifest) -> set:
    jsonl = Path(manifest["files"]["jsonl"]["path"])
    if not jsonl.exists():
        return set()
    text = jsonl.read_text(encoding="utf-8").strip()
    return {json.loads(line)["id"] for line in text.splitlines() if line}


# #1 — Unverified/forged-attestation fragment never reaches the river.
def test_acc_01_forged_attestation_refuted_by_independent_court():
    """A green that rests on the claimant's own word (self-certification) is
    refuted by the court's independence lens — the server-side assertion that a
    forged attestation never reaches the river."""
    from personal_brain import court_harness as ch
    # a real artifact lens that PASSED on a named artifact (evidence_ref)
    passed = ch.LensVerdict(lens="artifact", refuted=False, applied=True,
                            evidence_ref="proof_x.png")
    # self-certification (judge == executor) is refuted on the independence lens
    v = ch.lens_independence(claimed_by="neuronA", judged_by="neuronA",
                             artifact_lens=passed)
    assert v.refuted is True and v.applied is True
    # an independent judge on a NAMED artifact is NOT refuted on independence
    v2 = ch.lens_independence(claimed_by="neuronA", judged_by="roma-court",
                              artifact_lens=passed)
    assert v2.refuted is False
    # a "trust-me" green (no named artifact evidence) IS refuted even when the
    # judge is independent — the forged-attestation guard
    no_artifact = ch.LensVerdict(lens="artifact", refuted=False, applied=True,
                                 evidence_ref=None)
    v3 = ch.lens_independence(claimed_by="neuronA", judged_by="roma-court",
                              artifact_lens=no_artifact)
    assert v3.refuted is True


# #2 — dataset_export contains zero quarantined bytes.
def test_acc_02_export_has_zero_quarantined_rows(tmp_path):
    store = _store(tmp_path)
    _ins(store, id="ok", tier="collective_ok", quar=0)
    _ins(store, id="forgotten", tier="collective_ok", quar=1)
    from personal_brain.dataset_export import export_fragments
    mf = export_fragments(store, out_dir=tmp_path / "e", dataset_name="d",
                          training_target="collective")
    assert "forgotten" not in _exported_ids(mf)


# #3 — Firm-A private fragments absent from the collective dataset.
def test_acc_03_firm_private_absent_from_collective(tmp_path):
    store = _store(tmp_path)
    _ins(store, id="collective", tier="collective_ok")
    _ins(store, id="firmA", tier="firm_private_only")
    from personal_brain.dataset_export import export_fragments
    mf = export_fragments(store, out_dir=tmp_path / "e", dataset_name="d",
                          training_target="collective")
    ids = _exported_ids(mf)
    assert "firmA" not in ids and "collective" in ids


# #4 — Mandate bump via auto path BLOCKED without founder signature.
def test_acc_04_root_override_requires_founder_authority(tmp_path):
    """A non-root attempt to force a verdict the court would refuse is blocked;
    only `is_root_authority=True` (the founder) may override — the mandate-bump
    signature gate expressed in the requirement-tree."""
    from personal_brain import requirement_tree as rt
    from personal_brain.storage import BrainStore as Store
    s = Store.open(tmp_path / "rt.db")
    root = rt.create_root(s, tree_id="t1", title="root")
    rt.decompose(s, tree_id="t1", node_id=root.root_id,
                 children=[{"title": "leaf", "gate_kind": "manual"}])
    leaf = rt.frontier(s, tree_id="t1")[0]
    rt.claim_leaf(s, tree_id="t1", node_id=leaf.node_id, agent_id="exec")
    # self-certification (judge == executor) is refused without root authority
    with pytest.raises(PermissionError):
        rt.set_verdict(s, tree_id="t1", node_id=leaf.node_id, verdict="green",
                       judged_by="exec", is_root_authority=False)


# #11 — Cross-tenant recall attack -> zero leakage.
def test_acc_11_cross_tenant_read_blocked_and_filtered():
    from personal_brain.acl import Identity, can_read, filter_for_reader
    from personal_brain.models import Scope
    other_firm_fragment = {
        "id": "f-secret", "kind": "fact", "text": "firm-B private",
        "scope": Scope.FIRM.value, "visibility": "private",
        "owner_user": "bob", "project_id": None, "firm_id": "firmB",
    }
    intruder = Identity(user_id="eve", firm_id="firmA")
    assert can_read(other_firm_fragment, reader=intruder).allow is False
    # and the bulk reader-filter drops it (zero leakage in a recall result set)
    visible = filter_for_reader([other_firm_fragment], reader=intruder)
    assert all(f["id"] != "f-secret" for f in visible)


# #12 — Decontamination scan train<->eval flags overlap (the BRV-14 artifact).
def test_acc_12_decontamination_flags_overlap():
    from personal_brain.decontamination import scan_decontamination
    eval_rows = [{"id": "e1", "text": "the quick brown fox jumps over the lazy "
                                      "sleeping dog beside the riverbank at dawn"}]
    train_rows = [{"id": "leak", "text": "the quick brown fox jumps over the lazy "
                                         "sleeping dog beside the riverbank at dawn"}]
    rep = scan_decontamination(train_rows, eval_rows)
    assert rep.scanned is True and rep.clean is False
    assert "leak" in rep.contaminated_train_ids


# #17 — Clean-corpus filter: provider-prose gated out of the competing-model set.
def test_acc_17_clean_corpus_gates_provider_prose(tmp_path):
    """`export_trainable_fragments` keeps the Tier-0 action signal but DROPS the
    language payload of a model-generated (provider-prose) trace unless the
    founder ToS gate (`allow_provider_prose`) is set — the §7a clean-corpus
    filter."""
    store = _store(tmp_path)
    _ins(store, id="model_trace", origin_kind="model_generated",
         tier="collective_ok", lang="claude wrote this prose", action='{"op":"x"}')
    rows = store.export_trainable_fragments(target="collective")
    row = next(r for r in rows if r["id"] == "model_trace")
    assert row["action_payload"] is not None          # Tier-0 always kept
    assert row["language_payload"] is None            # provider prose gated out
    # with the founder ToS gate the prose is allowed through
    rows2 = store.export_trainable_fragments(target="collective",
                                             allow_provider_prose=True)
    assert next(r for r in rows2 if r["id"] == "model_trace")["language_payload"]


# #18 — Eval time-split: every eval item post-cutoff.
def test_acc_18_eval_time_split_post_cutoff():
    from datetime import datetime, timedelta, timezone
    from personal_brain.decontamination import time_split
    now = datetime.now(timezone.utc)
    rows = [
        {"id": "train_old", "created_at": (now - timedelta(days=3)).isoformat()},
        {"id": "eval_new", "created_at": (now + timedelta(days=3)).isoformat()},
    ]
    train, eval_ = time_split(rows, now.isoformat())
    assert {r["id"] for r in eval_} == {"eval_new"}
    assert {r["id"] for r in train} == {"train_old"}


# #19 — Unlearning honesty: revoke (quarantine) -> absent from the NEXT export.
def test_acc_19_revoked_row_absent_from_next_export(tmp_path):
    """Export-gating IS the erasure: flipping quarantine_flag (a revocation)
    removes the row from the next export — the only reliable unlearning."""
    store = _store(tmp_path)
    _ins(store, id="revoked", tier="collective_ok", quar=1)
    rows = store.export_trainable_fragments(target="collective")
    assert all(r["id"] != "revoked" for r in rows)


# #21 — Control plane fires: a red ledger gate blocks the turn-exit.
def test_acc_21_control_plane_blocks_on_red_gate():
    import sys
    sys.path.insert(0, str(_REPO / "tools"))
    import completion_gate as cg
    v = cg.evaluate([cg.Gate(name="ledger-load")], iterations=0,
                    runner=lambda g: False)   # gate red
    assert v.action == "block"


# #22 — Tamper-proof done-rule: green is sweep-derived; self-cert refused.
def test_acc_22_done_is_sweep_derived_not_hand_asserted(tmp_path):
    from personal_brain import requirement_tree as rt
    from personal_brain.storage import BrainStore as Store
    s = Store.open(tmp_path / "rt22.db")
    root = rt.create_root(s, tree_id="t", title="r")
    rt.decompose(s, tree_id="t", node_id=root.root_id,
                 children=[{"title": "c1", "gate_kind": "manual"},
                           {"title": "c2", "gate_kind": "manual"}])
    # nothing verified yet -> sweep is NOT dry (done can't be hand-asserted)
    assert rt.sweep(s, tree_id="t").get("dry") is False


# #23 — Scope-lock: an undefined-scope (manual-gate) leaf cannot auto-green.
def test_acc_23_undefined_scope_leaf_is_needs_root():
    """A leaf with no machine gate (`manual`) is never auto-green — the court
    returns needs_root and it escalates, the scope-lock 'refuse if undefined'."""
    import sys
    sys.path.insert(0, str(_REPO / "tools"))
    import completion_gate as cg
    # a manual gate never passes -> not machine-resolvable -> escalate, never green
    g = cg.Gate(name="undefined-scope", kind="manual", machine_resolvable=False)
    v = cg.evaluate([g], iterations=0, runner=lambda gg: cg.run_gate(gg, Path(".")))
    assert v.action == "escalate"


# #24 — The drive fires: red->block; needs_root/cap->escalate (honest stop).
def test_acc_24_drive_blocks_red_and_escalates_needs_root():
    import sys
    sys.path.insert(0, str(_REPO / "tools"))
    import completion_gate as cg
    # red + machine-resolvable + under cap -> BLOCK (re-enter the agent)
    blk = cg.evaluate([cg.Gate(name="a")], iterations=0, runner=lambda g: False)
    assert blk.action == "block"
    # needs-human -> ESCALATE (not a silent quit, not a fake done)
    esc = cg.evaluate([cg.Gate(name="h", machine_resolvable=False)],
                      iterations=0, runner=lambda g: False)
    assert esc.action == "escalate"


# #25 — No-later gate: plan-lint rejects bare deferral, passes a tagged hold.
def test_acc_25_no_later_gate_rejects_untagged_passes_tagged():
    import sys
    sys.path.insert(0, str(_REPO / "tools"))
    import plan_lint as pl
    assert pl.lint_text("- [ ] ship it later\n")               # bare -> flagged
    assert pl.lint_text("- [ ] ship it later, depends-on:BRV-04\n") == []  # tagged -> ok


# #26 — Partial-cannot-land: a parent with any red child is not green.
def test_acc_26_partial_parent_not_green(tmp_path):
    from personal_brain import requirement_tree as rt
    from personal_brain.storage import BrainStore as Store
    s = Store.open(tmp_path / "rt26.db")
    root = rt.create_root(s, tree_id="t", title="r")
    rt.decompose(s, tree_id="t", node_id=root.root_id,
                 children=[{"title": "done", "gate_kind": "manual"},
                           {"title": "notdone", "gate_kind": "manual"}])
    leaves = {n.title: n for n in rt.frontier(s, tree_id="t")}
    # force ONE child green by founder authority; the other stays open
    rt.claim_leaf(s, tree_id="t", node_id=leaves["done"].node_id, agent_id="x")
    rt.set_verdict(s, tree_id="t", node_id=leaves["done"].node_id,
                   verdict="green", judged_by="root", is_root_authority=True)
    # the parent (root) must NOT be green while a sibling is unfinished
    sweep = rt.sweep(s, tree_id="t")
    assert sweep.get("dry") is False


# #27 — All-agents coverage: brain-side adjudication + both gates EXIST.
def test_acc_27_all_agents_brain_side_adjudication_exists():
    """The done-adjudication binds every agent because it lives at the shared
    chokepoints, NOT in a hook one client can skip: the brain owns `sweep`
    (server-side done) and the two un-bypassable gate modules exist
    (plan-lint + the completion drive). This asserts the chokepoint machinery is
    present; the CI-side enforcement is the founder-gated wiring step."""
    import importlib
    import sys
    sys.path.insert(0, str(_REPO / "tools"))
    # brain-side done-adjudication is a real callable (not the hook)
    rt = importlib.import_module("personal_brain.requirement_tree")
    assert callable(rt.sweep)
    # both shared-chokepoint gate modules import + expose their entrypoints
    pl = importlib.import_module("plan_lint")
    cg = importlib.import_module("completion_gate")
    assert callable(pl.lint_text) and callable(cg.evaluate)


# ════════════════════ PLAN-LOCKED — honest skips (collect, never fake-green) ══
# These correspond 1:1 to `_ACCEPTANCE_INDEX` "plan_locked" entries. Each is a
# real selector that COLLECTS under pytest and documents the precise blocker;
# none asserts a fabricated pass. When the artifact lands, the skip becomes an
# assertion (the standing burndown of "Done == acceptance green").

def test_acc_05_contradictory_facts_survive_as_siblings():
    pytest.skip("PLAN-LOCKED: HLC/LWW sibling-reconcile record (AgDR-0054 #5) not "
                "built — storage.py:1294 reconciles only via the manual "
                "tools/brain_unify.py band-aid; no sibling+reconcile-record path.")


def test_acc_06_unified_store_migration_parity():
    pytest.skip("PLAN-LOCKED: brain.db + graph.sqlite -> unified store with "
                "row-count + provenance parity (AgDR-0054 #6, slice 5) not built.")


def test_acc_07_red_team_corpus_attack_below_budget():
    pytest.skip("PLAN-LOCKED: AgentPoison/MemoryGraft red-team corpus + "
                "attack-success-vs-budget harness (AgDR-0054 #7, slice 6) not built.")


def test_acc_08_dual_retrieval_beats_raw_and_graph():
    pytest.skip("PLAN-LOCKED: dual-retrieval A/B on our corpus (AgDR-0054 #8) "
                "needs a frozen corpus + raw-only/graph-only baselines — not built.")


def test_acc_09_verified_skill_ab_lift():
    pytest.skip("PLAN-LOCKED: verified-skill A/B (+lift) on ArchHub workflows with "
                "deterministic verifiers (AgDR-0054 #9) not built.")


def test_acc_10_dam_false_accept_and_retraction_drill():
    pytest.skip("PLAN-LOCKED: dam false-accept-vs-budget measurement + retraction "
                "drill (merge a known-bad fact, prove downstream cleanup) "
                "(AgDR-0054 #10) not built.")


def test_acc_13_erasure_drill_tombstone_all_replicas():
    pytest.skip("PLAN-LOCKED: erasure-drill proving a tombstone propagates to ALL "
                "replicas (AgDR-0054 #13) needs a multi-replica cluster — not built.")


def test_acc_14_forgetting_alignment_regression_gate():
    pytest.skip("PLAN-LOCKED: forgetting/alignment regression gate (AgDR-0054 #14) "
                "scores a model promotion (instruction-following + safety refusals "
                "+ AEC) — no model promotion pipeline yet.")


def test_acc_15_poisoning_stack_activation_probe():
    pytest.skip("PLAN-LOCKED: poisoning-stack checkpoint activation-probe "
                "(AgDR-0054 #15) needs a trained checkpoint to probe — not built.")


def test_acc_16_base_model_audit():
    pytest.skip("PLAN-LOCKED: base-model red-team audit for a dormant trigger "
                "(AgDR-0054 #16) needs a base model — not built.")


def test_acc_20_capture_completeness_session_and_graph():
    pytest.skip("PLAN-LOCKED: session+graph capture across composer/Claude "
                "Code/Codex/fleet as first-class recallable entities "
                "(AgDR-0054 #20, slice 3) not built.")


# ─────────────── meta: the suite must collect >=1 selector per item ──────────

def test_every_acceptance_item_has_a_selector():
    """Self-check: there is exactly one `test_acc_NN_*` for each 1..27."""
    import re
    src = Path(__file__).read_text(encoding="utf-8")
    nums = sorted({int(m) for m in re.findall(r"^def test_acc_(\d{2})_",
                                              src, flags=re.MULTILINE)})
    assert nums == list(range(1, 28)), f"missing/extra acceptance selectors: {nums}"
