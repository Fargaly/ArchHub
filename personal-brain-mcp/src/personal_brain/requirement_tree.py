"""ROMA requirement-tree ledger — the store-backed spine of the
"method-that-finishes-everything" (ROMA: Recursive Open Meta-Agent).

Per `01.ECHO/METHOD_finish_everything.html` + the founder:

    vision = ROOT of a requirement TREE
    SPLIT (never simplify) until each LEAF = one machine-checkable predicate
    parallel executors CLAIM leaves; NONE self-certify
    an external COURT must FAIL-TO-REFUTE a leaf on the REAL artifact before
        it goes GREEN
    loop-until-dry RE-DECOMPOSE on RED
    done = full GREEN sweep
    YOU (founder) = ROOT for taste / ties

This module owns ONLY the tree state + transitions. The COURT lives in
`court_harness.py`; the orchestration loop lives in `roma.py`. The split keeps
each piece pure + unit-testable in the same spirit as `diligence.py`
(pure policy) vs `tools/anti_laziness_gate.py` (the I/O shell).

────────────────────────────────────────────────────────────────────────────
SAFETY (load-bearing — see CLAUDE.md ONE-SYSTEM-PLAN / LIBRARY-FIRST):
────────────────────────────────────────────────────────────────────────────
  * ADDITIVE ONLY. No new SQLite table, no schema migration. Every tree is
    persisted under ONE `brain_meta` key (`requirement_tree_v1`) as a JSON doc
    keyed by tree_id. `BrainStore.set_meta` is an
    `INSERT … ON CONFLICT(key) DO UPDATE` (storage.py:1054) guarded by the
    store's RLock — so the whole tree namespace is a single row and never
    touches `fragments` / `skills` / `-wal` / `-shm`.
  * Pure-Python + Pydantic, mirroring `models.py` style. Defined LOCALLY here
    (not appended to models.py) so the stable MCP contract in models.py is
    untouched.
  * Datetimes serialise via `default=str`; `RequirementTree.model_validate`
    re-parses ISO strings back to datetimes on load.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

# ONE definition of identity normalization + the root-token check — shared with
# the court's independence lens (court_harness has no import back into this
# module, so no cycle). See the 2026-07-02 forensic-audit fixes.
from .court_harness import ROOT_TOKEN_ENV, normalize_agent, root_token_ok

if TYPE_CHECKING:  # avoid a runtime import cycle; only needed for typing
    from .storage import BrainStore


# NEW brain_meta key — never collides with calibration_v1 / organize.clusters /
# diligence.stats / bound_owner_* / personal_cloud_sync.* etc.
TREE_META_KEY = "requirement_tree_v1"

# Append-only audit ledger for founder/root overrides (defect 3): every
# is_root_authority verdict lands here — a root override that leaves no trace
# is indistinguishable from a forged one.
ROOT_OVERRIDE_LOG_KEY = "root_override_log_v1"

_log = logging.getLogger("personal_brain.requirement_tree")


# ─────────────────────────── enums + models ────────────────────────────


class NodeState(str, Enum):
    OPEN = "open"            # not yet claimed
    CLAIMED = "claimed"      # an executor owns it, work in flight
    GREEN = "green"          # court FAILED TO REFUTE on the real artifact
    RED = "red"              # court refuted → must re-decompose / re-work
    NEEDS_ROOT = "needs_root"  # decomposition floor / tie → founder (YOU)


# Terminal-ish states a node can settle into. GREEN is success; the rest are
# either in-flight (OPEN/CLAIMED) or need action (RED/NEEDS_ROOT).
GREEN = NodeState.GREEN


class ReqNode(BaseModel):
    node_id: str                              # sha256-derived stable id
    parent: Optional[str] = None              # None == ROOT (the vision)
    title: str                                # plain-English requirement
    predicate: str = ""                       # machine-checkable assertion (leaf)
    state: NodeState = NodeState.OPEN
    verdict: Optional[str] = None             # "green" | "red" | None
    evidence_ref: Optional[str] = None        # pointer to court evidence
    children: list[str] = Field(default_factory=list)  # child node_ids
    claimed_by: Optional[str] = None          # executor agent id (anti-self-cert)
    # CLAIM HISTORY (audit defect 2): every agent that EVER claimed this leaf.
    # A red verdict clears claimed_by (the leaf re-enters the frontier) but the
    # claimer is recorded here so it can never come back as the "independent"
    # judge that greens its own past work (boomerang self-certification).
    past_claimants: list[str] = Field(default_factory=list)
    gate_kind: str = "manual"                 # py_compile|pytest|cdp|anti_laziness|manual
    gate_spec: dict[str, Any] = Field(default_factory=dict)  # args for the gate
    # Who delivered the latest verdict — MUST differ from claimed_by (the
    # executor never judges its own leaf). Recorded for the audit ledger.
    judged_by: Optional[str] = None
    attempts: int = 0                         # red→re-work cycles seen
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_leaf(self) -> bool:
        """A node is a LEAF iff it has no children. predicate / gate_kind /
        gate_spec are only meaningful on leaves; an internal node's greenness
        is DERIVED (green iff every child is green)."""
        return not self.children


class RequirementTree(BaseModel):
    tree_id: str
    root_id: str
    nodes: dict[str, ReqNode] = Field(default_factory=dict)   # node_id -> ReqNode
    owner_user: str = "founder"
    title: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── derived helpers ────────────────────────────────────────────────
    def leaves(self) -> list[ReqNode]:
        return [n for n in self.nodes.values() if n.is_leaf]

    def children_of(self, node_id: str) -> list[ReqNode]:
        node = self.nodes.get(node_id)
        if node is None:
            return []
        return [self.nodes[c] for c in node.children if c in self.nodes]

    def dangling_child_refs(self) -> list[tuple[str, str]]:
        """``(parent_id, missing_child_id)`` for every child id declared in
        some node's ``children`` but ABSENT from ``nodes``. A non-empty result
        means the tree is structurally incomplete (a corrupted / partially
        written persisted doc) and MUST NOT be reported as a full green sweep —
        the fail-closed integrity guard read by ``_propagate_green`` + ``sweep``."""
        out: list[tuple[str, str]] = []
        for n in self.nodes.values():
            for c in n.children:
                if c not in self.nodes:
                    out.append((n.node_id, c))
        return out


# ─────────────────────────── persistence ───────────────────────────────


def _parse_doc(raw: Optional[str]) -> dict[str, dict]:
    """Parse the tree-namespace blob into the tree_id→tree dict. An empty blob
    (None / "") OR an unparseable / non-object blob → ``{}`` (a fresh empty
    namespace). Tree integrity is enforced fail-closed downstream by
    ``dangling_child_refs`` / ``sweep`` (a corrupted tree can never read as a
    full green sweep), so the loader stays lenient here — matching the prior
    ``_load_all`` behaviour exactly."""
    if not raw:
        return {}
    try:
        doc = json.loads(raw)
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


class TreeStore:
    """Thin wrapper over `BrainStore.update_meta` (atomic) / `get_meta` (read).

    Stores ALL trees as ONE JSON doc under `brain_meta[TREE_META_KEY]`:

        { tree_id: <RequirementTree json>, ... }

    Never creates a table, never touches fragments / skills. Mirrors
    `active_work.ActiveWorkStore` EXACTLY — it is ONE system, not a fork.

    ATOMIC mutation (the court-demanded fix). Every read-decide-write goes
    through ONE ``BrainStore.update_meta`` call, whose critical section is
    serialised on TWO levels: the store's RLock (across THREADS in one process)
    AND a ``BEGIN IMMEDIATE`` RESERVED-lock transaction (across CONNECTIONS /
    PROCESSES — see storage.update_meta). The decide step (e.g. "is this leaf
    still OPEN?") runs INSIDE both, so two racing claims — whether two threads OR
    two separate daemon/hook processes on the same brain.db — can never both read
    OPEN and both claim (no cross-process TOCTOU double-claim, no lost update).
    The earlier ``get_meta`` → decide → ``set_meta`` shape took TWO separate
    locks, leaving exactly that window open (the court reproduced 8/8 forced).
    """

    def __init__(self, store: "BrainStore"):
        self.store = store

    def _load_all(self) -> dict[str, dict]:
        raw = self.store.get_meta(TREE_META_KEY)
        return _parse_doc(raw)

    # ── atomic mutation (single critical section) ───────────────────────
    def _mutate(self, fn: "Any") -> "Any":
        """Run ``fn(doc) -> result`` as ONE atomic read-modify-write.

        ``fn`` receives the live tree_id→tree dict and MUTATES IT IN PLACE; its
        return value is handed back to the caller. The whole load→fn→persist
        runs inside ``BrainStore.update_meta``'s BEGIN IMMEDIATE critical
        section, so the decision ``fn`` makes cannot be invalidated by a
        concurrent writer (another thread OR another process) between read and
        write. Mirrors ``active_work.ActiveWorkStore._mutate``."""
        box: dict[str, Any] = {}

        def _apply(old_raw: Optional[str]):
            doc = _parse_doc(old_raw)
            box["result"] = fn(doc)
            new_raw = json.dumps(doc, default=str)
            return new_raw, new_raw

        self.store.update_meta(TREE_META_KEY, _apply)
        return box.get("result")

    def load(self, tree_id: str) -> Optional[RequirementTree]:
        doc = self._load_all()
        raw = doc.get(tree_id)
        if raw is None:
            return None
        try:
            # raw is a dict (already json-decoded) — model_validate re-parses
            # ISO datetime strings + enum values.
            return RequirementTree.model_validate(raw)
        except Exception:
            return None

    def save(self, tree: RequirementTree) -> None:
        """Persist a tree atomically (single critical section). Bumps
        updated_at. Prefer ``mutate_tree`` for read-modify-write — this
        last-writer-wins setter is for callers that built the tree fresh
        (e.g. create_root)."""
        tree.updated_at = datetime.now(timezone.utc)

        def _fn(doc: dict[str, dict]):
            doc[tree.tree_id] = tree.model_dump(mode="json")
            return tree

        self._mutate(_fn)

    def mutate_tree(self, tree_id: str, fn: "Any") -> "Any":
        """THE atomic read-modify-write over a SINGLE tree.

        Loads the tree (raising KeyError if absent), calls ``fn(tree) ->
        result``, persists the mutated tree, and returns ``result`` — all inside
        ONE critical section. This is the choke point decompose / claim_leaf /
        set_verdict route through so their decide-then-write is never split by a
        concurrent writer (the cross-process CAS). Mirrors
        ``active_work.ActiveWorkStore.mutate_owner``."""

        def _fn(doc: dict[str, dict]):
            raw = doc.get(tree_id)
            if raw is None:
                raise KeyError(f"tree '{tree_id}' not found")
            tree = RequirementTree.model_validate(raw)
            result = fn(tree)
            tree.updated_at = datetime.now(timezone.utc)
            doc[tree_id] = tree.model_dump(mode="json")
            return result

        return self._mutate(_fn)

    def list_trees(self) -> list[str]:
        return sorted(self._load_all().keys())

    def delete(self, tree_id: str) -> bool:
        def _fn(doc: dict[str, dict]):
            if tree_id in doc:
                del doc[tree_id]
                return True
            return False

        return self._mutate(_fn)


# ─────────────────────────── id helper ─────────────────────────────────


def _node_id(tree_id: str, parent: Optional[str], title: str) -> str:
    """sha256(tree_id|parent|title)[:16] — stable, content-derived. Mirrors
    `server._hash_id` style (sha256 of canonical parts). Stable across
    re-decompose so a RED node that is split again with the SAME child titles
    reuses ids (idempotent re-decomposition)."""
    h = hashlib.sha256()
    for part in (tree_id, parent or "", title):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


def _tree_id_for(title: str, owner_user: str) -> str:
    return "rt-" + hashlib.sha256(
        f"{title}|{owner_user}".encode("utf-8")
    ).hexdigest()[:16]


# ─────────────────────────── API (the encode contract) ─────────────────


def create_root(
    store: "BrainStore",
    *,
    title: str,
    owner_user: str = "founder",
    tree_id: Optional[str] = None,
    predicate: str = "",
    gate_kind: str = "manual",
    gate_spec: Optional[dict[str, Any]] = None,
) -> RequirementTree:
    """The vision becomes the ROOT node (state=open). Persists + returns the
    tree. If a tree with the derived id already exists it is returned as-is
    (idempotent create)."""
    tid = tree_id or _tree_id_for(title, owner_user)
    ts = TreeStore(store)
    existing = ts.load(tid)
    if existing is not None:
        return existing

    rid = _node_id(tid, None, title)
    root = ReqNode(
        node_id=rid,
        parent=None,
        title=title,
        predicate=predicate,
        gate_kind=gate_kind,
        gate_spec=gate_spec or {},
        state=NodeState.OPEN,
    )
    tree = RequirementTree(
        tree_id=tid,
        root_id=rid,
        nodes={rid: root},
        owner_user=owner_user,
        title=title,
    )
    ts.save(tree)
    return tree


def decompose(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    children: list[dict],
) -> RequirementTree:
    """SPLIT (never simplify).

    `children` = [{title, predicate?, gate_kind?, gate_spec?}, ...]. Appends
    child nodes, links them under `node_id`, and — because the parent now has
    children — the parent stops being a leaf (its greenness becomes DERIVED).

    Idempotent on identical child titles: re-decomposing a RED node with the
    same titles reuses the deterministic child ids (no duplicate siblings).
    A child id that already exists keeps its current state (so a green child
    survives a parent re-split). Refuses to decompose a node already GREEN
    (a verified-complete node is not re-opened by fiat).
    """
    if not children:
        raise ValueError("decompose requires at least one child (SPLIT, never simplify)")
    ts = TreeStore(store)

    def _fn(tree: RequirementTree) -> RequirementTree:
        parent = tree.nodes.get(node_id)
        if parent is None:
            raise KeyError(f"node '{node_id}' not found in tree '{tree_id}'")
        if parent.state == NodeState.GREEN:
            raise ValueError(
                f"refusing to decompose GREEN node '{node_id}' — verified-complete "
                f"nodes are not re-opened (supersede via a new root instead)"
            )

        # NO COSMETIC CLONES (audit defect 6, "boosting"): decompose-on-red must
        # CHANGE the check. A child that repeats the RED parent's gate_kind AND
        # gate_spec verbatim is a re-skin, not a split — the same gate would be
        # retried under a new title forever.
        if parent.state == NodeState.RED:
            for spec in children:
                if not (spec.get("title") or "").strip():
                    continue
                ck = spec.get("gate_kind") or "manual"
                cs = spec.get("gate_spec") or {}
                if ck == parent.gate_kind and cs == (parent.gate_spec or {}):
                    raise ValueError(
                        f"cosmetic clone refused: child '{spec.get('title')}' of RED "
                        f"node '{node_id}' repeats the parent's gate verbatim "
                        f"(gate_kind='{ck}' + identical gate_spec). Decompose-on-red "
                        f"must differ in gate_kind OR gate_spec — split, never re-skin."
                    )

        now = datetime.now(timezone.utc)
        for spec in children:
            title = (spec.get("title") or "").strip()
            if not title:
                continue
            cid = _node_id(tree_id, node_id, title)
            if cid in tree.nodes:
                # idempotent re-decompose: keep the existing child (+ its state),
                # just ensure it's linked under this parent.
                if cid not in parent.children:
                    parent.children.append(cid)
                continue
            child = ReqNode(
                node_id=cid,
                parent=node_id,
                title=title,
                predicate=(spec.get("predicate") or ""),
                gate_kind=(spec.get("gate_kind") or "manual"),
                gate_spec=(spec.get("gate_spec") or {}),
                state=NodeState.OPEN,
                created_at=now,
                updated_at=now,
            )
            tree.nodes[cid] = child
            if cid not in parent.children:
                parent.children.append(cid)

        # The parent is now internal: clear any leaf-only verdict/claim it carried
        # and let its state be derived. If it was RED/NEEDS_ROOT (the usual reason
        # to decompose), it reopens as an internal node pending its children.
        parent.claimed_by = None
        parent.verdict = None
        parent.evidence_ref = None
        parent.state = NodeState.OPEN
        parent.updated_at = now
        return tree

    # Atomic read-modify-write: the whole split is one critical section (a
    # concurrent decompose/claim never clobbers nodes this call added).
    return ts.mutate_tree(tree_id, _fn)


def claim_leaf(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    agent_id: str,
) -> ReqNode:
    """An executor claims an OPEN/RED leaf → CLAIMED, recording claimed_by=agent_id.

    A REAL cross-process CAS: the "is this leaf still claimable?" check and the
    claim write run inside ONE ``BEGIN IMMEDIATE`` critical section (via
    ``TreeStore.mutate_tree``), so exactly ONE caller wins a contested leaf —
    whether the contenders are two threads OR two separate processes on the same
    brain.db. The earlier shape did ``load`` (one lock) then ``save`` (another
    lock), so two processes could BOTH read the leaf as OPEN and BOTH write the
    claim (the court reproduced 8/8 forced). Now the second claimant sees
    ``state == CLAIMED`` inside the lock and gets the typed already-claimed
    refusal.

    `agent_id` is REQUIRED and is the anti-self-certify anchor: `set_verdict`
    later REFUSES if the judge == claimed_by (the executor never judges its own
    leaf). Refuses a non-leaf, an already-GREEN leaf, or one already claimed by
    a DIFFERENT agent (re-claim by the same agent is idempotent)."""
    if not (agent_id or "").strip():
        raise ValueError("claim_leaf requires a non-empty agent_id (anti-self-certify anchor)")
    ts = TreeStore(store)

    def _fn(tree: RequirementTree) -> ReqNode:
        # check-then-set under ONE lock (the cross-process CAS). The guards and
        # the claim write can't be split by a concurrent claimer in another
        # thread OR another process.
        node = tree.nodes.get(node_id)
        if node is None:
            raise KeyError(f"node '{node_id}' not found in tree '{tree_id}'")
        if not node.is_leaf:
            raise ValueError(f"cannot claim non-leaf '{node_id}' — only leaves are executable")
        if node.state == NodeState.GREEN:
            raise ValueError(f"leaf '{node_id}' is already GREEN — nothing to claim")
        # Identity comparison is NORMALIZED (strip+casefold): 'Exec-1' re-claiming
        # as 'exec-1' is the same actor (idempotent), and a different actor can't
        # sneak past the guard with a case-flip.
        if node.claimed_by and normalize_agent(node.claimed_by) != normalize_agent(agent_id):
            raise ValueError(
                f"leaf '{node_id}' already claimed by '{node.claimed_by}' "
                f"(requested by '{agent_id}')"
            )
        node.claimed_by = agent_id
        # Permanent claim history — survives the red round-trip that clears
        # claimed_by, so a past claimant can never re-enter as the judge.
        if normalize_agent(agent_id) not in {normalize_agent(p) for p in node.past_claimants}:
            node.past_claimants.append(agent_id)
        node.state = NodeState.CLAIMED
        node.updated_at = datetime.now(timezone.utc)
        return node

    return ts.mutate_tree(tree_id, _fn)


def _append_root_override_log(store: "BrainStore", entry: dict[str, Any]) -> None:
    """Append one root-override audit entry (atomic read-modify-write on the
    dedicated brain_meta key) AND emit it on the real logging tree. Defect 3:
    the old docstring claimed 'it is logged' while NO logging existed."""
    _log.warning("ROOT OVERRIDE (is_root_authority): %s", entry)

    def _apply(old_raw: Optional[str]):
        try:
            log = json.loads(old_raw) if old_raw else []
        except Exception:
            log = []
        if not isinstance(log, list):
            log = []
        log.append(entry)
        raw = json.dumps(log, default=str)
        return raw, raw

    store.update_meta(ROOT_OVERRIDE_LOG_KEY, _apply)


def set_verdict(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    verdict: str,
    judged_by: str,
    evidence_ref: Optional[str] = None,
    is_root_authority: bool = False,
    root_token: Optional[str] = None,
) -> ReqNode:
    """Record the COURT's verdict on a leaf, then propagate derived greenness up.

    `verdict` ∈ {"green", "red", "needs_root"}.
    `judged_by` is the court/jury identity, compared NORMALIZED (strip +
    casefold — 'Exec-1' IS 'exec-1'). ANTI-SELF-CERTIFY, all fail-closed:

      * a "green" on a LEAF that was never claimed → PermissionError (a verdict
        needs a claimed executor to judge against);
      * a "green" where judged_by == the current claimer → PermissionError;
      * a "green" where judged_by is ANY PAST claimant of this leaf →
        PermissionError (a red round-trip clears the claim but NOT the history
        — the original claimer can't boomerang back as the judge).

    ROOT OVERRIDE (the founder settling a tie) is AUTHENTICATED: it requires
    env ARCHHUB_ROOT_TOKEN to be set AND a matching `root_token` argument;
    mismatch/absent → PermissionError. Every root override is REALLY logged —
    a logging.warning plus an append into brain_meta['root_override_log_v1']
    (timestamp / tree / node / judged_by / verdict).

    GREEN flips internal ancestors GREEN when ALL their children are green
    (the loop-until-dry "full green sweep" is derived, never asserted by hand).
    RED bumps `attempts`, records the claimer into `past_claimants`, and clears
    the claim so the leaf re-enters the frontier for re-work / re-decompose.
    """
    v = (verdict or "").strip().lower()
    if v not in ("green", "red", "needs_root"):
        raise ValueError(f"verdict must be green|red|needs_root, got '{verdict}'")
    if not (judged_by or "").strip():
        raise ValueError("set_verdict requires a non-empty judged_by (the court identity)")

    # Root override must AUTHENTICATE before it bypasses anything. No env token
    # configured == the god-mode path is closed, not open.
    if is_root_authority and not root_token_ok(root_token):
        raise PermissionError(
            f"root override refused: is_root_authority=True requires env "
            f"{ROOT_TOKEN_ENV} to be set AND a matching root_token argument "
            f"(mismatch or absent). The unauthenticated god-mode bool is gone."
        )

    judge_norm = normalize_agent(judged_by)
    ts = TreeStore(store)

    def _fn(tree: RequirementTree) -> ReqNode:
        node = tree.nodes.get(node_id)
        if node is None:
            raise KeyError(f"node '{node_id}' not found in tree '{tree_id}'")

        # Anti-self-certify (all comparisons NORMALIZED; reads + decision inside
        # the critical section so a concurrent claim can't slip the identity
        # between check and write). Authenticated root authority bypasses —
        # that is its one purpose — and is audited below.
        if v == "green" and not is_root_authority:
            if node.is_leaf and not (node.claimed_by or "").strip():
                raise PermissionError(
                    f"green refused: leaf '{node_id}' was never claimed — a "
                    f"verdict needs a claimed executor to judge against "
                    f"(claim the leaf first, or the founder decides via the "
                    f"authenticated root override)."
                )
            if node.claimed_by and judge_norm == normalize_agent(node.claimed_by):
                raise PermissionError(
                    f"self-certification refused: judge '{judged_by}' is the same agent "
                    f"that claimed leaf '{node_id}' (identities compared normalized). "
                    f"The court must be an INDEPENDENT identity (executor never judges "
                    f"its own work). Founder override requires is_root_authority=True "
                    f"+ the root token."
                )
            past = {normalize_agent(p) for p in node.past_claimants}
            if judge_norm in past:
                raise PermissionError(
                    f"self-certification refused: judge '{judged_by}' previously "
                    f"CLAIMED leaf '{node_id}' (claim history: {node.past_claimants}). "
                    f"A red round-trip clears the claim but not the history — a past "
                    f"claimant cannot return as the judge."
                )

        now = datetime.now(timezone.utc)
        node.judged_by = judged_by
        node.evidence_ref = evidence_ref
        node.updated_at = now
        if v == "green":
            node.state = NodeState.GREEN
            node.verdict = "green"
        elif v == "red":
            node.state = NodeState.RED
            node.verdict = "red"
            node.attempts += 1
            # Record the claimer BEFORE clearing (belt for legacy trees whose
            # claims predate the past_claimants field).
            if node.claimed_by and normalize_agent(node.claimed_by) not in {
                normalize_agent(p) for p in node.past_claimants
            }:
                node.past_claimants.append(node.claimed_by)
            node.claimed_by = None  # re-enter the frontier
        else:  # needs_root
            node.state = NodeState.NEEDS_ROOT
            node.verdict = None

        _propagate_green(tree)
        return node

    result = ts.mutate_tree(tree_id, _fn)

    # AUDIT (defect 3): every authenticated root override leaves a real trace.
    if is_root_authority:
        _append_root_override_log(store, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tree_id": tree_id,
            "node_id": node_id,
            "judged_by": judged_by,
            "verdict": v,
            "evidence_ref": evidence_ref,
        })
    return result


def _propagate_green(tree: RequirementTree) -> None:
    """Derive internal-node greenness bottom-up: an internal node is GREEN iff
    every child is GREEN. Repeats to a fixpoint so a chain greens in one call.
    NEVER greens a leaf (leaves only go green via a court verdict)."""
    changed = True
    while changed:
        changed = False
        for node in tree.nodes.values():
            if node.is_leaf:
                continue
            # Fail-closed: a declared child id ABSENT from the tree (a corrupted
            # / partially-written persisted doc) is a DANGLING ref and blocks
            # greenness — it is NEVER silently dropped. An internal node greens
            # only when every declared child is PRESENT and GREEN. (The old
            # `if c in tree.nodes` filter + `if not kids: continue` were TWO
            # false-green paths: a partial-missing parent greened on its
            # surviving children, and an all-missing parent kept a stale green.)
            missing = [c for c in node.children if c not in tree.nodes]
            kids = [tree.nodes[c] for c in node.children if c in tree.nodes]
            all_green = (not missing) and bool(kids) and all(
                k.state == NodeState.GREEN for k in kids)
            if all_green and node.state != NodeState.GREEN:
                node.state = NodeState.GREEN
                node.verdict = "green"
                node.updated_at = datetime.now(timezone.utc)
                changed = True
            elif not all_green and node.state == NodeState.GREEN:
                # No longer fully green — a child reopened (re-decompose) OR a
                # child id is dangling. Either way the parent cannot stay green.
                node.state = NodeState.OPEN
                node.verdict = None
                node.updated_at = datetime.now(timezone.utc)
                changed = True


def frontier(store: "BrainStore", *, tree_id: str) -> list[ReqNode]:
    """The actionable leaves: every LEAF not yet GREEN (OPEN, CLAIMED, RED, or
    NEEDS_ROOT). This is what parallel executors pull from. Empty frontier of
    leaves == the tree is potentially dry (see `sweep`)."""
    ts = TreeStore(store)
    tree = ts.load(tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    return [n for n in tree.leaves() if n.state != NodeState.GREEN]


def open_leaves(store: "BrainStore", *, tree_id: str) -> list[ReqNode]:
    """Leaves an executor may CLAIM right now: OPEN or RED (RED == re-work),
    excluding CLAIMED (in-flight) and NEEDS_ROOT (escalated to the founder)."""
    return [
        n for n in frontier(store, tree_id=tree_id)
        if n.state in (NodeState.OPEN, NodeState.RED)
    ]


def sweep(store: "BrainStore", *, tree_id: str) -> dict[str, Any]:
    """Compute the full-green status of the tree — done == every leaf GREEN
    and the root GREEN (loop-until-dry termination test).

    Returns a status dict:
      {dry, root_green, counts:{open,claimed,green,red,needs_root},
       total_leaves, green_leaves, needs_root:[node_id...]}

    `dry` is True iff there are NO actionable (non-green) leaves AND the root is
    green — i.e. nothing left to decompose, claim, or refute. A tree with any
    NEEDS_ROOT leaf is NOT dry (it waits on the founder)."""
    ts = TreeStore(store)
    tree = ts.load(tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")

    counts = {s.value: 0 for s in NodeState}
    for n in tree.nodes.values():
        counts[n.state.value] += 1

    leaves = tree.leaves()
    green_leaves = [n for n in leaves if n.state == NodeState.GREEN]
    actionable = [n for n in leaves if n.state != NodeState.GREEN]
    needs_root = [n.node_id for n in tree.nodes.values() if n.state == NodeState.NEEDS_ROOT]
    root = tree.nodes.get(tree.root_id)
    root_green = bool(root and root.state == NodeState.GREEN)

    # Fail-closed integrity gate: a dangling child ref (a declared child absent
    # from `nodes` — a corrupted / partially-written persisted doc) means the
    # tree is structurally incomplete and can NEVER be "done", whatever the node
    # states say. The last line of defence against a silent false-green sweep.
    dangling = tree.dangling_child_refs()

    dry = (not actionable) and root_green and not needs_root and not dangling
    return {
        "tree_id": tree_id,
        "dry": dry,
        "root_green": root_green,
        "counts": counts,
        "total_leaves": len(leaves),
        "green_leaves": len(green_leaves),
        "actionable_leaves": len(actionable),
        "needs_root": needs_root,
        "dangling_refs": [{"parent": p, "missing_child": c} for p, c in dangling],
    }


def get_tree(store: "BrainStore", *, tree_id: str) -> Optional[RequirementTree]:
    """Convenience read-through for callers (court harness, orchestrator)."""
    return TreeStore(store).load(tree_id)


def list_trees(store: "BrainStore") -> list[str]:
    return TreeStore(store).list_trees()


# ─────────────────────────── MCP tool registration ─────────────────────


def register_tree_tools(mcp: "Any", store: "BrainStore") -> "Any":
    """Register the additive `brain.tree_*` MCP tools on an existing FastMCP
    instance — the ENCODE of the ROMA "method that finishes everything".

    PURE-ADDITIVE: this registers NEW tool names only and touches NO existing
    handler. `server.build_server` adds exactly ONE call to it next to the
    other registrations. Every tree mutation persists through `TreeStore`
    (one `brain_meta` JSON doc, key `requirement_tree_v1`) — no new table, no
    schema migration, no touch of `fragments` / `skills` / `-wal` / `-shm`.

    The three method pieces wire here:
      * TREE          — `create_root` / `decompose` (split-never-simplify) +
                        `claim_leaf` (parallel executors, anti-self-certify).
      * COURT         — `court_harness.convene_court` is the EXTERNAL jury
                        (artifact + diligence + independence lenses) that must
                        FAIL-TO-REFUTE a leaf on the REAL artifact before
                        `set_verdict` can flip it GREEN. Its verdict feeds
                        `set_verdict`, which re-checks anti-self-certify and
                        derives the up-tree green sweep.
      * LOOP-TO-DRY   — `sweep` / `frontier` report the green sweep + the open
                        leaves; done == root GREEN + no actionable leaves.
      * YOU = ROOT     — `needs_root` leaves are reserved to the founder;
                        `set_verdict(is_root_authority=True)` is the only
                        override of an anti-self-certify tie.

    Tools registered (all read-only except where noted):
      brain.tree_create     — vision → ROOT of a new requirement tree.   (writes)
      brain.tree_decompose  — split a node into machine-checkable children.(writes)
      brain.tree_claim      — an executor claims an OPEN/RED leaf.        (writes)
      brain.tree_court      — convene the EXTERNAL court on a leaf + apply
                              its verdict (green/red/needs_root).         (writes)
      brain.tree_verdict    — apply a verdict directly (judge ≠ claimer;
                              founder settles ties via is_root_authority).(writes)
      brain.tree_sweep      — roll verdicts up; report done = full green.
      brain.tree_frontier   — the open/claimed/red/needs_root leaves left.
      brain.tree_get        — read a whole tree (nodes + states).
      brain.tree_list       — list tree ids this brain holds.

    Returns `mcp` for chaining.
    """
    from .court_harness import convene_court

    def _resolve_owner() -> str:
        """Reuse the daemon's bound owner when the server exposed a resolver
        (server.build_server sets `mcp._brain_resolve_owner`); else 'founder'."""
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
        name="brain.tree_create",
        description=(
            "ROMA 'finish everything' method — START a requirement tree from a "
            "VISION. The vision becomes the ROOT node (state=open). Persisted "
            "ADDITIVELY in brain_meta (one JSON doc, key 'requirement_tree_v1') "
            "— no table, no schema change, never touches fragments/skills. "
            "Idempotent: re-creating the same title+owner returns the existing "
            "tree. Returns {ok, tree_id, root_id, root}. Then SPLIT it with "
            "brain.tree_decompose until every leaf is one machine-checkable "
            "predicate."
        ),
    )
    def brain_tree_create(
        title: str,
        owner_user: Optional[str] = None,
        predicate: str = "",
        gate_kind: str = "manual",
        gate_spec: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        try:
            tree = create_root(
                store,
                title=title,
                owner_user=owner_user or _resolve_owner(),
                predicate=predicate,
                gate_kind=gate_kind,
                gate_spec=gate_spec or {},
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {
            "ok": True,
            "tree_id": tree.tree_id,
            "root_id": tree.root_id,
            "root": tree.nodes[tree.root_id].model_dump(mode="json"),
        }

    @mcp.tool(
        name="brain.tree_decompose",
        description=(
            "ROMA method — SPLIT (never simplify) a node into children. "
            "children = [{title, predicate?, gate_kind?, gate_spec?}, ...]. "
            "gate_kind ∈ {py_compile, pytest, cdp, file_exists, manual} — how "
            "the external court will check that leaf on the REAL artifact "
            "(gate_spec carries the args, e.g. {'path': 'x.py'} or {'selector': "
            "'tests/test_x.py::test_y'}). Idempotent on identical child titles "
            "(re-decompose after a RED reuses ids + keeps green siblings). "
            "Refuses to re-split a GREEN node. Returns {ok, tree_id, node_id, "
            "children:[...], sweep}."
        ),
    )
    def brain_tree_decompose(
        tree_id: str,
        node_id: str,
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            tree = decompose(store, tree_id=tree_id, node_id=node_id, children=children)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        parent = tree.nodes[node_id]
        return {
            "ok": True,
            "tree_id": tree_id,
            "node_id": node_id,
            "children": [tree.nodes[c].model_dump(mode="json")
                         for c in parent.children if c in tree.nodes],
            "sweep": sweep(store, tree_id=tree_id),
        }

    @mcp.tool(
        name="brain.tree_claim",
        description=(
            "ROMA method — an EXECUTOR claims an OPEN (or RED, for re-work) "
            "LEAF. Records claimed_by=agent_id; the claimer can NEVER later "
            "certify its own leaf (brain.tree_court / brain.tree_verdict refuse "
            "a green when judge==claimer). Refuses internal nodes, already-GREEN "
            "leaves, and leaves claimed by another agent. Returns {ok, node}."
        ),
    )
    def brain_tree_claim(
        tree_id: str,
        node_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        try:
            node = claim_leaf(store, tree_id=tree_id, node_id=node_id, agent_id=agent_id)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "node": node.model_dump(mode="json")}

    @mcp.tool(
        name="brain.tree_court",
        description=(
            "ROMA method — convene the EXTERNAL COURT on a leaf and apply its "
            "verdict. The court (court_harness.convene_court) refutes through "
            "three INDEPENDENT lenses on the REAL artifact — ARTIFACT "
            "(py_compile/pytest/file_exists/cdp probe of the leaf predicate), "
            "DILIGENCE (never-reward-short: the brain's anti-laziness policy "
            "over `evidence`), and INDEPENDENCE (anti-tamper: judge_id MUST "
            "differ from the claimer + a named artifact must back the pass). "
            "A leaf goes GREEN only when the jury FAILS TO REFUTE (≥1 lens "
            "applied, none refuted); a manual leaf with no machine gate becomes "
            "needs_root (escalated to the founder, never auto-green). The "
            "verdict feeds set_verdict (which re-checks anti-self-certify + "
            "derives the up-tree green sweep). `context` may carry "
            "{repo_root, cwd, cdp_url, evidence:{last_message, touched_files, "
            "file_contents, session_signals}}. Returns {ok, court, node, sweep}."
        ),
    )
    def brain_tree_court(
        tree_id: str,
        node_id: str,
        judged_by: str,
        context: Optional[dict[str, Any]] = None,
        require_diligence: bool = False,
    ) -> dict[str, Any]:
        tree = get_tree(store, tree_id=tree_id)
        if tree is None:
            return {"ok": False, "error": f"tree '{tree_id}' not found"}
        node = tree.nodes.get(node_id)
        if node is None:
            return {"ok": False, "error": f"node '{node_id}' not in tree '{tree_id}'"}
        if not node.is_leaf:
            return {"ok": False,
                    "error": f"node '{node_id}' is internal — its greenness is "
                             f"derived from children; only leaves face the court"}
        try:
            cv = convene_court(
                node_id=node_id,
                gate_kind=node.gate_kind,
                gate_spec=node.gate_spec,
                claimed_by=node.claimed_by,
                judged_by=judged_by,
                context=context or {},
                # BOOSTING guard: a leaf on its 2nd+ round (>=1 red already)
                # must show the work — diligence becomes mandatory.
                require_diligence=require_diligence or node.attempts >= 1,
                # GATE-BINDING: a pre-existing artifact can't prove new work.
                leaf_created_at=node.created_at,
                leaf_title=node.title,
                leaf_predicate=node.predicate,
            )
        except Exception as ex:
            return {"ok": False, "error": f"court error: {type(ex).__name__}: {ex}"}
        # Feed the jury verdict into set_verdict — which re-enforces
        # anti-self-certify and derives the up-tree green sweep.
        try:
            updated = set_verdict(
                store,
                tree_id=tree_id,
                node_id=node_id,
                verdict=cv.verdict,
                judged_by=judged_by,
                evidence_ref=cv.reason[:480],
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}",
                    "court": cv.to_dict()}
        return {
            "ok": True,
            "court": cv.to_dict(),
            "node": updated.model_dump(mode="json"),
            "sweep": sweep(store, tree_id=tree_id),
        }

    @mcp.tool(
        name="brain.tree_verdict",
        description=(
            "ROMA method — apply a verdict ('green'|'red'|'needs_root') to a "
            "LEAF directly (e.g. an out-of-band court, or the founder settling "
            "an escalation). ANTI-SELF-CERTIFY (identities normalized): a "
            "'green' is REFUSED on a never-claimed leaf, when judged_by is the "
            "leaf's claimer, or when judged_by EVER claimed this leaf, UNLESS "
            "is_root_authority=true WITH a root_token matching env "
            "ARCHHUB_ROOT_TOKEN (the authenticated founder override; every use "
            "is audit-logged). 'red' bumps the re-work counter + frees the "
            "claim so the leaf re-enters the frontier. Greens derive up the "
            "tree (full green sweep). Returns {ok, node, sweep}."
        ),
    )
    def brain_tree_verdict(
        tree_id: str,
        node_id: str,
        verdict: str,
        judged_by: str,
        evidence_ref: Optional[str] = None,
        is_root_authority: bool = False,
        root_token: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            node = set_verdict(
                store,
                tree_id=tree_id,
                node_id=node_id,
                verdict=verdict,
                judged_by=judged_by,
                evidence_ref=evidence_ref,
                is_root_authority=is_root_authority,
                root_token=root_token,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "node": node.model_dump(mode="json"),
                "sweep": sweep(store, tree_id=tree_id)}

    @mcp.tool(
        name="brain.tree_sweep",
        description=(
            "ROMA method — roll leaf verdicts UP the tree and report the green "
            "sweep. Returns {tree_id, dry, root_green, counts:{open,claimed,"
            "green,red,needs_root}, total_leaves, green_leaves, "
            "actionable_leaves, needs_root:[...]}. dry=true iff the ROOT is "
            "GREEN AND no actionable (non-green) leaves remain AND nothing is "
            "escalated — the terminal loop-until-dry condition (done = full "
            "green sweep)."
        ),
    )
    def brain_tree_sweep(tree_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, **sweep(store, tree_id=tree_id)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.tree_frontier",
        description=(
            "ROMA method — the actionable leaves still to close: every LEAF not "
            "yet GREEN (OPEN=claim me, CLAIMED=in flight, RED=re-work / "
            "re-decompose, NEEDS_ROOT=founder decides). Parallel executors pull "
            "from here. Loop until this is empty AND the root is GREEN. Returns "
            "{ok, tree_id, frontier:[node...]}."
        ),
    )
    def brain_tree_frontier(tree_id: str) -> dict[str, Any]:
        try:
            nodes = frontier(store, tree_id=tree_id)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {
            "ok": True,
            "tree_id": tree_id,
            "frontier": [n.model_dump(mode="json") for n in nodes],
        }

    @mcp.tool(
        name="brain.tree_get",
        description=(
            "READ-ONLY. Return a whole requirement tree (root_id + every node "
            "with its state/verdict/claim/judge/children). Returns {ok, tree} "
            "or {ok:false} when the tree id is unknown."
        ),
    )
    def brain_tree_get(tree_id: str) -> dict[str, Any]:
        tree = get_tree(store, tree_id=tree_id)
        if tree is None:
            return {"ok": False, "error": f"tree '{tree_id}' not found"}
        return {"ok": True, "tree": tree.model_dump(mode="json")}

    @mcp.tool(
        name="brain.tree_list",
        description=(
            "READ-ONLY. List every requirement-tree id this brain holds (from "
            "the additive brain_meta doc). Returns {ok, tree_ids}."
        ),
    )
    def brain_tree_list() -> dict[str, Any]:
        try:
            return {"ok": True, "tree_ids": list_trees(store)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    return mcp
