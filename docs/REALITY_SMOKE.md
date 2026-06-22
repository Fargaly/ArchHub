# Reality Smoke Test

`scripts/reality_smoke.py` is the **honest answer** to "is the production system alive RIGHT NOW?".

Unlike the in-repo unit tests, every probe hits a real surface — Fly.io, Stripe, GitHub, even the live Anthropic/OpenAI/Google APIs when you ask it to. There is no mocking. If a check returns `[OK]`, the dependency it targets is responsive.

The script runs in CI every 30 minutes (`.github/workflows/reality.yml`) and you can run it locally at any time:

```powershell
python scripts/reality_smoke.py            # human-readable
python scripts/reality_smoke.py --json     # machine-parseable
python scripts/reality_smoke.py --quiet    # failures + summary only
```

---

## Reading the output

Each check prints one of three statuses on its own line:

| Tag | Meaning |
|---|---|
| `[OK]` | The dependency answered correctly within the timeout. |
| `[FAIL: <reason>]` | The check ran and the dependency did not behave as expected. |
| `[SKIP: <reason>]` | The check was disabled (flag off) or its prerequisite is missing (no env var, `gh` CLI not installed, etc.). Skipped checks **never** fail the run. |

The last line is the only one you need to read in a hurry:

```
Reality check: 8/10 green · 2 failed · 6 skipped
```

- `green / total` — the count of `[OK]` checks over all non-skipped checks.
- `failed` — the count of `[FAIL]` checks. **If this is `0`, the script's exit code is `0`.**
- `skipped` — informational only.

The script's exit code is `1` if any non-skipped check failed, `0` otherwise. That is what the CI workflow keys off.

### JSON shape (`--json`)

The JSON output is stable and is the schema CI consumes:

```json
{
  "schema": "archhub.reality_smoke/1",
  "generated_at": "2026-05-13T12:00:00+00:00",
  "cloud_url":  "https://archhub-cloud.fly.dev",
  "agents_url": "https://archhub-agents.fly.dev",
  "flags":   { "stripe_check": false, "llm_check": false, "retry": 1 },
  "env":     { "STRIPE_SECRET_KEY": "<set>", "ANTHROPIC_API_KEY": "<unset>", ... },
  "summary": { "total_non_skipped": 10, "green": 8, "failed": 2,
               "skipped": 6, "exit_code": 1 },
  "checks":  [ { "name": "cloud.healthz", "category": "Cloud backend",
                 "status": "ok", "detail": "...", "duration_ms": 412 }, ... ]
}
```

**Secrets never appear in the JSON output.** The `env` block only reports `<set>` / `<unset>`. There is a regression test (`test_reality_smoke.py::TestJSONOutput::test_secrets_never_appear_in_json`) that scans the output for canary values.

---

## Common failure modes + fixes

### `cloud.healthz` — FAIL HTTP 404 / 503

The cloud_backend Fly app is not deployed, or has crashed.

- Run `flyctl status -a archhub-cloud` to see what's up.
- If the app is sleeping (Fly free tier), a single `/healthz` GET should wake it — the script retries with `--retry 2` in CI.
- First-boot? Give it 30 seconds — the SQLite migration runs synchronously on the first request and can time out.

### `cloud.billing_plans` — FAIL route not registered (404)

The `/v1/billing/plans` endpoint does not yet exist in `cloud_backend/main.py`. The script *expects* the deployed backend to publish a public read-only plans endpoint. Until that endpoint lands, this check will be red. The fix is server-side, not a misconfiguration.

### `cloud.register` — non-mutating against PROD (does NOT create users)

Root-cause fix (2026-06-22): this check used to POST a throwaway
`reality+smoketest<ts>@archhub.io` signup on **every** run. Against the live
Fly app — which the hourly cron (`reality.yml`) and post-deploy verify both
target — each run created a NEW real `users` row, so production accrued
hundreds of synthetic accounts and the founder cockpit's users/MRR/signups
numbers were junk.

Now, against a **prod** target (`archhub-cloud.fly.dev` / `*.archhub.io`,
detected by `_is_prod_target`), the check sends a deliberately **invalid** body
and accepts `400`/`422` as proof the route is wired — **no user is created**.
The full 202 magic-link probe runs only against a **non-prod** `--cloud-url`
(localhost / staging) or with the explicit `--register-live` opt-in; the
synthetic email it then uses keeps its `+smoketest` / `@archhub.io` markers so
`db.is_test_account_email` recognises it and the cockpit excludes / can purge
it.

To clean up the rows already accrued: open the Founder Cockpit → "Users by
plan" card → "Purge N test accounts" (calls the founder-gated
`POST /founder/api/purge-test-users` with `{confirm:true}`).

If you DO run a live register probe and see `502 email_send_failed`: the route
is up but `RESEND_API_KEY` is missing or the sending domain isn't verified.

- `flyctl secrets list -a archhub-cloud` and check `RESEND_API_KEY` exists.
- Resend dashboard → Domains → verify `archhub.io`.

