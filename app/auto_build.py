"""Auto-build connector binaries on demand.

When the user toggles a connector ON and the payload binary is missing, this
module builds it in the background. The user never opens a terminal.

Public surface:
    detect_dotnet_sdk()                 -> str | None  (version like "8.0.405" or None)
    download_dotnet_installer(target)   -> Path        (downloads .NET 8 SDK installer)
    find_revit_install(year)            -> Path | None
    find_autocad_install(year)          -> Path | None
    find_max_install(year)              -> Path | None
    build_revit_connector(year, ...)    -> BuildResult
    build_acad_connector(year, ...)     -> BuildResult
    install_max_connector(year, ...)    -> BuildResult  (no compile — just file copy)

All build_* functions accept an `on_progress(stage, percent, line)` callback so
the UI can stream progress without polling.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Where the bundled C# sources live, and where built binaries land. Both
# match manager.py's PAYLOAD_DIR — sibling of app/, not nested under it.
APP_ROOT = Path(__file__).resolve().parent
PAYLOAD_DIR = APP_ROOT.parent / "payload"
SOURCES_DIR = PAYLOAD_DIR / "sources"


# Type for the progress callback: (stage_name, percent_0_to_100, optional_log_line)
ProgressFn = Callable[[str, int, str], None]


@dataclass
class BuildResult:
    success: bool
    detail: str
    artifacts: list[Path]


# ---------------------------------------------------------------------------
# .NET SDK detection / install
# ---------------------------------------------------------------------------

_DOTNET_8_INSTALLER_URL = (
    "https://download.visualstudio.microsoft.com/download/pr/"
    "76e5dbb2-6ae3-4629-9a84-527f8feb709c/"
    "df6e7437f1d8f2b7c0b1e3a31b9b80fe/"
    "dotnet-sdk-8.0.405-win-x64.exe"
)


def _dotnet_exe() -> str:
    """Resolve the dotnet executable path. PATH lookup first; common
    install locations second. Necessary because pythonw subprocesses
    sometimes inherit a stripped PATH that doesn't include
    `C:\\Program Files\\dotnet\\`, which made `dotnet --list-sdks`
    fail silently and the Add Host page show ".NET SDK · not detected"
    on machines that DO have .NET installed."""
    import shutil
    found = shutil.which("dotnet")
    if found:
        return found
    for guess in (
        r"C:\Program Files\dotnet\dotnet.exe",
        r"C:\Program Files (x86)\dotnet\dotnet.exe",
    ):
        if os.path.exists(guess):
            return guess
    return "dotnet"   # let subprocess raise FileNotFoundError


def detect_dotnet_sdk() -> Optional[str]:
    """Return the highest installed .NET SDK version, or None."""
    try:
        # CREATE_NO_WINDOW prevents a console flash when called from
        # pythonw GUI contexts (e.g. the Add Host page on launch).
        kw: dict = dict(capture_output=True, text=True, timeout=10)
        if sys.platform == "win32":
            kw["creationflags"] = getattr(
                subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run([_dotnet_exe(), "--list-sdks"], **kw)
        if proc.returncode != 0:
            return None
        # Each line looks like "8.0.405 [C:\Program Files\dotnet\sdk]"
        # OR "10.0.100-rc.1.25451.107 [...]" for preview SDKs. Accept
        # both — `line[0].isdigit()` already handles the prefix-digit
        # check, and `line.split()[0]` keeps the full version string
        # including the -rc suffix.
        versions = [line.split()[0] for line in proc.stdout.splitlines()
                    if line.strip() and line[0].isdigit()]
        return max(versions) if versions else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


_NET48_DEVPACK_URL = (
    "https://download.visualstudio.microsoft.com/download/pr/"
    "2d6bb6b2-226a-4baa-bdec-798822606ff1/8494001c276a4b96804cde7829c04d7f/"
    "ndp48-devpack-enu.exe"
)


def detect_net48_targeting_pack() -> bool:
    """Return True if the .NET Framework 4.8 targeting/developer pack is installed."""
    # Primary check: reference assemblies on disk (installed by dev pack)
    ref = Path(r"C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.8")
    if ref.is_dir() and any(ref.glob("*.dll")):
        return True
    # Secondary: registry Release flag >= 528040 means .NET 4.8 runtime installed,
    # but NOT necessarily the targeting pack. Only trust if ref assemblies also exist.
    return False


def download_net48_devpack(dest_dir: Path,
                           on_progress: Optional[ProgressFn] = None) -> Path:
    """Download the .NET Framework 4.8 Developer Pack (~115 MB). Returns .exe path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "ndp48-devpack.exe"
    if target.exists() and target.stat().st_size > 10_000_000:
        if on_progress:
            on_progress("Dev Pack cached", 100, str(target))
        return target

    def report(blocks: int, block_size: int, total_size: int) -> None:
        if on_progress and total_size > 0:
            pct = int(100 * blocks * block_size / total_size)
            mb_done = blocks * block_size / 1_048_576
            mb_total = total_size / 1_048_576
            on_progress(
                "Downloading .NET 4.8 Developer Pack",
                min(pct, 99),
                f"{mb_done:.0f} / {mb_total:.0f} MB",
            )

    urllib.request.urlretrieve(_NET48_DEVPACK_URL, target, reporthook=report)
    if on_progress:
        on_progress("Downloaded", 100, str(target))
    return target


