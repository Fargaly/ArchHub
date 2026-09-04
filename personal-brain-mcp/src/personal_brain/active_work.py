"""Legacy Brain active-work coordination projection.

This module preserves the Brain-side active-work MCP surface while assignments
are migrated into the application-owned Universal Cell graph.
It is not the active product work authority. The active authority is
10.PRODUCT/13.NODE-LANGUAGE; this BrainStore JSON row remains a migration gate,
compatibility projection, and immutable evidence source.

This is the brain-side, all-agents counterpart to the per-agent file ledger in
`tools/active_work.py` (whose own docstring names this as the slice it "builds
toward"). That v0 file ledger stays as the skippable local Stop-hook catch. This
module keeps the shared Brain-side choke point until every work assignment,
claim, evidence edge, and release transition is issued directly through Cell
protocols and courts.

────────────────────────────────────────────────────────────────────────────
SAFETY (load-bearing — mirrors requirement_tree.py's TreeStore EXACTLY):
────────────────────────────────────────────────────────────────────────────
  * ADDITIVE ONLY. No new SQLite table, no schema migration. The whole ledger
    is persisted under ONE `brain_meta` key (`active_work_v1`) as a JSON doc.
    `BrainStore.set_meta` is an `INSERT … ON CONFLICT(key) DO UPDATE`
    (storage.py:1054) guarded by the store's RLock — so the ledger namespace is
    a single row and never touches `fragments` / `skills` / `-wal` / `-shm`.
  * Pure-Python + Pydantic, mirroring `models.py` / `requirement_tree.py`
    style. Defined LOCALLY here so the stable MCP contract in models.py is
    untouched.
  * Datetimes serialise via `default=str`; `model_validate` re-parses ISO
    strings back to datetimes on load.

THE DRIVE'S STATE MACHINE (mirrors the ROMA leaf states — NO "later"):
  OPEN     — unclaimed work; an executor may claim it.
  CLAIMED  — an executor owns it (claimed_by + runtime), work in flight.
  DONE     — the gate went green (recorded via release(done=True)).
  BLOCKED  — needs the founder / an external dependency (escalated, never
             a silent park; the agent-facing equivalent of `needs_root`).
There is deliberately NO "deferred"/"later" state — bare deferral is the exact
failure the drive kills (AgDR-0054 §"No 'later' as a legal state").
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # avoid a runtime import cycle; only needed for typing
    from .storage import BrainStore


# NEW brain_meta key — never collides with requirement_tree_v1 / calibration_v1
# / organize.clusters / diligence.stats / bound_owner_* / personal_cloud_sync.*
LEDGER_META_KEY = "active_work_v1"
LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "superseded_by_universal_cell"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False
# Durability siblings (same brain_meta table, additive keys). The last-good copy
# lets a corrupt/partial read RECOVER instead of returning {} (the founder's
# "data not persistent" fear); the corrupt blob is QUARANTINED, never discarded.
LEDGER_LASTGOOD_KEY = "active_work_v1__lastgood"
LEDGER_CORRUPT_PREFIX = "active_work_v1__corrupt_"


class LedgerCorruptError(RuntimeError):
    """The ledger blob would not parse AND no last-good copy exists to recover
    from. Raised LOUD instead of silently returning an empty ledger — losing
    every owner's open work on one bad read is the exact silent-data-loss the
    court refuted. The bad blob is quarantined under a corrupt-* key first."""


# ─────────────────────────── enums + models ────────────────────────────


class LeafState(str, Enum):
    OPEN = "open"          # unclaimed; claimable by any executor
    CLAIMED = "claimed"    # an executor owns it, work in flight
    DONE = "done"          # the gate went green (verified-complete)
    BLOCKED = "blocked"    # needs the founder / external dep (escalated)


# Terminal-ish: DONE is success; OPEN/CLAIMED are in-flight; BLOCKED waits on
# the founder. The drive is "dry" when no OPEN/CLAIMED leaf remains.
ACTIONABLE = (LeafState.OPEN, LeafState.CLAIMED)
SETUP_LEAF_PRIORITY = 10000
EXECUTABLE_GATE_KINDS = {
    "pytest",
    "py_compile",
    "file_exists",
    "grep_clean",
    "cdp",
    "mcp_tool",
    "hook_coverage_repair",
    "governance_gate_repair",
    "core_values_authority_repair",
    "core_values_trace_repair",
}


class WorkLeaf(BaseModel):
    leaf_id: str                              # sha256-derived stable id
    title: str                                # plain-English unit of work
    gate_kind: str = "manual"                 # py_compile|pytest|file_exists|grep_clean|cdp|manual
    gate_spec: dict[str, Any] = Field(default_factory=dict)  # args for the gate
    cde_container: dict[str, Any] = Field(default_factory=dict)  # ArchHub CDE metadata for hook scope gates
    governance_context: dict[str, Any] = Field(default_factory=dict)
    state: LeafState = LeafState.OPEN
    claimed_by: Optional[str] = None          # executor agent id (anti-self-cert anchor)
    runtime: Optional[str] = None             # which client owns it: claude_code|codex|gemini|composer
    fit: list[str] = Field(default_factory=list)  # capability tags this leaf needs (host/runtime hints)
    priority: int = 0                         # higher = pulled first (ties broken by created_at)
    attempts: int = 0                         # claim→release(done=False) cycles seen
    note: str = ""                            # last release note / block reason (honest escalation)
    evidence_ref: Optional[str] = None        # pointer to the proof the gate passed
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActiveWork(BaseModel):
    """Legacy Brain coordination ledger for one owner.

    Holds migration-stage leaves and the re-entry counter the Stop hook reads.
    The Universal Cell graph is the active product work authority.
    """
    owner_user: str = "founder"
    leaves: dict[str, WorkLeaf] = Field(default_factory=dict)   # leaf_id -> WorkLeaf
    iterations: int = 0                       # total re-entries (blocked-stop catches)
    cap: int = 12                             # re-entry cap before escalate
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── derived helpers ────────────────────────────────────────────────
    def actionable(self) -> list[WorkLeaf]:
        return [lf for lf in self.leaves.values() if lf.state in ACTIONABLE]

    def open_leaves(self) -> list[WorkLeaf]:
        return [lf for lf in self.leaves.values() if lf.state == LeafState.OPEN]


# ─────────────────────────── persistence ───────────────────────────────


def _parse_doc(raw: Optional[str]) -> Optional[dict[str, dict]]:
    """Parse the ledger blob. Returns the owner→ledger dict on success, or None
    when the blob is corrupt (unparseable / not a JSON object). An EMPTY blob
    (None / "") is a valid empty ledger → {} (NOT corruption)."""
    if not raw:
        return {}
    try:
        doc = json.loads(raw)
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


class ActiveWorkStore:
    """Thin wrapper over `BrainStore.update_meta` / `get_meta`.

    Stores ALL owners' ledgers as ONE JSON doc under
    `brain_meta[LEDGER_META_KEY]`:

        { owner_user: <ActiveWork json>, ... }

    Mirrors `requirement_tree.TreeStore` shape — never creates a table, never
    touches fragments / skills.

    TWO hard guarantees the court demanded (and the v0 forked copy lacked):

      * ATOMIC mutation. Every read-modify-write goes through ONE
        ``BrainStore.update_meta`` call, whose critical section is serialised on
        TWO levels: the store's RLock (across THREADS in one process) AND a
        ``BEGIN IMMEDIATE`` RESERVED-lock transaction (across CONNECTIONS /
        PROCESSES). The decide step is INSIDE both, so two racing pulls — whether
        two threads OR two separate daemon/hook processes on the same brain.db —
        can never both read OPEN and both claim (no TOCTOU double-claim, no lost
        update). The RLock alone is in-process only; the cross-process guarantee
        rests on BEGIN IMMEDIATE (see storage.update_meta).

      * DURABLE read. A corrupt/partial blob is NEVER silently dropped: the bad
        bytes are quarantined under a ``corrupt_*`` key, and the loader RECOVERS
        from the last-good copy. Only when there is genuinely no recoverable
        copy does it raise ``LedgerCorruptError`` — loud, never a silent {} that
        wipes every owner's open work.
    """

    def __init__(self, store: "BrainStore"):
        self.store = store

    # ── durable read ───────────────────────────────────────────────────
    def _load_all(self) -> dict[str, dict]:
        """Load the owner→ledger dict, recovering loudly on corruption.

        Bad blob → quarantine it + fall back to the last-good copy. If even the
        last-good copy is missing/corrupt → raise LedgerCorruptError (never
        return {} and silently erase the ledger)."""
        raw = self.store.get_meta(LEDGER_META_KEY)
        doc = _parse_doc(raw)
        if doc is not None:
            return doc
        # CORRUPT primary. Preserve the bad bytes, then try last-good. Only a
        # last-good key that ACTUALLY EXISTS and parses is a valid recovery — a
        # MISSING last-good key (None) is NOT a recoverable empty doc, it means
        # there is nothing to recover from, so we must raise (never invent {}).
        self._quarantine(raw)
        good_raw = self.store.get_meta(LEDGER_LASTGOOD_KEY)
        good = _parse_doc(good_raw) if good_raw is not None else None
        if good is not None:
            # Re-promote the recovered copy as the live ledger so the next
            # writer extends the good state, not the corrupt blob.
            self.store.set_meta(LEDGER_META_KEY, good_raw or json.dumps({}))
            return good
        raise LedgerCorruptError(
            "active-work ledger blob is corrupt and no last-good copy exists; "
            f"bad bytes quarantined under '{LEDGER_CORRUPT_PREFIX}*'. Refusing "
            "to silently return an empty ledger (would lose every owner's open "
            "work)."
        )

    def _quarantine(self, raw: Optional[str]) -> None:
        """Stash a corrupt blob under a timestamped corrupt-* key so the bytes
        are recoverable for forensics — never thrown away."""
        if not raw:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        try:
            self.store.set_meta(LEDGER_CORRUPT_PREFIX + ts, raw)
        except Exception:
            pass  # quarantine is best-effort; never block recovery on it

    # ── atomic mutation (single critical section) ───────────────────────
    def _mutate(self, fn: "Any") -> "Any":
        """Run ``fn(doc) -> result`` as ONE atomic read-modify-write.

        ``fn`` receives the live owner→ledger dict (already corruption-checked)
        and MUTATES IT IN PLACE; its return value is handed back to the caller.
        The whole load→fn→persist runs inside ``BrainStore.update_meta``'s lock,
        so the decision ``fn`` makes (e.g. "is this leaf still OPEN?") cannot be
        invalidated by a concurrent writer between read and write. On success the
        new doc is also mirrored to the last-good key for durable recovery."""
        box: dict[str, Any] = {}

        def _apply(old_raw: Optional[str]):
            doc = _parse_doc(old_raw)
            if doc is None:
                # Corrupt under the lock — recover via the durable path (which
                # quarantines + falls back to last-good or raises loudly).
                doc = self._load_all()
            box["result"] = fn(doc)
            new_raw = json.dumps(doc, default=str)
            box["new_raw"] = new_raw
            return new_raw, new_raw  # (value-to-persist, result passed through)

        new_raw = self.store.update_meta(LEDGER_META_KEY, _apply)
        # Mirror the just-persisted good state as the last-good copy (outside the
        # decision but still serialised by the same RLock per call).
        if new_raw is not None:
            try:
                self.store.set_meta(LEDGER_LASTGOOD_KEY, new_raw)
            except Exception:
                pass
        return box.get("result")

    def load(self, owner_user: str) -> Optional[ActiveWork]:
        doc = self._load_all()
        raw = doc.get(owner_user)
        if raw is None:
            return None
        try:
            return ActiveWork.model_validate(raw)
        except Exception:
            return None

    def load_or_new(self, owner_user: str) -> ActiveWork:
        return self.load(owner_user) or ActiveWork(owner_user=owner_user)

    def save(self, ledger: ActiveWork) -> None:
        """Persist a ledger atomically (single critical section). Bumps
        updated_at. Prefer the ``mutate_*`` helpers for read-modify-write — this
        last-writer-wins setter is for callers that built the ledger fresh."""
        ledger.updated_at = datetime.now(timezone.utc)

        def _fn(doc: dict[str, dict]):
            doc[ledger.owner_user] = ledger.model_dump(mode="json")
            return ledger

        self._mutate(_fn)

    def mutate_owner(self, owner_user: str, fn: "Any") -> "Any":
        """THE atomic read-modify-write over a SINGLE owner's ledger.

        Loads (or news) the owner's ActiveWork, calls ``fn(ledger) -> result``,
        persists the mutated ledger, and returns ``result`` — all inside ONE
        critical section. This is the choke point next_leaf / claim / release /
        add_leaves / bump_iteration route through so their decide-then-write is
        never split by a concurrent writer."""

        def _fn(doc: dict[str, dict]):
            raw = doc.get(owner_user)
            ledger: ActiveWork
            if raw is None:
                ledger = ActiveWork(owner_user=owner_user)
            else:
                try:
                    ledger = ActiveWork.model_validate(raw)
                except Exception:
                    # A single owner's slot is unparseable but the doc as a
                    # whole is fine — start that owner fresh rather than nuking
                    # the others. (Whole-doc corruption is handled in _load_all.)
                    ledger = ActiveWork(owner_user=owner_user)
            result = fn(ledger)
            ledger.updated_at = datetime.now(timezone.utc)
            doc[owner_user] = ledger.model_dump(mode="json")
            return result

        return self._mutate(_fn)

    def list_owners(self) -> list[str]:
        return sorted(self._load_all().keys())

    def delete(self, owner_user: str) -> bool:
        def _fn(doc: dict[str, dict]):
            if owner_user in doc:
                del doc[owner_user]
                return True
            return False

        return self._mutate(_fn)


# ─────────────────────────── id helper ─────────────────────────────────


def _default_owner(store: "BrainStore") -> str:
    """Best-effort owner resolution that honours a cloud binding when present,
    matching roma._default_owner / server.resolve_default_owner without
    importing build_server. Used by client_hook's in-process path."""
    import os
    try:
        bound = store.get_meta("bound_owner_user")
        if bound and bound.strip():
            return bound.strip()
    except Exception:
        pass
    return (
        os.environ.get("BRAIN_OWNER_USER")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "founder"
    )


