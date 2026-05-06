> ⚠️ **INTERNAL DOCUMENT.** Engineering decisions and rationale,
> intended for maintainers. Some entries reference comparable tools
> for context — those are technical notes, not marketing copy.

# ArchHub — Development Log

A running record of architectural decisions, pivots, and rationale.
Newest entries at top.

---

## v0.11.0 — 2026-05-06 — Sketch → Production + threat moats

**The pivot.** ArchHub is no longer "sketch → mass". It is **sketch →
production drawings**, end-to-end, in a single Skill. The user's
brief: *I'm going with sketch to production... not just sketch to mass.
It interacts with Revit and other tools and creates families... setup
projects... annotate.* The whole pipeline now exists as Skills the
matcher can pick from chat, plus one master Skill that chains every
stage in one prompt.

**Six new production-pipeline Skills (`app/skills/production_seeds.py`):**

| ID | Name | Stage |
|----|------|-------|
| `seed-extract-mass-from-sketch-v1` | Extract mass from sketch | Vision → parameters → Blender mass |
| `seed-setup-revit-project-v1` | Set up Revit project | Levels, grids, units, default types, cover sheet |
| `seed-mass-to-walls-v1` | Convert mass to Revit walls | Mass faces → stacked walls per level |
| `seed-place-openings-v1` | Place doors and windows | Default fenestration on every wall |
| `seed-generate-production-sheets-v1` | Generate production sheets | Plans / elevations / sections / room schedule on sheets |
| `seed-sketch-to-production-v1` | **Sketch to production** | All six above chained in one workflow |

The master `sketch-to-production` Skill is a six-stage workflow graph:
each stage is its own `llm.complete_with_tools` node with a focused
framing prompt + an `allowed_tools` whitelist. The previous stage's
output flows into the next stage's prompt template, so each stage
sees what the model just did. One "Run" click triggers the whole
pipeline.

Skill JSON carries the *intent and constraints*, not the
implementation. The actual Revit C# is generated fresh per project by
whichever LLM the router picks (Claude for cloud, qwen2.5-coder for
local). When foundation models get smarter at Revit, the Skills layer
captures the firm's accumulated practice; better models make Skills
*more* valuable, not less.

`main.py` now calls `ensure_production_skills()` on launch alongside
the existing `ensure_starter_skills()`. Both are idempotent — they
only seed Skills missing from the current library.

### Threat defenses (from the competitive brief)

The brief listed five threats. Defenses now baked into the product:

1. **"Anthropic / OpenAI ship native AEC MCP servers."**
   Defense: ArchHub is a *Skill execution layer*, not a tool catalogue.
   When generic AEC MCP arrives, ArchHub still owns:
   - the user's saved Skills (cloud-synced, shareable JSON)
   - the parametric DAG memory across stages
   - the multi-LLM router (any model can drive any Skill)
   - the user's domain practice expressed as Skills the firm has tuned
   Generic MCP gives ArchHub a *richer toolbox*, not a replacement.

2. **"Autodesk acquires/builds Forma equivalent."**
   Defense:
   - Open source, no Autodesk tax
   - Multi-tool roundtrip (Revit ↔ Blender ↔ Speckle ↔ Max) — Forma is
     Autodesk-only
   - Local LLM path via Ollama for IP-sensitive firms — never possible
     for Forma
   - Skills are JSON the user owns, exports, and forks. Forma will
     never let users do that.

3. **"Hypar adds a chat layer."**
   Defense:
   - Already shipped — speed advantage in current market
   - Native Revit C# generation (Hypar is web-only)
   - Cloud-synced personal Skill library — Hypar's functions are
     central, not personal

4. **"Grasshopper community plugin ships chat-over-graph."**
   Defense:
   - Coexist via Speckle: ArchHub + Grasshopper users share data
   - ArchHub spans hosts (Revit, AutoCAD, Max, Blender), Grasshopper
     is Rhino-only
   - Skills are the asset; let the visual canvas catch up later

5. **"Foundation models become 10× better at Revit C#."**
   Defense:
   - Skills layer captures *intent + constraints + safety wrappers*
   - Smarter models execute Skills better, not around them
   - Skills are the moat: portable, copy-paste-shareable JSON the
     user can edit, version, and learn from

