"""Real token-accounting mechanism (FIX 1, 2026-05-31).

These tests prove the MECHANISM that replaced the footer ServerStrip's old
client-side chars/4 ESTIMATE with REAL provider-reported usage:

  provider response usage{prompt_tokens, completion_tokens}
      → LLMRouter._record_usage  (the exact call _complete_once makes)
      → LLMRouter._token_usage accumulator
      → LLMRouter.get_token_usage()  (read by bridge get_token_usage slot)
      → ServerStrip renders tokens (+cost when the price is known)

Honest caveat made explicit by `test_empty_state_is_zero_before_any_call`:
with no real completion, the total is 0 — the footer shows nothing. That is
real, not fabricated: it reflects actual provider usage, which is none until
a provider call lands. providers_configured is 0 on a fresh box, so a live
chat can't be made here; we verify the capture path with real-SHAPED provider
responses instead.
"""
from __future__ import annotations

import json

import pytest

import llm_router
from llm_router import LLMRouter, _price_for_model


class _StubTools:
    """Minimal stand-in for ToolEngine. LLMRouter.__init__ only stores it;
    the token-accounting path never calls into it, so a bare object is a
    faithful, real substitute (no behaviour is mocked away)."""


def _router() -> LLMRouter:
    return LLMRouter(_StubTools())


def test_empty_state_is_zero_before_any_call():
    r = _router()
    u = r.get_token_usage()
    assert u["tokens"] == 0
    assert u["prompt_tokens"] == 0
    assert u["completion_tokens"] == 0
    assert u["cost"] == 0.0
    assert u["cost_known"] is False
    assert u["completions"] == 0
    # ServerStrip gates the badge on tokens > 0 — empty state renders nothing.
    assert not (u["tokens"] > 0)


def test_record_usage_accumulates_real_numbers():
    r = _router()
    # Two REAL-shaped Anthropic/OpenAI usage blocks (prompt + completion).
    r._record_usage("anthropic", "claude-sonnet-4-6",
                    {"prompt_tokens": 1200, "completion_tokens": 300})
    r._record_usage("anthropic", "claude-sonnet-4-6",
                    {"prompt_tokens": 800, "completion_tokens": 150})
    u = r.get_token_usage()
    # REAL accumulation — not an estimate.
    assert u["prompt_tokens"] == 2000
    assert u["completion_tokens"] == 450
    assert u["tokens"] == 2450
    assert u["completions"] == 2
    assert u["model"] == "anthropic:claude-sonnet-4-6"
    # ServerStrip would now render (tokens > 0).
    assert u["tokens"] > 0


def test_real_cost_from_price_table():
    r = _router()
    # claude-sonnet-4 price = ($3/M in, $15/M out).
    r._record_usage("anthropic", "claude-sonnet-4-6",
                    {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})
    u = r.get_token_usage()
    assert u["cost_known"] is True
    # 1M prompt × $3/M + 1M completion × $15/M = $18.00 exactly.
    assert u["cost"] == pytest.approx(18.0, abs=1e-6)


def test_local_model_reports_tokens_but_no_cost():
    r = _router()
    # An Ollama (local) model: real tokens, but NOT metered → cost omitted
    # honestly rather than fabricated.
    r._record_usage("ollama", "llama3.1:8b",
                    {"prompt_tokens": 500, "completion_tokens": 120})
    u = r.get_token_usage()
    assert u["tokens"] == 620
    assert u["cost_known"] is False
    assert u["cost"] == 0.0


def test_missing_or_empty_usage_adds_nothing():
    r = _router()
    # Provider didn't report usage (None) or reported zeros — no guessing.
    r._record_usage("google", "gemini-2.5-pro", None)
    r._record_usage("google", "gemini-2.5-pro", {})
    r._record_usage("google", "gemini-2.5-pro",
                    {"prompt_tokens": 0, "completion_tokens": 0})
    u = r.get_token_usage()
    assert u["tokens"] == 0
    assert u["completions"] == 0


def test_capture_from_provider_stream_dict_shape():
    """The non-ollama path in _complete_once does
    `self._record_usage(provider, model_name, stream.get("usage"))`.
    Feed a real-shaped `stream` dict (as the anthropic/openai clients now
    return) and confirm the usage rides through."""
    r = _router()
    stream = {
        "type": "final",
        "text": "Placed 47 dimensions.",
        "usage": {"prompt_tokens": 640, "completion_tokens": 88},
    }
    r._record_usage("openai", "gpt-4o", stream.get("usage"))
    u = r.get_token_usage()
    assert u["prompt_tokens"] == 640
    assert u["completion_tokens"] == 88
    assert u["tokens"] == 728
    # gpt-4o is a metered model with a known price → cost surfaces.
    assert u["cost_known"] is True
    assert u["cost"] > 0


