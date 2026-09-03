# -*- coding: utf-8 -*-
"""LEAF: the history tree is APPEND-ONLY — a committed past version cannot be
rewritten, yet revert still restores it.

Exercised against the REAL running interpreter (node_lang.Graph / node_lang.History),
not a mock. Reuses the engine's _Frozen sealed-snapshot mechanism; edits nothing.

The single claim, made executable:

  1) commit v0          -> an immutable, sealed deep-copied snapshot of the live graph.
  2) edit live          -> the engine recomputes; the live value moves off v0.
  3) attempt to mutate the v0 snapshot IN PLACE (rewrite history) -> REFUSED.
        - __setitem__ on the sealed snapshot raises (append-only guard).
        - __delitem__ on the sealed snapshot raises (append-only guard).
        - the committed v0 value is byte-for-byte what it was at commit time.
  4) revert to v0       -> the live graph restores to the EXACT v0 value.

So: the past is protected (you cannot rewrite a committed version), AND the past
is still reachable (revert rerolls the live graph to it). Both at once.

Prints HISTORY_APPEND_ONLY_OK only if every assertion above truly holds.
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph, History


def run():
    print("=" * 72)
    print("LEAF — history tree is APPEND-ONLY: committed past is immutable, yet")
    print("       revert still restores it. (real engine, executed)")
    print("=" * 72)

    # ---- build a tiny running program: (a=5) + (b=3) -> sum -> group(out=sum) ----
    g = Graph()
    g.add("a", "const", params={"value": 5})
    g.add("b", "const", params={"value": 3})
    g.add("s", "sum", inputs=["a", "b"])
    g.group("grp", ["a", "b"], "s")          # GROUP runs as a node: value = round(sum)

    h = History()

    # ---- 1) COMMIT v0 : immutable sealed snapshot of the live graph ----------
    v0 = h.commit(g, "v0 baseline")
    v0_value = g.eval("grp")                  # the value living in v0
    snap = h.versions[v0]                     # the sealed _Frozen snapshot
    # exact stored payload captured at commit time (deep copy so later asserts are honest)
    v0_stored_a = snap["session"]["nodes"]["a"]["params"]["value"]
    v0_stored_full = copy.deepcopy(dict(snap["session"]["nodes"]))
    print(f"   1) committed v0 ; live group 'grp' = {v0_value} ; v0 stores a.value = {v0_stored_a}")

    # ---- 2) EDIT LIVE : the engine recomputes, value moves off v0 -----------
    g.set_param("a", "value", 1000)
    edited_value = g.eval("grp")
    print(f"   2) edited live a.value 5 -> 1000 ; live group 'grp' = {edited_value}  (incremental)")
    assert edited_value != v0_value, ("live edit had no effect", v0_value, edited_value)

    # ---- 3) ATTEMPT TO REWRITE THE v0 SNAPSHOT IN PLACE : must be REFUSED -----
    # (a) rewrite a top-level key on the sealed snapshot -> append-only guard fires
    refused_set = False
    try:
        snap["label"] = "TAMPERED v0"
    except TypeError as e:
        refused_set = True
        print(f"   3a) snapshot[set] REFUSED (append-only): {e}")
    assert refused_set, "sealed snapshot allowed in-place rewrite via __setitem__ (history not protected)"

    # (b) delete a key from the sealed snapshot -> append-only guard fires
    refused_del = False
    try:
        del snap["session"]
    except TypeError as e:
        refused_del = True
        print(f"   3b) snapshot[del] REFUSED (append-only): {e}")
    assert refused_del, "sealed snapshot allowed in-place delete via __delitem__ (history not protected)"

    # (c) even a LIVE edit AFTER the commit must not have leaked into v0's stored payload
    #     (commit deep-copies; the snapshot must still hold the original numbers).
    snap_a_now = h.versions[v0]["session"]["nodes"]["a"]["params"]["value"]
    print(f"   3c) v0 still stores a.value = {snap_a_now}  (live edit never leaked into the committed past)")
    assert snap_a_now == v0_stored_a == 5, ("committed v0 was mutated", v0_stored_a, snap_a_now)
    assert dict(h.versions[v0]["session"]["nodes"]) == v0_stored_full, "committed v0 payload changed under us"
    assert h.versions[v0]["label"] == "v0 baseline", ("v0 label was rewritten", h.versions[v0]["label"])

    # ---- 4) REVERT to v0 : the past is immutable BUT still reachable ---------
    lab = h.revert(g, v0)
    reverted_value = g.eval("grp")
    print(f"   4) reverted to '{lab}' ; live group 'grp' = {reverted_value}")
    assert reverted_value == v0_value, ("revert did not restore the exact v0 value", v0_value, reverted_value)
    assert g.eval("a") == 5, ("revert did not restore a.value", g.eval("a"))

    # ---- 5) and v0 is STILL intact after a revert (revert reads, never rewrites) ----
    assert h.versions[v0]["session"]["nodes"]["a"]["params"]["value"] == 5, "revert mutated the snapshot it read"
    assert h.versions[v0]["label"] == "v0 baseline"

    print("-" * 72)
    print(f"   ASSERT OK  v0={v0_value}  edited={edited_value}  reverted={reverted_value}")
    print("   committed past is APPEND-ONLY (set+del refused, payload unchanged) AND revert restores it")
    print("   HISTORY_APPEND_ONLY_OK")
    return v0_value, edited_value, reverted_value


if __name__ == "__main__":
    run()
