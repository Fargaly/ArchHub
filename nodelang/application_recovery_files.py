"""Publish verified physical SQLite copies; the owner supplies snapshot authority.

Sources must already be frozen, admitted committed snapshots. This module neither
coordinates transactions across databases nor grants recovery/activation authority.
The destination's parent must exist. The verifier receives self-contained file
paths and must close its handles before returning small, non-secret metadata.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid


_RESERVE_BYTES = 256 * 1024 * 1024
_METADATA_BYTES = 64 * 1024
_MANIFEST_BYTES = 128 * 1024
_FILE_NAMES = {"graph": "graph.sqlite3", "content": "content.sqlite3"}


def _json_bytes(value, limit):
    pieces, used = [], 0
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False,
                               sort_keys=True, separators=(",", ":"))
    for piece in encoder.iterencode(value):
        encoded = piece.encode("utf-8")
        used += len(encoded)
        if used > limit:
            raise ValueError("recovery metadata exceeds its byte budget")
        pieces.append(encoded)
    return b"".join(pieces)


def _require_disk_reserve(parent, logical_bytes):
    if shutil.disk_usage(parent).free < logical_bytes + _RESERVE_BYTES:
        raise OSError("insufficient disk space for recovery copies and 256 MiB reserve")


@contextmanager
def _copy_connection(path, check_budget):
    database = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                               timeout=0.1, isolation_level=None)

    def progress():
        try:
            check_budget()
        except TimeoutError:
            return 1
        return 0

    try:
        database.execute("PRAGMA cache_size=-1024")
        database.execute("PRAGMA synchronous=FULL")
        database.set_progress_handler(progress, 1000)
        yield database
    except BaseException as error:
        try:
            database.close()
        except BaseException as close_error:
            error.add_note("Recovery copy close failed for %s: %s" % (path, close_error))
        if isinstance(error, sqlite3.OperationalError):
            check_budget()
        raise
    else:
        database.close()


def _verify_database(database, check_budget):
    check_budget()
    rows = database.execute("PRAGMA quick_check(1)").fetchall()
    if rows != [("ok",)]:
        raise ValueError("recovery SQLite quick_check failed")
    if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("recovery SQLite foreign_key_check failed")
    check_budget()
    checkpoint = database.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if checkpoint is not None and checkpoint[0] != 0:
        raise ValueError("recovery SQLite checkpoint is busy")
    mode = database.execute("PRAGMA journal_mode=DELETE").fetchone()
    if mode is None or mode[0].lower() != "delete":
        raise ValueError("recovery SQLite copy is not self-contained")
    check_budget()


def _backup_sqlite(source, path, check_budget):
    with _copy_connection(path, check_budget) as target:
        source.backup(target, pages=64,
            progress=lambda status, remaining, total: check_budget(), sleep=0.01)
        _verify_database(target, check_budget)


def _require_sqlite_header(path):
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise ValueError("recovery copy lacks a valid SQLite file header")


def _check_stage(stage, parent):
    if (parent.resolve(strict=True) != parent or stage.parent != parent
            or stage.is_symlink() or stage.resolve(strict=True) != stage):
        raise ValueError("recovery staging directory identity changed")


def _check_file(path, stage, parent):
    _check_stage(stage, parent)
    if (path.parent != stage or path.is_symlink()
            or path.resolve(strict=False) != path):
        raise ValueError("recovery staged file identity changed")


def _check_stage_files(stage, parent, expected_names):
    _check_stage(stage, parent)
    found = set()
    with os.scandir(stage) as entries:
        for entry in entries:
            if entry.name not in expected_names or not entry.is_file(follow_symlinks=False):
                raise ValueError("recovery staging contains an unexpected file: %s" % entry.path)
            found.add(entry.name)
    if found != expected_names:
        raise ValueError("recovery staging is missing a required file")


def _cleanup_stage(stage, parent, paths, error):
    # No recursion or directory enumeration. Only these exact helper-owned
    # filenames can be removed; unknown files keep the directory and a note.
    for path in reversed(paths):
        try:
            _check_file(path, stage, parent)
            path.unlink(missing_ok=True)
        except BaseException as cleanup_error:
            error.add_note("Recovery staging cleanup failed for %s: %s" % (path, cleanup_error))
    try:
        _check_stage(stage, parent)
        stage.rmdir()
    except BaseException as cleanup_error:
        error.add_note("Recovery staging cleanup failed for %s: %s" % (stage, cleanup_error))


def _create_file(path, owned_paths):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    owned_paths.append(path)
    os.close(descriptor)


def _file_evidence(path, check_budget):
    digest = hashlib.sha256()
    size = 0
    with path.open("r+b") as stream:
        while True:
            check_budget()
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
        os.fsync(stream.fileno())
    check_budget()
    return {"name": path.name, "size_bytes": size, "sha256": digest.hexdigest()}


def publish_application_recovery(sources, directory, *, verify_copies,
                                 before_publish, deadline):
    """Copy frozen sources and atomically rename one complete recovery folder.

    ``deadline`` is an absolute monotonic timestamp. ``verify_copies`` receives
    a graph/content Path mapping and a zero-argument budget checker. It may
    perform rolled-back verification, but must leave no transaction/handle open.
    ``before_publish`` performs the owner's fresh admission/release immediately
    before publication. Failure leaves previous recovery folders untouched.
    """
    if type(sources) is not dict or set(sources) not in ({"graph"}, {"graph", "content"}):
        raise ValueError("recovery requires graph and optional content sources only")
    if any(not isinstance(source, sqlite3.Connection) for source in sources.values()):
        raise TypeError("recovery sources must be SQLite connections")
    if not callable(verify_copies) or not callable(before_publish):
        raise TypeError("recovery verification and publication admission must be callable")
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("recovery deadline must be a finite monotonic timestamp")

    def check_budget():
        if time.monotonic() >= deadline:
            raise TimeoutError("application recovery time budget exceeded")

    check_budget()
    destination = Path(directory).absolute()
    if os.path.lexists(destination):
        raise FileExistsError("recovery destination already exists: %s" % destination)
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir():
        raise NotADirectoryError(parent)
    destination = parent / destination.name
    if os.path.lexists(destination):
        raise FileExistsError("recovery destination already exists: %s" % destination)
    roles = tuple(role for role in _FILE_NAMES if role in sources)
    logical_sizes = {}
    for role in roles:
        check_budget()
        pages = sources[role].execute("PRAGMA page_count").fetchone()[0]
        page_size = sources[role].execute("PRAGMA page_size").fetchone()[0]
        if type(pages) is not int or pages < 0 or type(page_size) is not int or page_size <= 0:
            raise ValueError("recovery source page metadata is invalid")
        logical_sizes[role] = pages * page_size
    _require_disk_reserve(parent, sum(logical_sizes.values()))
    check_budget()
    stage = parent / (".application-recovery-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    owned_paths = []
    try:
        copies = {}
        remaining = sum(logical_sizes.values())
        for role in roles:
            check_budget()
            _require_disk_reserve(parent, remaining)
            path = stage / _FILE_NAMES[role]
            _check_file(path, stage, parent)
            _create_file(path, owned_paths)
            # SQLite owns these exact sidecars while a copied database is open.
            owned_paths.extend(Path(str(path) + suffix) for suffix in ("-journal", "-wal", "-shm"))
            _backup_sqlite(sources[role], path, check_budget)
            _require_sqlite_header(path)
            copies[role] = path
            remaining -= logical_sizes[role]
        metadata = verify_copies(dict(copies), check_budget)
        check_budget()
        if type(metadata) is not dict:
            raise TypeError("recovery verifier must return a metadata object")
        # Freeze a bounded JSON value before hashing the verifier's final copies.
        metadata = json.loads(_json_bytes(metadata, _METADATA_BYTES))
        files = {}
        for role, path in copies.items():
            _check_file(path, stage, parent)
            _require_sqlite_header(path)
            with _copy_connection(path, check_budget) as database:
                _verify_database(database, check_budget)
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if os.path.lexists(sidecar):
                    raise ValueError("recovery copy left a SQLite sidecar: %s" % sidecar)
            files[role] = _file_evidence(path, check_budget)
        manifest_path = stage / "recovery.json"
        _check_file(manifest_path, stage, parent)
        _create_file(manifest_path, owned_paths)
        manifest = _json_bytes({"format": 1, "files": files, "metadata": metadata}, _MANIFEST_BYTES)
        with manifest_path.open("r+b") as stream:
            stream.write(manifest)
            stream.flush()
            os.fsync(stream.fileno())
        _require_disk_reserve(parent, 0)
        expected_names = {path.name for path in copies.values()} | {"recovery.json"}
        _check_stage_files(stage, parent, expected_names)
        check_budget()
        before_publish()
        check_budget()
        _check_stage_files(stage, parent, expected_names)
        if os.path.lexists(destination):
            raise FileExistsError("recovery destination already exists: %s" % destination)
        check_budget()
        os.rename(stage, destination)
        return destination
    except BaseException as error:
        _cleanup_stage(stage, parent, owned_paths, error)
        raise