def _leaf_id(owner_user: str, title: str) -> str:
    """sha256(owner|title)[:16] — stable, content-derived. Mirrors
    requirement_tree._node_id style. Stable so re-adding the SAME title for the
    same owner is idempotent (no duplicate leaves)."""
    h = hashlib.sha256()
    for part in (owner_user, title):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


# ─────────────────────────── API (the drive contract) ──────────────────


def add_leaves(
    store: "BrainStore",
    *,
    owner_user: str = "founder",
    leaves: list[dict],
) -> ActiveWork:
    """Enqueue work into the brain's ledger (the PRODUCER side).

    `leaves` = [{title, gate_kind?, gate_spec?, fit?, priority?}, ...]. Each
    becomes an OPEN leaf the brain will hand to the next fitting executor.
    Idempotent on identical titles per owner (re-adding keeps the existing
    leaf + its state — a DONE/CLAIMED leaf is not re-opened by re-adding)."""
    if not leaves:
        raise ValueError("add_leaves requires at least one leaf")
    aws = ActiveWorkStore(store)

    def _fn(ledger: ActiveWork) -> ActiveWork:
        now = datetime.now(timezone.utc)
        for spec in leaves:
            title = (spec.get("title") or "").strip()
            if not title:
                continue
            lid = _leaf_id(owner_user, title)
            if lid in ledger.leaves:
                # Governance sync may correct routing/gate metadata while work
                # is still OPEN. Once claimed/done/blocked, preserve the exact
                # assignment contract and its state (never re-open or retarget).
                existing = ledger.leaves[lid]
                if existing.state == LeafState.OPEN:
                    existing.gate_kind = (spec.get("gate_kind") or "manual")
                    existing.gate_spec = (spec.get("gate_spec") or {})
                    existing.cde_container = (spec.get("cde_container") or {})
                    existing.governance_context = (
                        spec.get("governance_context") or {}
                    )
                    existing.fit = list(spec.get("fit") or [])
                    existing.priority = int(spec.get("priority") or 0)
                    existing.updated_at = now
                continue
            ledger.leaves[lid] = WorkLeaf(
                leaf_id=lid,
                title=title,
                gate_kind=(spec.get("gate_kind") or "manual"),
                gate_spec=(spec.get("gate_spec") or {}),
                cde_container=(spec.get("cde_container") or {}),
                governance_context=(spec.get("governance_context") or {}),
                fit=list(spec.get("fit") or []),
                priority=int(spec.get("priority") or 0),
                state=LeafState.OPEN,
                created_at=now,
                updated_at=now,
            )
        return ledger

    # Atomic read-modify-write: the whole enqueue is one critical section, so a
    # concurrent producer never clobbers leaves this call added (lost update).
    return aws.mutate_owner(owner_user, _fn)


