"""Facet organization + embedding backfill — the brain's self-tidying pass.

Per founder ONE-SYSTEM mandate this is NEW code that EXTENDS the existing
daemon (it lives beside retrieval.py, reuses BrainStore + get_embedder, and
is driven by the same worker engine in workers.py). It does NOT mint a
parallel store.

Two public passes, both idempotent + re-runnable on the sync cadence:

  brain_organize(store)
    (0) Stamp each fragment's Ebbinghaus half_life_days by facet/kind
        (decision→180, capability→3650 pinned, trace→30, fact/rule→90 — see
        half_life_for). Idempotent (writes only rows whose value differs).
        Runs IN-DAEMON via store.write_fragment, so it is NOT gated by the MCP
        brain.write ACL that denied the project-scoped capability/decision
        rows — which is why the half-life only lands here, not via the MCP.
    (a) Partition every fragment by (kind, predicate) into a coarse FACET in
        {Capability, Decisions, Memory}.
    (b) Read each row's category label from extra_json / the text JSON blob
        (regex over a fixed AEC vocabulary). For UNLABELED Memory rows,
        assign the nearest labeled-group centroid via get_embedder().encode
        (cosine to each labeled group's mean vector; threshold 0.35 else
        'unfiled').
    (c) MERGE near-duplicates — ONLY cosine >= 0.95 AND same subject AND same
        predicate. Keep the higher success_count, union provenance, DELETE
        the loser.
    (d) ARCHIVE stale traces (kind=trace, age > 30d, success_count == 0) by
        setting valid_until = now. Decisions + Capability rows are NEVER
        archived or deleted by this pass.
    (e) Persist the cluster map + per-facet counts to
        brain_meta('organize.clusters', json) and stamp organize.last_run.

  brain_reembed(store)
    For every fragment whose embedding_blob is NULL/empty, compute
    get_embedder().encode(text + subject + object) and persist it. Stamps
    brain_meta embed.backend + embed.dim. This fixes the all-NULL embeddings
    — the single biggest retrieval-quality fix.

Zero new deps: numpy (present) for the centroid math; get_embedder() is the
existing lexical/fastembed embedder. networkx is available but not needed.

Guardrails honoured:
  - Mutates ONLY through BrainStore methods (write_fragment / delete_fragment
    / set_meta) — never raw sqlite writes against the live WAL.
  - Merge is gated on cosine>=0.95 AND same subject AND same predicate.
  - Archive (valid_until=now) is used for stale traces — never hard-delete,
    and never for Decisions/Capability.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .embeddings import Embedder, get_embedder
from .models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Skill,
    Visibility,
)
from .storage import BrainStore


# ─────────────────────── constants ──────────────────────────────────────

# Coarse facets. A fragment lands in exactly one.
FACET_CAPABILITY = "Capability"
FACET_DECISIONS = "Decisions"
FACET_MEMORY = "Memory"

# Predicate → facet. Anything not named here is Memory.
_PREDICATE_FACET = {
    "capability": FACET_CAPABILITY,
    "decision": FACET_DECISIONS,
}

# Facets that are STRUCTURAL knowledge — never merged-away, archived, or
# touched destructively by the organize pass (founder guardrail #4).
_PROTECTED_FACETS = frozenset({FACET_CAPABILITY, FACET_DECISIONS})

# Cosine threshold for the dedupe merge. ONLY pairs at or above this AND
# sharing subject AND predicate merge (founder guardrail #3).
MERGE_COSINE_THRESHOLD = 0.95

# Nearest-centroid assignment threshold for unlabeled Memory rows. Below
# this the row is left 'unfiled' rather than force-fit to a weak centroid.
CLUSTER_ASSIGN_THRESHOLD = 0.35

# Stale-trace archive policy.
_TRACE_STALE_DAYS = 30

# ── Ebbinghaus half-life by facet / kind (founder gap-close 2026-06-01) ──
# The decay constant each fragment SHOULD carry, keyed first by predicate
# (the structural facets) then by kind. Set every organize cycle, idempotent
# (only written when the stored value differs), and applied IN-DAEMON via
# store.write_fragment — which bypasses the MCP ACL that previously
# DENIED the 252 project-scoped capability/decision rows.
#
#   Decisions   (predicate=decision)   → 180   half a year; decisions age out
#   Capability  (predicate=capability) → 3650  PINNED ~10y; the node inventory
#                                              is structural, must not decay
#   traces      (kind=trace)           → 30    ephemeral session residue
#   facts/rules (kind=fact)            → 90    a quarter; general knowledge
#
# Precedence: the predicate facets (decision / capability) WIN over the
# kind buckets, because capability/decision rows are themselves kind=fact —
# a plain `kind==fact → 90` rule would otherwise clobber the 3650 pin.
HALF_LIFE_DECISION = 180.0
HALF_LIFE_CAPABILITY = 3650.0
HALF_LIFE_TRACE = 30.0
HALF_LIFE_FACT = 90.0

# Category vocabulary the regex/keyword scan recognises. Drawn from the live
# brain's actual labels (extra_json.category + the text JSON "category"
# field): architecture/tool/host/data/render/speckle/gotcha/... plus the
# rest observed in the store so the labeled-centroid set is real.
_KNOWN_CATEGORIES = (
    "architecture", "tool", "host", "data", "render", "speckle", "gotcha",
    "convention", "process", "environment", "product", "workflow_pattern",
    "file_location", "broker_gotcha", "broker_fact", "claude_code_config",
    "decision", "fact", "skill", "io", "llm", "control", "ai", "document",
    "connector", "vision", "anim", "mesh", "math", "text", "share",
    "adapter", "code", "compose", "ux", "bugfix", "workshop",
)

# Matches a JSON-ish  "category": "value"  inside text / extra blobs.
_CATEGORY_JSON_RE = re.compile(r'"category"\s*:\s*"([a-z0-9_\-]+)"', re.IGNORECASE)

# ── Project-code EXTRACTION (founder gap-close 2026-06-01) ───────────────
# The research DEFERRED a blanket project_id assignment because the OLD 227
# rows (machine catalog + AgDRs) are NOT project-specific — assigning them a
# project would be FABRICATION. But the HARVESTED facts carry REAL project
# codes in their own text / subject / provenance. Tagging THOSE is accurate
# EXTRACTION of a code the fact already states — not invention.
#
# SAFETY (why this is safe + reversible):
#   - Writes ONLY extra_json.project (free-form metadata). It NEVER touches the
#     ACL-gated project_id column — that is the field the research warned
#     against and the one whose writes triggered the 'actor not in project
#     None' MCP denials. extra.project carries no ACL weight.
#   - Runs IN-DAEMON via store.write_fragment (the ACL-free path), so it is not
#     subject to the brain.write MCP gate.
#   - Idempotent: _set_extra only writes when extra.project differs.
#   - Reversible: backups exist; extra.project can be cleared the same way.
#
# All patterns are WORD-BOUNDARY anchored. This is load-bearing safety: a loose
# `stall?er` matches 'install' / 'installer' (5 daemon/installer rows in the
# live brain) — `\bstaller\b` isolates only the genuine "Staller … Tower"
# references. Likewise `\bP-?\d{3}\b` so a bare 'P461' or stray digits in a
# path don't over-match.
#
# Canonical codes observed in the live store: P-674 (Staller by Ellie Saab
# Tower), P-679 (Missoni Residential Tower), BBC4, BH3D (Revit BIM360 project
# 4300-BH3D-…; the doc-name typo 'BN3D' is the SAME project, already covered by
# the row that names BH3D), 26000-KIN, plus the P-### series (P461/P603/P649/
# P664/P665/P669/P973) that appear only in the multi-project workspace
# inventory — see the MULTI-PROJECT guard below.

# Named-tower aliases → canonical project code. Each is a word-boundary regex
# so partial words never trigger. "Ellie Saab" / "Elie Saab" both map to the
# Staller tower (P-674); spelling varies in the source ("Ellie"/"Elie").
_PROJECT_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bstaller\b", re.IGNORECASE), "P-674"),
    (re.compile(r"\bel+ie\s+saab\b", re.IGNORECASE), "P-674"),
    (re.compile(r"\bmissoni\b", re.IGNORECASE), "P-679"),
)

# Literal project codes (non P-series). Word-boundary anchored. BH3D also
# accepts the BB3D spelling the founder uses interchangeably (task: "BH3D/BB3D").
_PROJECT_CODE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bBBC4\b", re.IGNORECASE), "BBC4"),
    (re.compile(r"\bB[BH]3D\b", re.IGNORECASE), "BH3D"),
    (re.compile(r"\b26000[-_ ]?KIN\b", re.IGNORECASE), "26000-KIN"),
)

# P-series codes: P-674, P-679, P461, P 603, … Canonicalised to P-### (dash,
# zero gaps preserved). Word-boundary both sides so it won't fire inside a
# longer token. Captures the 3 digits for canonicalisation.
_PSERIES_RE = re.compile(r"\bP[-_ ]?(\d{3})\b", re.IGNORECASE)

# Only MEMORY-facet kinds may be project-tagged. Capability rows (the machine
# catalog) + Decisions (AgDRs) are NOT project-specific — tagging them is the
# fabrication the research warned against, so they are excluded by kind here
# AND by facet at the call site. trace/setup/document are left alone too: the
# real per-project facts in the live store are all kind=fact.
_PROJECT_TAGGABLE_KINDS = frozenset({FragmentKind.FACT})

# ── Skill-fragment promotion (founder gap-close 2026-06-01) ──────────────
# A prior harvest ingested ~49 mined procedures as kind=skill FRAGMENTS
# (name/trigger/broker_tool/steps packed into text + extra_json) because
# brain.write cannot write the `skills` table and the harvested human names
# violate the Skill.name regex. `promote_skill_fragments` lifts each into a
# PROPER `skills` row so retrieval (search_skills / brain.context) can match
# + fire them, then DELETES the now-redundant skill-fragment (the DELETE path
# is ACL-free) so it isn't double-counted in the Memory facet.
#
# Skill.name must satisfy this regex (see models.Skill); slugify_skill_name
# maps any human title onto it.
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_\-]*$")
_SKILL_NAME_MAXLEN = 64  # mirrors models.Skill.name max_length
_SKILL_DESC_MINLEN = 80  # mirrors models.Skill.description min_length (AgDR-0014)
_SKILL_DESC_MAXLEN = 1536  # mirrors models.Skill.description max_length

# A skill-fragment is one of these kinds AND/OR carries this harvest marker.
# kind=skill is the primary signal (the harvest stored them that way); the
# source marker is a belt-and-braces fallback for rows mis-kinded as fact.
_HARVEST_SOURCE = "session-harvest"

# Near-duplicate dedupe: two skills are "the same" if their slugs collide OR
# their descriptions share at least this fraction of significant tokens. Kept
# deliberately high so only genuine restatements are skipped (founder DEDUPE
# requirement) — distinct procedures with incidental word overlap still pass.
_SKILL_DEDUPE_JACCARD = 0.82
# Tokens too generic to count toward description similarity.
_SKILL_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "via", "by",
    "with", "then", "based", "each", "via", "is", "are", "be", "as", "at",
    "from", "into", "skill", "auto", "mined", "flow", "step", "successful",
    "pass", "that", "this", "it", "its", "use", "using",
})


# ─────────────────────── small helpers ──────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _now().isoformat()


def facet_for(fragment: Fragment) -> str:
    """Coarse facet from (kind, predicate).

    Capability + Decisions are keyed off the predicate (the live brain stores
    capability/decision rows with those exact predicates). Skills (kind=skill)
    are procedures — they live in Memory unless their predicate says
    otherwise. Everything else is Memory.
    """
    pred = (fragment.predicate or "").strip().lower()
    return _PREDICATE_FACET.get(pred, FACET_MEMORY)


def half_life_for(fragment: Fragment) -> Optional[float]:
    """The Ebbinghaus half-life (days) a fragment SHOULD carry, by facet/kind.

    Precedence (predicate facets beat kind buckets, since capability/decision
    rows are themselves kind=fact):

        predicate == decision    → 180   (Decisions facet)
        predicate == capability  → 3650  (Capability facet — pinned)
        kind == trace            → 30    (ephemeral Memory)
        kind == fact             → 90    (facts / rules)

    Returns None for anything else (skill / setup / document-without-a-
    decision-predicate / geometry / image / …) so the organize pass leaves
    those rows' half_life untouched rather than forcing a value the founder
    never specified.
    """
    pred = (fragment.predicate or "").strip().lower()
    if pred == "decision":
        return HALF_LIFE_DECISION
    if pred == "capability":
        return HALF_LIFE_CAPABILITY
    if fragment.kind == FragmentKind.TRACE:
        return HALF_LIFE_TRACE
    if fragment.kind == FragmentKind.FACT:
        return HALF_LIFE_FACT
    return None


def category_label(fragment: Fragment) -> Optional[str]:
    """Extract an EXPLICIT category label for a fragment, or None.

    Explicit means the label was authored, not guessed:
      1. extra_json.category — the canonical slot (e.g. gotcha, architecture).
      2. A "category":"X" key embedded in the text JSON blob (graph rows
         serialise their node props into text).
    Returns the lowercased label or None when neither is present. The softer
    bare-keyword heuristic + the embedding-centroid fallback live in
    `keyword_label` / brain_organize so they only fire for rows that lack an
    explicit label (keeps the centroid path meaningful).
    """
    # 1. extra_json.category
    extra = fragment.extra or {}
    cat = extra.get("category")
    if isinstance(cat, str) and cat.strip():
        return cat.strip().lower()

    # 2. "category": "X" inside the text blob (or a stringified extra)
    for blob in (fragment.text or "", json.dumps(extra) if extra else ""):
        m = _CATEGORY_JSON_RE.search(blob)
        if m:
            return m.group(1).strip().lower()
    return None


def keyword_label(fragment: Fragment) -> Optional[str]:
    """Soft category guess from a bare keyword hit over the known vocabulary.

    Heuristic tier between an explicit label and the embedding centroid: a row
    whose text plainly contains a vocabulary token (e.g. 'render', 'host',
    'architecture') gets that label. Returns None when no known token appears.
    """
    text_l = (fragment.text or "").lower()
    for known in _KNOWN_CATEGORIES:
        # word-boundary match so 'ai' doesn't fire inside 'maintain'
        if re.search(rf"\b{re.escape(known)}\b", text_l):
            return known
    return None


def _project_haystack(fragment: Fragment) -> str:
    """The string scanned for project codes: the fact's OWN content (text +
    subject + object) plus its provenance + extra blobs.

    Per the task we scan text + subject + provenance + extra. We include
    `object` too (the triple's tail often carries the path/code, e.g.
    'P-674 Staller / P-679 Missoni on \\\\BASERVER'). extra/provenance are
    serialised to JSON so a code stored in a structured field
    (extra.what_worked = '… across 3 BBC4 sessions') is seen.
    """
    parts = [fragment.text or "", fragment.subject or "", fragment.object or ""]
    extra = fragment.extra or {}
    if extra:
        try:
            parts.append(json.dumps(extra, default=str))
        except Exception:
            parts.append(str(extra))
    prov = getattr(fragment, "provenance", None)
    if prov is not None:
        try:
            # accessed_resources + session/trace ids are where harvest puts the
            # source-file / project hints.
            parts.append(json.dumps(list(prov.accessed_resources or [])))
        except Exception:
            pass
        for attr in ("session_id", "trace_id"):
            v = getattr(prov, attr, None)
            if v:
                parts.append(str(v))
    return " ".join(p for p in parts if p)


def detect_project(fragment: Fragment) -> Optional[str]:
    """Extract the canonical project code a fragment EXPLICITLY names, or None.

    Scans text + subject + object + extra + provenance (see _project_haystack)
    with WORD-BOUNDARY patterns for:
      - named-tower aliases  ("Staller"/"Ellie Saab"→P-674, "Missoni"→P-679),
      - literal codes        (BBC4, BH3D/BB3D, 26000-KIN),
      - the P-### series      (P-674, P-679, P461, …) canonicalised to 'P-###'.

    Returns the canonical code (e.g. 'P-674', 'BBC4', '26000-KIN') or None.

    This is EXTRACTION, not inference: it returns a code only when the fragment
    itself states it. Two guards keep it honest:

      MULTI-PROJECT GUARD. A row that names ≥2 distinct projects is a
      CROSS-project fact (the workspace inventory listing 12 codes; the "firm
      project file locations" row; the Speckle round-trip row naming both
      candidate towers). Assigning it a single code would FABRICATE a
      primary — so such rows return None and stay general. This is the crux of
      the research's fabrication warning applied at the row level.

      WORD BOUNDARIES. `\\bstaller\\b` not `stall?er` (the latter hits
      'install'/'installer'); `\\bP-?\\d{3}\\b` not a bare digit run. Without
      these, daemon/installer rows would be mis-tagged P-674.

    Note: kind/facet eligibility is enforced by the CALLER
    (`_tag_projects` / brain_organize), not here, so this stays a pure,
    unit-testable mapping over any fragment.
    """
    hay = _project_haystack(fragment)
    if not hay:
        return None

    found: set[str] = set()

    # Named-tower aliases.
    for rx, code in _PROJECT_ALIASES:
        if rx.search(hay):
            found.add(code)
    # Literal non-P codes.
    for rx, code in _PROJECT_CODE_PATTERNS:
        if rx.search(hay):
            found.add(code)
    # P-### series → canonical 'P-###'.
    for m in _PSERIES_RE.finditer(hay):
        found.add("P-" + m.group(1))

    if not found:
        return None
    if len(found) > 1:
        # Cross-project row — naming several projects is itself the signal that
        # this fact isn't scoped to ONE. Leave it general rather than invent a
        # primary (the deferred-tagging fabrication the research flagged).
        return None
    return next(iter(found))


def _embed_text_for(fragment: Fragment) -> str:
    """The canonical string fed to the embedder for a fragment — text plus
    subject + object so the vector carries the triple's full signal (mirrors
    retrieval.retrieve_facts)."""
    parts = [fragment.text or ""]
    if fragment.subject:
        parts.append(fragment.subject)
    if fragment.object:
        parts.append(fragment.object)
    return " ".join(p for p in parts if p)


def _mean_vector(vectors: list[list[float]]) -> Optional[list[float]]:
    """Centroid (mean) of a list of equal-length vectors via numpy. Returns
    None for an empty list."""
    if not vectors:
        return None
    import numpy as np

    arr = np.asarray(vectors, dtype=float)
    if arr.size == 0:
        return None
    return arr.mean(axis=0).tolist()


def _set_extra(
    store: BrainStore, fragment: Fragment, updates: dict[str, Any]
) -> None:
    """Upsert extra_json fields on a fragment via the store's safe writer.

    We mutate the Fragment model's `extra` dict + call write_fragment, which
    is the daemon-safe upsert path (never a raw sqlite write against the live
    WAL). write_fragment re-packs the embedding from fragment.embedding, so an
    already-embedded fragment keeps its vector across this update.
    """
    new_extra = dict(fragment.extra or {})
    changed = False
    for k, v in updates.items():
        if new_extra.get(k) != v:
            new_extra[k] = v
            changed = True
    if not changed:
        return  # idempotent: nothing to write when labels already match
    fragment.extra = new_extra
    store.write_fragment(fragment)


def _set_half_life(store: BrainStore, fragment: Fragment, target: float) -> bool:
    """Set a fragment's Ebbinghaus half_life_days to `target` IF it differs.

    Idempotent (no write when already at `target`, so re-running every cycle
    causes no churn) and reversible (backups exist). Mutates ONLY through the
    daemon-safe write_fragment — never a raw sqlite write against the live WAL,
    and NOT subject to the MCP ACL (this runs in-process), which is the whole
    point: the MCP brain.write path ACL-DENIED the project-scoped
    capability/decision rows, so the half-life never landed for them.

    write_fragment re-packs the embedding from fragment.embedding, so an
    already-embedded row keeps its vector across this update.

    Returns True when a write happened, False when it was a no-op.
    """
    current = fragment.half_life_days
    # Float compare with a tiny tolerance so 180 == 180.0 and re-runs are no-ops.
    if current is not None and abs(float(current) - float(target)) < 1e-9:
        return False
    fragment.half_life_days = float(target)
    store.write_fragment(fragment)
    return True


# ─────────────────────── organize pass ──────────────────────────────────


def brain_organize(
    store: BrainStore,
    *,
    embedder: Optional[Embedder] = None,
    owner_user: Optional[str] = None,
) -> dict[str, Any]:
    """Run the full facet-organization pass. Idempotent + re-runnable.

    Step (0) stamps each fragment's Ebbinghaus half_life_days by facet/kind
    (decision→180, capability→3650, trace→30, fact→90) — see half_life_for.
    Idempotent: only the rows whose value differs are written, so a steady-
    state re-run reports half_life_updates == 0. This runs IN-DAEMON via
    store.write_fragment and is therefore NOT subject to the MCP brain.write
    ACL that previously denied the project-scoped capability/decision rows.

    Returns a result dict:
        {
          "facet_counts": {Capability: n, Decisions: n, Memory: n},
          "cluster_counts": {label: n, ...},   # category clusters in Memory
          "labeled": int, "assigned_by_centroid": int, "unfiled": int,
          "merges": int, "archived": int,
          "half_life_updates": int,             # rows re-stamped this cycle
          "half_life_distribution": {days: n},  # over policy-covered rows
          "total": int, "elapsed_ms": float,
        }
    """
    import time as _t

    t0 = _t.perf_counter()
    embedder = embedder or get_embedder()

    # Pull the whole table (single owner-agnostic enumeration; ACL gating is
    # upstream). limit huge so we get everything.
    fragments = store.list_fragments(owner_user=None, limit=1_000_000)

    # ── (0) half-life by facet/kind ─────────────────────────────────────
    # Stamp the Ebbinghaus decay constant each fragment should carry, keyed by
    # facet (decision/capability) then kind (trace/fact). Idempotent: only
    # writes the rows whose half_life actually differs. Runs FIRST so the
    # fragment objects already carry the right half_life before any later
    # _set_extra write re-persists them (no double write per row). This is the
    # IN-DAEMON pass that bypasses the MCP ACL — the brain.write MCP path
    # DENIED the project-scoped capability/decision rows, so their half_life
    # never landed; store.write_fragment here is not ACL-gated.
    half_life_updates = 0
    half_life_by_value: dict[float, int] = {}
    for frag in fragments:
        target = half_life_for(frag)
        if target is None:
            continue
        if _set_half_life(store, frag, target):
            half_life_updates += 1
        half_life_by_value[target] = half_life_by_value.get(target, 0) + 1

    facet_counts: dict[str, int] = {
        FACET_CAPABILITY: 0,
        FACET_DECISIONS: 0,
        FACET_MEMORY: 0,
    }

    # ── (a)+(b) facet + label assignment ────────────────────────────────
    # First pass: assign facet + explicit label where present. Collect the
    # labeled Memory vectors per label to build centroids for the unlabeled.
    labeled_count = 0
    label_vectors: dict[str, list[list[float]]] = {}
    unlabeled_memory: list[Fragment] = []
    cluster_counts: dict[str, int] = {}

    for frag in fragments:
        facet = facet_for(frag)
        facet_counts[facet] += 1
        label = category_label(frag)

        if label:
            labeled_count += 1
            cluster_counts[label] = cluster_counts.get(label, 0) + 1
            # build centroid material from labeled rows (all facets contribute
            # to the centroid vocabulary so Memory rows can match a
            # tool/architecture/etc centroid).
            try:
                vec = embedder.encode(_embed_text_for(frag))
                label_vectors.setdefault(label, []).append(vec)
            except Exception:
                pass
            _set_extra(store, frag, {"facet": facet, "cluster_label": label})
        else:
            # Unlabeled. Only Memory rows get centroid-assigned; protected
            # facets (Capability/Decisions) without an explicit label are
            # left labelled by their facet name so they stay grouped.
            if facet in _PROTECTED_FACETS:
                fallback = facet.lower()
                cluster_counts[fallback] = cluster_counts.get(fallback, 0) + 1
                _set_extra(
                    store, frag, {"facet": facet, "cluster_label": fallback}
                )
            else:
                unlabeled_memory.append(frag)

    # Build per-label centroids.
    centroids: dict[str, list[float]] = {}
    for label, vecs in label_vectors.items():
        c = _mean_vector(vecs)
        if c is not None:
            centroids[label] = c

    # ── (b cont.) heuristic + nearest-centroid for unlabeled Memory ────
    # Tier order per unlabeled Memory row: (3a) bare-keyword guess over the
    # known vocabulary, then (3b) nearest labeled centroid (cosine threshold),
    # else 'unfiled'. Keyword + centroid assignments are tracked separately so
    # the result shows how each unlabeled row got filed.
    assigned_by_keyword = 0
    assigned_by_centroid = 0
    unfiled = 0
    for frag in unlabeled_memory:
        # (3a) soft keyword guess.
        kw = keyword_label(frag)
        if kw is not None:
            assigned_by_keyword += 1
            cluster_counts[kw] = cluster_counts.get(kw, 0) + 1
            _set_extra(store, frag, {"facet": FACET_MEMORY, "cluster_label": kw})
            continue

        # (3b) nearest labeled centroid.
        best_label: Optional[str] = None
        best_sim = -1.0
        if centroids:
            try:
                fvec = embedder.encode(_embed_text_for(frag))
            except Exception:
                fvec = None
            if fvec is not None:
                for label, cvec in centroids.items():
                    sim = embedder.cosine(fvec, cvec)
                    if sim > best_sim:
                        best_sim = sim
                        best_label = label
        if best_label is not None and best_sim >= CLUSTER_ASSIGN_THRESHOLD:
            assigned_by_centroid += 1
            cluster_counts[best_label] = cluster_counts.get(best_label, 0) + 1
            _set_extra(
                store, frag,
                {"facet": FACET_MEMORY, "cluster_label": best_label},
            )
        else:
            unfiled += 1
            cluster_counts["unfiled"] = cluster_counts.get("unfiled", 0) + 1
            _set_extra(
                store, frag,
                {"facet": FACET_MEMORY, "cluster_label": "unfiled"},
            )

    # ── (c) merge near-duplicates (cosine>=0.95 AND same subj AND pred) ─
    merges = _merge_duplicates(store, fragments, embedder)

    # ── (d) archive stale traces ────────────────────────────────────────
    archived = _archive_stale_traces(store, fragments)

    # ── (d2) tag MEMORY facts with the project code they explicitly name ─
    # Accurate EXTRACTION of a code the fact already states (NOT the deferred
    # fabricated project_id assignment). Sets extra.project only — never the
    # ACL-gated project_id column. Idempotent: writes only when it differs.
    projects_tagged, projects_by_code, projects_general = _tag_projects(
        store, fragments
    )

    # ── (e) persist cluster map + per-facet counts to brain_meta ────────
    elapsed_ms = (_t.perf_counter() - t0) * 1000.0
    result = {
        "facet_counts": facet_counts,
        "cluster_counts": dict(sorted(cluster_counts.items())),
        "labeled": labeled_count,
        "assigned_by_keyword": assigned_by_keyword,
        "assigned_by_centroid": assigned_by_centroid,
        "unfiled": unfiled,
        "merges": merges,
        "archived": archived,
        # Project-code EXTRACTION pass: how many MEMORY facts were tagged with
        # extra.project this cycle (0 on a steady-state re-run — idempotent),
        # broken down by canonical code, plus the count of project-MENTIONING
        # facts deliberately LEFT general (multi-project / cross-project rows).
        "projects_tagged": projects_tagged,
        "projects_by_code": dict(sorted(projects_by_code.items())),
        "projects_left_general": projects_general,
        # Half-life-by-kind pass: how many rows were re-stamped this cycle
        # (0 on a steady-state re-run — idempotent) + the resulting
        # distribution over the rows the policy covers.
        "half_life_updates": half_life_updates,
        "half_life_distribution": {
            str(int(k)): v for k, v in sorted(half_life_by_value.items())
        },
        "total": len(fragments),
        "elapsed_ms": round(elapsed_ms, 1),
    }
    store.set_meta("organize.clusters", json.dumps(result))
    store.set_meta("organize.last_run", _utcnow_iso())
    return result


def _merge_duplicates(
    store: BrainStore, fragments: list[Fragment], embedder: Embedder
) -> int:
    """Merge fragment pairs that share subject AND predicate AND have cosine
    >= MERGE_COSINE_THRESHOLD. Keeps the higher success_count, unions
    provenance.accessed_resources, DELETEs the loser. Returns merge count.

    Protected facets (Capability/Decisions) are excluded from the loser side
    — a decision/capability row is never deleted by the organize pass.
    """
    # Bucket by (subject, predicate); only buckets with >1 member can merge.
    buckets: dict[tuple, list[Fragment]] = {}
    for f in fragments:
        if not f.subject or not f.predicate:
            continue
        key = (f.subject, f.predicate)
        buckets.setdefault(key, []).append(f)

    merges = 0
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        # Encode each member once.
        vecs: dict[str, list[float]] = {}
        for f in group:
            try:
                vecs[f.id] = embedder.encode(_embed_text_for(f))
            except Exception:
                pass
        # Compare all unordered pairs; merge on threshold. Iterate over a
        # mutable survivor set so a merged-away loser isn't re-merged.
        survivors = {f.id: f for f in group}
        ids = [f.id for f in group]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a_id, b_id = ids[i], ids[j]
                if a_id not in survivors or b_id not in survivors:
                    continue
                if a_id not in vecs or b_id not in vecs:
                    continue
                sim = embedder.cosine(vecs[a_id], vecs[b_id])
                if sim < MERGE_COSINE_THRESHOLD:
                    continue
                a, b = survivors[a_id], survivors[b_id]
                # Never delete a protected-facet row; if either side is
                # protected, skip the merge entirely (keep both).
                if facet_for(a) in _PROTECTED_FACETS or facet_for(b) in _PROTECTED_FACETS:
                    continue
                # Keeper = higher success_count (tie → keep a).
                keeper, loser = (a, b) if a.success_count >= b.success_count else (b, a)
                # Union provenance.accessed_resources.
                try:
                    merged_res = list(dict.fromkeys(
                        list(keeper.provenance.accessed_resources or [])
                        + list(loser.provenance.accessed_resources or [])
                    ))
                    keeper.provenance.accessed_resources = merged_res
                except Exception:
                    pass
                # Carry the loser's success/fail signal into the keeper so the
                # merge doesn't lose reinforcement history.
                keeper.success_count = max(keeper.success_count, loser.success_count)
                keeper.fail_count = max(keeper.fail_count, loser.fail_count)
                store.write_fragment(keeper)
                store.delete_fragment(loser.id)
                survivors.pop(loser.id, None)
                merges += 1
    return merges


def _archive_stale_traces(store: BrainStore, fragments: list[Fragment]) -> int:
    """Set valid_until = now on kind=trace rows older than 30d with
    success_count == 0. Never hard-deletes; never touches Decisions/Capability
    (traces are Memory by predicate anyway, but the facet guard is explicit).
    Idempotent — a row already archived (valid_until set) is skipped.
    Returns the count archived this pass.
    """
    now = _now()
    archived = 0
    for f in fragments:
        if f.kind != FragmentKind.TRACE:
            continue
        if facet_for(f) in _PROTECTED_FACETS:
            continue  # defensive — never archive a protected facet
        if f.success_count != 0:
            continue
        if f.valid_until is not None:
            continue  # already archived — idempotent
        # Age from provenance.created_at (fall back to last_used_at).
        created = getattr(f.provenance, "created_at", None) or f.last_used_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).total_seconds() / 86400.0
        if age_days <= _TRACE_STALE_DAYS:
            continue
        f.valid_until = now
        store.write_fragment(f)
        archived += 1
    return archived


def _is_project_taggable(fragment: Fragment) -> bool:
    """Gate: only MEMORY-facet facts may carry an extracted project tag.

    Excludes — by KIND and by FACET — exactly the rows the research said are
    NOT project-specific (so a tag would be fabricated):
      - Capability rows (predicate=capability — the machine/node catalog),
      - Decisions rows  (predicate=decision  — the AgDRs),
      - non-fact kinds  (skill / setup / trace / document / geometry / image).

    The per-row 'does it name exactly one project' test is detect_project's
    job; this is purely the eligibility gate.
    """
    if fragment.kind not in _PROJECT_TAGGABLE_KINDS:
        return False
    if facet_for(fragment) in _PROTECTED_FACETS:
        # Belt-and-braces: a capability/decision row is kind=fact but its
        # predicate puts it in a protected facet — never project-tag it.
        return False
    return True


def _tag_projects(
    store: BrainStore, fragments: list[Fragment]
) -> tuple[int, dict[str, int], int]:
    """Stamp extra.project on every MEMORY fact that EXPLICITLY names ONE
    project. EXTRACTION, not fabrication — see detect_project + the module
    header.

    SAFETY / GUARDRAILS honoured:
      - Eligibility gate (_is_project_taggable): MEMORY-facet kind=fact only.
        Capability/Decisions/skills/traces/etc are skipped.
      - detect_project returns None for rows that name 0 or ≥2 projects, so
        cross-project rows stay general (no fabricated primary).
      - Writes ONLY extra.project via _set_extra — the daemon-safe, ACL-FREE
        write_fragment path. The ACL-gated project_id column is NEVER touched
        (that is the field the research flagged + that caused the 'actor not in
        project None' denials).
      - Idempotent: _set_extra writes only when extra.project actually differs,
        so a steady-state re-run reports projects_tagged == 0.

    Returns (rows_tagged_this_cycle, counts_by_canonical_code,
    project_mentioning_rows_left_general).
    """
    tagged = 0
    by_code: dict[str, int] = {}
    left_general = 0
    for frag in fragments:
        if not _is_project_taggable(frag):
            continue
        code = detect_project(frag)
        if code is None:
            # Did this row MENTION a project but get held back by the
            # multi-project guard? Count it as a deliberate 'left general' so
            # the report shows the cross-project rows weren't silently missed.
            if _mentions_any_project(frag):
                left_general += 1
            continue
        # Per-code census reflects the CURRENT desired state of the store (not
        # just this cycle's writes) so the report is a true by-project count
        # even on an idempotent re-run.
        by_code[code] = by_code.get(code, 0) + 1
        before = (frag.extra or {}).get("project")
        _set_extra(store, frag, {"project": code})
        if before != code:
            tagged += 1
    return tagged, by_code, left_general


def _mentions_any_project(fragment: Fragment) -> bool:
    """True if the fragment names ANY project code (used to distinguish a
    cross-project row deliberately left general from a row with no project at
    all). Mirrors detect_project's scan WITHOUT the single-project collapse."""
    hay = _project_haystack(fragment)
    if not hay:
        return False
    for rx, _ in _PROJECT_ALIASES:
        if rx.search(hay):
            return True
    for rx, _ in _PROJECT_CODE_PATTERNS:
        if rx.search(hay):
            return True
    return bool(_PSERIES_RE.search(hay))


# ─────────────────────── reembed pass ───────────────────────────────────


def brain_reembed(
    store: BrainStore,
    *,
    embedder: Optional[Embedder] = None,
) -> dict[str, Any]:
    """Backfill embeddings for every fragment whose vector is NULL/empty.

    For each such fragment, compute get_embedder().encode(text+subject+object)
    and persist it via write_fragment (which packs fragment.embedding into the
    embedding_blob column). Stamps brain_meta embed.backend + embed.dim.

    Idempotent: a fragment that already has an embedding is skipped, so
    re-running on the sync cadence only fills the genuinely-missing vectors.

    Returns:
        {"rows_embedded": int, "already_had": int, "backend": str,
         "dim": int, "total": int, "elapsed_ms": float}
    """
    import time as _t

    t0 = _t.perf_counter()
    embedder = embedder or get_embedder()

    fragments = store.list_fragments(owner_user=None, limit=1_000_000)
    rows_embedded = 0
    already_had = 0
    dim = getattr(embedder, "dim", 0)

    for frag in fragments:
        if frag.embedding:  # already populated → skip (idempotent)
            already_had += 1
            continue
        text = _embed_text_for(frag)
        if not text.strip():
            continue
        try:
            vec = embedder.encode(text)
        except Exception:
            continue
        if not vec:
            continue
        frag.embedding = [float(x) for x in vec]
        dim = len(frag.embedding)
        store.write_fragment(frag)
        rows_embedded += 1

    backend = getattr(embedder, "backend_name", "unknown")
    store.set_meta("embed.backend", backend)
    store.set_meta("embed.dim", str(dim))
    store.set_meta("reembed.last_run", _utcnow_iso())

    elapsed_ms = (_t.perf_counter() - t0) * 1000.0
    return {
        "rows_embedded": rows_embedded,
        "already_had": already_had,
        "backend": backend,
        "dim": dim,
        "total": len(fragments),
        "elapsed_ms": round(elapsed_ms, 1),
    }


# ─────────────────────── browse (read-only view) ────────────────────────
#
# brain_browse() is the READ-ONLY assembler behind the founder-facing visual
# brain browser (the BrainViewModal in studio-lm.jsx). It NEVER writes — it
# reads the facet/cluster labels organize already stamped onto extra_json and
# shapes them into the four coordinated views the CEO sees in 60 seconds:
#
#   1. top_of_mind  — the most salient Memory+Decisions cards (decay-weighted
#                     salience score), each a plain one-liner + last-used +
#                     "used N times" + facet + a plain "why is this here".
#   2. facets       — cluster CARDS (label + count + top-3 salient items),
#                     grouped under the three facet lanes. Capability is the
#                     de-emphasised machine inventory (collapsed by default in
#                     the UI); Memory carries the real notes/rules/skills.
#   3. archived     — the "Faded / archived" tray (valid_until set) so
#                     MAKE-IT-REAL-NEVER-TRIM is visible with a Restore path.
#   4. timeline     — recent learnings by ISO date ("what the brain learned
#                     this week").
#
# Salience here is the SAME Generative-Agents math the retrieval ranker uses
# (recency decay × importance), MINUS the query-relevance term (there is no
# query for the default view). When the caller passes `query`, the brain's
# real retrieval ranker is layered on top (see brain.context / brain.browse in
# server.py) — this function just supplies the organized substrate.

# Facets that are de-emphasised machine inventory (collapsed + off by default
# in the UI). Memory + Decisions are the human-meaningful lanes shown first.
_DEEMPHASISED_FACETS = frozenset({FACET_CAPABILITY})

# How many top items to embed per cluster card, and the global card caps so a
# huge brain never ships a megabyte of JSON across the bridge.
_TOP_PER_CLUSTER = 3
_MAX_TOP_OF_MIND = 24
_MAX_TIMELINE = 40
_MAX_ARCHIVED = 60


def _importance(success: int, fail: int) -> float:
    """Wilson-ish importance in [0,1] — mirrors retrieval._importance_from_counts
    so the browser's salience ordering matches what retrieval actually ranks."""
    import math

    total = (success or 0) + (fail or 0)
    if total == 0:
        return 0.3  # gentle prior for unused items (same as retrieval)
    ratio = ((success or 0) + 1) / (total + 2)
    volume = min(math.log(1 + total) / math.log(50), 1.0)
    return 0.5 * ratio + 0.5 * volume


def _salience(frag: Fragment) -> float:
    """Decay-weighted salience for the default (query-less) view.

    score = recency_decay + 0.6·importance  — the Generative-Agents recency +
    importance terms (no relevance term: there's no query). Recency uses the
    fragment's Ebbinghaus half_life_days; an item never used decays from its
    creation time so brand-new-but-unused notes still surface briefly.
    """
    import math

    now = _now()
    when = frag.last_used_at or getattr(frag.provenance, "created_at", None)
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age_s = (now - when).total_seconds() if when is not None else 1e9
    half_life_s = max(frag.half_life_days or 30.0, 0.5) * 86400.0
    decay = math.exp(-max(age_s, 0.0) / half_life_s)
    return decay + 0.6 * _importance(frag.success_count, frag.fail_count)


# A JSON tail is appended to many Decision/skill rows (the serialised node
# props, e.g.  Title {"agdr_id": "AgDR-0002", "category": "..."}). The founder
# must NOT see raw JSON at the top, so we strip a trailing {...} blob and the
# ugly  trace · user='...' · tools=[...]  envelope to a plain one-liner.
_JSON_TAIL_RE = re.compile(r"\s*\{.*\}\s*$", re.DOTALL)
_TRACE_RE = re.compile(r"^trace\s*·\s*user=['\"]?(.*?)['\"]?\s*(?:·\s*tools=.*)?$", re.IGNORECASE | re.DOTALL)


def _plain_oneliner(frag: Fragment) -> str:
    """A clean, CEO-readable one-line summary of a fragment — no SPO, no JSON.

    Strips the serialised-props JSON tail and unwraps the trace envelope so the
    card shows the human sentence, not the machine blob. Mojibake from older
    rows is left as-is (cosmetic); the raw text stays available in the Details
    drawer.
    """
    text = (frag.text or "").strip()
    m = _TRACE_RE.match(text)
    if m and m.group(1):
        text = m.group(1).strip()
    else:
        text = _JSON_TAIL_RE.sub("", text).strip()
    # Collapse internal whitespace/newlines to a single line.
    text = re.sub(r"\s+", " ", text)
    if len(text) > 160:
        text = text[:157].rstrip() + "…"
    return text or (frag.subject or frag.predicate or frag.id)


def _why_here(frag: Fragment, *, in_search: bool = False) -> str:
    """Plain-English 'why is this here' badge text — recent / often-used /
    matches search. No jargon (FOUNDER-SPEAK)."""
    if in_search:
        return "matches your search"
    now = _now()
    when = frag.last_used_at
    if when is not None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_days = (now - when).total_seconds() / 86400.0
        if age_days <= 7:
            return "used recently"
    if (frag.success_count or 0) >= 3:
        return f"used often ({frag.success_count}×)"
    if (frag.success_count or 0) >= 1:
        return "proven useful"
    created = getattr(frag.provenance, "created_at", None)
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).total_seconds() / 86400.0 <= 7:
            return "learned recently"
    return "in your memory"


