"""Thinking-system projector — versioned brain governance → CLAUDE.md.

Closes BRV-09. The brain already holds memory, skills, setups, wiring and the
requirement-tree ledger, but the GOVERNANCE layer — the mandates, hook
contracts and practices that shape how every agent on the repo behaves — lived
ONLY as hand-edited prose in `CLAUDE.md` / `AGENTS.md`. There was no projector
module and `FragmentKind` had no MANDATE / HOOK / PRACTICE, so those rules were
not versioned brain fragments and could not be COMPILED to the agent-facing
projection. That made them un-auditable (who changed which mandate, when?) and
un-signable (anyone editing the markdown could weaken a founder mandate).

This module makes governance a first-class, VERSIONED, FOUNDER-SIGNED brain
artifact and PROJECTS it:

    record_fragment(...)        — write/version a MANDATE | HOOK | PRACTICE
    bump_mandate(...)           — version-bump a MANDATE; REFUSED without
                                   is_root_authority=True (founder-signed)
    project_claude_md(...)      — compile the ACTIVE governance fragments into a
                                   deterministic CLAUDE.md projection string
    write_projection(path, ...) — same, written to a file artifact

WHY A SEPARATE PROJECTION PATH (not the live CLAUDE.md):
    The hand-authored `CLAUDE.md` stays the human source of truth. The projector
    emits to a DISTINCT artifact path (default `<brain_root>/projections/CLAUDE.brain.md`,
    overridable) so the compiled-from-brain view never clobbers the human file —
    they are reconciled deliberately, not silently. Mirrors how
    `requirement_tree` persists ADDITIVELY in `brain_meta` and never touches the
    `fragments` schema.

ONE-SYSTEM / LIBRARY-FIRST:
    Governance fragments are stored as ordinary `Fragment` rows (kind ∈
    {mandate, hook, practice}) via the existing `BrainStore.write_fragment` — NO
    new table, NO schema migration. Versioning + active-flag ride in
    `Fragment.extra` ({"version": N, "active": bool, "mandate_key": "..."}),
    the same place `doc_links` reads `extra.deps`. Provenance (who/when/which
    agent) is the existing immutable `Provenance` on every fragment, which is
    exactly the audit trail the governance layer was missing.

FOUNDER-SIGNED (the mandate-bump guard):
    A MANDATE is the founder's word. `bump_mandate` raises `PermissionError`
    unless `is_root_authority=True` — the SAME shape as
    `requirement_tree.set_verdict`'s self-certification refusal. HOOK / PRACTICE
    fragments are routine and don't require the founder gate.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .models import Confidence, Fragment, FragmentKind, Provenance, Scope, Visibility

if TYPE_CHECKING:  # avoid an import cycle; only needed for typing
    from .storage import BrainStore


# Governance kinds the projector compiles, in the order they appear in the
# projection (mandates first — they are supreme — then hooks, then practices).
PROJECTED_KINDS: tuple[FragmentKind, ...] = (
    FragmentKind.MANDATE,
    FragmentKind.HOOK,
    FragmentKind.PRACTICE,
)

_SECTION_TITLE = {
    FragmentKind.MANDATE: "MANDATES (founder-signed, supreme)",
    FragmentKind.HOOK: "HOOKS (automation contracts)",
    FragmentKind.PRACTICE: "PRACTICES (recommended conventions)",
}

# Default projection artifact path under the brain root (kept OUT of the
# hand-authored CLAUDE.md — see module docstring).
DEFAULT_PROJECTION_RELPATH = "projections/CLAUDE.brain.md"


# ─────────────────────────── id + key helpers ──────────────────────────


def _mandate_key(title: str) -> str:
    """Stable identity for a governance rule across versions: a slug of its
    title. A bump reuses the key (same rule, new version)."""
    slug = "".join(c.lower() if c.isalnum() else "-" for c in title.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "untitled"


def _fragment_id(kind: FragmentKind, key: str, version: int) -> str:
    """Content-derived, version-stamped id so each version is its own row and
    history is preserved (never overwritten) — the audit trail."""
    h = hashlib.sha256()
    h.update(f"{kind.value}\x1f{key}\x1f{version}".encode("utf-8"))
    return f"gov-{kind.value}-{h.hexdigest()[:16]}"


def _prov(agent: str, user: str) -> Provenance:
    return Provenance(
        contributing_agent=agent,
        contributing_user=user,
        created_at=datetime.now(timezone.utc),
    )


# ─────────────────────────── read helpers ──────────────────────────────


def _all_governance(
    store: "BrainStore", *, owner_user: str, kind: Optional[FragmentKind] = None,
) -> list[Fragment]:
    kinds = [kind] if kind is not None else list(PROJECTED_KINDS)
    out: list[Fragment] = []
    for fk in kinds:
        out.extend(store.list_fragments(kinds=[fk], owner_user=owner_user, limit=10_000))
    return out


def latest_versions(
    store: "BrainStore", *, owner_user: str, kind: Optional[FragmentKind] = None,
    active_only: bool = True,
) -> dict[str, Fragment]:
    """Newest version of each governance rule, keyed by mandate_key.

    A rule with multiple stored versions resolves to its highest `extra.version`
    (every version is its own row — history is intact). `active_only` drops
    rules whose newest version is retired (`extra.active is False`).
    """
    by_key: dict[str, Fragment] = {}
    for f in _all_governance(store, owner_user=owner_user, kind=kind):
        extra = f.extra or {}
        key = str(extra.get("mandate_key") or _mandate_key(f.subject or f.text[:40]))
        ver = int(extra.get("version", 1) or 1)
        cur = by_key.get(key)
        if cur is None or int((cur.extra or {}).get("version", 1) or 1) < ver:
            by_key[key] = f
    if active_only:
        by_key = {
            k: v for k, v in by_key.items()
            if (v.extra or {}).get("active", True)
        }
    return by_key


def current_version(store: "BrainStore", *, owner_user: str, title: str) -> int:
    """Highest stored version for the rule identified by `title` (0 if none)."""
    key = _mandate_key(title)
    best = 0
    for f in _all_governance(store, owner_user=owner_user):
        extra = f.extra or {}
        if str(extra.get("mandate_key") or "") == key:
            best = max(best, int(extra.get("version", 1) or 1))
    return best


# ─────────────────────────── write / version ───────────────────────────


def record_fragment(
    store: "BrainStore",
    *,
    kind: FragmentKind,
    title: str,
    body: str,
    owner_user: str = "founder",
    agent: str = "projector",
    scope: Scope = Scope.USER,
    is_root_authority: bool = False,
) -> Fragment:
    """Write (or version-bump) a governance fragment of `kind`.

    If a rule with the same title (→ mandate_key) already exists, this creates
    the NEXT version (preserving prior versions as their own rows — the audit
    history). For a MANDATE the founder gate applies on every bump (version ≥ 2):
    a new version of an existing mandate without `is_root_authority=True` is
    REFUSED, because re-stating a founder mandate is a founder-only act.

    The FIRST version of a mandate (version 1, the initial codification) is
    allowed without the gate so the brain can be seeded; subsequent edits to a
    founder mandate require the founder. HOOK / PRACTICE never require the gate.
    """
    if kind not in PROJECTED_KINDS:
        raise ValueError(
            f"projector only records {[k.value for k in PROJECTED_KINDS]}, "
            f"got {kind.value}"
        )
    key = _mandate_key(title)
    prev = current_version(store, owner_user=owner_user, title=title)
    version = prev + 1

    if kind is FragmentKind.MANDATE and prev >= 1 and not is_root_authority:
        raise PermissionError(
            f"mandate bump refused: re-stating the founder mandate "
            f"'{title}' (v{prev} → v{version}) requires is_root_authority=True. "
            f"A MANDATE is the founder's word — only the root authority (the "
            f"founder) may version it. HOOK/PRACTICE fragments do not need this."
        )

    frag = Fragment(
        id=_fragment_id(kind, key, version),
        kind=kind,
        text=body,
        subject=title,
        predicate="governs",
        object=kind.value,
        scope=scope,
        visibility=Visibility.PRIVATE,
        owner_user=owner_user,
        confidence=Confidence.EXTRACTED,
        provenance=_prov(agent, owner_user),
        extra={
            "mandate_key": key,
            "version": version,
            "active": True,
            "projected": True,
            "signed_by_root": bool(is_root_authority),
        },
    )
    store.write_fragment(frag)
    return frag


def bump_mandate(
    store: "BrainStore",
    *,
    title: str,
    body: str,
    owner_user: str = "founder",
    agent: str = "founder",
    is_root_authority: bool = False,
) -> Fragment:
    """Founder-signed version bump of a MANDATE.

    Thin, explicit wrapper over `record_fragment(kind=MANDATE, ...)` that exists
    so callers (and the BRV-09 test) name the founder-signed act directly. It
    raises `PermissionError` without `is_root_authority=True`, mirroring
    `requirement_tree.set_verdict`'s self-certification refusal.
    """
    return record_fragment(
        store,
        kind=FragmentKind.MANDATE,
        title=title,
        body=body,
        owner_user=owner_user,
        agent=agent,
        is_root_authority=is_root_authority,
    )


def retire_fragment(
    store: "BrainStore", *, title: str, owner_user: str = "founder",
    agent: str = "projector", is_root_authority: bool = False,
) -> Optional[Fragment]:
    """Mark a rule's newest version inactive so it drops out of the projection.

    Retiring a MANDATE is itself a founder act (same gate as a bump). Returns the
    retired fragment, or None if the rule is unknown.
    """
    latest = latest_versions(store, owner_user=owner_user, active_only=False)
    key = _mandate_key(title)
    frag = latest.get(key)
    if frag is None:
        return None
    if frag.kind is FragmentKind.MANDATE and not is_root_authority:
        raise PermissionError(
            f"mandate retire refused: retiring the founder mandate '{title}' "
            f"requires is_root_authority=True."
        )
    extra = dict(frag.extra or {})
    extra["active"] = False
    frag.extra = extra
    store.write_fragment(frag)
    return frag


# ─────────────────────────── projection (compile) ──────────────────────


def project_claude_md(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    title: str = "ArchHub — projected governance (compiled from the brain)",
) -> str:
    """Compile the ACTIVE governance fragments into a CLAUDE.md projection.

    Deterministic: kinds in `PROJECTED_KINDS` order (mandates → hooks →
    practices); within a kind, rules sorted by mandate_key. Each rule renders
    its title (as a `##` heading carrying its version) + body. A provenance
    footer records the compile time + fragment counts so the projection is
    self-describing and auditable. Returns the markdown string; pure (no write).
    """
    latest = latest_versions(store, owner_user=owner_user, active_only=True)

    lines: list[str] = [f"# {title}", ""]
    lines.append(
        "<!-- GENERATED by personal_brain.projector — compiled from versioned "
        "brain governance fragments. Do not hand-edit; edit the brain "
        "fragments (projector.record_fragment / bump_mandate) and recompile. -->"
    )
    lines.append("")

    total = 0
    for fk in PROJECTED_KINDS:
        rules = sorted(
            (f for f in latest.values() if f.kind is fk),
            key=lambda f: str((f.extra or {}).get("mandate_key", "")),
        )
        if not rules:
            continue
        lines.append(f"## {_SECTION_TITLE[fk]}")
        lines.append("")
        for f in rules:
            ver = int((f.extra or {}).get("version", 1) or 1)
            signed = (f.extra or {}).get("signed_by_root")
            badge = " · founder-signed" if signed else ""
            lines.append(f"### {f.subject or '(untitled)'}  — v{ver}{badge}")
            lines.append("")
            lines.append((f.text or "").strip())
            lines.append("")
            total += 1

    lines.append("---")
    counts = {
        fk.value: sum(1 for f in latest.values() if f.kind is fk)
        for fk in PROJECTED_KINDS
    }
    lines.append(
        f"<!-- projection: {total} active governance fragments "
        f"({counts[FragmentKind.MANDATE.value]} mandates, "
        f"{counts[FragmentKind.HOOK.value]} hooks, "
        f"{counts[FragmentKind.PRACTICE.value]} practices) "
        f"compiled {datetime.now(timezone.utc).isoformat()} -->"
    )
    return "\n".join(lines) + "\n"


def write_projection(
    store: "BrainStore",
    *,
    path: Optional[str | Path] = None,
    owner_user: str = "founder",
) -> Path:
    """Compile + write the CLAUDE.md projection to `path` (default under the
    brain root). Returns the written path. The directory is created if absent.
    """
    md = project_claude_md(store, owner_user=owner_user)
    if path is None:
        # Brain root = the directory holding the brain .db. An in-memory store
        # (':memory:') has no on-disk root → fall back to the cwd.
        try:
            store_path = Path(str(store.path))
            root = store_path.parent if str(store_path) != ":memory:" else Path(".")
        except Exception:
            root = Path(".")
        path = root / DEFAULT_PROJECTION_RELPATH
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md, encoding="utf-8")
    return p
