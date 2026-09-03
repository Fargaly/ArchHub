# ArchHub — User Guide (v1.4)

> Last updated: 2026-05-14

ArchHub is a graph-first AI workspace for AEC. Every entity — a Revit
host, a conversation with Claude, a document, a skill, a tool call —
lives as a **typed node** on a **canvas**. You wire them together with
**typed bridges** that carry real data. The whole canvas can be saved,
shared, and re-run as a Skill.

---

## 1. Mental model

| Concept | What it is |
|---|---|
| **Session** | One canvas. One graph. Lives on disk as a single `.archhub-session.json` file. Switching session swaps the entire workspace. |
| **Node** | A typed unit of work — Revit host, conversation with an LLM, CSV reader, filter, dimension placer, etc. Each node is its own MCP server other agents can call. |
| **Wire** | A typed bridge between two nodes. Carries the actual payload (a list of walls, a view ref, a text prompt). Field selectors let you pluck a sub-property out of the source. |
| **Skill** | A subgraph saved for reuse. Drops back onto any canvas as a single composite node. |
| **Workflow** | What happens when you press **▶ Run Workflow** — every sink node cooks, dirty branches recompute, frozen nodes stay cached. |

This is the synthesis of Grasshopper (typed sockets), Houdini (lazy +
dirty + cached cook), ComfyUI (node-library + JSON-shareable graphs),
and Unreal Blueprints (exec vs data pins).

---

## 2. First launch

When ArchHub starts you land on the **Home pane**:

- Top: model picker (Claude Sonnet 4.5 by default — click to swap).
- Middle: **Start a new session…** input. Type a title, press **↵**.
- Below: grid of your existing sessions.

On a fresh install the grid is empty and shows:
> *No sessions yet. Type a title above and hit ↵ to start your first
> canvas.*

That's correct — sessions are real, created on demand, persisted to
disk.

---

## 3. The canvas

### Layout

```
┌────┬─────────┬──────────────────────────┬─────────┐
│    │ Sidebar │  Workspace canvas         │ NodeRail│
│ ●  │         │                           │         │
│ ◇  │ Sessions│  [HOST] ──── [READ] ──── │ params  │
│ ★  │  ─Tow…  │     │            │       │ for the │
│ 🔍 │         │     ▼            ▼       │ focused │
│ ⚙  │ Nodes   │  [AI ] ──intent──[FILTER]│ node    │
│    │  ─Read  │           │              │         │
│    │  ─Edit  │           ▼              │         │
│    │  ─AI…   │       [ANNOTATE]         │         │
└────┴─────────┴──────────────────────────┴─────────┘
```

### Header bar

- **Home** icon (top-left): return to all-sessions view.
- **Session title**: click to rename inline.
- **+** : new session. Mints a fresh slug, persists empty graph,
  switches the canvas.
- **Host pill row**: live status of every desktop host the detector
  finds — **18 host families** as of v1.4: Revit, AutoCAD, 3ds Max,
  Blender, Rhino, Speckle, Outlook, Teams, Notion, LM Studio,
  Antigravity, Photoshop, Illustrator, InDesign, Word, Excel,
  PowerPoint, Dropbox. Click a pill to drop that host as a node onto
  the canvas. Re-polls every 25 s.
- **Model strip**: click to pick a different model.
- **Fork** / **Save as Skill** : duplicate / persist current canvas.

### Sidebar

Four panels, switched via the icon rail:

| Panel | What's in it |
|---|---|
| **Sessions** | Your saved canvases. Click to open. Pencil icon = new session. |
| **Nodes** | Searchable library — **80 node types across 10 categories** (host, read, filter, transform, annotate, compose, logic, AI, output, trigger). **Most-used** row floats at the top of the list once you've used the canvas for a few sessions. **Collapse-all / Expand-all** toggle in the header keeps the rail tidy. Drag onto canvas, or double-click. See `docs/NODE_LIBRARY_v2.md` for the full taxonomy. |
| **Skills** | Your saved skills (composite nodes). Click = drop onto canvas. |
| **Search** | Cross-scope search: sessions, nodes, skills, memory, hosts. Each result clickable. |

### Canvas gestures

