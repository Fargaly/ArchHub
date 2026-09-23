"""Keep graph backups for the last three days (founder, 2026-09-23).

Recovery copies of a 6.7 GB graph piled up to 220 GB. After a NEW backup has
been written and verified, the other backups in the same directory are
deleted when the date in their folder name is before the last three days
(today and the two days before it). Age is read from the folder name
(YYYYMMDD), never from file times: a reboot touched every folder's
modification time to the same minute. A folder whose name carries no date is
kept and reported, never guessed at. The new backup, anything an armed update
names, staging folders (leading dot) and plain files are never deleted.
"""
from __future__ import annotations

import re
import shutil
from datetime import date, timedelta
from pathlib import Path

KEEP_DAYS = 3
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


def prune_backups(directory, *, keep, today: date | None = None, keep_days: int = KEEP_DAYS,
                  protected_names=(), remove=shutil.rmtree) -> dict:
    """Delete dated backup folders older than the last ``keep_days`` days.

    ``keep`` is the backup just written and verified; it must be a directory
    inside ``directory``. Nothing is deleted without it.
    """
    if int(keep_days) < 1:
        raise ValueError("backup retention keeps at least one day")
    directory = Path(directory).resolve()
    keep = Path(keep).resolve()
    if not keep.is_dir() or keep.parent != directory:
        raise ValueError("the new verified backup must be a folder inside the backup directory")
    first_kept_day = (today or date.today()) - timedelta(days=int(keep_days) - 1)
    protected = {keep.name.casefold(), *(str(name).casefold() for name in protected_names)}
    removed, kept, undated = [], [], []
    for entry in sorted(directory.iterdir(), key=lambda path: path.name):
        if entry.name.casefold() in protected or entry.name.startswith("."):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        when = backup_date(entry.name)
        if when is None:
            undated.append(entry.name)
        elif when < first_kept_day:
            remove(entry)
            removed.append(entry.name)
        else:
            kept.append(entry.name)
    return {"kept_from": first_kept_day.isoformat(), "new": keep.name, "removed": removed,
            "kept": kept, "undated_kept": undated}
