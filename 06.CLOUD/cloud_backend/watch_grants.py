"""Read-only, account-scoped views of an explicitly shared desktop session."""
from builtins import OverflowError
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
import secrets
import sys
import time

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

import db

SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
NODE_ID = re.compile(r"n(?:0|[1-9][0-9]{0,3})")
STATUS = frozenset("done failed skipped blocked stopped disabled waiting approval unconfirmed retry stale running unknown pending".split())
MAX_NODES = 10_000
MAX_BYTES = 256 * 1024
WATCH_PROJECTION = {"id": "watch.projection", "params": {"fresh_seconds": 30}}


def product_labels():
    """Use the same static catalogue and first title per engine as the desktop projection."""
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES, LIBRARY_PRESENTATION
    titles = {item: title for _, cards in LIBRARY_PRESENTATION for item, title, *_ in cards}
    labels = {"step": "Step", "skill": "Skill"}
    for item, wiring in LIBRARY_ITEM_ENGINES.items():
        engine = wiring.get("engine")
        if item in titles and isinstance(engine, str) and not engine.startswith("skill."):
            labels.setdefault(engine, titles[item])
    return labels


@lru_cache(maxsize=1)
def labels():
    packaged = Path(__file__).with_name("watch-engine-labels.json")
    if packaged.is_file():
        return json.loads(packaged.read_text(encoding="utf-8"))
    # Repository runs see the same source that builds the deployment manifest.
    source = Path(__file__).resolve().parents[2] / "01.APP"
    if source.is_dir() and str(source) not in sys.path:
        sys.path.append(str(source))
    return product_labels()


def fields(obj, required, optional=()):
    return isinstance(obj, dict) and set(required) <= obj.keys() <= set(required).union(optional)


def number(value):
    return type(value) in (int, float) and -1e12 < value < 1e12


def valid_projection(view):
    if not fields(view, ("schema", "nodes", "wires", "groups")) or view["schema"] != "archhub-watch/v1":
        return False
    nodes, wires, groups = view["nodes"], view["wires"], view["groups"]
    if not all(isinstance(value, list) for value in (nodes, wires, groups)) or len(nodes) > MAX_NODES:
        return False
    ids = set()
    allowed = labels()
    for node in nodes:
        if not fields(node, ("id", "engine", "label", "status"), ("position", "result")):
            return False
        uid, engine = node["id"], node["engine"]
        if (not isinstance(uid, str) or not NODE_ID.fullmatch(uid) or uid in ids
                or not isinstance(engine, str) or engine not in allowed or node["label"] != allowed[engine]
                or not isinstance(node["status"], str) or node["status"] not in STATUS):
            return False
        ids.add(uid)
        if "position" in node:
            pos = node["position"]
            if not fields(pos, ("x", "y")) or not all(number(v) for v in pos.values()):
                return False
        if "result" in node:
            result = node["result"]
            if not fields(result, (), ("error", "items", "count")) or not result:
                return False
            if ("error" in result and result["error"] is not True
                    or "items" in result and (type(result["items"]) is not int or not 0 < result["items"] < 1e12)
                    or "count" in result and not number(result["count"])):
                return False
    def members(values):
        return isinstance(values, list) and all(isinstance(v, str) and v in ids for v in values)
    return (all(members(wire) and len(wire) == 2 for wire in wires)
            and all(fields(g, ("children",)) and members(g["children"]) and g["children"] for g in groups))