| Gesture | Action |
|---|---|
| Scroll | Zoom (cursor-anchored) |
| Drag empty | Pan |
| Right-click empty | Add node menu, fit graph, zoom 100% |
| Right-click node | Run / Freeze / Rename / Duplicate / Save as Skill / Disconnect all / Delete / Properties |
| Right-click socket | Disconnect every wire touching that port |
| Right-click wire | Pick source field, pick destination field, disconnect |
| Drag output → input | New wire. 28 px snap radius. Hover preview glows green (will connect) or red (refused — incompatible types, would cycle, dupe, or self). |
| Drag output → node body | Auto-connects to the first unconnected compatible input. |
| Delete / Backspace | Remove focused node or selected wire. |
| Shift-click node | Extend multi-selection. |
| Ctrl/Cmd + G | Compose selection into a subgraph composite node. |

---

## 4. The composer

The floating bar at the bottom is the **composer**. Three modes:

### Chat mode

Anything you type goes to the **focused conversation node** as a user
turn. The model's reply streams into the same node body.

### Agent mode (NL intent → graph mutations, v1.4)

If the composer has no focused conversation node, your message is
routed to **`bridge.agent_step`** — the AI agent composer. It parses
your natural-language intent against a **7-tool schema**:

| Tool | Effect |
|---|---|
| `spawn_host(family)` | Add a `host.<family>` node. |
| `spawn_node(type, x, y)` | Add a node of any registered type. |
| `wire(src, srcPort, dst, dstPort)` | Add a typed wire between two ports. |
| `focus(node)` | Move the focused-node marker. |
| `rename(node, title)` | Rename a node inline. |
| `delete(node)` | Remove a node and every wire touching it. |
| `run(node?)` | Cook a single node, or run the entire workflow if no id given. |

Examples:

- `"ping outlook"` → spawns `h_outlook` + `i_conv`, wires
  `status → conv.system`.
- `"list walls then dimension exterior ones"` → spawns
  `h_revit` + `r_walls` + `f_pred` + `a_dims`, wires them in series.
- `"send last weeks renders to teams"` → spawns `h_dropbox` +
  `r_files` + `o_teams`.

The agent shows you each proposed mutation as a chip and applies them
on confirm. Reject any chip to drop just that step.

### Slash mode

Type `/` to invoke a command:

| Command | What it does |
|---|---|
| `/wire src_node.port → dst_node.port` | Add a wire. |
| `/connect …` | Alias of `/wire`. |
| `/disconnect src_node.port → dst_node.port` | Remove that specific wire. |
| `/freeze [node-id]` | Toggle freeze on a node (defaults to focused). |
| `/rename node-id "new title"` | Rename. |
| `/duplicate node-id` | Clone +30/+30 px offset. |
| `/delete node-id` | Remove node + every incident wire. |
| `/properties node-id` | Open the property modal. |
| `/host.<family>` | Drop a host node (Revit, AutoCAD, Outlook, etc.). |

A bare `/` opens the inline help dropdown.

### Token shortcuts

| Token | Meaning |
|---|---|
| `@skill` | Search and insert a saved skill. |
| `#host` | Pick a host to bind this turn to. |
| `+attach` | Attach a file (PDF, IFC, CSV, DWG, RVT, image). |
| `/remember` | Add a memory fact to your profile. |

---

## 5. The wire system

Wires are typed bridges, not just lines. Each wire carries:

- **Source field** — pluck a sub-property (e.g. only the `length_mm`
  off a wall list).
- **Destination field** — drop the value into a specific config slot.
- **Transform** — optional inline transformation (round to 10, take
  first 50, group by level).
- **State** — idle, flowing, cached, stale, error. Painted as colour
  on the wire.

Right-click a wire to open its menu. Right-click a port to disconnect
every wire touching it.

---

## 6. Freezing nodes (Houdini bypass)

Each node has a ❄ **Freeze** toggle in its right-click menu (also
visible as a header icon when focused). A frozen node:

- Skipped during workflow runs.
- Returns its last cached output to downstream wires.
- Stays gray-tinted on the canvas to make the state obvious.

Use it to lock in expensive results while iterating downstream.

---

## 7. Subgraphs

Select two or more nodes (shift-click each, or rubber-band) then press
**Cmd/Ctrl + G**. They collapse into a single `subgraph.user` node.
Wires that crossed the selection boundary become facade ports on the
composite. The original wires inside are preserved.

Right-click the composite → **Expand subgraph** to inline its contents
back onto the canvas. Compose and expand are exact inverses.

