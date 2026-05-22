# Civil 3D connector roadmap

> **Design reference — not the roadmap.** The single roadmap / source of
> truth is [`docs/ROADMAP.md`](ROADMAP.md); the Civil 3D line lives in
> its LATER section. This document is the deferred-feature design memo.

**Status:** scaffold deferred to v1.2. Architecture documented here so the work is unblocked the moment we can compile against the Civil 3D SDK.

## Why deferred

Civil 3D's .NET API is a *superset* on top of AutoCAD's. The DLLs we need (`AeccDbMgd.dll`, `AeccApplicationsBaseMgd.dll`, `AeccPipesMgd.dll`, etc.) are shipped with Civil 3D itself and not redistributable. To build the connector you need:

1. **A machine with Civil 3D installed** (so the Aecc DLLs are present)
2. **Visual Studio 2022 + .NET 8 SDK** (already required for the Revit / AutoCAD connectors)
3. **The Civil 3D ObjectARX kit** (`https://aps.autodesk.com/developer/overview/civil-3d`) — adds samples + headers Autodesk doesn't put in the install

The CI runner that builds the Windows installer doesn't have Civil 3D installed; adding it would require either a paid Civil 3D license on the runner (expensive) or a self-hosted runner the user maintains.

## Architecture (when we ship)

```
┌──────────────┐ HTTP :48887 ┌──────────────────────┐
│   ArchHub    ├────────────►│ CivilMCP.dll          │
│  (chat/UI)   │              │ loaded into Civil 3D  │
└──────────────┘              └──────────────────────┘
                                   │
                                   ▼
                              Aecc* + Acad* APIs
                              (alignments, profiles,
                               corridors, surfaces)
```

Civil 3D = AutoCAD + Civil objects. The connector loads as a NETLOADable
`.dll` (same as `AcadMCP.dll`), but adds tool families for the
Civil-only objects:

| Tool family | Covers |
|---|---|
| `civil_ping` / `civil_info` | Health + active doc info |
| `civil_execute_csharp` | C# escape hatch (Aecc + Acad APIs in scope) |
| `civil_list_alignments` | Alignments + their stationing |
| `civil_list_profiles` | Profile views + station ranges |
| `civil_list_corridors` | Corridor models + region status |
| `civil_list_surfaces` | TIN / Grid surfaces + bounds |
| `civil_list_pipe_networks` | Pipe network names + sizes |
| `civil_extract_section` | Cross-section at station for a corridor |

## File layout (v1.2 target)

```
payload/sources/civil_mcp/
├── CivilMCP.csproj            # references Aecc* + Acad* DLLs
├── PluginEntry.cs             # IExtensionApplication
├── HttpServer.cs              # localhost listener (mirrors AcadMCP)
├── handlers/
│   ├── PingHandler.cs
│   ├── InfoHandler.cs
│   ├── AlignmentHandler.cs
│   ├── ProfileHandler.cs
│   ├── CorridorHandler.cs
│   └── SurfaceHandler.cs
└── README.md

payload/Civil/<year>/CivilMCP.dll            # built artefact
app/connectors/                              # Python side
app/acad_broker.py                           # SHARED — Civil 3D = AutoCAD doc
```

The broker is shared with AutoCAD on purpose. Civil 3D *is* AutoCAD —
sessions appear in `acad_broker.list_sessions()` with `version` carrying
a `civil-` prefix. Tool dispatch:

```python
def _broker_for(family):
    if family in ("acad", "civil"):
        return acad_broker      # same broker, both ports
```

Each session in the broker is tagged with `host_kind = "acad" | "civil"`.
Civil tools error cleanly when called against a plain AutoCAD session
(no Civil objects present).

## Detection

`auto_build.find_civil_install(year: int) -> Optional[Path]`

Probe paths:
- `C:\Program Files\Autodesk\AutoCAD 20XX` + `AeccDbMgd.dll` present
- (Civil 3D installs into the same dir as AutoCAD; the Civil bit is
  marked by the presence of the Aecc DLLs.)

## Add Host catalog entry

```python
{"id": "civil-2026", "label": "Civil 3D 2026", "kind": "civil_year",
 "year": 2026, "letter": "C"},
{"id": "civil-2025", "label": "Civil 3D 2025", "kind": "civil_year",
 "year": 2025, "letter": "C"},
```

Detection runs `find_civil_install(year)`; activation copies
`CivilMCP.dll` into `%APPDATA%\Autodesk\C3D ... \Support\` and writes
a `.bundle` PackageContents.xml entry pointing at it (same pattern as
`AcadMCP`).

## AI Behaviour defaults

```python
"civil": {
    "ping": "allow", "info": "allow",
    "execute_csharp": "ask",
    "list_alignments": "allow",
    "list_profiles": "allow",
    "list_corridors": "allow",
    "list_surfaces": "allow",
    "list_pipe_networks": "allow",
    "extract_section": "allow",
},
```

## What's blocking the ship

1. **Civil 3D licence on the build runner** — $$ per year. Options:
   - Use a self-hosted Windows runner on a workstation that already has
     Civil 3D. Cheapest.
   - Build manually on a dev box and upload the DLL as a release asset.
     Requires release discipline.
2. **No headless way to verify the build** — Civil 3D won't load the
   plugin in CI for smoke tests. We accept this and rely on the user's
   first run as the integration test.

## Until then

Civil 3D users can use the **AutoCAD** connector + the generic
`acad_execute_csharp` tool. The Acad runtime in Civil 3D exposes the
Aecc namespaces; a savvy user can write C# that talks to them. The
dedicated Civil tools are pure ergonomics, not pure capability.

## Decision

We will ship the v1.2 Civil 3D connector when **either** condition holds:

- A user with a Civil 3D licence offers to host the build runner, OR
- Civil 3D revenue from existing customers justifies paying for our own
  Civil 3D licence (~$2,400/year)

Until then this document is the design memo so the work doesn't have
to be redone when the licensing problem is solved.
