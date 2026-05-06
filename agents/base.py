"""Base Agent class — one Ollama-backed department.

Each Agent owns:
  - a name + model + system prompt (defines the role)
  - an output directory under agents/outputs/<dept>/<task-id>/
  - a tool whitelist (read_file / write_output / append_log)
  - a max-tokens budget per task to keep runs predictable

Agents do NOT have arbitrary file write, shell exec, network access, or
the ability to push to git. The dispatcher is responsible for any
cross-cutting concerns (committing outputs to a feature branch, opening
a PR, etc.) once an Agent returns its result.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .ollama import complete, OllamaCompletion, is_running
from .queue import Task, OUTPUTS_DIR, LOGS_DIR, REPO_ROOT


@dataclass
class AgentResult:
    success: bool
    summary: str
    output_dir: Optional[Path] = None
    artifacts: list[Path] = field(default_factory=list)
    elapsed_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: Optional[str] = None


class Agent:
    """Base class — subclass and set `name`, `model`, `system_prompt`."""

    name: str = "agent"
    model: str = "llama3.1:latest"
    system_prompt: str = ""

    # Per-agent generation timeout. Reasoning models (deepseek-r1) can
    # blow past the 600s default; subclasses bump this to avoid
    # spurious .failed marks from the daemon.
    timeout_seconds: int = 600

    # Subclasses can override to seed self-recurring tasks at boot.
    seed_tasks: list[dict] = []

    # Files in the repo this agent is allowed to READ. Glob patterns
    # relative to repo root. Reading anything else returns "(redacted)".
    readable_globs: list[str] = ["app/**/*.py", "docs/**/*.md", "*.md"]

    def __init__(self):
        self.output_root = OUTPUTS_DIR / self.name
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.log_path = LOGS_DIR / f"{self.name}-{datetime.now().strftime('%Y%m%d')}.log"

    # ---- public API used by the dispatcher --------------------------------

    def can_run(self) -> bool:
        return is_running()

    def execute(self, task: Task) -> AgentResult:
        """Run a task end-to-end. Catches every exception so the daemon
        keeps running."""
        if not self.can_run():
            return AgentResult(False, "Ollama not running", error="ollama_offline")

        out_dir = self.output_root / task.id
        out_dir.mkdir(parents=True, exist_ok=True)

        prompt = self._build_prompt(task)
        self._log(f"[{task.id}] {task.title} → starting model={self.model} timeout={self.timeout_seconds}s")
        t0 = time.time()
        completion = complete(self.model, self.system_prompt, prompt,
                              timeout=self.timeout_seconds)
        elapsed = int((time.time() - t0) * 1000)

        if completion.error:
            self._log(f"[{task.id}] FAILED: {completion.error}")
            return AgentResult(
                False, f"Model error: {completion.error}",
                output_dir=out_dir, elapsed_ms=elapsed, error=completion.error,
            )

        # Always write the raw completion to disk for audit + debugging.
        raw_path = out_dir / "completion.md"
        raw_path.write_text(completion.text, encoding="utf-8")

        # Subclasses may post-process (split into multiple files, validate
        # JSON output, etc.) and return additional artifacts.
        try:
            artifacts = self._post_process(task, completion, out_dir) or []
        except Exception as ex:
            self._log(f"[{task.id}] POSTPROCESS FAILED: {ex}")
            return AgentResult(
                False, f"Post-process error: {ex}",
                output_dir=out_dir, error=str(ex), elapsed_ms=elapsed,
            )

        self._log(
            f"[{task.id}] OK in {elapsed}ms · "
            f"prompt_tokens={completion.prompt_tokens} "
            f"completion_tokens={completion.completion_tokens} "
            f"artifacts={len(artifacts) + 1}"
        )

        summary = self._summarise(task, completion, [raw_path, *artifacts])
        return AgentResult(
            success=True, summary=summary,
            output_dir=out_dir, artifacts=[raw_path, *artifacts],
            elapsed_ms=elapsed,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
        )

    # ---- subclass hooks ---------------------------------------------------

    def _build_prompt(self, task: Task) -> str:
        """Compose the user prompt sent to the model. Subclasses can
        override to pre-load file context."""
        ctx_lines = []
        for fname in (task.inputs.get("context_files") or []):
            content = self._read_repo_file(fname)
            if content is None:
                continue
            ctx_lines.append(f"=== {fname} ===\n{content[:8000]}\n")
        ctx = "\n".join(ctx_lines)
        return (
            f"# Task: {task.title}\n\n"
            f"## Instructions\n{task.instructions}\n\n"
            + (f"## Context files\n{ctx}\n" if ctx else "")
            + "\nProduce your output now."
        )

    def _post_process(self, task: Task, completion: OllamaCompletion,
                      out_dir: Path) -> list[Path]:
        """Default: nothing to do. Subclasses split markdown into files,
        validate JSON, etc."""
        return []

    def _summarise(self, task: Task, completion: OllamaCompletion,
                   artifacts: list[Path]) -> str:
        """One-line summary written to the queue's .done file."""
        first_line = (completion.text or "").strip().splitlines()[:1]
        head = first_line[0][:160] if first_line else "(empty completion)"
        return f"{head}  ·  {len(artifacts)} files"

    # ---- helpers ----------------------------------------------------------

    def _read_repo_file(self, path: str) -> Optional[str]:
        """Read a repo file IF its path matches one of `readable_globs`."""
        target = (REPO_ROOT / path).resolve()
        try:
            target.relative_to(REPO_ROOT)
        except ValueError:
            return None
        from fnmatch import fnmatch
        rel = str(target.relative_to(REPO_ROOT)).replace("\\", "/")
        if not any(fnmatch(rel, g) for g in self.readable_globs):
            return None
        try:
            return target.read_text(encoding="utf-8")[:32_000]
        except Exception:
            return None

    def _log(self, line: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{ts} [{self.name}] {line}\n")
        except Exception:
            pass
