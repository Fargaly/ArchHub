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


def _pack_to_dict(row: dict, *, with_readme: bool = False) -> dict:
    """Project a marketplace_packs row to the public JSON shape."""
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
    }
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
            "  status, download_count, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (pack_id, slug, title, description, version, category,
             user["id"], json.dumps(manifest_obj), signature, pubkey,
             STATUS_PENDING, now, now),
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
        "sha256": sha,
    }


# ---------------------------------------------------------------------------
# GET /marketplace/packs  — browse
# ---------------------------------------------------------------------------
@router.get("/marketplace/packs")
def list_packs(
    query: str = Query("", max_length=200),
    category: str = Query("", max_length=64),
    verified_only: bool = Query(False),
    cursor: str = Query("", max_length=64),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    authorization: str | None = Header(None),
) -> dict:
    user = _optional_user(authorization)
    is_admin = bool(user and int(user.get("is_admin") or 0))

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
    if cursor:
        # Cursor is an opaque created_at — newer rows have higher ts; we
        # paginate descending so the cursor caps from above.
        try:
            cursor_ts = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad_cursor")
        wheres.append("created_at < ?")
        args.append(cursor_ts)
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    sql = (
        "SELECT * FROM marketplace_packs"
        + where_sql
        + " ORDER BY created_at DESC LIMIT ?"
    )
    args.append(limit + 1)   # fetch +1 to detect more

    with db.connect() as con:
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = str(rows[-1]["created_at"]) if (has_more and rows) else None

    return {
        "packs": [_pack_to_dict(r) for r in rows],
        "next_cursor": next_cursor,
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
    out = _pack_to_dict(row, with_readme=True)
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
            "SELECT status, author_user_id, signature, pubkey, slug, version"
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