### What this kills
- "Sketch → mass" framing — too thin, table stakes by 2027
- Single-step Skills as the only Skill kind — chained workflows are
  first-class now
- Treating the LLM as the product — the **Skills + LLM** combo is

### What this preserves
- The four-node `_build_chain` pattern (input → template → llm → output)
  is still how single-stage Skills are built
- Users can still pick an individual stage Skill from the panel
- Cloud sync, OAuth sign-ins, vision input, glass theme all from the
  prior 0.11.0 commit

---

## v0.10.0 — 2026-05-05 — Skills system

**The frame shift.** Annotation, materials, sketch-to-mass, render, push-to-Speckle
— none of these are *features*. Each is a **Skill**: a saved workflow with intent
metadata that the chat can find, run, edit, share, and learn from. Hardcoded
agent classes (DimensionsAgent, AnnotationsAgent) are dead. Skills are JSON
files anyone can edit, and a new Skill ships to all 50 architects in the firm
without a code change.

The mental model is ComfyUI under the hood, chat on top: behind every Skill
is a node graph, but the architect rarely sees it. They type. The chat finds
the right Skill (or composes a new one), runs it, shows the answer.

**What ships in v0.10.0:**

- `app/skills/` — new package on top of `app/workflows/`:
  - `metadata.py` — `SkillMeta` dataclass (`intent`, `keywords`, `when_to_use`,
    `examples`, `tags`, `requires`, `author`, `scope`, `version`). Stored as
    `Workflow.metadata['skill']` so the on-disk schema is one file per Skill.
  - `library.py` — `list_skills`, `load_skill`, `save_skill`, `delete_skill`
    across two roots: per-user (`%LOCALAPPDATA%/ArchHub/workflows/`) and
    machine-wide (`%PROGRAMDATA%/ArchHub/skills/`) for team/firm scope.
    User overrides shared on id collision.
  - `matcher.py` — `match_skills(prompt, ...)` ranks Skills against a user
    prompt using a weighted keyword score (keyword ×3, tag ×2, name ×1.5,
    intent ×1.0), filtered by active connectors. Optional LLM rerank via
    Haiku for tied candidates (off by default in v0.10).
  - `capture.py` — `capture_chat_as_skill(history, ...)` summarises the last
    12 chat turns, asks Haiku to author strict-JSON metadata, then wraps the
    conversation in a Workflow via the existing `chat_to_workflow` helper.
  - `usage.py` — sidecar JSON (`skill_usage.json`) tracking `runs`,
    `successes`, `failures`, `last_used`, `total_elapsed_ms` per Skill.
    Per-user only — never synced.
  - `seeds.py` — three starter Skills materialised on first launch:
    `dimension-walls`, `room-tags`, `push-to-speckle`. Each is a four-node
    chain (input → template → llm.complete_with_tools → output) with an
    `allowed_tools` whitelist that scopes the LLM to the right connectors.

- `app/skills_panel.py` — new dialog with two tabs:
  - **Skills** — cards with intent, tags, examples, run count, success
    rate, last-used. Run / Edit / Delete on each card.
  - **Workflows** — preserved JSON list/editor for power users.
  - The header chat button is renamed *Skills*; the legacy *Workflows*
    entry point routes here too.

- `app/chat_window.py` — chat surface for Skills:
  - Slash commands: `/skill save [name]`, `/skill list`, `/skill run <id|name>`,
    `/skills`, `/help`.
  - Auto-suggestion: before the LLM tool loop runs, the matcher checks the
    user's prompt against the library. A strong match (score ≥ 0.55, or
    ≥ 0.10 ahead of the runner-up) shows an inline “💡 Skill match” bubble
    with **Run / Skip** buttons. Skip falls through to the normal LLM path.
  - Skill execution wraps `WorkflowExecutor.run` and records usage stats
    via `skills.record_run(...)`.

- `app/workflows/graph.py` — `Workflow` gains a `metadata: dict` field
  (default empty). Backward-compatible: workflows saved before this
  release deserialise unchanged.

- `app/main.py` — calls `skills.ensure_starter_skills()` once at boot.
  Idempotent; never overwrites a user-edited Skill (id-keyed).

- `app/theme.qss` — styles for the Skills panel, skill cards, tabs, and
  the inline skill-suggestion bubble.

