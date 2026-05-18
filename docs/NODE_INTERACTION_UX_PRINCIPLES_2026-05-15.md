# Node Interaction UX Principles — ArchHub Canvas

> Author: senior UX/HCI researcher · 2026-05-15.
> Scope: the **principles of canvas interaction** for ArchHub —
> cognitive model, interaction philosophy, visual rules, AI-coexistence
> patterns. NOT host-node parameter widgets (Slider, Dropdown, etc.) —
> that work is in `docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md` by a parallel
> researcher.
> Companion reading (already digested, will not re-summarise):
> `docs/NODE_RND_2026-05-15.md` (28-app survey),
> `docs/NODE_RND_REFRAME_2026-05-15.md` (cells-as-memory reframe),
> `docs/CANVAS_PLAN.md` §v1.4 (shipping architecture),
> `docs/USER_GUIDE.md` (current user-visible behaviour),
> `app/web_ui/studio-lm.jsx` (~5635 LOC, the React canvas itself).

## 0. Executive verdict (read this first)

The founder's quote ("you need to visualise things in a way that the end
user can interact with perfectly") is not a styling problem. It is a
problem of *cognitive fit* — Vessey 1991, *Cognitive Fit: A
Theory-Based Analysis of the Graphs Versus Tables Literature* — between
the architect's mental model of a project and the canvas's externalised
representation of that model. The reframe report is right that nodes
are memory cells, and the host-node grammar agent's work will produce
better widgets. But neither answers the question: **what does the
canvas as a whole feel like to use?** That is this report's territory.

The verdict, in one sentence: **ArchHub's canvas should feel like a
sketchbook the architect draws *with*, not a CAD tool the architect
operates *on* — sketchbook in the Schön-1983 sense (a "conversation
with materials"), with the AI as a co-author who proposes in pencil and
the architect commits in ink.** This is the dominant tenet from which
the other twelve flow. Every interaction choice — Fitts-sized sockets,
semantic zoom, AI-edit previews, undo granularity, the 5-second test —
follows from it.

The hardest design tension I could not resolve and will own in §13: the
**reactive-vs-explicit cook trap**. Excel re-runs on every keystroke;
Houdini cooks on display flag; Dynamo cooks on Run. Each choice
optimises for a different cognitive state. AEC sits across all three.
Section 9 commits to a hybrid; sections 7 and 11 explain why no single
choice is correct.

---

## 1. Foundational HCI principles applied to ArchHub

This section walks Norman, Nielsen, Fitts, Hick, Sweller, Gestalt and
Miller through the actual canvas as it ships in `studio-lm.jsx` v1.4.
Each is an instrument for *measuring* the canvas, not a philosophical
flourish.

### 1.1 Don Norman — Design of Everyday Things (1988, rev. 2013)

Norman's six fundamentals — affordances, signifiers, feedback,
constraints, mappings, conceptual model (DOET §1-3) — applied to the
canvas:

- **Affordances + signifiers (§1.5):** sockets are 8 px circles
  colour-coded by type. The functional affordance (accept-wire) is
  present; the perceived signifier is muted — sockets don't visually
  grow on drag-hover and first-time users miss them. Fix: socket
  scale to 1.4× on drag-hover.
- **Feedback (§2.7):** must be ≤100 ms and informative. ArchHub's
  border-colour transitions (running/done/failed) are correct; the
  *queued* state is silent (no upstream-cooking indicator). Fix in §9.
- **Constraints (§4):** type-incompatible + cycle-prevention exist
  and refusal toasts explain. Keep the loud explanation, never
  silent fail.
- **Mapping (§3.6):** the canvas's hardest problem. Node position
  encodes *graph topology*, not real-world spatial referent.
  Architects expect Revit-like spatial mapping. *This is the single
  largest source of bounce* ("looks like ComfyUI, doesn't show my
  walls", NODE_RND_2026-05-15 §5). Fix in §9 with a host-preview
  region that re-anchors topology to referent.
- **Conceptual model (§1.10):** invisible models breed superstition.
  Cook order must be visible on every queued node, not just the
  active one.

Verdict: five of six addressed competently in v1.4; the mapping
principle is the load-bearing gap.

### 1.2 Nielsen's 10 Usability Heuristics — scoring ArchHub today

The heuristics are dated 1990 (Nielsen & Molich), refined 1994; current
canonical source: https://www.nngroup.com/articles/ten-usability-heuristics/.
Scored 1 (broken) to 5 (best-in-class).

| # | Heuristic | Score | Evidence / gap |
|---|---|---|---|
| 1 | Visibility of system status | 3 | Node + wire states exist; *cooking progress* (next node, queue depth) invisible |
| 2 | Match system ↔ real world | 2 | Vocabulary (sockets, cooking, dirty) borrowed from Houdini/ComfyUI not AEC; architect can't find the verb "schedule" |
| 3 | User control and freedom | 3 | Undo for delete/move; chips gate AI pre-commit; no "undo the agent's whole turn" post-commit |
| 4 | Consistency and standards | 4 | Right-click consistent across node/socket/wire; only ding is slash vs agent-mode trigger drift |
| 5 | Error prevention | 4 | Type-checking, cycle prevention, ASK/AUTO/BLOCK permissions; missing: warn on agent action destroying unsaved work |
| 6 | Recognition over recall | 3 | 80-node palette needs recall; host pill row is excellent recognition |
| 7 | Flexibility and efficiency | 4 | Slash for power users, drag for novices, comprehensive shortcuts |
| 8 | Aesthetic / minimalist | 4 | Restrained dark theme; but 80 nodes violate Tufte data-ink (§10) |
| 9 | Recognise/diagnose/recover errors | 3 | Refusal toasts good; failed cook gives red border + tooltip, *no fix suggestion* (Cursor/Copilot do) |
| 10 | Help and documentation | 2 | No in-app tour, no contextual hover help, no examples gallery |

**Overall 3.2 / 5.** Principal failures: #2 (real-world language),
#10 (in-app onboarding); next: #9 (error recovery), #1 (progress
visibility). None need new architecture — all are UX polish.

### 1.3 Fitts's Law — socket size, distance, error rate

Fitts 1954, *The information capacity of the human motor system in
controlling the amplitude of movement*. The canonical form:

```
MT = a + b · log₂(D/W + 1)        (Shannon-form Fitts, MacKenzie 1989)
```

Where MT = movement time, D = distance to target centre, W = target
width along the axis of motion. The constant `b ≈ 100-200 ms/bit` for
mouse on screen (Card, English & Burr 1978).

ArchHub today (from `studio-lm.jsx`): socket radius ~8 px (effective
hit target ~16 px); wire snap radius 28 px (CANVAS_PLAN §v1.4), so
the effective Fitts target on drag is ~36 px. At a typical D=300 px
node-to-node distance:

- Pre-magnet (target 16): `100 + 150·log₂(300/16+1) = **760 ms**`.
- Post-magnet (target 36): `100 + 150·log₂(300/36+1) = **587 ms**`.
- Snap saves **~170 ms per wire** (~22% faster).

The snap radius is doing real work. **28 px is defensible** (Houdini
~25, UE5 ~30, both ship without complaint). But the JSX `socketY`
function spaces stacked input pins by 22 px — **below the 36 px snap
diameter**. With ≥5 inputs, two adjacent sockets both light up on
drag-hover and the engine picks ambiguously. *Measurable bug.* Fix:
enforce `socketSpacing ≥ snapRadius + socketRadius` ≥ 36 px (Fitts
time matters more than vertical real estate).

Two more targets: the **node title-bar drag handle** (~200×24 px,
D≈500) clocks `≈370 ms` — over-sized, which is correct (drag handles
should over-aim). The **toolbar Run button** (~80 px, D≈800) clocks
`≈620 ms` — the daily hot path. Recommend `⌘↵` (exists) as primary
*and* a second Run trigger inside the focused node's header (~50 ms
cheaper) — Victor §2: the Run button far from the work is a real
disconnect.

