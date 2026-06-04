---
id: AgDR-0051
timestamp: 2026-06-01T00:00:00Z
agent: claude-code (Opus)
session: founder gripe 2026-06-01 — list_levels + Revit structured tools fail with CS0012 "add a reference to System.Runtime"; AutoCAD broker dead. Founder said "fix them" re the broker .cs (= sign-off, ARCHHUB_ALLOW_CS_EDIT). Live Revit PID 96076 (P-679 Missoni) + live AutoCAD PID 14556 (A-200) must NOT be closed.
status: executed
category: architecture
projects: [archhub, revitmcp, acadmcp]
extends:
  - AgDR-0025 — subprocess-csc Roslyn isolation. The reference list this
    AgDR augments is the AgDR-0025 /reference: contract.
  - AgDR-0031 — runtime-built reference list from
    AppDomain.CurrentDomain.GetAssemblies(). This AgDR closes the
    cold-start hole in that snapshot (lazy BCL facades absent on first
    /exec).
  - AgDR-0037 — net8 host viability (BCL refs Fix 3.A, response file
    Fix 3.B, ALC-aware load Fix 3.C). This AgDR is the cold-start
    completion of Fix 3.A: 3.A made the WARM domain list complete; the
    lazy facades can still be missing COLD.
---

# ScriptCompiler — guarantee BCL forwarder facades on a cold first /exec (CS0012 root)

> Founder, 2026-06-01: "fix them" — re the broker `.cs`. `list_levels`
> and the Revit structured tools return
> `CS0012: ... add a reference to assembly 'System.Runtime,
> Version=8.0.0.0 ...'` on the first /exec after a cold Core; the
> AutoCAD broker is dead. This AgDR records the ADDITIVE reference fix
> shipped to the SHARED compiler, the incident-safety reasoning behind
> keeping it surgical, and the AutoCAD finding (operational, not code).

## Constraints (locked)

1. **Additive + surgical only.** `payload/sources/**/*.cs` are broker
   CONTRACT SURFACES. On 2026-05-25 an agent damaged them (port
   48885→48887, NopFP injection) and the change was reverted. This fix
   ADDS references to the runtime-compilation list and NOTHING else —
   no port change, no transaction change, no entry-point change, no
   load-path change. Verified by `git diff` (additive hunks + 2
   `references`→`refs` substitutions that strictly WIDEN the ref set).
2. **No host restart.** Live Revit PID 96076 (P-679 Missoni) and live
   AutoCAD PID 14556 (A-200) are not closed. The Revit deploy path is
   AgDR-0027 hot-reload (`/reload` swaps the collectible ALC; the
   listener stays up; the document is untouched). The AutoCAD deploy
   path is a NETLOAD into the running session (does not modify the
   drawing) — flagged, not forced.
3. **One fix per class — no per-host duplication.** The fix lives in
   `payload/sources/shared/ScriptCompiler.cs::CompileAndRun`, the layer
   that assembles the final `/reference:` list. RevitMCP and AcadMCP
   BOTH inherit it via `<Compile Include="..\shared\ScriptCompiler.cs"
   Link=...>` (AgDR-0025 contract). The two most-sensitive per-connector
   contract files (`RevitMCPCore.cs`, `AcadMCPApp.cs`) are NOT touched.

## Context — what breaks, and why it's a cold-start hole

### The reported symptom — CS0012 on System.Runtime

`/exec` of any script that touches a forwarded BCL type (LINQ
`IEnumerable<>`, `System.Object` in a generic, collections) fails at
COMPILE with:

```
CS0012: The type 'IEnumerable<>' / 'Object' is defined in an assembly
that is not referenced. You must add a reference to assembly
'System.Runtime, Version=8.0.0.0, Culture=neutral,
PublicKeyToken=b03f5f7f11d50a3a'.
```

`list_levels` and the Revit structured tools all run LINQ-shaped /exec
scripts, so they all hit this. Reproduced LIVE on Revit PID 96076 via
the broker on :48884 (a `.Any(...)` probe returned exactly this CS0012).

### Root cause — lazy facades absent from the GetAssemblies() snapshot