- `docs/SKILLS.md` — architecture doc covering the mental model, file
  layout, JSON schema, matcher tiers, capture flow, sharing strategy,
  telemetry, extension points, and roadmap.

**End-to-end smoke test (no Revit required):**

```
$ python -c "import skills; skills.ensure_starter_skills(); print(skills.list_skills())"
[
  {'id': 'seed-dimension-walls-v1', 'name': 'Dimension walls in active view', ...},
  {'id': 'seed-room-tags-v1',       'name': 'Tag every room in active view',  ...},
  {'id': 'seed-push-to-speckle-v1', 'name': 'Push current model to Speckle',  ...}
]

$ python -c "import skills; print(skills.match_skills('Dimension all walls'))"
[MatchResult(name='Dimension walls in active view', score=0.55, ...)]
```

**What this kills:**

- DimensionsAgent / AnnotationsAgent code classes → dead. Replaced by
  user-editable Skill JSON.
- Per-feature slash commands (`/dimensions`, `/annotations`) → dead.
  Replaced by one `/skill <verb>` plus the matcher.
- The "drop a Python file in `app/agents/`" extension model → dead.
  Skills are JSON; no Python deploy needed to add a capability.

**What this preserves:**

- The workflow engine, JSON format, executor, and node registry — Skills
  are a metadata layer over them.
- The legacy `app/agents/` package — still loads, no migrations forced.
- The Workflows tab in the panel — power users can still edit raw JSON.

**Sharing strategy (v0.10):** local-only. Drop a `.archhub-workflow.json`
into `%PROGRAMDATA%\ArchHub\skills\` on each machine, or symlink that path
to a network share / OneDrive / Git repo. A first-class sync mechanism
(Git-backed registry, Speckle stream, or HTTP relay) lands once one of
those shapes proves itself in real use across the 50-architect pilot.

---

## v0.9.0 — 2026-05-05 — Speckle spine

**The data spine.** Speckle is now the interoperability layer between
ArchHub sessions and every CAD host. Parameters flow both ways: push
serialises the live session into a versioned Speckle object and creates
a commit; pull fetches the latest commit and injects its properties back
into the session, marking downstream steps DIRTY so the chain re-runs.

**What ships in v0.9.0:**

- `app/speckle_client.py` — extended with full push/pull transport:
  - `push_parameters(project_id, branch, parameters, geometry_ref, message)`
    serialises the session's parameter pool into a typed Speckle object
    (`Objects.BuiltElements.ArchHub.ParameterSet@1.0.0`), computes its
    SHA-256 id (`_hash_object`), uploads it to the object store
    (`POST /objects/{projectId}`), then creates a commit via the GraphQL
    `commitCreate` mutation. Returns `{"status": "ok", "commit_id": "...",
    "object_id": "..."}`.
  - `pull_parameters(project_id, branch)` queries the latest commit on
    the branch via `stream > branch > commits`, downloads the root object
    (`GET /objects/{projectId}/{objectId}/single`), and returns the raw
    `parameters` dict for the runner to inject.
  - `_create_commit` / `_get_latest_commit` — thin wrappers around the
    existing `_query` helper. Uses the v2-compatible `commitCreate` /
    `stream > branch > commits` API which works on all Speckle server
    versions including the latest `app.speckle.systems`.
  - `_hash_object` — canonical SHA-256 of the object payload (sorted
    keys, no whitespace, `id` field excluded from hash input) following
    the Speckle object model convention.

- `app/runners/speckle_push.py` — `StepKind.SPECKLE_PUSH` runner:
  - Reads `project_id` from `step.config` or session parameter
    `speckle_project_id` (allows the LLM to set it via a plan step).
  - Snapshots all `session.parameters` values into a plain dict.
  - Grabs `geometry_ref` from the most recent `GEOMETRY_BUILD` step output
    (if any) so geometry and parameters travel together.
  - Calls `SpeckleClient.push_parameters()`.
  - Upserts `speckle_version_id` and `speckle_object_id` back into the
    session so subsequent steps can reference them.
  - Returns a `StepOutput(kind="text")` with a human-readable summary.

- `app/runners/speckle_pull.py` — `StepKind.SPECKLE_PULL` runner:
  - Calls `SpeckleClient.pull_parameters()`.
  - Injects each key from the pulled `parameters` dict: updates existing
    session parameters (triggering dirty propagation downstream) and
    creates new ones for unknown keys (type inferred from Python type).
  - Injects `speckle_geometry_ref` (GEOMETRY) if present.
  - Upserts `speckle_version_id` and `speckle_object_id` from the pulled
    commit metadata.
  - Returns a `StepOutput(kind="text")` listing new vs. updated counts.

- `app/runners/__init__.py` — registered `speckle.push` and `speckle.pull`.

**Bidirectional parameter sync in practice:**

```
User: "push to Speckle"
  → LLM_PLAN adds SPECKLE_PUSH step with project_id from user context
  → SPECKLE_PUSH snapshots {building_height: 12, roof_pitch: 35, …}
  → Speckle object hash = abc123
  → Commit "ArchHub push" on archhub/main
  → session: speckle_version_id = "commit_xyz"

