"""Personal Brain MCP — ambient agent substrate.

Ships with ArchHub. Runs as standalone daemon. Reachable from every MCP
client (Claude Code, Cursor, ChatGPT desktop, Codex CLI, Gemini CLI,
Cline, Continue, ArchHub Composer) via stdio + Streamable HTTP.

AgDR-0044 (founder sign-off 2026-05-25):
  - F1.B Build from scratch on app/memory/graph.py
  - F2.A Voyager + SkillWeaver hybrid skill mining
  - F3.A Loro CRDT + Tailscale, EXTENDED with Speckle for spatial memory
  - F4.A Community tier in V1

Public surface (slice 1):
    from personal_brain.server import build_server, main
    from personal_brain.storage import BrainStore
    from personal_brain.models import Fragment, Skill, WiringEntry

Five live loops (see AgDR-0044 §"Decision"):
  1. context inject   (UserPromptSubmit hook → brain.context)
  2. tool augment     (PreToolUse hook → secret resolve)
  3. memory write     (PostToolUse hook → brain.write)
  4. skill mint       (Stop hook → brain.skill_mint → reflexion worker)
  5. wiring sync      (SessionStart hook → brain.wiring_announce)
"""
from __future__ import annotations

__version__ = "0.1.0"

from .storage import BrainStore  # noqa: F401
from .models import (  # noqa: F401
    Fragment,
    FragmentKind,
    Scope,
    Visibility,
    Skill,
    WiringEntry,
    SecretRef,
    Provenance,
    ContextResponse,
    WriteOp,
    WriteOpType,
    SkillMintResult,
)
from .server import build_server, main, main_stdio  # noqa: F401
from .cloud_config import (  # noqa: F401
    CloudConfig,
    load_cloud_config,
    save_cloud_config,
    default_cloud_config_path,
)
from .personal_cloud_sync import PersonalCloudSync, PersonalSyncResult  # noqa: F401

__all__ = [
    "BrainStore",
    "CloudConfig",
    "load_cloud_config",
    "save_cloud_config",
    "default_cloud_config_path",
    "PersonalCloudSync",
    "PersonalSyncResult",
    "Fragment",
    "FragmentKind",
    "Scope",
    "Visibility",
    "Skill",
    "WiringEntry",
    "SecretRef",
    "Provenance",
    "ContextResponse",
    "WriteOp",
    "WriteOpType",
    "SkillMintResult",
    "build_server",
    "main",
    "main_stdio",
]
