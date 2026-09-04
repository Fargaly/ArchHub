"""INDEPENDENT node-native court SUITE (judged_by=claude, NOT codex).

Builds the real operating graph ONCE and runs every node court against it, so
the whole verification is one cheap sweep. Each court imports only Codex's
public API and asserts against the real store snapshot at the current revision.
Standing + re-runnable. Honors the patent hold: local only, nothing external.

  python node_courts/run_all.py    # exit 0 = all GREEN
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
# The node language lives at node-language/ inside this repository (PR #306);
# the founder's workstation also carries it as the sibling 13.NODE-LANGUAGE
# worktree. Whichever exists first is the one the courts run against.
for _candidate in (
    os.path.join(_HERE, "..", "..", "node-language"),
    os.path.join(_HERE, "..", "..", "..", "13.NODE-LANGUAGE"),
):
    if os.path.isdir(os.path.join(_candidate, "nodelang")):
        sys.path.insert(0, os.path.abspath(_candidate))
        break
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sibling courts

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.cell_deliberation import evaluate_deliberation_gate
from nodelang.universal_cell import NULL_CELL_ID, InvalidCell
import court_room_feed_equivalence  # C4 (self-contained fixture, no app build)


def _provider():
    p = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    p.add_key("archhub.local.court-attestation", b"e" * 32)
    return p


def run_all():
    store, reg = build_universal_application(resolve_map_path(), key_provider=_provider())
    snap = store.snapshot(); cells = snap.cells
    proto = reg.deliberation_protocol; ws = reg.workshop_root
    out = {}

    # C1: workshop is a RELATION with a leaf atom, not a JSON blob
    c = cells[ws]
    assert (c.link0 and c.link0 != c.id) or (c.link1 and c.link1 != c.id)
    assert c.atom[:1] not in (b"{", b"[")
    out["C1_atom_is_leaf"] = "GREEN"

    # C2: done gate refuses without court + fails closed on a requirement-less phase
    g = evaluate_deliberation_gate(snap, proto, ws,
                                   phase_root=reg.workshop_phase_roots["done"], reference_root=ws)
    assert g.allowed is False and any("court" in m for m in g.missing_category_roots)
    try:
        evaluate_deliberation_gate(snap, proto, ws, phase_root=NULL_CELL_ID, reference_root=ws)
    except InvalidCell:
        pass
    else:
        raise AssertionError("C2: gate allowed a requirement-less phase (bypass)")
    out["C2_done_requires_court"] = "GREEN"

    # C3: referential integrity -- every structural reference of the workshop
    # (requirement roots, phase roots, category roots) resolves to a real cell
    def _ids(x):
        return list(x.values()) if hasattr(x, "values") else list(x)
    struct = ([ws] + _ids(reg.workshop_requirement_roots)
              + _ids(reg.workshop_phase_roots) + _ids(reg.workshop_category_roots))
    dangling = [r for r in struct if isinstance(r, str) and r not in cells]
    assert not dangling, f"C3: dangling workshop references: {dangling[:5]}"
    out["C3_references_resolve"] = "GREEN"

    # C4: the migration gate -- room feed <-> cell_deliberation is lossless
    # (self-contained fixture per Codex's own pattern; proves retiring the
    # python room onto the node graph loses nothing before the bridge flips)
    out.update(court_room_feed_equivalence.run())

    out["cells"] = len(cells)
    return out


if __name__ == "__main__":
    r = run_all()
    print("NODE-NATIVE COURT SUITE:", r)
    print("ALL GREEN" if all(v == "GREEN" for k, v in r.items() if k.startswith("C")) else "RED")
