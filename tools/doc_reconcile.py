#!/usr/bin/env python3
"""doc_reconcile — the documentation-always-up-to-date gate (DOC-01/02).

Founder ask (2026-06-15): keep the docs reconciled with reality so the
ROADMAP never drifts from what is actually merged. This is the merge-time
gate that makes "documentation up to date" a CHECK, not a hope — the same
shape as the brain/commit/reality gates already in `tools/`.

It fails a PR when ANY of three drift classes is present:

  R1  STALE-CHECKED   — a `docs/ROADMAP.md` "- [x]" item is marked DONE but
                        carries NO proof receipt (no PR `#NNN`, no commit SHA,
                        no `✓`/SHIPPED/FIXED/RESOLVED/verified marker). "Done"
                        with no evidence is exactly the ANTI-LIE failure the
                        founder banned — a green with no artifact behind it.

  R2  AGDR-COLLISION  — two files under `docs/agdr/` declare the SAME `id:`
                        in their YAML frontmatter (e.g. the untracked
                        `AgDR-0054-revit-transactionless-exec.md` colliding
                        with the tracked `AgDR-0054-collective-mind-one-brain`).
                        A duplicate decision-record id makes the ledger
                        ambiguous — the gate forces a renumber.

  R3  SHIPPED-OPEN    — an item KNOWN to be shipped (its receipt lives in the
                        SHIPPED_RECEIPTS ledger below, derived from the merged
                        git history) is still sitting as "- [ ]" (open) — or is
                        absent from the roadmap entirely. The doc lags the code.

DESIGN — ONE SYSTEM, no parallel store
--------------------------------------
This gate READS the existing sources of truth (`docs/ROADMAP.md`, the
`docs/agdr/*.md` frontmatter) using the SAME parsing shape the autonomous
loop already uses in `agents/roadmap_source.py` (the `- [x]`/`- [ ]` bullet
grammar, the `#P0/#P1/#P2` tags, the `Done` section skip). It does NOT mint a
new roadmap, a new ledger table, or a second backlog file — per the ROADMAP +
ONE-SYSTEM mandates. The SHIPPED_RECEIPTS map is the only new datum: a small,
auditable record of "what merged + its PR receipt," which is precisely the
fact a doc-reconcile gate must hold to know the doc lags reality.

EXIT CONTRACT
-------------
  exit 0  = reconciled (zero violations)
  exit 1  = drift found — the violations are printed (one per line) to stderr
            and a machine-readable summary to stdout.

This module is import-safe (no side effects at import) so the pytest gate can
call `find_violations(...)` directly against the repo's real files.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
ROADMAP_PATH = REPO_ROOT / "docs" / "ROADMAP.md"
AGDR_DIR = REPO_ROOT / "docs" / "agdr"
BUILT_MAP_PATH = REPO_ROOT / "docs" / "BUILT_MAP.md"


# ──────────────────────────────────────────────────────────────────────────
# SHIPPED_RECEIPTS — the merged-truth ledger (DOC-02).
#
# Each entry: a stable `key` (a substring that uniquely identifies the
# roadmap line for the shipped work) → its proof `receipt` (PR number(s) +
# one-line what). The reconcile step (R3) asserts that for every shipped
# entry the roadmap carries a CHECKED (`- [x]`) line matching the key, with
# the receipt present. Derived from `git log origin/main` — NOT hand-waved:
# every PR number below resolves to a real merge commit.
#
# This is the session's merged set per the DOC-02 ask. Add a row here the
# moment a PR merges and the gate keeps the roadmap honest forever after.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ShippedReceipt:
    key: str            # unique substring of the roadmap line (case-insensitive)
    receipt: str        # the proof string that MUST appear on the checked line
    summary: str        # plain-English what-shipped (for the generated map)


SHIPPED_RECEIPTS: tuple[ShippedReceipt, ...] = (
    ShippedReceipt(
        key="NVIDIA NIM provider",
        receipt="#122",
        summary="NVIDIA NIM models in the picker (one key unlocks the catalog) "
                "via the OpenAI-compatible endpoint.",
    ),
    ShippedReceipt(
        key="boot-hang — LM Studio probe off the Qt main thread",
        receipt="#123",
        summary="APP-01 boot-hang: route the LM Studio probe in get_models off "
                "the Qt main thread.",
    ),
    ShippedReceipt(
        key="boot-hang — off-thread the last 3 provider slots",
        receipt="#129",
        summary="APP-01 boot-hang root: off-thread the last 3 provider slots + "
                "close the blind guard.",
    ),
    ShippedReceipt(
        key="brain-driver active-work ledger",
        receipt="#124",
        summary="BRV-01/02 brain-driver active-work ledger (server-authoritative).",
    ),
    ShippedReceipt(
        key="wire THE DRIVE into the runtime",
        receipt="#128",
        summary="Wire THE DRIVE into the runtime + cross-process atomic claim "
                "(court defect #5 + latent race).",
    ),
    ShippedReceipt(
        key="connector honesty — CON-01",
        receipt="#125",
        summary="CON-01 connector honesty: no fabricated empty DirectShape; "
                "honest status surfaced.",
    ),
    ShippedReceipt(
        key="gate send_to_speckle — CON-02",
        receipt="#127",
        summary="CON-02: gate send_to_speckle as kind=action (was an un-gated "
                "AI write mislabeled read).",
    ),
    ShippedReceipt(
        key="Skills + Search sidebar panels",
        receipt="#126",
        summary="Wire the Skills + Search sidebar panels REAL (MAKE-IT-REAL).",
    ),
)


# ──────────────────────────────────────────────────────────────────────────
# Receipt detection — what counts as proof on a checked line.
# ──────────────────────────────────────────────────────────────────────────
# A PR / issue reference: `#NNN` (2+ digits — `#1` is too ambiguous).
_RECEIPT_PR = re.compile(r"#\d{2,}")
# A git short SHA: 7-40 hex chars as a standalone token (word-boundaried,
# and containing at least one digit so plain English words like "deeded"
# or "facade" don't read as a SHA).
_RECEIPT_SHA = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
# Textual proof markers that ride on genuinely-shipped roadmap lines.
_RECEIPT_WORDS = re.compile(
    r"(?:✓|✅|SHIPPED|FIXED|RESOLVED|DONE|LANDED|verified|"
    r"green|tests?\b|guard\b|CDP-PROVEN|live-proven|live-verified)",
    re.IGNORECASE,
)


def line_has_receipt(text: str) -> bool:
    """True iff a checked roadmap line carries SOME proof of completion.

    Proof = a PR/issue ref (`#NNN`), a commit SHA, or a textual ship-marker
    (`✓` / SHIPPED / FIXED / RESOLVED / verified / a test/guard mention …).
    A `- [x]` with none of these is a bare claim — the R1 drift class.
    """
    return bool(
        _RECEIPT_PR.search(text)
        or _RECEIPT_SHA.search(text)
        or _RECEIPT_WORDS.search(text)
    )


# ──────────────────────────────────────────────────────────────────────────
# Roadmap parsing — mirrors agents/roadmap_source.py's bullet grammar.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RoadmapItem:
    lineno: int
    raw: str               # the full line as written
    text: str              # line with the `- [x]`/`- [ ]` prefix stripped
    checked: bool          # True for `- [x]`, False for `- [ ]`
    in_done_section: bool   # under a "Done" heading (autopopulated archive)


_CHECKBOX = re.compile(r"^\s*- \[( |x|X)\]\s?(.*)$")


def parse_roadmap(text: str) -> list[RoadmapItem]:
    """Every checkbox bullet in the roadmap, with done-section context.

    `## Done — last 7 days` (and any heading containing "done") flips the
    `in_done_section` flag — those archived lines are still parsed (so the
    R3 reconcile can find a shipped receipt that was moved there) but are
    EXEMPT from the R1 stale-checked rule, because archived ships are summary
    rows, not live claims.
    """
    items: list[RoadmapItem] = []
    in_done = False
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("## "):
            in_done = "done" in stripped.lower()
            continue
        m = _CHECKBOX.match(raw)
        if not m:
            continue
        checked = m.group(1).lower() == "x"
        items.append(
            RoadmapItem(
                lineno=i,
                raw=raw.rstrip(),
                text=m.group(2).strip(),
                checked=checked,
                in_done_section=in_done,
            )
        )
    return items


# ──────────────────────────────────────────────────────────────────────────
# AgDR frontmatter id scan (R2).
# ──────────────────────────────────────────────────────────────────────────
_FRONT_ID = re.compile(r"^id:\s*(\S+)", re.MULTILINE)


def scan_agdr_ids(agdr_dir: Optional[Path] = None) -> dict[str, list[str]]:
    """Map `AgDR-NNNN` id → [filenames that declare it] across docs/agdr.

    Reads the `id:` line from each `.md`'s YAML frontmatter. A value list
    with len > 1 is a COLLISION (the R2 drift class). Filenames-only are
    returned (not full paths) so the verdict is environment-independent.
    """
    if agdr_dir is None:
        agdr_dir = AGDR_DIR
    out: dict[str, list[str]] = {}
    if not agdr_dir.exists():
        return out
    for path in sorted(agdr_dir.glob("AgDR-*.md")):
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except Exception:
            continue
        m = _FRONT_ID.search(head)
        if not m:
            continue
        agdr_id = m.group(1).strip()
        out.setdefault(agdr_id, []).append(path.name)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Violation model + the three checks.
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Violation:
    rule: str               # "R1" | "R2" | "R3"
    where: str              # file:line or filename(s)
    message: str            # human-readable explanation

    def __str__(self) -> str:  # one-line CI-friendly rendering
        return f"[{self.rule}] {self.where}: {self.message}"


@dataclass
class ReconcileResult:
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def by_rule(self, rule: str) -> list[Violation]:
        return [v for v in self.violations if v.rule == rule]


def check_stale_checked(items: Iterable[RoadmapItem], *, roadmap_name: str
                        ) -> list[Violation]:
    """R1 — every live `- [x]` must carry a proof receipt."""
    out: list[Violation] = []
    for it in items:
        if not it.checked or it.in_done_section:
            continue
        if not line_has_receipt(it.text):
            out.append(Violation(
                rule="R1",
                where=f"{roadmap_name}:{it.lineno}",
                message=(
                    "checked item has NO proof receipt (no #PR / SHA / "
                    "SHIPPED / FIXED / verified / test marker) — a bare "
                    f'"done" claim: {it.text[:90]!r}'
                ),
            ))
    return out


def check_agdr_collisions(id_map: dict[str, list[str]]) -> list[Violation]:
    """R2 — no two AgDR files may declare the same id."""
    out: list[Violation] = []
    for agdr_id, files in sorted(id_map.items()):
        if len(files) > 1:
            out.append(Violation(
                rule="R2",
                where=", ".join(files),
                message=(
                    f"AgDR id {agdr_id!r} is declared by {len(files)} files — "
                    "a duplicate decision-record id makes the ledger "
                    "ambiguous; renumber all but one."
                ),
            ))
    return out


def check_shipped_open(items: list[RoadmapItem], *, roadmap_name: str,
                       receipts: Iterable[ShippedReceipt] = SHIPPED_RECEIPTS
                       ) -> list[Violation]:
    """R3 — every shipped receipt must map to a CHECKED roadmap line.

    For each ledger entry we look for ANY roadmap line whose text contains
    the entry's `key` (case-insensitive). Failure modes:
      * a matching line exists but is `- [ ]` (open) → the doc lags the code.
      * a matching line exists, is checked, but lacks the receipt string →
        checked without its proof (a softer R1, caught here with the exact
        expected receipt named).
      * no matching line at all → the shipped work is undocumented.
    """
    out: list[Violation] = []
    for rcpt in receipts:
        key_l = rcpt.key.lower()
        matches = [it for it in items if key_l in it.text.lower()]
        if not matches:
            out.append(Violation(
                rule="R3",
                where=roadmap_name,
                message=(
                    f"shipped work {rcpt.key!r} (receipt {rcpt.receipt}) has "
                    "NO line in the roadmap — merged code, undocumented."
                ),
            ))
            continue
        # Prefer a checked match; if any checked match carries the receipt,
        # the item is reconciled.
        reconciled = any(
            it.checked and rcpt.receipt.lower() in it.text.lower()
            for it in matches
        )
        if reconciled:
            continue
        # Not reconciled — diagnose the closest match (first one).
        first = matches[0]
        if not any(it.checked for it in matches):
            out.append(Violation(
                rule="R3",
                where=f"{roadmap_name}:{first.lineno}",
                message=(
                    f"shipped work {rcpt.key!r} (receipt {rcpt.receipt}) is "
                    "still OPEN '- [ ]' in the roadmap — flip it to '- [x]' "
                    "with its PR receipt."
                ),
            ))
        else:
            out.append(Violation(
                rule="R3",
                where=f"{roadmap_name}:{first.lineno}",
                message=(
                    f"shipped work {rcpt.key!r} is checked but is MISSING its "
                    f"proof receipt {rcpt.receipt} — add the PR number to the "
                    "line."
                ),
            ))
    return out


def find_violations(
    *,
    roadmap_path: Optional[Path] = None,
    agdr_dir: Optional[Path] = None,
    receipts: Iterable[ShippedReceipt] = SHIPPED_RECEIPTS,
    check_shipped: bool = True,
) -> ReconcileResult:
    """Run all three drift checks against the real (or supplied) files."""
    roadmap_path = roadmap_path or ROADMAP_PATH
    roadmap_name = roadmap_path.name

    result = ReconcileResult()

    if roadmap_path.exists():
        items = parse_roadmap(roadmap_path.read_text(encoding="utf-8"))
        result.violations += check_stale_checked(items, roadmap_name=roadmap_name)
        if check_shipped:
            result.violations += check_shipped_open(
                items, roadmap_name=roadmap_name, receipts=receipts)
    else:
        result.violations.append(Violation(
            rule="R1", where=str(roadmap_path),
            message="roadmap file does not exist",
        ))

    result.violations += check_agdr_collisions(scan_agdr_ids(agdr_dir))
    return result


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _format_report(result: ReconcileResult) -> str:
    if result.ok:
        return "doc-reconcile: OK — ROADMAP + AgDR ledger reconciled."
    lines = [f"doc-reconcile: {len(result.violations)} DRIFT VIOLATION(S)\n"]
    for rule, name in (("R1", "stale-checked (no receipt)"),
                       ("R2", "AgDR id collision"),
                       ("R3", "shipped-but-open / undocumented")):
        vs = result.by_rule(rule)
        if vs:
            lines.append(f"── {rule} · {name} ({len(vs)}) ──")
            lines.extend(f"  {v}" for v in vs)
            lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Reconcile docs/ROADMAP.md + AgDR ledger against reality.")
    ap.add_argument("--roadmap", type=Path, default=None,
                    help="path to ROADMAP.md (default: docs/ROADMAP.md)")
    ap.add_argument("--agdr-dir", type=Path, default=None,
                    help="path to docs/agdr (default: docs/agdr)")
    ap.add_argument("--no-shipped", action="store_true",
                    help="skip the R3 shipped-receipt reconciliation")
    args = ap.parse_args(argv)

    result = find_violations(
        roadmap_path=args.roadmap,
        agdr_dir=args.agdr_dir,
        check_shipped=not args.no_shipped,
    )
    report = _format_report(result)
    if result.ok:
        print(report)
        return 0
    # Drift → human report to stderr, machine summary to stdout, exit 1.
    print(report, file=sys.stderr)
    print(f"VIOLATIONS={len(result.violations)} "
          f"R1={len(result.by_rule('R1'))} "
          f"R2={len(result.by_rule('R2'))} "
          f"R3={len(result.by_rule('R3'))}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
