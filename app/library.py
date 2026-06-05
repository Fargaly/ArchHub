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


# Behaviour keys that live on the runner side (AgDR-0038 custom_nodes
# contract) but have no field on the library's ModularNodeSpec model. We
# carry them VERBATIM on the stored library entry so the minted node's real
# executor survives persistence — `model_dump()` would otherwise drop them.
_BEHAVIOUR_KEYS = ("impl", "code")


def _with_behaviour(stored: dict, raw: Optional[dict]) -> dict:
    """Return a copy of the canonical spec with any `impl`/`code` body from
    the raw spec folded back in, so the behaviour survives `save_to_disk`
    + the next boot's `load_from_disk` re-validation (extra keys are
    ignored by the validator + round-tripped by library_persistence)."""
    out = dict(stored)
    raw = raw or {}
    for key in _BEHAVIOUR_KEYS:
        if key in raw and key not in out:
            out[key] = raw[key]
    return out


# Types the library mirror itself registered into the workflow runner
# registry. The library OWNS these and may freely replace them (an edited
# re-mint) or drop them (a delete). It must NEVER touch a runner entry it
# did not create — those are the engine's BUILT-IN executors (data.constant,
# control.if, connector.run, …), many of which the library SEED set also
# describes. A bare library description re-registering one as a passthrough
# would clobber the real executor (data.constant would emit None). Gap-fill
# only: the mirror closes the trap for NODES THE RUNNER LACKS; it is not a
# second registrar for primitives the engine already owns (ONE-SYSTEM).
_MIRRORED: set[str] = set()


def _mirror_to_runner(stored: dict, raw: Optional[dict] = None) -> None:
    """Bridge a library-minted spec into the workflow RUNNER's registry.

    Closes the DUAL-REGISTRY TRAP (R5): `_REGISTRY` here is the
    LIBRARY-FIRST inventory the Composer + LLM tools read, but the runner
    cooks from `app.workflows.registry._REGISTRY`, a SEPARATE store keyed
    by the same `type`. A node minted through the library never reached
    the runner, so a user/AI-minted node could not cook.

    We REUSE the one in-place registration path —
    `workflows.custom_nodes.register_spec` — which pops any prior binding,
    builds the executor (passthrough / python / connector / ai / graph via
    `_build_executor`), and registers `(NodeSpec, executor)` for the
    runner. No parallel mechanism (ONE-SYSTEM mandate).

    GAP-FILL guard: we register into the runner ONLY when the runner has no
    executor for this type yet, OR when the library itself created the
    existing entry (an edited re-mint of a library node). We never overwrite
    an entry the library did not create — those are the engine's BUILT-IN
    executors, and the library seed set re-describes several of them
    (data.constant, control.*, connector.run). Clobbering a built-in with a
    bodyless library passthrough is the regression this guard prevents.

    `stored` is the canonical ModularNodeSpec dump (the library's source of
    truth). `raw` is the un-narrowed spec as the caller supplied it — it
    may carry an `impl`/`code` block that the ModularNodeSpec dump drops,
    so we fold those behaviour keys back in before building the executor.
    Without them a minted node would still register but only as a
    passthrough; with them the runner cooks the real body.

    Best-effort + import-local: a runner-registry hiccup (or the workflows
    package being unavailable on a cold/headless boot) must never fail a
    library mint or a disk hydrate.
    """
    try:
        from workflows import custom_nodes as _cn
        from workflows import registry as _reg
    except Exception:
        return
    type_name = stored.get("type")
    if not type_name:
        return
    # Don't shadow a built-in executor the library didn't put there.
    if _reg.get(type_name) is not None and type_name not in _MIRRORED:
        return
    bridged = dict(stored)
    raw = raw or {}
    for behaviour_key in ("impl", "code"):
        if behaviour_key in raw and behaviour_key not in bridged:
            bridged[behaviour_key] = raw[behaviour_key]
    try:
        _cn.register_spec(bridged)
        _MIRRORED.add(type_name)
    except Exception:
        # The library copy is authoritative; a failed runner mirror leaves
        # the inventory intact. The node simply won't cook until the next
        # successful registration — surfaced honestly as "no executor",
        # never a fabricated value.
        pass


def _unmirror_from_runner(type_name: str) -> None:
    """Drop a type from the runner registry when the library deletes it,
    so no orphan executor outlives its library spec. Reuses the in-place
    `custom_nodes.delete_spec` (pops the live registry; the missing
    on-disk custom-node file for a library type is a harmless no-op).

    Only drops an entry the library mirror created — a delete of a library
    node that merely DESCRIBES a built-in must not unregister the engine's
    real executor (symmetry with `_mirror_to_runner`'s gap-fill guard)."""
    if type_name not in _MIRRORED:
        return
    try:
        from workflows import custom_nodes as _cn
    except Exception:
        return
    try:
        _cn.delete_spec(type_name)
    finally:
        _MIRRORED.discard(type_name)


def create_node_type(spec: dict) -> dict:
    """Validate + register a new node-type.

    On success returns `{id, registered: True, type}`.
    On failure raises:
      - RegistrationError(violations) — spec is not modular.
      - DuplicateTypeError — type already registered.

    Registration is DUAL: the spec enters the library inventory AND is
    mirrored into the workflow runner's registry (`_mirror_to_runner`) so
    the minted node can immediately cook — closing the dual-registry trap.
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
    # The ModularNodeSpec model has no `impl`/`code` field, so model_dump()
    # DROPS the behaviour body. Persist it on the stored entry (extra keys
    # round-trip through library_persistence + survive re-validation) so a
    # node minted this session still cooks its REAL body — not a degraded
    # passthrough — after a restart. Without this, boot-load (R5's boot
    # half) would silently rebuild the executor as passthrough.
    stored = _with_behaviour(validated, spec)
    _REGISTRY[type_name] = stored
    # Reach the runner so the node cooks (R5). Pass the raw spec too so an
    # `impl`/`code` body survives into the executor build.
    _mirror_to_runner(stored, spec)
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
    # Keep the runner registry in lock-step — no orphan executor (R5).
    _unmirror_from_runner(node_type)
    return {"id": node_type, "ok": True}


# ---------------------------------------------------------------------------
# Test / introspection helpers


def reset_registry() -> None:
    """Empty the in-process registry. Tests call this before seeding.

    Also drops every runner-registry executor the library mirror created
    (R5), so a library reset leaves NO library-owned binding behind in
    `workflows.registry` — built-in executors are untouched (the mirror
    never owned them). Keeps the two stores consistent across resets."""
    _REGISTRY.clear()
    if _MIRRORED:
        for _type in list(_MIRRORED):
            _unmirror_from_runner(_type)
        # Unconditional post-condition: a reset leaves no library-owned
        # mirror state, even if the runner package was unimportable above.
        _MIRRORED.clear()


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
        # Re-attach the behaviour block the dump dropped so a re-save keeps
        # the executor across MULTIPLE restart cycles, and so the in-memory
        # entry stays the single source of truth for behaviour.
        stored = _with_behaviour(canonical, spec)
        _REGISTRY[stored["type"]] = stored
        # Boot-load must ALSO reach the runner registry (R5) — otherwise a
        # node minted in a prior session loads into the library inventory
        # on cold boot but still can't cook. `spec` is the on-disk dict,
        # which preserves any `impl`/`code` behaviour block.
        _mirror_to_runner(stored, spec)
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
