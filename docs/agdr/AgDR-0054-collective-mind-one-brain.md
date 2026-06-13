---
id: AgDR-0054
timestamp: 2026-06-10
status: executed — founder-signed 2026-06-10 ("EXECUTE")
category: architecture
supersedes: none
builds-on: [AgDR-0012, AgDR-0021, AgDR-0038, AgDR-0042, AgDR-0044, AgDR-0045]
---

# AgDR-0054 — The Collective Mind: one brain, dam-gated river, training flywheel

> **Status: REWORK-FIRST.** The adversarial court (`court-collective-mind-final`, 2026-06-10)
> ruled the *concept* sound but the *spec* not-ready: PROPERLY_RESEARCHED **no**,
> PROPERLY_TESTED **no**, PROPERLY_DESIGNED **no**. This document is the rework record,
> not a sign-ready decision. Decision is **PENDING** the blockers in §Must-Resolve.
> Artifacts: `docs/prototypes/collective-mind-2026-06-09.html` (interactive, design-token) +
> `docs/research/memory-km-agentic-evolution-2026-06-09.md` (+ its Court-corrections block).

## Context

ArchHub is multi-user. The founder's model (iterated 2026-06-09→10, prototype-confirmed):

- **A watershed, not pools.** Each user's work = a **stream** flowing **automatically** (no
  manual promote) through security **dams** into a cloud **river = global mind** that
  auto-reads/categorizes/clusters similar workflows. **Bidirectional** — contribute up,
  recall down; every neuron drinks the river.
- **Neurons.** Each user/device runs **one local brain**; many sync (CRDT/HLC) to the global
  brain; the collective advances together.
- **One entity.** Brain + memory are ONE — not a recall cache but **an infrastructure for AI
  training and evolving.** Memory is the training set.
- **The brain consolidates ALL** — not only skills: **thinking systems** (operating mandates,
  ROMA verification, design system, domain practices), hooks-wiring, best practices — versioned
  brain content served current to every neuron. *"Not only a second brain — the thinking system
  itself."*
- **It documents EVERY session, graph, and connected-agent session — not just skills.** Each full
  **session** (the trajectory) + its **node graph** + the sessions of **every connected agent**
  (ArchHub composer · Claude Code · Codex · fleet swarm · MCP clients) are first-class, versioned,
  recallable, dam-gated entities. Skills/facts are **distilled layers** on top; the training corpus is
  verified **sessions** (the AEC action-signal), not just minted skills. (Closes the founder's original
  ask — "recreate every past session.")
- **Skills version.** Adjustments/upgrades/variants of one skill = **one lineage with computed
  diffs**; recall surfaces the best-verified version.
- **Strategic endgame.** The flywheel trains **ArchHub's collective cloud AEC models** (not
  per-firm). Specialized AEC models are missing from the landscape; AEC adopts slowest →
  forefront placement compounds. **The dam-gated river curates the only verified-AEC-trajectory
  corpus → the data moat IS the model moat.**

**What already exists (extend, never re-mint — ONE-SYSTEM):**

