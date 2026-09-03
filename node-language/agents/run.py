"""Daemon entry point.

Run modes:

    python -m agents.run                # daemon — runs forever
    python -m agents.run --once         # one cycle, print results, exit
    python -m agents.run --enqueue file  # add tasks from a YAML file
    python -m agents.run --status       # print queue + last-run state

The daemon is safe to start and stop at any time. Outputs are
filesystem-backed so a crash loses no in-flight work — the half-
completed task gets re-claimed on next boot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .scheduler import Scheduler
from .queue import TaskQueue, Task, TASKS_DIR, OUTPUTS_DIR, LOGS_DIR
from .ollama import is_running, list_models
from .departments import DEPARTMENTS


def _print_status() -> None:
    print(f"Repo: {TASKS_DIR.parent.parent}")
    print(f"Tasks dir:   {TASKS_DIR}")
    print(f"Outputs dir: {OUTPUTS_DIR}")
    print(f"Logs dir:    {LOGS_DIR}")
    print()
    print(f"Ollama running: {is_running()}")
    if is_running():
        models = list_models()
        print(f"Models pulled ({len(models)}):")
        for m in models:
            print(f"  - {m}")
    print()
    print("Departments:")
    available = set(list_models())
    for name, cls in DEPARTMENTS.items():
        agent = cls()
        mark = "OK " if agent.model in available else "MISSING"
        print(f"  [{mark}] {name:6s}  model={agent.model}")
    print()

    q = TaskQueue()
    pending = q.list_pending()
    print(f"Pending tasks: {len(pending)}")
    for t in pending[:10]:
        print(f"  [{t.priority:3d}] {t.department:6s} {t.id}  {t.title}")
    if len(pending) > 10:
        print(f"  ... and {len(pending) - 10} more")


def _enqueue_from_file(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    q = TaskQueue()
    n = 0
    for entry in (data.get("tasks") or []):
        task = Task(
            id=entry["id"], department=entry["department"], title=entry["title"],
            instructions=entry["instructions"],
            priority=int(entry.get("priority", 50)),
            inputs=dict(entry.get("inputs") or {}),
        )
        q.add(task)
        n += 1
    print(f"Enqueued {n} tasks.")


def main(argv: list[str]) -> int:
    if "--status" in argv:
        _print_status()
        return 0

    if "--enqueue" in argv:
        i = argv.index("--enqueue")
        if i + 1 >= len(argv):
            print("Usage: --enqueue <path-to-yaml>")
            return 2
        _enqueue_from_file(Path(argv[i + 1]))
        return 0

    if not is_running():
        print("Ollama is not running on localhost:11434.")
        print("Start it (https://ollama.com) and try again.")
        return 1

    sched = Scheduler()
    if "--once" in argv:
        summary = sched.tick()
        print(json.dumps(summary, indent=2))
        return 0

    cycle = 300
    if "--cycle" in argv:
        i = argv.index("--cycle")
        cycle = int(argv[i + 1])
    sched.run_forever(cycle_seconds=cycle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
