---
id: AgDR-0044
timestamp: 2026-05-25T00:00:00Z
agent: claude-code (Opus 4.7 · 1M ctx)
session: workshop-personal-brain-substrate
trigger: founder request 2026-05-25 — "shared memory across all AI agents · skills · setups · secrets · real-time · cross-device · inside + outside ArchHub"
status: executed
founder-signoff: 2026-05-25 — picked F1.B + F2.A + F3.A(+Speckle spatial) + F4.A on docs/prototypes/personal-brain-2026-05-25.html
category: architecture
projects: [archhub, personal-brain-mcp]
supersedes: extends AgDR-0042 §"Multi-seat sharing" + AgDR-0013 §"Layer 3 enforcement"
slices:
  - "slice 1/8 — FastMCP scaffold + 4 tools (brain.context, brain.write, brain.skill_mint, brain.wiring_announce)"
  - "slice 2/8 — embedding + retrieval (MiniLM/bge-small + FAISS)"
  - "slice 3/8 — Claude Code hook wiring (~/.claude/settings.json drop-in)"
  - "slice 4/8 — ArchHub Layer 5 (llm_router.py:1232/1410/1430/1378)"
  - "slice 5/8 — reflexion worker (Voyager + SkillWeaver hone-before-publish)"
  - "slice 6/8 — multi-device sync (Loro CRDT + Tailscale + Speckle spatial transport)"
  - "slice 7/8 — bipartite ACL + redaction (arXiv 2505.18279)"
  - "slice 8/8 — community tier (FICAL + DP-noise + ActivityPub discovery)"
---

# Personal Brain MCP — ambient agent substrate across all AI clients

> Founder picked F1.B (build from scratch on `app/memory/graph.py`) + F2.A
> (Voyager+SkillWeaver hybrid skill mining) + F3.A (Loro CRDT + Tailscale,
> EXTENDED with Speckle as parallel transport for geometrical/spatial memory)
> + F4.A (community tier in V1). Total scope: 8 slices, ~6-10 weeks. Ships as
> bundled-with-ArchHub daemon, outlives sessions, reachable from every MCP
> client (Claude Code, Cursor, ChatGPT, Codex, Gemini CLI, Cline, Continue,
> ArchHub Composer). Built on full ownership of the substrate so future
> federation + ACL + spatial-memory primitives stay first-class.

## Context

Workshop 2026-05-25 (this AgDR's deliverable: `docs/prototypes/personal-brain-2026-05-25.html`)
held a 7-hat planning council over the founder's request: a shared substrate
that EVERY AI agent the founder uses (Claude Code, Cursor, ChatGPT desktop,
Codex CLI, Gemini CLI, ArchHub Composer) connects to and shares memory + skills
+ setups + secrets in REAL TIME, across devices and across community. The
council pulled R&D from 6 parallel scouts spanning 50+ projects (agent memory:
mem0/Letta/Zep/agentmemory/OMEGA/Mastra etc; skill mining: Voyager/ExpeL/
SkillWeaver/SAGE; sync: Loro/Automerge/Anytype/Speckle; neuroscience: CLS/
reconsolidation/replay; library science: PMEST/Topic Maps; MCP ecosystem state)
and surfaced four open forks for founder sign-off.

ArchHub already has 60% of the substrate built:
- `app/memory/graph.py` (505 LoC) — MemoryGraph nodes + edges + SQLite
- `app/memory/sync.py` (267 LoC) — push/pull/merge + JsonFileTransport
- `app/memory/extractors/` — turns/library/decisions/projects extractors
- `app/memory/communities.py` — Louvain detection
- `app/library_gate.py` — Layer 3 router gate pattern (template for Layer 5)
- AgDR-0013 4-layer multi-LLM enforcement → adds Layer 5 (memory I/O hooks)

What's missing: live (not batch) write path, cross-client MCP server, semantic
retrieval, reflexion worker for skill mining, bipartite ACL, redaction-on-
promote, Loro CRDT replacing ts-wins sync, Speckle spatial transport, and the
federation tier.

## Forks resolved (founder picks)

### Fork 1 — Substrate origin: **F1.B · Build from scratch on `app/memory/graph.py`**

| Option | Picked | Why |
|---|---|---|
| A) Fork agentmemory + bolt on | no | 9.3k★ but Apache-2.0 derivative work; brain shape doesn't match MemoryGraph |
| **B) Build from scratch on `app/memory/graph.py`** | **YES** | Full ownership · brain matches existing graph exactly · clean ACL primitives · no upstream drift risk · ~10 weeks instead of ~6 |
| C) Mem0 managed service | no | vendor lock-in · no on-prem for firms · no auto-skill-mint |

