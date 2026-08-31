"""Append-only, session-scoped history for generic Cell changes.

The physical journal retains every Store revision.  This graph protocol makes
the user-visible transaction itself inspectable: actor, view session,
operation, exact before/after Cell images, revision, and any compensation are
ordinary Cells.  Undo and redo append compensating transactions; they never
erase or roll the Store back.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    Snapshot,
)


ROLE_NAMES = (
    "vocabulary-member",
    "transaction",
    "actor",
    "session",
    "operation",
    "authority",
    "scope",
    "interface",
    "base-revision",
    "result-revision",
    "timestamp",
    "change",
    "target",
    "before",
    "after",
    "undo-of",
    "redo-of",
)


@dataclass(frozen=True, slots=True)
class ChangeHistoryProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown change-history role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class CellChange:
    root_id: str
    target_root: str
    before: Cell | None
    after: Cell


@dataclass(frozen=True, slots=True)
class ChangeTransaction:
    root_id: str
    actor_root: str
    session_root: str
    operation_root: str
    authority_root: str | None
    scope_roots: tuple[str, ...]
    interface_root: str | None
    base_revision: int
    result_revision: int
    timestamp: str
    changes: tuple[CellChange, ...]
    undo_of: str | None
    redo_of: str | None


@dataclass(frozen=True, slots=True)
class ChangeCommit:
    root_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class HistoryState:
    undo_root: str | None
    redo_root: str | None
    applied_roots: tuple[str, ...]
    redo_roots: tuple[str, ...]


def bootstrap_change_history_protocol(
    store: CellStore,
    *,
    prefix: str = "change-history-protocol",
) -> ChangeHistoryProtocol:
    root_id = prefix + ":root"
    snapshot = store.snapshot()
    if root_id in snapshot.cells:
        members = read_relation(snapshot, root_id, budget=256)
        existing_by_name: dict[str, str] = {}
        for member in members:
            cell = snapshot.cells[member.participant_id]
            if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
                raise InvalidCell(
                    "change-history vocabulary member is not terminal"
                )
            try:
                name = cell.atom.decode("ascii")
            except UnicodeDecodeError as exc:
                raise InvalidCell(
                    "change-history role is not ASCII"
                ) from exc
            existing_by_name[name] = member.participant_id
        missing_names = tuple(
            name for name in ROLE_NAMES if name not in existing_by_name
        )
        if missing_names:
            vocabulary_roles = {member.role_id for member in members}
            if len(vocabulary_roles) != 1:
                raise InvalidCell(
                    "change-history vocabulary has inconsistent incidences"
                )
            vocabulary_role = next(iter(vocabulary_roles))
            expected_vocabulary_role = prefix + ":role:vocabulary-member"
            if vocabulary_role != expected_vocabulary_role:
                raise InvalidCell(
                    "change-history vocabulary does not self-identify"
                )
            missing_roots = {
                name: "%s:role:%s" % (prefix, name)
                for name in missing_names
            }
            if set(missing_roots.values()).intersection(snapshot.cells):
                raise InvalidCell(
                    "change-history vocabulary migration collides with Cells"
                )
            patch = prepare_append_relation_members(
                snapshot,
                root_id,
                (
                    (vocabulary_role, root)
                    for root in missing_roots.values()
                ),
                budget=256,
            )
            store.commit(
                snapshot.revision,
                create=(
                    *(
                        Cell(
                            root,
                            NULL_CELL_ID,
                            NULL_CELL_ID,
                            name.encode("ascii"),
                        )
                        for name, root in missing_roots.items()
                    ),
                    *patch.create,
                ),
                replace=patch.replace,
            )
            snapshot = store.snapshot()
        return project_change_history_protocol(snapshot, root_id)
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in ROLE_NAMES
    }
    batch = CellBatch(store)
    for name, role_root in roles.items():
        batch.add(Cell(
            role_root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
        ))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return ChangeHistoryProtocol(root_id, MappingProxyType(roles))


def project_change_history_protocol(
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 128,
) -> ChangeHistoryProtocol:
    members = read_relation(snapshot, root_id, budget=budget)
    if not members:
        raise InvalidCell("change-history vocabulary is empty")
    vocabulary_roles = {member.role_id for member in members}
    if len(vocabulary_roles) != 1:
        raise InvalidCell("change-history vocabulary has inconsistent incidences")
    vocabulary_role = next(iter(vocabulary_roles))
    by_name: dict[str, str] = {}
    for member in members:
        cell = snapshot.cells[member.participant_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("change-history vocabulary member is not terminal")
        try:
            name = cell.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell("change-history role is not ASCII") from exc
        if name in by_name:
            raise InvalidCell("change-history vocabulary repeats a role")
        by_name[name] = member.participant_id
    if set(by_name) != set(ROLE_NAMES):
        raise InvalidCell("change-history vocabulary is incomplete or extended")
    if by_name["vocabulary-member"] != vocabulary_role:
        raise InvalidCell("change-history vocabulary does not self-identify")
    return ChangeHistoryProtocol(root_id, MappingProxyType(by_name))


def _single(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell(
            "change transaction requires exactly one %s" % label
        )
    return values[0]


def _optional(members, role_id: str, label: str) -> str | None:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) > 1:
        raise InvalidCell("change transaction repeats %s" % label)
    return values[0] if values else None


def _many(members, role_id: str, label: str) -> tuple[str, ...]:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != len(set(values)):
        raise InvalidCell("change transaction repeats %s" % label)
    return values


def _terminal_text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("change transaction %s is not terminal" % label)
        return cell.atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell(
            "change transaction %s is missing or invalid" % label
        ) from exc


def _image_as_target(image: Cell, target_root: str) -> Cell:
    return Cell(target_root, image.link0, image.link1, image.atom)


def read_change_transaction(
    snapshot: Snapshot,
    protocol: ChangeHistoryProtocol,
    transaction_root: str,
    *,
    budget: int = 10_000,
) -> ChangeTransaction:
    if project_change_history_protocol(
        snapshot, protocol.root_id, budget=min(budget, 256)
    ) != protocol:
        raise InvalidCell("change-history protocol authority drifted")
    members = read_relation(snapshot, transaction_root, budget=budget)
    admitted = {
        protocol.role("actor"),
        protocol.role("session"),
        protocol.role("operation"),
        protocol.role("authority"),
        protocol.role("scope"),
        protocol.role("interface"),
        protocol.role("base-revision"),
        protocol.role("result-revision"),
        protocol.role("timestamp"),
        protocol.role("change"),
        protocol.role("undo-of"),
        protocol.role("redo-of"),
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("change transaction contains an undeclared role")
    actor_root = _single(members, protocol.role("actor"), "actor")
    session_root = _single(members, protocol.role("session"), "session")
    operation_root = _single(
        members, protocol.role("operation"), "operation"
    )
    authority_root = _optional(
        members, protocol.role("authority"), "authority"
    )
    scope_roots = _many(members, protocol.role("scope"), "scope")
    interface_root = _optional(
        members, protocol.role("interface"), "interface"
    )
    base_root = _single(
        members, protocol.role("base-revision"), "base revision"
    )
    result_root = _single(
        members, protocol.role("result-revision"), "result revision"
    )
    timestamp_root = _single(
        members, protocol.role("timestamp"), "timestamp"
    )
    undo_of = _optional(members, protocol.role("undo-of"), "undo source")
    redo_of = _optional(members, protocol.role("redo-of"), "redo source")
    if undo_of is not None and redo_of is not None:
        raise InvalidCell("change transaction cannot be both undo and redo")
    try:
        base_revision = int(_terminal_text(
            snapshot, base_root, "base revision"
        ))
        result_revision = int(_terminal_text(
            snapshot, result_root, "result revision"
        ))
    except ValueError as exc:
        raise InvalidCell("change transaction revision is not an integer") from exc
    if result_revision != base_revision + 1:
        raise InvalidCell("change transaction does not describe one atomic revision")

    change_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("change")
    )
    if not change_roots or len(change_roots) > budget:
        raise InvalidCell("change transaction has an invalid change count")
    changes: list[CellChange] = []
    targets: set[str] = set()
    for change_root in change_roots:
        change_members = read_relation(snapshot, change_root, budget=32)
        allowed = {
            protocol.role("target"),
            protocol.role("before"),
            protocol.role("after"),
        }
        if any(member.role_id not in allowed for member in change_members):
            raise InvalidCell("Cell change contains an undeclared role")
        target_root = _single(
            change_members, protocol.role("target"), "change target"
        )
        if target_root in targets:
            raise InvalidCell("change transaction repeats a target")
        targets.add(target_root)
        before_root = _optional(
            change_members, protocol.role("before"), "before image"
        )
        after_root = _single(
            change_members, protocol.role("after"), "after image"
        )
        if target_root not in snapshot.cells:
            raise InvalidCell("change transaction target is missing")
        try:
            before = (
                _image_as_target(snapshot.cells[before_root], target_root)
                if before_root is not None else None
            )
            after = _image_as_target(snapshot.cells[after_root], target_root)
        except KeyError as exc:
            raise InvalidCell("change transaction image is missing") from exc
        changes.append(CellChange(change_root, target_root, before, after))
    return ChangeTransaction(
        transaction_root,
        actor_root,
        session_root,
        operation_root,
        authority_root,
        scope_roots,
        interface_root,
        base_revision,
        result_revision,
        _terminal_text(snapshot, timestamp_root, "timestamp"),
        tuple(changes),
        undo_of,
        redo_of,
    )


def _history_transaction_roots(
    snapshot: Snapshot,
    protocol: ChangeHistoryProtocol,
    history_root: str,
    *,
    budget: int,
) -> tuple[str, ...]:
    members = read_relation(snapshot, history_root, budget=budget)
    if any(member.role_id != protocol.role("transaction") for member in members):
        raise InvalidCell("change history contains a non-transaction member")
    roots = tuple(member.participant_id for member in members)
    if len(roots) != len(set(roots)):
        raise InvalidCell("change history repeats a transaction")
    return roots


def history_state(
    snapshot: Snapshot,
    protocol: ChangeHistoryProtocol,
    history_root: str,
    *,
    budget: int = 10_000,
) -> HistoryState:
    applied: list[str] = []
    redo: list[str] = []
    transactions: dict[str, ChangeTransaction] = {}
    for root in _history_transaction_roots(
        snapshot, protocol, history_root, budget=budget
    ):
        transaction = read_change_transaction(
            snapshot, protocol, root, budget=budget
        )
        transactions[root] = transaction
        if transaction.undo_of is not None:
            original = transaction.undo_of
            if original not in transactions or not applied or applied[-1] != original:
                raise InvalidCell("change history has an invalid undo order")
            if (
                transactions[original].undo_of is not None
                or transactions[original].redo_of is not None
            ):
                raise InvalidCell("undo source is not an original transaction")
            applied.pop()
            redo.append(original)
        elif transaction.redo_of is not None:
            original = transaction.redo_of
            if original not in transactions or not redo or redo[-1] != original:
                raise InvalidCell("change history has an invalid redo order")
            redo.pop()
            applied.append(original)
        else:
            applied.append(root)
            redo.clear()
    return HistoryState(
        applied[-1] if applied else None,
        redo[-1] if redo else None,
        tuple(applied),
        tuple(redo),
    )


def commit_tracked_change(
    store: CellStore,
    protocol: ChangeHistoryProtocol,
    *,
    history_root: str,
    actor_root: str,
    session_root: str,
    operation_root: str,
    authority_root: str,
    scope_roots: Iterable[str],
    interface_root: str | None = None,
    create: Iterable[Cell] = (),
    replace: Iterable[Cell] = (),
    undo_of: str | None = None,
    redo_of: str | None = None,
    transaction_id: str | None = None,
    expected_revision: int | None = None,
) -> ChangeCommit:
    """Commit one graph mutation and its inspectable receipt atomically."""
    snapshot = store.snapshot()
    if expected_revision is not None and snapshot.revision != expected_revision:
        raise Conflict(
            "expected revision %s, current revision is %s"
            % (expected_revision, snapshot.revision)
        )
    if project_change_history_protocol(snapshot, protocol.root_id) != protocol:
        raise InvalidCell("change-history protocol authority drifted")
    if history_root not in snapshot.cells:
        raise InvalidCell("change history root is missing")
    normalized_scope_roots = tuple(scope_roots)
    if (
        not normalized_scope_roots
        or len(normalized_scope_roots) != len(set(normalized_scope_roots))
    ):
        raise InvalidCell("change transaction scopes are invalid")
    for root_id, label in (
        (actor_root, "actor"),
        (session_root, "session"),
        (operation_root, "operation"),
        (authority_root, "authority"),
        *((root, "scope") for root in normalized_scope_roots),
    ):
        if root_id not in snapshot.cells:
            raise InvalidCell("change transaction %s is missing" % label)
    if interface_root is not None and interface_root not in snapshot.cells:
        raise InvalidCell("change transaction interface is missing")
    if undo_of is not None and redo_of is not None:
        raise InvalidCell("change cannot be both undo and redo")
    created = tuple(create)
    replacements = tuple(
        cell for cell in replace
        if snapshot.cells.get(cell.id) != cell
    )
    create_ids = tuple(cell.id for cell in created)
    replace_ids = tuple(cell.id for cell in replacements)
    duplicate_create_ids = len(create_ids) != len(set(create_ids))
    duplicate_replace_ids = len(replace_ids) != len(set(replace_ids))
    create_replace_overlap = set(create_ids).intersection(replace_ids)
    created_existing = tuple(
        root_id for root_id in create_ids if root_id in snapshot.cells
    )
    missing_replace_ids = tuple(
        root_id for root_id in replace_ids if root_id not in snapshot.cells
    )
    if (
        duplicate_create_ids
        or duplicate_replace_ids
        or create_replace_overlap
        or created_existing
        or missing_replace_ids
    ):
        detail = (
            "duplicate_create=%s duplicate_replace=%s overlap=%s "
            "created_existing=%s missing_replace=%s"
        ) % (
            duplicate_create_ids,
            duplicate_replace_ids,
            tuple(sorted(create_replace_overlap))[:3],
            tuple(sorted(created_existing))[:3],
            missing_replace_ids[:3],
        )
        raise InvalidCell(
            "tracked change contains invalid Cell identities: %s" % detail
        )
    if not replacements:
        raise InvalidCell(
            "tracked change requires a continuing Cell anchor for compensation"
        )

    token = transaction_id or "change:%s" % uuid.uuid4().hex
    base_revision_root = token + ":base-revision"
    result_revision_root = token + ":result-revision"
    timestamp_root = token + ":timestamp"
    record_cells: list[Cell] = [
        Cell(
            base_revision_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(snapshot.revision).encode("ascii"),
        ),
        Cell(
            result_revision_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(snapshot.revision + 1).encode("ascii"),
        ),
        Cell(
            timestamp_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            datetime.now(timezone.utc).isoformat().encode("ascii"),
        ),
    ]
    change_roots: list[str] = []
    for index, cell in enumerate((*replacements, *created)):
        change_root = "%s:change:%s" % (token, index)
        before_root = change_root + ":before"
        after_root = change_root + ":after"
        before = snapshot.cells.get(cell.id)
        if before is not None:
            record_cells.append(Cell(
                before_root, before.link0, before.link1, before.atom
            ))
        record_cells.append(Cell(
            after_root, cell.link0, cell.link1, cell.atom
        ))
        relation = compose_relation_cells((
            (protocol.role("target"), cell.id),
            *((
                (protocol.role("before"), before_root),
            ) if before is not None else ()),
            (protocol.role("after"), after_root),
        ), relation_id=change_root)
        record_cells.extend(relation.cells)
        change_roots.append(change_root)

    transaction = compose_relation_cells((
        (protocol.role("actor"), actor_root),
        (protocol.role("session"), session_root),
        (protocol.role("operation"), operation_root),
        (protocol.role("authority"), authority_root),
        *((protocol.role("scope"), root) for root in normalized_scope_roots),
        *((
            (protocol.role("interface"), interface_root),
        ) if interface_root is not None else ()),
        (protocol.role("base-revision"), base_revision_root),
        (protocol.role("result-revision"), result_revision_root),
        (protocol.role("timestamp"), timestamp_root),
        *((protocol.role("change"), root) for root in change_roots),
        *((
            (protocol.role("undo-of"), undo_of),
        ) if undo_of is not None else ()),
        *((
            (protocol.role("redo-of"), redo_of),
        ) if redo_of is not None else ()),
    ), relation_id=token)
    record_cells.extend(transaction.cells)
    history_patch = prepare_append_relation_members(
        snapshot,
        history_root,
        ((protocol.role("transaction"), token),),
        budget=100_000,
    )
    record_cells.extend(history_patch.create)
    pending_create = (*created, *record_cells)
    pending_ids = tuple(cell.id for cell in pending_create)
    if (
        len(pending_ids) != len(set(pending_ids))
        or any(root_id in snapshot.cells for root_id in pending_ids)
    ):
        raise InvalidCell("tracked change record has an identity collision")
    replacement_map = {cell.id: cell for cell in replacements}
    for cell in history_patch.replace:
        previous = replacement_map.get(cell.id)
        if previous is not None and previous != cell:
            raise InvalidCell("tracked change conflicts with its history append")
        replacement_map[cell.id] = cell
    revision = store.commit(
        snapshot.revision,
        create=pending_create,
        replace=tuple(replacement_map.values()),
    )
    if revision != snapshot.revision + 1:
        raise InvalidCell("tracked change published an unexpected revision")
    return ChangeCommit(token, revision)


def _incoming_links_for_targets(
    snapshot: Snapshot,
    target_roots: frozenset[str],
) -> Mapping[str, frozenset[tuple[str, int]]]:
    """Index every guarded target in one graph pass."""
    if not target_roots:
        return MappingProxyType({})
    incoming: dict[str, set[tuple[str, int]]] = {
        root: set() for root in target_roots
    }
    for cell in snapshot.cells.values():
        if cell.link0 in incoming:
            incoming[cell.link0].add((cell.id, 0))
        if cell.link1 in incoming:
            incoming[cell.link1].add((cell.id, 1))
    return MappingProxyType({
        root: frozenset(links) for root, links in incoming.items()
    })


def _require_transaction_context(
    transaction: ChangeTransaction,
    *,
    actor_root: str,
    session_root: str,
) -> None:
    if (
        transaction.actor_root != actor_root
        or transaction.session_root != session_root
    ):
        raise Conflict("change belongs to another actor or view session")


def _compensation_tolerates_drift(target_root: str) -> bool:
    """Structural linkage and signed-authority cells compensate elsewhere.

    A chain cell is pure linkage: replaying its recorded bytes after another
    lawful append would corrupt the relation, and skipping it keeps the
    current, longer chain intact. A signed authority relationship can never
    be compensated by byte replay at all -- the broker's anti-replay
    generation rightly refuses resurrection -- so undo/redo leave those
    cells to the grant reconciler, which issues NEW signed generations.
    """
    return (
        target_root.startswith("chain:")
        or "archhub-projection" in target_root
        or target_root.startswith("app:authority-relationship:")
    )


def undo_last_change(
    store: CellStore,
    protocol: ChangeHistoryProtocol,
    *,
    history_root: str,
    actor_root: str,
    session_root: str,
    operation_root: str,
) -> ChangeCommit:
    snapshot = store.snapshot()
    state = history_state(snapshot, protocol, history_root)
    if state.undo_root is None:
        raise Conflict("nothing to undo")
    original = read_change_transaction(
        snapshot, protocol, state.undo_root
    )
    _require_transaction_context(
        original, actor_root=actor_root, session_root=session_root
    )
    if original.authority_root is None or not original.scope_roots:
        raise Conflict("change lacks compensation authority evidence")
    result_snapshot = store.at(original.result_revision)
    created_targets = frozenset(
        change.target_root for change in original.changes
        if change.before is None
    )
    current_incoming = _incoming_links_for_targets(snapshot, created_targets)
    result_incoming = _incoming_links_for_targets(
        result_snapshot, created_targets
    )
    replacements: list[Cell] = []
    for change in original.changes:
        current = snapshot.cells.get(change.target_root)
        if current != change.after:
            if _compensation_tolerates_drift(change.target_root):
                continue
            raise Conflict(
                "Cell changed after the recorded transaction: %s"
                % change.target_root
            )
        if change.before is None:
            if (
                current_incoming[change.target_root]
                != result_incoming[change.target_root]
            ):
                raise Conflict(
                    "created Cell gained references after the recorded transaction"
                )
            continue
        replacements.append(change.before)
    return commit_tracked_change(
        store,
        protocol,
        history_root=history_root,
        actor_root=actor_root,
        session_root=session_root,
        operation_root=operation_root,
        authority_root=original.authority_root,
        scope_roots=original.scope_roots,
        interface_root=original.interface_root,
        replace=replacements,
        undo_of=original.root_id,
    )


def redo_last_change(
    store: CellStore,
    protocol: ChangeHistoryProtocol,
    *,
    history_root: str,
    actor_root: str,
    session_root: str,
    operation_root: str,
) -> ChangeCommit:
    snapshot = store.snapshot()
    state = history_state(snapshot, protocol, history_root)
    if state.redo_root is None:
        raise Conflict("nothing to redo")
    original = read_change_transaction(
        snapshot, protocol, state.redo_root
    )
    _require_transaction_context(
        original, actor_root=actor_root, session_root=session_root
    )
    if original.authority_root is None or not original.scope_roots:
        raise Conflict("change lacks compensation authority evidence")
    replacements: list[Cell] = []
    for change in original.changes:
        current = snapshot.cells.get(change.target_root)
        expected = change.before if change.before is not None else change.after
        if current != expected:
            if _compensation_tolerates_drift(change.target_root):
                continue
            raise Conflict(
                "Cell changed after the recorded compensation: %s"
                % change.target_root
            )
        if change.before is not None:
            replacements.append(change.after)
    return commit_tracked_change(
        store,
        protocol,
        history_root=history_root,
        actor_root=actor_root,
        session_root=session_root,
        operation_root=operation_root,
        authority_root=original.authority_root,
        scope_roots=original.scope_roots,
        interface_root=original.interface_root,
        replace=replacements,
        redo_of=original.root_id,
    )


__all__ = [
    "ChangeCommit",
    "ChangeHistoryProtocol",
    "ChangeTransaction",
    "CellChange",
    "HistoryState",
    "bootstrap_change_history_protocol",
    "commit_tracked_change",
    "history_state",
    "project_change_history_protocol",
    "read_change_transaction",
    "redo_last_change",
    "undo_last_change",
]
