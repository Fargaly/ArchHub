"""Decision / score nodes — SPEC §6 floor addition (grand-map
nodes_decision_score + nodes_decision_fuzzy).

Two pure, deterministic multi-criteria decision executors:

  decision.topsis — classic crisp TOPSIS (construction-MCDM staple):
                    vector-normalize -> weight -> ideal / anti-ideal ->
                    Euclidean distances -> closeness coefficient.
  decision.fuzzy  — linguistic multi-stakeholder scoring (simplified
                    fuzzy-TOPSIS / fuzzy weighted sum): triangular fuzzy
                    numbers, stakeholders fused by fuzzy averaging,
                    defuzzified by centroid.

Both take their decision problem from `config` (wired `criteria` /
`options` inputs win over config, matching the data.dedupe / data.join
"wired input beats config" parity), and both return the same shape:

    {"status": "ok", "ranked": [{"name": ..., "score": ...}, ...],
     "best": <top option name>}

Ranking is descending by score with option NAME as the deterministic
tie-break, so the same inputs always produce byte-identical output.
No host, no LLM, math module only.
"""
from __future__ import annotations

import math
from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


_DIRECTIONS = ("max", "min")


def _err(msg: str) -> dict:
    return {"status": "error", "ranked": [], "best": None, "error": msg}


def _pick(inputs: dict, config: dict, key: str):
    """Wired input beats config (data.join / data.dedupe parity)."""
    wired = (inputs or {}).get(key)
    if wired is not None:
        return wired
    return (config or {}).get(key)


def _validate_criteria(criteria: Any) -> str | None:
    if not isinstance(criteria, (list, tuple)) or not criteria:
        return "criteria must be a non-empty list"
    for c in criteria:
        if not isinstance(c, dict) or not c.get("name"):
            return "each criterion needs a `name`"
    return None


def _validate_options(options: Any) -> str | None:
    if not isinstance(options, (list, tuple)) or not options:
        return "options must be a non-empty list"
    for o in options:
        if not isinstance(o, dict) or not o.get("name"):
            return "each option needs a `name`"
    return None


def _ranked(scores: dict) -> list:
    """Descending score, option name breaks ties — deterministic."""
    return [{"name": n, "score": scores[n]}
            for n in sorted(scores, key=lambda n: (-scores[n], n))]


# ---------------------------------------------------------------------------
# decision.topsis
#
# Config:
#   criteria — [{name, weight (positive number), direction: "max"|"min"}]
#   options  — [{name, values: {criterion_name: number}}]
# Output:
#   ranked — [{name, score}] descending by closeness coefficient
#   best   — name of the top-ranked option
#
# Standard TOPSIS (Hwang & Yoon):
#   1. r_ij = x_ij / sqrt(sum_i x_ij^2)         (vector normalize per column;
#                                                an all-zero column yields 0)
#   2. v_ij = (w_j / sum(w)) * r_ij             (weights normalized to sum 1)
#   3. A+_j = best v_ij per column (max for direction=max, min for min);
#      A-_j = worst.
#   4. D+_i = sqrt(sum_j (v_ij - A+_j)^2), D-_i likewise vs A-.
#   5. closeness C_i = D-_i / (D+_i + D-_i)     (0 if both distances are 0,
#                                                i.e. all options identical)


def _topsis_executor(config: dict, inputs: dict, ctx) -> dict:
    criteria = _pick(inputs, config, "criteria")
    options = _pick(inputs, config, "options")
    bad = _validate_criteria(criteria) or _validate_options(options)
    if bad:
        return _err(f"topsis: {bad}")

    names: list[str] = []
    weights: dict[str, float] = {}
    directions: dict[str, str] = {}
    for c in criteria:
        cname = str(c["name"])
        try:
            w = float(c.get("weight", 1.0))
        except (TypeError, ValueError):
            return _err(f"topsis: criterion {cname!r} weight is not a number")
        if w <= 0:
            return _err(f"topsis: criterion {cname!r} weight must be > 0")
        d = str(c.get("direction", "max")).lower()
        if d not in _DIRECTIONS:
            return _err(f"topsis: criterion {cname!r} direction {d!r} — "
                        f"want one of {', '.join(_DIRECTIONS)}")
        names.append(cname)
        weights[cname] = w
        directions[cname] = d

    matrix: dict[str, dict[str, float]] = {}
    for o in options:
        oname = str(o["name"])
        vals = o.get("values") or {}
        if not isinstance(vals, dict):
            return _err(f"topsis: option {oname!r} `values` must be a dict")
        row: dict[str, float] = {}
        for cname in names:
            v = vals.get(cname)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return _err(f"topsis: option {oname!r} is missing a numeric "
                            f"value for criterion {cname!r}")
            row[cname] = float(v)
        matrix[oname] = row
    if len(matrix) != len(options):
        return _err("topsis: option names must be unique")

    wsum = sum(weights.values())
    onames = list(matrix)

    # 1+2. normalize + weight.
    v: dict[str, dict[str, float]] = {n: {} for n in onames}
    for cname in names:
        norm = math.sqrt(sum(matrix[n][cname] ** 2 for n in onames))
        for n in onames:
            r = matrix[n][cname] / norm if norm > 0 else 0.0
            v[n][cname] = (weights[cname] / wsum) * r

    # 3. ideal / anti-ideal.
    ideal: dict[str, float] = {}
    anti: dict[str, float] = {}
    for cname in names:
        col = [v[n][cname] for n in onames]
        if directions[cname] == "max":
            ideal[cname], anti[cname] = max(col), min(col)
        else:
            ideal[cname], anti[cname] = min(col), max(col)

    # 4+5. distances -> closeness.
    scores: dict[str, float] = {}
    for n in onames:
        d_plus = math.sqrt(sum((v[n][c] - ideal[c]) ** 2 for c in names))
        d_minus = math.sqrt(sum((v[n][c] - anti[c]) ** 2 for c in names))
        denom = d_plus + d_minus
        scores[n] = (d_minus / denom) if denom > 0 else 0.0

    ranked = _ranked(scores)
    return {"status": "ok", "ranked": ranked, "best": ranked[0]["name"]}