def test_price_table_longest_match_wins():
    # gpt-4o-mini must NOT be priced as gpt-4o.
    assert _price_for_model("gpt-4o-mini") == (0.15, 0.60)
    assert _price_for_model("gpt-4o") == (2.5, 10.0)
    # Unknown / local model → no price.
    assert _price_for_model("llama3.1:8b") is None
    assert _price_for_model("") is None


def test_get_token_usage_returns_a_copy():
    """The slot must hand out a copy so a JS-side caller (or anything else)
    can't mutate the live accumulator."""
    r = _router()
    r._record_usage("anthropic", "claude-opus-4-7",
                    {"prompt_tokens": 10, "completion_tokens": 5})
    snap = r.get_token_usage()
    snap["tokens"] = 999_999
    assert r.get_token_usage()["tokens"] == 15


def test_bridge_slot_delegates_to_router(monkeypatch):
    """The bridge `get_token_usage` slot returns the router's REAL usage as
    JSON. Verify the wiring without standing up Qt: call the unbound slot
    against a tiny stand-in that carries a real router."""
    import bridge as bridge_mod

    r = _router()
    r._record_usage("anthropic", "claude-haiku-4-5-20251001",
                    {"prompt_tokens": 220, "completion_tokens": 40})

    class _Holder:
        pass

    holder = _Holder()
    holder.router = r
    # Call the slot's underlying function directly (bypass the Qt wrapper).
    raw = bridge_mod.ArchHubBridge.get_token_usage(holder)
    data = json.loads(raw)
    assert data["prompt_tokens"] == 220
    assert data["completion_tokens"] == 40
    assert data["tokens"] == 260
    assert data["cost_known"] is True  # haiku is metered


def test_bridge_slot_safe_when_router_missing():
    import bridge as bridge_mod

    class _Holder:
        router = None

    raw = bridge_mod.ArchHubBridge.get_token_usage(_Holder())
    data = json.loads(raw)
    assert data["tokens"] == 0
    assert data["cost_known"] is False


# ───────────────────────────────────────────────────────────────────────────
# END-TO-END exact-capture: a REAL-SHAPED provider response (the provider's
# OWN native field names — Anthropic input_tokens/output_tokens, OpenAI's
# include_usage chunk, Ollama prompt_eval_count/eval_count) driven through the
# actual provider client → the client's usage{} → _record_usage → the tally.
# This proves the FULL path, including each client's field translation, lands
# EXACTLY 1234 / 567 — NOT a chars/4 estimate of the streamed text (which is
# "Placed 47 walls." → would be ~4 tokens, nowhere near 1234/567). The tests
# above start at the post-translation {prompt_tokens, completion_tokens} shape;
# these close the gap by exercising the raw provider field names too.
# ───────────────────────────────────────────────────────────────────────────

from types import SimpleNamespace as _NS  # noqa: E402

# Deliberately tiny streamed text — if anything were still estimating tokens
# from character count (chars/4), the captured count would be ~4, not 1234/567.
_STREAM_TEXT = "Placed 47 walls."


class _FakeAnthropicStreamCtx:
    """Context-manager + iterator mimicking anthropic's messages.stream()."""

    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return iter(self._events)

    def __exit__(self, *a):
        return False


def test_anthropic_client_captures_real_usage_into_router():
    """Anthropic streams usage on message_start (input_tokens) +
    message_delta (output_tokens). Drive the REAL AnthropicClient with a fake
    SDK emitting input_tokens:1234 / output_tokens:567, then feed its returned
    usage{} into the router exactly as _complete_once does."""
    from llm_providers.anthropic_client import AnthropicClient

    client = AnthropicClient(api_key="sk-test")          # no network on init

    class _FakeMessages:
        def stream(self, **kw):
            events = [
                _NS(type="message_start",
                    message=_NS(usage=_NS(input_tokens=1234, output_tokens=0))),
                _NS(type="content_block_delta",
                    delta=_NS(type="text_delta", text=_STREAM_TEXT)),
                _NS(type="message_delta",
                    delta=_NS(stop_reason="end_turn"),
                    usage=_NS(output_tokens=567)),
            ]
            return _FakeAnthropicStreamCtx(events)

    client._client = _NS(messages=_FakeMessages())

    chunks: list[str] = []
    out = client.stream_completion(
        model="claude-sonnet-4-6", system="s",
        messages=[{"role": "user", "content": "hi"}], tools=[],
        on_chunk=chunks.append,
    )
    # The client translated the provider's native fields to the router shape.
    assert out["usage"] == {"prompt_tokens": 1234, "completion_tokens": 567}
    assert "".join(chunks) == _STREAM_TEXT

    # Now the router fold — the exact call _complete_once makes.
    r = _router()
    r._record_usage("anthropic", "claude-sonnet-4-6", out["usage"])
    u = r.get_token_usage()
    assert u["prompt_tokens"] == 1234          # EXACT — not chars/4
    assert u["completion_tokens"] == 567
    assert u["tokens"] == 1801
    assert u["cost_known"] is True             # sonnet is metered
    # Real per-model math: 1234×$3/M + 567×$15/M.
    assert u["cost"] == pytest.approx(1234 * 3.0 / 1e6 + 567 * 15.0 / 1e6, abs=1e-9)


