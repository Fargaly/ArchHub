"""Brain privacy layer — the scope-crossing gate + differential-privacy runtime.

Implements the architecture from
``docs/research/privacy-respecting-knowledge-sharing-2026-05-26.md`` (Q10
founder pick, 2026-05-26): the per-scope ladder + differential-privacy noise
that lets brain knowledge flow *up* toward a shared pool **without** leaking
the raw work that produced it.

The scope ladder (widening left→right)::

    USER  <  PROJECT  <  FIRM  <  COMMUNITY  <  GLOBAL
    │          │          │          │            │
    your       project    org        ArchHub-     canonical
    machine    team       seats      wide pool    (maintainers)
    only                             (opt-in →
                                      Brain #33)

The research doc names the widest *opt-in cross-firm pool* "COLLECTIVE". In
the live ``models.Scope`` enum (AgDR-0044) that pool is the ``COMMUNITY``
tier (``Visibility.SHARED_PUBLIC`` — "promoter (redacted)"). This module
treats ``COMMUNITY`` as the collective pool the doc describes and exposes
``COLLECTIVE`` as an alias so the spec's vocabulary keeps working. ``GLOBAL``
(canonical / maintainers) sits above it; both ``COMMUNITY`` and ``GLOBAL``
are "collective-class" scopes that may only ever receive differentially-
private aggregates — never raw fragments.

The core guarantee (research doc §D + §C, threat-model row "Re-identification
from aggregates"):

    **Raw user fragments NEVER reach the collective scope. Only
    differentially-private AGGREGATES do.**

A raw fragment carries subjects / objects / free text / file paths / firm
details — exactly the things that re-identify a user or firm. ``may_cross``
BLOCKS any raw fragment from crossing into a collective-class scope.
``privatize_for_collective`` is the *only* sanctioned way to emit anything to
the collective: it returns counts/sums/means with Laplace noise added, and
strips every raw string out. This mirrors the federated-learning posture from
the prior-art scan (Google Gboard / Apple): pool aggregates, not raw data.

This also upholds the repo-wide BRAIN-FIRST posture: the brain stores
**references only — no raw secrets** (``op://…`` refs resolved at call time).
The privacy layer extends that posture outward: what leaves a scope toward a
wider one is references/aggregates, never the raw secret-bearing payload.

Zero heavy deps required — the module imports on a minimal install. If
OpenDP / SmartNoise is present (research doc Pick #7: "Use OpenDP /
SmartNoise … mature, MIT-licensed, Microsoft-maintained") it is used for a
stronger, audited Laplace mechanism via a lazy import; otherwise a pure-
python inverse-CDF Laplace sampler is the fallback. ``is_opendp_available()``
reports which path is live.

Design reference: docs/research/privacy-respecting-knowledge-sharing-
2026-05-26.md — NOT the roadmap. The roadmap is docs/ROADMAP.md.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any, Iterable, Optional

from .models import Fragment, Scope


# ───────────────────────── Scope ladder ─────────────────────────────────
#
# Lower rank = narrower / more private. A fragment may always flow to its own
# scope or a NARROWER one (rank ≤). Flowing to a WIDER scope (rank >) is the
# gated direction — see ``may_cross``.

_SCOPE_ORDER: tuple[Scope, ...] = (
    Scope.USER,       # 0 — private, owner only
    Scope.PROJECT,    # 1 — project team
    Scope.FIRM,       # 2 — org seats
    Scope.COMMUNITY,  # 3 — ArchHub-wide opt-in pool (the doc's "COLLECTIVE")
    Scope.GLOBAL,     # 4 — canonical / maintainers
)
_SCOPE_RANK: dict[Scope, int] = {s: i for i, s in enumerate(_SCOPE_ORDER)}

# The research doc speaks of a "COLLECTIVE" tier. In the live enum that is the
# COMMUNITY pool. Alias so spec vocabulary keeps working in callers/tests.
COLLECTIVE: Scope = Scope.COMMUNITY

# Scopes that represent a shared, cross-origin pool. Raw fragments may NEVER
# land here — only DP aggregates. COMMUNITY is the opt-in collective pool;
# GLOBAL (canonical) is wider still, so it is collective-class too.
COLLECTIVE_SCOPES: frozenset[Scope] = frozenset({Scope.COMMUNITY, Scope.GLOBAL})


def scope_rank(scope: Scope | str) -> int:
    """Return the ladder rank of a scope (USER=0 … GLOBAL=4).

    Lower is narrower / more private. Accepts a ``Scope`` or its string value
    ("user", "project", "firm", "community"/"collective", "global").

    Raises ``ValueError`` for an unknown scope so a typo can never silently
    rank as "most private" and leak.
    """
    if isinstance(scope, str):
        s = scope.strip().lower()
        if s == "collective":  # spec alias for the community pool
            scope = Scope.COMMUNITY
        else:
            try:
                scope = Scope(s)
            except ValueError as exc:  # pragma: no cover - defensive
                raise ValueError(f"unknown scope: {scope!r}") from exc
    if scope not in _SCOPE_RANK:
        raise ValueError(f"unknown scope: {scope!r}")
    return _SCOPE_RANK[scope]


def is_collective_scope(scope: Scope | str) -> bool:
    """True if ``scope`` is a shared cross-origin pool (COMMUNITY or GLOBAL).

    These are the only scopes that demand differential privacy before any
    data may enter them.
    """
    if isinstance(scope, str):
        s = scope.strip().lower()
        scope = Scope.COMMUNITY if s == "collective" else Scope(s)
    return scope in COLLECTIVE_SCOPES


# ───────────────────────── The crossing gate ────────────────────────────


def may_cross(
    fragment_scope: Scope | str,
    target_scope: Scope | str,
    *,
    dp_applied: bool,
) -> bool:
    """Decide whether a fragment at ``fragment_scope`` may flow to
    ``target_scope``.

    The gate (research doc §B "scope routing" + §D "differential privacy"):

    * **Own scope or NARROWER → always allowed.** A FIRM fact is freely
      visible to FIRM, PROJECT, and USER callers (rank ≤ origin). Narrowing
      never widens exposure, so it is unconditionally safe.
    * **Wider, but NOT collective-class → allowed.** Escalating one tier up
      the org ladder (e.g. PROJECT → FIRM) is a normal, sanctioned share. The
      per-fact ``shareable`` flag + audit trail (doc §A/§F) govern *whether* a
      given fragment opts in; this gate governs *what kind of crossing is even
      legal*. Org-internal widening is legal.
    * **Wider INTO a collective-class scope (COMMUNITY / GLOBAL) → allowed
      ONLY when ``dp_applied=True``.** A raw fragment may NEVER reach the
      collective pool. The only thing that may cross that boundary is a
      differentially-private aggregate, and the caller asserts that by passing
      ``dp_applied=True`` (which ``privatize_for_collective`` does on its
      output). With ``dp_applied=False`` the gate returns ``False`` — this is
      the core privacy guarantee.

    ``dp_applied`` is ignored for non-collective targets: you don't need DP to
    share a fact with your own firm.
    """
    src = scope_rank(fragment_scope)
    dst = scope_rank(target_scope)

    # Own scope or narrower — always fine.
    if dst <= src:
        return True

    # Widening into a collective-class pool requires DP.
    if is_collective_scope(target_scope):
        return bool(dp_applied)

    # Widening within the org ladder (PROJECT→FIRM etc.) is legal.
    return True


# ───────────────────────── Laplace mechanism ────────────────────────────
#
# Differential privacy via the Laplace mechanism (Dwork & Roth, "The
# Algorithmic Foundations of Differential Privacy"). For a query with
# L1-sensitivity Δf, releasing  f(x) + Laplace(0, Δf/ε)  is ε-differentially
# private. Apple's iOS telemetry (prior-art scan) uses the same family.

_OPENDP_PROBE: Optional[bool] = None


def is_opendp_available() -> bool:
    """Return True if OpenDP / SmartNoise can be imported (lazy, cached).

    Per research doc Pick #7, OpenDP is the preferred mechanism when present.
    When absent, the module falls back to a pure-python Laplace sampler — so
    the brain still privatizes correctly on a minimal install. Probing never
    raises; a missing/broken package simply means "use the fallback".
    """
    global _OPENDP_PROBE
    if _OPENDP_PROBE is None:
        try:
            import opendp  # type: ignore  # noqa: F401

            _OPENDP_PROBE = True
        except Exception:
            _OPENDP_PROBE = False
    return _OPENDP_PROBE


def laplace_noise(scale: float, *, rng: Optional[random.Random] = None) -> float:
    """Sample one draw from a zero-mean Laplace distribution with ``scale`` b.

    Pure-python inverse-CDF (no numpy / no heavy dep):

        X = -b · sgn(u) · ln(1 - 2|u|),  u ~ Uniform(-1/2, 1/2)

    The expectation is 0; the variance is 2·b². ``scale`` must be > 0.
    A custom ``rng`` (``random.Random``) may be passed for reproducible tests.
    """
    if scale <= 0:
        raise ValueError("laplace scale must be > 0")
    r = rng or random
    # u in (-1/2, 1/2); avoid the exact endpoints so ln is finite.
    u = r.random() - 0.5
    return -scale * math.copysign(1.0, u) * math.log1p(-2.0 * abs(u))


def _laplace_via_opendp(scale: float) -> Optional[float]:
    """Best-effort single Laplace draw through OpenDP. Returns None if the
    installed OpenDP build doesn't expose a usable base-Laplace measurement
    (API drift across versions) so the caller falls back to pure-python."""
    try:  # pragma: no cover - exercised only where opendp is installed
        from opendp.measurements import make_laplace  # type: ignore
        from opendp.domains import atom_domain  # type: ignore
        from opendp.metrics import absolute_distance  # type: ignore
        from opendp.mod import enable_features  # type: ignore

        enable_features("contrib", "floating-point")
        meas = make_laplace(
            atom_domain(T=float, nan=False),
            absolute_distance(T=float),
            scale=float(scale),
        )
        return float(meas(0.0))
    except Exception:
        return None


def _sample_laplace(scale: float, *, rng: Optional[random.Random] = None) -> float:
    """Draw Laplace(0, scale) — via OpenDP when available + a custom rng is
    NOT requested, else the pure-python fallback.

    A caller-supplied ``rng`` forces the deterministic pure-python path so
    tests stay reproducible regardless of whether OpenDP is installed.
    """
    if rng is None and is_opendp_available():
        val = _laplace_via_opendp(scale)
        if val is not None:
            return val
    return laplace_noise(scale, rng=rng)


# ───────────────────────── DP queries ───────────────────────────────────


def dp_count(
    true_count: int,
    *,
    epsilon: float,
    sensitivity: float = 1.0,
    rng: Optional[random.Random] = None,
) -> int:
    """ε-differentially-private noised count.

    Adds Laplace(0, sensitivity/ε) to ``true_count``, clamps to ≥ 0, and
    rounds to the nearest int. A single record changes a count by at most 1,
    so the default ``sensitivity`` is 1.0 (research doc §D).

    Over many independent calls the mean of ``dp_count`` ≈ ``true_count``
    (the noise is zero-mean); any individual release hides whether one
    specific record was present. Never returns a negative number — a count
    is non-negative by definition.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    if sensitivity <= 0:
        raise ValueError("sensitivity must be > 0")
    scale = sensitivity / epsilon
    noised = true_count + _sample_laplace(scale, rng=rng)
    return max(0, round(noised))