A composite can be saved as a **Skill** from the same menu — it'll
appear in the Skills sidebar and drop back onto any canvas as a single
node.

---

## 8. Settings (native PyQt dialog · 5 tabs · v1.4)

Open via the gear icon in the sidebar, or press `⌘,`. Real, wired tabs
in the **native PyQt** dialog (the JSX overlay is preview-only and
never opens in desktop mode):

| Tab | What it does |
|---|---|
| **Providers** | Connect Anthropic / OpenAI / Google / OpenRouter. Click-only OAuth or paste-key. Stored in Windows Credential Manager. Stats per provider visible inline (tokens, $, last-success). |
| **Memory** | List / add / edit / forget memory facts. Cloud-synced when relay is configured; local-only otherwise. |
| **Profile** | Name, firm, role, avatar. Persisted to `secrets_store.profile`. Used by Skills as the default `author` field. |
| **Storage** | Real filesystem usage: `%LOCALAPPDATA%\ArchHub\` (sessions, skills, logs, model cache), `%PROGRAMDATA%\ArchHub\` (firm skills), with **Export all** and **Clear model cache** buttons. |
| **Shortcuts** | Editable keybindings. Click a row → press the new chord. Persisted to `secrets_store.shortcuts`; hot-reloaded by JSX. |

Host toggles moved out of Settings — they live on the canvas
host-pill row. Permission toggles (AUTO / ASK / BLOCK) live inline on
each host node now.

---

## 9. Keyboard shortcuts

| Key | Action |
|---|---|
| `↵` | Send composer / commit rename |
| `⇧ ↵` | Newline in composer |
| `Esc` | Cancel rename / close menu / dismiss modal |
| `⌘ K` | Open palette |
| `⌘ N` | New session |
| `⌘ ↵` | Run focused node |
| `⌘ L` | Add node from library |
| `⌘ ,` | Open settings |
| `⌘ 0` | Fit graph to view |
| `⌘ 1` | Zoom to 100% |
| `⌘ M` | Switch model |
| `⌘ ⇧ S` | Save canvas as Skill |
| `⌘ G` / `⌃ G` | Compose selection into subgraph |
| `Delete` / `Backspace` | Remove focused node or selected wire |
| `F5` / `⌘ R` | Reload WebView |
| `F12` | Toggle DevTools (Chromium inspector) |

---

## 10. Troubleshooting

**Canvas is blank / black:**
- Press `F12` to open DevTools and read the console for the JSX
  exception.
- The new ErrorBoundary (v1.4) should surface any render crash with
  the full stack and a **Reload** button — if you see a black canvas
  instead of that error pane, capture the F12 console and share it.

**Chat returns "router not wired":**
- No LLM provider configured. Open **Settings → Providers** and sign
  into OpenRouter (one-click OAuth covers Claude / GPT / Gemini) or
  paste an Anthropic / OpenAI / Google key.

**Host pill shows dim / missing:**
- That app isn't running on your machine right now. Launch it; the
  detector recheecks every 25 s.

**Revit `/exec` errors with "Microsoft.CodeAnalysis 4.11.0.0":**
- Add-in DLL needs the AssemblyResolve handler patch. Close Revit,
  run `Install.bat` to redeploy the add-in, reopen Revit.

**Session graph won't save:**
- Check `%LOCALAPPDATA%\ArchHub\sessions\` for write access. Each
  session is `<slug>.archhub-session.json`. If the directory is
  read-only, autosave silently fails.

---

## 11. File layout

```
%LOCALAPPDATA%\ArchHub\
├── ArchHub-silent.cmd       # main launcher (no console)
├── ArchHub.cmd              # debug launcher (shows console)
├── app/
│   ├── main.py              # entry point
│   ├── bridge.py            # ~94 QWebChannel slots
│   ├── web_shell.py         # QtWebEngine host
│   ├── web_ui/
│   │   ├── index.html       # React + Babel + ErrorBoundary
│   │   └── studio-lm.jsx    # the canvas itself (~5k lines)
│   ├── workflows/           # graph + runner + composer commands + subgraph
│   ├── mcp/                 # node-as-MCP server
│   ├── connectors/          # Revit / AutoCAD / Max / Blender / Rhino / Outlook
│   └── skills/              # saved subgraph skills
├── sessions/                # *.archhub-session.json
└── logs/
    ├── dev_source_sync.log
    └── llm_trace.log
```
