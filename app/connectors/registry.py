"""Per-family connector specs.

Each spec implements activate(entry, payload_dir) and deactivate(entry) and
is_active(entry). The manager dispatches on entry.family.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Protocol

from manager import APP_DIR, ConnectorEntry


class ConnectorSpec(Protocol):
    family: str
    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None: ...
    def deactivate(self, entry: ConnectorEntry) -> None: ...
    def is_active(self, entry: ConnectorEntry) -> bool: ...


# ---------------------------------------------------------------------------
class _RevitSpec:
    family = "revit"

    @staticmethod
    def _addin_path(year: str) -> Path:
        return Path(os.environ["APPDATA"]) / "Autodesk" / "Revit" / "Addins" / year / "RevitMCP.addin"

    @staticmethod
    def _staged_dir(year: str) -> Path:
        return APP_DIR / "Revit" / year

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        year = entry.version or ""
        src_dir = payload_dir / "revit" / year
        if not src_dir.exists():
            raise RuntimeError(f"No Revit payload for {year}. Build the DLL via the dev kit first.")
        dst_dir = self._staged_dir(year)
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)

        addin = self._addin_path(year)
        addin.parent.mkdir(parents=True, exist_ok=True)
        dll_path = dst_dir / "RevitMCP.dll"
        addin.write_text(f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>RevitMCP</Name>
    <Assembly>{dll_path}</Assembly>
    <FullClassName>RevitMCP.RevitMCPApp</FullClassName>
    <ClientId>9f5c3b6f-2a1c-4e1f-bd0a-7a31c0e22c1d</ClientId>
    <VendorId>FRGL</VendorId>
    <VendorDescription>ArchHub bridge for Claude</VendorDescription>
  </AddIn>
</RevitAddIns>
""", encoding="utf-8")

    def deactivate(self, entry: ConnectorEntry) -> None:
        year = entry.version or ""
        addin = self._addin_path(year)
        if addin.exists():
            addin.unlink()

    def is_active(self, entry: ConnectorEntry) -> bool:
        return self._addin_path(entry.version or "").exists()


# ---------------------------------------------------------------------------
class _AutoCADSpec:
    family = "autocad"
    REG_ROOT = r"Software\Autodesk\AutoCAD"

    @staticmethod
    def _staged_dir(year: str) -> Path:
        return APP_DIR / "AutoCAD" / year

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        year = entry.version or ""
        src_dir = payload_dir / "autocad" / year
        if not src_dir.exists():
            raise RuntimeError(f"No AutoCAD payload for {year}.")
        dst_dir = self._staged_dir(year)
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)

        # Register HKCU auto-load entry
        try:
            import winreg
            dll = str(dst_dir / "AcadMCP.dll")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_ROOT, 0, winreg.KEY_READ) as root:
                # Iterate releases (R24.0, R25.0, etc.)
                i = 0
                while True:
                    try:
                        rel = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    rel_path = f"{self.REG_ROOT}\\{rel}"
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rel_path) as rk:
                        j = 0
                        while True:
                            try:
                                pkey = winreg.EnumKey(rk, j)
                            except OSError:
                                break
                            j += 1
                            apps = f"{rel_path}\\{pkey}\\Applications\\ArchHub_AcadMCP"
                            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, apps) as ak:
                                winreg.SetValueEx(ak, "DESCRIPTION", 0, winreg.REG_SZ, "ArchHub AutoCAD MCP")
                                winreg.SetValueEx(ak, "LOADCTRLS",   0, winreg.REG_DWORD, 14)
                                winreg.SetValueEx(ak, "LOADER",      0, winreg.REG_SZ, dll)
                                winreg.SetValueEx(ak, "MANAGED",     0, winreg.REG_DWORD, 1)
        except Exception as ex:
            raise RuntimeError(f"Could not register AutoCAD auto-load: {ex}")

    def deactivate(self, entry: ConnectorEntry) -> None:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_ROOT, 0, winreg.KEY_READ) as root:
                i = 0
                while True:
                    try:
                        rel = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    rel_path = f"{self.REG_ROOT}\\{rel}"
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rel_path) as rk:
                            j = 0
                            while True:
                                try:
                                    pkey = winreg.EnumKey(rk, j)
                                except OSError:
                                    break
                                j += 1
                                apps = f"{rel_path}\\{pkey}\\Applications\\ArchHub_AcadMCP"
                                try:
                                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, apps)
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except Exception:
            pass

    def is_active(self, entry: ConnectorEntry) -> bool:
        # Cheap probe: registry key present somewhere
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_ROOT, 0, winreg.KEY_READ) as root:
                i = 0
                while True:
                    try:
                        rel = winreg.EnumKey(root, i)
                    except OSError:
                        return False
                    i += 1
                    rel_path = f"{self.REG_ROOT}\\{rel}"
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rel_path) as rk:
                            j = 0
                            while True:
                                try:
                                    pkey = winreg.EnumKey(rk, j)
                                except OSError:
                                    break
                                j += 1
                                apps = f"{rel_path}\\{pkey}\\Applications\\ArchHub_AcadMCP"
                                try:
                                    winreg.OpenKey(winreg.HKEY_CURRENT_USER, apps).Close()
                                    return True
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
class _MaxSpec:
    family = "max"

    def _target(self, entry: ConnectorEntry) -> Path:
        return entry.detected_path / "max_mcp_startup.py"  # type: ignore[union-attr]

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        src = payload_dir / "max" / "max_mcp_startup.py"
        if not src.exists():
            raise RuntimeError("3ds Max payload missing.")
        shutil.copy2(src, self._target(entry))

    def deactivate(self, entry: ConnectorEntry) -> None:
        t = self._target(entry)
        if t.exists():
            t.unlink()

    def is_active(self, entry: ConnectorEntry) -> bool:
        return self._target(entry).exists()


