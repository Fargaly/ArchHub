# AI Reasoning Visualization — The Graph IS the Reasoning, Rendered

> Author: senior research lead, dataflow visualization & AI-system
> observability · ArchHub · 2026-05-15.
> Companion reading (digested, not re-summarised): `docs/CANVAS_PLAN.md`
> §v1.4, `docs/NODE_RND_REFRAME_2026-05-15.md` (cells-as-memory),
> `docs/NODE_INTERACTION_UX_PRINCIPLES_2026-05-15.md` (HCI tenets),
> `docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md` §4.6 (Speckle WIRE map).
> Code grounded in: `app/web_ui/studio-lm.jsx` (5659 LOC),
> `app/bridge.py` (2246 LOC), `app/workflows/runner.py`,
> `app/agents/composer_agent.py`.

## Executive summary (read this first)

1. ArchHub's agent today reasons in a **text sidebar** (`chat_reasoning`
   → `m.reasoning[]` array in a Conversation node). That is a chat log
   bolted onto a canvas — it throws away the canvas the moment the AI
   does the interesting part. The founder is right: this is "stupid and
   limiting."
2. The fix: **the graph IS the agent's reasoning, rendered live.** When
   the agent works, the user does not read — they *watch*: nodes
   activate, wires carry a visible pulse, branches resolve, values
   propagate. Every step is an inspectable, reversible canvas event.
3. This is not a metaphor. ComfyUI, n8n, NiFi, TouchDesigner, and
   LangGraph already render computation-in-flight; ArchHub must render
   *reasoning*-in-flight, which is the same problem one abstraction
   layer up.
4. **Transparency = control.** Seeing every step unlocks the seven
   controls a debugger gives a programmer — Watch, Pause, Step, Inspect,
   Intervene, Rewind, Branch. None of these are possible against a
   text log. All are possible against a live graph.
5. The hard constraint: this must not lag. ArchHub's `bumpGraph()` full
   re-render is the wrong primitive for per-node pulses. §5 specifies a
   separate animation layer driven by direct DOM class toggles, never
   React state.

**Top 3 to build first:**
1. **`node_state_changed` signal + per-node CSS-class subscription**
   (§8) — the runner already emits wire states; add the node-level
   twin and let the canvas paint state *without* a React re-render.
   Everything else is downstream of this.
2. **The agent-cursor / focus spotlight** (§2, §6) — one visible
   "the AI is here" marker that travels the graph. It is the single
   highest-signal, lowest-cost expression of "I see what is happening."
3. **`agent_focus_changed` from `composer_agent.py`** (§8) — the agent
   emits which node it is reasoning about before it acts, so the
   spotlight and the live highlight have something to follow.

---

## 1. Reference research — systems that visualize computation as it happens

For each: (a) the visual mechanism, (b) the state it encodes, (c) how
the user interacts with it, (d) what ArchHub steals.

### 1.1 ComfyUI — the execution sweep

(a) ComfyUI renders a node graph for diffusion pipelines. During a run,
the node currently executing gets a **bright green border outline**;
each node shows a **per-node progress bar** for multi-step work (e.g. a
sampler's denoise steps); a **queue** holds pending prompts. Execution
visibly *sweeps* — the green outline jumps node to node in topological
order as each completes. (b) It encodes: which node is live, how far
through that node's internal work, and how many runs are stacked.
(c) The user interacts by queuing more prompts (they stack), or hitting
"Interrupt." There is no step or inspect — it is watch-only.
(d) **ArchHub steals the green-outline-on-the-active-node and the
queue.** The sweep is the canonical "computation moving through a
graph" idiom and ArchHub's agent loop is literally a sweep. Source:
ComfyUI execution model, <https://github.com/comfyanonymous/ComfyUI>;
the `PromptExecutor` walks the graph and emits `executing` /
`progress` / `executed` messages over a WebSocket — *the same
event shape ArchHub's bridge already has* (`workflow_started`,
`wire_state_changed`, `workflow_done`). ComfyUI's lesson: the
animation is **server-pushed events**, the client only paints. Do not
compute "what's live" on the client.

### 1.2 n8n — post-run state + pinned data on connections

(a) n8n is a workflow automation tool. After a run, each node turns
**green (success) or red (error)**; each node shows an **item count**
("4 items"); the **data is pinned to each connection** — click a
connection and see the JSON that flowed; the **Executions** tab is a
replay list of every past run. (b) It encodes per-node success/failure,
throughput (item counts), and the actual payload on every edge.
(c) The user clicks any node post-run to open its input/output panels;
the Executions list lets them re-open any historical run and inspect
it frozen. (d) **ArchHub steals the item count on the node and the
"data pinned to the connection."** ArchHub's `Edge.value_preview`
(`runner.py:_emit`, `repr(value)[:200]`) is exactly n8n's pinned
connection data but is currently hover-only — it must move onto the
wire as a persistent badge. Steal also the **Executions replay** — it
is §4's Rewind. Source: <https://docs.n8n.io/workflows/executions/>.

### 1.3 Node-RED — the status dot

(a) Node-RED wires IoT/message flows. Each node carries a small
**status dot + label underneath it** — a green dot "connected", a blue
dot "47 msgs", a red ring "error". A **Debug sidebar** prints messages
as they pass a debug node. Messages do not animate along wires; the
status text is the signal. (b) It encodes a node's *standing state*
(connected / count / error) compactly, in a fixed spot, without
expanding the node. (c) The user reads the dot passively; drops debug
nodes to inspect a specific wire. (d) **ArchHub steals the
status-dot-under-the-node grammar** for a non-intrusive node-state
indicator that does not require growing the node body — critical for
the founder's "heavy and not smooth" complaint. Source:
<https://nodered.org/docs/creating-nodes/status>.

### 1.4 Apache NiFi — flowfiles moving, queue depth, back-pressure

(a) NiFi is a dataflow platform. Its canvas shows **flowfiles visibly
queued on each connection** with a live **count + byte size**; when a
downstream processor is slow, the connection turns **red for
back-pressure**; a separate **data provenance graph** shows the full
lineage of any single flowfile — every processor it touched, every
transform, with timestamps. (b) It encodes queue depth, throughput,
back-pressure, and complete per-datum lineage. (c) The user
right-clicks any flowfile → "View provenance" → sees a node-link
diagram of that datum's whole journey, and can **replay** it.
(d) **ArchHub steals two things: (1) back-pressure color** — when a
node is waiting on a slow upstream (a host broker, an LLM call), the
incident wire should signal "stalled, not dead"; **(2) the provenance
graph as the model for the reasoning trace** — NiFi proves a
per-datum lineage *is itself a readable graph*. That is §3's core
argument. Source: <https://nifi.apache.org/docs.html>, "Data
Provenance."

### 1.5 TouchDesigner — the cook indicator, live at 60fps

(a) TouchDesigner is a real-time visual programming environment. Every
operator ("OP") has a **cook indicator**; data is *alive* — the network
recomputes every frame at 60fps; wires can show a **pulse**; the
bottom-right of each OP shows cook time in microseconds. (b) It encodes
"is this recomputing right now" and "how expensive is it" continuously.
(c) The user watches; can pin a value; can drop a "perform" monitor.
(d) **ArchHub steals the cook-time-on-the-node** (so the architect sees
which reasoning step is slow) but **explicitly rejects the 60fps
continuous cook** — ArchHub's reasoning steps are discrete LLM calls
seconds apart, not a per-frame dataflow. The lesson kept: a cook
indicator must be *cheap to paint* because TouchDesigner paints it 60×
a second. Source: <https://docs.derivative.ca/Cook>.

### 1.6 Houdini — cook flags, dependency highlighting, the geometry spreadsheet

