# Host bridges

ArchHub drives Revit, AutoCAD, Rhino, Blender and 3ds Max through a small
listener inside each program. This folder is their source. The app side lives
in `nodelang/host_bridge_auth.py` (the one client that calls them),
`nodelang/host_brokers.py`, `nodelang/clean_revit_adapter.py`,
`nodelang/pipeline_engines.py` and the `host` node in `nodelang/core.py`.

| Host | Source | Listens on | Shipped as |
|---|---|---|---|
| Revit | `sources/revit_mcp`, `sources/revit_mcp_core`, `sources/shared` | first free of 48884-48899 | compiled per Revit year by `installer/build_host_bridges.ps1`; setup registers it when reviewed |
| AutoCAD | `sources/acad_mcp`, `sources/shared` | 48884-48899 (answers as `acad-mcp`) | compiled per AutoCAD year into `{app}\bridges\autocad\<year>`; **not registered** (see below) |
| 3ds Max | `sources/max_mcp/max_mcp_startup.py` | first free of 48886-48899 under `/max-mcp` | copied to `{app}\bridges\max`; setup places it in each installed version's startup folder when reviewed |
| Rhino 8 | `rhino/archhub_mcp.py` | 9879 | copied to `{app}\bridges\rhino`; "open Rhino" launches Rhino with it |
| Blender 3.6+ | `blender/archhub_mcp/` | 9876 | copied to `{app}\bridges\blender`; "open Blender" launches Blender with it |

Provenance of the .NET and Max sources: `sources/PROVENANCE.md`, licence
`sources/NOTICE.txt`, remaining build work `sources/BUILD-PROPOSAL.md`.

## Who may call a bridge

Every bridge runs code it is sent, so every bridge checks its caller first:

- `/ping` (identity) answers a local, non-browser caller. It reports no path
  on the machine.
- Every other route needs a fresh signature. The caller sends
  `X-ArchHub-Bridge-Time` (unix seconds), `X-ArchHub-Bridge-Nonce` (32 random
  hex digits) and `X-ArchHub-Bridge-Signature`, the hex
  HMAC-SHA256(secret, `METHOD|target|time|nonce|sha256hex(body)`), where
  target is the path and query exactly as sent. The bridge refuses (**401**) a
  wrong signature, a time more than 60 s from its clock, and a nonce it has
  already seen, so each signature works once, for that body only.
- A request carrying `Origin` or `Sec-Fetch-Mode` (a browser), or a `Host` that
  is not `127.0.0.1`, `localhost` or `[::1]`, gets **403**. No bridge sends a
  CORS header.
- With no secret provisioned the bridge answers **503** to everything but
  `/ping`: it fails closed.

The secret is made once by the app (`nodelang/host_bridge_auth.py`), 32 random
bytes, and kept in the app's credential store (`app/secrets_store.py`, which on
the shipped desktop is keyring, i.e. the Windows Credential Locker, entry user
`archhub-host-bridge`). The bridges read it there. It never crosses the wire and
is never written to a file. The Python bridges carry one identical copy of the
check (between the `ArchHub bridge caller check` markers); the .NET add-ins link
`sources/shared/BridgeAuth.cs`.

Limits: another process of the same Windows user can read the Credential
Locker too. A process squatting a bridge port before the host binds it receives
the app's one signed request and could forward it once, unchanged, within 60 s;
it cannot sign anything else. If keyring is unavailable the app keeps the secret
in its DPAPI file, which the bridges cannot read: they then refuse (503).

## Build, register, remove

1. `installer/build_release.ps1` calls `installer/build_host_bridges.ps1`, which
   builds the Revit add-in for every Revit year installed on the build machine
   (2020: net47, 2021-2024: net48, 2025+: net8) and the AutoCAD add-in for every
   AutoCAD year installed there, each against that year's own API assemblies,
   and writes `HOST_ARTIFACTS.json` (Revit manifests, AutoCAD pins, the Max
   script pin). Pass `-BrokerReviewPath <review file>` with the independent
   custody review of this source; without it nothing carries activation and
   setup activates nothing.
2. The installer copies `bridges/revit/<year>/`, `bridges/autocad/<year>/`,
   `bridges/max/` and `HOST_ARTIFACTS.json` into the install folder.
3. On first open, setup (`colleague_setup.py`) registers the Revit add-in for
   each packaged year that is installed (`%APPDATA%\Autodesk\Revit\Addins\<year>\RevitMCP.addin`,
   through `nodelang/host_broker_installation.py`) and places the Max script in
   `%LOCALAPPDATA%\Autodesk\3dsMax\<year> - 64bit\ENU\scripts\startup\`. It never
   overwrites a different registration or script, never needs administrator
   rights and never starts a host. Restart the host to load it.
4. Uninstall (`installer/host_registrations.iss`) deletes only a `RevitMCP.addin`
   whose assembly lies in this install's `bridges\revit\`, and only a Max
   startup script byte-identical to the one this install shipped.

AutoCAD registration is not built: AutoCAD loads .NET add-ins through an
`ApplicationPlugins\<name>.bundle\PackageContents.xml` per product series, and
no reviewed owner for writing that bundle exists yet (the Revit equivalent is
`nodelang/host_broker_installation.py`). Until one does, the compiled add-in is
carried but AutoCAD does not load it.

The v1 legacy sweep still keeps `payload\` while any Revit registration loads
from it; the new registration loads from `bridges\revit\`, never `payload\`.

## Assistants (MCP)

The installed app's MCP server is the native owner (`nodelang/native_agent_mcp.py`,
entry `archhub_agent_coordination`). Its `hosts.status` tool returns every
connector's state and each operation's evidence; host operations run only as
graph nodes inside admitted Work. Settings > Hosts > Assistants shows Claude
Code, Codex and OpenCode and writes an entry only when you press Connect
(`nodelang/assistant_registration.py`). OpenCode cannot take an MCP entry (it
gives MCP servers no session identity); it connects through the Session Link
plugin.

## What each operation has proven

`nodelang/connector_operation_evidence.py` lists every catalogue operation with
either the real court that ran it or the exact dependency that keeps it
unavailable. Settings > Hosts > Operations and `hosts.status` show the same
table.
