"""LEAF: grouping-runs-as-node, over the REAL grand map.

The law made executable: a GROUP is a NODE whose value is the LIVE result of the
nodes inside it. Here that is proven against the actual 15-domain / 261-node
project data (grand_domains.json) — NOT stored numbers, NOT a mockup.

For each real grand-map domain we build, bottom-up from its inner primitives:
    status_score(child)  ->  avg(children)  ->  mul x100  ->  GROUP node
The GROUP's value is computed by RUNNING that inner subgraph, so editing any
inner status re-runs the group and the domain percentage changes live.

This file REUSES node_lang.Graph unchanged (no edits to node_lang.py / server.py).
Run it:  PYTHONIOENCODING=utf-8 python leaf_group_runs_as_node_on_real_map.py
"""
import json
import os

from .node_lang import Graph  # the real engine — reused, not rebuilt

DATA = os.environ.get("ARCHHUB_GRAND_MAP_PATH")


def build_domain_groups(graph, domains):
    """Build each domain as a GROUP node computed bottom-up from its inner
    status_score primitives. Returns {domain_key: group_id}."""
    groups = {}
    for dom in domains:
        key = dom.get("key") or dom["id"]
        child_scores = []
        for n in dom["nodes"]:
            sid = "s_" + n["id"]
            graph.add(sid, "status_score", params={"status": n.get("status", "vision")})
            child_scores.append(sid)
        # inner subgraph: avg of the child status scores, then x100 to a percentage
        avg_id = "avg_" + key
        pct_id = "pct_" + key
        graph.add(avg_id, "avg", inputs=child_scores)
        graph.add(pct_id, "mul", inputs=[avg_id], params={"factor": 100})
        # the GROUP node: its value is the LIVE result of the nodes inside it
        gid = "grp_" + key
        graph.group(gid, child_scores, pct_id)
        groups[key] = gid
    return groups


def main():
    if not DATA:
        raise RuntimeError(
            "ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is "
            "never embedded in the public product tree")
    domains = json.load(open(os.path.abspath(DATA), encoding="utf-8"))
    g = Graph()
    groups = build_domain_groups(g, domains)

    total_nodes = sum(len(d["nodes"]) for d in domains)
    print("Built %d GROUP nodes over %d real project nodes (engine evals so far: %d)"
          % (len(groups), total_nodes, g.evals))
    print("-" * 64)

    # Evaluate every domain GROUP by RUNNING its inner subgraph.
    vals = {}
    for dom in domains:
        key = dom.get("key") or dom["id"]
        vals[key] = g.eval(groups[key])

    for dom in domains:
        key = dom.get("key") or dom["id"]
        print("  %-10s %3d%%   (%2d inner nodes)  %s"
              % (key, vals[key], len(dom["nodes"]), dom.get("title", "")))

    # Hard invariants — same as the verify check, asserted here too.
    # 2026-07-02: counts asserted DYNAMICALLY against the live json. The old
    # hardcoded 261 rotted when the map grew (261->282) and false-failed this
    # flagship leaf — a stored number is exactly what this leaf exists to forbid.
    assert len(vals) == len(domains), (len(vals), len(domains))
    assert total_nodes >= 261, total_nodes
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in vals.values()), vals
    print("-" * 64)
    print("Invariants OK: DOMAINS %d  PROJECT_NODES %d  ALL_INT_0_100 %s"
          % (len(vals), total_nodes, all(isinstance(v, int) and 0 <= v <= 100
                                         for v in vals.values())))

    # PROVE it RUNS, not stored: flip the FIRST domain's children to 'live' and
    # show the GROUP re-computes itself live (grouping-runs-as-node).
    d0 = domains[0]
    key0 = d0.get("key") or d0["id"]
    before = g.eval(groups[key0])
    for n in d0["nodes"]:
        g.set_status("s_" + n["id"], "live")   # edit inner nodes
    after = g.eval(groups[key0])               # GROUP re-runs its subgraph
    print("-" * 64)
    print("LIVE re-run proof on domain '%s': %d%% -> set all inner nodes live -> %d%%"
          % (key0, before, after))
    assert after == 100, after

    print("OK 15 GROUP-nodes ran on %d real nodes; values %s"
          % (total_nodes, list(vals.items())[:3]))


if __name__ == "__main__":
    main()