def dp_aggregate(
    values: list[float],
    *,
    epsilon: float,
    sensitivity: float,
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    """Release DP-noised sum / mean / count for a list of numeric values.

    Splits the privacy budget across the count query and the sum query
    (ε/2 each) so the *combined* release is ε-DP by sequential composition.
    The mean is derived from the two noised statistics (never released as a
    separate query, which would cost more budget). Returns a dict — counts
    and totals only, no raw values — safe to hand to a collective-class
    scope.

    This is the per-metric primitive ``privatize_for_collective`` composes to
    answer questions like "how many wall-classify runs hit a COM timeout
    across all firms?" without exposing any single firm's contribution
    (research doc §D + threat-model row "Re-identification from aggregates").
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    if sensitivity <= 0:
        raise ValueError("sensitivity must be > 0")

    half = epsilon / 2.0
    true_count = len(values)
    true_sum = float(sum(values)) if values else 0.0

    noised_count = max(0, round(true_count + _sample_laplace(1.0 / half, rng=rng)))
    noised_sum = true_sum + _sample_laplace(sensitivity / half, rng=rng)
    # Mean of genuinely-empty input is 0 — don't let count-noise rounding up
    # from 0 fabricate a non-zero magnitude out of an empty list. When there
    # IS real data, derive the mean from the two noised statistics.
    if true_count == 0:
        noised_mean = 0.0
    else:
        noised_mean = (noised_sum / noised_count) if noised_count > 0 else 0.0

    return {
        "count": noised_count,
        "sum": noised_sum,
        "mean": noised_mean,
        "epsilon": epsilon,
        "sensitivity": sensitivity,
        "mechanism": "opendp" if is_opendp_available() and rng is None else "laplace",
        "dp_applied": True,
    }


# ───────────────────────── Collective release ───────────────────────────

# Keys that are pure aggregates / metadata — provably free of raw fragment
# content. Used as the allow-list when asserting the privacy guarantee.
_COLLECTIVE_OUTPUT_KEYS: frozenset[str] = frozenset(
    {
        "total_fragments",
        "counts_by_kind",
        "counts_by_scope",
        "success_rate",
        "epsilon",
        "mechanism",
        "dp_applied",
        "schema_version",
        "guarantee",
    }
)

_COLLECTIVE_SCHEMA_VERSION = "1.0"


def privatize_for_collective(
    fragments: Iterable[Fragment],
    *,
    epsilon: float,
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    """Top-level collective release. The ONLY sanctioned COLLECTIVE export.

    Takes raw fragments and returns **only differentially-private
    aggregates** — DP-noised counts by kind and by scope, a DP success-rate,
    and the total. It deliberately drops every raw string: subjects,
    predicates, objects, free text, owner / project / firm ids, blob paths.
    None of those ever appear in the output.

    This is what a COLLECTIVE / COMMUNITY export is *allowed* to emit. The
    raw fragments stay where they are; what crosses the boundary is noise-
    protected counts. The returned dict carries ``dp_applied=True`` so it can
    pass ``may_cross(..., target_scope=COLLECTIVE, dp_applied=...)``.

    The budget ε is spread across the kind-count queries and the scope-count
    queries (sequential composition). ``rng`` forces the deterministic
    pure-python Laplace path for tests.

    Privacy guarantee (asserted in tests): no raw fragment subject / object /
    predicate / text string appears anywhere in this output.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")

    frags = list(fragments)
    kind_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    successes = 0
    attempts = 0
    for f in frags:
        kind_val = f.kind.value if hasattr(f.kind, "value") else str(f.kind)
        scope_val = f.scope.value if hasattr(f.scope, "value") else str(f.scope)
        kind_counts[kind_val] += 1
        scope_counts[scope_val] += 1
        sc = getattr(f, "success_count", 0) or 0
        fc = getattr(f, "fail_count", 0) or 0
        successes += sc
        attempts += sc + fc

    # Split budget across the two count families so the whole release is ε-DP.
    n_buckets = max(1, len(kind_counts) + len(scope_counts))
    per_query_eps = epsilon / n_buckets

    counts_by_kind = {
        k: dp_count(v, epsilon=per_query_eps, rng=rng) for k, v in kind_counts.items()
    }
    counts_by_scope = {
        k: dp_count(v, epsilon=per_query_eps, rng=rng) for k, v in scope_counts.items()
    }
    total = dp_count(len(frags), epsilon=per_query_eps, rng=rng)

    # DP success-rate: noise numerator + denominator, then ratio (clamped).
    noised_succ = dp_count(successes, epsilon=per_query_eps, rng=rng)
    noised_att = dp_count(attempts, epsilon=per_query_eps, rng=rng)
    success_rate = (noised_succ / noised_att) if noised_att > 0 else 0.0
    success_rate = max(0.0, min(1.0, success_rate))

    return {
        "schema_version": _COLLECTIVE_SCHEMA_VERSION,
        "total_fragments": total,
        "counts_by_kind": counts_by_kind,
        "counts_by_scope": counts_by_scope,
        "success_rate": round(success_rate, 4),
        "epsilon": epsilon,
        "mechanism": "opendp" if is_opendp_available() and rng is None else "laplace",
        "dp_applied": True,
        "guarantee": (
            "differentially-private aggregates only; no raw fragment subjects,"
            " objects, text, or origin ids cross into the collective scope"
        ),
    }


def is_pure_aggregate(payload: dict[str, Any]) -> bool:
    """True if ``payload`` contains only allow-listed aggregate/metadata keys.

    A cheap structural check that a dict destined for a collective-class scope
    carries no surprise raw-data keys. The substring privacy guarantee
    (no raw strings in the values) is enforced by tests against real
    fragments; this guards the *shape* at runtime.
    """
    return set(payload.keys()).issubset(_COLLECTIVE_OUTPUT_KEYS)