register(NodeSpec(
    type="decision.topsis", category="data", display_name="TOPSIS rank",
    description="Rank options by TOPSIS closeness coefficient. `criteria` "
                "= [{name, weight, direction: max|min}], `options` = "
                "[{name, values: {criterion: number}}]. Wired inputs win "
                "over config. Pure + deterministic.",
    inputs=[Port(name="criteria", type=PortType.LIST),
            Port(name="options",  type=PortType.LIST)],
    outputs=[Port(name="ranked", type=PortType.LIST),
             Port(name="best",   type=PortType.STRING)],
    config_schema={
        "criteria": {"type": "array",
                     "description": "[{name, weight>0, direction max|min}]"},
        "options":  {"type": "array",
                     "description": "[{name, values:{criterion:number}}]"},
    },
    icon="⚖"), _topsis_executor)


# ---------------------------------------------------------------------------
# decision.fuzzy
#
# Linguistic multi-stakeholder scoring with triangular fuzzy numbers (TFN
# (l, m, u)) — the intuitionistic/fuzzy-MCDM shape simplified to the
# standard fuzzy-TOPSIS pre-ranking pipeline (fuse -> weight -> defuzzify).
#
# Linguistic WEIGHT scale (importance of a criterion, TFN on [0, 1]):
#   very-low  -> (0.00, 0.00, 0.25)
#   low       -> (0.00, 0.25, 0.50)
#   medium    -> (0.25, 0.50, 0.75)
#   high      -> (0.50, 0.75, 1.00)
#   very-high -> (0.75, 1.00, 1.00)
#
# Linguistic RATING scale (how an option performs, TFN on [0, 10]):
#   very-poor -> (0.0, 0.0, 2.5)
#   poor      -> (0.0, 2.5, 5.0)
#   moderate  -> (2.5, 5.0, 7.5)
#   good      -> (5.0, 7.5, 10.0)
#   very-good -> (7.5, 10.0, 10.0)
#
# Config:
#   criteria — [{name,
#                weights: [linguistic, ... one per stakeholder]
#                         (or a single string),
#                direction: "max" (default) | "min"}]
#   options  — [{name, ratings: {criterion: [linguistic per stakeholder]
#                                            or single string}}]
#
# Pipeline (all component-wise on TFNs):
#   1. FUSE stakeholders by fuzzy averaging:
#        w_j  = (1/K) * (w_j1 + ... + w_jK)
#        r_ij = (1/K) * (r_ij1 + ... + r_ijK)
#   2. direction=min inverts the fused rating on the [0,10] scale:
#        (l, m, u) -> (10-u, 10-m, 10-l)   ("cheap cost rates high")
#   3. WEIGHT: v_ij = w_j (*) r_ij with the standard TFN product
#      approximation (l1*l2, m1*m2, u1*u2), then S_i = sum_j v_ij.
#   4. DEFUZZIFY by centroid: score_i = (l + m + u) / 3 of S_i.
#
# Stakeholder counts may differ per cell (each cell averages its own
# raters); every rating list must be non-empty.


_FUZZY_WEIGHTS = {
    "very-low":  (0.00, 0.00, 0.25),
    "low":       (0.00, 0.25, 0.50),
    "medium":    (0.25, 0.50, 0.75),
    "high":      (0.50, 0.75, 1.00),
    "very-high": (0.75, 1.00, 1.00),
}

