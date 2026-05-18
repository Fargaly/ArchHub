# Connector Master Plan — All 18 Hosts Genuinely Working

> Author: senior integrations architect, ArchHub · 2026-05-15
> Mandate (founder, verbatim): *"FULL. EVERYTHING. Do what it takes to finish it.
> Utilize an agent for each. Use local agents. Orchestrate. DEEPLY RESEARCH AND
> PLAN BEFORE ACTION."*
> Scope: research + plan only. This document is the literal spec a wave of build
> agents executes. No connector code is written here.
> Sources audited (read in full): `app/host_detector.py`, `app/connector_health.py`,
> `app/{acad,revit,max,outlook}_broker.py`, `app/connectors/{ai,blender,outlook,
> procore,rhino}_runner.py` + `registry.py`, `app/mcp/node_mcp.py`, `app/mcp_fetcher.py`,
> `app/bridge.py`, `app/workflows/registry.py` + `nodes/tools.py`, `app/speckle_client.py`,
> `app/local_llm_detector.py`, `app/auto_build.py`, `payload/sources/{revit_mcp,acad_mcp,
> max_mcp}/*`, `payload/{rhino,blender}/*`, `docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md`,
> `docs/AUDIT_2026-05-14.md`.

---

## Executive summary

ArchHub claims 18 host connectors. The audit finds a better starting position
than feared, plus one genuinely hard cluster.

**No frozen-DLL crisis.** `payload/sources/` holds full, readable C# source for
Revit (`RevitMCPApp.cs` 475 LOC + `RevitEventHandler.cs` 238 LOC) and AutoCAD
(`AcadMCPApp.cs` 293 LOC), each with a working `.csproj`. 3ds Max needs no
compiled add-in — its integration is a 328-LOC Python startup script
(`max_mcp_startup.py`), already complete. `app/auto_build.py` ships a working
`dotnet` SDK detect/install/build toolchain. The .NET add-ins rebuild from source.

**Real state of the 18:** 7 have real working connector code (Revit, AutoCAD,
3ds Max, Blender, Rhino via broker/runner; Outlook via COM; Speckle via GraphQL).
The other 11 are detect-only — `host_detector.py` probes whether the app runs,
but there is zero action code: Word, Excel, PowerPoint, Photoshop, Illustrator,
InDesign (COM, nothing), Teams, Notion, Dropbox (REST, nothing), LM Studio (works
as a chat backend, no host-node connector) and Antigravity (honest stub — Google
ships no public API).

**Verdict on "all 18 today":** 12-14 can be made genuinely code-complete in the
wave; of those, the subset whose app is installed on the founder's machine can
also be verified live. Antigravity cannot be made "working" — no API exists; the
honest deliverable reports `host_offline`/`unavailable` truthfully. The gating
constraint is not code — it is which host apps are installed for live
verification (§6).

**The single biggest blocker** is not the .NET add-ins (source exists). It is the
COM cluster of 6 Office/Adobe apps — Word, Excel, PowerPoint, Photoshop,
Illustrator, InDesign — needing a uniform `win32com` connector layer built from
nothing, live-verifiable only for whichever are installed. De-risked via a shared
COM base + recorded fixtures so connectors are code-complete and unit-tested even
where the app is absent.

---

## 1. Ground-truth audit — what EXISTS today, per host

Legend: **WORKS** = end-to-end path exists and is exercised · **PARTIAL** =
some code, real gaps · **DETECT-ONLY** = `host_detector` probe exists, no action
code · **STUB** = honest placeholder.

| # | Host | Mechanism | Code that exists today (paths) | Works now | Precise gap |
|---|------|-----------|--------------------------------|-----------|-------------|
| 1 | **Revit** | .NET broker add-in (HTTP :48884-99) | `payload/sources/revit_mcp/{RevitMCPApp.cs,RevitEventHandler.cs,RevitMCP.csproj,.addin}`; DLLs `payload/revit/{2020,2023,2024,2025}/RevitMCP.dll`; `revit_broker.py`; `registry.py:_RevitSpec`; tools `revit_ping/info/execute_csharp/screenshot` | **WORKS** — 4 C# routes, multi-session broker | DLLs for 2020/23/24/25 only, no 2026. Only `/ping /info /exec /screenshot` — no `/list_docs`, no typed element queries |
| 2 | **AutoCAD** | .NET broker add-in (HTTP :48885) | `payload/sources/acad_mcp/{AcadMCPApp.cs,AcadMCP.csproj}`; DLL `payload/autocad/2026/AcadMCP.dll`; `acad_broker.py`; `_AutoCADSpec` (HKCU autoload); `connector_health.py` COM NETLOAD self-heal; tools `acad_ping/info/execute_csharp` | **WORKS** — `/ping /info /exec` C#; broker + self-heal | AcadMCP **hard-codes :48885** — no multi-session range, no session-file heartbeat (legacy-only). Only 2026 DLL. No `/list_docs`, no typed queries |
| 3 | **3ds Max** | Python startup script (bundled CPython + PySide, HTTP :48886-99) | `payload/sources/max_mcp/max_mcp_startup.py` (328 LOC, complete); `max_broker.py`; `_MaxSpec`; tools `max_ping/info/execute_python/execute_maxscript` | **WORKS (code-complete)** — all routes, session registry, heartbeat | **No compiled add-in needed.** Gap is verification only + no typed scene queries |
| 4 | **Blender** | Bundled Python addon (HTTP :9876) | `payload/blender/archhub_mcp/__init__.py` (296 LOC); `app/connectors/blender_runner.py`; `_BlenderSpec`; tools `blender_ping/info/save/render/execute_python` | **WORKS** — addon + full HTTP-client runner | Two install paths disagree: `blender_runner.install_addon` wants a `GeneratedSource`, `_BlenderSpec` copies `payload/blender/archhub_mcp` directly. No typed scene queries |
| 5 | **Rhino** | Embedded Python script (HTTP :9879) | `payload/rhino/archhub_mcp.py` (284 LOC) + README; `app/connectors/rhino_runner.py`; `_PassiveSpec("rhino")`; tools `rhino_ping/info/execute_python/screenshot` | **WORKS** — full HTTP-client runner | `host_detector` has **no Rhino probe** and `connector_health.LISTENER_URL` has **no `rhino`** — Rhino is invisible to the health daemon + host pill row |
| 6 | **Speckle** | REST + GraphQL (`app.speckle.systems`) | `app/speckle_client.py` (227 LOC); `_PassiveSpec("speckle")`; tools `speckle_list_projects/get_project/push_parameters/pull_parameters` | **PARTIAL** — list/get/push/pull work | Mixes **v2** (`stream/branch/commitCreate`) with **v3** (`project/models/versions` in `_get_project`). Inconsistent. No object-tree pull, no per-class filter |
| 7 | **Outlook** | Windows COM (`win32com`, classic Outlook) | `app/connectors/outlook_runner.py` (995 LOC — read + categorize + draft); `app/outlook_broker.py`; ~20 `outlook_*` tools | **WORKS** — richest connector; list/search/read/draft/categorize/folders, `com_thread()` STA guard | Classic Outlook only (New/UWP unsupported, documented). No calendar/contacts ops. Send is draft-only by design |
| 8 | **Teams** | MS Graph REST (cloud) | `host_detector.probe_teams` (process + token detect) | **DETECT-ONLY** | No module, no Graph client, no app registration, no OAuth flow |
| 9 | **Notion** | Notion REST API v1 | `host_detector.probe_notion` (process detect) | **DETECT-ONLY** | No module, no REST client, no integration-token handling |
| 10 | **LM Studio** | Local OpenAI-compatible server (:1234) | `ai_runner.lmstudio_ask`; `host_detector.probe_lmstudio`; `local_llm_detector.probe_lmstudio`; tool `ai_lmstudio_ask` | **PARTIAL** — works as a chat backend | No *host-node* connector — treated as an LLM provider, not a host with `list models`/`completion`/`embedding` ports |
| 11 | **Antigravity** | None — Google ships no public API | `ai_runner.antigravity_ask` (honest stub); `host_detector.probe_antigravity` (process detect) | **STUB (honest)** | No public API exists. Cannot be made "working" — honest deliverable only |
| 12 | **Photoshop** | Windows COM (`Photoshop.Application`) | `host_detector.probe_photoshop` (detect) | **DETECT-ONLY** | No module, no COM action code |
| 13 | **Illustrator** | Windows COM (`Illustrator.Application`) | `host_detector.probe_illustrator` (detect) | **DETECT-ONLY** | No module, no action code |
| 14 | **InDesign** | Windows COM (`InDesign.Application`) | `host_detector.probe_indesign` (detect) | **DETECT-ONLY** | No module, no action code |
| 15 | **Word** | Windows COM (`Word.Application`) | `host_detector.probe_word` (detect) | **DETECT-ONLY** | No module, no action code |
| 16 | **Excel** | Windows COM (`Excel.Application`) | `host_detector.probe_excel` (detect) | **DETECT-ONLY** | No module, no action code |
| 17 | **PowerPoint** | Windows COM (`PowerPoint.Application`) | `host_detector.probe_powerpoint` (detect) | **DETECT-ONLY** | No module, no action code |
| 18 | **Dropbox** | Dropbox REST API v2 | *(none — in the v1.4 host list per `AUDIT_2026-05-14.md` but `host_detector.PROBERS` has no `dropbox` key)* | **NOTHING** | No probe, no module. Needs OAuth2 + `dropbox` SDK + everything |

**Honest summary:** 5 desktop-host connectors genuinely WORK (Revit, AutoCAD,
3ds Max code-complete, Blender, Rhino), Outlook WORKS richly, Speckle is PARTIAL.
**11 of 18 are detect-only or nothing.** The repo's own `AUDIT_2026-05-14.md`
marks host nodes "✅" — that is true for *node registration and detection*, not
for *action capability* on the 11.

---

## 2. Integration-mechanism taxonomy

Five clusters. Group build agents by cluster (§5), not by host.

### Cluster A — .NET broker add-in (Revit, AutoCAD, 3ds Max)

- **Pattern**: host-side add-in runs an `HttpListener` on a localhost port; marshals
  host-API work to the host UI thread (Revit `ExternalEvent`, AutoCAD
  `Application.Idle`, Max `QTimer` drain); writes a session JSON to
  `%LOCALAPPDATA%\ArchHub\sessions\<family>-<pid>.json` with a 10 s heartbeat.
  ArchHub's `*_broker.py` scans the dir, picks a session, `forward()`s HTTP calls.
- **Build / libs / SDK**: full detail in §4 — Revit + AutoCAD C# via `dotnet build`
  (.NET SDK 8.x, NuGet `Revit_All_Main_Versions_API_x64` / `AutoCAD.NET` /
  `Microsoft.CodeAnalysis.CSharp.Scripting` 4.11.0|3.11.0 / `System.Text.Json`
  8.0.5|6.0.10; net8 ≥2025, net48 ≤2024); 3ds Max = Python, no compile.
- **ArchHub-side Python**: stdlib only (`urllib`, `socket`, `json`). **Auth**: none (loopback).
- **Failure modes**: §7 risks 3, 4, 14. **"Working"**: `/ping` → `{"status":"ok"}`;
  `/info` → live doc title; `/exec` with C#/Python mutates the model in a
  transaction. Verify: `curl …:48884/ping` + a script via `revit_execute_csharp`.

### Cluster B — Windows COM automation (Outlook, Word, Excel, PowerPoint, Photoshop, Illustrator, InDesign)

- **Pattern**: ArchHub's Python process COM-dispatches into the running host —
  `GetActiveObject` first (avoid launching), `Dispatch` as fallback. All in-process,
  **no listener, no add-in**. Every worker thread MUST `pythoncom.CoInitialize()` /
  `CoUninitialize()` — the `com_thread()` context manager in `outlook_runner.py` is
  the proven template.
- **Library**: `pywin32` — pin **`pywin32>=306`** (current 308; 306 is the floor
  with stable `win32com` on Python 3.12+). Provides `win32com.client` + `pythoncom`.
- **ProgIDs**: `Outlook.Application`, `Word.Application`, `Excel.Application`,
  `PowerPoint.Application`, `Photoshop.Application`, `Illustrator.Application`,
  `InDesign.Application`. **Auth**: none (drives the logged-in desktop session).
- **Failure modes**: §7 risks 1, 2, 9, 11. **"Working"**: read ops return live doc
  state (Excel range, Word paragraphs, PSD layers); action ops mutate the open
  document, visible in the host. Verify: run a read op, diff against screen; absent
  hosts → recorded COM-shape fixture (§5 DoD).

### Cluster C — Python-API / socket (Blender, Rhino)

- **Pattern**: host bundles its own Python; ArchHub ships an addon/script that runs
  an HTTP server inside the host; ArchHub's `*_runner.py` is a stdlib HTTP client.
  Blender addon auto-loads via `addon_utils.enable`; Rhino script is run once via
  `_-RunPythonScript` or dropped in the scripts folder.
- **Libraries**: ArchHub side stdlib only. Host side: `bpy` (Blender, bundled),
  `rhinoscriptsyntax`/`Rhino`/`scriptcontext` (Rhino, bundled). Optional out-of-process
  fixture path: `rhino3dm>=8.0` reads `.3dm` files with no Rhino running. **Auth**: none.
- **Failure modes**: addon not enabled / script not loaded; Blender path drift in
  `find_addons_folder`; Rhino :9879 not registered with `connector_health` (gap §3.5).
  **"Working"**: `/ping` + `/info` + `/execute` + `/render` (Blender) return live
  results. Verify: `blender_runner.ping()`/`rhino_runner.ping()`; fixture uses
  `rhino3dm` on a sample `.3dm`.

### Cluster D — REST / GraphQL cloud API (Speckle, Notion, Teams, Dropbox)

- **Pattern**: stateless module functions; token from `secrets_store.load_api_key(<provider>)`
  + context from `load_setting`; HTTPS call; uniform `{"status":...}` envelope.
  `procore_runner.py` is the proven template.
- **Libraries (exact pins)**: **Speckle** — stdlib `urllib` (sufficient; keep the dep
  surface clean). **Notion** — stdlib `urllib` against `api.notion.com/v1` (consistent
  with `procore_runner`; `notion-client>=2.2,<3` is the alternative). **Teams** —
  `msal>=1.31,<2` (device-code OAuth) + stdlib `urllib` for Graph; do **not** pull the
  heavy `msgraph-sdk`. **Dropbox** — `dropbox>=12.0,<13` (official SDK; OAuth2 +
  chunked transfer).