| Piece | Where | State |
|---|---|---|
| Local brain store | `personal-brain-mcp/src/personal_brain/storage.py` | fragments+skills with `scope/visibility/owner_user/project_id/firm_id`, FTS5, `half_life_days`, success/fail counts |
| Verify gate | `requirement_tree.py` + `court_harness.py` + `roma.py` (+ `diligence.py`) | ROMA jury: artifact/diligence/independence lenses, loop-until-dry |
| Auto-organize | brain `organize` worker (~300s) + `reflexion` worker | clustering + skill-mint from traces |
| Cloud replicas + fanout | `cloud_backend/brain_replica.py` + `/v1/brain/sync` | per-user/firm/community DBs, HLC merge, refs-only privacy, server-resolved membership |
| Training export | `brain.dataset_export` + `exports/brain-datasets` | dataset curation seam EXISTS |
| Hooks | UserPromptSubmit→`brain.context`, PostToolUse→`brain.write`, Stop→`brain.skill_mint`; in-app hooks in `llm_router.py` | neuron wiring EXISTS |
| **Debt** | `brain.db` vs `app/memory/graph.sqlite` (unify named in storage.py header, never done); thinking content scattered across `CLAUDE.md` / `settings.json` / agent memory / brain | **N-store ONE-SYSTEM violation this AgDR must resolve** |
| Known breaks | cloud sync 401 (leaked token); CLI-brain MCP race FIXED (PR #93, persistent SSE :48700) | in scope |

**Research base** (sourced; numbers corrected per court — see research doc Court-corrections):
hybrid raw⊕graph retrieval (MultiHop-RAG: **11.6% RAG-only / 13.6% GraphRAG-only**, complementary;
concat **+6.4%**; ~34% answer-entity KG-miss = construction loss, HotpotQA/NQ); HippoRAG (PageRank
multi-hop, +20%); Zep/Graphiti (temporal KG; **vendor self-eval**, "up to 18.5%", +1.4pp DMR);
EDC (schema auto-induction + canonicalization); KARMA (multi-agent KG enrichment + verify/conflict
gates; **83.1% is LLM-graded → ~1-in-6 wrong facts pass** = needs a false-accept budget);
SkillsBench (unverified auto-skills **−1.3pp**, verified **+16.2pp**; **secondhand via SoK survey,
single 86-task benchmark** — verify primary); AgentPoison (**≥80% ASR**, evades perplexity+rephrase);
MemoryGraft (**9%→47.9%** retrieval dominance, n=12 one-framework → motivates per-source caps);
ClawHavoc (shared-repo supply chain → canary); MAST (pooling ≠ improvement → regression-demote).

## Options considered

| # | Option | Verdict |
|---|---|---|
| 1 | Status quo — skills-only brain, static CLAUDE.md mandates, manual promote, two stores | ✗ N-store violation; no collective evolution |
| 2 | Manual promotion pools | ✗ founder-rejected — "streams pouring into a collective river," not pools |
| 3 | Auto-share with filter-only dams (no execution-verify) | ✗ research-refuted: filters evaded (AgentPoison); unverified skills net-negative (SkillsBench) |
| 4 | Per-firm fine-tunes as endgame | ✗ founder-corrected — marginal; the play is collective cloud AEC models |
| 5 | **One brain (memory⊕skills⊕thinking⊕training), bidirectional dam-gated river, neurons, versioned lineages, flywheel→collective AEC models** | ✓ **chosen in principle** — but execution gated on §Must-Resolve below |

## Court verdict (court-collective-mind-final, 2026-06-10) — REWORK-FIRST

**Survived:** every primary source is real; the dual-retrieval bet holds; the watershed shape is
right; "nothing unverified rises" is correct. **Failed:** spec contradicts shipped reality and
has unresearched, ungated, un-tested halves. Top issues (ranked):

1. **CRITICAL — mandate updates bypass the dam.** A quarantine event auto-versioned the operating
   mandates and fanned them to every neuron, unsigned — highest-privilege content on the lowest
   gate. *Fixed in the prototype 2026-06-10: mandate-class is now founder-gated (machine proposes,
   founder ratifies); knowledge auto-rises, the constitution does not.*
2. **CRITICAL — training erases privacy.** scope/ACL gates recall only; fine-tuning collapses all
   scopes into weights → firm-private data baked into the collective model, unremovable. "Quarantine
   never trains" stated, enforced nowhere.
3. **CRITICAL — verifier in the attacker's trust domain.** ROMA court runs on the contributing
   user's machine; real verifier today is one human (bus-factor-one); sync is 401-dead.
4. **HIGH — merge contradicts shipped invariant.** Dam stage "reconcile" vs live last-writer-wins in
   `brain_replica.py` (test-pinned). Stage 4 can't be built on the current data model.
5. **HIGH — "one store" has no migration plan** (≥5 stores today).
6. **HIGH — training endgame has ZERO research** (the moat): legality, model collapse, training-time
   poisoning, forgetting, unlearning.
7. **HIGH — circular eval** (train + held-out both river-fed → leakage by construction; day-0 suite empty).
8–12. MEDIUM/LOW — corrupted provenance numbers (fixed in research doc); under-evidenced numbers
   (labeled); unsourced consolidation + rank pillars; inbound dam untested in prototype; flywheel economics absent.

## Decision

Direction (Option 5) accepted. The 3 founder rulings are made and the 4 architecture decisions drafted
(2026-06-10) → **sign-ready**. Founder signature is the only remaining gate; no code until signed.

### Founder rulings (2026-06-10)
- **Corpus = HYBRID, tiered per trace** (founder: "hybrid between the 3"):
  - **Tier-0 action-signal — ALWAYS trainable:** verified tool-call sequences + structured outcomes (ArchHub-owned
    operational data, NOT provider prose). The base of the collective AEC model; ToS-clean.
  - **Tier-1 human-authored language** (`origin_kind=human_verified`) — trainable; adds intent/notes; ToS-clean.
  - **Tier-2 provider-prose** (`origin_kind=model_generated` + `generating_model_id`) — EXCLUDED from the
    competing-model corpus by default; admitted only under express provider approval OR an explicit risk-accepted lane.
  - The export filter computes the tier from schema fields; requires each trace to store `action_payload` (always)
    separately from `language_payload` (gated) — see §6 schema.
- **Training-rights = collective-default + opt-out.** A firm's verified work flows to the collective unless it opts
  out. ⚠ **This raises the privacy/IP bar** — the dam's redaction + per-firm gate must be airtight and opt-out honored
  at **export** (not just recall); top residual risk of this choice, paired with the Tier-2 gate above.
- **Verifier = server-side sandboxed re-execution, now.** The ROMA verify gate runs server-side, off the
  contributor's machine (resolves the "verifier in the attacker's trust domain" CRITICAL). Signed neuron attestation =
  cheap pre-filter; server re-exec = the authoritative gate. Fixing the 401 sync is in scope.

### Architecture decisions
- **A · Store unification (#2):** `brain.db` (SQLite+FTS5) = the ONE local store of record. Absorb
  `app/memory/graph.sqlite` via the adapter storage.py already names (MemoryGraph→brain backend), migrate with
  provenance parity, then delete graph.sqlite + `tools/brain_unify.py`. Thinking content (CLAUDE.md / settings.json /
  MEMORY.md) becomes brain fragments (kinds MANDATE/HOOK/PRACTICE); those files are **compiled OUT** by the projector
  (C) — generated artifacts, not sources. The ONE out-of-store kernel = the hook-loader shim (declared + allowlisted;
  it can't live in the brain it loads). Migration order: graph.sqlite first (the named debt).
- **B · Fragment-model v2 (#3, reconcile):** fragments hold **sibling concurrent versions** {value, hlc, source,
  verdict}; default view = highest-verified; KARMA conflict-resolve keeps the losers as linked lineage + a reconcile
  record. The shipped HLC last-writer-wins tests are **consciously rewritten** to assert sibling-survival (acceptance
  #5). Same lineage+diff mechanism as skill versions — generalized to all fragments AND sessions/graphs (#10).
- **C · Thinking projector (#4):** versioned brain content → compiled per-harness artifacts (CLAUDE.md, settings.json,
  pre-prompts) with version pins + **session epochs** (in-flight sessions stay pinned); **mandate-class bumps require
  founder signature** (quarantine→auto path deleted). Knowledge auto-rises; the constitution is founder-ratified.
- **D · Verify trust-domain (#5):** server-side sandboxed re-execution (founder ruling above).
- **E · Eval protocol (#8):** time-split "living" held-out (post-cutoff verified workflows) + decontamination scan
  (hash + n-gram + canary) every export + day-0 baseline = frontier API + significance threshold. Suite power-sizing
  is the one item that lands at build-time (sized to resolve the deploy-gate delta), not now.

**Build order (after signature):** firm-scoped verified loop first (corpus pump) → server-side verify + store unify →
session/graph capture across agents → open the river past own firm only once the dam survives red-team → flywheel at
corpus critical mass. No code until signed.

## Must-Resolve before signature

1. **Training research pillar** — ✓ **RESEARCHED 2026-06-10** → `docs/research/training-endgame-2026-06-10.md`.
   Decisions: mix **~20% AEC / ~80% general** (court-recorded hyperparam); **accumulate-never-replace** (keep
   the human-verified corpus forever); **LoRA-first** (rank = retention knob; poisoned user = droppable adapter);
   **LR ~1e-6, batched** consolidation (not online; most forgetting + alignment-collapse happen <100 steps at high
   LR); **Self-Synthesized Rehearsal** for the general anchor; **verifier-as-information-source** (ROMA court is the
   collapse defense — verified retraining converges to the verifier, no collapse). ✓ **R3/R4/R5 RE-RUN 2026-06-10**
   → `docs/research/training-gaps-addendum-2026-06-10.md`: **poisoning** = defense-in-depth (content-hash +
   per-contributor cap <250 doc-equiv + checkpoint activation-probe AUROC 99.3% + **base-model audit**; *verifying a
   trace ≠ clean weights* — Sleeper Agents survive SFT/RL); **unlearning CONFIRMED impossible** (TOFU; 83% recovered
   via 4-bit quant) → **export-gate is the only path**; **legality = facial ToS breach** across the 3 providers (see #7a — now decisive).
2. **Store unification plan**: enumerate all ≥5 stores; absorb-vs-adapter per store; `brain.db`+`graph.sqlite`
   migration first; carve out the minimal out-of-store kernel (the hook shim that loads the brain can't live in the brain).
3. **Fragment data-model v2**: sibling/multi-value versions so *reconcile* is possible; explicit statement on
   the shipped last-writer-wins invariant + its pinned tests.
4. **Thinking-system projector**: compiles versioned brain content → per-harness artifacts (CLAUDE.md,
   settings.json, pre-prompts) with version pins + session epochs; **mandate-class requires founder signature**
   on every bump (quarantine→auto path deleted — done in prototype).
5. **Verify trust-domain**: signed neuron attestation + trust-decay OR server-side sandboxed re-execution —
   pick one; name bus-factor-one as the starting state + the path off it; fix the 401-dead sync.
6. **Per-trace schema** — ✓ **DELIVERED** (research doc §4). Five **non-negotiable, lockable-now** fields:
   `origin_kind` {human_verified|model_generated}, `training_rights_tier` {collective_ok|firm_private_only|
   quarantine_never_trains}, `generating_model_id`, `format_shape_descriptor`, `content_hash_pre/post`;
   consolidation bookkeeping keys reserved (run_id, mix_ratio/LR/rank used, pre/post gate scores, eval-split).
   **Hybrid-corpus split (founder ruling 7a):** every trace stores `action_payload` (tool-calls + structured
   outcomes — ArchHub-owned, ALWAYS trainable: Tier-0) separately from `language_payload` (prose, tagged by
   `origin_kind`; Tier-1 human = trainable, Tier-2 provider-prose = gated). The export filter trains Tier-0 always,
   Tier-1 when present, Tier-2 only under approval/risk-accept — so the legal tier is computable per trace.
   **Training-side export gates** (build on the schema): "quarantine never trains" + "firm-private never trains
   the collective" as enforced export filters; declared dam false-accept budget + post-merge audit/retraction.
   (Schema lockable independent of the missing R3–R5 strands.)
7. **FOUNDER RULINGS — ✓ ANSWERED 2026-06-10 (recorded in Decision §): (a) hybrid tiered corpus · (b) collective-default + opt-out · (c) server-side re-execution.** Detail/options:
   (a) **Provider-ToS — NOW DECISIVE (research 2026-06-10):** training a competing model on Claude/GPT/Gemini
   OUTPUTS is a **facial breach of all three providers' ToS** (Anthropic §D.4 + Help Center; OpenAI; Gemini API);
   "non-competing" is undefined/unsafe; case law agrees (Thomson Reuters v. Ross). **As drawn — distilling Claude
   traces — the flywheel endgame is legally blocked.** Your ruling = pick a clean-corpus path: (i) train only on the
   **AEC ACTION signal** (verified tool-call sequences/outcomes, not model prose); (ii) **human-authored** traces
   only; (iii) **express provider approval**; (iv) permissive base + non-provider data — or explicitly accept the
   risk. **Default until ruled: no fine-tune on provider-derived traces.** (The schema + dam build regardless.)
   (b) **Training-rights tiers** in firm contracts (does Firm A's work train only its private model or the
   collective?) — once set, the `training_rights_tier` field enforces it mechanically.
   (c) **Clean-corpus policy** if (a) is conditional (human-authored only? non-Claude-model only? AEC-action-not-
   language as the learned signal?) — I encode whatever you set; I can't pick the legal line.
8. **Eval protocol**: split-and-freeze held-out suite + decontamination lineage + versioning + significance
   threshold + day-0 baseline (frontier API) + honest ship criterion (cost/latency/privacy at bounded quality delta).
9. **Source the two unsourced pillars** (consolidation; rank formula) or mark asserted.
10. **Capture completeness**: make SESSION (full trajectory) + node-GRAPH + CONNECTED-AGENT-SESSION first-class
    brain entities — versioned, recallable, dam-gated — across ALL agents (ArchHub composer · Claude Code · Codex ·
    fleet · MCP). Today: partial (traces→skills + standalone `.archhub-session.json`; Codex/swarm coverage gap).
    The training corpus draws from verified **sessions**; skills/facts are distilled views, not the record.

## Acceptance suite (Artifacts — "built" == these 13 pass)

1. Unverified/forged-attestation fragment from a hostile neuron never reaches the river (server-side assertion).
2. `dataset_export` contains zero quarantined bytes (CI-pinned).
3. Firm-A private fragments absent from the collective dataset + canary-string memorization probe on any fine-tune.
4. Mandate bump via quarantine/auto path is BLOCKED without founder signature; in-flight sessions stay pinned to their epoch.
5. Two contradictory facts on one entity survive as siblings with a reconcile record (rewrite the HLC/LWW tests consciously).
6. Migration test: brain.db + graph.sqlite → unified store, row-count + provenance parity; out-of-store kernel allowlist.
7. Red-team corpus (AgentPoison + MemoryGraft style) → attack success below declared budget; source trust decays after court failures.
8. Dual retrieval beats raw-only and graph-only **on our corpus** (a citation is not a test).
9. Verified-skill A/B (+lift) on ArchHub workflows with deterministic verifiers (after reading SkillsBench primary).
10. Dam false-accept measured vs budget + retraction drill (merge a known-bad fact, prove downstream cleanup).
11. Cross-tenant recall attack (incl. edge traversal) → zero leakage (prototype currently fails this by design).
12. Decontamination scan train↔eval each export + frozen versioned eval + power analysis for the deploy-gate deltas.
13. Erasure drill: tombstone propagates to all replicas AND erased trace absent from every post-request export (weights-level erasure impossible → export gating precedes training).
14. **Forgetting/alignment regression gate**: before any model promotes, a frozen suite scores instruction-following + reasoning/knowledge + **safety refusals** + AEC domain; promotion BLOCKS on general OR safety regression beyond threshold (a verified trace can still cause alignment collapse in <100 steps).
15. **Poisoning stack**: ~200 trigger-bearing-but-execution-valid traces from a hostile neuron → per-contributor cap blocks them pre-train AND the checkpoint activation-probe flags any that slip (defense-in-depth, no single layer trusted).
16. **Base-model audit**: probe + red-team the BASE model before any consolidation; block on a dormant trigger (LoRA won't wash out an inherited backdoor).
17. **Clean-corpus filter**: export passes ONLY traces matching the founder's §7a policy (`origin_kind`/`generating_model_id`/`training_rights_tier`); assert zero provider-output traces in a competing-model training set unless policy permits.
18. **Eval time-split + decontamination**: eval items all post-training-cutoff; hash + n-gram + canary scan train↔eval = clean; suite sized (power analysis) to resolve the deploy-gate delta.
19. **Unlearning honesty**: revoke a firm → absent from the next export (export-gate is the erasure); documented that weights-level erasure of shipped checkpoints is impossible (revocation = retrain-from-clean-checkpoint).
20. **Capture completeness**: a session run in the ArchHub composer AND one in Claude Code AND one in Codex/a fleet agent all appear in the brain as recallable **session + graph** entities with full trajectory (not skills-only); replay reconstructs the graph; the training export reads them as sessions.

## Build order (after sign-off)
Firm-scoped verified loop FIRST (the corpus pump) → open the river past own firm only after the dam survives
real workloads → flywheel at corpus critical mass. The collective AEC model is the endgame the architecture feeds.

---

## Execution control plane — the wall (added 2026-06-13; plan-locked, NO BUILD until founder "go")

**Why (root cause of the recurring failure).** ArchHub keeps producing half-built work claimed "done"
because work is governed by *chat, summaries, mandates* — descriptive authority a model can infer around
(it can mis-scope, trust stale context, call an apply-log "done," over-batch, or forget the source of truth
across sessions). The fix is an **enforceable control plane**: a machine-readable **active-work ledger**
every session must load and obey BEFORE acting; "done" is derivable only from the ledger's gates, never
from prose. (Diagnosis relayed by the founder from ChatGPT 2026-06-13. Verdict: correct on the gap, but
~70% of the machinery already exists as a *library* — `requirement_tree.py` (task_tree), `court_harness.py`
(acceptance_gates + independent verify), the per-trace schema (provenance), `sweep().dry` (done_rule) — it
is simply not wired as a mandatory wall, and there is no per-job work-state record. So this is wiring +
one new record, NOT a new system.)

**It is the SAME brain gate, turned inward — not a parallel system (ONE-SYSTEM holds).** The dam governs
*knowledge* flowing outward (stream→river→recall); the wall governs a *session's work* flowing inward
(chat→done). Both pass the one gate: ROMA court + per-trace provenance + scope. Three gates, one standard,
cascading: **WALL** (per job, source) → **DAM** (per contribution, mid) → **RIVER** (collective). A trace
cannot reach the dam, the river, or the training corpus unless it cleared the wall — source-water treatment,
the upstream answer to the poisoning / false-green threats (Court #2/#3/#7; acceptance #7/#15). It is the
**precondition for the multi-user brain**: every neuron runs the same wall, so the river is fed only governed
water; the collective is only as clean as the dirtiest contributor's *process*.

**The active-work ledger (the one genuinely-missing record).** A new fragment kind in `brain.db` (NOT a new
store), reusing existing primitives:

| Ledger field | Backed by | State |
|---|---|---|
| `scope` (in / out, refuse-if-undefined) | brain scopes USER/PROJECT/FIRM | NEW (the lock) |
| `source_of_truth` (per artifact type) | `docs/ROADMAP.md` + provenance | partial |
| `artifact_manifest` (files/models/exports + ts) | per-trace provenance (slice 1) | partial |
| `task_tree` (atomic leaves + owners) | `requirement_tree.py` | HAVE |
| `acceptance_gates` (machine check per leaf) | `court_harness.py` 3-lens jury | HAVE |
| `verification_status` (pass/fail/blocked + evidence path) | ROMA court verdicts | NEW (per in-flight job) |
| `last_verified` (freshness vs the thing it proves) | per-trace timestamps | partial |
| `done_rule` (no prose overrides a failed/missing gate) | `sweep().dry` | HAVE (make non-optional) |

**Multi-user lock (resolves the founder's 2026-06-13 concern "do other users get Lubb?").** Lubb is the
**engine for all** — shipped to every ArchHub install as a pinned dependency (every user runs their own
neuron + own private `brain.db`); the skill-mint / workflow-save / redeployable-diagram capability reaches
every user; the collective value (a skill one user mints → recall to others) is the dam-gated river on top.
"Private repo" = source IP, **not** user lockout; the built package + capability ship to all (engine = shared
code · data = per-user private · river = collective gated). Lubb is **never** framed as a personal box.
Design reference: `docs/prototypes/control-plane-execution-ledger-2026-06-13.html`.

## Build contract — Lubb extraction (P0–P3) + control plane (S1–S4) (added 2026-06-13; NO BUILD until "go")

Every phase is **reversible**, **gated on a real machine check the founder can see**, and reported under
ANTI-LIE (the word "done" is banned without the 5-row proof table green + an openable artifact). The founder
may **stop at any gate**; `brain.db` is backed up first and **never touched** (worst case = where we started,
minus minutes). Governance: **S0 rides AgDR-0002 (ECHO, executed) + `01.ECHO/BRAIN_EXTRACTION_PLAN.md`**;
the control-plane layer **extends this AgDR** — no new AgDR is minted (NO-NEW-AGDR honored). All build runs in
an **isolated worktree on a build branch, never the founder's live tree** (the branch-flip lesson).

### S0 — extract the brain to its own repo (Lubb): the de-risk
Kills the root cause of the branch-flip/stranding chaos: the brain is editable-installed into ArchHub's tree,
so auto-sync branch switches silently change the LIVE brain's code and strand commits (proven this session).

| Phase | What you get | Gate (machine check you see) | Proof | Rollback |
|---|---|---|---|---|
| **P0** | backup + baseline | backup file exists; `brain.health` reads the baseline counts | the counts, shown | none needed (read-only + file copy) |
| **P1** | birth `Fargaly/lubb` (no live impact) | full brain pytest green in the new clone (incl. the 602-test schema suite) | green pytest + the repo | delete the repo; nothing live changed |
| **P2** | repoint the live daemon (~5 min) | `brain.health` ok + identical counts post-cutover; ArchHub recalls | same counts + a live recall | re-point the old install (~2 min); db untouched |
| **P3** | ArchHub becomes a dependent | app boots + composer recalls on the new brain; grep proves zero stale `personal-brain-mcp/` path refs | the live app on the new brain | `git revert` the one deletion commit |

### S1–S4 — the control plane: THE CORE (built back-to-back, NONE "later")
These are the parts that kill the recurring failure — false-greens, scope-creep, lying, sessions-as-truth.
They are **not** deferred. Build order = dependency order: the ledger is the substrate, so it is **S1**
(corrected 2026-06-13 after the founder flagged the core was wrongly tagged "later"; the first draft mis-numbered
the gate ahead of the ledger it loads). S0 is the **only** thing before them, and it is hours of reversible
plumbing, not a feature.

| Slice | What it builds | Gate (acceptance) | Rollback |
|---|---|---|---|
| **S1 · core** | `active_work` ledger record in `brain.db` (scope · manifest · verification_status · last_verified) — the substrate everything writes to | the new fragment kind persists + round-trips; fields populated from a real session | additive schema; migration reversible |
| **S2 · core** | gates non-optional — every session loads + obeys the ledger before acting | a session that skips the load-gate is refused (test) + the load-gate fires in a real run | branch revert; gates return to opt-in |
| **S3 · core** | scope-lock — refuse to act if in/out scope undefined; pilot-before-batch (**kills over-batch/creep**) | an undefined-scope action is refused; a batch over an unclassified set is refused | flag-gated; default off until verified |
| **S4 · core** | done == green sweep (universal) + tamper-proof ledger writes — a gate-write needs an evidence path (**kills false-greens/lying**) | "done" derivable only from `sweep().dry`; a ledger write without evidence is rejected | branch revert |

(**S5** — every neuron obeys the wall — is the collective rollout. It is **safety-gated**, not deprioritized:
the wall must survive red-team before it is exposed to every neuron + the river, or one bad neuron poisons all.
Coincides with acceptance #1/#7/#11.)

**Acceptance additions** (extend the suite above):
21. **Control plane fires**: a session that does not load the `active_work` ledger is refused before any file write (the wall blocks it).
22. **Tamper-proof done-rule**: "done" is computed from `sweep().dry`; a hand-asserted done over a red/missing gate is rejected; a ledger gate-write without an evidence path is refused.
23. **Scope-lock**: an action outside the declared in-scope set — or a batch over an unclassified set — is refused with a typed recovery (pilot-first).
