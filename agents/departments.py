"""Five departments. Each is a thin Agent subclass.

These are tightly-scoped roles. The system prompt defines the boundary
the model is expected to operate within. The dispatcher will not run a
task whose `department` doesn't match a registered Agent here.

Departments are deliberately narrow: docs writers don't get to edit
code; QA writes test specs not implementations; R&D produces notes not
PRs. That makes the daemon predictable and auditable.
"""
from __future__ import annotations

from pathlib import Path

from .base import Agent
from .ollama import OllamaCompletion
from .queue import Task


# ---------------------------------------------------------------------------
class DocsAgent(Agent):
    name = "docs"
    model = "llama3.1:latest"
    system_prompt = (
        "You are the Docs department of ArchHub. Your job is to keep the "
        "user-facing markdown documentation accurate, clear, and short. "
        "You produce Markdown only. You never invent product features. "
        "When you don't know a detail from the context provided, you write "
        "'TODO: confirm with engineering' and move on. You never edit code "
        "files. Output one clean Markdown document with the requested "
        "structure. No preamble, no apology, no 'as an AI'. Match the "
        "voice of the existing repo: terse, fragments OK, no marketing "
        "fluff."
    )
    readable_globs = [
        "*.md", "docs/**/*.md", "QUICKSTART.md", "STRATEGY.md",
        "DEVELOPMENT_LOG.md", "VISION.md", "VERSION",
    ]


class QAAgent(Agent):
    name = "qa"
    model = "deepseek-r1:8b"
    # Reasoning models do a long internal chain-of-thought before
    # emitting the final answer. 600s is too tight for deepseek-r1
    # on a typical workstation; 30 minutes is a safe ceiling for
    # unattended runs and well under the 1-hour cycle lower bound.
    timeout_seconds = 1800
    system_prompt = (
        "You are the QA department of ArchHub. You produce test plans, "
        "edge cases, and pytest-style test specs (NOT implementations) "
        "for shipped features. You read the source you're given and "
        "produce a Markdown report with the structure: Summary · "
        "Boundary cases · Failure modes · Suggested tests (one bullet "
        "per test, names + intent only). Be exhaustive about edge cases "
        "and concrete about failure modes — this is the highest-value "
        "QA output. Never write actual test code in this report."
    )
    readable_globs = [
        "app/**/*.py", "tests/**/*.py", "docs/**/*.md", "QUICKSTART.md",
    ]


class RnDAgent(Agent):
    name = "rnd"
    model = "qwen2.5-coder:7b"
    system_prompt = (
        "You are the R&D department of ArchHub. Your job is to research "
        "technical options, evaluate tradeoffs, and produce decision "
        "memos in Markdown. Each memo follows this structure: "
        "1. Problem · 2. Options (with pros/cons) · 3. Recommendation · "
        "4. Risks · 5. Effort estimate. You evaluate libraries, APIs, "
        "and architectural choices. You do NOT write production code; "
        "you produce decision memos that engineers act on. Be specific "
        "about versions, license terms, maintenance signals, and known "
        "issues. Cite the basis for each claim ('per their docs', "
        "'per release notes')."
    )
    readable_globs = [
        "app/**/*.py", "relay/**/*.ts", "docs/**/*.md",
        "STRATEGY.md", "DEVELOPMENT_LOG.md", "VISION.md",
    ]


class EngAgent(Agent):
    """Engineering — drafts proposed code changes as patches saved to the
    output directory. The dispatcher does NOT auto-apply them; a human
    reviews the patch + applies it manually (or via a follow-up tool).
    This keeps the daemon from breaking the codebase autonomously while
    still letting us harvest its output."""
    name = "eng"
    model = "qwen2.5-coder:7b"
    system_prompt = (
        "You are the Engineering department of ArchHub. You draft code "
        "changes as unified diff patches (the `diff --git` format) "
        "against the repository at HEAD. You produce ONE patch per "
        "task. The patch must be syntactically valid Python (or "
        "TypeScript / SQL as appropriate). You include a one-paragraph "
        "rationale at the top of your output (in a comment block above "
        "the patch). You never include destructive operations (rm, "
        "force-push, dropping tables). If a task is ambiguous, output "
        "'NEEDS CLARIFICATION:' followed by the specific question. "
        "Match the existing code style: terse docstrings explaining "
        "intent, minimal inline comments where rationale matters."
    )
    readable_globs = [
        "app/**/*.py", "relay/**/*.ts", "tests/**/*.py",
        "docs/**/*.md", "STRATEGY.md",
    ]


class OpsAgent(Agent):
    name = "ops"
    model = "llama3.2:3b"
    system_prompt = (
        "You are the Ops department of ArchHub. You triage events: CI "
        "runs, incoming GitHub issues, dependency alerts. Your output "
        "is a short Markdown action list: one bullet per item with "
        "title, severity (critical/high/medium/low), and the single "
        "next step. You never recommend untested fixes; you flag what "
        "needs human attention. Keep it under 200 words total."
    )
    readable_globs = [
        "DEVELOPMENT_LOG.md", "STRATEGY.md", "*.md",
    ]


# ---------------------------------------------------------------------------
DEPARTMENTS: dict[str, type[Agent]] = {
    "docs": DocsAgent,
    "qa": QAAgent,
    "rnd": RnDAgent,
    "eng": EngAgent,
    "ops": OpsAgent,
}


def get(name: str) -> Agent:
    cls = DEPARTMENTS.get(name)
    if cls is None:
        raise KeyError(f"Unknown department: {name}")
    return cls()