_FUZZY_RATINGS = {
    "very-poor": (0.0, 0.0, 2.5),
    "poor":      (0.0, 2.5, 5.0),
    "moderate":  (2.5, 5.0, 7.5),
    "good":      (5.0, 7.5, 10.0),
    "very-good": (7.5, 10.0, 10.0),
}

_RATING_TOP = 10.0   # upper bound of the rating scale, for min-inversion


def _tfn_avg(tfns: list) -> tuple:
    k = len(tfns)
    return (sum(t[0] for t in tfns) / k,
            sum(t[1] for t in tfns) / k,
            sum(t[2] for t in tfns) / k)


def _lookup_terms(raw: Any, table: dict, what: str):
    """Resolve a linguistic term (or list of terms, one per stakeholder)
    to a list of TFNs. Returns (tfns, None) or (None, error string)."""
    terms = raw if isinstance(raw, (list, tuple)) else [raw]
    if not terms:
        return None, f"{what}: empty stakeholder list"
    tfns = []
    for t in terms:
        key = str(t).strip().lower()
        if key not in table:
            return None, (f"{what}: unknown term {t!r} — want one of "
                          f"{', '.join(table)}")
        tfns.append(table[key])
    return tfns, None


def _fuzzy_executor(config: dict, inputs: dict, ctx) -> dict:
    criteria = _pick(inputs, config, "criteria")
    options = _pick(inputs, config, "options")
    bad = _validate_criteria(criteria) or _validate_options(options)
    if bad:
        return _err(f"fuzzy: {bad}")

    names: list[str] = []
    fused_w: dict[str, tuple] = {}
    directions: dict[str, str] = {}
    for c in criteria:
        cname = str(c["name"])
        raw_w = c.get("weights", c.get("weight", "medium"))
        tfns, lerr = _lookup_terms(raw_w, _FUZZY_WEIGHTS,
                                   f"fuzzy: criterion {cname!r} weight")
        if lerr:
            return _err(lerr)
        d = str(c.get("direction", "max")).lower()
        if d not in _DIRECTIONS:
            return _err(f"fuzzy: criterion {cname!r} direction {d!r} — "
                        f"want one of {', '.join(_DIRECTIONS)}")
        names.append(cname)
        fused_w[cname] = _tfn_avg(tfns)          # step 1 (weights)
        directions[cname] = d

    scores: dict[str, float] = {}
    for o in options:
        oname = str(o["name"])
        ratings = o.get("ratings") or {}
        if not isinstance(ratings, dict):
            return _err(f"fuzzy: option {oname!r} `ratings` must be a dict")
        total = (0.0, 0.0, 0.0)
        for cname in names:
            if cname not in ratings:
                return _err(f"fuzzy: option {oname!r} has no rating for "
                            f"criterion {cname!r}")
            tfns, lerr = _lookup_terms(
                ratings[cname], _FUZZY_RATINGS,
                f"fuzzy: option {oname!r} rating for {cname!r}")
            if lerr:
                return _err(lerr)
            l, m, u = _tfn_avg(tfns)             # step 1 (ratings)
            if directions[cname] == "min":       # step 2
                l, m, u = _RATING_TOP - u, _RATING_TOP - m, _RATING_TOP - l
            wl, wm, wu = fused_w[cname]
            total = (total[0] + wl * l,          # step 3
                     total[1] + wm * m,
                     total[2] + wu * u)
        scores[oname] = (total[0] + total[1] + total[2]) / 3.0   # step 4
    if len(scores) != len(options):
        return _err("fuzzy: option names must be unique")

    ranked = _ranked(scores)
    return {"status": "ok", "ranked": ranked, "best": ranked[0]["name"]}


register(NodeSpec(
    type="decision.fuzzy", category="data", display_name="Fuzzy rank",
    description="Rank options from linguistic multi-stakeholder judgements "
                "(triangular fuzzy numbers). Weights very-low..very-high, "
                "ratings very-poor..very-good; stakeholders fused by fuzzy "
                "averaging, defuzzified by centroid. Wired inputs win over "
                "config. Pure + deterministic.",
    inputs=[Port(name="criteria", type=PortType.LIST),
            Port(name="options",  type=PortType.LIST)],
    outputs=[Port(name="ranked", type=PortType.LIST),
             Port(name="best",   type=PortType.STRING)],
    config_schema={
        "criteria": {"type": "array",
                     "description": "[{name, weights: [very-low..very-high "
                                    "per stakeholder], direction max|min}]"},
        "options":  {"type": "array",
                     "description": "[{name, ratings: {criterion: "
                                    "[very-poor..very-good per "
                                    "stakeholder]}}]"},
    },
    icon="≈"), _fuzzy_executor)
