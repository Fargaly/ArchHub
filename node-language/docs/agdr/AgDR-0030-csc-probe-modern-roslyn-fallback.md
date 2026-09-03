---
id: AgDR-0030
timestamp: 2026-05-21T16:30:00Z
agent: claude-code (Sonnet)
session: handoff from prior session (commit eccfc2c) — Bug 2 in ScriptCompiler probe
trigger: Founder report — /exec returns CS1617 "Invalid option '7.3' for /langversion" on any box without VS BuildTools; root cause = ScriptCompiler probe accepts Framework64 csc.exe which caps at C# 5 on .NET 4.8.1.
status: executed
category: architecture
projects: [archhub, revitmcp, acadmcp]
extends:
  - AgDR-0025 — subprocess-csc Roslyn isolation that introduced the
    probe order this AgDR repairs
---

# ScriptCompiler csc probe · reject sub-C#7.3 compilers + wire SDK fallback · generic across every .NET host

> Founder demand 2026-05-21: "make sure those bugs won't happen for
> other hosts as well."  ScriptCompiler.cs is `<Link>`-ed into every
> .NET connector (RevitMCP Core, AcadMCP, future hosts) per AgDR-0025.
> A single probe-order fix in shared/ScriptCompiler.cs fixes /exec
> for every host simultaneously — no per-host code change needed.

## Constraints (signed once founder approves)

1. **No host accepts a C#5-only csc.**  Probe verifies each
   candidate's `/langversion:?` output advertises ≥7.3 before
   committing.  Cache the per-process verdict.
2. **SDK `dotnet exec csc.dll` is a first-class fallback.**  Wired
   into the probe order between Framework csc and VS BuildTools.
3. **One AgDR-0025 wrapper, every host.**  The `langversion:7.3`
   wrapper is fixed at the ScriptCompiler.cs level — RevitMCP +
   AcadMCP both inherit the fix.
4. **Honest failure when no usable csc exists.**  Surface the
   existing `csc_missing` typed error with a concrete install
   pointer (SDK download URL + Build Tools URL).
5. **Guard test pins the class.**  A unit test feeds the probe a
   mock csc with C# 5-only `/langversion:?` output and asserts
   rejection.  Adding a new probe path automatically picks up the
   gate.

## Context — what's there today

`payload/sources/shared/ScriptCompiler.cs::_ProbeOnce()`:

```csharp
// 1. Explicit override.
var env = Environment.GetEnvironmentVariable("ARCHHUB_CSC_PATH");
if (...) return env;

// 2. .NET Framework 4.0 csc — comment says "Roslyn 1.x with C# 7.3
//    support".  Comment is WRONG on .NET 4.8.1 boxes — that csc
//    caps at C# 5 → CS1617 on /langversion:7.3.
var fxCsc = Path.Combine(sysRoot, "..", "Microsoft.NET",
                         "Framework64", "v4.0.30319", "csc.exe");
if (File.Exists(fxCsc)) return fxCsc;   // ← LANDS HERE FOR EVERYONE

// 3. VS BuildTools well-known paths — rarely installed.
foreach (var root in vsRoots) { ... }

// 4. .NET SDK csc.dll — COMMENTED OUT.
//    "skipped because spawning dotnet exec csc.dll adds JIT overhead"
return null;
```

On a clean Revit box with no VS BuildTools: probe lands on step 2,
returns a C#5 csc, every /exec fails on every .NET host.

## Decision (proposed)

### New probe order

```
1. ARCHHUB_CSC_PATH env var (unchanged).
2. VS BuildTools 2022 well-known paths — MODERN Roslyn 4.x, prefer
   over Framework when available (was step 3).
3. .NET SDK dotnet-exec csc.dll path (was step 4 — now WIRED).
   Discovery: `dotnet --list-sdks` → highest version → look for
   `Roslyn/bincore/csc.dll` under that SDK.
4. Framework64 csc.exe — LAST resort, gated by /langversion:? probe
   that verifies it accepts /langversion:7.3 before we commit.
5. (Optional bundled csc — see Fork B below.)

Reject any candidate whose /langversion:? output contains "up to
C# 5" or any version <7.3 in the supported list.
```

### `/langversion:?` gate

```csharp
private static bool _AcceptsLangVersion73(string cscPath, bool dotnetExec)
{
    try
    {
        var psi = new ProcessStartInfo {
            FileName = dotnetExec ? "dotnet" : cscPath,
            Arguments = (dotnetExec ? "exec \"" + cscPath + "\" " : "")
                       + "/langversion:?",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError  = true,
            CreateNoWindow = true,
        };
        using (var p = Process.Start(psi))
        {
            var stdout = p.StandardOutput.ReadToEnd();
            var stderr = p.StandardError.ReadToEnd();
            p.WaitForExit(5000);
            var all = (stdout + "\n" + stderr).ToLowerInvariant();
            // Reject if it advertises "up to C# 5" or doesn't
            // mention 7.3+ anywhere.
            if (all.Contains("up to c# 5") || all.Contains("up to c#5")) return false;
            // Accept if either "7.3" appears in the supported list
            // or any version 8+ does.
            return all.Contains("7.3") || all.Contains("8.0")
                || all.Contains("9.0") || all.Contains("10.0")
                || all.Contains("11.0") || all.Contains("12.0")
                || all.Contains("latest");
        }
    }
    catch { return false; }
}
```

