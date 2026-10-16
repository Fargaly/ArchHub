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
                  protected_names=(), today=None, remove=shutil.rmtree):
    """Keep the newest N verified recovery directories within a byte budget.

    The owner supplies the newly verified backup and any armed-update names.
    Links, junctions, staging and unrelated files are never traversed or removed.
    Protected backups win over limits; an unsatisfied budget is explicit.
    """
    if type(keep_count) is not int or keep_count < 1:
        raise ValueError("backup count must be a positive integer")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("backup budget must be a positive integer")
    directory = Path(directory).resolve()
    selected = Path(keep)
    if selected.is_symlink() or selected.is_junction():
        raise ValueError("verified backup must not be a link")
    keep = selected.resolve()
    if not keep.is_dir() or keep.parent != directory:
        raise ValueError("the new verified backup must be a folder inside the backup directory")
    protected = {keep.name.casefold(), *(str(n).casefold() for n in protected_names)}
    candidates = [p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
                  and not p.is_junction() and not p.name.startswith('.')
                  and any((p / name).is_file() and not (p / name).is_symlink()
                          for name in ('graph.sqlite3', 'authority.sqlite3'))]
    if keep not in candidates:
        raise ValueError('verified backup has no owned graph snapshot')
    candidates.sort(key=lambda p: (p.stat().st_mtime_ns,
        (backup_date(p.name) or date.min).toordinal(), p.name), reverse=True)
    sizes = {p.name: _backup_bytes(p) for p in candidates}
    retained = set(p.name for p in candidates if p.name.casefold() in protected)
    available = max(0, keep_count - len(retained))
    retained.update(p.name for p in [p for p in candidates if p.name not in retained][:available])
    total = sum(sizes[n] for n in retained)
    for path in reversed(candidates):
        if total <= max_bytes:
            break
        if path.name in retained and path.name.casefold() not in protected:
            retained.remove(path.name)
            total -= sizes[path.name]
    removed = []
    for path in reversed(candidates):
        if path.name not in retained:
            # Revalidate the literal target after inventory, including junctions.
            if path.is_symlink() or path.is_junction() or path.resolve().parent != directory:
                raise ValueError("backup target changed during retention")
            remove(path)
            removed.append(path.name)
    return {"removed": removed, "kept": sorted(retained), "retained_bytes": total,
            "budget_exceeded": total > max_bytes,
            "kept_from": None,
            "undated_kept": sorted(n for n in retained if backup_date(n) is None)}


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


def protected_update_backups(state_directory, backup_directory):
    """An armed update keeps its exact final-close recovery until disarmed."""
    marker = Path(state_directory) / 'updates' / 'update-ready.json'
    if not marker.exists():
        return ()
    if marker.is_symlink() or marker.is_junction() or marker.stat().st_size > 4 * 1024**2:
        raise ValueError('update recovery marker is not a bounded plain file')
    receipt = json.loads(marker.read_text(encoding='utf-8'))
    recovery = Path(receipt['recovery']['path']).resolve()
    if recovery.parent != Path(backup_directory).resolve():
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
