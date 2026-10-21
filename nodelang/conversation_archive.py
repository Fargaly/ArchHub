"""User-visible conversation archive written before retention removes content.

One JSONL file per conversation in the user's data folder, beside the content
store, with a fixed-width sidecar index (sequence -> offset, length, sha256 of
the line). Before any message is deleted its exact canonical line must be in
the archive: an existing line is compared byte for byte, a new line is written,
forced to disk and read back. Any difference keeps the message, writes a
conflict file and refuses the batch. Under the owner lock only the batch's own
lines and an unindexed tail of at most TAIL_LIMIT bytes are read; a stale or
missing index is rebuilt outside the lock. Nothing here writes the graph.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import uuid


ARCHIVE_DIRECTORY_NAME = "Conversation archive"
STATUS_FILE_NAME = "retention-status.json"
ARCHIVE_VERSION = 1
TAIL_LIMIT = 2 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_LINE_BYTES = 1024 * 1024
_MESSAGE_FIELDS = ("id", "conversation_id", "sequence", "author", "content", "category",
                   "recipients", "refs", "evidence", "reply_to", "created_at", "idempotency_key")
_RECORD = struct.Struct(">QI32s")          # offset, length, sha256 of the line
_HEADER = struct.Struct(">8sQ")             # magic, bytes of the archive covered
_MAGIC = b"AHCIDX01"
RECORD_SIZE = _RECORD.size                  # 44; slot N holds sequence N, slot 0 the header


class ArchiveConflict(ValueError):
    """The archive holds a different line for a message about to be deleted."""


class ArchiveIndexStale(RuntimeError):
    """The index does not cover the archive; rebuild it outside the owner lock."""


def archive_directory(content_path):
    parent = Path(content_path).resolve().parent
    # Adoption relocates only journal companions into a generation. Archives
    # remain at the stable profile root, outside generation/rollback custody.
    try:
        generation = str(uuid.UUID(parent.name)) == parent.name
    except ValueError:
        generation = False
    if (generation and parent.parent.name == 'generations'
            and parent.parent.parent.name == 'unified-authority'):
        migration = parent / 'migration.json'
        if migration.is_file():
            if migration.stat().st_size > 16384:
                raise ArchiveConflict('archive adoption metadata exceeds its bound')
            try:
                record = json.loads(migration.read_text(encoding='utf-8'))
                source = Path(record['source_path'])
                current = parent.parent.parent / 'CURRENT'
                if (record.get('format') != 'archhub-application-journal-migration/v1'
                        or record.get('generation_id') != parent.name
                        or not source.is_absolute()
                        or current.stat().st_size > 128
                        or current.read_text(encoding='ascii').strip() != parent.name):
                    raise ValueError('unselected archive adoption metadata')
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ArchiveConflict('archive adoption metadata is invalid') from error
            # Old metadata contains an absolute path from the previous user
            # profile. Only its released basename/layout is portable authority.
            profile = parent.parents[2]
            parent = (profile.parent / 'ArchHub-Test' if source.parent.name == 'ArchHub-Test'
                      else profile)
        else:
            parent = parent.parent.parent.parent
    return parent / ARCHIVE_DIRECTORY_NAME


def archive_file(directory, conversation_id):
    if type(conversation_id) is not str or not conversation_id:
        raise ValueError("archive conversation is invalid")
    # Conversation ids are graph roots with ':' and other path-hostile bytes.
    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:24]
    return Path(directory) / ("conversation-%s.jsonl" % digest)


def index_file(path):
    return Path(str(path) + ".index")


def conflict_file(path):
    return Path(str(path) + ".conflict.json")


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_line(message):
    """The exact bytes one message occupies in its archive."""
    return _line({"kind": "message", **{field: message[field] for field in _MESSAGE_FIELDS}})


def _header_line(conversation_id, instance_id):
    return _line({"kind": "conversation-archive", "version": ARCHIVE_VERSION,
                  "conversation_id": conversation_id, "instance_id": instance_id})


def _message(value, conversation_id):
    if type(value) is not dict or value.get("kind") != "message":
        raise ValueError("conversation archive record is invalid")
    message = {field: value.get(field) for field in _MESSAGE_FIELDS}
    if (message["conversation_id"] != conversation_id or type(message["sequence"]) is not int
            or message["sequence"] < 1):
        raise ValueError("conversation archive record is invalid")
    return message


def _check_header(raw, conversation_id, instance_id, path=None):
    # Compared by its fields, not bytes: a user may open and re-save the file.
    try:
        header = json.loads(raw.decode("utf-8"))
    except ValueError:
        header = None
    if header != json.loads(_header_line(conversation_id, instance_id)):
        if path is not None:
            _write_conflicts(path, [(0, _header_line(conversation_id, instance_id), raw)])
        raise ArchiveConflict("conversation archive belongs to another conversation")


def _write_conflicts(path, conflicts):
    conflict_file(path).write_text(json.dumps([{"sequence": sequence,
        "in_store": expected.decode("utf-8", "replace"), "in_archive": found.decode("utf-8", "replace")}
        for sequence, expected, found in conflicts], ensure_ascii=False, indent=1), encoding="utf-8")


def read_archive(path, conversation_id, instance_id):
    """Every complete archived message, oldest first (restore; never under the owner lock)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("conversation archive is missing")
    with open(path, "rb") as handle:
        data = handle.read(_MAX_ARCHIVE_BYTES + 1)
    if len(data) > _MAX_ARCHIVE_BYTES:
        raise ValueError("conversation archive exceeds its size limit")
    lines = data[:data.rfind(b"\n") + 1].splitlines(keepends=True)
    if not lines:
        return []
    _check_header(lines[0], conversation_id, instance_id)
    messages = {}
    for raw in lines[1:]:
        message = _message(json.loads(raw.decode("utf-8")), conversation_id)
        prior = messages.get(message["sequence"])
        if prior is not None and prior != message:
            raise ValueError("conversation archive holds two different messages at one sequence")
        messages[message["sequence"]] = message
    return [messages[sequence] for sequence in sorted(messages)]