def decode(raw):
    def distinct(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError("duplicate key")
        return obj
    return json.loads(raw, object_pairs_hook=distinct)


async def payload(request):
    raw = bytearray()
    async for part in request.stream():
        if len(raw) + len(part) > MAX_BYTES:
            raise HTTPException(413, "watch_payload_too_large")
        raw.extend(part)
    try:
        return decode(raw)
    except (ValueError, RecursionError):
        raise HTTPException(400, "invalid_watch_payload") from None


def expiry(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        raise HTTPException(400, "invalid_watch_expiry") from None


def stamp(value):
    return None if value is None else datetime.fromtimestamp(value, timezone.utc).isoformat()


def grant_row(row):
    return {"id": row["id"], "session_id": row["session_id"], "owner": row["owner_email"],
            "grantee_email": row["grantee_email"], "expires_at": stamp(row["expires_at"]),
            "created_at": stamp(row["created_at"]), "revoked_at": stamp(row["revoked_at"]), "updated_at": stamp(row["updated_at"])}


GRANTS = """SELECT g.id,g.session_id,g.created_at,g.expires_at,g.revoked_at,g.updated_at, o.email AS owner_email, v.email AS grantee_email
            FROM watch_grants g JOIN users o ON o.id=g.owner_id JOIN users v ON v.id=g.grantee_id"""


def response(**data):
    return JSONResponse({"ok": True, **data}, headers={"Cache-Control": "no-store"})


def clear_expired(con, now):
    if not con.execute("SELECT 1 FROM watch_grants WHERE projection IS NOT NULL AND expires_at<=? LIMIT 1", (now,)).fetchone():
        return
    con.execute("""UPDATE watch_grants SET projection=NULL,updated_at=NULL
        WHERE projection IS NOT NULL AND expires_at<=?""", (now,))


def held_projection(value):
    try:
        view = decode(value) if value else None
    except (ValueError, RecursionError):
        view = None
    if not valid_projection(view):
        raise HTTPException(410, "watch_unavailable")
    return view


def install(app, require_user):
    @app.get("/v1/watch-grants")
    def owned(authorization: str | None = Header(None)):
        user = require_user(authorization)
        with db.connect() as con:
            clear_expired(con, time.time())
            # Never load projection blobs for the owner's capability/list request.
            rows = con.execute(GRANTS
                               + " WHERE g.owner_id=? ORDER BY g.rowid", (user["id"],))
            return response(grants=[grant_row(row) for row in rows])

    @app.post("/v1/watch-grants")
    async def create(request: Request, authorization: str | None = Header(None)):
        user = require_user(authorization)
        body = await payload(request)
        if not fields(body, ("session_id", "session_file_id", "grantee_email", "expires_at")):
            raise HTTPException(400, "invalid_watch_grant")
        sid, email = body["session_id"], body["grantee_email"]
        if not isinstance(sid, str) or not SESSION_ID.fullmatch(sid) or body["session_file_id"] != sid:
            raise HTTPException(400, "invalid_watch_session")
        if not isinstance(email, str) or len(email) > 320:
            raise HTTPException(400, "invalid_watch_recipient")
        until = expiry(body["expires_at"])
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            viewer = con.execute("SELECT id FROM users WHERE email=? AND suspended_at IS NULL",
                                 (email.strip().lower(),)).fetchone()
            if not viewer or viewer["id"] == user["id"]:
                raise HTTPException(400, "invalid_watch_recipient")
            now = time.time()
            if until is not None and until <= now:
                raise HTTPException(400, "invalid_watch_expiry")
            # BEGIN IMMEDIATE serializes lookup and creation across connections.
            existing = con.execute(GRANTS + """ WHERE g.owner_id=? AND g.session_id=? AND g.grantee_id=?
                AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at>?)""",
                (user["id"], sid, viewer["id"], now)).fetchone()
            if existing:
                grant = dict(existing)
                # A retry may narrow consent, but must never extend it or refresh the projection.
                if until is not None and (grant["expires_at"] is None or until < grant["expires_at"]):
                    con.execute("UPDATE watch_grants SET expires_at=? WHERE id=?", (until, grant["id"]))
                    grant["expires_at"] = until
                return response(grant=grant_row(grant))
            grant = secrets.token_urlsafe(24)
            con.execute("INSERT INTO watch_grants(id,owner_id,grantee_id,session_id,expires_at,created_at) VALUES(?,?,?,?,?,?)",
                        (grant, user["id"], viewer["id"], sid, until, now))
            return response(grant=grant_row(con.execute(GRANTS + " WHERE g.id=?", (grant,)).fetchone()))

    @app.delete("/v1/watch-grants/{grant_id}")
    def revoke(grant_id: str, authorization: str | None = Header(None)):
        user = require_user(authorization)
        with db.connect() as con:
            updated = con.execute("""UPDATE watch_grants SET revoked_at=coalesce(revoked_at,?),
                projection=NULL, updated_at=NULL WHERE id=? AND owner_id=?""", (time.time(), grant_id, user["id"]))
            if not updated.rowcount:
                raise HTTPException(403, "watch_unavailable")
            return response(grant=grant_row(con.execute(GRANTS + " WHERE g.id=?", (grant_id,)).fetchone()))

    @app.put("/v1/watch-grants/{grant_id}/projection")
    async def push(grant_id: str, request: Request, authorization: str | None = Header(None)):
        user = require_user(authorization)
        body = await payload(request)
        beat = fields(body, ("session_id", "privacy", "heartbeat")) and body["heartbeat"] is True
        if not beat and (not fields(body, ("session_id", "privacy", "projection"))
                         or not valid_projection(body["projection"])):
            raise HTTPException(400, "invalid_watch_projection")
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            grant = con.execute("SELECT * FROM watch_grants WHERE id=? AND owner_id=?", (grant_id, user["id"])).fetchone()
            if grant is None:
                raise HTTPException(403, "watch_unavailable")
            now = time.time()
            if grant["revoked_at"] is not None or grant["expires_at"] is not None and grant["expires_at"] <= now:
                clear_expired(con, now)
                con.commit()
                raise HTTPException(410, "watch_unavailable")
            if body["session_id"] != grant["session_id"]:
                raise HTTPException(409, "watch_session_or_tier_changed")
            if body["privacy"] != "Internal":
                con.execute("UPDATE watch_grants SET revoked_at=?,projection=NULL,updated_at=NULL WHERE id=?",
                            (now, grant_id))
            elif beat:
                held_projection(grant["projection"])
                con.execute("UPDATE watch_grants SET updated_at=? WHERE id=?", (now, grant_id))
            else:
                con.execute("UPDATE watch_grants SET projection=?,updated_at=? WHERE id=?",
                            (json.dumps(body["projection"], allow_nan=False, separators=(",", ":")), now, grant_id))
        if body["privacy"] != "Internal":
            raise HTTPException(409, "watch_session_or_tier_changed")
        return response()

    @app.get("/v1/watching")
    def invitations(authorization: str | None = Header(None)):
        user = require_user(authorization)
        with db.connect() as con:
            now = time.time()
            clear_expired(con, now)
            rows = con.execute("""SELECT id,session_id,expires_at,revoked_at,updated_at FROM watch_grants
                WHERE grantee_id=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)
                AND EXISTS (SELECT 1 FROM users WHERE id=watch_grants.owner_id AND suspended_at IS NULL)
                ORDER BY rowid""", (user["id"], now))
            return response(grants=[{"id": r["id"], "session_id": r["session_id"],
                                    "updated_at": stamp(r["updated_at"]), "expires_at": stamp(r["expires_at"]),
                                    "revoked_at": None} for r in rows])

    @app.get("/v1/watching/{grant_id}")
    def view(grant_id: str, authorization: str | None = Header(None)):
        user = require_user(authorization)
        with db.connect() as con:
            now = time.time()
            clear_expired(con, now)
            grant = con.execute("""SELECT projection,updated_at FROM watch_grants WHERE id=? AND grantee_id=?
                AND EXISTS (SELECT 1 FROM users WHERE id=watch_grants.owner_id AND suspended_at IS NULL)
                AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)
                AND updated_at BETWEEN ? AND ?""", (grant_id, user["id"], now, now - WATCH_PROJECTION["params"]["fresh_seconds"], now)).fetchone()
        if grant is None:
            raise HTTPException(410, "watch_unavailable")
        return response(projection=held_projection(grant["projection"]), updated_at=stamp(grant["updated_at"]))


if __name__ == "__main__":
    Path("watch-engine-labels.json").write_text(json.dumps(product_labels(), ensure_ascii=False), encoding="utf-8")
