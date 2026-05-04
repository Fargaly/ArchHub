# ArchHub

A single double-clickable application that connects an architect to every AEC
tool they use, with an LLM (or a council of LLMs) as the brain and Speckle as
the data spine.

This is **not a Claude Desktop helper.** ArchHub is a standalone product:
its own chat UI, its own LLM router, its own tool execution engine, its own
Speckle integration. The user opens ArchHub, types a prompt, and ArchHub
routes the work to whatever combination of tools is needed.

## What it does

- **Chat with an LLM that can drive your tools.** Type "list all walls in the
  active Revit project" — ArchHub generates the C# code, executes it live in
  Revit, returns the result.
- **Multi-LLM council with auto-routing.** Modeling tasks → Claude. Quick
  greetings → Haiku. Complex reasoning → Opus. Multimodal → GPT-4o. The user
  can override manually in the dropdown.
- **One-click connectors.** Toggle Revit, AutoCAD, 3ds Max, Blender, Speckle,
  Rhino, SketchUp, Fusion. ArchHub installs the right add-in for the host
  application's version, registers auto-load, manages everything.
- **Speckle as the data spine.** Browse projects, fetch model versions,
  push/pull geometry. Use it to move a model from Revit to Blender to 3ds Max
  with no manual exports.
- **Agents (extensible).** DimensionsAgent, AnnotationsAgent, ParametersAgent,
  DataMappingAgent. Drop a Python file in `app/agents/` and it appears as a
  slash command.

## What's bundled in the installer

- Python 3.11 embeddable runtime (~30 MB)
- PyQt6 desktop UI (~50 MB)
- Anthropic, OpenAI, keyring SDKs
- The ArchHub application
- Connector payloads: RevitMCP.dll (per Revit version), AcadMCP.dll, 3ds Max
  startup script, Blender addon

Total installer size: ~120–150 MB. End users double-click, and within a minute
they have a working AI cockpit for their AEC stack.

## Quick start (today, while the polished installer is being built)

1. Make sure Python 3.10+ is on PATH.
2. Double-click `Install.bat`. It installs PyQt6, anthropic, openai, keyring,
   stages the app to `%LOCALAPPDATA%\ArchHub`, creates Start Menu and Startup
   shortcuts, and launches the chat window.
3. Click the gear icon (top-right) → add at least one API key (Anthropic
   recommended). Optionally add a Speckle Personal Access Token.
4. Click "Connectors" → toggle on the tools you have installed.
5. Open the host application(s). The connectors auto-load on startup.
6. Type in the chat: "Ping Revit and tell me which document is open."

## Polished installer build

On a Windows build machine with Python 3.11, PyInstaller, PyQt6, and
Inno Setup 6 installed:

```cmd
cd ArchHub
installer\build.bat
```

Output: `dist\ArchHub-Setup.exe`. Single file. Distribute that.

## Architecture

```
                    ┌──────────────────────────┐
                    │  ArchHub Desktop (PyQt6) │
                    │   - chat UI              │
                    │   - connector toggles    │
                    │   - settings / API keys  │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼──────────┐
                    │     LLMRouter       │  auto-routes by task,
                    │   Anthropic / OAI / │  manages tool-use loop
                    │       Google        │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │     ToolEngine      │  exposes tools per
                    │  (active connectors │  active connector,
                    │   only)             │  invokes them live
                    └──────────┬──────────┘
                               │
       ┌───────────────────────┼─────────────────────────────┐
       │              │              │              │         │
       ▼              ▼              ▼              ▼         ▼
   localhost      localhost      localhost      localhost   Speckle GraphQL
   :48884         :48885         :48886         :9876       (cloud)
       │              │              │              │         │
   RevitMCP       AcadMCP        3ds Max        Blender    Project data,
   .NET addin     .NET plug      pymxs          MCP addon  versions, etc.
       │              │              │              │
   Revit API      AutoCAD API    3ds Max API    bpy
```

The LLMRouter holds the tool-use loop. When the LLM emits a tool call,
ToolEngine invokes the right backend, packages the result, and feeds it back
to the LLM. The conversation continues until the LLM emits a final text
response.

## File map

```
ArchHub/
├── Install.bat                 Quick-install (no compile, dev path)
├── installer/
│   ├── setup.iss               Inno Setup script
│   └── build.bat               End-to-end .exe build
├── app/                        ArchHub Python source
│   ├── main.py                 Entry point
│   ├── chat_window.py          Main chat UI
│   ├── connector_panel.py      Connector toggle dialog
│   ├── settings_dialog.py      API keys management
│   ├── llm_router.py           Multi-LLM routing brain
│   ├── llm_providers/          Per-provider clients
│   │   ├── anthropic_client.py
│   │   ├── openai_client.py
│   │   └── google_client.py
│   ├── tool_engine.py          Tool catalogue + invocation
│   ├── speckle_client.py       Speckle GraphQL client
│   ├── secrets_store.py        OS keyring + file fallback
│   ├── manager.py              ConnectorManager
│   ├── detection.py            Detect installed AEC tools
│   ├── connectors/             Per-family activate/deactivate
│   │   ├── __init__.py
│   │   └── registry.py
│   ├── agents/                 Pluggable agents
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── dimensions_agent.py
│   ├── tray.py                 System tray
│   ├── theme.qss               Dark Qt stylesheet
│   ├── requirements.txt
│   └── assets/
│       ├── archhub.ico
│       └── archhub.png
└── payload/                    Bundled connector files
    ├── bridge/
    │   ├── server.py           Legacy unified MCP (still useful for
    │   └── requirements.txt    Claude Desktop users)
    ├── revit/<year>/
    ├── autocad/<year>/
    ├── max/
    └── blender/
```

## Roadmap (next milestones)

- **Agents in the chat** — `/dimensions`, `/annotations`, `/parameters`,
  `/data-mapping`. Each agent is a pluggable Python class.
- **Speckle round-trip** — push geometry from Revit → Speckle → Blender → 3ds
  Max in one prompt. Already wired up at the API level; needs UX polish.
- **Image input in chat** — drop a screenshot or a sketch, ArchHub uses a
  multimodal model to interpret it and turns it into geometry.
- **Project memory** — per-project conversation history + Speckle metadata,
  so the assistant has continuity across sessions.
- **Council mode** — multiple LLMs running in parallel on hard prompts,
  ArchHub picks the best answer (or routes to the user to pick).
- **Native modeling environment** — Stage 3 of the original vision. ArchHub
  becomes the canvas, Revit/AutoCAD/Max become exporters.

## License

TBD. Likely a permissive core (MIT/Apache 2.0) with optional commercial
extensions for enterprise features (multi-user workspaces, hosted LLM
key relay, Speckle Enterprise sync, audit logging).
