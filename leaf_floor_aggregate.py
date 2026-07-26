"""LEAF: AGGREGATE — a node that folds a LIST to ONE value (the floor primitive).

The law made executable (SPEC.md §6, The Floor):
    "aggregate | collapse a list to one (sum / collect / fold) | rollups, group values"

This REUSES node_lang.Graph unchanged. The engine already ships the `aggregate`
kind (op in sum|count|collect|max|min|avg over an `over` list — a node id whose
value is a list, or a literal list). This leaf proves that primitive end to end,
and proves it COMPOSES on the floor: aggregate over the output of an `iterate`
node (iterate-then-aggregate) is exactly the spreadsheet lacing-then-rollup move.

What is asserted:
  - build the list [10, 20, 30] as a real node in the graph
  - aggregate sum     == 60
  - aggregate count   == 3
  - aggregate max     == 30
  - aggregate collect == [10, 20, 30]
  - (belt) min == 10, avg == 20.0
  - COMPOSITION: aggregate(sum) over iterate(double) of [10,20,30] == 120
                 aggregate(count) over that same iterate           == 3

Run it:  PYTHONIOENCODING=utf-8 python leaf_floor_aggregate.py
"""
from node_lang import Graph  # the real engine — reused, not rebuilt


def main():
    g = Graph()

    # 1) Build the list [10, 20, 30] as a REAL node in the graph.
    #    A `sum` node's INPUTS feed it; but we want the raw list, so we hold the
    #    values in const nodes and expose the list via an `iterate`/`id` node,
    #    which yields [eval(x) for x in over] — a genuine list-valued node.
    g.add("a", "const", params={"value": 10})
    g.add("b", "const", params={"value": 20})
    g.add("c", "const", params={"value": 30})
    # `iterate` with op=id over the three const node ids -> the list [10, 20, 30].
    g.add("the_list", "iterate", params={"over": ["a", "b", "c"], "op": "id"})

    the_list = g.eval("the_list")
    print("the_list (list node)         -> %r" % (the_list,))
    assert the_list == [10, 20, 30], the_list

    # 2) AGGREGATE folds that list to ONE value, per op. Each is its own node,
    #    all reading the SAME list node — one primitive, many rollups.
    g.add("agg_sum", "aggregate", params={"over": "the_list", "op": "sum"})
    g.add("agg_count", "aggregate", params={"over": "the_list", "op": "count"})
    g.add("agg_max", "aggregate", params={"over": "the_list", "op": "max"})
    g.add("agg_min", "aggregate", params={"over": "the_list", "op": "min"})
    g.add("agg_avg", "aggregate", params={"over": "the_list", "op": "avg"})
    g.add("agg_collect", "aggregate", params={"over": "the_list", "op": "collect"})

    got = {
        "sum": g.eval("agg_sum"),
        "count": g.eval("agg_count"),
        "max": g.eval("agg_max"),
        "min": g.eval("agg_min"),
        "avg": g.eval("agg_avg"),
        "collect": g.eval("agg_collect"),
    }
    for op, val in got.items():
        print("  aggregate %-8s -> %r" % (op, val))

    # The checks the leaf MUST pass:
    assert got["sum"] == 60, got["sum"]
    assert got["count"] == 3, got["count"]
    assert got["max"] == 30, got["max"]
    assert got["collect"] == [10, 20, 30], got["collect"]
    # belt-and-suspenders on the remaining folds:
    assert got["min"] == 10, got["min"]
    assert got["avg"] == 20.0, got["avg"]

    # 3) COMPOSITION on the floor: aggregate over the OUTPUT of an iterate node.
    #    iterate(double) of [10,20,30] -> [20,40,60]; aggregate(sum) -> 120.
    g.add("doubled", "iterate", params={"over": "the_list", "op": "double"})
    doubled = g.eval("doubled")
    print("-" * 60)
    print("iterate(double) of the_list  -> %r" % (doubled,))
    assert doubled == [20, 40, 60], doubled

    g.add("agg_over_iter", "aggregate", params={"over": "doubled", "op": "sum"})
    g.add("count_over_iter", "aggregate", params={"over": "doubled", "op": "count"})
    composed_sum = g.eval("agg_over_iter")
    composed_count = g.eval("count_over_iter")
    print("aggregate(sum)  over iterate -> %r" % (composed_sum,))
    print("aggregate(count) over iterate-> %r" % (composed_count,))
    assert composed_sum == 120, composed_sum          # iterate then aggregate COMPOSES
    assert composed_count == 3, composed_count

    # 4) It RUNS incrementally: edit a source const, and the aggregate follows.
    g.set_param("a", "value", 100)                    # 10 -> 100
    assert g.eval("the_list") == [100, 20, 30]
    assert g.eval("agg_sum") == 150                   # 100+20+30, recomputed live
    assert g.eval("agg_over_iter") == 300             # (100+20+30)*2, through the compose
    print("-" * 60)
    print("edit a=100 -> sum=%d, composed(sum*2)=%d  (live recompute)"
          % (g.eval("agg_sum"), g.eval("agg_over_iter")))

    print("FLOOR_AGGREGATE_OK")


if __name__ == "__main__":
    main()
