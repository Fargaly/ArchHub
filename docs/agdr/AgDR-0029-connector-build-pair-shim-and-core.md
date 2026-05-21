---
id: AgDR-0029
timestamp: 2026-05-21T16:00:00Z
agent: claude-code (Sonnet)
session: handoff from prior session (commit eccfc2c) — Bug 1 in deploy machinery
trigger: Founder report — Revit 2025 listener never binds; root cause = auto_build.py.build_revit_connector only invokes dotnet build on the shim csproj, never on RevitMCPCore.csproj.  Half-deployed pair on every end-user Connectors-panel toggle.
status: approved
category: architecture
projects: [archhub, revitmcp, acadmcp]
extends:
  - AgDR-0027 — introduced the shim+core split that this AgDR's build
    pipeline has to support
  - AgDR-0017 — original Revit add-in deploy contract
---

# Data-driven multi-csproj connector build · generic across every .NET host

> Founder demand 2026-05-21: "make sure those bugs won't happen for
> other hosts as well."  Bug 1 today is Revit-only because RevitMCP
> is the only host split into shim+core (AgDR-0027), but every future
> .NET host will get the same split.  Fix at the BUILD-PIPELINE level
> so this class of bug — "a connector ships N DLLs and the build
> script only builds N−1 of them" — can never recur for any host.

## Constraints (signed once founder approves)

1. **No connector ships half-built.**  If any csproj under a
   connector's source root fails to build, the whole connector
   toggle fails.  No half-deploy with a stale or missing Core DLL.
2. **Build is data-driven.**  Adding a new csproj to a connector
   source root (`payload/sources/<host>_mcp*/`) automatically picks
   it up.  No editing `auto_build.py` to wire in each new DLL.
3. **Deploy-time sanity gate.**  Before copying
   `payload/<host>/<year>/` → `%LOCALAPPDATA%\ArchHub\<Host>\<year>\`,
   verify every expected artifact is present + at least as new as
   its source.  Fail loudly with a typed error (named recovery per
   USER-AGENCY MANDATE).
4. **Generic across hosts.**  RevitMCP, AcadMCP, and every future
   .NET host go through the same `_build_dotnet_connector(...)`
   helper.  Host-specific bits (Revit API discovery vs AutoCAD
   API discovery) are injected as callbacks.
5. **Guard test catches the class.**  A parametrised test asserts
   each connector builds EVERY csproj under its source root into a
   single output dir.  Any future host or new DLL trips the test.

## Context — what's there today

`app/auto_build.py`:

```python
def build_revit_connector(year, on_progress=None) -> BuildResult:
    src = SOURCES_DIR / "revit_mcp"
    ...
    output_dir = PAYLOAD_DIR / "revit" / str(year)
    success, last_line = _run_dotnet_build(
        project_path=src / "RevitMCP.csproj",  # ← SHIM ONLY
        ...
    )
    # RevitMCPCore.csproj NEVER BUILT
```

`build_acad_connector` has the same shape — single csproj invocation.
When AcadMCP gets its own shim+core split, the bug will reappear there
verbatim unless the build pipeline is generic by then.

## Decision (proposed)

### Generalised helper

```python
def _build_dotnet_connector(host: str, year: int, sources_glob: str,
                             output_subdir: str, msbuild_props: dict,
                             target_framework: str,
                             on_progress=None) -> BuildResult:
    """Build EVERY *.csproj matching `sources_glob` into one output_dir.
    Hard-fails the whole build on any individual csproj failure."""
    csprojs = sorted(SOURCES_DIR.glob(sources_glob + "/*.csproj"))
    if not csprojs:
        return BuildResult(False, f"no csprojs match {sources_glob}", [])
    output_dir = PAYLOAD_DIR / output_subdir / str(year)
    artifacts: list[Path] = []
    for i, proj in enumerate(csprojs):
        on_progress(f"Building {proj.name}",
                    20 + int(60 * i / len(csprojs)), "")
        ok, last = _run_dotnet_build(project_path=proj,
                                      target_framework=target_framework,
                                      msbuild_props=msbuild_props,
                                      output_dir=output_dir,
                                      on_progress=on_progress)
        if not ok:
            return BuildResult(False,
                f"{proj.name}: {last or 'build failed'}", [])
    artifacts = [p for p in output_dir.iterdir() if p.is_file()]
    return BuildResult(True, f"Built {len(artifacts)} files.", artifacts)
