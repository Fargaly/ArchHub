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
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # avoid a runtime import cycle; only needed for typing
    from .storage import BrainStore


# NEW brain_meta key — never collides with calibration_v1 / organize.clusters /
# diligence.stats / bound_owner_* / personal_cloud_sync.* etc.
TREE_META_KEY = "requirement_tree_v1"


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


class TreeStore:
    """Thin wrapper over `BrainStore.get_meta` / `set_meta`.

    Stores ALL trees as ONE JSON doc under `brain_meta[TREE_META_KEY]`:

        { tree_id: <RequirementTree json>, ... }

    Never creates a table, never touches fragments / skills. Every mutation is
    a read-modify-write of that single key — and because `set_meta` already
    serialises under the store's RLock, the doc-level write is atomic per call.
    """

    def __init__(self, store: "BrainStore"):
        self.store = store

    def _load_all(self) -> dict[str, dict]:
        raw = self.store.get_meta(TREE_META_KEY)
        if not raw:
            return {}
        try:
            doc = json.loads(raw)
        except Exception:
            return {}
        return doc if isinstance(doc, dict) else {}

    def _save_all(self, doc: dict[str, dict]) -> None:
        self.store.set_meta(TREE_META_KEY, json.dumps(doc, default=str))

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
        """Read-modify-write the single tree-namespace key. Bumps updated_at."""
        tree.updated_at = datetime.now(timezone.utc)
        doc = self._load_all()
        doc[tree.tree_id] = tree.model_dump(mode="json")
        self._save_all(doc)

    def list_trees(self) -> list[str]:
        return sorted(self._load_all().keys())

    def delete(self, tree_id: str) -> bool:
        doc = self._load_all()
        if tree_id in doc:
            del doc[tree_id]
            self._save_all(doc)
            return True
        return False


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
    ts = TreeStore(store)
    tree = ts.load(tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    parent = tree.nodes.get(node_id)
    if parent is None:
        raise KeyError(f"node '{node_id}' not found in tree '{tree_id}'")
    if parent.state == NodeState.GREEN:
        raise ValueError(
            f"refusing to decompose GREEN node '{node_id}' — verified-complete "
            f"nodes are not re-opened (supersede via a new root instead)"
        )
    if not children:
        raise ValueError("decompose requires at least one child (SPLIT, never simplify)")

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
    ts.save(tree)
    return tree


def claim_leaf(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    agent_id: str,
) -> ReqNode:
    """An executor claims an OPEN leaf → CLAIMED, recording claimed_by=agent_id.

    `agent_id` is REQUIRED and is the anti-self-certify anchor: `set_verdict`
    later REFUSES if the judge == claimed_by (the executor never judges its own
    leaf). Refuses a non-leaf, an already-GREEN leaf, or one already claimed by
    a DIFFERENT agent (re-claim by the same agent is idempotent)."""
    if not (agent_id or "").strip():
        raise ValueError("claim_leaf requires a non-empty agent_id (anti-self-certify anchor)")
    ts = TreeStore(store)
    tree = ts.load(tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    node = tree.nodes.get(node_id)
    if node is None:
        raise KeyError(f"node '{node_id}' not found in tree '{tree_id}'")
    if not node.is_leaf:
        raise ValueError(f"cannot claim non-leaf '{node_id}' — only leaves are executable")
    if node.state == NodeState.GREEN:
        raise ValueError(f"leaf '{node_id}' is already GREEN — nothing to claim")
    if node.claimed_by and node.claimed_by != agent_id:
        raise ValueError(
            f"leaf '{node_id}' already claimed by '{node.claimed_by}' "
            f"(requested by '{agent_id}')"
        )
    node.claimed_by = agent_id
    node.state = NodeState.CLAIMED
    node.updated_at = datetime.now(timezone.utc)
    ts.save(tree)
    return node


def set_verdict(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    verdict: str,
    judged_by: str,
    evidence_ref: Optional[str] = None,
    is_root_authority: bool = False,
) -> ReqNode:
    """Record the COURT's verdict on a leaf, then propagate derived greenness up.

    `verdict` ∈ {"green", "red", "needs_root"}.
    `judged_by` is the court/jury identity. ANTI-SELF-CERTIFY: a "green"
    verdict is REFUSED when `judged_by == node.claimed_by` (the executor cannot
    pass its own leaf) UNLESS `is_root_authority` is set — the founder (YOU) is
    the only authority that may override a tie, and even then it is logged.

    GREEN flips internal ancestors GREEN when ALL their children are green
    (the loop-until-dry "full green sweep" is derived, never asserted by hand).
    RED bumps `attempts` and clears the claim so the leaf re-enters the
    frontier for re-work / re-decompose.
    """
    ts = TreeStore(store)
    tree = ts.load(tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    node = tree.nodes.get(node_id)
    if node is None:
        raise KeyError(f"node '{node_id}' not found in tree '{tree_id}'")

    v = (verdict or "").strip().lower()
    if v not in ("green", "red", "needs_root"):
        raise ValueError(f"verdict must be green|red|needs_root, got '{verdict}'")
    if not (judged_by or "").strip():
        raise ValueError("set_verdict requires a non-empty judged_by (the court identity)")

    # Anti-self-certify: the executor that CLAIMED the leaf may not green it.
    if (
        v == "green"
        and node.claimed_by
        and judged_by == node.claimed_by
        and not is_root_authority
    ):
        raise PermissionError(
            f"self-certification refused: judge '{judged_by}' is the same agent "
            f"that claimed leaf '{node_id}'. The court must be an INDEPENDENT "
            f"identity (executor never judges its own work). Founder override "
            f"requires is_root_authority=True."
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
        node.claimed_by = None  # re-enter the frontier
    else:  # needs_root
        node.state = NodeState.NEEDS_ROOT
        node.verdict = None

    _propagate_green(tree)
    ts.save(tree)
    return tree.nodes[node_id]


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
                require_diligence=require_diligence,
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
            "an escalation). ANTI-SELF-CERTIFY: a 'green' is REFUSED when "
            "judged_by == the leaf's claimer, UNLESS is_root_authority=true "
            "(the founder/root is the only override of a tie). 'red' bumps the "
            "re-work counter + frees the claim so the leaf re-enters the "
            "frontier. Greens derive up the tree (full green sweep). Returns "
            "{ok, node, sweep}."
        ),
    )
    def brain_tree_verdict(
        tree_id: str,
        node_id: str,
        verdict: str,
        judged_by: str,
        evidence_ref: Optional[str] = None,
        is_root_authority: bool = False,
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
