/**
 * POST /v1/chat/completions — OpenAI-shape proxy.
 *
 * Authenticates the caller against Supabase, picks an upstream provider
 * based on the model name, streams the upstream response straight back
 * to the client (SSE passthrough — no buffering, because architects run
 * multi-stage pipelines that take minutes), and logs usage out-of-band.
 *
 * The handler runs on Vercel's Node runtime (not Edge) because the
 * @supabase/supabase-js client and our usage-logging are easier to
 * reason about with full Node primitives. Streaming still works fine —
 * Vercel pipes the Web ReadableStream we return.
 */
export const config = { runtime: "nodejs" };

import {
  getUserFromToken,
  getFirmKey,
  getMonthlyUsage,
  recordUsage,
  checkRateLimit,
} from "../../../lib/supabase.js";
import { routeModel, maybeRewriteModel } from "../../../lib/upstream.js";

export default async function handler(req: Request): Promise<Response> {
  if (req.method !== "POST") {
    return json({ error: "method_not_allowed" }, 405);
  }

  const auth = req.headers.get("authorization") ?? "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : null;
  if (!token) return json({ error: "missing_bearer_token" }, 401);

  const user = await getUserFromToken(token);
  if (!user) return json({ error: "invalid_token" }, 401);

  if (!checkRateLimit(user.id)) {
    return json({ error: "rate_limited" }, 429);
  }

  const firm = await getFirmKey(user.firm_id);
  if (!firm) return json({ error: "firm_not_found" }, 401);

  // Cap check: cheap monthly view lookup. The view aggregates the
  // partitioned `usage` table, so this is one indexed read.
  const used = await getMonthlyUsage(firm.id);
  if (used >= firm.monthly_token_cap) {
    return json({ error: "monthly_cap_exceeded", used, cap: firm.monthly_token_cap }, 402);
  }

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  const model = typeof body.model === "string" ? body.model : "";
  if (!model) return json({ error: "missing_model" }, 400);

  const route = routeModel(model, firm);
  if ("error" in route) return json({ error: route.error }, 400);

  const finalBody = maybeRewriteModel(route, body);
  const wantsStream = body.stream === true;
  const started = Date.now();

  const upstreamRes = await fetch(route.url, {
    method: "POST",
    headers: route.headers,
    body: JSON.stringify(finalBody),
  });

  // Mirror upstream errors verbatim — clients already understand them.
  if (!upstreamRes.ok) {
    const text = await upstreamRes.text();
    return new Response(text, {
      status: upstreamRes.status,
      headers: { "content-type": upstreamRes.headers.get("content-type") ?? "application/json" },
    });
  }

  if (wantsStream && upstreamRes.body) {
    // SSE passthrough. We tee the body so we can also count tokens for
    // logging without buffering the user-visible stream. The logging
    // branch resolves after the stream ends.
    const [forUser, forLog] = upstreamRes.body.tee();
    void logStreamUsage(forLog, {
      user_id: user.id,
      firm_id: firm.id,
      provider: route.provider,
      model,
      started,
    });
    return new Response(forUser, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
      },
    });
  }

  // Non-stream: parse once, log, return.
  const data = (await upstreamRes.json()) as {
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };
  await recordUsage({
    user_id: user.id,
    firm_id: firm.id,
    provider: route.provider,
    model,
    prompt_tokens: data.usage?.prompt_tokens ?? 0,
    completion_tokens: data.usage?.completion_tokens ?? 0,
    latency_ms: Date.now() - started,
  });
  return json(data, 200);
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Drain a teed SSE stream and emit a usage row when the final chunk
 * arrives. OpenAI-compatible streams emit a final chunk with `usage`
 * populated when `stream_options.include_usage = true` on OpenAI/OR; we
 * fall back to 0/0 if upstream didn't include it.
 */
async function logStreamUsage(
  stream: ReadableStream<Uint8Array>,
  ctx: { user_id: string; firm_id: string; provider: string; model: string; started: number }
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let prompt_tokens = 0;
  let completion_tokens = 0;
  let buf = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // Each SSE line starts with "data: ". Last non-[DONE] data line
      // with a `usage` field is what we want.
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          const obj = JSON.parse(payload) as { usage?: { prompt_tokens?: number; completion_tokens?: number } };
          if (obj.usage) {
            prompt_tokens = obj.usage.prompt_tokens ?? prompt_tokens;
            completion_tokens = obj.usage.completion_tokens ?? completion_tokens;
          }
        } catch {
          /* skip malformed line */
        }
      }
    }
  } catch (err) {
    console.error("stream tee read failed", err);
  }
  await recordUsage({
    user_id: ctx.user_id,
    firm_id: ctx.firm_id,
    provider: ctx.provider,
    model: ctx.model,
    prompt_tokens,
    completion_tokens,
    latency_ms: Date.now() - ctx.started,
  });
}
