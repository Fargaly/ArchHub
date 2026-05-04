"""Google Gemini provider client. Stub implementation — returns a clear
error if invoked. Wire up the google-genai SDK when needed."""
from __future__ import annotations

from typing import Callable


class GoogleClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def stream_completion(
        self, model: str, system: str, messages: list[dict],
        tools: list[dict], on_chunk: Callable[[str], None],
    ) -> dict:
        msg = (
            "[Gemini provider not yet implemented. The Google client stub is in place "
            "and the API key is loaded — wire up `google-genai` SDK in "
            "llm_providers/google_client.py to enable.]"
        )
        on_chunk(msg)
        return {"type": "final", "text": msg}