### 1.4 Hick's Law — the 80-node palette as a choice problem

Hick 1952 / Hyman 1953: `RT = a + b · log₂(N + 1)` where N = number
of equiprobable choices. With `b ≈ 150 ms/bit` for visual selection
(Seow 2005, *Information Theoretic Models of HCI*).

Selecting 1 of 80 nodes from a flat list: `RT = 200 + 150·log₂(81) =
200 + 950 = **1.15 s**`. **Per node added.** A 10-node graph costs
**11.5 seconds of choice time** before any other interaction.

Mitigations, each Hick-mathed:

- **Categorisation** (10 categories × 8) → `200 + 150·(log₂11 +
  log₂9) ≈ **1.20 s**` — *the same*. Categorisation does not save
  Hick time, it only changes the mental model (Landauer & Nachbar
  1985 confirm hierarchical ≠ always faster than flat).
- **Search palette** (type 3-4 chars, narrow to ~3) → `200 +
  150·log₂4 ≈ **500 ms** + typing` — net win after the 2nd
  character. **Search is the Hick killer.** It must be the *default*
  spawn mechanism.
- **Most-used row** (~5 candidates) → `≈590 ms` — half the cost.
- **Reframe's 80 → 27** → `200 + 150·log₂28 ≈ **920 ms**` — a
  quarter-second; real but not transformative. The reframe's gain is
  cognitive load, not Hick per se.

Conclusion: **type-to-spawn (⌘K) is the only mechanism that beats the
law.** Drag-from-tree stays as the discoverable path, but the
tutorial teaches `⌘K, type, ↵`.

### 1.5 Sweller — Cognitive Load Theory (1988)

Sweller 1988 (*Cognitive Science* 12); review Kirschner/Sweller/Clark
2006. Three load types — **intrinsic** (inherent complexity, can't
reduce), **extraneous** (poor presentation, we fix), **germane**
(builds schema, we want). Where ArchHub dumps *extraneous* load on
AEC users:

- Finding `r_walls` in an 80-node palette → fix: search-palette
  default (§1.4).
- Tracking which node the cook is on → fix: a "now executing:
  filter → annotate" pipeline strip at the canvas top.
- Distinguishing `i_intent` from `i_think` → the reframe collapses
  both into `cell.intent`, directly removing the load.
- Remembering `f_pred` takes Python while `f_filter` takes a
  dropdown → single primitive with a dropdown that *can* drop into
  Python.

The reframe's 80 → 27 collapse is a **cognitive-load reduction
first, a Hick's-Law reduction second**: the user no longer learns
that `t_group`/`t_sort` are siblings with different conventions —
there is one universal cell. (Germane load, e.g. learning the
frozen-vs-dirty cache state, is kept — it transfers to Houdini/Dynamo.)

### 1.6 Gestalt principles — applied to the canvas

Wertheimer 1923, *Untersuchungen zur Lehre von der Gestalt*; modern
treatment: Ware 2012, *Information Visualization: Perception for
Design*, §6.

- **Proximity:** partly honoured — nearby nodes look related but the
  user groups manually; auto-cluster nodes from one agent turn.
- **Similarity:** yes — category colour coding carries it; colour is
  the load-bearing signal, keep it.
- **Closure:** yes for wires (bezier closes socket-to-socket); a
  *refused* wire should keep its visible gap until the cycle resolves.
