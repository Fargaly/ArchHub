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
import json
from types import MappingProxyType
from typing import Iterable, Mapping
from weakref import WeakKeyDictionary, ref
import threading
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
    MatchBudgetExceeded,
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
    "record",
)

# A compact change record (founder order 2026-09-23): the transaction keeps
# its actor, session, operation, authority, scope and interface links, and one
# terminal "record" holds its base/result revisions, time and exact target
# set. Before/after images are read from the revision history (cell_versions)
# instead of being copied into the graph again for every changed Cell.
# Transactions recorded with per-change images stay readable and undoable.
COMPACT_RECORD_FORMAT = "archhub-change/compact-v1"


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
class _ChangeTransactionHeader:
    """Presentation metadata; never an executable or fully audited change."""
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
    change_count: int
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


@dataclass(frozen=True, slots=True)
class _HeaderReuse:
    """One header a walk already proved, with the walk length it cost."""
    header: _ChangeTransactionHeader
    steps: int


class ChangeTransactionHeaderMemo:
    """Disposable reuse of headers of transactions the Store cannot rewrite.

    commit_tracked_change writes a transaction once and never again: every
    Cell it mints carries the transaction identity as its prefix -- the
    relation root itself, its <token>:chain:<n> and <token>:incidence:<n>
    Cells, <token>:base-revision, <token>:result-revision, <token>:timestamp
    and <token>:change:<n>[:before|:after] -- and appending the transaction to
    the history relation replaces only history-relation Cells. The header is
    therefore a function of Cells under one prefix, and a Store advance that
    touches none of them cannot change it.

    This is acceleration in the SPEC 3.1.6-7 sense and nothing else. It holds
    only what a generic walk already returned, it is bound to the exact
    published head mapping it was proved against, a commit drops every entry
    whose prefix that commit wrote, and a revision the memo cannot account
    for one revision at a time empties it. Deleting the memo costs a walk and
    changes no projected byte and no refusal: a hit re-applies the same
    traversal budget the walk would have applied.
    """

    MAX_ACCOUNTED_REVISIONS = 4096

    __slots__ = (
        "_lock", "_cells", "_revision", "_entries", "hits", "misses",
        "__weakref__",
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cells = None
        self._revision = None
        self._entries: dict[str, _HeaderReuse] = {}
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def forget(self, touched: Iterable[str]) -> None:
        """Drop every memoised transaction one commit wrote under."""
        with self._lock:
            if not self._entries:
                return
            doomed = set()
            for cell_id in touched:
                prefix = cell_id
                while True:
                    if prefix in self._entries:
                        doomed.add(prefix)
                    cut = prefix.rfind(":")
                    if cut < 0:
                        break
                    prefix = prefix[:cut]
            for root_id in doomed:
                del self._entries[root_id]

    def bind(self, store: CellStore, snapshot: Snapshot) -> None:
        """Account for every revision between this memo and one snapshot.

        A memo already bound to this exact published mapping is already
        proved. Otherwise each intervening revision is retired by the exact
        Cell identities it wrote; anything this cannot account for -- a
        rewind, a reload, a gap wider than the accounted window -- empties
        the memo instead of guessing.
        """
        with self._lock:
            if snapshot.cells is self._cells:
                return
            revision = snapshot.revision
            if (
                self._revision is None
                or type(revision) is not int
                or revision <= self._revision
                or revision - self._revision > self.MAX_ACCOUNTED_REVISIONS
            ):
                self._entries = {}
            else:
                try:
                    for step in range(self._revision + 1, revision + 1):
                        self.forget(store.revision_changes(step))
                except Exception:
                    self._entries = {}
            self._cells = snapshot.cells
            self._revision = revision

    def get(self, snapshot: Snapshot, transaction_root: str, budget: int):
        with self._lock:
            if snapshot.cells is not self._cells:
                return None
            reuse = self._entries.get(transaction_root)
        if reuse is None:
            self.misses += 1
            return None
        # The walk this stands in for would have refused first.
        if reuse.steps > budget:
            raise MatchBudgetExceeded(
                "relation projection exceeded %s chain cells" % budget
            )
        if reuse.header.change_count > budget:
            raise InvalidCell("change transaction has an invalid change count")
        self.hits += 1
        return reuse.header

    def put(self, snapshot, transaction_root, header, steps) -> None:
        with self._lock:
            if snapshot.cells is not self._cells:
                return
            self._entries[transaction_root] = _HeaderReuse(header, steps)


_CHANGE_TRANSACTION_HEADER_MEMOS: WeakKeyDictionary[
    CellStore, ChangeTransactionHeaderMemo
] = WeakKeyDictionary()
_CHANGE_TRANSACTION_HEADER_MEMO_LOCK = threading.RLock()


def change_transaction_header_memo(
    store: CellStore | None,
) -> ChangeTransactionHeaderMemo | None:
    """Return one Store's header memo, minting and arming it on demand."""
    if store is None:
        return None
    with _CHANGE_TRANSACTION_HEADER_MEMO_LOCK:
        memo = _CHANGE_TRANSACTION_HEADER_MEMOS.get(store)
        if memo is not None:
            return memo
        memo = ChangeTransactionHeaderMemo()
        _CHANGE_TRANSACTION_HEADER_MEMOS[store] = memo
        memo_ref = ref(memo)

        def invalidate(event) -> None:
            active = memo_ref()
            if active is not None:
                active.forget(event.touched)

        store.subscribe(invalidate)
        return memo


def forget_change_transaction_header_memo(store: CellStore) -> None:
    """Delete one Store accelerator; the next projection rebuilds it."""
    with _CHANGE_TRANSACTION_HEADER_MEMO_LOCK:
        _CHANGE_TRANSACTION_HEADER_MEMOS.pop(store, None)


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
    history=None,
) -> ChangeTransaction:
    """Read one transaction with its exact before/after images.

    ``history(revision) -> Snapshot`` (normally ``store.at``) supplies the
    images of a compact record; a record with copied images needs none.
    """
    return _read_change_transaction(
        snapshot, protocol, transaction_root, budget=budget, history=history
    )


