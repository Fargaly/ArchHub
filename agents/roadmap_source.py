"""Roadmap source — multi-input ingestion of pending items.

Reads roadmap signals from several sources, deduplicates by id (stable
hash of title), and returns a list of pending RoadmapItem objects.

Sources (best-effort; any failure is logged + skipped):

  1. `docs/ROADMAP.md`         — primary curated backlog
  2. `CHANGELOG.md`            — "Roadmap" sections, "Limitations" sections
  3. GitHub issues             — `gh issue list --label roadmap --json …`
  4. Open pull requests        — `gh pr list --state open --draft …`
                                  scanned for `- [ ]` TODO items in body
  5. Source-tree comments      — `# ROADMAP:` prefixed TODO/FIXME in
                                  `app/main.py` (configurable glob)

Each item carries:

  - `id`           stable 12-char hash of source+title
  - `title`        one-line summary (the markdown bullet text)
  - `body`         optional extended description (for issue / PR sources)
  - `source`       one of "roadmap_md" / "changelog" / "github_issue"
                   / "github_pr" / "source_comment"
  - `priority`     "high" / "med" / "low" — extracted from `#P0` /
                   `#P1` / `#P2` tags (high / med / low respectively).
                   Defaults to "med" when no tag present.
  - `suggested_dept`  "eng" / "qa" / "docs" / "ops" / "rnd". Parsed
                      from a trailing `(dept)` annotation, or guessed
                      from keywords if absent.

No new network deps — `gh` runs via stdlib `subprocess`. If `gh` is
missing or unauthenticated, that source returns `[]` and the loop
continues.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
ROADMAP_PATH = REPO_ROOT / "docs" / "ROADMAP.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
SOURCE_COMMENT_GLOBS = ["app/main.py"]


# Markers we recognise inside markdown bullets.
_PRIORITY_TAGS = {"#P0": "high", "#P1": "med", "#P2": "low"}
_DEPT_KEYWORDS = {
    "eng":  ("frontend", "backend", "api", "endpoint", "fix", "wire",
             "implement", "ui", "desktop"),
    "docs": ("doc", "trust center", "email", "newsletter", "page", "template"),
    "ops":  ("release", "deploy", "icns", "appimage", "artifact",
             "dashboard", "monitor", "audit"),
    "rnd":  ("connector", "research", "evaluate", "experiment", "civil 3d"),
    "qa":   ("test", "regression", "coverage", "smoke"),
}


@dataclass(frozen=True)
class RoadmapItem:
    id: str
    title: str
    body: str
    source: str
    priority: str          # "high" | "med" | "low"
    suggested_dept: str    # "eng" | "qa" | "docs" | "ops" | "rnd"

    def priority_rank(self) -> int:
        return {"high": 0, "med": 50, "low": 90}.get(self.priority, 50)


# ---------------------------------------------------------------------------
# Helpers
def _stable_id(source: str, title: str) -> str:
    """12-char hex hash of source+title. Same item across runs → same id."""
    blob = f"{source}::{title.strip().lower()}".encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


def _extract_priority(text: str) -> str:
    for tag, prio in _PRIORITY_TAGS.items():
        if tag in text:
            return prio
    return "med"


def _extract_dept(text: str, default: str = "eng") -> str:
    """Parse `(dept)` annotation; fall back to keyword guess; else default."""
    m = re.search(r"\(\s*(eng|qa|docs|ops|rnd)\s*\)\s*$", text.strip(),
                  re.IGNORECASE)
    if m:
        return m.group(1).lower()
    lower = text.lower()
    for dept, kws in _DEPT_KEYWORDS.items():
        if any(k in lower for k in kws):
            return dept
    return default


def _clean_title(line: str) -> str:
    """Strip `- [ ]`, `#P0` tags, `(dept)` annotation. Return display title."""
    s = line.strip()
    s = re.sub(r"^\-\s*\[\s*\]\s*", "", s)
    s = re.sub(r"#P[012]\b", "", s)
    s = re.sub(r"\(\s*(eng|qa|docs|ops|rnd)\s*\)\s*$", "", s,
               flags=re.IGNORECASE)
    return s.strip(" -—:")


# ---------------------------------------------------------------------------
# Source 1 — docs/ROADMAP.md
def _read_roadmap_md(path: Optional[Path] = None) -> list[RoadmapItem]:
    """Pull every `- [ ]` line from the roadmap markdown."""
    if path is None:
        path = ROADMAP_PATH
    if not path.exists():
        return []
    out: list[RoadmapItem] = []
    in_done_section = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            in_done_section = "done" in line.lower()
            continue
        if in_done_section:
            continue
        if not line.lstrip().startswith("- [ ]"):
            continue
        title = _clean_title(line)
        if not title:
            continue
        item = RoadmapItem(
            id=_stable_id("roadmap_md", title),
            title=title,
            body="",
            source="roadmap_md",
            priority=_extract_priority(line),
            suggested_dept=_extract_dept(line),
        )
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Source 2 — CHANGELOG.md "Roadmap" / "Limitations" sections
def _read_changelog(path: Optional[Path] = None) -> list[RoadmapItem]:
    """Pull bullets from sections titled Roadmap / Limitations / Phase 2."""
    if path is None:
        path = CHANGELOG_PATH
    if not path.exists():
        return []
    out: list[RoadmapItem] = []
    in_target = False
    section_kind = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.lstrip("# ").strip().lower()
        if line.startswith("##") or line.startswith("###"):
            in_target = any(
                k in stripped
                for k in ("roadmap", "limitations", "phase 2",
                          "follow-ups", "follow ups")
            )
            section_kind = stripped if in_target else ""
            continue
        if not in_target:
            continue
        if not line.lstrip().startswith("- "):
            continue
        title = _clean_title(line.lstrip("- "))
        # Skip empty bullets and bullets that are clearly meta-narrative
        # ("see X.md is the playbook…") — keep only actionable items.
        if not title or len(title) < 8:
            continue
        item = RoadmapItem(
            id=_stable_id("changelog", title),
            title=title[:140],
            body=section_kind,
            source="changelog",
            priority=_extract_priority(line),
            suggested_dept=_extract_dept(line),
        )
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Source 3 — GitHub issues labelled "roadmap"
def _read_github_issues() -> list[RoadmapItem]:
    """Run `gh issue list --label roadmap`. Empty list on any failure."""
    try:
        proc = subprocess.run(
            ["gh", "issue", "list", "--label", "roadmap", "--state", "open",
             "--json", "number,title,body", "--limit", "100"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except Exception:
        return []
    out: list[RoadmapItem] = []
    for entry in data:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        body = (entry.get("body") or "")[:600]
        merged = f"{title}\n{body}"
        out.append(RoadmapItem(
            id=_stable_id(f"github_issue#{entry.get('number')}", title),
            title=title[:140],
            body=body,
            source="github_issue",
            priority=_extract_priority(merged),
            suggested_dept=_extract_dept(merged),
        ))
    return out


# ---------------------------------------------------------------------------
# Source 4 — Open PRs in draft / WIP. Their body checklists count as
# in-flight roadmap items.
_TODO_BULLET = re.compile(r"^\s*-\s*\[\s*\]\s*(.+)$")


def _read_github_prs() -> list[RoadmapItem]:
    """Scan open draft PRs for unchecked checklist items."""
    try:
        proc = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--draft",
             "--json", "number,title,body", "--limit", "50"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except Exception:
        return []
    out: list[RoadmapItem] = []
    for entry in data:
        pr_num = entry.get("number")
        for line in (entry.get("body") or "").splitlines():
            m = _TODO_BULLET.match(line)
            if not m:
                continue
            title = m.group(1).strip()
            if len(title) < 6:
                continue
            out.append(RoadmapItem(
                id=_stable_id(f"github_pr#{pr_num}", title),
                title=title[:140],
                body=f"From PR #{pr_num}: {entry.get('title', '')}",
                source="github_pr",
                priority=_extract_priority(line),
                suggested_dept=_extract_dept(line),
            ))
    return out


# ---------------------------------------------------------------------------
# Source 5 — `# ROADMAP:` comments inside source files
_SOURCE_TAG = re.compile(
    r"#\s*(?:TODO|FIXME)?\s*ROADMAP:\s*(.+?)$",
    re.IGNORECASE,
)


def _read_source_comments() -> list[RoadmapItem]:
    """Grep `# ROADMAP:` prefixed lines in the configured globs."""
    out: list[RoadmapItem] = []
    for glob in SOURCE_COMMENT_GLOBS:
        for path in REPO_ROOT.glob(glob):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for raw in text.splitlines():
                m = _SOURCE_TAG.search(raw)
                if not m:
                    continue
                title = m.group(1).strip()
                if not title:
                    continue
                out.append(RoadmapItem(
                    id=_stable_id(f"source::{path.name}", title),
                    title=title[:140],
                    body=f"In {path.relative_to(REPO_ROOT)}",
                    source="source_comment",
                    priority=_extract_priority(raw),
                    suggested_dept=_extract_dept(raw),
                ))
    return out


# Sentinel — pass this to `fetch_pending` to skip the completed-id
# filter entirely (used by the dispatcher so it can count "skipped
# because already done" itself).
class _Unfiltered:
    pass


UNFILTERED = _Unfiltered()


# ---------------------------------------------------------------------------
def fetch_pending(
    *,
    include_github: bool = True,
    state_path=None,
) -> list[RoadmapItem]:
    """All sources merged, deduplicated by id, sorted by priority.

    Items whose id appears in `state_path` (one id per line) are
    filtered out — they're already completed. Pass
    `state_path=UNFILTERED` to skip filtering entirely (the dispatcher
    does this so it can count completed-skips for telemetry).
    """
    items: list[RoadmapItem] = []
    items.extend(_read_roadmap_md())
    items.extend(_read_changelog())
    items.extend(_read_source_comments())
    if include_github:
        items.extend(_read_github_issues())
        items.extend(_read_github_prs())

    if isinstance(state_path, _Unfiltered):
        completed: set[str] = set()
    else:
        completed = _load_completed_ids(state_path)
    seen: set[str] = set()
    deduped: list[RoadmapItem] = []
    for it in items:
        if it.id in completed or it.id in seen:
            continue
        seen.add(it.id)
        deduped.append(it)

    deduped.sort(key=lambda x: (x.priority_rank(), x.title.lower()))
    return deduped


def _load_completed_ids(path: Optional[Path]) -> set[str]:
    if path is None:
        from .roadmap_dispatcher import COMPLETED_IDS_PATH
        path = COMPLETED_IDS_PATH
    if not path or not path.exists():
        return set()
    try:
        return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")}
    except Exception:
        return set()
