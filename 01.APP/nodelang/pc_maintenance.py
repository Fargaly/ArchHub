"""Settings > This PC maintenance: back up now, keep logs for N days, export diagnostics.

Stdlib only. Every write is atomic (temp file in the target folder, then os.replace).
Deletes only touch files this module owns: archhub-backup-*.zip in the backup folder,
and rotated logs under <state>/logs.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import string
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BACKUP_GLOB = 'archhub-backup-*.zip'
_GB = 1024 ** 3
DRIVE_LETTERS = string.ascii_uppercase
_PRIVATE_NAME = ('secret', 'credential', 'token')
_ACTIVE_LOGS = {'launcher.log', 'updates.log'}
_ROTATED = re.compile(r'\.log\.\d+$', re.IGNORECASE)
_LOG_TAIL_BYTES = 2 * 1024 * 1024
_TOKEN_PATTERNS = [re.compile(p) for p in (
    r'sk-[A-Za-z0-9_-]{16,}',
    r'ghp_[A-Za-z0-9]{20,}',
    r'Bearer\s+\S+',
    r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+',
)]


def _state(state_dir):
    from .user_paths import state_directory
    return Path(state_dir) if state_dir is not None else state_directory()


def _setting(state_dir, key) -> int:
    from .application_update import saved_application_settings
    from .settings_owner import _application_setting_default
    return saved_application_settings(state_dir).get(key, _application_setting_default(key))


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _atomic_zip(target: Path, fill) -> int:
    """Write a zip with fill(zf) to target atomically; a failed write leaves no partial file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.archhub-', suffix='.tmp', dir=target.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as zf:
            fill(zf)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return target.stat().st_size


def backup_destination(backup_to, backup_dir=None, environ=os.environ, state_dir=None) -> Path:
    """The folder a backup goes to, for the 'Back up to' and 'Backup folder' rows."""
    if backup_to == 'This PC':
        return Path(backup_dir) if backup_dir else _state(state_dir) / 'Backups'
    if backup_to == 'OneDrive':
        root = environ.get('OneDrive')
        if not root or not Path(root).is_dir():
            raise ValueError('OneDrive is not set up on this PC. Sign in to OneDrive or pick another place.')
        return Path(root) / 'ArchHub Backups'
    if backup_to == 'Google Drive':
        for letter in DRIVE_LETTERS:
            root = Path(f'{letter}:\\My Drive')
            if root.is_dir():
                return root / 'ArchHub Backups'
        raise ValueError('Google Drive is not set up on this PC. Install Google Drive for desktop or pick another place.')
    if backup_to == 'Office server':
        if not backup_dir or not Path(backup_dir).is_dir():
            raise ValueError('The office server folder cannot be reached. Pick a backup folder that exists.')
        return Path(backup_dir)
    raise ValueError(f'"{backup_to}" is not a backup place. Pick This PC, OneDrive, Google Drive or Office server.')


def back_up_now(state_dir, sessions_dir, destination) -> dict:
    """One zip of the settings files and the session files, then prune old backups by count and space."""
    state, sessions, dest = Path(state_dir), Path(sessions_dir), Path(destination)
    settings = sorted(p for p in (state / 'settings').glob('*.json')
                      if p.is_file() and not any(word in p.name.casefold() for word in _PRIVATE_NAME))
    documents = sorted(p for pattern in ('*.archhub', '*/*.archhub') for p in sessions.glob(pattern) if p.is_file())

    def fill(zf):
        for path in settings:
            zf.write(path, 'settings/' + path.name)
        for path in documents:
            zf.write(path, 'sessions/' + path.relative_to(sessions).as_posix())

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    target = dest / f'archhub-backup-{stamp}.zip'
    size = _atomic_zip(target, fill)

    count = _setting(state, 'backup_count')
    budget = _setting(state, 'backup_budget_bytes')
    backups = sorted((p for p in dest.glob(BACKUP_GLOB) if p.is_file() and not _is_link(p)),
                     key=lambda p: p.name, reverse=True)  # name carries the UTC stamp: newest first
    kept = [target] + [p for p in backups if p != target]
    removed = kept[count:]
    kept = kept[:count]
    while len(kept) > 1 and sum(p.stat().st_size for p in kept) > budget:
        removed.append(kept.pop())
    for path in removed:
        path.unlink(missing_ok=True)
    return {'path': str(target), 'bytes': size, 'kept': len(kept), 'removed': [p.name for p in removed]}


