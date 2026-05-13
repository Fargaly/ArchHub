"""ArchHub Departments — local Ollama agents acting as a real company.

A small team of role-scoped agents that runs locally on the user's
Ollama install (no Claude tokens, no cloud spend) and chips away at
ArchHub's backlog continuously: R&D notes, QA test cases, doc
maintenance, ops triage. Each "department" is a Python class wrapping
one Ollama model with a tightly-scoped system prompt, a read-only file
toolset, and an output sink at `agents/outputs/<dept>/<task-id>/`.

Safety contract (do NOT relax without explicit human review):

  * Outputs land in `agents/outputs/`, never in `app/` or `cloud_backend/`.
  * Branches are prefixed `auto/<dept>/<task-id>`. Never to `main`.
  * Pushes are off by default; any push needs `ARCHHUB_AUTO_PUSH=1`.
  * Every Ollama call is logged to `agents/logs/<dept>-YYYYMMDD.log`.
  * No agent has shell-exec or arbitrary-write access. Tools are an
    explicit allow-list per department.
"""
from .base import Agent, AgentResult
from .ollama import OllamaCompletion, list_models
from .queue import TaskQueue, Task, TaskStatus
from .dispatcher import Dispatcher
from .scheduler import Scheduler

__all__ = [
    "Agent", "AgentResult",
    "OllamaCompletion", "list_models",
    "TaskQueue", "Task", "TaskStatus",
    "Dispatcher",
    "Scheduler",
]
