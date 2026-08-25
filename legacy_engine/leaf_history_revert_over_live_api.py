# -*- coding: utf-8 -*-
"""LEAF: a HISTORY TREE that rerolls to any previous version — exercised against the
RUNNING interpreter, not in a vacuum.

Two proofs, both REAL (executed, not drawn):

  PROOF A (in-process):  History.commit takes an immutable deep-copied snapshot and
     History.revert restores any prior version of the live Graph. Undo is real:
     the edited value differs from baseline; after revert the value is byte-for-byte
     the baseline again.

  PROOF B (over the LIVE HTTP API):  start the REAL server.py (the ONE graph in a
     process), read a SERVED value over HTTP, commit that snapshot into a History,
     then make an edit THROUGH the live HTTP API (POST /set) — the served value
     changes — then REVERT by replaying the committed snapshot back over the same
     HTTP API. The served value returns to the EXACT prior value. Undo is real over
     the wire, not a redraw.

REUSES node_lang.Graph / node_lang.History and the real server.py. Edits neither.
"""
import json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph, History


# ---------- tiny HTTP client against the running server.py ----------
def _req(base, path, payload=None):
    url = base + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _served_value(base, nid):
    """Read ONE node's live value straight off the wire — what the UI would render."""
    state = _req(base, "/graph")
    for n in state["nodes"]:
        if n["id"] == nid:
            return n["value"]
    raise KeyError(nid)


def _served_graph(base):
    """Reconstruct a Graph from exactly what the server is serving right now."""
    state = _req(base, "/graph")
    g = Graph()
    for n in state["nodes"]:
        g.add(n["id"], n["kind"], params=n["params"], inputs=n["inputs"])
    return g


# =====================================================================
# PROOF A — in-process: commit immutable snapshot, edit, revert restores it
# =====================================================================
def proof_a():
    print("=" * 70)
    print("PROOF A — IN-PROCESS history tree: commit -> edit -> revert restores")
    print("=" * 70)
    g = Graph()
    g.add("a", "const", params={"value": 5})
    g.add("b", "const", params={"value": 3})
    g.add("s", "sum", inputs=["a", "b"])
    g.group("grp", ["a", "b"], "s")          # GROUP runs as a node: value = round(sum)

    h = History()
    v0 = h.commit(g, "v0 baseline")          # immutable deep-copied snapshot
    base = g.eval("grp")
    print(f"   committed v0 ; group 'grp' baseline = {base}")

    g.set_param("a", "value", 1000)          # LIVE edit through the engine
    mid = g.eval("grp")
    print(f"   edited a.value 5 -> 1000 ; group now = {mid}  (incremental recompute)")

    # prove the snapshot is truly immutable: the later edit did NOT mutate v0
    snap_a = h.versions[v0]["session"]["nodes"]["a"]["params"]["value"]
    print(f"   snapshot v0 still holds a.value = {snap_a}  (deep copy never mutated)")

    lab = h.revert(g, v0)                     # reroll to the prior version
    back = g.eval("grp")
    print(f"   reverted to '{lab}' ; group = {back}")

    assert mid != base, ("edit had no effect", base, mid)
    assert back == base, ("revert did not restore exact prior value", base, back)
    assert snap_a == 5, ("snapshot was mutated", snap_a)
    print(f"   ASSERT OK  base={base}  edited={mid}  reverted={back}  (base!=edited, reverted==base)")
    return base, mid, back


# =====================================================================
# PROOF B — over the LIVE HTTP API: edit a served value, revert restores it
# =====================================================================
def proof_b():
    print()
    print("=" * 70)
    print("PROOF B — OVER THE LIVE HTTP API: serve -> edit served value -> revert")
    print("=" * 70)
    port = 8791
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py"), str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        # wait for the real server to come up
        for _ in range(50):
            try:
                _req(base_url, "/graph"); break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("server.py did not start")

        # 1) read a SERVED value off the wire (the seed program: const 5 + const 3 = 8)
        served_before = _served_value(base_url, "n_sum")
        print(f"   GET /graph -> served n_sum = {served_before}  (live, off the wire)")

        # 2) commit the CURRENT served state into the history tree (immutable snapshot)
        hist = History()
        snap_graph = _served_graph(base_url)
        v0 = hist.commit(snap_graph, "v0 served-baseline")
        print(f"   committed v0 from the served state ({len(snap_graph.nodes)} nodes)")

        # 3) EDIT through the live HTTP API — change a served input value
        _req(base_url, "/set", {"id": "n_a", "key": "value", "val": 1000})
        served_edited = _served_value(base_url, "n_sum")
        print(f"   POST /set n_a.value=1000 -> served n_sum = {served_edited}  (the wire changed)")

        # 4) REVERT over the live HTTP API: replay the committed snapshot back through /set
        snap_nodes = hist.versions[v0]["session"]["nodes"]
        for nid_, n in snap_nodes.items():
            for key, val in n["params"].items():
                if key.startswith("_"):      # skip layout coords (_x/_y)
                    continue
                _req(base_url, "/set", {"id": nid_, "key": key, "val": val})
        served_reverted = _served_value(base_url, "n_sum")
        print(f"   reverted via API (replayed v0 snapshot) -> served n_sum = {served_reverted}")

        assert served_edited != served_before, ("API edit had no effect", served_before, served_edited)
        assert served_reverted == served_before, ("API revert did not restore", served_before, served_reverted)
        print(f"   ASSERT OK  served_before={served_before}  served_edited={served_edited}  "
              f"served_reverted={served_reverted}  (changed, then exactly restored over HTTP)")
        return served_before, served_edited, served_reverted
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    a = proof_a()
    b = proof_b()
    print()
    print("=" * 70)
    print("SUMMARY — undo is REAL, in-process AND over the live HTTP API")
    print("=" * 70)
    print(f"   in-process : baseline {a[0]} -> edited {a[1]} -> reverted {a[2]}")
    print(f"   live  API  : served   {b[0]} -> edited {b[1]} -> reverted {b[2]}")
    print("   LEAF_HISTORY_REVERT_OK")
