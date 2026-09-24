"""Durable indexed conversation content, not graph authority.

The caller must authorize the current graph node/instance and derive principal
and read_all. Neither an ID nor read_all is a credential. Legacy migration,
cutover, and application integration remain separate work. No workers or replay.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .conversation_pages import (ConversationPageProtection, PAGE_PROTECTION_VERSION,
                                 normalize_schema_sql, validate_page_schema)


_APP_ID = 0x41484348
_VERSION = 3
_RETENTION_VERSION = 4
_RETENTION_SECONDS = 20 * 86400
_RETENTION_FIELDS = ("last_activity_at", "activity_basis", "activity_revision",
                     "archive_revision", "archived_at", "content_generation", "purged_messages")
_MAX_BODY = 65536
_MAX_OUTPUT = 16 * 1024 * 1024


def _text(value, label, maximum=512):
    if type(value) is not str or not value or len(value.encode("utf-8")) > maximum or "\x00" in value:
        raise ValueError("invalid " + label)
    return value


def _integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid " + label)
    return value


def _references(values, label):
    if not isinstance(values, (tuple, list)) or len(values) > 64:
        raise ValueError("invalid " + label)
    result = [_text(value, label) for value in values]
    if len(set(result)) != len(result):
        raise ValueError("duplicate " + label)
    return result


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def validate_message_fields(conversation_id, *, author, content, category="note", recipients=(),
                            refs=(), evidence=(), reply_to=None, idempotency_key,
                            message_id=None, created_at=None):
    """Pure append validation, also used before any legacy migration writes.

    This validates content compatibility, not graph admission or reply access.
    Optional identity/time remain unset here; only append generates defaults.
    """
    _text(conversation_id, "conversation")
    _text(author, "author")
    _text(content, "content", _MAX_BODY)
    _text(category, "category")
    _text(idempotency_key, "idempotency key")
    recipients = _references(recipients, "recipients")
    refs = _references(refs, "references")
    evidence = _references(evidence, "evidence")
    if reply_to is not None:
        _text(reply_to, "reply target")
    if message_id is not None:
        _text(message_id, "message id")
    if created_at is not None:
        _text(created_at, "timestamp", 64)
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timestamp must have timezone")
        except ValueError as exc:
            raise ValueError("invalid timestamp") from exc
    return dict(id=message_id, conversation_id=conversation_id, author=author,
                content=content, category=category, recipients=recipients, refs=refs,
                evidence=evidence, reply_to=reply_to, created_at=created_at,
                idempotency_key=idempotency_key)


class ConversationHistoryStore(ConversationPageProtection):
    def __init__(self, path, *, instance_id, create=True, busy_timeout_seconds=2.0,
                 retention_clock=None):
        self.instance_id = _text(instance_id, "instance")
        if retention_clock is not None and not callable(retention_clock):
            raise TypeError("retention clock must be a trusted callable")
        self._retention_clock = retention_clock or time.time
        if type(create) is not bool:
            raise ValueError("invalid create option")
        if (type(busy_timeout_seconds) not in (int, float)
                or not 0 <= busy_timeout_seconds <= 30):
            raise ValueError("invalid history lock wait budget")
        if not create:
            existing = Path(path).resolve()
            if not existing.is_file():
                raise FileNotFoundError("admitted conversation database is missing")
            # mode=rw prevents a deletion between the check and connect from
            # silently creating replacement content. No URI comes from a request.
            path = existing.as_uri() + "?mode=rw"
        self._lock = threading.RLock()
        self._operation_cancelled = None
        self._db = sqlite3.connect(path, timeout=busy_timeout_seconds, isolation_level=None,
                                   check_same_thread=False, cached_statements=64,
                                   uri=not create)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA cache_size=-2048")
            with self._transaction(write=True):
                objects = self._db.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 32"
                ).fetchall()
                app_id = self._db.execute("PRAGMA application_id").fetchone()[0]
                version = self._db.execute("PRAGMA user_version").fetchone()[0]
                if create and not objects and app_id == 0 and version == 0:
                    self._initialize()
                elif app_id != _APP_ID or version not in (_VERSION, _RETENTION_VERSION, PAGE_PROTECTION_VERSION):
                    raise ValueError("not a supported conversation history database")
                identity = self._db.execute("SELECT instance_id FROM history_identity WHERE singleton=1").fetchone()
                if identity is None or identity[0] != self.instance_id:
                    raise ValueError("conversation database instance mismatch")
                if version in (_RETENTION_VERSION, PAGE_PROTECTION_VERSION):
                    self._validate_retention_source_schema(version)
                    self._db.execute("SELECT " + ",".join(_RETENTION_FIELDS) +
                                     " FROM conversation_retention LIMIT 0")
                    self._db.execute("SELECT conversation_id,sequence,message_digest,idempotency_digest "
                                     "FROM message_tombstones LIMIT 0")
                if version == PAGE_PROTECTION_VERSION:
                    validate_page_schema(self._db)
                elif self._db.execute("SELECT 1 FROM sqlite_master WHERE name IN "
                        "('conversation_pages','conversation_page_tracking','conversation_pages_protected') LIMIT 1").fetchone():
                    raise ValueError('page protection objects have an older schema version')
        except BaseException:
            self._db.close()
            raise

    @staticmethod
    def _base_schema_statements():
        return (
            "CREATE TABLE history_identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1), instance_id TEXT NOT NULL)",
            "CREATE TABLE conversations(id TEXT PRIMARY KEY, last_sequence INTEGER NOT NULL DEFAULT 0)",
            "CREATE TABLE messages(id TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id), sequence INTEGER NOT NULL, author TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL, recipients TEXT NOT NULL, refs TEXT NOT NULL, evidence TEXT NOT NULL, reply_to TEXT, created_at TEXT NOT NULL, idempotency_key TEXT NOT NULL, public INTEGER NOT NULL, UNIQUE(conversation_id,id), UNIQUE(conversation_id,sequence), UNIQUE(conversation_id,id,sequence,category), UNIQUE(conversation_id,idempotency_key), FOREIGN KEY(conversation_id,reply_to) REFERENCES messages(conversation_id,id))",
            "CREATE TABLE recipients(conversation_id TEXT NOT NULL, message_id TEXT NOT NULL, principal TEXT NOT NULL, sequence INTEGER NOT NULL, category TEXT NOT NULL, PRIMARY KEY(conversation_id,message_id,principal), FOREIGN KEY(conversation_id,message_id,sequence,category) REFERENCES messages(conversation_id,id,sequence,category))",
            "CREATE TABLE category_counts(conversation_id TEXT NOT NULL REFERENCES conversations(id), audience_kind TEXT NOT NULL, principal TEXT NOT NULL, category TEXT NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY(conversation_id,audience_kind,principal,category))",
            "CREATE INDEX message_author_sequence ON messages(conversation_id,author,sequence)",
            "CREATE INDEX message_public_sequence ON messages(conversation_id,public,sequence)",
            "CREATE INDEX recipient_sequence ON recipients(conversation_id,principal,sequence)",
            "CREATE INDEX message_category_sequence ON messages(conversation_id,category,sequence)",
            "CREATE INDEX message_public_category_sequence ON messages(conversation_id,public,category,sequence)",
            "CREATE INDEX message_author_category_sequence ON messages(conversation_id,author,category,sequence)",
            "CREATE INDEX recipient_category_sequence ON recipients(conversation_id,principal,category,sequence)",
            "CREATE VIRTUAL TABLE message_search USING fts5(content, content='messages', content_rowid='rowid')",
        )

    def _initialize(self):
        for statement in self._base_schema_statements():
            self._db.execute(statement)
        self._db.execute("INSERT INTO history_identity VALUES(1,?)", (self.instance_id,))
        self._db.execute("PRAGMA application_id=%d" % _APP_ID)
        self._db.execute("PRAGMA user_version=%d" % _VERSION)

    @contextmanager
    def _bounded_operations(self, *, deadline, cancelled):
        """Trusted owner batch budget, retained across individual transactions."""
        if (not callable(cancelled) or type(deadline) not in (int, float)
                or not math.isfinite(deadline)):
            raise ValueError('invalid history operation budget')
        with self._lock:
            if self._operation_cancelled is not None or self._db.in_transaction:
                raise ValueError('history operation budget requires an idle connection')
            previous_busy = self._db.execute('PRAGMA busy_timeout').fetchone()[0]
            stop = lambda: time.monotonic() >= deadline or cancelled()
            self._operation_cancelled = stop
            self._db.execute('PRAGMA busy_timeout=50')
            self._db.set_progress_handler(stop, 1000)
            try:
                if stop():
                    raise TimeoutError('history operation budget exhausted')
                yield
            finally:
                self._db.set_progress_handler(None, 0)
                self._operation_cancelled = None
                self._db.execute('PRAGMA busy_timeout=%d' % previous_busy)

    @contextmanager
    def _transaction(self, *, write=False, before_commit=None):
        with self._lock:
            remaining = 2000

            def budget():
                nonlocal remaining
                remaining -= 1
                return int(remaining <= 0 or self._operation_cancelled is not None
                           and self._operation_cancelled())

            self._db.set_progress_handler(budget, 1000)
            try:
                if self._operation_cancelled is not None and self._operation_cancelled():
                    raise TimeoutError('history operation budget exhausted')
                self._db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    yield
                    if before_commit is not None:
                        before_commit()
                    if self._operation_cancelled is not None and self._operation_cancelled():
                        raise TimeoutError('history operation budget exhausted')
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.set_progress_handler(None, 0)
                    if self._db.in_transaction:
                        self._db.execute("ROLLBACK")
                    raise
            finally:
                self._db.set_progress_handler(self._operation_cancelled,
                    1000 if self._operation_cancelled is not None else 0)

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def ensure_conversation(self, conversation_id):
        conversation_id = _text(conversation_id, "conversation")
        with self._transaction(write=True):
            self._db.execute("INSERT OR IGNORE INTO conversations(id) VALUES(?)", (conversation_id,))

    @staticmethod
    def _retention_schema_statements():
        return (
            """CREATE TABLE conversation_retention(
                conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
                last_activity_at REAL,
                activity_basis TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(activity_basis IN ('unknown','owner-observed','archive-observation')),
                activity_revision INTEGER NOT NULL DEFAULT 0 CHECK(activity_revision>=0),
                archive_revision INTEGER NOT NULL DEFAULT 0 CHECK(archive_revision>=0),
                archived_at REAL,
                content_generation INTEGER NOT NULL DEFAULT 0 CHECK(content_generation>=0),
                purged_messages INTEGER NOT NULL DEFAULT 0 CHECK(purged_messages>=0))""",
            """CREATE TABLE message_tombstones(
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                sequence INTEGER NOT NULL CHECK(sequence>0),
                message_digest TEXT NOT NULL CHECK(length(message_digest)=64),
                idempotency_digest TEXT NOT NULL CHECK(length(idempotency_digest)=64),
                PRIMARY KEY(conversation_id,sequence),
                UNIQUE(conversation_id,message_digest),
                UNIQUE(conversation_id,idempotency_digest))""",
            "CREATE INDEX message_reply_to ON messages(conversation_id,reply_to)",
        )

    def initialize_retention(self, *, before_commit=None):
        """Explicit additive v4 activation; opening a history never migrates it.

        Existing conversations have unknown activity until an owner lifecycle
        event. No message timestamp, imported transcript or read starts its age.
        Recovery consumers must recognize v4 before an owner enables live purge.
        """
        if before_commit is not None and not callable(before_commit):
            raise ValueError('retention activation commit guard is invalid')
        with self._transaction(write=True, before_commit=before_commit):
            identity = self._db.execute(
                "SELECT singleton,instance_id FROM history_identity LIMIT 2").fetchall()
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if (self._db.execute("PRAGMA application_id").fetchone()[0] != _APP_ID
                    or len(identity) != 1 or tuple(identity[0]) != (1, self.instance_id)
                    or version not in (_VERSION, _RETENTION_VERSION, PAGE_PROTECTION_VERSION)):
                raise ValueError("retention initialization identity or format mismatch")
            self._validate_retention_source_schema(version)
            if version == _VERSION:
                for statement in self._retention_schema_statements():
                    self._db.execute(statement)
                self._db.execute("PRAGMA user_version=%d" % _RETENTION_VERSION)
        return max(version, _RETENTION_VERSION)

    def _validate_retention_source_schema(self, version):
        # Schema metadata only: no message scan, sample-based trust or implicit
        # repair. The upgraded-v2 variant retains its historical message table
        # and supplies the v3 recipient FK target with an explicit unique index.
        objects = self._db.execute("SELECT type,name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' LIMIT 65").fetchall()
        if len(objects) > 64 or any(row["type"] not in ("table", "index") for row in objects):
            raise ValueError("unsupported retention source schema objects")
        declarations = {row["name"]: row for row in objects}

        normalized = normalize_schema_sql

        required = {}
        for statement in self._base_schema_statements():
            parts = statement.split()
            name = parts[3] if parts[1] == "VIRTUAL" else parts[2].split("(", 1)[0]
            required[name] = statement
        native_messages = required["messages"]
        legacy_messages = native_messages.replace("UNIQUE(conversation_id,id,sequence,category)",
                                                   "UNIQUE(conversation_id,id,sequence)")
        actual_messages = declarations.get("messages")
        if actual_messages is not None and normalized(actual_messages["sql"]) == normalized(legacy_messages):
            required["messages"] = legacy_messages
            required["message_identity_sequence_category"] = (
                "CREATE UNIQUE INDEX message_identity_sequence_category "
                "ON messages(conversation_id,id,sequence,category)")
        if version in (_RETENTION_VERSION, PAGE_PROTECTION_VERSION):
            required.update({statement.split()[2].split('(', 1)[0]:statement
                             for statement in self._retention_schema_statements()})
        for name, expected in required.items():
            actual = declarations.get(name)
            expected_type = "index" if " INDEX " in expected else "table"
            if (actual is None or actual["type"] != expected_type
                    or normalized(actual["sql"]) != normalized(expected)):
                raise ValueError("unsupported retention source schema: " + name)
        migration_tables = {
            "migration_staging": "CREATE TABLE migration_staging(singleton INTEGER PRIMARY KEY CHECK(singleton=1), ticket_digest TEXT NOT NULL, destination TEXT NOT NULL, stage_id TEXT NOT NULL)",
            "migration_publications": "CREATE TABLE migration_publications(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), application_root TEXT NOT NULL, instance_id TEXT NOT NULL, binding_root TEXT NOT NULL, manifest_digest TEXT NOT NULL, stage_id TEXT NOT NULL, source_authority TEXT NOT NULL, source_revision INTEGER NOT NULL, source_digest TEXT NOT NULL, imported_count INTEGER NOT NULL)",
        }
        for name, expected in migration_tables.items():
            actual = declarations.get(name)
            if actual is not None and (actual["type"] != "table"
                                      or normalized(actual["sql"]) != normalized(expected)):
                raise ValueError("unsupported retention migration schema: " + name)
        permitted = set(required) | set(migration_tables) | {
            "message_search_data", "message_search_idx", "message_search_docsize", "message_search_config"}
        if version in (_RETENTION_VERSION, PAGE_PROTECTION_VERSION):
            permitted.update(("conversation_retention", "message_tombstones", "message_reply_to"))
            self._db.execute("SELECT conversation_id," + ",".join(_RETENTION_FIELDS) +
                             " FROM conversation_retention LIMIT 0")
            self._db.execute("SELECT conversation_id,sequence,message_digest,idempotency_digest "
                             "FROM message_tombstones LIMIT 0")
        if version == PAGE_PROTECTION_VERSION:
            permitted.update(('conversation_page_tracking', 'conversation_pages', 'conversation_pages_protected'))
            validate_page_schema(self._db)
        if set(declarations) - permitted:
            raise ValueError("unknown retention source schema objects")

    def _retention_active(self):
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (_VERSION, _RETENTION_VERSION, PAGE_PROTECTION_VERSION):
            raise ValueError("unsupported conversation history format")
        if version != PAGE_PROTECTION_VERSION and self._db.execute(
                "SELECT 1 FROM sqlite_master WHERE name IN "
                "('conversation_pages','conversation_page_tracking','conversation_pages_protected') LIMIT 1").fetchone():
            raise ValueError('page protection objects have an older schema version')
        return version in (_RETENTION_VERSION, PAGE_PROTECTION_VERSION)

    def _retention_now(self):
        value = self._retention_clock()
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799:
            raise ValueError("owner retention clock is invalid")
        return float(value)

    def _retention_status(self, conversation_id, *, require_enabled=False):
        head = self._head(conversation_id)
        enabled = self._retention_active()
        if require_enabled and not enabled:
            raise ValueError("conversation retention has not been initialized")
        status = dict(conversation_id=conversation_id, last_sequence=head, enabled=enabled,
            last_activity_at=None, activity_basis="unknown", activity_revision=0,
            archive_revision=0, archived_at=None, content_generation=0, purged_messages=0)
        if enabled:
            row = self._db.execute("SELECT " + ",".join(_RETENTION_FIELDS) +
                " FROM conversation_retention WHERE conversation_id=?", (conversation_id,)).fetchone()
            if row is not None:
                status.update(dict(row))
        for field in ("activity_revision", "archive_revision", "content_generation", "purged_messages"):
            _integer(status[field], field, 0, 2**63 - 1)
        for field in ("last_activity_at", "archived_at"):
            value = status[field]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                      or not 0 <= value <= 253402300799):
                raise ValueError("invalid conversation retention timestamp")
        if (status["activity_basis"] not in ("unknown", "owner-observed", "archive-observation")
                or (status["last_activity_at"] is None) != (status["activity_basis"] == "unknown")
                or status["archived_at"] is not None and status["last_activity_at"] is None):
            raise ValueError("invalid conversation retention activity")
        status["protected_until_known"] = status["last_activity_at"] is None
        return status

    def retention_status(self, conversation_id):
        with self._transaction():
            return self._retention_status(conversation_id)

    def _put_retention(self, status):
        fields = ("conversation_id", *_RETENTION_FIELDS)
        self._db.execute("INSERT INTO conversation_retention(" + ",".join(fields) +
            ") VALUES(" + ",".join("?" for _ in fields) + ") ON CONFLICT(conversation_id) DO UPDATE SET " +
            ",".join(field + "=excluded." + field for field in _RETENTION_FIELDS),
            tuple(status[field] for field in fields))

    def _record_activity(self, conversation_id):
        status = self._retention_status(conversation_id, require_enabled=True)
        now = self._retention_now()
        status.update(last_activity_at=max(now, status["last_activity_at"] or 0),
            activity_basis="owner-observed", activity_revision=status["activity_revision"] + 1,
            archive_revision=status["archive_revision"] + int(status["archived_at"] is not None),
            archived_at=None, protected_until_known=False)
        self._put_retention(status)
        return status

    def record_activity(self, conversation_id, *, before_commit=None):
        """Record an admitted open/resume/close, never a poll or imported time."""
        with self._transaction(write=True, before_commit=before_commit):
            return self._record_activity(conversation_id)

    @staticmethod
    def _retention_guard(protected, before_commit):
        if protected is not False or not callable(before_commit):
            raise ValueError("retention requires explicit owner protection clearance and commit guard")

    @staticmethod
    def _retention_cas(status, activity, archive, head, generation):
        for value, label in ((activity, "activity revision"), (archive, "archive revision"),
                             (head, "head"), (generation, "content generation")):
            _integer(value, label, 0, 2**63 - 1)
        if (status["activity_revision"], status["archive_revision"], status["last_sequence"],
                status["content_generation"]) != (activity, archive, head, generation):
            raise ValueError("conversation retention state changed; refresh")

    def archive(self, conversation_id, *, expected_activity_revision, expected_archive_revision,
                expected_head, expected_content_generation, protected=True, before_commit=None):
        self._retention_guard(protected, before_commit)
        with self._transaction(write=True, before_commit=before_commit):
            before_commit()
            status = self._retention_status(conversation_id, require_enabled=True)
            self._retention_cas(status, expected_activity_revision, expected_archive_revision,
                expected_head, expected_content_generation)
            self._require_pages_clear(conversation_id)
            if status["archived_at"] is not None:
                return status
            now = self._retention_now()
            if status["last_activity_at"] is None:
                status.update(last_activity_at=now, activity_basis="archive-observation",
                    activity_revision=status["activity_revision"] + 1, protected_until_known=False)
            status.update(archived_at=now, archive_revision=status["archive_revision"] + 1)
            self._put_retention(status)
            return status

    def purge_archived(self, conversation_id, *, expected_activity_revision, expected_archive_revision,
                       expected_head, expected_content_generation, protected=True, before_commit=None,
                       max_messages=100, max_bytes=262144):
        """Delete one bounded newest-first batch, preserving sequence identities.

        The owner guard must reject active work, unsaved drafts or uncertain
        protection. It runs again immediately before commit. No graph is touched.
        """
        self._retention_guard(protected, before_commit)
        _integer(max_messages, "purge message limit", 1, 100)
        _integer(max_bytes, "purge byte limit", 1, 1024 * 1024)
        with self._transaction(write=True, before_commit=before_commit):
            before_commit()
            status = self._retention_status(conversation_id, require_enabled=True)
            self._retention_cas(status, expected_activity_revision, expected_archive_revision,
                expected_head, expected_content_generation)
            self._require_pages_clear(conversation_id)
            now = self._retention_now()
            if status["archived_at"] is None or status["last_activity_at"] is None:
                raise ValueError("conversation is not archived with known owner activity")
            if now - status["last_activity_at"] < _RETENTION_SECONDS or status["archived_at"] > now:
                raise ValueError("conversation has not been inactive for 20 days")
            cursor = self._db.execute("SELECT sequence FROM messages WHERE conversation_id=? "
                "ORDER BY sequence DESC LIMIT ?", (conversation_id, max_messages))
            try:
                sequences = [row[0] for row in cursor.fetchall()]
            finally:
                cursor.close()
            removed = removed_bytes = 0
            for sequence in sequences:
                row = self._db.execute("SELECT rowid,* FROM messages WHERE conversation_id=? AND sequence=?",
                                       (conversation_id, sequence)).fetchone()
                message = self._message(row)
                _integer(message["sequence"], "message sequence", 1, status["last_sequence"])
                fields = {key: value for key, value in message.items()
                          if key not in ("id", "sequence", "conversation_id")}
                validate_message_fields(conversation_id, message_id=message["id"], **fields)
                if type(row["public"]) is not int or row["public"] != int(not message["recipients"]):
                    raise ValueError("invalid retained message audience")
                size = len(_json(message).encode("utf-8"))
                if removed_bytes + size > max_bytes:
                    if removed == 0:
                        raise ValueError("message exceeds the purge byte budget")
                    break
                if self._db.execute("SELECT 1 FROM messages WHERE conversation_id=? AND reply_to=? LIMIT 1",
                                    (conversation_id, message["id"])).fetchone():
                    raise ValueError("purge would orphan a retained reply")
                self._db.execute("INSERT INTO message_tombstones VALUES(?,?,?,?)", (
                    conversation_id, message["sequence"], self._identity_digest(message["id"]),
                    self._identity_digest(message["idempotency_key"])))
                self._db.execute("INSERT INTO message_search(message_search,rowid,content) VALUES('delete',?,?)",
                                 (row["rowid"], message["content"]))
                audiences = [("all", "")]
                if not message["recipients"]:
                    audiences.append(("public", ""))
                else:
                    audiences.extend(("principal", principal) for principal in set(message["recipients"]) | {message["author"]})
                for kind, principal in audiences:
                    changed = self._db.execute("UPDATE category_counts SET amount=amount-1 WHERE "
                        "conversation_id=? AND audience_kind=? AND principal=? AND category=? AND amount>0",
                        (conversation_id, kind, principal, message["category"])).rowcount
                    if changed != 1:
                        raise ValueError("conversation category counts are inconsistent")
                    self._db.execute("DELETE FROM category_counts WHERE conversation_id=? AND audience_kind=? "
                        "AND principal=? AND category=? AND amount=0", (conversation_id, kind, principal, message["category"]))
                self._db.execute("DELETE FROM recipients WHERE conversation_id=? AND message_id=?",
                                 (conversation_id, message["id"]))
                self._db.execute("DELETE FROM messages WHERE conversation_id=? AND id=?",
                                 (conversation_id, message["id"]))
                removed += 1
                removed_bytes += size
            if removed:
                status.update(content_generation=status["content_generation"] + 1,
                              purged_messages=status["purged_messages"] + removed)
                self._put_retention(status)
            remaining = self._db.execute("SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1",
                                         (conversation_id,)).fetchone() is not None
            return {**status, "purged": removed, "purged_bytes": removed_bytes, "has_more": remaining}

    @staticmethod
    def _identity_digest(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def conversation_head(self, conversation_id):
        """Read admitted conversation metadata; never create a missing record."""
        with self._transaction():
            return self._head(conversation_id)

    def _head(self, conversation_id):
        _text(conversation_id, "conversation")
        row = self._db.execute("SELECT last_sequence FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            raise ValueError("unknown conversation")
        return row[0]

    @staticmethod
    def _message(row):
        result = {key: row[key] for key in
                  ("id", "conversation_id", "sequence", "author", "content", "category", "reply_to", "created_at", "idempotency_key")}
        for key in ("recipients", "refs", "evidence"):
            result[key] = json.loads(row[key])
        return result

    def append(self, conversation_id, *, author, content, category="note", recipients=(),
               refs=(), evidence=(), reply_to=None, idempotency_key, message_id=None, created_at=None,
               reply_principal=None, reply_read_all=False, before_commit=None, require_new=False):
        """Append content; application callers derive reply access and admission.

        The optional commit guard is trusted in-process code, never request data.
        It also runs for idempotent returns; failure rolls the transaction back.
        Raw migration callers remain responsible for historical authorization.
        require_new rejects an idempotent replay inside the same transaction,
        allowing admitted callers to reserve an effect without clock assumptions.
        """
        if type(require_new) is not bool:
            raise ValueError("require_new must be boolean")
        validated = validate_message_fields(conversation_id, author=author, content=content,
            category=category, recipients=recipients, refs=refs, evidence=evidence,
            reply_to=reply_to, idempotency_key=idempotency_key, message_id=message_id,
            created_at=created_at)
        reply_access = None
        if reply_principal is not None:
            reply_access = self._audience(reply_principal, reply_read_all)
        elif reply_read_all:
            raise ValueError("reply access requires an admitted principal")
        with self._transaction(write=True, before_commit=before_commit):
            previous_head = self._head(conversation_id)
            message = self._append_in_transaction(validated, reply_access=reply_access)
            if require_new and message["sequence"] <= previous_head:
                raise ValueError("idempotency conflict")
            if message["sequence"] > previous_head and self._retention_active():
                self._record_activity(conversation_id)
            return message

    def _append_in_transaction(self, validated, *, reply_access=None):
        """Insert validated fields within an already owned write transaction.

        Ordinary append retains its transaction, resource limit and admission
        guard. Governed migration reuses this insertion logic so its records,
        derived indexes and publication receipt can commit together. This
        private primitive grants no access or authority by itself.
        """
        if not self._db.in_transaction:
            raise ValueError("message insertion requires an owned transaction")
        conversation_id = validated["conversation_id"]
        author, content, category = (validated[key] for key in ("author", "content", "category"))
        recipients, refs, evidence = (validated[key] for key in ("recipients", "refs", "evidence"))
        reply_to = validated["reply_to"]
        idempotency_key, message_id, created_at = (validated[key] for key in ("idempotency_key", "id", "created_at"))
        head = self._head(conversation_id)
        if reply_to is not None and reply_access is not None:
            reply_clause, reply_args = reply_access
            if not self._db.execute(
                    "SELECT 1 FROM messages m WHERE m.conversation_id=? AND m.id=? AND " + reply_clause,
                    (conversation_id, reply_to, *reply_args)).fetchone():
                raise ValueError("reply target is not visible in this conversation")
        prior = self._db.execute("SELECT * FROM messages WHERE conversation_id=? AND idempotency_key=?",
                                 (conversation_id, idempotency_key)).fetchone()
        fields = dict(author=author, content=content, category=category, recipients=recipients,
                      refs=refs, evidence=evidence, reply_to=reply_to)
        if prior is not None:
            existing = self._message(prior)
            if (any(existing[key] != value for key, value in fields.items())
                    or message_id is not None and existing["id"] != message_id
                    or created_at is not None and existing["created_at"] != created_at):
                raise ValueError("idempotency conflict")
            return existing
        identifier = message_id or uuid.uuid4().hex
        if self._retention_active():
            for field, value in (("message_digest", identifier), ("idempotency_digest", idempotency_key)):
                if self._db.execute("SELECT 1 FROM message_tombstones WHERE conversation_id=? AND " +
                        field + "=? LIMIT 1", (conversation_id, self._identity_digest(value))).fetchone():
                    raise ValueError("message identity was removed by conversation retention")
        if self._db.execute("SELECT 1 FROM messages WHERE conversation_id=? AND id=?",
                            (conversation_id, identifier)).fetchone():
            raise ValueError("message id conflict")
        if reply_to is not None and not self._db.execute(
                "SELECT 1 FROM messages WHERE conversation_id=? AND id=?", (conversation_id, reply_to)).fetchone():
            raise ValueError("reply target is not in this conversation")
        stamp = created_at or datetime.now(timezone.utc).isoformat()
        cursor = self._db.execute(
            "INSERT INTO messages(id,conversation_id,sequence,author,content,category,recipients,refs,evidence,reply_to,created_at,idempotency_key,public) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identifier, conversation_id, head + 1, author, content, category, _json(recipients),
             _json(refs), _json(evidence), reply_to, stamp, idempotency_key, int(not recipients)))
        self._db.execute("INSERT INTO message_search(rowid,content) VALUES(?,?)", (cursor.lastrowid, content))
        for recipient in recipients:
            self._db.execute("INSERT INTO recipients VALUES(?,?,?,?,?)",
                (conversation_id, identifier, recipient, head + 1, category))
        audiences = [("all", "")]
        if not recipients:
            audiences.append(("public", ""))
        else:
            audiences.extend(("principal", principal) for principal in set(recipients) | {author})
        for kind, principal in audiences:
            self._db.execute(
                "INSERT INTO category_counts VALUES(?,?,?,?,1) ON CONFLICT(conversation_id,audience_kind,principal,category) DO UPDATE SET amount=amount+1",
                (conversation_id, kind, principal, category))
        self._db.execute("UPDATE conversations SET last_sequence=? WHERE id=?", (head + 1, conversation_id))
        return dict(id=identifier, conversation_id=conversation_id, sequence=head + 1,
                    created_at=stamp, idempotency_key=idempotency_key, **fields)

    @staticmethod
    def _audience(principal, read_all):
        _text(principal, "principal")
        if type(read_all) is not bool:
            raise ValueError("invalid read_all")
        if read_all:
            return "1", ()
        return ("(m.public=1 OR m.author=? OR EXISTS(SELECT 1 FROM recipients r WHERE "
                "r.conversation_id=m.conversation_id AND r.message_id=m.id AND r.principal=?))",
                (principal, principal))

    @staticmethod
    def _limits(limit, max_bytes, *, maximum=100):
        _integer(limit, "limit", 1, maximum)
        _integer(max_bytes, "byte budget", 1, _MAX_OUTPUT)

    @staticmethod
    def _count_rows(conversation_id, principal, read_all, category=None):
        prefix = "SELECT category,amount FROM category_counts WHERE conversation_id=? AND "
        suffix = "" if category is None else " AND category=?"
        category_args = () if category is None else (category,)
        if read_all:
            return prefix + "audience_kind='all' AND principal=''" + suffix, (conversation_id, *category_args)
        # Separate exact index ranges: unrelated principals' counters must not
        # be visited merely because they belong to the same conversation.
        return (prefix + "audience_kind='public' AND principal=''" + suffix + " UNION ALL " + prefix +
                "audience_kind='principal' AND principal=?" + suffix,
                (conversation_id, *category_args, conversation_id, principal, *category_args))

    @staticmethod
    def _collect(cursor, limit, max_bytes):
        result = []
        size = 2
        extra = False
        try:
            for row in cursor:
                if len(result) == limit:
                    extra = True
                    break
                message = ConversationHistoryStore._message(row)
                cost = len(_json(message).encode("utf-8")) + int(bool(result))
                if size + cost > max_bytes:
                    if not result:
                        raise ValueError("single message exceeds output byte budget")
                    extra = True
                    break
                result.append(message)
                size += cost
        finally:
            cursor.close()
        return result, extra

    def _visible_head(self, conversation_id, principal, *, read_all, head, category=None):
        if read_all and category is None:
            return head
        category_sql = "" if category is None else " AND category=?"
        category_args = () if category is None else (category,)
        if read_all:
            row = self._db.execute(
                "SELECT sequence FROM messages WHERE conversation_id=?" + category_sql +
                " ORDER BY sequence DESC LIMIT 1", (conversation_id, *category_args)).fetchone()
            return 0 if row is None else row[0]
        # Three exact index seeks; unrelated audiences and message bodies are
        # never traversed merely to decide whether this audience changed.
        queries = (
            ("SELECT sequence FROM messages WHERE conversation_id=? AND public=1" + category_sql +
                " ORDER BY sequence DESC LIMIT 1", (conversation_id, *category_args)),
            ("SELECT sequence FROM messages WHERE conversation_id=? AND author=?" + category_sql +
                " ORDER BY sequence DESC LIMIT 1", (conversation_id, principal, *category_args)),
            ("SELECT sequence FROM recipients WHERE conversation_id=? AND principal=?" + category_sql +
                " ORDER BY sequence DESC LIMIT 1", (conversation_id, principal, *category_args)),
        )
        visible = 0
        for sql, parameters in queries:
            row = self._db.execute(sql, parameters).fetchone()
            if row is not None:
                visible = max(visible, row[0])
        return visible

    def page(self, conversation_id, *, principal, read_all=False, limit=50, before=None,
              high_water=None, max_bytes=262144, include_categories=False,
              include_visible_head=False, if_visible_head=None, category=None,
              if_content_generation=None):
        self._limits(limit, max_bytes, maximum=500)
        if category is not None:
            _text(category, "category")
        category_sql = "" if category is None else " AND category=?"
        category_args = () if category is None else (category,)
        if type(include_categories) is not bool:
            raise ValueError("include categories must be a boolean")
        if type(include_visible_head) is not bool:
            raise ValueError("include visible head must be a boolean")
        if if_visible_head is not None:
            _integer(if_visible_head, "visible head", 0, 2**63 - 1)
            if not include_visible_head:
                raise ValueError("conditional refresh requires the visible head")
        if if_content_generation is not None:
            _integer(if_content_generation, "content generation", 0, 2**63 - 1)
        if include_visible_head and high_water is not None:
            raise ValueError("visible head requires the current content snapshot")
        audience, args = self._audience(principal, read_all)
        if before is not None:
            _integer(before, "before", 1, 2**63 - 1)
        if high_water is not None:
            _integer(high_water, "high water", 0, 2**63 - 1)
        with self._transaction():
            head = self._head(conversation_id)
            content_generation = self._retention_status(conversation_id)["content_generation"]
            if include_visible_head:
                visible_head = self._visible_head(conversation_id, principal,
                    read_all=read_all, head=head, category=category)
                if (if_visible_head == visible_head and
                        (if_content_generation == content_generation or
                         if_content_generation is None and content_generation == 0)):
                    result = dict(unchanged=True, visible_head=visible_head,
                                  content_generation=content_generation)
                    if len(_json(result).encode("utf-8")) > max_bytes:
                        raise ValueError("page envelope exceeds output byte budget")
                    return result
            water = head if high_water is None else high_water
            if water > head:
                raise ValueError("high water exceeds conversation head")
            if include_categories and water != head:
                raise ValueError("category summary requires the current content snapshot")
            where = ("m.conversation_id=? AND m.sequence<=?" +
                ("" if category is None else " AND m.category=?") + " AND " + audience)
            params = (conversation_id, water, *category_args, *args)
            if water == head:
                count_sql, count_args = self._count_rows(conversation_id, principal, read_all, category)
                total = self._db.execute(
                    "SELECT coalesce(sum(amount),0) FROM (" + count_sql + ")", count_args).fetchone()[0]
            else:
                # Historic totals remain a budgeted metadata query; current
                # counters cannot describe an earlier pinned snapshot.
                total = self._db.execute("SELECT count(*) FROM messages m WHERE " + where, params).fetchone()[0]
            ceiling = min(water, before - 1) if before is not None else water
            if read_all:
                cursor = self._db.execute(
                    "SELECT * FROM messages WHERE conversation_id=?" + category_sql +
                    " AND sequence<=? ORDER BY sequence DESC LIMIT ?",
                    (conversation_id, *category_args, ceiling, limit + 1))
            else:
                # Each audience branch yields only its newest bounded sequence
                # IDs. Dedupe IDs before reading bodies, including overlap
                # between public, author and recipient visibility. CROSS JOIN
                # keeps that bounded set outside the body lookup; otherwise
                # SQLite can scan every message before reevaluating the CTE.
                cursor = self._db.execute(f"""
                    WITH visible_public AS (
                        SELECT sequence FROM messages WHERE conversation_id=? AND public=1{category_sql} AND sequence<=?
                        ORDER BY sequence DESC LIMIT ?),
                    visible_author AS (
                        SELECT sequence FROM messages WHERE conversation_id=? AND author=?{category_sql} AND sequence<=?
                        ORDER BY sequence DESC LIMIT ?),
                    visible_recipient AS (
                        SELECT sequence FROM recipients WHERE conversation_id=? AND principal=?{category_sql} AND sequence<=?
                        ORDER BY sequence DESC LIMIT ?),
                    visible AS (
                        SELECT sequence FROM visible_public UNION SELECT sequence FROM visible_author
                        UNION SELECT sequence FROM visible_recipient),
                    newest AS (SELECT sequence FROM visible ORDER BY sequence DESC LIMIT ?)
                    SELECT m.* FROM newest CROSS JOIN messages m ON m.conversation_id=? AND m.sequence=newest.sequence
                    ORDER BY m.sequence DESC
                    """, (conversation_id, *category_args, ceiling, limit + 1,
                           conversation_id, principal, *category_args, ceiling, limit + 1,
                           conversation_id, principal, *category_args, ceiling, limit + 1,
                           limit + 1, conversation_id))
            messages, older = self._collect(cursor, limit, max_bytes)
            result = dict(messages=list(reversed(messages)), high_water=water,
                           next_before=messages[-1]["sequence"] if older else None,
                           total=total, has_older=older, content_generation=content_generation)
            if include_categories:
                result["categories"] = self._categories_at_snapshot(conversation_id, principal, read_all, category)
            if include_visible_head:
                result["visible_head"] = visible_head
            if len(_json(result).encode("utf-8")) > max_bytes:
                raise ValueError("page envelope exceeds output byte budget")
            return result

    def _categories_at_snapshot(self, conversation_id, principal, read_all, category=None):
        count_sql, args = self._count_rows(conversation_id, principal, read_all, category)
        rows = self._db.execute("SELECT category,sum(amount) AS amount FROM (" + count_sql +
                                ") GROUP BY category LIMIT 1025", args).fetchall()
        if len(rows) > 1024:
            raise ValueError("category count output exceeds budget")
        return {row["category"]: row["amount"] for row in rows}

    def counts(self, conversation_id, *, principal, read_all=False):
        self._audience(principal, read_all)
        with self._transaction():
            self._head(conversation_id)
            categories = self._categories_at_snapshot(conversation_id, principal, read_all)
            return dict(total=sum(categories.values()), categories=categories)

    def get(self, conversation_id, message_id, *, principal, read_all=False):
        _text(message_id, "message id")
        audience, args = self._audience(principal, read_all)
        with self._transaction():
            self._head(conversation_id)
            row = self._db.execute("SELECT m.* FROM messages m WHERE m.conversation_id=? AND m.id=? AND " + audience,
                                   (conversation_id, message_id, *args)).fetchone()
            return self._message(row) if row is not None else None

    def get_by_idempotency(self, conversation_id, idempotency_key, *, principal, read_all=False):
        """Read one admitted operation receipt through its existing unique index."""
        _text(idempotency_key, "idempotency key")
        audience, args = self._audience(principal, read_all)
        with self._transaction():
            self._head(conversation_id)
            row = self._db.execute("SELECT m.* FROM messages m WHERE m.conversation_id=? "
                "AND m.idempotency_key=? AND " + audience,
                (conversation_id, idempotency_key, *args)).fetchone()
            return self._message(row) if row is not None else None

    def replies_to(self, conversation_id, message_ids, *, principal, read_all=False, limit=500,
                   max_bytes=262144):
        """Visible direct replies to a bounded set of messages, oldest first.

        Uses the reply_to index with the same audience rule as page(); delivery
        receipts and relayed replies are read here rather than from a page tail.
        """
        ids = tuple(dict.fromkeys(message_ids))
        if not 1 <= len(ids) <= 200:
            raise ValueError("reply lookup needs 1 to 200 message ids")
        for value in ids:
            _text(value, "message id")
        _integer(limit, "limit", 1, 1000)
        _integer(max_bytes, "byte budget", 1, _MAX_OUTPUT)
        audience, args = self._audience(principal, read_all)
        with self._transaction():
            self._head(conversation_id)
            cursor = self._db.execute(
                "SELECT m.* FROM messages m WHERE m.conversation_id=? AND m.reply_to IN (" +
                ",".join("?" * len(ids)) + ") AND " + audience + " ORDER BY m.sequence LIMIT ?",
                (conversation_id, *ids, *args, limit + 1))
            messages, truncated = self._collect(cursor, limit, max_bytes)
            return dict(messages=messages, truncated=truncated)

    def search(self, conversation_id, query, *, principal, read_all=False, limit=20, max_bytes=262144):
        self._limits(limit, max_bytes)
        _text(query, "search query", 2048)
        audience, args = self._audience(principal, read_all)
        # A literal phrase, not caller-controlled FTS syntax or SQL.
        expression = '"' + query.replace('"', '""') + '"'
        with self._transaction():
            self._head(conversation_id)
            cursor = self._db.execute(
                "SELECT m.* FROM message_search JOIN messages m ON m.rowid=message_search.rowid "
                "WHERE message_search MATCH ? AND m.conversation_id=? AND " + audience +
                " ORDER BY m.sequence DESC LIMIT ?", (expression, conversation_id, *args, limit))
            messages, _ = self._collect(cursor, limit, max_bytes)
            return messages