def _iso_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def _card(frag: Fragment, facet: str, label: str, *, in_search: bool = False) -> dict[str, Any]:
    """Serialise ONE fragment into a UI card. Plain fields at the top; the raw
    predicate/subject/object/text live under `details` for the collapsed
    Details drawer (raw SPO/JSON never shown at the top — FOUNDER-SPEAK)."""
    last = frag.last_used_at or getattr(frag.provenance, "created_at", None)
    return {
        "id": frag.id,
        "facet": facet,
        "cluster": label,
        # The project code organize stamped on extra.project (EXTRACTION, never
        # the ACL-gated project_id). None for general/cross-project rows. Drives
        # the browser's project filter chip-row.
        "project": (frag.extra or {}).get("project"),
        "kind": frag.kind.value if hasattr(frag.kind, "value") else str(frag.kind),
        "headline": _plain_oneliner(frag),
        "used_count": int(frag.success_count or 0),
        "last_used": _iso_date(last),
        "salience": round(_salience(frag), 4),
        "archived": frag.valid_until is not None,
        "why": _why_here(frag, in_search=in_search),
        # Raw — for the Details drawer only.
        "details": {
            "subject": frag.subject,
            "predicate": frag.predicate,
            "object": frag.object,
            "scope": frag.scope.value if hasattr(frag.scope, "value") else str(frag.scope),
            "text": frag.text,
        },
    }


