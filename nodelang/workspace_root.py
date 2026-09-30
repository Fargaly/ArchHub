"""The governed workspace root the application runs against (one resolver).

Shared by the universal application and the workspace-roots catalogue so the
built-in governed tree and the application root are always the same folder.
"""
from __future__ import annotations

from pathlib import Path

from .universal_cell import InvalidCell


def workspace_root_for_map(map_path: str | Path) -> Path:
    """The governed workspace root: the founder tree when the map sits in one.

    Elsewhere -- a colleague install, a CI runner -- there is no 00.GOVERNANCE
    above the map and the application still has to open. ARCHHUB_WORKSPACE_ROOT
    names it explicitly; otherwise the root is the tree that holds the node
    language itself (the parent of the nodelang package), which is what a
    colleague machine has.
    """
    import os
    resolved = Path(map_path).expanduser().resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (
            (candidate / "00.GOVERNANCE").is_dir()
            and (candidate / "10.PRODUCT").is_dir()
        ):
            return candidate
    named = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if named and Path(named).expanduser().is_dir():
        return Path(named).expanduser().resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / "nodelang" / "__init__.py").is_file():
            return candidate
    raise InvalidCell("ArchHub workspace root is unavailable")
