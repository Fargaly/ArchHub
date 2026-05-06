/**
 * Provider router.
 *
 * Maps a requested `model` string to the upstream URL + auth headers we
 * forward to. Anthropic and Google don't speak OpenAI shape natively;
 * for those we route through OpenRouter (which translates), so the
 * relay always speaks one wire format regardless of underlying vendor.
 * If a firm prefers direct billing with a vendor, set the matching
 * `*_key` on their firm row and we'll prefer that path — but body
 * transformation for direct Anthropic/Gemini is intentionally out of
 * scope for v0; OpenRouter handles it for us.
 */
import type { RelayFirm } from "./supabase.js";

export interface UpstreamTarget {
  provider: "anthropic" | "openai" | "google" | "openrouter";
  url: string;
  headers: Record<string, string>;
  /** Optional: rewrite body.model to this before forwarding (used to
   *  strip the "openai/" prefix when going direct to api.openai.com). */
  rewriteModel?: string;
}

const OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions";
const OPENAI_BASE = "https://api.openai.com/v1/chat/completions";

export function routeModel(model: string, firm: RelayFirm): UpstreamTarget | { error: string } {
  const m = model.toLowerCase();

  // Direct OpenAI: shape is identical, just swap base URL.
  if ((m.startsWith("openai/") || m.startsWith("gpt-")) && firm.openai_key) {
    // Strip optional "openai/" prefix so api.openai.com gets a clean model id.
    const cleanModel = m.startsWith("openai/") ? model.slice("openai/".length) : model;
    return {
      provider: "openai",
      url: OPENAI_BASE,
      headers: {
        Authorization: `Bearer ${firm.openai_key}`,
        "Content-Type": "application/json",
      },
      rewriteModel: cleanModel,
    };
  }

  // Anthropic, Google, and the long tail all go through OpenRouter — it
  // accepts model strings like "anthropic/claude-3-5-sonnet" and
  // "google/gemini-2.0-flash" verbatim and translates the body shape.
  const key = firm.openrouter_key;
  if (!key) return { error: "firm has no upstream key configured for this model" };
  return {
    provider: m.startsWith("anthropic/") || m.startsWith("claude-")
      ? "anthropic"
      : m.startsWith("google/") || m.startsWith("gemini-")
      ? "google"
      : "openrouter",
    url: OPENROUTER_BASE,
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      // OpenRouter attribution headers (analytics only).
      "HTTP-Referer": "https://archhub.app",
      "X-Title": "ArchHub Relay",
    },
  };
}

/**
 * If the routed target asked us to rewrite the model id (OpenAI direct
 * path strips its "openai/" prefix), apply that to the request body.
 */
export function maybeRewriteModel(target: UpstreamTarget, body: Record<string, unknown>): Record<string, unknown> {
  if (target.rewriteModel) return { ...body, model: target.rewriteModel };
  return body;
}
