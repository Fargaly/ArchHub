# Running ArchHub alongside other Revit add-ins

> Founder gripe 2026-05-21: **"WE SHOULDN'T CONFLICT WITH OTHER ADDINS."**
> This doc documents the fix per AgDR-0023.

## The conflict

Revit loads every `.addin` into ONE shared .NET AppDomain. If two
add-ins reference DIFFERENT versions of the same assembly (e.g.
`Microsoft.CodeAnalysis` 4.11 vs 3.4), the second loader hits a
`FileLoadException`.

ArchHub's `RevitMCP.dll` used to compile C# scripts via in-process
Roslyn 4.11. pyRevit + Speckle ship Roslyn 3.4. Whichever loaded
second lost.

## The fix (architectural — per AgDR-0023)

RevitMCP NEVER loads Roslyn assemblies into the Revit AppDomain
anymore. Instead it spawns `csc.exe` as a subprocess to compile
each script, then `Assembly.LoadFile`s the result. Roslyn lives in
its own process. ArchHub coexists with every other Revit add-in.

## One-time setup

ArchHub needs a working `csc.exe` (the .NET C# compiler). Pick one:

### Option A — .NET Framework 4 SDK (smallest)

Already installed on most Windows machines under:

```
%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
```

If present, RevitMCP picks it up automatically.

### Option B — Visual Studio Build Tools (recommended)

Download:
[https://aka.ms/vs/17/release/vs_BuildTools.exe](https://aka.ms/vs/17/release/vs_BuildTools.exe)

In the installer pick "C# and Visual Basic build tools". This
ships a newer csc supporting modern C# language features.

### Option C — point ArchHub at any csc.exe

```
setx ARCHHUB_CSC_PATH "C:\path\to\csc.exe"
```

Restart Revit. RevitMCP probes `ARCHHUB_CSC_PATH` first.

## Verifying

Launch Revit. ArchHub's broker `/ping` returns a `compiler` field:

```bash
curl http://localhost:48884/ping
# {"service": "revit-mcp", "version": "...", "compiler": "subprocess_csc"}
```

`subprocess_csc` ✓ means the conflict-free path is active. If you
see `in_process_roslyn`, RevitMCP needs an update — open an issue
or rebuild from the .NET repo with the AgDR-0023 patch.

## Quick triage if you still see errors

| Symptom | Cause | Fix |
|---|---|---|
| `FileLoadException: Microsoft.CodeAnalysis` | RevitMCP still on the legacy in-process Roslyn path | Update RevitMCP to the AgDR-0023 build |
| `csc.exe not found` from /exec | No C# compiler installed | Install VS Build Tools (Option B above) |
| ArchHub broker shows no Revit sessions | RevitMCP add-in not loaded | Check `%APPDATA%\Autodesk\Revit\Addins\2025\` contains the ArchHub `.addin` file |

## Why we don't just "disable Speckle / pyRevit"

That's symptom patching. The founder uses Speckle + pyRevit
daily. ArchHub MUST coexist. The subprocess-csc fix
(AgDR-0023) is the structural answer — works regardless of which
other add-ins are loaded.
