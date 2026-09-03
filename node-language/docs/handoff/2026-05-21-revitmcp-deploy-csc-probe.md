# Handoff — ArchHub root fixes for connector deploy gap + csc probe gap (ALL HOSTS)

**From:** Claude session 2026-05-21 (closing on commit `eccfc2c`)
**To:** Next Claude session
**Repo:** `C:\Users\fargaly\00.ARCHUB\ArchHub`
**HEAD:** `eccfc2c feat(roslyn+lag+hot-reload+library): AgDR-0025/26/27/28 ship`
**Source tree on disk:** fully the v2 reflection-by-name ABI (good). Working tree clean.

Two ROOT-CAUSE bugs found in production that any other ArchHub user will hit. Both need fixing at source + committing per the ENGINEERING MANDATE in `CLAUDE.md` (fix the class of bug, add a guard test). Each warrants its own AgDR per the AGDR MANDATE — propose them before coding, get founder sign-off in chat.

**Founder demand 2026-05-21:** "make sure those bugs won't happen for other hosts as well." → the fix must be GENERIC across every .NET-host connector (Revit, AutoCAD, future Rhino/Blender/etc.), not Revit-specific. Generalisations called out in each section below.

---

## Bug 1 — Build script doesn't build Core DLL

**Symptom:** Revit 2025 add-in fails `OnStartup` with
`System.InvalidOperationException: Core DLL ...RevitMCPCore.dll has no ICoreEntryPoint impl`
OR
`RevitMCPCore.dll missing`.
Listener never binds → broker port (48884–48899) unreachable for Revit 2025 sessions while Revit 2020 sessions work fine.

**Root cause:** AgDR-0027 split RevitMCP into `RevitMCP.dll` (shim) + `RevitMCPCore.dll` (hot-reloadable). `app/auto_build.py.build_revit_connector` (and `FixAndTestRevit2025.bat`) still only invokes `dotnet build` on `payload/sources/revit_mcp/RevitMCP.csproj`. `payload/sources/revit_mcp_core/RevitMCPCore.csproj` never gets built. End users toggling Revit from the Connectors panel get a half-deployed pair: fresh shim + missing-or-stale Core. The shim's `CoreLoader.Load()` either can't find `RevitMCPCore.dll` next to `RevitMCP.dll` (fresh install) or finds a Core built before the v2 amendment (upgrade install) and the reflection probe for the `CoreEntry` class fails.

**Why 2020 escapes:** net48 build path is one DLL, no shim/core split.

**Fix at source (GENERIC — covers every host, not Revit only):**

