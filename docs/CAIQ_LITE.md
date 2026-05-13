# CAIQ-Lite — ArchHub answers

**CAIQ-Lite v3.1** (Consensus Assessment Initiative Questionnaire — Lite) is the security-review form most mid-market buyers send before signing. Filling it out once and keeping it current means we answer in 2 minutes instead of 2 hours when a deal comes in.

This doc is the canonical pre-filled answer set. When a buyer sends their version of the form, copy-paste from here.

> If you're a buyer who landed here looking for an answer to a specific question, the table of contents below mirrors the official CAIQ-Lite domain numbering.

---

## A&A — Audit & Assurance

| # | Question | Answer |
|---|---|---|
| A&A-01 | Do you maintain an independent audit certification (SOC 2, ISO 27001)? | **Not yet.** Type I planned for Q2 2027. CSA STAR Self-Assessment in progress for Q3 2026. |
| A&A-02 | Do you provide tenants with audit reports on request? | **Yes**, once SOC 2 Type I is issued. Today: this doc + Trust Center page. |
| A&A-03 | Do you allow tenant audits of your environment? | **No.** Single-tenant audits are not feasible at our stage. SOC 2 will be the proxy. |

## AIS — Application & Interface Security

| # | Question | Answer |
|---|---|---|
| AIS-01 | Is application source code reviewed for vulnerabilities? | **Yes.** Dependabot scans weekly. Founder reviews every PR (solo team). |
| AIS-02 | Are inputs validated to prevent injection (SQL, XSS, command)? | **Yes.** All DB access via parameterised queries. Tool engine validates JSON Schema before dispatch. |
| AIS-03 | Is data classified in transit and at rest? | **Yes.** TLS 1.2+ in transit. AES-256 at rest (Fly.io volume + SQLite full-file). |

## BCR — Business Continuity & Resilience

| # | Question | Answer |
|---|---|---|
| BCR-01 | Do you have a business continuity plan? | **Partial.** Drafted; formal document Q2 2026. |
| BCR-02 | Do you perform DR exercises? | **Quarterly** restore tests of cloud_backend snapshots. |
| BCR-03 | Do you have an RPO/RTO target? | **RPO: 24 h** (daily snapshots). **RTO: 4 h** (restore + DNS swap to a new Fly.io app). |

## CCC — Change Control & Configuration Management

| # | Question | Answer |
|---|---|---|
| CCC-01 | Is there a documented change-management process? | **Yes.** All prod changes ship via signed git tag → GitHub Actions release pipeline. |
| CCC-02 | Are configuration changes logged and reviewable? | **Yes.** Every commit is reviewable on <https://github.com/Fargaly/ArchHub/commits>. Fly.io deploys are logged + retained 30 days. |

## CEK — Cryptography, Encryption & Key Management

| # | Question | Answer |
|---|---|---|
| CEK-01 | Is data encrypted at rest? | **Yes.** AES-256 via Fly.io volume + SQLite encrypted. |
| CEK-02 | Is data encrypted in transit? | **Yes.** TLS 1.2+ enforced; HSTS preload pending. |
| CEK-03 | How are encryption keys managed? | Fly.io-managed for infrastructure. App-level secrets in GitHub Actions secrets (encrypted with libsodium sealed box). |
| CEK-04 | Are keys rotated on a schedule? | **Annually** for app-level secrets. Provider-managed for cloud infra. |

## DCS — Data Centre Security

| # | Question | Answer |
|---|---|---|
| DCS-01 | Where is data physically hosted? | Fly.io regions — US East (`iad`) primary, EU West (`ams`) optional per customer. |
| DCS-02 | Are data centres SOC 2 / ISO 27001 certified? | **Yes.** Fly.io's underlying infrastructure carries SOC 2 + ISO 27001 + PCI DSS. |

## DSP — Data Security & Privacy Lifecycle

| # | Question | Answer |
|---|---|---|
| DSP-01 | Do you have a data classification policy? | **In draft.** Public / Internal / Confidential tiers, formal doc Q3 2026. |
| DSP-02 | Do you have data retention policies? | **Yes.** Chat history kept only while user account active. Telemetry: 90 days. Backups: 30 days. |
| DSP-03 | Do you support data deletion on request? | **Yes.** GDPR / CCPA compliant. Email `privacy@archhub.app` → 30-day deletion SLA. |
| DSP-04 | Do you use customer data for AI training? | **No, never** unless customer explicitly opts in. Default is OFF and we have no plan to make it ON. |

