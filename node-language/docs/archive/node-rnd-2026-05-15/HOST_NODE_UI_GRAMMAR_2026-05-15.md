# Host-Node UI Grammar — Architect Retains the Controls

> Author: senior product/UX lead, ArchHub · 2026-05-15
> Refines (does not replace) `docs/NODE_RND_REFRAME_2026-05-15.md`.
> Founder correction 2026-05-15: architects are the end user, want grip on
> every parameter (sliders, dropdowns, pickers); host nodes expose all
> important available host parameters; what shows depends on user config;
> wires are Speckle data connectors; AI orchestrates the controls — does
> not replace them.
> Companion: `app/web_ui/studio-lm.jsx:3754-3920` (current NodeRenderer/
> HostBody — visibly thin), `app/workflows/graph.py:78-134` (Port/Node),
> `app/agents/composer_agent.py:138-160` (broker host roster), `app/bridge.py`.

## Executive verdict

The reframe ("nodes are memory cells") was correct in spirit and **wrong on
interaction model**. A memory cell on its own is a passive readout, and the
founder is not building a passive tool. The architect wants a **rich control
surface on every host node** — sliders, dropdowns populated from the live host,
pickers, toggles, chips — at the density Houdini, TouchDesigner, Grasshopper,
ComfyUI, and n8n ship. The `(formula, last_value, format, deps)` framing stays;
the *formula* is no longer one NL intent string but a **structured ParamDef set
the architect grips directly, with AI fill per param, not per node.**

Current state — `HostBody` in `studio-lm.jsx:3910-3920` is **four lines** of
flex rows mapping `outs → label · value`. That is a memory readout, not a
control surface. It is the single biggest UX defect on the canvas.

**Top-3 refinements to the reframe:**

1. **Add `param_schema: list[ParamDef]` to `Node`** — every host node carries
   a declarative typed-parameter list with widget hints. Replaces today's
   untyped `config: dict`. Drives the new `HostNodeBody`.
2. **Wires are Speckle Object kit transports**, not abstract pipes — port
   types map onto Speckle Base sub-classes; wires carry converter specs;
   the WIRE color map rebuilds against the Speckle taxonomy.
3. **Per-user `ui_config`** controls which params render — the founder is
   explicit that "what shows depends on user configurations." Add
   `Workflow.metadata["ui_config"]` + `SettingsDialog → Host Display`.

---

## 1. Reference grammar — how high-end node systems render host parameters

For each system: (a) widgets used, (b) how dynamic option lists are populated,
(c) how a wire binds to a specific parameter, (d) how "offline / live N items"
is signaled. Primary docs cited.

### 1.1 Grasshopper — typed sockets + side-mounted persistent data