```

`build_revit_connector` / `build_acad_connector` become thin
wrappers that resolve host install dir + delegate:

```python
def build_revit_connector(year, on_progress=None):
    revit_dir = find_revit_install(year)
    if revit_dir is None: return BuildResult(False, "Revit not found", [])
    return _build_dotnet_connector(
        host="revit", year=year,
        sources_glob="revit_mcp*",   # picks revit_mcp + revit_mcp_core
        output_subdir="revit",
        msbuild_props={"RevitInstallDir": str(revit_dir)},
        target_framework=_target_framework_for_revit(year),
        on_progress=on_progress)
```

### Deploy-time sanity gate

After build, before copying artifacts to AppData:

```python
def _verify_deploy_manifest(host, year, output_dir) -> tuple[bool, str]:
    """Check every expected DLL is present + newer than its source.
    Manifest discovered via `<host>_mcp*/build-manifest.json` OR
    inferred from csproj <AssemblyName> if no manifest present."""
```

If verify fails: surface a typed error
`{"error_code": "incomplete_build", "missing": [...]}`.

### Build manifest (per-connector, optional fork — see below)

```json
{
  "expected_artifacts": ["RevitMCP.dll", "RevitMCPCore.dll"],
  "addin_manifests": ["RevitMCP.addin"]
}
```

at `payload/sources/<host>_mcp/build-manifest.json`.  Used by the
deploy gate.  Optional because the csproj `<AssemblyName>` already
tells us the output DLL name.

### Batch scripts (`FixAndTestRevit2025.bat`, etc.)

Re-write as a loop over the same csproj glob.  Or — better — have
the batch script just call `python -m archhub.auto_build revit 2025`
which uses the canonical Python path.

## Forks — signed 2026-05-21

- **Fork A: A3 — Both glob + manifest gate.**  Glob discovers csprojs
  to build; manifest declares the expected output DLLs; deploy gate
  fails if any expected DLL is missing.
- **Fork B: B2 — SHA-256 in manifest.**  Stronger guarantee.  Pair
  with `<Deterministic>true</Deterministic>` added to every csproj so
  same source bytes → identical DLL bytes.
- **Fork C: C1 — Replace bat body with `python -m archhub.auto_build
  revit 2025`.**  Single source of truth.  Founder note 2026-05-21:
  "don't do shortcuts and ruin other work" — implementation MUST verify
  Python-on-PATH detection + fall back to a clear typed error if
  missing rather than silently dying.  Existing shipped bat scripts
  stay byte-identical from the user's perspective (drop in, double-
  click, get build output).

## What ships once approved

- `app/auto_build.py` — new `_build_dotnet_connector` + thin
  per-host wrappers + deploy gate.
- `payload/sources/revit_mcp/build-manifest.json` (if Fork A2/A3).
- `payload/sources/acad_mcp/build-manifest.json` (ditto).
- `FixAndTestRevit2025.bat` updated per Fork C.
- `tests/test_connector_build.py` (new): parametrised over
  `[revit, acad]`, mocks `_run_dotnet_build`, asserts every csproj
  under each connector's source root is invoked + into the same
  output_dir.  Asserts deploy gate fails on missing/stale DLL.
- AcadMCP gets the same treatment now (not just RevitMCP) — the
  helper is host-agnostic.

## What does NOT ship

- Splitting AcadMCP into shim+core (AgDR-0027-equivalent for acad)
  — separate AgDR, separate slice.
- Cross-host parallel build (build Revit + AutoCAD simultaneously)
  — out of scope.

## Acceptance

1. `build_revit_connector(2025)` builds BOTH `RevitMCP.dll` AND
   `RevitMCPCore.dll` into the same `payload/revit/2025/`.
2. Deploy step copies both to `%LOCALAPPDATA%\ArchHub\Revit\2025\`
   and verifies presence + freshness.
3. Removing the Core csproj's build output mid-test → deploy gate
   fails with typed `incomplete_build` error + names the missing
   DLL.
4. Test sweep parametrised over `[revit, acad]` proves every csproj
   under each connector root gets built.
5. Suite green.  Founder confirms via CDP demo.

## Artifacts

- This AgDR.
- Pending implementation listed in §"What ships once approved".