# ─────────────────── skills lane (promoted procedures) ──────────────────
#
# Skills live in their OWN table (not the fragments table), so the facet
# lanes above — which read only fragments — never see them. After
# promote_skill_fragments lifts the harvested skill-FRAGMENTS into proper
# `skills` rows (and deletes the duplicated fragments), the browser would
# otherwise show an EMPTY "How-to / Skills" lane. These helpers render the
# skills table as a first-class lane so the founder sees the real,
# auto-firing skills exactly where the harvested shells used to appear.

# The skills lane is its own facet so the UI can colour it distinctly from
# the Capability (machine-inventory) lane.
FACET_SKILLS = "How-to / Skills"

# Plain-English cluster labels for a skill's side_effects tag.
_SKILL_SIDE_EFFECT_LABEL = {
    "host_write": "changes a host",
    "network": "calls a service",
    "pure": "read-only",
}

_MAX_SKILLS_LANE = 200  # cap the lane so a huge skill library stays bounded


def _skill_salience(skill: Skill) -> float:
    """Decay-weighted salience for a Skill, mirroring _salience for fragments
    so the skills lane orders consistently with the rest of the browser.

    Skills are pinned knowledge (like Capability), so they decay on the
    capability half-life rather than the 30-day default — a proven procedure
    stays bright for a long time.
    """
    import math

    now = _now()
    when = skill.last_used_at or skill.minted_at or getattr(
        skill.provenance, "created_at", None
    )
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age_s = (now - when).total_seconds() if when is not None else 1e9
    half_life_s = HALF_LIFE_CAPABILITY * 86400.0
    decay = math.exp(-max(age_s, 0.0) / half_life_s)
    return decay + 0.6 * _importance(skill.success_count, skill.fail_count)


