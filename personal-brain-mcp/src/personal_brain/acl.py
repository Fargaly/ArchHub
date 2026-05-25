"""Bipartite access control — arXiv 2505.18279 "Collaborative Memory".

Per AgDR-0044 Slice 7. Every fragment carries immutable provenance:
contributing_agent, contributing_user, accessed_resources, timestamps.
Read policies enforce per-fragment ACL on EVERY retrieval. Write policies
gate promotion across scope boundaries with mandatory redaction.

Bipartite graph:
                user                agent              resource
                  ↘ ↙ ↗ ↖              ↘ ↙ ↗ ↖           ↘ ↙ ↗ ↖
                  fragment            fragment           fragment
                  (visible)           (used by)          (touched)

The check `can_read(reader, fragment)` walks all three edges and the
fragment's `scope` + `visibility` + `valid_from/until` window. Returns
allow / deny + audit record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .models import (
    Fragment,
    Scope,
    Skill,
    Visibility,
)


# ─────────────────────── identity ──────────────────────────────────────


@dataclass
class Identity:
    """Who is asking? Combines user identity, agent identity (which LLM),
    and current project/firm context."""

    user_id: str
    agent_id: Optional[str] = None
    project_id: Optional[str] = None
    firm_id: Optional[str] = None
    community_subscriptions: list[str] = field(default_factory=list)
    is_maintainer: bool = False  # for `global` scope writes


# ─────────────────────── decision ──────────────────────────────────────


@dataclass
class AccessDecision:
    """Result of can_read / can_write check."""

    allow: bool
    reason: str = ""
    redaction_required: bool = False
    audit_record: Optional[dict[str, Any]] = None


# ─────────────────────── reader policies ───────────────────────────────


def can_read(
    fragment: Fragment | dict[str, Any] | Skill,
    *,
    reader: Identity,
    now: Optional[datetime] = None,
) -> AccessDecision:
    """Check if `reader` may see `fragment`.

    Rules:
      - `global` + canonical → anyone
      - `community` + shared_public → reader is a community subscriber for
                                       this fragment's community_id
      - `firm` + shared_company    → reader.firm_id == fragment.firm_id
      - `project` + shared_project → reader.project_id == fragment.project_id
      - `user` + private           → reader.user_id == fragment.owner_user
      - `valid_until` must not be in the past (memories expire)
    """
    # Coerce dict to Fragment-like attribute access
    f = _as_fragment_dict(fragment)
    scope = f.get("scope")
    visibility = f.get("visibility")
    owner_user = f.get("owner_user")
    project_id = f.get("project_id")
    firm_id = f.get("firm_id")
    valid_until = f.get("valid_until")

    now = now or datetime.now(timezone.utc)

    # Expiry check
    if valid_until is not None:
        try:
            vu = (
                valid_until
                if isinstance(valid_until, datetime)
                else datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
            )
            if vu.tzinfo is None:
                vu = vu.replace(tzinfo=timezone.utc)
            if vu < now:
                return AccessDecision(
                    allow=False, reason=f"fragment expired at {vu.isoformat()}"
                )
        except Exception:
            pass  # malformed valid_until — fail open on the date check

    # Scope-by-scope rules
    if scope == Scope.GLOBAL.value:
        return _allow("global canonical — visible to all")

    if scope == Scope.COMMUNITY.value:
        com_id = f.get("community_id") or "default"
        if com_id in reader.community_subscriptions:
            return _allow(f"subscribed to community '{com_id}'")
        return AccessDecision(
            allow=False, reason=f"reader not subscribed to community '{com_id}'"
        )

    if scope == Scope.FIRM.value:
        if reader.firm_id and reader.firm_id == firm_id:
            return _allow(f"reader is in firm '{firm_id}'")
        return AccessDecision(
            allow=False,
            reason=f"reader.firm_id={reader.firm_id} != fragment.firm_id={firm_id}",
        )

    if scope == Scope.PROJECT.value:
        if reader.project_id and reader.project_id == project_id:
            return _allow(f"reader is in project '{project_id}'")
        # owner can always read their own project fragments
        if reader.user_id == owner_user:
            return _allow("reader is fragment owner")
        return AccessDecision(
            allow=False,
            reason=f"reader.project_id={reader.project_id} != fragment.project_id={project_id}",
        )

    # USER scope (default)
    if reader.user_id == owner_user:
        return _allow("reader is fragment owner")
    return AccessDecision(
        allow=False,
        reason=f"user-scoped fragment owned by '{owner_user}'; reader is '{reader.user_id}'",
    )


def _allow(reason: str) -> AccessDecision:
    return AccessDecision(allow=True, reason=reason)


def filter_for_reader(
    fragments: Iterable[Fragment | dict[str, Any] | Skill],
    *,
    reader: Identity,
    now: Optional[datetime] = None,
) -> list[Any]:
    """Apply can_read to a list, drop denied entries.

    Returns only the fragments visible to this reader. This is the call to
    plug at the END of BrainStore.search_fragments / search_skills once
    Slice 7 lands in production.
    """
    return [f for f in fragments if can_read(f, reader=reader, now=now).allow]


# ─────────────────────── writer policies ───────────────────────────────


def can_write_to_scope(
    *,
    actor: Identity,
    target_scope: Scope,
    target_project_id: Optional[str] = None,
    target_firm_id: Optional[str] = None,
    target_community_id: Optional[str] = None,
) -> AccessDecision:
    """Can `actor` write a new fragment with `target_scope`?

    Rules:
      - USER scope: anyone writes to their own user space
      - PROJECT scope: actor must be a project member (project_id matches)
      - FIRM scope: actor must be a firm seat (firm_id matches)
      - COMMUNITY scope: actor must subscribe to that community AND any
                          write to community scope MUST be redacted
                          (transform policy enforced)
      - GLOBAL scope: maintainers only
    """
    if target_scope == Scope.USER:
        return _allow("user always writes to user scope")

    if target_scope == Scope.PROJECT:
        if actor.project_id and actor.project_id == target_project_id:
            return _allow(f"actor is in project '{target_project_id}'")
        return AccessDecision(
            allow=False,
            reason=f"actor not in project '{target_project_id}'",
        )

    if target_scope == Scope.FIRM:
        if actor.firm_id and actor.firm_id == target_firm_id:
            return _allow(f"actor is firm seat '{target_firm_id}'")
        return AccessDecision(
            allow=False,
            reason=f"actor not in firm '{target_firm_id}'",
        )

    if target_scope == Scope.COMMUNITY:
        com_id = target_community_id or "default"
        if com_id not in actor.community_subscriptions:
            return AccessDecision(
                allow=False,
                reason=f"actor not subscribed to community '{com_id}'",
            )
        return AccessDecision(
            allow=True,
            reason=f"community write — redaction mandatory",
            redaction_required=True,
        )

    if target_scope == Scope.GLOBAL:
        if actor.is_maintainer:
            return _allow("maintainer writing global canonical")
        return AccessDecision(
            allow=False, reason="global scope is maintainers-only",
        )

    return AccessDecision(allow=False, reason=f"unknown scope: {target_scope}")


# ─────────────────────── promote across scopes ─────────────────────────


def can_promote(
    fragment: Fragment | dict[str, Any] | Skill,
    *,
    actor: Identity,
    target_scope: Scope,
    target_project_id: Optional[str] = None,
    target_firm_id: Optional[str] = None,
    target_community_id: Optional[str] = None,
) -> AccessDecision:
    """Can `actor` promote `fragment` to `target_scope`?

    A promote is allowed when:
      - actor owns the source fragment (or is admin of source scope)
      - actor has write rights at target_scope
      - promotion crosses a scope boundary upward (user → project → firm → community)
      - target scope demands redaction iff target ∈ {community, global}
    """
    f = _as_fragment_dict(fragment)
    source_scope = Scope(f.get("scope", "user"))

    # Must own at source
    if source_scope == Scope.USER:
        if actor.user_id != f.get("owner_user"):
            return AccessDecision(allow=False,
                                   reason="only owner can promote their user-scope fragment")
    elif source_scope == Scope.PROJECT:
        if actor.project_id != f.get("project_id"):
            return AccessDecision(allow=False,
                                   reason="must be in the source project to promote from it")
    elif source_scope == Scope.FIRM:
        if actor.firm_id != f.get("firm_id"):
            return AccessDecision(allow=False,
                                   reason="must be in the source firm to promote from it")

    # Must have write rights at target
    target_decision = can_write_to_scope(
        actor=actor, target_scope=target_scope,
        target_project_id=target_project_id,
        target_firm_id=target_firm_id,
        target_community_id=target_community_id,
    )
    if not target_decision.allow:
        return target_decision

    # Promotion direction sanity (downward = always OK; upward = stricter
    # already covered above). Same-scope = noop.
    return target_decision


# ─────────────────────── helpers ───────────────────────────────────────


def _as_fragment_dict(
    fragment: Fragment | dict[str, Any] | Skill,
) -> dict[str, Any]:
    if isinstance(fragment, dict):
        # Coerce enum-shaped strings already are strings — passthrough
        return fragment
    # Pydantic model — model_dump
    try:
        d = fragment.model_dump(mode="json")
    except Exception:
        d = dict(fragment.__dict__)
    # Ensure scope/visibility are strings
    if "scope" in d and hasattr(d["scope"], "value"):
        d["scope"] = d["scope"].value
    if "visibility" in d and hasattr(d["visibility"], "value"):
        d["visibility"] = d["visibility"].value
    return d