def install_net48_devpack(installer_path: Path,
                          on_progress: Optional[ProgressFn] = None) -> bool:
    """Run the .NET 4.8 Developer Pack installer silently. Returns True on success."""
    if on_progress:
        on_progress("Installing .NET 4.8 Developer Pack", 0,
                    "This takes ~1 minute. Please wait…")
    try:
        proc = subprocess.run(
            [str(installer_path), "/q", "/norestart"],
            timeout=300,
        )
        ok = proc.returncode in (0, 3010)  # 3010 = success, reboot pending
        if on_progress:
            on_progress(
                "Installed" if ok else "Install failed",
                100,
                f"exit code {proc.returncode}",
            )
        return ok
    except subprocess.TimeoutExpired:
        return False


def download_dotnet_installer(dest_dir: Path,
                              on_progress: Optional[ProgressFn] = None) -> Path:
    """Download the .NET 8 SDK installer to dest_dir. Returns the .exe path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "dotnet-sdk-8.exe"

    def report(blocks: int, block_size: int, total_size: int) -> None:
        if on_progress and total_size > 0:
            pct = int(100 * blocks * block_size / total_size)
            on_progress("Downloading .NET SDK", min(pct, 100), "")

    urllib.request.urlretrieve(_DOTNET_8_INSTALLER_URL, target, reporthook=report)
    return target


def install_dotnet_sdk(installer_path: Path,
                       on_progress: Optional[ProgressFn] = None) -> bool:
    """Run the .NET SDK installer silently. Returns True on success."""
    if on_progress:
        on_progress("Installing .NET SDK", 0, "Running silent installer…")
    try:
        proc = subprocess.run(
            [str(installer_path), "/install", "/quiet", "/norestart"],
            timeout=600,
        )
        return proc.returncode in (0, 3010)   # 3010 = success, reboot required
    except subprocess.TimeoutExpired:
        return False


# ---------------------------------------------------------------------------
# Autodesk install detection
# ---------------------------------------------------------------------------

def find_revit_install(year: int) -> Optional[Path]:
    candidates = [
        Path(rf"C:\Program Files\Autodesk\Revit {year}"),
        Path(rf"D:\Program Files\Autodesk\Revit {year}"),
    ]
    for c in candidates:
        if (c / "RevitAPI.dll").exists():
            return c
    return None


def find_autocad_install(year: int) -> Optional[Path]:
    # AutoCAD year-to-folder mapping is non-trivial. AutoCAD 2024 = R24.3, 2025 = R25.0,
    # 2026 = R25.1, etc. We probe a few common patterns.
    program_files = [Path(r"C:\Program Files\Autodesk"),
                     Path(r"D:\Program Files\Autodesk")]
    for pf in program_files:
        if not pf.exists(): continue
        for sub in pf.iterdir():
            name = sub.name
            # Matches "AutoCAD 2025", "AutoCAD 2025 - English", etc.
            if name.startswith(f"AutoCAD {year}") and (sub / "AcMgd.dll").exists():
                return sub
    return None


def find_max_install(year: int) -> Optional[Path]:
    candidates = [
        Path(rf"C:\Program Files\Autodesk\3ds Max {year}"),
        Path(rf"D:\Program Files\Autodesk\3ds Max {year}"),
    ]
    for c in candidates:
        if (c / "3dsmax.exe").exists():
            return c
    return None


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

def _target_framework_for_revit(year: int) -> str:
    # Revit 2025+   → .NET 8 (Revit's runtime)
    # Revit 2023/24 → .NET Framework 4.8
    # Revit 2020/21/22 → .NET Framework 4.7 (Revit ships the 4.7 runtime)
    if year >= 2025:
        return "net8.0-windows"
    if year >= 2023:
        return "net48"
    return "net47"


def _target_framework_for_acad(year: int) -> str:
    return "net8.0-windows" if year >= 2025 else "net48"


def _run_dotnet_build(project_path: Path,
                      target_framework: str,
                      msbuild_props: dict,
                      output_dir: Path,
                      on_progress: ProgressFn) -> tuple[bool, str]:
    """Invoke dotnet restore + build, stream stdout to on_progress.

    The explicit restore step matters for net48 builds: the
    Microsoft.NETFramework.ReferenceAssemblies NuGet package only
    works once it's been restored, but `dotnet build` evaluates the
    framework reference assemblies BEFORE the restore step in some
    SDK versions. Doing restore-then-build splits the work in two
    so the build phase has the package available.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    common_props = [f'-p:TargetFramework={target_framework}']
    for k, v in msbuild_props.items():
        common_props.append(f'-p:{k}={v}')

    def _stream(args: list[str], stage: str, base_pct: int) -> tuple[bool, str]:
        on_progress(stage, base_pct, " ".join(args))
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            last = ""
            for line in proc.stdout or []:
                line = line.rstrip()
                if line:
                    last = line
                    on_progress(stage, base_pct + 10, line)
            rc = proc.wait()
            return (rc == 0, last)
        except FileNotFoundError:
            return (False, "dotnet not found on PATH")

    # 1. Restore — pulls Microsoft.NETFramework.ReferenceAssemblies
    #    so net48 builds find their reference assemblies without
    #    requiring the .NET Framework 4.8 Developer Pack.
    restore_args = ["dotnet", "restore", str(project_path)] + common_props
    ok, last = _stream(restore_args, "Restoring NuGet packages", 20)
    if not ok:
        return (False, last or "restore failed")

    # 2. Build — uses --no-restore so we don't redo the work.
    build_args = (["dotnet", "build", str(project_path),
                   "-c", "Release", "--no-restore", "-o", str(output_dir)]
                  + common_props)
    return _stream(build_args, "Compiling", 50)


