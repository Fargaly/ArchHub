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


def detect_dotnet_sdk() -> Optional[str]:
    """Return the highest installed .NET SDK version, or None."""
    try:
        proc = subprocess.run(
            ["dotnet", "--list-sdks"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return None
        # Each line looks like "8.0.405 [C:\Program Files\dotnet\sdk]"
        versions = [line.split()[0] for line in proc.stdout.splitlines()
                    if line.strip() and line[0].isdigit()]
        return max(versions) if versions else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


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
    """Invoke dotnet build, stream stdout to on_progress."""
    output_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "dotnet", "build", str(project_path),
        "-c", "Release",
        "-p:TargetFramework=" + target_framework,
        "-o", str(output_dir),
    ]
    for k, v in msbuild_props.items():
        args.append(f'-p:{k}={v}')

    on_progress("Compiling", 30, " ".join(args))
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
                on_progress("Compiling", 60, line)
        rc = proc.wait()
        return (rc == 0, last)
    except FileNotFoundError:
        return (False, "dotnet not found on PATH")


# ---------------------------------------------------------------------------
def build_revit_connector(year: int,
                          on_progress: Optional[ProgressFn] = None) -> BuildResult:
    """Build RevitMCP.dll for the given year and copy into payload/revit/<year>/."""
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating Revit", 5, f"Searching for Revit {year}…")
    revit_dir = find_revit_install(year)
    if revit_dir is None:
        return BuildResult(False, f"Revit {year} not found in standard locations.", [])

    src = SOURCES_DIR / "revit_mcp"
    if not (src / "RevitMCP.csproj").exists():
        return BuildResult(False,
                           f"Revit connector source not bundled at {src}.", [])

    on_progress("Checking .NET SDK", 10, "")
    if detect_dotnet_sdk() is None:
        return BuildResult(False, "no_dotnet_sdk", [])

    output_dir = PAYLOAD_DIR / "revit" / str(year)
    success, last_line = _run_dotnet_build(
        project_path=src / "RevitMCP.csproj",
        target_framework=_target_framework_for_revit(year),
        msbuild_props={"RevitInstallDir": str(revit_dir)},
        output_dir=output_dir,
        on_progress=on_progress,
    )

    if not success:
        return BuildResult(False, last_line or "build failed", [])

    # Copy the .addin manifest alongside (Revit needs both)
    addin_src = src / "RevitMCP.addin"
    if addin_src.exists():
        shutil.copy2(addin_src, output_dir / "RevitMCP.addin")

    artifacts = [p for p in output_dir.iterdir() if p.is_file()]
    on_progress("Done", 100, f"{len(artifacts)} files in {output_dir}")
    return BuildResult(True, f"Built {len(artifacts)} files.", artifacts)


# ---------------------------------------------------------------------------
def build_acad_connector(year: int,
                         on_progress: Optional[ProgressFn] = None) -> BuildResult:
    on_progress = on_progress or (lambda *_a, **_kw: None)

    on_progress("Locating AutoCAD", 5, f"Searching for AutoCAD {year}…")
    acad_dir = find_autocad_install(year)
    if acad_dir is None:
        return BuildResult(False, f"AutoCAD {year} not found.", [])

    src = SOURCES_DIR / "acad_mcp"
    if not (src / "AcadMCP.csproj").exists():
        return BuildResult(False,
                           f"AutoCAD connector source not bundled at {src}.", [])

    on_progress("Checking .NET SDK", 10, "")
    if detect_dotnet_sdk() is None:
        return BuildResult(False, "no_dotnet_sdk", [])

    output_dir = PAYLOAD_DIR / "autocad" / str(year)
    success, last_line = _run_dotnet_build(
        project_path=src / "AcadMCP.csproj",
        target_framework=_target_framework_for_acad(year),
        msbuild_props={"AcadInstallDir": str(acad_dir)},
        output_dir=output_dir,
        on_progress=on_progress,
    )

    if not success:
        return BuildResult(False, last_line or "build failed", [])

    artifacts = [p for p in output_dir.iterdir() if p.is_file()]
    on_progress("Done", 100, f"{len(artifacts)} files in {output_dir}")
    return BuildResult(True, f"Built {len(artifacts)} files.", artifacts)


# ---------------------------------------------------------------------------
def install_max_connector(year: int,
                          on_progress: Optional[ProgressFn] = None) -> BuildResult:
    """3ds Max connector is pure Python — no compilation. Just file copy."""
    on_progress = on_progress or (lambda *_a, **_kw: None)

    src = SOURCES_DIR / "max_mcp"
    if not src.exists() or not any(src.iterdir()):
        return BuildResult(False, f"3ds Max connector source not bundled at {src}.", [])

    output_dir = PAYLOAD_DIR / "max" / str(year)
    output_dir.mkdir(parents=True, exist_ok=True)

    on_progress("Copying scripts", 30, "")
    copied = []
    for p in src.iterdir():
        if p.is_file():
            dst = output_dir / p.name
            shutil.copy2(p, dst)
            copied.append(dst)

    on_progress("Done", 100, f"Copied {len(copied)} files.")
    return BuildResult(True, f"Installed {len(copied)} files.", copied)
