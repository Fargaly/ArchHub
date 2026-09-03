#!/usr/bin/env python3
"""build_map — generate the "what is built" map from DERIVED truth (DOC-02 #3).

The founder asked for a build-map that is NOT hand-typed: it must come from the
machine-checkable state the project already records. Two sources, both derived:

  1. AgDR ledger status — every `docs/agdr/AgDR-*.md` carries a `status:` line
     in its YAML frontmatter (`executed` / `proposed` / `superseded` / …). That
     status is the project's own record of whether a decision is BUILT. We read
     it straight from the files — no human re-typing.

  2. Requirement-tree GREEN leaves — the ROMA ledger
     (`personal_brain.requirement_tree`, persisted in `brain_meta`) records each
     vision-tree's leaves and whether the external court FAILED TO REFUTE them
     (`state == GREEN`). A green leaf is a verified-complete unit of work. We list
     them when the brain store is reachable; we skip that section cleanly when it
     is not (a fresh clone / CI with no brain has no trees — that is not an error).

Output: `docs/BUILT_MAP.md`, regenerated in place. The generator is
deterministic (sorted), so re-running with no state change produces a
byte-identical file — which lets a CI check assert the committed map is current
(the same shape the grammar-health / drift guards use).

Run:
    python tools/build_map.py            # regenerate docs/BUILT_MAP.md
    python tools/build_map.py --check    # exit 1 if the committed map is stale
    python tools/build_map.py --stdout   # print the map, don't write
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
AGDR_DIR = REPO_ROOT / "docs" / "agdr"
BUILT_MAP_PATH = REPO_ROOT / "docs" / "BUILT_MAP.md"
_BRAIN_SRC = REPO_ROOT / "personal-brain-mcp" / "src"


# ──────────────────────────────────────────────────────────────────────────
# Source 1 — AgDR frontmatter status.
# ──────────────────────────────────────────────────────────────────────────
_FRONT_ID = re.compile(r"^id:\s*(\S+)", re.MULTILINE)
_FRONT_STATUS = re.compile(r"^status:\s*(.+)$", re.MULTILINE)
_FRONT_TITLE = re.compile(r"^title:\s*(.+)$", re.MULTILINE)
# The H1 (`# AgDR-NNNN — …`) is the human title when frontmatter has none.
_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class AgdrRecord:
    agdr_id: str
    status: str           # raw frontmatter status (lower-cased, first word kept)
    status_class: str     # "built" | "planned" | "superseded" | "unknown"
    title: str
    filename: str


def _classify_status(raw: str) -> str:
    """Bucket a free-form AgDR status into one of four classes.

    The status field is prose in many records ("executed — founder-signed …",
    "proposed", "superseded by AgDR-0048", "PLAN-LOCKED (needs go)"). We bucket
    on the leading keyword so the map reflects the project's own language.
    """
    low = raw.strip().lower()
    if low.startswith("superseded") or "superseded by" in low:
        return "superseded"
    if low.startswith(("executed", "shipped", "done", "implemented")):
        return "built"
    # `approved-direction · build-pending` is direction-locked but NOT built —
    # it must read as planned, never built (the DOC-07 distinction). It is
    # listed before the bare "approved" prefix so the compound is unambiguous.
    if low.startswith(("approved-direction", "build-pending")):
        return "planned"
    if low.startswith(("proposed", "plan-locked", "planned", "executing",
                       "approved", "draft", "rework")):
        return "planned"
    return "unknown"


def scan_agdrs(agdr_dir: Optional[Path] = None) -> list[AgdrRecord]:
    """Read every AgDR file's id / status / title from frontmatter."""
    if agdr_dir is None:
        agdr_dir = AGDR_DIR
    out: list[AgdrRecord] = []
    if not agdr_dir.exists():
        return out
    for path in sorted(agdr_dir.glob("AgDR-*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        head = text[:2500]
        mid = _FRONT_ID.search(head)
        agdr_id = mid.group(1).strip() if mid else path.stem.split("-")[0]
        mst = _FRONT_STATUS.search(head)
        raw_status = mst.group(1).strip() if mst else "unknown"
        mtitle = _FRONT_TITLE.search(head)
        if mtitle:
            title = mtitle.group(1).strip()
        else:
            mh1 = _H1.search(text)
            title = mh1.group(1).strip() if mh1 else path.stem
        out.append(AgdrRecord(
            agdr_id=agdr_id,
            status=raw_status,
            status_class=_classify_status(raw_status),
            title=title,
            filename=path.name,
        ))
    return out


def _agdr_sort_key(rec: AgdrRecord) -> tuple:
    m = re.search(r"(\d+)", rec.agdr_id)
    return (int(m.group(1)) if m else 9999, rec.filename)


# ──────────────────────────────────────────────────────────────────────────
# Source 2 — requirement-tree GREEN leaves (best-effort; skipped if no brain).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GreenLeaf:
    tree_title: str
    leaf_title: str
    predicate: str


def scan_green_leaves() -> tuple[list[GreenLeaf], str]:
    """List every GREEN leaf across all requirement trees in the brain store.

    Returns (leaves, note). `note` explains why the list is empty when it is
    (no brain module / no DB / zero trees) so the generated map is honest about
    its own coverage rather than silently omitting the section.
    """
    if _BRAIN_SRC.exists() and str(_BRAIN_SRC) not in sys.path:
        sys.path.insert(0, str(_BRAIN_SRC))
    try:
        from personal_brain.requirement_tree import (  # type: ignore
            NodeState, TreeStore,
        )
        from personal_brain.storage import BrainStore  # type: ignore
    except Exception as exc:  # brain not importable (fresh clone / CI)
        return [], f"requirement-tree source not importable ({exc.__class__.__name__})"

    try:
        store = BrainStore.open()  # opens the default brain.db location
    except Exception as exc:
        return [], f"brain store unavailable ({exc.__class__.__name__})"

    leaves: list[GreenLeaf] = []
    try:
        ts = TreeStore(store)
        tree_ids = ts.list_trees()
        for tid in tree_ids:
            tree = ts.load(tid)
            if tree is None:
                continue
            for leaf in tree.leaves():
                if leaf.state == NodeState.GREEN:
                    leaves.append(GreenLeaf(
                        tree_title=tree.title or tree.tree_id,
                        leaf_title=leaf.title,
                        predicate=leaf.predicate or "",
                    ))
    except Exception as exc:
        return leaves, f"partial scan ({exc.__class__.__name__})"
    finally:
        try:
            store.close()
        except Exception:
            pass

    leaves.sort(key=lambda g: (g.tree_title.lower(), g.leaf_title.lower()))
    note = (f"{len(tree_ids)} requirement tree(s) in the brain store"
            if leaves or tree_ids else "no requirement trees recorded yet")
    return leaves, note


# ──────────────────────────────────────────────────────────────────────────
# Render.
# ──────────────────────────────────────────────────────────────────────────
def render_map(
    agdrs: list[AgdrRecord],
    green_leaves: list[GreenLeaf],
    leaf_note: str,
    *,
    today: Optional[str] = None,
) -> str:
    today = today or date.today().isoformat()
    built = sorted([a for a in agdrs if a.status_class == "built"], key=_agdr_sort_key)
    planned = sorted([a for a in agdrs if a.status_class == "planned"], key=_agdr_sort_key)
    superseded = sorted([a for a in agdrs if a.status_class == "superseded"], key=_agdr_sort_key)
    unknown = sorted([a for a in agdrs if a.status_class == "unknown"], key=_agdr_sort_key)

    L: list[str] = []
    L.append("# What is built — generated map")
    L.append("")
    L.append("> **GENERATED — do not edit by hand.** Regenerate with "
             "`python tools/build_map.py`.")
    L.append("> Truth is DERIVED, not typed: AgDR status comes from each "
             "`docs/agdr/*.md` frontmatter;")
    L.append("> the verified-complete units come from the ROMA requirement "
             "tree's GREEN leaves")
    L.append("> (`personal_brain.requirement_tree`). The "
             "`docs/ROADMAP.md` remains the single roadmap;")
    L.append("> this file is a read-only projection of build state for "
             "fast scanning.")
    L.append("")
    L.append(f"_Generated {today} from {len(agdrs)} AgDR record(s)._")
    L.append("")

    L.append("## AgDR ledger — by build state")
    L.append("")
    L.append(f"- **Built (executed):** {len(built)}")
    L.append(f"- **Planned (proposed / plan-locked / executing):** {len(planned)}")
    L.append(f"- **Superseded:** {len(superseded)}")
    if unknown:
        L.append(f"- **Unclassified status:** {len(unknown)}")
    L.append("")

    def _table(title: str, rows: list[AgdrRecord]) -> None:
        if not rows:
            return
        L.append(f"### {title}")
        L.append("")
        L.append("| AgDR | Status | Title |")
        L.append("|---|---|---|")
        for r in rows:
            # collapse the status to its leading clause for table tidiness
            short_status = r.status.split("—")[0].split(" - ")[0].strip()[:48]
            safe_title = r.title.replace("|", "\\|")[:120]
            L.append(f"| {r.agdr_id} | {short_status} | {safe_title} |")
        L.append("")

    _table("Built", built)
    _table("Planned / in-flight", planned)
    _table("Superseded", superseded)
    _table("Unclassified", unknown)

    L.append("## Verified-complete units — requirement-tree GREEN leaves")
    L.append("")
    L.append(f"_Source: {leaf_note}._")
    L.append("")
    if green_leaves:
        L.append("| Vision (tree) | Verified leaf | Gate predicate |")
        L.append("|---|---|---|")
        for g in green_leaves:
            tt = g.tree_title.replace("|", "\\|")[:60]
            lt = g.leaf_title.replace("|", "\\|")[:80]
            pr = g.predicate.replace("|", "\\|")[:80]
            L.append(f"| {tt} | {lt} | {pr} |")
        L.append("")
    else:
        L.append("_No GREEN leaves available in this environment (the brain "
                 "store holds the live ROMA trees; a fresh clone / CI without "
                 "a brain DB has none). Run on the founder's machine with the "
                 "brain daemon up to populate this section._")
        L.append("")

    return "\n".join(L) + "\n"


def generate(today: Optional[str] = None) -> str:
    agdrs = scan_agdrs()
    green_leaves, note = scan_green_leaves()
    return render_map(agdrs, green_leaves, note, today=today)


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate docs/BUILT_MAP.md from "
                                             "derived AgDR + requirement-tree state.")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed map differs from a fresh "
                         "generation (CI staleness guard)")
    ap.add_argument("--stdout", action="store_true",
                    help="print the generated map instead of writing the file")
    # For --check determinism across days, allow pinning the date so a stale
    # check fails ONLY on content drift, not the timestamp line.
    ap.add_argument("--date", default=None,
                    help="override the generated-on date (ISO); used by --check")
    args = ap.parse_args(argv)

    if args.check:
        if not BUILT_MAP_PATH.exists():
            print("BUILT_MAP.md is missing — run `python tools/build_map.py`",
                  file=sys.stderr)
            return 1
        committed = BUILT_MAP_PATH.read_text(encoding="utf-8")
        # Pin date to the committed map's date so only CONTENT drift fails.
        m = re.search(r"_Generated (\d{4}-\d{2}-\d{2})", committed)
        pin = args.date or (m.group(1) if m else None)
        fresh = generate(today=pin)
        if committed != fresh:
            print("BUILT_MAP.md is STALE — regenerate with "
                  "`python tools/build_map.py`", file=sys.stderr)
            return 1
        print("BUILT_MAP.md is current.")
        return 0

    content = generate(today=args.date)
    if args.stdout:
        sys.stdout.write(content)
        return 0
    BUILT_MAP_PATH.write_text(content, encoding="utf-8")
    print(f"wrote {BUILT_MAP_PATH.relative_to(REPO_ROOT)} "
          f"({len(content.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
