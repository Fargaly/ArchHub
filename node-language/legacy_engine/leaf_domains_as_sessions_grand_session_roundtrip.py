# -*- coding: utf-8 -*-
"""LEAF: Domains SAVE AS SESSIONS + ONE grand session wires every domain as a node.

This is a self-contained leaf of the node-language replica. It REUSES the real
engine (node_lang.Graph: add / group / eval / to_session / from_session) — it does
NOT rebuild it and does NOT edit node_lang.py / server.py.

It demonstrates, by RUNNING on the real 15 domains / 261 project nodes in
grand_domains.json:

  1. EACH DOMAIN SAVES AS ITS OWN SESSION  — a domain is a node-graph (status_score
     per child -> avg -> x100 -> group). to_session writes it out; from_session
     reloads it; re-running the reloaded group-node yields the identical value.
     (15 per-domain session files written to ./domain_sessions/.)

  2. ONE GRAND SESSION WIRES EVERY DOMAIN AS A NODE — all 15 domains live in ONE
     graph; the whole map serializes via to_session to grandmap.session.json
     (schema node_lang/1, 306 nodes = 15 domain group-nodes + their inner
     primitives), and reloads via from_session.

  3. LOSSLESS + STILL RUNNABLE — after reload, re-running every domain group-node
     yields byte-identical values to before the round-trip, twice over
     (file -> from_session -> eval, and a second independent from_session -> eval).

Run:
    PYTHONIOENCODING=utf-8 python leaf_domains_as_sessions_grand_session_roundtrip.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph  # the REAL engine — reused, not rebuilt

GM = os.environ.get("ARCHHUB_GRAND_MAP_PATH")
if not GM:
    raise RuntimeError(
        "ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is "
        "never embedded in the public product tree")
DOMAINS = json.load(open(GM, encoding="utf-8"))


def build_domain_into(g, dom):
    """Wire ONE domain into graph g as primitive nodes feeding a group-node.

    status_score per child  ->  avg  ->  mul x100  ->  group(out=pct).
    Returns the group-node id. Identical wiring to demo_run.py so the grand
    session this leaf writes is the SAME 306-node artifact the engine expects.
    """
    score_ids = []
    for n in dom["nodes"]:
        sid = "score_" + n["id"]
        g.add(sid, "status_score", params={"status": n.get("status", "vision")})
        score_ids.append(sid)
    avg_id = "avg_" + dom["key"]
    g.add(avg_id, "avg", inputs=score_ids)
    pct_id = "pct_" + dom["key"]
    g.add(pct_id, "mul", inputs=[avg_id], params={"factor": 100})
    grp_id = "grp_" + dom["key"]
    g.add(grp_id, "group", params={"members": score_ids, "out": pct_id})
    return grp_id


def main():
    line = "=" * 70

    # ---------------------------------------------------------------- 1. EACH DOMAIN -> ITS OWN SESSION
    print(line)
    print("1. EACH DOMAIN SAVES AS ITS OWN SESSION (a domain is a node-graph)")
    print(line)
    sess_dir = os.path.join(HERE, "domain_sessions")
    os.makedirs(sess_dir, exist_ok=True)
    per_domain_ok = 0
    for dom in DOMAINS:
        dg = Graph()
        grp = build_domain_into(dg, dom)
        before = dg.eval(grp)
        # save as a session...
        dsess = dg.to_session()
        dpath = os.path.join(sess_dir, "domain_%s.session.json" % dom["key"])
        json.dump(dsess, open(dpath, "w", encoding="utf-8"), ensure_ascii=False)
        # ...reload it and re-run the SAME group-node: must be identical (lossless + runnable)
        dg2 = Graph.from_session(json.load(open(dpath, encoding="utf-8")))
        after = dg2.eval(grp)
        assert after == before, "domain %s drifted on round-trip: %r != %r" % (dom["key"], after, before)
        assert dsess["schema"] == "node_lang/1", dsess.get("schema")
        per_domain_ok += 1
        print("   %-26s = %3d%%  saved %d-node session -> reloaded -> re-ran = %3d%%  (lossless)"
              % (dom["title"][:26], before, len(dsess["nodes"]), after))
    print("   %d/%d domains: each saved as its OWN session and round-tripped identically"
          % (per_domain_ok, len(DOMAINS)))

    # ---------------------------------------------------------------- 2. ONE GRAND SESSION (every domain a node)
    print()
    print(line)
    print("2. ONE GRAND SESSION — every domain wired as a node in ONE graph")
    print(line)
    g = Graph()
    grp_ids = [build_domain_into(g, dom) for dom in DOMAINS]
    # capture every domain group-node's live value BEFORE serializing
    before_vals = {gid: g.eval(gid) for gid in grp_ids}
    for dom, gid in zip(DOMAINS, grp_ids):
        print("   %-26s = %3d%%   <- group runs: avg(status_score) x100"
              % (dom["title"][:26], before_vals[gid]))

    sess = g.to_session()
    grp_count = sum(1 for k in sess["nodes"] if k.startswith("grp_"))
    print("   session = %d nodes (15 domain group-nodes + their inner primitive nodes)"
          % len(sess["nodes"]))
    assert sess["schema"] == "node_lang/1", sess.get("schema")
    assert grp_count == 15, grp_count
    out = os.path.join(HERE, "grandmap.session.json")
    json.dump(sess, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("   saved -> %s  (schema %s, %d grp_ domain-nodes)"
          % (os.path.basename(out), sess["schema"], grp_count))

    # ---------------------------------------------------------------- 3. RELOAD + RE-RUN = IDENTICAL (twice)
    print()
    print(line)
    print("3. RELOAD via from_session + RE-RUN — lossless, still runnable")
    print(line)
    # round-trip A: from the file on disk
    gA = Graph.from_session(json.load(open(out, encoding="utf-8")))
    conn = gA.eval("grp_connectors")
    print("   reloaded + re-ran 'Connectors' = %d%%  (round-trips)" % conn)

    # round-trip B: a second, independent reload from the same file
    gB = Graph.from_session(json.load(open(out, encoding="utf-8")))

    # prove EVERY domain group-node re-evaluates identically across both reloads
    drift = []
    for gid in grp_ids:
        a = gA.eval(gid)
        b = gB.eval(gid)
        if not (a == b == before_vals[gid]):
            drift.append((gid, before_vals[gid], a, b))
    assert conn == before_vals["grp_connectors"], (conn, before_vals["grp_connectors"])
    assert not drift, "LOSSLESS round-trip FAILED: %r" % drift
    print("   all %d domain group-nodes re-ran identically after reload (A==B==pre-save)"
          % len(grp_ids))
    print("   LOSSLESS + RUNNABLE confirmed: grand session is the SAME running map after save/load")

    # final machine-checkable line
    print()
    print("LEAF_OK  schema=%s  nodes=%d  grp=%d  connectors=%d%%  per_domain=%d/%d  ROUNDTRIP"
          % (sess["schema"], len(sess["nodes"]), grp_count, conn, per_domain_ok, len(DOMAINS)))


if __name__ == "__main__":
    main()
