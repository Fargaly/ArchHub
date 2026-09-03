"""Community federation tier — FICAL + DP-noise + ActivityPub discovery.

AgDR-0044 Slice 8 (founder pick F4.A — include in V1).

Cross-firm sharing without leaking proprietary data:

  1. **Local pattern compendium** — each firm computes a knowledge
     compendium summarising its memory graph as PATTERNS, not raw
     fragments (FICAL — arXiv 2412.08054).

  2. **Differential privacy noise** — Gaussian / Laplace noise added to
     pattern statistics before publication (FedMentor — arXiv 2509.14275).

  3. **Content-addressed publication** — patterns get a Merkle hash;
     consumers pull by hash. No raw text travels over the wire.

  4. **ActivityPub-style discovery** — each participating firm publishes
     a small outbox of pattern Activity records (Create / Update); peers
     subscribe and pull by hash. ([W3C ActivityPub])

  5. **Reputation gating** — incoming patterns weighted by contributor
     reputation (Wikidata-style — high reputation contributors auto-accept;
     low reputation queued for manual review).

This file ships the FOUR primitives in functional form. The ActivityPub
HTTP server itself is a thin separate concern; here we expose the inbox /
outbox data shapes so any HTTP framework can serve them.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .models import Skill, Fragment


# ─────────────────────── pattern compendium (FICAL) ────────────────────


@dataclass
class Pattern:
    """One pattern entry in a firm's compendium.

    A pattern is a STATISTIC over the firm's memory — e.g. "5 successful
    invocations of skill X across 3 distinct projects, average success
    rate 92%, top 3 trigger phrases [...]". Never the raw memory.
    """

    pattern_id: str  # content-addressed hash
    kind: str  # "skill_usage" | "tool_sequence" | "fact_distribution"
    summary: str  # short human-readable headline
    statistics: dict[str, Any] = field(default_factory=dict)
    contributor_firm: str = ""
    contributor_reputation: float = 0.5
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def derive_skill_usage_patterns(
    skills: Iterable[Skill],
    *,
    firm_id: str,
    min_success_count: int = 3,
) -> list[Pattern]:
    """Distill a firm's skill library into shareable usage patterns.

    Patterns are anonymous statistics: how many uses, success rate,
    trigger overlap. NEVER the skill body or examples (those would leak).
    """
    patterns: list[Pattern] = []
    for sk in skills:
        if sk.success_count < min_success_count:
            continue
        total = sk.success_count + sk.fail_count
        success_rate = sk.success_count / total if total else 0
        summary = (
            f"skill '{sk.name[:20]}' used {sk.success_count}× "
            f"({success_rate:.0%} success); requires_mcps={sorted(sk.requires_mcps)}"
        )
        statistics = {
            "name_prefix": sk.name.split("_", 1)[0],
            "success_count": sk.success_count,
            "success_rate": round(success_rate, 3),
            "trigger_count": len(sk.triggers),
            "trigger_topics": _topic_terms(sk.triggers + [sk.description])[:5],
            "requires_mcps": sorted(sk.requires_mcps),
            "side_effects": sk.side_effects,
            "honed_passed": sk.honed_passed,
            "honed_trials": sk.honed_trials,
        }
        pat_id = _hash_pattern("skill_usage", firm_id, sk.name, statistics)
        patterns.append(Pattern(
            pattern_id=pat_id,
            kind="skill_usage",
            summary=summary,
            statistics=statistics,
            contributor_firm=firm_id,
        ))
    return patterns


def derive_tool_sequence_patterns(
    traces: Iterable[dict[str, Any]],
    *,
    firm_id: str,
    min_occurrences: int = 3,
) -> list[Pattern]:
    """Find frequently-co-occurring tool sequences across a firm's
    traces. Anonymous bigrams + trigrams over tool-name space."""
    bigrams: Counter[tuple[str, ...]] = Counter()
    for trace in traces:
        tool_calls = trace.get("tool_calls", []) or []
        names = [tc.get("name", "?") for tc in tool_calls
                  if tc.get("status") == "ok"]
        for i in range(len(names) - 1):
            bigrams[(names[i], names[i + 1])] += 1

    patterns: list[Pattern] = []
    for (a, b), count in bigrams.most_common():
        if count < min_occurrences:
            continue
        summary = f"sequence '{a} → {b}' seen {count}×"
        statistics = {"a": a, "b": b, "count": count}
        pat_id = _hash_pattern("tool_sequence", firm_id, a, b, str(count))
        patterns.append(Pattern(
            pattern_id=pat_id,
            kind="tool_sequence",
            summary=summary,
            statistics=statistics,
            contributor_firm=firm_id,
        ))
    return patterns


def _topic_terms(strings: Iterable[str]) -> list[str]:
    """Crude bag-of-words signal. Returns most-frequent non-stopword
    tokens for use as pattern statistics."""
    import re
    stop = frozenset({"the", "a", "an", "and", "or", "of", "to", "in", "on",
                       "for", "with", "this", "that"})
    c: Counter[str] = Counter()
    for s in strings:
        for tok in re.findall(r"[A-Za-z]{3,}", str(s)):
            t = tok.lower()
            if t not in stop:
                c[t] += 1
    return [t for t, _ in c.most_common(10)]


def _hash_pattern(*parts: str | dict[str, Any]) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, dict):
            h.update(json.dumps(p, sort_keys=True, default=str).encode("utf-8"))
        else:
            h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


# ─────────────────────── differential privacy ──────────────────────────


def add_dp_noise(
    value: float,
    *,
    sensitivity: float = 1.0,
    epsilon: float = 1.0,
    mechanism: str = "laplace",
) -> float:
    """Add calibrated noise to a single statistic (ε-DP).

    Laplace mechanism (default): noise ~ Lap(sensitivity/epsilon).
    Gaussian mechanism: noise ~ N(0, (sensitivity·σ/epsilon)²); requires
    (ε, δ)-DP — for personal-brain use, Laplace suffices.

    `sensitivity` is the maximum change in the statistic caused by adding
    or removing one record (Δf in the DP literature). For counts: 1.
    For success rates: 1/n.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    scale = sensitivity / epsilon
    if mechanism == "laplace":
        # u ~ Uniform(-0.5, 0.5) → noise = -scale · sign(u) · ln(1 - 2|u|)
        u = random.uniform(-0.5, 0.5)
        noise = -scale * math.copysign(1.0, u) * math.log(1 - 2 * abs(u))
    elif mechanism == "gaussian":
        # Simple Gaussian — see Dwork & Roth Algorithm 1
        sigma = scale * 1.5  # approx for ε,δ=1e-5
        noise = random.gauss(0.0, sigma)
    else:
        raise ValueError(f"unknown mechanism: {mechanism}")
    return value + noise


