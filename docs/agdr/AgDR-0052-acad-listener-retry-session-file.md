---
id: AgDR-0052
timestamp: 2026-06-01T00:00:00Z
agent: claude-code (Opus 4.8)
session: incident-boundary broker repair · founder "fix them" sign-off 2026-06-01
trigger: AcadMCP broker dies on a stale http.sys URL reservation — single
  hardcoded port 48885, no retry, no session file. The listener gives up
  (returns) on the first HttpListenerException, forcing a manual NETLOAD
  every time the reservation goes stale. RevitMCP already solved this class
  (port-range scan + session-file heartbeat) in AgDR-0027 / RevitMCPCore.
status: executed
category: architecture
projects: [archhub, acadmcp]
extends:
  - AgDR-0027 — connector hot-reload split that introduced the
    RevitMCPCore.CoreEntry port-scan + session-registry pattern this mirrors.
  - AgDR-0029 — data-driven multi-csproj build + SHA-256 deploy manifest
    (the gate that re-pins AcadMCP.dll after this rebuild).
---

# AcadMCP listener resilience — port-range scan + retry + session-file heartbeat (mirror of the Revit broker)

> In the context of the founder's "fix them" sign-off (2026-06-01) for the
> AutoCAD broker dying on a stale `http.sys` URL reservation, I decided to
> make an **ADDITIVE, surgical** change to `AcadMCPApp.cs` that mirrors the
> proven `RevitMCPCore.CoreEntry` pattern: WIDEN the single hardcoded port
> 48885 into a 48885..48899 scan that retries on bind failure, and ADD a
> session-file writer + 10s heartbeat at
> `%LOCALAPPDATA%\ArchHub\sessions\autocad-<pid>.json`. The transaction model
> (`RunCSharpScript` + `DocumentLock` + `Transaction`) is UNTOUCHED, and the
> canonical port 48885 is PRESERVED as the first element of the scan range
> (non-destructive). This is explicitly NOT the 2026-05-25 incident class
> (an agent rewrote the port 48885→48887 + injected a NopFP into the
> transaction path, reverted): no port reassignment, no transaction-model
> change.

## Context

`payload/sources/**/*.cs` are broker **contract surfaces**. On 2026-05-25 an
agent broke them (port 48885→48887 reassignment + NopFP injection into the
transaction path); it was reverted, and `tools/cs_tripwire.ps1` +
`ARCHHUB_ALLOW_CS_EDIT` were added as a tripwire so any `.cs` drift needs an
AgDR + the founder's sign-off.

The live defect (AcadMCPApp.cs at HEAD `45e4d0c`):

- **Line 34** — `private const string ListenPrefix = "http://localhost:48885/";`
  A single hardcoded port.
