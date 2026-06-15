"""FastMCP server exposing the brain as 4 MCP tools.

Per AgDR-0044 Slice 1:
  brain.context           — UserPromptSubmit hook target. Returns skills +
                            facts + wiring + secret refs + setups filtered
                            by scope ACL, formatted as a system-prompt block.
  brain.write             — PostToolUse hook target. Mem0-style ADD/UPDATE/
                            DELETE/NOOP ops against the store, with provenance.
  brain.skill_mint        — Stop hook target. Queues trace for reflexion
                            worker (Voyager + SkillWeaver in Slice 5). Slice 1
                            ships the queue + immediate-mint short-circuit.
  brain.wiring_announce   — SessionStart hook target. Each client declares
                            which MCPs / CLIs / models are on this device.

Transports:
  - stdio    (default; launched per-process by each client)
  - http     (Streamable HTTP; one daemon serves all remote clients)

Run:
  python -m personal_brain.server              # stdio
  python -m personal_brain.server --http 8473  # streamable HTTP
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import (
    ContextResponse,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    SecretRef,
    Skill,
    SkillMintResult,
    Visibility,
    WiringAnnounceRequest,
    WiringAnnounceResponse,
    WiringEntry,
    WriteOp,
    WriteOpType,
    WriteResponse,
)
from .storage import BrainStore, default_brain_path
from .retrieval import retrieve_skills, retrieve_facts


# ─────────────────────── tool implementations ───────────────────────────


def make_context_payload(
    *,
    store: BrainStore,
    prompt: str,
    owner_user: str,
    project_id: Optional[str] = None,
    firm_id: Optional[str] = None,
    cwd: Optional[str] = None,
    k_skills: int = 5,
    k_facts: int = 8,
) -> ContextResponse:
    """Compute the per-prompt brain context — what skills + facts + wiring +
    secret refs to inject into the system prompt for this turn.

    Slice 2: FTS5 candidates + vector cosine rerank + Generative-Agents
    triple-score (α·recency + β·importance + γ·relevance). Slice 7 adds
    bipartite ACL pre-filter.
    """
    t0 = time.perf_counter()
    scope_filter = _scope_filter_for(owner_user, project_id, firm_id)

    skills = retrieve_skills(
        store, prompt,
        owner_user=owner_user, scope_filter=scope_filter, k=k_skills,
    )
    facts = retrieve_facts(
        store, prompt,
        owner_user=owner_user, scope_filter=scope_filter, k=k_facts,
    )
    wiring = store.list_wiring()
    secret_refs = store.list_secret_refs(owner_user, scope_filter=scope_filter)

    # log retrievals (reconsolidation: every read is an implicit edit signal)
    for f in facts:
        store.log_access(owner_user, f.id, purpose="brain.context")
        store.touch_fragment(f.id, success=True)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    injection = _format_injection(skills, facts, wiring, secret_refs)

    return ContextResponse(
        skills=skills,
        facts=facts,
        wiring=wiring,
        secret_refs=secret_refs,
        setups=[],
        injection=injection,
        retrieval_ms=elapsed_ms,
        scope_filter=scope_filter,
    )


def apply_write(
    *,
    store: BrainStore,
    ops: list[WriteOp],
) -> WriteResponse:
    """Apply a batch of memory ops with provenance attached. Mem0-style
    ADD / UPDATE / DELETE / NOOP."""
    return store.apply_write_ops(ops)


def queue_skill_mint(
    *,
    store: BrainStore,
    trace: dict[str, Any],
    outcome: str,
    owner_user: str,
    contributing_agent: str,
    session_id: Optional[str] = None,
) -> SkillMintResult:
    """Receive a trace at Stop time.

    Threshold logic upgraded per AgDR-0044 P1/P2 push:
      R1 — CalibrationState (calibration.py) computes adaptive novelty +
           success floors via Beta-Bernoulli LCB + streaming quantile +
           CUSUM drift detector. Cold-start permissive; tightens over
           observations; resets on drift.
      R2 — echo_trap_decide (exploration.py) layers diversity floor +
           variance gate over the candidate's tool sequence — refuses
           redundant or low-variance mints before they enter the library.

    Calibration state persists to brain_meta under key 'calibration_v1'.
    """
    # Import lazily — these modules are heavier and only needed at mint time
    from .calibration import CalibrationState, adaptive_decide

    if outcome != "success":
        return SkillMintResult(
            queued=False,
            reason="trace not flagged successful — no mint",
            success_score=0.0,
        )

    tool_calls = trace.get("tool_calls", []) or []
    successful = [tc for tc in tool_calls if tc.get("status") == "ok"]
    if len(successful) < 2:
        return SkillMintResult(
            queued=False,
            reason=f"only {len(successful)} successful tool calls — below mint floor (≥2)",
            success_score=len(successful) / max(len(tool_calls), 1),
        )

    # Persist the trace as a Fragment so the reflexion worker can pick it up.
    trace_text = _summarise_trace(trace)
    frag_id = _hash_id("trace", session_id or "", trace_text[:200])
    fragment = Fragment(
        id=frag_id,
        kind=FragmentKind.TRACE,
        text=trace_text,
        scope=Scope.USER,
        visibility=Visibility.PRIVATE,
        owner_user=owner_user,
        provenance=Provenance(
            contributing_agent=contributing_agent,
            contributing_user=owner_user,
            session_id=session_id,
            trace_id=trace.get("trace_id"),
            created_at=datetime.now(timezone.utc),
        ),
        extra={"trace": trace, "outcome": outcome, "queued_for_reflexion": True},
    )
    store.write_fragment(fragment)

    proposed_name = _propose_skill_name(trace)
    novelty = _novelty_estimate(store, trace, owner_user)
    success_score = len(successful) / max(len(tool_calls), 1)

    # R1 — Adaptive calibration gate (replaces fixed novelty>0.25 + success>=0.7)
    calib_json = store.get_meta("calibration_v1")
    if calib_json:
        try:
            calib = CalibrationState.from_json(calib_json)
        except Exception:
            calib = CalibrationState()
    else:
        calib = CalibrationState()

    accept, breakdown = adaptive_decide(
        calib, novelty=novelty, success_score=success_score,
    )
    store.set_meta("calibration_v1", calib.to_json())

    # R2 — Echo Trap pre-flight: refuse if candidate too similar to an
    # existing skill (Voyager diversity floor). Skip when no embeddings
    # available — slice 2 lexical embedder is always available.
    diversity_blocked = False
    diversity_reason = ""
    if accept:
        try:
            from .embeddings import get_embedder
            from .exploration import check_diversity, DiversityCheck
            emb = get_embedder()
            qvec = emb.encode(trace_text[:512])
            existing_skills = store.list_skills(owner_user=owner_user, limit=100)
            existing_pairs = [
                (s.name, emb.encode(s.description + " " + " ".join(s.triggers)))
                for s in existing_skills
            ]
            div = check_diversity(qvec, existing_pairs, cfg=DiversityCheck())
            if div.action == "refuse_redundant":
                diversity_blocked = True
                diversity_reason = (
                    f"echo-trap: {div.reason} (nearest={div.nearest_id})"
                )
            elif div.action == "merge":
                diversity_blocked = True
                diversity_reason = (
                    f"echo-trap merge: identical to '{div.nearest_id}' "
                    f"(cos={div.max_cosine:.3f})"
                )
        except Exception as ex:
            # Embeddings unavailable — degrade silently, calibration alone gates
            diversity_reason = f"diversity check skipped: {ex}"

    will_hone = accept and not diversity_blocked

    # ── REAL MINT (AgDR-0044 §1 wire: skill_mint → reflect_on_trace →
    # record_outcome). Before this, queue_skill_mint persisted a trace and
    # scored the gates but NEVER reflected, so no live trace ever minted a
    # skill and calibration alpha/beta stayed frozen at the 1.0/1.0 prior.
    # Now, when R1+R2 pass, we run the reflexion pipeline inline (Heuristic
    # critic — deterministic, no network) so a real trace mints a real
    # skill, then feed the hone outcome back into calibration so the Beta
    # posterior moves. The ReflexionWorker thread is ALSO fed (for the async
    # path / future LLM critic), but the inline run is what makes the mint
    # observable + verifiable this turn per the ANTI-LIE mandate.
    minted_skill_id: Optional[str] = None
    minted_skill_name: Optional[str] = None
    minted_skill: Optional[Skill] = None
    if will_hone:
        try:
            from .reflexion import reflect_on_trace
            from .workers import get_supervisor

            # Enqueue onto the live worker if the engine is running (async
            # path). Non-fatal if absent.
            sup = get_supervisor(store)
            if sup is not None and sup.reflexion is not None:
                try:
                    from .reflexion import WorkerTask
                    sup.reflexion.enqueue(WorkerTask(
                        trace=trace,
                        owner_user=owner_user,
                        contributing_agent=contributing_agent,
                    ))
                except Exception:
                    pass

            result = reflect_on_trace(
                trace,
                store=store,
                owner_user=owner_user,
                contributing_agent=contributing_agent,
                publish=True,
            )
            if result.accepted and result.skill is not None:
                minted_skill = result.skill
                minted_skill_id = result.skill.id
                minted_skill_name = result.skill.name
                # Calibration outcome: a honed-and-published skill is a
                # "retained" observation → moves alpha; a non-accept (hone
                # failed / validator rejected) moves beta. Either way the
                # posterior leaves 1.0/1.0.
                honed_ok = bool(result.hone.get("ok", True))
                calib.record_outcome(retained=honed_ok)
            else:
                calib.record_outcome(retained=False)
                will_hone = False  # reflexion declined downstream of the gates
            # Persist the moved calibration state (alpha/beta now off prior).
            store.set_meta("calibration_v1", calib.to_json())
        except Exception as ex:
            # Never let a mint failure break the Stop hook. Record the
            # reason; the trace fragment is already persisted for retry.
            diversity_reason = (diversity_reason + f" | mint error: {ex}").strip(" |")

    final_reason = (
        f"trace persisted {frag_id[:12]}…; "
        f"novelty={novelty:.2f} (floor {breakdown['novelty_floor']:.2f}) · "
        f"success={success_score:.2f} (floor {breakdown['success_floor']:.2f}) · "
        f"observed_mints={breakdown['observed_mints']}; "
    )
    if not accept:
        final_reason += f"calibration deny: {breakdown['reason']}"
    elif diversity_blocked:
        final_reason += diversity_reason
    elif minted_skill_id:
        final_reason += (
            f"MINTED real skill '{minted_skill_name}' ({minted_skill_id}) "
            f"via reflexion; calibration α={calib.alpha:.2f} β={calib.beta:.2f}"
        )
    else:
        final_reason += "R1+R2 gates passed; reflexion declined downstream"

    return SkillMintResult(
        queued=True,
        immediate_skill=minted_skill,
        proposed_name=minted_skill_name or proposed_name,
        novelty_score=novelty,
        success_score=success_score,
        will_hone=will_hone,
        reason=final_reason,
    )


def announce_wiring(
    *,
    store: BrainStore,
    req: WiringAnnounceRequest,
    owner_user: str,
) -> WiringAnnounceResponse:
    """Receive a wiring announcement on SessionStart. Updates registry of
    which MCPs / CLIs are reachable on this device.

    Slice 1: simple upsert. Slice 6 adds federation propagation.
    """
    registered = 0
    skipped = 0
    for entry in req.entries:
        entry.device_id = entry.device_id or req.device_id
        try:
            inserted = store.upsert_wiring(entry)
            if inserted:
                registered += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    for ref in req.secret_refs:
        ref.owner_user = ref.owner_user or owner_user
        try:
            store.upsert_secret_ref(ref)
        except Exception:
            pass

    # Scope hints help downstream brain.context calls determine scope_filter
    # without re-asking the client every time.
    return WiringAnnounceResponse(
        registered=registered,
        skipped=skipped,
        revoked=0,
        scope_hint=_infer_scope(req.cwd, req.git_remote),
        project_id_hint=_infer_project_id(req.cwd, req.git_remote),
        firm_id_hint=_infer_firm_id(req.git_remote),
    )


# ─────────────────────── FastMCP server build ──────────────────────────


def build_server(
    *,
    store: Optional[BrainStore] = None,
    db_path: Optional[str | Path] = None,
    default_owner_user: Optional[str] = None,
):
    """Build the FastMCP server with 4 tools attached.

    Returns the FastMCP instance; caller decides which transport to run on
    (stdio via .run() / .run_stdio() or streamable HTTP via .run_http(port)).

    `default_owner_user` is used when clients don't pass an `owner_user`.
    Defaults to $USER / $USERNAME / 'founder'.
    """
    try:
        # CUTOVER 2026-06-03: the brain runs on ArchHub's OWN in-house MCP core
        # — no third-party framework in the data path (founder grievance #1).
        # InHouseMCP is a drop-in for FastMCP's .tool()/.run()/attribute-carrier
        # surface (56 parity tests, e5c3b1e; wire-parity vs memory_gate proven).
        # REVERT = restore `from fastmcp import FastMCP`.
        from .mcp_core import InHouseMCP as FastMCP
    except ImportError as ex:  # pragma: no cover
        raise RuntimeError(
            "personal_brain.mcp_core (in-house MCP core) failed to import"
        ) from ex

    if store is None:
        store = BrainStore.open(db_path)

    # ── Account binding (MAKE-IT-REAL: local brain ⇄ cloud user_id) ────────
    # brain_meta keys that persist the bound cloud owner across daemon
    # restarts. Once `bound_owner_user` is set (via brain.set_owner), every
    # tool that falls back to the default owner resolves to the cloud user_id
    # — so the local brain's fragments/skills are owned by the signed-in
    # account, not by `$USER`/"founder".
    BOUND_OWNER_KEY = "bound_owner_user"
    BOUND_EMAIL_KEY = "bound_owner_email"
    BOUND_NAME_KEY = "bound_owner_display_name"
    BOUND_SET_AT_KEY = "bound_owner_set_at"

    # The env/OS/static fallback, resolved once (does NOT include the bound
    # owner — that is read live from meta on every resolution so a set_owner
    # takes effect in-process without a daemon restart).
    fallback_owner = (
        default_owner_user
        or os.environ.get("BRAIN_OWNER_USER")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "founder"
    )

    def _bound_owner() -> Optional[str]:
        """The persisted cloud owner, or None when unbound. Read from
        brain_meta on EVERY call so a brain.set_owner during the daemon's
        lifetime governs all subsequent default-owner resolutions without a
        restart."""
        try:
            val = store.get_meta(BOUND_OWNER_KEY)
        except Exception:
            return None
        val = (val or "").strip()
        return val or None

    def resolve_default_owner() -> str:
        """Effective default owner: the bound cloud user_id when present,
        else the env/OS/static fallback. Called per-tool-invocation (not
        cached) so binding is live in-process."""
        return _bound_owner() or fallback_owner

    def _owner_source() -> str:
        """Where the current effective owner comes from — for diagnostics."""
        if _bound_owner():
            return "bound"
        if default_owner_user or os.environ.get("BRAIN_OWNER_USER"):
            return "env"
        if os.environ.get("USER") or os.environ.get("USERNAME"):
            return "os"
        return "default"

    mcp = FastMCP("personal-brain")

    @mcp.tool(
        name="brain.context",
        description=(
            "Retrieve the brain's relevant context for a user prompt. "
            "Returns top-K skills + facts + wiring + secret references + "
            "setups filtered by the user's scope ACL, plus a pre-formatted "
            "injection block ready to prepend to the system prompt. "
            "Wire this to UserPromptSubmit (Claude Code) or session-init "
            "instructions (other clients)."
        ),
    )
    def brain_context(
        prompt: str,
        owner_user: Optional[str] = None,
        project_id: Optional[str] = None,
        firm_id: Optional[str] = None,
        cwd: Optional[str] = None,
        k_skills: int = 5,
        k_facts: int = 8,
    ) -> dict[str, Any]:
        owner = owner_user or resolve_default_owner()
        resp = make_context_payload(
            store=store,
            prompt=prompt,
            owner_user=owner,
            project_id=project_id,
            firm_id=firm_id,
            cwd=cwd,
            k_skills=k_skills,
            k_facts=k_facts,
        )
        return resp.model_dump(mode="json")

    @mcp.tool(
        name="brain.write",
        description=(
            "Apply Mem0-style memory ops (ADD/UPDATE/DELETE/NOOP) with "
            "immutable provenance attached. Wire to PostToolUse so the brain "
            "captures every tool outcome as memory in real time. Slice 11: "
            "every non-USER-scope write is gated by acl.can_write_to_scope; "
            "operations that fail ACL are rejected with a typed reason — "
            "the rest of the batch still applies."
        ),
    )
    def brain_write(ops: list[dict[str, Any]]) -> dict[str, Any]:
        from .acl import Identity, Scope as AclScope, can_write_to_scope
        from .firm import current_firm_id, current_seat
        parsed: list[WriteOp] = []
        denied: list[dict[str, Any]] = []

        # Build actor identity from local firm membership
        seat = current_seat(store)
        actor = Identity(
            user_id=(seat.user_id if seat else resolve_default_owner()),
            firm_id=(seat.firm_id if seat else None),
            is_maintainer=False,  # `global` writes are out-of-band
        )

        for raw in ops:
            try:
                op = WriteOp.model_validate(raw)
            except Exception as ex:
                return {"error": f"invalid write op: {ex}", "ops_applied": 0}

            # Slice 11 — ACL gate: every non-USER write checked.
            # User-scope writes pass through (owner-only enforced at search).
            if op.fragment is not None:
                scope_val = (
                    op.fragment.scope.value
                    if hasattr(op.fragment.scope, "value")
                    else str(op.fragment.scope)
                )
                if scope_val != "user":
                    try:
                        target_scope = AclScope(scope_val)
                    except ValueError:
                        denied.append({
                            "op_id": op.fragment.id,
                            "reason": f"unknown scope '{scope_val}'",
                        })
                        continue
                    decision = can_write_to_scope(
                        actor=actor,
                        target_scope=target_scope,
                        target_project_id=op.fragment.project_id,
                        target_firm_id=op.fragment.firm_id,
                    )
                    if not decision.allow:
                        denied.append({
                            "op_id": op.fragment.id,
                            "scope": scope_val,
                            "reason": decision.reason,
                        })
                        continue
                    if decision.redaction_required and scope_val in ("community", "global"):
                        # Community/global writes must go through brain.promote
                        # (which applies redaction) — refuse direct writes.
                        denied.append({
                            "op_id": op.fragment.id,
                            "scope": scope_val,
                            "reason": (
                                f"direct write to '{scope_val}' scope blocked — "
                                "use brain.promote with redaction"
                            ),
                        })
                        continue
            parsed.append(op)

        resp = apply_write(store=store, ops=parsed)
        result = resp.model_dump(mode="json")
        if denied:
            result["acl_denied"] = denied
            result["acl_denied_count"] = len(denied)
        return result

    @mcp.tool(
        name="brain.organize",
        description=(
            "Facet-organize the brain: partition every fragment into a coarse "
            "facet (Capability / Decisions / Memory) by predicate, label each "
            "row's category from extra_json/text (nearest-centroid for "
            "unlabeled Memory rows), MERGE near-duplicates (cosine>=0.95 AND "
            "same subject AND predicate), and ARCHIVE stale traces "
            "(kind=trace, >30d, 0 successes) via valid_until — never deleting "
            "Decisions/Capability. Idempotent; also runs on the sync cadence "
            "via the worker engine. Persists the cluster map to "
            "brain_meta('organize.clusters')."
        ),
    )
    def brain_organize_tool() -> dict[str, Any]:
        from .organize import brain_organize
        owner = resolve_default_owner()
        return brain_organize(store, owner_user=owner)

    @mcp.tool(
        name="brain.reembed",
        description=(
            "Backfill embeddings for every fragment whose vector is "
            "NULL/empty: encode(text+subject+object) with the active embedder "
            "and persist it, stamping brain_meta embed.backend + embed.dim. "
            "Fixes all-NULL embeddings — the top retrieval-quality fix. "
            "Idempotent (skips rows that already have a vector); also runs on "
            "the sync cadence via the worker engine."
        ),
    )
    def brain_reembed_tool() -> dict[str, Any]:
        from .organize import brain_reembed
        return brain_reembed(store)

    @mcp.tool(
        name="brain.promote_skills",
        description=(
            "Promote harvested skill-FRAGMENTS (kind=skill rows, or fact rows "
            "marked source=session-harvest with a skill_name) into PROPER "
            "`skills` rows so retrieval (brain.context / search_skills) can "
            "match + fire them. For each: slugify the human name to the "
            "Skill.name regex (^[a-z][a-z0-9_-]*$, collision-suffixed), build a "
            "Skill (triggers←trigger, requires_mcps←broker_tool, body←steps, "
            "examples, eval_queries synthesized from the description, "
            "scope/visibility/owner + provenance carried from the fragment), "
            "upsert_skill it, then delete the now-duplicated fragment. DEDUPE: "
            "skips (keeps the existing) when a same-slug or near-identical "
            "skill already exists. One-shot + idempotent (a 2nd run promotes 0 "
            "— the fragments are gone). Writes ONLY via in-daemon "
            "upsert_skill/delete_fragment (never raw sqlite). Pass dry_run=true "
            "to preview the slug map + dedupe decisions without mutating."
        ),
    )
    def brain_promote_skills_tool(dry_run: bool = False) -> dict[str, Any]:
        from .organize import promote_skill_fragments
        owner = resolve_default_owner()
        return promote_skill_fragments(store, owner_user=owner, dry_run=dry_run)

    @mcp.tool(
        name="brain.browse",
        description=(
            "READ-ONLY. Assemble the founder-facing visual brain browser: the "
            "decay-weighted 'top of mind' cards, facet lanes (Decisions / "
            "Memory / Capability) as cluster cards with top-3 salient items, "
            "the faded/archived tray, and a learning timeline. Each card is a "
            "plain one-liner + last-used + 'used N times' + a plain 'why is "
            "this here' — raw subject/predicate/object live under details. "
            "The payload includes a `projects` per-project fact census; pass "
            "`project` (e.g. 'P-674') to scope the whole view to one project's "
            "facts. Pass `query` to layer the real retrieval ranker on top "
            "(search results carry facet colour). Never writes; safe to poll."
        ),
    )
    def brain_browse_tool(
        query: Optional[str] = None,
        owner_user: Optional[str] = None,
        project: Optional[str] = None,
    ) -> dict[str, Any]:
        from .organize import brain_browse
        owner = owner_user or resolve_default_owner()
        return brain_browse(store, owner_user=owner, query=query, project=project)

    @mcp.tool(
        name="brain.restore",
        description=(
            "Un-archive a fragment — clear its valid_until so a faded/archived "
            "note rejoins active memory. The inverse of the organize pass's "
            "stale-trace archive; powers the visual browser's 'Restore' button "
            "(MAKE-IT-REAL-NEVER-TRIM). Mutates only through the safe writer; "
            "idempotent. Returns {ok, restored, id}."
        ),
    )
    def brain_restore_tool(fragment_id: str) -> dict[str, Any]:
        from .organize import brain_restore
        return brain_restore(store, fragment_id)

    @mcp.tool(
        name="brain.skill_mint",
        description=(
            "Receive a trace on Stop / SessionEnd. The reflexion worker "
            "scores novelty + success and decides whether to mint a new "
            "skill (Voyager critic + SkillWeaver hone — Slice 5). Slice 1 "
            "queues the trace and returns a SkillMintResult describing the "
            "decision."
        ),
    )
    def brain_skill_mint(
        trace: dict[str, Any],
        outcome: str = "success",
        owner_user: Optional[str] = None,
        contributing_agent: str = "unknown",
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or resolve_default_owner()
        result = queue_skill_mint(
            store=store,
            trace=trace,
            outcome=outcome,
            owner_user=owner,
            contributing_agent=contributing_agent,
            session_id=session_id,
        )
        return result.model_dump(mode="json")

    @mcp.tool(
        name="brain.wiring_announce",
        description=(
            "Announce which MCPs / CLIs / models are configured on this "
            "device, plus which secret references are present. Wire to "
            "SessionStart on every client. Brain uses this to filter skills "
            "by `requires_mcps` so the model never sees a skill it can't run."
        ),
    )
    def brain_wiring_announce(
        device_id: str,
        entries: Optional[list[dict[str, Any]]] = None,
        secret_refs: Optional[list[dict[str, Any]]] = None,
        cwd: Optional[str] = None,
        git_remote: Optional[str] = None,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or resolve_default_owner()
        # Coerce dicts → WiringEntry / SecretRef with sane defaults.
        wiring_entries: list[WiringEntry] = []
        for raw in entries or []:
            raw.setdefault("device_id", device_id)
            try:
                wiring_entries.append(WiringEntry.model_validate(raw))
            except Exception:
                continue
        sec_refs: list[SecretRef] = []
        for raw in secret_refs or []:
            raw.setdefault("owner_user", owner)
            try:
                sec_refs.append(SecretRef.model_validate(raw))
            except Exception:
                continue

        req = WiringAnnounceRequest(
            device_id=device_id,
            entries=wiring_entries,
            secret_refs=sec_refs,
            cwd=cwd,
            git_remote=git_remote,
        )
        resp = announce_wiring(store=store, req=req, owner_user=owner)
        return resp.model_dump(mode="json")

    @mcp.tool(
        name="brain.promote",
        description=(
            "Promote a fragment from its current scope to a higher one "
            "(user→project→firm→community→global). Required redaction is "
            "applied automatically when target scope crosses the privacy "
            "boundary (community/global). ACL + redaction enforced per "
            "arXiv 2505.18279. Returns the promoted fragment id + audit "
            "record."
        ),
    )
    def brain_promote(
        fragment_id: str,
        target_scope: str,
        owner_user: Optional[str] = None,
        target_project_id: Optional[str] = None,
        target_firm_id: Optional[str] = None,
        target_community_id: Optional[str] = None,
        is_maintainer: bool = False,
    ) -> dict[str, Any]:
        from .acl import (  # local import to avoid cycles
            Identity, Scope as AclScope, can_promote,
        )
        from .redaction import redact_fragment

        actor = Identity(
            user_id=owner_user or resolve_default_owner(),
            project_id=target_project_id,
            firm_id=target_firm_id,
            community_subscriptions=(
                [target_community_id] if target_community_id else []
            ),
            is_maintainer=is_maintainer,
        )

        # Look up source fragment
        source = store.get_fragment(fragment_id)
        if source is None:
            return {"error": f"fragment '{fragment_id}' not found",
                    "promoted": False}

        target = AclScope(target_scope)
        decision = can_promote(
            source.model_dump(mode="json"),
            actor=actor,
            target_scope=target,
            target_project_id=target_project_id,
            target_firm_id=target_firm_id,
            target_community_id=target_community_id,
        )
        if not decision.allow:
            return {"error": decision.reason, "promoted": False}

        # Build promoted copy (new id derived from source + target scope)
        import hashlib
        source_dict = source.model_dump(mode="json")
        if decision.redaction_required:
            promoted_dict, report = redact_fragment(source_dict)
        else:
            promoted_dict, report = source_dict, None

        new_id = (
            "promoted-"
            + hashlib.sha256(
                f"{source.id}|{target.value}".encode("utf-8")
            ).hexdigest()[:16]
        )
        promoted_dict["id"] = new_id
        promoted_dict["scope"] = target.value
        if target == AclScope.PROJECT:
            promoted_dict["visibility"] = "shared_project"
            promoted_dict["project_id"] = target_project_id
        elif target == AclScope.FIRM:
            promoted_dict["visibility"] = "shared_company"
            promoted_dict["firm_id"] = target_firm_id
        elif target == AclScope.COMMUNITY:
            promoted_dict["visibility"] = "shared_public"
        elif target == AclScope.GLOBAL:
            promoted_dict["visibility"] = "canonical"

        # Persist via WriteOp path (keeps Mem0-style consistency)
        from .models import Fragment as _Fragment, WriteOp, WriteOpType
        # Coerce dict → Fragment for validation
        promoted_fragment = _Fragment.model_validate(promoted_dict)
        op = WriteOp(op=WriteOpType.ADD, fragment=promoted_fragment)
        resp = store.apply_write_ops([op])

        # Audit log
        store.log_access(
            actor.user_id, source.id,
            purpose=f"promote→{target.value}",
        )
        store.log_access(
            actor.user_id, new_id,
            purpose=f"promote_target",
        )

        return {
            "promoted": True,
            "source_id": source.id,
            "promoted_id": new_id,
            "target_scope": target.value,
            "redaction_required": decision.redaction_required,
            "redaction_report": (
                {
                    "policy_id": report.policy_id,
                    "findings_count": len(report.findings),
                    "findings": report.findings,
                } if report else None
            ),
            "write_ms": resp.write_ms,
            "audit_logged": True,
        }

    # ─────────────────── firm identity (Slice 9) ────────────────────

    @mcp.tool(
        name="brain.firm_create",
        description=(
            "Create a new firm on this device. Caller becomes the root "
            "admin. Returns the firm identity (firm_id + name + public "
            "key). The private key is held LOCAL only — other devices "
            "join via signed invite tokens. Idempotent: re-running "
            "without `force=true` returns the existing firm."
        ),
    )
    def brain_firm_create(
        name: str,
        created_by: Optional[str] = None,
        force: bool = False,
    ) -> dict[str, Any]:
        from .firm import create_firm, current_firm
        existing = current_firm(store)
        if existing is not None and not force:
            return {
                "ok": True, "already_exists": True,
                "firm_id": existing.firm_id, "name": existing.name,
                "root_pub": existing.root_pub,
            }
        identity = create_firm(
            store, name=name, created_by=created_by or resolve_default_owner(),
        )
        return {
            "ok": True,
            "firm_id": identity.firm_id, "name": identity.name,
            "root_pub": identity.root_pub,
            "is_admin": True,
        }

    @mcp.tool(
        name="brain.firm_invite_create",
        description=(
            "Create a signed invite token to add a teammate to the "
            "current firm. Only the firm admin (the device that holds "
            "root_priv) can issue tokens. Token is a base64url payload "
            "+ ed25519 signature; expires in `ttl_hours`. Share by "
            "any channel (paste, QR, message); recipient passes to "
            "`brain.firm_invite_accept`."
        ),
    )
    def brain_firm_invite_create(
        role: str = "seat",
        ttl_hours: int = 24,
    ) -> dict[str, Any]:
        from .firm import create_invite_token
        try:
            envelope = create_invite_token(
                store, role=role, ttl_hours=ttl_hours,
            )
            return {"ok": True, "token": envelope, "role": role,
                     "ttl_hours": ttl_hours}
        except RuntimeError as ex:
            return {"ok": False, "error": str(ex)}

    @mcp.tool(
        name="brain.firm_invite_accept",
        description=(
            "Accept an invite token to join a firm. Verifies signature "
            "+ expiry; on success materialises firm identity (public "
            "key only — not admin priv) and records the local seat. "
            "Idempotent: re-running with the same token is a no-op."
        ),
    )
    def brain_firm_invite_accept(
        token: str,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from .firm import accept_invite_token
        try:
            seat = accept_invite_token(
                store, envelope=token, user_id=user_id or resolve_default_owner(),
            )
            return {
                "ok": True, "firm_id": seat.firm_id, "user_id": seat.user_id,
                "role": seat.role, "invited_by": seat.invited_by,
            }
        except RuntimeError as ex:
            return {"ok": False, "error": str(ex)}

    @mcp.tool(
        name="brain.firm_seats",
        description=(
            "List all seats in the current firm (synced via the firm-"
            "scope graph). Returns [] when not in a firm."
        ),
    )
    def brain_firm_seats() -> dict[str, Any]:
        from .firm import current_firm, list_seats
        f = current_firm(store)
        if f is None:
            return {"ok": True, "firm_id": None, "seats": []}
        seats = list_seats(store)
        return {
            "ok": True, "firm_id": f.firm_id, "firm_name": f.name,
            "seats": [
                {"user_id": s.user_id, "role": s.role,
                  "joined_at": s.joined_at, "invited_by": s.invited_by}
                for s in seats
            ],
        }

    @mcp.tool(
        name="brain.firm_leave",
        description=(
            "Leave the current firm on this device. The seat record "
            "remains visible on other seats until next sync, then gets "
            "pruned."
        ),
    )
    def brain_firm_leave() -> dict[str, Any]:
        from .firm import leave_firm
        leave_firm(store)
        return {"ok": True}

    # ─────────────────── community (Slice 14 MCP wires) ────────────────

    @mcp.tool(
        name="brain.community_subscribe",
        description=(
            "Subscribe to a peer firm's federation outbox. Records a "
            "Subscription (actor_url + display_name) in the local brain "
            "store; the CommunityPoller subsequently pulls "
            "`<actor_url>/outbox` activities, runs reputation + redaction "
            "gates, and imports accepted patterns at scope=community. "
            "Idempotent — re-subscribing overwrites the display_name."
        ),
    )
    def brain_community_subscribe(
        actor_url: str,
        display_name: str = "",
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        from . import community as _community
        owner = owner_user or resolve_default_owner()
        sub = _community.subscribe(
            store,
            actor_url=actor_url,
            display_name=display_name,
            owner_user=owner,
        )
        return {
            "ok": True,
            "subscription": {
                "actor_url": sub.actor_url,
                "display_name": sub.display_name,
                "subscribed_at": sub.subscribed_at,
            },
        }

    @mcp.tool(
        name="brain.community_unsubscribe",
        description=(
            "Remove a community subscription by actor_url. Returns "
            "`removed: True` when the row existed; `False` when no such "
            "subscription was registered. Previously-imported community-"
            "scope fragments stay — only the polling link is severed."
        ),
    )
    def brain_community_unsubscribe(actor_url: str) -> dict[str, Any]:
        from . import community as _community
        removed = _community.unsubscribe(store, actor_url)
        return {"ok": True, "removed": bool(removed)}

    @mcp.tool(
        name="brain.community_list",
        description=(
            "List all peer firm outboxes this device currently subscribes "
            "to. Each entry includes display_name, subscribed_at, and "
            "last_poll_at + last_accepted / quarantined / rejected counters "
            "updated by the CommunityPoller after every tick."
        ),
    )
    def brain_community_list() -> dict[str, Any]:
        from . import community as _community
        subs = _community.list_subscriptions(store)
        return {
            "ok": True,
            "subscriptions": [
                {
                    "actor_url": s.actor_url,
                    "display_name": s.display_name,
                    "subscribed_at": s.subscribed_at,
                    "last_poll_at": s.last_poll_at,
                    "last_accepted": s.last_accepted,
                    "last_quarantined": s.last_quarantined,
                    "last_rejected": s.last_rejected,
                }
                for s in subs
            ],
        }

    @mcp.tool(
        name="brain.community_poll_now",
        description=(
            "Manually trigger one CommunityPoller.tick() across all current "
            "subscriptions. Lazily instantiates a singleton poller (with a "
            "FederationDriver bound to the local firm_id) on first call; "
            "subsequent calls reuse it. Returns a list of PollResult dicts "
            "(activities_fetched, accepted, quarantined, rejected, error)."
        ),
    )
    def brain_community_poll_now() -> dict[str, Any]:
        from dataclasses import asdict as _asdict
        poller = _get_or_create_community_poller(store)
        results = poller.tick()
        return {"ok": True, "results": [_asdict(r) for r in results]}

    # ───────────── multi-device community (create / join / converge) ──────
    # Distinct from the federation `community_*` subscription tools above:
    # these create a community the user OWNS + a second device JOINS via a
    # signed join-code, then both converge COMMUNITY-scope fragments through
    # the shared transport (owned Speckle server OR cloud relay).

    @mcp.tool(
        name="brain.community_create",
        description=(
            "Create a multi-device community on this device. The caller "
            "becomes the OWNER (holds the signing key locally). Writes a "
            "COMMUNITY-scope `community` fragment + an owner `community_"
            "member` fragment, so brain.community_groups + brain.community_"
            "list are immediately non-empty. `transport_kind` is one of "
            "'disk' (offline JSON snapshot — default), 'cloud_relay' "
            "(ArchHub /v1/brain/sync replica, the user's own token), or "
            "'speckle' (the user's OWNED local Speckle server). "
            "`transport_base_url` points at the relay/server (e.g. "
            "http://localhost:3000 for an owned Speckle server). Idempotent "
            "only by name collision is NOT enforced — call once."
        ),
    )
    def brain_community_create(
        name: str,
        created_by: Optional[str] = None,
        transport_kind: str = "disk",
        transport_base_url: str = "",
        transport_note: str = "",
    ) -> dict[str, Any]:
        from . import community_groups as _cg
        tconf = _cg.TransportConfig(
            kind=transport_kind or "disk",
            base_url=transport_base_url or "",
            note=transport_note or "",
        )
        community = _cg.create_community(
            store, name=name,
            created_by=created_by or resolve_default_owner(),
            transport=tconf,
        )
        return {
            "ok": True,
            "community": community.to_safe_dict(),
            "is_owner": True,
        }

    @mcp.tool(
        name="brain.community_join_code",
        description=(
            "Create a signed join-code (+ archhub:// URL) for the CURRENT "
            "community so a SECOND device can join. Only the owner (device "
            "holding the signing key) can issue one. The code is a "
            "base64url payload + signature carrying the community id, name, "
            "owner public key, AND the transport config — so the joining "
            "device knows where to converge, fully offline-verifiable. "
            "Expires in `ttl_hours` (default 7 days). Returns {token, url}."
        ),
    )
    def brain_community_join_code(
        role: str = "member",
        ttl_hours: int = 168,
    ) -> dict[str, Any]:
        from . import community_groups as _cg
        try:
            token = _cg.create_join_code(store, role=role, ttl_hours=ttl_hours)
            return {
                "ok": True,
                "token": token,
                "url": _cg.join_url(token),
                "role": role,
                "ttl_hours": ttl_hours,
            }
        except RuntimeError as ex:
            return {"ok": False, "error": str(ex)}

    @mcp.tool(
        name="brain.community_join",
        description=(
            "Join a community on THIS device using a join-code (the bare "
            "token OR the archhub://community/join?code=... URL). Verifies "
            "signature + expiry offline, materialises membership, writes a "
            "COMMUNITY-scope `community_member` fragment so the owner sees "
            "this device after the next sync, and adopts the community's "
            "transport config. Idempotent: re-joining with the same code "
            "refreshes the member record. Returns the joined community."
        ),
    )
    def brain_community_join(
        code: str,
        member_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from . import community_groups as _cg
        try:
            community = _cg.join_community(
                store, envelope=code,
                member_id=member_id or resolve_default_owner(),
            )
            return {
                "ok": True,
                "community": community.to_safe_dict(),
                "is_owner": False,
            }
        except RuntimeError as ex:
            return {"ok": False, "error": str(ex)}

    @mcp.tool(
        name="brain.community_groups",
        description=(
            "List every multi-device community this device knows about "
            "(from synced COMMUNITY-scope `community` fragments). Each entry "
            "includes id, name, transport config, and this device's role. "
            "Returns [] when this device has not created or joined any "
            "community. This is the multi-device-group list — distinct from "
            "brain.community_list, which lists peer-firm outbox subscriptions."
        ),
    )
    def brain_community_groups() -> dict[str, Any]:
        from . import community_groups as _cg
        comms = _cg.list_communities(store)
        current = _cg.current_community(store)
        return {
            "ok": True,
            "current_community_id": current.community_id if current else None,
            "communities": [c.to_safe_dict() for c in comms],
        }

    @mcp.tool(
        name="brain.community_members",
        description=(
            "List the members (devices/users) of the current community "
            "from synced COMMUNITY-scope `community_member` fragments. Two "
            "devices on the same community see each other here after a sync "
            "cycle. Returns [] when not in a community."
        ),
    )
    def brain_community_members(
        community_id: Optional[str] = None,
    ) -> dict[str, Any]:
        from . import community_groups as _cg
        members = _cg.list_members(store, community_id=community_id)
        cid = community_id or _cg.current_community_id(store)
        return {
            "ok": True,
            "community_id": cid,
            "members": [
                {
                    "member_id": m.member_id,
                    "role": m.role,
                    "joined_at": m.joined_at,
                    "invited_by": m.invited_by,
                }
                for m in members
            ],
        }

    @mcp.tool(
        name="brain.community_set_transport",
        description=(
            "Point the current community at a transport so its devices "
            "converge: 'disk' (offline JSON snapshot), 'cloud_relay' "
            "(ArchHub /v1/brain/sync), or 'speckle' (owned local Speckle "
            "server). Use this after starting an owned server to upgrade an "
            "offline community to live multi-device sync. Re-issue a "
            "join-code afterward so new devices pick up the new transport."
        ),
    )
    def brain_community_set_transport(
        transport_kind: str,
        transport_base_url: str = "",
        transport_note: str = "",
    ) -> dict[str, Any]:
        from . import community_groups as _cg
        tconf = _cg.TransportConfig(
            kind=transport_kind or "disk",
            base_url=transport_base_url or "",
            note=transport_note or "",
        )
        community = _cg.set_transport(store, tconf)
        if community is None:
            return {"ok": False, "error": "no community on this device"}
        return {"ok": True, "community": community.to_safe_dict()}

    @mcp.tool(
        name="brain.community_leave",
        description=(
            "Leave the current multi-device community on this device. "
            "Tombstones this device's member fragment so the roster "
            "converges on other devices after their next sync. The "
            "community record + any COMMUNITY-scope fragments stay until "
            "pruned. Reversible: re-join with a fresh join-code."
        ),
    )
    def brain_community_leave() -> dict[str, Any]:
        from . import community_groups as _cg
        _cg.leave_community(store)
        return {"ok": True}

    @mcp.tool(
        name="brain.community_owned_server",
        description=(
            "Report whether an OWNED Speckle server (no external account) is "
            "reachable / startable, so a community can converge through it. "
            "Checks the port (default http://localhost:3000) then Docker. "
            "Returns {reachable, docker_available, can_start, code, message}. "
            "code is 'running' (live), 'ready_to_start' (Docker up — start it "
            "from the desktop), or 'docker_missing' (install + start Docker "
            "Desktop first). Does NOT start anything — that is the desktop's "
            "`docker compose up`. Pass `base_url` to check a specific server."
        ),
    )
    def brain_community_owned_server(
        base_url: str = "http://localhost:3000",
    ) -> dict[str, Any]:
        from . import owned_server as _os
        report = _os.readiness(base_url or "http://localhost:3000")
        return {"ok": True, **report}

    # ─────────────── account binding (local brain ⇄ cloud user) ──────────
    @mcp.tool(
        name="brain.set_owner",
        description=(
            "Bind this local brain to a signed-in cloud account. Persists the "
            "cloud `user_id` (+ optional email / display_name) to brain_meta "
            "so every fragment, skill, and wiring write that falls back to the "
            "default owner is owned by that user_id — not by $USER / 'founder'. "
            "Takes effect IN-PROCESS immediately (no daemon restart) and "
            "survives restarts (persisted). Call this right after cloud "
            "sign-in. Returns {ok, owner_user, previously}."
        ),
    )
    def brain_set_owner(
        user_id: str,
        email: str = "",
        display_name: str = "",
    ) -> dict[str, Any]:
        uid = (user_id or "").strip()
        if not uid:
            return {
                "ok": False,
                "error": "user_id must be a non-empty string",
                "owner_user": resolve_default_owner(),
            }
        previously = _bound_owner()  # None when this is the first bind
        now_iso = datetime.now(timezone.utc).isoformat()
        store.set_meta(BOUND_OWNER_KEY, uid)
        store.set_meta(BOUND_EMAIL_KEY, (email or "").strip())
        store.set_meta(BOUND_NAME_KEY, (display_name or "").strip())
        store.set_meta(BOUND_SET_AT_KEY, now_iso)
        return {
            "ok": True,
            "owner_user": uid,
            "bound": True,
            "previously": previously,
            "email": (email or "").strip(),
            "display_name": (display_name or "").strip(),
            "set_at": now_iso,
        }

    @mcp.tool(
        name="brain.get_owner",
        description=(
            "Report the current effective brain owner and where it comes "
            "from. Returns {owner_user, bound, email, display_name, source} "
            "— source is 'bound' (cloud user_id persisted via set_owner), "
            "'env' (BRAIN_OWNER_USER / build default), 'os' ($USER/$USERNAME), "
            "or 'default' ('founder')."
        ),
    )
    def brain_get_owner() -> dict[str, Any]:
        bound = _bound_owner()
        return {
            "ok": True,
            "owner_user": resolve_default_owner(),
            "bound": bound is not None,
            "email": (store.get_meta(BOUND_EMAIL_KEY) or "") if bound else "",
            "display_name": (store.get_meta(BOUND_NAME_KEY) or "") if bound else "",
            "set_at": (store.get_meta(BOUND_SET_AT_KEY) or "") if bound else "",
            "source": _owner_source(),
            "fallback_owner": fallback_owner,
        }

    @mcp.tool(
        name="brain.clear_owner",
        description=(
            "Unbind the cloud account from this local brain (sign-out). "
            "Removes the persisted owner binding so the default owner reverts "
            "to env / OS / 'founder'. The brain DATA stays — only the binding "
            "is cleared; previously-bound fragments keep their owner_user. "
            "Returns {ok, owner_user (new effective), previously}."
        ),
    )
    def brain_clear_owner() -> dict[str, Any]:
        previously = _bound_owner()
        for key in (
            BOUND_OWNER_KEY,
            BOUND_EMAIL_KEY,
            BOUND_NAME_KEY,
            BOUND_SET_AT_KEY,
        ):
            try:
                store.set_meta(key, "")
            except Exception:
                pass
        return {
            "ok": True,
            "owner_user": resolve_default_owner(),
            "bound": False,
            "previously": previously,
            "cleared": previously is not None,
        }

    @mcp.tool(
        name="brain.health",
        description="Diagnostic: counts of skills, facts, wiring entries, brain db path.",
    )
    def brain_health() -> dict[str, Any]:
        # Engine liveness (AgDR-0044 §1 prevent-clause): report whether the
        # background workers are actually ALIVE, not just whether tools are
        # registered. A daemon with tools but no engine is the dormant-brain
        # failure this surfaces.
        engine: dict[str, Any] = {"started": False, "workers": {}}
        try:
            from .workers import get_supervisor
            sup = get_supervisor(store)
            if sup is not None:
                engine = sup.status()
        except Exception as ex:
            engine = {"started": False, "error": f"{type(ex).__name__}: {ex}"}

        # Calibration posterior — proves the self-tightening loop has moved
        # off the 1.0/1.0 prior once a real trace has been reflected.
        calibration: dict[str, Any] = {}
        try:
            import json as _json
            raw = store.get_meta("calibration_v1")
            if raw:
                c = _json.loads(raw)
                calibration = {
                    "alpha": c.get("alpha"),
                    "beta": c.get("beta"),
                    "mints_proposed": c.get("mints_proposed"),
                    "mints_accepted": c.get("mints_accepted"),
                    "observed_mints": int(
                        max(0, (c.get("alpha", 1.0) + c.get("beta", 1.0) - 2))
                    ),
                }
        except Exception:
            pass

        # Account binding — surface the effective owner + whether it is
        # bound to a cloud user_id so the desktop/founder can see the link
        # is live (MAKE-IT-REAL: local brain ⇄ cloud account).
        effective_owner = resolve_default_owner()
        is_bound = _bound_owner() is not None

        # Personal cross-device cloud sync — surface whether this device is
        # signed in (token present) + the last tick outcome, so the founder
        # can SEE the personal brain is converging across devices (or that it
        # is inert pending sign-in). Never raises; degrades to a minimal dict.
        personal_sync: dict[str, Any] = {"signed_in": False}
        try:
            from .cloud_config import load_cloud_config
            import json as _json2
            _cfg = load_cloud_config()
            personal_sync = {
                "signed_in": _cfg.is_signed_in,
                "cloud": _cfg.redacted(),
                "since_hlc": store.get_meta("personal_cloud_sync.since_hlc") or "",
                "last_sync_ts": store.get_meta("personal_cloud_sync.last_sync_ts") or "",
                "error_count": int(store.get_meta("personal_cloud_sync.error_count") or 0),
            }
            _lr = store.get_meta("personal_cloud_sync.last_result_json")
            if _lr:
                try:
                    personal_sync["last_result"] = _json2.loads(_lr)
                except Exception:
                    pass
        except Exception as ex:
            personal_sync = {"signed_in": False,
                             "error": f"{type(ex).__name__}: {ex}"}

        return {
            "ok": True,
            "version": "0.1.0",
            "db_path": str(store.path),
            "skills": store.count_skills(),
            "facts": store.count_fragments(Scope.USER) + store.count_fragments(Scope.PROJECT),
            "wiring_active": len(store.list_wiring()),
            "owner_user_default": effective_owner,
            "owner": {
                "owner_user": effective_owner,
                "bound": is_bound,
                "source": _owner_source(),
                "email": (store.get_meta(BOUND_EMAIL_KEY) or "") if is_bound else "",
            },
            "engine": engine,
            "calibration": calibration,
            "personal_sync": personal_sync,
        }

    # ── Content ecosystem tools (CONTENT-ECOSYSTEM-2026-05-26.md) ──────
    @mcp.tool(
        name="brain.skill_export",
        description=(
            "Export skills as markdown for static-site builds. "
            "scope: 'community'|'firm'|'project'|'user'|'global'. "
            "Returns list of {id, name, description, body, scope, "
            "reputation, contributor} dicts."
        ),
    )
    def brain_skill_export(
        scope: str = "community",
        limit: int = 100,
    ) -> dict[str, Any]:
        try:
            scope_enum = Scope(scope)
        except ValueError:
            return {"ok": False, "error": f"invalid scope: {scope}"}
        skills = store.list_skills(scope=scope_enum, limit=limit) \
            if hasattr(store, "list_skills") else []
        out = []
        for sk in skills:
            out.append({
                "id": sk.id,
                "name": sk.name,
                "description": sk.description,
                "body": sk.body,
                "scope": sk.scope.value if hasattr(sk.scope, "value") else str(sk.scope),
                "triggers": list(sk.triggers or []),
                "requires_mcps": list(sk.requires_mcps or []),
                "examples": list(sk.examples or []),
                "contributor": sk.owner_user,
                "firm_id": getattr(sk, "firm_id", None),
            })
        return {
            "ok": True,
            "count": len(out),
            "scope": scope,
            "skills": out,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

    @mcp.tool(
        name="brain.find_similar",
        description=(
            "Brain #31 multimodal (founder ask 2026-05-26): rank stored "
            "IMAGE / GEOMETRY fragments by similarity to a query. Accepts "
            "query_phash (hex string) and/or query_embedding (list of "
            "floats). Returns up to `k` hits with phash_distance + "
            "embedding_cosine + combined rank_score. Defaults to USER scope; "
            "kinds default to [IMAGE, GEOMETRY]."
        ),
    )
    def brain_find_similar(
        query_phash: Optional[str] = None,
        query_embedding: Optional[list[float]] = None,
        scopes: Optional[list[str]] = None,
        kinds: Optional[list[str]] = None,
        k: int = 5,
        max_phash: int = 50,
        max_candidates: int = 500,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        from .similarity import find_similar as _find_similar
        from .models import Scope as _S, FragmentKind as _K
        try:
            scope_filter = [_S(s) for s in (scopes or ["user"])]
        except ValueError as ex:
            return {"ok": False, "error": f"invalid scope: {ex}"}
        kind_filter = None
        if kinds:
            try:
                kind_filter = [_K(k_) for k_ in kinds]
            except ValueError as ex:
                return {"ok": False, "error": f"invalid kind: {ex}"}
        if not query_phash and not query_embedding:
            return {"ok": False, "error": "need query_phash or query_embedding"}
        try:
            hits = _find_similar(
                store,
                query_phash=query_phash,
                query_embedding=query_embedding,
                kinds=kind_filter,
                scope_filter=scope_filter,
                owner_user=owner_user or resolve_default_owner(),
                k=int(k),
                max_candidates=int(max_candidates),
                max_phash=int(max_phash),
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {
            "ok": True,
            "count": len(hits),
            "hits": [
                {
                    "id": h.fragment.id,
                    "kind": h.fragment.kind.value,
                    "scope": h.fragment.scope.value,
                    "text": h.fragment.text,
                    "perceptual_hash": h.fragment.perceptual_hash,
                    "blob_path": h.fragment.blob_path,
                    "phash_distance": h.phash_distance,
                    "embedding_cosine": h.embedding_cosine,
                    "rank_score": round(h.rank_score, 4),
                }
                for h in hits
            ],
        }

    @mcp.tool(
        name="brain.dataset_export",
        description=(
            "Brain #32 (founder ask 2026-05-26): export fragments as a "
            "HuggingFace-style training dataset. Writes JSONL primary + "
            "optional parquet (if pyarrow installed) + manifest.json. "
            "Defaults to USER scope only — never escalates without "
            "explicit scope_filter. Used to seed collective model "
            "training (Brain #33 north star)."
        ),
    )
    def brain_dataset_export(
        out_dir: str,
        dataset_name: str = "brain-facts",
        scopes: Optional[list[str]] = None,
        kinds: Optional[list[str]] = None,
        since: Optional[str] = None,
        limit: int = 10_000,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        from pathlib import Path as _P
        from . import dataset_export as _de
        from .models import Fragment as _F, FragmentKind, Scope as _S

        try:
            scope_filter = [_S(s) for s in (scopes or ["user"])]
        except ValueError as ex:
            return {"ok": False, "error": f"invalid scope: {ex}"}
        kind_filter = None
        if kinds:
            try:
                kind_filter = [FragmentKind(k) for k in kinds]
            except ValueError as ex:
                return {"ok": False, "error": f"invalid kind: {ex}"}
        try:
            manifest = _de.export_fragments(
                store,
                _P(out_dir),
                dataset_name=dataset_name,
                scope_filter=scope_filter,
                kinds=kind_filter,
                since=since,
                limit=int(limit),
                owner_user=owner_user or resolve_default_owner(),
            )
            return manifest
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.fanout_export",
        description=(
            "Slice-17 cloud-fanout export: return RAW fragment rows for the "
            "given scopes, shaped for POST /v1/brain/sync (the cloud replica "
            "fanout). Unlike brain.dataset_export — which routes COMMUNITY/"
            "GLOBAL to differentially-private AGGREGATES for model-training — "
            "this is the multi-device CONVERGENCE path: USER + FIRM + "
            "COMMUNITY raw rows that ride the shared cloud replicas so a "
            "teammate / second device receives them (per community_groups.py: "
            "COMMUNITY multi-device groups converge raw, keyed by "
            "community_id). USER rows are still gated to the owner; the cloud "
            "keeps USER private per account. Each row carries its HLC (from "
            "provenance.hlc, else a fresh device-clock tick) so the cloud's "
            "last-writer-wins CRDT merge is correct + idempotent. NEVER emits "
            "GLOBAL raw rows (that scope stays DP-aggregate only). Returns "
            "{ok, fragments:[...], count, scopes}."
        ),
    )
    def brain_fanout_export(
        scopes: Optional[list[str]] = None,
        owner_user: Optional[str] = None,
        limit: int = 10_000,
    ) -> dict[str, Any]:
        from .models import Scope as _S
        from .hlc import device_clock as _device_clock
        # Default to the three convergence scopes. GLOBAL is refused — it is
        # collective-class (DP-aggregate only), never raw multi-device sync.
        requested = scopes or ["user", "firm", "community"]
        try:
            scope_filter = [_S(s) for s in requested]
        except ValueError as ex:
            return {"ok": False, "error": f"invalid scope: {ex}"}
        if any(s == _S.GLOBAL for s in scope_filter):
            return {"ok": False,
                    "error": "global scope is DP-aggregate only — "
                             "use brain.dataset_export"}
        owner = owner_user or resolve_default_owner()
        try:
            frags = store.list_fragments(
                scope_filter=scope_filter,
                owner_user=owner,
                limit=int(limit),
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        clock = _device_clock()

        def _hlc_str(raw: Any) -> str:
            """Normalise an HLC to a FIXED-WIDTH 16-hex string so the cloud's
            lexicographic `excluded.hlc > fragments.hlc` compare matches the
            packed-int numeric order. provenance.hlc is a packed 64-bit int
            (sync.stamp_with_hlc); a missing one gets a fresh device tick."""
            if isinstance(raw, int):
                return f"{raw:016x}"
            if isinstance(raw, str) and raw:
                # Already a string HLC — keep as-is (assumed comparable).
                return raw
            return f"{clock.tick():016x}"

        out: list[dict[str, Any]] = []
        for f in frags:
            prov = f.provenance
            hlc = _hlc_str(prov.hlc if prov else None)
            scope_val = f.scope.value if hasattr(f.scope, "value") else str(f.scope)
            out.append({
                "id": f.id,
                "kind": f.kind.value if hasattr(f.kind, "value") else str(f.kind),
                "text": f.text or "",
                "subject": f.subject,
                "predicate": f.predicate,
                "object": f.object,
                "scope": scope_val,
                "visibility": (f.visibility.value
                               if hasattr(f.visibility, "value")
                               else str(f.visibility)),
                "owner_user": f.owner_user or owner,
                "project_id": f.project_id,
                "firm_id": f.firm_id,
                "confidence": (f.confidence.value
                               if hasattr(f.confidence, "value")
                               else str(f.confidence)),
                "extra": dict(f.extra or {}),
                "hlc": hlc,
            })
        return {"ok": True, "fragments": out, "count": len(out),
                "scopes": [s.value for s in scope_filter]}

    @mcp.tool(
        name="brain.fanout_apply",
        description=(
            "Slice-17 cloud-fanout INBOUND merge: write FIRM/COMMUNITY "
            "fragment rows pulled from the cloud replica back into the local "
            "brain. This is the receive half of the fanout — a device pulls "
            "the merged firm/community delta (other devices' / teammates' "
            "facts) and lands it locally. These rows ALREADY crossed the "
            "promote/redaction gate on the contributor's machine, so — exactly "
            "like sync_worker._write_remote_fragment_into_store — they are "
            "written straight via the store's CRDT upsert, NOT re-gated "
            "through brain.write/brain.promote (which would refuse a direct "
            "community write). Merge is last-writer-wins by HLC + idempotent: "
            "a row whose local copy has an equal-or-newer HLC is skipped, so "
            "re-pulling the same delta is a no-op and any apply order "
            "converges. USER-scope rows are refused here (they are the "
            "account's own private state, never fanned in). Returns "
            "{ok, applied, skipped, refused}."
        ),
    )
    def brain_fanout_apply(fragments: list[dict[str, Any]]) -> dict[str, Any]:
        from .models import (Confidence as _C, Fragment as _F,
                             FragmentKind as _FK, Provenance as _P,
                             Scope as _S, Visibility as _V)

        def _as_packed(hlc: Any) -> int:
            """Coerce an HLC (16-hex str, decimal str, or int) to a packed int
            for ordered compare. Unknown / missing → -1 (older than any real
            row, so an absent local copy always loses to incoming)."""
            if isinstance(hlc, int):
                return hlc
            if isinstance(hlc, str) and hlc:
                try:
                    return int(hlc, 16)
                except ValueError:
                    try:
                        return int(hlc)
                    except ValueError:
                        return -1
            return -1

        def _local_hlc(fid: str) -> int:
            """Packed-int HLC of the local copy, or -1 if absent/unstamped."""
            try:
                cur = store.get_fragment(fid) if hasattr(store, "get_fragment") else None
            except Exception:
                cur = None
            if cur is None:
                return -1
            prov = getattr(cur, "provenance", None)
            return _as_packed(getattr(prov, "hlc", None) if prov else None)

        applied = 0
        skipped = 0
        refused = 0
        for f in (fragments or []):
            if not isinstance(f, dict):
                refused += 1
                continue
            scope_val = (f.get("scope") or "").strip().lower()
            # Only the SHARED convergence scopes are fanned in. USER stays
            # private; PROJECT/GLOBAL are out of this path's contract.
            if scope_val not in ("firm", "community"):
                refused += 1
                continue
            fid = f.get("id")
            if not fid:
                refused += 1
                continue
            raw_hlc = f.get("hlc")
            incoming = _as_packed(raw_hlc)
            local = _local_hlc(fid)
            if local >= 0 and incoming <= local:
                # Local copy is equal/newer — LWW says keep it (idempotent).
                skipped += 1
                continue
            # Provenance.hlc is a STRING in the model — keep the wire hex form
            # (or stringify an int) so the type validates + the next export
            # compares it consistently.
            hlc_str = (raw_hlc if isinstance(raw_hlc, str) and raw_hlc
                       else (f"{raw_hlc:016x}" if isinstance(raw_hlc, int) else None))
            prov = _P(
                contributing_agent="cloud-fanout",
                contributing_user=f.get("owner_user") or "remote",
                hlc=hlc_str,
            )
            try:
                frag = _F(
                    id=fid,
                    kind=_FK(f.get("kind") or "fact"),
                    text=f.get("text") or "",
                    subject=f.get("subject"),
                    predicate=f.get("predicate"),
                    object=f.get("object"),
                    scope=_S(scope_val),
                    visibility=_V(f.get("visibility") or "shared_public"),
                    owner_user=f.get("owner_user") or "remote",
                    project_id=f.get("project_id"),
                    firm_id=f.get("firm_id"),
                    confidence=_C(f.get("confidence") or "extracted"),
                    provenance=prov,
                    extra=f.get("extra") or {},
                )
                store.write_fragment(frag)
                applied += 1
            except Exception:
                refused += 1
        return {"ok": True, "applied": applied, "skipped": skipped,
                "refused": refused}

    @mcp.tool(
        name="brain.cloud_archive",
        description=(
            "Brain #32 day-2: upload a local dataset directory (from "
            "brain.dataset_export) to an S3-compatible bucket the USER "
            "owns (Cloudflare R2 / AWS S3 / Hetzner / MinIO). ArchHub "
            "never holds the data — it pushes to the caller's chosen "
            "target. Credentials are passed as op://vault/item/field refs "
            "(resolved at call time via 1Password CLI / Credential Manager "
            "/ env), never plaintext. include_blobs also mirrors the "
            "content-addressed blob tree. Returns ok/uploaded_count/"
            "total_bytes/error. Requires boto3 (returns a clean error if "
            "absent — never crashes)."
        ),
    )
    def brain_cloud_archive(
        local_dir: str,
        bucket: str,
        endpoint_url: Optional[str] = None,
        region: str = "auto",
        access_key_ref: Optional[str] = None,
        secret_key_ref: Optional[str] = None,
        prefix: str = "archhub-brain",
        dataset_name: Optional[str] = None,
        include_blobs: bool = False,
        blob_store_root: Optional[str] = None,
    ) -> dict[str, Any]:
        from pathlib import Path as _P
        from . import cloud_archive as _ca

        try:
            return _ca.upload_dataset(
                _P(local_dir),
                bucket=bucket,
                endpoint_url=endpoint_url,
                region=region,
                access_key_ref=access_key_ref,
                secret_key_ref=secret_key_ref,
                prefix=prefix,
                dataset_name=dataset_name,
                include_blobs=include_blobs,
                blob_store_root=_P(blob_store_root) if blob_store_root else None,
            )
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.doc_links",
        description=(
            "Backlinks for a documentation file. file: path relative to "
            "repo root. Returns {backlinks: [...], forward_links: [...], "
            "freshness_score: 0.0–1.0}."
        ),
    )
    def brain_doc_links(file: str) -> dict[str, Any]:
        if hasattr(store, "doc_links"):
            return store.doc_links(file)
        return {
            "ok": True,
            "file": file,
            "backlinks": [],
            "forward_links": [],
            "freshness_score": 1.0,
            "note": "store.doc_links not implemented yet",
        }

    @mcp.tool(
        name="brain.a11y_prefs",
        description=(
            "Get or set per-user accessibility preferences. mode: 'get'|"
            "'set'. prefs (set only): {font_size, contrast, reduce_motion, "
            "screen_reader_optimised}. User-scope, syncs cross-device."
        ),
    )
    def brain_a11y_prefs(
        mode: str = "get",
        prefs: Optional[dict[str, Any]] = None,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or resolve_default_owner()
        if hasattr(store, "a11y_prefs"):
            return store.a11y_prefs(mode=mode, prefs=prefs, owner_user=owner)
        return {
            "ok": True,
            "mode": mode,
            "prefs": prefs or {
                "font_size": "medium",
                "contrast": "normal",
                "reduce_motion": False,
                "screen_reader_optimised": False,
            },
            "note": "store.a11y_prefs not implemented yet",
        }

    @mcp.tool(
        name="brain.enforce_diligence",
        description=(
            "Anti-laziness gate. Given an agent's final message + the files "
            "it touched + session proof signals, decide whether it has "
            "earned the right to stop. Returns {verdict: allow|block, "
            "violations, reason}. A 'block' verdict means the Stop hook "
            "refuses to let the session end — the agent must do the work. "
            "This is the brain holding EVERY AI client to the same bar."
        ),
    )
    def brain_enforce_diligence(
        last_message: str,
        touched_files: Optional[list[str]] = None,
        file_contents: Optional[dict[str, str]] = None,
        session_signals: Optional[dict[str, Any]] = None,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        from .diligence import evaluate_diligence

        verdict = evaluate_diligence(
            last_message=last_message,
            touched_files=touched_files,
            file_contents=file_contents,
            session_signals=session_signals,
        )
        # Remember enforcement stats so the brain can report how often
        # laziness was caught (a device-level diligence ledger).
        try:
            key = "diligence.stats"
            raw = store.get_meta(key)
            import json as _json
            stats = _json.loads(raw) if raw else {"checks": 0, "blocks": 0}
            stats["checks"] = int(stats.get("checks", 0)) + 1
            if verdict.verdict == "block":
                stats["blocks"] = int(stats.get("blocks", 0)) + 1
            store.set_meta(key, _json.dumps(stats))
            out = verdict.to_dict()
            out["stats"] = stats
            return out
        except Exception:
            return verdict.to_dict()

    # Expose the bound store on the server object so the daemon entrypoint
    # (`main`) can start the background engine against the SAME store the
    # tools read/write. build_server stays pure (no threads) so unit tests
    # that call it directly don't spawn workers — `main` flips the engine.
    # Also expose the owner resolver so additive tool families (below) can
    # honour the cloud account binding without importing build_server.
    try:
        mcp._brain_store = store  # type: ignore[attr-defined]
        mcp._brain_resolve_owner = resolve_default_owner  # type: ignore[attr-defined]
    except Exception:
        pass

    # ROMA "method-that-finishes-everything" tool families (ADDITIVE; ENCODE
    # artifact). Two complementary additive surfaces over ONE requirement-tree
    # ledger persisted in brain_meta (key 'requirement_tree_v1' — no new table,
    # no schema migration, no touch of fragments/skills/-wal/-shm):
    #   • brain.tree_*  — the requirement-tree primitives (create_root →
    #                     decompose/split-never-simplify → claim_leaf →
    #                     external court → sweep/frontier). [requirement_tree.py]
    #   • brain.roma_*  — the orchestration loop over the same tree (atomize →
    #                     claim → judge → loop-until-dry).            [roma.py]
    # Each registers NEW tool names only; zero existing handlers touched. Both
    # are wrapped fail-soft so the core 40 tools never depend on them building.
    try:
        from .requirement_tree import register_tree_tools
        register_tree_tools(mcp, store)
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] tree tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
    try:
        from .roma import register_roma_tools
        register_roma_tools(mcp, store)
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] roma tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    # BRV-01: the brain-driver active-work ledger (brain.work_*). The
    # server-authoritative, all-agents drive — every runtime pulls its next
    # leaf from brain.work_next + reports completion to brain.work_release.
    # ADDITIVE: one brain_meta JSON doc (key 'active_work_v1'), no new table,
    # no schema migration, no touch of fragments/skills. Fail-soft like the
    # families above so the core tools never depend on it building.
    try:
        from .active_work import register_active_work_tools
        register_active_work_tools(mcp, store)
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] active_work tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    return mcp


# ─────────────────────── helpers ───────────────────────────────────────


# Module-global cache: one CommunityPoller per BrainStore id. The poller
# holds a FederationDriver bound to the current firm_id; we lazily build
# it on first brain.community_poll_now invocation so the daemon doesn't
# pay the cost when no one is using the community tier.
_COMMUNITY_POLLERS: dict[int, Any] = {}


def _get_or_create_community_poller(store: BrainStore) -> Any:
    """Lazy singleton: build a CommunityPoller bound to this store + the
    current firm identity. Cached by store id() so repeat invocations
    reuse the same driver + reputations dict.
    """
    from .community import CommunityPoller
    from .federation import FederationDriver
    from .firm import current_firm_id

    cached = _COMMUNITY_POLLERS.get(id(store))
    if cached is not None:
        return cached
    firm_id = current_firm_id(store) or "default"
    driver = FederationDriver(
        firm_id=firm_id,
        actor_url="http://127.0.0.1:8474/actor",
        base_url="http://127.0.0.1:8474",
    )
    poller = CommunityPoller(store, driver)
    _COMMUNITY_POLLERS[id(store)] = poller
    return poller


def _scope_filter_for(
    owner_user: str, project_id: Optional[str], firm_id: Optional[str]
) -> list[Scope]:
    """Default scope filter: user + global always; project if project_id;
    firm if firm_id; community if subscribed (Slice 8)."""
    filt = [Scope.USER, Scope.GLOBAL]
    if project_id:
        filt.append(Scope.PROJECT)
    if firm_id:
        filt.append(Scope.FIRM)
    return filt


def _format_injection(
    skills: list[Skill],
    facts: list[Fragment],
    wiring: list[WiringEntry],
    secret_refs: list[SecretRef],
) -> str:
    """Markdown block ready to prepend to the system prompt."""
    lines: list[str] = []
    lines.append("<brain_context>")
    if skills:
        lines.append("## Relevant skills")
        for s in skills:
            triggers = ", ".join(s.triggers[:3]) if s.triggers else "(no triggers)"
            lines.append(f"- **{s.name}** — {s.description[:200]}")
            lines.append(f"  triggers: {triggers}; uses: {s.success_count}/{s.success_count + s.fail_count}")
    if facts:
        lines.append("\n## Relevant facts")
        for f in facts:
            lines.append(f"- {f.text}  [{f.confidence.value}; scope={f.scope.value}]")
    if wiring:
        active = [w for w in wiring if w.status == "active"]
        if active:
            lines.append("\n## Wiring on this device")
            for w in active[:12]:
                lines.append(f"- {w.name} ({w.kind})" + (f" → {w.endpoint}" if w.endpoint else ""))
    if secret_refs:
        lines.append("\n## Secret references (resolved JIT, never stored)")
        for r in secret_refs[:6]:
            desc = f" — {r.description}" if r.description else ""
            lines.append(f"- {r.ref}{desc}")
    lines.append("</brain_context>")
    return "\n".join(lines)


def _hash_id(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _summarise_trace(trace: dict[str, Any]) -> str:
    """Compact one-line summary of a trace — used as fragment.text."""
    tool_calls = trace.get("tool_calls", []) or []
    names = [tc.get("name", "?") for tc in tool_calls]
    user_msg = trace.get("user_message") or trace.get("prompt") or ""
    return (
        f"trace · user='{user_msg[:80]}' · tools=["
        + ", ".join(names[:8])
        + (f"… +{len(names)-8}" if len(names) > 8 else "")
        + f"] · outcome={trace.get('outcome', 'unknown')}"
    )


def _propose_skill_name(trace: dict[str, Any]) -> str:
    """Heuristic name proposal from trace — slice 5 reflexion worker
    refines this with an LLM call."""
    tool_calls = trace.get("tool_calls", []) or []
    if not tool_calls:
        return "unnamed_skill"
    first = tool_calls[0].get("name", "skill")
    # Strip provider prefix conventions (e.g. "outlook_set_categories" → "set_categories")
    parts = first.split("_", 1)
    base = parts[-1] if len(parts) > 1 else first
    return f"{base}_flow"


def _novelty_estimate(
    store: BrainStore, trace: dict[str, Any], owner_user: str
) -> float:
    """Slice-1 novelty estimate: cosine over tool-name sequence vs existing
    skills' `requires_mcps`. Slice 2 swaps in a real embedding cosine.

    Returns a value in [0, 1]: 0 = identical to existing skill, 1 = entirely
    novel.
    """
    tool_calls = trace.get("tool_calls", []) or []
    if not tool_calls:
        return 0.0
    sequence = [tc.get("name", "") for tc in tool_calls]
    if not sequence:
        return 0.0
    sig = set(sequence)
    existing = store.list_skills(owner_user=owner_user, limit=200)
    if not existing:
        return 1.0
    max_overlap = 0.0
    for s in existing:
        s_sig = set(s.requires_mcps + [t for t in s.triggers if "_" in t])
        if not s_sig:
            continue
        overlap = len(sig & s_sig) / max(len(sig | s_sig), 1)
        if overlap > max_overlap:
            max_overlap = overlap
    return max(0.0, 1.0 - max_overlap)


def _infer_scope(cwd: Optional[str], git_remote: Optional[str]) -> Scope:
    """Slice-1 inference: cwd inside a known project → PROJECT; git remote
    suggests firm → FIRM; else USER. Slice 6 wires firm/project registries."""
    if git_remote and ("firm" in git_remote.lower() or "company" in git_remote.lower()):
        return Scope.FIRM
    if cwd:
        return Scope.PROJECT
    return Scope.USER


def _infer_project_id(cwd: Optional[str], git_remote: Optional[str]) -> Optional[str]:
    if git_remote:
        # `git@github.com:archhub/web-ui.git` → `web-ui`
        tail = git_remote.split("/")[-1] if "/" in git_remote else git_remote
        return tail.removesuffix(".git") or None
    if cwd:
        return Path(cwd).name or None
    return None


def _infer_firm_id(git_remote: Optional[str]) -> Optional[str]:
    if not git_remote:
        return None
    # github org or gitlab group
    if ":" in git_remote and "/" in git_remote:
        org = git_remote.split(":", 1)[1].split("/", 1)[0]
        return org or None
    return None


# ─────────────────────── entrypoints ───────────────────────────────────


def main(argv: Optional[list[str]] = None) -> None:
    """Default CLI: stdio transport (matches Claude Code / Codex / Cursor)."""
    parser = argparse.ArgumentParser(
        prog="personal-brain",
        description="Personal Brain MCP server (AgDR-0044)",
    )
    parser.add_argument(
        "--http", type=int, default=None,
        help="Run Streamable HTTP transport on this port instead of stdio.",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help=f"SQLite database path. Default: {default_brain_path()}",
    )
    parser.add_argument(
        "--owner", type=str, default=None,
        help="Default owner_user when clients don't pass one. "
             "Default: $BRAIN_OWNER_USER / $USER / 'founder'.",
    )
    args = parser.parse_args(argv)

    server = build_server(db_path=args.db, default_owner_user=args.owner)

    # ── Turn the ENGINE ON (AgDR-0044 §1). build_server only registers
    # tools; the background workers (Sync / Publish / Reflexion / Watchdog)
    # are started HERE, at daemon boot, against the same bound store.
    # Guarded by BRAIN_WORKERS (default ON). Without this the brain is a
    # library of dormant primitives, not an ambient engine.
    try:
        from .workers import start_workers, workers_enabled
        bound_store = getattr(server, "_brain_store", None)
        if bound_store is not None:
            sup = start_workers(bound_store, owner_user=args.owner)
            if sup is not None:
                st = sup.status()
                alive = [
                    name for name, w in st.get("workers", {}).items()
                    if isinstance(w, dict) and w.get("alive")
                ]
                print(
                    f"[brain] engine ON — workers alive: {', '.join(alive) or 'none'}"
                    + (f" | errors: {st['errors']}" if st.get("errors") else ""),
                    file=sys.stderr, flush=True,
                )
            elif not workers_enabled():
                print("[brain] engine OFF — BRAIN_WORKERS disabled",
                      file=sys.stderr, flush=True)
    except Exception as ex:  # never block daemon boot on engine start
        print(f"[brain] engine start error: {type(ex).__name__}: {ex}",
              file=sys.stderr, flush=True)

    if args.http is not None:
        # InHouseMCP.run (mcp_core.run) serves build_asgi_app() — our
        # hand-rolled stateless Streamable-HTTP Starlette app — over uvicorn.
        # `transport="http"` selects that path; `stateless_http=True` keeps
        # every POST self-contained so ArchHub's BrainClient (synchronous,
        # in-process) never has to track an Mcp-Session-Id between hooks. The
        # run() signature always accepts these kwargs (mcp_core.run), so no
        # version fallback is needed.
        host = os.environ.get("BRAIN_HTTP_HOST", "127.0.0.1")
        server.run(transport="http", host=host, port=args.http,
                   stateless_http=True)
        return

    # stdio is the default transport.
    server.run(transport="stdio")


def main_stdio(argv: Optional[list[str]] = None) -> None:
    """Explicit stdio entrypoint for client configs that expect a no-arg
    command."""
    main(argv=[] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover
    main()
