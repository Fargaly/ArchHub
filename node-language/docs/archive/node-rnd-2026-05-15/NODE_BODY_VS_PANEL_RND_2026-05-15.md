# Node Body vs. Property Panel — the Three-Way Split

> Author: senior interaction-design researcher · ArchHub · 2026-05-15.
> Brief: founder correction of 2026-05-15. Supersedes the "everything on
> the node body" stance of `docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md` §2.2
> and that doc's §7 pushback item #2 ("no right-side panel"). Refines
> `docs/NODE_RND_REFRAME_2026-05-15.md` (cells-as-memory) and is governed
> by the five tenets of `docs/NODE_INTERACTION_UX_PRINCIPLES_2026-05-15.md`.
> Companion code: `app/web_ui/studio-lm.jsx` (`NodeRenderer` L3778,
> `HostBody` L3934, `AIBody` L3946, `NodeRail` L4957, `FullParam` L5318),
> `app/workflows/graph.py` (`Node` L108, `Port` L78, `PortType` L26).

---

## Executive summary (read this first)

1. **The host node body must shrink, not grow.** Houdini, Fusion, Nuke and
   Revit itself all converge on the same rule: the tile/element shows
   identity + a handful of decision-critical controls; everything else
   lives in an inspector. ArchHub's `HostBody` (a 4-line readout today)
   and the rejected "all params on the node" spec are both wrong — the
   answer is *in between*, with the deep editor in the **NodeRail**.
2. **The boundary rule is objective** (§2 decision table): a parameter
   renders on the node body only if it is high-frequency AND topology-
   shaping OR a live readout; everything else is NodeRail-only.
3. **Fields are type-aware** (§3): one widget per data type, rendered two
   ways — a compact glanceable form on the body, a full editor in the
   panel. A list never renders as 40 rows on a node; it renders as a
   count chip that opens a searchable list in the panel.
4. **Reader-by-default, control-opt-in** (§4): every field ships as a
   readout of what the AI is doing; the user clicks a lock to seize
   control. This is the spreadsheet cell / DevTools "computed vs styles"
   idiom, and it is the spine of the whole design.
5. **Element pickers leave the host node entirely** (§5): views, levels,
   worksets are *output ports*, consumed by a dedicated **Filter node** —
   never element-pickers crammed onto the Revit session node.

**Top 3 things to build first** are at the very end of this document.

---

## 1. Reference research — the node-body / inspector-panel split

The question every mature node tool has answered: *given a parameter,
does it render on the node or in the side inspector?* I surveyed thirteen
systems against primary documentation. The table gives, per system, (a)
what lives on the node, (b) what lives in the panel, (c) the explicit
split rule, (d) panel organisation; the prose after each cluster gives
(e) the steal. Every primary-doc URL is in the source list at the end.

| System | (a) On the node | (b) In the panel | (c) The split rule | (d) Panel org |
|---|---|---|---|---|
| **Houdini** | name, type shape/colour, **flags** (display/render/bypass/lock) as edge badges; zero param values | every param — sliders, ramps, vector triplets, file pickers, channel refs, menus | tile = identity + exec state; **Parameter pane = the entire control surface** (a `.hip` has thousands of nodes — per-tile widgets would destroy the view) | author-declared **folders → tabs** (Geometry/Render/Misc); spare params add to them |
| **Unreal Blueprints** | pins; an **inline default widget only on an UNWIRED input** — once wired, the widget vanishes, the wire is the value | node metadata; for variable/component nodes the full property set | **inline editing exists only as a fallback for an unconnected input**; a connected input shows nothing | Details panel: collapsible **categories** + search |
| **Unity Shader Graph** | inline widgets for *constant* inputs only (a `Color` swatch) | **Blackboard** = graph-public properties; **Graph Inspector** = Node Settings tab + Graph Settings tab | node-local constants inline; graph-public params in Blackboard; per-node settings in Inspector | tabbed Graph Inspector + separate list-style Blackboard |
| **TouchDesigner** | name, a small **node viewer** thumbnail, connect flags; no params | the **parameter dialog** (floats or docks), **page tabs** per operator | the tile readout is a per-node opt-in — the **"viewer active"** toggle | page tabs (Common/Preview/Cook/About) |
| **Blender Geometry Nodes** | widgets for inputs with a sensible local value; unconnected socket → inline widget, connected → just the wire | inputs **promoted to the Group Input** appear in the **modifier panel** — same param editable in both places | a socket is a node-body widget when unconnected; it becomes a modifier-panel field **when the author promotes it** | modifier panel = flat list of promoted inputs, author-defined panels |
| **Grasshopper** | **only typed sockets** + a name; zero inline value widgets | a `Number Slider`/`Panel`/`Value List` is a **separate component**, not a field; **Remote Control Panel** aggregates all input controls | Grasshopper has almost no node body — **a parameter is itself a node** | Remote Control Panel = flat aggregation of every input control |
| **Fusion (Resolve)** | name + thumbnail; no params | the **Inspector** — selected tool's controls in **tabs** (Controls/Settings + tool tabs); multi-select stacks | node = identity; Inspector = all controls, tabbed | tabbed; first tab = most-used controls |
| **Nuke** | name + a couple of state indicators; no inline params | the **Properties bin** — **stacks multiple** node property panels, each tabbed, pinnable | node = identity; properties bin = the control surface, stackable | stacked tabbed panels |
| **Figma / Framer** | the **rendered result** itself; no controls overlaid | the **right panel** — every property in collapsible **sections** (Position/Layout/Fill/Stroke/Effects/Export) | canvas object = WYSIWYG output; panel = 100% of controls, sectioned | collapsible **sections**, not tabs (design props all relevant at once) |
| **n8n / Node-RED** | name, icon, execution state (items in/out) | the **node detail drawer** — all params | canvas node = identity + run state; drawer = full config | **operation dropdown reorganises the whole field list**; collapsible groups; **"Add optional parameter"** so rare fields are absent until summoned |
| **Max/MSP** | object name + typed-in **constructor arguments** (`metro 500`) — args are inline | the **Inspector** — every attribute, categorised + search filter | **constructor args inline** (they define the object); **attributes in the Inspector** | categorised + searchable |
| **Revit** | the element geometry only; no controls | the **Properties palette** — params in collapsible **groups** (Constraints/Graphics/Dimensions/Identity/Phasing), **Type Selector** on top, instance vs. type split | element shows the design; palette shows all params, grouped; **instance-vs-type** is the primary cut | collapsible groups, fixed order, searchable (2025+) |
| **Dynamo** | **every widget directly on the node body** (a slider lives on the node; a `Categories` dropdown on the node) | **none — Dynamo has no per-node inspector at all** | "everything on the node, or nowhere" | — |

