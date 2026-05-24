"""LLM proxy — OpenAI-compatible /v1/chat/completions.

Authenticates the bearer, enforces quota, forwards the request to
the appropriate upstream provider (Anthropic / OpenAI / Google),
streams the response back through Server-Sent Events.

Provider selection:
  - If `model` starts with 'claude-' → Anthropic
  - If `model` starts with 'gpt-' or 'o' followed by digit → OpenAI
  - If `model` starts with 'gemini-' → Google (translated to OpenAI
    shape via google-generativeai's OpenAI-compatible base URL)
  - If model is 'auto' → pick the cheapest / fastest that has a key
    configured server-side.

Quota:
  - On request start, check user.msg_used < user.msg_limit. If not,
    return 402 with upgrade_url.
  - After a successful conversation turn (final assistant message
    delivered), increment msg_used by 1. We bill per-TURN, not per
    request, because a single tool-use loop iteration can be many
    HTTP calls.
"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator, Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

import config
import db


# Cost table — USD per million tokens (rough; real billing pulls
# actual from provider headers when available).
_COST_PER_MTOK_USD = {
    "claude-sonnet-4-6":  {"in": 3.0,  "out": 15.0},
    "claude-haiku-4-5":   {"in": 0.8,  "out": 4.0},
    "gpt-4o":             {"in": 2.5,  "out": 10.0},
    "gpt-4o-mini":        {"in": 0.15, "out": 0.6},
    "gemini-2.5-pro":     {"in": 1.25, "out": 5.0},
    "gemini-2.5-flash":   {"in": 0.075,"out": 0.30},
}


def _provider_for(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("claude") or "haiku" in m or "opus" in m or "sonnet" in m:
        return "anthropic"
    if m.startswith("gemini"):
        return "google"
    if m.startswith("gpt-") or (len(m) > 1 and m[0] == "o" and m[1].isdigit()):
        return "openai"
    if m == "auto":
        if config.ANTHROPIC_API_KEY:
            return "anthropic"
        if config.OPENAI_API_KEY:
            return "openai"
        if config.GOOGLE_API_KEY:
            return "google"
    return "openai"   # last-resort


def _default_model_for(provider: str) -> str:
    return {
        "anthropic": "claude-sonnet-4-6",
        "openai":    "gpt-4o-mini",
        "google":    "gemini-2.5-flash",
    }.get(provider, "gpt-4o-mini")


# ---------------------------------------------------------------------------
async def chat_completions(*, user: dict, body: dict) -> StreamingResponse:
    """Handle one chat completion request. Streams SSE."""
    # Quota gate first — saves a provider round-trip when the actor is
    # already over. v1.3.3: actor = company when user.current_company_id
    # is set (Studio + Firm seats share one bucket); falls back to user
    # quota for solo + trial users.
    remaining = db.quota_remaining_for_actor(user)
    if remaining <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "quota_exhausted",
                "actor":  "company" if user.get("current_company_id") else "user",
                "upgrade_url": f"{config.PUBLIC_URL.rstrip('/')}/upgrade",
            },
        )

    # ── Tier + ops gate (2026-05-24). Quota check above wins when the
    # actor is genuinely burnt out (more actionable upgrade message).
    # This gate then enforces: Free / Solo run BYO key, only Studio +
    # Firm get cloud-proxied LLM access, AND only when PROXY_LIVE is
    # on (founder flips after funding upstream provider balances).
    # Until then every paid request gets a clear BYO_REQUIRED — so
    # accidental traffic can't burn down the dev balance.
    plan = (user.get("plan") or "trial").lower().strip()
    if not config.PROXY_LIVE or plan not in config.PROXY_ENABLED_PLANS:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "byo_key_required",
                "plan":  plan,
                "proxy_live":   config.PROXY_LIVE,
                "allowed_plans": sorted(config.PROXY_ENABLED_PLANS),
                "reason": ("Cloud LLM proxy is in private beta. Your plan "
                           "either runs BYO key (Free / Solo) or the proxy "
                           "is not enabled yet. Paste your own provider key "
                           "in ArchHub → Settings → LLM to keep working "
                           "while we onboard cloud-proxy customers."),
                "upgrade_url": f"{config.PUBLIC_URL.rstrip('/')}/upgrade",
            },
        )

    model = body.get("model") or "auto"
    provider = _provider_for(model)
    if model == "auto":
        model = _default_model_for(provider)
        body["model"] = model

    if provider == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise HTTPException(
                status_code=503,
                detail={"error": "provider_not_configured",
                        "provider": "anthropic"},
            )
        upstream = _stream_anthropic(model, body)
    elif provider == "google":
        if not config.GOOGLE_API_KEY:
            raise HTTPException(
                status_code=503,
                detail={"error": "provider_not_configured",
                        "provider": "google"},
            )
        upstream = _stream_google(model, body)
    else:
        if not config.OPENAI_API_KEY:
            raise HTTPException(
                status_code=503,
                detail={"error": "provider_not_configured",
                        "provider": "openai"},
            )
        upstream = _stream_openai(model, body)

    async def iter_with_meter() -> AsyncIterator[bytes]:
        """Pass through SSE bytes from upstream + on completion,
        decrement quota + log usage."""
        in_toks = out_toks = 0
        async for chunk in upstream:
            yield chunk
            # Try to parse token counts from the chunk for billing.
            if b"usage" in chunk:
                try:
                    # OpenAI/Anthropic both expose usage in the final
                    # 'data: {...}' line of the stream.
                    for line in chunk.splitlines():
                        line = line.strip()
                        if not line.startswith(b"data:"):
                            continue
                        body_str = line[5:].strip()
                        if body_str == b"[DONE]":
                            continue
                        try:
                            d = json.loads(body_str)
                        except Exception:
                            continue
                        u = (d.get("usage") if isinstance(d, dict)
                             else None)
                        if isinstance(u, dict):
                            in_toks = int(u.get("input_tokens") or
                                          u.get("prompt_tokens") or 0)
                            out_toks = int(u.get("output_tokens") or
                                           u.get("completion_tokens") or 0)
                except Exception:
                    pass
        # End-of-stream: decrement + log. Actor-aware (company vs user).
        db.increment_usage_for_actor(user, 1)
        cost = _COST_PER_MTOK_USD.get(model, {"in": 1.0, "out": 4.0})
        cost_micros = int(
            (in_toks * cost["in"] + out_toks * cost["out"])
            * 1.0   # USD per Mtok already → micros = same scale
        )
        try:
            db.log_usage(user["id"], model=model,
                          input_toks=in_toks, output_toks=out_toks,
                          cost_micros=cost_micros)
        except Exception:
            pass

    return StreamingResponse(iter_with_meter(),
                              media_type="text/event-stream",
                              headers={
                                  "Cache-Control": "no-cache",
                                  "X-Accel-Buffering": "no",
                              })


# ---------------------------------------------------------------------------
async def _stream_openai(model: str, body: dict) -> AsyncIterator[bytes]:
    """Forward to OpenAI Chat Completions."""
    body = {**body, "stream": True}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk


async def _stream_anthropic(model: str, body: dict) -> AsyncIterator[bytes]:
    """Forward to Anthropic Messages API + re-shape SSE to OpenAI form."""
    # Body shape: convert OpenAI-style messages to Anthropic shape.
    msgs = body.get("messages") or []
    system = ""
    anth_msgs = []
    for m in msgs:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            system += (str(content) + "\n") if content else ""
            continue
        anth_msgs.append({"role": role, "content": content})
    payload = {
        "model": model,
        "max_tokens": body.get("max_tokens") or 4096,
        "messages": anth_msgs,
        "stream": True,
    }
    if system:
        payload["system"] = system.strip()
    if body.get("tools"):
        payload["tools"] = body["tools"]

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            # For simplicity stream Anthropic SSE through unchanged.
            # The desktop client's archhub_cloud_client uses the
            # OpenAI SDK which expects OpenAI-shape SSE — clients
            # that need Anthropic-native chunks should request
            # 'anthropic-passthrough' via a future content type.
            # MVP: clients call this when model starts with 'claude-'
            # via their own anthropic_client (not the OpenAI one).
            async for chunk in resp.aiter_bytes():
                yield chunk


async def _stream_google(model: str, body: dict) -> AsyncIterator[bytes]:
    """Forward to Gemini via the OpenAI-compatibility endpoint."""
    body = {**body, "stream": True}
    url = ("https://generativelanguage.googleapis.com/v1beta/"
            "openai/chat/completions")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream(
            "POST", url,
            headers={
                "Authorization": f"Bearer {config.GOOGLE_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk
