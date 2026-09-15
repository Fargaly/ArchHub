"""Explicit offline format-2 to format-3 history upgrade; no graph activation.

Reserve the source writer slot, pin a separate read snapshot, copy with SQLite's
bounded backup API, validate the copy before changing its schema, then publish
only the verified closed result. An unpublished interrupted copy restarts; an
existing owned result is fully reconciled. This does not modify source records,
but SQLite may create/recover journal sidecars when opening a database.
"""
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from .conversation_history import ConversationHistoryStore, _text, validate_message_fields
from .conversation_migration import (
    _check_time, _deadline, _encoded, _feed, _reconcile_database,
    _reconcile_history, _verify_stage_owner, _write_stage_owner,
)


# The historical format-2 declarations, not the current initializer with a
# changed version label. Only whitespace/case variations are accepted. This
# checks defaults, constraints, composite-key grouping and collations together;
# valid existing rows alone cannot prove that future writes will work.
_V2_TABLES = {
    "history_identity": "CREATE TABLE history_identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1), instance_id TEXT NOT NULL)",
    "conversations": "CREATE TABLE conversations(id TEXT PRIMARY KEY, last_sequence INTEGER NOT NULL DEFAULT 0)",
    "messages": "CREATE TABLE messages(id TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id), sequence INTEGER NOT NULL, author TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL, recipients TEXT NOT NULL, refs TEXT NOT NULL, evidence TEXT NOT NULL, reply_to TEXT, created_at TEXT NOT NULL, idempotency_key TEXT NOT NULL, public INTEGER NOT NULL, UNIQUE(conversation_id,id), UNIQUE(conversation_id,sequence), UNIQUE(conversation_id,id,sequence), UNIQUE(conversation_id,idempotency_key), FOREIGN KEY(conversation_id,reply_to) REFERENCES messages(conversation_id,id))",
    "recipients": "CREATE TABLE recipients(conversation_id TEXT NOT NULL, message_id TEXT NOT NULL, principal TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY(conversation_id,message_id,principal), FOREIGN KEY(conversation_id,message_id,sequence) REFERENCES messages(conversation_id,id,sequence))",
    "category_counts": "CREATE TABLE category_counts(conversation_id TEXT NOT NULL REFERENCES conversations(id), audience_kind TEXT NOT NULL, principal TEXT NOT NULL, category TEXT NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY(conversation_id,audience_kind,principal,category))",
}
_V2_INDEXES = {
    "message_author_sequence": "CREATE INDEX message_author_sequence ON messages(conversation_id,author,sequence)",
    "message_public_sequence": "CREATE INDEX message_public_sequence ON messages(conversation_id,public,sequence)",
    "recipient_sequence": "CREATE INDEX recipient_sequence ON recipients(conversation_id,principal,sequence)",
}


def _connect(path, mode):
    database = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True,
                               timeout=2, isolation_level=None, cached_statements=32)
    try:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA cache_size=-2048")
        database.execute("PRAGMA foreign_keys=ON")
        return database
    except BaseException:
        database.close()
        raise


def _validate_v2_schema(database, instance_id):
    if (database.execute("PRAGMA application_id").fetchone()[0] != 0x41484348 or
            database.execute("PRAGMA user_version").fetchone()[0] != 2):
        raise ValueError("unsupported history upgrade source")
    objects = database.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 64").fetchall()
    tables = set(_V2_TABLES) | {"message_search", "message_search_data", "message_search_idx",
                            "message_search_docsize", "message_search_config"}
    if (len(objects) != len(tables) + len(_V2_INDEXES) or
            {row["name"] for row in objects if row["type"] == "table"} != tables or
            {row["name"] for row in objects if row["type"] == "index"} != set(_V2_INDEXES)):
        raise ValueError("unsupported format-2 schema objects or triggers")
    declarations = {row["name"]: row["sql"] for row in objects}
    for name, expected in {**_V2_TABLES, **_V2_INDEXES}.items():
        if "".join(declarations[name].lower().split()) != "".join(expected.lower().split()):
            raise ValueError("unsupported format-2 schema declaration: " + name)
    fts = next(row["sql"] for row in objects if row["name"] == "message_search")
    if "".join(fts.lower().split()) != "createvirtualtablemessage_searchusingfts5(content,content='messages',content_rowid='rowid')":
        raise ValueError("unsupported format-2 search schema")
    identity = database.execute("SELECT singleton,instance_id FROM history_identity LIMIT 2").fetchall()
    if len(identity) != 1 or tuple(identity[0]) != (1, instance_id):
        raise ValueError("history upgrade instance mismatch")


