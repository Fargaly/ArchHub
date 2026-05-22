"""ArchHub Departments — autonomous workforce, local or cloud.

A small team of role-scoped agents that chips away at ArchHub's
backlog continuously: R&D notes, QA test cases, doc maintenance, ops
triage. Each "department" is a Python class wrapping one model with a
tightly-scoped system prompt, a read-only file toolset, and an output
sink at `agents/outputs/<dept>/<task-id>/`.

Two run modes:

  * **Local** — `python -m agents.run`. Uses Ollama on
    `localhost:11434`. No cloud spend, requires Ollama installed.
  * **Cloud** — `python -m agents.cloud_runner` (containerised on
    Fly.io as `archhub-agents`). Uses Anthropic's API with a Haiku
    default; see `agents/CLOUD_DEPLOY.md` for the deploy walkthrough.
    The backend is selected by `ARCHHUB_AGENTS_BACKEND=anthropic|ollama`.

Safety contract (do NOT relax without explicit human review):

  * Outputs land in `agents/outputs/`, never in `app/` or `cloud_backend/`.
  * Branches are prefixed `auto/<dept>/<task-id>`. Never to `main`.
  * Pushes are off by default; any push needs `ARCHHUB_AUTO_PUSH=1`.
  * Every LLM call is logged to `agents/logs/<dept>-YYYYMMDD.log`.
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
