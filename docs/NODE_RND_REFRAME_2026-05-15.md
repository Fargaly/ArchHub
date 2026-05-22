# Node R&D Reframe — Nodes as Memory Cells for an LLM

> Author: senior research lead, ArchHub · 2026-05-15.
> Supersedes the conceptual model in `docs/NODE_RND_2026-05-15.md`
> (which still stands as a survey of node-system *UX* — but its
> "ship-80-features" framing is now wrong).
> Companion reading (do not re-summarise): `docs/CANVAS_PLAN.md` §v1.4,
> `docs/NODE_LIBRARY_v2.md`, `app/workflows/graph.py:Node|Edge|PortType`,
> `app/workflows/runner.py:WorkflowRunner.pull`,
> `app/agents/composer_agent.py:TOOL_SCHEMA`,
> `app/bridge.py` lines 1700-1740 (`agent_step`).

## Executive verdict (read this first)

**The founder is right.** Treating each node as a unit of feature work — "add `l_select`, add `l_foreach_begin`, ship a marketplace" — was a category error. The prior R&D treated ArchHub as another node-based application competing with Dynamo and ComfyUI on surface area. Under the reframe, **ArchHub is not a node-based application — it is a structured-memory IDE for AEC agents.** The graph is the agent's working memory. Each node is a typed memory cell with a formula (the user's intent) and a last value (what the agent or executor produced). Wires aren't pipes — they declare which cells one cell *reads from*, just like `=A1+B1` in Excel. The 80-node library is now 90 % surplus: most of those nodes are scaffolding shortcuts an LLM can derive on the fly from typed inputs and a sentence of intent.

The single biggest architectural shift the reframe demands is **letting the agent mutate cell values mid-cook, not just at compose time** — i.e. an LLM-evaluator executor (`exec_llm_cell`) that any node can declare as its formula, and a runner that re-cooks downstream when the cell's value changes. This is the LangGraph `StateGraph` insight ported to AEC: the State is the graph, the reducer is the cook policy, the channels are the wires. Combined with Anthropic's [Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) packaging model (a Skill = `SKILL.md` + scaffold graph + scripts, *not* Python plugins), this collapses three roadmap items — Player runtime, marketplace, agent — into one mental model.

**ArchHub's new category: a *spatial agent memory IDE* — Excel for AI agents, scoped to AEC.** Not Dynamo (no parametric geometry primitive). Not LangGraph (no Python authoring required). Not ComfyUI (no pixel pipeline). Not Cursor (no file-as-unit). The cell-formula-reducer-reactive idiom of Excel/Observable, the typed-state-checkpoint idiom of LangGraph, the SKILL.md packaging idiom of Anthropic, all wrapped in a visual canvas whose host integrations (Revit, AutoCAD, 3ds Max, Speckle, Outlook…) supply the typed contents.

**Top-3 immediate adoptions** (pick all three; rest is downstream):