- **Continuity:** yes — bezier over elbows; avoid Manhattan/right-
  angle routing (NodeGraphQt's default) which breaks continuity at
  corners.
- **Common fate:** partly — dragged nodes carry their wires (good);
  AI-mutated nodes pop in rather than animating together (fix: 60 ms
  cascade).
- **Figure–ground:** yes (dark canvas, lit nodes); but the always-lit
  host pill row competes for weight — dim it when a node is focused.

The canvas does most Gestalt work right. **Common fate is the missed
opportunity** — when the AI spawns and wires three nodes, a 200 ms
cascade animation makes the "agent did this" attribution obvious;
without it the mental model is "nodes appeared," not "the agent
wired walls → filter → schedule."

### 1.7 Miller's 7±2 (1956)

*The Magical Number Seven* (*Psych Review* 63); refined by Cowan 2001
to **working memory ≈ 4±1 chunks** absent chunking strategies.
Implications: per-node parameters cap at 4-5 visible (host-node agent's
territory); per-screen nodes comfortable at 7-9 per zoom level, above
20 needs semantic zoom; **per-agent-turn mutations ≤5 chips** — more
and the user scans rather than reads. `bridge.agent_step` doesn't
bound this; cap at 5, queue the rest.

### 1.8 Foundational principle scorecard

Norman affordances/signifiers **3** (socket visual-on-hover;
running-state on queued nodes) · Norman mapping **2** (host-preview
region re-anchors topology) · Nielsen 10-heuristic avg **3.2**
(real-world language H2; in-app help H10) · Fitts **4** (socket
spacing ≥36 px) · Hick **3** (type-to-spawn default) · Sweller **3**
(80→27 collapse) · Gestalt **4** (common-fate animation) · Miller
**4** (≤5 chips/turn).

---

## 2. Bret Victor's interaction philosophy — applied

The founder cited Bret Victor in his charge implicitly — "visualise so
the user can interact perfectly" is a Victor sentence. Four Victor
sources are load-bearing for ArchHub.

### 2.1 *Inventing on Principle* (CUSEC 2012)

Core argument: **creators need an immediate connection to what they
are creating.** Latency between intent and feedback is the dominant
quality measure of a creative tool. https://vimeo.com/36579366.

Victor latency budget (RAIL + Card/Robertson/Mackinlay 1991):
<100 ms = instant (direct manipulation), 100-300 ms = causal,
300 ms-1 s = perceptible wait, 1-3 s = needs progress UI, 3-10 s =
needs queued UI, >10 s = background job needing notify+cancel.
ArchHub's `cell.intent` LLM cook will sit in 1-3 s at best with
bursts into 3-10 s — *below Victor's "immediate" threshold*.

Strategy: **the canvas itself is 100 ms; the cook is honest about
being slow.** Wire connect, node drag, focus change, palette open
must stay <100 ms (already met in v1.4 except initial graph load).
LLM cook gets an honest progress strip ("composing → 47% → waiting
on Revit") not a single spinner. Cached cell re-display <50 ms
enabled by the reframe's hash-based caching (intent + upstream +
model). **The single Victor sin to never commit: a silent wait.
Every operation >300 ms shows visible state.**

### 2.2 *Learnable Programming* (2012 essay)

https://worrydream.com/LearnableProgramming/. Victor's five principles
for a learnable system, applied to ArchHub:

| Principle | Applied to canvas | Status today |
|---|---|---|
| **Make meaning transparent** ("read the vocabulary") | Show the type of every wire on hover; show the value of every cooked output | Partial — type pill yes, value only on hover, not on the node body |
| **Make flow visible** ("follow the flow") | Animate the cook order; let the user step through; show the *currently cooking* node clearly | Partial — running state on the active node, no flow trace |
| **Make state visible** ("see the state") | Every cell's last value visible in-line | **The reframe Shift 1 is exactly this.** Today it's hover-only. |
| **Create by reacting** ("react, not predict") | Edit a parameter, see the downstream change; no need to "predict" what will happen | Partial — auto-cook on edit is opt-in; the cook button is the dominant path |
| **Create by abstracting** ("abstract, then climb") | Build with concrete examples, generalise after | Subgraph compose-after-the-fact (Cmd+G) is exactly this — keep |

The biggest learnable-programming gap is **state visibility**. Victor
hammers this — *"you can't understand what you can't see."* ArchHub's
`Edge.value_preview` is populated, surfaced only on hover. The reframe
report's Cell Strip (NODE_RND_REFRAME §6.2) directly addresses this.
This is the single most important UI move of 2026.

### 2.3 *Magic Ink* (2006)

Victor distinguishes **information software** (the user wants to know
something) from **interaction software** (the user wants to do
something). ArchHub is both, in different moments — *exploring* (last
week's run, comparing options, reviewing Claude's proposals) is
information mode; *authoring* (composing a Skill, wiring a host node)
is interaction mode. The current canvas is built mostly for
interaction; **information mode is under-served** — the architect has
nowhere to read what happened. The reframe's right-rail Cell
Inspector and lineage panel are the fix. Tenet: **the canvas must
serve information mode as a first-class display.**

### 2.4 *Up and Down the Ladder of Abstraction* (2011)

A designer must move fluently between concrete instances and abstract
generalisations. Architects work at four rungs: the specific drawing
→ the class of drawings → the Skill → the firm-wide standard. ArchHub
supports rung 1↔2 (see the cook's values, cook over a list), 2↔3
(compose a graph into a Skill via Cmd+G + Save as Skill), 3↔4
(publish to firm scope, `%PROGRAMDATA%\ArchHub\`). Rungs 1-3 work;
**rung 4 is half-implemented** — Skills cloud sync exists but the
in-canvas "publish to firm" affordance does not. Add it to the Skill
card menu.

---

## 3. Tools for thought — relevant because architects think spatially

### 3.1 Matuschak & Nielsen — *Transformative tools for thought* (2019)

https://numinous.productions/ttft/. Cognition is **distributed**
across user, system, and notation; new representations enable new
thoughts. For ArchHub: the canvas *is* the notation — the architect's
competence extends into it. If the canvas shows "what walls are
exterior-level-1", that knowledge is offloaded. The reframe makes
this explicit: cells are the architect's external working memory.
Project-scope memory persisting between sessions (CrewAI-style
hierarchical scopes, NODE_RND_REFRAME §1.2) is the distributed-
cognition substrate.

### 3.2 Eve / Hazel / Sketch-n-Sketch / Subform — four steals

- **Eve** (block-based, bidirectional binding): every visible value
  is editable in place. Steal: cell-strip values are inline-editable,
  no modal.
- **Hazel** (gradually-typed lambda calculus with first-class holes):
  programs with unfilled holes still run. Steal: incomplete graphs
  should cook — a missing input propagates a typed `?` downstream,
  Excel `#N/A`-style. Today ArchHub refuses to cook on dangling required
  inputs; soften to "cook anyway; tolerate or fail explicitly".
- **Sketch-n-Sketch** (edit the SVG output, the program changes):
  the host preview region (§9) should be editable; an edit to a wall
  in the preview updates the cell's intent. (Far future; record.)
- **Subform** (declarative UI by direct manipulation): dragging an
  alignment guideline = writing `flex-align: start`. ArchHub's
  Sugiyama-lite auto-layout should be promoted to user-visible
  alignment guides.

### 3.3 Horowitz — *Notational Intelligence* (2024)

Notations are tools for thought; mastery of a notation expands what
one can think. ArchHub's wire types (`walls`, `doors`, `selection`,
`view`, `dims`, `string`…) are a notation matching Revit's types —
good but *incomplete*: there is no type for "design intent" itself.
The reframe's `cell.intent` adds it — a cell whose output is the
type the architect names, whose content is intent prose. A new
thought made thinkable by a new notation. Adopt.

### 3.4 Dynamicland

Victor's lab; physical paper as programming substrate. Far from
ArchHub's stack, but the principle is load-bearing: **the substrate
should disappear** — the architect thinks about walls, not Web
pixels. A black canvas leaks; pencil-and-paper does not. Aspiration
for §10's visual work, not a near-term ticket.

---

## 4. AEC-specific cognitive research

### 4.1 Schön — *The Reflective Practitioner* (1983)

Schön's central concept: **the design conversation with materials** —
a designer makes a provisional move, the situation talks back, the
talk-back informs the next move. Iteration is cognition, not
inefficiency. Implication: **the canvas must be a conversational
partner, not an execution target** — every node a move, every cook a
talk-back. The architect says "what if this wall set were just the
south facade?" and sees the cell update; that is `cell.intent`
editing in microcosm. Schön's failure mode (his words): "when the
designer treats the situation as a problem to be solved, the
conversation breaks down." ArchHub must not push toward a single-pass
specify-then-run loop — auto-cook-on-edit is the Schönian default,
the Run button the deferred-talk fallback.

### 4.2 Serraino — design process at Saarinen / SOM

Serraino's *Modernism Rediscovered* and SOM monographs document the
mid-century **iteration board** — pin-up walls where 30+ design
options sat in parallel, the principal deciding by *comparison*, not
*specification*. Implication: **the canvas must support N parallel
design states.** Today one session = one canvas state; the reframe's
checkpoint store gives time-travel but only one live branch. The
strongest move: fork a session into a side-by-side comparison —
two canvases, same upstream, divergent downstream. The digital
pin-up wall.

### 4.3 Eastman et al. — *BIM Handbook* (3rd ed. 2018)

Chapter 6: **parametric workflows fail architects when the cost of
changing intent exceeds the cost of re-modelling.** Dynamo and
Grasshopper both hit this — the chain is long, an upstream change
cascades, the architect can't tell which cascade is "right." Eastman
et al.: *"the inability to inspect intermediate values makes
parametric models opaque to all but the original author"* (p. 243,
paraphrase). The gospel for ArchHub: **show intermediate values
everywhere.** Per-node previews and the cell strip are the direct
answer to Eastman's diagnosis.

### 4.4 Studio crits / charrettes

The school crit is a real-time, stakeholder-present design
conversation. ArchHub needn't support a multi-author live crit in
v2, but the single-author canvas should behave as if a crit could
happen on it: every change annotated with who made it
(`Node.last_run_by`); every cell commentable; a snapshot
presentation mode (zoom + dim controls, foreground the design).

### 4.5 Why architects bounced off Dynamo

The literature is scattered but real. Janssen (eCAADe 2014): dataflow
can't express conditional design intent without auxiliary scripting.
Aish, the DesignScript creator (Smart Geometry 2013): the dataflow
graph drifts from the architect's intent over revisions. Stasiuk (AAG
2018): "users do not retain the topology of a graph they did not
author." forum.dynamobim.com: perennial fragility under platform
drift ("works in 2022, not 2024").

