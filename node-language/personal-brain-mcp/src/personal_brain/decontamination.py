"""Brain #32/#33 · train<->eval decontamination scan (AgDR-0054 acceptance #12/#18).

THE GAP THIS CLOSES. `dataset_export.py` documented a "`content_hash_post`
decontamination scan" as *pending* (its docstring said so) and the
`Fragment.content_hash_post` field was added "for the train<->eval
decontamination scan" — but **no code ever performed that scan**. An export
could therefore ship a training row that is byte-identical to (or heavily
n-gram-overlapping with) a held-out eval item, silently inflating every later
eval score: the circular-eval / contamination risk AgDR-0054 §Eval-protocol and
acceptance #12/#18 names. This module is the actual scan.

What "decontamination" means here (three independent detectors, defence-in-depth
— no single layer trusted, mirroring the poisoning-stack pattern):

  - **EXACT (hash).** A normalised SHA-256 of each row's text. A train row whose
    hash collides with any eval row's hash is a verbatim leak -> flagged.
  - **N-GRAM (Carlini-style).** Word n-gram (default 13-gram, the standard
    contamination window) Jaccard-ish overlap: a train row sharing >= a fraction
    of its n-gram shingles with some eval item is a near-duplicate leak ->
    flagged even when not byte-identical (whitespace/case/edit churn).
  - **CANARY.** Explicit canary strings seeded into the eval set (memorisation
    probes). A train row containing a canary is a leak of the held-out set ->
    flagged.

What it produces: a typed `DecontaminationReport` listing every contaminated
train-row id, the detector that caught it, and the offending eval id/overlap.
The report is *honest*: with no eval holdout supplied it returns
`scanned=False` (not a fake "clean"), so a caller can never mistake "not
scanned" for "scanned and clean".

Time-split (acceptance #18: eval items all post-training-cutoff). `time_split`
partitions rows by `created_at` at a cutoff: train = strictly-before, eval =
at-or-after. Decontamination then proves the split is clean — the two halves
together are the eval protocol's first line (a leak across the time boundary is
exactly what contaminates a held-out suite).

ONE-SYSTEM: this is the scan `dataset_export.export_fragments` calls when an
`eval_holdout` is supplied (it does not mint a parallel exporter); it operates
on the SAME flattened export rows (`_fragment_to_row`) the dataset writes.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


# 13-gram is the conventional contamination-detection window (Brown et al. /
# Carlini decontamination use 8-13 token spans); a row shorter than n is hashed
# whole as its single shingle so short rows are still comparable.
_DEFAULT_NGRAM = 13
# A train row sharing >= this fraction of ITS shingles with one eval item is a
# near-duplicate leak. 0.5 catches paraphrase/edit churn without flagging the
# incidental boilerplate overlap two unrelated rows share.
_DEFAULT_NGRAM_THRESHOLD = 0.5

_WORD = re.compile(r"\w+", re.UNICODE)


def _normalise(text: str) -> str:
    """Lowercase + collapse whitespace — the canonical form both the exact-hash
    and n-gram detectors compare on, so trivial case/whitespace churn cannot
    smuggle a verbatim eval row into the training set."""
    return " ".join((text or "").lower().split())


def _row_hash(text: str) -> str:
    """Stable normalised SHA-256 of a row's text (the exact-leak key)."""
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()


