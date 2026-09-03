# -*- coding: utf-8 -*-
"""LEAF: REFERENCE — one node reads another node by id, LIVE.

SPEC.md §6 lists three floor primitives. ITERATE and AGGREGATE were the real
gaps (just added to the engine). REFERENCE was ALSO listed as a floor primitive,
but it is NOT a gap: the engine already ships it as the `ref` kind. This leaf
proves that claim by RUNNING it — REFERENCE is the primitive that makes
classification and watchers real, because it lets one node's value be defined as
"whatever that other node currently is."

What `ref` is, in the real engine (node_lang.py, unchanged here):

    ref node R  ->  params={"ref": A}      # holds the id of the node it reads
    eval(R)     ->  self.eval(p["ref"])    # returns A's CURRENT value, computed now

The "live, not stale" guarantee is structural, not incidental:
  - Graph._consumers() treats ANY param string equal to a node id as a read.
    So R (params.ref == A) is registered as a consumer of A.
  - Graph.set_param(A, ...) calls _invalidate(A), which walks consumers and
    drops R from the memo cache. The next eval(R) RE-COMPUTES from A's new value.
  - Graph.evals counts real computations, so we can prove eval(R) actually re-ran
    (it was not served a stale cached number).

Proves, by RUNNING it (no mocks, no engine edits):
  1. A = const 7 ; R = ref -> A ; eval(R) == 7
  2. set_param(A, value: 7 -> 99) ; eval(R) == 99   (live, RE-computed, not stale)
     + Graph.evals increased across that second eval(R) -> proof it recomputed.
  3. classifier pattern: a `ref` node reading ANOTHER node's *status*, so a
     downstream classifier reflects a live status change through the reference.

Prints FLOOR_REFERENCE_OK.

REUSES node_lang.Graph unchanged. A NEW self-contained file; edits nothing else.

Run:
  cd <NODE_LANGUAGE_ROOT>
  PYTHONIOENCODING=utf-8 python leaf_floor_reference.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph   # REUSE the real engine, do not rebuild


def classify(score):
    """A tiny pure classifier over a numeric status score (the kind of rule a
    real 'classifier' node would carry). live=1.0, partial=0.5, else dead."""
    if score >= 1.0:
        return "LIVE"
    if score >= 0.5:
        return "PARTIAL"
    return "DEAD"


def main():
    g = Graph()
    print("=" * 74)
    print("LEAF: REFERENCE — one node reads another by id, live (engine `ref` kind)")
    print("=" * 74)
    print()

    # ---- part 1: A = const 7 ; R = ref -> A ; eval(R) == 7 --------------------
    g.add("A", "const", params={"value": 7})
    g.add("R", "ref", params={"ref": "A"})          # R references A by its id

    r0 = g.eval("R")
    print("A = const 7 ; R = ref -> A")
    print("   eval(R) = %r" % r0)
    assert r0 == 7, ("REFERENCE did not read A's value", r0)

    # ---- part 2: change A live -> R re-computes to the NEW value --------------
    evals_before = g.evals
    g.set_param("A", "value", 99)                   # the referenced node changes, live
    r1 = g.eval("R")
    evals_after = g.evals
    print()
    print("set_param(A, value: 7 -> 99)")
    print("   eval(R) = %r   (expected 99, live)" % r1)
    assert r1 == 99, ("REFERENCE served a STALE value after A changed", r1)
    assert r1 != r0, ("reference did not track the change", r0, r1)
    # prove it actually RE-computed (was invalidated, not served from stale memo)
    assert evals_after > evals_before, (
        "eval(R) returned a cached value — reference was stale, not live",
        evals_before, evals_after,
    )
    print("   Graph.evals rose %d -> %d  ->  R was invalidated and RE-computed"
          % (evals_before, evals_after))

    # ---- part 3: the CLASSIFIER pattern ------------------------------------
    # A real use of REFERENCE: a classifier reads another node's STATUS through a
    # reference, so when that node's status flips, the classifier reflects it live.
    #   S            : a status_score node (status -> a number), the "subject"
    #   sref         : ref -> S            (the reference that makes it real)
    #   classify()   : the rule applied to the referenced score
    g.add("S", "status_score", params={"status": "partial"})
    g.add("sref", "ref", params={"ref": "S"})       # classifier reads S BY REFERENCE

    verdict_before = classify(g.eval("sref"))
    print()
    print("classifier pattern: sref = ref -> S(status_score)")
    print("   S.status = 'partial' -> ref score = %.1f -> class = %s"
          % (g.eval("sref"), verdict_before))
    assert verdict_before == "PARTIAL", verdict_before

    g.set_param("S", "status", "live")              # the subject's status flips, live
    verdict_after = classify(g.eval("sref"))
    print("   S.status -> 'live'   -> ref score = %.1f -> class = %s   (live through the reference)"
          % (g.eval("sref"), verdict_after))
    assert verdict_after == "LIVE", verdict_after
    assert verdict_after != verdict_before, (
        "classifier did not track the referenced status change", verdict_before, verdict_after,
    )

    print()
    print("FLOOR_REFERENCE_OK")
    print("   eval(R) 7 -> (A:=99) -> 99         live re-read, not stale (evals rose)")
    print("   ref->status: PARTIAL -> LIVE       classifier reflects referenced node live")
    print("   REFERENCE was NOT a gap: engine `ref` kind already provides it, proven by running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