def test_openai_client_captures_real_usage_into_router():
    """OpenAI emits a final usage-only chunk (choices == []) carrying
    prompt_tokens / completion_tokens because the client requests
    include_usage. Drive the REAL OpenAIClient with a fake SDK and confirm
    1234 / 567 ride through to the router."""
    from llm_providers.openai_client import OpenAIClient

    client = OpenAIClient(api_key="sk-test")

    class _FakeCompletions:
        def create(self, **kw):
            # include_usage must have been requested for the usage chunk.
            assert kw.get("stream_options") == {"include_usage": True}
            yield _NS(choices=[_NS(delta=_NS(content=_STREAM_TEXT,
                                             tool_calls=None),
                                   finish_reason=None)], usage=None)
            yield _NS(choices=[_NS(delta=_NS(content=None, tool_calls=None),
                                   finish_reason="stop")], usage=None)
            # Final usage-only chunk (no choices).
            yield _NS(choices=[],
                      usage=_NS(prompt_tokens=1234, completion_tokens=567))

    client._client = _NS(chat=_NS(completions=_FakeCompletions()))

    out = client.stream_completion(
        model="gpt-4o", system="s",
        messages=[{"role": "user", "content": "hi"}], tools=[],
        on_chunk=lambda _p: None,
    )
    assert out["usage"] == {"prompt_tokens": 1234, "completion_tokens": 567}

    r = _router()
    r._record_usage("openai", "gpt-4o", out["usage"])
    u = r.get_token_usage()
    assert u["prompt_tokens"] == 1234
    assert u["completion_tokens"] == 567
    assert u["tokens"] == 1801
    assert u["cost_known"] is True
    assert u["cost"] == pytest.approx(1234 * 2.5 / 1e6 + 567 * 10.0 / 1e6, abs=1e-9)


def test_ollama_client_captures_real_usage_into_router(monkeypatch):
    """Ollama reports real counts on the done-chunk as prompt_eval_count /
    eval_count; the client stashes them on `last_usage`, which _complete_once
    folds in. Local model → tokens captured, cost omitted honestly."""
    import llm_providers.ollama_client as oc

    ndjson = [
        json.dumps({"message": {"content": _STREAM_TEXT}, "done": False}).encode(),
        json.dumps({"message": {"content": ""}, "done": True,
                    "prompt_eval_count": 1234, "eval_count": 567}).encode(),
    ]

    class _FakeResp:
        def __enter__(self):
            return iter(ndjson)

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(oc.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp())

    client = oc.OllamaClient()
    text, calls = client.complete(
        system="s", history=[{"role": "user", "content": "hi"}],
        model="llama3.1:8b", tools=[], on_chunk=lambda _p: None,
    )
    assert client.last_usage == {"prompt_tokens": 1234, "completion_tokens": 567}

    r = _router()
    r._record_usage("ollama", "llama3.1:8b", client.last_usage)
    u = r.get_token_usage()
    assert u["prompt_tokens"] == 1234
    assert u["completion_tokens"] == 567
    assert u["tokens"] == 1801
    # Local model is not metered → cost stays honestly absent.
    assert u["cost_known"] is False
    assert u["cost"] == 0.0


def test_chars_over_four_estimate_is_gone_from_serverstrip():
    """Guard against regression to the old client-side chars/4 + blended
    $3/M estimate. ServerStrip (and the whole JSX) must contain NO live
    `window.__archhub_usage` assignment and NO `/ 4` token heuristic. The
    only permitted mentions are in comments documenting the removal."""
    from pathlib import Path
    import re

    jsx = (Path(__file__).resolve().parent.parent
           / "app" / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")

    for ln in jsx.splitlines():
        # Strip line comments so we only inspect live code.
        code = ln.split("//", 1)[0]
        # No assignment to the old estimate global.
        assert "window.__archhub_usage" not in code, (
            f"old chars/4 estimate global still in live code: {ln!r}")
        # No `/4` or `/ 4` token-from-chars heuristic in live code.
        assert not re.search(r"/\s*4\b", code), (
            f"a `/ 4` heuristic survives in live code: {ln!r}")
    # The blended $3/M fabrication must not appear anywhere (incl. comments
    # claiming it's still used). It's gone — cost comes from MODEL_PRICES.
    assert "$3/M" not in jsx or "blended $3/M" in jsx, (
        "if $3/M is mentioned it must only be as the documented-removed "
        "'blended $3/M' estimate, never live")