def _shingles(text: str, n: int) -> set[str]:
    """The set of word n-grams in `text` (its contamination fingerprint).

    A text with fewer than `n` words yields a single shingle (the whole text),
    so short rows still participate in overlap detection rather than silently
    matching nothing.
    """
    words = _WORD.findall((text or "").lower())
    if not words:
        return set()
    if len(words) < n:
        return {" ".join(words)}
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _row_text(row: Any) -> str:
    """Extract the comparable text from an export row (dict) or a Fragment-like
    object. Concatenates the S/P/O triple + free text so a fact stored as a
    triple is decontaminated too, not just `text`-bearing rows."""
    if isinstance(row, dict):
        parts = [
            str(row.get("subject") or ""),
            str(row.get("predicate") or ""),
            str(row.get("object") or ""),
            str(row.get("text") or ""),
        ]
        return " ".join(p for p in parts if p).strip()
    # Fragment-like: pull the same fields by attribute.
    parts = [
        str(getattr(row, "subject", "") or ""),
        str(getattr(row, "predicate", "") or ""),
        str(getattr(row, "object", "") or ""),
        str(getattr(row, "text", "") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _row_id(row: Any, fallback: int) -> str:
    if isinstance(row, dict):
        return str(row.get("id") or f"row_{fallback}")
    return str(getattr(row, "id", None) or f"row_{fallback}")


def _row_created_at(row: Any) -> Optional[datetime]:
    """Best-effort `created_at` as an aware datetime (UTC), for time_split."""
    if isinstance(row, dict):
        raw = row.get("created_at")
    else:
        raw = getattr(row, "created_at", None)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


@dataclass
class Contamination:
    """One contaminated TRAIN row + why it was flagged."""

    train_id: str
    detector: str               # "exact" | "ngram" | "canary"
    eval_id: Optional[str] = None
    overlap: float = 1.0        # 1.0 for exact/canary; n-gram overlap fraction
    detail: str = ""


@dataclass
class DecontaminationReport:
    """Result of a train<->eval decontamination scan.

    `scanned` is False ONLY when no eval holdout was supplied — an honest "not
    scanned", never confused with "scanned and clean" (`clean=True`,
    `scanned=True`). `clean` is True iff zero contaminations were found.
    """

    scanned: bool
    clean: bool
    train_count: int = 0
    eval_count: int = 0
    ngram: int = _DEFAULT_NGRAM
    contaminations: list[Contamination] = field(default_factory=list)

    @property
    def contaminated_train_ids(self) -> set[str]:
        return {c.train_id for c in self.contaminations}

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "clean": self.clean,
            "train_count": self.train_count,
            "eval_count": self.eval_count,
            "ngram": self.ngram,
            "contaminated_count": len(self.contaminated_train_ids),
            "contaminations": [
                {
                    "train_id": c.train_id,
                    "detector": c.detector,
                    "eval_id": c.eval_id,
                    "overlap": round(c.overlap, 4),
                    "detail": c.detail,
                }
                for c in self.contaminations
            ],
        }


def scan_decontamination(
    train_rows: Iterable[Any],
    eval_rows: Optional[Iterable[Any]],
    *,
    ngram: int = _DEFAULT_NGRAM,
    ngram_threshold: float = _DEFAULT_NGRAM_THRESHOLD,
    canaries: Optional[Iterable[str]] = None,
) -> DecontaminationReport:
    """Flag every TRAIN row that leaks a held-out EVAL item.

    Runs three detectors (exact hash, word-n-gram overlap, canary substring) and
    returns a typed report. `eval_rows=None` (or empty) -> `scanned=False`: an
    honest "no holdout to scan against", NOT a fake clean pass.

    The detectors are deliberately independent: a row caught by any one is
    contaminated. The first detector to flag a given train row wins its
    `Contamination` record (exact > ngram > canary), so the report is one entry
    per contaminated train row with the strongest reason.
    """
    if eval_rows is None:
        return DecontaminationReport(scanned=False, clean=True, ngram=ngram)

    eval_list = list(eval_rows)
    train_list = list(train_rows)
    canary_list = [c for c in (canaries or []) if c]

    if not eval_list:
        return DecontaminationReport(
            scanned=False, clean=True, train_count=len(train_list), ngram=ngram
        )

    # Index the eval side once.
    eval_hashes: dict[str, str] = {}          # hash -> eval_id
    eval_shingles: list[tuple[str, set[str]]] = []  # (eval_id, shingles)
    for i, er in enumerate(eval_list):
        etext = _row_text(er)
        eid = _row_id(er, i)
        eval_hashes.setdefault(_row_hash(etext), eid)
        eval_shingles.append((eid, _shingles(etext, ngram)))

    canary_norm = [(_normalise(c), c) for c in canary_list]

    contaminations: list[Contamination] = []
    for j, tr in enumerate(train_list):
        ttext = _row_text(tr)
        tid = _row_id(tr, j)

        # 1) EXACT — verbatim leak.
        thash = _row_hash(ttext)
        if thash in eval_hashes:
            contaminations.append(
                Contamination(
                    train_id=tid,
                    detector="exact",
                    eval_id=eval_hashes[thash],
                    overlap=1.0,
                    detail="verbatim train==eval (normalised SHA-256 match)",
                )
            )
            continue

        # 2) N-GRAM — near-duplicate leak.
        tshingles = _shingles(ttext, ngram)
        if tshingles:
            best_id, best_overlap = None, 0.0
            for eid, eshingles in eval_shingles:
                if not eshingles:
                    continue
                shared = len(tshingles & eshingles)
                if shared == 0:
                    continue
                overlap = shared / len(tshingles)
                if overlap > best_overlap:
                    best_id, best_overlap = eid, overlap
            if best_overlap >= ngram_threshold:
                contaminations.append(
                    Contamination(
                        train_id=tid,
                        detector="ngram",
                        eval_id=best_id,
                        overlap=best_overlap,
                        detail=f"{ngram}-gram overlap {best_overlap:.2f} "
                        f">= threshold {ngram_threshold:.2f}",
                    )
                )
                continue

        # 3) CANARY — memorisation probe leaked into train text.
        tnorm = _normalise(ttext)
        hit = next((orig for cnorm, orig in canary_norm if cnorm and cnorm in tnorm), None)
        if hit is not None:
            contaminations.append(
                Contamination(
                    train_id=tid,
                    detector="canary",
                    eval_id=None,
                    overlap=1.0,
                    detail=f"canary string present in train row: {hit!r}",
                )
            )

    return DecontaminationReport(
        scanned=True,
        clean=not contaminations,
        train_count=len(train_list),
        eval_count=len(eval_list),
        ngram=ngram,
        contaminations=contaminations,
    )


def time_split(
    rows: Iterable[Any],
    cutoff: Any,
) -> tuple[list[Any], list[Any]]:
    """Partition `rows` by `created_at` at `cutoff` (AgDR-0054 acceptance #18).

    Returns ``(train, eval)`` where train = rows strictly BEFORE the cutoff and
    eval = rows AT-OR-AFTER it — so every eval item is post-training-cutoff by
    construction. Rows with no parseable `created_at` are placed in TRAIN (a row
    of unknown vintage must never silently become a held-out eval item — that
    would defeat the time-split's contamination guarantee). `cutoff` accepts an
    ISO8601 string or a datetime (naive is treated as UTC).
    """
    if isinstance(cutoff, str):
        cutoff_dt = datetime.fromisoformat(cutoff)
    elif isinstance(cutoff, datetime):
        cutoff_dt = cutoff
    else:
        raise TypeError(f"cutoff must be ISO8601 str or datetime, got {type(cutoff)!r}")
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)

    train: list[Any] = []
    eval_: list[Any] = []
    for r in rows:
        ts = _row_created_at(r)
        if ts is not None and ts >= cutoff_dt:
            eval_.append(r)
        else:
            train.append(r)
    return train, eval_
