# ArchHub Content Ecosystem · brain-anchored · 2026-05-26

> Coordination plan. **Not an AgDR.** Not a prototype. Reusable across
> sessions. The brain (`personal-brain-mcp`, see AgDR-0044) is the
> single source of truth that feeds every customer-facing surface:
> website, tutorials, docs, user DB, accessibility. When the code
> changes, the brain notices; when the brain notices, the surfaces
> update.

Mandates that govern this plan (cross-checked per CONSOLIDATE-WITH-ALL-MANDATES):

- DEFINITION-OF-SHIPPED, ANTI-LIE, NO-NEW-AGDR-UNTIL-LAST-ONE-LIVES,
  CONSOLIDATE-WITH-ALL-MANDATES, BIG-PICTURE-PLAN-BEFORE-EXECUTION,
  NEVER-ASK-PICK-ONE, BRAIN-FIRST, AUTOMATION, PROTOTYPE-IS-CONTRACT,
  NO-OPEN-THREADS.

---

## 1. The brain as the spine

Every track plugs into a brain primitive that already ships:

| Brain primitive | What it serves |
|-----------------|----------------|
| `memory.graph` (12 491 nodes today) | docs generator, internal-link map |
| `skill library` (mint pipeline · Slice 5) | tutorial generator (each skill → tutorial) |
| `firm + community federation` (Slices 9-16) | seat onboarding, multi-device settings sync |
| `reputation v2` (R4) | community contribution gating |
| `bipartite ACL` (Slice 7) | per-user content visibility (paywall, plan tier) |
| `redaction` (Slice 7) | PII strip before content leaves user scope |
| `wiring_announce` | per-device capability disclosure → conditional UI |
| `brain.skill_mint` | tutorial recorded automatically when user finishes a flow |
| `BrainTab` + Settings DB | a11y prefs + locale + theme — sync cross-device |

The brain is the dependency. Every track below READS from the brain or
WRITES to it. Nothing maintains a parallel store.

---

## 2. Website

### Today
- `landing/index.html` (single page) + `landing/security.html` + `archhub.png`. No content pipeline. No CMS. No live data.

### Target — single living site
- **Stack**: static-site generator that reads from the brain over the
  MCP wire (or from cloud_backend mirrors). Recommend Astro (file-based
  routing, MDX, fast). Optionally Next.js if SSR needed for personalised
  pricing.
- **Surfaces**:
  - `/` landing — hero, demo loop, three-pillar value prop pulled from
    `STRATEGY.md` or a dedicated `content/landing.md`.
  - `/pricing` — pulls live tier definitions from `cloud_backend/billing.py`
    constants (no hardcoded prices duplicated on the marketing site).
  - `/features` — feature blocks generated per skill family in the brain.
    A skill ships → a feature card appears. Skill deprecated → card auto-
    archives.
  - `/community` — top public skills from the federation `/outbox` per
    `personal_brain.federation_server`. Reputation badges per
    contributor firm.
  - `/docs` — full documentation portal (track 3 below).
  - `/security` — already exists; auto-pulled from `CAIQ_LITE.md` + `TRUST_CENTER.md`.
  - `/changelog` — generated from git tags + AgDR ledger.

### Brain integration
- Build step calls `brain.health` + `brain.context` + iterates the
  skill library via a new `brain.skill_export(scope=community)` MCP
  tool. Skill markdown bodies become MDX feature pages.
- Per-page footer line: "this page generated from brain commit `<sha>`
  on `<ts>`" — auditable freshness.
- CI hook: on every merge to main, the site re-builds. Brain daemon
  health probe runs first; if down, build fails fast (no stale-data
  publish).

### Deliverables
1. `web/` directory at repo root with Astro scaffold.
2. `web/src/content/` — auto-generated MDX from brain export.
3. `web/scripts/from-brain.js` — pulls latest skill bodies + pricing
   constants. Run as `npm run build`.
4. New MCP tool `brain.skill_export(scope, limit)` returning markdown
   payloads.
5. Fly.io or Cloudflare Pages deployment config.
6. Lighthouse target: 95+ on all four metrics, AA contrast minimum.

---

## 3. Tutorials

### Today
- `QUICKSTART.md` — 1 file.
- `app/onboarding.py` + `app/onboarding_dialog.py` — in-app first-run flow (348 + 376 LoC).
- Zero recorded walkthroughs. Zero auto-generation from real usage.

### Target — tutorials minted from successful traces
- The reflexion worker (Slice 5) already distils skills from successful
  trajectories. Add a SECOND output: when a skill mints, ALSO write a
  tutorial markdown into `docs/tutorials/<slug>.md`.
