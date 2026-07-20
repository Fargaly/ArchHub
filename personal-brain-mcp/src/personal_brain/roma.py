"""ROMA orchestration engine + additive MCP tool surface.

Ties the three existing pieces named in the encode brief into one method:

    Workflow (orchestrate)  →  the loop in `run_to_dry` + the .js template
    personal-brain (hold the tree + skill library)  →  requirement_tree.TreeStore
    ArchHub court (gate on the real artifact)  →  court_harness.convene_court
    never-reward-short  →  diligence.evaluate_diligence (wired as a juror)
    YOU (founder) = root for taste/ties  →  NEEDS_ROOT escape + root authority

The legacy direct Python helpers remain store-backed (brain_meta, additive) for
compatibility tests and old local callers. The governed path is Cell-first:
`*_cell_first` helpers and mutating `brain.roma_*` handlers sync the actual
requirement tree to the Universal Cell application route before updating the
Brain metadata projection.
`register_roma_tools(mcp, store)` attaches the tool family to the FastMCP
server. `build_server` calls it via exactly ONE added line.

Loop shape (mirrors the method exactly):

    atomize   → create_root(vision) + decompose until leaves are machine-checkable
    claim     → executors claim OPEN/RED leaves (none self-certify)
    judge     → convene_court on each CLAIMED leaf against the REAL artifact
    settle    → green | red(→re-work) | needs_root(→founder)
    loop      → repeat until sweep().dry  (full green sweep == done)

SAFETY: never writes to fragments/skills. MCP writes require the Universal Cell
tree sync first; `brain_meta` is a compatibility projection. The court's
artifact probes are injectable so this module itself runs the deterministic
gates (py_compile/pytest/file) and only touches the live app via an
explicitly-supplied CDP probe.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from . import requirement_tree as rt
from .court_harness import ProbeRunner, convene_court
from .server_verify import VerifyAttestation, server_side_verify, verify_attestation

if TYPE_CHECKING:
    from .storage import BrainStore


# An executor is (leaf: ReqNode, context) -> evidence dict. It DOES the work
# and returns the closing evidence the court will judge (last_message + proof
# signals + touched files). Injectable so the orchestrator stays testable; in
# production a Workflow sub-agent fills this role (see roma.template.js).
ExecutorFn = Callable[["rt.ReqNode", dict[str, Any]], dict[str, Any]]


def atomize_candidate(
    *,
    vision: str,
    decomposition: list[dict[str, Any]],
    owner_user: str = "founder",
    tree_id: Optional[str] = None,
) -> rt.RequirementTree:
    """Build an atomized tree in memory before any compatibility projection."""
    tree = rt.build_root_tree(
        title=vision,
        owner_user=owner_user,
        tree_id=tree_id,
    )

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
        rt._decompose_tree(
            tree,
            tree_id=tree.tree_id,
            node_id=parent_id,
            children=child_specs,
        )
        for s in specs:
            title = s.get("title")
            if title and s.get("children"):
                cid = rt._node_id(tree.tree_id, parent_id, title)
                _attach(cid, s["children"])

    _attach(tree.root_id, decomposition)
    return tree


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
    tree = atomize_candidate(
        vision=vision,
        decomposition=decomposition or [],
        owner_user=owner_user,
        tree_id=tree_id,
    )
    rt.TreeStore(store).save(tree)
    return tree


def atomize_cell_first(
    store: "BrainStore",
    *,
    vision: str,
    decomposition: list[dict[str, Any]],
    owner_user: str = "founder",
    tree_id: Optional[str] = None,
) -> dict[str, Any]:
    """Direct atomize path that uses the Universal Cell route as authority."""
    tree = atomize_candidate(
        vision=vision,
        decomposition=decomposition or [],
        owner_user=owner_user,
        tree_id=tree_id,
    )
    cell_tree = rt.sync_requirement_tree_cell_graph(
        operation="roma.atomize_cell_first",
        tree=tree,
    )
    rt.save_tree_projection_after_cell_sync(store, tree=tree)
    return {
        "ok": True,
        "authority_source": "cell_route",
        "brain_written": True,
        "tree_id": tree.tree_id,
        "root_id": tree.root_id,
        "tree": tree.model_dump(mode="json"),
        "cell_tree": cell_tree,
        "sweep": rt.sweep_tree(tree),
    }


def decompose_cell_first(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    tree, read_authority_source, _projection = rt.read_tree_authority_first(
        store, tree_id=tree_id
    )
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    candidate = rt.clone_tree(tree)
    rt._decompose_tree(
        candidate, tree_id=tree_id, node_id=node_id, children=children
    )
    cell_tree = rt.sync_requirement_tree_cell_graph(
        operation="roma.decompose_cell_first",
        tree=candidate,
    )
    rt.save_tree_projection_after_cell_sync(store, tree=candidate)
    parent = candidate.nodes[node_id]
    return {
        "ok": True,
        "authority_source": "cell_route",
        "read_authority_source": read_authority_source,
        "brain_written": True,
        "tree_id": tree_id,
        "node_id": node_id,
        "children": [
            candidate.nodes[child].model_dump(mode="json")
            for child in parent.children
            if child in candidate.nodes
        ],
        "tree": candidate.model_dump(mode="json"),
        "cell_tree": cell_tree,
        "sweep": rt.sweep_tree(candidate),
    }


def claim_leaf_cell_first(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    agent_id: str,
) -> dict[str, Any]:
    tree, read_authority_source, _projection = rt.read_tree_authority_first(
        store, tree_id=tree_id
    )
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    candidate = rt.clone_tree(tree)
    node = rt._claim_leaf_in_tree(
        candidate, tree_id=tree_id, node_id=node_id, agent_id=agent_id
    )
    cell_tree = rt.sync_requirement_tree_cell_graph(
        operation="roma.claim_leaf_cell_first",
        tree=candidate,
    )
    rt.save_tree_projection_after_cell_sync(store, tree=candidate)
    return {
        "ok": True,
        "authority_source": "cell_route",
        "read_authority_source": read_authority_source,
        "brain_written": True,
        "tree_id": tree_id,
        "node": node.model_dump(mode="json"),
        "tree": candidate.model_dump(mode="json"),
        "cell_tree": cell_tree,
        "sweep": rt.sweep_tree(candidate),
    }


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
    == executor (normalized), AND `set_verdict` itself refuses a green where
    judged_by is the claimer or any past claimant. Belt-and-braces.

    GATE-BINDING: the leaf's created_at + title/predicate are passed to the
    court so a pre-existing artifact (mtime before the leaf existed) REFUTES.
    BOOSTING guard: a leaf on its 2nd+ round (attempts >= 1 — it has already
    been refuted once) is judged with require_diligence forced on."""
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
        require_diligence=require_diligence or node.attempts >= 1,
        leaf_created_at=node.created_at,
        leaf_title=node.title,
        leaf_predicate=node.predicate,
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


