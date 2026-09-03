"""Tests for the 4 risk-mitigation modules:
  R1 — calibration.py     Beta-Bernoulli LCB + streaming quantile + CUSUM
  R2 — exploration.py     Diversity + variance gate + DPP + library health
  R3 — liveness.py        Circuit breaker + write journal + watchdog
  R4 — reputation.py      Empirical-Bayes Beta + decay + multi-domain + sybil
"""
from __future__ import annotations

import time

import pytest

# ─── R1 ─────────────────────────────────────────────────────────────────


def test_beta_ppf_basic_quantiles():
    from personal_brain.calibration import beta_ppf
    # Beta(1,1) is uniform → ppf(q) ≈ q
    assert abs(beta_ppf(0.5, 1, 1) - 0.5) < 0.01
    assert abs(beta_ppf(0.1, 1, 1) - 0.1) < 0.02
    # Beta(10,2) — heavy near 1
    high = beta_ppf(0.5, 10, 2)
    assert 0.7 < high < 0.95


def test_calibration_warmup_uses_permissive_floors():
    from personal_brain.calibration import CalibrationState
    st = CalibrationState()
    # Day-1: warm thresholds (0.50 success, 0.05 novelty)
    assert st.success_floor() == 0.50
    assert st.novelty_floor() == 0.05
    accepted, _, _, _ = st.decide(novelty=0.10, success_score=0.55)
    assert accepted


def test_calibration_tightens_after_observations():
    from personal_brain.calibration import CalibrationState
    st = CalibrationState(min_mints_before_strict=10)
    # Feed 30 retained outcomes → posterior tightens around high success
    for _ in range(30):
        st.record_outcome(retained=True)
    sf = st.success_floor()
    # LCB at 10% of Beta(31,1) is high — at least 0.85 clamped (we clamp at 0.85)
    assert sf >= 0.80


def test_calibration_cusum_fires_on_drift_drop():
    from personal_brain.calibration import CalibrationState
    st = CalibrationState(min_mints_before_strict=10)
    # Establish good baseline
    for _ in range(50):
        st.record_outcome(retained=True)
    # Sudden drop — CUSUM should fire eventually
    fired = False
    for _ in range(30):
        if st.record_outcome(retained=False):
            fired = True
            break
    assert fired or st.drifts_detected > 0


def test_calibration_novelty_floor_tracks_quantile():
    from personal_brain.calibration import CalibrationState
    st = CalibrationState()
    # Fill window with values 0..1
    for v in [i / 99.0 for i in range(100)]:
        st.record_proposal(v)
    # Top-30% means cut at 0.70
    nf = st.novelty_floor()
    assert 0.60 < nf < 0.80


def test_calibration_persistence_roundtrip(tmp_path):
    from personal_brain.calibration import CalibrationState
    st = CalibrationState()
    for _ in range(5):
        st.record_outcome(retained=True)
    p = tmp_path / "calib.json"
    st.save(p)
    st2 = CalibrationState.load(p)
    assert abs(st2.alpha - st.alpha) < 1e-6
    assert abs(st2.beta - st.beta) < 1e-6


# ─── R2 ─────────────────────────────────────────────────────────────────


def _vec(*xs):
    return list(xs)


def test_diversity_refuses_when_too_close():
    from personal_brain.exploration import check_diversity, DiversityCheck
    existing = [("a", _vec(1.0, 0.0, 0.0)), ("b", _vec(0.0, 1.0, 0.0))]
    # cosine to "a" is ~0.93 — between refuse (0.92) and merge (0.97)
    decision = check_diversity(
        _vec(0.93, 0.37, 0.0), existing,
        cfg=DiversityCheck(refuse_threshold=0.92, merge_threshold=0.97),
    )
    assert decision.action == "refuse_redundant"


def test_diversity_merges_when_near_identical():
    from personal_brain.exploration import check_diversity, DiversityCheck
    existing = [("a", _vec(1.0, 0.0))]
    decision = check_diversity(
        _vec(0.999, 0.001), existing,
        cfg=DiversityCheck(refuse_threshold=0.92, merge_threshold=0.97),
    )
    assert decision.action == "merge"


def test_diversity_accepts_distinct():
    from personal_brain.exploration import check_diversity
    existing = [("a", _vec(1.0, 0.0))]
    decision = check_diversity(_vec(0.0, 1.0), existing)
    assert decision.action == "accept"


