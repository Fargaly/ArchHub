"""Gate test for tools/doc_reconcile.py R4 — AgDR status overclaim (DOC-07).

The founder flagged: AgDR-0054's frontmatter said `status: executed` while
EVERY one of its roadmap slices is `[ ] PLAN-LOCKED … NO BUILD`. `executed`
elsewhere in the ledger means "built + live"; here it meant only "founder
approved the direction" — so an unbuilt record read as shipped, and the
build-state ledger could not be trusted.

The fix has two halves, both tested here:

  1. MECHANISM (the class): `doc_reconcile.check_status_overclaim` (R4) fails
     any AgDR whose status reads as BUILT while ≥1 of its roadmap slices is
     explicitly PLAN-LOCKED / NO-BUILD and 0 slices are checked. It does NOT
     fire on a genuinely-shipped AgDR that merely has open follow-up lines
     naming its id.

  2. THE INSTANCE: the real AgDR-0054 frontmatter now reads
     `approved-direction · build-pending`, so the real repo passes R4, and
     `build_map` classifies it as `planned`, never `built`.

RED-before / GREEN-after:

  * RED on origin/main: AgDR-0054 frontmatter `status: executed …` + 7
    PLAN-LOCKED slices → R4 fires (proven by the synthetic-overclaim test,
    which reproduces the exact shape, and historically by the real file).
  * GREEN on this branch: the real-repo R4 check returns zero violations
    because the status is now the honest distinct value.

Run:
    python -m pytest tests/test_doc_status_overclaim.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
for _p in (str(REPO_ROOT), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import doc_reconcile as dr  # noqa: E402
import build_map as bm      # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────
# status_reads_as_built — the keyword classifier.
# ──────────────────────────────────────────────────────────────────────────
def test_status_reads_as_built_matrix():
    assert dr.status_reads_as_built('executed — founder-signed ("EXECUTE")')
    assert dr.status_reads_as_built("shipped")
    assert dr.status_reads_as_built("done")
    assert dr.status_reads_as_built("implemented 2026-06-01")
    # The corrected status must NOT read as built.
    assert not dr.status_reads_as_built(
        "approved-direction · build-pending — founder-signed direction")
    assert not dr.status_reads_as_built("proposed")
    assert not dr.status_reads_as_built("PLAN-LOCKED (needs go)")
    assert not dr.status_reads_as_built("rework")
    assert not dr.status_reads_as_built("superseded by AgDR-0048")


def test_slice_build_blocked_detector():
    assert dr.slice_is_build_blocked("PLAN-LOCKED (needs founder go) — S0")
    assert dr.slice_is_build_blocked("AgDR-0054 S1 — NO BUILD until go")
    assert dr.slice_is_build_blocked('needs "go" before building')
    assert not dr.slice_is_build_blocked("AgDR-0037 follow-ups — guard tests")
    assert not dr.slice_is_build_blocked("wired + tested, 12 tests green (#122)")


# ──────────────────────────────────────────────────────────────────────────
# R4 — the overclaim, on synthetic inputs (the AgDR-0054 shape).
# ──────────────────────────────────────────────────────────────────────────
_OVERCLAIM_ROADMAP = """\
# Roadmap

## AgDR-0054 — Collective Mind

- [ ] PLAN-LOCKED (needs founder "go" — NO BUILD) · AgDR-0054 S0 — extract brain (eng)
- [ ] PLAN-LOCKED (needs "go") · AgDR-0054 S1 (CORE) — ledger record (eng)
- [ ] #P1 AgDR-0054 slice 2 — populate the per-trace fields (eng)
"""

_EXECUTED_AGDR = """\
---
id: AgDR-0054
status: executed — founder-signed 2026-06-10 ("EXECUTE")
category: architecture
---

