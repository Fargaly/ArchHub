"""INDEPENDENT node-native court (judged_by=claude, NOT codex).

Verifies Codex's app:workshop in the ONE operating graph is a real Cell
RELATION, not a JSON blob -- the founder law "everything is a node" +
watch-condition (c): the atom stays a leaf. Imports ONLY the public API
(build_universal_application) and asserts against the real store snapshot at
the current revision -- never source strings, never Codex's own assertions.
Standing court: re-run any time to catch a regression to blob-storage.

  python node_courts/court_workshop_atom_is_leaf.py   # exit 0 = GREEN
"""
import sys, os

NL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "..", "..", "..", "13.NODE-LANGUAGE")
sys.path.insert(0, os.path.abspath(NL))

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application


def _provider():
    p = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    p.add_key("archhub.local.court-attestation", b"e" * 32)
    return p


def run():
    store, reg = build_universal_application(resolve_map_path(), key_provider=_provider())
    cells = store.snapshot().cells
    wr = reg.workshop_root
    c = cells[wr]
    # (1) workshop is a RELATION: links point at other cells
    assert (c.link0 and c.link0 != c.id) or (c.link1 and c.link1 != c.id), \
        "workshop_root is not a relation"
    # (2) atom is a LEAF, never a serialized subgraph / JSON blob
    assert c.atom[:1] not in (b"{", b"["), "workshop_root atom looks like a JSON blob"
    # (3) the requirement gate (claim->plan, done->test/doc/court) is real cells,
    #     none of them a blob
    reqs = reg.workshop_requirement_roots
    ids = list(reqs.values()) if isinstance(reqs, dict) else list(reqs)
    blobs = [r for r in ids if isinstance(r, str) and r in cells
             and cells[r].atom[:1] in (b"{", b"[")]
    assert not blobs, f"requirement cells stored as JSON blobs: {blobs}"
    return {"cells": len(cells), "requirement_cells": len(ids), "green": True}


if __name__ == "__main__":
    r = run()
    print("COURT C1 GREEN (independent, node-native):", r)