def _compact_record(snapshot: Snapshot, record_root: str) -> dict:
    try:
        record = json.loads(_terminal_text(snapshot, record_root, "record"))
    except ValueError as exc:
        raise InvalidCell("compact change record is not JSON") from exc
    if (
        type(record) is not dict
        or record.get("format") != COMPACT_RECORD_FORMAT
        or set(record) != {"format", "base", "result", "timestamp", "targets", "created"}
        or type(record["base"]) is not int
        or type(record["result"]) is not int
        or record["result"] != record["base"] + 1
        or type(record["timestamp"]) is not str
        or type(record["targets"]) is not list
        or type(record["created"]) is not list
        or not record["targets"]
        or any(type(target) is not str or not target for target in record["targets"])
        or len(set(record["targets"])) != len(record["targets"])
        or not set(record["created"]) <= set(record["targets"])
        or len(set(record["created"])) != len(record["created"])
    ):
        raise InvalidCell("compact change record is invalid")
    return record


def _read_change_transaction_header(
    snapshot, protocol, transaction_root, *, budget, memo=None,
    protocol_verified=False,
):
    """Read one presentation header, or reuse the walk that already proved it."""
    if memo is not None:
        reused = memo.get(snapshot, transaction_root, budget)
        if reused is not None:
            return reused
    return _read_change_transaction(
        snapshot, protocol, transaction_root, budget=budget, summary_only=True,
        protocol_verified=protocol_verified, memo=memo,
    )