def judge_leaf_cell_first(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    judged_by: str = "roma-court",
    context: Optional[dict[str, Any]] = None,
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
    require_diligence: bool = False,
) -> dict[str, Any]:
    """Convene court and write the verdict through the Cell route first."""
    tree, read_authority_source, _projection = rt.read_tree_authority_first(
        store, tree_id=tree_id
    )
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
        require_diligence=require_diligence or node.attempts >= 1,
        leaf_created_at=node.created_at,
        leaf_title=node.title,
        leaf_predicate=node.predicate,
    )
    candidate = rt.clone_tree(tree)
    updated = rt._set_verdict_in_tree(
        candidate,
        tree_id=tree_id,
        node_id=node_id,
        verdict=verdict.verdict,
        judged_by=judged_by,
        evidence_ref=next(
            (lens.evidence_ref for lens in verdict.lenses if lens.evidence_ref),
            None,
        ),
    )
    cell_tree = rt.sync_requirement_tree_cell_graph(
        operation="roma.judge_leaf_cell_first",
        tree=candidate,
    )
    rt.save_tree_projection_after_cell_sync(store, tree=candidate)
    return {
        "ok": True,
        "authority_source": "cell_route",
        "read_authority_source": read_authority_source,
        "brain_written": True,
        "court": verdict.to_dict(),
        "node": updated.model_dump(mode="json"),
        "tree": candidate.model_dump(mode="json"),
        "cell_tree": cell_tree,
        "sweep": rt.sweep_tree(candidate),
    }


