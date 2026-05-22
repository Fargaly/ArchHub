---
id: AgDR-0023
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop · "don't sleep" + founder gripe "we shouldn't conflict with other add-ins"
trigger: Founder demand 2026-05-21 — Roslyn version conflict (RevitMCP 4.11 vs pyRevit/Speckle 3.4) keeps recurring; symptom patches ("disable Speckle / pyRevit addin") are unacceptable
status: superseded by AgDR-0025
category: architecture
projects: [archhub, revitmcp]
extends:
  - AgDR-0017 — M2-Python Revit-Speckle ops + IPC `/exec` route
    contract (the path that today hits the in-process Roslyn)
---

# RevitMCP Roslyn isolation — subprocess C# compilation · zero in-process Roslyn · no add-in version conflicts forever

> In the context of the founder's gripe 2026-05-21 ("WE SHOULDN'T
> CONFLICT WITH OTHER ADDINS") + the recurring Roslyn 4.11 / 3.4
> AppDomain race against pyRevit + Speckle, I decided to **lock
> the architectural fix as: ArchHub.RevitMCP NEVER loads
> Microsoft.CodeAnalysis assemblies into the Revit AppDomain**.
> Today's path POSTs a C# script to `/exec`, the add-in compiles
> in-process via Roslyn 4.11 → collides with whichever Roslyn
> version another add-in already pinned. Replace with: the add-in
> writes the C# script to a temp file, invokes `csc.exe` as a
> subprocess to compile it to a temporary assembly, then
> `Assembly.LoadFile`s the result (one-shot, isolated, no Roslyn
> in AppDomain). Same `/exec` HTTP contract — the Python side
> (`revit_speckle_ops.py` + `revit_connector.py`) doesn't change.
> Accepting: subprocess spawn adds ~200-400ms per /exec call (one
> csc + load) — acceptable for the receive_from_speckle / batch_set_parameters
> ops (already long-running); a small csc cache keys on
> hash(source) so repeated identical scripts compile once. The
> founder's tactical fix ("disable Speckle .addin") is REJECTED
> as a long-term answer — symptom not class.

## Context

The Roslyn AppDomain conflict shape:

```
Revit 2025 boot
  ↓
loads all .addin files (alphabetical or insertion order)
  ↓
First add-in to reference Microsoft.CodeAnalysis pins its version
in the SINGLE shared AppDomain.
  • pyRevit / Speckle ship Roslyn 3.4
  • ArchHub.RevitMCP needs Roslyn 4.11
  ↓
Whichever loads second + asks for the OTHER version →
`FileLoadException: Could not load file or assembly
 'Microsoft.CodeAnalysis, Version=4.11.0.0, ...'`
```

Founder ran into this REPEATEDLY (CDP screenshots 2026-05-20 +
2026-05-21). My tactical advice "disable Speckle .addin temporarily"
gets ArchHub running TODAY but is unacceptable as a long-term
posture: ArchHub coexists with pyRevit + Speckle in any
professional architect's daily setup.

Per ENGINEERING MANDATE in CLAUDE.md:
> Every problem → dive to the ROOT. No quick patches. No stitching.
> Fix the mechanism so the whole CLASS of bug cannot recur.

The CLASS of bug here: ANY .NET version conflict between add-ins
sharing one AppDomain. Today it's Roslyn 4.11 vs 3.4. Tomorrow it
could be Newtonsoft.Json or any other transitive dependency.

## Options Considered

### Fork 1 — Where to compile

| Option | Picked | Why |
|---|---|---|
| In-process Roslyn (today) | no | The CLASS of bug — any add-in version conflict breaks ArchHub |
| **Subprocess `csc.exe`** (ships with .NET SDK / Visual Studio Build Tools) | **YES** | Roslyn lives in `csc.exe`'s OWN process → ArchHub's AppDomain stays clean → no add-in version conflicts forever |
| Subprocess `dotnet-script` (3rd-party) | no | External dep · install hassle · csc.exe is already on the user's machine |
| Bundle ILMerged Roslyn DLL with renamed namespace | no | Build pipeline rabbit hole · still loads in AppDomain (renamed but present) · would break if another add-in does the same trick |
| Bundle Roslyn as private assemblies in a subdir | no | .NET assembly-resolve probing isn't reliable across all CLR versions; CodeAnalysis has internal hard-coded type references that bypass private-paths |

**Pick: subprocess csc.exe.**

### Fork 2 — Assembly loading

| Option | Picked | Why |
|---|---|---|
| `Assembly.LoadFile(path)` — separate load context per /exec call | **YES** | Each compiled script lives in its own load context; collectible; doesn't pollute the AppDomain with type tables across calls |
| `Assembly.Load(byte[])` from compiled bytes | partial | Works but byte[] stays in memory; less obvious how to evict |
| `AssemblyLoadContext.Default.LoadFromAssemblyPath` (.NET 6+) | no (Revit 2025 still targets .NET Framework 4.8) | Not available pre-.NET 5 |

