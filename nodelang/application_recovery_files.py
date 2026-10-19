"""Publish verified physical SQLite copies; the owner supplies snapshot authority.

Sources must already be frozen, admitted committed snapshots. This module neither
coordinates transactions across databases nor grants recovery/activation authority.
The destination's parent must exist. The verifier receives self-contained file
paths and must close its handles before returning small, non-secret metadata.
"""
from contextlib import closing, contextmanager, ExitStack
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
_INSTALL_RESERVE_BYTES = 25 * 1024**3
_METADATA_BYTES = 64 * 1024
_MANIFEST_BYTES = 128 * 1024
_FILE_NAMES = {"graph": "graph.sqlite3", "content": "content.sqlite3"}


@contextmanager
def _closed_source_lease(path):
    """Deny writers/deletion without SQLite's 1-GiB Windows byte-range lock."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError('close ArchHub before preserving its pre-upgrade journal: ' + str(ctypes.WinError(ctypes.get_last_error())))
        close = kernel.CloseHandle
        close.argtypes = (wintypes.HANDLE,)
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                yield db
        finally:
            close(handle)
    else:
        with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, isolation_level=None)) as db:
            db.execute('PRAGMA busy_timeout=0')
            db.execute('BEGIN EXCLUSIVE')
            yield db


def _copy_closed_file(source, destination, report):
    """Stream one closed file; the caller verifies its complete byte digest."""
    with source.open('rb') as reader, destination.open('xb') as writer:
        copied = 0
        last_report = time.monotonic()
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
            copied += len(chunk)
            if time.monotonic() - last_report >= 0.5:
                report('Copying %s: %d / %d bytes' % (source.name, copied, source.stat().st_size))
                last_report = time.monotonic()
        writer.flush()
        os.fsync(writer.fileno())


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


def _owned_backup_directory(profile, directory):
    """Validate current and historical locations with the same ownership rule."""
    selected = Path(directory)
    identity = hashlib.sha256(str(profile).casefold().encode('utf-8')).hexdigest()
    if (not selected.is_absolute() or str(selected).startswith(('\\\\', '//'))
            or (selected != profile / 'ArchHub/backups' and
                (selected.name != 'profile-' + identity or selected.parent.name != 'ArchHub-backups'))):
        raise ValueError('installer backup directory is outside its owned container')
    if selected != profile / 'ArchHub/backups' and any(selected.is_relative_to(profile / name)
            for name in ('ArchHub', 'ArchHub-Test')):
        raise ValueError('installer backup directory is outside its owned container')
    for ancestor in (selected, *selected.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError('installer backup directory contains a link')
    return selected


def backup_location(profile):
    """Installer-owned physical preference; Settings and Setup use this file."""
    profile = Path(profile).resolve()
    path = profile / 'ArchHub/backup-location.json'
    if not path.exists():
        return {'location': 'auto', 'directory': str(profile / 'ArchHub/backups')}
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 16384:
        raise ValueError('installer backup location is not a bounded plain file')
    record = json.loads(path.read_text(encoding='utf-8'))
    if (type(record) is not dict or type(record.get('location')) is not str
            or type(record.get('directory')) is not str):
        raise ValueError('installer backup location is invalid')
    history = record.get('managed_directories', [])
    if type(history) is not list or any(type(item) is not str for item in history):
        raise ValueError('installer backup directory history is invalid')
    for directory in [record['directory'], *history]:
        _owned_backup_directory(profile, directory)
    return record


def set_backup_location(profile, location, *, directory=None):
    """One explicit preference; custom locations get a dedicated owned child."""
    profile = Path(profile).resolve()
    location = str(location).strip()
    if not location or (location != 'auto' and not Path(location).is_absolute()):
        raise ValueError('backup location must be auto or an absolute local folder')
    identity = hashlib.sha256(str(profile).casefold().encode('utf-8')).hexdigest()
    default = profile / 'ArchHub/backups'
    if location != 'auto':
        base = Path(location)
        if str(base).startswith(('\\\\', '//')):
            raise ValueError('backup location must be a local folder, not a network share')
        for live in (profile / 'ArchHub', profile / 'ArchHub-Test'):
            if base == live or base.is_relative_to(live):
                raise ValueError('backup location must be outside application profile directories')
    selected = Path(directory) if directory is not None else (
        default if location == 'auto' else Path(location) / 'ArchHub-backups' / ('profile-' + identity))
    if not selected.is_absolute():
        raise ValueError('backup directory must be absolute')
    for live in (profile / 'ArchHub', profile / 'ArchHub-Test'):
        if selected == live or live.is_relative_to(selected):
            raise ValueError('backup directory cannot contain a live application profile')
    for path in (selected, *selected.parents, profile / 'ArchHub'):
        if path.is_symlink() or path.is_junction():
            raise ValueError('installer backup location contains a link')
    _owned_backup_directory(profile, selected)
    previous = backup_location(profile)
    managed = list(dict.fromkeys([*previous.get('managed_directories', []), previous['directory'], str(selected)]))
    record = dict(location=location, directory=str(selected), managed_directories=managed)
    if len(json.dumps(record).encode('utf-8')) > 16384:
        raise ValueError('installer backup location history exceeds its bounded file size; existing custody was kept')
    target = profile / 'ArchHub/backup-location.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_junction():
        raise ValueError('installer backup preference is a link')
    pending = target.with_name('.backup-location-' + uuid.uuid4().hex)
    try:
        with pending.open('x', encoding='utf-8') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)
    return record


def _fixed_backup_drives():
    if os.name != 'nt':
        return []
    try:
        drives = os.listdrives()
    except OSError:
        return []
    return [Path(drive) for drive in drives
            if _local_backup_path(Path(drive))]


def _backup_volume_info(path):
    """Probe native volume/storage facts; unknown or virtual storage is ineligible."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    root = Path(path).anchor
    label, filesystem = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    if (not root or kernel.GetDriveTypeW(root) != 3 or not kernel.GetVolumeInformationW(
            root, label, len(label), None, None, None, filesystem, len(filesystem))):
        return None
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    handle = create('\\\\.\\' + root.rstrip('\\'), 0, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return None
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    ioctl = kernel.DeviceIoControl
    ioctl.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
    query, descriptor, returned = ctypes.create_string_buffer(struct.pack('<III', 0, 0, 0)), ctypes.create_string_buffer(4096), wintypes.DWORD()
    try:
        if not ioctl(handle, 0x2D1400, query, 12, descriptor, len(descriptor), ctypes.byref(returned), None) or returned.value < 36:
            return None
        # StorageDeviceProperty: reject unknown, network/iSCSI, virtual, VHD and
        # storage-space buses. A fixed cloud filesystem alone is not a disk.
        bus = struct.unpack_from('<I', descriptor.raw, 28)[0]
        physical = bus in (1, 2, 3, 7, 8, 10, 11, 12, 13, 17, 19) and not descriptor.raw[10]
        return dict(label=label.value, filesystem=filesystem.value, physical=physical)
    finally:
        close(handle)


def _backup_sync_roots():
    """Registered sync roots plus the providers' conventional local locations."""
    home = Path(os.environ.get('USERPROFILE', Path.home()))
    roots = [home / name for name in ('Google Drive', 'My Drive', 'OneDrive', 'Dropbox', 'Box', 'Box Sync')]
    roots.extend(Path(value) for key, value in os.environ.items() if key.casefold().startswith('onedrive') and value)
    if os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager') as manager:
                    for index in range(winreg.QueryInfoKey(manager)[0]):
                        try:
                            with winreg.OpenKey(manager, winreg.EnumKey(manager, index) + r'\UserSyncRoots') as key:
                                for item in range(winreg.QueryInfoKey(key)[1]):
                                    _, value, kind = winreg.EnumValue(key, item)
                                    if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and value:
                                        roots.append(Path(os.path.expandvars(value)))
                        except FileNotFoundError:
                            continue
            except FileNotFoundError:
                continue
    for variable in ('LOCALAPPDATA', 'APPDATA'):
        base = os.environ.get(variable)
        info = Path(base) / 'Dropbox/info.json' if base else None
        if info and info.is_file():
            if info.is_symlink() or info.is_junction() or info.stat().st_size > _METADATA_BYTES:
                raise ValueError('Dropbox sync location is unavailable')
            accounts = json.loads(info.read_text(encoding='utf-8'))
            if not isinstance(accounts, dict):
                raise ValueError('Dropbox sync location is unavailable')
            for account in accounts.values():
                if isinstance(account, dict) and isinstance(account.get('path'), str):
                    roots.append(Path(account['path']))
    if any(not root.is_absolute() for root in roots):
        raise ValueError('A sync location is unavailable')
    return roots


def _local_backup_path(path):
    import re
    path = Path(path)
    try:
        if str(path).startswith(('\\\\', '//')) or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            return False
        if os.name == 'nt':
            volume = _backup_volume_info(path)
            if not volume or not volume['physical'] or volume['filesystem'].casefold() not in ('ntfs', 'refs'):
                return False
            if re.search(r'google|gdrive|onedrive|dropbox|\bbox\b', volume['label'], re.IGNORECASE):
                return False
        if any(re.match(r'^(google drive|my drive|onedrive|dropbox|box)(\b|[-_])', part, re.IGNORECASE) for part in path.parts):
            return False
        return not any(path == root or path.is_relative_to(root) for root in _backup_sync_roots())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _install_reserve(profile, destination):
    """Keep25GiB on the system/profile disk; other drives retain256MiB."""
    return _INSTALL_RESERVE_BYTES if Path(destination).anchor.casefold() == Path(profile).anchor.casefold() else _RESERVE_BYTES


def _select_backup_location(profile, planned_bytes):
    preference = backup_location(profile)
    chosen = Path(preference['directory'])
    probe = next((path for path in (chosen, *chosen.parents) if path.exists()), profile)
    def fits(path, capacity_probe):
        try:
            return _local_backup_path(path) and shutil.disk_usage(capacity_probe).free - planned_bytes >= _install_reserve(profile, path)
        except OSError:
            return False
    admitted = fits(chosen, probe)
    if preference['location'] == 'auto' and not admitted:
        # Test the actual owned destination too: a sync root can be a child
        # folder on an otherwise eligible physical disk.
        identity = hashlib.sha256(str(profile).casefold().encode('utf-8')).hexdigest()
        destinations = [(drive, drive / 'ArchHub-backups' / ('profile-' + identity))
                        for drive in _fixed_backup_drives()]
        destinations = [(drive, destination) for drive, destination in destinations if fits(destination, drive)]
        if destinations:
            _drive, chosen = max(destinations, key=lambda item: shutil.disk_usage(item[0]).free)
            admitted = True
    if not admitted:
        raise OSError('Free space on a local NTFS or ReFS disk while keeping 25 GiB on the system disk, or choose a backup folder there outside Google Drive, OneDrive, Dropbox and Box.')
    return set_backup_location(profile, preference['location'], directory=chosen)


def installer_backup_directory(profile, source):
    """One installer custody container; isolate same-name legacy journals."""
    profile, source = Path(profile).resolve(), Path(source).resolve()
    relative = source.relative_to(profile).as_posix()
    identity = hashlib.sha256(relative.encode('utf-8')).hexdigest()
    return Path(backup_location(profile)['directory']) / ('journal-' + identity)


def _installer_copies(profile, container):
    """Adopt 0400's existing physical copies into this same retention owner."""
    roots = {Path(container), profile / 'ArchHub/backups', profile / 'ArchHub-Test/backups',
             *(Path(path) for path in backup_location(profile).get('managed_directories', []))}
    copies = set()
    for root in roots:
        if not root.is_dir() or root.is_symlink() or root.is_junction():
            continue
        parents = [root, *(p for p in root.glob('journal-*')
                          if p.is_dir() and not p.is_symlink() and not p.is_junction())]
        for parent in parents:
            for child in parent.iterdir():
                if not child.is_dir() or child.is_symlink() or child.is_junction() or child.name.endswith('-pending'):
                    continue
                receipt = child / 'closed-files.json'
                legacy = child / 'recovery.json'
                if receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size <= 65536:
                    record = json.loads(receipt.read_text(encoding='utf-8'))
                    if (record.get('producer') == 'archhub-product-installer/v1'
                            and record.get('kind') == 'closed-file-preservation'):
                        copies.add(child)
                elif legacy.is_file() and not legacy.is_symlink() and legacy.stat().st_size <= _MANIFEST_BYTES:
                    record = json.loads(legacy.read_text(encoding='utf-8'))
                    if (type(record) is dict and record.get('format') == 1
                            and type(record.get('files')) is dict and 'graph' in record['files']
                            and record['files']['graph'].get('name') == 'graph.sqlite3'
                            and type(record.get('metadata')) is dict
                            and all(path.is_file() and not path.is_symlink() for path in child.iterdir())
                            and set(path.name for path in child.iterdir()) <= {'graph.sqlite3','content.sqlite3','recovery.json'}):
                        copies.add(child)
    return copies



def _clean_installer_pending(parent, report):
    # Only the exact stage format emitted by this owner is eligible. Never
    # follow links or delete unknown contents belonging to someone else.
    import re
    for path in parent.glob('*-pending'):
        if (not re.fullmatch(r'[A-Za-z0-9._-]{1,128}-[a-f0-9]{32}-pending', path.name)
                or path.is_symlink() or path.is_junction() or not path.is_dir()):
            continue
        entries = list(path.iterdir())
        if all(child.is_file() and not child.is_symlink() and child.name in {
                'authority.sqlite3', 'archhub-test.universal.sqlite3',
                'node-native-wip.json.gz.universal.sqlite3', 'closed-files.json',
                'authority.sqlite3.conversations.sqlite3', 'archhub-test.universal.sqlite3.conversations.sqlite3',
                'node-native-wip.json.gz.universal.sqlite3.conversations.sqlite3'} for child in entries):
            shutil.rmtree(path)
            report('Removed incomplete installer backup: ' + str(path))


@contextmanager
def _installer_backup_lease(profile):
    """Serialize Setup custody so crash cleanup cannot erase an active copy."""
    if os.name != 'nt':
        yield
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create.restype = wintypes.HANDLE
    identity = hashlib.sha256(str(Path(profile).resolve()).casefold().encode('utf-8')).hexdigest()
    handle = create(None, False, 'Local\\ArchHubInstallerBackup-' + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    wait = kernel.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    release = kernel.ReleaseMutex
    release.argtypes = (wintypes.HANDLE,)
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    admitted = False
    try:
        admitted = wait(handle, 0) in (0, 128)
        if not admitted:
            raise OSError('Another Setup is preserving this profile; no backup or incomplete stage was changed')
        yield
    finally:
        if admitted:
            release(handle)
        close(handle)


def preserve_closed_application_journals(profile, build, *, keep_count=3, max_bytes=10 * 1024**3,
                                        progress=None):
    with _installer_backup_lease(profile):
        return _preserve_closed_application_journals(profile, build, keep_count=keep_count,
                                                    max_bytes=max_bytes, progress=progress)


def _preserve_closed_application_journals(profile, build, *, keep_count=3, max_bytes=10 * 1024**3,
                                        progress=None):
    """Installer-only, before replacing files: retain verified pre-upgrade bytes.

    The caller closes ArchHub first. An exclusive SQLite lease and byte readback
    fence the copy; a hot WAL/journal or busy owner refuses the upgrade. Completed
    Identical bytes reuse verified custody before reserving copy space. Only the
    latest pre-ADOPT copy is pinned; later copies use the common retention owner.
    Setup extracts this stdlib-only module and backup_retention before installing.
    """
    import re
    report = progress if progress is not None else lambda message: None
    report('Selecting closed journals')
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
    scores = {path: (_closed_source_score(path, selected, exact=True)
        if bounds[path][0] <= 1 < bounds[path][1] else bounds[path]) for path in candidates}
    primary = max(candidates, key=lambda path: (scores[path][0] > 1, scores[path][2], scores[path][3]))
    # Authoritative work receives custody first; a later empty compatibility
    # journal can neither steal its pin nor win merely by being newer.
    candidates.sort(key=lambda path: path != primary)
    completed = []
    written = False
    all_protected = set()
    total_planned = sum(path.stat().st_size + (Path(str(path) + '.conversations.sqlite3').stat().st_size
        if Path(str(path) + '.conversations.sqlite3').is_file() else 0) + _METADATA_BYTES for path in candidates)
    # A previous auto preference may itself point into a sync drive. Do not
    # create, inspect custody, or reconcile pending copies there.
    if not _local_backup_path(Path(backup_location(profile)['directory'])):
        _select_backup_location(profile, total_planned)
    retention = importlib.import_module((__package__ + '.' if __package__ else '') + 'backup_retention')
    for source in candidates:
        if not source.is_file():
            raise ValueError('closed journal changed after backup selection; saved work was kept')
        if source.is_symlink() or source.is_junction() or source.resolve() != source.absolute():
            raise ValueError('closed-backup journal is a link')
        paths = [source]
        content = Path(str(source) + '.conversations.sqlite3')
        if content.is_file():
            paths.append(content)
        planned_bytes = sum(path.stat().st_size for path in paths) + _METADATA_BYTES
        parent = installer_backup_directory(profile, source)
        for ancestor in (parent, *parent.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ValueError('closed-backup directory contains a link')
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('closed-backup directory is a link')
        from contextlib import ExitStack
        custody_parents = {parent, *(path.parent for path in _installer_copies(profile,
                                      Path(backup_location(profile)['directory'])))}
        for state in dict.fromkeys((root, profile / 'ArchHub-Test', source.parent)):
            for custody_parent in custody_parents:
                all_protected.update(custody_parent / name for name in
                    retention.protected_update_backups(state, custody_parent, strict_directory=False))
        with ExitStack() as leases:
            graph_database = None
            for path in paths:
                if path.is_symlink() or path.is_junction() or any(
                        Path(str(path) + suffix).exists() for suffix in ('-wal', '-journal')):
                    raise ValueError('close ArchHub before preserving its pre-upgrade journal')
                db = leases.enter_context(_closed_source_lease(path))
                if path == source:
                    graph_database = db
            _clean_installer_pending(parent, report)
            report('Hashing closed journal: ' + source.name)
            records = [_closed_file_record(path) for path in paths]
            receipts = _closed_receipts(parent)
            latest = next(((path, record) for path, record in receipts if any(
                item['name'] == source.name for item in record['files'])), None)
            if latest is not None:
                _verify_closed_receipt(*latest)
            adopted = Path(str(source) + '.adoption.json').exists()
            pinned = next((path for path, record in receipts
                           if record.get('retain_until_user_deletes') is True and any(
                               item['name'] == primary.name for item in record['files'])), None) if parent == installer_backup_directory(profile, primary) else None
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
                report('Reusing verified installer backup: ' + destination.name)
            else:
                # 0400's mandatory final-close custody stays protected until
                # disarmed, outside the ordinary rotating budget. Existing bytes
                # already reduce real disk free space; reserve checks stay exact.
                required_bytes = total_planned
                if required_bytes > max_bytes:
                    raise ValueError('Installer backup over budget: %d required bytes exceeds %d bytes; saved work was kept'
                                     % (required_bytes, max_bytes))
                preference = _select_backup_location(profile, total_planned)
                parent = installer_backup_directory(profile, source)
                parent.mkdir(parents=True, exist_ok=True)
                report('Installer backup location: ' + preference['directory'])
                free = shutil.disk_usage(parent).free
                reserve = _install_reserve(profile, parent)
                if free - planned_bytes < reserve:
                    raise OSError('Installer backup over budget: %d bytes free minus %d planned bytes must leave %d bytes (25 GiB on system disk); saved work was kept'
                                  % (free, planned_bytes, reserve))
                _require_disk_reserve(parent, sum(item['bytes'] for item in records))
                stage = parent / (build + '-' + uuid.uuid4().hex + '-pending')
                stage.mkdir()
                owned_paths = []
                try:
                    for path in paths:
                        destination = stage / path.name
                        report('Copying ' + path.name)
                        owned_paths.append(destination)
                        _copy_closed_file(path, destination, report)
                    receipt = dict(kind='closed-file-preservation', runtime=uuid.uuid4().hex,
                        build=build, producer='archhub-product-installer/v1',
                        source_relative_path=source.relative_to(profile).as_posix(),
                        retain_until_user_deletes=not adopted and source == primary, files=records,
                        journal_identity=journal_identity)
                    report('Verifying installer backup: ' + source.name)
                    _verify_closed_receipt(stage, receipt)
                    with (stage / 'closed-files.json').open('x', encoding='utf-8') as writer:
                        owned_paths.append(stage / 'closed-files.json')
                        json.dump(receipt, writer, sort_keys=True)
                        writer.flush()
                        os.fsync(writer.fileno())
                    destination = stage.with_name(stage.name.removesuffix('-pending') + '-closed')
                    os.rename(stage, destination)
                    written = True
                except BaseException as error:
                    _cleanup_stage(stage, parent, owned_paths, error)
                    raise
            if pinned is not None or (not adopted and source == primary):
                pinned = destination
            for path, record in _closed_receipts(parent):
                _set_closed_pin(path, record, path == pinned)
            completed.append(str(destination))
    if written:
        container = Path(backup_location(profile)['directory'])
        if all_protected:
            report('Preserving armed recovery outside rotating budget: %d bytes' %
                   sum(retention._backup_bytes(path) for path in all_protected if path.is_dir()))
        # All copy/budget admission has passed and every replacement is verified
        # before an older copy (including 0400's legacy folders) can be removed.
        if shutil.disk_usage(container).free < _install_reserve(profile, container):
            raise OSError('Installer backup over budget: insufficient reserve remains after backup (25 GiB on system disk); saved work and verified copies were kept')
        retained = retention.prune_backups(container, keep=Path(completed[-1]),
            keep_count=keep_count, max_bytes=max_bytes,
            owned_candidates=_installer_copies(profile, container),
            verified_paths=completed, protected_paths=all_protected)
        for removed in retained['removed']:
            report('Removed older installer-owned backup: ' + removed)
        if retained['budget_exceeded']:
            raise ValueError('Installer backup over budget: required verified custody exceeds its configured byte budget')
    report('Complete: installer journal backup verified')
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


def preserve_open_application_journal(root, source, snapshot, *, progress):
    """Reuse the recovery publisher for a bounded WAL-aware boot snapshot.

    Rollback custody is desirable, never a prerequisite to opening saved work.
    Large/busy/over-budget sources open in place with a boot warning instead.
    The installer's location and byte policy remain the single backup owner.
    """
    from .backup_retention import _backup_bytes, backup_policy
    root, source = Path(root).resolve(), Path(source).resolve()
    profile = Path(os.environ.get('LOCALAPPDATA', root.parent)).resolve()
    deadline = time.monotonic() + 2.0
    try:
        policy = backup_policy(snapshot)
        with ExitStack() as stack:
            paths = {'graph': source}
            content = Path(str(source) + '.conversations.sqlite3')
            if content.is_file():
                paths['content'] = content
            sources = {}
            for role, path in paths.items():
                connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                    timeout=max(0, deadline-time.monotonic()))
                sources[role] = stack.enter_context(closing(connection))
            size = sum(max(paths[role].stat().st_size, db.execute('PRAGMA page_count').fetchone()[0] *
                db.execute('PRAGMA page_size').fetchone()[0]) for role, db in sources.items())
            # Do not start multi-GB copy/hash work on the path to Studio.
            if size > 64 * 1024**2:
                raise TimeoutError('rollback snapshot deferred for a large saved graph')
            location = _select_backup_location(profile, size)
            parent = Path(location['directory'])
            parent.mkdir(parents=True, exist_ok=True)
            inventory = _installer_copies(profile, parent)
            available = policy['max_bytes'] - sum(_backup_bytes(path) for path in inventory)
            if len(inventory) >= policy['keep_count']:
                raise ValueError('rollback snapshot would exceed the configured retained backup count')
            if size + _MANIFEST_BYTES > available or shutil.disk_usage(parent).free - size < _install_reserve(profile, parent):
                raise ValueError('rollback snapshot exceeds the configured backup budget or disk reserve')
            def verify(copies, check):
                check()
                return {'kind': 'boot-snapshot', 'source': str(source)}
            return publish_application_recovery(sources, parent / ('boot-' + uuid.uuid4().hex),
                verify_copies=verify, before_publish=lambda: None, deadline=deadline, max_bytes=available)
    except (OSError, ValueError, sqlite3.Error, TimeoutError) as error:
        message = 'Your saved graph is opening without a new rollback backup: ' + str(error)
        _advance(progress, message)
        return None


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
    try:
        preserve_closed_application_journals(arguments.closed_profile, arguments.build,
                                             progress=lambda message: print(message, flush=True))
    except (OSError, ValueError, sqlite3.Error) as refused:
        print('Setup refused: ' + str(refused), flush=True)
        raise SystemExit(1) from refused
