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
from .storage import BrainStore


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

    # Persistent outbox (in-memory for now; persist via store in V2)
    outbox = Outbox(actor_url=actor_url, base_url=base_url)

    # Reputation registry — keyed by contributor_firm_hash
    reputations: dict[str, ContributorReputation] = {}

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
        new_outbox = driver.derive_and_publish(skills, traces=[])
        # Merge into our persistent outbox
        for act in new_outbox.activities:
            outbox.activities.append(act)
        return {
            "ok": True,
            "published_count": len(new_outbox.activities),
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
            status = "quarantined"
        else:
            rep.rejected_count += 1
            status = "rejected"

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


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse
    import uvicorn  # type: ignore
    parser = argparse.ArgumentParser(prog="brain-federation")
    parser.add_argument("--port", type=int, default=8474)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--firm-id", type=str, default="default")
    parser.add_argument("--actor-url", type=str,
                         default="http://127.0.0.1:8474/actor")
    parser.add_argument("--base-url", type=str,
                         default="http://127.0.0.1:8474")
    parser.add_argument("--db", type=str, default=None)
    args = parser.parse_args(argv)

    store = BrainStore.open(args.db)
    app = create_app(
        store, firm_id=args.firm_id,
        actor_url=args.actor_url, base_url=args.base_url,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
