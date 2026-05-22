# ArchHub SOC 2 Type I readiness pack

**Purpose:** a SOC 2 Type I audit confirms that — at a point in time —
your security controls are designed appropriately for the AICPA Trust
Services Criteria. This doc inventories what we already have, what's
missing, and the policies an auditor will ask for.

> Type I = "you have the controls"  
> Type II = "you have AND operate the controls for 3–12 months"
>
> Most enterprise procurement teams accept Type I as a starting point;
> they ask for Type II at the 12-month renewal. Plan accordingly.

## Audit firms (USA, suited to early-stage)

| Auditor | Approx Type I cost | Notes |
|---|---|---|
| **Drata + a partner CPA firm** | $5k–$8k Drata + $7k–$15k audit | Most popular for seed-stage. Drata's automation halves prep time. |
| **Vanta + a partner CPA firm** | $8k–$12k Vanta + $7k–$15k audit | Same playbook as Drata; pricier subscription |
| **Secureframe** | $7k–$12k + audit | Cheaper than Vanta |
| **Bare CPA firm (no platform)** | $10k–$25k all-in | Slower; spreadsheet-heavy. Realistic if you have a security generalist on staff |

**Recommendation for ArchHub Year 1:** Drata + small CPA partner.
$15k–$22k total. 8–10 weeks from kickoff to report.

## Trust Services Criteria scope

For ArchHub's stage we recommend filing for **Security** only at first.
Confidentiality is easy to add at renewal. Availability requires SLAs
we don't yet make.

| Criteria | In Year 1? | Why |
|---|---|---|
| Security | ✅ Yes | Required — table stakes |
| Availability | ❌ No | We don't publish an SLA yet |
| Confidentiality | ❌ Defer to Year 2 | Adds 1–2 weeks of prep, marginal sales value |
| Processing Integrity | ❌ No | Not applicable — we don't process transactions |
| Privacy | ❌ Defer | Add when we handle PHI / payment data directly |

## Controls inventory — what we already have

| Control | Status | Evidence |
|---|---|---|
| Multi-factor auth on all admin accounts | ✅ | GitHub MFA enforced, Stripe MFA |
| SSO for production access | ⚠️ Partial | GitHub OAuth in place; cloud_backend admin uses email magic-link (acceptable) |
| Encryption at rest | ✅ | Fly.io disk encryption; SQLite db on encrypted volume |
| Encryption in transit | ✅ | TLS 1.2+ enforced; Fly.io terminates |
| Least-privilege IAM | ⚠️ Partial | Fly.io token has full org scope — split into deploy + observe tokens |
| Secrets management | ✅ | Fly.io secrets + GitHub Actions secrets; no plaintext in repo |
| Vulnerability scanning | ✅ | Dependabot weekly + Sentry runtime errors |
| Logging + monitoring | ✅ | Sentry + Fly.io logs + telemetry consent flow |
| Backup + restore | ⚠️ Partial | Fly.io daily snapshots but **no documented restore test** |
| Change management | ✅ | All prod changes via git tag → GitHub Actions release |
| Code review on prod changes | ⚠️ Partial | Solo founder — no second reviewer. Document this as an "accepted risk" |
| Incident response plan | ❌ Missing | Need IR runbook + on-call rotation (Phase A below) |
| Vendor management | ⚠️ Partial | Stripe + Anthropic + Fly.io DPAs signed; list incomplete |
| Background checks | N/A | Solo founder |
| Security awareness training | ⚠️ Partial | Need annual self-attestation log |
| Asset inventory | ✅ | Repo manifest + Fly.io app list |

## Phase A — Gaps to close before audit kickoff (4–6 weeks)

1. **Incident Response Plan** — write `docs/IRP.md` covering:
   - Severity definitions (P0/P1/P2/P3)
   - Communication tree (who emails customers within 24h)
   - Forensic capture procedure
   - Post-mortem template
2. **Backup restore test** — run a real restore of `cloud_backend.db`
   into a staging Fly.io app. Document the runbook + the duration.
3. **Split Fly.io API tokens** — separate `deploy` from `observe`.
   Document each token's scope in `cloud_backend/.fly/README.md`.
4. **Vendor inventory** — `docs/VENDORS.md` listing every SaaS we touch:
   Anthropic, OpenAI, Google AI, OpenRouter, Stripe, Resend, Fly.io,
   Sentry, PostHog, GitHub. For each: DPA status, data shared, region.
