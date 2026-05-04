"""Detect locally installed AEC tools and produce ConnectorEntry objects.

Speckle is treated as always available because it's a cloud connector.
Other tools are only listed if found on disk.
"""
from __future__ import annotations

import os
from pathlib import Path

from manager import ConnectorEntry, ConnectorState


# ---------------------------------------------------------------------------
def _scan_autodesk_dir(name_prefix: str, exe_check: str) -> list[tuple[int, Path]]:
    """Return list of (year, install_path) for any Autodesk product whose
    install folder matches `<name_prefix> <year>` and contains `exe_check`.
    """
    results: list[tuple[int, Path]] = []
    for base in (r"C:\Program Files\Autodesk", r"C:\Program Files (x86)\Autodesk"):
        bp = Path(base)
        if not bp.exists():
            continue
        for d in bp.iterdir():
            if not d.is_dir():
                continue
            if not d.name.lower().startswith(name_prefix.lower() + " "):
                continue
            tail = d.name[len(name_prefix) + 1:].strip()
            if not tail.isdigit():
                continue
            if not (d / exe_check).exists():
                continue
            results.append((int(tail), d))
    return sorted(results, reverse=True)


def _detect_revit() -> list[ConnectorEntry]:
    out = []
    for year, path in _scan_autodesk_dir("Revit", "Revit.exe"):
        out.append(ConnectorEntry(
            id=f"revit-{year}",
            display_name=f"Revit {year}",
            short_letter="R",
            family="revit",
            version=str(year),
            detected_path=path,
            state=ConnectorState.READY,
        ))
    return out


def _detect_acad() -> list[ConnectorEntry]:
    out = []
    for year, path in _scan_autodesk_dir("AutoCAD", "acad.exe"):
        out.append(ConnectorEntry(
            id=f"autocad-{year}",
            display_name=f"AutoCAD {year}",
            short_letter="A",
            family="autocad",
            version=str(year),
            detected_path=path,
            state=ConnectorState.READY,
        ))
    return out


def _detect_max() -> list[ConnectorEntry]:
    out = []
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Autodesk" / "3dsMax"
    if not base.exists():
        return out
    for d in base.iterdir():
        if not d.is_dir():
            continue
        # Folder name like "2025 - 64bit"
        parts = d.name.split(" - ")
        if not parts[0].isdigit():
            continue
        year = int(parts[0])
        startup = d / "ENU" / "scripts" / "startup"
        if not startup.exists():
            continue
        out.append(ConnectorEntry(
            id=f"max-{year}",
            display_name=f"3ds Max {year}",
            short_letter="M",
            family="max",
            version=str(year),
            detected_path=startup,
            state=ConnectorState.READY,
        ))
    return sorted(out, key=lambda e: e.version or "", reverse=True)


def _detect_blender() -> list[ConnectorEntry]:
    """Detect Blender by user addons folder."""
    appdata = Path(os.environ.get("APPDATA", ""))
    if not appdata.exists():
        return []
    bf = appdata / "Blender Foundation" / "Blender"
    if not bf.exists():
        return []
    versions = [d for d in bf.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()]
    if not versions:
        return []
    versions.sort(key=lambda d: tuple(int(p) for p in d.name.split(".")), reverse=True)
    latest = versions[0]
    return [ConnectorEntry(
        id="blender",
        display_name=f"Blender {latest.name}",
        short_letter="B",
        family="blender",
        version=latest.name,
        detected_path=latest,
        state=ConnectorState.READY,
    )]


def _detect_rhino() -> list[ConnectorEntry]:
    appdata = Path(os.environ.get("APPDATA", ""))
    rhino_root = appdata / "McNeel" / "Rhinoceros"
    if not rhino_root.exists():
        return []
    versions = [d for d in rhino_root.iterdir() if d.is_dir() and d.name.endswith(".0")]
    if not versions:
        return []
    versions.sort(reverse=True)
    return [ConnectorEntry(
        id="rhino",
        display_name=f"Rhino {versions[0].name.split('.')[0]}",
        short_letter="6",
        family="rhino",
        version=versions[0].name,
        detected_path=versions[0],
        state=ConnectorState.READY,
    )]


def _detect_sketchup() -> list[ConnectorEntry]:
    for base in (r"C:\Program Files\SketchUp", r"C:\Program Files (x86)\SketchUp"):
        bp = Path(base)
        if not bp.exists():
            continue
        for d in bp.iterdir():
            if d.is_dir() and d.name.startswith("SketchUp"):
                return [ConnectorEntry(
                    id="sketchup",
                    display_name=d.name,
                    short_letter="S",
                    family="sketchup",
                    detected_path=d,
                    state=ConnectorState.READY,
                )]
    return []


def _detect_fusion() -> list[ConnectorEntry]:
    """Fusion is per-user: %LOCALAPPDATA%\\Autodesk\\webdeploy\\production\\..."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Autodesk" / "webdeploy" / "production"
    if not base.exists():
        return []
    sub = next((d for d in base.iterdir() if d.is_dir() and (d / "Fusion360.exe").exists()), None)
    if sub is None:
        return []
    return [ConnectorEntry(
        id="fusion",
        display_name="Fusion",
        short_letter="F",
        family="fusion",
        detected_path=sub,
        state=ConnectorState.READY,
    )]


def _detect_speckle() -> list[ConnectorEntry]:
    """Speckle is always present — it's a cloud connector."""
    return [ConnectorEntry(
        id="speckle",
        display_name="Speckle",
        short_letter="◉",
        family="speckle",
        state=ConnectorState.READY,
        detail="cloud",
    )]


# ---------------------------------------------------------------------------
def discover_all() -> list[ConnectorEntry]:
    """Run all detectors and return a flat list of entries.
    Order: Revit, AutoCAD, 3ds Max, Blender, Rhino, SketchUp, Fusion, Speckle.
    """
    found: list[ConnectorEntry] = []
    found.extend(_detect_revit())
    found.extend(_detect_acad())
    found.extend(_detect_max())
    found.extend(_detect_blender())
    found.extend(_detect_rhino())
    found.extend(_detect_sketchup())
    found.extend(_detect_fusion())
    found.extend(_detect_speckle())
    return found
