# ArchHub Visual Canvas — Architecture (shipped v1.4)

_Last update: 2026-05-14. Sections marked **HISTORICAL** describe the
v0.18 NodeGraphQt plan that was superseded by the v1.0 JSX rewrite.
Sections marked **CURRENT** describe what actually ships in v1.4._

## 0. TL;DR (CURRENT — v1.4)

- Canvas is the **primary surface**. Chat is one node type among
  many; conversations live as `i_conv` nodes on the same graph.
- Built on **React + Babel + QtWebEngine** (`app/web_ui/studio-lm.jsx`,
  ~5 k LOC). Python ↔ JSX talks via 115+ `@pyqtSlot` bridges on
  `app/bridge.py`.
- **Session = canvas.** One slug, one persistent autosaved graph,
  one URL. Switching session swaps the workspace.
- **80 node types across 10 categories** (host / read / filter /
  transform / annotate / compose / logic / AI / output / trigger) —
  see `docs/NODE_LIBRARY_v2.md`.
- **18 host families** detected by `app/host_detector.py` + brokers,
  surfaced as the canvas host-pill row.
- **AI-agent composer** (`bridge.agent_step`) — NL intent → 7-tool
  schema → graph mutation chips.

## 0b. TL;DR (HISTORICAL — v0.18 plan)

- Canvas was a **read+edit surface** over the existing `Workflow` JSON. It did not replace it, did not own state, and was opt-in. ComfyUI under the hood; chat on top.
- Built on **NodeGraphQt (jchanvfx)** — MIT, Qt6-supporting fork available, an order of magnitude less code than rolling our own QGraphicsScene, and fits the registry-driven palette pattern out of the box.
- Phased: v0.18 read+run+edit existing Skills; v0.19 build new Skills from scratch; v0.20+ multi-select / frames / search palette.

**Why we replaced NodeGraphQt with JSX:** QtWebEngine + React lets one
rendering pipeline cover both desktop and the future hosted web build,
the design language ports cleanly from the prototype Figma JSX files,
DevTools + hot-reload (F5) shortens iteration loops, and the wire
layer (28 px snap, hover preview, body-drop, refusal toast) is
substantially less code in pointer-events JS than `QGraphicsItem`
hit-testing. The NodeGraphQt branch was archived, not deleted.

---

## 1. Library choice

### Candidates

| Lib | License | Qt6 | Last commit | Stars | Bundle | Verdict |
|---|---|---|---|---|---|---|
| **NodeGraphQt** (jchanvfx) | MIT | Yes via maintained forks (PySide6/PyQt6); upstream has Qt6 branches | active 2024-2025 | ~1.4k | ~2-3 MB | **Recommended** |
| QtPyNodeEditor / hand-roll | MIT/BSD | Yes | N/A — you write it | 0 | ~300 KB | More control, 5-10× more LOC, no ecosystem |
| pyflow / PyFlow | Apache 2.0 | Qt5 only canonical; partial Qt6 in forks | last canonical 2019 | ~1.2k | ~5 MB | Stale + scope mismatch (pyflow is a workflow runtime, we already have one) |

#### Detailed scoring

(a) **MIT-compatibility** — All three are permissive. NodeGraphQt is MIT, drops cleanly into our open-core (STRATEGY.md: "MIT or Apache 2.0").

(b) **PyQt6 support** — NodeGraphQt's upstream targets `Qt.py` (PyQt5/6 + PySide2/6). Vendor a known-good fork at a pinned SHA.

(c) **Ergonomics** — NodeGraphQt's `BaseNode`+`NodeGraph` API maps cleanly to our `NodeSpec`/`Node`. Each registered `NodeSpec` becomes a NodeGraphQt node class generated at runtime; ports map 1:1; node config maps to NodeGraphQt's "properties bin." Adapter is ~250 LOC. Hand-roll: ~1500 LOC for equivalent.

(d) **Maintenance signal** — NodeGraphQt's fork ecosystem is healthy. pyflow upstream is dead since 2019.

(e) **Bundle size** — NodeGraphQt is pure Python + small SVG/icons. ~2-3 MB. Negligible.

### Recommendation

**Use NodeGraphQt, vendored.** Pin a Qt6-compatible fork at a SHA in `app/vendor/nodegraphqt/`. Reasons:

