# Pi.dev → ArchHub — consolidation + collective-brain design
_Design reference — NOT the roadmap (see docs/ROADMAP.md). Grounded in real source, file:line. 2026-06-09._

## 0. The job
Fold pi.dev's per-user ergonomics into ArchHub's **composer / router / graph / nodes**, riding ArchHub's **multi-user collective brain** (scopes + privacy + DB layers). Pi is single-user/local; ArchHub is multi-user/collective — so we take pi's **patterns**, not its storage.

---

## 1. Reality — what already exists (verified in source)

### ArchHub — the 4 systems
| System | Where | State |
|---|---|---|
| Router | `app/llm_router.py` `_route()` ~:934, `KNOWN_MODELS` ~:418 | Multi-provider (Anthropic/OpenAI/Google/CLI), **heuristic** model pick, local-first (claude_cli). NOT model-driven. |
| Composer | `app/agents/composer_agent.py` `run_agent_step`:291, `TOOL_SCHEMA`:111 (spawn_node/add_wire/set_node_param/run_node/run_workflow/query_graph/chat); `composer_commands.py detect_intent` | Already **agentic**; P/A/Y gating. |
| Graph | `app/workflows/graph.py` (Node/Edge/Workflow/PortType), `executor.py` (topo, sequential) | Node DAG works. |
| Nodes | `registry.py`, `custom_nodes.py` (`impl.kind` python/connector/ai/graph), `node_grammar.py`, `tool_engine.py` (node.search/create/place, graph.wire) | **Richer than pi** — capability nodes + library. |
| Sessions | `app/session_io.py save_session` → `%LOCALAPPDATA%/ArchHub/sessions/*.archhub-session.json` | **Flat JSON. No tree, no parentId, no scope.** |

### ArchHub — the collective brain / DB / privacy (the hard part)
| Piece | Where | State |
|---|---|---|
| Local store | `personal-brain-mcp/.../storage.py` | `fragments` + `skills` each carry **scope · visibility · owner_user · project_id · firm_id**; FTS5. |
| **ONE-SYSTEM debt** | `storage.py` header | In-code: *"slice 2 will wire app.memory.graph.MemoryGraph as a backend adapter"* — **never done**. Two local stores (`brain.db` + `app/memory/graph.sqlite`). |
| Cloud replicas | `cloud_backend/brain_replica.py` | Per **user / firm / community** dbs; **Slice-17 fanout** (your USER rows ⊎ every firm/community you belong to); **HLC LWW** merge; membership **server-resolved**; **per-user isolation forced**. |
| Privacy | `brain_replica.py` header + `app/resolver_registry.py` | Secrets = **refs only** (`op:// wcm:// env:// inline:`); bare creds **rejected**; resolution on-device only; GDPR delete = drop per-user dir. |
| Sync | `personal-brain-mcp/.../sync.py` | `Transport` (push/pull); **Loro CRDT** (text/skills) + **Speckle** (spatial, content-addressed). |
| Promote/recall | `brain.promote`, `brain.context` | USER→PROJECT→FIRM→COMMUNITY→GLOBAL promote; recall pulls the union. |
| **Status** | brain.health | Local brain **healthy** (64 skills/410 facts). **Cloud sync = HTTP 401** (sign-in broken → collective sync currently OFF). |

### pi.dev (Earendil, MIT) — what we borrow
| Pi piece | Detail |
|---|---|
| `pi-ai` | Unified LLM API, 15+ providers, mid-session switch (`ModelRegistry`). |
| `pi-agent-core` | Agent loop + tool-calling + state. |
| Tree history | session = **JSONL, each turn `{id, parentId}`** → in-place branching; `/tree` `/fork` `/clone`. |
| Tools/ext | `ExtensionAPI.registerTool({...})`; **Agent-Skills** `/skill:name`; prompt templates. |
| SDK/RPC | `createAgentSession`, `SessionManager`; RPC = JSONL over stdio. |

---