[Revit user edits roof_pitch to 40 in their session, pushes their own commit]

User: "pull from Speckle"
  → SPECKLE_PULL fetches latest commit → {building_height: 12, roof_pitch: 40}
  → session.update_parameter("roof_pitch", 40) → GEOMETRY_BUILD marked DIRTY
  → RENDER + IMAGE_PROCESS also marked DIRTY
  → rerun_dirty() fires → geometry rebuilt with new pitch → re-rendered automatically
```

---

## v0.6.0 — 2026-05-04 — Parametric session core, meta-connector, Blender runner

**The pivot.** ArchHub stops being "a chat that calls tools" and becomes
a parametric design environment with chat as the input surface. Two
foundational principles, captured in `VISION.md` at repo root:

1. **Connectors build themselves.** ArchHub asks the LLM to generate the
   adapter code per host/version. Static `payload/sources/` is now the
   cached fallback, not the primary path.
2. **Every step is a parametric node.** Parameters never die — they
   appear in a sidebar the moment they're introduced and stay live.
   Editing one marks downstream steps DIRTY and re-runs them.

**What ships in v0.6.0:**

- `VISION.md` — the north-star document for everything that follows.
- `app/session.py` — Session, ChainStep, Parameter, ParamType, StepKind,
  StepStatus, StepOutput. Pure data + state machinery, no UI or tool
  coupling. Dirty propagation (changing a parameter marks all steps
  that use it AND everything downstream as DIRTY) is verified by tests.
  Stable input hashing via SHA-256 over (parameters_used + config).
- `app/parameters_panel.py` — Qt sidebar that mirrors the session's
  parameter pool live. Renders Length/Angle/Number as slider+spinbox,
  Integer as spinbox, Boolean as checkbox, Enum as dropdown, Color as
  swatch, String as line-edit, Image/Geometry as readonly path. Edits
  emit `parameter_edited(name, value)` which the chat window debounces
  and routes to `Session.update_parameter`.
- `app/meta_connector.py` — the LLM-as-codegen pattern. Two contracts
  (Blender Python addon, Revit C# add-in) and one entry point per host:
  `generate_blender_addon(version, router)`,
  `generate_revit_addin(version, router)`. Output is content-hashed and
  cached in `payload/_generated/`. Validation rejects obviously broken
  output (Blender addon must have bl_info, register, unregister, the
  contract port). Multi-file parser handles `### FILE: <path>` headers
  for languages that need multiple files.
- `app/connectors/blender_runner.py` — concrete Blender adapter:
  `find_blender_executable()`, `detect_blender_version()`,
  `find_addons_folder(version)`, `install_addon(generated, ...)`,
  `launch_blender(...)`, `ping_until_ready()`, `info()`, `execute(code)`,
  `render(output_path)`. Talks HTTP to the addon on port 9876.
- Chat window — now has a horizontal splitter: chat on the left,
  parameters panel on the right (default 840 / 320 px). Window sized up
  to 1200×760 to accommodate. The session is created in `__init__`,
  bound to the panel via `set_session`, and parameter edits debounced
  via a 300 ms QTimer before being acknowledged in the chat.
- Theme — extended `theme.qss` with paramsPanel / paramRow / slider /
  spinbox / combobox styles in the Claude-orange palette.

**Verified by tests run today:**
- Adding parameters, adding chain steps, status transitions, dirty
  propagation all behave correctly.
