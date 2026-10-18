"""Publish verified physical SQLite copies; the owner supplies snapshot authority.

Sources must already be frozen, admitted committed snapshots. This module neither
coordinates transactions across databases nor grants recovery/activation authority.
The destination's parent must exist. The verifier receives self-contained file
paths and must close its handles before returning small, non-secret metadata.
"""
from contextlib import closing, contextmanager
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import time
import uuid


_RESERVE_BYTES = 256 * 1024 * 1024
_METADATA_BYTES = 64 * 1024
_MANIFEST_BYTES = 128 * 1024
_FILE_NAMES = {"graph": "graph.sqlite3", "content": "content.sqlite3"}


def _closed_receipts(parent):
    receipts = []
    for backup in parent.glob('*-closed'):
        path = backup / 'closed-files.json'
        if backup.is_symlink() or backup.is_junction() or not path.is_file():
            continue
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('closed-backup receipt is not a bounded plain file')
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('kind') == 'closed-file-preservation':
            receipts.append((backup, record))
    return sorted(receipts, key=lambda pair: (pair[0].stat().st_mtime_ns, pair[0].name), reverse=True)


def _closed_file_record(path):
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError('closed-backup file is not a plain file')
    with path.open('rb') as reader:
        return dict(name=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.file_digest(reader, 'sha256').hexdigest())


def _verify_closed_receipt(backup, record):
    expected = record['files']
    if not expected or len({item['name'] for item in expected}) != len(expected):
        raise ValueError('closed-backup file inventory is invalid')
    for item in expected:
        if Path(item['name']).name != item['name'] or item['name'] in ('.', '..'):
            raise ValueError('closed-backup filename leaves its directory')
        if (backup / item['name']).stat().st_nlink != 1 or _closed_file_record(backup / item['name']) != item or any(
                Path(str(backup / item['name']) + suffix).exists() for suffix in ('-wal', '-journal')):
            raise ValueError('closed-backup byte verification failed')


def _closed_journal_identity(database):
    """Installer-only logical custody ignores derivable SQLite index layout.

    Hash actual durable rows, rather than trusting cached chain/checkpoint rows;
    a same-revision mutation must not reuse an unrelated physical backup.
    """
    tables = database.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if not {'revisions', 'cell_versions', 'current_cells'} <= {row[0] for row in tables}:
        return None
    digest = hashlib.sha256()
    def field(value):
        if value is None:
            tag, raw = b'n', b''
        elif isinstance(value, bytes):
            tag, raw = b'b', value
        elif isinstance(value, str):
            tag, raw = b's', value.encode('utf-8')
        elif isinstance(value, int):
            tag, raw = b'i', str(value).encode('ascii')
        elif isinstance(value, float):
            tag, raw = b'f', struct.pack('>d', value)
        else:
            raise ValueError('closed journal contains an unsupported SQLite value')
        digest.update(tag + len(raw).to_bytes(8, 'big'))
        digest.update(raw)
    field(database.execute('PRAGMA application_id').fetchone()[0])
    field(database.execute('PRAGMA user_version').fetchone()[0])
    for (name,) in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        columns = database.execute('PRAGMA table_info(' + quoted + ')').fetchall()
        primary = sorted((row[5], row[1]) for row in columns if row[5])
        order = ','.join('"' + column.replace('"', '""') + '"'
                         for column in ([item[1] for item in primary] or [row[1] for row in columns]))
        field(name)
        field(len(columns))
        for column in columns:
            field(column[1])
            field(column[2])
        for row in database.execute('SELECT * FROM ' + quoted + ' ORDER BY ' + order):
            digest.update(b'r')
            for value in row:
                field(value)
        digest.update(b'e')
    head, count = database.execute('SELECT MAX(revision),COUNT(*) FROM revisions').fetchone()
    return dict(head_revision=head, revisions=count, logical_sha256=digest.hexdigest())