def _read_record(index, sequence):
    index.seek(sequence * RECORD_SIZE)
    raw = index.read(RECORD_SIZE)
    if len(raw) < RECORD_SIZE or raw == bytes(RECORD_SIZE):
        return None
    return _RECORD.unpack(raw)


def _write_record(index, sequence, offset, length, digest):
    index.seek(sequence * RECORD_SIZE)
    index.write(_RECORD.pack(offset, length, digest))


def _read_covered(index):
    index.seek(0)
    raw = index.read(RECORD_SIZE)
    if len(raw) < _HEADER.size:
        return None
    magic, covered = _HEADER.unpack(raw[:_HEADER.size])
    return covered if magic == _MAGIC else None


def _write_covered(index, covered):
    index.seek(0)
    index.write(_HEADER.pack(_MAGIC, covered).ljust(RECORD_SIZE, b"\0"))


def _read_at(handle, offset, length):
    handle.seek(offset)
    return handle.read(length)


def _index_lines(data_handle, index, start, end, conversation_id, instance_id, conflicts):
    """Index complete lines in data[start:end]; record differing duplicates."""
    offset = start
    data = _read_at(data_handle, start, end - start)
    for raw in data.splitlines(keepends=True):
        if len(raw) > _MAX_LINE_BYTES:
            raise ValueError("conversation archive line exceeds its size limit")
        if offset == 0:
            _check_header(raw, conversation_id, instance_id, data_handle.name)
        else:
            sequence = _message(json.loads(raw.decode("utf-8")), conversation_id)["sequence"]
            digest = hashlib.sha256(raw).digest()
            prior = _read_record(index, sequence)
            if prior is None:
                _write_record(index, sequence, offset, len(raw), digest)
            elif prior[2] != digest:
                conflicts.append((sequence, _read_at(data_handle, prior[0], prior[1]), raw))
        offset += len(raw)
    return offset


def rebuild_index(path, conversation_id, instance_id, *, deadline):
    """Rebuild the sidecar index from the whole archive; run OUTSIDE the owner lock."""
    path = Path(path)
    temporary = Path(str(index_file(path)) + ".tmp")
    conflicts = []
    with open(path, "rb") as data, open(temporary, "w+b") as index:
        _write_covered(index, 0)
        size = os.fstat(data.fileno()).st_size
        if size > _MAX_ARCHIVE_BYTES:
            raise ValueError("conversation archive exceeds its size limit")
        offset = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("conversation archive index rebuild exceeded its budget")
            chunk = _read_at(data, offset, min(4 * 1024 * 1024, size - offset))
            end = chunk.rfind(b"\n") + 1
            if end == 0:
                break
            offset = _index_lines(data, index, offset, offset + end, conversation_id, instance_id, conflicts)
        _write_covered(index, offset)
    if conflicts:
        _write_conflicts(path, conflicts)
        os.remove(temporary)
        raise ArchiveConflict("conversation archive holds two different lines for one message")
    os.replace(temporary, index_file(path))
    return offset