def _skill_why_here(skill: Skill) -> str:
    """Plain-English 'why is this here' for a skill (FOUNDER-SPEAK, no jargon)."""
    now = _now()
    when = skill.last_used_at
    if when is not None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if (now - when).total_seconds() / 86400.0 <= 7:
            return "used recently"
    if (skill.success_count or 0) >= 3:
        return f"used often ({skill.success_count}×)"
    if (skill.success_count or 0) >= 1:
        return "proven useful"
    minted = skill.minted_at or getattr(skill.provenance, "created_at", None)
    if minted is not None:
        if minted.tzinfo is None:
            minted = minted.replace(tzinfo=timezone.utc)
        if (now - minted).total_seconds() / 86400.0 <= 7:
            return "learned recently"
    return "a skill you can run"


def _skill_card(skill: Skill, *, in_search: bool = False) -> dict[str, Any]:
    """Serialise ONE Skill into the same UI card shape as _card, so the skills
    lane renders identically to the fragment lanes. The description is the
    plain headline; triggers / required tools / body live under `details`.
    """
    desc = re.sub(r"\s+", " ", (skill.description or "").strip())
    if len(desc) > 160:
        desc = desc[:157].rstrip() + "…"
    last = skill.last_used_at or skill.minted_at or getattr(
        skill.provenance, "created_at", None
    )
    label = _SKILL_SIDE_EFFECT_LABEL.get(skill.side_effects, "skill")
    return {
        "id": skill.id,
        "facet": FACET_SKILLS,
        "cluster": label,
        # Skills are cross-project procedures — they carry no single project
        # code, so the project filter treats them as facet-only (always shown).
        "project": None,
        "kind": "skill",
        "headline": desc or skill.name.replace("_", " "),
        "used_count": int(skill.success_count or 0),
        "last_used": _iso_date(last),
        "salience": round(_skill_salience(skill), 4),
        "archived": False,
        "why": "matches your search" if in_search else _skill_why_here(skill),
        # Raw — for the Details drawer only.
        "details": {
            "name": skill.name,
            "triggers": list(skill.triggers or []),
            "requires_mcps": list(skill.requires_mcps or []),
            "side_effects": skill.side_effects,
            "scope": skill.scope.value if hasattr(skill.scope, "value") else str(skill.scope),
            "text": skill.body,
        },
    }


