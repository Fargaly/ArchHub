"""Offline legacy conversation preflight and resumable ordinary-content copy.

The caller owns and admits the source and supplies isolated staging paths. A ticket
and its private manifest are reconciliation evidence, never credentials or
permission to activate a binding. This module neither changes the graph nor
opens an installed database implicitly. Activation/reference repair and recovery
of post-cutover writes are separate operations.

Preparation reads membership once, then one body at a time. A manifest retains
only indexed metadata and digests. Opening/resuming verifies that manifest and
the copied prefix once. Subsequent batches read only their next source entries.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from .cell_deliberation import read_deliberation_entry, read_deliberation_space
from .conversation_history import ConversationHistoryStore, validate_message_fields
from .conversation_pages import PAGE_PROTECTION_VERSION, reconcile_page_protection


_MAX_ENTRIES = 100_000
_MAX_RECORD_BYTES = 1024 * 1024
_COLUMNS = "sequence,message_id,idempotency_key,reply_to,record_digest,historical,record_bytes"
_HISTORICAL = ("policy_root", "authorization_action_root", "authorization_rule_roots",
               "authorization_reason", "lifecycle_root")


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _feed(digest, value):
    payload = _encoded(value)
    if len(payload) > _MAX_RECORD_BYTES:
        raise ValueError("migration metadata exceeds record byte budget")
    digest.update(len(payload).to_bytes(4, "big"))
    digest.update(payload)


def _deadline(seconds):
    if type(seconds) not in (int, float) or not 0 < seconds <= 120:
        raise ValueError("invalid migration time budget")
    return time.monotonic() + seconds


def _check_time(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("migration time budget exceeded")


def _connect_manifest(path, *, readonly=False):
    database = sqlite3.connect(path.as_uri() + "?mode=ro" if readonly else path,
                               uri=readonly, timeout=2, isolation_level=None)
    try:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA cache_size=-512")
        return database
    except BaseException:
        database.close()
        raise


def _source_matches(source, header):
    transition = source.snapshot_transition(previous_revision=header["source_revision"],
                                            previous_digest=header["source_digest"])
    if (source.authority_identity != header["source_authority"] or
            transition.snapshot.revision != header["source_revision"] or
            not hmac.compare_digest(transition.chain_digest, header["source_digest"])):
        raise ValueError("migration source changed")
    return transition.snapshot


def _record(entry, snapshot):
    record = validate_message_fields(entry.space_root, author=entry.actor_root,
        content=entry.content, category=entry.category_root, recipients=entry.recipient_roots,
        refs=entry.reference_roots, evidence=entry.evidence_roots, reply_to=entry.reply_to_root,
        idempotency_key=entry.idempotency_key, message_id=entry.root_id, created_at=entry.created_at)
    record["sequence"] = entry.sequence
    historical = {key: getattr(entry, key) for key in _HISTORICAL}
    historical["authorization_rule_roots"] = list(entry.authorization_rule_roots)
    roots = (entry.root_id, entry.space_root, entry.actor_root, entry.category_root,
             entry.policy_root, entry.authorization_action_root, entry.lifecycle_root,
             *entry.recipient_roots, *entry.reference_roots, *entry.evidence_roots,
             *entry.authorization_rule_roots)
    if any(root not in snapshot.cells for root in roots):
        raise ValueError("migration entry has a missing graph reference")
    payload = _encoded([record, historical])
    if len(payload) > _MAX_RECORD_BYTES:
        raise ValueError("migration entry exceeds record byte budget")
    return record, historical, hashlib.sha256(payload).hexdigest(), len(payload)


def _reconcile_history(history, deadline):
    with history._lock:
        _reconcile_database(history._db, deadline)


def _reconcile_database(database, deadline, *, storage_version=None):
    """Verify derived visibility, counters and search; never rebuild corruption.

    The importer holds exclusive destination ownership. SQL streams/spills its
    expected sets rather than retaining all recipients/counters in Python.
    FTS5's external-content integrity check (rank=1) compares its index to the
    actual messages; the enclosing transaction always rolls back, even on PASS.
    Inside an existing publication transaction, roll back only our savepoint,
    preserving the caller's pending rows and its responsibility for COMMIT.
    See https://sqlite.org/fts5.html#the_integrity_check_command.
    """
    actual_version = database.execute("PRAGMA user_version").fetchone()[0]
    if storage_version is None:
        storage_version = actual_version
    if storage_version not in (2, 3, 4, PAGE_PROTECTION_VERSION) or storage_version != actual_version:
        raise ValueError("unsupported reconciliation schema")
    if storage_version != PAGE_PROTECTION_VERSION and database.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN "
            "('conversation_pages','conversation_page_tracking','conversation_pages_protected') "
            "OR tbl_name IN ('conversation_pages','conversation_page_tracking') LIMIT 1").fetchone():
        raise ValueError("page protection objects require the page protection schema version")
    remaining = 100_000

    def budget():
        nonlocal remaining
        remaining -= 1
        return int(remaining <= 0 or time.monotonic() >= deadline)

    # Format 2 lacks the derived recipient category. Its own FK and the exact
    # canonical audience comparison must pass before creating format-3 indexes.
    actual_recipients = ("SELECT * FROM recipients" if storage_version in (3, 4, PAGE_PROTECTION_VERSION) else
        "SELECT r.conversation_id,r.message_id,r.principal,r.sequence,m.category FROM recipients r "
        "LEFT JOIN messages m ON m.conversation_id=r.conversation_id AND m.id=r.message_id")
    nested = database.in_transaction
    savepoint_open = False
    database.set_progress_handler(budget, 1000)
    try:
        if nested:
            database.execute("SAVEPOINT conversation_reconciliation")
            savepoint_open = True
        else:
            database.execute("PRAGMA temp_store=FILE")
            database.execute("BEGIN")
        if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("migration reconciliation: invalid foreign reference")
        if storage_version == PAGE_PROTECTION_VERSION:
            reconcile_page_protection(database, lambda: _check_time(deadline))
        if storage_version in (4, PAGE_PROTECTION_VERSION):
            # Deleted content leaves body-free sequence/identity tombstones.
            # Together they must cover the exact original sequence once; a gap,
            # duplicate or invented head is corruption, not retention.
            if database.execute("""WITH positions AS (
                    SELECT conversation_id,sequence FROM messages UNION ALL
                    SELECT conversation_id,sequence FROM message_tombstones)
                    SELECT 1 FROM conversations c LEFT JOIN positions p ON p.conversation_id=c.id
                    GROUP BY c.id HAVING typeof(c.last_sequence)!='integer' OR c.last_sequence<0
                    OR count(p.sequence)!=c.last_sequence
                    OR count(DISTINCT p.sequence)!=c.last_sequence
                    OR coalesce(max(p.sequence),0)!=c.last_sequence
                    OR (c.last_sequence>0 AND min(p.sequence)!=1) LIMIT 1""").fetchone():
                raise ValueError("retention reconciliation: conversation sequence coverage mismatch")
            if database.execute("""SELECT 1 FROM message_tombstones WHERE
                    typeof(sequence)!='integer' OR sequence<1
                    OR typeof(message_digest)!='text' OR length(message_digest)!=64
                    OR message_digest GLOB '*[^0-9a-f]*'
                    OR typeof(idempotency_digest)!='text' OR length(idempotency_digest)!=64
                    OR idempotency_digest GLOB '*[^0-9a-f]*' LIMIT 1""").fetchone():
                raise ValueError("retention reconciliation: tombstone identity is invalid")
            if database.execute("""SELECT 1 FROM conversation_retention WHERE
                    typeof(activity_revision)!='integer' OR activity_revision<0
                    OR typeof(archive_revision)!='integer' OR archive_revision<0
                    OR typeof(content_generation)!='integer' OR content_generation<0
                    OR typeof(purged_messages)!='integer' OR purged_messages<0
                    OR content_generation>purged_messages
                    OR (purged_messages>0 AND content_generation=0)
                    OR activity_basis NOT IN ('unknown','owner-observed','archive-observation')
                    OR (activity_basis!='unknown' AND last_activity_at IS NULL)
                    OR (activity_basis='unknown' AND last_activity_at IS NOT NULL)
                    OR (archived_at IS NOT NULL AND last_activity_at IS NULL)
                    OR (last_activity_at IS NOT NULL AND
                        (typeof(last_activity_at) NOT IN ('real','integer') OR last_activity_at<0 OR last_activity_at>253402300799))
                    OR (archived_at IS NOT NULL AND
                        (typeof(archived_at) NOT IN ('real','integer') OR archived_at<0 OR archived_at>253402300799))
                    LIMIT 1""").fetchone():
                raise ValueError("retention reconciliation: lifecycle metadata is invalid")
            if database.execute("""SELECT 1 FROM conversations c
                    LEFT JOIN conversation_retention r ON r.conversation_id=c.id
                    LEFT JOIN message_tombstones t ON t.conversation_id=c.id
                    GROUP BY c.id HAVING count(t.sequence)!=coalesce(r.purged_messages,0) LIMIT 1""").fetchone():
                raise ValueError("retention reconciliation: purge receipt count mismatch")
        elif database.execute("""SELECT 1 FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id
                GROUP BY c.id HAVING typeof(c.last_sequence)!='integer'
                OR count(m.id)!=c.last_sequence OR coalesce(max(m.sequence),0)!=c.last_sequence LIMIT 1""").fetchone():
            raise ValueError("migration reconciliation: conversation head mismatch")
        if database.execute("SELECT 1 FROM messages WHERE typeof(public)!='integer' OR public NOT IN (0,1) OR public!=(json_array_length(recipients)=0) LIMIT 1").fetchone():
            raise ValueError("migration reconciliation: public visibility mismatch")
        if database.execute("""WITH actual AS (""" + actual_recipients + """), expected AS (
                SELECT m.conversation_id,m.id,j.value,m.sequence,m.category
                FROM messages m,json_each(m.recipients) j),
                missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
                extra AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                SELECT 1 FROM missing UNION ALL SELECT 1 FROM extra LIMIT 1""").fetchone():
            raise ValueError("migration reconciliation: recipient index mismatch")
        if database.execute("""WITH audiences AS (
                SELECT conversation_id,'all' AS kind,'' AS principal,category FROM messages
                UNION ALL SELECT conversation_id,'public','',category FROM messages WHERE public=1
                UNION ALL SELECT conversation_id,'principal',author,category FROM messages WHERE public=0
                UNION ALL SELECT m.conversation_id,'principal',j.value,m.category
                    FROM messages m,json_each(m.recipients) j WHERE m.public=0 AND j.value!=m.author),
                expected AS (SELECT conversation_id,kind,principal,category,count(*) FROM audiences
                    GROUP BY conversation_id,kind,principal,category),
                missing AS (SELECT * FROM expected EXCEPT SELECT * FROM category_counts),
                extra AS (SELECT * FROM category_counts EXCEPT SELECT * FROM expected)
                SELECT 1 FROM missing UNION ALL SELECT 1 FROM extra LIMIT 1""").fetchone():
            raise ValueError("migration reconciliation: category counter mismatch")
        database.execute("INSERT INTO message_search(message_search,rank) VALUES('integrity-check',1)")
        _check_time(deadline)
    except sqlite3.Error as exc:
        raise ValueError("migration reconciliation: database or search integrity check failed") from exc
    finally:
        database.set_progress_handler(None, 0)
        if database.in_transaction:
            if nested and savepoint_open:
                database.execute("ROLLBACK TO conversation_reconciliation")
                database.execute("RELEASE conversation_reconciliation")
            elif not nested:
                database.execute("ROLLBACK")


def _write_stage_owner(database, destination, ticket_digest):
    database.execute("CREATE TABLE migration_staging(singleton INTEGER PRIMARY KEY CHECK(singleton=1), ticket_digest TEXT NOT NULL, destination TEXT NOT NULL, stage_id TEXT NOT NULL)")
    database.execute("INSERT INTO migration_staging VALUES(1,?,?,?)",
        (ticket_digest, os.path.normcase(str(destination)), uuid.uuid4().hex))


class _StagingHistoryStore(ConversationHistoryStore):
    """Initialize stage ownership and its conversation in the schema transaction."""
    def __init__(self, path, *, header, ticket_digest, destination):
        self._stage_header = header
        self._stage_digest = ticket_digest
        self._stage_destination = os.path.normcase(str(destination))
        super().__init__(path, instance_id=header["instance_id"])

    def _initialize(self):
        super()._initialize()
        _write_stage_owner(self._db, self._stage_destination, self._stage_digest)
        self._db.execute("INSERT INTO conversations(id) VALUES(?)", (self._stage_header["space_root"],))


def _publish_history_stage(destination, header, ticket_digest):
    """Publish a fully initialized stage without replacing any existing path.

    Same-directory hard linking is an atomic, non-overwriting publication. The
    temporary database is closed first and only our exact created temporary
    path is removed. After interruption the destination is absent or complete.
    Filesystems without hard-link support refuse; there is no overwrite fallback.
    A process crash may retain its unpublished temporary file for later cleanup;
    that file is never inferred to be an admitted destination.
    """
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + destination.name + ".preparing-",
        suffix=".sqlite3", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with _StagingHistoryStore(temporary, header=header, ticket_digest=ticket_digest,
                                  destination=destination):
            pass
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_stage_owner(history, destination, ticket_digest):
    database = history._db
    if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_staging'").fetchone():
        raise ValueError("migration destination lacks staging ownership")
    row = database.execute("SELECT ticket_digest,destination,stage_id FROM migration_staging WHERE singleton=1").fetchone()
    if (row is None or row["ticket_digest"] != ticket_digest or
            row["destination"] != os.path.normcase(str(destination))):
        raise ValueError("migration staging ownership mismatch")
    if type(row["stage_id"]) is not str or uuid.UUID(row["stage_id"]).hex != row["stage_id"]:
        raise ValueError("invalid migration staging identity")


@dataclass(frozen=True)
class MigrationTicket:
    """Retain with private migration evidence; not supplied by a remote caller."""
    manifest_path: str
    manifest_digest: str
    total: int


def open_legacy_migration_manifest(ticket, protocol, *, time_budget_seconds=30):
    """Verify and pin original import evidence without opening either data store.

    Return the read-only connection, with its read transaction still open, and
    the validated header. The caller owns closing the connection and admission
    of any subsequent operation. No current graph or staging identity is checked
    here: an authorized owner can also inspect this evidence after activation.
    """
    deadline = _deadline(time_budget_seconds)
    path = Path(ticket.manifest_path).resolve()
    database = _connect_manifest(path, readonly=True)
    try:
        database.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        database.execute("BEGIN")
        row = database.execute("SELECT content,digest FROM header WHERE singleton=1").fetchone()
        if row is None or len(row["content"].encode("utf-8")) > _MAX_RECORD_BYTES:
            raise ValueError("migration manifest is incomplete")
        header = json.loads(row["content"])
        if (header.get("format") != 1 or type(ticket.total) is not int or
                not 0 <= ticket.total <= _MAX_ENTRIES or header.get("total") != ticket.total or
                header.get("protocol_root") != protocol.root_id or
                header.get("protocol_roles") != dict(protocol.roles)):
            raise ValueError("migration manifest scope mismatch")
        seal = hashlib.sha256()
        _feed(seal, header)
        seen = 0
        for manifest_row in database.execute("SELECT " + _COLUMNS + " FROM entries ORDER BY sequence"):
            _check_time(deadline)
            seen += 1
            if seen > ticket.total or manifest_row["sequence"] != seen:
                raise ValueError("migration manifest sequence mismatch")
            _feed(seal, tuple(manifest_row))
        if (seen != ticket.total or not hmac.compare_digest(seal.hexdigest(), ticket.manifest_digest)
                or not hmac.compare_digest(row["digest"], ticket.manifest_digest)):
            raise ValueError("migration manifest changed")
        _check_time(deadline)
        database.set_progress_handler(None, 0)
        return database, header
    except BaseException:
        database.close()
        raise


def prepare_legacy_migration(source, protocol, *, application_root, space_root,
                             instance_id, manifest_path, time_budget_seconds=30):
    """Fully validate a pinned source before any destination message is written.

    Existing manifests are never replaced. An incomplete manifest created here
    is removed on failure. Legacy input exceeding current ordinary-store limits
    refuses explicitly; no truncation or silent schema adaptation is performed.
    """
    deadline = _deadline(time_budget_seconds)
    if type(instance_id) is not str or uuid.UUID(instance_id).hex != instance_id:
        raise ValueError("migration requires canonical instance identity")
    transition = source.snapshot_transition()
    snapshot = transition.snapshot
    if application_root not in snapshot.cells or application_root == space_root:
        raise ValueError("invalid migration application root")
    space = read_deliberation_space(snapshot, protocol, space_root)
    if space.content_store_root is not None:
        raise ValueError("conversation already uses ordinary content")
    if len(space.entry_roots) > _MAX_ENTRIES:
        raise ValueError("migration entry budget exceeded")
    controls = {key: getattr(space, key) for key in space.__dataclass_fields__ if key != "entry_roots"}
    header = dict(format=1, source_authority=source.authority_identity,
        source_revision=snapshot.revision, source_digest=transition.chain_digest,
        application_root=application_root, space_root=space_root, instance_id=instance_id,
        protocol_root=protocol.root_id, protocol_roles=dict(protocol.roles),
        total=len(space.entry_roots), controls=controls)
    seal = hashlib.sha256()
    _feed(seal, header)
    path = Path(manifest_path).resolve()
    # Exclusive reservation avoids replacing an existing file after a check.
    with path.open("xb"):
        pass
    database = None
    try:
        database = _connect_manifest(path)
        database.execute("CREATE TABLE header(singleton INTEGER PRIMARY KEY CHECK(singleton=1), content TEXT NOT NULL, digest TEXT NOT NULL)")
        database.execute("CREATE TABLE entries(sequence INTEGER PRIMARY KEY, message_id TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL UNIQUE, reply_to TEXT, record_digest TEXT NOT NULL, historical TEXT NOT NULL, record_bytes INTEGER NOT NULL)")
        database.execute("BEGIN IMMEDIATE")
        for sequence, root in enumerate(space.entry_roots, 1):
            _check_time(deadline)
            entry = read_deliberation_entry(snapshot, protocol, root)
            if type(entry.sequence) is not int or entry.sequence != sequence or entry.space_root != space_root:
                raise ValueError("migration entry sequence or conversation mismatch")
            record, historical, digest, record_bytes = _record(entry, snapshot)
            if entry.reply_to_root is not None and not database.execute(
                    "SELECT 1 FROM entries WHERE message_id=?", (entry.reply_to_root,)).fetchone():
                raise ValueError("migration reply is missing or not earlier in this conversation")
            row = (sequence, record["id"], record["idempotency_key"], record["reply_to"],
                   digest, _encoded(historical).decode("utf-8"), record_bytes)
            try:
                database.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?)", row)
            except sqlite3.IntegrityError as exc:
                raise ValueError("migration contains duplicate identity, sequence or retry key") from exc
            _feed(seal, row)
        _check_time(deadline)
        _source_matches(source, header)
        database.execute("INSERT INTO header VALUES(1,?,?)", (_encoded(header).decode("utf-8"), seal.hexdigest()))
        database.execute("COMMIT")
        return MigrationTicket(str(path), seal.hexdigest(), len(space.entry_roots))
    except BaseException:
        if database is not None:
            database.close()
            database = None
        path.unlink()
        raise
    finally:
        if database is not None:
            database.close()


class LegacyConversationImport:
    """Own an exclusive staged destination and copy only fully preflighted input.

    Close/reopen after any interrupted batch. Destination rows themselves are
    the durable checkpoint: a committed append is reconciled even if the caller
    never observed its return. Opening scans metadata and the imported prefix;
    ordinary batches never rescan that prefix. A complete copy is not cutover.
    """
    def __init__(self, source, protocol, ticket, destination, *, time_budget_seconds=30):
        deadline = _deadline(time_budget_seconds)
        self._manifest = None
        self._history = None
        self._failed = False
        self._closed = False
        self._verified_complete = False
        self.source, self.protocol = source, protocol
        path = Path(ticket.manifest_path).resolve()
        destination = Path(destination).resolve()
        self.ticket, self.destination = ticket, destination
        if destination == path or (destination.exists() and destination.samefile(path)):
            raise ValueError("migration destination aliases its manifest")
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("migration time budget exceeded")
            self._manifest, header = open_legacy_migration_manifest(
                ticket, protocol, time_budget_seconds=remaining)
            self._manifest.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            self.header = header
            self.total = ticket.total
            with source.stable_snapshot(expected_revision=header["source_revision"]):
                self.snapshot = _source_matches(source, header)
            _check_time(deadline)
            if not destination.exists():
                _publish_history_stage(destination, header, ticket.manifest_digest)
            self._history = ConversationHistoryStore(destination, instance_id=header["instance_id"], create=False)
            # Retain the exclusive lock across append transactions. This handle
            # is staging-only; failed batches require closing/reopening it.
            self._history._db.execute("PRAGMA locking_mode=EXCLUSIVE")
            self._history._db.execute("BEGIN EXCLUSIVE")
            self._history._db.execute("COMMIT")
            conversations = self._history._db.execute("SELECT id FROM conversations LIMIT 2").fetchall()
            if conversations and (len(conversations) != 1 or conversations[0][0] != header["space_root"]):
                raise ValueError("migration destination is not isolated conversation staging")
            if not conversations:
                raise ValueError("existing empty database is not prepared conversation staging")
            _verify_stage_owner(self._history, destination, ticket.manifest_digest)
            self.copied = self._history.conversation_head(header["space_root"])
            count = self._history._db.execute("SELECT count(*) FROM messages WHERE conversation_id=?",
                                             (header["space_root"],)).fetchone()[0]
            if count != self.copied or not 0 <= self.copied <= self.total:
                raise ValueError("migration destination sequence mismatch")
            for expected in self._manifest.execute("SELECT " + _COLUMNS + " FROM entries WHERE sequence<=? ORDER BY sequence", (self.copied,)):
                _check_time(deadline)
                actual = self._history.get(header["space_root"], expected["message_id"],
                    principal="migration-reconciliation", read_all=True)
                self._verify_record(actual, expected)
            _reconcile_history(self._history, deadline)
            self._verified_complete = self.copied == self.total
            _source_matches(source, header)
            _check_time(deadline)
            self._manifest.set_progress_handler(None, 0)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _verify_record(record, expected):
        historical = json.loads(expected["historical"])
        digest = hashlib.sha256(_encoded([record, historical])).hexdigest()
        if (record is None or record["sequence"] != expected["sequence"] or
                not hmac.compare_digest(digest, expected["record_digest"])):
            raise ValueError("migration destination record mismatch")

    def copy_batch(self, *, max_records=100, max_bytes=2 * 1024 * 1024, time_budget_seconds=2):
        if self._closed or self._failed:
            raise ValueError("migration importer must reopen after close or interruption")
        if type(max_records) is not int or not 1 <= max_records <= 100:
            raise ValueError("invalid migration record budget")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 8 * 1024 * 1024:
            raise ValueError("invalid migration byte budget")
        deadline = _deadline(time_budget_seconds)
        consumed = 0
        committed = self.copied
        try:
            _source_matches(self.source, self.header)
            with self.source.stable_snapshot(expected_revision=self.header["source_revision"]):
                cursor = self._manifest.execute("SELECT " + _COLUMNS + " FROM entries WHERE sequence>? ORDER BY sequence LIMIT ?", (self.copied, max_records))
                try:
                    # Stage ownership is exclusive. Keep one durable transaction
                    # per bounded batch instead of flushing the database for
                    # every message. Reuse normal insertion and derived indexes;
                    # only publish the checkpoint after COMMIT succeeds.
                    with self._history._transaction(write=True):
                        for expected in cursor:
                            if time.monotonic() >= deadline:
                                break
                            if expected["record_bytes"] + consumed > max_bytes:
                                if consumed == 0:
                                    raise ValueError("single migration record exceeds batch byte budget")
                                break
                            entry = read_deliberation_entry(self.snapshot, self.protocol, expected["message_id"])
                            record, historical, digest, record_bytes = _record(entry, self.snapshot)
                            if (record_bytes != expected["record_bytes"] or digest != expected["record_digest"]
                                    or _encoded(historical).decode("utf-8") != expected["historical"]):
                                raise ValueError("migration source record mismatch")
                            self._verify_record(record, expected)
                            actual = self._history._append_in_transaction(record)
                            self._verify_record(actual, expected)
                            committed = expected["sequence"]
                            consumed += record_bytes
                    self.copied = committed
                finally:
                    cursor.close()
            if self.copied == self.total and not self._verified_complete:
                _reconcile_history(self._history, deadline)
                _source_matches(self.source, self.header)
                self._verified_complete = True
            return dict(copied=self.copied, total=self.total, copy_complete=self._verified_complete)
        except BaseException:
            self._failed = True
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._history is not None:
                self._history.close()
        finally:
            if self._manifest is not None:
                self._manifest.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