- **Auth**: Speckle — Personal Access Token (Profile → Tokens), bearer. Notion —
  internal integration token (`secret_...`) + share pages with the integration. Teams —
  Azure AD app registration (delegated perms `Chat.Read`, `ChannelMessage.Read.All`,
  `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `Presence.Read`, `ChatMessage.Send`),
  MSAL device-code → access + refresh token. Dropbox — OAuth2 (app-console generated
  token simplest, or PKCE).
- **Failure modes**: §7 risks 5, 7, 10 (rate limits, token expiry, Speckle v2→v3,
  pagination). **"Working"**: read ops list real cloud objects; action ops
  create/modify a real object visible in the web app. Verify: live token; fixture
  path replays one recorded JSON per op.

### Cluster E — Local LLM server (LM Studio, Ollama, Antigravity)

- **Pattern**: local OpenAI-compatible HTTP server; `openai` SDK pointed at
  `http://localhost:<port>/v1` (LM Studio 1234, Ollama 11434). `ai_runner.lmstudio_ask`
  is the template. As a *host node* it also exposes `list models` / `model info` /
  `embeddings`.
- **Libraries**: `openai>=1.50,<2` (pinned); stdlib `urllib` for `/v1/models`. Ollama
  also has native `/api/tags` + `/api/embeddings`. **Auth**: none for localhost.
- **Failure modes**: server not started (LM Studio's is opt-in in its UI); no model
  loaded; **Antigravity has no API at all**. **"Working"**: `/v1/models` lists
  loaded models; a completion returns text; embeddings return a vector. Verify:
  `local_llm_detector.probe_lmstudio()` + a live completion.

---

## 3. Per-host build spec — the part the build agents execute

Conventions for every host: connector modules live in `app/connectors/`; every
public function returns the uniform `{"status":...}` envelope. Operations become
graph nodes automatically — tool defs go in `tool_engine.TOOLS`,
`register_tool_nodes()` auto-generates a `tool.<name>` node spec, and
`mcp/node_mcp.py:_HOST_TOOL_PREFIX` gains the family prefix. Ports are spec'd in
`docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md §2.2`. Every connector ships
`tests/test_<family>_runner.py` with a fixture path (no host installed, CI-safe)
and a `skipif`-guarded live path.

### 3.1 Revit — `app/connectors/revit_runner.py` (new thin wrapper) + C# extension

- **Mechanism**: .NET broker add-in; ArchHub side stdlib via `revit_broker.py`.
- **Module**: add routes to C# `payload/sources/revit_mcp/RevitEventHandler.cs`;
  new thin `app/connectors/revit_runner.py` wrapping `revit_broker.pick_session()`
  + `forward()`.
- **Read ops**: `revit_ping`, `revit_info` (exist); **add** `revit_list_docs` →
  `[{path,title,active}]`, `revit_list_views`, `revit_list_levels`,
  `revit_list_categories`, `revit_list_phases`, `revit_list_worksets`,
  `revit_query_elements(category, view_id?)` → `[element]` (drives
  `walls/doors/windows/rooms` ports).
- **Action ops**: `revit_execute_csharp`, `revit_screenshot` (exist). Typed
  actions (`create_wall`) deferred — `execute_csharp` covers them.
- **Ports** (grammar §2.2.1): in `document, active_view, phase, worksets,
  category_filter, element_limit`; out `walls, doors, windows, rooms, levels,
  views, sheets, families, selection, warnings`.
- **Wiring / auth**: family `revit`; detector + health already wired. User toggles
  the connector ON (writes `.addin`), restarts Revit once.
- **Test**: `tests/test_revit_runner.py` — fixture monkeypatches `revit_broker.forward`;
  live skipif `not revit_broker.is_any_alive()`. **LOC** C# ~260 + Python ~140 →
  **~400**. **Difficulty L**. **Depends on**: §4 .NET build, §5 scaffolding.

### 3.2 AutoCAD — `app/connectors/acad_runner.py` (new) + C# multi-session fix

- **Mechanism**: .NET broker add-in; `acad_broker.py`.
- **Module**: **critical C# fix** in `payload/sources/acad_mcp/AcadMCPApp.cs` —
  replace hard-coded `ListenPrefix = "http://localhost:48885/"` with a port-range
  bind (48885-48899) + session-file write + heartbeat, mirroring `RevitMCPApp.cs`
  (without it `acad_broker.py`, which expects per-PID session files, only sees the
  legacy port). New thin `app/connectors/acad_runner.py`.
- **Read ops**: `acad_ping`, `acad_info` (exist); **add** `acad_list_docs`,
  `acad_list_layers`, `acad_list_blocks`, `acad_list_layouts`,
  `acad_query_entities(types, layer?)`. **Action**: `acad_execute_csharp` (exists).
- **Ports** (§2.2.4): in `document, layers, block_filter, layout, entity_types`;
  out `entities, layers, blocks, xrefs, layouts, selection`.
- **Wiring / auth**: family `acad`; detector + NETLOAD self-heal wired. Toggle ON
  writes HKCU autoload via `_AutoCADSpec`; 2026 DLL prebuilt, older years build.
- **Test**: `tests/test_acad_runner.py` — fixture monkeypatches `acad_broker.forward`;
  live skipif `not acad_broker.is_any_alive()`. **LOC** C# ~120 + Python ~140 →
  **~260**. **Difficulty L** (C# multi-session fix). **Depends on**: §4 .NET build.

### 3.3 3ds Max — `app/connectors/max_runner.py` (new)

- **Mechanism**: Python startup script (no compile); `max_broker.py`.
- **Module**: `max_mcp_startup.py` is **already complete** — only add typed
  scene-query routes (`/list_objects`, `/list_cameras`, `/list_materials`). New
  thin `app/connectors/max_runner.py` over `max_broker.pick_session()` + `forward()`.
- **Read ops**: `max_ping`, `max_info` (exist); **add** `max_list_objects`,
  `max_list_cameras`, `max_list_lights`, `max_list_materials`. **Action**:
  `max_execute_python`, `max_execute_maxscript` (exist).
- **Ports** (§2.7): in `document, selection_set, category_filter, render_view`;
  out `objects, cameras, lights, materials, selection`.
- **Wiring / auth**: family `max`; detector + health wired. Toggle ON copies
  `max_mcp_startup.py` to `%LOCALAPPDATA%\Autodesk\3dsMax\<ver> - 64bit\ENU\scripts\startup\`,
  restart Max once.
- **Test**: `tests/test_max_runner.py` — fixture monkeypatches `max_broker.forward`.
  **LOC** script +80 + runner ~120 → **~200**. **Difficulty M** (no compile; needs
  Max to verify — likely fixture-only). **Depends on**: §5 scaffolding.

### 3.4 Blender — `app/connectors/blender_runner.py` (finish)

- **Mechanism**: bundled Python addon; `blender_runner.py` exists.
- **Module**: reconcile the two install paths — make `_BlenderSpec.activate` and
  `blender_runner.install_addon` agree on `payload/blender/archhub_mcp/`. Add
  typed-query routes to `payload/blender/archhub_mcp/__init__.py`.
- **Read ops**: `blender_ping`, `blender_info` (exist); **add** `blender_list_objects`,
  `blender_list_collections`, `blender_list_materials`. **Action**: `blender_save`,
  `blender_render`, `blender_execute_python` (exist).
- **Ports** (§2.7): in `file, collection, view_layer, selected_only`; out
  `objects, collections, materials, selection`.
- **Wiring / auth**: family `blender`; detector + health wired. Toggle ON installs
  the addon; launch Blender.
- **Test**: `tests/test_blender_runner.py` — fixture monkeypatches `blender_runner._request`.
  **LOC** addon +90 + reconcile ~40 → **~130**. **Difficulty M**. **Depends on**:
  §5 scaffolding.

### 3.5 Rhino — `app/connectors/rhino_runner.py` (finish) + detector/health wiring

- **Mechanism**: embedded Python script; `rhino_runner.py` exists.
- **Module**: runner is complete — **the gap is wiring**: add `probe_rhino` to
  `host_detector.PROBERS` (TCP :9879) + `HOST_DISPLAY["rhino"]`, and
  `"rhino": "http://localhost:9879/ping"` to `connector_health.LISTENER_URL` (no
  `HOST_PROCESS` self-heal). Add typed-query routes to `payload/rhino/archhub_mcp.py`.
- **Read ops**: `rhino_ping`, `rhino_info` (exist); **add** `rhino_list_layers`,
  `rhino_query_geometry(kind)`. **Action**: `rhino_execute_python`,
  `rhino_screenshot` (exist).
- **Ports** (§2.2.5): in `document, layers, geo_kind, tolerance, selection_only`;
  out `curves, surfaces, meshes, breps, points, blocks, selection`.
- **Wiring / auth**: family `rhino`; **detector + health must be added** (missing —
  Rhino invisible to health). Toggle ON installs the script; user runs
  `_-RunPythonScript` once.
- **Test**: `tests/test_rhino_runner.py` exists — extend; fixture uses `rhino3dm`
  on a sample `.3dm`. **LOC** wiring ~40 + addon +80 + runner ~40 → **~160**.
  **Difficulty S**. **Depends on**: §5 scaffolding.

### 3.6 Speckle — `app/speckle_client.py` (v3 reconcile)

- **Mechanism**: REST + GraphQL; stdlib `urllib` (do **not** add `specklepy`).
- **Module**: make `speckle_client.py` consistently **Speckle v3** (Projects /
  Models / Versions — `project`, `models`, `versions`, `versionCreate`).
  `_get_project` is already v3-shaped; `_create_commit`/`_get_latest_commit` are
  still v2 (`stream`/`branch`/`commitCreate`) — migrate, keep a v2 fallback.
- **Read ops**: `speckle_list_projects`, `speckle_get_project` (exist); **add**
  `speckle_list_models(project_id)`, `speckle_list_versions(model_id)`,
  `speckle_receive_objects(version_id, class_filter?)`. **Action**:
  `speckle_push_parameters`/`speckle_pull_parameters` (exist) → extend to
  `speckle_send_objects`.
- **Ports** (§2.2.3): in `server, stream, branch, commit, object_kit,
  class_filter, mode`; out `objects, commit_meta, send_status`.
- **Wiring / auth**: family `speckle` → node category `speckle`; optional
  `probe_speckle` (token + `/graphql` ping), no listener. User pastes a Personal
  Access Token into Settings → Speckle (`secrets_store` key `speckle`); optional
  `speckle_server` URL.
- **Test**: `tests/test_speckle_client.py` (new) — fixture monkeypatches
  `SpeckleClient._query`; live skipif no token.
- **LOC ~240**. **Difficulty M**. **Depends on**: §5 scaffolding.

### 3.7 Outlook — `app/connectors/outlook_runner.py` (extend)

- **Mechanism**: Windows COM; `pywin32`. `outlook_runner.py` is the richest
  connector in the repo — extend only with **calendar + contacts** (grammar wants
  a `calendar` output port); everything else is done.
- **Read ops**: ~20 exist (`list_inbox`, `search`, `read_thread`, `list_folders`,
  `list_sent_items`, …); **add** `outlook_list_calendar(since, until)`,
  `outlook_list_contacts`. **Action**: `draft_reply`, `set_categories`,
  `move_to_folder`, `mark_read`, `flag_for_followup`, `create_folder` (exist; send
  stays draft-only).
- **Ports** (§2.2.2): in `account, folder, unread_only, from_filter,
  subject_filter, since, limit, mark_read`; out `inbox, calendar, contacts,
  drafts, unread_count, selection`.
- **Wiring / auth**: family `outlook`; `probe_outlook` + `outlook_broker` exist.
  Classic Outlook + a profile; New Outlook unsupported.
- **Test**: extend `tests/test_outlook_execute.py` + `test_outlook_bulk.py` with
  calendar/contacts COM-shape fixtures. **LOC ~120**. **Difficulty S**. **Depends
  on**: nothing — can start immediately.

### 3.8 Teams — `app/connectors/teams_runner.py` (new)

- **Mechanism**: MS Graph REST; `msal>=1.31,<2` + stdlib `urllib`.
- **Module**: `app/connectors/teams_runner.py` — stateless, MSAL device-code flow,
  token cached in `secrets_store` (`ms_graph` + `ms_graph_refresh`).
- **Read ops**: `teams_list_teams` → `GET /me/joinedTeams`; `teams_list_channels(team_id)`
  → `GET /teams/{id}/channels`; `teams_list_messages(team_id, channel_id, since?)`
  → `GET /teams/{id}/channels/{id}/messages`; `teams_get_presence` →
  `GET /me/presence`; `teams_list_chats` → `GET /me/chats`. **Action**:
  `teams_send_channel_message(team_id, channel_id, text)` → `POST .../messages`
  (behind the `ai_behaviour` "ask" policy — no silent posts).
- **Ports** (§2.7): in `team, channel, since, mention_only`; out `messages, files,
  meetings, presence`.
- **Wiring / auth**: new family `teams` — add `"teams": ("teams_",)` to
  `_HOST_TOOL_PREFIX`; `probe_teams` exists, cloud, no listener.
  **One-time Azure AD app registration** (founder): register an app at
  `portal.azure.com`, set a device-code (public-client) redirect URI, grant
  delegated perms `Chat.Read`, `ChannelMessage.Read.All`, `Team.ReadBasic.All`,
  `Channel.ReadBasic.All`, `Presence.Read`, `ChatMessage.Send`; ArchHub stores the
  client ID + tenant; user signs in once. Heaviest setup of any host (§7).
- **Test**: `tests/test_teams_runner.py` (new) — fixture monkeypatches `urllib`
  with recorded Graph JSON; live skipif no token.
- **LOC ~360**. **Difficulty L**. **Depends on**: §5 scaffolding + Azure
  registration (founder action).

### 3.9 Notion — `app/connectors/notion_runner.py` (new)

- **Mechanism**: Notion REST API v1; stdlib `urllib` (consistent with
  `procore_runner`), header `Notion-Version: 2022-06-28`.
- **Module**: `app/connectors/notion_runner.py` — stateless; token from
  `secrets_store.load_api_key("notion")`.
- **Read ops**: `notion_search(query)` → `POST /v1/search`; `notion_list_databases`
  → search filtered to `database`; `notion_query_database(database_id, filter_json?)`
  → `POST /v1/databases/{id}/query`; `notion_get_page(page_id)` → `GET /v1/pages/{id}`;
  `notion_get_block_children(block_id)` → `GET /v1/blocks/{id}/children`.
  **Action**: `notion_create_page(parent_id, properties, content?)` →
  `POST /v1/pages`; `notion_append_blocks(block_id, blocks)` →
  `PATCH /v1/blocks/{id}/children`; `notion_update_page(page_id, properties)` →
  `PATCH /v1/pages/{id}`.
- **Ports** (§2.7): in `workspace, database, filter_json, limit`; out `pages,
  database_rows, selection`.
- **Wiring / auth**: new family `notion` — add `"notion": ("notion_",)` to
  `_HOST_TOOL_PREFIX`; `probe_notion` exists. User creates an **internal
  integration** at `notion.so/my-integrations`, pastes the `secret_...` token into
  Settings → Notion, and **shares each page/database with it** (Notion's
  per-resource sharing — the #1 confusion point).
- **Test**: `tests/test_notion_runner.py` (new) — fixture replays Notion JSON; live
  skipif no token. **LOC ~320**. **Difficulty M**. **Depends on**: §5 scaffolding.

### 3.10 LM Studio — `app/connectors/lmstudio_runner.py` (new host-node connector)

- **Mechanism**: local OpenAI-compatible server; `openai>=1.50,<2` + stdlib for
  `/v1/models`.
- **Module**: `app/connectors/lmstudio_runner.py` — distinct from
  `ai_runner.lmstudio_ask` (the chat-backend path); this is the *host-node* surface.
- **Read ops**: `lmstudio_ping` → TCP :1234; `lmstudio_list_models` →
  `GET /v1/models`; `lmstudio_model_info(id)`. **Action**:
  `lmstudio_complete(model, prompt, temperature, max_tokens)` →
  `POST /v1/chat/completions`; `lmstudio_embed(model, text)` → `POST /v1/embeddings`.
- **Ports** (§2.7): in `endpoint, model, temperature, max_tokens`; out
  `model_info, completion, embedding`.
- **Wiring / auth**: new family `lmstudio` — add `"lmstudio": ("lmstudio_",)` to
  `_HOST_TOOL_PREFIX`; `probe_lmstudio` exists. User starts LM Studio's server
  (toggle in its UI) + loads a model.
- **Test**: `tests/test_lmstudio_runner.py` (new) — fixture replays `/v1/models` +
  completion JSON; live skipif port closed. **LOC ~200**. **Difficulty S**.
  **Depends on**: §5 scaffolding.

### 3.11 Antigravity — `app/connectors/antigravity_runner.py` (honest stub)

- **Mechanism**: **none** — Google ships no public API for Antigravity as of 2026-05.
- **Module**: `app/connectors/antigravity_runner.py` — every op returns
  `{"status":"error","available":false,"error":"Antigravity has no public API…"}`
  (`ai_runner.antigravity_ask` is the template). Ops `antigravity_ping`,
  `antigravity_list_agents`, `antigravity_list_tasks` all honest-"unavailable";
  ports (§2.7 `workspace, agent_id, task_filter` → `agents, tasks, events`)
  declared but the node renders `host_offline` truthfully.
- **Wiring / test**: family `antigravity`; `probe_antigravity` (process detect)
  stays, status `unavailable`. `tests/test_antigravity_runner.py` asserts every op
  returns the honest envelope. **LOC ~80**. **Difficulty S**. **Depends on**:
  nothing — **the explicit allowed fallback** (§5 DoD): code-complete, truthful,
  never faked.

### 3.12-3.14 Photoshop / Illustrator / InDesign — Adobe COM connectors (new)

Agent B2. Each is a new COM module via `pywin32`, using the `base.com_app()` STA
pattern.

| Host | Module | Read ops | Action ops | Ports (§2.7) |
|------|--------|----------|-----------|--------------|
| **Photoshop** | `app/connectors/photoshop_runner.py` | `photoshop_ping`, `photoshop_info`, `photoshop_list_layers`, `photoshop_get_document` | `photoshop_run_jsx(script)`, `photoshop_export(path, format)`, `photoshop_toggle_layer(name, visible)` | in `document, layers, mode, dpi` → out `document, layers, active_layer, selection_bbox` |
| **Illustrator** | `app/connectors/illustrator_runner.py` | `illustrator_ping`, `illustrator_info`, `illustrator_list_artboards`, `illustrator_list_layers`, `illustrator_list_swatches` | `illustrator_run_jsx(script)`, `illustrator_export(path, format)` | in `document, artboards, layers, swatch_lib` → out `paths, artboards, swatches, selection` |
| **InDesign** | `app/connectors/indesign_runner.py` | `indesign_ping`, `indesign_info`, `indesign_list_spreads`, `indesign_list_styles`, `indesign_list_links` | `indesign_run_jsx(script)`, `indesign_export_pdf(path)` | in `document, spread_range, paragraph_style_filter` → out `spreads, frames, styles, links` |

Common: every Adobe app exposes `DoJavaScript`/`DoScript` — the **action surface
is "run an ExtendScript snippet"** (mirroring the .NET hosts' "run C#"); read ops
are direct COM property reads. New families → add prefixes to `_HOST_TOOL_PREFIX`;
`probe_*` exist (COM detect, no listener); no auth (app must be open). Each ships
`tests/test_<family>_runner.py` with a recorded COM-shape fixture (unit-tested
with no Adobe app), live skipif `GetActiveObject` fails. **LOC ~220 each → ~660.
Difficulty M each. Depends on**: §5 scaffolding.

### 3.15-3.17 Word / Excel / PowerPoint — Office COM connectors (new)

Shared build agent (Cluster B-Office). New modules, COM via `pywin32`,
`com_thread()` STA pattern.

| Host | Module | Read ops | Action ops | Grammar ports |
|------|--------|----------|-----------|----------------|
| **Word** | `app/connectors/word_runner.py` | `word_ping`, `word_info`, `word_list_paragraphs`, `word_list_headings`, `word_list_tables`, `word_list_comments`, `word_read_text(range?)` | `word_insert_paragraph(text, after?)`, `word_replace_text(find, replace)`, `word_set_track_changes(bool)`, `word_export_pdf(path)` | §2.7: in `document, style_filter, heading_range, track_changes` → out `paragraphs, headings, tables, comments` |
| **Excel** | `app/connectors/excel_runner.py` | `excel_ping`, `excel_info`, `excel_list_workbooks`, `excel_list_worksheets(workbook)`, `excel_list_named_ranges`, `excel_read_range(workbook, sheet, range)` → `range_values` | `excel_write_range(workbook, sheet, range, values)`, `excel_set_cell(addr, value)`, `excel_add_worksheet(name)`, `excel_export_pdf(path)` | grammar §2.2.6: in `workbook, worksheet, range, named_range, headers_row, as_objects` → out `workbook, worksheet, range_values, selection_range` |
| **PowerPoint** | `app/connectors/powerpoint_runner.py` | `powerpoint_ping`, `powerpoint_info`, `powerpoint_list_slides`, `powerpoint_list_shapes(slide)`, `powerpoint_read_notes(slide)` | `powerpoint_add_slide(layout)`, `powerpoint_set_text(slide, shape, text)`, `powerpoint_export_pdf(path)` | §2.7: in `presentation, slide_range, layout_filter` → out `slides, shapes, master, notes` |

Common: COM via `base.com_app()` — read ops = property walks, action ops = method
calls in a try/finally that never leaves the host modal. New families → add
prefixes to `_HOST_TOOL_PREFIX`; `probe_*` exist, no listener; no auth (prefer
`GetActiveObject`, report `host_offline` if absent). The Excel *connector* (live
workbook) is distinct from the existing `aec.csv_reader`/`doc.csv` *file readers*.
Each ships `tests/test_<family>_runner.py` with recorded COM-shape fixtures, live
skipif `GetActiveObject` fails (Excel `read_range`/`write_range` round-trip is the
key live test). **LOC ~230 each → ~690. Difficulty M each. Depends on**: §5
scaffolding.

### 3.18 Dropbox — `app/connectors/dropbox_runner.py` (new)

- **Mechanism**: Dropbox REST API v2; **`dropbox>=12.0,<13`** (official SDK —
  cleanest OAuth2 + chunked upload).
- **Module**: `app/connectors/dropbox_runner.py` — stateless; token from
  `secrets_store.load_api_key("dropbox")`.
- **Read ops**: `dropbox_ping` → `users_get_current_account()`;
  `dropbox_list_folder(path, recursive?)` → `files_list_folder`;
  `dropbox_get_metadata(path)`; `dropbox_list_revisions(path)` →
  `files_list_revisions`; `dropbox_download(path, local_path)`. **Action**:
  `dropbox_upload(local_path, dropbox_path)` → `files_upload` (chunked >150 MB);
  `dropbox_create_folder(path)`; `dropbox_share_link(path)` →
  `sharing_create_shared_link_with_settings`.
- **Ports** (§2.7): in `account, path, recursive, extensions_filter`; out `files,
  folders, revision_history`.
- **Wiring / auth**: new family `dropbox` — add `"dropbox": ("dropbox_",)` to
  `_HOST_TOOL_PREFIX` **and `probe_dropbox` to `host_detector.PROBERS`**
  (token-presence + `users_get_current_account` ping — no probe exists today).
  User creates an app at `dropbox.com/developers/apps`, generates an access token
  (scopes `files.content.read/write`, `files.metadata.read`, `sharing.write`),
  pastes into Settings → Dropbox.
- **Test**: `tests/test_dropbox_runner.py` (new) — fixture monkeypatches the
  `dropbox.Dropbox` client; live skipif no token.
- **LOC ~280**. **Difficulty M**. **Depends on**: §5 scaffolding.

**Per-host LOC roll-up:** Revit 400 · AutoCAD 260 · Max 200 · Blender 130 ·
Rhino 160 · Speckle 240 · Outlook 120 · Teams 360 · Notion 320 · LM Studio 200 ·
Antigravity 80 · Photoshop 220 · Illustrator 220 · InDesign 220 · Word 230 ·
Excel 230 · PowerPoint 230 · Dropbox 280 = **~4 300 LOC** connectors, plus
shared scaffolding (§5, ~600) and tests (~1 800) → **~6 700 LOC total**.

---

## 4. The .NET add-in problem

**NOT the blocker feared.** Audit result — all three host-side integrations have
source in the repo:

| Host | Source | Location | Build |
|------|--------|----------|-------|
| **Revit** | full C# | `payload/sources/revit_mcp/RevitMCPApp.cs` (475), `RevitEventHandler.cs` (238), `RevitMCP.csproj`, `.addin` | `dotnet build`; NuGet `Revit_All_Main_Versions_API_x64`; net8 ≥2025, net48 ≤2024 |
| **AutoCAD** | full C# | `payload/sources/acad_mcp/AcadMCPApp.cs` (293), `AcadMCP.csproj` | `dotnet build`; NuGet `AutoCAD.NET`; net8 ≥2025, net48 ≤2024 |
| **3ds Max** | full Python — no compile | `payload/sources/max_mcp/max_mcp_startup.py` (328) | none — Max bundles CPython 3 + PySide |

The **"DLL-without-source" risk does NOT apply** — the DLLs in
`payload/revit/{2020,2023,2024,2025}/` and `payload/autocad/2026/` are reproducible
build outputs. **Toolchain is already present**: `auto_build.py` ships
`detect_dotnet_sdk()`, `download_dotnet_installer()` (.NET SDK 8.0.405),
`install_dotnet_sdk()`, `_run_dotnet_build()` (`dotnet restore`+`build` with
`-p:TargetFramework`). The `.csproj` files build on a clean machine via NuGet
reference assemblies — no Revit/AutoCAD install required to *compile*.

**The one real gap — coverage, not capability:** no Revit 2026 target built
(`.csproj` parameterizes `RevitYear` — a build-matrix entry, not new code); only
the AutoCAD 2026 DLL is prebuilt (older years need a `dotnet build` pass with
`AcadYear` override); the **AcadMCP single-port bug** (§3.2) is a genuine C#
change.

**Recommendation: REBUILD FROM SOURCE** — do not decompile, do not freeze DLLs.
Agent A: (1) verify `dotnet --list-sdks` shows 8.x (else `install_dotnet_sdk`);
(2) apply the AcadMCP multi-session fix + new typed-query routes to all three
sources; (3) rebuild the matrix — `RevitMCP` {2020,2023,2024,2025,2026},
`AcadMCP` {2024,2025,2026} — via `_run_dotnet_build` with per-year props;
(4) stage into `payload/{revit,autocad}/<year>/`. Where the host is absent, the
NuGet path still compiles; only *runtime* verification needs the host.

**3ds Max "building one" takes nothing** — no add-in to build; the 328-LOC
`max_mcp_startup.py` is the whole integration; `_MaxSpec.activate` copies it to
Max's startup folder. (A future *compiled* .NET Max plugin would need the 3ds Max
SDK `Autodesk.Max` assemblies — not on NuGet — but pymxs covers the grammar's
scene-query surface today.)

**Net:** the .NET concern is "a build matrix + one C# bug" — it does **not**
block "all 18."

---

## 5. The orchestration plan — how to run the build wave

### 5.1 Agent count & ownership — group by integration cluster

One agent **per cluster**, not per host: hosts in a cluster share a mechanism,
libraries, an STA/transaction discipline and a test pattern — one COM agent writes
the COM base once and reuses it 6×; per-host agents would re-derive and diverge.

| Agent | Cluster | Hosts owned | Files owned (exclusive) |
|-------|---------|-------------|-------------------------|
| **Agent 0 — Scaffolding** | (pre-wave) | none | `app/connectors/base.py` (NEW), `app/connectors/_fixtures/` (NEW), `tests/conftest.py` additions, `app/connectors/registry.py` (extend `_REGISTRY`) |
| **Agent A — .NET hosts** | A | Revit, AutoCAD, 3ds Max | `payload/sources/revit_mcp/*`, `payload/sources/acad_mcp/*`, `payload/sources/max_mcp/*`, `app/connectors/{revit,acad,max}_runner.py` (NEW), `payload/revit/*`, `payload/autocad/*` (build outputs) |
| **Agent B1 — Office COM** | B | Word, Excel, PowerPoint | `app/connectors/{word,excel,powerpoint}_runner.py` (NEW) |
| **Agent B2 — Adobe COM** | B | Photoshop, Illustrator, InDesign | `app/connectors/{photoshop,illustrator,indesign}_runner.py` (NEW) |
| **Agent B3 — Outlook COM** | B | Outlook | `app/connectors/outlook_runner.py` (extend), `app/outlook_broker.py` |
| **Agent C — Python-host** | C | Blender, Rhino | `app/connectors/{blender,rhino}_runner.py`, `payload/blender/archhub_mcp/*`, `payload/rhino/archhub_mcp.py` |
| **Agent D — Cloud REST** | D | Speckle, Notion, Teams, Dropbox | `app/speckle_client.py`, `app/connectors/{notion,teams,dropbox}_runner.py` (NEW) |
| **Agent E — Local LLM** | E | LM Studio, Antigravity | `app/connectors/{lmstudio,antigravity}_runner.py` (NEW) |
| **Agent F — Integration** | (post-wave) | all | `app/tool_engine.py` (TOOLS additions), `app/host_detector.py`, `app/connector_health.py`, `app/mcp/node_mcp.py` (`_HOST_TOOL_PREFIX`) |

B is split B1/B2/B3 because COM is the largest cluster (10 hosts) — splitting keeps
each agent ≤3 hosts. The 4 shared files (`tool_engine.py`, `host_detector.py`,
`connector_health.py`, `node_mcp.py`) are owned by **Agent F alone** — cluster
agents instead emit their tool definitions as `<family>_runner.TOOLS_FRAGMENT`
(a list of `ConnectorOp`); Agent F merges them + wires detectors in one pass.
**No two agents touch the same file.**

### 5.2 Dependency order

`Agent 0` (alone, first — everyone imports `base.py`) → **parallel wave: A, B1,
B2, B3, C, D, E** (disjoint files, no inter-deps, each self-tests vs fixtures) →
`Agent F` (alone, last — only writer of the 4 shared files) → `pytest` + relaunch.
Start Agent A first inside the wave — it has the longest critical path (.NET build
matrix).

### 5.3 Shared scaffolding — Agent 0 builds BEFORE the wave

`app/connectors/base.py` (NEW, ~350 LOC):

```python
@dataclass
class ConnectorOp:
    name: str               # "excel_read_range"
    family: str             # "excel"
    summary: str            # one-line description (becomes tool description)
    kind: str               # "read" | "action"
    input_schema: dict      # JSON Schema — feeds register_tool_nodes + node_mcp
    destructive: bool = False

class Connector(Protocol):
    family: str
    def ops(self) -> list[ConnectorOp]: ...
    def invoke(self, op_name: str, args: dict) -> dict: ...   # returns {"status":...}
    def health(self) -> str: ...   # "live"|"loaded_dead"|"host_offline"|"unauth"|"unavailable"

def com_app(progid: str, *, launch: bool = False):
    """STA-safe COM acquisition — GetActiveObject first, optional Dispatch.
    Wraps the pythoncom CoInitialize/CoUninitialize discipline. The single
    canonical COM entry point for all of Cluster B."""

def ok(**kw) -> dict:  return {"status": "ok", **kw}
def err(msg, **kw) -> dict:  return {"status": "error", "error": str(msg), **kw}

def fixture(family: str, op: str) -> dict:
    """Load tests/_fixtures/<family>/<op>.json — the recorded host response
    used by the no-host-installed test path."""
```

Agent 0 also: creates `app/connectors/_fixtures/<family>/` dirs + a
`connector_fixture(family, op)` `pytest` fixture in `tests/conftest.py`; adds
`_PassiveSpec` entries to `connectors/registry.py:_REGISTRY` for the new cloud/COM
families; defines the `TOOLS_FRAGMENT` convention (each connector exposes a
`ConnectorOp` list → Agent F converts to `tool_engine.TOOLS` dicts). Every cluster
agent's job is then mechanical.

### 5.4 Per-agent ship gate & test command

All agents share one DoD (§5.5); the gate below is each agent's distinguishing
criterion + test command.

| Agent | Ship gate (beyond §5.5 DoD) | Test command |
|-------|----------------------------|--------------|
| 0 | `base.py` imports clean; `ConnectorOp`/`Connector`/`com_app`/`fixture` exist | `python -c "import app.connectors.base"` + `pytest -q` |
| A | `RevitMCP` builds 2025+2026; `AcadMCP` builds + binds a port range; `max_mcp_startup.py` has typed routes | `pytest tests/test_{revit,acad,max}_runner.py -q` |
| B1 | Excel range round-trip live IF Excel installed | `pytest tests/test_{word,excel,powerpoint}_runner.py -q` |
| B2 | all 3 Adobe modules pass fixture tests | `pytest tests/test_{photoshop,illustrator,indesign}_runner.py -q` |
| B3 | Outlook calendar+contacts added; existing tests green | `pytest tests/test_outlook_*.py -q` |
| C | Rhino wired into detector+health; Blender install paths reconciled | `pytest tests/test_{blender,rhino}_runner.py -q` |
| D | `speckle_client.py` consistently v3 | `pytest tests/test_{speckle_client,notion_runner,teams_runner,dropbox_runner}.py -q` |
| E | `antigravity_runner.py` honest-unavailable for every op | `pytest tests/test_{lmstudio,antigravity}_runner.py -q` |
| F | all `TOOLS_FRAGMENT`s merged; `PROBERS` has all 18 (incl. `rhino`, `dropbox`); `LISTENER_URL` has `rhino`; `_HOST_TOOL_PREFIX` has every family | `pytest -q` |

### 5.5 Definition of Done — per host, no fakery allowed

A host connector is **DONE** only when ALL of: (1) a module exists with every
read + action op from §3 against the **real** mechanism (broker/COM/REST/local
server); (2) every op returns the uniform `{"status":...}` envelope — errors are
real, never a hard-coded success; (3) it registers as graph nodes (`ConnectorOp`s
reach `tool_engine.TOOLS` → `register_tool_nodes`) and surfaces in `host_detector`
+ (if listener-based) `connector_health`; (4) `tests/test_<family>_runner.py`
exists with a **fixture path that passes with the host NOT installed** and a
**live path** guarded by `skipif`; (5) **if the host app IS on the dev machine**,
the live path passes — a real read op returns real state, a real action makes a
real change (recorded in §6).

**The explicit allowed fallback** (the founder's "honest about what's not
installed" rule): when a host app is **genuinely absent**, the connector is still
DONE if 1-4 hold — **code-complete + fixture-tested** — and at runtime it reports
`host_offline` (listener) / `unavailable` (COM, no `GetActiveObject`) / `unauth`
(cloud, no token) **honestly**, never a fabricated success. Antigravity is the
limiting case: code-complete, every op truthfully `unavailable` — DONE, and not
fakery but honesty.

**Forbidden**: canned data when the host is absent; a probe reporting `live`
without a real reachability check; marking a host "✅" when only detection works.

---

## 6. What can truly be finished today vs what cannot

Two axes: **code-complete** (achievable for all 18 except Antigravity) and
**live-verifiable** (depends on what is installed/configured on the founder's box).

| Host | Code-complete? | Live-verifiable today? |
|------|----------------|------------------------|
| AutoCAD, Outlook, LM Studio | YES | **LIVE** — known present on the founder's machine |
| Word, Excel, PowerPoint | YES | **LIVE if Office installed** — confirm via `GetActiveObject` at wave start |
| Revit, 3ds Max, Blender, Rhino | YES (Revit source builds, Max script complete) | LIVE **only if the host is installed** — else fixture path (Rhino uses `rhino3dm`) |
| Photoshop, Illustrator, InDesign | YES | LIVE **only if installed** — else COM-shape fixture |
| Speckle, Notion, Dropbox | YES | LIVE **only if a token is configured** (Notion also needs pages shared with the integration) |
| Teams | YES | LIVE **only after Azure app registration + device-code sign-in** — heaviest setup; likely fixture-only day one |
| Antigravity | code-complete only — honest stub | **NO — impossible; Google ships no public API** |

**Honest count:** verifiable-live today, high confidence — **3** (AutoCAD,
Outlook, LM Studio); conditional +3 — Word, Excel, PowerPoint go live the moment
the wave confirms Office is installed (very likely on an AEC pro's Windows box) →
**realistic 3-6 live today**. The remaining **12-15** are code-complete +
fixture-tested only — *finished* per the DoD, not *live-proven* on this machine.
**1** (Antigravity) can never be "working". The plan must **not** claim
"done = live" for the 12-15 — they are "code-complete, fixture-verified, go live
the moment the host/token is present."

---

## 7. Risk register

| # | Risk | Likelihood / Impact | Mitigation |
|---|------|---------------------|------------|
| 1 | **COM STA threading** — COM from a non-CoInitialize'd thread crashes `Qt6Core 0xc0000409` | High if ignored / crash | Every COM op goes through `base.com_app()` wrapping `com_thread()` (proven in `outlook_runner.py`). No raw `Dispatch` in cluster B; code-review gate |
| 2 | **Adobe/Office modal dialogs** block COM indefinitely | Medium / hang | Watchdog timeout per COM op → `err("host busy / modal dialog")`; connectors run on a worker, never the Qt thread |
| 3 | **Revit API version drift** 2020↔2026 | Medium / build break | `.csproj` parameterizes `RevitYear` + NuGet `Revit_All_Main_Versions_API_x64`; keep `/exec` to stable API; build-matrix test per year |
| 4 | **AcadMCP single-port bug** — hard-coded :48885 | **Certain** (in source now) / multi-instance broken | Agent A's first task: port-range bind + session file in `AcadMCPApp.cs`, mirror `RevitMCPApp.cs` |
| 5 | **Speckle v2 vs v3** — client mixes both | High / fails on v3-only servers | Agent D migrates `_create_commit`/`_get_latest_commit` to v3 (`versionCreate`, `project.model.versions`); keep v2 fallback |
| 6 | **MS Graph app registration** — Teams needs an Azure AD app | High / Teams not live day one | Document exact steps (§3.8); ship code-complete + fixture-tested; goes live after the one-time registration |
| 7 | **Cloud rate limits** — Notion 3 req/s, Graph/Dropbox 429 | Medium / intermittent failures | Shared `base.http_with_retry`: respect `Retry-After`, exponential backoff (3 tries), paginate (`next_cursor`/`@odata.nextLink`/`cursor`) |
| 8 | **DLL-without-source** | **Low — does NOT apply** | Full C# source for Revit + AutoCAD confirmed in `payload/sources/`. Risk closed |
| 9 | **pywin32 quirks** — binding mode, COM enum constants, `makepy` cache | Medium / wrong values | Late-binding (`Dispatch`, not `gencache.EnsureDispatch`); hard-code enum ints (`outlook_runner.py`: `_OL_FOLDER_INBOX=6`); pin `pywin32>=306` |
| 10 | **Token expiry** — Graph tokens ~1 h | High (Teams) / calls fail after an hour | `teams_runner` stores the MSAL refresh token, checks expiry + silently refreshes; Speckle/Notion/Dropbox long-lived — clean "re-paste token" on 401 |
| 11 | **New Outlook (UWP)** has no COM | Medium / Outlook dead for UWP users | Documented; `probe_outlook` detects the UWP case, note says "switch to classic Outlook" — surfaced honestly |
| 12 | **3ds Max Python drift** — PySide2 vs PySide6 | Low / import fails | `max_mcp_startup.py` already tries PySide2 then PySide6 — keep |
| 13 | **Shared-file merge collisions** | High if mis-orchestrated / lost edits | §5.1: cluster agents emit `TOOLS_FRAGMENT`; only Agent F writes the 4 shared files |
| 14 | **Build machine lacks .NET SDK** | Medium / Agent A blocked | `auto_build.detect_dotnet_sdk()` → `download_dotnet_installer` + `install_dotnet_sdk` (silent); Agent A step 0 |

---

## 8. The execution checklist

Linear, ordered. The orchestrator (main Claude session) follows this top to bottom.

1. **Pre-flight probe.** `python app/host_detector.py` — capture which of the 18
   apps are `live`/`missing`. `dotnet --list-sdks`. `python -c "import win32com"`.
   Record the live-host set — this fixes the §6 live-verifiable list for this machine.
2. **Dependency install.** `pip install pywin32>=306 dropbox>=12.0,<13 msal>=1.31,<2`
   (optionally `rhino3dm>=8.0` for the Rhino fixture). `openai` already pinned. Add
   all to `requirements.txt`.
3. **Spawn Agent 0 (Scaffolding) — ALONE.** Builds `app/connectors/base.py`
   (`ConnectorOp`, `Connector`, `com_app`, `ok`/`err`, `fixture`, `http_with_retry`),
   `app/connectors/_fixtures/<family>/` dirs, `tests/conftest.py` additions,
   `_PassiveSpec` entries in `connectors/registry.py` for the new families.
   **Gate**: `python -c "import app.connectors.base"` + `pytest -q` green.
4. **If .NET SDK absent**: run `auto_build.download_dotnet_installer` +
   `install_dotnet_sdk` before Agent A.
5. **Spawn the parallel wave** — Agents **A, B1, B2, B3, C, D, E** at once. Each
   implements its hosts per §3, records fixtures, writes `tests/test_*_runner.py`,
   emits a `TOOLS_FRAGMENT`. Start Agent A first (longest critical path). No two
   agents share a file (§5.1).
6. **Wait for all 7 cluster agents** — each passes its ship gate (§5.4).
7. **Spawn Agent F (Integration) — ALONE.** Merges every `TOOLS_FRAGMENT` into
   `tool_engine.TOOLS`; adds `probe_rhino` + `probe_dropbox` (+ any missing) to
   `host_detector.PROBERS` + `HOST_DISPLAY`; adds `"rhino"` to
   `connector_health.LISTENER_URL`; adds every family prefix to
   `mcp/node_mcp.py:_HOST_TOOL_PREFIX`; confirms `register_tool_nodes()` covers
   every new tool.
8. **Integration test.** `pytest -q` — all fixture-path tests pass (host-independent);
   installed-host live tests pass; absent-host live tests `skip` (not fail).
9. **Node registration check.** `python -c "from app.workflows.nodes.tools import
   register_tool_nodes; print(register_tool_nodes())"` — count jumped by the new
   tool count (~60+).
10. **Live smoke per installed host.** For each host step 1 found `live` (AutoCAD,
    Outlook, LM Studio, + Office if present): run one real read + one real action
    op via the connector, confirm the change in the host.
11. **Detector/health verify.** `python app/host_detector.py` again — all 18 probe
    + report honest status; `connector_health.instance().snapshot()` includes `rhino`.
12. **Relaunch ArchHub.** Confirm all 18 host nodes render in the Node Library,
    each shows the correct live/offline/unauth status per the
    `HOST_NODE_UI_GRAMMAR` four-state spec, and no connector returns fabricated
    data when its host is absent.
13. **Honest status doc.** Update `docs/AUDIT_2026-05-14.md` (or a new audit) with
    the truthful per-host state: WORKS-LIVE / CODE-COMPLETE-FIXTURE / HONEST-STUB —
    matching §6. Do not mark any host "done = live" that was only fixture-verified.

---

*End of Connector Master Plan. Author: senior integrations architect, ArchHub ·
2026-05-15. Execute §8 in order. The §3 per-host spec is the contract each build
agent fulfills; the §5 ownership table guarantees no two agents collide.*
