"""ArchHub Marketplace v1 — author uploads, browse, install.

Architects publish signed Skill packs; other architects browse + install
them through the desktop client. Each pack is a zip + Ed25519 detached
signature; the backend verifies the signature on upload and returns it
to the client on download so the client can re-verify before unzipping
into the local skills directory.

Storage shape (see db.SCHEMA for the canonical column list):
  marketplace_packs       — metadata + status (pending_review|approved|rejected)
  marketplace_pack_files  — single-row-per-pack zip blob
  marketplace_reports     — abuse / takedown signal from any signed-in user

Endpoints (all mounted under no prefix — paths begin /marketplace/...):

  POST /marketplace/packs                       — author upload (signed)
  GET  /marketplace/packs                       — browse approved packs
  GET  /marketplace/packs/{pack_id}             — pack detail
  GET  /marketplace/packs/{pack_id}/download    — streams zip + signature
  POST /marketplace/packs/{pack_id}/review      — admin approve/reject
  POST /marketplace/packs/{pack_id}/report      — abuse report

Auth: bearer token in `Authorization: Bearer <token>` — same as the rest
of the API. Anonymous browsing is permitted (no token required for GET
/marketplace/packs and detail); everything else requires auth.

Phase 2 (not in v1): migrate `marketplace_pack_files.content` BLOB to
S3/R2 object storage with signed download URLs. The router contract
stays the same — only the storage adapter changes.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
import uuid
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from fastapi import (
    APIRouter, Depends, File, Form, Header, HTTPException, Query, Response,
    UploadFile,
)
from fastapi.responses import Response as FastResponse
from pydantic import BaseModel, Field

import db


router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_PACK_BYTES = 10 * 1024 * 1024     # 10 MB hard cap on zip uploads
STATUS_PENDING = "pending_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

# Community Gallery — the enum spines (kept here, mirrored by the db defaults).
# A pack's `source` is who published it; `pack_type` is which of the four
# self-extend artifact classes it is.
SOURCE_USER = "user"
SOURCE_AGENT = "agent"
SOURCE_OFFICIAL = "official"
VALID_SOURCES = frozenset({SOURCE_USER, SOURCE_AGENT, SOURCE_OFFICIAL})
# `all` is a list FILTER value, never stored — it means "no source filter".
SOURCE_FILTERS = frozenset({SOURCE_USER, SOURCE_AGENT, SOURCE_OFFICIAL, "all"})
VALID_PACK_TYPES = frozenset({"skill", "connector", "node", "widget"})
SORT_NEW = "new"
SORT_TOP = "top"
VALID_SORTS = frozenset({SORT_NEW, SORT_TOP})


# ---------------------------------------------------------------------------
# Auth helpers (mirror main.py patterns)
# ---------------------------------------------------------------------------
def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401,
                            detail="missing_or_invalid_authorization")
    return authorization.split(None, 1)[1].strip()


def _require_user(authorization: str | None) -> dict:
    token = _bearer(authorization)
    user = db.user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_token")
    return user


def _require_admin(authorization: str | None) -> dict:
    user = _require_user(authorization)
    if not int(user.get("is_admin") or 0):
        raise HTTPException(status_code=403, detail="admin_required")
    return user


def _optional_user(authorization: str | None) -> Optional[dict]:
    """Best-effort auth — returns the user when a valid token is present,
    None otherwise. Used by GET /marketplace/packs so anonymous browsing
    works but admins still see pending packs."""
    if not authorization:
        return None
    try:
        return _require_user(authorization)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Crypto verification — re-uses the same Ed25519 wire format as
# app/marketplace_signing.py. Signature is computed over the raw zip
# bytes (not canonical JSON of the manifest) so the client can re-verify
# without rebuilding the manifest.
# ---------------------------------------------------------------------------
def _verify_signature(zip_bytes: bytes, signature_b64: str,
                       pubkey_b64: str) -> tuple[bool, str]:
    try:
        sig = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError):
        return False, "signature_not_base64"
    try:
        pub = base64.b64decode(pubkey_b64, validate=True)
    except (binascii.Error, ValueError):
        return False, "pubkey_not_base64"
    try:
        pk = Ed25519PublicKey.from_public_bytes(pub)
    except Exception:
        return False, "pubkey_invalid"
    try:
        pk.verify(sig, zip_bytes)
    except InvalidSignature:
        return False, "signature_mismatch"
    except Exception as ex:
        return False, f"verify_error_{type(ex).__name__}"
    return True, "ok"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ReviewReq(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(default="", max_length=500)


class ReportReq(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class VoteReq(BaseModel):
    # +1 up, -1 down, 0 clears the user's vote.
    vote: int = Field(ge=-1, le=1)


def _pack_to_dict(row: dict, *, with_readme: bool = False,
                  my_vote: int | None = None) -> dict:
    """Project a marketplace_packs row to the public JSON shape.

    Surfaces the Community Gallery fields (source / pack_type / vote counts /
    at_own_risk) alongside the original marketplace fields. `my_vote`, when
    provided, is the requesting user's current vote (+1/-1/0) on this pack.
    """
    up = int(row.get("up_votes") or 0)
    down = int(row.get("down_votes") or 0)
    out = {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "description": row["description"],
        "version": row["version"],
        "category": row.get("category", ""),
        "author_user_id": row["author_user_id"],
        "status": row["status"],
        "download_count": int(row["download_count"]),
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
        "approved_at": row.get("approved_at"),
        "signature": row["signature"],
        "pubkey": row["pubkey"],
        # Community Gallery fields (additive; defaults keep legacy rows valid).
        "source": row.get("source") or SOURCE_USER,
        "pack_type": row.get("pack_type") or "skill",
        "up_votes": up,
        "down_votes": down,
        "score": up - down,
        "at_own_risk": bool(int(row.get("at_own_risk") if row.get("at_own_risk")
                                is not None else 1)),
        "promoted_at": row.get("promoted_at"),
    }
    if my_vote is not None:
        out["my_vote"] = int(my_vote)
    try:
        manifest = json.loads(row["manifest_json"])
    except Exception:
        manifest = {}
    out["manifest"] = manifest
    if with_readme:
        out["readme"] = manifest.get("readme", "")
    return out


def _new_pack_id() -> str:
    return f"pk_{int(time.time()*1000):x}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# POST /marketplace/packs  — upload a signed pack
# ---------------------------------------------------------------------------
@router.post("/marketplace/packs", status_code=200)
async def upload_pack(
    pack_zip: UploadFile = File(...),
    signature: str = Form(default=""),
    pubkey: str = Form(default=""),
    manifest: str = Form(default=""),
    source: str = Form(default=""),
    authorization: str | None = Header(None),
) -> dict:
    user = _require_user(authorization)

    if not manifest:
        raise HTTPException(status_code=400, detail="missing_manifest")
    # Parse manifest before we burn CPU on signature verification.
    try:
        manifest_obj = json.loads(manifest)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="manifest_not_json")
    if not isinstance(manifest_obj, dict):
        raise HTTPException(status_code=400, detail="manifest_not_object")
    slug = str(manifest_obj.get("slug") or "").strip().lower()
    title = str(manifest_obj.get("title") or "").strip()
    if not slug or not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="invalid_slug")
    if not title:
        raise HTTPException(status_code=400, detail="missing_title")
    version = str(manifest_obj.get("version") or "0.1.0").strip()
    description = str(manifest_obj.get("description") or "")
    category = str(manifest_obj.get("category") or "")
    # Community Gallery: pack_type is one of the four self-extend artifact
    # classes, read from the manifest (defaults to 'skill' for legacy packs).
    pack_type = str(manifest_obj.get("pack_type") or "skill").strip().lower()
    if pack_type not in VALID_PACK_TYPES:
        raise HTTPException(status_code=400, detail="invalid_pack_type")
    # `source` is server-authoritative: a normal architect can only publish a
    # 'user' pack. 'agent' (published by the self-extend loop) is accepted ONLY
    # from an admin/agent caller. 'official' is NEVER set on upload — it is
    # reached solely via the founder-gated /promote endpoint.
    requested_source = (source or "").strip().lower()
    pack_source = SOURCE_USER
    if requested_source == SOURCE_AGENT and int(user.get("is_admin") or 0):
        pack_source = SOURCE_AGENT
    # at_own_risk is 1 for all freshly uploaded community packs (user + agent);
    # only promotion to official clears it.
    at_own_risk = 1

    # Read upload with hard size cap. UploadFile.read(N) blocks until N
    # bytes or EOF, so reading MAX+1 and checking length is enough.
    zip_bytes = await pack_zip.read(MAX_PACK_BYTES + 1)
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="empty_upload")
    if len(zip_bytes) > MAX_PACK_BYTES:
        raise HTTPException(status_code=413, detail="pack_too_large")

    if not signature:
        raise HTTPException(status_code=400, detail="missing_signature")
    if not pubkey:
        raise HTTPException(status_code=400, detail="missing_pubkey")

    ok, reason = _verify_signature(zip_bytes, signature, pubkey)
    if not ok:
        raise HTTPException(status_code=400,
                            detail=f"signature_invalid:{reason}")

    now = int(time.time())
    pack_id = _new_pack_id()
    sha = hashlib.sha256(zip_bytes).hexdigest()

    with db.connect() as con:
        # Enforce slug uniqueness with a friendly error rather than
        # bubbling up an IntegrityError.
        existing = con.execute(
            "SELECT id FROM marketplace_packs WHERE slug = ?", (slug,),
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="slug_taken")
        con.execute(
            "INSERT INTO marketplace_packs"
            " (id, slug, title, description, version, category,"
            "  author_user_id, manifest_json, signature, pubkey,"
            "  status, download_count, created_at, updated_at,"
            "  source, pack_type, at_own_risk)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
            (pack_id, slug, title, description, version, category,
             user["id"], json.dumps(manifest_obj), signature, pubkey,
             STATUS_PENDING, now, now,
             pack_source, pack_type, at_own_risk),
        )
        con.execute(
            "INSERT INTO marketplace_pack_files"
            " (pack_id, content, sha256, size_bytes, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pack_id, zip_bytes, sha, len(zip_bytes), now),
        )

    return {
        "pack_id": pack_id,
        "slug": slug,
        "version": version,
        "status": STATUS_PENDING,
        "source": pack_source,
        "pack_type": pack_type,
        "at_own_risk": bool(at_own_risk),
        "sha256": sha,
    }


# ---------------------------------------------------------------------------
# GET /marketplace/packs  — browse
# ---------------------------------------------------------------------------
@router.get("/marketplace/packs")
def list_packs(
    query: str = Query("", max_length=200),
    category: str = Query("", max_length=64),
    source: str = Query("", max_length=16),
    pack_type: str = Query("", max_length=16),
    sort: str = Query(SORT_NEW, max_length=8),
    verified_only: bool = Query(False),
    cursor: str = Query("", max_length=64),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    authorization: str | None = Header(None),
) -> dict:
    user = _optional_user(authorization)
    is_admin = bool(user and int(user.get("is_admin") or 0))

    # Validate the gallery filters up front so a bad value is a clean 400
    # rather than a silently-empty list.
    src = (source or "").strip().lower()
    if src and src not in SOURCE_FILTERS:
        raise HTTPException(status_code=400, detail="invalid_source")
    ptype = (pack_type or "").strip().lower()
    if ptype and ptype not in VALID_PACK_TYPES:
        raise HTTPException(status_code=400, detail="invalid_pack_type")
    sort_mode = (sort or SORT_NEW).strip().lower()
    if sort_mode not in VALID_SORTS:
        raise HTTPException(status_code=400, detail="invalid_sort")

    # Approved-only by default; admins viewing without verified_only see
    # the full pipeline so they can review pending packs from the same
    # endpoint.
    wheres: list[str] = []
    args: list = []
    if verified_only or not is_admin:
        wheres.append("status = ?")
        args.append(STATUS_APPROVED)
    if query:
        wheres.append("(title LIKE ? OR description LIKE ? OR slug LIKE ?)")
        like = f"%{query}%"
        args.extend([like, like, like])
    if category:
        wheres.append("category = ?")
        args.append(category)
    # Gallery source filter ('all' = no filter); the "official" value maps to
    # the existing approved/seed tier (source='official').
    if src and src != "all":
        wheres.append("source = ?")
        args.append(src)
    if ptype:
        wheres.append("pack_type = ?")
        args.append(ptype)
    if cursor:
        # Cursor is an opaque created_at — newer rows have higher ts; we
        # paginate descending so the cursor caps from above. Cursor pagination
        # only applies to the 'new' (created_at) ordering.
        try:
            cursor_ts = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad_cursor")
        if sort_mode == SORT_NEW:
            wheres.append("created_at < ?")
            args.append(cursor_ts)
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    # sort=top ranks by net score (up - down), newest as the tiebreak; sort=new
    # is the original created_at-desc feed. Column names are from the fixed
    # enum above — never user input — so this is not an injection surface.
    if sort_mode == SORT_TOP:
        order_sql = " ORDER BY (up_votes - down_votes) DESC, created_at DESC"
    else:
        order_sql = " ORDER BY created_at DESC"

    sql = (
        "SELECT * FROM marketplace_packs"
        + where_sql
        + order_sql
        + " LIMIT ?"
    )
    args.append(limit + 1)   # fetch +1 to detect more

    with db.connect() as con:
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]

    has_more = len(rows) > limit
    rows = rows[:limit]
    # next_cursor only meaningful for the created_at feed; top-sort callers
    # page by limit instead (votes shift the order between requests).
    next_cursor = (str(rows[-1]["created_at"])
                   if (has_more and rows and sort_mode == SORT_NEW) else None)

    # Attach the requesting user's own vote per pack (one batched query).
    my_votes: dict = {}
    if user:
        my_votes = db.pack_votes_for_user([r["id"] for r in rows], user["id"])

    return {
        "packs": [_pack_to_dict(r, my_vote=my_votes.get(r["id"], 0)
                                if user else None)
                  for r in rows],
        "next_cursor": next_cursor,
        "sort": sort_mode,
    }


# ---------------------------------------------------------------------------
# GET /marketplace/packs/{pack_id}  — detail
# ---------------------------------------------------------------------------
@router.get("/marketplace/packs/{pack_id}")
def get_pack(pack_id: str,
             authorization: str | None = Header(None)) -> dict:
    user = _optional_user(authorization)
    is_admin = bool(user and int(user.get("is_admin") or 0))
    with db.connect() as con:
        r = con.execute(
            "SELECT * FROM marketplace_packs WHERE id = ?", (pack_id,),
        ).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="pack_not_found")
        f = con.execute(
            "SELECT sha256, size_bytes FROM marketplace_pack_files"
            " WHERE pack_id = ?", (pack_id,),
        ).fetchone()
    row = dict(r)
    # Hide pending/rejected packs from non-admins.
    if row["status"] != STATUS_APPROVED and not is_admin:
        # The author can always see their own pack though.
        if not (user and user["id"] == row["author_user_id"]):
            raise HTTPException(status_code=404, detail="pack_not_found")
    my_vote = db.pack_vote_for_user(pack_id, user["id"]) if user else None
    out = _pack_to_dict(row, with_readme=True, my_vote=my_vote)
    if f is not None:
        out["sha256"] = f["sha256"]
        out["size_bytes"] = int(f["size_bytes"])
    return out


# ---------------------------------------------------------------------------
# GET /marketplace/packs/{pack_id}/download  — stream the signed zip
# ---------------------------------------------------------------------------
@router.get("/marketplace/packs/{pack_id}/download")
def download_pack(pack_id: str,
                  authorization: str | None = Header(None)) -> Response:
    user = _optional_user(authorization)
    is_admin = bool(user and int(user.get("is_admin") or 0))
    with db.connect() as con:
        r = con.execute(
            "SELECT status, author_user_id, signature, pubkey, slug, version,"
            " source, at_own_risk"
            " FROM marketplace_packs WHERE id = ?",
            (pack_id,),
        ).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="pack_not_found")
        if r["status"] != STATUS_APPROVED and not is_admin:
            if not (user and user["id"] == r["author_user_id"]):
                raise HTTPException(status_code=404, detail="pack_not_found")
        f = con.execute(
            "SELECT content FROM marketplace_pack_files WHERE pack_id = ?",
            (pack_id,),
        ).fetchone()
        if f is None:
            raise HTTPException(status_code=404, detail="pack_file_missing")
        # Bump download counter — best-effort, doesn't block on serialize.
        con.execute(
            "UPDATE marketplace_packs SET download_count = download_count + 1"
            " WHERE id = ?",
            (pack_id,),
        )
    filename = f"{r['slug']}-{r['version']}.zip"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "X-Pack-Signature": r["signature"],
        "X-Pack-Pubkey": r["pubkey"],
        "X-Pack-Id": pack_id,
        # Community Gallery: tell the client whether this pack is unreviewed
        # community content so it can show the adopt-at-own-risk warning.
        "X-Pack-Source": r["source"] or SOURCE_USER,
        "X-Pack-At-Own-Risk": "1" if int(r["at_own_risk"] or 0) else "0",
    }
    return FastResponse(
        content=bytes(f["content"]),
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# POST /marketplace/packs/{pack_id}/review  — admin approve/reject
# ---------------------------------------------------------------------------
@router.post("/marketplace/packs/{pack_id}/review")
def review_pack(pack_id: str, body: ReviewReq,
                authorization: str | None = Header(None)) -> dict:
    admin = _require_admin(authorization)
    now = int(time.time())
    new_status = STATUS_APPROVED if body.decision == "approve" else STATUS_REJECTED
    with db.connect() as con:
        r = con.execute(
            "SELECT id FROM marketplace_packs WHERE id = ?", (pack_id,),
        ).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="pack_not_found")
        con.execute(
            "UPDATE marketplace_packs"
            " SET status = ?, approved_at = ?, approved_by = ?,"
            "     rejected_reason = ?, updated_at = ?"
            " WHERE id = ?",
            (new_status,
             now if new_status == STATUS_APPROVED else None,
             admin["id"] if new_status == STATUS_APPROVED else None,
             body.reason if new_status == STATUS_REJECTED else None,
             now, pack_id),
        )
    return {"pack_id": pack_id, "status": new_status,
            "decided_by": admin["id"], "decided_at": now}


# ---------------------------------------------------------------------------
# POST /marketplace/packs/{pack_id}/vote  — one vote per user (up/down/clear)
# ---------------------------------------------------------------------------
@router.post("/marketplace/packs/{pack_id}/vote")
def vote_pack(pack_id: str, body: VoteReq,
              authorization: str | None = Header(None)) -> dict:
    """Cast / flip / clear the signed-in user's single vote on a pack.

    One-vote-per-user is enforced by the (pack_id, voter_user_id) composite
    PK in db.cast_vote — re-voting flips the SAME row, it never stacks. The
    denormalised up/down counters are recomputed from the ledger inside the
    same transaction so the returned counts are always honest.
    """
    user = _require_user(authorization)
    try:
        result = db.cast_vote(pack_id, user["id"], int(body.vote))
    except ValueError as ex:
        # Map the DAO's sentinel reasons to clean HTTP — never leak the raw
        # exception text to the client (CodeQL: stack-trace exposure).
        reason = str(ex)
        if reason == "pack_not_found":
            raise HTTPException(status_code=404, detail="pack_not_found")
        raise HTTPException(status_code=400, detail="invalid_vote")
    result["pack_id"] = pack_id
    return result


# ---------------------------------------------------------------------------
# POST /marketplace/packs/{pack_id}/promote  — founder-gated lift to official
# ---------------------------------------------------------------------------
@router.post("/marketplace/packs/{pack_id}/promote")
def promote_pack(pack_id: str,
                 authorization: str | None = Header(None)) -> dict:
    """Promote a top-voted user|agent pack to the OFFICIAL tier.

    Founder/admin-gated (`_require_admin`) — a community pack NEVER becomes
    official automatically. Sets source='official', clears at_own_risk, and
    stamps promoted_at/by. This is the approved->official tier lift; the
    existing /review remains the pending->approved moderation gate.
    """
    admin = _require_admin(authorization)
    row = db.promote_pack_to_official(pack_id, admin["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="pack_not_found")
    out = _pack_to_dict(row)
    out["promoted_by"] = admin["id"]
    return out


# ---------------------------------------------------------------------------
# POST /marketplace/packs/{pack_id}/report  — abuse report
# ---------------------------------------------------------------------------
@router.post("/marketplace/packs/{pack_id}/report", status_code=201)
def report_pack(pack_id: str, body: ReportReq,
                authorization: str | None = Header(None)) -> dict:
    user = _require_user(authorization)
    now = int(time.time())
    with db.connect() as con:
        r = con.execute(
            "SELECT id FROM marketplace_packs WHERE id = ?", (pack_id,),
        ).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="pack_not_found")
        cur = con.execute(
            "INSERT INTO marketplace_reports"
            " (pack_id, reporter_user_id, reason, created_at)"
            " VALUES (?, ?, ?, ?)",
            (pack_id, user["id"], body.reason, now),
        )
        report_id = cur.lastrowid
    return {"report_id": report_id, "pack_id": pack_id,
            "reporter_user_id": user["id"], "created_at": now}
