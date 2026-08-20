"""Uniform physical substrate for the universal-cell migration.

This module is intentionally parallel to ``nodelang.core``.  It contains no
product concepts and assigns no semantic meaning to atom bytes or link
position.  Higher-level protocols must be represented by connected Cells.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
from collections.abc import MutableMapping
from types import MappingProxyType
import threading
import time
from typing import Callable, Iterable, Iterator, Mapping, Protocol
import uuid

from rpds import HashTrieMap


NULL_CELL_ID = "00000000-0000-0000-0000-000000000000"
_JOURNAL_REVISIONS_COLUMNS = frozenset(("revision", "committed_at"))
_JOURNAL_CELL_VERSION_COLUMNS = frozenset(
    ("revision", "cell_id", "link0", "link1", "atom")
)
_JOURNAL_CURRENT_CELL_COUNT_QUERY = "SELECT COUNT(*) FROM current_cells"


@dataclass(frozen=True, slots=True)
class Cell:
    """The only persisted semantic record in the V0 kernel."""

    id: str
    link0: str
    link1: str
    atom: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.atom, bytes):
            raise TypeError("terminal atom must be opaque bytes")


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Immutable process view of a committed cell graph."""

    revision: int
    cells: Mapping[str, Cell]


@dataclass(frozen=True, slots=True)
class ReadOnlyJournalRevision:
    """A bounded, non-owning view of one durable Cell journal revision.

    This record deliberately says nothing about graph semantics.  It exists
    for recovery preflights that must inspect a stopped journal without
    opening ``CellStore`` and therefore without acquiring its owner fence.
    """

    revision: int
    revision_count: int
    latest_revision_change_count: int


@dataclass(frozen=True, slots=True)
class RewriteResult:
    """Published identities from one generic structural rewrite."""

    root_id: str
    revision: int
    bindings: Mapping[str, str]
    materialized: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PreparedRewrite:
    """Unpublished Cells materialized from one generic structural rule."""

    root_id: str
    expected_revision: int
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]
    bindings: Mapping[str, str]
    materialized: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CommitEvent:
    """Post-commit notification; the graph revision is already durable."""

    revision: int
    touched: frozenset[str]


@dataclass(frozen=True, slots=True)
class CellHistoryMigrationEvidence:
    """Exact physical evidence for one quiesced journal migration."""

    source_identity: str
    destination_identity: str
    source_revision: int
    destination_revision: int
    revision_chain_digest: str


class CellKernelError(ValueError):
    """Base class for rejected physical-kernel operations."""


class Conflict(CellKernelError):
    """The caller attempted to commit against an obsolete revision."""


class InvalidCell(CellKernelError):
    """A cell or commit would violate the physical substrate invariants."""


class ReadOnlyJournalError(CellKernelError):
    """A durable journal cannot supply a bounded, read-only revision view."""


class NoMatch(CellKernelError):
    """A target graph does not have the supplied physical pattern shape."""


class MatchBudgetExceeded(CellKernelError):
    """Generic graph matching exhausted its explicit work budget."""


class DatabaseOwnerConflict(Conflict):
    """Another live CellStore already owns the durable database."""


class CellJournal(Protocol):
    """Storage-neutral physical journal below the four-field Cell floor."""

    identity: str
    backend: str
    local_path: str | None
    exclusive_owner: bool
    shared_writers: bool

    def load(
        self,
    ) -> tuple[
        Mapping[str, Cell],
        int,
        dict[int, tuple[Cell, ...]],
        dict[int, tuple[str, ...]],
    ]: ...

    def append(
        self,
        expected_revision: int,
        next_revision: int,
        changed: Iterable[Cell],
    ) -> None: ...

    def close(self) -> None: ...

    def backup_to(self, destination: str | os.PathLike[str]) -> str: ...

    def acquire_runtime_fence(
        self, resource_id: str
    ) -> Callable[[], None]: ...


class CellHistoryReader(Protocol):
    """Exact physical history reads bound to one accepted journal head."""

    @property
    def head_revision(self) -> int: ...

    @property
    def head_digest(self) -> str: ...

    def revision_cells(self, revision: int) -> tuple[Cell, ...]: ...

    def snapshot_at(self, revision: int) -> Snapshot: ...

    def cells_at(
        self, revision: int, cell_ids: Iterable[str]
    ) -> Mapping[str, Cell]: ...

    def created_revision(self, cell_id: str) -> int: ...

    def chain_digest(self, revision: int) -> str: ...

    def version_count(self) -> int: ...

    def advance(self, revision: int, changed: Iterable[Cell]) -> None: ...


@dataclass(frozen=True, slots=True)
class LoadedJournalHead:
    """One current graph and its same-head physical history reader."""

    cells: Mapping[str, Cell]
    revision: int
    revision_chain_digest: str
    history: CellHistoryReader


def _frozen_cells(cells: Mapping[str, Cell]) -> Mapping[str, Cell]:
    # A lazily read head is already an immutable value; copying it
    # would materialise the whole graph to publish one snapshot.
    if isinstance(cells, _LazyHeadCellMap):
        return cells
    return MappingProxyType(dict(cells))


_MAX_OVERLAY_DEPTH = 32


class _OverlayCellMap(Mapping[str, Cell]):
    """Immutable persistent map used to publish small commits cheaply."""

    __slots__ = ("_cells", "_created_count", "_depth")

    def __init__(self, base: Mapping[str, Cell], delta: Mapping[str, Cell]) -> None:
        persistent_base = (
            base._cells
            if isinstance(base, _OverlayCellMap)
            else base
            if isinstance(base, HashTrieMap)
            else HashTrieMap(base)
        )
        self._created_count = sum(1 for key in delta if key not in persistent_base)
        self._cells = persistent_base.update(delta)
        self._depth = 1

    def __getitem__(self, key: str) -> Cell:
        return self._cells[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._cells)

    def __len__(self) -> int:
        return len(self._cells)

    def __contains__(self, key: object) -> bool:
        return key in self._cells

    @classmethod
    def _from_trie(cls, trie: HashTrieMap) -> "_OverlayCellMap":
        """Wrap an already-built persistent trie (a stepped-back history)."""
        self = object.__new__(cls)
        self._cells = trie
        self._created_count = 0
        self._depth = 1
        return self


class _LazyHeadCellMap(Mapping[str, Cell]):
    """The head, read from the journal on demand instead of all at once.

    Opening the founder's graph materialised 5.75 million Cell objects
    before anything could be served: forty-six seconds of sqlite and
    twenty of object construction, every start, to answer questions about
    a few hundred of them. The head lives in the journal; this reads a row
    when someone asks for it and keeps what it read.

    Commits do not copy it. A commit publishes a new map sharing this
    reader with a persistent overlay trie, so a published revision stays
    an immutable value while costing one small update.

    ponytail: cache is unbounded per store. It only ever holds cells that
    were actually asked for; cap it if a session ever walks the whole graph.
    """

    __slots__ = ("_reader", "_overlay", "_base_count", "_created_count")

    def __init__(
        self,
        reader: "_HeadRowReader",
        overlay: "HashTrieMap | None" = None,
        base_count: int = 0,
        created_count: int = 0,
    ) -> None:
        self._reader = reader
        self._overlay = HashTrieMap() if overlay is None else overlay
        self._base_count = base_count
        self._created_count = created_count

    def with_delta(self, delta: Mapping[str, Cell]) -> "_LazyHeadCellMap":
        created = sum(1 for key in delta if key not in self)
        return _LazyHeadCellMap(
            self._reader,
            self._overlay.update(delta),
            self._base_count,
            self._created_count + created,
        )

    def prefetch(self, cell_ids) -> None:
        """Warm many cells at once; a no-op for what is already held."""
        self._reader.prefetch([
            key for key in cell_ids if key not in self._overlay
        ])

    def __getitem__(self, key: str) -> Cell:
        held = self._overlay.get(key)
        if held is not None:
            return held
        cell = self._reader.read(key)
        if cell is None:
            raise KeyError(key)
        return cell

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._overlay or self._reader.read(key) is not None

    def get(self, key, default=None):
        held = self._overlay.get(key)
        if held is not None:
            return held
        cell = self._reader.read(key) if isinstance(key, str) else None
        return default if cell is None else cell

    def __iter__(self) -> Iterator[str]:
        seen = set()
        for key in self._overlay:
            seen.add(key)
            yield key
        for key in self._reader.stream_ids():
            if key not in seen:
                yield key

    def __len__(self) -> int:
        # ponytail: counting five million rows is an audit's cost, not
        # every open's. Charged on the first ask and shared after.
        if self._base_count is None:
            self._base_count = self._reader.count()
        return self._base_count + self._created_count


class _LoadingHeadMap(MutableMapping):
    """The replay writes here; reads fall through to the lazy head.

    Not a dict subclass: C-level consumers (dict(), MappingProxyType,
    set.issubset) read a dict subclass's real entries and never call the
    overrides, which made a full head look empty while reporting five
    million entries.
    """

    __slots__ = ("_head", "_written")

    def __init__(self, head: "_LazyHeadCellMap") -> None:
        self._head = head
        self._written: dict[str, Cell] = {}

    def __getitem__(self, key):
        held = self._written.get(key)
        if held is not None:
            return held
        cell = self._head.get(key)
        if cell is None:
            raise KeyError(key)
        return cell

    def __setitem__(self, key, value) -> None:
        self._written[key] = value

    def __delitem__(self, key) -> None:
        del self._written[key]

    def __contains__(self, key) -> bool:
        return key in self._written or key in self._head

    def get(self, key, default=None):
        held = self._written.get(key)
        if held is not None:
            return held
        cell = self._head.get(key)
        return default if cell is None else cell

    def __iter__(self):
        seen = set(self._written)
        yield from self._written
        for key in self._head:
            if key not in seen:
                yield key

    def __len__(self) -> int:
        return len(self._head) + sum(
            1 for key in self._written if key not in self._head
        )

    def published(self) -> "_LazyHeadCellMap":
        """The immutable head this load produced."""
        return (
            self._head.with_delta(self._written) if self._written
            else self._head
        )


class _HeadRowReader:
    """One journal connection answering head reads, remembering what it read."""

    __slots__ = ("_connection", "_cache", "_missing")

    def __init__(self, connection) -> None:
        self._connection = connection
        self._cache: dict[str, Cell] = {}
        self._missing: set[str] = set()

    def read(self, cell_id: str) -> "Cell | None":
        held = self._cache.get(cell_id)
        if held is not None:
            return held
        if cell_id in self._missing:
            return None
        row = self._connection.execute(
            "SELECT link0, link1, atom FROM current_cells WHERE cell_id = ?",
            (cell_id,),
        ).fetchone()
        if row is None:
            self._missing.add(cell_id)
            return None
        cell = Cell(cell_id, str(row[0]), str(row[1]), bytes(row[2]))
        self._cache[cell_id] = cell
        return cell

    def prefetch(self, cell_ids) -> None:
        """Read many head rows in one statement.

        A walk that asks for half a million cells one query at a time
        spends its life in sqlite call overhead, not in sqlite.
        """
        wanted = [
            cell_id for cell_id in cell_ids
            if cell_id not in self._cache and cell_id not in self._missing
        ]
        for start in range(0, len(wanted), 800):
            batch = wanted[start:start + 800]
            rows = self._connection.execute(
                "SELECT cell_id, link0, link1, atom FROM current_cells "
                "WHERE cell_id IN (%s)" % ",".join("?" * len(batch)),
                batch,
            ).fetchall()
            seen = set()
            for cell_id, link0, link1, atom in rows:
                key = str(cell_id)
                seen.add(key)
                self._cache[key] = Cell(
                    key, str(link0), str(link1), bytes(atom)
                )
            for cell_id in batch:
                if cell_id not in seen:
                    self._missing.add(cell_id)

    def forget(self, cell_id: str) -> None:
        self._missing.discard(cell_id)

    def stream_ids(self) -> Iterator[str]:
        for (cell_id,) in self._connection.execute(
            "SELECT cell_id FROM current_cells"
        ):
            yield str(cell_id)

    def count(self) -> int:
        return int(self._connection.execute(
            "SELECT COUNT(*) FROM current_cells"
        ).fetchone()[0])


class _BoundedCandidateCellMap(Mapping[str, Cell]):
    """Read-only candidate overlay that never scans an external base mapping."""

    __slots__ = ("_base", "_created_count", "_delta")

    def __init__(self, base: Mapping[str, Cell], delta: Mapping[str, Cell]) -> None:
        self._base = base
        self._delta = MappingProxyType(dict(delta))
        self._created_count = sum(1 for key in delta if key not in base)

    @classmethod
    def _from_parts(
        cls,
        base: Mapping[str, Cell],
        delta: Mapping[str, Cell],
        created_count: int,
    ) -> "_BoundedCandidateCellMap":
        """Stack a delta a caller already holds and has already counted.

        The read overlay for derived interaction cells stacks the same
        826k-cell delta on every revision; copying and counting it per
        revision cost seconds per gesture. The caller owns the delta's
        identity and recomputes the count only when a commit touches one
        of its ids.
        """
        self = object.__new__(cls)
        self._base = base
        self._delta = delta
        self._created_count = int(created_count)
        return self

    def __getitem__(self, key: str) -> Cell:
        try:
            return self._delta[key]
        except KeyError:
            return self._base[key]

    def __iter__(self) -> Iterator[str]:
        yielded: set[str] = set()
        for key in self._base:
            yielded.add(key)
            yield key
        for key in self._delta:
            if key not in yielded:
                yield key

    def __len__(self) -> int:
        return len(self._base) + self._created_count

    def __contains__(self, key: object) -> bool:
        return key in self._delta or key in self._base


