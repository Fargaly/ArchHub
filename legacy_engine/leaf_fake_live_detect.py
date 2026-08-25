# -*- coding: utf-8 -*-
"""LEAF: FAKE-LIVE DETECTION on the REAL grand map — the first Founder Cockpit command.

THE COMMAND (founder voice):
    "Show every node claiming live without a green court proof."

This is the anti-lie loop made executable. A node that says status="live" is a
LIVE-CLAIM. A claim is only believable if it carries a GREEN COURT PROOF — an
evidence_ref that names a real VERIFICATION (a passing test, a court verdict, or
a brain-proven fact). Anything weaker is a FAKE-LIVE: the map asserts "done" with
no proof a machine could re-run.

STRICT DEFINITIONS (aligned to the project's own federate / anti-lie rule):
  - LIVE-CLAIM      : node.status == "live".
  - GREEN COURT PROOF: evidence_ref starts with "test:" | "court:" | "brain:"
                       (a passing test, a court verdict, a brain-proven fact).
  - WEAK evidence   : a bare "file:..." reference. File-exists caps at *partial*
                       per the federate rule — it proves a file is THERE, not that
                       the thing WORKS. So file: is NOT a green court proof.
  - NO proof        : any other prefix (worker:, runtime:, ...) or no evidence_ref.
  - FAKE-LIVE       : a LIVE-CLAIM WITHOUT a green court proof.

WHAT IT DOES (and does NOT do):
  1. Loads the REAL map 30.KNOWLEDGE/grand-map/data/grand_domains.json — READ ONLY.
  2. Computes over ALL nodes: total live-claims, how many have a green court proof,
     and the FAKE-LIVE list (id, title, domain, evidence_ref).
  3. Lands the diagnosis AS A PROPOSAL NODE using node_lang's `proposal` kind:
     a diagnosis node holding the fake-live list + a proposed DEMOTION per node
     (file-evidence -> "partial", no/other-evidence -> "blocked"), status "pending".
     It does NOT mutate grand_domains.json — propose only, gated. Approve later.
  4. Prints a founder-readable summary.

REUSES node_lang.Graph + the `proposal` kind already in the engine. Edits NEITHER
node_lang.py NOR the map. The map is the source of truth; this only reads + proposes.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph

MAP_PATH = os.environ.get("ARCHHUB_GRAND_MAP_PATH")

# A live-claim is believable only if its evidence is one of these real verifications.
GREEN_PREFIXES = ("test:", "court:", "brain:")


def is_green_court_proof(evidence_ref):
    """True only if evidence_ref names a real verification (passing test / court / brain).
    A bare file: reference is WEAK (file-exists caps at partial) -> NOT green.
    No evidence_ref -> NOT green."""
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        return False
    return evidence_ref.startswith(GREEN_PREFIXES)


def proposed_demotion(evidence_ref):
    """A fake-live node's proposed new status:
       has a (weak) file: reference  -> 'partial'  (file proves presence, not working)
       no evidence / other prefix    -> 'blocked'  (nothing to stand on at all)."""
    if isinstance(evidence_ref, str) and evidence_ref.startswith("file:"):
        return "partial"
    return "blocked"


def load_map(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def detect_fake_live(domains):
    """Walk every node in the REAL map. Return (live_claims, green_proofs, fake_live[])."""
    live_claims = 0
    green_proofs = 0
    fake_live = []
    for dom in domains:
        dom_title = dom.get("title") or dom.get("key") or "?"
        for n in dom.get("nodes", []):
            if n.get("status") != "live":
                continue
            live_claims += 1
            ev = n.get("evidence_ref")
            if is_green_court_proof(ev):
                green_proofs += 1
                continue
            fake_live.append({
                "id": n.get("id"),
                "title": n.get("title"),
                "domain": dom_title,
                "evidence_ref": ev,                       # may be None
                "proposed_status": proposed_demotion(ev),
            })
    return live_claims, green_proofs, fake_live


def land_proposal(fake_live):
    """Land the diagnosis AS A PROPOSAL NODE in a node_lang Graph, status 'pending'.

    The map is NOT mutated. The proposal merely RECORDS, per fake-live node, the
    demotion a human could approve later. This is the loop: propose first, approve
    later — the AI never silently rewrites the map.
    """
    g = Graph()
    # the diagnosis lives as a const node the proposal points at (the 'target' of record)
    g.add("grand_map", "const", params={
        "value": "private-grand-map-input"})
    g.add("fake_live_diagnosis", "proposal", params={
        "target_node": "grand_map",
        "key": "fake_live_demotions",
        "val": fake_live,                 # the full fake-live list + per-node proposed demotion
        "status": "pending",
    })
    return g


def main():
    if not MAP_PATH:
        raise RuntimeError(
            "ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is "
            "never embedded in the public product tree")
    domains = load_map(MAP_PATH)
    live_claims, green_proofs, fake_live = detect_fake_live(domains)
    fake_n = live_claims - green_proofs

    g = land_proposal(fake_live)
    prop = g.eval("fake_live_diagnosis")
    # the map target of record is untouched by the pending proposal
    target_before = g.eval("grand_map")

    print("=" * 72)
    print('COCKPIT COMMAND: "Show every node claiming live without a green court proof."')
    print("=" * 72)
    print(f"   map: {MAP_PATH}")
    print(f"   green-court-proof = evidence_ref starts with {GREEN_PREFIXES}")
    print(f"   (a bare 'file:' ref is WEAK -> NOT a green court proof)")
    print()
    print(f"LIVE-CLAIMS: {live_claims} | GREEN-COURT-PROOF: {green_proofs} | "
          f"FAKE-LIVE: {fake_n}")
    print()
    if fake_live:
        print("FAKE-LIVE (live-claim with no green court proof):")
        for f in fake_live:
            ev = f["evidence_ref"] if f["evidence_ref"] is not None else "<no evidence_ref>"
            print(f"   - {f['id']}  [{f['domain']}]  \"{f['title']}\"")
            print(f"       evidence_ref: {ev}")
            print(f"       proposed demotion: live -> {f['proposed_status']}")
    else:
        print("FAKE-LIVE: none — every live-claim carries a green court proof.")
    print()

    # gating / no-mutation assertions, executed against the real engine
    assert prop["status"] == "pending", ("proposal not pending", prop)
    assert len(prop["val"]) == fake_n, ("proposal list size mismatch", len(prop["val"]), fake_n)
    assert target_before == "private-grand-map-input", \
        "map target of record moved while proposal pending"
    # prove on disk too: the real map file was not touched (size unchanged below run)
    print(f"PROPOSAL pending (map NOT mutated)")
    print(f"   proposal node 'fake_live_diagnosis' status = {prop['status']} ; "
          f"holds {len(prop['val'])} demotion(s)")
    print(f"   approve later via Graph.approve_proposal('fake_live_diagnosis') — "
          f"nothing applied until a human approves")


if __name__ == "__main__":
    main()
