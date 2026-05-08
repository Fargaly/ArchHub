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
    return "net8.0-windows" if year >= 2025 else "net48"


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
def build_revit_connector(year: int,
                          on_progress=None) -> BuildResult:
    """Build RevitMCP.dll for the given year and copy into payload/revit/<year>/."""
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating Revit", 5, "Searching for Revit {}...".format(year))
    revit_dir = find_revit_install(year)
    if revit_dir is None:
        return BuildResult(False, "Revit {} not found in standard locations.".format(year), [])

    src = SOURCES_DIR / "revit_mcp"
    if not (src / "RevitMCP.csproj").exists():
        return BuildResult(False, "Revit connector source not bundled at {}.".format(src), [])

    on_progress("Checking .NET SDK", 10, "")
    if detect_dotnet_sdk() is None:
        return BuildResult(False, "no_dotnet_sdk", [])

    tf = _target_framework_for_revit(year)

    # For Revit 2023/2024 (net48): the csproj now uses Microsoft.NETFramework.ReferenceAssemblies
    # NuGet package which provides reference assemblies without requiring the Developer Pack.
    # No manual installation needed — dotnet restore pulls it automatically.
    if tf == "net48":
        on_progress("Preparing net48 build", 15,
                    "Using NuGet reference assemblies (no Developer Pack needed)")

    output_dir = PAYLOAD_DIR / "revit" / str(year)
    success, last_line = _run_dotnet_build(
        project_path=src / "RevitMCP.csproj",
        target_framework=tf,
        msbuild_props={"RevitInstallDir": str(revit_dir)},
        output_dir=output_dir,
        on_progress=on_progress,
    )

    if not success:
        return BuildResult(False, last_line or "build failed", [])

    # Copy the .addin manifest (Revit needs both DLL + manifest)
    addin_src = src / "RevitMCP.addin"
    if addin_src.exists():
        shutil.copy2(addin_src, output_dir / "RevitMCP.addin")

    artifacts = [p for p in output_dir.iterdir() if p.is_file()]
    on_progress("Done", 100, "{} files in {}".format(len(artifacts), output_dir))
    return BuildResult(True, "Built {} files.".format(len(artifacts)), artifacts)


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

    output_dir = PAYLOAD_DIR / "autocad" / str(year)
    success, last_line = _run_dotnet_build(
        project_path=src / "AcadMCP.csproj",
        target_framework=tf,
        msbuild_props={"AcadInstallDir": str(acad_dir)},
        output_dir=output_dir,
        on_progress=on_progress,
    )

    if not success:
        return BuildResult(False, last_line or "build failed", [])

    artifacts = [p for p in output_dir.iterdir() if p.is_file()]
    on_progress("Done", 100, "{} files in {}".format(len(artifacts), output_dir))
    return BuildResult(True, "Built {} files.".format(len(artifacts)), artifacts)


# ---------------------------------------------------------------------------
def install_max_connector(year: int,
                          on_progress=None) -> BuildResult:
    """3ds Max connector — no compile needed, just copy scripts into Max startup folder."""
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating 3ds Max", 5, "Searching for 3ds Max {}...".format(year))
    max_dir = find_max_install(year)
    if max_dir is None:
        return BuildResult(False, "3ds Max {} not found.".format(year), [])

    src = SOURCES_DIR / "max_mcp"
    if not src.exists():
        return BuildResult(False, "3ds Max connector source not bundled.", [])

    startup_dir = max_dir / "scripts" / "startup"
    startup_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for f in src.iterdir():
        if f.suffix in (".ms", ".py", ".mcr"):
            dst = startup_dir / f.name
            shutil.copy2(f, dst)
            copied.append(dst)
            on_progress("Copying", 50, "{}".format(f.name))

    if not copied:
        return BuildResult(False, "No Max scripts found in source.", [])

    on_progress("Done", 100, "{} scripts installed".format(len(copied)))
    return BuildResult(True, "Installed {} scripts.".format(len(copied)), copied)