### `agents.healthz` — FAIL heartbeat stale (N min old)

The agents 24/7 daemon stopped writing to `/data/agents/heartbeat.txt`.

- `flyctl logs -a archhub-agents` to inspect.
- The dispatcher loop should write every 60s; the threshold here is 5 min (300s) so two missed beats counts as down.

### `stripe.products` — FAIL Stripe rejected the key (401)

`STRIPE_SECRET_KEY` is wrong or revoked. Cycle it in the Stripe dashboard and re-set with `flyctl secrets set STRIPE_SECRET_KEY=sk_... -a archhub-cloud`.

### `github.ci_latest` — FAIL latest CI conclusion=failure

The latest run of `.github/workflows/test.yml` on `main` was red. Click the run in the Actions tab and triage.

### `github.release_matches_version` — FAIL VERSION=1.2.0 but latest tag=v1.1.0

You bumped `VERSION` but never published the release. Run the release workflow (`.github/workflows/release.yml`) or run `gh release create v1.2.0 ...` locally.

### `local.boot_log` — FAIL boot.log not found / too old

You haven't launched the desktop app in over 24h, or `boot.log` was deleted. Launch ArchHub from `Launch.bat` to write a fresh entry.

### `local.ai_runner_providers` — FAIL N providers (expected 4)

Someone removed or renamed a provider in `app/connectors/ai_runner.list_providers()`. The four expected providers are `openai`, `google`, `lmstudio`, `antigravity`.

---

## Silencing false positives

Each check is small and self-contained. If a check is wrong for your environment (e.g. you don't use Stripe yet, you don't have a release to compare to), the right move is **not** to mute the alert — it's to flip the check into a `[SKIP]` so the truth is preserved:

1. Skip a whole category by removing it from `CHECKS` in `scripts/reality_smoke.py`.
2. Skip an individual check temporarily by short-circuiting at the top:

   ```python
   @check("cloud.billing_plans", "Cloud backend")
   def check_cloud_billing_plans(args):
       return CheckResult("cloud.billing_plans", "Cloud backend",
                          STATUS_SKIP, "endpoint not yet implemented")
   ```

3. For "this check is failing because the dependency genuinely has no public answer yet" (e.g. `/v1/billing/plans` before the route ships), prefer `[SKIP]` over deletion. When the dependency catches up you flip the check back on with one line.

**Do not** delete checks just to make the dashboard go green — the whole point of this script is to refuse that move.

---

## Adding a new check

Each check is a single function annotated with `@check(name, category)`. The function takes the parsed CLI `argparse.Namespace` and returns a `CheckResult`. Three rules:

1. **Don't crash.** Catch exceptions and return `CheckResult(..., STATUS_FAIL, str(ex))`. The dispatcher catches stray exceptions too, but explicit handling produces better detail messages.
2. **Stdlib only.** Use `urllib.request` (via the `http_request()` helper) for HTTP. No `requests`, no `httpx` — the script must run inside Fly.io's minimal Python image with zero deps.
3. **Honour `args.stripe_check` / `args.llm_check`.** Probes that hit a paid API or that need an opt-in flag should `STATUS_SKIP` when the flag is off.

After writing the function, append it to the `CHECKS` list near the bottom of the file. Order in `CHECKS` is the order they print.

### Example

```python
@check("cloud.marketplace", "Cloud backend")
def check_cloud_marketplace(args):
    """GET /marketplace/listings → 200 with a `listings` array."""
    url = f"{args.cloud_url.rstrip('/')}/marketplace/listings"
    r = http_request(url)
    if r.status != 200:
        return CheckResult("cloud.marketplace", "Cloud backend",
                           STATUS_FAIL, f"HTTP {r.status}")
    js = r.json() or {}
    if not isinstance(js, dict) or "listings" not in js:
        return CheckResult("cloud.marketplace", "Cloud backend",
                           STATUS_FAIL, "no listings field")
    return CheckResult("cloud.marketplace", "Cloud backend",
                       STATUS_OK,
                       f"{len(js['listings'])} listings")
```

Then add a corresponding test in `tests/test_reality_smoke.py` that mocks the URL — the existing `patch_http()` helper makes this a one-liner.

---

## CI integration

`.github/workflows/reality.yml` runs the smoke script every 30 minutes on a cron schedule (`*/30 * * * *`) plus on manual `workflow_dispatch`. On failure it opens (or re-opens) **one** tracking issue labelled `reality-down` — the body is rewritten on each failure to reflect the current failing checks. On the next green run that issue is automatically closed.

- The workflow uses the default `GITHUB_TOKEN` — no extra secrets to manage.
- Concurrency is gated to a single in-flight run (`concurrency: reality-smoke`), so overlapping cron runs can't race on the issue.
- The full JSON output of every run is uploaded as a `reality-smoke-<run_id>` artifact for 7 days. Inspect the JSON if you need the raw timestamps.

To check the latest cron run from a terminal:

```powershell
gh run list --workflow=reality.yml --limit 5
gh run view <run-id> --log
```
