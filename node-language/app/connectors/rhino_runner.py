"""Rhino runner — discovery + reachability for the Rhino MCP bridge.

Sister of `blender_runner` for Rhino 7+. Differences from Blender:
  - Rhino uses its own embedded Python (not a generic add-on system)
  - We don't build a connector binary; the user runs the script directly
    via `_-RunPythonScript` (one-time) or copies it into the Rhino
    scripts folder (permanent)

Public surface:
    find_rhino_executable() -> Path | None
    detect_rhino_version(exe) -> str | None     # "7", "8"
    rhino_scripts_folder(version) -> Path        # user-level scripts dir
    payload_addon_path() -> Path                  # the archhub_mcp.py source
    is_reachable(port=9879) -> bool               # quick TCP poke
    ping() -> dict                                # /ping → {status, version}
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import json
from pathlib import Path
from typing import Optional


CONNECTOR_PORT_DEFAULT = 9879
CONNECTOR_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
def find_rhino_executable() -> Optional[Path]:
    """Locate `Rhino.exe` on this machine, or return None."""
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        program_dirs = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        ]
        for pd in program_dirs:
            mcneel = pd / "Rhino 8" / "System" / "Rhino.exe"
            if mcneel.exists():
                candidates.append(mcneel)
            mcneel7 = pd / "Rhino 7" / "System" / "Rhino.exe"
            if mcneel7.exists():
                candidates.append(mcneel7)
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Rhino 8.app/Contents/MacOS/Rhinoceros"))
        candidates.append(Path("/Applications/Rhino 7.app/Contents/MacOS/Rhinoceros"))

    if not candidates:
        which = shutil.which("rhino") or shutil.which("Rhino")
        if which:
            candidates.append(Path(which))
    return candidates[0] if candidates else None


def detect_rhino_version(exe: Optional[Path]) -> Optional[str]:
    """Best-effort version detection. Inspect the install path; we don't
    actually launch Rhino just to read its version (slow)."""
    if not exe:
        return None
    s = str(exe)
    if "Rhino 8" in s:
        return "8"
    if "Rhino 7" in s:
        return "7"
    return None


def rhino_scripts_folder(version: str) -> Path:
    """User-level Python scripts folder Rhino auto-loads from."""
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", "")) / "McNeel" / "Rhinoceros" / f"{version}.0" / "scripts"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "McNeel" / "Rhinoceros" / f"{version}.0" / "scripts"
    # Linux is not officially supported but rhino-on-wine paths land here
    return Path.home() / ".rhino" / f"{version}.0" / "scripts"


def payload_addon_path() -> Path:
    """Return the absolute path to the bundled archhub_mcp.py addon."""
    return Path(__file__).resolve().parent.parent.parent / "payload" / "rhino" / "archhub_mcp.py"


def install_addon(version: str) -> dict:
    """Copy the bundled addon into Rhino's scripts folder for auto-load.

    Idempotent — re-running overwrites. Returns
        {"status": "ok", "dest": "..."} on success
        {"status": "error", "error": "..."}  otherwise
    """
    try:
        dest_dir = rhino_scripts_folder(version)
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = payload_addon_path()
        if not src.exists():
            return {"status": "error",
                    "error": f"Bundled addon missing at {src}"}
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        return {"status": "ok", "dest": str(dest)}
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


# ---------------------------------------------------------------------------
def is_reachable(port: int = CONNECTOR_PORT_DEFAULT,
                  timeout: float = 0.5) -> bool:
    """Quick TCP connect probe — used by host pills + tool dispatch."""
    try:
        with socket.create_connection((CONNECTOR_HOST, port), timeout=timeout):
            return True
    except Exception:
        return False


def ping(port: int = CONNECTOR_PORT_DEFAULT, timeout: float = 3.0) -> dict:
    """HTTP /ping endpoint — returns the JSON envelope from the addon."""
    try:
        url = f"http://{CONNECTOR_HOST}:{port}/ping"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as ex:
        return {"status": "error",
                "error": f"Cannot reach Rhino bridge at {CONNECTOR_HOST}:{port} — "
                         f"is the addon loaded? ({ex})"}
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def info(port: int = CONNECTOR_PORT_DEFAULT, timeout: float = 5.0) -> dict:
    """Full Rhino doc info."""
    try:
        url = f"http://{CONNECTOR_HOST}:{port}/info"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        return {"status": "error", "error": str(ex)}


def execute_python(code: str, *, timeout_seconds: int = 60,
                    port: int = CONNECTOR_PORT_DEFAULT) -> dict:
    """Run Python inside Rhino's context. `rs`, `Rhino`, `sc`, `doc`
    globals are pre-populated by the addon."""
    if not code:
        return {"status": "error", "error": "code is required"}
    body = json.dumps({"code": code, "timeout_seconds": timeout_seconds}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{CONNECTOR_HOST}:{port}/execute",
        data=body, headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds + 5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:300]}


def screenshot(*, output_path: Optional[str] = None,
                width: int = 1920, height: int = 1080,
                port: int = CONNECTOR_PORT_DEFAULT) -> dict:
    body = {"width": width, "height": height}
    if output_path:
        body["output_path"] = output_path
    req = urllib.request.Request(
        f"http://{CONNECTOR_HOST}:{port}/screenshot",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:300]}
