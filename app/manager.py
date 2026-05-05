"""ConnectorManager — orchestrates detection, activation, deactivation, and
state persistence for every connector ArchHub knows about.

Responsibilities:
  - Detect installed AEC tools (delegates to detection.py)
  - Activate a connector: copy connector files into place, register MCP server
    entry in Claude Desktop config.
  - Deactivate: remove files, remove the MCP entry.
  - Maintain `state.json` so toggle states persist across reboots.

A single unified MCP server (bridge/server.py) handles all toggled-on
connectors. When ANY are active, that server is registered in Claude Desktop
under the name 'archhub'. When none are active, the entry is removed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
PAYLOAD_DIR = Path(__file__).resolve().parent.parent / "payload"   # bundled connector files
STATE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "archhub.log"
BRIDGE_DIR = APP_DIR / "bridge"
PYTHON_EXE = sys.executable  # python that runs ArchHub also runs the bridge

CLAUDE_CFG = Path(os.environ.get("APPDATA", str(Path.home()))) / "Claude" / "claude_desktop_config.json"

APP_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Connector state
# ---------------------------------------------------------------------------
class ConnectorState(Enum):
    UNAVAILABLE = "unavailable"   # host app not installed
    READY = "ready"               # detected, not yet active
    ACTIVE = "active"             # toggled on, files in place
    ERROR = "error"               # last action failed


@dataclass
class ConnectorEntry:
    id: str                         # stable: "revit-2025", "blender", "speckle"
    display_name: str               # "Revit 2025"
    short_letter: str               # used in the round icon ("R", "A", "M")
    family: str                     # "revit" | "autocad" | "max" | "blender" | "rhino" | "speckle"
    version: str | None = None      # "2025" or None
    detected_path: Path | None = None  # where the host application lives
    state: ConnectorState = ConnectorState.UNAVAILABLE
    detail: str = ""                # extra status text


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class ConnectorManager:
    def __init__(self):
        self.entries: list[ConnectorEntry] = []
        self._persisted_active: set[str] = self._load_state()

    # ----- public API -------------------------------------------------------

    def refresh(self) -> None:
        """Re-detect host applications and rebuild the entry list."""
        from detection import discover_all
        from connectors.registry import resolve
        self.entries = discover_all()

        for e in self.entries:
            spec = resolve(e.family)
            if e.id in self._persisted_active and e.state == ConnectorState.READY:
                # Verify activation files are still in place
                if spec and spec.is_active(e):
                    e.state = ConnectorState.ACTIVE
                else:
                    # Files missing — clean up persisted state so user can re-activate
                    self._persisted_active.discard(e.id)
            elif spec:
                # Always run is_active() to auto-clean stale files (e.g. stale .addin
                # manifests that point to a DLL that was never built)
                spec.is_active(e)

    def activate(self, connector_id: str) -> Tuple[bool, str]:
        entry = self._find(connector_id)
        if entry is None:
            return False, "Unknown connector"
        if entry.state == ConnectorState.UNAVAILABLE:
            return False, "Host app not installed"

        from connectors.registry import resolve
        spec = resolve(entry.family)
        if spec is None:
            return False, "No connector implementation"

        try:
            spec.activate(entry, payload_dir=PAYLOAD_DIR)
        except Exception as ex:
            entry.state = ConnectorState.ERROR
            entry.detail = str(ex)
            log(f"activate {connector_id} failed: {ex}")
            return False, str(ex)

        entry.state = ConnectorState.ACTIVE
        entry.detail = "active"
        self._persisted_active.add(connector_id)
        self._save_state()
        self._sync_claude_config()
        log(f"activated {connector_id}")
        return True, "ok"

    def deactivate(self, connector_id: str) -> Tuple[bool, str]:
        entry = self._find(connector_id)
        if entry is None:
            return False, "Unknown connector"
        from connectors.registry import resolve
        spec = resolve(entry.family)
        if spec is None:
            return False, "No connector implementation"

        try:
            spec.deactivate(entry)
        except Exception as ex:
            entry.state = ConnectorState.ERROR
            entry.detail = str(ex)
            log(f"deactivate {connector_id} failed: {ex}")
            return False, str(ex)

        entry.state = ConnectorState.READY
        entry.detail = ""
        self._persisted_active.discard(connector_id)
        self._save_state()
        self._sync_claude_config()
        log(f"deactivated {connector_id}")
        return True, "ok"

    # ----- internals --------------------------------------------------------

    def _find(self, connector_id: str) -> ConnectorEntry | None:
        for e in self.entries:
            if e.id == connector_id:
                return e
        return None

    def _load_state(self) -> set[str]:
        if not STATE_PATH.exists():
            return set()
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return set(data.get("active", []))
        except Exception:
            return set()

    def _save_state(self) -> None:
        STATE_PATH.write_text(
            json.dumps({"active": sorted(self._persisted_active)}, indent=2),
            encoding="utf-8",
        )

    def _sync_claude_config(self) -> None:
        """Add or remove the unified ArchHub MCP server entry in Claude Desktop's
        config based on whether ANY connector is active.

        ArchHub registers a single 'archhub' MCP server. The server (bridge/server.py)
        reads ``state.json`` at every tool call to know which connectors are live,
        so toggling individual connectors doesn't require Claude to restart.
        """
        any_active = bool(self._persisted_active)
        bridge_script = BRIDGE_DIR / "server.py"

        # Make sure the bridge has been staged into APP_DIR (first run)
        if any_active and not bridge_script.exists():
            self._stage_bridge()

        try:
            CLAUDE_CFG.parent.mkdir(parents=True, exist_ok=True)
            cfg: dict = {}
            if CLAUDE_CFG.exists():
                try:
                    cfg = json.loads(CLAUDE_CFG.read_text(encoding="utf-8"))
                except Exception:
                    backup = CLAUDE_CFG.with_suffix(".json.bak")
                    shutil.copy2(CLAUDE_CFG, backup)
                    cfg = {}

            servers = cfg.setdefault("mcpServers", {})

            if any_active:
                servers["archhub"] = {
                    "command": PYTHON_EXE,
                    "args": [str(bridge_script)],
                }
            else:
                servers.pop("archhub", None)

            CLAUDE_CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            log(f"claude config sync: active={any_active}")
        except Exception as ex:
            log(f"claude config sync failed: {ex}")

    def _stage_bridge(self) -> None:
        """Copy the unified MCP bridge from the install payload to APP_DIR."""
        src = PAYLOAD_DIR / "bridge"
        if not src.exists():
            log(f"bridge payload missing at {src}")
            return
        if BRIDGE_DIR.exists():
            shutil.rmtree(BRIDGE_DIR)
        shutil.copytree(src, BRIDGE_DIR)
        log(f"bridge staged to {BRIDGE_DIR}")
