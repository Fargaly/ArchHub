#!/usr/bin/env python3
"""doc_freshness.py — Track C CI script (Content Ecosystem section 4).

Walks the docs corpus — top-level `docs/*.md` PLUS the decision/record
subtrees that carry their own machine-checkable `## Artifacts` paths
(`docs/agdr/`, `docs/adr/`, `docs/status/`, `docs/research/`) — and:

  1. Writes `docs/_meta/index.json` — TOC with
     {slug, title, path, word_count, mtime, deps: [...], missing_deps: [...]}
     per doc.
  2. Writes `docs/_meta/freshness.json` — per-doc
     {slug, path, stale: bool, reason, last_check_iso}.

`stale` is True when at least one of the doc's Artifacts (per AgDR
template `## Artifacts` section, also generalised to docs that mention
`app/...py` paths) has been touched in git after the doc's own mtime.
The 54 AgDRs each carry an `## Artifacts` section — they are exactly
the highest-value freshness targets, so they are indexed and checked,
not skipped (DOC-11). Honest mode (per ANTI-LIE): if `git` isn't on
PATH or this isn't a git checkout, every doc reports `stale=False`
with `reason="git unavailable — no commit timeline"`.

`deps` lists ONLY dependencies that resolve to something real: a
`docs/*.md` dep is emitted only when that file exists on disk; any
referenced-but-missing doc is surfaced (not silently dropped) in the
separate `missing_deps` field (DOC-12). A generated TOC must not carry
dangling graph edges — the same rule the brain-graph twin already
applies (`app/memory/extractors/docs.py` only lands doc→doc edges to
docs that exist).

Usage:
    python tools/doc_freshness.py            # writes both files
    python tools/doc_freshness.py --check    # exit 1 if any stale

Brain-side: this script is the JSON twin of
`app/memory/extractors/docs.py` (which writes the same data into the
MemoryGraph). The pair lets website/CI consume freshness without
loading the brain DB.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── locating the docs dir + meta dir ──────────────────────────────────


def _repo_root() -> Path:
    """tools/doc_freshness.py → repo root is parent of `tools/`."""
    return Path(__file__).resolve().parents[1]


# Subtrees under `docs/` that carry their own decision/record markdown
# (each with a machine-checkable `## Artifacts` section or a dated body).
# These are indexed + freshness-checked IN ADDITION to top-level
# `docs/*.md`. Deliberately NOT a blind recursive walk: `docs/prototypes`,
# `docs/mockups`, `docs/archive`, `docs/_templates` hold HTML/fossils that
# are not freshness-bearing decision records, so they stay out of the TOC.
# DOC-11: the 54 AgDRs + 3 ADRs + status/ + research/ used to be invisible
# to the engine even though AgDRs carry the very `## Artifacts` paths it was
# built to consume.
INDEXED_SUBDIRS: tuple[str, ...] = ("agdr", "adr", "status", "research")


def _iter_doc_files(docs_dir: Path) -> list[Path]:
    """Every markdown file the index covers, in deterministic order:
    top-level `docs/*.md` first, then each INDEXED_SUBDIRS tree
    (sorted). `docs/_meta` is never included (it's our own output)."""
    files: list[Path] = []
    files.extend(sorted(p for p in docs_dir.glob("*.md") if p.is_file()))
    for sub in INDEXED_SUBDIRS:
        subdir = docs_dir / sub
        if subdir.is_dir():
            files.extend(sorted(p for p in subdir.glob("*.md") if p.is_file()))
    return files


def _slug_for(p: Path, docs_dir: Path) -> str:
    """Unique slug for a doc. Top-level docs keep the bare stem (back-compat
    with the brain twin + existing freshness.json). Subtree docs are
    namespaced by their relative dir (`agdr/AgDR-0001-…`) so two files with
    the same stem in different trees never collide."""
    rel = p.relative_to(docs_dir)
    if rel.parent == Path("."):
        return p.stem
    return f"{rel.parent.as_posix()}/{p.stem}"


# ── markdown parsing (no PyYAML / no markdown deps) ───────────────────


_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_APP_PATH_RE = re.compile(r"app/[A-Za-z0-9_./\-]+\.py")
_ARTIFACTS_SECTION_RE = re.compile(
    r"^##\s*Artifacts\s*$(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_AGDR_REF_RE = re.compile(r"AgDR-(\d{4})")
_DOC_REF_RE = re.compile(r"docs/([A-Za-z0-9_./\-]+)\.md")


def _title_of(text: str, fallback: str) -> str:
    m = _H1_RE.search(text)
    return m.group(1).strip() if m else fallback


def _word_count(text: str) -> int:
    return len(text.split())


def _artifacts_paths(text: str) -> list[str]:
    """Code-path artefacts mentioned anywhere in the doc.

    Two sources merged:
      a) explicit `## Artifacts` section bullets (AgDR convention)
      b) top-level docs that don't use that header — any `app/*.py`
         reference is treated as an artefact candidate.
    """
    paths: set[str] = set()
    # (a) Artifacts section
    for m in _ARTIFACTS_SECTION_RE.finditer(text):
        for p in _APP_PATH_RE.findall(m.group(1)):
            paths.add(p)
    # (b) inline mentions throughout the doc body
    for p in _APP_PATH_RE.findall(text):
        paths.add(p)
    return sorted(paths)


def _doc_md_refs(text: str) -> set[str]:
    """Every top-level `docs/X.md` reference in the body (subdir refs
    like `docs/agdr/…` are excluded — those are tracked as AgDR/ADR ids).

    Returned RAW (un-resolved) so the caller can split them into deps
    that exist vs `missing_deps` that don't (DOC-12)."""
    out: set[str] = set()
    for m in _DOC_REF_RE.finditer(text):
        body = m.group(1)
        if "/" in body:
            continue
        out.add(f"docs/{body}.md")
    return out


def _non_doc_deps(text: str) -> set[str]:
    """Dependencies that are not `docs/*.md` files — artefact code paths
    (e.g. `app/bridge.py`) and AgDR ids (`AgDR-0042`). These are not
    on-disk *docs*, so they are never subject to the doc-existence
    filter; they always belong in `deps`."""
    deps: set[str] = set(_artifacts_paths(text))
    for m in _AGDR_REF_RE.finditer(text):
        deps.add(f"AgDR-{m.group(1)}")
    return deps


def _resolve_doc_deps(
    text: str, repo_root: Path
) -> tuple[list[str], list[str]]:
    """Split the doc's declared dependencies into:

      deps         — artefact paths + AgDR ids + `docs/*.md` that EXIST,
      missing_deps — `docs/*.md` references whose file is absent on disk.

    A generated TOC must not assert a dependency edge to a file that
    isn't there (DOC-12) — but the broken reference is recorded, not
    hidden, so the citing doc can be corrected."""
    deps: set[str] = _non_doc_deps(text)
    missing: set[str] = set()
    for ref in _doc_md_refs(text):
        if (repo_root / ref).is_file():
            deps.add(ref)
        else:
            missing.add(ref)
    return sorted(deps), sorted(missing)


# ── git helpers ───────────────────────────────────────────────────────


def _git_available(repo_root: Path) -> bool:
    if shutil.which("git") is None:
        return False
    # Are we inside a git repo? Per the env probe, ArchHub is reported
    # NOT a git repo here. The honest path: skip git calls entirely if
    # the .git dir is missing.
    return (repo_root / ".git").exists()


def _git_log_since(repo_root: Path, since_ts: int, path: str) -> list[str]:
    """Return commit SHAs that touched `path` since unix `since_ts`.
    Returns [] on any failure."""
    since_iso = datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat()
    try:
        out = subprocess.run(
            ["git", "log",
             f"--since={since_iso}",
             "--pretty=format:%H",
             "--",
             path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


# ── main pipeline ─────────────────────────────────────────────────────


def build_index_and_freshness(
    repo_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (index_entries, freshness_entries) for the docs corpus
    (top-level + INDEXED_SUBDIRS). Pure function — no side effects."""
    if repo_root is None:
        repo_root = _repo_root()
    docs_dir = repo_root / "docs"
    git_ok = _git_available(repo_root)
    now_iso = datetime.now(timezone.utc).isoformat()

    index: list[dict[str, Any]] = []
    freshness: list[dict[str, Any]] = []

    for p in _iter_doc_files(docs_dir):
        slug = _slug_for(p, docs_dir)
        rel_path = "docs/" + p.relative_to(docs_dir).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        try:
            mtime = int(p.stat().st_mtime)
        except OSError:
            mtime = 0

        title = _title_of(text, slug)
        deps, missing_deps = _resolve_doc_deps(text, repo_root)
        artefacts = _artifacts_paths(text)

        index.append({
            "slug": slug,
            "title": title,
            "path": rel_path,
            "word_count": _word_count(text),
            "mtime": mtime,
            "deps": deps,
            "missing_deps": missing_deps,
        })

        stale = False
        reason = "fresh"
        if not git_ok:
            reason = "git unavailable — no commit timeline"
        else:
            stale_artefacts: list[str] = []
            for art in artefacts:
                shas = _git_log_since(repo_root, mtime, art)
                if shas:
                    stale_artefacts.append(art)
            if stale_artefacts:
                stale = True
                reason = (
                    "artefacts changed after doc mtime: "
                    + ", ".join(stale_artefacts[:5])
                    + (" ..." if len(stale_artefacts) > 5 else "")
                )
        freshness.append({
            "slug": slug,
            "path": rel_path,
            "stale": stale,
            "reason": reason,
            "last_check_iso": now_iso,
        })

    return index, freshness


def write_meta(repo_root: Path | None = None) -> dict[str, Any]:
    """Write both meta JSONs. Returns {index_count, stale_count}."""
    if repo_root is None:
        repo_root = _repo_root()
    meta_dir = repo_root / "docs" / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index, freshness = build_index_and_freshness(repo_root)
    (meta_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (meta_dir / "freshness.json").write_text(
        json.dumps(freshness, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "index_count": len(index),
        "stale_count": sum(1 for f in freshness if f.get("stale")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if any doc is stale (CI gate).",
    )
    parser.add_argument(
        "--repo-root", type=Path, default=None,
        help="Override repo root (defaults to two parents up from this script).",
    )
    args = parser.parse_args(argv)

    result = write_meta(args.repo_root)
    print(
        f"[doc_freshness] wrote index.json ({result['index_count']} docs) "
        f"+ freshness.json ({result['stale_count']} stale)"
    )
    if args.check and result["stale_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