def noise_pattern_statistics(
    pattern: Pattern,
    *,
    epsilon: float = 1.0,
    seed: Optional[int] = None,
) -> Pattern:
    """Apply DP noise to a pattern's numeric statistics. Returns a NEW
    pattern with noised values; original untouched. Pattern_id is
    recomputed since the data changed."""
    if seed is not None:
        random.seed(seed)
    new_stats = dict(pattern.statistics)
    for key, value in pattern.statistics.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        sensitivity = 1.0
        if "rate" in key or "ratio" in key:
            sensitivity = 0.1  # ratios are bounded → lower sensitivity
        new_stats[key] = max(0.0, add_dp_noise(
            float(value), sensitivity=sensitivity, epsilon=epsilon,
        ))
    return Pattern(
        pattern_id=_hash_pattern(pattern.kind, pattern.contributor_firm,
                                  pattern.summary, new_stats),
        kind=pattern.kind,
        summary=pattern.summary,
        statistics=new_stats,
        contributor_firm=pattern.contributor_firm,
        contributor_reputation=pattern.contributor_reputation,
        created_at=pattern.created_at,
    )


# ─────────────────────── ActivityPub outbox / inbox ────────────────────


@dataclass
class ActivityRecord:
    """One ActivityPub-shaped record for federation discovery."""

    id: str  # URL-shaped — `https://firm.example/patterns/<hash>`
    type: str = "Create"  # Create / Update / Delete
    actor: str = ""  # `https://firm.example/actor`
    object: dict[str, Any] = field(default_factory=dict)
    published: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_jsonld(self) -> dict[str, Any]:
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": self.id,
            "type": self.type,
            "actor": self.actor,
            "object": self.object,
            "published": self.published,
        }


