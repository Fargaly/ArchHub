# Cloud Deploy — ArchHub Autonomous Agents

A separate Fly.io app, `archhub-agents`, that runs the ArchHub
autonomous workforce 24/7. Different from `cloud_backend`
(`archhub-cloud`) on purpose: the agents are an internal company,
not a customer-facing API.

## What this gives you

- Eight role-scoped agents (eng, qa, rnd, docs, ops, telemetry,
  backlog, watcher) running every 60 seconds against Anthropic's
  Haiku 4.5 — cheap, fast, plenty for the kind of role-bounded
  outputs each department produces.
- A persistent `/data` volume holding the task queue, outputs,
  and logs across deploys + restarts.
- A `/healthz` and `/status` endpoint on port 8080 so the
  `cloud_backend` (or you, via `fly proxy`) can see what the
  daemon's been up to.
- Anthropic spend in the ~$5–15/mo range for the default cycle.

## Prerequisites

1. **Fly.io account** with `flyctl` installed.
   - Windows: `iwr https://fly.io/install.ps1 -useb | iex`
   - macOS:   `brew install flyctl`
   - Authenticate: `flyctl auth login`
2. **Anthropic API key** with credit on it
   (https://console.anthropic.com/settings/keys).

## One-command deploy

From the repo root:

```powershell
.\agents\deploy.ps1
```

The script is idempotent:

1. Creates `archhub-agents` if it doesn't exist.
2. Creates the `archhub_agents_data` 1 GB volume in `iad`
   if it doesn't exist.
3. Reads `ANTHROPIC_API_KEY` from `$env:ANTHROPIC_API_KEY` or
   prompts you for it, then sets it as a Fly secret.
4. Runs `flyctl deploy --config agents/fly.toml --remote-only`.
5. Prints the post-deploy commands.

Override region or app name:

```powershell
.\agents\deploy.ps1 -AppName my-agents -Region ord -ApiKey sk-ant-...
```

## CI deploy (the default — no laptop required)

`agents/deploy.ps1` is the manual escape hatch. The day-to-day path is
**automated**: every push to `main` that touches `agents/**` runs
[`.github/workflows/agents_deploy.yml`](../.github/workflows/agents_deploy.yml),
which:

1. **Smokes the build** — boots the *real* agents app in CI via
   [`scripts/agents_smoke.py`](../scripts/agents_smoke.py) and runs the actual
   `reality_smoke` `agents.healthz` + `agents.status` checks against it. A
   broken container never reaches Fly. (No Fly, no token needed for this gate —
   it's a self-contained boot of `agents.dashboard_endpoint.build_app`.)
2. **Deploys to Fly** — `flyctl deploy --config agents/fly.toml` via the
   `superfly/flyctl-actions/setup-flyctl` action, gated on the **`FLY_API_TOKEN`**
   repo secret. When the secret is absent the step logs a warning and skips
   (forks / pre-token state don't hard-fail).
3. **Verifies live** — re-runs `scripts/agents_smoke.py --url
   https://archhub-agents.fly.dev` against the freshly deployed machine so the
   reality probe is green **immediately post-deploy**, not only on the next
   hourly [`reality.yml`](../.github/workflows/reality.yml) cron.

### One-time setup of the deploy secret

The only manual step is minting a scoped deploy token (do this once):

```bash
fly tokens create deploy -a archhub-agents | gh secret set FLY_API_TOKEN -R Fargaly/ArchHub
```

After that, agents deploys ride main automatically. Trigger an ad-hoc deploy or
re-probe from the Actions tab via **workflow_dispatch** on *Agents deploy*.

### Smoke it locally too

The same smoke runs anywhere — handy before pushing, or to debug a Fly box:

```bash
# Boot the real app locally and check its health surface:
python scripts/agents_smoke.py --json
# Probe a live deploy directly:
python scripts/agents_smoke.py --url https://archhub-agents.fly.dev
```

Exit 0 means the agents container's `/healthz` + `/status` are healthy.

> Note: `agents_dispatch.yml` is a *different* workflow — it drains the task
> **queue** inside GitHub Actions. It does not deploy or touch the Fly machine;
> `agents_deploy.yml` owns the container's lifecycle.

## Verify the daemon is running

```bash
flyctl logs -a archhub-agents
```

You should see a `[cloud_runner] tick N: ...` line approximately
every 60 seconds, starting within a few seconds of the deploy
completing.

If the dashboard endpoint is exposed publicly (it is in the default
`fly.toml`), you can also hit `/healthz`:

```bash
flyctl proxy 8080 -a archhub-agents
# in another shell
curl http://localhost:8080/healthz
# {"status":"ok","last_heartbeat":"2026-05-13T...","cycles":17,"age_seconds":3}
```

`/status` returns a summary of every department, the pending queue
depth, completed-today count, and the 10 most recent task outputs.

## Cost estimate

| Component                       | Approx /mo |
| ------------------------------- | ---------- |
| Fly.io `shared-cpu-1x` 256 MB   | $0 (free tier covers 3 of these) |
| Fly.io 1 GB persistent volume   | $0.15/mo  |
| Anthropic Haiku 4.5 tokens      | $5–15/mo  |
| **Total**                       | **$5–16/mo** |

The Anthropic figure assumes ~10–30 task runs per day across all
departments at ~2–4 K tokens each. Haiku is $0.25/M input, $1.25/M
output. Worst case you bump to ~$30/mo if you tighten the cycle to
30 seconds or add heavier reasoning departments.

## Operations

**Tail logs**

```bash
flyctl logs -a archhub-agents
```

**Open the dashboard locally**

```bash
flyctl proxy 8080 -a archhub-agents
```

Then visit `http://localhost:8080/status`.

**Stop the daemon** (zero spend, zero work)

```bash
flyctl scale count 0 -a archhub-agents
```

**Restart it**

```bash
flyctl scale count 1 -a archhub-agents
```

**Switch model maps**

Edit `agents/anthropic_client.py` → `MODEL_MAP`. Redeploy with
`.\agents\deploy.ps1`. Single source of truth — no per-dept code
changes.

**Roll back to a previous release**

```bash
flyctl releases -a archhub-agents
flyctl deploy --image registry.fly.io/archhub-agents@sha256:<previous>
```

## Local-vs-cloud

`agents/run.py` keeps working unchanged for users who run agents on
their own machine via local Ollama. The cloud runner is opt-in: it's
only invoked by the Docker image's `CMD`. Both paths share the same
queue + dispatcher + scheduler, just with a different LLM backend
selected by `ARCHHUB_AGENTS_BACKEND`.

## Founder status reports (every-N-min email)

The cloud daemon emails a per-cycle ArchHub digest to the founder
through Resend. Wired in `agents/status_report.py` (builds the dict +
HTML) and `agents/report_sender.py` (the Resend POST + cadence gate).
The runner calls it from `CloudDaemon.tick_once` so failures stay
contained — a Resend hiccup never crashes the agent loop.

### Env vars

| Var | Default | Purpose |
| --- | ------- | ------- |
| `RESEND_API_KEY` | unset | Required for live send. When absent, the sender logs to stdout + `agents/logs/reports.log` and returns ok. |
| `ARCHHUB_REPORT_RECIPIENT` | `ahmed.fargaly98@gmail.com` | Address the digest goes to. |
| `ARCHHUB_REPORT_FROM_EMAIL` | `noreply@archhub.io` | `from` header. Must be a verified Resend sender. |
| `ARCHHUB_REPORT_INTERVAL_MIN` | `60` | Minutes between sends. `0` disables the feature. |
| `ARCHHUB_REPORT_DIGEST_HOURS` | unset (off) | Buffers reports for N hours and sends one combined email — rate-limit-friendly. |
| `ARCHHUB_REPORT_DRY_RUN` | unset | Any truthy value forces stdout-only (useful for staging). |
| `ARCHHUB_BACKEND_HEALTHZ` | `http://127.0.0.1:8000/healthz` | URL probed for cloud_backend reachability. |
| `ARCHHUB_AGENTS_HEALTHZ` | `http://127.0.0.1:8080/healthz` | URL probed for the agents daemon. |
| `ARCHHUB_GH_REPO` / `GITHUB_TOKEN` | unset | When both set, the report includes the latest GitHub Actions run status. |

Change live (no redeploy required):

```bash
flyctl secrets set ARCHHUB_REPORT_INTERVAL_MIN=30 -a archhub-agents
flyctl secrets set ARCHHUB_REPORT_RECIPIENT=ops@archhub.io -a archhub-agents
```

### Resend free-tier reality — read this first

Resend's free tier ships **100 emails/day** (3,000/mo). Interval math:

| Interval | Sends/day | Free tier? |
| -------- | --------- | ---------- |
| 10 min   | 144       | NO — past the 100/day cap by 11 am UTC |
| 15 min   | 96        | tight, no headroom |
| 30 min   | 48        | comfortable |
| 60 min   | 24        | DEFAULT — leaves room for ad-hoc magic links too |

The default is **60 minutes** on purpose. For a pre-revenue product
the founder doesn't need a 10-minute pulse; an hourly digest catches
every meaningful signal (signups, billing webhooks, agent failures)
without flooding the inbox or burning the free tier.

If you genuinely want 10-min granularity:

* **Upgrade Resend** — $20/mo for the 50,000-email Pro tier.
* **Use digest mode** — `ARCHHUB_REPORT_DIGEST_HOURS=1` with a 10-min
  interval. Signals collected every 10 min; one combined email per
  hour. 24 emails/day instead of 144.

### Per-send audit log

Every send (live or dry-run) writes a JSONL row to
`agents/logs/reports.log`. Cadence state lives in
`agents/state/last_report_at.txt`. To force the next tick to send,
delete the file.

## Gotchas

- **`ANTHROPIC_API_KEY` is required.** The daemon starts without
  one but every task fails with `ANTHROPIC_API_KEY not set`. The
  `/healthz` endpoint still answers; check `fly secrets list -a
  archhub-agents` if tasks aren't producing output.
- **The volume must exist before the first deploy.** `deploy.ps1`
  creates it for you. If you deploy manually with `flyctl deploy`
  and forget the volume, the daemon writes outputs to ephemeral
  storage and loses them on next restart.
- **Don't enable `auto_stop_machines`.** Fly's default will idle
  the machine after a quiet period — this daemon doesn't idle by
  design.
- **Heartbeat ≠ liveness for tasks.** The heartbeat says the loop
  is ticking. If you want to know tasks are actually completing,
  check `/status` (look at `completed_today`) or `flyctl logs` for
  `OK in Xms` lines.