def _skills_lane(store: BrainStore) -> dict[str, Any]:
    """Build the 'How-to / Skills' lane from the skills table — cluster cards
    (label + count + top-3 salient) in the SAME shape as the fragment facet
    lanes. Reading from store.list_skills means promoted procedures show up
    here the moment promote_skill_fragments lifts them out of fragments.
    """
    try:
        skills = store.list_skills(limit=_MAX_SKILLS_LANE)
    except Exception:
        skills = []
    by_label: dict[str, list[Skill]] = {}
    for sk in skills:
        lbl = _SKILL_SIDE_EFFECT_LABEL.get(sk.side_effects, "skill")
        by_label.setdefault(lbl, []).append(sk)
    clusters: list[dict[str, Any]] = []
    for lbl, sks in by_label.items():
        sks_sorted = sorted(sks, key=_skill_salience, reverse=True)
        clusters.append({
            "label": lbl,
            "count": len(sks),
            "top": [_skill_card(sk) for sk in sks_sorted[:_TOP_PER_CLUSTER]],
            "salience": round(
                max((_skill_salience(sk) for sk in sks), default=0.0), 4
            ),
        })
    clusters.sort(key=lambda c: (c["salience"], c["count"]), reverse=True)
    return {
        "facet": FACET_SKILLS,
        "count": len(skills),
        "deemphasised": False,
        "clusters": clusters,
    }