def pattern_to_activity(
    pattern: Pattern, *, actor_url: str, base_url: str,
) -> ActivityRecord:
    """Wrap a pattern into an ActivityPub Create activity."""
    return ActivityRecord(
        id=f"{base_url.rstrip('/')}/patterns/{pattern.pattern_id}",
        type="Create",
        actor=actor_url,
        object={
            "type": "BrainPattern",
            "pattern_id": pattern.pattern_id,
            "kind": pattern.kind,
            "summary": pattern.summary,
            "statistics": pattern.statistics,
            "contributor_firm_hash": hashlib.sha256(
                pattern.contributor_firm.encode("utf-8")
            ).hexdigest()[:16],
        },
    )


@dataclass
class Outbox:
    """Per-firm publication outbox. Append-only. Peers GET this and
    discover new patterns by pulling each."""

    actor_url: str
    base_url: str
    activities: list[ActivityRecord] = field(default_factory=list)

    def publish(self, pattern: Pattern) -> ActivityRecord:
        activity = pattern_to_activity(
            pattern, actor_url=self.actor_url, base_url=self.base_url,
        )
        self.activities.append(activity)
        return activity

    def to_jsonld(self) -> dict[str, Any]:
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{self.base_url}/outbox",
            "type": "OrderedCollection",
            "totalItems": len(self.activities),
            "orderedItems": [a.to_jsonld() for a in self.activities],
        }


# ─────────────────────── reputation gating ─────────────────────────────


@dataclass
class ContributorReputation:
    """Tracked per contributor (firm). Patterns from high-rep firms get
    auto-accepted; low-rep go to a manual-review queue."""

    contributor_id: str  # firm hash
    accepted_count: int = 0
    rejected_count: int = 0
    quarantine_count: int = 0
    avg_quality_score: float = 0.5

    @property
    def score(self) -> float:
        """Wikidata-inspired weighted score in [0, 1].

        Volume bonus is multiplicative on ratio (not additive) so that a
        contributor with 1/50 success doesn't get a free reputation boost
        from having merely participated a lot.
        """
        total = self.accepted_count + self.rejected_count
        if total == 0:
            return 0.3  # fresh contributor — gentle prior
        ratio = self.accepted_count / total
        # Volume bonus, capped — multiplies ratio so poor performers
        # don't accumulate reputation just by trying many times.
        volume = min(math.log(1 + total) / math.log(50), 1.0)
        return ratio * (0.7 + 0.2 * volume) + 0.1 * self.avg_quality_score


@dataclass
class ImportDecision:
    """Result of evaluating an incoming pattern for import."""

    accept: bool
    reason: str = ""
    quarantine: bool = False
    weighted_value: float = 0.0