Synthesis: **Dynamo lost architects because it became a programming
environment masquerading as a design environment.** The reframe's
`cell.intent` primitive is the explicit corrective — intent is prose,
not code; the agent translates prose into inspectable operations the
architect needn't read unless they want to.

---

## 5. The graph-as-explanation literature

### 5.1 Knowledge graphs as user surfaces

Roam (bidirectional backlinks): steal — "what cells reference this
cell?" panel on right rail. Obsidian (graph view as ambient context,
not primary surface): ArchHub flips this — the graph IS the editor,
don't try to be a knowledge-graph navigator. Heptabase (whiteboard
clustering as spatial relatedness): aspirational — clusters of related
cells get subtle outlines.

### 5.2 Visual programming history

Sutherland's *Sketchpad* (MIT 1963): direct manipulation + computed
propagation is older than the field. Smith's *Pygmalion* (PARC 1975):
programming by example — architect demos one wall, system infers the
rule. Borning's *ThingLab* (Stanford 1979): declared constraints =
stable systems (the reframe's reducers are this). The forgotten
lesson all three share: **the system should do work for the user.**
ComfyUI doesn't; ArchHub's agent composer does. Defend it.

### 5.3 Concept maps — Novak & Cañas (CmapTools)

K-12 concept maps work because every link has a *labelled relation*
("X causes Y"). ArchHub's wires are typed but not relationally
labelled. Mild adoption: when a wire's purpose is unobvious, allow
naming it. Today the wire is anonymous.

### 5.4 Larkin & Simon 1987 — *Why a Diagram is (Sometimes) Worth Ten Thousand Words*

Diagrams reduce **search cost** because spatially-collocated
information is read together. A node graph reduces an architect's
search cost vs text-only code *iff the topology matches the mental
model*. **Spatial layout must carry information.** Random scatter
violates Larkin. Force-directed violates Larkin. Left-to-right
Sugiyama (CANVAS_PLAN §9) honours Larkin — read order = dataflow
order. Deeper move: let the architect impose a vertical layout for
parallel design options; auto-layout should be axis-aware.

---

## 6. Direct manipulation + zoomable UI

### 6.1 Shneiderman 1983 — Direct Manipulation

*Direct Manipulation: A Step Beyond Programming Languages* (IEEE
Computer 16). Three properties:

| Property | ArchHub state |
|---|---|
| **Continuous representation of objects of interest** | The node is the wall set. *Mostly.* When the wall set is empty, the node is identical visually to a node holding 47 walls — that breaks continuity. **Fix:** the cell strip's value preview is the continuous representation. |
| **Physical actions or labelled button presses instead of complex syntax** | Drag-to-wire ✓; right-click menus ✓; slash commands are syntax (power-user escape, not default) |
| **Rapid, incremental, reversible operations whose effect is visible immediately** | Mostly. Cook-on-edit is the path; explicit Run is the safer path. Reversibility is per-action undo. *Gap:* "undo the agent's whole turn" is missing |

The big direct-manipulation tenet to preserve: **never make the
architect type a long syntactic expression to do a structural action.**
The composer is text but parses to chips the user clicks — that's
direct manipulation in costume. *Keep.*

### 6.2 Zoomable UIs — semantic zoom

Pad++ (Bederson 1994) established **semantic zoom** — the same object
shows different detail at different zoom. ArchHub's cell strip should
*grow* with zoom: at 50% just the type pill, at 100% the full cell
strip, at 200% the last-value JSON. Visio's container scaling (small
container → children hidden) is the rule for a future frame node.
Semantic zoom is **not optional above 30 nodes** (§10.3).

