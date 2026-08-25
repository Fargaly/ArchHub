"""LEAF — the REAL personal-brain COURT as the anti-lie gate over the
node-language artifacts.

This leaf wires the node language to the SAME external court that gates every
ROMA leaf (`personal_brain.court_harness.convene_court`, the three-lens jury).
It proves the replica is *court-proven*, not self-asserted, by running the jury
on REALITY against `node_lang.py` on disk:

  1. REAL_PASS_GREEN     — a TRUE file predicate (node_lang.py exists AND
                           contains `def group`) → the court FAILS TO REFUTE →
                           verdict GREEN.
  2. MISSING_REFUTED     — a claim about a file that does NOT exist
                           (node_lang.py.NOPE) → the artifact lens REFUTES →
                           verdict RED.
  3. SELF_CERTIFY_REFUTED— a leaf whose judge == executor (judged_by ==
                           claimed_by) → the independence/anti-tamper lens
                           REFUTES → not green.

The gate runs on the REAL artifact (the live engine file) — no mocks, no
seeds. It ALSO exercises the real `node_lang.Graph` (the thing being gated):
it builds a graph that includes a `group` kind, evaluates it incrementally,
and gates the engine on whether the live source backing that capability is on
disk. So the artifact the court judges is the very engine this leaf just ran.

REUSE, not rebuild: imports `node_lang` (existing engine) + `court_harness`
(existing brain court). Adds nothing to either; a NEW self-contained file.

Run:
  cd <NODE_LANGUAGE_ROOT>
  PYTHONIOENCODING=utf-8 python leaf_court_gate_refutes_on_real_artifact.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# ─── locate the two REAL systems we reuse (engine here, court in the brain) ───
HERE = Path(__file__).resolve().parent                      # 13.NODE-LANGUAGE/
NODE_LANG_PY = HERE / "node_lang.py"                        # the REAL engine file
BRAIN_SRC = (
    HERE.parents[1] / "12.PRODUCTION" / "personal-brain-mcp" / "src"
)                                                           # personal_brain pkg root

# import the REAL node-language engine (same dir)
sys.path.insert(0, str(HERE))
# import the REAL brain court (the jury that gates every ROMA leaf)
sys.path.insert(0, str(BRAIN_SRC))

from . import node_lang  # the existing engine — class Graph, kinds incl. "group"
from personal_brain.court_harness import convene_court  # the existing jury


def exercise_engine() -> tuple[float, str, float]:
    """USE the real node_lang.Graph: build a tiny graph that includes a `group`,
    evaluate it incrementally, and return (sum value, group id, group value).
    This is the live capability the court will then gate on the real source."""
    g = node_lang.Graph()
    g.add("a", "const", params={"value": 10})
    g.add("b", "const", params={"value": 20})
    g.add("s", "sum")
    g.wire("s", "a")  # wire(dst, src): s reads a
    g.wire("s", "b")  # wire(dst, src): s reads b
    # the `group` kind named in the engine spec — collapse a + b + s,
    # the group's running value = its output subgraph (node "s")
    grp = g.group("box", ["a", "b", "s"], out_id="s")
    total = g.eval("s")          # incremental, memoized cook → returns the value
    group_val = g.eval(grp)      # the group RUNS: value == round(eval(out))
    return total, grp, group_val


def gate_node_language() -> dict[str, "object"]:
    """Run the REAL court three ways over the node-language artifact on disk."""
    real = str(NODE_LANG_PY)

    # CASE 1 — true predicate against the live engine file → FAIL TO REFUTE → GREEN
    g = convene_court(
        node_id="nl_engine",
        gate_kind="file_exists",
        gate_spec={"path": real, "contains": "def group"},
        claimed_by="executor_A",
        judged_by="roma-court",
    )
    # CASE 2 — missing-file claim → artifact lens REFUTES → RED
    r2 = convene_court(
        node_id="nl_missing",
        gate_kind="file_exists",
        gate_spec={"path": real + ".NOPE"},
        claimed_by="executor_A",
        judged_by="roma-court",
    )
    # CASE 3 — self-certification (judge == executor) → independence lens REFUTES
    r3 = convene_court(
        node_id="nl_self",
        gate_kind="file_exists",
        gate_spec={"path": real},
        claimed_by="roma-court",
        judged_by="roma-court",
    )
    return {"real": g, "missing": r2, "self": r3}


def main() -> int:
    # 1) prove the engine actually runs (the capability under the gate)
    total, grp, group_val = exercise_engine()
    assert total == 30 and group_val == 30, f"engine eval wrong: {total!r}/{group_val!r}"
    print(f"ENGINE_OK   node_lang.Graph eval → sum=10+20={total}, "
          f"group={grp!r} runs out subgraph → {group_val}")

    # 2) run the REAL court over the node-language artifact on disk
    v = gate_node_language()
    g, r2, r3 = v["real"], v["missing"], v["self"]

    print(
        f"REAL_PASS   green={g.green} verdict={g.verdict!r}\n"
        f"            reason: {g.reason}"
    )
    print(
        f"MISSING     green={r2.green} verdict={r2.verdict!r}\n"
        f"            reason: {r2.reason}"
    )
    print(
        f"SELF_CERT   green={r3.green} verdict={r3.verdict!r}\n"
        f"            reason: {r3.reason}"
    )

    # 3) THE assertions — the court ran on reality, so this is court-proven
    assert g.green and g.verdict == "green", ("REAL must be GREEN", g.verdict)
    assert (not r2.green) and r2.verdict == "red", ("MISSING must be RED", r2.verdict)
    assert not r3.green, ("SELF-CERTIFY must be REFUTED", r3.green)

    print(
        "COURT_OK real GREEN, missing REFUTED red, self-certify REFUTED "
        f"(Verified: REAL_PASS_GREEN {g.green} {g.verdict}; "
        f"MISSING_REFUTED {not r2.green} {r2.verdict}; "
        f"SELF_CERTIFY_REFUTED {not r3.green}.)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
