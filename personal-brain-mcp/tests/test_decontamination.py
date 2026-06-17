"""AgDR-0054 · BRV-14 — train<->eval decontamination scan.

Gate (the requirement leaf): `pytest -k decontamination` proving an export with
a known train/eval n-gram overlap is FLAGGED.

RED on origin/main: `personal_brain.decontamination` does not exist and
`export_fragments` performs no train<->eval scan (its docstring admitted the
scan was "pending" and `Fragment.content_hash_post` was a dangling field) — so
a training row byte-identical to a held-out eval item shipped silently. These
tests import the new module + drive the new export path; both fail to even
import on main.

Covers acceptance #12 (decontamination scan train<->eval each export) and #18
(eval time-split: eval items post-cutoff).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from personal_brain.decontamination import (
    DecontaminationReport,
    scan_decontamination,
    time_split,
)
from personal_brain.dataset_export import export_fragments
from personal_brain.models import Fragment, FragmentKind, Provenance, Scope
from personal_brain.storage import BrainStore as Store


# A 13+-word eval item so the default 13-gram window has shingles to match.
_EVAL_TEXT = (
    "To anchor a curtain wall mullion in Revit set the work plane to the "
    "level datum and dimension from the structural grid line origin point."
)


def _frag(fid, text, *, kind=FragmentKind.FACT, scope=Scope.USER, when=None):
    ts = when or datetime.now(timezone.utc)
    return Fragment(
        id=fid,
        kind=kind,
        scope=scope,
        text=text,
        owner_user="founder",
        provenance=Provenance(contributing_agent="test",
                              contributing_user="founder", created_at=ts),
    )


# ── the headline gate: a KNOWN n-gram overlap is flagged ─────────────────────

def test_decontamination_flags_known_ngram_overlap():
    """A train row that is a near-duplicate (case/whitespace churn, not byte
    identical) of an eval item is flagged by the n-gram detector."""
    eval_rows = [{"id": "e1", "text": _EVAL_TEXT}]
    # Same sentence, different case + spacing -> NOT an exact-hash match, but a
    # full n-gram overlap.
    train_rows = [
        {"id": "t_clean", "text": "Slab edges in Revit host a cornice profile."},
        {"id": "t_leak", "text": "  TO ANCHOR a CURTAIN wall MULLION in revit "
                                  "set the WORK plane to the level datum and "
                                  "dimension from the structural grid line "
                                  "origin point.  "},
    ]
    report = scan_decontamination(train_rows, eval_rows)
    assert report.scanned is True
    assert report.clean is False
    assert "t_leak" in report.contaminated_train_ids
    assert "t_clean" not in report.contaminated_train_ids
    # the flagged row names the n-gram detector + the eval item it leaked
    c = next(c for c in report.contaminations if c.train_id == "t_leak")
    assert c.detector in {"ngram", "exact"}
    assert c.eval_id == "e1"


def test_decontamination_flags_exact_verbatim_leak():
    eval_rows = [{"id": "e1", "text": _EVAL_TEXT}]
    train_rows = [{"id": "t_verbatim", "text": _EVAL_TEXT}]
    report = scan_decontamination(train_rows, eval_rows)
    assert report.clean is False
    c = report.contaminations[0]
    assert c.train_id == "t_verbatim"
    assert c.detector == "exact"


def test_decontamination_clean_set_passes():
    eval_rows = [{"id": "e1", "text": _EVAL_TEXT}]
    train_rows = [
        {"id": "t1", "text": "Rooms in Revit need a bounding wall to compute area."},
        {"id": "t2", "text": "A dimension string references two parallel grids."},
    ]
    report = scan_decontamination(train_rows, eval_rows)
    assert report.scanned is True
    assert report.clean is True
    assert report.contaminated_train_ids == set()


def test_decontamination_flags_canary_string():
    eval_rows = [{"id": "e1", "text": "unrelated held-out content here for shape"}]
    canary = "ZZQ-CANARY-7f3a-do-not-train"
    train_rows = [
        {"id": "t_ok", "text": "a perfectly ordinary training row about walls"},
        {"id": "t_canary", "text": f"leaked memo containing {canary} inside it"},
    ]
    report = scan_decontamination(train_rows, eval_rows, canaries=[canary])
    assert report.clean is False
    assert "t_canary" in report.contaminated_train_ids
    assert next(c for c in report.contaminations
                if c.train_id == "t_canary").detector == "canary"


def test_decontamination_honest_when_no_holdout():
    """No eval holdout -> scanned=False (honest 'not scanned'), never a fake
    'clean' that a caller could mistake for a real pass."""
    report = scan_decontamination([{"id": "t1", "text": "anything"}], None)
    assert isinstance(report, DecontaminationReport)
    assert report.scanned is False


def test_decontamination_reads_spo_triple_not_just_text():
    """A fact stored as a subject/predicate/object triple (no `text`) is still
    decontaminated — the scan reads the whole comparable surface."""
    eval_rows = [{"id": "e1", "subject": "curtain wall mullion anchor procedure",
                  "predicate": "requires", "object": "work plane set to level datum"}]
    train_rows = [{"id": "t_spo", "subject": "curtain wall mullion anchor procedure",
                   "predicate": "requires", "object": "work plane set to level datum"}]
    report = scan_decontamination(train_rows, eval_rows)
    assert report.clean is False
    assert "t_spo" in report.contaminated_train_ids


# ── acceptance #18: time-split (eval items all post-cutoff) ──────────────────

def test_decontamination_time_split_eval_is_post_cutoff():
    now = datetime.now(timezone.utc)
    rows = [
        {"id": "old1", "created_at": (now - timedelta(days=10)).isoformat()},
        {"id": "old2", "created_at": (now - timedelta(days=5)).isoformat()},
        {"id": "new1", "created_at": (now + timedelta(days=1)).isoformat()},
    ]
    cutoff = now.isoformat()
    train, eval_ = time_split(rows, cutoff)
    assert {r["id"] for r in train} == {"old1", "old2"}
    assert {r["id"] for r in eval_} == {"new1"}


def test_decontamination_time_split_unknown_vintage_goes_to_train():
    """A row with no parseable created_at must never silently become a held-out
    eval item (that would defeat the time-split guarantee) -> it lands in train."""
    rows = [{"id": "no_ts"}, {"id": "bad_ts", "created_at": "not-a-date"}]
    train, eval_ = time_split(rows, datetime.now(timezone.utc))
    assert {r["id"] for r in train} == {"no_ts", "bad_ts"}
    assert eval_ == []


# ── export-time enforcement: the dataset writer drops the contaminated row ───

@pytest.fixture
def store(tmp_path) -> Store:
    return Store.open(tmp_path / "decon.db")


def test_export_decontamination_drops_leaked_training_row(store, tmp_path):
    """End-to-end: a fragment that leaks a held-out eval item is EXCLUDED from
    the written dataset, and the manifest records the scan."""
    store.write_fragment(_frag("f_clean", "ordinary fact about door schedules"))
    store.write_fragment(_frag("f_leak", _EVAL_TEXT))
    eval_holdout = [{"id": "e1", "text": _EVAL_TEXT}]

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-decon",
        eval_holdout=eval_holdout,
    )

    assert manifest["decontamination"]["enforced"] is True
    assert manifest["decontamination"]["excluded_count"] == 1
    assert manifest["decontamination"]["report"]["clean"] is False
    # the written rows must NOT contain the leaked fragment
    jsonl = Path(manifest["files"]["jsonl"]["path"])
    ids = {json.loads(line)["id"] for line in
           jsonl.read_text(encoding="utf-8").strip().splitlines() if line}
    assert "f_leak" not in ids
    assert "f_clean" in ids
    assert manifest["row_count"] == 1


def test_export_without_holdout_does_not_scan(store, tmp_path):
    """No holdout -> no scan ran, honest report, all rows written."""
    store.write_fragment(_frag("f1", "a"))
    manifest = export_fragments(
        store, out_dir=tmp_path / "exp2", dataset_name="ds-noscan",
    )
    assert manifest["decontamination"]["enforced"] is False
    assert manifest["row_count"] == 1
