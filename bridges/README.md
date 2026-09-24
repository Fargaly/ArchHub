# Host bridges

ArchHub drives Revit, AutoCAD, Rhino, Blender and 3ds Max through a small
listener inside each program. This folder is their source. The app side lives
in `nodelang/host_brokers.py`, `nodelang/clean_revit_adapter.py` and
`nodelang/pipeline_engines.py`.

| Host | Source | Listens on | Shipped as |
|---|---|---|---|
| Revit | `sources/revit_mcp`, `sources/revit_mcp_core`, `sources/shared` | first free of 48884-48899 | compiled per Revit year by `installer/build_revit_bridge.ps1`, registered by setup |
| AutoCAD | `sources/acad_mcp`, `sources/shared` | 48884-48899 (answers as `acad-mcp`) | source only; not packaged yet |
| 3ds Max | `sources/max_mcp/max_mcp_startup.py` | first free of 48886-48899 under `/max-mcp` | copied to `{app}\bridges\max`; not placed in a 3ds Max startup folder |
| Rhino 8 | `rhino/archhub_mcp.py` | 9879 | copied to `{app}\bridges\rhino`; "open Rhino" launches Rhino with it |
| Blender 3.6+ | `blender/archhub_mcp/` | 9876 | copied to `{app}\bridges\blender`; "open Blender" launches Blender with it |

The Revit and AutoCAD sources were imported from `12.PRODUCTION/payload/sources`
(12.PRODUCTION commit 2ecb61d); their earlier history stays readable there.

## Who may call a bridge

Every bridge runs code it is sent, so every bridge checks its caller first:

- `/ping` (identity) answers any local caller that is not a browser.
- Every other route needs the header `X-ArchHub-Bridge-Token` equal to this
  install's bridge secret, compared in constant time. Otherwise: **401**.
- A request carrying `Origin` or `Sec-Fetch-Mode` (a browser) gets **403**, and
  no bridge ever sends a CORS header, so a web page can neither call a bridge
  nor read its answer.
- With no secret provisioned the bridge answers **503** to everything but
  `/ping`: it fails closed.

The secret is made once by the app (`nodelang/host_bridge_auth.py`), 32 random
bytes, and kept in the app's credential store (`app/secrets_store.py`, which on
the shipped desktop is keyring, i.e. the Windows Credential Locker, entry user
`archhub-host-bridge`). The bridges read it from there; it is never written to a
file and never sent to a non-loopback address. The Python bridges carry one
identical copy of the check (between the `ArchHub bridge caller check` markers);
the .NET add-ins link `sources/shared/BridgeAuth.cs`.

Limits: the secret is a bearer value between processes of the same Windows
user; another process of that user can read the Credential Locker too. A local
process that binds a bridge port before the host does could receive the header.
If keyring is unavailable the app keeps the secret in its DPAPI file, which the
bridges cannot read: they then refuse (503) rather than open.

## Revit add-in: build, register, remove

1. `installer/build_release.ps1` calls `installer/build_revit_bridge.ps1`, which
   builds the add-in for every Revit year installed on the build machine
   (2020: net47, 2021-2024: net48, 2025+: net8) against that year's
   `RevitAPI.dll`, and writes `bridges/revit/<year>/host-artifacts.json` plus
   `HOST_ARTIFACTS.json`. Pass `-BrokerReviewPath <review file>` with the
   independent custody review of this source; without it the manifests carry no
   activation and setup refuses them.
2. The installer copies `bridges/revit/<year>/` and `HOST_ARTIFACTS.json` into
   the install folder.
3. On first open, setup (`colleague_setup.py`, `register_revit_add_ins`) checks
   each packaged year that is also installed and registers
   `%APPDATA%\Autodesk\Revit\Addins\<year>\RevitMCP.addin` through
   `nodelang/host_broker_installation.py`. It never overwrites a different
   registration (an older ArchHub add-in is reported, not replaced), never needs
   administrator rights and never starts Revit. Restart Revit to load it.
4. Uninstall deletes only the `RevitMCP.addin` files whose assembly lies in this
   install's `bridges\revit\` folder.

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
