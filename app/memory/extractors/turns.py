"""Composer-turn extractor — ai.plan cache → MemoryGraph.

AgDR-0042 slice 2/6.

Walks `<project_dir>/.archhub/plans/*.json` (every persisted Composer
plan, see app/plan_history.py for the record shape) and emits:

  kind=turn   — every plan record. Id: `turn:<plan_id>`. Props carry
                prompt, model, status, ts. EXTRACTED — directly read.
  kind=tool   — every distinct tool name referenced inside a plan's
                `plan` (tool_invocations) list. Id: `tool:<name>`.
                Lazy-created on first reference (avoids requiring a
                separate tool-catalogue extractor).
  relation=called — turn → tool. One per tool_invocation in the plan.
                    Props carry args_preview + ts when available.
  relation=used   — turn → lib:cap:<type> OR turn → lib:skill:<type>
                    Emitted when the plan invoked a library-backed
                    Capability or Skill (i.e. the tool name maps to a
                    known library type). Confidence EXTRACTED. Skipped
                    silently when the cap node doesn't exist in the
                    graph — turn extractor doesn't depend on library
                    extractor having run, but cross-source edges only
                    materialise when both have.

Re-entrant. Re-running on the same plans dir upserts everything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

_APP = Path(__file__).resolve().parents[2]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from memory.graph import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence,
)


# ── id helpers ───────────────────────────────────────────────────────


def _turn_id(plan_id: str) -> str:
    return f"turn:{plan_id}"


def _tool_id(name: str) -> str:
    return f"tool:{name}"


def _cap_id(type_name: str) -> str:
    return f"lib:cap:{type_name}"


def _skill_id(type_name: str) -> str:
    return f"lib:skill:{type_name}"


# ── plan loader ──────────────────────────────────────────────────────


def _plan_records(project_dir: Path) -> Iterable[dict]:
    """Yield every persisted plan record under <project_dir>/.archhub/plans/."""
    plans_dir = Path(project_dir) / ".archhub" / "plans"
    if not plans_dir.is_dir():
        return
    for p in sorted(plans_dir.glob("*.json")):
        # Skip the .tmp files written by atomic save in mid-flight.
        if p.name.endswith(".tmp"):
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                yield json.load(f)
        except Exception:
            # Corrupt / half-written record — skip; don't crash the
            # whole extraction.
            continue


# ── tool-name resolution ─────────────────────────────────────────────


def _tool_target_id(tool_name: str, *, known_caps: set, known_skills: set
                     ) -> str | None:
    """Map a tool invocation's name onto a library/registry id IF the
    name matches a known capability or skill. Returns None when the
    tool is generic (LLM `respond`, internal `_local` helpers).

    Convention: tool names are dotted (`render.comfyui`, `connector.run`,
    `skill.revit_hero_render`). Skills win when ambiguous."""
    if not tool_name:
        return None
    # Heuristic — connector ops use double-underscore in some surfaces
    # (autocad__list_documents); strip to dotted for the library check.
    candidate = tool_name.replace("__", ".")
    if candidate.startswith("skill."):
        if _skill_id(candidate) in known_skills:
            return _skill_id(candidate)
    if _cap_id(candidate) in known_caps:
        return _cap_id(candidate)
    return None


# ── main entry ───────────────────────────────────────────────────────


def extract_turns(graph: MemoryGraph, project_dir: str | Path) -> dict:
    """Walk every persisted plan record under <project_dir>/.archhub/plans/
    and write turn:* / tool:* nodes + called / used edges into `graph`.

    Idempotent — re-running upserts in place.

    Returns counts:
      {turns_added, tools_added, called_edges, used_edges}.
    """
    project_dir = Path(project_dir)
    # Snapshot the set of cap / skill ids already in the graph so we
    # only emit `used` edges to nodes that exist (cross-extractor
    # ordering is the caller's problem; we don't fail when the library
    # extractor hasn't been run yet).
    known_caps = {n.id for n in graph.all_nodes(kind="capability")}
    known_skills = {n.id for n in graph.all_nodes(kind="skill")}

    new_turns: list[MemoryNode] = []
    new_tools: dict[str, MemoryNode] = {}  # name → node (de-dup)
    called_edges: list[MemoryEdge] = []
    used_edges: list[MemoryEdge] = []

    for record in _plan_records(project_dir):
        plan_id = record.get("plan_id") or ""
        if not plan_id:
            continue
        tid = _turn_id(plan_id)
        new_turns.append(MemoryNode(
            id=tid, kind="turn",
            label=(record.get("prompt") or "")[:80],
            props={
                "plan_id":  plan_id,
                "prompt":   record.get("prompt") or "",
                "model":    record.get("model") or "",
                "status":   record.get("status") or "",
                "ts":       record.get("ts") or 0,
                "error":    record.get("error") or "",
            },
        ))
        for inv in record.get("plan") or []:
            if not isinstance(inv, dict):
                continue
            name = (inv.get("tool") or inv.get("name")
                    or inv.get("op") or "")
            if not name:
                continue
            tool_node_id = _tool_id(name)
            if tool_node_id not in new_tools:
                new_tools[tool_node_id] = MemoryNode(
                    id=tool_node_id, kind="tool",
                    label=name,
                    props={"name": name},
                )
            called_edges.append(MemoryEdge(
                source=tid, target=tool_node_id,
                relation="called",
                confidence=Confidence.EXTRACTED,
                props={
                    "args_preview": str(inv.get("args")
                                         or inv.get("arguments")
                                         or "")[:160],
                    "ts": inv.get("ts") or 0,
                },
            ))
            # Cross-source `used` edge — only emit when the library
            # extractor has already surfaced the target cap / skill.
            target_lib = _tool_target_id(
                name, known_caps=known_caps, known_skills=known_skills)
            if target_lib is not None:
                used_edges.append(MemoryEdge(
                    source=tid, target=target_lib,
                    relation="used",
                    confidence=Confidence.EXTRACTED,
                ))

    with graph.transaction():
        graph.add_nodes(new_turns)
        graph.add_nodes(list(new_tools.values()))
        graph.add_edges(called_edges)
        graph.add_edges(used_edges)

    return {
        "turns_added":  len(new_turns),
        "tools_added":  len(new_tools),
        "called_edges": len(called_edges),
        "used_edges":   len(used_edges),
    }
