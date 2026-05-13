"""Multi-LLM backend selector for agents — v1.3.0.

Cloud daemon can now use any of: ollama (local), anthropic (default
cloud), openai, gemini, lmstudio. These tests pin the static surface
+ the backend-install patching so a future client edit can't silently
break dispatch.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Clear any cached agents.* modules so the per-test backend installs
# don't bleed.
@pytest.fixture(autouse=True)
def _reset_agents_modules():
    yield
    for k in list(sys.modules):
        if k == "agents" or k.startswith("agents."):
            sys.modules.pop(k, None)


# ---------------------------------------------------------------------------
class TestOpenAIClient:
    def test_module_imports_and_exposes_envelope(self):
        from agents import openai_client
        assert openai_client.DEFAULT_OPENAI_MODEL.startswith("gpt-")
        assert hasattr(openai_client, "complete")
        assert hasattr(openai_client, "OpenAICompletion")

    def test_model_map_covers_ollama_ids(self):
        from agents import openai_client
        for ollama_id in ("qwen2.5-coder:7b", "llama3.2:3b", "deepseek-r1:8b"):
            assert ollama_id in openai_client.MODEL_MAP

    def test_complete_without_key_raises(self):
        from agents import openai_client
        with patch.object(openai_client, "_api_key", return_value=None):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                openai_client.complete(
                    model="qwen2.5-coder:7b",
                    system="s", user="hi",
                )


class TestGeminiClient:
    def test_module_imports(self):
        from agents import gemini_client
        assert gemini_client.DEFAULT_GEMINI_MODEL.startswith("gemini-")
        assert hasattr(gemini_client, "complete")

    def test_complete_without_key_raises(self):
        from agents import gemini_client
        with patch.object(gemini_client, "_api_key", return_value=None):
            with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
                gemini_client.complete(model="x", system="s", user="hi")

    def test_picks_pro_for_deepseek_r1(self):
        from agents import gemini_client
        assert gemini_client.MODEL_MAP["deepseek-r1:14b"] == "gemini-2.5-pro"


class TestLMStudioClient:
    def test_module_imports(self):
        from agents import lmstudio_client
        assert "1234" in lmstudio_client.DEFAULT_LMSTUDIO_BASE

    def test_list_models_returns_empty_when_server_down(self):
        from agents import lmstudio_client
        # Point at a guaranteed-closed port; expect [] not a crash.
        with patch.dict("os.environ",
                          {"LMSTUDIO_BASE_URL": "http://127.0.0.1:1"}):
            assert lmstudio_client.list_models() == []


class TestBackendSelector:
    def test_default_is_anthropic(self):
        from agents.cloud_runner import _select_backend
        with patch.dict("os.environ", {}, clear=False):
            # Remove any pre-existing override
            import os
            os.environ.pop("ARCHHUB_AGENTS_BACKEND", None)
            assert _select_backend() == "anthropic"

    def test_env_override_works(self):
        import os
        from agents.cloud_runner import _select_backend
        for b in ("ollama", "anthropic", "openai", "gemini", "lmstudio"):
            with patch.dict("os.environ",
                              {"ARCHHUB_AGENTS_BACKEND": b}):
                assert _select_backend() == b


class TestBackendInstall:
    def test_ollama_is_noop(self):
        from agents.cloud_runner import _install_backend
        # No exception, no side effect — base.complete stays as the
        # original ollama.complete reference.
        _install_backend("ollama")

    def test_unknown_backend_raises(self):
        from agents.cloud_runner import _install_backend
        with pytest.raises(ValueError, match="Unknown ARCHHUB_AGENTS_BACKEND"):
            _install_backend("magicllm")

    def test_anthropic_install_swaps_base_complete(self):
        from agents.cloud_runner import _install_backend
        from agents import base, anthropic_client
        original = base.complete
        try:
            _install_backend("anthropic")
            assert base.complete is anthropic_client.complete
        finally:
            base.complete = original  # restore

    def test_openai_install_swaps_base_complete(self):
        from agents.cloud_runner import _install_backend
        from agents import base, openai_client
        original = base.complete
        try:
            _install_backend("openai")
            assert base.complete is openai_client.complete
        finally:
            base.complete = original

    def test_gemini_install_swaps_base_complete(self):
        from agents.cloud_runner import _install_backend
        from agents import base, gemini_client
        original = base.complete
        try:
            _install_backend("gemini")
            assert base.complete is gemini_client.complete
        finally:
            base.complete = original

    def test_lmstudio_install_swaps_base_complete(self):
        from agents.cloud_runner import _install_backend
        from agents import base, lmstudio_client
        original = base.complete
        try:
            _install_backend("lmstudio")
            assert base.complete is lmstudio_client.complete
        finally:
            base.complete = original
