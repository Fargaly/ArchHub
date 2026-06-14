# Training gaps addendum — poisoning · unlearning · legality (AgDR-0054)
_Re-run of the 3 strands that didn't land in the first pass. Sourced. 2026-06-10. Design reference._

> **Framing fact tying all three together:** verification gates the **WORKFLOW, not the WEIGHTS.** ROMA's court proves a trace *executes* correctly; a weight-level backdoor is *defined* by executing correctly until a trigger fires. A 100%-court-verified corpus can still train a backdoored model. Court-green is **necessary, not sufficient** for training safety. (Sleeper Agents, arXiv:2401.05566)

## 1. Anti-poisoning — defense-in-depth (every single layer is beatable → require the STACK)
- **Threat is COUNT-CONSTANT, not %-constant:** ~250 poisoned docs installed a backdoor at 600M→13B params alike (100 didn't). The absolute bar stays ~250 no matter how much clean data the model sees. (Anthropic/UK-AISI/Turing 2025, anthropic.com/research/small-samples-poison) → **"accumulate-never-replace" is a structural poison amplifier** (needed fraction → 0 as corpus grows; a poisoned contributor persists into every future LoRA round). Budget for **fewer than 250**.
- **Weight-level backdoors survive full SFT/RL/adversarial training**; adversarial training *hides* them; persist with scale + CoT. (Sleeper Agents 2401.05566) → low-LR LoRA will NOT wash out a base-model backdoor → **audit the base model**, treat it untrusted unless provenance-clean.
- **The gate stack:**
  - **G1 Provenance/integrity (cheapest, highest leverage):** content-hash each trace at court-sign; recompute pre-train, reject any byte-changed trace. Closes split-view/frontrunning (~$60 poisoned 0.01% of LAION). (Carlini, 2302.10149) — *already the schema's `content_hash_pre/post`.*
  - **G2 Per-contributor blast-radius cap + 2nd court review** above a max fraction AND max absolute count (set well below 250 doc-equiv).
  - **G3 Data-level anomaly scan** (spectral signatures + activation clustering) — triage, evadable, not a gate. (2406.07778)
  - **G4 Trigger-agnostic activation probe on EVERY post-fine-tune checkpoint:** generic yes/no contrast pairs detect the dormant defection state at **AUROC 99.3%** without knowing the trigger. (anthropic.com/research/probes-catch-sleeper-agents) **Detection, not proof** — never substitutes for the human verifier; salience may be an artifact; adaptive attacker can obfuscate.
  - **G5 Held-out trigger-elicitation red-team** each checkpoint.
  - **G6 Influence-function self-influence** — ADVISORY only (EK-FAC scales to 52B but "often fails to attribute abnormal behavior… particularly in LLMs"). (2308.03296, 2409.19998)

## 2. Unlearning verdict — CONFIRMED: export-gate is the only reliable path
- **No method truly forgets.** TOFU: "none of the baselines… show effective unlearning." (2401.06121)
- **Quantization recovers it:** utility-preserving unlearning retains 21% full-precision, **83% after 4-bit quant.** (Zhang et al., ICLR 2025, 2410.16454)
- **Reversible by light fine-tune** even on unrelated data → information is **suppressed, not erased.** (2505.16831)
- **Verdict:** no post-hoc method relaxes the constraint. **Weights-level erasure is impossible → gate at export, before training.** The per-trace `training_rights_tier` + `quarantine_flag` ARE the unlearning mechanism. Any pre-schema-lock fine-tune is a permanent liability.

## 3. Legality — the founder's ruling #1, now decisive
- **Provider ToS — all three forbid it:**
  - **Anthropic** Commercial Terms §D.4: may not "build a competing product… including to train competing AI models" without written approval; §B: "Anthropic may not train models on Customer Content" (good for client-data, but bars *you* from training a competitor on Claude outputs). Help Center: outputs may train **only non-competing** models; prohibited examples include "general purpose chatbots," "open-ended text generation," "using Outputs as training targets." (anthropic.com/legal/commercial-terms; support.claude.com/.../12326764)
  - **OpenAI:** may not "Use Output to develop models that compete with OpenAI." (openai.com/policies/row-terms-of-use)
  - **Google Gemini API:** "You may not use the Services to develop models that compete… (e.g., Gemini API)"; bars replicating weights. (ai.google.dev/gemini-api/terms)
  - **NET:** ArchHub's river traces are predominantly Claude/GPT/Gemini outputs → distilling them into ArchHub's own AEC model is a **facial ToS breach across all three**. "Non-competing" is undefined by every provider and **not a safe harbor** (a general-ish AEC assistant plausibly competes).
- **Case law:** Thomson Reuters v. Ross (Feb 2025) — training a *competing* tool from protected expression = NOT fair use (market-for-training-data harm). Bartz v. Anthropic (Jun 2025) — end-use transformative but **pirated-corpus provenance independently actionable**, settled ~$1.5B. Kadrey v. Meta — "market dilution" dicta; "in most cases… training on copyrighted works without permission is likely infringing." NYT v. OpenAI — preservation order sweeps all logs into discovery (client-data exposure beyond your control).
- **Client/firm-IP:** pooling firm AEC content (NDAs, third-party CAD/specs) into a shared model = contract breach + irreversible memorization/regurgitation leakage; AI-only output isn't copyrightable.
- **Viable clean-corpus paths (the founder picks):** (a) train only on the **AEC ACTION signal** (verified tool-call sequences/outcomes, not the model's prose) — greyer, arguably not "using outputs"; (b) **human-authored** traces only; (c) **express written approval** from provider(s); (d) base model on a permissive license + non-provider-generated data. **As drawn (distill Claude traces) the endgame is legally blocked.**

## 4. Decontamination + eval-stat
- **Time-split / "living" held-out is the strongest practical defense:** evaluate only on items created AFTER the model's cutoff (LiveCodeBench/LiveBench pattern). For ArchHub: freeze eval on post-cutoff verified workflows.
- N-gram (GPT-4 used 50-char) + embedding-overlap (paraphrase F1≈0.70) + canary strings (proven: Claude 3.5 / GPT-4 memorized BIG-bench canary) — layer them; rephrase attacks defeat any single one.

## 5. New acceptance tests (add to AgDR-0054)
- **T-poison:** insert ~200 trigger-bearing but execution-valid traces from a hostile neuron; assert (a) per-contributor cap blocks them pre-train, (b) G4 probe flags the checkpoint if any slip through.
- **T-base-audit:** run the G4 probe + red-team on the BASE model before any consolidation; block if it shows a dormant trigger.
- **T-unlearn-honesty:** prove the erasure path is export-gating (drill: revoke a firm; assert absent from next export) AND document that weights-level erasure of shipped checkpoints is impossible (so revocation = retrain-from-clean-checkpoint).
- **T-clean-corpus:** export filter passes ONLY traces matching the founder's clean-corpus policy (origin_kind / generating_model_id / training_rights_tier); assert zero provider-output traces in a "competing-model" training set unless policy permits.
- **T-eval-timesplit:** eval items are all post-training-cutoff; decontamination scan (hash + n-gram + canary) train↔eval = clean.

## Open
- **THE decision:** legality ruling #1 — without it, the flywheel endgame can't legally run on provider traces. Everything else (schema, gates) builds regardless.
- Eval statistical-power section (R5 strand B) arrived thin — size the held-out suite to resolve the deploy-gate deltas before trusting beat-or-demote.