def _set_closed_pin(backup, record, pinned):
    if record.get('retain_until_user_deletes') is pinned:
        return
    record = dict(record, retain_until_user_deletes=pinned)
    stamp = backup.stat()
    pending = backup / ('.closed-files-' + uuid.uuid4().hex)
    try:
        with pending.open('x', encoding='utf-8') as writer:
            json.dump(record, writer, sort_keys=True)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(pending, backup / 'closed-files.json')
        # Pin maintenance does not make an older snapshot the newest copy.
        os.utime(backup, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    finally:
        pending.unlink(missing_ok=True)


def _closed_source_score(source, selected, *, exact=False):
    """Match adoption's work-content preference, never filesystem timestamps."""
    if source.is_symlink() or source.is_junction() or source.resolve() != source.absolute():
        raise ValueError('closed-backup journal is a link')
    if any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ValueError('close ArchHub before preserving its pre-upgrade journal')
    # Closed WAL-mode files must not acquire fresh sidecars merely for scoring.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        work, total = 0, 0
        if 'current_cells' in tables:
            total = db.execute('SELECT COUNT(*) FROM current_cells').fetchone()[0]
            if exact:
                shapes = importlib.import_module((__package__ + '.' if __package__ else '') + 'conversation_trace_shapes')
                db.create_function('trace_candidate', 1, lambda ident: int(shapes._trace_family_descriptor(ident)[1]))
                work = db.execute('SELECT COUNT(*) FROM current_cells WHERE trace_candidate(cell_id)=0').fetchone()[0]
            else:
                lower = ''
                for prefix in sorted(('app:deliberation', 'app:agent-session:', 'app:workshop:', 'app:baboom-session:')):
                    work += db.execute('SELECT COUNT(*) FROM current_cells WHERE cell_id>=? AND cell_id<?',
                                       (lower, prefix)).fetchone()[0]
                    lower = prefix + chr(0x10ffff)
                work += db.execute('SELECT COUNT(*) FROM current_cells WHERE cell_id>=?', (lower,)).fetchone()[0]
        head = db.execute('SELECT committed_at,revision FROM revisions ORDER BY revision DESC LIMIT 1').fetchone() if 'revisions' in tables else (0, 0)
    return work, total, head or (0, 0), source == selected


def preserve_closed_application_journals(profile, build, *, keep_count=3, max_bytes=10 * 1024**3):
    """Installer-only, before replacing files: retain verified pre-upgrade bytes.

    The caller closes ArchHub first. An exclusive SQLite lease and byte readback
    fence the copy; a hot WAL/journal or busy owner refuses the upgrade. Completed
    Identical bytes reuse verified custody before reserving copy space. Only the
    latest pre-ADOPT copy is pinned; later copies use the common retention owner.
    Setup extracts this stdlib-only module and backup_retention before installing.
    """
    import re
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', build):
        raise ValueError('invalid closed-backup build')
    profile = Path(profile).resolve()
    candidates = [profile / 'ArchHub-Test/archhub-test.universal.sqlite3']
    root = profile / 'ArchHub'
    candidates.extend(root / name for name in ('authority.sqlite3',
        'archhub-test.universal.sqlite3', 'node-native-wip.json.gz.universal.sqlite3'))
    current = root / 'unified-authority/CURRENT'
    selected = root / 'authority.sqlite3'
    if current.is_file():
        generation = str(uuid.UUID(current.read_text(encoding='ascii').strip()))
        directory = current.parent / 'generations' / generation
        selected = directory / 'authority.sqlite3'
        migration = directory / 'migration.json'
        if migration.is_file():
            if migration.is_symlink() or migration.stat().st_size > 16384:
                raise ValueError('closed-backup migration locator is invalid')
            record = json.loads(migration.read_text(encoding='utf-8'))
            if record.get('adoption') == 'flat-in-place':
                selected = (root / record['journal_relative_path']).resolve()
                if selected not in candidates:
                    raise ValueError('closed-backup selected journal leaves this profile')
        candidates.append(selected)
    candidates = list(dict.fromkeys(path for path in candidates if path.is_file()))
    if not candidates:
        return []
    bounds = {path: _closed_source_score(path, selected) for path in candidates}
    best_floor = max(value[0] for value in bounds.values())
    contenders = [path for path in candidates if bounds[path][1] >= best_floor]
    scores = {path: (_closed_source_score(path, selected, exact=True)
        if len(contenders) > 1 and bounds[path][0] != bounds[path][1] else bounds[path]) for path in contenders}
    primary = max(contenders, key=lambda path: (scores[path][0], scores[path][2], scores[path][3]))
    # Authoritative work receives custody first; a later empty compatibility
    # journal can neither steal its pin nor win merely by being newer.
    candidates.sort(key=lambda path: path != primary)
    completed = []
    for source in candidates:
        if not source.is_file():
            continue
        if source.is_symlink() or source.is_junction() or source.resolve() != source.absolute():
            raise ValueError('closed-backup journal is a link')
        paths = [source]
        content = Path(str(source) + '.conversations.sqlite3')
        if content.is_file():
            paths.append(content)
        parent = source.parent / 'backups'
        parent.mkdir(exist_ok=True)
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('closed-backup directory is a link')
        from contextlib import ExitStack
        retention = importlib.import_module((__package__ + '.' if __package__ else '') + 'backup_retention')
        protected = tuple(name for state in dict.fromkeys((root, source.parent))
            for name in retention.protected_update_backups(state, parent, strict_directory=False))
        with ExitStack() as leases:
            graph_database = None
            for path in paths:
                if path.is_symlink() or path.is_junction() or any(
                        Path(str(path) + suffix).exists() for suffix in ('-wal', '-journal')):
                    raise ValueError('close ArchHub before preserving its pre-upgrade journal')
                db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, isolation_level=None)
                leases.callback(db.close)
                db.execute('PRAGMA busy_timeout=0')
                db.execute('BEGIN EXCLUSIVE')
                if path == source:
                    graph_database = db
            records = [_closed_file_record(path) for path in paths]
            receipts = _closed_receipts(parent)
            latest = next(((path, record) for path, record in receipts if any(
                item['name'] == source.name for item in record['files'])), None)
            if latest is not None:
                _verify_closed_receipt(*latest)
            adopted = Path(str(source) + '.adoption.json').exists()
            pinned = next((path for path, record in receipts
                           if record.get('retain_until_user_deletes') is True and any(
                               item['name'] == primary.name for item in record['files'])), None) if parent == primary.parent / 'backups' else None
            same_files = latest is not None and sorted(latest[1]['files'], key=lambda item: item['name']) == sorted(
                records, key=lambda item: item['name'])
            # Unchanged daily installs need only streaming file SHA, not a row
            # scan. Logical comparison is for changed bytes (e.g. new indexes).
            journal_identity = (latest[1].get('journal_identity') if same_files
                                else _closed_journal_identity(graph_database))
            same_journal = (latest is not None and journal_identity is not None
                and latest[1].get('journal_identity') == journal_identity
                and [item for item in latest[1]['files'] if item['name'] != source.name]
                    == [item for item in records if item['name'] != source.name])
            if same_files or same_journal:
                destination = latest[0]
            else:
                # Once verified pre-ADOPT custody exists, ordinary copies can
                # be reclaimed before reserving the next large physical copy.
                if pinned is not None:
                    pin_record = next(record for path, record in receipts if path == pinned)
                    _verify_closed_receipt(pinned, pin_record)
                    retention.prune_backups(parent, keep=pinned, keep_count=keep_count, max_bytes=max_bytes,
                                  protected_names=protected)
                _require_disk_reserve(parent, sum(item['bytes'] for item in records))
                stage = parent / (build + '-' + uuid.uuid4().hex + '-pending')
                stage.mkdir()
                owned_paths = []
                try:
                    for path in paths:
                        destination = stage / path.name
                        with path.open('rb') as reader, destination.open('xb') as writer:
                            owned_paths.append(destination)
                            shutil.copyfileobj(reader, writer, 1024 * 1024)
                            writer.flush()
                            os.fsync(writer.fileno())
                    receipt = dict(kind='closed-file-preservation', runtime=uuid.uuid4().hex,
                        build=build, producer='archhub-product-installer/v1',
                        retain_until_user_deletes=not adopted and source == primary, files=records,
                        journal_identity=journal_identity)
                    _verify_closed_receipt(stage, receipt)
                    with (stage / 'closed-files.json').open('x', encoding='utf-8') as writer:
                        owned_paths.append(stage / 'closed-files.json')
                        json.dump(receipt, writer, sort_keys=True)
                        writer.flush()
                        os.fsync(writer.fileno())
                    destination = stage.with_name(stage.name.removesuffix('-pending') + '-closed')
                    os.rename(stage, destination)
                except BaseException as error:
                    _cleanup_stage(stage, parent, owned_paths, error)
                    raise
            if not adopted and source == primary:
                pinned = destination
            for path, record in _closed_receipts(parent):
                _set_closed_pin(path, record, path == pinned)
            retention.prune_backups(parent, keep=destination, keep_count=keep_count, max_bytes=max_bytes,
                          protected_names=protected)
            completed.append(str(destination))
    return completed


