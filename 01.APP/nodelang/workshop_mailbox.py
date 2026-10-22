"""Session Link's public Workshop mailbox, independent of the Qt window.

Local stdio clients and the application use the same selected profile and
conversation rows. This does not start a service, open a graph or grant Work.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .agent_declarations import SESSION_KEYS, _alive, _lineage, canonical_path, overlaps
from .agent_runtime_registry import mailbox_label, observed_runtime_process
from .conversation_history import ConversationHistoryStore

ROOM = "app:workshop"
CATEGORY = ROOM + ":category:note"


def _text(value, label, maximum):
    if type(value) is not str or not value.strip() or "\0" in value or len(value.encode("utf-8")) > maximum:
        raise ValueError("Invalid " + label)
    return value


def _identity(context, peer):
    if type(context) is not dict or len(context) > 1 or set(context) - set(SESSION_KEYS):
        raise ValueError("Calling session metadata is invalid")
    if context:
        _text(next(iter(context.values())), "calling session", 256)
    if peer is None:
        import psutil
        from .application_machine_transport import MachinePipePeer
        process = psutil.Process()
        peer = MachinePipePeer(pid=process.pid, created_at=process.create_time(), cwd=process.cwd())
    key = "agent:%d:%d" % (peer.pid, round(peer.created_at * 1000000))
    if context:
        name, value = next(iter(context.items()))
        # Session metadata is a display address, never execution authority.
        key = "agent:session:" + sha256((name + ":" + value).encode()).hexdigest()
    label, runtime = mailbox_label(peer, context)
    return {"sender_key": key, "sender_label": label, "sender": label + " [" + key + "]"}, runtime, peer


def profile_database():
    from .persistence import application_database_path
    root = Path(os.environ.get("ARCHHUB_TEST_STATE_DIR") or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub"))
    return application_database_path(root)


def _session_alive(row):
    if _alive(row):
        return True
    if not row.get("native_session_id"):
        return False
    native = row.get("native_process")
    return bool(native and native["runtime"] == row["runtime"] and _alive(native))


def read_declarations(connection, *, include_archived=False):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone():
        return []
    rows = [json.loads(row[0]) for row in connection.execute("SELECT record FROM workshop_declarations ORDER BY root")]
    for row in rows:
        row["sockets"] = {field: row["root"] + ":" + field for field in row if field not in ("sockets", "root")}
        row["process_alive"] = _session_alive(row)
        row["current"] = row["status"] != "done" and row["process_alive"]
    return [row for row in rows if include_archived or row["current"]]


def _declare(history, body, context, identity, runtime, peer):
    task = _text(body["task"], "task", 1024)
    request = _text(body["request_id"], "request id", 256)
    if any(char in task + request for char in "\r\n") or body["status"] not in ("working", "blocked", "done"):
        raise ValueError("Declare one task line with working, blocked or done status")
    if type(body["paths"]) is not list or not 1 <= len(body["paths"]) <= 128:
        raise ValueError("Declare between 1 and 128 paths")
    paths = sorted({canonical_path(value, peer.cwd) for value in body["paths"]})
    if sum(len(value.encode()) for value in paths) > 16384:
        raise ValueError("Declaration paths exceed their byte budget")
    root = ROOM + ":declaration:" + sha256(identity["sender_key"].encode()).hexdigest()
    row = {"root": root, "agent": identity["sender_label"], "session": identity["sender_key"],
           "task": task.strip(), "request_id": request.strip(), "paths": paths, "status": body["status"],
           "runtime": runtime, "app": runtime, "native_session_id": next(iter(context.values()), None),
           "pid": peer.pid, "created_at": peer.created_at, "process_lineage": _lineage(peer),
           "native_process": observed_runtime_process(peer)}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    expired = []
    if history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone():
        for record, in history._db.execute("SELECT record FROM workshop_declarations "
                                          "WHERE json_extract(record,'$.updated_at')<?", (cutoff,)):
            archived = json.loads(record)
            if not _session_alive(archived):
                expired.append(archived["root"])
    with history._transaction(write=True):
        history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                            "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
        previous = history._db.execute("SELECT record FROM workshop_declarations WHERE root=?", (root,)).fetchone()
        old = json.loads(previous[0]) if previous else None
        changed = old is None or any(old.get(key) != value for key, value in row.items())
        row.update(version=(old["version"] if old else 0) + int(changed),
                   updated_at=datetime.now(timezone.utc).isoformat())
        history._db.execute("INSERT INTO workshop_declarations VALUES(?,?) ON CONFLICT(root) "
                            "DO UPDATE SET record=excluded.record", (root, json.dumps(row)))
        for archived in expired:
            history._db.execute("DELETE FROM workshop_declarations WHERE root=? "
                                "AND json_extract(record,'$.updated_at')<?", (archived, cutoff))
    notices = []
    if changed and row["status"] != "done" and row["request_id"] != "unassigned":
        for other in read_declarations(history._db):
            shared = overlaps(paths, other["paths"]) if other["root"] != root and other["request_id"] != "unassigned" else []
            if shared:
                pair = sorted(((root, row["version"]), (other["root"], other["version"])))
                message = history.append(ROOM, author="Workshop coordination",
                    content="To " + row["agent"] + ", " + other["agent"] + ":\nYour work overlaps at "
                    + ", ".join(shared) + ". Coordinate here; this is a notice, never a lock.",
                    category=CATEGORY, refs=(root, other["root"]),
                    idempotency_key="declaration-overlap:" + sha256(json.dumps(pair).encode()).hexdigest())
                notices.append(message["id"])
    row.update(current=row["status"] != "done", process_alive=True)
    return {**identity, "declaration": row, "coordination_messages": notices}


def _read(history, body, identity):
    since = body["since"]
    if type(since) is not int or not 0 <= since < 2**63:
        raise ValueError("Message cursor is invalid")
    after = body.get("declarations_after", "")
    if type(after) is not str or len(after) > 512 or type(body.get("include_archived", False)) is not bool:
        raise ValueError("Declaration cursor is invalid")
    with history._transaction():
        cursor = history._db.execute("SELECT * FROM messages WHERE conversation_id=? AND public=1 "
                                     "AND sequence>? ORDER BY sequence LIMIT 101", (ROOM, since))
        messages, more = history._collect(cursor, 100, 180000)
        from .installed_workshop_coordination import _recent_mailbox_peers
        peers = _recent_mailbox_peers(history, ROOM)
        declarations = read_declarations(history._db, include_archived=body.get("include_archived", False))
    result = {**identity, "messages": [], "peers": peers, "more": more, "next_since": since,
              "declarations": [], "declaration_total": len(declarations),
              "working_count": sum(row["current"] and row["status"] == "working" for row in declarations),
              "declarations_more": False, "declarations_after": ""}
    # Reserve cursor/count space once; each row is serialized once.
    size = len(json.dumps(result).encode()) + 1024
    for message in messages:
        row_size = len(json.dumps(message).encode()) + 2
        if size + row_size > 240000:
            if not result["messages"]:
                raise ValueError("A Workshop message exceeds the transport envelope")
            result["more"] = True
            break
        result["messages"].append(message)
        result["next_since"] = message["sequence"]
        size += row_size
    for row in declarations:
        if row["root"] <= after:
            continue
        row_size = len(json.dumps(row).encode()) + 2
        if size + row_size > 240000:
            if not result["declarations"]:
                raise ValueError("A declaration exceeds the transport envelope")
            result["declarations_more"] = True
            break
        result["declarations"].append(row)
        result["declarations_after"] = row["root"]
        size += row_size
    return result


def call(method, body, context, *, database=None, peer=None):
    required = {"send": {"to", "text"}, "read": {"since"},
                "declare": {"task", "paths", "status", "request_id"}}
    optional = {"send": {"reply_to", "idempotency_key"}, "read": {"declarations_after", "include_archived"}, "declare": set()}
    if method not in required or type(body) is not dict or not required[method] <= set(body) or set(body) - required[method] - optional[method]:
        raise ValueError("Workshop mailbox arguments are invalid")
    identity, runtime, peer = _identity(context, peer)
    from .persistence import application_content_path
    path = Path(database) if database is not None else profile_database()
    # The graph file may keep its messages in the sibling conversation store.
    path = application_content_path(path) or path
    # Never create another database when the selected profile is missing.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, isolation_level=None)) as connection:
        row = connection.execute("SELECT instance_id FROM history_identity WHERE singleton=1").fetchone()
        if row is None:
            raise ValueError("The selected profile has no Workshop conversation binding")
        with ConversationHistoryStore(path, instance_id=row[0], create=False, connection=connection) as history:
            if method == "read":
                return _read(history, body, identity)
            if method == "declare":
                return _declare(history, body, context, identity, runtime, peer)
            target, text = _text(body["to"], "recipient", 512), _text(body["text"], "message", 65536)
            if any(char in target for char in "\r\n"):
                raise ValueError("Recipient must be one line")
            reply = body.get("reply_to")
            if reply is not None:
                _text(reply, "reply reference", 512)
            retry_key = _text(body.get("idempotency_key", uuid4().hex), "retry key", 256)
            retry_key = sha256((identity["sender_key"] + ":" + retry_key).encode()).hexdigest()
            def rate_limit():
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
                rows = history._db.execute("SELECT 1 FROM (SELECT created_at,idempotency_key FROM messages "
                    "WHERE conversation_id=? AND author=? ORDER BY sequence DESC LIMIT 31) "
                    "WHERE created_at>=? AND idempotency_key<>? LIMIT 30",
                    (ROOM, identity["sender"], cutoff, retry_key)).fetchall()
                if len(rows) >= 30:
                    raise ValueError("Mailbox permits 30 messages per minute per peer")
            message = history.append(ROOM, author=identity["sender"], content="To " + target + ":\n" + text,
                category=CATEGORY, recipients=(), reply_to=reply, reply_principal=identity["sender"],
                idempotency_key=retry_key, before_commit=rate_limit)
            return {**identity, "to": target, "text": text, "message_id": message["id"], "sequence": message["sequence"]}
