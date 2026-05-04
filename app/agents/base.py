"""Agents — autonomous task runners.

An Agent is a higher-level abstraction than a single tool call. It receives
a goal and orchestrates multiple tool calls (and optionally LLM reasoning)
to achieve it. Examples to come:

  - DimensionsAgent        — auto-dimension a Revit view
  - AnnotationsAgent       — apply room name tags, ceiling heights
  - ParametersAgent        — create shared parameters from a CSV
  - DataMappingAgent       — map element parameters into Speckle data
                             schemas, push for analytics

This is the v0 scaffold. Each agent provides:
  - id, display_name, description
  - run(goal, tools, llm) → AgentResult

Agents are pluggable: drop a new file in app/agents/, register in
agents/__init__.py, and they appear in the chat as `/agent <id>` slash
commands or via the command palette.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    success: bool
    summary: str
    artifacts: list[Any] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


class Agent(ABC):
    id: str = ""
    display_name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, goal: str, *, tools, llm) -> AgentResult: ...


# Registry filled by agents/__init__.py
REGISTRY: dict[str, Agent] = {}