def _compact_cell_map(cells: Mapping[str, Cell]) -> Mapping[str, Cell]:
    """Materialize one dense immutable view without changing old snapshots."""
    return MappingProxyType(dict(cells))


def dense_read_snapshot(snapshot: Snapshot) -> Snapshot:
    """Return the already bounded immutable mapping for a dense read."""
    if type(snapshot) is not Snapshot:
        raise TypeError("dense read requires an exact Snapshot")
    return snapshot


def overlay_read_snapshot(
    snapshot: Snapshot,
    *,
    create: Iterable[Cell] = (),
    replace: Iterable[Cell] = (),
) -> Snapshot:
    """Project one immutable candidate revision without copying its base graph."""
    if type(snapshot) is not Snapshot:
        raise TypeError("overlay read requires an exact Snapshot")
    created = tuple(create)
    replaced = tuple(replace)
    for cell in created + replaced:
        _validate_cell(cell)
    create_ids = tuple(cell.id for cell in created)
    replace_ids = tuple(cell.id for cell in replaced)
    if (
        len(create_ids) != len(set(create_ids))
        or len(replace_ids) != len(set(replace_ids))
        or any(cell_id in snapshot.cells for cell_id in create_ids)
        or any(cell_id not in snapshot.cells for cell_id in replace_ids)
        or set(create_ids).intersection(replace_ids)
    ):
        raise InvalidCell("candidate patch has invalid Cell identities")
    if not created and not replaced:
        return Snapshot(snapshot.revision + 1, snapshot.cells)
    delta = {cell.id: cell for cell in created + replaced}
    cells = (
        _OverlayCellMap(snapshot.cells, delta)
        if isinstance(snapshot.cells, (_OverlayCellMap, HashTrieMap))
        or type(snapshot.cells) in {dict, MappingProxyType}
        else _BoundedCandidateCellMap(snapshot.cells, delta)
    )
    return Snapshot(snapshot.revision + 1, cells)


def _validate_cell(cell: Cell) -> None:
    if type(cell) is not Cell:
        raise InvalidCell("every persisted semantic record must be a Cell")
    if not isinstance(cell.id, str) or not cell.id:
        raise InvalidCell("cell identity must be a non-empty string")
    if not isinstance(cell.link0, str) or not isinstance(cell.link1, str):
        raise InvalidCell("physical links must be cell identities")
    if not isinstance(cell.atom, bytes):
        raise InvalidCell("terminal atom must be opaque bytes")


def revision_chain_digest_step(
    previous: bytes,
    revision: int,
    changed: Iterable[Cell],
) -> bytes:
    """Return the canonical digest after one exact physical revision."""
    if not isinstance(previous, bytes) or len(previous) != 32:
        raise InvalidCell("Cell revision digest predecessor is invalid")
    if type(revision) is not int or revision < 0:
        raise InvalidCell("Cell revision digest number is invalid")
    by_id: dict[str, Cell] = {}
    for cell in changed:
        _validate_cell(cell)
        if cell.id in by_id:
            raise InvalidCell("Cell revision contains duplicate identities")
        by_id[cell.id] = cell
    if not by_id:
        raise InvalidCell("Cell revision contains no changed Cells")
    digest = hashlib.sha256()
    domain = b"ArchHub/universal-cell-revision-chain/v1"
    digest.update(len(domain).to_bytes(8, "big"))
    digest.update(domain)
    digest.update(previous)
    raw_revision = str(revision).encode("ascii")
    digest.update(len(raw_revision).to_bytes(8, "big"))
    digest.update(raw_revision)
    for cell_id in sorted(by_id):
        cell = by_id[cell_id]
        for raw in (
            cell.id.encode("utf-8"),
            cell.link0.encode("utf-8"),
            cell.link1.encode("utf-8"),
            cell.atom,
        ):
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    return digest.digest()


