"""Atomic pending content publication beneath the existing application owner.

This operation never commits a graph patch, transfers a handle, or authorizes
activation. The caller owns its history handle and must hold owner/broker guards
before entry. Its trusted admission callback must not acquire those guards in
reverse order from inside the graph/history locks held here.
"""
import os
import sqlite3
import time

from .conversation_content import read_content_binding, read_content_space
from .conversation_history import validate_message_fields
from .conversation_migration import (
    _check_time, _deadline, _encoded, _reconcile_database, _reconcile_history,
    _source_matches, _verify_stage_owner,
)
from .conversation_migration_binding import _controls
from .universal_cell import overlay_read_snapshot


_RECEIPT_COLUMNS = (
    "conversation_id", "application_root", "instance_id", "binding_root",
    "manifest_digest", "stage_id", "source_authority", "source_revision",
    "source_digest", "imported_count",
)


def _receipt(importing, prepared, snapshot):
    header, patch = importing.header, prepared.patch
    expected = (header["source_authority"], header["source_digest"],
        importing.ticket.manifest_digest, header["source_revision"])
    actual = (prepared.source_authority, prepared.source_digest,
        prepared.manifest_digest, patch.expected_revision)
    if actual != expected:
        raise ValueError("migration publication prepared source mismatch")
    candidate = overlay_read_snapshot(snapshot, create=patch.create, replace=patch.replace)
    binding = read_content_binding(candidate, importing.protocol,
        application_root=header["application_root"], space_root=header["space_root"])
    if binding != patch.binding or binding.instance_id != header["instance_id"]:
        raise ValueError("migration publication prepared binding mismatch")
    controls = dict(header["controls"])
    controls.pop("content_store_root")
    space = read_content_space(candidate, importing.protocol, header["space_root"])
    if _encoded(_controls(space)) != _encoded(controls):
        raise ValueError("migration publication prepared controls mismatch")
    stage = importing._history._db.execute(
        "SELECT stage_id FROM migration_staging WHERE singleton=1").fetchone()
    if stage is None or stage[0] != prepared.stage_id:
        raise ValueError("migration publication stage ownership mismatch")
    return dict(conversation_id=header["space_root"], application_root=header["application_root"],
        instance_id=header["instance_id"], binding_root=binding.root_id,
        manifest_digest=prepared.manifest_digest, stage_id=prepared.stage_id,
        source_authority=prepared.source_authority, source_revision=patch.expected_revision,
        source_digest=prepared.source_digest, imported_count=importing.total)


def _require_instance(history, instance_id):
    row = history._db.execute("SELECT instance_id FROM history_identity WHERE singleton=1").fetchone()
    if history.instance_id != instance_id or row is None or row[0] != instance_id:
        raise ValueError("migration publication destination instance mismatch")


def _database_path(history):
    path = next((row["file"] for row in history._db.execute("PRAGMA database_list")
        if row["name"] == "main"), None)
    if not path or not os.path.isfile(path):
        raise ValueError("migration publication requires a durable database")
    return path


