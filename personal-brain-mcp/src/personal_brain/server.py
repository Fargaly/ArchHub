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
    else:
        final_reason += "will hone via reflexion worker (R1+R2 gates passed)"

    return SkillMintResult(
        queued=True,
        proposed_name=proposed_name,
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
        from fastmcp import FastMCP
    except ImportError as ex:  # pragma: no cover
        raise RuntimeError(
            "fastmcp not installed. `pip install fastmcp` "
            "(or `pip install personal-brain-mcp[server]`)"
        ) from ex

    if store is None:
        store = BrainStore.open(db_path)

    default_owner = (
        default_owner_user
        or os.environ.get("BRAIN_OWNER_USER")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "founder"
    )

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
        owner = owner_user or default_owner
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
            user_id=(seat.user_id if seat else default_owner),
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
        owner = owner_user or default_owner
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
        owner = owner_user or default_owner
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
            user_id=owner_user or default_owner,
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
            store, name=name, created_by=created_by or default_owner,
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
                store, envelope=token, user_id=user_id or default_owner,
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
        owner = owner_user or default_owner
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

    @mcp.tool(
        name="brain.health",
        description="Diagnostic: counts of skills, facts, wiring entries, brain db path.",
    )
    def brain_health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": "0.1.0",
            "db_path": str(store.path),
            "skills": store.count_skills(),
            "facts": store.count_fragments(Scope.USER) + store.count_fragments(Scope.PROJECT),
            "wiring_active": len(store.list_wiring()),
            "owner_user_default": default_owner,
        }

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

    if args.http is not None:
        # FastMCP 3.3.1 verified — `transport="http"` is the canonical
        # Streamable HTTP option. `stateless_http=True` skips session
        # tracking so ArchHub's BrainClient (synchronous, in-process)
        # doesn't have to maintain Mcp-Session-Id state between hooks.
        host = os.environ.get("BRAIN_HTTP_HOST", "127.0.0.1")
        try:
            server.run(transport="http", host=host, port=args.http,
                       stateless_http=True)
        except TypeError:
            # Older fastmcp without stateless_http kwarg — try plain http.
            try:
                server.run(transport="http", host=host, port=args.http)
            except TypeError:
                # Legacy fastmcp — last-resort streamable-http
                server.run(transport="streamable-http",
                           host=host, port=args.http)
        return

    # stdio is the default
    try:
        server.run(transport="stdio")
    except TypeError:
        # fastmcp <0.4 fallback
        server.run()


def main_stdio(argv: Optional[list[str]] = None) -> None:
    """Explicit stdio entrypoint for client configs that expect a no-arg
    command."""
    main(argv=[] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover
    main()