# ---------------------------------------------------------------------------
class _BlenderSpec:
    family = "blender"

    def _target(self, entry: ConnectorEntry) -> Path:
        # User's per-version Blender scripts/addons folder
        return entry.detected_path / "scripts" / "addons" / "archhub_mcp"  # type: ignore[union-attr]

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        src = payload_dir / "blender" / "archhub_mcp"
        if not src.exists():
            raise RuntimeError("Blender payload missing.")
        target = self._target(entry)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, target)

    def deactivate(self, entry: ConnectorEntry) -> None:
        target = self._target(entry)
        if target.exists():
            shutil.rmtree(target)

    def is_active(self, entry: ConnectorEntry) -> bool:
        return self._target(entry).exists()


# ---------------------------------------------------------------------------
class _PassiveSpec:
    """For connectors that need no per-host file installation (Speckle is cloud,
    Fusion's MCP is provided by Autodesk separately, Rhino/SketchUp are stubs
    until their respective payloads are built).

    These connectors register a marker file in APP_DIR/<family>.active so the
    manager can re-render their toggle state, and contribute to the bridge's
    knowledge of which proxies to expose.
    """

    def __init__(self, family: str):
        self.family = family

    def _marker(self, entry: ConnectorEntry) -> Path:
        return APP_DIR / f"{entry.id}.active"

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        m = self._marker(entry)
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({"id": entry.id, "family": entry.family}))

    def deactivate(self, entry: ConnectorEntry) -> None:
        m = self._marker(entry)
        if m.exists():
            m.unlink()

    def is_active(self, entry: ConnectorEntry) -> bool:
        return self._marker(entry).exists()


# ---------------------------------------------------------------------------
_REGISTRY: dict[str, ConnectorSpec] = {
    "revit":    _RevitSpec(),
    "autocad":  _AutoCADSpec(),
    "max":      _MaxSpec(),
    "blender":  _BlenderSpec(),
    "rhino":    _PassiveSpec("rhino"),
    "sketchup": _PassiveSpec("sketchup"),
    "fusion":   _PassiveSpec("fusion"),
    "speckle":  _PassiveSpec("speckle"),
}


def resolve(family: str) -> ConnectorSpec | None:
    return _REGISTRY.get(family)