def _fits(leaf: WorkLeaf, fit: Optional[list[str]]) -> bool:
    """A leaf is eligible for a runtime with capabilities `fit` iff EVERY tag
    the leaf requires is offered. A leaf with no fit requirement fits anyone.
    `fit=None` (an executor that advertises nothing) only matches no-requirement
    leaves — so a specialised leaf is never handed to a runtime that can't do it."""
    if not leaf.fit:
        return True
    offered = set(fit or [])
    return set(leaf.fit).issubset(offered)


def _next_open_candidate(
    store: "BrainStore",
    *,
    runtime: str,
    fit: Optional[list[str]] = None,
    owner_user: str = "founder",
) -> Optional[WorkLeaf]:
    ledger = get_ledger(store, owner_user=owner_user)
    if ledger is None:
        return None
    candidates = [lf for lf in ledger.open_leaves() if _fits(lf, fit)]
    if not candidates:
        return None
    candidates.sort(key=lambda lf: (-lf.priority, lf.created_at, lf.leaf_id))
    return candidates[0]


def _executable_gate_decision(leaf: WorkLeaf) -> dict[str, Any]:
    kind = (leaf.gate_kind or "").strip().lower()
    if not kind or kind == "manual":
        return {
            "allowed": False,
            "reason": f"leaf '{leaf.title}' has no executable gate",
        }
    if kind not in EXECUTABLE_GATE_KINDS:
        return {
            "allowed": False,
            "reason": f"leaf '{leaf.title}' uses unsupported gate '{leaf.gate_kind}'",
        }
    if kind not in {"py_compile"} and not leaf.gate_spec:
        return {
            "allowed": False,
            "reason": f"leaf '{leaf.title}' gate '{leaf.gate_kind}' has empty gate_spec",
        }
    return {"allowed": True, "reason": ""}


def _ensure_setup_leaf(
    store: "BrainStore",
    *,
    owner_user: str,
    title: str,
    gate_kind: str,
    gate_spec: dict[str, Any],
) -> WorkLeaf:
    add_leaves(
        store,
        owner_user=owner_user,
        leaves=[{
            "title": title,
            "gate_kind": gate_kind,
            "gate_spec": gate_spec,
            "fit": ["governance"],
            "priority": SETUP_LEAF_PRIORITY,
        }],
    )
    ledger = get_ledger(store, owner_user=owner_user)
    if ledger is None:
        raise RuntimeError("setup leaf was not persisted")
    return ledger.leaves[_leaf_id(owner_user, title)]


def _format_setup_leaf_block(reason: str, leaf: WorkLeaf) -> str:
    lines = [
        '<governance_setup_leaf status="blocked">',
        f"Decision: refuse unsafe write-capable assigned work before claim.",
        f"Reason: {reason}",
        f"Setup leaf: {leaf.title}",
        f"Gate: {leaf.gate_kind} {json.dumps(leaf.gate_spec, sort_keys=True)}",
        "Action: complete this setup leaf, then call brain.work_assigned_block again.",
        "</governance_setup_leaf>",
    ]
    return "\n".join(lines)


def _workshop_injection_block(store: "BrainStore") -> str:
    try:
        from .cell_room_wiring import (
            cell_room_enabled, cell_room_injection_tail, cell_room_is_wired,
        )
        if cell_room_enabled():
            if cell_room_is_wired():
                return cell_room_injection_tail().strip()
            return (
                '<meeting_room status="blocked" '
                'authority="application-owned Universal Cell Workshop">\n'
                "Universal Workshop is enabled but not wired; "
                "legacy meeting_room_v1 is not claim authority.\n"
                "</meeting_room>"
            )
    except Exception as ex:
        return (
            '<meeting_room status="blocked" '
            'authority="application-owned Universal Cell Workshop">\n'
            f"Universal Workshop gate unavailable: {type(ex).__name__}.\n"
            "</meeting_room>"
        )
    try:
        from .meeting_room import room_injection_block
        return room_injection_block(store).strip()
    except Exception:
        return ""


def _workshop_leaf_gate(
    store: "BrainStore", leaf_id: str, phase: str
) -> dict[str, object]:
    try:
        from .cell_room_wiring import (
            cell_room_enabled, cell_room_is_wired, cell_room_leaf_gate,
        )
        if cell_room_enabled():
            if cell_room_is_wired():
                return cell_room_leaf_gate(leaf_id, phase)
            return {
                "allowed": False,
                "missing": ["cell_room_unwired"],
                "authority": "application-owned Universal Cell Workshop",
                "phase": phase,
                "leaf_id": leaf_id,
            }
    except Exception as ex:
        return {
            "allowed": False,
            "missing": [f"cell_room_error:{type(ex).__name__}"],
            "authority": "application-owned Universal Cell Workshop",
            "phase": phase,
            "leaf_id": leaf_id,
        }
    try:
        from .meeting_room import room_leaf_gate
        return room_leaf_gate(store, leaf_id, phase)
    except Exception as ex:
        return {
            "allowed": False,
            "missing": [f"meeting_room_error:{type(ex).__name__}"],
        }


def _prepend_workshop_authority(store: "BrainStore", block: str) -> str:
    """Attach the mandatory workshop tail to every assignment response.

    brain.context already injects the room, but work assignment is the hard
    choke point for write-capable work. Keeping the workshop here as well makes
    the authority visible even when a client calls brain.work_assigned_block
    directly.
    """
    room_block = _workshop_injection_block(store)
    block = (block or "").strip()
    if room_block and block:
        return room_block + "\n" + block
    return room_block or block


def next_leaf(
    store: "BrainStore",
    *,
    runtime: str,
    fit: Optional[list[str]] = None,
    owner_user: str = "founder",
    agent_id: Optional[str] = None,
) -> Optional[WorkLeaf]:
    """THE DRIVER. Atomically hand the next OPEN, fitting leaf to a runtime and
    CLAIM it (OPEN → CLAIMED) in one read-modify-write — so two racing pulls
    can never grab the same leaf (the brain is the single arbiter).

    Selection: highest `priority`, ties broken by oldest `created_at`, among
    OPEN leaves whose `fit` requirements ⊆ the runtime's `fit` capabilities.
    Records claimed_by = agent_id (default: the runtime) — the anti-self-certify
    anchor the court/gate later checks. Returns the claimed leaf, or None when
    nothing is open/fitting (the runtime's frontier is dry).

    This is the ONE call every client's pre-prompt makes (via client_hook) so
    the brain — not the agent — decides what each runtime works on next."""
    if not (runtime or "").strip():
        raise ValueError("next_leaf requires a non-empty runtime")
    aws = ActiveWorkStore(store)

    def _fn(ledger: ActiveWork) -> Optional[WorkLeaf]:
        # SELECT + CLAIM are ONE critical section. On the old code the select
        # (load) released the lock before the claim (save) re-acquired it, so
        # two racing pulls both read the SAME leaf as OPEN and both claimed it
        # (deterministic double-claim — court-reproduced). Here the decide step
        # runs under the store's RLock, so the second pull sees state=CLAIMED
        # and skips it. The arbiter is single-threaded by construction.
        candidates = [lf for lf in ledger.open_leaves() if _fits(lf, fit)]
        if not candidates:
            return None
        # highest priority first; tie -> oldest created_at first (stable FIFO).
        candidates.sort(key=lambda lf: (-lf.priority, lf.created_at, lf.leaf_id))
        chosen = candidates[0]
        g = _workshop_leaf_gate(store, chosen.leaf_id, "claim")
        if not g.get("allowed", True):
            return None
        chosen.state = LeafState.CLAIMED
        chosen.claimed_by = (agent_id or runtime)
        chosen.runtime = runtime
        chosen.updated_at = datetime.now(timezone.utc)
        return chosen

    return aws.mutate_owner(owner_user, _fn)