5. **Annual security review log** — `docs/SECURITY_REVIEW_LOG.md`.
   Self-attest yearly: "Reviewed all controls 2026-05-13. No changes."
6. **Customer-facing security page** at `archhub.io/security`. Lists
   what we have. Builds buyer trust ahead of the audit.

## Phase B — Policies the auditor will ask for

Auditors expect roughly 15 policy docs. Templates exist in Drata/
Vanta/Secureframe; sketches here so you know what's coming.

1. **Information Security Policy** — top-level statement; everything
   else flows from this
2. **Acceptable Use Policy** — what employees can/can't do with company
   data and devices
3. **Access Control Policy** — least privilege + MFA + offboarding
4. **Asset Management Policy** — laptop inventory + tracking
5. **Backup & Restore Policy** — frequency, retention, restore tests
6. **Business Continuity Plan** — what happens if our hosting goes
   down
7. **Change Management Policy** — code review, deployment approval
8. **Data Classification Policy** — public, internal, confidential
9. **Encryption Policy** — at rest, in transit, key rotation
10. **Incident Response Plan** — see Phase A above
11. **Network Security Policy** — firewalls, segmentation (mostly N/A
    for SaaS-only orgs but auditors still want the policy)
12. **Password Policy** — even though we use SSO/magic-link, document
    requirements
13. **Risk Assessment Policy** — annual review cadence
14. **Vendor Management Policy** — DPA requirements + review cadence
15. **Vulnerability Management Policy** — patching SLA, scan cadence

Drata's template library covers all 15 with company-name templates
ready to sign off. **Strongly recommend using their templates** rather
than writing from scratch — auditors recognise the format and the
review is faster.

## Phase C — Controls-mapping spreadsheet

The auditor will want a sheet mapping each TSC criterion to the
specific control(s) that satisfy it. Drata generates this from the
control library. Sample row:

| Criterion | Control | Evidence | Test of design |
|---|---|---|---|
| CC6.1 — Logical access | MFA enforced on GitHub, Fly, Stripe, GCP | Screenshots of MFA-required policy | Auditor logs in; can't proceed without MFA |
| CC6.2 — New user provisioning | Onboarding checklist in `docs/ONBOARDING.md` | Onboarding doc + most recent hire ticket | Auditor reviews newest hire |
| CC6.3 — Periodic access review | Quarterly access review log | Most recent review entry | Auditor checks last entry is < 90 days old |

## Phase D — Audit kickoff timeline

| Week | Activity |
|---|---|
| 0 | Engage Drata + CPA partner. Sign LOE + invoice. |
| 1–2 | Drata onboarding; configure integrations (GitHub, Fly.io, AWS/GCP if any). |
| 3–4 | Auditor scopes the engagement. Close any Phase A gaps. |
| 5–6 | Auditor performs design walkthroughs. Provide policies + evidence. |
| 7 | Draft report. Address any findings. |
| 8 | Final SOC 2 Type I report issued. |

## Cost summary (Year 1)

| Item | Cost |
|---|---|
| Drata annual subscription | ~$7,000 |
| CPA audit fee (Type I) | ~$10,000 |
| Lawyer review of MSA + DPA template | ~$1,500 |
| Status page subscription (Statuspage / Atlassian) | $300 |
| **Total Year 1** | **~$19,000** |

| Year 2 |  |
|---|---|
| Drata renewal | $7,000 |
| Type II audit (12-month window) | $15,000 |
| **Total Year 2** | **~$22,000** |

## What this unlocks for sales

| Buyer profile | Likely ask |
|---|---|
| Solo architect / 1–5 person firm | None — they don't ask |
| 10–50 person AEC studio | SOC 2 Type I is "nice to have" |
| Enterprise general contractor (Skanska, Bechtel, AECOM) | **Required.** Type II expected for 100+ seat deals |
| Government / public sector | Required + FedRAMP eventually |

Year 1 Type I unlocks the **50–500 employee mid-market** that's our
near-term ICP. Year 2 Type II unlocks the enterprise tier.

## Action

When ready:
1. Sign with Drata (1-hour task; their AE will walk through pricing)
2. Pick a CPA partner from Drata's "audit partner" tab
3. Block 6 weeks of calendar before kickoff for Phase A gap-closing
4. Use templates from Drata for the 15 policies in Phase B

This doc lives in the repo so the work doesn't reset when a security
generalist is hired. The Phase A gaps are concrete tasks any
new-hire IT person can pick up.
