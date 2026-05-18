"""ArchHub Cloud LLM provider — managed proxy for paying subscribers.

Open-core monetization: the architect who doesn't want to install
Ollama and doesn't want to paste provider keys pays us a monthly
subscription, and every chat call flows through cloud.archhub.io/
v1/chat/completions. Our backend authenticates with their bearer
token, decrements their quota, and forwards to whichever provider
(Claude / GPT / Gemini) the routing layer picks server-side.

Wire format is OpenAI-compatible streaming so we reuse OpenAIClient
verbatim — only the base URL and auth header change. Tool calls,
reasoning content, and image inputs all pass through unchanged.

Auth note: the bearer token lives in secrets_store under
`archhub_cloud_token`. We load it at construction time, not at every
request, so a token refresh requires re-instantiating the client.
That happens naturally on the next chat turn because LLMRouter
recreates clients when their cached entry is dirty.
"""
from __future__ import annotations

from typing import Optional

from .openai_client import OpenAIClient


# Default base. Override via env for staging / local backend tests.
import os
DEFAULT_BASE_URL = os.environ.get(
    "ARCHHUB_CLOUD_LLM_BASE", "https://cloud.archhub.io/v1"
)


class ArchHubCloudClient(OpenAIClient):
    """Drop-in OpenAI-compatible client pointed at ArchHub Cloud.

    Constructed by llm_router when the user is signed into ArchHub
    Cloud and their plan has remaining quota. Calls to the proxy
    return 402 Payment Required when the quota is exhausted — the
    router maps that to an in-app paywall toast.
    """

    def __init__(self, token: str, *, base_url: Optional[str] = None):
        try:
            from openai import OpenAI
        except ImportError as ex:
            raise RuntimeError(
                "The 'openai' package isn't installed. Run: pip install openai"
            ) from ex
        self._client = OpenAI(
            api_key=token,
            base_url=base_url or DEFAULT_BASE_URL,
            default_headers={
                "X-ArchHub-Client": "desktop",
            },
        )