**Steals (e).** **Houdini** is the primary precedent — tile = identity +
flags + state, *nothing else*; the panel is tabbed by author-declared
folders. **Unreal**'s wire-replaces-widget rule is stolen verbatim — the
single most important precedent for §4 ("wired" = reader, "unwired
widget" = controller). **Blender**'s **promotion model** — the body is
the author's surface, the NodeRail the deep one, "promote to the Skill
face" is Blender's Group Input, with ArchHub's twist that the AI is also
a downstream consumer, so promoted = AI-facing. **Grasshopper** —
anti-steal the extreme (a-param-is-a-node is why GH graphs sprawl) but
steal the Remote Control Panel: the NodeRail is ArchHub's per-node Remote
Control Panel. **TouchDesigner**'s page-tabs → NodeRail tabs; "viewer
active" is the precedent for §4 reader fields being a deliberate surface.
**n8n**'s operation-driven field list + "Add optional parameter" — a
Revit node shows fields for the current mode, never 40 fields. **Revit**
— steal the mental model wholesale: an ArchHub host node IS a Revit
element, the NodeRail IS the Properties palette, zero training.
**Fusion** — first tab = decision-critical, later = rare. **Unity** —
one NodeRail for v1, no separate Blackboard. **Nuke** — panel-pinning is
a v2 note. **Figma** — *tabs* for mutually-exclusive contexts, *sections*
for sub-groups. **Dynamo** is the cautionary tale: the literature is
explicit that Dynamo graphs become "opaque to all but the original
author" (Eastman et al., *BIM Handbook* 3rd ed., Wiley 2018, ch. 6) and
the forum's perennial complaint is graph sprawl — a large cause being
that every node is bloated with its own widgets, so the dataflow
disappears. The absent inspector is not minimalism; it is the defect the
NodeRail corrects.

### 1.14 Synthesis — the convergent rule

Twelve of thirteen mature systems put the deep control surface in a side
panel. The lone exception (Dynamo) is widely documented as hard to read
*because of* that choice. The convergent rule across Houdini, Unreal,
Unity, TouchDesigner, Fusion, Nuke, Figma, n8n, Max, and Revit:

> **The node carries identity, execution state, and at most a few
> decision-critical controls. The inspector panel carries the complete,
> organised parameter set. A control appears inline only when it is
> either (a) topology-shaping enough that hiding it would hide the
> graph's shape, or (b) a fallback for an unconnected input.**

ArchHub's founder correction — "two sizes with only necessary parameters
visible, something in between, utilise the right panel" — *is this
convergent rule.* The rest of this document operationalises it.

---

## 2. The boundary rule for ArchHub — decision table

A parameter renders **on the node body**, **in the NodeRail only**, or as
an **output port** (consumed by a Filter node). The developer evaluates
each `ParamDef` against the table; the first matching row wins. No
guessing.

| # | Condition (evaluate top-down, first match wins) | Renders | Rationale / precedent |
|---|---|---|---|
| 1 | Parameter's value is a **collection the user picks INTO** (a specific view, a specific element, one workset out of many) | **Output port** → Filter node | §5; element-pickers belong on a Filter node, not the host. Houdini "downstream node," GH "param is a node" |
| 2 | Parameter **changes the node's output topology** (which output ports exist, e.g. Speckle `mode = receive/send`, Revit `discipline` if it gates outputs) AND has no safe default | **Node body** | Unreal: topology-shaping pins are always visible; hiding them hides the graph's shape |
| 3 | Parameter is the node's **defining identity** (host product, host version, target document) | **Node body** (header) | Max: constructor args define the object; Revit: Type Selector sits on the palette top — but ArchHub elevates it to the body because it is the node's name |
| 4 | Parameter is **high-frequency** (the architect changes it most sessions) AND is a **scalar/enum/bool** (a single glanceable value) | **Node body** | Houdini flags, ComfyUI seed: a few hot scalars earn body space. Cap at 4 (Miller 4±1, UX-principles §1.7) |
| 5 | Parameter is a **live readout** the AI is actively driving (current active view, element count, last sync) | **Node body** (reader field) | §4; TouchDesigner node viewer; the body's job is to show "what the AI is touching" |
| 6 | Parameter is a **list** (worksets, categories, layers, sheets) used for *configuration* (not picked-into per row) | **Node body = count chip**, **NodeRail = full list editor** | §3.2; a list never renders as N rows on a node. n8n collapses; Revit groups |
| 7 | Parameter is **destructive** (`mark_read`, `purge_unreferenced`) | **NodeRail only**, behind a confirm | Error prevention (Nielsen H5); never one careless click away on the canvas |
| 8 | Parameter is **advanced / rare** (changed once at setup: `include_linked`, `tolerance`, `element_limit`) | **NodeRail only** | Houdini "Misc" tab, Figma collapsed section, n8n "Add optional parameter" |
| 9 | Parameter has a **sensible default** AND is **low-frequency** | **NodeRail only** | If a default works and nobody touches it, it does not earn body pixels |
| 10 | Everything else | **NodeRail only** | Default to the panel. The body is a privilege, earned by rows 2–6 |

**The body budget is hard-capped.** Header (host + version + document) +
**at most 4** rows from rows 2/4/5 + **at most 3** count-chips from row 6
+ a 1-line live status. If a host's schema wants more on the body, the
schema is wrong — promote the overflow to the NodeRail. This cap is the
"something in between" the founder demanded: bigger than today's 4-line
readout, far smaller than the 9-row Revit body the prior grammar doc
proposed.

**Two node sizes** (founder: "two sizes are good"):
- **Compact** (default, ~300 px wide): header + ≤4 body params + ≤3
  count-chips + status line + 1 preview strip. This is rows 2–6 only.
- **Expanded** (toggle `⌃`, ~340 px wide): same params plus the live
  preview footer grows to a thumbnail + the per-port readout list. Still
  NOT the full parameter set — for that, the architect uses the NodeRail.
  Expanded is "see more of the *output*," not "see more *controls*."

The deep editing surface is always the NodeRail. There is no third
"giant node" size.

---

## 3. Type-aware fields — the complete field-type system

The founder: "the fields or cells should comprehend the data type
inside." Below is the full `type → widget` mapping, each type specified
for **both** surfaces — the **compact node body** and the **expanded
NodeRail**. The master table gives the controller form; §4 gives the
reader form. Widget design is grounded in NN/g forms research
(<https://www.nngroup.com/articles/web-form-design/>,
<https://www.nngroup.com/articles/drop-down-menus/>), Material 3
(<https://m3.material.io/components>), Apple HIG
(<https://developer.apple.com/design/human-interface-guidelines/>), and
the WAI-ARIA Authoring Practices
(<https://www.w3.org/WAI/ARIA/apg/patterns/>).

**Key design calls behind the master table below:**

- **list — the founder's explicit case** ("views, levels, etc are
  LISTS"). A list NEVER renders as N rows on the body — it renders as a
  single **count chip** (`views · 24`); while the AI iterates, the chip
  shows a position (`views · 7/24 ◌`). Clicking it opens the NodeRail
  list editor (n8n collapsed-list + Finder's "47 items" — the count is
  the information). In the NodeRail a *configuration* list (which
  worksets to include) is a searchable **multi-select**; a *drill-into*
  list (which specific view/wall) is **not a field at all** — it is an
  **output port** for a Filter node (§5). A chip-set of 3 on the body is
  fine; 8 worksets is not — chips collapse to a count above 3 to respect
  the §2 body cap.
- **enum** — dropdown not radio: Material 3 and HIG reserve radios for
  ≤5 all-visible options; host enums are longer and dynamic. >7 options
  → type-ahead filter inside the menu (NN/g: dropdowns over ~7 need
  search).
- **number** — body is a **stepper** (a slider is too wide/imprecise for
  a glance); NodeRail is **both** a slider AND a bound numeric input
  (Houdini's float-slider-with-field; NN/g notes sliders alone fail for
  precise values). The existing `FullParam` slider (`studio-lm.jsx:5322`)
  is close — keep slider+field, move it to the NodeRail.
- **boolean** — a toggle switch, not a checkbox (Material 3 reserves the
  switch for "takes effect immediately"); the `FullParam` toggle
  (`studio-lm.jsx:5349`) is already correct.
- **wire-bound — the keystone state** (expanded in §4). When a field's
  value comes from an upstream wire, it renders as a **wire chip**
  (`← revit.views · 24 items`, type-coloured) *replacing* the editable
  widget — the **Unreal Blueprints rule**: a connected input shows no
  widget because the wire is the value. The chip's readout is the wire's
  `value_preview` (`graph.py:159`). Wired = reader, automatically, with
  no mode toggle; override = right-click chip → "Detach & edit". The §4
  mode toggle is only for *unwired* fields.

### 3.10 the type→widget master table

| Data type | Node body (compact) | NodeRail (expanded) | ARIA pattern |
|---|---|---|---|
| enum / choice | truncated dropdown | dropdown + type-ahead if >7 | Combobox / Listbox |
| list (config) | count chip `label · N` | searchable multi-select list | Listbox (multi) |
| list (pick-into) | — (it is an **output port**) | — (Filter node consumes) | — |
| scalar number | stepper `− 500 +` | slider + bound numeric field | Slider + Spinbutton |
| boolean | toggle switch | toggle switch + help line | Switch |
| text | rarely shown (readout only) | single-line input | Textbox |
| regex / pattern | — | mono input + match-count badge | Textbox + live region |
| color | swatch | swatch → HSL/hex popover | Button + Dialog |
| geometry ref | count chip / glyph | readout card + "pick in host" | Button |
| file path | basename, hover=full | text + Browse button | Textbox + Button |
| **wire-bound** | **wire chip `← src.port`** | **wire chip + value preview** | (read-only) |

---

## 4. Reader-by-default, control-opt-in — the core principle

The founder's sharpest instruction: *"FIELDS CAN BE READERS displaying
what the AI is interacting with, and control is OPTIONAL."* This section
researches and designs it. It is the spine of the whole spec.

### 4.1 The precedent — read surfaces vs. edit surfaces

The pattern of "one surface shows a value, a sibling surface edits it"
is everywhere, and the precedents tell us exactly how to build it. A
**spreadsheet cell** displays a computed value while the formula bar
edits the formula — the result is always visible, editing is opt-in by
clicking into the bar (<https://support.microsoft.com/en-us/office/overview-of-formulas-in-excel-ecfdc708-9162-49e8-b993-c311f47ca173>);
this is exactly "reader by default." **Chrome DevTools** deliberately
separates a read-only **Computed** pane (what is true now) from an
editable **Styles** pane (what you can change)
(<https://developer.chrome.com/docs/devtools/css>) — ArchHub's reader
field = Computed, controller field = Styles. A **debugger watch panel**
reads a variable's live value as execution proceeds and updates as the
program runs — you watch first, you set deliberately
(<https://code.visualstudio.com/docs/editor/debugging>); this is the
model for "the AI is reasoning, the field updates." **React DevTools**
renders props/state as a readout and requires a double-click to edit —
inspection default, edit opt-in (<https://react.dev/learn/react-developer-tools>).
**Observability dashboards** (Grafana, Datadog) are pure readers — nobody
types into a metric graph. And HTML's own **`<span>` vs `<input>`**
distinction, and **Jupyter's** output cell (read) vs. input cell (edit),
are the same split. The synthesis: **inspection is the default state of
a field; control is a deliberate, signalled transition.** A node field
that is *always* an editable input is lying — it implies the user is in
control when, under ArchHub's agent-first model, the AI usually is.

### 4.2 Reader mode vs. controller mode — the visual design

A **reader field** (default) renders the value as **text/readout** in
`LM.ink` with **no input chrome** — no border, no `▼`, no focus ring; it
looks like a `<span>`, not an `<input>`. A **provenance glyph** on the
left edge says where the value came from (§4.5); a subtle **closed lock**
(`🔒`) on the right edge, shown on hover, is the affordance to take
control. A **controller field** (after the architect takes control)
renders the **full §3 widget** — dropdown, stepper, toggle, slider —
with input chrome and focus ring; the provenance glyph becomes `✎`, the
lock is **open** (`🔓`) and clicking it releases control (the field
reverts to reader and re-adopts the host/AI value). The metaphor is a
Photoshop layer-lock or a locked Excel cell — a closed lock means "not
yours to edit right now," universally understood.

### 4.3 How the user flips reader → controller

The flip is **one obvious click, not a hidden mode.** The **lock glyph
is the toggle** — click the closed lock → controller (the widget appears
in place); click the open lock → reader. It is **per-field, not a global
mode** — there is no "whole node in edit mode" state, so no Vim-mode tax.
Additionally, **editing implies taking control**: clicking directly into
a reader field's value (not the lock) auto-flips it to controller, like
clicking into an Excel cell — the lock is the explicit path, direct
interaction the implicit one, both end in controller. Releasing is
symmetric, plus a NodeRail "release all overrides" button. The anti-mode
property: **mode is a per-field property, always visible as the lock +
provenance glyph.** Norman's mode warning (DOET §5) targets *invisible,
global* modes; a per-field mode rendered as a lock on that exact field
is a signifier — like a locked Revit parameter or Figma layer.

### 4.4 How a reader field animates while the AI is reasoning

When the agent is cooking a node (the existing `state:'running'`,
`NodeStateDot` at `studio-lm.jsx:3870`): a reader field the agent
**reads** gets a brief **scan highlight** — a 600 ms low-alpha
`LM.accent` sweep across the row (the debugger "this line is executing"
cue — *the AI is looking at this now*); a reader field the agent
**writes** gets a **value-change flash** — the new value fades in over
200 ms with a brief `LM.accent` underline (the Gestalt "common fate"
attribution cue, UX-principles §1.6); a list field being iterated
advances its count chip (`views · 7/24 ◌` → `8/24 ◌`). All within the
UX-principles §10.4 motion budget (≤400 ms, non-blocking, causal). A
controller field **never** animates from the AI — the AI does not touch
it; that is the whole point of taking control.

### 4.5 Provenance — "who set this value"

Every field carries a one-glyph provenance marker. This is non-negotiable
for a licensed profession (UX-principles §7.3: a wrong schedule needs the
architect to show "I authored this"). Provenance values:

| Glyph | Provenance | Field mode | Meaning |
|---|---|---|---|
| `◆` | host-driven | reader | the live host supplied this (current active view) |
| `✦` | AI-set | reader | the agent chose this value this session |
| `←` | wire-bound | reader | an upstream node drives it (§3.9) |
| `▢` | host-default | reader | the `ParamDef` default, untouched |
| `✎` | user-set | controller | the architect took control and set it |

Provenance is stored per-param in `param_provenance: dict[str,str]` on
the `Node` (§8). It drives the glyph, and it drives precedence: a
`✎` user-set value is **never** overwritten by the AI or the host — the
agent must propose a change (a ghost-value the architect accepts), it may
not silently mutate a user-owned field. This is UX-principles Tenet 1
("the AI never over-writes") made mechanical.

---

## 5. The Revit session node — fully worked example

The founder's exact example, walked end to end.

### 5.1 What the Revit session node IS

A `host.revit_session` node represents one live connection to one Revit
instance. It is `kind:"resource"` in the reframe's three-way split
(`docs/NODE_RND_REFRAME_2026-05-15.md` §2) — a read surface the agent
queries freely. It is **not** where you pick an element; it is where you
declare *which Revit, which document* and then *expose what Revit
contains as typed output ports.*

### 5.2 Node body (compact) — what shows

Applying the §2 decision table, the body shows exactly:

- **Header:** `[R] Revit 2025 · Tower-A_central.rvt` — host product +
  version + document. (§2 row 3, identity. Version + document are
  dropdowns in the header because changing them redefines the node.)
- **Status line:** `◆ LIVE · synced 12s ago · 47 walls` — the live
  readout (§2 row 5). `◆` = host-driven provenance.
- **Active view** — `◆ L01-Floor-Plan-Arch` — reader field, host-driven.
  (§2 row 5: it is the single most-glanced live value; the AI usually
  drives it.) One click on the lock makes it a controller dropdown.
- **Discipline** — `✦ Architecture` — body field (§2 row 4: high-freq
  enum), shown as a reader because the agent set it; `✦` provenance.
- A **count-chip row**: `views · 24   levels · 8   worksets · 5` —
  three count chips (§2 row 6). These are NOT pickers — clicking a chip
  opens the NodeRail list, OR the architect wires the matching **output
  port** into a Filter node.
- A **preview strip**: `▓▓░░▓ plan · 47 walls (L01)`.

That is the whole body: 1 header + 1 status + 2 reader fields + 1
chip-row + 1 preview. Six rows. Inside the §2 cap.

### 5.3 NodeRail panel (expanded) — the full tabbed editor

When the Revit node is focused, the NodeRail shows the full editor. Tabs
are **derived from the host's parameter groups** — the `ParamDef.group`
field already exists in the prior grammar doc's schema; each distinct
`group` becomes a tab, in a host-declared order. For Revit:

**Tab 1 — Session** (the connection identity)
| Field | Type | Widget | Reader/Controller default |
|---|---|---|---|
| Revit version | enum | dropdown | controller (user picks) |
| Open document | enum | dropdown (`revit.list_open_docs`) | controller |
| Connection status | text | readout | reader (host-driven) |
| Active view | enum | dropdown (`revit.list_views`) | reader (`◆` host) |
| Phase | enum | dropdown (`revit.list_phases`) | reader (`✦` AI) |

**Tab 2 — Scope** (what subset of the model the node exposes)
| Field | Type | Widget | Reader/Controller default |
|---|---|---|---|
| Discipline | enum | dropdown | reader (`✦` AI) |
| Worksets | list (config) | searchable multi-select | reader (`✦` AI) |
| Categories | list (config) | searchable multi-select | reader (`✦` AI) |
| Limit to active view | boolean | toggle | reader (`▢` default OFF) |

**Tab 3 — Performance** (rare, setup-once)
| Field | Type | Widget | Reader/Controller default |
|---|---|---|---|
| Element limit | number | slider + numeric field | controller (`▢` default 500) |
| Include linked models | boolean | toggle | controller (`▢` default OFF) |
| Refresh interval | number | stepper | controller |

**Tab 4 — Wires** (§6.3) — this node's inputs/outputs and bindings.
**Tab 5 — Activity** (§6.4) — the "what the AI did here" trace.

Tabs 1–3 are host-defined parameter groups; tabs 4–5 are universal
(present on every node). The architect sees five tabs; Houdini-style.

### 5.4 Where do views / levels / worksets live? — the argument

**Worksets and Categories are configuration lists** → **NodeRail
multi-select fields** (Tab 2), with count-chips on the body. Rationale:
the architect is not picking *one* workset to act on; they are declaring
*which subset of the model* the whole node exposes — that is
configuration, and configuration with >3 items goes to the NodeRail (§2
row 6).

**Views and Levels are collections you drill into** → they are **output
ports**, not fields. Three reasons: (1) the founder's instruction is
sound — "if he wants to interact with a specific element he should use a
FILTER NODE"; picking "view L01 specifically" is *filtering a
collection*, a node operation, not a field edit. (2) **Topology** — if
"active view" were a picker gating all downstream queries, every Revit
node would need an embedded element-tree browser, exactly the Dynamo
bloat (§1.13) the §2 cap forbids. An output port keeps the host node
small and pushes the drilling onto a node the architect can see, move,
and rewire. (3) **Composability** — an output port `views` can fan into
*multiple* Filter nodes (one to plans, one to sections), each a visible
step; a field cannot fan out (the Larkin & Simon "a diagram reduces
search cost" property, UX-principles §5.4). So **Active view** is on the
body as a *reader* (the live focus the AI drives) AND `views` is also an
*output port* (so a Filter node can select independently) — not a
conflict: the body field shows "what Revit's UI currently has open," the
port lets the graph select on its own.

### 5.5 The flow — ASCII

```
   ┌──────────────────────────┐
   │ [R] Revit 2025           │
   │     Tower-A_central.rvt  │          ┌───────────────────────┐
   │ ◆ LIVE · 47 walls        │          │ ⧩ FILTER              │
   │                          │ views    │   where level = "L01" │
   │ Active view ◆ L01-Plan   │ ●────────┤▶ in: collection       │
   │ Discipline  ✦ Arch       │          │   field: level        │
   │                          │ levels   │   op: equals          │
   │ views·24  levels·8  ws·5 │ ●──┐     │   value: ◆ L01        │
   │                          │    │     │ out: filtered ●───────┼──▶ downstream
   │ ▓▓░░▓ plan · 47 walls    │    │     └───────────────────────┘    (schedule,
   │                          │    │                                  annotate…)
   │ OUT: walls● doors● views●│    │     ┌───────────────────────┐
   │      levels● selection●  │    └─────┤ ⧩ FILTER              │
   └──────────────────────────┘  levels │   where elevation>10m │
                                         └───────────────────────┘
```

The Revit node stays compact; `views` and `levels` are output ports; two
Filter nodes consume them independently; each drill-down is a visible,
movable node. The architect reads the whole story off the canvas.

---

## 6. NodeRail redesign spec

The NodeRail exists (`studio-lm.jsx:4957`) but is thin: a header, a
flat `CONNECTIONS` block, a flat `SETTINGS` list of `FullParam`s, four
buttons. It is not tabbed, not host-aware, has no activity trace, and its
empty state is a blank `<aside>`. Redesign:

### 6.1 Header — focused node identity + status

Host glyph (brand colour from `LM_HOST_META`) + node title in
`LM.serif` 21px (the current header is already close) + a **status pill**
(`◆ LIVE` / `○ IDLE` / `▲ STALE` / `✕ OFFLINE`) + last-sync relative
time. One line below: the node id in mono + `kind` (resource / tool /
cell).

### 6.2 Tabbed parameter categories

Replace the flat `SETTINGS` list with a **tab strip**. Tabs are derived:
for each distinct `ParamDef.group` in the node's schema, in host-declared
order, emit a tab; append the universal **Wires** and **Activity** tabs.
A host with one group shows one param-tab + Wires + Activity. Tab
contents render each field via the §3 widget set, each with its §4
reader/controller state and provenance glyph. Within a tab, fields may
be sub-grouped into Figma-style collapsible sections if a group is large.
A search box (`/` focus) at the top of the active tab filters fields
(n8n pattern, UX-principles Hick mitigation).

### 6.3 The Wires section

A dedicated tab listing this node's **inputs** and **outputs**, each row:
port name, type (colour-chipped), and binding state — `← bound to
revit.views` or `unbound` or `→ feeds 2 nodes`. This replaces the current
`CONNECTIONS` block but adds the binding readout and a per-row "detach"
action. This is where the architect manages §3.9 wire-bound fields.

### 6.4 The "what the AI did here" trace

An **Activity** tab: a reverse-chronological list of agent actions
scoped to this node — `✦ set Discipline = Architecture · 12s ago ·
claude-sonnet-4.6`, `✦ cooked · 480ms · 47 walls`. Sourced from the
reframe's lineage store (`docs/NODE_RND_REFRAME_2026-05-15.md` §6.2).
Each row has a "revert this" action. This is the per-node slice of the
UX-principles §7.6 mandate (every agent mutation must be auditable).

### 6.5 Empty state when no node focused

Never a blank panel: a one-line hint ("Select a node to edit its
properties") plus a compact **canvas summary** (node count, cook status,
last run). Figma's empty right-panel shows document properties; ArchHub
shows graph properties. Quiet, `LM.inkMuted`, never empty.

### 6.6 Component + LOC

`studio-lm.jsx`: replace `NodeRail` (L4957, ~125 LOC) with a new
`NodeRail` (~260) delegating to `NodeRailTabs` (~140), `WiresTab` (~90),
`ActivityTab` (~80), `NodeRailEmpty` (~50); keep `ConversationRail`
(L5085) for AI nodes. NodeRail redesign ≈ **620 LOC** plus §8 widgets.

---

## 7. ASCII mockups

### 7.1 Revit session node — compact, reader mode (AI is driving)

```
┌─────────────────────────────────────────────────┐
│ [R] REVIT 2025  ▾   ●LIVE 12s              [↻][⌃]│  header: version dropdown
│     Tower-A_central.rvt  ▾                       │  + document dropdown
├─────────────────────────────────────────────────┤
│ ◆ synced 12s ago · 47 walls · 12 doors           │  live status line
│                                                  │
│ Active view   ◆ L01-Floor-Plan-Arch         🔒  │  reader · host-driven
│ Discipline    ✦ Architecture                 🔒  │  reader · AI-set
│                                                  │
│ views · 24    levels · 8    worksets · 5         │  count chips (open NodeRail)
│                                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ ▓▓▒░░▓▓▒░░  plan preview · 47 walls (L01)   │ │
│ └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│ walls● doors● windows● rooms● views● levels●     │  OUTPUT PORTS
│ worksets● selection●                             │
└─────────────────────────────────────────────────┘
   all fields are READOUTS — closed locks 🔒 — the AI owns them
```

### 7.2 Same node — compact, controller mode (user took 2 fields)

```
┌─────────────────────────────────────────────────┐
│ [R] REVIT 2025  ▾   ●LIVE 4s               [↻][⌃]│
│     Tower-A_central.rvt  ▾                       │
├─────────────────────────────────────────────────┤
│ ◆ synced 4s ago · 47 walls · 12 doors            │
│                                                  │
│ Active view   ✎[▼ L02-Floor-Plan-Arch      ]  🔓│  CONTROLLER · user-set
│ Discipline    ✎[▼ Structure                 ]  🔓│  CONTROLLER · user-set
│                                                  │  ↑ widget chrome + open lock
│ views · 24    levels · 8    worksets · 5         │
│                                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ ▓▒░▓▒░▓  plan preview · 38 walls (L02)      │ │  preview followed the override
│ └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│ walls● doors● windows● rooms● views● levels●     │
│ worksets● selection●                             │
└─────────────────────────────────────────────────┘
   2 fields seized (✎ open lock 🔓) — AI may PROPOSE but not overwrite them
```

### 7.3 The NodeRail — Revit node focused, full tabbed panel

```
╔═══════════════════════════════════════╗
║ [R] Revit 2025          ●LIVE · 4s    ║  header
║ Tower-A_central.rvt                   ║
║ host.revit_session · kind: resource   ║
╠═══════════════════════════════════════╣
║ ┌Session┐ Scope  Perf.  Wires  Activ. ║  TABS (groups + universal)
║ └───────┘                             ║
║ [/ search fields…                  ]  ║
║                                       ║
║ Revit version   ✎[▼ Revit 2025      ] ║  controller
║ Open document   ✎[▼ Tower-A_central ] ║  controller
║ Connection      ◆ Live · port 48884   ║  reader (host)
║ Active view     ✎[▼ L02-Floor-Plan  ] ║  controller (user took it)
║ Phase           ✦[▼ New Construction] ║  reader→shown as widget,           
║                    🔒 (locked: AI)    ║  lock closed = AI owns
║                                       ║
║ ── provenance ────────────────────    ║
║  ◆ host  ✦ AI  ← wire  ✎ you  ▢ deflt ║  legend
╠═══════════════════════════════════════╣
║ ↻ Rerun node   ⤴ Promote to Skill     ║  actions
║ ⎘ Branch       ⊘ Release all overrides║
╚═══════════════════════════════════════╝
```

### 7.4 A Filter node consuming the Revit node's `views` output

```
            revit.views (24 items)
                  │
                  ▼
┌────────────────────────────────────────┐
│ ⧩ FILTER                          [⌃] │
├────────────────────────────────────────┤
│ in:  collection  ◆ 24 views            │  reader: what arrived on the wire
│                                        │
│ Field    ✎[▼ view_type            ]   │  controller: user picks the key
│ Operator ✎[▼ equals               ]   │  controller
│ Value    ✎[▼ FloorPlan            ]   │  controller (options from upstream)
│                                        │
│ ◆ 8 of 24 match                        │  reader: live match count
├────────────────────────────────────────┤
│ out: filtered ●  →  feeds 1 node       │  OUTPUT
└────────────────────────────────────────┘
   the DRILL-DOWN lives here, on a movable node — not on the host node
```

---

## 8. Architectural diff

Concrete changes, with file paths, symbols, and LOC estimates.

### 8.1 `app/workflows/graph.py` — `Node` schema (~45 LOC)

Add fields to `Node` (L108), all with defaults so `from_dict` (L127)
stays backward-compatible with sessions on disk:

```python
@dataclass
class Node:
    # ... existing fields ...
    param_schema: list[dict] = field(default_factory=list)   # ParamDef dicts
    param_values: dict = field(default_factory=dict)         # current values
    param_provenance: dict = field(default_factory=dict)     # id -> host|ai|wire|user|default
    param_mode: dict = field(default_factory=dict)           # id -> "reader"|"controller"
    host_status: str = "unknown"                             # live|stale|offline|unknown
```

`to_dict`/`from_dict` updated to round-trip the five fields; `from_dict`
reads legacy `config` into `param_values` when `param_schema` is empty.
Each `ParamDef` gains a `surface` field (`"body"|"rail"|"port"`) computed
by the §2 decision table at schema-author time so the renderer never
re-derives it.

### 8.2 `app/web_ui/studio-lm.jsx` — `HostBody` rewrite (~240 LOC)

Replace `HostBody` (L3934, currently 11 lines) with `HostNodeBody`:
header strip, status line, the ≤4 body fields filtered by
`surface==="body"`, the count-chip row for `surface` lists, the preview
strip, and the output-port row. Delegates to a new `BodyField` (~70 LOC)
that switches reader/controller per `param_mode` and renders the §3
compact widget. `NodeBody` switch at L3919 routes `'host'` →
`HostNodeBody`. `AIBody` (L3946) is untouched (AI nodes keep their
conversation body).

### 8.3 `app/web_ui/studio-lm.jsx` — `NodeRail` rewrite (~620 LOC)

Per §6.6: new `NodeRail` + `NodeRailTabs` + `WiresTab` + `ActivityTab` +
`NodeRailEmpty`. `FullParam` (L5318) is refactored into the per-type
controller widgets below and reused.

### 8.4 New field-widget components (~560 LOC)

A new file `app/web_ui/field_widgets.jsx` (or a section of
`studio-lm.jsx`): `EnumField` (~70), `ListField` count-chip + multi-select
(~150), `NumberField` stepper + slider (~90, lift from `FullParam`),
`BoolField` toggle (~40, lift from `FullParam`), `TextField`/`RegexField`
(~70), `ColorField` (~60), `WireChip` (~50), `LockToggle` + provenance
glyph helper (~40).

### 8.5 `app/bridge.py` — new slots (~260 LOC)

- `get_host_params(host_id, session_id) -> str` — JSON `param_schema`.
- `list_host_options(host_id, param_id, context_json) -> str` — resolve
  an option list; cached by `(host_id, param_id, ctx_hash)` for 30s.
- `set_node_param(node_id, param_id, value_json) -> bool` — set value;
  marks `param_provenance[param_id]="user"`, `param_mode="controller"`.
- `set_param_mode(node_id, param_id, mode) -> bool` — flip reader/
  controller; on release, re-adopt host/AI value.
- `probe_host_status(host_id) -> str` — `live|stale|offline`, cached 3s.
- `get_node_activity(node_id) -> str` — the §6.4 trace from lineage.

### 8.6 New filter node — `app/workflows/nodes/filter.py` (~120 LOC)

A `filter.collection` executor: takes a `LIST`/`SELECTION` input, a
`field`/`operator`/`value` config, emits the filtered subset. The
Filter node's body renders the §7.4 mockup. This is the node that
absorbs all element-drilling.

**Total: ~1845 LOC** (graph 45 + JSX 1420 + bridge 260 + filter 120).

---

## 9. Honest pushback

**Where the founder's model bites — and the hardest unresolved tension.**

**1. Reader/controller is still a mode, and modes carry a tax.** Norman
(DOET §5) and UX-principles §11 flag hidden modal state as a top
anti-pattern (the "Vim-mode tax"). A *per-field* mode rendered as a
visible lock glyph is a signifier, not a hidden mode — but it is not
free: the architect must still learn a field has two states and that a
`✎` field is AI-untouchable while a `◆` field is not (Sweller intrinsic
load). The mitigation (editing-implies-control — just click into fields
like a spreadsheet) works, but makes the explicit lock redundant for
most users and hurts discoverability of "release back to AI."

**2. The AI proposing into a user-owned field is unsolved.** §4.5 says a
`✎` field is never overwritten — the AI must *propose*. But what does a
proposal look like on a controller field that already shows the user's
value? A ghost value in the dropdown? A second value below? The prior
grammar doc's `✦` ghost-text accept/reject works for an empty field; it
is crowded on an already-set one. Needs its own mockup pass.

**3. The body/port duality for `views` can confuse.** §5.4 puts "Active
view" on the body as a reader *and* `views` as an output port. A
literal-minded architect wires `views` into a Filter, picks L02, and is
confused the body still says L01. Labelling discipline ("Active view (in
Revit)" vs. the port `views`) mitigates but does not eliminate it.

**4. Per-host tab derivation assumes clean parameter groups.** Hosts
without a real broker (Photoshop, Notion, Teams — prior grammar doc §7)
have thin or fabricated `group` metadata, producing a one-tab NodeRail
that looks broken next to Revit's five. The fix (a sensible default
grouping) is more schema work than it sounds.

**The single hardest tension — stated plainly:** *reader-by-default and
no-mode-tax are in genuine, irreducible conflict.* "Control is optional"
necessarily means a field has a no-control default state and a
has-control state — that IS a mode, by definition. Making the mode
per-field and visible (the lock) softens it but cannot remove it; the
architect must still hold the model "some of these fields are mine and
some are the AI's, and they behave differently." The closest resolution
is to lean entirely on **editing-implies-control** and treat the lock as
a power-user affordance — accept that 90% of architects will never think
in modes and will just click fields like Excel cells, while the
provenance glyphs quietly carry the "who owns this" information for the
10% who need the audit trail. But that means the founder's "control is
*optional*" framing is, in the shipped product, closer to "control is
*automatic on touch*" — a subtle but real reframing of his words, and the
one place this spec does not fully deliver his model as stated.

---

## Top 3 things to build first

1. **The boundary rule + the two-surface split (§2, §8.1–8.3).** Add
   `param_schema`/`param_values`/`param_provenance`/`param_mode` to
   `Node`; compute each param's `surface` via the §2 decision table;
   rewrite `HostBody` → `HostNodeBody` (compact, capped) and `NodeRail`
   → tabbed editor. This is the founder's "two sizes + utilise the
   panel" made real. Without it nothing else has a home.

2. **The reader/controller field with the lock toggle and provenance
   glyphs (§4, §8.4).** Build `BodyField`/`LockToggle` + the five
   provenance glyphs + editing-implies-control. This is the founder's
   sharpest principle and the spine of the design — every field on every
   node depends on it.

3. **The Filter node (§5, §8.6) and `views`/`levels` as output ports.**
   Ship `filter.collection` and make the Revit session node expose
   collections as ports, not pickers. This is what keeps the host node
   compact and is the founder's explicit instruction ("use a FILTER
   NODE"). Build it alongside #1 so the Revit node is correct from day
   one.

---

*End of report. Author: senior interaction-design researcher · ArchHub ·
2026-05-15. Supersedes the "everything on the node body" stance of
`docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md`; governed by the tenets of
`docs/NODE_INTERACTION_UX_PRINCIPLES_2026-05-15.md`.*

**Primary sources cited in body:**
Houdini flags & parameters — <https://www.sidefx.com/docs/houdini/network/flags.html>,
<https://www.sidefx.com/docs/houdini/network/parameters.html>,
<https://www.sidefx.com/docs/houdini/assets/parameter_interface.html> ·
Unreal Blueprint nodes — <https://dev.epicgames.com/documentation/en-us/unreal-engine/nodes-in-unreal-engine> ·
Unity Shader Graph — <https://docs.unity3d.com/Packages/com.unity.shadergraph@latest> ·
TouchDesigner Parameter & Node Viewer — <https://docs.derivative.ca/Parameter>,
<https://docs.derivative.ca/Node_Viewer> ·
Blender Geometry Nodes modifier & inspection — <https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/modifier.html>,
<https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/inspection.html> ·
Grasshopper developer guides — <https://developer.rhino3d.com/guides/grasshopper/> ·
DaVinci Resolve / Fusion — <https://www.blackmagicdesign.com/products/davinciresolve> ·
Nuke node properties — <https://learn.foundry.com/nuke/content/comp_environment/nodes/node_properties.html> ·
Figma inspect panel — <https://help.figma.com/hc/en-us/articles/360039831954-Inspect-your-designs> ·
n8n nodes — <https://docs.n8n.io/workflows/components/nodes/> ·
Max inspectors — <https://docs.cycling74.com/max8/vignettes/inspectors> ·
Revit Properties palette — <https://help.autodesk.com/view/RVT/2025/ENU/?guid=GUID-FBE5A1AD-EF31-4B33-B0F8-2EF1AB6CD70F> ·
Dynamo Primer — <https://primer.dynamobim.org/04_The-Building-Blocks-of-Programs/4-2_geometry-categories.html> ·
NN/g form & dropdown design — <https://www.nngroup.com/articles/web-form-design/>,
<https://www.nngroup.com/articles/drop-down-menus/> ·
Material 3 components — <https://m3.material.io/components> ·
Apple HIG — <https://developer.apple.com/design/human-interface-guidelines/> ·
WAI-ARIA APG patterns — <https://www.w3.org/WAI/ARIA/apg/patterns/> ·
Excel formulas — <https://support.microsoft.com/en-us/office/overview-of-formulas-in-excel-ecfdc708-9162-49e8-b993-c311f47ca173> ·
Chrome DevTools CSS (Computed vs Styles) — <https://developer.chrome.com/docs/devtools/css> ·
VS Code debugging / data inspection — <https://code.visualstudio.com/docs/editor/debugging> ·
React DevTools — <https://react.dev/learn/react-developer-tools> ·
Eastman et al., *BIM Handbook* 3rd ed., Wiley 2018, ch. 6.
