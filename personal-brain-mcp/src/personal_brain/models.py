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
    DOCUMENT = "document"  # docs/*.md indexed via extractors/docs.py (Track C)
    # Brain #31 multimodal (founder ask 2026-05-26): geometry + pictures.
    # GEOMETRY = BRep / mesh / wall-list / etc flowing on wires (Speckle
    # Base subtree serialised). IMAGE = render / sketch / viewport snapshot
    # / reference photo. Both indexed by perceptual_hash + CLIP-style
    # vision embedding (Fragment.embedding field; vision index in slice 2).
    GEOMETRY = "geometry"
    IMAGE = "image"
    # BRV-09 thinking-system projector (founder, 2026-06-17): versioned
    # governance fragments that the projector compiles into a CLAUDE.md
    # projection (and, future, settings.json / pre-prompts). A MANDATE is a
    # founder rule; a HOOK is an automation contract (UserPromptSubmit /
    # PostToolUse / Stop wiring); a PRACTICE is a recommended convention.
    # These are FOUNDER-SIGNED: a bump to a MANDATE without is_root_authority
    # is refused (see projector.bump_mandate), mirroring requirement_tree's
    # set_verdict self-certification guard.
    MANDATE = "mandate"
    HOOK = "hook"
    PRACTICE = "practice"


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
    # Brain #31 multimodal (2026-05-26): perceptual hash for cheap
    # similarity lookup BEFORE running the more expensive CLIP-style
    # embedding match. Empty for non-multimodal kinds. 64-bit pHash
    # rendered as a 16-char hex string keeps the storage cheap + index-
    # friendly. Geometry uses a derived hash (volume / aabb / vertex
    # count). Images use phash.
    perceptual_hash: Optional[str] = Field(default=None, max_length=64)
    # Brain #31 multimodal: blob payload pointer when the fragment carries
    # binary content (geometry serialisation / image bytes). Points to a
    # sidecar file under `<brain_root>/blobs/<sha256[:2]>/<sha256>.{ext}`
    # so SQLite stays small and the blob can be re-uploaded to cloud
    # archive (Brain #32 day-2) independently.
    blob_path: Optional[str] = Field(default=None, max_length=512)
    blob_mime: Optional[str] = Field(default=None, max_length=64)
    blob_bytes: int = 0
    # AgDR-0054 per-trace schema (founder-signed 2026-06-10). These ride on a
    # trace/session Fragment so the export dam can compute training/export tiers,
    # poisoning provenance, and unlearning (export-gating, since weights-level
    # erasure is impossible). Defaults MATCH the storage column defaults exactly
    # (storage.py:79-87) so an untagged Fragment is human_verified +
    # firm_private_only — legacy data is never auto-trained into the collective.
    # The storage write path persists these (write_fragment) and reads them back
    # (_row_to_fragment); the dam selects on them (export_trainable_fragments).
    origin_kind: str = Field(
        default="human_verified",
        description="human_verified | model_generated — keys the train/eval tier.",
    )
    generating_model_id: Optional[str] = Field(
        default=None,
        description="Model that produced the trace (e.g. claude-*); keys the ToS/legal tier.",
    )
    training_rights_tier: str = Field(
        default="firm_private_only",
        description="collective_ok | firm_private_only | quarantine_never_trains.",
    )
    format_shape_descriptor: Optional[str] = Field(
        default=None,
        description="prompt->tool->result fingerprint (mix + per-format poison cap).",
    )
    content_hash_pre: Optional[str] = Field(
        default=None,
        description="Pre-redaction integrity hash (Carlini split-view) + dedup key.",
    )
    content_hash_post: Optional[str] = Field(
        default=None,
        description="Post-redaction hash; train<->eval decontamination scan.",
    )
    action_payload: Optional[str] = Field(
        default=None,
        description="JSON: tool-calls + structured outcomes (Tier-0, ALWAYS trainable, ArchHub-owned).",
    )
    language_payload: Optional[str] = Field(
        default=None,
        description="JSON: prose (Tier-1 human / Tier-2 provider-prose, gated).",
    )
    quarantine_flag: bool = Field(
        default=False,
        description="True = never trains, never recalls (stored as 0/1).",
    )
    success_count: int = 0
    fail_count: int = 0
    last_used_at: Optional[datetime] = None
    half_life_days: float = Field(
        default=30.0,
        description="Ebbinghaus decay constant — grows on successful retrieval.",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


# ──────────────── Sibling-version reconcile model (BRV-12) ──────────────
#
# AgDR-0044 acceptance #5, decision B: concurrent edits to ONE fragment id do
# NOT last-writer-wins. When a divergent write arrives (a different value whose
# HLC is not a causal descendant of the stored head), BOTH values are retained
# as SIBLING versions and a reconcile record is attached, so the conflict is
# resolvable instead of silently dropping a user's edit.
#
# These ride inside `Fragment.extra` (keys `__siblings__` / `__reconcile__`) —
# ONE-SYSTEM: no new table, no schema migration; they round-trip through the
# existing `extra_json` column. The head row keeps the highest-HLC value so
# every existing reader/search path is unchanged; the losing branch lives on as
# a sibling for the reconcile UI/agent to merge.


class FragmentVersion(BaseModel):
    """One value-branch of a fragment, with the clock + origin that produced it.

    `verdict` is the reconcile state of THIS branch: ``head`` (the value the
    fragment row currently serves), ``sibling`` (a retained concurrent branch
    awaiting reconcile), or ``merged``/``discarded`` once a reconcile resolves.
    """

    value: str = Field(description="The branch's fragment text/value.")
    hlc: str = Field(description="Hybrid Logical Clock (16-char hex) of this write.")
    source: str = Field(
        default="",
        description="Origin of the write — device id / sync peer / agent.",
    )
    verdict: str = Field(
        default="sibling",
        description="head | sibling | merged | discarded — this branch's state.",
    )
    parent_hlc: Optional[str] = Field(
        default=None,
        description="HLC this write descended from (None = no parent observed).",
    )
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReconcileRecord(BaseModel):
    """Conflict marker attached to a fragment when divergent siblings exist.

    ``state == 'pending'`` means at least two concurrent value-branches are
    live and a human/agent must reconcile; ``resolved`` once a winner/merge is
    chosen. Stored under ``Fragment.extra['__reconcile__']``.
    """

    state: str = Field(default="pending", description="pending | resolved.")
    sibling_count: int = Field(
        default=0, description="Number of retained concurrent branches."
    )
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_hlc: Optional[str] = Field(
        default=None, description="HLC of the branch chosen on resolution."
    )
    note: str = Field(default="", description="Optional reconcile note.")


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
