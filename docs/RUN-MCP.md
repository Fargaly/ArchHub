# Run the ArchHub MCP server in Claude Code

> AgDR-0031.  The ArchHub MCP server already lives at
> `app/archhub_mcp_server.py` — it just needs to be registered into
> each Claude Code session that wants to drive ArchHub tools.

## One-time registration

Open a terminal at the repo root and run:

```powershell
claude mcp add archhub py "C:\Users\fargaly\00.ARCHUB\ArchHub\app\archhub_mcp_server.py"
```

Restart Claude Code so it picks up the new MCP entry.  Verify with:

```
/mcp
```

You should see `archhub` listed alongside the standard servers
(Adobe, Canva, Gmail, Notion, …).

## What tools appear

123+ connector ops are exposed as MCP tools, namespaced by host.
The op_id's `.` is replaced with `__` because MCP tool names can't
contain dots:

| ArchHub op id              | MCP tool name                  |
|---|---|
| `revit.list_walls`         | `revit__list_walls`            |
| `revit.run_csharp`         | `revit__run_csharp`            |
| `autocad.list_layers`      | `autocad__list_layers`         |
| `autocad.run_command`      | `autocad__run_command`         |
| `speckle.send`             | `speckle__send`                |
| `excel.read_range`         | `excel__read_range`            |
| `outlook.search_inbox`     | `outlook__search_inbox`        |

Destructive ops (anything that mutates the host) carry
`[DESTRUCTIVE — mutates the host]` in their description.

## Smoke test (no Claude Code needed)

```powershell
py "C:\Users\fargaly\00.ARCHUB\ArchHub\app\archhub_mcp_server.py" --selftest
```

Lists the first 12 ops + total count.  Should print
`archhub-mcp: 123 connector ops` (or close to it).

## When ArchHub isn't running

Tool calls return `ok: false` with a typed error explaining which
host broker is unreachable.  The MCP server itself stays up so the
calling session can retry once you launch ArchHub.

## Read-only mode

Set `ARCHHUB_MCP_READONLY=1` in the environment before
`claude mcp add` (or in your settings) to strip every `*_exec` /
destructive tool from the toolset.  Useful when sharing a session
with a less-trusted context.

## Uninstall

```powershell
claude mcp remove archhub
```

## Troubleshooting

- **`/mcp` doesn't show `archhub`.**  Re-run `claude mcp add ...`,
  then restart Claude Code completely (close all windows).
- **"No module named 'mcp.server'".**  The script auto-shadows the
  ArchHub-local `app/mcp/` directory; if you still see this error,
  your `py` launcher points at a Python without the MCP SDK
  installed.  Install with `py -m pip install mcp`.
- **`archhub_offline` on every call.**  Launch ArchHub first
  (`Run.bat` at the repo root).  The MCP server proxies into the
  broker modules in-process; if no broker is reachable it returns
  the offline error.
