# ArchHub Trust Center — source content

**Purpose:** content that mirrors what publishes at <https://archhub.io/security>. Lists every security control we have so prospects can answer their own "is ArchHub secure?" question without us getting on a call.

Updated whenever a real control changes. Reviewed quarterly.

---

## Last reviewed
2026-05-13 by Ahmed Yasser Fargaly, Founder

## At a glance

| Area | Status |
|---|---|
| Data encryption at rest | Host-level only. The Fly.io volume holding `archhub_cloud.db` and the brain replicas is reported encrypted by Fly.io (`flyctl volumes list`, recorded in `docs/USER_DATABASE.md`). ArchHub applies no application-level or end-to-end encryption; ArchHub's systems can read stored content. |
| Data encryption in transit | TLS 1.2+ enforced everywhere |
| Authentication | OAuth + magic-link (no passwords stored) |
| Multi-factor auth | Required for all admin + production accounts |
| Code signing | Azure Trusted Signing (in progress — v1.1.x) |
| Crash + error telemetry | Sentry, opt-in, PII-redacted at source |
| Usage analytics | PostHog, opt-in, PII-redacted at source |
| Independent audit | SOC 2 Type I planned for Year 2 (see public roadmap) |
| Self-assessment | CSA STAR Self-Assessment (filing in progress) |
| Vulnerability scanning | Dependabot weekly + Sentry runtime |
| Data residency | Fly.io EU / US regions; selectable per-customer at Studio tier |
| Vendor sub-processors | Listed below; DPAs in place for each |

## What we collect

**The desktop app sends nothing by default.** Telemetry is opt-in — you see the consent dialog on first run.

If you opt in:

| Channel | What | Why |
|---|---|---|
| Sentry crash reports | Stack traces, OS + app version, anonymous user id | Fix crashes before they hit other users |
| PostHog usage events | Anonymised event names (e.g. `chat_message_sent`), session duration, anonymous user id | Understand which features get used |
| Skill marketplace downloads | Pack id + version + your user id | Track pack popularity for authors |

We **never** transmit:
- Your prompts or model responses
- Project file paths or names
- API keys
- Outlook email content
- Revit / AutoCAD / Max document contents
- Anything from `localhost:9876+` connector traffic

Redaction happens at the source — `app/pii_redactor.py` in this repo is the implementation, open for inspection.

## What our cloud touches

For users on Cloud or Solo/Studio tiers, the cloud backend at `cloud.archhub.io` (Fly.io) stores:

- Email address (sign-in identifier)
- Stripe customer + subscription IDs (for billing only — full PAN never touches us)
- Your cloud brain copy, when cloud sync is on. When cloud sync is on, ArchHub keeps a copy of your brain on our servers so it can reach your other devices and your firm. That copy is not end-to-end encrypted, and ArchHub's systems can read it. Recognised API-key formats are blocked from upload. Deleting your cloud brain removes your personal copy; entries you shared with a firm are not removed. (This is the sentence the public Cell website is to carry; its text lives in `13.NODE-LANGUAGE/nodelang/cell_website.py` and is on no published page today.)
- Chat history sync to ArchHub's cloud: does not exist today (no chat-history table in `cloud_backend/db.py`, no such endpoint in `docs/CLOUD_API.md`). The desktop's **Sync sessions** button pushes sessions to a private GitHub repository you own (`app/cloud_sync.py`), not to ArchHub's servers. Hosted-mode chat writes `usage_log` counters (`cloud_backend/proxy.py`); a chat turn you explicitly approve for training is posted to `/v1/memory/capture` and stored as a `training_samples` row (`cloud_backend/main.py`). Neither the database nor the brain replicas are application-level encrypted.
- Marketplace pack uploads + downloads
- Token-usage counters for billing (provider name + count, never prompt content)

Anyone on the **BYO Key** tier never touches our cloud at all.

## Sub-processors

| Vendor | Why | Region | DPA |
|---|---|---|---|
| Anthropic | LLM provider (Claude) | US | Signed |
| OpenAI | LLM provider (GPT) | US | Signed |
| Google AI | LLM provider (Gemini) | US | Signed |
| OpenRouter | LLM router for multiple providers | US | Signed |
| Stripe | Payments | US + EU | Signed |
| Resend | Magic-link emails | US | Signed |
| Fly.io | Cloud backend hosting | US + EU regions | Signed |
| Sentry | Crash telemetry (opt-in) | EU | Signed |
| PostHog | Usage telemetry (opt-in) | EU | Signed |
| GitHub | Source code + release artifacts | US | Signed (Microsoft DPA) |
| Cloudflare | DNS + DDoS protection | Global edge | Signed |

## Security practices

### Authentication & access
- Magic-link sign-in — no passwords stored anywhere
- OAuth 2.0 with PKCE for OpenRouter sign-in
- Multi-factor auth (MFA) enforced on every admin account (GitHub, Fly.io, Stripe)
- All production secrets rotated annually

### Code & deployment
- Every production change ships via a git tag → GitHub Actions release pipeline
- Authenticode signing of the Windows installer (Azure Trusted Signing)
- Ed25519 signing for marketplace skill packs (signature re-verified post-download)
- Dependabot scans dependencies weekly; CVE > Medium severity gets a same-week fix

### Data
- Encryption at rest: Fly.io volume encryption only (host-level, as `flyctl volumes list` reports it; `docs/USER_DATABASE.md`). No application-level encryption: the SQLite database and brain replicas on that volume are not encrypted by ArchHub, and ArchHub's systems can read them.
- Encryption in transit: TLS 1.2+ on every endpoint, HSTS enforced
- Backups: nightly Fly.io snapshots, 30-day retention, restore-test documented

### Incident response
- Sentry alerts to founder within 60 s of a production crash
- 24h communication SLA to affected customers
- Post-mortem published in <https://github.com/Fargaly/ArchHub/issues?q=label%3Apost-mortem> for material incidents

## Compliance roadmap

| Standard | Status | Target |
|---|---|---|
| **CSA STAR Self-Assessment** | In progress | Q3 2026 |
| **CAIQ-Lite questionnaire** | Available on request (PDF) | Now |
| **SIG Lite questionnaire** | Available on request (PDF) | Now |
| **SOC 2 Type I** | Plan ready (docs/SOC2_READINESS.md) | Year 2 (Q2 2027) |
| **SOC 2 Type II** | Follows Type I | Q4 2027 |
| **ISO 27001** | Considering | Year 3 |
| **GDPR (EU)** | In compliance — data processing agreement available | Now |
| **CCPA (California)** | In compliance — opt-out form available | Now |

## Reporting a security issue

Email **security@archhub.io** with as much detail as you can. We respond within 24h. We do not yet run a paid bug bounty, but credited disclosures get a hat tip in the release notes.

## Public commitments

- We will never sell your data.
- We will never train an LLM on your prompts without explicit opt-in.
- We will publish an annual transparency report (first one: Q1 2027) listing every government data request received.

## Questions?

This page covers the most common procurement questions. For anything not covered, email **security@archhub.io** or ask in <https://discord.gg/archhub>.

---

## Internal: where this content goes

- `landing/security.html` — public-facing page (mirror of this doc, prettier)
- `docs/CAIQ_LITE.md` — full CAIQ-Lite spreadsheet, attached to procurement reviews
- `docs/SOC2_READINESS.md` — internal roadmap to Type I (already shipped)
- `cloud_backend/main.py` — `/security.txt` endpoint (RFC 9116) points back here