1. **One new node kind: `cell.intent`** — a typed memory cell whose value is computed by an LLM given (a) the user's intent string, (b) the cell's declared output type, (c) the upstream wires' last cached values. This is the founder's actual hypothesis made executable. Single executor in `app/workflows/nodes/llm.py`, ~150 LOC. Once it exists, 60 of the 80 current node types collapse into one cell with a different intent.
2. **A `cell` lens over the existing wire engine** — surface every node's `(intent, last_value, last_run_by, dependencies, format)` as a four-line cell strip on the node body, like Excel's formula bar + cell. Existing `Edge.value_preview` already carries the last-value bit. ~250 LOC of JSX + ~80 LOC bridge slots. This is the visible artefact that proves the model is right.
3. **Reframe Skills as `SKILL.md`-style scaffolds, not subgraphs** — adopt the Anthropic spec: each Skill = a directory with `SKILL.md` (YAML frontmatter: `name`, `description`, `when_to_use`) + a scaffold `graph.json` + optional `scripts/`. Stop shipping a Python-plugin sandbox plan. Distribute via git URLs. The agent picks the Skill by description; the canvas shows the scaffold. Skills become *instructions for the cell-evaluator agent*, not code. This is also how Anthropic, and now [OpenAI's Codex CLI](https://agentsdb.com/claude-skills-are-the-new-enterprise-agent-distribution), distribute.

The rest of this document defends those three. The 6-week backlog at the end is shorter than the prior plan — *eight* of the prior plan's items are now dead.

---

## 1. Survey — systems that already treat structured memory as a first-class user surface

For each: **(a)** the cell unit, **(b)** read/write API, **(c)** user edit path, **(d)** what ArchHub steals.

### 1.1 Spreadsheets — the existence proof

**Excel / Google Sheets.** (a) Cell = `(formula, last_value, format, dependencies, owner)`. (b) Engine re-runs the formula on dep edit. (c) Click → type formula → value updates everywhere. (d) **Steal the four layers verbatim**: ArchHub node renders formula (intent), last value (existing `Edge.value_preview`), format (output type), dependencies (wires). The killer pattern is *the cell IS the formula* — no separate "edit"/"view" modes. <https://support.microsoft.com/en-us/office/overview-of-formulas-in-excel-ecfdc708-9162-49e8-b993-c311f47ca173>.

**Observable / Marimo.** (a) Reactive named cell. (b) Runtime re-runs cells whose deps changed; lazy — unused cells never run; circular deps raise (<https://observablehq.com/@observablehq/how-observable-runs>, <https://docs.marimo.io/guides/editor_features/dataflow/>). (d) Steal *laziness over a named DAG* (`runner.run_all` already does this via sinks) + the **cell graph audit panel** — show the user which cells a focused cell reads and writes, on the right rail.

**Jupyter.** Cell = `(code, exec_count, output, kernel_state)`. **Anti-steal**: cells can re-run out of order, silently producing stale state. The whole reframe is *don't be Jupyter*.

### 1.2 LLM-agent graph frameworks

**LangGraph (the most directly relevant).** (a) "Memory cell" is the entire `State` — a TypedDict, e.g. `class State(TypedDict): messages: Annotated[list, add_messages]`. (b) Each node is `(state) → partial_state`. Partials merge via **reducers** declared as `Annotated[T, reducer_fn]`. Default reducer = `LastValue` (overwrite); `add_messages` appends with dedup (<https://reference.langchain.com/python/langgraph/graph/state/StateGraph>, <https://deepwiki.com/langchain-ai/langgraph/3.1-stategraph-api>). (c) `graph.update_state(thread_id, patch, checkpoint_id)` mutates state mid-run; **time-travel = pick any checkpoint, branch** (<https://www.baihezi.com/mirrors/langgraph/how-tos/time-travel/index.html>). (d) **Steal the reducer-as-cell-policy model.** Each ArchHub node declares: `overwrite | append | merge | accumulate`. Today the wire engine is overwrite-only. Reducers let an LLM cell *contribute to* a value, not just replace it. Also steal **threads + checkpoints**: every cook is a checkpoint; user rewinds and branches. The proposed `app/workflows/lineage.py` becomes the checkpoint store.

**Langflow / Flowise.** Nodes are whole LangChain objects → too coarse → users drop to Python. **Anti-steal**: ArchHub's typed cell with an `intent` string and `expected_type` is the *finer* primitive Langflow lacks.

**CrewAI / AutoGen / Agent Framework.** Memory recently unified into one `Memory` class with hierarchical scopes (`/project/alpha`, `/agent/researcher`); `remember()`/`recall()` blend semantic similarity + recency + importance (<https://docs.crewai.com/concepts/memory>). (d) **Steal hierarchical scope.** Add `firm/<slug>`, `project/<slug>`, `agent/<role>`, `node/<id>` scopes to ArchHub state. Solves "agent should know who Sarah is across sessions" without bloating every prompt.

**MemGPT / Letta.** **Memory blocks** = named in-context strips the agent edits via tools `core_memory_append`, `core_memory_replace`, `memory_insert`, `memory_replace`, `memory_rethink`; archival store via `archival_memory_insert/search` (<https://docs.letta.com/concepts/memgpt/>, <https://www.letta.com/blog/memory-blocks>). (d) **Steal `core_memory_replace` as the model for agent → graph mutations.** `bridge.agent_step` returns *cell edits* (set value / set intent / append) — a near-trivial rename of `set_node_param` in `composer_agent.py:TOOL_SCHEMA` with large consequences.

**Mem0.** Vector memory with `add`/`search`/`update` (<https://docs.mem0.ai/>). (d) Backing store for an `m_recall` cell whose value is "k most relevant prior cells for this intent."

**Microsoft Semantic Kernel / Agent Framework.** Planner LLM produces ordered `Plugin.function` steps over shared `KernelArguments` (<https://github.com/microsoft/semantic-kernel>). (d) **Steal "user inspects the plan."** Today `agent_step` shows chips per *isolated* tool call; reframe shows the *whole proposed sub-graph* before any cook.

### 1.3 Protocol-as-memory

**Anthropic MCP — tools vs resources.** Server exposes three primitives: **Tools** (executable callables, `tools/call`), **Resources** (readable URIs returning content via `resources/read`), **Prompts** (templates). The LLM never *executes* a resource — it reads it (<https://modelcontextprotocol.io/docs/concepts/architecture>). (d) **Steal the tool-vs-resource split for nodes.** `register_node_mcp` today treats every node as a tool. Under reframe: read-family (`r_walls`, `r_doors`) → MCP **resources**; action-family (`o_pdf`, `o_email`, `h_revit.create_dim`) → MCP **tools**. Two lines in `node_mcp.py`; agent reasoning gets safer (resources can't have side effects).

**Custom GPTs + Memory + Files.** Named memory slots auto-injected. **Steal** the "auto-injected when relevant" idea — the *graph* decides relevance: a cell is relevant if it sits upstream of the focused cell.

### 1.4 Code-edit-as-state agents

**Cursor, Claude Code, Replit Agent, Aider, Cline, Roo Code.** **The filesystem IS the memory.** Agent tool-uses `Read`/`Edit`/`Write`; user edits the same files. (d) ArchHub's session JSON is already filesystem-resident — add `QFileSystemWatcher` so an external edit auto-reloads the canvas (~80 LOC). Makes ArchHub interoperable with Cursor / Claude Code.

**GitHub Copilot Workspace.** Three artefacts: **Spec** (current vs desired) / **Plan** (per-file actions) / **Patch** (diff). Each is editable; lower layers re-derive (<https://devops.com/github-copilot-evolves-agent-mode-and-multi-model-support-transform-devops-workflows-2/>). (d) **Steal the three-tier split**: ArchHub = **Intent** (prose) / **Plan** (graph) / **Run** (cooked values). Today the canvas only persists the third; agent chips are a half-hearted second.

**Goose / Maestro / Devin.** Long-running task graphs with pause-edit-resume. (d) **Steal pause-and-resume on any cell** — `cell.ask` interrupt primitive.

### 1.5 Skill-library agents

**Voyager (Minecraft).** Agent grows its own **skill library** of executable code; picks skills by description (<https://voyager.minedojo.org/>, arXiv 2305.16291). (d) **Auto-save successful multi-cell plans as Skills.** When the agent + user produce a working wall schedule, `bridge.save_subgraph_as_skill` (line 1539) fires automatically. Skills are most valuable when the agent itself authored them.

**Anthropic Agent Skills (the most important import).** Each Skill = directory with `SKILL.md` containing YAML frontmatter (`name`, `description` ≤1024 chars including when-to-use) + optional `scripts/` and `examples/`. **Progressive disclosure**: metadata always in context (~100 tok/Skill); SKILL.md body loaded only when description matches user's request; scripts run via bash so code never enters context (<https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview>). OpenAI's Codex CLI adopted the same format as an open standard in Dec 2025 (<https://agentsdb.com/claude-skills-are-the-new-enterprise-agent-distribution>). (d) **Steal everything.** Replace `.archhub-skill.json` envelopes with `SKILL.md` + `graph.json` + `scripts/`. The Skill becomes *hybrid* — instructions for the agent + a starter graph for the canvas. Unifies "marketplace v1," "Skill versioning," and "Skill sandbox" into one already-solved problem.

### 1.6 Other relevant sources

**TouchDesigner with live camera, Houdini HDA spare-params.** Covered in prior R&D — under reframe, "promote internal slider" is what the *agent* does when generalising into a Skill, not a right-click feature.

**Replit Workspaces / Power Apps Copilot.** Same lesson: agent generates the artefact (Flow / workspace); user edits it; agent edits it back. The existing `agent_step` already moves that direction — reframe makes it primary.

**AirLLM** (<https://github.com/lyogavin/airllm>). Layer-by-layer inference: 70 B model split into ~80 transformer blocks loaded sequentially from disk to GPU. Specific verdict in §7. TL;DR: minutes-per-token on architect laptops; opt-in overnight mode only.

**Attention-vs-graph (Bahdanau).** Cells = KV cache slices the user can't see or edit. The graph wins when (i) context must persist across sessions, (ii) values must be inspectable, (iii) the user is non-technical. AEC users hit all three.

---

## 2. Reframed conceptual model

### What IS a node

A **memory cell** with these fields (extends `app/workflows/graph.py:Node`):

```jsonc
{
  "id": "walls_set",                       // identity
  "kind": "cell",                          // new: "cell" | "tool" | "resource"
  "intent": "all level-1 exterior walls",  // new: NL goal (formula)
  "expected_type": "selection.walls",      // new: typed output
  "reducer": "overwrite",                  // new: overwrite|append|merge|accumulate
  "scope": "session/<slug>",               // new: session|project|firm|agent
  "last_value": { ... },                   // existing: from runner.node_outputs
  "last_value_preview": "47 walls (Level 1)", // existing: Edge.value_preview
  "last_run_by": "agent:claude-sonnet-4.6",   // new: who ran it
  "last_run_at": "2026-05-15T12:34:00Z",      // new
  "last_run_cache_key": "sha256:...",         // existing
  "dependencies": ["selection_doc.id"],       // derived from upstream edges
  "format": { "render_as": "plan_thumbnail" } // new: hint to NodeRenderer
}
```

`kind=cell` is the *new* default. `kind=tool` is `o_pdf`-style action nodes (side-effects). `kind=resource` is `r_walls`-style readonly host queries. This three-way split tracks the MCP primitive split (<https://modelcontextprotocol.io/docs/concepts/architecture>) and lets the agent reason about which nodes are safe to call speculatively (resources) vs which need user confirmation (tools).

### What IS a wire

**Wires declare reads**, not flow. Excel `=A1+B1` is two read declarations — *this cell depends on A1 and B1*. ArchHub today already encodes this in `Edge.src_node` + `Edge.dst_port`, but the language around the canvas treats wires as pipes ("the wall set flows into the filter"). Reframe: a wire means "this destination cell *references* the source cell at this port." Three consequences:

1. **A wire's `state` (`runner.py:_emit`) doesn't need `flowing` semantics** — `idle | cached | stale | error` is enough, modelled on Excel cell states. We keep `flowing` for live-cook animation but it's UI, not data.
2. **Field selectors (`src_field` / `dst_field`) become Excel-style sub-references** — `walls_set.exterior` is the same idea as `=Sheet1!A1.exterior`.
3. **Reducer is now on the destination port, not the wire.** When two upstream cells point to the same input port (with `Port.multiple=True`), the destination's reducer decides how to merge — `overwrite` (use the most recently cooked), `append` (concat lists), `merge` (dict merge), `vote` (LLM picks). This is the LangGraph `Annotated[T, reducer]` pattern at port granularity.

### What IS the canvas

**The agent's working memory the user can edit.** Not a flowchart. Not a visual programming language. Specifically:

- The canvas is the *thread-state visualization* of a long-running agent conversation (the LangGraph `thread_id` lives in `session.id`).
- Each node renders as a *cell strip*: header (intent + scope) → output type pill → value preview (60 px Excel-style format-aware footer) → footer (last-run-by chip).
- Wires are the cell's `=SUM(A1:A10)` declarations rendered as bezier curves so non-technical users can see "this cell reads from those cells."
- The composer is the agent's hand on the canvas — typing intent creates a new cell, mutates an existing one, or pulls in a Skill.

### What IS the agent's role

**Both tool-caller and cell evaluator.** The agent has three jobs:

1. **Compose** — produce a graph mutation plan from intent (`bridge.agent_step` today). User reviews chips → applies → cells exist.
2. **Evaluate** — be the *executor* for `cell.intent` nodes whose formula is "follow this intent, use these upstream values, produce a value of this type." This is the new piece. Implemented as a registered executor in `app/workflows/nodes/llm.py`.
3. **Repair** — when a downstream cell fails, propose a fix to the upstream cell. The lineage trail (proposed in §6) gives the agent the "what changed" diff.

### What IS a Skill

A **directory** following the [Anthropic Agent Skills spec](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview):

```text
fargaly/wall-schedule/
├── SKILL.md           # YAML frontmatter (name, description), body =
│                      # the agent's playbook + when-to-use
├── graph.json         # The starter cell graph for the canvas
├── scripts/
│   └── verify.py      # Optional deterministic helpers
└── examples/
    └── input.json     # Sample inputs
```

`SKILL.md` body is *agent-readable* (Claude reads it via Bash at trigger time, [progressive disclosure](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)). `graph.json` is *canvas-readable* (a starter scaffold of cells the agent fills in). This unifies:

- The current `app/skills/library.py` JSON envelope (becomes `graph.json` + `SKILL.md`).
- The proposed "Skill versioning" (becomes Anthropic's `name@version` convention).
- The proposed marketplace (becomes any HTTPS-served git repo, like `.claude/skills/` discovery).

A Skill is *both* a frozen sub-canvas and an agent playbook — the founder's "bits of memory the AI utilizes" is precisely a Skill.

### What does "Run" mean

Three flavours, all are valid:

1. **Cook the dirty cells** (today's `runner.run_all`) — value engine, no LLM.
2. **Re-ask the cell-agent** (new) — for `cell.intent` nodes, calls the LLM with current upstream values. May be cached.
3. **Run a Skill** — instantiate the Skill's scaffold into the current session, let the agent fill blanks, then cook.

User-triggered (Run button) and auto-triggered (cell edit → dirty cascade → cook on idle). The cell-agent flavour gates on `prefer_local_llm` for cost.

---

## 3. Specific patterns the LLM-as-cell-evaluator model unlocks

| Pattern | Meaning for ArchHub | Implementation sketch |
|---|---|---|
| **Self-modifying graphs** | Cook executor returns `__graph_patch__`; runner applies with budget cap to prevent runaway. Mirrors LangGraph `Command(graph=PARENT, update=...)`. | `runner.pull` apply patch + `ctx.graph_patches_remaining=3`. |
| **Speculative cells** | Executor returns `candidates: [Y, Z, W]`; JSX renders chooser pill. Cursor "Apply / Discard / Alternative." | `executor → {value, candidates}` + JSX `CellStrip` chooser. |
| **Memoised prompts** | Identical intent + identical typed upstream + identical model = cached, no LLM hit. | One-line change to `runner._compute_cache_key` (include `intent`, `model`). |
| **CoT as graph topology** | Multi-step reasoning becomes a *graph of typed cells* (hypothesis / evidence / counter / decision) the user can see. | Decompose `i_think` into a `cell.intent` sub-graph. |
| **Tool-use as wire walking** | Agent picks the next tool by traversing wires by *type*. Typed ports already exist; surface the signal in the agent system prompt. | `composer_agent.system_prompt` enumerates downstream-by-type. |
| **Parameter scaffolding** | User fills 3 of 5 params; agent infers the rest from the cell's JSON schema. Ghost-text "AI will infer." | New `bridge.cell_infer_params(node_id)`. |
| **Visual debuggability** | Each cell = one inspectable LLM call. Click → prompt / inputs / response / tokens / cost / latency. Letta block-inspector model. | Extend `lineage.py` to per-cell LLM envelope; right-rail Cell Inspector. |
| **Pause / resume** | A `cell.ask` interrupts cook, awaits user, resumes. LangGraph `interrupt()` primitive. | New `cell.ask` node type; `runner` yields on flag; `bridge.resume_cell(value)`. |
| **Multi-agent specialisation** | `cell.config.preferred_model = "claude-opus" | "haiku" | "gemini" | "local-qwen"`. Vision agent on `i_vis`, reasoning on `i_think`, CAD on `h_revit`. | Router already supports per-call model selection. |
| **Time-travel** | Every cook → checkpoint. Pick any checkpoint and branch. LangGraph `update_state(checkpoint_id, patch)`. | Lineage.py = checkpoint store; right-rail "Run history" + "Fork from here." |

---

## 4. Implications for the existing 80-node library

The reframe is **ruthless**. Treat each node category:

| Category | Today | Under reframe | Verdict |
|---|---|---|---|
| `i_*` AI/intent | 8 nodes | All collapse to one `cell.intent` with different `expected_type` and `intent` strings | **REMOVE 7 of 8.** Keep `i_conv` (still needed for conversation as a typed cell). |
| `r_*` reads (walls/doors/rooms/views/sheets) | 10 nodes | All become MCP **resources** the cell-agent reads on demand from a single `read.host` cell whose intent is "fetch X from current host" | **REMOVE 8 of 10.** Keep `r_doc` (active document handle) and a generic `r_query` cell. The agent picks the right host API. |
| `f_*` filters | 7 nodes | A filter is just `cell.intent="exterior level-1 walls"` with upstream `r_walls`. The agent writes the predicate | **REMOVE 6 of 7.** Keep `f_pred` (user-written Python predicate, escape hatch). |
| `t_*` transforms (group/sort/count) | 8 nodes | One `cell.intent` per transform | **REMOVE 7 of 8.** Keep `t_group` because grouping changes output type non-trivially. |
| `a_*` annotate (dim/tag/mark) | 6 nodes | These are MCP **tools** (host side-effects) — keep | **KEEP all 6.** Promote to first-class tools. |
| `c_*` compose (sched/sheet/view) | 5 nodes | These are tools | **KEEP all 5.** |
| `l_*` logic (if/foreach/select/merge/throttle/loop/wait/finalize) | 10 nodes | Cells with reducers absorb most; keep iteration | **REMOVE 6 of 10.** Keep `l_foreach_begin/end` (Houdini block — still irreducible), `l_select` (router) — only because the agent picks differently with deterministic vs probabilistic dispatch. |
| `o_*` outputs (pdf/email/speckle/teams/notion) | 9 nodes | Tools — keep | **KEEP all 9.** |
| `h_*` host integrations (revit/acad/max/blender/rhino/photoshop…) | 18 hosts | Each becomes a tool *family* the agent can call | **KEEP all 18.** This is the moat. |
| `trg_*` triggers (manual/cron/webhook) | 4 nodes | Keep | **KEEP all 4.** |

**Result: 80 nodes → ~37 nodes.** The other 43 are *latent* — the agent generates them from a single `cell.intent` declaration. They don't need to ship; they only need to *exist on demand*.

**Promoted to "scaffolding primitives"** — the survivors split into two roles:
- **Resources** (read-only): the 10 host-query nodes, plus `r_doc`.
- **Tools** (side-effects): the 23 a_/c_/o_/h_ nodes.
- **Cells** (computation + memory): the new universal `cell.intent` + a handful of typed variants (`cell.conversation`, `cell.image`, `cell.list`).

**Added metadata on every cell** — what an LLM needs to evaluate it:
- `intent: str` (the formula)
- `expected_type: PortType` (the cell's output type — already exists, surface it harder)
- `accepted_input_shape: dict` (a JSON schema describing what upstream values the cell expects; agent uses this to wire correctly)
- `system_prompt_override: str` (per-cell override of the agent system prompt — like Letta's per-block instructions)

**The irreducible minimum.** If AI does the work, what nodes MUST exist?

1. `cell.intent` (universal evaluator)
2. `cell.conversation` (multi-turn LLM with `add_messages` reducer)
3. `r_doc` (active host document handle — the agent cannot guess this)
4. `o_publish` (universal output cell: publishes to pdf/email/speckle based on dst config)
5. 18 host *tool families* (revit, acad, max, …) registered as MCP tool servers — collapsed from per-action nodes
6. `l_foreach` (iteration is irreducible)
7. `l_select` (deterministic dispatch)
8. `trg_manual`, `trg_cron`, `trg_webhook`, `trg_filewatch` (triggers — irreducible)

**= 27 node types, max.** Everything else is generated by the agent into specific cell instances at design time, not registered at library time.

---

## 5. The Excel-cell test

Excel's killer pattern: every cell has 4 layers — **formula, last value, format, dependencies** — all editable, all visible, all caching transparently. Mapping to ArchHub:

| Excel layer | ArchHub equivalent today | Status |
|---|---|---|
| **Formula** | *missing* — the agent's intent is in `composer.history`, not on the node | **GAP** — add `Node.intent` field |
| **Last value** | `Edge.value_preview` (`graph.py:148`) — exists, surfaced only in hover tooltip | Partial — surface on node body (preview footer, already proposed in prior R&D §3.6 Shift 1) |
| **Format** | *missing* — no per-node format hint | **GAP** — add `Node.format = { render_as: "plan_thumb" | "table" | "json" | "text" | "chart" }` |
| **Dependencies** | `Edge.src_node` / `Edge.dst_node` — exists, rendered as wires | Match — Excel-grade |
| **Who set it** | *missing* — lineage is per-run, not per-cell | **GAP** — add `Node.last_run_by` + `Node.last_run_at` |

**What's missing under the reframe:** `intent` + `format` + `last_run_by`. Three string fields per Node. Schema migration is backward-compatible (default to `""`). All three exist as concepts elsewhere in the codebase but are scattered. Centralising them on `Node` is the schema move that proves the reframe.

---

## 6. Architectural recommendations

### 6.1 Minimum runtime change — `app/workflows/runner.py` + `graph.py`

- Add fields on `Node`: `intent`, `expected_type`, `format`, `reducer`, `last_run_by`, `last_run_at` (~30 LOC + back-compat migration).
- `_compute_cache_key` (line 377): include `node.intent` + `cfg.preferred_model`. ~1 LOC.
- `pull` (line 405): if executor returns `__graph_patch__`, apply via new `apply_graph_patch` with `ctx.graph_patches_remaining=3` budget. ~120 LOC.
- Executor contract broadens: may return `{value, value_preview, format_hint, by, candidates}`. Old raw-dict returns auto-wrap.
- **LOC**: ~180 runner, ~30 graph, ~50 tests.

### 6.2 Minimum UI change — `app/web_ui/studio-lm.jsx`

- New `CellStrip` component (80 px) on the `NodeRenderer` body (~line 1990): row 1 intent text (gray-italic if empty, click → mini composer popover), row 2 type pill + format-aware preview, row 3 "✦ claude-opus · 2 min ago" chip from `last_run_by`.
- `previewRendererForType(type, value, format_hint)` dispatch — walls/doors → SVG bbox plan, list → table, image → thumbnail.
- Right-rail "Cell Inspector" tab: prompt / upstream values / response / tokens / latency / candidates.
- **LOC**: ~280 JSX + ~80 bridge slots (`set_node_intent`, `get_cell_lineage`, `regenerate_cell`).

### 6.3 Minimum agent change — `app/agents/composer_agent.py`

Rewrite `TOOL_SCHEMA` (today's 7 tools alias to new names; add 4):

| Tool | Purpose | Replaces |
|---|---|---|
| `propose_cell` | Spawn cell with intent + expected_type | `spawn_node` |
| `read_cell` | Read value + lineage (the "agent reads memory") | NEW |
| `set_cell_intent` | Edit a cell's intent string | NEW |
| `set_cell_value` | Lock in a computed value | `set_node_param` (broadened) |
| `cook_cell` | Re-evaluate cell | `run_node` |
| `wire_cells` | Declare A reads from B | `add_wire` |
| `install_skill` | Apply a SKILL.md scaffold to the canvas | NEW |
| `find_skill` | Match by description against intent | NEW |

`system_prompt` becomes: "You are the cell evaluator for the ArchHub canvas — the architect's working memory. Cells you read are typed; cells you write must declare expected_type. Prefer cached values."

**LOC**: ~150. `bridge.agent_step` (line 1705) signature unchanged; action names update.

### 6.4 The new node type — one universal executor

```python
# app/workflows/nodes/llm.py
@registry.register("cell.intent")
def exec_cell_intent(cfg, inputs, ctx):
    intent = cfg.get("intent", "")
    expected_type = cfg.get("expected_type", "any")
    model = cfg.get("preferred_model", "auto")
    sys = build_cell_system_prompt(expected_type, intent)
    user = render_inputs_as_context(inputs)
    resp = ctx.router.complete(
        history=[{"role": "system_override", "content": sys},
                 {"role": "user", "content": user}],
        model=model)
    value = parse_typed(resp.text, expected_type)
    return {"value": value,
            "value_preview": preview_for_type(value, expected_type),
            "by": f"agent:{model}"}
```

Plus typed wrappers — `cell.conversation`, `cell.list`, `cell.image` — that lock the output format. ~200 LOC total in `llm.py`.

---

## 7. AirLLM specifically

Founder asked: relevant?

**What it is.** Layer-wise model loading: a 70 B model is split into ~80 transformer blocks, each loaded from disk to GPU, forward-passed, swapped out, next block loaded. The bottleneck moves from VRAM to disk I/O. Supports 70 B on 4 GB VRAM, 405 B on 8 GB VRAM, CPU mode. Standard HuggingFace `AutoModel.from_pretrained()` API. <https://github.com/lyogavin/airllm>.

**When it actually beats llama.cpp / Ollama.** It doesn't, for chat use. Architect-laptop reality: a single 70 B token from disk needs ~80 layer-loads. On a fast NVMe (3 GB/s read), 70 B weights ≈ 140 GB total (full precision) means *minutes per token*. Even quantised 4-bit (35 GB) is ~12 seconds per token. Ollama with the same 4-bit on 16 GB unified memory delivers 10-30 tokens/sec on Apple Silicon, 2-8 on a dGPU laptop. AirLLM only wins in one scenario: **batch inference of a few-token-budget cell-evaluator where you cannot rent cloud compute and quality matters more than latency.** For ArchHub specifically — agent cell cook on a Tuesday afternoon — that scenario is real but narrow.

**Realistic perf on the architect laptop.** 4 GB GPU + 16 GB RAM + NVMe: a 70 B inference will run, but a single 200-token response will take 30-120 seconds. Unusable for inline chat; usable for *overnight Skill cook* where the user kicks off "schedule all 14 buildings tonight" and walks away.

**Integration cost.** AirLLM exposes a HuggingFace-compatible `AutoModel`. The existing `app/local_llm_detector.py` is an Ollama / LM Studio detector. Wrapping AirLLM is ~200 LOC: detector + adapter that conforms to the existing `LocalProvider` interface in `app/llm_router.py`. Half-day to a day if `pip install airllm` works cleanly on Windows (it does on CUDA setups; CPU on Windows is supported per <https://github.com/lyogavin/airllm/releases/tag/v2.10.1>). Last release Aug 2024 — maintained, not stale, but slowing.

**Verdict.** *Wait.* Make a 2-day spike in week 4 of the backlog to validate batch-mode token-rate on a typical architect laptop. Ship as **opt-in "offline mode"** for overnight Skill cooks if the spike beats 5 tok/s; otherwise shelve. Do NOT route inline cell-evaluator cook through it — latency murders the Excel-like reactive UX the reframe demands.

---

## 8. Marketplace question — revisited

The prior R&D said "install-from-URL only." The cloud plan said "marketplace v1 in W7-9." Under the reframe, *both* are obsolete in their original form.

**The right model: Skills are Anthropic Agent Skills directories distributed via git URLs.**

- Skill = directory (`SKILL.md` + `graph.json` + optional `scripts/`).
- Distribution = any HTTPS git URL. `bridge.install_skill_from_url(url)` does `git clone --depth 1` into `%LOCALAPPDATA%\ArchHub\skills\<namespace>\<name>`.
- Discovery = same as Claude Code: walk `<project>/.archhub/skills/` and `%LOCALAPPDATA%\ArchHub\skills\` at every session open.
- The cell-evaluator agent sees only the YAML frontmatter (≤100 tokens/Skill) until the user's intent matches the `description`, then reads `SKILL.md`. Progressive disclosure — pasted from Anthropic's spec.
- The canvas reads `graph.json` to scaffold the cells.
- **Skills are instructions for the agent, not Python code.** The graph is JSON; the `scripts/` directory is optional and only invoked deterministically (e.g. a CSV validator).
- Sandboxing collapses: when the unit of distribution is "instructions for an LLM and a JSON graph," the security model is *trust the source*. The Python execution path is the same one any registered host node uses — the registry, not the Skill. A malicious Skill can only ask the agent to do harmful things, which the user reviews via the chips UI.
- For the small subset of Skills that ship a Python helper (`scripts/verify.py`), require a one-time "Allow scripts" approval per Skill source, modelled on Claude Code's plugin permission model.

**What dies:**
- The "Skills cloud sync" plan (the cloud doesn't host code — git does).
- The Python-plugin sandbox plan (no plugins under reframe).
- The Houdini-style versioning syntax (`namespace::name::1.0`) — adopt git tags instead.

**What survives:**
- The `app/skills/library.py` matcher — it now reads `SKILL.md` descriptions and ranks against user intent.
- The "share Skill" UX — becomes "push to a git repo."

---

## 9. Six-week R&D backlog UNDER the reframe

| Wk | Theme | Files | Ship gate |
|---|---|---|---|
| **1** | **Cell schema + `cell.intent` executor.** Add `Node.intent/expected_type/format/reducer/last_run_by/last_run_at`. Include `intent` + `preferred_model` in cache key. New `exec_cell_intent` + three typed variants. | `graph.py` (~30), `runner.py` (~5), `nodes/llm.py` (~250), `bridge.py` (~80), tests (~150) | A user types intent into one cell, hits Run, sees a typed value cooked by the LLM. |
| **2** | **Cell strip UI + Excel-style previews.** `CellStrip` component, type-dispatched preview renderers, intent click → mini composer popover. | `studio-lm.jsx` (~550) | Every node renders an Excel-like cell strip — *this is the visible proof of the reframe*. |
| **3** | **Tools schema + agent reframe.** Rewrite `TOOL_SCHEMA` with `propose_cell/read_cell/set_cell_intent/set_cell_value/cook_cell/wire_cells/install_skill/find_skill`. Old tools aliased. Right-rail Cell Inspector. | `composer_agent.py` (~150), `bridge.py` (~170), `studio-lm.jsx` (~200) | "Fill in the schedule formula for me" in the composer regenerates the targeted cell; Cell Inspector shows the LLM trace. |
| **4** | **SKILL.md adoption + AirLLM spike.** `app/skills/library.py` reads directory `SKILL.md`+`graph.json`+`scripts/`; old envelopes auto-convert. `install_skill_from_url(git_url)`. Matcher ranks by description vs intent. 2-day AirLLM spike → ship if ≥5 tok/s, else shelve. | `skills/library.py` (~180), `skills/matcher.py` (~80), `bridge.py` (~120), `local_llm_detector.py` (~200) | `bridge.install_skill_from_url("https://github.com/…/wall-schedule")` clones, validates, scaffolds the canvas. |
| **5** | **Lineage = checkpoints = time-travel.** `LineageRecorder` writes JSONL per cook; right-rail "Run history" timeline; "Fork from here" → new session at past cell values. | `workflows/lineage.py` (~180), `bridge.py` (~120), `studio-lm.jsx` (~200) | User runs a Skill Mon, again Tue, forks from Mon's run and diffs Tue's cell edits. |
| **6** | **Reducers + interrupts + speculative + library prune.** Per-port reducer (`overwrite/append/merge/accumulate/vote`). `cell.ask` interrupt primitive. Speculative `candidates` chooser pills. Delete 43 surplus library entries; legacy auto-rewrites to `cell.intent` on session load. | `runner.py` (~120), `nodes/control.py` (~150), `studio-lm.jsx` (~120), library + migration (~200) | Power user pauses a 7-cell Skill, edits, resumes; library palette shows ~30 nodes not 80. |

**Eight items from prior plans die under the reframe:**

- Player runtime (cell strip + agent makes the canvas non-technical-friendly; revisit only if data demands canvas-less mode)
- Houdini's full flag matrix (kept just `bypass`; reducers + interrupt + frozen do the rest)
- Marketplace v1 (replaced by git URLs)
- Skill sandbox (instructions not code)
- Variadic merge / switch / debug nodes (agent generates as cells)
- Skill versioning / promote-param / install-URL trio (collapsed into SKILL.md adoption in W4)
- State-graph overlay (Unity Bolt) (subsumed by reducers + scopes)
- Geometry Nodes "fields" (agent + foreach handles per-element)

---

## 10. Closing verdict

**Is the founder right?** Yes — with one caveat. The reframe is correct that nodes-as-memory-cells unlocks two orders of magnitude more value than nodes-as-features. The caveat: **action nodes still need to exist as separate, non-cell entities** because they have side effects (publishing PDFs, sending emails, mutating Revit). Treating those as "memory" muddles undo and the user-confirm model. The right split is **resources (read) → cells (compute) → tools (act)**, three kinds, one canvas. This is exactly the [MCP primitive split](https://modelcontextprotocol.io/docs/concepts/architecture). The founder's intuition is also right that 80 nodes is too many — closer to 27 is correct once cells absorb the latent surface.

**The single biggest architectural shift.** Introduce `cell.intent` as a registered executor in `app/workflows/nodes/llm.py` and add `intent` + `expected_type` + `last_run_by` to `Node`. Three field additions. One new executor. The rest of the reframe follows from those four lines of schema.

**The category ArchHub belongs in now.** Not Dynamo (no parametric geometry primitive). Not LangGraph (no Python authoring required for end users). Not ComfyUI (no media pipeline). Not Cursor (no file-as-unit). Not Excel (no AEC host integration). ArchHub is the *first* **spatial agent memory IDE** — a structured-memory IDE where each cell can be evaluated by an LLM, scoped to AEC professionals, host-integrated with Revit/AutoCAD/Speckle/Rhino/3ds Max. Its closest peers are *Observable for data viz* and *Letta for stateful agents*; its differentiator is the 18-host moat and the architect-grade visual canvas. Pitch line: **"Excel for AI agents, with Revit on the other side."**

---

### Where the founder may be slightly wrong

One pushback: the framing "nodes are just for ease of action acting as BITS OF MEMORY" is *almost* right, but conflates two distinct roles. **Memory cells (cells)** and **action invocations (tools)** are different beasts in every system that has thought about this — LangGraph separates `nodes` (state writers) from external tool calls; MCP separates `resources` from `tools`; Letta separates `memory_blocks` from `tools`; Excel separates `cells` from VBA macros. The founder's quote is correct for the *compute* half of the canvas, but the side-effect half — `o_email`, `h_revit.create_dim`, `o_speckle.commit` — must remain distinct so that *running an action node is a deliberate, undo-tracked event*. The reframe should be: **cells are memory the AI utilises; tools are side effects the AI proposes and the user confirms; resources are reads the AI does freely.** Three kinds. The 80-node library collapses to ~27 because most of the 80 are cells in disguise — but the action ones (host integrations, outputs, annotates) are not cells and shouldn't be merged.

---

*End of reframe report. Author: senior research lead, ArchHub · 2026-05-15.*
*Sources cited in body; recap below.*

**Key sources:**
- LangGraph StateGraph + reducers — <https://reference.langchain.com/python/langgraph/graph/state/StateGraph>, <https://deepwiki.com/langchain-ai/langgraph/3.1-stategraph-api>
- LangGraph time-travel — <https://www.baihezi.com/mirrors/langgraph/how-tos/time-travel/index.html>
- Anthropic Agent Skills (the primary import for ArchHub Skills) — <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview>, <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- MCP architecture / tools-vs-resources — <https://modelcontextprotocol.io/docs/concepts/architecture>
- Letta / MemGPT memory blocks — <https://docs.letta.com/concepts/memgpt/>, <https://www.letta.com/blog/memory-blocks>, <https://docs.letta.com/guides/agents/memory/>
- CrewAI unified memory + hierarchical scopes — <https://docs.crewai.com/concepts/memory>
- Observable reactive cells — <https://observablehq.com/@observablehq/how-observable-runs>, <https://github.com/observablehq/runtime>
- Marimo dataflow Python — <https://docs.marimo.io/guides/editor_features/dataflow/>, <https://marimo.io/blog/dataflow>
- Voyager skill library — <https://voyager.minedojo.org/>, arXiv 2305.16291
- Copilot Workspace spec/plan/patch — <https://devops.com/github-copilot-evolves-agent-mode-and-multi-model-support-transform-devops-workflows-2/>, <https://github.com/newsroom/press-releases/agent-mode>
- AirLLM — <https://github.com/lyogavin/airllm>
- OpenAI Codex CLI Skills adoption — <https://agentsdb.com/claude-skills-are-the-new-enterprise-agent-distribution>
- Microsoft Semantic Kernel / Agent Framework — <https://github.com/microsoft/semantic-kernel>
- Anthropic Agent Skills engineering deep-dive — <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