def evaluate_incoming_pattern(
    pattern: Pattern,
    *,
    contributor_rep: ContributorReputation,
    auto_accept_floor: float = 0.7,
    reject_floor: float = 0.1,
    peer_v2: Optional[Any] = None,
    cohort_prior: Optional[tuple[float, float]] = None,
) -> ImportDecision:
    """Decide whether to import a pattern based on contributor reputation.

    Upgraded per AgDR-0044 R4 push: when a `PeerV2` is passed alongside the
    legacy `ContributorReputation`, the decision uses Bayesian shrinkage
    + time-decay + multi-channel composite score from `reputation.py`. The
    legacy linear-blend path stays as a fallback for callers that haven't
    migrated to PeerV2 yet.

      score ≥ auto_accept_floor → accept
      reject_floor ≤ score < auto_accept_floor → quarantine for review
      score < reject_floor → reject
    """
    # R4 — preferred path: use PeerV2 + reputation.decide()
    if peer_v2 is not None:
        try:
            from .reputation import (  # local import to avoid cycle
                DecisionConfig, decide as _decide_rep,
            )
            prior = cohort_prior or (6.0, 2.0)
            view = peer_v2.reputation(domain=pattern.kind, cohort_prior=prior)
            rep_cfg = DecisionConfig(
                accept_floor=auto_accept_floor,
                quarantine_floor=max(reject_floor, 0.55),
                rate_limited_floor=reject_floor,
                sybil_kill_floor=0.50,
            )
            d = _decide_rep(view, cfg=rep_cfg)
            return ImportDecision(
                accept=(d.action == "accept"),
                quarantine=(d.action in ("quarantine", "rate_limited")),
                reason=f"R4 score={view.score:.3f} action={d.action} ({d.reason})",
                weighted_value=view.score,
            )
        except Exception as ex:
            # Reputation v2 path failed — fall through to legacy scoring
            pass

    # Legacy linear-blend path (kept for tests + back-compat)
    score = contributor_rep.score
    if score >= auto_accept_floor:
        return ImportDecision(
            accept=True,
            reason=f"contributor reputation {score:.2f} ≥ {auto_accept_floor}",
            weighted_value=score,
        )
    if score >= reject_floor:
        return ImportDecision(
            accept=False,
            quarantine=True,
            reason=f"contributor reputation {score:.2f} — quarantine for review",
            weighted_value=score,
        )
    return ImportDecision(
        accept=False,
        quarantine=False,
        reason=f"contributor reputation {score:.2f} < {reject_floor} — rejected",
        weighted_value=score,
    )


# ─────────────────────── inbox driver ──────────────────────────────────


@dataclass
class FederationDriver:
    """Glues the four primitives together.

    Per-firm flow:
      1. compendium = derive_skill_usage_patterns(local_skills) +
                       derive_tool_sequence_patterns(local_traces)
      2. compendium = [noise_pattern_statistics(p, epsilon=1.0) for p in compendium]
      3. outbox.publish(p) for each p
      4. peers fetch outbox.to_jsonld()
      5. on receive: evaluate_incoming_pattern(p, contributor_rep) → import / quarantine / reject
    """

    firm_id: str
    actor_url: str
    base_url: str
    epsilon: float = 1.0

    def derive_and_publish(
        self,
        skills: Iterable[Skill],
        traces: Optional[Iterable[dict[str, Any]]] = None,
    ) -> Outbox:
        outbox = Outbox(actor_url=self.actor_url, base_url=self.base_url)
        patterns: list[Pattern] = []
        patterns.extend(derive_skill_usage_patterns(skills, firm_id=self.firm_id))
        if traces is not None:
            patterns.extend(derive_tool_sequence_patterns(traces, firm_id=self.firm_id))
        for p in patterns:
            noised = noise_pattern_statistics(p, epsilon=self.epsilon)
            outbox.publish(noised)
        return outbox

    def receive(
        self,
        incoming_activity: dict[str, Any],
        *,
        reputation: ContributorReputation,
    ) -> ImportDecision:
        obj = incoming_activity.get("object", {})
        pattern = Pattern(
            pattern_id=obj.get("pattern_id", ""),
            kind=obj.get("kind", ""),
            summary=obj.get("summary", ""),
            statistics=obj.get("statistics", {}),
            contributor_firm=obj.get("contributor_firm_hash", ""),
        )
        return evaluate_incoming_pattern(pattern, contributor_rep=reputation)
