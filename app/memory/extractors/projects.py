"""Project extractor — Speckle / Revit / CAD → MemoryGraph.

AgDR-0042 slice 4/6 (D1·C). Walks the local Speckle disk transport
(default `<LOCALAPPDATA>/ArchHub/projects/<name>/.speckle/`) and
emits one node per discovered project plus a coarse per-object node
per SQLite content file.

Coverage in this slice intentionally light:
  kind=project      — every project directory under projects/.
                       Id: `proj:<name>`.
  kind=design       — every Speckle wire SQLite the disk transport
                       wrote. Id: `proj:<name>:<sqlite_basename>`.
                       Props carry size_bytes + mtime.

The deeper extraction (Revit families, AutoCAD blocks, drawing PDFs,
per-Speckle-Version object trees) lands in a follow-up — that needs
live connector calls + per-host parsing surfaces that aren't yet
plumbed for batch extraction. The lightweight pass here is enough to
unblock slice 6 (firm-shared sync) which only needs project + design
node IDs to coordinate per-firm graphs.

Project root discovery:
  - `<LOCALAPPDATA>/ArchHub/projects/*/` on Windows
  - `$XDG_DATA_HOME/ArchHub/projects/*/` on POSIX
  - `~/.local/share/ArchHub/projects/*/` fallback
Both can be overridden via `projects_root=` argument (used by tests).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

_APP = Path(__file__).resolve().parents[2]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from memory.graph import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence,
)


# ── id + path helpers ────────────────────────────────────────────────


def _project_id(name: str) -> str:
    return f"proj:{name}"


def _design_id(project_name: str, basename: str) -> str:
    return f"proj:{project_name}:{basename}"


def _default_projects_root() -> Path:
    """Mirror speckle_wire.default_project_dir's BASE path (one level
    above the per-project .speckle/ dir)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "ArchHub" / "projects"
        return Path.home() / "AppData" / "Local" / "ArchHub" / "projects"
    xdg = os.environ.get("XDG_DATA_HOME")
    base_path = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_path / "ArchHub" / "projects"


# ── main entry ───────────────────────────────────────────────────────


def extract_projects(graph: MemoryGraph,
                       projects_root: Optional[Path | str] = None,
                       ) -> dict:
    """Walk every project directory under `projects_root` and emit
    project + design nodes (+ `contains` edges design → project).

    Idempotent.

    Returns counts: {projects_added, designs_added, contains_edges}.
    """
    if projects_root is None:
        projects_root = _default_projects_root()
    projects_root = Path(projects_root)
    if not projects_root.is_dir():
        return {"projects_added": 0, "designs_added": 0,
                "contains_edges": 0}

    project_nodes: list[MemoryNode] = []
    design_nodes: list[MemoryNode] = []
    contains_edges: list[MemoryEdge] = []

    for proj_dir in sorted(projects_root.iterdir()):
        if not proj_dir.is_dir():
            continue
        project_name = proj_dir.name
        pid = _project_id(project_name)
        project_nodes.append(MemoryNode(
            id=pid, kind="project",
            label=project_name,
            props={
                "name": project_name,
                "path": str(proj_dir),
            },
        ))
        # Look for the .speckle/ wire-store dir.
        speckle_dir = proj_dir / ".speckle"
        if not speckle_dir.is_dir():
            continue
        for sqlite_path in sorted(speckle_dir.glob("*.sqlite")):
            try:
                st = sqlite_path.stat()
            except OSError:
                continue
            basename = sqlite_path.stem
            did = _design_id(project_name, basename)
            design_nodes.append(MemoryNode(
                id=did, kind="design",
                label=f"{project_name} / {basename}",
                props={
                    "project": project_name,
                    "basename": basename,
                    "path": str(sqlite_path),
                    "size_bytes": st.st_size,
                    "mtime": int(st.st_mtime),
                    "source": "speckle.disk_transport",
                },
            ))
            contains_edges.append(MemoryEdge(
                source=pid, target=did,
                relation="contains",
                confidence=Confidence.EXTRACTED,
            ))

    with graph.transaction():
        graph.add_nodes(project_nodes)
        graph.add_nodes(design_nodes)
        graph.add_edges(contains_edges)

    return {
        "projects_added": len(project_nodes),
        "designs_added":  len(design_nodes),
        "contains_edges": len(contains_edges),
    }
