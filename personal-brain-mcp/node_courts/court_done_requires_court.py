"""INDEPENDENT node-native court (judged_by=claude, NOT codex).

The done->court gate cannot be bypassed. On the REAL operating graph (not a
test fixture): (1) the 'done' phase is REFUSED unless a court entry exists for
the reference, and (2) a phase with no graph requirement FAILS CLOSED (raises)
- it never silently allows. Imports only the public API; asserts against the
real store snapshot. Standing court: re-run to catch a regression that lets
'done' slip through without a court.
"""
import sys, os
NL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "13.NODE-LANGUAGE")
sys.path.insert(0, os.path.abspath(NL))

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.cell_deliberation import evaluate_deliberation_gate
from nodelang.universal_cell import NULL_CELL_ID, InvalidCell


def _provider():
    p = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    p.add_key("archhub.local.court-attestation", b"e" * 32)
    return p


def run():
    store, reg = build_universal_application(resolve_map_path(), key_provider=_provider())
    proto = reg.deliberation_protocol
    ws = reg.workshop_root
    done_phase = reg.workshop_phase_roots["done"]
    snap = store.snapshot()

    # (1) done is REFUSED without a court entry, on the real app
    g = evaluate_deliberation_gate(snap, proto, ws, phase_root=done_phase, reference_root=ws)
    assert g.allowed is False, "done was allowed with no test/doc/court"
    assert any("court" in m for m in g.missing_category_roots), \
        f"court is not required at 'done' (missing={g.missing_category_roots})"

    # (2) FAIL CLOSED: a phase with no graph requirement raises, never allows
    try:
        evaluate_deliberation_gate(snap, proto, ws, phase_root=NULL_CELL_ID, reference_root=ws)
    except InvalidCell:
        pass  # correct - cannot bypass by pointing at a requirement-less phase
    else:
        raise AssertionError("gate allowed a phase with NO requirement (bypass!)")

    return {"green": True, "missing_at_done": list(g.missing_category_roots)}


if __name__ == "__main__":
    print("COURT C2 GREEN (independent, node-native):", run())