# AgDR-0054 — Collective Mind
"""


def test_R4_built_status_over_planlocked_plan_fails(tmp_path):
    """executed status + PLAN-LOCKED/NO-BUILD slices, 0 checked → RED."""
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", _OVERCLAIM_ROADMAP)
    agdr_dir = tmp_path / "docs" / "agdr"
    _write(agdr_dir / "AgDR-0054-collective-mind-one-brain.md", _EXECUTED_AGDR)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    r4 = res.by_rule("R4")
    assert len(r4) == 1, f"expected one R4, got {[str(v) for v in r4]}"
    assert "AgDR-0054" in r4[0].message
    assert "approved-direction" in r4[0].message  # names the honest fix
    assert "AgDR-0054-collective-mind-one-brain.md" in r4[0].where


def test_R4_corrected_status_passes(tmp_path):
    """The honest `approved-direction · build-pending` status → GREEN."""
    corrected = _EXECUTED_AGDR.replace(
        "status: executed — founder-signed 2026-06-10 (\"EXECUTE\")",
        "status: approved-direction · build-pending — direction locked, NO build",
    )
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", _OVERCLAIM_ROADMAP)
    agdr_dir = tmp_path / "docs" / "agdr"
    _write(agdr_dir / "AgDR-0054-collective-mind-one-brain.md", corrected)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    assert res.by_rule("R4") == [], (
        "corrected status must pass R4; got "
        + "; ".join(str(v) for v in res.by_rule("R4")))


def test_R4_built_agdr_with_open_followups_does_not_fire(tmp_path):
    """A genuinely-shipped AgDR with only open *follow-up* lines naming its id
    (no PLAN-LOCKED / NO-BUILD marker) must NOT trip R4 — the false-positive
    class the tightened predicate excludes."""
    roadmap_text = (
        "# Roadmap\n\n## NEXT 7 DAYS\n\n"
        "- [ ] #P1 AgDR-0037 follow-ups — guard tests for the net8 bugs (eng)\n"
        "- [ ] #P2 redeploy note mentioning AgDR-0037 at ship time (ops)\n"
    )
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", roadmap_text)
    agdr_dir = tmp_path / "docs" / "agdr"
    _write(agdr_dir / "AgDR-0037-net8.md",
           "---\nid: AgDR-0037\nstatus: executed\n---\n# AgDR-0037 — net8\n")
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    assert res.by_rule("R4") == [], (
        "a shipped AgDR with open follow-ups must not trip R4; got "
        + "; ".join(str(v) for v in res.by_rule("R4")))


def test_R4_built_agdr_with_a_checked_slice_passes(tmp_path):
    """If ≥1 slice is flipped to [x], the build started → no overclaim, even
    with PLAN-LOCKED siblings."""
    roadmap_text = (
        "# Roadmap\n\n## S\n\n"
        "- [x] AgDR-0077 S1 — shipped (#321) (eng)\n"
        "- [ ] PLAN-LOCKED · AgDR-0077 S2 — NO BUILD yet (eng)\n"
    )
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", roadmap_text)
    agdr_dir = tmp_path / "docs" / "agdr"
    _write(agdr_dir / "AgDR-0077-x.md",
           "---\nid: AgDR-0077\nstatus: executed\n---\n# AgDR-0077 — x\n")
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    assert res.by_rule("R4") == []


# ──────────────────────────────────────────────────────────────────────────
# The real repo — GREEN after the AgDR-0054 frontmatter correction.
# ──────────────────────────────────────────────────────────────────────────
def test_real_agdr_0054_status_is_not_built():
    """The real AgDR-0054 frontmatter no longer reads as built."""
    statuses = dr.scan_agdr_statuses()
    cm = [s for s in statuses
          if "collective-mind" in s.filename and s.agdr_id == "AgDR-0054"]
    assert cm, "AgDR-0054 collective-mind file must be present"
    assert not cm[0].reads_as_built, (
        f"AgDR-0054 still reads as built: status={cm[0].raw_status!r}")
    assert "approved-direction" in cm[0].raw_status.lower()


def test_real_repo_has_no_R4_overclaim():
    """The reconciled real repo produces zero R4 violations."""
    res = dr.find_violations()  # real files
    assert res.by_rule("R4") == [], (
        "R4 status-overclaim drift remains:\n"
        + "\n".join(str(v) for v in res.by_rule("R4")))


def test_build_map_lists_0054_as_planned_not_built():
    """`build_map` classifies the corrected AgDR-0054 as planned."""
    recs = bm.scan_agdrs()
    cm = [r for r in recs
          if "collective-mind" in r.filename and r.agdr_id == "AgDR-0054"]
    assert cm and cm[0].status_class == "planned", (
        f"AgDR-0054 must classify as planned; got "
        f"{cm[0].status_class if cm else 'MISSING'!r}")
