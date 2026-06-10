"""Ownership guard on Revit connector manifest auto-clean (2026-06-10).

Root cause pinned here: test ArchHub instances run with LOCALAPPDATA
redirected to a temp profile clone (the founder-state repro trick), so
their staged dir (`APP_DIR/Revit/<year>`) is empty — but %APPDATA% is NOT
redirected, so `_addin_path` resolves to the REAL install's manifest.
`_RevitSpec.is_active`'s unconditional "auto-clean stale manifest" made
every running clone repeatedly delete the founder's live RevitMCP.addin
within seconds of it being written.

Pins:
  - is_active does NOT unlink a manifest pointing at a FOREIGN staged dir
  - is_active still unlinks a manifest it owns when the DLL is gone
  - deactivate refuses to unlink a foreign manifest
  - deactivate removes its own manifest
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
for p in (str(APP), str(APP / "connectors")):
    if p not in sys.path:
        sys.path.insert(0, p)

from connectors import registry  # noqa: E402
from manager import ConnectorEntry  # noqa: E402


def _entry(year: str = "2023") -> ConnectorEntry:
    return ConnectorEntry(id=f"revit-{year}", display_name=f"Revit {year}",
                          short_letter="R", family="revit", version=year)


def _write_manifest(addin_dir: Path, year: str, assembly_dir: Path) -> Path:
    addin = addin_dir / "Autodesk" / "Revit" / "Addins" / year / "RevitMCP.addin"
    addin.parent.mkdir(parents=True, exist_ok=True)
    addin.write_text(
        "<?xml version=\"1.0\"?><RevitAddIns><AddIn Type=\"Application\">"
        f"<Assembly>{assembly_dir / 'RevitMCP.dll'}</Assembly>"
        "</AddIn></RevitAddIns>", encoding="utf-8")
    return addin


def test_is_active_spares_foreign_manifest(tmp_path, monkeypatch):
    """A clone profile (own empty APP_DIR) must NOT delete the real
    install's manifest, which points at the REAL staged dir."""
    real_staged_root = tmp_path / "real_localappdata" / "ArchHub"
    clone_app_dir = tmp_path / "clone_localappdata" / "ArchHub"
    appdata = tmp_path / "roaming"

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(registry, "APP_DIR", clone_app_dir)

    # Real install's manifest points at the REAL staged dir (which the
    # clone cannot see as its own).
    addin = _write_manifest(appdata, "2023",
                            real_staged_root / "Revit" / "2023")

    spec = registry._RevitSpec()
    assert spec.is_active(_entry()) is False   # clone is not active...
    assert addin.exists(), \
        "clone auto-clean deleted the real install's manifest"


def test_is_active_cleans_own_stale_manifest(tmp_path, monkeypatch):
    """The owning profile still auto-cleans its own manifest when the
    staged DLL is gone."""
    app_dir = tmp_path / "localappdata" / "ArchHub"
    appdata = tmp_path / "roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(registry, "APP_DIR", app_dir)

    addin = _write_manifest(appdata, "2023", app_dir / "Revit" / "2023")
    # No DLL staged → stale.
    spec = registry._RevitSpec()
    assert spec.is_active(_entry()) is False
    assert not addin.exists(), "own stale manifest should be auto-cleaned"


def test_is_active_true_when_manifest_and_dll_present(tmp_path, monkeypatch):
    app_dir = tmp_path / "localappdata" / "ArchHub"
    appdata = tmp_path / "roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(registry, "APP_DIR", app_dir)

    staged = app_dir / "Revit" / "2023"
    staged.mkdir(parents=True)
    (staged / "RevitMCP.dll").write_bytes(b"dll")
    _write_manifest(appdata, "2023", staged)

    spec = registry._RevitSpec()
    assert spec.is_active(_entry()) is True


def test_deactivate_spares_foreign_manifest(tmp_path, monkeypatch):
    real_staged_root = tmp_path / "real_localappdata" / "ArchHub"
    clone_app_dir = tmp_path / "clone_localappdata" / "ArchHub"
    appdata = tmp_path / "roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(registry, "APP_DIR", clone_app_dir)

    addin = _write_manifest(appdata, "2023",
                            real_staged_root / "Revit" / "2023")
    spec = registry._RevitSpec()
    spec.deactivate(_entry())
    assert addin.exists(), \
        "clone deactivate deleted the real install's manifest"


def test_deactivate_removes_own_manifest(tmp_path, monkeypatch):
    app_dir = tmp_path / "localappdata" / "ArchHub"
    appdata = tmp_path / "roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(registry, "APP_DIR", app_dir)

    addin = _write_manifest(appdata, "2023", app_dir / "Revit" / "2023")
    spec = registry._RevitSpec()
    spec.deactivate(_entry())
    assert not addin.exists()