def _require_exact_head(history, conversation_id, total):
    if history._head(conversation_id) != total or history._db.execute(
            "SELECT count(*) FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0] != total:
        raise ValueError("migration publication pending conversation count mismatch")


def _row(history, conversation_id, message_id):
    row = history._db.execute("SELECT * FROM messages WHERE conversation_id=? AND id=?",
        (conversation_id, message_id)).fetchone()
    if row is None:
        raise ValueError("migration publication record is missing")
    return history._message(row)


def publish_legacy_conversation(importing, prepared, destination_history, *, before_commit,
                                time_budget_seconds=30):
    """Publish one complete pending conversation and its receipt atomically.

    Support the exact first-stage handle and a separate same-instance database
    with existing conversations. An unowned destination conversation is never
    adopted or overwritten. Only an exact pending receipt and exact records
    admit a retry; a later live tail requires the separate activation/recovery
    path. The result always says pending, and the source graph is unchanged.

    The mandatory callback is trusted in-process admission code, not request
    data. Acquire any owner/broker guards before calling; this helper orders
    graph -> stage -> destination. Destination reservation through a subsequent
    graph commit remains the activation owner's responsibility.
    """
    if not callable(before_commit):
        raise ValueError("migration publication requires an admission guard")
    if importing._closed or importing._failed or importing._history is None:
        raise ValueError("migration publication importer is closed or interrupted")
    if not importing._verified_complete or importing.copied != importing.total:
        raise ValueError("migration publication copy must be complete")
    deadline = _deadline(time_budget_seconds)
    header, stage, target = importing.header, importing._history, destination_history
    same_stage = target is stage

    def admitted_commit():
        _check_time(deadline)
        _source_matches(importing.source, header)
        before_commit()
        _check_time(deadline)

    def within_budget():
        return int(time.monotonic() >= deadline)

    with importing.source.stable_snapshot(expected_revision=header["source_revision"]), stage._lock:
        if stage._db.in_transaction:
            raise ValueError("migration publication stage transaction is already active")
        _check_time(deadline)
        snapshot = _source_matches(importing.source, header)
        before_commit()
        _verify_stage_owner(stage, importing.destination, importing.ticket.manifest_digest)
        _require_instance(stage, header["instance_id"])
        conversations = stage._db.execute("SELECT id,last_sequence FROM conversations LIMIT 2").fetchall()
        if len(conversations) != 1 or tuple(conversations[0]) != (header["space_root"], importing.total):
            raise ValueError("migration publication stage conversation mismatch")
        _require_exact_head(stage, header["space_root"], importing.total)
        receipt = _receipt(importing, prepared, snapshot)
        _reconcile_history(stage, deadline)

        with target._lock:
            if target._db.in_transaction:
                raise ValueError("migration publication destination transaction is already active")
            target_path, stage_path = _database_path(target), _database_path(stage)
            if not os.path.samefile(stage_path, importing.destination):
                raise ValueError("migration publication stage destination mismatch")
            if not same_stage and os.path.samefile(target_path, stage_path):
                raise ValueError("migration publication requires the exact stage handle")
            try:
                with target._transaction(write=True, before_commit=admitted_commit):
                    # Bulk work has one explicit wall-clock deadline. The usual
                    # fixed instruction allowance applies again on the next
                    # ordinary transaction; _transaction clears this handler
                    # on every success, cancellation or error path.
                    target._db.set_progress_handler(within_budget, 1000)
                    _require_instance(target, header["instance_id"])
                    target._db.execute("""CREATE TABLE IF NOT EXISTS migration_publications(
                        conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
                        application_root TEXT NOT NULL, instance_id TEXT NOT NULL,
                        binding_root TEXT NOT NULL, manifest_digest TEXT NOT NULL,
                        stage_id TEXT NOT NULL, source_authority TEXT NOT NULL,
                        source_revision INTEGER NOT NULL, source_digest TEXT NOT NULL,
                        imported_count INTEGER NOT NULL)""")
                    existing = target._db.execute("SELECT " + ",".join(_RECEIPT_COLUMNS) +
                        " FROM migration_publications WHERE conversation_id=?",
                        (header["space_root"],)).fetchone()
                    already = existing is not None
                    if already and dict(existing) != receipt:
                        raise ValueError("migration publication receipt mismatch")
                    present = target._db.execute("SELECT 1 FROM conversations WHERE id=?",
                        (header["space_root"],)).fetchone() is not None
                    if present and not same_stage and not already:
                        raise ValueError("migration publication destination conversation is unowned")
                    if already and not present:
                        raise ValueError("migration publication owned conversation is missing")
                    if not present:
                        target._db.execute("INSERT INTO conversations(id) VALUES(?)", (header["space_root"],))
                    if same_stage or already:
                        _require_exact_head(target, header["space_root"], importing.total)

                    cursor = importing._manifest.execute("SELECT * FROM entries ORDER BY sequence")
                    seen = 0
                    try:
                        for expected in cursor:
                            _check_time(deadline)
                            record = _row(stage, header["space_root"], expected["message_id"])
                            importing._verify_record(record, expected)
                            if not same_stage and not already:
                                fields = {key: value for key, value in record.items()
                                    if key not in ("id", "sequence", "conversation_id")}
                                validated = validate_message_fields(record["conversation_id"],
                                    message_id=record["id"], **fields)
                                target._append_in_transaction(validated)
                            # Read stored rows, not merely the insertion return
                            # value, so triggers or an altered retry cannot hide
                            # changed content behind an otherwise matching receipt.
                            importing._verify_record(_row(target, header["space_root"],
                                expected["message_id"]), expected)
                            seen += 1
                    finally:
                        cursor.close()
                    if seen != importing.total:
                        raise ValueError("migration publication manifest count mismatch")
                    _require_exact_head(target, header["space_root"], importing.total)
                    if not already:
                        target._db.execute("INSERT INTO migration_publications(" +
                            ",".join(_RECEIPT_COLUMNS) + ") VALUES(" + ",".join("?" for _ in _RECEIPT_COLUMNS) + ")",
                            tuple(receipt[key] for key in _RECEIPT_COLUMNS))
                    # Includes real FTS5 external-content integrity and all
                    # derived audience metadata before any publication commits.
                    _reconcile_database(target._db, deadline)
                    target._db.set_progress_handler(within_budget, 1000)
            except sqlite3.OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError("migration publication time budget exceeded") from exc
                raise
        return dict(state="pending", conversation_id=header["space_root"],
            binding_root=receipt["binding_root"], imported_count=importing.total,
            already_published=already)
