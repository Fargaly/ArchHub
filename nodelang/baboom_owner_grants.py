"""BABOOM owner grants for exact, reviewed Brain writes."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from typing import Mapping

from .universal_cell import NULL_CELL_ID, Cell, CellStore, Conflict, InvalidCell


GRANT_ARGUMENT_KEY = "_baboom_owner_approval"
GRANT_KIND = "baboom-owner-brain-write-approval"
GRANT_VERSION = 1
APPROVAL_PREFIX = "app:baboom-brain-write-approval:"


def _json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def _bounded_text(value: object) -> str | None:
    if type(value) is not str or not value or "\x00" in value:
        return None
    return value if len(value.encode("utf-8")) <= 4096 else None


def _hex_digest(value: object) -> str | None:
    text = _bounded_text(value)
    if text is None or len(text) != 64:
        return None
    return text if all(character in "0123456789abcdef" for character in text) else None


def baboom_brain_write_arguments_digest(arguments: Mapping[str, object]) -> str:
    """Digest the approved Brain write arguments, excluding the grant wrapper."""
    clean = dict(arguments or {})
    clean.pop(GRANT_ARGUMENT_KEY, None)
    return _json_digest(clean)


def _state_root(approval_id: str) -> str:
    return approval_id + ":state"


def _record_root(value: object) -> str | None:
    text = _bounded_text(value)
    return text if text is not None and text.startswith(APPROVAL_PREFIX) else None


def _decode_record(cell: Cell) -> dict[str, object] | None:
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        return None
    try:
        value = json.loads(cell.atom.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def baboom_brain_write_owner_approval_record(
    store: CellStore,
    *,
    owner: str,
    actor: str,
    session: str,
    workflow: str,
    workflow_revision: int,
    scope: str,
    approval_digest: str,
    arguments: Mapping[str, object],
    approval_id: str | None = None,
) -> dict[str, object]:
    """Persist the exact grant a reviewed owner approval may attach to a write."""
    if not isinstance(store, CellStore):
        raise ValueError("invalid owner approval store")
    owner_text = _bounded_text(owner)
    actor_text = _bounded_text(actor)
    session_text = _bounded_text(session)
    workflow_text = _bounded_text(workflow)
    scope_text = _bounded_text(scope)
    approval_digest_text = _hex_digest(approval_digest)
    if (
        owner_text is None or actor_text is None or session_text is None
        or workflow_text is None or scope_text is None
        or approval_digest_text is None or type(workflow_revision) is not int
        or workflow_revision < 0
    ):
        raise ValueError("invalid owner approval record")
    arguments_digest = baboom_brain_write_arguments_digest(arguments)
    approval_root = _record_root(approval_id) if approval_id is not None else None
    if approval_id is not None and approval_root is None:
        raise ValueError("invalid owner approval id")
    approval_root = approval_root or (APPROVAL_PREFIX + uuid.uuid4().hex)
    record = {
        "kind": GRANT_KIND,
        "version": GRANT_VERSION,
        "tool": "brain.write",
        "owner": owner_text,
        "actor": actor_text,
        "session": session_text,
        "workflow": workflow_text,
        "workflow_revision": workflow_revision,
        "scope": scope_text,
        "approval_digest": approval_digest_text,
        "arguments_digest": arguments_digest,
    }
    state_root = _state_root(approval_root)
    store.commit(store.revision, create=(
        Cell(approval_root, NULL_CELL_ID, NULL_CELL_ID,
             json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        Cell(state_root, NULL_CELL_ID, NULL_CELL_ID, b"approved"),
    ))
    return {
        **record,
        "approval_id": approval_root,
    }


def _record_matches_approval(record: Mapping[str, object], approval: Mapping[str, object]) -> bool:
    for key in (
        "kind", "version", "tool", "owner", "actor", "session",
        "workflow", "workflow_revision", "scope",
    ):
        if record.get(key) != approval.get(key):
            return False
    for key in ("approval_digest", "arguments_digest"):
        if not secrets.compare_digest(str(record.get(key) or ""), str(approval.get(key) or "")):
            return False
    return True


def baboom_owner_grant_checker(
    store: CellStore,
    name: str,
    arguments: Mapping[str, object],
    *,
    owner: str,
    actor: str,
    session: str,
    workflow: str,
    workflow_revision: int,
    workflow_digest: str | None = None,
) -> bool:
    """Admit only one exact Brain write approved by an existing workflow scope."""
    if not isinstance(store, CellStore):
        return False
    if name != "brain.write" or not isinstance(arguments, Mapping):
        return False
    approval = arguments.get(GRANT_ARGUMENT_KEY)
    if not isinstance(approval, Mapping):
        return False
    if approval.get("kind") != GRANT_KIND or approval.get("version") != GRANT_VERSION:
        return False
    if approval.get("tool") != name:
        return False
    approval_id = _record_root(approval.get("approval_id"))
    if approval_id is None:
        return False
    for key, value in (
        ("owner", owner), ("actor", actor), ("session", session),
        ("workflow", workflow),
    ):
        if _bounded_text(approval.get(key)) is None or approval.get(key) != value:
            return False
    if approval.get("workflow_revision") != workflow_revision:
        return False
    if _bounded_text(approval.get("workflow")) is None:
        return False
    if _bounded_text(approval.get("scope")) is None:
        return False
    if _hex_digest(approval.get("approval_digest")) is None:
        return False
    if workflow_digest is not None:
        current_digest = _hex_digest(workflow_digest)
        if current_digest is None:
            return False
        if not secrets.compare_digest(str(approval.get("approval_digest") or ""), current_digest):
            return False
    expected_digest = _hex_digest(approval.get("arguments_digest"))
    if expected_digest is None:
        return False
    actual_digest = baboom_brain_write_arguments_digest(arguments)
    if not secrets.compare_digest(expected_digest, actual_digest):
        return False
    snapshot = store.snapshot()
    record_cell = snapshot.cells.get(approval_id)
    state_cell = snapshot.cells.get(_state_root(approval_id))
    if record_cell is None or state_cell is None or state_cell.atom != b"approved":
        return False
    record = _decode_record(record_cell)
    if record is None or not _record_matches_approval(record, approval):
        return False
    if not secrets.compare_digest(str(record.get("arguments_digest") or ""), actual_digest):
        return False
    try:
        store.commit(snapshot.revision, replace=(
            Cell(state_cell.id, NULL_CELL_ID, NULL_CELL_ID, b"consumed"),
        ))
    except (Conflict, InvalidCell):
        return False
    return True


__all__ = [
    "GRANT_ARGUMENT_KEY",
    "baboom_brain_write_arguments_digest",
    "baboom_brain_write_owner_approval_record",
    "baboom_owner_grant_checker",
]
