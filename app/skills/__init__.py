"""ArchHub Skills — discoverable, reusable workflows.

A Skill is a Workflow with intent metadata. The chat picks a Skill from the
library when the user's prompt matches its intent, runs it, and shows the
result. New Skills are created from a successful chat conversation via
`/skill save`.

Public surface:

    from skills import (
        SkillMeta, attach_meta, get_meta, is_skill,
        match_skills, list_skills, library_paths,
        record_run,
        capture_chat_as_skill,
    )
"""
from __future__ import annotations

from .metadata import (
    SkillMeta, SCOPE_USER, SCOPE_TEAM, SCOPE_FIRM,
    attach_meta, get_meta, is_skill,
)
from .matcher import match_skills, MatchResult
from .library import list_skills, load_skill, save_skill, delete_skill, library_paths
from .usage import record_run, get_usage
from .capture import capture_chat_as_skill
from .seeds import ensure_starter_skills
from .share import (
    export_skill_to_string, export_skill_to_file,
    import_skill_from_string, import_skill_from_file,
    looks_like_skill_json, SkillImportError,
)

__all__ = [
    "SkillMeta", "SCOPE_USER", "SCOPE_TEAM", "SCOPE_FIRM",
    "attach_meta", "get_meta", "is_skill",
    "match_skills", "MatchResult",
    "list_skills", "load_skill", "save_skill", "delete_skill", "library_paths",
    "record_run", "get_usage",
    "capture_chat_as_skill",
    "ensure_starter_skills",
    "export_skill_to_string", "export_skill_to_file",
    "import_skill_from_string", "import_skill_from_file",
    "looks_like_skill_json", "SkillImportError",
]
