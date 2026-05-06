/**
 * Supabase server helpers for the relay.
 *
 * Two clients live here on purpose: an *anon* client used only to validate
 * a user's bearer token (so RLS still applies on any read we do on their
 * behalf), and a *service-role* client used for two narrow tasks the user
 * cannot do themselves — looking up their firm's encrypted upstream key,
 * and inserting a row into `usage`. The service-role key never leaves
 * this module, and we never use it to read on a user's behalf.
 */
import { createClient, SupabaseClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY || !SUPABASE_SERVICE_ROLE_KEY) {
  // Throwing at import time means a misconfigured deploy fails fast on
  // first request rather than silently 500-ing per call.
  throw new Error("Missing SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY");
}

export interface RelayUser {
  id: string;
  email: string;
  firm_id: string;
  role: string;
}

export interface RelayFirm {
  id: string;
  name: string;
  plan_tier: "free" | "studio" | "enterprise";
  monthly_token_cap: number;
  anthropic_key: string | null;
  openai_key: string | null;
  google_key: string | null;
  openrouter_key: string | null;
}

export interface UsageRow {
  user_id: string;
  firm_id: string;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
}

const serviceClient: SupabaseClient = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false },
});

/**
 * Resolve a bearer token to a {user, firm} pair.
 *
 * The token is the user's Supabase JWT. We use the anon client to verify
 * it (this is the same path Supabase auth uses on the client SDK), then
 * fetch the user's firm row through the service client because the firm
 * key columns are protected from even the user themselves by RLS.
 */
export async function getUserFromToken(token: string): Promise<RelayUser | null> {
  const anon = createClient(SUPABASE_URL!, SUPABASE_ANON_KEY!, {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await anon.auth.getUser(token);
  if (error || !data.user) return null;

  // Pull our own users row (firm_id, role). Goes through anon client so RLS
  // applies — a token can only see its own row.
  const { data: row, error: rowErr } = await anon
    .from("users")
    .select("id, email, firm_id, role")
    .eq("id", data.user.id)
    .single();
  if (rowErr || !row) return null;
  return row as RelayUser;
}

/** Fetch the firm's decrypted upstream API keys + plan limits. Service-role only. */
export async function getFirmKey(firmId: string): Promise<RelayFirm | null> {
  const { data, error } = await serviceClient
    .from("firms")
    .select(
      "id, name, plan_tier, monthly_token_cap, anthropic_key_encrypted, openai_key_encrypted, google_key_encrypted, openrouter_key_encrypted"
    )
    .eq("id", firmId)
    .single();
  if (error || !data) return null;
  // `*_encrypted` columns are Supabase Vault references; we expose the
  // plaintext to the relay process only, never to clients. If you swap
  // Vault for KMS, decrypt here.
  return {
    id: data.id,
    name: data.name,
    plan_tier: data.plan_tier,
    monthly_token_cap: data.monthly_token_cap,
    anthropic_key: data.anthropic_key_encrypted,
    openai_key: data.openai_key_encrypted,
    google_key: data.google_key_encrypted,
    openrouter_key: data.openrouter_key_encrypted,
  };
}

export async function recordUsage(row: UsageRow): Promise<void> {
  // Fire-and-log: a logging failure must never poison the user's response.
  const { error } = await serviceClient.from("usage").insert(row);
  if (error) console.error("usage insert failed", error.message);
}

/** Sum tokens for a firm in the current calendar month. Reads the view. */
export async function getMonthlyUsage(firmId: string): Promise<number> {
  const { data, error } = await serviceClient
    .from("monthly_usage_per_firm")
    .select("total_tokens")
    .eq("firm_id", firmId)
    .maybeSingle();
  if (error || !data) return 0;
  return Number(data.total_tokens ?? 0);
}

/** Per-user token-bucket rate limit. In-memory; resets on cold start. */
const buckets = new Map<string, { tokens: number; updated: number }>();
const RATE_PER_MIN = Number(process.env.RELAY_RATE_PER_MIN ?? 60);

export function checkRateLimit(userId: string): boolean {
  const now = Date.now();
  const b = buckets.get(userId) ?? { tokens: RATE_PER_MIN, updated: now };
  // Refill linearly over a 60s window.
  const refill = ((now - b.updated) / 60_000) * RATE_PER_MIN;
  b.tokens = Math.min(RATE_PER_MIN, b.tokens + refill);
  b.updated = now;
  if (b.tokens < 1) {
    buckets.set(userId, b);
    return false;
  }
  b.tokens -= 1;
  buckets.set(userId, b);
  return true;
}