def export_messages(path, conversation_id, instance_id, messages, *, check=None):
    """Make every message about to be deleted present, byte for byte, in its archive.

    Returns the sequences newly written. Raises ArchiveConflict (and writes a
    conflict file) when any archived line differs, ArchiveIndexStale when the
    index must be rebuilt first; either way nothing may be deleted.
    """
    check = check or (lambda: None)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    index_path = index_file(path)
    if conflict_file(path).exists():
        raise ArchiveConflict("conversation archive has an unresolved conflict file")
    if not path.exists() or path.stat().st_size == 0:
        with open(path, "wb") as data:
            data.write(_header_line(conversation_id, instance_id))
            data.flush()
            os.fsync(data.fileno())
        with open(index_path, "wb") as index:
            _write_covered(index, 0)
    if not index_path.exists():
        raise ArchiveIndexStale("conversation archive index is missing")
    conflicts, pending = [], []
    with open(path, "r+b") as data, open(index_path, "r+b") as index:
        size = os.fstat(data.fileno()).st_size
        covered = _read_covered(index)
        if covered is None or covered > size or size - covered > TAIL_LIMIT or size > _MAX_ARCHIVE_BYTES:
            raise ArchiveIndexStale("conversation archive index does not cover the archive")
        check()
        # The header is re-read every time: 4 KiB at most.
        first = _read_at(data, 0, 4096)
        _check_header(first[:first.find(b"\n") + 1], conversation_id, instance_id, path)
        if size > covered:
            # Complete lines appended after the last indexed export (a crash
            # between the data fsync and the index write). A torn last line
            # is not content: it is cut and its message written again.
            tail = _read_at(data, covered, size - covered)
            end = covered + tail.rfind(b"\n") + 1
            covered = _index_lines(data, index, covered, end, conversation_id, instance_id, conflicts)
            if end < size:
                data.truncate(end)
                size = end
        for message in sorted(messages, key=lambda row: row["sequence"]):
            check()
            if message["conversation_id"] != conversation_id:
                raise ValueError("archive batch mixes conversations")
            expected = canonical_line(message)
            record = _read_record(index, message["sequence"])
            if record is None:
                pending.append((message["sequence"], expected))
                continue
            found = _read_at(data, record[0], record[1])
            if found != expected or hashlib.sha256(found).digest() != record[2]:
                conflicts.append((message["sequence"], expected, found))
        if conflicts:
            _write_conflicts(path, conflicts)
            raise ArchiveConflict("conversation archive line differs from the message to be removed")
        offsets = []
        data.seek(size)
        for sequence, expected in pending:
            offsets.append((sequence, data.tell(), expected))
            data.write(expected)
        data.flush()
        os.fsync(data.fileno())
        check()
        for sequence, offset, expected in offsets:
            if _read_at(data, offset, len(expected)) != expected:
                raise ArchiveConflict("conversation archive did not read back what was written")
        for sequence, offset, expected in offsets:
            _write_record(index, sequence, offset, len(expected), hashlib.sha256(expected).digest())
        _write_covered(index, data.tell() if offsets else size)
        # The index is derived: no fsync, a crash only leaves a tail to re-index.
        index.flush()
    return tuple(sequence for sequence, _offset, _expected in offsets)


