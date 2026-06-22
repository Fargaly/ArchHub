"""Brain-as-folders: list / edit / delete REAL brain facts for the UI browser.

The founder (2026-06-21) wanted the brain to surface as an *explorable +
editable folder system*, not a flat search and a do-nothing graph blob. This
module is the READ + WRITE backend the BrainFolders panel (studio-lm.jsx) talks
to through the bridge — every record is a real `Fragment` row in `brain.db`, so
the tree is the live store and edits persist.

ONE-SYSTEM (founder mandate): we do NOT mint a new store. Everything here walks
the existing `BrainStore.list_fragments` / `get_fragment` / `write_fragment` /
`delete_fragment` methods (the same safe writers `brain_restore` uses), and the
folder grouping reuses the EXISTING `organize.facet_for` facet logic so the
tree's folders match the rest of the brain's vocabulary.

Folder grouping ("type") — one fact lands in exactly one top-level folder:

    user        kind == fact   AND facet == Memory   (general knowledge / rules)
    feedback    predicate / text marks it founder feedback
    projects    kind == fact   AND facet == Memory   AND project-tagged
    reference   kind in (document, setup)            (reference material)
    decisions   facet == Decisions
    capability  facet == Capability
    skills      kind == skill
    traces      kind == trace

The four the founder named (User · Feedback · Projects · Reference) are always
present + ordered first; the rest follow so nothing is hidden (MAKE-IT-REAL).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .models import Fragment, FragmentKind
from .organize import facet_for, FACET_DECISIONS, FACET_CAPABILITY


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Top-level folder order the UI renders. The four founder-named folders lead.
FOLDER_ORDER = [
    "user", "feedback", "projects", "reference",
    "decisions", "capability", "skills", "traces",
]

FOLDER_LABEL = {
    "user": "User",
    "feedback": "Feedback",
    "projects": "Projects",
    "reference": "Reference",
    "decisions": "Decisions",
    "capability": "Capability",
    "skills": "Skills",
    "traces": "Traces",
}

# Words in a fact's text/predicate that mark it as founder FEEDBACK (the
# "feedback_*" memory class). Conservative — only the explicit signals.
_FEEDBACK_MARKERS = ("feedback", "founder:", "mandate", "don't ", "never ", "always ")


def folder_for(frag: Fragment) -> str:
    """Map one fragment to exactly one top-level folder (its "type")."""
    kind = frag.kind
    if kind == FragmentKind.SKILL:
        return "skills"
    if kind == FragmentKind.TRACE:
        return "traces"
    if kind in (FragmentKind.DOCUMENT, FragmentKind.SETUP):
        return "reference"
    facet = facet_for(frag)
    if facet == FACET_DECISIONS:
        return "decisions"
    if facet == FACET_CAPABILITY:
        return "capability"
    # Memory-facet facts: split feedback / projects / user.
    pred = (frag.predicate or "").strip().lower()
    text = (frag.text or "").lower()
    if pred == "feedback" or any(m in text for m in _FEEDBACK_MARKERS):
        return "feedback"
    # Projects folder keys on EITHER the ACL-gated project_id OR the ACL-free
    # extra.project tag that _tag_projects (organize) actually populates. Before,
    # only project_id was checked — and that column is deliberately never set —
    # so project-coded facts (BBC4/P-679/…) were tagged but never surfaced here,
    # leaving the Projects folder permanently empty even when codes were detected.
    if frag.project_id or (frag.extra or {}).get("project"):
        return "projects"
    return "user"


def _short(text: str, n: int = 140) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t if len(t) <= n else (t[: n - 1].rstrip() + "…")


def _fact_record(frag: Fragment) -> dict[str, Any]:
    """One fact → the flat record the UI tree row + detail pane consume.

    `name` is a short title (subject, else first line); `desc` is the short
    one-liner; `body` is the full text (shown when a fact is clicked).
    """
    body = (frag.text or "").strip()
    first_line = body.split("\n", 1)[0].strip()
    name = (frag.subject or "").strip() or _short(first_line, 80) or frag.id[:10]
    return {
        "id": frag.id,
        "name": name,
        "desc": _short(body),
        "body": body,
        "type": folder_for(frag),
        "kind": frag.kind.value,
        "scope": frag.scope.value,
        "predicate": frag.predicate or "",
        "project_id": frag.project_id or (frag.extra or {}).get("project") or "",
        "archived": frag.valid_until is not None,
    }


def list_facts(
    store: Any,
    *,
    owner_user: Optional[str] = None,
    include_archived: bool = False,
    limit: int = 100_000,
) -> dict[str, Any]:
    """Enumerate every brain fact, grouped into folders for the UI tree.

    Returns {ok, total, folders:[{id,label,count,facts:[record,...]}, ...]}.
    Folders are returned in FOLDER_ORDER; the four founder-named ones always
    appear (even when empty) so the tree shape is stable.
    """
    try:
        frags = store.list_fragments(owner_user=owner_user, limit=limit)
    except Exception as ex:  # pragma: no cover - defensive
        return {"ok": False, "error": f"list_fragments: {ex}", "folders": []}

    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in FOLDER_ORDER}
    total = 0
    for frag in frags:
        if frag.valid_until is not None and not include_archived:
            continue
        rec = _fact_record(frag)
        buckets.setdefault(rec["type"], []).append(rec)
        total += 1

    # Stable order: FOLDER_ORDER first, then any unexpected extra buckets.
    ordered_keys = FOLDER_ORDER + [k for k in buckets if k not in FOLDER_ORDER]
    folders = []
    for key in ordered_keys:
        facts = buckets.get(key, [])
        # Always surface the four founder-named folders even when empty.
        if not facts and key not in ("user", "feedback", "projects", "reference"):
            continue
        folders.append({
            "id": key,
            "label": FOLDER_LABEL.get(key, key.title()),
            "count": len(facts),
            "facts": facts,
        })
    return {"ok": True, "total": total, "folders": folders}


def edit_fact(store: Any, fragment_id: str, text: str) -> dict[str, Any]:
    """Edit a fact's text in place. Persists through the safe write path
    (`write_fragment`), never a raw sqlite write. Returns {ok, id, edited}."""
    if not fragment_id:
        return {"ok": False, "error": "missing fragment_id", "edited": False}
    new_text = (text or "").strip()
    if not new_text:
        return {"ok": False, "error": "empty text", "edited": False}
    frag = store.get_fragment(fragment_id)
    if frag is None:
        return {"ok": False, "error": "fragment not found",
                "id": fragment_id, "edited": False}
    if frag.text == new_text:
        return {"ok": True, "id": fragment_id, "edited": False,
                "note": "unchanged"}
    frag.text = new_text
    # Re-derive the subject's first line so the tree title stays in sync when
    # the subject was just the leading text (don't clobber a real subject).
    frag.last_used_at = _now()
    # Force a re-embed on next organize pass: text changed → stale embedding.
    frag.embedding = None
    try:
        store.write_fragment(frag)
    except Exception as ex:  # pragma: no cover - defensive
        return {"ok": False, "error": f"write_fragment: {ex}",
                "id": fragment_id, "edited": False}
    return {"ok": True, "id": fragment_id, "edited": True}


def delete_fact(store: Any, fragment_id: str, *, hard: bool = False) -> dict[str, Any]:
    """Delete a fact. Default is a SOFT delete (set valid_until=now → the fact
    drops out of the active tree but is recoverable via brain.restore, matching
    MAKE-IT-REAL-NEVER-TRIM). Pass hard=True to remove the row entirely.
    Returns {ok, id, deleted, hard}."""
    if not fragment_id:
        return {"ok": False, "error": "missing fragment_id", "deleted": False}
    if hard:
        try:
            ok = store.delete_fragment(fragment_id)
        except Exception as ex:  # pragma: no cover - defensive
            return {"ok": False, "error": f"delete_fragment: {ex}",
                    "id": fragment_id, "deleted": False}
        return {"ok": bool(ok), "id": fragment_id, "deleted": bool(ok), "hard": True}
    frag = store.get_fragment(fragment_id)
    if frag is None:
        return {"ok": False, "error": "fragment not found",
                "id": fragment_id, "deleted": False}
    if frag.valid_until is not None:
        return {"ok": True, "id": fragment_id, "deleted": True, "hard": False,
                "note": "already archived"}
    frag.valid_until = _now()
    try:
        store.write_fragment(frag)
    except Exception as ex:  # pragma: no cover - defensive
        return {"ok": False, "error": f"write_fragment: {ex}",
                "id": fragment_id, "deleted": False}
    return {"ok": True, "id": fragment_id, "deleted": True, "hard": False}
