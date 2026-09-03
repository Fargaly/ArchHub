# Cloud API — the desktop ↔ cloud surface

> **Reference — not the roadmap.** `docs/ROADMAP.md` is the single source of
> truth for plans and milestones. This is a concise reference for the endpoints
> the desktop app calls and how it wires to them, **as built today** (audited
> live 2026-06-18). For the full backend contract see `docs/BACKEND_SPEC.md`.

The desktop app talks to one live service: **`https://archhub-cloud.fly.dev`**.

## How the desktop wires to it

| Piece | File | Role |
| --- | --- | --- |
| Base URL | `app/cloud_client.py` → `DEFAULT_BASE` | Points at `https://archhub-cloud.fly.dev` (override with the `ARCHHUB_CLOUD_BASE_URL` env var). All cloud calls go through this client. |
| Token store | `app/cloud_client.py` | The bearer token is read from / written to `%APPDATA%\ArchHub\brain\cloud.json`. This file is the source of truth for "am I signed in". |
| Email sign-in | `app/cloud_auth.py` → `SignInWorker` | Runs the magic-link flow on a background thread. |
| Google sign-in | `app/cloud_auth.py` → `GoogleSignInWorker` | Runs the Google OAuth flow: it gets a consent URL from `/v1/auth/google/start`, opens the browser, catches the redirect on a local loopback port, and exchanges the code. |
| Quota meter | `app/cloud_usage.py` → `snapshot()` | Caches your plan + remaining messages (60-second cache, decrements locally per chat, refreshes on sign-in and on a `402`). This is what the account display shows. |
| Bridge slots | `app/bridge.py` → `cloud_status()`, `cloud_sign_in()`, `cloud_sign_in_google()` | The buttons the UI calls. They run the workers above and emit the `cloud_signin_done` signal when finished. |
| Account surface | Settings → Account (`app/settings_dialog.py` `AccountTab`) | Shows your signed-in email and plan; offers sign-in / sign-out. |

So the path is: a button in the UI → a `cloud_*` slot in `bridge.py` → a worker
in `cloud_auth.py` → the live backend → the token saved to `cloud.json` → your
plan and quota read back through `cloud_client` / `cloud_usage`.

## Sign-in flow (Google, the primary path)

1. The desktop generates a PKCE `code_verifier` + `code_challenge`.
2. It starts a one-shot loopback web server on `127.0.0.1:<port>`.
3. It calls `GET /v1/auth/google/start?code_challenge=…&redirect=http://127.0.0.1:<port>/cb&client=desktop`.
4. The backend returns `{ "auth_url": "https://accounts.google.com/…" }`.
5. You pick a Google account in the browser.
6. Google returns to `/v1/auth/google/callback`; the backend verifies the signed
   state and Google ID-token, mints a one-time ArchHub code, and redirects back
   to the desktop loopback.
7. The desktop exchanges it: `POST /v1/auth/exchange { "code": "…", "code_verifier": "…" }`.
8. The response carries the **bearer token** and plan; the desktop writes the
   token to `%APPDATA%\ArchHub\brain\cloud.json`.
9. The desktop pairs your local brain best-effort (`/v1/me`, set owner, an empty
   `/v1/brain/sync` handshake).

The email magic-link path (`SignInWorker`) does the same backend work, starting
from `POST /v1/auth/register` and finishing on the same `/v1/auth/exchange`.

## Endpoint reference

Every private call sends `Authorization: Bearer <token>` (the token from
`cloud.json`). The status column is what the live service returned on 2026-06-18.

### Auth

| Method | Path | Auth | Purpose | Live (no token) |
| --- | --- | --- | --- | --- |
| POST | `/v1/auth/register` | none | Start email magic-link sign-up/sign-in. | — |
| POST | `/v1/auth/exchange` | none | Exchange a one-time code for a bearer token. | — |
| GET | `/v1/auth/google/start` | none | Get a Google consent URL. | `200` |
| GET | `/v1/auth/google/callback` | none | Google redirect target; mints a code. | — |
| POST | `/v1/auth/logout` | bearer | Revoke this token (or all with `{"all_sessions": true}`). | — |

### Account, billing, AI

| Method | Path | Auth | Purpose | Live (no token) |
| --- | --- | --- | --- | --- |
| GET | `/v1/me` | bearer | Your identity, plan, remaining messages, period end, current company. Drives the account display. | `401` |
| GET | `/v1/billing/plans` | none | Public pricing / plan metadata. | `200` |
| POST | `/v1/billing/checkout` | bearer | Start a checkout (`{tier, seats?, annual?}`). | — |
| GET | `/v1/billing/portal` | bearer | Open the billing portal. | — |
| POST | `/v1/billing/credits` | bearer | Buy a hosted-AI credit pack. | — |
| GET / POST | `/v1/ai-mode` | bearer | Read / set your AI mode (`byo_key` or `hosted`). | — |
| POST | `/v1/chat/completions` | bearer | OpenAI-compatible chat (hosted mode). Returns `402 byo_key_required` in the default BYO-key mode so the desktop uses your own key. | `401` |

### Brain and memory

| Method | Path | Auth | Purpose | Live (no token) |
| --- | --- | --- | --- | --- |
| POST | `/v1/brain/sync` | bearer | Push/pull your brain replica delta (plus any firm/community replicas). | — |
| DELETE | `/v1/brain/sync` | bearer | Delete your cloud brain replica. | — |
| GET | `/v1/memory/stats` | bearer | Memory / training counters. | `401` |
| GET | `/v1/memory/facts` | bearer | List or search your memory facts (`?q=`, `?limit=`). | — |
| POST / PUT / DELETE | `/v1/memory/facts[/{id}]` | bearer | Add / update / soft-delete a fact you own. | — |
| GET | `/v1/memory/collective` | bearer | List shared collective facts. | — |
| GET | `/v1/memory/ops` | bearer | Your memory-write audit log. | — |

### Teams

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/companies` | bearer | Create a Studio or Firm workspace. |
| GET | `/v1/companies/mine` | bearer | List your team memberships (with role). |
| GET | `/v1/companies/{id}` | bearer (member) | Team detail + roster. |
| POST | `/v1/companies/{id}/invites` | bearer (owner/admin) | Invite a teammate by email. |
| POST | `/v1/companies/invites/accept` | bearer | Accept an invite (email must match). |
| DELETE | `/v1/companies/{id}/members/{user_id}` | bearer (owner) | Remove a member. |
| POST | `/v1/companies/{id}/transfer-ownership` | bearer (owner) | Hand the team to a member. |
| POST | `/v1/companies/{id}/switch` | bearer (member) | Set your active workspace. |
| POST | `/v1/companies/{id}/seats` | bearer (owner/admin) | Set the seat count. |

See `docs/PERMISSIONS.md` for the roles behind the team endpoints.

### Health

| Method | Path | Auth | Purpose | Live |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | none | Liveness probe. | `200 {"ok": true, "ts": <int>}` |

The health path is `/healthz`. There is no `/health` (it returns `404`).

## Token handling — keep it private

- The bearer token lives in `%APPDATA%\ArchHub\brain\cloud.json`. It proves it is
  you, so treat it like a password.
- **Never** paste a raw token into a doc, a log, a screenshot, or brain memory.
- Tokens expire after 90 days; signing out (`/v1/auth/logout`) revokes them
  immediately.
