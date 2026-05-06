/**
 * GET /v1/me — identity + usage snapshot for the calling user.
 *
 * Used by ArchHub's Settings → Firm Relay panel to confirm a token works
 * and show "X / Y tokens used this month" before the architect makes a
 * real request. Cheap call: one auth check + one view read.
 */
export const config = { runtime: "nodejs" };

import { getUserFromToken, getFirmKey, getMonthlyUsage } from "../../lib/supabase.js";

export default async function handler(req: Request): Promise<Response> {
  if (req.method !== "GET") {
    return json({ error: "method_not_allowed" }, 405);
  }
  const auth = req.headers.get("authorization") ?? "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : null;
  if (!token) return json({ error: "missing_bearer_token" }, 401);

  const user = await getUserFromToken(token);
  if (!user) return json({ error: "invalid_token" }, 401);

  const firm = await getFirmKey(user.firm_id);
  if (!firm) return json({ error: "firm_not_found" }, 401);

  const used = await getMonthlyUsage(firm.id);

  return json({
    user: { id: user.id, email: user.email, role: user.role },
    firm: { id: firm.id, name: firm.name, plan: firm.plan_tier },
    usage_this_month: used,
    monthly_token_cap: firm.monthly_token_cap,
  });
}

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}