- A camera-height change marks only Render and Post-process DIRTY,
  leaves the Geometry step alone.
- Input hashing is stable for unchanged values, changes when values do.
- Multi-file parser handles realistic LLM output.
- Python validation rejects non-addon code, accepts contract-compliant
  stubs.

**Files added:** 4 (session, parameters_panel, meta_connector, blender_runner).
**Files changed:** 2 (chat_window, theme).
**Total Python files in app:** 41 (was 37).

**What's NOT in this commit (deliberately):**
- StepKind runners — geometry.build / render / image.process don't yet
  have concrete executors that drive Blender end-to-end. The data model
  is ready; the runner is ready; the bridge is what comes next.
- The chat-side flow that introduces parameters from a user prompt.
  v0.7 wires LLM_PLAN: take the user prompt, decide which parameters
  to introduce, which steps to chain, then dispatch the runners.
- Image input (paste a sketch). The model is in place — Parameter type
  IMAGE exists — but the chat input bar doesn't accept images yet.

**Next concrete milestone (v0.7):**
The minimum demo from VISION.md:
> Toggle Blender on. ArchHub generates the addon if missing. Paste a
> sketch. Type "build this in 3D". Sidebar populates. Render shows.
> Drag roof_pitch slider. Re-render in 3 seconds.

---

## v0.5.1 — 2026-05-04 — GUI installer, no terminal output

**The point user kept making, that I kept missing:** end users don't see
cmd windows, don't see PowerShell prompts, don't see step-by-step text logs.
They click one file and watch a window. v0.5.0's `upgrade.ps1` failed exactly
because the end user saw a "Supply values for the following parameters:
InstallDir:" prompt — the trailing-backslash quoting bug ate the parameter,
and PowerShell fell back to interactive input.

**What ships now:**
- `Install.vbs` — the file the user double-clicks. Zero visible cmd or
  PowerShell. Reads VERSION, fires PowerShell with `-WindowStyle Hidden` via
  `WScript.Shell.Run(..., 0, False)` (invisible, fire-and-forget).
- `installer/install_gui.ps1` — replaces `upgrade.ps1`. Runs all install
  logic but presents it through a `System.Windows.Forms` dialog: dark-themed
  header, Claude-orange progress bar, single status line, single button.
  No console output, ever.
- `Install.bat` — kept as a fallback for users who prefer the cmd route.
  Now strips the trailing backslash from `%~dp0` before passing arguments
  (the original v0.5.0 bug fix).

**Visual states the user sees:**

| Phase           | Title                  | Subtitle                              | Button   |
|-----------------|------------------------|---------------------------------------|----------|
| First install   | Installing ArchHub     | Installing version 0.5.1...           | Cancel   |
| Upgrade in flight| Updating ArchHub      | Updating from 0.5.0 to 0.5.1.         | Cancel   |
| Repair          | Repairing ArchHub      | Reinstalling version 0.5.1.           | Cancel   |
| Success         | ArchHub installed      | Click Launch to open it.              | Launch   |
| Failure         | Installation failed    | <plain-English error message>         | Close    |

**Architectural choice: WinForms over a real .exe.** The proper end-state
is a single signed `ArchHub-Setup.exe` produced by Inno Setup, requiring a
Windows build machine + iscc.exe + a code-signing certificate. The `.iss`
script is in the repo (`installer/setup.iss`) but compilation needs CI infra
that doesn't exist yet. WinForms-via-PowerShell ships on every Windows
machine and gets us 90% of the polish today. The `.exe` upgrade is a future
step, not a blocker.

**Bonus fix.** `upgrade.ps1` got removed; its logic moved inline into
`install_gui.ps1`. One source of truth.

---

## v0.5.0 — 2026-05-04 — Upgrade-aware installer

**Direction:** A real product installer detects the previous version, stops
the running app, preserves user data, and replaces only what changed. v0.4.0's
`xcopy /e` did none of that.

**What ships:**

- `VERSION` at repo root — single source of truth for the installer.
- `requirements.txt` — pinned dependencies; the upgrader hashes this to
  decide whether `pip install` needs to run.
