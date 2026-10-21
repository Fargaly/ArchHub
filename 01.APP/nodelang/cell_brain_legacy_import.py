"""One-way import of the legacy brain's personal memory into the graph.

The legacy personal brain (12.PRODUCTION personal-brain-mcp storage.py) keeps
memory in a SQLite ``fragments`` table. This module reads that table READ-ONLY
and writes each admitted row through ``cell_brain_memory``, so imported memory
obeys the same sync law as any other write and running the import again
changes nothing.

There is deliberately no default path: the caller names the exact file, so a
court can only point this at a copy and a cutover names the file it means. The
file is opened with ``mode=ro``, which reads its write-ahead log without
writing it. There is no default owner either: the caller names which legacy
``owner_user`` maps to which owner root, and every write acts for that owner.

Rows that belong to another owner in the graph -- skills, secret references,
wiring, traces, shared scopes, quarantined rows, text that carries a
credential -- are skipped with a named reason, never guessed into memory. A row
the memory owner refuses is skipped as ``refused``; it never stops the rows
after it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .cell_brain_memory import CONFIDENCES, MEMORY_KINDS, acting_owner, forget, remember
from .cell_brain_secrets import assert_no_credential_in_text, assert_not_a_secret
from .universal_cell import InvalidCell

LEGACY_COLUMNS = (
    "id", "kind", "text", "scope", "owner_user", "confidence", "provenance_json",
    "valid_until", "quarantine_flag", "created_at", "updated_at",
)


@dataclass(frozen=True, slots=True)
class ImportReport:
    imported: int
    forgotten: int
    unchanged: int
    skipped: dict


def read_legacy_fragments(path):
    """The legacy fragments rows, read without writing the file."""
    source = Path(path)
    if not source.is_file():
        raise InvalidCell("no legacy brain file at %s" % source)
    connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'fragments'"
        ).fetchone()
        if table is None:
            raise InvalidCell(
                "%s is not a legacy brain: it has no fragments table" % source.name)
        rows = connection.execute(
            "SELECT %s FROM fragments ORDER BY id" % ", ".join(LEGACY_COLUMNS)
        ).fetchall()
    finally:
        connection.close()
    return tuple(dict(zip(LEGACY_COLUMNS, row)) for row in rows)


def _epoch_ms(stamp):
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        moment = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return round(moment.timestamp() * 1000)


def _row_clock(row):
    """The clock the legacy row already carries.

    A provenance HLC is ``<physical milliseconds>.<random>``; without one the
    row's own updated_at (then created_at) is the clock -- never the import time,
    or an old fact would beat every newer edit on another replica.
    """
    try:
        provenance = json.loads(row.get("provenance_json") or "{}")
    except ValueError:
        provenance = {}
    hlc = provenance.get("hlc") if isinstance(provenance, dict) else None
    if isinstance(hlc, str) and "." in hlc:
        physical = hlc.split(".", 1)[0]
        if physical.isdigit():
            return int(physical)
    return _epoch_ms(row.get("updated_at")) or _epoch_ms(row.get("created_at"))


def _skip_reason(row, owner_user):
    if row.get("scope") != "user":
        return "scope:%s" % row.get("scope")
    if row.get("owner_user") != owner_user:
        return "other-owner"
    if row.get("quarantine_flag"):
        return "quarantined"
    if row.get("kind") not in MEMORY_KINDS:
        return "kind:%s" % row.get("kind")
    text = row.get("text")
    if not isinstance(text, str) or not text.strip():
        return "empty"
    try:
        assert_not_a_secret(text, "legacy memory text")
        assert_no_credential_in_text(text, "legacy memory text")
    except InvalidCell:
        return "looks-like-a-secret"
    if row.get("confidence") not in CONFIDENCES:
        return "confidence:%s" % row.get("confidence")
    if _row_clock(row) is None:
        return "no-clock"
    return None


def import_legacy_fragments(store, rows, *, session_root, owner_user, origin):
    """Bring the session owner's personal legacy memory into the graph.

    The owner is the one the session acts for; ``owner_user`` only says which
    legacy account's rows are that owner's.
    """
    acting_owner(store.snapshot(), session_root)
    imported = forgotten = unchanged = 0
    skipped = {}
    for row in rows:
        reason = _skip_reason(row, owner_user)
        if reason is not None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        clock = _row_clock(row)
        before = store.snapshot().revision
        was_forgotten = bool(row.get("valid_until"))
        try:
            remember(
                store,
                session_root=session_root,
                fragment_id=row["id"],
                text=row["text"],
                kind=row["kind"],
                origin=origin,
                clock=clock,
                confidence=row["confidence"],
            )
            if was_forgotten:
                until = _epoch_ms(row["valid_until"])
                forget_clock = until if until is not None and until > clock else clock + 1
                forget(store, session_root=session_root, fragment_id=row["id"],
                       origin=origin, clock=forget_clock)
        except InvalidCell:
            skipped["refused"] = skipped.get("refused", 0) + 1
            continue
        if store.snapshot().revision == before:
            unchanged += 1
        else:
            imported += 1
            forgotten += int(was_forgotten)
    return ImportReport(imported, forgotten, unchanged, skipped)