def _read_change_transaction(
    snapshot, protocol, transaction_root, *, budget, summary_only=False,
    protocol_verified=False, memo=None, history=None, header_without_history=False,
):
    if not protocol_verified and project_change_history_protocol(
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
        protocol.role("record"),
    }
    if any(member.role_id not in admitted for member in members):
        raise InvalidCell("change transaction contains an undeclared role")
    record_root = _optional(members, protocol.role("record"), "record")
    if record_root is not None:
        return _read_compact_change_transaction(
            snapshot, protocol, transaction_root, members, record_root,
            budget=budget, summary_only=summary_only, memo=memo,
            history=history, header_without_history=header_without_history,
        )
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
    if summary_only:
        if len(change_roots) != len(set(change_roots)):
            raise InvalidCell("change transaction repeats a change")
        header = _ChangeTransactionHeader(
            transaction_root, actor_root, session_root, operation_root,
            authority_root, scope_roots, interface_root, base_revision,
            result_revision, _terminal_text(snapshot, timestamp_root, "timestamp"),
            len(change_roots), undo_of, redo_of,
        )
        if memo is not None:
            # One chain Cell per member is exactly what this walk stepped
            # through, so a reused header refuses the same budget it would.
            memo.put(snapshot, transaction_root, header, len(members) or 1)
        return header
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


def _read_compact_change_transaction(
    snapshot, protocol, transaction_root, members, record_root, *, budget,
    summary_only, memo, history, header_without_history,
):
    for name in ("base-revision", "result-revision", "timestamp", "change"):
        if any(member.role_id == protocol.role(name) for member in members):
            raise InvalidCell("compact change record mixes record formats")
    if record_root != transaction_root + ":record":
        raise InvalidCell("compact change record ownership drifted")
    actor_root = _single(members, protocol.role("actor"), "actor")
    session_root = _single(members, protocol.role("session"), "session")
    operation_root = _single(members, protocol.role("operation"), "operation")
    authority_root = _optional(members, protocol.role("authority"), "authority")
    scope_roots = _many(members, protocol.role("scope"), "scope")
    interface_root = _optional(members, protocol.role("interface"), "interface")
    undo_of = _optional(members, protocol.role("undo-of"), "undo source")
    redo_of = _optional(members, protocol.role("redo-of"), "redo source")
    if undo_of is not None and redo_of is not None:
        raise InvalidCell("change transaction cannot be both undo and redo")
    record = _compact_record(snapshot, record_root)
    targets = tuple(record["targets"])
    if len(targets) > budget:
        raise InvalidCell("change transaction has an invalid change count")
    if summary_only or (history is None and header_without_history):
        header = _ChangeTransactionHeader(
            transaction_root, actor_root, session_root, operation_root,
            authority_root, scope_roots, interface_root, record["base"],
            record["result"], record["timestamp"], len(targets), undo_of,
            redo_of,
        )
        if summary_only and memo is not None:
            memo.put(snapshot, transaction_root, header, len(members) or 1)
        return header
    if history is None:
        raise InvalidCell("compact change record requires its revision history")
    if record["result"] > snapshot.revision:
        raise InvalidCell("compact change record is newer than its snapshot")
    before_snapshot = history(record["base"])
    after_snapshot = history(record["result"])
    created = set(record["created"])
    changes: list[CellChange] = []
    for index, target_root in enumerate(targets):
        if target_root not in snapshot.cells:
            raise InvalidCell("change transaction target is missing")
        after = after_snapshot.cells.get(target_root)
        before = before_snapshot.cells.get(target_root)
        if after is None or (before is None) != (target_root in created):
            raise InvalidCell("compact change record disagrees with its revisions")
        changes.append(CellChange(
            "%s:change:%s" % (transaction_root, index), target_root, before, after,
        ))
    return ChangeTransaction(
        transaction_root, actor_root, session_root, operation_root,
        authority_root, scope_roots, interface_root, record["base"],
        record["result"], record["timestamp"], tuple(changes), undo_of, redo_of,
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
    history=None,
) -> HistoryState:
    return _history_state_and_transactions(
        snapshot, protocol, history_root, budget=budget, history=history
    )[0]