The .NET reference-assembly model requires the BCL **type-forwarder
facades** (`System.Runtime.dll`, `netstandard.dll`, `mscorlib.dll`) to
be in csc's `/reference:` list — hundreds of BCL types forward to them.
`System.Runtime.dll` is a 43 KB pure facade (vs CoreLib's 13 MB) that
the CLR loads **lazily**, on first touch of a forwarded type.

AgDR-0031 builds the ref list from
`AppDomain.CurrentDomain.GetAssemblies()` — which returns only the
assemblies ALREADY LOADED at the instant it is sampled. On a **cold**
first /exec (before any forwarded type has been touched in the Core
ALC), `System.Runtime` is absent from the enumeration → absent from
`/reference:` → CS0012. AgDR-0037 Fix 3.A made the WARM list complete;
it could not make the COLD list complete because the facade isn't
loaded yet.

Deterministic bench reproduction (`_alcrepro/cs0012.ps1`, .NET 8.0.11 +
SDK-10 Roslyn): a ref list of the eagerly-loaded impl assemblies
(CoreLib, System.Linq, System.Collections, …) WITHOUT the facades →
`CS0012 System.Runtime`. Adding the facades the fix resolves → COMPILE
OK.

### Downstream blocker (NOT in scope for this AgDR's reference fix)

With CS0012 cleared, the LIVE Revit then surfaces a SEPARATE failure at
the ALC-load stage (`ScriptCompiler.cs` lines ~509-514):
`FileLoadException 0x80131515: Could not load file or assembly
'RevitMCPCore, Version=1.0.0.0 ...'. Operation is not supported.` —
reproduced live for even `result = 42;` (every generated DLL references
the Core assembly via the `Run(ScriptContext)` signature). This is the
AgDR-0037 Fix 3.C site. The CURRENT source already CONTAINS Fix 3.C
(`coreAlc.LoadFromAssemblyPath`), and a faithful standalone .NET 8
collectible-ALC repro (`_alcrepro/repro.ps1`, 3 variants incl. a stray
different-bytes `RevitMCPCore.dll` in the resolve dir) loads + invokes
CLEAN. So the live FileLoadException is **deployed-binary / runtime-state
drift** (the running Core predates Fix 3.C, or a poisoned
`%TEMP%\archhub-csc-cache`), not a source defect, and its fix is a
rebuild + hot-reload — NOT a reference-list change. Fixing the load
stage would touch load logic (outside this AgDR's "reference-assembly
logic" scope) and is therefore deployed via reload, not re-coded here.

## Decision (executed)

Augment the `/reference:` list inside `ScriptCompiler.CompileAndRun`
with the BCL forwarder facades, resolved BY FILE from the runtime
directory of `typeof(object).Assembly` — so they are present regardless
of lazy-load order. Purely additive.

### Fix — `ScriptCompiler.cs::CompileAndRun` (+ `_BclFacadeRefs` helper)

```csharp
// AgDR-0051 — guarantee the BCL type-forwarder FACADES are in the
// /reference: list on a COLD first /exec. ADDITIVE ONLY: appends to the
// caller's list; the distinct/File.Exists filter de-dupes against the
// host's own GetAssemblies() entries. Touches no port / transaction /
// entry-point / load path.
var refs = references;
var facades = _BclFacadeRefs();
if (facades.Count > 0)
{
    var merged = new List<string>(references);
    merged.AddRange(facades);
    refs = merged.Where(File.Exists)
                 .Distinct(StringComparer.OrdinalIgnoreCase)
                 .ToList();
}
// ...Hash(... refs ...) and the /reference: response-file loop now
// iterate `refs` (a superset of `references`).
```

`_BclFacadeRefs()` resolves, from `Path.GetDirectoryName(typeof(object)
.Assembly.Location)`: `System.Runtime`, `netstandard`, `mscorlib`,
`System.Collections`, `System.Linq`, `System.Linq.Expressions`,
`System.Runtime.Extensions`, `System.Runtime.InteropServices`,
`System.Threading.Tasks`, `System.ObjectModel` — each gated on
`File.Exists`. It deliberately does **NOT** include
`System.Private.CoreLib.dll` (always `typeof(object).Assembly`, already
in the host's `GetAssemblies()` list; referencing it ALONGSIDE the
facades can confuse csc about where `System.Object` lives → CS0518 —
confirmed on the bench).

Backward compatibility: on net48 the facade files don't all exist in
that directory, so `_BclFacadeRefs()` returns the subset present (or
empty) and the caller's list is unchanged in practice — the net48
single-mscorlib BCL view AgDR-0037 relies on is preserved. The
response-file path (AgDR-0037 Fix 3.B) absorbs the few extra refs, so
no 32 K command-line risk.

### Build verification (in-repo, this session)

dotnet SDK 10.0.100-rc.1 present. All three connector csprojs build
clean against the changed shared file:

* `RevitMCPCore.csproj` (net8, local Revit 2025 API) → **EXIT 0, 0 errors**.
* `RevitMCP.csproj` shim (net8) → **EXIT 0, 0 errors**.
* `AcadMCP.csproj` (net8, local AutoCAD 2026 API) → **EXIT 0, 0 errors**.

A fresh `RevitMCPCore.dll` (carrying this fix + Fix 3.C) was built and
staged as the next hot-reload artifact at
`payload/revit/2025/hotfix/RevitMCPCore-hotfix7.dll` (gitignored), ready
for `/reload` into the live Revit without a restart.

> Note: the canonical `auto_build.py revit 2025` exits 1 ONLY because the
> running Revit holds `payload/revit/2025/RevitMCP.dll` open (deploy-stage
> file lock) — not a compile error. The hotfix7 staging path sidesteps
> the lock; that is exactly what AgDR-0027 hot-reload is for.

### AutoCAD — operational, not code

AutoCAD 2026 is installed (not 2025) and acad.exe PID 14556 is running
(A-200), but `:48885/ping` is actively refused → the AcadMCP add-in is
NOT loaded into the live session (`Initialize()` never ran → listener
never bound). This is OPERATIONAL (no NETLOAD / registration), not a
CS0012/code fault. The AcadMCP source compiles clean with this fix and
inherits the same cold-start protection the moment it IS loaded — its
`RunCSharpScript` had the identical latent hole (hardcoded BCL list
without `System.Runtime`), now covered at the shared layer. Per the
incident-safety rule the live NETLOAD is FLAGGED for VerifyShip, not
forced (see Open items).

## Consequences

### Wins

1. CS0012 cold-start hole closed for the whole class — every net8
   Revit/AutoCAD host, every future runtime split (net9/net10), because
   the facades are resolved by file, not sampled from load state.
2. One shared-layer edit fixes Revit AND AutoCAD; the two most-sensitive
   per-connector contract files are untouched (minimal blast radius on
   contract surfaces — directly honours the 2026-05-25 incident).
3. net48 (Revit 2020-2024) regression-free: facade subset / empty on
   that directory layout, response file absorbs size.

### Open items (TRUE boundaries — handed to VerifyShip)

1. **Revit live deploy (hot-reload).** `RevitMCPCore-hotfix7.dll` is
   staged. VerifyShip POSTs to the live broker (do NOT restart Revit):
   ```
   POST http://localhost:48884/reload
   {"core_path":"<repo>\\payload\\revit\\2025\\hotfix\\RevitMCPCore-hotfix7.dll"}
   ```
   then `/exec {"code":"result = 42;"}` must return `{status:ok}` and a
   `list_levels` must return rows. This is the live-confirm that both
   the CS0012 fix AND (via the already-present Fix 3.C in the fresh
   build) the FileLoadException clear on the live host. Flagged as a
   live-confirm because the FileLoadException's drift cause is
   deployment-state, which only the live `/reload` can settle — the
   standalone repro could not reproduce it, so it is not asserted fixed
   until the live reload is observed.
2. **Stale-cache contingency.** If `/reload` of hotfix7 still shows the
   FileLoadException, clear the live process's
   `%TEMP%\archhub-csc-cache` (the broker recompiles on next /exec).
   Low risk; no doc impact.
3. **AutoCAD NETLOAD (operational).** Into the running acad.exe PID
   14556, in the AutoCAD command line (does NOT modify A-200):
   `NETLOAD` → select the freshly built `AcadMCP.dll` (build with
   `py app/auto_build.py acad 2026`, or the local-API build used this
   session). Then `:48885/ping` should return ok. Flagged for VerifyShip
   to attempt carefully or hand to the founder — never forced while his
   drawing is open.
4. **Canonical redeploy on next clean toggle.** A clean Connectors-panel
   toggle should redeploy `RevitMCPCore.dll` (canonical name, this
   build) so future Revit launches load a Core that carries both fixes,
   retiring the hotfix sidecar (carries over from AgDR-0037 open item 4).

## Artifacts

* `payload/sources/shared/ScriptCompiler.cs` — `_BclFacadeRefs()` helper
  + additive facade merge in `CompileAndRun` (the ONLY source change).
* This AgDR.
* Staged build (gitignored): `payload/revit/2025/hotfix/RevitMCPCore-hotfix7.dll`
  (SHA256 F23C8441E1E3A4795E466E840B6000D7B4ECD91A2EA337D2403369583E200908)
  + `.deps.json`. Carries this fix + AgDR-0037 Fix 3.C.
* Bench proofs (outside repo, `_alcrepro/`): `cs0012.ps1` (CS0012
  cold-fail → facade-fixed COMPILE OK) and `repro.ps1` (collectible-ALC
  load CLEAN across 3 variants — isolates the live FileLoadException as
  deployment-state drift, not a source defect).
* Live evidence: `/ping` PID 96076 port 48884 `csc_status:ok`
  `csc_path:...sdk/10.0.100-rc.1.../Roslyn/bincore/csc.dll`; pre-fix
  `/exec` reproduced CS0012 (LINQ probe) and FileLoadException 0x80131515
  (`result=42`).