The bug is specific to RevitMCP today (it's the only host with a shim+core split per AgDR-0027), but AcadMCP and every future .NET host WILL get the same hot-reload split eventually. Fix the build pipeline so this class of bug can't recur:

1. **Data-driven build manifest.** For each connector source root (`payload/sources/<host>_mcp`), discover EVERY `*.csproj` under `payload/sources/<host>_mcp*` (note the trailing `*` — picks up both `revit_mcp` and `revit_mcp_core`) and build them all into the same `output_dir`. Generalise `build_revit_connector` → `_build_dotnet_connector(host, year, sources_glob, ...)`. Same approach for `build_acad_connector`.
2. **Hard-fail on any csproj build failure.** If the shim builds and the Core fails, the whole connector toggle fails — don't half-deploy.
3. Mirror in `FixAndTestRevit2025.bat` + any other batch entry points (`BuildRevit2023.bat`, AcadMCP installer paths if they bundle DLLs).
4. **Deploy-time sanity gate.** Before copying `payload/<host>/<year>/` → `%LOCALAPPDATA%\ArchHub\<Host>\<year>\`, scan the deployed dir against a manifest of expected DLLs. If any expected DLL is missing or older than its source, fail loudly with a typed error per the USER-AGENCY MANDATE. Generic — works for any host.
5. **Guard test** in `tests/test_connector_build.py` (new): mock `_run_dotnet_build` and assert each `build_*_connector(year)` invokes it for EVERY csproj under that connector's source root, into the same `output_dir`. Parametrise over `[revit, acad]` so adding a new host or splitting an existing host into shim+core automatically widens coverage. Kills the class of bug — any future Nth DLL added to ANY connector that's not wired into the build trips this test.
6. **Manifest file (optional but recommended).** Each connector source root carries a `payload/sources/<host>_mcp/build-manifest.json` listing every csproj + expected output DLL. Build script reads it; deploy step verifies against it. Single source of truth, no globbing surprises.

**AgDR naming suggestion:** `AgDR-0029-connector-build-pair-shim-and-core.md` (note: scope broadened from `revitmcp-` to `connector-` — applies to every host). Reference back to AgDR-0027.

**Diagnostic the user can run before/after** to verify (no rebuild needed):

```powershell
Get-ChildItem "$env:LOCALAPPDATA\ArchHub\Revit\2025\RevitMCP*.dll" |
    Select Name, Length, LastWriteTime
# Both DLLs must exist + LastWriteTime >= the latest source mod time

Get-Content (Get-ChildItem "$env:TEMP\*\revit-mcp.log" |
    Sort LastWriteTime -Desc | Select -First 1).FullName
# Shim's own error trail (it logs to %TEMP%\<guid>\revit-mcp.log)
```

---

## Bug 2 — ScriptCompiler csc.exe probe falls off a cliff on machines without VS BuildTools

**Symptom:** `/exec` route returns
`{"status":"error","error_code":"compile_error","error":"error CS1617: Invalid option '7.3' for /langversion; must be ISO-1, ISO-2, 3, 4, 5 or Default"}`.
Listener works, connector loads — but every script call fails.

**Root cause:** `payload/sources/shared/ScriptCompiler.cs::_ProbeOnce()` picks the first hit in this order:

1. `$ARCHHUB_CSC_PATH` env var (rare).
2. `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe` — the comment claims this is "Roslyn 1.x" with C# 7.3 support. On .NET Framework 4.8.1 / 4.8 Update installs this csc.exe is the legacy single-file csc that **caps at C# 5**. Comment is wrong, probe accepts it, every compile fails on `/langversion:7.3`. Verify on any 4.8.1 box:
   `& "$env:windir\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /langversion:?`
   output explicitly says "only supports language versions up to C# 5".
3. VS 2022 BuildTools at well-known paths — not present on this box, and not present on most end-user machines (Revit users aren't typically VS developers).
4. .NET SDK `csc.dll` — commented out as "skipped because spawning `dotnet exec csc.dll` adds JIT overhead". This is the only thing reliably installed alongside Revit-add-in users.

So in practice the probe lands on a csc that can't compile any AgDR-0025 script. ArchHub looks broken for everyone who doesn't happen to have VS BuildTools.

**Bug 2 scope is ALREADY generic.** `payload/sources/shared/ScriptCompiler.cs` is `<Link>`-ed into RevitMCP (Core), AcadMCP, and every future .NET host connector per AgDR-0025. Fixing the probe in this single file fixes /exec for every host simultaneously. No per-host code change needed.

**Fix at source — three pieces:**

1. **Demote the Framework64 csc.exe in the probe order** — call its `/langversion:?` output once at probe time (read stderr, scan for "up to C# 5"), reject if it doesn't advertise ≥7.3. Cache the verdict per-process.
2. **Wire up step 4** (`dotnet exec csc.dll`). Probe for `dotnet --list-sdks`, take the highest SDK path, locate `Roslyn/bincore/csc.dll` under it. When invoking, prepend `dotnet exec` to the args. The "JIT overhead" comment is misleading — SDK csc startup is ~300 ms cold, and AgDR-0025 already has a sha-keyed cache that skips compile on hit, so the overhead is paid once per unique script.
3. **Optional bundle:** ship a Roslyn `csc.exe` from the `Microsoft.Net.Compilers.Toolset` NuGet alongside the connector DLLs. Makes EVERY .NET connector self-contained — works on a clean box with only the host app installed (Revit, AutoCAD, …). **Decision for the founder:** bundle (~5 MB add to each connector deploy) vs require SDK present.

**Guard test:** a unit test that asserts `ProbeCsc()` rejects any csc whose `/langversion:?` output contains "up to C# 5" and asserts it accepts at least one of (modern fx csc with Roslyn, VS BuildTools csc, SDK csc.dll via `dotnet exec`). Mock subprocess to feed it the Framework 4.8.1 stderr signature. Test lives at `tests/test_script_compiler_probe.py` — covers ALL hosts implicitly since they all link the same ScriptCompiler.cs.

**Verify the fix lands for every host:** after shipping AgDR-0030, /exec must work on Revit 2025 AND AutoCAD AND any future .NET host on a clean box (no VS BuildTools). Add an integration smoke that POSTs /exec to each running host's broker port and asserts `status:ok`.

**AgDR naming suggestion:** `AgDR-0030-csc-probe-modern-roslyn-fallback.md`. Reference back to AgDR-0025. (Name stays — already host-agnostic.)

---

## Context this session already verified

- Source tree at HEAD is correct (CoreEntry-by-name reflection, no shared interface). The bug is in the deploy + probe machinery, not the connector itself.
- Manual rebuild + redeploy of `RevitMCP.dll`+`RevitMCPCore.dll` into `%LOCALAPPDATA%\ArchHub\Revit\2025\` brings the listener back. PA-JPD17-04 is now reachable on port 48884 in this session (PID 37640, Revit 2025.4). 2020 sessions on 48885/48887/48888 unaffected throughout.
- `/exec` works on 2020 sessions (they use a different in-process compile path, not AgDR-0025 subprocess csc). `/exec` fails on 2025 on this box because of Bug 2.
- Working tree is clean. No commits made by this session. Both fixes should be separate commits with their own AgDRs, founder sign-off per AGDR MANDATE, and tests per ENGINEERING MANDATE.

## Generalisation summary — all-hosts coverage

Founder mandate 2026-05-21: "make sure those bugs won't happen for other hosts as well."

| Bug | Generic fix | Why it covers every host |
|---|---|---|
| 1 (build pair) | Data-driven `_build_dotnet_connector(host, year, …)` that builds every csproj under `payload/sources/<host>_mcp*` into one output_dir. Manifest + deploy gate. Parametrised guard test over `[revit, acad, …]`. | Future shim+core splits for AcadMCP / any new .NET host are picked up automatically — no per-host code change. |
| 2 (csc probe) | `ScriptCompiler.cs::_ProbeOnce()` rejects sub-C#7.3 csc via `/langversion:?`, wires the SDK `dotnet exec csc.dll` path. | `ScriptCompiler.cs` is `<Link>`-ed into every .NET connector's csproj per AgDR-0025 → one edit, every host fixed. |

Status today:
- RevitMCP: shim+core split, bugs visible.
- AcadMCP: still monolithic (no Core split yet), uses same ScriptCompiler → Bug 2 hits it too, Bug 1 doesn't yet.
- MaxMCP: Python sidecar, no .NET, no Roslyn → neither bug applies.
- Future Rhino/Blender/etc.: handled by the generic fix shape above.

## What to do

Pick up the brief above. Two root-cause bugs in connector deploy + ScriptCompiler probe — both will hit any ArchHub user on any .NET host, both already diagnosed end-to-end. Write **AgDR-0029** (connector-build-pair-shim-and-core, GENERIC) and **AgDR-0030** (csc-probe-modern-roslyn-fallback, already host-agnostic) as proposed, surface the design forks for the founder, then ship the code + tests + commits per the ENGINEERING + AGDR MANDATEs. Reference back to AgDR-0027 and AgDR-0025 respectively.

**Don't touch the source tree until the founder has signed off each AgDR.**
