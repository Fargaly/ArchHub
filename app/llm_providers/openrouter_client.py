"""OpenRouter provider client.

OpenRouter (https://openrouter.ai) is an OpenAI-compatible aggregator that
gives a single OAuth-authenticated key access to ~300 cloud models —
Claude, GPT, Gemini, Llama, Mistral, Qwen, DeepSeek, etc. Because the API
shape is OpenAI-compatible, we reuse OpenAIClient and only change the
base URL and HTTP headers.

Supplying `app_url` and `app_name` is recommended by OpenRouter so the
provider's analytics dashboard shows traffic attributed to ArchHub
rather than "unknown app". They do not affect billing or routing.
"""
from __future__ import annotations

from typing import Any, Callable

from .openai_client import OpenAIClient


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient(OpenAIClient):
    """Drop-in OpenAI-compatible client pointed at OpenRouter."""

    def __init__(self, api_key: str, *, app_url: str = "https://archhub.local",
                 app_name: str = "ArchHub"):
        try:
            from openai import OpenAI
        except ImportError as ex:
            raise RuntimeError(
                "The 'openai' package isn't installed. Run: pip install openai"
            ) from ex
        # Note: we do NOT call super().__init__ because that would try to
        # construct a stock OpenAI client with the OpenRouter key, which
        # works but doesn't include the attribution headers OpenRouter asks
        # for. We replace the underlying client outright.
        self._client = OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": app_url,
                "X-Title": app_name,
            },
        )


class CustomOpenAICompatibleClient(OpenAIClient):
    """For self-hosted relays that speak the OpenAI Chat Completions API.

    Used for the firm-relay path: ArchHub points at relay.firm.com/v1,
    sends the architect's per-user token, never sees a raw provider key.
    """

    def __init__(self, api_key: str, base_url: str):
        try:
            from openai import OpenAI
        except ImportError as ex:
            raise RuntimeError(
                "The 'openai' package isn't installed. Run: pip install openai"
            ) from ex
        self._client = OpenAI(api_key=api_key, base_url=base_url)
