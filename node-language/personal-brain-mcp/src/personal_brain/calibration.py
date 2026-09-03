"""Adaptive calibration for skill-mint thresholds — solves R1.

Replaces the fixed `novelty > 0.25 AND success_score >= 0.7` heuristic
with self-tuning thresholds that adapt to library size + observed
retention:

  • Beta-Bernoulli posterior over P(skill_retained_30d | accepted)
    — LCB at 10th percentile becomes the success floor
  • Streaming quantile (P²) over recent proposed novelty values
    — top-30% by novelty becomes the novelty floor
  • CUSUM drift detector on retention rate
    — fires when distribution shifts; halves posterior to re-explore

References:
  • Jøsang & Ismail 2002 — Beta Reputation System
  • Thompson Sampling Tutorial (Russo et al.)
  • CUSUM concept-drift detector (Page 1954, modern formulation)
  • Streaming quantile P² algorithm (Jain & Chlamtac 1985)

Cost: O(1) per mint + O(1) per outcome. State ~2KB. Pure stdlib.
"""
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


# ─────────────────────── Beta-Bernoulli LCB ────────────────────────────


def beta_ppf(q: float, alpha: float, beta: float, *, eps: float = 1e-6) -> float:
    """Inverse CDF of Beta(alpha, beta) at quantile q.

    Stdlib-only implementation via bisection. Good enough for the LCB
    floor (we only need ~3 decimal places). For production loads, scipy
    is a faster swap-in.
    """
    if alpha <= 0 or beta <= 0:
        return 0.0
    if q <= 0:
        return 0.0
    if q >= 1:
        return 1.0
    # Bisect on the regularised incomplete beta function via Bn series
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if _beta_cdf(mid, alpha, beta) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < eps:
            break
    return 0.5 * (lo + hi)


def _beta_cdf(x: float, alpha: float, beta: float) -> float:
    """Regularised incomplete beta function I_x(a, b) via continued
    fraction (Numerical Recipes §6.4 — Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(alpha) + math.lgamma(beta) - math.lgamma(alpha + beta)
    front = math.exp(
        alpha * math.log(x) + beta * math.log1p(-x) - lbeta
    ) / alpha
    # Continued fraction
    f = 1.0
    c = 1.0
    d = 1.0 - (alpha + beta) * x / (alpha + 1.0)
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        # even step
        aa = m * (beta - m) * x / ((alpha + m2 - 1) * (alpha + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        # odd step
        aa = -(alpha + m) * (alpha + beta + m) * x / (
            (alpha + m2) * (alpha + m2 + 1)
        )
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-7:
            break
    return front * h


# ─────────────────────── streaming quantile ────────────────────────────


def streaming_quantile(values: list[float], q: float) -> float:
    """Cheap exact quantile over a finite window. Window kept small
    (200 in `CalibrationState`) so O(n log n) sort is fine — faster than
    the P² approximation at this size."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(q * (len(s) - 1))))
    return s[idx]


# ─────────────────────── CUSUM drift detector ──────────────────────────


@dataclass
class CUSUM:
    """One-sided CUSUM for detecting drops in a Bernoulli stream.

    Fires when S_t = max(0, S_{t-1} + (ref - x_t - k)) exceeds h.
    With Bernoulli x_t ∈ {0,1}, reference rate `ref`, slack `k`, threshold `h`.
    """

    ref: float = 0.6
    k: float = 0.05
    h: float = 4.0
    S: float = 0.0
    last_fire_t: int = -1

    def observe(self, x: float, t: int) -> bool:
        """Update with one observation. Returns True iff CUSUM fires
        (drift detected). Caller resets state after handling."""
        self.S = max(0.0, self.S + (self.ref - x - self.k))
        if self.S > self.h:
            self.last_fire_t = t
            return True
        return False

    def reset(self) -> None:
        self.S = 0.0


# ─────────────────────── calibration state ─────────────────────────────