- **Lines 66-78 `RunListenerAsync`** —
  ```
  _listener = new HttpListener();
  _listener.Prefixes.Add(ListenPrefix);
  _listener.Start();                      // throws HttpListenerException 183
  ...catch { Log("Listener.Start failed: " + ex); return; }   // gives up
  ```
  On a stale `http.sys` URL ACL/reservation (error 183 — "Cannot create a file
  when that file already exists"), `Start()` throws, the catch logs and
  `return`s, and the broker is dead until a human runs `NETLOAD` again. No
  retry, no alternate port, no session file.
- There was **no `WriteSessionFile` / heartbeat** anywhere in the file, even
  though `app/acad_broker.py` has *expected* one since v0.3 ("AcadMCP.dll v0.3+
  writes a session file when it loads, with port + pid + drawing path +
  heartbeat") and prunes sessions silent > 30s.

The Revit broker already fixed this exact class. `RevitMCPCore.CoreEntry`
(`payload/sources/revit_mcp_core/RevitMCPCore.cs`):

- Lines 61-62 — `PortFirst = 48884; PortLast = 48899;`
- Lines 103-110 — `for (p = PortFirst..PortLast) { lis = new HttpListener();
  lis.Prefixes.Add("http://localhost:"+p+"/"); try { lis.Start(); ...; break; }
  catch { /* port taken, try next */ } }`; throws only if none bind.
- Lines 130-133, 438-486 — `WriteSessionFile` (atomic tmp + `File.Replace`) +
  a 10s `System.Threading.Timer` heartbeat; file deleted in `Stop()`.

`app/acad_broker.py` is the Python consumer and already mirrors
`revit_broker` exactly: it scans `autocad-*.json`, port-range probes
48885..48899 (`PORT_FIRST`/`PORT_LAST`), and verifies `/ping`'s
`service == "acad-mcp"`. So both the additive endpoints (port scan + session
file) land into an already-waiting reader.

## Options Considered

| # | Option | Verdict |
|---|--------|---------|
| 1 | **Additive: widen 48885→48885..48899 scan + retry, add session-file + heartbeat, mirror Revit.** Canonical 48885 stays the first port tried; transaction model untouched. | **CHOSEN** — fixes the class, mirrors a proven pattern, satisfies the broker's existing expectations, fully additive (git diff = 136 ins / 8 del, the 8 dels are only the single-port bind becoming retry-next-port). |
| 2 | Reassign AcadMCP to a different fixed port to dodge the stale reservation | REJECTED — destructive canonical-port change; this is the exact 2026-05-25 incident class. |
| 3 | Pre-delete the stale `http.sys` URL ACL via `netsh http delete urlacl` from the Python side before NETLOAD | REJECTED — symptom patch (whack-a-mole on one instance), needs elevation, doesn't give multi-session support, and leaves the broker brittle to the next reservation. |
| 4 | Catch + retry the SAME single port in a sleep loop | REJECTED — a stale reservation doesn't clear on its own; busy-waiting one port never recovers and adds startup latency. |

## Decision

Apply Option 1 — the minimal additive edit to `AcadMCPApp.cs`:

1. Replace the single `const string ListenPrefix` with a range pair +
   discovered-port/session fields, keeping **48885 as the canonical range
   start** (non-destructive):
   `PortFirst = 48885`, `PortLast = 48899`, `HeartbeatSeconds = 10`,
   `int _port`, `string _sessionFile`, `Timer _heartbeat`.
2. Rewrite ONLY the bind block at the top of `RunListenerAsync` into a
   scan+retry loop (the sole permitted deletion: `return`-on-failure →
   retry-next-port). The accept loop below it is untouched.
3. Add `WriteSessionFile` / `HeartbeatTick` / `WriteSessionJson` — atomic
   tmp + `File.Replace` write of `autocad-<pid>.json` with the exact keys
   `acad_broker._read()` consumes (`session_id`, `family`, `pid`, `port`,
   `version`, `doc_title`, `started_at`, `last_heartbeat`, `heartbeat`),
   refreshed every 10s.
4. `Terminate()` disposes the heartbeat + deletes the session file (clean
   prune on unload), mirroring `CoreEntry.Stop`.
5. `/ping` now also returns `port` + `pid` so `acad_broker`'s port-range
   discovery can populate `Session` metadata for instances found without a
   session file. (Additive to the JSON; `service`/`version` unchanged.)

The transaction model (`RunCSharpScript`, `DocumentLock`, `StartTransaction`,
`OnIdle` work pump, `RouteAsync` dispatch) is byte-for-byte unchanged.

### LOAD (auto-load mechanism) — verified already complete, no change applied

The intended permanent auto-load for AutoCAD is the per-profile demand-load
registry key. It was inspected on the live machine (AutoCAD 2026 = R25.1) and
is **already present and correct**:

```
HKCU\Software\Autodesk\AutoCAD\R25.1\ACAD-9101:409\Applications\ArchHub_AcadMCP
  DESCRIPTION = "ArchHub AutoCAD MCP"
  LOADER      = C:\Users\fargaly\AppData\Local\ArchHub\AutoCAD\2026\AcadMCP.dll
  LOADCTRLS   = 14    (load on startup + on demand)
  MANAGED     = 1
```

So `load_action = fix-existing is already complete` — the demand-load autoload
the chat_window UI references is real, points at the deployed DLL, and needs
no change. The COM `_NETLOAD` self-heal in `app/connector_health.py`
(`_try_acad_netload`, 5s/30s/5min backoff) remains the runtime fallback for an
already-open AutoCAD; with this build it will succeed on the first retry
instead of silently dying, and the session file then lets `acad_broker` route
without even needing the port probe.

Anomaly flagged (NOT changed — inert + live AutoCAD has A-200 open): a stray
duplicate `ArchHub_AcadMCP` key sits under the non-profile `Update` node
(`R25.1\Update\Applications\ArchHub_AcadMCP`). AutoCAD only reads `Applications`
under the active profile (`ACAD-9101:409`), so this entry is never loaded —
harmless clutter from a prior writer. Reversible one-liner to clean it when
AutoCAD is next closed (documented, not executed):
`Remove-Item -Path 'HKCU:\Software\Autodesk\AutoCAD\R25.1\Update\Applications\ArchHub_AcadMCP' -Recurse`

## Consequences

- **AutoCAD broker survives a stale `http.sys` reservation** — it falls through
  to the next free port in 48885..48899 instead of dying, killing the
  "manual NETLOAD required" class for this cause.
- **Multi-session AutoCAD now works** — two AutoCAD instances bind two ports;
  each writes its own `autocad-<pid>.json`; `acad_broker.list_sessions`
  returns both. Previously the second instance's bind on 48885 collided.
- **The broker discovers AcadMCP without a port sweep** — the session file is
  the fast path; the heartbeat keeps it live (10s << 30s prune window).
- **`/ping` carries `port`+`pid`** so port-range-discovered sessions get real
  metadata.
- **Cost**: a `System.Threading.Timer` ticking every 10s + one small atomic
  file write per tick — negligible, identical to what Revit already runs.
- **Reversibility**: `git checkout -- payload/sources/acad_mcp/AcadMCPApp.cs`
  + rebuild reverts the code; the session file is deleted on `Terminate()` or
  pruned by the broker after 30s; the registry autoload was not touched.

## Incident-safety note (2026-05-25 boundary)

- **Additive only.** `git diff --numstat` = `136 insertions, 8 deletions`. The
  8 deleted lines are exclusively the `const ListenPrefix`, its one log
  reference, and the single-port `try { Add(ListenPrefix); Start(); } catch {
  return; }` becoming the scan+retry loop — i.e. the one explicitly-permitted
  deletion ("a return-on-failure becoming a retry-next-port").
- **Canonical port preserved.** 48885 remains the FIRST port attempted
  (`PortFirst = 48885`). No port was reassigned. This is the opposite of the
  2026-05-25 48885→48887 change.
- **Transaction model untouched.** `RunCSharpScript` / `DocumentLock` /
  `StartTransaction` / `Commit` / `Abort` are byte-for-byte identical. No
  NopFP or any other injection into the exec path.
- **Tripwire honored.** Edited under `ARCHHUB_ALLOW_CS_EDIT=1` (founder "fix
  them" sign-off). `tools/cs_tripwire.ps1` returns exit 0 ("drift is
  approved") for the single flagged file `payload/sources/acad_mcp/AcadMCPApp.cs`.

## Artifacts

- `payload/sources/acad_mcp/AcadMCPApp.cs` — the additive listener-retry +
  session-file fix (this AgDR).
- `payload/sources/acad_mcp/build-manifest.json` — `sha256` pin reset to `{}`
  then re-recorded to the freshly-built DLL (`3f975c6d6be1037c624bf573401279470636765ebf09f1f8f222d5e23ae66e9c`)
  by `auto_build._record_build_shas` (record_shas_on_build: true).
- `payload/autocad/2026/AcadMCP.dll` — rebuilt clean via
  `python app/auto_build.py acad 2026` (0 errors; 3 benign MSB3277
  reference-unification warnings).
- Verification: `cs_tripwire.ps1` exit 0; `pytest tests/test_broker_connectors.py
  tests/test_broker_cache.py tests/test_connector_build.py` → 90 passed.