1. Registry-driven palette (req #4) is one method on `NodeGraph.register_node()`. Hand-roll = full node-class generator.
2. Drag-from-palette, pan/zoom, snap-to-grid, port hit-testing, bezier wiring, undo hooks, copy/paste serialization for free.
3. Vendoring insulates from upstream drift.

**Escape hatch:** the adapter is the only code that touches NodeGraphQt's API directly. If NodeGraphQt rots, the adapter is the only thing to rewrite — ~250 LOC.

---

## 2. Architecture

### Layer diagram

```
   ┌─────────────────────────────────────────────────────────┐
   │  WorkflowCanvasDialog  (canvas_panel.py)                │
   │   palette ◀──────────  NodeGraphView (NodeGraphQt)      │
   │                       ▲                                  │
   │                       │  signals: node_added/moved/      │
   │                       │           connected/removed      │
   │                       ▼                                  │
   │  WorkflowGraphAdapter  (canvas_adapter.py)               │
   │     Workflow ◀──to_canvas──▶ NodeGraph state            │
   └─────────────────────────────────────────────────────────┘
                         │
                         ▼
               app/workflows/ (UNCHANGED)
                  graph.py  executor.py  registry.py
```

**Key principle: the `Workflow` dataclass is the single source of truth.** The canvas is a view+editor on top. Every user action mutates the `Workflow` first, then refreshes the canvas. Serialization always goes from `Workflow.to_dict()`.

### `WorkflowGraphAdapter` (new `app/canvas/adapter.py`)

```python
class WorkflowGraphAdapter:
    """Bidirectional bridge: Workflow <-> NodeGraphQt scene."""

    def __init__(self, graph: "NodeGraph"):
        self._graph = graph
        self._wf: Workflow | None = None
        self._node_by_wfid: dict[str, "BaseNode"] = {}

    def load(self, wf: Workflow) -> None:
        """Wipe scene and rebuild from wf. Called on open + on undo."""

    def to_workflow(self) -> Workflow:
        """Snapshot the scene into a fresh Workflow. Called on Save +
        before Run. Position dict is read straight from each NodeGraph
        node's pos()."""

    # --- live edit hooks (incremental, don't wipe) ---
    def on_node_added(self, qt_node) -> None: ...
    def on_node_moved(self, qt_node, pos) -> None: ...
    def on_edge_connected(self, src_port, dst_port) -> None: ...
    def on_edge_disconnected(self, edge) -> None: ...
    def on_node_removed(self, qt_node) -> None: ...
```

### Undo/redo

NodeGraphQt ships a `QUndoStack`. Wire it as the canvas's undo source. Adapter pushes commands like `AddNodeCmd`, `MoveNodeCmd`, `ConnectEdgeCmd`, each mutating the `Workflow` dataclass on `redo()` and reversing on `undo()`. **Do not let NodeGraphQt's internal undo stack mutate scene without going through the adapter** — otherwise `Workflow` and scene drift apart.

Memory bound: cap at 100 entries.

### Node positions

`Node.position: dict {"x": float, "y": float}` exists in `graph.py:70`. Adapter writes scene `pos()` back on every move event, debounced 100 ms. On save, positions land in JSON unchanged. On load, missing positions auto-layout via fallback (Sugiyama-lite, see §9 v0.18).

### Running from canvas

Run button calls `adapter.to_workflow()` then hands the workflow to the **same** `WorkflowExecutor` the chat uses. Reuse `_SkillRunWorker` from `chat_window.py` — extract to `app/workflows/run_worker.py` so canvas and chat both import.

```python
def _on_run(self):
    wf = self.adapter.to_workflow()
    errs = wf.validate()
    if errs:
        self._show_errors_overlay(errs)
        return
    inputs = self._collect_inputs(wf)
    self._worker = SkillRunWorker(wf, inputs, self.router, self.tools, self.manager)
    self._worker.event_received.connect(self._on_exec_event)
    self._worker.finished.connect(self._on_exec_done)
    self._worker.start()
```

The executor's `ExecutionEvent` stream feeds the live overlay (§5).

---

## 3. UI surface

Canvas lives **behind the cog**, never in the header. Two entry points:

1. **Skill card → "Edit graph"** — replaces today's "Edit" button which only opens the JSON tab. Opens canvas with the skill's workflow loaded.
2. **Cog menu → "✎ New workflow on canvas…"** — slotted between "Skills…" and "Sessions…". Opens an empty canvas with `Workflow.new()`.

The JSON tab in the Skills panel **stays** as the power-user fallback.

### Wireframe

```
┌──────────────────────────────────────────────────────────────────────┐
│ ArchHub — Edit Skill: "Dimension walls"                          [×] │
├──────────────────────────────────────────────────────────────────────┤
│ ▢ Save  ▢ Save & Close  ▢ Run ▶  ▢ Validate  ▢ Auto-layout  …   │
├──────────────┬───────────────────────────────────────┬───────────────┤
│  PALETTE     │       CANVAS  (NodeGraphQt view)      │  PROPERTIES   │
│              │                                       │               │
│  ▾ io        │     ┌─────┐   ┌─────────┐  ┌──────┐  │  Selected:    │
│   ↳ Input    │     │ in  │──▶│ template│─▶│ llm  │  │  llm.complete │
│   ↴ Output   │     └─────┘   └─────────┘  └──────┘  │  ────────────  │
│  ▾ data      │                              │       │  model: auto  │
│   • Const    │                              ▼       │  prompt: …    │
│   ¶ Template │                            ┌────┐    │  allowed_     │
│  ▾ llm       │                            │out │    │  tools: [ ]   │
│   ✦ Complete │                            └────┘    │               │
│   ◈ +tools   │                                      │               │
│   ? Classify │                                      │  [Apply]      │
│  ▾ control   │                                      │               │
│  ▾ tool      │                                      │               │
│   (auto)     │                                      │               │
│              │                                       │               │
│  search…     │                                       │               │
└──────────────┴───────────────────────────────────────┴───────────────┘
│ ◉ ready    nodes: 4    edges: 3    last run: 1.2s ✓        validated │
└──────────────────────────────────────────────────────────────────────┘
```

Glass-dark theme matches the rest. Reuse existing QSS objectNames.

### Modal vs non-modal

**Modal** for v0.18, like SkillsPanel. Reasons: chat is primary surface, opening canvas is explicit, modal sidesteps multi-window state sync. v0.20+ may make it dockable.

---

## 4. Node palette

**Rule: palette is generated from the registry. Never hand-maintained.**

```python
def _build_palette(self) -> QWidget:
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    by_category = registry.all_specs_by_category()
    order = ["io", "data", "llm", "tool", "speckle", "control"]
    for cat in order + [c for c in by_category if c not in order]:
        if cat not in by_category:
            continue
        cat_node = QTreeWidgetItem(tree, [cat])
        cat_node.setExpanded(True)
        for spec in sorted(by_category[cat], key=lambda s: s.display_name):
            it = QTreeWidgetItem(cat_node, [f"{spec.icon}  {spec.display_name}"])
            it.setData(0, Qt.UserRole, spec.type)
            it.setToolTip(0, f"<b>{spec.display_name}</b><br>{spec.description}")
    return tree
```

### Drag-to-canvas

Wire `tree.startDrag` to encode spec's `type` string as MIME `application/x-archhub-nodetype`. Canvas accepts drop, reads type, instantiates registered NodeGraphQt class, calls `adapter.on_node_added` with default config from `spec.config_schema`.

### Generated NodeGraphQt classes

At canvas startup, register one `BaseNode` subclass per `NodeSpec`. Cached by `spec.type`. Inputs/outputs from `spec.inputs/outputs`; port colours map to `PortType` (string=blue, geometry=green, image=magenta, tool_result=orange, any=gray). Two lines per NodeSpec — full loop ~30 LOC.

Search box at bottom of palette filters by `display_name + description`. v0.19.

---

## 5. Live execution overlay

Reuse executor's `ExecutionEvent` stream:

| Event | State | Visual |
|---|---|---|
| (initial) | `idle` | default theme |
| `node_started` | `running` | terracotta border (#cc785c), pulsing 1.0 Hz |
| `node_finished` | `done` | muted green border, fades after 4 s |
| `node_failed` | `failed` | red border, persistent until next run; tooltip shows `detail` |
| run finished (success) | rest stay `done` | toolbar shows `✓ 1.4s` |
| run finished (failed) | failed node stays red | toolbar shows `✗ <first error>` |

Status bar mirrors `SkillStepperCard` semantics — consistent state whether ran from chat or canvas.

Cancel mid-run: out of scope v0.18. Document gap.

---

## 6. Save flow

```python
def _on_save(self) -> bool:
    wf = self.adapter.to_workflow()
    errs = wf.validate()
    if errs:
        self._show_errors_overlay(errs)
        return False
    if skills.is_skill(wf):
        meta = skills.get_meta(wf)
        skills.save_skill(wf, meta)
    else:
        save_workflow(wf)
    self.statusBar().showMessage("Saved.", 3000)
    self._dirty = False
    return True
```

Validation is non-negotiable: `Workflow.validate()` already catches dangling edges, missing ports, cycles. Invalid → overlay + abort.

Auto-push: `skills.save_skill` already triggers cloud sync. **No new sync code needed.**

Dirty-tracking: `self._dirty = True` on any adapter mutation; ask-on-close if dirty.

---

## 7. Power-user features (v0.20+)

| Feature | Lib support | Effort |
|---|---|---|
| Multi-select (rubber-band, shift-click) | NodeGraphQt built-in | 0 LOC |
| Align selection (top/left/centre) | none | ~80 LOC |
| Search palette (Cmd+K) | none | ~150 LOC |
| Copy-paste subgraphs | NodeGraphQt clipboard JSON | ~120 LOC |
| Comment blocks | NodeGraphQt `BackdropNode` | ~40 LOC |
| Frame nodes (group + label) | NodeGraphQt `BackdropNode` resized | ~80 LOC |
| Mini-map | NodeGraphQt built-in | 0 LOC |
| Port preview tooltips (last value) | we add | ~100 LOC |

Out of scope canvas v1: real-time collab, multi-page graphs, sub-graphs as first-class nodes.

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NodeGraphQt + PyQt6 + Python 3.11 + Trusted Signing breaks at install | Medium | High | Vendor pinned fork. CI matrix smoke-tests canvas against PyQt 6.6 / 6.7 on Windows. |
| Performance with 50+ nodes | Medium | Medium | Disable node antialiasing at zoom <0.5; `QGraphicsItem.ItemUsesExtendedStyleOption=False`; no repaint on hover. |
| Undo stack memory blow-up | Low | Medium | Cap at 100; deep-copy via `pickle.dumps(wf)` is sub-MB. |
| DPI scaling | High | Medium | Read `devicePixelRatio()` at canvas init; scale node sizes. Don't trust NodeGraphQt defaults. |
| Workflow ↔ canvas drift | Medium | High | All mutations route through adapter. Debug-only `assert adapter.invariant()` after every command. |
| Two skills in two windows + global undo | Medium | Medium | One canvas at a time in v0.18 (modal). |
| Drag-from-palette drops off-canvas | Low | Low | Constrain drop target to scene viewport. |
| User edits JSON in Workflows tab while canvas open | Low | Medium | Disable JSON edit while canvas open on same skill id. |
| `tool.*` node specs change at runtime | Medium | Low | Re-read registry on canvas open, not at app boot. |
| Auto-layout produces noisy graphs | High | Low | Sugiyama-lite layout (left→right by topo level, vertical sibling spacing). |
| Vendored fork goes stale, has CVE-grade Qt bug | Low | High | Adapter isolates dep. Replacement plan: hand-roll QGraphicsScene equivalent ~1500 LOC. |

---

## 9. Phasing

### v0.18 — Read + Run + Edit existing skills

Goal: open any existing Skill from cards panel, see as graph, tweak node configs, save, run. **No new-from-scratch yet.**

Files to add:
- `app/canvas/__init__.py` (5 LOC)
- `app/canvas/adapter.py` — `WorkflowGraphAdapter` (~300 LOC)
- `app/canvas/canvas_panel.py` — `WorkflowCanvasDialog` modal, palette, properties, toolbar (~500 LOC)
- `app/canvas/node_factory.py` — auto-generate NodeGraphQt classes from `NodeSpec` (~150 LOC)
- `app/canvas/properties_form.py` — render `config_schema` as QFormLayout (~250 LOC)
- `app/canvas/layout.py` — Sugiyama-lite auto-layout (~120 LOC)
- `app/vendor/nodegraphqt/` — vendored library at pinned SHA

Files to modify:
- `app/skills_panel.py` — `SkillCard.edit_clicked` opens canvas (~30 LOC)
- `app/chat_window.py` — extract `_SkillRunWorker` to `app/workflows/run_worker.py` (~80 LOC moved)
- `app/main.py` — register canvas open hook after node registration (~5 LOC)
- `requirements.txt` — pin Qt.py if vendored fork needs it (~5 LOC)

Tests:
- `tests/test_canvas_adapter.py` — round-trip preservation (~200 LOC)
- `tests/test_canvas_smoke.py` — open canvas with each starter Skill, run, expect green tick (~150 LOC)

**~1900 LOC + vendored NodeGraphQt. ~2-3 weeks for one engineer with PyQt6 fluency.**

### v0.19 — Build new workflows from scratch

Goal: cog menu → "New workflow on canvas" → empty canvas → drag → wire → save → appears as Skill.

Files to add:
- `app/canvas/new_skill_dialog.py` — name + intent + scope picker (~120 LOC)

Files to modify:
- `app/chat_window.py` — add menu entry `_open_new_canvas` (~20 LOC)
- `app/canvas/canvas_panel.py` — accept `wf=None` for empty (~40 LOC)
- `app/canvas/canvas_panel.py` — palette search box (~50 LOC)
- `app/canvas/properties_form.py` — handle `data.constant` value editor (~80 LOC)
- `app/canvas/canvas_panel.py` — port-type compatibility check on connect (~60 LOC)

Tests:
- `tests/test_canvas_new_skill.py` — build four-node chain entirely on canvas (~180 LOC)

**~370 LOC + ~180 LOC tests. ~1 week.**

### v0.20+ — Power-user features

| Feature | LOC | Effort |
|---|---|---|
| Multi-select align/distribute | 120 | 1 day |
| Search palette (Cmd+K) | 150 | 1 day |
| Copy/paste subgraph | 200 | 2 days |
| Backdrop / frame nodes | 120 | 1 day |
| Mini-map toggle | 30 | 1 hour |
| Port preview tooltips | 150 | 2 days |
| Cancel mid-run | requires executor changes (~200 LOC) | 3 days |
| Auto-format / auto-layout button | 80 | 1 day |

**~1100 LOC.** Cherry-pick by user demand.

---

## 10. Out of scope (explicit)

- Real-time collaborative editing.
- Mobile / tablet canvas.
- Web-based canvas (React Flow). Maybe v2.0 alongside Skill Registry web app.
- Sub-graphs as first-class nodes. Post-v1.0.
- AI-generate-graph from prompt directly on canvas. We have `chat_to_workflow.py` already.
- Custom node types authored in GUI. Power users edit `app/workflows/nodes/*.py`.
- Performance simulation / dry-run / what-if executor mode.
- Branching execution / parallel scheduling at executor level (separate concern).
- Dark/light theme toggle for canvas alone.

---

## Order of operations checklist (HISTORICAL — v0.18 NodeGraphQt path)

1. Pin and vendor NodeGraphQt fork. Smoke test PyQt6 import.
2. Write `node_factory.py` — generate one BaseNode subclass per `NodeSpec`.
3. Write `adapter.py` round-trip first: `Workflow → canvas → Workflow` no UI. Test deep-equals.
4. Write `layout.py` (Sugiyama-lite) for legacy skills with all-zero positions.
5. Write `canvas_panel.py` — palette + canvas + properties + toolbar. No save/run yet.
6. Wire save flow with validation overlay.
7. Extract `_SkillRunWorker` to `workflows/run_worker.py`. Wire canvas Run.
8. Wire ExecutionEvent stream → node colour states.
9. Replace SkillCard.edit handler.
10. Cog menu entry (defer to v0.19 if shipping v0.18 separately).
11. Tests.
12. Cut v0.18 release.

---

## v1.4 architecture (CURRENT — JSX canvas)

### Layered view

```
┌─────────────────────────────────────────────────────────┐
│  app/web_ui/studio-lm.jsx  (React, ~5k LOC)            │
│    HostPillRow · CanvasView · NodeRenderer · WireLayer │
│    Sidebar · NodeLibrary · FloatingComposer · NodeRail │
│           ▲                                            │
│           │ QWebChannel                               │
└───────────┼──────────────────────────────────────────────┘
            ▼
   app/bridge.py  (PyQt6 QObject, 115+ @pyqtSlot)
   ├── hosts: 18 families, broker + COM + HTTP + token probes
   ├── sessions: CRUD + autosave + fork
   ├── graph: save_graph · run_node · run_workflow
   ├── wires: can_wire · would_create_cycle · wire_transform · list_wire_fields
   ├── node-MCP: register · invoke · dispatch · list
   ├── subgraph: compose · expand · save_as_skill · duplicate
   ├── composer: parse_composer_command · apply_composer_command
   └── agent: agent_step (7-tool schema · NL → graph mutation)
            │
            ▼
   app/workflows/   (graph + runner + nodes + library)
   app/connectors/  (revit · acad · max · blender · rhino · outlook
                    teams · notion · speckle · dropbox · procore)
   app/mcp/         (NodeMCPServer + MCPRegistry)
```

### Single source of truth

The session JSON in `%LOCALAPPDATA%\ArchHub\sessions\<slug>.archhub-session.json`
is canonical. JSX state is a view layer that round-trips through
`bridge.save_graph(session_id, graph_json)`. The Python `Workflow`
dataclass still exists for executor compatibility but the canvas
**reads/writes the session JSON directly** — no adapter to keep in
sync.

### Wire engine (v1.4 specifics)

| Property | Value |
|---|---|
| Snap radius | **28 px** (Houdini / UE5 magnet feel) |
| Hover preview | green glow = will connect, red glow = refused |
| Drop-on-node-body | auto-picks first unconnected compatible input |
| Drop-on-empty-canvas | fires `lm-wire-promote` event (future palette) |
| Refusal toast | banner with reason — incompatible types / would-cycle / dupe / self |
| Wire data state | idle / flowing / cached / stale / error — painted on the bezier |
| Field selector | `src_field` / `dst_field` plucked from `bridge.list_wire_fields` |
| Cache invalidation | cache key includes selectors → field change invalidates |
| Cycle prevention | edit-time via `bridge.would_create_cycle` |

### Run model

Press **▶ Run Workflow** on the toolbar:

1. JSX serialises the canvas to graph JSON.
2. `bridge.run_workflow(session_id, graph_json)` walks sinks first,
   recursively cooks upstream dirty nodes, skips frozen (returns
   cached output), respects host permissions (AUTO / ASK / BLOCK).
3. Each node emits state transitions through QWebChannel signals;
   JSX repaints node border colour (idle / running / done / failed).

### Node-as-MCP

Every node mounted in JSX calls `bridge.register_node_mcp(node_id,
node_type, config_json)` in its `useEffect`. The Python registry
hands the node a `NodeMCPServer` that exposes its tools via
JSON-RPC 2.0. Other agents (Claude, an internal subgraph, an
external tool) call `bridge.dispatch_node_mcp(node_id, method,
params_json)` to invoke them. On unmount JSX calls
`bridge.unregister_node_mcp(node_id)`.

### Agent composer (`bridge.agent_step`)

Distinct from the deterministic `/slash` parser. Used when the user
types free text in the composer without a focused conversation node.

```text
user_msg → bridge.agent_step(user_msg, graph_json, model)
        → LLM with 7-tool schema (spawn_host / spawn_node / wire /
          focus / rename / delete / run)
        → tool-call array → JSX renders as chips → user confirms
          per-chip → apply_composer_command per applied chip
        → graph mutates, autosaves
```

The agent has the current graph context so it can wire to existing
nodes, not just spawn fresh ones.

### v1.4 file map

| Path | What it owns |
|---|---|
| `app/web_ui/index.html` | React + Babel CDN + ErrorBoundary |
| `app/web_ui/studio-lm.jsx` | The canvas itself — DO NOT EDIT WHILE OTHER AGENT WORKING |
| `app/bridge.py` | 115+ slot QObject — DO NOT EDIT WHILE OTHER AGENT WORKING |
| `app/host_detector.py` | 18-family detector — DO NOT EDIT WHILE OTHER AGENT WORKING |
| `app/web_shell.py` | QtWebEngine host + NoContextMenu |
| `app/workflows/` | Graph + runner + registry + composer commands + subgraph |
| `app/mcp/node_mcp.py` | NodeMCPServer + MCPRegistry |
| `app/connectors/` | Per-host runners (Outlook, Teams, Notion, Blender, Rhino, Speckle, Procore) |
| `app/connectors/<host>_broker.py` | Revit / AutoCAD / 3ds Max brokers (port-handshake) |
| `app/settings_dialog.py` | Native PyQt 5-tab dialog |
| `app/skills/` | Saved subgraph skills + matcher + capture |
| `docs/NODE_LIBRARY_v2.md` | 80-node taxonomy reference |

### Out of scope v1.4

- Real-time collab on the same canvas.
- Mobile / tablet canvas (it's a desktop app).
- Cancel mid-run (deferred — `bridge.run_workflow` is synchronous-blocking).
- Auto-generate graph from prompt without confirmation chips (the
  agent composer always shows chips).
- Custom node types authored in GUI (power users add to
  `app/workflows/nodes/*.py` and call `register()` — see
  `bridge.create_node_type` for runtime-registered types).
