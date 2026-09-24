# Host connector build proposal

Status: source promotion complete; build, artifact closure and activation are
not approved by this document. No host binaries are included in this source
directory. The old manifests in `legacy-build-evidence/` are not current pins.

## Explicit inputs for review

| Input | Proposed pin or selection | Evidence status |
|---|---|---|
| .NET SDK | `8.0.405` | Version named by the original build helper; suitability and verified distribution digest need review before use |
| Revit API | Exact selected host year and its `RevitAPI.dll` / `RevitAPIUI.dll` reference hashes | Build input only; do not redistribute host assemblies |
| AutoCAD API | Exact selected host year and its `acmgd.dll`, `acdbmgd.dll`, `accoremgd.dll` reference hashes | Build input only; do not use the project's floating prerelease fallback for a release |
| Reference assemblies | `Microsoft.NETFramework.ReferenceAssemblies`, `.net47` and `.net48`, each `1.0.3` | Declared Revit project dependencies; target-specific package content must be locked |
| Revit JSON, .NET 8 | `System.Text.Json` `8.0.5` | Declared project dependency |
| Revit JSON, older framework | `System.Text.Json` `6.0.10`; `System.Threading.Tasks.Extensions` `4.5.4` | Declared project dependencies |
| AutoCAD JSON | `System.Text.Json` `8.0.5` | Declared project dependency |
| Runtime C# compiler | `Microsoft.Net.Compilers.Toolset` `4.11.0` | Original helper's nominated version; package digest, license and complete runtime closure need review |

These are proposed reproducibility inputs, not assertions that these versions
are current, secure or accepted for release. Resolve and review complete
per-target lock files and package/license hashes before building. Builds must
use the immutable canonical release snapshot and the reviewed lock; a hash
mismatch must fail rather than rewrite approval pins from the current output.

## Target and artifact closure

- Revit's original helper targets 2020–22 with `net47`, 2023–24 with `net48`,
  and 2025 or newer with `net8.0-windows`. Build both projects against the
  selected host API. Proposed installed location: `bridges/revit/<year>/`.
  Its own runtime outputs are `RevitMCP.dll` and `RevitMCPCore.dll`, plus
  applicable generated dependency descriptors and the verified runtime closure.
- AutoCAD's original helper targets versions through 2024 with `net48` and
  2025 or newer with `net8.0-windows`. Proposed installed location:
  `bridges/autocad/<year>/AcadMCP.dll`, plus applicable dependency descriptors
  and the verified runtime closure.
- The Max runtime source remains the single
  `bridges/sources/max_mcp/max_mcp_startup.py`. It requires the host's Python 3,
  `pymxs`, and PySide2 or PySide6. No supported-year matrix has been established.
- Revit and AutoCAD script execution also require a compiler accepting C# 7.3
  or newer. If the proposed toolset is accepted, package its complete required
  `tasks/net472` compiler runtime closure at installed `bin/csc`, with notices
  and verified package/file hashes. `csc.exe` alone is insufficient evidence of
  that closure. Compiler file presence does not prove language compatibility.

Target framework mappings describe existing source, not host acceptance.
Exact transitive runtime files remain unresolved until the locked build is
reviewed. Do not copy old payload directories to fill that gap. Keep compiled
outputs out of source history and bind the generated artifact manifest to the
source revision, target year, toolchain, package lock and artifact hashes.

## Deployment boundary

Deployment must select the exact user and host version, preserve registrations
it does not own, and report partial failures and pending host restarts. Generate
the Revit add-in manifest with the exact installed assembly path; register only
the selected AutoCAD product; use the selected user's Max startup folder.
Do not silently install external host applications, developer packs or URL ACLs,
fall back to Program Files writes, or restart applications.

The existing listeners require a separate custody and authorization review
before activation. A localhost listener, file, registry key or compiler
candidate does not establish graph permission, a loaded connector, successful
execution, or readiness.

## Implementation path to installation

`nodelang.host_broker_installation.install_revit_broker` now implements the
per-user registration operation. Its module documents the release-pinned
artifact manifest and exact selected-host inputs. Setup integration must supply
pins from the verified release, never generate approval from local file hashes.
The module preserves conflicting registrations and reports pending host load;
it is not yet called by setup and no current broker is activation-eligible.

Source inspection found that the promoted Core accepts execution and reload
without authentication. Merely including these binaries in setup would not
complete the product's admitted connector path. The remaining ordered work is:

1. Give the shim a boot identity and each open document an identity retained
   across Core reload, invalidated when that document closes. A title, path or
   port alone must not select an execution target.
2. Connect the physical broker through the existing ApplicationServer transport
   and custody mechanisms. Keep graph permissions in that owner; do not add a
   broker database, agent identity or second authority.
3. Bind the exact approved Work/node material to the existing adapter permission
   and one-use connector grant/receipt protocol. Native agents need their own
   admitted context within that protocol; do not weaken BABOOM-only admission.
4. Verify target identity, permitted operation, digest and expiry on the Revit
   UI thread immediately before the effect. Remove unauthenticated execution
   and reload entry points; bound queues, requests and deadlines. Preserve
   uncertain outcomes instead of replaying them.
5. Build and review the exact runtime closure, then integrate the verified
   manifest with setup and prove selected-user installation and a permitted
   physical operation. Only that evidence can make artifacts eligible.

Arbitrary C# can reach documents other than the context document. Normal node
operations therefore need reviewed operation implementations; document identity
checking alone is not a sandbox for arbitrary scripts.