- `installer/upgrade.ps1` — the new heart of the installer. Detects existing
  installation via `version.json`, stops any running ArchHub instance by
  matching the command line, ensures user-data dirs exist without touching
  their contents, mirrors code dirs with `robocopy /MIR` (so files removed
  in the new version are cleaned up), and writes a fresh version stamp
  including the previous version for upgrade history.
- `Install.bat` — now a thin wrapper that reads `VERSION`, calls
  `upgrade.ps1`, writes the launcher .cmd files, calls `make_shortcuts.ps1`,
  and launches the app. About 50 lines, all of them honest.
- `version.json` — written into the install dir on every install. Contains
  current version, previous version, install timestamp, install dir.

**User-data preservation rules.** The upgrader knows the difference between
*code* (replace cleanly) and *user data* (never touch). User data:
`workflows/`, `state.json`, `secrets.dat`, `logs/`, and crucially
`payload/revit/<year>/`, `payload/autocad/<year>/`, `payload/max/<year>/`
which is where auto_build writes user-built connector binaries. Code:
`app/`, `payload/sources/`, `payload/bridge/`, `payload/blender/`,
`installer/`. Mirrored, not merged — orphan files from older versions
get cleaned up.

**Bug fix found en route.** `manager.PAYLOAD_DIR` and `auto_build.PAYLOAD_DIR`
pointed to different directories in v0.4.0 (`%LOCALAPPDATA%\ArchHub\payload\`
vs `%LOCALAPPDATA%\ArchHub\app\payload\`). Auto-build would have succeeded
but activation would still have failed because the manager looked elsewhere.
Consolidated to the top-level `payload/` and moved the bundled C# sources
from `app/payload/sources/` to `payload/sources/`.

**Upgrade flow user sees:**
```
====================================================
  ArchHub - Updating v0.4.0 -> v0.5.0
====================================================

[1/5] Stopping any running ArchHub...
       Stopping PID 18432
[2/5] Checking Python dependencies...
       Unchanged. Skipping pip install.
[3/5] Preserving user data...
       Workflows, state, and built binaries kept as-is.
[4/5] Syncing app to C:\Users\fargaly\AppData\Local\ArchHub...
       Done.
[5/5] Recording version...
       Done.

====================================================
  Updated: 0.4.0 -> 0.5.0
====================================================
```

**Future hooks.** The upgrade.ps1 has clear extension points for: schema
migrations between versions (when `state.json` or `workflows/*.json` shape
changes), rollback to previous version (would require a backup step before
mirror), and silent updater that runs in the background and notifies the
chat window when a new version is available.

---

## v0.4.0 — 2026-05-04 — In-app connector setup, no terminal

## v0.3 — 2026-05-04 — Workflow layer (phase 1 of node-based paradigm)

**Direction:** Treat the application like ComfyUI / Grasshopper — AI models
and tools as nodes, wired into workflows that execute as DAGs. Architects
already speak this language fluently (Grasshopper, Dynamo), so the
onboarding cost is near zero.

**Phase 1 ships now:** graph data model + headless executor + chat-to-
workflow capture. No canvas UI yet (that's phase 3) — workflows are authored
either by capturing a chat conversation or by editing JSON.

**Components added:**
- `workflows/graph.py` — Workflow / Node / Edge / Port / Trigger dataclasses,
  JSON serialization, validate() + topological sort with cycle detection.
- `workflows/registry.py` — NodeSpec + executor registration.
- `workflows/executor.py` — WorkflowExecutor with per-node lifecycle events
  (started, finished, failed, log) for streaming UI updates.
- `workflows/nodes/io_data.py` — input.parameter, output.parameter,
  data.constant, data.template (with {var} substitution).
- `workflows/nodes/llm.py` — llm.complete, llm.complete_with_tools (with
  tool whitelist), llm.classify.
- `workflows/nodes/control.py` — control.if, control.merge, control.foreach
  (foreach is single-pass v0; sub-graph fan-out is phase 2).
- `workflows/nodes/tools.py` — `register_tool_nodes()` auto-creates a
  `tool.<name>` node type for every entry in `tool_engine.TOOLS`. Single
  source of truth, zero duplication.
- `workflows/library.py` — save / load / list / delete in
  `%LOCALAPPDATA%/ArchHub/workflows/`.
- `workflows/triggers/scheduler.py` — TriggerScheduler with manual / cron /
  file_watch / speckle_webhook (last one is a stub for phase 2).
- `workflows/chat_to_workflow.py` — converts ChatMessage history into a
  runnable Workflow. **The killer feature**: every chat is a reusable asset.
- `workflows_panel.py` — modal dialog listing saved workflows + JSON editor.
- `run_workflow.py` — CLI runner for headless execution (cron, CI, scripts).
- Chat window integration — "Save chat" + "Workflows" buttons.
- main.py — register tool nodes + start/stop trigger scheduler at app lifecycle.

**Strategic rationale documented in the previous turn's research:**
ComfyUI-style paradigm has matured (n8n 40K+ stars, Flowise just acquired by
Workday, ComfyGPT/ComfyUI-Copilot academic literature). None of them speak
AEC. Architects already live in node-based thinking via Grasshopper/Dynamo,
so this pattern is native to the audience. The wedge: be Grasshopper for AI
agents, native to Speckle, fluent in every AEC tool.

**Roadmap:**
- Phase 2 — sub-graph fan-out for foreach, real Speckle webhook receiver,
  retry/error-tolerant branches, parallel execution where the graph permits.
- Phase 3 — node canvas UI (Qt Graphics or web view), drag-and-drop wiring,
  live execution highlighting, node palette populated from the registry.
- Phase 4 — agents become workflow templates: DimensionsAgent / AnnotationsAgent /
  ParametersAgent / DataMappingAgent are saved workflows callable as single
  nodes from higher-level graphs.

---

## v0.2 — 2026-05-04 — Standalone product with multi-LLM brain

**Pivot:** ArchHub is no longer a Claude Desktop helper. It's its own
desktop application with built-in chat, multi-LLM router, tool execution
engine, and Speckle integration. Claude Desktop is no longer required for
end users.

**Why:** A connector toggle UI alone forces every user to also install
Claude Desktop and configure it. That's two products, two installations,
two failure surfaces. ArchHub becomes the product instead.

**What changed:**
- New: `chat_window.py` — main UI, streaming responses, inline tool-call cards
- New: `llm_router.py` — auto-routes to Claude/OpenAI/Gemini based on task signal
- New: `llm_providers/{anthropic,openai,google}_client.py` — per-provider clients
- New: `tool_engine.py` — single tool catalogue, dispatches to host HTTP servers
- New: `speckle_client.py` — Speckle GraphQL client (list_projects, get_project)
- New: `secrets_store.py` — Windows Credential Manager via keyring with file fallback
- New: `settings_dialog.py` — manage API keys per provider
- New: `agents/` — pluggable agent framework, `DimensionsAgent` skeleton
- Updated: `main.py` boots ChatWindow instead of ConnectorPanel
- Updated: installer bundles anthropic, openai, keyring SDKs

**Tool-use loop lives in LLMRouter.** When a model emits a tool call, the
router runs it through ToolEngine, packages the result, and feeds it back.
Up to 12 iterations per turn (safety cap on runaway agents).

**Auto-routing heuristics (v0):**
- Modeling signals (revit/autocad/3ds max/blender/wall/extrude/...) → Claude Opus
- Analysis signals (schedule/quantity/audit/explain/...) → Claude Sonnet
- Quick chat → Claude Haiku
- Default → Claude Sonnet
- Fallback chain when Anthropic key missing: OpenAI → Google

This is keyword-based and crude. Upgrade path: small classifier model
(GPT-4o-mini or Haiku) does intent classification, then routes.

---

## v0.1 — 2026-05-04 — Connector toggle product (superseded)

First attempt: a tray app + connector toggle panel that registered a
unified MCP server in Claude Desktop's config. Worked but dependent on
Claude Desktop being installed and running.

**Components built that survived into v0.2:**
- `manager.py` — ConnectorManager with state persistence
- `detection.py` — Detect installed Autodesk/Blender/Rhino/SketchUp
- `connectors/registry.py` — Per-family activate/deactivate (Revit addin
  install, AutoCAD HKCU registry, 3ds Max startup script, Blender addon)
- `tray.py` — System tray icon
- Inno Setup installer (`installer/setup.iss` + `build.bat`)
- Theme stylesheet (`theme.qss`)

---

## Pre-ArchHub — Earlier sessions

- Built `AutodeskMCP/` as a comprehensive C# add-in suite for Revit and
  AutoCAD with Roslyn live scripting, plus a 3ds Max pymxs HTTP server.
  These are the "payload" binaries ArchHub installs into the host
  applications.
- Designed the original Blender → Fusion → Revit interop chain.
- Researched Speckle: $19.2M Series A, 20+ connectors, Apache 2.0
  license. Decision: build ON TOP of Speckle, not against it. Speckle
  becomes ArchHub's data spine for cross-tool interop.

---

## Open questions / next milestones

- **Agent execution path.** `DimensionsAgent.run()` is a skeleton. Need
  to implement the LLM-with-restricted-tools pattern: run the router
  with a tool whitelist (e.g. only `revit_*`), capture invocations,
  return AgentResult.
- **Speckle round-trip.** Push geometry from Revit → Speckle → Blender
  in one prompt. ToolEngine has `speckle_list_projects` and
  `speckle_get_project`; needs `speckle_create_version` and
  `speckle_pull_to_<host>` tools.
- **Connector payload binaries.** Revit/AutoCAD DLLs need to be built
  per-version (2024, 2025, 2026) from the C# source in `AutodeskMCP/`
  and dropped into `payload/{revit,autocad}/<year>/`. One-time per
  Autodesk release.
- **Icons.** `app/assets/archhub.ico` and `archhub.png` need to be
  designed before shipping the polished installer.
- **Image input in chat.** Drop a screenshot, ArchHub uses multimodal
  Claude/GPT-4o to interpret it.
- **Project memory.** Per-project conversation history + Speckle metadata
  for continuity across sessions.
- **Council mode.** Run multiple LLMs in parallel on hard prompts, pick
  the best answer. Requires a judge model and a UX for when two
  responses differ meaningfully.

---

## Architectural principles (so far)

1. **Bring-your-own keys.** No hosted relay in v0; users provide their
   own Anthropic/OpenAI/Google/Speckle credentials. Stored in OS
   keyring. Future commercial path: optional managed relay with
   subscription.

2. **Local-first.** All host application servers run on localhost. No
   user model data leaves the machine without an explicit Speckle push
   or LLM tool call.

3. **Speckle is the interop spine.** We don't reinvent BIM
   serialization. Speckle's object graph + connectors carry the data.

4. **The LLM is replaceable.** Every provider implements the same
   `stream_completion(...)` interface. New providers slot in without
   touching the router or tool engine.

5. **Connectors stay sovereign.** Toggling on Revit installs an addin
   into Revit; toggling off removes it cleanly. No vendor lock-in.

---

---

## v0.7.0 — 2026-05-05 — End-to-end parametric demo

**The minimum demo ships.** v0.7 closes the loop described in VISION.md:
type a prompt → parameters appear → Blender builds geometry → renders →
drag a slider → re-renders in seconds.

**What ships in v0.7.0:**

- `app/runners/` module — step-kind runners dispatched from a registry:
  - `llm_plan.py` — extracts parameters + pipeline steps from user prompt via LLM
  - `geometry_build.py` — generates and executes Blender Python via LLM + blender_runner
  - `render_runner.py` — triggers Blender render, saves PNG to ArchHub/renders/
  - `image_process.py` — PIL post-processing (brightness, contrast, saturation, warmth)
- `app/session_runner.py` — orchestrates step chains:
  - `run_from_prompt()` — full pipeline from user message
  - `rerun_dirty()` — re-runs from first DIRTY step after parameter edit
- `app/chat_window.py` — extended:
  - `_SessionWorker` QThread drives session_runner on background thread
  - `_on_session_event` streams progress + images into the conversation
  - `_on_parameter_edited` debounces slider edits → triggers rerun_dirty
  - `_run_workflow_by_id` completed (was cut off in v0.6)
- `payload/blender/archhub_mcp/__init__.py` — full HTTP server:
  - /ping, /info, /execute, /render endpoints
  - bpy main-thread marshaling via bpy.app.timers.register
  - Background server thread, clean lifecycle (register/unregister)

**What's next (v0.8):**
- Image paste input (sketch → parameters)
- Meta-connector: auto-generate the Blender addon via LLM if missing
- Connector panel "generate addon" button
- Session serialization (save/load parametric sessions as files)
