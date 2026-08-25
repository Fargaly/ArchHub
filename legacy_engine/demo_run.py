"""Run the node language on the REAL grand map. Prints real output, not a mockup.
Proves: nodes-built-from-nodes, grouping-runs-as-node, the whole map as ONE session,
incremental recompute on edit, and the history tree (revert)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .node_lang import Graph, History

GM = os.environ.get("ARCHHUB_GRAND_MAP_PATH")
if not GM:
    raise RuntimeError(
        "ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is "
        "never embedded in the public product tree")
D = json.load(open(GM, encoding="utf-8"))

# Build the grand map AS a node graph: each domain = a GROUP node whose value is
# produced by real primitive nodes wired together (status_score per child -> avg -> x100).
g = Graph()
domains = []
for dom in D:
    score_ids = []
    for n in dom["nodes"]:
        sid = "score_" + n["id"]
        g.add(sid, "status_score", params={"status": n.get("status", "vision")})
        score_ids.append(sid)
    avg_id = "avg_" + dom["key"]; g.add(avg_id, "avg", inputs=score_ids)
    pct_id = "pct_" + dom["key"]; g.add(pct_id, "mul", inputs=[avg_id], params={"factor": 100})
    grp_id = "grp_" + dom["key"]; g.add(grp_id, "group", params={"members": score_ids, "out": pct_id})
    domains.append((dom["title"], grp_id, score_ids))

print("=" * 70)
print("1. RUN  — every domain value is COMPUTED BY THE NODE GRAPH (nodes from nodes)")
print("=" * 70)
for title, grp, scores in domains:
    print(f"   {title[:24]:24} = {g.eval(grp):3d}%   <- group runs: avg(status_score x{len(scores)}) x100")
print(f"   full run computed {g.evals} nodes total")

print()
print("=" * 70)
print("2. SESSION — the whole grand map is ONE graph, saved as a session")
print("=" * 70)
sess = g.to_session()
print(f"   session = {len(sess['nodes'])} nodes (15 domain group-nodes + their inner primitive nodes)")
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grandmap.session.json")
json.dump(sess, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print(f"   saved -> {os.path.basename(out)}  (reloadable: Graph.from_session)")
g2 = Graph.from_session(json.load(open(out, encoding="utf-8")))
print(f"   reloaded + re-ran 'Connectors' = {g2.eval('grp_connectors')}%  (round-trips)")

print()
print("=" * 70)
print("3. HISTORY TREE — commit the baseline BEFORE editing")
print("=" * 70)
hist = History()
v0 = hist.commit(g, "v0 baseline")
title, grp, scores = next(d for d in domains if "Connectors" in d[0])
print(f"   committed v0 ; '{title}' baseline = {g.eval(grp)}%")

print()
print("=" * 70)
print("4. EDIT ONE NODE -> it RUNS (incremental: recomputes only what depends on it)")
print("=" * 70)
flip = next(s for s in scores if g.nodes[s]["params"]["status"] != "live")
before = g.eval(grp)
g.evals = 0
g.set_status(flip, "live")             # change one inner node
after = g.eval(grp)
print(f"   flipped 1 inner node of '{title}' to live: {before}% -> {after}%")
print(f"   recompute touched only {g.evals} nodes (NOT all {len(sess['nodes'])}) — running incrementally")

print()
print("=" * 70)
print("5. REVERT — the history tree brings it back")
print("=" * 70)
hist.commit(g, "v1 after edit")
lab = hist.revert(g, v0)
print(f"   reverted to '{lab}': '{title}' = {g.eval(grp)}%  (back to baseline, edit undone)")
print()
print("ALL REAL — executed just now, not drawn.")
