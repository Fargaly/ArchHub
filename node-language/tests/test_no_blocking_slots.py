"""AgDR-0036 — the GUARD that stops the UI-freeze class from recurring.

The founder's recurring "the lag still persists" all traced to ONE
class: a @pyqtSlot doing blocking I/O on the Qt main thread, often
hidden one helper-hop down (c.probe(), broker.forward(),
cloud_client._request(), detect_all_*, a recursive glob).

This test runs the `maintenance_audit` blocking-in-pyqtslot detector
over app/bridge.py and FAILS if ANY slot blocks the UI thread.

The allowlist is now EMPTY. It once held the two EXPLICIT user-action
Settings buttons (`export_all` + `clear_model_cache`) whose brief stall
on click was treated as acceptable UX. As of 2026-06-02 (AgDR-0036
follow-up) both were converted to the proven off-thread idiom — the
slot submits the heavy glob+zip / glob+delete to `_bg_pool()`, returns
`{async, request_id}` instantly, and emits `settings_op_done` when the
work lands — so there is no longer any slot that blocks the Qt main
thread, on user action or otherwise.

If this test fails, a new blocking slot was added.  Route its slow
work off-thread: `ArchHubBridge._cached_async` (cached, pooled,
signal-on-fresh) for passive reads, or `_bg_pool().submit(...)` +
a `*_op_done` signal for user-action ops — see AgDR-0035 / AgDR-0036.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import maintenance_audit as ma  # noqa: E402

BRIDGE = REPO / "app" / "bridge.py"

# EMPTY by design (2026-06-02).  This once allowlisted the explicit
# user-action Settings buttons `export_all` + `clear_model_cache` — a
# 1-2s stall on a deliberate click was treated as acceptable UX.  Both
# are now genuinely off-thread (slot submits the heavy fs work to
# `_bg_pool()`, returns {async, request_id} instantly, and emits
# `settings_op_done` on completion — AgDR-0036 follow-up), so the
# exception is gone.  ANY blocking @pyqtSlot is now a real regression;
# keep this set empty and route new slow work off-thread instead.
_ALLOWLISTED_SLOTS: set[str] = set()


def _slot_name_for(finding, lines: list[str]) -> str:
    """Resolve the @pyqtSlot method name for a blocking finding.

    The detector embeds the SLOT's def-line in the finding detail
    ('slot at line N').  Use that, not a naive walk-up — a walk-up
    from the blocking line lands on a NESTED helper def (e.g.
    `_add_dir` inside `export_all`), not the slot itself."""
    m = re.search(r"slot at line (\d+)", finding.detail)
    slot_line = int(m.group(1)) if m else finding.line
    # The slot's `def` is on slot_line (1-based).
    if 1 <= slot_line <= len(lines):
        dm = re.match(r"\s*def\s+([A-Za-z_]\w*)\s*\(", lines[slot_line - 1])
        if dm:
            return dm.group(1)
    return "<unknown>"


def _blocking_findings_in_bridge():
    audit = ma.Audit()
    lines = BRIDGE.read_text(encoding="utf-8").splitlines()
    # Re-point the audit's REPO so relative paths resolve.
    ma.scan_blocking_in_slot(audit, BRIDGE, lines)
    return audit.findings, lines


def test_no_unguarded_blocking_slots_in_bridge():
    findings, lines = _blocking_findings_in_bridge()
    offenders = []
    for f in findings:
        if f.cls != "blocking-in-pyqtslot":
            continue
        slot = _slot_name_for(f, lines)
        if slot not in _ALLOWLISTED_SLOTS:
            offenders.append(f"{slot} (bridge.py:{f.line})")
    assert not offenders, (
        "New blocking @pyqtSlot(s) freeze the Qt UI thread — route "
        "the slow work through _cached_async:\n  " + "\n  ".join(offenders))


def test_allowlist_slots_still_exist():
    """Guard against the allowlist rotting into a silent escape hatch.

    The allowlist is currently EMPTY (no blocking slots are tolerated).
    If a future change re-adds an entry, it must name a slot that really
    exists — a stale name would silently excuse a slot that's no longer
    there. With an empty set this is a no-op, which is the intended
    steady state."""
    src = BRIDGE.read_text(encoding="utf-8")
    for slot in _ALLOWLISTED_SLOTS:
        assert re.search(rf"def\s+{re.escape(slot)}\s*\(", src), (
            f"allowlisted slot {slot!r} no longer exists — "
            f"remove it from _ALLOWLISTED_SLOTS")


def test_known_freeze_slots_are_fixed():
    """The five slots that caused the founder-visible whole-app freeze
    must NOT appear as blocking any more (AgDR-0035 + AgDR-0036)."""
    findings, lines = _blocking_findings_in_bridge()
    blocking_slots = {
        _slot_name_for(f, lines)
        for f in findings if f.cls == "blocking-in-pyqtslot"
    }
    for fixed in ("get_all_hosts", "get_local_llms", "probe_connector",
                  "list_host_sessions", "list_host_documents",
                  "get_memory_stats", "list_memory_facts",
                  "get_storage_stats"):
        assert fixed not in blocking_slots, (
            f"{fixed} regressed — it must route through _cached_async")
