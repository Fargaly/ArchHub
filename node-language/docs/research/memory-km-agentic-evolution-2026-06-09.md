# Deep research — memory systems · knowledge management · agentic evolution
_For the stream → dam → river collective-mind architecture. 2026-06-09. Design reference — NOT the roadmap._

> **Verification caveat (ANTI-LIE):** gathered by the deep-research harness (fan-out web + fetch). The harness's auto-verify phase failed on a schema bug (every claim got a `0-0` vote → falsely auto-labelled "refuted"). Claims below are **sourced to primary papers and cross-checked as real/known**, but NOT independently triple-verified. Each carries its source; verify load-bearing numbers before building on them.

---

## Court corrections (2026-06-10 — court-collective-mind-final ruled REWORK-FIRST)
Sources verified real on re-fetch; corrections to evidence-weight + provenance (apply before building):
- **Zep (arXiv:2501.13956)** = vendor self-eval; DMR margin only +1.4pp on a near-saturated benchmark; restore "**up to** 18.5%"; MemGPT comparison methodology disputed by the Letta team.
- **KARMA 83.1% (arXiv:2502.06472)** = **LLM-graded** correctness → ~1-in-6 wrong facts pass a KARMA-style gate. The dam needs a declared **false-accept budget + post-merge audit/retraction loop** (nothing currently retracts a merged, downstream-cited fact).
- **SkillsBench −1.3 / +16.2pp** = one concurrent 86-task benchmark cited **secondhand via the SoK survey (arXiv:2602.20867)** — pull the primary (Jiang et al.) before treating "verified-rises" as quantified; label single-benchmark.
- **Dual-retrieval number**: NOT "~⅓ live only in raw" — it's **11.6% RAG-only / 13.6% GraphRAG-only** on MultiHop-RAG; the ~34% is **answer-entity KG-miss** on HotpotQA/NQ (construction loss). Complementarity conclusion stands; framing was wrong.
- **Provenance**: "9%→47.9%" is **MemoryGraft (arXiv:2512.16962)** (n=12 queries, one framework — motivation for per-source caps, not sizing), NOT AgentPoison.
- **Unsourced pillars**: consolidation (episodic→semantic→procedural) and the rank formula (= Generative Agents' exact scoring) have **no rows** — source or mark asserted.
- **TRAINING ENDGAME = ZERO research** (the declared moat): continual learning / catastrophic forgetting, **model collapse** (recursive self-training), **distillation legality** (traces are Claude outputs → provider ToS), RLVR from court verdicts, **training-time poisoning** (~250 docs backdoor any-size model), **machine unlearning**, dedup/curation, train/test **leakage by construction**, eval statistical design. NON-DEFERRABLE — dictates the per-trace logging schema now. Researching next.

---

## Pillar 1 — Agent memory systems

| Finding | Source |
|---|---|
| **Hybrid beats either**: RAG and GraphRAG are complementary — on MultiHop-RAG, 13.6% of queries answered only by GraphRAG, 11.6% only by RAG; concatenating both evidence streams beats the best baseline **+6.4%** (query-type routing only +1.1%). | [arXiv:2502.11371](https://arxiv.org/html/2502.11371v3) |
| **KG extraction is the bottleneck**: only ~65.8% (HotpotQA) / 65.5% (NQ) of answer entities even appear in the constructed KG — KG-only retrieval silently misses what was never extracted. | [arXiv:2502.11371](https://arxiv.org/html/2502.11371v3) |
| **HippoRAG** — hippocampal-indexing retrieval: LLM + KG + Personalized PageRank → single-step multi-hop; up to **+20%** on multi-hop QA, comparable/better than iterative (IRCoT) at a fraction of cost. | [arXiv:2405.14831](https://arxiv.org/abs/2405.14831) |
| **Zep / Graphiti** — temporally-aware KG engine fusing unstructured + structured data, preserving history over time; beats MemGPT on DMR (**94.8 vs 93.4**), **+18.5%** on LongMemEval with **−90% latency**. | [arXiv:2501.13956](https://arxiv.org/abs/2501.13956) |

**Design implications (ArchHub river):**
1. The brain should retrieve **hybrid (vector + temporal-KG)**, not vector-only — ArchHub already has FTS5 + embeddings; add a KG/temporal layer (Graphiti-shaped) rather than betting on KG-only (extraction is lossy).
2. **Keep the raw fragment AND the extracted graph** — because ~⅓ of answers live only in raw text. Never discard the stream when you canonicalize it into the river.
3. **Temporal edges** (valid_from/valid_until — ArchHub fragments already have these) are the right primitive for "history preserved"; lean into time-aware retrieval.

---

## Pillar 2 — Knowledge management: auto-organize the river

| Finding | Source |
|---|---|
| **Auto-organize is a multi-agent pipeline, not one model**: KARMA enriches a collective KG with 9 specialized LLM agents (entity discovery → relation extraction → schema alignment → conflict resolution), with **verification + conflict-resolution gates BEFORE integration** — 83.1% verified correctness, −18.6% conflicts. | [arXiv:2502.06472](https://arxiv.org/abs/2502.06472) |
| **Schema can be auto-induced**: EDC (extract → define-schema → canonicalize) works with **no fixed schema** — it auto-generates a succinct schema and self-canonicalizes entities/relations. This is the "no-manual-promotion" regime exactly. | [ACL 2024.emnlp-main.548](https://aclanthology.org/2024.emnlp-main.548/) |

**Design implications (ArchHub river):**
1. The river's "auto-read + categorize similar workflows" = **extract → induce-schema (EDC) → canonicalize/dedup → conflict-gate (KARMA)**. ArchHub's `brain.organize` (clustering, ticks every 300s) is the seam — extend it toward the EDC/KARMA pipeline, don't hand-curate.
2. **Conflict resolution is a first-class stage**, not an afterthought — when two users' streams disagree, the river must reconcile (KARMA gate), which is also where the HLC last-writer-wins in `brain_replica.py` is too crude alone.
3. Auto-categorization is **decomposable into roles** → fits ArchHub's agent/fleet model (a "categorizer" fleet over the river).

---

## Pillar 3 — Agentic evolution: "verified rises" is empirically mandatory

| Finding | Source |
|---|---|
| **Unverified auto-skills are NET-NEGATIVE**: on SkillsBench, self-generated/self-evolving skills averaged **−1.3pp** vs skill-free (only 1 of 5 configs helped). | [arXiv:2602.20867](https://arxiv.org/html/2602.20867v1) |
| **Verified skills clearly help**: human/verified skills **+16.2pp**; a smaller model + curated skills can beat a larger model without them. | [arXiv:2602.20867](https://arxiv.org/html/2602.20867v1) |
| **Self-gen only works with automated execution-verification** (Voyager, Eureka) + domain specificity — exactly the gate condition. | [arXiv:2602.20867](https://arxiv.org/html/2602.20867v1) |
| **Pooling agents ≠ improvement**: multi-agent systems often barely beat single-agent; MAST taxonomy = 14 failure modes in 3 classes (system design, inter-agent misalignment, **task verification**); failures need **structural** safeguards, not prompt tweaks. | [arXiv:2503.13657](https://arxiv.org/abs/2503.13657) |

**Design implications (ArchHub river):**
1. **"Verified rises" is not optional — it's load-bearing.** A skill enters the river ONLY after passing an **automated execution-verification gate** (this is exactly ArchHub's ROMA court / `reflexion.validate_skill_against_trace` — the research validates it).
2. The gate must be **machine-checkable** (run the skill, check the artifact) — matches ROMA's "external court fails to refute on the real artifact." Manual review doesn't scale to a global river.
3. **Don't assume the collective self-improves by volume** (MAST) — measure that a promoted skill actually lifts pass-rate; demote on regression.

---

## The DAMS — the crux, and where naive designs die

| Finding | Source |
|---|---|
| **Shared skill repos = supply-chain attack surface**: one poisoned skill hits every consumer; the ClawHavoc case = **~1,200 malicious skills** in a major agent marketplace exfiltrating API keys, wallets, browser creds. | [arXiv:2602.20867](https://arxiv.org/html/2602.20867v1) |
| **Memory/RAG poisoning is highly effective + stealthy**: AgentPoison reaches **≥80% attack success** while degrading benign queries **≤1%**; a **single-token trigger** + **<0.1%** poison rate suffices; **evades perplexity filters + query rephrasing**. | [AgentPoison](https://billchan226.github.io/AgentPoison.html) |
| **Auto-ingest is the attack vector**: poisoned "successful experience" records enter long-term memory via **benign-looking content (e.g. README files)** the agent processes — no prompt injection needed. **10 of 110 entries (9%) → 47.9% of all retrievals.** A tiny contamination hijacks the river. | [arXiv:2512.16962](https://arxiv.org/html/2512.16962v1) |

**Design implications (ArchHub dams) — the make-or-break:**
1. **Naive content-filtering dams are insufficient** (AgentPoison evades perplexity/rephrase). The dam must be **provenance + behaviour-based**, not keyword/PII-only. ArchHub's refs-only + bare-cred rejection (`brain_replica.py`) is necessary but **not sufficient**.
2. **Auto-ingesting user workflows into a global pool is a documented poisoning surface.** Every stream entering the river needs: (a) **provenance/trust per source**, (b) **execution-verification before trust** (same gate as "verified rises" — the dam and the rise are the SAME gate), (c) **retrieval-time isolation** so no single source can dominate recall (the 9%→48% finding).
3. **Quarantine + canary**: new contributions land in a low-trust tier; promote to the river only after the verification gate AND no-regression. This is the dam as a *staged lock*, not a one-shot filter.
4. **HLC last-writer-wins is a safety hole at collective scale** — a malicious late write wins. Pair convergence with the trust gate + conflict resolution (KARMA), not LWW alone.

---

## Bottom line for ArchHub
- The **river** (auto-organize) is a real, published pattern: EDC + KARMA = extract→induce-schema→canonicalize→**gate**. Extend `brain.organize`, don't hand-curate.
- **"Verified rises" = the same gate as the security dam** — execution-verification (ArchHub's ROMA court) is what makes auto-promotion safe AND useful. Unverified rises are *net-negative* (SkillsBench) and *dangerous* (AgentPoison).
- The **dams are the hardest, most important part** — and the field shows naive filters fail. Provenance + execution gate + retrieval isolation + quarantine. This is where the architecture must be most rigorous.
- ArchHub already has the seams: `brain.organize` (river), `reflexion`/ROMA court (the gate), `brain_replica` refs-only + isolation (partial dam), temporal fragments (Graphiti-shaped memory). The work = wire them into an **automatic** stream→dam→river with the gate doubling as the security dam.
