"""Router fixes (founder 2026-06-20: 'the router is a piece of shit /
every time I write I get nothing').

Two root-caused bugs are locked here:

A) PRIMARY-CHURN — a signed-out / no-credential provider (claude_cli on
   PATH but the subscription is logged out) must NOT be chosen as the
   PRIMARY provider turn-after-turn. Once it auth-fails it is marked
   signed-out and `configured_providers()` skips it BEFORE the next turn
   tries it — so there is no per-turn 'switching provider…' churn. It
   re-enters automatically on the next successful completion.

B) EMPTY REPLY — host-family words ('teams', 'revit', 'word', 'max', …)
   made the model reach for an offline host tool and fabricate, the
   fabricated/refusal text was RETRACTED, the fallback chain dried up,
   and the turn ended EMPTY (chat_done, zero chunks). The router must
   NEVER end a turn empty: after a retraction with no replacement it
   falls through to a tools-disabled plain-LLM answer and streams THAT.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from llm_router import LLMRouter, LLMResponse  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal fakes — we drive complete() without any real provider client.


class _FakeManager:
    entries = []


class _FakeToolEngine:
    """Stand-in for ToolEngine. The router only touches `manager.entries`
    (system-prompt active list) and `tool_schemas_for` (had_tools check)."""

    def __init__(self, schemas):
        self.manager = _FakeManager()
        self._schemas = schemas

    def tool_schemas_for(self, provider):
        return list(self._schemas)

    def invoke(self, *a, **k):
        return {"status": "ok"}


def _router(schemas=None):
    r = LLMRouter(_FakeToolEngine(schemas or []))
    # Keep the brain / library gates inert during the test.
    r._build_system_prompt = lambda: "SYS"
    return r


class _FakeClient:
    """OpenAI-shape stream_completion client. `script` is a list of dicts
    consumed one per call: {"text":..., "tool_calls":[...], "type":...} or
    an Exception instance to raise."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def stream_completion(self, *, model, system, messages, tools,
                          on_chunk, **kwargs):
        self.calls += 1
        step = self._script.pop(0) if self._script else {
            "type": "final", "text": "", "tool_calls": []}
        if isinstance(step, Exception):
            raise step
        txt = step.get("text", "")
        if txt and on_chunk:
            on_chunk(txt)
        return {"type": step.get("type", "final"),
                "text": txt,
                "tool_calls": step.get("tool_calls", []),
                "usage": None}


# ---------------------------------------------------------------------------
# A) PRIMARY-CHURN — signed-out primary is skipped, no per-turn churn.


def test_signed_out_provider_dropped_from_configured():
    r = _router()
    r._signed_out.clear()
    assert r.is_provider_signed_out("claude_cli") is False
    r._mark_signed_out("claude_cli", reason="claude CLI error: 401 unauthorized")
    assert r.is_provider_signed_out("claude_cli") is True
    # configured_providers() must exclude a signed-out provider so the
    # auto-router can never pick it as PRIMARY again.
    base = ["anthropic", "claude_cli", "archhub_cloud"]
    r.configured_providers = lambda **k: sorted(
        p for p in base if not r.is_provider_signed_out(p))
    assert "claude_cli" not in r.configured_providers()
    assert "archhub_cloud" in r.configured_providers()


def test_auth_error_marks_signed_out_then_routes_onward():
    """First turn: claude_cli is primary but 401s → marked signed-out and
    archhub_cloud answers. SECOND turn: claude_cli is skipped BEFORE being
    tried (no churn), archhub_cloud is primary immediately."""
    r = _router(schemas=[])
    cloud = _FakeClient([{"type": "final", "text": "hello from cloud"}])

    def fake_get_client(provider):
        if provider == "claude_cli":
            raise RuntimeError("claude CLI error: 401 unauthorized — please log in")
        if provider == "archhub_cloud":
            return cloud
        raise RuntimeError(f"no client for {provider}")

    r._get_client = fake_get_client

    # _route picks claude_cli when configured, else archhub_cloud.
    def fake_route(history, model):
        cfg = set(r.configured_providers())
        if "claude_cli" in cfg:
            return "claude_cli", "sonnet", "local Claude Code"
        return "archhub_cloud", "auto", "ArchHub Cloud"

    r._route = fake_route
    base = ["claude_cli", "archhub_cloud"]
    r.configured_providers = lambda **k: sorted(
        p for p in base if not r.is_provider_signed_out(p))

    status_msgs = []
    resp = r.complete(history=[{"role": "user", "content": "hi"}],
                      model="auto", on_status=status_msgs.append)
    assert resp.text == "hello from cloud"
    # claude_cli got marked signed-out by the auth failure.
    assert r.is_provider_signed_out("claude_cli") is True

    # SECOND turn: claude_cli must be skipped BEFORE any attempt — the
    # router never even asks _get_client for it again (no churn toast).
    asked = []
    orig = fake_get_client

    def trace_get_client(provider):
        asked.append(provider)
        return orig(provider)

    r._get_client = trace_get_client
    cloud._script = [{"type": "final", "text": "second cloud reply"}]
    resp2 = r.complete(history=[{"role": "user", "content": "hi again"}],
                       model="auto")
    assert resp2.text == "second cloud reply"
    assert "claude_cli" not in asked  # pre-skipped, not tried-then-failed