def write_status(directory, status, name=STATUS_FILE_NAME):
    """Replace one small record atomically; never appended."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    temporary = directory / (name + ".tmp")
    temporary.write_bytes(json.dumps(status, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    os.replace(temporary, target)


def read_status(directory, name=STATUS_FILE_NAME, limit=65536):
    target = Path(directory) / name
    try:
        if target.stat().st_size > limit:
            return None
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if type(value) is dict else None
    except (OSError, ValueError):
        return None


def run_record(result, *, now=None):
    """The fields Settings shows for one maintenance pass."""
    return {"at": float(time.time() if now is None else now), "status": str(result.get("status")),
            "inspected": int(result.get("inspected") or 0), "protected": int(result.get("protected") or 0),
            "archived": int(result.get("archived") or 0), "purged": int(result.get("purged") or 0),
            "exported": int(result.get("exported") or 0)}


__all__ = ["ARCHIVE_DIRECTORY_NAME", "ArchiveConflict", "ArchiveIndexStale", "STATUS_FILE_NAME",
           "TAIL_LIMIT", "archive_directory", "archive_file", "canonical_line", "conflict_file",
           "export_messages", "index_file", "read_archive", "read_status", "rebuild_index",
           "run_record", "write_status"]

# The legacy trace evidence shares one cold archive beneath the conversation
# owner. Opening the live journal does not call any function in this section.
TRACE_ARCHIVE_NAME = "agent-traces.sqlite3"


def trace_archive_path(content_path):
    return archive_directory(content_path) / TRACE_ARCHIVE_NAME


def _trace_digest(row):
    digest = hashlib.sha256()
    for value in row:
        data = value if isinstance(value, bytes) else str(value).encode("utf-8")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _open_trace_archive(path, authority, *, create, busy_timeout_seconds: float = 0.05,
                        check_same_thread=True):
    import sqlite3
    path = Path(path).absolute()
    if path.resolve() != path or path.is_symlink() or path.is_junction():
        raise ArchiveConflict("trace archive path is an alias")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=busy_timeout_seconds, isolation_level=None,
                                     check_same_thread=check_same_thread)
    else:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                     timeout=busy_timeout_seconds, isolation_level=None,
                                     check_same_thread=check_same_thread)
    try:
        if create:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS trace_identity("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1),authority TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS trace_current("
                "cell_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,link0 TEXT NOT NULL,"
                "link1 TEXT NOT NULL,atom BLOB NOT NULL,session_id TEXT NOT NULL,digest TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS trace_current_session "
                               "ON trace_current(session_id,cell_id)")
            connection.execute("CREATE TABLE IF NOT EXISTS trace_versions("
                "revision INTEGER NOT NULL,cell_id TEXT NOT NULL,link0 TEXT NOT NULL,"
                "link1 TEXT NOT NULL,atom BLOB NOT NULL,source_rowid INTEGER NOT NULL,digest TEXT NOT NULL,"
                "PRIMARY KEY(revision,cell_id))")
            connection.execute("CREATE INDEX IF NOT EXISTS trace_versions_cell "
                               "ON trace_versions(cell_id,revision)")
            connection.execute("INSERT OR IGNORE INTO trace_identity VALUES(1,?)", (authority,))
        identity = connection.execute("SELECT authority FROM trace_identity WHERE singleton=1").fetchone()
        if identity is None or (authority is not None and identity[0] != authority):
            raise ArchiveConflict("trace archive belongs to another journal")
        return connection
    except BaseException:
        connection.close()
        raise


def preserve_trace_batch(connection, archive_path, authority, cell_ids, session_ids, check):
    """Make exact current/history custody durable and read it back.

    The caller keeps the live owner locked through admission and publication.
    An interruption leaves the original journal untouched. Replays compare
    pre-existing archive rows, so a corrupt copy never becomes accepted custody.
    The returned cold handle belongs to the caller and must be closed.
    """
    from contextlib import closing
    ids = tuple(dict.fromkeys(cell_ids))
    if not ids or len(ids) > 256 or set(ids) != set(session_ids) or not callable(check):
        raise ValueError("invalid bounded trace preservation batch")
    if choose_trace_batch(connection, ids, check) != ids:
        raise ValueError('trace preservation requires a smaller adaptive batch')
    cold = _open_trace_archive(archive_path, authority, create=True)
    try:
        cold.execute("BEGIN IMMEDIATE")
        if cold.execute("SELECT 1 FROM sqlite_master WHERE name='trace_session_counts'").fetchone() is None:
            cold.execute('CREATE TABLE trace_session_counts(session_id TEXT PRIMARY KEY,cell_count INTEGER NOT NULL)')
            # Once for archives created before the incremental counter existed.
            # Normal new archives are empty here; subsequent batches never scan.
            check()
            cold.execute('INSERT INTO trace_session_counts SELECT session_id,COUNT(*) FROM trace_current GROUP BY session_id')
        versions = 0
        for cell_id in ids:
            check()
            row = connection.execute("SELECT cell_id,revision,link0,link1,atom "
                "FROM current_cells WHERE cell_id=?", (cell_id,)).fetchone()
            if row is None:
                raise ArchiveConflict("trace candidate changed before export")
            current = (*row, session_ids[cell_id])
            expected = (*current, _trace_digest(current))
            present = cold.execute("SELECT cell_id,revision,link0,link1,atom,session_id,digest "
                                  "FROM trace_current WHERE cell_id=?", (cell_id,)).fetchone()
            if present is not None and present != expected:
                raise ArchiveConflict("trace archive current content differs")
            cold.execute("INSERT OR IGNORE INTO trace_current VALUES(?,?,?,?,?,?,?)", expected)
            if present is None:
                cold.execute('INSERT INTO trace_session_counts VALUES(?,1) ON CONFLICT(session_id) DO UPDATE SET cell_count=cell_count+1',
                    (session_ids[cell_id],))
            with closing(connection.execute("SELECT revision,cell_id,link0,link1,atom,rowid "
                    "FROM cell_versions WHERE cell_id=? ORDER BY revision", (cell_id,))) as rows:
                for version in rows:
                    check()
                    expected_version = (*version, _trace_digest(version))
                    present = cold.execute("SELECT revision,cell_id,link0,link1,atom,source_rowid,digest "
                        "FROM trace_versions WHERE revision=? AND cell_id=?", version[:2]).fetchone()
                    if present is not None and present != expected_version:
                        raise ArchiveConflict("trace archive historical content differs")
                    cold.execute("INSERT OR IGNORE INTO trace_versions VALUES(?,?,?,?,?,?,?)", expected_version)
                    versions += 1
            check()
            if cold.execute("SELECT cell_id,revision,link0,link1,atom,session_id,digest "
                    "FROM trace_current WHERE cell_id=?", (cell_id,)).fetchone() != expected:
                raise ArchiveConflict("trace archive read-back differs")
        cold.commit()
        for cell_id in ids:
            check()
            current = cold.execute("SELECT cell_id,revision,link0,link1,atom,session_id,digest "
                "FROM trace_current WHERE cell_id=?", (cell_id,)).fetchone()
            if current is None or _trace_digest(current[:-1]) != current[-1]:
                raise ArchiveConflict("trace archive current read-back differs")
            for row in cold.execute("SELECT revision,cell_id,link0,link1,atom,source_rowid,digest "
                                    "FROM trace_versions WHERE cell_id=?", (cell_id,)):
                check()
                if _trace_digest(row[:-1]) != row[-1]:
                    raise ArchiveConflict("trace archive historical read-back differs")
        return cold, versions
    except BaseException:
        cold.close()
        raise


def choose_trace_batch(connection, cell_ids, check, *, max_bytes=8 * 1024 * 1024):
    """Choose a byte-bounded prefix; one large Cell always makes progress.

    Version rows are streamed with cancellation between rows rather than an
    aggregate that can strand a history-heavy Cell behind every idle deadline.
    Exact custody still streams and verifies every version before retirement.
    """
    from contextlib import closing
    ids = tuple(dict.fromkeys(cell_ids))
    if not ids or len(ids) > 256 or type(max_bytes) is not int or max_bytes < 1 or not callable(check):
        raise ValueError('invalid bounded trace selection')
    selected, total = [], 0
    for cell_id in ids:
        check()
        size = 0
        with closing(connection.execute('SELECT length(CAST(cell_id AS BLOB))+length(CAST(link0 AS BLOB))+length(CAST(link1 AS BLOB))+length(atom)+64 FROM cell_versions WHERE cell_id=?',
                (cell_id,))) as rows:
            for row in rows:
                check()
                size += row[0]
                if total + size > max_bytes:
                    break
        if total + size > max_bytes:
            return tuple(selected) if selected else (cell_id,)
        selected.append(cell_id)
        total += size
    return tuple(selected)


def read_trace_archive(path, session_id, *, limit=100, after=""):
    """On-demand cold page, verified per Cell, never called by boot."""
    from contextlib import closing
    if type(session_id) is not str or not session_id or type(after) is not str:
        raise ValueError("trace archive session/cursor is invalid")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("trace archive page size is invalid")
    with closing(_open_trace_archive(path, None, create=False)) as cold:
        selected, page_bytes, more = [], 0, False
        with closing(cold.execute("SELECT cell_id,revision,link0,link1,atom,session_id,digest "
                "FROM trace_current WHERE session_id=? AND cell_id>? ORDER BY cell_id LIMIT ?",
                (session_id, after, limit + 1))) as rows:
            for row in rows:
                if _trace_digest(row[:-1]) != row[-1]:
                    raise ArchiveConflict("trace archive content verification failed")
                cost = sum(len(value.encode('utf-8')) if isinstance(value, str)
                    else len(value) if isinstance(value, bytes) else 16 for value in row)
                if len(selected) == limit or (selected and page_bytes + cost > 8 * 1024 * 1024):
                    more = True
                    break
                selected.append(row)
                page_bytes += cost
        return {"cells": [{"id": row[0], "revision": row[1], "link0": row[2],
            "link1": row[3], "atom": row[4]} for row in selected],
            "next": selected[-1][0] if more else None}