(a) Houdini is a procedural 3D tool. Nodes carry **flags** (display,
render, bypass, template); the **cook** is lazy and dirty-tracked
(ArchHub's `runner.py` is explicitly modelled on it); selecting a node
**highlights its dependency cone** — upstream contributors light one
way, downstream consumers another; the **geometry spreadsheet** shows
the full tabular detail of whatever the selected node produced.
(b) It encodes the dependency topology and the exact intermediate
data. (c) The user clicks a node → instantly sees the data and the
dependency highlight; toggles flags to change what cooks.
(d) **ArchHub steals dependency-cone highlighting** — when the agent
focuses a node, the canvas should dim everything except that node's
upstream-it-reads and downstream-it-affects (ArchHub's `connectedIds`
set at `studio-lm.jsx:3053` is a one-hop version of this; extend to
the full transitive cone). Steal also the **geometry-spreadsheet → the
Inspect panel** (§4). Source: <https://www.sidefx.com/docs/houdini/>.

### 1.7 LangGraph / LangSmith — trace view, current-node highlight, time-travel

(a) LangGraph builds stateful agent graphs; LangSmith is its
observability layer. The **trace view** renders the agent run as a
tree/graph with the **currently-executing node highlighted**; you can
**step through** a run; **checkpoints** let you "time-travel" — pick
any prior state and resume or branch from it (`graph.update_state(
thread_id, patch, checkpoint_id)`). (b) It encodes the agent's
execution path, every intermediate state, and a persistent timeline of
checkpoints. (c) The user steps node by node, inspects state at each,
rewinds to a checkpoint, edits the state, and resumes — the agent
continues from the corrected state. (d) **This is the single most
important steal in the document.** LangGraph proves that an agent's
reasoning *is* a graph with a checkpointed timeline, and that
time-travel + state-edit-and-resume is a shipping, production feature —
not research. ArchHub's §4 (Pause/Step/Inspect/Intervene/Rewind/Branch)
is LangGraph's interaction model ported onto a visual canvas the
architect already sees. Sources:
<https://langchain-ai.github.io/langgraph/concepts/time-travel/>,
<https://langchain-ai.github.io/langgraph/concepts/persistence/>,
<https://docs.smith.langchain.com/observability>.

### 1.8 LangFlow / Flowise — the playground run animation

(a) Both are visual LLM-app builders. On "Run" in the playground, the
graph **animates the active component** with a glow/pulse and a
spinner, walking the chain. (b) It encodes which component is live.
(c) Watch-only; the playground is a chat panel beside the graph.
(d) **ArchHub steals the confirmation that a glow-walks-the-chain
animation reads as "the AI is working here"** to non-technical users —
LangFlow's audience is exactly ArchHub's (people who will not read a
trace JSON). But ArchHub goes further: LangFlow's graph is *authored*
then *run*; ArchHub's graph is *authored by the agent as it reasons*.
Source: <https://docs.langflow.org/>.

### 1.9 Observable / Marimo — reactive cells lighting up

(a) Observable and Marimo are reactive notebooks. Editing a cell
causes **every dependent cell to recompute**, and the recomputing
cells show a visible **running state** — a subtle highlight ripples
through the dependency DAG. Marimo draws an explicit **dataflow graph**
of cell dependencies. (b) It encodes the propagation of a change
through a dependency graph. (c) The user edits one cell and *watches
the ripple*; Marimo lets you view the DAG directly. (d) **ArchHub
steals the ripple** — when the architect (or the agent) changes one
cell's value, the downstream dirty-cascade (`runner.mark_dirty`,
which already exists and emits `stale` on every incident edge) should
*visibly propagate* node by node, not snap. The propagation **is** the
reasoning made visible. Sources:
<https://observablehq.com/@observablehq/how-observable-runs>,
<https://docs.marimo.io/guides/reactivity/>.

### 1.10 Excel — formula tracing arrows + step-through evaluation

(a) Excel's **Trace Precedents / Trace Dependents** draws blue arrows
from a cell to the cells it reads and the cells that read it; a
**"Calculating…"** indicator shows in the status bar; **Evaluate
Formula** (a dialog) lets you **step through a formula one operation
at a time**, watching each sub-expression resolve to a value.
(b) It encodes the dependency graph of a single cell and the
*intermediate evaluation state* of one formula. (c) The user clicks
"Evaluate" repeatedly and watches `=A1+B1*C1` collapse step by step:
`=5+B1*C1` → `=5+3*C1` → `=5+3*2` → `=11`. (d) **ArchHub steals
Evaluate-Formula directly as the model for §4's Step.** Excel proves
ordinary non-technical users *want and use* a step-through-the-
computation control. ArchHub's "step the agent one reasoning step"
is Evaluate-Formula at the graph level. Trace arrows = the dependency
cone (§1.6). Source:
<https://support.microsoft.com/en-us/office/display-the-relationships-between-formulas-and-cells-a59bef2b-3701-46bf-8ff1-d3518771d507>.

### 1.11 Debuggers — breakpoints, step-into/over, call stack, watch, current-line

(a) VS Code and Chrome DevTools debuggers: a **breakpoint** (red dot)
halts execution at a line; the **current line is highlighted**;
**step-into / step-over / step-out** advance execution at chosen
granularity; the **call stack** panel shows the nested frames; **watch
expressions** show named values updating live; **variables** panel
shows local scope. (b) It encodes the exact execution position, the
nesting of calls, and the live value of any expression. (c) The user
sets a breakpoint, runs, hits it, inspects everything frozen, edits a
variable in the Variables panel, then steps or continues — execution
proceeds *with the edited value*. (d) **ArchHub steals the entire
debugger interaction model.** A breakpoint on a node = "freeze the
agent when it reaches this node." The current-line highlight = the
agent-cursor. Step-over/into = step one reasoning node / descend into a
sub-reasoning graph. Watch = pin a node's value to a persistent panel.
Edit-a-variable-and-continue = §4's Intervene. The debugger is a
60-year-proven UI for "watch a computation and control it" — ArchHub's
job is to make the *graph* the debugger surface. Sources:
<https://code.visualstudio.com/docs/editor/debugging>,
<https://developer.chrome.com/docs/devtools/javascript>.

### 1.12 Chrome DevTools Performance panel — the flame chart