### Fork 2 — Skill-mint trigger: **F2.A · Voyager + SkillWeaver hybrid**

| Option | Picked | Why |
|---|---|---|
| **A) Voyager + SkillWeaver hybrid** | **YES** | Critic-LLM verifies trace ✓ → propose skill → 3 sandbox trials → publish only if ≥2/3 succeed · highest quality · ~30s post-turn off-thread (no UX block) |
| B) Pure trace-similarity (hash + ≥5 occurrences) | no | Late-mints; misses one-shot novel skills |
| C) Founder-approval-gated | no | Velocity floor; abandonment risk |

### Fork 3 — Sync substrate: **F3.A · Loro CRDT + Tailscale, EXTENDED with Speckle**

Founder addition 2026-05-25: *"consider fork speckle as you can also allow for
geometrical and spatial memory"* — this is the right move. ArchHub already ships
Speckle Versions; its content-addressed model is purpose-built for geometric
data hashing. Adopt a **dual-transport architecture**:

```
                       brain.write(fragment)
                                 │
                ┌────────────────┴────────────────┐
        is_spatial?                          is_text/json?
                │                                 │
                ▼                                 ▼
   ┌────────────────────────┐         ┌────────────────────────┐
   │  Speckle Transport     │         │  Loro CRDT Transport   │
   │  ─ Revit walls/floors  │         │  ─ memory facts        │
   │  ─ AutoCAD blocks      │         │  ─ skill markdown      │
   │  ─ Blender meshes      │         │  ─ setups / wiring     │
   │  ─ Speckle objects     │         │  ─ session traces      │
   │  ─ camera framings     │         │                        │
   │  content-addressed     │         │  movable-tree CRDT     │
   │  immutable Versions    │         │  HLC-ordered writes    │
   │  per-stream ACL        │         │  Tailscale mesh        │
   └────────────────────────┘         └────────────────────────┘
                │                                 │
                └──────────────┬──────────────────┘
                               ▼
                       brain.query(intent)
                       cross-transport unified retrieval
                       (Speckle hashes + Loro CRDT joined via
                        MemoryGraph edges using both as values)
```

**Why dual-transport beats single-transport:**

- **Spatial memory is content-addressed by nature.** A specific wall composition,
  a render framing, a Blender mesh — these are best identified by Merkle hash, not
  CRDT op-log. Speckle Versions already do this well; reusing them costs near zero.
- **Text/skill memory is mutable by nature.** Skills get refined, facts update.
  Loro CRDT semantics fit; Speckle's immutability would force versioning explosion.
- **Cross-firm spatial reuse is high value.** "Show me how other firms detailed
  a Tower-base rain screen at 200mm" is a geometric memory query — Speckle's
  content-addressed objects make this O(1) hash lookup.
- **Privacy is naturally layered.** Spatial fragments are fingerprintable but
  not directly readable; firm can choose to expose Merkle hashes (interface) without
  exposing the wall composition (substance). Defers the redaction problem to a
  hash-vs-content boundary that's easier to audit.

### Fork 4 — Community tier timing: **F4.A · Include in V1**

| Option | Picked | Why |
|---|---|---|
| **A) Include community tier in V1** | **YES** | Builds the moat NOW; founder values network effect over time-to-market; aligns with VISION.md "Composer + Library + Community" |
| B) Defer to V2 | no | Trades moat for velocity; community catch-up is harder than initial build |

## Decision — architecture lock

### Five live loops underneath every AI client

| Loop | Trigger | Action | Latency budget |
|------|---------|--------|----------------|
| **Context inject** | `UserPromptSubmit` hook (Claude Code/ArchHub) OR session-init server `instructions` (everywhere else) | Embed prompt → top-K skills/facts/wiring/secret-refs → prepend to system prompt | <100ms |
| **Tool augment** | `PreToolUse` hook | Resolve `op://` secret refs at call time, expose available MCPs from wiring registry | <50ms |
| **Memory write** | `PostToolUse` hook | Mem0-style ADD/UPDATE/DELETE/NOOP ops live (not batch) with provenance | <200ms async |
| **Skill mint** | `Stop` hook (per turn) | Voyager critic verifies → SkillWeaver hone 3× → ModularNodeSpec validate → publish to library | seconds, off-thread |
| **Wiring sync** | `SessionStart` hook + config changes | Announce which MCPs configured, which CLIs installed, which models authed on this device | <1s, idempotent |

### One MCP server, two transports

- **FastMCP Python** server. SQLite + FTS5 + FAISS (MiniLM 384-dim embeddings).
- **stdio** transport for local-resident clients (low latency, env-var bearer auth).
- **Streamable HTTP** transport for remote clients (ChatGPT desktop requires it; OAuth 2.1 + PKCE + DCR).
- One binary serves both transports simultaneously.

