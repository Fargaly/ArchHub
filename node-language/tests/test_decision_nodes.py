"""decision.topsis + decision.fuzzy — SPEC §6 decision/score family.

Every cook goes through a REAL WorkflowRunner graph (dispatch by
node.type), never by calling the executor function directly.

Pins:
  (a) TOPSIS hand-worked 3-option / 3-criteria example — expected
      closeness coefficients derived by hand in the comments, 1e-6.
  (b) Flipping a criterion's direction flips the ranking.
  (c) A weight change changes the ranking, and recook_from (the
      param-edit dirty-propagation path) picks it up downstream.
  (d) Fuzzy: two stakeholders disagreeing — fused ranking matches the
      hand calculation.
  (e) Determinism: the same cook twice (same runner and a fresh
      runner) is byte-identical.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes registers every built-in type, decision.* included.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows.registry import get as _get_spec
from workflows.runner import WorkflowRunner


# ── shared fixture data ──────────────────────────────────────────────
#
# 3 options x 3 criteria (a contractor-selection toy):
#            cost(min)  quality(max)  speed(max)
#   A          100          7            5
#   B           80          6            8
#   C          120          9            6

OPTIONS = [
    {"name": "A", "values": {"cost": 100, "quality": 7, "speed": 5}},
    {"name": "B", "values": {"cost": 80,  "quality": 6, "speed": 8}},
    {"name": "C", "values": {"cost": 120, "quality": 9, "speed": 6}},
]


def _topsis_graph(criteria, options=OPTIONS):
    """options flow over a REAL wire (data.constant -> decision.topsis);
    criteria sit in config. Proves runner dispatch by node.type."""
    return {
        "nodes": [
            {"id": "opts", "type": "data.constant",
             "config": {"value": options}},
            {"id": "rank", "type": "decision.topsis",
             "config": {"criteria": criteria}},
        ],
        "wires": [
            {"from": ["opts", "value"], "to": ["rank", "options"]},
        ],
    }


def _scores(out):
    assert out.get("status") == "ok", out
    return {r["name"]: r["score"] for r in out["ranked"]}


def _order(out):
    return [r["name"] for r in out["ranked"]]


# ── (a) hand-worked TOPSIS ───────────────────────────────────────────
def test_topsis_hand_worked_example():
    """Weights cost 0.5 (min), quality 0.3 (max), speed 0.2 (max).

    HAND CALCULATION (standard TOPSIS):
    1. Column norms:
         cost    = sqrt(100^2 + 80^2 + 120^2) = sqrt(30800) = 175.499288...
         quality = sqrt(7^2 + 6^2 + 9^2)      = sqrt(166)   =  12.884099...
         speed   = sqrt(5^2 + 8^2 + 6^2)      = sqrt(125)   =  11.180340...
    2. Weighted normalized matrix v_ij = w_j * x_ij / norm_j
       (weights already sum to 1.0):
         A: cost 0.5*100/175.4993 = 0.284901   quality 0.3*7/12.8841 = 0.162992   speed 0.2*5/11.1803 = 0.089443
         B: cost 0.5* 80/175.4993 = 0.227921   quality 0.3*6/12.8841 = 0.139707   speed 0.2*8/11.1803 = 0.143108
         C: cost 0.5*120/175.4993 = 0.341882   quality 0.3*9/12.8841 = 0.209561   speed 0.2*6/11.1803 = 0.107331
    3. Ideal A+ (cost is MIN): (0.227921, 0.209561, 0.143108)
       Anti-ideal A-:          (0.341882, 0.139707, 0.089443)
    4. Distances:
         A: D+ = sqrt(0.056980^2 + 0.046569^2 + 0.053666^2) = 0.091173
            D- = sqrt(0.056980^2 + 0.023285^2 + 0.000000^2) = 0.061556
         B: D+ = sqrt(0^2 + 0.069854^2 + 0^2)               = 0.069854
            D- = sqrt(0.113961^2 + 0^2 + 0.053666^2)        = 0.125966
         C: D+ = sqrt(0.113961^2 + 0^2 + 0.035777^2)        = 0.119446
            D- = sqrt(0^2 + 0.069854^2 + 0.017889^2)        = 0.072108
    5. Closeness C_i = D-/(D+ + D-):
         A = 0.061556 / 0.152729 = 0.403281...
         B = 0.125966 / 0.195820 = 0.643273...
         C = 0.072108 / 0.191554 = 0.376439...
       (full precision: A 0.4032812965776307, B 0.6432728845471284,
        C 0.37643864950951283)  ->  ranking B > A > C.
    """
    criteria = [
        {"name": "cost",    "weight": 0.5, "direction": "min"},
        {"name": "quality", "weight": 0.3, "direction": "max"},
        {"name": "speed",   "weight": 0.2, "direction": "max"},
    ]
    runner = WorkflowRunner(_topsis_graph(criteria))
    out = runner.pull("rank")
    s = _scores(out)
    assert abs(s["A"] - 0.4032812965776307) < 1e-6
    assert abs(s["B"] - 0.6432728845471284) < 1e-6
    assert abs(s["C"] - 0.37643864950951283) < 1e-6
    assert _order(out) == ["B", "A", "C"]
    assert out["best"] == "B"


# ── (b) direction flag flips the ranking ─────────────────────────────
def test_topsis_direction_flip_reverses_ranking():
    """Single criterion `cost`, weight 1.0.

    direction=min: ideal is the cheapest (B=80), anti-ideal the dearest
    (C=120). With one criterion the closeness collapses to a linear
    position between the extremes:
        B = (0.341882-0.227921)/(0.341882-0.227921) = 1.0
        A = (0.341882-0.284901)/0.113961            = 0.5
        C =                                          0.0
    direction=max mirrors it exactly: C=1.0, A=0.5, B=0.0.
    """
    g_min = _topsis_graph([{"name": "cost", "weight": 1.0,
                            "direction": "min"}])
    out_min = WorkflowRunner(g_min).pull("rank")
    s_min = _scores(out_min)
    assert _order(out_min) == ["B", "A", "C"]
    assert abs(s_min["B"] - 1.0) < 1e-6
    assert abs(s_min["A"] - 0.5) < 1e-6
    assert abs(s_min["C"] - 0.0) < 1e-6

    g_max = _topsis_graph([{"name": "cost", "weight": 1.0,
                            "direction": "max"}])
    out_max = WorkflowRunner(g_max).pull("rank")
    s_max = _scores(out_max)
    assert _order(out_max) == ["C", "A", "B"]
    assert abs(s_max["C"] - 1.0) < 1e-6
    assert abs(s_max["A"] - 0.5) < 1e-6
    assert abs(s_max["B"] - 0.0) < 1e-6


# ── (c) weight change re-ranks + dirty propagation via recook_from ──
def test_topsis_weight_change_recooks_downstream():
    """Cost-heavy weights (0.7/0.2/0.1) rank the cheapest first: B.
    Quality-heavy weights (0.1/0.8/0.1) rank the best-quality first: C.

    Hand-checked closeness for the two configs (same pipeline as the
    worked example, weights swapped):
        cost-heavy:    B 0.7764913824383223, A 0.4753208141067194,
                       C 0.2280203716276302
        quality-heavy: C 0.8655287228925792, A 0.33105794220219514,
                       B 0.15895736874075087

    The `best` output feeds a downstream data.passthrough sink — after
    the config edit, recook_from("rank") (the param-edit path) must
    propagate the NEW winner through the wire to the sink."""
    cost_heavy = [
        {"name": "cost",    "weight": 0.7, "direction": "min"},
        {"name": "quality", "weight": 0.2, "direction": "max"},
        {"name": "speed",   "weight": 0.1, "direction": "max"},
    ]
    g = _topsis_graph(cost_heavy)
    g["nodes"].append({"id": "sink", "type": "data.passthrough",
                       "config": {}})
    g["wires"].append({"from": ["rank", "best"], "to": ["sink", "value"]})

    runner = WorkflowRunner(g)
    first = runner.pull("sink")
    assert first["value"] == "B"
    s1 = _scores(runner.pull("rank"))
    assert abs(s1["B"] - 0.7764913824383223) < 1e-6

    # Param edit: founder drags the quality weight up.
    runner.nodes_by_id["rank"]["config"]["criteria"] = [
        {"name": "cost",    "weight": 0.1, "direction": "min"},
        {"name": "quality", "weight": 0.8, "direction": "max"},
        {"name": "speed",   "weight": 0.1, "direction": "max"},
    ]
    result = runner.recook_from("rank")
    assert result["status"] == "ok"
    assert "sink" in result["sinks"]
    # The sink saw the new winner — dirty propagation worked.
    assert result["results"]["sink"]["value"] == "C"
    s2 = _scores(runner.pull("rank"))
    assert abs(s2["C"] - 0.8655287228925792) < 1e-6
    assert _order(runner.pull("rank")) == ["C", "A", "B"]


# ── (d) fuzzy: two disagreeing stakeholders ──────────────────────────
def test_fuzzy_two_stakeholders_fused_ranking():
    """Two stakeholders, two criteria (cost-effectiveness + quality),
    two options. Stakeholder 2 rates A's quality POOR where stakeholder
    1 says MODERATE — the fused average drags A below B.

    HAND CALCULATION (weight TFNs on [0,1], rating TFNs on [0,10]):
    1. Fused weights (fuzzy average of the two stakeholders):
         value:   avg((0.50,0.75,1.00) high, (0.75,1.00,1.00) very-high)
                = (0.625, 0.875, 1.000)
         quality: avg((0.25,0.50,0.75) medium, (0.50,0.75,1.00) high)
                = (0.375, 0.625, 0.875)
    2. Fused ratings:
         A.value:   avg(good(5,7.5,10), very-good(7.5,10,10)) = (6.25, 8.75, 10.0)
         A.quality: avg(moderate(2.5,5,7.5), poor(0,2.5,5))   = (1.25, 3.75, 6.25)
         B.value:   avg(moderate(2.5,5,7.5), good(5,7.5,10))  = (3.75, 6.25, 8.75)
         B.quality: avg(good, good)                           = (5.0, 7.5, 10.0)
    3. Weighted sums (component-wise TFN product, then add):
         A: value   (0.625*6.25, 0.875*8.75, 1.0*10)   = (3.90625, 7.65625, 10.0)
            quality (0.375*1.25, 0.625*3.75, 0.875*6.25) = (0.46875, 2.34375, 5.46875)
            total = (4.375, 10.0, 15.46875)
         B: value   (0.625*3.75, 0.875*6.25, 1.0*8.75) = (2.34375, 5.46875, 8.75)
            quality (0.375*5, 0.625*7.5, 0.875*10)     = (1.875, 4.6875, 8.75)
            total = (4.21875, 10.15625, 17.5)
    4. Centroid defuzzify:
         A = (4.375 + 10.0 + 15.46875) / 3 = 29.84375 / 3 = 9.9479166666...
         B = (4.21875 + 10.15625 + 17.5) / 3 = 31.875 / 3 = 10.625
       ->  B > A despite A's stronger `value` ratings.
    """
    criteria = [
        {"name": "value",   "weights": ["high", "very-high"]},
        {"name": "quality", "weights": ["medium", "high"]},
    ]
    options = [
        {"name": "A", "ratings": {"value":   ["good", "very-good"],
                                  "quality": ["moderate", "poor"]}},
        {"name": "B", "ratings": {"value":   ["moderate", "good"],
                                  "quality": ["good", "good"]}},
    ]
    g = {
        "nodes": [
            {"id": "opts", "type": "data.constant",
             "config": {"value": options}},
            {"id": "rank", "type": "decision.fuzzy",
             "config": {"criteria": criteria}},
        ],
        "wires": [
            {"from": ["opts", "value"], "to": ["rank", "options"]},
        ],
    }
    out = WorkflowRunner(g).pull("rank")
    s = _scores(out)
    assert abs(s["A"] - (29.84375 / 3)) < 1e-6      # 9.947916666...
    assert abs(s["B"] - 10.625) < 1e-6
    assert _order(out) == ["B", "A"]
    assert out["best"] == "B"


def test_fuzzy_min_direction_inverts_rating():
    """One stakeholder, one MIN criterion `cost`, weight very-high
    (0.75, 1.0, 1.0). direction=min inverts the rating TFN on [0,10]:

      X rated very-poor (0,0,2.5)  -> inverted (7.5, 10, 10)   (cheap!)
        weighted (0.75*7.5, 1*10, 1*10) = (5.625, 10, 10)
        centroid = 25.625 / 3 = 8.541666...
      Y rated very-good (7.5,10,10) -> inverted (0, 0, 2.5)    (dear!)
        weighted (0, 0, 2.5)
        centroid = 2.5 / 3 = 0.833333...

    So the LOW-cost option X ranks first."""
    g = {
        "nodes": [
            {"id": "rank", "type": "decision.fuzzy", "config": {
                "criteria": [{"name": "cost", "weights": ["very-high"],
                              "direction": "min"}],
                "options": [
                    {"name": "X", "ratings": {"cost": ["very-poor"]}},
                    {"name": "Y", "ratings": {"cost": ["very-good"]}},
                ],
            }},
        ],
        "wires": [],
    }
    out = WorkflowRunner(g).pull("rank")
    s = _scores(out)
    assert abs(s["X"] - (25.625 / 3)) < 1e-6
    assert abs(s["Y"] - (2.5 / 3)) < 1e-6
    assert _order(out) == ["X", "Y"]


# ── (e) determinism ──────────────────────────────────────────────────
def test_same_cook_twice_is_identical():
    """Same runner pulled twice AND a fresh runner over the same graph
    produce byte-identical outputs (memo-safe, no hidden state)."""
    criteria = [
        {"name": "cost",    "weight": 0.5, "direction": "min"},
        {"name": "quality", "weight": 0.3, "direction": "max"},
        {"name": "speed",   "weight": 0.2, "direction": "max"},
    ]
    g = _topsis_graph(criteria)
    r1 = WorkflowRunner(g)
    first = r1.pull("rank")
    second = r1.pull("rank")          # cache path
    assert first == second
    r1.mark_dirty("rank")
    third = r1.pull("rank")           # forced re-cook path
    assert first == third
    fresh = WorkflowRunner(_topsis_graph(criteria)).pull("rank")
    assert first == fresh

    # Fuzzy too.
    fg = {
        "nodes": [{"id": "rank", "type": "decision.fuzzy", "config": {
            "criteria": [{"name": "q", "weights": ["high", "low"]}],
            "options": [
                {"name": "A", "ratings": {"q": ["good", "poor"]}},
                {"name": "B", "ratings": {"q": ["moderate", "moderate"]}},
            ],
        }}],
        "wires": [],
    }
    f1 = WorkflowRunner(fg).pull("rank")
    f2 = WorkflowRunner(fg).pull("rank")
    assert f1 == f2


# ── registration sanity ──────────────────────────────────────────────
def test_specs_registered_with_ports():
    for t in ("decision.topsis", "decision.fuzzy"):
        tup = _get_spec(t)
        assert tup is not None, f"{t} not registered"
        spec, executor = tup
        assert callable(executor)
        assert [p.name for p in spec.inputs] == ["criteria", "options"]
        assert [p.name for p in spec.outputs] == ["ranked", "best"]


def test_error_shape_on_bad_input():
    """Malformed problems return the module's uniform error shape via a
    real runner cook — never a raise."""
    g = {"nodes": [{"id": "rank", "type": "decision.topsis",
                    "config": {"criteria": [], "options": OPTIONS}}],
         "wires": []}
    out = WorkflowRunner(g).pull("rank")
    assert out["status"] == "error"
    assert out["ranked"] == []
    assert "criteria" in out["error"]

    g2 = {"nodes": [{"id": "rank", "type": "decision.fuzzy", "config": {
        "criteria": [{"name": "q", "weights": ["superb"]}],   # unknown term
        "options": [{"name": "A", "ratings": {"q": ["good"]}}],
    }}], "wires": []}
    out2 = WorkflowRunner(g2).pull("rank")
    assert out2["status"] == "error"
    assert "superb" in out2["error"]