# ---------------------------------------------------------------------------
# ─── AgDR-0029 — data-driven multi-csproj build pipeline ──────────────
#
# Build glob + manifest gate (Fork A3) + SHA-256 verify (Fork B2).
# Adding a new csproj under any `<host>_mcp*` source root is picked
# up automatically; the manifest declares which DLLs MUST exist after
# deploy so half-builds (shim-without-Core, etc.) fail loudly.

import hashlib  # AgDR-0029 — manifest SHA-256


def _load_build_manifest(connector_source_root: Path) -> dict:
    """Read `<connector_source_root>/build-manifest.json` if present.
    Falls back to a minimal manifest inferred from csproj filenames so
    older connector roots without a manifest still get a deploy gate."""
    p = connector_source_root / "build-manifest.json"
    if p.exists():
        try:
            import json as _json
            return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Inferred fallback: each csproj's basename → expected .dll.
    expected = []
    for proj in connector_source_root.glob("*.csproj"):
        expected.append(proj.stem + ".dll")
    return {"expected_artifacts": expected, "addin_manifests": [],
            "sha256": {}}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_build_output(output_dir: Path, source_roots: list[Path],
                         host_label: str) -> tuple[bool, str, list[str]]:
    """Deploy gate.  Aggregates manifests across every source root for
    a host (e.g. revit_mcp + revit_mcp_core), then verifies each
    expected artifact exists in `output_dir`.  When SHA-256 entries are
    present in any manifest, verifies them too.  Returns
    (ok, error_message, missing_artifacts)."""
    expected: set[str] = set()
    sha_pins: dict[str, str] = {}
    for root in source_roots:
        m = _load_build_manifest(root)
        for art in m.get("expected_artifacts", []) or []:
            expected.add(art)
        for art, sha in (m.get("sha256", {}) or {}).items():
            if sha:
                sha_pins[art] = sha
    missing = [name for name in expected
               if not (output_dir / name).is_file()]
    if missing:
        return (False,
                f"incomplete_build: {host_label} missing " + ", ".join(missing),
                missing)
    # SHA-256 verify only when pins were declared.  Builds without
    # `<Deterministic>true</Deterministic>` can't satisfy this — auto_build
    # writes the sha back into the manifest on first successful build
    # of the connector (`_record_build_shas`).
    mismatches: list[str] = []
    for name, expected_sha in sha_pins.items():
        actual = _sha256_file(output_dir / name)
        if actual.lower() != expected_sha.lower():
            mismatches.append(name)
    if mismatches:
        return (False,
                f"sha_mismatch: {host_label} bytes differ for "
                + ", ".join(mismatches),
                mismatches)
    return (True, "", [])


