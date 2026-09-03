# Your User Database — where your account actually lives

> **Reference — not the roadmap.** `docs/ROADMAP.md` is the single source of
> truth for plans and milestones. This page describes the live database as it
> stands **today** (audited 2026-06-18). It is written for you, the founder —
> plain English, no code required to follow it.

You asked for a **proper user database — saved and documented**. You have one.
This page tells you, in plain terms, where it is, what is in it, that your own
account row is real, and how to look at it yourself at any time.

## The short version

- Your account data lives in a **real database** — a single SQLite file called
  `archhub_cloud.db`.
- That file sits on a **dedicated 1 GB encrypted disk** ("a Fly volume") that is
  attached to the ArchHub Cloud server, separate from the app code.
- Because the disk is separate from the code, **every time we ship a new version
  of the backend, your data stays.** Redeploys do not wipe accounts.
- It is **encrypted at rest** by the host.
- You can open a terminal into the server and read your own row in about three
  commands. The exact commands are at the bottom of this page.

## Where it lives (verified)

| Thing | Value (checked live on the server) |
| --- | --- |
| Cloud app | Fly.io app `archhub-cloud` (`https://archhub-cloud.fly.dev`) |
| Region | `ord` (Chicago) |
| Database file | `/data/archhub_cloud.db` |
| Disk it sits on | A Fly **volume** named `data`, mounted at `/data` |
| Disk size | **1 GB** |
| Encrypted | **Yes** (`ENCRYPTED = true`) |
| Survives redeploys | **Yes** — the volume is separate from the app image |

The volume detail above is not a claim from a plan — it is what the Fly platform
reports for the live server right now (`flyctl volumes list -a archhub-cloud`
shows `data · 1GB · encrypted true · ord`).

Your **personal brain** also lives on the same disk, in its own folder
(`/data/replicas`), one folder per account. So both your account and your
brain's cloud copy ride the durable, encrypted disk and survive redeploys.

## What is in it

The database holds **19 tables**. You do not need to know them all — here are the
ones that matter to you as the owner, in plain English:

| Table | What it stores |
| --- | --- |
| `users` | **Your account row** — email, your plan, your Stripe customer link, your message quota, your AI mode, and a pointer to your personal brain. One row per person. |
| `tokens` | Your active sign-ins. Each is a key that proves it is you, and it **expires after 90 days**. Signing out deletes it. |
| `codes` | The one-time magic-link codes used while signing in. Short-lived; deleted once used. |
| `companies` | A firm/team workspace, if you create one. Holds the plan, seat count, and billing link for the team. |
| `company_members` | Who is on a team and their role (owner, admin, or member). |
| `company_invites` | Pending email invitations to a team. |
| `credit_grants` | Hosted-AI credit packs you have bought, and how many messages are left. |
| `usage_log` | A line per completed hosted-AI message, for billing and analytics. |
| `marketplace_*` | Skill packs published to the marketplace, their files, and any abuse reports (three tables). |
| `memory_facts`, `memory_fact_index`, `memory_facts_fts`, `collective_memory`, `memory_op_log`, `memory_access_log` | Your brain's memory: the facts it remembers, the search index over them, shared/redacted patterns, and audit logs of every memory write and read. |
| `training_samples` | Captured conversation turns that may, after review, become training data. |
| `schema_meta` | Internal bookkeeping the database uses to track its own upgrades. |

The full column-by-column breakdown is in `docs/BACKEND_SPEC.md` if you ever want
the engineering detail.

## Your account row is real

When you sign in, the backend writes a real row into the `users` table with:

- your **email**,
- your **plan** (it starts as `trial` with 30 messages, and moves to a paid tier
  when you check out),
- your **Stripe customer** link once you have paid,
- your **AI mode** (`byo_key` by default — your own provider key — or `hosted`
  if you buy credits),
- a **brain id** that points at your own personal-brain copy on the server.

This is not a placeholder. The sign-in endpoints (`/v1/auth/register` +
`/v1/auth/exchange`, or Google sign-in) create and update this exact row, and
`/v1/me` reads it back. When the desktop app shows your plan and remaining
messages, those numbers come straight from this row.

## How to inspect it yourself

You can read your own data directly on the server. You need the `fly` command-line
tool signed in to the ArchHub account; then run:

```bash
# 1. Open a shell inside the running cloud server
fly ssh console -a archhub-cloud

# 2. List the tables (proves the database is real and populated)
sqlite3 /data/archhub_cloud.db ".tables"

# 3. Read YOUR account row in plain text (swap in your email)
sqlite3 /data/archhub_cloud.db \
  "SELECT id, email, plan, stripe_id, ai_mode, credit_balance, created_at
     FROM users WHERE email = 'you@yourfirm.com';"
```

A few useful follow-ups once you are in that shell:

```bash
# How many accounts exist in total
sqlite3 /data/archhub_cloud.db "SELECT COUNT(*) FROM users;"

# Your active sign-ins and when they expire
sqlite3 /data/archhub_cloud.db \
  "SELECT created_at, expires_at FROM tokens
     WHERE user_id = (SELECT id FROM users WHERE email='you@yourfirm.com');"

# Confirm the database is on the durable volume, not the throwaway image
df -h /data
```

When you are done, type `exit` to leave the server shell. Reading rows like this
does not change anything — these are read-only `SELECT` queries.

## Why this is safe

- The disk is **encrypted at rest**.
- Sign-in keys **expire after 90 days** and can be revoked at any time.
- We **never** store your AI provider keys in this database — those stay on the
  backend's secret store and are never written to a user row.
- Shipping new code does **not** touch your data, because the data is on a
  separate volume from the code.

For how the desktop app talks to this database, see `docs/CLOUD_API.md`. For the
roles and team-seat model, see `docs/PERMISSIONS.md`.
