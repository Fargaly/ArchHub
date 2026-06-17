"""FastAPI HTTP server for the federation tier.

AgDR-0044 Slice 8 (real HTTP impl over the federation primitives).

Routes:

    GET  /actor              — ActivityPub Actor JSON-LD
    GET  /outbox             — OrderedCollection of published Activities
    GET  /patterns/{hash}    — single Pattern by content-addressed hash
    POST /inbox              — receive incoming Activity from peer firms
    POST /publish            — local convenience: derive + DP-noise + publish
                               local skills/traces into the outbox
    GET  /reputation/{hash}  — read reputation of a contributor firm
    GET  /healthz            — liveness

Mounts onto any ASGI host (uvicorn, Hypercorn, behind nginx).
Authentication: simple bearer token via `BRAIN_FEDERATION_TOKEN`.
Per arXiv 2505.18279, every inbox POST also logs provenance to the
access log.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore

from .federation import (
    ActivityRecord,
    ContributorReputation,
    FederationDriver,
    ImportDecision,
    Outbox,
    Pattern,
    evaluate_incoming_pattern,
    pattern_to_activity,
)
from .publish_worker import (
    load_outbox_from_brain,
    persist_activity_to_brain,
)
from .storage import BrainStore


# ─────────────────────── reputation persistence (BRV-11) ───────────────
#
# The reputation registry used to be a process-local `dict` that vanished on
# restart. Persist it through the SAME brain store the rest of the federation
# tier already uses (ONE-SYSTEM) — `brain_meta`, the additive key/value store
# that requirement_tree / active_work / publish_worker all ride. No new table.

_META_REPUTATION_PREFIX = "federation.reputation."


def _reputation_meta_key(contributor_hash: str) -> str:
    return f"{_META_REPUTATION_PREFIX}{contributor_hash}"


def save_reputation_to_brain(
    store: BrainStore, rep: ContributorReputation,
) -> None:
    """Persist one contributor reputation so it survives a daemon restart.

    Stored as a JSON doc under a per-contributor `brain_meta` key. The score is
    a derived property (not stored) — only the counts + avg_quality_score that
    feed it are persisted, so the reload reconstructs an identical object.
    """
    payload = {
        "contributor_id": rep.contributor_id,
        "accepted_count": rep.accepted_count,
        "rejected_count": rep.rejected_count,
        "quarantine_count": rep.quarantine_count,
        "avg_quality_score": rep.avg_quality_score,
    }
    store.set_meta(_reputation_meta_key(rep.contributor_id), json.dumps(payload))


def load_reputations_from_brain(
    store: BrainStore,
) -> dict[str, ContributorReputation]:
    """Reload every persisted contributor reputation on daemon / app start."""
    out: dict[str, ContributorReputation] = {}
    try:
        rows = store._conn.execute(
            "SELECT key, value FROM brain_meta WHERE key LIKE ?",
            (_META_REPUTATION_PREFIX + "%",),
        ).fetchall()
    except Exception:
        return out
    for row in rows:
        try:
            data = json.loads(row["value"]) if row["value"] else {}
        except Exception:
            continue
        cid = data.get("contributor_id")
        if not cid:
            # Recover the id from the key suffix if the doc omitted it.
            cid = str(row["key"])[len(_META_REPUTATION_PREFIX):]
        if not cid:
            continue
        out[cid] = ContributorReputation(
            contributor_id=cid,
            accepted_count=int(data.get("accepted_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            quarantine_count=int(data.get("quarantine_count", 0)),
            avg_quality_score=float(data.get("avg_quality_score", 0.5)),
        )
    return out


# ─────────────────────── auth ──────────────────────────────────────────


def _check_token(authorization: Optional[str]) -> None:
    expected = os.environ.get("BRAIN_FEDERATION_TOKEN")
    if not expected:
        return  # auth disabled — local mode
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=403, detail="invalid token")


# ─────────────────────── app factory ───────────────────────────────────


def create_app(
    store: BrainStore,
    *,
    firm_id: str,
    actor_url: str = "https://brain.example/actor",
    base_url: str = "https://brain.example",
    epsilon: float = 1.0,
) -> "FastAPI":  # type: ignore
    """Build a federation server bound to a particular brain store.

    The server's outbox accumulates patterns published by the local firm.
    The inbox processes incoming activities from peer firms and decides
    which to import based on contributor reputation (Wikidata-style).
    """
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError(
            "FastAPI not installed. `pip install fastapi uvicorn`"
        )

    app = FastAPI(
        title="Personal Brain — Federation",
        version="0.1.0",
        description="Cross-firm pattern sharing per AgDR-0044 Slice 8",
    )

    driver = FederationDriver(
        firm_id=firm_id, actor_url=actor_url, base_url=base_url,
        epsilon=epsilon,
    )

    # ── BRV-11: store-backed outbox + reputation registry ───────────────
    # Both used to be process-local (an in-memory Outbox + a `dict`) that
    # vanished on restart AND diverged from publish_worker's already-persisted
    # outbox. Now BOTH are reloaded from — and written through — the SAME brain
    # store (ONE-SYSTEM). The outbox reuses publish_worker's `fragments`-backed
    # persistence; reputations ride `brain_meta`. A fresh app over the same
    # store re-hydrates both.
    outbox = Outbox(actor_url=actor_url, base_url=base_url)
    for _activity in load_outbox_from_brain(store):
        outbox.activities.append(_activity)

    # Reputation registry — keyed by contributor_firm_hash, reloaded from disk.
    reputations: dict[str, ContributorReputation] = (
        load_reputations_from_brain(store)
    )

    def _publish_pattern(pattern: Pattern) -> ActivityRecord:
        """Publish into the outbox AND durably persist the activity so it
        survives a restart. The single write-path the routes share."""
        activity = outbox.publish(pattern)
        try:
            persist_activity_to_brain(store, activity)
        except Exception:
            pass  # never let a persistence hiccup drop the in-memory publish
        return activity

    def _save_reputation(rep: ContributorReputation) -> None:
        reputations[rep.contributor_id] = rep
        try:
            save_reputation_to_brain(store, rep)
        except Exception:
            pass

    @app.get("/healthz")
    async def healthz():
        return {
            "ok": True, "firm_id": firm_id,
            "outbox_size": len(outbox.activities),
            "known_contributors": len(reputations),
        }

    @app.get("/actor")
    async def actor():
        return JSONResponse({
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
            ],
            "type": "Service",
            "id": actor_url,
            "name": f"brain-{firm_id}",
            "inbox": f"{base_url}/inbox",
            "outbox": f"{base_url}/outbox",
            "publicKey": {
                "id": f"{actor_url}#main-key",
                "owner": actor_url,
                "publicKeyPem": "PLACEHOLDER",
            },
        })

    @app.get("/outbox")
    async def get_outbox():
        return JSONResponse(outbox.to_jsonld())

    @app.get("/patterns/{pattern_id}")
    async def get_pattern(pattern_id: str):
        # Find activity whose object.pattern_id matches
        for act in outbox.activities:
            if act.object.get("pattern_id") == pattern_id:
                return JSONResponse(act.to_jsonld())
        raise HTTPException(status_code=404, detail="pattern not found")

    @app.post("/publish")
    async def publish(
        request: Request,
        authorization: Optional[str] = Header(None),
    ):
        """Local convenience: derive local patterns from the brain store +
        DP-noise + publish into the outbox. Returns the published count."""
        _check_token(authorization)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        max_skills = int(payload.get("max_skills", 100))

        skills = store.list_skills(limit=max_skills)
        # Derive + DP-noise locally, then publish each through the shared
        # write-path so every activity is durably persisted (BRV-11). Skip
        # patterns already in the outbox (idempotent by pattern_id).
        from .federation import (
            derive_skill_usage_patterns,
            noise_pattern_statistics,
        )
        existing_ids = {
            a.object.get("pattern_id") for a in outbox.activities
        }
        published = 0
        for pat in derive_skill_usage_patterns(skills, firm_id=firm_id):
            noised = noise_pattern_statistics(pat, epsilon=epsilon)
            if noised.pattern_id in existing_ids:
                continue
            _publish_pattern(noised)
            existing_ids.add(noised.pattern_id)
            published += 1
        return {
            "ok": True,
            "published_count": published,
            "outbox_total": len(outbox.activities),
        }

    @app.post("/inbox")
    async def inbox(
        request: Request,
        authorization: Optional[str] = Header(None),
    ):
        """Receive an Activity from a peer firm. Decide import / quarantine
        / reject based on contributor reputation. On import, write the
        pattern as a Fragment with `scope=community` and audit-log the
        access (arXiv 2505.18279)."""
        _check_token(authorization)
        try:
            activity = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON")

        obj = (activity or {}).get("object") or {}
        contributor_hash = obj.get("contributor_firm_hash") or "unknown"
        rep = reputations.setdefault(
            contributor_hash,
            ContributorReputation(contributor_id=contributor_hash),
        )
        decision = driver.receive(activity, reputation=rep)

        if decision.accept:
            rep.accepted_count += 1
            # Persist as a community-scope Fragment (slice-7 ACL applies)
            _import_pattern_to_store(
                store, obj, contributor_hash=contributor_hash,
            )
            status = "imported"
        elif decision.quarantine:
            rep.quarantine_count += 1
            status = "quarantined"
        else:
            rep.rejected_count += 1
            status = "rejected"

        # BRV-11: durably persist the (mutated) reputation so the tally
        # survives a restart.
        _save_reputation(rep)

        return {
            "ok": True,
            "status": status,
            "reason": decision.reason,
            "contributor_reputation": rep.score,
        }

    @app.get("/reputation/{contributor_hash}")
    async def get_reputation(contributor_hash: str):
        rep = reputations.get(contributor_hash)
        if rep is None:
            return JSONResponse({"contributor_id": contributor_hash,
                                  "known": False})
        return {
            "contributor_id": rep.contributor_id,
            "known": True,
            "accepted_count": rep.accepted_count,
            "rejected_count": rep.rejected_count,
            "quarantine_count": rep.quarantine_count,
            "score": rep.score,
        }

    # ── BRV-11: expose the store-backed state + write-paths on app.state ──
    # The live outbox + reputation registry (so callers can inspect what was
    # reloaded) and the durable write-paths the routes use. This is the
    # in-process handle for the daemon/UI + the persistence regression tests —
    # the SAME objects the HTTP routes mutate, so there is no second outbox.
    app.state.federation_store = store
    app.state.federation_outbox = outbox
    app.state.federation_reputations = reputations
    app.state.federation_publish_pattern = _publish_pattern
    app.state.federation_save_reputation = _save_reputation

    def _persist_demo_pattern(pattern_id: str) -> str:
        """Publish a minimal pattern with a caller-chosen id through the durable
        write-path. Used by the daemon's self-test + the persistence tests to
        exercise the real outbox-persist path without deriving from skills."""
        pat = Pattern(
            pattern_id=pattern_id, kind="skill_usage",
            summary=f"pattern {pattern_id}", contributor_firm=firm_id,
        )
        # pattern_to_activity recomputes the id from base_url + pattern_id, so
        # the persisted activity's object.pattern_id == pattern_id.
        act = _publish_pattern(pat)
        return act.object.get("pattern_id", "")

    app.state.federation_persist_demo_pattern = _persist_demo_pattern

    return app


# ─────────────────────── helpers ───────────────────────────────────────


def _import_pattern_to_store(
    store: BrainStore,
    pattern_object: dict[str, Any],
    *,
    contributor_hash: str,
) -> None:
    """Persist an accepted pattern as a community-scope Fragment.
    The pattern's STATISTICS land in the text; raw firm content never
    travels (FICAL contract)."""
    import hashlib
    import time
    from .models import (
        Confidence,
        Fragment,
        FragmentKind,
        Provenance,
        Scope,
        Visibility,
    )

    pattern_id = pattern_object.get("pattern_id") or ""
    summary = pattern_object.get("summary") or ""
    stats = pattern_object.get("statistics") or {}

    frag_id = "comm-" + hashlib.sha256(
        f"{pattern_id}|{contributor_hash}".encode("utf-8")
    ).hexdigest()[:16]

    fragment = Fragment(
        id=frag_id,
        kind=FragmentKind.FACT,
        text=f"[community] {summary}",
        scope=Scope.COMMUNITY,
        visibility=Visibility.SHARED_PUBLIC,
        owner_user="community",
        confidence=Confidence.INFERRED,
        provenance=Provenance(
            contributing_agent="federation",
            contributing_user=contributor_hash,
            accessed_resources=[f"pattern:{pattern_id}"],
        ),
        extra={"pattern_id": pattern_id, "statistics": stats,
                "contributor_firm_hash": contributor_hash},
    )
    store.write_fragment(fragment)


# ─────────────────────── entrypoint ────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Start the federation HTTP server. Daemon entry point.

    Pulls firm_id from local brain identity when not passed explicitly,
    so admins don't have to memorise their firm_id. Persists in brain_meta
    that the server is running on `port` so the main daemon + UI know
    where to find it.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="personal-brain-federation")
    parser.add_argument("--port", type=int, default=8474)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--firm-id", type=str, default=None,
                         help="Override firm_id; default = current firm from brain")
    parser.add_argument("--actor-url", type=str, default=None,
                         help="Public actor URL; default = http://host:port/actor")
    parser.add_argument("--base-url", type=str, default=None,
                         help="Public base URL; default = http://host:port")
    parser.add_argument("--db", type=str, default=None)
    args = parser.parse_args(argv)

    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("uvicorn not installed. `pip install 'personal-brain-mcp[server]'`")
        return 1

    store = BrainStore.open(args.db)

    # Resolve firm_id from local identity when not passed
    firm_id = args.firm_id
    if not firm_id:
        try:
            from .firm import current_firm_id
            firm_id = current_firm_id(store) or "default"
        except Exception:
            firm_id = "default"

    base_url = args.base_url or f"http://{args.host}:{args.port}"
    actor_url = args.actor_url or f"{base_url}/actor"

    app = create_app(
        store, firm_id=firm_id,
        actor_url=actor_url, base_url=base_url,
    )

    # Record the running daemon's coordinates so the main brain process +
    # UI can discover them.
    try:
        store.set_meta("federation.host", args.host)
        store.set_meta("federation.port", str(args.port))
        store.set_meta("federation.firm_id", firm_id)
        store.set_meta("federation.base_url", base_url)
    except Exception:
        pass

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main_cli(argv: Optional[list[str]] = None) -> int:
    """Alias for entry_points / pyproject."""
    return main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