## GRC — Governance, Risk & Compliance

| # | Question | Answer |
|---|---|---|
| GRC-01 | Do you have a formal information security policy? | **In draft.** Templates from SOC 2 readiness work. Q3 2026 finalisation. |
| GRC-02 | Is policy reviewed annually? | **Yes** going forward (committed in security review log). |
| GRC-03 | Who approves security policies? | Founder + outside security advisor (engaged Q1 2027). |

## HRS — Human Resources

| # | Question | Answer |
|---|---|---|
| HRS-01 | Background checks on employees? | **N/A.** Solo founder. Will apply at first hire. |
| HRS-02 | Onboarding security training? | **N/A.** Solo founder; documented procedure ready for first hire. |
| HRS-03 | Termination access revocation? | **N/A.** Solo founder. |

## IAM — Identity & Access Management

| # | Question | Answer |
|---|---|---|
| IAM-01 | Is MFA enforced for privileged access? | **Yes.** GitHub, Fly.io, Stripe, Anthropic, OpenAI, Resend — all MFA. |
| IAM-02 | How are passwords managed? | **No passwords.** Magic-link sign-in + OAuth (PKCE for OpenRouter). |
| IAM-03 | Are user access rights reviewed? | **Quarterly.** Documented in `docs/SECURITY_REVIEW_LOG.md` (in draft). |
| IAM-04 | Is least-privilege enforced? | **Yes.** Fly.io tokens scoped per app. GitHub fine-grained tokens for marketplace push. |

## IPY — Interoperability & Portability

| # | Question | Answer |
|---|---|---|
| IPY-01 | Can customers export their data? | **Yes.** Chat history → JSON, marketplace packs → signed zip. |
| IPY-02 | Open standards used? | OAuth 2.0, PKCE, JSON, OpenAI-compatible API surface. |

## IVS — Infrastructure & Virtualization

| # | Question | Answer |
|---|---|---|
| IVS-01 | Are environments segregated (dev / staging / prod)? | **Yes.** Separate Fly.io apps; no cross-environment service connections. |

## LOG — Logging & Monitoring

| # | Question | Answer |
|---|---|---|
| LOG-01 | Are security events logged? | **Yes.** Fly.io platform logs + Sentry exceptions + app-level audit log. |
| LOG-02 | Are logs reviewed? | **Sentry alerts → founder within 60 s.** Daily skim of access logs. |
| LOG-03 | Log retention period? | 30 days standard; security events retained 1 year. |

## SEF — Security Incident Management

| # | Question | Answer |
|---|---|---|
| SEF-01 | Is there an incident response process? | **In draft** (`docs/IRP.md` Phase A of SOC 2 readiness). |
| SEF-02 | Are tenants notified of incidents? | **Yes.** 24 h communication SLA. Email + Trust Center post. |
| SEF-03 | Have you had a security breach? | **No.** None to date. |

## STA — Supply Chain Management, Transparency & Accountability

| # | Question | Answer |
|---|---|---|
| STA-01 | Is sub-processor list published? | **Yes** — see Trust Center page or `docs/TRUST_CENTER.md`. |
| STA-02 | Are DPAs signed with sub-processors? | **Yes** — every sub-processor in the list. |
| STA-03 | Are tenants notified of sub-processor changes? | **Yes.** 30-day advance notice via email + Trust Center. |

## TVM — Threat & Vulnerability Management

| # | Question | Answer |
|---|---|---|
| TVM-01 | Vulnerability scanning cadence? | **Weekly** (Dependabot) + **continuous** (Sentry runtime). |
| TVM-02 | Patch SLA for critical CVEs? | **48 h** for Critical, **1 week** for High. |
| TVM-03 | Do you run pen tests? | **Not yet.** Planned annually starting Q2 2027 with SOC 2 engagement. |

## UEM — Universal Endpoint Management

| # | Question | Answer |
|---|---|---|
| UEM-01 | Endpoint device management? | **N/A** at solo-founder stage. Founder endpoints managed personally with FileVault / BitLocker. |

---

## Footer

**Effective date:** 2026-05-13
**Next review:** 2026-08-13 (quarterly)
**Contact for security questions:** security@archhub.app
**Contact for privacy questions:** privacy@archhub.app

When a buyer's procurement form differs from CAIQ-Lite v3.1 numbering, map their questions to the closest answer here. The substance is the same; the labels move around.
