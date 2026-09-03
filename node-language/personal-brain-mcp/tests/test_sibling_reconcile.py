"""BRV-12 — concurrent edits become SIBLING versions with a reconcile record.

Root cause (origin/main): `BrainStore.write_fragment` is a plain
`INSERT … ON CONFLICT(id) DO UPDATE` — last-writer-wins. When two devices each
edit the SAME fragment id concurrently (different value, each with its own HLC,
neither causally after the other), the second write silently CLOBBERS the first.
One user's edit is lost with no trace.

Decision B (AgDR-0044 acceptance #5): a divergent concurrent write does NOT
overwrite — both values are preserved as `{value, hlc, source, verdict}` SIBLING
versions and a reconcile record is attached, so the conflict is reconcilable
(not silently dropped). The head row keeps the highest-HLC value so existing
readers/search are unchanged; the losing sibling + the reconcile state live in
the fragment's `extra` lineage (ONE-SYSTEM — no new table).

These tests pin that contract via the new reconcile-aware write path
`BrainStore.write_fragment_versioned(fragment, *, hlc, source)`.
"""
from __future__ import annotations

import pytest

from personal_brain import hlc as _hlc
from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import (
    BrainStore,
    fragment_reconcile_record,
    fragment_siblings,
)


def _frag(fid: str, text: str, owner: str = "founder") -> Fragment:
    return Fragment(
        id=fid,
        kind=FragmentKind.FACT,
        text=text,
        owner_user=owner,
        provenance=Provenance(
            contributing_agent="claude", contributing_user=owner,
        ),
    )


def test_concurrent_divergent_writes_keep_both_as_siblings():
    """Two writes with DIFFERENT values + DIFFERENT HLCs on one id must BOTH
    survive (as sibling versions) — not last-writer-wins."""
    store = BrainStore.open(":memory:")
    fid = "frag-conflict-1"

    # Two divergent HLCs from two devices. hlc_a is *higher* (later wallclock),
    # so it becomes the head; hlc_b is the concurrent sibling neither saw.
    hlc_a = _hlc.pack(2_000_000, 0)
    hlc_b = _hlc.pack(1_000_000, 0)
    hlc_a_str = f"{hlc_a:016x}"
    hlc_b_str = f"{hlc_b:016x}"

    # device A writes value A
    store.write_fragment_versioned(
        _frag(fid, "value from device A"), hlc=hlc_a_str, source="device-A",
    )
    # device B writes a DIFFERENT value with a DIFFERENT (concurrent) HLC.
    store.write_fragment_versioned(
        _frag(fid, "value from device B"), hlc=hlc_b_str, source="device-B",
    )

    head = store.get_fragment(fid)
    assert head is not None

    # Both distinct values must be recoverable from the lineage — neither was
    # silently dropped (that is the whole point of decision B vs LWW).
    sibs = fragment_siblings(head)
    sib_values = {s.get("value") or s.get("text") for s in sibs}
    sib_hlcs = {s.get("hlc") for s in sibs}
    assert "value from device A" in sib_values
    assert "value from device B" in sib_values
    assert hlc_a_str in sib_hlcs and hlc_b_str in sib_hlcs
    assert len(sibs) >= 2, "both concurrent edits must be retained as siblings"

    # A reconcile record marks the conflict for resolution.
    rec = fragment_reconcile_record(head)
    assert rec is not None, "a divergent write must attach a reconcile record"
    assert rec.get("state") == "pending"
    assert rec.get("sibling_count", 0) >= 2

    # The head keeps the highest-HLC value (deterministic winner), so existing
    # readers see a stable value rather than whichever wrote last.
    assert head.text == "value from device A"
    assert (head.extra.get("hlc") or "") == hlc_a_str
    store.close()


def test_sibling_lineage_persists_across_reopen(tmp_path):
    """The sibling set + reconcile record survive a store reopen (durable in
    `extra`, no new table)."""
    db = tmp_path / "brain.db"
    fid = "frag-conflict-2"
    hlc_hi = f"{_hlc.pack(5_000_000, 0):016x}"
    hlc_lo = f"{_hlc.pack(4_000_000, 0):016x}"

    s1 = BrainStore.open(db)
    s1.write_fragment_versioned(_frag(fid, "hi-value"), hlc=hlc_hi, source="A")
    s1.write_fragment_versioned(_frag(fid, "lo-value"), hlc=hlc_lo, source="B")
    s1.close()

    s2 = BrainStore.open(db)
    head = s2.get_fragment(fid)
    sibs = fragment_siblings(head)
    assert {s.get("value") for s in sibs} >= {"hi-value", "lo-value"}
    assert fragment_reconcile_record(head) is not None
    s2.close()


def test_linear_newer_edit_advances_head_without_phantom_sibling():
    """A strictly causal newer edit (incoming HLC descends from the stored head)
    is a normal update — it advances the head and does NOT spawn a conflict
    reconcile record. Reconcile is only for DIVERGENT concurrent writes."""
    store = BrainStore.open(":memory:")
    fid = "frag-linear"

    hlc1 = f"{_hlc.pack(1_000_000, 0):016x}"
    store.write_fragment_versioned(_frag(fid, "v1"), hlc=hlc1, source="A")

    # device A advances ITS OWN value — pass the prior head's hlc as the parent,
    # so this is a linear successor, not a concurrent fork.
    hlc2 = f"{_hlc.pack(2_000_000, 0):016x}"
    store.write_fragment_versioned(
        _frag(fid, "v2"), hlc=hlc2, source="A", parent_hlc=hlc1,
    )

    head = store.get_fragment(fid)
    assert head.text == "v2"
    rec = fragment_reconcile_record(head)
    assert rec is None or rec.get("state") != "pending", (
        "a linear causal update must not raise a pending reconcile conflict"
    )
    store.close()


def test_idempotent_same_hlc_same_value_is_noop():
    """Re-applying the identical (id, hlc, value) — e.g. a sync replay — must
    not fabricate a duplicate sibling."""
    store = BrainStore.open(":memory:")
    fid = "frag-replay"
    hlc1 = f"{_hlc.pack(3_000_000, 0):016x}"
    store.write_fragment_versioned(_frag(fid, "same"), hlc=hlc1, source="A")
    store.write_fragment_versioned(_frag(fid, "same"), hlc=hlc1, source="A")

    head = store.get_fragment(fid)
    sibs = fragment_siblings(head)
    # At most one recorded sibling/version for an identical replay — no phantom.
    values = [s.get("value") for s in sibs]
    assert values.count("same") <= 1
    rec = fragment_reconcile_record(head)
    assert rec is None or rec.get("state") != "pending"
    store.close()
