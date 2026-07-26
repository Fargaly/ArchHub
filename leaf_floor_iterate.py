"""LEAF: ITERATE — do-for-each over a LIST, done visually as a NODE (SPEC.md §6).

The law made executable (SPEC.md §6, the Floor):
    | **iterate** | do for each item in a list (the spreadsheet lacing) |
      processing collections visually instead of dropping to code |

ITERATE runs a body op over every item of a list (the spreadsheet lacing),
producing a NEW list. Here it is a node, not code: an `iterate` node points at a
source list node via its `over` param and names a pure unary body op. Its value is
`[op(x) for x in source]`, computed by the engine — the user never writes a loop.

This REUSES node_lang.Graph unchanged (the `iterate`/`map` kind already ships in
the engine). This leaf builds the scenario, RUNS it, and proves:
  1) the output list equals the expected mapped list;
  2) editing the SOURCE list re-runs the iterate INCREMENTALLY (only the dirty
     nodes recompute — proven by the engine's real-computation counter g.evals);
  3) it round-trips through a session (save/load) and still maps correctly.

Run it:  PYTHONIOENCODING=utf-8 python leaf_floor_iterate.py
"""
import json

from node_lang import Graph  # the real engine — reused, not rebuilt


def main():
    g = Graph()

    # 1) A source LIST node: the spreadsheet column [1,2,3,4,5].
    #    (A `const` whose value is a list is a first-class list-producing node.)
    SRC = [1, 2, 3, 4, 5]
    g.add("src_list", "const", params={"value": list(SRC)})

    # 2) The ITERATE node: do-for-each over src_list, body op = double.
    #    Visually this is ONE node wired to the list; no user-written loop.
    BODY = "double"
    g.add("each_double", "iterate", params={"over": "src_list", "op": BODY})

    # --- RUN: assert the output list equals the expected mapped list ---------
    out = g.eval("each_double")
    expected = [x * 2 for x in SRC]          # the body op applied to every item
    print("input  (src_list)   -> %r" % (SRC,))
    print("iterate op          -> %r" % (BODY,))
    print("output (each_double)-> %r" % (out,))
    assert out == expected, "iterate must map every item: %r != %r" % (out, expected)
    assert len(out) == len(SRC), "iterate must preserve list length (one out per in)"

    # It really is a NEW list, not the source mutated in place.
    assert out is not SRC and g.eval("src_list") == SRC, "source list untouched"

    # --- INCREMENTAL: editing the SOURCE list re-runs iterate, and ONLY the ---
    # --- dirty nodes recompute (cache hit everywhere else). -----------------
    # Add an unrelated const to prove it is NOT recomputed on the edit.
    g.add("unrelated", "const", params={"value": 99})
    assert g.eval("unrelated") == 99          # prime its cache

    evals_before = g.evals                    # real-computation counter
    NEW_SRC = [10, 20, 30]                     # a smaller, different list
    g.set_param("src_list", "value", list(NEW_SRC))   # EDIT the source column

    out2 = g.eval("each_double")              # the iterate re-runs automatically
    expected2 = [x * 2 for x in NEW_SRC]
    print("-" * 60)
    print("edit src_list ->    %r" % (NEW_SRC,))
    print("iterate re-runs ->  %r" % (out2,))
    assert out2 == expected2, "iterate must re-run on source edit: %r != %r" % (out2, expected2)

    evals_after = g.evals
    recomputed = evals_after - evals_before
    print("real recomputes after edit: %d  (only src_list + each_double)" % recomputed)
    # Exactly the two dirty nodes recompute: the edited source and its consumer.
    # The unrelated const stays cached (NOT recomputed) -> incremental, not full.
    assert recomputed == 2, "expected 2 dirty recomputes, got %d (not incremental)" % recomputed
    assert g._cache.get("unrelated") == 99, "unrelated node must stay cached (not re-run)"

    # --- ROUND-TRIP: save the graph as a session, reload, still maps --------
    session = g.to_session()
    reloaded = Graph.from_session(json.loads(json.dumps(session)))
    assert reloaded.eval("each_double") == expected2, "iterate must survive save/load"
    print("-" * 60)
    print("session round-trip  -> %r  (iterate survives save/load)" % (reloaded.eval("each_double"),))

    print("FLOOR_ITERATE_OK  input=%r  output=%r" % (NEW_SRC, out2))


if __name__ == "__main__":
    main()
