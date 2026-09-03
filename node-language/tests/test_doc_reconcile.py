"""Gate tests for tools/doc_reconcile.py — the docs-up-to-date check (DOC-01/02).

The contract (mirrors the founder ask):

  * A deliberately-STALE `- [x]` (marked done, no proof receipt) FAILS the gate
    (RED). This is the R1 drift class.
  * The RECONCILED real `docs/ROADMAP.md` PASSES the gate (GREEN). This pins the
    reconciliation done in the same PR so it can never silently rot.
  * An AgDR id COLLISION (two files, same `id:`) FAILS (R2) — the exact
    AgDR-0054 reuse the founder flagged.
  * A shipped item left OPEN `- [ ]` (its receipt is in the merged ledger) FAILS
    (R3) — the doc-lags-code class.
  * The build-map generator (tools/build_map.py) derives state from AgDR
    frontmatter, never hand-typed values.

RED-before / GREEN-after is proven structurally: the same `find_violations`
function returns violations on a stale fixture and zero on the reconciled real
roadmap. Run:

    python -m pytest tests/test_doc_reconcile.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
for p in (str(REPO_ROOT), str(TOOLS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import doc_reconcile as dr  # noqa: E402
import build_map as bm      # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Fixtures — synthetic ROADMAP / AgDR trees written into tmp_path so the gate
# is exercised against KNOWN-good and KNOWN-bad inputs, independent of the
# real repo files.
# ──────────────────────────────────────────────────────────────────────────
GOOD_ROADMAP = """\
# ArchHub Roadmap

## NEXT 7 DAYS

- [x] #P1 Real shipped thing (#122) — wired + tested, 12 tests green (eng)
- [x] #P0 Another shipped thing — RESOLVED 2026-06-01, root fix verified live (eng)
- [ ] #P2 An open backlog item that nobody claims is done yet (eng)

## Done — last 7 days

- [x] archived summary row with no inline receipt — exempt because in Done (eng)
"""

# A roadmap with a bare `- [x]` (no receipt) in a LIVE section → R1.
STALE_ROADMAP = """\
# ArchHub Roadmap

## NEXT 7 DAYS

- [x] #P1 I claim this is finished but show no proof whatsoever (eng)
- [ ] #P2 An honest open item (eng)
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _agdr(id_: str, slug: str) -> str:
    return f"""\
---
id: {id_}
title: {slug.replace('-', ' ').title()}
status: proposed
category: test
---

# {id_} — {slug}
"""


# ──────────────────────────────────────────────────────────────────────────
# R1 — stale-checked
# ──────────────────────────────────────────────────────────────────────────
def test_R1_stale_checked_item_fails(tmp_path):
    """A `- [x]` with no receipt in a live section is RED."""
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", STALE_ROADMAP)
    agdr_dir = tmp_path / "docs" / "agdr"  # empty → no R2
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    assert not res.ok, "stale checked item must fail the gate"
    r1 = res.by_rule("R1")
    assert len(r1) == 1, f"expected exactly one R1, got {[str(v) for v in r1]}"
    assert "NO proof receipt" in r1[0].message


def test_R1_receipted_items_pass(tmp_path):
    """Checked items WITH receipts (PR ref, RESOLVED, tests) are GREEN."""
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", GOOD_ROADMAP)
    agdr_dir = tmp_path / "docs" / "agdr"
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    assert res.ok, f"clean roadmap should pass; got {[str(v) for v in res.violations]}"


def test_R1_done_section_is_exempt(tmp_path):
    """A receipt-less `- [x]` UNDER a Done heading is archive, not a live claim."""
    text = (
        "# R\n\n## Done — last 7 days\n\n"
        "- [x] some old thing with no receipt at all (eng)\n"
    )
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", text)
    res = dr.find_violations(roadmap_path=roadmap,
                             agdr_dir=tmp_path / "agdr", check_shipped=False)
    assert res.ok, "Done-section items must be exempt from R1"


def test_line_has_receipt_matrix():
    """The receipt detector accepts real proof, rejects bare claims."""
    assert dr.line_has_receipt("shipped via (#122)")
    assert dr.line_has_receipt("root fix at a3020c8 verified")  # sha
    assert dr.line_has_receipt("RESOLVED 2026-06-01")
    assert dr.line_has_receipt("12 tests green")
    assert dr.line_has_receipt("CDP-PROVEN live")
    assert not dr.line_has_receipt("I finished this, trust me")
    assert not dr.line_has_receipt("the facade is a deeded cabbage")  # no real sha/word


