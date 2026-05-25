"""Echo Trap mitigation — solves R2.

Defends the auto-skill library against reward-variance collapse and
attractor convergence by layering five mechanisms:

  1. **Diversity floor (Voyager-pattern)** — refuse mint when cosine to
     nearest neighbour > 0.92; auto-merge when > 0.97.
  2. **Variance gate (RAGEN-pattern)** — refuse mint from a cluster
     whose reward variance has collapsed below 50% of recent peak.
  3. **DPP marginal gain (ODPP-pattern)** — quality and diversity in one
     score via log-det of the kernel.
  4. **Inverse-frequency replay (Schapiro-pattern)** — when surfacing
     trace candidates for re-reflection, sample by 1/(1+retrievals) so
     weakly-used skills get attention.
  5. **Library health metrics** — embedding-Gini, cluster count,
     coverage radius, reward-std. Trigger alerts when concentrated.

References:
  • RAGEN — Self-Evolution in LLM Agents (arXiv 2504.20073)
  • SAGE — Skill Library RL (arXiv 2512.17102)
  • Voyager — Open-Ended Embodied Agent (arXiv 2305.16291)
  • Reflexion — Verbal Self-Reflection (arXiv 2303.11366)
  • ODPP — DPP for Skill Discovery (arXiv 2212.00211)
  • Schapiro et al. — Hippocampal replay prioritises weakly-learned (2018)
"""
from __future__ import annotations

import math
import random
from collections import Counter, deque
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any, Iterable, Optional, Sequence


# ─────────────────────── reusable cosine ───────────────────────────────


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    return dot / denom if denom else 0.0


# ─────────────────────── 1. diversity floor ────────────────────────────


@dataclass
class DiversityCheck:
    """Voyager-pattern: refuse mint when candidate too similar to an
    existing skill. Threshold tuned to 0.92 (refuse) / 0.97 (merge)."""

    refuse_threshold: float = 0.92
    merge_threshold: float = 0.97


@dataclass
class DiversityDecision:
    action: str  # "accept" | "refuse_redundant" | "merge"
    nearest_id: Optional[str] = None
    max_cosine: float = 0.0
    reason: str = ""


def check_diversity(
    candidate_vec: Sequence[float],
    existing: Iterable[tuple[str, Sequence[float]]],
    *,
    cfg: Optional[DiversityCheck] = None,
) -> DiversityDecision:
    cfg = cfg or DiversityCheck()
    best_id: Optional[str] = None
    best_cos = 0.0
    for skill_id, vec in existing:
        cos = cosine(candidate_vec, vec)
        if cos > best_cos:
            best_cos = cos
            best_id = skill_id
    if best_cos >= cfg.merge_threshold:
        return DiversityDecision(
            action="merge", nearest_id=best_id, max_cosine=best_cos,
            reason=f"cosine={best_cos:.3f} ≥ merge {cfg.merge_threshold}",
        )
    if best_cos >= cfg.refuse_threshold:
        return DiversityDecision(
            action="refuse_redundant", nearest_id=best_id,
            max_cosine=best_cos,
            reason=f"cosine={best_cos:.3f} ≥ refuse {cfg.refuse_threshold}",
        )
    return DiversityDecision(
        action="accept", nearest_id=best_id, max_cosine=best_cos,
        reason="below redundancy floor",
    )


# ─────────────────────── 2. variance gate ──────────────────────────────


@dataclass
class ClusterRewardWindow:
    """Tracks reward std per cluster over a rolling window. RAGEN's
    "variance collapse" canary."""

    window_size: int = 32
    rewards: deque = field(default_factory=lambda: deque())
    max_std_seen: float = 0.0

    def __post_init__(self):
        # Rebuild deque with the actual window_size (dataclass default
        # captured 32 before window_size was overridden by caller).
        if self.rewards.maxlen != self.window_size:
            self.rewards = deque(self.rewards, maxlen=self.window_size)

    def observe(self, reward: float) -> None:
        self.rewards.append(float(reward))
        if len(self.rewards) >= 2:
            cur = pstdev(self.rewards)
            if cur > self.max_std_seen:
                self.max_std_seen = cur

    @property
    def current_std(self) -> float:
        if len(self.rewards) < 2:
            return 0.0
        return pstdev(self.rewards)

    def collapsed(self, *, ratio: float = 0.5) -> bool:
        """True iff the current reward std has fallen below `ratio` of
        the historical max for this cluster. Default 0.5 per RAGEN."""
        if self.max_std_seen < 0.1:
            return False  # need a baseline before declaring collapse
        return self.current_std < ratio * self.max_std_seen


