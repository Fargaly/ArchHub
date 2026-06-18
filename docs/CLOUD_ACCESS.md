# ArchHub Cloud Access

Verified on 2026-06-18 from the CLOUD lane.

## What Is Live

The public landing page and the deployed API are two separate live surfaces:

| Surface | URL | Verified response |
| --- | --- | --- |
| Landing | `https://archhub.io` | `200 text/html` |
| API health | `https://archhub-cloud.fly.dev/healthz` | `200 {"ok": true, "ts": ...}` |
| Google auth start | `https://archhub-cloud.fly.dev/v1/auth/google/start` | `200 {"auth_url": "https://accounts.google.com/..."}` |
| Browser sign-in page | `https://archhub-cloud.fly.dev/signin` | `200 text/html` |
| Browser dashboard page | `https://archhub-cloud.fly.dev/dashboard` | `200 text/html` |

`/health` is not a live API route. The Fly health route is `/healthz`.

## How A User Signs In

ArchHub supports the same account/token backend through three entry points:

1. Desktop Google sign-in: `app/cloud_auth.py::GoogleSignInWorker`.
2. Desktop email/magic-link sign-in: `app/cloud_auth.py::SignInWorker`.
3. Brain CLI sign-in: `personal-brain-mcp/src/personal_brain/cloud_login.py`.

The desktop Google flow is the founder-facing path for the account chip:

1. The desktop generates a PKCE `code_verifier` and `code_challenge`.
2. It starts a one-shot loopback HTTP server on `127.0.0.1:<port>/cb`.
3. It calls:
   `GET /v1/auth/google/start?code_challenge=<challenge>&redirect=http://127.0.0.1:<port>/cb&state=<desktop-state>&client=desktop`
4. The backend returns `{ "auth_url": "https://accounts.google.com/..." }`.
5. The user chooses a Google account in the browser.
6. Google returns to `/v1/auth/google/callback`.
7. The backend verifies signed state plus Google ID-token claims, mints a one-time ArchHub code, and redirects through `/auth/return` to the desktop loopback. The live `/auth/return` hop sends `state=archhub`; the desktop loopback accepts that sentinel and also accepts the generated state if a future backend echoes it.
8. The desktop exchanges the one-time code:
   `POST /v1/auth/exchange { "code": "...", "code_verifier": "..." }`
9. The exchange response contains the bearer token and plan. The desktop writes the token to `%APPDATA%/ArchHub/brain/cloud.json` through `app/cloud_client.py`.
10. The desktop pairs the local brain best-effort: `/v1/me`, `brain.set_owner`, `brain.wiring_announce`, and an empty `/v1/brain/sync` handshake.

The email path opens `/signin?challenge=...&redirect=<loopback>&client=desktop`; the magic-link eventually lands on the same `/auth/return` and `/v1/auth/exchange` token path.

The brain CLI path does the same backend work from a shell:

```powershell
python -m personal_brain.cloud_login login --google
python -m personal_brain.cloud_login --email you@studio.com --code <CODE-OR-RETURN-URL>
python -m personal_brain.cloud_login status
python -m personal_brain.cloud_login logout
```

## Account And Data Endpoints

All private endpoints use:

```http
Authorization: Bearer <token-from-cloud.json>
```

The local token file is:

```text
%APPDATA%\ArchHub\brain\cloud.json
```

Do not print or store the raw token in docs, logs, or brain memory.