def server_verify_leaf(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    judged_by: str = "roma-server-verifier",
    context: Optional[dict[str, Any]] = None,
    require_diligence: bool = False,
    signing_key_ref: Optional[str] = None,
) -> dict[str, Any]:
    """SERVER-SIDE re-verify of one leaf — OFF the contributor's process.

    Unlike `judge_leaf` (the in-process court the executor's own interpreter
    runs), this re-executes the leaf's artifact gate in a FRESH subprocess and
    returns a SIGNED `VerifyAttestation`. The verdict it records in the tree is
    therefore one a forged contributor "green" cannot have produced (the
    artifact was re-checked on the real disk, off the claimant's box, and the
    attestation is HMAC-signed with a server-held key).

    This is the BRV-05 mechanism: the ROMA court no longer has to trust a
    verdict produced on the contributing machine. Returns
    {attestation: <dict>, node: <ReqNode dict>, authentic: bool,
     authentic_reason: str}.
    """
    tree = rt.get_tree(store, tree_id=tree_id)
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    node = tree.nodes.get(node_id)
    if node is None:
        raise KeyError(f"node '{node_id}' not found")

    att = server_side_verify(
        node_id=node_id,
        gate_kind=node.gate_kind,
        gate_spec=node.gate_spec,
        claimed_by=node.claimed_by,
        judged_by=judged_by,
        context=context,
        require_diligence=require_diligence,
        signing_key_ref=signing_key_ref,
    )

    # The server's OWN attestation is re-checked before it is trusted to write
    # a verdict: an unsigned/forged attestation is never allowed to green a leaf
    # when a key is configured. (Belt-and-braces, same spirit as judge_leaf's
    # double anti-self-cert.) `require_signed=False` so a no-key dev/test brain
    # still records verdicts; a key-bearing server refuses unsigned downgrades.
    authentic, authentic_reason = verify_attestation(
        att, signing_key_ref=signing_key_ref, require_signed=False,
    )
    record_verdict = att.verdict
    if att.green and not authentic:
        # A green whose attestation does not verify is downgraded to red — the
        # server never writes a green it cannot itself authenticate.
        record_verdict = "red"

    updated = rt.set_verdict(
        store,
        tree_id=tree_id,
        node_id=node_id,
        verdict=record_verdict,
        judged_by=judged_by,
        evidence_ref=att.evidence_ref,
    )
    return {
        "attestation": att.to_dict(),
        "node": updated.model_dump(mode="json"),
        "authentic": authentic,
        "authentic_reason": authentic_reason,
    }


