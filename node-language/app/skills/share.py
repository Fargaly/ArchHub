"""Skill sharing — export and import skill JSON.

Skills are portable: one file, one workflow, plain JSON. This module gives
the UI three ways to move a Skill between machines:

  - export_skill_to_string(skill_id)  → JSON text the user can paste anywhere
  - import_skill_from_string(text)    → parses JSON, validates, saves locally
  - import_skill_from_file(path)      → same, reading from a .archhub-workflow.json

The text form is the same format ArchHub writes to disk, so a Skill exported
from one architect's machine is directly droppable onto another. ComfyUI
users will recognise the pattern: copy JSON → paste → it loads.

Round-trip is lossless: every field round-trips through Workflow.from_json
/ Workflow.to_json.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from workflows.graph import Workflow

from .library import save_skill, list_skills
from .metadata import SkillMeta, get_meta, is_skill


class SkillImportError(Exception):
    """Raised when import text/file is not a valid Skill JSON."""


# ---------------------------------------------------------------------------
def export_skill_to_string(skill_id: str) -> str:
    """Return the Skill's JSON text (pretty-printed, UTF-8) for sharing."""
    item = next((s for s in list_skills() if s["id"] == skill_id), None)
    if item is None:
        raise SkillImportError(f"Skill '{skill_id}' not found.")
    return Path(item["path"]).read_text(encoding="utf-8")


def export_skill_to_file(skill_id: str, dest_path: Path) -> Path:
    """Write the Skill JSON to dest_path. Returns the resolved path."""
    text = export_skill_to_string(skill_id)
    dest = Path(dest_path)
    dest.write_text(text, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
def import_skill_from_string(text: str, *, force_new_id: bool = True) -> Workflow:
    """Parse text as a Skill JSON, save to the user library, return Workflow.

    By default the imported Skill gets a fresh id so it never clobbers a
    Skill the user already has. Set force_new_id=False to keep the original
    id (useful when re-importing your own previously exported file).
    """
    text = (text or "").strip()
    if not text:
        raise SkillImportError("Empty input.")

    try:
        wf = Workflow.from_json(text)
    except json.JSONDecodeError as ex:
        raise SkillImportError(f"Not valid JSON: {ex.msg} (line {ex.lineno}).")
    except KeyError as ex:
        raise SkillImportError(f"Missing required field {ex} in workflow JSON.")
    except Exception as ex:
        raise SkillImportError(f"Could not parse workflow: {ex}")

    errors = wf.validate()
    if errors:
        raise SkillImportError(
            "Workflow has structural errors:\n  - " + "\n  - ".join(errors[:6])
        )

    if not is_skill(wf):
        raise SkillImportError(
            "This JSON parses as a Workflow but has no Skill metadata "
            "(metadata.skill.intent is empty). Save it from the Workflows "
            "tab instead."
        )

    if force_new_id:
        wf.id = str(uuid.uuid4())

    meta = get_meta(wf) or SkillMeta()
    save_skill(wf, meta)
    return wf


def import_skill_from_file(path: Path, *, force_new_id: bool = True) -> Workflow:
    """Convenience wrapper around import_skill_from_string."""
    p = Path(path)
    if not p.exists():
        raise SkillImportError(f"File not found: {p}")
    return import_skill_from_string(
        p.read_text(encoding="utf-8"), force_new_id=force_new_id
    )


# ---------------------------------------------------------------------------
def looks_like_skill_json(text: str) -> bool:
    """Cheap sniff: does this string smell like Skill JSON?

    Used by the chat slash-command parser and the panel's paste-from-clipboard
    button to decide whether to treat input as a paste-import.
    """
    if not text:
        return False
    head = text.lstrip()[:200]
    if not head.startswith("{"):
        return False
    return ("\"nodes\"" in text and "\"edges\"" in text
            and ("\"schema_version\"" in text or "\"metadata\"" in text))