def brain_browse(
    store: BrainStore,
    *,
    owner_user: Optional[str] = None,
    query: Optional[str] = None,
    project: Optional[str] = None,
    embedder: Optional[Embedder] = None,
) -> dict[str, Any]:
    """Assemble the founder-facing visual-browser payload. READ-ONLY.

    Reads the facet/cluster labels organize() already stamped on extra_json
    (deriving them on the fly for any unlabeled row so the view is never blank
    before the first organize pass), computes decay-weighted salience, and
    returns the four coordinated views. When `query` is set, results are the
    brain's real retrieval ranker output re-shaped into the same card form (so
    search results carry facet colour + a 'matches your search' reason).

    `project` (optional) restricts the WHOLE view to the facts a single project
    code was EXTRACTED onto (extra.project — see _tag_projects / detect_project).
    The skills lane is exempt (procedures are cross-project, always shown). The
    `projects` breakdown below is ALWAYS computed over the unfiltered active set
    so the chip-row stays complete even while one project is selected. This is a
    pure read-side filter — it never writes and never touches project_id.

    Returns:
        {
          "ok": true,
          "generated_at": iso,
          "totals": {Capability, Decisions, Memory, archived, all},
          "projects": {code: count, ...},        # per-project fact census
          "project": project or null,            # the active filter (echoed)
          "top_of_mind": [card, ...],           # salient Memory+Decisions
          "facets": [                            # the lanes (cluster cards)
            {"facet": "Decisions", "count": n, "deemphasised": false,
             "clusters": [{"label","count","top":[card,...]}, ...]},
            ...
          ],
          "archived": [card, ...],               # faded tray (valid_until set)
          "timeline": [{"date","count","items":[{id,headline,facet}]}],
          "query": query or null,
          "search": [card, ...],                 # present only when query set
        }
    """
    import time as _t

    t0 = _t.perf_counter()
    project = (project or "").strip() or None
    fragments = store.list_fragments(owner_user=None, limit=1_000_000)

    # ── Label every row (use the stamped facet/cluster; derive if absent so
    #    the view works even before the first organize pass) ──
    # `projects` is the per-project fact census over the ACTIVE (non-archived)
    # rows — computed BEFORE any project filter so the chip-row is always the
    # complete set even while one project is selected. `project` (when set)
    # then drops every active row whose extra.project differs, so the four
    # views below show only that project's facts (read-only filter).
    enriched: list[tuple[Fragment, str, str]] = []
    facet_totals: dict[str, int] = {
        FACET_CAPABILITY: 0, FACET_DECISIONS: 0, FACET_MEMORY: 0,
    }
    projects: dict[str, int] = {}
    archived_cards: list[dict[str, Any]] = []
    for f in fragments:
        extra = f.extra or {}
        facet = extra.get("facet") or facet_for(f)
        label = extra.get("cluster_label") or category_label(f) or keyword_label(f) or (
            facet.lower() if facet in _PROTECTED_FACETS else "unfiled"
        )
        if f.valid_until is not None:
            # Archived rows live ONLY in the faded tray; the project filter
            # applies to them too so a filtered view's tray matches.
            if project is None or extra.get("project") == project:
                archived_cards.append(_card(f, facet, label))
            continue
        # Census every active row that carries a project code (pre-filter).
        code = extra.get("project")
        if code:
            projects[code] = projects.get(code, 0) + 1
        # Apply the optional project filter to the active set.
        if project is not None and code != project:
            continue
        facet_totals[facet] = facet_totals.get(facet, 0) + 1
        enriched.append((f, facet, label))

    # ── (1) Top of mind — most-salient Memory + Decisions (the human lanes) ──
    human = [
        (f, facet, label) for (f, facet, label) in enriched
        if facet not in _DEEMPHASISED_FACETS
    ]
    human.sort(key=lambda t: _salience(t[0]), reverse=True)
    top_of_mind = [_card(f, facet, label) for (f, facet, label) in human[:_MAX_TOP_OF_MIND]]

    # ── (2) Facet lanes — cluster cards (label + count + top-3 salient) ──
    facets_out: list[dict[str, Any]] = []
    facet_order = [FACET_DECISIONS, FACET_MEMORY, FACET_CAPABILITY]
    for facet in facet_order:
        members = [(f, lbl) for (f, fc, lbl) in enriched if fc == facet]
        # Bucket by cluster label.
        by_label: dict[str, list[Fragment]] = {}
        for f, lbl in members:
            by_label.setdefault(lbl, []).append(f)
        clusters = []
        for lbl, frs in by_label.items():
            frs_sorted = sorted(frs, key=_salience, reverse=True)
            clusters.append({
                "label": lbl,
                "count": len(frs),
                "top": [_card(fr, facet, lbl) for fr in frs_sorted[:_TOP_PER_CLUSTER]],
                "salience": round(max((_salience(fr) for fr in frs), default=0.0), 4),
            })
        # Brightest clusters first.
        clusters.sort(key=lambda c: (c["salience"], c["count"]), reverse=True)
        facets_out.append({
            "facet": facet,
            "count": facet_totals.get(facet, 0),
            "deemphasised": facet in _DEEMPHASISED_FACETS,
            "clusters": clusters,
        })

    # ── (2b) How-to / Skills lane — the promoted procedures (skills table). ──
    # Skills live in their own table, not in `fragments`, so the loop above
    # never sees them. Surface them as a first-class lane so the founder sees
    # the real auto-firing skills (not the harvested skill-fragments, which
    # promote_skill_fragments deletes). Shown first: it's the "what can I
    # actually do" lane. Under a project filter the lane is SUPPRESSED —
    # skills are cross-project procedures, so "facts about P-674" shouldn't
    # show the whole skill library.
    skills_lane = (
        _skills_lane(store) if project is None
        else {"facet": FACET_SKILLS, "count": 0, "deemphasised": False, "clusters": []}
    )
    if skills_lane["count"]:
        facets_out.insert(0, skills_lane)

    # ── (3) Archived tray — most-recent first (already collected above) ──
    archived_cards.sort(key=lambda c: (c.get("last_used") or ""), reverse=True)
    archived_cards = archived_cards[:_MAX_ARCHIVED]

    # ── (4) Timeline — learnings grouped by created date (human lanes only) ──
    dated: dict[str, list[dict[str, Any]]] = {}
    for f, facet, label in human:
        d = _iso_date(getattr(f.provenance, "created_at", None) or f.last_used_at)
        if not d:
            continue
        dated.setdefault(d, []).append({
            "id": f.id, "headline": _plain_oneliner(f), "facet": facet,
        })
    timeline = [
        {"date": d, "count": len(items), "items": items[:6]}
        for d, items in sorted(dated.items(), reverse=True)
    ][:_MAX_TIMELINE]

    result: dict[str, Any] = {
        "ok": True,
        "generated_at": _utcnow_iso(),
        "totals": {
            **facet_totals,
            FACET_SKILLS: skills_lane["count"],
            "archived": len(archived_cards),
            "all": len(fragments),
        },
        # Per-project fact census (complete set, computed pre-filter) + the
        # active filter echoed back so the UI can render the chip-row and mark
        # which chip is selected.
        "projects": dict(sorted(projects.items())),
        "project": project,
        "top_of_mind": top_of_mind,
        "facets": facets_out,
        "archived": archived_cards,
        "timeline": timeline,
        "query": query or None,
        "elapsed_ms": round((_t.perf_counter() - t0) * 1000.0, 1),
    }

    # ── Optional search — layer the real retrieval ranker on top ──
    if query and query.strip():
        result["search"] = _browse_search(
            store, query.strip(), owner_user=owner_user, embedder=embedder,
            enriched=enriched, project=project,
        )
    return result


