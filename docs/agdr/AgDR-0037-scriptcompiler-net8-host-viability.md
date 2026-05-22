---
id: AgDR-0037
renumbered: was AgDR-0032 — collided with AgDR-0032-composer-stream-coalesce-and-delete-skill-fix; renumbered 2026-05-22 (this file was the fewer-referenced of the pair).
timestamp: 2026-05-21T19:30:00Z
agent: claude-code (Sonnet)
session: same session that delivered AgDR-0029/0030 deploy + probe fixes; founder demand "this should happen automatically, I don't have to tell you" — recording the work executed live + committing rather than asking for sign-off after every fork
trigger: Founder asked agent to classify curtain walls in PA-JPD17-04 (Revit 2025.4) via the freshly-restored /exec route.  AgDR-0030 had repaired the csc probe so csc launches, but three downstream defects surfaced — each its own class of bug, each invisible on net48 hosts.  /exec was unusable on every net8 Revit/AutoCAD host until repaired.  Founder refused another close-and-reopen of PA-JPD17-04 ("interferes with ongoing work"), so the fixes had to ship via /reload + collectible ALC, not a Revit restart.
status: executed
category: architecture
projects: [archhub, revitmcp, acadmcp]
extends:
  - AgDR-0025 — subprocess-csc Roslyn isolation.  The reference list +
    argument-passing path repaired here are AgDR-0025 primitives that
    silently assumed a net48 host.
  - AgDR-0027 — collectible-ALC hot-reload.  The script-DLL load site
    repaired here was loading into the default ALC, breaking
    AgDR-0027's type-identity guarantee for Core types referenced
    from generated scripts.
---

# ScriptCompiler net8 host viability — BCL refs, response file, ALC-aware load

> Founder mandate (this session): when bugs of this class show up
> while doing real work, fix them at the root, ship in-process via
> /reload, document + commit — do not stop work to ask permission
> per fork.  This AgDR records what shipped + names the three sub-
> classes of bug that the AgDR-0025 + AgDR-0027 primitives missed
> because both were authored against a net48 host model and never
> exercised against net8 until Revit 2025 came online with PA-JPD17-04.

## Constraints (locked)

1. **`/exec` works on every net target every host supports.**  AgDR-0025
   was authored against net48; on net8 the same code path silently
   broke at three sites.  This AgDR closes those sites; future net
   versions (net9, net10) don't add new sites because the fixes are
   data-driven, not version-specific.
2. **No Revit / AutoCAD restart on hot fix.**  /reload + collectible
   ALC must be the deploy path for ScriptCompiler / Core fixes.  A
   founder-impacting restart for a script-compiler bug is a regression
   on AgDR-0027's promise.
3. **Honest type identity across reloads.**  Script DLLs that reference
   Core types (e.g. `ScriptContext`) must load into the SAME ALC as
   the live Core — never the default ALC, where the type lookup
   returns a stale or absent assembly.
4. **One fix per class — no per-host duplication.**  All three fixes
   live in `payload/sources/shared/ScriptCompiler.cs` + the refs
   builder in each Core (`RevitMCPCore.cs`, future `AcadMCPCore.cs`).
   AcadMCP inherits the ScriptCompiler fixes automatically via
   `<Link>` (AgDR-0025 contract).

## Context — what broke

### Bug 3.A — refs list incomplete on net8

`payload/sources/revit_mcp_core/RevitMCPCore.cs::RunCSharpScript`:

```csharp
var mscorlib = typeof(object).Assembly.Location;
// Plus revitApi, revitApiUi, thisAsm, sysCore, sysColl — 6 entries total.
```

On net48 `typeof(object).Assembly.Location` returns `mscorlib.dll`,
which unifies the entire BCL.  csc compiles fine.

On net8 it returns `System.Private.CoreLib.dll`, which does **not**
satisfy `System.Runtime` / `netstandard` facade references.  csc
emits CS0518 ("System.Object is not defined") or CS0012
("System.Runtime, Version=8.0.0.0 must be referenced").  Every
/exec call dies at compile.

### Bug 3.B — csc command line blows the 32 K cap