def _content_seal(database, instance_id, deadline, max_records):
    """Stream exact content and rowids; include empty conversations and heads."""
    digest = hashlib.sha256()
    _feed(digest, {"instance_id": instance_id})
    messages = conversations = 0
    database.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        for conversation in database.execute("SELECT id,last_sequence FROM conversations ORDER BY id"):
            _check_time(deadline)
            conversations += 1
            if conversations > max_records:
                raise ValueError("history upgrade conversation budget exceeded")
            _text(conversation["id"], "conversation")
            _feed(digest, [conversation["id"], conversation["last_sequence"]])
            sequence = 0
            for row in database.execute("SELECT rowid,* FROM messages WHERE conversation_id=? ORDER BY sequence", (conversation["id"],)):
                _check_time(deadline)
                messages += 1
                sequence += 1
                if messages > max_records:
                    raise ValueError("history upgrade message budget exceeded")
                if type(row["sequence"]) is not int or row["sequence"] != sequence:
                    raise ValueError("history upgrade sequence mismatch")
                message = ConversationHistoryStore._message(row)
                fields = {key: value for key, value in message.items() if key not in ("id", "sequence", "conversation_id")}
                normalized = validate_message_fields(message["conversation_id"], message_id=message["id"], **fields)
                if message != dict(sequence=sequence, **normalized):
                    raise ValueError("history upgrade message field mismatch")
                if message["reply_to"] is not None and not database.execute(
                        "SELECT 1 FROM messages WHERE conversation_id=? AND id=? AND sequence<?",
                        (message["conversation_id"], message["reply_to"], sequence)).fetchone():
                    raise ValueError("history upgrade reply order mismatch")
                _feed(digest, [row["rowid"], message, row["public"]])
            if type(conversation["last_sequence"]) is not int or conversation["last_sequence"] != sequence:
                raise ValueError("history upgrade conversation head mismatch")
        _check_time(deadline)
        return dict(digest=digest.hexdigest(), messages=messages, conversations=conversations)
    finally:
        database.set_progress_handler(None, 0)


def _upgrade_schema(database, *, destination, ticket_digest, deadline):
    """Change indexes/recipient schema only; preserve message rowids and FTS."""
    statements = (
        "CREATE UNIQUE INDEX message_identity_sequence_category ON messages(conversation_id,id,sequence,category)",
        "ALTER TABLE recipients RENAME TO recipients_v2",
        "CREATE TABLE recipients(conversation_id TEXT NOT NULL, message_id TEXT NOT NULL, principal TEXT NOT NULL, sequence INTEGER NOT NULL, category TEXT NOT NULL, PRIMARY KEY(conversation_id,message_id,principal), FOREIGN KEY(conversation_id,message_id,sequence,category) REFERENCES messages(conversation_id,id,sequence,category))",
        "INSERT INTO recipients SELECT r.conversation_id,r.message_id,r.principal,r.sequence,m.category FROM recipients_v2 r JOIN messages m ON m.conversation_id=r.conversation_id AND m.id=r.message_id AND m.sequence=r.sequence",
        "DROP TABLE recipients_v2",
        "CREATE INDEX recipient_sequence ON recipients(conversation_id,principal,sequence)",
        "CREATE INDEX message_category_sequence ON messages(conversation_id,category,sequence)",
        "CREATE INDEX message_public_category_sequence ON messages(conversation_id,public,category,sequence)",
        "CREATE INDEX message_author_category_sequence ON messages(conversation_id,author,category,sequence)",
        "CREATE INDEX recipient_category_sequence ON recipients(conversation_id,principal,category,sequence)",
    )
    database.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        database.execute("BEGIN IMMEDIATE")
        for statement in statements:
            _check_time(deadline)
            database.execute(statement)
        _write_stage_owner(database, destination, ticket_digest)
        database.execute("PRAGMA user_version=3")
        _check_time(deadline)
        database.execute("COMMIT")
    finally:
        database.set_progress_handler(None, 0)
        if database.in_transaction:
            database.execute("ROLLBACK")


