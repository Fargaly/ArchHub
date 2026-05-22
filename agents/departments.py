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
        "app/**/*.py", "cloud_backend/**/*.py", "docs/**/*.md",
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
        "app/**/*.py", "cloud_backend/**/*.py", "tests/**/*.py",
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
class TelemetryAgent(Agent):
    """Reads local usage + token-meter signals, emits a 'what hurts'
    friction report.

    Source data:
      * `%LOCALAPPDATA%/ArchHub/skill_usage.json` — per-Skill runs,
        successes, failures, retries, last_error.
      * `agents/logs/token_meter.json` — per-dept run cost.
      * `agents/logs/<dept>-<date>.log` — raw run history.

    Output: Markdown report with
      * top 5 failing Skills (highest failure-rate × runs)
      * top 5 retried prompts (strong UX-pain signal)
      * dept time burn vs weekly budget
      * 3-bullet recommended sprint focus
    """
    name = "telemetry"
    model = "llama3.1:latest"
    timeout_seconds = 600
    system_prompt = (
        "You are the Telemetry department of ArchHub. You read raw usage "
        "data and produce a short 'where it hurts' Markdown brief for the "
        "Engineering department. Structure: '# Friction report — <date>' "
        "→ '## Top failing Skills' (table) → '## Top retried prompts' "
        "→ '## Department burn' → '## Sprint focus (3 bullets)'. Be "
        "specific: include skill IDs, failure rates, last error excerpts. "
        "Never invent numbers — if a section is empty, say 'no signal yet'."
    )
    readable_globs = [
        "agents/logs/*.json", "agents/logs/*.log",
        "agents/outputs/**/*.md",
        "*.md",
    ]


class BacklogAgent(Agent):
    """Consumer of TelemetryAgent's friction report. Drafts new YAML
    task files for the Engineering / R&D / QA depts so the next
    scheduler cycle picks them up automatically.

    The dispatcher does NOT auto-apply BacklogAgent's output as new
    task files — they land in `agents/outputs/backlog/<run-id>/` for
    a human (founder) to review and `mv` into `agents/tasks/<dept>/`
    if approved. Treat this as the inbox, not the queue.
    """
    name = "backlog"
    model = "qwen2.5-coder:7b"
    timeout_seconds = 900
    system_prompt = (
        "You are the Backlog department of ArchHub. You read the latest "
        "friction report from agents/outputs/telemetry/ and produce ONE "
        "or more task YAML files that the dispatcher could later run. "
        "Each task block follows this exact JSON-in-YAML schema:\n"
        "{\n"
        "  \"id\": \"<dept-slug>-<short-title>-<random-8>\",\n"
        "  \"department\": \"eng | qa | rnd | docs | ops\",\n"
        "  \"title\": \"...\",\n"
        "  \"instructions\": \"...\",\n"
        "  \"priority\": 50,\n"
        "  \"inputs\": { \"context_files\": [\"app/...py\", ...] }\n"
        "}\n\n"
        "Only emit tasks where the friction signal is concrete (failing "
        "Skill ID, retry count, error text). Never invent. If no signal "
        "is actionable, output 'NO_BACKLOG_THIS_CYCLE' and nothing else."
    )
    readable_globs = [
        "agents/outputs/telemetry/**/*.md",
        "app/**/*.py",
        "*.md",
    ]


class WatcherAgent(Agent):
    """Scans peer GitHub issues + Reddit threads for AEC pain points
    that overlap with ArchHub's roadmap. Output: weekly Markdown
    digest of the top 5 unmet user needs in the niche, with citation.

    Uses no LLM API tokens — everything runs through local Ollama.
    The agent is given pre-fetched peer-issue text via context_files
    populated by an upstream fetcher script (added in a follow-up
    PR; for now it works on whatever Markdown is in the repo).
    """
    name = "watcher"
    model = "qwen2.5-coder:7b"
    timeout_seconds = 1200
    system_prompt = (
        "You are the Market-Watcher department of ArchHub. You read pre-"
        "fetched peer-repo issue text and Reddit thread snippets. "
        "Produce a weekly digest titled '# Peer pain — <week>' with "
        "EXACTLY this structure:\n"
        "  ## Top unmet needs (max 5)\n"
        "  ## What ArchHub already addresses\n"
        "  ## What ArchHub should consider next\n"
        "Never invent quotes. Cite the source line in brackets, e.g. "
        "'[blender-mcp#123]'. If a peer is silent this week, say so."
    )
    readable_globs = [
        "agents/outputs/watcher/**/*.md",
        "STRATEGY.md", "VISION.md", "*.md",
    ]


# ---------------------------------------------------------------------------
DEPARTMENTS: dict[str, type[Agent]] = {
    "docs": DocsAgent,
    "qa": QAAgent,
    "rnd": RnDAgent,
    "eng": EngAgent,
    "ops": OpsAgent,
    "telemetry": TelemetryAgent,
    "backlog": BacklogAgent,
    "watcher": WatcherAgent,
}


def get(name: str) -> Agent:
    cls = DEPARTMENTS.get(name)
    if cls is None:
        raise KeyError(f"Unknown department: {name}")
    return cls()