### Layer 5 attaches to existing AgDR-0013 router

```
llm_router._complete_once (line 1178)
  line 1232  ◄── LAYER 5 PRE-PROMPT     · brain.context()
  line 1366      stream_completion
  line 1410  ◄── LAYER 5 PRE-EXECUTE    · memory gate + secret resolve
  line 1430  ◄── LAYER 5 POST-EXECUTE   · brain.write(ops, provenance)
  line 1378  ◄── LAYER 5 STOP (per turn) · brain.skill_mint(trace)
```

`MemoryGate` is a sibling of `LibraryGate` (per AgDR-0013 Layer 3). Reuses
`TurnState` pattern. Provider-agnostic by construction (every client lands
in the same dispatch loop with normalized `ToolInvocation` shape).

### Five scope tiers (extends AgDR-0042 sharing model)

| scope | visibility | who reads | who writes | transport |
|-------|------------|-----------|------------|-----------|
| `user` | private | owner | owner | local SQLite |
| `project` | shared_project | project members | project members | Loro per-project doc |
| `firm` | shared_company | firm seats | firm seats | Loro firm-doc + Speckle stream |
| `community` | shared_public | subscribers | promoter (redacted) | content-addressed pull |
| `global` | canonical | all | maintainers | OSS skill packs |

### Skill-mint pipeline (Voyager + SkillWeaver hybrid)

```
1. Stop hook fires → reflexion_worker enqueues trace
2. Critic-LLM verifies success (end-state matches goal)        ◄── Voyager
3. Distill: trace → ModularNodeSpec proposal (per AgDR-0013)
4. SkillWeaver-style hone: run 3 sandbox trials                ◄── SkillWeaver
5. Pass gate iff ≥2/3 trials succeed AND validator(ok)
6. Description quality check: delta-debug + adversarial test
7. Auto-generate 20 eval queries (10 should-trigger / 10 shouldn't)
8. Compute novelty: cosine vs existing skills (≥0.25 = NEW; else UPDATE)
9. Write to library/<scope>/<slug>.md with provenance
10. Skill is immediately retrievable via brain.context
```

### Decay + lifecycle (Ebbinghaus + Anthropic budget pattern)

- Each skill carries `last_used_at`, `success_count`, `fail_count`, `half_life_days`.
- `score = α·recency_decay + β·importance + γ·relevance` (Generative Agents).
- Description budget = 1% of model context window; least-invoked descriptions
  truncated first on overflow (Anthropic pattern).
- Skill never deleted — moved to `archived/` after 90d unused; recoverable.
- Body stays full-fidelity; only descriptions decay.

### Provenance + audit (arXiv 2505.18279)

Every fragment carries immutable:
- `contributing_agent` (`claude-sonnet-4.7`, `gpt-5`, `gemini-2.5-pro`, …)
- `contributing_user` (which seat)
- `session_id` + `trace_id` (link back to source)
- `accessed_resources` (which secrets, which MCPs, which files)
- `created_at`, `last_reinforced_at` (HLC timestamps)

Bipartite ACL graph: `(user, fragment)` + `(agent, fragment)` + `(resource, fragment)`.
Retrospective check on every read — `memory_access_log` records `(reader, fragment, ts, purpose)`.

### Secrets — references only

Brain stores `op://vault/notion/token` references. **Never values.** At PreToolUse:
1. Hook intercepts call needing secret
2. Resolves via 1Password CLI / Infisical / Windows Credential Manager
3. Injects value into tool argument scope
4. Scrubs trace logs of resolved value
5. Audit records "used secret X" without value

## Build slices (8 total · 6-10 weeks)

### Phase A — local foundation (~2 weeks)

1. **FastMCP scaffold** — `personal-brain-mcp/` repo. 4 tools, SQLite, both transports.
2. **Embedding + retrieval** — `brain/embeddings.py`, FAISS index, MiniLM 384-dim.
3. **Claude Code wiring** — `~/.claude/settings.json` drop-in. SessionStart + UserPromptSubmit + PostToolUse + Stop hooks.
4. **ArchHub Layer 5** — insert at `llm_router.py:1232/1410/1430/1378`. New `app/memory_gate.py`.
5. **Reflexion worker** — Voyager+SkillWeaver skill mining. Reuses `app/library_validator.py:ModularNodeSpec`.

### Phase B — multi-device (~1 week)

6. **Loro + Speckle sync** — primary Loro CRDT for memory/skills, secondary Speckle Versions for spatial fragments. Tailscale mesh for personal+firm. HLC timestamps.

### Phase C — federation (~3-5 weeks)