def server_verify_leaf_cell_first(
    store: "BrainStore",
    *,
    tree_id: str,
    node_id: str,
    judged_by: str = "roma-server-verifier",
    context: Optional[dict[str, Any]] = None,
    require_diligence: bool = False,
    signing_key_ref: Optional[str] = None,
) -> dict[str, Any]:
    """Server-side verification with Cell-route-first verdict persistence."""
    tree, read_authority_source, _projection = rt.read_tree_authority_first(
        store, tree_id=tree_id
    )
    if tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    node = tree.nodes.get(node_id)
    if node is None:
        raise KeyError(f"node '{node_id}' not found")

    att = server_side_verify(
        node_id=node_id,
        gate_kind=node.gate_kind,
        gate_spec=node.gate_spec,
        claimed_by=node.claimed_by,
        judged_by=judged_by,
        context=context,
        require_diligence=require_diligence,
        signing_key_ref=signing_key_ref,
    )
    authentic, authentic_reason = verify_attestation(
        att, signing_key_ref=signing_key_ref, require_signed=False,
    )
    record_verdict = att.verdict
    if att.green and not authentic:
        record_verdict = "red"

    candidate = rt.clone_tree(tree)
    updated = rt._set_verdict_in_tree(
        candidate,
        tree_id=tree_id,
        node_id=node_id,
        verdict=record_verdict,
        judged_by=judged_by,
        evidence_ref=att.evidence_ref,
    )
    cell_tree = rt.sync_requirement_tree_cell_graph(
        operation="roma.server_verify_leaf_cell_first",
        tree=candidate,
    )
    rt.save_tree_projection_after_cell_sync(store, tree=candidate)
    return {
        "ok": True,
        "authority_source": "cell_route",
        "read_authority_source": read_authority_source,
        "brain_written": True,
        "attestation": att.to_dict(),
        "node": updated.model_dump(mode="json"),
        "authentic": authentic,
        "authentic_reason": authentic_reason,
        "tree": candidate.model_dump(mode="json"),
        "cell_tree": cell_tree,
        "sweep": rt.sweep_tree(candidate),
    }


