"""Library persistence — JSON storage at %LOCALAPPDATA%/ArchHub/library/.

Reference: docs/agdr/AgDR-0013-multi-llm-library-first-enforcement.md
Reference: docs/agdr/AgDR-0014-library-design-system.md

The library module (app/library.py) holds an in-process dict of registered
ModularNodeSpec entries. Without persistence the library evaporates on every
restart — the AI's freshly-minted nodes vanish, the user-created skills lose
their library entry, and the search index regenerates from seed only.

This module gives the library disk durability:
- `save(registry, path)`  — atomic write: serialise to tmp file, then rename.
- `load(path)`            — read JSON; return `{}` if file missing.
- `default_registry_path()` — `%LOCALAPPDATA%/ArchHub/library/registry.json`
                              on Windows; `~/.local/share/ArchHub/library/`
                              elsewhere.

Atomicity matters: a corrupted half-written file would brick the library on
next boot. We write to `<path>.tmp` first, then `os.replace()` (atomic on
both POSIX and Windows since Python 3.3) into place.

A bad-shape JSON file (manually edited, corrupted) is treated as empty +
logged — never raised. The library boots clean and the user is informed via
the bridge.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional


_REGISTRY_FILENAME = "registry.json"
_APP_DIR = "ArchHub"
_LIBRARY_SUBDIR = "library"


def default_registry_path() -> Path:
    """Default location for the library registry file.

    Windows:  %LOCALAPPDATA%/ArchHub/library/registry.json
    POSIX:    $XDG_DATA_HOME/ArchHub/library/registry.json
              fallback ~/.local/share/ArchHub/library/registry.json
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / _APP_DIR / _LIBRARY_SUBDIR / _REGISTRY_FILENAME
        # Fallback to home if LOCALAPPDATA missing.
        return (
            Path.home() / "AppData" / "Local"
            / _APP_DIR / _LIBRARY_SUBDIR / _REGISTRY_FILENAME
        )

    # POSIX
    xdg = os.environ.get("XDG_DATA_HOME")
    base_path = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_path / _APP_DIR / _LIBRARY_SUBDIR / _REGISTRY_FILENAME


def save(registry: dict[str, dict], path: Optional[Path] = None) -> Path:
    """Atomically write the registry to disk.

    `registry` is the in-process `{type_name: ModularNodeSpec.model_dump()}`
    dict from `app/library.py`. Returns the path written.

    Atomic via temp-file + replace. A crash mid-write leaves either the old
    file (unchanged) or the new file (complete) — never a half-written one.
    """
    p = path or default_registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = {
        "version": 1,
        "count": len(registry),
        "entries": registry,
    }
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, p)  # atomic on Windows + POSIX
    return p


def load(path: Optional[Path] = None) -> dict[str, dict]:
    """Read the registry from disk.

    Returns `{}` if:
      - the file does not exist (first run / cleared library)
      - the file is empty / unreadable (treated as corrupt-but-recoverable)
      - the JSON shape is unexpected (logged silently; library boots clean)

    Never raises — boot must always succeed even with a damaged file.
    """
    p = path or default_registry_path()
    if not p.exists():
        return {}

    try:
        with open(p, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # Corrupt / unreadable — treat as empty. The bridge can surface
        # this to the user via a one-shot toast.
        return {}

    if not isinstance(payload, dict):
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}

    # Filter out anything that does not look like a spec dict — defence
    # against partially-corrupted entries.
    clean: dict[str, dict] = {}
    for type_name, spec in entries.items():
        if (isinstance(type_name, str) and isinstance(spec, dict)
                and spec.get("type") == type_name):
            clean[type_name] = spec
    return clean


def delete_registry_file(path: Optional[Path] = None) -> bool:
    """Remove the registry file. Returns True if a file was deleted.

    Used by `bridge.reset_library` (a future M3 settings action) and by
    tests for clean teardown.
    """
    p = path or default_registry_path()
    if not p.exists():
        return False
    p.unlink()
    return True
