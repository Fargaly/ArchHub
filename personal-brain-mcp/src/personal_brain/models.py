"""Pydantic schemas for brain MCP I/O.

These types are the contract every MCP client sees. Stable. Versioned with
the brain.

Five scope tiers per AgDR-0044:
    user       — private, owner only
    project    — shared_project, project members
    firm       — shared_company, firm seats
    community  — shared_public, promoter (redacted)
    global     — canonical, maintainers
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ───────────────────────── Enums ────────────────────────────────────────


class Scope(str, Enum):
    USER = "user"
    PROJECT = "project"
    FIRM = "firm"
    COMMUNITY = "community"
    GLOBAL = "global"


class Visibility(str, Enum):
    PRIVATE = "private"
    SHARED_PROJECT = "shared_project"
    SHARED_COMPANY = "shared_company"
    SHARED_PUBLIC = "shared_public"
    CANONICAL = "canonical"


class FragmentKind(str, Enum):
    FACT = "fact"
    SKILL = "skill"
    SETUP = "setup"
    SECRET_REF = "secret_ref"
    WIRING = "wiring"
    TRACE = "trace"
    SPATIAL = "spatial"


class WriteOpType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"


class Confidence(str, Enum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"


# ───────────────────────── Provenance ──────────────────────────────────


class Provenance(BaseModel):
    """Immutable provenance attached to every fragment (arXiv 2505.18279).

    Recorded at write-time; never mutated. Used for retrospective ACL
    checks + audit log.
    """

    contributing_agent: str = Field(
        description="LLM model id that produced/touched the fragment"
        " — e.g. 'claude-sonnet-4.7', 'gpt-5', 'gemini-2.5-pro'."
    )
    contributing_user: str = Field(description="User identity (owner of this seat).")
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    accessed_resources: list[str] = Field(
        default_factory=list,
        description="MCP servers, secrets, files touched while producing this fragment.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_reinforced_at: Optional[datetime] = None
    hlc: Optional[str] = Field(
        default=None,
        description="Hybrid Logical Clock — 64-bit packed wallclock+logical counter.",
    )


# ───────────────────────── Fragment (memory) ───────────────────────────


class Fragment(BaseModel):
    """Atomic unit of brain memory. One row in the store.

    Fragments are nodes in the underlying MemoryGraph (AgDR-0042). Edges
    between fragments are stored separately and carry their own provenance.
    """

    id: str = Field(description="Stable content-derived ID (sha256 of canonical form).")
    kind: FragmentKind
    text: str = Field(description="Human-readable form. Searchable via FTS5.")
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    scope: Scope = Scope.USER
    visibility: Visibility = Visibility.PRIVATE
    owner_user: str
    project_id: Optional[str] = None
    firm_id: Optional[str] = None
    confidence: Confidence = Confidence.EXTRACTED
    provenance: Provenance
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    embedding: Optional[list[float]] = Field(default=None, repr=False)
    success_count: int = 0
    fail_count: int = 0
    last_used_at: Optional[datetime] = None
    half_life_days: float = Field(
        default=30.0,
        description="Ebbinghaus decay constant — grows on successful retrieval.",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


# ───────────────────────── Skill ───────────────────────────────────────


class Skill(BaseModel):
    """A reusable procedure mined from successful trajectories.

    Skills are a subkind of Fragment with extra structural fields. Storage
    keeps the markdown body separate from the indexable description so the
    Anthropic 1%-of-context budget can drop bodies while keeping
    descriptions retrievable.
    """

    id: str
    name: str = Field(pattern=r"^[a-z][a-z0-9_\-]*$", min_length=2, max_length=64)
    description: str = Field(
        min_length=80,
        max_length=1536,
        description="One sentence. Indexed for semantic retrieval. ≥80 chars per AgDR-0014.",
    )
    triggers: list[str] = Field(
        default_factory=list,
        description="Phrases that should activate this skill in UserPromptSubmit.",
    )
    requires_mcps: list[str] = Field(
        default_factory=list,
        description="MCP servers needed for this skill to run.",
    )
    requires_secrets: list[str] = Field(
        default_factory=list,
        description="op:// references resolved at PreToolUse time.",
    )
    body: str = Field(description="Full skill body (markdown + optional examples + reference).")
    examples: list[dict[str, Any]] = Field(
        default_factory=list,
        description="≥1 input/output pair per ModularNodeSpec (AgDR-0013 Layer 4).",
    )
    eval_queries: list[dict[str, Any]] = Field(
        default_factory=list,
        description="20 auto-generated should-trigger / shouldn't-trigger pairs.",
    )
    scope: Scope = Scope.USER
    visibility: Visibility = Visibility.PRIVATE
    owner_user: str
    provenance: Provenance
    success_count: int = 0
    fail_count: int = 0
    last_used_at: Optional[datetime] = None
    minted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    honed_trials: int = Field(default=0, description="SkillWeaver sandbox trial count.")
    honed_passed: int = Field(default=0, description="How many trials passed.")
    side_effects: str = Field(default="pure")  # pure | host_write | network


# ───────────────────────── Wiring + Secrets ────────────────────────────


class WiringEntry(BaseModel):
    """A registered MCP server / CLI / model on this device."""

    name: str
    kind: str = Field(description="mcp_server | cli | model_provider")
    endpoint: Optional[str] = None
    auth_method: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    device_id: str
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "active"  # active | idle | error | revoked


class SecretRef(BaseModel):
    """Reference to a secret. NEVER stores the value."""

    ref: str = Field(pattern=r"^(op|vault|wcm)://.+$")
    resolver: str = Field(description="1password | infisical | wcm | vault")
    description: Optional[str] = None
    last_used_at: Optional[datetime] = None
    owner_user: str
    scope: Scope = Scope.USER


# ───────────────────────── Tool I/O ────────────────────────────────────


class ContextResponse(BaseModel):
    """What brain.context returns to a hook on UserPromptSubmit."""

    skills: list[Skill] = Field(default_factory=list)
    facts: list[Fragment] = Field(default_factory=list)
    wiring: list[WiringEntry] = Field(default_factory=list)
    secret_refs: list[SecretRef] = Field(default_factory=list)
    setups: list[Fragment] = Field(default_factory=list)
    injection: str = Field(
        default="",
        description="Pre-formatted markdown block ready to prepend to the system prompt.",
    )
    retrieval_ms: float = 0.0
    scope_filter: list[Scope] = Field(default_factory=list)


class WriteOp(BaseModel):
    """A Mem0-style op against the brain (ADD/UPDATE/DELETE/NOOP)."""

    op: WriteOpType
    fragment: Optional[Fragment] = None
    fragment_id: Optional[str] = None  # for DELETE
    updates: Optional[dict[str, Any]] = None  # for UPDATE


class WriteResponse(BaseModel):
    ops_applied: int = 0
    fragments_added: int = 0
    fragments_updated: int = 0
    fragments_deleted: int = 0
    fragments_noop: int = 0
    write_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)


class SkillMintResult(BaseModel):
    """What brain.skill_mint returns after analysing a trace."""

    queued: bool = False
    immediate_skill: Optional[Skill] = None
    proposed_name: Optional[str] = None
    novelty_score: float = 0.0
    success_score: float = 0.0
    will_hone: bool = False
    reason: str = ""


class WiringAnnounceRequest(BaseModel):
    """Sent on SessionStart hook from each client."""

    device_id: str
    entries: list[WiringEntry] = Field(default_factory=list)
    secret_refs: list[SecretRef] = Field(default_factory=list)
    cwd: Optional[str] = None
    git_remote: Optional[str] = None


class WiringAnnounceResponse(BaseModel):
    registered: int = 0
    skipped: int = 0
    revoked: int = 0
    scope_hint: Scope = Scope.USER
    project_id_hint: Optional[str] = None
    firm_id_hint: Optional[str] = None
