"""Blender runner.

Knows how to:
  - find Blender's executable on the user's machine
  - find the user's Blender addons folder
  - install (or refresh) the ArchHub connector addon into that folder
  - launch Blender with the addon enabled
  - speak to the running addon over HTTP (ping/info/execute/render)

This module assumes the addon source is already in hand — it does NOT
generate the source. That's `meta_connector.generate_blender_addon`'s job.
The connector setup flow goes:

    1. meta_connector.generate_blender_addon(version, router)
         -> GeneratedSource with files["archhub_connector.py"]
    2. install_addon(GeneratedSource)
    3. launch_blender(blocking=False)        # or wait for user to open it
    4. ping_until_ready(timeout=30)
    5. start using the connector via execute() / render()
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from meta_connector import GeneratedSource


CONNECTOR_PORT_DEFAULT = 9876
CONNECTOR_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Locate Blender
# ---------------------------------------------------------------------------

def find_blender_executable() -> Optional[Path]:
    """Search the standard install locations on Windows / macOS / Linux."""
    candidates: list[Path] = []

    if sys.platform.startswith("win"):
        program_dirs = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        ]
        for pd in program_dirs:
            base = pd / "Blender Foundation"
            if not base.exists(): continue
            for sub in base.iterdir():
                exe = sub / "blender.exe"
                if exe.exists():
                    candidates.append(exe)
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Blender.app/Contents/MacOS/Blender"))
    else:
        for p in ("/usr/bin/blender", "/usr/local/bin/blender"):
            if Path(p).exists(): candidates.append(Path(p))

    # Try `which`/`where` as a final fallback
    if not candidates:
        which = shutil.which("blender")
        if which: candidates.append(Path(which))

    return candidates[0] if candidates else None


def detect_blender_version(exe: Path) -> Optional[str]:
    """Run `blender --version` and parse the major.minor version string."""
    try:
        out = subprocess.run([str(exe), "--version"],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = re.search(r"Blender\s+(\d+\.\d+)", out.stdout or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Locate Blender's user addons folder
# ---------------------------------------------------------------------------

def find_addons_folder(version: str) -> Path:
    """Return the user-level addons folder for the given Blender version.

    On Windows: %APPDATA%\\Blender Foundation\\Blender\\<version>\\scripts\\addons
    On macOS:   ~/Library/Application Support/Blender/<version>/scripts/addons
    On Linux:   ~/.config/blender/<version>/scripts/addons

    Created if missing.
    """
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", "")) / "Blender Foundation" / "Blender"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Blender"
    else:
        base = Path.home() / ".config" / "blender"
    folder = base / version / "scripts" / "addons"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def install_addon(generated: GeneratedSource,
                  blender_version: Optional[str] = None) -> Path:
    """Write the generated addon into Blender's user addons folder.

    If `blender_version` is given, install there; otherwise auto-detect.
    Returns the path of the installed addon file.
    """
    if blender_version is None:
        exe = find_blender_executable()
        if exe is None:
            raise FileNotFoundError("Blender executable not found.")
        v = detect_blender_version(exe) or "4.0"
    else:
        v = blender_version

    folder = find_addons_folder(v)

    # The contract emits one file: archhub_connector.py
    main_name = "archhub_connector.py"
    if main_name not in generated.files:
        raise RuntimeError(f"GeneratedSource missing {main_name}")

    target = folder / main_name
    target.write_text(generated.files[main_name], encoding="utf-8")
    return target


def write_enable_script(addons_folder: Path) -> Path:
    """Write a one-shot Blender Python script that enables the addon and
    saves user prefs. We pass this to `blender -P` on launch so the user
    doesn't need to enable manually in Edit > Preferences > Add-ons.
    """
    script = (
        "import bpy, addon_utils\n"
        "addon_utils.enable('archhub_connector', default_set=True, persistent=True)\n"
        "bpy.ops.wm.save_userpref()\n"
    )
    p = addons_folder / "_archhub_enable.py"
    p.write_text(script, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

@dataclass
class BlenderProcess:
    pid: int
    exe: Path
    process: subprocess.Popen


def launch_blender(*, with_addon_enabled: bool = True,
                   open_file: Optional[Path] = None) -> BlenderProcess:
    """Open Blender. If `with_addon_enabled`, runs a one-shot script that
    enables the ArchHub addon so the user doesn't have to."""
    exe = find_blender_executable()
    if exe is None:
        raise FileNotFoundError("Blender executable not found in standard locations.")
    version = detect_blender_version(exe) or "4.0"
    args: list[str] = [str(exe)]
    if open_file is not None:
        args.append(str(open_file))
    if with_addon_enabled:
        addons = find_addons_folder(version)
        script = write_enable_script(addons)
        args += ["-P", str(script)]
    proc = subprocess.Popen(args, close_fds=True)
    return BlenderProcess(pid=proc.pid, exe=exe, process=proc)


# ---------------------------------------------------------------------------
# HTTP client to the running addon
# ---------------------------------------------------------------------------

def _url(path: str, port: int = CONNECTOR_PORT_DEFAULT) -> str:
    return f"http://{CONNECTOR_HOST}:{port}{path}"


def _request(method: str, path: str, body: Optional[dict] = None,
             port: int = CONNECTOR_PORT_DEFAULT, timeout: float = 30.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(_url(path, port), data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "non-json response", "raw": raw}


def ping(port: int = CONNECTOR_PORT_DEFAULT, timeout: float = 2.0) -> Optional[dict]:
    """Single ping. Returns the response dict on success, None on connection
    error (Blender not running yet, addon not loaded, etc.)."""
    try:
        return _request("GET", "/ping", port=port, timeout=timeout)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def ping_until_ready(timeout: float = 30.0,
                     port: int = CONNECTOR_PORT_DEFAULT) -> bool:
    """Block up to `timeout` seconds waiting for the addon to come online."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ping(port=port) is not None:
            return True
        time.sleep(0.5)
    return False


def info(port: int = CONNECTOR_PORT_DEFAULT) -> dict:
    return _request("GET", "/info", port=port)


def execute(code: str, port: int = CONNECTOR_PORT_DEFAULT,
            timeout: float = 120.0) -> dict:
    return _request("POST", "/execute", body={"code": code},
                    port=port, timeout=timeout)


def render(output_path: Path, *, engine: str = "BLENDER_EEVEE",
           samples: Optional[int] = None,
           resolution: Optional[tuple[int, int]] = None,
           port: int = CONNECTOR_PORT_DEFAULT,
           timeout: float = 600.0) -> dict:
    body: dict = {"output_path": str(output_path), "engine": engine}
    if samples is not None: body["samples"] = samples
    if resolution is not None: body["resolution"] = list(resolution)
    return _request("POST", "/render", body=body, port=port, timeout=timeout)