| Endpoint | Auth | What it serves | Live result observed |
| --- | --- | --- | --- |
| `GET /v1/me` | Required | Current account identity: `user_id`, `brain_id`, `email`, `plan`, `remaining_messages`, `period_end`, `can_upgrade`. | `401` without bearer; `200` with bearer. |
| `POST /v1/auth/logout` | Required | Revokes this token, or all user tokens with `{"all_sessions": true}`. | Implemented server route. |
| `POST /v1/brain/sync` | Required | Push/pull brain replica delta. Body is `{ since_hlc, delta: { fragments, wiring }, community_keys? }`. Response is `{ accepted, rejected, new_hlc, merged, firm_keys, community_keys }`. | `200` with bearer; empty delta returned merged data. |
| `DELETE /v1/brain/sync` | Required | Deletes this user's cloud brain replica. | Implemented server route. |
| `GET /v1/memory/stats` | Required | Training/memory counters: `capture_today`, `redact_clean`, `judge_queued`, `approved`, `train_ready`, `threshold`. | `401` without bearer; `200` with bearer. |
| `GET /v1/memory/facts?limit=N&q=...` | Required | Lists or searches the user's semantic memory facts. Same canonical store as `/v1/brain/sync`. | `200` with bearer, `results` array. |
| `POST /v1/memory/facts` | Required | Adds a manual fact to the caller's memory. | Implemented server route. |
| `PUT /v1/memory/facts/{fact_id}` | Required | Updates a fact owned by the caller. | Implemented server route. |
| `DELETE /v1/memory/facts/{fact_id}` | Required | Soft-deletes a fact owned by the caller. | Implemented server route. |
| `GET /v1/memory/collective` | Required | Lists shared collective facts. | `200` with bearer, currently empty for this account. |
| `GET /v1/memory/ops` | Required | Memory operation audit log for the caller. | Implemented server route. |
| `GET /v1/companies/mine` | Required | Company memberships for the account. | `200` with bearer, `companies: []` for the tested account. |
| `GET /v1/companies/{company_id}` | Required | Company detail and team roster; used by `/dashboard` when memberships exist. | Implemented server route. |
| `GET /v1/billing/plans` | Public | Public pricing/plan metadata. | `200` public. |

There are no live routes named `/v1/brain/sessions` or `/v1/brain/data`; both returned `404`. The "session" concept is the bearer token plus `/v1/me` and `/v1/auth/logout`. The user's brain/account data is exposed through `/v1/brain/sync` and `/v1/memory/*`.

## What The User Can See Today

In a browser, the user can reach:

- `https://archhub.io` for the public landing page.
- `https://archhub-cloud.fly.dev/signin` for email magic-link sign-in.
- `https://archhub-cloud.fly.dev/dashboard` for the account dashboard.

The dashboard page signs in through the browser magic-link flow, stores `archhub_session_token` in browser `localStorage`, then reads:

- `/v1/me`
- `/v1/companies/mine`
- `/v1/companies/{company_id}` when the account belongs to a company.

For the tested founder account, `/v1/me` returned plan/account/quota metadata and `/v1/companies/mine` returned no companies.

From the desktop and brain daemon, the account is reachable when `%APPDATA%\ArchHub\brain\cloud.json` contains a valid bearer. The daemon status from `brain.health` showed the local brain bound to the cloud user and personal cloud sync signed in against `https://archhub-cloud.fly.dev`.

## The Exact Access Gap

The cloud backend is accessible. The founder's "can't visually access it" gap is in the desktop product surface, not in the API:

- Browser/API access works: landing, `/signin`, `/dashboard`, `/healthz`, Google auth start, `/v1/me`, `/v1/brain/sync`, and `/v1/memory/*` respond correctly.
- Desktop auth machinery exists: `GoogleSignInWorker`, `SignInWorker`, `cloud_client`, and brain pairing are implemented.
- The default desktop UI does not yet expose the in-app account chip/status entry point that makes the signed-in state visually obvious from the normal ArchHub surface.

The in-app account chip should use this contract:

| Chip state | Data source | Action |
| --- | --- | --- |
| Signed out | `cloud_client.is_signed_in()` false or `cloud_client.me()` returns `None`. | Show "Sign in"; launch `GoogleSignInWorker` as the primary action. |
| Signing in | Worker running. | Show pending state; disable duplicate starts; surface `failed(message)` as the recovery text. |
| Signed in | `cloud_client.me()` returns account payload. | Show email or initials, plan, and remaining messages. |
| Sync active | `brain.health` / personal sync status shows `personal_sync.signed_in: true`. | Show last sync timestamp and last result counts if expanded. |
| Needs reauth | `/v1/me` returns `401` or brain personal sync reports `needs_reauth`. | Clear local signed-in visual state and offer sign-in again. |

No new backend route is required for the chip. It needs to call the existing desktop client helpers and the existing brain status tool, then route sign-in through the existing workers.
