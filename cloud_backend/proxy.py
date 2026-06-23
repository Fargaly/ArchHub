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

    # ── AI-mode gate (Model C, founder 2026-05-31) ───────────────────
    # Each workspace chooses how AI is powered:
    #
    #   byo_key (default) — the user pastes their OWN provider key in the
    #     desktop. The hosted proxy does NOT serve their inference and
    #     NEVER decrements a hosted credit: there is no hosted limit, the
    #     user's key carries it. We return an honest byo_key_required 402
    #     so the client falls back to the local key.
    #
    #   hosted — WE run the LLM, metered against credit packs. Requires a
    #     paid plan + the global PROXY_LIVE switch (so accidental traffic
    #     can't burn the dev balance before the founder funds upstream
    #     balances). At 0 credits we return an honest out_of_credits 402
    #     prompting a top-up; otherwise one credit is decremented per
    #     conversation turn at end-of-stream.
    plan = (user.get("plan") or "trial").lower().strip()
    ai_mode = db.ai_mode_for_actor(user)
    actor = "company" if user.get("current_company_id") else "user"

    if ai_mode != "hosted":
        # byo_key (or anything unrecognised → default byo_key). Historically
        # this returned a 402 byo_key_required and the user was stuck until
        # they pasted a key. NEW (founder 2026-06-22): serve a strong FREE
        # model BY DEFAULT via our cloud so the composer just works, zero
        # config — no credit touched, no key needed by the user. The free
        # provider's key lives server-side (one key serves everyone).
        #
        # The free tier is still metered against the per-actor `msg_used`
        # fair-use ceiling (the quota gate above already ran), but never
        # touches hosted credits. BYO + hosted paths are untouched and win
        # when the user configures them.
        if config.free_default_available():
            # Per-user DAILY free cap (shared-key budget guard). One user can't
            # exhaust the shared founder key for everyone: over the cap we return
            # an honest 402 free_daily_cap (BYO + hosted still work; resets next
            # UTC day). cap<=0 disables it. Meters ONLY the free path.
            cap = config.free_daily_cap()
            if cap > 0:
                used_today = db.free_messages_today(user["id"])
                if used_today >= cap:
                    raise HTTPException(
                        status_code=402,
                        detail={
                            "error": "free_daily_cap",
                            "ai_mode": ai_mode,
                            "plan":  plan,
                            "free_used_today": used_today,
                            "free_daily_cap":  cap,
                            "reason": (
                                "You've used today's free messages "
                                f"({used_today}/{cap}). The free default "
                                "resets tomorrow — or paste your own provider "
                                "key (BYO) / switch to Hosted AI to keep going "
                                "now."),
                            "upgrade_url": f"{config.PUBLIC_URL.rstrip('/')}/upgrade",
                        },
                    )
            return _serve_free_default(user=user, body=body)
        # Free tier not configured (no provider key / switch off): fall back
        # to the honest BYO message so a missing free key never breaks the
        # box — BYO still works, and the founder funds the free key to flip
        # the zero-config default on.
        raise HTTPException(
            status_code=402,
            detail={
                "error": "byo_key_required",
                "ai_mode": ai_mode,
                "plan":  plan,
                "free_default": "unavailable",
                "reason": ("This workspace runs in BYO-key mode — paste "
                           "your own provider key in ArchHub → Settings → "
                           "LLM, or switch the workspace to Hosted AI to "
                           "use credits. (The free default model is not "
                           "configured on this server yet.)"),
                "upgrade_url": f"{config.PUBLIC_URL.rstrip('/')}/upgrade",
            },
        )

    # Hosted mode from here. Gate on plan + the global live switch.
    if not config.PROXY_LIVE or plan not in config.PROXY_ENABLED_PLANS:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "hosted_unavailable",
                "ai_mode": "hosted",
                "plan":  plan,
                "proxy_live":   config.PROXY_LIVE,
                "allowed_plans": sorted(config.PROXY_ENABLED_PLANS),
                "reason": ("Hosted AI is in private beta or your plan isn't "
                           "eligible yet. Paste your own provider key in "
                           "ArchHub → Settings → LLM (BYO-key mode) to keep "
                           "working while we onboard hosted customers."),
                "upgrade_url": f"{config.PUBLIC_URL.rstrip('/')}/upgrade",
            },
        )

    # Hosted credit gate — honest 402 at zero, prompting a top-up.
    credits = db.credit_balance_for_actor(user)
    if credits <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "out_of_credits",
                "ai_mode": "hosted",
                "actor": actor,
                "credit_balance": 0,
                "credit_pack": dict(config.CREDIT_PACK),
                "reason": ("You're out of hosted-AI credits. Top up a pack "
                           f"(${config.CREDIT_PACK['price_usd']} = "
                           f"{config.CREDIT_PACK['messages']:,} messages) to "
                           "keep using Hosted AI — or switch the workspace "
                           "to BYO-key mode."),
                "topup_url": f"{config.PUBLIC_URL.rstrip('/')}/billing/credits",
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
        # We only reach here in hosted mode (byo_key / out-of-credits are
        # rejected before the stream starts), so spend ONE hosted credit
        # per conversation turn — Model C bills per-turn, not per HTTP
        # call, because a tool-use loop is many calls. The legacy
        # msg_used bump stays for the fair-use ceiling + usage analytics.
        db.consume_credit_for_actor(user, 1)
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
def list_models(*, user: dict) -> dict:
    """OpenAI-compatible model list for /v1/models.

    Always advertises the FREE DEFAULT model when it's available + the
    workspace is not in hosted mode — so a no-key client sees a usable
    model (not an empty list / 402) and selects it by default. Hosted
    workspaces additionally see the configured upstream models.
    """
    ai_mode = db.ai_mode_for_actor(user)
    models: list[dict] = []
    free_on = (ai_mode != "hosted") and config.free_default_available()
    # ONE-SYSTEM (#64): advertise the model the free path will ACTUALLY serve
    # (the shared selector's choice — Gemini today, NVIDIA when keyed), not the
    # static config default which can differ from the reachable provider.
    free_model = config.free_selected_model() if free_on else None
    if free_on:
        models.append({
            "id": free_model,
            "object": "model",
            "owned_by": "archhub-free",
            "archhub_tier": "free-default",
            "archhub_default": True,
        })
    if ai_mode == "hosted":
        for m in _COST_PER_MTOK_USD:
            models.append({"id": m, "object": "model",
                            "owned_by": "archhub-hosted",
                            "archhub_tier": "hosted"})
    return {"object": "list", "data": models,
            "archhub_free_default": free_on,
            "archhub_default_model": free_model}


