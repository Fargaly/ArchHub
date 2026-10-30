"""Court: every HTTP chat the router sends is built and read by any-llm.

Founder order (rec_router_any_llm_not_litellm): put the model router on
any-llm-sdk (Mozilla.ai, Apache-2.0), never LiteLLM (malicious PyPI releases
in 2026), and replace the old hand-built provider path instead of adding a
second one. Fakes sit at the HTTP boundary (the opener); routing is real.
"""
import io
import json
import re
from pathlib import Path

from nodelang import model_router as router

ROOT = Path(__file__).resolve().parents[2]
ASK = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "2+2"}]


class _Answer(io.BytesIO):
    headers = {"Content-Type": "application/json"}


class _Wire:
    def __init__(self, payload):
        self.payload, self.requests = payload, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return _Answer(json.dumps(self.payload).encode("utf-8"))

    def header(self, name):
        return dict((k.lower(), v) for k, v in self.requests[-1].header_items()).get(name.lower())


def test_openrouter_is_sent_by_any_llm_with_the_key_and_the_unchanged_body():
    wire = _Wire({"id": "x", "object": "chat.completion", "created": 1, "model": "deepseek/deepseek-r1",
                  "choices": [{"index": 0, "message": {"role": "assistant", "content": "4"}, "finish_reason": "stop"}]})
    out = router.route_chat("deepseek/deepseek-r1", ASK, opener=wire, environ={"OPENROUTER_API_KEY": "or-fixture-key"},
                            secrets_loader=lambda name: "", cloud_session=None)
    assert out["text"] == "4" and out["family"] == "openrouter"
    assert wire.requests[0].full_url == router.OPENROUTER_CHAT
    assert wire.header("Authorization") == "Bearer or-fixture-key"
    assert "openai/python" in (wire.header("User-Agent") or "").lower(), "the OpenAI SDK under any-llm sent it"
    body = json.loads(wire.requests[0].data)
    assert body["max_tokens"] == 900 and "max_completion_tokens" not in body


def test_anthropic_answer_is_normalised_by_any_llm():
    wire = _Wire({"id": "m", "type": "message", "role": "assistant", "model": "claude-x",
                  "content": [{"type": "text", "text": "four"}], "stop_reason": "end_turn",
                  "usage": {"input_tokens": 3, "output_tokens": 1}})
    out = router.route_chat("anthropic-api/claude-x", ASK, opener=wire,
                            environ={"ANTHROPIC_API_KEY": "an-fixture-key-0001"},
                            secrets_loader=lambda name: "", cloud_session=None)
    body = json.loads(wire.requests[0].data)
    assert wire.requests[0].full_url == router.ANTHROPIC_MESSAGES
    assert body["system"] == "be brief" and body["messages"] == [{"role": "user", "content": "2+2"}]
    assert wire.header("x-api-key") == "an-fixture-key-0001"
    assert out["text"] == "four" and out["finish_reason"] == "stop" and out["usage"]["total_tokens"] == 4


def test_ollama_answer_is_normalised_and_carries_no_key():
    wire = _Wire({"model": "llama3", "created_at": "2026-10-29T00:00:00Z",
                  "message": {"role": "assistant", "content": "four"}, "done": True, "done_reason": "stop"})
    out = router.route_chat("ollama/llama3", ASK, opener=wire, environ={}, secrets_loader=lambda name: "",
                            cloud_session=None)
    assert wire.requests[0].full_url == router.OLLAMA_CHAT
    assert wire.header("Authorization") is None
    assert out["text"] == "four" and out["finish_reason"] == "stop"


def test_the_old_hand_built_wire_is_gone_and_litellm_is_never_shipped():
    source = (ROOT / "01.APP/nodelang/model_router.py").read_text(encoding="utf-8")
    assert "def _body(" not in source and "def _read_chat_stream(" not in source
    assert "from any_llm import AnyLLM" in source
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^any-llm-sdk==\S+$", requirements, re.M)
    assert not re.search(r"^\s*litellm", requirements, re.M | re.I)


def test_every_provider_call_writes_one_genai_span(monkeypatch):
    from contextlib import contextmanager
    from opentelemetry import trace
    spans = []

    class Span(dict):
        def set_attribute(self, key, value):
            self[key] = value

    class Tracer:
        @contextmanager
        def start_as_current_span(self, name, kind=None, attributes=None):
            span = Span(attributes or {}, name=name)
            spans.append(span)
            yield span

    monkeypatch.setattr(trace, "get_tracer", lambda *args, **kwargs: Tracer())
    wire = _Wire({"model": "llama3", "created_at": "2026-10-29T00:00:00Z", "prompt_eval_count": 5, "eval_count": 2,
                  "message": {"role": "assistant", "content": "four"}, "done": True, "done_reason": "stop"})
    router.route_chat("ollama/llama3", ASK, opener=wire, environ={}, secrets_loader=lambda name: "", cloud_session=None)
    assert len(spans) == 1
    span = spans[0]
    assert span["gen_ai.operation.name"] == "chat" and span["gen_ai.provider.name"] == "ollama"
    assert span["gen_ai.request.model"] == "llama3" and span["gen_ai.response.model"] == "llama3"
    assert span["gen_ai.usage.input_tokens"] == 5 and span["gen_ai.usage.output_tokens"] == 2
    assert not any("four" in str(value) or "2+2" in str(value) for value in span.values()), "no prompt or answer text"
