"""Library module — the agent's + user's living inventory of node-types.

Reference: docs/agdr/AgDR-0012-architecture-direction-x.md §"Mandate 1 — LIBRARY FIRST"
Reference: docs/agdr/AgDR-0013-multi-llm-library-first-enforcement.md §"Composer tool surface"
Reference: docs/agdr/AgDR-0014-library-design-system.md (design tokens this library enforces)

The library is the runtime + lookup surface behind the Composer tools:

    library.search(intent, input_schema?, output_schema?)
    library.list_node_types(category?)
    library.inspect(node_type)
    library.create_node_type(spec)
    library.delete_node_type(node_type)

Storage: in-process `dict[type_name → ModularNodeSpec.model_dump()]` plus a
ranking helper for `search`. Persistence is added in M3 when the library
backs onto the user's `%LOCALAPPDATA%/ArchHub/library/` folder.

Search algorithm (v1 — deterministic, no embedding):
    score(spec, intent) =
        + 50 if intent substring in display_name (case-insensitive)
        + 30 if intent substring in description
        + 20 if intent substring in any example.note
        + 10 if intent substring in type
        +  5 per shared significant word (stop-word filtered)
        + 25 if optional category filter matches
    Top-N sorted by score descending; ties broken by display_name
    alphabetical. Threshold ≥ 5 (otherwise treated as no match).

A future M3.x can swap in embeddings. The Composer tool layer is unchanged
because the interface is `(intent, optional schemas) -> [{id, name, type,
score}]`.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from library_validator import (
    ModularNodeSpec,
    ValidationResult,
    validate as validate_spec,
)


# ---------------------------------------------------------------------------
# Registry — in-process. Keyed by `type` (e.g. "data.constant").


_REGISTRY: dict[str, dict] = {}


# Stop words filtered out of word-level overlap scoring — common English
# tokens that carry no domain meaning.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "in", "is", "it", "its", "of", "on", "that", "the", "to", "was",
    "were", "will", "with", "do", "does", "this", "these", "those",
})


# Similarity threshold above which `search` returns a result as a "match".
# AgDR-0012 §LIBRARY FIRST rule 2: "≥0.75 cosine similarity on intent +
# structural match on I/O schemas → USE existing node." Until we have
# real embeddings, v1 maps that to a score ≥ 30 (= display_name hit OR
# description hit). Below 30 the result is "no match" — the agent should
# propose `library.create_node_type` instead.
MATCH_THRESHOLD = 30


# ---------------------------------------------------------------------------
# Public API — the 5 Composer tools


class RegistrationError(Exception):
    """Raised when library.create_node_type rejects a spec."""

    def __init__(self, violations: list[str]):
        super().__init__(
            "spec rejected by validator — fix the violations and retry: "
            + "; ".join(violations)
        )
        self.violations = violations


class DuplicateTypeError(Exception):
    """Raised when library.create_node_type is asked to register a type
    that already exists. The agent should call `library.inspect` first
    and decide whether to use the existing node, delete + re-register,
    or pick a new type name.
    """


class UnknownTypeError(Exception):
    """Raised when library.inspect / library.delete_node_type names a
    type that is not registered.
    """


def search(intent: str,
           input_schema: Optional[dict] = None,
           output_schema: Optional[dict] = None,
           category: Optional[str] = None,
           limit: int = 8) -> list[dict]:
    """Find node-types in the library that match the caller's intent.

    Returns a list of `{id, name, type, category, score}` sorted by
    score descending, capped at `limit`. Below-threshold results are
    dropped — an empty list IS a valid answer meaning "no match,
    propose creating a new node."

    `input_schema` / `output_schema` are accepted but UNUSED in v1
    (signature-matching arrives with M3.x). v1 ranks on intent text only.
    """
    if not intent or not isinstance(intent, str):
        return []

    intent_lc = intent.lower().strip()
    if not intent_lc:
        # An empty intent matches every spec via the "" substring rule
        # (`"" in any_string` is True). Guard against this so a caller
        # passing whitespace doesn't get the whole library back.
        return []
    intent_words = _significant_words(intent_lc)

    out: list[tuple[int, dict]] = []
    for spec in _REGISTRY.values():
        score = _score(spec, intent_lc, intent_words)
        if category and spec.get("category") == category:
            score += 25
        if score >= MATCH_THRESHOLD:
            out.append((score, spec))

    out.sort(key=lambda pair: (-pair[0], pair[1].get("display_name", "")))
    return [
        {
            "id": spec["type"],
            "name": spec["display_name"],
            "type": spec["type"],
            "category": spec.get("category"),
            "score": score,
        }
        for score, spec in out[:limit]
    ]


def list_node_types(category: Optional[str] = None) -> list[dict]:
    """List every registered node-type, optionally filtered by category.

    Returns minimal summaries `{id, name, type, category, side_effects,
    status}`. Use `inspect()` to fetch the full spec.
    """
    items = list(_REGISTRY.values())
    if category:
        items = [s for s in items if s.get("category") == category]
    items.sort(key=lambda s: (s.get("category", ""), s.get("display_name", "")))
    return [
        {
            "id": s["type"],
            "name": s["display_name"],
            "type": s["type"],
            "category": s.get("category"),
            "side_effects": s.get("side_effects", "pure"),
            "status": s.get("status", "registered"),
        }
        for s in items
    ]


def inspect(node_type: str) -> dict:
    """Return the full ModularNodeSpec dict for one registered type.

    Raises `UnknownTypeError` if no such type is registered.
    """
    if node_type not in _REGISTRY:
        raise UnknownTypeError(f"no registered node-type named '{node_type}'")
    return dict(_REGISTRY[node_type])  # shallow copy — caller can't mutate


def create_node_type(spec: dict) -> dict:
    """Validate + register a new node-type.

    On success returns `{id, registered: True, type}`.
    On failure raises:
      - RegistrationError(violations) — spec is not modular.
      - DuplicateTypeError — type already registered.
    """
    result: ValidationResult = validate_spec(spec)
    if not result.ok:
        raise RegistrationError(result.violations)

    # Validator passed — re-parse via the Pydantic model so we know the
    # stored shape is canonical (defaults filled, types narrowed).
    validated = ModularNodeSpec.model_validate(spec).model_dump()
    type_name = validated["type"]
    if type_name in _REGISTRY:
        raise DuplicateTypeError(
            f"node-type '{type_name}' is already registered "
            f"(use library.inspect to view, or library.delete_node_type "
            f"to remove first)"
        )
    _REGISTRY[type_name] = validated
    return {"id": type_name, "registered": True, "type": type_name}


def delete_node_type(node_type: str) -> dict:
    """Remove a node-type from the library.

    Raises `UnknownTypeError` if no such type. Returns `{id, ok: True}`
    on success. User-confirmation is the caller's responsibility (the
    bridge surfaces a dialog before invoking this).
    """
    if node_type not in _REGISTRY:
        raise UnknownTypeError(f"no registered node-type named '{node_type}'")
    del _REGISTRY[node_type]
    return {"id": node_type, "ok": True}


# ---------------------------------------------------------------------------
# Test / introspection helpers


def reset_registry() -> None:
    """Empty the in-process registry. Tests call this before seeding."""
    _REGISTRY.clear()


def registry_size() -> int:
    return len(_REGISTRY)


# ---------------------------------------------------------------------------
# Persistence (AgDR-0013 §"What ships in M3").
# Disk durability so AI-minted nodes + user-created skills survive a restart.
# Thin wrappers over `library_persistence`; library.py owns the registry,
# library_persistence.py owns the disk format.


def save_to_disk(path=None):
    """Persist the in-process registry to disk.

    Returns the path written. Callers normally invoke this after
    create_node_type / delete_node_type — the bridge will call it on a
    debounced schedule.
    """
    import library_persistence  # local to avoid import cycle on cold boot
    return library_persistence.save(_REGISTRY, path)


def load_from_disk(path=None) -> int:
    """Hydrate the in-process registry from disk.

    Returns the number of entries loaded. Each entry is RE-VALIDATED through
    the Pydantic ModularNodeSpec — a disk entry that no longer satisfies
    the contract (e.g. an old format predating AgDR-0014 token changes) is
    dropped with a violation list logged.

    Idempotent for entries already in the registry — duplicates from disk
    overwrite the in-process copy (disk is the source of truth on cold
    boot).
    """
    import library_persistence

    loaded = library_persistence.load(path)
    accepted = 0
    for type_name, spec in loaded.items():
        result = validate_spec(spec)
        if not result.ok:
            # Drift / corruption — skip the entry. Don't fail boot.
            continue
        canonical = ModularNodeSpec.model_validate(spec).model_dump()
        _REGISTRY[canonical["type"]] = canonical
        accepted += 1
    return accepted


# ---------------------------------------------------------------------------
# Scoring helpers


def _significant_words(text: str) -> set[str]:
    """Lower-case tokens with stop-words filtered out."""
    tokens = re.findall(r"[a-z][a-z0-9_]*", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _score(spec: dict, intent_lc: str, intent_words: set[str]) -> int:
    """Score one spec against a lower-cased intent string + its words.

    Hits stack — the same spec can earn from multiple categories.
    """
    score = 0

    display = (spec.get("display_name") or "").lower()
    description = (spec.get("description") or "").lower()
    type_name = (spec.get("type") or "").lower()

    if intent_lc in display:
        score += 50
    if intent_lc in description:
        score += 30
    if intent_lc in type_name:
        score += 10

    # Example.note hits (helpful — examples carry intent variations).
    for ex in spec.get("examples") or []:
        note = (ex.get("note") or "").lower()
        if note and intent_lc in note:
            score += 20
            break  # at most once per spec

    # Significant-word overlap — covers cases where the intent uses
    # different phrasing than display_name / description but shares
    # domain words.
    spec_text = " ".join([
        display, description, type_name,
        " ".join(ex.get("note") or "" for ex in spec.get("examples") or []),
    ])
    spec_words = _significant_words(spec_text)
    overlap = intent_words & spec_words
    score += 5 * len(overlap)

    return score