# ---------------------------------------------------------------------------
def _serve_free_default(*, user: dict, body: dict) -> StreamingResponse:
    """Serve the FREE DEFAULT model via our cloud (zero-config, no key).

    Proxies to a free OpenAI-compatible endpoint (Groq / OpenRouter /
    Google free tier — see config.FREE_PROVIDER) using a server-side key.
    No hosted credit is touched; the free tier is metered ONLY against the
    legacy per-actor `msg_used` fair-use counter (the quota gate already
    ran in chat_completions). The user pays nothing and configures nothing.
    """
    # Force the server-chosen free model — the client's requested model
    # (often "auto" or a paid model id) is overridden so a no-key user can
    # never aim our free key at an arbitrary/expensive upstream model.
    # ONE-SYSTEM (#64): the model id comes from the shared selector so it
    # always matches the provider _stream_free will actually call (Gemini
    # today, NVIDIA when keyed) — never a stale static default.
    model = config.free_selected_model()
    out_body = {**body, "model": model}
    upstream = _stream_free(model, out_body)

    async def iter_with_meter() -> AsyncIterator[bytes]:
        async for chunk in upstream:
            yield chunk
        # End-of-stream: bump the fair-use counter only. NO hosted credit.
        try:
            db.increment_usage_for_actor(user, 1)
        except Exception:
            pass
        try:
            db.log_usage(user["id"], model=f"free:{model}",
                          input_toks=0, output_toks=0, cost_micros=0)
        except Exception:
            pass

    return StreamingResponse(iter_with_meter(),
                              media_type="text/event-stream",
                              headers={
                                  "Cache-Control": "no-cache",
                                  "X-Accel-Buffering": "no",
                                  "X-ArchHub-Tier": "free-default",
                                  "X-ArchHub-Model": model,
                              })


def _embedded_error_in_chunk(raw: bytes) -> Optional[dict]:
    """Detect an OpenRouter/OpenAI-style error carried INSIDE a 200 stream
    body, and return the parsed error dict if found (else None).

    The class this catches (live curl, 2026-06-23): a model that is no longer
    free is returned by OpenRouter as a 200 response whose SSE body is a single
    JSON object {"error":{"code":404,"message":"...unavailable for free..."}}
    — the HTTP status is 200, so a status-only rotation never fires and the
    client gets the error as if it were content.

    We scan the chunk's `data:` SSE lines (and the bare body, for non-SSE error
    responses) for a top-level `error` object OR an embedded `code` >= 400.
    Returns the error dict on a hit so the caller can rotate to the next free
    candidate. A normal content delta (choices/delta/content) never matches."""
    if not raw:
        return None

    def _check_obj(d: object) -> Optional[dict]:
        if not isinstance(d, dict):
            return None
        # OpenAI/OpenRouter error shape: {"error": {"code": .., "message": ..}}
        err = d.get("error")
        if isinstance(err, dict):
            return err
        if isinstance(err, str) and err:
            return {"message": err}
        # An embedded non-2xx status code at the top level (some gateways put
        # {"code": 404, "message": "..."} without an "error" wrapper).
        code = d.get("code")
        try:
            if code is not None and int(code) >= 400:
                return {"code": int(code),
                        "message": d.get("message") or "upstream error"}
        except (TypeError, ValueError):
            pass
        return None

    # Try each SSE `data:` payload first, then the whole chunk as a fallback
    # (covers a non-SSE JSON error body returned under a 200).
    candidates_text: list[bytes] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith(b"data:"):
            payload = line[5:].strip()
            if payload and payload != b"[DONE]":
                candidates_text.append(payload)
    candidates_text.append(raw.strip())
    for payload in candidates_text:
        try:
            d = json.loads(payload)
        except Exception:
            continue
        hit = _check_obj(d)
        if hit is not None:
            return hit
    return None