def add_leaves_cell_first(
    store: "BrainStore",
    *,
    leaves: list[dict],
    owner_user: str = "founder",
    cell_bridge: Any = None,
) -> dict[str, Any]:
    """Create Cell request/outcome records before a legacy producer mutation."""
    request_payload = {
        "operation": "work_add",
        "owner_user": owner_user,
        "leaves": _jsonable(leaves),
        "requested_at": _utc_now_iso(),
    }
    rid = _request_id(request_payload)
    try:
        bridge = _cell_bridge_or_default(cell_bridge)
        request_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-request:{rid}",
            scope="founder/brain-control/active-work",
            claims=request_payload,
            provenance="personal_brain.active_work:cell_first_request",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        ledger = add_leaves(store, owner_user=owner_user, leaves=leaves)
    except Exception as exc:
        return _add_leaves_cell_first_denied(
            bridge,
            request_record=request_record,
            request_payload=request_payload,
            reason=f"{type(exc).__name__}: {exc}",
        )

    returned = _returned_added_leaves(
        owner_user=owner_user,
        leaves=leaves,
        ledger=ledger,
    )
    outcome_payload = {
        "operation": "work_add",
        "request_root": str(request_record["created_root"]),
        "owner_user": owner_user,
        "leaf_ids": [leaf["leaf_id"] for leaf in returned],
        "leaf_count": len(returned),
        "status": status(store, owner_user=owner_user),
        "recorded_at": _utc_now_iso(),
    }
    oid = _request_id(outcome_payload)
    try:
        outcome_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-outcome:{oid}",
            scope="founder/brain-control/active-work",
            claims=outcome_payload,
            provenance="personal_brain.active_work:cell_first_outcome",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": True,
            "side_effect_executed": True,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "leaves": returned,
            "leaf": returned[0] if len(returned) == 1 else None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    compliance_event = _append_compliance_event_cell_first_best_effort(
        store,
        owner_user=owner_user,
        cell_bridge=bridge,
        event={
            "event_type": "active_work_add",
            "source": "active_work_cell_first",
            "leaf_ids": [leaf["leaf_id"] for leaf in returned],
            "leaf_count": len(returned),
            "request_cell_record_root": str(request_record["created_root"]),
            "outcome_cell_record_root": str(outcome_record["created_root"]),
        },
    )
    return {
        "ok": True,
        "cell_first": True,
        "brain_written": True,
        "side_effect_executed": True,
        "owner_user": owner_user,
        "leaves": returned,
        "leaf": returned[0] if len(returned) == 1 else None,
        "status": status(store, owner_user=owner_user),
        "request_cell_record": request_record,
        "request_cell_record_root": str(request_record["created_root"]),
        "outcome_cell_record": outcome_record,
        "outcome_cell_record_root": str(outcome_record["created_root"]),
        "compliance_event": compliance_event,
    }


def _returned_added_leaves(
    *,
    owner_user: str,
    leaves: list[dict],
    ledger: ActiveWork,
) -> list[dict[str, Any]]:
    returned = []
    seen = set()
    for spec in leaves:
        title = str(spec.get("title") or "").strip()
        if not title:
            continue
        leaf_id = _leaf_id(owner_user, title)
        leaf = ledger.leaves.get(leaf_id)
        if leaf is not None and leaf_id not in seen:
            returned.append(leaf.model_dump(mode="json"))
            seen.add(leaf_id)
    return returned


def _add_leaves_cell_first_denied(
    cell_bridge: Any,
    *,
    request_record: dict[str, Any],
    request_payload: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    outcome_payload = {
        "operation": "work_add",
        "request_root": str(request_record["created_root"]),
        "owner_user": request_payload.get("owner_user", ""),
        "accepted": False,
        "reason": reason,
        "recorded_at": _utc_now_iso(),
    }
    oid = _request_id(outcome_payload)
    try:
        outcome_record = _cell_first_record(
            cell_bridge,
            source=f"brain-control:active-work-outcome:{oid}",
            scope="founder/brain-control/active-work",
            claims=outcome_payload,
            provenance="personal_brain.active_work:cell_first_denial",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "error": f"{type(exc).__name__}: {exc}",
            "denial_reason": reason,
        }
    return {
        "ok": False,
        "cell_first": True,
        "brain_written": False,
        "side_effect_executed": False,
        "request_cell_record": request_record,
        "request_cell_record_root": str(request_record["created_root"]),
        "outcome_cell_record": outcome_record,
        "outcome_cell_record_root": str(outcome_record["created_root"]),
        "error": reason,
    }


def claim(
    store: "BrainStore",
    *,
    leaf_id: str,
    agent_id: str,
    runtime: str = "",
    owner_user: str = "founder",
) -> WorkLeaf:
    """Claim a SPECIFIC open leaf by id (OPEN → CLAIMED). Records claimed_by =
    agent_id (REQUIRED — the anti-self-certify anchor). Re-claim by the same
    agent is idempotent; a claim on a leaf owned by a DIFFERENT agent is
    refused; a DONE leaf is refused (nothing to claim)."""
    if not (agent_id or "").strip():
        raise ValueError("claim requires a non-empty agent_id (anti-self-certify anchor)")
    aws = ActiveWorkStore(store)

    def _fn(ledger: ActiveWork) -> WorkLeaf:
        # check-then-set under one lock: the "already claimed by another?" guard
        # and the claim write can't be split by a concurrent claimer.
        leaf = ledger.leaves.get(leaf_id)
        if leaf is None:
            raise KeyError(f"leaf '{leaf_id}' not found for owner '{owner_user}'")
        if leaf.state == LeafState.DONE:
            raise ValueError(f"leaf '{leaf_id}' is DONE — nothing to claim")
        if leaf.claimed_by and leaf.claimed_by != agent_id:
            raise ValueError(
                f"leaf '{leaf_id}' already claimed by '{leaf.claimed_by}' "
                f"(requested by '{agent_id}')"
            )
        # WORKSHOP AUTHORITY (founder 2026-07-17): the workshop is a GATE on
        # work, not a journal. No claim without a PLAN posted in the governed
        # Workshop for this leaf -- so every agent plans in the open first. A
        # re-claim by the same agent is exempt (already in flight).
        if leaf.claimed_by != agent_id:
            g = _workshop_leaf_gate(store, leaf_id, "claim")
            if not g.get("allowed", True):
                raise PermissionError(
                    f"WORKSHOP GATE: cannot claim '{leaf_id}' -- missing "
                    f"{g.get('missing')} in the governed Workshop. Post kind=plan "
                    f"with refs=['{leaf_id}'] via brain.room_say FIRST (so every "
                    f"agent sees + weighs in), then claim.")
        leaf.claimed_by = agent_id
        if runtime:
            leaf.runtime = runtime
        leaf.state = LeafState.CLAIMED
        leaf.updated_at = datetime.now(timezone.utc)
        return leaf

    return aws.mutate_owner(owner_user, _fn)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except Exception:
        return {"unserializable": str(value)}


def _cell_first_record(
    cell_bridge: Any,
    *,
    source: str,
    scope: str,
    claims: dict[str, Any],
    provenance: str,
) -> dict[str, Any]:
    return cell_bridge.assembly_create(
        definition_key="knowledge-branch",
        fields={
            "source": source,
            "scope": scope,
            "claims": json.dumps(_jsonable(claims), sort_keys=True),
            "provenance": provenance,
        },
        idempotency_field="source",
    )


def _cell_bridge_or_default(cell_bridge: Any = None) -> Any:
    if cell_bridge is not None:
        return cell_bridge
    from .universal_runtime import UniversalRuntimeBridge

    return UniversalRuntimeBridge()


def _request_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def next_leaf_cell_first(
    store: "BrainStore",
    *,
    runtime: str,
    fit: Optional[list[str]] = None,
    owner_user: str = "founder",
    agent_id: Optional[str] = None,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    """Create Cell request/outcome records before exposing a legacy claim.

    This is a migration bridge for callers that still cannot provide a Universal
    Agent Session. The Cell records are the visible authority trail; the legacy
    `active_work_v1` row is only the compatibility projection being updated.
    """
    if not (runtime or "").strip():
        raise ValueError("next_leaf_cell_first requires a non-empty runtime")
    if _next_open_candidate(
        store, runtime=runtime, fit=fit, owner_user=owner_user
    ) is None:
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "owner_user": owner_user,
            "leaf": None,
            "frontier_dry": True,
        }
    request_payload = {
        "operation": "work_next",
        "owner_user": owner_user,
        "runtime": runtime,
        "fit": list(fit or []),
        "agent_id": agent_id or runtime,
        "requested_at": _utc_now_iso(),
    }
    rid = _request_id(request_payload)
    try:
        bridge = _cell_bridge_or_default(cell_bridge)
        request_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-request:{rid}",
            scope="founder/brain-control/active-work",
            claims=request_payload,
            provenance="personal_brain.active_work:cell_first_request",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    leaf: Optional[WorkLeaf] = None
    try:
        leaf = next_leaf(
            store,
            runtime=runtime,
            fit=fit,
            owner_user=owner_user,
            agent_id=agent_id,
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "error": f"{type(exc).__name__}: {exc}",
        }

    leaf_payload = leaf.model_dump(mode="json") if leaf else None
    outcome_payload = {
        "operation": "work_next",
        "request_root": str(request_record["created_root"]),
        "owner_user": owner_user,
        "runtime": runtime,
        "assigned": leaf is not None,
        "leaf_id": leaf.leaf_id if leaf else "",
        "leaf": leaf_payload,
        "recorded_at": _utc_now_iso(),
    }
    oid = _request_id(outcome_payload)
    try:
        outcome_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-outcome:{oid}",
            scope="founder/brain-control/active-work",
            claims=outcome_payload,
            provenance="personal_brain.active_work:cell_first_outcome",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": leaf is not None,
            "side_effect_executed": leaf is not None,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "leaf": leaf_payload,
            "error": f"{type(exc).__name__}: {exc}",
        }

    compliance_event = _append_compliance_event_cell_first_best_effort(
        store,
        owner_user=owner_user,
        cell_bridge=bridge,
        event={
            "event_type": "active_work_next_claim",
            "source": "active_work_cell_first",
            "runtime": runtime,
            "agent_id": agent_id or runtime,
            "leaf_id": leaf.leaf_id if leaf else "",
            "assigned": leaf is not None,
            "request_cell_record_root": str(request_record["created_root"]),
            "outcome_cell_record_root": str(outcome_record["created_root"]),
        },
    )
    return {
        "ok": True,
        "cell_first": True,
        "brain_written": leaf is not None,
        "side_effect_executed": leaf is not None,
        "owner_user": owner_user,
        "leaf": leaf_payload,
        "request_cell_record": request_record,
        "request_cell_record_root": str(request_record["created_root"]),
        "outcome_cell_record": outcome_record,
        "outcome_cell_record_root": str(outcome_record["created_root"]),
        "compliance_event": compliance_event,
    }