def test_variance_gate_collapses_after_consistent_high_rewards():
    from personal_brain.exploration import VarianceGate
    vg = VarianceGate(window_size=10, ratio=0.5)
    # Build up max std via high variance
    for r in [0.0, 1.0, 0.0, 1.0, 0.5, 0.9, 0.1, 0.7, 0.2, 0.8]:
        vg.observe("c1", r)
    assert vg._windows["c1"].max_std_seen > 0.3
    # Now feed steady stream → variance crashes
    for _ in range(10):
        vg.observe("c1", 1.0)
    assert vg.is_collapsed("c1")


def test_dpp_gain_higher_when_diverse():
    from personal_brain.exploration import dpp_log_marginal_gain
    existing = [_vec(1.0, 0.0)]
    redundant = dpp_log_marginal_gain(_vec(1.0, 0.01), existing, quality=1.0)
    diverse = dpp_log_marginal_gain(_vec(0.0, 1.0), existing, quality=1.0)
    assert diverse > redundant


def test_inverse_frequency_replay_prefers_low_use():
    from personal_brain.exploration import sample_inverse_frequency
    import random
    items = [
        {"id": "rare", "retrieval_count": 1},
        {"id": "common", "retrieval_count": 100},
    ]
    rng = random.Random(42)
    counts = {"rare": 0, "common": 0}
    for _ in range(500):
        picked = sample_inverse_frequency(items, k=1, rng=rng)[0]
        counts[picked["id"]] += 1
    assert counts["rare"] > counts["common"]


def test_library_health_detects_concentration():
    from personal_brain.exploration import measure_health
    # 10 nearly-identical skill vectors → high gini, low cluster count
    base = _vec(1.0, 0.0, 0.0)
    vectors = {f"sk-{i}": _vec(1.0, 0.01 * i, 0.0) for i in range(10)}
    h = measure_health(vectors, similarity_threshold=0.95)
    assert h.skill_count == 10
    assert h.cluster_count <= 2
    assert h.concentrated or h.pairwise_cosine_mean > 0.9


def test_library_health_passes_diverse():
    from personal_brain.exploration import measure_health
    # 8 orthogonal-ish vectors
    vectors = {f"sk-{i}": [1.0 if i == j else 0.0 for j in range(8)]
                for i in range(8)}
    h = measure_health(vectors)
    assert h.pairwise_cosine_mean < 0.4
    assert h.cluster_count >= 4


def test_echo_trap_decide_refuses_redundant():
    from personal_brain.exploration import echo_trap_decide
    existing = {"a": _vec(1.0, 0.0)}
    d = echo_trap_decide(
        candidate_vec=_vec(0.99, 0.0), candidate_quality=0.9,
        existing_vecs=existing, library_size=1,
    )
    assert not d.accept
    assert "cosine" in d.reason


def test_echo_trap_decide_accepts_diverse_quality_skill():
    from personal_brain.exploration import echo_trap_decide
    existing = {"a": _vec(1.0, 0.0)}
    d = echo_trap_decide(
        candidate_vec=_vec(0.0, 1.0), candidate_quality=0.9,
        existing_vecs=existing, library_size=1,
    )
    assert d.accept


# ─── R3 ─────────────────────────────────────────────────────────────────


def test_circuit_breaker_trips_on_hard_failure():
    from personal_brain.liveness import CircuitBreaker, BreakerConfig, BreakerOpen
    states_seen = []
    def on_status(state, details): states_seen.append(state)
    br = CircuitBreaker(
        config=BreakerConfig(threshold=3, hard_fail_trip=True),
        on_status=on_status,
    )

    def fail(): raise ConnectionRefusedError("daemon down")

    with pytest.raises(ConnectionRefusedError):
        br.call(fail)
    # Hard fail trips on first failure
    assert br.state == "open"
    # Next call blocked
    with pytest.raises(BreakerOpen):
        br.call(lambda: 1)


def test_circuit_breaker_soft_failures_threshold():
    from personal_brain.liveness import CircuitBreaker, BreakerConfig
    br = CircuitBreaker(config=BreakerConfig(threshold=3, hard_fail_trip=False))
    def soft_fail(): raise TimeoutError("slow")
    for _ in range(2):
        with pytest.raises(TimeoutError):
            br.call(soft_fail)
    # Still closed after 2
    assert br.state == "closed"
    with pytest.raises(TimeoutError):
        br.call(soft_fail)
    # Now open
    assert br.state == "open"


def test_circuit_breaker_recovers_on_half_open_success():
    from personal_brain.liveness import CircuitBreaker, BreakerConfig
    br = CircuitBreaker(
        config=BreakerConfig(threshold=1, reset_timeout_s=0.05),
    )
    def fail(): raise ConnectionRefusedError("x")
    with pytest.raises(ConnectionRefusedError):
        br.call(fail)
    assert br.state == "open"
    time.sleep(0.1)  # past reset timeout
    # First call goes to half_open then closes on success
    assert br.call(lambda: 42) == 42
    assert br.state == "closed"