def _record_build_shas(output_dir: Path, source_roots: list[Path]) -> None:
    """After a clean local build, write SHA-256 of each declared
    artifact back into its own connector's manifest.  Skips entries
    whose `sha256` key is `null` / missing.  Idempotent — running
    twice yields the same content (Deterministic builds)."""
    import json as _json
    for root in source_roots:
        manifest_path = root / "build-manifest.json"
        if not manifest_path.exists():
            continue
        try:
            m = _json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not m.get("record_shas_on_build", False):
            continue
        sha_map = m.get("sha256") or {}
        changed = False
        for art in m.get("expected_artifacts", []) or []:
            dll_path = output_dir / art
            if dll_path.is_file():
                actual = _sha256_file(dll_path)
                if sha_map.get(art) != actual:
                    sha_map[art] = actual
                    changed = True
        if changed:
            m["sha256"] = sha_map
            manifest_path.write_text(
                _json.dumps(m, indent=2) + "\n", encoding="utf-8")


# ─── AgDR-0030 — bundled pinned Roslyn csc.exe ────────────────────────
#
# Fork B3 (signed 2026-05-21): bundle ONCE at
# `%LOCALAPPDATA%\ArchHub\bin\csc\csc.exe`.  Every connector deploy
# inherits it — no per-host duplication.  Downloaded on first connector
# build if missing.  ScriptCompiler probes this path FIRST per Fork A1.

_ROSLYN_TOOLSET_VERSION = "4.11.0"
_ROSLYN_TOOLSET_NUPKG_URL = (
    f"https://www.nuget.org/api/v2/package/"
    f"Microsoft.Net.Compilers.Toolset/{_ROSLYN_TOOLSET_VERSION}"
)


def _bundled_csc_dir() -> Path:
    return (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "ArchHub" / "bin" / "csc")