def claim_cell_first(
    store: "BrainStore",
    *,
    leaf_id: str,
    agent_id: str,
    runtime: str = "",
    owner_user: str = "founder",
    cell_bridge: Any = None,
) -> dict[str, Any]:
    """Create Cell request/outcome records before a specific legacy claim."""
    request_payload = {
        "operation": "work_claim",
        "owner_user": owner_user,
        "runtime": runtime,
        "leaf_id": leaf_id,
        "agent_id": agent_id,
        "requested_at": _utc_now_iso(),
    }
    rid = _request_id(request_payload)
    try:
        bridge = _cell_bridge_or_default(cell_bridge)
        request_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-request:{rid}",
            scope="founder/brain-control/active-work",
            claims=request_payload,
            provenance="personal_brain.active_work:cell_first_request",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        leaf = claim(
            store,
            leaf_id=leaf_id,
            agent_id=agent_id,
            runtime=runtime,
            owner_user=owner_user,
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "error": f"{type(exc).__name__}: {exc}",
        }

    leaf_payload = leaf.model_dump(mode="json")
    outcome_payload = {
        "operation": "work_claim",
        "request_root": str(request_record["created_root"]),
        "owner_user": owner_user,
        "runtime": runtime,
        "leaf_id": leaf.leaf_id,
        "claimed_by": leaf.claimed_by,
        "leaf": leaf_payload,
        "recorded_at": _utc_now_iso(),
    }
    oid = _request_id(outcome_payload)
    try:
        outcome_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-outcome:{oid}",
            scope="founder/brain-control/active-work",
            claims=outcome_payload,
            provenance="personal_brain.active_work:cell_first_outcome",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": True,
            "side_effect_executed": True,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "leaf": leaf_payload,
            "error": f"{type(exc).__name__}: {exc}",
        }

    compliance_event = _append_compliance_event_cell_first_best_effort(
        store,
        owner_user=owner_user,
        cell_bridge=bridge,
        event={
            "event_type": "active_work_claim",
            "source": "active_work_cell_first",
            "runtime": runtime,
            "agent_id": agent_id,
            "leaf_id": leaf.leaf_id,
            "request_cell_record_root": str(request_record["created_root"]),
            "outcome_cell_record_root": str(outcome_record["created_root"]),
        },
    )
    return {
        "ok": True,
        "cell_first": True,
        "brain_written": True,
        "side_effect_executed": True,
        "owner_user": owner_user,
        "leaf": leaf_payload,
        "request_cell_record": request_record,
        "request_cell_record_root": str(request_record["created_root"]),
        "outcome_cell_record": outcome_record,
        "outcome_cell_record_root": str(outcome_record["created_root"]),
        "compliance_event": compliance_event,
    }


def release_cell_first(
    store: "BrainStore",
    *,
    leaf_id: str,
    done: bool,
    owner_user: str = "founder",
    note: str = "",
    evidence_ref: Optional[str] = None,
    blocked: bool = False,
    cell_bridge: Any = None,
) -> dict[str, Any]:
    """Create Cell request/outcome records before a legacy release mutation."""
    request_payload = {
        "operation": "work_release",
        "owner_user": owner_user,
        "leaf_id": leaf_id,
        "done": bool(done),
        "blocked": bool(blocked),
        "note": note,
        "evidence_ref": evidence_ref or "",
        "requested_at": _utc_now_iso(),
    }
    rid = _request_id(request_payload)
    try:
        bridge = _cell_bridge_or_default(cell_bridge)
        request_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-request:{rid}",
            scope="founder/brain-control/active-work",
            claims=request_payload,
            provenance="personal_brain.active_work:cell_first_request",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if done:
        try:
            from . import run_report as rr

            has_report = rr.has_run_report_for_leaf(
                store,
                owner_user=owner_user,
                leaf_id=leaf_id,
            )
        except Exception:
            has_report = False
        if not has_report:
            return _release_cell_first_denied(
                bridge,
                request_record=request_record,
                request_payload=request_payload,
                reason="run_report_required",
            )

    try:
        leaf = release(
            store,
            leaf_id=leaf_id,
            done=done,
            owner_user=owner_user,
            note=note,
            evidence_ref=evidence_ref,
            blocked=blocked,
        )
    except Exception as exc:
        return _release_cell_first_denied(
            bridge,
            request_record=request_record,
            request_payload=request_payload,
            reason=f"{type(exc).__name__}: {exc}",
        )

    leaf_payload = leaf.model_dump(mode="json")
    outcome_payload = {
        "operation": "work_release",
        "request_root": str(request_record["created_root"]),
        "owner_user": owner_user,
        "leaf_id": leaf.leaf_id,
        "state": leaf.state.value,
        "done": bool(done),
        "blocked": bool(blocked),
        "leaf": leaf_payload,
        "recorded_at": _utc_now_iso(),
    }
    oid = _request_id(outcome_payload)
    try:
        outcome_record = _cell_first_record(
            bridge,
            source=f"brain-control:active-work-outcome:{oid}",
            scope="founder/brain-control/active-work",
            claims=outcome_payload,
            provenance="personal_brain.active_work:cell_first_outcome",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": True,
            "side_effect_executed": True,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "leaf": leaf_payload,
            "error": f"{type(exc).__name__}: {exc}",
        }

    compliance_event = _append_compliance_event_cell_first_best_effort(
        store,
        owner_user=owner_user,
        cell_bridge=bridge,
        event={
            "event_type": "active_work_release",
            "source": "active_work_cell_first",
            "leaf_id": leaf.leaf_id,
            "state": leaf.state.value,
            "done": bool(done),
            "blocked": bool(blocked),
            "request_cell_record_root": str(request_record["created_root"]),
            "outcome_cell_record_root": str(outcome_record["created_root"]),
        },
    )
    return {
        "ok": True,
        "cell_first": True,
        "brain_written": True,
        "side_effect_executed": True,
        "owner_user": owner_user,
        "leaf": leaf_payload,
        "status": status(store, owner_user=owner_user),
        "request_cell_record": request_record,
        "request_cell_record_root": str(request_record["created_root"]),
        "outcome_cell_record": outcome_record,
        "outcome_cell_record_root": str(outcome_record["created_root"]),
        "compliance_event": compliance_event,
    }