class InterprocessOwnerFence:
    """Process-fatal-safe exclusive ownership of one physical resource."""

    _process_guard = threading.Lock()
    _process_paths: set[str] = set()

    def __init__(self, database_path: str) -> None:
        self._database_path = os.path.normcase(
            os.path.realpath(os.path.abspath(database_path))
        )
        self._lock_path = self._database_path + ".owner.lock"
        self._stream = None
        self._released = False
        with self._process_guard:
            if self._database_path in self._process_paths:
                # This exact process already holds the fence. Naming the
                # holder separates a caller bug from a real external owner;
                # one shared message for both costs hours of misdiagnosis.
                raise DatabaseOwnerConflict(
                    "Cell database is already owned by this same process "
                    "(pid %d): %s" % (os.getpid(), self._database_path)
                )
            self._process_paths.add(self._database_path)
        try:
            self._stream = open(self._lock_path, "a+b", buffering=0)
            self._ensure_lock_byte()
            self._acquire_os_lock()
        except Exception as exc:
            self._release_process_path()
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            if isinstance(exc, DatabaseOwnerConflict):
                raise
            raise DatabaseOwnerConflict(
                "Cell database owner fence could not be taken for %s: %s"
                % (self._database_path, exc)
            ) from exc

    def _ensure_lock_byte(self) -> None:
        self._stream.seek(0, os.SEEK_END)
        if self._stream.tell() == 0:
            self._stream.write(b"\0")
        self._stream.seek(0)

    def _acquire_os_lock(self) -> None:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise DatabaseOwnerConflict(
                    "Cell database is held by another live process; this "
                    "process (pid %d) cannot own it. The holder keeps the "
                    "OS lock on %s until it exits, so a supervisor must "
                    "either reuse the running owner or stop it first."
                    % (os.getpid(), self._lock_path)
                ) from exc
            return
        import fcntl

        try:
            fcntl.flock(
                self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except OSError as exc:
            raise DatabaseOwnerConflict(
                "Cell database is held by another live process; this "
                "process (pid %d) cannot own it. The holder keeps the "
                "OS lock on %s until it exits, so a supervisor must "
                "either reuse the running owner or stop it first."
                % (os.getpid(), self._lock_path)
            ) from exc

    def _release_process_path(self) -> None:
        with self._process_guard:
            self._process_paths.discard(self._database_path)

    def close(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            if self._stream is not None:
                if os.name == "nt":
                    import msvcrt

                    self._stream.seek(0)
                    msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._release_process_path()


class _SqliteJournal:
    """Durable implementation machinery; rows contain only Cell versions."""

    supports_lazy_history = True

    def __init__(
        self,
        path: str | os.PathLike[str],
        fault_injector: Callable[[str], None] | None,
    ) -> None:
        self._path = os.path.abspath(os.fspath(path))
        self._fault_injector = fault_injector
        self._owner_fence = InterprocessOwnerFence(self._path)
        self._connection = None
        try:
            self._connection = sqlite3.connect(
                self._path,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS revisions ("
                "revision INTEGER PRIMARY KEY, committed_at REAL NOT NULL)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS cell_versions ("
                "revision INTEGER NOT NULL, cell_id TEXT NOT NULL, "
                "link0 TEXT NOT NULL, link1 TEXT NOT NULL, atom BLOB NOT NULL, "
                "PRIMARY KEY (revision, cell_id), "
                "FOREIGN KEY (revision) REFERENCES revisions(revision))"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS current_cells ("
                "cell_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
                "link0 TEXT NOT NULL, link1 TEXT NOT NULL, atom BLOB NOT NULL, "
                "FOREIGN KEY (revision) REFERENCES revisions(revision))"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_cell_versions_cell_revision "
                "ON cell_versions(cell_id, revision DESC)"
            )
            # A chain checkpoint records the revision-chain digest at one
            # revision together with how many version rows lie at or before
            # it. History is append-only, so the prefix a checkpoint covers
            # cannot change; a later open re-verifies only the suffix and
            # seeds the chain from the checkpoint. A checkpoint that
            # disagrees with the rows it claims to cover is refused and the
            # full stream runs -- a proof cache, never an authority.
            # ...and it lives BESIDE the journal, not in it: the journal
            # holds one shape (revisions, cell_versions, current_cells --
            # SPEC court "everything persisted is one Cell shape"); a proof
            # cache is derivable, deletable, and never authority, so it
            # gets its own file. Deleting that file costs one full re-proof
            # and changes no meaning.
            self._accelerators().execute(
                "CREATE TABLE IF NOT EXISTS chain_checkpoints ("
                "revision INTEGER PRIMARY KEY, chain_digest BLOB NOT NULL, "
                "prefix_rows INTEGER NOT NULL)"
            )
            # Append-only is enforced by the storage layer, not assumed:
            # no statement may rewrite or remove a version row or a
            # revision. That is what lets the checkpoint and fingerprint
            # accelerators trust "same row count, same newest rowid" as
            # proof that covered rows are unchanged -- an in-place UPDATE
            # is refused before it can lie to them.
            #
            # Whether the fence was ALREADY there when this process arrived
            # is the fact the accelerators need: a file whose fence was
            # dropped and rewritten between two opens must not be trusted
            # just because this open re-created the fence. A brand-new
            # journal (no revisions yet) has nothing to have been rewritten.
            existing_triggers = {
                row[0] for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            self._fence_was_present = {
                "cell_versions_append_only_update",
                "cell_versions_append_only_delete",
                "revisions_append_only_update",
                "revisions_append_only_delete",
            }.issubset(existing_triggers) or (
                self._connection.execute(
                    "SELECT COUNT(*) FROM revisions"
                ).fetchone()[0] == 0
            )
            self._connection.execute(
                "CREATE TRIGGER IF NOT EXISTS cell_versions_append_only_update "
                "BEFORE UPDATE ON cell_versions BEGIN "
                "SELECT RAISE(ABORT, 'cell_versions is append-only'); END"
            )
            self._connection.execute(
                "CREATE TRIGGER IF NOT EXISTS cell_versions_append_only_delete "
                "BEFORE DELETE ON cell_versions BEGIN "
                "SELECT RAISE(ABORT, 'cell_versions is append-only'); END"
            )
            self._connection.execute(
                "CREATE TRIGGER IF NOT EXISTS revisions_append_only_update "
                "BEFORE UPDATE ON revisions BEGIN "
                "SELECT RAISE(ABORT, 'revisions is append-only'); END"
            )
            self._connection.execute(
                "CREATE TRIGGER IF NOT EXISTS revisions_append_only_delete "
                "BEFORE DELETE ON revisions BEGIN "
                "SELECT RAISE(ABORT, 'revisions is append-only'); END"
            )
            count = self._connection.execute(
                "SELECT COUNT(*) FROM revisions"
            ).fetchone()[0]
            if count == 0:
                null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    self._connection.execute(
                        "INSERT INTO revisions(revision, committed_at) "
                        "VALUES(0, ?)",
                        (time.time(),),
                    )
                    self._insert_versions(0, (null,))
                    self._upsert_current(0, (null,))
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise
            elif self._connection.execute(
                _JOURNAL_CURRENT_CELL_COUNT_QUERY
            ).fetchone()[0] == 0:
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    self._connection.execute(
                        "INSERT INTO current_cells(cell_id, revision, link0, link1, atom) "
                        "SELECT versions.cell_id, versions.revision, versions.link0, "
                        "versions.link1, versions.atom FROM cell_versions AS versions JOIN ("
                        "SELECT cell_id, MAX(revision) AS revision FROM cell_versions "
                        "GROUP BY cell_id) AS selected ON selected.cell_id = versions.cell_id "
                        "AND selected.revision = versions.revision"
                    )
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise
        except Exception:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._owner_fence.close()
            raise

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    def _insert_versions(self, revision: int, cells: Iterable[Cell]) -> None:
        self._connection.executemany(
            "INSERT INTO cell_versions"
            "(revision, cell_id, link0, link1, atom) VALUES(?, ?, ?, ?, ?)",
            (
                (revision, cell.id, cell.link0, cell.link1, cell.atom)
                for cell in cells
            ),
        )

    def _upsert_current(self, revision: int, cells: Iterable[Cell]) -> None:
        self._connection.executemany(
            "INSERT INTO current_cells(cell_id, revision, link0, link1, atom) "
            "VALUES(?, ?, ?, ?, ?) ON CONFLICT(cell_id) DO UPDATE SET "
            "revision=excluded.revision, link0=excluded.link0, "
            "link1=excluded.link1, atom=excluded.atom",
            (
                (cell.id, revision, cell.link0, cell.link1, cell.atom)
                for cell in cells
            ),
        )

    def load(
        self,
    ) -> tuple[
        Mapping[str, Cell],
        int,
        dict[int, tuple[Cell, ...]],
        dict[int, tuple[str, ...]],
    ]:
        current: dict[str, Cell] = {}
        versions: dict[int, tuple[Cell, ...]] = {}
        changes: dict[int, tuple[str, ...]] = {}
        revisions = self._connection.execute(
            "SELECT revision FROM revisions ORDER BY revision"
        ).fetchall()
        for (revision,) in revisions:
            rows = self._connection.execute(
                "SELECT cell_id, link0, link1, atom FROM cell_versions "
                "WHERE revision=? ORDER BY cell_id",
                (revision,),
            ).fetchall()
            changed = []
            for cell_id, link0, link1, atom in rows:
                cell = Cell(cell_id, link0, link1, bytes(atom))
                _validate_cell(cell)
                current[cell_id] = cell
                changed.append(cell)
            changes[revision] = tuple(row[0] for row in rows)
            versions[revision] = tuple(changed)
            for cell in changed:
                if cell.link0 not in current or cell.link1 not in current:
                    raise InvalidCell(
                        "durable revision %s has dangling incidence" % revision
                    )
        if not versions:
            raise InvalidCell("durable Cell journal has no revisions")
        latest = max(versions)
        return MappingProxyType(current), latest, versions, changes

    def load_head(self) -> LoadedJournalHead:
        """Read one same-transaction head and bounded history reader."""
        self._connection.execute("BEGIN")
        try:
            loaded = self._load_head_in_transaction()
            self._connection.commit()
            return loaded
        except Exception:
            self._connection.rollback()
            raise

    def _load_head_in_transaction(self) -> LoadedJournalHead:
        """Stream and validate history while retaining only the current graph."""
        current: dict[str, Cell] = {}
        current_revisions: dict[str, int] = {}
        revision_count, first_revision, latest = self._connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        if (
            type(revision_count) is not int
            or type(first_revision) is not int
            or type(latest) is not int
            or revision_count < 1
            or first_revision != 0
            or latest != revision_count - 1
        ):
            raise InvalidCell("durable Cell revision history is discontinuous")

        previous = b"\x00" * 32
        active_revision = -1
        changed: list[Cell] = []
        resume_after = -1
        checkpoint = self._accelerators().execute(
            "SELECT revision, chain_digest, prefix_rows FROM chain_checkpoints "
            "ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        if checkpoint is not None:
            checkpoint_revision, checkpoint_digest, prefix_rows = checkpoint
            # Without an index this count scans every version row on
            # every open. The index is an accelerator: dropping it costs
            # time, never meaning.
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cell_versions_revision "
                "ON cell_versions(revision)"
            )
            covered = self._connection.execute(
                "SELECT COUNT(*) FROM cell_versions WHERE revision <= ?",
                (int(checkpoint_revision),),
            ).fetchone()[0]
            # Genesis is the one revision whose content is fixed by the
            # protocol, so it is re-read on every open regardless of any
            # checkpoint: a forged genesis under an honest checkpoint would
            # otherwise pass. Prefix rows beyond genesis are guarded by the
            # accepted-proof fingerprint the authority layer keeps.
            genesis_rows = self._connection.execute(
                "SELECT cell_id, link0, link1, atom FROM cell_versions "
                "WHERE revision = 0"
            ).fetchall()
            genesis_honest = [
                (str(c), str(l0), str(l1), bytes(a))
                for c, l0, l1, a in genesis_rows
            ] == [(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")]
            fenced = bool(getattr(self, "_fence_was_present", False))
            if (
                fenced
                and genesis_honest
                and type(checkpoint_revision) is int
                and 0 <= checkpoint_revision <= latest
                and isinstance(checkpoint_digest, (bytes, memoryview))
                and len(bytes(checkpoint_digest)) == 32
                and int(covered) == int(prefix_rows)
            ):
                previous = bytes(checkpoint_digest)
                active_revision = int(checkpoint_revision)
                resume_after = int(checkpoint_revision)
                # The current cells at or before the checkpoint come from
                # the index the journal already keeps; only what changed
                # after the checkpoint is replayed as versions.
                # Every head row, not only those whose NEWEST version lies
                # at or before the checkpoint: a cell revised after the
                # checkpoint still existed at it, and a cell in the replayed
                # suffix may link to it before the suffix reaches its newest
                # version. Filtering by revision dropped exactly those cells
                # and a later removal's chain repair failed the dangling
                # check ("durable revision 1037 has dangling incidence") --
                # the graph would not load. The replay below re-applies the
                # suffix over the head rows; the chain digest is computed
                # from the streamed rows themselves, so the proof is unchanged.
                # The head is read on demand from this same connection.
                # Materialising it cost 46s of sqlite and 20s of object
                # construction on every open, to answer questions about a
                # few hundred cells.
                reader = _HeadRowReader(self._connection)
                lazy_head = _LazyHeadCellMap(reader, None, None, 0)
                current = _LoadingHeadMap(lazy_head)

        def accept_revision() -> None:
            nonlocal previous
            if not changed:
                raise InvalidCell(
                    "durable revision %s has no changed Cells"
                    % active_revision
                )
            if active_revision == 0 and changed != [
                Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
            ]:
                raise InvalidCell("durable Cell genesis revision is invalid")
            for cell in changed:
                current[cell.id] = cell
                current_revisions[cell.id] = active_revision
            for cell in changed:
                if cell.link0 not in current or cell.link1 not in current:
                    raise InvalidCell(
                        "durable revision %s has dangling incidence"
                        % active_revision
                    )
            previous = revision_chain_digest_step(
                previous,
                active_revision,
                changed,
            )

        rows = self._connection.execute(
            "SELECT revision, cell_id, link0, link1, atom "
            "FROM cell_versions WHERE revision > ? ORDER BY revision, cell_id",
            (resume_after,),
        )
        streamed_any = False
        for row_revision, cell_id, link0, link1, atom in rows:
            if type(row_revision) is not int:
                raise InvalidCell("durable Cell revision is invalid")
            if row_revision != active_revision:
                # A revision is accepted only once its rows were streamed
                # HERE; the checkpoint revision itself was accepted by the
                # load that recorded it and contributes no rows now.
                if active_revision >= 0 and streamed_any:
                    accept_revision()
                streamed_any = True
                if row_revision != active_revision + 1:
                    raise InvalidCell(
                        "durable Cell revision history is discontinuous"
                    )
                active_revision = row_revision
                changed = []
            cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            _validate_cell(cell)
            changed.append(cell)
        if active_revision >= 0 and streamed_any and changed:
            accept_revision()
        if active_revision != latest:
            raise InvalidCell("durable Cell journal has no complete head")
        # Record what this load proved, so the next open resumes here.
        # Written inside the same transaction as the load's reads: a
        # checkpoint at the head just verified is exactly the fact the
        # verification established.
        if latest > resume_after:
            self._accelerators().execute(
                "INSERT OR REPLACE INTO chain_checkpoints"
                "(revision, chain_digest, prefix_rows) VALUES(?, ?, ?)",
                (
                    latest,
                    previous,
                    int(self._connection.execute(
                        "SELECT COUNT(*) FROM cell_versions"
                    ).fetchone()[0]),
                ),
            )

        # The index audit proves current_cells == the replayed head. On a
        # checkpoint-resumed load the prefix of `current` was READ from
        # current_cells, so comparing it back is a table proving itself
        # -- 5.27M rows re-read and re-hashed on every open for nothing.
        # Only rows the streamed suffix touched can disagree; audit those,
        # plus the count, which catches a row the suffix never mentioned
        # but the index invented or lost.
        if resume_after < 0:
            audit_ids = None
        else:
            audit_ids = {
                cell_id for cell_id, revision in current_revisions.items()
                if revision > resume_after
            }
        if audit_ids is None:
            indexed = {
                str(cell_id): (
                    int(revision),
                    str(link0),
                    str(link1),
                    bytes(atom),
                )
                for cell_id, revision, link0, link1, atom
                in self._connection.execute(
                    "SELECT cell_id, revision, link0, link1, atom "
                    "FROM current_cells ORDER BY cell_id"
                )
            }
            expected = {
                cell_id: (
                    current_revisions[cell_id],
                    cell.link0,
                    cell.link1,
                    cell.atom,
                )
                for cell_id, cell in current.items()
            }
            if indexed != expected:
                raise InvalidCell("durable current Cell index is inconsistent")
        else:
            indexed_count = int(self._connection.execute(
                "SELECT COUNT(*) FROM current_cells"
            ).fetchone()[0])
            if indexed_count != len(current):
                raise InvalidCell("durable current Cell index is inconsistent")
            indexed_suffix = {}
            for cell_id in audit_ids:
                row = self._connection.execute(
                    "SELECT revision, link0, link1, atom FROM current_cells "
                    "WHERE cell_id = ?",
                    (cell_id,),
                ).fetchone()
                if row is not None:
                    indexed_suffix[cell_id] = (
                        int(row[0]), str(row[1]), str(row[2]), bytes(row[3]),
                    )
            expected_suffix = {
                cell_id: (
                    current_revisions[cell_id],
                    current[cell_id].link0,
                    current[cell_id].link1,
                    current[cell_id].atom,
                )
                for cell_id in audit_ids
            }
            if indexed_suffix != expected_suffix:
                raise InvalidCell("durable current Cell index is inconsistent")
        history = _SqliteHistoryReader(self, latest, previous.hex())
        return LoadedJournalHead(
            cells=MappingProxyType(current),
            revision=latest,
            revision_chain_digest=previous.hex(),
            history=history,
        )

    def append(
        self,
        expected_revision: int,
        next_revision: int,
        changed: Iterable[Cell],
    ) -> None:
        changed = tuple(changed)
        committed = False
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT MAX(revision) FROM revisions"
            ).fetchone()
            durable_revision = int(row[0])
            if durable_revision != expected_revision:
                raise Conflict(
                    "expected durable revision %s, current revision is %s"
                    % (expected_revision, durable_revision)
                )
            self._connection.execute(
                "INSERT INTO revisions(revision, committed_at) VALUES(?, ?)",
                (next_revision, time.time()),
            )
            self._insert_versions(next_revision, changed)
            self._upsert_current(next_revision, changed)
            self._fault("before_commit")
            self._connection.commit()
            committed = True
            self._fault("after_commit")
        except Exception:
            if not committed:
                self._connection.rollback()
            raise

    def _accelerators(self) -> sqlite3.Connection:
        """The proof-cache sidecar: '<journal>.accelerators'.

        Chain checkpoints and prefix fingerprints are facts a load already
        proved, kept so the next open can resume instead of re-proving.
        They hold no meaning the journal does not, so they do not share
        its file: the journal stays one Cell shape, and this file can be
        deleted at any time at the price of one full re-proof.
        """
        connection = getattr(self, "_accelerator_connection", None)
        if connection is None:
            connection = sqlite3.connect(
                self._path + ".accelerators",
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.execute("PRAGMA journal_mode=WAL")
            self._accelerator_connection = connection
        return connection

    def close(self) -> None:
        try:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            accelerators = getattr(self, "_accelerator_connection", None)
            if accelerators is not None:
                accelerators.close()
                self._accelerator_connection = None
        finally:
            self._owner_fence.close()

    @property
    def path(self) -> str:
        return self._path

    @property
    def identity(self) -> str:
        canonical = os.path.normcase(self._path).encode("utf-8")
        return "sqlite:sha256:" + hashlib.sha256(canonical).hexdigest()

    @property
    def backend(self) -> str:
        return "sqlite"

    @property
    def local_path(self) -> str:
        return self._path

    @property
    def exclusive_owner(self) -> bool:
        return True

    @property
    def shared_writers(self) -> bool:
        return False

    def backup_to(self, destination: str | os.PathLike[str]) -> str:
        """Create one transactionally consistent online SQLite backup."""
        target = os.path.abspath(os.fspath(destination))
        if target == self._path:
            raise InvalidCell("Cell backup destination equals its source")
        if os.path.exists(target):
            raise InvalidCell("Cell backup destination already exists")
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        backup = sqlite3.connect(target, isolation_level=None)
        try:
            self._connection.backup(backup)
            integrity = backup.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise InvalidCell("Cell backup failed SQLite integrity check")
        finally:
            backup.close()
        return target

    def acquire_runtime_fence(
        self, resource_id: str
    ) -> Callable[[], None]:
        """SQLite's process owner fence already covers every graph resource."""
        if not isinstance(resource_id, str) or not resource_id:
            raise InvalidCell("runtime fence resource identity is invalid")

        def release() -> None:
            return None

        return release


class _SqliteHistoryReader:
    """Exact SQLite history queries capped at one accepted Store head."""

    def __init__(
        self,
        journal: _SqliteJournal,
        head_revision: int,
        head_digest: str,
    ) -> None:
        self._journal = journal
        self._head_revision = head_revision
        self._head_digest = head_digest

    @property
    def head_revision(self) -> int:
        return self._head_revision

    @property
    def head_digest(self) -> str:
        return self._head_digest

    def _admit_revision(self, revision: int) -> int:
        if (
            type(revision) is not int
            or revision < 0
            or revision > self._head_revision
        ):
            raise InvalidCell("unknown revision %r" % revision)
        return revision

    def revision_cells(self, revision: int) -> tuple[Cell, ...]:
        target = self._admit_revision(revision)
        rows = self._journal._connection.execute(
            "SELECT cell_id, link0, link1, atom FROM cell_versions "
            "WHERE revision=? ORDER BY cell_id",
            (target,),
        )
        cells = tuple(
            Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            for cell_id, link0, link1, atom in rows
        )
        if not cells:
            raise InvalidCell("unknown revision %r" % revision)
        for cell in cells:
            _validate_cell(cell)
        return cells

    def snapshot_at(self, revision: int) -> Snapshot:
        target = self._admit_revision(revision)
        rows = self._journal._connection.execute(
            "SELECT versions.cell_id, versions.link0, versions.link1, "
            "versions.atom FROM cell_versions AS versions JOIN ("
            "SELECT cell_id, MAX(revision) AS revision FROM cell_versions "
            "WHERE revision<=? GROUP BY cell_id"
            ") AS selected ON selected.cell_id=versions.cell_id "
            "AND selected.revision=versions.revision ORDER BY versions.cell_id",
            (target,),
        )
        cells: dict[str, Cell] = {}
        for cell_id, link0, link1, atom in rows:
            cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            _validate_cell(cell)
            cells[cell.id] = cell
        if NULL_CELL_ID not in cells:
            raise InvalidCell("revision %s has no distinguished null Cell" % target)
        if any(
            cell.link0 not in cells or cell.link1 not in cells
            for cell in cells.values()
        ):
            raise InvalidCell("revision %s has dangling incidence" % target)
        return Snapshot(target, MappingProxyType(cells))

    def snapshot_stepped_back(self, later: Snapshot) -> Snapshot:
        """The snapshot one revision below one already in hand.

        Building a snapshot from scratch aggregates every version row in
        the store, so auditing a history downwards paid a full scan per
        revision -- a graph with six hundred revisions read itself six
        hundred times to start. Only the cells written at a revision
        differ across that step, and the store already knows which those
        are, so the step costs what actually changed.

        A cell written at this revision reverts to its newest version
        below; a cell first written here is simply gone. The result is
        checked as a whole, because dropping a cell can leave incidence
        dangling somewhere that did not change.
        """
        target = self._admit_revision(later.revision - 1)
        changed = [
            str(row[0])
            for row in self._journal._connection.execute(
                "SELECT DISTINCT cell_id FROM cell_versions WHERE revision=?",
                (later.revision,),
            )
        ]
        # A step down differs from the revision above by the cells that
        # revision wrote. Copying five million entries to change three
        # hundred made every audited head cost the whole graph again; a
        # persistent trie takes the same base and applies the delta. A
        # dense base is lifted into a trie once (a boot's first step) and
        # every step below it is then the size of its own change.
        base = later.cells
        if isinstance(base, _OverlayCellMap):
            trie = base._cells
        elif isinstance(base, HashTrieMap):
            trie = base
        else:
            trie = HashTrieMap(base)
        restored_cells: dict[str, Cell] = {}
        for start in range(0, len(changed), 500):
            selected = changed[start:start + 500]
            placeholders = ",".join("?" for _ in selected)
            rows = self._journal._connection.execute(
                "SELECT versions.cell_id, versions.link0, versions.link1, "
                "versions.atom FROM cell_versions AS versions JOIN ("
                "SELECT cell_id, MAX(revision) AS revision FROM cell_versions "
                "WHERE revision<=? AND cell_id IN (" + placeholders + ") "
                "GROUP BY cell_id"
                ") AS selected ON selected.cell_id=versions.cell_id "
                "AND selected.revision=versions.revision",
                (target, *selected),
            )
            for cell_id, link0, link1, atom in rows:
                cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
                _validate_cell(cell)
                restored_cells[cell.id] = cell
        restored = set()
        for start in range(0, len(changed), 500):
            selected = changed[start:start + 500]
            placeholders = ",".join("?" for _ in selected)
            restored.update(
                str(row[0])
                for row in self._journal._connection.execute(
                    "SELECT DISTINCT cell_id FROM cell_versions "
                    "WHERE revision<=? AND cell_id IN (" + placeholders + ")",
                    (target, *selected),
                )
            )
        removed = tuple(
            cell_id for cell_id in changed if cell_id not in restored
        )
        trie = trie.update(restored_cells)
        for cell_id in removed:
            trie = trie.discard(cell_id)
        cells = _OverlayCellMap._from_trie(trie)
        if NULL_CELL_ID not in cells:
            raise InvalidCell(
                "revision %s has no distinguished null Cell" % target
            )
        # Incidence can only dangle through what this step touched: a
        # restored version whose links no longer resolve, or a survivor
        # pointing at an id first created above. Every cell was checked
        # against the cells that existed when it was committed, and the
        # journal is append-only below this revision, so a survivor
        # cannot reference an id that did not yet exist. The restored
        # versions are checked here; the removed ids are asserted absent.
        if any(
            cell.link0 not in cells or cell.link1 not in cells
            for cell in restored_cells.values()
        ):
            raise InvalidCell("revision %s has dangling incidence" % target)
        if any(cell_id in cells for cell_id in removed):
            raise InvalidCell("revision %s retained a later cell" % target)
        return Snapshot(target, cells)

    def cells_at(
        self,
        revision: int,
        cell_ids: Iterable[str],
    ) -> Mapping[str, Cell]:
        target = self._admit_revision(revision)
        requested = tuple(dict.fromkeys(cell_ids))
        if not requested:
            return MappingProxyType({})
        out: dict[str, Cell] = {}
        for start in range(0, len(requested), 500):
            selected_ids = requested[start:start + 500]
            placeholders = ",".join("?" for _ in selected_ids)
            rows = self._journal._connection.execute(
                "SELECT versions.cell_id, versions.link0, versions.link1, "
                "versions.atom FROM cell_versions AS versions JOIN ("
                "SELECT cell_id, MAX(revision) AS revision FROM cell_versions "
                "WHERE revision<=? AND cell_id IN (" + placeholders + ") "
                "GROUP BY cell_id"
                ") AS selected ON selected.cell_id=versions.cell_id "
                "AND selected.revision=versions.revision",
                (target, *selected_ids),
            )
            for cell_id, link0, link1, atom in rows:
                cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
                _validate_cell(cell)
                out[cell.id] = cell
        for cell_id in requested:
            if cell_id not in out:
                raise InvalidCell(
                    "cell %r did not exist at revision %r"
                    % (cell_id, target)
                )
        return MappingProxyType({
            cell_id: out[cell_id]
            for cell_id in requested
        })

    def created_revision(self, cell_id: str) -> int:
        if not isinstance(cell_id, str) or not cell_id:
            raise InvalidCell("Cell identity is invalid")
        row = self._journal._connection.execute(
            "SELECT MIN(revision) FROM cell_versions "
            "WHERE cell_id=? AND revision<=?",
            (cell_id, self._head_revision),
        ).fetchone()
        if row is None or row[0] is None:
            raise InvalidCell("unknown cell %r" % cell_id)
        return int(row[0])

    def _append_only_fenced(self) -> bool:
        """Whether the storage layer refuses rewrites of history right now.

        The accelerators trust "same count, same newest rowid" only while
        an in-place rewrite is impossible. Anyone with raw file access can
        drop the triggers; then the accelerators must not trust counts,
        and every proof re-hashes the rows it covers.
        """
        return bool(getattr(self._journal, "_fence_was_present", False))

    def accepted_prefix_fingerprint(self, revision: int) -> tuple[int, int, str]:
        """Count, newest row, and content digest of the versions at or
        before one revision.

        A caller uses this to decide whether work it already did over that
        prefix still stands. Counting rows alone would answer yes to a
        history that was rewritten in place -- same number of rows, same
        newest row, different content -- so the digest covers what the rows
        actually say. Reading and hashing them straight from the table is
        under a second on the founder's graph, against the minutes it takes
        to rebuild and re-verify the same history as cells.
        """
        # "Under a second on the founder's graph" was true at 654 MB; at
        # 5.27M rows this re-hash was ~17s of every open, twice, re-proving
        # rows that are append-only. The digest of the rows at or before a
        # revision is a fixed fact once those rows exist: history is
        # append-only, so if the row count and the newest rowid for that
        # revision are unchanged, so is the digest. The triple is stored
        # durably beside the journal; a stale or foreign record fails the
        # count/newest gate and the full hash runs (once) and is recorded.
        # The digest FORMULA is unchanged, so every proof already recorded
        # by earlier opens still matches.
        connection = self._journal._connection
        accelerators = self._journal._accelerators()
        target = int(revision)
        accelerators.execute(
            "CREATE TABLE IF NOT EXISTS prefix_fingerprints ("
            "revision INTEGER PRIMARY KEY, rows INTEGER NOT NULL, "
            "newest INTEGER NOT NULL, digest TEXT NOT NULL)"
        )
        covered = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM cell_versions "
            "WHERE revision <= ?",
            (target,),
        ).fetchone()
        rows_now, newest_now = int(covered[0]), int(covered[1])
        held = accelerators.execute(
            "SELECT rows, newest, digest FROM prefix_fingerprints "
            "WHERE revision = ?",
            (target,),
        ).fetchone()
        if (
            held is not None
            and self._append_only_fenced()
            and int(held[0]) == rows_now
            and int(held[1]) == newest_now
            and isinstance(held[2], str) and len(held[2]) == 64
        ):
            return (rows_now, newest_now, held[2])
        rows = 0
        newest = 0
        content = hashlib.blake2b(digest_size=32)
        for row in connection.execute(
            "SELECT rowid, revision, cell_id, link0, link1, atom"
            " FROM cell_versions WHERE revision <= ? ORDER BY rowid",
            (target,),
        ):
            rows += 1
            newest = int(row[0])
            content.update(repr(row).encode("utf-8"))
        digest_hex = content.hexdigest()
        try:
            accelerators.execute(
                "INSERT OR REPLACE INTO prefix_fingerprints"
                "(revision, rows, newest, digest) VALUES(?, ?, ?, ?)",
                (target, rows, newest, digest_hex),
            )
        except sqlite3.Error:
            pass
        return (rows, newest, digest_hex)

    def chained_prefix_fingerprint(self, revision: int) -> tuple[int, int, str]:
        """Count, newest row, and a CHAINED content digest of the versions at
        or before one revision: digest(R) = blake2b(digest(R-1) || rows of R).

        The v1 prefix digest folds every row from the start, so recording a
        proof for a head that moved by eight commits re-hashed 5.28M rows
        (13-28 s at every boot that followed any work). Chaining by revision
        costs the rows of the revisions since the last recorded one. Each
        recorded link is trusted under the same gate as the other proof
        caches -- fence present, same count and newest rowid for its
        revision -- and a missing or untrusted link is recomputed from the
        nearest trusted one below it, or from the start.
        """
        connection = self._journal._connection
        accelerators = self._journal._accelerators()
        target = int(revision)
        accelerators.execute(
            "CREATE TABLE IF NOT EXISTS prefix_chain ("
            "revision INTEGER PRIMARY KEY, rows INTEGER NOT NULL, "
            "newest INTEGER NOT NULL, digest TEXT NOT NULL)"
        )
        fenced = self._append_only_fenced()

        def covered_at(rev):
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM cell_versions "
                "WHERE revision <= ?",
                (int(rev),),
            ).fetchone()
            return int(row[0]), int(row[1])

        rows_now, newest_now = covered_at(target)
        held = accelerators.execute(
            "SELECT rows, newest, digest FROM prefix_chain WHERE revision = ?",
            (target,),
        ).fetchone()
        if (
            held is not None and fenced
            and int(held[0]) == rows_now and int(held[1]) == newest_now
            and isinstance(held[2], str) and len(held[2]) == 64
        ):
            return (rows_now, newest_now, held[2])
        start_revision = -1
        previous = "0" * 64
        if fenced:
            links = accelerators.execute(
                "SELECT revision, rows, newest, digest FROM prefix_chain "
                "WHERE revision < ? ORDER BY revision DESC LIMIT 64",
                (target,),
            ).fetchall()
            for link_revision, link_rows, link_newest, link_digest in links:
                link_rows_now, link_newest_now = covered_at(link_revision)
                if (
                    link_rows_now == int(link_rows)
                    and link_newest_now == int(link_newest)
                    and isinstance(link_digest, str) and len(link_digest) == 64
                ):
                    start_revision = int(link_revision)
                    previous = link_digest
                    break
        # Carry the covered count and newest rowid forward link by link:
        # history is append-only below the target, so the rows at or
        # before R are the rows at or before R-1 plus the rows of R. Asking
        # the store to COUNT(rows <= R) for every link made the first chain
        # over 968 revisions scan 2.5 billion index entries (332 s).
        link_rows_now, link_newest_now = (
            covered_at(start_revision) if start_revision >= 0 else (0, 0)
        )
        for link_revision in range(start_revision + 1, target + 1):
            content = hashlib.blake2b(digest_size=32)
            content.update(b"ArchHub/prefix-chain/v2")
            content.update(previous.encode("ascii"))
            for row in connection.execute(
                "SELECT rowid, revision, cell_id, link0, link1, atom "
                "FROM cell_versions WHERE revision = ? ORDER BY rowid",
                (link_revision,),
            ):
                content.update(repr(row).encode("utf-8"))
                link_rows_now += 1
                if int(row[0]) > link_newest_now:
                    link_newest_now = int(row[0])
            previous = content.hexdigest()
            try:
                accelerators.execute(
                    "INSERT OR REPLACE INTO prefix_chain"
                    "(revision, rows, newest, digest) VALUES(?, ?, ?, ?)",
                    (link_revision, link_rows_now, link_newest_now, previous),
                )
            except sqlite3.Error:
                pass
        return (rows_now, newest_now, previous)

    def chain_digest(self, revision: int) -> str:
        target = self._admit_revision(revision)
        if target == self._head_revision:
            return self._head_digest
        previous = b"\x00" * 32
        active_revision = -1
        changed: list[Cell] = []
        rows = self._journal._connection.execute(
            "SELECT revision, cell_id, link0, link1, atom "
            "FROM cell_versions WHERE revision<=? ORDER BY revision, cell_id",
            (target,),
        )
        for row_revision, cell_id, link0, link1, atom in rows:
            row_revision = int(row_revision)
            if row_revision != active_revision:
                if active_revision >= 0:
                    previous = revision_chain_digest_step(
                        previous,
                        active_revision,
                        changed,
                    )
                if row_revision != active_revision + 1:
                    raise InvalidCell(
                        "durable Cell revision history is discontinuous"
                    )
                active_revision = row_revision
                changed = []
            changed.append(
                Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            )
        if active_revision >= 0:
            previous = revision_chain_digest_step(
                previous,
                active_revision,
                changed,
            )
        if active_revision != target:
            raise InvalidCell("unknown revision %r" % target)
        return previous.hex()

    def version_count(self) -> int:
        value = self._journal._connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision<=?",
            (self._head_revision,),
        ).fetchone()[0]
        return int(value)

    def advance(self, revision: int, changed: Iterable[Cell]) -> None:
        changed = tuple(changed)
        if revision != self._head_revision + 1:
            raise InvalidCell("durable history reader head changed")
        self._head_digest = revision_chain_digest_step(
            bytes.fromhex(self._head_digest),
            revision,
            changed,
        ).hex()
        self._head_revision = revision


def inspect_read_only_cell_journal(
    path: str | os.PathLike[str],
    *,
    max_revisions: int = 100_000,
    max_latest_revision_changes: int = 100_000,
) -> ReadOnlyJournalRevision:
    """Inspect one durable Cell revision without creating a CellStore owner.

    The SQLite connection is opened with ``mode=ro`` and ``query_only`` before
    a bounded read transaction.  This is intentionally a physical journal
    inspection, not a graph restore: callers receive only revision counts and
    cannot treat it as proof of Work, sessions, or authorization state.
    """
    if (
        type(max_revisions) is not int
        or max_revisions < 1
        or type(max_latest_revision_changes) is not int
        or max_latest_revision_changes < 1
    ):
        raise ReadOnlyJournalError("read-only journal inspection budget is invalid")
    connection = None
    try:
        database = Path(path).expanduser().resolve(strict=True)
        if not database.is_file():
            raise ReadOnlyJournalError("read-only journal path is not a file")
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        revisions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(revisions)")
        }
        cell_versions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(cell_versions)")
        }
        if revisions_columns != _JOURNAL_REVISIONS_COLUMNS or (
            cell_versions_columns != _JOURNAL_CELL_VERSION_COLUMNS
        ):
            raise ReadOnlyJournalError("read-only journal schema is unsupported")
        count, first_revision, latest_revision = connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        if type(count) is not int or count > max_revisions:
            raise ReadOnlyJournalError(
                "read-only journal revision history exceeds the inspection budget"
            )
        if (
            type(first_revision) is not int
            or type(latest_revision) is not int
            or count < 1
            or first_revision != 0
            or latest_revision != count - 1
        ):
            raise ReadOnlyJournalError("read-only journal revision history is invalid")
        null_count = connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision=0 AND cell_id=?",
            (NULL_CELL_ID,),
        ).fetchone()[0]
        latest_changes = connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision=?",
            (latest_revision,),
        ).fetchone()[0]
        if (
            type(latest_changes) is not int
            or latest_changes > max_latest_revision_changes
        ):
            raise ReadOnlyJournalError(
                "read-only journal latest revision exceeds the inspection budget"
            )
        if (
            type(null_count) is not int
            or null_count != 1
            or latest_changes < 1
        ):
            raise ReadOnlyJournalError("read-only journal Cell history is invalid")
        return ReadOnlyJournalRevision(
            revision=latest_revision,
            revision_count=count,
            latest_revision_change_count=latest_changes,
        )
    except ReadOnlyJournalError:
        raise
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ReadOnlyJournalError("read-only journal inspection is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def load_bounded_read_only_cell_snapshot(
    path: str | os.PathLike[str],
    *,
    max_revisions: int = 10_000,
    max_current_cells: int = 250_000,
    max_version_cells: int = 500_000,
) -> Snapshot:
    """Load one small durable graph without opening a ``CellStore`` owner.

    This is for independent authority artifacts such as a signing graph, never
    for the main application journal.  Callers must choose explicit caps; an
    oversized or malformed journal fails closed before Cells are materialized.
    """
    if any(
        type(value) is not int or value < 1
        for value in (max_revisions, max_current_cells, max_version_cells)
    ):
        raise ReadOnlyJournalError("read-only snapshot budget is invalid")
    connection = None
    try:
        database = Path(path).expanduser().resolve(strict=True)
        if not database.is_file():
            raise ReadOnlyJournalError("read-only journal path is not a file")
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        revisions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(revisions)")
        }
        cell_versions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(cell_versions)")
        }
        if revisions_columns != _JOURNAL_REVISIONS_COLUMNS or (
            cell_versions_columns != _JOURNAL_CELL_VERSION_COLUMNS
        ):
            raise ReadOnlyJournalError("read-only journal schema is unsupported")
        revision_count, first_revision, revision = connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        version_count = connection.execute(
            "SELECT COUNT(*) FROM cell_versions"
        ).fetchone()[0]
        if (
            type(revision_count) is not int
            or type(version_count) is not int
            or revision_count > max_revisions
            or version_count > max_version_cells
        ):
            raise ReadOnlyJournalError(
                "read-only snapshot exceeds the inspection budget"
            )
        if (
            type(first_revision) is not int
            or type(revision) is not int
            or revision_count < 1
            or first_revision != 0
            or revision != revision_count - 1
        ):
            raise ReadOnlyJournalError("read-only journal revision history is invalid")
        current_count = connection.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT cell_id, MAX(revision) FROM cell_versions GROUP BY cell_id"
            ")"
        ).fetchone()[0]
        if type(current_count) is not int or current_count > max_current_cells:
            raise ReadOnlyJournalError(
                "read-only snapshot exceeds the current-Cell budget"
            )
        rows = connection.execute(
            "SELECT versions.cell_id, versions.link0, versions.link1, versions.atom "
            "FROM cell_versions AS versions JOIN ("
            "SELECT cell_id, MAX(revision) AS revision "
            "FROM cell_versions GROUP BY cell_id"
            ") AS selected ON selected.cell_id = versions.cell_id "
            "AND selected.revision = versions.revision ORDER BY versions.cell_id"
        )
        cells: dict[str, Cell] = {}
        for cell_id, link0, link1, atom in rows:
            cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            _validate_cell(cell)
            cells[cell.id] = cell
        if len(cells) != current_count or NULL_CELL_ID not in cells:
            raise ReadOnlyJournalError("read-only snapshot Cell set is invalid")
        if any(
            cell.link0 not in cells or cell.link1 not in cells
            for cell in cells.values()
        ):
            raise ReadOnlyJournalError("read-only snapshot contains a dangling Cell")
        return Snapshot(revision, _frozen_cells(cells))
    except ReadOnlyJournalError:
        raise
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ReadOnlyJournalError("read-only snapshot is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def read_only_revision_chain_digest(
    path: str | os.PathLike[str],
    revision: int,
    *,
    max_revision_cells: int = 5_000_000,
) -> str:
    """Stream one durable revision-chain digest without opening ``CellStore``.

    The framing is exactly the normal journal digest.  Rows are streamed in
    primary-key order inside one read-only transaction, keeping memory bounded
    even when a trusted checkpoint covers many revisions.
    """
    if (
        type(revision) is not int
        or revision < 0
        or type(max_revision_cells) is not int
        or max_revision_cells < 1
    ):
        raise ReadOnlyJournalError("read-only digest request is invalid")
    connection = None
    try:
        database = Path(path).expanduser().resolve(strict=True)
        if not database.is_file():
            raise ReadOnlyJournalError("read-only journal path is not a file")
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        revision_count, first_revision, latest_revision = connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        if (
            type(revision_count) is not int
            or type(first_revision) is not int
            or type(latest_revision) is not int
            or revision_count < 1
            or first_revision != 0
            or latest_revision != revision_count - 1
            or revision > latest_revision
        ):
            raise ReadOnlyJournalError("read-only journal revision history is invalid")
        cell_count = connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision<=?", (revision,)
        ).fetchone()[0]
        if type(cell_count) is not int or cell_count > max_revision_cells:
            raise ReadOnlyJournalError(
                "read-only digest exceeds the revision-Cell budget"
            )
        previous = b"\x00" * 32
        current_revision = -1
        changed: list[Cell] = []
        rows = connection.execute(
            "SELECT revision, cell_id, link0, link1, atom FROM cell_versions "
            "WHERE revision<=? ORDER BY revision, cell_id",
            (revision,),
        )
        for row_revision, cell_id, link0, link1, atom in rows:
            if type(row_revision) is not int:
                raise ReadOnlyJournalError("read-only journal revision is invalid")
            if row_revision != current_revision:
                if row_revision != current_revision + 1:
                    raise ReadOnlyJournalError(
                        "read-only journal revision history is incomplete"
                    )
                if current_revision >= 0:
                    previous = revision_chain_digest_step(
                        previous,
                        current_revision,
                        changed,
                    )
                current_revision = row_revision
                changed = []
            changed.append(
                Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            )
        if current_revision != revision:
            raise ReadOnlyJournalError("read-only journal revision is missing")
        return revision_chain_digest_step(
            previous,
            current_revision,
            changed,
        ).hex()
    except ReadOnlyJournalError:
        raise
    except InvalidCell as exc:
        raise ReadOnlyJournalError(
            "read-only journal Cell history is invalid"
        ) from exc
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ReadOnlyJournalError("read-only digest is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


_RUNTIME_FENCE_LEASE_TOKEN = object()


class RuntimeFenceLease:
    """Opaque, process-local handoff for one already-held runtime fence."""

    __slots__ = (
        "_store",
        "_resource_id",
        "_release",
        "_consumed",
        "_released",
        "_lock",
    )

    def __init__(
        self,
        store: "CellStore",
        resource_id: str,
        release: Callable[[], None],
        *,
        _token: object,
    ) -> None:
        if _token is not _RUNTIME_FENCE_LEASE_TOKEN:
            raise InvalidCell("runtime fence lease cannot be constructed directly")
        self._store = store
        self._resource_id = resource_id
        self._release = release
        self._consumed = False
        self._released = False
        self._lock = threading.Lock()

    def consume(
        self,
        store: "CellStore",
        resource_id: str,
    ) -> Callable[[], None]:
        """Transfer this exact active fence to one runtime owner."""
        with self._lock:
            if self._consumed:
                raise InvalidCell("runtime fence lease was already consumed")
            if self._released:
                raise InvalidCell("runtime fence lease was already released")
            if store is not self._store:
                raise InvalidCell(
                    "runtime fence lease belongs to another CellStore"
                )
            if resource_id != self._resource_id:
                raise InvalidCell(
                    "runtime fence lease belongs to another resource"
                )
            self._consumed = True
            return self.close

    def close(self) -> None:
        """Release the physical fence once, before or after handoff."""
        with self._lock:
            if self._released:
                return
            self._released = True
            release = self._release
        release()


class CellStore:
    """Transactional Cell authority with immutable snapshots and journaling.

    Commits construct and validate a complete next mapping before one pointer
    swap publishes it. An optional SQLite journal preserves every committed
    revision and its incremental revision-chain digest across process restarts.
    """

    _HISTORICAL_CACHE_SIZE = 2
    # How far below the head at() walks by deltas before falling back to
    # one whole-store aggregate; a boot audit reaches the accepted floor,
    # which is however many revisions the last session committed.
    _STEP_BACK_LIMIT = 256
    _COPY_ON_COMMIT_CELL_LIMIT = 100_000

    def __init__(
        self,
        database_path: str | os.PathLike[str] | None = None,
        *,
        fault_injector: Callable[[str], None] | None = None,
        journal: CellJournal | None = None,
    ) -> None:
        if database_path is not None and journal is not None:
            raise InvalidCell(
                "CellStore accepts either database_path or journal, not both"
            )
        if journal is not None and fault_injector is not None:
            raise InvalidCell(
                "an injected Cell journal owns its own fault boundary"
            )
        self._lock = threading.RLock()
        self._journal: CellJournal | None = journal
        self._history_reader: CellHistoryReader | None = None
        if self._journal is None and database_path is not None:
            self._journal = _SqliteJournal(database_path, fault_injector)
        if self._journal is None:
            null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
            self._cells: Mapping[str, Cell] = _frozen_cells({NULL_CELL_ID: null})
            self._revision = 0
            self._versions: dict[int, tuple[Cell, ...]] = {0: (null,)}
            self._changes: dict[int, tuple[str, ...]] = {
                0: (NULL_CELL_ID,),
            }
        else:
            try:
                load_head = getattr(self._journal, "load_head", None)
                if (
                    getattr(self._journal, "supports_lazy_history", False)
                    and callable(load_head)
                ):
                    loaded = load_head()
                    self._validate_loaded_head(loaded)
                    self._cells = (
                        loaded.cells.published()
                        if isinstance(loaded.cells, _LoadingHeadMap)
                        else loaded.cells
                    )
                    self._revision = loaded.revision
                    self._history_reader = loaded.history
                    self._versions = {}
                    self._changes = {}
                else:
                    (
                        self._cells,
                        self._revision,
                        self._versions,
                        self._changes,
                    ) = self._journal.load()
            except Exception:
                self._journal.close()
                self._journal = None
                raise
        self._authority_identity = (
            self._journal.identity
            if self._journal is not None
            else "memory:" + uuid.uuid4().hex
        )
        self._historical_snapshots: OrderedDict[int, Snapshot] = OrderedDict()
        self._dense_snapshot_cache: Snapshot | None = None
        self._cell_history_index: dict[str, tuple[tuple[int, Cell], ...]] | None = None
        # revision -> additive set accumulator of the whole graph at that
        # revision (see cell_set_digest). Seeded by one full pass the first
        # time a caller asks; every commit moves it by exactly the cells it
        # writes; an audit stepping down a revision moves it by the cells
        # that revision wrote. Bounded: the audit only ever needs the
        # revision just above the one it is on.
        self._set_accumulators: OrderedDict[int, int] = OrderedDict()
        self._fingerprints: dict[tuple[str, frozenset[str]], str] = {}
        self._fingerprint_dependencies: dict[
            tuple[str, frozenset[str]], frozenset[str]
        ] = {}
        self._fingerprint_compute_counts: dict[
            tuple[str, frozenset[str]], int
        ] = {}
        self._listeners: set[Callable[[CommitEvent], None]] = set()
        self._listener_failures: list[str] = []
        self._revision_chain_digests: dict[int, bytes] = {}

    def close(self) -> None:
        with self._lock:
            if self._journal is not None:
                self._journal.close()
                self._journal = None

    @property
    def database_path(self) -> str | None:
        """Local SQLite path, or None for memory and remote authorities."""
        with self._lock:
            return (
                self._journal.local_path
                if self._journal is not None
                else None
            )

    @property
    def authority_identity(self) -> str:
        """Secret-free stable identity of this physical graph authority."""
        return self._authority_identity

    @property
    def durability_backend(self) -> str:
        """Physical persistence backend without semantic interpretation."""
        with self._lock:
            return (
                self._journal.backend
                if self._journal is not None
                else "memory"
            )

    @property
    def is_durable(self) -> bool:
        with self._lock:
            return self._journal is not None

    @property
    def has_exclusive_database_owner(self) -> bool:
        """Whether this live store holds the process-fatal-safe OS fence."""
        with self._lock:
            return bool(
                self._journal is not None
                and self._journal.exclusive_owner
            )

    @property
    def supports_shared_writers(self) -> bool:
        """Whether durable conflicts can originate in another process."""
        with self._lock:
            return bool(
                self._journal is not None
                and self._journal.shared_writers
            )

    def _adopt_journal_state(
        self,
        loaded: LoadedJournalHead | tuple[
                Mapping[str, Cell],
                int,
                dict[int, tuple[Cell, ...]],
                dict[int, tuple[str, ...]],
            ],
    ) -> None:
        if type(loaded) is LoadedJournalHead:
            self._validate_loaded_head(loaded)
            cells = loaded.cells
            revision = loaded.revision
            versions: dict[int, tuple[Cell, ...]] = {}
            changes: dict[int, tuple[str, ...]] = {}
            history_reader: CellHistoryReader | None = loaded.history
        else:
            cells, revision, versions, changes = loaded
            history_reader = None
        if revision < self._revision:
            raise InvalidCell("durable Cell authority moved backwards")
        self._cells = cells
        self._revision = revision
        self._versions = versions
        self._changes = changes
        self._history_reader = history_reader
        self._historical_snapshots.clear()
        self._dense_snapshot_cache = None
        self._cell_history_index = None
        self._fingerprints.clear()
        self._fingerprint_dependencies.clear()
        self._fingerprint_compute_counts.clear()
        self._revision_chain_digests.clear()

    @staticmethod
    def _validate_loaded_head(loaded: LoadedJournalHead) -> None:
        if type(loaded) is not LoadedJournalHead:
            raise InvalidCell("durable journal head shape is invalid")
        if (
            type(loaded.revision) is not int
            or loaded.revision < 0
            or loaded.history.head_revision != loaded.revision
            or not hmac.compare_digest(
                loaded.history.head_digest,
                loaded.revision_chain_digest,
            )
            or not hmac.compare_digest(
                loaded.history.chain_digest(loaded.revision),
                loaded.revision_chain_digest,
            )
        ):
            raise InvalidCell("durable journal head evidence is inconsistent")

    def _load_journal_state(
        self,
    ) -> LoadedJournalHead | tuple[
        Mapping[str, Cell],
        int,
        dict[int, tuple[Cell, ...]],
        dict[int, tuple[str, ...]],
    ]:
        if self._journal is None:
            raise InvalidCell("durable Cell journal is unavailable")
        load_head = getattr(self._journal, "load_head", None)
        if (
            getattr(self._journal, "supports_lazy_history", False)
            and callable(load_head)
        ):
            loaded = load_head()
            self._validate_loaded_head(loaded)
            return loaded
        return self._journal.load()

    def refresh(self) -> int:
        """Adopt the latest accepted revision from a shared authority."""
        with self._lock:
            if self._journal is None:
                return self._revision
            self._adopt_journal_state(self._load_journal_state())
            return self._revision

    def acquire_runtime_fence(
        self, resource_id: str
    ) -> Callable[[], None]:
        """Hold one physical runtime fence while graph ownership is active."""
        if not isinstance(resource_id, str) or not resource_id:
            raise InvalidCell("runtime fence resource identity is invalid")

        def no_op_release() -> None:
            return None

        with self._lock:
            if self._journal is None:
                return no_op_release
            if not self._journal.shared_writers:
                if not self._journal.exclusive_owner:
                    raise InvalidCell(
                        "durable authority has no admitted ownership fence"
                    )
                return no_op_release
            acquire = getattr(self._journal, "acquire_runtime_fence", None)
            if not callable(acquire):
                raise InvalidCell(
                    "shared durable authority has no runtime fence"
                )
            release = acquire(resource_id)
            if not callable(release):
                raise InvalidCell("runtime fence did not return a release")
            return release

    def prepare_runtime_fence(self, resource_id: str) -> RuntimeFenceLease:
        """Acquire one physical fence for an exact startup handoff."""
        return RuntimeFenceLease(
            self,
            resource_id,
            self.acquire_runtime_fence(resource_id),
            _token=_RUNTIME_FENCE_LEASE_TOKEN,
        )

    def backup_to(self, destination: str | os.PathLike[str]) -> str:
        """Invoke the physical backend's explicit recovery operation."""
        with self._lock:
            if self._journal is None:
                raise InvalidCell("an in-memory CellStore has no SQLite backup")
            return self._journal.backup_to(destination)

    def __enter__(self) -> "CellStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def read(self, cell_id: str, *, revision: int | None = None) -> Cell:
        with self._lock:
            source = self._cells if revision is None else self.at(revision).cells
            return source[cell_id]

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(self._revision, self._cells)

    def dense_snapshot(self) -> Snapshot:
        """Return the current revision in its bounded immutable read mapping.

        Persistent revisions already provide bounded identity lookup, so a
        dense reader must not copy the complete Cell map. The Store and every
        previously published Snapshot remain unchanged.
        """
        with self._lock:
            cached = self._dense_snapshot_cache
            if cached is not None and cached.revision == self._revision:
                return cached
            snapshot = dense_read_snapshot(Snapshot(self._revision, self._cells))
            self._dense_snapshot_cache = snapshot
            return snapshot

    def accepted_prefix_fingerprint(self, revision: int) -> tuple[int, int, str]:
        """Ask the history reader for the immutable prefix fingerprint."""
        with self._lock:
            reader = self._history_reader
        counter = getattr(reader, "accepted_prefix_fingerprint", None)
        if counter is None:
            return (0, 0, "")
        return counter(revision)

    def chained_prefix_fingerprint(self, revision: int) -> tuple[int, int, str]:
        """Ask the history reader for the chained (v2) prefix fingerprint."""
        with self._lock:
            reader = self._history_reader
        counter = getattr(reader, "chained_prefix_fingerprint", None)
        if counter is None:
            return (0, 0, "")
        return counter(revision)

    def at(self, revision: int) -> Snapshot:
        with self._lock:
            if revision == self._revision:
                return Snapshot(self._revision, self._cells)
            cached = self._historical_snapshots.get(revision)
            if cached is not None:
                self._historical_snapshots.move_to_end(revision)
                return cached
            if self._history_reader is not None:
                # Auditing a history walks downwards one revision at a
                # time. When the revision above is already in hand, the
                # step below it is a delta, not another whole scan.
                above = None
                if revision + 1 == self._revision:
                    above = Snapshot(self._revision, self._cells)
                else:
                    above = self._historical_snapshots.get(revision + 1)
                step_back = getattr(
                    self._history_reader, "snapshot_stepped_back", None
                )
                if above is not None and step_back is not None:
                    snapshot = step_back(above)
                elif (
                    step_back is not None
                    and 0 < self._revision - revision <= self._STEP_BACK_LIMIT
                ):
                    # No neighbour in hand, but the head is near: walk down
                    # from it. Each step costs the cells its revision wrote;
                    # the aggregate query below costs every version row in
                    # the store (measured 74 s on the founder's graph for a
                    # floor eight revisions under the head).
                    cursor = Snapshot(self._revision, self._cells)
                    for target in range(self._revision - 1, revision - 1, -1):
                        held = self._historical_snapshots.get(target)
                        cursor = held if held is not None else step_back(cursor)
                        self._historical_snapshots[target] = cursor
                        self._historical_snapshots.move_to_end(target)
                    snapshot = cursor
                else:
                    snapshot = self._history_reader.snapshot_at(revision)
                self._historical_snapshots[revision] = snapshot
                while (
                    len(self._historical_snapshots)
                    > self._HISTORICAL_CACHE_SIZE
                ):
                    self._historical_snapshots.popitem(last=False)
                return snapshot
            if revision not in self._versions:
                raise InvalidCell("unknown revision %r" % revision)
            previous_cached_revision = None
            for candidate in self._historical_snapshots:
                if candidate < revision and (
                    previous_cached_revision is None
                    or candidate > previous_cached_revision
                ):
                    previous_cached_revision = candidate
            if previous_cached_revision is None:
                reconstructed: dict[str, Cell] = {}
                start_revision = 0
            else:
                previous = self._historical_snapshots[previous_cached_revision]
                self._historical_snapshots.move_to_end(previous_cached_revision)
                reconstructed = dict(previous.cells)
                start_revision = previous_cached_revision + 1
            touched_since_base: set[str] = set()
            for current_revision in range(start_revision, revision + 1):
                try:
                    changed = self._versions[current_revision]
                except KeyError as exc:
                    raise InvalidCell(
                        "revision history is discontinuous at %r"
                        % current_revision
                    ) from exc
                for cell in changed:
                    reconstructed[cell.id] = cell
                    touched_since_base.add(cell.id)
            frozen = MappingProxyType(reconstructed)
            for cell_id in touched_since_base:
                cell = frozen[cell_id]
                if cell.link0 not in frozen or cell.link1 not in frozen:
                    raise InvalidCell(
                        "revision %s has dangling incidence" % revision
                    )
            snapshot = Snapshot(revision, frozen)
            self._historical_snapshots[revision] = snapshot
            while (
                len(self._historical_snapshots)
                > self._HISTORICAL_CACHE_SIZE
            ):
                self._historical_snapshots.popitem(last=False)
            return snapshot

    def revisions(self) -> tuple[int, ...]:
        """Return every retained immutable revision in journal order."""
        with self._lock:
            if self._history_reader is not None:
                return tuple(range(self._revision + 1))
            return tuple(sorted(self._versions))

    def revision_changes(self, revision: int) -> tuple[str, ...]:
        """Return the exact Cell identities changed by one retained revision."""
        with self._lock:
            if self._history_reader is not None:
                return tuple(
                    cell.id
                    for cell in self._history_reader.revision_cells(revision)
                )
            try:
                return self._changes[revision]
            except KeyError as exc:
                raise InvalidCell("unknown revision %r" % revision) from exc

    def cells_at(
        self, revision: int, cell_ids: Iterable[str]
    ) -> Mapping[str, Cell]:
        """Return selected Cell versions at a revision without a full snapshot."""
        requested = tuple(dict.fromkeys(cell_ids))
        with self._lock:
            if revision == self._revision:
                try:
                    return MappingProxyType({
                        cell_id: self._cells[cell_id]
                        for cell_id in requested
                    })
                except KeyError as exc:
                    raise InvalidCell("unknown cell %r" % (exc.args[0],)) from exc
            if self._history_reader is not None:
                return self._history_reader.cells_at(revision, requested)
            if revision not in self._versions:
                raise InvalidCell("unknown revision %r" % revision)
            if self._cell_history_index is None:
                history: dict[str, list[tuple[int, Cell]]] = {}
                for rev in sorted(self._versions):
                    for cell in self._versions[rev]:
                        history.setdefault(cell.id, []).append((rev, cell))
                self._cell_history_index = {
                    cell_id: tuple(entries)
                    for cell_id, entries in history.items()
                }
            out: dict[str, Cell] = {}
            for cell_id in requested:
                entries = self._cell_history_index.get(cell_id)
                if not entries:
                    raise InvalidCell("unknown cell %r" % cell_id)
                revisions = tuple(rev for rev, _cell in entries)
                index = bisect_right(revisions, revision) - 1
                if index < 0:
                    raise InvalidCell(
                        "cell %r did not exist at revision %r"
                        % (cell_id, revision)
                    )
                out[cell_id] = entries[index][1]
            return MappingProxyType(out)

    def cell_created_revision(self, cell_id: str) -> int:
        """Return the immutable journal revision that first created a Cell."""
        with self._lock:
            if cell_id not in self._cells:
                raise InvalidCell("unknown cell %r" % cell_id)
            if self._history_reader is not None:
                return self._history_reader.created_revision(cell_id)
            for revision in sorted(self._versions):
                if any(
                    cell.id == cell_id
                    for cell in self._versions[revision]
                ):
                    return revision
            raise InvalidCell("cell creation revision is missing")

    def retention_stats(self) -> Mapping[str, int]:
        """Expose bounded physical retention without interpreting the graph."""
        with self._lock:
            version_count = (
                self._history_reader.version_count()
                if self._history_reader is not None
                else sum(
                    len(changed)
                    for changed in self._versions.values()
                )
            )
            revision_count = (
                self._revision + 1
                if self._history_reader is not None
                else len(self._versions)
            )
            return MappingProxyType({
                "revision_count": revision_count,
                "current_cell_count": len(self._cells),
                "version_cell_count": version_count,
                "resident_history_version_cell_count": sum(
                    len(changed) for changed in self._versions.values()
                ),
                "historical_snapshot_count": len(
                    self._historical_snapshots
                ),
                "historical_snapshot_cell_count": sum(
                    len(snapshot.cells)
                    for snapshot in self._historical_snapshots.values()
                ),
            })

    def revision_chain_digest(self, revision: int | None = None) -> str:
        """Commit to every changed Cell record from genesis through revision."""
        with self._lock:
            target = self._revision if revision is None else revision
            if self._history_reader is not None:
                return self._history_reader.chain_digest(target)
            if target not in self._versions:
                raise InvalidCell("unknown revision %r" % target)
            previous = b"\x00" * 32
            start = 0
            cached = tuple(
                value for value in self._revision_chain_digests if value <= target
            )
            if cached:
                last = max(cached)
                previous = self._revision_chain_digests[last]
                start = last + 1
            for current_revision in range(start, target + 1):
                changed = {
                    cell.id: cell for cell in self._versions[current_revision]
                }
                ordered = tuple(
                    changed[root_id]
                    for root_id in self._changes[current_revision]
                )
                previous = revision_chain_digest_step(
                    previous,
                    current_revision,
                    ordered,
                )
                self._revision_chain_digests[current_revision] = previous
            return previous.hex()

    def subscribe(
        self,
        listener: Callable[[CommitEvent], None],
    ) -> Callable[[], None]:
        """Register a post-commit listener and return an idempotent remover."""
        if not callable(listener):
            raise TypeError("commit listener must be callable")
        with self._lock:
            self._listeners.add(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe

    def listener_failures(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._listener_failures)

    def commit(
        self,
        expected_revision: int,
        *,
        create: Iterable[Cell] = (),
        replace: Iterable[Cell] = (),
        precommit_guard: Callable[[], None] | None = None,
    ) -> int:
        created = tuple(create)
        replaced = tuple(replace)
        listeners: tuple[Callable[[CommitEvent], None], ...]
        event: CommitEvent
        with self._lock:
            if expected_revision != self._revision:
                raise Conflict(
                    "expected revision %s, current revision is %s"
                    % (expected_revision, self._revision)
                )

            base = self._cells
            if (
                isinstance(base, _OverlayCellMap)
                and base._depth >= _MAX_OVERLAY_DEPTH
            ):
                base = _compact_cell_map(base)
            delta: dict[str, Cell] = {}
            touched: set[str] = set()

            for cell in created:
                _validate_cell(cell)
                if cell.id in base or cell.id in touched:
                    raise InvalidCell("cannot create existing cell %r" % cell.id)
                touched.add(cell.id)
                delta[cell.id] = cell

            for cell in replaced:
                _validate_cell(cell)
                if cell.id == NULL_CELL_ID:
                    raise InvalidCell("the distinguished null cell is immutable")
                if cell.id not in base:
                    raise InvalidCell("cannot replace missing cell %r" % cell.id)
                if cell.id in touched:
                    raise InvalidCell("cell %r is changed twice in one commit" % cell.id)
                touched.add(cell.id)
                delta[cell.id] = cell

            if not touched:
                raise InvalidCell("empty commits are not transactions")

            for cell_id in touched:
                cell = delta[cell_id]
                if (
                    cell.link0 not in delta and cell.link0 not in base
                ) or (
                    cell.link1 not in delta and cell.link1 not in base
                ):
                    raise InvalidCell("cell %r contains a dangling physical link" % cell.id)

            next_revision = self._revision + 1
            # The accumulator of the next revision is this one's, less
            # the versions being replaced, plus every cell being written.
            # Computed here, from base, so the head digest a signer asks
            # for after this commit costs the cells this commit wrote.
            next_accumulator = None
            held_accumulator = self._set_accumulators.get(self._revision)
            if held_accumulator is not None:
                from .cell_set_digest import (
                    accumulator_add, accumulator_remove,
                )
                next_accumulator = accumulator_add(
                    accumulator_remove(
                        held_accumulator,
                        (base[cell.id] for cell in replaced),
                    ),
                    delta.values(),
                )
            if isinstance(base, _LazyHeadCellMap):
                published = base.with_delta(delta)
            elif len(base) <= self._COPY_ON_COMMIT_CELL_LIMIT:
                candidate = dict(base)
                candidate.update(delta)
                published = MappingProxyType(candidate)
            else:
                published = _OverlayCellMap(base, delta)
            if precommit_guard is not None:
                if not callable(precommit_guard):
                    raise TypeError("Cell commit guard must be callable")
                precommit_guard()
            snapshot = Snapshot(next_revision, published)
            if self._journal is not None:
                try:
                    self._journal.append(
                        expected_revision,
                        next_revision,
                        tuple(created) + tuple(replaced),
                    )
                except Conflict:
                    self._adopt_journal_state(self._load_journal_state())
                    raise
            self._cells = published
            self._revision = next_revision
            self._dense_snapshot_cache = None
            if next_accumulator is not None:
                self._remember_set_accumulator(next_revision, next_accumulator)
                self._record_set_accumulator(
                    next_revision, next_accumulator,
                    written=len(created) + len(replaced),
                )
            changed = tuple(created) + tuple(replaced)
            if self._history_reader is not None:
                self._history_reader.advance(next_revision, changed)
            else:
                self._versions[next_revision] = changed
                self._changes[next_revision] = tuple(sorted(touched))
            self._cell_history_index = None
            for cache_key, dependencies in tuple(
                self._fingerprint_dependencies.items()
            ):
                if touched.intersection(dependencies):
                    self._fingerprints.pop(cache_key, None)
                    self._fingerprint_dependencies.pop(cache_key, None)
            event = CommitEvent(next_revision, frozenset(touched))
            listeners = tuple(self._listeners)

        for listener in listeners:
            try:
                listener(event)
            except Exception as exc:
                with self._lock:
                    self._listener_failures.append(
                        "%s: %s" % (type(exc).__name__, exc)
                    )
                    if len(self._listener_failures) > 100:
                        del self._listener_failures[:-100]
        return next_revision

    _SET_ACCUMULATOR_CACHE_SIZE = 8

    def _remember_set_accumulator(self, revision: int, accumulator: int) -> None:
        self._set_accumulators[revision] = accumulator
        self._set_accumulators.move_to_end(revision)
        while len(self._set_accumulators) > self._SET_ACCUMULATOR_CACHE_SIZE:
            self._set_accumulators.popitem(last=False)

    def _changed_at(self, revision: int) -> tuple[Cell, ...]:
        """The versions written at one revision, as this store records them."""
        if self._history_reader is not None:
            return self._history_reader.revision_cells(revision)
        held = self._versions.get(revision)
        if held is None:
            raise InvalidCell("unknown revision %r" % revision)
        return tuple(held)

    def set_accumulator(self, snapshot: Snapshot) -> int:
        """The additive set accumulator of exactly this store snapshot.

        The head revision seeds by one full pass the first time it is asked
        for, and each commit then moves it by what it wrote. A historical
        snapshot one below a revision already in hand is derived by
        undoing that revision -- subtract the versions it wrote, add back
        the versions those cells held before, which the historical
        snapshot itself carries. Anything else pays the full pass over the
        snapshot handed in. Every path is exact for the snapshot given;
        none trusts a stored number for content it did not hash.
        """
        from .cell_set_digest import (
            accumulator_add, accumulator_remove, set_accumulator,
        )
        with self._lock:
            revision = snapshot.revision
            is_current = revision == self._revision
            if is_current and snapshot.cells is not self._cells:
                # A foreign mapping claiming the head revision is hashed
                # for real, never answered from the head's cache.
                return set_accumulator(snapshot.cells.values())
            held = self._set_accumulators.get(revision)
            if held is not None:
                self._set_accumulators.move_to_end(revision)
                return held
            above = self._set_accumulators.get(revision + 1)
            if above is not None and revision + 1 <= self._revision:
                written = self._changed_at(revision + 1)
                restored = tuple(
                    snapshot.cells[cell.id]
                    for cell in written
                    if cell.id in snapshot.cells
                )
                accumulator = accumulator_add(
                    accumulator_remove(above, written), restored
                )
            else:
                accumulator = self._recorded_set_accumulator(revision)
                if accumulator is None:
                    accumulator = set_accumulator(snapshot.cells.values())
                    self._record_set_accumulator(revision, accumulator)
            self._remember_set_accumulator(revision, accumulator)
            return accumulator

    def _recorded_set_accumulator(self, revision: int) -> int | None:
        """The accumulator a previous process left for this revision.

        Trusted under exactly the gate the other proof caches use: the
        storage layer refuses rewrites (fence present) and the rows at or
        before the revision are the same count with the same newest rowid.
        A raw-file rewrite under an intact fence is outside this model, as
        it is for the chain checkpoints; deleting the sidecar costs one full
        pass and changes no meaning.
        """
        journal = self._journal
        if journal is None or not getattr(journal, "_fence_was_present", False):
            return None
        try:
            accelerators = journal._accelerators()
            accelerators.execute(
                "CREATE TABLE IF NOT EXISTS set_accumulators ("
                "revision INTEGER PRIMARY KEY, rows INTEGER NOT NULL, "
                "newest INTEGER NOT NULL, accumulator BLOB NOT NULL)"
            )
            held = accelerators.execute(
                "SELECT rows, newest, accumulator FROM set_accumulators "
                "WHERE revision = ?",
                (int(revision),),
            ).fetchone()
            if held is None:
                return None
            covered = journal._connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM cell_versions "
                "WHERE revision <= ?",
                (int(revision),),
            ).fetchone()
            if int(held[0]) != int(covered[0]) or int(held[1]) != int(covered[1]):
                return None
            raw = bytes(held[2])
            from .cell_set_digest import SET_HASH_BYTES
            if len(raw) != SET_HASH_BYTES:
                return None
            return int.from_bytes(raw, "big")
        except sqlite3.Error:
            return None

    def _record_set_accumulator(
        self, revision: int, accumulator: int, *, written: int | None = None,
    ) -> None:
        """Leave the accumulator for one revision beside the journal.

        The covered-row count and newest rowid gate its reuse. Counting the
        rows at or before the revision is an index scan over the whole
        journal -- 0.7 s of every 1.2 s pan on the founder's graph -- so the
        count is carried forward from the previous record (rows + what this
        commit wrote; newest = the newest row of this revision, an indexed
        range) and only a record with no predecessor in hand counts.
        """
        journal = self._journal
        if journal is None:
            return
        try:
            from .cell_set_digest import SET_HASH_BYTES
            accelerators = journal._accelerators()
            accelerators.execute(
                "CREATE TABLE IF NOT EXISTS set_accumulators ("
                "revision INTEGER PRIMARY KEY, rows INTEGER NOT NULL, "
                "newest INTEGER NOT NULL, accumulator BLOB NOT NULL)"
            )
            held = getattr(self, "_set_accumulator_cover", None)
            if (
                written is not None
                and held is not None
                and held[0] == int(revision) - 1
            ):
                newest_row = journal._connection.execute(
                    "SELECT COALESCE(MAX(rowid), 0) FROM cell_versions "
                    "WHERE revision = ?",
                    (int(revision),),
                ).fetchone()
                covered = (held[1] + int(written), max(held[2], int(newest_row[0])))
            else:
                counted = journal._connection.execute(
                    "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM cell_versions "
                    "WHERE revision <= ?",
                    (int(revision),),
                ).fetchone()
                covered = (int(counted[0]), int(counted[1]))
            self._set_accumulator_cover = (int(revision), covered[0], covered[1])
            accelerators.execute(
                "INSERT OR REPLACE INTO set_accumulators"
                "(revision, rows, newest, accumulator) VALUES(?, ?, ?, ?)",
                (
                    int(revision), int(covered[0]), int(covered[1]),
                    accumulator.to_bytes(SET_HASH_BYTES, "big"),
                ),
            )
        except sqlite3.Error:
            pass

    def set_accumulator_after(
        self,
        base: Snapshot,
        *,
        create: Iterable[Cell],
        replace: Iterable[Cell],
        blank_atom_roots: Iterable[str] = (),
    ) -> int:
        """The accumulator a commit of these cells over 'base' would have.

        'blank_atom_roots' name cells whose atom is taken as empty for the
        purpose of the digest -- the head's own digest and signature
        payloads, which cannot contain themselves.
        """
        from .cell_set_digest import (
            accumulator_add, accumulator_remove,
        )
        blank = frozenset(blank_atom_roots)
        created = tuple(create)
        replaced = tuple(replace)
        accumulator = self.set_accumulator(base)
        accumulator = accumulator_remove(
            accumulator, (base.cells[cell.id] for cell in replaced)
        )
        return accumulator_add(
            accumulator,
            (
                Cell(cell.id, cell.link0, cell.link1, b"")
                if cell.id in blank else cell
                for cell in (*created, *replaced)
            ),
        )

    def fingerprint(
        self,
        root_id: str,
        *,
        budget: int = 100_000,
        excluded_roots: Iterable[str] = (),
    ) -> str:
        """Hash one reachable cell region without interpreting terminal data."""
        if budget < 1:
            raise MatchBudgetExceeded("fingerprint budget must be positive")
        with self._lock:
            excluded = frozenset(excluded_roots)
            if any(
                not isinstance(root, str) or not root
                for root in excluded
            ):
                raise InvalidCell("fingerprint exclusion root is invalid")
            if root_id in excluded:
                raise InvalidCell("fingerprint root cannot exclude itself")
            cache_key = (root_id, excluded)
            cached = self._fingerprints.get(cache_key)
            if cached is not None:
                return cached
            if root_id not in self._cells:
                raise InvalidCell("fingerprint root is missing")

            reachable: set[str] = set()
            pending = [root_id]
            steps = 0
            while pending:
                cell_id = pending.pop()
                if cell_id in reachable or cell_id in excluded:
                    continue
                steps += 1
                if steps > budget:
                    raise MatchBudgetExceeded(
                        "fingerprint exceeded %s reachable cells" % budget
                    )
                cell = self._cells[cell_id]
                reachable.add(cell_id)
                pending.append(cell.link0)
                pending.append(cell.link1)

            digest = hashlib.blake2b(digest_size=32)

            def add_field(data: bytes) -> None:
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)

            for cell_id in sorted(reachable):
                cell = self._cells[cell_id]
                add_field(cell.id.encode("utf-8"))
                add_field(cell.link0.encode("utf-8"))
                add_field(cell.link1.encode("utf-8"))
                add_field(cell.atom)

            value = digest.hexdigest()
            self._fingerprints[cache_key] = value
            self._fingerprint_dependencies[cache_key] = frozenset(reachable)
            self._fingerprint_compute_counts[cache_key] = (
                self._fingerprint_compute_counts.get(cache_key, 0) + 1
            )
            return value

    def fingerprint_computes(self, root_id: str) -> int:
        with self._lock:
            return sum(
                count
                for (candidate, _excluded), count
                in self._fingerprint_compute_counts.items()
                if candidate == root_id
            )

    def match(
        self,
        pattern: Mapping[str, Cell],
        *,
        pattern_root: str,
        target_root: str,
        variables: Iterable[str] = (),
        budget: int = 10_000,
        revision: int | None = None,
    ) -> dict[str, str]:
        """Unify a cell graph with a target graph using explicit variables.

        Atom bytes are tested only for exact opaque equality. They are never
        decoded or interpreted. The matcher knows graph structure, the null
        identity, and which pattern identities the caller supplied as
        variables; it knows no protocol or product vocabulary.
        """
        if budget < 1:
            raise MatchBudgetExceeded("match budget must be positive")
        variable_ids = frozenset(variables)
        with self._lock:
            stored_pattern = pattern is self._cells
            pattern_cells = pattern if stored_pattern else dict(pattern)
            if not stored_pattern:
                for cell in pattern_cells.values():
                    _validate_cell(cell)
            if pattern_root not in pattern_cells:
                raise InvalidCell("pattern root is missing")
            if NULL_CELL_ID not in pattern_cells:
                raise InvalidCell(
                    "pattern must contain the distinguished null cell"
                )
            if not all(root_id in pattern_cells for root_id in variable_ids):
                raise InvalidCell("every match variable must be a pattern cell")
            if NULL_CELL_ID in variable_ids:
                raise InvalidCell(
                    "the distinguished null cell cannot be a variable"
                )
            if not stored_pattern:
                for cell in pattern_cells.values():
                    if cell.id in variable_ids:
                        continue
                    if (
                        cell.link0 not in pattern_cells
                        or cell.link1 not in pattern_cells
                    ):
                        raise InvalidCell(
                            "pattern cell %r has a dangling link" % cell.id
                        )
            target_cells = self._cells if revision is None else self.at(revision).cells
            if target_root not in target_cells:
                raise NoMatch("target root is missing")

            bindings: dict[str, str] = {}
            concrete: dict[str, str] = {}
            pending = [(pattern_root, target_root)]
            steps = 0

            while pending:
                steps += 1
                if steps > budget:
                    raise MatchBudgetExceeded(
                        "graph match exceeded %s visited pairs" % budget
                    )
                pattern_id, target_id = pending.pop()

                if pattern_id in variable_ids:
                    previous = bindings.get(pattern_id)
                    if previous is not None and previous != target_id:
                        raise NoMatch("one variable matched two target cells")
                    bindings[pattern_id] = target_id
                    continue

                previous = concrete.get(pattern_id)
                if previous is not None:
                    if previous != target_id:
                        raise NoMatch("shared pattern structure was not preserved")
                    continue

                if pattern_id == NULL_CELL_ID:
                    if target_id != NULL_CELL_ID:
                        raise NoMatch("null incidence did not match")
                    concrete[pattern_id] = target_id
                    continue

                target_cell = target_cells.get(target_id)
                if target_cell is None:
                    raise NoMatch("target incidence is missing")
                pattern_cell = pattern_cells[pattern_id]
                if not hmac.compare_digest(pattern_cell.atom, target_cell.atom):
                    raise NoMatch("opaque terminal atoms differ")

                concrete[pattern_id] = target_id
                pending.append((pattern_cell.link0, target_cell.link0))
                pending.append((pattern_cell.link1, target_cell.link1))

            return bindings

    def _prepare_rewrite_locked(
        self,
        *,
        expected_revision: int,
        pattern_root: str,
        target_root: str,
        pattern_variables: Iterable[str],
        replacement_root: str,
        replacement_variables: Mapping[str, str],
        replacement_constants: Mapping[str, str] | None = None,
        budget: int = 10_000,
    ) -> PreparedRewrite:
        """Match one stored graph and materialize an unpublished replacement.

        Both sides of the rule are ordinary cells already in this store. The
        caller explicitly maps replacement placeholders to pattern variables.
        All other replacement cells are copied to fresh identities, except the
        replacement root, which preserves the target root's stable identity.
        """
        pattern_variable_ids = frozenset(pattern_variables)
        replacement_variable_map = dict(replacement_variables)
        replacement_constant_map = dict(replacement_constants or {})
        if expected_revision != self._revision:
            raise Conflict(
                "expected revision %s, current revision is %s"
                % (expected_revision, self._revision)
            )
        if target_root == NULL_CELL_ID:
            raise InvalidCell("the distinguished null cell cannot be rewritten")
        if replacement_root in replacement_variable_map:
            raise InvalidCell("replacement root cannot be a variable")
        if replacement_root in replacement_constant_map:
            raise InvalidCell("replacement root cannot be a constant binding")
        if set(replacement_variable_map).intersection(replacement_constant_map):
            raise InvalidCell("replacement placeholder has conflicting bindings")
        if not set(replacement_variable_map.values()).issubset(pattern_variable_ids):
            raise InvalidCell(
                "replacement variables must map to declared pattern variables"
            )
        if not all(root_id in self._cells for root_id in replacement_variable_map):
            raise InvalidCell("replacement variable cell is missing")
        if not all(root_id in self._cells for root_id in replacement_constant_map):
            raise InvalidCell("replacement constant placeholder is missing")
        if not all(
            root_id in self._cells for root_id in replacement_constant_map.values()
        ):
            raise InvalidCell("replacement constant target is missing")
        if replacement_root not in self._cells:
            raise InvalidCell("replacement root is missing")

        bindings = self.match(
            self._cells,
            pattern_root=pattern_root,
            target_root=target_root,
            variables=pattern_variable_ids,
            budget=budget,
            revision=expected_revision,
        )

        concrete_templates: set[str] = set()
        pending = [replacement_root]
        steps = 0
        while pending:
            steps += 1
            if steps > budget:
                raise MatchBudgetExceeded(
                    "replacement traversal exceeded %s cells" % budget
                )
            template_id = pending.pop()
            if (
                template_id == NULL_CELL_ID
                or template_id in replacement_variable_map
                or template_id in replacement_constant_map
                or template_id in concrete_templates
            ):
                continue
            template = self._cells.get(template_id)
            if template is None:
                raise InvalidCell("replacement contains a dangling link")
            concrete_templates.add(template_id)
            pending.append(template.link0)
            pending.append(template.link1)

        materialized: dict[str, str] = {replacement_root: target_root}
        occupied = {target_root}
        for template_id in sorted(concrete_templates):
            if template_id == replacement_root:
                continue
            fresh = str(uuid.uuid4())
            while fresh in self._cells or fresh in occupied:
                fresh = str(uuid.uuid4())
            occupied.add(fresh)
            materialized[template_id] = fresh

        def translated(template_id: str) -> str:
            if template_id == NULL_CELL_ID:
                return NULL_CELL_ID
            pattern_variable = replacement_variable_map.get(template_id)
            if pattern_variable is not None:
                return bindings[pattern_variable]
            constant_root = replacement_constant_map.get(template_id)
            if constant_root is not None:
                return constant_root
            try:
                return materialized[template_id]
            except KeyError as exc:
                raise InvalidCell(
                    "replacement reference was not materialized"
                ) from exc

        created: list[Cell] = []
        replaced: list[Cell] = []
        for template_id in sorted(concrete_templates):
            template = self._cells[template_id]
            instance = Cell(
                materialized[template_id],
                translated(template.link0),
                translated(template.link1),
                template.atom,
            )
            if template_id == replacement_root:
                replaced.append(instance)
            else:
                created.append(instance)

        return PreparedRewrite(
            root_id=target_root,
            expected_revision=expected_revision,
            create=tuple(created),
            replace=tuple(replaced),
            bindings=MappingProxyType(dict(bindings)),
            materialized=MappingProxyType(dict(materialized)),
        )

    def prepare_rewrite(
        self,
        *,
        expected_revision: int,
        pattern_root: str,
        target_root: str,
        pattern_variables: Iterable[str],
        replacement_root: str,
        replacement_variables: Mapping[str, str],
        replacement_constants: Mapping[str, str] | None = None,
        budget: int = 10_000,
    ) -> PreparedRewrite:
        """Materialize a rewrite without publishing it, for one atomic set."""
        with self._lock:
            return self._prepare_rewrite_locked(
                expected_revision=expected_revision,
                pattern_root=pattern_root,
                target_root=target_root,
                pattern_variables=pattern_variables,
                replacement_root=replacement_root,
                replacement_variables=replacement_variables,
                replacement_constants=replacement_constants,
                budget=budget,
            )

    def rewrite(
        self,
        *,
        expected_revision: int,
        pattern_root: str,
        target_root: str,
        pattern_variables: Iterable[str],
        replacement_root: str,
        replacement_variables: Mapping[str, str],
        replacement_constants: Mapping[str, str] | None = None,
        budget: int = 10_000,
    ) -> RewriteResult:
        """Match one stored graph and atomically publish its replacement."""
        with self._lock:
            prepared = self._prepare_rewrite_locked(
                expected_revision=expected_revision,
                pattern_root=pattern_root,
                target_root=target_root,
                pattern_variables=pattern_variables,
                replacement_root=replacement_root,
                replacement_variables=replacement_variables,
                replacement_constants=replacement_constants,
                budget=budget,
            )
            revision = self.commit(
                expected_revision,
                create=prepared.create,
                replace=prepared.replace,
            )
            return RewriteResult(
                root_id=target_root,
                revision=revision,
                bindings=prepared.bindings,
                materialized=prepared.materialized,
            )