def prune_logs(state_dir, days, now=None) -> list:
    """Delete rotated logs (*.log.N anywhere, *.log under logs/root) older than days. Active logs stay."""
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('Keep logs for must be between 1 and 90 days.')
    logs = Path(state_dir) / 'logs'
    if not logs.is_dir() or _is_link(logs):
        return []
    cutoff = (time.time() if now is None else now) - days * 86400
    root_history = logs / 'root'
    removed = []
    for folder, dirs, files in os.walk(logs):
        dirs[:] = [d for d in dirs if not _is_link(Path(folder) / d)]
        for name in files:
            path = Path(folder) / name
            if name.casefold() in _ACTIVE_LOGS or _is_link(path):
                continue
            rotated = _ROTATED.search(name) or (Path(folder) == root_history and name.casefold().endswith('.log'))
            if rotated and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed.append(path.relative_to(logs).as_posix())
    return removed


def prune_cache(state_dir, limit_gb) -> list:
    """Settings › This PC › Cache size: oldest files in <state>/cache go first above the limit (a cache is disposable)."""
    if type(limit_gb) is not int or not 1 <= limit_gb <= 32:
        raise ValueError('Choose a cache size from 1 to 32 GB.')
    root = _state(state_dir) / 'cache'
    if not root.is_dir() or _is_link(root):
        return []
    files = sorted((p for p in root.rglob('*') if p.is_file() and not _is_link(p)), key=lambda p: p.stat().st_mtime)
    total, removed = sum(p.stat().st_size for p in files), []
    for path in files:
        if total <= limit_gb * _GB:
            break
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
        removed.append(path.relative_to(root).as_posix())
    return removed


def _redact(text: str) -> str:
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub('[redacted]', text)
    return text


def export_diagnostics(state_dir, destination_file) -> dict:
    """One zip: redacted log tails plus health.json (no keys, no settings values)."""
    state, target = Path(state_dir), Path(destination_file)
    logs = state / 'logs'
    files = []
    if logs.is_dir() and not _is_link(logs):
        for folder, dirs, names in os.walk(logs):
            dirs[:] = [d for d in dirs if not _is_link(Path(folder) / d)]
            files += [Path(folder) / n for n in names if '.log' in n.casefold() and not _is_link(Path(folder) / n)]
    build = next((p.read_text(encoding='utf-8', errors='replace').strip()
                  for p in (state.parent / 'BUILD_ID', state / 'BUILD_ID') if p.is_file()), None)
    settings_keys = {}
    for path in sorted((state / 'settings').glob('*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            settings_keys[path.name] = sorted(data)
    health = {'platform': platform.platform(), 'python': sys.version, 'build_id': build,
              'disk_free_bytes': shutil.disk_usage(state).free, 'settings_keys': settings_keys}
    written = []

    def fill(zf):
        for path in sorted(files):
            with path.open('rb') as handle:
                handle.seek(max(0, path.stat().st_size - _LOG_TAIL_BYTES))
                text = handle.read().decode('utf-8', errors='replace')
            name = 'logs/' + path.relative_to(logs).as_posix()
            zf.writestr(name, _redact(text))
            written.append(name)
        zf.writestr('health.json', json.dumps(health, indent=2))
        written.append('health.json')

    size = _atomic_zip(target, fill)
    return {'path': str(target), 'bytes': size, 'files': written}
