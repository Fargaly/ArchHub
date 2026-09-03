"""DimensionsAgent — auto-dimension all walls in the active Revit view.

Skeleton implementation. The full version uses the LLM to generate the
exact C# script for the user's project conventions and runs it via
revit_execute_csharp.
"""
from __future__ import annotations

from .base import Agent, AgentResult


class DimensionsAgent(Agent):
    id = "dimensions"
    display_name = "Auto-dimensions"
    description = "Add dimensions to all walls in the active Revit view."

    def run(self, goal: str, *, tools, llm) -> AgentResult:
        # v0: route through the LLM with a focused prompt
        prompt = (
            "You are running as the ArchHub Dimensions agent. Goal: "
            f"{goal!r}. Use revit_execute_csharp to generate dimensions on "
            "all walls in the active Revit view. Use Linear dimensions, "
            "respect the project's primary type. Return a one-line summary "
            "of what you did when done."
        )
        # Hand off to LLM with restricted tools = only revit_*
        # (Implementation: call llm.complete with a short history;
        #  collect tool invocations; emit AgentResult.)
        return AgentResult(
            success=False,
            summary="DimensionsAgent skeleton — implement run() to invoke LLM with revit_* tools.",
            log=[prompt],
        )