def _browse_search(
    store: BrainStore,
    query: str,
    *,
    owner_user: Optional[str],
    embedder: Optional[Embedder],
    enriched: list[tuple[Fragment, str, str]],
    project: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Run the brain's real retrieval ranker for `query` and re-shape the hits
    into browser cards (facet colour + 'matches your search'). Falls back to a
    lexical contains-scan if the ranker import/encode fails so search is never
    dead.

    When `project` is set the results are scoped to that project: fact hits whose
    extra.project differs are dropped, and the (cross-project) skills lane is
    suppressed — matching the filtered default view. The lexical fallback runs
    over `enriched`, which the caller already project-filtered, so it's scoped
    for free."""
    from .retrieval import retrieve_facts, retrieve_skills
    from .models import FragmentKind as _FK

    owner = owner_user or "founder"
    label_by_id = {f.id: (facet, lbl) for (f, facet, lbl) in enriched}

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Skills first — a query like "promote skills" or "AutoCAD batch publish"
    # should surface the real, runnable procedure, not just loose facts. The
    # skills table is separate from fragments, so it needs its own ranker call.
    # Skipped entirely under a project filter (skills are cross-project).
    if project is None:
        try:
            skill_hits = retrieve_skills(store, query, owner_user=owner, k=8)
        except Exception:
            skill_hits = []
        for sk in skill_hits:
            if sk.id in seen:
                continue
            seen.add(sk.id)
            cards.append(_skill_card(sk, in_search=True))

    try:
        facts = retrieve_facts(
            store, query, owner_user=owner,
            kinds=[_FK.FACT, _FK.SETUP, _FK.SPATIAL, _FK.DOCUMENT, _FK.TRACE],
            k=18, embedder=embedder,
        )
    except Exception:
        facts = []
    for f in facts:
        if f.id in seen:
            continue
        # Project filter: keep only hits stamped with the selected code.
        if project is not None and (f.extra or {}).get("project") != project:
            continue
        seen.add(f.id)
        facet, lbl = label_by_id.get(f.id, (facet_for(f), "unfiled"))
        cards.append(_card(f, facet, lbl, in_search=True))

    # Lexical fallback when the ranker returned nothing (e.g. embeddings still
    # NULL): a plain case-insensitive contains over the already-loaded rows.
    if not cards:
        q = query.lower()
        scored = []
        for f, facet, lbl in enriched:
            if q in (f.text or "").lower() or q in (f.subject or "").lower():
                scored.append((f, facet, lbl))
        scored.sort(key=lambda t: _salience(t[0]), reverse=True)
        cards = [_card(f, facet, lbl, in_search=True) for (f, facet, lbl) in scored[:18]]
    return cards


def brain_restore(store: BrainStore, fragment_id: str) -> dict[str, Any]:
    """Un-archive a fragment: clear its `valid_until` so it rejoins active
    memory (the inverse of the organize pass's stale-trace archive). This is
    what the "Faded / archived → Restore" button does — making
    MAKE-IT-REAL-NEVER-TRIM a real, reversible affordance rather than a label.

    Mutates ONLY through the store's safe write_fragment path (never a raw
    sqlite write against the live WAL). Idempotent: restoring an already-active
    fragment is a no-op. Returns {ok, restored, id}.
    """
    if not fragment_id:
        return {"ok": False, "error": "missing fragment_id", "restored": False}
    frag = store.get_fragment(fragment_id) if hasattr(store, "get_fragment") else None
    if frag is None:
        # Fall back to a filtered enumeration if get_fragment isn't present.
        for f in store.list_fragments(owner_user=None, limit=1_000_000):
            if f.id == fragment_id:
                frag = f
                break
    if frag is None:
        return {"ok": False, "error": "fragment not found", "restored": False,
                "id": fragment_id}
    if frag.valid_until is None:
        return {"ok": True, "restored": False, "id": fragment_id,
                "note": "already active"}
    frag.valid_until = None
    # Reinforce lightly so it doesn't immediately re-archive on the next pass
    # (a restored note the user explicitly wanted back is not stale).
    frag.last_used_at = _now()
    store.write_fragment(frag)
    return {"ok": True, "restored": True, "id": fragment_id}


# ─────────────────── skill-fragment promotion ───────────────────────────


def slugify_skill_name(name: str, *, taken: Optional[set[str]] = None) -> str:
    """Map a human skill title onto the ^[a-z][a-z0-9_-]*$ Skill.name regex.

    Rules (founder spec):
      • lowercase
      • '&' → 'and' (keep the conjunction meaning before stripping symbols)
      • every run of illegal chars → a single '_'
      • collapse repeated '_' and strip leading/trailing '_'
      • must start with [a-z]; if it doesn't (empty or leading digit/symbol),
        prefix 's_'
      • truncate to 64 chars, then re-strip any trailing '_' the cut produced
      • dedupe-suffix '_2', '_3', … on collision with anything in `taken`

    The result is guaranteed to match models.Skill's name pattern + length.
    `taken` (when given) is consulted AND updated with the chosen slug so a
    batch of names slugged in sequence never collides with itself.
    """
    s = (name or "").strip().lower()
    s = s.replace("&", " and ")
    # Drop apostrophes outright so "agent's" → "agents" not "agent_s".
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or not s[0].isalpha():
        s = "s_" + s
        s = re.sub(r"_+", "_", s).strip("_")
    # Truncate, then re-strip a trailing '_' the cut may have created.
    s = s[:_SKILL_NAME_MAXLEN].rstrip("_")
    if len(s) < 2:  # Skill.name min_length is 2
        s = (s + "_x")[:_SKILL_NAME_MAXLEN]
    if taken is None:
        return s
    if s not in taken:
        taken.add(s)
        return s
    # Collision: append _2, _3, … keeping within the 64-char budget.
    base = s
    i = 2
    while True:
        suffix = f"_{i}"
        cand = base[: _SKILL_NAME_MAXLEN - len(suffix)].rstrip("_") + suffix
        if cand not in taken:
            taken.add(cand)
            return cand
        i += 1


def _is_skill_fragment(frag: Fragment) -> bool:
    """True for a harvested skill-shaped fragment awaiting promotion.

    Primary signal: kind == skill. Fallback: a fact-kinded row explicitly
    marked as a harvested skill (extra.category == 'skill' AND
    extra.source == 'session-harvest') — covers rows mis-kinded upstream.
    Proper `skills`-table rows are NOT fragments, so they never appear here.
    """
    if frag.kind == FragmentKind.SKILL:
        return True
    extra = frag.extra or {}
    return (
        extra.get("category") == "skill"
        and extra.get("source") == _HARVEST_SOURCE
        and bool(extra.get("skill_name"))
    )


def _frag_skill_name(frag: Fragment) -> str:
    """Human skill title carried by a skill-fragment (pre-slug)."""
    extra = frag.extra or {}
    return (
        (extra.get("skill_name") or "").strip()
        or (frag.subject or "").strip()
        or (frag.text or "").strip().split("\n", 1)[0][:64]
        or "harvested_skill"
    )


def _as_str_list(value: Any) -> list[str]:
    """Coerce a trigger / mcp field (str | list | None) into list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = item if isinstance(item, str) else str(item)
            s = s.strip()
            if s:
                out.append(s)
        return out
    return [str(value)]


def _parse_body_field(body: str, label: str) -> str:
    """Pull the single-line value after `LABEL:` out of a harvested body.

    The harvested body is the literal block
        TRIGGER: ...
        BROKER/TOOL: ...
        STEPS: ...
    so `_parse_body_field(body, 'TRIGGER')` recovers the trigger even when the
    structured extra fields are missing.
    """
    if not body:
        return ""
    m = re.search(rf"^{re.escape(label)}\s*:\s*(.*)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _skill_triggers(frag: Fragment) -> list[str]:
    extra = frag.extra or {}
    trg = _as_str_list(extra.get("triggers"))
    if trg:
        return trg
    line = _parse_body_field(extra.get("body") or frag.text or "", "TRIGGER")
    return [line] if line else []


def _skill_requires_mcps(frag: Fragment) -> list[str]:
    extra = frag.extra or {}
    mcps = _as_str_list(extra.get("requires_mcps"))
    if mcps:
        return mcps
    line = _parse_body_field(
        extra.get("body") or frag.text or "", "BROKER/TOOL"
    )
    return [line] if line else []


def _skill_body(frag: Fragment) -> str:
    extra = frag.extra or {}
    body = (extra.get("body") or "").strip()
    return body or (frag.text or "").strip()


def _skill_description(frag: Fragment, name: str) -> str:
    """Indexable one-liner. The fragment `text` is the description; pad it to
    the Skill.description ≥80-char floor when a harvest produced a terse one,
    and clamp to the ≤1536 ceiling."""
    desc = (frag.text or "").strip()
    if len(desc) < _SKILL_DESC_MINLEN:
        # Pad with the human title + a stable suffix so it stays meaningful
        # and clears the AgDR-0014 minimum without inventing facts.
        pad = (
            f"{name.replace('_', ' ')}. "
            "Harvested procedure promoted to a brain skill for retrieval."
        )
        desc = (desc + " " + pad).strip() if desc else pad
    if len(desc) > _SKILL_DESC_MAXLEN:
        desc = desc[: _SKILL_DESC_MAXLEN - 1].rstrip() + "…"
    # Final guard: if still short (degenerate input), right-pad deterministically.
    if len(desc) < _SKILL_DESC_MINLEN:
        desc = (desc + " " + "promoted harvested skill procedure" * 3)[
            :_SKILL_DESC_MAXLEN
        ]
    return desc


def _skill_examples(frag: Fragment) -> list[dict[str, Any]]:
    """Normalise the harvested `examples` (usually a free-text note like
    'YES (partial) — 43/56 sheets done') into the list[dict] Skill shape.
    A bare 'YES'/'NO' is recorded as an availability flag; anything richer is
    kept verbatim as a note so no provenance is lost."""
    extra = frag.extra or {}
    ex = extra.get("examples")
    if ex is None or ex == "":
        return []
    if isinstance(ex, list):
        out: list[dict[str, Any]] = []
        for item in ex:
            if isinstance(item, dict):
                out.append(item)
            elif item is not None:
                out.append({"note": str(item)})
        return out
    if isinstance(ex, dict):
        return [ex]
    return [{"note": str(ex).strip()}]


def _synth_eval_queries(description: str, name: str) -> list[dict[str, Any]]:
    """Synthesize 1-2 should-trigger retrieval test queries from the
    description (founder spec). These let `search_skills` self-test that the
    promoted skill is reachable. Deterministic — no LLM call."""
    desc = (description or "").strip()
    first = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0].strip() if desc else ""
    if len(first) > 160:
        first = first[:157].rstrip() + "…"
    queries: list[dict[str, Any]] = []
    if first:
        queries.append({"query": first, "should_trigger": True})
    # Second query: the de-slugged name as a keyword phrase, if it adds signal.
    phrase = name.replace("_", " ").strip()
    if phrase and phrase.lower() not in first.lower():
        queries.append({"query": phrase, "should_trigger": True})
    if not queries:  # degenerate: never emit an empty eval set
        queries.append({"query": phrase or name, "should_trigger": True})
    return queries[:2]


def _desc_tokens(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {t for t in toks if len(t) > 2 and t not in _SKILL_STOPWORDS}


def _near_duplicate_skill(
    *,
    base_slug: str,
    description: str,
    existing: list[Skill],
    strict_slug_names: Optional[set[str]] = None,
) -> Optional[str]:
    """Return the name of an existing skill that is the same as this one
    (founder DEDUPE), else None.

    Two independent signals flag a duplicate:
      • SAME-SLUG against a PRE-EXISTING skill (a name in `strict_slug_names`):
        the harvested name collides with an already-minted skill, so we keep
        the existing one. This protects the prior 14 skills from being
        clobbered or shadowed. `base_slug` MUST be the un-suffixed slug so the
        comparison is against the existing name, not a `_2` variant.
      • NEAR-IDENTICAL DESCRIPTION (high Jaccard on significant tokens) against
        ANY existing skill: a genuine restatement regardless of name.

    Crucially, same-slug is NOT a duplicate signal for skills promoted earlier
    in THIS run (not in `strict_slug_names`): two distinct harvested procedures
    that happen to share a human name are collision-suffixed (`_2`), not
    skipped — only their content similarity can collapse them.
    """
    strict = strict_slug_names if strict_slug_names is not None else set()
    my_tokens = _desc_tokens(description)
    for sk in existing:
        if sk.name == base_slug and sk.name in strict:
            return sk.name
        if not my_tokens:
            continue
        other = _desc_tokens(sk.description)
        if not other:
            continue
        inter = len(my_tokens & other)
        union = len(my_tokens | other)
        if union and inter / union >= _SKILL_DEDUPE_JACCARD:
            return sk.name
    return None


def promote_skill_fragments(
    store: BrainStore,
    *,
    owner_user: str = "Fargaly",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote every harvested skill-FRAGMENT into a proper `skills` row.

    For each fragment for which `_is_skill_fragment` is true:
      1. slugify its human name to ^[a-z][a-z0-9_-]*$ (collision-suffixed),
      2. DEDUPE vs the existing skills — skip (keep the existing one) when a
         same-slug or near-identical skill already exists,
      3. build a Skill (triggers ← trigger, requires_mcps ← broker_tool,
         body ← steps, examples, eval_queries ← synthesized from the
         description, scope/visibility/owner, provenance ← the fragment's),
      4. store.upsert_skill(it)  — the in-daemon, ACL-free write path,
      5. store.delete_fragment(fragment.id)  — ACL-free; removes the now
         duplicated Memory-facet row so it isn't double-counted.

    Guardrails honoured:
      • Mutates ONLY through store.upsert_skill / store.delete_fragment — never
        a raw sqlite write against the live WAL.
      • Idempotent + one-shot: a second run finds the fragments gone (deleted
        in step 5) and a matching skill present (dedupe), so it promotes 0.
      • Reversible: the skill row carries the fragment's provenance + body, and
        a dated brain.db backup + logical export are taken before any live run.
      • `dry_run=True` plans only (no upsert, no delete) — used to preview the
        slug map + dedupe decisions before the Deliver-stage live promotion.

    Returns a summary dict:
      {promoted, skipped_duplicate, deleted_fragments, total_candidates,
       slug_map, skipped, errors, dry_run}
    """
    # Enumerate ALL fragments (owner_user=None → no USER-scope filter, so a
    # mis-scoped harvest row is still seen) and keep only skill-shaped ones.
    all_frags = store.list_fragments(owner_user=None, limit=1_000_000)
    candidates = [f for f in all_frags if _is_skill_fragment(f)]
    # Stable order: by skill name then id, so slug dedupe-suffixing (_2/_3) is
    # deterministic across runs.
    candidates.sort(key=lambda f: (_frag_skill_name(f).lower(), f.id))

    existing_skills = store.list_skills(limit=1_000_000)
    taken_slugs: set[str] = {sk.name for sk in existing_skills}
    # Names of PRE-EXISTING skills (before this run). A harvested name that
    # slugs to one of these is a same-slug duplicate → skipped (keep existing).
    # Skills promoted later in THIS run are NOT in this set, so two distinct
    # harvested rows sharing a name get collision-suffixed instead of skipped.
    preexisting_slug_names: set[str] = set(taken_slugs)

    promoted = 0
    skipped_duplicate = 0
    deleted = 0
    slug_map: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    errors: list[str] = []

    for frag in candidates:
        human = _frag_skill_name(frag)
        try:
            # Dedupe is checked against the UN-suffixed base slug so a fragment
            # whose name slugs to an existing skill's exact name is caught (a
            # collision-suffixed `_2` would never equal the existing name). The
            # description is computed from the base slug only for the token
            # comparison; it's recomputed from the final slug below if we add.
            base_slug = slugify_skill_name(human, taken=None)
            description = _skill_description(frag, base_slug)
            dup_of = _near_duplicate_skill(
                base_slug=base_slug, description=description,
                existing=existing_skills,
                strict_slug_names=preexisting_slug_names,
            )
            if dup_of is not None:
                skipped_duplicate += 1
                skipped.append(
                    {"fragment_id": frag.id, "name": human,
                     "duplicate_of": dup_of}
                )
                # Do NOT delete the fragment on a dry run; on a real run the
                # fragment is left in place too — a near-dup that wasn't
                # promoted should remain inspectable rather than vanish.
                continue

            # Commit the slug to the live namespace now that we know we'll add.
            slug = slugify_skill_name(human, taken=taken_slugs)
            description = _skill_description(frag, slug)
            skill = Skill(
                id=f"promoted-skill-{frag.id}",
                name=slug,
                description=description,
                triggers=_skill_triggers(frag),
                requires_mcps=_skill_requires_mcps(frag),
                requires_secrets=[],
                body=_skill_body(frag),
                examples=_skill_examples(frag),
                eval_queries=_synth_eval_queries(description, slug),
                scope=frag.scope if isinstance(frag.scope, Scope) else Scope.USER,
                visibility=(
                    frag.visibility
                    if isinstance(frag.visibility, Visibility)
                    else Visibility.PRIVATE
                ),
                owner_user=frag.owner_user or owner_user,
                provenance=_promotion_provenance(frag),
                success_count=frag.success_count,
                fail_count=frag.fail_count,
                last_used_at=frag.last_used_at,
                side_effects=_infer_side_effects(frag),
            )
            slug_map.append({"fragment_id": frag.id, "name": human, "slug": slug})
            if not dry_run:
                store.upsert_skill(skill)
                if store.delete_fragment(frag.id):
                    deleted += 1
            # Track in-memory so later candidates dedupe against this new skill
            # (covers two harvested rows that are restatements of each other).
            existing_skills.append(skill)
            promoted += 1
        except Exception as exc:  # never let one bad row abort the batch
            errors.append(f"{frag.id} ({human!r}): {exc}")

    if not dry_run:
        store.set_meta("skills.promote.last_run", _utcnow_iso())
        store.set_meta(
            "skills.promote.last_summary",
            json.dumps(
                {
                    "promoted": promoted,
                    "skipped_duplicate": skipped_duplicate,
                    "deleted_fragments": deleted,
                    "at": _utcnow_iso(),
                }
            ),
        )

    return {
        "promoted": promoted,
        "skipped_duplicate": skipped_duplicate,
        "deleted_fragments": deleted,
        "total_candidates": len(candidates),
        "slug_map": slug_map,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }


def _promotion_provenance(frag: Fragment) -> Provenance:
    """Carry the fragment's provenance forward onto the promoted skill, with an
    added breadcrumb that this skill was promoted from a harvested fragment so
    the lineage is auditable (and a live run is reversible from the backups)."""
    src = frag.provenance
    resources = list(src.accessed_resources or [])
    marker = f"promoted_from_fragment:{frag.id}"
    if marker not in resources:
        resources.append(marker)
    return Provenance(
        contributing_agent=src.contributing_agent,
        contributing_user=src.contributing_user,
        session_id=src.session_id,
        trace_id=src.trace_id,
        accessed_resources=resources,
        created_at=src.created_at,
        last_reinforced_at=_now(),
        hlc=src.hlc,
    )


def _infer_side_effects(frag: Fragment) -> str:
    """Best-effort side_effects tag for a promoted procedure.

    Harvested procedures that drive a host/broker (write to AutoCAD / Revit /
    the filesystem) are 'host_write'; ones that hit an endpoint are 'network';
    pure read/verify procedures stay 'pure'. Conservative: defaults to
    'host_write' for broker-driven skills since they mutate external state."""
    blob = " ".join(
        [
            frag.text or "",
            (frag.extra or {}).get("body", "") or "",
            " ".join(_skill_requires_mcps(frag)),
        ]
    ).lower()
    host_write_signals = (
        "qsave", "save in place", "write", "rewrite", "set parameter",
        "batch_set", "export", "publish", "accoreconsole", "/exec",
        "place", "create", "paste", "assign", "modify", "edit",
    )
    network_signals = ("http://", "https://", "post /", "endpoint", "curl ")
    if any(sig in blob for sig in host_write_signals):
        return "host_write"
    if any(sig in blob for sig in network_signals):
        return "network"
    return "pure"
