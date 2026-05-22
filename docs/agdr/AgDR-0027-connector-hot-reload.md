---
id: AgDR-0027
timestamp: 2026-05-21T14:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "DIDN'T WE AGREE THAT THE CONNECTORS SHOULDN'T REQUIRE RESTARTING REVIT... OR CLOSING CURRENT SESSIONS?"
trigger: AgDR-0025 deploy required restart of Revit 2025 to swap the in-memory `RevitMCP.dll`.  Founder's agreed principle: connector updates ship hot.
status: approved
category: architecture
projects: [archhub, revitmcp, acadmcp]
extends:
  - AgDR-0025 — Subprocess csc Roslyn isolation (the change that
    surfaced the missing hot-reload story)
  - AgDR-0002 — disable verbs / no-restart semantics (founder's
    original "don't restart" position)
---

# Connector hot-reload — thin shim + collectible AssemblyLoadContext, so every future connector DLL update lands without restarting Revit / AutoCAD

> Founder principle (re-stated 2026-05-21): connector updates MUST
> NOT require closing host sessions.  AgDR-0025 violated that —
> swapping the new RevitMCP.dll needed one Revit 2025 restart
> because Revit's AppDomain pinned the old DLL.  This AgDR locks
> the architecture that prevents the next forced restart, forever.

## Constraints (signed)

1. **Add-in shim is a stable thin loader.** `RevitMCP.dll` /
   `AcadMCP.dll` carry ONLY the host-vendor interfaces
   (`IExternalApplication`, `IExtensionApplication`) plus an
   `IExternalEventHandler` work queue.  They never change between
   ArchHub versions — host pinning of these DLLs is fine.
2. **Real impl lives in a hot-reloadable Core DLL.**
   `RevitMCPCore.dll` / `AcadMCPCore.dll` hold the HTTP listener,
   `/exec` route, ScriptCompiler usage, etc.  These ship updates;
   the shim never blinks.
3. **Collectible AssemblyLoadContext on .NET 8** (Revit 2025+,
   AutoCAD 2025+).  The shim loads Core into an unloadable ALC;
   `/reload` disposes that ALC + loads a fresh Core DLL → no
   Revit restart.