def _release_cell_first_denied(
    cell_bridge: Any,
    *,
    request_record: dict[str, Any],
    request_payload: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    outcome_payload = {
        "operation": "work_release",
        "request_root": str(request_record["created_root"]),
        "owner_user": request_payload.get("owner_user", ""),
        "leaf_id": request_payload.get("leaf_id", ""),
        "accepted": False,
        "reason": reason,
        "recorded_at": _utc_now_iso(),
    }
    oid = _request_id(outcome_payload)
    try:
        outcome_record = _cell_first_record(
            cell_bridge,
            source=f"brain-control:active-work-outcome:{oid}",
            scope="founder/brain-control/active-work",
            claims=outcome_payload,
            provenance="personal_brain.active_work:cell_first_denial",
        )
    except Exception as exc:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "side_effect_executed": False,
            "request_cell_record": request_record,
            "request_cell_record_root": str(request_record["created_root"]),
            "error": f"{type(exc).__name__}: {exc}",
            "denial_reason": reason,
        }
    return {
        "ok": False,
        "cell_first": True,
        "brain_written": False,
        "side_effect_executed": False,
        "request_cell_record": request_record,
        "request_cell_record_root": str(request_record["created_root"]),
        "outcome_cell_record": outcome_record,
        "outcome_cell_record_root": str(outcome_record["created_root"]),
        "code": reason,
        "error": reason,
    }


def _append_compliance_event_cell_first_best_effort(
    store: "BrainStore",
    *,
    owner_user: str,
    cell_bridge: Any,
    event: dict[str, Any],
) -> dict[str, Any]:
    try:
        from . import compliance_report as cr

        return cr.append_compliance_event_cell_first(
            store,
            owner_user=owner_user,
            cell_bridge=cell_bridge,
            event=event,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def release(
    store: "BrainStore",
    *,
    leaf_id: str,
    done: bool,
    owner_user: str = "founder",
    note: str = "",
    evidence_ref: Optional[str] = None,
    blocked: bool = False,
) -> WorkLeaf:
    """Report the outcome of a claimed leaf (the CONSUMER side of the drive).

      done=True            → DONE (verified-complete; records evidence_ref).
      done=False           → re-OPEN the leaf (bumps attempts, frees the claim)
                             so it re-enters the frontier for the next pull.
      done=False+blocked   → BLOCKED (needs the founder / external dep). An
                             honest escalation, NOT a silent park — there is no
                             "later" state.

    Mirrors requirement_tree.set_verdict's red-path (bump attempts + clear the
    claim). Returns the updated leaf."""
    aws = ActiveWorkStore(store)

    def _fn(ledger: ActiveWork) -> WorkLeaf:
        leaf = ledger.leaves.get(leaf_id)
        if leaf is None:
            raise KeyError(f"leaf '{leaf_id}' not found for owner '{owner_user}'")
        now = datetime.now(timezone.utc)
        leaf.note = note or leaf.note
        leaf.updated_at = now
        if done:
            # WORKSHOP AUTHORITY (founder 2026-07-17): no 'done' without TEST +
            # DOC + COURT verdict in the governed Workshop for this leaf. The
            # court is present in the workshop; completion is proven there, in
            # the open.
            g = _workshop_leaf_gate(store, leaf_id, "done")
            if not g.get("allowed", True):
                raise PermissionError(
                    f"WORKSHOP GATE: cannot mark '{leaf_id}' done -- missing "
                    f"{g.get('missing')} in the governed Workshop. Post the test "
                    f"result + documentation (refs=['{leaf_id}']) and run the "
                    f"graph court (brain.universal_work_court) FIRST.")
            leaf.state = LeafState.DONE
            leaf.evidence_ref = evidence_ref
        elif blocked:
            leaf.state = LeafState.BLOCKED
            leaf.claimed_by = None
        else:
            leaf.state = LeafState.OPEN
            leaf.claimed_by = None
            leaf.attempts += 1
        return leaf

    return aws.mutate_owner(owner_user, _fn)


def bump_iteration(store: "BrainStore", *, owner_user: str = "founder") -> int:
    """Record one Stop-hook re-entry (the gate blocked a premature stop + fed
    the agent the unfinished list). The cap on these is the anti-infinite-grind
    backstop. Mirrors tools/active_work.bump while Cell-native work replaces
    this BrainStore projection."""
    aws = ActiveWorkStore(store)

    def _fn(ledger: ActiveWork) -> int:
        ledger.iterations += 1
        return ledger.iterations

    return aws.mutate_owner(owner_user, _fn)


def status(store: "BrainStore", *, owner_user: str = "founder") -> dict[str, Any]:
    """Read the drive's state for an owner — the done-rule the Stop hook + every
    client reads. `dry` is True iff NO actionable (open/claimed) leaf remains
    AND there are leaves at all (an empty ledger is not "done", it is "idle").
    A BLOCKED leaf keeps the drive NOT dry (it waits on the founder), mirroring
    sweep()'s needs_root handling.

    Returns {owner_user, dry, counts:{open,claimed,done,blocked}, total,
    actionable, blocked:[leaf_id...], iterations, cap}."""
    aws = ActiveWorkStore(store)
    ledger = aws.load(owner_user)
    if ledger is None:
        return {
            "owner_user": owner_user, "dry": False, "exists": False,
            "counts": {s.value: 0 for s in LeafState}, "total": 0,
            "actionable": 0, "blocked": [], "iterations": 0, "cap": 12,
        }
    counts = {s.value: 0 for s in LeafState}
    for lf in ledger.leaves.values():
        counts[lf.state.value] += 1
    actionable = ledger.actionable()
    blocked = [lf.leaf_id for lf in ledger.leaves.values()
               if lf.state == LeafState.BLOCKED]
    total = len(ledger.leaves)
    # dry == nothing left to work AND nothing escalated AND there WAS work.
    dry = (not actionable) and (not blocked) and total > 0
    return {
        "owner_user": owner_user,
        "dry": dry,
        "exists": True,
        "counts": counts,
        "total": total,
        "actionable": len(actionable),
        "blocked": blocked,
        "iterations": ledger.iterations,
        "cap": ledger.cap,
    }


def get_ledger(store: "BrainStore", *, owner_user: str = "founder") -> Optional[ActiveWork]:
    """Convenience read-through for callers (client_hook, the Stop gate)."""
    return ActiveWorkStore(store).load(owner_user)


def list_owners(store: "BrainStore") -> list[str]:
    return ActiveWorkStore(store).list_owners()


# ─────────────────────────── MCP tool registration ─────────────────────


def _active_cde_state_path(*, runtime: str = "", session_id: str = "") -> Path:
    raw = os.environ.get("ARCHHUB_ACTIVE_CDE_STATE", "").strip()
    if raw:
        return Path(raw)
    base = os.environ.get("LOCALAPPDATA")
    root = (Path(base) / "ArchHub") if base else (Path.home() / ".archhub")
    identity = session_id.strip()
    runtime_name = runtime.strip().lower()
    if identity:
        digest = hashlib.sha256(
            runtime_name.encode("utf-8")
            + b"\x00"
            + identity.encode("utf-8")
        ).hexdigest()
        return root / "active_cde" / (digest + ".json")
    if runtime_name:
        safe = "".join(
            character if character.isalnum() else "_"
            for character in runtime_name
        ).strip("_")
        if safe:
            return root / ("active_cde_%s.json" % safe)
    return root / "active_cde_container.json"


def _clear_active_cde_state(*, runtime: str = "", session_id: str = "") -> None:
    try:
        path = _active_cde_state_path(runtime=runtime, session_id=session_id)
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _workspace_root() -> Path:
    configured = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "00.GOVERNANCE").is_dir():
            return candidate
    return Path.cwd().resolve()


