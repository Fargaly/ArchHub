"""File-backed task queue for departments.

Tasks are YAML files under `agents/tasks/<dept>/<id>.yaml`. The
dispatcher reads them, marks them in-progress by writing a sibling
`<id>.lock` file, and on completion writes `<id>.done` plus the actual
output under `agents/outputs/<dept>/<id>/`.

File-on-disk queue keeps the system resilient across crashes / reboots
and trivially auditable — every task and its outcome lives in the repo
as plain text.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "agents" / "tasks"
OUTPUTS_DIR = REPO_ROOT / "agents" / "outputs"
LOGS_DIR = REPO_ROOT / "agents" / "logs"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    department: str
    title: str
    instructions: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    priority: int = 50          # 0 = highest, 100 = lowest
    recurring_cron: Optional[str] = None    # if set, dispatcher re-creates after run
    inputs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "Task":
        return Task(
            id=d["id"], department=d["department"], title=d["title"],
            instructions=d["instructions"],
            created_at=d.get("created_at") or datetime.now(timezone.utc).isoformat(),
            priority=int(d.get("priority", 50)),
            recurring_cron=d.get("recurring_cron"),
            inputs=dict(d.get("inputs") or {}),
            status=TaskStatus(d.get("status", "pending")),
        )


class TaskQueue:
    """Find pending tasks, lock + claim them for a worker, mark done/failed.

    Storage layout:
        agents/tasks/<dept>/<id>.yaml          — task definition
        agents/tasks/<dept>/<id>.lock          — exists while running
        agents/tasks/<dept>/<id>.done          — exists after success
        agents/tasks/<dept>/<id>.failed        — exists after failure
        agents/outputs/<dept>/<id>/...         — agent's produced files
    """

    def __init__(self, root: Path = TASKS_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def add(self, task: Task) -> Path:
        dept_dir = self.root / task.department
        dept_dir.mkdir(parents=True, exist_ok=True)
        path = dept_dir / f"{task.id}.yaml"
        path.write_text(_yaml_dump(task.to_dict()), encoding="utf-8")
        return path

    def list_pending(self, department: Optional[str] = None) -> list[Task]:
        out: list[Task] = []
        depts = [department] if department else [
            p.name for p in self.root.iterdir() if p.is_dir()
        ]
        for dept in depts:
            d = self.root / dept
            if not d.exists():
                continue
            for f in sorted(d.glob("*.yaml")):
                stem = f.stem
                if (d / f"{stem}.lock").exists() or (d / f"{stem}.done").exists():
                    continue
                if (d / f"{stem}.failed").exists():
                    continue
                try:
                    task = Task.from_dict(_yaml_load(f.read_text(encoding="utf-8")))
                    if task.status == TaskStatus.PENDING:
                        out.append(task)
                except Exception:
                    continue
        out.sort(key=lambda t: t.priority)
        return out

    def claim(self, task: Task) -> bool:
        """Atomically mark a task running by creating its lock file. Returns
        False if another dispatcher claimed it first."""
        lock = self.root / task.department / f"{task.id}.lock"
        try:
            # exclusive create — fails if exists
            lock.touch(exist_ok=False)
        except FileExistsError:
            return False
        return True

    def mark_done(self, task: Task, summary: str) -> None:
        d = self.root / task.department
        (d / f"{task.id}.done").write_text(
            _yaml_dump({"id": task.id, "summary": summary,
                        "finished_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        try:
            (d / f"{task.id}.lock").unlink(missing_ok=True)
        except Exception:
            pass

    def mark_failed(self, task: Task, error: str) -> None:
        d = self.root / task.department
        (d / f"{task.id}.failed").write_text(
            _yaml_dump({"id": task.id, "error": error,
                        "failed_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        try:
            (d / f"{task.id}.lock").unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tiny YAML-ish dump/load. Avoids a PyYAML dependency for the agents
# package. The format is JSON masquerading as YAML — every YAML parser
# handles it, and so does json.loads, so we get free portability.
def _yaml_dump(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _yaml_load(text: str) -> dict:
    return json.loads(text)
