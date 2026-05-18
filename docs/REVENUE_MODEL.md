# ArchHub — Revenue Model

> Drafted 2026-05-14 · Working assumptions

## 1. Pricing tiers

| Tier | Price | Audience | What's included | Limits |
|---|---|---|---|---|
| **Solo** | Free | Individual architects, students, hobbyists | Local-first canvas. All 60+ tools. BYO API keys. Single-user. Local memory only. Unlimited Skills (local). | No cloud Skills sync. No team sharing. No managed LLM proxy (BYO keys). |
| **Studio** | $39 / user / mo (annual $39 × 10 = $390/yr — 2 months free) | Practicing firms, 5–25 seats | Everything in Solo + cloud-synced Skills + cloud memory + managed LLM proxy (5M tokens/mo included) + Revit / AutoCAD / Max signed plugins + email support | 5M proxy tokens/mo (then BYO key kicks in). Up to 25 seats per account. |
| **Firm** | $79 / user / mo (annual $79 × 10 = $790/yr) | Established firms, 25–150 seats | Everything in Studio + SSO (Okta / Azure AD / Google) + role-based permissions + audit log export + 20M proxy tokens / user / mo + priority support + per-host quotas | 20M proxy tokens / user / mo. |
| **Enterprise** | $30K–$120K / yr base + per-seat | Firms with compliance / on-prem needs, 100+ seats | Self-hosted control plane (Docker / K8s deployment). Dedicated support engineer. Custom integrations. SLA. SOC2 / ISO docs. Unlimited proxy or BYO. | None. |

### Why these numbers

- **$39 Studio anchor:** matches typical AEC tool subscriptions
  (ArchiCAD lite, Enscape personal, Rhino Inside services) the
  buyer already has approval to spend on.
- **$79 Firm step:** doubles the price for the features (SSO,
  audit) that only firms above ~25 seats actually need. Stops solo
  buyers from accidentally over-paying.
- **Token budgets:** Studio's 5M ≈ $15-20 of cloud LLM at 2026
  prices. Margin per seat after token cost ≈ $20. Firm's 20M ≈
  $60-80 cost, still ~$0-19 margin per seat — Firm makes its money
  on the SSO / audit features, not the proxy.

## 2. Unit economics

### Per-seat monthly economics (Studio tier, 2026 prices)

| Line item | Amount |
|---|---|
| Revenue | $39.00 |
| LLM proxy cost (avg user, 3M tokens actual / 5M cap) | -$10.50 |
| Cloud infra (Fly compute + memory writes) | -$1.20 |
| Stripe + processor | -$1.50 |
| Customer success allocation | -$3.00 |
| **Gross margin** | **$22.80 (58 %)** |

### Per-seat monthly economics (Firm tier)

| Line item | Amount |
|---|---|
| Revenue | $79.00 |
| LLM proxy cost (avg user, 12M tokens actual / 20M cap) | -$42.00 |
| Cloud infra | -$2.00 |
| Stripe | -$3.00 |
| SSO/Audit infra | -$1.50 |
| Customer success | -$4.00 |
| **Gross margin** | **$26.50 (34 %)** |

Note: Firm margin is thinner per-seat but volume + retention is
much higher (annual contracts, SSO-locked-in).

## 3. CAC + LTV targets

| Tier | Target CAC | Target LTV | LTV/CAC |
|---|---|---|---|
| Solo | $0 (organic) | N/A | — |
| Studio | $200 / customer (≈5 seats avg) | $39 × 5 × 18 mo = $3,510 | 17.5× |
| Firm | $2,500 / firm (≈30 seats avg) | $79 × 30 × 30 mo = $71,100 | 28.4× |
| Enterprise | $25,000 / deal | $80K × 3 yr = $240K | 9.6× |

## 4. Revenue trajectory

### 12-month projection (conservative)

Assumes 3 lighthouse customers go paid in month 3, then steady 1–2
new firms per month afterwards.

