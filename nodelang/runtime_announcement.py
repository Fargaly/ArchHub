"""The machine's active-runtime announcement, written by the runtime that owns it.

The desktop launcher's runtime writes its signed descriptor next to its graph
(the owner record) and copies it to %LOCALAPPDATA%/ArchHub/active-universal-
runtime.json so the brain, BABOOM and governed agents find the live graph.

That copy used to be put BACK to whatever was there before the launch when the
launch exited: an older descriptor still saying "active" with a long-dead
process id. Every clean exit resurrected a stale owner. Now an exit writes this
runtime's own final record (its owner record says "stopped") over the
announcement if, and only if, the announcement still names this runtime; if
another runtime has been announced since, it is left alone. Nothing older is
ever restored.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _runtime_id(raw: bytes) -> str | None:
    try:
        value = json.loads(raw.decode("utf-8")).get("runtime_id")
    except (UnicodeError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class Announcement:
    """What this launch announced: where, and which runtime."""

    path: Path
    owner_record: Path
    runtime_id: str


def announce(path: str | os.PathLike[str], owner_record: str | os.PathLike[str]) -> Announcement:
    """Copy this runtime's owner record to the machine announcement."""
    target, source = Path(path), Path(owner_record)
    raw = source.read_bytes()
    runtime_id = _runtime_id(raw)
    if runtime_id is None:
        raise ValueError("the owner record names no runtime")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp-%d" % os.getpid())
    temporary.write_bytes(raw)
    os.replace(temporary, target)
    return Announcement(target, source, runtime_id)


def release(announcement: Announcement) -> str:
    """At exit: the announcement follows this runtime's own final record.

    Returns what happened: "released" (this runtime's final record now stands
    in the announcement), "left" (another runtime was announced since, or the
    announcement is gone), never a restore of an older record.
    """
    try:
        current = announcement.path.read_bytes()
    except FileNotFoundError:
        return "left"
    if _runtime_id(current) != announcement.runtime_id:
        return "left"
    final = announcement.owner_record.read_bytes()
    if _runtime_id(final) != announcement.runtime_id:
        # The owner record was taken over by another runtime of the same graph;
        # its announcement is that runtime's to make.
        return "left"
    temporary = announcement.path.with_name(announcement.path.name + ".tmp-%d" % os.getpid())
    temporary.write_bytes(final)
    os.replace(temporary, announcement.path)
    return "released"


__all__ = ["Announcement", "announce", "release"]
