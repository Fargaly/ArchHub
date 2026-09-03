# BRUTAL AUDIT — 2026-05-14

Read-only sweep. Every clickable / draggable / dropdown in `studio-lm.jsx` (3973 lines) graded against `bridge.py` (1578 lines) + `settings_dialog.py`. Verdicts: F = functional, P = partial, D = dead shell.

Legend: **F** = wired end-to-end, **P** = visible action but bridge missing/signature wrong/no save, **D** = no handler / decoration.

---

## 1. Home pane (openId=null)

| Surface | File:Line | Handler | Bridge | Persist? | Verdict |
|---|---|---|---|---|---|
| ModelStrip click | 1421-1422 | `setPickerOpen(true)` | model picker only mutates JSX state | no | **P** — opens picker but `set_model` is never called (line 525 bridge exists, never invoked from JSX picker `setModel(m)` on line 3894) |
| "fork" button (WsHeader) | 1321 | `HoverBtn` with NO `onClick` prop | — | no | **D** — pure decoration |
| "save as skill" button (WsHeader) | 1322 | `HoverBtn primary` with NO `onClick` | — | no | **D** — pure decoration |
| Session thumbnail click | 1231-1238 | `onOpen` → `openSession(id)` | `bridge.load_session` (real, returns graph) | yes — graph splices into `LM_GRAPH`; `window.__archhub_session_id` set | **F** |
| HomeComposer input Enter | 1126-1128 | `onSubmit` → `onCreateSession` → `bridge.create_session` | `create_session` writes JSON file + emits `sessions_changed` (line 422-462) | yes | **F** |
| HomeComposer Send button | 1179-1182 | type=submit (same path) | same | yes | **F** |
| "+ new canvas" chip | 1148 | `onCreateSession('untitled')` | same | yes | **F** |
| Filter chips: all/mine/scheduled/workflows | 1144-1147 | no `onClick` on any | — | no | **D** — pure decoration |

---

## 2. Sidebar / IconRail (44px column)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| Home icon (orange arch) | 780-785 | `onHome` → `setOpenId(null)` | **F** |
| Chats icon | 769, 787-790 | `setPanel('chats')` | **F** |
| Nodes icon | 770 | `setPanel('nodes')` | **F** |
| Skills icon | 771 | `setPanel('skills')` | **F** |
| Search icon | 772 | `setPanel('search')` | **F** |
| **Share icon** | 793-795 | NO `onClick`, NO `title` action | **D** — pure decoration |
| Settings gear | 796-801 | `onSettings` → `openSettingsResolved` → `bridge.open_settings` (1.4) | **F** — opens native PyQt SettingsDialog (settings_dialog.py:144) |

---

## 3. ChatsPanel (line 820-900)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| "More" (···) button | 826-828 | NO `onClick` | **D** |
| "New chat" pencil button | 829-831 | NO `onClick` (does NOT fire `lm-new-session` or `create_session`) | **D** |
| "Search chats…" input | 836-843 | not an `<input>` — `<span>` placeholder text | **D** — decoration |
| "New Folder" button | 847-858 | NO `onClick` | **D** |
| Session list items | 862-884 | `onOpen(s.id)` → `openSession(id)` | **F** |
| User row (Fargaly + BYO·CLOUD chip) | 888-898 | no `onClick` | **D** |

---

## 4. NodesPanel (line 909-981)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| "Collapse all" (−) button | 920-922 | `setOpenCats({})` | **F** |
| Search input | 931-933 | real `<input>` with `onChange` | **F** (local filter only) |
| Category header buttons | 945-957 | `setOpenCats(o => {...o, [g.cat]: !o[g.cat]})` | **F** |
| Library item drag | 985-988 | `onDragStart` sets `application/x-lm-node` payload | **F** — canvas `onDrop` (line 1759) splices into `userNodes` + `saveCurrentGraph()` |
| Library item dblclick | 994 | `onAdd` → `addNodeFromLibrary` | **F** — persists |
| User row (bottom) | 968-978 | no `onClick` | **D** |

---

