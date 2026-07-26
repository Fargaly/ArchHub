import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

package_dir = Path(SPECPATH).resolve()
project_root = Path(os.environ.get(
    "ARCHHUB_PROJECT_ROOT", package_dir.parent.parent)).resolve()

hidden_imports = [
    "PyQt6.QtCore",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "cryptography.hazmat.primitives.ciphers.aead",
    "nodelang.baboom_native_companion",
    "nodelang.baboom_native_host",
    "nodelang.baboom_native_runtime",
    "nodelang.baboom_native_visual",
    "nodelang.baboom_native_voice",
    "pythoncom",
    "pywintypes",
    "win32com.client",
]
hidden_imports += collect_submodules("nodelang.domains")

analysis = Analysis(
    [str(package_dir / "entrypoint.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(package_dir / "package-manifest.json"), "."),
        (str(project_root / "nodelang" / "data" / "public_runtime_map.json"),
         "nodelang/data"),
        (str(project_root / "nodelang" / "data" / "baboom" / "spritesheet.png"),
         "nodelang/data/baboom"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ArchHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    version=str(package_dir / "version_info.txt"),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ArchHub",
)
