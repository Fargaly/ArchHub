"""One retention policy for graph recovery: recent count plus disk budget."""
from __future__ import annotations

import re
import shutil
import json
from datetime import date
from pathlib import Path

_DATE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def backup_date(name: str) -> date | None:
    """The first valid YYYYMMDD date in a backup folder name, or None."""
    for match in _DATE.finditer(str(name)):
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
    return None


def backup_name_stamp(today: date | None = None) -> str:
    """The date a new backup's folder name carries."""
    return (today or date.today()).strftime("%Y%m%d")


def _backup_bytes(path):
    """Count physical files without traversing links or Windows junctions."""
    total = 0
    for child in path.iterdir():
        if child.is_symlink() or child.is_junction():
            continue
        total += _backup_bytes(child) if child.is_dir() else child.stat().st_size
    return total


def prune_backups(directory, *, keep, keep_count=3, max_bytes=10 * 1024**3,
                  protected_names=(), today=None, remove=shutil.rmtree,
                  owned_candidates=None, verified_paths=(), protected_paths=()):
    """One count/byte policy, including installer-adopted0400 directories.

    Cross-container custody is inventoried by the installer owner. No removal
    occurs until a newer verified copy exists and required custody fits budget.
    Explicit installer protected_paths are armed recovery, exempt from the
    rotating byte budget until disarmed. Their actual bytes remain reported.
    """
    if type(keep_count) is not int or keep_count < 1:
        raise ValueError('backup count must be a positive integer')
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('backup budget must be a positive integer')
    directory = Path(directory).resolve()
    selected = Path(keep)
    if selected.is_symlink() or selected.is_junction():
        raise ValueError('verified backup must not be a link')
    keep = selected.resolve()
    scoped = owned_candidates is not None
    inventory = list(owned_candidates) if scoped else list(directory.iterdir())
    if not keep.is_dir() or (keep not in inventory if scoped else keep.parent != directory):
        raise ValueError('the new verified backup must be a folder inside the backup directory')
    closed = {}
    for path in inventory:
        receipt = path / 'closed-files.json'
        if (path.is_symlink() or path.is_junction() or not receipt.is_file()
                or receipt.is_symlink() or receipt.stat().st_size > 65536):
            continue
        record = json.loads(receipt.read_text(encoding='utf-8'))
        if record.get('kind') == 'closed-file-preservation':
            closed[path] = record
    candidates = [path for path in inventory if path.is_dir() and not path.is_symlink()
                  and not path.is_junction() and not path.name.startswith('.')
                  and not path.name.endswith('-pending')
                  and (any((path / name).is_file() and not (path / name).is_symlink()
                           for name in ('graph.sqlite3', 'authority.sqlite3'))
                       or path in closed)]
    if keep not in candidates:
        raise ValueError('verified backup has no owned graph snapshot')
    protected = {keep, *map(Path, verified_paths), *map(Path, protected_paths)}
    protected.update(path for path in candidates if path.name.casefold() in
                     {str(name).casefold() for name in protected_names})
    if not scoped:
        pins = [path for path, record in closed.items() if record.get('retain_until_user_deletes') is True]
        if pins:
            protected.add(max(pins, key=lambda path: (path.stat().st_mtime_ns, path.name)))
    candidates.sort(key=lambda path: (path.stat().st_mtime_ns,
        (backup_date(path.name) or date.min).toordinal(), path.name), reverse=True)
    sizes = {path: _backup_bytes(path) for path in candidates}
    retained = protected.intersection(candidates)
    exempt = set(map(Path, protected_paths)).intersection(protected)
    total = sum(sizes[path] for path in retained if path not in exempt)
    # Refusal cannot prune the older recovery that the failed update needs.
    refused = total > max_bytes
    if refused:
        retained = set(candidates)
        total = sum(size for path, size in sizes.items() if path not in exempt)
    else:
        for path in candidates:
            if path not in retained and len(retained) < keep_count and total + sizes[path] <= max_bytes:
                retained.add(path)
                total += sizes[path]
    removed = []
    for path in reversed(candidates):
        if path not in retained:
            if path.is_symlink() or path.is_junction() or (path not in inventory if scoped else path.resolve().parent != directory):
                raise ValueError('backup target changed during retention')
            remove(path)
            removed.append(str(path) if scoped else path.name)
    names = sorted(path.name for path in retained)
    return {'removed': removed, 'kept': names,
            'retained_bytes': sum(sizes[path] for path in retained), 'budgeted_bytes': total,
            'budget_exceeded': refused or total > max_bytes, 'kept_from': None,
            'undated_kept': sorted(name for name in names if backup_date(name) is None)}


def backup_policy(snapshot, registry=None):
    """Read the same graph parameters Settings edits; defaults create no Cells."""
    from .universal_application import _workshop_board_int_param, _APPLICATION_SETTING_SPECS, _application_setting_default
    if registry is None and 'app:archhub' in snapshot.cells:
        from types import SimpleNamespace
        from .universal_map_import import project_grand_map_cells
        roles = dict(project_grand_map_cells(snapshot, lazy=True).roles)
        roles['property'] = 'app:role:property'
        registry = SimpleNamespace(canvas_root='app:canvas', roles=roles)
    count_bounds = _APPLICATION_SETTING_SPECS['backup_count'][1]
    byte_bounds = _APPLICATION_SETTING_SPECS['backup_budget_bytes'][1]
    return {
        'keep_count': _workshop_board_int_param(snapshot, registry, 'backup_count',
            default=_application_setting_default('backup_count'),
            lower=count_bounds['min'], upper=count_bounds['max']),
        'max_bytes': _workshop_board_int_param(snapshot, registry, 'backup_budget_bytes',
            default=_application_setting_default('backup_budget_bytes'),
            lower=byte_bounds['min'], upper=byte_bounds['max']),
    }


def protected_update_backups(state_directory, backup_directory, *, strict_directory=True):
    """An armed update keeps its exact final-close recovery until disarmed."""
    marker = Path(state_directory) / 'updates' / 'update-ready.json'
    if not marker.exists():
        return ()
    if marker.is_symlink() or marker.is_junction() or marker.stat().st_size > 4 * 1024**2:
        raise ValueError('update recovery marker is not a bounded plain file')
    receipt = json.loads(marker.read_text(encoding='utf-8'))
    if receipt.get('format') == 2:
        if (type(receipt['format']) is not int or receipt.get('recovery') != {
                'owner': 'archhub-product-installer/v1', 'state': 'required-before-copy'}):
            raise ValueError('installer-only update custody marker is invalid')
        return ()
    if 'format' in receipt and (type(receipt['format']) is not int or receipt['format'] != 1):
        raise ValueError('update custody marker format is invalid')
    recovery = Path(receipt['recovery']['path']).resolve()
    if recovery.parent != Path(backup_directory).resolve():
        if not strict_directory:
            return ()
        raise ValueError('armed update recovery is outside this backup directory')
    return (recovery.name,)


def protected_backup_bytes(state_directory, backup_directory):
    """Reserve existing armed recovery bytes before admitting another copy."""
    directory = Path(backup_directory).resolve()
    total = 0
    for name in protected_update_backups(state_directory, directory):
        protected = directory / name
        if protected.is_symlink() or protected.is_junction() or not protected.is_dir():
            raise ValueError('armed recovery backup is not a plain directory')
        total += _backup_bytes(protected)
    return total