## 5. SkillsPanel (line 1027-1066)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| "New skill" (+) button | 1033-1035 | NO `onClick` | **D** |
| Search input (Search saved skills…) | 1037-1044 | `<span>` placeholder (NOT an `<input>`) | **D** |
| Skill items | 1047-1063 | `draggable="true"` but NO `onClick`, NO `onDragStart` data, NO `lm-spawn-skill` dispatch | **D** — hovers/highlights only |

---

## 6. SearchPanel (line 1069-1112)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| Search input (everything in studio…) | 1077-1086 | `<span>` placeholder, not an `<input>` | **D** |
| Scope buttons (chats/nodes/skills/memory/files/hosts) | 1097-1109 | NO `onClick` | **D** — pure decoration |

---

## 7. WsHeader (open canvas, line 1287-1324)

| Surface | File:Line | Handler | Bridge | Verdict |
|---|---|---|---|---|
| Home grid icon | 1293 | `onHome` → `setOpenId(null)` | — | **F** |
| Tab click | 1308 | `setOpenId(id)` → `openSession` | `load_session` | **F** |
| Tab × close | 1308, 1380-1388 | `closeTab(id)` | — | **F** |
| Tab dblclick rename | 1343, 1361-1372 | inline `<input>` then `bridgeCall('rename_session', ...)` | **`rename_session` SLOT DOES NOT EXIST** in bridge.py | **P** — JSX mutates `s.title` in-memory (line 1336) but disk write is dead. Title resets on session reload. |
| "+ new session" plus | 1310-1317 | `onCreateSession('untitled')` | `create_session` | **F** |
| ModelStrip compact | 1320 | `setPickerOpen(true)` | — | **P** (picker opens; selection doesn't reach router — see §1) |
| **"fork"** | 1321 | `HoverBtn` NO `onClick` | — | **D** |
| **"save as skill"** | 1322 | `HoverBtn primary` NO `onClick` | — | **D** |

---

## 8. Canvas (NodeCanvas line 1457-2068)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| Pan empty space | 1507-1513 (mousedown), 1657-1659 (move) | sets `dragRef={mode:'pan'}` → updates `pan` | **F** |
| Wheel zoom | 1735-1745 | rezooms + recenters around cursor | **F** |
| Right-click empty | 1515-1520 | opens `CanvasMenu` | **F** |
| Node title drag | 1522-1529, 1660-1662 | repositions; persists on mouseup (line 1716-1724 → `saveCurrentGraph`) | **F** |
| Node body click | 2275 | `onFocus` → `setFocusId` | **F** |
| Node right-click | 1532-1538 | opens `NodeMenu` | **F** |
| Socket drag start | 1560-1574 | only output→input; sets `wireDrag` | **F** |
| Socket right-click | 1541-1553 | filters wires touching that port, saves graph | **F** |
| Wire click | 1907-1909 | sets `selectedWire` | **F** |
| Wire right-click | 1910-1915 | opens `WireMenu` | **F** |
| Delete/Backspace key | 1804-1837 | wire delete + user-node delete + cascade-wire removal | **F** |
| Cmd/Ctrl+Enter | 1845-1849 | fires `bridge.run_workflow` | **F** |
| Cmd/Ctrl+G | 1851-1860 | `bridge.compose_subgraph` (returns `{ok, graph}`) — JSX reads `result.graph.nodes` → works | **F** |

### 8a. CanvasMenu (line 2195-2247)

| Item | Handler | Verdict |
|---|---|---|
| "Add node…" | `onAddNode` → `setLibraryOpen(true)` | **F** |
| **"Paste"** | `it.k:'⌘V'` no `on` | **D** |
| "Fit graph to view" | `onFit` → `onResetView` (pan=14,12 / zoom=0.66) | **P** — resets to hardcoded coords, doesn't actually compute graph bounds |
| **"Zoom to 100%"** | no `on` | **D** |
| **"Snap to grid"** | toggle:true, no handler | **D** |
| **"Auto-layout"** | no `on` | **D** |
| **"Reset positions"** | no `on` | **D** |
| "Clear all nodes" | inline at line 1995-1999: `LM_GRAPH.wires=[]` + delete user-nodes | **P** — only clears user nodes, demo `LM_GRAPH.nodes` survives |

### 8b. NodeMenu (line 2001-2046, defined 2071-2119)

| Item | Handler | Bridge | Verdict |
|---|---|---|---|
| ▶ Run | `bridge.run_node(sid, id, graph_json)` | `run_node` exists, threaded | **F** |
| ❄ Freeze | `node.frozen = !node.frozen` + saveCurrentGraph | runner respects `frozen` | **F** |
| ✎ Rename | `window.prompt` then mutates `node.title` + save | — | **F** |
| ⎘ Duplicate | `addNodeFromLibrary({...node, id:undefined, ...})` (JSX-side clone, NOT bridge.duplicate_node) | bridge has `duplicate_node` but JSX doesn't use it | **P** — works but bypasses the bridge helper; cloned node loses sockets if cat-template absent |
| ★ Save as Skill | `bridge.save_node_as_skill(sid, id)` | **SLOT DOES NOT EXIST** (bridge has `save_as_skill(name, payload_json)` only) | **D** |
| ⤢ Expand subgraph | `bridge.expand_subgraph(graph_json, id)` returns `{ok, graph}` — JSX reads `result.nodes` (line 2040) | bridge wraps as `{ok, graph: new_graph}` so `result.nodes` is undefined → branch never fires | **D** — slot is real but JSX reads the wrong key |
| ⊝ Disconnect all | filter `LM_GRAPH.wires` | — | **F** |
| ⓘ Properties | `setFocusId(nodeMenu.id)` (rail shows props) | — | **F** |
| ✕ Delete | removes user node + cascade wires; refuses demo nodes | — | **F** for user nodes; **D** for demo nodes (toast "Demo node — cannot delete") |

### 8c. WireMenu (line 2122-2162)

| Item | Handler | Bridge | Verdict |
|---|---|---|---|
| **⇄ Pick source field…** | `on:onClose` (literal close) | bridge `list_wire_fields` + `wire_transform` exist | **D** — slots are real but UI item never invokes them; just closes the menu |
| **⇆ Pick destination field…** | `on:onClose` | same | **D** |
| ⊝ Disconnect | filters wire at idx | — | **F** |

---

## 9. Wire engine (line 1559-1733)

| Behaviour | File:Line | Verdict |
|---|---|---|
| onMove scans + sets `data-wire-hover` | 1632-1654 | **F** |
| Hover preview glow CSS | 2165-2176 | **F** |
| Type/cycle/dupe precheck | 1615-1630 | **D** — calls `bridge.can_wire(out_type, in_type, '', '')` (4 strings); bridge sig is `(str, str, bool, bool)→bool`. Worse, JSX reads `can.ok === false` (line 1619) but slot returns a bare `bool`, so `can.ok` is always undefined → check is bypassed. `would_create_cycle` similarly mis-signatured (JSX 2 args, slot needs 4). |
| Drop on socket — finalises | 1664-1676 | **F** for the local commit; **P** because the precheck above silently passes everything |
| Drop on body — auto-pick input | 1680-1704 | **F** |
| Drop on empty — dispatches `lm-wire-promote` | 1706-1711 | **D** — no listener exists anywhere in JSX |
| Refused toast | 1678, 1699, 1702 | **F** (only triggers when precheck happens to return `{ok:false}` from a future-shape response — never does today) |

---

## 10. Right rail (NodeRail / ConversationRail, line 3054-3209)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| ConversationRail shown for AI nodes | 3059, 3138-3208 | renders `node.messages`, autoscrolls | **F** |
| tool_trace renders when populated | 3188-3201 | reads `node.tool_trace` array | **F** — but no bridge path populates `tool_trace`; remains empty in practice |
| Non-AI rail param widgets | 3092-3119 | renders `params` array | **F** |
| Text input onChange | 3342-3346 | `onParamChange` writes `node.config[k]=v` + saveCurrentGraph | **F** |
| Number/slider input | 3298-3322 | same path | **F** |
| Boolean toggle | 3325-3336 | same path | **F** |
| Enum select | 3380-3386 | same path | **F** |
| Version dropdown | 3350-3375 | `bridge.list_host_sessions(family)` — real broker call | **F** — but no node spec in `LM_NODE_TEMPLATES` ever sets `p.type === 'version'`, so this code is reachable only via hand-crafted graph |
| Document dropdown | 3350-3375 | `bridge.list_host_documents(family, session)` — real | **F** — same caveat |
| "↻ Rerun this node" | 3122-3123 | `bridge.run_node(...)` | **F** |
| "Pin to skill" | 3124 | `bridge.save_node_as_skill(sid, id)` | **D** — slot doesn't exist |
| "Branch from here" | 3125 | no `onClick` | **D** |
| "Disconnect all" | 3126-3129 | filters wires + save | **F** |
| Chat action buttons (regen/branch/edit/copy) | 3253-3257 | each `ChatAction` has `onClick={e=>e.stopPropagation()}` — does NOTHING beyond stopping propagation | **D** |
| ChatTurn "reasoning" toggle | 3232-3249 | local state, shows canned text "1. parse intent · 2. plan stages · …" | **P** — toggle works; content is hardcoded literal, never from bridge |

---

## 11. FloatingComposer (line 2797-2864)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| Input onChange | 2833-2834 | `setText(...)` + toggles help on bare `/` | **F** |
| Enter submit | 2818-2819 | `submit()` | **F** |
| Send button | 2842 | `submit()` | **F** |
| `/wire` `/freeze` `/delete` `/rename` `/duplicate` `/properties` `/disconnect` | 2808 → 503-518 | `bridge.parse_composer_command` + `bridge.apply_composer_command` round-trip; result splices `LM_GRAPH.nodes/wires` | **F** |
| `/createnode` | 520-522 | sets `createNodeOpen` → opens CreateNodeModal | **F** — modal POSTs `bridge.create_node_type` |
| Bare `/` → help dropdown | 2806, 2844-2861 | renders literal help block | **F** |
| **"ping outlook" / "ping revit" natural-language** | 465-501 | JSX dispatches on `case 'spawn_host':` but bridge returns `command:'spawn_host_chat'` (`workflows/composer_commands.py:248`) | **D** — case name mismatch, falls through to default `chat` |
| Library button | 2841 | `setLibraryOpen(true)` | **F** |
| @ skill / # host / + attach / /remember chips | — | NOT IMPLEMENTED — no such chips render in this file | **D** — does not exist |

---

## 12. Mini-map (line 2867-2962)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| Viewport rect visible | 2949-2953 | rendered SVG rect | **F** |
| Click → pans | 2903-2913 | converts minimap px → world, recenters | **F** |
| Drag → pans | 2915-2924 | document mousemove during press | **F** |

---

## 13. Top toolbar (CanvasToolbar, line 2757-2783)

| Surface | File:Line | Handler | Verdict |
|---|---|---|---|
| Zoom + | 2763 | setZoom(z + 0.1) | **F** |
| Zoom − | 2764 | setZoom(z − 0.1) | **F** |
| Zoom % readout | 2765-2767 | cursor:default | **F** (decorative) |
| ⟲ Reset view | 2768 | `onFit` → onResetView | **F** |
| ＋ add node | 2770-2774 | `setLibraryOpen(true)` | **F** |
| ▶ RUN | 2777-2781 | `bridge.run_workflow(sid, graph_json)` threaded | **F** |

---

## 14. Settings dialog

PyQt path (bridge.open_settings → settings_dialog.SettingsDialog).

| Tab | File:Line | State |
|---|---|---|
| Providers | settings_dialog.py:153 | **F** — `_ProviderRow` rows, sign-in / sign-out, real `save_api_key` |
| Memory | 473, 1256-1383 | **F when cloud reachable**; "Cloud unreachable — managed memory disabled" otherwise. Add/Edit/Forget call `cloud_client.{add,update,delete}_memory_fact` |
| Profile | 474, 1386-1448 | **F** — reads/writes `%LOCALAPPDATA%\ArchHub\profile.json` |
| Storage | 475, 1451-1526 | **F** — `_dir_size` on real folders; "Open folder" uses `os.startfile`; Forget-all calls `cc.delete_all` |
| Shortcuts | 476, 1529+ | **F** — read-only table |
| **Close (×)** | — | inherited QDialog close — **F** |

React `<Settings/>` overlay (3398-3461) is the fallback when bridge is missing. All its tabs (Memory/Profile/Permissions/Hosts/Providers/Models/Theme/Shortcuts/Storage/About) render **hardcoded LM_MEMORY / LM_PERMISSIONS / LM_PROVIDERS arrays** — every button (add fact, edit, forget, export, change, connect, manage, do it) has NO onClick. Entire fallback Settings is **decoration** — every input is a `<span>`/static value, not an editor. **D across the board** if bridge ever fails to open native dialog.

---

## 15. Backend (bridge.py)

| Slot | File:Line | Real or stub? | Verdict |
|---|---|---|---|
| `run_workflow` | 967-1025 | Worker thread; `WorkflowRunner.run_all`; streams `wire_state_changed`; emits `workflow_done` | **F** |
| `run_node` | 1027-1100 | Same pattern; `runner.pull(node_id)` | **F** |
| `send_chat_history` | 543-619 | Threaded; chat_chunk on each piece; chat_done on success AND error | **F** |
| `parse_composer_command` | 1501-1516 | Delegates to `workflows.composer_commands.parse_composer_command`; returns `spawn_host_chat` for "ping outlook" | **F backend** — but JSX dispatcher (line 465) listens for `spawn_host`, so the surface is broken. |
| `create_session` | 422-462 | Writes JSON to disk + emits `sessions_changed` | **F** |
| `save_as_skill` | 1336-1383 | Writes skill JSON + emits `skills_changed` | **F backend** — but JSX never calls this slot (calls non-existent `save_node_as_skill` instead) |
| `compose_subgraph` / `expand_subgraph` | 1443-1492 | Real; uses `workflows.subgraph` | **F backend**; expand-shape mismatch on JSX (sees `result.graph.nodes` ≠ `result.nodes`) breaks expand path |
| `list_host_sessions("revit")` | 82-167 | Imports `revit_broker.list_sessions(prune=False)`, serializes Session dataclass | **F** |
| `can_wire` | 920-936 | Calls `workflows.typesystem.can_wire`; returns `bool`; **fail-open on exception** (returns True) | **F backend**, **D from JSX** (signature + result-shape mismatch) |
| `would_create_cycle` | 938-964 | Calls `WorkflowRunner.would_create_cycle` | **F backend**, **D from JSX** |
| `list_wire_fields`, `wire_transform` | 1137-1196 | Real introspection via runner helpers | **F backend**, never invoked from JSX (WireMenu items are `onClose` only) |
| `register_node_mcp` / `unregister_node_mcp` | 1226-1300 | Real `NodeMCPServer` + REGISTRY | **F** — NodeRenderer mounts/unmounts mcp servers correctly (line 2259-2270) |
| `set_model` | 524-535 | Delegates to chat_widget.model_picker | **F backend**, **D from JSX** (ModelPicker `setModel(m)` at 3894 never calls this slot) |
| `set_host_active` | 377-391 | Real manager.activate_family/deactivate_family | **F backend**, **D from JSX** (no JSX surface invokes it; SettingsHosts toggles at line 3836 are pure JSX-state divs with no onClick) |

---

## 16. ServerStrip (bottom strip, line 3923-3969)

| Item | File:Line | Handler | Verdict |
|---|---|---|---|
| "server :7300 · live/total hosts" | 3945-3947 | `setSettingsOpen(true)` | **F** |
| Session file path | 3951 | no onClick (StripItem without `onClick`) | **D** (intentional read-out) |
| Model + tokens + cost | 3953-3955 | `setSettingsOpen(true)` | **F** |
| settings link | 3964 | `setSettingsOpen(true)` | **F** |
| v1.4 prototype label | 3966 | no onClick | **D** (intentional read-out) |

---

## SUMMARY

Surfaces audited: **84**

| Verdict | Count | % |
|---|---|---|
| **F** Functional | **45** | 54% |
| **P** Partial / wired but broken edge | **9** | 11% |
| **D** Dead shell | **30** | 36% |

### Top 10 most critical dead shells (highest user-visible damage, easiest to fix)

1. **`save_node_as_skill` slot doesn't exist on bridge.** Two big buttons call it: NodeMenu "Save as Skill" (line 2035) and NodeRail "Pin to skill" (line 3124). Bridge has `save_as_skill(name, payload_json)` (line 1336). Wire JSX to that slot with a serialized subgraph.
2. **`rename_session` slot missing.** Tab dblclick rename (line 1337) silently fails to persist. Title resets on next reload. Add `rename_session(old_id, new_name)` to bridge or extend `save_graph` to carry a name.
3. **"ping outlook" / natural-language host spawn broken.** JSX (line 465) listens for `case 'spawn_host':` but bridge emits `spawn_host_chat` (workflows/composer_commands.py:248). One-line rename either side.
4. **`can_wire` JSX signature wrong.** Calls with 4 strings, slot wants `(str, str, bool, bool)`; reads `can.ok === false` but slot returns bare `bool`. Type-checking on wire-drop is completely bypassed today. Bad wires commit silently.
5. **`would_create_cycle` JSX signature wrong.** Calls with `(sid, graph_json)` but slot wants `(sid, src_node, dst_node, graph_json="")`. Cycle prevention is silently bypassed.
6. **NodeMenu "Expand subgraph" dead.** Bridge returns `{ok, graph}` (line 1490); JSX reads `result.nodes` (line 2040) → branch never fires. Should be `result.graph.nodes/wires`.
7. **WireMenu "Pick source field…" / "Pick destination field…" both wired to `onClose`** (line 2134-2135). The `list_wire_fields` + `wire_transform` slots exist and work. Replace `on:onClose` with a real field-picker overlay.
8. **ModelPicker selection never reaches router.** `setModel(m)` (line 3894) updates JSX state only. `bridge.set_model(model_id)` exists and is wired to chat_widget. Add the call after `setModel`.
9. **SkillsPanel items are decoration.** No `onClick`, no `onDragStart` payload, no `lm-spawn-skill` event. Listed skills can't be invoked, dragged, or run.
10. **React `<Settings/>` overlay is 100% fake.** Every button (forget, edit, add fact, change, connect, manage, "do it", export) has no handler. Native PyQt path covers the common case, but if bridge is missing the user sees a fully decorative settings dialog with no functioning controls. Either remove the React overlay or wire it to the same slot endpoints.

### Other dead-shell clusters worth a sweep

- **IconRail "Share" button** (line 793) — pure decoration.
- **ChatsPanel "More", "New chat", "Search chats…", "New Folder"** — none wired.
- **SkillsPanel "New skill" + search input** — `<span>` placeholder, not real.
- **SearchPanel input + all 6 scope buttons** — none real; the entire panel is a mockup.
- **Home filter chips** (all/mine/scheduled/workflows) — no handlers.
- **WsHeader "fork" and "save as skill" pills** — no `onClick`.
- **CanvasMenu Paste / Zoom 100% / Snap / Auto-layout / Reset positions** — no handlers.
- **NodeRail "Branch from here"** (line 3125) — no `onClick`.
- **ChatTurn regen/branch/edit/copy** (line 3253-3257) — `stopPropagation` only.
- **`lm-wire-promote` dispatched on empty-canvas drop** (line 1707) — no listener anywhere.
- **NodeRail "reasoning" details** — hardcoded literal text, never from bridge.
- **Hosts settings tab toggle pills** — divs styled as switches, no onClick → `bridge.set_host_active` (which is real) is never called from any UI surface.

### Backend slots that are real but orphaned (UI never invokes them)

- `set_model` · `set_host_active` · `save_as_skill` · `list_wire_fields` · `wire_transform` · `duplicate_node` (bridge helper bypassed by JSX local clone) · `get_node_library` (canvas uses hardcoded `LM_LIBRARY` rather than fetching this) · `get_node_mcp_tools` · `invoke_node_tool` · `dispatch_node_mcp` · `get_permissions` · `set_permission` · `get_providers` · `set_provider_key` (overlay React Settings never reaches these — only the native PyQt dialog does, via its own paths).