def ensure_bundled_csc(on_progress=None) -> Path | None:
    """Make sure a pinned modern Roslyn csc.exe sits at
    `%LOCALAPPDATA%\\ArchHub\\bin\\csc\\csc.exe`.  Returns the path
    (whether pre-existing or freshly downloaded) or None on failure.

    Idempotent — does nothing if already present.  Called by every
    `build_*_connector` so the deploy box always has at least ONE
    usable csc, regardless of SDK/BuildTools state."""
    on_progress = on_progress or (lambda *_a, **_kw: None)
    dest_dir = _bundled_csc_dir()
    dest_csc = dest_dir / "csc.exe"
    if dest_csc.exists():
        return dest_csc

    on_progress("Bundling Roslyn csc", 5,
                f"Downloading Microsoft.Net.Compilers.Toolset {_ROSLYN_TOOLSET_VERSION}")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # nupkg = zip — grab + extract just `tasks/net472/csc.exe` (and its
        # sibling DLLs).  net472 build has the standalone csc.exe; the
        # net core build needs `dotnet exec`.
        import io
        import zipfile
        nupkg_bytes = urllib.request.urlopen(
            _ROSLYN_TOOLSET_NUPKG_URL, timeout=120).read()
        with zipfile.ZipFile(io.BytesIO(nupkg_bytes)) as z:
            prefix = "tasks/net472/"
            members = [n for n in z.namelist() if n.startswith(prefix)
                       and not n.endswith("/")]
            for name in members:
                rel = name[len(prefix):]
                target = dest_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        if dest_csc.exists():
            on_progress("Bundled csc ready", 10, str(dest_csc))
            return dest_csc
        on_progress("Bundle failed", 10, "csc.exe missing after extract")
        return None
    except Exception as ex:
        on_progress("Bundle failed", 10, str(ex))
        return None


def _build_dotnet_connector(host_label: str, year: int,
                            sources_glob: str, output_subdir: str,
                            msbuild_props: dict, target_framework: str,
                            on_progress: ProgressFn) -> BuildResult:
    """Build EVERY *.csproj under SOURCES_DIR matching `sources_glob`
    into ONE output dir.  Hard-fails on any individual csproj build
    failure (no half-deploy).  Verifies the deploy manifest after build.

    `sources_glob` example: 'revit_mcp*' (picks revit_mcp +
    revit_mcp_core).  Note: matches DIRECTORIES, then we glob *.csproj
    inside each.
    """
    source_roots = sorted(
        p for p in SOURCES_DIR.glob(sources_glob) if p.is_dir())
    if not source_roots:
        return BuildResult(False,
            f"no source roots match {sources_glob} under {SOURCES_DIR}", [])
    csprojs: list[Path] = []
    for root in source_roots:
        csprojs.extend(sorted(root.glob("*.csproj")))
    if not csprojs:
        return BuildResult(False,
            f"no csprojs found under {[str(r) for r in source_roots]}", [])

    output_dir = PAYLOAD_DIR / output_subdir / str(year)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build every csproj into the SAME output_dir.  AgDR-0027 split
    # forces RevitMCP.dll + RevitMCPCore.dll to land next to each other.
    n = len(csprojs)
    for i, proj in enumerate(csprojs):
        stage_pct = 20 + int(60 * i / n)
        on_progress(f"Building {proj.name}", stage_pct,
                    f"({i + 1}/{n})")
        ok, last = _run_dotnet_build(
            project_path=proj,
            target_framework=target_framework,
            msbuild_props=msbuild_props,
            output_dir=output_dir,
            on_progress=on_progress,
        )
        if not ok:
            return BuildResult(False,
                f"{proj.name}: {last or 'build failed'}", [])

    # Copy any .addin manifests sitting next to a csproj into the
    # same output (Revit needs them paired with the DLL).
    for root in source_roots:
        for addin in root.glob("*.addin"):
            try: shutil.copy2(addin, output_dir / addin.name)
            except Exception: pass

    # Deploy gate — verify expected artifacts + optional SHA-256.
    ok, err, missing = _verify_build_output(output_dir, source_roots, host_label)
    if not ok:
        return BuildResult(False, err, [output_dir / m for m in missing])

    # Record fresh SHA-256s for any manifest opting in.
    _record_build_shas(output_dir, source_roots)

    artifacts = [p for p in output_dir.iterdir() if p.is_file()]
    on_progress("Done", 100, "{} files in {}".format(len(artifacts), output_dir))
    return BuildResult(True, "Built {} files.".format(len(artifacts)), artifacts)


