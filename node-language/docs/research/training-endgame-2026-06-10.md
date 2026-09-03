# Training endgame — ArchHub collective AEC models (research brief)
_Unblocks AgDR-0054 §Must-Resolve #1 + #6. Sourced; 2026-06-10. Design reference — NOT the roadmap._

> **Honesty floor:** 5 strands launched; reports R1 (continual-learning) + R2 (model-collapse) arrived fully cited. R3 (poisoning), R4 (unlearning), R5 (legality+decontamination) did **not** fully land — those sections lean on AgDR-0054's own court-verified research base and **must be re-run before sign-off** (AgDR §Must-Resolve #1). The Section-4 schema does NOT depend on the missing strands and is lockable now.

## 1. Method + cadence + cost
- **Mix, don't specialize-narrow.** Every fine-tune blends verified AEC traces with a held-aside general/instruction replay set. Usable band: domain ≈ 15–50% / general ≈ 50–85%. Start **~20% AEC / ~80% general**, treat as a court-recorded hyperparameter. (arXiv:2506.09428, 2512.13706, 2403.08763)
- **Accumulate, never replace.** Keep the original human-verified corpus forever; add synthetic/model-gen traces alongside. Replacing → collapse (tails/rare-AEC-workflows vanish first); accumulating has a proven finite error bound. (arXiv:2404.01413, 2305.17493, Nature s41586-024-07566-y)
- **One asset, two gates:** the permanent "general anchor" replay corpus = the "real data you must keep" for collapse-escape. Build it via **Self-Synthesized Rehearsal** since you can't ship the base model's instruction set (arXiv:2403.01244).
- **LoRA-first, rank = retention knob.** "Learns less, forgets less"; a poisoned user = a droppable adapter (rollback without retrain). Full FT only for periodic audited consolidation. (arXiv:2405.09673, 2512.15634)
- **Cadence:** batched consolidation runs, NOT a continuous drip; cap steps/epochs; **LR ~1e-6**, no re-warming spikes (most forgetting + alignment collapse happen in the first <100 steps at high LR). (arXiv:2509.20758, 2403.08763)
- **Cost:** low, data-mixing-dominated, front-loaded. Synthetic data helps while real AEC data is scarce, **hurts once real data is ample** — shrink the synthetic fraction as the corpus grows. (arXiv:2410.16713)
- **Verifier-as-information-source:** iterative *verified* retraining converges to the verifier's knowledge center; binary accept/reject suffices (perfect accuracy not required). The ROMA court is the external verifier — the collapse + poisoning defense in one. (arXiv:2510.16657, 2407.09499)

## 2. Safety gates
- **Anti-collapse:** enforce accumulate-not-replace as an invariant; cap synthetic fraction vs real-data volume; protect tails (tag domain/task/format).
- **Anti-poisoning [lean on AgDR; R3 pending]:** execution-verify (not filters — AgentPoison ≥80% ASR evades them); per-source/format caps (MemoryGraft 9%→47.9%); declared false-accept budget + post-merge audit/retraction; canary-string probe; trust decay.
- **Privacy/unlearning [lean on AgDR; R4 pending]:** **training erases privacy** — fine-tuning collapses scopes into weights; weights-level erasure is effectively impossible → **export-gating must PRECEDE training** ("quarantine never trains" + "firm-private never trains the collective" as enforced export filters). The per-trace training-rights tier IS the unlearning mechanism.
- **Decontamination [lean on AgDR; R5 pending]:** train + held-out eval are both river-fed → leakage by construction; split-and-freeze + decontamination scan (content-hash) every export + day-0 baseline (frontier API) + significance threshold.
- **★ Forgetting/alignment regression gate (the net-new control):** before promoting any fine-tuned model, run a fixed held-out suite — (a) instruction-following, (b) reasoning/knowledge, (c) **safety refusals**, (d) AEC domain — and **block on general OR safety regression**. Fragility rises with model scale (BLOOMZ 1.1B→7.1B forgetting 9.54%→18.37%) → your "bigger specialized model" ambition makes this gate MORE necessary over time. EWC is an add-on, not a replacement for replay. (arXiv:2308.08747, 2602.15799, 2603.18596)