def test_write_journal_append_and_drain(tmp_path):
    from personal_brain.liveness import WriteJournal
    j = WriteJournal(tmp_path / "journal.ndjson")
    j.append({"op": "add", "id": "f1"})
    j.append({"op": "add", "id": "f2"})
    assert j.pending_count() == 2
    drained = j.drain()
    assert len(drained) == 2
    assert drained[0]["id"] == "f1"
    assert j.pending_count() == 0


def test_resilient_brain_client_journals_when_breaker_open(tmp_path):
    from personal_brain.liveness import (
        BreakerConfig, ResilientBrainClient,
    )

    class FailingClient:
        def write(self, ops): raise ConnectionRefusedError("down")
        def context(self, *a, **k): raise ConnectionRefusedError("down")
        def skill_mint(self, *a, **k): raise ConnectionRefusedError("down")
        def wiring_announce(self, *a, **k): raise ConnectionRefusedError("down")

    client = ResilientBrainClient(
        FailingClient(),
        journal_path=tmp_path / "j.ndjson",
        breaker_config=BreakerConfig(threshold=1, hard_fail_trip=True),
    )
    resp = client.write([{"op": "add", "id": "f1"}])
    # First write: journal is appended FIRST, then network attempt fails.
    # Breaker then trips, but the journal already has the write.
    assert client.journal.pending_count() >= 1
    # Second call: breaker open → journaled, no network attempt
    resp2 = client.write([{"op": "add", "id": "f2"}])
    assert resp2["ops_applied"] == 0
    assert resp2["journal_pending"] >= 2


def test_resilient_client_replay_journal_on_recovery(tmp_path):
    from personal_brain.liveness import (
        BreakerConfig, ResilientBrainClient,
    )

    class TogglingClient:
        def __init__(self): self.failing = True; self.written = []
        def write(self, ops):
            if self.failing: raise ConnectionRefusedError("down")
            self.written.extend(ops); return {"ops_applied": len(ops)}
        def context(self, *a, **k): raise ConnectionRefusedError("down")
        def skill_mint(self, *a, **k): raise ConnectionRefusedError("down")
        def wiring_announce(self, *a, **k): raise ConnectionRefusedError("down")

    inner = TogglingClient()
    client = ResilientBrainClient(
        inner, journal_path=tmp_path / "j.ndjson",
        breaker_config=BreakerConfig(threshold=1, hard_fail_trip=True,
                                      reset_timeout_s=0.01),
    )
    client.write([{"op": "add", "id": "f1"}])
    client.write([{"op": "add", "id": "f2"}])
    assert client.journal.pending_count() >= 2

    # Recover
    inner.failing = False
    time.sleep(0.05)
    replayed = client.replay_journal()
    assert replayed >= 2
    assert len(inner.written) >= 2
    assert client.journal.pending_count() == 0


# ─── R4 ─────────────────────────────────────────────────────────────────


def test_decay_factor_half_life():
    from personal_brain.reputation import decay_factor
    # At 1 half-life, factor should be 0.5
    assert abs(decay_factor(180.0, 180.0) - 0.5) < 1e-6
    # At 2 half-lives, 0.25
    assert abs(decay_factor(360.0, 180.0) - 0.25) < 1e-6
    # At 0, factor=1
    assert decay_factor(0.0, 180.0) == 1.0


def test_decayed_beta_posterior_mean_starts_at_prior():
    from personal_brain.reputation import DecayedBeta
    d = DecayedBeta(prior_alpha=3.0, prior_beta=1.0)
    # No observations → 0.75
    assert abs(d.posterior_mean() - 0.75) < 1e-6


def test_decayed_beta_decays_old_observations():
    from personal_brain.reputation import DecayedBeta
    d = DecayedBeta(half_life_seconds=10.0)
    now = time.time()
    # 50 successes a long time ago → should decay to near prior
    for _ in range(50):
        d.observe(True, ts=now - 1000.0)  # 100 half-lives ago
    # Effective alpha should be ~prior_alpha
    assert d.effective_alpha(now) < 2.0


def test_empirical_bayes_prior_fits_high_acceptance_cohort():
    from personal_brain.reputation import empirical_bayes_prior
    # Cohort of peers with ~80% acceptance
    cohort = [(80, 100), (75, 100), (85, 100), (78, 100), (82, 100), (79, 100)]
    a0, b0 = empirical_bayes_prior(cohort)
    mu = a0 / (a0 + b0)
    assert 0.75 < mu < 0.85