@dataclass
class CalibrationState:
    """Self-tuning thresholds for skill-mint admission.

    Persist as JSON between sessions. Tiny payload (~2KB even after
    months of mints).

    Default behaviour:
      • Warm-up: first `min_mints_before_strict=30` mints use permissive
        defaults (0.50, 0.05) so the cold-start library grows.
      • After warm-up: success_floor = Beta-LCB(10%); novelty_floor =
        top-30% quantile of recent novelty values.
      • CUSUM on retention: drift → halve posterior + clear window.
    """

    # Beta posterior over P(retained | accepted)
    alpha: float = 1.0
    beta: float = 1.0

    # Streaming novelty window
    novelty_window: list[float] = field(default_factory=list)
    novelty_window_cap: int = 200

    # CUSUM state on retention
    cusum: CUSUM = field(default_factory=CUSUM)

    # Knobs
    min_mints_before_strict: int = 30
    lcb_quantile: float = 0.10
    target_accept_rate: float = 0.30
    warm_success_floor: float = 0.50
    warm_novelty_floor: float = 0.05
    success_floor_clamp: tuple[float, float] = (0.40, 0.85)

    # Counters
    mints_proposed: int = 0
    mints_accepted: int = 0
    drifts_detected: int = 0
    t: int = 0  # monotonic step counter for CUSUM

    def observed_mints(self) -> int:
        """Number of REAL observations (alpha + beta - prior pseudo-counts)."""
        return int(max(0, self.alpha + self.beta - 2))

    # ── thresholds (called per proposed mint) ───────────────────────

    def success_floor(self) -> float:
        if self.observed_mints() < self.min_mints_before_strict:
            return self.warm_success_floor
        lcb = beta_ppf(self.lcb_quantile, self.alpha, self.beta)
        lo, hi = self.success_floor_clamp
        return max(lo, min(hi, lcb))

    def novelty_floor(self) -> float:
        if len(self.novelty_window) < 20:
            return self.warm_novelty_floor
        # We accept the TOP `target_accept_rate` fraction; cut at
        # (1 - target_accept_rate) quantile.
        return streaming_quantile(
            self.novelty_window, 1.0 - self.target_accept_rate,
        )

    # ── feedback path (called per proposed + per outcome) ──────────

    def record_proposal(self, novelty: float) -> None:
        self.mints_proposed += 1
        self.novelty_window.append(float(novelty))
        if len(self.novelty_window) > self.novelty_window_cap:
            self.novelty_window.pop(0)

    def record_decision(self, accepted: bool) -> None:
        if accepted:
            self.mints_accepted += 1

    def record_outcome(self, retained: bool) -> bool:
        """Call when we know whether a previously-minted skill was kept.
        Returns True iff drift was detected (caller may also log it).
        """
        self.t += 1
        if retained:
            self.alpha += 1
        else:
            self.beta += 1
        x = 1.0 if retained else 0.0
        drift = self.cusum.observe(x, self.t)
        if drift:
            # Forget half the posterior so we explore again. Don't drop
            # below 1.0 (proper Beta prior).
            self.alpha = max(1.0, self.alpha * 0.5)
            self.beta = max(1.0, self.beta * 0.5)
            self.cusum.reset()
            # Also flush the novelty window — distribution has shifted
            self.novelty_window.clear()
            self.drifts_detected += 1
        return drift

    # ── decision ───────────────────────────────────────────────────

    def decide(
        self, *, novelty: float, success_score: float,
    ) -> tuple[bool, float, float, str]:
        """Per-mint gate. Returns (accept, novelty_floor, success_floor,
        reason).

        Side effect: records the proposal in the novelty window so the
        next decision sees this observation.
        """
        self.record_proposal(novelty)
        nf = self.novelty_floor()
        sf = self.success_floor()
        if novelty < nf:
            self.record_decision(False)
            return (False, nf, sf,
                    f"novelty={novelty:.3f} < floor={nf:.3f}")
        if success_score < sf:
            self.record_decision(False)
            return (False, nf, sf,
                    f"success={success_score:.3f} < floor={sf:.3f}")
        self.record_decision(True)
        return (True, nf, sf, "accept")

    # ── persistence ────────────────────────────────────────────────

    def to_json(self) -> str:
        d = asdict(self)
        # asdict serialises CUSUM dataclass fine
        return json.dumps(d, default=str)

    @classmethod
    def from_json(cls, payload: str) -> "CalibrationState":
        d = json.loads(payload)
        cusum_d = d.pop("cusum", {})
        st = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        # Re-coerce CUSUM
        cu = CUSUM(**{k: v for k, v in cusum_d.items() if k in CUSUM.__dataclass_fields__})
        st.cusum = cu
        return st

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CalibrationState":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls.from_json(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()


# ─────────────────────── convenience facade ────────────────────────────


def adaptive_decide(
    state: CalibrationState,
    *,
    novelty: float,
    success_score: float,
) -> tuple[bool, dict[str, float]]:
    """One-call API. Returns (accept, breakdown_for_logging)."""
    accepted, nf, sf, reason = state.decide(
        novelty=novelty, success_score=success_score,
    )
    return accepted, {
        "novelty": novelty,
        "novelty_floor": nf,
        "success_score": success_score,
        "success_floor": sf,
        "alpha": state.alpha,
        "beta": state.beta,
        "observed_mints": state.observed_mints(),
        "reason": reason,
    }
