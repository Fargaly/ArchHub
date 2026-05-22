"""AgDR-0036 — the GUARD that stops the UI-freeze class from recurring.

The founder's recurring "the lag still persists" all traced to ONE
class: a @pyqtSlot doing blocking I/O on the Qt main thread, often
hidden one helper-hop down (c.probe(), broker.forward(),
cloud_client._request(), detect_all_*, a recursive glob).

This test runs the `maintenance_audit` blocking-in-pyqtslot detector
over app/bridge.py and FAILS if any slot blocks the UI thread —
except a tiny, documented allowlist of EXPLICIT user-action Settings
buttons whose brief stall is acceptable UX.

If this test fails, a new blocking slot was added.  Route its slow
work through `ArchHubBridge._cached_async` (cached, pooled,
signal-on-fresh) — see AgDR-0035 / AgDR-0036.
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

# Explicit user-action Settings buttons.  A 1-2s stall when the user
# deliberately clicks "Export everything" / "Clear model cache" is
# expected UX, NOT the passive freeze the founder reported.  Bounded,
# documented, and tracked on docs/ROADMAP.md for async conversion.
# Anything NOT in this set that blocks is a real regression.
_ALLOWLISTED_SLOTS = {"export_all", "clear_model_cache"}


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
    """If an allowlisted slot is renamed / removed, shrink the
    allowlist — don't let it rot into a silent escape hatch."""
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