def _chunk_has_content(raw: bytes) -> bool:
    """True iff a chunk carries a real content delta/choice (so it is safe to
    commit to streaming this candidate). Used to confirm a candidate is
    actually producing output before we stream it through."""
    if not raw:
        return False
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            continue
        try:
            d = json.loads(payload)
        except Exception:
            # Non-JSON SSE data we can't classify — treat as content (the
            # upstream is talking; don't discard it).
            return True
        if isinstance(d, dict) and (d.get("choices") or d.get("delta")
                                    or d.get("content")):
            return True
    return False


async def _stream_free(model: str, body: dict) -> AsyncIterator[bytes]:
    """Forward to the SELECTED free OpenAI-compatible provider, ROTATING
    across the free pool on a rate-limit / 4xx OR an IN-BODY error.

    ONE-SYSTEM (#64): the candidate list comes from the shared
    config.free_model_rotation() — its HEAD is exactly select_free_model()
    (OpenRouter when the founder's key is set, else NVIDIA / Gemini), and for
    OpenRouter its TAIL is the rest of the CURRENT `:free` pool (live-enumerated
    pricing==0) on the SAME key/base.

    Rotation fires on EITHER signal:
      1. HTTP 4xx status (throttled, quota, model unavailable) — the legacy path.
      2. An IN-BODY error (2026-06-23 fix): OpenRouter returns a no-longer-free
         model as a 200 whose SSE body is {"error":{"code":404,...}}. We PEEK
         each candidate's first chunk(s) BEFORE streaming it to the client; if
         the peeked body carries an error object (or an embedded code >= 400),
         the candidate is treated as FAILED and we rotate to the next. Only the
         FIRST candidate that yields a real content delta is streamed through
         (its peeked chunks are replayed first so nothing is lost).

    If EVERY candidate fails, the LAST candidate's body is streamed through so
    the client gets an honest error instead of silence. The server-side key is
    read from config only and is NEVER logged."""
    candidates = config.free_model_rotation()
    if not candidates:
        # Nothing reachable via the selector — preserve the legacy single-shot
        # behaviour (degrade honestly rather than crash).
        candidates = [{
            "provider": config.FREE_PROVIDER,
            "base_url": config.FREE_PROVIDER_BASE_URL,
            "model":    model,
            "key":      config.free_provider_key(),
        }]

    # How many leading chunks to peek for an in-body error before committing.
    # The error body is the FIRST (usually only) chunk; a couple covers a slow
    # provider that prefixes a role-only delta. Kept small so latency is unhurt.
    _PEEK_CHUNKS = 4

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        for idx, cand in enumerate(candidates):
            cand_model = cand.get("model") or model
            out_body = {**body, "model": cand_model, "stream": True}
            base = (cand.get("base_url") or config.FREE_PROVIDER_BASE_URL or "")
            url = f"{base.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json"}
            key = cand.get("key")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            # OpenRouter recommends (optional) attribution headers; harmless else.
            if cand.get("provider") == "openrouter":
                headers["HTTP-Referer"] = config.PUBLIC_URL
                headers["X-Title"] = "ArchHub"
            is_last = idx == len(candidates) - 1
            async with client.stream(
                "POST", url, headers=headers, json=out_body,
            ) as resp:
                # (1) HTTP-status rotation (legacy) — drain + try next unless last.
                status_code = getattr(resp, "status_code", 200)
                if 400 <= status_code < 500 and not is_last:
                    try:
                        await resp.aread()
                    except Exception:
                        pass
                    continue

                # (2) IN-BODY error peek. Buffer the leading chunks and inspect
                # them for an embedded error object / code>=400 BEFORE streaming
                # anything to the client. We hold a SINGLE iterator over the
                # response body (httpx raises StreamConsumed if aiter_bytes is
                # restarted) and continue from it once we commit.
                body_iter = resp.aiter_bytes().__aiter__()
                peeked: list[bytes] = []
                in_body_error = False
                async for chunk in body_iter:
                    peeked.append(chunk)
                    if _embedded_error_in_chunk(chunk) is not None:
                        in_body_error = True
                        break
                    if _chunk_has_content(chunk):
                        break
                    if len(peeked) >= _PEEK_CHUNKS:
                        break

                if in_body_error and not is_last:
                    # This candidate carried an error in its 200 body — treat as
                    # failed and rotate. Drain the rest so the conn releases.
                    try:
                        await resp.aread()
                    except Exception:
                        pass
                    continue

                # Commit to this candidate: replay the peeked chunks, then the
                # REMAINDER of the SAME iterator (never a fresh aiter_bytes()).
                # For the LAST candidate we stream its body even if it errored —
                # an honest error body beats silence.
                for c in peeked:
                    yield c
                async for chunk in body_iter:
                    yield chunk
                return


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