| Month | New firms | Total firms | Avg seats | Tier mix | MRR |
|---|---|---|---|---|---|
| 1 | 0 | 0 | — | Solo only (free) | $0 |
| 2 | 0 | 0 | — | Solo only | $0 |
| 3 | 3 (lighthouses, free year) | 3 | 8 | Free year | $0 |
| 4 | 2 | 5 | 7 | 2 Studio | $546 |
| 5 | 2 | 7 | 7 | 4 Studio | $1,092 |
| 6 | 3 | 10 | 8 | 6 Studio, 1 Firm | $2,344 |
| 7 | 3 | 13 | 8 | 9 Studio, 1 Firm | $3,114 |
| 8 | 4 | 17 | 9 | 12 Studio + 2 Firm | $5,148 |
| 9 | 4 | 21 | 9 | 15 Studio + 3 Firm | $6,732 |
| 10 | 5 | 26 | 9 | 19 Studio + 4 Firm | $9,108 |
| 11 | 5 | 31 | 10 | 22 Studio + 6 Firm | $13,320 |
| 12 | 6 | 37 | 10 | 26 Studio + 8 Firm | $16,460 |

Year-end ARR ≈ **$197K**. Conservative because it assumes zero
churn and zero enterprise deals — first enterprise deal would
roughly double ARR.

### 24-month projection (with one enterprise deal)

Assumes one $80K/year enterprise deal closes month 18:

| Month | MRR | Cumulative ARR |
|---|---|---|
| 12 | $16,460 | $197K |
| 18 | $32,500 | $390K |
| 24 | $58,000 + $80K Ent | $776K |

Path to $1M ARR by month 30.

## 5. Cost structure (year 1)

| Category | Annual cost |
|---|---|
| Founder salary (Fargaly, deferred until ARR > $10K MRR) | $0 → $60K |
| LLM proxy compute (Fly + token pass-through) | $4K |
| Stripe / processor fees | 3 % of revenue |
| Cloud infra (Fly, Postgres, R2, Sentry) | $3.6K |
| Code signing certificate | $250 / yr |
| Domain / SSL / misc | $200 |
| Marketing (ads, conference, swag) | $5K |
| **Total fixed (excl. salary)** | **~$13K** |

Break-even MRR: **$1,200 ≈ month 5** (excl. salary), or month 12
including a $60K founder draw.

## 6. Money in vs money out (today)

| Money in | $0 |
| Money out | Anthropic API ~$30/mo, Fly trial → expired, domain ~$15/mo |
| **Net burn** | **~$45/mo** (until Fly card added) |

**Action: add Fly card (~$50/mo committed) to unblock public demos +
managed proxy.**

## 7. Funding

We don't need outside money to reach break-even — $13K/year fixed +
$60K deferred founder salary is bootstrappable from the first 10–15
paying firms.

If we do raise:

- **Pre-seed ($200-400K, +18 mo runway)** is appropriate after
  hitting **5 paying firms** and shipping a stable v1.4.1. Smaller
  raise = less dilution; only justified if customer demand is
  outrunning our ability to ship.
- **Seed ($1.5-3M)** only after **$10K MRR** + **clear retention
  data** (3+ months of net revenue retention > 100 %).
- **Series A** after **$50K MRR**, with clean unit economics,
  reference customers in 3 regions, signed Autodesk Partner status.

The pricing is designed so the company is fundable but not
fund-dependent — we want the optionality, not the obligation.

## 8. Key risks to the model

| Risk | Mitigation |
|---|---|
| **LLM costs spike** | BYO-key kicks in past quotas. We don't lose money serving heavy users. |
| **Free Solo tier cannibalises Studio** | Studio's lock-ins (cloud Skills sync, team library, signed plugins) are the upgrade triggers. |
| **Customer concentration** | No customer > 15 % of revenue until $100K MRR. |
| **Compliance surprise (SOC2 audit blows up)** | SOC2 readiness already documented; Firm tier doesn't claim full SOC2 until audit complete. |
| **Autodesk hostility** | Multi-host strategy means we survive a Revit lockout. Even so, Revit-only firms are 60 % of market; losing it would halve TAM. |
