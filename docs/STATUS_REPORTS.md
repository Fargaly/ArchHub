# Status Reports

ArchHub's cloud daemon (`agents/cloud_runner.py`) emails a structured
status digest to the founder on a configurable cadence. Source files:

| File | Role |
| --- | --- |
| `agents/status_report.py`  | Builds the structured dict + HTML/text rendering. Runs entirely on stdlib + the cloud_backend SQLite. |
| `agents/report_sender.py`  | Resend POST, cadence gate (`state/last_report_at.txt`), digest-mode buffer (`state/digest_buffer.jsonl`). |
| `agents/cloud_runner.py`   | Calls `report_sender.tick_send_report` every loop. Swallows errors so a bad Resend response never kills the daemon. |
| `agents/logs/reports.log`  | JSONL audit trail — one line per send attempt. |

## What's in a report

```
BUSINESS           — signups 24h, paying signups 24h, MRR delta, active subs, churn 7d
INFRASTRUCTURE     — cloud_backend /healthz, agents /healthz, CI status (GitHub Actions)
AGENTS             — pending tasks by dept, completed today, last 5 outputs
COST               — Anthropic spend last 24h, naive 30-day projection
ROADMAP            — items targeted in next 7 days, items shipped today
ERRORS             — boot.log tail + any lines containing ERR/Error/Traceback
META               — heartbeat freshness, cadence, generator id
```

Each section is best-effort. If the cloud_backend SQLite is
unreachable, the report still renders — the business section just
shows `unavailable — backend_db_unreachable`.

## Sample subject

```
[ArchHub] 14:30 | 0 paying 24h | CI green | 3 roadmap pending
```

Keeps to 80 chars when possible. No exclamation points by convention.

## Sample plain-text body

```
ArchHub status · 2026-05-13T14:30:00+00:00
Subject: [ArchHub] 14:30 | 0 paying 24h | CI green | 3 roadmap pending

BUSINESS
  signups (24h):       0
  paying new (24h):    0
  active subs:         0
  MRR delta (24h):     $0
  churn (7d):          0

INFRASTRUCTURE
  backend /healthz:    200
  agents /healthz:     200
  CI:                  success

AGENTS
  pending total:       4
  completed today:     12
    docs         1
    eng          1
    ops          0
    qa           1
    rnd          1

COST
  spend 24h:           $0.0421
  projected 30d:       $1.26

ROADMAP
  pending next 7d:     3
  shipped 24h:         1

ERRORS (boot.log tail)
  outlook_runner  : COM reachable
  revit installs  : [2020, 2023, 2024, 2025]
  autocad installs: [2026]

heartbeat: 2026-05-13T14:29:58+00:00 · cycles 1742 · age 2s · fresh True
report id: rpt_1715610600_a1b2c3
```

## Sample HTML body

The HTML mirrors the text structure with one `<table>` per section,
all inline-styled so Gmail (which strips `<style>`/`<link>`) renders
it correctly. Approximate visual:

```html
<h1>ArchHub status</h1>
<div>2026-05-13T14:30 · cadence: every 60 min</div>

<h3>Business</h3>
<table>
  <tr><td>New signups (24h)</td><td>0</td></tr>
  <tr><td>New paying customers (24h)</td><td>0</td></tr>
  ...
</table>

<h3>Infrastructure</h3>
<table>...</table>

<h3>Agents</h3>
<div>Pending tasks (4 total) · completed today: 12</div>
<ul><li><b>docs</b>: 1</li><li><b>eng</b>: 1</li>...</ul>
<table>...</table>

<h3>Cost</h3>
<table>...</table>

<h3>Roadmap</h3>
<table>...</table>

<h3>Errors</h3>
<div>(boot.log tail, monospace, color-coded)</div>
```

## How to read it

* **Subject first.** The headline `X paying 24h | CI <state> | Y roadmap pending`
  is meant for a 2-second glance from a phone notification. Open the
  body only if one of those numbers surprises you.
* **`new_paying_24h` is the metric to care about pre-revenue.** Everything
  else is a hygiene signal.
* **`agents.pending_total` should stay near 0 in steady state.** A
  growing number means the dispatcher is starved (Anthropic key issue,
  rate limit) or the depts have stalled.
* **`CI: failure` is a hard stop signal.** Treat it as P0; main is broken.
* **`infrastructure.backend_healthz.status_code: null` means the cloud_backend
  is unreachable from the agent container.** Likely Fly app sleeping or
  a deploy failure — `flyctl logs -a archhub-cloud`.

## How to throttle

Throttle the cadence (no redeploy needed):

```bash
flyctl secrets set ARCHHUB_REPORT_INTERVAL_MIN=120 -a archhub-agents
```

Switch to digest mode (one email per hour, but signals collected every
10 minutes):

```bash
flyctl secrets set ARCHHUB_REPORT_INTERVAL_MIN=10 -a archhub-agents
flyctl secrets set ARCHHUB_REPORT_DIGEST_HOURS=1   -a archhub-agents
```

## How to mute

Set the interval to `0`. Nothing else changes — the daemon keeps
ticking, the report builder just never fires.

```bash
flyctl secrets set ARCHHUB_REPORT_INTERVAL_MIN=0 -a archhub-agents
```

Per-deploy dry-run (logs but never sends):

```bash
flyctl secrets set ARCHHUB_REPORT_DRY_RUN=1 -a archhub-agents
```

## How to test locally

Build one report without sending:

```bash
python -m agents.status_report > /tmp/report.json
python -m agents.status_report --html > /tmp/report.html
python -m agents.status_report --text > /tmp/report.txt
```

Force a live send (uses `RESEND_API_KEY`):

```powershell
$env:ARCHHUB_REPORT_INTERVAL_MIN = '1'
Remove-Item agents\state\last_report_at.txt -ErrorAction SilentlyContinue
python -m agents.cloud_runner --once
```

## How to add a custom signal

1. Add a `_section_xxx()` function to `agents/status_report.py` that
   returns a dict with primitive-typed fields.
2. Call it inside `generate_report()` via `_safe(_section_xxx)`.
3. Add a rendering row to `_render_html()` and a block to
   `_render_text()`.
4. Add a key + value to the subject if the signal matters at a glance.
5. Update `tests/test_status_report.py` shape assertion.

The whole report is plain stdlib + Python types — no schema, no
migrations, no contract with the recipient beyond "human readable".

## Resend free-tier cap

The Resend free tier is 100 emails/day. A 10-minute cadence ships 144
emails/day — past the cap by ~11 am UTC. See
`agents/CLOUD_DEPLOY.md#founder-status-reports-every-n-min-email` for
the full table. The default of **60 minutes** is chosen to leave
headroom for ad-hoc magic-link emails.

## Audit trail

Every send attempt — live or stdout-only — appends one JSONL row to
`agents/logs/reports.log`:

```json
{"ts":"2026-05-13T14:00:00+00:00","ok":true,"status":200,"subject":"[ArchHub] 14:00 | 0 paying 24h | CI green | 3 roadmap pending","mode":"live","recipient":"ahmed.fargaly98@gmail.com","note":""}
```

Tail it on Fly:

```bash
flyctl ssh console -a archhub-agents -C "tail -n 20 /data/agents/logs/reports.log"
```