# ──────────────────────────────────────────────────────────────────────────
# R2 — AgDR id collision (the real AgDR-0054 reuse class)
# ──────────────────────────────────────────────────────────────────────────
def test_R2_duplicate_agdr_id_fails(tmp_path):
    """Two files declaring the same id → RED (the AgDR-0054 collision)."""
    agdr_dir = tmp_path / "docs" / "agdr"
    _write(agdr_dir / "AgDR-0054-collective-mind-one-brain.md",
           _agdr("AgDR-0054", "collective-mind-one-brain"))
    _write(agdr_dir / "AgDR-0054-revit-transactionless-exec.md",
           _agdr("AgDR-0054", "revit-transactionless-exec"))
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", GOOD_ROADMAP)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=agdr_dir,
                             check_shipped=False)
    assert not res.ok
    r2 = res.by_rule("R2")
    assert len(r2) == 1
    assert "AgDR-0054" in r2[0].message
    assert "ambiguous" in r2[0].message
    # both filenames named in the verdict
    assert "collective-mind-one-brain.md" in r2[0].where
    assert "revit-transactionless-exec.md" in r2[0].where


def test_R2_unique_ids_pass(tmp_path):
    """Distinct ids across files → no R2."""
    agdr_dir = tmp_path / "docs" / "agdr"
    _write(agdr_dir / "AgDR-0054-a.md", _agdr("AgDR-0054", "a"))
    _write(agdr_dir / "AgDR-0055-b.md", _agdr("AgDR-0055", "b"))
    ids = dr.scan_agdr_ids(agdr_dir)
    assert ids == {"AgDR-0054": ["AgDR-0054-a.md"],
                   "AgDR-0055": ["AgDR-0055-b.md"]}
    assert dr.check_agdr_collisions(ids) == []


# ──────────────────────────────────────────────────────────────────────────
# R3 — shipped-but-open / undocumented
# ──────────────────────────────────────────────────────────────────────────
_RCPT = (dr.ShippedReceipt(key="Frobnicator wired", receipt="#999",
                           summary="frobnicator"),)


def test_R3_shipped_item_left_open_fails(tmp_path):
    """A shipped receipt whose roadmap line is still `- [ ]` → RED."""
    text = "# R\n\n## NEXT\n\n- [ ] #P1 Frobnicator wired into the runtime (eng)\n"
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", text)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=tmp_path / "agdr",
                             receipts=_RCPT)
    assert not res.ok
    r3 = res.by_rule("R3")
    assert len(r3) == 1
    assert "still OPEN" in r3[0].message


def test_R3_shipped_item_undocumented_fails(tmp_path):
    """A shipped receipt with NO matching roadmap line at all → RED."""
    text = "# R\n\n## NEXT\n\n- [x] #P1 something unrelated (#1) (eng)\n"
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", text)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=tmp_path / "agdr",
                             receipts=_RCPT)
    assert not res.ok
    assert any("NO line in the roadmap" in v.message for v in res.by_rule("R3"))


def test_R3_shipped_item_checked_with_receipt_passes(tmp_path):
    """A checked line carrying the receipt → reconciled, GREEN."""
    text = ("# R\n\n## Done — last 7 days\n\n"
            "- [x] #P1 Frobnicator wired into the runtime (#999) (eng)\n")
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", text)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=tmp_path / "agdr",
                             receipts=_RCPT)
    assert res.ok, f"reconciled item should pass; got {[str(v) for v in res.violations]}"


def test_R3_checked_but_missing_receipt_fails(tmp_path):
    """Checked, line matches the key, but the PR receipt string is absent."""
    text = ("# R\n\n## Done — last 7 days\n\n"
            "- [x] #P1 Frobnicator wired into the runtime — shipped (eng)\n")
    roadmap = _write(tmp_path / "docs" / "ROADMAP.md", text)
    res = dr.find_violations(roadmap_path=roadmap, agdr_dir=tmp_path / "agdr",
                             receipts=_RCPT)
    assert not res.ok
    assert any("MISSING its proof receipt" in v.message
               for v in res.by_rule("R3"))


# ──────────────────────────────────────────────────────────────────────────
# THE HEADLINE GATE — RED on a stale roadmap, GREEN on the REAL reconciled one.
# ──────────────────────────────────────────────────────────────────────────
def test_real_reconciled_roadmap_passes():
    """The committed, reconciled docs/ROADMAP.md + AgDR ledger PASS the gate.

    This is the GREEN-after half of the contract: after the reconciliation in
    this PR, the real files produce ZERO violations. If a future edit marks an
    item done without a receipt, reuses an AgDR id, or leaves a merged item
    open, THIS test goes red.
    """
    res = dr.find_violations()  # defaults to the repo's real files
    assert res.ok, (
        "the reconciled ROADMAP + AgDR ledger must pass; violations:\n"
        + "\n".join(str(v) for v in res.violations)
    )


