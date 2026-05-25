"""Memory extractors — write into the MemoryGraph from existing stores.

AgDR-0042 slice 2/6 (D1·C). Each extractor is a pure function:

    extract_library(graph)   → reads library.list_node_types +
                                workflows.registry.all_specs,
                                emits lib:* nodes + contains/wires_with edges
    extract_turns(graph, project_dir)  → reads
                                <project_dir>/.archhub/plans/*.json,
                                emits turn:* nodes + called edges to tool:*

Slices 4 + 5 add extract_project (Speckle / Revit / CAD / drawing PDFs
→ proj:*) and extract_decisions (docs/agdr/*.md → agdr:*).

Idempotent — re-running on the same source replaces existing nodes /
edges (MemoryGraph upserts by id / triple key). Safe to schedule on a
timer.

Each extractor runs inside a single g.transaction() so a half-finished
crash leaves the graph clean — see MemoryGraph._tx_depth for the
contract.
"""
from __future__ import annotations

from .library import extract_library  # noqa: F401
from .turns import extract_turns  # noqa: F401
from .decisions import extract_decisions  # noqa: F401
from .projects import extract_projects  # noqa: F401

__all__ = [
    "extract_library", "extract_turns",
    "extract_decisions", "extract_projects",
]
