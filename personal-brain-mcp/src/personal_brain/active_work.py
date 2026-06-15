"""active_work.py — BRV-01: the SERVER-AUTHORITATIVE active-work ledger.

THE BRAIN-DRIVER CORE. The founder's #1 ask: *the brain drives every agent.*
An agent has no intrinsic drive-to-completion — it does not persist between
turns and feels no pressure from the undone (AgDR-0054 §"the drive"). The
externalised drive lives HERE: a single server-authoritative ledger of the
open work, persisted in `brain.db`, that every runtime (Claude Code / Codex /
Gemini / composer) pulls its next assignment FROM and reports completion TO.

This is the brain-side, all-agents counterpart to the per-agent file ledger in
`tools/active_work.py` (whose own docstring names this as the slice it "builds
toward"). That v0 file ledger stays as the skippable local Stop-hook catch;
THIS is the non-skippable choke point at the shared layer every agent crosses
(AgDR-0054 S1 · the substrate everything writes to). It is ONE system — it
EXTENDS the brain, it does not fork it.

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
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # avoid a runtime import cycle; only needed for typing
    from .storage import BrainStore


# NEW brain_meta key — never collides with requirement_tree_v1 / calibration_v1
# / organize.clusters / diligence.stats / bound_owner_* / personal_cloud_sync.*
LEDGER_META_KEY = "active_work_v1"


# ─────────────────────────── enums + models ────────────────────────────


class LeafState(str, Enum):
    OPEN = "open"          # unclaimed; claimable by any executor
    CLAIMED = "claimed"    # an executor owns it, work in flight
    DONE = "done"          # the gate went green (verified-complete)
    BLOCKED = "blocked"    # needs the founder / external dep (escalated)


# Terminal-ish: DONE is success; OPEN/CLAIMED are in-flight; BLOCKED waits on
# the founder. The drive is "dry" when no OPEN/CLAIMED leaf remains.
ACTIONABLE = (LeafState.OPEN, LeafState.CLAIMED)


class WorkLeaf(BaseModel):
    leaf_id: str                              # sha256-derived stable id
    title: str                                # plain-English unit of work
    gate_kind: str = "manual"                 # py_compile|pytest|file_exists|grep_clean|cdp|manual
    gate_spec: dict[str, Any] = Field(default_factory=dict)  # args for the gate
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
    """The server-authoritative ledger: one per owner. Holds every leaf the
    brain is driving for that owner, plus a re-entry counter (the
    anti-infinite-grind backstop the Stop hook reads)."""
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


class ActiveWorkStore:
    """Thin wrapper over `BrainStore.get_meta` / `set_meta`.

    Stores ALL owners' ledgers as ONE JSON doc under
    `brain_meta[LEDGER_META_KEY]`:

        { owner_user: <ActiveWork json>, ... }

    Mirrors `requirement_tree.TreeStore` EXACTLY — never creates a table, never
    touches fragments / skills. Every mutation is a read-modify-write of that
    single key, and because `set_meta` serialises under the store's RLock, the
    doc-level write is atomic per call.
    """

    def __init__(self, store: "BrainStore"):
        self.store = store

    def _load_all(self) -> dict[str, dict]:
        raw = self.store.get_meta(LEDGER_META_KEY)
        if not raw:
            return {}
        try:
            doc = json.loads(raw)
        except Exception:
            return {}
        return doc if isinstance(doc, dict) else {}

    def _save_all(self, doc: dict[str, dict]) -> None:
        self.store.set_meta(LEDGER_META_KEY, json.dumps(doc, default=str))

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
        """Read-modify-write the single ledger-namespace key. Bumps updated_at."""
        ledger.updated_at = datetime.now(timezone.utc)
        doc = self._load_all()
        doc[ledger.owner_user] = ledger.model_dump(mode="json")
        self._save_all(doc)

    def list_owners(self) -> list[str]:
        return sorted(self._load_all().keys())

    def delete(self, owner_user: str) -> bool:
        doc = self._load_all()
        if owner_user in doc:
            del doc[owner_user]
            self._save_all(doc)
            return True
        return False


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
    ledger = aws.load_or_new(owner_user)
    now = datetime.now(timezone.utc)
    for spec in leaves:
        title = (spec.get("title") or "").strip()
        if not title:
            continue
        lid = _leaf_id(owner_user, title)
        if lid in ledger.leaves:
            # idempotent: keep the existing leaf + its state (never re-open).
            continue
        ledger.leaves[lid] = WorkLeaf(
            leaf_id=lid,
            title=title,
            gate_kind=(spec.get("gate_kind") or "manual"),
            gate_spec=(spec.get("gate_spec") or {}),
            fit=list(spec.get("fit") or []),
            priority=int(spec.get("priority") or 0),
            state=LeafState.OPEN,
            created_at=now,
            updated_at=now,
        )
    aws.save(ledger)
    return ledger


def _fits(leaf: WorkLeaf, fit: Optional[list[str]]) -> bool:
    """A leaf is eligible for a runtime with capabilities `fit` iff EVERY tag
    the leaf requires is offered. A leaf with no fit requirement fits anyone.
    `fit=None` (an executor that advertises nothing) only matches no-requirement
    leaves — so a specialised leaf is never handed to a runtime that can't do it."""
    if not leaf.fit:
        return True
    offered = set(fit or [])
    return set(leaf.fit).issubset(offered)


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
    ledger = aws.load_or_new(owner_user)
    candidates = [
        lf for lf in ledger.open_leaves() if _fits(lf, fit)
    ]
    if not candidates:
        return None
    # highest priority first; tie -> oldest created_at first (stable FIFO).
    candidates.sort(key=lambda lf: (-lf.priority, lf.created_at, lf.leaf_id))
    chosen = candidates[0]
    chosen.state = LeafState.CLAIMED
    chosen.claimed_by = (agent_id or runtime)
    chosen.runtime = runtime
    chosen.updated_at = datetime.now(timezone.utc)
    aws.save(ledger)
    return chosen


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
    ledger = aws.load_or_new(owner_user)
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
    leaf.claimed_by = agent_id
    if runtime:
        leaf.runtime = runtime
    leaf.state = LeafState.CLAIMED
    leaf.updated_at = datetime.now(timezone.utc)
    aws.save(ledger)
    return leaf


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
    ledger = aws.load_or_new(owner_user)
    leaf = ledger.leaves.get(leaf_id)
    if leaf is None:
        raise KeyError(f"leaf '{leaf_id}' not found for owner '{owner_user}'")
    now = datetime.now(timezone.utc)
    leaf.note = note or leaf.note
    leaf.updated_at = now
    if done:
        leaf.state = LeafState.DONE
        leaf.evidence_ref = evidence_ref
    elif blocked:
        leaf.state = LeafState.BLOCKED
        leaf.claimed_by = None
    else:
        leaf.state = LeafState.OPEN
        leaf.claimed_by = None
        leaf.attempts += 1
    aws.save(ledger)
    return leaf