def _latest_work_court_event(
    store: "BrainStore", *, owner_user: str, leaf_id: str,
) -> Optional[dict[str, Any]]:
    try:
        from . import compliance_report as cr

        history = cr.get_compliance_history(
            store, owner_user=owner_user, limit=cr.HISTORY_LIMIT)
        for event in history.get("events") or []:
            if event.get("event_type") == "work_court_verdict" \
                    and event.get("leaf_id") == leaf_id:
                return event
    except Exception:
        return None
    return None


def _run_report_proof_signals(run_report: Optional[dict[str, Any]]) -> dict[str, bool]:
    """Translate structured run-report evidence into diligence proof signals."""
    report = run_report if isinstance(run_report, dict) else {}
    sections = report.get("sections")
    sections = sections if isinstance(sections, dict) else {}
    lines = sections.get("evidence")
    lines = lines if isinstance(lines, list) else []
    evidence = "\n".join(str(line).lower() for line in lines if line)
    changed_nodes = report.get("changed_nodes")
    changed_nodes = changed_nodes if isinstance(changed_nodes, list) else []
    return {
        "wrote_files": bool(changed_nodes),
        "ran_tests": "pytest" in evidence and "passed" in evidence,
        "ran_curl": "curl" in evidence and any(
            marker in evidence for marker in ("http 200", "status 200", "passed")),
        "ran_build": any(
            marker in evidence for marker in ("ran build", "build passed")),
        "started_server": any(
            marker in evidence for marker in ("server started", "serving on")),
        "took_screenshot": any(
            marker in evidence
            for marker in ("captured screenshot", "screenshot evidence")),
    }


