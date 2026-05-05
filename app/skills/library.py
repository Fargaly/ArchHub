"""Skill library — discover, save, delete skills across local + shared paths.

Two paths searched, in order:
  - User library:   %LOCALAPPDATA%/ArchHub/workflows/      (per user)
  - Shared library: %PROGRAMDATA%/ArchHub/skills/          (firm-wide, optional)

Shared path is opt-in: created on first save with scope='team' or 'firm'.
Sync mechanism (Git, Speckle, network drive) is delegated to whatever owns
%PROGRAMDATA%/ArchHub/skills/. v0.7 = local-only; pick mechanism in v0.8.

Returns Workflow objects but only those whose metadata makes them a Skill
(intent non-empty). Use workflows.library for raw workflow listing.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from workflows.graph import Workflow
from workflows.library import WORKFLOWS_DIR as USER_LIBRARY, _FILE_SUFFIX, _slug

from .metadata import SkillMeta, attach_meta, get_meta, is_skill, SCOPE_USER, SCOPE_FIRM, SCOPE_TEAM


SHARED_LIBRARY = Path(
    os.environ.get("PROGRAMDATA", os.environ.get("LOCALAPPDATA", str(Path.home())))
) / "ArchHub" / "skills"


def library_paths() -> list[Path]:
    """Library roots in priority order. User overrides shared on collision."""
    return [USER_LIBRARY, SHARED_LIBRARY]


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path_for(workflow: Workflow, root: Path) -> Path:
    return _ensure(root) / f"{_slug(workflow.name)}__{workflow.id}{_FILE_SUFFIX}"


def list_skills() -> list[dict]:
    """Index every Skill across libraries. Lightweight: name + meta + path."""
    seen_ids: set[str] = set()
    out: list[dict] = []
    for root in library_paths():
        if not root.exists():
            continue
        for f in sorted(root.glob(f"*{_FILE_SUFFIX}"),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                wf = Workflow.from_json(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not is_skill(wf):
                continue
            if wf.id in seen_ids:
                continue
            seen_ids.add(wf.id)
            meta = get_meta(wf)
            out.append({
                "id": wf.id,
                "name": wf.name,
                "intent": meta.intent if meta else "",
                "keywords": meta.keywords if meta else [],
                "when_to_use": meta.when_to_use if meta else "",
                "examples": meta.examples if meta else [],
                "tags": meta.tags if meta else [],
                "requires": meta.requires if meta else [],
                "scope": meta.scope if meta else SCOPE_USER,
                "author": meta.author if meta else "",
                "path": str(f),
                "library": "shared" if root == SHARED_LIBRARY else "user",
                "node_count": len(wf.nodes),
                "updated_at": wf.updated_at,
            })
    return out


def load_skill(skill_id: str) -> Optional[Workflow]:
    for item in list_skills():
        if item["id"] == skill_id:
            return Workflow.load(Path(item["path"]))
    return None


def save_skill(workflow: Workflow, meta: Optional[SkillMeta] = None) -> Path:
    """Save a workflow as a Skill. Routes by scope to user or shared library."""
    if meta is not None:
        attach_meta(workflow, meta)
    workflow.updated_at = datetime.now(timezone.utc).isoformat()
    cur_meta = get_meta(workflow)
    scope = cur_meta.scope if cur_meta else SCOPE_USER
    root = SHARED_LIBRARY if scope in (SCOPE_TEAM, SCOPE_FIRM) else USER_LIBRARY
    path = _path_for(workflow, root)
    path.write_text(workflow.to_json(), encoding="utf-8")
    return path


def delete_skill(skill_id: str) -> bool:
    for item in list_skills():
        if item["id"] == skill_id:
            Path(item["path"]).unlink(missing_ok=True)
            return True
    return False