**Pick: `Assembly.LoadFile` with collectible context.**

### Fork 3 — csc.exe discovery

The user might have any of:
- Visual Studio (csc at `C:\Program Files\Microsoft Visual Studio\<ver>\<edition>\MSBuild\Current\Bin\Roslyn\csc.exe`)
- .NET Framework reference assemblies (`%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` — old single-file Roslyn 1.x; usable for our purpose)
- .NET SDK (`dotnet build` driver; spawns its own compiler)

| Option | Picked | Why |
|---|---|---|
| Hard-coded path to Framework's `csc.exe` | no | Brittle across Windows versions |
| **Probe a known-path list at startup, cache the result, error honestly if none found** | **YES** | Robust + honest |
| Ship a vendored Roslyn 4.11 csc.exe with ArchHub | no | ~50 MB extra install + legal review |

**Pick: probe-and-cache.**

### Fork 4 — Caching

| Option | Picked | Why |
|---|---|---|
| Compile fresh every /exec call | no | 200-400ms × N calls for an identical script (e.g. a graph that runs the same `receive_from_speckle` op repeatedly) — wasteful |
| **Cache by `sha256(source + references + flags)` → assembly path; LRU evict** | **YES** | Identical scripts compile once + load fast on subsequent /exec calls |
| Cache by source string only | no | Doesn't capture reference changes; subtle bugs |

**Pick: sha256-keyed LRU.**

## Decision

### Architectural fix (RevitMCP repo)

Today's flow (in-process Roslyn):
```
ArchHub Python  ──HTTP /exec──>  RevitMCP add-in
                                   ↓
                                 Microsoft.CodeAnalysis (4.11) in AppDomain  ← COLLISION
                                   ↓
                                 CSharpScript.RunAsync(...)
                                   ↓
                                 result via ctx
```

New flow (subprocess csc):
```
ArchHub Python  ──HTTP /exec──>  RevitMCP add-in
                                   ↓
                                 hash = sha256(source + refs)
                                 if cached: assemblyPath = cache[hash]
                                 else:
                                   write source.cs to %TEMP%/archhub-csc-<hash>.cs
                                   spawn csc.exe → out.dll
                                   cache[hash] = out.dll
                                   ↓
                                 Assembly.LoadFile(out.dll)  ← isolated load
                                   ↓
                                 reflection-invoke entry point
                                   ↓
                                 result via ctx
```

### `csc.exe` probe order

```csharp
// One-time probe at add-in init; cached for the life of the process.
string[] _probePaths = new[] {
    Environment.GetEnvironmentVariable("ARCHHUB_CSC_PATH"),
    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                  "..", "Microsoft.NET", "Framework64",
                  "v4.0.30319", "csc.exe"),
    // VS BuildTools well-known locations:
    @"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe",
    @"C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\Roslyn\csc.exe",
    @"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\Roslyn\csc.exe",
};
// First existing wins; throw with a clear remediation if none.
```

### Cache shape

```csharp
class CompileCache {
  // Key: sha256(source + sorted ref-list + lang version + flags)
  // Value: assembly path under %TEMP%/archhub-roslyn-cache/
  // Eviction: LRU; max 64 entries.
  ConcurrentDictionary<string, string> _entries;
}
```

### Honest failure

If csc.exe is not found:
```
HTTP 503 from /exec with body:
  {
    "status": "error",
    "error_code": "csc_missing",
    "error": "Microsoft C# compiler (csc.exe) not found. ArchHub
              requires the .NET Framework 4 SDK or Visual Studio
              Build Tools. Install:
              https://aka.ms/vs/17/release/vs_BuildTools.exe
              — then restart Revit."
  }
```

ArchHub Python side (`revit_connector.py`) surfaces this as a
typed error to the user.

### Same HTTP `/exec` contract

The Python side does NOT change. `revit_speckle_ops.send_to_speckle` /
`receive_from_speckle` / `batch_set_parameters` still POST C# to
`/exec`. The architectural shift is INSIDE the .NET add-in. This
keeps the Python codebase + tests unchanged.

### Python-side support (this repo)

The .NET fix is OUT OF SCOPE for ArchHub-Python. What ships here:

1. **Pre-flight check** (`app/connectors/revit_broker.py`): when
   the broker probes a Revit session via `/ping`, it now ALSO
   reads the new `compiler` field in the response (per the
   updated RevitMCP contract: `{service: "revit-mcp", version: "X",
   compiler: "in_process_roslyn" | "subprocess_csc" | "unknown"}`).
   When `in_process_roslyn`, the connector warns the user in the
   broker discovery log that they're on the legacy path + may hit
   conflicts.

