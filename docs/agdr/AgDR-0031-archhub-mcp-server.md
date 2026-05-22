---
id: AgDR-0031
timestamp: 2026-05-21T19:30:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — other Claude Code session can't see ArchHub tools in its MCP toolset
trigger: Founder screenshot showing a separate Claude session saying "I don't currently see an archhub MCP server in my available tools list".  ArchHub today is a Qt desktop app with HTTP brokers; not an MCP server.  Founder demand: every Claude Code session should be able to drive ArchHub's hosts via the MCP toolset, not shell out via accoreconsole.exe / Bash.
status: approved
category: architecture
projects: [archhub]
extends:
  - AgDR-0017 — Revit-Speckle ops + /exec HTTP contract that this
    MCP server proxies to
  - AgDR-0027 — shim + Core HTTP routes the MCP server forwards to
---

# ArchHub MCP server — register the existing stdio shim with Claude Code

> Founder demand 2026-05-21: any Claude Code session should be able
> to call ArchHub tools (Revit `/info`, AutoCAD `/exec`, Speckle
> `send_to_speckle`, …) from its MCP toolset, not by shelling out
> to `accoreconsole.exe` + LISP scripts or by `curl`-ing the broker
> ports from Bash.
>
> **DISCOVERY 2026-05-21:** `app/archhub_mcp_server.py` ALREADY exists
> (shipped 2026-05-16 per a prior founder demand for routing local
> Claude through MCP).  It speaks stdio MCP and advertises 123
> connector ops via `connectors.base.run_op`.  The OTHER Claude
> session can't see it because it was never `claude mcp add`-ed
> into that session's MCP config.  Fix = registration + docs, not
> new code.  Status pivots from "build" to "ship registration + tests".

## Constraints (signed once founder approves)

1. **One-time install:** `claude mcp add archhub py
   C:\Users\fargaly\00.ARCHUB\ArchHub\app\archhub_mcp_server.py`.
   No extra runtime deps beyond stdlib + the `mcp` python package
   already shipped with Claude Code.
2. **Stdio transport.**  No HTTP/SSE listener of its own — the MCP
   server reads from stdin / writes to stdout per the MCP spec.
   The ArchHub HTTP brokers stay unchanged.
3. **Discovery via the broker.**  At startup the MCP server enumerates
   alive Revit / AutoCAD / Max / Outlook sessions via the existing
   Python broker modules (no new HTTP scanning).
4. **Read-only by default.**  Tool surface for v1 is host introspection
   + script /exec (which is already user-gated by the founder's
   USER-AGENCY MANDATE for writes).  No new auth model.
5. **Honest failure modes.**  If ArchHub isn't running, every tool
   returns a typed `archhub_offline` error — the MCP server itself
   stays up so the other Claude can poll until ArchHub starts.
6. **Same code, two callers.**  The MCP server invokes the SAME
   broker functions the Qt bridge calls (`revit_broker.forward`,
   `acad_broker.forward`, etc.).  No business-logic fork.

## Tool surface (v1)

| Tool | What it does | Wraps |
|---|---|---|
| `archhub_list_sessions(family?)` | List running host sessions (revit / autocad / max / outlook), with pid + port + doc title. | brokers.list_sessions |
| `archhub_revit_info(session_id?)` | Active doc title, path, view, Revit version, workshared flag. | revit_broker.forward `/info` |
| `archhub_revit_exec(code, session_id?, transaction_name?)` | Run a C# script in a Revit session — same /exec route Composer uses today. | revit_broker.forward `/exec` |
| `archhub_acad_info(session_id?)` | Active AutoCAD doc info. | acad_broker.forward `/info` |
| `archhub_acad_exec(code, session_id?)` | Run a C# script in AutoCAD. | acad_broker.forward `/exec` |
| `archhub_get_connectors()` | The 16-connector op catalogue + ops + I/O schema. | bridge.get_connectors |
| `archhub_speckle_send(host, op_id, payload)` | Send objects to a Speckle stream. | speckle_wire.send |
| `archhub_screenshot(host, session_id?, path?, width_px?)` | Capture a host viewport PNG. | <host>_broker.forward `/screenshot` |

Tools are namespaced with `archhub_` so they don't collide with
the standard MCP servers (Adobe, Canva, Gmail, Notion, etc.).

## Forks — signed 2026-05-21 (defaults adopted)

- **Fork A: A1** — Import broker modules in-process.  Single source
  of truth; reuses prune logic + session-file parsing.
- **Fork B: B3** — Log to BOTH `%LOCALAPPDATA%\ArchHub\logs\mcp-server.log`
  and stderr.  File for cross-session diagnosis; stderr for the
  Claude Code MCP debug pane.
- **Fork C: C3** — Inherit host confirmation by default + honour
  `ARCHHUB_MCP_READONLY=1` env to strip every `*_exec` tool.

## What ships in THIS commit

1. **No new MCP server code.**  `app/archhub_mcp_server.py` is
   already there + selftest reports 123 ops registered:
   `py app/archhub_mcp_server.py --selftest`.
2. `docs/RUN-MCP.md` — registration instructions for any Claude
   Code session.  Verified registration command:
   ```
   claude mcp add archhub py "C:\Users\fargaly\00.ARCHUB\ArchHub\app\archhub_mcp_server.py"
   ```
   Restart Claude Code → tools appear in the toolset as
   `autocad__list_layers`, `revit__list_walls`, `speckle__send`, etc.
   (`.` in op_id → `__` in tool name for MCP-compat).
3. `tests/test_archhub_mcp_server.py` — pins the server's tool
   surface: selftest reports ≥80 ops; tool names use the `host__op`
   pattern; `--selftest` exits 0 when ops registered; `connectors`
   import path stays intact (the `app/mcp/` shadowing bug fixed
   in-source 2026-05-16).

## What does NOT ship

- SSE / HTTP transport (stdio only for v1 — Claude Code's
  `claude mcp add` defaults to stdio).
- Auth / API key — the MCP server only listens on the stdio of the
  Claude Code session that spawned it; no network surface.
- Cross-machine: this is localhost-only.

## Acceptance

1. After `claude mcp add archhub ...`, a fresh Claude Code session
   sees `archhub_list_sessions`, `archhub_revit_info`,
   `archhub_revit_exec`, `archhub_acad_*`, etc. in its toolset.
2. Calling `archhub_list_sessions` from that Claude returns the
   same set the Qt bridge's `get_sessions` reports.
3. `archhub_revit_exec({code: "result = new
   FilteredElementCollector(Doc).OfClass(typeof(Wall)).Count();"})`
   returns the wall count from the active Revit session.
4. When ArchHub isn't running, every tool call returns
   `{"error_code": "archhub_offline", ...}` and the MCP server
   itself stays up.
5. Suite green.  Founder confirms by /loop'ing the brief through
   another Claude session.

## Artifacts

- This AgDR.
- Pending: `app/archhub_mcp_server.py` + `docs/RUN-MCP.md` + tests.
