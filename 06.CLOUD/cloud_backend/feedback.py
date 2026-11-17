"""Feedback: what people tell ArchHub from the app and the website.

One owner, one table (`feedback` in the cloud db). A signed-in person sends
with POST /v1/feedback; the founder reads, answers, moves and merges it from
the Cockpit (/founder/api/feedback*, routes in founder_cockpit.py, each one
audited there). Spec 35.08 app-002 section 9.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from fastapi import Header, Request
from fastapi.responses import JSONResponse

import db

TYPES = ("bug", "idea", "praise")
STATUSES = ("new", "planned", "doing", "shipped", "declined")
SOURCES = ("app", "site")

def _row(r) -> dict:
    out = dict(r)
    out["replies"] = json.loads(out.get("replies") or "[]")
    return out


def submit(user_id: str, text: str, type_: str = "idea", source: str = "app") -> dict:
    text = str(text or "").strip()[:5000]
    if not text:
        raise ValueError("empty")
    now = int(time.time())
    row = {"id": "fb_%x_%s" % (now, uuid.uuid4().hex[:8]), "user_id": user_id,
           "type": type_ if type_ in TYPES else "idea", "text": text,
           "source": source if source in SOURCES else "app", "created_at": now, "updated_at": now}
    with db.connect() as con:
        con.execute("INSERT INTO feedback (id, user_id, type, text, source, created_at, updated_at) "
                    "VALUES (:id, :user_id, :type, :text, :source, :created_at, :updated_at)", row)
    return get(row["id"])


def get(feedback_id: str) -> Optional[dict]:
    with db.connect() as con:
        r = con.execute("SELECT f.*, u.email, u.full_name FROM feedback f "
                        "LEFT JOIN users u ON u.id = f.user_id WHERE f.id = ?",
                        (feedback_id,)).fetchone()
    return _row(r) if r else None


def listing(status: str = "", limit: int = 200) -> dict:
    """Rows newest first (merged rows only under their own filter), with the
    count each status filter holds."""
    where, args = "WHERE f.merged_into IS NULL", []
    if status in STATUSES:
        where += " AND f.status = ?"
        args.append(status)
    with db.connect() as con:
        rows = con.execute("SELECT f.*, u.email, u.full_name, "
                           "(SELECT COUNT(*) FROM feedback m WHERE m.merged_into = f.id) AS merged "
                           "FROM feedback f LEFT JOIN users u ON u.id = f.user_id "
                           "%s ORDER BY f.created_at DESC LIMIT ?" % where,
                           args + [int(limit)]).fetchall()
        counts = {s: 0 for s in STATUSES}
        for s, n in con.execute("SELECT status, COUNT(*) FROM feedback WHERE merged_into IS NULL "
                                "GROUP BY status"):
            counts[s] = int(n)
    return {"feedback": [_row(r) for r in rows], "counts": counts}


def set_status(feedback_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise ValueError("status")
    with db.connect() as con:
        con.execute("UPDATE feedback SET status = ?, updated_at = ? WHERE id = ?",
                    (status, int(time.time()), feedback_id))
    return get(feedback_id)


def set_plan(feedback_id: str, plan_row: str) -> dict:
    with db.connect() as con:
        con.execute("UPDATE feedback SET plan_row = ?, updated_at = ? WHERE id = ?",
                    (str(plan_row or "").strip()[:40], int(time.time()), feedback_id))
    return get(feedback_id)


def merge(feedback_id: str, into_id: str) -> dict:
    """Fold a duplicate into another row; rows already merged into it follow."""
    if feedback_id == into_id:
        raise ValueError("self")
    target = get(into_id)
    if target is None or target.get("merged_into"):
        raise ValueError("target")
    with db.connect() as con:
        con.execute("UPDATE feedback SET merged_into = ?, updated_at = ? WHERE id = ? OR merged_into = ?",
                    (into_id, int(time.time()), feedback_id, feedback_id))
    return get(feedback_id)


def add_reply(feedback_id: str, *, by: str, subject: str, text: str) -> dict:
    row = get(feedback_id)
    replies = row["replies"] + [{"at": int(time.time()), "by": by, "subject": subject, "text": text}]
    with db.connect() as con:
        con.execute("UPDATE feedback SET replies = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(replies), int(time.time()), feedback_id))
    return get(feedback_id)


def new_count() -> int:
    with db.connect() as con:
        return int(con.execute("SELECT COUNT(*) FROM feedback WHERE status = 'new' "
                               "AND merged_into IS NULL").fetchone()[0])


# The app path's bounds, checked before anything is stored.
MAX_BODY_BYTES = 4096              # the whole request body, refused unread past this
MAX_TEXT_CHARS = 2000              # refused, never cut
PER_10_MIN = 5                     # sends per person in any 10 minutes
PER_DAY = 20                       # sends per person in any 24 hours
FIELDS = {"text", "type", "source"}


def _recent(user_id: str, since: int) -> int:
    with db.connect() as con:
        return int(con.execute("SELECT COUNT(*) FROM feedback WHERE user_id = ? AND created_at >= ?",
                               (user_id, since)).fetchone()[0])


async def send_feedback(request: Request, authorization: Optional[str] = Header(None)) -> JSONResponse:
    """A signed-in person sends feedback from the app or the website:
    {"text": 1..2000 characters, "type": bug|idea|praise, "source": app|site}."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = db.user_for_token(token) if token else None
    if user is None:
        return JSONResponse({"ok": False, "error": "sign in to send feedback"}, status_code=401)
    declared = request.headers.get("content-length")
    if declared and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        return JSONResponse({"ok": False, "error": "feedback is up to %d bytes" % MAX_BODY_BYTES},
                            status_code=413)
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse({"ok": False, "error": "feedback is up to %d bytes" % MAX_BODY_BYTES},
                                status_code=413)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return JSONResponse({"ok": False, "error": "send JSON"}, status_code=400)
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        return JSONResponse({"ok": False, "error": "only text, type and source are accepted"}, status_code=400)
    text, type_, source = payload.get("text"), payload.get("type", "idea"), payload.get("source", "app")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        return JSONResponse({"ok": False, "error": "write 1 to %d characters" % MAX_TEXT_CHARS}, status_code=400)
    if type_ not in TYPES or source not in SOURCES:
        return JSONResponse({"ok": False, "error": "type is bug, idea or praise; source is app or site"},
                            status_code=400)
    now = int(time.time())
    if _recent(user["id"], now - 600) >= PER_10_MIN or _recent(user["id"], now - 86400) >= PER_DAY:
        return JSONResponse({"ok": False, "error": "too much feedback at once; try again later"},
                            status_code=429)
    row = submit(user["id"], text, type_, source)
    return JSONResponse({"ok": True, "id": row["id"], "status": row["status"]})