def test_stale_roadmap_is_red_real_agdrs():
    """RED-before: a deliberately-stale roadmap fails even with the real AgDRs.

    Proves the gate WOULD have caught drift on the live tree — the same engine,
    a stale input, a red verdict.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        roadmap = _write(Path(td) / "ROADMAP.md", STALE_ROADMAP)
        res = dr.find_violations(roadmap_path=roadmap, check_shipped=False)
        assert not res.ok
        assert res.by_rule("R1"), "the stale `- [x]` must trip R1"


def test_all_eight_merged_prs_are_reconciled():
    """Every SHIPPED_RECEIPTS entry resolves to a checked, receipted line.

    Directly pins the DOC-02 reconciliation: the 8 merged PRs this session are
    each documented with their PR number on a `- [x]` line.
    """
    res = dr.find_violations()  # real files
    assert res.by_rule("R3") == [], (
        "shipped-but-open drift remains:\n"
        + "\n".join(str(v) for v in res.by_rule("R3"))
    )
    # and the ledger really does carry all eight this session
    receipts = {r.receipt for r in dr.SHIPPED_RECEIPTS}
    assert receipts == {"#122", "#123", "#124", "#125",
                        "#126", "#127", "#128", "#129"}


# ──────────────────────────────────────────────────────────────────────────
# CLI exit codes
# ──────────────────────────────────────────────────────────────────────────
def test_cli_exit_zero_on_clean_repo():
    """`python tools/doc_reconcile.py` exits 0 on the reconciled repo."""
    assert dr.main([]) == 0


def test_cli_exit_one_on_stale(tmp_path, capsys):
    roadmap = _write(tmp_path / "ROADMAP.md", STALE_ROADMAP)
    rc = dr.main(["--roadmap", str(roadmap), "--no-shipped",
                  "--agdr-dir", str(tmp_path / "agdr")])
    assert rc == 1
    out = capsys.readouterr()
    assert "VIOLATIONS=" in out.out  # machine summary on stdout


# ──────────────────────────────────────────────────────────────────────────
# build_map — derived, not hand-typed
# ──────────────────────────────────────────────────────────────────────────
def test_build_map_derives_status_from_agdr_frontmatter(tmp_path, monkeypatch):
    """The map's build-state comes from real AgDR `status:` lines."""
    agdr_dir = tmp_path / "agdr"
    _write(agdr_dir / "AgDR-0001-x.md",
           "---\nid: AgDR-0001\ntitle: X\nstatus: executed\n---\n# AgDR-0001 — X\n")
    _write(agdr_dir / "AgDR-0002-y.md",
           "---\nid: AgDR-0002\ntitle: Y\nstatus: proposed\n---\n# AgDR-0002 — Y\n")
    _write(agdr_dir / "AgDR-0003-z.md",
           "---\nid: AgDR-0003\ntitle: Z\nstatus: superseded by AgDR-0001\n---\n# Z\n")
    recs = bm.scan_agdrs(agdr_dir)
    by_id = {r.agdr_id: r for r in recs}
    assert by_id["AgDR-0001"].status_class == "built"
    assert by_id["AgDR-0002"].status_class == "planned"
    assert by_id["AgDR-0003"].status_class == "superseded"


def test_build_map_classifier_buckets():
    assert bm._classify_status("executed — founder-signed") == "built"
    assert bm._classify_status("PLAN-LOCKED (needs go)") == "planned"
    assert bm._classify_status("superseded by AgDR-0048") == "superseded"
    assert bm._classify_status("partially_superseded") == "unknown"


def test_build_map_render_is_deterministic():
    """Same inputs → byte-identical output (lets a CI staleness check work)."""
    agdrs = [bm.AgdrRecord("AgDR-0001", "executed", "built", "Thing one", "a.md")]
    out1 = bm.render_map(agdrs, [], "no brain", today="2026-06-15")
    out2 = bm.render_map(agdrs, [], "no brain", today="2026-06-15")
    assert out1 == out2
    assert "Thing one" in out1
    assert "Built (executed):** 1" in out1


def test_build_map_real_repo_generates_and_lists_collective_mind():
    """The generator runs on the real repo and shows AgDR-0054 collective-mind
    as a PLANNED record, NOT built.

    CONSCIOUSLY REWRITTEN (DOC-07): this test previously asserted
    `status_class == "built"` — it encoded the very overclaim the founder
    flagged (frontmatter `executed` while every roadmap slice is PLAN-LOCKED /
    NO BUILD). The honest status is now `approved-direction · build-pending`,
    so the map must list it under planned/in-flight. The map reflecting the
    tracked ledger (collective-mind file present, not the untracked revit reuse)
    still holds.
    """
    recs = bm.scan_agdrs()  # real docs/agdr
    by_id = {}
    for r in recs:
        by_id.setdefault(r.agdr_id, []).append(r)
    assert "AgDR-0054" in by_id
    cm = [r for r in by_id["AgDR-0054"]
          if "collective-mind" in r.filename]
    assert cm, "tracked AgDR-0054 collective-mind file must be present"
    # Direction-approved but unbuilt → planned, never built.
    assert cm[0].status_class == "planned", (
        f"AgDR-0054 must read as planned (build-pending), got "
        f"{cm[0].status_class!r} from status {cm[0].status!r}")
    # rendering the full map does not raise
    text = bm.generate(today="2026-06-15")
    assert "What is built" in text
    assert "AgDR-0054" in text