4. **Net48 fallback (Revit 2020–2024).**  Collectible ALC doesn't
   exist on net48.  For those years the shim STILL hosts the new
   Core but can't unload the old one — first install is hot
   (because no old Core was loaded yet), subsequent updates are
   queued for the next Revit launch (with a clear "needs Revit
   restart this version" warning in the broker UI).  Net48 hot
   updates become a follow-up slice (sidecar process).
5. **Stable HTTP contract across reloads.**  The listener port,
   /ping, /info, /exec, /screenshot, /reload routes never change
   shape across Core versions.  ArchHub Python doesn't need to
   know which Core is in flight.
6. **Same hot-reload pattern for every .NET connector.**
   RevitMCP, AcadMCP, plus any future net-host connector — all use
   the shared `payload/sources/shared/CoreLoader.cs` to host their
   Core.

## Decision

### Repository layout

```
payload/sources/
  shared/
    ScriptCompiler.cs         (AgDR-0025 — unchanged)
    CoreLoader.cs             (NEW — shim-side ALC manager)
    ICoreEntryPoint.cs        (NEW — contract interface)
  revit_mcp/
    RevitMCP.csproj           (shim only — net8 + net48)
    RevitMCPApp.cs            (IExternalApplication + IEEH)
  revit_mcp_core/
    RevitMCPCore.csproj       (NEW — hot-reloadable impl)
    HttpServer.cs             (moved from RevitMCPApp.cs)
    RouteHandlers.cs          (/info /exec /screenshot)
    CoreEntry.cs              (implements ICoreEntryPoint)
  acad_mcp/  (parallel layout)
  acad_mcp_core/
```

### ICoreEntryPoint

```csharp
namespace ArchHub.Shared {
  public interface ICoreEntryPoint {
    // Called by the shim once on Core load.  Receives the work-queue
    // callback (run-on-host-thread) + a logger.  Returns when the
    // HTTP listener is up.
    void Start(IWorkQueue queue, Action<string> log,
               IDictionary<string,string> hostInfo);
    // Called by the shim on /reload before the ALC is disposed.
    // Core must stop the listener + release every resource.
    void Stop();
  }
  public interface IWorkQueue {
    // Returns a string result.  The Func runs on the host UI thread.
    System.Threading.Tasks.Task<string> SubmitAsync(
        Func<object, string> fn);
  }
}
```

`ICoreEntryPoint` + `IWorkQueue` live in the shared file so BOTH
the shim and the core reference the SAME type (loaded into the
default ALC — type identity is stable across Core reloads).

### CoreLoader (net8 path)

```csharp
public class CoreLoader {
  private System.Runtime.Loader.AssemblyLoadContext _alc;
  private ICoreEntryPoint _core;
  public void Load(string corePath, IWorkQueue queue, ...) {
    _alc = new AssemblyLoadContext("RevitMCPCore", isCollectible: true);
    _alc.Resolving += (ctx, name) => { ... probe addin dir ... };
    var asm = _alc.LoadFromAssemblyPath(corePath);
    var t = asm.GetTypes().Single(x => typeof(ICoreEntryPoint).IsAssignableFrom(x));
    _core = (ICoreEntryPoint)Activator.CreateInstance(t);
    _core.Start(queue, log, hostInfo);
  }
  public void Unload() {
    _core?.Stop(); _core = null;
    _alc?.Unload(); _alc = null;
    System.GC.Collect(); System.GC.WaitForPendingFinalizers();
  }
}
```

Shim adds one extra HTTP route:
```
POST /reload  body: {"core_path": "C:\\...\\RevitMCPCore-v0.5.0.dll"}
→ Unload + Load + 200 OK {"status":"ok","loaded_from":"..."}
```

### Net48 fallback

`CoreLoader` on net48 does `Assembly.LoadFrom(corePath)` directly
into the default AppDomain (no unload).  First install lands hot
(no old Core to displace).  Subsequent `/reload` returns
`{"status":"error","error_code":"net48_no_hot_reload"}` so the
broker shows "Restart Revit 2024 to apply update" — but only on
older years.  Sidecar-based hot reload for net48 is queued.

### ArchHub Python side

`app/auto_build.py`:
- Builds BOTH `RevitMCP.dll` (shim, stable) AND
  `RevitMCPCore.dll` (hot impl).
- Deploys shim to `%LOCALAPPDATA%\ArchHub\Revit\<year>\` ONCE.
- Deploys Core to versioned filename
  `%LOCALAPPDATA%\ArchHub\Revit\<year>\RevitMCPCore-<sha>.dll`.
- After deploy, POSTs `/reload` to every running Revit session
  (net8 only) so each session swaps Core live.

`app/connectors/revit_broker.py`:
- Records `core_sha` from /ping.
- Triggers /reload when a newer Core ships.

## What ships in THIS commit

1. `payload/sources/shared/CoreLoader.cs` + `ICoreEntryPoint.cs`.
2. `payload/sources/revit_mcp/` — refactored shim (only
   IExternalApplication + IEEH + bootstrap; HTTP moved out).
3. `payload/sources/revit_mcp_core/` — new csproj + moved files
   (HttpServer, route handlers, RunCSharpScript via ScriptCompiler).
4. `payload/sources/acad_mcp/` + `acad_mcp_core/` — parallel split.
5. `app/auto_build.py` — two-DLL build + deploy paths.
6. `app/connectors/revit_broker.py` — `/reload` trigger when
   `core_sha` mismatches.
7. Tests — pin the split + hot-reload contract.

## What does NOT ship

- net48 sidecar-based hot reload (queued — AgDR-0028 candidate).
- Cross-connector reload coordination if many hosts are open.

## Acceptance

1. Fresh Revit 2025 boot loads shim + initial Core; /ping ok.
2. Founder edits Core source, runs `python -m archhub.auto_build`,
   waits ≤ 5 s.  No Revit restart.  Next /exec uses new Core.
3. /ping reports `core_sha: <new>` after reload.
4. Suite green.  Founder confirms via CDP demo.

## Risks

- **Type identity bugs.**  If ICoreEntryPoint accidentally lives
  in the Core ALC (not default), reloads break with cast
  exceptions.  Guard: tests load both DLLs in a unit harness and
  cast through ICoreEntryPoint.
- **Stale captures.**  If shim holds delegates pointing into the
  old Core ALC, that ALC can't be GC'd → unload silently fails.
  Mitigation: shim only holds the ICoreEntryPoint reference; nulls
  it on Stop().
- **Forced restart for net48 stays.**  Documented + UI-warned.

## v2 amendment (2026-05-21, same day)

First implementation put `ICoreEntryPoint` + `IWorkQueue` as
interfaces in shared/ICoreEntryPoint.cs and linked the source
into both shim and Core csprojs.  RESULT — two distinct CLR
types named `ArchHub.Shared.ICoreEntryPoint`, one in each
assembly.  Shim's `IsAssignableFrom(coreType)` returned false →
Core was never discovered → shim crashed silently in
OnStartup → HTTP listener never bound on Revit 2025.

**Fix shipped same day:**
- `ICoreEntryPoint.cs` reduced to a placeholder (header comment
  explains the bug, no public surface).
- `CoreLoader.cs` discovers `CoreEntry` by NAME via reflection;
  no interface check.
- ABI between shim ↔ Core is BCL-only:
  `Func<Func<object,string>, Task<string>>` for the submit pump,
  `Action<string>` for log + reload trigger,
  `IDictionary<string,string>` for hostInfo.
- Core's `CoreEntry` no longer implements any shim interface; it
  exposes Start/Stop methods + ReloadTriggerForShim property by
  name, all discoverable via reflection.

This sidesteps the type-identity problem entirely without
introducing a separate ArchHub.Shared.dll.

## Artifacts

- This AgDR.
- Pending implementation listed in §"What ships in THIS commit".
