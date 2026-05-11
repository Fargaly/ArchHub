"""Local-model procrastination fixes (v1.0).

Regression coverage for the diagnosis "AI keeps writing essays
instead of calling tools":
  * Re-ranked model preferences pick tool-trained models first
  * deepseek-r1 / *-think models removed from action chains
  * gemma4 typo dropped; gemma3 present in quick chain
  * _looks_like_action heuristic
  * System prompt rewritten directive-first, total length < 1100 chars
  * Ollama client sends low temperature
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


def _router():
    from llm_router import LLMRouter
    from tool_engine import ToolEngine
    mgr = MagicMock(); mgr.entries = []
    return LLMRouter(ToolEngine(mgr))


# ---------------------------------------------------------------------------
class TestActionDetector:
    @pytest.mark.parametrize("text, expected", [
        ("place a wall in revit", True),
        ("add a door at level 2", True),
        ("list my outlook folders", True),
        ("read the latest email", True),
        ("send a reply", True),
        ("export the IFC", True),
        ("hello there", False),
        ("what time is it", False),
        ("thanks!", False),
        ("can you explain how revit works", False),
    ])
    def test_action_classification(self, text, expected):
        from llm_router import _looks_like_action
        msgs = [{"role": "user", "content": text}]
        assert _looks_like_action(msgs) is expected

    def test_empty_history_is_not_action(self):
        from llm_router import _looks_like_action
        assert _looks_like_action([]) is False

    def test_last_user_message_wins(self):
        # Earlier action message + later chitchat → not action.
        from llm_router import _looks_like_action
        msgs = [
            {"role": "user", "content": "place a wall"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "thanks!"},
        ]
        assert _looks_like_action(msgs) is False


# ---------------------------------------------------------------------------
class TestModelPreferences:
    def test_modeling_picks_tool_trained_first(self):
        from llm_router import LLMRouter
        prefs = LLMRouter._OLLAMA_MODEL_PREFERENCES
        first = prefs["modeling"][0]
        # command-r7b is Cohere's tool-use specialist; if not first,
        # at minimum llama3.1 (general tool-use winner) is first.
        assert first.startswith(("command-r", "llama3.1"))

    def test_action_chains_exclude_deepseek_r1(self):
        from llm_router import LLMRouter
        prefs = LLMRouter._OLLAMA_MODEL_PREFERENCES
        for chain_name in ("modeling", "analysis", "quick", "default"):
            chain = prefs.get(chain_name, ())
            assert not any("deepseek-r1" in m for m in chain), (
                f"deepseek-r1 leaked into {chain_name} chain — "
                "reasoning models procrastinate via <think> tags."
            )

    def test_reasoning_chain_keeps_thinking_models(self):
        # Reasoning is the only OPT-IN home for *-r1 / *-think models.
        from llm_router import LLMRouter
        prefs = LLMRouter._OLLAMA_MODEL_PREFERENCES
        chain = prefs.get("reasoning", ())
        assert any("r1" in m or "think" in m for m in chain)

    def test_gemma4_typo_removed(self):
        from llm_router import LLMRouter
        prefs = LLMRouter._OLLAMA_MODEL_PREFERENCES
        for chain in prefs.values():
            assert not any("gemma4" in m for m in chain), (
                "gemma4 doesn't exist on Ollama Hub — typo for gemma3."
            )

    def test_quick_chain_has_small_fast_models(self):
        from llm_router import LLMRouter
        prefs = LLMRouter._OLLAMA_MODEL_PREFERENCES
        first = prefs["quick"][0]
        # First-pick for quick should be a 3B model or smaller.
        assert "3b" in first.lower() or "3:" in first.lower()


# ---------------------------------------------------------------------------
class TestSystemPrompt:
    def test_prompt_leads_with_act_directive(self):
        r = _router()
        prompt = r._build_system_prompt()
        # First non-blank line should be the imperative — small models
        # weight the first ~80 tokens heavily.
        first_line = next(line for line in prompt.splitlines()
                          if line.strip())
        assert "act" in first_line.lower()
        assert "do not describe" in first_line.lower()

    def test_prompt_is_under_token_budget(self):
        # Effective attention window for 3-7B models is ~500 tokens
        # of system. Keep our prompt well under that so the meaningful
        # instructions don't get truncated/diluted.
        r = _router()
        prompt = r._build_system_prompt()
        # Rough char-to-token conversion: ~4 chars/token.
        assert len(prompt) < 1100, (
            f"System prompt too long ({len(prompt)} chars) — small "
            "models will lose the tail."
        )

    def test_prompt_forbids_pasting_code(self):
        r = _router()
        prompt = r._build_system_prompt()
        # The core rule that prevents the "here's some code" failure mode.
        assert ("pasting code" in prompt.lower()
                or "paste this" in prompt.lower()
                or "code into chat" in prompt.lower())


# ---------------------------------------------------------------------------
class TestOllamaPayload:
    """Verify the Ollama client sends a low temperature so the model
    doesn't 'explore' instead of calling tools."""

    def test_payload_includes_low_temperature(self):
        """Inspect the actual JSON we'd post for low temp."""
        import json
        # Build the same payload the client builds, sans the network.
        # We reach into the module to recreate the logic deterministically.
        from llm_providers.ollama_client import OllamaClient
        client = OllamaClient()
        # We can't call client.complete without Ollama; instead, verify
        # the source contains the right options block.
        import inspect
        source = inspect.getsource(OllamaClient.complete)
        assert "temperature" in source
        # The literal value must be low (under 0.3).
        # Search for "temperature": <float>
        import re
        m = re.search(r'"temperature"\s*:\s*([0-9.]+)', source)
        assert m is not None, "temperature option missing"
        assert float(m.group(1)) < 0.3, (
            f"Ollama temperature {m.group(1)} too high — encourages "
            "non-tool-calling text generation."
        )

    def test_payload_includes_num_predict_cap(self):
        from llm_providers.ollama_client import OllamaClient
        import inspect
        source = inspect.getsource(OllamaClient.complete)
        assert "num_predict" in source, (
            "num_predict cap missing — a procrastinating model could "
            "burn 8K tokens of 'let me think about this'."
        )
