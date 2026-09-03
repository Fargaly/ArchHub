# ArchHub Rhino bridge

Live HTTP bridge that lets ArchHub talk to a running Rhino session
(Rhino 7+ with embedded Python 3, or Rhino 8 native CPython).

## Install

1. Open Rhino.
2. Type `_-RunPythonScript` at the command line.
3. Browse to this file (`archhub_mcp.py`) and select it.
4. Rhino's command line should print:
   ```
   [ArchHub] Rhino MCP bridge listening on 127.0.0.1:9879
   ```
5. ArchHub auto-detects the bridge on its next probe (host pill turns
   green within ~6 s).

To auto-load on every Rhino start: copy this file into
`%APPDATA%\McNeel\Rhinoceros\<version>\scripts\` and add a line to
your startup Python script (or use an alias) calling
`_-RunPythonScript archhub_mcp.py`.

## Port

Default `9879`. Override with the `ARCHHUB_RHINO_PORT` env var before
launching Rhino.

## Tools exposed

| ArchHub tool | Rhino endpoint | Purpose |
|---|---|---|
| `rhino_ping`            | `GET /ping`        | Health check |
| `rhino_info`            | `GET /info`        | Doc + layer + object counts |
| `rhino_execute_python`  | `POST /execute`    | Run Python in Rhino's context |
| `rhino_screenshot`      | `POST /screenshot` | Capture active viewport |

`execute_python` defaults to **ask** in AI Behaviour — Rhino's
`rhinoscriptsyntax` (`rs`) and full .NET surface are available, so a
runaway script can stamp a real document. Flip to **allow** in
Settings → AI Behaviour → Rhino once you trust the workflow.

## Stop

Type at Rhino's command line:
```
_-RunPythonScript "import archhub_mcp; archhub_mcp.stop()"
```
Or just close Rhino — the bridge thread is a daemon and dies with the
process.