(a) The Performance panel records a timeline and renders a **flame
chart** — nested horizontal bars where width = duration and vertical
nesting = call depth, laid against a time axis. (b) It encodes *time*
as the primary axis — what ran, for how long, nested in what.
(c) The user scrubs the timeline, zooms into a slow span, clicks a bar
to see detail. (d) **ArchHub steals the flame chart as the shape of the
reasoning timeline view** — a secondary "timeline" rail (not the
canvas) where each reasoning step is a bar; this is how a 200-step
reasoning chain (§9's hard problem) stays readable when it is too big
to be a canvas. Source:
<https://developer.chrome.com/docs/devtools/performance>.

### 1.13 Cursor / Claude Code / Copilot agent UIs — plan, steps, diff-before-apply

(a) These coding agents show: a **plan / todo list** the agent will
follow; **per-step status** as it works (a tool call, a file read);
critically, a **diff preview before apply** — the change is shown
red/green and the user accepts or rejects per-hunk before anything is
written. (b) It encodes intent (the plan), progress (the steps), and
the *proposed but not-yet-committed* mutation (the diff). (c) The user
reviews the plan, watches steps stream, and accepts/rejects the diff.
(d) **ArchHub steals diff-before-apply** — it already half-exists as
the agent "chips" (`studio-lm.jsx:4651`, the `step.actions` dispatch).
The steal is to make the chips a **ghosted preview subgraph** (§2.6):
the agent's planned nodes/wires appear on the canvas *dimmed and
dashed*, and the architect accepts them into solidity. Source:
Cursor/Claude Code agent UX, <https://docs.cursor.com/>.

### 1.14 Glamorous Toolkit / Smalltalk live inspectors

(a) Glamorous Toolkit (a "moldable development" environment) and
classic Smalltalk inspectors let you **open any live object** and see
its state, with **custom per-object views** — a graph object renders
as a graph, a matrix as a grid. The object is live; the inspector
updates as the object changes. (b) It encodes arbitrary runtime state
with a representation chosen *per data type*. (c) The user clicks into
any object, drills arbitrarily deep, all live. (d) **ArchHub steals
the per-type custom inspector** — a node holding walls inspects as an
SVG plan bbox, a node holding a list as a table, a node holding a
reasoning step as prose. This is the reframe doc's
`previewRendererForType` made into the Inspect panel. Source:
<https://gtoolkit.com/>.

### 1.15 Bret Victor — making time and state visible

(a) "Inventing on Principle" (CUSEC 2012) and "Learnable Programming"
(2012) argue a creator must **see the effect of their work
immediately**, and that **time and state must be made visible** —
Victor's canonical demo scrubs a timeline and the program's entire
state history is laid out spatially, not hidden in a variable.
(b) It encodes the *history* of a computation as a visible, navigable
artifact. (c) The user scrubs time and sees state at every instant.
(d) **ArchHub steals the principle that the agent's reasoning history
must be a visible, scrubbable artifact, not an ephemeral stream.** The
reasoning that scrolled past in a chat log is gone; reasoning rendered
as graph topology + a checkpoint timeline is *there*, forever,
inspectable. This is the philosophical spine of the whole document.
Source: <https://worrydream.com/LearnableProgramming/>,
<https://worrydream.com/InventingOnPrinciple/>.

### 1.16 Algorithm visualizers + neural-net activation maps

(a) Sorting visualizers animate comparisons and swaps; neural-network
visualizers (e.g. the TensorFlow Playground) light up neurons and
edges by activation magnitude — "computation as light moving through
circuits." (b) They encode the *flow of activity* through a fixed
structure. (c) Watch-only, usually with a speed slider. (d) **ArchHub
steals the "light moving through circuits" idiom for the wire pulse**
(§6) and the **speed slider** — the architect controls how fast the
reasoning sweep animates (and can set it to 0 = step mode). Source:
TensorFlow Playground, <https://playground.tensorflow.org/>.

### 1.17 Synthesis — the seven mechanisms ArchHub assembles

| Mechanism | Best source | ArchHub use |
|---|---|---|
| Active-node outline + sweep | ComfyUI | The agent-focus highlight |
| Status dot under node | Node-RED | Cheap node-state indicator |
| Data pinned on the wire | n8n / NiFi | `value_preview` badge on the bezier |
| Back-pressure color | NiFi | "Stalled on slow upstream" wire state |
| Dependency-cone highlight | Houdini / Excel trace | Dim all but the focused node's cone |
| Step-through evaluation | Excel Evaluate Formula / debugger | §4 Step |
| Checkpoint time-travel | LangGraph / n8n Executions | §4 Rewind + Branch |
| Per-type live inspector | Glamorous Toolkit | §4 Inspect panel |
| Diff/ghost before commit | Cursor / Copilot | §2.6 ghosted preview subgraph |
| Flame chart timeline | Chrome DevTools | The fallback for 200-step chains |

The pattern: **everyone server-pushes discrete events and the client
only paints.** No serious tool computes "what is live" on the render
side. ArchHub's bridge already does this for wires. The whole
architecture in §8 is "do for nodes and the agent what the runner
already does for wires."

---

## 2. The model — "the graph is the reasoning"

When the architect types intent into the composer and the agent acts,
the user must **watch the canvas**, not read a log. Here is what they
see, defined precisely.

### 2.1 The frame-by-frame storyboard (high level)

The agent loop in `composer_agent.py` is: receive intent → LLM emits
tool calls → tool calls execute → loop. Each phase maps to a canvas
event:

1. **Intent received.** The composer pill pulses once; an
   **agent-cursor** (a soft terracotta spotlight, §6.4) fades in over
   the composer.
2. **Agent plans.** Before the first real action, the agent emits a
   **ghosted preview subgraph** (§2.6) — dashed, 40%-opacity nodes and
   wires showing what it intends to build. The architect sees the
   *plan* as graph topology.
3. **Agent picks a tool / spawns a node.** The agent-cursor *travels*
   from the composer to the location where the node will appear; the
   node **draws itself** (200ms scale-from-90% + fade, the existing
   spawn animation at `studio-lm.jsx` motion budget) and the ghost for
   that node solidifies.
4. **Agent wires.** The wire **draws itself** — the bezier path animates
   its length from source socket to destination socket (a stroke-
   dashoffset reveal, ~150ms).
5. **Agent cooks the node.** The node enters `cooking` state — green
   outline, the Node-RED status dot pulsing. If it is an LLM cell, a
   thin per-node progress bar fills (ComfyUI-style). The agent-cursor
   sits on the cooking node.
6. **Value propagates.** On cook complete, the node flips to `cooked`;
   every downstream wire shows a **pulse** — a traveling glow bead runs
   source → destination (§6.3); the value-preview badge on the wire
   updates.
7. **Branch resolves.** If a logic node is involved, the chosen branch's
   wire lights solid and the rejected branch's wire dims to a ghost
   (§2.5).
8. **Done.** The agent-cursor fades; the final node gets a soft
   one-shot ring; the composer returns to rest.

The architect has *watched* the agent reason. They never read a
sentence unless they chose to open the Inspect panel.

### 2.2 Node states — "thinking about me" vs "cooked" vs "idle" vs "stale" vs "error"

The node must express, at a glance, where it stands relative to the
agent. Eight states (full spec in §6.1):

- **idle** — neutral. The agent is not looking at it; it has no fresh
  value. Default border, no glow.
- **AI-focused** — *the agent is reasoning about this node right now.*
  This is the founder's "thinking about me." A terracotta spotlight
  halo + the agent-cursor parked on it. This state is the headline of
  the whole document; it did not exist before.
- **queued** — the agent intends to cook this node next; it is in the
  cook queue. A thin dashed terracotta outline (the "about to" state —
  Norman feedback principle, currently silent per the UX doc's
  Nielsen-H1 gap).
- **cooking** — actively executing. Green outline (ComfyUI steal),
  pulsing 1.0Hz, status dot animated, progress bar if multi-step.
- **cooked** — finished with a fresh value. Muted-green left accent,
  value badge populated, fades the *outline* after 4s but keeps the
  accent.
- **stale** — has a value but an upstream changed; the value is no
  longer authoritative (the runner's `mark_dirty` state). Amber
  hatched left edge.
- **error** — the cook failed. Red border, persistent, error badge with
  the reason; offers a "fix" affordance (the UX doc's Nielsen-H9 gap).
- **frozen** — the user pinned it (`node.frozen`, already in the
  runner). A small lock glyph + a desaturated body; the agent's
  sweep visibly *routes around* it.

### 2.3 Wires showing data MOVING

A wire is not a static line during a run. ArchHub already paints wire
*state* on the bezier (`runner.py:_emit` → `wire_state_changed` →
`studio-lm.jsx:3199`). Today it animates a crude `strokeDasharray`
march (`lmDash`, `studio-lm.jsx:1085`) whenever either endpoint node is
`running`. The model upgrades this to four distinct motions:

- **carrying (a value is flowing right now)** — a **traveling glow
  bead**: a short bright segment runs along the bezier from source to
  destination, once per cook, ~400ms, ease-in-out. This is the
  "light through circuits" idiom (§1.16). It is a *one-shot per cook*,
  not a loop — loops are decorative and cost frames (UX doc motion
  budget: "hurts when it repeats decoratively").
- **cached (value present, fresh, idle)** — solid, full-opacity,
  colored by data type. No motion.
- **stale (value present, upstream changed)** — the bezier goes amber
  and dashed-static (no march). Dashed = "do not trust."
- **empty (no value ever)** — thin, 30% opacity, neutral grey.
- **error / upstream_error** — red, with a small ✕ at the midpoint.

**Color = data type**, reusing the Speckle taxonomy already specified
in `HOST_NODE_UI_GRAMMAR_2026-05-15.md` §4.6 (walls/doors/rooms warm
orange `#E87D0D`, geometry cyan `#0696D7`, email Outlook-blue
`#0078D4`, etc.). Motion = data *state*. The two are orthogonal: a wire
is "orange + traveling bead" = wall data, flowing now.

### 2.4 The canvas showing the AI DECIDING

Deciding is the interesting part and must be the most visible. Three
decision types:

- **Choosing a tool / spawning a node.** The agent-cursor travels to an
  empty canvas spot; a node materializes there (scale-up + fade,
  200ms); its incident wires draw themselves. The *travel* of the
  cursor is the decision being made visible — the architect sees the
  agent "move to" where it will work before the node exists.
- **Picking a branch.** A logic node (`l_select`, an if-node) shows
  *both* candidate output wires faintly during evaluation; on
  resolution, the chosen wire snaps to solid + fires a pulse, the
  rejected wire fades to a 15%-opacity ghost. The architect sees the
  fork *and* the road not taken.
- **Spawning sub-reasoning.** If the agent decomposes a step (CoT/ToT,
  §3), the parent reasoning node grows child reasoning nodes that draw
  themselves below it, wired back up. The decomposition is the topology
  appearing.

### 2.5 Logic resolution — if-nodes and foreach

- **If-node.** Two output ports, `true` and `false`. While the
  predicate cooks: node in `cooking` state, both wires ghosted. On
  resolve: the taken wire lights with a pulse; a tiny badge on the node
  shows the resolved predicate value (`exterior == true`).
- **Foreach.** A `l_foreach_begin`/`l_foreach_end` block (the runner's
  irreducible iteration primitive). During iteration, the block shows
  an **iteration counter** ("12 / 47"); the body subgraph's nodes
  *re-pulse once per iteration* — the architect literally watches the
  loop spin. A subtle progress ring around the `foreach_begin` node
  fills as iterations complete. (Performance caveat: re-pulsing every
  body node every iteration for a 5000-element loop is a frame killer —
  §5 caps this; above N iterations the per-iteration pulse drops to a
  counter-only update.)

### 2.6 The plan before execution — the ghosted preview subgraph

Before the agent commits any mutation, it emits its *plan* as a
**ghosted subgraph**: the nodes it intends to spawn and the wires it
intends to draw appear on the canvas at 40% opacity, dashed borders,
with a soft "PLAN" watermark on each. The architect can:
- **Accept all** — the ghost solidifies and the agent executes.
- **Accept per-node** — click a ghost node to solidify just that one.
- **Reject** — the ghost fades; the agent re-plans or asks.

This is Cursor's diff-before-apply (§1.13) expressed in graph topology
instead of red/green text, and it directly fulfils the UX doc's Tenet 1
("the AI is a co-author whose proposals are visible, reversible, and
bounded"). It replaces today's chip list (`step.actions` at
`studio-lm.jsx:4651`) with something *spatial* — the architect sees
*where* on their canvas the agent will act, not an abstract list.

---

## 3. The reasoning trace AS the graph — position and design

ArchHub today routes agent reasoning to `chat_reasoning` → a flat
string array `m.reasoning[]` on a Conversation node, rendered as a
collapsible numbered text list (`studio-lm.jsx:4071-4092`). The
question: should reasoning **(a)** stay text in the conversation node,
**(b)** become real nodes/wires on the canvas, or **(c)** a hybrid?

### 3.1 Position — (c) hybrid, but with a hard, opinionated rule

**Reasoning becomes graph topology when, and only when, a reasoning
step has a consequence on the canvas. Purely linguistic deliberation
stays as text — but as text attached to the node it produced, never in
a separate sidebar.**

The rule, stated sharply: **every reasoning step that results in a
canvas action (spawn, wire, cook, branch, tool call) IS a node. Every
reasoning step that is pure natural-language deliberation ("the user
probably means exterior walls because they said facade") is a
**thought annotation** attached to the node that the deliberation
produced.** The flat sidebar list is deleted entirely.

Why not pure (a): a text log throws away the canvas — it is exactly
what the founder rejected. It also makes Pause/Step/Inspect/Branch
(§4) impossible: you cannot set a breakpoint on line 3 of a paragraph.

Why not pure (b): token-level streaming and genuinely linguistic
reasoning do not map to discrete nodes (this is §9's hardest tension).
Forcing "the user said facade, facades are exterior, so I'll filter
exterior" into three wired nodes is noise — it is one thought, and it
belongs as one annotation on the filter node it justifies.

Why (c) with this rule: it makes the canvas the reasoning *for the
parts that are structural* (which is what the architect needs to
watch, control, and rewind) while keeping language as language *for
the parts that are linguistic* — but co-located with the structure, so
it is still inspectable, never a detached log.

### 3.2 What node kind is a "thought"

A new node category: **`reason`** (the ninth category alongside the
existing eight in `studio-lm.jsx:CAT`). A reasoning node differs from a
compute cell in four ways:

| Property | Compute cell (`cell.intent`) | Reasoning node (`reason`) |
|---|---|---|
| Purpose | Holds a typed *value* the workflow uses | Records a *decision* the agent made |
| Output | A typed payload (walls, list, image) | A `decision` payload: `{chose, because, alternatives}` |
| Persistence | Persists; re-cooks on dirty | Persists as a *trace*; never re-cooks — it is history |
| Lifecycle | Lives until deleted | Belongs to one agent turn; collapsible into the turn |
| Re-runnable | Yes (it is a formula) | No (it is a record of what happened) |

A reasoning node is closer to a NiFi provenance event (§1.4) or a
LangGraph checkpoint than to a compute cell: it is **immutable history
with structure**. Critically, reasoning nodes are **collapsible** — a
whole turn's reasoning subgraph collapses into a single "Turn 14:
reasoned in 6 steps" node that the architect expands only when they
want the detail. This is the §9 mitigation for the 200-node problem.

### 3.3 Grounding in the literature

The "reasoning is a graph" claim is not ArchHub's invention — it is the
trajectory of the chain-of-thought research:

- **Chain-of-Thought** (Wei et al., arXiv:2201.11903): reasoning as a
  *linear chain* of intermediate steps. A chain maps to a wired line of
  reasoning nodes — ArchHub's simplest case.
  <https://arxiv.org/abs/2201.11903>
- **Tree-of-Thoughts** (Yao et al., arXiv:2305.10601): reasoning as a
  *tree* — the agent explores multiple branches and prunes. This maps
  directly to ArchHub's branch visualization (§2.4): explored-then-
  pruned branches are the ghosted rejected wires. ToT *is* a graph and
  needs a graph UI.
  <https://arxiv.org/abs/2305.10601>
- **Graph-of-Thoughts** (Besta et al., arXiv:2308.09687): reasoning as
  an arbitrary *graph* — thoughts merge, loop, aggregate. GoT explicitly
  argues that reasoning steps form a graph with aggregation vertices.
  ArchHub's reducer-on-the-port model (from the reframe doc) is exactly
  GoT's aggregation vertex.
  <https://arxiv.org/abs/2308.09687>

The research arc is CoT (chain) → ToT (tree) → GoT (graph). ArchHub is
a canvas that *already renders graphs*. Rendering the agent's reasoning
as a graph is not a stretch — it is the native representation the
research has been converging on, and ArchHub is the rare product whose
primary surface can show it. **This is the strategic insight: ArchHub
should be the first tool where Graph-of-Thought reasoning is the
literal, visible, manipulable UI — not a diagram in a paper.**

---

## 4. Transparency = control — the interaction design

The founder's equation: *seeing is controlling*. Each control below is
unlocked *only* because the reasoning is a visible graph. For each: the
interaction, the visual, the precedent, and the concrete
bridge/runner change.

### 4.1 Watch
- **Interaction:** passive. The agent runs; the canvas shows it.
- **Visual:** the agent-cursor spotlight travels; the AI-focused node
  glows; wires pulse; nodes sweep through `cooking`→`cooked`.
- **Precedent:** ComfyUI execution sweep (§1.1); LangFlow playground
  (§1.8).
- **Change needed:** `bridge.py` new signal `agent_focus_changed(
  session_id, node_id, phase)`; `composer_agent.py` emits it before
  each tool call; `studio-lm.jsx` animation layer moves the spotlight.

### 4.2 Pause
- **Interaction:** the architect clicks a "Pause" control (or
  Spacebar) mid-run; the agent halts after the current step.
- **Visual:** the agent-cursor freezes on the current node; that node
  gets a "paused" double-bar badge; the canvas dims slightly to signal
  "frozen."
- **Precedent:** debugger pause (§1.11); LangGraph `interrupt()`.
- **Change needed:** `composer_agent.py` checks a
  `ctx.pause_requested` flag between tool-loop iterations and yields;
  `bridge.py` new slot `pause_agent(session_id)` sets it; the agent
  loop becomes cooperatively interruptible (today it is one blocking
  `router.complete` call — see §9, this is the hardest engineering
  piece).

### 4.3 Step
- **Interaction:** with the agent paused, the architect clicks "Step";
  the agent advances exactly one reasoning step, then re-pauses.
- **Visual:** one node activates, one wire pulses, the cursor moves
  once, then everything freezes again.
- **Precedent:** Excel Evaluate-Formula (§1.10); debugger step-over
  (§1.11).
- **Change needed:** `bridge.py` slot `step_agent(session_id)` sets
  `ctx.step_budget = 1`; the agent loop decrements and re-pauses at 0.

### 4.4 Inspect
- **Interaction:** the architect clicks any node mid-run (or post-run);
  a panel shows the exact state *at that node* — for a reasoning node:
  the prompt, the model's full response, the chosen decision, the
  alternatives considered, tokens, latency; for a compute cell: the
  typed value, rendered per-type (plan bbox / table / image).
- **Visual:** the right rail (`NodeRail`, `studio-lm.jsx:4957`) gains an
  "Inspect" tab; per-type renderers (the Glamorous Toolkit steal,
  §1.14).
- **Precedent:** Houdini geometry spreadsheet (§1.6); n8n node panels
  (§1.2); Smalltalk inspectors.
- **Change needed:** `bridge.py` slot `get_node_trace(session_id,
  node_id)` returns the per-node LLM envelope; the runner must *record*
  per-node prompt/response/tokens (today `node_outputs` holds only the
  output dict — extend to a `node_trace` map).

### 4.5 Intervene
- **Interaction:** the architect, with the agent paused on a node,
  edits that node's value (or a reasoning node's decision); resumes;
  the agent continues *from the corrected state*.
- **Visual:** the edited node flashes amber ("you changed this"), its
  downstream goes `stale`, the dirty-cascade ripple plays; on resume
  the agent recomputes from there.
- **Precedent:** debugger "edit a variable and continue" (§1.11);
  LangGraph `update_state` then resume (§1.7).
- **Change needed:** `bridge.py` slot `set_node_value_and_resume(
  session_id, node_id, value_json)`; the runner's `mark_dirty` already
  cascades; `composer_agent.py` must re-read graph state on resume
  rather than trusting its own in-memory plan.

### 4.6 Rewind
- **Interaction:** the architect opens a checkpoint timeline and jumps
  to any prior canvas state.
- **Visual:** a horizontal timeline rail (the flame-chart shape, §1.12)
  along the canvas bottom; each checkpoint a tick; clicking a tick
  restores the canvas to that state.
- **Precedent:** LangGraph time-travel checkpoints (§1.7); n8n
  Executions replay (§1.2); Victor's scrubbable state history (§1.15).
- **Change needed:** a checkpoint store. Every agent turn (and every
  cook) writes a checkpoint — the reframe doc already proposed
  `app/workflows/lineage.py` as a JSONL checkpoint store; this is that.
  `bridge.py` slots `list_checkpoints(session_id)` and
  `restore_checkpoint(session_id, checkpoint_id)`.

### 4.7 Branch
- **Interaction:** the architect picks any reasoning node and says
  "try a different path here"; the agent forks the reasoning from that
  node and explores an alternative; both branches coexist on the canvas
  for comparison.
- **Visual:** from the chosen node, a second subgraph grows alongside
  the original; a small branch label distinguishes them (the UX doc's
  side-by-side / pin-up-wall, Tenet 5).
- **Precedent:** git branch; LangGraph branch-from-checkpoint (§1.7);
  Tree-of-Thoughts exploration (§3.3).
- **Change needed:** `bridge.py` slot `branch_from_node(session_id,
  node_id)` clones the upstream cone into a new sub-region and
  re-invokes the agent with a "try differently" instruction; the
  checkpoint store (§4.6) is the substrate.

### 4.8 The control surface

These seven controls live in a compact **transport bar** that appears
at the canvas bottom *only while an agent run is live or paused* —
modelled on a video transport / debugger toolbar: `⏸ Pause · ⏭ Step ·
🔍 Inspect · ✎ Intervene · ⏪ Rewind · ⑂ Branch`, plus a **speed
slider** (§1.16) for Watch. When no run is active the bar is hidden —
the canvas stays clean (UX doc Tenet 4, invisible substrate).

---

## 5. Performance — visualization must not lag

The founder already called the UI "heavy and not smooth." A
live-animated reasoning graph is a real risk. This section sets hard
budgets and a concrete architecture.

### 5.1 The frame budget

60fps = **16.7ms per frame**. Of that, the browser needs ~4-6ms for
its own layout/paint/composite, leaving **~10ms of script budget** per
frame. Any animation that does layout or triggers React reconciliation
inside that window will drop frames. The reference: Google's RAIL
model — animations get a 10ms budget, response to input <100ms, idle
work in <50ms chunks (<https://web.dev/articles/rail>).

### 5.2 Why `bumpGraph()` is the wrong primitive

ArchHub's `bumpGraph()` (`studio-lm.jsx:488`) is
`setGraphBump(b => b + 1)` — it increments a counter that forces the
**entire `Workspace` subtree to re-render**: every `NodeRenderer`,
every wire, every `AIBody`. It is called on *every* `chat_chunk`
(`studio-lm.jsx:868`) and every `chat_reasoning` step
(`studio-lm.jsx:901`). For a streaming response that is dozens of
re-renders per second of the *whole canvas*. For a per-node reasoning
pulse it would be catastrophic: animating a 1Hz pulse on 40 nodes via
`bumpGraph` is 40 full-canvas reconciliations per second.

**`bumpGraph` is correct for structural change** (a node added, a wire
created — the topology changed, React must reconcile). **It is wrong
for state change** (a node started cooking, a wire is carrying — the
topology is identical, only a visual attribute changed).

### 5.3 The correct architecture — a separate animation layer

Three rules:

1. **Node/wire *state* never goes through React state.** When
   `node_state_changed(node_id, state)` arrives, a thin imperative
   handler does `document.querySelector('[data-node-id="..."]')
   .setAttribute('data-state', state)` — and CSS does the rest. The
   eight node states and five wire states are **CSS classes/attributes
   with CSS-defined visuals**; flipping an attribute is a compositor
   operation, not a React render. This is how ComfyUI, n8n, and
   Node-RED all do it: the server pushes an event, a handler toggles a
   class, CSS animates. Zero reconciliation.

2. **The agent-cursor and wire pulses live on a dedicated overlay
   `<canvas>` or a single absolutely-positioned SVG layer** that is
   *not* a React-managed tree. It is driven by one
   `requestAnimationFrame` loop that the agent run starts and stops.
   The rAF loop reads a plain mutable object (`agentAnim.cursorTarget`,
   `agentAnim.activePulses[]`) and draws — it never calls `setState`.
   This is the algorithm-visualizer model (§1.16): one draw loop, plain
   state, no framework in the hot path.

3. **Per-node subscription, not top-down props.** Each `NodeRenderer`
   that needs to react to *value* changes (the value badge) subscribes
   to a per-node event channel (`nodeBus.on(node.id, cb)`) and calls
   its *own* local `setState` — so a value update on node A re-renders
   only node A, not the canvas. This is the standard fix for the
   "one store, N subscribers" problem (the pattern behind Zustand
   selectors / `useSyncExternalStore`).

Motion technique choices:
- **CSS animation / transition** — for node-state pulses, glows, the
  spawn scale-fade. Compositor-threaded, cheapest. Default choice.
- **`requestAnimationFrame` + canvas overlay** — for the agent-cursor
  travel and the wire pulse bead, because they move along arbitrary
  bezier paths that CSS cannot express. One rAF loop total.
- **SVG SMIL** — rejected. Deprecated in Chromium-trajectory, poor
  performance at scale, no fine control.
- **WebGL** — overkill for ArchHub's node counts; revisit only if a
  canvas regularly exceeds ~300 nodes.

### 5.4 How ComfyUI and n8n keep it cheap

ComfyUI's litegraph canvas renders the *whole graph to a single
`<canvas>`* and only redraws on change; the execution highlight is one
extra stroke on the already-drawn canvas — not a DOM mutation per node.
n8n uses Vue with the execution state in a store and per-node computed
bindings, so a node's color change re-renders one node component. Both
confirm rule 1 and rule 3: **never re-render the graph to change one
node's color.**

### 5.5 Concrete ceiling budget

For an architect's mid-range laptop (integrated GPU, the realistic
ArchHub target — the UX doc's persona):

| Quantity | Comfortable | Degrade at | Hard ceiling |
|---|---|---|---|
| Nodes painted | ≤ 60 | 60–120 | ~200 |
| Wires painted | ≤ 90 | 90–200 | ~300 |
| Concurrent wire pulses | ≤ 12 | 12–25 | ~40 |
| Reasoning steps/sec (sweep rate) | ≤ 6 | 6–12 | ~20 |
| Node-state flips/sec | ≤ 30 | 30–80 | ~150 |

Mitigations when a count is exceeded:
- **> 120 nodes:** semantic zoom — collapse reasoning subgraphs into
  turn-summary nodes (§3.2); stop animating off-screen nodes (an
  `IntersectionObserver` gate — only on-screen nodes get pulses).
- **> 25 concurrent pulses:** coalesce — drop per-wire beads, switch to
  a single "wave" highlight that sweeps the whole dirty cone at once.
- **> 12 steps/sec:** the sweep is faster than the eye anyway; drop the
  per-step animation and batch — paint the final state with one ripple.
- **foreach > N iterations:** per-iteration body pulse becomes a
  counter-only update (§2.5).

The rule the founder needs to hear: **the animation layer is bounded
and degrades gracefully; it never blocks the agent and never blocks
input.** A dropped animation frame is invisible; a dropped *input*
frame is the "heavy and not smooth" complaint. The animation layer is
explicitly lower priority than input handling.

---

## 6. Visual language spec

Concrete. States × properties. Reuses the Speckle WIRE color taxonomy
from `HOST_NODE_UI_GRAMMAR_2026-05-15.md` §4.6.

### 6.1 Node states

| State | Border | Glow / halo | Badge | Motion | Trigger |
|---|---|---|---|---|---|
| **idle** | 1px `LM.line` grey | none | none | none | default |
| **AI-focused** | 2px `#cc785c` terracotta | terracotta halo, 8px soft, ~30% | none (cursor parks here) | halo breathes 0.5Hz | `agent_focus_changed` |
| **queued** | 1px dashed `#cc785c` ~50% | none | small ⋯ top-right | dash static | in cook queue |
| **cooking** | 2px `#5a9e6f` green | green halo 6px | status dot ●, animated; progress bar if multi-step | border pulses 1.0Hz | `node_state_changed: cooking` |
| **cooked** | 1px grey; 3px `#5a9e6f` left accent | none | value-preview text | one-shot ring on entry, 400ms | `node_state_changed: cooked` |
| **stale** | 1px grey; 3px `#d99a3e` amber hatched left | none | value badge dimmed 50% | none (static hatch) | `mark_dirty` cascade |
| **error** | 2px `#c0564a` red | none | ✕ + reason text + "fix" link | none (persistent) | cook failed |
| **frozen** | 1px grey; body desaturated 40% | none | 🔒 lock glyph | none; sweep routes around | `node.frozen === true` |

### 6.2 Wire states

| State | Stroke | Opacity | Color source | Motion | Badge |
|---|---|---|---|---|---|
| **empty** | 1px | 30% | neutral `#7d7466` | none | none |
| **carrying** | 2px | 100% | data type (Speckle map) | traveling glow bead, 1×/cook, ~400ms ease-in-out | none during travel |
| **cached** | 1.6px | 100% | data type (Speckle map) | none | `value_preview` chip at midpoint |
| **stale** | 1.6px dashed | 70% | amber `#d99a3e` | none (dashed-static) | dimmed value chip |
| **error** | 2px | 100% | red `#c0564a` | none | ✕ at midpoint |
| **refused** | 1.6px dashed | 60% | red `#c0564a` | none; visible gap kept (Gestalt closure, per UX doc §1.6) | reason tooltip |

Data-type → color (from `HOST_NODE_UI_GRAMMAR` §4.6, abbreviated):
walls/doors/windows/rooms `#E87D0D`; levels/sheets/views `#C66C0A`;
curves/surfaces/meshes/breps `#0696D7`; email/calendar `#0078D4`;
ranges/csv `#107C41`; intent/decision/reasoning `#7E6BB8` purple;
exec/control `#FFFFFF`; untyped `#7d7466`.

### 6.3 The wire pulse — motion spec

- **Shape:** a 14px-long bright segment (the data-type color at 100%
  lightness + a 2px glow) riding the bezier path.
- **Path:** the exact `M…C…` bezier already computed at
  `studio-lm.jsx:3182`. The bead position is sampled along the cubic at
  parameter `t ∈ [0,1]`.
- **Duration:** 400ms source→destination. **Easing:** `ease-in-out`
  (cubic-bezier 0.4, 0, 0.2, 1) — accelerate off the source, decelerate
  into the destination, so the eye reads "delivered."
- **Frequency:** exactly once per cook of the source node. Never loops.
- **`prefers-reduced-motion` fallback:** no bead. Instead the wire does
  a single 200ms opacity flash (40%→100%→cached). State is still
  conveyed; motion is removed. This is mandatory — the UX doc and
  WCAG 2.1 require it.

### 6.4 The agent-cursor — design

**Yes — the canvas shows a visible "AI is here" cursor.** This is the
single highest-signal element. Design:

- **Form:** a soft circular spotlight, ~120px diameter, terracotta
  `#cc785c` at ~12% opacity center fading to 0 at the edge — like a
  stage follow-spot, not a hard pointer. It does not obscure the node
  it lands on; it *illuminates* it.
- **A small leading glyph** at the spotlight's center: a 16px ✦ (the
  AI-category mark already in `studio-lm.jsx:CAT.ai`), so the architect
  has a precise point to track.
- **Travel:** when the agent moves from node A to node B, the spotlight
  *glides* the straight-line path A→B over 300–500ms (distance-scaled),
  `ease-in-out`. The glide IS the decision being made visible (§2.4).
- **At rest on a node:** the spotlight sits centered on the
  AI-focused node; its glyph pulses gently 0.5Hz to signal "thinking."
- **Idle:** when no agent run is active, the cursor does not exist —
  zero pixels (UX doc Tenet 4).
- **Reduced-motion:** the spotlight *cuts* (no glide) from node to
  node, with a 150ms cross-fade. Still legible.
- **Performance:** the cursor is one element on the rAF overlay layer
  (§5.3). One draw call per frame. It is the cheapest possible way to
  express "the AI is working here."

### 6.5 Motion budget summary

| Element | Duration | Easing | Loops? | Reduced-motion |
|---|---|---|---|---|
| Node spawn (agent) | 200ms scale 0.9→1 + fade | ease-out | no | fade only, 120ms |
| Wire self-draw | 150ms dashoffset reveal | ease-out | no | instant |
| Wire pulse bead | 400ms travel | ease-in-out | no | 200ms opacity flash |
| Agent-cursor travel | 300–500ms glide | ease-in-out | no | 150ms cut+crossfade |
| Cooking border pulse | 1.0Hz | sine | yes (only while cooking) | static green border |
| AI-focused halo breathe | 0.5Hz | sine | yes (only while focused) | static halo |
| Cooked entry ring | 400ms | ease-out | no | none |
| Dirty-cascade ripple | 60ms/hop stagger | linear | no | instant stale repaint |

Three looping animations only, each bounded to a transient state. No
decorative loops (UX doc motion principle).

---

## 7. ASCII / textual storyboards (mandatory)

### 7.1 Scenario A — "list level-1 exterior walls and tag them"

The architect types into the composer: *"list level-1 exterior walls
and tag them."* `[ ]` = ghost/plan, `[#]` = cooking, `[=]` = cooked,
`(*)` = agent-cursor spotlight.

```
FRAME 1 — intent received. Cursor fades in over composer.
┌──────────────────────────────────────────────────────────┐
│                                                            │
│                                                            │
│                                                            │
│        ┌────────────────────────────────────┐  (*)        │
│        │ /list level-1 exterior walls and…  │ ◀── cursor  │
│        └────────────────────────────────────┘   over      │
│                                                  composer  │
└──────────────────────────────────────────────────────────┘

FRAME 2 — agent emits its PLAN as a ghosted subgraph (40% opacity,
dashed). The architect sees the whole intended pipeline at once.
┌──────────────────────────────────────────────────────────┐
│  ┌ r_doc ┐   ┌ r_walls ┐   ┌ f:exterior ┐   ┌ a_tag ┐    │
│  [ Revit ]·· [ list    ]·· [ filter L1  ]·· [ tag   ]    │
│  [ active]   [ walls   ]   [ exterior   ]   [ walls  ]    │
│       (ghost — dashed, watermarked "PLAN")          (*)   │
│   [ Accept all ]  [ Reject ]      cursor waits at composer │
└──────────────────────────────────────────────────────────┘

FRAME 3 — architect clicks Accept. Cursor glides to slot 1; the
r_doc node solidifies + draws itself; it cooks (green).
┌──────────────────────────────────────────────────────────┐
│  ┌ r_doc ┐(*)  ┌ r_walls ┐   ┌ f:exterior ┐  ┌ a_tag ┐   │
│  [# Revit ]    [ list    ]·· [ filter L1  ]··[ tag    ]   │
│  [# active]    [ walls   ]   [ exterior   ]  [ walls  ]   │
│   cooking ↑ green pulse, status dot ●                      │
└──────────────────────────────────────────────────────────┘

FRAME 4 — r_doc cooked. Wire to r_walls draws + fires a pulse bead
(orange = wall-domain data). Cursor glides to r_walls; it cooks.
┌──────────────────────────────────────────────────────────┐
│  ┌ r_doc ┐    ┌ r_walls ┐(*) ┌ f:exterior ┐  ┌ a_tag ┐   │
│  [= Revit ]───●──▶[# list ]··[ filter L1  ]··[ tag    ]   │
│  [= active]  bead [# walls]  [ exterior   ]  [ walls  ]   │
│   cooked      ↑ orange pulse travelling                    │
└──────────────────────────────────────────────────────────┘

FRAME 5 — r_walls cooked: value badge "212 walls". Cursor glides to
the filter; it cooks. The wire carries "212 walls" as a midpoint chip.
┌──────────────────────────────────────────────────────────┐
│  ┌ r_doc ┐    ┌ r_walls ┐    ┌ f:exterior ┐(*) ┌ a_tag ┐ │
│  [= Revit ]──▶[= list   ]──●─▶[# filter L1]···[ tag    ] │
│  [= active]   [= 212    ]  "212  [# exterior]  [ walls  ] │
│               [  walls  ] walls"  cooking                 │
└──────────────────────────────────────────────────────────┘

FRAME 6 — filter cooked: "47 walls (L1 exterior)". A 'reason' node
has appeared below the filter: the agent's deliberation, attached.
┌──────────────────────────────────────────────────────────┐
│  [= r_doc]──▶[= r_walls]──▶[= f:exterior]──●─▶[# a_tag ]  │
│                            [= 47 walls  ]  "47  [# tag  ] │
│                                  │         walls" cooking │
│                            ┌─────▼──────┐          (*)    │
│                            │ ✦ reason   │  "facade ⇒      │
│                            │ chose L1+  │   exterior;      │
│                            │ exterior   │   L1 from        │
│                            └────────────┘   'level-1'"     │
└──────────────────────────────────────────────────────────┘

FRAME 7 — a_tag cooked. Cursor fades out. Final node gets a one-shot
ring. The architect watched the agent reason, end to end.
┌──────────────────────────────────────────────────────────┐
│  [= r_doc]──▶[= r_walls]──▶[= f:exterior]──▶[= a_tag   ]  │
│                            [= 47 walls  ]   [= 47 tags ]  │
│                                  │           ◌ ring fades │
│                            [✦ reason]                     │
│   ▸ Turn 14 · reasoned in 4 steps · 6.2s · claude-sonnet  │
└──────────────────────────────────────────────────────────┘
```

The architect never read a chat log. They watched four nodes appear,
wire themselves, cook in sequence, carry orange wall-data pulses, and
saw the one genuinely linguistic decision ("facade ⇒ exterior") parked
as a reason node on the filter it justified.

### 7.2 Scenario B — pause mid-run, inspect a node, edit a value, resume

The agent is mid-run on a larger pipeline. The architect suspects the
filter caught the wrong walls.

```
FRAME 1 — agent running; cursor on the filter, which is cooking.
The architect hits SPACEBAR (or clicks ⏸ Pause).
┌──────────────────────────────────────────────────────────┐
│ [= r_walls]──▶[# f:exterior]··▶[ a_dim ]··▶[ c_sched ]   │
│               [# cooking  ](*)                            │
│ ───────────────────────────────────────────────────────  │
│  ⏸ Pause  ⏭ Step  🔍 Inspect  ✎ Intervene  ⏪ Rewind     │
└──────────────────────────────────────────────────────────┘

FRAME 2 — agent halts AFTER the current step. The filter finished;
cursor freezes on it with a ‖ paused badge; canvas dims slightly.
┌──────────────────────────────────────────────────────────┐
│ [= r_walls]──▶[= f:exterior]‖··▶[ a_dim ]··▶[ c_sched ]  │
│               [= 47 walls  ](*) paused                   │
│               cursor frozen here                          │
│ ─────────────────────── PAUSED ─────────────────────────  │
└──────────────────────────────────────────────────────────┘

FRAME 3 — architect clicks the filter node, then 🔍 Inspect. The
right rail opens the per-node trace.
┌────────────────────────────────────┬─────────────────────┐
│ [= r_walls]─▶[= f:exterior]‖─▶[a_dim]│  INSPECT · f:exterior│
│              [= 47 walls  ]          │  ──────────────────  │
│                  ▲ selected          │  intent: "exterior   │
│                                      │   walls on Level 1"  │
│                                      │  input: 212 walls    │
│                                      │  output: 47 walls    │
│                                      │  ┌────────────────┐  │
│                                      │  │ ▢ plan bbox    │  │
│                                      │  │  (47 wall      │  │
│                                      │  │   centerlines) │  │
│                                      │  └────────────────┘  │
│                                      │  model: sonnet       │
│                                      │  predicate the AI    │
│                                      │  wrote:              │
│                                      │   wall.Function ==   │
│                                      │   'Exterior' AND     │
│                                      │   wall.Level=='L1'   │
│                                      │  [ ✎ Edit value ]    │
└────────────────────────────────────┴─────────────────────┘

FRAME 4 — the architect sees the predicate excluded a curtain-wall
type. Clicks ✎ Edit value, edits the 47-wall set to 51 (adds the 4
curtain walls). The node flashes amber; downstream goes stale; the
dirty-cascade ripple plays toward a_dim and c_sched.
┌──────────────────────────────────────────────────────────┐
│ [= r_walls]──▶[~ f:exterior]‖··▶[~ a_dim ]··▶[~ c_sched]  │
│               [~ 51 walls  ]    amber       amber         │
│                ▲ amber flash   stale ripple →→→           │
│ ─────────────────────── PAUSED ─────────────────────────  │
└──────────────────────────────────────────────────────────┘

FRAME 5 — architect clicks ⏵ Resume. The agent re-reads graph state,
sees 51 walls, and continues from the corrected node. Cursor glides
to a_dim; it cooks with the corrected input.
┌──────────────────────────────────────────────────────────┐
│ [= r_walls]──▶[= f:exterior]──●─▶[# a_dim ](*)▶[ c_sched] │
│               [= 51 walls  ] "51    [# cooking]           │
│                               walls"  with 51             │
│ ──────────────────────── RUNNING ───────────────────────  │
└──────────────────────────────────────────────────────────┘

FRAME 6 — run completes with the architect's correction baked in.
A checkpoint tick is dropped on the timeline for this intervention.
┌──────────────────────────────────────────────────────────┐
│ [= r_walls]──▶[= f:exterior]──▶[= a_dim ]──▶[= c_sched ]  │
│               [= 51 walls  ]   [= 51 dims]  [= schedule] │
│ timeline: ──•────────•─────────•──────────●  ◀ "intervened"│
└──────────────────────────────────────────────────────────┘
```

The architect did not fight the agent or restart. They paused it,
looked inside a node, found the bug in the agent's own predicate,
corrected the value, and the agent continued from the fix. That is
control through transparency — the founder's thesis, operational.

---

## 8. Architectural diff

Concrete: files, functions, signals, LOC. ArchHub already has the wire
half of this (`wire_state_changed` flows from `runner.py` to the
canvas). The work is the **node half** and the **agent half**.

### 8.1 `app/bridge.py` — new signals + slots (~260 LOC)

New signals (alongside the existing block at `bridge.py:292-313`):

```python
node_state_changed   = pyqtSignal(str, str, str)   # (node_id, state, preview)
agent_focus_changed  = pyqtSignal(str, str, str)   # (session_id, node_id, phase)
reasoning_node_added = pyqtSignal(str, str)        # (session_id, node_json)
agent_paused         = pyqtSignal(str, str)        # (session_id, node_id)
checkpoint_created    = pyqtSignal(str, str)        # (session_id, checkpoint_id)
```

`node_state_changed` is the headline addition — it is the exact twin
of `wire_state_changed`, which the runner already emits via
`runner.on_wire_state`. The runner gains an `on_node_state` callback
(§8.2) and the bridge wires it in `run_workflow` / `run_node` (the
`_emit_wire_state` closures at `bridge.py:1190` and `:1264` get a
sibling `_emit_node_state`).

New slots:
- `pause_agent(session_id)` — sets `ctx.pause_requested`.
- `step_agent(session_id)` — sets `ctx.step_budget = 1`.
- `resume_agent(session_id)` — clears the pause flag.
- `get_node_trace(session_id, node_id)` → JSON of the per-node LLM
  envelope (prompt / response / tokens / latency / value).
- `set_node_value_and_resume(session_id, node_id, value_json)` —
  Intervene (§4.5).
- `list_checkpoints(session_id)` / `restore_checkpoint(session_id,
  checkpoint_id)` — Rewind (§4.6).
- `branch_from_node(session_id, node_id)` — Branch (§4.7).

### 8.2 `app/workflows/runner.py` — node-state emission + trace recording (~160 LOC)

- Add `on_node_state(cb)` mirroring `on_wire_state` (`runner.py:299`),
  and an `_emit_node` helper mirroring `_emit` (`runner.py:308`).
- In `pull()` (`runner.py:405`): emit `queued` when a node enters the
  upstream walk, `cooking` immediately before `executor(...)`
  (`runner.py:483`), `cooked` / `error` after. Today the node has *no*
  state signal at all — only its wires do. This is the gap.
- Add a `node_trace: dict[str, dict]` map alongside `node_outputs`
  (`runner.py:291`); when an LLM-backed executor runs, record
  `{prompt, response, tokens, latency, model}` so `get_node_trace` has
  something to return.
- Make the runner cooperatively interruptible: between upstream pulls
  and before each `executor` call, check `self.ctx.pause_requested` and
  `self.ctx.step_budget`; if paused, raise a `Paused` sentinel the
  bridge catches and re-enters on `resume_agent`. (This is the hardest
  part — see §9.)
- `mark_dirty` (`runner.py:355`) already emits `stale` on incident
  edges — extend it to also `_emit_node(n, "stale")` so the
  dirty-cascade ripple has node-level events to animate.

### 8.3 `app/agents/composer_agent.py` — step events + plan emission (~180 LOC)

- The agent loop currently fires one blocking `router.complete`
  (`composer_agent.py:256`). Restructure so that *before* each tool
  invocation the agent emits `agent_focus_changed(session_id,
  target_node_id, phase)` — phases: `planning`, `spawning`, `wiring`,
  `cooking`, `deciding`, `done`. The `_on_inv` callback
  (`composer_agent.py:225`) is the natural hook — it already fires per
  tool call; add the focus emit there.
- Add a planning pre-pass: the agent first returns a *plan* (the set of
  intended spawn/wire calls) without executing; the bridge turns that
  into the ghosted preview subgraph (§2.6) and waits for accept. This
  replaces the current "execute then show chips" with "show ghost then
  execute."
- When a tool call is a reasoning decision (not a structural mutation),
  emit `reasoning_node_added` with a `reason`-category node payload
  instead of appending to the text `chat_reasoning` stream.
- Honour `ctx.pause_requested` / `ctx.step_budget` between tool-loop
  iterations.

The `TOOL_SCHEMA` also gains a `note_reasoning` tool so the agent can
explicitly emit a thought annotation: `{node_id, decision, because,
alternatives}` → a `reason` node wired to `node_id`.

### 8.4 `app/web_ui/studio-lm.jsx` — the animation layer (~620 LOC)

The biggest and most delicate change. **Do not extend `bumpGraph`.**

- **New: a non-React animation overlay.** A single `<canvas>` (or one
  static SVG layer) absolutely positioned over the node layer, inside
  the pan/zoom transform. It draws the agent-cursor and wire pulse
  beads. Driven by one `requestAnimationFrame` loop started by
  `agent_focus_changed` and stopped on `phase === 'done'`.
- **New: `nodeBus` — a tiny per-node event emitter.** `node_state_
  changed` handler does *not* call `bumpGraph`; it does
  `nodeBus.emit(node_id, state)`. Each `NodeRenderer` subscribes in a
  `useEffect` (`nodeBus.on(n.id, ...)`) and flips a local
  `data-state` attribute / minimal local state. One node re-renders,
  not the canvas.
- **New: CSS for the eight node states and five wire states** — added
  to the `<style>` block (where `lmDash` lives, `studio-lm.jsx:1085`).
  State visuals are pure CSS keyed off `data-state` attributes.
- **Rewrite the `chat_reasoning` handler** (`onReasoning`,
  `studio-lm.jsx:883`): instead of pushing to `m.reasoning[]`, listen
  for `reasoning_node_added` and add a `reason`-category node to the
  graph (this one *is* a structural change, so `bumpGraph` is correct
  here — but it fires once per reasoning node, not per token).
- **New: the transport bar** (§4.8) — appears on `agent_focus_changed`,
  hidden on done; wired to `pause_agent` / `step_agent` / etc.
- **New: the Inspect tab** in `NodeRail` (`studio-lm.jsx:4957`) — calls
  `get_node_trace`, renders per-type (plan bbox / table / prose).
- **Wire-pulse trigger:** the existing `wire_state_changed` handler,
  on `state === 'flowing'`, pushes a pulse onto `agentAnim.activePulses`
  for the rAF loop — it no longer just sets a boolean for the `lmDash`
  march.
- Delete the `m.reasoning[]` text-list rendering in `AIBody`
  (`studio-lm.jsx:4071-4092`) once reasoning nodes ship.

### 8.5 `app/workflows/lineage.py` — new file, the checkpoint store (~180 LOC)

A JSONL-per-session checkpoint store (the reframe doc already proposed
this file). Each agent turn and each cook appends a checkpoint
`{id, ts, graph_snapshot, trigger}`. Backs Rewind (§4.6) and Branch
(§4.7). `restore_checkpoint` swaps the session graph; `branch_from_node`
clones a cone and re-invokes the agent.

### 8.6 LOC summary

| File | Change | LOC |
|---|---|---|
| `bridge.py` | 5 signals + 8 slots | ~260 |
| `runner.py` | node-state emit + trace + interrupt | ~160 |
| `composer_agent.py` | focus events + plan pass + reason tool | ~180 |
| `studio-lm.jsx` | animation layer + nodeBus + CSS + transport + Inspect | ~620 |
| `lineage.py` | new — checkpoint store | ~180 |
| tests | runner interrupt, checkpoint round-trip, bridge signals | ~260 |
| **Total** | | **~1660** |

---

## 9. Honest pushback — where "the graph is the reasoning" breaks down

It is a strong model. It is not universally true. Four places it
strains:

1. **Very long reasoning chains.** A hard agentic task can be 100–200
   reasoning steps. 200 reason nodes on a canvas is unreadable — it
   violates the UX doc's semantic-zoom ceiling (~30 nodes) by an order
   of magnitude. The canvas becomes the wall of spaghetti the founder
   is trying to escape.
2. **Token-level streaming does not map to discrete nodes.** An LLM
   emits tokens continuously; a node is discrete. There is no honest
   way to render "the agent is 340 tokens into composing a response" as
   graph topology. The chat-chunk stream is genuinely linear text.
3. **Some reasoning is genuinely linguistic, not structural.** "The
   user said 'facade,' facades are the exterior envelope, so they
   probably mean exterior walls" is one inference. Rendering it as
   three wired nodes (premise → premise → conclusion) is *noise* — it
   inflates the canvas without adding inspectability. It is one
   thought.
4. **Backtracking and dead ends.** Real agent reasoning explores, fails,
   and abandons. If every abandoned path stays on the canvas as
   topology, the canvas accumulates dead subgraphs. If they are
   deleted, the architect loses the ability to see *why* the agent
   rejected a path — which is exactly the transparency the model
   promises.

**The single hardest tension:** *reasoning is partly graph-shaped and
partly text-shaped, and forcing all of it into either representation
breaks.* Pure graph drowns the canvas in 200 micro-nodes (problem 1+3);
pure text is the chat log the founder rejected (problem 2). The model
"the graph IS the reasoning" is true for the **structural** spine of
reasoning and false for the **linguistic** texture of it.

**The mitigation** — a three-part answer, which is why §3 took the
hybrid position so firmly:

- **Granularity rule (problem 1, 3):** a reasoning step becomes a node
  *only if it has a canvas consequence* (spawn / wire / cook / branch /
  tool call). Pure linguistic deliberation is a **thought annotation**
  on the node it justified — text, but co-located with structure, not
  in a detached log. A 200-LLM-call task that produces 12 structural
  actions is a 12-node reasoning graph with annotations, not a
  200-node graph.
- **Collapsible turns (problem 1, 4):** an agent turn's reasoning
  subgraph — including its explored-then-abandoned branches — collapses
  by default into one "Turn N · reasoned in K steps" node. The dead
  ends are *inside* it, preserved, available on expand (so the "why did
  it reject that" transparency survives) but not cluttering the canvas.
  The default canvas shows turn-summary nodes; the architect expands
  the one turn they care about. This is semantic zoom (UX doc §6.2)
  applied to reasoning.
- **The timeline fallback (problem 1, 2):** for genuinely long or
  genuinely linear reasoning, the **flame-chart timeline rail** (§1.12,
  §4.6) is the right surface, not the canvas. The canvas shows the
  structural graph; the timeline shows the full step sequence as bars;
  token streaming shows in the Inspect panel as live text. Each kind of
  reasoning gets the representation that fits it. The canvas is the
  *primary* and *default* view because structural reasoning is what the
  architect must control — but it is not forced to carry what it cannot
  carry.

Honest bottom line: "the graph is the reasoning" is the right
*organizing principle and default*, but the implementation must be a
disciplined hybrid — graph for structure, annotation for language,
timeline for length — or it recreates the spaghetti it set out to kill.

---

## 10. Six-week build plan

| Wk | Theme | File-level scope | Ship gate |
|---|---|---|---|
| **1** | **Node-state plumbing.** Runner emits node states; bridge relays. | `runner.py` — `on_node_state` + `_emit_node` + emits in `pull` (~90); `bridge.py` — `node_state_changed` signal + relay (~60); tests (~80) | Run a workflow; every node's `idle→queued→cooking→cooked` transitions arrive on the bridge signal. No UI yet. |
| **2** | **The animation layer.** Non-React overlay; `nodeBus`; CSS state visuals; kill per-state `bumpGraph`. | `studio-lm.jsx` — rAF overlay, `nodeBus`, CSS for 8 node + 5 wire states, per-node subscription (~320) | Nodes paint their state via CSS-class flips with zero canvas re-render; a 60-node graph cooks at a steady 60fps. |
| **3** | **The agent-cursor + focus events.** Composer agent emits focus; cursor travels; wire pulse beads. | `composer_agent.py` — `agent_focus_changed` emits per phase (~90); `bridge.py` — signal (~30); `studio-lm.jsx` — cursor draw + glide + pulse beads on rAF layer (~180) | The architect types intent and watches the spotlight travel the graph; wires fire pulse beads on cook. |
| **4** | **Reasoning as nodes.** New `reason` category; `note_reasoning` tool; ghosted preview subgraph; delete the text reasoning list. | `composer_agent.py` — plan pass + `note_reasoning` (~120); `studio-lm.jsx` — `reason` node render, ghost subgraph, rewrite `onReasoning` (~220) | The agent's plan appears as a ghost; reasoning steps with consequences appear as `reason` nodes; the sidebar text list is gone. |
| **5** | **Pause / Step / Inspect.** Cooperative interrupt in runner; transport bar; per-node trace + Inspect tab. | `runner.py` — interrupt checks + `node_trace` (~110); `bridge.py` — pause/step/resume/get_node_trace (~110); `composer_agent.py` — honour flags (~50); `studio-lm.jsx` — transport bar + Inspect tab (~200) | The architect pauses a live run, steps it one node at a time, clicks a node, sees its prompt/value/tokens. |
| **6** | **Rewind / Intervene / Branch.** Checkpoint store; intervene-and-resume; branch-from-node; reduced-motion + perf degradation. | `lineage.py` — new checkpoint store (~180); `bridge.py` — checkpoint + intervene + branch slots (~120); `studio-lm.jsx` — timeline rail, `prefers-reduced-motion` fallbacks, IntersectionObserver perf gate (~180); tests (~180) | The architect intervenes mid-run (edit a value, resume), rewinds to a checkpoint, and branches the reasoning; reduced-motion verified; a 150-node graph degrades gracefully without input lag. |

Each week ships behind a flag and is independently demoable. Week 1–3
deliver "Watch" (the founder's core ask). Week 4 makes reasoning
structural. Week 5–6 deliver the full debugger-grade control surface.

---

*End of report. Author: senior research lead, dataflow visualization &
AI-system observability · ArchHub · 2026-05-15.*

**Key sources (primary docs cited in body):**
- ComfyUI execution model — <https://github.com/comfyanonymous/ComfyUI>
- n8n executions — <https://docs.n8n.io/workflows/executions/>
- Node-RED node status — <https://nodered.org/docs/creating-nodes/status>
- Apache NiFi data provenance — <https://nifi.apache.org/docs.html>
- TouchDesigner cook — <https://docs.derivative.ca/Cook>
- Houdini docs — <https://www.sidefx.com/docs/houdini/>
- LangGraph time-travel — <https://langchain-ai.github.io/langgraph/concepts/time-travel/>
- LangGraph persistence/checkpoints — <https://langchain-ai.github.io/langgraph/concepts/persistence/>
- LangSmith observability — <https://docs.smith.langchain.com/observability>
- LangFlow — <https://docs.langflow.org/>
- Observable runtime — <https://observablehq.com/@observablehq/how-observable-runs>
- Marimo reactivity — <https://docs.marimo.io/guides/reactivity/>
- Excel formula tracing — <https://support.microsoft.com/en-us/office/display-the-relationships-between-formulas-and-cells-a59bef2b-3701-46bf-8ff1-d3518771d507>
- VS Code debugging — <https://code.visualstudio.com/docs/editor/debugging>
- Chrome DevTools performance — <https://developer.chrome.com/docs/devtools/performance>
- Chrome DevTools JS debugging — <https://developer.chrome.com/docs/devtools/javascript>
- Cursor docs — <https://docs.cursor.com/>
- Glamorous Toolkit — <https://gtoolkit.com/>
- Bret Victor, Learnable Programming — <https://worrydream.com/LearnableProgramming/>
- Bret Victor, Inventing on Principle — <https://worrydream.com/InventingOnPrinciple/>
- TensorFlow Playground — <https://playground.tensorflow.org/>
- Google RAIL performance model — <https://web.dev/articles/rail>
- Chain-of-Thought — Wei et al., arXiv:2201.11903 — <https://arxiv.org/abs/2201.11903>
- Tree-of-Thoughts — Yao et al., arXiv:2305.10601 — <https://arxiv.org/abs/2305.10601>
- Graph-of-Thoughts — Besta et al., arXiv:2308.09687 — <https://arxiv.org/abs/2308.09687>