def build_revit_connector(year: int,
                          on_progress=None) -> BuildResult:
    """Build RevitMCP.dll + RevitMCPCore.dll + any other csproj under
    payload/sources/revit_mcp* into payload/revit/<year>/.

    AgDR-0029 — the build is now data-driven: every csproj under
    a `revit_mcp*` dir is built.  When AgDR-0027 split RevitMCP into
    shim + core, this picks up the Core csproj automatically.
    """
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating Revit", 5, "Searching for Revit {}...".format(year))
    revit_dir = find_revit_install(year)
    if revit_dir is None:
        return BuildResult(False, "Revit {} not found in standard locations.".format(year), [])

    on_progress("Checking .NET SDK", 10, "")
    if detect_dotnet_sdk() is None:
        return BuildResult(False, "no_dotnet_sdk", [])

    # AgDR-0030 — make sure a usable Roslyn csc is on this box before
    # we ship a Core that depends on /exec compiling at runtime.
    # Best-effort: if the bundle fails we still build, but the user
    # will get csc_missing on /exec until they install an SDK.
    ensure_bundled_csc(on_progress=on_progress)

    tf = _target_framework_for_revit(year)
    if tf == "net48":
        on_progress("Preparing net48 build", 15,
                    "Using NuGet reference assemblies (no Developer Pack needed)")

    return _build_dotnet_connector(
        host_label="revit",
        year=year,
        sources_glob="revit_mcp*",  # picks revit_mcp + revit_mcp_core
        output_subdir="revit",
        msbuild_props={"RevitInstallDir": str(revit_dir)},
        target_framework=tf,
        on_progress=on_progress,
    )


# ---------------------------------------------------------------------------
def build_acad_connector(year: int,
                         on_progress=None) -> BuildResult:
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating AutoCAD", 5, "Searching for AutoCAD {}...".format(year))
    acad_dir = find_autocad_install(year)
    if acad_dir is None:
        return BuildResult(False, "AutoCAD {} not found.".format(year), [])

    src = SOURCES_DIR / "acad_mcp"
    if not (src / "AcadMCP.csproj").exists():
        return BuildResult(False, "AutoCAD connector source not bundled at {}.".format(src), [])

    on_progress("Checking .NET SDK", 10, "")
    if detect_dotnet_sdk() is None:
        return BuildResult(False, "no_dotnet_sdk", [])

    tf = _target_framework_for_acad(year)

    if tf == "net48" and not detect_net48_targeting_pack():
        cache_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "_prereqs"
        on_progress("Downloading .NET 4.8 Developer Pack", 12,
                    "Required for AutoCAD 2024 and earlier - one-time ~115 MB download")
        try:
            installer = download_net48_devpack(cache_dir, on_progress=on_progress)
        except Exception as ex:
            return BuildResult(False, "Download failed: {}".format(ex), [])
        on_progress("Installing .NET 4.8 Developer Pack", 45, "Running silent installer...")
        ok = install_net48_devpack(installer, on_progress=on_progress)
        if not ok or not detect_net48_targeting_pack():
            return BuildResult(False,
                "net48_install_failed - install may need a reboot. "
                "Restart Windows and toggle the connector again.", [])
        on_progress("Developer Pack installed", 55, "")

    # AgDR-0030 — same bundled csc availability check for AcadMCP.
    ensure_bundled_csc(on_progress=on_progress)

    # AgDR-0029 — data-driven build picks up every csproj under
    # acad_mcp* so a future shim+core split lands without script edits.
    return _build_dotnet_connector(
        host_label="acad",
        year=year,
        sources_glob="acad_mcp*",
        output_subdir="autocad",
        msbuild_props={"AcadInstallDir": str(acad_dir)},
        target_framework=tf,
        on_progress=on_progress,
    )


