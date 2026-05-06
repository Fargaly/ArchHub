/**
 * Local-dev seed: create a test firm + test user, return a usable
 * bearer token. Idempotent on email — re-runs reuse the existing user.
 *
 * Run with: `pnpm seed` (or `npx tsx scripts/seed-test-firm.ts`).
 * Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in env.
 */
import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SUPABASE_URL || !SERVICE_KEY) {
  console.error("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before running.");
  process.exit(1);
}

const TEST_EMAIL = process.env.SEED_EMAIL ?? "test-architect@archhub.local";
const TEST_PASSWORD = process.env.SEED_PASSWORD ?? "archhub-dev-only";
const FIRM_NAME = process.env.SEED_FIRM ?? "Test Studio";
const TOKEN_CAP = Number(process.env.SEED_CAP ?? 1000);

async function main(): Promise<void> {
  const sb = createClient(SUPABASE_URL!, SERVICE_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // 1. Firm row.
  const { data: firmRow, error: firmErr } = await sb
    .from("firms")
    .upsert(
      {
        name: FIRM_NAME,
        plan_tier: "studio",
        monthly_token_cap: TOKEN_CAP,
        // Plain-text in the column for local dev only — swap for Vault
        // before using a real key.
        openrouter_key_encrypted: process.env.OPENROUTER_API_KEY ?? null,
        anthropic_key_encrypted: process.env.ANTHROPIC_API_KEY ?? null,
        openai_key_encrypted: process.env.OPENAI_API_KEY ?? null,
        google_key_encrypted: process.env.GOOGLE_API_KEY ?? null,
      },
      { onConflict: "name" }
    )
    .select()
    .single();
  if (firmErr || !firmRow) throw new Error(`firm upsert failed: ${firmErr?.message}`);
  console.log(`firm: ${firmRow.id} (${firmRow.name})`);

  // 2. Auth user (admin API). Idempotent: getUserByEmail-equivalent then create.
  const { data: list } = await sb.auth.admin.listUsers();
  let userId = list?.users.find((u) => u.email === TEST_EMAIL)?.id;
  if (!userId) {
    const { data: created, error } = await sb.auth.admin.createUser({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
      email_confirm: true,
    });
    if (error || !created.user) throw new Error(`createUser failed: ${error?.message}`);
    userId = created.user.id;
  }

  // 3. Mirror row in public.users.
  const { error: uErr } = await sb.from("users").upsert(
    { id: userId, firm_id: firmRow.id, email: TEST_EMAIL, role: "owner" },
    { onConflict: "id" }
  );
  if (uErr) throw new Error(`users upsert failed: ${uErr.message}`);

  // 4. Sign in to get a JWT the user can paste into ArchHub.
  const anonKey = process.env.SUPABASE_ANON_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!anonKey) {
    console.warn("(set SUPABASE_ANON_KEY to also print a usable bearer token)");
    return;
  }
  const anon = createClient(SUPABASE_URL!, anonKey);
  const { data: session, error: signInErr } = await anon.auth.signInWithPassword({
    email: TEST_EMAIL,
    password: TEST_PASSWORD,
  });
  if (signInErr || !session.session) throw new Error(`signIn failed: ${signInErr?.message}`);

  console.log("\n--- paste into ArchHub Settings → Firm Relay ---");
  console.log(`Relay URL : http://localhost:3000/v1`);
  console.log(`Token     : ${session.session.access_token}`);
  console.log("------------------------------------------------\n");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