2. **Typed error surface**: when `/exec` returns the new
   `csc_missing` error code, the Revit connector translates it
   into a typed `csc_missing` OpResult that the JSX UI can surface
   with a clear install-Build-Tools prompt instead of a raw HTTP
   error.

3. **Documentation**: `docs/RUN-REVIT.md` (new) walks the founder
   through the one-time Build Tools install, references this AgDR.

## Consequences

### What ships in THIS repo

- `app/connectors/revit_broker.py` — reads the new `compiler`
  field from `/ping` + logs a deprecation warning when the value
  is `in_process_roslyn`.
- `app/connectors/revit_connector.py` — surfaces `csc_missing`
  as a typed OpResult with the install link.
- `docs/RUN-REVIT.md` — one-pager: install Build Tools, point
  ArchHub at `csc.exe` via `ARCHHUB_CSC_PATH` env var, no need to
  disable Speckle / pyRevit.
- Tests pin: deprecation warning fires when broker sees
  `compiler: in_process_roslyn`; `csc_missing` translates honestly.

### What ships in the SEPARATE RevitMCP .NET repo (NOT this commit)

- `RoslynIsolator.cs` — subprocess csc.exe wrapper + compile cache.
- `RevitEventHandler.RunCSharpScript` refactor to call the new
  wrapper instead of `Microsoft.CSharp.Scripting.CSharpScript`.
- `csc_missing` typed HTTP error.
- `/ping` response carries `compiler: "subprocess_csc"`.

### What collapses

- The recurring Roslyn 4.11 / 3.4 AppDomain conflict — the whole
  CLASS of "ArchHub conflicts with add-in X's transitive dep".
- The "disable Speckle / pyRevit before launch" workaround.
- The `FileLoadException: Could not load file or assembly
  'Microsoft.CodeAnalysis'` error path.

### What's reinforced

- ENGINEERING MANDATE — fix the CLASS, not the instance.
- ArchHub coexists with EVERY other Revit add-in by default.

### Risks

- **Compile latency.** ~200-400ms per /exec on cache miss; ~5ms on
  hit. Acceptable for receive_from_speckle / batch_set_parameters
  (already 1-2 sec operations). Mitigation: warm the cache by
  pre-compiling the 3 commonly-used scripts at add-in init.
- **Build Tools install friction.** Some founders don't have VS
  Build Tools installed. Mitigation: `RUN-REVIT.md` walks the
  one-time setup; csc.exe is ~150MB install; we can also ship
  a sidecar installer.
- **csc.exe version drift.** Older Framework csc may lack newer
  C# language features. Mitigation: detect language version
  support at probe time, fall back to C# 7.3 if 10+ unavailable.

### Tests (this repo)

| Test | What it proves |
|---|---|
| `test_revit_broker_logs_warning_on_legacy_compiler` | Broker logs deprecation when `/ping` returns `compiler: in_process_roslyn` |
| `test_revit_broker_no_warning_on_subprocess_csc` | Modern path doesn't trigger the warning |
| `test_revit_broker_handles_missing_compiler_field_back_compat` | Old RevitMCP without the `compiler` field is treated as 'unknown' (no warning, no break) |
| `test_revit_connector_csc_missing_surfaces_typed_error` | A 503 with `error_code: csc_missing` becomes a typed OpResult |

## Implementation order

1. ✓ This AgDR (done — locks the architectural fix).
2. THIS COMMIT — ArchHub Python-side support:
   - revit_broker.py `compiler` field handling + deprecation log
   - revit_connector.py `csc_missing` typed error
   - docs/RUN-REVIT.md install pointer
   - tests
3. SEPARATE .NET commit (RevitMCP repo) — Founder hands this
   AgDR to whoever maintains RevitMCP. Implement
   `RoslynIsolator.cs` + refactor RunCSharpScript per §"What
   ships in the SEPARATE RevitMCP .NET repo".

## Open forks for founder

1. **AssemblyLoadContext on Revit 2026.** When Revit 2026 ships
   targeting .NET 8, switch from `Assembly.LoadFile` to
   `AssemblyLoadContext.Unloadable` for collectible loads
   (proper GC of compiled scripts).
2. **MAXScript / DesignAutomation parallel.** Same class of
   conflict could hit 3ds Max + AutoCAD. Apply the same pattern
   to acad_speckle_ops + max_speckle_ops when those ship.
3. **Add-in-load-order config.** Revit lets us hint the load
   order via `<VendorId>.addin` attributes. Out of scope here;
   the subprocess csc fix removes the need.

## Artifacts

- This AgDR.
- Pending (this commit): `app/connectors/revit_broker.py` +
  `app/connectors/revit_connector.py` + `docs/RUN-REVIT.md` +
  test files.
- Pending (RevitMCP .NET repo): `RoslynIsolator.cs` per §
  "What ships in the SEPARATE RevitMCP .NET repo".
