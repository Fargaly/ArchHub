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
  - stdio    (default; proxies to the singleton HTTP daemon)
  - http     (Streamable HTTP; one daemon serves all remote clients)

Run:
  python -m personal_brain.server              # stdio proxy to singleton
  python -m personal_brain.server --http 8473  # streamable HTTP
  python -m personal_brain.server --local-stdio  # explicit local stdio
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import (
    Confidence,
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
    # Hybrid recall lane (ARCHHUB_HYBRID_RECALL, default ON '1'). The
    # predictor itself preserves the zero-risk default: alpha stays 1.0
    # (pure dense, bit-identical original path) unless the query carries an
    # exact-code token (AP_CORNICE / CW22 / 9820-style), where BM25 gets an
    # equal say so self_extend:: loop facts actually surface. Env '0' kills
    # the lane entirely.
    hybrid_alpha: Optional[float] = None
    if os.environ.get("ARCHHUB_HYBRID_RECALL", "1") != "0":
        from .hybrid_recall import predict_alpha
        hybrid_alpha = predict_alpha(prompt)
    facts = retrieve_facts(
        store, prompt,
        owner_user=owner_user, scope_filter=scope_filter, k=k_facts,
        hybrid_alpha=hybrid_alpha,
    )
    wiring = store.list_wiring()
    secret_refs = store.list_secret_refs(owner_user, scope_filter=scope_filter)

    # log retrievals (reconsolidation: every read is an implicit edit signal)
    for f in facts:
        store.log_access(owner_user, f.id, purpose="brain.context")
        store.touch_fragment(f.id, success=True)
    # Skills are consumed too — count every skill returned in the payload.
    # This is the read-path incrementer the federation sharing gate
    # (derive_skill_usage_patterns, success_count >= 3) depends on; without
    # it that gate is unsatisfiable by construction.
    for sk in skills:
        store.touch_skill(sk.id, success=True)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    injection = _format_injection(skills, facts, wiring, secret_refs)

    # MEETING ROOM tail (founder 2026-07-17): every agent's pre-prompt hook
    # calls brain.context each turn — appending the room's recent messages HERE
    # is what makes the workshop real-time for all agents with zero client
    # plumbing. Fail-soft: the room never breaks context retrieval.
    try:
        from .cell_room_wiring import (
            cell_room_injection_tail, cell_room_is_wired,
        )
        if cell_room_is_wired():
            _room_tail = cell_room_injection_tail()
        else:
            _room_tail = (
                '<meeting_room status="blocked" '
                'authority="application-owned Universal Cell Workshop">\n'
                "Universal Workshop is enabled but not wired; legacy meeting_room_v1 "
                "is not prompt authority.\n"
                "</meeting_room>"
            )
        if _room_tail:
            injection = injection + "\n" + _room_tail
    except Exception:
        pass

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
    critic_policy: Optional[dict[str, Any]] = None,
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
    r1_gate = {
        "passed": bool(accept),
        "novelty_score": novelty,
        "success_score": success_score,
        "breakdown": dict(breakdown),
    }
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

    r2_gate = {
        "passed": bool(accept and not diversity_blocked),
        "reason": diversity_reason or (
            "diversity gate passed" if accept else "R1 calibration gate did not pass"),
    }
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
                critic_policy=critic_policy,
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
                minted_skill.mint_evidence = {
                    "schema": "archhub-skill-mint-evidence/v1",
                    "source_trace": {
                        "trace_id": trace.get("trace_id"),
                        "session_id": session_id or trace.get("session_id"),
                        "contributing_agent": contributing_agent,
                    },
                    "r1_gate": r1_gate,
                    "r2_gate": r2_gate,
                    "reflexion": {
                        "accepted": True,
                        "hone": dict(result.hone or {}),
                        "classification": dict(result.classification or {}),
                        "critic_policy": dict(critic_policy or {}),
                        "proposal": dict(result.proposal or {}),
                    },
                }
                store.upsert_skill(minted_skill)
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
        r1_gate=r1_gate,
        r2_gate=r2_gate,
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


def announce_wiring_cell_first(
    *,
    store: BrainStore,
    req: WiringAnnounceRequest,
    owner_user: str,
) -> dict[str, Any]:
    entry_summaries = [
        {
            "name": entry.name,
            "kind": entry.kind,
            "endpoint_sha256": hashlib.sha256(
                str(entry.endpoint or "").encode("utf-8")
            ).hexdigest(),
            "device_id": entry.device_id or req.device_id,
        }
        for entry in req.entries
    ]
    secret_ref_hashes = [
        hashlib.sha256(str(ref.ref).encode("utf-8")).hexdigest()
        for ref in req.secret_refs
    ]
    claims = {
        "operation": "brain.wiring_announce",
        "owner_user": owner_user,
        "device_id": req.device_id,
        "entry_count": len(req.entries),
        "entries": entry_summaries,
        "secret_ref_count": len(req.secret_refs),
        "secret_ref_hashes": secret_ref_hashes,
        "cwd_sha256": hashlib.sha256(str(req.cwd or "").encode("utf-8")).hexdigest(),
        "git_remote_sha256": hashlib.sha256(
            str(req.git_remote or "").encode("utf-8")
        ).hexdigest(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    basis = json.dumps(claims, sort_keys=True)
    source = "brain-control:wiring:%s" % (
        hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    )
    try:
        from .universal_runtime import UniversalRuntimeBridge

        runtime = UniversalRuntimeBridge()
        cell_record = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": source,
                "scope": "founder/brain-control/wiring",
                "claims": basis,
                "provenance": "personal_brain.server:wiring_announce",
            },
            idempotency_field="source",
        )
    except Exception as cell_error:
        return {
            "ok": False,
            "registered": 0,
            "skipped": len(req.entries),
            "cell_first": True,
            "brain_written": False,
            "cell_record_source": source,
            "error": f"{type(cell_error).__name__}: {cell_error}",
        }

    resp = announce_wiring(store=store, req=req, owner_user=owner_user)
    out = resp.model_dump(mode="json")
    out["ok"] = True
    out["cell_first"] = True
    out["brain_written"] = True
    out["cell_record"] = cell_record
    out["cell_record_root"] = str(cell_record["created_root"])
    out["cell_record_source"] = source
    return out


def queue_skill_mint_with_cell_receipt(
    *,
    store: BrainStore,
    trace: dict[str, Any],
    outcome: str,
    owner_user: str,
    contributing_agent: str,
    session_id: Optional[str] = None,
    critic_policy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    redacted_trace = _redact_hook_value(trace)
    trace_json = json.dumps(redacted_trace, sort_keys=True, default=str)
    tool_calls = trace.get("tool_calls", []) or []
    claims = {
        "operation": "brain.skill_mint",
        "owner_user": owner_user,
        "contributing_agent": contributing_agent,
        "session_id": session_id or "",
        "trace_id": trace.get("trace_id") or "",
        "outcome": outcome,
        "tool_call_count": len(tool_calls),
        "successful_tool_call_count": len([
            call for call in tool_calls if call.get("status") == "ok"
        ]),
        "trace_sha256": hashlib.sha256(trace_json.encode("utf-8")).hexdigest(),
        "trace_len": len(trace_json),
        "critic_policy_sha256": hashlib.sha256(
            json.dumps(critic_policy or {}, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    basis = json.dumps(claims, sort_keys=True)
    source = "brain-control:skill-mint:%s" % (
        hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    )
    try:
        from .universal_runtime import UniversalRuntimeBridge

        runtime = UniversalRuntimeBridge()
        cell_record = runtime.assembly_create(
            definition_key="knowledge-branch",
            fields={
                "source": source,
                "scope": "founder/brain-control/skill-mint",
                "provenance": "personal_brain.server:skill_mint",
            },
            structured_fields={"claims": claims},
            idempotency_field="source",
        )
    except Exception as cell_error:
        return {
            "ok": False,
            "queued": False,
            "cell_receipt": False,
            "cell_authority": False,
            "legacy_authority": True,
            "migration_status": "receipt-required",
            "brain_written": False,
            "cell_record_source": source,
            "error": f"{type(cell_error).__name__}: {cell_error}",
        }

    result = queue_skill_mint(
        store=store,
        trace=trace,
        outcome=outcome,
        owner_user=owner_user,
        contributing_agent=contributing_agent,
        session_id=session_id,
        critic_policy=critic_policy,
    )
    out = result.model_dump(mode="json")
    out["ok"] = True
    out["cell_receipt"] = True
    out["cell_authority"] = False
    out["legacy_authority"] = True
    out["migration_status"] = "receipt-only"
    out["brain_written"] = bool(result.queued)
    out["legacy_projection_written"] = bool(result.queued)
    out["cell_record"] = cell_record
    out["cell_record_root"] = str(cell_record["created_root"])
    out["cell_record_source"] = source
    return out


def create_brain_control_cell_receipt(
    *,
    operation: str,
    scope: str,
    claims: dict[str, Any],
    provenance: str,
) -> tuple[dict[str, Any], str]:
    """Create a Universal Cell governance receipt for a Brain control write."""
    safe_claims = dict(claims)
    safe_claims["operation"] = operation
    safe_claims["recorded_at"] = datetime.now(timezone.utc).isoformat()
    basis = json.dumps(safe_claims, sort_keys=True, default=str)
    source = "brain-control:%s:%s" % (
        scope,
        hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16],
    )
    from .universal_runtime import UniversalRuntimeBridge

    runtime = UniversalRuntimeBridge()
    record = runtime.assembly_create(
        definition_key="knowledge-branch",
        fields={
            "source": source,
            "scope": f"founder/brain-control/{scope}",
            "claims": basis,
            "provenance": provenance,
        },
        idempotency_field="source",
    )
    return record, source


def build_server(
    *,
    store: Optional[BrainStore] = None,
    db_path: Optional[str | Path] = None,
    default_owner_user: Optional[str] = None,
    runtime_session_manager=None,
    cell_bridge=None,
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

    store_supplied = store is not None
    if store is None:
        store = BrainStore.open(db_path)
    governance_cell_bridge = cell_bridge
    if governance_cell_bridge is None and not store_supplied:
        try:
            from .universal_runtime import UniversalRuntimeBridge

            governance_cell_bridge = UniversalRuntimeBridge()
        except Exception:
            governance_cell_bridge = None
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
    setattr(mcp, "_brain_governance_cell_bridge", governance_cell_bridge)
    if runtime_session_manager is None:
        from .universal_session_manager import UniversalRuntimeSessionManager
        runtime_session_manager = UniversalRuntimeSessionManager()
    mcp._universal_runtime_session_manager = runtime_session_manager

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
            "CELL-FIRST legacy Brain memory write. Accepted ADD/UPDATE/DELETE/"
            "NOOP ops get a Universal Cell governance receipt before the legacy "
            "Brain fragment projection is written. The Cell receipt records ids, "
            "scopes, kinds, content hashes, and lengths, not raw arbitrary memory "
            "text. If the Cell receipt cannot be created, the Brain write is "
            "refused. Every non-USER-scope write is still gated by ACL."
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

        cell_record = None
        cell_record_source = ""
        if parsed:
            op_summaries: list[dict[str, Any]] = []
            for op in parsed:
                fragment = op.fragment
                frag_text = fragment.text if fragment is not None else ""
                frag_id = fragment.id if fragment is not None else ""
                frag_scope = (
                    fragment.scope.value
                    if fragment is not None and hasattr(fragment.scope, "value")
                    else (str(fragment.scope) if fragment is not None else "")
                )
                frag_kind = (
                    fragment.kind.value
                    if fragment is not None and hasattr(fragment.kind, "value")
                    else (str(fragment.kind) if fragment is not None else "")
                )
                op_summaries.append({
                    "op": op.op.value if hasattr(op.op, "value") else str(op.op),
                    "fragment_id": frag_id,
                    "scope": frag_scope,
                    "kind": frag_kind,
                    "text_sha256": hashlib.sha256(
                        str(frag_text).encode("utf-8")
                    ).hexdigest(),
                    "text_len": len(str(frag_text)),
                })
            owner = resolve_default_owner()
            batch_basis = json.dumps(
                {
                    "owner_user": owner,
                    "ops": op_summaries,
                    "denied": denied,
                },
                sort_keys=True,
            )
            batch_id = hashlib.sha256(batch_basis.encode("utf-8")).hexdigest()[:16]
            cell_record_source = f"brain-control:write:{batch_id}"
            try:
                from .universal_runtime import UniversalRuntimeBridge

                runtime = UniversalRuntimeBridge()
                cell_record = runtime.assembly_create(
                    definition_key="knowledge-branch",
                    fields={
                        "source": cell_record_source,
                        "scope": "founder/brain-control/write",
                        "claims": json.dumps(
                            {
                                "operation": "brain.write",
                                "owner_user": owner,
                                "ops": op_summaries,
                                "acl_denied_count": len(denied),
                                "recorded_at": datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            },
                            sort_keys=True,
                        ),
                        "provenance": "personal_brain.server:brain_write",
                    },
                    idempotency_field="source",
                )
            except Exception as cell_error:
                result = {
                    "ok": False,
                    "ops_applied": 0,
                    "cell_first": True,
                    "brain_written": False,
                    "cell_record_source": cell_record_source,
                    "error": f"{type(cell_error).__name__}: {cell_error}",
                }
                if denied:
                    result["acl_denied"] = denied
                    result["acl_denied_count"] = len(denied)
                return result

        resp = apply_write(store=store, ops=parsed)
        result = resp.model_dump(mode="json")
        result["cell_first"] = bool(parsed)
        result["brain_written"] = bool(parsed)
        if cell_record is not None:
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
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
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.organize",
                scope="maintenance",
                claims={
                    "owner_user_sha256": hashlib.sha256(
                        owner.encode("utf-8")
                    ).hexdigest(),
                    "fragment_count": int(store.count_fragments()),
                },
                provenance="personal_brain.server.brain.organize",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        result = brain_organize(store, owner_user=owner)
        result["ok"] = True
        result["cell_first"] = True
        result["brain_written"] = True
        result["cell_record"] = cell_record
        result["cell_record_root"] = str(cell_record["created_root"])
        result["cell_record_source"] = cell_record_source
        return result

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
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.reembed",
                scope="maintenance",
                claims={
                    "fragment_count": int(store.count_fragments()),
                },
                provenance="personal_brain.server.brain.reembed",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        result = brain_reembed(store)
        result["ok"] = True
        result["cell_first"] = True
        result["brain_written"] = True
        result["cell_record"] = cell_record
        result["cell_record_root"] = str(cell_record["created_root"])
        result["cell_record_source"] = cell_record_source
        return result

    @mcp.tool(
        name="brain.promote_skills",
        description=(
            "CELL-FIRST for live runs. "
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
        if dry_run:
            plan = promote_skill_fragments(
                store, owner_user=owner, dry_run=True,
            )
            plan["cell_first"] = True
            plan["brain_written"] = False
            return plan

        plan = promote_skill_fragments(store, owner_user=owner, dry_run=True)
        plan_json = json.dumps(plan, sort_keys=True, default=str)
        claims = {
            "owner_user_sha256": hashlib.sha256(
                owner.encode("utf-8")
            ).hexdigest(),
            "planned_promoted": int(plan.get("promoted", 0)),
            "planned_deleted_fragments": int(
                plan.get("deleted_fragments", 0)
            ),
            "planned_total_candidates": int(plan.get("total_candidates", 0)),
            "planned_skipped_duplicate": int(
                plan.get("skipped_duplicate", 0)
            ),
            "planned_errors_count": len(plan.get("errors", []) or []),
            "planned_slug_map_count": len(plan.get("slug_map", []) or []),
            "plan_sha256": hashlib.sha256(
                plan_json.encode("utf-8")
            ).hexdigest(),
        }
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.promote_skills",
                scope="promote-skills",
                claims=claims,
                provenance="personal_brain.server.brain.promote_skills",
            )
        except Exception as exc:
            return {
                "ok": False,
                "promoted": 0,
                "skipped_duplicate": 0,
                "deleted_fragments": 0,
                "total_candidates": int(plan.get("total_candidates", 0)),
                "slug_map": [],
                "skipped": [],
                "errors": [f"cell unavailable: {exc}"],
                "dry_run": False,
                "cell_first": True,
                "brain_written": False,
            }

        result = promote_skill_fragments(store, owner_user=owner, dry_run=False)
        result["ok"] = True
        result["cell_first"] = True
        result["brain_written"] = bool(
            result.get("promoted") or result.get("deleted_fragments")
        )
        result["cell_record"] = cell_record
        result["cell_record_root"] = str(cell_record["created_root"])
        result["cell_record_source"] = cell_record_source
        return result

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
            "CELL-FIRST. "
            "Un-archive a fragment — clear its valid_until so a faded/archived "
            "note rejoins active memory. The inverse of the organize pass's "
            "stale-trace archive; powers the visual browser's 'Restore' button "
            "(MAKE-IT-REAL-NEVER-TRIM). Mutates only through the safe writer; "
            "idempotent. Returns {ok, restored, id}."
        ),
    )
    def brain_restore_tool(fragment_id: str) -> dict[str, Any]:
        from .organize import brain_restore
        before = store.get_fragment(fragment_id) if fragment_id else None
        if before is not None and before.valid_until is not None:
            try:
                cell_record, cell_record_source = create_brain_control_cell_receipt(
                    operation="brain.restore",
                    scope="fact-mutation",
                    claims={
                        "fragment_id_sha256": hashlib.sha256(
                            str(fragment_id).encode("utf-8")
                        ).hexdigest(),
                        "kind": (
                            before.kind.value
                            if hasattr(before.kind, "value")
                            else str(before.kind)
                        ),
                        "scope": (
                            before.scope.value
                            if hasattr(before.scope, "value")
                            else str(before.scope)
                        ),
                        "text_sha256": hashlib.sha256(
                            str(before.text or "").encode("utf-8")
                        ).hexdigest(),
                        "text_len": len(str(before.text or "")),
                        "had_valid_until": True,
                    },
                    provenance="personal_brain.server:restore",
                )
            except Exception as cell_error:
                return {
                    "ok": False,
                    "restored": False,
                    "id": fragment_id,
                    "cell_first": True,
                    "brain_written": False,
                    "error": f"{type(cell_error).__name__}: {cell_error}",
                }
            result = brain_restore(store, fragment_id)
            result["cell_first"] = True
            result["brain_written"] = bool(result.get("restored"))
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
            return result
        result = brain_restore(store, fragment_id)
        result["cell_first"] = False
        result["brain_written"] = False
        return result

    # ── Brain-as-folders (founder 2026-06-21): explorable + editable tree ──
    # The flat search + do-nothing graph blob are replaced by a real folder
    # browser in the UI (BrainFolders panel). These three tools are its
    # READ + WRITE backend — every record is a live Fragment row, edits
    # persist through the safe writers (ONE-SYSTEM: no new store).
    @mcp.tool(
        name="brain.list_facts",
        description=(
            "READ-ONLY. Enumerate every brain fact grouped into top-level "
            "FOLDERS by type (User / Feedback / Projects / Reference, then "
            "Decisions / Capability / Skills / Traces) for the explorable "
            "folder browser. Each fact carries id, name, short desc, full "
            "body, type, kind, scope. Returns {ok,total,folders:[{id,label,"
            "count,facts:[...]}]}. Folders are the live store grouped by the "
            "same facet vocabulary brain.browse uses. Safe to poll."
        ),
    )
    def brain_list_facts_tool(
        owner_user: Optional[str] = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        from .brain_facts import list_facts
        owner = owner_user or resolve_default_owner()
        return list_facts(store, owner_user=owner,
                          include_archived=include_archived)

    @mcp.tool(
        name="brain.edit_fact",
        description=(
            "CELL-FIRST. "
            "Edit a brain fact's text in place. Persists through the safe "
            "write_fragment path (never a raw sqlite write) and stales the "
            "embedding so the next organize pass re-embeds. Powers the folder "
            "browser's Edit affordance — edits are REAL and persist. Returns "
            "{ok, id, edited}."
        ),
    )
    def brain_edit_fact_tool(fragment_id: str, text: str) -> dict[str, Any]:
        from .brain_facts import edit_fact
        new_text = (text or "").strip()
        before = store.get_fragment(fragment_id) if fragment_id else None
        if before is not None and new_text and before.text != new_text:
            try:
                cell_record, cell_record_source = create_brain_control_cell_receipt(
                    operation="brain.edit_fact",
                    scope="fact-mutation",
                    claims={
                        "fragment_id_sha256": hashlib.sha256(
                            str(fragment_id).encode("utf-8")
                        ).hexdigest(),
                        "kind": (
                            before.kind.value
                            if hasattr(before.kind, "value")
                            else str(before.kind)
                        ),
                        "scope": (
                            before.scope.value
                            if hasattr(before.scope, "value")
                            else str(before.scope)
                        ),
                        "old_text_sha256": hashlib.sha256(
                            str(before.text or "").encode("utf-8")
                        ).hexdigest(),
                        "new_text_sha256": hashlib.sha256(
                            new_text.encode("utf-8")
                        ).hexdigest(),
                        "old_text_len": len(str(before.text or "")),
                        "new_text_len": len(new_text),
                    },
                    provenance="personal_brain.server:edit_fact",
                )
            except Exception as cell_error:
                return {
                    "ok": False,
                    "id": fragment_id,
                    "edited": False,
                    "cell_first": True,
                    "brain_written": False,
                    "error": f"{type(cell_error).__name__}: {cell_error}",
                }
            result = edit_fact(store, fragment_id, text)
            result["cell_first"] = True
            result["brain_written"] = bool(result.get("edited"))
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
            return result
        result = edit_fact(store, fragment_id, text)
        result["cell_first"] = False
        result["brain_written"] = False
        return result

    @mcp.tool(
        name="brain.delete_fact",
        description=(
            "CELL-FIRST. "
            "Delete a brain fact. Default is a SOFT delete (set valid_until "
            "→ drops out of the active tree, recoverable via brain.restore, "
            "honouring MAKE-IT-REAL-NEVER-TRIM). Pass hard=True to remove the "
            "row entirely. Powers the folder browser's Delete affordance. "
            "Returns {ok, id, deleted, hard}."
        ),
    )
    def brain_delete_fact_tool(fragment_id: str, hard: bool = False) -> dict[str, Any]:
        from .brain_facts import delete_fact
        before = store.get_fragment(fragment_id) if fragment_id else None
        mutates = before is not None and (bool(hard) or before.valid_until is None)
        if mutates:
            try:
                cell_record, cell_record_source = create_brain_control_cell_receipt(
                    operation="brain.delete_fact",
                    scope="fact-mutation",
                    claims={
                        "fragment_id_sha256": hashlib.sha256(
                            str(fragment_id).encode("utf-8")
                        ).hexdigest(),
                        "kind": (
                            before.kind.value
                            if hasattr(before.kind, "value")
                            else str(before.kind)
                        ),
                        "scope": (
                            before.scope.value
                            if hasattr(before.scope, "value")
                            else str(before.scope)
                        ),
                        "text_sha256": hashlib.sha256(
                            str(before.text or "").encode("utf-8")
                        ).hexdigest(),
                        "text_len": len(str(before.text or "")),
                        "hard": bool(hard),
                        "had_valid_until": before.valid_until is not None,
                    },
                    provenance="personal_brain.server:delete_fact",
                )
            except Exception as cell_error:
                return {
                    "ok": False,
                    "id": fragment_id,
                    "deleted": False,
                    "hard": bool(hard),
                    "cell_first": True,
                    "brain_written": False,
                    "error": f"{type(cell_error).__name__}: {cell_error}",
                }
            result = delete_fact(store, fragment_id, hard=hard)
            result["cell_first"] = True
            result["brain_written"] = bool(result.get("deleted"))
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
            return result
        result = delete_fact(store, fragment_id, hard=hard)
        result["cell_first"] = False
        result["brain_written"] = False
        return result

    @mcp.tool(
        name="brain.skill_mint",
        description=(
            "Skill mint migration bridge. Creates a redacted Universal Cell "
            "receipt before the current legacy Brain trace/skill authority "
            "writes. The response declares receipt-only status; it is not a "
            "Cell-authoritative skill workflow."
        ),
    )
    def brain_skill_mint(
        trace: dict[str, Any],
        outcome: str = "success",
        owner_user: Optional[str] = None,
        contributing_agent: str = "unknown",
        session_id: Optional[str] = None,
        critic_policy: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        owner = owner_user or resolve_default_owner()
        return queue_skill_mint_with_cell_receipt(
            store=store,
            trace=trace,
            outcome=outcome,
            owner_user=owner,
            contributing_agent=contributing_agent,
            session_id=session_id,
            critic_policy=critic_policy,
        )

    @mcp.tool(
        name="brain.wiring_announce",
        description=(
            "CELL-FIRST wiring announcement. Creates a Universal Cell receipt "
            "for the device/session wiring, then writes the legacy Brain wiring "
            "projection used by context filtering. Secret references are hashed "
            "in the Cell receipt, not copied as raw refs."
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
        return announce_wiring_cell_first(store=store, req=req, owner_user=owner)

    # ───────────────── Claude Code HOOK WRAPPERS (the fix) ─────────────────
    # ROOT CAUSE (2026-06-21): Claude Code's `mcp_tool` hooks call the brain
    # tool with the hook's RAW payload as `arguments`. The four real targets
    # (brain.context / brain.write / brain.skill_mint / brain.wiring_announce)
    # each take a TYPED positional (prompt / ops:LIST / trace:dict / device_id)
    # that `${...}` interpolation cannot build from scalar hook fields — so
    # every hook fired with the wrong/empty shape and FAILED. Result: no
    # context recall, no memory written, no skills minted, no wiring announce
    # → "memory + learning + drive don't persist across sessions."
    #
    # These four THIN wrappers accept the exact field names Claude Code emits
    # for each event, tolerate ANY extra kwargs (hook_event_name, transcript
    # fields, …) via **_ignored, synthesize the real typed call internally, and
    # delegate to the SAME logic the canonical tools use (ONE-SYSTEM — no new
    # store, no parallel path). Each is FAST + failure-tolerant: a hook must
    # NEVER hard-error, so every wrapper swallows internal failures to a soft
    # result dict. The hooks in settings.json / installer.py point HERE with an
    # `arguments` map built from the hook's scalar fields.

    @mcp.tool(
        name="brain.hook_context",
        description=(
            "Claude Code UserPromptSubmit hook target (wrapper). Accepts the "
            "raw hook payload (prompt + session_id + cwd + any extra fields), "
            "resolves the bound owner, and returns the same context injection "
            "block brain.context produces. Tolerant of unexpected kwargs so "
            "the hook never errors."
        ),
    )
    def brain_hook_context(
        prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        try:
            text = (prompt or "").strip()
            if not text:
                # Empty prompt (e.g. slash-command turn) — nothing to recall;
                # return an empty-but-valid context so the hook is a no-op.
                return {
                    "ok": True,
                    "injection": "",
                    "skills": [],
                    "facts": [],
                    "note": "empty prompt — no context injected",
                }
            owner = resolve_default_owner()
            resp = make_context_payload(
                store=store,
                prompt=text,
                owner_user=owner,
                cwd=cwd,
            )
            out = resp.model_dump(mode="json")
            out["ok"] = True
            return out
        except Exception as ex:  # a hook must never hard-error
            return {
                "ok": False,
                "injection": "",
                "skills": [],
                "facts": [],
                "error": f"{type(ex).__name__}: {ex}",
            }

    @mcp.tool(
        name="brain.observe",
        description=(
            "CELL-FIRST Claude Code PostToolUse hook target. Synthesizes one "
            "observed tool-call memory record, creates a Universal Cell evidence "
            "record first, then writes the legacy Brain fragment only as a "
            "projection receipt. If the Cell record cannot be created, the hook "
            "soft-fails without writing Brain memory. Tolerant of unexpected "
            "kwargs."
        ),
    )
    def brain_observe(
        tool_name: Optional[str] = None,
        tool_input: Optional[Any] = None,
        tool_response: Optional[Any] = None,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        try:
            tname = (tool_name or "").strip() or "unknown_tool"
            owner = resolve_default_owner()

            # Strip op:// / api-key-shaped secrets from the captured payload so
            # nothing sensitive lands in memory (same policy as memory_gate).
            input_summary = _summarise_hook_value(_redact_hook_value(tool_input))
            result_summary = _summarise_hook_value(_redact_hook_value(tool_response))
            text = f"{tname}({input_summary}) → {result_summary}"

            # Stable, content-derived id (dedupe re-fires of the same call).
            frag_id = _hash_id(
                "observe", tname, (session_id or ""), text[:200]
            )
            cell_payload = {
                "operation": "brain.observe",
                "fragment_id": frag_id,
                "tool_name": tname,
                "session_id": session_id or "",
                "cwd": cwd or "",
                "owner_user": owner,
                "input_summary": input_summary,
                "result_summary": result_summary,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            cell_record_source = f"brain-control:observe:{frag_id}"
            try:
                from .universal_runtime import UniversalRuntimeBridge

                runtime = UniversalRuntimeBridge()
                cell_record = runtime.assembly_create(
                    definition_key="knowledge-branch",
                    fields={
                        "source": cell_record_source,
                        "scope": "founder/brain-control/observe",
                        "claims": json.dumps(cell_payload, sort_keys=True),
                        "provenance": "personal_brain.server:brain_observe",
                    },
                    idempotency_field="source",
                )
            except Exception as cell_error:
                return {
                    "ok": False,
                    "ops_applied": 0,
                    "cell_first": True,
                    "brain_written": False,
                    "cell_record_source": cell_record_source,
                    "error": f"{type(cell_error).__name__}: {cell_error}",
                }
            fragment = Fragment(
                id=frag_id,
                kind=FragmentKind.FACT,
                text=text,
                subject=tname,
                predicate="produced",
                object=result_summary[:120],
                scope=Scope.USER,
                visibility=Visibility.PRIVATE,
                owner_user=owner,
                confidence=Confidence.EXTRACTED,
                provenance=Provenance(
                    contributing_agent="claude-code",
                    contributing_user=owner,
                    session_id=session_id,
                    created_at=datetime.now(timezone.utc),
                ),
                extra={
                    "source": "hook.observe",
                    "cwd": cwd,
                    "cell_record_root": str(cell_record["created_root"]),
                    "cell_record_source": cell_record_source,
                },
            )
            # Same typed write path brain.write delegates to — a LIST of ops.
            try:
                resp = apply_write(
                    store=store,
                    ops=[WriteOp(op=WriteOpType.ADD, fragment=fragment)],
                )
            except Exception as write_error:
                return {
                    "ok": False,
                    "ops_applied": 0,
                    "cell_first": True,
                    "brain_written": False,
                    "cell_record": cell_record,
                    "cell_record_root": str(cell_record["created_root"]),
                    "cell_record_source": cell_record_source,
                    "error": f"{type(write_error).__name__}: {write_error}",
                }
            result = resp.model_dump(mode="json")
            result["ok"] = True
            result["cell_first"] = True
            result["brain_written"] = True
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
            return result
        except Exception as ex:  # a hook must never hard-error
            return {"ok": False, "ops_applied": 0,
                    "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.hook_skill_mint",
        description=(
            "CELL-FIRST Claude Code Stop hook target. Reads the session "
            "transcript JSONL, extracts tool_use/tool_result events, creates a "
            "Universal Cell skill-mint request, then runs the legacy Brain "
            "skill-mint projection. No transcript means soft no-op."
        ),
    )
    def brain_hook_skill_mint(
        session_id: Optional[str] = None,
        transcript_path: Optional[str] = None,
        cwd: Optional[str] = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        try:
            trace = _trace_from_transcript(transcript_path, session_id)
            if trace is None or not trace.get("tool_calls"):
                return {
                    "ok": True,
                    "queued": False,
                    "reason": (
                        "no transcript / no tool calls — skill mint skipped"
                    ),
                }
            owner = resolve_default_owner()
            out = queue_skill_mint_with_cell_receipt(
                store=store,
                trace=trace,
                outcome="success",
                owner_user=owner,
                contributing_agent="claude-code",
                session_id=session_id,
            )
            out["ok"] = True
            return out
        except Exception as ex:  # a hook must never hard-error
            return {"ok": False, "queued": False,
                    "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.hook_session_start",
        description=(
            "CELL-FIRST Claude Code SessionStart hook target. Records the "
            "session wiring through the same Cell-first path brain.wiring_announce "
            "uses, then enrolls the runtime Agent Session when available. "
            "Tolerant of unexpected kwargs; never hard-errors."
        ),
    )
    def brain_hook_session_start(
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
        vendor: Optional[str] = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        try:
            owner = resolve_default_owner()
            device = (session_id or "").strip() or "claude-code-session"
            req = WiringAnnounceRequest(
                device_id=device,
                entries=[],
                secret_refs=[],
                cwd=cwd,
                git_remote=None,
            )
            out = announce_wiring_cell_first(
                store=store,
                req=req,
                owner_user=owner,
            )
            if not out.get("ok"):
                return out
            runtime = (vendor or "unknown").strip() or "unknown"
            if session_id:
                try:
                    graph_session = runtime_session_manager.enroll(
                        runtime=runtime,
                        external_session_id=session_id,
                    )
                    out["universal_runtime_connected"] = True
                    out["universal_agent_session"] = graph_session[
                        "agent_session"
                    ]
                    out["universal_agent_session_reused"] = graph_session[
                        "reused"
                    ]
                except Exception as graph_error:
                    out["universal_runtime_connected"] = False
                    out["universal_runtime_error"] = (
                        f"{type(graph_error).__name__}: {graph_error}"
                    )
            else:
                out["universal_runtime_connected"] = False
                out["universal_runtime_error"] = (
                    "vendor did not provide a session identity"
                )
            return out
        except Exception as ex:  # a hook must never hard-error
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @mcp.tool(
        name="brain.universal_work_status",
        description=(
            "Read Cell-native governed work through an enrolled external "
            "Agent Session. Brain transports the request and owns no work row."
        ),
    )
    def brain_universal_work_status(
        session_id: str,
        vendor: str,
    ) -> dict[str, Any]:
        return runtime_session_manager.work_status(
            runtime=vendor, external_session_id=session_id
        )

    @mcp.tool(
        name="brain.universal_work_next",
        description=(
            "Atomically claim the highest-priority open Cell-native work as "
            "the exact enrolled Agent Session. Brain owns no copied queue."
        ),
    )
    def brain_universal_work_next(
        session_id: str,
        vendor: str,
    ) -> dict[str, Any]:
        return runtime_session_manager.claim_next(
            runtime=vendor, external_session_id=session_id
        )

    @mcp.tool(
        name="brain.universal_work_create",
        description=(
            "Create governed Work directly in the Universal Cell graph for an "
            "enrolled Agent Session. Brain transports the request and does not "
            "write a legacy work ledger."
        ),
    )
    def brain_universal_work_create(
        session_id: str,
        vendor: str,
        title: str,
        external_key: str,
        description: str = "",
        priority: int = 0,
        references: Optional[dict[str, str]] = None,
        structured_references: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return runtime_session_manager.create(
            runtime=vendor,
            external_session_id=session_id,
            title=title,
            description=description,
            priority=priority,
            external_key=external_key,
            references=references,
            structured_references=structured_references,
        )

    @mcp.tool(
        name="brain.universal_work_transition",
        description=(
            "Claim, release, block, or submit Cell-native governed work as the "
            "exact enrolled Agent Session. Graph policy and history decide."
        ),
    )
    def brain_universal_work_transition(
        session_id: str,
        vendor: str,
        work_root: str,
        event: str,
        evidence: str = "",
    ) -> dict[str, Any]:
        return runtime_session_manager.transition(
            runtime=vendor,
            external_session_id=session_id,
            root_id=work_root,
            event=event,
            evidence=evidence,
        )

    @mcp.tool(
        name="brain.universal_work_court",
        description=(
            "Request the application-owned independent court for one submitted "
            "Cell-native work node. The court reruns the graph-declared gate; "
            "the caller cannot choose accept or return."
        ),
    )
    def brain_universal_work_court(
        session_id: str,
        vendor: str,
        work_root: str,
    ) -> dict[str, Any]:
        return runtime_session_manager.adjudicate(
            runtime=vendor,
            external_session_id=session_id,
            root_id=work_root,
        )

    @mcp.tool(
        name="brain.promote",
        description=(
            "CELL-FIRST. "
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
            promoted_dict, report = dict(source_dict), None

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

        source_scope = source_dict.get("scope", "user")
        source_text = str(source_dict.get("text", ""))
        promoted_text = str(promoted_dict.get("text", ""))
        claims = {
            "fragment_id_sha256": hashlib.sha256(
                source.id.encode("utf-8")
            ).hexdigest(),
            "promoted_id_sha256": hashlib.sha256(
                new_id.encode("utf-8")
            ).hexdigest(),
            "source_scope": source_scope,
            "target_scope": target.value,
            "source_kind": source_dict.get("kind"),
            "target_visibility": promoted_dict.get("visibility"),
            "actor_user_sha256": hashlib.sha256(
                actor.user_id.encode("utf-8")
            ).hexdigest(),
            "owner_user_sha256": hashlib.sha256(
                str(source_dict.get("owner_user", "")).encode("utf-8")
            ).hexdigest(),
            "source_text_sha256": hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            "promoted_text_sha256": hashlib.sha256(
                promoted_text.encode("utf-8")
            ).hexdigest(),
            "source_text_len": len(source_text),
            "promoted_text_len": len(promoted_text),
            "redaction_required": bool(decision.redaction_required),
            "redaction_policy_id": report.policy_id if report else None,
            "redaction_findings_count": len(report.findings) if report else 0,
            "target_project_sha256": hashlib.sha256(
                str(target_project_id or "").encode("utf-8")
            ).hexdigest(),
            "target_firm_sha256": hashlib.sha256(
                str(target_firm_id or "").encode("utf-8")
            ).hexdigest(),
            "target_community_sha256": hashlib.sha256(
                str(target_community_id or "").encode("utf-8")
            ).hexdigest(),
        }
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.promote",
                scope="promote",
                claims=claims,
                provenance="personal_brain.server.brain.promote",
            )
        except Exception as exc:
            return {
                "ok": False,
                "promoted": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
                "source_id": source.id,
                "target_scope": target.value,
            }

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
            "ok": True,
            "promoted": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
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
            "CELL-FIRST for new firm writes. "
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
                "cell_first": False,
                "brain_written": False,
            }
        actor = created_by or resolve_default_owner()
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.firm_create",
                scope="firm",
                claims={
                    "name_sha256": hashlib.sha256(
                        name.encode("utf-8")
                    ).hexdigest(),
                    "created_by_sha256": hashlib.sha256(
                        actor.encode("utf-8")
                    ).hexdigest(),
                    "force": bool(force),
                    "existing_firm_sha256": hashlib.sha256(
                        str(existing.firm_id if existing else "").encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.firm_create",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        identity = create_firm(
            store, name=name, created_by=actor,
        )
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
            "firm_id": identity.firm_id, "name": identity.name,
            "root_pub": identity.root_pub,
            "is_admin": True,
        }

    @mcp.tool(
        name="brain.firm_invite_create",
        description=(
            "CELL-FIRST for invite writes. "
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
        from .firm import create_invite_token, current_firm, current_seat
        firm = current_firm(store)
        seat = current_seat(store)
        if firm is None:
            return {"ok": False, "error": "no firm - create_firm first"}
        if not firm.root_priv:
            return {
                "ok": False,
                "error": "this device is not the firm admin - no root_priv available",
            }
        if seat is None or seat.role != "admin":
            return {"ok": False, "error": "only admin can issue invites"}
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.firm_invite_create",
                scope="firm",
                claims={
                    "firm_id_sha256": hashlib.sha256(
                        firm.firm_id.encode("utf-8")
                    ).hexdigest(),
                    "role": role,
                    "ttl_hours": int(ttl_hours),
                    "issued_by_sha256": hashlib.sha256(
                        seat.user_id.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.firm_invite_create",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        try:
            envelope = create_invite_token(
                store, role=role, ttl_hours=ttl_hours,
            )
        except RuntimeError as ex:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "cell_record": cell_record,
                "cell_record_root": str(cell_record["created_root"]),
                "cell_record_source": cell_record_source,
                "error": str(ex),
            }
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
            "token": envelope,
            "role": role,
            "ttl_hours": ttl_hours,
        }

    @mcp.tool(
        name="brain.firm_invite_accept",
        description=(
            "CELL-FIRST for accepted invite writes. "
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
        from .firm import accept_invite_token, verify_invite_token
        invite, ok, reason = verify_invite_token(token)
        if not ok:
            return {"ok": False, "error": f"invite token rejected: {reason}"}
        user = user_id or resolve_default_owner()
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.firm_invite_accept",
                scope="firm",
                claims={
                    "token_sha256": hashlib.sha256(
                        token.encode("utf-8")
                    ).hexdigest(),
                    "firm_id_sha256": hashlib.sha256(
                        invite.firm_id.encode("utf-8")
                    ).hexdigest(),
                    "firm_name_sha256": hashlib.sha256(
                        invite.firm_name.encode("utf-8")
                    ).hexdigest(),
                    "role": invite.role,
                    "issued_by_sha256": hashlib.sha256(
                        invite.issued_by.encode("utf-8")
                    ).hexdigest(),
                    "user_id_sha256": hashlib.sha256(
                        user.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.firm_invite_accept",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        try:
            seat = accept_invite_token(
                store, envelope=token, user_id=user,
            )
        except RuntimeError as ex:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "cell_record": cell_record,
                "cell_record_root": str(cell_record["created_root"]),
                "cell_record_source": cell_record_source,
                "error": str(ex),
            }
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
            "firm_id": seat.firm_id,
            "user_id": seat.user_id,
            "role": seat.role,
            "invited_by": seat.invited_by,
        }

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
            "CELL-FIRST. "
            "Leave the current firm on this device. The seat record "
            "remains visible on other seats until next sync, then gets "
            "pruned."
        ),
    )
    def brain_firm_leave() -> dict[str, Any]:
        from .firm import current_firm, current_seat, leave_firm
        firm = current_firm(store)
        seat = current_seat(store)
        if firm is None and seat is None:
            return {"ok": True, "cell_first": False, "brain_written": False}
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.firm_leave",
                scope="firm",
                claims={
                    "firm_id_sha256": hashlib.sha256(
                        str(firm.firm_id if firm else "").encode("utf-8")
                    ).hexdigest(),
                    "user_id_sha256": hashlib.sha256(
                        str(seat.user_id if seat else "").encode("utf-8")
                    ).hexdigest(),
                    "role": seat.role if seat else "",
                },
                provenance="personal_brain.server.brain.firm_leave",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        leave_firm(store)
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
        }

    # ─────────────────── community (Slice 14 MCP wires) ────────────────

    @mcp.tool(
        name="brain.community_subscribe",
        description=(
            "CELL-FIRST. "
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
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.community_subscribe",
                scope="community",
                claims={
                    "actor_url_sha256": hashlib.sha256(
                        actor_url.encode("utf-8")
                    ).hexdigest(),
                    "display_name_sha256": hashlib.sha256(
                        (display_name or "").encode("utf-8")
                    ).hexdigest(),
                    "owner_user_sha256": hashlib.sha256(
                        owner.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.community_subscribe",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        sub = _community.subscribe(
            store,
            actor_url=actor_url,
            display_name=display_name,
            owner_user=owner,
        )
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
            "subscription": {
                "actor_url": sub.actor_url,
                "display_name": sub.display_name,
                "subscribed_at": sub.subscribed_at,
            },
        }

    @mcp.tool(
        name="brain.community_unsubscribe",
        description=(
            "CELL-FIRST when a subscription exists. "
            "Remove a community subscription by actor_url. Returns "
            "`removed: True` when the row existed; `False` when no such "
            "subscription was registered. Previously-imported community-"
            "scope fragments stay — only the polling link is severed."
        ),
    )
    def brain_community_unsubscribe(actor_url: str) -> dict[str, Any]:
        from . import community as _community
        before = {
            sub.actor_url
            for sub in _community.list_subscriptions(store)
        }
        if actor_url not in before:
            return {
                "ok": True,
                "removed": False,
                "cell_first": False,
                "brain_written": False,
            }
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.community_unsubscribe",
                scope="community",
                claims={
                    "actor_url_sha256": hashlib.sha256(
                        actor_url.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.community_unsubscribe",
            )
        except Exception as exc:
            return {
                "ok": False,
                "removed": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        removed = _community.unsubscribe(store, actor_url)
        return {
            "ok": True,
            "removed": bool(removed),
            "cell_first": True,
            "brain_written": bool(removed),
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
        }

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
        payloads: list[dict[str, Any]] = []
        for result in results:
            payload = _asdict(result)
            payload["cell_first"] = bool(getattr(result, "cell_first", False))
            payload["brain_written"] = bool(getattr(result, "brain_written", False))
            payload["cell_record_root"] = getattr(result, "cell_record_root", None)
            payload["cell_record_source"] = getattr(result, "cell_record_source", None)
            payloads.append(payload)
        return {"ok": True, "results": payloads}

    # ───────────── multi-device community (create / join / converge) ──────
    # Distinct from the federation `community_*` subscription tools above:
    # these create a community the user OWNS + a second device JOINS via a
    # signed join-code, then both converge COMMUNITY-scope fragments through
    # the shared transport (owned Speckle server OR cloud relay).

    @mcp.tool(
        name="brain.community_create",
        description=(
            "CELL-FIRST. "
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
        actor = created_by or resolve_default_owner()
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.community_create",
                scope="community",
                claims={
                    "name_sha256": hashlib.sha256(
                        name.encode("utf-8")
                    ).hexdigest(),
                    "created_by_sha256": hashlib.sha256(
                        actor.encode("utf-8")
                    ).hexdigest(),
                    "transport_kind": tconf.kind,
                    "transport_base_url_sha256": hashlib.sha256(
                        tconf.base_url.encode("utf-8")
                    ).hexdigest(),
                    "transport_note_sha256": hashlib.sha256(
                        tconf.note.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.community_create",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        community = _cg.create_community(
            store, name=name,
            created_by=actor,
            transport=tconf,
        )
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
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
            "CELL-FIRST for accepted joins. "
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
        code_obj, ok, reason = _cg.verify_join_code(code)
        if not ok:
            return {"ok": False, "error": f"join-code rejected: {reason}"}
        member = member_id or resolve_default_owner()
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.community_join",
                scope="community",
                claims={
                    "code_sha256": hashlib.sha256(
                        code.encode("utf-8")
                    ).hexdigest(),
                    "community_id_sha256": hashlib.sha256(
                        code_obj.community_id.encode("utf-8")
                    ).hexdigest(),
                    "name_sha256": hashlib.sha256(
                        code_obj.name.encode("utf-8")
                    ).hexdigest(),
                    "member_id_sha256": hashlib.sha256(
                        member.encode("utf-8")
                    ).hexdigest(),
                    "role": code_obj.role,
                    "issued_by_sha256": hashlib.sha256(
                        code_obj.issued_by.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.community_join",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        try:
            community = _cg.join_community(
                store, envelope=code,
                member_id=member,
            )
        except RuntimeError as ex:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "cell_record": cell_record,
                "cell_record_root": str(cell_record["created_root"]),
                "cell_record_source": cell_record_source,
                "error": str(ex),
            }
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
            "community": community.to_safe_dict(),
            "is_owner": False,
        }

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
            "CELL-FIRST when a community exists. "
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
        current = _cg.current_community(store)
        if current is None:
            return {
                "ok": False,
                "error": "no community on this device",
                "cell_first": False,
                "brain_written": False,
            }
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.community_set_transport",
                scope="community",
                claims={
                    "community_id_sha256": hashlib.sha256(
                        current.community_id.encode("utf-8")
                    ).hexdigest(),
                    "transport_kind": tconf.kind,
                    "transport_base_url_sha256": hashlib.sha256(
                        tconf.base_url.encode("utf-8")
                    ).hexdigest(),
                    "transport_note_sha256": hashlib.sha256(
                        tconf.note.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server.brain.community_set_transport",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        community = _cg.set_transport(store, tconf)
        if community is None:
            return {"ok": False, "error": "no community on this device"}
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
            "community": community.to_safe_dict(),
        }

    @mcp.tool(
        name="brain.community_leave",
        description=(
            "CELL-FIRST when membership exists. "
            "Leave the current multi-device community on this device. "
            "Tombstones this device's member fragment so the roster "
            "converges on other devices after their next sync. The "
            "community record + any COMMUNITY-scope fragments stay until "
            "pruned. Reversible: re-join with a fresh join-code."
        ),
    )
    def brain_community_leave() -> dict[str, Any]:
        from . import community_groups as _cg
        current = _cg.current_community(store)
        if current is None:
            return {"ok": True, "cell_first": False, "brain_written": False}
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.community_leave",
                scope="community",
                claims={
                    "community_id_sha256": hashlib.sha256(
                        current.community_id.encode("utf-8")
                    ).hexdigest(),
                    "created_by_sha256": hashlib.sha256(
                        current.created_by.encode("utf-8")
                    ).hexdigest(),
                    "role": current.role,
                },
                provenance="personal_brain.server.brain.community_leave",
            )
        except Exception as exc:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"cell unavailable: {exc}",
            }
        _cg.leave_community(store)
        return {
            "ok": True,
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
        }

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
            "CELL-FIRST owner binding. Persists the "
            "cloud `user_id` (+ optional email / display_name) to brain_meta "
            "so every fragment, skill, and wiring write that falls back to the "
            "default owner is owned by that user_id — not by $USER / 'founder'. "
            "Takes effect IN-PROCESS immediately (no daemon restart) and "
            "survives restarts (persisted). Call this right after cloud "
            "sign-in. Refuses the Brain binding if the Universal Cell receipt "
            "cannot be created."
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
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.set_owner",
                scope="owner-binding",
                claims={
                    "previous_owner_sha256": hashlib.sha256(
                        str(previously or "").encode("utf-8")
                    ).hexdigest(),
                    "target_owner_sha256": hashlib.sha256(
                        uid.encode("utf-8")
                    ).hexdigest(),
                    "target_owner_len": len(uid),
                    "email_present": bool((email or "").strip()),
                    "email_sha256": hashlib.sha256(
                        (email or "").strip().encode("utf-8")
                    ).hexdigest(),
                    "display_name_present": bool((display_name or "").strip()),
                    "display_name_sha256": hashlib.sha256(
                        (display_name or "").strip().encode("utf-8")
                    ).hexdigest(),
                    "effective_fallback_sha256": hashlib.sha256(
                        fallback_owner.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server:set_owner",
            )
        except Exception as cell_error:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "owner_user": resolve_default_owner(),
                "previously": previously,
                "error": f"{type(cell_error).__name__}: {cell_error}",
            }
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
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
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
            "CELL-FIRST owner unbinding. "
            "Removes the persisted owner binding so the default owner reverts "
            "to env / OS / 'founder'. The brain DATA stays — only the binding "
            "is cleared; previously-bound fragments keep their owner_user. "
            "Refuses the Brain clear if the Universal Cell receipt cannot be "
            "created."
        ),
    )
    def brain_clear_owner() -> dict[str, Any]:
        previously = _bound_owner()
        try:
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.clear_owner",
                scope="owner-binding",
                claims={
                    "previous_owner_sha256": hashlib.sha256(
                        str(previously or "").encode("utf-8")
                    ).hexdigest(),
                    "had_binding": previously is not None,
                    "effective_fallback_sha256": hashlib.sha256(
                        fallback_owner.encode("utf-8")
                    ).hexdigest(),
                },
                provenance="personal_brain.server:clear_owner",
            )
        except Exception as cell_error:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "owner_user": resolve_default_owner(),
                "bound": previously is not None,
                "previously": previously,
                "cleared": False,
                "error": f"{type(cell_error).__name__}: {cell_error}",
            }
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
            "cell_first": True,
            "brain_written": True,
            "cell_record": cell_record,
            "cell_record_root": str(cell_record["created_root"]),
            "cell_record_source": cell_record_source,
        }

    @mcp.tool(
        name="brain.liveness",
        description="Transport-safe local liveness and server identity for supervised clients.",
    )
    def brain_liveness() -> dict[str, Any]:
        """Return only transport and in-memory worker evidence.

        The process supervisor and BABOOM call this endpoint while recovering
        from a busy or locked Brain store.  Do not add persistent-store reads
        here: counts and wiring diagnostics belong to ``brain.health``.  A
        response proves this MCP handler is serving, while the worker snapshot
        states whether the in-memory engine is ready.
        """
        engine: dict[str, Any] = {"started": False, "workers": {}}
        try:
            from .workers import get_supervisor
            sup = get_supervisor(store)
            if sup is not None:
                engine = sup.status()
        except Exception as ex:
            engine = {"started": False, "error": f"{type(ex).__name__}: {ex}"}
        return {
            "ok": True,
            "server_pid": os.getpid(),
            "engine": engine,
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
            "server_pid": os.getpid(),
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
                "provenance": sk.provenance.model_dump(mode="json"),
                "minted_at": sk.minted_at.isoformat(),
                "honed_trials": sk.honed_trials,
                "honed_passed": sk.honed_passed,
                "side_effects": sk.side_effects,
                "success_count": sk.success_count,
                "fail_count": sk.fail_count,
                "mint_evidence": dict(sk.mint_evidence or {}),
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
            "CELL-FIRST. "
            "Brain #32 (founder ask 2026-05-26): export fragments as a "
            "HuggingFace-style training dataset. Writes JSONL primary + "
            "optional parquet (if pyarrow installed) + manifest.json. "
            "Defaults to USER scope only — never escalates without "
            "explicit scope_filter. The AgDR-0054 legal/training-rights dam "
            "runs at export: quarantined (right-to-be-forgotten / poisoned) "
            "rows are ALWAYS dropped, and training_target='collective' also "
            "drops firm_private_only rows (pass it when seeding the cross-firm "
            "collective pool; default 'firm_private' is the legal floor). Used "
            "to seed collective model training (Brain #33 north star)."
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
        respect_training_rights: bool = True,
        training_target: str = "firm_private",
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
            owner = owner_user or resolve_default_owner()
            scope_values = [s.value for s in scope_filter]
            kind_values = [
                k.value if hasattr(k, "value") else str(k)
                for k in (kind_filter or [])
            ]
            claims = {
                "out_dir_sha256": hashlib.sha256(
                    str(out_dir).encode("utf-8")
                ).hexdigest(),
                "dataset_name_sha256": hashlib.sha256(
                    str(dataset_name).encode("utf-8")
                ).hexdigest(),
                "scopes": scope_values,
                "kinds": kind_values,
                "since_sha256": hashlib.sha256(
                    str(since or "").encode("utf-8")
                ).hexdigest(),
                "limit": int(limit),
                "owner_user_sha256": hashlib.sha256(
                    owner.encode("utf-8")
                ).hexdigest(),
                "respect_training_rights": bool(respect_training_rights),
                "training_target": training_target,
            }
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.dataset_export",
                scope="dataset-export",
                claims=claims,
                provenance="personal_brain.server.brain.dataset_export",
            )
            manifest = _de.export_fragments(
                store,
                _P(out_dir),
                dataset_name=dataset_name,
                scope_filter=scope_filter,
                kinds=kind_filter,
                since=since,
                limit=int(limit),
                owner_user=owner,
                respect_training_rights=respect_training_rights,
                training_target=training_target,
            )
            manifest["cell_first"] = True
            manifest["brain_written"] = True
            manifest["cell_record"] = cell_record
            manifest["cell_record_root"] = str(cell_record["created_root"])
            manifest["cell_record_source"] = cell_record_source
            return manifest
        except Exception as ex:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"{type(ex).__name__}: {ex}",
            }

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
            "CELL-FIRST for inbound writes. "
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

        write_candidates: list[_F] = []
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
                write_candidates.append(frag)
            except Exception:
                refused += 1
        if write_candidates:
            candidate_claims: list[dict[str, Any]] = []
            for frag in write_candidates:
                scope_val = (
                    frag.scope.value
                    if hasattr(frag.scope, "value")
                    else str(frag.scope)
                )
                kind_val = (
                    frag.kind.value
                    if hasattr(frag.kind, "value")
                    else str(frag.kind)
                )
                text = frag.text or ""
                candidate_claims.append({
                    "fragment_id_sha256": hashlib.sha256(
                        frag.id.encode("utf-8")
                    ).hexdigest(),
                    "scope": scope_val,
                    "kind": kind_val,
                    "text_sha256": hashlib.sha256(
                        text.encode("utf-8")
                    ).hexdigest(),
                    "text_len": len(text),
                    "owner_user_sha256": hashlib.sha256(
                        (frag.owner_user or "").encode("utf-8")
                    ).hexdigest(),
                    "firm_id_sha256": hashlib.sha256(
                        str(frag.firm_id or "").encode("utf-8")
                    ).hexdigest(),
                    "hlc_sha256": hashlib.sha256(
                        str(getattr(frag.provenance, "hlc", "") or "").encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                })
            claims = {
                "candidate_count": len(write_candidates),
                "skipped_count": skipped,
                "refused_count": refused,
                "fragments": candidate_claims,
            }
            try:
                cell_record, cell_record_source = (
                    create_brain_control_cell_receipt(
                        operation="brain.fanout_apply",
                        scope="fanout-apply",
                        claims=claims,
                        provenance="personal_brain.server.brain.fanout_apply",
                    )
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "applied": 0,
                    "skipped": skipped,
                    "refused": refused,
                    "cell_first": True,
                    "brain_written": False,
                    "error": f"cell unavailable: {exc}",
                }
        else:
            cell_record = None
            cell_record_source = ""

        applied = 0
        for frag in write_candidates:
            try:
                store.write_fragment(frag)
                applied += 1
            except Exception:
                refused += 1
        result = {
            "ok": True,
            "applied": applied,
            "skipped": skipped,
            "refused": refused,
            "cell_first": bool(write_candidates),
            "brain_written": bool(applied),
        }
        if cell_record is not None:
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
        return result

    @mcp.tool(
        name="brain.cloud_archive",
        description=(
            "CELL-FIRST for upload-capable archive requests. "
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
            local_path = _P(local_dir)
            # Preserve clean local guard branches without requiring the Cell
            # runtime when no upload can happen.
            if (
                not _ca._is_boto3_available()
                or not local_path.exists()
            ):
                return _ca.upload_dataset(
                    local_path,
                    bucket=bucket,
                    endpoint_url=endpoint_url,
                    region=region,
                    access_key_ref=access_key_ref,
                    secret_key_ref=secret_key_ref,
                    prefix=prefix,
                    dataset_name=dataset_name,
                    include_blobs=include_blobs,
                    blob_store_root=(
                        _P(blob_store_root) if blob_store_root else None
                    ),
                )
            claims = {
                "local_dir_sha256": hashlib.sha256(
                    str(local_path).encode("utf-8")
                ).hexdigest(),
                "bucket_sha256": hashlib.sha256(
                    bucket.encode("utf-8")
                ).hexdigest(),
                "endpoint_url_sha256": hashlib.sha256(
                    str(endpoint_url or "").encode("utf-8")
                ).hexdigest(),
                "region": region,
                "access_key_ref_sha256": hashlib.sha256(
                    str(access_key_ref or "").encode("utf-8")
                ).hexdigest(),
                "secret_key_ref_sha256": hashlib.sha256(
                    str(secret_key_ref or "").encode("utf-8")
                ).hexdigest(),
                "prefix_sha256": hashlib.sha256(
                    prefix.encode("utf-8")
                ).hexdigest(),
                "dataset_name_sha256": hashlib.sha256(
                    str(dataset_name or local_path.name).encode("utf-8")
                ).hexdigest(),
                "include_blobs": bool(include_blobs),
                "blob_store_root_sha256": hashlib.sha256(
                    str(blob_store_root or "").encode("utf-8")
                ).hexdigest(),
            }
            cell_record, cell_record_source = create_brain_control_cell_receipt(
                operation="brain.cloud_archive",
                scope="cloud-archive",
                claims=claims,
                provenance="personal_brain.server.brain.cloud_archive",
            )
            archive_result = _ca.upload_dataset(
                local_path,
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
            archive_result["cell_first"] = True
            archive_result["brain_written"] = bool(
                archive_result.get("ok")
                and archive_result.get("uploaded_count", 0)
            )
            archive_result["cell_record"] = cell_record
            archive_result["cell_record_root"] = str(cell_record["created_root"])
            archive_result["cell_record_source"] = cell_record_source
            return archive_result
        except Exception as ex:
            return {
                "ok": False,
                "cell_first": True,
                "brain_written": False,
                "error": f"{type(ex).__name__}: {ex}",
            }

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
            "READ/SET accessibility preferences. Get is read-only. Set is "
            "CELL-FIRST: a Universal Cell governance receipt with hashed "
            "preference evidence is created before the legacy Brain preference "
            "projection is written. If the Cell receipt fails, preferences are "
            "not changed."
        ),
    )
    def brain_a11y_prefs(
        mode: str = "get",
        prefs: Optional[dict[str, Any]] = None,
        owner_user: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_user or resolve_default_owner()
        if hasattr(store, "a11y_prefs"):
            requested_mode = str(mode or "get").strip().lower()
            if requested_mode != "set":
                result = store.a11y_prefs(
                    mode=requested_mode,
                    prefs=prefs,
                    owner_user=owner,
                )
                result["cell_first"] = False
                result["brain_written"] = False
                return result
            if not isinstance(prefs, dict):
                result = store.a11y_prefs(
                    mode=requested_mode,
                    prefs=prefs,
                    owner_user=owner,
                )
                result["cell_first"] = False
                result["brain_written"] = False
                return result
            current = store.a11y_prefs(
                mode="get",
                prefs=None,
                owner_user=owner,
            ).get("prefs", {})
            proposed = {**dict(current or {}), **prefs}
            try:
                cell_record, cell_record_source = create_brain_control_cell_receipt(
                    operation="brain.a11y_prefs.set",
                    scope="a11y-prefs",
                    claims={
                        "owner_user_sha256": hashlib.sha256(
                            owner.encode("utf-8")
                        ).hexdigest(),
                        "keys": sorted(str(key) for key in prefs),
                        "patch_sha256": hashlib.sha256(
                            json.dumps(
                                prefs,
                                sort_keys=True,
                                default=str,
                            ).encode("utf-8")
                        ).hexdigest(),
                        "current_sha256": hashlib.sha256(
                            json.dumps(
                                current,
                                sort_keys=True,
                                default=str,
                            ).encode("utf-8")
                        ).hexdigest(),
                        "proposed_sha256": hashlib.sha256(
                            json.dumps(
                                proposed,
                                sort_keys=True,
                                default=str,
                            ).encode("utf-8")
                        ).hexdigest(),
                        "scope": "user",
                    },
                    provenance="personal_brain.server:a11y_prefs",
                )
            except Exception as cell_error:
                return {
                    "ok": False,
                    "mode": "set",
                    "cell_first": True,
                    "brain_written": False,
                    "prefs": current,
                    "error": f"{type(cell_error).__name__}: {cell_error}",
                }
            result = store.a11y_prefs(
                mode=requested_mode,
                prefs=prefs,
                owner_user=owner,
            )
            result["cell_first"] = True
            result["brain_written"] = bool(result.get("ok"))
            result["cell_record"] = cell_record
            result["cell_record_root"] = str(cell_record["created_root"])
            result["cell_record_source"] = cell_record_source
            return result
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

    # BRV-01 compatibility registration. active_work_v1 is migration evidence;
    # public legacy routes refuse and graph-session Work owns creation, claims,
    # transitions, status, and courts. Fail-soft like the families above so the
    # core tools never depend on this compatibility surface building.
    try:
        from .active_work import register_active_work_tools
        register_active_work_tools(mcp, store)
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] active_work tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    # MEETING ROOM (founder, 2026-07-17): the brain as an ACTIVE communication
    # channel — a live workshop, not a log. brain.room_say/read/presence tools
    # + GET /room live page on this same daemon; the room's unread tail is
    # appended to every brain.context injection (see _room_tail in the context
    # path), so every agent HEARS the room each turn.
    try:
        from .cell_room_wiring import (
            register_unavailable_cell_room_tools,
            wire_cell_room,
        )
        try:
            wire_cell_room(mcp, store)
        except Exception as ex:
            error = f"{type(ex).__name__}: {ex}"
            print(
                "[brain] runtime Workshop unavailable; "
                f"registering fail-closed room tools: {error}",
                file=sys.stderr,
                flush=True,
            )
            register_unavailable_cell_room_tools(mcp, error)
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] room registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    # Brain-owned run reports. These are the per-run governance nodes agents
    # must write before active work can be marked complete.
    try:
        from .run_report import register_run_report_tools
        register_run_report_tools(
            mcp, store, cell_bridge=governance_cell_bridge
        )
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] run_report tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    # Brain-owned client hook coverage ledger. The installer is a legacy
    # repair path for per-client wiring; these tools audit/repair that wiring
    # and persist hook_coverage_v1 in brain_meta so work assignment can refuse
    # write-capable claims when a runtime's hooks are red.
    try:
        from .hook_coverage import register_hook_coverage_tools
        register_hook_coverage_tools(
            mcp, store, cell_bridge=governance_cell_bridge
        )
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] hook_coverage tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    # Grand Map -> CDE -> active_work compiler. This turns the actual plan into
    # Brain-owned leaves so agents pull governed work instead of inventing it.
    try:
        from .grand_map_sync import register_grand_map_sync_tools
        register_grand_map_sync_tools(mcp, store)
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] grand_map_sync tools registration skipped: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    # Single governance status surface: hook coverage + active work + active
    # CDE state + last pre-tool gate decision.
    try:
        from .compliance_report import register_compliance_report_tools
        register_compliance_report_tools(
            mcp, store, cell_bridge=governance_cell_bridge
        )
    except Exception as ex:  # pragma: no cover - never block server build
        print(f"[brain] compliance_report tool registration skipped: "
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
    from .community import CommunityPoller, PollResult, list_subscriptions
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
    class CellFirstCommunityPoller(CommunityPoller):
        def tick(self) -> list[Any]:
            subs = list_subscriptions(self.store)
            if not subs:
                return []
            try:
                cell_record, cell_record_source = create_brain_control_cell_receipt(
                    operation="brain.community_poll_now",
                    scope="community",
                    claims={
                        "firm_id_sha256": hashlib.sha256(
                            firm_id.encode("utf-8")
                        ).hexdigest(),
                        "subscription_count": len(subs),
                        "actor_url_hashes": [
                            hashlib.sha256(
                                sub.actor_url.encode("utf-8")
                            ).hexdigest()
                            for sub in subs
                        ],
                    },
                    provenance="personal_brain.server.brain.community_poll_now",
                )
            except Exception as exc:
                results = []
                for sub in subs:
                    result = PollResult(
                        actor_url=sub.actor_url,
                        ok=False,
                        error=f"cell unavailable: {exc}",
                    )
                    result.cell_first = True
                    result.brain_written = False
                    results.append(result)
                self._cycle_count += 1
                self._last_results = results
                return results
            results = super().tick()
            for result in results:
                result.cell_first = True
                result.brain_written = bool(result.ok)
                result.cell_record_root = str(cell_record["created_root"])
                result.cell_record_source = cell_record_source
            return results

    poller = CellFirstCommunityPoller(store, driver)
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


# ── hook-wrapper helpers (Claude Code hook payloads → brain calls) ──────


_SECRET_PREFIXES = ("op://", "vault://", "wcm://", "sk-", "ghp_", "AKIA",
                    "ya29.")


def _redact_hook_value(obj: Any) -> Any:
    """Recursively replace secret-shaped strings with `<secret>` so a captured
    tool payload never lands secrets in memory. Mirrors
    app/memory_gate._strip_secrets — ONE policy, two call sites."""
    if isinstance(obj, str):
        if any(obj.startswith(p) for p in _SECRET_PREFIXES):
            return "<secret>"
        return obj
    if isinstance(obj, dict):
        return {k: _redact_hook_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_hook_value(v) for v in obj]
    return obj


def _summarise_hook_value(obj: Any, *, limit: int = 160) -> str:
    """Compact one-line summary of a hook payload value (tool_input /
    tool_response) for the fragment text. Claude Code may send these as a JSON
    string OR an already-parsed object — handle both. Never raises."""
    if obj is None:
        return "∅"
    # Claude Code interpolates ${tool_input} as a JSON STRING — try to parse
    # it so the summary reflects structure, but fall back to the raw string.
    if isinstance(obj, str):
        s = obj.strip()
        if s[:1] in ("{", "[") and s[-1:] in ("}", "]"):
            try:
                import json as _json
                obj = _json.loads(s)
            except Exception:
                return s[:limit]
        else:
            return s[:limit] if s else "∅"
    if isinstance(obj, (int, float, bool)):
        return str(obj)[:limit]
    if isinstance(obj, dict):
        keys = sorted(str(k) for k in obj.keys())[:6]
        return ("keys{" + ", ".join(keys) + "}")[:limit]
    if isinstance(obj, list):
        return f"list[{len(obj)}]"
    return type(obj).__name__


def _trace_from_transcript(
    transcript_path: Optional[str], session_id: Optional[str]
) -> Optional[dict[str, Any]]:
    """Build a skill_mint trace from a Claude Code transcript JSONL.

    The transcript is one JSON object per line (the agent's message stream).
    We walk it for tool-use + tool-result events and emit a
    `{trace_id, tool_calls:[{name, status}], outcome, user_message}` trace
    shaped exactly like the one queue_skill_mint expects (it reads
    `tool_calls[*].status == 'ok'`). Returns None when the file is missing /
    unreadable / has no tool calls. Never raises."""
    if not transcript_path:
        return None
    try:
        from pathlib import Path as _Path
        import json as _json

        p = _Path(transcript_path)
        if not p.exists():
            return None

        tool_calls: list[dict[str, Any]] = []
        # tool_use_id → index in tool_calls, so a later tool_result can flip
        # that call's status from the result's is_error flag.
        by_use_id: dict[str, int] = {}
        user_message = ""

        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = _json.loads(line)
            except Exception:
                continue
            if not isinstance(evt, dict):
                continue

            msg = evt.get("message") if isinstance(evt.get("message"), dict) else evt
            role = msg.get("role") or evt.get("type")
            content = msg.get("content")

            # Capture the first real user prompt for the trace summary.
            if role == "user" and not user_message:
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            user_message = str(block.get("text") or "")
                            break

            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    name = str(block.get("name") or "tool")
                    idx = len(tool_calls)
                    tool_calls.append({"name": name, "status": "ok"})
                    uid = block.get("id")
                    if isinstance(uid, str):
                        by_use_id[uid] = idx
                elif btype == "tool_result":
                    uid = block.get("tool_use_id")
                    if isinstance(uid, str) and uid in by_use_id:
                        if block.get("is_error"):
                            tool_calls[by_use_id[uid]]["status"] = "error"

        if not tool_calls:
            return None
        return {
            "trace_id": session_id or p.stem,
            "session_id": session_id,
            "tool_calls": tool_calls,
            "outcome": "success",
            "user_message": user_message[:200],
        }
    except Exception:
        return None


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


def _start_http_runtime_services(server: Any, owner: Optional[str]) -> None:
    """Start heavy ambient services after the HTTP listener is available."""
    try:
        from .workers import start_workers, workers_enabled

        bound_store = getattr(server, "_brain_store", None)
        if bound_store is not None:
            sup = start_workers(bound_store, owner_user=owner)
            if sup is not None:
                st = sup.status()
                alive = [
                    name for name, worker in st.get("workers", {}).items()
                    if isinstance(worker, dict) and worker.get("alive")
                ]
                print(
                    f"[brain] engine ON - workers alive: {', '.join(alive) or 'none'}"
                    + (f" | errors: {st['errors']}" if st.get("errors") else ""),
                    file=sys.stderr,
                    flush=True,
                )
            elif not workers_enabled():
                print(
                    "[brain] engine OFF - BRAIN_WORKERS disabled",
                    file=sys.stderr,
                    flush=True,
                )
    except Exception as ex:
        print(
            f"[brain] engine start error: {type(ex).__name__}: {ex}",
            file=sys.stderr,
            flush=True,
        )

    try:
        from .hook_coverage import (
            hook_coverage_auto_repair_enabled,
            hook_coverage_monitor_enabled,
            start_hook_coverage_monitor,
        )

        bound_store = getattr(server, "_brain_store", None)
        if bound_store is not None:
            mon = start_hook_coverage_monitor(
                bound_store,
                owner_user=owner or "founder",
                auto_repair=hook_coverage_auto_repair_enabled(),
                cell_bridge=getattr(server, "_brain_governance_cell_bridge", None),
            )
            if mon is not None:
                st = mon.status()
                last = st.get("last_report") or {}
                print(
                    "[brain] hook coverage monitor ON"
                    f" - status: {last.get('status', 'unknown')}"
                    f" | interval_s: {st.get('interval_s')}",
                    file=sys.stderr,
                    flush=True,
                )
            elif not hook_coverage_monitor_enabled():
                print(
                    "[brain] hook coverage monitor OFF",
                    file=sys.stderr,
                    flush=True,
                )
    except Exception as ex:
        print(
            "[brain] hook coverage monitor error: "
            f"{type(ex).__name__}: {ex}",
            file=sys.stderr,
            flush=True,
        )


def _http_runtime_services_suspended() -> tuple[bool, str]:
    """Return an explicit operator suspension without disabling MCP service."""
    configured = os.environ.get("BRAIN_HTTP_RUNTIME_SERVICES", "").strip().lower()
    if configured in {"0", "off", "false", "no"}:
        return True, "BRAIN_HTTP_RUNTIME_SERVICES"
    if configured in {"1", "on", "true", "yes"}:
        return False, ""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return False, ""
    marker = (
        Path(local_app_data)
        / "ArchHub"
        / "brain"
        / "ambient-runtime.suspended"
    )
    return marker.is_file(), str(marker) if marker.is_file() else ""


def _start_http_runtime_services_after_bind(
    server: Any,
    *,
    owner: Optional[str],
    host: str,
    port: int,
    wait_timeout_s: float = 60.0,
    poll_interval_s: float = 0.25,
) -> threading.Thread:
    """Wait for the real listener, then start workers and hook monitoring."""
    def run() -> None:
        deadline = time.monotonic() + max(0.0, wait_timeout_s)
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((host, int(port)), timeout=0.2):
                    _start_http_runtime_services(server, owner)
                    return
            except OSError:
                time.sleep(max(0.01, poll_interval_s))
        print(
            "[brain] runtime services not started: HTTP listener did not bind "
            f"within {wait_timeout_s:.1f}s",
            file=sys.stderr,
            flush=True,
        )

    thread = threading.Thread(
        target=run,
        name="brain-http-runtime-start",
        daemon=True,
    )
    thread.start()
    return thread


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
    parser.add_argument(
        "--local-stdio",
        "--standalone-stdio",
        dest="local_stdio",
        action="store_true",
        help=(
            "Run a local stdio Brain instead of proxying to the singleton. "
            "Use only for explicitly isolated/manual maintenance."
        ),
    )
    args = parser.parse_args(argv)
    if args.http is not None and args.local_stdio:
        parser.error("--local-stdio cannot be combined with --http")

    if args.http is None and not args.local_stdio:
        # No-arg stdio is the cached-client compatibility path. It must never
        # construct a second full Brain silently; it either reuses the healthy
        # singleton HTTP daemon or exits nonzero.
        _run_stdio_singleton_proxy_if_available()
        return

    # Provision the independent Court's signing capability before accepting
    # work. Only the reference and availability metadata are logged; the key
    # remains inside the OS credential store and is resolved only when signing.
    try:
        from .server_verify import ensure_court_signing_key

        key_status = ensure_court_signing_key()
        if key_status.get("ok"):
            disposition = "created" if key_status.get("created") else "existing"
            print(
                "[brain] court signing capability READY"
                f" - {disposition} | ref: {key_status.get('ref')}"
                f" | backend: {key_status.get('backend')}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                "[brain] court signing capability UNAVAILABLE"
                f" | ref: {key_status.get('ref')}"
                f" | reason: {key_status.get('reason', 'unknown')}",
                file=sys.stderr,
                flush=True,
            )
    except Exception as ex:
        # The daemon remains available for read-only work, while Court verdicts
        # continue to fail closed until the capability can be provisioned.
        print(
            "[brain] court signing capability UNAVAILABLE"
            f" | reason: {type(ex).__name__}",
            file=sys.stderr,
            flush=True,
        )

    server = build_server(db_path=args.db, default_owner_user=args.owner)

    if args.http is not None:
        # Bind the real MCP endpoint before the expensive workers and hook audit.
        # The supervisor can prove liveness instead of killing a healthy process
        # that is still warming its ambient services.
        host = os.environ.get("BRAIN_HTTP_HOST", "127.0.0.1")
        suspended, suspension_source = _http_runtime_services_suspended()
        if suspended:
            print(
                "[brain] ambient runtime services SUSPENDED"
                f" - source: {suspension_source}",
                file=sys.stderr,
                flush=True,
            )
        else:
            _start_http_runtime_services_after_bind(
                server,
                owner=args.owner,
                host=host,
                port=args.http,
            )
        server.run(
            transport="http",
            host=host,
            port=args.http,
            stateless_http=True,
        )
        return

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

    # Hook coverage compliance monitor. Startup performs an immediate audit and
    # persists hook_coverage_v1; the daemon thread keeps the report fresh so
    # write-capable work assignment is gated by current client wiring.
    try:
        from .hook_coverage import (
            hook_coverage_auto_repair_enabled,
            hook_coverage_monitor_enabled,
            start_hook_coverage_monitor,
        )
        bound_store = getattr(server, "_brain_store", None)
        if bound_store is not None:
            mon = start_hook_coverage_monitor(
                bound_store,
                owner_user=args.owner or "founder",
                auto_repair=hook_coverage_auto_repair_enabled(),
                cell_bridge=getattr(server, "_brain_governance_cell_bridge", None),
            )
            if mon is not None:
                st = mon.status()
                last = st.get("last_report") or {}
                print(
                    "[brain] hook coverage monitor ON"
                    f" — status: {last.get('status', 'unknown')}"
                    f" | interval_s: {st.get('interval_s')}",
                    file=sys.stderr, flush=True,
                )
            elif not hook_coverage_monitor_enabled():
                print("[brain] hook coverage monitor OFF",
                      file=sys.stderr, flush=True)
    except Exception as ex:  # never block daemon boot on coverage audit
        print(f"[brain] hook coverage monitor error: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

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


def _run_stdio_singleton_proxy_if_available() -> bool:
    try:
        from .stdio_http_proxy import (
            run_stdio_proxy_if_healthy,
        )

        if run_stdio_proxy_if_healthy():
            return True
        raise RuntimeError("singleton proxy disabled for default stdio launch")
    except Exception as ex:
        print(
            "[brain] stdio singleton guard FAIL-CLOSED"
            f" - {type(ex).__name__}: {ex}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2) from ex


def main_stdio(argv: Optional[list[str]] = None) -> None:
    """No-arg stdio entrypoint for client configs; proxies to the singleton."""
    main(argv=[] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover
    main()