- The tutorial has: prerequisites (from `requires_mcps`), step list
  (from the trace tool_calls), screenshots (capture via mss on each
  step), expected outcome (from the trace's outcome).
- Re-runnable: every tutorial ends with a "Replay this" button that
  fires `brain.skill_mint` against a fresh session — verifies the
  tutorial still works (CI gate: stale tutorials get deprecated
  automatically).

### Brain integration
- `brain.skill_mint` already returns `proposed_name` + `description`.
  Extend the reflexion worker (`reflexion.py:reflect_on_trace`) to also
  emit a tutorial draft per successful trace.
- Tutorial draft goes through the same Voyager critic gate the skill
  goes through — bad traces never become public tutorials.
- Tutorials carry `scope` like skills: user → project → firm → community.
  A firm's tutorials sync via the existing firm-graph transport.

### Deliverables
1. `docs/tutorials/` directory + index page.
2. `reflexion.py::extract_tutorial_draft(trace)` — sister to existing
   skill extractor.
3. Tutorial template at `docs/_templates/tutorial.md`.
4. `tools/tutorial_record.py` — companion to skill mint: triggers mss
   screenshots per step during the trace.
5. Tutorial portal section on the website (`/learn`).

---

## 4. Documentation — always-up-to-date

### Today
- 30 markdown files in `docs/`. Loose collection. No table of contents
  generator. No backlinks. No staleness alerts.

### Target — docs ARE the brain
- Every `docs/*.md` indexed by the brain's `memory.extractors.decisions`
  pipeline (already exists per AgDR-0042). Each doc becomes a
  `Fragment(kind=document)` in the graph.
- Docs link to skills, AgDRs, and code paths via stable IDs. The brain
  maintains the backlink graph; a doc cited by N pages is visible from
  those pages without manual link maintenance.
- "Staleness" detection: when code referenced by a doc changes (git
  diff over `Artifacts:` paths in the AgDR), brain flags the doc as
  potentially stale. Staleness shown in the docs portal sidebar.
- On every PR that touches code with an associated doc, CI generates a
  "doc sync" suggestion (proposed diff) for the doc author to accept.

### Brain integration
- Reuse `memory/extractors/decisions.py` — already extracts AgDRs.
  Extend it to also extract all `docs/*.md`.
- New `brain.doc_links(file)` MCP tool — returns backlinks for any
  doc/file via the graph.
- A "freshness score" field on every Fragment(kind=document) updated
  on every commit that touches dependencies.

### Deliverables
1. `docs/_meta/index.json` — generated TOC + freshness scores.
2. `app/web_ui/docs-portal.jsx` (or a sub-route inside the main UI)
   rendering the docs locally inside ArchHub Composer.
3. `tools/doc_freshness.py` — CI script that flips stale docs to red.
4. `app/memory/extractors/docs.py` — new extractor sibling of
   `decisions.py`.
5. Website `/docs` route reads from the same brain.

---

## 5. User database

### Today
- `cloud_backend/archhub_cloud.db` — 18 tables, schema only, 0 rows.
- `cloud_backend/auth.py` — magic-link verification flow built.
- `cloud_backend/companies.py` — firm tier endpoints built.
- No production users yet.

### Target — user DB as the seat of the brain
- Each authenticated user gets a server-side brain.db replica synced
  with their desktop brain via the federation transport (Loro CRDT
  doc per user-scope graph; firm graph shared across firm members).
- The user DB stores: identity, plan tier, firm membership, billing
  state, telemetry-opt-in flag, a11y preferences, locale, last-sync
  HLC timestamps.
- Privacy contract: ZERO secrets, ZERO API keys server-side. Cloud
  brain replica is reference-only per BRAIN-FIRST.
- GDPR-ready: every fragment carries provenance + reversible deletion
  (just delete the user's brain.db replica + invalidate auth tokens).

### Brain integration
- `cloud_backend/memory_writer.py` + `cloud_backend/memory_extractor.py`
  already exist (per ADR-002) — wire them to the personal_brain.federation
  Slice 8 pipeline.
- Per-user sync endpoint: `POST /v1/brain/sync` with HLC-tagged delta.
  Server merges via `merge_snapshots` and returns the merged delta.
- Magic-link signin (`cloud_backend/auth.py`) becomes the first
  brain-touch — on first login, the user's local brain pushes its
  user-scope fragments to cloud, gets an HLC handshake, marks itself
  cloud-paired.

### Deliverables
1. `cloud_backend/main.py` new endpoint `POST /v1/brain/sync`.
2. `cloud_backend/brain_replica.py` — per-user brain.db service.
3. `app/cloud_auth.py` extended to drive brain sync after token mint.
4. Server-side analytics dashboard (Fly.io) showing per-user
   brain-pair status, last sync, error count.
5. GDPR delete flow: button in Settings → Account.

---

## 6. Accessibility

### Today
- 3 a11y test files for modals, dropdowns, nucleus (focus management,
  ARIA labels).
- No central a11y playbook. No screen-reader smoke. No WCAG audit doc.
- No per-user a11y preferences (font size, contrast, motion).

### Target — WCAG AA across every surface, prefs live in brain
- WCAG 2.1 AA audit: keyboard nav for every interactive control,
  ARIA labels everywhere, contrast ratios verified.
- Per-user a11y prefs stored as `Fragment(kind=setup, predicate="a11y",
  object={font_size, contrast, reduce_motion, screen_reader_optimised})`
  at user scope — sync cross-device via brain.
- Settings → Accessibility tab (11th tab in `settings_dialog.py`):
  font size slider · contrast toggle · reduce-motion toggle ·
  screen-reader optimised toggle · keyboard-shortcut customiser.
- Native PyQt accessibility tree audit (PyQt has built-in
  `setAccessibleName` / `setAccessibleDescription` — most existing
  widgets don't set them).
- Founder-eye check: navigate every Settings tab by keyboard alone
  with no mouse → all reachable.

### Brain integration
- A11y prefs as brain fragments mean: change font on phone → laptop
  picks up.
- Tutorial pages get auto-generated AAA-contrast variant when user
  has `contrast=high` set.
- Voice-over scripts for tutorials use the same step list with
  text-to-speech metadata.

### Deliverables
1. `docs/ACCESSIBILITY-AUDIT-2026-05-26.md` — current state + gap list.
2. `app/settings_dialog.py::AccessibilityTab` as 11th tab.
3. Brain MCP tool `brain.a11y_prefs(get|set)`.
4. Sweep pass on every PyQt widget setting accessibleName.
5. Sweep pass on every JSX clickable adding aria-label.
6. CI test: at least one keyboard-only smoke per panel.

---

## 7. Wave plan — parallel sub-agents (next session or this one)

Per NEVER-ASK-PICK-ONE: assume all five tracks ship. Per
NO-NEW-AGDR-UNTIL-LAST-ONE-LIVES: only do the work; no new AgDR for any
of these — this doc IS the coordination artifact.

Tracks → file ownership groups (so parallel agents don't merge-conflict):

| Track | Owns | Lead deliverable |
|-------|------|------------------|
| Website | new `web/` dir | Astro skeleton + `from-brain.js` import |
| Tutorials | `docs/tutorials/`, `reflexion.py` extension | `extract_tutorial_draft` + 3 seed tutorials |
| Docs | `docs/_meta/`, new `extractors/docs.py` | TOC + freshness pipeline |
| User DB | `cloud_backend/`, `app/cloud_auth.py` | `/v1/brain/sync` endpoint + magic-link → brain pair |
| Accessibility | new `AccessibilityTab` in `settings_dialog.py`, sweep `studio-lm.jsx` aria | 11th Settings tab + audit doc + a11y prefs in brain |

Sequence: all five can spawn in parallel (no file overlap). Final
verification: a CDP/native screenshot per track showing the visible
surface working (per ANTI-LIE).

---

## 8. Living-content invariants

These are the cross-track rules:

1. **No hand-maintained content tables.** Pricing in one place
   (`cloud_backend/billing.py`). Skill descriptions in one place (the
   brain). Doc titles in one place (the markdown frontmatter). All
   surfaces READ from the source.
2. **Every customer-facing string carries a fragment ID.** The
   provenance lives in the brain. "Where does this sentence come
   from?" is always answerable.
3. **Staleness is visible.** A doc whose source code has changed
   since the doc was last edited gets a red dot on the website AND
   in the docs portal AND in the in-app help search.
4. **A11y is non-negotiable.** No surface ships without the audit
   doc green for that surface.
5. **No PII in any cloud-side fragment.** Per BRAIN-FIRST: server
   stores `op://` references. Per Slice 7: redaction on every
   promote.

---

## 9. What's NOT in scope here

- Marketing campaigns / paid acquisition (separate from website infra).
- Pricing strategy itself — `PRICING_STATUS.md` owns that.
- Building a separate CMS — the brain IS the CMS.
- Mobile app — out of scope until desktop fully ships.

---

## 10. Coordination handle

Next agent / next session reads this doc + the latest entries in
`docs/FAILURE_LOG.md` + the running task list. The five tracks above
spawn as five parallel sub-agents on demand. Each agent's first action
is `brain.health` per BRAIN-FIRST. Each agent's last action is a CDP/
native screenshot of its track's visible surface per ANTI-LIE.
