# -*- coding: utf-8 -*-
"""LEAF: an AI action becomes a PROPOSAL node (pending), never a silent mutation.

The safety boundary (SPEC §5b): when the AI wants to change the graph it does NOT
reach in and mutate a target. It drops a `proposal` node — a pending, inert record
of the change it WOULD make. The target keeps its old value. A human (approve) is
the ONLY thing that applies it. So the AI can never silently rewrite the graph.

Two proofs, both REAL (executed against the running engine, not drawn):

  PROOF A (in-process, the CHECK):
     target = const node = 5. An AI "action" creates a proposal node to set it to 99.
     Assert target is STILL 5 while the proposal is pending (graph NOT mutated).
     approve_proposal -> assert target is now 99 and the proposal status is 'applied'.

  PROOF B (over the LIVE HTTP API):
     start the REAL server.py (the ONE graph), POST /add a proposal node that wants
     to set the served const to 99, then GET /graph and confirm OVER THE WIRE that the
     target const is STILL 5 while the proposal node sits there reading 'pending'.
     The AI added a node to the live graph and the target did NOT move. Then approve
     in-process on a graph rebuilt from the served state and confirm it flips to 99.

REUSES node_lang.Graph.approve_proposal + the `proposal` kind already in the engine,
and the real server.py. Edits NEITHER file. Prints AI_PROPOSAL_OK on success.
"""
import json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from node_lang import Graph


# ---------- tiny HTTP client against the running server.py ----------
def _req(base, path, payload=None):
    url = base + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _served(base, nid):
    """Read ONE node off the wire: (value, params) — what the UI would render."""
    for n in _req(base, "/graph")["nodes"]:
        if n["id"] == nid:
            return n["value"], n["params"]
    raise KeyError(nid)


# =====================================================================
# PROOF A — in-process: the CHECK, verbatim
# =====================================================================
def proof_a():
    print("=" * 70)
    print("PROOF A — IN-PROCESS: AI proposal is pending, target unchanged until approve")
    print("=" * 70)
    g = Graph()
    g.add("target", "const", params={"value": 5})         # the target const node = 5
    print(f"   target const = {g.eval('target')}")

    # An AI 'action' does NOT call set_param on the target. It drops a proposal node:
    # a pending, inert record of the change it WOULD make.
    g.add("ai_prop", "proposal", params={
        "target_node": "target", "key": "value", "val": 99, "status": "pending"})
    prop = g.eval("ai_prop")
    print(f"   AI action -> proposal node 'ai_prop' = {prop}")

    pending_target = g.eval("target")
    print(f"   while pending: target const = {pending_target}  (graph NOT mutated)")
    assert pending_target == 5, ("AI silently mutated the target while pending", pending_target)
    assert prop["status"] == "pending", ("proposal not pending", prop)

    applied = g.approve_proposal("ai_prop")               # the ONLY thing that applies it
    after_target = g.eval("target")
    after_prop = g.eval("ai_prop")
    print(f"   approve_proposal('ai_prop') -> {applied}")
    print(f"   after approve: target const = {after_target} ; proposal status = {after_prop['status']}")

    assert applied is True, ("approve returned falsy", applied)
    assert after_target == 99, ("target not applied to proposed value", after_target)
    assert after_prop["status"] == "applied", ("proposal status not 'applied'", after_prop)
    # idempotent: approving again is a no-op (already applied)
    assert g.approve_proposal("ai_prop") is False, "double-approve should be a no-op"
    print(f"   ASSERT OK  pending_target=5  approved_target=99  status=applied  (pending-then-applied)")
    return pending_target, after_target, after_prop["status"]


# =====================================================================
# PROOF B — over the LIVE HTTP API: AI adds a proposal node, target stays 5
# =====================================================================
def proof_b():
    print()
    print("=" * 70)
    print("PROOF B — OVER THE LIVE HTTP API: AI adds proposal node, served target unchanged")
    print("=" * 70)
    port = 8794
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py"), str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        for _ in range(50):
            try:
                _req(base, "/graph"); break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("server.py did not start")

        # the seed program serves n_a = const 5. that is our target.
        before, _ = _served(base, "n_a")
        print(f"   GET /graph -> served n_a (target const) = {before}  (off the wire)")

        # the AI (me) acts over HTTP: it does NOT POST /set n_a=99 (that would be a silent
        # mutation). It POSTs /add a PROPOSAL node that merely RECORDS the change it wants.
        _req(base, "/add", {"id": "ai_prop", "kind": "proposal", "params": {
            "target_node": "n_a", "key": "value", "val": 99, "status": "pending"}})
        prop_val, _ = _served(base, "ai_prop")
        target_after_add, _ = _served(base, "n_a")
        print(f"   POST /add proposal -> served ai_prop = {prop_val}")
        print(f"   served n_a (target) = {target_after_add}  (AI added a node; target did NOT move)")

        assert prop_val["status"] == "pending", ("served proposal not pending", prop_val)
        assert target_after_add == before == 5, ("AI mutated served target while pending", target_after_add)

        # approve on a Graph rebuilt from EXACTLY the served state, then confirm the flip.
        state = _req(base, "/graph")
        g = Graph()
        for n in state["nodes"]:
            g.add(n["id"], n["kind"], params=n["params"], inputs=n["inputs"])
        assert g.eval("n_a") == 5, "rebuilt target not 5 before approve"
        g.approve_proposal("ai_prop")
        approved = g.eval("n_a")
        status = g.eval("ai_prop")["status"]
        print(f"   approve_proposal (engine) on served-state graph -> n_a = {approved} ; status = {status}")

        assert approved == 99, ("approve did not apply over served state", approved)
        assert status == "applied", ("proposal status not applied", status)
        print(f"   ASSERT OK  served_target_while_pending=5  approved=99  status=applied")
        return before, target_after_add, approved
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
    print("SUMMARY — an AI action is a PROPOSAL (pending), never a silent mutation")
    print("=" * 70)
    print(f"   in-process : pending target {a[0]} -> approved {a[1]} (status {a[2]})")
    print(f"   live  API  : served target {b[0]} stayed {b[1]} while pending -> approved {b[2]}")
    print("   AI_PROPOSAL_OK")