def migrate_cell_history(
    source: CellStore,
    destination: CellStore,
) -> CellHistoryMigrationEvidence:
    """Copy one quiesced Cell history and prove exact revision equivalence.

    The destination is never promoted here. Callers must keep the source
    write-frozen, inspect this evidence, run provider restore courts, and only
    then change the runtime authority pointer.
    """
    if source.authority_identity == destination.authority_identity:
        raise InvalidCell("Cell migration requires distinct authorities")
    if destination.revision != 0 or set(destination.snapshot().cells) != {
        NULL_CELL_ID
    }:
        raise InvalidCell("Cell migration destination must be at genesis")

    source_revision = source.revision
    source_digest = source.revision_chain_digest(source_revision)
    for revision in range(1, source_revision + 1):
        changed_ids = source.revision_changes(revision)
        changed = source.cells_at(revision, changed_ids)
        destination_snapshot = destination.snapshot()
        create = tuple(
            changed[cell_id]
            for cell_id in changed_ids
            if cell_id not in destination_snapshot.cells
        )
        replace = tuple(
            changed[cell_id]
            for cell_id in changed_ids
            if cell_id in destination_snapshot.cells
        )
        destination.commit(
            destination_snapshot.revision,
            create=create,
            replace=replace,
        )

    if source.revision != source_revision:
        raise Conflict("Cell migration source changed during history copy")
    destination_digest = destination.revision_chain_digest()
    if (
        destination.revision != source_revision
        or destination_digest != source_digest
    ):
        raise InvalidCell("Cell migration history proof does not match")
    return CellHistoryMigrationEvidence(
        source_identity=source.authority_identity,
        destination_identity=destination.authority_identity,
        source_revision=source_revision,
        destination_revision=destination.revision,
        revision_chain_digest=source_digest,
    )


__all__ = [
    "NULL_CELL_ID",
    "Cell",
    "Snapshot",
    "ReadOnlyJournalRevision",
    "RewriteResult",
    "PreparedRewrite",
    "CommitEvent",
    "CellHistoryMigrationEvidence",
    "CellJournal",
    "CellHistoryReader",
    "LoadedJournalHead",
    "RuntimeFenceLease",
    "InterprocessOwnerFence",
    "CellStore",
    "CellKernelError",
    "Conflict",
    "InvalidCell",
    "ReadOnlyJournalError",
    "NoMatch",
    "MatchBudgetExceeded",
    "dense_read_snapshot",
    "overlay_read_snapshot",
    "inspect_read_only_cell_journal",
    "load_bounded_read_only_cell_snapshot",
    "read_only_revision_chain_digest",
    "revision_chain_digest_step",
    "migrate_cell_history",
]
