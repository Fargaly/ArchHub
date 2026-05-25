"""Reputation v2 — solves R4 (Bayesian shrinkage + decay + cold-start).

Replaces the linear `ratio * (0.7 + 0.2*volume) + 0.1*avg_quality` from
federation.py with:

  1. **Empirical Bayes Beta-Bernoulli posterior** — prior fit from
     cohort accept rates; new peers start near `mu_hat` not 0.3.
  2. **Time-decay** — exponential forgetting with 180-day half-life so
     stale silence doesn't get treated as live evidence.
  3. **Cold-start bootstrap** — identity (TLS-signed manifest) + inviter
     vouch + refundable stake side-channels boost score before history.
  4. **Multi-domain reputation** — separate Beta posteriors per pattern
     domain (revit, structural, contracts, …).
  5. **Sybil risk floor** — graph-anomaly score from invite topology;
     overrides high reputation when risk is high.

References:
  • Jøsang & Ismail — Beta Reputation System (2002)
  • Robinson — Empirical Bayes Baseball (2015)
  • Stein's Paradox / James-Stein shrinkage (Rochford)
  • TrustRank — Wu/Goel/Davison (2006)
  • EigenTrust — Kamvar et al. (2003)
  • BrightID — GroupSybilRank
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


# ─────────────────────── decayed Beta ──────────────────────────────────


def decay_factor(elapsed_seconds: float, half_life_seconds: float) -> float:
    """Multiplier for an observation that occurred `elapsed_seconds` ago,
    given a half-life. lambda^elapsed where lambda = 0.5^(1/half_life)."""
    if half_life_seconds <= 0:
        return 1.0
    return 0.5 ** (max(0.0, elapsed_seconds) / half_life_seconds)


@dataclass
class DecayedBeta:
    """Beta(α, β) posterior where every observation carries a timestamp
    and contributes a decayed weight. Use `effective_alpha/beta()` for
    the time-aware reading."""

    half_life_seconds: float = 180.0 * 86400.0  # 180 days

    # Each observation: (ts_seconds, x ∈ {0,1})
    observations: list[tuple[float, float]] = field(default_factory=list)

    # Prior pseudo-counts (decay-immune — they don't age)
    prior_alpha: float = 1.0
    prior_beta: float = 1.0

    def observe(self, retained: bool, *, ts: Optional[float] = None) -> None:
        self.observations.append(
            (ts if ts is not None else time.time(),
              1.0 if retained else 0.0)
        )

    def effective_alpha(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        s = self.prior_alpha
        for (t, x) in self.observations:
            if x > 0:
                s += decay_factor(now - t, self.half_life_seconds) * x
        return s

    def effective_beta(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        s = self.prior_beta
        for (t, x) in self.observations:
            if x < 1.0:
                s += decay_factor(now - t, self.half_life_seconds) * (1.0 - x)
        return s

    def posterior_mean(self, now: Optional[float] = None) -> float:
        a = self.effective_alpha(now)
        b = self.effective_beta(now)
        denom = a + b
        return a / denom if denom > 0 else 0.5

    def effective_sample_size(self, now: Optional[float] = None) -> float:
        a = self.effective_alpha(now)
        b = self.effective_beta(now)
        return max(0.0, a + b - (self.prior_alpha + self.prior_beta))


# ─────────────────────── empirical Bayes prior ─────────────────────────


def empirical_bayes_prior(
    cohort_accept_rates: list[tuple[float, float]],
    *,
    fallback_mean: float = 0.75,
    fallback_strength: float = 4.0,
) -> tuple[float, float]:
    """Method-of-moments Beta fit over a cohort of observed
    (accept_count, total_count) pairs. Returns (alpha_0, beta_0).

    Falls back to Beta(`fallback_mean*strength`, `(1-fallback_mean)*strength`)
    when the cohort is too small for stable moments (< 5 peers with > 0
    observations).
    """
    rates = []
    for (acc, total) in cohort_accept_rates:
        if total <= 0:
            continue
        rates.append(acc / total)

    if len(rates) < 5:
        # Cold-start fallback — generous, bounded
        return (fallback_mean * fallback_strength,
                (1.0 - fallback_mean) * fallback_strength)

    mu = sum(rates) / len(rates)
    var = sum((r - mu) ** 2 for r in rates) / len(rates)
    if var <= 0 or mu <= 0 or mu >= 1:
        return (fallback_mean * fallback_strength,
                (1.0 - fallback_mean) * fallback_strength)

    # Method-of-moments: alpha+beta = mu(1-mu)/var - 1
    nu = (mu * (1.0 - mu) / var) - 1.0
    if nu <= 0:
        return (fallback_mean * fallback_strength,
                (1.0 - fallback_mean) * fallback_strength)
    alpha_0 = mu * nu
    beta_0 = (1.0 - mu) * nu
    # Clamp to reasonable bounds (avoid degenerate priors). Upper bound
    # raised to 200 so tight cohorts (low variance) preserve their mean
    # rather than getting squished. Lower bound prevents Beta(0, ·).
    alpha_0 = max(0.5, min(200.0, alpha_0))
    beta_0 = max(0.5, min(200.0, beta_0))
    return (alpha_0, beta_0)


# ─────────────────────── multi-channel peer record ─────────────────────


@dataclass
class IdentityProof:
    """What identity proofs has the peer presented? Each contributes a
    bounded score in [0, 1] to the overall reputation."""

    domain_verified: bool = False  # TLS cert chain matches a public domain
    manifest_signed: bool = False  # peer manifest signed by recognised CA
    kyb_complete: bool = False     # business-verification (KYB) done

    def score(self) -> float:
        s = 0.0
        if self.domain_verified:
            s += 0.4
        if self.manifest_signed:
            s += 0.3
        if self.kyb_complete:
            s += 0.3
        return min(1.0, s)


@dataclass
class Vouch:
    """An inviter peer signed an introduction for this peer."""

    inviter_id: str
    inviter_score_at_invite: float  # snapshot of inviter rep at time of vouch
    ts: float = field(default_factory=time.time)


@dataclass
class Stake:
    """Refundable bond posted by the peer. Lost on confirmed malice;
    refunded after N successful patterns."""

    amount: float = 0.0
    posted_at: float = 0.0
    refunded: bool = False

    def score(self, *, min_stake: float = 100.0) -> float:
        if self.refunded or self.amount < min_stake:
            return 0.0
        return min(1.0, self.amount / (min_stake * 10.0))


@dataclass
class PeerV2:
    """Multi-dimensional reputation record. One per peer firm."""

    contributor_id: str
    domains: dict[str, DecayedBeta] = field(default_factory=dict)
    identity: IdentityProof = field(default_factory=IdentityProof)
    vouches: list[Vouch] = field(default_factory=list)
    stake: Stake = field(default_factory=Stake)
    avg_quality_score: float = 0.5  # 0..1 LLM-graded quality side-channel
    sybil_risk: float = 0.0  # 0..1; from graph-anomaly score
    first_seen: float = field(default_factory=time.time)

    def ensure_domain(self, domain: str, prior: tuple[float, float]) -> DecayedBeta:
        if domain not in self.domains:
            a, b = prior
            d = DecayedBeta()
            d.prior_alpha = a
            d.prior_beta = b
            self.domains[domain] = d
        return self.domains[domain]

    def observe(
        self,
        *,
        domain: str,
        retained: bool,
        prior: tuple[float, float],
        ts: Optional[float] = None,
    ) -> None:
        d = self.ensure_domain(domain, prior)
        d.observe(retained, ts=ts)

    def vouch_score(self) -> float:
        if not self.vouches:
            return 0.0
        # Strongest vouch wins; decay 0.5 / 365 days
        now = time.time()
        return max(
            v.inviter_score_at_invite
            * decay_factor(now - v.ts, 365.0 * 86400.0)
            for v in self.vouches
        )

    def reputation(
        self, *, domain: str, cohort_prior: tuple[float, float],
        now: Optional[float] = None,
    ) -> "ReputationView":
        d = self.ensure_domain(domain, cohort_prior)
        base = d.posterior_mean(now)
        ess = d.effective_sample_size(now)
        vouch = self.vouch_score()
        identity = self.identity.score()
        stake = self.stake.score()
        # Composite (matches scout recommendation):
        # 55% Bayesian + 20% vouch + 15% identity + 10% stake
        score = (
            0.55 * base
            + 0.20 * vouch
            + 0.15 * identity
            + 0.10 * stake
        )
        return ReputationView(
            contributor_id=self.contributor_id,
            domain=domain,
            score=score,
            base_posterior=base,
            effective_samples=ess,
            vouch_score=vouch,
            identity_score=identity,
            stake_score=stake,
            sybil_risk=self.sybil_risk,
            avg_quality_score=self.avg_quality_score,
        )


@dataclass
class ReputationView:
    """Per-decision snapshot — what the gate sees."""

    contributor_id: str
    domain: str
    score: float
    base_posterior: float
    effective_samples: float
    vouch_score: float
    identity_score: float
    stake_score: float
    sybil_risk: float
    avg_quality_score: float

    def explain(self) -> str:
        return (
            f"score={self.score:.3f} = "
            f"0.55·base({self.base_posterior:.3f}) + "
            f"0.20·vouch({self.vouch_score:.3f}) + "
            f"0.15·identity({self.identity_score:.3f}) + "
            f"0.10·stake({self.stake_score:.3f}); "
            f"ess={self.effective_samples:.1f}, sybil={self.sybil_risk:.2f}"
        )


# ─────────────────────── decision gates ────────────────────────────────


@dataclass
class DecisionConfig:
    accept_floor: float = 0.80
    quarantine_floor: float = 0.55
    rate_limited_floor: float = 0.30
    sybil_kill_floor: float = 0.50


@dataclass
class FederationDecision:
    action: str  # accept | quarantine | rate_limited | reject
    view: ReputationView
    reason: str = ""


def decide(
    view: ReputationView,
    *,
    cfg: Optional[DecisionConfig] = None,
) -> FederationDecision:
    cfg = cfg or DecisionConfig()
    if view.sybil_risk >= cfg.sybil_kill_floor:
        return FederationDecision(
            action="quarantine", view=view,
            reason=f"sybil risk {view.sybil_risk:.2f} ≥ {cfg.sybil_kill_floor}",
        )
    if view.score >= cfg.accept_floor:
        return FederationDecision(
            action="accept", view=view, reason="above accept floor",
        )
    if view.score >= cfg.quarantine_floor:
        return FederationDecision(
            action="quarantine", view=view, reason="above quarantine floor",
        )
    if view.score >= cfg.rate_limited_floor:
        return FederationDecision(
            action="rate_limited", view=view,
            reason="above rate-limited floor",
        )
    return FederationDecision(
        action="reject", view=view, reason="below all floors",
    )


# ─────────────────────── sybil floor ──────────────────────────────────


def compute_sybil_risk(
    *,
    peer_id: str,
    invite_graph: dict[str, list[str]],
    cluster_size_cap: int = 5,
) -> float:
    """Cheap heuristic — measure how clustered the peer is within a
    tight group of invites (potential Sybil farm).

    `invite_graph[peer_id]` = list of peers this peer invited or
    is invited by. Returns risk in [0, 1].
    """
    direct = set(invite_graph.get(peer_id, []))
    if not direct:
        return 0.0  # no info; trust upstream identity proofs
    # 2-hop neighbours
    two_hop: set[str] = set()
    for d in direct:
        two_hop.update(invite_graph.get(d, []))
    two_hop.discard(peer_id)
    # If the 2-hop community is small and dense, that's a red flag.
    community = direct | two_hop
    if len(community) <= cluster_size_cap:
        return min(1.0, 1.0 - len(community) / float(cluster_size_cap + 1))
    return 0.0


# ─────────────────────── helpers ──────────────────────────────────────


def contributor_hash(firm_id: str) -> str:
    """Stable 16-char hash for use in provenance + sybil graph."""
    return hashlib.sha256(firm_id.encode("utf-8")).hexdigest()[:16]