def _advance(check_budget, stage, completed=None, total=None):
    """Only completed I/O or SQLite work renews a migration's stall lease."""
    check_budget()
    advance = getattr(check_budget, 'advance', None)
    if advance is not None:
        advance(stage, completed, total)


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
            _advance(check_budget, 'Checking SQLite')
        except TimeoutError:
            return 1
        return 0

    try:
        database.execute("PRAGMA cache_size=-1024")
        database.execute("PRAGMA mmap_size=2147483648")
        database.execute("PRAGMA synchronous=FULL")
        # Integrity checking counts B-tree steps, each potentially walking a
        # whole blob overflow chain. A thousand steps can span gigabytes.
        database.set_progress_handler(progress, 1)
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
        previous = None
        def progress(status, remaining, total):
            nonlocal previous
            check_budget()
            if status in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE) and (
                    previous is None or remaining < previous):
                _advance(check_budget, 'Copying journal pages', total - remaining, total)
                previous = remaining
        source.backup(target, pages=64,
            progress=progress, sleep=0.01)
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
            _advance(check_budget, 'Verifying file bytes', size, path.stat().st_size)
        os.fsync(stream.fileno())
    check_budget()
    return {"name": path.name, "size_bytes": size, "sha256": digest.hexdigest()}


def publish_application_recovery(sources, directory, *, verify_copies,
                                 before_publish, deadline, max_bytes=None):
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

    def deadline_check():
        if time.monotonic() >= deadline:
            raise TimeoutError("application recovery time budget exceeded")

    check_budget = deadline_check
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
    shared = sources.get('content') is sources['graph']
    logical_sizes = {}
    for role in roles:
        check_budget()
        if shared and role == 'content':
            logical_sizes[role] = 0
            continue
        pages = sources[role].execute("PRAGMA page_count").fetchone()[0]
        page_size = sources[role].execute("PRAGMA page_size").fetchone()[0]
        if type(pages) is not int or pages < 0 or type(page_size) is not int or page_size <= 0:
            raise ValueError("recovery source page metadata is invalid")
        logical_sizes[role] = pages * page_size
        _advance(check_budget, 'Reading journal size')
    if max_bytes is not None and sum(logical_sizes.values()) + _MANIFEST_BYTES > max_bytes:
        raise ValueError('new recovery exceeds the configured backup disk budget')
    _require_disk_reserve(parent, sum(logical_sizes.values()))
    check_budget()
    stage = parent / ('.application-recovery-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    owned_paths = []
    try:
        copies = {}
        remaining = sum(logical_sizes.values())
        for role in roles:
            check_budget()
            if shared and role == 'content':
                copies[role] = copies['graph']
                continue
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
            if shared and role == 'content':
                files[role] = files['graph']
                continue
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
        physical_bytes = sum(path.stat().st_size for path in set(copies.values())) + len(manifest)
        if max_bytes is not None and physical_bytes > max_bytes:
            raise ValueError('verified recovery exceeds the configured backup disk budget')
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


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Preserve closed pre-upgrade journals')
    parser.add_argument('--closed-profile', required=True)
    parser.add_argument('--build', required=True)
    arguments = parser.parse_args()
    preserve_closed_application_journals(arguments.closed_profile, arguments.build)
