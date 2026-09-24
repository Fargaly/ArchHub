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
    return Path(content_path).resolve().parent / ARCHIVE_DIRECTORY_NAME


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