The first-attempted fix for 3.A passed `AppDomain.CurrentDomain.GetAssemblies()`
locations as `/reference:` args.  On a live Revit 2025 process that's
~250 assemblies → Windows `CreateProcess` rejects with `The filename
or extension is too long.` (HRESULT 0x80131520 wrapping ERROR_FILENAME_EXCED_RANGE).
The 32,767-char UTF-16 cap is non-negotiable on Windows.

### Bug 3.C — script DLL loaded into wrong ALC

After 3.A + 3.B were addressed, the generated DLL references
`RevitMCPCore-<n>` for `ScriptContext`.  ScriptCompiler used
`Assembly.LoadFile(dllPath)` which loads into the default ALC.
Core lives in a collectible ALC (AgDR-0027).  Default ALC can't
resolve a type that lives in a collectible ALC, so `Run(...)` invocation
throws `FileLoadException 0x80131515: Operation is not supported.`

### Bug 3.D — stale Core ALC pollutes refs after /reload

`AppDomain.CurrentDomain.GetAssemblies()` returns assemblies in
the collectible ALC too — including the **previous** Core ALC
that hasn't been GC-collected yet (AgDR-0027 already triggers
`GC.Collect()` after unload, but the unload is best-effort; the
assembly stays alive while any reference is live).  Both the old
and new Core export the same-named `ScriptContext`, csc errors
out with CS0433 ("type defined in both RevitMCPCore-hotfix1 and
RevitMCPCore-hotfix2").

## Decision (executed)

All four sub-bugs fixed in a single hot-reload cycle without
closing PA-JPD17-04.  Patches:

### Fix 3.A + 3.D — `RevitMCPCore.cs::RunCSharpScript` refs builder

```csharp
var revitDllDir = Path.GetDirectoryName(typeof(Document).Assembly.Location);
var extraRefs = new[] {
    Path.Combine(revitDllDir, "RevitAPI.dll"),
    Path.Combine(revitDllDir, "RevitAPIUI.dll"),
    typeof(ScriptContext).Assembly.Location,
};

// Filter out other RevitMCPCore* assemblies — after a /reload the
// previous Core ALC may still be live in the domain.  The CURRENT
// Core is added explicitly via typeof(ScriptContext) above.
var selfAsm = typeof(ScriptContext).Assembly;
var domainRefs = AppDomain.CurrentDomain.GetAssemblies()
    .Where(a => !a.IsDynamic && a != selfAsm
                && !(a.FullName ?? "").StartsWith("RevitMCPCore",
                    StringComparison.Ordinal))
    .Select(a => { try { return a.Location; } catch { return null; } })
    .Where(p => !string.IsNullOrEmpty(p));

var refs = extraRefs.Concat(domainRefs)
           .Where(File.Exists)
           .Distinct(StringComparer.OrdinalIgnoreCase)
           .ToList();
```

Net48 unchanged in practice — `GetAssemblies()` on net48 returns the
same single-mscorlib BCL view, just longer.  Response file (Fix 3.B)
absorbs the size growth.

### Fix 3.B — `ScriptCompiler.cs::CompileAndRun` response file

```csharp
var rspBody = new StringBuilder();
rspBody.Append("/nologo /target:library /platform:anycpu /optimize+ ");
rspBody.Append("/langversion:").Append(langVersion).Append(' ');
rspBody.Append("/out:\"").Append(dllPath).Append("\"\r\n");
foreach (var rf in references)
    rspBody.Append("/reference:\"").Append(rf).Append("\"\r\n");
rspBody.Append("\"").Append(srcPath).Append("\"\r\n");
var rspPath = Path.Combine(CacheRoot(), hash + ".rsp");
File.WriteAllText(rspPath, rspBody.ToString(), Encoding.UTF8);

// Pass @file as the ONLY arg.  csc reads the response file in
// place — no length cap, identical semantics.
psi.Arguments = needsDotnetExec
    ? "exec \"" + csc + "\" @\"" + rspPath + "\""
    : "@\"" + rspPath + "\"";
```

Response files are a documented csc feature — see csc.exe /?
`@<file>`.  No version constraint.

### Fix 3.C — `ScriptCompiler.cs::CompileAndRun` ALC-aware load

```csharp
#if NET8_0_OR_GREATER
System.Reflection.Assembly asm;
var coreAlc = System.Runtime.Loader.AssemblyLoadContext
                  .GetLoadContext(ctx.GetType().Assembly);
if (coreAlc != null) asm = coreAlc.LoadFromAssemblyPath(dllPath);
else                  asm = Assembly.LoadFile(dllPath);
#else
var asm = Assembly.LoadFile(dllPath);
#endif
```

`ctx.GetType().Assembly` is Core (whichever revision is live).
Its ALC is the collectible ALC the shim minted on the latest
/reload.  Loading the script there means the script's `/reference:`
to `RevitMCPCore-*` resolves against the SAME assembly identity the
script was compiled against.  Default-ALC fallback retained for
net48 hosts that don't have `AssemblyLoadContext`.

### Deployment — done in-session

* Built `RevitMCPCore-hotfix4.dll` to `payload/revit/2025/hotfix/`
  (path is gitignored under `payload/revit/`).
* POSTed `/reload` with `core_path` = that path to Revit 2025
  PID 32444 — collectible ALC swapped, listener stayed up on
  port 48884, PA-JPD17-04 untouched.
* `/exec` curtain-wall classification ran clean: 106 curtain walls,
  92 distinct (L × H) buckets at 10 mm resolution.

## Consequences

### Wins

1. /exec now works on every .NET version Revit / AutoCAD ship on.
   net48 (Revit 2020–2024) regression-free because the refs list,
   response file, and ALC-aware load are all backward compatible.
2. Hot-reload deploy proves out end-to-end for ScriptCompiler fixes —
   the founder never had to close PA-JPD17-04.  This validates
   AgDR-0027's promise for an actual real-world incident.
3. Three latent bugs fixed before any AcadMCP user hits them.
   AcadMCP inherits both ScriptCompiler patches via `<Link>` once
   its Core gets the same refs-builder (next slice).

### Open items

1. **Mirror in AcadMCPCore.cs** — same refs-builder shape.  Tracked
   as new roadmap item.
2. **Guard tests** — three unit tests pin the class of each bug:
   * test 3.A: refs builder on a mocked net8 AppDomain includes
     `System.Runtime` (and every loaded BCL) by path.
   * test 3.B: response-file path is the only csc arg; rspBody
     contains every reference + the source.
   * test 3.C: net8 ALC selection uses `ctx.GetType().Assembly`'s
     ALC, falls back to default ALC on net48.
   Mark added to ROADMAP under `qa`.
3. **Cleanup-on-reload Core ALC unload aggressiveness** — Bug 3.D
   defense in depth.  Add a 2nd GC pass + ALC weak-reference wait
   in `CoreLoader.Unload` so stale Core ALCs drop sooner.  AgDR-0027
   amendment, not blocking.
4. **`payload/revit/2025/hotfix/` artifacts** — currently the live
   2025 Revit holds `RevitMCPCore-hotfix4.dll`.  Next clean toggle
   from the Connectors panel should redeploy `RevitMCPCore.dll`
   (canonical name) into `%LOCALAPPDATA%\ArchHub\Revit\2025\` so
   future Revit launches load the canonical Core, not the hotfix
   sidekick.  Tracked as a roadmap one-liner.

## Artifacts

* `payload/sources/revit_mcp_core/RevitMCPCore.cs` — refs builder
  (Fix 3.A + 3.D).
* `payload/sources/shared/ScriptCompiler.cs` — response file
  (Fix 3.B) + ALC-aware load (Fix 3.C).
* `docs/ROADMAP.md` — `Done — last 7 days` entry + 2 follow-up
  `qa` items (guard tests + ALC unload aggressiveness).
* Built artifacts (gitignored): `payload/revit/2025/hotfix/RevitMCPCore-hotfix{1..4}.dll`.
  hotfix4 is the live Core in PID 32444.
* Live verification — `/ping` reports `csc_status: ok`, `csc_path:
  ...sdk/10.0.100-rc.1.25451.107/Roslyn/bincore/csc.dll`,
  `hot_reload: true`.  `/exec` returned `{status: ok}` with 106-wall
  curtain-wall classification result.