# ---------------------------------------------------------------------------
def install_max_connector(year: int,
                          on_progress=None) -> BuildResult:
    """3ds Max connector — copy startup scripts into Max's PER-USER
    startup folder (not the install dir).

    3ds Max loads startup scripts from THREE locations on launch:
      1. <install>\\scripts\\startup\\          (Program Files — admin only)
      2. %LOCALAPPDATA%\\Autodesk\\3dsMax\\<year> - 64bit\\ENU\\scripts\\startup\\
      3. %LOCALAPPDATA%\\Autodesk\\3dsMax\\<year> - 64bit\\ENU\\scripts\\Startup\\

    The previous version wrote to (1), which on Windows requires admin
    perms — silent failure when ArchHub runs as a normal user. (2) is
    the right destination per Autodesk docs and per the comment at the
    top of max_mcp_startup.py. We copy to (2) so non-admin installs
    actually work.
    """
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating 3ds Max", 5, "Searching for 3ds Max {}...".format(year))
    max_dir = find_max_install(year)
    if max_dir is None:
        return BuildResult(False, "3ds Max {} not found.".format(year), [])

    src = SOURCES_DIR / "max_mcp"
    if not src.exists():
        return BuildResult(False, "3ds Max connector source not bundled.", [])

    # Per-user startup dir.
    local_app = Path(os.environ.get("LOCALAPPDATA",
                                     str(Path.home() / "AppData" / "Local")))
    startup_dir = (local_app / "Autodesk" / "3dsMax"
                   / f"{year} - 64bit" / "ENU" / "scripts" / "startup")
    on_progress("Preparing startup dir", 20, str(startup_dir))
    startup_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for f in src.iterdir():
        if f.suffix in (".ms", ".py", ".mcr"):
            dst = startup_dir / f.name
            shutil.copy2(f, dst)
            copied.append(dst)
            on_progress("Copying", 60, f.name)

    if not copied:
        return BuildResult(False, "No Max scripts found in source.", [])

    # ALSO copy into the install-dir startup as a fallback (best-effort,
    # silently skips when running as non-admin). Helps in shops where
    # the per-user dir gets pruned by IT.
    install_startup = max_dir / "scripts" / "startup"
    try:
        install_startup.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.suffix in (".ms", ".py", ".mcr"):
                shutil.copy2(f, install_startup / f.name)
    except (PermissionError, OSError):
        pass

    on_progress("Done", 100,
                "{} scripts at {}".format(len(copied), startup_dir))
    return BuildResult(True,
                       "Installed {} scripts to user startup dir.".format(len(copied)),
                       copied)


# ─── AgDR-0029 — CLI entry so batch scripts call one canonical path ──
#
# Replaces the inline `dotnet build` invocations in
# FixAndTestRevit2025.bat / BuildRevit2023.bat with:
#   py app/auto_build.py revit 2025
# Single source of truth: the same code path the Connectors panel uses.
#
# Founder note 2026-05-21: "don't do shortcuts and ruin other work."
# This CLI intentionally writes the SAME progress lines the panel sees,
# so users running the bat get a familiar transcript, and the bat's
# success/failure exit code is honest (0 on green, 1 on any failure).

def _cli_progress(stage: str, pct: int, line: str) -> None:
    msg = f"[{pct:3d}%] {stage}"
    if line:
        msg += f": {line}"
    print(msg, flush=True)


def main(argv=None) -> int:
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2 or argv[0] in ("-h", "--help", "help"):
        print("Usage: py app/auto_build.py <host> <year>")
        print("  host = revit | acad | max")
        return 2
    host = argv[0].lower()
    try:
        year = int(argv[1])
    except ValueError:
        print(f"Year must be an integer; got {argv[1]!r}")
        return 2
    if host == "revit":
        result = build_revit_connector(year, on_progress=_cli_progress)
    elif host in ("acad", "autocad"):
        result = build_acad_connector(year, on_progress=_cli_progress)
    elif host in ("max", "3dsmax", "3ds_max"):
        result = install_max_connector(year, on_progress=_cli_progress)
    else:
        print(f"Unknown host {host!r}; want revit | acad | max")
        return 2

    print()
    if result.success:
        print(f"SUCCESS: {result.detail}")
        if result.artifacts:
            # Windows console codepage may be cp1252 — stick to ASCII.
            print(f"  -> {len(result.artifacts)} artifact(s) in "
                  f"{result.artifacts[0].parent}")
        return 0
    print(f"FAILED: {result.detail}")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