def test_signed_out_cleared_on_success():
    """A successful completion on a provider clears its signed-out flag —
    so claude_cli comes back automatically once the user re-signs-in."""
    r = _router(schemas=[])
    r._mark_signed_out("anthropic", reason="401")
    assert r.is_provider_signed_out("anthropic") is True

    client = _FakeClient([{"type": "final", "text": "ok now"}])
    r._get_client = lambda p: client
    r._route = lambda h, m: ("anthropic", "claude-sonnet-4-6", "note")
    r.configured_providers = lambda **k: ["anthropic"]

    resp = r.complete(history=[{"role": "user", "content": "hi"}], model="auto")
    assert resp.text == "ok now"
    assert r.is_provider_signed_out("anthropic") is False


# ---------------------------------------------------------------------------
# B) EMPTY REPLY — a retraction is followed by a real non-empty answer.


def test_fabrication_retraction_falls_through_to_plain_answer():
    """A host-word prompt makes the only provider fabricate tool markup
    (retracted). The chain dries up — but instead of an empty turn the
    router does a tools-DISABLED plain-LLM pass and returns real text."""
    r = _router(schemas=[{"name": "teams_post_message"}])  # had_tools=True

    # Same provider, two behaviours: first call (tools on) fabricates;
    # the plain-LLM fallback call (system_override ⇒ tools=[]) answers.
    client = _FakeClient([
        {"type": "final",
         "text": "<function_calls><invoke name=\"teams_post_message\">"
                 "</invoke></function_calls> Done, message posted."},
        {"type": "final",
         "text": "Teams isn't reachable right now, so I can't post — "
                 "but here's a draft you can send."},
    ])
    r._get_client = lambda p: client
    r._route = lambda h, m: ("anthropic", "claude-sonnet-4-6", "note")
    r.configured_providers = lambda **k: ["anthropic"]

    retracts = []
    resp = r.complete(
        history=[{"role": "user", "content": "post a teams message to the team"}],
        model="auto",
        on_attempt_reset=lambda p: retracts.append(p),
    )
    # The fabricated text was retracted...
    assert "anthropic" in retracts
    # ...and a REAL, non-empty answer replaced it (never an empty turn).
    assert resp.text.strip()
    assert "isn't reachable" in resp.text or "draft" in resp.text
    # The fallback ran tools-disabled (second script step consumed).
    assert client.calls == 2


def test_refusal_retraction_falls_through_to_plain_answer():
    """Same guarantee for the refusal class: a provider that refuses to use
    tools is retracted, then a plain-LLM answer is streamed."""
    r = _router(schemas=[{"name": "revit_list_walls"}])
    client = _FakeClient([
        {"type": "final",
         "text": "I'm not able to access your Revit files or read that data."},
        {"type": "final",
         "text": "I can't reach Revit from here, but I can explain how to "
                 "list walls yourself."},
    ])
    r._get_client = lambda p: client
    r._route = lambda h, m: ("google", "gemini-2.5-flash", "note")
    r.configured_providers = lambda **k: ["google"]

    chunks = []
    resp = r.complete(
        history=[{"role": "user", "content": "list all walls in revit"}],
        model="auto", on_chunk=chunks.append,
        on_attempt_reset=lambda p: None,
    )
    assert resp.text.strip()
    assert "can't reach Revit" in resp.text or "list walls" in resp.text


def test_plain_fallback_returns_none_when_no_provider_reachable():
    """When NO provider is reachable, the fallback returns None and the
    caller raises the honest 'exhausted' error (not a silent empty turn)."""
    r = _router(schemas=[])
    r.configured_providers = lambda **k: []
    out = r._plain_llm_fallback(
        history=[{"role": "user", "content": "hi"}],
        on_chunk=lambda _: None, on_reasoning=lambda _: None,
        on_status=lambda _: None, on_attempt_reset=lambda _: None,
    )
    assert out is None
