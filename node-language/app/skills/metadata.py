"""SkillMeta — discoverability layer over a Workflow.

Stored as `Workflow.metadata` (a plain dict) so the on-disk schema stays one
file, one workflow. The matcher and chat read these fields to find the right
Skill for a user prompt.

A Workflow becomes a Skill the moment its metadata.intent is non-empty.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


SCOPE_USER = "user"
SCOPE_TEAM = "team"
SCOPE_FIRM = "firm"
SCOPES = (SCOPE_USER, SCOPE_TEAM, SCOPE_FIRM)


@dataclass
class SkillMeta:
    intent: str = ""                          # one-line "what this does", e.g. "Dimension all walls in the active Revit view"
    keywords: list[str] = field(default_factory=list)   # match terms ("dimension", "wall", "annotate")
    when_to_use: str = ""                     # guidance for matcher and AI: when this is the right pick
    examples: list[dict] = field(default_factory=list)  # [{prompt, expected_outcome}]
    tags: list[str] = field(default_factory=list)       # taxonomy: "revit", "annotation", "render"
    requires: list[str] = field(default_factory=list)   # connectors that must be active: "revit", "blender"
    author: str = ""
    scope: str = SCOPE_USER                   # SCOPE_USER | SCOPE_TEAM | SCOPE_FIRM
    version: str = "1.0.0"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SkillMeta":
        return SkillMeta(
            intent=d.get("intent", ""),
            keywords=list(d.get("keywords") or []),
            when_to_use=d.get("when_to_use", ""),
            examples=list(d.get("examples") or []),
            tags=list(d.get("tags") or []),
            requires=list(d.get("requires") or []),
            author=d.get("author", ""),
            scope=d.get("scope", SCOPE_USER),
            version=d.get("version", "1.0.0"),
        )


def attach_meta(workflow, meta: SkillMeta) -> None:
    """Stamp SkillMeta onto a Workflow's metadata dict."""
    workflow.metadata = dict(workflow.metadata or {})
    workflow.metadata["skill"] = meta.to_dict()


def get_meta(workflow) -> Optional[SkillMeta]:
    raw = (workflow.metadata or {}).get("skill") if hasattr(workflow, "metadata") else None
    if not raw:
        return None
    return SkillMeta.from_dict(raw)


def is_skill(workflow) -> bool:
    meta = get_meta(workflow)
    return bool(meta and meta.intent)