def run_to_dry(
    store: "BrainStore",
    *,
    tree_id: str,
    executor: ExecutorFn,
    judged_by: str = "roma-court",
    context: Optional[dict[str, Any]] = None,
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
    require_diligence: bool = True,
    max_rounds: int = 25,
    auto_decompose: Optional[Callable[["rt.ReqNode"], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """The loop-until-dry driver.

    AUDIT FIX (defect 7): `require_diligence` now DEFAULTS TRUE — the unattended
    loop holds every leaf to never-reward-short unless a caller explicitly
    opts out.

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


def run_to_dry_cell_first(
    store: "BrainStore",
    *,
    tree_id: str,
    executor: ExecutorFn,
    judged_by: str = "roma-court",
    context: Optional[dict[str, Any]] = None,
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
    require_diligence: bool = True,
    max_rounds: int = 25,
    auto_decompose: Optional[Callable[["rt.ReqNode"], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """Loop-until-dry driver whose mutations go through the Cell route first."""
    ctx = dict(context or {})
    rounds: list[dict[str, Any]] = []

    for round_no in range(1, max_rounds + 1):
        tree, read_authority_source, _projection = rt.read_tree_authority_first(
            store, tree_id=tree_id
        )
        if tree is None:
            raise KeyError(f"tree '{tree_id}' not found")
        claimable = rt.open_leaves_for_tree(tree)
        if not claimable:
            break

        progressed = False
        round_trace: list[dict[str, Any]] = []
        for leaf in claimable:
            agent_id = ctx.get("executor_id") or "roma-executor"
            if agent_id == judged_by:
                agent_id = f"{agent_id}#executor"
            try:
                claim_leaf_cell_first(
                    store, tree_id=tree_id, node_id=leaf.node_id,
                    agent_id=agent_id,
                )
            except (KeyError, ValueError):
                continue

            try:
                evidence = executor(leaf, ctx) or {}
            except Exception as ex:
                evidence = {
                    "last_message": f"executor crashed: {ex}",
                    "session_signals": {},
                }
            leaf_ctx = dict(ctx)
            leaf_ctx["evidence"] = evidence
            result = judge_leaf_cell_first(
                store,
                tree_id=tree_id,
                node_id=leaf.node_id,
                judged_by=judged_by,
                context=leaf_ctx,
                extra_probes=extra_probes,
                require_diligence=require_diligence,
            )
            round_trace.append({
                "node_id": leaf.node_id,
                "title": leaf.title,
                "verdict": result["court"]["verdict"],
                "reason": result["court"]["reason"][:240],
                "read_authority_source": read_authority_source,
            })
            verdict = result["court"]["verdict"]
            if verdict == "green":
                progressed = True
            elif verdict == "red" and auto_decompose is not None:
                latest, _source, _projection = rt.read_tree_authority_first(
                    store, tree_id=tree_id
                )
                node = latest.nodes.get(leaf.node_id) if latest else None
                if node is not None:
                    kids = auto_decompose(node)
                    if kids:
                        decompose_cell_first(
                            store, tree_id=tree_id, node_id=leaf.node_id,
                            children=kids,
                        )
                        progressed = True

        rounds.append({"round": round_no, "leaves": round_trace})
        current, _source, _projection = rt.read_tree_authority_first(
            store, tree_id=tree_id
        )
        if current is None:
            raise KeyError(f"tree '{tree_id}' not found")
        status = rt.sweep_tree(current)
        if status["dry"]:
            break
        if not progressed:
            break

    final_tree, authority_source, _projection = rt.read_tree_authority_first(
        store, tree_id=tree_id
    )
    if final_tree is None:
        raise KeyError(f"tree '{tree_id}' not found")
    final = rt.sweep_tree(final_tree)
    final["authority_source"] = authority_source
    final["rounds"] = rounds
    final["rounds_run"] = len(rounds)
    return final


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
            "(gate_kind: py_compile|pytest|file_exists|cdp). Syncs the tree to "
            "the Universal Cell application route first, then writes the Brain "
            "metadata compatibility projection. Returns the tree + sweep."
        ),
    )
    def roma_atomize(
        vision: str,
        decomposition: Optional[list[dict[str, Any]]] = None,
        owner_user: Optional[str] = None,
        tree_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or _default_owner(store)
        try:
            tree = atomize_candidate(
                vision=vision,
                decomposition=decomposition or [],
                owner_user=owner,
                tree_id=tree_id,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        try:
            cell_tree = rt.sync_requirement_tree_cell_graph(
                operation="brain.roma_atomize",
                tree=tree,
            )
        except Exception as ex:
            return rt.cell_tree_unavailable_response("brain.roma_atomize", ex)
        try:
            rt.save_tree_projection_after_cell_sync(store, tree=tree)
        except Exception as ex:
            return rt.attach_cell_tree_fields({
                "ok": False,
                "error": f"{type(ex).__name__}: {ex}",
                "tree_id": tree.tree_id,
                "root_id": tree.root_id,
            }, cell_tree, brain_written=False)
        return rt.attach_cell_tree_fields({
            "ok": True,
            "tree_id": tree.tree_id,
            "root_id": tree.root_id,
            "sweep": rt.sweep_tree(tree),
            "tree": tree.model_dump(mode="json"),
        }, cell_tree)

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
        current = rt.get_tree(store, tree_id=tree_id)
        if current is None:
            return {"ok": False, "error": f"tree '{tree_id}' not found"}
        try:
            tree = rt.clone_tree(current)
            rt._decompose_tree(
                tree, tree_id=tree_id, node_id=node_id, children=children
            )
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        try:
            cell_tree = rt.sync_requirement_tree_cell_graph(
                operation="brain.roma_decompose",
                tree=tree,
            )
        except Exception as ex:
            return rt.cell_tree_unavailable_response(
                "brain.roma_decompose", ex, tree_id=tree_id, node_id=node_id,
            )
        try:
            rt.save_tree_projection_after_cell_sync(store, tree=tree)
        except Exception as ex:
            return rt.attach_cell_tree_fields({
                "ok": False,
                "error": f"{type(ex).__name__}: {ex}",
                "tree_id": tree_id,
            }, cell_tree, brain_written=False)
        return rt.attach_cell_tree_fields({
            "ok": True,
            "tree_id": tree_id,
            "sweep": rt.sweep_tree(tree),
            "tree": tree.model_dump(mode="json"),
        }, cell_tree)

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
        current = rt.get_tree(store, tree_id=tree_id)
        if current is None:
            return {"ok": False, "error": f"tree '{tree_id}' not found"}
        try:
            tree = rt.clone_tree(current)
            node = rt._claim_leaf_in_tree(
                tree, tree_id=tree_id, node_id=node_id, agent_id=agent_id
            )
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        try:
            cell_tree = rt.sync_requirement_tree_cell_graph(
                operation="brain.roma_claim",
                tree=tree,
            )
        except Exception as ex:
            return rt.cell_tree_unavailable_response(
                "brain.roma_claim", ex, tree_id=tree_id, node_id=node_id,
            )
        try:
            rt.save_tree_projection_after_cell_sync(store, tree=tree)
        except Exception as ex:
            return rt.attach_cell_tree_fields({
                "ok": False,
                "error": f"{type(ex).__name__}: {ex}",
                "tree_id": tree_id,
                "node_id": node_id,
            }, cell_tree, brain_written=False)
        return rt.attach_cell_tree_fields({
            "ok": True,
            "node": node.model_dump(mode="json"),
        }, cell_tree)

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
            if tree is None:
                raise KeyError(f"tree '{tree_id}' not found")
            if node is None:
                raise KeyError(f"node '{node_id}' not found")
            verdict = convene_court(
                node_id=node_id,
                gate_kind=node.gate_kind,
                gate_spec=node.gate_spec,
                claimed_by=node.claimed_by,
                judged_by=judged_by,
                context=ctx,
                extra_probes=extra,
                require_diligence=require_diligence or node.attempts >= 1,
                leaf_created_at=node.created_at,
                leaf_title=node.title,
                leaf_predicate=node.predicate,
            )
            try:
                candidate = rt.clone_tree(tree)
                updated = rt._set_verdict_in_tree(
                    candidate,
                    tree_id=tree_id,
                    node_id=node_id,
                    verdict=verdict.verdict,
                    judged_by=judged_by,
                    evidence_ref=next(
                        (l.evidence_ref for l in verdict.lenses if l.evidence_ref),
                        None,
                    ),
                )
            except Exception as ex:
                return {"ok": False, "error": f"{type(ex).__name__}: {ex}",
                        "court": verdict.to_dict()}
            try:
                cell_tree = rt.sync_requirement_tree_cell_graph(
                    operation="brain.roma_judge",
                    tree=candidate,
                )
            except Exception as ex:
                return rt.cell_tree_unavailable_response(
                    "brain.roma_judge",
                    ex,
                    tree_id=tree_id,
                    node_id=node_id,
                    court=verdict.to_dict(),
                )
            try:
                rt.save_tree_projection_after_cell_sync(store, tree=candidate)
            except Exception as ex:
                return rt.attach_cell_tree_fields({
                    "ok": False,
                    "error": f"{type(ex).__name__}: {ex}",
                    "court": verdict.to_dict(),
                }, cell_tree, brain_written=False)
            return rt.attach_cell_tree_fields({
                "ok": True,
                "court": verdict.to_dict(),
                "node": updated.model_dump(mode="json"),
            }, cell_tree)
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.roma_server_verify",
        description=(
            "ROMA — SERVER-SIDE re-verify a claimed leaf OFF the contributor's "
            "process. Unlike brain.roma_judge (the in-process court that runs in "
            "the claimant's interpreter), this RE-EXECUTES the leaf's artifact "
            "gate (py_compile|pytest|file_exists) in a FRESH subprocess on the "
            "real disk and returns a SIGNED attestation a forged 'green' cannot "
            "reproduce. The recorded verdict is downgraded to red if its own "
            "attestation does not authenticate. This is the bus-factor-one fix: "
            "a contributor green is re-checked server-side and a forged one "
            "rejected. cdp/manual gates are not re-executable off-process and "
            "honestly return needs_root. Returns {attestation, node, authentic}."
        ),
    )
    def roma_server_verify(
        tree_id: str,
        node_id: str,
        judged_by: str = "roma-server-verifier",
        evidence: Optional[dict[str, Any]] = None,
        require_diligence: bool = False,
        signing_key_ref: Optional[str] = None,
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        if evidence:
            ctx["evidence"] = evidence
        try:
            tree = rt.get_tree(store, tree_id=tree_id)
            if tree is None:
                raise KeyError(f"tree '{tree_id}' not found")
            node = tree.nodes.get(node_id)
            if node is None:
                raise KeyError(f"node '{node_id}' not found")
            att = server_side_verify(
                node_id=node_id,
                gate_kind=node.gate_kind,
                gate_spec=node.gate_spec,
                claimed_by=node.claimed_by,
                judged_by=judged_by,
                context=ctx,
                require_diligence=require_diligence,
                signing_key_ref=signing_key_ref,
            )
            authentic, authentic_reason = verify_attestation(
                att, signing_key_ref=signing_key_ref, require_signed=False,
            )
            record_verdict = att.verdict
            if att.green and not authentic:
                record_verdict = "red"
            try:
                candidate = rt.clone_tree(tree)
                updated = rt._set_verdict_in_tree(
                    candidate,
                    tree_id=tree_id,
                    node_id=node_id,
                    verdict=record_verdict,
                    judged_by=judged_by,
                    evidence_ref=att.evidence_ref,
                )
            except Exception as ex:
                return {"ok": False, "error": f"{type(ex).__name__}: {ex}",
                        "attestation": att.to_dict()}
            try:
                cell_tree = rt.sync_requirement_tree_cell_graph(
                    operation="brain.roma_server_verify",
                    tree=candidate,
                )
            except Exception as ex:
                return rt.cell_tree_unavailable_response(
                    "brain.roma_server_verify",
                    ex,
                    tree_id=tree_id,
                    node_id=node_id,
                    attestation=att.to_dict(),
                    authentic=authentic,
                    authentic_reason=authentic_reason,
                )
            try:
                rt.save_tree_projection_after_cell_sync(store, tree=candidate)
            except Exception as ex:
                return rt.attach_cell_tree_fields({
                    "ok": False,
                    "error": f"{type(ex).__name__}: {ex}",
                    "attestation": att.to_dict(),
                    "authentic": authentic,
                    "authentic_reason": authentic_reason,
                }, cell_tree, brain_written=False)
            return rt.attach_cell_tree_fields({
                "ok": True,
                "attestation": att.to_dict(),
                "node": updated.model_dump(mode="json"),
                "authentic": authentic,
                "authentic_reason": authentic_reason,
            }, cell_tree)
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

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
            tree, authority_source, projection = rt.read_tree_authority_first(
                store, tree_id=tree_id
            )
            if tree is None:
                return {"ok": False, "error": f"tree '{tree_id}' not found"}
            out = {
                "ok": True,
                "authority_source": authority_source,
                **rt.sweep_tree(tree),
            }
            if projection is not None:
                out["cell_tree"] = projection
            return out
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

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
            tree, authority_source, projection = rt.read_tree_authority_first(
                store, tree_id=tree_id
            )
            if tree is None:
                return {"ok": False, "error": f"tree '{tree_id}' not found"}
            leaves = (rt.open_leaves_for_tree(tree) if claimable_only
                      else rt.frontier_for_tree(tree))
        except KeyError as ex:
            return {"ok": False, "error": str(ex)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        out = {
            "ok": True,
            "tree_id": tree_id,
            "authority_source": authority_source,
            "leaves": [n.model_dump(mode="json") for n in leaves],
        }
        if projection is not None:
            out["cell_tree"] = projection
        return out

    @mcp.tool(
        name="brain.roma_list",
        description=(
            "ROMA - list requirement-tree ids from the Universal Cell route "
            "first, with Brain metadata as compatibility fallback."
        ),
    )
    def roma_list() -> dict[str, Any]:
        tree_ids, authority_source, projection = rt.list_trees_authority_first(store)
        out = {
            "ok": True,
            "authority_source": authority_source,
            "trees": tree_ids,
        }
        if projection is not None:
            out["cell_tree_index"] = projection
        return out


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
