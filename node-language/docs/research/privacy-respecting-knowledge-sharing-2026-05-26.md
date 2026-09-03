# Brain · privacy-respecting knowledge sharing · research + prototype

**Triggered by**: founder Q10 comment 2026-05-26 — *"figure out a way for sharing
knowledge without determining privacy, do the research... and prototype."*

**Output**: prior-art scan + proposed architecture + threat model + concrete
1-week prototype slice. No code lands without founder signing the picks at the
bottom.

---

## The problem in one sentence

The brain captures everything you do. Some of that should help your firm,
even other firms. Most of it shouldn't. **How do users mark what crosses
each boundary, with one click, defaulting to "no"?**

## The boundaries

```
            USER  ──  PROJECT  ──  FIRM  ──  COLLECTIVE (cross-firm pool)
            ↑           ↑          ↑           ↑
            your        per         per        ArchHub-wide
            machine     project     org        shared pool
            only        team        team       (opt-in, drives
                                                 the future hosted
                                                 models · Brain #33)
```

Today: USER + PROJECT + FIRM scopes exist in brain (per AgDR-0044 + Q10 fork
FB4=opt-in). COLLECTIVE doesn't exist yet — it's the substrate for the
collective-model training north star (Brain #33).

## What gets shared (the unit)

A brain **fact** is the atom. Shape:

```
{
  id:           "f_abc123",
  kind:         "fact" | "skill" | "wire-version" | "geometry" | "image",
  scope:        "user" | "project" | "firm" | "collective",
  shareable:    true | false,    ← NEW per this proposal
  payload:      { ... },
  payload_pii:  { ... },         ← NEW: PII split kept ONLY at USER scope
  redacted:     bool,            ← NEW: copy that's safe at higher scopes
  created_at:   "2026-05-26T...",
  origin:       { user_id, project_id, firm_id }
}
```

The `shareable` flag is the **only place the user makes a privacy
decision**. Everything else flows from it.

## Prior art (read this first)

| What | Where | Lesson for ArchHub |
|---|---|---|
| **Speckle SHARE scopes** | speckle.systems · 5 visibility levels (private / link / project / workspace / public) | Per-object scope works; UX must default to most-private |
| **Notion sharing model** | per-page permission inheritance + workspace defaults | Cascade is convenient but error-prone; users grant more than intended |
| **GitHub repo visibility** | public / private / org / collaborators | Forking creates a privacy surprise; mirror = scope leak |
| **Federated learning** (Google Gboard / Apple Siri) | gradients pooled, raw data stays on-device | Right model for Brain #33 collective; pool aggregates not raw facts |
| **Differential privacy** (Apple iOS telemetry) | noise added so single user can't be re-identified | Useful for COLLECTIVE-scope numerical aggregates (counts, distributions) |
| **End-to-end encrypted backup** (iCloud Keychain · 1Password) | data encrypted on-device with user's keys, server can't decrypt | Right model for USER + PROJECT scopes; brain.db on disk should mirror this |
| **Per-row ACL databases** (Postgres RLS · Firebase rules) | enforce visibility at query time, not at storage time | The pattern we adopt — brain.context filters at retrieval |

## Proposed architecture

### A · per-fact shareable flag

Every `brain.write` accepts `shareable: bool` (default `false`). Field stored
on the row. UI surfaces a one-click toggle on each fact:

```
[ Brain panel · facts list ]
  walls v0024 · 4 · 14:32                [ ☐ share → firm ]
  doors v0017 · 12 · 14:30               [ ☑ share → firm ]
  load-bearing-classify · skill run 8    [ ☑ share → collective ]
```

### B · scope routing

Brain query API filters by callable scope:

```python
# Today
brain.context(scope="project", kinds=["fact"])

# Proposed — explicit scope-up traversal
brain.context(
    callable_scopes=["user", "project", "firm"],   # ← what the caller can see
    kinds=["fact"],
)
# Result: facts where scope ∈ callable_scopes AND
# (origin matches caller OR shareable=true)
```

The caller declares which scopes they can see; brain filters. Brain NEVER
returns a fact whose scope > the caller's max OR `shareable=false` from a
foreign origin.

### C · PII split

For every fact with potential PII (anything user-typed, anything containing
file paths / names / addresses / firm details), the writer splits:

```
fact.payload      = { wire_id: "walls→ai", version: "v0024", count: 4 }
fact.payload_pii  = { user_id: "fargaly", project_id: "p-664-doubletree" }
fact.redacted     = false
```

- `payload`: safe at any scope above origin
- `payload_pii`: stays at USER scope · never traverses
- `redacted` flag flips true when the writer ran a redaction pass
  (e.g. names replaced with `{user_X}` tokens)

For COLLECTIVE scope: only `redacted=true` facts are eligible. Anything else
is silently filtered.

### D · differential privacy at COLLECTIVE aggregate

For numeric aggregates (e.g. "how many wall-classify runs hit COM timeout
across all firms?"), apply Laplace noise scaled to the aggregate's
sensitivity. Individual firm contribution can't be re-identified from the
total. Reuse the OpenDP Python library (`opendp.smartnoise`).

### E · SHARE node config UI

Per the Q10 founder pick (FB4=opt-in), each SHARE node in a workflow gets
a config picker:

```
[ share.publish · config ]
  ▸ scope:     ◉ private (just my machine)
               ○ project (my project team)
               ○ firm    (my org)
               ○ collective (ArchHub-wide pool — opt-in to model training)
  ▸ payload:   ☑ include redacted only
               ☐ include all (USER scope only)
  ▸ aggregate: ☑ apply differential privacy noise (COLLECTIVE only)
```

Default scope `private`. Every escalation requires an explicit click.

### F · audit trail

Every fact write logs:
- requested scope
- granted scope (after redaction pass)
- caller identity
- timestamp

Audit log is itself scope=USER (never crosses). User can grep their own
audit log to see exactly what's been shared.

## Threat model

| Threat | Defended by | Residual risk |
|---|---|---|
| Accidental over-share (user clicks wrong toggle) | default `shareable=false` · click required per fact · undo button per fact | medium — UX matters · need clear preview |
| Malicious peer scraping firm pool | scope routing at brain.context — caller can never see > their max scope | low — server enforces · client can't bypass |
| Re-identification from aggregates | differential privacy noise at COLLECTIVE | low — formal ε-bound |
| PII leak via redacted=false bug | redaction pass mandatory for COLLECTIVE · CI test asserts no PII patterns | medium — depends on pattern coverage |
| Insider threat at ArchHub-hosted collective pool | E2E encryption for transit · scoped DB partitions · audit access | medium — Hetzner box ops surface |
| Subpoena / legal compel | E2E encrypted USER scope · ArchHub can't decrypt USER facts even with subpoena | low — by-design |
| Model inversion attack on hosted collective model | training noise + reject queries that look like data probes | low-medium — research area |

## The 1-week prototype slice

Concrete, scoped:

| Day | Deliverable |
|---|---|
| 1 | `brain.write` accepts `shareable: bool` · schema migration adds column |
| 2 | `brain.context` honors `callable_scopes` filter · returns facts whose scope ≤ caller's max AND (origin matches OR shareable=true) |
| 3 | PII split helper · auto-detect user_id / project_id / firm_id in payloads · split to `payload_pii` |
| 4 | SHARE node config UI (Qt picker) per the spec above · default scope=private |
| 5 | Brain panel facts list shows per-row shareable toggle · undo button · scope chip |
| 6 | Audit log writer · USER-scope log of every shareable change |
| 7 | CI tests · pytest covers: no leak across scope boundary · default-private invariant · redaction pass coverage |

After week-1: COLLECTIVE scope + differential privacy + ArchHub-hosted pool
infrastructure = Brain #33 north star (weeks of work, separate AgDR).

## What this prototype does NOT cover

- Cross-firm authentication / identity proofing (separate AgDR · enterprise
  SSO integration)
- COLLECTIVE pool infrastructure (Brain #33 north star)
- Model training pipeline (Brain #33 north star)
- Encryption at rest of brain.db (separate AgDR · per-machine keyring)
- Legal / GDPR compliance review (founder + counsel)
- Billing for non-contributor inference on collective model (Brain #33)

## Picks needed from founder

Following FOUNDER-SPEAK MANDATE — each one a single yes/no, defaults pre-set:

| # | Pick | Default |
|---|---|---|
| 1 | Default `shareable=false` for every new fact (zero-trust)? | **YES** |
| 2 | One-click toggle per fact in Brain panel · undo on next click? | **YES** |
| 3 | Mandatory PII split for COLLECTIVE-eligible facts? | **YES** |
| 4 | Differential privacy noise on COLLECTIVE aggregates? | **YES** |
| 5 | SHARE node default scope = private (every escalation needs explicit click)? | **YES** |
| 6 | Audit log scope = USER (never crosses, founder sees own history)? | **YES** |
| 7 | Use OpenDP / SmartNoise library for the differential-privacy implementation? | **YES** (mature, MIT-licensed, Microsoft-maintained) |

If all defaults stand (per FOUNDER-INTENT-CARRIES), the prototype slice
starts immediately on founder next ack OR if no override within next loop tick.

## What ships next

Per FOUNDER-INTENT-CARRIES — no signoff card. The recommended defaults
above ARE the picks unless founder overrides. Day-1 deliverable (schema +
shareable flag) lands in the next code tick.

---

`docs/research/privacy-respecting-knowledge-sharing-2026-05-26.md` ·
generated 2026-05-26 per Q10 founder pick. Bundles with Brain #33
collective-model north star.