def _write_active_cde_state(
    leaf: Optional[dict[str, Any]],
    *,
    runtime: str,
    session_id: str = "",
) -> None:
    try:
        container = None
        if isinstance(leaf, dict):
            value = leaf.get("cde_container")
            if isinstance(value, dict) and value.get("container_id"):
                container = value
            else:
                gate_spec = leaf.get("gate_spec")
                if isinstance(gate_spec, dict):
                    value = gate_spec.get("cde_container")
                    if isinstance(value, dict) and value.get("container_id"):
                        container = value
        if not container:
            return
        payload = {
            "schema": "archhub-active-cde/v1",
            "runtime": runtime,
            "session_id": session_id,
            "leaf_id": leaf.get("leaf_id", ""),
            "title": leaf.get("title", ""),
            "cwd": os.getcwd(),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "container": container,
        }
        path = _active_cde_state_path(runtime=runtime, session_id=session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def register_active_work_tools(mcp: "Any", store: "BrainStore") -> "Any":
    """Register the additive `brain.work_*` MCP tools — the BRAIN-DRIVER surface
    (BRV-01). `server.build_server` adds exactly ONE call to this next to
    `register_tree_tools` / `register_roma_tools`.

    Legacy Brain work records are migration evidence only. Every public Work
    tool now either uses the Universal Cell runtime or explicitly refuses; no
    Cell-first wrapper may make the legacy ledger authoritative. Returns `mcp`."""

    def _resolve_owner() -> str:
        """Reuse the daemon's bound owner when the server exposed a resolver
        (server.build_server sets `mcp._brain_resolve_owner`); else 'founder'.
        Mirrors register_tree_tools._resolve_owner EXACTLY."""
        try:
            getter = getattr(mcp, "_brain_resolve_owner", None)
            if callable(getter):
                val = getter()
                if val:
                    return str(val)
        except Exception:
            pass
        return "founder"

    def _retired_legacy_work_route(
        owner: str,
        operation: str,
        replacement: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "owner_user": owner,
            "universal": True,
            "code": "legacy_work_route_retired",
            "error": (
                "Legacy Work %s is retired. Use %s with an enrolled Universal "
                "Agent Session." % (operation, replacement)
            ),
            "replacement": replacement,
            "leaf": None,
        }

    @mcp.tool(
        name="brain.work_add",
        description=(
            "RETIRED compatibility route. It never writes active_work_v1; use "
            "brain.universal_work_create with an enrolled Universal Agent "
            "Session."
        ),
    )
    def brain_work_add(
        leaves: list[dict[str, Any]],
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "creation", "brain.universal_work_create"
        )

    @mcp.tool(
        name="brain.work_add_cell_first",
        description=(
            "RETIRED compatibility route. It never writes active_work_v1; use "
            "brain.universal_work_create with an enrolled Universal Agent "
            "Session."
        ),
    )
    def brain_work_add_cell_first(
        leaves: list[dict[str, Any]],
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "creation", "brain.universal_work_create"
        )

    @mcp.tool(
        name="brain.work_next",
        description=(
            "RETIRED compatibility route. It never claims active_work_v1; use "
            "brain.universal_work_next with an enrolled Universal Agent Session."
        ),
    )
    def brain_work_next(
        runtime: str,
        fit: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "claim", "brain.universal_work_next"
        )

    @mcp.tool(
        name="brain.work_next_cell_first",
        description=(
            "RETIRED compatibility route. It never claims active_work_v1; use "
            "brain.universal_work_next with an enrolled Universal Agent Session."
        ),
    )
    def brain_work_next_cell_first(
        runtime: str,
        fit: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "claim", "brain.universal_work_next"
        )

    @mcp.tool(
        name="brain.work_claim",
        description=(
            "RETIRED compatibility route. It never claims active_work_v1; use "
            "brain.universal_work_next or brain.universal_work_transition with "
            "an enrolled Universal Agent Session."
        ),
    )
    def brain_work_claim(
        leaf_id: str,
        agent_id: str,
        runtime: str = "",
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "claim", "brain.universal_work_transition"
        )

    @mcp.tool(
        name="brain.work_claim_cell_first",
        description=(
            "RETIRED compatibility route. It never claims active_work_v1; use "
            "brain.universal_work_next or brain.universal_work_transition with "
            "an enrolled Universal Agent Session."
        ),
    )
    def brain_work_claim_cell_first(
        leaf_id: str,
        agent_id: str,
        runtime: str = "",
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "claim", "brain.universal_work_transition"
        )

    @mcp.tool(
        name="brain.work_release",
        description=(
            "RETIRED compatibility route. It never releases active_work_v1; use "
            "brain.universal_work_transition with an enrolled Universal Agent "
            "Session."
        ),
    )
    def brain_work_release(
        leaf_id: str,
        done: bool,
        owner_user: Optional[str] = None,
        note: str = "",
        evidence_ref: Optional[str] = None,
        blocked: bool = False,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "release", "brain.universal_work_transition"
        )

    @mcp.tool(
        name="brain.work_release_cell_first",
        description=(
            "RETIRED compatibility route. It never releases active_work_v1; use "
            "brain.universal_work_transition with an enrolled Universal Agent "
            "Session."
        ),
    )
    def brain_work_release_cell_first(
        leaf_id: str,
        done: bool,
        owner_user: Optional[str] = None,
        note: str = "",
        evidence_ref: Optional[str] = None,
        blocked: bool = False,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "release", "brain.universal_work_transition"
        )

    @mcp.tool(
        name="brain.work_status",
        description=(
            "RETIRED compatibility route. It never reads active_work_v1 as "
            "authority; use brain.universal_work_status with an enrolled "
            "Universal Agent Session."
        ),
    )
    def brain_work_status(owner_user: Optional[str] = None) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "status read", "brain.universal_work_status"
        )

    @mcp.tool(
        name="brain.work_get",
        description=(
            "RETIRED compatibility route. It never exposes active_work_v1 as "
            "authority; use brain.universal_work_status with an enrolled "
            "Universal Agent Session."
        ),
    )
    def brain_work_get(owner_user: Optional[str] = None) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "work read", "brain.universal_work_status"
        )

    @mcp.tool(
        name="brain.work_leaf_get",
        description=(
            "RETIRED compatibility route. It never exposes active_work_v1 as "
            "authority; use brain.universal_work_status with an enrolled "
            "Universal Agent Session."
        ),
    )
    def brain_work_leaf_get(
        leaf_id: str = "",
        title: str = "",
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "work read", "brain.universal_work_status"
        )

    @mcp.tool(
        name="brain.work_court_run",
        description=(
            "RETIRED compatibility route. It never adjudicates active_work_v1; "
            "use brain.universal_work_court with an enrolled Universal Agent "
            "Session."
        ),
    )
    def brain_work_court_run(
        leaf_id: str,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "court adjudication", "brain.universal_work_court"
        )

    @mcp.tool(
        name="brain.work_court_run_cell_first",
        description=(
            "RETIRED compatibility route. It never adjudicates active_work_v1; "
            "use brain.universal_work_court with an enrolled Universal Agent "
            "Session."
        ),
    )
    def brain_work_court_run_cell_first(
        leaf_id: str,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        return _retired_legacy_work_route(
            owner, "court adjudication", "brain.universal_work_court"
        )

    def _cell_work_leaf(
        manager,
        *,
        runtime: str,
        session_id: str,
        work: dict[str, Any],
        workshop_root: str,
    ) -> dict[str, Any]:
        interfaces = work.get("interfaces") or {}
        resolved = work.get("resolved") or {}

        def scalar(name: str, default: Any = "") -> Any:
            interface = interfaces.get(name) or {}
            return interface.get("value", default)

        def structured(name: str, default: Any) -> Any:
            if isinstance(resolved, dict) and name in resolved:
                return resolved[name]
            interface = interfaces.get(name) or {}
            target = interface.get("target")
            if (
                not isinstance(target, str)
                or not target
                or ":data:" not in target
            ):
                return default
            return manager.value_read(
                runtime=runtime,
                external_session_id=session_id,
                root_id=target,
            )

        requirements = structured("requirements", {})
        requirements = requirements if isinstance(requirements, dict) else {}
        gate = requirements.get("gate")
        gate = gate if isinstance(gate, dict) else {}
        external_key = str(scalar("external-key") or work.get("root") or "")
        return {
            "leaf_id": external_key,
            "work_root": work.get("root"),
            "title": str(scalar("title")),
            "note": str(scalar("description")),
            "priority": int(str(scalar("priority", 0))),
            "state": "claimed",
            "runtime": runtime,
            "session_id": session_id,
            "claimed_by": work.get("claimant_session"),
            "gate_kind": str(gate.get("kind") or "manual"),
            "gate_spec": gate.get("spec") or {},
            "cde_container": structured("cde-container", {}),
            "fit": structured("required-capabilities", []),
            "governance_context": structured("applicable-policy", {}),
            "workshop_root": workshop_root,
        }

    def _cell_assigned_block(leaf: dict[str, Any]) -> str:
        gate_spec = leaf.get("gate_spec") or {}
        transition = (
            "session_id=%r, vendor=%r, work_root=%r" % (
                leaf.get("session_id", ""),
                leaf.get("runtime", ""),
                leaf.get("work_root", ""),
            )
        )
        lines = [
            "<assigned_leaf>",
            "The Universal Cell graph assigns this work to your exact Agent Session.",
            f"  work_root: {leaf.get('work_root', '')}",
            f"  work:      {leaf.get('title', '')}",
            f"  gate:      {leaf.get('gate_kind', 'manual')}"
            + (
                "  " + json.dumps(gate_spec, separators=(",", ":"))
                if gate_spec else ""
            ),
            f"  workshop:  {leaf.get('workshop_root', '')}",
            "  release:   brain.universal_work_transition(%s, event='release')" % transition,
            "  blocked:   brain.universal_work_transition(%s, event='block', evidence=<reason>)" % transition,
            "  submit:    brain.universal_work_transition(%s, event='submit', evidence=<artifact proof>)" % transition,
            "  court:     brain.universal_work_court(%s)" % transition,
            "</assigned_leaf>",
        ]
        return "\n".join(lines)

    def _cell_first_assignment_error_block(error: str) -> str:
        lines = [
            '<governance_setup_leaf status="blocked">',
            "Decision: refuse old-client assigned work before claim.",
            "Reason: Cell-first assignment record could not be created.",
            f"Error: {error}",
            "Action: connect the Universal Cell runtime or call "
            "brain.work_assigned_block with a Universal Agent Session.",
            "</governance_setup_leaf>",
        ]
        return "\n".join(lines)

    @mcp.tool(
        name="brain.work_assigned_block",
        description=(
            "GRAPH-SESSION DRIVER (pre-prompt): requires a Universal Agent "
            "Session and claims only through the Cell-native work manager. "
            "Legacy import is a separate one-way migration adapter, never a "
            "step in an assignment. A missing session is denied before any "
            "work can change. Returns {ok, block, "
            "leaf} where block=\"\" when the graph frontier is dry."
        ),
    )
    def brain_work_assigned_block(
        runtime: str,
        session_id: Optional[str] = None,
        fit: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
        agent_id: Optional[str] = None,
        wrap: bool = True,
        write: bool = True,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        session_identity = str(session_id or "").strip()
        if not session_identity:
            _clear_active_cde_state(runtime=runtime, session_id="")
            return {
                "ok": False,
                "owner_user": owner,
                "blocked": True,
                "universal": True,
                "code": "universal_session_required",
                "error": (
                    "A Universal Agent Session is required before work can be "
                    "claimed."
                ),
                "block": "",
                "leaf": None,
            }
        if session_identity:
            try:
                manager = getattr(
                    mcp, "_universal_runtime_session_manager", None
                )
                if manager is None:
                    raise RuntimeError(
                        "Universal runtime session manager is unavailable"
                    )
                enrollment = manager.enroll(
                    runtime=runtime,
                    external_session_id=session_identity,
                )
                assignment = manager.claim_next(
                    runtime=runtime,
                    external_session_id=session_identity,
                )
                work = assignment.get("work")
                if not assignment.get("claimed") or not isinstance(work, dict):
                    return {
                        "ok": True,
                        "owner_user": owner,
                        "blocked": False,
                        "block": "",
                        "leaf": None,
                        "universal": True,
                        "agent_session": enrollment["agent_session"],
                        "status": assignment.get("status"),
                    }
                leaf = _cell_work_leaf(
                    manager,
                    runtime=runtime,
                    session_id=session_identity,
                    work=work,
                    workshop_root=str(assignment.get("workshop") or ""),
                )
                _write_active_cde_state(
                    leaf,
                    runtime=runtime,
                    session_id=session_identity,
                )
                block = _cell_assigned_block(leaf)
                if wrap:
                    from . import client_hook as ch
                    block = ch._wrap(block)
                return {
                    "ok": True,
                    "owner_user": owner,
                    "blocked": False,
                    "block": block,
                    "leaf": leaf,
                    "universal": True,
                    "agent_session": enrollment["agent_session"],
                    "status": assignment.get("status"),
                }
            except Exception as ex:
                return {
                    "ok": False,
                    "owner_user": owner,
                    "blocked": True,
                    "universal": True,
                    "code": "universal_work_unavailable",
                    "error": f"{type(ex).__name__}: {ex}",
                    "block": "",
                    "leaf": None,
                }
    return mcp
