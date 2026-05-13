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