## 2. Consolidation — per system (adopt / have / borrow)

| System | pi gives | ArchHub now | Verdict | Seam (file:fn) |
|---|---|---|---|---|
| **Router** | pi-ai provider abstraction + mid-session switch | multi-provider heuristic router | **HAVE** core; **BORROW** mid-session switch UX. The "agentic router" you want is **NEW** (neither has a planner) → add a planner over `_route()` | `llm_router.py:_route` |
| **Composer** | agent loop + **mid-run steering** + ExtensionAPI | agentic composer + P/A/Y | **HAVE**; **BORROW** steering + extension ergonomics | `composer_agent.py:run_agent_step` |
| **Graph / Sessions** | **tree history** (id+parentId, /tree /fork /clone) | flat JSON sessions, linear chat | **BORROW** — the signature gap → make sessions a **branchable tree** (the visual steer) | `session_io.py`, `session.py` |
| **Nodes** | Agent-Skills + prompt templates | capability nodes + library + brain skills | **HAVE** (richer); **BORROW** skill-authoring ergonomics into brain | `custom_nodes.py`, brain `skills` |

**Net:** ArchHub already owns router/composer/nodes. Pi's real additive gift = the **branching session tree** as the visual control surface. Don't replace the node/brain/connector systems.

---

## 3. The collective layer — where pi's per-user patterns must become multi-user

Pi has no scopes/privacy/sync. So every borrowed pattern gets a **scope + privacy + sync** answer, reusing what's already built:

1. **Session tree → scoped + private.** Add `parentId` branching (borrow pi) **and** `scope`/`visibility`/`owner_user` to the session model (today `*.archhub-session.json` has none). Default **USER-private**; promote a branch to **PROJECT/FIRM** to share a trajectory — reuse the same `scope`+HLC machinery fragments already use (`storage.py`, `brain_replica.py`).
2. **Skills stay collective.** Pi's `~/.pi/skills` files → ArchHub already mints skills into the scoped brain; keep that. Borrow only the **authoring ergonomics** (Agent-Skills format, `/skill:name`).
3. **DB unify (ONE-SYSTEM).** Execute the unify `storage.py` already names: make `app/memory/graph.MemoryGraph` a **backend adapter of the brain**, kill the second store. No new store.
4. **Turn collective sync ON.** The fanout + HLC + per-scope replicas are **built** (`brain_replica.py`); the blocker is the **401 sign-in** (leaked-token). Fix sign-in → cross-device + firm/community convergence works.
5. **Privacy boundary is reused, not reinvented.** Refs-only + bare-cred rejection + per-user isolation already enforced in `brain_replica.py`; the session tree inherits the same contract.

---

## 4. Make it actually fire (it stalls today)
- **Composer turn doesn't complete a recall** → recall-chip stays "idle". Root: CLI-brain MCP race (claude_cli brain has 0 tools at `-p` turn). Fix: route composer turns to an **API model** (tools run server-side) OR pre-warm/persist the MCP. (`llm_router` provider choice for composer turns.)
- **Cloud sync 401** → no collective convergence. Fix the sign-in/token (the leaked `ah_test` token issue).

---

## 5. Sequence (smallest VISIBLE win first)
1. ✅ **Recall-chip in composer** — done (preview, CDP-verified). Surfaces the loop.
2. **Make the loop fire** — fix the turn recall so the chip lights live (CLI-brain).
3. **Session tree** — add `parentId` + `/tree` `/fork` (borrow pi). The branching visual steer.
4. **Scope the tree** — USER-private default; promote a branch to FIRM (ties tree into collective brain + privacy).
5. **DB unify + sync ON** — MemoryGraph→brain adapter (ONE-SYSTEM) + fix 401.
6. **Skill/extension ergonomics** — Agent-Skills + ExtensionAPI into the brain.

_Each slice: real, file-grounded, CDP-verified before "done" (DEFINITION-OF-SHIPPED). No new store, no new AgDR — builds on 0012/0021/0038/0044._
