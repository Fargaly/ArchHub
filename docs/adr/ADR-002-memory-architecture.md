# ADR-002: ArchHub AI Memory Architecture

**Status:** Proposed
**Date:** 2026-05-13
**Deciders:** Fargaly (founder) · Claude (backend)
**Supersedes:** none. Extends ADR-001 §6 (Memory page training pipeline placeholder).

## Context

The Memory page shipped in v1.3.3 (Capture → Redact → Judge → Train) is a thin UI surface over one table — `training_samples`. That's enough to *show* the pipeline but not enough to be the **infrastructure of ArchHub's community-based approach** the founder asked for.

State-of-the-art (May 2026) for AI agent memory consolidates around three patterns we don't yet have:

1. **Multi-tier memory** — Letta (formerly MemGPT) splits memory into core/archival/recall; Mem0 runs a hierarchical extraction phase that produces ADD/UPDATE/DELETE/NOOP operations against an evolving fact store; Zep stores facts in a temporal knowledge graph with validity windows.
2. **Vector retrieval over raw chat logs** — semantic similarity surfaces relevant past turns regardless of exact wording. pgvector / Qdrant / Weaviate are mature.
3. **Collaborative memory with access control** — arXiv 2505.18279 "Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control" formalises private vs shared fragments with provenance + redaction policies.

