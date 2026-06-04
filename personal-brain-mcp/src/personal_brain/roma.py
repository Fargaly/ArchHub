"""ROMA orchestration engine + additive MCP tool surface.

Ties the three existing pieces named in the encode brief into one method:

    Workflow (orchestrate)  →  the loop in `run_to_dry` + the .js template
    personal-brain (hold the tree + skill library)  →  requirement_tree.TreeStore
    ArchHub court (gate on the real artifact)  →  court_harness.convene_court
    never-reward-short  →  diligence.evaluate_diligence (wired as a juror)
    YOU (founder) = root for taste/ties  →  NEEDS_ROOT escape + root authority

The whole engine is store-backed (brain_meta, additive) and pure-Python. It
exposes module-level functions AND a `register_roma_tools(mcp, store)` that
attaches a `brain.roma_*` tool family to the FastMCP server. `build_server`
calls it via exactly ONE added line (no existing handler touched).

Loop shape (mirrors the method exactly):

    atomize   → create_root(vision) + decompose until leaves are machine-checkable
    claim     → executors claim OPEN/RED leaves (none self-certify)
    judge     → convene_court on each CLAIMED leaf against the REAL artifact
    settle    → green | red(→re-work) | needs_root(→founder)
    loop      → repeat until sweep().dry  (full green sweep == done)

SAFETY: never writes to fragments/skills; only requirement_tree's single
brain_meta key. The court's artifact probes are injectable so this module
itself runs the deterministic gates (py_compile/pytest/file) and only touches
the live app via an explicitly-supplied CDP probe.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from . import requirement_tree as rt
from .court_harness import ProbeRunner, convene_court

if TYPE_CHECKING:
    from .storage import BrainStore


# An executor is (leaf: ReqNode, context) -> evidence dict. It DOES the work
# and returns the closing evidence the court will judge (last_message + proof
# signals + touched files). Injectable so the orchestrator stays testable; in
# production a Workflow sub-agent fills this role (see roma.template.js).
ExecutorFn = Callable[["rt.ReqNode", dict[str, Any]], dict[str, Any]]


def atomize(
    store: "BrainStore",
    *,
    vision: str,
    decomposition: list[dict[str, Any]],
    owner_user: str = "founder",
    tree_id: Optional[str] = None,
) -> rt.RequirementTree:
    """Build the requirement tree from a vision + a (possibly nested)
    decomposition.

    `decomposition` is a list of node specs; each:
        {title, predicate?, gate_kind?, gate_spec?, children?: [ ...same... ]}
    A node with `children` is internal (split, never simplified); a node
    without is a LEAF and SHOULD carry a machine-checkable gate. This is the
    one-shot atomizer; `brain.roma_decompose` lets the loop split further on RED.
    """
    tree = rt.create_root(store, title=vision, owner_user=owner_user, tree_id=tree_id)

    def _attach(parent_id: str, specs: list[dict[str, Any]]) -> None:
        if not specs:
            return
        child_specs = [
            {
                "title": s.get("title", ""),
                "predicate": s.get("predicate", ""),
                "gate_kind": s.get("gate_kind", "manual"),
                "gate_spec": s.get("gate_spec", {}),
            }
            for s in specs if s.get("title")
        ]
        if not child_specs:
            return
        rt.decompose(store, tree_id=tree.tree_id, node_id=parent_id, children=child_specs)
        # Recurse for any spec that itself has children.
        reloaded = rt.get_tree(store, tree_id=tree.tree_id)
        assert reloaded is not None
        for s in specs:
            title = s.get("title")
            if title and s.get("children"):
                cid = rt._node_id(tree.tree_id, parent_id, title)
                _attach(cid, s["children"])

    _attach(tree.root_id, decomposition)
    result = rt.get_tree(store, tree_id=tree.tree_id)
    assert result is not None
    return result


def judge_leaf(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    judged_by: str = "roma-court",
    context: Optional[dict[str, Any]] = None,
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
    require_diligence: bool = False,
) -> dict[str, Any]:
    """Convene the court on ONE leaf against the real artifact, then record the
    verdict in the tree (green / red / needs_root). Returns
    {court: <CourtVerdict dict>, node: <ReqNode dict>}.

    ANTI-SELF-CERTIFY is enforced twice: the independence lens refuses a judge
    == executor, AND `set_verdict` itself refuses a green where judged_by ==
    claimed_by. Belt-and-braces."""
    tree = rt.get_tree(store, tree_id=tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    node = tree.nodes.get(node_id)
    if node is None:
        raise KeyError(f"node '{node_id}' not found")

    verdict = convene_court(
        node_id=node_id,
        gate_kind=node.gate_kind,
        gate_spec=node.gate_spec,
        claimed_by=node.claimed_by,
        judged_by=judged_by,
        context=context,
        extra_probes=extra_probes,
        require_diligence=require_diligence,
    )

    updated = rt.set_verdict(
        store,
        tree_id=tree_id,
        node_id=node_id,
        verdict=verdict.verdict,
        judged_by=judged_by,
        evidence_ref=next(
            (l.evidence_ref for l in verdict.lenses if l.evidence_ref), None
        ),
    )
    return {"court": verdict.to_dict(), "node": updated.model_dump(mode="json")}


def run_to_dry(
    store: "BrainStore",
    *,
    tree_id: str,
    executor: ExecutorFn,
    judged_by: str = "roma-court",
    context: Optional[dict[str, Any]] = None,
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
    require_diligence: bool = False,
    max_rounds: int = 25,
    auto_decompose: Optional[Callable[["rt.ReqNode"], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """The loop-until-dry driver.

    Each round:
      1. pull the OPEN/RED leaves (the claimable frontier),
      2. for each: claim → run the executor → judge with the external court,
      3. RED leaves that have exceeded re-work and have an `auto_decompose`
         re-decompose into machine-checkable children (split, never simplify),
      4. stop when `sweep().dry` (full green sweep) OR no progress was made
         in a round (avoids a spin when only NEEDS_ROOT leaves remain — those
         wait for the founder).

    `executor(leaf, context) -> evidence` DOES the leaf's work and returns the
    closing evidence the court judges. The court — NOT the executor — decides
    green. Returns a final report dict with the sweep + per-round trace."""
    ctx = dict(context or {})
    rounds: list[dict[str, Any]] = []

    for round_no in range(1, max_rounds + 1):
        claimable = rt.open_leaves(store, tree_id=tree_id)
        if not claimable:
            break

        progressed = False
        round_trace: list[dict[str, Any]] = []
        for leaf in claimable:
            agent_id = ctx.get("executor_id") or "roma-executor"
            # The executor identity must differ from the court — assert it so a
            # misconfigured caller can't silently self-certify.
            if agent_id == judged_by:
                agent_id = f"{agent_id}#executor"
            rt.claim_leaf(store, tree_id=tree_id, node_id=leaf.node_id, agent_id=agent_id)

            # DO THE WORK — collect closing evidence for the diligence lens.
            try:
                evidence = executor(leaf, ctx) or {}
            except Exception as ex:
                evidence = {"last_message": f"executor crashed: {ex}",
                            "session_signals": {}}
            leaf_ctx = dict(ctx)
            leaf_ctx["evidence"] = evidence

            result = judge_leaf(
                store, tree_id=tree_id, node_id=leaf.node_id,
                judged_by=judged_by, context=leaf_ctx,
                extra_probes=extra_probes, require_diligence=require_diligence,
            )
            round_trace.append({
                "node_id": leaf.node_id,
                "title": leaf.title,
                "verdict": result["court"]["verdict"],
                "reason": result["court"]["reason"][:240],
            })
            verdict = result["court"]["verdict"]
            if verdict == "green":
                progressed = True
            elif verdict == "red" and auto_decompose is not None:
                # loop-until-dry RE-DECOMPOSE: a refuted leaf is split into
                # machine-checkable children rather than retried forever.
                reloaded = rt.get_tree(store, tree_id=tree_id)
                node = reloaded.nodes.get(leaf.node_id) if reloaded else None
                if node is not None:
                    kids = auto_decompose(node)
                    if kids:
                        rt.decompose(store, tree_id=tree_id, node_id=leaf.node_id,
                                     children=kids)
                        progressed = True

        rounds.append({"round": round_no, "leaves": round_trace})
        status = rt.sweep(store, tree_id=tree_id)
        if status["dry"]:
            break
        if not progressed:
            # only NEEDS_ROOT / stuck-RED leaves remain — escalate, don't spin.
            break

    final = rt.sweep(store, tree_id=tree_id)
    final["rounds"] = rounds
    final["rounds_run"] = len(rounds)
    return final


# ─────────────────────────── MCP tool surface ──────────────────────────


def register_roma_tools(mcp: Any, store: "BrainStore") -> None:
    """Attach the additive `brain.roma_*` tool family to a FastMCP server.

    Called by `build_server` via ONE added line. Registers NEW tools only —
    zero existing handlers touched. Each tool is a thin shell over the pure
    functions above (same pattern as every other brain.* tool).

    The court tools run the DETERMINISTIC artifact gates (py_compile / pytest /
    file_exists) + the diligence juror in-process; the CDP live-DOM gate is
    opt-in (the caller passes gate_kind='cdp' with an expression, and the
    daemon builds the CDP probe only then)."""

    @mcp.tool(
        name="brain.roma_atomize",
        description=(
            "ROMA step 1 — ATOMIZE a vision into a requirement TREE. The "
            "vision becomes the ROOT; `decomposition` is a (possibly nested) "
            "list of node specs [{title, predicate?, gate_kind?, gate_spec?, "
            "children?}]. A node with children is internal (split, never "
            "simplified); a leaf SHOULD carry a machine-checkable gate "
            "(gate_kind: py_compile|pytest|file_exists|cdp). Persists the tree "
            "additively in brain_meta (no new table). Returns the tree + sweep."
        ),
    )
    def roma_atomize(
        vision: str,
        decomposition: Optional[list[dict[str, Any]]] = None,
        owner_user: Optional[str] = None,
        tree_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _default_owner(store)
        tree = atomize(
            store, vision=vision, decomposition=decomposition or [],
            owner_user=owner, tree_id=tree_id,
        )
        return {
            "ok": True,
            "tree_id": tree.tree_id,
            "root_id": tree.root_id,
            "sweep": rt.sweep(store, tree_id=tree.tree_id),
            "tree": tree.model_dump(mode="json"),
        }

    @mcp.tool(
        name="brain.roma_decompose",
        description=(
            "ROMA — SPLIT (never simplify) a node into children. children = "
            "[{title, predicate?, gate_kind?, gate_spec?}]. Idempotent on "
            "identical child titles (re-decompose on RED reuses ids). Refuses "
            "to decompose a GREEN node. Returns the updated tree + sweep."
        ),
    )
    def roma_decompose(
        tree_id: str,
        node_id: str,
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            tree = rt.decompose(store, tree_id=tree_id, node_id=node_id, children=children)
        except (KeyError, ValueError) as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, "tree_id": tree_id,
                "sweep": rt.sweep(store, tree_id=tree_id),
                "tree": tree.model_dump(mode="json")}

    @mcp.tool(
        name="brain.roma_claim",
        description=(
            "ROMA — an executor CLAIMS an OPEN/RED leaf (state→claimed, "
            "claimed_by=agent_id). agent_id is REQUIRED and is the anti-self-"
            "certify anchor: the court later refuses a green where judge == "
            "this agent. Refuses non-leaf / already-claimed-by-another."
        ),
    )
    def roma_claim(tree_id: str, node_id: str, agent_id: str) -> dict[str, Any]:
        try:
            node = rt.claim_leaf(store, tree_id=tree_id, node_id=node_id, agent_id=agent_id)
        except (KeyError, ValueError) as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, "node": node.model_dump(mode="json")}

    @mcp.tool(
        name="brain.roma_judge",
        description=(
            "ROMA — convene the EXTERNAL COURT (3 diverse lenses: artifact, "
            "diligence/never-reward-short, independence/anti-tamper) on one "
            "claimed leaf against the REAL artifact, then record the verdict. "
            "judged_by MUST differ from the leaf's claimed_by (executor never "
            "judges its own work). Pass `evidence` {last_message, "
            "touched_files?, file_contents?, session_signals?} so the "
            "diligence juror can run. A leaf goes GREEN only when the jury "
            "FAILS TO REFUTE it; an unverifiable (manual) leaf → needs_root "
            "(founder decides). Returns {court, node}."
        ),
    )
    def roma_judge(
        tree_id: str,
        node_id: str,
        judged_by: str = "roma-court",
        evidence: Optional[dict[str, Any]] = None,
        cdp_url: Optional[str] = None,
        require_diligence: bool = False,
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        if evidence:
            ctx["evidence"] = evidence
        if cdp_url:
            ctx["cdp_url"] = cdp_url
        # Build the CDP probe only when the leaf actually needs it (the live
        # app + websocket-client are only required for a cdp gate).
        extra: dict[str, ProbeRunner] = {}
        tree = rt.get_tree(store, tree_id=tree_id)
        node = tree.nodes.get(node_id) if tree else None
        if node is not None and node.gate_kind == "cdp":
            try:
                from .court_harness import make_cdp_probe
                extra["cdp"] = make_cdp_probe(cdp_url or "http://127.0.0.1:9223")
            except Exception:
                pass
        try:
            return {"ok": True, **judge_leaf(
                store, tree_id=tree_id, node_id=node_id, judged_by=judged_by,
                context=ctx, extra_probes=extra, require_diligence=require_diligence,
            )}
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}

    @mcp.tool(
        name="brain.roma_sweep",
        description=(
            "ROMA — the loop-until-dry status. Returns {dry, root_green, "
            "counts, total_leaves, green_leaves, actionable_leaves, "
            "needs_root}. `dry` (done) is True iff every leaf is GREEN, the "
            "root is GREEN, and no leaf is NEEDS_ROOT. The frontier is the set "
            "of non-green leaves; an empty actionable frontier with a green "
            "root is a finished tree."
        ),
    )
    def roma_sweep(tree_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, **rt.sweep(store, tree_id=tree_id)}
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}

    @mcp.tool(
        name="brain.roma_frontier",
        description=(
            "ROMA — list the actionable leaves (every leaf not yet GREEN: "
            "open/claimed/red/needs_root). This is what parallel executors "
            "pull from. Pass claimable_only=true to get only OPEN/RED leaves "
            "(excludes in-flight CLAIMED + escalated NEEDS_ROOT)."
        ),
    )
    def roma_frontier(tree_id: str, claimable_only: bool = False) -> dict[str, Any]:
        try:
            leaves = (rt.open_leaves(store, tree_id=tree_id) if claimable_only
                      else rt.frontier(store, tree_id=tree_id))
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, "tree_id": tree_id,
                "leaves": [n.model_dump(mode="json") for n in leaves]}

    @mcp.tool(
        name="brain.roma_list",
        description="ROMA — list all requirement-tree ids held in this brain.",
    )
    def roma_list() -> dict[str, Any]:
        return {"ok": True, "trees": rt.list_trees(store)}


def _default_owner(store: "BrainStore") -> str:
    """Best-effort owner resolution that honours a cloud binding when present,
    matching server.resolve_default_owner without importing build_server."""
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
