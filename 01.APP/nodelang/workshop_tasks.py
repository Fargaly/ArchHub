"""Workshop tasks: one table in the Workshop mailbox SQLite, claimed atomically.

Prior art: Paperclip issues.ts checkout. A claim is one conditional UPDATE; the row
changes only when it is free, its lease expired, or the claimant already holds it.
A lease that lapses frees the task for the next agent; nothing runs on a timer.
"""
import re
import time
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

SCHEMA = ("CREATE TABLE IF NOT EXISTS workshop_tasks(id TEXT PRIMARY KEY, title TEXT NOT NULL, "
          "status TEXT NOT NULL CHECK(status IN ('open','claimed','done')), owner TEXT, owner_label TEXT, "
          "lease_until REAL, result TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
          "updated_at TEXT NOT NULL) STRICT")
TASKS_NODE = {'id': 'workshop.tasks', 'params': {'lease_seconds': 900}}
UI_STATUS = {"open": "PLANNED", "claimed": "WIP", "done": "DONE"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write(history, sql, values):
    with history._transaction(write=True):
        history._db.execute(SCHEMA)
        return history._db.execute(sql, values).rowcount == 1


def _text(value, label, maximum):
    if type(value) is not str or not value.strip() or "\0" in value or len(value.encode("utf-8")) > maximum:
        raise ValueError("Invalid task " + label)
    return value.strip()


def create(history, title, creator):
    task = uuid4().hex
    _write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
           "VALUES(?,?,'open',?,?,?)", (task, _text(title, "title", 2000), creator, _now(), _now()))
    return get(history, task)


def claim(history, task, owner, label, lease_seconds=None):
    """True when this owner holds the task after the call; False when another holds it."""
    lease_seconds = TASKS_NODE['params']['lease_seconds'] if lease_seconds is None else lease_seconds
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 86400:
        raise ValueError("Lease must be 30 to 86400 seconds")
    now = time.time()
    return _write(history, "UPDATE workshop_tasks SET status='claimed', owner=?, owner_label=?, lease_until=?, "
                  "updated_at=? WHERE id=? AND status!='done' AND (owner IS NULL OR owner=? OR lease_until<?)",
                  (owner, label, now + lease_seconds, _now(), task, owner, now))


def release(history, task, owner):
    return _write(history, "UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, lease_until=NULL, "
                  "updated_at=? WHERE id=? AND owner=? AND status='claimed'", (_now(), task, owner))


def complete(history, task, owner, result=""):
    # The holder may finish after its lease lapsed, as long as nobody claimed it since.
    return _write(history, "UPDATE workshop_tasks SET status='done', lease_until=NULL, result=?, updated_at=? "
                  "WHERE id=? AND owner=? AND status='claimed'", (result, _now(), task, owner))


def declared(history, root, request_id, title, status, owner, label):
    """An agent's declare() is its task: working/blocked holds it, done completes it.

    Re-declaring renews the lease; a session that stops declaring lets it lapse.
    """
    task = "declared-" + sha256((root + "\0" + request_id).encode()).hexdigest()[:32]
    if status == "done":
        return complete(history, task, owner)
    _write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
           "VALUES(?,?,'open',?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title WHERE status!='done'",
           (task, _text(title, "title", 2000), label, _now(), _now()))
    # Moving to another request gives the previous declared task back to the pool.
    _write(history, "UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, lease_until=NULL, "
           "updated_at=? WHERE owner=? AND status='claimed' AND id LIKE 'declared-%' AND id!=?", (_now(), owner, task))
    return claim(history, task, owner, label)


# A token that reads as an id, path, flag or measurement, not as words.
_JARGON = re.compile(r"[=/\\_<>{}`]|\d{3,}|[a-z][A-Z]|^[(\[]|^[A-Z][A-Z0-9]*-?\d|^[a-f0-9]{7,}$")
_TRAILING = {"in", "on", "at", "to", "for", "of", "and", "the", "a", "with", "from", "by"}


def short_title(text, limit=60):
    """A human task name: the first clause of the declared text without id/path tokens, at most `limit` chars."""
    text = re.sub(r"^\s*[A-Z0-9][A-Z0-9-]*:\s+", "", str(text or "").strip())  # a leading lane tag ("WSFIX: ")
    first = re.split(r"(?<=[.;:!?])\s|\n|\s[–—-]\s|\s\(", text, maxsplit=1)[0]
    words = [w for w in first.split() if not _JARGON.search(w)]
    while len(words) > 1 and words[-1].casefold() in _TRAILING:
        words.pop()
    title = " ".join(words).strip(" ,;:.-") or text[:limit]
    return title if len(title) <= limit else title[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"


def column(history):
    """The Studio Work rows: a short name, the full declaration as details, and the owner's live state:
    Working while its session declares working or holds the lease, Needs you while it is blocked, Done when completed."""
    from .workshop_mailbox import read_declarations
    live = {"declared-" + sha256((d["root"] + "\0" + d["request_id"]).encode()).hexdigest()[:32]: d["status"]
            for d in read_declarations(history._db)}
    def state(row):
        if row["status"] == "done":
            return "DONE"
        if live.get(row["id"]) == "blocked":
            return "IN REVIEW"
        if live.get(row["id"]) == "working" or (row["status"] == "claimed" and not row["lease_expired"]):
            return "WIP"
        return "PLANNED"
    return [{'id': row['id'], 'title': short_title(row['title']), 'description': row['title'],
             'owner': row['owner_label'] if row['id'] in live or not row['lease_expired'] else None,
             'status': state(row), 'result': row['result'],
             'messages': [], 'steps': [], 'reviews': [], 'queuedMessages': [], 'declarations': [],
             'updated_at': row['updated_at']} for row in rows(history)]


def set_status(history, task, status):
    """The founder's board move: PLANNED frees the task, DONE closes it, whoever holds it."""
    if status == "PLANNED":
        return _write(history, "UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, "
                      "lease_until=NULL, updated_at=? WHERE id=?", (_now(), task))
    if status == "DONE":
        return _write(history, "UPDATE workshop_tasks SET status='done', lease_until=NULL, updated_at=? "
                      "WHERE id=?", (_now(), task))
    raise ValueError("An agent claims a task; the board sets PLANNED or DONE")


COLUMNS = ("id", "title", "status", "owner", "owner_label", "lease_until", "result",
           "created_by", "created_at", "updated_at")


def rows(history, task=None):
    if not history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_tasks'").fetchone():
        return []
    now = time.time()
    found = [dict(zip(COLUMNS, row)) for row in history._db.execute(
        "SELECT " + ",".join(COLUMNS) + " FROM workshop_tasks WHERE ? IS NULL OR id=? "
        "ORDER BY created_at DESC LIMIT 500", (task, task))]
    for row in found:
        row["lease_expired"] = row["status"] == "claimed" and row["lease_until"] < now
    return found


def get(history, task):
    return next(iter(rows(history, task)), None)
