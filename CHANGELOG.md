# Changelog

All notable changes to ArchHub.
Format roughly follows [Keep a Changelog](https://keepachangelog.com/).

## [1.2.0] — 2026-05-13

The "customer infrastructure" release. Earlier today's audit revealed
the cloud backend tracked email-only — no firm name, no team support,
no real path from signup to revenue. Six hotfix releases trimmed the
distractions; this minor bump replaces them with the missing
customer + revenue plumbing.

| Track | Status |
|---|---|
| Customer profile fields on signup | ✅ shipped |
| Companies + multi-seat + invite flow | ✅ shipped |
| Per-company Stripe Checkout (Studio 5 seats / Firm 25 seats) | ✅ shipped |
| Stripe webhook end-to-end tests | ✅ 7 new tests (mocked) |
| Cloud backend one-command Fly.io deploy | ✅ shipped |
| Go-live checklist (Stripe account → first $) | ✅ shipped |
| Agents 24/7 cloud daemon on Fly.io | ✅ shipped (Anthropic Haiku backend) |
| Agents `/healthz` + `/status` dashboard | ✅ shipped |

### Added — Customer profiling + companies

- **`cloud_backend/db.py`** — 8 idempotent profile columns on `users`:
  `full_name`, `firm_name`, `aec_role`, `aec_discipline`, `firm_size`,
  `country`, `signup_source`, `current_company_id`.
- **3 new tables**:
  - `companies` (id, name, slug, owner_user_id, plan, seat_limit,
    billing_email, stripe_customer_id, stripe_subscription_id,
    period_end, created_at)
  - `company_members` (company_id, user_id, role, joined_at,
    invited_by_user_id) — role ∈ owner / admin / member
  - `company_invites` (token, company_id, email, role,
    invited_by_user_id, expires_at, accepted_at)
- **DAO helpers**: `update_user_profile`, `get_user_with_profile`,
  `create_company`, `get_company`, `list_companies_for_user`,
  `list_company_members`, `add_company_member`, `remove_company_member`,
  `create_company_invite`, `get_company_invite`, `mark_invite_accepted`,
  `set_current_company`. Slug-collision retry built in.

### Added — Companies API (`cloud_backend/companies.py`)

- `POST   /v1/companies`                       — create + auto-add owner
- `GET    /v1/companies/mine`                  — list with roles
- `GET    /v1/companies/{id}`                  — detail + members (owner/admin)
- `PATCH  /v1/companies/{id}`                  — update (owner)
- `POST   /v1/companies/{id}/invites`          — invite teammate (owner/admin)
- `POST   /v1/companies/invites/accept`        — accept invite token
- `DELETE /v1/companies/{id}/members/{uid}`    — remove member (owner, no-self)
- `POST   /v1/companies/{id}/switch`           — set caller's `current_company_id`
- `POST   /v1/auth/register`                   — now accepts profile fields

### Added — Stripe seat-based billing

- **`cloud_backend/billing.py`**: `create_company_checkout(company_id,
  plan, billing_email)` builds Stripe Checkout with
  `metadata.company_id` + `metadata.kind=company`. Quantity = seats
  (5 / 25) for per-seat unit prices.
- Webhook handler routes company-scoped sessions to
  `db.update_company(plan, seat_limit, stripe_customer_id,
  stripe_subscription_id, period_end)`.
- **`PLAN_SEATS = {"studio": 5, "firm": 25}`** in
  `cloud_backend/config.py`.

### Added — Agents 24/7 on Fly.io

- **`agents/anthropic_client.py`** — Anthropic `/messages` HTTP client
  matching the Ollama envelope shape. Ollama model id → Anthropic map:
  every existing dept model maps to `claude-haiku-4-5` (cheapest
  reasonable). Edit the dict in one place to change.
- **`agents/cloud_runner.py`** — 24/7 daemon entry. Backend selected
  via `ARCHHUB_AGENTS_BACKEND=anthropic|ollama` (anthropic default in
  cloud). Heartbeat to `/data/agents/heartbeat.txt`. SIGTERM-graceful.
  Spawns the dashboard endpoint on a thread.
- **`agents/dashboard_endpoint.py`** — FastAPI sub-app on port 8080:
  - `GET /healthz`               — last heartbeat + status
  - `GET /status`                — depts, pending task count, today's
    completed, last outputs
  - `GET /outputs/<dept>/<task>` — fetch a specific output file
- **`agents/Dockerfile`** — python:3.13-slim, non-root, /data volume,
  CMD runs cloud_runner.
- **`agents/fly.toml`** — app `archhub-agents`, region iad,
  shared-cpu-1x 256MB, mount, `auto_stop_machines=false`.
- **`agents/deploy.ps1`** — idempotent one-shot. Installs flyctl if
  missing, creates app + volume, prompts for `ANTHROPIC_API_KEY`,
  deploys.
- **`agents/CLOUD_DEPLOY.md`** — pre-reqs, deploy, verify, cost
  estimate (~$5-16/mo Anthropic Haiku + free shared VM tier).

### Added — Cloud backend deploy automation

- **`cloud_backend/deploy.ps1`** — one-command Fly.io deploy for the
  customer-facing backend. Installs flyctl, creates the app + volume,
  prompts for each Stripe / Anthropic / OpenAI / Google / Resend / JWT
  secret, deploys, hits `/healthz`, optional `--DnsAttach` for
  `cloud.archhub.app`.
- **`docs/GO_LIVE_CHECKLIST.md`** — 5-phase walkthrough from blank
  Stripe account → real $19 charge. Phase 1 Stripe setup (10 min),
  Phase 2 backend deploy (5 min), Phase 3 webhook registration (3 min),
  Phase 4 DNS (optional), Phase 5 real-card smoke test
  (`4242 4242 4242 4242` then flip to LIVE).

### Added — Stripe webhook end-to-end tests

- **`cloud_backend/tests/test_stripe_webhook.py`** — 7 tests covering:
  - `checkout.session.completed` → plan upgrades + msg_used reset
  - `customer.subscription.updated` → tier mapped via price id
  - `customer.subscription.deleted` → downgrade to trial
  - `invoice.payment_failed` → log only, no auto-downgrade
  - bad signature → reject cleanly
  - stripe not configured → safe error
  - unknown event type → ignored

### Tests

- `tests/` — **433 passing** (up from 413; +20 agent cloud tests)
- `cloud_backend/tests/` — **77 passing** (up from 40; +30 companies +
  user_profile + stripe webhook tests)

### Limitations / Phase 2 follow-ups

- **Frontend invite acceptance page** is not yet built. Invite tokens
  are returned in the API response so the dashboard can offer a "copy
  link" fallback today.
- **Email-match on invite acceptance is loose** — token is the only
  credential. Tightening to require matching user email = Phase 2.
- **Owner transfer flow** is not yet built — owner can't remove self.
- **Per-company quota** is not wired into `proxy.chat_completions` yet
  — proxy still reads the legacy `users.msg_limit`/`msg_used` columns.
- **Desktop app profile capture** — UI still doesn't ask for firm
  name / AEC role / discipline on first run. Backend accepts the
  fields; UI follow-up.
- **Civil 3D connector** stays deferred — needs $2.4k/yr Civil 3D
  licence on a build runner.

### Roadmap

`docs/GO_LIVE_CHECKLIST.md` is the next 2-hour playbook for the
founder. Run it end-to-end and the cloud backend goes from "code on
disk" → "real Stripe webhook deliveries showing in your dashboard."

## [1.1.1] — 2026-05-13

The "founder economics" release. Three signing / legal / compliance
tracks left over from v1.1.0 reframed against actual solo-founder
budget. Reduces $20,400 of "ready to spend" obligations to
**$390 + 60 min of paperwork** today.

| Track | v1.1.0 plan | v1.1.1 plan | Saved |
|---|---|---|---|
| Code signing | Azure Trusted Signing setup pending | **Going.** Automated setup script + GitHub secrets walkthrough | — |
| Trademark | $1,400 (4 USPTO filings) | **$350** (1 USPTO filing — wordmark Class 042 only) | $1,050 |
| SOC 2 Type I | $19,000 audit + Drata subscription | **$0** Trust Center page + CAIQ-Lite + CSA STAR self-assessment | $19,000 |

Total run-rate trimmed: **$20,050** — without losing core protection.
SOC 2 Type I goes back on the plan when the first enterprise prospect
with a real budget asks for it.

### Added

- **`scripts/setup_azure_trusted_signing.ps1`** — one-command Azure
  setup. Verifies `az` CLI, creates the resource group + Trusted
  Signing account (Basic SKU = $9.99/mo), registers
  `Microsoft.CodeSigning`, creates a Certificate Profile, creates an
  Entra service principal with the right RBAC role, prints the 6
  GitHub Actions secret values to paste. Idempotent — safe to re-run.
- **`docs/AZURE_SIGNING_QUICKSTART.md`** — start-to-signed-installer
  walkthrough. Step 1 (identity verification, $40) is the only thing
  the user does manually in the Azure portal; everything else is
  automated.
- **`docs/TRUST_CENTER.md`** — source content for the public
  <https://archhub.app/security> page. Covers data handling,
  sub-processors with DPA status, security practices, compliance
  roadmap, incident reporting. Replaces "where's your SOC 2?" with
  a credible answer mid-market buyers accept.
- **`docs/CAIQ_LITE.md`** — CAIQ-Lite v3.1 with every question
  pre-filled for ArchHub. When a buyer sends their security review
  questionnaire, copy-paste from here. Drops a 4-hour task to 5
  minutes.
- **™ symbol rollout** — landing page title, hero copy, footer
  attribution; chat window header brand label + tooltip explaining
  the TM status; About dialog with full attribution + Class 042
  filing note. Common-law trademark protection now active in every
  US state where ArchHub sells.

### Changed

- **`docs/TRADEMARK_FILING.md`** rewritten for the slim path:
  - Single filing today: wordmark, Class 042 (SaaS), TEAS Standard,
    **$350**
  - Year-2 add-ons documented with triggers (Class 009 when desktop
    revenue > $5k MRR; stylized mark when logo finalises; Madrid
    Protocol when international deals appear)
  - "TEAS Standard vs Plus" decision rationale captured
  - Filing-pending → ® transition called out

### Why this matters

Most pre-revenue solo founders skip TM + compliance entirely because
the "real" plan looks like $20k+ of out-of-pocket. v1.1.1 ships the
**cheap correct path** for both: $350 + free templates that don't lose
material protection at our stage. The expensive paths stay documented
(`docs/SOC2_READINESS.md`, original `docs/TRADEMARK_FILING.md` history)
for the moment revenue justifies them.

## [1.1.0] — 2026-05-13

The "minor-bump deep build" release. Three production hotfixes earlier
today (v1.0.2, v1.0.3, v1.0.4) cleared the burning issues; this minor
bump pushes the platform into new territory:

- 2 new host connectors (Rhino + Procore)
- Marketplace v1 (signed skill packs, cloud-hosted)
- Cross-platform CI matrix (Win/Mac/Linux)
- Code-signing infrastructure (Azure Trusted Signing + classic .pfx)
- Civil 3D roadmap, US trademark filing pack, SOC 2 readiness pack

### Added — new host connectors

#### Rhino 7 / 8
- `payload/rhino/archhub_mcp.py` — HTTP bridge inside Rhino's embedded
  Python. Drop-in script. Marshals all calls to Rhino's UI thread.
- `app/connectors/rhino_runner.py` — Python client: discovery,
  reachability probe, ping/info/execute_python/screenshot.
- 4 new tools in `tool_engine.TOOLS` (family `rhino`):
  `rhino_ping`, `rhino_info`, `rhino_execute_python`, `rhino_screenshot`.
- Auto-activate via `_rhino_active_cached()` — same 30-s TTL pattern
  as Outlook. Bridge listens on `:9879`.
- Add Host catalog entry + dedicated `_refresh_rhino` + `_kick_rhino`
  install action.
- `_FAMILY_DEFAULTS["rhino"]` defaults; `host_display_label("rhino")
  → "Rhino"`.
- 14 new tests in `tests/test_rhino_runner.py`.

#### Procore (construction PM SaaS)
- `app/connectors/procore_runner.py` — REST client. Bearer-token auth,
  stdlib `urllib.request`, no new deps.
- 10 new tools in `tool_engine.TOOLS` (family `procore`):
  `procore_ping`, `procore_info`, `procore_list_rfis`,
  `procore_get_rfi`, `procore_create_rfi`, `procore_list_submittals`,
  `procore_list_change_orders`, `procore_list_daily_logs`,
  `procore_list_projects`, `procore_list_users`.
- Procore is **always-on** in `tool_schemas_for()` (same as `_local`
  and `ai`) — no host install, just an API token.
- `_FAMILY_DEFAULTS["procore"]` — reads default `allow`, `create_rfi`
  defaults `ask` (writes to a live construction record).
- Settings → Sign-ins surfaces Procore as a provider.
- 37 new tests in `tests/test_procore_runner.py`.

### Added — Marketplace v1

#### Cloud backend
- `cloud_backend/marketplace.py` — FastAPI router. Endpoints:
  - `POST /marketplace/packs` — signed-pack upload (multipart)
  - `GET  /marketplace/packs` — list with text search, category,
    `verified_only`, cursor pagination
  - `GET  /marketplace/packs/{pack_id}` — pack detail
  - `GET  /marketplace/packs/{pack_id}/download` — streams zip + sig
  - `POST /marketplace/packs/{pack_id}/review` — admin approve/reject
  - `POST /marketplace/packs/{pack_id}/report` — abuse report
- 3 new tables in `cloud_backend/db.py`:
  `marketplace_packs`, `marketplace_pack_files`,
  `marketplace_reports`. Plus an idempotent `is_admin` column on
  `users`.
- Mounted in `cloud_backend/main.py`.
- 16 new tests in `cloud_backend/tests/test_marketplace.py`.

#### Client
- `app/marketplace_client.py` — `list_packs`, `install_pack`,
  `uninstall_pack`, `list_installed`, `upload_pack`. Re-verifies the
  Ed25519 signature after download — bad-sig packs are refused at
  install time.
- `app/skills/library.py` — marketplace install dir now part of the
  local skill search path. Entries tagged with `source: "marketplace"`,
  `pack_id`, `pack_version` for UI provenance.
- 9 new tests in `tests/test_marketplace_client.py`.

### Added — CI matrix + cross-platform builds

- `.github/workflows/test.yml` — matrix on `windows-latest`,
  `macos-latest`, `ubuntu-latest`. Python 3.14. Runs `pytest tests/`
  + `pytest cloud_backend/tests/` on every push + PR. Concurrency
  group keyed on PR ref so old runs cancel.
- `.github/workflows/build-macos.yml` — tag-triggered `.app` + `.dmg`
  via PyInstaller + `hdiutil`. Upload as release asset.
- `.github/workflows/build-linux.yml` — tag-triggered `tar.gz` (and
  AppImage where the runtime allows).
- `tests/test_outlook_bulk.py` + `tests/test_outlook_execute.py` —
  module-level `@pytest.mark.skipif(sys.platform != "win32", ...)`
  so non-Windows CI doesn't try to import win32com.

### Added — Code-signing infrastructure

- `scripts/sign_installer.ps1` — auto-detect dispatcher:
  - Azure Trusted Signing first (if AZURE_TENANT_ID set)
  - Classic .pfx fallback (if ARCHHUB_SIGN_CERT_PATH set)
  - Logs "unsigned — no signing config" + exits 0 if neither
- `scripts/build_installer.ps1` — replaces inline signtool with the
  new dispatcher; runs `signtool verify /pa /v` after a real signing.
- `.github/workflows/release.yml` — secrets block documented, sign
  step + verify step added.
- `docs/CODE_SIGNING.md` — Azure setup walkthrough, classic EV cert
  vendor table with prices, timestamp servers, troubleshooting.

### Added — Strategy + compliance docs

- `docs/CIVIL_3D_ROADMAP.md` — architecture memo for the deferred
  Civil 3D connector (blocked on Civil 3D licence on a build runner).
- `docs/TRADEMARK_FILING.md` — USPTO TEAS Plus prep pack: wordmark +
  stylized mark, Class 009 + 042 descriptions, basis 1(a) specimens,
  global Madrid Protocol strategy. ~$1,400 US filing cost mapped out.
- `docs/SOC2_READINESS.md` — Year-1 Type I plan: controls inventory,
  Phase A gaps, the 15 policies an auditor will request, vendor list,
  cost projection ($19k Year 1).

### Changed

- `tool_engine._active_families()` — added Rhino reachability cache
  (30-s TTL probe of `:9879`) alongside the existing Outlook cache.
- `tool_engine.tool_schemas_for()` always-on tuple extended:
  `("_local", "ai", "procore")`.
- `ai_behaviour._FAMILY_DEFAULTS` — added `rhino` + `procore` blocks.
- `ai_behaviour.host_display_label()` — added Rhino + Procore.
- Display order tuple in `tools_grouped_by_host()` — added rhino +
  procore in the preferred position.

### Tests

413 passing in `tests/` (up from 353 — +60), 40 passing in
`cloud_backend/tests/` (up from 24 — +16).

## [1.0.4] — 2026-05-13

The "auto-update like Claude Desktop" release. Until now the choice
was "off / notify (toast only) / silent (force install + restart)".
v1.0.4 adds the middle ground every user actually wants: ArchHub
downloads the new build in the background and shows an in-app banner
asking the user to relaunch at a convenient time.

### Added

- **In-app update banner** in `chat_window` — sits between the
  header and the chat surface, painted with the brand accent. Shows
  the release tag, a Restart now button (primary, fires the installer
  + auto-relaunch via Inno Setup `/RESTARTAPPLICATIONS`), and a Later
  button (dismisses; installer stays on disk for the next prompt).
- **New `prompt` update mode** — now the default. Modes:
    * `off` — never check
    * `notify` — Windows toast only (legacy)
    * `prompt` — silent download + in-app banner (new default)
    * `silent` — install + force-restart with no prompt (opt-in)
- **`release_updater.check_and_download()`** — splits the check + GH
  download from the install step so the banner has a clean way to
  download in the background. Returns `installer_path` for the UI to
  consume.
- **Periodic update watcher** — `schedule_auto_check(period_seconds=
  6*3600)` keeps probing every 6 hours, not just at launch. A user
  who leaves ArchHub running all day gets the prompt within hours of
  a release ship.
- **`on_ready(installer_path, release)` callback** plumbed through
  `schedule_auto_check` → `main.py` → `chat_window._on_update_ready`.
  Daemon-thread callback marshals to the Qt main thread via the new
  `ChatWindow.update_ready_signal` pyqtSignal.
- **9 new tests** in `tests/test_update_prompt_flow.py` cover: off
  mode skips, up-to-date returns ok, new-version downloads but does
  NOT install, prompt mode returns installer path, silent mode
  installs, legacy `auto` maps to silent, notify never installs,
  on_ready fires with installer path, ChatWindow banner wiring.

### Changed

- `release_updater.auto_check_and_apply()` now delegates to
  `check_and_download()` internally; the only branch left in the old
  function is "should we run the installer now or hand the installer
  to the UI?". Legacy `mode == "auto"` is mapped to `"silent"` so
  existing configs keep their behaviour.
- Update cooldown shortened from **24 h → 6 h** — long-running
  sessions now see the prompt the same day a release lands.
- `main.py` — passes `window._on_update_ready` to
  `schedule_auto_check(on_ready=...)`.

### Tests

353 passing in `tests/` (up from 344), 24 in `cloud_backend/tests/`.

## [1.0.3] — 2026-05-13

The "AI-as-tool" release. Architects increasingly mix multiple AIs in
their workflow — Claude for reasoning, GPT for code, Gemini for
vision / long context, LM Studio for offline privacy-bound work. v1.0.3
makes every one of those a first-class tool the primary model can call
mid-conversation, instead of forcing the user to swap chat backends.

### Added

- **`ai_runner.py` connector** — `chatgpt_ask`, `gemini_ask`,
  `lmstudio_ask`, `antigravity_ask`, `list_providers`. Each returns
  the same envelope (`{status, provider, model, text, ...}`) so the
  primary model can consume any of them uniformly.
- **5 new tools in `tool_engine.TOOLS`** under the `ai` family:
  - `ai_chatgpt_ask` — OpenAI (default `gpt-4o-mini`, override via
    `model:`)
  - `ai_gemini_ask` — Google (default `gemini-2.5-flash`)
  - `ai_lmstudio_ask` — local OpenAI-compatible at
    `http://localhost:1234/v1` (no key needed)
  - `ai_antigravity_ask` — stub returning a clean
    "no public API yet" error so the model can discover the capability
    and the user gets a setup hint when Google ships an SDK
  - `ai_list_providers` — inventory of which AI-as-tool providers are
    configured + reachable. The primary model uses this to decide
    which delegation tool to call.
- **`ai` family is always-on** in `tool_engine.tool_schemas_for()` —
  no host needs to be installed; if a provider key is missing the
  handler returns a clean error pointing at Settings → Sign-ins
  rather than the tool being filtered out of the schema.
- **REST fallback for Gemini** — when `google.generativeai` isn't
  installed (light-install user), the runner hits
  `generativelanguage.googleapis.com` directly. Tool works either way.
- **LM Studio reachability probe** — `_lmstudio_reachable()` does a
  1.5 s GET on `/models`; `list_providers()` surfaces the result so
  the primary model knows whether the local server is up before
  calling it.
- **AI Behaviour defaults for the `ai` family** — all 5 tools default
  to `allow` (calling another LLM is a read, not a mutation). The
  user can tighten any specific tool to `ask` in Settings if they
  want a confirmation before spending tokens on a delegation.
- **16 new tests** in `tests/test_ai_runner.py` covering: missing-key
  handling, empty-prompt rejection, antigravity stub, list_providers
  shape, tool-registry membership, every handler exists, always-on
  filter, and AI-Behaviour defaults.

### Changed

- `tool_engine.tool_schemas_for()` — `_local` always-on rule extended
  to `_local` + `ai`. Schema breakdown stays per-provider (anthropic /
  openai / google native shapes) — just the gate widened.
- `ai_behaviour._FAMILY_DEFAULTS` — added `"ai"` family table.
- `ai_behaviour.host_display_label("ai")` →
  `"AI delegations (ChatGPT · Gemini · LM Studio · Antigravity)"` so
  the Settings section header explains what it is.

### Notes

- Antigravity (Google's experimental coding-agent platform) has no
  public stable API as of 2026-05. The tool is registered as a stub so
  the schema is stable today; when Google ships an SDK we'll replace
  the body without touching the input schema.
- LM Studio defaults to `http://localhost:1234/v1`. Custom URL +
  optional API key live under `lmstudio` in Settings → Sign-ins
  (advanced — most users never set this).

### Tests

344 passing in `tests/` (up from 328), 24 in `cloud_backend/tests/`.

## [1.0.2] — 2026-05-13

The "alive again" hotfix release. Production Sentry alerts after
v1.0.1 revealed dead code paths, missing imports, and a handful of UX
gaps that made the app feel stagnant even when it was working. v1.0.2
ships the diagnosis + every fix in one shot.

### Fixed

- **Settings → Cloud Sync no longer crashes** — `_on_sync_now` raised
  `NameError: name 'QApplication' is not defined` (Sentry PYTHON-9).
  Added the missing import.
- **Transient network blips no longer kill a turn** — `llm_router`
  retries once on `APIConnectionError`, `httpx.ReadError`,
  `WinError 10054`, anthropic 529 / cloudflare 502-504 (Sentry
  PYTHON-7). Auth/quota errors still switch provider as before.

### Added

- **Per-host AI Behaviour defaults** — `ai_behaviour._FAMILY_DEFAULTS`
  maps each host family (revit / acad / max / outlook / blender / speckle
  / archhub) to its own policy table. New connectors slotted into
  `_FAMILY_DEFAULTS` get sensible defaults without touching the UI
  or the generic rules.
- **AI Behaviour panel in the legacy Settings dialog** — the section
  previously lived only in the Studio shell; users opening the gear
  from the chat window saw an empty old dialog. Settings now renders
  the dynamic per-host tool list (grouped by family, scroll-area
  capped at 260 px) plus the thinking-effort dropdown in both
  surfaces.
- **`+ Add Host` button in the chat header** — first-class entry
  point instead of being buried in the Studio sidebar / app menu.
  Routes to the Studio page when present, falls back to a modal
  `AddHostPanel` so the chat-only fallback path also gets it.
- **Live host status pills next to the brand** — one pill per
  detected host family (●green = broker reports a live session,
  ●amber = installed but no session, hidden = not detected). Probed
  every 6 s; never blocks the UI.
- **Startup self-test** — `_startup_self_test()` writes a one-block
  summary to `boot.log` on every launch: broker session counts, host
  installation paths, .NET SDK version, tool-registry breakdown by
  family. Diagnosing "nothing works" becomes a one-file lookup.
- **21 new tests** — coverage for `_FAMILY_DEFAULTS`,
  `tools_grouped_by_host()`, `host_display_label()`, and
  `_looks_like_transient_network()`. Total: 328 passing in `tests/`,
  24 in `cloud_backend/tests/`.

### Changed

- `ai_behaviour._DEFAULT_RULES` renamed to `_GENERIC_RULES` and made
  longest-pattern-first. Legacy name kept as an alias so external
  callers don't break.
- `ai_behaviour.tools_grouped_by_host()` added — single helper that
  pulls live `tool_engine.TOOLS`, applies family + suffix rules,
  groups by host, marks user overrides. UI consumes this instead of
  iterating `TOOLS` itself.
- `SettingsDialog` default size bumped 560 × 520 → 640 × 720 to fit
  the new AI Behaviour section without forcing a global scroll.

### Removed

- **Orphan files deleted** — `app/company_pets.py` (pet-strip
  decoration, no value), `app/do_build_2023.py`,
  `app/do_build_2024.py` (superseded by
  `auto_build.build_revit_connector(year)`).
- **Dangling `relay/**/*.ts` glob references scrubbed** from
  `agents/departments.py` (now `cloud_backend/**/*.py`).
- **`relay/` directory cleaned up** — `.vercel/` cache + leftover
  `node_modules/` removed (source files were deleted in v1.0.1).

## [1.0.1] — 2026-05-12

The "make it actually work" release. v1.0.0 shipped 22 features in a
single day; v1.0.1 is the bug-hunt + UX-polish sprint that followed.
30+ live-trace-driven fixes after real-world testing.

### Added

- **Settings → AI Behaviour** section
  - Extended-thinking effort: off / low / medium / high (mapped to
    Anthropic `budget_tokens`, Gemini 2.5 `thinkingBudget`, OpenAI
    o-series `reasoning_effort`)
  - Per-tool permission table: `allow` / `ask` / `deny` per registered
    tool, with sensible defaults (read-only allow, mutate ask)
  - Inline Approve / Deny buttons in chat when a tool returns
    `needs_confirmation`
- **Outlook bulk macros** to escape the per-message loop trap
  - `outlook_auto_categorize_by_sender()` — zero-arg one-shot,
    derives category from sender domain
  - `outlook_auto_categorize_by_subject_keywords(map)` — content-based
    tagging with `{keyword: category}` map
  - `outlook_set_categories_by_filter(...)` — one-call bulk apply
  - `outlook_list_distinct_senders(days)` — domains + counts for
    deriving categories
  - `outlook_list_sent_items(limit, days)` — sent-mail mirror
- **`outlook_execute_python`** — universal escape hatch. Model writes
  Python, runs in COM context with `outlook`, `ns`, `inbox`, `sent`,
  `drafts` globals injected. Pattern mirrors the existing
  `revit_execute_csharp` / `blender_execute_python`.
- **Refusal detector** — when a provider returns text matching known
  refusal patterns ("I cannot read", "I'm not able to", "my capabilities
  are limited") AND zero tool calls AND tools were available, the router
  blocks the provider for 10 min + auto-falls-through to the next.
- **Retry-without-tools** — when a provider returns empty text AND empty
  tool calls AND tools were sent, the router retries once with
  `tools=[]` + a "reply in 1-2 short sentences" suffix. Catches the
  "Gemini overwhelmed by 33 tools" failure mode.
- **Tool-schema relevance filter** — Gemini limited to ≤12 schemas per
  request, with family-keyword promotion. Stops empty responses caused
  by Gemini Flash's "too many tools" overwhelm.
- **Tool-result synthesizer** — when an LLM finishes a turn with empty
  text but successful tool calls, the router synthesizes a one-line
  summary from the most recent invocation (e.g. "Outlook: 966 inbox,
  3 unread"). No more blank bubbles after a successful tool run.
- **Procrastination detector** — local models that emit essays instead
  of calling tools get one auto-nudge ("call the tool now, no
  description") before the router gives up.
- **AUTHORITY grant** — explicit system-prompt clause telling the model
  the user already authorised tool access. Reduces refusal rate from
  models with conservative safety fine-tunes.
- **Skill-matcher host-context filter** — drops skills whose `requires`
  targets only an unrelated host family when the prompt clearly names
  a different one (e.g. "categorise emails" no longer suggests a Revit
  construction Skill).
- **Bubble reconciliation** — `_on_finished` now force-paints from
  `response.text` when the chunk signal hasn't arrived yet. Fixes the
  "1-chunk streaming race" that left bubbles blank for some providers.
- **Empty-response placeholder** — when LLM returns empty text and no
  tools fired, bubble shows clear "(empty response — provider returned
  no text. Check Settings → Providers for credit / quota issues.)"
- **Session-save four-layer guarantee**
  - `save_session` refuses to write when content is empty
  - Post-write roundtrip verification (re-read + assert counts)
  - AST guardrail script `scripts/check_session_saves.py` + pre-commit
    hook fails any call missing `messages=`
  - 9 contract tests pinning the invariants
- **Startup stub sweep** — `cleanup_empty_sessions()` runs on every
  launch so crashed-turn stubs from previous sessions don't pollute
  the THREADS rail.
- **Multi-line chat input** — Shift+Enter inserts newline, Ctrl+Enter
  also works, plain Enter submits. Input auto-grows 1..10 lines.
- **OpenRouter 409 recovery** — sign-in dialog now has "Or paste a key
  manually" button below the OAuth one. Click to flip into clipboard-
  watch mode when OpenRouter's auth-code endpoint rate-limits.
- **CHANGELOG.md** (this file).

### Changed

- **Local-model preferences re-ranked**
  - Modeling / analysis chains: `command-r7b` (Cohere tool-use
    specialist) first; `llama3.1:8b` second; coder variants as late
    fallback.
  - `deepseek-r1` removed from action chains (reasoning model burns
    1000+ tokens in `<think>` before acting). Kept in a dedicated
    `reasoning` chain for opt-in use.
  - `gemma4:latest` typo removed (model doesn't exist); replaced with
    real `gemma3` + `gemma2`.
- **System prompt softened** — old version's "ACT, do not describe"
  made Gemini emit empty turns after a tool call. New version
  explicitly says "after the tool runs, end with one or two short
  sentences. Never end a turn silently."
- **Ollama request options** — `temperature: 0.15`, `num_predict:
  4096`, `top_p: 0.9` sent on every request. Default 0.7 made models
  "explore" instead of acting on tool-use prompts.
- **Status-bar version** reads `VERSION` file dynamically; previously
  hardcoded `v0.27.6`.
- **Pricing tiers** reworked from 2 tiers (BYO/Studio @ $199) to 4
  tiers (BYO $0 / Solo $19 / Studio $79 / Firm $299+seat).
- **Saved-session filter** now requires at least one assistant message
  with non-empty content. Sessions where the LLM never replied are
  treated as stubs.
- **Schema-filter tool count** — Gemini gets ≤12 tools per request
  (previously 33+). Family promotion keeps the right ones in the slice.

### Fixed

- Sessions appearing in THREADS rail but loading as blank chats
  (autosave wrote the empty `Session` object, not `self.history`)
- Empty assistant bubble after PING OUTLOOK on Gemini Flash (33-tool
  overwhelm → no text, no tool calls)
- Gemini refusing to use Outlook tools despite AUTHORITY grant
  (refusal detector + fallback chain → Ollama command-r7b succeeds)
- Local Ollama passing placeholder `entry_id` strings like
  `"[each message in inbox]"` (sharpened tool descriptions + explicit
  bulk pattern in prompt + zero-arg macros that don't require loops)
- Typed text invisible in chat input (Fusion-style palette didn't
  apply QSS `color:` to `QPlainTextEdit`; now sets palette directly)
- Multi-line input height clipping (chrome buffer raised from 12px
  to 36px to cover QSS padding + frame + doc margin)
- Hardcoded `v0.27.6` in status bar (now reads `VERSION` file)
- Taskbar showing pythonw snake icon despite AUMID set (Windows
  needed an explicit registry entry at
  `HKCU\Software\Classes\AppUserModelId\io.archhub.studio`)
- Empty Bubble streaming race (1-chunk responses processed `finished`
  before the chunk signal landed)

### Removed

- `gemini-1.5-pro` references (Google retired model in v1beta).
- Hardcoded version string in status bar.
- 2-tier pricing model.

### Stats

- 31 commits since v1.0.0
- 300/300 tests green (started day at 29 tests)
- ~5,500 LOC added across 50+ files
- 0 production bugs reported (still pre-public-beta)

---

## [1.0.0] — 2026-05-11

Initial public release. Open-core architecture.

### Added

- Studio shell (PyQt6 desktop) with brand v0.1 (terra/graphite/ochre)
- Multi-instance `@session` routing — Revit × N, AutoCAD × N, Max × N,
  Outlook × N accounts. Chat composer parses `@<token>` to pin a turn
  to a specific session.
- Connectors for Revit (2020-2025) / AutoCAD 2024-2026 / 3ds Max
  2025-2026 / Blender 4+ / Outlook (COM) / Speckle (cloud)
- Marketplace v0.39 — signed Skills + semver-pinned install. Ed25519
  signing module with pinned trust roots.
- Workflow canvas v2 — node editor, undo/redo (100-entry stack),
  Ctrl+D duplicate, Delete to remove, arrow nudge, Ctrl+A select all,
  minimap with click-to-pan.
- Reality Check — per-host 24h sparklines on the Telemetry page,
  driven by a ring-buffer `health_history` module.
- Sectioned Settings — Providers / About / Diagnostics tabs.
- Zero-barrier onboarding — first-launch dialog offers silent Ollama
  install + qwen2.5:3b model pull for users with no AI tooling.
- ArchHub Cloud client scaffold — bearer auth, PKCE sign-in flow,
  OpenAI-compatible streaming client, status-bar quota meter. Backend
  yet to be built; spec at `docs/BACKEND_SPEC.md`.
- 4-tier pricing UI — BYO ($0) / Solo ($19) / Studio ($79) /
  Firm ($299+seat).
- Inno Setup installer script at `installer/setup.iss`.

[1.0.1]: https://github.com/archhub/archhub/releases/tag/v1.0.1
[1.0.0]: https://github.com/archhub/archhub/releases/tag/v1.0.0