def _verify_result(path, destination, instance_id, ticket_digest, seal, deadline, max_records):
    with ConversationHistoryStore(path, instance_id=instance_id, create=False) as history:
        history._db.execute("PRAGMA locking_mode=EXCLUSIVE")
        history._db.execute("BEGIN EXCLUSIVE")
        history._db.execute("COMMIT")
        _verify_stage_owner(history, destination, ticket_digest)
        if _content_seal(history._db, instance_id, deadline, max_records) != seal:
            raise ValueError("upgraded history content mismatch")
        _reconcile_history(history, deadline)


def upgrade_history_v2(source, destination, *, instance_id, max_bytes=256 * 1024 * 1024,
                       max_records=100_000, time_budget_seconds=30):
    """Return a verified offline upgrade; preserve the original and every scope.

    Busy sources refuse. Time/size/record caps apply to the whole attempt. A
    destination is never overwritten. Source reservations authorize no graph
    cutover; the caller must separately reconcile deployment and recovery.
    SQLite backup documentation: https://sqlite.org/backup.html.
    """
    _text(instance_id, "instance")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 8 * 1024**3:
        raise ValueError("invalid history upgrade byte budget")
    if type(max_records) is not int or not 1 <= max_records <= 2**31 - 1:
        raise ValueError("invalid history upgrade record budget")
    deadline = _deadline(time_budget_seconds)
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or (destination.exists() and source.samefile(destination)):
        raise ValueError("history upgrade source/destination alias")
    reservation = reader = staged = None
    temporary = None
    try:
        reservation = _connect(source, "rw")
        reservation.execute("BEGIN IMMEDIATE")
        reader = _connect(source, "ro")
        reader.execute("BEGIN")
        _validate_v2_schema(reader, instance_id)  # Forces the reserved read snapshot.
        page_size = reader.execute("PRAGMA page_size").fetchone()[0]
        if reader.execute("PRAGMA page_count").fetchone()[0] * page_size > max_bytes:
            raise ValueError("history upgrade source exceeds byte budget")
        seal = _content_seal(reader, instance_id, deadline, max_records)
        ticket_digest = hashlib.sha256(_encoded(["history-format-2-to-3",
            os.path.normcase(str(source)), instance_id, seal])).hexdigest()
        descriptor, name = tempfile.mkstemp(prefix="." + destination.name + ".upgrading-",
            suffix=".sqlite3", dir=destination.parent)
        os.close(descriptor)
        temporary = Path(name)
        staged = _connect(temporary, "rw")

        def progress(_status, _remaining, total):
            _check_time(deadline)
            if total * page_size > max_bytes:
                raise ValueError("history upgrade backup exceeds byte budget")

        reader.backup(staged, pages=256, progress=progress, sleep=0.01)
        _validate_v2_schema(staged, instance_id)
        if _content_seal(staged, instance_id, deadline, max_records) != seal:
            raise ValueError("history upgrade source copy mismatch")
        _reconcile_database(staged, deadline, storage_version=2)
        if destination.exists():
            staged.close()
            staged = None
            _verify_result(destination, destination, instance_id, ticket_digest, seal, deadline, max_records)
        else:
            staged.execute("PRAGMA max_page_count=%d" % (max_bytes // page_size))
            _upgrade_schema(staged, destination=destination, ticket_digest=ticket_digest, deadline=deadline)
            staged.close()
            staged = None
            _verify_result(temporary, destination, instance_id, ticket_digest, seal, deadline, max_records)
            _check_time(deadline)
            os.link(temporary, destination)
        return dict(complete=True, source_version=2, destination_version=3,
                    instance_id=instance_id, **seal)
    finally:
        if staged is not None:
            staged.close()
        if reader is not None:
            reader.close()
        if reservation is not None:
            reservation.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
