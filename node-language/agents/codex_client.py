"""Codex backend — dedicated GPT-5 Codex routing for code-heavy depts.

Selected via env `ARCHHUB_AGENTS_BACKEND=codex`. Same surface as the
other clients (`complete`, `is_configured`, `list_models`, dataclass
envelope shape-compatible with OllamaCompletion).

Use this when you want EVERY department's task to go through a Codex
model — including the non-coding depts (docs, ops, watcher). Trade-off:
Codex is tuned for code so writes prose noticeably tighter but loses
some creative range. Set ARCHHUB_AGENTS_BACKEND=openai instead for
the default mixed routing (general + codex + reasoning).

Cost: gpt-5.3-codex is ~$2/M input, $8/M output (as of v1.3.2). For
the agents queue's typical patch-sized output (1-2k tokens) that's
~$0.01-0.02 per task.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from agents import openai_client


DEFAULT_CODEX_MODEL = "gpt-5.3-codex"

# Every Ollama model id routes to the same Codex model. Departments
# stay LLM-agnostic; this client expresses the "codex everywhere" call.
MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder:7b":  "gpt-5.3-codex",
    "qwen2.5-coder:14b": "gpt-5.3-codex",
    "llama3.2:3b":       "gpt-5.1-codex-mini",      # cheap for chatter
    "llama3.1:latest":   "gpt-5.1-codex",
    "llama3.1:8b":       "gpt-5.1-codex",
    "command-r7b":       "gpt-5.1-codex-mini",
    "command-r:latest":  "gpt-5.1-codex-mini",
    "deepseek-r1:8b":    "gpt-5.1-codex-max",
    "deepseek-r1:14b":   "gpt-5.1-codex-max",
}


@dataclass
class CodexCompletion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def is_configured() -> bool:
    return openai_client.is_configured()


def list_models() -> list[str]:
    return list(set(MODEL_MAP.values())) + [DEFAULT_CODEX_MODEL]


def complete(*, model: str, system: str, user: str,
              temperature: float = 0.1,
              max_tokens: int = 4096,
              timeout_seconds: int = 600) -> CodexCompletion:
    """Same shape as openai_client.complete but locks the model to a
    Codex variant. Reuses openai_client.complete by temporarily swapping
    MODEL_MAP so we don't duplicate the HTTP plumbing.
    """
    codex_model = MODEL_MAP.get(model, DEFAULT_CODEX_MODEL)
    # Temporarily override the mapping so openai_client routes our
    # incoming model id to the Codex variant we want.
    _prev = openai_client.MODEL_MAP.get(model)
    openai_client.MODEL_MAP[model] = codex_model
    try:
        r = openai_client.complete(
            model=model, system=system, user=user,
            temperature=temperature, max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    finally:
        if _prev is None:
            openai_client.MODEL_MAP.pop(model, None)
        else:
            openai_client.MODEL_MAP[model] = _prev
    return CodexCompletion(
        text=r.text, model=r.model,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
    )