Components carry typed sockets (Brep / Mesh / Layer / Block); persistent data
lives on the param itself — right-click → "Set One Brep" → Rhino viewport
picker, value stored even after the file closes. List access menu (per-port
zip/longest/cross) and type-coloured sockets. Ref:
[McNeel Grasshopper guides](https://developer.rhino3d.com/guides/grasshopper/).
**Borrow:** per-param-stored value + right-click → "Set / Pick from viewport".

### 1.2 Dynamo for Revit — dropdown nodes for catalog data

Four widget families: (a) inline dropdowns auto-populated from the open
document (`Categories`, `Levels`, `Phases`, `Worksets`, `Views`), (b) a
"Select Model Elements" button that minimizes Dynamo and lets the user
pick in Revit directly, (c) `Number Slider` with min/max/step, (d) code-block
escape hatch. Dropdowns refresh on document change. Ref:
[Dynamo Primer §4](https://primer.dynamobim.org/04_The-Building-Blocks-of-Programs/4-2_geometry-categories.html),
[Dynamo BIM forum](https://forum.dynamobim.com/). **Borrow:** document-scoped
dropdowns + "click to pick in host" button.

### 1.3 Houdini — parameter dialog, spare parameters, channels

The densest control surface in any node system: float sliders with bound
input fields, ramps, vector triplets, file pickers, channel references
(`ch("/obj/geo1/tx")`), ordered menus, folders/tabs, toggles, buttons.
Spare parameters are user-promoted controls: right-click any internal parm
→ "Edit Parameter Interface" → drag into the HDA's exposed panel. Ref:
[Houdini parameters](https://www.sidefx.com/docs/houdini/network/parameters.html),
[parameter interface](https://www.sidefx.com/docs/houdini/assets/parameter_interface.html).
**Borrow:** parm folder tabs (Common / Cook / About) and the
slider/ramp/picker/toggle widget vocabulary.

### 1.4 TouchDesigner — operator parameters + pulse + drag-to-bind

Page tabs per operator (Common / Preview / About / Cook). Numeric sliders,
RGB pickers, file pickers, dropdowns ("menus"), **pulse buttons** for
one-shot actions, expression fields (`op('cam1').par.tx`). Drag-to-bind:
drop a param onto another's expression field to channel-wire them. Ref:
[TD parameters](https://docs.derivative.ca/Parameter),
[TD expressions](https://docs.derivative.ca/Expression). **Borrow:**
page tabs, pulse buttons (for "Refresh"), drag-a-wire-onto-a-param.

### 1.5 Unreal Blueprints — struct breakout on node body

A `Transform` struct exposes `Location.X/Y/Z`, `Rotation.*`, `Scale.*` as
nested pins the user expands. Details panel mirrors the same set. Ref:
[UE Blueprint nodes](https://docs.unrealengine.com/5.3/en-US/blueprints-visual-scripting-in-unreal-engine/).
**Borrow:** struct breakout — one output port fans into typed sub-ports
(ArchHub's `selection` → `walls/doors/rooms`).

### 1.6 Substance Designer — exposed parameters with UI hints

`expose` decorator carries `min`, `max`, `step`, `label`, `group`, and
**`visible_if`** predicates that drive which params render based on other
param values. Ref:
[Substance exposed parameters](https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/exposed-parameters.html).
**Borrow:** `visible_if` verbatim.

### 1.7 ComfyUI — widgets directly on the node body

Closest reference to what the founder showed. Sliders, dropdowns
(`sampler_name`, `scheduler`), seed-with-randomize, pinned image preview,
multi-line text widgets, uniform "widget grows the node downward" layout.
Widgets declared as `INPUT_TYPES` tuples (`"steps": ("INT", {"default": 20,
"min": 1, "max": 100})`). Ref:
[ComfyUI custom nodes](https://docs.comfy.org/custom-nodes/overview),
[INPUT_TYPES spec](https://docs.comfy.org/custom-nodes/backend/datatypes).
**Borrow:** the type-tagged-tuple → widget mapping. This is the layout
idiom ArchHub clones for host nodes.

### 1.8 n8n — host-action node with endpoint browser

OpenAPI-driven: user picks an operation from a dropdown, parameter list
rebuilds, each field typed (string/number/dropdown/dateTime/collection),
**Test step** button runs the node with current params. Ref:
[n8n declarative nodes](https://docs.n8n.io/integrations/creating-nodes/build/declarative-style-node/).
**Borrow:** Test step → ArchHub's "Refresh" pulse.

### 1.9 Power Automate — dynamic content picker

Each step exposes outputs as `Dynamic Content` chips; downstream fields
get a chip-picker on every input. Ref:
[Power Automate dynamic content](https://learn.microsoft.com/en-us/power-automate/dynamic-content).
**Borrow:** chip picker on every parameter as the alternate wire-bind path.

### 1.10 Speckle Connectors — stream/branch/commit pickers

Send/Receive nodes show three pickers (**Stream → Branch → Commit**) populated
from server at expand time; object selection trees over Speckle Base
sub-classes (`Objects.BuiltElements.Wall`, `Objects.Geometry.Mesh`). Ref:
[Speckle concepts](https://speckle.guide/user/concepts.html),
[Speckle Object Model](https://speckle.guide/dev/objects.html).
**Borrow:** wires carry Speckle Base types — see §2.4.

### 1.11 MCP host inspectors

[MCP Inspector](https://modelcontextprotocol.io/legacy/tools/inspector)
renders each server's `resources/list`, `tools/list`, `prompts/list` as
JSON-Schema-derived widgets (toggles for bool, dropdowns for enum, sliders
for ranged numbers). **Borrow:** param_schema's wire format = JSON Schema
+ widget hints.

### 1.12 Cross-cutting "offline / live N" pattern

| State           | Visual                                | Implies                                  |
|----------------|---------------------------------------|------------------------------------------|
| Live + populated| Bold border, count chip ("47 walls") | Click param → instant dropdown           |
| Live + empty    | Bold border, neutral chip ("0 walls")| Dropdown says "(none)"                    |
| Offline         | Dimmed, lock icon, "Connect…" link   | Params disabled; only header pulse works |
| Probing         | Pulse animation on header dot         | Last value stale; awaiting refresh       |

ArchHub today only shows state 4 (a `NodeStateDot` at
`studio-lm.jsx:3846-3857`). The other three are missing.

---

## 2. ArchHub host-node grammar — the spec

### 2.1 Header strip

```
┌─────────────────────────────────────────────────────────┐
│ [icon] REVIT 2025  ·  Tower-A_central.rvt    ●LIVE 12s ↻│
└─────────────────────────────────────────────────────────┘
```

Components (left to right): brand-color glyph (Revit `#0696D7`, AutoCAD
`#E51937`, Blender `#E87D0D`, Speckle `#0F62FE`, Outlook `#0078D4` …);
host name + version; document/file pill; status indicator
(`●LIVE` / `○IDLE` / `▲STALE` / `✕OFFLINE` / `?UNAUTH`); last-sync
relative timestamp; `↻` refresh pulse button.

Brand colors live on `LM_HOSTS[*].color` already
(`studio-lm.jsx:56-63`) — surface them on the node border, not just
the rail row.

### 2.2 Parameters region — the control surface

For each host node, `param_schema` declares a list of ParamDef objects:

```python
# app/workflows/param_schemas/_types.py
@dataclass
class ParamDef:
    id: str                        # "active_view"
    label: str                     # "Active view"
    type: str                      # "string"|"number"|"bool"|"enum"|"multi"|"picker"|"color"|"path"
    widget: str                    # "slider"|"dropdown"|"chips"|"toggle"|"button"|"text"|"file"
    default: Any = None
    options_source: str = ""       # function name in option_sources.py; runs at expand time
    min: float | None = None       # for slider
    max: float | None = None
    step: float | None = None
    unit: str = ""                 # "mm"|"deg"|"%"|"px"
    group: str = ""                # "Document" | "Filter" | "Advanced"
    visible_if: str = ""           # Python predicate evaluated against current params
    help: str = ""                 # tooltip
    destructive: bool = False      # require confirm before cook
    drives: list[str] = field(default_factory=list)  # output ports this param feeds
```

#### 2.2.1 Revit host node (`h_revit`)

| id                  | label             | type    | widget   | options_source            | group       | notes |
|---------------------|-------------------|---------|----------|---------------------------|-------------|-------|
| `document`          | Document          | enum    | dropdown | `revit.list_open_docs`    | Document    | required |
| `active_view`       | Active view       | enum    | dropdown | `revit.list_views`        | Document    | depends_on=`document` |
| `phase`             | Phase             | enum    | dropdown | `revit.list_phases`       | Document    | |
| `worksets`          | Worksets          | multi   | chips    | `revit.list_worksets`     | Document    | multi-select |
| `discipline_filter` | Discipline        | enum    | dropdown | `static:arch,struct,mep,coord` | Filter | |
| `category_filter`   | Categories        | multi   | chips    | `revit.list_categories`   | Filter      | walls/doors/windows/rooms/sheets/families/... |
| `bounding_view`     | Limit to active view | bool | toggle   | —                         | Filter      | help="Bound queries to the active view" |
| `element_limit`     | Element limit     | number  | slider   | —                         | Performance | min=10, max=10000, step=10, default=500 |
| `include_linked`    | Include linked models | bool | toggle  | —                         | Advanced    | visible_if=`ui_config.show_advanced` |

Outputs (see §2.3): `walls`, `doors`, `windows`, `rooms`, `levels`, `views`,
`sheets`, `families`, `selection`, `warnings`, `events`.

#### 2.2.2 Outlook (`h_outlook`)

`account` (dropdown, `outlook.list_accounts`), `folder` (dropdown,
`outlook.list_folders`), `unread_only` (toggle), `from_filter` (text),
`subject_filter` (regex text), `since` (date), `limit` (slider 10-500/10),
`mark_read` (toggle, **destructive**). Outputs: `inbox`, `calendar`,
`contacts`, `drafts`, `unread_count`, `selection`.

#### 2.2.3 Speckle (`h_speckle`)

`server` → `stream` → `branch` → `commit` (cascading dropdowns,
`speckle.list_*`), `object_kit` (dropdown), `class_filter` (multi-chip,
`speckle.list_classes`), `mode` (dropdown `receive/send/both`). Outputs:
`objects`, `commit_meta`, `send_status`.

#### 2.2.4 AutoCAD (`h_autocad`)

`document` (dropdown, `acad.list_open_docs`), `layers` (multi-chip,
`acad.list_layers`), `block_filter` (multi-chip, `acad.list_blocks`),
`layout` (dropdown, `acad.list_layouts`), `entity_types` (multi-chip,
static), `purge_unreferenced` (toggle, **destructive**). Outputs:
`entities`, `layers`, `blocks`, `xrefs`, `layouts`, `selection`.

#### 2.2.5 Rhino (`h_rhino`)

`document` (dropdown, `rhino.list_open_docs`), `layers` (multi-chip,
`rhino.list_layers`), `geo_kind` (dropdown
`curves/surfaces/meshes/breps/points/blocks`), `tolerance`
(slider 0.001-10 mm), `selection_only` (toggle). Outputs: `curves`,
`surfaces`, `meshes`, `breps`, `points`, `blocks`, `selection`.

#### 2.2.6 Excel (`h_excel`)

`workbook` (dropdown, `excel.list_workbooks`), `worksheet` (dropdown,
depends_on=`workbook`), `range` (text, `A1:G47`), `named_range`
(dropdown, `excel.list_named_ranges`), `headers_row` (toggle),
`as_objects` (toggle). Outputs: `workbook`, `worksheet`, `range_values`,
`selection_range`.

#### 2.2.7 Remaining 12 hosts — brief

| Host | Pinned params | Outputs |
|------|---------------|---------|
| **3ds Max** | `document`, `selection_set`, `category_filter`, `render_view` | `objects`, `cameras`, `lights`, `materials`, `selection` |
| **Blender** | `file`, `collection`, `view_layer`, `selected_only` | `objects`, `collections`, `materials`, `selection` |
| **Photoshop** | `document`, `layers`, `mode` (RGB/CMYK), `dpi` | `document`, `layers`, `active_layer`, `selection_bbox` |
| **Illustrator** | `document`, `artboards`, `layers`, `swatch_lib` | `paths`, `artboards`, `swatches`, `selection` |
| **InDesign** | `document`, `spread_range`, `paragraph_style_filter` | `spreads`, `frames`, `styles`, `links` |
| **Word** | `document`, `style_filter`, `heading_range`, `track_changes` | `paragraphs`, `headings`, `tables`, `comments` |
| **PowerPoint** | `presentation`, `slide_range`, `layout_filter` | `slides`, `shapes`, `master`, `notes` |
| **Teams** | `team`, `channel`, `since`, `mention_only` | `messages`, `files`, `meetings`, `presence` |
| **Notion** | `workspace`, `database`, `filter_json`, `limit` | `pages`, `database_rows`, `selection` |
| **LM Studio** | `endpoint`, `model`, `temperature`, `max_tokens` | `model_info`, `completion`, `embedding` |
| **Antigravity** | `workspace`, `agent_id`, `task_filter` | `agents`, `tasks`, `events` |
| **Dropbox** | `account`, `path`, `recursive`, `extensions_filter` | `files`, `folders`, `revision_history` |

### 2.3 Outputs region

Each output port carries a Speckle-typed payload. Port type names extend
`PortType` (`app/workflows/graph.py:26-75`):

```python
# Add to PortType enum:
WALL          = "wall"            # Objects.BuiltElements.Wall
DOOR          = "door"            # Objects.BuiltElements.Door
WINDOW        = "window"          # Objects.BuiltElements.Window
ROOM          = "room"            # Objects.BuiltElements.Room
LEVEL         = "level"           # Objects.BuiltElements.Level
SHEET         = "sheet"           # Objects.BuiltElements.View
VIEW          = "view"            # Objects.BuiltElements.View
CURVE         = "curve"           # Objects.Geometry.Curve
SURFACE       = "surface"         # Objects.Geometry.Surface
MESH          = "mesh"            # Objects.Geometry.Mesh
BREP          = "brep"            # Objects.Geometry.Brep
EMAIL         = "email"           # ArchHub.Mail.Message
CALENDAR_EVT  = "calendar_event"  # ArchHub.Mail.CalendarEvent
RANGE_VALUES  = "range_values"    # ArchHub.Sheet.Range
PARAGRAPH     = "paragraph"       # ArchHub.Doc.Paragraph
SLIDE         = "slide"           # ArchHub.Slide.Slide
LAYER_RASTER  = "layer_raster"    # ArchHub.Raster.Layer (Photoshop)
LAYER_VECTOR  = "layer_vector"    # ArchHub.Vector.Layer (Illustrator)
```

Each port output is a `list[Base]` where `Base` is a Speckle-style dict
with `speckle_type`, `id`, `applicationId`, plus host-specific fields.
List ports carry their `len()` as `value_preview` (existing
`Edge.value_preview` mechanism in `graph.py:148`).

### 2.4 Wires-as-Speckle-connectors — auto-coerce rules

```
wall          → curve         : extract centerline
wall          → brep          : extract geometry
mesh          → brep          : fit-brep (lossy, warn)
brep          → mesh          : tessellate(tolerance from ui_config)
selection     → wall          : filter speckle_type=="Wall"
selection     → list port     : filter by speckle_type
range_values  → list          : flatten cells row-major
paragraph     → string        : join('\n')
email         → string        : .body_plaintext
ANY           → ANY           : pass-through
ANY           → STRING        : repr() (last-resort)
```

No auto-coerce → wire renders **dashed red** and the canvas inserts an
explicit converter-node placeholder (Grasshopper yellow-ribbon pattern).

Implementation hook: `app/workflows/typesystem.py` extends with a
`COERCERS: dict[tuple[PortType, PortType], Callable]` table — e.g.
`(WALL, CURVE): lambda walls: [w["centerline"] for w in walls]`.

### 2.5 What shows / hides per user config

`Workflow.ui_config` schema:

```jsonc
{
  "host_display": {
    "revit": {
      "show_advanced": false,
      "hidden_params": ["bounding_view", "include_linked"],
      "pinned_params": ["active_view", "category_filter"],
      "compact_mode": false,
      "show_preview_footer": true
    },
    "outlook": {
      "hidden_params": ["mark_read"],
      "pinned_params": ["folder", "unread_only"]
    }
  },
  "wire_style": "speckle"   // "speckle" | "minimal" | "thick"
}
```

Stored at: `Workflow.metadata["ui_config"]` (existing `metadata` dict on
`Workflow` line 216 of `graph.py`). Surfaces in `SettingsDialog` under
new "Host display" tab — checkbox grid per host, drag-to-reorder for
pinning, "Reset to defaults" button. Read by `HostNodeBody` at render time.

### 2.6 Visual treatment

- Node body width: dynamic — `min(360, max(280, longest_label_px + widget_px + 64))`
- Parameter row height: 24 px collapsed, 28 px when widget is slider or chips
- Group dividers: 1 px `LM.lineSoft` line + 8.5 px mono caps label `LM.inkMuted`
- Inline preview region: 64 px footer with format-aware thumb (plan SVG /
  table / image) — TouchDesigner pattern
- Collapsed mode: header + pinned params (max 3) + 32 px preview
- Expanded mode: all params, scrollable above 8 rows, grouped, with
  in-node search bar (`/`-keystroke)
- Disabled state: opacity 0.5, `cursor:not-allowed`, lock glyph in header,
  underline-link "Connect…" replaces refresh pulse

---

## 3. Interaction patterns

**Bind upstream wire to a param.** Right-click param → "Drive from wire…"
→ modal of type-compatible upstream ports. Pick → row replaces widget with
a wire chip `← src_node.port`. Houdini channel-reference pattern.

**Promote param to Skill facade.** Right-click → "Expose to Skill inputs"
→ appears on the Skill's outer face. Houdini HDA + Substance `expose`.

**Param search.** Type `/` while node focused → in-header search filters
rows. n8n pattern.

**AI fill per param.** Each row has a `✦` glyph; click → agent reads
upstream context + `help` text + last user intent → proposes ghost-text;
user Enter/Esc. **This is how AI orchestrates instead of replacing — the
founder's exact framing.**

**Live edit.** Drag a slider → runner re-cooks downstream lazily via
existing `runner.pull` (`app/workflows/runner.py`). ComfyUI pattern.

**Destructive confirm.** Params with `destructive: true` (e.g.
`mark_read`, `purge_unreferenced`) require a confirm checkbox before cook,
session-scoped.

**Drag-wire-onto-param.** TouchDesigner gesture — drop the loose wire end
on a param row, not just the input socket. Extend hit-test in `studio-lm.jsx`
wire-drag (~line 3160) to include param rows.

---

## 4. Architectural diff for ArchHub

### 4.1 `app/workflows/graph.py:Node` — schema additions (~40 LOC)

```python
@dataclass
class Node:
    # ... existing fields ...
    param_schema: list[ParamDef] = field(default_factory=list)  # NEW
    param_values: dict = field(default_factory=dict)            # NEW — split from `config`
    ui_config: dict = field(default_factory=dict)               # NEW — per-instance override
    host_status: str = "unknown"                                # NEW — live|offline|stale|probing|unauth|unknown
    host_last_probe: str = ""                                   # NEW — ISO ts
```

Backward-compat: `from_dict` defaults to empty `param_schema` and reads
existing `config` as `param_values`.

### 4.2 New `app/workflows/param_schemas/` directory (~1200 LOC)

`__init__.py` (registry: `PARAM_SCHEMAS[host_id] → list[ParamDef]`),
`_types.py` (ParamDef + option_source registry, ~80), `option_sources.py`
(broker-facing callables). One file per host: `revit.py` (180),
`outlook.py` (80), `speckle.py` (100), `autocad.py` (110), `rhino.py` (90),
`max.py` (80), `blender.py` (80), `photoshop.py` / `illustrator.py` /
`indesign.py` / `word.py` / `powerpoint.py` / `lmstudio.py` /
`antigravity.py` / `dropbox.py` (70 each), `excel.py` (80), `teams.py` (80),
`notion.py` (90).

### 4.3 `studio-lm.jsx` — replace `HostBody` (~720 LOC)

Replace `studio-lm.jsx:3910-3920` with `HostNodeBody`:

```jsx
const HostNodeBody = ({ n }) => {
  const schema = useParamSchema(n.hostId);
  const cfg = useUiConfig(n.hostId);
  const visible = filterVisible(schema, n.params, cfg);
  return (<div>
    <HostStatusStrip n={n}/>
    {groupByGroup(visible).map(g => <ParamGroup key={g.id} group={g}/>)}
    <HostPreviewFooter n={n}/>
  </div>);
};
```

### 4.4 New `app/web_ui/widgets/` JSX modules (~900 LOC)

`Slider.jsx` (120, numeric + unit + min/max), `Dropdown.jsx` (140,
async-populated, search-in-list), `ChipMulti.jsx` (150, multi-select +
x-to-remove), `Picker.jsx` (130, click-to-pick-in-host button),
`Toggle.jsx` (60), `ColorPicker.jsx` (110), `FilePicker.jsx` (100),
`TextField.jsx` (50), `ParamRow.jsx` (40, wrapper + ✦ AI button).

### 4.5 `app/bridge.py` — new slots (~280 LOC)

```python
@Slot(str, str, result=str)
def get_host_params(host_id: str, session_id: str) -> str:
    """JSON-encoded param_schema for a host node at instantiation time."""

@Slot(str, str, str, result=str)
def list_host_options(host_id: str, param_id: str, context_json: str) -> str:
    """Resolve an options_source on-demand. Cached by (host_id, param_id, ctx_hash)."""

@Slot(str, str, str, result=bool)
def set_host_param(node_id: str, param_id: str, value_json: str) -> bool:
    """Update one param value; sets node dirty; triggers downstream re-cook."""

@Slot(str, result=str)
def probe_host_status(host_id: str) -> str:
    """live | offline | stale | probing | unauth — cached 3s."""

@Slot(str, result=str)
def ai_fill_param(node_id: str, param_id: str) -> str:
    """Per-param ✦ agent — proposes a value from upstream context."""
```

### 4.6 WIRE color map — rebuild against Speckle taxonomy (~80 LOC)

Replace `studio-lm.jsx:39-43`:

```jsx
const WIRE = {
  // Speckle BuiltElements — warm orange family
  wall:'#E87D0D', door:'#E87D0D', window:'#E87D0D', room:'#E87D0D',
  level:'#C66C0A', sheet:'#C66C0A', view:'#C66C0A',
  // Speckle Geometry — cyan family
  curve:'#0696D7', surface:'#0696D7', mesh:'#0696D7', brep:'#0696D7',
  // ArchHub-Mail — Outlook blue
  email:'#0078D4', calendar_event:'#0078D4',
  // ArchHub-Sheet — Excel green
  range_values:'#107C41', csv:'#107C41',
  // ArchHub-Doc — Word blue
  paragraph:'#2B579A', slide:'#B7472A',
  // Raster/Vector — Photoshop / Illustrator
  layer_raster:'#31A8FF', layer_vector:'#FF9A00',
  // Control — Unreal white
  exec:'#FFFFFF',
  // Untyped — soft grey
  any:'#7d7466',
};
```

### 4.7 Estimated total LOC

| Piece                                | LOC      |
|--------------------------------------|----------|
| `graph.py` schema additions          | ~40      |
| `param_schemas/` directory           | ~1200    |
| `HostNodeBody` + helpers in JSX      | ~720     |
| `widgets/` JSX modules               | ~900     |
| `bridge.py` slots                    | ~280     |
| WIRE map + coercers                  | ~120     |
| Tests                                | ~400     |
| **Total**                            | **~3660**|

---

## 5. Six-week host-node delivery plan

| Wk | Theme | Files (function-level) | Ship gate | LOC |
|---|---|---|---|---|
| **1** | ParamDef schema + 3 widgets + 2 schemas + HostNodeBody | `graph.py:Node` (40), `_types.py` (80), `{revit,outlook}.py` (260), `widgets/{Slider,Dropdown,Toggle,ParamRow}.jsx` (370), `HostNodeBody` (280), `bridge.py:get_host_params/set_host_param/probe_host_status` (140) | Revit host renders 9 typed params; slider drag updates; refresh probes broker | ~1170 |
| **2** | ChipMulti + Picker + Speckle/Rhino/AutoCAD schemas + wire-bind | `{ChipMulti,Picker,TextField}.jsx` (280), `{speckle,rhino,autocad}.py` (300), wire-drop-on-param hit-test (120), `list_host_options` cache (80) | Right-click param → "Drive from wire" attaches upstream port | ~780 |
| **3** | Preview footer + status + auto-refresh + Test step | `HostPreviewFooter+HostStatusStrip` (260), `probe_host_status` polling (60), per-host preview renderers (220), pulse button (40) | Every host shows live thumb + status dot + last-sync; Test step fires one-shot cook | ~580 |
| **4** | Remaining 12 hosts | `{max,blender,photoshop,illustrator,indesign,word,excel,powerpoint,teams,notion,lmstudio,antigravity,dropbox}.py` (880), broker/MCP stubs (200) | All 18 hosts render HostNodeBody with ≥4 typed params each | ~1080 |
| **5** | Per-user `ui_config` + Host Display tab + visible_if | `Workflow.metadata["ui_config"]` (60), `SettingsDialog` Host Display tab (220), `visible_if` evaluator (60), pinned/hidden state (120) | Toggle "show advanced" → 4 Revit params show/hide; pinned reorder | ~460 |
| **6** | Speckle wire colors + auto-coerce + destructive confirm + AI fill | `WIRE` rebuild (120), `typesystem.py:COERCERS` (180), destructive gate in `runner.py` (60), `ai_fill_param` (80), `ParamRow ✦` (60) | `walls` wire → `curves` input auto-coerces to centerlines; ✦ proposes values | ~500 |
| | **Total** | | | **~4570** |

---

## 6. Four ASCII mockups — Revit host node, four states

### 6.1 Live + collapsed (header + 3 pinned params + thumb)

```
┌───────────────────────────────────────────────────────────┐
│ [R] REVIT 2025 · Tower-A_central.rvt    ●LIVE 12s   [↻] [⌃]│
├───────────────────────────────────────────────────────────┤
│  ACTIVE VIEW                                              │
│  [▼ L01-Floor-Plan-Architectural   ]              ✦       │
│                                                           │
│  CATEGORIES                                               │
│  [walls ×][doors ×][windows ×][+]                 ✦       │
│                                                           │
│  LIMIT TO ACTIVE VIEW                                     │
│  [● ON  ]                                                 │
│                                                           │
│  ┌───────────────────────────────────────────────────┐    │
│  │  ▓▓▓░░░▓▓▓░░░▓▓▓  preview: 47 walls (L01)        │    │
│  └───────────────────────────────────────────────────┘    │
├───────────────────────────────────────────────────────────┤
│ walls ●─    doors ●─    windows ●─    rooms ●─            │
│ levels ●─   sheets ●─   selection ●─                       │
└───────────────────────────────────────────────────────────┘
```

### 6.2 Live + expanded (full param list grouped + thumb + footer)

```
┌───────────────────────────────────────────────────────────┐
│ [R] REVIT 2025 · Tower-A_central.rvt    ●LIVE 12s   [↻][⌄]│
├───────────────────────────────────────────────────────────┤
│  [/ search params…                                       ]│
│                                                           │
│  ── DOCUMENT ──                                           │
│  Document          [▼ Tower-A_central.rvt        ] ✦      │
│  Active view       [▼ L01-Floor-Plan-Arch        ] ✦      │
│  Phase             [▼ New Construction           ] ✦      │
│  Worksets          [Shared Levels ×][Arch ×][+]    ✦      │
│                                                           │
│  ── FILTER ──                                             │
│  Discipline        [▼ Architecture               ] ✦      │
│  Categories        [walls ×][doors ×][windows ×]   ✦      │
│  Limit to view     [● ON  ]                               │
│                                                           │
│  ── PERFORMANCE ──                                        │
│  Element limit     [────●──────────] 500 / 10000   ✦      │
│                                                           │
│  ── ADVANCED ── (show_advanced=true)                      │
│  Include linked    [○ OFF ]                               │
│                                                           │
│  ┌───────────────────────────────────────────────────┐    │
│  │ ┌─────────────────┐  47 walls · 12 doors          │    │
│  │ │  plan SVG thumb │  8 windows · 4 rooms          │    │
│  │ │  ▓▓░░▓░░▓▓░░    │  Cooked 12s ago · 480ms       │    │
│  │ └─────────────────┘  by agent:claude-sonnet-4.6   │    │
│  └───────────────────────────────────────────────────┘    │
├───────────────────────────────────────────────────────────┤
│ walls ●─    doors ●─    windows ●─    rooms ●─            │
│ levels ●─   sheets ●─   families ●─   selection ●─        │
│ warnings ●─ events ●─                                     │
└───────────────────────────────────────────────────────────┘
```

### 6.3 Missing (broker offline) — disabled visual treatment

```
┌╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴┐ ← dimmed border
╎ [R] REVIT 2025 · (no document)         ✕OFFLINE   [Connect…]╎
├╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴┤
╎                                                            ╎
╎   🔒  Broker not reachable on port 48884.                  ╎
╎       Open Revit and load the ArchHub connector,           ╎
╎       or [Switch to Revit 2024] (port 48886).              ╎
╎                                                            ╎
╎   Last successful probe: 6 minutes ago                     ╎
╎   Last known: Tower-A_central.rvt · 47 walls               ╎
╎                                                            ╎
╎   ┌──────────────────────────────────────────────────┐     ╎
╎   │  (preview unavailable — host disconnected)       │     ╎
╎   └──────────────────────────────────────────────────┘     ╎
├╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴┤
╎ walls ○─    doors ○─    windows ○─    (cached, stale)      ╎
└╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴╴┘
       all params disabled · opacity 0.5 · cursor:not-allowed
```

### 6.4 AI-filling (✦ on a param while agent proposes)

```
┌───────────────────────────────────────────────────────────┐
│ [R] REVIT 2025 · Tower-A_central.rvt    ●LIVE 12s   [↻][⌃]│
├───────────────────────────────────────────────────────────┤
│                                                           │
│  ACTIVE VIEW                                              │
│  [▼ L01-Floor-Plan-Architectural   ]              ✦       │
│                                                           │
│  CATEGORIES                                               │
│  [walls ×][doors ×][windows ×][+]                 ✦       │
│                                                           │
│  ELEMENT LIMIT                              ✦◌ thinking…  │ ← agent active
│  ┌──────────────────────────────────────────────────┐     │
│  │ ✦ propose 250 (matches your last 3 schedule runs)│     │
│  │   [Accept ↵]    [Reject Esc]    [More options ⌄]│     │
│  └──────────────────────────────────────────────────┘     │
│                                                           │
│  ┌───────────────────────────────────────────────────┐    │
│  │  ▓▓▓░░░▓▓▓░░░ preview frozen — awaiting accept    │    │
│  └───────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
```

---

## 7. Honest pushback / risks

**What's likely to fail in execution.**

1. **Option-source latency.** `revit.list_categories` over a 200 MB central
   file hits the broker via pywin32/RPC at 800-2000 ms. Without caching +
   a shimmer treatment, every dropdown click feels broken. Mitigation:
   `list_host_options` caches `(host_id, param_id, ctx_hash)` for 30 s;
   refresh pulse forces re-fetch.

2. **18 host schemas is real work.** ~1200 LOC of declarative spec, but each
   `options_source` needs a working broker/COM/MCP path. Hosts without
   brokers today (Photoshop, Illustrator, InDesign, Word, Teams, Notion,
   Antigravity, Dropbox) need probe stubs returning cached fixtures so the
   UI doesn't block. Budget a half-week of "fake but typed" stubs.

3. **`visible_if` is eval-not-exec.** Tempting to allow arbitrary Python;
   the safe path is a tiny expression parser (op + atom + literal),
   ~80 LOC. Do *not* call `eval()`.

4. **`ui_config` is a UX black hole.** Settings that "hide things by default"
   lead users to assume the product is broken. The default state for every
   param is visible; `ui_config` is power-user add-on, not the gate. Mirror
   Houdini: spare-params *add*, never subtract from the basic view.

**What ArchHub should NOT add even though it's tempting.**

1. Full Houdini expression language on every param (`ch("/obj/box/tx")`).
   Too much surface; drag-a-wire-onto-param + AI fill cover the cases.
2. A separate right-side Details panel (Unreal pattern). Splits attention
   from the canvas + composer; keep everything on the node body (ComfyUI).
3. Auto-record-to-Skill. Captures button-press sequences instead of
   intent. Save-as-Skill stays agent-mediated.
4. Per-firm `ui_config` in the cloud. Per-architect local only; firm-wide
   is a v2 problem.

**Conflicts with the reframe report.**

1. Reframe says `cell.intent` collapses 60 of 80 nodes. Under this grammar
   **host nodes do not collapse** — they expand. The collapse applies to
   filter/transform/intent nodes; host-bound resource/tool nodes stay
   richly parameterised. Cells collapse, hosts expand.
2. Reframe says "agent fills everything." Under this grammar AI fills
   *per param*, not per node. Resolve: ✦ AI fill fires automatically on
   composer-spawned new nodes, but **manual edit is first-class** afterward.
3. Reframe's 80 px cell strip cannot host the 320-520 px expanded host body.
   Resolve: cell strip stays as the *bottom rail* of the host node (intent +
   last-value preview footer), param block above it.

---

## 8. Closing verdict

**A node** is a typed memory cell **with a rich declarative control surface**
on its body. The architect grips every parameter directly — sliders,
dropdowns populated from the live host, chips, pickers, toggles — and the
surface is configurable per user. The cell still holds `(formula, last_value,
format, deps)`; the *formula* is now a `param_schema + param_values` pair,
not a single intent string.

**A wire** is a Speckle-typed data transport between programs. Port types
map onto Speckle Base sub-classes; wires carry typed payloads; mismatched
types auto-coerce (centerline extraction, tessellation) or render dashed-red
and demand an explicit converter node.

**The agent** is the co-pilot on the controls, not the operator. AI fills
one parameter at a time on demand (✦) using upstream context and stated
intent. AI proposes sub-graphs in the composer chips view as today, and
**never mutates a parameter without the architect's accept**.

**Refines the reframe report.** The reframe was correct that nodes are
memory cells, wires are read-declarations, and Skills are agent-readable
directories. It was incomplete on the *interaction grammar* — treating the
cell strip as the whole UI and assuming AI fills the formula. This document
specifies the missing 90% of the host-node surface: typed params, widgets,
options sources, per-user visibility, Speckle wire typing, and the four
canonical states (live-collapsed / live-expanded / offline / AI-filling).
The three-way kind split (resource / cell / tool) survives; every kind
renders a control surface, not a four-line readout. The 27-node minimum
from the reframe holds — but each survivor gets a rich, configurable
parm dialog.

**The single biggest move.** Add `param_schema` to `Node`, ship Slider /
Dropdown / Toggle widgets, replace `HostBody` at `studio-lm.jsx:3910-3920`
with `HostNodeBody`, write Revit + Outlook schemas. W1 ship; visible proof.

---

*End of host-node UI grammar report. Author: senior product/UX lead,
ArchHub · 2026-05-15. Refines `docs/NODE_RND_REFRAME_2026-05-15.md`.*