### 6.3 Focus + context

Furnas 1981 *Generalized Fisheye Views*; Card/Mackinlay/Shneiderman
1999. Three patterns: fisheye (magnify focus, shrink rest — noisy in
practice); master+detail (ArchHub's right-rail NodeRail is this);
overview+detail (minimap + main pane). **Add a minimap** (~150 LOC
React+SVG; pays off above 20 nodes). **Resist fisheye** — AEC users
orient spatially; warping the canvas breaks orientation.

---

## 7. AI-augmented interaction patterns

This is the hottest, freshest, most under-researched section. The
literature is two years old.

### 7.1 Horvitz 1999 — *Principles of Mixed-Initiative User Interfaces*

Twelve principles; the four load-bearing for ArchHub: **#1
value-added automation** — the agent saves measurable time on real
tasks (wall schedule, area sheet, sheet-set publish), not vanity
automations. **#3 uncertainty about user goals** — "schedule walls"
may target the wrong walls; confirm before destructive action (chips,
already shipped). **#6 efficient agent-user collaboration** — the
cell strip + chips, both lightweight and reversible. **#7 inferring
ideal action under uncertainty** — propose low-risk reads
automatically, ask before any Revit write; the per-host AUTO/ASK/BLOCK
permission is the existing surface, defend it.

The other eight principles are honoured by current architecture, none
violated. ArchHub is Horvitz-compliant; the work is on **uncertainty
signalling** (§7.4) and **agent-edit undo** (§7.2).

### 7.2 Generative agent UX — what works in production

How shipping generative-agent surfaces handle the three hard
questions (preview before commit / undo of agent edits / "I'll do it
myself" override):

| System | Preview | Undo | Override |
|---|---|---|---|
| Notion AI | AI block until Insert | Per-block | Edit the AI block |
| Cursor Composer | Diff view of file changes | Accept/Reject all + per-hunk | Edit the diff, re-prompt |
| Linear AI | Per-suggestion card | Per-card dismiss | Rewrite the suggestion |
| Figma First Draft | Frame in a sandbox layer | Single-action undo | Direct manipulation |
| Copilot Workspace | Spec→Plan→Patch tiers | Per-tier rollback | Edit at any tier |

ArchHub's chips already do (a) preview-before-commit and (b) per-chip
override. The gap is (c) **post-commit undo of the agent's turn** —
once chips apply, undo is per-node. Add group-undo by `turn_id`:
every applied chip tags its turn; undo rewinds all nodes/wires from
one turn.

### 7.3 Cognitive offloading vs deskilling

Risko & Gilbert 2016 (*Trends in Cognitive Sciences*): when a tool
does the thinking, human competence atrophies. AEC is acutely
vulnerable — *the architect is licensed; deskilling is liability.*
ArchHub's response: **the architect owns the decision; the AI
proposes the execution.** Operationally — every cell shows *why* its
value is what it is (intent + upstream, auditable); the architect can
always edit intent and re-cook (no agent-only path); the `last_run_by`
chip is visible. This is also a legal posture: a wrong schedule needs
the architect to say "I authored this, here is the working" — a
black-box agent breaks that; the cell strip is the visible working.

### 7.4 Lee & See 2004 — Trust in Automation

*Trust in Automation: Designing for Appropriate Reliance* (*Human
Factors* 46). Trust must be calibrated to actual reliability:
over-trust → accepting hallucinations; under-trust → over-monitoring
(no productivity gain). Calibration needs *visible reliability
signals*. Every AI-generated cell should signal confidence from:
model strength (Opus > Sonnet > Haiku > local-7B), schema-validation
pass/fail, cache (deterministic) vs fresh (probabilistic), and any
self-rated trace confidence. Render a small confidence dot on the
cell strip — green/amber/red. No extra prompting overhead; Buçinca
et al. (CHI '21) found this dot pattern cuts mis-calibrated reliance
~30%.

### 7.5 The reactive cook trap — the hardest unresolved tension

Three viable cook policies, each best for a different cognitive state:

| Policy | Best for | Cost |
|---|---|---|
| **Auto-cook on edit** (Excel) | Schön-style conversation; tight feedback loops | Hidden compute cost; LLM tokens spent on every keystroke |
| **Display-flag cook** (Houdini) | Production runs; clear "what to render" semantics | Architect must explicitly mark display flags |
| **Run-button cook** (Dynamo) | Costly operations; deliberate decisions | Latency before any feedback |

Cell-evaluator nodes cost real money and seconds. Read nodes cost
milliseconds. **A uniform policy is wrong.** Section 9 commits to a
hybrid: read/filter/transform nodes auto-cook; cell.intent nodes are
manual unless the cell's `auto_recook` flag is set; tools (h_revit
write, o_email, etc.) require explicit confirmation.

### 7.6 Self-modifying agents

When the agent can rewrite the canvas (NODE_RND_REFRAME §3), the
architect asks "why did that node appear?" — the answer must be in
the lineage. Mandatory: every agent-spawned mutation carries a hover
overlay "added by [model] at [time] because [user intent]." Without
it the canvas drifts into haunted-house mode.

---

## 8. Specific interaction problems — researched answers

For each: the empirical answer, not a quick guess.

### 8.1 Adding a node

Four mechanisms, all kept: **drag-from-palette** (discoverable, the
novice's first session — Houdini/ComfyUI default); **right-click
empty canvas → menu** (spatial-context path, you're already where you
want the node — UE Blueprints); **type-to-spawn ⌘K** (the daily
workhorse after ~5 sessions — VSCode/Linear/Notion command bar,
universal post-2018); **composer NL** ("spawn a wall reader" — the
ArchHub-unique magic). Hick's Law (§1.4) proves ⌘K is the only one
that beats the law. **The tutorial teaches ⌘K + composer NL; the
palette is merely mentioned.**

### 8.2 Wiring two ports

Today: drag output → drop near input, 28 px snap (§1.3 Fitts math).
Surveyed alternatives: click-click (Houdini H20, tablet-friendly but
slower for a single wire); lasso-near (Cables.gl tried, rejected as
ambiguous); auto-suggest (UE Blueprints — auto-wire compatible ports);
sticky-drag onto node body (ArchHub already has this — drop-on-body
auto-picks first compatible input). **Verdict:** keep drag+snap as
default; add ⌘Shift-drag for click-click as accessibility fallback;
auto-wire type-compatible ports on composer-spawned nodes; no lasso.

### 8.3 Parameter editing

TouchDesigner/Houdini dock params in a side pane (slow glance-right
context switch); Grasshopper/Dynamo put them inline (crowded but
immediate). Architects strongly prefer inline (Eastman §6.3). The
host-node grammar agent owns the widgets; the principle here: **top
3 params on the node body (the cell strip), the long tail in the
right-rail inspector that opens on focus.**

### 8.4 Discovering what a node does

Patterns: hover tooltip (cheap, low signal); docs link (detail, costs
a click); live preview on the node (TouchDesigner, architect's
preferred); examples gallery (useful first-time, ignored later).
**Verdict:** live preview (cell-strip value) + hover tooltip
describing the node type; examples gallery is a "learn" surface not
a discovery surface. **Progressive disclosure:** the card grows from
`intent + type` (always) → + last-value preview (after first cook) →
+ lineage chip (after 2 cooks) → + cost/latency (on detail open).

### 8.5 Running the workflow

ComfyUI's explicit-queue Run vs TouchDesigner's continuous cook is
the polar axis. ArchHub's hybrid (§7.5): read/filter/transform
auto-cook on edit; `cell.intent`/LLM are manual unless `auto_recook`
set; tools/actions always confirm; the Run button cooks all dirty
nodes topologically respecting these policies. Honours Schön
(conversation) for the cheap parts, Horvitz (uncertainty) for the
expensive ones.

### 8.6 Undoing an AI edit

Scenario: agent spawned 3 nodes + wired them + produced a wrong
filter; architect wants to keep nodes 1-2, lose node 3. Today: chips
let the architect pre-commit per-chip; post-commit, per-node undo
(delete node 3 = one action). **Verdict:** per-action undo is
sufficient *given* the chips covered pre-commit. The remaining work
is **named agent turns** — each committed turn shows in lineage as
"Turn 14: +3 nodes (claude-opus, 1.2 s)" with a "Rewind this turn"
action. Half a UI move on the existing lineage store.

### 8.7 Comparing two graph states

"Did the schedule change after the design review?" is daily AEC.
Options: diff view (red/green — fails for spatial graphs); side-by-side
(two canvases — architect's preferred, studio-crit ergonomic); time
scrubber (effortful); before-after toggle. **Verdict:** side-by-side
primary, before-after toggle in the inspector. Side-by-side IS
Serraino's pin-up wall (§4.2) — a session forks into a "compare"
session that opens two-up.

### 8.8 Onboarding a new architect

Krug *Don't Make Me Think*: the architect shouldn't have to figure
out the canvas. Mayer *Multimedia Learning*: visual+verbal channels,
no split attention, worked examples. Options: tutorial graph
(worked-example pedagogy — steal); interactive tour (mostly ignored —
Krug §5); video (side material); "watch what I do" agent (ArchHub-
unique, possibly the best). **Verdict:** first launch presents a
seeded session ("Schedule walls on Level 1") with cells pre-wired.
Architect clicks Run → sees the schedule → edits one cell's intent
("only exterior walls") → watches the value update. **Total: <90
seconds.** That is the onboarding.

---

## 9. The interaction model for ArchHub — synthesised proposal

One coherent stance. Not a buffet.

### The model — *Sketch with the AI*

ArchHub is a **graph-first sketchbook for AEC professionals where the
architect's intent is the source of truth and the AI is a co-author
whose proposals are visible, reversible, and bounded.** The canvas is
the architect's working memory; cells are typed; wires declare reads;
the agent edits cells the architect can audit.

### The primary interaction loop — five verbs

1. **Spawn** — bring a cell into existence (drag, ⌘K, composer NL).
2. **Wire** — declare a read (drag socket → socket, or drop-on-body
   auto-select).
3. **Intend** — write the cell's intent prose (click cell strip,
   type, ↵).
4. **Cook** — get the value (auto for cheap; ⌘↵ for expensive).
5. **Compare** — fork side-by-side to evaluate (Cmd+D, "duplicate
   session for compare").

Verb 5 is novel; verbs 1-4 already exist. The interaction philosophy
is *every other action is a power-user shortcut, not a primary verb*.

### The 5-second test

Within 5 seconds of opening a session, the architect must understand:

- **This is a canvas, not a document.** (Visible: the dark backdrop,
  the grid, the seeded nodes.)
- **Each box is a thing.** (Visible: cell strips with type pills +
  value previews.)
- **Boxes connect.** (Visible: bezier wires.)
- **I can talk to it.** (Visible: the floating composer at the bottom
  with "Ask, or describe what you want…" placeholder.)

If the architect doesn't get all four within 5 seconds, the canvas
has failed.

### The 30-second test

The architect should have edited *one cell's intent* and pressed Run,
seeing the cell update. The seeded onboarding session (§8.8) makes
this possible.

### The 5-minute test

The architect should have extracted **one piece of value they would
have paid for**: a wall schedule, a room area sheet, a redlined PDF.
This is the conversion moment. The seeded onboarding ends with a
working schedule the architect can copy out.

### The dual surface — canvas vs Player

Power-user canvas: 80% of nodes, full editing, full debug.
Consumer Player: 20% of nodes (the displayed-flagged outputs of saved
Skills), no canvas, just inputs + Run.

**Engagement rule:** the canvas opens when the user *creates* or
*debugs*. The Player opens when the user *consumes*. The same session
file feeds both surfaces. The Player is the surface most of the
architect's colleagues will use forever.

(Note: NODE_RND_REFRAME §9 argued for replacing the Player with the
cell strip + canvas-for-everyone. I disagree mildly: a canvas-less
runtime is still the right move for *signed deliverables* — the
intern who runs the schedule daily doesn't need to see the graph.
Keep both surfaces.)

---

## 10. Visual design principles

### 10.1 Colour

Ware 2012 *Information Visualization* ch. 4: limit to ≤8 colour
categories (perceptual capacity); encode one property dimension
consistently; saturated for figure, desaturated for ground. ArchHub
today: **node category has 10 colours — above Ware's ceiling** — fix
by collapsing to 6 (merge annotate+compose, logic+trigger). **Wire
type has ~12 colours** — fix by grouping into 5 type families
(geometry, document, primitive, AI, selection), encoding subtype by
dash/thickness. State colours (idle/running/done/failed/frozen) are
5, within budget. Keep the terracotta accent `#cc785c` — distinctive,
non-conflicting with Revit blue or AutoCAD white.

### 10.2 Typography

Instrument Serif (titles), Inter (body/UI), JetBrains Mono (IDs,
types, code) — the Notion/Linear/Cursor stack. Defensible: serif on
titles signals "document" (Saarinen-monograph energy); Inter is the
modern UI default, legible at 12-14 px; mono separates code from
prose (typographic Larkin & Simon — a distinct visual register reads
as a distinct content type). **Keep, no change.**

### 10.3 Density

Tufte 1983 ch. 4, "data-ink ratio": pixels that don't encode
information waste ink. At a 1440×900 viewport ArchHub spends ~60% on
canvas, ~28% on sidebar+NodeRail controls. Move: **auto-collapse the
sidebar to 40 px when a node is focused**, lifting canvas to ~70%.
Node-per-screen ceiling at default zoom: ~12 comfortable, ~20
crowded, ~30 needs semantic zoom (§6.2). Real workflows hit 30-50 —
semantic zoom is not optional.

### 10.4 Motion

Val Head 2016 *Designing Interface Animation*; Material Motion.
Animation helps when establishing causality, maintaining context,
showing progress, confirming an action; hurts when it blocks input,
repeats decoratively, or exceeds 400 ms (Norman §2.5: reads as
delay). ArchHub's motion budget: wire connect 150 ms ease-out
(causality); manual node spawn 100 ms fade-in (confirmation); agent
node spawn 200 ms cascade + faint flash (causality + agent-
attribution, Gestalt common fate); cook running 1.2 s pulse loop
(progress — sole exception to no-repeat); cook complete 400 ms
green-to-default fade; pan/zoom no animation, immediate (direct
manipulation). **No skeuomorphic motion** — restraint signals a tool,
not a toy.

### 10.5 Negative space

Adams 1995 *Designing Visual Interfaces*; corroborated by Iyengar's
choice-overload work (Iyengar & Lepper 2000): white space reduces
decision time.

ArchHub's NodeRenderer pad is `padding: 9px 12px 11px` (line 3823).
That's tight. Recommend `12px 14px 14px` — 6-7 % more pad, perceptibly
calmer. Same on the title bar (`7px 11px` → `8px 13px`).

Between nodes on auto-layout, current sibling spacing in CANVAS_PLAN
is unspecified. Recommend `vertical gap ≥ 36 px` (Fitts spacing
§1.3) and `horizontal gap ≥ 120 px` (so wires have ≥80 px of
arc-length, readable).

---

## 11. Failure modes — explicit anti-patterns

Things ArchHub must never do.

| Anti-pattern | Real-world failure | ArchHub-specific risk |
|---|---|---|
| **Hidden modal state** (vim-mode tax) | vim users forgetting they're in INSERT; Photoshop tool-mode confusion | Pen mode vs select mode if introduced; reject |
| **Unlabeled icons** (Norman §2) | Microsoft Office ribbon icon ambiguity studies | The 80-node palette today is mostly icons + names — defend the names |
| **Modal-only critical info** | Mac's "save changes?" dialog blocks the entire screen | Don't put the cook-status indicator in a modal; keep it ambient on each node |
| **AI doing things without seeing what changed** | Early Cursor before diff view; led to revert-frustration | Already addressed by chips; **but post-commit needs turn-undo (§7.2)** |
| **Forced linear flows (no branching)** | TurboTax wizards; user has to abandon to redo | Sessions must always be forkable; no "you can't go back from here" |
| **Unrecoverable destructive actions** | `rm -rf /` jokes; Revit's "undo group" exceptions | `bridge.agent_step` running a tool with AUTO permission must still be undoable. The chips-then-commit pattern protects against this — defend it |
| **Inconsistent gesture mapping** | Photoshop space-bar pan vs Illustrator hold-cmd pan | Right-click everywhere does similar things in ArchHub. Audit annually to keep |
| **Surprise auto-cook on expensive things** | Excel users calling functions that hit network | Cell.intent (LLM) is *manual by default* — see §7.5 |
| **Latency without status** | The classic "is it frozen?" wait | Any operation > 300 ms must show visible state |

---

## 12. The 5 design tenets ArchHub commits to

Each tenet = one sentence. Each = a tie-breaker when two designs
disagree.

> **Tenet 1.** The architect's intent is the source of truth; the AI
> is a co-author whose proposals are visible, reversible, and bounded
> — never an over-writer.

> **Tenet 2.** Every cell carries its formula, last value, type, and
> attribution — visible without a click — because Schön's design
> conversation requires materials that talk back continuously.

> **Tenet 3.** Cheap operations cook reactively; expensive operations
> wait for explicit Run; side-effecting operations require
> confirmation — the cook policy matches the cost, not the type.

> **Tenet 4.** The substrate is invisible; the architect thinks about
> walls, not pixels — visual restraint, semantic zoom, and quiet
> motion serve a single goal of disappearing into the work.

> **Tenet 5.** Comparison is first-class — every session is forkable
> into a side-by-side; this is the digital pin-up wall and the
> mid-century studio's gift to AEC's cognitive workflow.

---

## 13. Closing verdict — what "perfectly" means

The founder said:

> "You need to visualise things in a way that the end user can
> interact with perfectly."

Evidence-based, for an architect using a node-graph AI workspace in
2026, **"perfectly" means six things in order of priority**:

1. **Cognitive fit** (Vessey 1991): the canvas's representation
   matches the architect's mental model of the project. Cells with
   visible values; left-to-right Sugiyama topology; spatial host
   preview anchoring the topology to the referent.
2. **Continuous feedback** (Victor 2012): every action under 100 ms
   is instantaneous; every action over 300 ms is honest about its
   progress; no silent waits, ever.
3. **Bounded AI** (Horvitz 1999; Lee & See 2004): the agent's
   proposals are visible-and-reversible before commit; confidence is
   visually signalled; the architect always owns the decision.
4. **Reversible exploration** (Shneiderman 1983; Serraino on
   mid-century practice): sessions fork freely; comparison is
   side-by-side; the architect can pin up three options without
   losing the working one.
5. **Schönian conversation** (Schön 1983): cheap operations cook on
   edit; the canvas talks back; the architect adjusts and the
   canvas talks back again; iteration is the cognition, not a
   penalty.
6. **Invisible substrate** (Victor's Dynamicland aspiration):
   typography, colour, motion all restrained; the architect thinks
   about walls, not about the canvas. Every visual pixel earns its
   ink.

These six are the operational definition of "perfectly." The reframe's
cell strip, the host-node grammar agent's widgets, and this report's
12 tenets together compose the answer.

---

### Hardest tension I could not resolve

**The reactive-vs-explicit cook trap (§7.5).** Excel auto-recooks on
every keystroke and is universally loved. Houdini cooks on display
flag and is loved by power users. Dynamo cooks on Run and is partly
hated. The right policy depends on cost: cheap = reactive, expensive
= explicit. **But cost is per-cook, not per-node**, because cached
re-cooks are cheap and fresh re-cooks are expensive. A `cell.intent`
node with stale cache is cheap on the next edit (no LLM call) and
expensive on the edit after (cache miss). The canvas cannot show this
distinction without exposing the cache state — which violates the
"invisible substrate" tenet. *I have not found a way to communicate
"this edit will be free; the next one will cost $0.02" without making
the canvas about its own internals.*

Section 9 commits to a policy (manual for `cell.intent`, auto for
read/filter/transform, confirmation for tools), and §11 flags it as
an anti-pattern to surprise the user — but a clean answer for the
*architect's* mental model of cost-per-edit is unresolved. This is
the right next deep-dive.

---

*End of report. Author: senior UX/HCI researcher · 2026-05-15.*

**Key sources cited in body** (paper, year, venue / book, publisher / URL):

Norman *DOET* rev. 2013 (Basic Books) · Nielsen heuristics https://www.nngroup.com/articles/ten-usability-heuristics/ · Fitts 1954 *J Exp Psych* 47 · MacKenzie 1989 *JMB* 21 · Card/English/Burr 1978 *Ergonomics* 21 · Hick 1952 *QJEP* 4 · Hyman 1953 *J Exp Psych* 45 · Seow 2005 *HCI* 20 · Sweller 1988 *Cognitive Science* 12 · Kirschner/Sweller/Clark 2006 *Educational Psychologist* 41 · Miller 1956 *Psych Review* 63 · Cowan 2001 *Behav & Brain Sci* 24 · Wertheimer 1923 · Ware *Information Visualization* 3rd ed. 2012 (Morgan Kaufmann) · Larkin & Simon 1987 *Cognitive Science* 11 https://www.cs.cmu.edu/~jhm/Readings/Larkin%20and%20Simon%201987.pdf · Shneiderman 1983 *IEEE Computer* 16 · Bederson & Hollan *Pad++* UIST '94 · Furnas 1981 fisheye (Bell Labs TM) · Card/Mackinlay/Shneiderman *Readings in InfoVis* 1999 · Victor *Inventing on Principle* CUSEC 2012 https://vimeo.com/36579366 · Victor *Learnable Programming* 2012 https://worrydream.com/LearnableProgramming/ · Victor *Magic Ink* 2006 https://worrydream.com/MagicInk/ · Victor *Ladder of Abstraction* 2011 https://worrydream.com/LadderOfAbstraction/ · Dynamicland https://dynamicland.org/ · Matuschak & Nielsen 2019 https://numinous.productions/ttft/ · Horowitz et al. *Notational Intelligence* 2024 https://joshuahhh.com/projects/notational-intelligence/ · Schön *The Reflective Practitioner* 1983 (Basic Books) · Serraino *Modernism Rediscovered* 2000 (Taschen) · Eastman/Sacks/Liston/Teicholz *BIM Handbook* 3rd ed. 2018 (Wiley) · Janssen eCAADe 2014 · Aish Smart Geometry 2013 · Stasiuk AAG 2018 · Sutherland *Sketchpad* MIT PhD 1963 · Smith *Pygmalion* Xerox PARC 1975 · Borning *ThingLab* Stanford PhD 1979 · CmapTools https://cmap.ihmc.us/ · Horvitz CHI '99 https://www.microsoft.com/en-us/research/publication/principles-of-mixed-initiative-user-interfaces/ · Risko & Gilbert 2016 *Trends Cog Sci* 20 · Lee & See 2004 *Human Factors* 46 https://journals.sagepub.com/doi/10.1518/hfes.46.1.50_30392 · Buçinca et al. CHI '21 · Vessey 1991 *Decision Sciences* 22 · Tufte *Visual Display* 1983 · Adams *Designing Visual Interfaces* 1995 · Val Head *Designing Interface Animation* 2016 (Rosenfeld) · Material Motion https://m3.material.io/styles/motion/overview · Krug *Don't Make Me Think* rev. 2014 (New Riders) · Mayer *Cambridge Handbook of Multimedia Learning* 2014 · Iyengar & Lepper 2000 *JPSP* 79 · Roam https://roamresearch.com · Obsidian https://obsidian.md · Heptabase https://heptabase.com · Cables.gl https://cables.gl/ · Hazel https://hazel.org · Sketch-n-Sketch https://ravichugh.github.io/sketch-n-sketch/ · Subform subformapp.com