7. **Bipartite ACL + redaction** — `brain/acl.py`, `brain/redaction.py`. Promote-with-LLM-redaction. arXiv 2505.18279 conformant.
8. **Community tier** — FICAL pattern compendium + DP-noise + ActivityPub discovery + content-addressed Speckle pull. Reputation gating per Wikidata pattern.

## Consequences

### What becomes easier

- Skills minted in Claude Code session at 3am are usable in ArchHub Composer next morning. Same SQLite, same retrieval.
- Cross-firm spatial memory query: "show me how firms detail X" becomes a Speckle hash search across opted-in firms.
- New seat onboarding: brain restores their entire setup (wiring + secrets refs + preferred skills) on first launch.
- Multi-LLM neutrality: switching from Claude to Gemini mid-session preserves context because the brain layer sits below the provider.

### What changes in existing code

- `app/llm_router.py` — 4 hook insertion points added (~150 LoC)
- `app/memory/sync.py` — JsonFileTransport stays, add LoroTransport + SpeckleSpatialTransport
- `app/memory/graph.py` — extend MemoryNode with `scope`, `visibility`, `owner_user`, `provenance{}`, `acl_edges`
- `cloud_backend/main.py` — `/v1/brain/*` endpoints for federation tier
- `app/bridge.py` — new slots for brain control panel UI

### New code estimate

| Component | LoC est. | Notes |
|-----------|----------|-------|
| `personal-brain-mcp/server.py` | 400 | FastMCP + 4 tools |
| `brain/embeddings.py` | 150 | MiniLM + FAISS |
| `brain/retrieval.py` | 200 | scope-filtered query |
| `brain/reflexion.py` | 500 | Voyager + SkillWeaver worker |
| `brain/acl.py` | 300 | bipartite check |
| `brain/redaction.py` | 200 | LLM-redaction pass |
| `brain/sync_loro.py` | 350 | Loro CRDT wrap |
| `brain/sync_speckle_spatial.py` | 250 | Speckle Versions wrap for geometry |
| `brain/federation.py` | 600 | FICAL + DP + ActivityPub |
| `app/memory_gate.py` (ArchHub side) | 250 | Layer 5 gate (mirrors library_gate) |
| `hooks/claude-code.json` + installers | 100 | config snippets |
| Tests | 800 | ~40% of total |
| **Total** | **~4100 LoC** | excluding existing reused code |

### What this kills

- The "batch extractor" path in `app/memory/extractors/`. Live writes via Layer 5
  supersede; extractors stay as backfill for historical data only.
- The "single transport" assumption in `sync.py`. Now multi-transport with router.
- The notion of skills-as-frontmatter-only. Skills now have full provenance + lifecycle.

### Risks

- **CRDT semantic dedupe.** Two devices independently mint same-named skill → both
  keep. Mitigation: embedding-similarity check at write time (≥0.85 cosine = MERGE,
  not separate).
- **Echo Trap.** Reward variance collapse on self-mined libraries. Mitigation:
  Voyager-style exploration term in reflexion prompt ("discover diverse skills").
- **OAuth dance for ChatGPT desktop.** One-time user click per device — can't be
  fully automated. Acceptable per AUTOMATION MANDATE exception (3rd-party UI auth).
- **Speckle transport drift.** Speckle Versions are immutable; spatial memory
  garbage-collection is non-trivial. Mitigation: TTL on least-cited hashes,
  pinning recent + canonical objects.

## Artifacts

- This AgDR.
- `docs/prototypes/personal-brain-2026-05-25.html` — workshop prototype + 7-hat
  council output + interactive demo (founder signed off 2026-05-25).
- `personal-brain-mcp/` — new repo (Slice 1).
- `app/memory_gate.py` — Layer 5 gate (Slice 4).
- `brain/sync_speckle_spatial.py` — spatial transport (Slice 6).
- `cloud_backend/brain/` — federation tier endpoints (Slices 7-8).
- 27 citations in prototype footer.

## Slice tracking

Each slice ships with:
1. Code commit + clean working tree
2. Tests passing (≥80% coverage on new modules)
3. AgDR slice-line flipped from `pending` to commit SHA
4. Pre-flight gate per CLAUDE.md (built · restarted · reachable · visible · clickable · persistent · discoverable)
5. CDP screenshot proof where UI surfaces (slices 4, 7, 8)

## Not in scope (deferred to V1.5+)

- ChatGPT mobile / web app — depends on OpenAI shipping MCP there (TBD)
- Cursor full prompt-level hook — depends on Cursor extending hook surface
- Skill marketplace UI (vs library browser) — V2 product surface
- Multi-tenant cloud (vs per-firm sync) — would require redesigning federation tier
- Cross-firm "community" beyond ~1000 subscribers — gossip protocol (SWIM) belongs in V1.6