## 3. Legal — the founder's calls (true boundaries; not buildable by me)
1. **Provider-ToS ruling:** train a competing AEC model on **Claude-generated traces** — yes / no / "yes but a legally clean subset"? If unanswered → must be **accepted as a named risk** before any fine-tune. (R5 legality strand pending; conservative default = do not fine-tune on Claude-derived traces until ruled.)
2. **Training-rights tiers in firm contracts:** does Firm A's verified work train only Firm A's private model, or the collective? Once set, the per-trace `training_rights_tier` field enforces it mechanically.
3. **Clean-corpus policy** (if #1 is conditional): what counts as trainable-clean (human-authored only? non-Claude-model only? AEC-action-not-language as the learned signal?). I encode whatever rule you set into the export filter; I can't pick the legal line.

Everything else legal-adjacent that IS buildable (provenance flags, tier field, export filters, canary probe) is in §4 — not handed back.

## 4. PER-TRACE LOGGING SCHEMA (the deliverable — lockable NOW)
Every verified trace carries these at dam-entry. **Five non-negotiable** (each, if missing, makes a named gate impossible later): `origin_kind`, `training_rights_tier`, `generating_model_id`, `format_shape_descriptor`, `content_hash_pre/post`.

**A. Provenance & identity** — `trace_id` · **`origin_kind`** {human_verified|model_generated} · **`generating_model_id`+version** (keys the ToS filter) · `user_id`/`neuron_id` (per-source caps + adapter rollback) · `source_app`+version · `project_id`,`firm_id` · `timestamp` (HLC+wall) · **`training_rights_tier`** {collective_ok|firm_private_only|quarantine_never_trains} (the unlearning mechanism).

**B. Domain / difficulty / shape** — `discipline`+`task_type` (mix-ratio + replay stratification) · `token_sequence_length` · `difficulty_rank_signal` (high-rank = high-forgetting detection) · **`format_shape_descriptor`** (prompt→tool→result fingerprint; caps format over-rep that triggers alignment collapse + per-format poison cap) · derived `rarity/tail_flag` (protect rare-but-correct workflows).

**C. Verification record** — `court_verdict` (3-lens) · `verifier_identity`/host+env (regression traceback; trust-domain) · `independence_attestation` (judged_by≠claimed_by, signed) · `trust_score_at_entry` (decays on court failures).

**D. Content integrity & privacy** — **`content_hash_pre_redaction`+`content_hash_post_redaction`** (dedup, poison forensics, train↔eval decontamination) · `pii_redaction_status` · `quarantine_flag` (provably absent from export).

**E. Consolidation bookkeeping** (written at train-time; **keys reserved now** or runs become non-reproducible) — `consumed_by_run_id` · `mix_ratio_used`,`learning_rate_used`,`adapter_rank_used` · `pre_gate_scores`/`post_gate_scores` · `eval_split_assignment` + decontamination-lineage id.

A–D populated at dam-entry, lockable now; E reserved now, filled later.

## 5. Open risks
1. **R3/R4/R5 didn't fully land** — re-run poisoning/unlearning/legality before sign (highest).
2. **Provider-ToS unresolved** — if disallowed, "data moat = model moat" needs a clean-corpus redefinition (founder ruling).
3. **Alignment collapse from verified data** — §2.5 gate is the control, but the day-0 safety/eval baseline is prerequisite work, currently empty.
4. **Scale worsens forgetting** — re-tune mix/LR/rank at every scale step.
5. **Synthetic value inverts with corpus size** — shrink synthetic fraction over time.
6. **Weights-level unlearning impossible** — export-gate before training; any pre-schema-lock fine-tune is a permanent liability.
7. **Verifier in attacker's trust domain** — signed attestation OR server-side re-execution before the river opens past the founder's firm.

Sources: R1 continual-learning + R2 model-collapse URLs inline above; R3–R5 pending re-run.