class VarianceGate:
    """Per-cluster variance tracker. Cluster keys can be skill_id, MCP
    prefix, tool-sequence hash — whatever groups "similar trajectories"
    in the founder's reflexion pipeline."""

    def __init__(self, *, window_size: int = 32, ratio: float = 0.5):
        self._windows: dict[str, ClusterRewardWindow] = {}
        self._window_size = window_size
        self._ratio = ratio

    def observe(self, cluster_key: str, reward: float) -> None:
        w = self._windows.setdefault(
            cluster_key,
            ClusterRewardWindow(window_size=self._window_size),
        )
        w.observe(reward)

    def is_collapsed(self, cluster_key: str) -> bool:
        w = self._windows.get(cluster_key)
        if w is None:
            return False
        return w.collapsed(ratio=self._ratio)

    def status(self, cluster_key: str) -> dict[str, float]:
        w = self._windows.get(cluster_key)
        if w is None:
            return {"current_std": 0.0, "max_std_seen": 0.0,
                     "samples": 0.0}
        return {
            "current_std": w.current_std,
            "max_std_seen": w.max_std_seen,
            "samples": float(len(w.rewards)),
        }


# ─────────────────────── 3. DPP marginal gain ──────────────────────────


def dpp_log_marginal_gain(
    candidate_vec: Sequence[float],
    existing_vecs: list[Sequence[float]],
    *,
    quality: float = 1.0,
) -> float:
    """Approximate log determinantal marginal gain — how much volume the
    candidate adds to the embedding kernel. Higher = more diverse.

    Exact DPP would be O(N³) — instead we use the local approximation:
      gain ≈ log(quality² · (1 - max_cosine_to_existing²))
    This is the DPP "marginal volume" for adding one point next to its
    nearest neighbour. Cheap, monotone in diversity, monotone in quality.
    """
    if not existing_vecs:
        return math.log(max(quality, 1e-6))
    max_cos = max(cosine(candidate_vec, v) for v in existing_vecs)
    redundancy = max_cos * max_cos
    # Clamp to avoid log(0) when candidate is identical to existing
    volume = max(1e-6, 1.0 - redundancy)
    return math.log(max(quality, 1e-6)) + 0.5 * math.log(volume)


# ─────────────────────── 4. inverse-frequency replay ───────────────────


def sample_inverse_frequency(
    items: list[dict[str, Any]],
    *,
    retrieval_count_key: str = "retrieval_count",
    k: int = 1,
    rng: Optional[random.Random] = None,
) -> list[dict[str, Any]]:
    """Schapiro-pattern: sample k items with probability proportional to
    1 / (1 + retrieval_count). Weakly-used items get replay priority."""
    if not items:
        return []
    rng = rng or random
    weights = [1.0 / (1.0 + max(0.0, float(it.get(retrieval_count_key, 0))))
                for it in items]
    return rng.choices(items, weights=weights, k=min(k, len(items)))


# ─────────────────────── 5. library health metrics ─────────────────────


@dataclass
class LibraryHealth:
    """Snapshot of library-level Echo Trap indicators."""

    embedding_gini: float = 0.0
    pairwise_cosine_mean: float = 0.0
    pairwise_cosine_max: float = 0.0
    cluster_count: int = 0
    coverage_radius: float = 0.0
    skill_count: int = 0
    concentrated: bool = False
    reasons: list[str] = field(default_factory=list)