def test_empirical_bayes_falls_back_when_cohort_small():
    from personal_brain.reputation import empirical_bayes_prior
    a0, b0 = empirical_bayes_prior([])  # empty cohort
    mu = a0 / (a0 + b0)
    assert 0.7 < mu < 0.8


def test_peer_v2_new_peer_lands_near_cohort_mean():
    from personal_brain.reputation import PeerV2
    p = PeerV2(contributor_id="new-peer")
    view = p.reputation(domain="revit", cohort_prior=(6.0, 2.0))  # mu=0.75
    # No history yet — score reflects identity (0) + vouch (0) + stake (0)
    # + 0.55 * 0.75 = 0.4125
    assert 0.40 < view.score < 0.45


def test_peer_v2_with_full_identity_and_vouch():
    from personal_brain.reputation import IdentityProof, PeerV2, Stake, Vouch
    p = PeerV2(
        contributor_id="vouched-peer",
        identity=IdentityProof(domain_verified=True, manifest_signed=True,
                                kyb_complete=True),
        vouches=[Vouch(inviter_id="trusted", inviter_score_at_invite=0.9)],
        stake=Stake(amount=1000.0, posted_at=time.time()),
    )
    view = p.reputation(domain="revit", cohort_prior=(6.0, 2.0))
    # 0.55*0.75 + 0.20*0.9 + 0.15*1.0 + 0.10*1.0
    # = 0.4125 + 0.18 + 0.15 + 0.10 = 0.84 → above accept floor 0.80
    assert view.score > 0.80


def test_peer_v2_decays_after_long_silence():
    from personal_brain.reputation import PeerV2
    p = PeerV2(contributor_id="old-peer")
    # 30 successes 500 days ago (half-life 180d → ~5% remaining)
    old_ts = time.time() - 500 * 86400.0
    for _ in range(30):
        p.observe(domain="revit", retained=True, prior=(6.0, 2.0), ts=old_ts)
    view = p.reputation(domain="revit", cohort_prior=(6.0, 2.0))
    # Posterior should drift back toward prior mean (~0.75) — not stay at 1.0
    assert view.base_posterior < 0.85


def test_sybil_risk_high_for_small_dense_community():
    from personal_brain.reputation import compute_sybil_risk
    graph = {
        "x": ["y", "z"],
        "y": ["x", "z"],
        "z": ["x", "y"],
    }
    risk = compute_sybil_risk(peer_id="x", invite_graph=graph,
                               cluster_size_cap=5)
    assert risk > 0.0


def test_sybil_risk_low_for_diffuse_community():
    from personal_brain.reputation import compute_sybil_risk
    graph = {
        "x": ["y1", "y2", "y3", "y4", "y5", "y6"],
    }
    # 2-hop is sparse (only direct + their nothing) → 6 ≤ cap 5? actually
    # direct = 6 invites; 2-hop = 0 → community = 6, > cluster_size_cap=5
    risk = compute_sybil_risk(peer_id="x", invite_graph=graph,
                               cluster_size_cap=5)
    assert risk == 0.0


def test_federation_decide_accept_quarantine_reject():
    from personal_brain.reputation import (
        DecisionConfig, ReputationView, decide,
    )
    high = ReputationView(
        contributor_id="x", domain="r", score=0.85, base_posterior=0.8,
        effective_samples=10, vouch_score=0.5, identity_score=0.5,
        stake_score=0.2, sybil_risk=0.0, avg_quality_score=0.7,
    )
    assert decide(high).action == "accept"

    medium = ReputationView(
        contributor_id="x", domain="r", score=0.60, base_posterior=0.6,
        effective_samples=5, vouch_score=0.1, identity_score=0.3,
        stake_score=0.0, sybil_risk=0.0, avg_quality_score=0.5,
    )
    assert decide(medium).action == "quarantine"

    low = ReputationView(
        contributor_id="x", domain="r", score=0.10, base_posterior=0.1,
        effective_samples=10, vouch_score=0.0, identity_score=0.0,
        stake_score=0.0, sybil_risk=0.0, avg_quality_score=0.0,
    )
    assert decide(low).action == "reject"


def test_federation_decide_sybil_kill_overrides_high_score():
    from personal_brain.reputation import ReputationView, decide
    suspicious = ReputationView(
        contributor_id="x", domain="r", score=0.95,
        base_posterior=0.9, effective_samples=50,
        vouch_score=0.9, identity_score=0.9, stake_score=0.9,
        sybil_risk=0.8,  # high!
        avg_quality_score=0.9,
    )
    assert decide(suspicious).action == "quarantine"
