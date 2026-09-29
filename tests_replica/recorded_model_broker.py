"""Shared recorded provider boundary; importing it does not load transport courts."""
import hashlib
from nodelang.model_execution_broker import ModelExecutionResult


class _RecordedModelBroker:
    """A physical-boundary double; it never launches a provider process."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def execute(self, *, provider, location, model, data_class, task):
        self.calls.append({
            "provider": provider,
            "location": location,
            "model": model,
            "data_class": data_class,
            "task": task,
        })
        output = (
            b'{"summary":"Review the bounded Workshop evidence.",'
            b'"next_actions":["Request review before an effect."],'
            b'"risks":["Unapproved action is denied."],"uncertainty":0.2}'
        )
        return ModelExecutionResult(
            "succeeded",
            hashlib.sha256(output).hexdigest(),
            len(output),
            "",
            {
                "summary": "Review the bounded Workshop evidence.",
                "next_actions": ["Request review before an effect."],
                "risks": ["Unapproved action is denied."],
                "uncertainty": 0.2,
            },
        )

    def model_provider_readiness(self):
        return {
            provider: {
                "location": location,
                "state": "test-ready",
                "evidence": "test host observation",
                "execution_authority": "requires graph request, approval, and one-use grant",
            }
            for provider, location in (
                ("gpt", "local-cli:codex"),
                ("claude", "local-cli:claude"),
                ("gemini", "local-cli:gemini"),
                ("openrouter", "network:openrouter"),
                ("local", "local-http:ollama"),
            )
        }