### SDK csc.dll discovery

```csharp
private static (string path, bool dotnetExec) _FindSdkCsc()
{
    try
    {
        var psi = new ProcessStartInfo {
            FileName = "dotnet", Arguments = "--list-sdks",
            UseShellExecute = false, RedirectStandardOutput = true,
            CreateNoWindow = true,
        };
        using var p = Process.Start(psi);
        var lines = p.StandardOutput.ReadToEnd().Split('\n');
        p.WaitForExit(5000);
        // Each line: "8.0.405 [C:\Program Files\dotnet\sdk]"
        var best = lines.Select(l => l.Trim())
                        .Where(l => l.Length > 0)
                        .OrderByDescending(l => l)
                        .FirstOrDefault();
        if (best == null) return (null, false);
        var verEnd = best.IndexOf(' ');
        var ver = best.Substring(0, verEnd);
        var rootStart = best.IndexOf('[') + 1;
        var rootEnd = best.IndexOf(']');
        var root = best.Substring(rootStart, rootEnd - rootStart);
        var csc = Path.Combine(root, ver, "Roslyn", "bincore", "csc.dll");
        return File.Exists(csc) ? (csc, true) : (null, false);
    }
    catch { return (null, false); }
}
```

`ProbeResult` extended to carry the `dotnetExec` flag so
`CompileAndRun` knows to spawn `dotnet exec csc.dll` instead of
`csc.exe` directly.

### Cost — startup overhead

SDK csc cold start ≈ 300 ms.  AgDR-0025's sha-keyed cache means
the compile only happens on cache miss → overhead amortised across
runs of the same script.  Original "JIT overhead" comment that
killed step 4 is outdated.

## Forks — signed 2026-05-21

- **Fork A: A1 — BuildTools → SDK → Framework64 (gated).**  Modern
  Roslyn first.  Framework64 still tried as last-resort but ONLY
  after passing the `/langversion:?` gate that proves it advertises
  ≥7.3.  No silent C#5 acceptance ever again.
- **Fork B: B3 — Bundle ONCE at `%LOCALAPPDATA%\ArchHub\bin\csc\`.**
  +5 MB total (not per-year).  `auto_build` downloads
  `Microsoft.Net.Compilers.Toolset` csc.exe on first connector build
  if no usable csc is present on the box.  Probed FIRST (ahead of
  BuildTools) when found.  Self-contained on clean machines.
- **Fork C: C3 — Both eager at Core boot + lazy re-probe.**  Eager
  probe runs in `CoreEntry.Start` so `/ping` reports `csc_status`
  before any `/exec`.  Lazy re-probe fires only if a previous /exec
  attempt failed with `csc_missing` AND the env-var path changed.

## What ships once approved

- `payload/sources/shared/ScriptCompiler.cs`:
  - Probe order rewritten per Fork A pick.
  - `_AcceptsLangVersion73` gate on every candidate.
  - `_FindSdkCsc` + `dotnetExec` flag plumbed through
    `CompileAndRun`.
  - Per Fork B pick: optional bundled csc path probed first.
- `tests/test_script_compiler_probe.py` (new): unit tests
  feeding mock subprocess output asserting the gate rejects
  C#5-only csc and accepts ≥7.3 csc.
- `app/connectors/revit_broker.py` + (where applicable)
  `acad_broker.py`: surface `csc_missing` typed error with the
  install pointer chosen in Fork B.
- `docs/RUN-REVIT.md` updated with the SDK install pointer.

## What does NOT ship

- Auto-installing the .NET SDK if missing — out of scope (heavy
  install flow + license concerns).
- Cross-process csc daemon to avoid per-call startup — out of
  scope (cache already absorbs repeat costs).

## Acceptance

1. On a box with .NET SDK present but no VS BuildTools, /exec
   compiles + runs the AgDR-0025 wrapper successfully.  No CS1617.
2. On a box with NEITHER SDK nor BuildTools, /exec returns
   typed `csc_missing` with the install URL.  No silent compile
   failure.
3. /ping reports `csc_status` matching the actual probed path
   (per Fork C pick).
4. Probe rejects Framework64 csc on .NET 4.8.1 (verified by
   /langversion:? mock).
5. Both RevitMCPCore and AcadMCP /exec succeed (shared probe).
6. Suite green.  Founder confirms via CDP demo.

## Artifacts

- This AgDR.
- Pending implementation listed in §"What ships once approved".