def measure_health(
    skill_vectors: dict[str, Sequence[float]],
    *,
    similarity_threshold: float = 0.7,
    max_pairs_sample: int = 1000,
) -> LibraryHealth:
    """Compute library-level health on the skill embedding set.

    Returns a `LibraryHealth` snapshot. `concentrated=True` means the
    library has crossed at least one Echo Trap threshold and minting
    should be paused / human-reviewed until it diversifies.

    `max_pairs_sample` caps the pairwise compute when library is large.
    """
    n = len(skill_vectors)
    h = LibraryHealth(skill_count=n)
    if n < 2:
        return h

    ids = list(skill_vectors.keys())
    vecs = [skill_vectors[i] for i in ids]

    # Sample pairs if library is huge
    pairs: list[tuple[int, int]] = []
    if n * (n - 1) // 2 <= max_pairs_sample:
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((i, j))
    else:
        seen = set()
        while len(pairs) < max_pairs_sample:
            i = random.randint(0, n - 1)
            j = random.randint(0, n - 1)
            if i == j or (i, j) in seen or (j, i) in seen:
                continue
            seen.add((i, j))
            pairs.append((i, j))

    cos_values = [cosine(vecs[i], vecs[j]) for (i, j) in pairs]
    h.pairwise_cosine_mean = mean(cos_values)
    h.pairwise_cosine_max = max(cos_values)

    # Gini over pairwise cosine — measures concentration
    h.embedding_gini = _gini(cos_values)

    # Naive cluster count: items connected if cosine > threshold; union-find
    parents = list(range(n))

    def find(x: int) -> int:
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parents[rx] = ry

    for (i, j), c in zip(pairs, cos_values):
        if c > similarity_threshold:
            union(i, j)
    h.cluster_count = len({find(i) for i in range(n)})

    # Coverage radius — mean distance from each skill to its 5 nearest
    # neighbours (lower = more concentrated)
    coverage_per_item: list[float] = []
    for i in range(n):
        sims = sorted(
            (cosine(vecs[i], vecs[j]) for j in range(n) if j != i),
            reverse=True,
        )[:5]
        if sims:
            coverage_per_item.append(1.0 - mean(sims))
    h.coverage_radius = mean(coverage_per_item) if coverage_per_item else 0.0

    # Concentration flags
    if h.embedding_gini > 0.6:
        h.concentrated = True
        h.reasons.append(f"gini={h.embedding_gini:.2f} > 0.6")
    if h.pairwise_cosine_mean > 0.65:
        h.concentrated = True
        h.reasons.append(f"mean_cos={h.pairwise_cosine_mean:.2f} > 0.65")
    expected_clusters = max(1, int(math.sqrt(n)))
    if h.cluster_count < 0.5 * expected_clusters:
        h.concentrated = True
        h.reasons.append(
            f"clusters={h.cluster_count} < 0.5·√n ({expected_clusters})"
        )
    return h


def _gini(values: list[float]) -> float:
    """Gini coefficient for inequality of pairwise-cosine values."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    total = sum(s)
    if total <= 0:
        return 0.0
    cumulative = 0.0
    for i, v in enumerate(s):
        cumulative += (i + 1) * v
    return (2 * cumulative) / (n * total) - (n + 1) / n


# ─────────────────────── exploration term (composite) ──────────────────


@dataclass
class ExplorationConfig:
    """Tunable knobs for the composite Echo-Trap-aware mint gate."""

    diversity_refuse: float = 0.92
    diversity_merge: float = 0.97
    variance_collapse_ratio: float = 0.5
    quality_weight: float = 1.0
    dpp_weight: float = 0.5
    annealing_skills: int = 1000  # exploration term anneals over this


@dataclass
class ExplorationDecision:
    accept: bool
    composite_score: float
    diversity: DiversityDecision
    variance_collapsed: bool
    dpp_gain: float
    annealed_beta: float
    reason: str


def echo_trap_decide(
    *,
    candidate_vec: Sequence[float],
    candidate_quality: float,
    existing_vecs: dict[str, Sequence[float]],
    library_size: int,
    variance_gate: Optional[VarianceGate] = None,
    cluster_key: Optional[str] = None,
    cfg: Optional[ExplorationConfig] = None,
) -> ExplorationDecision:
    """Composite Echo-Trap gate. Combines diversity floor + variance
    collapse + DPP marginal gain into one decision."""
    cfg = cfg or ExplorationConfig()
    diversity = check_diversity(
        candidate_vec, list(existing_vecs.items()),
        cfg=DiversityCheck(
            refuse_threshold=cfg.diversity_refuse,
            merge_threshold=cfg.diversity_merge,
        ),
    )
    if diversity.action != "accept":
        return ExplorationDecision(
            accept=False, composite_score=0.0,
            diversity=diversity, variance_collapsed=False, dpp_gain=0.0,
            annealed_beta=0.0,
            reason=diversity.reason,
        )

    var_collapsed = False
    if variance_gate is not None and cluster_key is not None:
        var_collapsed = variance_gate.is_collapsed(cluster_key)
    if var_collapsed:
        return ExplorationDecision(
            accept=False, composite_score=0.0,
            diversity=diversity, variance_collapsed=True, dpp_gain=0.0,
            annealed_beta=0.0,
            reason=f"variance collapsed for cluster '{cluster_key}'",
        )

    dpp = dpp_log_marginal_gain(
        candidate_vec, list(existing_vecs.values()),
        quality=candidate_quality,
    )

    # Anneal the exploration bonus from 0.5 → 0.1 as library fills
    beta = max(
        0.1,
        0.5 * (1.0 - library_size / cfg.annealing_skills),
    )

    composite = cfg.quality_weight * candidate_quality + beta * cfg.dpp_weight * dpp
    accept = composite > 0.0
    return ExplorationDecision(
        accept=accept,
        composite_score=composite,
        diversity=diversity,
        variance_collapsed=False,
        dpp_gain=dpp,
        annealed_beta=beta,
        reason="composite OK" if accept else "composite below floor",
    )
