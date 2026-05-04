"""Workflow library — save/load workflows from disk.

Workflows live in %LOCALAPPDATA%/ArchHub/workflows/<id>.archhub-workflow.json.
The library indexes them by id and provides simple list/get/save/delete.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .graph import Workflow

WORKFLOWS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "workflows"
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

_FILE_SUFFIX = ".archhub-workflow.json"
_SAFE = re.compile(r"[^a-zA-Z0-9_\- ]+")


def _slug(name: str) -> str:
    return _SAFE.sub("-", (name or "untitled")).strip("- ").lower() or "untitled"


def _path_for(workflow: Workflow) -> Path:
    return WORKFLOWS_DIR / f"{_slug(workflow.name)}__{workflow.id}{_FILE_SUFFIX}"


# ---------------------------------------------------------------------------
def save_workflow(workflow: Workflow) -> Path:
    workflow.updated_at = datetime.utcnow().isoformat()
    path = _path_for(workflow)
    path.write_text(workflow.to_json(), encoding="utf-8")
    return path


def load_workflow(path: Path) -> Workflow:
    return Workflow.from_json(Path(path).read_text(encoding="utf-8"))


def list_workflows() -> list[dict]:
    """Return a lightweight index for the UI: id, name, description, path, updated_at."""
    items: list[dict] = []
    for f in sorted(WORKFLOWS_DIR.glob(f"*{_FILE_SUFFIX}"),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "id": data.get("id"),
                "name": data.get("name"),
                "description": data.get("description", ""),
                "path": str(f),
                "updated_at": data.get("updated_at"),
                "node_count": len(data.get("nodes") or []),
                "trigger_types": [t.get("type") for t in (data.get("triggers") or [])],
            })
        except Exception:
            continue
    return items


def get_workflow(workflow_id: str) -> Optional[Workflow]:
    for item in list_workflows():
        if item["id"] == workflow_id:
            return load_workflow(Path(item["path"]))
    return None


def delete_workflow(workflow_id: str) -> bool:
    for item in list_workflows():
        if item["id"] == workflow_id:
            Path(item["path"]).unlink(missing_ok=True)
            return True
    return False