Our community ambition (Codex prototype's "Searchable collective memory · community-safe layer") needs all three. The current single-table store cannot:
- Distinguish a fact about *one user's project* from a fact about *Revit semantics*
- Retrieve "what did we decide last time about wall types" without exact-match search
- Promote a redacted pattern from one user's session into shared knowledge with audit trail
- Update a fact when reality changes (Mumbai → Bangalore, in Mem0's canonical example)

This ADR proposes the architecture that closes those gaps.

## Decision

Adopt a **5-tier memory model**:

```
┌──────────────────────────────────────────────────────────────┐
│  HOT  (working memory — in-process)                          │
│  Current chat window context (last N turns + system prompt). │
│  Already exists; no change.                                  │
└──────────────────────────────────────────────────────────────┘
                              │  end-of-session: extract + summarise
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  EPISODIC  (training_samples — ALREADY SHIPPED v1.3.3)       │
│  Raw approved chat turns + tool_trace.                       │
│  Stages: captured → redacted → judged → approved | rejected. │
│  No change. This is the SOURCE for fact extraction.          │
└──────────────────────────────────────────────────────────────┘
                              │  Mem0-style ADD/UPDATE/DELETE/NOOP
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  SEMANTIC  (memory_facts — NEW)                              │
│  Atomic facts: who/what/when, confidence, source provenance, │
│  validity window, scope, visibility, optional embedding.     │
│  FTS5 index for keyword + Postgres pgvector for embedding.   │
└──────────────────────────────────────────────────────────────┘
                              │  promote (redacted) with consent
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  COLLECTIVE  (collective_memory — NEW)                       │
│  Anonymised + redacted patterns shared across community.     │
│  Provenance + audit per arXiv 2505.18279. Searchable by all. │
└──────────────────────────────────────────────────────────────┘
                              │  optional: train apprentice once
                              ▼  approved >= TRAIN_READY_THRESHOLD
┌──────────────────────────────────────────────────────────────┐
│  PROCEDURAL  (apprentice LoRA weights — DEFERRED)            │
│  LoRA fine-tune of OSS base on approved episodic samples.    │
│  Lives on Modal/GPU. Wires in v1.5 per ADR-001 Stack A.      │
└──────────────────────────────────────────────────────────────┘
```

### Tier shapes

**SEMANTIC (`memory_facts`)** — atomic fact rows. One fact per row. Examples:
- "User prefers metric units" (scope=user)
- "Project Tower-A uses Generic-200mm as default wall type" (scope=project, project_id=...)
- "Revit's `Wall.Create` requires Level reference at locationCurve start" (scope=global)

Columns:
- `id`, `user_id`, `company_id NULLABLE`, `project_id NULLABLE`
- `scope`: `user | project | company | global`
- `visibility`: `private | shared_company | shared_public`
- `subject`, `predicate`, `object`, `text` (denormalized full-text)
- `confidence` 0-1 float
- `source_sample_id` (FK to training_samples)
- `valid_from`, `valid_until` (NULL = current)
- `created_at`, `last_reinforced_at`, `reinforce_count`
- `embedding BLOB NULLABLE` (384-dim MiniLM or 1536-dim OpenAI; absent until embed worker runs)

Plus an FTS5 virtual table mirroring `text` so SQLite-only deployments still get search. When migrated to Postgres (per ADR-001 §7 revisit at v1.5), embeddings move to `pgvector`.

**COLLECTIVE (`collective_memory`)** — community-shared facts. Same shape as semantic minus user identity, plus:
- `contributing_user_id` (the promoter, kept for audit)
- `redaction_policy_id` — which prompt template was applied before promotion
- `promoted_at`
- `access_policy`: `public | architects_only | studio_tier+`

**Audit log (`memory_access_log`)** — per arXiv 2505.18279. Every read of a shared fact records `(reader_user_id, fact_id, ts, purpose)`. Every promotion records `(promoter_user_id, fact_id, redaction_applied, ts)`.

### Operation set (Mem0-style)

Memory updates are NOT INSERT-only. Four operations:

| Op | Semantics | Example |
|---|---|---|
| **ADD** | New fact, no conflict with existing | "User uses Revit 2024" (first observation) |
| **UPDATE** | Refines existing fact (more specific, higher confidence) | "User uses Revit 2024" → "User uses Revit 2024 + 2025" |
| **DELETE** | Old fact superseded | "User in Mumbai" → "User in Bangalore"; old row gets `valid_until=now` |
| **NOOP** | Already known | Stops duplicate ingestion |

Implemented in `cloud_backend/memory_writer.py`. Each session's approved samples go through an extractor (instructor LLM call) that emits operation tuples; writer applies them in a single transaction.

### Privacy + redaction

Following arXiv 2505.18279 "Collaborative Memory":
- **Two policies**: `simple` (verbatim) and `transform` (LLM redacts before write).
- `transform` policy is *required* for any `visibility != private` fact.
- Redaction prompt is content-aware: strip client names, file paths, addresses, dollar amounts, PII patterns.
- Reader-side: shared facts always carry `provenance.contributing_company_id` so audits can trace.

### Retrieval

Three paths:

1. **Keyword (FTS5)** — fast, exact-ish. Default first-line retrieval.
2. **Vector** — when embedding exists, cosine similarity top-K. Embedding worker runs async.
3. **Hybrid** — RRF (reciprocal rank fusion) of keyword + vector. Used for "deep memory" queries.

Per Hermes OS' "dual-layer architecture" guidance: Hot Path = recent context + summary; Cold Path = retrieval from semantic+collective via above three.

## Options Considered

### Option A: 5-tier with SQLite + FTS5 today, pgvector later (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | **Medium** — adds three tables + DAO + writer + extractor |
| Cost | $0 incremental (rides existing Fly cloud_backend) |
| Scalability | FTS5 fine to ~100K facts; pgvector swap when needed |
| Lock-in | None — SQLite + plain Python |
| Privacy posture | Strong — redaction-on-promote enforced at the writer |

**Pros**: ships in days, no new infra, matches state of the art on shape if not on retrieval speed.
**Cons**: vector search via Python loops (no ANN index) until pgvector migration; embedding worker is best-effort.

### Option B: Drop in Mem0 / Zep / Letta as a service

| Dimension | Assessment |
|---|---|
| Complexity | **Low** initial integration; **High** debugging unknowns |
| Cost | $30-200/mo at scale, free tier available |
| Scalability | Vendor-managed, generally good |
| Lock-in | Strong — vendor schema, vendor API |
| Privacy posture | Depends on vendor; multi-tenant exposure for shared facts |

**Pros**: matures the feature in hours not days.
**Cons**: external dependency on PII-bearing service; pricing climbs with usage; no control over the redaction policy needed for community sharing.

### Option C: Knowledge graph (Neo4j / Graphiti)

| Dimension | Assessment |
|---|---|
| Complexity | **High** — graph data model is a paradigm shift for the team |
| Cost | $0 self-host, $$ managed |
| Scalability | Excellent for relational queries |
| Lock-in | Strong — Cypher syntax, graph mental model |
| Privacy posture | Same as Option A |

**Pros**: multi-hop queries (Zep's win); natural fit for AEC ontologies (Wall hasPart Door, Project contains Sheet).
**Cons**: overkill for v1.5; we can layer Graphiti on top of `memory_facts` later if the AEC ontology demands hop-3+ traversals.

### Option D: Vector-only (skip facts, embed raw turns)

| Dimension | Assessment |
|---|---|
| Complexity | **Low** |
| Cost | Cheapest |
| Scalability | OK |
| Lock-in | None |
| Privacy posture | Weak — raw turns contain PII verbatim |

**Pros**: simplest possible thing that works.
**Cons**: cannot UPDATE/DELETE facts (the Mumbai→Bangalore problem); cannot promote individual facts without re-embedding whole turns; cannot scope by `project_id` cleanly.

## Trade-off Analysis

Real axes:

| | Option A (chosen) | Option B (Mem0) | Option C (graph) | Option D (vector-only) |
|---|---|---|---|---|
| **Ship today** | yes | yes | no | yes |
| **Update semantics** | yes (ops set) | yes | yes | no |
| **Community sharing** | yes (policy enforced) | hard (vendor multi-tenant) | yes | weak |
| **AEC ontology fit** | OK (text+predicate) | OK | best | weak |
| **Cost ceiling** | $0 today, $$ later | $30-200/mo | $0-$$$ | $0 |
| **Reversibility** | easy | hard | medium | easy |

Option A wins because it preserves **reversibility** and **control over the redaction layer**, both of which matter for a community-shared product where one leaked client name is a reputational event. We accept the cost of building the writer + extractor in-house because we *want* to own the privacy boundary.

Option C (graph) is a **future option**, not a competitor today. Once `memory_facts` has > 50K rows AND we observe hop-3+ AEC queries (e.g. "find rules for fire-rated walls that touch occupied spaces above grade"), layer Graphiti on top of the same rows.

## Consequences

What becomes easier:
- The Memory page can show *facts* not just *raw samples* — much more usable.
- Cross-session context: a new chat about Tower-A pulls in the project-scoped facts from prior sessions automatically.
- Community marketplace of facts: studios publish redacted dimensioning patterns; other studios install them.
- Apprentice training (deferred per ADR-001) gets a cleaner signal — train on facts not on chat noise.

What becomes harder:
- Two new failure modes: extractor over-extracts (false ADD) or under-extracts (NOOP when should ADD). Mitigated by `confidence` floor on ADD and human-in-loop approve at the Judge stage.
- Redaction can leak PII if the prompt template is wrong. Mitigated by required `transform` policy on any non-private write + per-tenant pen-test before opening shared writes.
- Schema migration once pgvector lands; manageable, well-trodden path.

What we'll need to revisit:
- **Move to pgvector** when fact count > 50K OR retrieval p99 > 200ms on FTS5 alone.
- **Layer Graphiti** when AEC ontology queries demand multi-hop.
- **Add Modal-hosted embedding service** when SQLite vector loops cost > $5/mo in Fly CPU.
- **Open shared writes** only after the redaction policy passes an internal red-team pass.

## Action Items

Phase 1 — Foundation (this commit, today)
1. [x] Write ADR-002 (this file).
2. [ ] Schema migration: `memory_facts`, `memory_facts_fts`, `collective_memory`, `memory_access_log`, `memory_op_log`.
3. [ ] DAO in `cloud_backend/db.py`: insert/update/delete/lookup/search/promote.
4. [ ] Writer in `cloud_backend/memory_writer.py`: applies ADD/UPDATE/DELETE/NOOP ops in one transaction; logs every op.
5. [ ] Extractor stub in `cloud_backend/memory_extractor.py`: takes an episodic sample, returns list of ops. v1 uses heuristic regex + tag templates; v2 calls instructor LLM.
6. [ ] Endpoints in `cloud_backend/main.py`:
   - `POST /v1/memory/facts` (manual add)
   - `GET /v1/memory/facts?scope=&q=&limit=` (search/list)
   - `PUT /v1/memory/facts/{id}` (update + valid_from bump)
   - `DELETE /v1/memory/facts/{id}` (sets valid_until)
   - `POST /v1/memory/facts/{id}/promote` (private → shared, with redaction)
   - `POST /v1/memory/extract` (run extractor on a session)
   - `POST /v1/memory/search` (hybrid retrieval)
7. [ ] Tests: 20-25 covering DAO + writer ops + endpoint auth + redaction enforcement.

Phase 2 — UI surface (follow-up PR)
8. [ ] Memory page (`studio_shell.py:_build_memory_page`) gains a "Facts" tab showing user's facts list with source attribution, manual edit, and a /remember composer hint.
9. [ ] Composer `/remember <fact>` slash command → POST /v1/memory/facts manually.
10. [ ] Collective memory feed: replace canned rows with real GET /v1/memory/collective.
11. [ ] Add Permissions tab to Settings — AUTO/ASK/BLOCK for memory writes per scope.

Phase 3 — Retrieval into chat (v1.4 ship)
12. [ ] Hook semantic+collective retrieval into the proxy's chat_completions pre-pass. Inject top-K relevant facts into system prompt.
13. [ ] Embedding worker as a job in agents/. Uses sentence-transformers MiniLM at first; OpenAI text-embedding-3-small when key available.

Phase 4 — Community (v1.5+)
14. [ ] Promote flow UI: pick a fact → preview redaction → publish.
15. [ ] Subscribe-to-community-fact-pack flow.
16. [ ] Per-tenant pen-test of redaction before shared-write GA.

## Reversal Plan

Memory tier rollout is **strictly additive**. If the Semantic tier proves unhelpful (extractor doesn't surface anything valuable), the rows are dead but cause no harm — the Episodic tier (training_samples) keeps working untouched. The endpoints are versioned `/v1/memory/...` so a future `/v2/...` schema swap doesn't break clients.

If we later want to migrate off Option A to vendor Mem0/Zep, the rows transfer as a flat fact list — that's the most-portable possible shape.

## References

- [Mem0 — State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Letta architecture (formerly MemGPT)](https://hermesos.cloud/blog/ai-agent-memory-systems)
- [Zep + Graphiti — temporal knowledge graph](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
- [Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control (arXiv 2505.18279)](https://arxiv.org/abs/2505.18279)
- [Graph-based Agent Memory: Taxonomy, Techniques, and Applications (arXiv 2602.05665)](https://arxiv.org/html/2602.05665v1)
- [Best Vector Databases in 2026 — pgvector / Qdrant / Milvus benchmarks](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb)
- [AI Memory vs RAG vs Knowledge Graph — Enterprise Guide 2026](https://atlan.com/know/ai-memory-vs-rag-vs-knowledge-graph/)
