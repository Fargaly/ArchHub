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
        if not src_dir.exists() or not (src_dir / "RevitMCP.dll").exists():
            raise RuntimeError(f"payload missing for Revit {year}: DLL not built yet.")
        dst_dir = self._staged_dir(year)

        # If the staged directory already has the same RevitMCP.dll
        # we'd be copying, skip the overwrite entirely. Revit holds
        # the DLL open while it's running, so a blind rmtree here
        # raises WinError 5. Idempotent stage = re-toggling Revit ON
        # while it's open just re-writes the addin manifest.
        src_dll = src_dir / "RevitMCP.dll"
        dst_dll = dst_dir / "RevitMCP.dll"
        if not (dst_dll.exists() and self._same_file(src_dll, dst_dll)):
            try:
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.copytree(src_dir, dst_dir)
            except PermissionError:
                # Revit is open and has the previous DLL loaded. The
                # already-staged copy is functional (it loaded once;
                # it works for this session). Don't refuse the toggle —
                # write the addin manifest so the connector goes live
                # against the existing DLL. Next architect-side restart
                # of Revit will pick up the fresh build automatically
                # because the .addin path is stable.
                if not dst_dll.exists():
                    raise        # genuinely no DLL on disk = real failure
                # else: silent fall-through, addin manifest below.

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

    @staticmethod
    def _same_file(a: Path, b: Path) -> bool:
        """Cheap fingerprint compare — size + first 4 KB. Avoids
        reading the whole DLL just to decide if a copy is needed."""
        try:
            if a.stat().st_size != b.stat().st_size:
                return False
            with a.open("rb") as fa, b.open("rb") as fb:
                return fa.read(4096) == fb.read(4096)
        except OSError:
            return False

    def deactivate(self, entry: ConnectorEntry) -> None:
        year = entry.version or ""
        addin = self._addin_path(year)
        if not addin.exists():
            return
        # Same ownership guard as is_active: a profile (e.g. a temp test
        # clone with LOCALAPPDATA redirected) may only remove a manifest
        # that points into ITS OWN staged dir — never the real install's.
        try:
            mine = str(self._staged_dir(year)).lower() in \
                addin.read_text(encoding="utf-8").lower()
        except OSError:
            mine = False
        if mine:
            addin.unlink()

    def is_active(self, entry: ConnectorEntry) -> bool:
        year = entry.version or ""
        addin = self._addin_path(year)
        if not addin.exists():
            return False
        # DLL must also exist — if missing, clean up the stale manifest.
        # OWNERSHIP GUARD (2026-06-10): only unlink a manifest whose
        # <Assembly> points into THIS profile's staged dir. Test instances
        # run with LOCALAPPDATA redirected to a temp clone (the founder-state
        # repro trick), so their staged dir is empty — but %APPDATA% is NOT
        # redirected, so `addin` here is the REAL install's manifest. The
        # unconditional unlink made every running test clone repeatedly
        # delete the founder's live Revit connector manifests.
        dll = self._staged_dir(year) / "RevitMCP.dll"
        if not dll.exists():
            try:
                mine = str(self._staged_dir(year)).lower() in \
                    addin.read_text(encoding="utf-8").lower()
            except OSError:
                mine = False
            if mine:
                try:
                    addin.unlink()
                except OSError:
                    pass
            return False
        return True


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
            raise RuntimeError(f"payload missing for AutoCAD {year}")
        dst_dir = self._staged_dir(year)

        # Same locked-DLL guard as Revit: if AutoCAD is open and our
        # AcadMCP.dll already matches, skip the copy. Re-toggling
        # while AutoCAD is running just re-asserts the registry
        # auto-load entry.
        src_dll = src_dir / "AcadMCP.dll"
        dst_dll = dst_dir / "AcadMCP.dll"
        if not (dst_dll.exists() and _RevitSpec._same_file(src_dll, dst_dll)):
            try:
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.copytree(src_dir, dst_dir)
            except PermissionError:
                # Same logic as Revit: AutoCAD running with previous
                # build of the DLL — the loaded copy works. Skip the
                # overwrite, fall through to (re-)register the auto-load
                # entry. Fresh build picks up on the next AutoCAD start.
                if not dst_dll.exists():
                    raise

        # Register HKCU auto-load entry
        try:
            import winreg
            dll = str(dst_dir / "AcadMCP.dll")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_ROOT, 0, winreg.KEY_READ) as root:
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

    def _user_target(self, entry: ConnectorEntry) -> Path:
        # Per-user startup dir — Max loads from here without admin
        # rights. Was: install dir under Program Files (admin only).
        year = entry.version or ""
        local = Path(os.environ.get("LOCALAPPDATA",
                                     str(Path.home() / "AppData" / "Local")))
        return (local / "Autodesk" / "3dsMax"
                / f"{year} - 64bit" / "ENU" / "scripts" / "startup"
                / "max_mcp_startup.py")

    def _src(self, payload_dir: Path) -> Path:
        # Sources live under payload/sources/max_mcp/. Old code looked
        # at payload/max/ which never existed — caused the
        # "payload missing for 3ds Max" toggle failure.
        return payload_dir / "sources" / "max_mcp" / "max_mcp_startup.py"

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        src = self._src(payload_dir)
        if not src.exists():
            raise RuntimeError("payload missing for 3ds Max")
        target = self._user_target(entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        # Best-effort secondary copy to install dir (admin machines).
        try:
            install_target = entry.detected_path / "scripts" / "startup" / "max_mcp_startup.py"
            install_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, install_target)
        except (PermissionError, OSError):
            pass

    def deactivate(self, entry: ConnectorEntry) -> None:
        for t in (self._user_target(entry),
                  entry.detected_path / "scripts" / "startup" / "max_mcp_startup.py"):
            try:
                if t.exists():
                    t.unlink()
            except (PermissionError, OSError):
                pass

    def is_active(self, entry: ConnectorEntry) -> bool:
        return self._user_target(entry).exists()


# ---------------------------------------------------------------------------
class _BlenderSpec:
    family = "blender"

    def _target(self, entry: ConnectorEntry) -> Path:
        return entry.detected_path / "scripts" / "addons" / "archhub_mcp"  # type: ignore[union-attr]

    def activate(self, entry: ConnectorEntry, payload_dir: Path) -> None:
        src = payload_dir / "blender" / "archhub_mcp"
        if not src.exists():
            raise RuntimeError("payload missing for Blender")
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
