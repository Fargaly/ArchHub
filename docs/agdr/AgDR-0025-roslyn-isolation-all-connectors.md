---
id: AgDR-0025
timestamp: 2026-05-21T12:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "/exec broken on Revit 2025 · same Roslyn conflict · make sure this problem doesn't happen with other connectors"
trigger: Founder pick 2026-05-21 — "Subprocess csc per AgDR-0023" + "make sure this problem doesn't happen with other connectors"
status: approved
category: architecture
projects: [archhub, revitmcp, acadmcp]
extends:
  - AgDR-0023 — RevitMCP Roslyn isolation via subprocess csc (this
    AgDR's predecessor; same architectural fix, broader scope)
  - AgDR-0017 — M2-Python Revit-Speckle ops + IPC `/exec` route
supersedes:
  - AgDR-0023 (status: superseded by AgDR-0025; AgDR-0023's Revit
    scope is folded in here + extended to acad_mcp + every
    future .NET connector that compiles C# at runtime)
---

# Subprocess csc isolation for EVERY .NET connector — Revit · AutoCAD · (and any future net-host that ships a `/exec` route)

> Context: the Roslyn AppDomain conflict that AgDR-0023 fixed for
> RevitMCP RE-SURFACED on Revit 2025 (net8) because pyRevit /
> Speckle load Roslyn 3.x FIRST into the shared AppDomain, then
> RevitMCP's `CSharpScript.RunAsync` asks for 4.11 → FileLoadException.
> Founder demand 2026-05-21: fix this for Revit AND every other
> connector that does in-process Roslyn — AcadMCP today, more
> tomorrow. AgDR-0023 picked subprocess-csc; this AgDR LOCKS that
> choice + broadens scope to all .NET connectors + ships the
> implementation as ONE shared `ScriptCompiler.cs` linked into
> every csproj.

## Constraints (signed)

1. **Zero in-process Roslyn anywhere.** Microsoft.CodeAnalysis*
   never enters any .NET connector's AppDomain.
2. **Subprocess `csc.exe`** compiles user C# to a temp DLL per
   /exec call (sha256-keyed cache so identical scripts compile
   once).
3. **`Assembly.LoadFile`** loads the compiled DLL; reflection-invoke
   the entry point with the per-host `ScriptContext`.
4. **One shared `ScriptCompiler.cs`** lives at
   `payload/sources/shared/ScriptCompiler.cs` and is `<Link>`-ed
   into every connector csproj. Per-connector glue (ScriptContext
   type · API DLL references) stays in the connector.
5. **`/ping` exposes `compiler: "subprocess_csc"`** so the broker
   logs the modern path + warns on legacy connectors.
6. **Honest failure** — `csc_missing` typed HTTP error with install
   pointer if no csc.exe is found.
7. **Same `/exec` HTTP contract** — Python side unchanged
   (`revit_speckle_ops.py`, `acad_speckle_ops.py`, etc.).
8. **Founder's "WE SHOULDN'T CONFLICT WITH OTHER ADDINS" mandate**
   is now class-of-bug closed, not whack-a-mole on individual
   conflicts.

## Decision

### Architectural shape (same as AgDR-0023, broader scope)

```
ArchHub Python  ──HTTP /exec──>  <Connector>MCP add-in
                                   ↓
                                 ScriptCompiler.CompileAndRun(code, ctx)
                                   ↓
                                 hash = sha256(code + refs + lang)
                                 if cached: assemblyPath = cache[hash]
                                 else:
                                   write source.cs to %TEMP%/archhub-csc-cache/<hash>.cs
                                   spawn csc.exe → out.dll
                                   cache[hash] = out.dll
                                   ↓
                                 Assembly.LoadFile(out.dll)
                                   ↓
                                 reflection-invoke Generated_<hash>.Entry.Run(ctx)
                                   ↓
                                 result via ctx
```

### csc.exe probe order (unchanged from AgDR-0023)

1. `ARCHHUB_CSC_PATH` env var
2. `%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`
3. VS BuildTools / Community / Enterprise well-known paths

First existing wins. Honest `csc_missing` error if none.

### Generated wrapper template

```csharp
namespace ArchHub.Generated_<hash> {
  using System;
  using System.Collections.Generic;
  using System.Linq;
  using <HostNamespace.DB>;
  using <HostNamespace.UI>;
  public static class Entry {
    public static object Run(<ScriptContextType> ctx) {
      var UIApp = ctx.UIApp;
      var UIDoc = ctx.UIDoc;
      var Doc   = ctx.Doc;
      object result = null;
      // -- user code start --
      <USER_CODE>
      // -- user code end --
      ctx.result = result;
      return result;
    }
  }
}
```

User scripts that today do `result = X;` keep working because
`result` is a local in the wrapper that's piped to `ctx.result`
after the body.

### Cache shape

`%TEMP%/archhub-csc-cache/`
- Key: `sha256(source + sorted-refs + langVersion + frameworkTarget)`
- Value: file at `<hash>.dll`
- Eviction: opportunistic — delete entries older than 7 days at startup; bounded to 64 entries (LRU by mtime).
- Survives Revit restarts → repeat /exec calls in next session compile-once.

### Cross-connector reuse

`payload/sources/shared/ScriptCompiler.cs` is the canonical impl.
Each connector csproj:
```xml
<ItemGroup>
  <Compile Include="..\shared\ScriptCompiler.cs"
           Link="ScriptCompiler.cs"/>
</ItemGroup>
```

Connector-specific glue (which references to pass, which
ScriptContext type) lives in the per-connector RevitEventHandler /
AcadCommandRunner.

## What ships in THIS commit (.NET source)

- `payload/sources/shared/ScriptCompiler.cs` — new file. The whole
  csc subprocess + cache + Assembly.LoadFile + reflection-invoke
  pipeline. Generic over `TContext` so each connector passes its
  own ScriptContext type.
- `payload/sources/revit_mcp/RevitMCP.csproj`:
  - DROP `<PackageReference Include="Microsoft.CodeAnalysis..." />`
    (no more in-process Roslyn).
  - ADD `<Compile Include="..\shared\ScriptCompiler.cs" Link="..." />`.
- `payload/sources/revit_mcp/RevitEventHandler.cs`:
  - DROP `using Microsoft.CodeAnalysis.*`.
  - REFACTOR `RunCSharpScript` to call
    `ScriptCompiler.CompileAndRun(code, ctx, refs)`.
- `payload/sources/revit_mcp/RevitMCPApp.cs`:
  - `/ping` response gains `"compiler":"subprocess_csc"`.
- Same triplet for `acad_mcp` (paralleled).
- Tests pin: ScriptCompiler probe order; cache hit returns
  identical path; csc_missing surfaces typed error.

## What does NOT ship (out of scope here)

- `app/connectors/revit_broker.py` `compiler:` field handling +
  deprecation warning — already shipped in AgDR-0023.
- `app/connectors/revit_connector.py` `csc_missing` typed surface
  — already shipped in AgDR-0023.
- `docs/RUN-REVIT.md` — already shipped in AgDR-0023.
- Lag fix — separate AgDR-0026 (queued).

## Acceptance

1. Revit 2025 boots WITH pyRevit + Speckle + RevitMCP loaded.
2. /ping returns `compiler: "subprocess_csc"`.
3. POST `/exec` with `{ code: "result = new
   FilteredElementCollector(Doc).OfClass(typeof(Wall)).Count();" }`
   returns `{ "status":"ok","result":<n> }`.
4. NO FileLoadException for Microsoft.CodeAnalysis ever again,
   regardless of which add-in loaded first.
5. Same /exec works on AutoCAD with `result = doc.Layers.Count;`.
6. JSX Babel-parse clean. Python tests green. Founder confirms via
   CDP demo.

## Risks (carry-over from AgDR-0023)

- **csc latency.** ~200-400ms first call; ~5ms cached. Acceptable.
- **Build Tools install friction.** `RUN-REVIT.md` covers it.
- **C# language version drift.** Framework csc is C# 7.3; modern
  scripts using C# 10+ features (records, etc.) need the VS
  BuildTools path. ScriptCompiler logs which csc it picked.

## Artifacts

- This AgDR.
- Pending (this commit): `payload/sources/shared/ScriptCompiler.cs`
  + the per-connector edits listed above.
- AgDR-0023 marked superseded by this one.