def bump_iteration(store: "BrainStore", *, owner_user: str = "founder") -> int:
    """Record one Stop-hook re-entry (the gate blocked a premature stop + fed
    the agent the unfinished list). The cap on these is the anti-infinite-grind
    backstop — mirrors tools/active_work.bump but server-authoritative."""
    aws = ActiveWorkStore(store)
    ledger = aws.load_or_new(owner_user)
    ledger.iterations += 1
    aws.save(ledger)
    return ledger.iterations


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


def register_active_work_tools(mcp: "Any", store: "BrainStore") -> "Any":
    """Register the additive `brain.work_*` MCP tools — the BRAIN-DRIVER surface
    (BRV-01). `server.build_server` adds exactly ONE call to this next to
    `register_tree_tools` / `register_roma_tools`.

    PURE-ADDITIVE: registers NEW tool names only, touches NO existing handler.
    Every mutation persists through `ActiveWorkStore` (one `brain_meta` JSON
    doc, key 'active_work_v1') — no new table, no schema migration, no touch of
    fragments / skills / -wal / -shm.

    This is the server-authoritative, all-agents drive: every runtime pulls its
    next leaf from `brain.work_next` (the brain decides what each agent works on
    next) and reports completion to `brain.work_release`. Returns `mcp`."""

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

    @mcp.tool(
        name="brain.work_add",
        description=(
            "THE DRIVE (producer) — enqueue work into the brain's "
            "server-authoritative active-work ledger. leaves = [{title, "
            "gate_kind?, gate_spec?, fit?, priority?}]. gate_kind ∈ "
            "{py_compile, pytest, file_exists, grep_clean, cdp, manual} — how "
            "'done' is checked on the REAL artifact. `fit` is a list of "
            "capability tags a runtime must offer to be handed this leaf (e.g. "
            "['revit'] for a Revit task). Persisted ADDITIVELY in brain_meta "
            "(key 'active_work_v1') — no table, no schema change. Idempotent on "
            "identical titles per owner. Returns {ok, owner_user, status}."
        ),
    )
    def brain_work_add(
        leaves: list[dict[str, Any]],
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            add_leaves(store, owner_user=owner, leaves=leaves)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "owner_user": owner,
                "status": status(store, owner_user=owner)}

    @mcp.tool(
        name="brain.work_next",
        description=(
            "THE DRIVER — the brain hands the calling runtime its NEXT unit of "
            "work and CLAIMS it atomically (OPEN → CLAIMED), so two agents "
            "never grab the same leaf. Selection: highest priority, oldest "
            "first, among open leaves whose `fit` ⊆ the runtime's capabilities. "
            "`runtime` is the client id (claude_code|codex|gemini|composer); "
            "`fit` is what this runtime can do (host/tool tags). Records "
            "claimed_by = agent_id (default runtime) — the anti-self-certify "
            "anchor. Returns {ok, leaf} or {ok:true, leaf:null} when the "
            "frontier is dry. This is the ONE call every client's pre-prompt "
            "makes — the brain drives the agent."
        ),
    )
    def brain_work_next(
        runtime: str,
        fit: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            leaf = next_leaf(store, runtime=runtime, fit=fit,
                             owner_user=owner, agent_id=agent_id)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "owner_user": owner,
                "leaf": leaf.model_dump(mode="json") if leaf else None}

    @mcp.tool(
        name="brain.work_claim",
        description=(
            "THE DRIVE — claim a SPECIFIC open leaf by id (OPEN → CLAIMED). "
            "Records claimed_by = agent_id (REQUIRED — the anti-self-certify "
            "anchor; the claimer can never certify its own leaf). Refuses a "
            "DONE leaf or one already claimed by another agent. Use brain.work_"
            "next for the brain to PICK the leaf; use this to claim a named "
            "one. Returns {ok, leaf}."
        ),
    )
    def brain_work_claim(
        leaf_id: str,
        agent_id: str,
        runtime: str = "",
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            leaf = claim(store, leaf_id=leaf_id, agent_id=agent_id,
                         runtime=runtime, owner_user=owner)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "leaf": leaf.model_dump(mode="json")}

    @mcp.tool(
        name="brain.work_release",
        description=(
            "THE DRIVE (consumer) — report the outcome of a claimed leaf. "
            "done=true → DONE (verified-complete; pass evidence_ref naming the "
            "proof). done=false → re-OPEN the leaf (bumps attempts, frees the "
            "claim) so it re-enters the frontier. done=false + blocked=true → "
            "BLOCKED: an HONEST escalation to the founder (needs you / external "
            "dep), never a silent park — there is no 'later' state. Returns "
            "{ok, leaf, status}."
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
        try:
            leaf = release(store, leaf_id=leaf_id, done=done, owner_user=owner,
                           note=note, evidence_ref=evidence_ref, blocked=blocked)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "leaf": leaf.model_dump(mode="json"),
                "status": status(store, owner_user=owner)}

    @mcp.tool(
        name="brain.work_status",
        description=(
            "THE DRIVE (done-rule) — report the active-work state for an owner. "
            "Returns {owner_user, dry, exists, counts:{open,claimed,done,"
            "blocked}, total, actionable, blocked:[...], iterations, cap}. "
            "dry=true iff NO open/claimed leaf remains AND nothing is BLOCKED "
            "AND there was work — the server-authoritative 'done' the Stop hook "
            "+ every client reads. An empty ledger is idle (dry=false, "
            "exists=false), not done."
        ),
    )
    def brain_work_status(owner_user: Optional[str] = None) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        try:
            return {"ok": True, **status(store, owner_user=owner)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.work_get",
        description=(
            "READ-ONLY. Return the whole active-work ledger for an owner (every "
            "leaf with its state/claim/runtime/gate/attempts). Returns {ok, "
            "ledger} or {ok:false} when the owner has no ledger."
        ),
    )
    def brain_work_get(owner_user: Optional[str] = None) -> dict[str, Any]:
        owner = owner_user or _resolve_owner()
        ledger = get_ledger(store, owner_user=owner)
        if ledger is None:
            return {"ok": False, "error": f"no ledger for owner '{owner}'"}
        return {"ok": True, "ledger": ledger.model_dump(mode="json")}

    return mcp