def _history_state_and_transactions(
    snapshot: Snapshot,
    protocol: ChangeHistoryProtocol,
    history_root: str,
    *,
    budget: int = 10_000,
    history=None,
) -> tuple[HistoryState, dict[str, ChangeTransaction]]:
    """Return the state with the exact transactions validated to derive it.

    Records with copied images are validated in full here. A compact record
    is validated in full when ``history`` is supplied, and otherwise by its
    header; every undo/redo re-reads its one transaction with history.
    """
    def reader(snapshot_, protocol_, transaction_root, *, budget):
        return _read_change_transaction(
            snapshot_, protocol_, transaction_root, budget=budget,
            history=history, header_without_history=True,
        )

    return _read_history_projection(
        snapshot, protocol, history_root, budget, reader
    )


def _history_summary(
    snapshot: Snapshot,
    protocol: ChangeHistoryProtocol,
    history_root: str,
    *,
    budget: int = 10_000,
    memo: ChangeTransactionHeaderMemo | None = None,
) -> tuple[HistoryState, dict[str, _ChangeTransactionHeader]]:
    """Describe history candidates without materializing historical Cell images.

    Header and compensation order are validated here. Full change-body checks
    remain in history_state/read_change_transaction and every undo/redo path.
    This summary grants no execution authority and retains no projection cache.

    The protocol authority is proved once, where the first transaction would
    have proved it, and then holds for every transaction of this one summary:
    they all read the same immutable snapshot. With a memo, that proof is the
    only reason a reused header still answers for this revision.
    """
    verified = []

    def reader(snapshot_, protocol_, transaction_root, *, budget):
        if not verified:
            if project_change_history_protocol(
                snapshot_, protocol_.root_id, budget=min(budget, 256)
            ) != protocol_:
                raise InvalidCell("change-history protocol authority drifted")
            verified.append(True)
        return _read_change_transaction_header(
            snapshot_, protocol_, transaction_root, budget=budget, memo=memo,
            protocol_verified=True,
        )

    return _read_history_projection(
        snapshot, protocol, history_root, budget, reader
    )


def _read_history_projection(snapshot, protocol, history_root, budget, reader):
    applied: list[str] = []
    redo: list[str] = []
    transactions = {}
    for root in _history_transaction_roots(
        snapshot, protocol, history_root, budget=budget
    ):
        transaction = reader(
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
    state = HistoryState(
        applied[-1] if applied else None,
        redo[-1] if redo else None,
        tuple(applied),
        tuple(redo),
    )
    return state, transactions


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
    record_root = token + ":record"
    record_cells: list[Cell] = [Cell(
        record_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        json.dumps({
            "format": COMPACT_RECORD_FORMAT,
            "base": snapshot.revision,
            "result": snapshot.revision + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "targets": [cell.id for cell in (*replacements, *created)],
            "created": [cell.id for cell in created],
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"),
    )]

    transaction = compose_relation_cells((
        (protocol.role("actor"), actor_root),
        (protocol.role("session"), session_root),
        (protocol.role("operation"), operation_root),
        (protocol.role("authority"), authority_root),
        *((protocol.role("scope"), root) for root in normalized_scope_roots),
        *((
            (protocol.role("interface"), interface_root),
        ) if interface_root is not None else ()),
        (protocol.role("record"), record_root),
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
    state = history_state(snapshot, protocol, history_root, history=store.at)
    if state.undo_root is None:
        raise Conflict("nothing to undo")
    original = read_change_transaction(
        snapshot, protocol, state.undo_root, history=store.at
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
    state = history_state(snapshot, protocol, history_root, history=store.at)
    if state.redo_root is None:
        raise Conflict("nothing to redo")
    original = read_change_transaction(
        snapshot, protocol, state.redo_root, history=store.at
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
